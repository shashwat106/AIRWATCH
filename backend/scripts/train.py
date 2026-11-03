"""Evaluate and train the forecast for every city, then write ml/metrics.json. Run from anywhere."""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app.config import CITIES  # noqa: E402
from ml import forecast as fc  # noqa: E402


async def main() -> None:
    cities = {}
    for city in CITIES.values():
        air = pd.read_parquet(f.history_path("air", city.id))
        blh = pd.read_parquet(f.history_path("wx", city.id))["boundary_layer_height"]
        wxf = await f.weather_previous_runs(city)
        wxf.to_parquet(f.history_path("wxf", city.id))
        res = fc.evaluate_city(air, wxf, blh)
        fc.train_final(city.id, air, wxf, blh)
        cities[city.id] = res
        print(city.id, "ours", res["ours"], "persist", res["persistence"], "yday", res["same_hour_yesterday"], flush=True)
    fc.save_metrics({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "target": "PM2.5 (ug/m3), hourly, 1-24 h ahead",
                     "truth": "Open-Meteo past series (global model), not station measurements",
                     "cities": cities})


asyncio.run(main())
