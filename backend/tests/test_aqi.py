import pandas as pd
import pytest

from ml.aqi import BANDS, BREAKPOINTS, aqi_series, category, overall, sub_index


@pytest.mark.parametrize("pollutant", list(BREAKPOINTS))
def test_every_band_boundary(pollutant):
    for (lo, hi), (i_lo, i_hi) in zip(BREAKPOINTS[pollutant], BANDS):
        assert sub_index(pollutant, lo) == i_lo
        assert sub_index(pollutant, hi) == i_hi


@pytest.mark.parametrize("value,expected", [(31, 51), (45, 75), (60, 100)])
def test_cpcb_published_pm25_examples(value, expected):
    assert sub_index("pm2_5", value) == expected


@pytest.mark.parametrize("pollutant,value,expected", [
    ("pm2_5", 30.9, 50), ("pm2_5", 60.9, 100), ("pm2_5", 250.9, 400), ("pm10", 100.9, 100),
    ("pm10", 430.5, 400), ("co", 1.09, 50), ("co", 2.05, 100),
])
def test_values_between_bands_truncate_down(pollutant, value, expected):
    assert sub_index(pollutant, value) == expected


def test_official_table_values():
    assert BREAKPOINTS["pm2_5"][:5] == [(0, 30), (31, 60), (61, 90), (91, 120), (121, 250)]
    assert BREAKPOINTS["pm10"][:5] == [(0, 50), (51, 100), (101, 250), (251, 350), (351, 430)]


def test_capped_at_500_and_bad_input():
    assert sub_index("pm2_5", 9999) == 500
    assert sub_index("pm2_5", None) is None
    assert sub_index("pm2_5", float("nan")) is None
    assert sub_index("pm2_5", -1) is None


@pytest.mark.parametrize("aqi,name", [
    (0, "Good"), (50, "Good"), (51, "Satisfactory"), (100, "Satisfactory"),
    (101, "Moderately Polluted"), (200, "Moderately Polluted"), (201, "Poor"), (300, "Poor"),
    (301, "Very Poor"), (400, "Very Poor"), (401, "Severe"), (500, "Severe"),
])
def test_category_edges(aqi, name):
    assert category(aqi)[0] == name


def test_overall_takes_worst_and_needs_three_with_pm():
    res = overall({"pm2_5": 320, "pm10": 210, "no2": 40})
    assert (res.aqi, res.dominant) == (320, "pm2_5")
    assert overall({"pm2_5": 320, "no2": 40}).aqi is None
    assert overall({"no2": 40, "so2": 20, "o3": 30}).aqi is None


def _frame(hours, pm25=100.0):
    idx = pd.date_range("2026-11-01", periods=hours, freq="h")
    return pd.DataFrame({"pm2_5": pm25, "pm10": 150.0, "nitrogen_dioxide": 30.0, "sulphur_dioxide": 10.0,
                         "ozone": 40.0, "carbon_monoxide": 800.0}, index=idx)


def test_series_needs_16_hours_for_24h_pollutants():
    out = aqi_series(_frame(24))
    assert out.aqi.iloc[:15].isna().all()
    assert out.aqi.iloc[15] == sub_index("pm2_5", 100)


def test_series_converts_co_to_mg():
    df = _frame(24, pm25=5.0)
    df["pm10"], df["nitrogen_dioxide"], df["ozone"], df["sulphur_dioxide"] = 5.0, 5.0, 5.0, 5.0
    df["carbon_monoxide"] = 12000.0  # 12 mg/m3 falls in the Poor band
    out = aqi_series(df)
    assert out.dominant.iloc[-1] == "co"
    assert out.aqi.iloc[-1] == sub_index("co", 12.0)
