"""track_cps.Track.reach_rate and guess: the search reach follows a fast
storm's own speed (FAST_FACTOR times it) and stays at SPEED_KMH otherwise."""

from __future__ import annotations

import pytest

import track_cps as tc


def _track(*fixes):
    tr = tc.Track("X:30.0,-60.0:0")
    for fhr, lat, lon in fixes:
        tr.fixes.append({"fhr": fhr, "lat": lat, "lon": lon, "mslp_hpa": 980.0})
    return tr


def test_base_rate_with_fewer_than_two_fixes():
    assert _track().reach_rate() == tc.SPEED_KMH
    assert _track((0, 30.0, -60.0)).reach_rate() == tc.SPEED_KMH


def test_slow_mover_keeps_the_base_rate_and_cap():
    tr = _track((0, 30.0, -60.0), (6, 31.0, -60.0))  # about 111 km in 6 h
    assert tr.reach_rate() == tc.SPEED_KMH
    _, _, rad = tr.guess(12)
    assert rad == pytest.approx(min(tc.SPEED_KMH * 6, tc.CAP_KM))


def test_fast_mover_gets_a_wider_reach_and_cap():
    tr = _track((0, 40.0, 150.0), (6, 44.6, 156.0))  # about 700 km in 6 h
    speed = float(tc.gc_km(40.0, 150.0, 44.6, 156.0)) / 6.0
    assert speed > tc.SPEED_KMH
    assert tr.reach_rate() == pytest.approx(tc.FAST_FACTOR * speed)
    _, _, rad = tr.guess(12)
    assert rad > tc.CAP_KM
    assert rad == pytest.approx(min(tr.reach_rate() * 6, tc.CAP_KM * tr.reach_rate() / tc.SPEED_KMH))
    # the next 700 km step lies inside the reach now
    assert tr.reach_rate() * 6 > 700.0
