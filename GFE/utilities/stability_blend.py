"""
Stability and Wind Boosting Utility Module

Meteorological functions for atmospheric stability calculations and
stability-dependent wind adjustments.

This module contains the scientific/domain logic while grid_ops handles
the underlying math operations.

Usage:
    from utilities import stability_blend
    
    # Calculate instability
    instability = stability_blend.calc_sst_instability(sst, t850)
    
    # Boost winds in unstable areas
    boosted = stability_blend.boost_winds_by_stability(
        wind_grid, instability, boost_factor=1.3
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple, Union

import numpy as np
from scipy import ndimage

# Import grid_ops for underlying operations
try:
    from utilities import grid_ops
except ImportError:
    import grid_ops


# =============================================================================
# Constants
# =============================================================================

# Pressure level reference heights (meters)
PRESSURE_HEIGHTS = {
    1000: 111,
    925: 762,
    850: 1457,
    700: 3013,
    500: 5574,
}

# Adiabatic lapse rates (K/m)
DRY_ADIABATIC_LAPSE = 0.0098   # ~9.8 K/km
MOIST_ADIABATIC_LAPSE = 0.0065  # ~6.5 K/km (approximate average)

# Stability thresholds (Kelvin)
STABLE_THRESHOLD = 2.0       # SST - T <= this is stable
UNSTABLE_THRESHOLD = 5.0     # SST - T >= this is unstable
VERY_UNSTABLE_THRESHOLD = 10.0

# CAPE thresholds (J/kg)
CAPE_LOW = 500
CAPE_MODERATE = 1000
CAPE_HIGH = 2000
CAPE_EXTREME = 3000

# Wind boost defaults
DEFAULT_BOOST_FACTOR = 1.25
MAX_BOOST_FACTOR = 1.50
MIN_BOOST_FACTOR = 1.0

# Richardson number thresholds
RICHARDSON_UNSTABLE = 0.0
RICHARDSON_CRITICAL = 0.25


# =============================================================================
# Enums and Data Classes
# =============================================================================

class StabilityClass(Enum):
    """Atmospheric stability classification."""
    VERY_STABLE = "very_stable"
    STABLE = "stable"
    NEUTRAL = "neutral"
    UNSTABLE = "unstable"
    VERY_UNSTABLE = "very_unstable"


@dataclass
class StabilityResult:
    """Complete stability analysis results."""
    instability: np.ndarray          # Raw instability index
    stability_class: np.ndarray      # Classification grid (integer codes)
    boost_factor: np.ndarray         # Calculated boost factor grid
    mixing_potential: np.ndarray     # Vertical mixing potential (0-100)
    description: str                 # Human-readable summary


@dataclass 
class BoostConfig:
    """Configuration for wind boosting."""
    min_factor: float = 1.0          # Minimum boost (stable conditions)
    max_factor: float = 1.35         # Maximum boost (very unstable)
    instability_threshold: float = 3.0  # Start boosting above this
    full_boost_threshold: float = 10.0  # Full boost above this
    use_cape: bool = False           # Include CAPE in calculation
    cape_weight: float = 0.3         # Weight for CAPE component
    smooth_result: bool = True       # Smooth the boost factor grid
    smooth_sigma: float = 1.0        # Gaussian sigma for smoothing


# =============================================================================
# SST-Based Instability (Primary Method)
# =============================================================================

def calc_sst_instability(
    sst: np.ndarray,
    t_level: np.ndarray,
    *,
    level: int = 850,
    method: str = "simple",
) -> np.ndarray:
    """
    Calculate atmospheric instability from SST and upper-level temperature.
    
    The instability index represents how much warmer the ocean surface is
    compared to the air aloft. Larger positive values = more unstable.
    
    Args:
        sst: Sea surface temperature (Kelvin or Celsius)
        t_level: Temperature at pressure level (same units)
        level: Pressure level (850, 925, etc.)
        method: "simple" (just difference) or "lapse" (lapse rate adjusted)
    
    Returns:
        Instability index grid (positive = unstable, negative = stable)
    
    Physical Interpretation:
        > 10: Very unstable - strong convective potential
        5-10: Unstable - good vertical mixing
        2-5: Slightly unstable - some mixing
        -2 to 2: Neutral
        < -2: Stable - suppressed vertical motion
    """
    if method == "simple":
        return sst - t_level
    
    elif method == "lapse":
        # Account for expected dry adiabatic cooling with height
        height_diff = PRESSURE_HEIGHTS.get(level, 1500)
        expected_cooling = height_diff * DRY_ADIABATIC_LAPSE
        
        # Instability = actual difference minus expected
        actual_diff = sst - t_level
        return actual_diff - expected_cooling
    
    else:
        raise ValueError(f"Unknown method: {method}")


def calc_dual_level_instability(
    sst: np.ndarray,
    t850: np.ndarray,
    t925: np.ndarray,
    *,
    weights: Tuple[float, float] = (0.6, 0.4),
) -> np.ndarray:
    """
    Calculate instability using both 850mb and 925mb temperatures.
    
    Uses weighted combination of both levels for more robust estimate.
    The 925mb level is closer to the surface, while 850mb captures
    the lower troposphere.
    
    Args:
        sst: Sea surface temperature
        t850: Temperature at 850mb
        t925: Temperature at 925mb
        weights: Weights for (850mb, 925mb) instabilities
    
    Returns:
        Combined instability index
    """
    inst_850 = calc_sst_instability(sst, t850, level=850)
    inst_925 = calc_sst_instability(sst, t925, level=925)
    
    w850, w925 = weights
    total = w850 + w925
    
    return (w850 * inst_850 + w925 * inst_925) / total


# =============================================================================
# CAPE-Based Instability
# =============================================================================

def calc_cape_instability(
    cape: np.ndarray,
    *,
    normalize: bool = True,
    max_cape: float = 4000.0,
) -> np.ndarray:
    """
    Convert CAPE to normalized instability index.
    
    Args:
        cape: Convective Available Potential Energy (J/kg)
        normalize: If True, return 0-10 scale. If False, return raw CAPE.
        max_cape: CAPE value corresponding to maximum instability
    
    Returns:
        Instability index (0-10 if normalized, raw CAPE otherwise)
    """
    if not normalize:
        return cape.copy()
    
    # Map CAPE to 0-10 scale with diminishing returns at high values
    # Using sqrt to compress high values
    normalized = np.sqrt(np.maximum(cape, 0) / max_cape) * 10.0
    return np.clip(normalized, 0.0, 10.0)


def calc_combined_instability(
    sst_instability: np.ndarray,
    cape: Optional[np.ndarray] = None,
    *,
    sst_weight: float = 0.7,
    cape_weight: float = 0.3,
) -> np.ndarray:
    """
    Combine SST-based and CAPE-based instability.
    
    When both measures agree, confidence is higher.
    SST instability captures marine boundary layer dynamics.
    CAPE captures deep convective potential.
    
    Args:
        sst_instability: From calc_sst_instability (any scale)
        cape: CAPE values (J/kg) - will be normalized
        sst_weight: Weight for SST component
        cape_weight: Weight for CAPE component
    
    Returns:
        Combined instability index
    """
    if cape is None or cape_weight == 0:
        return sst_instability.copy()
    
    cape_inst = calc_cape_instability(cape, normalize=True)
    
    # Normalize SST instability to similar scale (assume -5 to 15 range)
    sst_norm = np.clip((sst_instability + 5) / 2, 0, 10)
    
    total_weight = sst_weight + cape_weight
    combined = (sst_weight * sst_norm + cape_weight * cape_inst) / total_weight
    
    return combined


# =============================================================================
# Stability Classification
# =============================================================================

def classify_stability(
    instability: np.ndarray,
    *,
    thresholds: Optional[Dict[str, float]] = None,
) -> np.ndarray:
    """
    Classify instability into discrete stability categories.
    
    Args:
        instability: Instability index grid
        thresholds: Custom thresholds dict with keys:
                   very_stable, stable, unstable, very_unstable
    
    Returns:
        Integer grid where:
            0 = very stable
            1 = stable  
            2 = neutral
            3 = unstable
            4 = very unstable
    """
    if thresholds is None:
        thresholds = {
            "very_stable": -5.0,
            "stable": -2.0,
            "unstable": 5.0,
            "very_unstable": 10.0,
        }
    
    classes = np.full_like(instability, 2, dtype=np.int32)  # Default neutral
    
    classes = np.where(instability <= thresholds["very_stable"], 0, classes)
    classes = np.where(
        (instability > thresholds["very_stable"]) & 
        (instability <= thresholds["stable"]), 
        1, classes
    )
    classes = np.where(
        (instability >= thresholds["unstable"]) & 
        (instability < thresholds["very_unstable"]), 
        3, classes
    )
    classes = np.where(instability >= thresholds["very_unstable"], 4, classes)
    
    return classes


def stability_to_text(stability_class: int) -> str:
    """Convert stability class code to text description."""
    labels = {
        0: "Very Stable",
        1: "Stable",
        2: "Neutral",
        3: "Unstable",
        4: "Very Unstable",
    }
    return labels.get(stability_class, "Unknown")


# =============================================================================
# Wind Boosting
# =============================================================================

def calc_boost_factor(
    instability: np.ndarray,
    config: Optional[BoostConfig] = None,
    *,
    cape: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Calculate wind boost factor from instability.
    
    Maps instability to a multiplicative boost factor that can be
    applied to wind speeds.
    
    Args:
        instability: Instability index
        config: BoostConfig with parameters
        cape: Optional CAPE grid for additional consideration
    
    Returns:
        Boost factor grid (values typically 1.0 - 1.5)
    """
    if config is None:
        config = BoostConfig()
    
    # Base boost from instability
    inst_range = config.full_boost_threshold - config.instability_threshold
    if inst_range <= 0:
        inst_range = 7.0  # Default range
    
    # Normalize instability to 0-1 range
    norm_inst = (instability - config.instability_threshold) / inst_range
    norm_inst = np.clip(norm_inst, 0.0, 1.0)
    
    # Map to boost range
    boost_range = config.max_factor - config.min_factor
    boost = config.min_factor + norm_inst * boost_range
    
    # Optional CAPE contribution
    if config.use_cape and cape is not None:
        cape_norm = np.clip(cape / CAPE_HIGH, 0.0, 1.0)
        cape_boost = cape_norm * boost_range * config.cape_weight
        boost = boost + cape_boost
    
    # Ensure within bounds
    boost = np.clip(boost, config.min_factor, config.max_factor)
    
    # Optional smoothing
    if config.smooth_result:
        boost = grid_ops.smooth_gaussian(boost, sigma=config.smooth_sigma)
    
    return boost


def boost_winds_scalar(
    wind_speed: np.ndarray,
    boost_factor: np.ndarray,
    *,
    max_boost_speed: Optional[float] = None,
) -> np.ndarray:
    """
    Apply boost factor to wind speed grid.
    
    Args:
        wind_speed: Wind speed grid
        boost_factor: Multiplicative boost factor (e.g., 1.0-1.5)
        max_boost_speed: Optional cap on boosted speed
    
    Returns:
        Boosted wind speed grid
    """
    boosted = wind_speed * boost_factor
    
    if max_boost_speed is not None:
        boosted = np.minimum(boosted, max_boost_speed)
    
    return boosted


def boost_winds_vector(
    wind_grid: Tuple[np.ndarray, np.ndarray],
    boost_factor: np.ndarray,
    *,
    max_boost_speed: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply boost factor to vector wind grid (magnitude only).
    
    Direction is preserved; only magnitude is boosted.
    
    Args:
        wind_grid: Tuple of (magnitude, direction)
        boost_factor: Multiplicative boost factor
        max_boost_speed: Optional cap on boosted speed
    
    Returns:
        Boosted (magnitude, direction) tuple
    """
    mag, dir_ = wind_grid
    boosted_mag = boost_winds_scalar(mag, boost_factor, max_boost_speed=max_boost_speed)
    return (boosted_mag, dir_.copy())


def boost_winds_by_stability(
    wind_grid: Union[np.ndarray, Tuple[np.ndarray, np.ndarray]],
    instability: np.ndarray,
    *,
    config: Optional[BoostConfig] = None,
    cape: Optional[np.ndarray] = None,
    mask: Optional[np.ndarray] = None,
) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """
    Boost winds based on atmospheric stability (main entry point).
    
    This is the primary function for stability-dependent wind adjustment.
    
    Args:
        wind_grid: Scalar speed or (magnitude, direction) vector
        instability: Instability index from calc_sst_instability
        config: BoostConfig parameters
        cape: Optional CAPE for combined boosting
        mask: Optional mask - only boost where True
    
    Returns:
        Boosted wind (same type as input)
    
    Example:
        >>> instability = calc_sst_instability(sst, t850)
        >>> boosted_wind = boost_winds_by_stability(
        ...     wind_grid, instability,
        ...     config=BoostConfig(max_factor=1.4)
        ... )
    """
    boost_factor = calc_boost_factor(instability, config, cape=cape)
    
    # Apply mask if provided
    if mask is not None:
        boost_factor = np.where(mask, boost_factor, 1.0)
    
    # Detect if vector or scalar
    if isinstance(wind_grid, tuple) and len(wind_grid) == 2:
        return boost_winds_vector(wind_grid, boost_factor)
    else:
        return boost_winds_scalar(wind_grid, boost_factor)


# =============================================================================
# Advanced Stability Metrics
# =============================================================================

def calc_bulk_richardson(
    theta_sfc: np.ndarray,
    theta_level: np.ndarray,
    wind_speed_level: np.ndarray,
    *,
    level: int = 850,
    gravity: float = 9.81,
) -> np.ndarray:
    """
    Calculate bulk Richardson number.
    
    Ri = (g * dTheta * dz) / (Theta_mean * dU^2)
    
    Ri < 0: Unstable (convective)
    0 < Ri < 0.25: Dynamically unstable
    Ri > 0.25: Stable
    
    Args:
        theta_sfc: Surface potential temperature (K)
        theta_level: Potential temperature at level (K)
        wind_speed_level: Wind speed at level (m/s)
        level: Pressure level for height
        gravity: Gravitational acceleration
    
    Returns:
        Richardson number grid
    """
    dz = PRESSURE_HEIGHTS.get(level, 1500)
    dtheta = theta_level - theta_sfc
    theta_mean = (theta_sfc + theta_level) / 2.0
    
    # Avoid division by zero
    wind_sq = np.maximum(wind_speed_level**2, 0.1)
    
    ri = (gravity * dtheta * dz) / (theta_mean * wind_sq)
    
    return ri


def calc_mixing_efficiency(
    instability: np.ndarray,
    wind_speed: np.ndarray,
    *,
    wind_threshold: float = 5.0,
) -> np.ndarray:
    """
    Estimate vertical mixing efficiency.
    
    Combines instability with wind-driven mechanical mixing.
    
    Args:
        instability: Instability index
        wind_speed: Surface wind speed
        wind_threshold: Wind speed where mechanical mixing starts
    
    Returns:
        Mixing efficiency (0-100%)
    """
    # Thermal component (from instability)
    thermal = np.clip(instability / 10.0, -0.5, 1.0)
    thermal = (thermal + 0.5) / 1.5 * 0.6  # Scale to 0-0.6 contribution
    
    # Mechanical component (from wind)
    mechanical = np.clip((wind_speed - wind_threshold) / 15.0, 0, 1) * 0.4
    
    efficiency = (thermal + mechanical) * 100.0
    return np.clip(efficiency, 0.0, 100.0)


def calc_convective_index(
    sst: np.ndarray,
    t850: np.ndarray,
    t500: Optional[np.ndarray] = None,
    rh850: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Calculate convective potential index.
    
    Enhanced index that considers multiple factors:
    - SST-based instability (primary)
    - Mid-level lapse rate (if T500 available)
    - Moisture availability (if RH850 available)
    
    Args:
        sst: Sea surface temperature
        t850: Temperature at 850mb
        t500: Optional temperature at 500mb
        rh850: Optional relative humidity at 850mb (%)
    
    Returns:
        Convective index (0-100)
    """
    # Base instability
    inst = calc_sst_instability(sst, t850)
    base_index = np.clip(inst / 15.0, 0, 1) * 40.0  # Up to 40 points
    
    # Mid-level lapse rate contribution
    if t500 is not None:
        lapse_rate = (t850 - t500) / (PRESSURE_HEIGHTS[500] - PRESSURE_HEIGHTS[850])
        steep_lapse = (lapse_rate - MOIST_ADIABATIC_LAPSE) / 0.003
        lapse_contrib = np.clip(steep_lapse, 0, 1) * 30.0  # Up to 30 points
    else:
        lapse_contrib = 15.0  # Neutral value
    
    # Moisture contribution
    if rh850 is not None:
        moisture_contrib = np.clip(rh850 / 100.0, 0, 1) * 30.0  # Up to 30 points
    else:
        moisture_contrib = 15.0  # Neutral value
    
    total = base_index + lapse_contrib + moisture_contrib
    return np.clip(total, 0.0, 100.0)


# =============================================================================
# Marine-Specific Functions
# =============================================================================

def calc_air_sea_temperature_diff(
    sst: np.ndarray,
    t2m: np.ndarray,
) -> np.ndarray:
    """
    Calculate air-sea temperature difference.
    
    Positive = SST warmer than air (heat flux to atmosphere)
    Negative = SST cooler than air (stable marine layer)
    """
    return sst - t2m


def calc_marine_instability_index(
    sst: np.ndarray,
    t2m: np.ndarray,
    t850: np.ndarray,
    *,
    include_surface: bool = True,
) -> np.ndarray:
    """
    Calculate marine-specific instability index.
    
    Combines near-surface air-sea temperature difference with
    lower-tropospheric stability.
    
    Args:
        sst: Sea surface temperature
        t2m: 2-meter air temperature
        t850: Temperature at 850mb
        include_surface: Include air-sea diff in calculation
    
    Returns:
        Marine instability index
    """
    # Lower troposphere instability
    lower_inst = calc_sst_instability(sst, t850)
    
    if include_surface:
        # Surface heat flux potential
        air_sea_diff = calc_air_sea_temperature_diff(sst, t2m)
        # Weight surface more heavily
        return 0.6 * lower_inst + 0.4 * air_sea_diff * 2.0
    else:
        return lower_inst


def estimate_wave_enhancement(
    wind_speed: np.ndarray,
    instability: np.ndarray,
    *,
    base_factor: float = 1.0,
    max_factor: float = 1.2,
) -> np.ndarray:
    """
    Estimate wave height enhancement from instability.
    
    Unstable conditions enhance air-sea momentum transfer,
    which can increase wave growth rates.
    
    Args:
        wind_speed: Wind speed grid
        instability: Instability index
        base_factor: Factor in stable conditions
        max_factor: Maximum factor in very unstable
    
    Returns:
        Wave enhancement factor (multiplicative)
    """
    # Enhanced momentum transfer in unstable conditions
    norm_inst = np.clip(instability / 10.0, 0, 1)
    factor = base_factor + norm_inst * (max_factor - base_factor)
    
    # Enhancement is stronger at higher wind speeds
    wind_factor = np.clip(wind_speed / 25.0, 0.5, 1.0)
    factor = base_factor + (factor - base_factor) * wind_factor
    
    return factor


# =============================================================================
# Complete Analysis Function
# =============================================================================

def analyze_stability(
    sst: np.ndarray,
    t850: np.ndarray,
    *,
    t925: Optional[np.ndarray] = None,
    cape: Optional[np.ndarray] = None,
    boost_config: Optional[BoostConfig] = None,
) -> StabilityResult:
    """
    Perform complete stability analysis.
    
    This is the high-level entry point for stability analysis,
    returning all relevant metrics in a single result object.
    
    Args:
        sst: Sea surface temperature
        t850: Temperature at 850mb
        t925: Optional temperature at 925mb
        cape: Optional CAPE
        boost_config: Configuration for boost calculation
    
    Returns:
        StabilityResult with all metrics
    """
    # Calculate instability
    if t925 is not None:
        instability = calc_dual_level_instability(sst, t850, t925)
    else:
        instability = calc_sst_instability(sst, t850)
    
    # Optionally incorporate CAPE
    if cape is not None:
        instability = calc_combined_instability(instability, cape)
    
    # Classify
    stability_class = classify_stability(instability)
    
    # Calculate boost factor
    boost_factor = calc_boost_factor(instability, boost_config, cape=cape)
    
    # Estimate mixing potential
    # (simplified - would need wind for full calc)
    mixing_potential = np.clip(instability / 10.0, 0, 1) * 100.0
    
    # Generate description
    mean_inst = float(np.nanmean(instability))
    if mean_inst > 7:
        description = "Very unstable conditions - strong vertical mixing expected"
    elif mean_inst > 4:
        description = "Unstable conditions - enhanced momentum transfer likely"
    elif mean_inst > 1:
        description = "Slightly unstable - some vertical mixing"
    elif mean_inst > -2:
        description = "Near-neutral stability"
    else:
        description = "Stable conditions - suppressed vertical motion"
    
    return StabilityResult(
        instability=instability,
        stability_class=stability_class,
        boost_factor=boost_factor,
        mixing_potential=mixing_potential,
        description=description,
    )


# =============================================================================
# Fog / Low Visibility Support
# =============================================================================

def calc_fog_potential(
    sst: np.ndarray,
    t2m: np.ndarray,
    rh: np.ndarray,
    *,
    sst_t2m_threshold: float = -2.0,
    rh_threshold: float = 85.0,
) -> np.ndarray:
    """
    Calculate sea fog potential.
    
    Advection fog forms when warm, moist air moves over cooler water.
    
    Args:
        sst: Sea surface temperature
        t2m: 2-meter air temperature
        rh: Relative humidity (%)
        sst_t2m_threshold: SST-T2m threshold for fog (negative = SST cooler)
        rh_threshold: RH threshold for fog
    
    Returns:
        Fog potential (0-100)
    """
    air_sea_diff = sst - t2m
    
    # Fog favored when SST < air temp (cold water)
    temp_factor = np.clip(-air_sea_diff / 5.0, 0, 1)
    
    # High RH required
    rh_factor = np.clip((rh - rh_threshold) / (100 - rh_threshold), 0, 1)
    
    # Combined potential
    potential = (temp_factor * 0.5 + rh_factor * 0.5) * 100.0
    
    return np.clip(potential, 0.0, 100.0)


def suppress_boost_in_stable(
    boost_factor: np.ndarray,
    instability: np.ndarray,
    *,
    stable_threshold: float = 0.0,
    suppression_factor: float = 0.5,
) -> np.ndarray:
    """
    Reduce boost factor in stable conditions.
    
    In stable marine boundary layers, momentum coupling is reduced,
    so model winds may already be reasonable or even too high.
    
    Args:
        boost_factor: Calculated boost factor
        instability: Instability index
        stable_threshold: Below this, apply suppression
        suppression_factor: How much to reduce boost (0=no boost, 1=full boost)
    
    Returns:
        Adjusted boost factor
    """
    stable_mask = instability < stable_threshold
    
    # Reduce boost toward 1.0 in stable areas
    adjusted = np.where(
        stable_mask,
        1.0 + (boost_factor - 1.0) * suppression_factor,
        boost_factor
    )
    
    return adjusted


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Data classes and enums
    "StabilityClass",
    "StabilityResult",
    "BoostConfig",
    
    # SST-based instability
    "calc_sst_instability",
    "calc_dual_level_instability",
    
    # CAPE-based instability  
    "calc_cape_instability",
    "calc_combined_instability",
    
    # Classification
    "classify_stability",
    "stability_to_text",
    
    # Wind boosting
    "calc_boost_factor",
    "boost_winds_scalar",
    "boost_winds_vector",
    "boost_winds_by_stability",
    
    # Advanced metrics
    "calc_bulk_richardson",
    "calc_mixing_efficiency",
    "calc_convective_index",
    
    # Marine-specific
    "calc_air_sea_temperature_diff",
    "calc_marine_instability_index",
    "estimate_wave_enhancement",
    
    # Complete analysis
    "analyze_stability",
    
    # Fog support
    "calc_fog_potential",
    "suppress_boost_in_stable",
    
    # Constants (for reference)
    "PRESSURE_HEIGHTS",
    "CAPE_LOW",
    "CAPE_MODERATE", 
    "CAPE_HIGH",
    "CAPE_EXTREME",
    "DEFAULT_BOOST_FACTOR",
    "MAX_BOOST_FACTOR",
]
