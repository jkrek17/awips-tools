# ERA5 exploration — scripts and what they established

Research code, not part of the site build. Unlike everything in `tools/`, these
scripts need `numpy` and `numcodecs` (`pip install numpy numcodecs`) and they
stream from a public Google Cloud mirror of ERA5. Nothing here runs in CI,
nothing here feeds `docs/`, and no site data depends on it.

They are committed because the work cost real effort to establish and the
findings below are worth not rediscovering.

## WHAT DOES NOT EXIST HERE

**There is no calibrated gust index.** No HF-equivalent criterion has been
fitted, validated, or applied. If you have been told a calibration exists, it
does not. What exists is the pilot evidence that a gust-based criterion is the
right shape for one, and a stationarity test that says where it could safely be
applied. Both are described below.

There is also no extended event record. The archive still starts in 2001.

## The store

    https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3

Hourly, 0.25 degrees, one blosc-compressed chunk per variable per time step,
shape [1, 721, 1440], about 2.16 MB for mean sea level pressure and 3.2 MB for
instantaneous 10 m wind gust. `era5lib.py` has the chunk fetch and the time
index. Verified present for every year from 1940 to 2026.

Despite the "zarr-v3" in the path the layout is v2, which is why these scripts
fetch chunks by URL rather than through a zarr client.

## What the pilot established (2001-2026 overlap with the archive)

- Mean sea level pressure carries a **+0.6 hPa median bias** against the
  archive's analysed central pressures. Small and correctable.
- **10 m wind is unusable as an HF criterion**: 0 of 103 sampled events reach
  64 kt. ERA5 at 0.25 degrees does not resolve the wind maximum.
- **Gusts are usable**: median 73 kt, 85% at or above 64 kt. Any criterion has
  to key on gusts or on pressure gradient, not on sustained wind.
- A cyclone tracker reached 95% detection at AUC 0.93 against the archive, but
  **no single threshold reproduces the archive's event set**. That is the reason
  to build an index rather than a detector.
- Greenland tip jets are **not** damped worse than other events, contradicting
  the expectation going in.

## The stationarity test — the gate on extending the record backwards

`stationarity.py`, result in `stationarity-result.txt`.

The question: a criterion calibrated in the satellite era can only be applied to
earlier decades if ERA5's own representation of deep cyclones is stationary. If
it is not, an extended record would carry a reanalysis observing-system artefact
in place of the recording-practice artefact the archive had — the same mistake
in different clothes.

North Atlantic 30-70N, 80W-10E, January and February, 16 sampled 6-hourly
fields per year, every third year 1940-2024:

    quantity                 pre-satellite   satellite era        t
                               (1940-1976)     (1979-2024)
    min MSLP, mean                  970.01          970.36     +0.3
    min MSLP, p10                   955.07          957.09     +0.9
    max gradient hPa/100km           21.46           19.37     -2.8
    fields with a low <960           17.8%           19.1%     +0.4
    fields with a low <980           79.3%           75.1%     -0.8

So pressure DEPTH looks stationary, and pressure GRADIENT — the quantity a wind
or gust criterion leans on hardest — runs about 11% stronger before 1979. The
trend across the whole record is t = -2.5, but within the satellite era alone
only t = -1.2, which is the shape of a step at the observing-system boundary
rather than a climate trend.

The direction matters: stronger early gradients mean a gust-based criterion
would flag MORE events before 1979 and manufacture a spurious DECLINE in
hurricane-force frequency.

**This result is a flag, not a finding, and must not be built on.** It rests on
16 fields per year from two months, and it measures a basin-wide maximum, which
is an extreme-value statistic with a between-year sd of 2.20 against an era
difference of 2.10. A proper test needs every year rather than every third,
September through May rather than two months, many more fields per year, and the
actual `instantaneous_10m_wind_gust` variable in place of the gradient proxy
used here. Roughly 15-20 GB streamed.

## Why extending the record was being considered at all

The teleconnection analysis is limited by seasons, not by events. Each index
contributes only so much independent information per winter:

    index   lag-1 autocorrelation   independent values per Oct-May season
    ONI     0.958 (monthly)         about 1
    NAO     0.95  (daily, ~19 d)    about 7

ONI is published monthly but is so strongly autocorrelated that a winter holds
about one independent value. Effective sample sizes at 25 seasons come out at
about 27 for ONI and about 188 for NAO, which matches the variance
decomposition (ICC 0.94 and 0.12).

Consequently the detectable interference effect — whether two teleconnections
reinforce or cancel — sits at 34-40% of the NAO main effect, and only more
SEASONS can lower it. Adding more cyclones per winter cannot, because the
predictor's own decorrelation time, not the number of storms, sets the ceiling.
ERA5 reaching back to 1940 is the only available route, which is what the
stationarity test above is gating.

Note that the archive cannot be extended from the warning text instead: OPC's
Atlantic high seas product contains no "HURRICANE FORCE" wording in 1990, 1994,
1996, 1998, 1999 or 2000, then 13 occurrences in a single month of 2001. The
archive starts in 2001 because the warning category does.

## If you build the criterion

Two things worth carrying over:

A criterion fitted against the archive inherits the archive's definition, so an
extended record measures "cyclones ERA5 says look like what OPC called hurricane
force" — well defined, but not the same quantity. It should be labelled a proxy
everywhere it appears, and it can never be validated before 2001 because there
is nothing to validate against.

The overlap is more useful as a laboratory than as a training set. Fitting on
2001-2005 and testing on 2021-2025, and the reverse, measures how much the
criterion drifts across 20 years of ERA5's own evolution, and that drift rate is
the evidence for or against reaching further back. Fitting only on the most
recent years maximises input quality but also maximises the observing-system
distance to the era being extrapolated to.

## Scripts

    era5lib.py          chunk fetch, time indexing, the lat/lon grid
    sizes.py            per-variable chunk sizes by era, for cost projection
    ncar_probe.py       alternative-store probe
    sample.py           single-field sanity checks
    compare.py          ERA5 pressure against archive analysed pressure
    analyse.py          summary of that comparison
    month.py            one month of candidate cyclone detections
    matchmonth.py       candidates matched to archive events
    mismatch.py         the ones that do not match
    evalmonths.py       detection and AUC across months
    evalmonths_core.py  scoring used by evalmonths
    tip.py              Greenland tip-jet damping check
    envdemo.py          environment and access demo
    stationarity.py     the observing-era gate described above
