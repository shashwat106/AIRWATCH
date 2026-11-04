"""Work out the slow, history-only results here, so a small free server only has to read them.

Writes daily tables, daily upwind fires, the season calendar and notable days to data/history.
Re-run after backfill.py or backfill_fires.py. Run from anywhere.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import fetchers as f  # noqa: E402
from app import service  # noqa: E402
from app.config import CITIES  # noqa: E402
from ml import history as hist  # noqa: E402


async def main() -> None:
    fires_recent, _ = await service.fire_frame()
    for city in CITIES.values():
        air, wx = service.stored("air", city.id), service.stored("wx", city.id)
        last_full = air.index.max().date()
        stamp = str(last_full)
        table = hist.daily_table(air, service.stored_aqi(city.id)["aqi"])
        table.to_parquet(f.history_path("daily", city.id))
        service._daily.cache_clear()
        upwind = service._fires_daily(city.id, stamp)
        if upwind is not None:
            upwind.rename("upwind").to_frame().to_parquet(f.history_path("upwind", city.id))
        this_season, last_season = hist.season_windows(last_full)
        fires = service.archive_fires()
        derived = {"last_full": stamp, "calendar": service.season_calendar(city, air, wx, last_full, fires_recent),
                   "notable": {"this_season": service.notable(city, air, wx, this_season, fires),
                               "last_season": service.notable(city, air, wx, last_season, fires)}}
        service.derived_path(city.id).write_text(json.dumps(service.clean(derived)), encoding="utf-8")
        print(city.id, "done", flush=True)


asyncio.run(main())
