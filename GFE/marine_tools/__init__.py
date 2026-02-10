"""
Marine Tools -- storm identification for GFE grid editing.

Provides:
- Storm detection from MSLP and wind-speed grids
- Geographic distance utilities for storm separation checks
"""

from __future__ import annotations

from .domains import (
    EARTH_RADIUS_KM,
    DEG_TO_KM,
    haversine_distance,
    degrees_to_km,
    km_to_degrees,
)
from .storm_identification import (
    StormFeature,
    identify_storms,
)

__all__ = [
    "EARTH_RADIUS_KM",
    "DEG_TO_KM",
    "haversine_distance",
    "degrees_to_km",
    "km_to_degrees",
    "StormFeature",
    "identify_storms",
]
