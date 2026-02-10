"""
Ocean domain utilities for marine storm analysis.

Provides spherical coordinate math and distance calculations used by
storm identification tools. The OceanDomain class is not tied to the
GFE grid -- it is used only for geographic distance/separation checks
during storm detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union

import numpy as np

# Earth radius in km for distance calculations
EARTH_RADIUS_KM = 6371.0

# Degrees-to-km at the equator (pi * R / 180)
DEG_TO_KM = np.pi * EARTH_RADIUS_KM / 180.0


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Great-circle distance between two points (scalar or array).

    Args:
        lat1, lon1: First point(s) in degrees.
        lat2, lon2: Second point(s) in degrees.

    Returns:
        Distance in kilometers.
    """
    lat1_r, lon1_r = np.radians(lat1), np.radians(lon1)
    lat2_r, lon2_r = np.radians(lat2), np.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))

    return EARTH_RADIUS_KM * c


def degrees_to_km(lat, delta_lat=0.0, delta_lon=0.0):
    """
    Convert degree displacements to kilometers at a given latitude.

    Args:
        lat: Reference latitude (degrees).
        delta_lat: Latitude displacement (degrees).
        delta_lon: Longitude displacement (degrees).

    Returns:
        Tuple of (dy_km, dx_km).
    """
    lat_rad = np.radians(lat)
    dy_km = delta_lat * DEG_TO_KM
    dx_km = delta_lon * DEG_TO_KM * np.cos(lat_rad)
    return dy_km, dx_km


def km_to_degrees(lat, dy_km=0.0, dx_km=0.0):
    """
    Convert kilometer displacements to degrees at a given latitude.

    Args:
        lat: Reference latitude (degrees).
        dy_km: North-south displacement (km).
        dx_km: East-west displacement (km).

    Returns:
        Tuple of (delta_lat, delta_lon).
    """
    lat_rad = np.radians(lat)
    delta_lat = dy_km / DEG_TO_KM
    cos_lat = np.cos(lat_rad)
    if cos_lat == 0:
        delta_lon = 0.0
    else:
        delta_lon = dx_km / (DEG_TO_KM * cos_lat)
    return delta_lat, delta_lon


__all__ = [
    "EARTH_RADIUS_KM",
    "DEG_TO_KM",
    "haversine_distance",
    "degrees_to_km",
    "km_to_degrees",
]
