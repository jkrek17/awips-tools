#!/usr/bin/env python3
"""Storm-following Hart cyclone phase space from GFS 0.25 degree data.

Driven by gfs_cps.py:

    python3 gfs_cps.py --cycle 2026092412 --region global --hours $(seq 0 6 198) \\
        --track EPAC:15.5,-155.5 --track GREENLAND:62,-20 --hart-bands

Each frame is fetched, decoded and run through the operational module
with gfs_cps's own functions (fetch, decode, compute_products,
compute_hart_bands); every --track low is followed from frame to frame
by its MSLP minimum, the products are sampled at the center, and per
low this writes out/<cycle>/track_<NAME>.csv and phase_<NAME>.png: the
two Hart diagrams in the style of the Florida State University cyclone
phase pages (24 h running mean, markers every 6 h colored by MSLP) and
the time series of the three parameters with the class strip. See
README.md, "Storm-following phase diagrams".
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import gfs_cps as g

hc = g.hc
import matplotlib.pyplot as plt  # noqa: E402  (gfs_cps selected the Agg backend)
import matplotlib.patheffects as pe  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

sys.path.insert(0, str(g.CPS_ROOT / "article" / "figures"))
import diagram_style as ds  # noqa: E402  (Hart's quadrant colors, labels and limits)

# ------------------------------------------------------------------ settings
SPEED_KMH = 90.0  # search radius grows at this rate with the hours since the last fix, and no
#                   candidate may lie farther from the last fix than this rate allows (no cap)
CAP_KM = 600.0  # ... up to this radius
SEED_KM = 400.0  # search radius around the seed position at FHR0
LOCAL_MIN_HALF = 4  # a candidate center is the minimum of its (2k+1) x (2k+1) box (k = 4: +/- 1 degree)
MAX_MSLP_HPA = 1018.0  # a minimum at or above this is not a center (FSU's tracker limit)
MIN_PSFC_HPA = 950.0  # nor is one where the surface is higher than about 500 m (MSLP extrapolated)
POLE_LAT = 85.0  # nor is one poleward of this latitude (the pole row is one repeated value)
MAX_RISE_HPA = 12.0  # nor one more than this above the previous fix (a handover, not a filling low)
OUTSIDE_FRAMES = 2  # a track ends after this many consecutive fixes outside the closed-low mask
MERGE_TRACK_KM = 150.0  # two tracks whose centers are closer than this in a frame: the later one stops
CLOSED_DEPTH_HPA = 2.0  # the tracker's closed-low test: closed_low_mask with a 2 hPa ring depth
CLOSED_BLOB_KM = 200.0  # (the product uses 5 hPa, which a broad deep low's 300-500 km ring can miss)
CLOSED_SEARCH_KM = hc.MIN_RADIUS_KM  # closedness is checked at the deepest MSLP within this of the fix,
#                    not at the fix itself (the mask's own candidate radius: a secondary minimum whose
#                    box reaches a deeper center that far away is still judged by that deeper center)
CLIMB_KM = 0.0  # a fix moves to a deeper candidate this close; 0 turns the step off (it merged two
#                 adjacent lows in testing); hc.MIN_RADIUS_KM (300 km, the mask's candidate radius) turns it on
CLIMB_TOL_HPA = hc.DEFAULT_CENTER_TOL_HPA  # ... if deeper by more than this (the mask's center tolerance)
SUB_KM = 1000.0  # half width of the subgrid kept around each center for B with the track motion
RADIUS_KM = 500.0
LAYER_SCALE = 1.4548  # 925-700 hPa thickness rescaled to 900-600 hPa, as in the D2D XML
B_THR = 10.0
EARTH_R_KM = 6371.0
MS_TO_KT = 1.0 / 0.514444
SMOOTH_H = 24.0  # centered running mean over +/- 12 h (5 frames at 6 h)

# FSU's intensity legend: marker color by MSLP, each step covering pressures
# above the next deeper step up to its own value (1004 hPa is "1010").
INTENSITY = [(950, "#ff1493"), (960, "#ff8c00"), (970, "#e8d800"), (980, "#1fbf1f"), (990, "#19c3c3"),
             (1000, "#1f3fff"), (1010, "#9b19c8"), (1015, "#000000")]
CLASS_PALETTE = {0: (0.85, 0.15, 0.15), 1: (0.80, 0.20, 0.75), 2: (0.98, 0.85, 0.10), 3: (0.20, 0.68, 0.25),
                 4: (0.15, 0.50, 0.90), 5: (0.35, 0.22, 0.72), 6: (0.72, 0.72, 0.70)}
CLASS_SHORT = ["sym deep warm", "sym shallow warm", "asym deep warm", "asym shallow warm", "asym cold",
               "sym cold", "shallow cold"]
PURPLE, RED, BLUE = "#8e44ad", "#d62d2d", "#2a78d6"

CSV_COLS = ["fhr", "valid", "lat", "lon", "mslp_hpa", "hvtl", "hvtu", "hb", "idx", "class", "hvtl_hart",
            "hvtu_hart", "hb_track", "motion_kt", "heading_deg", "steering_heading_deg", "steering_kt", "hb_hart"]


# ------------------------------------------------------------------ geometry
def parse_track(spec: str) -> dict:
    """NAME:LAT,LON[:FHR0[:FHR1]] -> dict(name, lat, lon, fhr0, fhr1); FHR1
    (optional) is the last hour to track, for a low known to be lost or
    replaced by another after it."""
    parts = spec.split(":")
    if len(parts) not in (2, 3, 4):
        raise SystemExit(f"--track {spec!r}: expected NAME:LAT,LON[:FHR0[:FHR1]]")
    lat, lon = (float(v) for v in parts[1].split(","))
    return dict(name=parts[0], lat=lat, lon=(lon + 180.0) % 360.0 - 180.0,
                fhr0=int(parts[2]) if len(parts) > 2 and parts[2] else 0,
                fhr1=int(parts[3]) if len(parts) > 3 else 10 ** 6)


def gc_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (km), broadcasting."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def wrap180(lon):
    """Longitude folded to -180..180."""
    return (np.asarray(lon) + 180.0) % 360.0 - 180.0


def frac_index(f: dict, lat: float, lon: float) -> tuple[float, float]:
    """Fractional (row, column) of a position on the decoded grid."""
    return (lat - f["lat"][0]) / g.RES_DEG, ((lon - f["lon"][0]) % 360.0) / g.RES_DEG


def subgrid(f: dict, fi: float, fj: float, half_km: float, wrap: bool):
    """Row and column index arrays of a box of about +/- half_km around the
    fractional grid position (fi, fj), and the position's fractional index
    inside the box. On the global grid the columns wrap; the column count
    uses the grid spacing at the box's most poleward row so the box is at
    least half_km wide on every row."""
    ny, nx = f["lat"].size, f["lon"].size
    dy_km = g.RES_DEG * g.KM_PER_DEG
    hr = int(math.ceil(half_km / dy_km))
    ic, jc = int(round(fi)), int(round(fj))
    rows = np.arange(max(0, ic - hr), min(ny, ic + hr + 1))
    cosmin = max(np.cos(np.radians(np.abs(f["lat"][rows]).max())), 0.05)
    hcol = min(int(math.ceil(half_km / (dy_km * cosmin))), nx // 2 - 1)
    cols = np.arange(jc - hcol, jc + hcol + 1)
    if wrap:
        cols %= nx
        j_local = fj - (jc - hcol)
    else:
        cols = cols[(cols >= 0) & (cols < nx)]
        j_local = fj - cols[0]
    return rows, cols, fi - rows[0], j_local


def bilinear(a: np.ndarray, fi: float, fj: float) -> float:
    """Bilinear value at a fractional index, NaN-aware: missing corners are
    dropped and the remaining weights renormalized (NaN if all four are
    missing). Columns wrap."""
    ny, nx = a.shape
    i0, j0 = int(math.floor(fi)), int(math.floor(fj))
    di, dj = fi - i0, fj - j0
    num = den = 0.0
    for ii, wi in ((i0, 1 - di), (i0 + 1, di)):
        for jj, wj in ((j0, 1 - dj), (j0 + 1, dj)):
            if 0 <= ii < ny and wi * wj > 0:
                v = a[ii, jj % nx]
                if np.isfinite(v):
                    num += wi * wj * v
                    den += wi * wj
    return num / den if den > 0 else float("nan")


def nearest(a: np.ndarray, fi: float, fj: float) -> float:
    """Value at the grid point nearest a fractional index (columns wrap)."""
    ny, nx = a.shape
    return float(a[min(max(int(round(fi)), 0), ny - 1), int(round(fj)) % nx])


def local_minima(pm: np.ndarray, k: int) -> np.ndarray:
    """Boolean mask of points equal to the minimum of their (2k+1)^2 box
    (edges padded with +inf)."""
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.pad(pm, k, constant_values=np.inf)
    return pm <= sliding_window_view(pad, (2 * k + 1, 2 * k + 1)).min(axis=(2, 3))


def parabolic(a: float, b: float, c: float) -> float:
    """Offset (-0.5..0.5 cells) of the vertex of the parabola through
    (-1, a), (0, b), (1, c)."""
    den = a - 2 * b + c
    return float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) if den > 0 else 0.0


def all_centers(f: dict, wrap: bool) -> list[tuple[int, int, float]]:
    """Every point of the whole grid that find_center would accept as a
    center: terrain (surface pressure below MIN_PSFC_HPA) masked before the
    +/- LOCAL_MIN_HALF box-minimum test, MSLP below MAX_MSLP_HPA, latitude
    within POLE_LAT. On the
    global grid the box wraps across the seam. Returns [(i, j, mslp_hpa)]."""
    k = LOCAL_MIN_HALF
    pm = f["pmsl"] / 100.0
    pm_ok = np.where(f["psfc"] / 100.0 >= MIN_PSFC_HPA, pm, np.inf)
    if wrap:
        ext = np.concatenate([pm_ok[:, -k:], pm_ok, pm_ok[:, :k]], axis=1)
        ismin = local_minima(ext, k)[:, k:-k]
    else:
        ismin = local_minima(pm_ok, k)
    ismin &= (pm_ok < MAX_MSLP_HPA) & (np.abs(f["lat"]) <= POLE_LAT)[:, None]
    return [(int(i), int(j), float(pm[i, j])) for i, j in np.argwhere(ismin)]


def closed_mask(f: dict) -> np.ndarray:
    """The tracker's closed-low test: the module's closed_low_mask on MSLP
    with the arguments executeHartClass passes it except a ring depth of
    CLOSED_DEPTH_HPA (2 hPa) instead of the product's 5 hPa, which a broad
    deep low (its 300 to 500 km ring not 5 hPa above the center) fails.
    Unlike a blank HCPSclass, it does not depend on B or the band levels,
    so a slow storm (HB blank under MIN_STEERING_MS) or one over low
    terrain still counts as a closed low."""
    dx, dy, _ = g.grid_metrics(f["lat"], f["lon"].size)
    return hc.closed_low_mask(hc.pmsl_input_hpa(f["pmsl"], hc.PMSL_KIND_PRESSURE), dx, dy, hc.MIN_RADIUS_KM,
                              RADIUS_KM, CLOSED_DEPTH_HPA, CLOSED_BLOB_KM)


def closed_at(f: dict, mask: np.ndarray, clat: float, clon: float, wrap: bool) -> bool:
    """Whether the fix at (clat, clon) counts as inside a closed low: the
    mask (closed_mask) taken not at the fix itself but at the deepest MSLP
    within CLOSED_SEARCH_KM of it (terrain and pole masked out, as in
    find_center). A secondary minimum whose own +/- 300 km candidate box
    reaches onto the flank of a deeper center that far away fails the
    mask's candidate test right at the fix; walking to the deepest point
    within the same radius lands on that flank, close enough to the deeper
    center to fall inside its mask blob, without moving the tracked
    position itself (so the 150 km merge rule between tracks never sees
    it). Where the fix already is the deepest point nearby (the ordinary
    case, one low with nothing deeper close by) this is identical to
    testing the mask at the fix."""
    fi, fj = frac_index(f, clat, clon)
    rows, cols, _, _ = subgrid(f, fi, fj, CLOSED_SEARCH_KM, wrap)
    pm = f["pmsl"][np.ix_(rows, cols)] / 100.0
    ps = f["psfc"][np.ix_(rows, cols)] / 100.0
    la = f["lat"][rows][:, None]
    lo = f["lon"][cols][None, :]
    ok = (ps >= MIN_PSFC_HPA) & (np.abs(la) <= POLE_LAT) & (gc_km(clat, clon, la, lo) <= CLOSED_SEARCH_KM)
    pm_ok = np.where(ok, pm, np.inf)
    r, c = np.unravel_index(int(np.argmin(pm_ok)), pm_ok.shape)
    if not np.isfinite(pm_ok[r, c]):
        return bool(nearest(mask, fi, fj))
    return bool(nearest(mask, float(rows[r]), float(cols[c])))


def find_center(f: dict, lat: float, lon: float, radius_km: float, wrap: bool, max_mslp: float | None = None,
                reach: tuple[float, float, float] | None = None):
    """The MSLP minimum nearest (lat, lon) within radius_km: a point that is
    the lowest of its +/- LOCAL_MIN_HALF box, below MAX_MSLP_HPA (and not
    above max_mslp, if given), where the surface pressure is at least
    MIN_PSFC_HPA, no more than POLE_LAT from the equator, and, if reach =
    (lat0, lon0, km) is given, within km of (lat0, lon0). If CLIMB_KM is
    above 0 (it is 0, off, by default) and a candidate more than
    CLIMB_TOL_HPA deeper (by the same tests, not limited to
    radius_km but still within reach) lies within CLIMB_KM of the chosen
    one, the fix moves to the deepest such candidate, repeatedly, until
    none is: the center closed_low_mask's candidate test recognizes,
    rather than a secondary minimum beside it; minima within the mask's
    own 0.6 hPa center tolerance are left alone. Returns (fi, fj, mslp_hpa) on
    the full grid, refined to a fraction of a cell by a parabola through the
    minimum and its neighbors along each axis, or None.

    Terrain points (surface pressure below MIN_PSFC_HPA, where MSLP is
    extrapolated well below ground) are masked out before the box-minimum
    test, not just filtered from the candidate list afterward: otherwise an
    artificially deep terrain reading (the Greenland ice cap, Iceland's
    interior) can sit inside a genuine low's +/- 1 degree box and hide it,
    since the real, slightly shallower minimum beside the terrain then no
    longer looks like the lowest point of its own box."""
    fi, fj = frac_index(f, lat, lon)
    rows, cols, _, _ = subgrid(f, fi, fj, radius_km + CLIMB_KM + 150.0, wrap)
    pm = f["pmsl"][np.ix_(rows, cols)] / 100.0
    la = f["lat"][rows][:, None]
    lo = f["lon"][cols][None, :]
    ps = f["psfc"][np.ix_(rows, cols)] / 100.0
    pm_ok = np.where(ps >= MIN_PSFC_HPA, pm, np.inf)
    ismin = local_minima(pm_ok, LOCAL_MIN_HALF)
    dist = gc_km(lat, lon, la, lo)
    ok = ismin & (pm_ok < MAX_MSLP_HPA) & (np.abs(la) <= POLE_LAT)
    if max_mslp is not None:
        ok &= pm_ok <= max_mslp
    if reach is not None:
        ok &= gc_km(reach[0], reach[1], la, lo) <= reach[2]
    cand = np.argwhere(ok & (dist <= radius_km))
    if cand.size == 0:
        return None
    r, c = min(cand, key=lambda rc: dist[rc[0], rc[1]])
    every = np.argwhere(ok) if CLIMB_KM > 0 else np.empty((0, 2), dtype=int)
    while every.size:  # climb to the deepest candidate within CLIMB_KM (off when CLIMB_KM is 0)
        near = gc_km(la[r, 0], lo[0, c], la[every[:, 0], 0], lo[0, every[:, 1]]) <= CLIMB_KM
        deeper = [(pm_ok[a, b], a, b) for a, b in every[near] if pm_ok[a, b] < pm_ok[r, c] - CLIMB_TOL_HPA]
        if not deeper:
            break
        _, r, c = min(deeper)
    i, j = rows[r], cols[c]
    full = f["pmsl"] / 100.0
    ny, nx = full.shape
    di = parabolic(full[i - 1, j], full[i, j], full[i + 1, j]) if 0 < i < ny - 1 else 0.0
    dj = parabolic(full[i, (j - 1) % nx], full[i, j], full[i, (j + 1) % nx])
    return i + di, j + dj, float(full[i, j])


# ------------------------------------------------------------------ tracking
class Track:
    """One followed low: seed, fixes (one dict per frame) and state."""

    def __init__(self, spec: str):
        self.__dict__.update(parse_track(spec))
        self.fixes: list[dict] = []
        self.missed = 0
        self.outside = 0  # consecutive fixes outside the closed-low mask
        self.done = False
        self.end_reason = ""
        self.merged: tuple[str, int, float] | None = None  # (other track, hour, km) when it stopped for it

    def guess(self, fhr: int) -> tuple[float, float, float]:
        """(lat, lon, radius_km): the seed, or the last fix moved on by the
        last motion over the hours since it (half of that after a coasted
        frame, so a wrong motion does not carry the search away), and the
        search radius."""
        if not self.fixes:
            return self.lat, self.lon, SEED_KM
        last = self.fixes[-1]
        hours = fhr - last["fhr"]
        lat, lon = last["lat"], last["lon"]
        if len(self.fixes) > 1:
            prev = self.fixes[-2]
            rate = hours / (last["fhr"] - prev["fhr"]) * (0.5 if self.missed else 1.0)
            lat += (last["lat"] - prev["lat"]) * rate
            lon += float(wrap180(last["lon"] - prev["lon"])) * rate
        return float(np.clip(lat, -89.0, 89.0)), float(wrap180(lon)), min(SPEED_KMH * hours, CAP_KM)


def sample_frame(tr: Track, f: dict, p: dict, fhr: int, wrap: bool) -> None:
    """Advance one track by one frame: find the center, sample the products
    there, and keep the subgrid B needs once the track motion is known."""
    if fhr > tr.fhr1 and not tr.done:
        tr.done = True
        tr.end_reason = f"FHR1 {tr.fhr1} h reached"
    if tr.done or fhr < tr.fhr0:
        return
    lat, lon, rad = tr.guess(fhr)
    cap = reach = None
    if tr.fixes:
        last = tr.fixes[-1]
        cap = last["mslp_hpa"] + MAX_RISE_HPA
        reach = (last["lat"], last["lon"], SPEED_KMH * (fhr - last["fhr"]))
    hit = find_center(f, lat, lon, rad, wrap, cap, reach)
    if hit is None:
        what = f"no minimum within {rad:.0f} km of {lat:.1f},{lon:.1f}" + (
            f" at or below {cap:.0f} hPa and within {reach[2]:.0f} km of the last fix" if cap else "")
        if tr.fixes and tr.missed == 0:
            tr.missed = 1
            print(f"  {tr.name} f{fhr:03d}: {what}; extrapolating one frame")
        else:
            tr.done = True
            tr.end_reason = f"{what} at +{fhr} h"
            print(f"  {tr.name} f{fhr:03d}: {what}; track ends")
        return
    tr.missed = 0
    fi, fj, pmin = hit
    clat = float(f["lat"][0] + fi * g.RES_DEG)
    clon = float(wrap180(f["lon"][0] + fj * g.RES_DEG))
    row = dict(fhr=fhr, valid=f["valid"], lat=clat, lon=clon, mslp_hpa=pmin)
    for k in ("hvtl", "hvtu", "hb", "idx", "hvtl_hart", "hvtu_hart"):
        row[k] = bilinear(p[k], fi, fj) if k in p else float("nan")
    row["class"] = nearest(p["cls"], fi, fj)
    row["closed"] = (closed_at(f, p["closed"], clat, clon, wrap) if "closed" in p
                     else bool(np.isfinite(row["class"])))
    if not row["closed"]:
        tr.outside += 1
        if tr.outside >= OUTSIDE_FRAMES:  # end at the last fix inside a closed low
            out = [fx["fhr"] for fx in tr.fixes if not fx["closed"]][-(OUTSIDE_FRAMES - 1):] + [fhr]
            while len(tr.fixes) > 1 and not tr.fixes[-1]["closed"]:
                tr.fixes.pop()
            tr.done = True
            tr.end_reason = (f"outside a closed low at +{', +'.join(str(h) for h in out)} h "
                             f"({pmin:.0f} hPa at +{fhr} h)")
            print(f"  {tr.name} f{fhr:03d}: {tr.end_reason}; track ends at +{tr.fixes[-1]['fhr']} h")
            return
    else:
        tr.outside = 0
    # Subgrid around the center: thickness for B, and the module's steering proxy.
    rows, cols, li, lj = subgrid(f, fi, fj, SUB_KM, wrap)
    cut = np.ix_(rows, cols)
    dx, dy, cor = g.grid_metrics(f["lat"][rows], cols.size)
    ps = hc.surface_pressure_hpa(f["psfc"][cut])

    def masked(p_hpa):
        return hc.mask_below_ground(f[f"z{p_hpa}"][cut], ps, float(p_hpa), hc.BELOW_GROUND_CAP_HPA)

    sub = dict(dx=dx, dy=dy, cor=cor, li=li, lj=lj, thk=masked(700) - masked(925))
    if "z600" in f and "z900" in f:
        sub["thk_hart"] = masked(600) - masked(900)
    us, vs = hc.steering([f[f"u{q}"][cut] for q in g.WIND_LEVELS], [f[f"v{q}"][cut] for q in g.WIND_LEVELS])
    us, vs = hc.steering_window_mean(us, vs, dx, dy, RADIUS_KM)
    su, sv = bilinear(us, li, lj), bilinear(vs, li, lj)
    row["steering_heading_deg"] = math.degrees(math.atan2(su, sv)) % 360.0
    row["steering_kt"] = math.hypot(su, sv) * MS_TO_KT
    # Same B as the full grid (a check that the subgrid holds the whole window).
    b_sub = hc.parameter_b_grid(sub["thk"], us, vs, dx, dy, cor, RADIUS_KM, LAYER_SCALE)
    row["hb_sub_check"] = bilinear(b_sub, li, lj)
    row["sub"] = sub
    tr.fixes.append(row)


def merge_close(tracks: list[Track], fhr: int, km: float | None = None) -> list[tuple[Track, Track, float]]:
    """Two tracks that chose centers within km of each other at this frame
    follow the same low: the one whose track started later (for the same
    start the shallower here, then the later in the list) stops at its
    previous fix (km defaults to MERGE_TRACK_KM). Returns [(stopped, kept, distance_km), ...]."""
    km = MERGE_TRACK_KM if km is None else km
    here = [(t.fixes[0]["fhr"], t.fixes[-1]["mslp_hpa"], k, t) for k, t in enumerate(tracks)
            if t.fixes and t.fixes[-1]["fhr"] == fhr and t.merged is None]
    kept: list[Track] = []
    out = []
    for *_, t in sorted(here, key=lambda r: r[:3]):
        fx = t.fixes[-1]
        near = min(((float(gc_km(fx["lat"], fx["lon"], k.fixes[-1]["lat"], k.fixes[-1]["lon"])), k) for k in kept),
                   default=None, key=lambda r: r[0])
        if near is None or near[0] >= km:
            kept.append(t)
            continue
        t.fixes.pop()
        t.done = True
        t.merged = (near[1].name, fhr, near[0])
        t.end_reason = f"merged into {near[1].name} at +{fhr} h"
        print(f"  {t.name} f{fhr:03d}: {near[0]:.0f} km from {near[1].name}; {t.end_reason}")
        out.append((t, near[1], near[0]))
    return out


def track_motion(fixes: list[dict]) -> None:
    """Center motion from the track by finite differences: centered over the
    neighboring fixes inside the track, one-sided at its ends. Sets
    motion_kt, heading_deg (toward, clockwise from north), u_ms, v_ms."""
    n = len(fixes)
    for k, fx in enumerate(fixes):
        a, b = fixes[max(k - 1, 0)], fixes[min(k + 1, n - 1)]
        hours = b["fhr"] - a["fhr"]
        if n < 2 or hours <= 0:
            fx.update(motion_kt=float("nan"), heading_deg=float("nan"), u_ms=float("nan"), v_ms=float("nan"))
            continue
        mlat = math.radians(0.5 * (a["lat"] + b["lat"]))
        east = float(wrap180(b["lon"] - a["lon"])) * g.KM_PER_DEG * math.cos(mlat)
        north = (b["lat"] - a["lat"]) * g.KM_PER_DEG
        u, v = east * 1000.0 / (hours * 3600.0), north * 1000.0 / (hours * 3600.0)
        fx.update(u_ms=u, v_ms=v, motion_kt=math.hypot(u, v) * MS_TO_KT,
                  heading_deg=math.degrees(math.atan2(u, v)) % 360.0)


def b_with_track_motion(fixes: list[dict]) -> None:
    """hb_track (925-700 hPa thickness scaled by LAYER_SCALE, as HB) and,
    with Hart's levels, hb_hart (900-600 hPa thickness, unscaled): the
    module's parameter_b_grid with u_s, v_s a uniform field of the track
    motion, on the subgrid kept around the center, sampled there. Unlike HB
    (blank under MIN_STEERING_MS), any nonzero track motion is used, as
    FSU's B uses its tracker's motion whatever the speed."""
    for fx in fixes:
        sub = fx.pop("sub")
        fx["hb_track"] = fx["hb_hart"] = float("nan")
        if not np.isfinite(fx["u_ms"]):
            continue
        u = np.full(sub["thk"].shape, fx["u_ms"])
        v = np.full(sub["thk"].shape, fx["v_ms"])
        for key, thk, scale in (("hb_track", "thk", LAYER_SCALE), ("hb_hart", "thk_hart", 1.0)):
            if thk in sub:
                b = hc.parameter_b_grid(sub[thk], u, v, sub["dx"], sub["dy"], sub["cor"], RADIUS_KM, scale,
                                        min_speed=0.0)
                fx[key] = bilinear(b, sub["li"], sub["lj"])


def write_csv(path: Path, fixes: list[dict]) -> None:
    """track_<NAME>.csv, one row per fix."""
    def fmt(k, v):
        if k == "valid":
            return v.strftime("%Y-%m-%dT%H:%MZ")
        if k == "fhr":
            return str(v)
        if k == "class":
            return "" if not np.isfinite(v) else str(int(v))
        if not np.isfinite(v):
            return ""
        return f"{v:.2f}" if k in ("lat", "lon", "idx") else f"{v:.1f}"

    with path.open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(CSV_COLS)
        for fx in fixes:
            wr.writerow([fmt(k, fx[k]) for k in CSV_COLS])


# ------------------------------------------------------------------ analysis
def running_mean(hours: np.ndarray, vals: np.ndarray, width_h: float = SMOOTH_H) -> np.ndarray:
    """Centered running mean over +/- width_h/2 (5 frames at 6 h), NaN-aware;
    near the ends of the track the window holds the frames that exist."""
    out = np.full(vals.shape, np.nan)
    for k, h in enumerate(hours):
        w = vals[np.abs(hours - h) <= width_h / 2 + 1e-6]
        w = w[np.isfinite(w)]
        if w.size:
            out[k] = w.mean()
    return out


def first_hour(hours, vals, test, after=None):
    """First hour (not before `after`) where test(vals) holds, else NaN."""
    for h, v in zip(hours, vals):
        if (after is None or h >= after) and np.isfinite(v) and test(v):
            return float(h)
    return float("nan")


def onset_completion(hours, b, vtl) -> tuple[float, float]:
    """Onset: first hour the smoothed B exceeds B_THR. Completion: first hour
    at or after onset (from the start if no onset) the smoothed lower
    thermal wind term drops below zero."""
    on = first_hour(hours, b, lambda v: v > B_THR)
    comp = first_hour(hours, vtl, lambda v: v < 0.0, after=None if np.isnan(on) else on)
    return on, comp


def intensity_color(p: float) -> str:
    """FSU intensity step color for MSLP p (hPa)."""
    for step, color in INTENSITY:
        if p <= step:
            return color
    return INTENSITY[-1][1]


# ------------------------------------------------------------------ figure
def fsu_time(t: dt.datetime) -> str:
    """12Z24SEP2026."""
    return f"{t:%H}Z{t:%d}{t:%b}{t:%Y}".upper()


def limits(base, *series, pad=0.06):
    """base, widened to fit the finite values of the series plus a margin."""
    lo, hi = ds.widen_limits(base, *series)
    m = pad * (hi - lo)
    return (lo - m if lo < base[0] else lo, hi + m if hi > base[1] else hi)


def draw_trajectory(ax, hours, valid, x, y, xr, yr, mslp, xh=None, yh=None):
    """FSU-style trajectory on one diagram: raw series faint, 24 h mean as
    the main line with markers every 6 h colored by MSLP (analysis solid,
    forecast with an x), day of month at 00Z, A and Z at the ends; the
    Hart-band trajectory (already smoothed) dashed with open diamonds."""
    ax.plot(xr, yr, "-", color="0.45", lw=0.8, alpha=0.45, zorder=3)
    ax.scatter(xr, yr, s=6, color="0.45", alpha=0.45, zorder=3, linewidths=0)
    if xh is not None:
        ax.plot(xh, yh, "--", color="0.15", lw=1.4, zorder=4)
        ax.scatter(xh, yh, s=26, marker="D", facecolor="white", edgecolor="0.15", linewidth=0.9, zorder=4)
    ax.plot(x, y, "-", color="black", lw=2.0, zorder=5)
    cols = [intensity_color(p) for p in mslp]
    ax.scatter(x, y, s=110, c=cols, edgecolor="black", linewidth=0.7, zorder=6)
    fc = hours > 0
    ax.scatter(x[fc], y[fc], s=55, marker="x", color="white", linewidth=2.6, zorder=7)
    ax.scatter(x[fc], y[fc], s=55, marker="x", color="black", linewidth=1.1, zorder=8)
    halo = [pe.withStroke(linewidth=3, foreground="white")]
    for k, t in enumerate(valid):
        if t.hour == 0 and np.isfinite(x[k]) and np.isfinite(y[k]):
            ax.annotate(f"{t:%d}", (x[k], y[k]), xytext=(0, 9), textcoords="offset points", ha="center",
                        va="bottom", fontsize=12, weight="bold", zorder=9, path_effects=halo)
    ok = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    if ok.size:
        for k, lab in ((ok[0], "A"), (ok[-1], "Z")):
            ax.annotate(lab, (x[k], y[k]), xytext=(-12, -12), textcoords="offset points", ha="center",
                        va="center", fontsize=15, weight="bold", zorder=9, path_effects=halo)


def plot_phase(path: Path, name: str, cycle: str, fixes: list[dict], hart: bool) -> dict:
    """phase_<NAME>.png: (a) B against -V_T^L, (b) -V_T^U against -V_T^L,
    (c) the time series with the class strip. Returns onset/completion."""
    hours = np.array([fx["fhr"] for fx in fixes], dtype=float)
    valid = [fx["valid"] for fx in fixes]
    col = {k: np.array([fx[k] for fx in fixes], dtype=float)
           for k in ("hvtl", "hvtu", "hb", "hvtl_hart", "hvtu_hart", "hb_track", "hb_hart", "mslp_hpa", "class")}
    sm = {k: running_mean(hours, v) for k, v in col.items()}
    have_h = hart and np.isfinite(col["hvtl_hart"]).any()
    ev = {"standard": onset_completion(hours, sm["hb"], sm["hvtl"])}
    if have_h:
        ev["hart"] = onset_completion(hours, sm["hb_track"], sm["hvtl_hart"])

    fig = plt.figure(figsize=(24.0, 10.0), dpi=100)
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.0, 1.25], left=0.045, right=0.985, top=0.80, bottom=0.25,
                          wspace=0.2)
    axa, axb, axc = (fig.add_subplot(gs[0, k]) for k in range(3))
    xs = [col["hvtl"], sm["hvtl"]] + ([col["hvtl_hart"], sm["hvtl_hart"]] if have_h else [])
    xlim = limits((-50.0, 250.0), *xs)
    ylim_a = limits((-10.0, 30.0), col["hb"], sm["hb"], sm["hb_track"])
    ylim_b = limits((-100.0, 100.0), col["hvtu"], sm["hvtu"], *([sm["hvtu_hart"]] if have_h else []))

    # (a) B against -V_T^L
    axa.set_xlim(*xlim)
    axa.set_ylim(*ylim_a)
    ds.draw_b_vtl_quadrants(axa, xlim, ylim_a, B_THR, fontsize=11)
    axa.axhline(B_THR, color="black", lw=1.0, zorder=2)
    axa.axhline(0.0, color="0.35", lw=0.7, ls=":", zorder=2)
    axa.axvline(0.0, color="black", lw=1.0, zorder=2)
    draw_trajectory(axa, hours, valid, sm["hvtl"], sm["hb"], col["hvtl"], col["hb"], col["mslp_hpa"],
                    sm["hvtl_hart"] if have_h else None, sm["hb_track"] if have_h else None)
    if not have_h:  # track-motion B against the standard lower term
        axa.plot(sm["hvtl"], sm["hb_track"], ":", color="0.15", lw=1.4, zorder=4)
    axa.set_xlabel(r"$-V_T^L$ (m)   925-700 hPa thermal wind" + (" (dashed: 900-600 hPa)" if have_h else ""),
                   fontsize=12)
    axa.set_ylabel("B (m)   storm-relative 925-700 hPa thickness asymmetry, scaled to 900-600", fontsize=12)
    axa.set_title("(a) B against $-V_T^L$", loc="left", fontsize=14)

    # (b) -V_T^U against -V_T^L
    axb.set_xlim(*xlim)
    axb.set_ylim(*ylim_b)
    ds.draw_vtu_vtl_quadrants(axb, xlim, ylim_b, fontsize=11)
    axb.axhline(0.0, color="black", lw=1.0, zorder=2)
    axb.axvline(0.0, color="black", lw=1.0, zorder=2)
    draw_trajectory(axb, hours, valid, sm["hvtl"], sm["hvtu"], col["hvtl"], col["hvtu"], col["mslp_hpa"],
                    sm["hvtl_hart"] if have_h else None, sm["hvtu_hart"] if have_h else None)
    axb.set_xlabel(r"$-V_T^L$ (m)   925-700 hPa thermal wind" + (" (dashed: 900-600 hPa)" if have_h else ""),
                   fontsize=12)
    axb.set_ylabel(r"$-V_T^U$ (m)   500-300 hPa thermal wind" + (" (dashed: 600-300 hPa)" if have_h else ""),
                   fontsize=12)
    axb.set_title(r"(b) $-V_T^U$ against $-V_T^L$", loc="left", fontsize=14)
    for ax in (axa, axb):
        ax.grid(True, color=ds.GRID_COLOR, lw=0.5, zorder=0.2)
        ax.tick_params(labelsize=11)

    # (c) time series, raw 6-hourly values, class strip on top
    axc.plot(hours, col["hb"], "-", color=PURPLE, lw=1.8, label="B, steering-proxy motion")
    axc.plot(hours, col["hb_track"], ":", color=PURPLE, lw=1.8, label="B, track motion")
    axc.plot(hours, col["hvtl"], "-", color=RED, lw=1.8, label=r"$-V_T^L$ 925-700")
    axc.plot(hours, col["hvtu"], "-", color=BLUE, lw=1.8, label=r"$-V_T^U$ 500-300")
    if have_h:
        axc.plot(hours, col["hvtl_hart"], "--", color=RED, lw=1.5, label=r"$-V_T^L$ 900-600 (Hart)")
        axc.plot(hours, col["hvtu_hart"], "--", color=BLUE, lw=1.5, label=r"$-V_T^U$ 600-300 (Hart)")
    axc.axhline(0.0, color="black", lw=0.7)
    axc.axhline(B_THR, color=PURPLE, lw=0.6, ls=(0, (2, 3)))
    vals = np.concatenate([col[k] for k in ("hb", "hb_track", "hvtl", "hvtu", "hvtl_hart", "hvtu_hart")])
    vals = vals[np.isfinite(vals)]
    lo, hi = min(vals.min(), -20.0), max(vals.max(), 40.0)
    axc.set_ylim(lo - 0.05 * (hi - lo), hi + 0.08 * (hi - lo))
    axc.set_xlim(hours.min() - 3, hours.max() + 3)
    ticks = np.arange(hours.min(), hours.max() + 1, 24)
    axc.set_xticks(ticks)
    t0 = valid[0] - dt.timedelta(hours=float(hours[0]))
    axc.set_xticklabels([f"{int(h)}\n{t0 + dt.timedelta(hours=float(h)):%d/%H}Z" for h in ticks], fontsize=11)
    axc.tick_params(axis="y", labelsize=11)
    axc.set_xlabel("forecast hour, valid day/hour", fontsize=12)
    axc.set_ylabel("m", fontsize=12)
    axc.grid(True, color=ds.GRID_COLOR, lw=0.5)
    for key, ls in (("standard", "-"), ("hart", "--")):
        if key not in ev:
            continue
        on, comp = ev[key]
        for h, c in ((on, PURPLE), (comp, RED)):
            if np.isfinite(h):
                axc.axvline(h, color=c, ls=ls, lw=1.0, alpha=0.7)
    axc.legend(fontsize=10, loc="best", ncol=2, framealpha=0.9)
    strip = axc.inset_axes([0.0, 1.01, 1.0, 0.055], sharex=axc)
    for h, c in zip(hours, col["class"]):
        if np.isfinite(c):
            strip.add_patch(Rectangle((h - 3.0, 0.0), 6.0, 1.0, facecolor=CLASS_PALETTE[int(c)], edgecolor="none"))
    strip.set_ylim(0, 1)
    strip.set_yticks([])
    strip.tick_params(axis="x", labelbottom=False, bottom=False)
    strip.set_ylabel("class", rotation=0, ha="right", va="center", fontsize=11)
    strip.set_title("(c) parameters at the center, 6-hourly (not smoothed); HCPSclass strip on top",
                    loc="left", fontsize=14)

    # Title block, FSU style.
    c0 = g.cycle_time(cycle)
    a, z = fixes[0], fixes[-1]

    def pos(fx):
        return f"{abs(fx['lat']):.1f}{'N' if fx['lat'] >= 0 else 'S'} {abs(fx['lon']):.1f}{'W' if fx['lon'] < 0 else 'E'}"

    fig.text(0.045, 0.975, f"GFS 0.25 ({fsu_time(c0)} run) {name}, gridded CPS", fontsize=20, weight="bold",
             color="#138a13", va="top")
    fig.text(0.045, 0.925, f"Start (A): {fsu_time(a['valid'])} ({a['valid']:%a}) (+{a['fhr']}h)  {pos(a)}  "
             f"{a['mslp_hpa']:.0f} hPa        End (Z): {fsu_time(z['valid'])} ({z['valid']:%a}) (+{z['fhr']}h)  "
             f"{pos(z)}  {z['mslp_hpa']:.0f} hPa", fontsize=14, color="#d23c3c", va="top")
    evs = ["After the 24 h mean:"]
    for key, lab in (("standard", "standard bands, steering-proxy B"), ("hart", "Hart bands, track-motion B")):
        if key in ev:
            on, comp = ev[key]
            evs.append(f"{lab}: onset (B > 10) {'+%dh' % on if np.isfinite(on) else 'none'}, "
                       f"completion ($-V_T^L$ < 0) {'+%dh' % comp if np.isfinite(comp) else 'none'}")
    fig.text(0.045, 0.9, "\n".join(evs), fontsize=12, color="0.2", va="top", linespacing=1.3)

    # Legends and note along the bottom.
    inten = [Line2D([0], [0], marker="o", ls="none", markersize=11, markerfacecolor=c, markeredgecolor="black",
                    label=f"{s}") for s, c in INTENSITY[::-1]]
    fig.legend(handles=inten, loc="lower left", bbox_to_anchor=(0.045, 0.06), ncol=8, fontsize=11,
               title="MSLP (hPa)", title_fontsize=11, frameon=False, handletextpad=0.2, columnspacing=0.9)
    style = [Line2D([0], [0], marker="o", ls="none", markersize=11, markerfacecolor="0.6", markeredgecolor="k",
                    label="analysis (+0h)"),
             Line2D([0], [0], marker="x", ls="none", markersize=9, color="k", markeredgewidth=1.4,
                    label="forecast"),
             Line2D([0], [0], color="black", lw=2.0, label="24 h mean, 925-700 / 500-300 hPa, steering-proxy B"),
             Line2D([0], [0], color="0.45", lw=0.8, alpha=0.6, marker="o", markersize=3,
                    label="raw 6-hourly (same terms)")]
    if have_h:
        style.append(Line2D([0], [0], color="0.15", ls="--", lw=1.4, marker="D", markersize=5,
                            markerfacecolor="white", label="24 h mean, 900-600 / 600-300 hPa (Hart), track-motion B"))
    else:
        style.append(Line2D([0], [0], color="0.15", ls=":", lw=1.4, label="24 h mean, track-motion B"))
    fig.legend(handles=style, loc="lower left", bbox_to_anchor=(0.33, 0.05), ncol=2, fontsize=11, frameon=False)
    cls = [Rectangle((0, 0), 1, 1, facecolor=CLASS_PALETTE[k], label=f"{k} {CLASS_SHORT[k]}") for k in range(7)]
    cls.append(Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="0.6", label="no closed low"))
    fig.legend(handles=cls, loc="lower left", bbox_to_anchor=(0.66, 0.03), ncol=4, fontsize=10.5,
               title="HCPSclass at the center", title_fontsize=11, frameon=False)
    fig.text(0.045, 0.012, "NOTE: A 24hr running mean smoother is applied to the CPS trajectory in (a) and (b). "
             "Day of month at 00Z. Gridded products of cps_HartCPS.py on the GFS 0.25 degree grid, 500 km "
             "square-window thermal wind, semicircle B, sampled bilinearly at the tracked MSLP minimum.",
             fontsize=11, color="0.5", va="bottom")
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return ev


# ------------------------------------------------------------------ driver
def run(cycle: str, hours: list[int], region: str, outdir: Path, source: str, specs: list[str],
        hart: bool) -> int:
    """Fetch every frame (downloads run ahead in two threads), compute the
    products, advance every track; then B with the track motion, the CSVs
    and the figures."""
    if region != "global":
        print(f"note: region {region}: a track that leaves the box (plus margin) ends there; "
              "--region global has no edge")
    tracks = [Track(s) for s in specs]
    wrap = g.REGIONS[region] is None
    cache = outdir.parent / "cache" / cycle
    t0 = time.time()
    print(f"cycle {cycle}, region {region}, {len(hours)} hours, source {source}, hart bands {hart}, "
          f"tracks {', '.join(t.name for t in tracks)}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {h: pool.submit(g.get_grib, cycle, h, region, cache, source, hart) for h in sorted(hours)}
        for fhr in sorted(hours):
            if all(t.done for t in tracks):
                for fu in futs.values():
                    fu.cancel()
                break
            t1 = time.time()
            try:
                grib = futs[fhr].result()
            except Exception as exc:  # a late hour may not be posted yet
                print(f"  f{fhr:03d}: skipped ({exc})")
                continue
            f = g.decode(grib, region, hart)
            t2 = time.time()
            p = g.compute_products(f)
            if hart:
                p.update(g.compute_hart_bands(f))
            p["closed"] = closed_mask(f)
            for tr in tracks:
                sample_frame(tr, f, p, fhr, wrap)
            merge_close(tracks, fhr)
            where = "; ".join(f"{t.name} {t.fixes[-1]['lat']:.1f},{t.fixes[-1]['lon']:.1f} "
                              f"{t.fixes[-1]['mslp_hpa']:.0f}" for t in tracks
                              if t.fixes and t.fixes[-1]["fhr"] == fhr)
            print(f"  f{fhr:03d}: wait+decode {t2 - t1:.1f} s, compute+track {time.time() - t2:.1f} s   {where}")
    for tr in tracks:
        if not tr.fixes:
            why = tr.end_reason if tr.merged else f"no low found near {tr.lat},{tr.lon} at f{tr.fhr0:03d}"
            print(f"{tr.name}: {why}; nothing written")
            continue
        track_motion(tr.fixes)
        b_with_track_motion(tr.fixes)
        chk = np.array([fx["hb"] - fx["hb_sub_check"] for fx in tr.fixes])
        write_csv(outdir / f"track_{tr.name}.csv", tr.fixes)
        ev = plot_phase(outdir / f"phase_{tr.name}.png", tr.name, cycle, tr.fixes, hart)
        dh = np.array([((fx["steering_heading_deg"] - fx["heading_deg"] + 180.0) % 360.0) - 180.0
                       for fx in tr.fixes])
        fast = np.array([fx["motion_kt"] >= 5.0 and fx["steering_kt"] >= 5.0 for fx in tr.fixes])
        dfast = dh[fast & np.isfinite(dh)]
        dh = dh[np.isfinite(dh)]
        if dfast.size:
            print(f"{tr.name}: with both motions at least 5 kt ({dfast.size} fixes): steering minus track heading "
                  f"mean {dfast.mean():+.1f}, mean abs {np.abs(dfast).mean():.1f}, max abs {np.abs(dfast).max():.1f} deg")
        print(f"{tr.name}: {len(tr.fixes)} fixes f{tr.fixes[0]['fhr']:03d}-f{tr.fixes[-1]['fhr']:03d}; "
              f"subgrid B check max |diff| {np.nanmax(np.abs(chk)):.2e} m; steering minus track heading "
              f"mean {dh.mean():+.1f}, mean abs {np.abs(dh).mean():.1f}, max abs {np.abs(dh).max():.1f} deg; "
              + "; ".join(f"{k}: onset {on:g} h, completion {cp:g} h" for k, (on, cp) in ev.items()))
    print(f"done in {time.time() - t0:.1f} s, output in {outdir}")
    return 0
