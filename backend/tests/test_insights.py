from datetime import date

import numpy as np
import pandas as pd

from ml.insights import days_over_limit, relief_ahead, short_date, timing_saving, weather_levers, winter_outlook


def closing(start, end, value=100.0):
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(value, index=idx)


def test_short_date():
    assert short_date(date(2026, 11, 3)) == "3 Nov"


def test_outlook_splits_at_the_same_date_and_skips_the_current_winter():
    s = closing("2024-08-01", "2026-11-03")
    s.loc["2024-10-20":"2024-10-21"] = 350  # before the cut
    s.loc["2024-12-01":"2024-12-08"] = 350  # after the cut
    s.loc["2026-10-05"] = 400  # this winter must not count
    res = winter_outlook(s, date(2026, 11, 3), "Delhi")
    first = res["winters"][0]
    assert (first["winter"], first["before"], first["after"]) == ("2024-25", 2, 8)
    assert res["total"] == 10 and res["later"] == 8 and res["ahead"]
    assert res["summary"] == "In the last 2 winters, 8 of 10 days above AQI 300 came after 3 Nov."


def test_outlook_does_not_claim_much_for_a_clean_city():
    res = winter_outlook(closing("2024-08-01", "2026-11-03"), date(2026, 11, 3), "Chandigarh")
    assert not res["ahead"] and res["summary"].startswith("Chandigarh rarely goes above AQI 300")


def test_outlook_is_silent_outside_winter_and_without_full_winters():
    s = closing("2024-08-01", "2026-11-03")
    assert winter_outlook(s, date(2026, 7, 1), "Delhi") is None
    assert winter_outlook(closing("2026-08-01", "2026-11-03"), date(2026, 11, 3), "Delhi") is None


def test_outlook_late_in_winter_is_not_called_ahead():
    s = closing("2024-08-01", "2026-02-10")
    s.loc["2024-12-01":"2024-12-10"] = 350
    res = winter_outlook(s, date(2026, 2, 10), "Delhi")
    assert res["later"] == 0 and not res["ahead"]


def weather_frames(rain_days=12):
    hours = pd.date_range("2025-10-01", "2025-12-31 23:00", freq="h")
    days = hours.normalize().unique()
    wind = pd.Series(np.where(np.arange(len(days)) % 2 == 0, 4.0, 12.0), index=days)
    pm = pd.Series(np.where(np.arange(len(days)) % 2 == 0, 120.0, 60.0), index=days)
    air = pd.DataFrame({"pm2_5": pm.reindex(hours.normalize()).values}, index=hours)
    rain = pd.Series(0.0, index=hours)
    for day in days[:rain_days * 2:2]:
        rain[day] = 3.0
    wx = pd.DataFrame({"wind_speed_10m": wind.reindex(hours.normalize()).values, "precipitation": rain.values}, index=hours)
    return air, wx


def test_levers_compare_still_and_windy_days_and_the_day_after_rain():
    air, wx = weather_frames()
    res = weather_levers(air, wx)
    assert (res["still_pm"], res["windy_pm"]) == (120, 60)
    assert res["rain"]["next_day_ratio"] == 0.5 and "50% lower" in res["rain"]["summary"]


def test_levers_need_enough_days():
    air, wx = weather_frames()
    assert weather_levers(air.iloc[:24 * 10], wx.iloc[:24 * 10]) is None
    air, wx = weather_frames(rain_days=3)
    assert weather_levers(air, wx)["rain"] is None


def forecast_wx(wind, rain=0.0, hours=48):
    idx = pd.date_range("2026-11-04 12:00", periods=hours, freq="h")
    return pd.DataFrame({"wind_speed_10m": wind, "precipitation": rain, "boundary_layer_height": 300.0}, index=idx)


def test_relief_names_the_first_helpful_day():
    wx = forecast_wx(4.0)
    wx.loc["2026-11-05", "precipitation"] = 0.5
    res = relief_ahead(wx, pd.Timestamp("2026-11-04 11:00"))
    assert res["days"][1]["verdict"] == "Rain could help" and res["summary"] == "Rain could help on 5 Nov."


def test_relief_says_so_when_nothing_is_coming():
    res = relief_ahead(forecast_wx(4.0), pd.Timestamp("2026-11-04 11:00"))
    assert "No strong wind or rain" in res["summary"] and not any(d["relief"] for d in res["days"])
    assert relief_ahead(forecast_wx(4.0), pd.Timestamp("2027-01-01")) is None


def test_relief_skips_days_with_only_a_few_hours_left():
    res = relief_ahead(forecast_wx(12.0, hours=15), pd.Timestamp("2026-11-04 11:00"))
    assert [d["date"] for d in res["days"]] == ["2026-11-04"]


def limit_table():
    idx = pd.date_range("2024-10-01", "2026-11-03", freq="D")
    table = pd.DataFrame({"pm2_5": 10.0}, index=idx)
    table.loc["2024-10-01":"2024-10-03", "pm2_5"] = 70.0
    table.loc["2024-11-10":"2024-11-20", "pm2_5"] = 70.0  # outside the matching window
    table.loc["2026-10-01":"2026-10-05", "pm2_5"] = 70.0
    return table


def test_days_over_limit_uses_the_same_dates_each_year():
    res = days_over_limit(limit_table(), date(2026, 11, 3), "Delhi")
    assert [r["over_india"] for r in res["seasons"]] == [3, 0, 5]
    assert res["india_summary"] == "Delhi was over it on 5 of 34 days this season, the most for these dates in our record, which starts in 2024."


def test_days_over_limit_claims_no_record_when_it_is_not_one():
    table = limit_table()
    table.loc["2024-10-01":"2024-10-10", "pm2_5"] = 70.0
    assert "most" not in days_over_limit(table, date(2026, 11, 3), "Delhi")["india_summary"]


def test_days_over_limit_counts_who_and_skips_gaps():
    table = limit_table()
    table.loc["2026-10-20", "pm2_5"] = np.nan
    table.loc["2026-10-21", "pm2_5"] = 20.0
    res = days_over_limit(table, date(2026, 11, 3), "Delhi")
    assert res["seasons"][-1]["days"] == 33 and res["seasons"][-1]["over_who"] == 6


def hourly(values, start="2026-11-04 06:00"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="h"), dtype=float)


def test_timing_saving_compares_the_window_with_that_days_worst_two_hours():
    pm = hourly([200, 180, 100, 80, 60, 60, 90])
    res = timing_saving(pm, "2026-11-04T10:00:00", "2026-11-04T12:00:00")
    assert (res["best_pm"], res["worst_pm"], res["ratio"]) == (60, 190, 3.2)
    assert res["summary"] == "The day's worst 2 hours have about 3.2× the PM2.5 of this window (190 vs 60 µg/m³)."


def test_timing_says_when_it_barely_matters():
    pm = hourly([100, 102, 100, 101, 100, 100])
    res = timing_saving(pm, "2026-11-04T07:00:00", "2026-11-04T09:00:00")
    assert res["summary"].startswith("Timing makes little difference")


def test_timing_ignores_night_hours_and_handles_no_data():
    pm = hourly([900, 900, 100, 100, 50, 50], start="2026-11-04 04:00")
    assert timing_saving(pm, "2026-11-04T08:00:00", "2026-11-04T10:00:00")["worst_pm"] == 100
    assert timing_saving(pm, "2027-01-01T08:00:00", "2027-01-01T10:00:00") is None
