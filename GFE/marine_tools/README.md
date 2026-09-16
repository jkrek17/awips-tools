# Marine Forecast Tools

A comprehensive suite of tools for marine weather forecasting with a focus on hazard assessment and uncertainty communication.

## Tool Overview

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `Assess_Marine.py` | Diagnostic assessment | **First** - understand the situation |
| `Populate_Marine.py` | Create forecast grids | When confidence is adequate |
| `Analyze_Scenarios.py` | Scenario analysis | When uncertainty is high |

## Recommended Workflow

```
┌─────────────────────────────────────────────────────────┐
│                 1. ASSESS_MARINE                        │
│  "What's the situation? How confident should I be?"     │
└────────────────────────┬────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│ If confidence HIGH:     │   │ If confidence LOW:      │
│                         │   │                         │
│  2. POPULATE_MARINE     │   │  3. ANALYZE_SCENARIOS   │
│  "Create the forecast"  │   │  "Show the range"       │
└─────────────────────────┘   └─────────────────────────┘
```

## Dependencies

These tools require the utility modules in `GFE/utilities/`:

- `grid_ops.py` - Grid operations (blending, ensemble stats, smoothing)
- `stability_blend.py` - Atmospheric stability and wind boosting
- `grid_fetch.py` - Model data retrieval
- `model_aliases.py` - Model configuration registry
- `thresholds.py` - Physical constants and thresholds

## Hazard Level Encoding

All tools use consistent hazard level encoding:

| Value | Wind Hazard | Threshold | Wave Hazard | Threshold |
|-------|-------------|-----------|-------------|-----------|
| 0 | None | — | None | — |
| 1 | Small Craft Advisory | ≥21 kt | Small Craft Advisory | ≥5 ft |
| 2 | Gale Warning | ≥34 kt | Rough Seas | ≥8 ft |
| 3 | Storm Warning | ≥48 kt | Very Rough Seas | ≥13 ft |
| 4 | Hurricane Force | ≥64 kt | High Seas | ≥20 ft |

## Quick Start

### 1. Assess the Situation

```python
# Run Assess_Marine first
# Select tabs: Confidence, Stability, Hazard Probability
# Review output grids:
#   - WindConfidence, WindSpread
#   - Instability, WindBoostFactor
#   - ProbWindGale, ProbWindStorm
```

### 2. Decide Your Approach

**If WindConfidence > 70% and WindSpread < 10 kt:**
→ Use `Populate_Marine` with weighted blend

**If WindConfidence < 50% or WindSpread > 15 kt:**
→ Use `Analyze_Scenarios` to show Low/Likely/High

**If WindSpread is moderate (10-15 kt):**
→ Use `Populate_Marine` with spread-weighted blend (downweights outliers)

### 3. Create Grids

```python
# Populate_Marine for deterministic forecast
#   Wind tab: Select models, set weights, enable stability boost
#   Wave tab: Select wave models, choose blend method
#   Wx tab: Enable Wx, Visibility, IceAccretion as needed

# OR

# Analyze_Scenarios for uncertainty communication
#   Wind Scenarios: Creates WindLow, WindLikely, WindHigh
#   Wave Scenarios: Creates WaveLow, WaveLikely, WaveHigh
#   Hazard Suggestions: Creates SuggestedWindHazard + headline report
```

## Key Features

### Stability-Based Wind Enhancement

Models often underestimate surface winds when cold air moves over warm water. The tools use SST-based instability to:

1. Calculate instability index: `SST - T850`
2. Derive boost factor (typically 1.0 - 1.35)
3. Apply boost to blended winds
4. Enhance gust factor in unstable conditions

### Ensemble-Based Uncertainty

When models disagree:

- **Spread** = max - min across models
- **Confidence** = composite index (0-100%)
- **Probabilities** = % of models exceeding threshold
- **Scenarios** = percentile-based Low/Likely/High

### Hazard Suggestions

The tools provide objective hazard recommendations:

- **Suggested Hazard**: Based on "likely" probability (default 60%)
- **Max Hazard**: Highest hazard with "possible" probability (default 30%)
- **Headline Report**: Text summary with RECOMMEND/CONSIDER guidance

## File Structure

```
GFE/marine_tools/
├── README.md                    # This file
├── README_Assess_Marine.md      # Detailed Assess_Marine docs
├── README_Populate_Marine.md    # Detailed Populate_Marine docs
├── README_Analyze_Scenarios.md  # Detailed Analyze_Scenarios docs
├── Assess_Marine.py             # Assessment tool
├── Populate_Marine.py           # Population tool
└── Analyze_Scenarios.py         # Scenario analysis tool
```

## See Also

- `GFE/utilities/README_grid_ops.md` - Grid operations reference
- `GFE/utilities/README_stability_blend.md` - Stability calculations reference
