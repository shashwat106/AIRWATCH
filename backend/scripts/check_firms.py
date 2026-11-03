"""Check the FIRMS key and which products reach which dates. Never prints the key."""
import asyncio
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app.config import FIRMS_MAP_KEY  # noqa: E402


async def main() -> None:
    print("key loaded:", bool(FIRMS_MAP_KEY), "length", len(FIRMS_MAP_KEY))
    async with httpx.AsyncClient(timeout=30) as client:
        status = await client.get("https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/",
                                  params={"MAP_KEY": FIRMS_MAP_KEY})
    print("key status:", status.status_code, status.text[:160].replace(FIRMS_MAP_KEY, "***"))
    checks = [("VIIRS_NOAA20_NRT", date(2026, 11, 1)), ("VIIRS_SNPP_NRT", date(2026, 10, 25)),
              ("VIIRS_SNPP_NRT", date(2026, 10, 1)), ("VIIRS_SNPP_SP", date(2026, 10, 1)),
              ("VIIRS_SNPP_SP", date(2025, 10, 25)), ("VIIRS_SNPP_NRT", date(2025, 10, 25)),
              ("VIIRS_SNPP_SP", date(2024, 10, 25))]
    for product, day in checks:
        try:
            frame = await f.fires_archive_chunk(product, day, 5)
            print(product, day, "rows", len(frame), "" if frame.empty else (str(frame.time.min()), str(frame.time.max())))
        except RuntimeError as exc:
            print(product, day, "FAILED:", exc)


asyncio.run(main())
