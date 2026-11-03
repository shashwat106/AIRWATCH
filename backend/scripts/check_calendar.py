"""Print how the season calendar's causes are spread across each city, as a sanity check."""
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app import service  # noqa: E402
from app.config import CITIES  # noqa: E402


async def main() -> None:
    for city in CITIES.values():
        data = await service.city_history(city)
        spread = Counter((d["cause"] or {}).get("id", "none") for d in data["calendar"])
        print(city.id, dict(spread))
        if city.id == "delhi":
            for day in data["calendar"][2:6]:
                print("  ", day["date"], day["aqi"], day["dominant"], day["cause"])
            print("   worst:", data["notable"]["this_season"][0])


asyncio.run(main())
