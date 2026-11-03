"""Print what the fire archive says for every city, as a sanity check."""
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
        h = await service.city_history(city)
        a, b = h["season"]["this_season"], h["season"]["last_season"]
        link = h["fire_link"]
        spread = Counter((d["cause"] or {}).get("id", "none") for d in h["calendar"])
        print(f"{city.id}: upwind fires {a['upwind_fires']} vs {b['upwind_fires']}, AQI {a['mean_aqi']} vs {b['mean_aqi']}")
        print("   link:", link.get("summary") or link.get("reason"))
        print("   lags:", link.get("lags"))
        print("   causes:", dict(spread), "crop scored", sum(d["crop_scored"] for d in h["calendar"]))
        print("   same day last year:", h["vs_years"]["earlier"][0], "| today:", h["vs_years"]["day"])


asyncio.run(main())
