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
