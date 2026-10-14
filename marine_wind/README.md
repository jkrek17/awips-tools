# Marine wind page (North Atlantic and North Pacific)

A public web page, served at `/marine-wind/` on the public site, that shows a
blended 10 m wind forecast for the North Atlantic (18–67N, 95W–10E, 0.25°) and
where forecasters should look:

| Layer | What it shows |
|---|---|
| Blended wind | base + min(k × member spread, 5 kt); k = 0.25, 0.15 at +24 h and earlier |
| Model base, added wind | the two parts of the blend; the base weights GFS, ECMWF and AIFS at each point by the share of members within about 5 kt of each |
| Model agreement | ride (all models < 30 kt), agree, focus (split across 34 kt or a 10 kt range near gale), high impact (split across 48 or 64 kt) |
| Member spread | standard deviation of about 80 GEFS + ECMWF ENS member speeds |
| Ensemble chance | share of members at 34, 48 and 64 kt or more: GEFS + ENS plus the 51-member AIFS ensemble (Brier score 6% better at 34 kt and 11% at 48 kt on 265 hindcast cases) |
| Single models | GFS, ECMWF, AIFS |

Overlays: sea-level pressure, the blend's 34 and 48 kt edges, wind arrows, and
lone-model signals (one model at 48 or 64 kt that neither other model has
within about 50 km). Hovering a point lists every value there.

## Why this blend

Averaging three models flattens the peaks: the plain average forecasts only
about 70% of the gale area that verifies. Adding a quarter of the ensemble
spread restores it. Weighting the models by member support,
rather than equally, trimmed the error at 25+ kt by about 0.1 kt more on the
200 out-of-sample cases. The recipe was tuned on 145 hindcast cases (fall 2026 and
winter 2025–26) and held up on 200 cases it never saw (Mar–Apr 2025, Oct–Nov
2025, Mar 2026), scored against the GFS and ECMWF analyses and against buoys
and ships. The experiment write-ups are in the project files under
`wind-focus/experiment/`.

In testing, a lone hurricane-force signal verified 3% of the time and a lone
storm-force signal 17%. A lone storm-force signal verified 54% of the time
when half or more of the members also reached 48 kt.

## How it runs

```
marine_wind/
  pipeline/build.py     fetch one cycle from the AWS mirrors, compute, write data/
  pipeline/fetch.py     byte-range GRIB fetch and decode to the domain
  pipeline/domain.py    the grid
  pipeline/build_coast.py  regenerate page/coast.js (Natural Earth 50m land)
  page/                 the static page (index.html, style.css, app.js, coast.js)
```

`.github/workflows/marine_wind.yml` runs `build.py` at 08:30 and 20:30 UTC.
By then the 00 and 12 UTC ECMWF ensemble is on AWS. The workflow force-pushes
the output to the orphan branch `marine-wind-live` under `latest/`. "Publish
public site" (`site_publish.yml`) then copies `page/` to `/marine-wind/` and
`latest/` to `/marine-wind/data/`.

Run it locally:

```
pip install -r marine_wind/pipeline/requirements.txt
python3 marine_wind/pipeline/build.py --out marine_wind/page/data   # newest complete cycle
python3 -m http.server -d marine_wind/page 8000
```

`page/data/` is ignored by git.

## Data format

`data/manifest.json` lists the cycle, the grid, the fields (name, scale, unit)
and the lead times. `data/fFFF.bin` holds one uint8 array per field, each
ny × nx, row-major, north row first, in manifest order. The stored value is
`round(value × scale)`, except `msl`, which is hPa − 900.

## North Pacific, recalibrated chances, run-to-run change (Oct 2026)

- `?basin=npac` shows the North Pacific (18–67N, 135E–115W, longitudes kept
  0–360 across the date line). The data workflow builds it from the same run
  into `latest/npac/`, published at `/marine-wind/data/npac/`. A hindcast on
  733 cases per basin (Sep 2025–Oct 2026) found the blend works there without
  retuning.
- `p48` and `p64` are the member shares recalibrated by basin and lead
  (`pipeline/calibration.json`, fitted on that hindcast against the GFS+IFS and
  IFS analyses). Raw shares stay in `p48raw` and `p64raw`. On months it was not
  fitted to, the recalibration cut the day 1–2 storm-force Brier error by about
  15% and later leads by 2–7%. `p34` stays the raw share, because buoys and
  ships say it is already about right.
- `trend` is the 3-model mean minus the run 24 h earlier at the same valid time.
  In the hindcast the truth fell back about a fifth of this change.
- Fields can carry an `offset` in the manifest: value = byte / scale − offset.
- The hindcast write-up is in the project files under `wind-focus/basins/`.

## Wider boxes (Oct 2026)

Both boxes now match the OPC 48 h surface chart areas: 18–67N, 95W–10E and
18–67N, 135E–115W (`pipeline/domain.py`; the Atlantic runs −95 to 10 across the
prime meridian). The blend, the storm-chance recalibration and the lone-model
rule were tuned and tested on 30–67N, 75W–0 and 30–67N, 160E–115W; the added
strips (subtropics, Gulf of Mexico, Caribbean, NW Europe, Sea of Japan) use them
untested. Tropical cyclones are outside what the recipe was tuned for.

## Daily verification (North Atlantic and North Pacific)

`verify/verify.py` scores the blend every day for both basins: the North
Atlantic box above and the North Pacific box (18–67N, 135E–115W). After the
12 UTC analyses are on AWS, it rebuilds the +24 to +120 h forecasts valid at
12 UTC from the AWS mirrors and scores them against:

- the GFS + ECMWF analysis mean and the ECMWF analysis alone, on open, ice-free water
- moored buoys, and ships plus buoys, from the GDAS marine monitoring file
  (first guess plus O−B; buoys raised to 10 m, ships scaled onto the buoy basis;
  stations with a persistent bias are listed in `verify/obs_blacklist.txt`)

It scores the page's blend, the equal-weight blend, the plain 3-model mean and
each model. The 34/48/64 kt chances get a Brier score.

`.github/workflows/marine_wind_verify.yml` runs it at 22:15 UTC. It keeps
`scores.csv` (one row per day, basin, lead, method and referee) and
`summary.md` (last 7 days, last 30 days, all) as the single commit of the
orphan branch `marine-wind-verify`. To backfill, run the workflow by hand with
a start date.

```
pip install -r marine_wind/verify/requirements.txt
python3 marine_wind/verify/verify.py --valid 20261012 --out day.csv
python3 marine_wind/verify/verify.py --summary day.csv --md summary.md
```
