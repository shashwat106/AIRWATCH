"""Warn when stations measured worse air than the model shows.

The model understates the worst hours and no correction passed testing, so the app doesn't change its
number. It says so plainly instead, and advice follows whichever is worse. Measured air uses the same
24-hour PM2.5 average CPCB uses, from the newest readings each source has.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .aqi import CATEGORIES, category, sub_index

WINDOW_HOURS = 24
MIN_HOURS = 16  # CPCB's minimum for a sub-index
MAX_AGE_HOURS = 36  # older readings say little about today
NAMES = [name for name, _ in CATEGORIES]
RESULTS_PATH = Path(__file__).resolve().parent / "warning_results.json"


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8")) if RESULTS_PATH.exists() else {}


def rank(aqi: float | None) -> int:
    found = category(aqi)
    return NAMES.index(found[0]) if found else -1


def latest_mean(hourly: pd.Series, now: pd.Timestamp) -> tuple[float, pd.Timestamp] | None:
    """Mean of the most recent 24-hour window with enough readings. CPCB's feed arrives in batches with
    gaps, so the newest reading alone may not have a full window behind it."""
    series = hourly.dropna().sort_index()
    for end in reversed(series.index):
        if now - end > pd.Timedelta(hours=MAX_AGE_HOURS):
            return None
        window = series.loc[end - pd.Timedelta(hours=WINDOW_HOURS - 1):end]
        if len(window) >= MIN_HOURS:
            return float(window.mean()), end
    return None


def check(sources: dict[str, pd.Series], model_aqi: int | None, now: pd.Timestamp) -> dict | None:
    """Compare the worst recent measurement with the model's AQI. Returns None without usable data."""
    readings = []
    for name, hourly in sources.items():
        found = latest_mean(hourly, now)
        if found:
            readings.append((found[0], found[1], name))
    if not readings or model_aqi is None:
        return None
    pm, end, name = max(readings, key=lambda r: r[0])
    index = sub_index("pm2_5", pm)
    measured = category(index)
    warn = rank(index) > rank(model_aqi)
    until = f"{end.day} {end:%b} {end:%H:%M} IST"
    out = {"warn": warn, "measured_pm": round(pm), "until": until, "measured_index": index, "category": {"name": measured[0], "color": measured[1]},
           "source": name, "to": end.isoformat(timespec="minutes"), "message": None}
    if warn:
        out["message"] = (f"Stations measured worse air than this estimate: PM2.5 averaged {pm:.0f} µg/m³ over the 24 hours to {until}, "
                          f"which is {measured[0]}. Treat today as {measured[0]}.")
    return out


def backtest(model_aqi: pd.Series, real: pd.Series, lag_hours: int = 18) -> dict | None:
    """Replay the rule at noon each day, using only station readings at least `lag_hours` old.
    Truth is the station 24-hour average that was only known later."""
    real = real.sort_index()
    full = real.reindex(pd.date_range(real.index.min(), real.index.max(), freq="h"))
    mean24 = full.rolling(WINDOW_HOURS, min_periods=MIN_HOURS).mean()
    rows = []
    for now in pd.date_range(real.index.min().normalize() + pd.Timedelta(days=3), real.index.max().normalize(), freq="D") + pd.Timedelta(hours=12):
        shown = model_aqi.get(now)
        known = mean24.get(now - pd.Timedelta(hours=lag_hours))
        truth = mean24.get(now)
        if shown is None or pd.isna(shown) or pd.isna(known) or pd.isna(truth):
            continue
        rows.append({"shown": rank(shown), "known": rank(sub_index("pm2_5", known)), "truth": rank(sub_index("pm2_5", truth))})
    if len(rows) < 14:
        return None
    t = pd.DataFrame(rows)
    fired = t[t.known > t.shown]
    used = t[["shown", "known"]].max(axis=1)
    return {"days": len(t), "fired": len(fired), "fired_right": int((fired.truth > fired.shown).sum()),
            "under_before": int((t.shown < t.truth).sum()), "under_after": int((used < t.truth).sum()),
            "over_before": int((t.shown > t.truth).sum()), "over_after": int((used > t.truth).sum())}
