"""Fetch history once and store it in data/history. Safe to re-run: it only asks for missing days.

Air quality starts at AQ_EARLIEST (the first day Open-Meteo returns values). Weather uses the same
range. Run from backend/.
"""
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app.config import AQ_EARLIEST, CITIES  # noqa: E402
from ml.aqi import aqi_series  # noqa: E402


async def extend(kind: str, city, fetch) -> None:
    path = f.history_path(kind, city.id)
    old = pd.read_parquet(path) if path.exists() else None
    # Re-fetch the last two stored days too, because the newest hours can be revised.
    start = AQ_EARLIEST if old is None else (old.index.max() - pd.Timedelta(days=2)).date().isoformat()
    end = (pd.Timestamp.now(tz="Asia/Kolkata").date() - timedelta(days=1)).isoformat()
    new = await fetch(city, start, end)
    new = new.dropna(how="all")
    merged = new if old is None else pd.concat([old[old.index < new.index.min()], new])
    merged.to_parquet(path)
    print(kind, city.id, merged.index.min(), merged.index.max(), len(merged), flush=True)


async def main() -> None:
    for city in CITIES.values():
        await extend("air", city, f.air_range)
        await extend("wx", city, f.weather_archive)
        aqi_series(pd.read_parquet(f.history_path("air", city.id))).to_parquet(f.history_path("aqi", city.id))


asyncio.run(main())
