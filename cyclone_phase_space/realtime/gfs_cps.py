#!/usr/bin/env python3
"""Hart cyclone phase space four-panel images from public GFS 0.25 degree data.

Proof of concept: fetches only the GRIB2 messages the operational D2D
module needs (NOMADS grib filter, or byte ranges from the NOAA AWS
bucket), runs them through the unchanged operational module
D2D/derivedParameters/functions/cps_HartCPS.py (imported, not copied),
and writes per frame: a compressed npz of HVTL, HVTU, HB, HCPSidx and
HCPSclass, a lows table, and the OPC four-panel figure; plus a montage
of all requested hours.

    python3 gfs_cps.py --cycle 2026092406 --hours 6 54 78 102 126 --region natl

Grid convention: every field is reordered to rows increasing northward
(latitude ascending) and columns increasing eastward with contiguous
longitudes, whatever order the source file uses, and the module is run
with ORIENTATION_MODE = 0. See README.md.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
CPS_ROOT = HERE.parent
sys.path.insert(0, str(CPS_ROOT / "D2D" / "derivedParameters" / "functions"))
import cps_HartCPS as hc  # noqa: E402

hc.ORIENTATION_MODE = 0  # rows increase northward after decode() reorders them

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.path as mpath  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap, Normalize  # noqa: E402

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAVE_CARTOPY = True
except ImportError:  # plain lon/lat axes with a GFS land-mask coastline
    HAVE_CARTOPY = False

# ------------------------------------------------------------------ settings
# (west, east, south, north); east < west means the box crosses the dateline.
REGIONS = {"natl": (-100.0, 20.0, 5.0, 80.0), "npac": (120.0, -110.0, 5.0, 70.0), "global": None}
MARGIN_DEG = 10.0
RES_DEG = 0.25
KM_PER_DEG = 111.32
OMEGA = 7.292e-5
HGT_LEVELS = (925, 850, 700, 500, 400, 300)
WIND_LEVELS = (850, 700, 500, 300)
NOMADS = "https://nomads.ncep.noaa.gov"
AWS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
RETRIES = 3
TIMEOUT = 60

# Field key -> (idx variable, idx level text). The same list drives the
# NOMADS var_/lev_ flags, the AWS .idx selection and the decoder.
WANTED = {f"z{p}": ("HGT", f"{p} mb") for p in HGT_LEVELS}
WANTED.update({f"u{p}": ("UGRD", f"{p} mb") for p in WIND_LEVELS})
WANTED.update({f"v{p}": ("VGRD", f"{p} mb") for p in WIND_LEVELS})
WANTED.update(pmsl=("PRMSL", "mean sea level"), psfc=("PRES", "surface"), land=("LAND", "surface"))
PYGRIB_NAMES = {"HGT": "gh", "UGRD": "u", "VGRD": "v", "PRMSL": "prmsl", "PRES": "sp", "LAND": "lsm"}

CMAP_DIR = CPS_ROOT / "D2D" / "colormaps" / "Grid"
CLASS_NAMES = ["sym deep\nwarm", "sym shallow\nwarm", "asym deep\nwarm", "asym shallow\nwarm",
               "asym\ncold", "sym\ncold", "shallow\ncold"]


# ------------------------------------------------------------------ helpers
def cycle_time(cycle: str) -> dt.datetime:
    """Parse YYYYMMDDHH into an aware UTC datetime."""
    return dt.datetime.strptime(cycle, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)


def gfs_name(cycle: str, fhr: int) -> tuple[str, str]:
    """(directory, file name) of the 0.25 degree pgrb2 file, relative to the archive root."""
    ymd, hh = cycle[:8], cycle[8:]
    return f"gfs.{ymd}/{hh}/atmos", f"gfs.t{hh}z.pgrb2.0p25.f{fhr:03d}"


def http_get(url: str, headers: dict | None = None, method: str = "GET") -> requests.Response:
    """GET (or HEAD) with RETRIES attempts and exponential backoff; raises on the last failure."""
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.request(method, url, headers=headers, timeout=TIMEOUT)
            if r.status_code in (200, 206):
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
            if r.status_code == 404:
                break
        except requests.RequestException as exc:
            last = exc
        if attempt < RETRIES - 1:
            time.sleep(2.0 * 2 ** attempt)
    raise RuntimeError(f"failed after retries: {last}")


def cycle_exists(cycle: str) -> str | None:
    """Return 'nomads' or 'aws' if the cycle's f006 index exists there, else None."""
    d, f = gfs_name(cycle, 6)
    for src, root in (("nomads", f"{NOMADS}/pub/data/nccf/com/gfs/prod"), ("aws", AWS)):
        try:
            if requests.head(f"{root}/{d}/{f}.idx", timeout=TIMEOUT).status_code == 200:
                return src
        except requests.RequestException:
            pass
    return None


def latest_cycle(now: dt.datetime | None = None) -> str:
    """Most recent cycle whose f006 exists, probing back up to two days in 6 h steps."""
    now = now or dt.datetime.now(dt.timezone.utc)
    t = now.replace(hour=now.hour // 6 * 6, minute=0, second=0, microsecond=0)
    for _ in range(8):
        cyc = t.strftime("%Y%m%d%H")
        if cycle_exists(cyc):
            return cyc
        t -= dt.timedelta(hours=6)
    raise RuntimeError("no GFS cycle with f006 found in the last two days")


def fetch_box(region: str) -> tuple[float, float, float, float]:
    """(west, span, south, north) of the fetched box: the region plus MARGIN_DEG, lat clipped to +/-90."""
    box = REGIONS[region]
    if box is None:
        return -180.0, 360.0 - RES_DEG, -90.0, 90.0
    w, e, s, n = box
    span = (e - w) % 360.0
    return w - MARGIN_DEG, span + 2 * MARGIN_DEG, max(s - MARGIN_DEG, -90.0), min(n + MARGIN_DEG, 90.0)


# ------------------------------------------------------------------ download
def fetch_nomads(cycle: str, fhr: int, region: str, path: Path) -> None:
    """One grib-filter request: var_/lev_ flags (a cross product, so a few extra
    messages such as UGRD 925 mb come along and are ignored) and the region
    plus margin as a subregion."""
    d, f = gfs_name(cycle, fhr)
    params = {"dir": "/" + d, "file": f}
    for var, lev in WANTED.values():
        params["var_" + var] = "on"
        params["lev_" + lev.replace(" ", "_")] = "on"
    if REGIONS[region] is not None:
        w, span, s, n = fetch_box(region)
        left = w % 360.0
        params.update(subregion="", leftlon=f"{left:g}", rightlon=f"{left + span:g}",
                      toplat=f"{n:g}", bottomlat=f"{s:g}")
    r = http_get(f"{NOMADS}/cgi-bin/filter_gfs_0p25.pl?" + "&".join(f"{k}={v}" for k, v in params.items()))
    if not r.content.startswith(b"GRIB"):
        raise RuntimeError(f"NOMADS returned no GRIB data ({len(r.content)} bytes)")
    path.write_bytes(r.content)


def fetch_aws(cycle: str, fhr: int, path: Path) -> None:
    """Read the .idx sidecar and byte-range GET just the wanted messages of the global file."""
    d, f = gfs_name(cycle, fhr)
    url = f"{AWS}/{d}/{f}"
    lines = http_get(url + ".idx").text.strip().splitlines()
    offsets = [int(ln.split(":")[1]) for ln in lines]
    wanted = set(WANTED.values())
    chunks = []
    for i, ln in enumerate(lines):
        parts = ln.split(":")
        if (parts[3], parts[4]) in wanted:
            end = f"{offsets[i + 1] - 1}" if i + 1 < len(lines) else ""
            chunks.append(http_get(url, headers={"Range": f"bytes={offsets[i]}-{end}"}).content)
    if len(chunks) < len(wanted):
        raise RuntimeError(f"AWS index for {f} lists {len(chunks)} of {len(wanted)} messages")
    path.write_bytes(b"".join(chunks))


def get_grib(cycle: str, fhr: int, region: str, cache: Path, source: str) -> Path:
    """Cached GRIB2 path for one frame, downloading on a miss. NOMADS files are
    per region (subsetted server side); AWS files hold the wanted messages on
    the whole grid and serve every region."""
    cache.mkdir(parents=True, exist_ok=True)
    nom = cache / f"{region}_f{fhr:03d}.nomads.grb2"
    aws = cache / f"global_f{fhr:03d}.aws.grb2"
    for p in (nom, aws):
        if p.exists() and p.stat().st_size > 0:
            return p
    if source == "nomads":
        try:
            fetch_nomads(cycle, fhr, region, nom)
            return nom
        except RuntimeError as exc:
            print(f"  NOMADS failed for f{fhr:03d} ({exc}); falling back to AWS")
    fetch_aws(cycle, fhr, aws)
    return aws


# ------------------------------------------------------------------ decode
def decode(path: Path, region: str) -> dict:
    """Decode the wanted messages with pygrib and reorder them to latitude
    ascending (rows northward) and contiguous longitude ascending from the
    fetch box's west edge (rolled across the dateline or the 0/360 seam as
    needed). Returns the fields plus 1D lat/lon."""
    import pygrib

    w, span, s, n = fetch_box(region)
    out = {}
    with pygrib.open(str(path)) as g:
        msgs = list(g)
    lat = lon = None
    for key, (var, lev) in WANTED.items():
        short, level = PYGRIB_NAMES[var], (int(lev.split()[0]) if lev.endswith("mb") else 0)
        tol = "isobaricInhPa" if lev.endswith("mb") else ("meanSea" if var == "PRMSL" else "surface")
        hit = [m for m in msgs if m.shortName == short and m.typeOfLevel == tol and m.level == level]
        if not hit:
            raise RuntimeError(f"{path.name}: missing {var} {lev}")
        m = hit[0]
        if lat is None:
            la, lo = m.latlons()
            lat, lon = la[:, 0], lo[0, :]
            rel = (lon - w) % 360.0
            cols = np.argsort(rel)
            cols = cols[rel[cols] <= span + 1e-6]
            rows = np.argsort(lat)
            rows = rows[(lat[rows] >= s - 1e-6) & (lat[rows] <= n + 1e-6)]
            lon_out = w + rel[cols]
            lat_out = lat[rows]
        out[key] = np.asarray(m.values, dtype=float)[np.ix_(rows, cols)]
        out.setdefault("valid", m.validDate.replace(tzinfo=dt.timezone.utc))
    out["lat"], out["lon"] = lat_out, lon_out
    return out


# ------------------------------------------------------------------ products
def grid_metrics(lat: np.ndarray, nx: int):
    """dx (m, per row from cos(lat)), dy (m) and coriolis (1/s) pseudo-fields, shape (ny, nx)."""
    dx_row = RES_DEG * KM_PER_DEG * 1000.0 * np.cos(np.radians(lat))
    dx = np.repeat(dx_row[:, None], nx, axis=1)
    dy = np.full_like(dx, RES_DEG * KM_PER_DEG * 1000.0)
    cor = np.repeat((2.0 * OMEGA * np.sin(np.radians(lat)))[:, None], nx, axis=1)
    return dx, dy, cor


def compute_products(f: dict) -> dict:
    """HVTL, HVTU, HB, HCPSidx and HCPSclass through the module's AWIPS entry
    points, with the operational constants; psfc and pmsl are passed in Pa."""
    dx, dy, cor = grid_metrics(f["lat"], f["lon"].size)
    z = [f[f"z{p}"] for p in HGT_LEVELS]
    winds = [f[f"{c}{p}"] for p in WIND_LEVELS for c in "uv"]
    psfc, pmsl = f["psfc"], f["pmsl"]
    return dict(
        hvtl=hc.executeBand3(*z[:3], psfc, dx, dy, 500.0, 925.0, 850.0, 700.0),
        hvtu=hc.executeBand3(*z[3:], psfc, dx, dy, 500.0, 500.0, 400.0, 300.0),
        hb=hc.executeB(z[0], z[2], *winds, psfc, cor, dx, dy, 500.0, 1.4548, 900.0),
        idx=hc.executeIndexStd(pmsl, *z, psfc, dx, dy, 500.0, 100.0, 5.0, 200.0, 900.0, 0),
        cls=hc.executeHartClass(pmsl, *z, *winds, psfc, cor, dx, dy, 500.0, 10.0, 1.4548, 5.0, 200.0, 900.0, 0),
    )


def region_slices(f: dict, region: str):
    """Row and column index arrays that drop the fetch margin."""
    box = REGIONS[region]
    if box is None:
        return np.arange(f["lat"].size), np.arange(f["lon"].size)
    w, e, s, n = box
    rel = (f["lon"] - w) % 360.0
    rows = np.where((f["lat"] >= s) & (f["lat"] <= n))[0]
    cols = np.where(rel <= (e - w) % 360.0 + 1e-6)[0]
    return rows, cols


def label_blobs(mask: np.ndarray, wrap: bool) -> list[np.ndarray]:
    """8-connected components of a boolean mask (flood fill), as lists of flat indices."""
    ny, nx = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    blobs = []
    for start in zip(*np.nonzero(mask)):
        if seen[start]:
            continue
        stack, members = [start], []
        seen[start] = True
        while stack:
            i, j = stack.pop()
            members.append(i * nx + j)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    ii, jj = i + di, j + dj
                    if wrap:
                        jj %= nx
                    if 0 <= ii < ny and 0 <= jj < nx and mask[ii, jj] and not seen[ii, jj]:
                        seen[ii, jj] = True
                        stack.append((ii, jj))
        blobs.append(np.array(members))
    return blobs


def find_lows(f: dict, p: dict, region: str, cycle: str, fhr: int) -> list[dict]:
    """One row per connected blob of the class field: the MSLP minimum inside
    the blob and every product's value there. Blobs whose minimum lies in the
    fetch margin are dropped."""
    rows, cols = region_slices(f, region)
    inside = np.zeros(p["cls"].shape, dtype=bool)
    inside[np.ix_(rows, cols)] = True
    pm = f["pmsl"] / 100.0
    out = []
    for blob in label_blobs(np.isfinite(p["cls"]), wrap=REGIONS[region] is None):
        k = blob[np.argmin(pm.flat[blob])]
        i, j = divmod(int(k), pm.shape[1])
        if not inside[i, j]:
            continue
        out.append(dict(cycle=cycle, fhr=fhr, valid=f["valid"].strftime("%Y-%m-%dT%H:%MZ"),
                        lat=round(float(f["lat"][i]), 2), lon=round((float(f["lon"][j]) + 180) % 360 - 180, 2),
                        mslp_hpa=round(float(pm[i, j]), 1), hvtl=round(float(p["hvtl"][i, j]), 1),
                        hvtu=round(float(p["hvtu"][i, j]), 1), hb=round(float(p["hb"][i, j]), 1),
                        idx=round(float(p["idx"][i, j]), 2), **{"class": int(p["cls"][i, j])}))
    return sorted(out, key=lambda r: r["mslp_hpa"])


def write_lows(path: Path, new_rows: list[dict], hours: list[int]) -> None:
    """Merge rows into the lows CSV, replacing any earlier rows for the same hours."""
    cols = ["cycle", "fhr", "valid", "lat", "lon", "mslp_hpa", "hvtl", "hvtu", "hb", "idx", "class"]
    keep = []
    if path.exists():
        with path.open() as fh:
            keep = [r for r in csv.DictReader(fh) if int(r["fhr"]) not in hours]
    allrows = keep + new_rows
    allrows.sort(key=lambda r: (int(r["fhr"]), float(r["mslp_hpa"])))
    with path.open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(allrows)


# ------------------------------------------------------------------ colormaps
def load_cmap_rgba(path: Path) -> np.ndarray:
    """(N, 4) r,g,b,a array from a CAVE .cmap file (copied from
    article/figures/feature_catalog.py so this tool stays self-contained)."""
    root = ET.parse(path).getroot()
    return np.array([[float(c.get(k)) for k in "rgba"] for c in root.findall("color")])


def make_cmaps() -> dict:
    """The three shipped colormaps with their alpha channels, and the style-rule ranges."""
    cm = {}
    for key, name in (("core", "CPS_CoreDiverging"), ("asym", "CPS_Asymmetry"), ("cls", "CPS_HartClass")):
        c = ListedColormap(load_cmap_rgba(CMAP_DIR / f"{name}.cmap"), name=name)
        c.set_bad((0, 0, 0, 0))
        cm[key] = c
    cm["core_norm"] = Normalize(-300.0, 300.0)
    cm["asym_norm"] = Normalize(-40.0, 40.0)
    cm["cls_norm"] = BoundaryNorm(np.arange(-0.5, 7.5, 1.0), 7)
    return cm


# ------------------------------------------------------------------ plotting
def projection(region: str):
    """Map projection per region (cartopy), or None for plain lon/lat axes."""
    if not HAVE_CARTOPY:
        return None
    if region == "natl":
        return ccrs.LambertConformal(central_longitude=-40.0, standard_parallels=(30.0, 60.0))
    if region == "npac":
        return ccrs.LambertConformal(central_longitude=-175.0, standard_parallels=(30.0, 60.0))
    return ccrs.PlateCarree()


def box_xy(proj, lon: np.ndarray, lat: np.ndarray, k: int = 200) -> np.ndarray:
    """Outline of the lat/lon box spanned by lon and lat, in projection coordinates."""
    w, e, s, n = lon[0], lon[-1], lat[0], lat[-1]
    bl = np.r_[np.linspace(w, e, k), np.full(k, e), np.linspace(e, w, k), np.full(k, w)]
    bb = np.r_[np.full(k, s), np.linspace(s, n, k), np.full(k, n), np.linspace(n, s, k)]
    return proj.transform_points(ccrs.PlateCarree(), bl, bb)[:, :2]


def setup_map(ax, region: str, fr: dict) -> dict:
    """Clip the axes to the region's lat/lon box, draw coastlines, and return
    the keyword arguments data calls need (a transform under cartopy)."""
    lon, lat = fr["lon"], fr["lat"]
    w, e, s, n = lon[0], lon[-1], lat[0], lat[-1]
    if not HAVE_CARTOPY:
        ax.set_xlim(w, e)
        ax.set_ylim(s, n)
        ax.set_aspect(1.0 / np.cos(np.radians(0.5 * (s + n))))
        ax.contour(lon, lat, fr["land"], levels=[0.5], colors="0.2", linewidths=0.5, zorder=4)
        ax.tick_params(labelsize=6)
        return {}
    pc = ccrs.PlateCarree()
    if region != "global":
        xy = box_xy(ax.projection, lon, lat)
        ax.set_boundary(mpath.Path(xy), transform=ax.transData)
        ax.set_xlim(xy[:, 0].min(), xy[:, 0].max())
        ax.set_ylim(xy[:, 1].min(), xy[:, 1].max())
    else:
        ax.set_global()
    ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#efefec", edgecolor="none", zorder=0)
    ax.add_feature(cfeature.COASTLINE.with_scale("50m"), edgecolor="0.15", linewidth=0.5, zorder=4)
    ax.gridlines(color="0.6", linewidth=0.3, alpha=0.6, xlocs=np.arange(-180, 361, 10), ylocs=np.arange(-90, 91, 10))
    return {"transform": pc}


def mslp_contours(ax, fr, kw, color="0.25", lw=0.6, labels=True):
    """MSLP every 4 hPa."""
    cs = ax.contour(fr["lon"], fr["lat"], fr["mslp"], levels=np.arange(900, 1080, 4), colors=color,
                    linewidths=lw, zorder=3, **kw)
    if labels:
        ax.clabel(cs, fmt="%d", fontsize=5, inline=True)


def thin(fr, n_across: int):
    """Row and column indices for evenly spaced vectors, thinning columns by 1/cos(lat)."""
    lat, lon = fr["lat"], fr["lon"]
    step = max(1, int(round((lon[-1] - lon[0]) / RES_DEG / n_across)))
    rows = np.arange(step // 2, lat.size, step)
    pts = [(i, j) for i in rows
           for j in np.arange(step // 2, lon.size, max(1, int(round(step / max(np.cos(np.radians(lat[i])), 0.15)))))]
    return np.array([p[0] for p in pts]), np.array([p[1] for p in pts])


def draw_panels(axes, fr, region, cm, small=False):
    """The four OPC panels on axes (class, HB, HVTL, HVTU); returns the mappables for colorbars."""
    kws = [setup_map(ax, region, fr) for ax in axes]
    lon, lat = fr["lon"], fr["lat"]
    mk = dict(shading="nearest", zorder=2)
    ax, kw = axes[0], kws[0]
    m0 = ax.pcolormesh(lon, lat, np.ma.masked_invalid(fr["cls"]), cmap=cm["cls"], norm=cm["cls_norm"], **mk, **kw)
    mslp_contours(ax, fr, kw, labels=not small)
    for low in fr["lows"]:
        x = low["lon"] if lon[0] <= low["lon"] <= lon[-1] else low["lon"] + 360.0
        ax.text(x, low["lat"], f"{low['mslp_hpa']:.0f}", fontsize=5 if small else 7, weight="bold", ha="center",
                va="center", zorder=6, path_effects=[pe.withStroke(linewidth=2, foreground="white")], **kw)
    m1 = axes[1].pcolormesh(lon, lat, np.ma.masked_invalid(fr["hb"]), cmap=cm["asym"], norm=cm["asym_norm"],
                            **mk, **kws[1])
    mslp_contours(axes[1], fr, kws[1], labels=not small)
    m2 = axes[2].pcolormesh(lon, lat, np.ma.masked_invalid(fr["hvtl"]), cmap=cm["core"], norm=cm["core_norm"],
                            **mk, **kws[2])
    ii, jj = thin(fr, 18 if small else 30)
    kt = 1.0 / 0.514444
    axes[2].barbs(lon[jj], lat[ii], fr["u850"][ii, jj] * kt, fr["v850"][ii, jj] * kt, length=3.2 if small else 4.6,
                  linewidth=0.35 if small else 0.5, color="0.1", zorder=5, **kws[2])
    m3 = axes[3].pcolormesh(lon, lat, np.ma.masked_invalid(fr["hvtu"]), cmap=cm["core"], norm=cm["core_norm"],
                            **mk, **kws[3])
    axes[3].quiver(lon[jj], lat[ii], fr["u300"][ii, jj], fr["v300"][ii, jj], scale=1400 if small else 1800,
                   width=0.0022 if small else 0.0016, color="0.1", zorder=5, **kws[3])
    return [m0, m1, m2, m3]


PANEL_TITLES = ["HCPSclass, MSLP 4 hPa", "HB (m), MSLP 4 hPa", "HVTL 925-700 (m), 850 hPa wind (kt)",
                "HVTU 500-300 (m), 300 hPa wind"]


def add_colorbar(fig, mappable, ax, i, small=False, fraction=0.045):
    """Horizontal colorbar under one panel (or a column of panels) with the style-rule ticks."""
    cb = fig.colorbar(mappable, ax=ax, orientation="horizontal", fraction=fraction, pad=0.02, shrink=0.85)
    cb.ax.tick_params(labelsize=5 if small else 7)
    if i == 0:
        cb.set_ticks(range(7))
        cb.set_ticklabels([str(k) if small else f"{k}\n{CLASS_NAMES[k]}" for k in range(7)], fontsize=5 if small else 7)
    elif i == 1:
        cb.set_ticks([-40, -20, -10, 0, 10, 20, 40])
    else:
        cb.set_ticks([-300, -200, -100, 0, 100, 200, 300])


def panel_aspect(region: str, fr: dict) -> float:
    """Height over width of one map panel in its projection."""
    lon, lat = fr["lon"], fr["lat"]
    if not HAVE_CARTOPY or region == "global":
        return (lat[-1] - lat[0]) / (lon[-1] - lon[0]) / (np.cos(np.radians(lat.mean())) if not HAVE_CARTOPY else 1)
    xy = box_xy(projection(region), lon, lat)
    return float(np.ptp(xy[:, 1]) / np.ptp(xy[:, 0]))


def frame_title(cycle: str, fhr: int, valid: dt.datetime, region: str) -> str:
    """Model, cycle, forecast hour and valid time."""
    c = cycle_time(cycle)
    return (f"GFS 0.25 deg   cycle {c:%Y-%m-%d %H} UTC   F{fhr:03d}   valid {valid:%a %Y-%m-%d %H} UTC   "
            f"Hart CPS ({region})")


def plot_frame(fr: dict, region: str, cycle: str, cm: dict, path: Path) -> None:
    """The four-panel figure for one frame, about 1800 px wide."""
    asp = panel_aspect(region, fr)
    fig = plt.figure(figsize=(18.0, 2 * 9.0 * asp + 2.4), dpi=100, layout="constrained")
    axes = [fig.add_subplot(2, 2, k + 1, projection=projection(region)) for k in range(4)]
    for i, (ax, m) in enumerate(zip(axes, draw_panels(axes, fr, region, cm))):
        ax.set_title(PANEL_TITLES[i], fontsize=10)
        add_colorbar(fig, m, ax, i)
    fig.suptitle(frame_title(cycle, fr["fhr"], fr["valid"], region), fontsize=13)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def plot_montage(frames: list[dict], region: str, cycle: str, cm: dict, path: Path) -> None:
    """Rows by forecast hour, the four products across (class, HB, HVTL, HVTU)."""
    asp = panel_aspect(region, frames[0])
    n = len(frames)
    fig = plt.figure(figsize=(18.0, n * (4.5 * asp + 0.35) + 1.2), dpi=100, layout="constrained")
    columns = [[] for _ in range(4)]
    for r, fr in enumerate(frames):
        axes = [fig.add_subplot(n, 4, 4 * r + k + 1, projection=projection(region)) for k in range(4)]
        mappables = draw_panels(axes, fr, region, cm, small=True)
        for i, ax in enumerate(axes):
            ax.set_title(f"F{fr['fhr']:03d} {fr['valid']:%d/%HZ}  {PANEL_TITLES[i]}", fontsize=7)
            columns[i].append(ax)
    for i in range(4):  # one colorbar under each column
        add_colorbar(fig, mappables[i], columns[i], i, small=True, fraction=0.045 / n)
    fig.suptitle(f"GFS 0.25 deg Hart CPS, cycle {cycle_time(cycle):%Y-%m-%d %H} UTC, {region}", fontsize=13)
    fig.savefig(path, dpi=100)
    plt.close(fig)


# ------------------------------------------------------------------ driver
def run_frame(cycle: str, fhr: int, region: str, outdir: Path, source: str, cm: dict) -> dict:
    """Fetch, decode, compute, save the npz and the figure for one forecast hour."""
    t0 = time.time()
    grib = get_grib(cycle, fhr, region, outdir.parent / "cache" / cycle, source)
    f = decode(grib, region)
    t1 = time.time()
    p = compute_products(f)
    t2 = time.time()
    lows = find_lows(f, p, region, cycle, fhr)
    rows, cols = region_slices(f, region)
    cut = np.ix_(rows, cols)
    fr = {k: v[cut] for k, v in {**p, "mslp": f["pmsl"] / 100.0, "u850": f["u850"], "v850": f["v850"],
                                  "u300": f["u300"], "v300": f["v300"], "land": f["land"]}.items()}
    fr.update(lat=f["lat"][rows], lon=f["lon"][cols], valid=f["valid"], fhr=fhr, lows=lows)
    np.savez_compressed(outdir / f"cps_{region}_f{fhr:03d}.npz", lat=fr["lat"], lon=fr["lon"],
                        mslp_hpa=fr["mslp"].astype(np.float32),
                        **{k: fr[k].astype(np.float32) for k in ("hvtl", "hvtu", "hb", "idx", "cls")})
    plot_frame(fr, region, cycle, cm, outdir / f"cps4_{region}_f{fhr:03d}.png")
    print(f"  f{fhr:03d}: {grib.name}, fetch+decode {t1 - t0:.1f} s, compute {t2 - t1:.1f} s, "
          f"plot {time.time() - t2:.1f} s, {len(lows)} lows")
    return fr


def main(argv=None) -> int:
    """Command line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycle", help="YYYYMMDDHH (default: latest cycle whose f006 exists)")
    ap.add_argument("--hours", type=int, nargs="+", default=list(range(0, 121, 6)))
    ap.add_argument("--region", choices=sorted(REGIONS), default="natl")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--source", choices=["nomads", "aws"], default="nomads")
    ap.add_argument("--plain", action="store_true", help="skip cartopy; coastline from the GFS land mask")
    a = ap.parse_args(argv)
    global HAVE_CARTOPY
    HAVE_CARTOPY = HAVE_CARTOPY and not a.plain
    cycle = a.cycle or latest_cycle()
    outdir = a.out / cycle
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"cycle {cycle}, region {a.region}, hours {a.hours}, source {a.source}, "
          f"maps {'cartopy' if HAVE_CARTOPY else 'plain lon/lat, GFS land-mask coastline'}")
    cm = make_cmaps()
    t0 = time.time()
    frames, lows = [], []
    for fhr in a.hours:
        try:
            fr = run_frame(cycle, fhr, a.region, outdir, a.source, cm)
        except Exception as exc:  # keep going: late hours may not be posted yet
            print(f"  f{fhr:03d}: skipped ({exc})")
            continue
        frames.append(fr)
        lows.extend(fr["lows"])
    if not frames:
        return 1
    write_lows(outdir / f"lows_{a.region}.csv", lows, [fr["fhr"] for fr in frames])
    if len(frames) > 1:
        plot_montage(frames, a.region, cycle, cm, outdir / f"cps4_{a.region}_montage.png")
    print(f"done: {len(frames)} frames in {time.time() - t0:.1f} s, output in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
