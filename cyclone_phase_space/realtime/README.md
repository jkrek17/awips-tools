# Realtime GFS cyclone phase space (proof of concept)

*** EXPERIMENTAL. NOT OPERATIONALLY VETTED. ***

`gfs_cps.py` makes the OPC four-panel cyclone phase space images from
public GFS 0.25 degree data, with no AWIPS or CAVE in the loop. It
downloads only the GRIB2 messages the products need, runs them through
the operational D2D module
`cyclone_phase_space/D2D/derivedParameters/functions/cps_HartCPS.py`
(imported unchanged, through its AWIPS entry points and with the same
constants as the XML definitions), and writes for every forecast hour:

- `out/<cycle>/cps_<region>_f<hhh>.npz`: HVTL, HVTU, HB, HCPSidx
  (`idx`) and HCPSclass (`cls`) as float32, plus `mslp_hpa`, `lat`,
  `lon`, compressed, clipped to the region;
- `out/<cycle>/cps4_<region>_f<hhh>.png`: the four-panel figure, 1800 px
  wide, laid out like the CAVE procedure (article Figure 11): top left
  HCPSclass with MSLP every 4 hPa and each detected low labeled with its
  central pressure, top right HB on CPS_Asymmetry with MSLP, bottom left
  HVTL on CPS_CoreDiverging with 850 hPa wind barbs (kt), bottom right
  HVTU on CPS_CoreDiverging with 300 hPa wind arrows, coastlines on all
  four, a colorbar per panel;
- `out/<cycle>/lows_<region>.csv`: one row per detected low (below);

and, when more than one hour is requested,
`out/<cycle>/cps4_<region>_montage.png`, one row per hour with the four
products across, like the article's Figure 12.

## Running

    pip install -r requirements.txt
    python3 gfs_cps.py --cycle 2026092406 --hours 6 54 78 102 126 --region natl

| Option | Default | Meaning |
|---|---|---|
| `--cycle YYYYMMDDHH` | latest | Latest is the most recent cycle whose f006 index exists on NOMADS (or AWS), probed back up to two days. |
| `--hours H [H ...]` | 0 to 120 step 6 | Forecast hours. An hour that is not posted yet is skipped with a message. |
| `--region` | `natl` | `natl` 100W to 20E, 5N to 80N; `npac` 120E to 110W across the dateline, 5N to 70N; `global` the whole grid. |
| `--out DIR` | `realtime/out` | Output root; frames go to `DIR/<cycle>/`, downloads to `DIR/cache/<cycle>/`. |
| `--source` | `nomads` | `nomads` or `aws`. NOMADS falls back to AWS by itself after 3 failed tries with backoff (2 s, 4 s). |
| `--plain` | off | Skip cartopy and draw plain lon/lat maps (see coastlines below). |
| `--track NAME:LAT,LON[:FHR0[:FHR1]]` | none | Follow a low from LAT,LON (degrees, west negative) at forecast hour FHR0 (default 0), optionally only up to hour FHR1, and draw its phase diagrams instead of the maps; repeatable. See "Storm-following phase diagrams" below. |
| `--hart-bands` | off | Also fetch HGT every 50 hPa from 900 to 300 hPa and compute the thermal wind terms over Hart's own 900-600 and 600-300 hPa bands (`executeBand7`); added to the npz as `hvtl_hart`, `hvtu_hart`, or to the track tables. |

Run time on this machine for the five natl frames above, from an empty
cache: about 50 s in total (per frame about 1.5 s download and decode
from NOMADS, 1.5 s for the five products, 4 s for the figure; the
montage about 20 s). From the AWS bucket the download is about 10 s per
frame. A global frame computes in about 8 s.

## Data sources and what is fetched

Per forecast hour, 17 messages of `gfs.tHHz.pgrb2.0p25.fFFF`:

- HGT at 925, 850, 700, 500, 400, 300 mb;
- UGRD and VGRD at 850, 700, 500, 300 mb;
- PRMSL at mean sea level, PRES at the surface;
- LAND at the surface (the land-sea mask, used only for the fallback
  coastline).

With `--hart-bands`, HGT also at 900, 800, 750, 650, 600, 550, 450 and
350 mb (25 messages).

**NOMADS** (default): requests to
`https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl` with `var_`
and `lev_` flags and, for a region, the `subregion` box. The filter
takes the cross product of the variables and levels, so the variables
are grouped by their level sets and each group is one request (HGT on
its levels, UGRD and VGRD on theirs, PRES and LAND at the surface,
PRMSL), concatenated into one file; only surface orography comes along
unasked and is ignored. A natl file is about 7 MB, a global file with
Hart's levels about 18 MB. The box is the region plus 10
degrees on every side (natl: 110W to 30E, 5S to 90N; npac: 110E to
100W, 5S to 80N) so the 500 km window, the 300 to 500 km closed-low
ring and the half-disks of B are complete at the plotted edge; the
margin is cut off before plotting, before the npz is written and before
lows are reported. The subregion longitudes are sent as 0 to 360 with
the east edge allowed past 360 (natl is `leftlon=250&rightlon=390`),
which is how the filter accepts a box across the Greenwich meridian.

**AWS** (`https://noaa-gfs-bdp-pds.s3.amazonaws.com`, fallback or
`--source aws`): the `.idx` sidecar is read and each wanted message is
fetched with an HTTP byte-range GET on the global file (about 11 MB per
hour for the whole grid); the region box is cut out after decoding.
The two sources give identical products (checked at f006: every field
equal to within 2e-5 m).

The requests go through `requests`, which honors `HTTPS_PROXY` and
`REQUESTS_CA_BUNDLE`; TLS verification is never turned off.

## Dependencies

`requirements.txt` pins the versions that installed and worked here
(Python 3.11, Linux x86_64):

- `pygrib` 2.1.8 decodes the GRIB2 (its manylinux wheel bundles
  ecCodes; it pulls in `pyproj`);
- `cartopy` 0.26.0 draws the maps (pulls in `shapely` and `pyshp`). On
  first use it downloads the Natural Earth 1:50m coastline and land
  polygons from `naturalearth.s3.amazonaws.com` into
  `~/.local/share/cartopy`; this worked through the proxy here;
- `numpy`, `matplotlib`, `requests`.

The module itself needs only numpy. No scipy is needed: blob labeling is
a small flood fill in the script.

## Conventions

**Orientation.** GFS files come in two row orders: the global file (and
AWS) runs north to south with longitudes 0 to 359.75; the NOMADS
subregion output runs south to north with longitudes starting at the
box's west edge. `decode()` reads the latitudes and longitudes of the
file itself and reorders every field to rows increasing northward and
columns increasing eastward, with longitudes contiguous from the fetch
box's west edge (so npac runs 110 to 260 through the dateline and
global runs -180 to 179.75). The module is therefore run with
`hc.ORIENTATION_MODE = 0`, as the synthetic article scripts do (the OPC
CAVE build, whose rows run southward, uses 1). Checks on the 2026092406
f006 natl data:

- mode 0 on the south-to-north arrays and mode 1 on the same data
  flipped north to south give the same B to 4e-10 m;
- where the steering flow is westerly (u over 8 m/s) and thickness falls
  northward between 35N and 60N (10,905 points, warm air on the right of
  motion), B is positive at 98.5% of them with mode 0 (median 35.6 m)
  and at 1.8% with the wrong mode;
- the southern hemisphere polar front on a global frame is also
  positive, through the sign of the coriolis field;
- NOMADS (south to north) and AWS (north to south) inputs give the same
  products.

**Grid metrics.** `dx` per row is 0.25 x 111.32 km x cos(lat) in meters,
`dy` is 0.25 x 111.32 km, both as 2D pseudo-fields; coriolis is
2 omega sin(lat). A global grid is recognized by the module's own
`is_global_lon` (1440 columns x 27.83 km), so its windows wrap across the
seam; the regional boxes do not wrap, and the flood fill wraps only on
the global grid.

**Units.** Surface pressure and MSLP are passed in Pa as GFS gives them
(the module detects Pa from the field median); the npz and the table
carry MSLP in hPa. Heights are geopotential meters. HVTL, HVTU and HB
are meters; HCPSidx runs -3 to 3; HCPSclass is the 0 to 6 code.

**Constants.** radiusKm 500, bThresholdM 10, layerScale 1.4548,
depthHpa 5, blobKm 200, capHpa 900, pmslKind 0 (MSLP), scaleM 100 for
HCPSidx, as in the D2D XML definitions.

**Colormaps.** Read from `D2D/colormaps/Grid/*.cmap` with a parser
copied from `article/figures/feature_catalog.py` (copied, not imported,
so this tool does not load the article's synthetic grid on import),
with their alpha channels: CPS_CoreDiverging over plus or minus 300 m,
transparent near zero; CPS_Asymmetry over plus or minus 40 m,
transparent within 5 m; CPS_HartClass on -0.5 to 6.5.

## Caching

Downloads are kept under `out/cache/<cycle>/`:
`<region>_f<hhh>.nomads.grb2` for a NOMADS subregion, and
`global_f<hhh>.aws.grb2` for the AWS messages on the whole grid (which
serve any region). A rerun finds them and does no network traffic; the
products and figures are always recomputed (about 5 s a frame). Delete
the cache directory to refetch. `out/` is ignored by git.

## Storm-following phase diagrams (`--track`)

`--track NAME:LAT,LON[:FHR0[:FHR1]]` follows a low through the requested hours
and draws its Hart phase diagrams the way the Florida State University
cyclone phase pages draw them, so the two can be compared by eye. The
tracking and plotting live in `track_cps.py`, which reuses this
script's fetch, decode and compute functions; with `--track` no maps or
npz files are written.

    python3 gfs_cps.py --cycle 2026092412 --region global --hours $(seq 0 6 198) \
        --track EPAC:15.5,-155.5 --track GREENLAND:62,-20 --track LABRADOR:61.5,-63:0:96 --hart-bands

Use `--region global`: a track that leaves a regional box (plus its
margin) simply ends there. All tracks of a run share the frames, so
several lows cost no more than one. Downloads run ahead of the
computation in two threads.

**Tracker.** At FHR0 the center is the MSLP minimum nearest the seed
within 400 km. At every later frame the first guess is the last center
moved on by the last 6 h motion (the last center itself at the second
frame), and the search radius is 60 km/h times the hours since the last
fix, capped at 700 km (360 km at 6 h spacing). A candidate is a grid
point that is the lowest of its +/- 1 degree box (9 x 9 points); the
candidate nearest the first guess wins. A minimum of 1018 hPa or more
is not a candidate (FSU's tracker uses the same limit, and a filled low
otherwise hands over to any weak minimum nearby), nor is one where the
surface pressure is under 950 hPa (terrain above about 500 m, where
MSLP is extrapolated: the Greenland ice cap, Iceland's interior). A
terrain point is masked out before the box-minimum test itself, not
just dropped from the candidate list afterward, so an artificially deep
terrain reading cannot sit inside a genuine low's box and hide the
real, slightly shallower minimum beside it (a low crossing Iceland's
highlands otherwise loses its box-minimum status to the terrain point
next to it and the track ends). If
there is none, the track coasts one frame on the extrapolated motion (that frame is left out of
the table) and tries again with the larger radius; a second miss ends
it. An optional FHR1 in the spec (`NAME:LAT,LON:0:96`) stops the track
after that hour, for a low that is lost or replaced by another after it.
The center is refined to a fraction of a cell by a parabola through
the minimum and its neighbors along each axis.

**Sampling.** HVTL, HVTU, HB, HCPSidx and the Hart-band terms are
sampled bilinearly at the refined center (corners without a value are
dropped and the rest renormalized); HCPSclass is taken at the nearest
grid point (blank where the module found no closed low); `mslp_hpa` is
the grid-point minimum. The products are the full-grid ones, so the
values are exactly what the maps show there.

**Motion.** `motion_kt` and `heading_deg` (toward, clockwise from
north) are centered finite differences of the track positions over the
neighboring fixes (12 h), one-sided at the ends. `steering_heading_deg`
and `steering_kt` are the module's own motion proxy at the center: the
850/700/500/300 hPa mean wind (`steering`) averaged over the 500 km
window (`steering_window_mean`), as `executeB` uses it.

**B with the track motion.** `hb_track` is `parameter_b_grid` on the
same 925-700 hPa thickness (below-ground masked, times 1.4548) with
`u_s`, `v_s` a uniform field of the track motion, computed on a box of
+/- 1000 km around the center and sampled there. The same box with the
steering proxy reproduces the full-grid HB to 1e-6 m, which checks that
the box holds the whole window. With `--hart-bands`, `hb_hart` is the
same with Hart's own 900-600 hPa thickness and no rescaling. Unlike HB,
which is blank where the steering proxy is under 2 m/s
(`MIN_STEERING_MS`), these use any nonzero track motion, as FSU's B
uses its tracker's motion whatever the speed.

**Hart bands.** `hvtl_hart` and `hvtu_hart` are `executeBand7` over
900, 850, ..., 600 and 600, 550, ..., 300 hPa (the least-squares slope
of the window's height range against ln p, as for the standard bands),
on the same 0.25 degree grid and 500 km window.

Outputs in `out/<cycle>/`:

- `track_<NAME>.csv`: one row per fix, columns `fhr, valid, lat, lon,
  mslp_hpa, hvtl, hvtu, hb, idx, class, hvtl_hart, hvtu_hart, hb_track,
  motion_kt, heading_deg, steering_heading_deg`, then `steering_kt` and
  `hb_hart`; the Hart columns are blank without `--hart-bands`.
- `phase_<NAME>.png`, 2400 x 1000 px: (a) B against -V_T^L and (b)
  -V_T^U against -V_T^L on Hart's quadrants
  (`article/figures/diagram_style.py`) with the B = 10 m and zero
  lines; the 24 h running mean (centered, 5 frames, fewer at the track
  ends) of the standard terms as the main line with markers every 6 h
  colored by MSLP in FSU's steps (1015 black, 1010 purple, 1000 blue,
  990 cyan, 980 green, 970 yellow, 960 orange, 950 magenta; a step
  covers the pressures above the next deeper step), the analysis solid
  and the forecasts with an x, day of month at 00Z, A and Z at the
  ends; the raw 6-hourly series as a faint line; the 24 h mean of the
  Hart-band terms (with the track-motion B on (a)) dashed with open
  diamonds. Axes are at least -50 to 250 m by -10 to 30 m (FSU's zoom
  window) on (a) and -50 to 250 by -100 to 100 m on (b), widened to fit
  the data. (c) the raw time series of the three parameters (Hart
  bands dashed, track-motion B dotted) with the class strip along the
  top and the onset (B above 10 m, purple) and completion (-V_T^L
  below 0 after onset, red) hours of the smoothed series marked
  (solid: standard; dashed: Hart bands with track-motion B), which the
  title block also lists.

### Comparing with the FSU pages

The FSU GFS page for a cycle is
`http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/YYMMDDHH/` (plain
http). Its `alltrack.png` map shows every cyclone of the run with its
number (black: existing at the analysis; red: forms later in the
forecast); cyclone N's page is `N.html`, and the images to screenshot
are `N.phase1.zoom.png` (B against -V_T^L) and `N.phase2.zoom.png`
(-V_T^U against -V_T^L), with `N.track.png` for the track. Put
them next to `phase_<NAME>.png` and compare the shape of the path, the
quadrant it is in, the day labels and the colors. Expect these
differences:

- FSU draws the trajectory from the first analysis of the storm (days
  before the run for a long-lived cyclone), so its path starts earlier;
  compare from the circled current position C onward. A low FSU picked
  up only later in the forecast ("Future cyclone") starts at that hour.
- FSU uses the 0.5 degree GFS; this uses 0.25 degree. Minima,
  and the terms near a compact warm core, differ somewhat.
- FSU uses Hart's bands, 900-600 and 600-300 hPa every 50 hPa; the
  standard trace here uses 925-850-700 and 500-400-300 hPa. The dashed
  Hart-band trace is the one to compare. Where 900 hPa is below ground
  (Greenland, Labrador, high terrain) the bands are masked differently.
- FSU computes over a 500 km radius circle; the module's thermal wind
  terms use a square 500 km window (more area, corners farther out), so
  the height range, and hence $-V_T$, is larger in magnitude.
- FSU's B takes the motion from its tracker; the standard B here uses
  the module's steering proxy. `hb_track` (dotted, and on the dashed
  trace of (a)) uses the track's own motion, which is closer to FSU.
- The 24 h running mean is applied to both, but FSU's includes the
  frames before the run, so its first day differs.
- FSU's tracker needs MSLP under 1018 hPa and a 24 h lifetime; a weak or
  short-lived low may not be on its list.

### Example: 2026092412

    python3 gfs_cps.py --cycle 2026092412 --region global --hours $(seq 0 6 198) --hart-bands \
        --track EPAC:15.5,-155.5 --track GREENLAND:62,-20 --track LABRADOR:61.5,-63:0:96

takes about 6 minutes here (34 global frames at about 10 s of
computation each; the 18 MB NOMADS downloads run ahead and are hidden
behind it). The three lows and their FSU pages for the same run:

| Low | Our track | FSU cyclone |
|---|---|---|
| EPAC, tropical cyclone near 15N 156W | 0 to 198 h, 998 hPa to 963 hPa (84 h) to 977 hPa at 46.9N 160.9W | [#1](http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/26092412/1.html), existing cyclone, through +198 h |
| GREENLAND, 958 hPa low southwest of Iceland at 60.6N 22.75W | 0 to 114 h, ends when it fills (the next minimum is over 1018 hPa) | [#19](http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/26092412/19.html), existing cyclone, through +54 h |
| LABRADOR, cold-core low at 61.5N 63.1W | 0 to 96 h (after 96 h the nearest minimum is a different low south of Iceland) | [#48](http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/26092412/48.html), picked up as a "future cyclone" from +6 h, through +96 h |

The 0.25 degree GFS keeps GREENLAND as a closed minimum circling north
of Iceland well past FSU's +54 h end; after a missed frame at 84 h the
track resumes about 500 km west at 90 h on a weak minimum (1000 to 1010
hPa) that the module does not count as a closed low.

With the standard bands the EPAC storm reaches B = 10 m (24 h mean) at
+132 h, with Hart's bands and the track-motion B at +144 h; the lower
term stays warm (100 to 130 m) to the end, so there is no completion
within 198 h in either, as on FSU's diagram (B crosses 10 m near its
00Z 1 October label, about +156 h, and the lower term stays warm).

## Daily collection

`collect_daily.py` runs the storm tracking every day on the 12 UTC GFS
for the storms listed in `watch.json`, keeps the results in `data/`,
and matches each storm to its Florida State University cyclone of the
same run so the two sets of diagrams can be compared day by day.

    python3 collect_daily.py [--cycle YYYYMMDDHH] [--hours H [H ...]] [--data-dir DIR]
                             [--watch FILE] [--force] [--no-fsu]

| Option | Default | Meaning |
|---|---|---|
| `--cycle` | see below | GFS cycle to collect. |
| `--hours` | 0 to 198 step 6 | Forecast hours. |
| `--data-dir` | `realtime/data` | Collection root. |
| `--watch` | `realtime/watch.json` | Watch list. |
| `--force` | off | Recompute storms already collected for the cycle. |
| `--no-fsu` | off | Skip the FSU matching. |

**What runs, when.** The `CPS daily collection` workflow
(`.github/workflows/cps_daily.yml`) runs at 20:00 UTC every day: the
12 UTC GFS is complete on NOMADS by about 16:30 UTC and FSU's page for
the run is up by evening. Without `--cycle` the script takes today's
(UTC) 12 UTC run if its last hour (f198) is posted, otherwise the newest
12 UTC run that has it, probing back four days (NOMADS first, then the
AWS bucket). The workflow installs `requirements.txt`, runs the script,
and commits `data/` and `watch.json` to main as `cps-daily` with the
message `CPS daily collection <cycle>`; nothing is committed when
nothing changed, and a rejected push is rebased and retried. The GFS
work runs through `gfs_cps` and `track_cps` functions (global grid,
Hart's bands; about 6 minutes of computation for 34 frames plus the
downloads, about 600 MB from NOMADS). The tracking path draws no maps,
so cartopy never downloads its Natural Earth data there and nothing is
cached between runs.

**Where data lands.** `data/<cycle>/<NAME>/` holds `track.csv`,
`phase.png` (downscaled to 1600 px; it and `compare.png` are saved
with a 256-color palette to keep the repository small, about 0.8 MB
per storm and day with FSU's images), `meta.json` and, for a storm
matched to FSU, `fsu_phase1.png`, `fsu_phase2.png`, `fsu_track.png` and
`compare.png`; `data/<cycle>/summary.md` tabulates the run (FSU number,
start position and MSLP, class sequence, onset and completion by both
band sets) and `data/log.csv` gets one row per cycle and storm
(`cycle, storm, fsu_number, status`). `data/README.md` describes the
layout. The full-size outputs and the GRIB cache stay in `out/`, which
git ignores.

**Seeds.** Each `watch.json` entry has `name`, a seed `lat`, `lon`
(west negative), the `cycle` the seed is valid for, optional `fhr0`
(the hour of that cycle the seed is valid at, default 0) and `fhr1`
(the last hour to track, for a low known to be lost or replaced after
it), `notes` and `active`. For a new cycle the seed is:

1. the stored seed, if its cycle is this cycle (or its `fhr0` is still
   ahead of this cycle);
2. otherwise the position in the newest earlier collected `track.csv` of
   the storm at the forecast hour valid now (normally +24 h of
   yesterday's run);
3. otherwise the stored seed (for example after a missed day, or when
   yesterday's track ended before +24 h).

The tracker then looks for the MSLP minimum nearest the seed within
400 km, as with `--track`. After a successful run the entry's seed
becomes the track's first position of this cycle and its `cycle` this
cycle; `fhr1` counts down by the hours since its cycle and is dropped
(with a note) once it has passed. If there is no closed low within
400 km of the seed, the storm is marked `"active": false` with
`ended_cycle` and a note, and its folder gets only a `meta.json` with
status `lost`. A backfill of a cycle older than an entry's `cycle` does
not move the entry's seed; there the stored seed is used at the hour it
is valid in the older run (for example +24 h of the day before), unless
an earlier collected track covers that time.

**Adding a storm.** Add an entry to `watch.json` with a name (it
becomes the folder name), the low's position at the analysis time of a
12 UTC cycle, that cycle, and `"active": true`, and commit it to main;
the next daily run picks it up. For a low that forms later in the run,
give its position at `fhr0` of that cycle. To stop following a storm set
`active` to false. Example:

    {"name": "NATL1", "lat": 35.0, "lon": -60.0, "cycle": "2026092512", "fhr0": 0,
     "fhr1": null, "notes": "", "active": true}

**Backfilling a cycle.** Actions > CPS daily collection > Run workflow,
with `cycle` set to a 12 UTC cycle (YYYYMMDD12); NOMADS keeps about ten
days, older cycles come from the AWS bucket. `force` recomputes storms
already collected for that cycle. Locally:
`python3 collect_daily.py --cycle 2026092412`. A rerun for a collected
cycle does no GFS work for storms whose `meta.json` says `ok`, reuses the
FSU files already downloaded, and replaces rather than repeats its rows
in `log.csv`; it does retry the FSU match of a storm that has none (for
example when the FSU page was not up yet).

**FSU matching.** The FSU page of a GFS cycle is
`http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/YYMMDDHH/index.html`
(https is tried first, then plain http). Its `alltrack.png` is a plate
carree map (30E to 390E, 80S to 80N) with an HTML image map: one
16 px `<area>` square per cyclone, linking to `N.html`. `fsu_cyclones()`
turns the center of each square into a position with a fixed
calibration on the map's axis labels and ticks, set so that cyclone 1 of
26092412 lands at 15.2N 156.3W (about 0.35 degree longitude and 0.33
degree latitude per pixel); the colored frame of `alltrack.png` is
checked and the calibration rescaled if the frame has moved. Each of our
storms is matched to the nearest FSU cyclone within 400 km of our first
fix, whose `N.phase1.zoom.png`, `N.phase2.zoom.png` and `N.track.png` are
downloaded; `compare.png` puts FSU's two diagrams side by side (1024 px
each) above our `phase.png` scaled to 2048 px. The requests to FSU carry
a User-Agent naming this repository, are spaced at least one second
apart, and files already downloaded are reused (the index and map are
cached under `out/cache/<cycle>/fsu/`). Limits:

- An existing cyclone's square sits at its analysis position, a future
  cyclone's where FSU first finds it (LABRADOR of 2026092412 matches #48,
  first found at +6 h); a storm far from both, or one FSU does not
  track (MSLP 1018 hPa or more, under 24 h), gets no match.
- Two lows within 400 km of each other can be confused; the match takes
  the nearest square, and the pixel positions are good to about 40 km.
- If FSU changes the page (no `<area>` elements, or a different map),
  the match is skipped with a message; the run never fails for FSU, and
  a later rerun of the cycle retries it.
- The FSU page for a run appears in the evening; a run made before that
  (a backfill before 20 UTC, for instance) collects without FSU and
  picks it up on a rerun.
- FSU's diagrams remain theirs; they are kept only for comparison, and
  the differences listed in "Comparing with the FSU pages" above apply.

## Lows table

`lows_<region>.csv` has one row per connected blob (8-connected) of the
HCPSclass field, that is per closed low the module's MSLP detector
found and painted: the position of the MSLP minimum inside the blob,
and every product's value at that grid point.

    cycle,fhr,valid,lat,lon,mslp_hpa,hvtl,hvtu,hb,idx,class
    2026092406,6,2026-09-24T12:00Z,61.0,-22.75,958.6,68.0,-185.5,20.3,0.23,3

Longitudes are -180 to 180. Blobs whose minimum lies in the margin are
dropped. A rerun with other hours replaces the rows for those hours and
keeps the rest.

## Verification against the CAVE captures

The 2026092406 cycle at 6, 54, 78, 102 and 126 h over natl was compared
with the CAVE screen captures of the same frames. The captures carry a
sample readout at one point per frame; the values here, sampled
bilinearly at the same point, are:

| Frame, point | HVTL capture / here | HVTU capture / here | HB capture / here | class |
|---|---|---|---|---|
| 6 h, 33.58N 71.00W | 192.95 / 192.8 | -246.95 / -246.9 | 34.55 / 33.7 | 3 / 3 |
| 54 h, 40.00N 69.76W | 139.85 / 139.5 | -97.26 / -97.3 | 43.72 / 67.7 | 3 / 3 |
| 78 h, 41.02N 70.53W | 153.47 / 153.5 | -130.41 / -130.3 | 15.41 / 14.1 | 2.98 / 2.98 |
| 102 h, 40.22N 69.70W | 12.93 / 11.8 | -229.76 / -230.3 | 17.11 / 21.6 | 3 / 3 |
| 126 h, 42.58N 66.98W | -4.31 / -4.8 | -226.82 / -226.9 | 23.16 / 25.7 | 3.6 / 3.7 |

The thermal wind terms agree to about 1 m. HB differs where a storm's
own thickness dipole is inside the window, because the captures were
made with the former first-order B (the window-mean gradient), which
reads a dipole at about 55 to 60% of the semicircle difference the
module now computes. The class blocks match the captures low for low,
except for lows near the 5 hPa detection depth, which differ because the
captures used the 1000 hPa height detector and this uses MSLP.

## Known limits

- GFS posts about 3.5 to 5 hours after the cycle time, and the late
  forecast hours last; the default cycle is the newest with f006, so
  its later hours can still be missing (they are skipped). NOMADS keeps
  about 10 days; older cycles come from AWS.
- The 10 degree margin makes the products complete to the region edge,
  but the outermost margin itself is not; `--region global` has no edge
  but, like the D2D grids, near-pole rows have very wide windows.
- The npac and natl maps are Lambert conformal clipped to the lat/lon
  box, global is plate carree. With `--plain` (or without cartopy) the
  maps are plain lon/lat axes, the coastline is the 0.5 contour of the
  GFS land-sea mask fetched with the data, and the wind vectors are
  drawn in lon/lat space.
- A 404 from a source is not retried (the file is not there); other
  errors are retried 3 times.
- Only the CPS products are drawn; the captures' 1000-500 hPa thickness
  and surface wind overlays are not.
