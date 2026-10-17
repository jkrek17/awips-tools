#!/usr/bin/env python3
"""Build the marine wind page's data for one model cycle.

For each lead time this computes, on the basin's 0.25 degree grid (--domain natl for the
North Atlantic, npac for the North Pacific; see domain.py):

    wind      base + min(k * sigma, 5 kt), the blend tested on 345 hindcast cases
              (k = 0.25; 0.15 at +24 h and earlier)
    mean      the base: GFS, ECMWF and AIFS speeds weighted at each point by member
              support (the share of members within about 5 kt of each model)
    boost     the added wind, min(k * sigma, 5 kt)
    sigma     standard deviation of the GEFS + ENS member speeds (about 80)
    gfs, ecmwf, aifs   each model's speed
    p34, p48, p64      chance of gale, storm, hurricane force from the GEFS + ENS members plus
                       the AIFS ensemble (51) when it is posted: the share of members recalibrated
                       to how often it verified in the 2025-26 hindcast (calibration.json: 34 and
                       48 kt against ASCAT since 17 Oct 2026, 64 kt against analyses; the raw shares
                       stay in p34raw, p48raw, p64raw, and the hazard lines use the raw shares)
    trend     change of the 3-model mean since the 12Z/00Z run 24 h earlier, valid at the
              same time (the truth fell back about a fifth of this change in the hindcast)
    nomem     the deterministic blend, a candidate for GFE where the ensemble members may not be
              available: the 3 models weighted by support among 9 runs (these 3 and the same
              models from the runs 12 h and 24 h earlier, valid at the same time) +
              min(0.3 x spread of the 9, 5 kt). On 265 hindcast cases it kept about 90% of
              the member blend's gain against the analyses but only about 40% of its gale
              hits at ships and buoys.
    nomemdiff nomem minus wind
    focus     0 ride (all models < 30 kt), 1 agree, 2 focus (models split across
              34 kt, or a 10 kt range near gale), 3 high impact (split across 48 or 64)
    lone      a single model at storm (48) or hurricane (64) force that the other
              two do not have anywhere within about 50 km
    dir       direction the wind blows from, from the 3-model mean wind vector
    msl       3-model mean sea-level pressure
    core      storm layers (storm.py): chance (%) that ASCAT sees 48+ kt within ~50 km
    windcore  Core Lifted: wind + 5 kt where core >= 35% (the most likely wind with storm cores kept)
    hazard    bit 1 gale possible, bit 2 storm possible, bit 4 hurricane force possible
              (plus tracks.json: the ensemble low tracks with central pressure and cone size)

and writes OUT/manifest.json plus one OUT/fFFF.bin per lead (uint8 fields,
row-major, north row first, in the order of manifest["fields"]).

    python3 build.py --out site_data                # newest complete cycle, North Atlantic
    python3 build.py --domain npac --out site_data/npac
    python3 build.py --cycle 2026101312 --out site_data

--domain glob builds the whole globe, the page's grid since Oct 2026, and writes each field
on its own (OUT/fFFF/NAME.gz: one uint8 byte per cell, each row stored as differences from
the cell to its west, gzipped; see write_global). --boxes DIR also cuts the two OPC boxes from
it in the older per-basin format into DIR/ (North Atlantic) and DIR/npac/, without fetching
anything again:

    python3 build.py --domain glob --out site_data/global --boxes site_data
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import gzip
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# the basin must be known before domain.py is imported (fetch.py crops with it)
if "--domain" in sys.argv:
    os.environ["MARINE_DOMAIN"] = sys.argv[sys.argv.index("--domain") + 1]
import fetch  # noqa: E402
import storm  # noqa: E402
from domain import BASIN, BASINS, EAST, GLOBAL, KEY, LATS, LONS, NORTH, NX, NY, SOUTH, TESTED, WEST  # noqa: E402

KT = 1.943844
STEPS = list(range(6, 121, 6))   # every 6 h (Jason 2026-10-16; was 12 h)
MODELS = ("GFS", "ECMWF", "AIFS")
CAP_KT = 5.0
RIDE_BELOW, SPREAD_KT, TOL_CELLS = 30.0, 10.0, 2
SUPPORT_KT = 5.0
NOMEM_K = 0.3         # chosen leave-one-cycle-out for the 9-run spread; 0.3 in every fold

TREND_OFFSET = 64.0   # trend is stored as (kt + 64) x 2, so -64..+63.5 kt

# name, scale (stored = round((value + offset) * scale)), unit, description[, offset]
FIELDS = [
    ("wind", 2, "kt", "Blended wind: support-weighted 3-model base + min(k x member spread, 5 kt)"),
    ("dir", 0.5, "deg", "Direction the wind blows from (3-model mean vector)"),
    ("mean", 2, "kt", "Base: 3 models weighted by member support"),
    ("boost", 20, "kt", "Added wind"),
    ("sigma", 4, "kt", "Member spread (std dev of all GEFS and ENS members)"),
    ("gfs", 2, "kt", "GFS"),
    ("ecmwf", 2, "kt", "ECMWF"),
    ("aifs", 2, "kt", "AIFS"),
    ("p34", 1, "%", "Chance of 34 kt or more (member share, recalibrated)"),
    ("p48", 1, "%", "Chance of 48 kt or more (member share, recalibrated)"),
    ("p64", 1, "%", "Chance of 64 kt or more (member share, recalibrated)"),
    ("p48raw", 1, "%", "Members at 48 kt or more"),
    ("p64raw", 1, "%", "Members at 64 kt or more"),
    ("trend", 2, "kt", "Change of the 3-model mean since the run 24 h earlier", TREND_OFFSET),
    ("nomem", 2, "kt", "Deterministic blend: 3 models weighted by support among 9 lagged runs + min(0.3 x their spread, 5 kt)"),
    ("nomemdiff", 2, "kt", "Deterministic blend minus the blended wind", TREND_OFFSET),
    ("focus", 1, "", "0 ride, 1 agree, 2 focus, 3 high impact"),
    ("lone", 1, "", "Lone model: bits 0-1 at 48 kt, bits 2-3 at 64 kt (1 GFS, 2 ECMWF, 3 AIFS)"),
    ("msl", 1, "hPa-900", "3-model mean sea-level pressure minus 900 hPa"),
    ("core", 1, "%", "Core likelihood: chance of 48+ kt within about 50 km (ASCAT-trained)"),
    ("windcore", 2, "kt", "Core Lifted (most likely wind, storm cores kept): wind + 5 kt where core likelihood >= 35%"),
    ("hazard", 1, "", "Possible: bit 1 gale (30%+ of members 34+), bit 2 storm (core 30%+), bit 4 hurricane force (core 90%+ and 30%+ of members 48+)"),
    ("p34raw", 1, "%", "Members at 34 kt or more"),
]
TRACK_STEPS = (24, 48, 72, 96, 120)
RECORD_STEPS = (24, 48, 72, 96, 120)   # leads kept for the verification (--record)
# extra leads cut into the two OPC boxes only (--boxes), not the global page. Empty since STEPS went
# 6-hourly: STEPS alone give the High Seas draft its C+6 h synopsis (the 00Z run -> the 06Z synopsis
# forecast due 1030Z) and its 6 h steps
BOX_STEPS = ()
CORE_MODEL = storm.load_model()
storm.WRAP = GLOBAL   # the global grid wraps round the date line


CALIB = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")))
# the filters wrap round the date line on the global grid
FMODE = ("reflect", "wrap") if GLOBAL else "reflect"


def in_box(box, lats=None, lons=None):
    """[y, x] mask of the cells of this grid inside a box (longitudes continuous, west < east)."""
    lats = LATS if lats is None else lats
    lons = LONS if lons is None else lons
    lat_ok = (lats >= box["south"]) & (lats <= box["north"])
    lon_ok = (lons - box["west"]) % 360 <= box["east"] - box["west"]
    return lat_ok[:, None] & lon_ok[None, :]


def calibrate(pct, thr, step):
    """Member share (%) -> chance (%) from the hindcast table for this basin and lead.
    On the global grid each OPC box uses its own basin's table and everywhere else the
    average of the two (untested there)."""
    g = "le48" if step <= 48 else ("72" if step <= 84 else "ge96")
    tab = CALIB["thresholds"][str(thr)]
    cal = {b: np.interp(pct, tab[b][g]["raw"], tab[b][g]["cal"]) for b in ("natl", "npac")}
    if not GLOBAL:
        return cal[KEY]
    out = (cal["natl"] + cal["npac"]) / 2
    for b in ("natl", "npac"):
        m = in_box(BASINS[b])
        out[m] = cal[b][m]
    return out


def k_for(step):
    return 0.15 if step <= 24 else 0.25


def focus_grid(speeds):
    """speeds [3, y, x] kt -> 0 ride / 1 agree / 2 focus / 3 high impact.
    A model only counts as disagreeing if it has no such wind within TOL_CELLS,
    so a gale edge drawn 25 km differently is not flagged."""
    cats = (34.0, 48.0, 64.0)
    mx = speeds.max(0)
    near = np.array([ndimage.maximum_filter(s, size=2 * TOL_CELLS + 1, mode=FMODE) for s in speeds])
    cmax, cmin = np.digitize(speeds, cats).max(0), np.digitize(near, cats).min(0)
    out = np.ones(mx.shape, np.uint8)
    out[mx < RIDE_BELOW] = 0
    out[((cmax >= 1) & (cmin == 0)) | ((mx - near.min(0) >= SPREAD_KT) & (mx >= RIDE_BELOW))] = 2
    out[(cmax >= 2) & (cmin < cmax)] = 3
    return out


def support_base(speeds, members):
    """Weight each model at each point by the share of members near its speed
    (Gaussian kernel, SUPPORT_KT wide), so a run out on its own counts for less.
    On 200 out-of-sample cases this cut error at 25+ kt by about 0.1 kt against
    the equal-weight mean and kept or added gale hits."""
    w = np.array([np.exp(-0.5 * ((members - s[None]) / SUPPORT_KT) ** 2).mean(0) for s in speeds]) + 1e-6
    return (w * speeds).sum(0) / w.sum(0)


def lone_flags(speeds):
    """Bits 0-1: the one model (1-3) at >= 48 kt where neither other model has 48 kt
    within TOL_CELLS; bits 2-3: the same at 64 kt."""
    out = np.zeros(speeds.shape[1:], np.uint8)
    for shift, thr in ((0, 48.0), (2, 64.0)):
        has = speeds >= thr
        near = np.array([ndimage.maximum_filter(h, size=2 * TOL_CELLS + 1, mode=FMODE) for h in has])
        for i in range(3):
            others = [j for j in range(3) if j != i]
            lone = has[i] & ~near[others[0]] & ~near[others[1]]
            out[lone] |= np.uint8((i + 1) << shift)
    return out


def centres(msl):
    """H and L labels: ['L'|'H', lat, lon, hPa] at the extreme of a ~6 degree box
    that stands at least 2 hPa off the box mean, away from the domain edge (on the global grid: within 80 degrees of the equator)."""
    out = []
    size, edge = 25, 4
    mode = ("nearest", "wrap") if GLOBAL else "nearest"
    mean = ndimage.uniform_filter(msl, size=size, mode=mode)
    for kind, ext, sign in (("L", ndimage.minimum_filter(msl, size=size, mode=mode), -1),
                            ("H", ndimage.maximum_filter(msl, size=size, mode=mode), 1)):
        hit = (msl == ext) & (sign * (msl - mean) >= 2.0)
        if GLOBAL:
            hit[np.abs(LATS) > 80] = False
        else:
            hit[:edge] = hit[-edge:] = False
            hit[:, :edge] = hit[:, -edge:] = False
        for j, i in zip(*np.nonzero(hit)):
            out.append([kind, round(float(LATS[j]), 2), round(float(LONS[i]), 2), round(float(msl[j, i]), 1)])
    return out


def prior_speeds(ymd, hh, step, hours):
    """GFS, ECMWF, AIFS speeds [3, y, x] from the run `hours` earlier at the same valid time, or None."""
    p = dt.datetime.strptime(ymd + hh, "%Y%m%d%H") - dt.timedelta(hours=hours)
    py, ph, s = p.strftime("%Y%m%d"), p.strftime("%H"), step + hours
    try:
        with ThreadPoolExecutor(3) as ex:
            dets = [f.result() for f in (ex.submit(fetch.gfs, py, ph, s), ex.submit(fetch.ec_det, "ifs", py, ph, s),
                                         ex.submit(fetch.ec_det, "aifs-single", py, ph, s))]
    except Exception as e:
        print("run %dh earlier +%dh unavailable: %s" % (hours, s, e), flush=True)
        return None
    if any(d is None for d in dets):
        return None
    return np.array([np.hypot(d["u"], d["v"]) * KT for d in dets])


def nomem_blend(speeds, lagged):
    """The deterministic blend from the 3 current models and the lagged runs that are there."""
    runs = np.concatenate([speeds] + lagged)
    return support_base(speeds, runs) + np.minimum(NOMEM_K * runs.std(0), CAP_KT)


def pack(vals):
    """The page's fields as uint8 grids, one per FIELDS entry."""
    return np.stack([np.clip(np.rint((vals[f[0]] + (f[4] if len(f) > 4 else 0)) * f[1]), 0, 255).astype(np.uint8)
                     for f in FIELDS])


def step_fields(ymd, hh, step):
    vals, stats, _ = step_values(ymd, hh, step)
    return pack(vals), stats


def step_values(ymd, hh, step):
    """The page's fields at one lead as float grids (vals), the run's stats, and extras the
    verification page scores but the page does not show: each ensemble's mean wind (the speed
    of the members' mean u and v, as AWIPS shows an ensemble mean)."""
    with ThreadPoolExecutor(12) as ex:
        lag_f = [ex.submit(prior_speeds, ymd, hh, step, h) for h in (12, 24)]   # alongside this run's fetches
        track = step in TRACK_STEPS   # members' MSL only where the low track has a point
        det_f = [ex.submit(fetch.gfs, ymd, hh, step), ex.submit(fetch.ec_det, "ifs", ymd, hh, step),
                 ex.submit(fetch.ec_det, "aifs-single", ymd, hh, step)]
        low_f = [ex.submit(fetch.gfs_low, ymd, hh, step), ex.submit(fetch.ec_low, "ifs", ymd, hh, step),
                 ex.submit(fetch.ec_low, "aifs-single", ymd, hh, step)]
        gefs_f = [ex.submit(fetch.gefs, ymd, hh, step, m, track) for m in fetch.GEFS_MEMBERS]
        ens_f = ex.submit(fetch.ec_ens, ymd, hh, step, "ifs", track)
        aens_f = ex.submit(fetch.ec_ens, ymd, hh, step, "aifs-ens")
        dets = [f.result() for f in det_f]
        lowx = [f.result() for f in low_f]
        gefs = [f.result() for f in gefs_f]
        ens = ens_f.result()
        try:
            aens = aens_f.result()
        except Exception as e:  # optional: probabilities fall back to GEFS + ENS
            print("AIFS ensemble +%dh unavailable: %s" % (step, e), flush=True)
            aens = None
        lag12, lag24 = [f.result() for f in lag_f]
    prev = None if lag24 is None else lag24.mean(0)
    if any(d is None for d in dets):
        raise RuntimeError("missing deterministic model at +%dh" % step)
    gefs = [g for g in gefs if g is not None]
    mu = [g["u"] for g in gefs] + (list(ens["u"]) if ens else [])
    mv = [g["v"] for g in gefs] + (list(ens["v"]) if ens else [])
    if len(mu) < 20:
        raise RuntimeError("only %d members at +%dh" % (len(mu), step))
    members = np.hypot(np.array(mu), np.array(mv)) * KT
    speeds = np.array([np.hypot(d["u"], d["v"]) * KT for d in dets])
    mean = support_base(speeds, members)
    sigma = members.std(0)
    # The AIFS ensemble sharpens the 34/48/64 kt chances (Brier score 6% and 11%
    # better on 265 hindcast cases) but its smaller spread and smoother mean did not
    # help the wind itself, so it feeds only the probabilities.
    pmem = members if aens is None else np.concatenate([members, np.hypot(aens["u"], aens["v"]) * KT])
    boost = np.minimum(k_for(step) * sigma, CAP_KT)
    u = np.mean([d["u"] for d in dets], 0)
    v = np.mean([d["v"] for d in dets], 0)
    wdir = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
    msl = np.mean([d["msl"] for d in dets], 0) / 100.0
    p34raw, p48raw, p64raw = (100 * (pmem >= t).mean(0) for t in (34, 48, 64))
    trend = np.zeros_like(mean) if prev is None else speeds.mean(0) - prev
    lagged = [x for x in (lag12, lag24) if x is not None]
    nomem = nomem_blend(speeds, lagged)
    # storm layers: core likelihood, Core Lifted wind, possible areas, low positions for the track
    core, windcore, hazard, lows = core_layers(step, mean + boost, boost, speeds, members, aens, lowx, dets, gefs, ens)
    vals = {
        "wind": mean + boost, "dir": wdir, "mean": mean, "boost": boost, "sigma": sigma,
        "gfs": speeds[0], "ecmwf": speeds[1], "aifs": speeds[2],
        "p34": calibrate(p34raw, 34, step), "p48": calibrate(p48raw, 48, step), "p64": calibrate(p64raw, 64, step),
        "p34raw": p34raw, "p48raw": p48raw, "p64raw": p64raw, "trend": trend,
        "nomem": nomem, "nomemdiff": nomem - (mean + boost),
        "focus": focus_grid(speeds), "lone": lone_flags(speeds), "msl": msl - 900.0,
        "core": 100 * core, "windcore": windcore, "hazard": hazard,
    }
    stats = dict(step=step, members=len(mu), gefs=len(gefs), ens=0 if ens is None else len(ens["u"]),
                 aifs_ens=0 if aens is None else len(aens["u"]), prob_members=len(pmem), trend=prev is not None,
                 nomem_runs=3 * (1 + len(lagged)),
                 max_wind=round(float(vals["wind"].max()), 1), gale_cells=int((vals["wind"] >= 34).sum()),
                 focus_cells=int((vals["focus"] >= 2).sum()), lone_cells=int((vals["lone"] > 0).sum()),
                 centres=centres(msl), core_model=all(x is not None for x in lowx), lows=lows,
                 storm_cells=int(((hazard & 2) > 0).sum()), hf_cells=int(((hazard & 4) > 0).sum()))
    extra = {"gefs_mean": np.hypot(np.mean([g["u"] for g in gefs], 0), np.mean([g["v"] for g in gefs], 0)) * KT,
             "ens_mean": None if ens is None else np.hypot(ens["u"].mean(0), ens["v"].mean(0)) * KT,
             "aifsens_mean": None if aens is None else np.hypot(aens["u"].mean(0), aens["v"].mean(0)) * KT}
    return vals, stats, extra


def core_layers(step, wind, boost, speeds, members, aens, lowx, dets, gefs, ens):
    """Core likelihood (0-1), Core Lifted wind, hazard bits and (at track leads) low positions.
    Without the extra low-level fields the core is left at 0, so windcore = wind and only the
    gale line is drawn."""
    core = np.zeros(wind.shape, np.float32)
    ocean = np.ones(wind.shape, bool)
    if all(x is not None for x in lowx):
        low = {k: np.mean([x[k] for x in lowx], 0) for k in ("t2", "skt", "t925", "t850")}
        for k in ("u925", "v925", "u850", "v850"):
            low[k] = np.mean([x[k] for x in lowx], 0) * KT
        ocean = (lowx[0]["land"] < 0.5) & ~(lowx[0]["ice"] >= 0.5)
        asp = None if aens is None else np.hypot(aens["u"], aens["v"]) * KT
        # the core model was trained on 30-67N only, with latitude an input: the Southern
        # Hemisphere uses |lat|, and the tropics (|lat| < 25, tropical cyclones) get no core,
        # so no core lift and no storm or hurricane-force line there; the gale line stays
        feats = storm.core_features(np.abs(LATS), wind, boost, speeds, members, asp, low)
        core = storm.core_grid(feats, ocean, CORE_MODEL)
        core[np.abs(LATS) < 25] = 0
    else:
        print("core +%dh: low-level fields missing" % step, flush=True)
    windcore, hazard = storm.products(wind, core, members)
    hazard = np.where(ocean, hazard, 0).astype(np.uint8)
    lows = []
    if step in TRACK_STEPS:
        mem_msl = [g["msl"] / 100.0 for g in gefs if "msl" in g] + ([] if ens is None or "msl" not in ens else list(ens["msl"] / 100.0))
        if len(mem_msl) >= 20:
            lows = storm.step_lows(LATS, LONS, [d["msl"] / 100.0 for d in dets], speeds, mem_msl)
    return core, windcore, hazard, lows


def newest_cycle(now=None):
    """Newest 00/06/12/18Z cycle whose +120 h is on AWS for all three models and the ENS."""
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    t = now.replace(minute=0, second=0, microsecond=0, hour=now.hour // 6 * 6)
    for _ in range(12):
        ymd, hh = t.strftime("%Y%m%d"), t.strftime("%H")
        urls = [fetch.gfs_url(ymd, hh, 120) + ".idx", fetch.ec_url("ifs", ymd, hh, 120),
                fetch.ec_url("aifs-single", ymd, hh, 120), fetch.ec_url("ifs", ymd, hh, 120, "enfo", "ef")]
        if all(fetch.exists(u) for u in urls):
            return ymd + hh
        t -= dt.timedelta(hours=6)
    raise RuntimeError("no complete cycle in the last three days")


def write_global(out, step, packed):
    """One file per field, OUT/fFFF/NAME.gz: each row as differences from the cell to its west
    (uint8, wrapping), gzipped. The page undoes it with a running sum along each row. The
    differences make wind fields about 15% smaller than gzip alone, about as small as PNG."""
    d = os.path.join(out, "f%03d" % step)
    os.makedirs(d, exist_ok=True)
    for f, a in zip(FIELDS, packed):
        diff = np.diff(a, axis=1, prepend=np.uint8(0)).astype(np.uint8)
        with open(os.path.join(d, f[0] + ".gz"), "wb") as fh:
            fh.write(gzip.compress(diff.tobytes(), 6, mtime=0))


def field_list():
    return [dict(name=f[0], scale=f[1], unit=f[2], desc=f[3], offset=f[4] if len(f) > 4 else 0) for f in FIELDS]


def write_boxes(root, base, steps, packs):
    """Cut the two OPC boxes from the global build, in the older per-basin format
    (root/ North Atlantic, root/npac/ North Pacific: manifest.json + fFFF.bin)."""
    wind = [f[0] for f in FIELDS].index("wind")
    focus, lone = [f[0] for f in FIELDS].index("focus"), [f[0] for f in FIELDS].index("lone")
    for key in ("natl", "npac"):
        b = BASINS[key]
        out = root if key == "natl" else os.path.join(root, "npac")
        os.makedirs(out, exist_ok=True)
        iy = slice(int(round((NORTH - b["north"]) * 4)), int(round((NORTH - b["south"]) * 4)) + 1)
        ix = (int(round((b["west"] - WEST) * 4)) + np.arange(int(round((b["east"] - b["west"]) * 4)) + 1)) % NX
        bsteps = []
        for st, packed in zip(steps, packs):
            crop = packed[:, iy][:, :, ix]
            with open(os.path.join(out, "f%03d.bin" % st["step"]), "wb") as f:
                f.write(np.ascontiguousarray(crop).tobytes())
            w = crop[wind] / 2.0
            cs = [c for c in st["centres"] if b["south"] <= c[1] <= b["north"] and (c[2] - b["west"]) % 360 <= b["east"] - b["west"]]
            cs = [[c[0], c[1], c[2] % 360 if key == "npac" else c[2], c[3]] for c in cs]   # npac runs 135-245
            st = {k: v for k, v in st.items() if k != "lows"}   # low positions are global grid indices
            bsteps.append(dict(st, max_wind=round(float(w.max()), 1), gale_cells=int((w >= 34).sum()),
                               focus_cells=int((crop[focus] >= 2).sum()), lone_cells=int((crop[lone] > 0).sum()), centres=cs))
        manifest = dict(basin=key, basin_name=b["name"], cycle=base.strftime("%Y-%m-%dT%H:00Z"),
                        built=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%MZ"),
                        grid=dict(north=b["north"], south=b["south"], west=b["west"], east=b["east"],
                                  ny=iy.stop - iy.start, nx=len(ix), res=0.25),
                        fields=field_list(), cap_kt=CAP_KT, steps=bsteps)
        with open(os.path.join(out, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycle", help="YYYYMMDDHH (default: newest complete 00/06/12/18Z cycle)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--domain", default=KEY, choices=list(BASINS), help="glob, natl or npac (default natl)")
    ap.add_argument("--boxes", help="with --domain glob: also write the two OPC boxes in the per-basin format here")
    ap.add_argument("--record", help="with --domain glob: also keep each lead in RECORD_STEPS (vals, extras, stats) here, for the verification")
    a = ap.parse_args()
    if a.boxes and not GLOBAL:
        ap.error("--boxes needs --domain glob")
    if a.record and not GLOBAL:
        ap.error("--record needs --domain glob")
    cycle = a.cycle or newest_cycle()
    ymd, hh = cycle[:8], cycle[8:]
    os.makedirs(a.out, exist_ok=True)
    base = dt.datetime.strptime(cycle, "%Y%m%d%H")
    steps, packs = [], []
    bsteps, bpacks = [], []   # what the boxes get: STEPS plus BOX_STEPS
    for step in sorted(set(STEPS) | (set(BOX_STEPS) if a.boxes else set())):
        page = step in STEPS
        path = os.path.join(a.out, "f%03d.bin" % step)
        done = os.path.join(a.out, "f%03d.json" % step)
        if os.path.exists(done) and (GLOBAL or os.path.exists(path)):  # resume a partial run of the same cycle
            st = json.load(open(done))
            if st.get("cycle") == cycle:
                pk = np.load(path + ".npy") if a.boxes else None
                if page:
                    steps.append(st)
                    packs.append(pk)
                bsteps.append(st)
                bpacks.append(pk)
                continue
        vals, stats, extra = step_values(ymd, hh, step)
        packed = pack(vals)
        if GLOBAL:
            if page:
                write_global(a.out, step, packed)
            if a.boxes:   # kept until the boxes are cut, then removed
                np.save(path + ".npy", packed)
        else:
            with open(path, "wb") as f:
                f.write(packed.tobytes())
        stats["valid"] = (base + dt.timedelta(hours=step)).strftime("%Y-%m-%dT%H:00Z")
        stats["k"] = k_for(step)
        stats["cycle"] = cycle
        if page:
            steps.append(stats)
            packs.append(packed if a.boxes else None)
        bsteps.append(stats)
        bpacks.append(packed if a.boxes else None)
        with open(done, "w") as f:
            json.dump(stats, f)
        if a.record and page and step in RECORD_STEPS:
            try:
                import record
                record.save(a.record, cycle, step, vals, stats, extra)
            except Exception as e:   # never fails the build
                print("forecast record +%dh not saved: %s" % (step, e), flush=True)
        print("+%03dh members %d max %.0f kt gale cells %d focus %d lone %d" % (
            step, stats["members"], stats["max_wind"], stats["gale_cells"], stats["focus_cells"], stats["lone_cells"]), flush=True)
    for st in bsteps:
        st.pop("cycle", None)
    tracks = storm.link_tracks(LATS, LONS, {s["step"]: s.get("lows", []) for s in steps if s["step"] in TRACK_STEPS})
    track_doc = dict(cycle=base.strftime("%Y-%m-%dT%H:00Z"), tracks=tracks,
                     note="Ensemble low track: median of the GEFS+ENS members' own lows; cone_km holds the analysed low about 2 in 3")
    with open(os.path.join(a.out, "tracks.json"), "w") as f:
        json.dump(track_doc, f)
    grid = dict(north=NORTH, south=SOUTH, west=WEST, east=EAST, ny=NY, nx=NX, res=0.25)
    if GLOBAL:
        grid["tested"] = TESTED
    manifest = dict(
        basin=KEY, basin_name=BASIN["name"],
        cycle=base.strftime("%Y-%m-%dT%H:00Z"), built=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%MZ"),
        grid=grid, fields=field_list(), cap_kt=CAP_KT, steps=steps, tracks="tracks.json")
    if GLOBAL:
        manifest["format"] = "fFFF/NAME.gz, rows as west-to-east differences, gzipped"
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    if a.boxes:
        write_boxes(a.boxes, base, bsteps, bpacks)
        for step in set(STEPS) | set(BOX_STEPS):
            p = os.path.join(a.out, "f%03d.bin.npy" % step)
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    main()
