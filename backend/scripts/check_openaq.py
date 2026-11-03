"""See what OpenAQ offers near each city: who runs the stations, how fresh they are, what they read.
Never prints the key."""
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import CITIES  # noqa: E402,F401  (also loads backend/.env)

KEY = os.getenv("OPENAQ_API_KEY", "").strip()
BASE = "https://api.openaq.org/v3"


async def main() -> None:
    print("key loaded:", bool(KEY), "length", len(KEY))
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=40, headers={"X-API-Key": KEY}) as client:
        for city in CITIES.values():
            r = await client.get(f"{BASE}/locations", params={"coordinates": f"{city.lat},{city.lon}", "radius": 25000, "limit": 100})
            if r.status_code != 200:
                print(city.id, "HTTP", r.status_code, r.text[:120])
                continue
            rows = r.json()["results"]
            fresh = []
            for loc in rows:
                last = (loc.get("datetimeLast") or {}).get("utc")
                if last and now - datetime.fromisoformat(last.replace("Z", "+00:00")) < timedelta(hours=6):
                    fresh.append(loc)
            monitors = [x for x in fresh if x.get("isMonitor")]
            pm = [x for x in monitors if any(s["parameter"]["name"] == "pm25" for s in x["sensors"])]
            owners = Counter((x.get("owner") or {}).get("name", "?") for x in monitors)
            providers = Counter((x.get("provider") or {}).get("name", "?") for x in monitors)
            print(f"{city.id}: {len(rows)} locations, {len(fresh)} fresh, {len(monitors)} fresh monitors, {len(pm)} with PM2.5")
            print("   providers:", dict(providers), "| owners:", dict(owners))
            values = []
            for loc in pm[:6]:
                sensor = next(s for s in loc["sensors"] if s["parameter"]["name"] == "pm25")
                latest = await client.get(f"{BASE}/locations/{loc['id']}/latest")
                for item in latest.json().get("results", []):
                    if item["sensorsId"] == sensor["id"]:
                        values.append(item["value"])
                        print("   ", loc["name"][:42], "PM2.5", item["value"], sensor["parameter"]["units"], item["datetime"]["local"][:16])
                await asyncio.sleep(1.1)
            if values:
                print("   mean of shown:", round(sum(values) / len(values), 1))
            await asyncio.sleep(1.1)


asyncio.run(main())
