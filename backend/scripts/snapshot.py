"""Save Open-Meteo's current forecast for every city, and report recent fires. Run from backend/."""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app import service  # noqa: E402
from app.config import CITIES  # noqa: E402


async def save_ours(city) -> None:
    """Store our own forecast at the same moment, so both are judged on the same hours."""
    air, wx, _ = await service.frames(city)
    at = service.current_hour(air)
    ours = await service.ours_forecast(city, air, wx, at)
    if ours is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
        ours.to_parquet(f.SNAPSHOT_DIR / city.id / f"ours_{stamp}.parquet")


async def main() -> None:
    for city in CITIES.values():
        df = await f.snapshot_forecast(city)
        await save_ours(city)
        print("snapshot", city.id, df.index[0], df.index[-1], int(df.pm2_5.notna().sum()))
    fires = (await f.fires_recent()).df
    print("fires", len(fires), fires.time.min(), fires.time.max(), fires.confidence.value_counts().to_dict())


asyncio.run(main())
