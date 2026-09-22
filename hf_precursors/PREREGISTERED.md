# Written before the confirmation seasons were looked at

Committed deliberately ahead of running `analyze_tracks.py --confirm`, so the
confirmation is checkable against a record rather than a recollection. The
exploration seasons are 2020, 2022 and 2024; the confirmation seasons are
2021, 2023 and 2025 and have not been examined.

## What the exploration found

One cohort: every North Pacific low from October to April, 2020-2025,
detected, described and tracked by the same code. 10,149 low-instances,
1,314 tracks of at least 18 h, of which 226 of the archive's 261 Pacific
hurricane-force cases (87%) matched a track. Hurricane-force tracks and the
rest differ in what happened to them, not in how they were measured.

Exploration seasons: 104 hurricane-force tracks, 532 others.

**At the track's own deepest moment**, hurricane-force tracks are deeper
(37.9 against 24.3 hPa), **more compact (490 against 540 km)**, and much
tighter (gradient 8.2 against 5.0 hPa/100 km).

**The sign test.** Regressing ERA5's own maximum gust on depth and scale
together, the scale coefficient is **negative** -- at a given depth, the
compact low is the windier one. It is negative against the archive's
hurricane-force label as well. The two outcomes, one measured by ERA5 and
one recorded by a forecaster, agree.

**The label holds up.** Every hurricane-force track in the exploration set
reaches an ERA5 gust of 64 kt, against 25% of the others; 84% reach 70 kt,
against 7%. Only 4 non-hurricane-force tracks reach the hurricane-force
median gust. The archive's determination is measuring wind, not coverage.

## Predictions for the confirmation seasons

Stated as numbers so they can be wrong.

1. **Scale coefficient on ERA5 max gust, at the peak: negative**, within a
   factor of two of -0.013 kt per km. (Exploration: -0.0133, t = -6.6.)
2. **Scale coefficient at 24 h before the peak: negative**, within a factor
   of two of -0.021 kt per km, and larger in magnitude than at the peak.
   (Exploration: -0.0209, t = -3.9.)
3. **Depth coefficient on gust, at the peak: positive**, near +0.9 kt per
   hPa. (Exploration: +0.883, t = 24.7.)
4. **Gradient alone explains roughly 45% of the variance in peak gust** and
   roughly 34% at 24 h lead. (Exploration: R2 0.459 and 0.344.)
5. **Odds ratio on scale for the archive label: below 1**, near 0.996 per km
   at both times. (Exploration: 0.9964 and 0.9963.)
6. **Every hurricane-force track reaches an ERA5 gust of 64 kt**, and fewer
   than a third of the others do.

Failure of 1 or 2 falsifies the compactness hypothesis on this data. Failure
of 6 means the label and the measured wind have come apart and the rest needs
re-reading.

## Thresholds, fixed now

A candidate operational form, so the confirmation scores something concrete
rather than a coefficient:

    gradient = depth / scale, in hPa per 100 km, from the Gaussian fit to
    the azimuthal-mean pressure profile.

    >= 7.0   expect hurricane force
    5.0-7.0  watch
    < 5.0    unlikely

7.0 sits between the exploration medians (8.2 for hurricane-force tracks,
5.0 for the rest) and is not tuned beyond that. Its hit rate and false alarm
ratio on the confirmation seasons are the number that matters.

## What this does not establish

The regression is on ERA5 analyses, not forecasts. It measures the physical
relationship, which is an upper bound on what a forecaster could get from a
model that has to predict depth and scale 24 h ahead in the first place.

---

# Confirmation, run after the above was committed

Seasons 2021, 2023, 2025. 122 hurricane-force tracks, 556 others.

| # | Prediction | Result | |
| --- | --- | --- | --- |
| 1 | scale coef on gust at peak negative, ~-0.013 | **-0.0152**, t = -8.3 | held |
| 2 | scale coef at 24 h lead negative, ~-0.021, larger than at peak | **-0.0238**, t = -5.6, larger | held |
| 3 | depth coef at peak ~ +0.9 | **+0.849**, t = 26.6 | held |
| 4 | gradient R2 ~0.45 peak, ~0.34 lead | **0.528** and **0.335** | lead held; peak came in higher than predicted |
| 5 | scale odds ratio below 1, ~0.996 | **0.9967** peak, **0.9944** lead | held |
| 6 | every HF track reaches 64 kt gust, under a third of others | **97%** and **20%** | held on the second half; 97%, not every |

The medians replicate across independent seasons almost exactly: peak scale
500 against 550 km (exploration 490 against 540), peak gradient 8.2 against
4.8 (exploration 8.2 against 5.0), ERA5 max gust 75.8 against 57.5
(exploration 77.5 against 58.0).

## The threshold, scored

`gradient = depth / scale >= 7.0 hPa/100 km`, fixed before looking:

| | POD | FAR | CSI |
| --- | --- | --- | --- |
| at the peak, exploration | 0.73 | 0.53 | 0.40 |
| **at the peak, confirmation** | **0.70** | **0.44** | **0.45** |
| **24 h before the peak, confirmation** | **0.31** | **0.15** | **0.29** |
| depth >= 30 hPa at the peak, confirmation | 0.84 | 0.54 | 0.42 |

Against depth alone the gradient threshold trades recall for precision: ten
fewer false alarms for every seventeen, at the cost of catching fewer events.
Its CSI is better, 0.45 against 0.42, and that is the honest size of the
improvement -- real, replicated, and modest.

At 24 h lead the same threshold becomes a high-confidence, low-sensitivity
trigger: when it fires it is right 85% of the time, and it fires for only a
third of the events, because many lows have not tightened yet a day out.

## What this establishes, and what it does not

**Established.** At a given depth, the compact low is the windier one, in
both outcomes, at the peak and a day before it, in two independent sets of
seasons, with every coefficient physically signed. The forecaster's
hypothesis is supported.

**Its size.** 100 km of extra compactness is worth about 1.5 kt of gust;
1 hPa of extra depth about 0.85 kt. So 100 km of compactness trades for
roughly 1.8 hPa of depth. Depth remains the bigger lever; compactness is a
real second term, not a replacement.

**Not established.** This is perfect prog: ERA5 analyses, not forecasts, so
it measures the physical relationship and sets an upper bound on what a
forecaster gets from a model that must first predict depth and scale a day
ahead. The 24 h lead sample is 210 tracks. And the cyclone phase space
fields are still not in this table -- whether they add anything over depth
and scale is untested.

---

# Lead time: what predicts the wind, and how far ahead

Fitted on 2020/2022/2024, scored on 2021/2023/2025, 678 held-out tracks.
Outcome is the maximum ERA5 gust STRICTLY AFTER the predictor time -- an
earlier version included the current instant, which let persistence score
itself, and inflated its R2 by about 0.07.

## Best predictor at 24 h

| predictor | out-of-sample R2 | AUC for 64 kt ahead |
| --- | --- | --- |
| **persistence + 24 h deepening** | **0.743** | |
| persistence (the gust already blowing) | 0.573 | 0.872 |
| 24 h deepening alone | 0.382 | 0.841 |
| gradient wind Vg | 0.335 | 0.784 |
| gradient = depth/scale | 0.285 | 0.770 |
| depth | 0.191 | 0.694 |
| scale | 0.120 | 0.692 |

## What each variable adds to persistence, which is the only test that matters

| added to the gust now | R2 | gain |
| --- | --- | --- |
| **24 h deepening** | **0.743** | **+0.171** |
| 12 h deepening | 0.738 | +0.165 |
| depth + scale + deepening + latitude | 0.740 | +0.167 |
| latitude | 0.591 | +0.019 |
| depth + scale | 0.583 | +0.011 |
| gradient | 0.573 | -0.000 |
| gradient wind Vg | 0.572 | -0.000 |

**The gradient adds nothing once the current wind is known, and that is not a
failure of the earlier result -- it is the explanation of it.** The gradient
explains the wind that is blowing: diagnostically it accounts for 53% of the
variance in peak gust, which is why compact lows are windier. But the wind
field already IS that gradient's consequence, so a forecaster looking at it
has the information. What the current wind cannot say is which way it is
going, and that is the one thing the tendency adds.

Two variables carry the 24 h forecast: **how windy it is now, and how fast
it is deepening.** Depth, scale and the gradient add a rounding error on top
of those, and adding them costs nothing but buys nothing.

## 96 hours: the question has to change

Anchored on each track's own peak, the lead-time study runs out of storms,
not out of data: at 48 h before its peak there are 33 held-out tracks, at
72 h there are 5, and at 96 h there is 1. Median track lifetime is 30 h,
p90 is 72 h, and **only 3% of North Pacific lows live 96 h at all** -- 14%
of the hurricane-force ones.

The forward-window framing ("given a low now, how windy in the next N
hours") keeps its sample at every horizon because every instance can answer,
but the curves flatten past about 48 h for the same reason: the window stops
adding future to look at, because the storm is over.

So 96 h is not a longer version of this question. At 96 h the low being
forecast does not exist yet, and depth, scale, tendency and current wind are
all undefined for it. That is a **cyclogenesis** forecast, and its predictors
are environmental rather than structural -- upstream trough position and
amplitude, jet-level divergence, low-level baroclinicity and the SST
gradient, evaluated where the low will form rather than where it is. Nothing
in this pipeline addresses it, and extending the horizon will not make it
appear.

---

# Correction: the 96 h conclusion was an artifact of my own depth floor

The earlier claim that "at 96 h the low does not exist" was measured against
tracks anchored on each track's own pressure minimum, in a database that only
admitted a low once it was **15 hPa deep**. Two things were tested:

**Fragmentation is not the cause.** Allowing a track to survive one or two
missed detections (6, 12, 18 h gaps) changes nothing: median lifetime stays
30 h and the share living 96 h stays 3.1%.

**The depth floor is the cause.** Anchoring instead on the archive's own
hurricane-force onset and walking back from it with no floor at all:

| lead before HF onset | identifiable | median depth | median gradient | median gust |
| ---: | ---: | ---: | ---: | ---: |
| 0 h | 100% | 33.7 hPa | 8.09 | 73 kt |
| 12 h | 74% | 23.6 | 5.20 | 60 |
| **24 h** | **73%** | **14.1** | **3.04** | **52** |
| 48 h | 64% | 9.4 | 2.27 | 44 |
| 72 h | 53% | 10.5 | 2.58 | 43 |
| 96 h | 50% | 10.2 | 2.47 | 43 |

**At 24 h before hurricane-force onset the median storm is 14.1 hPa deep --
below the 15 hPa floor that decided whether it entered the track database at
all.** The pipeline was systematically blind to the developmental phase it
was supposed to forecast from, which is exactly the objection raised against
the archive, landing instead on my own detector.

## What the trail back actually shows

A low is findable at T-96 in **half** of all cases, so "the low does not
exist" was wrong. But the *unbroken* trail -- every step from onset back to
that lead identifiable and reachable by a plausible storm step -- tells a
harder story: median 18 h, reaching 24 h in 49% of cases, 48 h in 20%,
72 h in 8% and 96 h in 5%.

And beyond about 60 h the numbers stop moving: depth sits near 10 hPa, gust
near 43 kt, and the step stays near 380 km at every lead. A trail whose
quantities are independent of how far back you have gone is not following a
storm; it has settled onto whatever low is nearby.

**So following the surface low is good to roughly 36-48 h and goes cold after
that.** Past that the forecast cannot be about the low's own depth and scale,
because the thing being measured is no longer reliably the storm. It has to
be about the environment that will produce one -- which is where upper levels
come in.
