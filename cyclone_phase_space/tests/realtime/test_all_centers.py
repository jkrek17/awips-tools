"""track_cps.all_centers: per its own docstring, "every point of the whole
grid that find_center would accept as a center" -- terrain masked before
the box-minimum test, MSLP below MAX_MSLP_HPA, latitude within POLE_LAT.

It has no notion of one low's own tracked history (no previous fix, no
max_mslp cap, no reach), and -- unlike find_center used by a Track, or
merge_close used on two Tracks' current fixes -- its docstring names no
distance-based suppression between two candidates found on the same
frame: it simply lists every accepted point. On a real analysis this is
just the handful of genuine lows; on the perfectly flat synthetic
background used here (no other feature disturbs it) it is also, quite
correctly by that same rule, every point of the untouched flat plateau
-- each one trivially tied with its neighbors as "the minimum of its
own box". These tests therefore only look at the points meaningfully
below the flat background (SIGNIFICANT_HPA), which are the genuine
lows the field was built to have.
"""

from __future__ import annotations

import pytest

import track_cps as tc
from rt_synthetic import add_gaussian_low, make_frame

BASE_HPA = 1013.0
SIGNIFICANT_HPA = 1.0  # a center at least this far below the flat background is a real feature


def _nearest(f, lat, lon):
    return int(round((lat - f["lat"][0]) / tc.g.RES_DEG)), int(round((lon - f["lon"][0]) / tc.g.RES_DEG))


def _significant(centers):
    return [c for c in centers if c[2] < BASE_HPA - SIGNIFICANT_HPA]


def test_two_separated_lows_found_once_each():
    f = make_frame(25.0, 45.0, -100.0, 0.0, mslp_hpa=BASE_HPA)
    add_gaussian_low(f, 35.0, -70.0, depth_hpa=25.0, sigma_km=150.0)
    add_gaussian_low(f, 35.0, -20.0, depth_hpa=8.0, sigma_km=150.0)

    centers = _significant(tc.all_centers(f, wrap=False))
    assert len(centers) == 2

    i0, j0 = _nearest(f, 35.0, -70.0)
    i1, j1 = _nearest(f, 35.0, -20.0)
    found = {(i, j): mslp for i, j, mslp in centers}
    assert (i0, j0) in found and (i1, j1) in found
    assert found[(i0, j0)] == pytest.approx(BASE_HPA - 25.0, abs=1e-6)
    assert found[(i1, j1)] == pytest.approx(BASE_HPA - 8.0, abs=1e-6)


def test_a_shallower_minimum_within_500_km_is_not_suppressed():
    """Two distinct local minima about 270 km apart (well under the 500 km
    figure sometimes used elsewhere in this module as a "close" distance;
    merge_close's own default MERGE_TRACK_KM, by contrast, is far smaller
    at 150 km): since all_centers's docstring lists no such suppression,
    both are returned, not just the deeper one."""
    f = make_frame(25.0, 45.0, -85.0, -55.0, mslp_hpa=BASE_HPA)
    deep_lat, deep_lon = 35.0, -71.0
    shallow_lat, shallow_lon = 35.0, -68.0  # ~3 deg east: about 270 km at this latitude
    km_apart = float(tc.gc_km(deep_lat, deep_lon, shallow_lat, shallow_lon))
    assert km_apart < 500.0

    add_gaussian_low(f, deep_lat, deep_lon, depth_hpa=25.0, sigma_km=60.0)
    add_gaussian_low(f, shallow_lat, shallow_lon, depth_hpa=5.0, sigma_km=60.0)

    centers = _significant(tc.all_centers(f, wrap=False))
    assert len(centers) == 2
    found = {(i, j): mslp for i, j, mslp in centers}
    id_, jd = _nearest(f, deep_lat, deep_lon)
    is_, js = _nearest(f, shallow_lat, shallow_lon)
    assert (id_, jd) in found  # the deeper low
    assert (is_, js) in found  # the shallower one, kept despite being close
    assert found[(id_, jd)] == pytest.approx(BASE_HPA - 25.0, abs=1e-4)
    assert found[(is_, js)] == pytest.approx(BASE_HPA - 5.0, abs=1e-4)
