"""24-hour PM2.5 and PM10 forecast per city, with an honest evaluation.

What the numbers mean:
- "Truth" is Open-Meteo's own past series (a global model), not station measurements. Scores say how
  well we anticipate that series, not how close anyone gets to real air.
- That past series is stitched from Open-Meteo's own short-range runs and the API keeps no old
  forecasts (pm2_5_previous_dayN is all null), so its forecast cannot be scored on the past 7 days:
  it would be compared with itself. On those 7 days we compare against persistence and the same
  hour yesterday. Open-Meteo itself is compared only through live snapshots (score_snapshots).

No future data is used in testing. Weather features are real archived forecasts issued about a day
ahead (Previous Runs API). Boundary-layer height has no archived forecast, so the value from 24
hours before the target is used, which is known at forecast time.
"""
from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .aqi import sub_index

MODEL_DIR = Path(__file__).resolve().parent / "models"
METRICS_PATH = Path(__file__).resolve().parent / "metrics.json"
TRAIN_DAYS, HOLDOUT_DAYS, HORIZON = 60, 7, 24
TARGETS = ("pm2_5", "pm10")
MIN_SNAPSHOT_HOURS = 12  # below this we do not claim anything against Open-Meteo
WEATHER = ["wind_speed_10m", "wind_direction_10m", "relative_humidity_2m", "precipitation"]
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=20,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=42,
              n_jobs=2)


def features(air: pd.DataFrame, wx_future: pd.DataFrame, blh: pd.Series, origins: pd.DatetimeIndex,
             fires_48h: pd.Series | None = None) -> pd.DataFrame:
    """One row per (origin, horizon). Uses only air values at or before the origin."""
    pm25, pm10 = air["pm2_5"], air["pm10"]
    base = pd.DataFrame({
        "pm25_now": pm25, "pm25_1h": pm25.shift(1), "pm25_3h": pm25.shift(3), "pm25_6h": pm25.shift(6),
        "pm25_12h": pm25.shift(12), "pm25_mean24": pm25.rolling(24, min_periods=16).mean(),
        "pm10_now": pm10, "pm10_mean24": pm10.rolling(24, min_periods=16).mean(),
        "pm_ratio": pm25 / pm10.replace(0, np.nan),
    }).reindex(origins)
    if fires_48h is not None:
        base["fires_48h"] = fires_48h.reindex(origins)
    frames = []
    for h in range(1, HORIZON + 1):
        target = origins + pd.Timedelta(hours=h)
        part = base.copy()
        part["origin"], part["target_time"], part["horizon"] = origins, target, h
        part["hour"], part["weekday"] = target.hour, target.day_of_week
        part["pm25_day_ago"] = pm25.reindex(target - pd.Timedelta(hours=24)).values
        part["pm10_day_ago"] = pm10.reindex(target - pd.Timedelta(hours=24)).values
        part["blh_day_ago"] = blh.reindex(target - pd.Timedelta(hours=24)).values
        wx = wx_future.reindex(target)
        part["wind"], part["humidity"] = wx["wind_speed_10m"].values, wx["relative_humidity_2m"].values
        part["rain"] = wx["precipitation"].values
        rad = np.radians(wx["wind_direction_10m"].values)
        part["wind_sin"], part["wind_cos"] = np.sin(rad), np.cos(rad)
        frames.append(part)
    return pd.concat(frames, ignore_index=True)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in ("origin", "target_time")]


def split_bounds(last_hour: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return (train_start, holdout_start). Whole days, ending at last_hour."""
    holdout_start = last_hour.normalize() + pd.Timedelta(days=1) - pd.Timedelta(days=HOLDOUT_DAYS)
    return holdout_start - pd.Timedelta(days=TRAIN_DAYS), holdout_start


def score(pred: np.ndarray, truth: np.ndarray) -> dict:
    ok = ~(np.isnan(pred) | np.isnan(truth))
    err = pred[ok] - truth[ok]
    return {"mae": round(float(np.abs(err).mean()), 2), "rmse": round(float(np.sqrt((err ** 2).mean())), 2),
            "n": int(ok.sum())}


def fit(frame: pd.DataFrame, truth: pd.Series) -> lgb.LGBMRegressor:
    y = truth.reindex(frame.target_time).values
    ok = ~np.isnan(y)
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(frame.loc[ok, feature_columns(frame)], np.log1p(y[ok]))
    return model


def predict(model: lgb.LGBMRegressor, frame: pd.DataFrame) -> np.ndarray:
    return np.expm1(model.predict(frame[feature_columns(frame)]))


def evaluate_city(air, wx_future, blh, fires_48h=None) -> dict:
    """Train on 60 days, test on the following 7. All test targets come after all training targets."""
    last = air["pm2_5"].dropna().index.max()
    train_start, holdout_start = split_bounds(last)
    train_origins = pd.date_range(train_start, holdout_start - pd.Timedelta(hours=1), freq="3h")
    test_origins = pd.date_range(holdout_start, last - pd.Timedelta(hours=HORIZON), freq="6h")
    train = features(air, wx_future, blh, train_origins, fires_48h)
    train = train[train.target_time < holdout_start]
    test = features(air, wx_future, blh, test_origins, fires_48h)
    truth = air["pm2_5"].reindex(test.target_time).values
    model = fit(train, air["pm2_5"])
    return {
        "train_period": [str(train_start.date()), str((holdout_start - pd.Timedelta(days=1)).date())],
        "test_period": [str(holdout_start.date()), str(last.date())],
        "ours": score(predict(model, test), truth),
        "persistence": score(test.pm25_now.values, truth),
        "same_hour_yesterday": score(test.pm25_day_ago.values, truth),
        "uses_fire_feature": fires_48h is not None,
    }


def hourly_index(pm25: float, pm10: float) -> int | None:
    """Sub-index on one hour's particles. For ranking hours only: not an official AQI,
    which needs 24-hour averages and at least three pollutants."""
    subs = [s for s in (sub_index("pm2_5", pm25), sub_index("pm10", pm10)) if s is not None]
    return max(subs) if subs else None


def best_window(series: pd.Series, start_hour: int = 6, end_hour: int = 22, length: int = 2) -> dict | None:
    """Lowest mean index over `length` consecutive waking hours, on the first day with such a window."""
    series = series.dropna()
    if series.empty:
        return None
    for _, day in series.groupby(series.index.date):
        awake = day[(day.index.hour >= start_hour) & (day.index.hour < end_hour)]
        best = None
        for i in range(len(awake) - length + 1):
            chunk = awake.iloc[i:i + length]
            if chunk.index[-1] - chunk.index[0] != pd.Timedelta(hours=length - 1):
                continue
            if best is None or chunk.mean() < best[0]:
                best = (float(chunk.mean()), chunk.index[0], chunk.index[-1] + pd.Timedelta(hours=1))
        if best:
            return {"start": best[1].isoformat(), "end": best[2].isoformat(), "mean_index": round(best[0])}
    return None


def score_snapshots(snapshots: dict[pd.Timestamp, pd.DataFrame], truth: pd.Series, column: str,
                    now: pd.Timestamp) -> dict | None:
    """Score stored forecasts against the later series, on hours that have since passed.
    Each target hour keeps its earliest forecast, so the score is not flattered by short leads."""
    pairs: dict[pd.Timestamp, float] = {}
    for issued in sorted(snapshots):
        frame = snapshots[issued]
        for t, value in frame[column].items():
            if issued < t <= now and t not in pairs and not pd.isna(value):
                pairs[t] = float(value)
    if not pairs:
        return None
    index = pd.DatetimeIndex(sorted(pairs))
    return score(np.array([pairs[t] for t in index]), truth.reindex(index).values)


def decide(ours: dict | None, open_meteo: dict | None) -> tuple[str, str]:
    """Serve our model only with evidence that it beats Open-Meteo; otherwise show Open-Meteo."""
    if not ours or not open_meteo or min(ours["n"], open_meteo["n"]) < MIN_SNAPSHOT_HOURS:
        return "open_meteo", "Not enough live forecast hours yet to show our model beats Open-Meteo."
    if ours["mae"] < open_meteo["mae"]:
        return "ours", f"Our model's error is lower on {ours['n']} live forecast hours."
    return "open_meteo", f"Open-Meteo's error is lower or equal on {ours['n']} live forecast hours."


def model_path(city_id: str, target: str) -> Path:
    return MODEL_DIR / f"{city_id}_{target}.txt"


def train_final(city_id: str, air, wx_future, blh, fires_48h=None) -> None:
    """Refit on the most recent 60 days for serving. These exact fits are not the ones scored on the
    hold-out, which had to stop 7 days earlier."""
    MODEL_DIR.mkdir(exist_ok=True)
    last = air["pm2_5"].dropna().index.max()
    origins = pd.date_range(last - pd.Timedelta(days=TRAIN_DAYS), last - pd.Timedelta(hours=1), freq="3h")
    frame = features(air, wx_future, blh, origins, fires_48h)
    frame = frame[frame.target_time <= last]
    for target in TARGETS:
        fit(frame, air[target]).booster_.save_model(str(model_path(city_id, target)))


def run_models(city_id: str, air, wx_future, blh, origin: pd.Timestamp) -> pd.DataFrame | None:
    """Forecast the next 24 hours from `origin`. Returns None if no model has been trained."""
    if not all(model_path(city_id, t).exists() for t in TARGETS):
        return None
    frame = features(air, wx_future, blh, pd.DatetimeIndex([origin]))
    out = pd.DataFrame(index=pd.DatetimeIndex(frame.target_time))
    for target in TARGETS:
        booster = lgb.Booster(model_file=str(model_path(city_id, target)))
        out[target] = np.expm1(booster.predict(frame[booster.feature_name()]))
    return out


def save_metrics(metrics: dict) -> None:
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def load_metrics() -> dict:
    return json.loads(METRICS_PATH.read_text(encoding="utf-8")) if METRICS_PATH.exists() else {}
