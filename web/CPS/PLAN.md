# Cyclone Phase Space, self-hosted web version

**Status:** the AWIPS D2D derived-parameter version under `D2D/` is
built, installed at OPC, and validated against the FSU page (see
`D2D/README.md`, Validation log). Phase 1 here (the math module
`cps/hart.py` and its tests) is done. The web pipeline and page (phases 2 to 5) are deferred: the
current starting point is the AWIPS D2D derived-parameter version under
`D2D/`, which needs no tracker, download, server, or page. See
`D2D/README.md`. This document remains the plan for the web version.
**Scope:** an interactive replacement for the static FSU cyclone phase
space plots (https://moe.met.fsu.edu/cyclonephase/), computed from
public NOAA GFS output and served from one Linux box with no paid or
managed cloud services.

The AWIPS-native version (same math, data from the DAL, output in GFE)
is deliberately out of scope for this document. The math module is
written with no AWIPS or web dependencies so it can be reused there
later without change.

---

## 1. What we are building

Four linked panels, matching what forecasters already know from the
FSU page:

1. Track map with the model track, colored by intensity.
2. MSLP and Vmax trace against forecast hour.
3. Phase diagram 1: parameter B (thermal asymmetry) against -V_T^L
   (lower-tropospheric thermal wind).
4. Phase diagram 2: -V_T^L against -V_T^U (upper-tropospheric thermal
   wind).

Hovering a forecast hour in any panel highlights the same hour in the
other three. A storm and cycle picker browses the archive. A 3D view
(B, -V_T^L, -V_T^U) is an optional toggle.

Deterministic GFS only for the first release. GEFS members and other
models are phase 2 items; the JSON schema and the page are designed so
adding them does not change the existing files.

---

## 2. Architecture

```
NOAA public HTTPS                    your server
------------------                   -----------------------------------------
NHC a-deck (storm tracks)  ---+
                              +-->  cps/ pipeline (Python, numpy)  -->  data/*.json
AWS open-data GFS GRIB2    ---+       systemd timer, every 30 min          |
  (byte-range, .idx)                                                        v
NOMADS grib filter (fallback)                                nginx serves data/ + web/CPS/
                                                                            |
                                                                            v
                                                             browser: index.html + Plotly + Leaflet
```

Everything on the server side is a directory of JSON files. There is no
database, no API server, no queue, and no cache layer. nginx serves the
JSON and the page with gzip and long cache headers. The pipeline is a
single Python process started by a timer.

### 2.1 Server requirements

- Linux (any current Debian, Ubuntu, Rocky, or RHEL), 2 cores, 4 GB RAM,
  20 GB disk. Bandwidth is the only resource that matters: about 100 to
  450 MB inbound per GFS cycle depending on the resolution choice in 3.3.
- Python 3.10 or newer in a venv.
- nginx (or Apache; nothing here depends on which).
- Outbound HTTPS to `ftp.nhc.noaa.gov`, `noaa-gfs-bdp-pds.s3.amazonaws.com`,
  and `nomads.ncep.noaa.gov`.

### 2.2 Python dependencies

| Package | Why | Notes |
| :--- | :--- | :--- |
| numpy | all the math | |
| requests | HTTPS fetches with Range headers | |
| pygrib | decode GRIB2 messages to arrays | Linux wheels bundle ecCodes, so `pip install pygrib` is the whole install. cfgrib + eccodes is the fallback if the wheel is unavailable on the target OS. |
| matplotlib | offline verification plots only | not needed at runtime |

No xarray, MetPy, Herbie, or pandas. The byte-range fetcher is about 60
lines against the `.idx` sidecar and not worth a dependency.

---

## 3. Data sources

### 3.1 Storm positions: NHC a-deck

The center the phase space is computed around must be the model's own
vortex, not the official forecast. NCEP runs the GFDL vortex tracker on
every GFS cycle and the results are published in the ATCF a-deck files:

- `https://ftp.nhc.noaa.gov/atcf/aid_public/aAL092026.dat.gz` (and `aEP`, `aCP`).
- Tech `AVNO` is the raw GFS tracker output, 6-hourly, out to 168 h or
  beyond. Each line gives forecast hour, lat, lon, Vmax, MSLP, and the
  wind radii.
- Invests (`AL9x`) are in the same directory, so pre-genesis systems are
  covered as soon as NHC opens an invest.
- GEFS members are `AP01` through `AP30` and `AEMN` in the same file,
  which is what makes ensemble support a phase 2 item rather than a
  rewrite.

The a-deck is the source of truth for the track, the MSLP and Vmax
trace, and the storm motion used by parameter B. The pipeline
re-centers each position on the local MSLP minimum in the fetched
fields, with a cap of 100 km, to remove tracker and grid-interpolation
offsets before drawing the 500 km circle. The cap keeps a bad refit
from jumping to a neighboring low.

Limits, to be honest about up front:

- NHC's public a-decks cover the Atlantic, East Pacific, and Central
  Pacific only. West Pacific is not in scope for release 1. The path to
  it is either NCEP's own tracker file posted with each GFS run on
  NOMADS (covers all basins; exact filename to be verified) or the
  guided MSLP-minimum tracker described in the AWIPS discussion, seeded
  from JTWC warnings. Either fits behind the same `positions()`
  interface.
- The a-deck for a cycle lands roughly 4 to 6 hours after synoptic time,
  which sets the latency of the whole product. Nothing we can do about
  it.
- Non-tropical lows are out of scope until a tracker exists.

### 3.2 Model fields: GFS over HTTPS

Primary: AWS Open Data. The bucket is public over plain HTTPS with no
account:

```
https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.YYYYMMDD/HH/atmos/gfs.tHHz.pgrb2.0p50.fFFF
https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.YYYYMMDD/HH/atmos/gfs.tHHz.pgrb2.0p50.fFFF.idx
```

The `.idx` file lists every GRIB message with its byte offset. The
fetcher reads it, finds the wanted messages, and issues one HTTP Range
request per message. Fields needed per forecast hour:

| Field | Levels | Used for |
| :--- | :--- | :--- |
| HGT | 900, 850, 800, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300 hPa | B, -V_T^L, -V_T^U |
| PRMSL | mean sea level | center refinement, trace |
| UGRD, VGRD | 925 hPa | gale radius for marker size |
| UGRD, VGRD | 10 m | intensity trace cross-check |

Fallback: the NOMADS grib filter
(`https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p50.pl`), which
returns only the requested variables, levels, and a lat/lon box. Tiny
downloads, but NOMADS throttles by IP and gets unreliable during
landfall events. It is the fallback, not the primary, for that reason.

The AWS bucket also holds the full GFS archive back to early 2021, so
the same fetcher can backfill an archive of past storms for the
historical overlay feature.

### 3.3 Resolution decision: 0.5 degree

Hart's method was developed and calibrated on 1 degree data. The
thermal wind terms use max minus min height inside a circle, which is
sensitive to grid noise, and 0.25 degree output produces visibly
noisier trajectories than the FSU plots. The 0.5 degree product has the
same 13 levels, matches FSU behavior more closely, and cuts inbound
transfer by three quarters. Resolution is a config value; nothing in
the math depends on it.

To verify before coding: that `pgrb2.0p50` carries HGT on all 13
levels. If it only has the mandatory levels, switch to
`pgrb2full.0p50`.

---

## 4. The math (Hart 2003)

Implemented in `cps/hart.py` with numpy only, no I/O, so it is unit
testable and reusable in AWIPS.

Inputs per forecast hour: center lat/lon, storm motion vector, and for
each of the 13 levels a 2D height array with its lat/lon grids.

1. Build a great-circle distance mask for points within 500 km of the
   center. Cosine-latitude weighting applies to every areal mean.
2. **Parameter B.** Thickness `Z600 - Z900`. Split the masked points
   into right and left of the motion vector. `B = h * (mean_right -
   mean_left)`, with `h = +1` in the Northern Hemisphere and `-1` in the
   Southern. Threshold 10 m separates symmetric from asymmetric.
3. **Thermal wind.** At each level, `dZ = max(Z) - min(Z)` inside the
   mask. Least-squares slope of `dZ` against `ln(p)` over 900 to 600 hPa
   gives `V_T^L`; over 600 to 300 hPa gives `V_T^U`. Report the
   negatives. Positive is warm core, negative is cold core.
4. **Gale radius.** Mean radius of the 34 kt isotach at 925 hPa over
   the eight compass sectors, for marker sizing. Sectors with no 34 kt
   wind contribute zero, following Hart.
5. Storm motion comes from a centered difference of the a-deck track
   positions, forward or backward at the ends.

Outputs: `B`, `VTL`, `VTU`, `gale_radius_km`, plus diagnostics that
make debugging possible without re-running: the number of grid points
in the mask, the refined center, the per-level `dZ` values.

---

## 5. Pipeline

`cps/run.py`, invoked by a systemd timer every 30 minutes. Idempotent;
a crash mid-run is retried on the next tick.

1. Load `state.json` (cycles already completed, per storm).
2. Determine the newest GFS cycle whose forecast hour 168 file exists on
   AWS. Skip if already done.
3. Fetch the a-decks for every active basin. Collect every storm and
   invest with an `AVNO` line for that cycle.
4. For each forecast hour 0 to 168 step 6, fetch the fields once (shared
   across storms), then compute the parameters for every storm.
5. Write `data/gfs/YYYYMMDDHH/AL092026.json` per storm and
   `data/gfs/YYYYMMDDHH/index.json` for the cycle.
6. Rewrite `data/manifest.json`, the flat index the page reads: storms,
   cycles per storm, latest cycle, names.
7. Update `state.json`.

Runtime is a few minutes per cycle on a small box, dominated by
download. Fetched GRIB is discarded after use. Output is about 30 kB per
storm per cycle, so the archive is small forever.

Logging goes to a file under `logs/` with one line per storm per cycle
and a clear failure line when a fetch or a track lookup fails. A storm
that fails does not block the others.

### 5.1 JSON schema (per storm, per cycle)

```json
{
  "schema": 1,
  "model": "GFS",
  "resolution_deg": 0.5,
  "cycle": "2026-09-09T00:00:00Z",
  "storm": {"id": "AL092026", "name": "HELENE", "basin": "AL"},
  "source": {"track": "NHC a-deck AVNO", "fields": "AWS noaa-gfs-bdp-pds"},
  "points": [
    {
      "fhr": 0,
      "valid": "2026-09-09T00:00:00Z",
      "lat": 24.1, "lon": -74.3,
      "mslp_hpa": 985.0, "vmax_kt": 75,
      "B": 4.2, "VTL": 118.0, "VTU": 31.0,
      "gale_radius_km": 210.0,
      "diag": {"npts": 311, "center_shift_km": 18.0}
    }
  ]
}
```

`points` may contain `null` for `B`, `VTL`, `VTU` when the mask has too
few points (storm at the edge of the domain) or the a-deck has no
position for that hour. The page must handle gaps.

Ensemble output, when added, is a separate file per cycle
(`AL092026.gefs.json`) with a `members` array of the same point shape,
so release 1 files never change format.

---

## 6. Frontend

Plain HTML, CSS, and JavaScript. No build step, no framework, no
bundler. This matches `web/TCWind_JTWC` and keeps the page editable by
anyone who can edit a text file.

Files under `web/CPS/`:

- `index.html`: layout, panel containers, storm and cycle pickers.
- `app.js`: fetch manifest and storm JSON, build the four panels, wire
  hover sync.
- `style.css`: layout grid, dark and light theme via CSS variables.
- `vendor/`: pinned copies of `plotly.min.js` and `leaflet.js` plus
  Leaflet CSS, so the page works on a network with no CDN access.
- `coastlines.json`: Natural Earth 110 m coastline GeoJSON so the map
  works with no tile server. Basemap tiles from OpenStreetMap are an
  optional layer when the browser has internet.

Panel behavior:

- **Phase diagrams** reproduce Hart's layout: quadrant shading, the
  B = 10 line and the zero lines, the same axis ranges as the FSU plots
  so nobody has to relearn them. Markers colored by MSLP and sized by
  gale radius, the trajectory line colored by forecast hour, an `A` at
  the first point and a `Z` at the last, labels every 24 h.
- **Track map** uses the same colors so a point is recognizable across
  panels.
- **Trace** shows MSLP and Vmax on twin axes.
- **Hover sync** is one shared `activeIndex` variable. Each panel's
  hover handler sets it and calls a `highlight(i)` on the others via
  `Plotly.restyle` and a Leaflet marker update. About 40 lines total.
- **3D toggle** replaces the two 2D phase panels with one `scatter3d`
  trace.
- **Pickers** read `manifest.json`. URL hash carries storm and cycle so
  a view is linkable.

Deliberately not in release 1: ensemble overlay, historical overlay,
model comparison. The picker and JSON layout leave room for all three.

---

## 7. Serving

nginx server block: root at the repo's `web/CPS`, an alias for `/data/`
to the pipeline output directory, `gzip on` for JSON, a short cache
lifetime on `manifest.json` and a long one on cycle files since they
never change once written. Optional basic auth if this stays internal.
A dedicated non-root user owns the pipeline and its output; nginx only
needs read access.

---

## 8. Verification

The science is the risk, so verification comes before the page.

1. **Analytic test.** A synthetic vortex with a Gaussian warm-core
   height perturbation whose amplitude decays with height. Expected
   results: `B` near zero, `VTL` and `VTU` positive with `VTL > VTU`.
   Rotating the perturbation to add a known left-right thickness
   difference must move `B` by exactly that amount. Flipping the
   hemisphere must flip the sign of `B`.
2. **Golden files.** One real cycle and storm stored under
   `tests/cps/fixtures/` as extracted arrays (not GRIB, to keep the
   fixture small) with the expected JSON checked in, the same way
   `tests/tcwind_jtwc` does it.
3. **FSU comparison.** Run the pipeline for a cycle that exists in the
   FSU archive (for example the 2026090900 run) and overlay our
   trajectory on their image with matplotlib. Shapes and quadrant
   crossings should agree; exact values will not, because FSU uses its
   own tracker and grid.
4. **Fetcher test.** The `.idx` parser against a checked-in index file,
   confirming it selects exactly the 17 wanted messages per hour.

---

## 9. Phases and effort

| Phase | Deliverable | Rough effort |
| :--- | :--- | :--- |
| 1 | `cps/hart.py` with the analytic tests passing | 1 to 2 days |
| 2 | a-deck parser, `.idx` fetcher, pygrib decode, one storm end to end, FSU comparison plot | 2 to 3 days |
| 3 | timer, state, manifest, logging, nginx config, running on the server | 1 day |
| 4 | `web/CPS` page with the four panels and hover sync | 2 to 3 days |
| 5 | archive browsing and linkable URLs | half a day |
| Later | GEFS members from `AP01..AP30`, ECMWF once a public track source exists, historical overlay from the AWS backfill, West Pacific via NCEP tracker file or the guided tracker, AWIPS-native procedure reusing `cps/hart.py` | |

---

## 10. Open items to confirm before phase 2

- `pgrb2.0p50` carries HGT on all 13 levels 900 to 300 hPa (else use
  `pgrb2full.0p50`).
- The `AVNO` line in current a-decks extends to 168 h at 6 h spacing
  (older files were 12-hourly beyond 72 h; if so, interpolate and mark
  the interpolated hours in `diag`).
- Whether the target server can reach all three NOAA hosts.
- Whether the page will be public or internal, which decides basic auth
  and whether the OpenStreetMap tile layer is on by default.
