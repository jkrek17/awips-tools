"""
Marine Tools for Grid-Based Multi-Storm Analysis.

This package provides specialized tools for analyzing marine weather patterns
across large ocean basins with multiple concurrent storm systems. Designed for
the North Atlantic (30N-65N, 85W-20E) and North Pacific (30N-65N, 115W-120E)
domains.

Key Capabilities:
- Domain definition and coordinate handling (including dateline crossing)
- Grid-based storm feature identification
- Multi-storm ensemble statistics
- Spatial correlation and uncertainty analysis
- Storm-relative coordinate transformations
"""

from __future__ import annotations

from .domains import (
    OceanDomain,
    NORTH_ATLANTIC,
    NORTH_PACIFIC,
    get_domain,
    list_domains,
)
from .grid_analysis import (
    GridAnalyzer,
    extract_subgrid,
    compute_spatial_statistics,
    compute_gradient_fields,
    compute_laplacian,
)
from .storm_identification import (
    StormFeature,
    StormIdentifier,
    identify_storms_from_pressure,
    identify_storms_from_wind,
    calculate_storm_extent,
)
from .ensemble_statistics import (
    StormEnsembleStats,
    compute_storm_relative_spread,
    compute_position_uncertainty,
    compute_compound_probability,
    compute_spatial_correlation,
)
from .multi_storm_analysis import (
    MultiStormAnalyzer,
    StormTrack,
    analyze_storm_interactions,
)

__all__ = [
    # Domains
    "OceanDomain",
    "NORTH_ATLANTIC",
    "NORTH_PACIFIC",
    "get_domain",
    "list_domains",
    # Grid Analysis
    "GridAnalyzer",
    "extract_subgrid",
    "compute_spatial_statistics",
    "compute_gradient_fields",
    "compute_laplacian",
    # Storm Identification
    "StormFeature",
    "StormIdentifier",
    "identify_storms_from_pressure",
    "identify_storms_from_wind",
    "calculate_storm_extent",
    # Ensemble Statistics
    "StormEnsembleStats",
    "compute_storm_relative_spread",
    "compute_position_uncertainty",
    "compute_compound_probability",
    "compute_spatial_correlation",
    # Multi-Storm Analysis
    "MultiStormAnalyzer",
    "StormTrack",
    "analyze_storm_interactions",
]
