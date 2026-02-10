"""
Storm identification from gridded pressure and wind fields.

Finds discrete storm features (pressure minima, wind maxima) and
classifies their intensity.  Designed to work directly on GFE grids --
lat/lon coordinate arrays are used only for geographic separation checks,
not for domain clipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from scipy import ndimage
from scipy.ndimage import label, minimum_filter, maximum_filter

from .domains import haversine_distance, degrees_to_km


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class StormFeature:
    """
    An identified storm on the grid.

    Attributes:
        storm_id: Unique label (e.g. ``"STORM_001"``).
        center_lat, center_lon: Storm center in degrees.
        grid_row, grid_col: Storm center indices in the source grid.
        min_pressure: MSLP at center (hPa), if available.
        max_wind: Maximum wind speed near center (kt), if available.
        intensity_category: ``"hurricane"``, ``"storm"``, ``"gale"``,
                            ``"moderate"``, ``"weak"``.
        extent_mask: Boolean grid marking the storm's footprint.
        area_km2: Approximate storm area (km^2).
    """

    storm_id: str
    center_lat: float
    center_lon: float
    grid_row: int
    grid_col: int
    min_pressure: Optional[float] = None
    max_wind: Optional[float] = None
    intensity_category: str = "weak"
    extent_mask: Optional[np.ndarray] = None
    area_km2: float = 0.0


# ---------------------------------------------------------------------------
# Intensity classification
# ---------------------------------------------------------------------------

def _classify_intensity(max_wind, min_pressure):
    """Return a category string from wind / pressure values."""
    if max_wind is not None:
        if max_wind >= 64:
            return "hurricane"
        if max_wind >= 48:
            return "storm"
        if max_wind >= 34:
            return "gale"
        return "moderate"
    if min_pressure is not None:
        if min_pressure <= 960:
            return "hurricane"
        if min_pressure <= 980:
            return "storm"
        if min_pressure <= 1000:
            return "gale"
        return "moderate"
    return "weak"


# ---------------------------------------------------------------------------
# Grid-metric helpers
# ---------------------------------------------------------------------------

def _grid_metrics(lat_grid, lon_grid):
    """
    Compute grid spacing in degrees and km from 2-D coordinate arrays.

    Returns (dlat, dlon, dy_km, dx_km).
    """
    if lat_grid.shape[0] > 1:
        dlat = float(np.abs(lat_grid[1, 0] - lat_grid[0, 0]))
    else:
        dlat = 1.0

    if lon_grid.shape[1] > 1:
        dlon_raw = lon_grid[0, 1] - lon_grid[0, 0]
        # handle dateline wrap
        if dlon_raw < -180:
            dlon_raw += 360
        elif dlon_raw > 180:
            dlon_raw -= 360
        dlon = float(np.abs(dlon_raw))
    else:
        dlon = 1.0

    center_lat = float(np.mean(lat_grid))
    dy_km, dx_km = degrees_to_km(center_lat, dlat, dlon)
    return dlat, dlon, dy_km, dx_km


def _smooth(field, sigma_pts):
    """Gaussian-smooth *field*, tolerating NaN regions."""
    valid = np.isfinite(field)
    if not np.any(valid):
        return field.copy()
    fill_val = float(np.nanmean(field))
    filled = np.where(valid, field, fill_val)
    smoothed = ndimage.gaussian_filter(filled, sigma=sigma_pts, mode="nearest")
    return np.where(valid, smoothed, np.nan)


def _search_mask(center_i, center_j, radius_pts, shape):
    """Boolean circle of *radius_pts* around (center_i, center_j)."""
    y, x = np.ogrid[:shape[0], :shape[1]]
    # Scale row/col distances so the circle is isotropic in grid space
    dist_sq = (y - center_i) ** 2 + (x - center_j) ** 2
    return dist_sq <= radius_pts ** 2


# ---------------------------------------------------------------------------
# Public identification functions
# ---------------------------------------------------------------------------

def identify_storms(
    lat_grid,
    lon_grid,
    pressure=None,
    wind_speed=None,
    min_separation_km=500.0,
    min_pressure_anomaly_hpa=4.0,
    min_wind_threshold_kt=34.0,
    max_storms=10,
    smoothing_scale_km=100.0,
    search_radius_km=500.0,
):
    """
    Identify storm features from pressure and/or wind grids.

    At least one of *pressure* or *wind_speed* must be provided.  When both
    are given, storms are detected from pressure minima and wind information
    is used for intensity classification.

    Args:
        lat_grid: 2-D latitude array (degrees).
        lon_grid: 2-D longitude array (degrees).
        pressure: 2-D MSLP field (hPa), or None.
        wind_speed: 2-D wind-speed field (kt), or None.
        min_separation_km: Minimum distance between storm centres.
        min_pressure_anomaly_hpa: Minimum background-relative depression.
        min_wind_threshold_kt: Minimum wind speed for wind-only detection.
        max_storms: Cap on number of storms returned.
        smoothing_scale_km: Gaussian smoothing width (km).
        search_radius_km: Radius around each centre for extent/intensity.

    Returns:
        List of :class:`StormFeature`, sorted strongest first.
    """
    if pressure is None and wind_speed is None:
        return []

    _, _, dy_km, dx_km = _grid_metrics(lat_grid, lon_grid)
    mean_res_km = (dy_km + dx_km) / 2.0
    sigma_pts = max(1.0, smoothing_scale_km / mean_res_km)
    sep_pts = max(3, int(min_separation_km / mean_res_km))
    radius_pts = max(3, int(search_radius_km / mean_res_km))

    if pressure is not None:
        storms = _identify_from_pressure(
            pressure, lat_grid, lon_grid, wind_speed,
            dy_km, dx_km, sigma_pts, sep_pts, radius_pts,
            min_pressure_anomaly_hpa, max_storms, min_separation_km,
        )
    else:
        storms = _identify_from_wind(
            wind_speed, lat_grid, lon_grid,
            dy_km, dx_km, sigma_pts, sep_pts, radius_pts,
            min_wind_threshold_kt, max_storms, min_separation_km,
        )

    return storms


# ---------------------------------------------------------------------------
# Internal detection routines
# ---------------------------------------------------------------------------

def _identify_from_pressure(
    pressure, lat_grid, lon_grid, wind_speed,
    dy_km, dx_km, sigma_pts, sep_pts, radius_pts,
    min_anomaly, max_storms, min_sep_km,
):
    pressure_smooth = _smooth(pressure, sigma_pts)

    # Background field (very large-scale smooth)
    bg_sigma = max(sigma_pts * 5, 20)
    background = _smooth(pressure_smooth, bg_sigma)
    anomaly = background - pressure_smooth  # positive = low pressure

    # Local minima
    local_min = pressure_smooth == minimum_filter(
        pressure_smooth, size=sep_pts, mode="constant", cval=np.inf,
    )
    candidates = local_min & (anomaly >= min_anomaly) & np.isfinite(pressure_smooth)
    candidate_idx = np.argwhere(candidates)

    if len(candidate_idx) == 0:
        return []

    # Sort by anomaly strength (strongest first)
    anom_vals = anomaly[candidate_idx[:, 0], candidate_idx[:, 1]]
    order = np.argsort(anom_vals)[::-1]
    candidate_idx = candidate_idx[order]

    storms = []
    counter = 0
    for idx in candidate_idx:
        if len(storms) >= max_storms:
            break
        i, j = int(idx[0]), int(idx[1])
        clat, clon = float(lat_grid[i, j]), float(lon_grid[i, j])

        # Enforce minimum separation (geographic distance)
        too_close = False
        for s in storms:
            dist = haversine_distance(clat, clon, s.center_lat, s.center_lon)
            if dist < min_sep_km:
                too_close = True
                break
        if too_close:
            continue

        counter += 1
        mask = _search_mask(i, j, radius_pts, pressure.shape)

        # Intensity from wind if available
        max_wind = None
        if wind_speed is not None:
            ws_region = np.where(mask, wind_speed, 0)
            max_wind = float(np.max(ws_region))

        min_p = float(pressure_smooth[i, j])
        cat = _classify_intensity(max_wind, min_p)

        storms.append(StormFeature(
            storm_id="STORM_%03d" % counter,
            center_lat=clat,
            center_lon=clon,
            grid_row=i,
            grid_col=j,
            min_pressure=min_p,
            max_wind=max_wind,
            intensity_category=cat,
            extent_mask=mask,
            area_km2=float(np.sum(mask)) * dx_km * dy_km,
        ))

    storms.sort(key=lambda s: s.min_pressure if s.min_pressure is not None else 1100)
    return storms


def _identify_from_wind(
    wind_speed, lat_grid, lon_grid,
    dy_km, dx_km, sigma_pts, sep_pts, radius_pts,
    min_wind_kt, max_storms, min_sep_km,
):
    wind_smooth = _smooth(wind_speed, sigma_pts)

    above = wind_smooth >= min_wind_kt
    labeled, n_features = label(above & np.isfinite(wind_smooth))

    if n_features == 0:
        return []

    storms = []
    counter = 0
    for fid in range(1, n_features + 1):
        if len(storms) >= max_storms:
            break
        fmask = labeled == fid
        region_wind = np.where(fmask, wind_smooth, 0)
        max_idx = np.unravel_index(np.argmax(region_wind), region_wind.shape)
        i, j = int(max_idx[0]), int(max_idx[1])
        clat, clon = float(lat_grid[i, j]), float(lon_grid[i, j])
        mw = float(wind_smooth[i, j])

        too_close = False
        for s in storms:
            dist = haversine_distance(clat, clon, s.center_lat, s.center_lon)
            if dist < min_sep_km:
                too_close = True
                break
        if too_close:
            continue

        counter += 1
        mask = _search_mask(i, j, radius_pts, wind_speed.shape)
        cat = _classify_intensity(mw, None)

        storms.append(StormFeature(
            storm_id="STORM_%03d" % counter,
            center_lat=clat,
            center_lon=clon,
            grid_row=i,
            grid_col=j,
            max_wind=mw,
            intensity_category=cat,
            extent_mask=mask,
            area_km2=float(np.sum(mask)) * dx_km * dy_km,
        ))

    storms.sort(key=lambda s: -(s.max_wind if s.max_wind is not None else 0))
    return storms


__all__ = [
    "StormFeature",
    "identify_storms",
]
