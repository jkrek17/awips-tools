# Storm layers verification

Through 20261126 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs.

- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, `windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): blend 15% caught / 4% false alarm, core lift 49% / 15%.
- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.
- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone (cone sized to hold it about 2 in 3).
- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.

## Last 7 days (7 days)

### North Atlantic

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 100% | 25% | 100% | 70% | 3 |
| +48 h | 100% | 25% | 100% | 70% | 3 |
| +72 h | 0% | 100% | 67% | 71% | 3 |
| +96 h | 0% | 100% | 0% | 100% | 3 |
| +120 h | 0% | 100% | 0% | 100% | 3 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 57% | 67% | 0.8x | 36170 |
| storm | 60% | 11% | 5.3x | 960 |
| hf | 20% | 1% | 33.2x | 10 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 17 | 73 km | 65% | -0.3 hPa | 1 |
| +48 h | 17 | 151 km | 59% | +1.8 hPa | 0 |
| +72 h | 20 | 203 km | 65% | +1.4 hPa | 0 |
| +96 h | 18 | 241 km | 61% | +0.3 hPa | 0 |
| +120 h | 14 | 329 km | 64% | -0.6 hPa | 0 |

### North Pacific

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 57% | 0% | 86% | 54% | 14 |
| +48 h | 36% | 0% | 93% | 46% | 14 |
| +72 h | 21% | 0% | 64% | 50% | 14 |
| +96 h | 0% | - | 43% | 33% | 14 |
| +120 h | 0% | - | 29% | 43% | 14 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 64% | 59% | 1.1x | 87265 |
| storm | 64% | 7% | 9.3x | 1450 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 17 | 78 km | 88% | -0.3 hPa | 0 |
| +48 h | 16 | 129 km | 75% | -0.7 hPa | 1 |
| +72 h | 17 | 192 km | 71% | -0.3 hPa | 1 |
| +96 h | 16 | 278 km | 56% | +0.8 hPa | 1 |
| +120 h | 17 | 246 km | 76% | +1.1 hPa | 1 |

## Last 30 days (28 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 0% | - | 33% | 0% | 3 |
| +48 h | 0% | - | 0% | - | 1 |
| +72 h | 0% | - | 0% | - | 1 |
| +96 h | 0% | - | 0% | - | 4 |
| +120 h | 0% | - | 0% | - | 4 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 41% | 38% | 1.1x | 11004 |
| storm | 0% | 0% | 1.7x | 418 |
| hf | - | - | - | 0 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 78% | 30% | 100% | 73% | 9 |
| +48 h | 67% | 40% | 89% | 73% | 9 |
| +72 h | 22% | 67% | 56% | 76% | 9 |
| +96 h | 9% | 67% | 27% | 79% | 11 |
| +120 h | 8% | 67% | 8% | 83% | 12 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 59% | 58% | 1.0x | 114760 |
| storm | 58% | 5% | 11.0x | 1343 |
| hf | 20% | 0% | 56.9x | 10 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 37 | 88 km | 62% | -0.4 hPa | 1 |
| +48 h | 32 | 142 km | 66% | +0.8 hPa | 2 |
| +72 h | 37 | 221 km | 68% | +0.5 hPa | 2 |
| +96 h | 38 | 252 km | 68% | +0.3 hPa | 2 |
| +120 h | 34 | 302 km | 71% | -0.1 hPa | 3 |

### North Pacific

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 29% | 0% | 71% | 29% | 7 |
| +48 h | 50% | 0% | 88% | 12% | 8 |
| +72 h | 38% | 0% | 75% | 25% | 8 |
| +96 h | 30% | 40% | 70% | 36% | 10 |
| +120 h | 10% | 67% | 10% | 67% | 10 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 75% | 75% | 1.0x | 14657 |
| storm | 35% | 36% | 1.0x | 2815 |
| hf | 0% | 0% | 0.8x | 68 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 70% | 18% | 91% | 65% | 46 |
| +48 h | 61% | 34% | 89% | 63% | 44 |
| +72 h | 50% | 27% | 77% | 63% | 44 |
| +96 h | 19% | 38% | 53% | 66% | 43 |
| +120 h | 12% | 17% | 37% | 62% | 41 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 73% | 58% | 1.2x | 293391 |
| storm | 65% | 6% | 11.6x | 5757 |
| hf | 0% | 0% | 13.7x | 226 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 66 | 64 km | 73% | -0.7 hPa | 0 |
| +48 h | 63 | 131 km | 63% | -1.0 hPa | 1 |
| +72 h | 58 | 173 km | 71% | -1.3 hPa | 2 |
| +96 h | 62 | 242 km | 74% | +0.2 hPa | 1 |
| +120 h | 54 | 303 km | 76% | +0.2 hPa | 1 |

## All days (50 days)

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
| +24 h | 80% | 18% | 97% | 66% | 35 |
| +48 h | 63% | 15% | 86% | 66% | 35 |
| +72 h | 37% | 35% | 69% | 68% | 35 |
| +96 h | 11% | 56% | 30% | 73% | 37 |
| +120 h | 11% | 50% | 16% | 74% | 38 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 63% | 62% | 1.0x | 272005 |
| storm | 67% | 9% | 7.8x | 5703 |
| hf | 30% | 3% | 10.0x | 245 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 87 | 72 km | 63% | -0.0 hPa | 2 |
| +48 h | 78 | 125 km | 63% | +1.0 hPa | 2 |
| +72 h | 80 | 191 km | 68% | +1.3 hPa | 3 |
| +96 h | 78 | 235 km | 68% | +1.5 hPa | 2 |
| +120 h | 74 | 275 km | 73% | +1.0 hPa | 4 |

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
| +24 h | 70% | 16% | 90% | 59% | 81 |
| +48 h | 59% | 29% | 85% | 55% | 79 |
| +72 h | 41% | 22% | 70% | 58% | 79 |
| +96 h | 14% | 42% | 41% | 66% | 78 |
| +120 h | 13% | 47% | 26% | 64% | 76 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 73% | 59% | 1.2x | 395296 |
| storm | 65% | 7% | 9.3x | 10037 |
| hf | 9% | 1% | 9.8x | 421 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 108 | 69 km | 66% | -0.3 hPa | 0 |
| +48 h | 100 | 122 km | 67% | -0.4 hPa | 1 |
| +72 h | 95 | 162 km | 72% | -0.2 hPa | 4 |
| +96 h | 102 | 233 km | 71% | +0.7 hPa | 3 |
| +120 h | 91 | 319 km | 69% | -0.3 hPa | 5 |

