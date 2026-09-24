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

**NOMADS** (default): one request to
`https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl` with `var_`
and `lev_` flags and, for a region, the `subregion` box. The filter
takes the cross product of the variables and levels, so a few unneeded
messages (UGRD 925 and 400 mb, surface orography) come along and are
ignored; a natl file is about 7 MB. The box is the region plus 10
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
