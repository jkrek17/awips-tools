"""track_cps.find_center on synthetic MSLP fields.

See find_center's own docstring for the rules exercised here: the MSLP
minimum nearest a guess position within a search radius, below
MAX_MSLP_HPA, not over terrain (surface pressure under MIN_PSFC_HPA),
not poleward of POLE_LAT, not above an optional max_mslp cap, and
within an optional reach = (lat0, lon0, km) of some other point.
"""

from __future__ import annotations

import numpy as np
import pytest

import track_cps as tc
from rt_synthetic import add_gaussian_low, make_frame, set_point

BASE_HPA = 1013.0


def _basin(depth_hpa=25.0, sigma_km=300.0, clat=35.0, clon=-70.0):
    """A single Gaussian low on a regional (non-wrapping) grid, its peak
    exactly on a grid point so the expected minimum MSLP is exact."""
    f = make_frame(25.0, 45.0, -80.0, -60.0, mslp_hpa=BASE_HPA)
    add_gaussian_low(f, clat, clon, depth_hpa, sigma_km)
    return f, clat, clon, BASE_HPA - depth_hpa


def test_finds_gaussian_low_at_its_center():
    f, clat, clon, expect_mslp = _basin()
    hit = tc.find_center(f, clat + 0.2, clon - 0.2, radius_km=400.0, wrap=False)
    assert hit is not None
    fi, fj, mslp = hit
    i0, j0 = tc.frac_index(f, clat, clon)
    assert abs(fi - i0) < 1.0  # within one grid cell of the true center
    assert abs(fj - j0) < 1.0
    assert mslp == pytest.approx(expect_mslp, abs=1e-6)


def test_terrain_does_not_hide_the_real_low_beside_it():
    """A terrain point (surface pressure under MIN_PSFC_HPA) reading deeper
    than the real low, placed inside the real low's own +/- LOCAL_MIN_HALF
    box, must not steal the fix: the real low is found instead, per
    find_center's docstring."""
    f, clat, clon, expect_mslp = _basin()
    # 2 cells (0.5 deg) away from the low's center: inside the +/- 4 cell
    # box find_center tests for a local minimum, and reading far deeper
    # (900 hPa) than the genuine low, but over terrain (750 hPa surface
    # pressure, well under MIN_PSFC_HPA).
    terr_lat = clat + 2 * tc.g.RES_DEG
    assert terr_lat != clat
    set_point(f, terr_lat, clon, mslp_hpa=900.0, psfc_hpa=750.0)
    assert tc.MIN_PSFC_HPA > 750.0

    hit = tc.find_center(f, clat, clon, radius_km=400.0, wrap=False)
    assert hit is not None
    fi, fj, mslp = hit
    i0, j0 = tc.frac_index(f, clat, clon)
    assert abs(fi - i0) < 1.0
    assert abs(fj - j0) < 1.0
    # The fix lands on the real low's depth, not the bogus terrain value.
    assert mslp == pytest.approx(expect_mslp, abs=1e-6)
    assert mslp > 900.0


def test_candidate_above_max_mslp_cap_is_refused():
    """A candidate more than MAX_RISE_HPA above the previous fix (passed in
    as max_mslp = previous_mslp + MAX_RISE_HPA by sample_frame) is refused."""
    f, clat, clon, actual_mslp = _basin(depth_hpa=25.0)  # actual_mslp = 988.0
    previous_fix_mslp = actual_mslp - 20.0  # a deeper previous fix (968.0)
    cap = previous_fix_mslp + tc.MAX_RISE_HPA  # 980.0 < actual 988.0: refused
    assert cap < actual_mslp

    hit = tc.find_center(f, clat, clon, radius_km=400.0, wrap=False, max_mslp=cap)
    assert hit is None

    # Sanity: without the cap the same search finds the low.
    hit_uncapped = tc.find_center(f, clat, clon, radius_km=400.0, wrap=False)
    assert hit_uncapped is not None


def test_candidate_beyond_reach_is_refused():
    """A candidate outside reach = (lat0, lon0, km) is refused even when it
    is inside the plain search radius around (lat, lon)."""
    f, clat, clon, _ = _basin()
    far_lat, far_lon = clat, clon - 5.0  # ~5 deg west: several hundred km away
    far_km = float(tc.gc_km(far_lat, far_lon, clat, clon))
    assert far_km > 100.0

    # Search centered right on the low (radius alone would find it)...
    hit_no_reach = tc.find_center(f, clat, clon, radius_km=50.0, wrap=False)
    assert hit_no_reach is not None
    # ...but reach is anchored elsewhere with too small a limit.
    hit = tc.find_center(f, clat, clon, radius_km=50.0, wrap=False, reach=(far_lat, far_lon, 10.0))
    assert hit is None
    # A reach big enough to cover the distance lets it through again.
    hit_ok = tc.find_center(f, clat, clon, radius_km=50.0, wrap=False, reach=(far_lat, far_lon, far_km + 10.0))
    assert hit_ok is not None


def test_latitudes_poleward_of_pole_lat_are_excluded():
    """A deep low placed poleward of POLE_LAT is never returned."""
    f = make_frame(80.0, 89.0, -5.0, 5.0, mslp_hpa=BASE_HPA)
    plat, plon = 87.0, 0.0
    assert plat > tc.POLE_LAT
    add_gaussian_low(f, plat, plon, depth_hpa=30.0, sigma_km=100.0)

    hit = tc.find_center(f, plat, plon, radius_km=200.0, wrap=False)
    assert hit is None

    # Sanity: the same field with the low moved equatorward of POLE_LAT is found.
    f2 = make_frame(80.0, 89.0, -5.0, 5.0, mslp_hpa=BASE_HPA)
    add_gaussian_low(f2, tc.POLE_LAT - 1.0, plon, depth_hpa=30.0, sigma_km=100.0)
    hit2 = tc.find_center(f2, tc.POLE_LAT - 1.0, plon, radius_km=200.0, wrap=False)
    assert hit2 is not None
