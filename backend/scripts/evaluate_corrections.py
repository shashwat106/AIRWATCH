"""Test corrections on days they never saw, then fit and approve only the ones that pass. Run from anywhere.

Two tests, each training only on earlier data:
  winter:  train 1 Oct to 31 Dec 2025, test 1 Jan to 28 Feb 2026 (peak smog)
  recent:  train to 20 Oct 2026,       test 21 Oct to 3 Nov 2026 (this season's rise)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app import fetchers as f  # noqa: E402
from app.config import CITIES  # noqa: E402
from ml import calibration as cal  # noqa: E402

SPLITS = {"winter": ("2025-10-01", "2025-12-31 23:00", "2026-01-01", "2026-02-28 23:00"),
          "recent": ("2025-10-01", "2026-10-20 23:00", "2026-10-21", "2026-11-03 23:00")}


def run_split(x, real, raw, split):
    a, b, c, d = split
    both = pd.DataFrame({"real": real}).join(x, how="inner").dropna()
    train, test = both.loc[a:b], both.loc[c:d]
    if len(train) < 500 or len(test) < 100:
        return None
    cols = list(x.columns)
    lin_a, lin_b = cal.linear_fit(train.pm25, train.real)
    methods = {
        "raw": test.pm25,
        "linear": np.expm1(lin_a + lin_b * np.log1p(test.pm25)),
        "quantile": cal.quantile_map(train.pm25, train.real, test.pm25),
        "gbm": cal.predict(cal.fit(train[cols], train.real), test[cols]),
    }
    return {name: cal.score(pred, test.real) for name, pred in methods.items()}


def main() -> None:
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cities": {}}
    for city in CITIES.values():
        path = f.history_path("station", city.id)
        if not path.exists():
            print(city.id, "no station data")
            report["cities"][city.id] = {"approved": False, "reason": "No station data."}
            continue
        real = cal.station_mean(pd.read_parquet(path))
        air = pd.read_parquet(f.history_path("air", city.id))
        wx = pd.read_parquet(f.history_path("wx", city.id))
        x = cal.features(air, wx)
        print(f"== {city.id}: {len(real)} station hours, {real.index.min().date()} to {real.index.max().date()}, mean {real.mean():.0f}, top1% {real.quantile(.99):.0f}")
        results = {}
        for name, split in SPLITS.items():
            res = run_split(x, real, air["pm2_5"], split)
            if res is None:
                print("  ", name, "not enough hours")
                continue
            results[name] = res
            for method, s in res.items():
                print(f"   {name:7}{method:9} MAE {s['mae']:6.1f} bias {s['bias']:7.1f} | worst {s['worst_pred']:4d} vs {s['worst_real']:4d} (MAE {s['worst_mae']:6.1f}) | days {s['days']:3d}: same {s['same_category_days']:3d} under {s['under_warn_days']:3d} over {s['over_warn_days']:3d}")
        report["cities"][city.id] = {"results": results}
    Path(cal.REPORT_PATH).with_suffix(".draft.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


main()
