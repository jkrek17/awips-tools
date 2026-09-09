"""Analytic tests for D2D/derivedParameters/functions/CycloneCore.py.

Expectations here are derived independently from the physics/math (solid-
body rotation has constant vorticity 2*Omega everywhere; pure shear has a
known, sign-dependent vorticity; a box mean of an isolated spike has a
closed-form result), not copied from the implementation, per the task
instructions.
"""

from __future__ import annotations

import numpy as np
import pytest

import CycloneCore as cc


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------

_N = 41
_SPACING_M = 1000.0


def _grid():
    """A uniform (_N, _N) grid, spacing 1 km, centered at (0, 0)."""
    coords = (np.arange(_N) - _N // 2) * _SPACING_M
    x, y = np.meshgrid(coords, coords)
    return x, y


def _interior(arr, margin=3):
    return arr[margin:-margin, margin:-margin]


# ---------------------------------------------------------------------------
# (a), (b): solid-body rotation
# ---------------------------------------------------------------------------


def test_relative_vorticity_solid_body_rotation_scalar_spacing():
    x, y = _grid()
    W = 1.0e-4
    u, v = -W * y, W * x

    zeta = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M)

    expected = 2.0 * W
    np.testing.assert_allclose(_interior(zeta), expected, rtol=1e-9)


def test_relative_vorticity_solid_body_rotation_array_spacing():
    x, y = _grid()
    W = 1.0e-4
    u, v = -W * y, W * x

    dx = np.full_like(x, _SPACING_M)
    dy = np.full_like(x, _SPACING_M)

    zeta_scalar = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M)
    zeta_array = cc.relative_vorticity(u, v, dx, dy)

    np.testing.assert_allclose(_interior(zeta_array), _interior(zeta_scalar), rtol=1e-12)
    np.testing.assert_allclose(_interior(zeta_array), 2.0 * W, rtol=1e-9)


# ---------------------------------------------------------------------------
# (c): Y_INCREASES_NORTHWARD flips the du/dy term
# ---------------------------------------------------------------------------


def test_y_orientation_flips_shear_sign(monkeypatch):
    x, y = _grid()
    a = 3.0e-5
    u = a * y
    v = np.zeros_like(x)

    monkeypatch.setattr(cc, "Y_INCREASES_NORTHWARD", True)
    zeta_north_up = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M)
    np.testing.assert_allclose(_interior(zeta_north_up), -a, rtol=1e-9)

    monkeypatch.setattr(cc, "Y_INCREASES_NORTHWARD", False)
    zeta_north_down = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M)
    np.testing.assert_allclose(_interior(zeta_north_down), a, rtol=1e-9)


# ---------------------------------------------------------------------------
# (d): execute() combines two levels; swapping levels negates the result
# ---------------------------------------------------------------------------


def test_execute_vertical_difference_and_level_swap():
    x, y = _grid()
    w_lo = 1.0e-4
    w_hi = 0.4e-4
    u_lo, v_lo = -w_lo * y, w_lo * x
    u_hi, v_hi = -w_hi * y, w_hi * x

    result = cc.execute(u_lo, v_lo, u_hi, v_hi, _SPACING_M, _SPACING_M, smoothKm=0.0)

    assert result.dtype == np.float32
    expected = 2.0 * (w_lo - w_hi)
    # float32 output, so tolerance is float32 precision (~1e-7 relative),
    # not the float64 1e-9 used for the pure-numpy relative_vorticity checks.
    np.testing.assert_allclose(_interior(result).astype(np.float64), expected, rtol=1e-6)

    swapped = cc.execute(u_hi, v_hi, u_lo, v_lo, _SPACING_M, _SPACING_M, smoothKm=0.0)
    np.testing.assert_allclose(_interior(swapped).astype(np.float64), -expected, rtol=1e-6)


# ---------------------------------------------------------------------------
# (e): box_smooth
# ---------------------------------------------------------------------------


def test_box_smooth_zero_cells_is_identity():
    field = np.arange(25.0).reshape(5, 5)
    field[2, 2] = np.nan
    smoothed = cc.box_smooth(field, 0)
    assert smoothed is not field
    np.testing.assert_array_equal(smoothed[~np.isnan(field)], field[~np.isnan(field)])
    assert np.isnan(smoothed[2, 2])


def test_box_smooth_single_spike():
    n = 15
    field = np.zeros((n, n))
    r, c = 7, 7
    field[r, c] = 9.0

    smoothed = cc.box_smooth(field, 1)

    # The spike and its 8 neighbors each average a full 3x3 window
    # containing the spike (sum 9) plus 8 zeros -> mean 1.0.
    window = smoothed[r - 1 : r + 2, c - 1 : c + 2]
    np.testing.assert_allclose(window, 1.0)

    # Total sum is preserved: the spike's value is spread over exactly the
    # 9 points that see it and nowhere else, since every other point of the
    # domain is either unaffected (window has no spike) or, near the
    # domain edges, only sees zeros anyway.
    np.testing.assert_allclose(np.nansum(smoothed), np.nansum(field))
    assert np.count_nonzero(smoothed) == 9


def test_box_smooth_nan_handling():
    # A single interior NaN is excluded from neighboring means (they
    # average over the remaining valid points), not propagated.
    field = np.ones((7, 7))
    field[3, 3] = np.nan
    smoothed = cc.box_smooth(field, 1)
    np.testing.assert_allclose(smoothed[2, 2], 1.0)  # window has 8 ones + 1 NaN
    np.testing.assert_allclose(smoothed[3, 2], 1.0)

    # A window that is ENTIRELY NaN comes back NaN.
    all_nan = np.full((2, 2), np.nan)
    smoothed_all_nan = cc.box_smooth(all_nan, 1)
    assert np.all(np.isnan(smoothed_all_nan))


# ---------------------------------------------------------------------------
# (f): cells_for_km
# ---------------------------------------------------------------------------


def test_cells_for_km():
    assert cc.cells_for_km(100.0, 25000.0, 25000.0) == 4
    assert cc.cells_for_km(100.0, 27800.0, 27800.0) == 4
    assert cc.cells_for_km(0.0, 25000.0, 25000.0) == 0


# ---------------------------------------------------------------------------
# (g): missing values
# ---------------------------------------------------------------------------


def test_execute_missing_value_localized():
    x, y = _grid()
    w_lo, w_hi = 1.0e-4, 0.4e-4
    u_lo, v_lo = -w_lo * y, w_lo * x
    u_hi, v_hi = -w_hi * y, w_hi * x

    r, c = _N // 2, _N // 2
    u_lo = u_lo.copy()
    u_lo[r, c] = -999999.0

    result = cc.execute(u_lo, v_lo, u_hi, v_hi, _SPACING_M, _SPACING_M, smoothKm=0.0)

    assert not np.isfinite(result[r, c])
    # Contamination is confined to the immediate neighborhood of the
    # missing point (the centered-difference stencil plus the explicit
    # missing mask) -- a handful of points at most, not the whole field.
    n_bad = int(np.count_nonzero(~np.isfinite(result)))
    assert 1 <= n_bad <= 6

    corner_finite = np.isfinite(result[2, 2]) and np.isfinite(result[-3, -3])
    assert corner_finite


# ---------------------------------------------------------------------------
# (h): smoothKm coercion
# ---------------------------------------------------------------------------


def test_execute_smoothkm_coercion():
    x, y = _grid()
    w_lo, w_hi = 1.0e-4, 0.4e-4
    u_lo, v_lo = -w_lo * y, w_lo * x
    u_hi, v_hi = -w_hi * y, w_hi * x

    baseline = cc.execute(u_lo, v_lo, u_hi, v_hi, _SPACING_M, _SPACING_M, smoothKm=100.0)
    from_array = cc.execute(u_lo, v_lo, u_hi, v_hi, _SPACING_M, _SPACING_M, smoothKm=np.array([100.0]))
    from_f32 = cc.execute(u_lo, v_lo, u_hi, v_hi, _SPACING_M, _SPACING_M, smoothKm=np.float32(100.0))

    np.testing.assert_allclose(from_array, baseline)
    np.testing.assert_allclose(from_f32, baseline)


# ---------------------------------------------------------------------------
# (i): Southern Hemisphere sign
# ---------------------------------------------------------------------------


def test_southern_hemisphere_warm_core_reads_negative():
    x, y = _grid()
    # Clockwise (Southern Hemisphere cyclonic) rotation, weakening with
    # height -- physically a warm core, but relative vorticity itself is
    # negative for a SH cyclone, so the vertical difference comes out
    # negative too (see D2D/README.md "Known limitation").
    w_lo, w_hi = -1.0e-4, -0.4e-4
    u_lo, v_lo = -w_lo * y, w_lo * x
    u_hi, v_hi = -w_hi * y, w_hi * x

    result = cc.execute(u_lo, v_lo, u_hi, v_hi, _SPACING_M, _SPACING_M, smoothKm=0.0)

    assert np.all(_interior(result) < 0)
    expected = 2.0 * (w_lo - w_hi)
    assert expected < 0
    np.testing.assert_allclose(_interior(result).astype(np.float64), expected, rtol=1e-6)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
