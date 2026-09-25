"""Synthetic MSLP field builders for the realtime test suite.

No test functions live here -- import this from the test modules. Grid
spacing follows `gfs_cps.RES_DEG` (the real GFS 0.25 degree grid) since
`track_cps.subgrid` and `track_cps.find_center` assume that spacing
when converting a search radius in km to a number of grid cells.

Fields are built on a plain (non-wrapping) regional box: none of these
tests need the global dateline wrap, so callers pass `wrap=False` to
the functions under test.
"""

from __future__ import annotations

import numpy as np

import gfs_cps as g
import track_cps as tc


def make_frame(lat0: float, lat1: float, lon0: float, lon1: float, mslp_hpa: float = 1013.0,
               psfc_hpa: float = 1013.0) -> dict:
    """A flat frame (constant MSLP and surface pressure) on a `g.RES_DEG`
    grid spanning [lat0, lat1] x [lon0, lon1], in the Pa units `find_center`
    and `all_centers` expect (they divide by 100 internally)."""
    n_lat = int(round((lat1 - lat0) / g.RES_DEG)) + 1
    n_lon = int(round((lon1 - lon0) / g.RES_DEG)) + 1
    lat = lat0 + g.RES_DEG * np.arange(n_lat)
    lon = lon0 + g.RES_DEG * np.arange(n_lon)
    pmsl = np.full((n_lat, n_lon), mslp_hpa * 100.0)
    psfc = np.full((n_lat, n_lon), psfc_hpa * 100.0)
    return dict(lat=lat, lon=lon, pmsl=pmsl, psfc=psfc)


def add_gaussian_low(f: dict, clat: float, clon: float, depth_hpa: float, sigma_km: float) -> None:
    """Subtracts a Gaussian dip of peak depth_hpa (at the center, decaying
    over sigma_km) from f["pmsl"], using track_cps's own great-circle
    distance so the geometry matches what find_center itself uses."""
    la = f["lat"][:, None]
    lo = f["lon"][None, :]
    r_km = tc.gc_km(clat, clon, la, lo)
    f["pmsl"] -= (depth_hpa * np.exp(-(r_km / sigma_km) ** 2)) * 100.0


def nearest_index(f: dict, lat: float, lon: float) -> tuple[int, int]:
    """Grid (row, col) nearest a lat/lon, for placing a single-point feature."""
    i = int(round((lat - f["lat"][0]) / g.RES_DEG))
    j = int(round((lon - f["lon"][0]) / g.RES_DEG))
    return i, j


def set_point(f: dict, lat: float, lon: float, mslp_hpa: float | None = None,
              psfc_hpa: float | None = None) -> tuple[int, int]:
    """Overwrites a single grid point's MSLP and/or surface pressure (e.g. a
    terrain point where MSLP is extrapolated well below ground). Returns its
    (row, col)."""
    i, j = nearest_index(f, lat, lon)
    if mslp_hpa is not None:
        f["pmsl"][i, j] = mslp_hpa * 100.0
    if psfc_hpa is not None:
        f["psfc"][i, j] = psfc_hpa * 100.0
    return i, j
