"""Replay the station warning on past days, and give the one fixed correction its fair test.

The correction (48-hour recent gap, 18-hour lag, full strength) was fixed before these cities were
tested. A city must pass both tests to use it. Run from anywhere.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app import fetchers as f  # noqa: E402
from app.config import CITIES  # noqa: E402
from ml import calibration as cal  # noqa: E402
from ml import warning as w  # noqa: E402

SPLITS = {"winter": ("2026-01-01", "2026-02-28 23:00"), "recent": ("2026-10-21", "2026-11-03 23:00")}


def gap(model, real, window=48, lag=18):
    r = real.reindex(model.index)
    top = r.rolling(window, min_periods=window // 2).mean().shift(lag)
    bottom = model.where(r.notna()).rolling(window, min_periods=window // 2).mean().shift(lag)
    return model * (top / bottom).clip(0.4, 3.0).fillna(1.0)


total = {"days": 0, "fired": 0, "fired_right": 0, "under_before": 0, "under_after": 0, "over_before": 0, "over_after": 0}
for city in CITIES.values():
    path = f.history_path("station", city.id)
    if not path.exists():
        print(city.id, "no stations")
        continue
    table = pd.read_parquet(path)
    real = cal.station_mean(table)
    model = pd.read_parquet(f.history_path("air", city.id))["pm2_5"]
    aqi = pd.to_numeric(pd.read_parquet(f.history_path("aqi", city.id))["aqi"], errors="coerce")
    res = w.backtest(aqi, real)
    print(f"{city.id}: {len(real)} station hours from {real.index.min().date()}")
    if res:
        print("   warning:", res)
        for key in total:
            total[key] += res[key]
    passed = []
    for name, (a, b) in SPLITS.items():
        test = real.loc[a:b]
        if len(test) < 100:
            print("   correction", name, "not enough hours")
            passed.append(False)
            continue
        raw, fixed = cal.score(model, test), cal.score(gap(model, real), test)
        ok = cal.passes_test(raw, fixed)
        passed.append(ok)
        print(f"   correction {name}: MAE {raw['mae']} -> {fixed['mae']}, worst MAE {raw['worst_mae']} -> {fixed['worst_mae']}, "
              f"under {raw['under_warn_days']} -> {fixed['under_warn_days']}, over {raw['over_warn_days']} -> {fixed['over_warn_days']}, pass {ok}")
    print("   correction verdict:", "PASSES BOTH" if all(passed) else "does not pass")
print("ALL CITIES warning:", total)
