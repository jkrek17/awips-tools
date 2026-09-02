# Analyze_Scenarios - Scenario Analysis with Hazard Suggestions

Ensemble scenario analysis tool for communicating forecast uncertainty when model spread is high.

**Use when:** Model confidence is low and you need to show the range of possible outcomes.

## GUI Overview

```
┌─────────────────────────────────────────────────────────────┐
│  [Wind Scenarios]  [Wave Scenarios]  [Hazard Suggestions]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Model selection, percentiles, and output options           │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [Analyze Scenarios]  [Cancel]                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Tab 1: Wind Scenarios

Creates Low/Likely/High wind scenario grids.

### Settings

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Models | Multi-select | GFS, ECMWF, NAM, CMC | Models for scenarios |
| Low Percentile | 5-30 | 10 | Percentile for low scenario |
| High Percentile | 70-95 | 90 | Percentile for high scenario |

### Output Grids

| Grid | Description | Use |
|------|-------------|-----|
| `WindLow` | 10th percentile wind | "If conditions are weaker than expected" |
| `WindLikely` | Median wind | "Most likely outcome" |
| `WindHigh` | 90th percentile wind | "If conditions are stronger than expected" |
| `WindScenarioSpread` | High - Low | Shows uncertainty magnitude |

### Interpretation

The scenarios represent the **reasonable range** of outcomes:
- **WindLow:** 90% of models are higher than this
- **WindLikely:** Half the models are higher, half lower
- **WindHigh:** Only 10% of models are higher than this

### Example Output

```
[Wind Scenarios]
  WindLow (10th pct): mean=18.2 kt
  WindLikely (median): mean=24.6 kt
  WindHigh (90th pct): mean=32.1 kt
  Scenario spread: mean=13.9 kt
```

---

## Tab 2: Wave Scenarios

Creates Low/Likely/High wave scenario grids.

### Settings

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Models | Multi-select | All wave models | Models for scenarios |
| Low Percentile | 5-30 | 10 | Percentile for low scenario |
| High Percentile | 70-95 | 90 | Percentile for high scenario |

### Output Grids

| Grid | Description |
|------|-------------|
| `WaveLow` | 10th percentile waves |
| `WaveLikely` | Median waves |
| `WaveHigh` | 90th percentile waves |
| `WaveScenarioSpread` | High - Low spread |

---

## Tab 3: Hazard Suggestions

Creates hazard grids and headline recommendations based on probability analysis.

### Probability Thresholds

| Setting | Default | Description |
|---------|---------|-------------|
| Likely | 60% | Threshold for "mention in headline" |
| Possible | 30% | Threshold for "consider/monitor" |

### Output Grids

| Grid | Description |
|------|-------------|
| `SuggestedWindHazard` | Hazard level where prob ≥ "likely" threshold |
| `MaxWindHazard` | Highest hazard where prob ≥ "possible" threshold |
| `SuggestedWaveHazard` | Wave hazard based on "likely" probability |

### Hazard Level Encoding

| Value | Wind Hazard | Wave Hazard |
|-------|-------------|-------------|
| 0 | None | None |
| 1 | Small Craft Advisory (≥21 kt) | SCA (≥5 ft) |
| 2 | Gale Warning (≥34 kt) | Rough Seas (≥8 ft) |
| 3 | Storm Warning (≥48 kt) | Very Rough (≥13 ft) |
| 4 | Hurricane Force (≥64 kt) | High Seas (≥20 ft) |

### Headline Report

When enabled, generates a text summary with recommendations:

```
HEADLINE ANALYSIS REPORT
========================================

WIND HAZARDS:
--------------------
  Hurricane Force Wind Warning: UNLIKELY (max prob: 5%)
  Storm Warning: POSSIBLE (max prob: 42%)
  Gale Warning: LIKELY (max prob: 78%)
  Small Craft Advisory: LIKELY (max prob: 95%)

WAVE HAZARDS:
--------------------
  High Seas: UNLIKELY (max prob: 8%)
  Very Rough Seas: POSSIBLE (max prob: 35%)
  Rough Seas: LIKELY (max prob: 82%)

SUMMARY:
--------------------
  Primary headline: Gale Warning
  Consider upgrade to: Storm Warning (if trend continues)

Hazard levels: 0=None, 1=SCA, 2=Gale, 3=Storm, 4=Hurricane
```

---

## When to Use Scenarios

### Decision Tree

```
                    ┌─────────────────────┐
                    │ Run Assess_Marine   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Check WindConfidence │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
        Confidence >70%   50-70%          <50%
              │                │                │
              ▼                ▼                ▼
    ┌─────────────────┐ ┌──────────────┐ ┌──────────────────┐
    │ Populate_Marine │ │ Either tool  │ │ Analyze_Scenarios│
    │ (deterministic) │ │ depending on │ │ (show range)     │
    └─────────────────┘ │ situation    │ └──────────────────┘
                        └──────────────┘
```

### Specific Situations

**Use Analyze_Scenarios when:**
- WindSpread > 15 kt
- WindConfidence < 50%
- ProbWindGale/Storm spans wide range (e.g., 30-80%)
- Models show different timing/track solutions
- High-impact event with significant uncertainty

**Use Populate_Marine when:**
- WindSpread < 10 kt
- WindConfidence > 70%
- Models generally agree on solution
- Routine forecast situation

---

## Usage Examples

### Example 1: High Uncertainty Gale Event

```
Assess_Marine shows:
- WindConfidence: 42%
- WindSpread: 18 kt
- ProbWindGale: max 75%
- ProbWindStorm: max 40%

Action: Run Analyze_Scenarios

Results:
- WindLow: 28 kt (borderline gale)
- WindLikely: 38 kt (solid gale)
- WindHigh: 48 kt (borderline storm)
- SuggestedWindHazard: 2 (Gale)
- MaxWindHazard: 3 (Storm)

Messaging: "Gale Warning likely, Storm Warning possible if 
higher-end solutions verify"
```

### Example 2: Pre-Event Analysis

```
48 hours before potential storm:
- Run Analyze_Scenarios daily
- Track how scenarios evolve
- If WindHigh consistently shows Storm → prepare for upgrade
- If WindLow and WindHigh converging → confidence increasing
```

### Example 3: Custom Percentiles

```
For more conservative scenarios:
- Set Low Percentile: 20 (less extreme low end)
- Set High Percentile: 80 (less extreme high end)

For showing full range:
- Set Low Percentile: 5
- Set High Percentile: 95
```

---

## Technical Details

### Scenario Calculation

```python
# Fetch all model wind grids
wind_grids = [fetch(model, "Wind") for model in models]
magnitudes = [grid[0] for grid in wind_grids]

# Calculate percentile scenarios
low, high = grid_ops.ensemble_percentile_range(
    magnitudes, low_pct=10, high_pct=90
)
likely = grid_ops.ensemble_median(magnitudes)
spread = high - low
```

### Hazard Suggestion Logic

```python
# Calculate probability for each hazard
probs = {}
for hazard, threshold in HAZARDS.items():
    probs[hazard] = grid_ops.prob_exceeds(wind_grids, threshold)

# Assign hazard level where prob >= threshold
for hazard, prob in probs.items():
    level = HAZARD_LEVELS[hazard]
    mask = prob >= prob_likely_threshold
    result = where(mask & (level > result), level, result)
```

### Headline Report Generation

The report analyzes probabilities across all time periods:
1. Tracks maximum probability for each hazard
2. Classifies as LIKELY (≥60%), POSSIBLE (30-60%), or UNLIKELY (<30%)
3. Identifies primary headline (highest LIKELY hazard)
4. Identifies potential upgrade (highest POSSIBLE hazard above primary)

---

## Integration with Other Tools

### Typical Workflow

```
Day 1:
1. Assess_Marine → Low confidence, high spread
2. Analyze_Scenarios → Create WindLow/Likely/High
3. Review SuggestedWindHazard for initial headlines
4. Communicate uncertainty to partners

Day 2 (event approaches):
1. Assess_Marine → Confidence improving
2. Check if scenarios are converging
3. If confidence > 60%: Switch to Populate_Marine
4. If still uncertain: Update scenarios

Day 3 (during event):
1. Populate_Marine for deterministic forecast
2. Optional: Keep scenarios for extended outlook
```

### Combining Outputs

You can display scenario grids alongside deterministic forecast:
- Main `Wind` grid from Populate_Marine
- `WindHigh` from Analyze_Scenarios as "upper bound"
- `SuggestedWindHazard` for headline guidance
