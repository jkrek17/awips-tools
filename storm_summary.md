# Storm layers verification

Through 20261119 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs.

- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, `windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): blend 15% caught / 4% false alarm, core lift 49% / 15%.
- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.
- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone (cone sized to hold it about 2 in 3).
- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.

## Last 7 days (7 days)

### North Atlantic

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 60% | 40% | 100% | 71% | 5 |
| +48 h | 40% | 50% | 80% | 75% | 5 |
| +72 h | 20% | 67% | 40% | 82% | 5 |
| +96 h | 0% | - | 40% | 71% | 5 |
| +120 h | 0% | - | 0% | - | 5 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 69% | 59% | 1.2x | 46310 |
| storm | 66% | 3% | 23.1x | 235 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 8 | 81 km | 88% | -0.5 hPa | 0 |
| +48 h | 4 | 158 km | 50% | -1.6 hPa | 2 |
| +72 h | 8 | 258 km | 62% | -3.1 hPa | 1 |
| +96 h | 10 | 236 km | 70% | -0.6 hPa | 2 |
| +120 h | 11 | 298 km | 73% | +0.9 hPa | 2 |

### North Pacific

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 75% | 40% | 100% | 80% | 8 |
| +48 h | 88% | 61% | 88% | 83% | 8 |
| +72 h | 88% | 46% | 88% | 82% | 8 |
| +96 h | 0% | 100% | 38% | 86% | 8 |
| +120 h | 0% | - | 38% | 85% | 8 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 75% | 60% | 1.2x | 92345 |
| storm | 86% | 5% | 18.8x | 1525 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 20 | 55 km | 65% | -0.5 hPa | 0 |
| +48 h | 16 | 110 km | 56% | -1.5 hPa | 0 |
| +72 h | 17 | 160 km | 71% | -1.9 hPa | 1 |
| +96 h | 20 | 206 km | 85% | +1.2 hPa | 0 |
| +120 h | 17 | 275 km | 88% | +1.2 hPa | 0 |

## Last 30 days (28 days)

### North Atlantic

**Peaks vs ascat**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 41% | 0% | 76% | 24% | 17 |
| +48 h | 33% | 0% | 60% | 0% | 15 |
| +72 h | 7% | 0% | 47% | 0% | 15 |
| +96 h | 11% | 0% | 22% | 43% | 18 |
| +120 h | 6% | 0% | 17% | 0% | 18 |

**Hazard lines vs ascat** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 56% | 59% | 0.9x | 48169 |
| storm | 49% | 35% | 1.4x | 4218 |
| hf | 20% | 1% | 21.0x | 5 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 73% | 16% | 100% | 60% | 22 |
| +48 h | 59% | 19% | 86% | 57% | 22 |
| +72 h | 32% | 36% | 68% | 62% | 22 |
| +96 h | 17% | 50% | 29% | 71% | 24 |
| +120 h | 12% | 40% | 20% | 50% | 25 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 62% | 59% | 1.1x | 137365 |
| storm | 62% | 5% | 11.3x | 1883 |
| hf | 18% | 1% | 18.9x | 40 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 44 | 81 km | 66% | -0.2 hPa | 0 |
| +48 h | 34 | 114 km | 68% | +0.8 hPa | 2 |
| +72 h | 35 | 200 km | 69% | +0.9 hPa | 2 |
| +96 h | 39 | 242 km | 77% | +1.7 hPa | 2 |
| +120 h | 39 | 281 km | 74% | +1.2 hPa | 3 |

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
| gale | 70% | 70% | 1.0x | 16367 |
| storm | 35% | 36% | 1.0x | 2815 |
| hf | 0% | 0% | 0.8x | 68 |

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 75% | 23% | 94% | 68% | 36 |
| +48 h | 68% | 38% | 79% | 68% | 34 |
| +72 h | 56% | 30% | 76% | 68% | 34 |
| +96 h | 24% | 43% | 55% | 73% | 33 |
| +120 h | 16% | 17% | 35% | 66% | 31 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 75% | 59% | 1.3x | 241966 |
| storm | 64% | 5% | 12.3x | 4572 |
| hf | 0% | 0% | 11.7x | 226 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 57 | 60 km | 63% | -0.8 hPa | 0 |
| +48 h | 53 | 128 km | 60% | -0.9 hPa | 0 |
| +72 h | 51 | 170 km | 71% | -0.7 hPa | 1 |
| +96 h | 54 | 227 km | 78% | +0.5 hPa | 0 |
| +120 h | 43 | 333 km | 72% | -1.0 hPa | 0 |

## All days (43 days)

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
| +24 h | 78% | 17% | 97% | 65% | 32 |
| +48 h | 59% | 14% | 84% | 65% | 32 |
| +72 h | 41% | 32% | 69% | 67% | 32 |
| +96 h | 12% | 50% | 32% | 71% | 34 |
| +120 h | 11% | 43% | 17% | 70% | 35 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 63% | 62% | 1.0x | 235835 |
| storm | 68% | 8% | 8.3x | 4743 |
| hf | 31% | 3% | 9.0x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 70 | 72 km | 63% | +0.0 hPa | 1 |
| +48 h | 61 | 118 km | 64% | +0.8 hPa | 2 |
| +72 h | 60 | 187 km | 68% | +1.3 hPa | 3 |
| +96 h | 60 | 234 km | 70% | +1.8 hPa | 2 |
| +120 h | 60 | 262 km | 75% | +1.3 hPa | 4 |

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
| +24 h | 73% | 18% | 91% | 60% | 67 |
| +48 h | 65% | 31% | 83% | 57% | 65 |
| +72 h | 45% | 24% | 71% | 59% | 65 |
| +96 h | 17% | 42% | 41% | 69% | 64 |
| +120 h | 16% | 47% | 26% | 67% | 62 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 75% | 59% | 1.3x | 308031 |
| storm | 65% | 7% | 9.3x | 8587 |
| hf | 9% | 1% | 8.7x | 421 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 91 | 67 km | 62% | -0.2 hPa | 0 |
| +48 h | 84 | 121 km | 65% | -0.3 hPa | 0 |
| +72 h | 78 | 156 km | 72% | -0.2 hPa | 3 |
| +96 h | 86 | 225 km | 73% | +0.7 hPa | 2 |
| +120 h | 74 | 336 km | 68% | -0.6 hPa | 4 |

