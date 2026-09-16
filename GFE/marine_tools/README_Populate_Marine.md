# Populate_Marine - Marine Forecast Population Tool

Comprehensive tool for creating all marine forecast grids with meteorologically sound blending and physics-based adjustments.

## GUI Overview

```
┌─────────────────────────────────────────────────────────────┐
│  [Wind & Gust]  [Waves]  [Wx / Vis / Ice]                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Model weights, blend methods, and processing options       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [Populate Grids]  [Cancel]                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Tab 1: Wind & Gust

Creates `Wind` (vector) and `WindGust` (scalar) grids.

### Model Weights

| Model | Default | Notes |
|-------|---------|-------|
| GFS | 5 | Global model, good for synoptic patterns |
| ECMWF | 5 | Often best for medium range |
| NAM | 0 | Better for mesoscale, shorter range |
| CMC | 0 | Canadian model |
| UKMET | 0 | UK Met Office |
| GEFS | 0 | GFS Ensemble mean |

Weights are relative (0-10 scale). Actual percentages shown in GUI.

### Blend Methods

| Method | Description | When to Use |
|--------|-------------|-------------|
| **Weighted Mean** | Standard weighted average | High confidence situations |
| **Spread-Weighted** | Downweights outliers | Moderate confidence |
| **Trimmed Mean** | Excludes extremes | One model is clearly wrong |
| **Median** | Middle value | Low confidence, want robust center |

### Stability-Based Wind Boost

**Purpose:** Models underestimate surface winds when cold air flows over warm water (unstable marine boundary layer).

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Enable boost | On/Off | On | Apply stability-based enhancement |
| Max Boost | 1.1-1.5 | 1.30 | Maximum boost multiplier |

**How it works:**
1. Calculates instability: `SST - T850`
2. Maps instability to boost factor (1.0 at neutral, up to max at very unstable)
3. Applies boost to blended wind magnitude
4. Direction is preserved

### Gust Calculation

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Base Gust Factor | 1.1-1.6 | 1.30 | Gust = Wind × Factor |
| Stability-aware | On/Off | On | Higher factor in unstable air |

**Stability-aware gust:** In unstable conditions, the gust factor increases by up to 0.15 (e.g., 1.30 → 1.45).

### Smoothing

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Apply smoothing | On/Off | On | Gaussian spatial smoothing |
| Sigma | 0.3-2.0 | 0.7 | Smoothing kernel size |

### Example Output

```
[Wind]
  Models: ['GFS', 'ECMWF']
  Boost applied to 28.3% of area
  Wind: mean=22.4 kt, max=48.2 kt
  Gust: mean=29.1 kt, max=62.7 kt
```

---

## Tab 2: Waves

Creates `WaveHeight` grid.

### Model Weights

| Model | Default | Notes |
|-------|---------|-------|
| GFSWAVE | 5 | GFS wave model |
| ECMWF | 5 | ECMWF wave model |
| CMC | 0 | Canadian wave model |
| NWPS | 0 | Nearshore Wave Prediction System |

### Blend Methods

| Method | Description | When to Use |
|--------|-------------|-------------|
| **Weighted Mean** | Standard weighted average | Normal situations |
| **Spread-Weighted** | Downweights outliers | Models disagree |
| **Maximum** | Takes highest value | Conservative for hazards |
| **Median** | Middle value | Robust central estimate |

### Wave Enhancement

| Setting | Default | Description |
|---------|---------|-------------|
| Stability enhancement | Off | Enhance waves in unstable conditions |

**How it works:** Unstable boundary layer = enhanced momentum transfer = slightly higher wave growth. Factor typically 1.0-1.2.

### Example Output

```
[Waves]
  Models: ['GFSWAVE', 'ECMWF']
  WaveHeight: mean=6.8 ft, max=14.2 ft
```

---

## Tab 3: Wx / Vis / Ice

Creates `Wx`, `Visibility`, and `IceAccretion` grids.

### Weather Grid (Wx)

| Setting | Options | Default | Description |
|---------|---------|---------|-------------|
| Populate Wx | On/Off | On | Create weather grid |
| Primary Model | GFS/ECMWF/NAM/Blend | GFS | Source for QPF, temp |
| Include thunder | On/Off | On | Add thunderstorms where CAPE+precip |
| Include fog | On/Off | On | Add fog from stability analysis |

**Weather determination logic:**
1. **Thunder:** CAPE > 1000 J/kg + precipitation → Iso/Sct T
2. **Precipitation:** QPF-based coverage and intensity, temp-based type (R vs S)
3. **Fog:** Stability-based fog potential > 50% → Patchy F

### Visibility

| Setting | Options | Default | Description |
|---------|---------|---------|-------------|
| Populate Vis | On/Off | On | Create visibility grid |
| Method | model/derived/blend | model | How to calculate |

**Visibility methods:**
- **Model:** Use model visibility directly
- **Derived:** Calculate from fog potential (stability-based)
- **Blend:** Average of model and derived

### Ice Accretion

| Setting | Options | Default | Description |
|---------|---------|---------|-------------|
| Populate Ice | On/Off | On | Create ice accretion grid |
| Algorithm | Overland/Comiso | Overland | Ice calculation method |

**Ice Accretion Conditions:**
- Air temperature < -1.7°C
- Wind speed ≥ 15 kt
- SST < 7°C (if available)

**Algorithms:**
- **Overland (1990):** Standard NWS method based on wind, temp, SST
- **Comiso-Sullivan:** Enhanced with wave spray contribution

### Example Output

```
[Weather]
  Wx grid populated
[Visibility]
  Visibility: min=2.3 NM
[Ice Accretion]
  IceAccretion: 12.4% of area has icing potential
```

---

## Complete Usage Example

### Scenario: Strong Cold Air Outbreak

```
1. Run Assess_Marine first:
   - WindConfidence: 65% (moderate)
   - Instability: mean 8.2 K (very unstable)
   - ProbWindGale: max 85%

2. Run Populate_Marine:
   
   Wind & Gust tab:
   - GFS: 5, ECMWF: 5 (equal weight)
   - Blend Method: Spread-Weighted
   - Enable boost: ON
   - Max Boost: 1.35 (increase for strong instability)
   - Base Gust Factor: 1.35
   - Stability-aware gust: ON
   
   Waves tab:
   - GFSWAVE: 5, ECMWF: 5
   - Blend Method: Maximum (conservative for hazard)
   - Stability enhancement: ON
   
   Wx/Vis/Ice tab:
   - Wx: ON, Include thunder: OFF (cold air)
   - Visibility: ON, Method: derived (fog unlikely)
   - Ice: ON, Algorithm: Comiso (high winds)

3. Review output grids for quality
```

---

## Technical Details

### Wind Blending Algorithm

```python
# Fetch models
wind_grids = [fetch_wind(model) for model in selected_models]

# Blend based on method
if method == "weighted":
    mag, dir = grid_ops.blend_vector(wind_grids, weights)
elif method == "spread_weighted":
    mag = grid_ops.weighted_by_spread([g[0] for g in wind_grids])
    _, dir = grid_ops.blend_vector(wind_grids, weights)
elif method == "trimmed":
    mag = grid_ops.trimmed_mean([g[0] for g in wind_grids])
    _, dir = grid_ops.blend_vector(wind_grids, weights)
elif method == "median":
    mag = grid_ops.ensemble_median([g[0] for g in wind_grids])
    _, dir = grid_ops.blend_vector(wind_grids, weights)

# Apply stability boost
if enable_boost:
    stability = stability_blend.analyze_stability(sst, t850)
    mag = mag * stability.boost_factor

# Smooth
if smooth:
    mag = grid_ops.smooth_gaussian(mag, sigma=sigma)
```

### Ice Accretion Formula (Overland)

```python
# Conditions
temp_ok = temp_c < -1.7
wind_ok = wind_kt >= 15
sst_ok = sst_c < 7.0

# Rate calculation (simplified)
where_icing = temp_ok & wind_ok & sst_ok
temp_diff = sst - temp_c  # Heat available for freezing
wind_factor = (wind_kt - 15) / 50
temp_factor = temp_diff / 20
rate = wind_factor * temp_factor * 0.5  # inches/hour

# Wave enhancement
wave_factor = clip(wave_ft / 10, 1.0, 1.5)
rate = rate * wave_factor
```

### Data Flow

```
Model Data (GFS, ECMWF, etc.)
         │
         ▼
┌─────────────────────┐
│  grid_fetch.py      │  ← Retrieves grids from D2D/GFE
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  grid_ops.py        │  ← Blending, smoothing, statistics
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  stability_blend.py │  ← Boost calculation
└─────────────────────┘
         │
         ▼
     Fcst Grids
```
