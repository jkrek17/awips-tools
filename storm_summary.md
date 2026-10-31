# Storm layers verification

Through 20261029 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs.

- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, `windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): blend 15% caught / 4% false alarm, core lift 49% / 15%.
- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.
- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone (cone sized to hold it about 2 in 3).
- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.

## Last 7 days (7 days)

### North Atlantic

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 79% | 8% | 100% | 58% | 14 |
| +48 h | 64% | 10% | 93% | 50% | 14 |
| +72 h | 36% | 29% | 79% | 59% | 14 |
| +96 h | 29% | 50% | 36% | 71% | 14 |
| +120 h | 21% | 40% | 36% | 50% | 14 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 65% | 58% | 1.1x | 69230 |
| storm | 68% | 6% | 11.9x | 1210 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 20 | 72 km | 70% | -0.4 hPa | 0 |
| +48 h | 17 | 117 km | 65% | +0.6 hPa | 0 |
| +72 h | 17 | 183 km | 65% | +1.3 hPa | 1 |
| +96 h | 17 | 254 km | 76% | +2.5 hPa | 1 |
| +120 h | 20 | 296 km | 70% | +1.9 hPa | 1 |

### North Pacific

**Peaks vs analysis**

| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |
|---|---|---|---|---|---|
| +24 h | 88% | 12% | 88% | 65% | 8 |
| +48 h | 38% | 0% | 62% | 67% | 8 |
| +72 h | 25% | 33% | 50% | 71% | 8 |
| +96 h | 25% | 33% | 38% | 73% | 8 |
| +120 h | 0% | - | 25% | 50% | 8 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 73% | 65% | 1.1x | 50640 |
| storm | 43% | 2% | 25.8x | 390 |
| hf | - | 0% | - | 0 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 8 | 63 km | 50% | -1.3 hPa | 0 |
| +48 h | 7 | 139 km | 57% | -0.1 hPa | 0 |
| +72 h | 10 | 227 km | 60% | +1.8 hPa | 0 |
| +96 h | 8 | 320 km | 62% | +3.5 hPa | 0 |
| +120 h | 6 | 381 km | 67% | +0.8 hPa | 0 |

## Last 30 days (24 days)

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
| +24 h | 81% | 8% | 96% | 63% | 27 |
| +48 h | 63% | 6% | 85% | 60% | 27 |
| +72 h | 44% | 20% | 74% | 64% | 27 |
| +96 h | 15% | 50% | 37% | 69% | 27 |
| +120 h | 15% | 43% | 22% | 68% | 27 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 64% | 63% | 1.0x | 171245 |
| storm | 70% | 9% | 7.5x | 4405 |
| hf | 31% | 4% | 8.4x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 53 | 64 km | 66% | +0.2 hPa | 1 |
| +48 h | 52 | 118 km | 65% | +1.0 hPa | 0 |
| +72 h | 47 | 168 km | 70% | +2.0 hPa | 2 |
| +96 h | 44 | 238 km | 66% | +2.5 hPa | 1 |
| +120 h | 44 | 259 km | 75% | +1.9 hPa | 2 |

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
| +24 h | 72% | 15% | 88% | 52% | 40 |
| +48 h | 55% | 19% | 80% | 43% | 40 |
| +72 h | 30% | 14% | 58% | 52% | 40 |
| +96 h | 10% | 43% | 28% | 69% | 39 |
| +120 h | 12% | 62% | 18% | 65% | 40 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 75% | 62% | 1.2x | 129444 |
| storm | 65% | 8% | 7.8x | 4409 |
| hf | 18% | 3% | 6.9x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 45 | 76 km | 56% | +0.3 hPa | 0 |
| +48 h | 40 | 114 km | 72% | +0.5 hPa | 0 |
| +72 h | 38 | 148 km | 76% | +0.9 hPa | 2 |
| +96 h | 41 | 231 km | 66% | +1.3 hPa | 2 |
| +120 h | 38 | 343 km | 63% | +0.3 hPa | 4 |

## All days (24 days)

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
| +24 h | 81% | 8% | 96% | 63% | 27 |
| +48 h | 63% | 6% | 85% | 60% | 27 |
| +72 h | 44% | 20% | 74% | 64% | 27 |
| +96 h | 15% | 50% | 37% | 69% | 27 |
| +120 h | 15% | 43% | 22% | 68% | 27 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 64% | 63% | 1.0x | 171245 |
| storm | 70% | 9% | 7.5x | 4405 |
| hf | 31% | 4% | 8.4x | 235 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 53 | 64 km | 66% | +0.2 hPa | 1 |
| +48 h | 52 | 118 km | 65% | +1.0 hPa | 0 |
| +72 h | 47 | 168 km | 70% | +2.0 hPa | 2 |
| +96 h | 44 | 238 km | 66% | +2.5 hPa | 1 |
| +120 h | 44 | 259 km | 75% | +1.9 hPa | 2 |

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
| +24 h | 72% | 15% | 88% | 52% | 40 |
| +48 h | 55% | 19% | 80% | 43% | 40 |
| +72 h | 30% | 14% | 58% | 52% | 40 |
| +96 h | 10% | 43% | 28% | 69% | 39 |
| +120 h | 12% | 62% | 18% | 65% | 40 |

**Hazard lines vs analysis** (all leads)

| Line | inside | verified | area | obs at threshold |
|---|---|---|---|---|
| gale | 75% | 62% | 1.2x | 129444 |
| storm | 65% | 8% | 7.8x | 4409 |
| hf | 18% | 3% | 6.9x | 195 |

**Ensemble low track vs analysis**

| Lead | lows matched | mean error | in cone | pressure bias | unmatched |
|---|---|---|---|---|---|
| +24 h | 45 | 76 km | 56% | +0.3 hPa | 0 |
| +48 h | 40 | 114 km | 72% | +0.5 hPa | 0 |
| +72 h | 38 | 148 km | 76% | +0.9 hPa | 2 |
| +96 h | 41 | 231 km | 66% | +1.3 hPa | 2 |
| +120 h | 38 | 343 km | 63% | +0.3 hPa | 4 |

