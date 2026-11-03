"""Builds each API payload from cached data. Nothing here invents a value: gaps stay None and carry a note."""
from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from ml import forecast as fc
from ml import history as hist
from ml.aqi import LABELS, aqi_series, category
from ml.sources import compass, mean_wind, score_hour

from . import fetchers as f
from .advice import ADVICE, DISCLAIMER
from .config import AQ_EARLIEST, CITIES, DATA_GOV_IN_KEY, FIRMS_MAP_KEY, HISTORY_DIR, City

MODEL_SOURCE = "Open-Meteo Air Quality API (CAMS global model), AQI by CPCB method"
SHARED_GRID = {"gurugram": "Noida", "noida": "Gurugram"}
SOURCE_NOTE = "Modelled, not a station reading."


def now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)


def clean(value):
    """Make a payload JSON-safe: NaN becomes None and numpy values become Python ones."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def category_payload(aqi) -> dict | None:
    cat = category(aqi)
    return {"name": cat[0], "color": cat[1]} if cat else None


@lru_cache(maxsize=16)
def stored(kind: str, city_id: str) -> pd.DataFrame:
    return pd.read_parquet(f.history_path(kind, city_id))


@lru_cache(maxsize=8)
def stored_aqi(city_id: str) -> pd.DataFrame:
    path = f.history_path("aqi", city_id)
    if path.exists():  # written by scripts/backfill.py so a cold start stays fast
        return pd.read_parquet(path)
    return aqi_series(stored("air", city_id))


def _join(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([old[old.index < new.index.min()], new])


async def frames(city: City) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """History joined to live data, including forecast hours, plus freshness details."""
    air, wx = await f.air_live(city), await f.weather_live(city)
    fetched = pd.Timestamp(air.fetched_at, unit="s", tz="UTC").tz_convert("Asia/Kolkata").tz_localize(None)
    meta = {"fetched_at": fetched.isoformat(timespec="seconds"), "stale": air.stale}
    return _join(stored("air", city.id), air.df), _join(stored("wx", city.id), wx.df), meta


def current_hour(air: pd.DataFrame) -> pd.Timestamp:
    now = now_ist().floor("h")
    return air.loc[:now, "pm2_5"].dropna().index.max()


def aqi_to(air: pd.DataFrame, city_id: str, end: pd.Timestamp) -> pd.DataFrame:
    """AQI up to `end`: stored values, then only the recent hours recalculated."""
    old = stored_aqi(city_id)
    recent = aqi_series(air.loc[end - pd.Timedelta(hours=96):end]).iloc[48:]
    return pd.concat([old[old.index < recent.index.min()], recent])


def official_stations(frame: pd.DataFrame) -> list[dict]:
    """Group data.gov.in rows by station. Station AQI uses CPCB's method on the feed's averages."""
    from ml.aqi import overall, sub_index
    names = {"PM2.5": "pm2_5", "PM10": "pm10", "NO2": "no2", "SO2": "so2", "OZONE": "o3", "CO": "co"}
    out = []
    value_col = "avg_value" if "avg_value" in frame.columns else "pollutant_avg"
    for station, rows in frame.groupby("station"):
        subs = {}
        for _, row in rows.iterrows():
            key = names.get(str(row.get("pollutant_id", "")).upper())
            value = pd.to_numeric(row.get(value_col), errors="coerce")
            if key and not pd.isna(value):
                # UNVERIFIED: this assumes the feed gives concentrations. It has not been tested against
                # a live response, because no key was available when this was written.
                subs[key] = sub_index(key, float(value))
        res = overall(subs)
        out.append({"station": station, "aqi": res.aqi, "dominant": LABELS.get(res.dominant),
                    "category": category_payload(res.aqi), "last_update": rows.iloc[0].get("last_update")})
    return sorted(out, key=lambda s: (s["aqi"] is None, -(s["aqi"] or 0)))


async def official(city: City) -> dict:
    if not DATA_GOV_IN_KEY:
        return {"available": False, "message": "Official feed unavailable: no data.gov.in key set.", "stations": []}
    try:
        res = await f.cpcb_stations(city)
    except Exception:
        return {"available": False, "message": "Official feed unavailable right now.", "stations": []}
    if res.df.empty:
        return {"available": False, "message": "Official feed returned no stations for this city.", "stations": []}
    return {"available": True, "message": None, "stations": official_stations(res.df),
            "source": "CPCB real-time feed via data.gov.in", "stale": res.stale}


async def city_now(city: City) -> dict:
    air, _, meta = await frames(city)
    at = current_hour(air)
    series = aqi_to(air, city.id, at)
    row = series.loc[at]
    aqi = None if pd.isna(row.aqi) else int(row.aqi)
    cat = category_payload(aqi)
    latest = air.loc[at]
    return clean({
        "city": city.name, "time": at.isoformat(), "aqi": aqi, "category": cat,
        "dominant": LABELS.get(row.dominant), "pm2_5": latest["pm2_5"], "pm10": latest["pm10"],
        "unit": "µg/m³", "source": MODEL_SOURCE, "source_note": SOURCE_NOTE,
        "shared_grid_with": SHARED_GRID.get(city.id), "official": await official(city),
        "advice": ADVICE.get(cat["name"], []) if cat else [], "advice_note": DISCLAIMER, **meta,
    })


async def city_forecast(city: City) -> dict:
    air, wx, meta = await frames(city)
    at = current_hour(air)
    hours = pd.date_range(at + pd.Timedelta(hours=1), periods=fc.HORIZON, freq="h")
    baseline = air.reindex(hours)
    ours = fc.run_models(city.id, air.loc[:at], wx, wx["boundary_layer_height"], at)
    metrics = fc.load_metrics().get("cities", {}).get(city.id, {})
    served = metrics.get("served", "open_meteo")
    reason = metrics.get("served_reason", "Not enough live forecast hours yet to show our model beats Open-Meteo.")
    if ours is None:
        served, reason = "open_meteo", "Our model is not trained for this city."
    chosen = ours if served == "ours" else baseline[["pm2_5", "pm10"]]
    future = air.copy()
    future.loc[hours, ["pm2_5", "pm10"]] = chosen[["pm2_5", "pm10"]].values
    aqi = aqi_series(future.loc[at - pd.Timedelta(hours=48):hours[-1]])["aqi"].reindex(hours)
    index = pd.Series([fc.hourly_index(a, b) for a, b in zip(chosen.pm2_5, chosen.pm10)], index=hours, dtype=float)
    rows = [{"time": t.isoformat(), "pm2_5": chosen.pm2_5[t], "pm10": chosen.pm10[t], "aqi": aqi[t], "hourly_index": index[t],
             "open_meteo_pm2_5": baseline.pm2_5[t], "ours_pm2_5": None if ours is None else ours.pm2_5[t]} for t in hours]
    best = fc.best_window(index)
    if best:
        best["category"] = category_payload(best["mean_index"])
    return clean({
        "city": city.name, "issued": at.isoformat(), "served": served, "served_reason": reason, "hours": rows,
        "best_time": best, "best_time_note": "Ranked on hourly PM2.5 and PM10, not the 24-hour official AQI.",
        "metrics": metrics, "source": "Open-Meteo" if served == "open_meteo" else "the AirWatch model", **meta,
    })


async def fire_frame() -> tuple[pd.DataFrame | None, dict]:
    try:
        res = await f.fires_recent()
    except Exception:
        return None, {"available": False, "note": "Fire data unavailable right now."}
    source = "NASA FIRMS area API" if FIRMS_MAP_KEY else "NASA FIRMS public 7-day files"
    return res.df, {"available": True, "stale": res.stale, "source": f"{source}, VIIRS (3 satellites)",
                    "note": "Counts are satellite detections. One fire can be seen on several passes.",
                    "from": res.df.time.min().isoformat(), "to": res.df.time.max().isoformat()}


async def city_sources(city: City) -> dict:
    air, wx, meta = await frames(city)
    at = current_hour(air)
    frame = air.loc[at - pd.Timedelta(hours=72):at].join(wx, how="left")
    fires, fire_meta = await fire_frame()
    return clean({
        "city": city.name, "time": at.isoformat(), "sources": score_hour(frame, at, city.lat, city.lon, fires, air),
        "fires": fire_meta, "note": "Estimates from rules, not measurements. Scores are separate and do not add up to 100%.",
        **meta,
    })


def archive_fires() -> pd.DataFrame | None:
    files = sorted(HISTORY_DIR.glob("fires_*.parquet"))
    return pd.concat([pd.read_parquet(p) for p in files], ignore_index=True) if files else None


@lru_cache(maxsize=8)
def _daily(city_id: str, stamp: str) -> pd.DataFrame:
    return hist.daily_table(stored("air", city_id), stored_aqi(city_id)["aqi"])


@lru_cache(maxsize=8)
def _fires_daily(city_id: str, stamp: str) -> pd.Series | None:
    fires = archive_fires()
    if fires is None:
        return None
    city = CITIES[city_id]
    days = pd.DatetimeIndex(sorted(fires.time.dt.normalize().unique()))
    return hist.daily_upwind(fires, city.lat, city.lon, stored("wx", city_id), days)


def notable(city: City, air: pd.DataFrame, wx: pd.DataFrame, window: tuple[date, date], fires) -> list[dict]:
    days = hist.worst_days(_daily(city.id, str(air.index.max().date())), *window)
    for day in days:
        at = pd.Timestamp(day["date"]) + pd.Timedelta(hours=23)
        frame = air.loc[at - pd.Timedelta(hours=72):at].join(wx, how="left")
        scored = score_hour(frame, at, city.lat, city.lon, fires, air)
        day["dominant"] = LABELS.get(stored_aqi(city.id).dominant.get(at))
        ranked = sorted((s for s in scored if s["score"] is not None), key=lambda s: -s["score"])
        day["top_source"] = {"label": ranked[0]["label"], "score": ranked[0]["score"]} if ranked else None
    return days


async def city_history(city: City) -> dict:
    air, wx, meta = await frames(city)
    at = current_hour(air)
    aqi = aqi_to(air, city.id, at)["aqi"]
    past = air.loc[:at]
    now_table = hist.hour_table(past, aqi, at.hour)
    today = at.date()
    last_full = stored("air", city.id).index.max().date()
    daily = _daily(city.id, str(last_full))
    fires_daily = _fires_daily(city.id, str(last_full))
    this_season, last_season = hist.season_windows(last_full)
    fires = archive_fires()
    fire_note = None if fires_daily is not None else "Fire history needs the FIRMS archive, which needs a FIRMS key."
    return clean({
        "city": city.name, "as_of": at.isoformat(), "window": f"24 hours ending {at.strftime('%H:%M')} IST",
        "vs_years": hist.compare_years(now_table, today, fires_daily),
        "vs_recent": hist.recent_averages(now_table, today),
        "season": hist.season_comparison(daily, last_full, fires_daily),
        "season_chart": hist.season_lines(daily, last_full),
        "fire_link": hist.fire_link(daily, fires_daily, *this_season),
        "notable": {"this_season": notable(city, air, wx, this_season, fires),
                    "last_season": notable(city, air, wx, last_season, fires)},
        "fire_note": fire_note, "source": MODEL_SOURCE,
        "method_note": "All years use the same model data and the same CPCB calculation. Season figures use complete days only.",
        "range": {"from": AQ_EARLIEST, "to": last_full.isoformat()}, **meta,
    })


async def map_view(day: date | None) -> dict:
    today = now_ist().date()
    day = day or today
    fires, fire_meta = await fire_frame()
    points, covered = [], False
    if fires is not None:
        covered = pd.Timestamp(day) >= fires.time.min().normalize()
        chosen = fires[fires.time.dt.date == day]
        points = [{"lat": round(a, 3), "lon": round(b, 3), "confidence": c}
                  for a, b, c in zip(chosen.latitude, chosen.longitude, chosen.confidence)]
    fires_note = None
    if fires is None:
        fires_note = "Fire data unavailable right now."
    elif not covered:
        fires_note = "No fire data for this date: the feed in use does not reach this far back."
    elif not points and day == today:
        fires_note = "No satellite detections yet today. This can mean no pass has happened yet, not that there are no fires."
    cities = []
    loaded = await asyncio.gather(*(frames(city) for city in CITIES.values()))
    for city, (air, wx, _) in zip(CITIES.values(), loaded):
        at = current_hour(air) if day == today else pd.Timestamp(day) + pd.Timedelta(hours=23)
        row = aqi_to(air, city.id, current_hour(air)).loc[at]
        hours = wx.loc[at - pd.Timedelta(hours=23):at]
        speed, direction = mean_wind(hours["wind_speed_10m"], hours["wind_direction_10m"])
        aqi = None if pd.isna(row.aqi) else int(row.aqi)
        cities.append({"id": city.id, "name": city.name, "lat": city.lat, "lon": city.lon, "aqi": aqi,
                       "category": category_payload(aqi), "wind_kmh": round(speed, 1), "wind_from_deg": round(direction),
                       "wind_from": None if math.isnan(direction) else compass(direction)})
    return clean({"date": day.isoformat(), "cities": cities, "fires": points, "fires_covered": bool(covered),
                  "fires_note": fires_note, "fires_meta": fire_meta, "days": [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)],
                  "source": MODEL_SOURCE})


def health() -> dict:
    snapshots = sorted(p.name for p in (f.SNAPSHOT_DIR / "delhi").glob("[0-9]*.parquet"))
    return {"status": "ok", "time": now_ist().isoformat(timespec="seconds"),
            "keys": {"firms": bool(FIRMS_MAP_KEY), "data_gov_in": bool(DATA_GOV_IN_KEY)},
            "history": {"from": AQ_EARLIEST, "to": str(stored("air", "delhi").index.max().date())},
            "fire_archive": bool(list(HISTORY_DIR.glob("fires_*.parquet"))), "forecast_snapshots": len(snapshots)}
