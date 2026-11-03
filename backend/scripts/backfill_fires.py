"""Fetch the FIRMS fire archive for each season so far. Needs FIRMS_MAP_KEY in backend/.env.

One satellite (Suomi NPP) is used for every year so that yearly counts compare fairly. Standard
processing (SP) is tried first, and the near-real-time feed (NRT) fills the months SP has not
reached. Written to data/history/fires_<season>.parquet with the product used in a `product` column.

NOT YET RUN: no key was available when this was written. Check its output before trusting it.
"""
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app.config import FIRMS_MAP_KEY, HISTORY_DIR  # noqa: E402
from ml.history import same_date_in_year, season_start  # noqa: E402

CHUNK_DAYS = 5
PRODUCTS = ("VIIRS_SNPP_SP", "VIIRS_SNPP_NRT")


async def chunk(start: date, days: int) -> pd.DataFrame:
    for product in PRODUCTS:
        try:
            frame = await f.fires_archive_chunk(product, start, days)
        except RuntimeError as exc:
            print("  ", product, start, "failed:", exc, flush=True)
            continue
        if len(frame):
            frame["product"] = product
            return frame
    return pd.DataFrame()


async def season(first: date, last: date) -> None:
    frames, day = [], first
    while day <= last:
        days = min(CHUNK_DAYS, (last - day).days + 1)
        frames.append(await chunk(day, days))
        print(day, days, len(frames[-1]), flush=True)
        day += timedelta(days=days)
    merged = pd.concat([x for x in frames if len(x)], ignore_index=True)
    merged.to_parquet(HISTORY_DIR / f"fires_{first.year}.parquet")
    print("season", first.year, len(merged), merged.time.min(), merged.time.max(), flush=True)


async def main() -> None:
    if not FIRMS_MAP_KEY:
        sys.exit("FIRMS_MAP_KEY is not set in backend/.env")
    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    start = season_start(today)
    for back in (0, 1, 2):
        # This season starts earlier so the forecast can train on fires across its full 60 days.
        first = date(start.year, 8, 25) if back == 0 else date(start.year - back, 10, 1)
        await season(first, same_date_in_year(today, today.year - back))


asyncio.run(main())
