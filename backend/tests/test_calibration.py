import numpy as np
import pandas as pd

from ml import calibration as cal


def hours(n=480):
    return pd.date_range("2026-01-01", periods=n, freq="h")


def frames(n=480):
    idx = hours(n)
    air = pd.DataFrame({"pm2_5": 100.0, "pm10": 200.0, "nitrogen_dioxide": 30.0, "carbon_monoxide": 800.0, "dust": 5.0}, index=idx)
    wx = pd.DataFrame({"wind_speed_10m": 5.0, "relative_humidity_2m": 60.0, "boundary_layer_height": 300.0}, index=idx)
    return air, wx


def test_features_use_no_future_hours():
    air, wx = frames()
    before = cal.features(air, wx).iloc[:100]
    air.iloc[100:, 0] = 9999.0
    wx.iloc[100:, 0] = 99.0
    pd.testing.assert_frame_equal(before, cal.features(air, wx).iloc[:100])


def test_station_mean_uses_cpcb_only_and_drops_spikes():
    idx = hours(2000)
    a = pd.DataFrame({"time": idx, "pm2_5": 100.0, "provider": "CPCB", "station": "A"})
    a.loc[0, "pm2_5"] = 990.0
    b = pd.DataFrame({"time": idx, "pm2_5": 500.0, "provider": "AirNow", "station": "B"})
    out = cal.station_mean(pd.concat([a, b]))
    assert out.max() == 100 and len(out) == 1999


def test_quantile_map_stretches_towards_station_values():
    rng = np.random.default_rng(1)
    model = pd.Series(rng.uniform(50, 100, 2000))
    real = (model - 50) * 4 + 20  # stations span a much wider range
    out = cal.quantile_map(model, real, pd.Series([50.0, 75.0, 100.0]))
    assert abs(out[0] - 20) < 5 and abs(out[1] - 120) < 8 and abs(out[2] - 220) < 5


def test_category_edges_match_cpcb():
    assert [cal.category(v) for v in (30, 60, 90, 120, 250, 300)] == [0, 1, 2, 3, 4, 5]


def test_score_counts_warnings_by_day():
    idx = hours(72)
    real = pd.Series(np.repeat([100.0, 200.0, 40.0], 24), index=idx)  # Poor, Very Poor, Satisfactory
    pred = pd.Series(np.repeat([100.0, 100.0, 100.0], 24), index=idx)
    s = cal.score(pred, real)
    assert s["days"] == 3 and s["same_category_days"] == 1 and s["under_warn_days"] == 1 and s["over_warn_days"] == 1


def good(**changes):
    return {"mae": 30.0, "worst_mae": 100.0, "under_warn_days": 10} | changes


def test_passes_needs_all_three_conditions():
    raw = good()
    assert cal.passes_test(raw, good(mae=29.0, worst_mae=70.0, under_warn_days=5))
    assert not cal.passes_test(raw, good(mae=29.0, worst_mae=95.0, under_warn_days=5))  # worst hours barely better
    assert not cal.passes_test(raw, good(mae=33.0, worst_mae=70.0, under_warn_days=5))  # worse overall
    assert not cal.passes_test(raw, good(mae=29.0, worst_mae=70.0, under_warn_days=10))  # no fewer under-warned days


def test_apply_refuses_unapproved_cities(monkeypatch):
    air, wx = frames()
    monkeypatch.setattr(cal, "load_report", lambda: {"cities": {"delhi": {"approved": False}}})
    assert cal.apply("delhi", air, wx) is None
    assert cal.apply("kanpur", air, wx) is None
