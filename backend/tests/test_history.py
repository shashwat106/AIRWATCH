from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.history import (compare_years, correlation_strength, daily_table, fire_link, ratio_words,
                        recent_averages, same_date_in_year, season_comparison, season_lines,
                        season_start, season_stats, season_windows, worst_days)


def hourly(start, days, pm25=100.0):
    idx = pd.date_range(start, periods=days * 24, freq="h")
    return pd.DataFrame({"pm2_5": pm25, "pm10": 150.0, "nitrogen_dioxide": 30.0, "sulphur_dioxide": 10.0,
                         "ozone": 40.0, "carbon_monoxide": 800.0}, index=idx)


def table(rows):
    index = pd.to_datetime(list(rows))
    return pd.DataFrame({"aqi": [float(v) if v is not None else np.nan for v in rows.values()],
                         "pm2_5": [float(v) / 2 if v is not None else np.nan for v in rows.values()],
                         "pm10": 100.0, "hours": 24}, index=index)


def test_leap_day_maps_to_28_feb():
    assert same_date_in_year(date(2024, 2, 29), 2023) == date(2023, 2, 28)
    assert same_date_in_year(date(2023, 2, 28), 2024) == date(2024, 2, 28)
    assert same_date_in_year(date(2026, 11, 4), 2025) == date(2025, 11, 4)


@pytest.mark.parametrize("day,start", [(date(2026, 10, 1), date(2026, 10, 1)), (date(2026, 11, 4), date(2026, 10, 1)),
                                       (date(2026, 12, 31), date(2026, 10, 1)), (date(2027, 1, 1), date(2026, 10, 1)),
                                       (date(2026, 9, 30), date(2025, 10, 1))])
def test_season_start(day, start):
    assert season_start(day) == start


def test_season_windows_line_up_across_new_year_and_leap_day():
    assert season_windows(date(2026, 11, 3)) == ((date(2026, 10, 1), date(2026, 11, 3)),
                                                 (date(2025, 10, 1), date(2025, 11, 3)))
    assert season_windows(date(2024, 2, 29)) == ((date(2023, 10, 1), date(2024, 2, 29)),
                                                 (date(2022, 10, 1), date(2023, 2, 28)))


def test_daily_table_blanks_days_with_too_few_hours():
    air = hourly("2026-11-01", 3)
    air.loc["2026-11-02 08:00":"2026-11-02 23:00", "pm2_5"] = np.nan  # 8 hours remain that day
    out = daily_table(air)
    assert out.hours.tolist() == [24, 8, 24]
    assert np.isnan(out.loc["2026-11-02", "aqi"]) and np.isnan(out.loc["2026-11-02", "pm2_5"])
    assert out.loc["2026-11-01", "pm2_5"] == 100


def test_daily_table_survives_missing_hours_above_the_minimum():
    air = hourly("2026-11-01", 2).drop(pd.date_range("2026-11-02 03:00", periods=6, freq="h"))
    out = daily_table(air)
    assert out.hours.tolist() == [24, 18] and not np.isnan(out.loc["2026-11-02", "pm2_5"])


def test_compare_years_reports_gaps_rather_than_inventing():
    t = table({"2026-11-03": 300, "2025-11-03": 150})
    res = compare_years(t, date(2026, 11, 3))
    assert res["earlier"][0]["summary"] == "PM2.5 is 2.0× the earlier value."
    assert res["earlier"][1] == {"date": "2024-11-03", "available": False}


def test_compare_years_adds_fires_only_when_given():
    t = table({"2026-11-03": 300, "2025-11-03": 150})
    fires = pd.Series([10, 40], index=pd.to_datetime(["2026-11-03", "2025-11-03"]))
    res = compare_years(t, date(2026, 11, 3), fires)
    assert res["day"]["upwind_fires"] == 10 and res["earlier"][0]["upwind_fires"] == 40
    assert "upwind_fires" not in compare_years(t, date(2026, 11, 3))["day"]


def test_recent_averages_exclude_the_day_itself_and_count_gaps():
    days = pd.date_range("2026-10-27", "2026-11-03").strftime("%Y-%m-%d")
    t = table({d: 100 for d in days[:-1]} | {days[-1]: 400})
    t.loc["2026-10-30", ["aqi", "pm2_5"]] = np.nan
    res = recent_averages(t, date(2026, 11, 3))
    assert res["last_7_days"]["aqi"] == 100 and res["last_7_days"]["days_with_data"] == 6
    assert res["last_30_days"]["days_with_data"] == 6


def test_season_stats_counts_each_band_at_its_edges():
    t = table({"2026-10-01": 200, "2026-10-02": 201, "2026-10-03": 300, "2026-10-04": 301,
               "2026-10-05": 400, "2026-10-06": 401, "2026-10-07": None})
    s = season_stats(t, date(2026, 10, 1), date(2026, 10, 7))
    assert (s["poor_days"], s["very_poor_days"], s["severe_days"]) == (2, 2, 1)
    assert s["days_with_data"] == 6 and s["days_expected"] == 7 and s["upwind_fires"] is None


def test_season_comparison_uses_same_dates_and_says_so():
    t = table({"2026-10-01": 300, "2026-10-02": 300, "2025-10-01": 200, "2025-10-02": 200, "2025-10-03": 500})
    res = season_comparison(t, date(2026, 10, 2))
    assert res["last_season"]["mean_aqi"] == 200  # 3 Oct last year is outside the window
    assert res["summary"].startswith("Average AQI this season is 100 points higher")


def test_season_lines_pair_same_dates_and_keep_gaps():
    t = table({"2026-10-01": 300, "2026-10-02": None, "2025-10-01": 200, "2025-10-02": 210})
    rows = season_lines(t, date(2026, 10, 2))
    assert rows[0] == {"label": "01 Oct", "this_season": 300, "last_season": 200}
    assert rows[1] == {"label": "02 Oct", "this_season": None, "last_season": 210}


def test_fire_link_is_honest_without_data():
    t = table({"2026-10-01": 300})
    assert fire_link(t, None, date(2026, 10, 1), date(2026, 10, 1))["available"] is False
    few = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-09-30", "2026-10-01"]))
    assert fire_link(t, few, date(2026, 10, 1), date(2026, 10, 1))["available"] is False


def test_fire_link_finds_a_planted_next_day_relationship():
    days = pd.date_range("2026-10-01", periods=30)
    rng = np.random.default_rng(1)
    fires = pd.Series(rng.integers(0, 500, 30).astype(float), index=days)
    pm = fires.shift(1) * 0.5 + 20  # PM2.5 follows yesterday's fires
    t = pd.DataFrame({"pm2_5": pm, "aqi": 200.0, "pm10": 100.0, "hours": 24}, index=days).dropna()
    res = fire_link(t, fires, date(2026, 10, 2), date(2026, 10, 30))
    assert res["available"] and res["best"]["lag_days"] == 0 and res["best"]["r"] == 1.0
    assert "strong" in res["summary"] and "does not prove cause" in res["summary"]


def test_correlation_words():
    assert [correlation_strength(r) for r in (0.1, -0.29, 0.3, -0.59, 0.6, -0.9)] == \
        ["weak", "weak", "moderate", "moderate", "strong", "strong"]


def test_ratio_words():
    assert ratio_words(180, 100, "PM2.5") == "PM2.5 is 1.8× the earlier value."
    assert ratio_words(50, 100, "PM2.5") == "PM2.5 is 50% lower."
    assert ratio_words(102, 100, "PM2.5") == "PM2.5 is about the same."
    assert "cannot be compared" in ratio_words(5, 0, "PM2.5")


def test_worst_days_order_and_category():
    t = table({"2026-10-01": 450, "2026-10-02": 250, "2026-10-03": 320, "2026-10-04": None})
    res = worst_days(t, date(2026, 10, 1), date(2026, 10, 4), n=2)
    assert [(x["date"], x["category"]) for x in res] == [("2026-10-01", "Severe"), ("2026-10-03", "Very Poor")]
