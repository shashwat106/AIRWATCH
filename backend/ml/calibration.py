"""Tools for testing corrections of modelled PM2.5 against CPCB stations.

The global model squeezes values towards the middle, so it understates the worst hours. These
functions fit and score possible corrections on days they never saw. None is used in the app: only
Ghaziabad passed both tests, so the app warns from station readings instead (see warning.py).
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from .aqi import sub_index

PARAMS = dict(n_estimators=250, learning_rate=0.04, num_leaves=15, min_child_samples=40, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=2.0, verbose=-1, random_state=42, n_jobs=2)
CATEGORY_EDGES = (50, 100, 200, 300, 400)


def features(air: pd.DataFrame, wx: pd.DataFrame) -> pd.DataFrame:
    """Hourly inputs. Everything here is available for past, live and forecast hours."""
    pm = air["pm2_5"]
    w = wx.reindex(air.index)
    return pd.DataFrame({
        "pm25": pm, "pm10": air["pm10"], "pm25_mean24": pm.rolling(24, min_periods=12).mean(),
        "pm25_mean6": pm.rolling(6, min_periods=3).mean(), "ratio": pm / air["pm10"].replace(0, np.nan),
        "no2": air["nitrogen_dioxide"], "co": air["carbon_monoxide"], "dust": air["dust"], "hour": air.index.hour,
        "wind": w["wind_speed_10m"], "wind_mean24": w["wind_speed_10m"].rolling(24, min_periods=12).mean(),
        "humidity": w["relative_humidity_2m"], "mixing": w["boundary_layer_height"],
        "mixing_mean24": w["boundary_layer_height"].rolling(24, min_periods=12).mean(),
    }, index=air.index)


def station_mean(stations: pd.DataFrame) -> pd.Series:
    """Hourly mean of a city's CPCB stations. Each station is first capped at its own 99.9th percentile,
    which removes obvious spikes without touching real smog days."""
    cpcb = stations[stations.provider == "CPCB"]
    caps = cpcb.groupby("station").pm2_5.transform(lambda s: s.quantile(0.999))
    return cpcb[cpcb.pm2_5 <= caps].groupby("time").pm2_5.mean()


def fit(x: pd.DataFrame, y: pd.Series) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(x, np.log1p(y))
    return model


def predict(model, x: pd.DataFrame) -> pd.Series:
    return pd.Series(np.expm1(model.predict(x)), index=x.index).clip(lower=0)


def linear_fit(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    """log(station) = a + b log(model)."""
    b, a = np.polyfit(np.log1p(x), np.log1p(y), 1)
    return float(a), float(b)


def quantile_map(train_model: pd.Series, train_real: pd.Series, values: pd.Series) -> pd.Series:
    """Move each value to the station value at the same rank. Beyond the fitted range the top gap carries on."""
    q = np.linspace(0.005, 0.995, 100)
    src, dst = np.quantile(train_model, q), np.quantile(train_real, q)
    return pd.Series(np.interp(values, src, dst) + np.clip(values - src[-1], 0, None), index=values.index)


def category(pm: float) -> int:
    index = sub_index("pm2_5", pm)
    return next((i for i, edge in enumerate(CATEGORY_EDGES) if index <= edge), 5)


def score(pred: pd.Series, real: pd.Series) -> dict:
    """Hourly error, error on the worst 10% of measured hours, and daily category agreement."""
    both = pd.DataFrame({"pred": pred, "real": real}).dropna()
    worst = both[both.real >= both.real.quantile(0.9)]
    daily = both.resample("D").mean().dropna()
    cats = pd.DataFrame({"pred": daily.pred.map(category), "real": daily.real.map(category)})
    return {"hours": len(both), "mae": round(float((both.pred - both.real).abs().mean()), 1), "bias": round(float((both.pred - both.real).mean()), 1),
            "worst_pred": round(float(worst.pred.mean())), "worst_real": round(float(worst.real.mean())),
            "worst_mae": round(float((worst.pred - worst.real).abs().mean()), 1), "days": len(cats),
            "under_warn_days": int((cats.pred < cats.real).sum()), "over_warn_days": int((cats.pred > cats.real).sum()),
            "same_category_days": int((cats.pred == cats.real).sum())}


def passes_test(raw: dict, fixed: dict) -> bool:
    """Better on the worst hours, not worse overall, and fewer under-warned days."""
    return (fixed["worst_mae"] < raw["worst_mae"] * 0.9 and fixed["mae"] <= raw["mae"] * 1.05
            and fixed["under_warn_days"] < raw["under_warn_days"])
