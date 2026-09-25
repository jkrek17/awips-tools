"""track_cps.running_mean: a centered running mean over +/- width_h/2,
NaN-aware, with a window at the ends of the track that just holds
whatever frames exist (per its own docstring).
"""

from __future__ import annotations

import numpy as np
import pytest

import track_cps as tc


def test_running_mean_matches_manual_window_with_nan_gap():
    hours = np.arange(0.0, 36.1, 6.0)  # 0, 6, 12, 18, 24, 30, 36 (default width 24 h -> 5 frames)
    vals = np.array([10.0, 11.0, np.nan, 13.0, 14.0, 15.0, 16.0])

    out = tc.running_mean(hours, vals)
    assert out.shape == vals.shape

    half = tc.SMOOTH_H / 2.0
    for k, h in enumerate(hours):
        w = vals[np.abs(hours - h) <= half + 1e-6]
        w = w[np.isfinite(w)]
        expected = w.mean() if w.size else np.nan
        if np.isnan(expected):
            assert np.isnan(out[k])
        else:
            assert out[k] == pytest.approx(expected)

    # h=12's window is [0, 24] hours -> indices 0..4; index 2 (h=12) is NaN
    # and dropped, leaving 10, 11, 13, 14.
    assert out[2] == pytest.approx(np.mean([10.0, 11.0, 13.0, 14.0]))

    # At the left end (h=0) the window is [-12, 12] hours, i.e. only the
    # frames that exist there: h=0, 6, 12 -- and h=12 is the NaN gap.
    assert out[0] == pytest.approx(np.mean([10.0, 11.0]))


def test_running_mean_all_nan_window_stays_nan():
    hours = np.array([0.0, 6.0])
    vals = np.array([np.nan, np.nan])
    out = tc.running_mean(hours, vals)
    assert np.all(np.isnan(out))


def test_running_mean_custom_width():
    hours = np.array([0.0, 6.0, 12.0, 18.0, 24.0])
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = tc.running_mean(hours, vals, width_h=12.0)  # +/- 6 h -> 3 frames
    assert out[2] == pytest.approx(3.0)  # window [6, 18] -> 2, 3, 4
    assert out[0] == pytest.approx(1.5)  # window [-6, 6] -> 1, 2 (only frames that exist)
