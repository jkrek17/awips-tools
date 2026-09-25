#!/usr/bin/env python3
"""Data for the live global web map of the Hart cyclone phase space products.

    python3 export_web.py [--cycle YYYYMMDDHH] [--hours 0 6 ... 198] [--out DIR] [--workers N]

For every forecast hour of one GFS 0.25 degree cycle, on the global grid,
the products are computed once through gfs_cps (fetch, decode and the
operational module's executeHartClass, executeBand3, executeB and
executeIndexStd entry points) and written as files a static web page can
load directly:

    DIR/index.json                cycle, hours, valid times, layers, raster geometry, storms
                                  (every low closed for 24 h, linked across the frames, plus the
                                  daily collection's storms that no track matches)
    DIR/legend.json               class palette, colormap stops, ranges
    DIR/history.json              the cycles exported to DIR
    DIR/frames/fHHH/lows.geojson  one polygon per closed low (HCPSclass blob) and its center
    DIR/frames/fHHH/mslp.geojson  MSLP every 4 hPa
    DIR/frames/fHHH/{hb,hvtl,hvtu,class}.png   Web Mercator rasters, lon -180..180, lat -85..85

Without --cycle the newest cycle whose f198 is posted (NOMADS, else the AWS
bucket) is used, probing back two days in 6 h steps. Without --out the files
go to out/web/<cycle>/ and out/web/history.json lists every cycle there.
See README.md, "Live web map data".
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gfs_cps as g  # noqa: E402
import track_cps as tc  # noqa: E402

import contourpy  # noqa: E402  (comes with matplotlib)
from PIL import Image  # noqa: E402
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping  # noqa: E402
from shapely.geometry.polygon import orient  # noqa: E402
from shapely.affinity import translate  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

REGION = "global"
DEFAULT_HOURS = list(range(0, 199, 6))
LAST_FHR = 198
PROBE_CYCLES = 8  # default cycle: the newest with f198, probing back this many 6 h steps
DATA = HERE / "data"
STORMS_REL = "../storms"  # storm assets, relative to index.json's directory: STORMS_REL/<cycle>/<NAME>/...
TRACK_REACH_KM = 600.0  # a center may move this far between 6 h frames (track_cps: 90 km/h reach, 600 km cap)
TRACK_GAP_FRAMES = 1  # one missing frame is bridged, with the reach scaled by the elapsed time
TRACK_MIN_FRAMES = 5  # a track is kept when the low stays closed for 24 h (five 6 h frames)
TRACK_MATCH_KM = 300.0  # a collected storm and a track are the same low when their same-hour centers are this close

# Rasters: Web Mercator (EPSG:3857) image covering lon -180..180, lat -85..85.
LAT_MAX = 85.0
WIDTH = 2048
RASTERS = {  # key -> (colormap file, range, units, label)
    "hb": ("CPS_Asymmetry", (-40.0, 40.0), "m", "HB, storm-relative 900-600 hPa thickness asymmetry"),
    "hvtl": ("CPS_CoreDiverging", (-300.0, 300.0), "m", "HVTL, lower thermal wind 925-700 hPa"),
    "hvtu": ("CPS_CoreDiverging", (-300.0, 300.0), "m", "HVTU, upper thermal wind 500-300 hPa"),
}
LEGEND_STOPS = 16

# Vectors.
BLOB_TOL_DEG = 0.25  # blob polygon simplification
MSLP_TOL_DEG = 0.15  # isobar simplification ...
MSLP_MAX_BYTES = 400_000  # ... raised in 0.05 degree steps (up to 0.6) while mslp.geojson is larger
MSLP_STEP_HPA = 4.0
TERRAIN_RING_DEG = 1.0  # closed isobars smaller than this over high terrain are dropped
MIN_PART_DEG = 0.2  # a dateline piece narrower than this is the half-cell pad, not part of the blob
NDIG = 2
BLOB_RADIUS_KM = 200  # the dilation radius the low-finder uses to build each blob (track_cps.CLOSED_BLOB_KM)
TERRAIN_PSFC_HPA = 925.0  # display default (not a product rule): a center this far below the surface, roughly
#                          770 m, is flagged as a terrain artifact rather than a real low; trips over the
#                          Iranian and Mexican plateaus, Mongolia and the Andes foothills, not the Great Plains

CLASS_FULL = ["symmetric deep warm core", "symmetric shallow warm core", "asymmetric deep warm core",
              "asymmetric shallow warm core", "asymmetric cold core", "symmetric cold core", "shallow cold core"]


def log(msg: str) -> None:
    print(msg, flush=True)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def r1(v) -> float | None:
    """One decimal, or None for NaN."""
    v = float(v)
    return round(v, 1) if math.isfinite(v) else None


def track_val(row: dict, key: str) -> float | None:
    """One decimal from a track.csv field, or None if blank or the column is missing."""
    v = row.get(key, "")
    return round(float(v), 1) if v not in ("", None) else None


def write_json(path: Path, obj) -> int:
    """Compact JSON; returns the size in bytes."""
    s = json.dumps(obj, separators=(",", ":"), allow_nan=False)
    path.write_text(s)
    return len(s)


# ------------------------------------------------------------------ cycle
def f198_source(cycle: str) -> str | None:
    """'nomads' or 'aws' if the cycle's f198 index is posted there, else None."""
    d, f = g.gfs_name(cycle, LAST_FHR)
    for src, root in (("nomads", f"{g.NOMADS}/pub/data/nccf/com/gfs/prod"), ("aws", g.AWS)):
        try:
            if requests.head(f"{root}/{d}/{f}.idx", timeout=g.TIMEOUT).status_code == 200:
                return src
        except requests.RequestException:
            pass
    return None


def default_cycle(now: dt.datetime | None = None) -> str:
    """The newest cycle whose f198 is posted, stepping back 6 h at a time."""
    now = now or dt.datetime.now(dt.timezone.utc)
    t = now.replace(hour=now.hour // 6 * 6, minute=0, second=0, microsecond=0)
    for _ in range(PROBE_CYCLES):
        cyc = t.strftime("%Y%m%d%H")
        src = f198_source(cyc)
        if src:
            log(f"default cycle {cyc}: f{LAST_FHR:03d} found on {src}")
            return cyc
        log(f"cycle {cyc}: f{LAST_FHR:03d} not posted")
        t -= dt.timedelta(hours=6)
    raise SystemExit(f"no GFS cycle with f{LAST_FHR:03d} in the last {PROBE_CYCLES} cycles")


# ------------------------------------------------------------------ colormaps
def palettes() -> dict:
    """Per raster key: (rgba uint8 (N, 4), lo, hi); 'class' has the 7 class colors."""
    out = {}
    for key, (name, (lo, hi), _, _) in RASTERS.items():
        out[key] = (np.round(g.load_cmap_rgba(g.CMAP_DIR / f"{name}.cmap") * 255).astype(np.uint8), lo, hi)
    out["class"] = (np.round(g.load_cmap_rgba(g.CMAP_DIR / "CPS_HartClass.cmap") * 255).astype(np.uint8), -0.5, 6.5)
    return out


def hexcol(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[int(c) for c in rgb[:3]])


def cmap_index(v: np.ndarray, n: int, lo: float, hi: float) -> np.ndarray:
    """Colormap entry of each value as matplotlib's ListedColormap with
    Normalize(lo, hi) picks it (ends clipped); n (the transparent entry) for NaN."""
    with np.errstate(invalid="ignore"):
        k = np.floor((v - lo) / (hi - lo) * n)
    k = np.clip(np.nan_to_num(k, nan=n), 0, n)
    k[~np.isfinite(v)] = n
    return k.astype(np.uint8)


def legend(pal: dict) -> dict:
    stops, ranges, units, labels = {}, {}, {}, {}
    for key, (cmap, (lo, hi), unit, label) in RASTERS.items():
        rgba = pal[key][0]
        vals = np.linspace(lo, hi, LEGEND_STOPS)
        idx = cmap_index(vals, len(rgba), lo, hi)
        idx = np.minimum(idx, len(rgba) - 1)
        stops[key] = [[round(float(v), 2), hexcol(rgba[i]), round(rgba[i][3] / 255.0, 3)] for v, i in zip(vals, idx)]
        ranges[key] = [lo, hi]
        units[key] = unit
        labels[key] = f"{label} ({cmap})"
    cls = pal["class"][0]
    return {
        "classes": [{"code": k, "name": tc.CLASS_SHORT[k], "hex": hexcol(cls[k])} for k in range(len(cls))],
        "class_full": CLASS_FULL,
        "stops": stops,
        "ranges": ranges,
        "units": units,
        "labels": labels,
    }


# ------------------------------------------------------------------ rasters
def mercator_height(width: int = WIDTH, lat_max: float = LAT_MAX) -> int:
    ymax = math.log(math.tan(math.pi / 4 + math.radians(lat_max) / 2))
    return int(round(width * 2 * ymax / (2 * math.pi)))


class Sampler:
    """Maps the 0.25 degree lat/lon grid (rows northward, lon from -180) onto
    the Web Mercator image by nearest grid point: the latitude of each output
    row from the inverse of y = ln(tan(pi/4 + lat/2)), rows spaced evenly in
    y from lat_max at the top down to -lat_max, columns evenly in longitude
    from -180, wrapping at the seam. (Bilinear sampling of the continuous
    fields looked no better at this size and made the PNGs about 70% larger.)"""

    def __init__(self, lat: np.ndarray, lon: np.ndarray, width: int = WIDTH, lat_max: float = LAT_MAX):
        self.width, self.height = width, mercator_height(width, lat_max)
        ymax = math.log(math.tan(math.pi / 4 + math.radians(lat_max) / 2))
        y = ymax - (np.arange(self.height) + 0.5) * (2 * ymax / self.height)
        lat_out = np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)
        lon_out = -180.0 + (np.arange(width) + 0.5) * 360.0 / width
        fi = (lat_out - lat[0]) / (lat[1] - lat[0])
        fj = (lon_out - lon[0]) / (lon[1] - lon[0])
        self.ir = np.clip(np.rint(fi).astype(int), 0, lat.size - 1)
        self.jr = np.rint(fj).astype(int) % lon.size

    def __call__(self, a: np.ndarray) -> np.ndarray:
        return np.asarray(a, dtype=float)[np.ix_(self.ir, self.jr)]


def save_palette_png(idx: np.ndarray, rgba: np.ndarray, path: Path) -> int:
    """Indexed PNG: entries 0..N-1 are the colormap (with its alpha), entry N is transparent."""
    pal = np.vstack([rgba, [[0, 0, 0, 0]]]).astype(np.uint8)
    im = Image.fromarray(idx, mode="P")
    im.putpalette(pal[:, :3].ravel().tolist())
    im.save(path, optimize=True, transparency=bytes(pal[:, 3].tolist()))
    return path.stat().st_size


def write_rasters(p: dict, smp: Sampler, pal: dict, fdir: Path) -> dict:
    sizes = {}
    for key in RASTERS:
        rgba, lo, hi = pal[key]
        v = smp(p[key])
        sizes[key] = save_palette_png(cmap_index(v, len(rgba), lo, hi), rgba, fdir / f"{key}.png")
    rgba = pal["class"][0]
    c = smp(p["cls"])
    k = np.where(np.isfinite(c), np.clip(np.rint(np.nan_to_num(c)), 0, len(rgba) - 1), len(rgba)).astype(np.uint8)
    sizes["class"] = save_palette_png(k, rgba, fdir / "class.png")
    return sizes


# ------------------------------------------------------------------ vectors
def rnd(coords) -> list:
    """Coordinates rounded to NDIG decimals, as nested lists."""
    if isinstance(coords[0], (float, int)):
        return [round(float(coords[0]), NDIG), round(float(coords[1]), NDIG)]
    return [rnd(c) for c in coords]


WORLD = box(-180.0, -90.0, 180.0, 90.0)


def split_dateline(geom) -> list:
    """Pieces of a geometry drawn in continuous longitude (it may run past
    180 or -180), shifted back into -180..180 and cut at the dateline."""
    parts = []
    for off in (0.0, -360.0, 360.0):
        piece = translate(geom, xoff=off).intersection(WORLD) if off else geom.intersection(WORLD)
        if piece.is_empty:
            continue
        x0, _, x1, _ = piece.bounds
        if x1 - x0 < MIN_PART_DEG:
            continue
        parts.append(piece)
    return parts


def polygons_of(geom) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    return [q for q in getattr(geom, "geoms", []) if isinstance(q, Polygon) and not q.is_empty]


def blob_geometry(members: np.ndarray, lat: np.ndarray, lon: np.ndarray):
    """The outline of one blob (flat indices into the global grid) as a
    shapely geometry in continuous longitude: the 0.5 filled contour of its
    own mask (other blobs left out), on a sub-grid padded by one cell and
    unrolled so a blob across the seam is contiguous."""
    nx = lon.size
    ii, jj = np.divmod(members, nx)
    u = np.unique(jj)
    gaps = np.diff(np.r_[u, u[0] + nx])  # gap after each occupied column, circularly
    start = u[(int(np.argmax(gaps)) + 1) % u.size]  # first column after the widest gap
    jr = (jj - start) % nx
    i0, i1, w = ii.min(), ii.max(), jr.max() + 1
    sub = np.zeros((i1 - i0 + 3, w + 2))
    sub[ii - i0 + 1, jr + 1] = 1.0
    dlat, dlon = lat[1] - lat[0], lon[1] - lon[0]
    x = lon[start] + (np.arange(w + 2) - 1) * dlon
    y = lat[i0] + (np.arange(i1 - i0 + 3) - 1) * dlat
    gen = contourpy.contour_generator(x, y, sub, fill_type=contourpy.FillType.OuterOffset)
    polys = []
    for pts, offs in zip(*gen.filled(0.5, 1.5)):
        rings = [pts[offs[k]:offs[k + 1]] for k in range(len(offs) - 1)]
        poly = Polygon(rings[0], rings[1:])
        if not poly.is_valid:
            poly = poly.buffer(0)
        polys.append(poly)
    return unary_union(polys) if polys else None


def lows_features(f: dict, p: dict) -> list[dict]:
    """One center Point per connected blob of HCPSclass (the MSLP minimum
    inside it and every product there) and the blob's outline as Polygon or
    MultiPolygon features (two, same id, for a blob across the dateline)."""
    lat, lon = f["lat"], f["lon"]
    pm = f["pmsl"] / 100.0
    ps = f["psfc"] / 100.0
    cls = np.asarray(p["cls"], dtype=float)
    blobs = g.label_blobs(np.isfinite(cls), wrap=True)
    centers = []
    for blob in blobs:
        k = int(blob[np.argmin(pm.flat[blob])])
        i, j = divmod(k, pm.shape[1])
        centers.append((float(pm[i, j]), i, j, blob))
    centers.sort(key=lambda c: c[0])  # id 1 is the deepest low of the frame
    feats, points = [], []
    for n, (mslp, i, j, blob) in enumerate(centers, start=1):
        c = int(round(float(cls[i, j])))
        geom = blob_geometry(blob, lat, lon)
        for piece in split_dateline(geom) if geom is not None else []:
            simp = piece.simplify(BLOB_TOL_DEG, preserve_topology=True)
            if simp.is_empty:
                simp = piece
            polys = [orient(q, 1.0) for q in polygons_of(simp)]
            if not polys:
                continue
            shape = polys[0] if len(polys) == 1 else MultiPolygon(polys)
            gj = mapping(shape)
            feats.append({"type": "Feature", "properties": {"kind": "blob", "cls": c, "id": n},
                          "geometry": {"type": gj["type"], "coordinates": rnd(gj["coordinates"])}})
        la, lo = round(float(lat[i]), NDIG), round((float(lon[j]) + 180.0) % 360.0 - 180.0, NDIG)
        psfc = r1(ps[i, j])
        points.append({"type": "Feature",
                       "properties": {"kind": "center", "id": n, "lat": la, "lon": lo, "mslp": round(mslp, 1),
                                      "hvtl": r1(p["hvtl"][i, j]), "hvtu": r1(p["hvtu"][i, j]),
                                      "hb": r1(p["hb"][i, j]), "idx": r1(p["idx"][i, j]), "cls": c,
                                      "psfc": psfc, "terrain": psfc is not None and psfc < TERRAIN_PSFC_HPA,
                                      "radius_km": BLOB_RADIUS_KM,
                                      "name": tc.CLASS_SHORT[c] if 0 <= c < len(tc.CLASS_SHORT) else str(c)},
                       "geometry": {"type": "Point", "coordinates": [lo, la]}})
    return feats + points


def mslp_features(f: dict, tol: float = MSLP_TOL_DEG) -> list[dict]:
    """Isobars every MSLP_STEP_HPA hPa from contourpy on the global field.
    The first column is repeated at lon 180 so lines reach the dateline,
    where they end (and continue from -180). Small closed rings (under
    TERRAIN_RING_DEG across) centered where the surface pressure is below
    tc.MIN_PSFC_HPA are dropped: over high terrain MSLP is extrapolated and
    breaks into many such rings, which are noise rather than lows."""
    lat, lon = f["lat"], f["lon"]
    pm = f["pmsl"] / 100.0
    ps = f["psfc"] / 100.0
    x = np.r_[lon, lon[0] + 360.0]
    z = np.concatenate([pm, pm[:, :1]], axis=1)
    gen = contourpy.contour_generator(x, lat, z, line_type=contourpy.LineType.Separate)
    lo = math.ceil(np.nanmin(pm) / MSLP_STEP_HPA) * MSLP_STEP_HPA
    dlat, dlon = lat[1] - lat[0], lon[1] - lon[0]
    feats = []
    for level in np.arange(lo, np.nanmax(pm), MSLP_STEP_HPA):
        for line in gen.lines(level):
            if len(line) < 2:
                continue
            if (line[0] == line[-1]).all() and np.ptp(line, axis=0).max() < TERRAIN_RING_DEG:
                cx, cy = line.mean(axis=0)
                i = int(np.clip(round((cy - lat[0]) / dlat), 0, lat.size - 1))
                j = int(round((cx - lon[0]) / dlon)) % lon.size
                if ps[i, j] < tc.MIN_PSFC_HPA:
                    continue
            line = np.clip(line, [-180.0, -90.0], [180.0, 90.0])
            s = LineString(line).simplify(tol, preserve_topology=False)
            coords = rnd(list(s.coords)) if not s.is_empty else []
            coords = [c for k, c in enumerate(coords) if k == 0 or c != coords[k - 1]]  # repeats from rounding
            if len(coords) < 2:
                continue
            feats.append({"type": "Feature", "properties": {"level": int(level)},
                          "geometry": {"type": "LineString", "coordinates": coords}})
    return feats



# ------------------------------------------------------------------ frames
def export_frame(cycle: str, fhr: int, out: Path, cache: Path) -> dict:
    """Fetch, decode and compute one frame, write its GeoJSON and PNGs.
    Returns the valid time, the number of lows, timings and sizes."""
    t0 = time.time()
    grib = g.get_grib(cycle, fhr, REGION, cache, "nomads", False)
    f = g.decode(grib, REGION, False)
    t1 = time.time()
    p = g.compute_products(f)
    t2 = time.time()
    fdir = out / "frames" / f"f{fhr:03d}"
    fdir.mkdir(parents=True, exist_ok=True)
    lows = lows_features(f, p)
    sizes = {"lows": write_json(fdir / "lows.geojson", {"type": "FeatureCollection", "features": lows})}
    tol = MSLP_TOL_DEG
    while True:
        iso_ = mslp_features(f, tol)
        s = json.dumps({"type": "FeatureCollection", "features": iso_}, separators=(",", ":"))
        if len(s) <= MSLP_MAX_BYTES or tol >= 0.6:
            break
        tol = round(tol + 0.05, 2)
    (fdir / "mslp.geojson").write_text(s)
    sizes["mslp"] = len(s)
    t3 = time.time()
    smp = Sampler(f["lat"], f["lon"])
    sizes.update(write_rasters(p, smp, palettes(), fdir))
    t4 = time.time()
    n = sum(1 for ft in lows if ft["properties"]["kind"] == "center")
    return dict(fhr=fhr, valid=iso(f["valid"]), lows=n, mslp_tol=tol, sizes=sizes, height=smp.height,
                t_fetch=t1 - t0, t_compute=t2 - t1, t_vec=t3 - t2, t_png=t4 - t3)


# ------------------------------------------------------------------ storms
def storms_for(cycle: str, data_dir: Path = DATA) -> tuple[str | None, list[dict]]:
    """The collected storms (status ok) of the newest data/<cycle> folder
    on this cycle's day, or of the newest folder if none is."""
    if not data_dir.exists():
        return None, []
    cands = sorted((p.name for p in data_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{10}", p.name)),
                   reverse=True)
    same_day = [c for c in cands if c[:8] == cycle[:8]]
    pick = (same_day or cands or [None])[0]
    if pick is None:
        return None, []
    storms = []
    for mp in sorted((data_dir / pick).glob("*/meta.json")):
        try:
            meta = json.loads(mp.read_text())
        except (OSError, ValueError):
            continue
        sdir = mp.parent
        if meta.get("status") != "ok" or not (sdir / "track.csv").exists():
            continue
        pts = []
        with (sdir / "track.csv").open() as fh:
            for row in csv.DictReader(fh):
                c = row.get("class", "")
                pts.append({"fhr": int(row["fhr"]), "valid": row["valid"].replace("Z", ":00Z"),
                            "lat": round(float(row["lat"]), 2), "lon": round(float(row["lon"]), 2),
                            "mslp": round(float(row["mslp_hpa"]), 1),
                            "cls": int(round(float(c))) if c not in ("", None) else None,
                            "hvtl": track_val(row, "hvtl"), "hvtu": track_val(row, "hvtu"),
                            "hb": track_val(row, "hb")})
        fsu = meta.get("fsu_number")
        storms.append({"name": sdir.name, "cycle": pick, "fsu": int(fsu) if fsu is not None else None,
                       "points": pts, "cls_seq": [pt["cls"] for pt in pts],
                       "phase_png": f"{STORMS_REL}/{pick}/{sdir.name}/phase.png",
                       "compare_png": f"{STORMS_REL}/{pick}/{sdir.name}/compare.png"
                       if (sdir / "compare.png").exists() else None})
    return pick, storms



# ------------------------------------------------------------------ tracks
def link_tracks(frames: list[dict], reach_km: float = TRACK_REACH_KM, gap: int = TRACK_GAP_FRAMES,
                min_frames: int = TRACK_MIN_FRAMES) -> list[list[dict]]:
    """Link the closed-low centers of consecutive frames into tracks.

    frames: [{"fhr", "valid", "centers": [center properties as lows_features
    writes them]}] in time order. Centers over high terrain (the extrapolated
    MSLP there is not a low) are not linked. Each center is predicted from the
    track's last position plus half its last 6 h motion and joined to the
    closest unclaimed center within reach_km per 6 h elapsed, closest pairs
    first, one center per track; a track may skip up to gap frames. Tracks
    shorter than min_frames are dropped. Each point keeps the center's frame
    id so the page can join the map marks to the track."""
    tracks: list[dict] = []
    for fr in frames:
        fhr, valid = fr["fhr"], fr["valid"]
        cands = [c for c in fr["centers"] if not c.get("terrain")]
        live = [t for t in tracks if 0 < fhr - t["last_fhr"] <= 6 * (gap + 1)]
        pairs = []
        for ti, t in enumerate(live):
            steps = (fhr - t["last_fhr"]) / 6.0
            plat = t["lat"] + 0.5 * t["dlat"] * steps
            plon = t["lon"] + 0.5 * t["dlon"] * steps
            for ci, c in enumerate(cands):
                d = float(tc.gc_km(plat, plon, c["lat"], c["lon"]))
                if d <= reach_km * steps:
                    pairs.append((d, ti, ci))
        pairs.sort()
        used_t, used_c = set(), set()
        for d, ti, ci in pairs:
            if ti in used_t or ci in used_c:
                continue
            used_t.add(ti)
            used_c.add(ci)
            t, c = live[ti], cands[ci]
            steps = (fhr - t["last_fhr"]) / 6.0
            dlon = float(tc.wrap180(c["lon"] - t["lon"]))
            t["dlat"], t["dlon"] = (c["lat"] - t["lat"]) / steps, dlon / steps
            t["lat"], t["lon"], t["last_fhr"] = c["lat"], c["lon"], fhr
            t["points"].append(_track_point(fhr, valid, c))
        for ci, c in enumerate(cands):
            if ci not in used_c:
                tracks.append({"lat": c["lat"], "lon": c["lon"], "dlat": 0.0, "dlon": 0.0, "last_fhr": fhr,
                               "points": [_track_point(fhr, valid, c)]})
    return [t["points"] for t in tracks if len(t["points"]) >= min_frames]


def _track_point(fhr: int, valid: str, c: dict) -> dict:
    return {"fhr": fhr, "valid": valid, "id": c["id"], "lat": c["lat"], "lon": c["lon"], "mslp": c["mslp"],
            "cls": c["cls"], "hvtl": c["hvtl"], "hvtu": c["hvtu"], "hb": c["hb"], "idx": c.get("idx")}


def match_collection(points: list[dict], storms: list[dict], km: float = TRACK_MATCH_KM) -> dict | None:
    """The collected storm whose track shares the most valid times within km
    of this track (at least two, and at least half of the hours both have),
    or None."""
    by_valid = {p["valid"]: p for p in points}
    best, best_n = None, 0
    for s in storms:
        both = [(by_valid[q["valid"]], q) for q in s["points"] if q["valid"] in by_valid]
        if len(both) < 2:
            continue
        n = sum(1 for p, q in both if float(tc.gc_km(p["lat"], p["lon"], q["lat"], q["lon"])) <= km)
        if n >= 2 and n * 2 >= len(both) and n > best_n:
            best, best_n = s, n
    return best


def build_storms(out: Path, hours: list[int], valids: list[str], collection: list[dict]) -> list[dict]:
    """The storm list of index.json: every track of link_tracks over the
    exported frames, deepest first, named after the collected storm it
    matches (with its FSU number and diagrams) or L01, L02, ...; then the
    collected storms no track matched. The frames' center features get a
    "track" property with the track id."""
    frames, feats = [], {}
    for fhr, valid in zip(hours, valids):
        path = out / "frames" / f"f{fhr:03d}" / "lows.geojson"
        try:
            fc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        feats[fhr] = (path, fc)
        frames.append({"fhr": fhr, "valid": valid,
                       "centers": [ft["properties"] for ft in fc["features"] if ft["properties"]["kind"] == "center"]})
    tracks = link_tracks(frames)
    tracks.sort(key=lambda pts: (min(p["mslp"] for p in pts), pts[0]["fhr"]))
    storms, taken, n_unnamed = [], set(), 0
    for k, pts in enumerate(tracks, start=1):
        tid = f"T{k:02d}"
        hit = match_collection(pts, [s for s in collection if s["name"] not in taken])
        if hit is not None:
            taken.add(hit["name"])
            name, fsu, phase, comp = hit["name"], hit["fsu"], hit["phase_png"], hit["compare_png"]
        else:
            n_unnamed += 1
            name, fsu, phase, comp = f"L{n_unnamed:02d}", None, None, None
        storms.append({"id": tid, "name": name, "source": "track", "fsu": fsu,
                       "min_mslp": min(p["mslp"] for p in pts), "points": pts,
                       "cls_seq": [p["cls"] for p in pts], "phase_png": phase, "compare_png": comp})
        for p in pts:
            for ft in feats[p["fhr"]][1]["features"]:
                if ft["properties"]["kind"] == "center" and ft["properties"]["id"] == p["id"]:
                    ft["properties"]["track"] = tid
    for k, s in enumerate((s for s in collection if s["name"] not in taken), start=1):
        storms.append({"id": f"C{k:02d}", "source": "collection", "min_mslp": min(p["mslp"] for p in s["points"]),
                       **s})
    for path, fc in feats.values():
        write_json(path, fc)
    return storms


# ------------------------------------------------------------------ driver
def update_history(path: Path, cycle: str, generated: str, index: str) -> None:
    """history.json: {"latest": cycle, "cycles": [{"cycle", "generated", "index"}, ...]}, newest first."""
    old = []
    if path.exists():
        try:
            old = [c for c in json.loads(path.read_text()).get("cycles", []) if c.get("cycle") != cycle]
        except (OSError, ValueError, AttributeError):
            old = []
    cycles = sorted(old + [{"cycle": cycle, "generated": generated, "index": index}],
                    key=lambda c: c["cycle"], reverse=True)
    write_json(path, {"latest": cycles[0]["cycle"], "cycles": cycles})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycle", help="YYYYMMDDHH (default: the newest cycle whose f198 is posted)")
    ap.add_argument("--hours", type=int, nargs="+", default=DEFAULT_HOURS)
    ap.add_argument("--out", type=Path, help="output directory (default: out/web/<cycle>/)")
    ap.add_argument("--cache", type=Path, help="GRIB cache (default: out/cache/<cycle>/)")
    ap.add_argument("--workers", type=int, default=min(3, os.cpu_count() or 1),
                    help="frames computed in parallel (processes)")
    ap.add_argument("--relink", type=Path, metavar="DIR",
                    help="only rebuild the storms of an existing export DIR from its frames")
    a = ap.parse_args(argv)
    if a.relink:
        return relink(a.relink.resolve())
    cycle = a.cycle or default_cycle()
    if not re.fullmatch(r"\d{10}", cycle):
        ap.error("--cycle must be YYYYMMDDHH")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"cycle={cycle}\n")
    web_root = HERE / "out" / "web"
    out = (a.out or web_root / cycle).resolve()
    cache = (a.cache or HERE / "out" / "cache" / cycle).resolve()
    out.mkdir(parents=True, exist_ok=True)
    hours = sorted(set(a.hours))
    log(f"cycle {cycle}, {len(hours)} hours, {a.workers} workers, out {out}")
    t0 = time.time()
    done = []
    with ProcessPoolExecutor(max_workers=max(1, a.workers)) as pool:
        futs = {h: pool.submit(export_frame, cycle, h, out, cache) for h in hours}
        for h in hours:
            try:
                r = futs[h].result()
            except Exception as exc:  # a missing hour is skipped, the rest still publish
                log(f"  f{h:03d}: skipped ({exc})")
                continue
            done.append(r)
            sz = r["sizes"]
            log(f"  f{h:03d}: {time.time() - t0:5.0f} s  fetch+decode {r['t_fetch']:.1f} s, compute "
                f"{r['t_compute']:.1f} s, geojson {r['t_vec']:.1f} s, png {r['t_png']:.1f} s; {r['lows']} lows; "
                f"lows {sz['lows'] / 1e3:.0f} KB, mslp {sz['mslp'] / 1e3:.0f} KB (tol {r['mslp_tol']}), "
                + ", ".join(f"{k} {sz[k] / 1e3:.0f} KB" for k in ("hb", "hvtl", "hvtu", "class")))
    if not done:
        log("no frame could be exported")
        return 1
    generated = iso(dt.datetime.now(dt.timezone.utc))
    pal = palettes()
    leg = legend(pal)
    write_json(out / "legend.json", leg)
    storms_cycle, collection = storms_for(cycle)
    storms = build_storms(out, [r["fhr"] for r in done], [r["valid"] for r in done], collection)
    index = {
        "cycle": cycle,
        "model": "GFS 0.25",
        "generated": generated,
        "hours": [r["fhr"] for r in done],
        "valid": [r["valid"] for r in done],
        "layers": {"class": True, "mslp": True, "hb": True, "hvtl": True, "hvtu": True},
        "raster": {"bounds": [[-LAT_MAX, -180], [LAT_MAX, 180]], "crs": "EPSG:3857", "width": WIDTH,
                   "height": done[0]["height"]},
        "ranges": leg["ranges"],
        "frames": "frames/f{hhh}/",
        "storms_cycle": storms_cycle,
        "storms": storms,
    }
    index["tracks"] = sum(1 for s_ in storms if s_["source"] == "track")
    write_json(out / "index.json", index)
    update_history(out / "history.json", cycle, generated, "index.json")
    if a.out is None:
        update_history(web_root / "history.json", cycle, generated, f"{cycle}/index.json")
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    log(f"done: {len(done)} of {len(hours)} frames in {time.time() - t0:.0f} s, {index['tracks']} tracks, "
        f"{len(storms) - index['tracks']} more collected storms (data/{storms_cycle}), {total / 1e6:.1f} MB in {out}")
    return 0


def relink(out: Path) -> int:
    """Rebuild index.json's storms from the frames already in out (no GRIB)."""
    ip = out / "index.json"
    index = json.loads(ip.read_text())
    storms_cycle, collection = storms_for(index["cycle"])
    storms = build_storms(out, index["hours"], index["valid"], collection)
    index["storms_cycle"], index["storms"] = storms_cycle, storms
    index["tracks"] = sum(1 for s_ in storms if s_["source"] == "track")
    write_json(ip, index)
    log(f"relinked {out}: {index['tracks']} tracks, {len(storms) - index['tracks']} more collected storms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
