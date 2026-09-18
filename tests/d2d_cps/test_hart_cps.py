"""Analytic tests for D2D/derivedParameters/functions/HartCPS.py.

Expectations here are derived independently from the algorithm's own
specification (brute-force sliding-window loops, the closed-form
least-squares formula, and a second numerical implementation of Hart's
actual method via `cps.hart`) rather than copied from HartCPS.py's own
implementation, per the task instructions.

`tests/d2d_cps/conftest.py` puts `D2D/derivedParameters/functions` on
sys.path (`import HartCPS`), the repo root on sys.path (`import cps`),
and `tests/cps` on sys.path (`import synthetic`, the vortex-generator
module `tests/cps/test_hart.py` itself uses).
"""

from __future__ import annotations

import math
import time
import warnings

import numpy as np
import pytest

import HartCPS as hc
import cps
import synthetic

EARTH_RADIUS_KM = 6371.0


# ---------------------------------------------------------------------------
# Brute-force references
# ---------------------------------------------------------------------------


def _brute_extreme_1d(a: np.ndarray, half_width: int, axis: int, kind: str) -> np.ndarray:
    """Naive O(N*w) sliding max/min along `axis`, NaN-ignoring, edges
    clipped -- independent of HartCPS.running_extreme_1d's doubling-trick
    implementation.
    """
    a = np.asarray(a, dtype=float)
    n = a.shape[axis]
    out = np.empty_like(a)
    reducer = np.nanmax if kind == "max" else np.nanmin
    for i in range(n):
        lo = max(0, i - half_width)
        hi = min(n - 1, i + half_width)
        idx = [slice(None)] * a.ndim
        idx[axis] = slice(lo, hi + 1)
        window = a[tuple(idx)]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            reduced = reducer(window, axis=axis)
        out_idx = [slice(None)] * a.ndim
        out_idx[axis] = i
        out[tuple(out_idx)] = reduced
    return out


def _brute_window_sum_2d(field, half_x_per_row, half_y):
    """Naive nested-loop two-pass (row then column) box sum/count, NaN
    treated as missing -- independent of HartCPS.window_sum_2d's
    cumulative-sum implementation, matching only its two-pass
    definition (per-row x half-width, then a scalar y half-width).
    """
    field = np.asarray(field, dtype=float)
    ny, nx = field.shape

    row_sum = np.empty_like(field)
    row_cnt = np.empty_like(field)
    for i in range(ny):
        hw = int(half_x_per_row[i])
        for j in range(nx):
            lo, hi = max(0, j - hw), min(nx - 1, j + hw)
            window = field[i, lo : hi + 1]
            valid = np.isfinite(window)
            row_sum[i, j] = np.sum(window[valid])
            row_cnt[i, j] = np.sum(valid)

    out_sum = np.empty_like(field)
    out_cnt = np.empty_like(field)
    for i in range(ny):
        lo, hi = max(0, i - half_y), min(ny - 1, i + half_y)
        for j in range(nx):
            out_sum[i, j] = np.sum(row_sum[lo : hi + 1, j])
            out_cnt[i, j] = np.sum(row_cnt[lo : hi + 1, j])
    return out_sum, out_cnt


def _brute_window_extreme_2d(field, half_x_per_row, half_y, kind) -> np.ndarray:
    """Naive nested-loop two-pass (row then column) sliding extreme,
    matching window_extreme_2d's own definition (per-row x half-width,
    then a scalar y half-width) but with no vectorization or doubling
    trick at all -- independent of HartCPS.window_extreme_2d's
    grouped-rows-plus-running_extreme_1d implementation.
    """
    field = np.asarray(field, dtype=float)
    ny, nx = field.shape
    reducer = np.nanmax if kind == "max" else np.nanmin

    out_x = np.empty_like(field)
    for i in range(ny):
        hw = int(half_x_per_row[i])
        for j in range(nx):
            lo = max(0, j - hw)
            hi = min(nx - 1, j + hw)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                out_x[i, j] = reducer(field[i, lo : hi + 1])

    out = np.empty_like(field)
    for i in range(ny):
        lo = max(0, i - half_y)
        hi = min(ny - 1, i + half_y)
        for j in range(nx):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                out[i, j] = reducer(out_x[lo : hi + 1, j])
    return out


# ---------------------------------------------------------------------------
# (a) running_extreme_1d vs brute force
# ---------------------------------------------------------------------------


def test_running_extreme_1d_matches_brute_force():
    rng = np.random.default_rng(20260917)
    a = rng.standard_normal((13, 17))
    nan_mask = rng.random((13, 17)) < 0.12
    a[nan_mask] = np.nan

    for half_width in (0, 1, 2, 5, 17):
        for axis in (0, 1):
            for kind in ("max", "min"):
                got = hc.running_extreme_1d(a, half_width, axis=axis, kind=kind)
                expected = _brute_extreme_1d(a, half_width, axis=axis, kind=kind)
                np.testing.assert_allclose(
                    got, expected, equal_nan=True,
                    err_msg=f"half_width={half_width} axis={axis} kind={kind}",
                )


def test_running_extreme_1d_zero_half_width_is_copy():
    a = np.array([[1.0, np.nan, 3.0], [4.0, 5.0, 6.0]])
    result = hc.running_extreme_1d(a, 0, axis=1, kind="max")
    assert result is not a
    np.testing.assert_array_equal(result[np.isfinite(a)], a[np.isfinite(a)])
    assert np.isnan(result[0, 1])


def test_running_extreme_1d_all_nan_window_is_nan():
    a = np.array([np.nan, np.nan, np.nan, 5.0, np.nan])
    result_max = hc.running_extreme_1d(a, 1, axis=0, kind="max")
    # Position 0's window (positions 0,1, plus left padding) is all-NaN.
    assert np.isnan(result_max[0])
    # Position 2's window (1,2,3) includes the real value 5.0.
    assert result_max[2] == 5.0


# ---------------------------------------------------------------------------
# (b) window_extreme_2d vs brute force, varying per-row half-widths
# ---------------------------------------------------------------------------


def test_window_extreme_2d_matches_brute_force_varying_half_widths():
    rng = np.random.default_rng(7)
    ny, nx = 9, 11
    field = rng.standard_normal((ny, nx))
    nan_mask = rng.random((ny, nx)) < 0.1
    field[nan_mask] = np.nan

    half_x_per_row = np.array([1, 2, 3, 4, 1, 2, 3, 4, 1])
    assert half_x_per_row.shape == (ny,)
    half_y = 2

    for kind in ("max", "min"):
        got = hc.window_extreme_2d(field, half_x_per_row, half_y, kind)
        expected = _brute_window_extreme_2d(field, half_x_per_row, half_y, kind)
        np.testing.assert_allclose(got, expected, equal_nan=True, err_msg=kind)


def test_window_sum_2d_matches_brute_force_varying_half_widths():
    rng = np.random.default_rng(11)
    ny, nx = 9, 11
    field = rng.standard_normal((ny, nx))
    nan_mask = rng.random((ny, nx)) < 0.15
    field[nan_mask] = np.nan

    half_x_per_row = np.array([1, 2, 3, 1, 2, 3, 1, 2, 3])
    half_y = 2

    got_sum, got_cnt = hc.window_sum_2d(field, half_x_per_row, half_y)
    expected_sum, expected_cnt = _brute_window_sum_2d(field, half_x_per_row, half_y)
    np.testing.assert_allclose(got_sum, expected_sum)
    np.testing.assert_allclose(got_cnt, expected_cnt)


def test_window_sum_2d_all_nan_window_is_zero_count():
    field = np.full((5, 5), np.nan)
    s, c = hc.window_sum_2d(field, np.full(5, 1), 1)
    np.testing.assert_allclose(s, 0.0)
    np.testing.assert_allclose(c, 0.0)


def test_window_extreme_2d_clamps_half_width():
    # A half-width far larger than the axis size must not raise or index
    # out of bounds -- it is clamped to (n-1)//2 for that axis and must
    # then match a brute-force computation using that same clamped
    # half-width (not "the whole axis": for e.g. nx=5, (nx-1)//2 == 2,
    # a window that still shrinks away from the corners, not one that
    # reaches every column from every starting position).
    field = np.arange(20.0).reshape(4, 5)
    half_x_per_row = np.full(4, 1000)
    clamped_x = np.full(4, (field.shape[1] - 1) // 2)
    clamped_y = (field.shape[0] - 1) // 2

    for kind in ("max", "min"):
        got = hc.window_extreme_2d(field, half_x_per_row, 1000, kind)
        expected = _brute_window_extreme_2d(field, clamped_x, clamped_y, kind)
        np.testing.assert_allclose(got, expected, err_msg=kind)


# ---------------------------------------------------------------------------
# (c) band_slope: exact linear case, NaN propagation
# ---------------------------------------------------------------------------


def test_band_slope_exact_for_linear_dz():
    pressures = [925.0, 850.0, 700.0]
    x = np.log(np.asarray(pressures))
    true_slope = 137.5
    true_intercept = 42.0
    ny, nx = 4, 6
    dz_list = [np.full((ny, nx), true_intercept + true_slope * xi) for xi in x]

    slope = hc.band_slope(dz_list, pressures)
    np.testing.assert_allclose(slope, true_slope, rtol=1e-10)


def test_band_slope_exact_for_linear_dz_varies_by_gridpoint():
    # A different (slope, intercept) pair baked into every grid point,
    # not a single constant field -- band_slope must recover each one
    # independently and elementwise.
    pressures = [925.0, 850.0, 700.0, 500.0]
    x = np.log(np.asarray(pressures))
    ny, nx = 5, 5
    rng = np.random.default_rng(3)
    slopes = rng.uniform(-300.0, 300.0, size=(ny, nx))
    intercepts = rng.uniform(-50.0, 50.0, size=(ny, nx))
    dz_list = [intercepts + slopes * xi for xi in x]

    got = hc.band_slope(dz_list, pressures)
    np.testing.assert_allclose(got, slopes, rtol=1e-9)


def test_band_slope_nan_propagates():
    pressures = [925.0, 850.0, 700.0]
    dz_list = [np.ones((3, 3)), np.ones((3, 3)), np.ones((3, 3))]
    dz_list[1][1, 1] = np.nan

    slope = hc.band_slope(dz_list, pressures)
    assert np.isnan(slope[1, 1])
    finite_mask = np.ones((3, 3), dtype=bool)
    finite_mask[1, 1] = False
    assert np.all(np.isfinite(slope[finite_mask]))


def test_band_slope_requires_at_least_two_levels():
    with pytest.raises(ValueError):
        hc.band_slope([np.zeros((2, 2))], [850.0])


# ---------------------------------------------------------------------------
# (d) Reference check against cps.hart on a synthetic warm/cold-core vortex
# ---------------------------------------------------------------------------


def _grid_and_dx_dy(clat, clon, half_width_deg, dlat):
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=half_width_deg, dlat=dlat, dlon=dlat)
    lat_vals = lat2d[:, 0]
    dx_row = EARTH_RADIUS_KM * np.cos(np.radians(lat_vals)) * np.radians(dlat) * 1000.0
    dx2d = np.repeat(dx_row[:, np.newaxis], lon2d.shape[1], axis=1)
    dy_m = EARTH_RADIUS_KM * np.radians(dlat) * 1000.0
    return lat2d, lon2d, dx2d, dy_m


def _standard_level_hart_reference(lat2d, lon2d, clat, clon, z_stack, levels):
    """Hart's own circular-window dZ (via cps.hart.thermal_wind) at every
    one of `levels`, then this module's own closed-form band slope
    (cps.hart._band_slope, called directly rather than through
    thermal_wind()'s built-in LOWER_LEVELS/UPPER_LEVELS bands, which do
    not line up with HartCPS's standard-level bands) over LOWER_BAND and
    UPPER_BAND -- the reference this module's square-window
    thermal_wind_grid is compared against.
    """
    hart_result = cps.thermal_wind(levels, z_stack, lat2d, lon2d, clat, clon, radius_km=hc.RADIUS_KM)
    dz_by_level = hart_result["dz_by_level"]
    vtl_ref = cps.hart._band_slope(dz_by_level, hc.LOWER_BAND)
    vtu_ref = cps.hart._band_slope(dz_by_level, hc.UPPER_BAND)
    return vtl_ref, vtu_ref


def test_thermal_wind_grid_matches_hart_reference_warm_core():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg=8.0, dlat=0.25)

    A0 = 300.0

    def warm_amp(p):
        return A0 * (math.log(p / 300.0) / math.log(900.0 / 300.0)) ** 2

    levels = hc.LOWER_BAND + hc.UPPER_BAND
    z_stack = synthetic.warm_core_heights(lat2d, lon2d, clat, clon, levels, warm_amp, scale_km=150.0)
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}

    vtl_grid = hc.thermal_wind_grid([z_by_level[p] for p in hc.LOWER_BAND], hc.LOWER_BAND, dx2d, dy_m, hc.RADIUS_KM)
    vtu_grid = hc.thermal_wind_grid([z_by_level[p] for p in hc.UPPER_BAND], hc.UPPER_BAND, dx2d, dy_m, hc.RADIUS_KM)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    vtl_ref, vtu_ref = _standard_level_hart_reference(lat2d, lon2d, clat, clon, z_stack, levels)

    # Square (this module) vs circle (cps.hart) window: agreement within
    # 2% on a smooth 150 km-scale Gaussian, per the module docstring.
    assert vtl_grid[ci, cj] == pytest.approx(vtl_ref, rel=0.02)
    assert vtu_grid[ci, cj] == pytest.approx(vtu_ref, rel=0.02)

    # Warm core: both positive.
    assert vtl_grid[ci, cj] > 0
    assert vtu_grid[ci, cj] > 0
    assert vtl_ref > 0 and vtu_ref > 0


def test_thermal_wind_grid_matches_hart_reference_cold_core():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg=8.0, dlat=0.25)

    A0 = 300.0

    def cold_amp(p):
        return A0 * (1.0 - math.log(p / 300.0) / math.log(3.0))

    levels = hc.LOWER_BAND + hc.UPPER_BAND
    z_stack = synthetic.warm_core_heights(lat2d, lon2d, clat, clon, levels, cold_amp, scale_km=150.0)
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}

    vtl_grid = hc.thermal_wind_grid([z_by_level[p] for p in hc.LOWER_BAND], hc.LOWER_BAND, dx2d, dy_m, hc.RADIUS_KM)
    vtu_grid = hc.thermal_wind_grid([z_by_level[p] for p in hc.UPPER_BAND], hc.UPPER_BAND, dx2d, dy_m, hc.RADIUS_KM)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    vtl_ref, vtu_ref = _standard_level_hart_reference(lat2d, lon2d, clat, clon, z_stack, levels)

    assert vtl_grid[ci, cj] == pytest.approx(vtl_ref, rel=0.02)
    assert vtu_grid[ci, cj] == pytest.approx(vtu_ref, rel=0.02)

    # Cold core: both negative.
    assert vtl_grid[ci, cj] < 0
    assert vtu_grid[ci, cj] < 0
    assert vtl_ref < 0 and vtu_ref < 0


# ---------------------------------------------------------------------------
# (e) closed_low_mask -- candidate-plus-annulus-depth detector
# ---------------------------------------------------------------------------

# closed_low_mask's dilation step uses a *square* window (like everything
# else in this file), whose corners reach sqrt(2) times its half-width --
# see the module docstring's "Square window versus Hart's circle" section.
# The tight (5 m) candidate test around a smooth 150 km-scale Gaussian low
# also has some spatial extent of its own (the height only needs to rise
# 5 m from the true minimum, which for a gentle 150 km-scale bowl reaches
# several tens of km out), so the dilated blob's true reach from the exact
# center is a bit more than DEFAULT_BLOB_RADIUS_KM: this bound is a generous
# but finite envelope for both effects together, used instead of a tight
# "blob_radius + one grid spacing" bound that assumes a circular dilation
# and a single-pixel candidate.
_BLOB_REACH_BOUND_KM = math.sqrt(2.0) * hc.DEFAULT_BLOB_RADIUS_KM + 75.0


def _big_grid(clat=20.0, clon=0.0, half_width_deg=None, dlat=0.25):
    """A grid at least 1500 km across (so the old annulus false-positive
    -- see closed_low_mask's docstring -- would have shown up well inside
    it) with dx/dy pseudo-fields to match.
    """
    if half_width_deg is None:
        half_width_deg = 8.0  # ~890 km half-width at this latitude/dlon
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)
    r_km = synthetic._haversine_km(lat2d, lon2d, clat, clon)
    assert r_km.max() * 2.0 >= 1500.0  # domain spans >= 1500 km across
    return lat2d, lon2d, dx2d, dy_m, r_km


def _gaussian_low(r_km, depth_m, scale_km=150.0, background_m=1500.0):
    return background_m - depth_m * np.exp(-(r_km / scale_km) ** 2)


def test_closed_low_mask_gaussian_low_blob_and_far_field_false():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, dx2d, dy_m, r_km = _big_grid(clat, clon)
    z925 = _gaussian_low(r_km, depth_m=60.0, scale_km=150.0)

    mask = hc.closed_low_mask(z925, dx2d, dy_m)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    assert mask[ci, cj]  # True at the center (r = 0)

    row = ci
    j150 = int(np.argmin(np.abs(r_km[row, :] - 150.0)))
    assert mask[row, j150]  # True at ~150 km out

    assert not np.any(mask & (r_km > 400.0))  # False at 400 km and beyond
    assert np.all(r_km[mask] <= _BLOB_REACH_BOUND_KM)  # confined near the low


def test_closed_low_mask_low_on_uniform_gradient_still_one_blob():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, dx2d, dy_m, r_km = _big_grid(clat, clon)

    dlon_deg = ((lon2d - clon + 180.0) % 360.0) - 180.0
    dx_km_from_center = EARTH_RADIUS_KM * math.cos(math.radians(clat)) * np.radians(dlon_deg)
    gradient_m_per_km = 50.0 / 1000.0  # 50 m per 1000 km
    z_gradient = 1500.0 + gradient_m_per_km * dx_km_from_center

    z925 = z_gradient - 60.0 * np.exp(-(r_km / 150.0) ** 2)
    mask = hc.closed_low_mask(z925, dx2d, dy_m)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    assert mask[ci, cj]
    assert np.all(r_km[mask] <= _BLOB_REACH_BOUND_KM)  # a single blob at the low, nothing else


def test_closed_low_mask_uniform_gradient_alone_all_false():
    # The failure mode this replaces the old formula for: a uniform slope
    # (no low at all) is, to within a few meters, its own neighborhood
    # minimum everywhere in the downslope direction, and an old-style
    # "window max minus window min is big" test also passes everywhere on
    # a slope -- see closed_low_mask's docstring. The new annulus-depth
    # test must reject this outright.
    clat, clon = 20.0, 0.0
    lat2d, lon2d, dx2d, dy_m, r_km = _big_grid(clat, clon)

    dlon_deg = ((lon2d - clon + 180.0) % 360.0) - 180.0
    dx_km_from_center = EARTH_RADIUS_KM * math.cos(math.radians(clat)) * np.radians(dlon_deg)
    gradient_m_per_km = 50.0 / 1000.0
    z925 = 1500.0 + gradient_m_per_km * dx_km_from_center

    mask = hc.closed_low_mask(z925, dx2d, dy_m)
    assert not np.any(mask)


def test_closed_low_mask_shallow_low_all_false():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, dx2d, dy_m, r_km = _big_grid(clat, clon)
    z925 = _gaussian_low(r_km, depth_m=20.0, scale_km=150.0)  # depth 20 m < depthM 40

    mask = hc.closed_low_mask(z925, dx2d, dy_m, depth_m=40.0)
    assert not np.any(mask)


def test_closed_low_mask_flat_field_all_false():
    lat2d, lon2d, dx2d, dy_m, r_km = _big_grid()
    z925 = np.full(lat2d.shape, 1500.0)

    mask = hc.closed_low_mask(z925, dx2d, dy_m)
    assert not np.any(mask)


def test_closed_low_mask_two_lows_two_separate_blobs():
    clat, clon_a = 20.0, 0.0
    separation_km = 1200.0
    dlon_deg = math.degrees(separation_km / (EARTH_RADIUS_KM * math.cos(math.radians(clat))))
    clon_b = clon_a + dlon_deg
    mid_lon = (clon_a + clon_b) / 2.0

    half_width_deg = dlon_deg / 2.0 + 8.0  # margin beyond each low
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, mid_lon, half_width_deg, 0.25)
    r_a = synthetic._haversine_km(lat2d, lon2d, clat, clon_a)
    r_b = synthetic._haversine_km(lat2d, lon2d, clat, clon_b)

    z925 = 1500.0 - 60.0 * np.exp(-(r_a / 150.0) ** 2) - 60.0 * np.exp(-(r_b / 150.0) ** 2)
    mask = hc.closed_low_mask(z925, dx2d, dy_m)

    idx_a = np.unravel_index(np.argmin(r_a), r_a.shape)
    idx_b = np.unravel_index(np.argmin(r_b), r_b.shape)
    idx_mid = np.unravel_index(np.argmin(np.abs(r_a - r_b)), r_a.shape)

    assert mask[idx_a]
    assert mask[idx_b]
    assert not mask[idx_mid]  # the gap between the two lows is not painted

    # The two detections are genuinely disjoint, not one big connected
    # blob spanning the 1200 km gap: no True point is simultaneously far
    # from *both* centers (i.e. every True point is within the envelope
    # of one low or the other, not something in between).
    near_a = r_a <= _BLOB_REACH_BOUND_KM
    near_b = r_b <= _BLOB_REACH_BOUND_KM
    assert np.array_equal(mask, mask & (near_a | near_b))


# ---------------------------------------------------------------------------
# (f) executeIndexStd on a synthetic warm-core vortex
# ---------------------------------------------------------------------------


def _warm_core_fields(amp_by_level, clat=20.0, clon=0.0, half_width_deg=20.0, dlat=0.5):
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)
    levels = tuple(amp_by_level.keys())
    z_stack = synthetic.warm_core_heights(
        lat2d, lon2d, clat, clon, levels, lambda p: amp_by_level[p], scale_km=150.0
    )
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}
    return lat2d, lon2d, z_by_level, dx2d, dy_m


def _ocean_psfc(shape, hpa=1013.0):
    """A uniform, terrain-free surface pressure field (hPa) -- passed to
    executeIndexStd/executeHartClass wherever a test is not itself about
    below-ground masking, so `mask_below_ground` never blanks anything.
    """
    return np.full(shape, hpa)


def test_execute_index_std_deep_warm_core_and_far_field_nan():
    # z1000 is built the same way as z925 (same synthetic-vortex machinery),
    # with a slightly larger amplitude so the low is deepest at 1000 hPa --
    # closed_low_mask reads z1000, not z925 (see HartCPS.py's module
    # docstring, "Closed-low mask level").
    amp_by_level = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    lat2d, lon2d, z_by_level, dx2d, dy_m = _warm_core_fields(amp_by_level)

    idx = hc.executeIndexStd(
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        _ocean_psfc(lat2d.shape), dx2d, dy_m,
    )
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    assert idx.dtype == np.float32
    assert idx[ci, cj] > 2.0  # deep warm core, tanh saturating positive
    assert np.isnan(idx[0, 0])


# ---------------------------------------------------------------------------
# (g) Below-ground masking (surface_pressure_hpa, mask_below_ground,
#     BELOW_GROUND_CAP_HPA, and the psfc/capHpa entry-point wiring)
# ---------------------------------------------------------------------------


def test_surface_pressure_hpa_auto_detects_pa_vs_hpa():
    hpa = np.array([1013.0, 1000.0, 960.0, np.nan])
    pa = hpa * 100.0

    np.testing.assert_allclose(hc.surface_pressure_hpa(hpa), hpa, equal_nan=True)
    np.testing.assert_allclose(hc.surface_pressure_hpa(pa), hpa, equal_nan=True)


def test_mask_below_ground_cap_applies_at_level_1000():
    # level_hpa=1000, cap_hpa=900 (the module default) -> threshold is
    # min(1000, 900) == 900. psfc 880 is below that -- masked. psfc 920
    # is not -- left alone, even though it is itself below 1000 hPa
    # (the whole point of the cap).
    z = np.array([[500.0, 500.0]])
    psfc_hpa = np.array([[880.0, 920.0]])

    masked = hc.mask_below_ground(z, psfc_hpa, level_hpa=1000.0)

    assert np.isnan(masked[0, 0])
    assert masked[0, 1] == 500.0


def test_mask_below_ground_deep_ocean_low_not_masked_by_cap():
    # A deep low's own surface pressure (960 hPa at its center) is well
    # under both the 1000 and 925 hPa standard levels, but well above
    # BELOW_GROUND_CAP_HPA's default 900 -- nothing should be masked at
    # either level; the cap, not the level's own literal pressure, is
    # what decides.
    z = np.full((3, 3), 1500.0)
    psfc_hpa = np.full((3, 3), 960.0)

    for level_hpa in (1000.0, 925.0):
        masked = hc.mask_below_ground(z, psfc_hpa, level_hpa, cap_hpa=hc.BELOW_GROUND_CAP_HPA)
        np.testing.assert_allclose(masked, z)


def test_execute_index_std_psfc_accepts_pa_or_hpa():
    amp_by_level = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    lat2d, lon2d, z_by_level, dx2d, dy_m = _warm_core_fields(amp_by_level)
    args = (
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
    )

    idx_hpa = hc.executeIndexStd(*args, _ocean_psfc(lat2d.shape, hpa=1013.0), dx2d, dy_m)
    idx_pa = hc.executeIndexStd(*args, _ocean_psfc(lat2d.shape, hpa=101300.0), dx2d, dy_m)

    np.testing.assert_allclose(idx_pa, idx_hpa, equal_nan=True)


def test_execute_index_std_terrain_block_west_of_vortex():
    """A fake terrain block (surface pressure 750 hPa, well under
    BELOW_GROUND_CAP_HPA's 900) 800 km due west of a warm-core vortex.

    The block sits outside the vortex's own 500 km analysis window, so
    the index at the vortex center is unchanged by its presence, and
    HVTL at a point 300 km east of the block's near (eastern) edge --
    close enough that its own 500 km window reaches into the block, far
    enough that it is not the block itself -- is still finite and close
    to its no-terrain value, because the NaN-aware sliding window
    simply ignores the block's masked-out cells. The block's own
    footprint reads NaN (below ground).
    """
    clat, clon = 20.0, 0.0
    half_width_deg, dlat = 20.0, 0.5
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)

    amp_by_level = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    levels = tuple(amp_by_level.keys())
    z_stack = synthetic.warm_core_heights(
        lat2d, lon2d, clat, clon, levels, lambda p: amp_by_level[p], scale_km=150.0
    )
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}

    km_per_deg_lon = EARTH_RADIUS_KM * math.cos(math.radians(clat)) * math.radians(1.0)
    block_half_deg = 1.0
    block_dlon_deg = 800.0 / km_per_deg_lon
    block_lon_center = clon - block_dlon_deg
    block_mask = (
        (np.abs(lon2d - block_lon_center) <= block_half_deg)
        & (np.abs(lat2d - clat) <= block_half_deg)
    )

    psfc_ocean = _ocean_psfc(lat2d.shape)
    psfc_terrain = psfc_ocean.copy()
    psfc_terrain[block_mask] = 750.0

    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2
    band_args = (
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
    )

    idx_no_terrain = hc.executeIndexStd(*band_args, psfc_ocean, dx2d, dy_m)
    idx_terrain = hc.executeIndexStd(*band_args, psfc_terrain, dx2d, dy_m)

    assert idx_no_terrain[ci, cj] > 2.0  # deep warm core, tanh saturating positive
    assert idx_terrain[ci, cj] == pytest.approx(float(idx_no_terrain[ci, cj]), rel=0.05)  # unchanged: outside the 500 km window

    block_i, block_j = np.argwhere(block_mask)[0]
    assert np.isnan(idx_terrain[block_i, block_j])

    # East edge of the block (nearest the vortex), then 300 km further
    # east (closer to the vortex center).
    block_east_edge_km_west = 800.0 - block_half_deg * km_per_deg_lon
    test_point_km_west = block_east_edge_km_west - 300.0
    test_lon = clon - test_point_km_west / km_per_deg_lon
    tj = int(np.argmin(np.abs(lon2d[ci, :] - test_lon)))

    vtl_terrain = hc.thermal_wind_grid(
        [z_by_level[p] for p in hc.LOWER_BAND], hc.LOWER_BAND, dx2d, dy_m, hc.RADIUS_KM,
        psfc_hpa=psfc_terrain, cap_hpa=hc.BELOW_GROUND_CAP_HPA,
    )
    vtl_reference = hc.thermal_wind_grid(
        [z_by_level[p] for p in hc.LOWER_BAND], hc.LOWER_BAND, dx2d, dy_m, hc.RADIUS_KM,
    )

    assert np.isfinite(vtl_terrain[ci, tj])
    assert vtl_terrain[ci, tj] == pytest.approx(vtl_reference[ci, tj], rel=0.05)


# ---------------------------------------------------------------------------
# (h) Performance: 721x1440 grid, three levels, lat-dependent dx
# ---------------------------------------------------------------------------


def test_thermal_wind_grid_performance(capsys):
    ny, nx = 721, 1440
    lat_vals = np.linspace(-90.0, 90.0, ny)
    dlon_rad = math.radians(360.0 / nx)
    dx_row = EARTH_RADIUS_KM * np.cos(np.radians(lat_vals)) * dlon_rad * 1000.0
    # Not externally clamped: window_extreme_2d's own per-axis clamp
    # (half-width <= (n-1)//2) is what keeps the near-pole blow-up in
    # cell count from being a problem, per the module docstring.
    dx2d = np.repeat(dx_row[:, np.newaxis], nx, axis=1)
    dlat_rad = math.radians(180.0 / (ny - 1))
    dy_m = EARTH_RADIUS_KM * dlat_rad * 1000.0

    rng = np.random.default_rng(1234)
    base = rng.standard_normal((ny, nx)).astype(np.float32)

    def _smooth(a, passes=5):
        out = a.astype(np.float64)
        for _ in range(passes):
            out = (
                out
                + np.roll(out, 1, axis=0) + np.roll(out, -1, axis=0)
                + np.roll(out, 1, axis=1) + np.roll(out, -1, axis=1)
            ) / 5.0
        return out

    z1 = _smooth(base) * 50.0 + 3000.0
    z2 = _smooth(base + 1.0) * 50.0 + 2000.0
    z3 = _smooth(base + 2.0) * 50.0 + 1000.0

    start = time.perf_counter()
    grid = hc.thermal_wind_grid([z1, z2, z3], [850.0, 700.0, 500.0], dx2d, dy_m, hc.RADIUS_KM)
    elapsed = time.perf_counter() - start

    with capsys.disabled():
        print(f"\nHartCPS.thermal_wind_grid on a {ny}x{nx} grid, 3 levels: {elapsed:.3f} s")

    assert grid.shape == (ny, nx)
    assert elapsed < 8.0


# ---------------------------------------------------------------------------
# Parameter B and the joint class
# ---------------------------------------------------------------------------


@pytest.fixture
def hart_standard_orientation(monkeypatch):
    """Monkeypatch `HartCPS.ORIENTATION_MODE` to 0 (the plain numpy-default
    grid layout: axis 0 = y increasing northward, axis 1 = x) for the
    duration of a test -- the same pattern `conftest.py`'s
    `standard_orientation` fixture uses for `CycloneCore.ORIENTATION_MODE`.
    `HartCPS.ORIENTATION_MODE`'s own real default is 1 (tuned for AWIPS
    sites, per `gradient_2d`'s module-level comment), not "the standard
    layout" a test wants to reason about directly.
    """
    monkeypatch.setattr(hc, "ORIENTATION_MODE", 0)


# --- (a) gradient_2d: plane field, orientation modes ------------------------


def test_gradient_2d_plane_field_and_orientation_modes():
    ny, nx = 15, 17
    dx_m = 2000.0
    dy_m = 1500.0
    y_idx, x_idx = np.mgrid[0:ny, 0:nx]
    x_m = x_idx * dx_m
    y_m = y_idx * dy_m
    gx_true, gy_true = 3.5, -2.0
    field = gx_true * x_m + gy_true * y_m

    interior = (slice(2, -2), slice(2, -2))

    # Mode 0: plain numpy layout, no flip.
    gx0, gy0 = hc.gradient_2d(field, dx_m, dy_m, mode=0)
    np.testing.assert_allclose(gx0[interior], gx_true, rtol=1e-10)
    np.testing.assert_allclose(gy0[interior], gy_true, rtol=1e-10)

    # Mode 1: same x-derivative, y-derivative negated.
    gx1, gy1 = hc.gradient_2d(field, dx_m, dy_m, mode=1)
    np.testing.assert_allclose(gx1[interior], gx_true, rtol=1e-10)
    np.testing.assert_allclose(gy1[interior], -gy_true, rtol=1e-10)

    # Mode 2: transposed input -- output shape matches the transposed
    # input, and (since the field is exactly linear, so its gradient is
    # a constant everywhere) the recovered components equal the
    # untransposed gx_true/gy_true.
    field_t = field.T
    gx2, gy2 = hc.gradient_2d(field_t, dx_m, dy_m, mode=2)
    assert gx2.shape == field_t.shape
    assert gy2.shape == field_t.shape
    interior_t = (slice(2, -2), slice(2, -2))
    np.testing.assert_allclose(gx2[interior_t], gx_true, rtol=1e-10)
    np.testing.assert_allclose(gy2[interior_t], gy_true, rtol=1e-10)

    # Mode 3: transposed input, y-derivative also negated.
    gx3, gy3 = hc.gradient_2d(field_t, dx_m, dy_m, mode=3)
    np.testing.assert_allclose(gx3[interior_t], gx_true, rtol=1e-10)
    np.testing.assert_allclose(gy3[interior_t], -gy_true, rtol=1e-10)


def test_gradient_2d_invalid_mode_raises():
    field = np.zeros((5, 5))
    with pytest.raises(ValueError):
        hc.gradient_2d(field, 1000.0, 1000.0, mode=4)


# --- (b) parameter_b_grid: sign reasoning on a linear thickness gradient ---


def test_parameter_b_grid_sign_and_magnitude(hart_standard_orientation):
    # thickness = -g*y: warm/thick to the south (y < 0), cold/thin to the
    # north (y > 0) -- dThickness/dy = -g everywhere.
    ny, nx = 41, 43
    dx_m = 20000.0
    dy_m = 20000.0
    y_idx, x_idx = np.mgrid[0:ny, 0:nx]
    y_m = (y_idx - ny // 2) * dy_m
    g = 0.02  # m/m, a gentle thickness slope
    thickness = -g * y_m

    radius_km = 500.0
    layer_scale = 1.0
    ci, cj = ny // 2, nx // 2

    # Sign reasoning: moving due WEST, the right-hand side (NH) is NORTH
    # (facing west, north is to your right) -- the cold side of this
    # thickness field -- so the right-minus-left difference is negative,
    # and B = h*(mean_right - mean_left) with h=+1 in the NH is negative.
    full_magnitude = hc.b_geometry_km(radius_km) * 1000.0 * g * layer_scale

    u_west = np.full((ny, nx), -10.0)
    v_west = np.zeros((ny, nx))
    b_west = hc.parameter_b_grid(thickness, u_west, v_west, dx_m, dy_m, 1.0, radius_km, layer_scale)
    np.testing.assert_allclose(b_west[ci, cj], -full_magnitude, rtol=1e-6)

    # Moving due EAST instead, the right-hand side flips to SOUTH (the
    # warm side): B flips sign to positive.
    u_east = np.full((ny, nx), 10.0)
    v_east = np.zeros((ny, nx))
    b_east = hc.parameter_b_grid(thickness, u_east, v_east, dx_m, dy_m, 1.0, radius_km, layer_scale)
    np.testing.assert_allclose(b_east[ci, cj], full_magnitude, rtol=1e-6)

    # Southern Hemisphere (h=-1) flips the sign again, back to negative,
    # for the same due-east motion.
    b_east_sh = hc.parameter_b_grid(thickness, u_east, v_east, dx_m, dy_m, -1.0, radius_km, layer_scale)
    np.testing.assert_allclose(b_east_sh[ci, cj], -full_magnitude, rtol=1e-6)

    # Moving due NORTH -- parallel to the gradient, perpendicular to the
    # (east-west) thickness contours -- puts the "right" and "left" of
    # track equally on the warm and cold side on average: B collapses to
    # (near) zero, well within 2% of the west/east full magnitude.
    u_north = np.zeros((ny, nx))
    v_north = np.full((ny, nx), 10.0)
    b_north = hc.parameter_b_grid(thickness, u_north, v_north, dx_m, dy_m, 1.0, radius_km, layer_scale)
    assert abs(b_north[ci, cj]) < 0.02 * full_magnitude

    # Zero steering: no well defined direction of motion -> NaN.
    u_zero = np.zeros((ny, nx))
    v_zero = np.zeros((ny, nx))
    b_zero = hc.parameter_b_grid(thickness, u_zero, v_zero, dx_m, dy_m, 1.0, radius_km, layer_scale)
    assert np.isnan(b_zero[ci, cj])


# --- (c) cross-check against cps.hart.parameter_b's true half-disk means ---


def test_parameter_b_grid_matches_cps_hart_parameter_b(hart_standard_orientation):
    clat, clon = 20.0, 0.0
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg=8.0, dlat=0.25)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    dx_km, dy_km = cps.local_offsets_km(lat2d, lon2d, clat, clon)
    a_m_per_km, b_m_per_km = 0.3, -0.15
    thickness_field = a_m_per_km * dx_km + b_m_per_km * dy_km
    z900 = np.zeros_like(thickness_field)
    z600 = thickness_field

    heading_deg = 60.0
    radius_km = hc.RADIUS_KM
    speed_ms = 12.0
    heading_rad = math.radians(heading_deg)
    u_s = np.full(lat2d.shape, speed_ms * math.sin(heading_rad))
    v_s = np.full(lat2d.shape, speed_ms * math.cos(heading_rad))

    b_ref = cps.parameter_b(z900, z600, lat2d, lon2d, clat, clon, heading_deg, radius_km)
    b_grid = hc.parameter_b_grid(thickness_field, u_s, v_s, dx2d, dy_m, 1.0, radius_km, 1.0)

    assert np.isfinite(b_ref)
    assert b_grid[ci, cj] == pytest.approx(b_ref, rel=0.05)


# --- (d) hart_class truth table ----------------------------------------------


def test_hart_class_truth_table():
    # One point per code, 0-6, in order, using the boundary convention
    # hart_class documents: B frontal at > 10 (thr), symmetric at <= 10;
    # each thermal wind term warm at >= 0, cold only at strictly < 0.
    B = np.array([5.0, 5.0, 20.0, 20.0, 20.0, 5.0, 20.0])
    vtl = np.array([50.0, 50.0, 50.0, 50.0, -50.0, -50.0, -50.0])
    vtu = np.array([50.0, -50.0, 50.0, -50.0, -50.0, -50.0, 50.0])
    mask_all = np.ones_like(B, dtype=bool)

    code = hc.hart_class(B, vtl, vtu, mask_all)
    assert code.dtype == np.float32
    np.testing.assert_allclose(code, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    # Boundary: B exactly at the 10 m threshold is symmetric (<=), not
    # frontal (>) -- code 0, not 2.
    code_b_thr = hc.hart_class(np.array([10.0]), np.array([50.0]), np.array([50.0]), np.array([True]))
    assert code_b_thr[0] == 0.0

    # Boundary: VTL exactly 0.0 is warm (>= 0), not cold -- Evans and
    # Hart's completion is VTL turning *negative*, so exactly 0.0 has
    # not yet turned; code 0, not 5/6.
    code_vtl0 = hc.hart_class(np.array([5.0]), np.array([0.0]), np.array([50.0]), np.array([True]))
    assert code_vtl0[0] == 0.0

    # Boundary: VTU exactly 0.0 is also warm (>= 0), same convention --
    # code 0, not 1.
    code_vtu0 = hc.hart_class(np.array([5.0]), np.array([50.0]), np.array([0.0]), np.array([True]))
    assert code_vtu0[0] == 0.0

    # mask False -> NaN regardless of B/vtl/vtu.
    code_masked = hc.hart_class(np.array([5.0]), np.array([50.0]), np.array([50.0]), np.array([False]))
    assert np.isnan(code_masked[0])

    # NaN B -> NaN even inside the mask (the steering-flow speed below
    # MIN_STEERING_MS case).
    code_nan_b = hc.hart_class(np.array([np.nan]), np.array([50.0]), np.array([50.0]), np.array([True]))
    assert np.isnan(code_nan_b[0])


# --- (e) executeB with a 2D coriolis pseudo-field straddling the equator ---


def test_execute_b_hemisphere_as_2d_field_straddles_equator(hart_standard_orientation):
    ny, nx = 41, 21
    lat_vals = np.linspace(-10.0, 10.0, ny)
    lon_vals = np.linspace(-5.0, 5.0, nx)
    lon2d, lat2d = np.meshgrid(lon_vals, lat_vals)

    dx_row = EARTH_RADIUS_KM * np.cos(np.radians(lat_vals)) * math.radians(lon_vals[1] - lon_vals[0]) * 1000.0
    dx2d = np.repeat(dx_row[:, np.newaxis], nx, axis=1)
    dy_m = EARTH_RADIUS_KM * math.radians(lat_vals[1] - lat_vals[0]) * 1000.0

    y_km = EARTH_RADIUS_KM * np.radians(lat2d)
    z925 = np.full((ny, nx), 700.0)
    z700 = np.full((ny, nx), 3000.0) - 0.02 * y_km  # same thickness gradient everywhere

    u_level = np.full((ny, nx), 15.0)
    v_level = np.full((ny, nx), 0.0)
    psfc = np.full((ny, nx), 1013.0)

    # Positive north of the equator, negative south -- a coriolis-like
    # pseudo-field.
    coriolis = np.sign(lat2d)
    coriolis[lat2d == 0.0] = 1.0

    b = hc.executeB(
        z925, z700,
        u_level, v_level, u_level, v_level, u_level, v_level, u_level, v_level,
        psfc, coriolis, dx2d, dy_m,
    )

    north_row = int(np.argmin(np.abs(lat_vals - 8.0)))
    south_row = int(np.argmin(np.abs(lat_vals - (-8.0))))
    cj = nx // 2

    assert np.isfinite(b[north_row, cj])
    assert np.isfinite(b[south_row, cj])
    assert b[north_row, cj] > 0
    assert b[south_row, cj] < 0
    np.testing.assert_allclose(b[north_row, cj], -b[south_row, cj], rtol=1e-5)


# --- (f) executeHartClass on synthetic vortices ------------------------------


def _four_level_steering(u, v):
    """Repeat a single uniform (u, v) wind into the four (850/700/500/300
    hPa) steering-level argument pairs `executeHartClass`/`executeB` take.
    """
    return [u, v, u, v, u, v, u, v]


def test_execute_hart_class_deep_warm_core_weak_steering_no_gradient(hart_standard_orientation):
    # A vortex with no ambient thickness gradient at all (the background
    # is purely radial, see synthetic.warm_core_heights) gives parameter
    # B near zero at the exact center regardless of steering direction,
    # so a weak, merely-nonzero steering flow (comfortably above
    # MIN_STEERING_MS, so B is finite rather than NaN) should read
    # symmetric (B <= 10 m) with both thermal wind terms warm -> code 0.
    clat, clon = 20.0, 0.0
    half_width_deg, dlat = 20.0, 0.5
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    amp_warm = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    levels = tuple(amp_warm.keys())
    z_stack = synthetic.warm_core_heights(
        lat2d, lon2d, clat, clon, levels, lambda p: amp_warm[p], scale_km=150.0
    )
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}

    psfc = _ocean_psfc(lat2d.shape)
    coriolis = np.full(lat2d.shape, 1.0)
    u_weak = np.full(lat2d.shape, 5.0)
    v_weak = np.full(lat2d.shape, 0.0)

    cls = hc.executeHartClass(
        z_by_level[1000.0], z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        *_four_level_steering(u_weak, v_weak),
        psfc, coriolis, dx2d, dy_m,
    )
    assert cls.dtype == np.float32
    assert cls[ci, cj] == 0.0
    assert np.isnan(cls[0, 0])  # outside the closed-low mask


def test_execute_hart_class_thickness_gradient_and_steering_gives_frontal_deep_warm(hart_standard_orientation):
    # Same deep warm-core vortex, but with a 925-700 hPa thickness
    # gradient in the background and a steering flow along its contours
    # (the case that produces a clean, full-magnitude B -- see the
    # module docstring's "Parameter B and the joint class" section).
    # VTU is untouched by the z700 modification (it comes from
    # 500/400/300 hPa), so it stays clearly positive; only B crosses the
    # 10 m frontal line -> code 2 (frontal deep warm core), not 0.
    clat, clon = 20.0, 0.0
    half_width_deg, dlat = 20.0, 0.5
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    amp_warm = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    levels = tuple(amp_warm.keys())
    z_stack = synthetic.warm_core_heights(
        lat2d, lon2d, clat, clon, levels, lambda p: amp_warm[p], scale_km=150.0
    )
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}

    y_km = EARTH_RADIUS_KM * np.radians(lat2d - clat)
    psfc = _ocean_psfc(lat2d.shape)
    coriolis = np.full(lat2d.shape, 1.0)
    u_level = np.full(lat2d.shape, 15.0)  # due east: along the (east-west) thickness contours
    v_level = np.full(lat2d.shape, 0.0)

    def _cls_for_slope(slope):
        z700_mod = z_by_level[700.0] - slope * y_km
        return hc.executeHartClass(
            z_by_level[1000.0], z_by_level[925.0], z_by_level[850.0], z700_mod,
            z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
            *_four_level_steering(u_level, v_level),
            psfc, coriolis, dx2d, dy_m,
        )

    # Weak gradient: B stays below the 10 m frontal line -> still code 0.
    cls_weak = _cls_for_slope(0.01)
    assert cls_weak[ci, cj] == 0.0

    # Stronger gradient: B crosses 10 m, both thermal wind terms still
    # warm -> code 2 (frontal deep warm core, Evans and Hart's onset).
    cls_onset = _cls_for_slope(0.06)
    assert cls_onset[ci, cj] == 2.0


def test_execute_hart_class_tilted_cold_core_in_gradient_gives_cold(capsys, hart_standard_orientation):
    # A cold-core vortex tilted westward with height (the low-level
    # center and the upper-level center are not exactly stacked, as in a
    # real, developing extratropical cyclone), embedded in the same kind
    # of background thickness gradient and along-contour steering as the
    # previous test. Both thermal wind terms are cold at the center
    # (amplitude grows with height at every level -- see the module
    # docstring's sign derivation), so the class must land on the cold
    # side of the table (frontal cold core, 4, if B has crossed the 10 m
    # line; symmetric cold core, 5, otherwise) -- whichever the setup
    # actually produces is asserted and B is printed for visibility,
    # since only the qualitative "cold, not warm or mid-level" claim is
    # the point of this test, not a specific B value.
    clat, clon = 20.0, 0.0
    half_width_deg, dlat = 20.0, 0.5
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    amp_cold = {
        1000.0: 100.0, 925.0: 80.0, 850.0: 100.0, 700.0: 120.0, 500.0: 150.0, 400.0: 180.0, 300.0: 200.0,
    }
    levels = tuple(amp_cold.keys())
    tilt_km = 200.0  # westward shift at 300 hPa, linear in ln(p) from 0 at 1000 hPa

    def _tilted_level(p):
        frac = math.log(1000.0 / p) / math.log(1000.0 / 300.0)
        lon_shift_deg = math.degrees(
            (tilt_km * frac) / (EARTH_RADIUS_KM * math.cos(math.radians(clat)))
        )
        r_km = synthetic._haversine_km(lat2d, lon2d, clat, clon - lon_shift_deg)
        background = 100.0 + 7000.0 * np.log(1000.0 / p)
        return background - amp_cold[p] * np.exp(-(r_km / 150.0) ** 2)

    z_by_level = {p: _tilted_level(p) for p in levels}

    y_km = EARTH_RADIUS_KM * np.radians(lat2d - clat)
    slope = 0.04
    z700_mod = z_by_level[700.0] - slope * y_km

    psfc = _ocean_psfc(lat2d.shape)
    coriolis = np.full(lat2d.shape, 1.0)
    u_level = np.full(lat2d.shape, 15.0)
    v_level = np.full(lat2d.shape, 0.0)

    cls = hc.executeHartClass(
        z_by_level[1000.0], z_by_level[925.0], z_by_level[850.0], z700_mod,
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        *_four_level_steering(u_level, v_level),
        psfc, coriolis, dx2d, dy_m,
    )
    b = hc.executeB(
        z_by_level[925.0], z700_mod,
        *_four_level_steering(u_level, v_level),
        psfc, coriolis, dx2d, dy_m,
    )
    with capsys.disabled():
        print(f"\nTilted cold-core class at center: {cls[ci, cj]!r}, B = {b[ci, cj]:.1f} m")

    assert cls[ci, cj] in (4.0, 5.0)
    assert np.isnan(cls[0, 0])


def test_execute_hart_class_shallow_warm_vortex_gives_1_or_3(capsys, hart_standard_orientation):
    # Amplitude decays from a large low-level value to zero around
    # 600 hPa (the gap layer neither band claims) and turns slightly
    # negative above it, so the lower band (925/850/700 hPa) reads warm
    # (amplitude shrinking toward 600 hPa) while the upper band
    # (500/400/300 hPa) reads cold (|amplitude| growing again above
    # 600 hPa) -- the classic shallow-warm-core signature. Which of the
    # two shallow-warm codes (1 symmetric, 3 frontal) comes out depends
    # only on B, which this setup does not force either way; whichever
    # it lands on is asserted and B is printed.
    clat, clon = 20.0, 0.0
    half_width_deg, dlat = 20.0, 0.5
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)
    ci, cj = lat2d.shape[0] // 2, lat2d.shape[1] // 2

    amp_shallow = {
        1000.0: 200.0, 925.0: 150.0, 850.0: 90.0, 700.0: 20.0, 500.0: -15.0, 400.0: -25.0, 300.0: -35.0,
    }
    levels = tuple(amp_shallow.keys())
    z_stack = synthetic.warm_core_heights(
        lat2d, lon2d, clat, clon, levels, lambda p: amp_shallow[p], scale_km=150.0
    )
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}

    psfc = _ocean_psfc(lat2d.shape)
    coriolis = np.full(lat2d.shape, 1.0)
    u_weak = np.full(lat2d.shape, 5.0)
    v_weak = np.full(lat2d.shape, 0.0)

    cls = hc.executeHartClass(
        z_by_level[1000.0], z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        *_four_level_steering(u_weak, v_weak),
        psfc, coriolis, dx2d, dy_m,
    )
    b = hc.executeB(
        z_by_level[925.0], z_by_level[700.0],
        *_four_level_steering(u_weak, v_weak),
        psfc, coriolis, dx2d, dy_m,
    )
    with capsys.disabled():
        print(f"\nShallow warm-core class at center: {cls[ci, cj]!r}, B = {b[ci, cj]:.1f} m")

    assert cls[ci, cj] in (1.0, 3.0)


def test_execute_hart_class_constants_as_one_element_arrays(hart_standard_orientation):
    clat, clon = 20.0, 0.0
    half_width_deg, dlat = 20.0, 0.5
    lat2d, lon2d, dx2d, dy_m = _grid_and_dx_dy(clat, clon, half_width_deg, dlat)

    amp_warm = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    levels = tuple(amp_warm.keys())
    z_stack = synthetic.warm_core_heights(
        lat2d, lon2d, clat, clon, levels, lambda p: amp_warm[p], scale_km=150.0
    )
    z_by_level = {p: z_stack[i] for i, p in enumerate(levels)}

    psfc = _ocean_psfc(lat2d.shape)
    coriolis = np.full(lat2d.shape, 1.0)
    u_level = np.full(lat2d.shape, 15.0)
    v_level = np.full(lat2d.shape, 0.0)

    args = (
        z_by_level[1000.0], z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        *_four_level_steering(u_level, v_level),
        psfc, coriolis, dx2d, dy_m,
    )

    baseline = hc.executeHartClass(*args)
    from_arrays = hc.executeHartClass(
        *args,
        radiusKm=np.array([500.0]),
        bThresholdM=np.array([10.0]),
        layerScale=np.array([hc.HART_B_LAYER_SCALE]),
        depthM=np.array([40.0]),
        blobKm=np.array([200.0]),
        capHpa=np.array([900.0]),
    )
    np.testing.assert_allclose(from_arrays, baseline, equal_nan=True)


# --- (g) performance: 721x1440 grid ------------------------------------------


def test_execute_hart_class_performance(capsys):
    ny, nx = 721, 1440
    lat_vals = np.linspace(-90.0, 90.0, ny)
    dlon_rad = math.radians(360.0 / nx)
    dx_row = EARTH_RADIUS_KM * np.cos(np.radians(lat_vals)) * dlon_rad * 1000.0
    dx2d = np.repeat(dx_row[:, np.newaxis], nx, axis=1)
    dlat_rad = math.radians(180.0 / (ny - 1))
    dy_m = EARTH_RADIUS_KM * dlat_rad * 1000.0

    rng = np.random.default_rng(91011)
    base = rng.standard_normal((ny, nx)).astype(np.float32)

    def _smooth(a, passes=5):
        out = a.astype(np.float64)
        for _ in range(passes):
            out = (
                out
                + np.roll(out, 1, axis=0) + np.roll(out, -1, axis=0)
                + np.roll(out, 1, axis=1) + np.roll(out, -1, axis=1)
            ) / 5.0
        return out

    levels = [1000.0, 925.0, 850.0, 700.0, 500.0, 400.0, 300.0]
    zs = [_smooth(base + i) * 50.0 + (3900.0 - i * 400.0) for i in range(len(levels))]
    winds = [(_smooth(base + 10.0 + i) * 2.0 + 10.0, _smooth(base - 10.0 - i) * 2.0) for i in range(4)]
    psfc = _ocean_psfc((ny, nx))
    coriolis = np.repeat(np.sign(lat_vals)[:, np.newaxis], nx, axis=1)
    coriolis[coriolis == 0.0] = 1.0

    wind_args = []
    for u, v in winds:
        wind_args.extend([u, v])

    start = time.perf_counter()
    cls = hc.executeHartClass(*zs, *wind_args, psfc, coriolis, dx2d, dy_m)
    elapsed = time.perf_counter() - start

    with capsys.disabled():
        print(f"\nHartCPS.executeHartClass on a {ny}x{nx} grid: {elapsed:.3f} s")

    assert cls.shape == (ny, nx)
    assert elapsed < 8.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
