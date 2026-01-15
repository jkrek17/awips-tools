"""
Shared thresholds and conversion helpers for Smart Tools.

All Smart Tools should import values from this module instead of
duplicating constants in each script. Keeping numbers here ensures that
operational tweaks (fog visibility, CAPE cutoffs, smoothing defaults,
unit conversions, etc.) only require a single change.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Dict

# ---------------------------------------------------------------------------
# Precipitation thresholds (3-hour window by default)
# ---------------------------------------------------------------------------

PRECIP_INTENSITY_INCHES: Dict[str, float] = {
    "minimum": 0.01,
    "light": 0.10,
    "moderate": 0.50,
    "heavy": 1.00,
}

PRECIP_COVERAGE_INCHES: Dict[str, float] = {
    "wide": 1.00,
    "numerous": 0.50,
    "scattered": 0.10,
}

PRECIP_PROBABILITY_INCHES: Dict[str, float] = {
    "definite": 1.00,
    "likely": 0.50,
    "chance": 0.10,
}

# ---------------------------------------------------------------------------
# CAPE / convection thresholds (J/kg)
# ---------------------------------------------------------------------------

CAPE_THRESHOLDS: Dict[str, float] = {
    "thunder_min": 500.0,
    "severe_min": 3000.0,
    "high": 2000.0,
    "moderate": 1000.0,
}

# ---------------------------------------------------------------------------
# Fog thresholds
# ---------------------------------------------------------------------------

FOG_THRESHOLDS: Dict[str, float] = {
    "relative_humidity_min": 85.0,
    "visibility_default_sm": 3.0,
    "visibility_min_sm": 0.5,
    "visibility_max_sm": 6.0,
}

# ---------------------------------------------------------------------------
# Smoothing defaults
# ---------------------------------------------------------------------------

SMOOTHING_DEFAULTS: Dict[str, float] = {
    "recommended": 2.0,
    "min": 0.0,
    "max": 5.0,
    "sigma": 0.7,
}

# ---------------------------------------------------------------------------
# ModelWx-specific thresholds (mirrors legacy simpleModelWx defaults)
# ---------------------------------------------------------------------------

MODEL_WX_QPF_THRESHOLDS: Dict[str, float] = {
    "minimum_in": 0.01,
    "light_in": 0.05,
    "moderate_in": 0.25,
    "heavy_in": 0.50,
    "coverage_wide_in": 0.25,
    "coverage_numerous_in": 0.10,
    "coverage_scattered_in": 0.03,
    "prob_definite_in": 0.25,
    "prob_likely_in": 0.10,
    "prob_chance_in": 0.03,
    "severe_with_thunder_in": 1.0,
}

MODEL_WX_CONVECTION: Dict[str, float] = {
    "convective_index_threshold": 7.0,
}

MODEL_WX_TEXTURE: Dict[str, float] = {
    "window": 9,
    "stratiform_max": 0.4,
    "convective_min": 0.8,
    "cape_stratiform_max": 300.0,
    "cape_convective_min": 800.0,
    "eps": 1e-6,
}

MODEL_WX_SMOOTHING_DEFAULTS: Dict[str, float] = {
    "recommended": 10.0,
    "min": 0.0,
    "max": 20.0,
    "sigma": 0.7,
}

# Visibility defaults are stored in nautical miles to align with project units
_SM_TO_NM = 0.868976
MODEL_WX_FOG_THRESHOLDS_NM: Dict[str, float] = {
    "visibility_default_nm": 3.0 * _SM_TO_NM,
    "visibility_min_nm": 0.5 * _SM_TO_NM,
    "visibility_max_nm": 6.0 * _SM_TO_NM,
    "relative_humidity_min_pct": 85.0,
}

# ---------------------------------------------------------------------------
# Wind boost defaults (for instability-based boosting)
# ---------------------------------------------------------------------------

WIND_BOOST_DEFAULTS: Dict[str, float] = {
    "boost_scale": 0.02,      # Boost per degree F of instability
    "max_boost": 0.25,        # Maximum 25% boost cap
    "min_instability": 2.0,   # Minimum instability (F) to trigger boost
}

# GFS alternate wind levels for boosting (higher levels have faster winds)
GFS_ALT_WIND_LEVELS = ["30FHAG", "50FHAG", "80FHAG", "100FHAG"]

# ---------------------------------------------------------------------------
# Grid clipping defaults
# ---------------------------------------------------------------------------

DIAGNOSTIC_CLIPPING = {
    "qpf_max_in": 10.0,
    "cape_max": 8000.0,
    "temp_min_f": -50.0,
    "temp_max_f": 150.0,
    "rh_min_pct": 0.0,
    "rh_max_pct": 100.0,
    "vis_min_nm": 0.0,
    "vis_max_nm": 8.0,
    "wind_min_kt": 0.0,
    "wind_max_kt": 150.0,
}

# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

KNOTS_TO_MPS = 0.514444
MPS_TO_KNOTS = 1.0 / KNOTS_TO_MPS
METERS_TO_NM = 1.0 / 1852.0
NM_TO_METERS = 1852.0
MM_TO_INCHES = 25.4
INCHES_TO_MM = 1.0 / MM_TO_INCHES
CELSIUS_TO_F_MULT = 9.0 / 5.0
CELSIUS_TO_F_ADD = 32.0
KELVIN_TO_CELSIUS = -273.15


def to_knots(speed_mps):
    """Convert meters/second to knots."""

    return speed_mps * MPS_TO_KNOTS


def to_mps(speed_knots):
    """Convert knots to meters/second."""

    return speed_knots * KNOTS_TO_MPS


def meters_to_nm(distance_m):
    """Convert meters to nautical miles."""

    return distance_m * METERS_TO_NM


def nm_to_meters(distance_nm):
    """Convert nautical miles to meters."""

    return distance_nm * NM_TO_METERS


def mm_to_inches(value_mm):
    """Convert millimeters to inches."""

    return value_mm / MM_TO_INCHES


def inches_to_mm(value_in):
    """Convert inches to millimeters."""

    return value_in * MM_TO_INCHES


def c_to_f(temp_c):
    """Convert Celsius to Fahrenheit."""

    return temp_c * CELSIUS_TO_F_MULT + CELSIUS_TO_F_ADD


def f_to_c(temp_f):
    """Convert Fahrenheit to Celsius."""

    return (temp_f - CELSIUS_TO_F_ADD) / CELSIUS_TO_F_MULT


def k_to_c(temp_k):
    """Convert Kelvin to Celsius."""

    return temp_k + KELVIN_TO_CELSIUS


def get_precip_intensity_thresholds() -> Dict[str, float]:
    return deepcopy(PRECIP_INTENSITY_INCHES)


def get_precip_coverage_thresholds() -> Dict[str, float]:
    return deepcopy(PRECIP_COVERAGE_INCHES)


def get_precip_probability_thresholds() -> Dict[str, float]:
    return deepcopy(PRECIP_PROBABILITY_INCHES)


def get_cape_thresholds() -> Dict[str, float]:
    return deepcopy(CAPE_THRESHOLDS)


def get_fog_thresholds() -> Dict[str, float]:
    return deepcopy(FOG_THRESHOLDS)


def get_smoothing_defaults() -> Dict[str, float]:
    return deepcopy(SMOOTHING_DEFAULTS)


def get_diagnostic_clipping() -> Dict[str, float]:
    return deepcopy(DIAGNOSTIC_CLIPPING)


def get_wind_boost_defaults() -> Dict[str, float]:
    return deepcopy(WIND_BOOST_DEFAULTS)


def get_gfs_alt_wind_levels():
    return list(GFS_ALT_WIND_LEVELS)


def get_model_wx_qpf_thresholds() -> Dict[str, float]:
    """Return ModelWx precipitation thresholds (inches)."""

    return deepcopy(MODEL_WX_QPF_THRESHOLDS)


def get_model_wx_convection() -> Dict[str, float]:
    """Return ModelWx convection thresholds."""

    return deepcopy(MODEL_WX_CONVECTION)


def get_model_wx_texture() -> Dict[str, float]:
    """Return ModelWx QPF texture thresholds."""

    return deepcopy(MODEL_WX_TEXTURE)


def get_model_wx_smoothing_defaults() -> Dict[str, float]:
    """Return smoothing defaults for ModelWx (legacy values)."""

    return deepcopy(MODEL_WX_SMOOTHING_DEFAULTS)


def get_model_wx_fog_thresholds_nm() -> Dict[str, float]:
    """Return fog thresholds for ModelWx in nautical miles."""

    return deepcopy(MODEL_WX_FOG_THRESHOLDS_NM)


__all__ = [
    "PRECIP_INTENSITY_INCHES",
    "PRECIP_COVERAGE_INCHES",
    "PRECIP_PROBABILITY_INCHES",
    "CAPE_THRESHOLDS",
    "FOG_THRESHOLDS",
    "SMOOTHING_DEFAULTS",
    "WIND_BOOST_DEFAULTS",
    "GFS_ALT_WIND_LEVELS",
    "DIAGNOSTIC_CLIPPING",
    "to_knots",
    "to_mps",
    "meters_to_nm",
    "nm_to_meters",
    "mm_to_inches",
    "inches_to_mm",
    "c_to_f",
    "f_to_c",
    "k_to_c",
    "get_precip_intensity_thresholds",
    "get_precip_coverage_thresholds",
    "get_precip_probability_thresholds",
    "get_cape_thresholds",
    "get_fog_thresholds",
    "get_smoothing_defaults",
    "get_diagnostic_clipping",
    "get_wind_boost_defaults",
    "get_gfs_alt_wind_levels",
    "MODEL_WX_QPF_THRESHOLDS",
    "MODEL_WX_CONVECTION",
    "MODEL_WX_TEXTURE",
    "MODEL_WX_SMOOTHING_DEFAULTS",
    "MODEL_WX_FOG_THRESHOLDS_NM",
    "get_model_wx_qpf_thresholds",
    "get_model_wx_convection",
    "get_model_wx_texture",
    "get_model_wx_smoothing_defaults",
    "get_model_wx_fog_thresholds_nm",
]

