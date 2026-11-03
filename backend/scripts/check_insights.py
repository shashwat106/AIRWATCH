"""Print the insight wording each city gets, as a sanity check."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app import service  # noqa: E402
from app.config import CITIES  # noqa: E402


async def main() -> None:
    for city in CITIES.values():
        i = await service.city_insights(city)
        f = await service.city_forecast(city)
        lev, out, rel, lim = i["levers"], i["outlook"], i["relief"], i["limits"]
        print(f"== {city.name}")
        print("  outlook:", out and (out["summary"], "ahead" if out["ahead"] else "not ahead"))
        print("  levers:", lev and (lev["still_pm"], lev["still_days"], lev["windy_pm"], lev["windy_days"]))
        print("  rain:", lev and lev["rain"] and lev["rain"]["summary"])
        print("  relief:", rel and rel["summary"], [(d["date"][5:], d["wind_kmh"], d["rain_mm"], d["verdict"]) for d in (rel or {}).get("days", [])])
        print("  limits:", lim and lim["india_summary"], "|", lim and lim["who_summary"])
        print("  timing:", f["timing"] and f["timing"]["summary"])


asyncio.run(main())
