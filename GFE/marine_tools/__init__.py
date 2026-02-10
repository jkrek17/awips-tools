"""
Marine Tools -- storm identification and area-based grid editing for GFE.

Package contents:
    domains              - Spherical distance and coordinate utilities
    storm_identification - Detect storms from MSLP / wind grids
    Analyze_MarineStorms - GFE procedure: find storms, create edit areas
    Blend_StormArea      - GFE smart tool: blend models inside an edit area
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
    # domain utilities
    "EARTH_RADIUS_KM",
    "DEG_TO_KM",
    "haversine_distance",
    "degrees_to_km",
    "km_to_degrees",
    # storm identification
    "StormFeature",
    "identify_storms",
]
