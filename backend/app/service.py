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
from ml import insights as ins
from ml import validation as val
from ml import warning as warn
from ml.aqi import COLUMNS, LABELS, aqi_series, category, running_means, sub_index
from ml.sources import compass, mean_wind, score_hour, top_cause

from . import fetchers as f
from .advice import ADVICE, DISCLAIMER
from .config import AQ_EARLIEST, CITIES, DATA_GOV_IN_KEY, FIRMS_MAP_KEY, HISTORY_DIR, OPENAQ_API_KEY, City

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
    from ml.aqi import overall
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


def stored_stations(city_id: str) -> pd.DataFrame | None:
    path = f.history_path("station", city_id)
    return pd.read_parquet(path) if path.exists() else None


async def openaq_stations(city: City) -> dict:
    """Measured station readings through OpenAQ, newest first."""
    table = stored_stations(city.id)
    none = {"available": False, "message": "No station readings for this city right now.", "stations": []}
    if table is None or not OPENAQ_API_KEY:
        return none
    ids = table.drop_duplicates("location")[["location", "sensor", "station", "provider", "distance_km"]]
    try:
        res = await f.station_latest(city, ids)
    except Exception:
        return none
    rows = res.df.sort_values("time", ascending=False).to_dict("records")
    return {"available": True, "message": None, "stations": rows, "stale": res.stale,
            "source": "Measured readings via OpenAQ, from CPCB and AirNow monitors"}


async def official(city: City) -> dict:
    if not DATA_GOV_IN_KEY:
        return await openaq_stations(city)
    try:
        res = await f.cpcb_stations(city)
    except Exception:
        return {"available": False, "message": "Official feed unavailable right now.", "stations": []}
    if res.df.empty:
        return {"available": False, "message": "Official feed returned no stations for this city.", "stations": []}
    return {"available": True, "message": None, "stations": official_stations(res.df),
            "source": "CPCB real-time feed via data.gov.in", "stale": res.stale}


def pollutant_rows(air: pd.DataFrame, at: pd.Timestamp) -> list[dict]:
    """Each pollutant on the averaging period CPCB uses, worst sub-index first."""
    means = running_means(air.loc[at - pd.Timedelta(hours=30):at]).iloc[-1]
    rows = []
    for key in COLUMNS:
        short = key in ("co", "o3")
        rows.append({"id": key, "label": LABELS[key], "value": round(float(means[key]), 1 if key == "co" else 0),
                     "unit": "mg/m³" if key == "co" else "µg/m³", "window": "8-hour" if short else "24-hour",
                     "sub_index": sub_index(key, means[key])})
    return sorted(rows, key=lambda r: -(r["sub_index"] or 0))


def weather_now(wx: pd.DataFrame, at: pd.Timestamp) -> dict:
    row = wx.loc[at]
    direction = row["wind_direction_10m"]
    return {"wind_kmh": row["wind_speed_10m"], "wind_from": None if pd.isna(direction) else compass(direction),
            "humidity_pct": row["relative_humidity_2m"], "mixing_layer_m": row["boundary_layer_height"],
            "rain_mm": row["precipitation"]}


async def measured_check(city: City, aqi: int | None) -> dict | None:
    """Compare the model's AQI with what stations recently measured. Quietly absent if stations are unavailable."""
    table = stored_stations(city.id)
    if table is None or not OPENAQ_API_KEY:
        return None
    ids = table.drop_duplicates("location")[["sensor", "station", "provider"]]
    try:
        recent = (await f.station_recent(city, ids)).df
    except Exception:
        return None
    sources = {f"{provider} stations": rows.groupby("time").pm2_5.mean() for provider, rows in recent.groupby("provider")}
    return warn.check(sources, aqi, now_ist())


async def city_now(city: City) -> dict:
    air, wx, meta = await frames(city)
    at = current_hour(air)
    series = aqi_to(air, city.id, at)
    row = series.loc[at]
    aqi = None if pd.isna(row.aqi) else int(row.aqi)
    cat = category_payload(aqi)
    latest = air.loc[at]
    check = await measured_check(city, aqi)
    advice_cat = check["category"] if check and check["warn"] else cat
    return clean({
        "city": city.name, "time": at.isoformat(), "aqi": aqi, "category": cat,
        "dominant": LABELS.get(row.dominant), "pm2_5": latest["pm2_5"], "pm10": latest["pm10"],
        "unit": "µg/m³", "pollutants": pollutant_rows(air, at), "weather": weather_now(wx, at), "source": MODEL_SOURCE, "source_note": SOURCE_NOTE,
        "shared_grid_with": SHARED_GRID.get(city.id), "official": await official(city),
        "check": check, "advice_category": advice_cat,
        "advice": ADVICE.get(advice_cat["name"], []) if advice_cat else [], "advice_note": DISCLAIMER, **meta,
    })


async def ours_forecast(city: City, air: pd.DataFrame, wx: pd.DataFrame, at: pd.Timestamp) -> pd.DataFrame | None:
    """Run our model from `at`, with the fire feature when fire data is available."""
    fires, _ = await fire_frame()
    series = None if fires is None else fc.fire_series(fires, city.lat, city.lon, wx, pd.DatetimeIndex([at]))
    return fc.run_models(city.id, air.loc[:at], wx, wx["boundary_layer_height"], at, series)


async def city_forecast(city: City) -> dict:
    air, wx, meta = await frames(city)
    at = current_hour(air)
    hours = pd.date_range(at + pd.Timedelta(hours=1), periods=fc.HORIZON, freq="h")
    baseline = air.reindex(hours)
    ours = await ours_forecast(city, air, wx, at)
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
    timing = None
    if best:
        best["category"] = category_payload(best["mean_index"])
        timing = ins.timing_saving(chosen.pm2_5, best["start"], best["end"])
    return clean({
        "city": city.name, "issued": at.isoformat(), "served": served, "served_reason": reason, "hours": rows,
        "best_time": best, "timing": timing, "best_time_note": "Ranked on hourly PM2.5 and PM10, not the 24-hour official AQI.",
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


DAY_HOURS = (9, 14, 19)  # morning, afternoon, evening. Night alone always looks like trapping.


def day_scores(city: City, air: pd.DataFrame, wx: pd.DataFrame, day: date, fires) -> list[dict]:
    """A whole day's source scores: the mean of its morning, afternoon and evening scores."""
    runs = []
    for hour in DAY_HOURS:
        at = pd.Timestamp(day) + pd.Timedelta(hours=hour)
        frame = air.loc[at - pd.Timedelta(hours=72):at].join(wx, how="left")
        runs.append(score_hour(frame, at, city.lat, city.lon, fires, air))
    merged = []
    for parts in zip(*runs):
        scores = [p["score"] for p in parts]
        mean = None if any(v is None for v in scores) else round(sum(scores) / len(scores), 2)
        merged.append({"id": parts[0]["id"], "label": parts[0]["label"], "score": mean})
    return merged


def notable(city: City, air: pd.DataFrame, wx: pd.DataFrame, window: tuple[date, date], fires) -> list[dict]:
    days = hist.worst_days(_daily(city.id, str(air.index.max().date())), *window)
    for day in days:
        at = pd.Timestamp(day["date"]) + pd.Timedelta(hours=23)
        day["dominant"] = LABELS.get(stored_aqi(city.id).dominant.get(at))
        cause = top_cause(day_scores(city, air, wx, date.fromisoformat(day["date"]), fires))
        day["top_source"] = {"label": cause["label"], "score": cause["score"]} if cause else None
    return days


_calendars: dict[tuple, list[dict]] = {}


def season_calendar(city: City, air: pd.DataFrame, wx: pd.DataFrame, last_full: date, recent_fires) -> list[dict]:
    """Each day of this season with its AQI and likely cause.

    Crop burning is scored only when fire data covers that day's full 48-hour window. Otherwise it
    is left unscored, because a missing record must not read as zero fires.
    """
    archive = archive_fires()
    key = (city.id, last_full, archive is not None, recent_fires is not None)
    if key in _calendars:
        return _calendars[key]
    fires = archive if archive is not None else recent_fires
    covered_from = None if fires is None else fires.time.min() + pd.Timedelta(hours=48)
    table = _daily(city.id, str(last_full))
    dominant = stored_aqi(city.id).dominant
    rows = []
    start = hist.season_start(last_full)
    for offset in range((last_full - start).days + 1):
        day = start + timedelta(days=offset)
        at = pd.Timestamp(day) + pd.Timedelta(hours=23)
        ts = pd.Timestamp(day)
        aqi = None if ts not in table.index or pd.isna(table.at[ts, "aqi"]) else int(table.at[ts, "aqi"])
        entry = {"date": day.isoformat(), "aqi": aqi, "category": category_payload(aqi), "cause": None,
                 "dominant": LABELS.get(dominant.get(at)), "crop_scored": False}
        if aqi is not None:
            morning = pd.Timestamp(day) + pd.Timedelta(hours=DAY_HOURS[0])
            usable = fires if covered_from is not None and morning >= covered_from else None
            entry["cause"] = top_cause(day_scores(city, air, wx, day, usable))
            entry["crop_scored"] = usable is not None
        rows.append(entry)
    _calendars[key] = rows
    return rows


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
    recent_fires, _ = await fire_frame()
    fire_note = None if fires_daily is not None else "Fire history needs the FIRMS archive, which needs a FIRMS key."
    season = hist.season_comparison(daily, last_full, fires_daily)
    if fires_daily is not None:
        a, b = season["this_season"], season["last_season"]
        layer = wx["boundary_layer_height"]
        season["fire_summary"] = hist.fire_words(a, b, layer.loc[a["start"]:a["end"]].mean(), layer.loc[b["start"]:b["end"]].mean())
        fire_note = (f"Fire counts come from one satellite (Suomi NPP). Days too calm to tell upwind are left out: "
                     f"{a['fire_days_counted']} of {a['days_expected']} days counted this season, "
                     f"{b['fire_days_counted']} of {b['days_expected']} last season. This year uses NASA's near-real-time "
                     "data and earlier years its final processed data, so the two aren't identical.")
    return clean({
        "city": city.name, "as_of": at.isoformat(), "window": f"24 hours ending {at.strftime('%H:%M')} IST",
        "vs_years": hist.compare_years(now_table, today, fires_daily),
        "vs_recent": hist.recent_averages(now_table, today),
        "season": season,
        "season_chart": hist.season_lines(daily, last_full),
        "calendar": season_calendar(city, air, wx, last_full, recent_fires),
        "fire_link": hist.fire_link(daily, fires_daily, *this_season),
        "notable": {"this_season": notable(city, air, wx, this_season, fires),
                    "last_season": notable(city, air, wx, last_season, fires)},
        "fire_note": fire_note, "source": MODEL_SOURCE,
        "method_note": "All years use the same model data and the same CPCB calculation. Season figures use complete days only.",
        "range": {"from": AQ_EARLIEST, "to": last_full.isoformat()}, **meta,
    })


def validation_for(city: City, air: pd.DataFrame) -> dict | None:
    table = stored_stations(city.id)
    if table is None:
        return None
    season = pd.Timestamp(hist.season_start(air.index.max().date()))
    table = table[table.time >= season]  # the file holds a year, for fitting; this reports the season
    result = val.compare(table, air["pm2_5"], city.name)
    if result:
        result["cleanest"] = val.cleanest_window(table)
    return result


async def city_insights(city: City) -> dict:
    air, wx, meta = await frames(city)
    at = current_hour(air)
    history_air, history_wx = stored("air", city.id), stored("wx", city.id)
    last_full = history_air.index.max().date()
    table = _daily(city.id, str(last_full))
    return clean({
        "city": city.name, "levers": ins.weather_levers(history_air, history_wx),
        "relief": ins.relief_ahead(wx, at), "outlook": ins.winter_outlook(table["aqi"], last_full, city.name),
        "limits": ins.days_over_limit(table, last_full, city.name),
        "validation": validation_for(city, history_air),
        "source": "Patterns from Open-Meteo model data since Aug 2022. Forecast from Open-Meteo weather.", **meta,
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


async def fires_by_day() -> dict:
    """Recent detections grouped by IST date, for the fires chapter."""
    fires, meta = await fire_frame()
    days = []
    if fires is not None:
        for day, rows in fires.groupby(fires.time.dt.date):
            days.append({"date": day.isoformat(), "fires": [
                {"lat": round(a, 3), "lon": round(b, 3)} for a, b in zip(rows.latitude, rows.longitude)]})
    return clean({"days": days, "meta": meta})


def health() -> dict:
    snapshots = sorted(p.name for p in (f.SNAPSHOT_DIR / "delhi").glob("[0-9]*.parquet"))
    return {"status": "ok", "time": now_ist().isoformat(timespec="seconds"),
            "keys": {"firms": bool(FIRMS_MAP_KEY), "data_gov_in": bool(DATA_GOV_IN_KEY)},
            "history": {"from": AQ_EARLIEST, "to": str(stored("air", "delhi").index.max().date())},
            "fire_archive": bool(list(HISTORY_DIR.glob("fires_*.parquet"))), "forecast_snapshots": len(snapshots)}
