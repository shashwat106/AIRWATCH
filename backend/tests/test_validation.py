import numpy as np
import pandas as pd

from ml.validation import cleanest_window, compare, hour_range


def station_frame(hours=240, value=100.0, provider="CPCB"):
    idx = pd.date_range("2026-10-01", periods=hours, freq="h")
    wave = np.sin(np.arange(hours) / 24 * 2 * np.pi / 5) * 30
    return pd.DataFrame({"time": idx, "pm2_5": value + wave, "provider": provider, "station": "A"}), idx, wave


def test_compare_says_when_the_model_reads_high_and_tracks_well():
    stations, idx, wave = station_frame()
    res = compare(stations, pd.Series(120.0 + wave, index=idx), "Delhi")
    assert res["ratio"] == 1.2 and res["hours"] == 240
    assert res["summary"].startswith("The model read about 20% above nearby CPCB stations in Delhi")
    assert "closely" in res["tracking"]


def test_compare_says_when_the_model_reads_low_or_close():
    stations, idx, wave = station_frame()
    assert "% below" in compare(stations, pd.Series(70.0 + wave, index=idx), "Delhi")["summary"]
    assert "was close to" in compare(stations, pd.Series(102.0 + wave, index=idx), "Delhi")["summary"]


def test_compare_ignores_other_providers_and_needs_a_week():
    stations, idx, wave = station_frame(provider="AirNow")
    assert compare(stations, pd.Series(100.0, index=idx), "Delhi") is None
    short, idx, _ = station_frame(hours=100)
    assert compare(short, pd.Series(100.0, index=idx), "Delhi") is None


def test_hour_range_labels():
    assert hour_range(15) == "3 pm to 5 pm"
    assert hour_range(10) == "10 am to 12 pm"
    assert hour_range(12) == "12 pm to 2 pm"


def test_cleanest_window_finds_waking_hours_only():
    idx = pd.date_range("2026-10-01", periods=240, freq="h")
    value = np.where((idx.hour == 15) | (idx.hour == 16), 40.0, 100.0)
    value = np.where(idx.hour == 3, 5.0, value)  # cleaner, but nobody is out at 3 am
    stations = pd.DataFrame({"time": idx, "pm2_5": value, "provider": "CPCB", "station": "A"})
    res = cleanest_window(stations)
    assert res["start_hour"] == 15 and res["pm"] == 40
    assert res["summary"] == "At CPCB stations this season, the cleanest hours have averaged 3 pm to 5 pm."


def test_compare_flags_a_model_that_misses_the_worst_hours():
    idx = pd.date_range("2026-10-01", periods=200, freq="h")
    real = pd.Series(50.0, index=idx)
    real.iloc[:20] = 300.0  # the worst 10% of hours
    stations = pd.DataFrame({"time": idx, "pm2_5": real.values, "provider": "CPCB", "station": "A"})
    res = compare(stations, pd.Series(70.0, index=idx), "Delhi")
    assert (res["worst_real"], res["worst_model"]) == (300, 70) and res["understates_peaks"]
    assert res["peaks"].startswith("It understates the worst air")
    held = compare(stations, real * 0.95, "Delhi")
    assert not held["understates_peaks"] and held["peaks"].startswith("In the worst 10% of hours it held up")
