import numpy as np
import pandas as pd

from ml.warning import backtest, check, latest_mean, rank

NOW = pd.Timestamp("2026-11-04 04:00")


def hourly(value, end=NOW, hours=24):
    return pd.Series(float(value), index=pd.date_range(end=end, periods=hours, freq="h"))


def test_rank_follows_cpcb_categories():
    assert [rank(v) for v in (40, 90, 150, 250, 350, 450)] == [0, 1, 2, 3, 4, 5]
    assert rank(None) == -1


def test_latest_mean_needs_16_hours_and_a_recent_reading():
    assert latest_mean(hourly(100), NOW)[0] == 100
    assert latest_mean(hourly(100, hours=15), NOW) is None
    assert latest_mean(hourly(100, end=NOW - pd.Timedelta(hours=37)), NOW) is None
    assert latest_mean(hourly(100, end=NOW - pd.Timedelta(hours=30)), NOW) is not None
    assert latest_mean(pd.Series(dtype=float), NOW) is None


def test_warns_when_measured_category_is_worse():
    res = check({"CPCB": hourly(300)}, 276, NOW)  # 300 ug/m3 is Severe, the model says Poor
    assert res["warn"] and res["category"]["name"] == "Severe"
    assert res["message"].endswith("which is Severe. Treat today as Severe.")


def test_no_warning_in_the_same_or_better_category():
    assert not check({"CPCB": hourly(100)}, 276, NOW)["warn"]  # 100 is Poor, the same as the model
    res = check({"CPCB": hourly(40)}, 276, NOW)
    assert not res["warn"] and res["message"] is None


def test_uses_the_worst_source_and_skips_stale_ones():
    res = check({"CPCB": hourly(100), "AirNow": hourly(280)}, 276, NOW)
    assert res["source"] == "AirNow" and res["warn"]
    stale = check({"CPCB": hourly(100), "AirNow": hourly(280, end=NOW - pd.Timedelta(hours=40))}, 276, NOW)
    assert stale["source"] == "CPCB" and not stale["warn"]


def test_silent_without_usable_data():
    assert check({"CPCB": hourly(300, hours=5)}, 276, NOW) is None
    assert check({}, 276, NOW) is None
    assert check({"CPCB": hourly(300)}, None, NOW) is None


def test_backtest_only_uses_readings_known_at_the_time():
    idx = pd.date_range("2026-01-01", periods=24 * 30, freq="h")
    real = pd.Series(20.0, index=idx)
    real.loc["2026-01-15":"2026-01-20"] = 300.0  # a Severe spell
    model = pd.Series(40.0, index=idx)  # the model stays Good throughout
    res = backtest(model, real)
    assert res["under_after"] < res["under_before"]
    assert res["fired"] > 0 and res["fired_right"] > 0
    # The first Severe day is missed: a day-old reading can't see it coming.
    assert res["under_after"] >= 1
    assert res["over_after"] >= res["over_before"]


def test_backtest_needs_enough_days():
    idx = pd.date_range("2026-01-01", periods=24 * 5, freq="h")
    assert backtest(pd.Series(40.0, index=idx), pd.Series(np.full(len(idx), 20.0), index=idx)) is None


def test_latest_mean_steps_back_over_a_gap_in_the_feed():
    full = hourly(100, end=NOW - pd.Timedelta(hours=20), hours=24)
    newest = hourly(300, end=NOW, hours=2)  # a fresh batch after a gap, too short to average
    mean, end = latest_mean(pd.concat([full, newest]), NOW)
    assert mean == 100 and end == NOW - pd.Timedelta(hours=20)
