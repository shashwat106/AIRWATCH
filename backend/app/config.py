"""Static configuration. Secrets are read from backend/.env only."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"          # disposable, gitignored
HISTORY_DIR = DATA_DIR / "history"      # fetched once, committed so deploys need no re-fetch
SNAPSHOT_DIR = DATA_DIR / "snapshots"   # live forecast snapshots, used to score Open-Meteo honestly
SOURCE_LOG = DATA_DIR / "source_log.jsonl"
for _d in (CACHE_DIR, HISTORY_DIR, SNAPSHOT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

load_dotenv(BACKEND_DIR / ".env")
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "").strip()
DATA_GOV_IN_KEY = os.getenv("DATA_GOV_IN_KEY", "").strip()
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "").strip()
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

TZ = "Asia/Kolkata"
# Verified live 2026-11-04 by binary search: first day with non-null pm2_5, identical for all 8 cities.
AQ_EARLIEST = "2022-08-04"
# FIRMS bounding box: west,south,east,north. Punjab, Haryana, west UP, Delhi, plus Lucknow/Kanpur.
FIRE_BBOX = (73.5, 26.0, 81.5, 32.7)


@dataclass(frozen=True)
class City:
    id: str
    name: str
    state: str
    lat: float
    lon: float
    cpcb_city: str  # spelling used by the data.gov.in feed


CITIES: dict[str, City] = {c.id: c for c in [
    City("delhi", "Delhi", "Delhi", 28.61, 77.21, "Delhi"),
    City("gurugram", "Gurugram", "Haryana", 28.46, 77.03, "Gurugram"),
    City("noida", "Noida", "Uttar Pradesh", 28.57, 77.32, "Noida"),
    City("ghaziabad", "Ghaziabad", "Uttar Pradesh", 28.67, 77.45, "Ghaziabad"),
    City("chandigarh", "Chandigarh", "Chandigarh", 30.73, 76.78, "Chandigarh"),
    City("ludhiana", "Ludhiana", "Punjab", 30.90, 75.86, "Ludhiana"),
    City("lucknow", "Lucknow", "Uttar Pradesh", 26.85, 80.95, "Lucknow"),
    City("kanpur", "Kanpur", "Uttar Pradesh", 26.45, 80.33, "Kanpur"),
]}
