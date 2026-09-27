"""Tests of the circular (disk) analysis window of cps_HartCPS.py.

The module's sliding windows (the max/min behind delta_z, the sums behind
its valid-fraction guard, window_mean and closed_low_mask) default to
Hart's disk (WINDOW_SHAPE = "circle"); the square used before is kept as
shape="square". These tests check the disk against brute-force loops over
every offset inside the radius, check that the square still reproduces
the code it replaced bit for bit (a verbatim copy of that code lives
below, built on the module's unchanged primitives running_extreme_1d,
_box_sum_1d, cells_per_row and cells_y), check that the disk is the one
parameter B's half-disks use, that a closed-low footprint is round, and
time one executeBand3 call on a global 0.25 degree grid.

See conftest.py for the sys.path setup (`import cps_HartCPS`).
"""

from __future__ import annotations

import math
import time
import warnings

import numpy as np
import pytest

import cps_HartCPS as hc
import synthetic

EARTH_RADIUS_KM = 6371.0


# ---------------------------------------------------------------------------
# A small lat/lon grid whose dx varies by row, and brute-force disk loops
# ---------------------------------------------------------------------------


def _small_latlon_grid(nx, ny=15, lat0=30.0, lat1=80.0):
    """Row spacing dx = 61 km * cos(lat) from lat0 to lat1 (so the polar
    rows' chords exceed half the grid width and hit the wrap clamp), and
    dy = 55.5555 km; values chosen so no chord lands within rounding of a
    whole number of cells."""
    lat = np.linspace(lat0, lat1, ny)
    row_dx = 61000.0 * np.cos(np.radians(lat))
    dx2d = np.repeat(row_dx[:, np.newaxis], nx, axis=1)
    dy_m = 55555.5
    return row_dx, dx2d, dy_m


def _brute_disk_cells(i, c, row_dx, dy_m, radius_m, nx, ny, wrap, max_offset):
    """Every in-grid cell (r, cc) whose offset from (i, c) is inside the
    disk: row offset j = r - i with (j*dy)**2 + (k*row_dx[r])**2 <= R**2,
    k the column offset measured in the source row r's own dx, |k| at
    most `max_offset` (nx//2 for the extremes, (nx-1)//2 for the sums when
    wrapping, nx-1 otherwise). Wrapped columns are taken modulo nx; rows
    beyond the grid are skipped (never wrapped over the pole)."""
    cells = []
    j_reach = int(radius_m // dy_m) + 1
    for j in range(-j_reach, j_reach + 1):
        r = i + j
        if r < 0 or r >= ny:
            continue
        for k in range(-max_offset, max_offset + 1):
            if (j * dy_m) ** 2 + (k * row_dx[r]) ** 2 > radius_m ** 2:
                continue
            cc = c + k
            if wrap:
                cc %= nx
            elif cc < 0 or cc >= nx:
                continue
            cells.append((r, cc))
    return cells


@pytest.mark.parametrize("nx", [24, 25])
@pytest.mark.parametrize("wrap", [False, True])
def test_disk_extremes_match_brute_force(nx, wrap):
    ny = 15
    row_dx, dx2d, dy_m = _small_latlon_grid(nx, ny)
    radius_km = 400.0
    rng = np.random.default_rng(20260927 + nx)
    field = rng.standard_normal((ny, nx))
    field[rng.random((ny, nx)) < 0.15] = np.nan
    field[2:5, 3:9] = np.nan  # a block, so some disks near it are mostly or all NaN

    geometry = hc.window_geometry(radius_km, dx2d, dy_m, ny, nx, global_lon=wrap)
    got_max = hc.window_extreme_2d(field, kind="max", geometry=geometry)
    got_min = hc.window_extreme_2d(field, kind="min", geometry=geometry)
    # The default shape is the circle; asking for it explicitly is the same.
    np.testing.assert_array_equal(got_max, hc.window_extreme_2d(field, kind="max", shape="circle", geometry=geometry))

    max_offset = nx // 2 if wrap else nx - 1
    for i in range(ny):
        for c in range(nx):
            vals = np.array([field[r, cc] for r, cc in
                             _brute_disk_cells(i, c, row_dx, dy_m, radius_km * 1000.0, nx, ny, wrap, max_offset)])
            finite = vals[np.isfinite(vals)]
            if finite.size:
                assert got_max[i, c] == finite.max(), (i, c)
                assert got_min[i, c] == finite.min(), (i, c)
            else:
                assert np.isnan(got_max[i, c]) and np.isnan(got_min[i, c]), (i, c)


@pytest.mark.parametrize("nx", [24, 25])
@pytest.mark.parametrize("wrap", [False, True])
def test_disk_sums_and_counts_match_brute_force(nx, wrap):
    ny = 15
    row_dx, dx2d, dy_m = _small_latlon_grid(nx, ny)
    radius_km = 400.0
    rng = np.random.default_rng(20260928 + nx)
    field = rng.standard_normal((ny, nx)) * 10.0 + 1000.0
    field[rng.random((ny, nx)) < 0.15] = np.nan

    geometry = hc.window_geometry(radius_km, dx2d, dy_m, ny, nx, global_lon=wrap)
    got_sum, got_cnt = hc.window_sum_2d(field, geometry=geometry)

    max_offset = (nx - 1) // 2 if wrap else nx - 1
    for i in range(ny):
        for c in range(nx):
            vals = np.array([field[r, cc] for r, cc in
                             _brute_disk_cells(i, c, row_dx, dy_m, radius_km * 1000.0, nx, ny, wrap, max_offset)])
            finite = vals[np.isfinite(vals)]
            assert got_cnt[i, c] == finite.size, (i, c)
            assert got_sum[i, c] == pytest.approx(float(finite.sum()), rel=1e-12, abs=1e-9), (i, c)

    # window_mean is the sum over the count.
    mean = hc.window_mean(field, dx2d, dy_m, radius_km, global_lon=wrap)
    np.testing.assert_allclose(mean, got_sum / got_cnt, rtol=1e-15)


def test_disk_is_the_one_half_disk_means_uses():
    """On a uniform grid with no missing data, the disk mean (window_mean)
    at an interior point is the average of half_disk_means' north and
    south half-disk means: the two halves carry equal weight there (the
    center row split half and half), so this holds only if the disk the
    windows use and the disk parameter B uses are the same cells."""
    rng = np.random.default_rng(5)
    ny, nx = 61, 71
    field = rng.standard_normal((ny, nx))
    spacing_m = 25000.0
    mean = hc.window_mean(field, spacing_m, spacing_m, hc.RADIUS_KM)
    north, south, east, west = hc.half_disk_means(field, spacing_m, spacing_m, hc.RADIUS_KM, mode=0)
    interior = (slice(21, 40), slice(21, 50))
    np.testing.assert_allclose(mean[interior], 0.5 * (north + south)[interior], rtol=1e-12)
    np.testing.assert_allclose(mean[interior], 0.5 * (east + west)[interior], rtol=1e-12)


def test_window_shape_validation_and_module_default(monkeypatch):
    field = np.arange(30.0).reshape(5, 6)
    half_x = np.full(5, 2)
    with pytest.raises(ValueError):
        hc.window_extreme_2d(field, half_x, 2, "max", shape="hexagon")
    with pytest.raises(ValueError):
        hc.window_extreme_2d(field, kind="max")  # neither cell counts nor a geometry
    assert hc.WINDOW_SHAPE == "circle"
    circle = hc.window_extreme_2d(field, half_x, 2, "max")
    square = hc.window_extreme_2d(field, half_x, 2, "max", shape="square")
    assert not np.array_equal(circle, square)
    # shape=None reads the module constant at call time.
    monkeypatch.setattr(hc, "WINDOW_SHAPE", "square")
    np.testing.assert_array_equal(hc.window_extreme_2d(field, half_x, 2, "max"), square)


# ---------------------------------------------------------------------------
# shape="square" reproduces the code it replaced, bit for bit
# ---------------------------------------------------------------------------
# Verbatim copies of the square-window functions as they were before the
# disk became the default (only renamed, and pointed at the module's own
# unchanged primitives).


def _old_window_extreme_2d(field, half_x_cells_per_row, half_y_cells, kind, wrap_x=False):
    field = np.asarray(field, dtype=float)
    ny, nx = field.shape
    half_x = np.asarray(half_x_cells_per_row).astype(int)
    max_half_x = max(nx - 1, 0)
    half_x = np.clip(half_x, 0, max_half_x)
    max_half_y = max(ny - 1, 0)
    half_y = int(np.clip(int(half_y_cells), 0, max_half_y))
    out_x = np.empty_like(field)
    if wrap_x and nx > 1 and half_x.size:
        pad = min(nx // 2, int(half_x.max()))
        if pad > 0:
            padded_field = np.concatenate([field[:, nx - pad :], field, field[:, :pad]], axis=1)
        else:
            padded_field = field
        for hw in np.unique(half_x):
            hw_eff = min(int(hw), pad)
            rows = np.nonzero(half_x == hw)[0]
            res = hc.running_extreme_1d(padded_field[rows, :], hw_eff, axis=1, kind=kind)
            if pad > 0:
                res = res[:, pad : pad + nx]
            out_x[rows, :] = res
    else:
        for hw in np.unique(half_x):
            rows = np.nonzero(half_x == hw)[0]
            out_x[rows, :] = hc.running_extreme_1d(field[rows, :], int(hw), axis=1, kind=kind)
    return hc.running_extreme_1d(out_x, half_y, axis=0, kind=kind)


def _old_window_sum_2d(field, half_x_cells_per_row, half_y_cells, wrap_x=False):
    field = np.asarray(field, dtype=float)
    ny, nx = field.shape
    half_x = np.asarray(half_x_cells_per_row).astype(int)
    max_half_x = max(nx - 1, 0)
    half_x = np.clip(half_x, 0, max_half_x)
    max_half_y = max(ny - 1, 0)
    half_y = int(np.clip(int(half_y_cells), 0, max_half_y))
    valid = np.isfinite(field)
    values = np.where(valid, field, 0.0)
    counts = valid.astype(float)
    sum_x = np.empty_like(field)
    cnt_x = np.empty_like(field)
    if wrap_x and nx > 1 and half_x.size:
        pad = min(nx // 2, int(half_x.max()))
        if pad > 0:
            values_p = np.concatenate([values[:, nx - pad :], values, values[:, :pad]], axis=1)
            counts_p = np.concatenate([counts[:, nx - pad :], counts, counts[:, :pad]], axis=1)
        else:
            values_p, counts_p = values, counts
        for hw in np.unique(half_x):
            hw_eff = min(int(hw), pad)
            rows = np.nonzero(half_x == hw)[0]
            s, c = hc._box_sum_1d(values_p[rows, :], counts_p[rows, :], hw_eff, axis=1)
            if pad > 0:
                s = s[:, pad : pad + nx]
                c = c[:, pad : pad + nx]
            sum_x[rows, :], cnt_x[rows, :] = s, c
    else:
        for hw in np.unique(half_x):
            rows = np.nonzero(half_x == hw)[0]
            sum_x[rows, :], cnt_x[rows, :] = hc._box_sum_1d(values[rows, :], counts[rows, :], int(hw), axis=1)
    return hc._box_sum_1d(sum_x, cnt_x, half_y, axis=0)


def _old_delta_z(z, dx, dy, radius_km, global_lon=None):
    z_arr = np.asarray(z, dtype=float)
    ny, nx = z_arr.shape
    bad = hc._missing_mask(z_arr)
    z_clean = np.where(bad, np.nan, z_arr)
    half_x = hc.cells_per_row(radius_km, dx, ny, nx)
    half_y = hc.cells_y(radius_km, dy)
    dy_m = float(np.nanmean(np.asarray(dy, dtype=float)))
    wrap = hc.is_global_lon(nx, dy_m) if global_lon is None else bool(global_lon)
    z_max = _old_window_extreme_2d(z_clean, half_x, half_y, "max", wrap_x=wrap)
    z_min = _old_window_extreme_2d(z_clean, half_x, half_y, "min", wrap_x=wrap)
    dz = z_max - z_min
    valid_indicator = np.where(bad, 0.0, 1.0)
    valid_count, total_count = _old_window_sum_2d(valid_indicator, half_x, half_y, wrap_x=wrap)
    with np.errstate(invalid="ignore", divide="ignore"):
        valid_fraction = np.where(total_count > 0, valid_count / total_count, 0.0)
    dz = np.where(valid_fraction < hc.MIN_VALID_FRACTION, np.nan, dz)
    return np.where(bad, np.nan, dz)


def _old_window_mean(field, dx, dy, radius_km, global_lon=None):
    field = np.asarray(field, dtype=float)
    ny, nx = field.shape
    half_x = hc.cells_per_row(radius_km, dx, ny, nx)
    half_y = hc.cells_y(radius_km, dy)
    dy_m = float(np.nanmean(np.asarray(dy, dtype=float)))
    wrap = hc.is_global_lon(nx, dy_m) if global_lon is None else bool(global_lon)
    total, count = _old_window_sum_2d(field, half_x, half_y, wrap_x=wrap)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / count, np.nan)
    return mean


def _old_closed_low_mask(pmsl, dx, dy, min_radius_km=hc.MIN_RADIUS_KM, ring_radius_km=hc.RADIUS_KM,
                         depth_hpa=hc.DEFAULT_DEPTH_HPA, blob_radius_km=hc.DEFAULT_BLOB_RADIUS_KM,
                         center_tol_hpa=hc.DEFAULT_CENTER_TOL_HPA, global_lon=None):
    p_arr = hc.mslp_hpa(pmsl)
    ny, nx = p_arr.shape
    bad = hc._missing_mask(p_arr)
    p_clean = np.where(bad, np.nan, p_arr)
    dy_m = float(np.nanmean(np.asarray(dy, dtype=float)))
    wrap = hc.is_global_lon(nx, dy_m) if global_lon is None else bool(global_lon)
    half_x_min = hc.cells_per_row(min_radius_km, dx, ny, nx)
    half_y_min = hc.cells_y(min_radius_km, dy)
    local_min = _old_window_extreme_2d(p_clean, half_x_min, half_y_min, "min", wrap_x=wrap)
    with np.errstate(invalid="ignore"):
        candidate = (p_clean - local_min) <= float(center_tol_hpa)
    half_x_ring = hc.cells_per_row(ring_radius_km, dx, ny, nx)
    half_y_ring = hc.cells_y(ring_radius_km, dy)
    sum_outer, count_outer = _old_window_sum_2d(p_clean, half_x_ring, half_y_ring, wrap_x=wrap)
    sum_inner, count_inner = _old_window_sum_2d(p_clean, half_x_min, half_y_min, wrap_x=wrap)
    ring_sum = sum_outer - sum_inner
    ring_count = count_outer - count_inner
    with np.errstate(invalid="ignore", divide="ignore"):
        ring_mean = np.where(ring_count > 0, ring_sum / ring_count, np.nan)
        depth_ok = (ring_mean - p_clean) >= float(depth_hpa)
    valid = ~bad & np.isfinite(local_min) & np.isfinite(ring_mean)
    raw = (candidate & depth_ok & valid).astype(float)
    half_x_blob = hc.cells_per_row(blob_radius_km, dx, ny, nx)
    half_y_blob = hc.cells_y(blob_radius_km, dy)
    dilated = _old_window_extreme_2d(raw, half_x_blob, half_y_blob, "max", wrap_x=wrap)
    return dilated > 0.5


def _global_grid(dlat=1.0):
    lat = np.linspace(-90.0, 90.0, int(round(180.0 / dlat)) + 1)
    nx = int(round(360.0 / dlat))
    dx2d = np.repeat((EARTH_RADIUS_KM * 1000.0 * np.cos(np.radians(lat)) * np.radians(dlat))[:, np.newaxis], nx, axis=1)
    dy_m = EARTH_RADIUS_KM * 1000.0 * np.radians(dlat)
    return lat, dx2d, dy_m


def _smooth(a, passes=4):
    out = np.asarray(a, dtype=float)
    for _ in range(passes):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0) + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
    return out


def test_square_reproduces_previous_window_functions_bit_for_bit():
    rng = np.random.default_rng(424242)
    # A regional grid (varying dx) and a global 1 degree grid (wrapping).
    ny, nx = 40, 55
    lat = np.linspace(35.0, 70.0, ny)
    dx_regional = np.repeat((27800.0 * np.cos(np.radians(lat)))[:, np.newaxis], nx, axis=1)
    dy_regional = 27800.0
    lat_g, dx_global, dy_global = _global_grid(1.0)

    for dx, dy in ((dx_regional, dy_regional), (dx_global, dy_global)):
        shape2d = dx.shape
        field = _smooth(rng.standard_normal(shape2d)) * 60.0 + 5000.0
        field[rng.random(shape2d) < 0.05] = np.nan
        field[5:12, 10:30] = np.nan
        gny, gnx = shape2d
        for radius_km in (200.0, 300.0, 500.0):
            half_x = hc.cells_per_row(radius_km, dx, gny, gnx)
            half_y = hc.cells_y(radius_km, dy)
            for wrap in (False, True):
                for kind in ("max", "min"):
                    np.testing.assert_array_equal(
                        hc.window_extreme_2d(field, half_x, half_y, kind, wrap_x=wrap, shape="square"),
                        _old_window_extreme_2d(field, half_x, half_y, kind, wrap_x=wrap),
                    )
                    geometry = hc.window_geometry(radius_km, dx, dy, gny, gnx, global_lon=wrap)
                    np.testing.assert_array_equal(
                        hc.window_extreme_2d(field, kind=kind, shape="square", geometry=geometry),
                        _old_window_extreme_2d(field, half_x, half_y, kind, wrap_x=wrap),
                    )
                got = hc.window_sum_2d(field, half_x, half_y, wrap_x=wrap, shape="square")
                old = _old_window_sum_2d(field, half_x, half_y, wrap_x=wrap)
                np.testing.assert_array_equal(got[0], old[0])
                np.testing.assert_array_equal(got[1], old[1])
            np.testing.assert_array_equal(hc.delta_z(field, dx, dy, radius_km, shape="square"),
                                          _old_delta_z(field, dx, dy, radius_km))
            np.testing.assert_array_equal(hc.window_mean(field, dx, dy, radius_km, shape="square"),
                                          _old_window_mean(field, dx, dy, radius_km))

        pmsl = 1012.0 + _smooth(rng.standard_normal(shape2d), 8) * 40.0
        np.testing.assert_array_equal(hc.closed_low_mask(pmsl, dx, dy, shape="square"),
                                      _old_closed_low_mask(pmsl, dx, dy))


def test_square_reproduces_previous_products_bit_for_bit(monkeypatch):
    """With WINDOW_SHAPE = "square" the AWIPS entry points (whose argument
    lists are unchanged) give exactly what they gave before the disk,
    rebuilt here from the verbatim old window functions."""
    monkeypatch.setattr(hc, "ORIENTATION_MODE", 0)
    rng = np.random.default_rng(97)
    lat, dx2d, dy_m = _global_grid(1.0)
    shape2d = dx2d.shape
    base = rng.standard_normal(shape2d)
    levels = [925.0, 850.0, 700.0, 500.0, 400.0, 300.0]
    zs = [_smooth(base + 0.3 * i, 6) * 60.0 + (800.0 + 1500.0 * i) for i in range(6)]
    pmsl = (1012.0 + _smooth(base, 6) * 25.0) * 100.0  # Pa
    winds = [(_smooth(rng.standard_normal(shape2d), 6) * 8.0 + 6.0, _smooth(rng.standard_normal(shape2d), 6) * 8.0)
             for _ in range(4)]
    wind_args = [w for pair in winds for w in pair]
    psfc = np.full(shape2d, 1013.0)
    psfc[20:40, 100:140] = 700.0  # terrain, so the valid-fraction guard is exercised
    coriolis = np.repeat(np.where(lat >= 0.0, 1.0, -1.0)[:, np.newaxis], shape2d[1], axis=1)
    radius_km, cap = hc.RADIUS_KM, hc.BELOW_GROUND_CAP_HPA

    psfc_hpa = hc.surface_pressure_hpa(psfc)
    masked = [hc.mask_below_ground(z, psfc_hpa, p, cap) for z, p in zip(zs, levels)]
    vtl_old = hc.band_slope([_old_delta_z(z, dx2d, dy_m, radius_km) for z in masked[:3]], levels[:3])
    vtu_old = hc.band_slope([_old_delta_z(z, dx2d, dy_m, radius_km) for z in masked[3:]], levels[3:])
    u_s, v_s = hc.steering([w[0] for w in winds], [w[1] for w in winds])
    u_s, v_s = _old_window_mean(u_s, dx2d, dy_m, radius_km), _old_window_mean(v_s, dx2d, dy_m, radius_km)
    thickness = masked[2] - masked[0]
    b_old = hc.parameter_b_grid(thickness, u_s, v_s, dx2d, dy_m, coriolis, radius_km, hc.HART_B_LAYER_SCALE)
    mask_old = _old_closed_low_mask(hc.mslp_hpa(pmsl), dx2d, dy_m, hc.MIN_RADIUS_KM, radius_km,
                                    hc.DEFAULT_DEPTH_HPA, hc.DEFAULT_BLOB_RADIUS_KM)
    cls_old = hc.hart_class(b_old, vtl_old, vtu_old, mask_old, hc.B_THRESHOLD_M)
    assert mask_old.any()

    monkeypatch.setattr(hc, "WINDOW_SHAPE", "square")
    band3 = hc.executeBand3(*zs[:3], psfc, dx2d, dy_m, radius_km, *levels[:3])
    np.testing.assert_array_equal(band3, vtl_old.astype(np.float32))
    b_new = hc.executeB(zs[0], zs[2], *wind_args, psfc, coriolis, dx2d, dy_m)
    np.testing.assert_array_equal(b_new, b_old.astype(np.float32))
    cls_new = hc.executeHartClass(pmsl, *zs, *wind_args, psfc, coriolis, dx2d, dy_m)
    np.testing.assert_array_equal(cls_new, cls_old)

    # And the circle (the default) does differ from it.
    monkeypatch.setattr(hc, "WINDOW_SHAPE", "circle")
    assert not np.array_equal(hc.executeBand3(*zs[:3], psfc, dx2d, dy_m, radius_km, *levels[:3]), band3)


# ---------------------------------------------------------------------------
# A round closed-low footprint
# ---------------------------------------------------------------------------


def _ray_extent_km(mask, ci, cj, di, dj, dx_m, dy_m):
    """Distance (km) from (ci, cj) to the last True cell of the unbroken run
    of True cells along the grid ray (di, dj)."""
    n = 0
    while True:
        i, j = ci + (n + 1) * di, cj + (n + 1) * dj
        if not (0 <= i < mask.shape[0] and 0 <= j < mask.shape[1]) or not mask[i, j]:
            break
        n += 1
    return n * math.hypot(di * dy_m, dj * dx_m) / 1000.0


def test_closed_low_footprint_is_round():
    """An isolated, round Gaussian MSLP low on a 0.25 degree grid: the
    footprint closed_low_mask paints (its detections dilated by a disk of
    DEFAULT_BLOB_RADIUS_KM) reaches as far along the grid diagonals as
    along the axes, within one cell; the square it replaced reached about
    1.3 times as far along the diagonals."""
    clat, clon = 20.0, 0.0
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=8.0, dlat=0.25, dlon=0.25)
    dx_row = EARTH_RADIUS_KM * np.cos(np.radians(lat2d[:, 0])) * np.radians(0.25) * 1000.0
    dx2d = np.repeat(dx_row[:, np.newaxis], lat2d.shape[1], axis=1)
    dy_m = EARTH_RADIUS_KM * np.radians(0.25) * 1000.0
    r_km = synthetic._haversine_km(lat2d, lon2d, clat, clon)
    pmsl = 1012.0 - 7.5 * np.exp(-(r_km / 150.0) ** 2)
    ci, cj = np.unravel_index(np.argmin(pmsl), pmsl.shape)
    dx_m = dx_row[ci]
    cell_km = math.hypot(dx_m, dy_m) / 1000.0

    rays = [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]
    extents = {}
    for shape in ("circle", "square"):
        mask = hc.closed_low_mask(pmsl, dx2d, dy_m, shape=shape)
        assert mask[ci, cj]
        extents[shape] = [_ray_extent_km(mask, ci, cj, di, dj, dx_m, dy_m) for di, dj in rays]

    circle = extents["circle"]
    assert max(circle) - min(circle) <= cell_km, circle
    # About the blob radius, give or take the candidate's own extent.
    assert hc.DEFAULT_BLOB_RADIUS_KM - cell_km <= min(circle) and max(circle) <= hc.DEFAULT_BLOB_RADIUS_KM + 2 * cell_km
    # Measured: 209-222 km along the axes, 229 km along the diagonals.
    # The square fails the same test by almost two cells (its diagonals
    # measured 305 km against 222-235 km along the axes).
    square = extents["square"]
    assert min(square[4:]) - max(square[:4]) > 1.5 * cell_km, square


# ---------------------------------------------------------------------------
# Timing on a global 0.25 degree grid
# ---------------------------------------------------------------------------


def test_execute_band3_global_quarter_degree_timing(capsys):
    """One executeBand3 call (three levels, each a disk max, a disk min and,
    where terrain masks cells, the valid-fraction disk sum) on the global
    721 x 1440 grid. The bound is generous on purpose (10 s); the measured
    time is printed."""
    lat, dx2d, dy_m = _global_grid(0.25)
    ny, nx = dx2d.shape
    assert hc.is_global_lon(nx, dy_m)
    rng = np.random.default_rng(31337)
    base = rng.standard_normal((ny, nx))
    zs = [_smooth(base + i, 5) * 50.0 + (800.0 + 700.0 * i) for i in range(3)]
    psfc = np.full((ny, nx), 101300.0)
    psfc[40:120, 100:500] = 70000.0  # an ice sheet: below ground at all three levels
    psfc[250:290, 300:420] = 60000.0

    start = time.perf_counter()
    vtl = hc.executeBand3(*zs, psfc, dx2d, dy_m, 500.0, 925.0, 850.0, 700.0)
    elapsed = time.perf_counter() - start
    with capsys.disabled():
        print(f"\nHartCPS.executeBand3 (circle) on a {ny}x{nx} global grid: {elapsed:.3f} s")
    assert vtl.shape == (ny, nx)
    assert np.isnan(vtl[80, 300]) and np.isfinite(vtl[400, 900])
    assert elapsed < 10.0
