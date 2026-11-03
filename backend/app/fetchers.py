"""Upstream data fetchers. Every request is logged with its URL and parameters (keys redacted)."""
from __future__ import annotations

import io
import json
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd

from .cache import Cached, cached_df
from .config import (DATA_GOV_IN_KEY, FIRE_BBOX, FIRMS_MAP_KEY, HISTORY_DIR, SNAPSHOT_DIR,
                     SOURCE_LOG, TZ, City)

log = logging.getLogger("airwatch.fetch")
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_URL = "https://api.open-meteo.com/v1/forecast"
WX_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
WX_PREVIOUS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FIRMS_PUBLIC = "https://firms.modaps.eosdis.nasa.gov/data/active_fire"
FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
CPCB_URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"

AQ_VARS = "pm2_5,pm10,nitrogen_dioxide,carbon_monoxide,sulphur_dioxide,ozone,dust"
WX_VARS = "wind_speed_10m,wind_direction_10m,relative_humidity_2m,precipitation,boundary_layer_height"
PUBLIC_FEEDS = ["noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_Asia_7d.csv",
                "noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_Asia_7d.csv",
                "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_Asia_7d.csv"]


def _redact(text: str) -> str:
    for secret in (FIRMS_MAP_KEY, DATA_GOV_IN_KEY):
        if secret:
            text = text.replace(secret, "***")
    return text


def _log(url: str, params: dict | None, status: int | str) -> None:
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "url": _redact(url),
           "params": {k: ("***" if k == "api-key" else v) for k, v in (params or {}).items()},
           "status": status}
    with SOURCE_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


async def _get(url: str, params: dict | None = None, timeout: float = 45.0) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            _log(url, params, type(exc).__name__)
            raise RuntimeError(f"request failed: {type(exc).__name__}") from None
    _log(url, params, resp.status_code)
    if resp.is_error:  # raise_for_status() would put the keyed URL in the message
        raise RuntimeError(f"upstream returned HTTP {resp.status_code}")
    return resp


def _hourly(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame(payload["hourly"])
    df["time"] = pd.to_datetime(df["time"])  # naive IST wall-clock time
    return df.set_index("time").sort_index()


async def air_range(city: City, start: str, end: str) -> pd.DataFrame:
    params = {"latitude": city.lat, "longitude": city.lon, "hourly": AQ_VARS, "timezone": TZ,
              "start_date": start, "end_date": end}
    return _hourly((await _get(AQ_URL, params, 90)).json())


async def weather_archive(city: City, start: str, end: str) -> pd.DataFrame:
    params = {"latitude": city.lat, "longitude": city.lon, "hourly": WX_VARS, "timezone": TZ,
              "start_date": start, "end_date": end}
    return _hourly((await _get(WX_ARCHIVE_URL, params, 90)).json())


async def weather_previous_runs(city: City, past_days: int = 71) -> pd.DataFrame:
    """Forecasts as issued about a day ahead. boundary_layer_height has no such archive."""
    names = ["wind_speed_10m", "wind_direction_10m", "relative_humidity_2m", "precipitation"]
    params = {"latitude": city.lat, "longitude": city.lon, "timezone": TZ, "past_days": past_days,
              "forecast_days": 1, "hourly": ",".join(f"{n}_previous_day1" for n in names)}
    df = _hourly((await _get(WX_PREVIOUS_URL, params, 90)).json())
    return df.rename(columns={f"{n}_previous_day1": n for n in names})


async def air_live(city: City) -> Cached:
    """Last 3 days plus 3 days of forecast, cached for 30 minutes."""
    async def go():
        params = {"latitude": city.lat, "longitude": city.lon, "hourly": AQ_VARS, "timezone": TZ,
                  "past_days": 3, "forecast_days": 3}
        return _hourly((await _get(AQ_URL, params)).json())
    return await cached_df(f"air_live:{city.id}", 1800, go)


async def weather_live(city: City) -> Cached:
    async def go():
        params = {"latitude": city.lat, "longitude": city.lon, "hourly": WX_VARS, "timezone": TZ,
                  "past_days": 3, "forecast_days": 3}
        return _hourly((await _get(WX_URL, params)).json())
    return await cached_df(f"wx_live:{city.id}", 1800, go)


def _clean_fires(df: pd.DataFrame) -> pd.DataFrame:
    west, south, east, north = FIRE_BBOX
    df = df[df.latitude.between(south, north) & df.longitude.between(west, east)].copy()
    hhmm = df.acq_time.astype(int).astype(str).str.zfill(4)
    utc = pd.to_datetime(df.acq_date.astype(str) + " " + hhmm, format="%Y-%m-%d %H%M")
    df["time"] = utc + pd.Timedelta(hours=5, minutes=30)  # FIRMS is UTC; store naive IST like the rest
    df["confidence"] = df.confidence.astype(str).str.lower().str[0]  # l / n / h
    keep = ["latitude", "longitude", "time", "confidence", "frp", "satellite", "daynight"]
    return df[keep].reset_index(drop=True)


async def _fires_keyed() -> pd.DataFrame:
    """Last 15 days from the keyed area API, in the 5-day chunks it allows."""
    bbox = ",".join(str(v) for v in FIRE_BBOX)
    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    frames = []
    for src in ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT"):
        for back in (14, 9, 4):
            start = (today - timedelta(days=back)).isoformat()
            resp = await _get(f"{FIRMS_AREA}/{FIRMS_MAP_KEY}/{src}/{bbox}/5/{start}", timeout=90)
            if not resp.text.startswith("latitude"):
                raise RuntimeError(f"FIRMS said: {_redact(resp.text[:120])}")
            frames.append(pd.read_csv(io.StringIO(resp.text)))
    return pd.concat(frames, ignore_index=True)


async def _fires_public() -> pd.DataFrame:
    frames = []
    for feed in PUBLIC_FEEDS:
        resp = await _get(f"{FIRMS_PUBLIC}/{feed}", timeout=90)
        frames.append(pd.read_csv(io.StringIO(resp.text)))
    return pd.concat(frames, ignore_index=True)


async def fires_recent() -> Cached:
    """Recent fires from the three VIIRS satellites.

    Uses the keyed area API (14-day map) when FIRMS_MAP_KEY is set and working, otherwise NASA's
    public no-key CSVs (7 days). Satellites see the same fire on overlapping passes, so counts are
    detections, not unique fires.
    """
    async def go():
        if FIRMS_MAP_KEY:
            try:
                return _clean_fires(await _fires_keyed())
            except RuntimeError as exc:
                log.warning("keyed FIRMS failed, using public feed: %s", exc)
        return _clean_fires(await _fires_public())
    return await cached_df("fires_recent:keyed" if FIRMS_MAP_KEY else "fires_recent", 3600, go)


async def fires_archive_chunk(source: str, day: date, days: int = 5) -> pd.DataFrame:
    """One archive chunk. Needs FIRMS_MAP_KEY: there is no keyless route to older fires."""
    if not FIRMS_MAP_KEY:
        raise RuntimeError("FIRMS_MAP_KEY not set")
    bbox = ",".join(str(v) for v in FIRE_BBOX)
    resp = await _get(f"{FIRMS_AREA}/{FIRMS_MAP_KEY}/{source}/{bbox}/{days}/{day.isoformat()}", timeout=120)
    if not resp.text.startswith("latitude"):
        raise RuntimeError(f"FIRMS said: {_redact(resp.text[:120])}")
    df = pd.read_csv(io.StringIO(resp.text))
    return _clean_fires(df) if len(df) else pd.DataFrame()


async def cpcb_stations(city: City) -> Cached:
    """Official station readings. Raises if there is no key; the API layer reports it as unavailable."""
    async def go():
        if not DATA_GOV_IN_KEY:
            raise RuntimeError("DATA_GOV_IN_KEY not set")
        params = {"api-key": DATA_GOV_IN_KEY, "format": "json", "limit": 500,
                  "filters[city]": city.cpcb_city}
        records = (await _get(CPCB_URL, params)).json().get("records", [])
        return pd.DataFrame(records).astype(str)
    return await cached_df(f"cpcb:{city.id}", 1800, go)


def history_path(kind: str, city_id: str):
    return HISTORY_DIR / f"{kind}_{city_id}.parquet"


async def snapshot_forecast(city: City) -> pd.DataFrame:
    """Store Open-Meteo's forecast as issued now. Later truth can then score it fairly,
    which the API cannot do retroactively: pm2_5_previous_dayN returned all nulls on 2026-11-04."""
    params = {"latitude": city.lat, "longitude": city.lon, "hourly": "pm2_5,pm10", "timezone": TZ,
              "forecast_days": 3}
    df = _hourly((await _get(AQ_URL, params)).json())
    issued = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    folder = SNAPSHOT_DIR / city.id
    folder.mkdir(exist_ok=True)
    df.to_parquet(folder / f"{issued}.parquet")
    return df
