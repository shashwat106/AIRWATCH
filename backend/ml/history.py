"""Comparisons with earlier days and seasons, all on one method and one source.

Every figure here is Open-Meteo modelled data run through the same CPCB calculation, so past and
present are like for like. They are not station records. A day counts only with at least 16 hours
of data, CPCB's minimum for a sub-index.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .aqi import aqi_series, category
from .sources import mean_wind, upwind_fires

MIN_HOURS = 16
MIN_CORRELATION_DAYS = 14
BAD_DAYS = {"poor": (201, 300), "very_poor": (301, 400), "severe": (401, 500)}


def same_date_in_year(day: date, year: int) -> date:
    """The same calendar date in another year; 29 Feb maps to 28 Feb."""
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


def season_start(day: date) -> date:
    """Pollution season starts on 1 October; January to September belong to last year's start."""
    return date(day.year if day.month >= 10 else day.year - 1, 10, 1)


def season_windows(day: date) -> tuple[tuple[date, date], tuple[date, date]]:
    """(this season so far, the same dates one year earlier), both inclusive."""
    start = season_start(day)
    return (start, day), (date(start.year - 1, 10, 1), same_date_in_year(day, day.year - 1))


def daily_table(air: pd.DataFrame, aqi: pd.Series | None = None) -> pd.DataFrame:
    """One row per calendar day: AQI at 23:00 (the 24-hour running value for that whole day), mean
    particles, and hours of data. Days under MIN_HOURS get NaN rather than a partial figure."""
    aqi = aqi_series(air)["aqi"] if aqi is None else aqi
    groups = air.groupby(air.index.date)
    table = pd.DataFrame({"pm2_5": groups["pm2_5"].mean(), "pm10": groups["pm10"].mean(),
                          "hours": groups["pm2_5"].count()})
    table.index = pd.to_datetime(table.index)
    closing = aqi[aqi.index.hour == 23]
    closing.index = closing.index.normalize()
    table["aqi"] = pd.to_numeric(closing, errors="coerce").reindex(table.index)
    table.loc[table.hours < MIN_HOURS, ["pm2_5", "pm10", "aqi"]] = np.nan
    return table


def hour_table(air: pd.DataFrame, aqi: pd.Series, hour: int) -> pd.DataFrame:
    """One row per day for the 24 hours ending at `hour`, so a part-finished today compares fairly
    with earlier dates: every row covers the same window of the day."""
    means = air[["pm2_5", "pm10"]].rolling(24, min_periods=MIN_HOURS).mean()
    table = means[means.index.hour == hour].copy()
    table["hours"] = air["pm2_5"].rolling(24, min_periods=1).count().reindex(table.index)
    table["aqi"] = pd.to_numeric(aqi, errors="coerce").reindex(table.index)
    table.index = table.index.normalize()
    return table


def daily_upwind(fires: pd.DataFrame, lat: float, lon: float, wx: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """Upwind fire detections for each day, using that day's mean wind. Calm days are NaN."""
    counts = {}
    for day in days:
        hours = wx.loc[day:day + pd.Timedelta(hours=23)]
        speed, direction = mean_wind(hours["wind_speed_10m"], hours["wind_direction_10m"])
        end = day + pd.Timedelta(hours=23, minutes=59)
        stats = upwind_fires(fires, lat, lon, speed, direction, end, hours=24)
        # With no usable wind, upwind has no meaning: the count is unknown, not zero.
        counts[day] = float("nan") if stats.calm else stats.upwind_count
    return pd.Series(counts, dtype=float)


def _row(table: pd.DataFrame, day: date) -> dict | None:
    ts = pd.Timestamp(day)
    if ts not in table.index or pd.isna(table.at[ts, "aqi"]):
        return None
    return {"date": day.isoformat(), "aqi": int(table.at[ts, "aqi"]), "pm2_5": round(float(table.at[ts, "pm2_5"]), 1)}


def ratio_words(now: float, then: float, what: str) -> str:
    if then <= 0:
        return f"{what} cannot be compared: the earlier value is zero."
    ratio = now / then
    if 0.95 <= ratio <= 1.05:
        return f"{what} is about the same."
    if ratio > 1:
        return f"{what} is {ratio:.1f}× the earlier value."
    return f"{what} is {(1 - ratio) * 100:.0f}% lower."


def _fires_on(fires: pd.Series, day: date) -> int | None:
    value = fires.get(pd.Timestamp(day))
    return None if value is None or pd.isna(value) else int(value)


def compare_years(table: pd.DataFrame, day: date, fires: pd.Series | None = None) -> dict:
    """The given complete day against the same date one and two years earlier."""
    today = _row(table, day)
    out = {"day": today, "earlier": []}
    for back in (1, 2):
        then_day = same_date_in_year(day, day.year - back)
        then = _row(table, then_day)
        if then is None:
            out["earlier"].append({"date": then_day.isoformat(), "available": False})
            continue
        then["available"] = True
        if today:
            then["summary"] = ratio_words(today["pm2_5"], then["pm2_5"], "PM2.5")
        if fires is not None:
            then["upwind_fires"] = _fires_on(fires, then_day)
        out["earlier"].append(then)
    if fires is not None and today:
        today["upwind_fires"] = _fires_on(fires, day)
    return out


def recent_averages(table: pd.DataFrame, day: date) -> dict:
    """The day against the averages of the 7 and 30 days before it (the day itself excluded)."""
    today = _row(table, day)
    out = {"day": today}
    for n in (7, 30):
        window = table.loc[pd.Timestamp(day - timedelta(days=n)):pd.Timestamp(day - timedelta(days=1))]
        days = int(window.aqi.notna().sum())
        entry = {"days_with_data": days, "aqi": None, "pm2_5": None}
        if days:
            entry["aqi"], entry["pm2_5"] = round(float(window.aqi.mean())), round(float(window.pm2_5.mean()), 1)
            if today:
                entry["summary"] = ratio_words(today["pm2_5"], entry["pm2_5"], "PM2.5")
        out[f"last_{n}_days"] = entry
    return out


def season_stats(table: pd.DataFrame, start: date, end: date, fires: pd.Series | None = None) -> dict:
    window = table.loc[pd.Timestamp(start):pd.Timestamp(end)]
    aqi = window.aqi.dropna()
    expected = (end - start).days + 1
    stats = {"start": start.isoformat(), "end": end.isoformat(), "days_with_data": int(len(aqi)),
             "days_expected": expected, "mean_aqi": round(float(aqi.mean())) if len(aqi) else None}
    for name, (lo, hi) in BAD_DAYS.items():
        stats[f"{name}_days"] = int(aqi.between(lo, hi).sum())
    stats["upwind_fires"] = None
    stats["fire_days_counted"] = None
    if fires is not None:
        counted = fires.loc[pd.Timestamp(start):pd.Timestamp(end)].dropna()
        stats["upwind_fires"] = int(counted.sum())
        stats["fire_days_counted"] = int(len(counted))
    return stats


def fire_words(now: dict, before: dict, mixing_now: float | None = None, mixing_before: float | None = None) -> str | None:
    """Plain-words comparison of upwind fires. Weather is named only when the numbers support it."""
    a, b = now.get("upwind_fires"), before.get("upwind_fires")
    if a is None or b is None:
        return None
    gap = a - b
    if gap == 0:
        text = f"The same number of upwind fire detections as last year ({a:,})"
    else:
        text = f"{abs(gap):,} {'fewer' if gap < 0 else 'more'} upwind fire detections than the same dates last year ({a:,} vs {b:,})"
    higher = (now.get("mean_aqi") or 0) > (before.get("mean_aqi") or 0)
    if gap < 0 and higher:
        text += ", yet AQI is higher"
        if mixing_now and mixing_before and mixing_now < mixing_before * 0.95:
            return f"{text}. The mixing layer averaged {mixing_now:,.0f} m against {mixing_before:,.0f} m, so air had less room to disperse."
    return f"{text}."

def season_comparison(table: pd.DataFrame, day: date, fires: pd.Series | None = None) -> dict:
    (a, b), (c, d) = season_windows(day)
    now, before = season_stats(table, a, b, fires), season_stats(table, c, d, fires)
    words = None
    if now["mean_aqi"] and before["mean_aqi"]:
        diff = now["mean_aqi"] - before["mean_aqi"]
        change = "the same as" if diff == 0 else f"{abs(diff)} points {'higher' if diff > 0 else 'lower'} than"
        words = f"Average AQI this season is {change} the same dates last year ({now['mean_aqi']} vs {before['mean_aqi']})."
    return {"this_season": now, "last_season": before, "summary": words}


def season_lines(table: pd.DataFrame, day: date) -> list[dict]:
    """Daily AQI for both seasons on shared month-day labels, for the line chart."""
    (a, b), (c, d) = season_windows(day)
    now = table.loc[pd.Timestamp(a):pd.Timestamp(b), "aqi"]
    before = table.loc[pd.Timestamp(c):pd.Timestamp(d), "aqi"]
    rows = []
    for offset in range((b - a).days + 1):
        ts = pd.Timestamp(a + timedelta(days=offset))
        prev = pd.Timestamp(same_date_in_year(ts.date(), ts.year - 1))
        rows.append({"label": ts.strftime("%d %b"),
                     "this_season": None if pd.isna(now.get(ts, np.nan)) else int(now[ts]),
                     "last_season": None if pd.isna(before.get(prev, np.nan)) else int(before[prev])})
    return rows


def correlation_strength(r: float) -> str:
    size = abs(r)
    return "weak" if size < 0.3 else "moderate" if size < 0.6 else "strong"


def fire_link(table: pd.DataFrame, fires: pd.Series | None, start: date, end: date) -> dict:
    """Pearson correlation of daily upwind fires (lag 0-2 days) with the next day's PM2.5."""
    if fires is None:
        return {"available": False, "reason": "Needs the FIRMS fire archive, which needs a FIRMS key."}
    pm = table["pm2_5"].loc[pd.Timestamp(start):pd.Timestamp(end)]
    results, pairs = [], {}
    for lag in (0, 1, 2):
        paired = pd.DataFrame({"pm": pm, "fires": fires.reindex(pm.index - pd.Timedelta(days=1 + lag)).values},
                              index=pm.index).dropna()
        pairs[lag] = paired
        if len(paired) < MIN_CORRELATION_DAYS or paired.fires.std() == 0 or paired.pm.std() == 0:
            results.append({"lag_days": lag, "r": None, "n": int(len(paired))})
        else:
            results.append({"lag_days": lag, "r": round(float(paired.pm.corr(paired.fires)), 2), "n": int(len(paired))})
    usable = [x for x in results if x["r"] is not None]
    if not usable:
        return {"available": False, "reason": f"Fewer than {MIN_CORRELATION_DAYS} days of paired data.", "lags": results}
    best = max(usable, key=lambda x: abs(x["r"]))
    words = (f"The link between upwind fires and next-day PM2.5 this season is {correlation_strength(best['r'])} "
             f"(r = {best['r']}, {best['n']} days, fires {best['lag_days']} day(s) earlier). "
             "Correlation does not prove cause: fires and calm weather often arrive together.")
    points = [{"fires": int(r.fires), "pm2_5": round(float(r.pm), 1)} for r in pairs[best["lag_days"]].itertuples()]
    return {"available": True, "lags": results, "best": best, "summary": words, "points": points}


def worst_days(table: pd.DataFrame, start: date, end: date, n: int = 3) -> list[dict]:
    window = table.loc[pd.Timestamp(start):pd.Timestamp(end)].dropna(subset=["aqi"])
    top = window.sort_values("aqi", ascending=False).head(n)
    return [{"date": ts.date().isoformat(), "aqi": int(row.aqi), "pm2_5": round(float(row.pm2_5), 1),
             "category": category(row.aqi)[0]} for ts, row in top.iterrows()]
