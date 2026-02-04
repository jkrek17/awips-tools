# Grid Operations Utility Module

Low-level grid manipulation functions for blending, smoothing, ensemble statistics, and masking. These are pure NumPy functions with no meteorological knowledge—just math on grids.

## Quick Start

```python
from utilities import grid_ops

# Blend multiple model grids
blended = grid_ops.blend_scalar([gfs, ecmwf, cmc], weights=[0.5, 0.3, 0.2])

# Get ensemble spread
spread = grid_ops.ensemble_spread([gfs, ecmwf, nam, cmc])

# Probability of gale-force winds
prob_gale = grid_ops.prob_exceeds(wind_models, 34.0)
```

---

## Scalar Blending

### Basic Weighted Blend

```python
# Equal weight blend (default)
blended = grid_ops.blend_scalar([model1, model2, model3])

# Custom weights
blended = grid_ops.blend_scalar(
    [gfs, ecmwf, cmc],
    weights=[0.5, 0.3, 0.2]
)
```

### Blend Strategies

```python
from utilities.grid_ops import BlendStrategy

# Weighted mean (default)
result = grid_ops.blend_scalar(grids, strategy=BlendStrategy.WEIGHTED_MEAN)

# Maximum value at each point
result = grid_ops.blend_scalar(grids, strategy=BlendStrategy.MAXIMUM)

# Minimum value (good for visibility)
result = grid_ops.blend_scalar(grids, strategy="min")  # string also works

# Median (outlier resistant)
result = grid_ops.blend_scalar(grids, strategy=BlendStrategy.MEDIAN)
```

### Handling Missing Data

```python
# Ignore NaN values (default)
result = grid_ops.blend_scalar(grids, handle_nan="ignore")

# Fill NaN with zero before blending
result = grid_ops.blend_scalar(grids, handle_nan="fill_zero")

# Propagate NaN (result is NaN if any input is NaN)
result = grid_ops.blend_scalar(grids, handle_nan="propagate")
```

---

## Vector Blending (Wind)

Vector blending uses U/V component decomposition to properly average wind direction. Never average directions directly—it fails at the 0/360 boundary.

```python
# Each wind grid is a tuple of (magnitude, direction)
gfs_wind = (gfs_speed, gfs_dir)
ecmwf_wind = (ecmwf_speed, ecmwf_dir)
nam_wind = (nam_speed, nam_dir)

# Blend vectors
blended_mag, blended_dir = grid_ops.blend_vector(
    [gfs_wind, ecmwf_wind, nam_wind],
    weights=[0.5, 0.3, 0.2]
)
```

### Vector Utilities

```python
# Convert mag/dir to U/V components
u, v = grid_ops.mag_dir_to_uv(speed, direction)

# Convert U/V back to mag/dir
speed, direction = grid_ops.uv_to_mag_dir(u, v)

# Calculate magnitude from components
speed = grid_ops.vector_magnitude(u, v)

# Rotate direction by angle
new_dir = grid_ops.rotate_direction(direction, 15.0)  # Add 15 degrees
```

---

## Ensemble Statistics

### Basic Statistics

```python
models = [gfs, ecmwf, nam, cmc, ukmet]

# Central tendency
mean = grid_ops.ensemble_mean(models)
median = grid_ops.ensemble_median(models)

# Extremes
max_val = grid_ops.ensemble_max(models)
min_val = grid_ops.ensemble_min(models)

# Variability
std = grid_ops.ensemble_std(models)

# Percentiles
p10 = grid_ops.ensemble_percentile(models, 10)
p90 = grid_ops.ensemble_percentile(models, 90)

# Full range
low, high = grid_ops.ensemble_range(models)

# Percentile range (more robust)
p10, p90 = grid_ops.ensemble_percentile_range(models, 10, 90)
```

### Spread and Confidence

```python
# Spread = max - min (measure of uncertainty)
spread = grid_ops.ensemble_spread(models)

# Interquartile range (robust spread)
iqr = grid_ops.ensemble_iqr(models)

# Model agreement (0-100%)
agreement = grid_ops.ensemble_agreement(models)

# Composite confidence index
confidence = grid_ops.ensemble_confidence(models)

# Normalized spread (relative to mean)
norm_spread = grid_ops.ensemble_normalized_spread(models)
```

---

## Probability Calculations

```python
wind_models = [gfs_wind, ecmwf_wind, nam_wind, cmc_wind]

# Probability of exceeding threshold
prob_gale = grid_ops.prob_exceeds(wind_models, 34.0)      # P(wind > 34 kt)
prob_storm = grid_ops.prob_exceeds(wind_models, 48.0)    # P(wind > 48 kt)

# Probability below threshold
prob_calm = grid_ops.prob_below(wind_models, 10.0)       # P(wind < 10 kt)

# Probability in range
prob_mod = grid_ops.prob_between(wind_models, 20.0, 34.0)  # P(20 < wind < 34)

# Standard wind categories (returns dict)
wind_probs = grid_ops.prob_wind_categories(wind_models)
# wind_probs["calm"], wind_probs["gale"], wind_probs["storm"], etc.

# Standard wave categories
wave_probs = grid_ops.prob_wave_categories(wave_models)
# wave_probs["slight"], wave_probs["rough"], wave_probs["high"], etc.
```

### Category Probabilities

```python
# Custom categories with thresholds
thresholds = [10, 20, 34, 48, 64]  # Wind speed categories
most_likely_cat, prob_list = grid_ops.prob_category(wind_models, thresholds)

# prob_list[0] = P(wind < 10)
# prob_list[1] = P(10 <= wind < 20)
# prob_list[2] = P(20 <= wind < 34)
# etc.
```

---

## Weighted Ensemble Methods

### Trimmed Mean

Excludes extreme outliers before averaging.

```python
# Trim 10% from each end
result = grid_ops.trimmed_mean(models, trim_fraction=0.1)

# More aggressive trimming
result = grid_ops.trimmed_mean(models, trim_fraction=0.2)
```

### Spread-Weighted Mean

Models closer to the consensus get higher weight; outliers get downweighted.

```python
# Default weighting
result = grid_ops.weighted_by_spread(models)

# More aggressive outlier downweighting
result = grid_ops.weighted_by_spread(models, power=2.0)
```

### Consistency-Weighted Mean

Models that changed less from their previous run get higher weight.

```python
# Compare current run to previous run
current = [gfs_12z, ecmwf_12z, nam_12z]
previous = [gfs_00z, ecmwf_00z, nam_00z]

result = grid_ops.weighted_by_consistency(current, previous)
```

---

## Model Comparison

```python
# Single model vs ensemble
gfs_anomaly = grid_ops.model_anomaly(gfs, all_models)

# Normalized anomaly (like z-score)
gfs_z = grid_ops.model_normalized_anomaly(gfs, all_models)
# +1 = one std above mean, -1 = one std below

# Compare two models
diff = grid_ops.pairwise_difference(gfs, ecmwf)
# diff["difference"]      - signed difference
# diff["abs_difference"]  - absolute difference  
# diff["pct_difference"]  - percent difference
```

---

## Scenario Analysis

```python
# Find most representative member
idx, grid = grid_ops.most_likely_scenario(models)

# Complete scenario summary
summary = grid_ops.scenario_summary(models, model_names=["GFS", "ECMWF", "NAM", "CMC"])

# summary["low_scenario"]      - 10th percentile
# summary["high_scenario"]     - 90th percentile
# summary["most_likely"]       - closest to median
# summary["mean"]              - ensemble mean
# summary["spread"]            - max - min
# summary["confidence"]        - confidence index
# summary["most_likely_model_name"]  - "ECMWF" etc.
```

---

## Smoothing

### Gaussian Smoothing

```python
# Basic smoothing
smoothed = grid_ops.smooth_gaussian(grid, sigma=1.0)

# Multiple passes for more smoothing
smoothed = grid_ops.smooth_gaussian(grid, sigma=0.7, passes=3)

# Preserve NaN values (default)
smoothed = grid_ops.smooth_gaussian(grid, sigma=1.0, preserve_nan=True)
```

### Uniform (Box) Smoothing

```python
# 3x3 box filter
smoothed = grid_ops.smooth_uniform(grid, size=3)

# 5x5 box filter, 2 passes
smoothed = grid_ops.smooth_uniform(grid, size=5, passes=2)
```

### Vector Smoothing

```python
wind_grid = (magnitude, direction)

# Smooth magnitude only (default - preserves direction detail)
smoothed = grid_ops.smooth_vector(wind_grid, sigma=1.0)

# Smooth both magnitude and direction
smoothed = grid_ops.smooth_vector(wind_grid, sigma=1.0, smooth_direction=True)
```

---

## Edit Area / Masking

### Apply Changes Within Edit Area

```python
# Sharp boundary
result = grid_ops.apply_edit_area(new_values, old_values, mask)

# Smooth transition at edges (5 pixel taper)
result = grid_ops.apply_edit_area(new_values, old_values, mask, taper_width=5)
```

### Vector Edit Area

```python
new_wind = (new_mag, new_dir)
old_wind = (old_mag, old_dir)

# Apply with U/V blending at edges
result_mag, result_dir = grid_ops.apply_edit_area_vector(
    new_wind, old_wind, mask, taper_width=5
)
```

### Mask Operations

```python
# Create taper from mask
taper = grid_ops.create_taper(mask, width=10)

# Expand mask by 5 pixels
expanded = grid_ops.expand_mask(mask, 5)

# Shrink mask by 3 pixels
shrunk = grid_ops.shrink_mask(mask, 3)
```

---

## Grid Utilities

### Clipping and Bounds

```python
# Clip to range
clipped = grid_ops.clip_values(grid, min_val=0.0, max_val=100.0)

# Fill missing values
filled = grid_ops.fill_missing(grid, fill_value=0.0)
filled = grid_ops.fill_missing(grid, method="mean")      # Fill with mean
filled = grid_ops.fill_missing(grid, method="interpolate")  # Interpolate

# Ensure range (clip or scale)
result = grid_ops.ensure_range(grid, 0, 100)              # Clip
result = grid_ops.ensure_range(grid, 0, 100, scale=True)  # Scale to fit
```

### Grid Information

```python
# Check if grids are compatible
if grid_ops.grids_compatible(grid1, grid2, grid3):
    # Safe to blend
    
# Get statistics
stats = grid_ops.get_grid_stats(grid)
# stats["min"], stats["max"], stats["mean"], stats["std"], 
# stats["median"], stats["pct_nan"]

# Create empty grid with same shape
empty = grid_ops.create_empty_like(template, fill_value=0.0)
```

---

## Complete Example: Ensemble Wind Blending

```python
from utilities import grid_ops, grid_fetch

def blend_ensemble_wind(time_range, edit_area=None):
    """Blend wind from multiple models with full diagnostics."""
    
    # Fetch model winds
    models = {
        "GFS": grid_fetch.get_model_wind("GFS", time_range),
        "ECMWF": grid_fetch.get_model_wind("ECMWF", time_range),
        "NAM": grid_fetch.get_model_wind("NAM", time_range),
        "CMC": grid_fetch.get_model_wind("CMC", time_range),
    }
    
    # Filter out any that failed to load
    valid_models = {k: v for k, v in models.items() if v[0] is not None}
    wind_grids = list(valid_models.values())
    model_names = list(valid_models.keys())
    
    # Extract just magnitudes for scalar stats
    magnitudes = [w[0] for w in wind_grids]
    
    # Calculate diagnostics
    spread = grid_ops.ensemble_spread(magnitudes)
    confidence = grid_ops.ensemble_confidence(magnitudes)
    prob_gale = grid_ops.prob_exceeds(magnitudes, 34.0)
    
    # Blend using spread-weighted mean (downweight outliers)
    blended = grid_ops.weighted_by_spread(magnitudes)
    
    # Blend direction via vectors
    _, blended_dir = grid_ops.blend_vector(wind_grids)
    
    # Smooth the result
    blended = grid_ops.smooth_gaussian(blended, sigma=0.7)
    
    # Apply edit area if provided
    if edit_area is not None:
        old_wind = grid_fetch.get_gfe_wind(time_range)
        blended = grid_ops.apply_edit_area(
            blended, old_wind[0], edit_area, taper_width=5
        )
    
    return {
        "wind_speed": blended,
        "wind_dir": blended_dir,
        "spread": spread,
        "confidence": confidence,
        "prob_gale": prob_gale,
    }
```

---

## Function Reference

### Blending
| Function | Description |
|----------|-------------|
| `blend_scalar()` | Blend scalar grids with various strategies |
| `blend_vector()` | Blend wind vectors using U/V decomposition |
| `normalize_weights()` | Normalize weights to sum to 1.0 |
| `filter_valid_grids()` | Remove None grids from sequence |

### Ensemble Statistics
| Function | Description |
|----------|-------------|
| `ensemble_mean()` | Weighted or unweighted mean |
| `ensemble_median()` | Median (outlier resistant) |
| `ensemble_max()` / `ensemble_min()` | Extremes |
| `ensemble_std()` | Standard deviation |
| `ensemble_percentile()` | Nth percentile |
| `ensemble_range()` | (min, max) tuple |
| `ensemble_percentile_range()` | (p_low, p_high) tuple |
| `ensemble_spread()` | max - min |
| `ensemble_iqr()` | Interquartile range |
| `ensemble_agreement()` | Model agreement 0-100% |
| `ensemble_confidence()` | Composite confidence index |

### Probability
| Function | Description |
|----------|-------------|
| `prob_exceeds()` | P(value > threshold) |
| `prob_below()` | P(value < threshold) |
| `prob_between()` | P(low < value < high) |
| `prob_category()` | Probabilities for each category |
| `prob_wind_categories()` | Standard wind categories |
| `prob_wave_categories()` | Standard wave categories |

### Weighted Methods
| Function | Description |
|----------|-------------|
| `trimmed_mean()` | Exclude extremes before averaging |
| `weighted_by_spread()` | Weight by closeness to consensus |
| `weighted_by_consistency()` | Weight by run-to-run stability |

### Smoothing
| Function | Description |
|----------|-------------|
| `smooth_gaussian()` | Gaussian filter |
| `smooth_uniform()` | Box filter |
| `smooth_vector()` | Smooth wind magnitude/direction |

### Edit Area
| Function | Description |
|----------|-------------|
| `apply_edit_area()` | Apply changes within mask |
| `apply_edit_area_vector()` | Vector version with U/V blending |
| `create_taper()` | Create gradient from mask edge |
| `expand_mask()` / `shrink_mask()` | Dilate/erode mask |

### Utilities
| Function | Description |
|----------|-------------|
| `mag_dir_to_uv()` | Convert to U/V components |
| `uv_to_mag_dir()` | Convert from U/V components |
| `clip_values()` | Clip to range |
| `fill_missing()` | Fill NaN values |
| `get_grid_stats()` | Calculate grid statistics |
