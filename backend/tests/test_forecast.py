import numpy as np
import pandas as pd

from ml.forecast import (HOLDOUT_DAYS, TRAIN_DAYS, best_window, decide, features, hourly_index, score,
                         score_snapshots, split_bounds)


def _inputs(hours=200):
    idx = pd.date_range("2026-10-01", periods=hours, freq="h")
    air = pd.DataFrame({"pm2_5": np.arange(hours, dtype=float), "pm10": np.arange(hours, dtype=float) * 2}, index=idx)
    wx = pd.DataFrame({"wind_speed_10m": 5.0, "wind_direction_10m": 90.0, "relative_humidity_2m": 50.0,
                       "precipitation": 0.0}, index=idx)
    return air, wx, pd.Series(500.0, index=idx)


def test_features_use_nothing_after_the_origin():
    air, wx, blh = _inputs()
    origin = air.index[100]
    before = features(air, wx, blh, pd.DatetimeIndex([origin]))
    changed = air.copy()
    changed.loc[changed.index > origin, ["pm2_5", "pm10"]] = 99999.0
    after = features(changed, wx, blh, pd.DatetimeIndex([origin]))
    pd.testing.assert_frame_equal(before, after)


def test_day_ago_feature_is_24h_before_target():
    air, wx, blh = _inputs()
    origin = air.index[100]
    frame = features(air, wx, blh, pd.DatetimeIndex([origin]))
    row = frame[frame.horizon == 5].iloc[0]
    assert row.pm25_day_ago == 100 + 5 - 24 and row.pm25_now == 100


def test_split_is_60_then_7_whole_days():
    train_start, holdout_start = split_bounds(pd.Timestamp("2026-11-03 23:00"))
    assert holdout_start == pd.Timestamp("2026-10-28")
    assert (pd.Timestamp("2026-11-04") - holdout_start).days == HOLDOUT_DAYS
    assert (holdout_start - train_start).days == TRAIN_DAYS


def test_score_skips_missing_values():
    res = score(np.array([1.0, np.nan, 5.0]), np.array([2.0, 3.0, 2.0]))
    assert res == {"mae": 2.0, "rmse": 2.24, "n": 2}


def test_hourly_index_takes_worse_particle():
    assert hourly_index(45, 20) == 75
    assert hourly_index(None, None) is None


def _series(values, start="2026-11-04 06:00"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="h"), dtype=float)


def test_best_window_finds_lowest_pair():
    res = best_window(_series([300, 280, 120, 110, 290, 300]))
    assert res == {"start": "2026-11-04T08:00:00", "end": "2026-11-04T10:00:00", "mean_index": 115}


def test_best_window_ignores_night_and_gaps():
    night = _series([10, 10, 10, 10, 300, 310, 320], start="2026-11-04 02:00")
    assert best_window(night)["start"] == "2026-11-04T06:00:00"
    gap = _series([10, 300, 300, 200, 210]).drop(pd.Timestamp("2026-11-04 07:00"))
    assert best_window(gap)["start"] == "2026-11-04T09:00:00"


def test_best_window_moves_to_tomorrow_when_today_is_over():
    late = _series([100] * 12, start="2026-11-04 21:00")
    assert best_window(late)["start"].startswith("2026-11-05T06")
    assert best_window(pd.Series(dtype=float)) is None


def test_snapshots_score_only_past_hours_and_keep_the_earliest_forecast():
    now = pd.Timestamp("2026-11-04 12:00")
    first = pd.DataFrame({"pm2_5": _series([100.0] * 12, "2026-11-04 03:00")})
    second = pd.DataFrame({"pm2_5": _series([50.0] * 12, "2026-11-04 03:00")})
    truth = _series([100.0] * 12, "2026-11-04 03:00")
    res = score_snapshots({pd.Timestamp("2026-11-04 02:00"): first, pd.Timestamp("2026-11-04 05:00"): second},
                          truth, "pm2_5", now)
    assert res == {"mae": 0.0, "rmse": 0.0, "n": 10}  # 03:00-12:00 only, all from the first run


def test_decide_defaults_to_open_meteo_without_evidence():
    good, bad = {"mae": 5, "n": 50}, {"mae": 9, "n": 50}
    assert decide(None, None)[0] == "open_meteo"
    assert decide({"mae": 1, "n": 5}, {"mae": 9, "n": 5})[0] == "open_meteo"
    assert decide(good, bad)[0] == "ours"
    assert decide(bad, good)[0] == "open_meteo"
    assert decide(good, good)[0] == "open_meteo"


def test_fire_series_counts_one_satellite_and_only_the_past():
    from ml.forecast import fire_series
    idx = pd.date_range("2026-11-01", periods=72, freq="h")
    wx = pd.DataFrame({"wind_speed_10m": 10.0, "wind_direction_10m": 315.0}, index=idx)
    at = pd.Timestamp("2026-11-02 12:00")
    fires = pd.DataFrame({"latitude": [29.8, 29.8, 29.8], "longitude": [75.9, 75.9, 75.9],
                          "time": [at - pd.Timedelta(hours=6), at - pd.Timedelta(hours=6), at + pd.Timedelta(hours=6)],
                          "confidence": "n", "satellite": ["N", "N20", "N"]})
    assert fire_series(fires, 28.61, 77.21, wx, pd.DatetimeIndex([at])).iloc[0] == 1
