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
moved on by the last motion over the hours since it (the last center
itself at the second frame; after a coasted frame, half that
extrapolation, so a wrong motion does not carry the search away), and
the search radius around the guess is 90 km/h times the hours since the
last fix, capped at 600 km (540 km at 6 h spacing). A candidate is a grid
point that is the lowest of its +/- 1 degree box (9 x 9 points); the
candidate nearest the first guess wins. (`find_center` also has a
move-to-deeper-center step: if a candidate more than 0.6 hPa deeper, the
mask's center tolerance, lies within `CLIMB_KM` of the chosen one, the
fix moves to the deepest such candidate, repeatedly, still within the
reach limit below. It is off by default, `CLIMB_KM = 0`; set it to
`hc.MIN_RADIUS_KM`, 300 km, to turn it on. In testing on 2026092418 it
moved GREENLAND at +60 h from its own minimum onto LABRADOR's center
290 km away, so the merge rule stopped LABRADOR at +54 h and the
LABRADOR low that FSU follows to +96 h was no longer tracked. The fix
below for the closed-low check (`closed_at`) reaches the same deeper
center without moving the tracked position, so it does not have this
merge problem; `CLIMB_KM` is kept, off, only as the earlier, rejected
attempt.)
Not a candidate:

- a minimum of 1018 hPa or more (FSU's tracker uses the same limit);
- one farther from the last fix than 90 km/h times the hours since it
  (540 km for one 6 h step, 1080 km after a coasted frame; no cap):
  with the guess extrapolated, a search radius alone would let each
  jump lengthen the next;
- one more than 12 hPa above the previous fix (`MAX_RISE_HPA`): a
  filling low does not rise 12 hPa in 6 h, a handover to a different,
  weaker low does;
- one poleward of 85 degrees (`POLE_LAT`): the pole row of the grid is
  one value repeated, so it passes the box test and a track that
  reaches it spins in longitude;
- one where the surface pressure is under 950 hPa (terrain above about
  500 m, where MSLP is extrapolated: the Greenland ice cap, Iceland's
  interior). A terrain point is masked out before the box-minimum test
  itself, not just dropped from the candidate list afterward, so an
  artificially deep terrain reading cannot sit inside a genuine low's
  box and hide the real, slightly shallower minimum beside it (a low
  crossing Iceland's highlands otherwise loses its box-minimum status
  to the terrain point next to it and the track ends).

A track ends in four ways:

1. *No candidate.* The track coasts one frame on the extrapolated
   motion (that frame is left out of the table) and tries again with
   the larger radius; a second miss ends it.
2. *Outside a closed low.* Each fix is checked against the module's own
   closed-low definition, `closed_low_mask` on MSLP, computed once per
   frame, with the arguments `executeHartClass` gives it (300 km
   candidate radius, 500 km ring, 200 km blob) except a 2 hPa ring depth
   (`CLOSED_DEPTH_HPA`) instead of the product's 5 hPa, which a broad
   deep low whose ring is not 5 hPa above its center fails. The mask is
   used rather than a blank HCPSclass because the class is also blank
   where HB is (steering under 2 m/s) or below ground, inside a
   perfectly good low. The mask's own candidate test requires a point to
   be within 0.6 hPa of the lowest MSLP anywhere in its own +/- 300 km
   box, so a secondary minimum whose box reaches onto the flank of a
   deeper center 300 to 350 km away fails the test right at that point
   even though the system as a whole is a closed low (`GREENLAND` beside
   Iceland at +24 h of 2026092412, 320 km from the low's own 970 hPa
   center: see the example below). `closed_at` therefore checks the mask
   not at the fix but at the deepest MSLP within `CLOSED_SEARCH_KM`
   (300 km, the mask's own candidate radius) of it: the search reaches
   most of the way to a genuinely deeper center in the same system and
   lands inside its mask blob, while an isolated low (the ordinary case,
   nothing deeper nearby) has the fix itself as the deepest point in
   range, so the test is unchanged. The tracked position itself never
   moves, so, unlike `CLIMB_KM` above, this cannot feed the merge rule
   below. After two consecutive fixes outside the mask (`OUTSIDE_FRAMES`;
   a coasted frame between them does not reset the count), the track
   ends at its last fix inside one, which stops a filled low from
   wandering from one weak minimum to the next. A single fix outside is
   kept.
3. *Same low as another track.* When two tracks of a run choose centers
   within 150 km of each other in a frame (`MERGE_TRACK_KM`), the one
   whose track started later (for the same start, the shallower at that
   frame; then the later in the list) stops at its previous fix and the
   other continues. `collect_daily.py` notes "merged into <name> at
   +<fhr> h" in the stopped storm's `meta.json` and logs it as `merged`.
4. *FHR1.* An optional FHR1 in the spec (`NAME:LAT,LON:0:96`) stops the
   track after that hour, for a low that is lost or replaced by another
   after it.

These apply to every track, from `--track` or from `watch.json`, picked
by hand or found automatically. The center is refined to a fraction of
a cell by a parabola through the minimum and its neighbors along each
axis.

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
| GREENLAND, 958 hPa low southwest of Iceland at 60.6N 22.75W | 0 to 18 h (970 hPa at 64.4N 15.5W, off east Iceland) | [#19](http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/26092412/19.html), existing cyclone, through +54 h |
| LABRADOR, cold-core low at 61.5N 63.1W | 0 to 96 h (its FHR1), deepest 985 hPa (66 h), 996 hPa at 63.9N 15.8W | [#48](http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/26092412/48.html), picked up as a "future cyclone" from +6 h, through +96 h |

Rerun from the GRIB cache with the tracker rules above. Before the
`closed_at` fix, GREENLAND ended well before FSU's +54 h because the
tracker stayed on a secondary minimum: at +24 h the candidate nearest
its first guess is 64.4N 15.6W (975 hPa, beside Iceland), while the
low's deeper center is north of Iceland at 67.25N 15.75W (970 hPa),
320 km away. The closed-low mask's own candidate test compares a center
with every grid point in its own +/- 300 km box, which reaches onto the
flank of that deeper center, so the +24 h and +30 h minima were outside
the mask at any ring depth and the track ended at +18 h. The
move-to-deeper-center step described above would keep it on the 970 hPa
center too, but by moving the fix there, not just the closedness check.

**Rerun after the fix.** Checking the mask at the deepest MSLP within
300 km of the fix (`closed_at`) reaches the 970 hPa center instead,
inside its own mask blob, without moving the fix; the +24 h and +30 h
fixes now count as inside a closed low and the track continues. Both
cycles were rerun from the GRIB cache with `collect_daily.py --force`
(`watch.json`'s own seeds, close to but not identical to the ones
above):

| Cycle | Storm | Before | After | End reason after |
|---|---|---|---|---|
| 2026092412 | EPAC | 0-198 h | +6-198 h | ran out of requested hours (unaffected; +6 not +0 because `watch.json`'s stored seed has since moved to the 2026092418 cycle, and a backfill of an older cycle uses the seed at the hour it is valid there -- see "Backfilling a cycle" below, unrelated to this fix) |
| 2026092412 | GREENLAND | 0-18 h | +6-174 h | no candidate within reach near the 85 deg pole limit, after wandering east across the Arctic at a fairly steady 977-992 hPa |
| 2026092412 | LABRADOR | 0-96 h | +6-96 h | its own FHR1 (unaffected) |
| 2026092418 | EPAC | 0-198 h | 0-198 h | ran out of requested hours (unaffected) |
| 2026092418 | GREENLAND | 0-54 h | 0-84 h | outside a closed low at +90, +96 h -- matches FSU cyclone 17's own ending at +84 h |
| 2026092418 | LABRADOR | 0-90 h | 0-66 h | merged into GREENLAND at +72 h (see below) |
| 2026092418 | AUTO_260924_02 | 0-6 h | 0-90 h | no candidate within reach of a filling low |
| 2026092418 | AUTO_260924_03 | 0-90 h | 0-30 h | merged into AUTO_260924_02 at +36 h (see below) |

EPAC and LABRADOR are unaffected at 2026092412 (LABRADOR still stops
exactly at its own FHR1); at 2026092418, EPAC is unaffected but
LABRADOR now stops earlier, merged into GREENLAND. GREENLAND was dead
by +54 h before the fix, so it never competed for this merge; with it
alive, the two tracks' own independently found centers land within
150 km of each other (`MERGE_TRACK_KM`) at +72 h, and the existing merge
rule (unchanged by this fix) keeps the older entry, GREENLAND, and stops
LABRADOR there. The raw MSLP field at +72 h, 55-75N 30W-5E, has one
minimum (986.8 hPa near 68N 4-11W), not two: GREENLAND's warm seclusion
and LABRADOR's cold-core low have genuinely merged into one low in this
forecast by then, so tracking them as two separate storms past that
point would be wrong, not merely a tracker quirk. It is also the same
"hands over to another low" outcome LABRADOR's FHR1 = 90 was already
chosen to preempt (previously expected near +96 h from crossing
Iceland's terrain, per `watch.json`'s own note on the entry); with
GREENLAND's early end fixed, the handover happens 24 h sooner because
GREENLAND is no longer missing from contention, not because of a new
defect. AUTO_260924_03 stopping when AUTO_260924_02 (previously dead by
+6 h) catches up to it at +36 h is the same effect between two
automatically discovered lows. Every fix in both reruns stayed within
the tracker's own reach limit, and no track's MSLP or position changed
by more than 12 hPa or 540 km between consecutive fixes anywhere in
either rerun (the largest were GREENLAND's 533 km step and 9.6 hPa step,
both at 2026092412, both under the limits) -- neither rerun shows a
track running away onto an unrelated low.

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
downloads, about 600 MB from NOMADS). Each frame is fetched, decoded and
run through the module, Hart's bands and the closed-low mask once (about
10 s of the 11 s a frame takes), and every storm samples those shared fields (about 0.02 s
per storm and frame); per storm there is then B with the track motion
and the diagram (about 1 s) and four FSU requests spaced a second apart,
so ten storms cost well under a minute more than one. The tracking path draws no maps,
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

**Automatic discovery.** Besides the hand-picked storms, every run adds
the deep lows of its analysis on its own (constants at the top of
`collect_daily.py`):

- *Rule.* On the 0 h frame (global grid, fields computed once for all
  storms), every point the tracker would accept as a center
  (`track_cps.all_centers`, the rule of `find_center`: the lowest point
  of its +/- 1 degree box after terrain with surface pressure below
  950 hPa is masked, MSLP under 1018 hPa, within 85 degrees of the
  equator) with MSLP below
  `AUTO_MSLP_HPA` (980 hPa) and latitude north of `AUTO_LAT_MIN` (0,
  so the northern hemisphere only) is a candidate. Deepest first, a
  candidate within 500 km of a deeper one kept is dropped (one per
  system). A low within 500 km of the 0 h position of a storm already in
  `watch.json`, active or made inactive in this cycle, is skipped, so a
  hand-picked storm is not duplicated and a storm just lost or merged is
  not re-added at the same spot.
- *Naming.* Each remaining low becomes an active entry
  `AUTO_<YYMMDD>_<NN>` (the cycle's date, `NN` a two-digit serial per
  day, deepest first), seeded at its 0 h position of the cycle with
  `fhr0` 0 and a note giving the 0 h MSLP and a basin word: `NATL`
  north of 20N between 100W and 20E, `NPAC` north of 20N west of 100W or
  east of 100E, `TROP` south of 20N, otherwise the position. It is
  tracked in the same run like any other storm and followed on later
  days the same way. Its `meta.json` has a `discovered` block.
- *Cap.* At most `AUTO_MAX_PER_DAY` (6) AUTO storms per day, deepest
  first (the ones already named for that day count), so a bad analysis
  cannot flood the record; lows left out by the cap are listed.
- *Record.* `data/<cycle>/discovery.json` lists every candidate with
  its result (`added`, `known` with the storm it is near, `cap`), and
  `summary.md` shows it as a table. A rerun of the cycle without
  `--force` does not repeat the discovery; with `--force` it does, adds
  nothing twice (the storms it added before now cover their lows) and
  keeps them listed as added.
- *Merging.* If two active storms are within 300 km of each other at
  0 h of a cycle (`MERGE_KM`), the older entry (earlier in `watch.json`)
  is kept and the newer is marked inactive with the note `merged into
  <name>`; its folder gets only a `meta.json` with status `merged`.
- *Ending.* A storm whose track is lost is marked inactive, as before.
  An AUTO storm whose 0 h MSLP is above 1000 hPa (`FILL_HPA`) in two
  consecutive collected cycles (`FILL_CYCLES`, this one and its newest
  earlier `meta.json`) is marked inactive with the note `filled`; that
  cycle's diagrams are still kept. Hand-picked storms (no `AUTO_`
  prefix) are never ended by this rule.
- *Stopping by hand.* To stop following an AUTO storm (or any other),
  set its `active` to false in `watch.json` and keep the entry: it holds
  the day's serial, and as long as the storm's last collected track
  reaches the time of a new cycle, a low within 500 km of where that
  track puts it is not added again (a storm set inactive by hand has no
  `ended_cycle`). Once that track has run out, a low still deeper than
  980 hPa there is found again under a new name.

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

## Live web map data

`export_web.py` turns one GFS cycle into files a static web page can
load directly: the live global map in `cyclone_phase_space/article/live/`
reads them from the `cps-live` branch.

    python3 export_web.py [--cycle YYYYMMDDHH] [--hours H [H ...]] [--out DIR] [--cache DIR] [--workers N]

| Option | Default | Meaning |
|---|---|---|
| `--cycle` | see below | GFS cycle to export. |
| `--hours` | 0 to 198 step 6 | Forecast hours; one that cannot be fetched is skipped. |
| `--out` | `realtime/out/web/<cycle>/` | Output directory (`index.json` and the rest go straight into it). |
| `--cache` | `realtime/out/cache/<cycle>/` | GRIB cache, shared with the other scripts. |
| `--workers` | 3 (fewer on smaller machines) | Frames computed in parallel, one process each (about 1 GB each). |

`--relink DIR` skips the fetch, decode and compute step entirely: it
reads `DIR/index.json` for the cycle and the hours and valid times
already exported, re-links `DIR/frames/*/lows.geojson` into tracks
(below), rebuilds `storms` from them and the daily collection, and
rewrites `index.json` and the frames' `"track"` properties in place,
without downloading anything. Use it after a tracker constant changes,
or to pick up a collection storm added after the frames were exported.

Without `--cycle` the script takes the newest cycle whose f198 index is
posted (NOMADS, else the AWS bucket), stepping back 6 h at a time for up
to two days, so a run made before the newest cycle is complete falls
back to the one before it. Every frame is fetched, decoded and run
through the module once on the global grid, through `gfs_cps`
(`get_grib`, `decode`, `compute_products`: executeHartClass, the two
executeBand3 calls, executeB and executeIndexStd, with the operational
constants), and the blobs are labeled with `gfs_cps.label_blobs`. The
GeoJSON and PNG work adds about 1.5 s per frame. The whole run for 34
frames from the cache takes about 2 min 15 s here with 3 workers (about
10 s per frame, 3.2 GB of memory at the peak; about 6 min with one
worker). One cycle's output is about 34 MB (about 1 MB per frame).

**Tracks.** Every closed low of a frame, the center of an HCPSclass
blob that is not flagged as a terrain artifact, is linked to the
closest such center of the next frame within 600 km per 6 h elapsed,
predicting each position first from half the low's last motion so a
fast mover is not missed; a low absent from one frame is bridged, with
the reach scaled to the elapsed time, but absent from two frames in a
row ends the track, and a low that reappears later starts a new one. A
track is kept once its low has stayed closed for 24 h (five frames).
The kept tracks are listed deepest first (lowest MSLP reached) as
`T01`, `T02`, ..., named `L01`, `L02`, ... unless a storm of the day's
collection shares at least two of the same valid hours, and at least
half of the hours both cover, within 300 km of the track, in which
case the track takes that storm's name, FSU number and phase and
compare diagrams instead. Collection storms that no track matches
follow as `C01`, `C02`, .... Every center feature of `lows.geojson`
that ends up on a track carries a `"track"` property naming it, so the
page can join a map mark to the matching `storms[].points` entry
without guessing.

**Files.** In the output directory:

- `index.json`:

      {"cycle": "2026092418", "model": "GFS 0.25", "generated": "2026-09-25T15:10:41Z",
       "hours": [0, 6, ...], "valid": ["2026-09-24T18:00:00Z", ...],
       "layers": {"class": true, "mslp": true, "hb": true, "hvtl": true, "hvtu": true},
       "raster": {"bounds": [[-85, -180], [85, 180]], "crs": "EPSG:3857", "width": 2048, "height": 2041},
       "ranges": {"hb": [-40, 40], "hvtl": [-300, 300], "hvtu": [-300, 300]},
       "frames": "frames/f{hhh}/", "storms_cycle": "2026092418", "storms": [...]}

  `hours` and `valid` list the frames actually written, in step;
  `frames` is a template (`{hhh}` is the hour in three digits).
  `storms` lists the run's cyclones, deepest first: the tracks built
  from the frames themselves (see **Tracks** above) come first, each
  `{"id": "T01", "name", "source": "track", "fsu": FSU number or null,
  "min_mslp", "points": [{"fhr", "valid", "id", "lat", "lon", "mslp",
  "cls", "hvtl", "hvtu", "hb", "idx"}, ...], "cls_seq", "phase_png",
  "compare_png"}` (a point's `id` is the matching center's `id` in that
  frame's `lows.geojson`); then whichever storms of the day's
  collection no track matched, `{"id": "C01", "source": "collection",
  "min_mslp", "name", "cycle", "fsu", "points": [{"fhr", "valid",
  "lat", "lon", "mslp", "cls", "hvtl", "hvtu", "hb"}, ...], "cls_seq",
  "phase_png", "compare_png"}`, the points from that storm's
  `track.csv` (`cls` an int or null where the class is blank; `hvtl`,
  `hvtu`, `hb` to one decimal, null where blank). `storms_cycle` names
  the `data/<cycle>/` folder the collection storms with status `ok`
  came from, the newest on the exported cycle's day, else the newest
  folder; a collection storm repeats it as its own `cycle`, since its
  forecast hours count from that run (a track has no `cycle`: its
  hours are this export's). `cls_seq` is the same `cls` values pulled
  out in point order, for a quick look at a storm's full life cycle
  without walking `points`. The two images are paths relative to
  `index.json`'s own directory, `../storms/<cycle>/<name>/phase.png`
  and `.../compare.png` (`compare_png` null when there is none, and
  both null for a track with no matching name); see **Assets layout**
  below for what has to sit next to them.
- `legend.json`: `{"classes": [{"code", "name", "hex"}, ...],
  "class_full": [...], "stops": {"hb": [[value, "#rrggbb", alpha], ...],
  "hvtl": ..., "hvtu": ...}, "ranges": {...}, "units": {...},
  "labels": {...}}`; the stops sample each colormap at 16 evenly spaced
  values across its range. `class_full` gives the seven classes' full
  names (code order, matching `classes`), spelled out as the class
  table does, e.g. "symmetric deep warm core", where `classes[].name`
  gives the short form, e.g. "sym deep warm".
- `history.json`: `{"latest": cycle, "cycles": [{"cycle", "generated",
  "index"}, ...]}`, newest first, the cycles exported into this
  directory (`index` relative to it). With the default `--out`,
  `out/web/history.json` lists every cycle under `out/web/` as well.
- `frames/fHHH/lows.geojson`: a FeatureCollection. For each closed low,
  that is each 8-connected blob of HCPSclass, numbered by depth (`id` 1
  is the deepest of the frame): the blob's outline as a Polygon (or
  MultiPolygon) feature with `{"kind": "blob", "cls", "id"}`, and a
  Point at the MSLP minimum inside the blob with `{"kind": "center",
  "id", "lat", "lon", "mslp", "hvtl", "hvtu", "hb", "idx", "cls",
  "name", "psfc", "terrain", "radius_km"}` (hPa and m to one decimal, a
  product null where it is blank; `cls` is the class at the minimum,
  `name` its short name). `psfc` is the surface pressure at that same
  point (hPa, one decimal); `terrain` is true when it is under 925 hPa
  (roughly 770 m), flagging a center that is likely a spurious
  extrapolated-MSLP artifact over high ground rather than a real low.
  This is a display default for the page, not a rule the product
  itself applies: 925 hPa trips over the Iranian and Mexican plateaus,
  Mongolia and the Andes foothills, but not the Great Plains.
  `radius_km` is the dilation radius (200) the low-finder used to
  build the blob, so a page can draw a halo of that size around a
  center without a lookup elsewhere. The outline is the 0.5 filled
  contour of the blob's own mask (contourpy), simplified with a 0.25
  degree tolerance; a blob across the dateline
  is cut at 180 into two features with the same `id`. Rings follow
  RFC 7946 (exterior counterclockwise). Once tracks are linked, a
  center that ends up on one also gets `"track"`, that track's `id`
  in `storms` (see **Tracks** above); a center whose low was dropped
  (too short-lived, or over terrain) has no `"track"` property.
- `frames/fHHH/mslp.geojson`: isobars every 4 hPa as LineString
  features with `{"level": hPa}`, from contourpy on the global field
  (the first column repeated at 180 so lines reach the dateline and end
  there), simplified with a 0.15 degree tolerance. Closed rings less
  than 1 degree across centered where the surface pressure is below
  950 hPa are dropped: over high terrain the extrapolated MSLP breaks
  into many such rings. A file over 400 KB is redone with the
  tolerance raised in 0.05 degree steps (none of the 34 frames of
  2026092418 needed it; they are 300 to 350 KB).
- `frames/fHHH/hb.png`, `hvtl.png`, `hvtu.png`: the field through its
  colormap (`CPS_Asymmetry`, -40 to 40 m; `CPS_CoreDiverging`, -300 to
  300 m), with the colormap's own alpha, so values near zero are
  transparent, and blanks (below ground, no steering flow) fully
  transparent. `class.png`: HCPSclass in the `CPS_HartClass` colors,
  transparent outside the blobs. Each is a 2048 by 2041 px indexed PNG
  (the 64 colormap entries plus one transparent entry, about 200 to
  260 KB) in Web Mercator (EPSG:3857) covering lon -180 to 180 and
  lat -85 to 85: rows are evenly spaced in y = ln(tan(pi/4 + lat/2)),
  and every pixel takes the nearest grid point, so the image goes on
  the map as a plain image overlay on those bounds.

Longitudes are -180 to 180 and coordinates are rounded to 2 decimals
throughout.

**Assets layout.** `export_web.py` itself only ever writes the
`index.json`/`legend.json`/`history.json`/`frames/` tree above; it
does not write or copy any storm assets. Where it is published,
`data/latest/` holds that tree (so `index.json` lands at
`data/latest/index.json`) and, one level up from it,
`data/storms/<cycle>/<name>/` holds that storm's `phase.png`,
`compare.png`, `meta.json` and `track.csv`, copied there from this
repo's own `data/<cycle>/<name>/` by whatever publishes the run. The
`phase_png`/`compare_png` paths in `index.json` are relative to
`data/latest/` on that assumption, so `../storms/<cycle>/<name>/
phase.png` resolves to `data/storms/<cycle>/<name>/phase.png`. A local
run for testing needs that same `storms/` sibling directory next to
its output directory, populated by hand from this repo's `data/`, for
the relative links to resolve.

**Schedule and branch.** The `CPS live map data` workflow
(`.github/workflows/cps_live.yml`) runs at 03:40, 09:40, 15:40 and
21:40 UTC, about 3 h 40 min after each cycle, when the 0.25 degree
f198 is usually posted; if it is not yet, the script falls back to the
previous cycle. It installs `requirements.txt` (with the pip cache),
runs `export_web.py` into a temporary directory, and publishes the
result as the single commit of the orphan branch `cps-live`, under
`latest/` (`index.json`, `legend.json`, `history.json`, `frames/`),
committed as `cps-live` with the message `CPS live data <cycle>` and
force-pushed. The branch is built from nothing in a fresh work tree
each time, so it never carries more than one cycle (about 34 MB) and
never grows a history, and main is never touched: committing a few
hundred binary files four times a day to main would bloat every
clone. Nothing else runs on that push: the Pages workflow builds only
on pushes to main, and the branch holds no workflows. The page fetches

    https://raw.githubusercontent.com/jkrek17/awips-tools/cps-live/latest/index.json

and the frame files relative to it; raw.githubusercontent.com answers
with `Access-Control-Allow-Origin: *` and `Cache-Control: max-age=300`,
so a new cycle reaches viewers within about five minutes of the push.

**Re-running or backfilling.** Actions > CPS live map data > Run
workflow, with a cycle (YYYYMMDDHH) to publish that run instead of the
newest; blank takes the newest complete cycle. The branch then holds
that cycle until the next scheduled run replaces it. NOMADS keeps about
10 days; older cycles come from the AWS bucket. Locally,
`python3 export_web.py --cycle YYYYMMDDHH --out DIR` writes the same
tree to `DIR`, which a local copy of the page can be pointed at.

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

## A second model: ECMWF open data (`ecmwf_cps.py`)

`ecmwf_cps.py` makes the same four-panel figures, npz and lows table
from ECMWF's open-data IFS forecasts at 0.25 degree
(`https://data.ecmwf.int/forecasts/`), for the same 00 and 12 UTC
cycles GFS runs at. It takes the same four options as `gfs_cps.py`:
`--cycle`, `--hours`, `--region`, `--out` (default `realtime/out/ecmwf`,
so frames land in `out/ecmwf/<cycle>/`), and reuses `gfs_cps.py`'s
`compute_products`, `find_lows`, `region_slices`, `write_lows`,
`make_cmaps`, `draw_panels`, `plot_frame` and the rest of the plotting
code by import, unchanged; only the fetch and decode are its own,
because ECMWF's open data has no NOMADS-style filter endpoint and a
different index format. Titles say "ECMWF IFS 0.25" in place of "GFS
0.25 deg".

    python3 ecmwf_cps.py --cycle 2026092500 --hours 0 6 12 --region natl

No new Python package was needed: fetching goes through direct HTTPS
byte-range GETs against the `.index` sidecars ECMWF publishes next to
every GRIB2 file (the `ecmwf-opendata` client was the other option
named for this work, but it does not do anything the existing
`requests`-based byte-range approach in `gfs_cps.py`'s AWS path does
not already do), and decoding reuses `pygrib`, already a dependency.
`requirements.txt` is unchanged.

**Field availability**, checked with real requests against the
2026092500 cycle (both the fields in doubt, 400 hPa and surface
pressure, were checked explicitly and are present):

- geopotential height, ECMWF's `gh` parameter, already in geopotential
  meters (no conversion from geopotential needed, unlike a model that
  only carries `z`, which ECMWF also carries alongside `gh`), is posted
  at all six of 925, 850, 700, 500, 400 and 300 hPa, at every 6 h step
  from 0 to at least 144 h (checked at every step; ECMWF also posts 3 h
  steps to 144 h and 6 h steps beyond it, out to 240 h at 0.25 degree);
- u/v wind (`u`, `v`) is posted at 850, 700, 500 and 300 hPa over the
  same steps;
- mean sea level pressure (`msl`) is posted at every step;
- surface pressure (`sp`) is posted at every step checked (f000 and
  f144, and every 6 h between); no substitute was needed.

**Substitution kept in the code, not triggered by this run.** Because
ECMWF's product list for a future cycle is not a fixed guarantee the
way the GFS pgrb2 file's contents are, `ecmwf_cps.py` still degrades
explicitly if `sp` is ever absent from an hour's `.index`: `psfc`
becomes a constant 1013 hPa field for that hour instead of a decoded
message, which only widens the below-ground mask to the model's own
missing values rather than PRES's terrain mask (a constant field has
no terrain to mask against). The frame's title and the montage's
suptitle say "sp not posted: below-ground mask uses a constant 1013
hPa" when this happens; the console output marks the hour
`[no sp: psfc=1013 hPa constant]`. This did not happen in the run
below or in any of the steps checked above.

**Grid order and longitude convention.** ECMWF's own grid is latitude
descending (90 to -90) with longitude -180 to 179.75, unlike GFS's AWS
file (latitude descending, longitude 0 to 359.75) or NOMADS subregion
output (latitude ascending from the box's west edge). `decode()`
reorders it the same way `gfs_cps.decode()` reorders GFS files, to
rows increasing northward and columns increasing eastward from the
fetch box's west edge, reusing `gfs_cps.fetch_box()` unchanged, so a
region crossing the dateline or the Greenwich meridian works the same
way. Checked on the 2026092500 f000 natl-plus-margin box, the same
polar-front B sign check the GFS README runs: of the 14,215 points
between 35N and 60N with 850 hPa wind over 8 m/s and 925-700 hPa
thickness falling northward (warm air to the south), B is positive at
99.9% of them (median 39.1 m), against 98.5% (median 35.6 m) for GFS.

**Run.** `2026092500`, the latest 00 or 12 UTC cycle with an f006
index at the time this was run (2026-09-25, about 15:00 UTC; the
12 UTC run of the same day was not yet posted), hours 0, 6, 12,
region `natl`, cartopy maps, from an empty cache: 112.8 s total (about
25-30 s per frame for the 17 byte-range GETs and pygrib decode, one
request per message as with `gfs_cps.py`'s AWS path, plus about 1 s to
compute and 4-13 s to plot). The lows table at f006:

    cycle,fhr,valid,lat,lon,mslp_hpa,hvtl,hvtu,hb,idx,class
    2026092500,6,2026-09-25T06:00Z,65.75,-16.0,967.6,139.0,-78.4,15.2,1.11,3
    2026092500,6,2026-09-25T06:00Z,57.5,-45.5,993.8,-167.3,-249.8,40.5,-2.85,4
    2026092500,6,2026-09-25T06:00Z,36.0,-70.75,999.6,220.5,-143.8,37.5,1.06,3
    2026092500,6,2026-09-25T06:00Z,14.5,-21.75,1003.7,48.5,-39.7,-4.1,0.52,1
    2026092500,6,2026-09-25T06:00Z,39.5,-60.0,1010.2,130.7,-157.0,29.5,0.81,3
    2026092500,6,2026-09-25T06:00Z,29.5,-42.25,1014.3,47.5,18.3,9.8,1.07,0
    2026092500,6,2026-09-25T06:00Z,42.5,7.0,1014.3,-170.4,-149.8,43.1,-2.78,4
    2026092500,6,2026-09-25T06:00Z,41.75,18.25,1014.5,-106.3,-261.9,57.4,-2.56,4
    2026092500,6,2026-09-25T06:00Z,31.25,-41.75,1016.7,61.0,-33.8,14.4,0.76,3
    2026092500,6,2026-09-25T06:00Z,43.0,19.75,1019.3,-21.0,-240.2,46.6,-1.4,4

The f006 figure was read and checked by eye: the class blobs' central
pressures (968, 994, 1014, 1019 mb near Iceland/Scandinavia; 1000,
1010 mb near Newfoundland; 1017/1014, 1004 mb in the tropics) match the
lows table, coastlines and MSLP contours are in the right places, the
HB panel is warm (purple) through most of the midlatitudes with a
cold-core (teal) center over the low near Iceland, and the HVTL/HVTU
panels' 850 hPa barbs and 300 hPa arrows both point the right way for
that low's cyclonic circulation.

**Known differences from `gfs_cps.py`.** No NOMADS-style region filter
exists for ECMWF open data, so every forecast hour downloads the whole
0.25 degree grid's wanted messages (17 byte-range GETs, like
`gfs_cps.py`'s AWS path) regardless of `--region`; the cache is
therefore keyed only by forecast hour (`out/ecmwf/cache/<cycle>/
global_f<hhh>.ecmwf.grb2`), not by region, and a natl run and a global
run of the same cycle and hour share one download. `--source`,
`--plain`, `--track` and `--hart-bands` are not implemented (ECMWF's
own file does not carry Hart's 50 hPa levels; adding them would need
fetching `gh` at ECMWF's own 900, 800, 750, 650, 600, 550 and 450 hPa
levels, which are posted, the same way).
