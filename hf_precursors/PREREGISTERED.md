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
