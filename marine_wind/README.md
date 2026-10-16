# Marine wind page (global)

A public web page, served at `/marine-wind/` on the public site, that shows a
blended 10 m wind forecast for the whole globe (0.25°, shown to 85N and 85S) on a
map that pans and zooms, and where forecasters should look. Buttons jump to the
OPC Atlantic (18–67N, 95W–10E) and Pacific (18–67N, 135E–115W) chart areas. The
blend was tuned and tested only on 30–67N in those two basins; the page outlines
that area and the readout flags points outside it.

| Layer | What it shows |
|---|---|
| Blended wind | base + min(k × member spread, 5 kt); k = 0.25, 0.15 at +24 h and earlier |
| Model base, added wind | the two parts of the blend; the base weights GFS, ECMWF and AIFS at each point by the share of members within about 5 kt of each |
| Model agreement | ride (all models < 30 kt), agree, focus (split across 34 kt or a 10 kt range near gale), high impact (split across 48 or 64 kt) |
| Member spread | standard deviation of about 80 GEFS + ECMWF ENS member speeds |
| Ensemble chance | share of members at 34, 48 and 64 kt or more: GEFS + ENS plus the 51-member AIFS ensemble (Brier score 6% better at 34 kt and 11% at 48 kt on 265 hindcast cases) |
| Deterministic blend (GFE test) | a blend that needs no ensemble members, for GFE: GFS, ECMWF and AIFS weighted by support among 9 runs (these and the same models from the runs 12 h and 24 h earlier, same valid time) + min(0.3 x spread of the 9, 5 kt); and its difference from the blended wind where either has 25+ kt |
| Single models | GFS, ECMWF, AIFS |

Overlays: sea-level pressure, the blend's 34 and 48 kt edges, wind arrows, and
lone-model signals (one model at 48 or 64 kt that neither other model has
within about 50 km), and the tested area. Hovering a point lists every value there.
The side panel sums up what is in view.

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
  pipeline/domain.py    the grids (global, and the two OPC boxes)
  pipeline/build_coast.py  regenerate page/land.json (Natural Earth 50m land)
  page/                 the static page (index.html, style.css, app.js, scorecard.js, land.json)
  page/lib/             MapLibre GL JS 5.24.0 (BSD-3-Clause, same build as /ndfd/), kept here so the page needs no CDN
```

`.github/workflows/marine_wind.yml` runs `build.py --domain glob` at 02:30, 08:30,
14:30 and 20:30 UTC for every 00, 06, 12 and 18 UTC cycle, once its models and the
ECMWF ensemble reach +120 h on AWS (about 7-8 h after the cycle); a cycle already
published is not rebuilt. One global build
replaces the two basin builds: the pipeline always downloaded each model's whole
global GRIB record and cropped it, so the build time is set by the download and
the globe costs about what one box did (about 2 minutes a lead, 2.6 GB of memory).
The workflow force-pushes the output to the orphan branch `marine-wind-live`
under `latest/` (the globe in `latest/global/`, the two boxes cut from it in the
older format in `latest/` and `latest/npac/`). "Publish public site"
(`site_publish.yml`) then copies `page/` to `/marine-wind/` and `latest/` to
`/marine-wind/data/`.

Run it locally:

```
pip install -r marine_wind/pipeline/requirements.txt
python3 marine_wind/pipeline/build.py --domain glob --out marine_wind/page/data/global --boxes marine_wind/page/data
python3 -m http.server -d marine_wind/page 8000
```

`page/data/` is ignored by git.

## Data format

`data/global/manifest.json` lists the cycle, the grid (with the tested boxes),
the fields (name, scale, unit, offset) and the lead times, with the H and L
centres for each. `data/global/fFFF/NAME.gz` holds one field: 721 × 1440 uint8
(90N to 90S, 180W to 179.75E), row-major, north row first, each row stored as
differences from the cell to its west (mod 256) and gzipped. The page fetches
the 19 fields of a lead (about 3.5 MB) and undoes the differences with a running
sum. The stored value is `round((value + offset) × scale)`, except `msl`, which
is hPa − 900.

The older per-basin files (`data/manifest.json` + `data/fFFF.bin`, and the same
under `data/npac/`) hold every field of a lead in one file, ny × nx per field in
manifest order.

## The map

`page/app.js` draws on a MapLibre GL JS (WebGL) globe over the Esri World Ocean
basemap, styled like the site's `/ndfd/` page (top bar with the valid time,
layers panel, legend card, timeline). MapLibre, the shared look, the map setup,
the overlay canvas, the timeline rail and the land outline come from the globe
kit (`globe_kit/`, published at `/globe-kit/` and loaded as `../globe-kit/`; to
run the page locally, serve a folder with `marine-wind/` and `globe-kit/` side by
side). The page loads no map fonts. The field is
coloured in the browser into 256 px raster tiles made on demand from the grid (a
`mwfield://` tile protocol), with land (the kit's `land.json`) cut out of each tile so the
basemap's land and a sharp coast show; the GPU wraps them onto the globe.
Isobars, the 34 and 48 kt edges and the lone-model outlines are contoured in the
browser once per lead and drawn as line layers. Text (H and L, isobar values,
lone-model labels, graticule labels) and the wind arrows go on a 2D canvas over
the map, leaving out anything on the far side of the globe or crowded on its rim.
The storm layers (from `storm.py`, live since #97) add two map layers (most
likely wind with cores kept, storm core chance), the gale/storm/HF possible
lines contoured from the `hazard` bits, and the ensemble low tracks from
`tracks.json`: solid to the shown lead, dashed beyond, with the cone. The view is kept in the link (`#layer/lead/zoom/lat/lon`); older `?basin=npac`
links open the Pacific area. The Model scorecard opens for the basin the map is centred on.

## Outside the tested area (Oct 2026)

The blend, the storm-chance recalibration and the lone-model rule are applied
everywhere unchanged. `p48` and `p64` use each basin's table inside its OPC box
and the average of the two tables elsewhere. Nothing outside 30–67N in the two
basins has been tested; tropical cyclones are beyond what the recipe was built
for. The daily verification scores the tropics (18S–18N) and the Southern Ocean
(30–67S) alongside the two boxes so evidence builds up.

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

## Daily verification

`verify/verify.py` scores the blend every day for the North Atlantic and North
Pacific boxes above, and for the tropics (18S–18N) and the Southern Ocean
(30–67S), where the global page runs it untested. After the
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

## Model scorecard

The "Model scorecard" button opens how GFS, ECMWF and AIFS have handled the
pattern over the last 7 and 30 days, for the page's basin, by forecast day
(1 to 5). It is for awareness only and does not feed the blend: in a winter
2025–26 test on 151 North Atlantic runs, the model that had led over the past
3, 7 or 15 days was no more likely to lead the next run than its season-long
ranking already said, and weighting the blend by recent skill did not help.

| Field | Area | Scores |
|---|---|---|
| Sea-level pressure | the high seas the blend was tested on: 30–67N, Atlantic 75W–0, Pacific 160E–115W | RMSE; position and central-pressure error of analysed lows under 1000 hPa (matched within 800 km) and the share missed; 34 and 48 kt hit scores (CSI) for 10 m wind on open water |
| 500 mb height | 25–75N, Atlantic 130W–10E, Pacific 100E–110W (the basin plus upstream) | anomaly correlation against the ERA5 1990–2019 climatology, and RMSE |

Truth is the mean of the GFS and ECMWF analyses at 12 UTC, so no model is
scored against its own. The hit scores sit next to the pressure scores because
AIFS's smooth fields score well on pressure error but have the weakest storm
cores. A 30-day strip of the headline score shades days when all three models
did worse than their own usual, which points to a hard pattern rather than one
bad model.

```
marine_wind/scorecard/
  scorecard.py     score one 12 UTC valid day (or --backfill N days) into scores.json
  make_climo.py    one-time build of z500_clim.npz from WeatherBench 2's ERA5 climatology
  z500_clim.npz    500 mb height climatology, 12 UTC, 18–82N, 1.5 deg, by day of year
page/scorecard.js  the scorecard sheet
```

`.github/workflows/marine_wind_scorecard.yml` runs at 21:45 UTC. It rescores
the last three days into `scores.json` (newest 60 days kept; 30 days are
backfilled the first time) and force-pushes it as the single commit of the
orphan branch `marine-wind-scorecard`. Publish public site copies it to
`/marine-wind/data/scorecard.json`.

```
pip install -r marine_wind/pipeline/requirements.txt
python3 marine_wind/scorecard/scorecard.py --backfill 30 --scores marine_wind/page/data/scorecard.json
```
