"""track_cps.max_rise: the pressure rise a track tolerates between fixes
grows with the depth of the last fix and with the hours elapsed."""

from __future__ import annotations

import pytest

import track_cps as tc


def test_shallow_low_keeps_the_flat_cap():
    assert tc.max_rise(1000.0, 6) == pytest.approx(tc.MAX_RISE_HPA)
    assert tc.max_rise(tc.DEEP_RISE_HPA, 6) == pytest.approx(tc.MAX_RISE_HPA)


def test_deep_low_may_fill_faster():
    # the 24 Sep 2026 cases: 931.4 to 945.7 hPa and 947.5 to 962.1 hPa in 6 h
    assert tc.max_rise(931.4, 6) > 945.7 - 931.4
    assert tc.max_rise(947.5, 6) > 962.1 - 947.5
    assert tc.max_rise(931.4, 6) == pytest.approx(tc.MAX_RISE_HPA + tc.DEEP_RISE_FRAC * (tc.DEEP_RISE_HPA - 931.4))


def test_a_bridged_frame_doubles_the_allowance():
    assert tc.max_rise(1000.0, 12) == pytest.approx(2 * tc.MAX_RISE_HPA)
    assert tc.max_rise(1000.0, 3) == pytest.approx(tc.MAX_RISE_HPA)
