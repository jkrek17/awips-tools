"""Analytic vortex generators for the cps.hart test suite.

Deliberately independent of `cps.hart` (its own inline haversine, its
own offset math) so the tests are checking `cps.hart` against a second,
separately-written implementation of the same geometry rather than
against itself. No test functions live here -- import this from
test_hart.py.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

_EARTH_RADIUS_KM = 6371.0


def _wrap180(delta_deg: np.ndarray) -> np.ndarray:
    return ((np.asarray(delta_deg, dtype=float) + 180.0) % 360.0) - 180.0


def _haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Standalone haversine distance (km), independent of cps.hart."""
    lat1r, lat2r = np.radians(lat1), np.radians(lat2)
    dlat = lat2r - lat1r
    dlon = np.radians(_wrap180(np.asarray(lon2, dtype=float) - np.asarray(lon1, dtype=float)))
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    return 2.0 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def make_grid(
    clat: float,
    clon: float,
    half_width_deg: float = 20.0,
    dlat: float = 0.5,
    dlon: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """A regular lat/lon grid centered on (clat, clon), +/- half_width_deg
    in each direction. Longitude is always wrapped into -180..180, so a
    center placed near the antimeridian (e.g. clon=179.75) produces a
    grid that genuinely straddles it (some lon values negative, some
    positive) rather than running past 180 unwrapped -- exactly the
    case the dateline-handling code in cps.hart needs to get right.
    """
    lat_vals = np.arange(clat - half_width_deg, clat + half_width_deg + dlat / 2.0, dlat)
    lon_vals = np.arange(clon - half_width_deg, clon + half_width_deg + dlon / 2.0, dlon)
    lon2d, lat2d = np.meshgrid(lon_vals, lat_vals)
    lon2d = _wrap180(lon2d)
    return lat2d, lon2d


def warm_core_heights(
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    levels: Sequence[float],
    amp_fn: Callable[[float], float],
    scale_km: float = 150.0,
) -> np.ndarray:
    """Synthetic geopotential height stack: a smooth per-level background
    minus a Gaussian bump of amplitude `amp_fn(level)` centered on the
    storm. A warm core is `amp_fn` decreasing with height (larger at
    900 hPa than 300 hPa); a cold core is the opposite.

    Returns an array shaped (len(levels), *lat2d.shape).
    """
    r_km = _haversine_km(lat2d, lon2d, clat, clon)
    decay = np.exp(-(r_km / scale_km) ** 2)

    z_stack = np.empty((len(levels),) + lat2d.shape, dtype=float)
    for i, p in enumerate(levels):
        background = 100.0 + 7000.0 * np.log(1000.0 / p)
        z_stack[i] = background - amp_fn(p) * decay
    return z_stack


def rankine_wind(
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    vmax_ms: float,
    rmax_km: float,
    decay: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Cyclonic (counterclockwise in the NH) modified-Rankine tangential
    wind field: `V = vmax*(r/rmax)` inside `rmax`, `vmax*(rmax/r)**decay`
    outside. Returns (u, v) wind components in m/s.
    """
    r_km = _haversine_km(lat2d, lon2d, clat, clon)

    dlat_deg = np.asarray(lat2d, dtype=float) - clat
    dlon_deg = _wrap180(np.asarray(lon2d, dtype=float) - clon)
    dx_km = _EARTH_RADIUS_KM * np.cos(np.radians(clat)) * np.radians(dlon_deg)
    dy_km = _EARTH_RADIUS_KM * np.radians(dlat_deg)

    r_safe = np.where(r_km > 0, r_km, 1.0)
    # Cyclonic (NH counterclockwise): tangential unit vector is the
    # radial unit vector rotated 90 degrees counterclockwise.
    tangent_x = -dy_km / r_safe
    tangent_y = dx_km / r_safe

    speed = np.where(
        r_km <= rmax_km,
        vmax_ms * (r_km / rmax_km),
        vmax_ms * (rmax_km / r_safe) ** decay,
    )
    speed = np.where(r_km == 0, 0.0, speed)

    u = speed * tangent_x
    v = speed * tangent_y
    return u, v
