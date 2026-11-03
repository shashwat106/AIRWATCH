"""Likely contributors to a city's air, scored 0-1 with a plain-words reason.

These are explained heuristics, not measured source shares. Each score is independent, so they do
not add up to 100%. The weights and thresholds are our judgement and are not calibrated against
source-apportionment studies. Open-Meteo's pollutant values come from a coarse global model, so
street-level traffic or a nearby building site cannot show up directly.

Wind convention: wind_direction_10m is where the wind comes FROM (meteorological). A fire is upwind
when the wind blows from the fire to the city, so the fire-to-city bearing is compared with the
heading the wind blows TOWARDS, which is wind_from + 180.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

RADIUS_KM = 300.0
HALF_ANGLE = 45.0
WINDOW_HOURS = 48
CALM_KMH = 3.0  # below this a mean wind has no meaningful direction
CONFIDENCE_WEIGHT = {"h": 1.0, "n": 0.7, "l": 0.3}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def clip01(x: float) -> float:
    return 0.0 if x is None or math.isnan(x) else float(min(1.0, max(0.0, x)))


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing from point 1 to point 2, in degrees 0-360."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2) - np.radians(lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def angular_diff(a, b):
    """Smallest absolute angle between two bearings; handles the 0/360 line."""
    return np.abs((np.asarray(a, dtype=float) - b + 180.0) % 360.0 - 180.0)


def compass(deg: float) -> str:
    return COMPASS[int(((deg % 360) + 22.5) // 45) % 8]


def distance_weight(km):
    """1 at the city, falling linearly to 0 at RADIUS_KM."""
    return np.clip(1.0 - np.asarray(km, dtype=float) / RADIUS_KM, 0.0, 1.0)


def mean_wind(speed: pd.Series, direction_from: pd.Series) -> tuple[float, float]:
    """Vector-mean wind. Returns (speed km/h, direction the wind comes from)."""
    ok = speed.notna() & direction_from.notna()
    if not ok.any():
        return float("nan"), float("nan")
    rad = np.radians(direction_from[ok])
    u, v = (speed[ok] * np.sin(rad)).mean(), (speed[ok] * np.cos(rad)).mean()
    return float(math.hypot(u, v)), float((math.degrees(math.atan2(u, v)) + 360) % 360)


@dataclass
class FireStats:
    upwind_count: int = 0
    weighted: float = 0.0
    nearby_count: int = 0
    wind_kmh: float = float("nan")
    wind_from: float = float("nan")
    calm: bool = False


def upwind_fires(fires: pd.DataFrame, lat: float, lon: float, wind_kmh: float, wind_from: float,
                 at: pd.Timestamp, hours: int = WINDOW_HOURS) -> FireStats:
    stats = FireStats(wind_kmh=wind_kmh, wind_from=wind_from)
    recent = fires[(fires.time <= at) & (fires.time > at - pd.Timedelta(hours=hours))]
    if recent.empty:
        stats.calm = bool(math.isnan(wind_kmh) or wind_kmh < CALM_KMH)
        return stats
    km = haversine_km(recent.latitude.values, recent.longitude.values, lat, lon)
    near = km <= RADIUS_KM
    stats.nearby_count = int(near.sum())
    if math.isnan(wind_kmh) or wind_kmh < CALM_KMH:
        stats.calm = True
        return stats
    to_city = bearing_deg(recent.latitude.values, recent.longitude.values, lat, lon)
    heading = (wind_from + 180.0) % 360.0
    upwind = near & (angular_diff(to_city, heading) <= HALF_ANGLE)
    weights = recent.confidence.map(CONFIDENCE_WEIGHT).fillna(0.3).values
    stats.upwind_count = int(upwind.sum())
    stats.weighted = float((distance_weight(km) * weights)[upwind].sum())
    return stats


@dataclass
class Source:
    id: str
    label: str
    score: float | None
    level: str
    reason: str
    evidence: dict = field(default_factory=dict)


def level(score: float | None) -> str:
    if score is None:
        return "Unknown"
    return "Low" if score < 0.33 else "Medium" if score < 0.66 else "High"


def _src(id_: str, label: str, score: float | None, reason: str, evidence: dict) -> Source:
    score = None if score is None else round(clip01(score), 2)
    return Source(id_, label, score, level(score), reason, evidence)


def crop_burning(stats: FireStats | None, pm_ratio: float, co_excess: float) -> Source:
    label = "Crop burning"
    if stats is None:
        return _src("crop", label, None, "Fire data is unavailable for this date, so this was not scored.", {})
    evidence = {"upwind_detections": stats.upwind_count, "nearby_detections": stats.nearby_count,
                "pm_ratio": round(pm_ratio, 2)}
    if stats.calm:
        return _src("crop", label, 0.0 if stats.nearby_count == 0 else None,
                    f"{stats.nearby_count:,} fire detections within 300 km in 48 h, but the wind is too "
                    "calm to tell which way smoke is moving.", evidence)
    wind = f"wind from {compass(stats.wind_from)} at {stats.wind_kmh:.0f} km/h (24 h mean)"
    if stats.upwind_count == 0:
        return _src("crop", label, 0.0, f"No fire detections upwind in the last 48 h; {wind}.", evidence)
    fire_part = 1 - math.exp(-stats.weighted / 150.0)
    ratio_part = clip01((pm_ratio - 0.5) / 0.3)
    score = fire_part * (0.6 + 0.25 * ratio_part + 0.15 * clip01(co_excess))
    return _src("crop", label, score,
                f"{stats.upwind_count:,} fire detections upwind within 300 km in the last 48 h; {wind}.", evidence)


def vehicles(no2: float, co: float, no2_base: float, co_base: float, hour: int, weekday: int) -> Source:
    no2_x = clip01(no2 / no2_base - 1) if no2_base else 0.0
    co_x = clip01(co / co_base - 1) if co_base else 0.0
    rush = (8 <= hour < 11) or (18 <= hour < 22)
    factor = (1.0 if rush else 0.4) * (1.0 if weekday < 5 else 0.7)
    when = "rush hour" if rush else "outside rush hours"
    day = "weekday" if weekday < 5 else "weekend"
    pct = (no2 / no2_base - 1) * 100 if no2_base else float("nan")
    trend = f"{abs(pct):.0f}% {'above' if pct >= 0 else 'below'}"
    return _src("vehicles", "Vehicles", (0.6 * no2_x + 0.4 * co_x) * factor,
                f"NO2 is {trend} this city's 30-day norm, {when} on a {day}.",
                {"no2_ugm3": round(no2, 1), "no2_baseline_ugm3": round(no2_base, 1),
                 "co_ugm3": round(co), "co_baseline_ugm3": round(co_base)})


def dust(pm10: float, pm_ratio: float, hour: int, wind_kmh: float, humidity: float, rain_6h: float) -> Source:
    high_pm10 = clip01((pm10 - 100) / 200)
    coarse = clip01((0.5 - pm_ratio) / 0.3)
    dry = 1.0 if rain_6h < 0.1 and humidity < 60 else 0.0
    windy = clip01(wind_kmh / 20)
    day = 1.0 if 7 <= hour < 18 else 0.5
    return _src("dust", "Dust and construction", high_pm10 * coarse * (0.5 + 0.25 * dry + 0.25 * windy) * day,
                f"PM10 is {pm10:.0f} µg/m³ and fine particles are {pm_ratio * 100:.0f}% of it; "
                f"{'dry' if dry else 'not dry'} air, wind {wind_kmh:.0f} km/h.",
                {"pm10_ugm3": round(pm10, 1), "pm_ratio": round(pm_ratio, 2), "humidity_pct": round(humidity)})


def trapping(wind_kmh: float, blh_m: float) -> Source:
    calm = clip01((10 - wind_kmh) / 8)
    shallow = clip01((800 - blh_m) / 600)
    return _src("weather", "Weather trapping", 0.5 * calm + 0.5 * shallow,
                f"Wind {wind_kmh:.0f} km/h and a mixing layer of {blh_m:.0f} m: "
                f"{'pollution has little room to disperse' if calm + shallow > 1 else 'air can still mix'}.",
                {"wind_kmh": round(wind_kmh, 1), "boundary_layer_m": round(blh_m)})


def score_hour(frame: pd.DataFrame, at: pd.Timestamp, lat: float, lon: float,
               fires: pd.DataFrame | None, baseline: pd.DataFrame) -> list[dict]:
    """Score all sources for one hour.

    frame: hourly air and weather columns up to `at`. baseline: at least the prior days used for the
    city's own NO2 and CO norm (median of the 30 days before `at`).
    """
    recent = frame[frame.index <= at]
    last3 = recent.tail(3).mean(numeric_only=True)
    day = recent.tail(24)
    pm25, pm10 = last3["pm2_5"], last3["pm10"]
    ratio = float(pm25 / pm10) if pm10 else float("nan")
    window = baseline[(baseline.index < at) & (baseline.index >= at - pd.Timedelta(days=30))]
    no2_base = float(window["nitrogen_dioxide"].median())
    co_base = float(window["carbon_monoxide"].median())
    co_excess = last3["carbon_monoxide"] / co_base - 1 if co_base else 0.0
    wind_mean, wind_from = mean_wind(day["wind_speed_10m"], day["wind_direction_10m"])
    stats = None if fires is None else upwind_fires(fires, lat, lon, wind_mean, wind_from, at)
    out = [
        crop_burning(stats, ratio, float(co_excess)),
        vehicles(float(last3["nitrogen_dioxide"]), float(last3["carbon_monoxide"]), no2_base, co_base,
                 at.hour, at.weekday()),
        dust(float(pm10), ratio, at.hour, float(last3["wind_speed_10m"]),
             float(last3["relative_humidity_2m"]), float(recent.tail(6)["precipitation"].sum())),
        trapping(float(last3["wind_speed_10m"]), float(last3["boundary_layer_height"])),
    ]
    return [asdict(s) for s in out]
