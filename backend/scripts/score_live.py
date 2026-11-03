"""Score stored forecasts on hours that have since passed, and choose what each city serves.

Open-Meteo is judged against its own later series, which favours it, so our model must clearly earn
its place. Nothing is claimed below MIN_SNAPSHOT_HOURS.
"""
import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app import service  # noqa: E402
from app.config import CITIES  # noqa: E402
from ml import forecast as fc  # noqa: E402


def load(city_id: str, pattern: str, prefix: str = "") -> dict:
    out = {}
    for path in (f.SNAPSHOT_DIR / city_id).glob(pattern):
        stamp = path.stem.removeprefix(prefix)
        utc = pd.to_datetime(stamp, format="%Y%m%dT%H%MZ", utc=True)
        out[utc.tz_convert("Asia/Kolkata").tz_localize(None)] = pd.read_parquet(path)
    return out


async def main() -> None:
    metrics = fc.load_metrics()
    now = service.now_ist().floor("h")
    for city in CITIES.values():
        air, _, _ = await service.frames(city)
        truth = air["pm2_5"].loc[:now]
        om = fc.score_snapshots(load(city.id, "[0-9]*.parquet"), truth, "pm2_5", now)
        ours = fc.score_snapshots(load(city.id, "ours_*.parquet", "ours_"), truth, "pm2_5", now)
        served, reason = fc.decide(ours, om)
        entry = metrics["cities"][city.id]
        entry.update({"open_meteo_live": om, "ours_live": ours, "served": served, "served_reason": reason})
        print(city.id, "open-meteo", om, "ours", ours, "->", served, flush=True)
    fc.save_metrics(metrics)


asyncio.run(main())
