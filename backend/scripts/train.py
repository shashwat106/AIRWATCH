"""Evaluate and train the forecast for every city, then write ml/metrics.json. Run from anywhere."""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app import service  # noqa: E402
from app.config import CITIES  # noqa: E402
from ml import forecast as fc  # noqa: E402


async def main() -> None:
    cities = {}
    fires = service.archive_fires()
    print("fire archive rows:", None if fires is None else len(fires), flush=True)
    for city in CITIES.values():
        air = pd.read_parquet(f.history_path("air", city.id))
        blh = pd.read_parquet(f.history_path("wx", city.id))["boundary_layer_height"]
        wxf = await f.weather_previous_runs(city)
        wxf.to_parquet(f.history_path("wxf", city.id))
        res = fc.evaluate_city(air, wxf, blh)
        series = None
        if fires is not None:
            wx = pd.read_parquet(f.history_path("wx", city.id))
            times = pd.date_range(air.index.max() - pd.Timedelta(days=70), air.index.max(), freq="3h").floor("3h")
            series = fc.fire_series(fires, city.lat, city.lon, wx, times)
            with_fires = fc.evaluate_city(air, wxf, blh, series)
            res["ours_without_fires"] = res["ours"]
            res["ours_with_fires"] = with_fires["ours"]
            res["uses_fire_feature"] = with_fires["ours"]["mae"] < res["ours"]["mae"]
            if res["uses_fire_feature"]:
                res["ours"] = with_fires["ours"]
            else:
                series = None
        fc.train_final(city.id, air, wxf, blh, series)
        cities[city.id] = res
        print(city.id, "ours", res["ours"], "no-fire", res.get("ours_without_fires"), "with-fire", res.get("ours_with_fires"),
              "persist", res["persistence"], "yday", res["same_hour_yesterday"], flush=True)
    fc.save_metrics({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "target": "PM2.5 (ug/m3), hourly, 1-24 h ahead",
                     "truth": "Open-Meteo past series (global model), not station measurements",
                     "cities": cities})


asyncio.run(main())
