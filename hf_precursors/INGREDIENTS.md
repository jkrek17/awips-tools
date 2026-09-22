# Ingredients, grounded in the explosive-cyclogenesis literature

Written after the lead-time study showed that following the surface low goes
cold past roughly 36-48 h, so anything beyond that has to be measured in the
environment rather than in the storm. Rather than invent an ingredient list,
this takes one from the papers that established the problem.

Citations were checked against the journals rather than quoted from memory,
which is this repository's standing convention. Where a finding is
paraphrased from an abstract rather than the full text, it says so.

---

## Sanders and Gyakum 1980, Mon. Wea. Rev. 108, 1589-1606

"Synoptic-Dynamic Climatology of the 'Bomb'". Northern Hemisphere,
September 1976 - May 1979. The paper that defined the object.

**The definition.** A surface cyclone whose central pressure falls at least
1 mb per hour for 24 h, geostrophically adjusted -- the Bergeron, which the
HF archive already computes and whose distribution the archive site already
plots.

**What they found, and what each becomes here:**

| Finding | Ingredient |
| :--- | :--- |
| Bombs sit about **400 n mi (740 km) downstream of a mobile 500 mb trough** | vector from the surface low to the 500 hPa trough: distance and bearing |
| **Within or poleward of the maximum westerlies** | the low's latitude relative to the 250-300 hPa wind maximum |
| Within or ahead of planetary-scale troughs | 500 hPa height anomaly over a synoptic-scale radius |
| Development occurs over a wide range of SSTs but **preferentially near the strongest gradients** | \|grad SST\| near the low -- note it is the GRADIENT, not the SST itself |
| A quasi-geostrophic diagnosis of a composite incipient bomb gives **pressure falls far short of the observed rates** | QG forcing alone does not close the budget, so low-level moisture belongs in the set: 850 hPa specific humidity and moisture flux convergence |

The 740 km trough distance is the single most specific number in the
literature for this problem, and it is a vector rather than a scalar --
which is why the earlier plan called a trough locator the biggest schedule
risk, and why it is worth the trouble after all.

## Gyakum and Danielson 2000, Mon. Wea. Rev. 128, 851-863

"Analysis of Meteorological Precursors to Ordinary and Explosive
Cyclogenesis in the Western North Pacific". 35 cases, cold seasons
1975-1995, **the same basin as this study**, and the closest prior work to
what is being attempted here. From the abstract:

- Both samples show a favourable-looking thickness trough-ridge structure,
  so the presence of that structure does not discriminate.
- **The upstream surface anticyclone is stronger** in the explosive sample
  at the start of most rapid deepening.
- **The downstream precedent cyclone is stronger** in the explosive sample.
- Because of the stronger equatorward flow that follows, **the 1000-500 hPa
  thickness anomaly is about 40 m (~2 C) colder** in the region of incipient
  cyclogenesis, and 1500 km eastward of it.

These are the cheapest ingredients on this page and the most specific to our
basin. The upstream anticyclone and downstream cyclone need only the MSLP
field already being read, sampled in sectors rather than at the centre, and
the thickness anomaly needs two geopotential levels.

## Gyakum, Roebber and Bullock 1992; Bullock and Gyakum 1993

On the western North Pacific: **antecedent surface vorticity development
conditions the later explosive intensification**, and strong cyclogenesis is
preceded by stronger antecedent development.

**This is the one finding already confirmed by our own numbers.** In the
lead-time study, added to knowing the wind now, the 24 h deepening rate
gains +0.171 in out-of-sample R2 while depth, scale and gradient together
gain +0.011. The storm's prior development is the predictor; its present
shape is not. Three decades of literature said so first.

---

## The set, in the order worth building

Cheapest and most basin-specific first.

1. **Upstream anticyclone and downstream cyclone** (Gyakum and Danielson).
   MSLP only, sampled in sectors at 1000-2000 km. No new field reads.
2. **Antecedent deepening** (Gyakum, Roebber and Bullock). Already built,
   already the best incremental predictor found.
3. **1000-500 hPa thickness anomaly** in the genesis region, and 1500 km
   east of it (Gyakum and Danielson). Two levels of geopotential.
4. **SST gradient magnitude** near the low (Sanders and Gyakum). One field.
5. **The 500 hPa trough vector** -- distance and bearing, against their
   740 km (Sanders and Gyakum). Needs a trough locator, which is the hard
   part and the reason it is fifth rather than first.
6. **Jet position** -- the low's latitude relative to the 250-300 hPa wind
   maximum (Sanders and Gyakum).
7. **Low-level moisture** -- what the quasi-geostrophic diagnosis was
   missing (Sanders and Gyakum).
8. **The cyclone phase space fields** -- HVTL, HVTU, HB. Not from this
   literature, but they are multi-level thermal-structure diagnostics and
   this is the first ingredient set in which they have a fair test against
   named alternatives rather than against nothing.

Every one of these is computable from the ERA5 store already in use:
geopotential, u, v, temperature, specific humidity, vertical velocity and
potential vorticity on 37 levels, plus SST and 2 m temperature.

## What has to be true for any of it to mean anything

The earlier case-control design failed because its two arms were built by
different processes. Whatever is measured here must be measured the same way
for cases and for non-events, by one detector, with the depth floor low
enough to admit a developing low -- the median storm is 14.1 hPa deep 24 h
before hurricane-force onset, and the first pipeline's floor was 15.

---

# Screen result: the phase space fields are the only ingredient that adds

2652 lows from the 5 hPa cohort, each carrying every ingredient above,
labelled by whether hurricane force followed within 24 h. Baseline is what a
forecaster already has from the low itself: **its depth and the wind
currently blowing near it**, AUC 0.892 on the exploration seasons and 0.882
on the confirmation seasons. An ingredient earns a field in D2D only by
beating that.

| ingredient | alone | + baseline | gain (explore) | gain (confirm) |
| :--- | ---: | ---: | ---: | ---: |
| **Hart HVTU** | 0.756 | 0.927 | **+0.044** | **+0.045** |
| **Hart HVTL** | 0.503 | 0.905 | **+0.019** | **+0.023** |
| gradient wind Vg | 0.825 | 0.887 | +0.008 | +0.005 |
| S&G trough depth | 0.679 | 0.886 | +0.003 | +0.004 |
| scale | 0.611 | 0.886 | +0.005 | +0.004 |
| G&D thickness anomaly | 0.649 | 0.885 | +0.002 | +0.003 |
| S&G SST gradient | 0.607 | 0.882 | +0.004 | +0.000 |
| G&D upstream anticyclone | 0.746 | 0.882 | -0.000 | +0.000 |
| G&D downstream cyclone | 0.735 | 0.882 | +0.000 | +0.001 |
| S&G trough distance | 0.558 | 0.882 | +0.002 | -0.000 |

Both Hart terms together take the baseline from 0.882 to **0.929**, and
adding every other ingredient on top of them buys nothing further (0.928).
**The entire gain is the phase space.**

## Why, and what it means

HVTU is the upper-tropospheric thermal wind: how cold the core is aloft.
Depth says how strong the low is and the current wind says what it is doing;
neither says whether the system has developed the deep cold core aloft that
marks a mature extratropical cyclone rather than a shallow wave. That is
development STAGE, and it is the piece the surface fields cannot see.

So after this whole sequence -- compactness, tendency, the classic
ingredients -- the package already built and installed at OPC turns out to
carry the one thing that adds to what a forecaster can already read off a
surface chart. HVTL and HVTU need only geopotential, which the definitions
already request.

## Signs that came out opposite to what was expected

Reported rather than quietly flipped, because each one is informative:

- **HVTU, and HVTL.** The expected sign was Hart's positive-is-warm-core,
  which is the TROPICAL reading. These are extratropical systems, and a cold
  core aloft is the mature signature, so the reversal is the expected physics
  rather than a contradiction.
- **G&D thickness anomaly, and the downstream cyclone.** Gyakum and
  Danielson's finding is about the region of *incipient cyclogenesis*, which
  lies upstream of the low; both quantities here are measured at the low
  itself, with sectors fixed to west and east rather than to their composite
  frame. A sign flip under that mismatch is an implementation caveat, not a
  refutation of their result, and testing it properly means compositing in
  their frame.

## Caveats

Instances from one track are not independent, so the effective sample is
nearer the number of tracks than the 1360 rows scored; the season split
means no track spans fit and score, so the generalization is honest even
though the nominal significance is overstated. The baseline is already at
0.88, where gains are hard to come by, which makes +0.047 worth more than it
looks. And this is still perfect prog -- ERA5 analyses, not forecasts.
