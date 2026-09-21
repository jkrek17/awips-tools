"""Analytic verification of cps.hart.

Every expected value here is derived independently of cps.hart's own
code (closed-form geometry, or a second haversine/least-squares
computation in synthetic.py / this file), per web/CPS/PLAN.md section 8.
Run with:  python3 -m pytest cyclone_phase_space/tests/cps -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import cps
import synthetic

R_KM = 6371.0
CIRCLE_KM = cps.RADIUS_KM  # 500.0


# ---------------------------------------------------------------------------
# (a) Mask geometry: dateline invariance and circle area
# ---------------------------------------------------------------------------


def test_mask_count_invariant_to_dateline_and_lon_convention():
    lat0, lon0 = make_lat_lon = (20.0, 0.0)
    lat_a, lon_a = synthetic.make_grid(*make_lat_lon, half_width_deg=8, dlat=0.25, dlon=0.25)
    count_a = int(cps.radial_mask(lat_a, lon_a, lat0, lon0, CIRCLE_KM).sum())

    # A grid centered right on the antimeridian genuinely straddles it:
    # make_grid wraps into -180..180, so half its points come back negative.
    clat, clon = 20.0, 179.75
    lat_d, lon_d = synthetic.make_grid(clat, clon, half_width_deg=8, dlat=0.25, dlon=0.25)
    assert (lon_d < 0).any() and (lon_d > 0).any(), "grid should straddle the antimeridian"
    count_d = int(cps.radial_mask(lat_d, lon_d, clat, clon, CIRCLE_KM).sum())
    assert count_d == count_a

    # The same physical points, re-expressed in 0..360 instead of -180..180,
    # must give the identical count -- the convention must not matter.
    lon_d_360 = np.where(lon_d < 0, lon_d + 360.0, lon_d)
    count_360 = int(cps.radial_mask(lat_d, lon_d_360, clat, clon, CIRCLE_KM).sum())
    assert count_360 == count_a


def test_mask_area_matches_circle_area():
    clat, clon = 20.0, 0.0
    dlat = dlon = 0.1
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=8, dlat=dlat, dlon=dlon)
    mask = cps.radial_mask(lat2d, lon2d, clat, clon, CIRCLE_KM)

    cell_km2 = (R_KM * math.radians(dlat)) * (R_KM * math.radians(dlon) * np.cos(np.radians(lat2d)))
    area_km2 = float(cell_km2[mask].sum())

    expected = math.pi * CIRCLE_KM ** 2
    assert abs(area_km2 - expected) / expected < 0.03


# ---------------------------------------------------------------------------
# (b) Symmetric warm core
# ---------------------------------------------------------------------------

ALL_LEVELS = (900, 850, 800, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300)
A0 = 300.0


def _warm_amp(p: float) -> float:
    return A0 * (math.log(p / 300.0) / math.log(900.0 / 300.0)) ** 2


def _band_slope_reference(levels, amps) -> float:
    x = np.log(np.asarray(levels, dtype=float))
    y = np.asarray(amps, dtype=float)
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def _symmetric_warm_core_grid(clat=20.0, clon=0.0):
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=8, dlat=0.25, dlon=0.25)
    z_stack = synthetic.warm_core_heights(lat2d, lon2d, clat, clon, ALL_LEVELS, _warm_amp, scale_km=150.0)
    return lat2d, lon2d, z_stack


def test_symmetric_warm_core_thermal_wind():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, z_stack = _symmetric_warm_core_grid(clat, clon)

    result = cps.thermal_wind(ALL_LEVELS, z_stack, lat2d, lon2d, clat, clon)

    vtl_expected = _band_slope_reference(cps.LOWER_LEVELS, [_warm_amp(p) for p in cps.LOWER_LEVELS])
    vtu_expected = _band_slope_reference(cps.UPPER_LEVELS, [_warm_amp(p) for p in cps.UPPER_LEVELS])

    assert result["VTL"] == pytest.approx(vtl_expected, rel=0.01)
    assert result["VTU"] == pytest.approx(vtu_expected, rel=0.01)
    assert result["VTL"] > result["VTU"] > 0


def test_symmetric_warm_core_b_near_zero_any_heading():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, z_stack = _symmetric_warm_core_grid(clat, clon)
    z900 = z_stack[ALL_LEVELS.index(900)]
    z600 = z_stack[ALL_LEVELS.index(600)]

    for heading in (0.0, 90.0, 225.0):
        b_value = cps.parameter_b(z900, z600, lat2d, lon2d, clat, clon, heading)
        assert abs(b_value) < 1.0


# ---------------------------------------------------------------------------
# (c) Asymmetry: a known left/right thickness tilt
# ---------------------------------------------------------------------------

G_TILT = 0.05  # m/km


def _tilted_thickness(clat, clon):
    # A finer grid than the other tests: parameter_b's right/left split is a
    # step function right at the motion line, so the discrete mask's area
    # converges to the continuum half-disk centroid (4R/(3*pi)) slowly with
    # a coarse grid. 0.1 deg keeps the discretization error under ~0.2%.
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=6, dlat=0.1, dlon=0.1)
    dlon_deg = ((lon2d - clon + 180.0) % 360.0) - 180.0
    dx_km = R_KM * math.cos(math.radians(clat)) * np.radians(dlon_deg)
    z900 = np.zeros_like(lat2d)
    z600 = G_TILT * dx_km
    return lat2d, lon2d, z900, z600


def _expected_tilt_b(hemisphere_sign: float, heading_sign: float) -> float:
    # Centroid of a half-disk of radius R, measured from the diameter, is
    # 4R/(3*pi); the two half-disk means are +/- that value, so their
    # difference is 8R/(3*pi). heading_sign flips which half is "right".
    centroid_term = 8.0 * CIRCLE_KM / (3.0 * math.pi)
    return hemisphere_sign * heading_sign * G_TILT * centroid_term


def test_tilt_asymmetry_heading_north():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, z900, z600 = _tilted_thickness(clat, clon)
    b_value = cps.parameter_b(z900, z600, lat2d, lon2d, clat, clon, heading_deg=0.0)
    expected = _expected_tilt_b(hemisphere_sign=1.0, heading_sign=1.0)
    assert b_value == pytest.approx(expected, rel=0.03)


def test_tilt_asymmetry_heading_south_flips_sign():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, z900, z600 = _tilted_thickness(clat, clon)
    b_north = cps.parameter_b(z900, z600, lat2d, lon2d, clat, clon, heading_deg=0.0)
    b_south = cps.parameter_b(z900, z600, lat2d, lon2d, clat, clon, heading_deg=180.0)
    assert b_south == pytest.approx(-b_north, rel=0.03)


def test_tilt_asymmetry_southern_hemisphere_flips_sign():
    clat, clon = -30.0, 0.0
    lat2d, lon2d, z900, z600 = _tilted_thickness(clat, clon)
    b_value = cps.parameter_b(z900, z600, lat2d, lon2d, clat, clon, heading_deg=0.0)
    expected = _expected_tilt_b(hemisphere_sign=-1.0, heading_sign=1.0)
    assert b_value == pytest.approx(expected, rel=0.03)


# ---------------------------------------------------------------------------
# (d) Cold core: thermal wind sign flips
# ---------------------------------------------------------------------------


def _cold_amp(p: float) -> float:
    return A0 * (1.0 - math.log(p / 300.0) / math.log(3.0))


def test_cold_core_gives_negative_thermal_wind():
    clat, clon = 20.0, 0.0
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=8, dlat=0.25, dlon=0.25)
    z_stack = synthetic.warm_core_heights(lat2d, lon2d, clat, clon, ALL_LEVELS, _cold_amp, scale_km=150.0)

    result = cps.thermal_wind(ALL_LEVELS, z_stack, lat2d, lon2d, clat, clon)
    assert result["VTL"] < 0
    assert result["VTU"] < 0


# ---------------------------------------------------------------------------
# (e) track_motion
# ---------------------------------------------------------------------------


def test_track_motion_due_north():
    lats = np.array([0.0, 1.0, 2.0])
    lons = np.array([0.0, 0.0, 0.0])
    times = np.array([0.0, 21600.0, 43200.0])

    headings, speeds = cps.track_motion(lats, lons, times)
    assert np.all(np.abs(headings - 0.0) < 0.5)

    expected_speed = 111.2 * 1000.0 / 21600.0
    assert speeds == pytest.approx(expected_speed, rel=0.01)


def test_track_motion_due_east_at_equator():
    lats = np.array([0.0, 0.0, 0.0])
    lons = np.array([0.0, 1.0, 2.0])
    times = np.array([0.0, 21600.0, 43200.0])

    headings, _speeds = cps.track_motion(lats, lons, times)
    assert np.all(np.abs(headings - 90.0) < 0.5)


def test_track_motion_dateline_crossing_is_eastward():
    lats = np.array([0.0, 0.0])
    lons = np.array([179.5, -179.5])
    times = np.array([0.0, 21600.0])

    headings, _speeds = cps.track_motion(lats, lons, times)
    assert np.all(np.abs(headings - 90.0) < 0.5)
    assert np.all(np.abs(headings - 270.0) > 100.0)


def test_track_motion_single_point():
    headings, speeds = cps.track_motion([10.0], [20.0], [0.0])
    assert math.isnan(headings[0])
    assert speeds[0] == 0.0


# ---------------------------------------------------------------------------
# (f) gale_radius_km against an analytic modified-Rankine vortex
# ---------------------------------------------------------------------------


def test_gale_radius_matches_rankine_r34():
    clat, clon = 20.0, 0.0
    vmax, rmax, decay = 40.0, 40.0, 0.5
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=5, dlat=0.1, dlon=0.1)
    u, v = synthetic.rankine_wind(lat2d, lon2d, clat, clon, vmax, rmax, decay)

    result_km = cps.gale_radius_km(u, v, lat2d, lon2d, clat, clon)

    expected_km = rmax * (vmax / cps.GALE_MS) ** 2
    assert result_km == pytest.approx(expected_km, rel=0.03)


# ---------------------------------------------------------------------------
# (g) refine_center
# ---------------------------------------------------------------------------


def test_refine_center_finds_the_true_minimum():
    clat0, clon0 = 20.0, 0.0
    dlat = dlon = 0.1
    grid_km = R_KM * math.radians(dlat)  # ~11.1 km

    true_shift_km = 40.0
    dlon_deg = math.degrees(true_shift_km / (R_KM * math.cos(math.radians(clat0))))
    clat_true, clon_true = clat0, clon0 + dlon_deg

    lat2d, lon2d = synthetic.make_grid(clat0, clon0, half_width_deg=3, dlat=dlat, dlon=dlon)
    r_km = synthetic._haversine_km(lat2d, lon2d, clat_true, clon_true)
    mslp = 1010.0 - 30.0 * np.exp(-(r_km / 100.0) ** 2)

    new_lat, new_lon, shift_km = cps.refine_center(mslp, lat2d, lon2d, clat0, clon0, max_shift_km=100.0)

    dist_to_true = float(cps.great_circle_km(new_lat, new_lon, clat_true, clon_true))
    assert dist_to_true <= grid_km * 1.5
    assert abs(shift_km - true_shift_km) <= 0.5 * grid_km

    # Capped search: shift must not exceed the cap by more than one grid cell.
    _, _, capped_shift_km = cps.refine_center(mslp, lat2d, lon2d, clat0, clon0, max_shift_km=20.0)
    assert capped_shift_km <= 20.0 + grid_km


def test_refine_center_empty_search_returns_input():
    lat2d, lon2d = synthetic.make_grid(20.0, 0.0, half_width_deg=1, dlat=0.5, dlon=0.5)
    mslp = np.full(lat2d.shape, 1000.0)
    # A center far outside the grid means the search circle has no points.
    new_lat, new_lon, shift_km = cps.refine_center(mslp, lat2d, lon2d, 60.0, 60.0, max_shift_km=50.0)
    assert new_lat == 60.0
    assert new_lon == 60.0
    assert shift_km == 0.0


# ---------------------------------------------------------------------------
# (h) compute_point
# ---------------------------------------------------------------------------


def test_compute_point_matches_individual_functions():
    clat, clon = 20.0, 0.0
    lat2d, lon2d, z_stack = _symmetric_warm_core_grid(clat, clon)
    r_km = synthetic._haversine_km(lat2d, lon2d, clat, clon)
    mslp = 1000.0 - 30.0 * np.exp(-(r_km / 100.0) ** 2)
    u925, v925 = synthetic.rankine_wind(lat2d, lon2d, clat, clon, vmax_ms=20.0, rmax_km=50.0)

    result = cps.compute_point(
        ALL_LEVELS, z_stack, lat2d, lon2d, clat, clon, heading_deg=45.0,
        mslp=mslp, u925=u925, v925=v925,
    )

    rc_lat, rc_lon = result.center_lat, result.center_lon
    z900 = z_stack[ALL_LEVELS.index(900)]
    z600 = z_stack[ALL_LEVELS.index(600)]
    b_expected = cps.parameter_b(z900, z600, lat2d, lon2d, rc_lat, rc_lon, 45.0)
    tw_expected = cps.thermal_wind(ALL_LEVELS, z_stack, lat2d, lon2d, rc_lat, rc_lon)
    gale_expected = cps.gale_radius_km(u925, v925, lat2d, lon2d, rc_lat, rc_lon)

    assert result.B == pytest.approx(b_expected)
    assert result.VTL == pytest.approx(tw_expected["VTL"])
    assert result.VTU == pytest.approx(tw_expected["VTU"])
    assert result.gale_radius_km == pytest.approx(gale_expected)
    assert result.npts >= cps.MIN_MASK_POINTS


def test_compute_point_too_few_points_returns_nan():
    clat, clon = 20.0, 0.0
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=1, dlat=1.0, dlon=1.0)
    assert lat2d.shape == (3, 3)
    z_stack = np.zeros((2,) + lat2d.shape)

    result = cps.compute_point([900, 600], z_stack, lat2d, lon2d, clat, clon, heading_deg=0.0)

    assert result.npts == 9
    assert math.isnan(result.B)
    assert math.isnan(result.VTL)
    assert math.isnan(result.VTU)
    assert math.isnan(result.gale_radius_km)


# ---------------------------------------------------------------------------
# (i) thermal_wind with a band entirely missing
# ---------------------------------------------------------------------------


def test_thermal_wind_missing_lower_band():
    clat, clon = 20.0, 0.0
    levels = (550, 500, 450, 400, 350, 300)  # no overlap with LOWER_LEVELS at all
    lat2d, lon2d = synthetic.make_grid(clat, clon, half_width_deg=8, dlat=0.25, dlon=0.25)
    z_stack = synthetic.warm_core_heights(lat2d, lon2d, clat, clon, levels, _warm_amp, scale_km=150.0)

    result = cps.thermal_wind(levels, z_stack, lat2d, lon2d, clat, clon)
    assert math.isnan(result["VTL"])
    assert not math.isnan(result["VTU"])
    assert result["VTU"] > 0
