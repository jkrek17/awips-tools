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
# Marine storm identification thresholds
# ---------------------------------------------------------------------------

MARINE_STORM_THRESHOLDS: Dict[str, float] = {
    # Wind speed thresholds (knots)
    "gale_min_kt": 34.0,       # Gale force (BF 8)
    "storm_min_kt": 48.0,      # Storm force (BF 10)
    "hurricane_min_kt": 64.0,  # Hurricane force (BF 12)
    "violent_storm_kt": 56.0,  # Violent storm (BF 11)
    
    # Pressure thresholds (hPa)
    "deep_low_hpa": 980.0,     # Deep low pressure
    "intense_low_hpa": 960.0,  # Intense low pressure
    "extreme_low_hpa": 940.0,  # Extreme low pressure
    "standard_pressure_hpa": 1013.25,
    
    # Storm identification parameters
    "min_pressure_anomaly_hpa": 4.0,    # Minimum depression for detection
    "min_storm_separation_km": 500.0,   # Minimum center separation
    "storm_search_radius_km": 800.0,    # Radius for feature extraction
    "smoothing_scale_km": 100.0,        # Noise reduction scale
    
    # Vorticity thresholds (1/s)
    "cyclonic_vorticity_min": 1e-5,     # Minimum for storm detection
    "strong_vorticity": 3e-5,           # Strong cyclonic circulation
    
    # Wave thresholds (feet)
    "rough_seas_ft": 8.0,      # Rough seas
    "very_rough_ft": 13.0,     # Very rough seas  
    "high_seas_ft": 20.0,      # High seas
    "phenomenal_ft": 46.0,     # Phenomenal seas
}

MARINE_INTERACTION_THRESHOLDS: Dict[str, float] = {
    # Storm interaction distances (km)
    "fujiwhara_interaction_km": 1400.0,  # Potential Fujiwhara effect
    "strong_interaction_km": 500.0,      # Strong steering interaction
    "moderate_interaction_km": 800.0,    # Moderate interaction
    "weak_interaction_km": 1200.0,       # Weak interaction
    
    # Risk index weights
    "n_storm_risk_weight": 0.4,          # Per-storm contribution
    "intensity_risk_weight": 0.3,        # Intensity contribution
    "proximity_risk_weight": 0.2,        # Interaction contribution
    "area_risk_weight": 0.1,             # Area coverage contribution
}

MARINE_ENSEMBLE_THRESHOLDS: Dict[str, float] = {
    # Position uncertainty bounds (km)
    "low_position_uncertainty_km": 100.0,
    "moderate_position_uncertainty_km": 200.0,
    "high_position_uncertainty_km": 400.0,
    
    # Intensity spread bounds
    "low_wind_spread_kt": 5.0,
    "moderate_wind_spread_kt": 15.0,
    "high_wind_spread_kt": 25.0,
    
    "low_pressure_spread_hpa": 4.0,
    "moderate_pressure_spread_hpa": 10.0,
    "high_pressure_spread_hpa": 20.0,
    
    # Ensemble agreement thresholds
    "strong_agreement_fraction": 0.8,    # 80% of members agree
    "moderate_agreement_fraction": 0.6,  # 60% agree
    "weak_agreement_fraction": 0.5,      # 50% agree
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


def get_model_wx_smoothing_defaults() -> Dict[str, float]:
    """Return smoothing defaults for ModelWx (legacy values)."""

    return deepcopy(MODEL_WX_SMOOTHING_DEFAULTS)


def get_model_wx_fog_thresholds_nm() -> Dict[str, float]:
    """Return fog thresholds for ModelWx in nautical miles."""

    return deepcopy(MODEL_WX_FOG_THRESHOLDS_NM)


def get_marine_storm_thresholds() -> Dict[str, float]:
    """Return marine storm identification thresholds."""

    return deepcopy(MARINE_STORM_THRESHOLDS)


def get_marine_interaction_thresholds() -> Dict[str, float]:
    """Return marine storm interaction thresholds."""

    return deepcopy(MARINE_INTERACTION_THRESHOLDS)


def get_marine_ensemble_thresholds() -> Dict[str, float]:
    """Return marine ensemble analysis thresholds."""

    return deepcopy(MARINE_ENSEMBLE_THRESHOLDS)


def beaufort_scale(wind_kt: float) -> int:
    """
    Convert wind speed in knots to Beaufort scale number.
    
    Args:
        wind_kt: Wind speed in knots.
        
    Returns:
        Beaufort scale number (0-12).
    """
    thresholds = [1, 4, 7, 11, 17, 22, 28, 34, 41, 48, 56, 64]
    for bf, thresh in enumerate(thresholds):
        if wind_kt < thresh:
            return bf
    return 12


def wave_state_description(wave_height_ft: float) -> str:
    """
    Get WMO sea state description from wave height.
    
    Args:
        wave_height_ft: Significant wave height in feet.
        
    Returns:
        Sea state description string.
    """
    if wave_height_ft < 0.33:
        return "Calm (glassy)"
    elif wave_height_ft < 1.0:
        return "Calm (rippled)"
    elif wave_height_ft < 1.6:
        return "Smooth"
    elif wave_height_ft < 4.0:
        return "Slight"
    elif wave_height_ft < 8.0:
        return "Moderate"
    elif wave_height_ft < 13.0:
        return "Rough"
    elif wave_height_ft < 20.0:
        return "Very rough"
    elif wave_height_ft < 30.0:
        return "High"
    elif wave_height_ft < 46.0:
        return "Very high"
    else:
        return "Phenomenal"


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
    "MODEL_WX_SMOOTHING_DEFAULTS",
    "MODEL_WX_FOG_THRESHOLDS_NM",
    "get_model_wx_qpf_thresholds",
    "get_model_wx_convection",
    "get_model_wx_smoothing_defaults",
    "get_model_wx_fog_thresholds_nm",
    # Marine storm thresholds
    "MARINE_STORM_THRESHOLDS",
    "MARINE_INTERACTION_THRESHOLDS",
    "MARINE_ENSEMBLE_THRESHOLDS",
    "get_marine_storm_thresholds",
    "get_marine_interaction_thresholds",
    "get_marine_ensemble_thresholds",
    "beaufort_scale",
    "wave_state_description",
]

