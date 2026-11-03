import math

import pandas as pd
import pytest

from ml.sources import (FireStats, angular_diff, bearing_deg, compass, crop_burning, distance_weight,
                        dust, haversine_km, level, mean_wind, top_cause, trapping, upwind_fires, vehicles)

DELHI = (28.61, 77.21)
AT = pd.Timestamp("2026-11-03 12:00")


def fires_at(points, conf="n", when=AT - pd.Timedelta(hours=6)):
    return pd.DataFrame({"latitude": [p[0] for p in points], "longitude": [p[1] for p in points],
                         "time": when, "confidence": conf})


@pytest.mark.parametrize("a,b,expected", [(350, 10, 20), (10, 350, 20), (0, 360, 0), (359, 1, 2),
                                          (0, 180, 180), (90, 270, 180), (45, 45, 0)])
def test_angular_diff_across_north(a, b, expected):
    assert float(angular_diff(a, b)) == pytest.approx(expected)


def test_bearings_on_the_compass():
    assert float(bearing_deg(28, 77, 29, 77)) == pytest.approx(0, abs=0.01)
    assert float(bearing_deg(29, 77, 28, 77)) == pytest.approx(180, abs=0.01)
    assert float(bearing_deg(28, 77, 28, 78)) == pytest.approx(90, abs=0.3)
    assert float(bearing_deg(28, 78, 28, 77)) == pytest.approx(270, abs=0.3)


def test_haversine_one_degree_latitude():
    assert float(haversine_km(28, 77, 29, 77)) == pytest.approx(111.2, abs=0.5)


def test_distance_weight_falls_to_zero():
    assert float(distance_weight(0)) == 1
    assert float(distance_weight(150)) == pytest.approx(0.5)
    assert float(distance_weight(300)) == 0
    assert float(distance_weight(450)) == 0


def test_fire_northwest_is_upwind_of_a_northwest_wind():
    nw_fire = fires_at([(29.8, 75.9)])  # roughly 180 km NW of Delhi
    stats = upwind_fires(nw_fire, *DELHI, wind_kmh=11, wind_from=315, at=AT)
    assert stats.upwind_count == 1 and stats.weighted > 0


def test_same_fire_is_not_upwind_when_wind_reverses():
    nw_fire = fires_at([(29.8, 75.9)])
    stats = upwind_fires(nw_fire, *DELHI, wind_kmh=11, wind_from=135, at=AT)
    assert stats.upwind_count == 0 and stats.nearby_count == 1


def test_upwind_across_the_north_line():
    # Fire due north-ish, slightly east: city-to-fire bearing about 10 deg, wind from 350 deg.
    fire = fires_at([(30.0, 77.46)])
    assert upwind_fires(fire, *DELHI, wind_kmh=10, wind_from=350, at=AT).upwind_count == 1
    # Fire slightly west of north with the wind from 10 deg.
    fire = fires_at([(30.0, 76.96)])
    assert upwind_fires(fire, *DELHI, wind_kmh=10, wind_from=10, at=AT).upwind_count == 1


def test_beyond_radius_and_outside_window_are_ignored():
    far = fires_at([(33.0, 73.0)])
    assert upwind_fires(far, *DELHI, wind_kmh=11, wind_from=315, at=AT).nearby_count == 0
    old = fires_at([(29.8, 75.9)], when=AT - pd.Timedelta(hours=49))
    assert upwind_fires(old, *DELHI, wind_kmh=11, wind_from=315, at=AT).nearby_count == 0
    future = fires_at([(29.8, 75.9)], when=AT + pd.Timedelta(hours=1))
    assert upwind_fires(future, *DELHI, wind_kmh=11, wind_from=315, at=AT).nearby_count == 0


def test_closer_and_more_confident_fires_weigh_more():
    near = upwind_fires(fires_at([(29.0, 76.8)]), *DELHI, wind_kmh=11, wind_from=315, at=AT)
    far = upwind_fires(fires_at([(30.2, 75.5)]), *DELHI, wind_kmh=11, wind_from=315, at=AT)
    assert near.weighted > far.weighted
    high = upwind_fires(fires_at([(29.0, 76.8)], "h"), *DELHI, wind_kmh=11, wind_from=315, at=AT)
    low = upwind_fires(fires_at([(29.0, 76.8)], "l"), *DELHI, wind_kmh=11, wind_from=315, at=AT)
    assert high.weighted > near.weighted > low.weighted


def test_calm_wind_has_no_upwind():
    stats = upwind_fires(fires_at([(29.8, 75.9)]), *DELHI, wind_kmh=1.5, wind_from=315, at=AT)
    assert stats.calm and stats.upwind_count == 0 and stats.nearby_count == 1


def test_mean_wind_across_north_is_north_not_south():
    speed, direction = mean_wind(pd.Series([10.0, 10.0]), pd.Series([350.0, 10.0]))
    assert angular_diff(direction, 0) < 0.01 and speed == pytest.approx(9.85, abs=0.01)


def test_compass_names():
    assert [compass(d) for d in (0, 44, 46, 180, 315, 359)] == ["N", "NE", "NE", "S", "NW", "N"]


def test_crop_score_zero_without_upwind_fires_and_grows_with_fires():
    none = crop_burning(FireStats(0, 0, 0, 11, 315), 0.7, 0.5)
    some = crop_burning(FireStats(100, 50, 100, 11, 315), 0.7, 0.5)
    many = crop_burning(FireStats(1200, 600, 1200, 11, 315), 0.7, 0.5)
    assert none.score == 0 and 0 < some.score < many.score <= 1
    assert "1,200 fire detections upwind" in many.reason and "from NW at 11 km/h" in many.reason


def test_crop_not_scored_without_fire_data_or_with_calm_wind():
    assert crop_burning(None, 0.7, 0.5).score is None
    assert crop_burning(None, 0.7, 0.5).level == "Unknown"
    calm = FireStats(0, 0, 40, 1.0, 315, calm=True)
    assert crop_burning(calm, 0.7, 0.5).score is None


def test_vehicles_higher_at_rush_hour_and_on_weekdays():
    rush = vehicles(60, 1500, 30, 800, hour=9, weekday=1)
    midday = vehicles(60, 1500, 30, 800, hour=14, weekday=1)
    weekend = vehicles(60, 1500, 30, 800, hour=9, weekday=6)
    assert rush.score > weekend.score > midday.score
    assert vehicles(20, 500, 30, 800, hour=9, weekday=1).score == 0
    assert vehicles(60, 1500, 30, 800, hour=11, weekday=1).score == midday.score


def test_dust_needs_coarse_particles():
    coarse = dust(300, 0.25, hour=13, wind_kmh=20, humidity=30, rain_6h=0)
    fine = dust(300, 0.8, hour=13, wind_kmh=20, humidity=30, rain_6h=0)
    assert coarse.score > 0.6 and fine.score == 0


def test_trapping_extremes():
    assert trapping(2, 200).score == 1
    assert trapping(15, 1500).score == 0
    assert trapping(2, 1500).score == 0.5


def test_levels_and_nan_safety():
    assert [level(s) for s in (0, 0.32, 0.33, 0.65, 0.66, 1)] == ["Low", "Low", "Medium", "Medium", "High", "High"]
    assert math.isnan(mean_wind(pd.Series([float("nan")]), pd.Series([float("nan")]))[0])


def test_top_cause_needs_medium_and_skips_unscored():
    scored = [{"id": "crop", "label": "Crop burning", "score": None},
              {"id": "dust", "label": "Dust", "score": 0.4},
              {"id": "weather", "label": "Weather", "score": 0.7}]
    assert top_cause(scored)["id"] == "weather"
    assert top_cause([{"id": "dust", "label": "Dust", "score": 0.32}]) is None
    assert top_cause([{"id": "crop", "label": "Crop burning", "score": None}]) is None
