"""How the model compares with real CPCB stations over the same hours."""
from __future__ import annotations

import pandas as pd

MIN_HOURS = 168  # a week of paired hours before we say anything
AWAKE = range(6, 22)


def hour_range(start: int) -> str:
    def label(h: int) -> str:
        return "12 pm" if h == 12 else f"{h} am" if h < 12 else f"{h - 12} pm"
    return f"{label(start)} to {label(start + 2)}"


def compare(stations: pd.DataFrame, model: pd.Series, city: str) -> dict | None:
    """Mean of the CPCB stations each hour against the model. Other providers are left out."""
    cpcb = stations[stations.provider == "CPCB"]
    both = pd.DataFrame({"real": cpcb.groupby("time").pm2_5.mean(), "model": model}).dropna()
    if len(both) < MIN_HOURS:
        return None
    real, modelled = float(both.real.mean()), float(both.model.mean())
    ratio = modelled / real
    daily = both.resample("D").mean().dropna()
    r = float(daily.real.corr(daily.model))
    if 0.9 <= ratio <= 1.1:
        level = f"The model's average was close to nearby CPCB stations in {city} ({modelled:.0f} vs {real:.0f} µg/m³)."
    elif ratio > 1.1:
        level = f"The model read about {(ratio - 1) * 100:.0f}% above nearby CPCB stations in {city} ({modelled:.0f} vs {real:.0f} µg/m³)."
    else:
        level = f"The model read about {(1 - ratio) * 100:.0f}% below nearby CPCB stations in {city} ({modelled:.0f} vs {real:.0f} µg/m³)."
    follow = "closely" if r >= 0.7 else "partly" if r >= 0.4 else "poorly"
    worst = both[both.real >= both.real.quantile(0.9)]
    worst_real, worst_model = float(worst.real.mean()), float(worst.model.mean())
    if worst_model < worst_real * 0.85:
        peaks = (f"It understates the worst air: in the worst 10% of hours, stations measured {worst_real:.0f} µg/m³ "
                 f"while the model said {worst_model:.0f}.")
    else:
        peaks = f"In the worst 10% of hours it held up: stations measured {worst_real:.0f} µg/m³ and the model said {worst_model:.0f}."
    return {"hours": len(both), "stations": int(cpcb.station.nunique()), "real_pm": round(real), "model_pm": round(modelled),
            "ratio": round(ratio, 2), "daily_r": round(r, 2), "from": str(both.index.min().date()), "to": str(both.index.max().date()),
            "worst_real": round(worst_real), "worst_model": round(worst_model), "understates_peaks": worst_model < worst_real * 0.85,
            "peaks": peaks, "summary": level, "tracking": f"It followed the day-to-day ups and downs {follow} (r = {r:.2f} across {len(daily)} days)."}


def cleanest_window(stations: pd.DataFrame) -> dict | None:
    """The cleanest 2 waking hours on average at CPCB stations."""
    cpcb = stations[stations.provider == "CPCB"]
    if cpcb.time.nunique() < MIN_HOURS:
        return None
    by_hour = cpcb.groupby(cpcb.time.dt.hour).pm2_5.mean()
    by_hour = by_hour[by_hour.index.isin(AWAKE)]
    pairs = by_hour.rolling(2).mean().dropna()
    if pairs.empty:
        return None
    start = int(pairs.idxmin()) - 1
    return {"start_hour": start, "pm": round(float(pairs.min())),
            "summary": f"At CPCB stations this season, the cleanest hours have averaged {hour_range(start)}."}
