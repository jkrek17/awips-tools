"""export_web's track-motion B: hart_class_point and track_motion_b (see
export_web.py, the LAYER_SCALE block and build_storms)."""

from __future__ import annotations

import math

import pytest

import export_web as ew


def test_class_rule_matches_the_d2d_table():
    f = ew.hart_class_point
    assert f(0.0, 50.0, 50.0) == 0 and f(30.0, 50.0, 50.0) == 2
    assert f(0.0, 50.0, -50.0) == 1 and f(30.0, 50.0, -50.0) == 3
    assert f(30.0, -50.0, -50.0) == 4 and f(0.0, -50.0, -50.0) == 5
    assert f(0.0, -50.0, 50.0) == 6 and f(30.0, -50.0, 50.0) == 6
    # ties: B exactly at the threshold is symmetric, a term at zero is warm
    assert f(10.0, 0.0, 0.0) == 0 and f(10.01, 0.0, 0.0) == 2
    assert f(None, 1.0, 1.0) is None and f(float("nan"), 1.0, 1.0) is None


def _pts(positions, bq):
    return [{"fhr": 6 * k, "lat": la, "lon": lo, "hvtl": 50.0, "hvtu": -50.0, "bq": list(bq)}
            for k, (la, lo) in enumerate(positions)]


def test_northward_motion_reads_east_minus_west():
    pts = _pts([(40.0, 0.0), (41.0, 0.0), (42.0, 0.0)], bq=(0.0, 0.0, 30.0, 10.0))  # N S E W
    ew.track_motion_b(pts)
    for p in pts:
        assert p["hbt"] == pytest.approx(20.0)
        assert p["hdg"] == pytest.approx(0.0) and p["spd"] > 0
        assert p["clst"] == 3  # asymmetric shallow warm core


def test_eastward_motion_reads_south_minus_north_and_flips_in_the_south():
    north = _pts([(40.0, 0.0), (40.0, 1.0), (40.0, 2.0)], bq=(5.0, 25.0, 0.0, 0.0))
    ew.track_motion_b(north)
    assert north[1]["hbt"] == pytest.approx(20.0) and north[1]["hdg"] == pytest.approx(90.0)
    south = _pts([(-40.0, 0.0), (-40.0, 1.0), (-40.0, 2.0)], bq=(5.0, 25.0, 0.0, 0.0))
    ew.track_motion_b(south)
    assert south[1]["hbt"] == pytest.approx(-20.0)


def test_single_point_or_missing_means_gives_none():
    one = _pts([(40.0, 0.0)], bq=(0.0, 0.0, 1.0, 0.0))
    ew.track_motion_b(one)
    assert one[0]["hbt"] is None and one[0]["clst"] is None
    two = _pts([(40.0, 0.0), (41.0, 0.0)], bq=(0.0, 0.0, 1.0, 0.0))
    two[1].pop("bq")
    ew.track_motion_b(two)
    assert two[0]["hbt"] is not None and two[1]["hbt"] is None and two[1]["spd"] is not None


def test_speed_matches_the_distance():
    pts = _pts([(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)], bq=(0.0, 0.0, 0.0, 0.0))
    ew.track_motion_b(pts)
    km = 111.195 * 2  # centered over two degrees of longitude at the equator in 12 h
    assert pts[1]["spd"] == pytest.approx(km / 12.0 / 1.852, abs=0.2)
