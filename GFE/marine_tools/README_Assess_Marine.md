# Assess_Marine - Marine Assessment Tool

Comprehensive diagnostic tool for understanding the forecast situation before creating grids.

**Run this FIRST** to assess model confidence, stability conditions, and hazard probabilities.

## GUI Overview

The tool uses a tabbed interface with three assessment sections:

```
┌─────────────────────────────────────────────────────────────┐
│  [Model Confidence] [Marine Stability] [Hazard Probability] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Section-specific options and output selections             │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [Run Assessment]  [Cancel]                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Tab 1: Model Confidence

Analyzes ensemble agreement across selected models.

### Settings

| Option | Description | Default |
|--------|-------------|---------|
| Wind Models | Models to include in wind analysis | GFS, ECMWF, NAM |
| Wave Models | Models to include in wave analysis | All |

### Output Grids

| Grid | Range | Description |
|------|-------|-------------|
| `WindConfidence` | 0-100% | Composite confidence index |
| `WindSpread` | 0-50 kt | Max - min across models |
| `WaveConfidence` | 0-100% | Wave model agreement |
| `WaveSpread` | 0-20 ft | Wave model spread |
| `ModelAgreement` | 0-100% | Simple agreement metric |

### Interpretation

| WindConfidence | WindSpread | Interpretation | Action |
|----------------|------------|----------------|--------|
| >80% | <8 kt | High confidence | Use weighted blend |
| 60-80% | 8-12 kt | Moderate confidence | Use spread-weighted blend |
| 40-60% | 12-18 kt | Low confidence | Consider scenarios |
| <40% | >18 kt | Very low confidence | Use scenarios |

### Example Output

```
[Confidence Assessment]
  WindConfidence: mean=72.3%
  WindSpread: mean=8.5 kt, max=22.1 kt
  WaveConfidence: mean=68.1%
  WaveSpread: mean=3.2 ft
```

---

## Tab 2: Marine Stability

Calculates atmospheric stability from SST and upper-air temperatures.

### Settings

| Option | Description | Default |
|--------|-------------|---------|
| SST Source | Where to get sea surface temperature | RTOFS |
| Upper Air Source | Model for T850/T925 | GFS |
| Max Boost Factor | Maximum wind boost multiplier | 1.35 |

### Output Grids

| Grid | Range | Description |
|------|-------|-------------|
| `Instability` | -15 to 20 K | SST - T850 (positive = unstable) |
| `WindBoostFactor` | 1.0-1.5 | Calculated boost multiplier |
| `StabilityClass` | 0-4 | Categorical stability |
| `MixingPotential` | 0-100% | Vertical mixing strength |
| `FogPotential` | 0-100% | Advection fog likelihood |

### Stability Classes

| Value | Class | Instability | Effect |
|-------|-------|-------------|--------|
| 0 | Very Stable | < -5 K | Suppressed mixing, fog likely |
| 1 | Stable | -5 to -2 K | Limited vertical exchange |
| 2 | Neutral | -2 to 5 K | Normal conditions |
| 3 | Unstable | 5 to 10 K | Enhanced momentum transfer |
| 4 | Very Unstable | > 10 K | Strong convective mixing |

### Example Output

```
[Stability Assessment]
  Unstable conditions - enhanced momentum transfer likely
  Instability: mean=6.2 K
  WindBoostFactor: 34.2% of area will be boosted
  FogPotential: max=12.3%
```

---

## Tab 3: Hazard Probability

Calculates probability of exceeding critical thresholds.

### Wind Hazard Probabilities

| Output Grid | Threshold | Headline |
|-------------|-----------|----------|
| `ProbWindSCA` | ≥21 kt | Small Craft Advisory |
| `ProbWindGale` | ≥34 kt | Gale Warning |
| `ProbWindStorm` | ≥48 kt | Storm Warning |
| `ProbWindHurricane` | ≥64 kt | Hurricane Force Wind Warning |

### Wave Hazard Probabilities

| Output Grid | Threshold | Headline |
|-------------|-----------|----------|
| `ProbWaveModerate` | ≥4 ft | — |
| `ProbWaveRough` | ≥8 ft | Hazardous Seas |
| `ProbWaveVeryRough` | ≥13 ft | Very Rough Seas |
| `ProbWaveHigh` | ≥20 ft | High Seas |

### Visibility Hazard Probabilities

| Output Grid | Threshold | Condition |
|-------------|-----------|-----------|
| `ProbVisDense` | <0.25 NM | Dense Fog |
| `ProbVisFog` | <1.0 NM | Fog |
| `ProbVisMist` | <3.0 NM | Mist/Haze |

### Example Output

```
[Hazard Probability Assessment]
  ProbWindGale (≥34kt): max=78%, area >50%: 23.1%
  ProbWindStorm (≥48kt): max=35%, area >50%: 2.4%
  ProbWaveRough (≥8ft): max=82%
```

---

## Usage Examples

### Basic Assessment

```python
# 1. Run Assess_Marine from GFE
# 2. Select time range
# 3. Enable all three tabs (default)
# 4. Click "Run Assessment"
# 5. Review output grids in GFE
```

### Focus on Hazard Probability Only

```python
# 1. Uncheck "Model Confidence" tab
# 2. Uncheck "Marine Stability" tab  
# 3. Keep "Hazard Probability" checked
# 4. Select desired hazard outputs
# 5. Run
```

### Custom Stability Analysis

```python
# 1. Go to "Marine Stability" tab
# 2. Change SST Source to "Fcst" (if you have better SST)
# 3. Change Upper Air Source to "Blend" (GFS+ECMWF average)
# 4. Adjust Max Boost Factor to 1.25 (more conservative)
# 5. Run
```

---

## Decision Matrix

Use the assessment results to decide your next step:

| WindConfidence | ProbWindGale | Recommendation |
|----------------|--------------|----------------|
| >70% | Any | Use `Populate_Marine` |
| 50-70% | <30% | Use `Populate_Marine` with spread-weighting |
| 50-70% | >30% | Consider `Analyze_Scenarios` |
| <50% | Any | Use `Analyze_Scenarios` |

| Instability | WindBoostFactor Area | Recommendation |
|-------------|---------------------|----------------|
| <2 K | <10% | Boost not needed |
| 2-5 K | 10-30% | Enable boost in Populate_Marine |
| >5 K | >30% | Enable boost, consider higher max |

---

## Technical Details

### Algorithms Used

**Confidence Calculation:**
```python
confidence = grid_ops.ensemble_confidence(wind_grids)
# Combines: spread factor, consistency factor, sample size factor
```

**Stability Analysis:**
```python
result = stability_blend.analyze_stability(sst, t850, boost_config=config)
# Returns: instability, stability_class, boost_factor, mixing_potential
```

**Probability Calculation:**
```python
prob = grid_ops.prob_exceeds(wind_grids, threshold)
# Returns: percentage of models exceeding threshold at each point
```

### Data Requirements

| Data | Required For | Source Priority |
|------|--------------|-----------------|
| SST | Stability | RTOFS → Fcst → RTGSST |
| T850 | Stability | GFS → ECMWF → Blend |
| T925 | Stability (optional) | Same as T850 |
| T2m, RH | Fog potential | GFS |
| Wind (multiple models) | Confidence, Hazard Prob | Selected models |
| Wave (multiple models) | Wave confidence/prob | Selected models |
