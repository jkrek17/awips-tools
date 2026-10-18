# Our cyclone phase space against FSU's, digitized

Generated 2026-10-18T01:39Z by `realtime/fsu_stats.py` from `realtime/data/` (159 storm-cycles with an FSU match, 318 FSU plots). FSU publishes only images; their values here are read off the plots by `realtime/fsu_digitize.py`. Ours: GFS 0.25 degree, 24 h centered running mean, paired with FSU (GFS 0.5 degree, its own 24 h mean) at shared valid hours of the same run. Differences are ours minus FSU, in m.

## Digitizing

- Hours with a timed point on either FSU plot: 1279; paired with our track: 1110 usable, of which 517 verified (timed independently on both plots, with agreeing -V_T^L).
- -V_T^L read on phase1 minus phase2 on verified hours: mean 0.01 m, RMS 0.13 m (n 517); the median error estimate per point is 0.06 m for B, 0.29 m for -V_T^L and 0.47 m for -V_T^U (0.7 px of center uncertainty, more for a covered or crowded marker, times the axis scale).
- Hours timed independently on both plots: 662, of which 77 (12%) disagreed on -V_T^L (a walk miscounted a hidden marker or picked a wrong neighbor) and were dropped with the rest of that walk; the same rate is the best estimate of the timing error among usable points timed on one plot only, which is why the verified set is the headline.
- Against hand readings of 48 points on five plots: 45 compared, x RMS 0.2 m (mean 0.04), y RMS 0.07 m (mean 0.0); 3 hand points the digitizer left untimed or dropped.
- Plots: 60 closed, 231 partial, 27 failed, 0 errors (closed: a walk from the end marker reached the analysis marker, or one from the start marker of a future cyclone reached the end, with the right count; partial: some hours timed; failed: none timed, mostly because neither end of the forecast trajectory could be found: the end under the inset map or in a cluster, the analysis marker's ring hidden). Discs found 12483, of which 9747 left untimed (clusters of overlapping markers, markers under the inset map, tangled tracks, analysis hours before the run).
- Shading check on the calibration (median over plots of where the background hue changes): phase1 B boundary at 11.0 m (expected 10), phase2 -V_T^U boundary at -0.6 m (expected 0); the -V_T^L boundary is a white band of shading around 0 (medians -1.0 and -0.7 m), so it only bounds the calibration loosely.

## Bias / RMS (count), verified points

| Term | Bands | All | Warm lower core | Cold lower core | Faster than 20 kt | 20 kt or slower |
|---|---|---|---|---|---|---|
| B | standard (hb) | +7.7 / 16.0 (505) | +6.0 / 12.5 (321) | +10.7 / 20.8 (184) | +6.8 / 14.3 (82) | +7.8 / 16.3 (421) |
| B | hart (hb_track) | +1.8 / 12.0 (515) | +1.0 / 9.8 (333) | +3.3 / 15.3 (182) | +5.3 / 13.8 (82) | +1.1 / 11.6 (433) |
| -V_T^L | standard (hvtl) | +11.9 / 56.0 (517) | +7.3 / 48.2 (333) | +20.3 / 67.9 (184) | +2.9 / 83.4 (82) | +13.1 / 48.5 (433) |
| -V_T^L | hart (hvtl_hart) | -14.2 / 50.7 (517) | -10.4 / 43.6 (333) | -21.0 / 61.4 (184) | -30.2 / 83.0 (82) | -11.2 / 42.0 (433) |
| -V_T^U | standard (hvtu) | -2.3 / 52.4 (517) | -10.1 / 46.2 (333) | +11.8 / 62.1 (184) | -9.2 / 67.1 (82) | -0.9 / 49.3 (433) |
| -V_T^U | hart (hvtu_hart) | -6.6 / 39.4 (517) | -4.1 / 37.0 (333) | -11.2 / 43.3 (184) | -16.5 / 54.9 (82) | -4.5 / 35.6 (433) |

## Bias / RMS (count), usable points

| Term | Bands | All | Warm lower core | Cold lower core | Faster than 20 kt | 20 kt or slower |
|---|---|---|---|---|---|---|
| B | standard (hb) | +5.8 / 14.2 (836) | +4.2 / 11.3 (598) | +9.6 / 19.6 (238) | +5.8 / 15.4 (125) | +5.7 / 13.9 (709) |
| B | hart (hb_track) | +0.8 / 11.4 (863) | +0.3 / 9.6 (627) | +2.2 / 15.2 (236) | +4.4 / 15.1 (125) | +0.2 / 10.7 (738) |
| -V_T^L | standard (hvtl) | +5.7 / 52.8 (944) | +0.8 / 46.4 (697) | +19.5 / 67.5 (247) | +1.2 / 81.2 (132) | +6.1 / 46.1 (810) |
| -V_T^L | hart (hvtl_hart) | -11.4 / 49.2 (944) | -9.2 / 44.8 (697) | -17.6 / 59.8 (247) | -28.5 / 83.7 (132) | -8.6 / 40.9 (810) |
| -V_T^U | standard (hvtu) | +0.5 / 61.2 (894) | -4.3 / 59.6 (664) | +14.4 / 65.7 (230) | -17.8 / 109.9 (124) | +3.5 / 49.1 (768) |
| -V_T^U | hart (hvtu_hart) | -2.4 / 51.5 (894) | -1.2 / 52.4 (664) | -6.0 / 49.0 (230) | -23.2 / 105.2 (124) | +1.1 / 36.0 (768) |

## Class agreement (verified points)

| Bands | All | Faster than 20 kt | 20 kt or slower | B side only (B > 10 m) |
|---|---|---|---|---|
| standard | 55% (275/505) | 61% (50/82) | 53% (224/421) | 68% (343/505) |
| hart | 70% (359/515) | 65% (53/82) | 71% (306/433) | 78% (399/515) |

## Onset and completion timing, ours minus FSU (h), usable points

Storm-cycles where both sides start symmetric (B <= 10 m) and both cross B = 10 m later (onset), or start warm and both cross -V_T^L = 0 later, at or after onset (completion).

| Bands | Onset median / mean (n), within 6 h | Completion median / mean (n), within 6 h |
|---|---|---|
| standard | -9.0 / -8.0 (6), 2 | 6.0 / 0.6 (10), 7 |
| hart | 0.0 / -4.0 (9), 4 | 0.0 / 0.0 (11), 11 |

## Our tracks alone: B with the steering proxy against B with the track motion

All 187 storm-cycles, raw 6-hourly values.

| motion_kt | hb - hb_track mean / RMS (n) | 90th pct of abs | class differs | B side differs |
|---|---|---|---|---|
| 0 to 10 | +5.8 / 17.6 (1299) | 18.64 | 17% (219/1282) | 18% |
| 10 to 20 | +5.6 / 19.4 (1028) | 16.99 | 12% (120/1016) | 14% |
| 20 to 30 | +4.1 / 18.7 (339) | 15.24 | 10% (35/337) | 11% |
| 30 to 40 | +4.9 / 17.8 (122) | 10.31 | 7% (8/120) | 7% |
| 40 and up | +1.2 / 8.2 (59) | 16.1 | 4% (2/57) | 3% |

hvtl - hvtl_hart: mean 16.71 m, RMS 37.77 m (n 3139), 5/25/50/75/95th percentiles [-24.3, -8.2, 10.0, 34.6, 82.3]. hvtu - hvtu_hart: mean 7.63 m, RMS 35.24 m (n 3176), percentiles [-41.9, -12.5, 6.9, 23.2, 57.1].

## Caveats

- FSU's values are digitized from 1024 x 768 images: a marker center is good to about a pixel, which is 0.3 to 3 m depending on the plot's axis range; markers drawn over one another, under the inset map or along tangled tracks are left untimed rather than guessed.
- FSU uses the 0.5 degree GFS and its own tracker; its 24 h running mean includes the days before the run, ours only the frames of the run, so the first 12 h of a run are smoothed differently.
- FSU's B uses its tracker's motion; our standard B uses the steering-flow proxy and hb_track the track motion; our hb is blank where the steering flow is under 2 m/s.
- The pairs are not independent: consecutive 6-hourly points of one storm-cycle, and the same storm on consecutive days, are strongly correlated, so the counts overstate the effective sample size.
- Cycles collected before 2026-09-27 used the module's former square 500 km window for the thermal wind terms (cold cores about 50 m more negative); the archive is to be recomputed.
