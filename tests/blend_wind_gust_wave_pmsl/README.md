# `Blend_WindGustWavePmsl` checks

`GFE/procedures/Blend_WindGustWavePmsl.py` builds Wind, WindGust, WaveHeight
and pmsl from one set of model weights, using each model's newest complete
run, and writes nothing unless every model grid it needs is there and holds
data. Two scripts check it outside AWIPS:

```bash
python3 test_blend.py        # scenarios on a fake database - numpy only
python3 run_real_data.py     # the newest real GFS and ECMWF runs, checked and plotted
```

Both exit non-zero on a failed check. `run_real_data.py` writes its log,
maps and download cache to `out/`, which is gitignored.

## Why a harness

The procedure imports `SmartScript`, `AbsTime` and `TimeRange`, none of
which exist outside AWIPS. `gfe_fakes.py` registers fakes for them (and a
stub `tkinter` when the real one is missing), then the scripts import the
procedure and call `Procedure.execute()` with a `varDict`, the way another
procedure would, so the dialog never opens.

The fake database answers `findDatabase(name, -n)` from a newest-first list
of model ids, `getGridInfo` from the grids that are actually there, and
`getParm(...).getGridInfo().getUnitString()` with each parm's units. It
records every `createGrid`, which is what lets a test assert that *nothing*
was written when a check fails. A grid may be a callable, so the real-data run
only downloads what the procedure asks for.

## `test_blend.py`

A small domain with Fcst grids every 3 h, and model databases built to hit
each path:

| Scenario | What it proves |
|---|---|
| GFS 18Z stops at 60 h, 12Z is complete | The newest *complete* run is used, and the skipped 18Z is named in the status message. |
| ECMWF grids every 6 h | Fcst times between them are interpolated; m/s, Pa and m are converted to kt, mb and ft. |
| ECMWF has no gust grid | Its gust is its wind x the gust factor; GFS's own gust grid is blended as is. |
| CMC has no pmsl | Urgent error naming CMC and pmsl; nothing written. |
| UKMET (no database, no wave pairing) | Both problems reported; nothing written. |
| One all-zero GFS pmsl grid | Caught by the read-ahead check; nothing written. |
| A 12 h gap in the ECMWF wave grids | Too far apart to interpolate; error names the missing time; nothing written. |
| Edit area over half the grid | Points outside keep their Fcst values. |
| Wave grids with land as missing | Land keeps the Fcst value; sea points are blended. |

## `run_real_data.py`

Fills the fake database with the last few GFS / GFS Wave cycles from NOMADS
and ECMWF / ECMWF wave cycles from the ECMWF open-data server, laid out the
way D2D presents them: `wind` FHAG10 and `gust` SFC in m/s, `pmsl` MSL in Pa,
`WaveHeight` in m. Only what the procedure reads is downloaded - NOMADS cuts
GFS to the box server-side, ECMWF fields come by byte range from each step's
`.index`. The procedure picks each model's run itself, as it would in GFE.

```bash
python3 run_real_data.py                                 # W Atlantic 30-50N 80-50W, from now, 90 h
python3 run_real_data.py --box 30,55,-150,-120 --hours 72 --weights GFS=1,ECMWF=1
python3 run_real_data.py --start 2026101306              # a fixed start time
```

Needs `numpy`, `matplotlib`, `requests` and `eccodes` (`pip install eccodes`
brings the ecCodes library with it). It checks every written grid - no
missing values, none one value everywhere, gusts never below the wind, and the
pmsl blend equal to the weighted model mean - then writes three maps of each
model beside the blend, and a time series of the blend's extremes.

On the first run (13 Oct 2026, 03Z) both models used their 18Z runs: the 00Z
runs had nothing posted yet, so the procedure passed over them. All 124 grids
(4 elements x 31 times) passed the checks.

Two details of the open data the script handles: ECMWF's gust is `10fg`
through 90 h and `10fg3` after it, and NOMADS answers 403, not 404, for a
cycle that has not started posting.

## Not covered here

These need a real GFE: the parm and level names your D2D databases use
(listed at the top of the procedure, easy to change), and laying out new Fcst
grids on an element's time constraints when the selection has none.
