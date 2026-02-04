# Stability and Wind Boosting Utility Module

Atmospheric stability calculations and stability-dependent wind adjustments. This module contains the meteorological/scientific logic while `grid_ops` handles underlying array operations.

## Quick Start

```python
from utilities import stability_blend

# Calculate instability from SST and 850mb temperature
instability = stability_blend.calc_sst_instability(sst, t850)

# Boost winds in unstable areas
boosted_wind = stability_blend.boost_winds_by_stability(
    wind_speed, instability
)

# Complete analysis in one call
result = stability_blend.analyze_stability(sst, t850, cape=cape)
```

---

## Instability Calculations

### SST-Based Instability (Primary Method)

The SST instability index represents how much warmer the ocean is compared to the air aloft. Positive values indicate unstable conditions with potential for enhanced vertical mixing and momentum transfer.

```python
# Basic SST - T850 difference
instability = stability_blend.calc_sst_instability(sst, t850)

# Use 925mb instead
instability = stability_blend.calc_sst_instability(sst, t925, level=925)

# Lapse-rate adjusted (accounts for expected cooling with height)
instability = stability_blend.calc_sst_instability(
    sst, t850, method="lapse"
)
```

**Interpretation of instability values:**
| Value | Condition | Effect |
|-------|-----------|--------|
| > 10 | Very unstable | Strong convective potential |
| 5–10 | Unstable | Good vertical mixing |
| 2–5 | Slightly unstable | Some mixing |
| -2 to 2 | Neutral | — |
| < -2 | Stable | Suppressed vertical motion |

### Dual-Level Instability

Combine 850mb and 925mb for more robust estimates:

```python
instability = stability_blend.calc_dual_level_instability(
    sst, t850, t925,
    weights=(0.6, 0.4)  # Weight 850mb more
)
```

### CAPE-Based Instability

Convert CAPE to a normalized instability index:

```python
# Normalized to 0-10 scale
cape_inst = stability_blend.calc_cape_instability(cape)

# Raw CAPE values
cape_raw = stability_blend.calc_cape_instability(cape, normalize=False)
```

### Combined Instability

Merge SST-based and CAPE-based indices:

```python
combined = stability_blend.calc_combined_instability(
    sst_instability, cape,
    sst_weight=0.7,
    cape_weight=0.3
)
```

---

## Stability Classification

Convert continuous instability to discrete categories:

```python
# Get integer classification grid
classes = stability_blend.classify_stability(instability)

# Classes:
# 0 = Very Stable
# 1 = Stable
# 2 = Neutral
# 3 = Unstable
# 4 = Very Unstable

# Convert to text
label = stability_blend.stability_to_text(3)  # "Unstable"
```

### Custom Thresholds

```python
custom = {
    "very_stable": -8.0,
    "stable": -3.0,
    "unstable": 4.0,
    "very_unstable": 8.0,
}
classes = stability_blend.classify_stability(instability, thresholds=custom)
```

---

## Wind Boosting

Wind speeds from models often underestimate surface winds in unstable conditions due to enhanced momentum transfer from aloft. The boost factor compensates for this.

### Basic Boosting

```python
# Calculate boost factor from instability
boost = stability_blend.calc_boost_factor(instability)

# Apply to wind speed
boosted = stability_blend.boost_winds_scalar(wind_speed, boost)

# Or in one step
boosted = stability_blend.boost_winds_by_stability(wind_speed, instability)
```

### Vector Wind Boosting

For wind grids with magnitude and direction:

```python
wind_grid = (magnitude, direction)

# Boost magnitude, preserve direction
boosted_mag, boosted_dir = stability_blend.boost_winds_vector(
    wind_grid, boost_factor
)

# Or use the unified function (auto-detects vector input)
boosted = stability_blend.boost_winds_by_stability(wind_grid, instability)
```

### Configuring Boost Behavior

Use `BoostConfig` to customize the boost calculation:

```python
from utilities.stability_blend import BoostConfig

config = BoostConfig(
    min_factor=1.0,           # No boost in stable conditions
    max_factor=1.35,          # Max 35% boost in very unstable
    instability_threshold=3.0,  # Start boosting above this
    full_boost_threshold=10.0,  # Full boost above this
    use_cape=True,            # Include CAPE in calculation
    cape_weight=0.3,          # Weight for CAPE component
    smooth_result=True,       # Smooth the boost factor
    smooth_sigma=1.0          # Gaussian smoothing sigma
)

boosted = stability_blend.boost_winds_by_stability(
    wind_speed, instability, config=config, cape=cape_grid
)
```

### Applying Boost Only in Specific Areas

```python
# Only boost over water
water_mask = land_sea_mask == 0

boosted = stability_blend.boost_winds_by_stability(
    wind_speed, instability, mask=water_mask
)
```

### Conservative Boost in Stable Conditions

In stable marine boundary layers, momentum coupling is reduced—model winds may already be reasonable:

```python
boost = stability_blend.calc_boost_factor(instability, config)

# Reduce boost in stable areas
boost = stability_blend.suppress_boost_in_stable(
    boost, instability,
    stable_threshold=0.0,
    suppression_factor=0.5  # Cut boost effect in half
)
```

---

## Advanced Stability Metrics

### Bulk Richardson Number

Dynamic stability indicator based on potential temperature gradient and wind shear:

```python
ri = stability_blend.calc_bulk_richardson(
    theta_surface, theta_850, wind_speed_850
)

# Interpretation:
# Ri < 0: Convectively unstable
# 0 < Ri < 0.25: Dynamically unstable (turbulent)
# Ri > 0.25: Stable (laminar)
```

### Mixing Efficiency

Estimate of vertical mixing combining thermal and mechanical effects:

```python
efficiency = stability_blend.calc_mixing_efficiency(
    instability, wind_speed,
    wind_threshold=5.0  # Wind speed where mechanical mixing starts
)
# Returns 0-100%
```

### Convective Index

Multi-factor convective potential considering:
- SST-based instability (primary)
- Mid-level lapse rate (if T500 available)
- Moisture availability (if RH850 available)

```python
conv_index = stability_blend.calc_convective_index(
    sst, t850,
    t500=t500,      # Optional
    rh850=rh850     # Optional
)
# Returns 0-100 scale
```

---

## Marine-Specific Functions

### Air-Sea Temperature Difference

```python
diff = stability_blend.calc_air_sea_temperature_diff(sst, t2m)
# Positive = SST warmer (heat flux to atmosphere)
# Negative = SST cooler (stable marine layer)
```

### Marine Instability Index

Combined near-surface and lower-tropospheric stability:

```python
marine_inst = stability_blend.calc_marine_instability_index(
    sst, t2m, t850,
    include_surface=True  # Include air-sea diff
)
```

### Wave Enhancement

Estimate how instability affects wave growth (unstable conditions enhance air-sea momentum transfer):

```python
enhancement = stability_blend.estimate_wave_enhancement(
    wind_speed, instability,
    base_factor=1.0,
    max_factor=1.2
)

# Apply to wave heights
enhanced_waves = wave_height * enhancement
```

### Fog Potential

Advection fog forms when warm, moist air moves over cooler water:

```python
fog = stability_blend.calc_fog_potential(
    sst, t2m, rh,
    sst_t2m_threshold=-2.0,  # SST cooler than air
    rh_threshold=85.0
)
# Returns 0-100 potential
```

---

## Complete Analysis

Get all stability metrics in one call:

```python
from utilities.stability_blend import analyze_stability, BoostConfig

result = stability_blend.analyze_stability(
    sst, t850,
    t925=t925,        # Optional
    cape=cape,        # Optional
    boost_config=BoostConfig(max_factor=1.4)
)

# Result contains:
result.instability       # Raw instability index
result.stability_class   # Integer classification (0-4)
result.boost_factor      # Calculated boost multiplier
result.mixing_potential  # Vertical mixing potential (0-100)
result.description       # Human-readable summary
```

---

## Complete Example: Stability-Enhanced Wind Forecast

```python
from utilities import stability_blend, grid_ops, grid_fetch
from utilities.stability_blend import BoostConfig, analyze_stability

def create_stability_boosted_wind(time_range, edit_area=None):
    """
    Create wind forecast with stability-based enhancement.
    
    In unstable marine conditions, model winds often underestimate
    actual surface winds due to enhanced momentum transfer from
    the boundary layer. This applies a physics-based correction.
    """
    
    # Fetch required grids
    sst = grid_fetch.get_grid("RTGSST", "SST", time_range)
    t850 = grid_fetch.get_model_grid("GFS", "T", time_range, level=850)
    t925 = grid_fetch.get_model_grid("GFS", "T", time_range, level=925)
    cape = grid_fetch.get_model_grid("GFS", "CAPE", time_range)
    
    # Fetch model winds
    gfs_wind = grid_fetch.get_model_wind("GFS", time_range)
    ecmwf_wind = grid_fetch.get_model_wind("ECMWF", time_range)
    
    # Blend model winds
    blended_mag, blended_dir = grid_ops.blend_vector(
        [gfs_wind, ecmwf_wind],
        weights=[0.6, 0.4]
    )
    
    # Analyze stability
    config = BoostConfig(
        min_factor=1.0,
        max_factor=1.35,
        use_cape=True,
        cape_weight=0.25
    )
    
    stability = analyze_stability(
        sst, t850,
        t925=t925,
        cape=cape,
        boost_config=config
    )
    
    # Apply boost
    boosted_wind = (blended_mag, blended_dir)
    boosted_mag, boosted_dir = stability_blend.boost_winds_vector(
        boosted_wind, stability.boost_factor
    )
    
    # Smooth result
    boosted_mag = grid_ops.smooth_gaussian(boosted_mag, sigma=0.7)
    
    # Apply edit area if provided
    if edit_area is not None:
        old_wind = grid_fetch.get_gfe_wind(time_range)
        boosted_mag = grid_ops.apply_edit_area(
            boosted_mag, old_wind[0], edit_area, taper_width=5
        )
    
    return {
        "wind_speed": boosted_mag,
        "wind_dir": boosted_dir,
        "instability": stability.instability,
        "boost_factor": stability.boost_factor,
        "stability_class": stability.stability_class,
        "description": stability.description,
    }
```

---

## Constants Reference

The module provides physical constants for reference:

```python
from utilities import stability_blend

# Pressure level heights (meters)
stability_blend.PRESSURE_HEIGHTS[850]  # 1457 m
stability_blend.PRESSURE_HEIGHTS[925]  # 762 m

# CAPE thresholds (J/kg)
stability_blend.CAPE_LOW       # 500
stability_blend.CAPE_MODERATE  # 1000
stability_blend.CAPE_HIGH      # 2000
stability_blend.CAPE_EXTREME   # 3000

# Default boost factors
stability_blend.DEFAULT_BOOST_FACTOR  # 1.25
stability_blend.MAX_BOOST_FACTOR      # 1.50
```

---

## Function Reference

### Instability Calculations
| Function | Description |
|----------|-------------|
| `calc_sst_instability()` | SST vs upper-level temperature |
| `calc_dual_level_instability()` | Combined 850/925mb |
| `calc_cape_instability()` | CAPE-based index |
| `calc_combined_instability()` | Merge SST + CAPE |

### Classification
| Function | Description |
|----------|-------------|
| `classify_stability()` | Discrete categories (0-4) |
| `stability_to_text()` | Category to label |

### Wind Boosting
| Function | Description |
|----------|-------------|
| `calc_boost_factor()` | Instability to boost mapping |
| `boost_winds_scalar()` | Apply boost to speed grid |
| `boost_winds_vector()` | Apply boost to (mag, dir) |
| `boost_winds_by_stability()` | Main entry point |
| `suppress_boost_in_stable()` | Reduce boost in stable areas |

### Advanced Metrics
| Function | Description |
|----------|-------------|
| `calc_bulk_richardson()` | Richardson number |
| `calc_mixing_efficiency()` | Vertical mixing estimate |
| `calc_convective_index()` | Multi-factor convective potential |

### Marine Functions
| Function | Description |
|----------|-------------|
| `calc_air_sea_temperature_diff()` | SST - T2m |
| `calc_marine_instability_index()` | Combined marine stability |
| `estimate_wave_enhancement()` | Instability effect on waves |
| `calc_fog_potential()` | Advection fog potential |

### Analysis
| Function | Description |
|----------|-------------|
| `analyze_stability()` | Complete analysis, returns `StabilityResult` |

### Data Classes
| Class | Description |
|-------|-------------|
| `BoostConfig` | Configuration for boost calculation |
| `StabilityResult` | Complete analysis results |
| `StabilityClass` | Enum of stability categories |
