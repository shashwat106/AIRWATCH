"""Fetch a year of hourly PM2.5 from the nearest CPCB stations, through OpenAQ, for each city.

Stored in data/history/station_<city>.parquet with one row per station-hour, then compared with the
model. Delhi also gets the AirNow New Delhi monitor. Never prints the key.
"""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app import fetchers as f  # noqa: E402
from app.config import CITIES, HISTORY_DIR  # noqa: E402

KEY = os.getenv("OPENAQ_API_KEY", "").strip()
BASE = "https://api.openaq.org/v3"
START = "2025-10-01"
END = "2026-11-30"
RECENT = "2026-11-01"
PER_CITY = 3


def pm_sensor(loc: dict) -> dict | None:
    return next((s for s in loc["sensors"] if s["parameter"]["name"] == "pm25"), None)


async def hours(client: httpx.AsyncClient, sensor: int) -> list[dict]:
    """A year of hours in month-sized requests. Long ranges time out at OpenAQ."""
    rows = []
    starts = pd.date_range(START, END, freq="MS", tz="UTC")
    for first in starts:
        last = first + pd.offsets.MonthBegin(1)
        for attempt in range(3):
            r = await client.get(f"{BASE}/sensors/{sensor}/hours", params={
                "datetime_from": first.strftime("%Y-%m-%dT%H:%M:%SZ"), "datetime_to": last.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 1000})
            await asyncio.sleep(1.1)
            if r.status_code == 200:
                rows += [{"utc": x["period"]["datetimeFrom"]["utc"], "pm2_5": x["value"]} for x in r.json()["results"]]
                break
            if attempt == 2:
                print("   gave up on", first.date(), "HTTP", r.status_code, flush=True)
    return rows


async def main() -> None:
    async with httpx.AsyncClient(timeout=90, headers={"X-API-Key": KEY}) as client:
        for city in CITIES.values():
            r = await client.get(f"{BASE}/locations", params={"coordinates": f"{city.lat},{city.lon}", "radius": 25000, "limit": 100})
            await asyncio.sleep(1.1)
            locs = [x for x in r.json()["results"] if x.get("isMonitor") and pm_sensor(x)
                    and ((x.get("datetimeLast") or {}).get("utc") or "") >= RECENT]
            cpcb = [x for x in locs if (x.get("provider") or {}).get("name") == "CPCB"]
            cpcb.sort(key=lambda x: x.get("distance") or 1e9)
            airnow = [x for x in locs if (x.get("provider") or {}).get("name") == "AirNow" and city.id == "delhi"]
            frames = []
            for loc in cpcb + airnow:
                if len(frames) >= PER_CITY and (loc.get("provider") or {}).get("name") == "CPCB":
                    continue
                sensor = pm_sensor(loc)
                rows = await hours(client, sensor["id"])
                if not rows:
                    print("  ", city.id, loc["name"][:38], "no PM2.5 hours", flush=True)
                    continue
                df = pd.DataFrame(rows)
                df["time"] = pd.to_datetime(df.utc, utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.floor("h")
                df = df[(df.pm2_5 > 0) & (df.pm2_5 < 1000)].drop_duplicates("time")
                df["station"], df["provider"] = loc["name"], loc["provider"]["name"]
                df["distance_km"] = round((loc.get("distance") or 0) / 1000, 1)
                df["sensor"], df["location"] = sensor["id"], loc["id"]
                frames.append(df.drop(columns="utc"))
                print("  ", city.id, loc["name"][:38], loc["provider"]["name"], f"{df.distance_km.iloc[0]} km", len(df), "hours, to", df.time.max(), flush=True)
            if not frames:
                print(city.id, "NO STATIONS")
                continue
            table = pd.concat(frames, ignore_index=True)
            table.to_parquet(HISTORY_DIR / f"station_{city.id}.parquet")
    print()
    for city in CITIES.values():
        path = HISTORY_DIR / f"station_{city.id}.parquet"
        if not path.exists():
            continue
        table = pd.read_parquet(path)
        cpcb = table[table.provider == "CPCB"]
        real = cpcb.groupby("time").pm2_5.mean()
        model = pd.read_parquet(f.history_path("air", city.id))["pm2_5"]
        both = pd.DataFrame({"real": real, "model": model}).dropna()
        if len(both) < 24:
            print(city.id, "too few paired hours", len(both))
            continue
        daily = both.resample("D").mean().dropna()
        print(f"{city.id}: {len(both)} h, real {both.real.mean():.0f}, model {both.model.mean():.0f}, ratio {both.real.mean() / both.model.mean():.2f}, "
              f"MAE {(both.real - both.model).abs().mean():.0f}, r hourly {both.real.corr(both.model):.2f}, r daily {daily.real.corr(daily.model):.2f}")
        if city.id == "delhi":
            hours_real = both.groupby(both.index.hour).mean().round(0)
            print("   hour real ", hours_real.real.astype(int).to_dict())
            print("   hour model", hours_real.model.astype(int).to_dict())
            print("   cleanest real", int(hours_real.real.idxmin()), "model", int(hours_real.model.idxmin()))
            air = table[table.provider == "AirNow"].set_index("time").pm2_5
            pair = pd.DataFrame({"real": air, "model": model}).dropna()
            if len(pair):
                print(f"   AirNow: {len(pair)} h, real {pair.real.mean():.0f}, model {pair.model.mean():.0f}, ratio {pair.real.mean() / pair.model.mean():.2f}, r {pair.real.corr(pair.model):.2f}, last {air.index.max()} = {air.iloc[-1]}")


asyncio.run(main())
