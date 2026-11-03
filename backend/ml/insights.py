"""Plain-words insights drawn from each city's own record.

Every function returns None, or says so in words, when the data doesn't support a claim, so a city
is never told something that is only true elsewhere. Values come from Open-Meteo's model, so patterns
are more reliable than exact levels.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .history import same_date_in_year, season_start

VERY_POOR_FROM = 300  # "above AQI 300" means Very Poor or Severe
STILL_KMH, WINDY_KMH, RAIN_MM = 6.0, 10.0, 2.0
INDIA_LIMIT, WHO_LIMIT = 60.0, 15.0
MIN_WEATHER_DAYS, MIN_RAIN_DAYS, MIN_BAD_DAYS = 20, 10, 5
WINTER_MONTHS = (10, 11, 12, 1, 2)


def short_date(day: date) -> str:
    return f"{day.day} {day:%b}"


def winter_outlook(closing: pd.Series, cut: date, city: str) -> dict | None:
    """How past winters split around this calendar date. `closing` is daily AQI on midnight stamps.
    Only full winters (1 Oct to 28 Feb) count, and only while it is winter now."""
    start = season_start(cut)
    if not date(start.year, 10, 1) <= cut <= date(start.year + 1, 2, 28):
        return None
    winters = []
    for year in range(closing.index.min().year, start.year):
        first, last = pd.Timestamp(year, 10, 1), pd.Timestamp(year + 1, 2, 28)
        if closing.index.min() > first or closing.index.max() < last:
            continue
        season = closing.loc[first:last].dropna()
        if season.empty:
            continue
        then = pd.Timestamp(same_date_in_year(cut, year if cut.month >= 10 else year + 1))
        bad = season[season > VERY_POOR_FROM]
        worst = season.idxmax()
        winters.append({"winter": f"{year}-{str(year + 1)[2:]}", "before": int((bad.index <= then).sum()),
                        "after": int((bad.index > then).sum()), "worst_date": worst.date().isoformat(),
                        "worst_aqi": int(season.max())})
    if not winters:
        return None
    total = sum(w["before"] + w["after"] for w in winters)
    later = sum(w["after"] for w in winters)
    n = len(winters)
    if total < MIN_BAD_DAYS:
        return {"winters": winters, "total": total, "later": later, "ahead": False,
                "summary": f"{city} rarely goes above AQI 300: {total} days across the last {n} winters."}
    ahead = later / total >= 0.6
    return {"winters": winters, "total": total, "later": later, "ahead": ahead,
            "summary": f"In the last {n} winters, {later} of {total} days above AQI 300 came after {short_date(cut)}."}


def weather_levers(air: pd.DataFrame, wx: pd.DataFrame) -> dict | None:
    """How PM2.5 differs on still and windy winter days, and the day after rain."""
    daily = pd.DataFrame({"pm": air["pm2_5"].resample("D").mean(), "wind": wx["wind_speed_10m"].resample("D").mean(),
                          "rain": wx["precipitation"].resample("D").sum()}).dropna()
    winter = daily[daily.index.month.isin(WINTER_MONTHS)]
    still, windy = winter[winter.wind < STILL_KMH], winter[winter.wind >= WINDY_KMH]
    if len(still) < MIN_WEATHER_DAYS or len(windy) < MIN_WEATHER_DAYS:
        return None
    out = {"still_pm": round(float(still.pm.mean())), "still_days": len(still), "windy_pm": round(float(windy.pm.mean())),
           "windy_days": len(windy), "rain": None,
           "summary": f"Winter days with wind under {STILL_KMH:.0f} km/h averaged {still.pm.mean():.0f} µg/m³ of PM2.5. "
                      f"Days at {WINDY_KMH:.0f} km/h or more averaged {windy.pm.mean():.0f}."}
    following = (daily.pm.shift(-1) / daily.pm).reindex(winter.index)
    rained = winter.rain >= RAIN_MM
    if rained.sum() >= MIN_RAIN_DAYS:
        change = float(following[rained].median())
        days = int(rained.sum())
        words = (f"The day after rain of {RAIN_MM:.0f} mm or more, PM2.5 was typically {(1 - change) * 100:.0f}% lower ({days} rain days)."
                 if change <= 0.95 else f"Rain made no clear difference the next day ({days} rain days).")
        out["rain"] = {"days": days, "next_day_ratio": round(change, 2), "summary": words}
    return out


def relief_ahead(wx: pd.DataFrame, now: pd.Timestamp) -> dict | None:
    """Forecast wind and rain by day, and the first day that crosses a threshold that has helped before."""
    future = wx.loc[wx.index > now]
    if future.empty:
        return None
    days = []
    for day, hours in future.groupby(future.index.date):
        if len(hours) < 6:
            continue
        wind, rain = float(hours["wind_speed_10m"].mean()), float(hours["precipitation"].sum())
        windy, wet = wind >= WINDY_KMH, rain >= RAIN_MM
        verdict = "Rain could help" if wet else "Wind could help" if windy else "Still air" if wind < STILL_KMH else "Light wind"
        days.append({"date": day.isoformat(), "wind_kmh": round(wind, 1), "rain_mm": round(rain, 1),
                     "mixing_layer_m": round(float(hours["boundary_layer_height"].mean())), "verdict": verdict,
                     "relief": bool(windy or wet)})
    if not days:
        return None
    first = next((d for d in days if d["relief"]), None)
    last = date.fromisoformat(days[-1]["date"])
    if first:
        words = f"{first['verdict']} on {short_date(date.fromisoformat(first['date']))}."
    else:
        words = f"No strong wind or rain is forecast through {short_date(last)}, so don't expect a clear-out from the weather."
    return {"days": days, "summary": words}


def days_over_limit(table: pd.DataFrame, cut: date, city: str) -> dict | None:
    """Days with mean PM2.5 over India's and the WHO's 24-hour limits, this season and on the same dates before."""
    start = season_start(cut)
    rows = []
    for year in range(table.index.min().year, start.year + 1):
        first = pd.Timestamp(year, 10, 1)
        if table.index.min() > first:
            continue
        end = pd.Timestamp(same_date_in_year(cut, year if cut.month >= 10 else year + 1))
        pm = table.loc[first:end, "pm2_5"].dropna()
        if len(pm):
            rows.append({"season": year, "days": len(pm), "over_india": int((pm > INDIA_LIMIT).sum()),
                         "over_who": int((pm > WHO_LIMIT).sum())})
    if not rows or rows[-1]["season"] != start.year:
        return None
    now, earlier = rows[-1], rows[:-1]
    india = f"{city} was over it on {now['over_india']} of {now['days']} days this season"
    if earlier and now["over_india"] > max(r["over_india"] for r in earlier):
        india += f", the most for these dates in our record, which starts in {earlier[0]['season']}"
    return {"seasons": rows, "india_summary": india + ".",
            "who_summary": f"{city} was over it on {now['over_who']} of {now['days']} days this season."}


def timing_saving(pm: pd.Series, start: str, end: str) -> dict | None:
    """PM2.5 in the best window against the worst 2 waking hours of that same day."""
    window = pm.loc[(pm.index >= pd.Timestamp(start)) & (pm.index < pd.Timestamp(end))].dropna()
    day = pm[pm.index.date == pd.Timestamp(start).date()].dropna()
    awake = day[(day.index.hour >= 6) & (day.index.hour < 22)]
    worst = awake.rolling(2).mean().max()
    if window.empty or pd.isna(worst) or window.mean() <= 0:
        return None
    best = float(window.mean())
    ratio = float(worst) / best
    if ratio < 1.15:
        return {"best_pm": round(best), "worst_pm": round(float(worst)), "ratio": round(ratio, 1),
                "summary": "Timing makes little difference today: the air stays much the same through the day."}
    return {"best_pm": round(best), "worst_pm": round(float(worst)), "ratio": round(ratio, 1),
            "summary": f"The day's worst 2 hours have about {ratio:.1f}× the PM2.5 of this window ({float(worst):.0f} vs {best:.0f} µg/m³)."}
