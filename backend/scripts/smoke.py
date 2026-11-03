"""Call every endpoint in-process and print status and timing. Run from anywhere."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import CITIES  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
paths = ["/api/health", "/api/cities", "/api/map", "/api/map?date=2026-11-03", "/api/map?date=2026-10-22"]
for city in CITIES:
    paths += [f"/api/city/{city}/{part}" for part in ("now", "forecast", "sources", "history", "insights")]
failed = 0
for path in paths:
    start = time.time()
    response = client.get(path)
    failed += response.status_code != 200
    print(path, response.status_code, f"{time.time() - start:.1f}s")
print("failed:", failed)
print("today note:", client.get("/api/map").json()["fires_note"])
print("old note:", client.get("/api/map?date=2026-10-22").json()["fires_note"])
print("fires on 3 Nov:", len(client.get("/api/map?date=2026-11-03").json()["fires"]))
