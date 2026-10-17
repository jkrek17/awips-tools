# Storm layers verification

Through 20261015 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs.

- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, `windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): blend 15% caught / 4% false alarm, core lift 49% / 15%.
- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.
- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone (cone sized to hold it about 2 in 3).
- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.

## Last 7 days (7 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 0% | - | 100% | 0% | 2 |
| +48 h | 0% | - | 100% | 0% | 2 |
| +72 h | 0% | - | 0% | - | 2 |
| +96 h | 0% | - | 50% | 0% | 2 |
| +120 h | 0% | - | 50% | 0% | 2 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 56% | 60% | 0.9x | 6270 |
| storm | 86% | 56% | 1.5x | 285 |
| hf | - | - | - | 0 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 100% | 10% | 100% | 65% | 9 |
| +48 h | 67% | 0% | 89% | 58% | 9 |
| +72 h | 67% | 0% | 78% | 42% | 9 |
| +96 h | 0% | - | 56% | 50% | 9 |
| +120 h | 11% | 50% | 11% | 80% | 9 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 62% | 66% | 0.9x | 49415 |
| storm | 73% | 16% | 4.6x | 2820 |
| hf | 33% | 5% | 7.0x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 14 | 50 km | 57% | +0.4 hPa | 1 |
| +48 h | 12 | 134 km | 58% | +1.0 hPa | 0 |
| +72 h | 11 | 202 km | 64% | +3.2 hPa | 1 |
| +96 h | 11 | 247 km | 55% | +3.5 hPa | 0 |
| +120 h | 10 | 275 km | 60% | +3.8 hPa | 0 |

### North Pacific

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 100% | 0% | 100% | 25% | 3 |
| +48 h | 67% | 0% | 67% | 33% | 3 |
| +72 h | 33% | 50% | 33% | 67% | 3 |
| +96 h | 0% | - | 0% | 100% | 3 |
| +120 h | 0% | - | 0% | - | 3 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 44% | 50% | 0.9x | 2245 |
| storm | 52% | 24% | 2.1x | 515 |
| hf | 12% | 35% | 0.3x | 95 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 70% | 22% | 70% | 59% | 10 |
| +48 h | 70% | 12% | 70% | 42% | 10 |
| +72 h | 20% | 33% | 30% | 40% | 10 |
| +96 h | 0% | - | 0% | 100% | 10 |
| +120 h | 0% | - | 0% | - | 10 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 55% | 47% | 1.2x | 19375 |
| storm | 45% | 15% | 3.0x | 830 |
| hf | 13% | 26% | 0.5x | 155 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 18 | 91 km | 56% | +0.9 hPa | 0 |
| +48 h | 16 | 91 km | 75% | +0.4 hPa | 0 |
| +72 h | 13 | 119 km | 77% | +0.8 hPa | 0 |
| +96 h | 17 | 243 km | 71% | +1.9 hPa | 0 |
| +120 h | 18 | 319 km | 78% | +1.8 hPa | 1 |

## Last 30 days (10 days)

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
| +24 h | 90% | 10% | 90% | 68% | 10 |
| +48 h | 60% | 0% | 80% | 62% | 10 |
| +72 h | 60% | 0% | 70% | 46% | 10 |
| +96 h | 0% | - | 50% | 55% | 10 |
| +120 h | 10% | 50% | 10% | 88% | 10 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 62% | 66% | 0.9x | 54915 |
| storm | 72% | 15% | 4.9x | 2860 |
| hf | 33% | 5% | 7.0x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 20 | 62 km | 50% | +0.5 hPa | 1 |
| +48 h | 18 | 142 km | 56% | +1.1 hPa | 0 |
| +72 h | 17 | 189 km | 65% | +2.5 hPa | 1 |
| +96 h | 15 | 231 km | 53% | +2.2 hPa | 0 |
| +120 h | 14 | 240 km | 64% | +2.3 hPa | 0 |

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
| +24 h | 70% | 12% | 87% | 43% | 30 |
| +48 h | 60% | 18% | 87% | 30% | 30 |
| +72 h | 30% | 10% | 60% | 36% | 30 |
| +96 h | 7% | 33% | 23% | 56% | 30 |
| +120 h | 13% | 64% | 13% | 69% | 30 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 78% | 62% | 1.3x | 63290 |
| storm | 68% | 12% | 5.4x | 3985 |
| hf | 18% | 4% | 5.1x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 30 | 74 km | 63% | +0.8 hPa | 0 |
| +48 h | 28 | 92 km | 82% | +0.8 hPa | 0 |
| +72 h | 24 | 107 km | 83% | +1.0 hPa | 1 |
| +96 h | 27 | 211 km | 70% | +1.5 hPa | 1 |
| +120 h | 29 | 326 km | 62% | +0.7 hPa | 2 |

## All days (10 days)

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
| +24 h | 90% | 10% | 90% | 68% | 10 |
| +48 h | 60% | 0% | 80% | 62% | 10 |
| +72 h | 60% | 0% | 70% | 46% | 10 |
| +96 h | 0% | - | 50% | 55% | 10 |
| +120 h | 10% | 50% | 10% | 88% | 10 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 62% | 66% | 0.9x | 54915 |
| storm | 72% | 15% | 4.9x | 2860 |
| hf | 33% | 5% | 7.0x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 20 | 62 km | 50% | +0.5 hPa | 1 |
| +48 h | 18 | 142 km | 56% | +1.1 hPa | 0 |
| +72 h | 17 | 189 km | 65% | +2.5 hPa | 1 |
| +96 h | 15 | 231 km | 53% | +2.2 hPa | 0 |
| +120 h | 14 | 240 km | 64% | +2.3 hPa | 0 |

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
| +24 h | 70% | 12% | 87% | 43% | 30 |
| +48 h | 60% | 18% | 87% | 30% | 30 |
| +72 h | 30% | 10% | 60% | 36% | 30 |
| +96 h | 7% | 33% | 23% | 56% | 30 |
| +120 h | 13% | 64% | 13% | 69% | 30 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 78% | 62% | 1.3x | 63290 |
| storm | 68% | 12% | 5.4x | 3985 |
| hf | 18% | 4% | 5.1x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 30 | 74 km | 63% | +0.8 hPa | 0 |
| +48 h | 28 | 92 km | 82% | +0.8 hPa | 0 |
| +72 h | 24 | 107 km | 83% | +1.0 hPa | 1 |
| +96 h | 27 | 211 km | 70% | +1.5 hPa | 1 |
| +120 h | 29 | 326 km | 62% | +0.7 hPa | 2 |

