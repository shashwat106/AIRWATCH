"""AirWatch API."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import service
from .config import CITIES, FRONTEND_ORIGIN, City

RATE_LIMIT, RATE_WINDOW = 300, 60.0  # per IP; judges on one network can share an address

WARM_EVERY = 1200  # seconds between rebuilds; free hosts have little CPU, so visitors shouldn't wait for this work
READY_FOR = 1800  # a prepared answer is served for up to this long
log = logging.getLogger("airwatch.warm")
_ready: dict[str, tuple[float, Any]] = {}


async def remembered(key: str, work, refresh: bool = False):
    """Serve a prepared answer if there is a recent one. Otherwise do the work and keep the result."""
    hit = _ready.get(key)
    if hit and not refresh and time.time() - hit[0] < READY_FOR:
        return hit[1]
    value = await work()
    _ready[key] = (time.time(), value)
    return value


def warm_jobs() -> list[tuple[str, Any]]:
    jobs: list[tuple[str, Any]] = [("fires", service.fires_by_day), ("league", service.league)]
    for city in CITIES.values():
        for name, build in (("now", service.city_now), ("forecast", service.city_forecast), ("sources", service.city_sources),
                            ("insights", service.city_insights), ("history", service.city_history)):
            jobs.append((f"{name}:{city.id}", lambda build=build, city=city: build(city)))
    return jobs


async def warm_forever() -> None:
    await asyncio.sleep(15)  # let the host's first health check pass
    while True:
        for key, work in warm_jobs():
            try:
                await remembered(key, work, refresh=True)
            except Exception as exc:  # one bad upstream must not stop the rest; visitors still get a live attempt
                log.warning("warm %s failed: %s", key, type(exc).__name__)
            await asyncio.sleep(0.5)  # leave room for real visitors between jobs
        await asyncio.sleep(WARM_EVERY)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(warm_forever())
    yield
    task.cancel()


app = FastAPI(title="AirWatch API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN, "https://airwatcher.vercel.app"], allow_methods=["GET"], allow_headers=["*"])
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
    check: dict[str, Any] | None
    advice_category: Category | None
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
    plans: list[dict[str, Any]]
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
    city = get_city(city_id)
    return await guarded(remembered(f"now:{city.id}", lambda: service.city_now(city)))


@app.get("/api/city/{city_id}/forecast", response_model=Forecast)
async def forecast(city_id: str):
    city = get_city(city_id)
    return await guarded(remembered(f"forecast:{city.id}", lambda: service.city_forecast(city)))


@app.get("/api/city/{city_id}/sources", response_model=Sources)
async def sources(city_id: str):
    city = get_city(city_id)
    return await guarded(remembered(f"sources:{city.id}", lambda: service.city_sources(city)))


@app.get("/api/city/{city_id}/history", response_model=History)
async def history(city_id: str):
    city = get_city(city_id)
    return await guarded(remembered(f"history:{city.id}", lambda: service.city_history(city)))


class Insights(BaseModel):
    city: str
    levers: dict[str, Any] | None
    relief: dict[str, Any] | None
    outlook: dict[str, Any] | None
    limits: dict[str, Any] | None
    validation: dict[str, Any] | None
    changed: dict[str, Any] | None
    smoke: list[dict[str, Any]]
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
    city = get_city(city_id)
    return await guarded(remembered(f"insights:{city.id}", lambda: service.city_insights(city)))


class League(BaseModel):
    cities: list[dict[str, Any]]
    source: str
    time: str


class Scoreboard(BaseModel):
    cities: list[dict[str, Any]]
    warning_total: dict[str, Any] | None
    generated_at: str | None
    note: str


@app.get("/api/league", response_model=League)
async def league():
    return await guarded(remembered("league", service.league))


@app.get("/api/scoreboard", response_model=Scoreboard)
def scoreboard():
    return service.scoreboard()


@app.get("/api/fires", response_model=FireDays)
async def fires():
    return await guarded(remembered("fires", service.fires_by_day))


@app.get("/api/map", response_model=MapView)
async def map_view(day: date | None = Query(None, alias="date", description="YYYY-MM-DD, within the last 14 days")):
    today = service.now_ist().date()
    if day is not None and not today - timedelta(days=13) <= day <= today:
        raise HTTPException(422, "Date must be within the last 14 days.")
    return await guarded(service.map_view(day))
