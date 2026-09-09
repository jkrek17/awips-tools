"""
Hart (2003) cyclone phase space parameters, pure numpy.

Cyclone Phase Space (CPS) is a way of classifying a storm's structure
without relying on satellite presentation or a forecaster's eye: it
looks only at the height (geopotential) field on a set of pressure
levels around the storm's own center. Three numbers come out of it
for every analysis or forecast time:

- **B**: how lopsided the low-level thickness is, left of the storm's
  track versus right of it. Near zero means an axisymmetric,
  tropical-like structure; large means a frontal (asymmetric)
  structure. B says nothing about warm versus cold core on its own;
  that is what VTL and VTU are for.
- **VTL, VTU**: the lower- and upper-tropospheric "thermal wind"
  parameters. Positive means the storm's core is warmer than its
  surroundings at that level (tropical-like); negative means colder
  (baroclinic/extratropical-like).

This module has no I/O and no AWIPS or web dependencies on purpose,
so the exact same code can run inside a nightly GFS pipeline, an
AWIPS GFE procedure, or a unit test. See `web/CPS/PLAN.md` section 4
for the derivation this follows and section 8 for how it is verified.

Grid convention used throughout: `lat2d` and `lon2d` are 2D numpy
arrays of identical shape (degrees), paired with field arrays of that
same shape. Longitude may be given in -180..180 or 0..360, and a storm
may sit right on the antimeridian; every function here wraps longitude
differences into -180..180 before using them, so either convention
works and the two can even be mixed between the grid and the center.

Headings and bearings are meteorological "toward" directions: degrees
clockwise from north, so 0 is moving/pointing north and 90 is moving/
pointing east.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

__all__ = [
    "RADIUS_KM",
    "LOWER_LEVELS",
    "UPPER_LEVELS",
    "B_SYMMETRIC_THRESHOLD_M",
    "GALE_MS",
    "MIN_MASK_POINTS",
    "great_circle_km",
    "local_offsets_km",
    "radial_mask",
    "weighted_mean",
    "track_motion",
    "parameter_b",
    "thermal_wind",
    "gale_radius_km",
    "refine_center",
    "CPSPoint",
    "compute_point",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_KM = 6371.0

#: Radius of the analysis circle Hart uses around the storm center.
RADIUS_KM = 500.0

#: Pressure levels (hPa) spanning the lower-tropospheric thermal wind band.
LOWER_LEVELS = (900, 850, 800, 750, 700, 650, 600)

#: Pressure levels (hPa) spanning the upper-tropospheric thermal wind band.
UPPER_LEVELS = (600, 550, 500, 450, 400, 350, 300)

#: |B| below this (in meters of thickness) is considered "symmetric".
B_SYMMETRIC_THRESHOLD_M = 10.0

#: Gale-force threshold, 34 kt in m/s, used for the gale radius.
GALE_MS = 17.5

#: A CPS point with fewer masked grid points than this is not trustworthy.
MIN_MASK_POINTS = 20


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _wrap_deg180(delta_deg: np.ndarray) -> np.ndarray:
    """Wrap a longitude difference (degrees) into the range -180..180."""
    return ((np.asarray(delta_deg, dtype=float) + 180.0) % 360.0) - 180.0


def great_circle_km(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Great-circle distance (km) between two points, via the haversine
    formula. All four arguments are degrees and broadcast against each
    other normally, so this works for two scalars, a grid against a
    scalar center, or two grids of the same shape.
    """
    lat1r = np.radians(lat1)
    lat2r = np.radians(lat2)
    dlat = lat2r - lat1r
    dlon = np.radians(_wrap_deg180(np.asarray(lon2, dtype=float) - np.asarray(lon1, dtype=float)))
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def local_offsets_km(
    lat2d: np.ndarray, lon2d: np.ndarray, clat: float, clon: float
) -> tuple[np.ndarray, np.ndarray]:
    """East (`dx_km`) and north (`dy_km`) offsets of every grid point from
    a center, in a flat local Cartesian approximation. Good for the
    storm-scale (few hundred km) distances CPS works at; not meant for
    anything much larger. The longitude difference is wrapped into
    -180..180 first, so this is safe across the antimeridian.
    """
    dlon_deg = _wrap_deg180(np.asarray(lon2d, dtype=float) - clon)
    dlat_deg = np.asarray(lat2d, dtype=float) - clat
    dx_km = EARTH_RADIUS_KM * np.cos(np.radians(clat)) * np.radians(dlon_deg)
    dy_km = EARTH_RADIUS_KM * np.radians(dlat_deg)
    return dx_km, dy_km


def radial_mask(
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    radius_km: float = RADIUS_KM,
) -> np.ndarray:
    """Boolean mask of grid points within `radius_km` of the center."""
    return great_circle_km(lat2d, lon2d, clat, clon) <= radius_km


def weighted_mean(values: np.ndarray, lat2d: np.ndarray, mask: np.ndarray) -> float:
    """Cosine-latitude-weighted mean of `values` over `mask`. Every areal
    mean in this module goes through this function, so that grid cells
    are weighted by their true area rather than by count. Returns nan
    if the mask selects no points.
    """
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return float("nan")
    weights = np.cos(np.radians(np.asarray(lat2d, dtype=float)))[mask]
    return float(np.average(np.asarray(values, dtype=float)[mask], weights=weights))


# ---------------------------------------------------------------------------
# Storm motion
# ---------------------------------------------------------------------------


def track_motion(
    lats: Sequence[float], lons: Sequence[float], times_s: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Heading (degrees, clockwise from north) and speed (m/s) at every
    point of a track. Interior points use a centered difference (the
    point before to the point after); the first and last points use a
    one-sided forward/backward difference. `times_s` is any monotonic
    time coordinate in seconds (Unix epoch, or seconds since genesis,
    it does not matter as long as it is consistent). A single-point
    track returns heading nan and speed 0. Longitude wraparound at the
    antimeridian is handled the same way as everywhere else in this
    module.
    """
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    times_s = np.asarray(times_s, dtype=float)
    n = lats.size

    headings = np.full(n, np.nan)
    speeds = np.zeros(n)
    if n < 2:
        return headings, speeds

    for i in range(n):
        if i == 0:
            i0, i1 = 0, 1
        elif i == n - 1:
            i0, i1 = n - 2, n - 1
        else:
            i0, i1 = i - 1, i + 1

        dt = float(times_s[i1] - times_s[i0])
        dx_km, dy_km = local_offsets_km(lats[i1], lons[i1], lats[i0], lons[i0])
        if dt == 0.0:
            headings[i] = float("nan")
            speeds[i] = 0.0
            continue
        headings[i] = float(np.degrees(np.arctan2(dx_km, dy_km)) % 360.0)
        speeds[i] = float(np.hypot(dx_km, dy_km) * 1000.0 / dt)

    return headings, speeds


# ---------------------------------------------------------------------------
# Parameter B (thermal asymmetry)
# ---------------------------------------------------------------------------


def parameter_b(
    z900: np.ndarray,
    z600: np.ndarray,
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    heading_deg: float,
    radius_km: float = RADIUS_KM,
) -> float:
    """Hart's parameter B: the left/right asymmetry of 900-600 hPa
    thickness across the storm's direction of motion.

    The 900-600 hPa layer thickness (`z600 - z900`) is averaged
    separately over the half of the analysis circle to the right of
    the motion vector and the half to the left, and `B = h * (mean_right
    - mean_left)`, with `h = +1` in the Northern Hemisphere and `-1` in
    the Southern. The hemisphere factor makes B positive whenever the
    warm (thick) air lies on the equatorward-facing flank of the track,
    which is the frontal configuration a cyclone takes on during
    extratropical transition: right of track in the Northern Hemisphere,
    left of track in the Southern. Values near zero (see
    `B_SYMMETRIC_THRESHOLD_M`) indicate an axisymmetric, tropical-like
    thickness field; values well above it indicate a frontal one.

    Returns nan if the circle is empty, or if either half is empty
    (e.g. the circle is clipped by the domain edge).
    """
    mask = radial_mask(lat2d, lon2d, clat, clon, radius_km)
    if not mask.any():
        return float("nan")

    thickness = np.asarray(z600, dtype=float) - np.asarray(z900, dtype=float)
    dx_km, dy_km = local_offsets_km(lat2d, lon2d, clat, clon)

    heading_rad = np.radians(heading_deg)
    mx, my = np.sin(heading_rad), np.cos(heading_rad)
    # Cross product of the motion vector with each point's offset vector.
    # Moving north (mx=0, my=1) with a point due east (dx=+1, dy=0) gives
    # cross = 0*0 - 1*1 = -1, so cross < 0 is defined as "right of track".
    cross = mx * dy_km - my * dx_km

    right_mask = mask & (cross < 0)
    left_mask = mask & (cross > 0)
    if not right_mask.any() or not left_mask.any():
        return float("nan")

    mean_right = weighted_mean(thickness, lat2d, right_mask)
    mean_left = weighted_mean(thickness, lat2d, left_mask)
    hemisphere_sign = 1.0 if clat >= 0 else -1.0
    return hemisphere_sign * (mean_right - mean_left)


# ---------------------------------------------------------------------------
# Thermal wind (VTL, VTU)
# ---------------------------------------------------------------------------


def _band_slope(dz_by_level: dict[int, float], band_levels: Sequence[int]) -> float:
    """Least-squares slope of dZ against ln(pressure) over one band."""
    present = [lvl for lvl in band_levels if not np.isnan(dz_by_level.get(lvl, float("nan")))]
    if len(present) < 3:
        return float("nan")
    x = np.log(np.asarray(present, dtype=float))
    y = np.asarray([dz_by_level[lvl] for lvl in present], dtype=float)
    slope, _intercept = np.polyfit(x, y, 1)
    return float(slope)


def thermal_wind(
    levels_hpa: Sequence[float],
    z_stack: np.ndarray,
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    radius_km: float = RADIUS_KM,
) -> dict:
    """Hart's lower- and upper-tropospheric thermal wind parameters.

    At each level, `dZ = max(Z) - min(Z)` over the analysis circle. VTL
    is the least-squares slope of `dZ` against `ln(pressure)` over the
    900-600 hPa band (`LOWER_LEVELS`); VTU is the same over 600-300 hPa
    (`UPPER_LEVELS`). A band needs at least 3 of its levels present in
    `levels_hpa` or its slope comes back nan.

    SIGN CONVENTION: the values returned here are already the
    *negative* of the textbook thermal-wind sign, chosen so that
    **positive VTL/VTU means warm core**, matching the -V_T^L axis
    label on Hart's own diagrams. Concretely: a warm-core storm has
    more 900-600 hPa thickness right over its center than at 500 km
    out, and that difference shrinks with height, so `dZ` is larger at
    900 hPa (large ln p) than at 600 hPa (small ln p) -- a *positive*
    slope of dZ against ln(p). A cold core is the opposite and comes
    back negative. Do not re-negate this when plotting against Hart's
    diagrams; it already matches the axis as printed.

    `z_stack` has shape (nlev, ny, nx), one 2D height array per entry
    of `levels_hpa` (any order -- matched to `z_stack` by position,
    then handled in whatever order they come in).

    Returns a dict with keys `VTL`, `VTU`, `dz_by_level` (level in hPa
    -> dZ in meters, for every level given), and `npts` (grid points in
    the analysis circle).
    """
    levels_hpa = [int(round(lvl)) for lvl in levels_hpa]
    mask = radial_mask(lat2d, lon2d, clat, clon, radius_km)
    npts = int(np.count_nonzero(mask))

    dz_by_level: dict[int, float] = {}
    for lvl, z in zip(levels_hpa, z_stack):
        if npts == 0:
            dz_by_level[lvl] = float("nan")
        else:
            vals = np.asarray(z, dtype=float)[mask]
            dz_by_level[lvl] = float(vals.max() - vals.min())

    return {
        "VTL": _band_slope(dz_by_level, LOWER_LEVELS),
        "VTU": _band_slope(dz_by_level, UPPER_LEVELS),
        "dz_by_level": dz_by_level,
        "npts": npts,
    }


# ---------------------------------------------------------------------------
# Gale radius
# ---------------------------------------------------------------------------


def gale_radius_km(
    u: np.ndarray,
    v: np.ndarray,
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    threshold_ms: float = GALE_MS,
    search_radius_km: float = RADIUS_KM,
) -> float:
    """Mean radius (km) of the gale-force (default 34 kt) wind isotach,
    averaged over the eight 45-degree compass sectors the way Hart's
    diagrams size their markers. A sector with no wind at or above the
    threshold contributes 0 km to the average (a calm/small sector
    should shrink the mean, not be skipped). Returns 0.0 if the search
    circle has no grid points at all.
    """
    mask = radial_mask(lat2d, lon2d, clat, clon, search_radius_km)
    if not mask.any():
        return 0.0

    speed = np.hypot(np.asarray(u, dtype=float), np.asarray(v, dtype=float))
    dist_km = great_circle_km(lat2d, lon2d, clat, clon)
    dx_km, dy_km = local_offsets_km(lat2d, lon2d, clat, clon)
    bearing_deg = np.degrees(np.arctan2(dx_km, dy_km)) % 360.0

    sector_radii = []
    for sector in range(8):
        lo, hi = sector * 45.0, (sector + 1) * 45.0
        sector_mask = mask & (bearing_deg >= lo) & (bearing_deg < hi)
        gale_mask = sector_mask & (speed >= threshold_ms)
        sector_radii.append(float(dist_km[gale_mask].max()) if gale_mask.any() else 0.0)

    return float(np.mean(sector_radii))


# ---------------------------------------------------------------------------
# Center refinement
# ---------------------------------------------------------------------------


def _box_mean_3x3(field: np.ndarray) -> np.ndarray:
    """One pass of a 3x3 box mean, edges repeated (not shrunk)."""
    field = np.asarray(field, dtype=float)
    padded = np.pad(field, 1, mode="edge")
    total = np.zeros_like(field)
    for i in range(3):
        for j in range(3):
            total += padded[i : i + field.shape[0], j : j + field.shape[1]]
    return total / 9.0


def refine_center(
    mslp: np.ndarray,
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    max_shift_km: float = 100.0,
) -> tuple[float, float, float]:
    """Nudge a storm center onto the local MSLP minimum.

    Smooths `mslp` with one pass of a 3x3 box mean (to avoid latching
    onto a single noisy grid point), then returns the lat/lon of the
    lowest smoothed pressure within `max_shift_km` of the given center,
    plus the distance moved. If that search circle has no grid points,
    the input center is returned unchanged with a shift of 0.0. This
    keeps a bad refit from jumping to a neighboring low.
    """
    mask = radial_mask(lat2d, lon2d, clat, clon, max_shift_km)
    if not mask.any():
        return float(clat), float(clon), 0.0

    smoothed = _box_mean_3x3(mslp)
    candidate = np.where(mask, smoothed, np.inf)
    idx = np.unravel_index(np.argmin(candidate), candidate.shape)

    new_lat = float(np.asarray(lat2d)[idx])
    new_lon = float(np.asarray(lon2d)[idx])
    shift_km = float(great_circle_km(new_lat, new_lon, clat, clon))
    return new_lat, new_lon, shift_km


# ---------------------------------------------------------------------------
# Combined per-time-step result
# ---------------------------------------------------------------------------


@dataclass
class CPSPoint:
    """All of the CPS diagnostics for one storm at one analysis/forecast
    time. Any field may be nan when the analysis circle did not have
    enough grid points (`MIN_MASK_POINTS`) to trust, e.g. a storm near
    the edge of the model domain.
    """

    B: float
    VTL: float
    VTU: float
    gale_radius_km: float
    center_lat: float
    center_lon: float
    center_shift_km: float
    npts: int
    dz_by_level: dict = field(default_factory=dict)


def _find_level(levels_hpa: Sequence[float], z_stack: np.ndarray, target_hpa: int) -> np.ndarray:
    for lvl, z in zip(levels_hpa, z_stack):
        if int(round(lvl)) == target_hpa:
            return z
    raise ValueError(f"level {target_hpa} hPa not found in levels_hpa")


def compute_point(
    levels_hpa: Sequence[float],
    z_stack: np.ndarray,
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    clat: float,
    clon: float,
    heading_deg: float,
    *,
    mslp: np.ndarray | None = None,
    u925: np.ndarray | None = None,
    v925: np.ndarray | None = None,
    radius_km: float = RADIUS_KM,
    refine: bool = True,
) -> CPSPoint:
    """Compute one full `CPSPoint`: optionally refine the center on
    `mslp`, then B, VTL, VTU, and (if `u925`/`v925` are given) the gale
    radius, all relative to the (possibly refined) center.

    Raises `ValueError` if 900 or 600 hPa heights are not present in
    `levels_hpa`/`z_stack` -- both are required for parameter B. This
    check only happens once the analysis circle is known to have
    enough points to be worth computing at all.
    """
    center_lat, center_lon, shift_km = float(clat), float(clon), 0.0
    if mslp is not None and refine:
        center_lat, center_lon, shift_km = refine_center(
            mslp, lat2d, lon2d, clat, clon
        )

    mask = radial_mask(lat2d, lon2d, center_lat, center_lon, radius_km)
    npts = int(np.count_nonzero(mask))

    if npts < MIN_MASK_POINTS:
        return CPSPoint(
            B=float("nan"),
            VTL=float("nan"),
            VTU=float("nan"),
            gale_radius_km=float("nan"),
            center_lat=center_lat,
            center_lon=center_lon,
            center_shift_km=shift_km,
            npts=npts,
            dz_by_level={},
        )

    z900 = _find_level(levels_hpa, z_stack, 900)
    z600 = _find_level(levels_hpa, z_stack, 600)

    b_value = parameter_b(
        z900, z600, lat2d, lon2d, center_lat, center_lon, heading_deg, radius_km
    )
    tw = thermal_wind(levels_hpa, z_stack, lat2d, lon2d, center_lat, center_lon, radius_km)

    if u925 is not None and v925 is not None:
        gale_km = gale_radius_km(
            u925, v925, lat2d, lon2d, center_lat, center_lon, search_radius_km=radius_km
        )
    else:
        gale_km = float("nan")

    return CPSPoint(
        B=b_value,
        VTL=tw["VTL"],
        VTU=tw["VTU"],
        gale_radius_km=gale_km,
        center_lat=center_lat,
        center_lon=center_lon,
        center_shift_km=shift_km,
        npts=npts,
        dz_by_level=tw["dz_by_level"],
    )
