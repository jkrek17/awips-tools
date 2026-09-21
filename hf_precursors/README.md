# Hurricane-force wind precursors

Can the cyclone phase space fields, computed 12 to 48 h ahead, tell a
hurricane-force low from one that stays below it?

**Status: foundation built and validated. No result yet.** The case list,
the ERA5 access and the agreement between them are done and checked. The
control set, the predictor extraction and the analysis are not.

## Why this needs more than the archive

The HF archive is an *outcome* catalog. It records where and when lows
reached hurricane force. Two things follow, and both shape the design:

1. **It has no precursor state.** Tracks begin at or just before onset:
   1045 of 1825 cases have their first fix already at HF. So what the
   atmosphere looked like beforehand has to come from reanalysis, sampled
   at the archive's own position and time minus the lead.
2. **It has no negative cases. None.** Every event in it reached hurricane
   force. That is fine for a climatology and fatal for a predictor: you can
   describe what these lows looked like 24 h earlier, but not whether those
   features *discriminate*, because there is nothing to discriminate
   against. A precursor found this way has an unknown false alarm rate.

So the study is a case-control design, and the controls have to be built.

## The controls must be matched, not random

Random ocean points would be trivially separable -- most of the North
Atlantic in January is not a deep low -- and would return a skill estimate
that means nothing. Controls are lows that existed, got deep enough to be
candidates, and never reached hurricane force, matched to each case on
**central pressure, latitude and month**. Without that matching the study
would rediscover "deeper lows are windier", which is already known.

The archive doubles as the exclusion list: a candidate is rejected if any
archive fix is near it in space and time. Where the archive has missed a
real HF low, a contaminated control makes the test harder rather than
easier, which is the safe direction.

## What is built

- `archive_cases.py` -- hurricane-force onsets from the archive, via
  `tools/build_hf_lows.build()` so every case inherits that script's QC.
  Excludes tip jets and no-centre events (no cyclone centre means no phase
  space), seasons before the archive's own `RECORD_START`, and tracks with
  no fix categorized HF.

  **1825 cases, 2004-2025, 969 Atlantic and 856 Pacific.** Median minimum
  pressure 964 hPa, median 0.82 Bergerons, 39% explosive (381 of the 981
  carrying enough pressure data to score) -- reproducing the archive site's
  own summary panels exactly, which is the check that it is being read
  right.

- ERA5 access, validated. ARCO-ERA5 on Google Cloud, anonymous, no
  credentials: 0.3 s for one MSLP field, 2.6 s for seven pressure levels of
  geopotential, at 0.25 deg -- the same resolution the D2D package already
  runs on. On six random cases, the ERA5 pressure minimum sits 21 to 223 km
  from the archive position and within 0.4 to 6.7 hPa of its pressure.

## What is not built

- The matched control set.
- Extraction of the phase space fields at each lead time.
- The analysis, which needs the discipline below.

## Phase 0 result: the record starts in 2020, not 2016

Hurricane-force counts per Pacific season step up 35% at 2020 -- 32.3 per
season over 2016-2019, 43.5 over 2020-2025. The Atlantic shows no such step
over the same years (ratio 0.91).

That asymmetry is the tell. Weather does not raise the Pacific count by a
third while leaving the Atlantic flat. ASCAT-C (MetOp-C, launched late 2018,
data through 2019) improves revisit most where the coverage gaps are widest,
and the Pacific basin is the wider one. A predictor correlated with era would
otherwise masquerade as a predictor of wind, and the compactness hypothesis is
about small, short-lived wind maxima -- exactly the population a third
scatterometer preferentially catches.

**The study record is Pacific, 2020-2025: 261 cases.** 2016-2019 is available
as a sensitivity check but is not pooled with it.

With six seasons the interleaved split is 3 explore / 3 confirm, about 130
each. That is thinner than is comfortable, which raises the value of the
Atlantic replication: a second basin is stronger confirmation than a larger
holdout in the same one.

## Phase 0.5 result: the archive cannot decide the compactness hypothesis

The hypothesis under test is that hurricane force comes from a tight pressure
gradient rather than a deep centre, so a compact, fast-falling low can reach
it at a central pressure in the 980s. The archive carries no footprint and no
environmental pressure, so it cannot test that directly; the corollary it can
test is whether events reaching hurricane force at modest depth are the
fast-falling ones.

They are not, on the measure available: grouping by minimum track pressure,
the shallow group's fastest 12 h fall is a median 8 hPa against the deep
group's 12 hPa -- the opposite of the prediction. But that comparison is
between two track extremes that need not occur together, and minimum pressure
is not depth: a 985 hPa low under a 1035 hPa ridge is a 50 hPa depression, and
nothing in the archive says which it was.

Conditioning properly, on the state at hurricane-force onset, the test runs
out of data: only 68 events in the whole record carry a 12 h fall ending at
onset, and **none of them are Pacific**, because Pacific tracks begin at onset.
Among those 68 the correlation is +0.18, not significant, and the shallow and
deep groups' falls are within 2 hPa of each other.

Two things the archive does establish:

- **The stated signature is real but rare.** 13 events in the full record
  reached hurricane force with a minimum pressure at or above 980 hPa and a
  12 h fall of 20 hPa or more, including one at 1005 hPa falling 21 hPa and
  one at 994 falling 24.
- **The converse is common.** 162 of 362 deep events, 45%, never fell more
  than 10 hPa in 12 h. Nearly half of deep hurricane-force lows got there
  without rapid deepening.

Both routes exist, which is consistent with wind depending on something other
than central pressure alone -- but it does not confirm depth-over-scale
specifically, because scale is exactly what is missing. The gate outcome is to
proceed to ERA5, and Phase 0.5 has earned its hour by naming precisely what
ERA5 has to supply: environmental pressure, for depth, and footprint, for
scale.

## Holdout, decided before any of it is looked at

This is an exploratory search for differentiators across many candidate
features on a finite case set, which will find separators that are not
real. So the split comes first: cases are partitioned by season into an
exploration set and a held-out confirmation set, and nothing from the
held-out seasons is plotted, tabulated or summarized until the candidate
features and their thresholds are fixed in writing.

Anything that survives only in the exploration set is a finding about this
sample. The repository already works this way for the wind radii
(`tests/tcwind_jtwc/verify_holdout.py`).

Whatever comes out, the project's standing rule still applies: a field that
does no better than deepening rate alone is dropped. With 61% of these
events reaching hurricane force *without* explosive deepening, that bar is
lower than it first appeared, which is the encouraging part.

## Exploration result (seasons 2020, 2022, 2024 -- confirmation withheld)

79 matched strata, 79 cases and 215 controls, each low described 24 h before
the moment of interest.

**In the space the hypothesis predicted a boundary in, there is no boundary.**
Depth against scale (`data/exploration.png`, panel a) shows cases and
controls completely overlapped: not a ray through the origin, not a
horizontal line, nothing. The medians are within a whisker of each other --
depth 18.4 against 19.2 hPa, scale 520 against 510 km, gradient 4.0 against
4.3 hPa/100 km.

**What does separate them is which way the low is going.** The 12 h pressure
tendency is a median -7.7 hPa for the cases against -3.2 for the controls,
and -13.0 against -4.5 over 24 h: the lows that go on to make hurricane force
are deepening between two and three times as fast as the ones matched to them
on depth. In the model ladder the tendency is the only term with a
respectable z, and the best two-variable fit is gradient plus tendency.

### The sign problem, and why the structure terms cannot be read

Every structural coefficient comes out negative -- at matched depth the
hurricane-force case is the *shallower, weaker-gradient* low. That is not a
statement about the atmosphere. It is the matching:

Depth at an instant conflates how strong a low is with how far along it is.
A case is a developing low 24 h short of its peak; a control drawn at a
random time is often at or past its own. Matching them on depth therefore
pairs a developing low with a mature one, and the mature one is
structurally stronger at the same depth because it has had time to spin up.
The negative coefficients are that pairing, not a finding, and adding
tendency makes the gradient's coefficient *more* negative rather than less
-- which is what an artifact does and a physical effect does not.

So this pass neither confirms nor refutes the compactness hypothesis. It
establishes that depth and scale at a single time, matched this way, carry
no separable signal, and that the tendency does.

### The next experiment, which is the right one

Invert the design: **match on tendency, then test whether structure adds.**
Among lows deepening at the same rate, does the compact one produce hurricane
force and the broad one not? That asks the question directly, and it removes
the maturity confound by holding fixed the variable that tracks it.

It is a small change -- tendency joins the matching criteria -- and the
extraction is already built and checkpointed, so only the matching and the
fit are rerun.

### What is not yet established

- The confirmation seasons (2021, 2023, 2025) have not been looked at, and
  will not be until a feature list and thresholds are written down.
- 79 strata is a small exploration set; z values of 3 are worth following,
  not worth believing.
- ERA5 at 0.25 deg smooths exactly the compact lows the hypothesis is about,
  which biases against finding the effect.
- The cyclone phase space fields are not in this table yet. Whether they add
  anything over tendency is untested.

## The inverted design, and why its result is withdrawn

Matching on tendency instead of depth gave a strong and internally
consistent answer: 88 strata, and at matched deepening rate the
hurricane-force case was the broader (OR 1.003 per km, z +2.8), shallower
(OR 0.922 per hPa, z -3.4), weaker-gradient (z -3.8) low, with the gradient
wind the single strongest term at z -4.4. The matching worked -- residual
tendency spread inside strata was 0.83 hPa/12 h against a 3.0 tolerance --
and the result is the opposite of the compactness hypothesis.

**It is an artifact, and so is the depth-matched result before it.**

Cases and controls were not measured the same way. A control is described
exactly where it was detected. A case is described after four backward
tracking steps, each searching a fixed 550 km radius around the previous
position. 550 km in 6 h is 48 kt of storm motion, more than most of these
systems manage, so the search routinely reached past the storm and took
whatever deeper minimum lay inside it: **147 of 190 cases came back with a
step pinned at the radius limit**, median 531 km against a 550 km cap, while
every control had a tracked distance of exactly zero.

Every bit of tracker degradation therefore landed on the cases and none on
the controls. That alone makes cases look systematically weaker than the
lows they are matched to, which is exactly what both analyses reported, in
both directions of matching. The finding was in the measurement, not the
atmosphere.

### The corrected tracker

`tracker.py` replaces it with a motion first guess -- extrapolate the
previous displacement and search 250 km around where the low should be,
rather than 550 km around where it was -- and, more importantly, a check
that it followed the same low: track back, track forward again, and see
whether you return to where you started.

On 25 cases the round trip misses by a median of 61 km, and 76% return
within 200 km. The remaining 24% are tracks that changed low, and they can
now be dropped as unverifiable instead of being carried into the table as a
weak low that was never the storm.

### What this means for the result

There is no result. Both answers above are withdrawn, and the hypothesis is
where it was after Phase 0.5: untested. What has been established is the
machinery and one hard lesson -- in a case-control design the two arms must
be *measured* the same way, not just matched the same way, and a tracker
that silently returns something is more dangerous than one that fails.

Redoing it means re-extracting the cases through the verified tracker,
dropping those that fail the round trip, and rerunning both matchings. The
control pool and its tendencies stand; only the case arm was corrupted.
