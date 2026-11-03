"""AirWatch API."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import service
from .config import CITIES, FRONTEND_ORIGIN, City

RATE_LIMIT, RATE_WINDOW = 300, 60.0  # per IP; judges on one network can share an address

app = FastAPI(title="AirWatch API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN], allow_methods=["GET"], allow_headers=["*"])
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    now, hits = time.time(), _hits[ip]
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return JSONResponse({"detail": "Too many requests. Please wait a minute."}, status_code=429)
    hits.append(now)
    return await call_next(request)


class Category(BaseModel):
    name: str
    color: str


class CityInfo(BaseModel):
    id: str
    name: str
    state: str
    lat: float
    lon: float


class Official(BaseModel):
    available: bool
    message: str | None = None
    stations: list[dict[str, Any]] = []
    source: str | None = None
    stale: bool | None = None


class Now(BaseModel):
    city: str
    time: str
    aqi: int | None
    category: Category | None
    dominant: str | None
    pm2_5: float | None
    pm10: float | None
    unit: str
    pollutants: list[dict[str, Any]]
    weather: dict[str, Any]
    source: str
    source_note: str
    shared_grid_with: str | None
    official: Official
    advice: list[dict[str, str]]
    advice_note: str
    fetched_at: str
    stale: bool


class ForecastHour(BaseModel):
    time: str
    pm2_5: float | None
    pm10: float | None
    aqi: float | None
    hourly_index: float | None
    open_meteo_pm2_5: float | None
    ours_pm2_5: float | None


class Forecast(BaseModel):
    city: str
    issued: str
    served: str
    served_reason: str
    hours: list[ForecastHour]
    best_time: dict[str, Any] | None
    timing: dict[str, Any] | None
    best_time_note: str
    metrics: dict[str, Any]
    source: str
    fetched_at: str
    stale: bool


class SourceScore(BaseModel):
    id: str
    label: str
    score: float | None
    level: str
    reason: str
    evidence: dict[str, Any]


class Sources(BaseModel):
    city: str
    time: str
    sources: list[SourceScore]
    fires: dict[str, Any]
    note: str
    fetched_at: str
    stale: bool


class History(BaseModel):
    city: str
    as_of: str
    window: str
    vs_years: dict[str, Any]
    vs_recent: dict[str, Any]
    season: dict[str, Any]
    season_chart: list[dict[str, Any]]
    calendar: list[dict[str, Any]]
    fire_link: dict[str, Any]
    notable: dict[str, Any]
    fire_note: str | None
    source: str
    method_note: str
    range: dict[str, str]
    fetched_at: str
    stale: bool


class MapView(BaseModel):
    date: str
    cities: list[dict[str, Any]]
    fires: list[dict[str, Any]]
    fires_covered: bool
    fires_note: str | None
    fires_meta: dict[str, Any]
    days: list[str]
    source: str


def get_city(city_id: str) -> City:
    city = CITIES.get(city_id.lower())
    if city is None:
        raise HTTPException(404, f"Unknown city '{city_id[:40]}'. See /api/cities for the list.")
    return city


async def guarded(work):
    try:
        return await work
    except HTTPException:
        raise
    except RuntimeError as exc:  # upstream failed and no cached copy exists
        raise HTTPException(503, f"Data source unavailable: {exc}") from None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return service.health()


@app.get("/api/cities", response_model=list[CityInfo])
def cities():
    return [CityInfo(id=c.id, name=c.name, state=c.state, lat=c.lat, lon=c.lon) for c in CITIES.values()]


@app.get("/api/city/{city_id}/now", response_model=Now)
async def now(city_id: str):
    return await guarded(service.city_now(get_city(city_id)))


@app.get("/api/city/{city_id}/forecast", response_model=Forecast)
async def forecast(city_id: str):
    return await guarded(service.city_forecast(get_city(city_id)))


@app.get("/api/city/{city_id}/sources", response_model=Sources)
async def sources(city_id: str):
    return await guarded(service.city_sources(get_city(city_id)))


@app.get("/api/city/{city_id}/history", response_model=History)
async def history(city_id: str):
    return await guarded(service.city_history(get_city(city_id)))


class Insights(BaseModel):
    city: str
    levers: dict[str, Any] | None
    relief: dict[str, Any] | None
    outlook: dict[str, Any] | None
    limits: dict[str, Any] | None
    validation: dict[str, Any] | None
    source: str
    fetched_at: str
    stale: bool


class FireDay(BaseModel):
    date: str
    fires: list[dict[str, float]]


class FireDays(BaseModel):
    days: list[FireDay]
    meta: dict[str, Any]


@app.get("/api/city/{city_id}/insights", response_model=Insights)
async def insights(city_id: str):
    return await guarded(service.city_insights(get_city(city_id)))


@app.get("/api/fires", response_model=FireDays)
async def fires():
    return await guarded(service.fires_by_day())


@app.get("/api/map", response_model=MapView)
async def map_view(day: date | None = Query(None, alias="date", description="YYYY-MM-DD, within the last 14 days")):
    today = service.now_ist().date()
    if day is not None and not today - timedelta(days=13) <= day <= today:
        raise HTTPException(422, "Date must be within the last 14 days.")
    return await guarded(service.map_view(day))
