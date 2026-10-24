# Storm layers verification

Through 20261022 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs.

- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, `windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): blend 15% caught / 4% false alarm, core lift 49% / 15%.
- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.
- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone (cone sized to hold it about 2 in 3).
- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.

## Last 7 days (7 days)

### North Atlantic

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 67% | 0% | 100% | 67% | 3 |
| +48 h | 67% | 0% | 67% | 80% | 3 |
| +72 h | 33% | 50% | 67% | 87% | 3 |
| +96 h | 0% | - | 0% | 100% | 3 |
| +120 h | 0% | - | 0% | 100% | 3 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 64% | 66% | 1.0x | 47100 |
| storm | 58% | 4% | 13.4x | 335 |
| hf | 18% | 9% | 2.0x | 40 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 13 | 55 km | 85% | +0.7 hPa | 0 |
| +48 h | 17 | 95 km | 76% | +1.2 hPa | 0 |
| +72 h | 13 | 119 km | 85% | +2.2 hPa | 0 |
| +96 h | 12 | 224 km | 67% | +2.7 hPa | 0 |
| +120 h | 10 | 209 km | 100% | +1.3 hPa | 1 |

### North Pacific

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 50% | 50% | 100% | 71% | 2 |
| +48 h | 50% | 50% | 50% | 75% | 2 |
| +72 h | 50% | 0% | 50% | 83% | 2 |
| +96 h | 0% | 100% | 100% | 88% | 1 |
| +120 h | 50% | 50% | 50% | 67% | 2 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 73% | 54% | 1.4x | 15514 |
| storm | 6% | 0% | 75.1x | 34 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 7 | 96 km | 29% | -0.3 hPa | 0 |
| +48 h | 5 | 198 km | 40% | -0.5 hPa | 0 |
| +72 h | 4 | 196 km | 75% | -2.3 hPa | 1 |
| +96 h | 6 | 203 km | 50% | -2.5 hPa | 1 |
| +120 h | 3 | 423 km | 67% | -4.8 hPa | 2 |

## Last 30 days (17 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 0% | - | 50% | 0% | 6 |
| +48 h | 0% | - | 50% | 0% | 6 |
| +72 h | 0% | - | 17% | 0% | 6 |
| +96 h | 0% | - | 33% | 0% | 6 |
| +120 h | 0% | - | 50% | 0% | 6 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 58% | 63% | 0.9x | 8240 |
| storm | 79% | 44% | 1.8x | 465 |
| hf | - | - | - | 0 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 85% | 8% | 92% | 68% | 13 |
| +48 h | 62% | 0% | 77% | 68% | 13 |
| +72 h | 54% | 12% | 69% | 68% | 13 |
| +96 h | 0% | - | 38% | 67% | 13 |
| +120 h | 8% | 50% | 8% | 89% | 13 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 63% | 66% | 1.0x | 102015 |
| storm | 71% | 12% | 5.8x | 3195 |
| hf | 31% | 5% | 6.1x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 33 | 59 km | 64% | +0.6 hPa | 1 |
| +48 h | 35 | 119 km | 66% | +1.2 hPa | 0 |
| +72 h | 30 | 159 km | 73% | +2.4 hPa | 1 |
| +96 h | 27 | 228 km | 59% | +2.4 hPa | 0 |
| +120 h | 24 | 227 km | 79% | +1.9 hPa | 1 |

### North Pacific

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 43% | 0% | 100% | 22% | 7 |
| +48 h | 29% | 0% | 43% | 25% | 7 |
| +72 h | 14% | 50% | 29% | 50% | 7 |
| +96 h | 0% | - | 14% | 67% | 7 |
| +120 h | 0% | 100% | 0% | 100% | 7 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 73% | 64% | 1.1x | 9155 |
| storm | 44% | 19% | 2.3x | 1360 |
| hf | 12% | 35% | 0.3x | 95 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 69% | 15% | 88% | 47% | 32 |
| +48 h | 59% | 21% | 84% | 34% | 32 |
| +72 h | 31% | 9% | 59% | 44% | 32 |
| +96 h | 6% | 50% | 26% | 67% | 31 |
| +120 h | 16% | 62% | 16% | 69% | 32 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 77% | 60% | 1.3x | 78804 |
| storm | 67% | 11% | 6.0x | 4019 |
| hf | 18% | 4% | 5.1x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 37 | 79 km | 57% | +0.6 hPa | 0 |
| +48 h | 33 | 108 km | 76% | +0.6 hPa | 0 |
| +72 h | 28 | 120 km | 82% | +0.5 hPa | 2 |
| +96 h | 33 | 209 km | 67% | +0.8 hPa | 2 |
| +120 h | 32 | 335 km | 62% | +0.2 hPa | 4 |

## All days (17 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 0% | - | 50% | 0% | 6 |
| +48 h | 0% | - | 50% | 0% | 6 |
| +72 h | 0% | - | 17% | 0% | 6 |
| +96 h | 0% | - | 33% | 0% | 6 |
| +120 h | 0% | - | 50% | 0% | 6 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 58% | 63% | 0.9x | 8240 |
| storm | 79% | 44% | 1.8x | 465 |
| hf | - | - | - | 0 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 85% | 8% | 92% | 68% | 13 |
| +48 h | 62% | 0% | 77% | 68% | 13 |
| +72 h | 54% | 12% | 69% | 68% | 13 |
| +96 h | 0% | - | 38% | 67% | 13 |
| +120 h | 8% | 50% | 8% | 89% | 13 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 63% | 66% | 1.0x | 102015 |
| storm | 71% | 12% | 5.8x | 3195 |
| hf | 31% | 5% | 6.1x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 33 | 59 km | 64% | +0.6 hPa | 1 |
| +48 h | 35 | 119 km | 66% | +1.2 hPa | 0 |
| +72 h | 30 | 159 km | 73% | +2.4 hPa | 1 |
| +96 h | 27 | 228 km | 59% | +2.4 hPa | 0 |
| +120 h | 24 | 227 km | 79% | +1.9 hPa | 1 |

### North Pacific

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 43% | 0% | 100% | 22% | 7 |
| +48 h | 29% | 0% | 43% | 25% | 7 |
| +72 h | 14% | 50% | 29% | 50% | 7 |
| +96 h | 0% | - | 14% | 67% | 7 |
| +120 h | 0% | 100% | 0% | 100% | 7 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 73% | 64% | 1.1x | 9155 |
| storm | 44% | 19% | 2.3x | 1360 |
| hf | 12% | 35% | 0.3x | 95 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 69% | 15% | 88% | 47% | 32 |
| +48 h | 59% | 21% | 84% | 34% | 32 |
| +72 h | 31% | 9% | 59% | 44% | 32 |
| +96 h | 6% | 50% | 26% | 67% | 31 |
| +120 h | 16% | 62% | 16% | 69% | 32 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 77% | 60% | 1.3x | 78804 |
| storm | 67% | 11% | 6.0x | 4019 |
| hf | 18% | 4% | 5.1x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 37 | 79 km | 57% | +0.6 hPa | 0 |
| +48 h | 33 | 108 km | 76% | +0.6 hPa | 0 |
| +72 h | 28 | 120 km | 82% | +0.5 hPa | 2 |
| +96 h | 33 | 209 km | 67% | +0.8 hPa | 2 |
| +120 h | 32 | 335 km | 62% | +0.2 hPa | 4 |

