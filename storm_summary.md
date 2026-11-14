# Storm layers verification

Through 20261112 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs.

- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, `windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): blend 15% caught / 4% false alarm, core lift 49% / 15%.
- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.
- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone (cone sized to hold it about 2 in 3).
- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.

## Last 7 days (6 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 0% | - | 0% | - | 2 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 68% | 27% | 2.5x | 134 |
| storm | 0% | - | 0.0x | 2 |
| hf | - | - | - | 0 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | - | - | - | 100% | 0 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 45% | 57% | 0.8x | 5938 |
| storm | - | 0% | - | 0 |
| hf | - | - | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 9 | 109 km | 33% | -0.3 hPa | 0 |
| +48 h | 8 | 125 km | 75% | +0.3 hPa | 0 |
| +72 h | 5 | 231 km | 80% | +1.5 hPa | 0 |
| +96 h | 4 | 270 km | 75% | +1.6 hPa | 0 |
| +120 h | 1 | 168 km | 100% | -2.4 hPa | 0 |

### North Pacific

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 0% | - | 50% | 50% | 2 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 74% | 78% | 0.9x | 1039 |
| storm | 98% | 35% | 2.8x | 63 |
| hf | - | - | - | 0 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 71% | 14% | 94% | 58% | 17 |
| +48 h | 64% | 22% | 82% | 55% | 11 |
| +72 h | 30% | 25% | 80% | 50% | 10 |
| +96 h | 0% | 100% | 50% | 60% | 8 |
| +120 h | 0% | - | 20% | 0% | 5 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 78% | 58% | 1.3x | 52245 |
| storm | 73% | 10% | 7.7x | 1796 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 20 | 64 km | 70% | -0.9 hPa | 0 |
| +48 h | 19 | 144 km | 53% | -0.7 hPa | 0 |
| +72 h | 10 | 211 km | 60% | +0.6 hPa | 0 |
| +96 h | 9 | 279 km | 67% | -0.1 hPa | 0 |
| +120 h | 3 | 494 km | 33% | +0.3 hPa | 0 |

## Last 30 days (28 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 38% | 0% | 73% | 17% | 26 |
| +48 h | 29% | 0% | 67% | 0% | 24 |
| +72 h | 12% | 0% | 50% | 20% | 24 |
| +96 h | 7% | 0% | 26% | 36% | 27 |
| +120 h | 4% | 0% | 11% | 0% | 27 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 60% | 61% | 1.0x | 75309 |
| storm | 53% | 33% | 1.6x | 7133 |
| hf | 39% | 34% | 1.1x | 530 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 83% | 9% | 100% | 59% | 24 |
| +48 h | 71% | 6% | 92% | 58% | 24 |
| +72 h | 50% | 25% | 83% | 63% | 24 |
| +96 h | 15% | 50% | 35% | 69% | 26 |
| +120 h | 15% | 43% | 22% | 60% | 27 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 64% | 63% | 1.0x | 158925 |
| storm | 71% | 10% | 7.4x | 4178 |
| hf | 36% | 4% | 9.9x | 200 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 44 | 73 km | 64% | -0.1 hPa | 0 |
| +48 h | 41 | 102 km | 71% | +0.9 hPa | 0 |
| +72 h | 37 | 167 km | 73% | +2.0 hPa | 1 |
| +96 h | 38 | 229 km | 76% | +2.9 hPa | 0 |
| +120 h | 37 | 268 km | 76% | +2.2 hPa | 2 |

### North Pacific

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 25% | 0% | 62% | 38% | 8 |
| +48 h | 44% | 0% | 78% | 12% | 9 |
| +72 h | 33% | 0% | 67% | 25% | 9 |
| +96 h | 27% | 40% | 64% | 36% | 11 |
| +120 h | 9% | 67% | 9% | 67% | 11 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 70% | 67% | 1.0x | 19157 |
| storm | 34% | 35% | 1.0x | 2895 |
| hf | 0% | 0% | 0.8x | 68 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 76% | 15% | 93% | 63% | 29 |
| +48 h | 63% | 19% | 78% | 57% | 27 |
| +72 h | 48% | 13% | 74% | 55% | 27 |
| +96 h | 35% | 36% | 62% | 67% | 26 |
| +120 h | 25% | 25% | 38% | 44% | 24 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 72% | 56% | 1.3x | 161971 |
| storm | 52% | 5% | 9.5x | 3077 |
| hf | 0% | 0% | 7.2x | 226 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 47 | 80 km | 57% | -0.7 hPa | 0 |
| +48 h | 45 | 139 km | 60% | -0.7 hPa | 0 |
| +72 h | 42 | 179 km | 67% | -0.0 hPa | 1 |
| +96 h | 44 | 238 km | 70% | -0.0 hPa | 1 |
| +120 h | 34 | 361 km | 68% | -2.0 hPa | 2 |

## All days (36 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 28% | 9% | 72% | 16% | 36 |
| +48 h | 21% | 0% | 59% | 0% | 34 |
| +72 h | 9% | 0% | 38% | 19% | 34 |
| +96 h | 5% | 0% | 24% | 31% | 37 |
| +120 h | 3% | 0% | 19% | 0% | 37 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 58% | 60% | 1.0x | 89939 |
| storm | 54% | 32% | 1.7x | 7973 |
| hf | 39% | 34% | 1.1x | 530 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 81% | 12% | 96% | 64% | 27 |
| +48 h | 63% | 6% | 85% | 63% | 27 |
| +72 h | 44% | 25% | 74% | 64% | 27 |
| +96 h | 14% | 50% | 31% | 71% | 29 |
| +120 h | 13% | 43% | 20% | 70% | 30 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 62% | 63% | 1.0x | 189525 |
| storm | 68% | 9% | 7.6x | 4508 |
| hf | 31% | 4% | 8.4x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 62 | 71 km | 60% | +0.1 hPa | 1 |
| +48 h | 57 | 116 km | 65% | +1.0 hPa | 0 |
| +72 h | 52 | 176 km | 69% | +1.9 hPa | 2 |
| +96 h | 50 | 233 km | 70% | +2.3 hPa | 0 |
| +120 h | 49 | 254 km | 76% | +1.4 hPa | 2 |

### North Pacific

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 41% | 0% | 82% | 26% | 17 |
| +48 h | 44% | 0% | 67% | 14% | 18 |
| +72 h | 22% | 20% | 56% | 29% | 18 |
| +96 h | 15% | 40% | 40% | 43% | 20 |
| +120 h | 5% | 80% | 5% | 83% | 20 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 70% | 66% | 1.0x | 29577 |
| storm | 38% | 26% | 1.4x | 4480 |
| hf | 7% | 11% | 0.6x | 163 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 73% | 14% | 90% | 53% | 59 |
| +48 h | 61% | 19% | 82% | 43% | 57 |
| +72 h | 39% | 12% | 68% | 47% | 57 |
| +96 h | 20% | 35% | 41% | 64% | 56 |
| +120 h | 19% | 47% | 24% | 55% | 54 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 75% | 58% | 1.3x | 215686 |
| storm | 61% | 8% | 7.2x | 7062 |
| hf | 9% | 1% | 6.2x | 421 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 71 | 71 km | 61% | -0.2 hPa | 0 |
| +48 h | 68 | 124 km | 68% | -0.1 hPa | 0 |
| +72 h | 61 | 154 km | 72% | +0.3 hPa | 2 |
| +96 h | 66 | 230 km | 70% | +0.5 hPa | 2 |
| +120 h | 57 | 354 km | 61% | -1.1 hPa | 4 |

