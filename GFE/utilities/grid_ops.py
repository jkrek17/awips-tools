"""
Grid Operations Utility Module

Low-level grid manipulation functions for blending, smoothing, and masking.
These are pure functions with no meteorological knowledge - just math on grids.

All functions expect numpy arrays and return numpy arrays.

Usage:
    from utilities import grid_ops
    
    # Blend multiple model grids
    blended = grid_ops.blend_scalar([gfs, ecmwf, cmc], weights=[0.5, 0.3, 0.2])
    
    # Ensemble statistics
    spread = grid_ops.ensemble_spread(models)
    confidence = grid_ops.ensemble_confidence(models)
    
    # Probabilities
    prob_gale = grid_ops.prob_exceeds(wind_models, 34.0)
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from scipy import ndimage

try:
    from scipy import stats as scipy_stats
except ImportError:
    scipy_stats = None


# =============================================================================
# Types and Constants
# =============================================================================

# Type aliases for clarity
ScalarGrid = np.ndarray                      # 2D array of floats
VectorGrid = Tuple[np.ndarray, np.ndarray]   # (magnitude, direction) each 2D
MaskGrid = np.ndarray                        # 2D array of bools


class BlendStrategy(Enum):
    """Available strategies for blending multiple grids."""
    
    WEIGHTED_MEAN = "mean"      # Standard weighted average
    MAXIMUM = "max"             # Take max value at each point
    MINIMUM = "min"             # Take min value (good for visibility)
    MEDIAN = "median"           # Median value (outlier resistant)


# Default smoothing parameters
DEFAULT_SIGMA = 0.7
DEFAULT_TRUNCATE = 4.0  # Standard deviations before cutoff


# =============================================================================
# Weight Normalization
# =============================================================================

def normalize_weights(
    weights: Sequence[float],
    *,
    allow_negative: bool = False,
) -> np.ndarray:
    """
    Normalize weights to sum to 1.0.
    
    Args:
        weights: Sequence of weight values
        allow_negative: If True, allow negative weights (for difference blending)
    
    Returns:
        Normalized weights as numpy array
    
    Raises:
        ValueError: If weights sum to zero or invalid
    """
    weights = np.array(weights, dtype=float)
    
    if not allow_negative and np.any(weights < 0):
        raise ValueError("Negative weights not allowed (set allow_negative=True)")
    
    total = np.sum(weights)
    if np.abs(total) < 1e-10:
        raise ValueError("Weights cannot sum to zero")
    
    return weights / total


def filter_valid_grids(
    grids: Sequence[Optional[np.ndarray]],
    weights: Sequence[float],
) -> Tuple[List[np.ndarray], np.ndarray]:
    """
    Filter out None grids and their corresponding weights.
    
    Returns:
        Tuple of (valid_grids, valid_weights)
    """
    valid_grids = []
    valid_weights = []
    
    for grid, weight in zip(grids, weights):
        if grid is not None and weight != 0:
            valid_grids.append(grid)
            valid_weights.append(weight)
    
    return valid_grids, np.array(valid_weights)


# =============================================================================
# Scalar Blending
# =============================================================================

def blend_scalar(
    grids: Sequence[np.ndarray],
    weights: Optional[Sequence[float]] = None,
    *,
    strategy: Union[BlendStrategy, str] = BlendStrategy.WEIGHTED_MEAN,
    threshold: Optional[float] = None,
    handle_nan: str = "ignore",
) -> np.ndarray:
    """
    Blend multiple scalar grids into one.
    
    Args:
        grids: Sequence of 2D numpy arrays (must be same shape)
        weights: Optional weights for each grid (defaults to equal weights)
        strategy: Blending strategy (see BlendStrategy enum)
        threshold: For PROBABILITY strategy, the threshold value
        handle_nan: How to handle NaN values: "ignore", "propagate", "fill_zero"
    
    Returns:
        Blended 2D numpy array
    
    Example:
        >>> gfs = fetch_grid("GFS", "T", tr)
        >>> ecmwf = fetch_grid("ECMWF", "T", tr)
        >>> blended = blend_scalar([gfs, ecmwf], [0.6, 0.4])
    """
    if not grids:
        raise ValueError("At least one grid required")
    
    # Convert string strategy to enum
    if isinstance(strategy, str):
        strategy = BlendStrategy(strategy)
    
    # Default to equal weights
    if weights is None:
        weights = [1.0] * len(grids)
    
    # Filter valid grids
    valid_grids, valid_weights = filter_valid_grids(grids, weights)
    if not valid_grids:
        raise ValueError("No valid grids to blend")
    
    # Verify shapes match
    shape = valid_grids[0].shape
    for i, g in enumerate(valid_grids[1:], 1):
        if g.shape != shape:
            raise ValueError(f"Grid {i} shape {g.shape} doesn't match {shape}")
    
    # Stack grids for vectorized operations
    stacked = np.stack(valid_grids, axis=0)
    
    # Handle NaN values
    if handle_nan == "fill_zero":
        stacked = np.nan_to_num(stacked, nan=0.0)
    
    # Apply strategy
    if strategy == BlendStrategy.WEIGHTED_MEAN:
        return _blend_weighted_mean(stacked, valid_weights)
    elif strategy == BlendStrategy.MAXIMUM:
        return _blend_maximum(stacked)
    elif strategy == BlendStrategy.MINIMUM:
        return _blend_minimum(stacked)
    elif strategy == BlendStrategy.MEDIAN:
        return _blend_median(stacked)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")


def _blend_weighted_mean(stacked: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted average of stacked grids."""
    weights_norm = weights / np.sum(weights)
    # Reshape weights for broadcasting: (N,) -> (N, 1, 1)
    weights_3d = weights_norm[:, np.newaxis, np.newaxis]
    return np.sum(stacked * weights_3d, axis=0)


def _blend_maximum(stacked: np.ndarray) -> np.ndarray:
    """Maximum value at each grid point."""
    return np.nanmax(stacked, axis=0)


def _blend_minimum(stacked: np.ndarray) -> np.ndarray:
    """Minimum value at each grid point."""
    return np.nanmin(stacked, axis=0)


def _blend_median(stacked: np.ndarray) -> np.ndarray:
    """Median value at each grid point."""
    return np.nanmedian(stacked, axis=0)


# =============================================================================
# Vector Blending
# =============================================================================

def blend_vector(
    grids: Sequence[VectorGrid],
    weights: Optional[Sequence[float]] = None,
    *,
    handle_calm: str = "preserve",
) -> VectorGrid:
    """
    Blend multiple vector grids (wind) using U/V component averaging.
    
    Vector blending MUST use U/V decomposition to properly average
    directions. Simple averaging of directions fails at 0/360 boundary
    and doesn't account for cancellation of opposing winds.
    
    Args:
        grids: Sequence of (magnitude, direction) tuples
        weights: Optional weights (defaults to equal)
        handle_calm: How to handle calm winds: "preserve", "zero_dir"
    
    Returns:
        Tuple of (blended_magnitude, blended_direction)
    
    Example:
        >>> gfs_wind = (gfs_mag, gfs_dir)
        >>> ecmwf_wind = (ecmwf_mag, ecmwf_dir)
        >>> blended = blend_vector([gfs_wind, ecmwf_wind], [0.7, 0.3])
    """
    if not grids:
        raise ValueError("At least one grid required")
    
    # Default to equal weights
    if weights is None:
        weights = [1.0] * len(grids)
    
    # Filter valid grids
    valid_grids = []
    valid_weights = []
    for (mag, dir_), weight in zip(grids, weights):
        if mag is not None and dir_ is not None and weight != 0:
            valid_grids.append((mag, dir_))
            valid_weights.append(weight)
    
    if not valid_grids:
        raise ValueError("No valid grids to blend")
    
    weights_arr = normalize_weights(valid_weights)
    
    # Initialize accumulators
    shape = valid_grids[0][0].shape
    u_sum = np.zeros(shape, dtype=float)
    v_sum = np.zeros(shape, dtype=float)
    
    # Accumulate weighted U/V components
    for (mag, dir_), weight in zip(valid_grids, weights_arr):
        u, v = mag_dir_to_uv(mag, dir_)
        u_sum += u * weight
        v_sum += v * weight
    
    # Convert back to mag/dir
    blended_mag, blended_dir = uv_to_mag_dir(u_sum, v_sum)
    
    # Handle calm winds (magnitude near zero)
    if handle_calm == "zero_dir":
        calm_mask = blended_mag < 0.5
        blended_dir = np.where(calm_mask, 0.0, blended_dir)
    
    return (blended_mag, blended_dir)


# =============================================================================
# Vector Utilities
# =============================================================================

def mag_dir_to_uv(
    magnitude: np.ndarray,
    direction: np.ndarray,
    *,
    convention: str = "meteorological",
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert magnitude and direction to U/V components.
    
    Args:
        magnitude: Wind speed magnitude
        direction: Wind direction in degrees
        convention: "meteorological" (dir wind is FROM) or "math" (dir wind is TO)
    
    Returns:
        Tuple of (U, V) components
    """
    # Convert to radians
    dir_rad = np.radians(direction)
    
    if convention == "meteorological":
        # Meteorological: direction wind is coming FROM
        u = -magnitude * np.sin(dir_rad)
        v = -magnitude * np.cos(dir_rad)
    else:
        # Math convention: direction wind is going TO
        u = magnitude * np.cos(dir_rad)
        v = magnitude * np.sin(dir_rad)
    
    return (u, v)


def uv_to_mag_dir(
    u: np.ndarray,
    v: np.ndarray,
    *,
    convention: str = "meteorological",
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert U/V components to magnitude and direction.
    
    Returns:
        Tuple of (magnitude, direction) with direction in [0, 360)
    """
    magnitude = np.sqrt(u**2 + v**2)
    
    if convention == "meteorological":
        # Direction wind is coming FROM
        direction = np.degrees(np.arctan2(-u, -v))
    else:
        direction = np.degrees(np.arctan2(v, u))
    
    # Normalize to [0, 360)
    direction = np.mod(direction, 360.0)
    
    return (magnitude, direction)


def vector_magnitude(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Calculate vector magnitude from U/V components."""
    return np.sqrt(u**2 + v**2)


def rotate_direction(
    direction: np.ndarray,
    angle: float,
) -> np.ndarray:
    """Rotate direction by angle (degrees), keeping in [0, 360)."""
    return np.mod(direction + angle, 360.0)


# =============================================================================
# Ensemble Statistics - Basic
# =============================================================================

def ensemble_mean(
    grids: Sequence[np.ndarray],
    weights: Optional[Sequence[float]] = None,
) -> np.ndarray:
    """
    Calculate ensemble mean (weighted or unweighted).
    
    Args:
        grids: Sequence of 2D model grids
        weights: Optional weights (defaults to equal)
    
    Returns:
        Mean grid
    """
    stacked = np.stack(grids, axis=0)
    
    if weights is None:
        return np.nanmean(stacked, axis=0)
    
    weights = np.array(weights)
    weights = weights / np.sum(weights)
    weights_3d = weights[:, np.newaxis, np.newaxis]
    
    return np.nansum(stacked * weights_3d, axis=0)


def ensemble_median(grids: Sequence[np.ndarray]) -> np.ndarray:
    """Calculate ensemble median (outlier-resistant central tendency)."""
    stacked = np.stack(grids, axis=0)
    return np.nanmedian(stacked, axis=0)


def ensemble_max(grids: Sequence[np.ndarray]) -> np.ndarray:
    """Maximum value across ensemble at each point."""
    stacked = np.stack(grids, axis=0)
    return np.nanmax(stacked, axis=0)


def ensemble_min(grids: Sequence[np.ndarray]) -> np.ndarray:
    """Minimum value across ensemble at each point."""
    stacked = np.stack(grids, axis=0)
    return np.nanmin(stacked, axis=0)


def ensemble_std(grids: Sequence[np.ndarray]) -> np.ndarray:
    """Standard deviation across ensemble (measure of uncertainty)."""
    stacked = np.stack(grids, axis=0)
    return np.nanstd(stacked, axis=0)


def ensemble_percentile(
    grids: Sequence[np.ndarray],
    percentile: float,
) -> np.ndarray:
    """
    Calculate specific percentile across ensemble.
    
    Args:
        grids: Ensemble members
        percentile: Percentile to calculate (0-100)
    
    Returns:
        Percentile grid
    
    Example:
        >>> p90 = ensemble_percentile(models, 90)  # 90th percentile
        >>> p10 = ensemble_percentile(models, 10)  # 10th percentile
    """
    stacked = np.stack(grids, axis=0)
    return np.nanpercentile(stacked, percentile, axis=0)


def ensemble_range(
    grids: Sequence[np.ndarray],
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Get min and max grids (full ensemble envelope).
    
    Returns:
        Tuple of (min_grid, max_grid)
    """
    stacked = np.stack(grids, axis=0)
    return (
        np.nanmin(stacked, axis=0),
        np.nanmax(stacked, axis=0),
    )


def ensemble_percentile_range(
    grids: Sequence[np.ndarray],
    low_pct: float = 10.0,
    high_pct: float = 90.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Get percentile range (more robust than min/max).
    
    Default 10th-90th excludes extreme outliers.
    
    Returns:
        Tuple of (low_percentile_grid, high_percentile_grid)
    """
    stacked = np.stack(grids, axis=0)
    return (
        np.nanpercentile(stacked, low_pct, axis=0),
        np.nanpercentile(stacked, high_pct, axis=0),
    )


# =============================================================================
# Ensemble Statistics - Spread & Confidence
# =============================================================================

def ensemble_spread(grids: Sequence[np.ndarray]) -> np.ndarray:
    """
    Calculate ensemble spread (max - min).
    
    Large spread = high uncertainty, models disagree
    Small spread = higher confidence, models agree
    """
    min_grid, max_grid = ensemble_range(grids)
    return max_grid - min_grid


def ensemble_iqr(grids: Sequence[np.ndarray]) -> np.ndarray:
    """
    Interquartile range (75th - 25th percentile).
    
    More robust spread measure than full range.
    """
    stacked = np.stack(grids, axis=0)
    p75 = np.nanpercentile(stacked, 75, axis=0)
    p25 = np.nanpercentile(stacked, 25, axis=0)
    return p75 - p25


def ensemble_normalized_spread(
    grids: Sequence[np.ndarray],
    *,
    reference_spread: Optional[np.ndarray] = None,
    epsilon: float = 0.1,
) -> np.ndarray:
    """
    Spread normalized by mean value (coefficient of variation).
    
    Useful when comparing spread across different magnitudes.
    
    Args:
        grids: Ensemble members
        reference_spread: Optional climatological spread for normalization
        epsilon: Small value to avoid division by zero
    
    Returns:
        Normalized spread (0 = perfect agreement, higher = more uncertainty)
    """
    spread = ensemble_spread(grids)
    
    if reference_spread is not None:
        return spread / np.maximum(reference_spread, epsilon)
    else:
        mean = ensemble_mean(grids)
        return spread / np.maximum(np.abs(mean), epsilon)


def ensemble_agreement(
    grids: Sequence[np.ndarray],
    *,
    method: str = "normalized_std",
    max_expected_std: Optional[float] = None,
) -> np.ndarray:
    """
    Calculate model agreement index (0-100%).
    
    100% = perfect agreement (all models identical)
    0% = maximum disagreement
    
    Args:
        grids: Ensemble members
        method: "normalized_std" or "range_based"
        max_expected_std: For normalization (if known from climatology)
    
    Returns:
        Agreement percentage grid (0-100)
    """
    n_models = len(grids)
    if n_models < 2:
        return np.full_like(grids[0], 100.0)
    
    if method == "normalized_std":
        std = ensemble_std(grids)
        mean = ensemble_mean(grids)
        
        cv = std / np.maximum(np.abs(mean), 0.1)
        
        if max_expected_std is not None:
            cv = cv / max_expected_std
        else:
            cv = cv / 0.5
        
        agreement = (1.0 - np.minimum(cv, 1.0)) * 100.0
        
    elif method == "range_based":
        spread = ensemble_spread(grids)
        mean = ensemble_mean(grids)
        
        relative_spread = spread / np.maximum(np.abs(mean), 0.1)
        agreement = (1.0 - np.minimum(relative_spread, 1.0)) * 100.0
    
    else:
        raise ValueError(f"Unknown method: {method}")
    
    return np.clip(agreement, 0.0, 100.0)


def ensemble_confidence(
    grids: Sequence[np.ndarray],
    *,
    spread_weight: float = 0.5,
    consistency_weight: float = 0.3,
    sample_weight: float = 0.2,
) -> np.ndarray:
    """
    Composite confidence index combining multiple factors.
    
    Factors:
    - Spread: Lower spread = higher confidence
    - Consistency: Models near median = higher confidence  
    - Sample size: More models = higher confidence
    
    Returns:
        Confidence index (0-100)
    """
    n_models = len(grids)
    
    # Spread factor
    spread_factor = ensemble_agreement(grids) / 100.0
    
    # Consistency factor
    median = ensemble_median(grids)
    stacked = np.stack(grids, axis=0)
    spread = ensemble_spread(grids)
    threshold = spread * 0.25
    near_median = np.abs(stacked - median) < np.maximum(threshold, 0.1)
    consistency_factor = np.mean(near_median, axis=0)
    
    # Sample size factor
    sample_factor = np.minimum(n_models / 5.0, 1.0)
    
    # Combine factors
    confidence = (
        spread_weight * spread_factor +
        consistency_weight * consistency_factor +
        sample_weight * sample_factor
    ) * 100.0
    
    return np.clip(confidence, 0.0, 100.0)


# =============================================================================
# Probability Calculations
# =============================================================================

def prob_exceeds(
    grids: Sequence[np.ndarray],
    threshold: float,
    *,
    strict: bool = True,
) -> np.ndarray:
    """
    Probability of exceeding threshold.
    
    Args:
        grids: Ensemble members
        threshold: Value threshold
        strict: If True, use > (strict). If False, use >= 
    
    Returns:
        Probability grid (0-100%)
    
    Example:
        >>> prob_gale = prob_exceeds(wind_models, 34.0)  # P(wind > 34 kt)
    """
    stacked = np.stack(grids, axis=0)
    
    if strict:
        exceeds = stacked > threshold
    else:
        exceeds = stacked >= threshold
    
    return np.mean(exceeds, axis=0) * 100.0


def prob_below(
    grids: Sequence[np.ndarray],
    threshold: float,
    *,
    strict: bool = True,
) -> np.ndarray:
    """
    Probability of being below threshold.
    
    Example:
        >>> prob_fog = prob_below(vis_models, 1.0)  # P(vis < 1 NM)
    """
    stacked = np.stack(grids, axis=0)
    
    if strict:
        below = stacked < threshold
    else:
        below = stacked <= threshold
    
    return np.mean(below, axis=0) * 100.0


def prob_between(
    grids: Sequence[np.ndarray],
    low: float,
    high: float,
    *,
    inclusive: bool = True,
) -> np.ndarray:
    """
    Probability of value being in range.
    
    Args:
        grids: Ensemble members
        low: Lower bound
        high: Upper bound
        inclusive: Include boundaries
    
    Returns:
        Probability grid (0-100%)
    """
    stacked = np.stack(grids, axis=0)
    
    if inclusive:
        in_range = (stacked >= low) & (stacked <= high)
    else:
        in_range = (stacked > low) & (stacked < high)
    
    return np.mean(in_range, axis=0) * 100.0


def prob_category(
    grids: Sequence[np.ndarray],
    thresholds: Sequence[float],
    *,
    labels: Optional[Sequence[str]] = None,
) -> Tuple[np.ndarray, List[np.ndarray]]:
    """
    Probability of each category based on thresholds.
    
    Args:
        grids: Ensemble members
        thresholds: Category boundaries (N thresholds = N+1 categories)
        labels: Optional category labels
    
    Returns:
        Tuple of (most_likely_category_index, list_of_probability_grids)
    """
    stacked = np.stack(grids, axis=0)
    thresholds = sorted(thresholds)
    n_categories = len(thresholds) + 1
    
    prob_grids = []
    
    for cat_idx in range(n_categories):
        if cat_idx == 0:
            in_cat = stacked < thresholds[0]
        elif cat_idx == n_categories - 1:
            in_cat = stacked >= thresholds[-1]
        else:
            in_cat = (stacked >= thresholds[cat_idx-1]) & (stacked < thresholds[cat_idx])
        
        prob = np.mean(in_cat, axis=0) * 100.0
        prob_grids.append(prob)
    
    prob_stack = np.stack(prob_grids, axis=0)
    most_likely = np.argmax(prob_stack, axis=0)
    
    return most_likely, prob_grids


def prob_wind_categories(
    wind_grids: Sequence[np.ndarray],
) -> Dict[str, np.ndarray]:
    """
    Standard wind probability categories.
    
    Returns dict with probabilities for:
    - calm: < 10 kt
    - light: 10-20 kt  
    - moderate: 20-34 kt
    - gale: 34-48 kt
    - storm: 48-64 kt
    - hurricane: >= 64 kt
    """
    return {
        "calm": prob_below(wind_grids, 10),
        "light": prob_between(wind_grids, 10, 20),
        "moderate": prob_between(wind_grids, 20, 34),
        "gale": prob_between(wind_grids, 34, 48),
        "storm": prob_between(wind_grids, 48, 64),
        "hurricane": prob_exceeds(wind_grids, 64, strict=False),
    }


def prob_wave_categories(
    wave_grids: Sequence[np.ndarray],
) -> Dict[str, np.ndarray]:
    """
    Standard wave probability categories (feet).
    
    - calm: < 2 ft
    - slight: 2-4 ft
    - moderate: 4-8 ft
    - rough: 8-13 ft
    - very_rough: 13-20 ft
    - high: >= 20 ft
    """
    return {
        "calm": prob_below(wave_grids, 2),
        "slight": prob_between(wave_grids, 2, 4),
        "moderate": prob_between(wave_grids, 4, 8),
        "rough": prob_between(wave_grids, 8, 13),
        "very_rough": prob_between(wave_grids, 13, 20),
        "high": prob_exceeds(wave_grids, 20, strict=False),
    }


# =============================================================================
# Weighted Ensemble Methods
# =============================================================================

def weighted_mean(
    grids: Sequence[np.ndarray],
    weights: Sequence[float],
) -> np.ndarray:
    """Standard weighted mean."""
    return ensemble_mean(grids, weights)


def trimmed_mean(
    grids: Sequence[np.ndarray],
    trim_fraction: float = 0.1,
) -> np.ndarray:
    """
    Trimmed mean - exclude extreme values before averaging.
    
    Args:
        grids: Ensemble members
        trim_fraction: Fraction to trim from each tail (0.1 = trim 10% from each end)
    
    Returns:
        Trimmed mean grid
    """
    stacked = np.stack(grids, axis=0)
    
    if scipy_stats is not None:
        return scipy_stats.trim_mean(stacked, trim_fraction, axis=0)
    else:
        # Fallback: manual implementation
        n = len(grids)
        k = int(n * trim_fraction)
        if k == 0:
            return np.nanmean(stacked, axis=0)
        
        sorted_stack = np.sort(stacked, axis=0)
        trimmed = sorted_stack[k:-k] if k > 0 else sorted_stack
        return np.nanmean(trimmed, axis=0)


def weighted_by_spread(
    grids: Sequence[np.ndarray],
    *,
    power: float = 1.0,
) -> np.ndarray:
    """
    Weight inversely by each model's deviation from ensemble.
    
    Models closer to the consensus get higher weight.
    Outlier models get lower weight.
    
    Args:
        grids: Ensemble members
        power: Higher power = more aggressive outlier downweighting
    
    Returns:
        Spread-weighted mean
    """
    initial_mean = ensemble_mean(grids)
    stacked = np.stack(grids, axis=0)
    
    deviations = np.abs(stacked - initial_mean)
    model_deviations = np.nanmean(deviations, axis=(1, 2))
    
    weights = 1.0 / np.maximum(model_deviations, 0.01) ** power
    weights = weights / np.sum(weights)
    
    weights_3d = weights[:, np.newaxis, np.newaxis]
    return np.nansum(stacked * weights_3d, axis=0)


def weighted_by_consistency(
    grids: Sequence[np.ndarray],
    previous_grids: Optional[Sequence[np.ndarray]] = None,
    *,
    power: float = 1.0,
) -> np.ndarray:
    """
    Weight by run-to-run consistency.
    
    Models that changed less from their previous run get higher weight.
    
    Args:
        grids: Current run ensemble members
        previous_grids: Previous run of same models (same order)
        power: Higher = more weight to consistent models
    """
    if previous_grids is None:
        return weighted_by_spread(grids, power=power)
    
    stacked = np.stack(grids, axis=0)
    prev_stacked = np.stack(previous_grids, axis=0)
    
    changes = np.abs(stacked - prev_stacked)
    model_changes = np.nanmean(changes, axis=(1, 2))
    
    weights = 1.0 / np.maximum(model_changes, 0.01) ** power
    weights = weights / np.sum(weights)
    
    weights_3d = weights[:, np.newaxis, np.newaxis]
    return np.nansum(stacked * weights_3d, axis=0)


# =============================================================================
# Model Comparison
# =============================================================================

def model_anomaly(
    grid: np.ndarray,
    ensemble_grids: Sequence[np.ndarray],
) -> np.ndarray:
    """
    Calculate a single model's anomaly from ensemble mean.
    
    Positive = model is higher than consensus
    Negative = model is lower than consensus
    """
    mean = ensemble_mean(ensemble_grids)
    return grid - mean


def model_normalized_anomaly(
    grid: np.ndarray,
    ensemble_grids: Sequence[np.ndarray],
) -> np.ndarray:
    """
    Model anomaly normalized by ensemble spread (like z-score).
    
    Values:
        0 = at the ensemble mean
        +1 = one spread above mean
        -1 = one spread below mean
    """
    mean = ensemble_mean(ensemble_grids)
    std = ensemble_std(ensemble_grids)
    
    return (grid - mean) / np.maximum(std, 0.01)


def pairwise_difference(
    grid_a: np.ndarray,
    grid_b: np.ndarray,
) -> Dict[str, np.ndarray]:
    """
    Calculate difference between two model grids.
    
    Returns:
        Dict with difference, abs_difference, pct_difference
    """
    diff = grid_a - grid_b
    abs_diff = np.abs(diff)
    
    avg = (grid_a + grid_b) / 2.0
    pct_diff = abs_diff / np.maximum(np.abs(avg), 0.01) * 100.0
    
    return {
        "difference": diff,
        "abs_difference": abs_diff,
        "pct_difference": pct_diff,
    }


# =============================================================================
# Scenarios
# =============================================================================

def most_likely_scenario(
    grids: Sequence[np.ndarray],
    *,
    method: str = "closest_to_median",
) -> Tuple[int, np.ndarray]:
    """
    Identify the most representative ensemble member.
    
    Args:
        grids: Ensemble members
        method: "closest_to_median" or "closest_to_mean"
    
    Returns:
        Tuple of (member_index, member_grid)
    """
    if method == "closest_to_median":
        target = ensemble_median(grids)
    elif method == "closest_to_mean":
        target = ensemble_mean(grids)
    else:
        raise ValueError(f"Unknown method: {method}")
    
    distances = np.array([np.nanmean(np.abs(g - target)) for g in grids])
    best_idx = np.argmin(distances)
    
    return best_idx, grids[best_idx]


def scenario_summary(
    grids: Sequence[np.ndarray],
    model_names: Optional[Sequence[str]] = None,
) -> Dict[str, any]:
    """
    Generate comprehensive scenario summary.
    
    Returns:
        Dict with low_scenario, most_likely, high_scenario, mean, spread, confidence
    """
    low, high = ensemble_percentile_range(grids, 10, 90)
    most_likely_idx, most_likely_grid = most_likely_scenario(grids)
    
    means = [np.nanmean(g) for g in grids]
    rank_order = np.argsort(means)
    
    result = {
        "low_scenario": low,
        "high_scenario": high,
        "most_likely": most_likely_grid,
        "most_likely_model_index": most_likely_idx,
        "mean": ensemble_mean(grids),
        "median": ensemble_median(grids),
        "spread": ensemble_spread(grids),
        "confidence": ensemble_confidence(grids),
        "lowest_models": list(rank_order[:2]),
        "highest_models": list(rank_order[-2:]),
    }
    
    if model_names:
        result["most_likely_model_name"] = model_names[most_likely_idx]
        result["lowest_model_names"] = [model_names[i] for i in rank_order[:2]]
        result["highest_model_names"] = [model_names[i] for i in rank_order[-2:]]
    
    return result


# =============================================================================
# Smoothing
# =============================================================================

def smooth_gaussian(
    grid: np.ndarray,
    sigma: float = DEFAULT_SIGMA,
    *,
    passes: int = 1,
    truncate: float = DEFAULT_TRUNCATE,
    preserve_nan: bool = True,
) -> np.ndarray:
    """
    Apply Gaussian smoothing to a grid.
    
    Args:
        grid: 2D numpy array
        sigma: Standard deviation of Gaussian kernel
        passes: Number of smoothing passes
        truncate: Truncate filter at this many sigmas
        preserve_nan: If True, NaN values remain NaN after smoothing
    
    Returns:
        Smoothed grid
    """
    if sigma <= 0:
        return grid.copy()
    
    result = grid.copy()
    nan_mask = None
    
    if preserve_nan:
        nan_mask = np.isnan(result)
        result = np.nan_to_num(result, nan=0.0)
    
    for _ in range(passes):
        result = ndimage.gaussian_filter(
            result, sigma=sigma, truncate=truncate, mode="nearest"
        )
    
    if preserve_nan and nan_mask is not None:
        result[nan_mask] = np.nan
    
    return result


def smooth_uniform(
    grid: np.ndarray,
    size: int = 3,
    *,
    passes: int = 1,
) -> np.ndarray:
    """
    Apply uniform (box) smoothing to a grid.
    
    Args:
        grid: 2D numpy array
        size: Size of the smoothing window (must be odd)
        passes: Number of smoothing passes
    """
    if size < 1:
        return grid.copy()
    
    if size % 2 == 0:
        size += 1
    
    result = grid.copy()
    for _ in range(passes):
        result = ndimage.uniform_filter(result, size=size, mode="nearest")
    
    return result


def smooth_vector(
    vector_grid: VectorGrid,
    sigma: float = DEFAULT_SIGMA,
    *,
    passes: int = 1,
    smooth_direction: bool = False,
) -> VectorGrid:
    """
    Apply smoothing to a vector grid.
    
    By default, only smooths magnitude (preserves direction detail).
    
    Args:
        vector_grid: Tuple of (magnitude, direction)
        sigma: Gaussian sigma
        passes: Number of passes
        smooth_direction: Whether to smooth direction (usually False)
    """
    mag, dir_ = vector_grid
    
    smoothed_mag = smooth_gaussian(mag, sigma, passes=passes)
    
    if smooth_direction:
        u, v = mag_dir_to_uv(mag, dir_)
        u_smooth = smooth_gaussian(u, sigma, passes=passes)
        v_smooth = smooth_gaussian(v, sigma, passes=passes)
        _, smoothed_dir = uv_to_mag_dir(u_smooth, v_smooth)
    else:
        smoothed_dir = dir_.copy()
    
    return (smoothed_mag, smoothed_dir)


# =============================================================================
# Edit Area / Masking
# =============================================================================

def apply_edit_area(
    new_grid: np.ndarray,
    old_grid: np.ndarray,
    mask: np.ndarray,
    *,
    taper_width: int = 0,
) -> np.ndarray:
    """
    Apply changes only within edit area, with optional edge tapering.
    
    Args:
        new_grid: The new values to apply
        old_grid: The existing values (used outside edit area)
        mask: Boolean mask (True = apply new values)
        taper_width: Width of taper zone at edges (0 = sharp boundary)
    
    Returns:
        Blended grid
    """
    if taper_width > 0:
        taper = create_taper(mask, taper_width)
    else:
        taper = mask.astype(float)
    
    return old_grid + (new_grid - old_grid) * taper


def apply_edit_area_vector(
    new_grid: VectorGrid,
    old_grid: VectorGrid,
    mask: np.ndarray,
    *,
    taper_width: int = 0,
) -> VectorGrid:
    """
    Apply edit area to vector grid using U/V blending.
    """
    if taper_width > 0:
        taper = create_taper(mask, taper_width)
    else:
        taper = mask.astype(float)
    
    u_new, v_new = mag_dir_to_uv(new_grid[0], new_grid[1])
    u_old, v_old = mag_dir_to_uv(old_grid[0], old_grid[1])
    
    u_result = u_old + (u_new - u_old) * taper
    v_result = v_old + (v_new - v_old) * taper
    
    return uv_to_mag_dir(u_result, v_result)


def create_taper(
    mask: np.ndarray,
    width: int,
    *,
    method: str = "distance",
) -> np.ndarray:
    """
    Create a taper grid from a boolean mask.
    
    Args:
        mask: Boolean mask (True = inside region)
        width: Width of taper zone
        method: "distance" or "gaussian"
    
    Returns:
        Float array with 1.0 inside, 0.0 outside, gradient in between
    """
    if width <= 0:
        return mask.astype(float)
    
    mask_float = mask.astype(float)
    
    if method == "gaussian":
        return ndimage.gaussian_filter(mask_float, sigma=width / 2.5)
    
    else:  # distance method
        dist_inside = ndimage.distance_transform_edt(mask)
        taper = np.clip(dist_inside / width, 0.0, 1.0)
        return taper


def expand_mask(
    mask: np.ndarray,
    pixels: int,
) -> np.ndarray:
    """Expand a boolean mask by a number of pixels."""
    if pixels <= 0:
        return mask.copy()
    
    y, x = np.ogrid[-pixels:pixels+1, -pixels:pixels+1]
    structure = x**2 + y**2 <= pixels**2
    
    return ndimage.binary_dilation(mask, structure=structure, iterations=1)


def shrink_mask(
    mask: np.ndarray,
    pixels: int,
) -> np.ndarray:
    """Shrink a boolean mask by a number of pixels."""
    if pixels <= 0:
        return mask.copy()
    
    y, x = np.ogrid[-pixels:pixels+1, -pixels:pixels+1]
    structure = x**2 + y**2 <= pixels**2
    
    return ndimage.binary_erosion(mask, structure=structure, iterations=1)


# =============================================================================
# Clipping & Bounds
# =============================================================================

def clip_values(
    grid: np.ndarray,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> np.ndarray:
    """
    Clip grid values to specified range.
    """
    result = grid.copy()
    if min_val is not None:
        result = np.maximum(result, min_val)
    if max_val is not None:
        result = np.minimum(result, max_val)
    return result


def fill_missing(
    grid: np.ndarray,
    fill_value: float = 0.0,
    *,
    method: str = "constant",
) -> np.ndarray:
    """
    Fill missing (NaN) values in a grid.
    
    Args:
        grid: Input grid with NaN values
        fill_value: Value to use for "constant" method
        method: "constant", "mean", "interpolate"
    """
    if method == "constant":
        return np.nan_to_num(grid, nan=fill_value)
    elif method == "mean":
        mean_val = np.nanmean(grid)
        return np.nan_to_num(grid, nan=mean_val)
    elif method == "interpolate":
        from scipy.interpolate import griddata
        mask = np.isnan(grid)
        if not np.any(mask):
            return grid.copy()
        
        y, x = np.mgrid[0:grid.shape[0], 0:grid.shape[1]]
        valid_points = np.array([y[~mask], x[~mask]]).T
        valid_values = grid[~mask]
        invalid_points = np.array([y[mask], x[mask]]).T
        
        filled = grid.copy()
        filled[mask] = griddata(valid_points, valid_values, invalid_points, 
                                method='nearest')
        return filled
    else:
        raise ValueError(f"Unknown method: {method}")


def ensure_range(
    grid: np.ndarray,
    min_val: float,
    max_val: float,
    *,
    scale: bool = False,
) -> np.ndarray:
    """
    Ensure grid values are within specified range.
    
    Args:
        grid: Input grid
        min_val: Minimum value
        max_val: Maximum value
        scale: If True, scale values to fit range. If False, clip.
    """
    if scale:
        grid_min = np.nanmin(grid)
        grid_max = np.nanmax(grid)
        if grid_max - grid_min < 1e-10:
            return np.full_like(grid, (min_val + max_val) / 2)
        normalized = (grid - grid_min) / (grid_max - grid_min)
        return normalized * (max_val - min_val) + min_val
    else:
        return clip_values(grid, min_val, max_val)


# =============================================================================
# Grid Utilities
# =============================================================================

def grids_compatible(*grids: np.ndarray) -> bool:
    """Check if all grids have the same shape."""
    if not grids:
        return True
    shape = grids[0].shape
    return all(g.shape == shape for g in grids)


def get_grid_stats(grid: np.ndarray) -> Dict[str, float]:
    """
    Calculate statistics for a grid.
    """
    return {
        "min": float(np.nanmin(grid)),
        "max": float(np.nanmax(grid)),
        "mean": float(np.nanmean(grid)),
        "std": float(np.nanstd(grid)),
        "median": float(np.nanmedian(grid)),
        "pct_nan": float(np.sum(np.isnan(grid)) / grid.size * 100),
    }


def create_empty_like(
    template: np.ndarray,
    fill_value: float = 0.0,
) -> np.ndarray:
    """Create an empty grid with the same shape as template."""
    return np.full_like(template, fill_value, dtype=float)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "BlendStrategy",
    
    # Blending
    "blend_scalar",
    "blend_vector",
    "normalize_weights",
    "filter_valid_grids",
    
    # Ensemble - Basic
    "ensemble_mean",
    "ensemble_median",
    "ensemble_max",
    "ensemble_min",
    "ensemble_std",
    "ensemble_percentile",
    "ensemble_range",
    "ensemble_percentile_range",
    
    # Ensemble - Spread & Confidence
    "ensemble_spread",
    "ensemble_iqr",
    "ensemble_normalized_spread",
    "ensemble_agreement",
    "ensemble_confidence",
    
    # Ensemble - Probability
    "prob_exceeds",
    "prob_below",
    "prob_between",
    "prob_category",
    "prob_wind_categories",
    "prob_wave_categories",
    
    # Ensemble - Weighted Methods
    "weighted_mean",
    "trimmed_mean",
    "weighted_by_spread",
    "weighted_by_consistency",
    
    # Ensemble - Model Comparison
    "model_anomaly",
    "model_normalized_anomaly",
    "pairwise_difference",
    
    # Ensemble - Scenarios
    "most_likely_scenario",
    "scenario_summary",
    
    # Smoothing
    "smooth_gaussian",
    "smooth_uniform",
    "smooth_vector",
    
    # Edit Area
    "apply_edit_area",
    "apply_edit_area_vector",
    "create_taper",
    "expand_mask",
    "shrink_mask",
    
    # Clipping
    "clip_values",
    "fill_missing",
    "ensure_range",
    
    # Vector utilities
    "mag_dir_to_uv",
    "uv_to_mag_dir",
    "vector_magnitude",
    "rotate_direction",
    
    # Grid utilities
    "grids_compatible",
    "get_grid_stats",
    "create_empty_like",
]
