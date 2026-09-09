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

    # mode=0: the standard numpy layout (axis 0 = y increasing northward).
    # The module's real default is ORIENTATION_MODE = 1, tuned for AWIPS
    # sites, not for describing this layout -- see the standard_orientation
    # fixture in conftest.py for tests that want the default itself.
    zeta = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M, mode=0)

    expected = 2.0 * W
    np.testing.assert_allclose(_interior(zeta), expected, rtol=1e-9)


def test_relative_vorticity_solid_body_rotation_array_spacing():
    x, y = _grid()
    W = 1.0e-4
    u, v = -W * y, W * x

    dx = np.full_like(x, _SPACING_M)
    dy = np.full_like(x, _SPACING_M)

    zeta_scalar = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M, mode=0)
    zeta_array = cc.relative_vorticity(u, v, dx, dy, mode=0)

    np.testing.assert_allclose(_interior(zeta_array), _interior(zeta_scalar), rtol=1e-12)
    np.testing.assert_allclose(_interior(zeta_array), 2.0 * W, rtol=1e-9)


# ---------------------------------------------------------------------------
# (c): ORIENTATION_MODE flips the du/dy term (modes 0 vs 1), and modes 2/3
# additionally correct for arrays that arrive transposed (x on axis 0, y on
# axis 1) -- the second AWIPS grid convention that can produce the same
# lobed, deformation-like cpsZ850 pattern a flipped y axis produces.
# ---------------------------------------------------------------------------


def test_orientation_mode_flips_shear_sign():
    # Pure shear: u = a*y, v = 0 on the standard layout (axis 0 = y
    # increasing northward). Analytically, zeta = dv/dx - du/dy = 0 - a = -a
    # under mode 0; mode 1 negates the du/dy term, flipping the sign to +a.
    x, y = _grid()
    a = 3.0e-5
    u = a * y
    v = np.zeros_like(x)

    zeta_mode0 = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M, mode=0)
    np.testing.assert_allclose(_interior(zeta_mode0), -a, rtol=1e-9)

    zeta_mode1 = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M, mode=1)
    np.testing.assert_allclose(_interior(zeta_mode1), a, rtol=1e-9)


def test_solid_body_rotation_mode0_explicit_and_via_default(standard_orientation):
    # Same solid-body vortex as above: mode=0 gives 2W explicitly, and
    # mode=None (the "use ORIENTATION_MODE" default) gives the same 2W
    # once ORIENTATION_MODE is monkeypatched to 0 by the fixture -- i.e.
    # mode=None and mode=0 really are the same computation when
    # ORIENTATION_MODE == 0.
    x, y = _grid()
    W = 1.0e-4
    u, v = -W * y, W * x
    expected = 2.0 * W

    zeta_explicit = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M, mode=0)
    np.testing.assert_allclose(_interior(zeta_explicit), expected, rtol=1e-9)

    zeta_default = cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M)
    np.testing.assert_allclose(_interior(zeta_default), expected, rtol=1e-9)


def _rect_grid(ny, nx, spacing=_SPACING_M):
    """A non-square (ny, nx) grid, axis 0 = y, axis 1 = x -- large enough,
    and non-square enough, that a transposition bug in relative_vorticity
    would either raise (shape mismatch) or be caught by the interior-value
    check rather than passing by accident on a square grid.
    """
    y_coords = (np.arange(ny) - ny // 2) * spacing
    x_coords = (np.arange(nx) - nx // 2) * spacing
    x, y = np.meshgrid(x_coords, y_coords)
    return x, y


def test_relative_vorticity_transposed_mode2():
    # A site whose arrays arrive transposed (axis 0 = x, axis 1 = y
    # increasing northward): hand relative_vorticity the SAME solid-body
    # vortex as above but transposed, as that site's AWIPS would, and mode
    # 2 must still recover 2W everywhere in the interior -- with the
    # output shaped like the (transposed) inputs given, not like the
    # untransposed vortex.
    ny, nx = 41, 61  # deliberately non-square: shape mistakes fail loudly
    x, y = _rect_grid(ny, nx)
    W = 1.0e-4
    u, v = -W * y, W * x  # shape (ny, nx)
    dx2d = np.full((ny, nx), _SPACING_M)
    dy2d = np.full((ny, nx), _SPACING_M)

    zeta = cc.relative_vorticity(u.T, v.T, dx2d.T, dy2d.T, mode=2)

    assert zeta.shape == (nx, ny)
    np.testing.assert_allclose(_interior(zeta), 2.0 * W, rtol=1e-9)


def test_relative_vorticity_transposed_and_flipped_mode3():
    # Same transposed convention as mode 2, but the site's y axis also
    # increases southward: build that by flipping the standard vortex's y
    # axis (axis 0) before transposing, exactly as such a site's raw
    # arrays would look. Mode 3 must still recover 2W, with the output
    # shaped like the given (transposed) inputs.
    ny, nx = 41, 61
    x, y = _rect_grid(ny, nx)
    W = 1.0e-4
    u, v = -W * y, W * x
    dx2d = np.full((ny, nx), _SPACING_M)
    dy2d = np.full((ny, nx), _SPACING_M)

    u_raw = u[::-1].T
    v_raw = v[::-1].T
    dx_raw = dx2d[::-1].T
    dy_raw = dy2d[::-1].T

    zeta = cc.relative_vorticity(u_raw, v_raw, dx_raw, dy_raw, mode=3)

    assert zeta.shape == (nx, ny)
    np.testing.assert_allclose(_interior(zeta), 2.0 * W, rtol=1e-9)


def test_relative_vorticity_transposed_input_with_mode0_is_not_2w():
    # This is what documents why the mode exists: feeding the SAME
    # transposed-convention arrays from the mode-2 test above into mode 0
    # (i.e. treating them as if axis 0 were already y) does NOT recover
    # 2W -- it comes out near zero, a deformation-like artifact of
    # differentiating along the wrong axes, not the true vorticity. This
    # is the pointwise analogue of the lobed cpsZ850 pattern the real
    # AWIPS site saw: a single positive blob (vorticity) misread as
    # something else (deformation) because of the axis mismatch.
    ny, nx = 41, 61
    x, y = _rect_grid(ny, nx)
    W = 1.0e-4
    u, v = -W * y, W * x

    zeta_wrong = cc.relative_vorticity(u.T, v.T, _SPACING_M, _SPACING_M, mode=0)

    assert zeta_wrong.shape == (nx, ny)
    assert not np.allclose(_interior(zeta_wrong), 2.0 * W, rtol=1e-3)
    np.testing.assert_allclose(_interior(zeta_wrong), 0.0, atol=1e-9)


def test_execute_vorticity_mode_as_array():
    x, y = _grid()
    W = 1.0e-4
    u, v = -W * y, W * x

    result = cc.executeVorticity(u.T, v.T, _SPACING_M, _SPACING_M, mode=np.array([2.0]))

    assert result.dtype == np.float32
    np.testing.assert_allclose(_interior(result).astype(np.float64), 2.0 * W, rtol=1e-5)


def test_relative_vorticity_invalid_mode_raises():
    x, y = _grid()
    u, v = np.zeros_like(x), np.zeros_like(x)
    with pytest.raises(ValueError):
        cc.relative_vorticity(u, v, _SPACING_M, _SPACING_M, mode=4)


# ---------------------------------------------------------------------------
# (d): execute() combines two levels; swapping levels negates the result
# ---------------------------------------------------------------------------


def test_execute_vertical_difference_and_level_swap(standard_orientation):
    # execute() has no mode parameter of its own (see CycloneCore.py) --
    # it always uses ORIENTATION_MODE via relative_vorticity's default, so
    # this test needs the standard_orientation fixture to describe the
    # standard layout instead of the module's real (AWIPS-tuned) default.
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


def test_southern_hemisphere_warm_core_reads_negative(standard_orientation):
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


# ---------------------------------------------------------------------------
# (j): classify() decision table
# ---------------------------------------------------------------------------


def test_classify_decision_table():
    band = 3.0e-5
    zeta_ok = 1.0e-4  # comfortably above the default vortex_min

    # (vtl, vtu, expected code), covering every row of the table, including
    # boundary values exactly at +band, -band, and 0.
    cases = [
        # deep warm core: vtl > band, vtu > band
        (5.0e-5, 5.0e-5, 4),
        (band + 1e-6, band + 1e-6, 4),
        # shallow warm core: vtl > band, vtu <= band
        (5.0e-5, 0.0, 3),
        (5.0e-5, band, 3),  # vtu exactly at +band -> "<=" side
        (5.0e-5, -5.0e-5, 3),
        # cold core: |vtl| <= band, vtu < -band
        (0.0, -5.0e-5, 1),
        (band, -5.0e-5, 1),  # vtl exactly at +band -> "|vtl| <= band" side
        (-band, -5.0e-5, 1),  # vtl exactly at -band -> "|vtl| <= band" side
        # neutral: |vtl| <= band, vtu >= -band
        (0.0, 0.0, 2),
        (0.0, -band, 2),  # vtu exactly at -band -> ">=" side
        (band, band, 2),
        (-band, 0.0, 2),
        # mid-level vortex: vtl < -band, vtu > band
        (-5.0e-5, 5.0e-5, 0),
        # cold core: vtl < -band, vtu <= band
        (-5.0e-5, 0.0, 1),
        (-5.0e-5, band, 1),  # vtu exactly at +band -> "<=" side
        (-5.0e-5, -5.0e-5, 1),
    ]

    vtl = np.array([c[0] for c in cases])
    vtu = np.array([c[1] for c in cases])
    expected = np.array([c[2] for c in cases], dtype=float)
    zeta_lo = np.full_like(vtl, zeta_ok)

    code = cc.classify(vtl, vtu, zeta_lo, band=band, vortex_min=5.0e-5)
    assert code.dtype == np.float32
    np.testing.assert_array_equal(code, expected)


def test_classify_masks_below_vortex_min():
    band = 3.0e-5
    vortex_min = 5.0e-5
    vtl = np.array([5.0e-5, -5.0e-5, 0.0])
    vtu = np.array([5.0e-5, 5.0e-5, 0.0])
    zeta_lo = np.full_like(vtl, vortex_min - 1.0e-6)  # just below threshold

    code = cc.classify(vtl, vtu, zeta_lo, band=band, vortex_min=vortex_min)
    assert np.all(np.isnan(code))


def test_classify_nan_input_propagates():
    band = 3.0e-5
    vtl = np.array([np.nan, 5.0e-5])
    vtu = np.array([5.0e-5, 5.0e-5])
    zeta_lo = np.array([1.0e-4, 1.0e-4])

    code = cc.classify(vtl, vtu, zeta_lo, band=band, vortex_min=5.0e-5)
    assert np.isnan(code[0])
    assert code[1] == 4.0


# ---------------------------------------------------------------------------
# (k): continuous_index()
# ---------------------------------------------------------------------------


def test_continuous_index_extremes_and_masking():
    zeta_ok = 1.0e-4
    scale = 1.0e-4
    large = 1.0e2 * scale  # tanh saturates hard by this point

    idx_deep_warm = cc.continuous_index(np.array([large]), np.array([large]), np.array([zeta_ok]), scale=scale)
    np.testing.assert_allclose(idx_deep_warm, 3.0, atol=1e-3)

    idx_cold = cc.continuous_index(np.array([-large]), np.array([-large]), np.array([zeta_ok]), scale=scale)
    np.testing.assert_allclose(idx_cold, -3.0, atol=1e-3)

    idx_neutral = cc.continuous_index(np.array([0.0]), np.array([0.0]), np.array([zeta_ok]), scale=scale)
    np.testing.assert_allclose(idx_neutral, 0.0, atol=1e-6)

    idx_shallow = cc.continuous_index(np.array([large]), np.array([0.0]), np.array([zeta_ok]), scale=scale)
    np.testing.assert_allclose(idx_shallow, 2.0, atol=1e-3)

    idx_masked = cc.continuous_index(np.array([large]), np.array([large]), np.array([1.0e-6]), scale=scale)
    assert np.all(np.isnan(idx_masked))


def test_continuous_index_monotonic_in_vtl():
    zeta_ok = 1.0e-4
    scale = 1.0e-4
    vtl = np.linspace(-5.0e-4, 5.0e-4, 21)
    vtu_fixed = np.zeros_like(vtl)
    zeta_lo = np.full_like(vtl, zeta_ok)

    idx = cc.continuous_index(vtl, vtu_fixed, zeta_lo, scale=scale)
    assert np.all(np.diff(idx) > 0)


# ---------------------------------------------------------------------------
# (l): core_fields() on a three-level solid-body vortex
# ---------------------------------------------------------------------------


def test_core_fields_three_level_vortex(standard_orientation):
    x, y = _grid()
    W_lo, W_mid, W_hi = 1.0e-4, 0.6e-4, 0.2e-4
    u_lo, v_lo = -W_lo * y, W_lo * x
    u_mid, v_mid = -W_mid * y, W_mid * x
    u_hi, v_hi = -W_hi * y, W_hi * x

    vtl, vtu, zeta_lo_smoothed = cc.core_fields(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M, smooth_km=0.0
    )

    expected_vtl = 2.0 * (W_lo - W_mid)
    expected_vtu = 2.0 * (W_mid - W_hi)
    expected_zeta_lo = 2.0 * W_lo

    # float64 compare before any float32 cast, per the task's analytic
    # expectations.
    np.testing.assert_allclose(_interior(vtl), expected_vtl, rtol=1e-6)
    np.testing.assert_allclose(_interior(vtu), expected_vtu, rtol=1e-6)
    np.testing.assert_allclose(_interior(zeta_lo_smoothed), expected_zeta_lo, rtol=1e-6)


# ---------------------------------------------------------------------------
# (m): executeClass() on the three-level vortex
# ---------------------------------------------------------------------------


def test_execute_class_deep_warm_core(standard_orientation):
    x, y = _grid()
    W_lo, W_mid, W_hi = 1.0e-4, 0.6e-4, 0.2e-4
    u_lo, v_lo = -W_lo * y, W_lo * x
    u_mid, v_mid = -W_mid * y, W_mid * x
    u_hi, v_hi = -W_hi * y, W_hi * x

    code = cc.executeClass(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=0.0, band=3.0e-5, vortexMin=5.0e-5,
    )
    assert code.dtype == np.float32
    np.testing.assert_allclose(_interior(code), 4.0)


def test_execute_class_cold_core_needs_lower_vortex_min(standard_orientation):
    # W_lo=0.2e-4, W_mid=0.6e-4, W_hi=1.0e-4: zeta_lo = 2*W_lo = 0.4e-4,
    # which is BELOW the default vortex_min (5e-5), so with the default
    # threshold this comes out fully masked (NaN), not classified as cold.
    x, y = _grid()
    W_lo, W_mid, W_hi = 0.2e-4, 0.6e-4, 1.0e-4
    u_lo, v_lo = -W_lo * y, W_lo * x
    u_mid, v_mid = -W_mid * y, W_mid * x
    u_hi, v_hi = -W_hi * y, W_hi * x

    masked_with_default = cc.executeClass(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=0.0, band=3.0e-5,
    )
    assert np.all(np.isnan(_interior(masked_with_default)))

    code = cc.executeClass(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=0.0, band=3.0e-5, vortexMin=1.0e-5,
    )
    np.testing.assert_allclose(_interior(code), 1.0)


def test_execute_class_mid_level_vortex(standard_orientation):
    # W_lo=0.5e-4, W_mid=1.0e-4, W_hi=0.5e-4: vtl = 2*(0.5-1.0)e-4 = -1e-4,
    # vtu = 2*(1.0-0.5)e-4 = +1e-4 -> mid-level vortex (code 0).
    x, y = _grid()
    W_lo, W_mid, W_hi = 0.5e-4, 1.0e-4, 0.5e-4
    u_lo, v_lo = -W_lo * y, W_lo * x
    u_mid, v_mid = -W_mid * y, W_mid * x
    u_hi, v_hi = -W_hi * y, W_hi * x

    code = cc.executeClass(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=0.0, band=3.0e-5, vortexMin=1.0e-5,
    )
    np.testing.assert_allclose(_interior(code), 0.0)


def test_execute_class_weak_rotation_all_masked():
    # Weak all-equal solid-body rotation at every level: zeta_lo = 2*W is
    # below the default vortex_min, so every point is masked NaN.
    x, y = _grid()
    W = 1.0e-6
    u, v = -W * y, W * x

    code = cc.executeClass(u, v, u, v, u, v, _SPACING_M, _SPACING_M, smoothKm=0.0)
    assert np.all(np.isnan(code))


# ---------------------------------------------------------------------------
# (n): executeIndex()
# ---------------------------------------------------------------------------


def test_execute_index_deep_warm_and_cold(standard_orientation):
    x, y = _grid()

    # Wider level-to-level separation than the executeClass fixture so
    # vtl/scale and vtu/scale (both = 2 here, scale = DEFAULT_INDEX_SCALE)
    # push tanh well past its half-saturation point:
    # idx = 3*tanh(2) ~= 2.89 > 2.
    W_lo, W_mid, W_hi = 2.0e-4, 1.0e-4, 0.0
    u_lo, v_lo = -W_lo * y, W_lo * x
    u_mid, v_mid = -W_mid * y, W_mid * x
    u_hi, v_hi = -W_hi * y, W_hi * x
    idx_warm = cc.executeIndex(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=0.0, vortexMin=5.0e-5,
    )
    assert idx_warm.dtype == np.float32
    assert np.all(_interior(idx_warm) > 2.0)

    W_lo2, W_mid2, W_hi2 = 0.2e-4, 0.6e-4, 1.0e-4
    u_lo2, v_lo2 = -W_lo2 * y, W_lo2 * x
    u_mid2, v_mid2 = -W_mid2 * y, W_mid2 * x
    u_hi2, v_hi2 = -W_hi2 * y, W_hi2 * x
    idx_cold = cc.executeIndex(
        u_lo2, v_lo2, u_mid2, v_mid2, u_hi2, v_hi2, _SPACING_M, _SPACING_M,
        smoothKm=0.0, vortexMin=1.0e-5,
    )
    assert np.all(_interior(idx_cold) < -1.0)


# ---------------------------------------------------------------------------
# (o): scalar constants as 1-element arrays
# ---------------------------------------------------------------------------


def test_execute_class_and_index_constant_coercion(standard_orientation):
    x, y = _grid()
    W_lo, W_mid, W_hi = 1.0e-4, 0.6e-4, 0.2e-4
    u_lo, v_lo = -W_lo * y, W_lo * x
    u_mid, v_mid = -W_mid * y, W_mid * x
    u_hi, v_hi = -W_hi * y, W_hi * x

    baseline_code = cc.executeClass(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=0.0, band=3.0e-5, vortexMin=5.0e-5,
    )
    array_code = cc.executeClass(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=np.array([0.0]), band=np.array([3.0e-5]), vortexMin=np.array([5.0e-5]),
    )
    np.testing.assert_allclose(array_code, baseline_code)

    baseline_idx = cc.executeIndex(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=0.0, scale=1.0e-4, vortexMin=5.0e-5,
    )
    array_idx = cc.executeIndex(
        u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M,
        smoothKm=np.array([0.0]), scale=np.array([1.0e-4]), vortexMin=np.array([5.0e-5]),
    )
    np.testing.assert_allclose(array_idx, baseline_idx)


# ---------------------------------------------------------------------------
# (p): Southern Hemisphere masking of CPScat
# ---------------------------------------------------------------------------


def test_southern_hemisphere_class_entirely_masked():
    # Clockwise (Southern Hemisphere cyclonic) rotation, weakening with
    # height at each level -- physically a deep warm core, but relative
    # vorticity is negative for a SH cyclone, so the vortex mask
    # (zeta_lo < vortex_min) blanks it entirely rather than merely
    # flipping its sign. Documented limitation (see D2D/README.md).
    x, y = _grid()
    W_lo, W_mid, W_hi = -1.0e-4, -0.6e-4, -0.2e-4
    u_lo, v_lo = -W_lo * y, W_lo * x
    u_mid, v_mid = -W_mid * y, W_mid * x
    u_hi, v_hi = -W_hi * y, W_hi * x

    code = cc.executeClass(u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, _SPACING_M, _SPACING_M, smoothKm=0.0)
    assert np.all(np.isnan(code))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
