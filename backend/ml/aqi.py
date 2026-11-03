"""India's National AQI (CPCB).

Sources, read 2026-11-04:
- Method: "How is AQI calculated?", CPCB, https://airquality.cpcb.gov.in/ccr_docs/How_AQI_Calculated.pdf
- Breakpoints: CPCB Table 3.1 (AQI scale 0-500), as reproduced at
  https://app.cpcbccr.com/ccr_docs/How_AQI_Calculated.pdf, which describes itself as a reference
  copy of the official sheet.

Method: sub-index from the 24-hour average (8-hour for CO and O3), running averages, at least 16
hours of data per sub-index, AQI = worst sub-index, and at least 3 pollutants including PM2.5 or
PM10. Above 208 ug/m3 of 8-hour O3, the 1-hour value is used.

ASSUMPTION: CPCB prints the Severe band as open-ended ("250+"). The top concentration of each
Severe band below is the one commonly used by AQI calculators, not from the CPCB sheet. It only
affects values above 400, and the result is capped at 500.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

BANDS = [(0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500)]

# (low, high) per band, ug/m3 except CO in mg/m3. The last tuple is the Severe band (see ASSUMPTION).
BREAKPOINTS: dict[str, list[tuple[float, float]]] = {
    "pm10": [(0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (431, 510)],
    "pm2_5": [(0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (251, 380)],
    "no2": [(0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (401, 520)],
    "o3": [(0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (749, 1000)],
    "co": [(0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34), (34.1, 51)],
    "so2": [(0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1601, 2400)],
}
DECIMALS = {"co": 1}  # CPCB truncates Cp; bands step by 1, or by 0.1 for CO

# Names from the CPCB sheet. Colours are the ones usually used on the CPCB scale; the sheet's text
# does not list hex values.
CATEGORIES = [
    ("Good", "#00B050"), ("Satisfactory", "#92D050"), ("Moderately Polluted", "#FFFF00"),
    ("Poor", "#FF9900"), ("Very Poor", "#FF0000"), ("Severe", "#C00000"),
]
LABELS = {"pm2_5": "PM2.5", "pm10": "PM10", "no2": "NO2", "o3": "O3", "co": "CO", "so2": "SO2"}


def truncate(pollutant: str, value: float) -> float:
    factor = 10 ** DECIMALS.get(pollutant, 0)
    return math.floor(value * factor + 1e-9) / factor


def sub_index(pollutant: str, value: float | None) -> int | None:
    """CPCB linear sub-index for one concentration, or None for missing or negative input."""
    if value is None or pd.isna(value) or value < 0:
        return None
    cp = truncate(pollutant, float(value))
    for (bp_lo, bp_hi), (i_lo, i_hi) in zip(BREAKPOINTS[pollutant], BANDS):
        if cp <= bp_hi:
            return round((i_hi - i_lo) / (bp_hi - bp_lo) * (cp - bp_lo) + i_lo)
    return 500


def category(aqi: float | None) -> tuple[str, str] | None:
    if aqi is None or pd.isna(aqi):
        return None
    for (_, hi), cat in zip(BANDS, CATEGORIES):
        if aqi <= hi:
            return cat
    return CATEGORIES[-1]


@dataclass
class AqiResult:
    aqi: int | None
    dominant: str | None
    sub_indices: dict[str, int]


def overall(sub_indices: dict[str, int | None]) -> AqiResult:
    """Apply CPCB's validity rule, then take the worst sub-index."""
    valid = {k: v for k, v in sub_indices.items() if v is not None}
    if len(valid) < 3 or not ({"pm2_5", "pm10"} & valid.keys()):
        return AqiResult(None, None, valid)
    dominant = max(valid, key=valid.get)
    return AqiResult(valid[dominant], dominant, valid)


COLUMNS = {"pm2_5": "pm2_5", "pm10": "pm10", "no2": "nitrogen_dioxide", "so2": "sulphur_dioxide",
           "o3": "ozone", "co": "carbon_monoxide"}


def running_means(df: pd.DataFrame) -> pd.DataFrame:
    """Hourly frame of Open-Meteo pollutants -> CPCB running averages.

    Returns the concentrations the sub-indices use: 24 h (min 16 h), or 8 h (min 6 h) for CO and
    O3. Open-Meteo reports CO in ug/m3, CPCB in mg/m3. The 6-hour minimum for 8-hour windows is our
    choice, scaling CPCB's 16-of-24 rule; CPCB's sheet does not state one.
    """
    out = pd.DataFrame(index=df.index)
    for key, col in COLUMNS.items():
        series = df[col] / 1000.0 if key == "co" else df[col]
        window, minimum = (8, 6) if key in ("co", "o3") else (24, 16)
        out[key] = series.rolling(window, min_periods=minimum).mean()
    out["o3_1h"] = df["ozone"]
    return out


def aqi_series(df: pd.DataFrame) -> pd.DataFrame:
    """Hourly AQI on CPCB running averages. Returns columns aqi and dominant."""
    means = running_means(df)
    rows = []
    for _, row in means.iterrows():
        subs = {k: sub_index(k, row[k]) for k in COLUMNS}
        if not pd.isna(row["o3"]) and row["o3"] > 208:
            subs["o3"] = sub_index("o3", row["o3_1h"])
        res = overall(subs)
        rows.append((res.aqi, res.dominant))
    return pd.DataFrame(rows, index=df.index, columns=["aqi", "dominant"])
