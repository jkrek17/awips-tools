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

---

# Would a panel actually work? Two tests

## Test 1: does the gain survive what D2D can compute? YES

The screen used a depth from a Gaussian fit to the azimuthal-mean pressure
profile around a detected centre. A derived parameter has no centre -- it
computes one number per grid point from windowed operations. So the depth a
panel could show is not the depth the model was fitted on, and a gain
measured with one is not evidence for the other.

Refitting with the pointwise analogue the package already builds -- maximum
pressure within a 500 km window minus the value at the point:

| depth used | baseline | + Hart | gain | FAR at POD 0.80 |
| :--- | ---: | ---: | ---: | :--- |
| fitted profile (what the screen used) | 0.882 | 0.929 | +0.047 | 0.33 -> 0.22 |
| **pointwise 500 km window (what a panel shows)** | **0.882** | **0.928** | **+0.046** | **0.34 -> 0.23** |

The two depths correlate at r = 0.92, the pointwise one running 1.3 hPa
shallower. The gain is intact: +0.046 against +0.047, and false alarms still
fall by a third at the same detection rate. **Panel A is worth building.**

## Test 2: does it survive on FORECASTS rather than analyses? Not yet run

Everything above is perfect prog. Both panels are fitted and scored on ERA5
analyses, so they measure the physical relationship and set an upper bound on
what a forecaster gets from a model that has to predict the 3D structure
24 h ahead in the first place.

The real competitor for Panel B is not persistence of the analysis -- it is
**the model's own 24 h forecast of 10 m wind**, which a forecaster already
has on the screen. A tendency field only earns its place by beating that.

The test is feasible and cheap, which was not obvious:

- the GFS forecast archive on AWS open data is reachable, and covers the
  confirmation seasons from 2021;
- each cycle's `.idx` allows byte-range reads, so the eight fields needed --
  PRMSL and geopotential on seven levels -- cost **6.8 MB per forecast
  instead of the 500 MB file**;
- cfgrib parses them onto a 721x1440 0.25 degree grid, the same grid ERA5
  uses, so every routine in this package applies unchanged.

For the confirmation-season lows that is roughly 700 unique valid times,
about 5 GB streamed and discarded, well inside an hour in parallel.

Until that runs, the honest statement about both panels is that the physics
holds and the operational gain is unmeasured.

---

# Test 2, run: against the model's own forecast, the gain mostly disappears

## First, a correction: sustained wind, not gust

The archive's hurricane force is an analyst's SUSTAINED wind determination.
The pipeline had been pairing it with ERA5's instantaneous gust, both as the
"wind now" predictor and as the measured outcome. That was wrong, and the
sustained field was recorded all along beside it.

Redone on sustained wind, the phase-space gain is slightly LARGER: baseline
0.877 rather than 0.882, and +0.054 rather than +0.047.

One earlier claim does not survive the correction. The statement that every
hurricane-force track reaches 64 kt in ERA5 was made on gust. **On sustained
wind, none of them do** -- 0%, with a median of 44 kt against 33 for the
rest. ERA5's 10 m wind at 0.25 degrees is a smoothed model wind and sits
about 20 kt below what an analyst determines from scatterometer data. It
discriminates well; it does not measure. The earlier threshold agreement was
a coincidence of the gust field's scaling, not a validation of the label.

## The operational ladder, held-out season 2025, 270 lows

GFS f024 forecasts fetched by byte range from the AWS archive, one per cycle,
sampled where the low actually was 24 h later -- a perfect track handed to
the competitor on purpose.

| model | AUC | FAR at POD 0.80 | false alarms |
| :--- | ---: | ---: | ---: |
| 1  depth + sustained wind now | 0.783 | 0.44 | 64 |
| 2  + GFS f024 forecast wind | 0.876 | 0.30 | 35 |
| **3  + HVTL and HVTU** | **0.889** | **0.28** | **33** |
| GFS f024 wind alone | 0.846 | 0.34 | 42 |
| phase space, without the forecast | 0.859 | 0.35 | 45 |

**The model's own forecast is worth +0.093. The phase space on top of it is
worth +0.013** -- two fewer false alarms in 270 lows.

That is the answer to whether a panel is truly useful, and it is mostly no.
The +0.054 measured without the forecast in the model was largely the phase
space standing in for information the model's own forecast already carries,
which is what should have been expected: GFS integrated the developing
structure to produce that wind.

## What does survive

The phase space without the forecast (0.859) is about as good as the
forecast alone (0.846). They are two largely independent readings of the
same storm that reach similar skill by different routes, and combining them
adds little because they agree most of the time.

**Where they disagree is the only place a panel can earn anything.** That is
a different product from the one proposed: not a probability field to add to
the model's wind, but a flag for the cases where the structure says
something the model's wind does not. Whether that subset is one a forecaster
wins on is untested and is the obvious next experiment.

## Limits of this test

One held-out season, 270 lows, so FAR 0.30 against 0.28 is inside the noise.
The GFS archive on AWS begins in 2021, which is why the fit/score split had
to be made within the confirmation seasons rather than against the
exploration ones. And the label remains the archive's, so every "false
alarm" is a low no analyst recorded at hurricane force.
