# Storm layers verification

Through 20261104 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs.

- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, `windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): blend 15% caught / 4% false alarm, core lift 49% / 15%.
- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.
- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone (cone sized to hold it about 2 in 3).
- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.

## Last 7 days (7 days)

### North Atlantic

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 50% | 0% | 100% | 43% | 4 |
| +48 h | 50% | 33% | 75% | 62% | 4 |
| +72 h | 75% | 50% | 75% | 57% | 4 |
| +96 h | 25% | 50% | 25% | 80% | 4 |
| +120 h | 25% | 50% | 25% | 67% | 4 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 58% | 51% | 1.1x | 21680 |
| storm | 65% | 3% | 18.7x | 305 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 7 | 48 km | 100% | -0.9 hPa | 0 |
| +48 h | 4 | 115 km | 75% | -1.3 hPa | 0 |
| +72 h | 5 | 138 km | 100% | -1.1 hPa | 0 |
| +96 h | 7 | 184 km | 100% | -2.0 hPa | 0 |
| +120 h | 6 | 320 km | 83% | -2.7 hPa | 0 |

### North Pacific

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 92% | 21% | 92% | 58% | 12 |
| +48 h | 83% | 23% | 92% | 56% | 12 |
| +72 h | 92% | 15% | 92% | 48% | 12 |
| +96 h | 67% | 27% | 75% | 65% | 12 |
| +120 h | 42% | 17% | 58% | 36% | 12 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 79% | 59% | 1.3x | 79795 |
| storm | 14% | 2% | 7.6x | 1360 |
| hf | 0% | 0% | 1.1x | 330 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 22 | 54 km | 77% | -0.2 hPa | 0 |
| +48 h | 19 | 90 km | 84% | -0.4 hPa | 0 |
| +72 h | 18 | 109 km | 89% | -0.8 hPa | 1 |
| +96 h | 18 | 230 km | 78% | -1.4 hPa | 0 |
| +120 h | 15 | 360 km | 67% | -1.7 hPa | 0 |

## Last 30 days (30 days)

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
| +24 h | 77% | 8% | 97% | 61% | 30 |
| +48 h | 60% | 5% | 83% | 59% | 30 |
| +72 h | 47% | 26% | 73% | 63% | 30 |
| +96 h | 13% | 50% | 33% | 70% | 30 |
| +120 h | 13% | 43% | 20% | 68% | 30 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 63% | 63% | 1.0x | 183410 |
| storm | 69% | 9% | 7.5x | 4665 |
| hf | 31% | 4% | 8.4x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 59 | 63 km | 69% | +0.1 hPa | 1 |
| +48 h | 55 | 119 km | 65% | +0.9 hPa | 0 |
| +72 h | 51 | 166 km | 73% | +1.8 hPa | 2 |
| +96 h | 50 | 228 km | 70% | +1.9 hPa | 1 |
| +120 h | 49 | 267 km | 76% | +1.3 hPa | 2 |

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
| +24 h | 78% | 16% | 90% | 53% | 49 |
| +48 h | 63% | 21% | 84% | 45% | 49 |
| +72 h | 43% | 12% | 65% | 48% | 49 |
| +96 h | 21% | 33% | 38% | 66% | 48 |
| +120 h | 20% | 47% | 24% | 56% | 49 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 76% | 60% | 1.3x | 194514 |
| storm | 53% | 8% | 6.8x | 5679 |
| hf | 7% | 2% | 2.8x | 525 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 66 | 69 km | 62% | +0.2 hPa | 0 |
| +48 h | 58 | 107 km | 76% | +0.2 hPa | 0 |
| +72 h | 55 | 135 km | 82% | +0.4 hPa | 3 |
| +96 h | 58 | 229 km | 71% | +0.6 hPa | 2 |
| +120 h | 52 | 348 km | 63% | -0.2 hPa | 4 |

## All days (30 days)

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
| +24 h | 77% | 8% | 97% | 61% | 30 |
| +48 h | 60% | 5% | 83% | 59% | 30 |
| +72 h | 47% | 26% | 73% | 63% | 30 |
| +96 h | 13% | 50% | 33% | 70% | 30 |
| +120 h | 13% | 43% | 20% | 68% | 30 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 63% | 63% | 1.0x | 183410 |
| storm | 69% | 9% | 7.5x | 4665 |
| hf | 31% | 4% | 8.4x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 59 | 63 km | 69% | +0.1 hPa | 1 |
| +48 h | 55 | 119 km | 65% | +0.9 hPa | 0 |
| +72 h | 51 | 166 km | 73% | +1.8 hPa | 2 |
| +96 h | 50 | 228 km | 70% | +1.9 hPa | 1 |
| +120 h | 49 | 267 km | 76% | +1.3 hPa | 2 |

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
| +24 h | 78% | 16% | 90% | 53% | 49 |
| +48 h | 63% | 21% | 84% | 45% | 49 |
| +72 h | 43% | 12% | 65% | 48% | 49 |
| +96 h | 21% | 33% | 38% | 66% | 48 |
| +120 h | 20% | 47% | 24% | 56% | 49 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 76% | 60% | 1.3x | 194514 |
| storm | 53% | 8% | 6.8x | 5679 |
| hf | 7% | 2% | 2.8x | 525 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 66 | 69 km | 62% | +0.2 hPa | 0 |
| +48 h | 58 | 107 km | 76% | +0.2 hPa | 0 |
| +72 h | 55 | 135 km | 82% | +0.4 hPa | 3 |
| +96 h | 58 | 229 km | 71% | +0.6 hPa | 2 |
| +120 h | 52 | 348 km | 63% | -0.2 hPa | 4 |

