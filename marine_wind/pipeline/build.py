#!/usr/bin/env python3
"""Build the marine wind page's data for one model cycle.

For each lead time this computes, on the 0.25 degree North Atlantic grid:

    wind      mean(GFS, ECMWF, AIFS speed) + min(k * sigma, 5 kt), the blend
              tested on 345 hindcast cases (k = 0.25; 0.15 at +24 h and earlier)
    mean      the plain 3-model mean speed
    boost     the added wind, min(k * sigma, 5 kt)
    sigma     standard deviation of the GEFS + ENS member speeds (about 80)
    gfs, ecmwf, aifs   each model's speed
    p34, p48, p64      share of members at or above gale, storm, hurricane force
    focus     0 ride (all models < 30 kt), 1 agree, 2 focus (models split across
              34 kt, or a 10 kt range near gale), 3 high impact (split across 48 or 64)
    lone      a single model at storm (48) or hurricane (64) force that the other
              two do not have anywhere within about 50 km
    dir       direction the wind blows from, from the 3-model mean wind vector
    msl       3-model mean sea-level pressure

and writes OUT/manifest.json plus one OUT/fFFF.bin per lead (uint8 fields,
row-major, north row first, in the order of manifest["fields"]).

    python3 build.py --out site_data                # newest complete cycle
    python3 build.py --cycle 2026101312 --out site_data
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch  # noqa: E402
from domain import EAST, NORTH, NX, NY, SOUTH, WEST  # noqa: E402

KT = 1.943844
STEPS = list(range(12, 121, 12))
MODELS = ("GFS", "ECMWF", "AIFS")
CAP_KT = 5.0
RIDE_BELOW, SPREAD_KT, TOL_CELLS = 30.0, 10.0, 2

# name, scale (stored = round(value * scale)), unit, description
FIELDS = [
    ("wind", 2, "kt", "Blended wind: 3-model mean + min(k x member spread, 5 kt)"),
    ("dir", 0.5, "deg", "Direction the wind blows from (3-model mean vector)"),
    ("mean", 2, "kt", "Plain 3-model mean"),
    ("boost", 20, "kt", "Added wind"),
    ("sigma", 4, "kt", "Member spread (std dev of all GEFS and ENS members)"),
    ("gfs", 2, "kt", "GFS"),
    ("ecmwf", 2, "kt", "ECMWF"),
    ("aifs", 2, "kt", "AIFS"),
    ("p34", 1, "%", "Members at 34 kt or more"),
    ("p48", 1, "%", "Members at 48 kt or more"),
    ("p64", 1, "%", "Members at 64 kt or more"),
    ("focus", 1, "", "0 ride, 1 agree, 2 focus, 3 high impact"),
    ("lone", 1, "", "Lone model: bits 0-1 at 48 kt, bits 2-3 at 64 kt (1 GFS, 2 ECMWF, 3 AIFS)"),
    ("msl", 1, "hPa-900", "3-model mean sea-level pressure minus 900 hPa"),
]


def k_for(step):
    return 0.15 if step <= 24 else 0.25


def focus_grid(speeds):
    """speeds [3, y, x] kt -> 0 ride / 1 agree / 2 focus / 3 high impact.
    A model only counts as disagreeing if it has no such wind within TOL_CELLS,
    so a gale edge drawn 25 km differently is not flagged."""
    cats = (34.0, 48.0, 64.0)
    mx = speeds.max(0)
    near = np.array([ndimage.maximum_filter(s, size=2 * TOL_CELLS + 1) for s in speeds])
    cmax, cmin = np.digitize(speeds, cats).max(0), np.digitize(near, cats).min(0)
    out = np.ones(mx.shape, np.uint8)
    out[mx < RIDE_BELOW] = 0
    out[((cmax >= 1) & (cmin == 0)) | ((mx - near.min(0) >= SPREAD_KT) & (mx >= RIDE_BELOW))] = 2
    out[(cmax >= 2) & (cmin < cmax)] = 3
    return out


def lone_flags(speeds):
    """Bits 0-1: the one model (1-3) at >= 48 kt where neither other model has 48 kt
    within TOL_CELLS; bits 2-3: the same at 64 kt."""
    out = np.zeros(speeds.shape[1:], np.uint8)
    for shift, thr in ((0, 48.0), (2, 64.0)):
        has = speeds >= thr
        near = np.array([ndimage.maximum_filter(h, size=2 * TOL_CELLS + 1) for h in has])
        for i in range(3):
            others = [j for j in range(3) if j != i]
            lone = has[i] & ~near[others[0]] & ~near[others[1]]
            out[lone] |= np.uint8((i + 1) << shift)
    return out


def centres(msl):
    """H and L labels: ['L'|'H', lat, lon, hPa] at the extreme of a ~6 degree box
    that stands at least 2 hPa off the box mean, away from the domain edge."""
    from domain import LATS, LONS
    out = []
    size, edge = 25, 4
    mean = ndimage.uniform_filter(msl, size=size, mode="nearest")
    for kind, ext, sign in (("L", ndimage.minimum_filter(msl, size=size, mode="nearest"), -1),
                            ("H", ndimage.maximum_filter(msl, size=size, mode="nearest"), 1)):
        hit = (msl == ext) & (sign * (msl - mean) >= 2.0)
        hit[:edge] = hit[-edge:] = False
        hit[:, :edge] = hit[:, -edge:] = False
        for j, i in zip(*np.nonzero(hit)):
            out.append([kind, round(float(LATS[j]), 2), round(float(LONS[i]), 2), round(float(msl[j, i]), 1)])
    return out


def step_fields(ymd, hh, step):
    with ThreadPoolExecutor(12) as ex:
        det_f = [ex.submit(fetch.gfs, ymd, hh, step), ex.submit(fetch.ec_det, "ifs", ymd, hh, step),
                 ex.submit(fetch.ec_det, "aifs-single", ymd, hh, step)]
        gefs_f = [ex.submit(fetch.gefs, ymd, hh, step, m) for m in fetch.GEFS_MEMBERS]
        ens_f = ex.submit(fetch.ec_ens, ymd, hh, step)
        dets = [f.result() for f in det_f]
        gefs = [f.result() for f in gefs_f]
        ens = ens_f.result()
    if any(d is None for d in dets):
        raise RuntimeError("missing deterministic model at +%dh" % step)
    gefs = [g for g in gefs if g is not None]
    mu = [g["u"] for g in gefs] + (list(ens["u"]) if ens else [])
    mv = [g["v"] for g in gefs] + (list(ens["v"]) if ens else [])
    if len(mu) < 20:
        raise RuntimeError("only %d members at +%dh" % (len(mu), step))
    members = np.hypot(np.array(mu), np.array(mv)) * KT
    speeds = np.array([np.hypot(d["u"], d["v"]) * KT for d in dets])
    mean = speeds.mean(0)
    sigma = members.std(0)
    boost = np.minimum(k_for(step) * sigma, CAP_KT)
    u = np.mean([d["u"] for d in dets], 0)
    v = np.mean([d["v"] for d in dets], 0)
    wdir = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
    msl = np.mean([d["msl"] for d in dets], 0) / 100.0
    vals = {
        "wind": mean + boost, "dir": wdir, "mean": mean, "boost": boost, "sigma": sigma,
        "gfs": speeds[0], "ecmwf": speeds[1], "aifs": speeds[2],
        "p34": 100 * (members >= 34).mean(0), "p48": 100 * (members >= 48).mean(0), "p64": 100 * (members >= 64).mean(0),
        "focus": focus_grid(speeds), "lone": lone_flags(speeds), "msl": msl - 900.0,
    }
    packed = np.stack([np.clip(np.rint(vals[n] * s), 0, 255).astype(np.uint8) for n, s, _, _ in FIELDS])
    stats = dict(step=step, members=len(mu), gefs=len(gefs), ens=0 if ens is None else len(ens["u"]),
                 max_wind=round(float(vals["wind"].max()), 1), gale_cells=int((vals["wind"] >= 34).sum()),
                 focus_cells=int((vals["focus"] >= 2).sum()), lone_cells=int((vals["lone"] > 0).sum()),
                 centres=centres(msl))
    return packed, stats


def newest_cycle(now=None):
    """Newest 00/12Z cycle whose +120 h is on AWS for all three models and the ENS."""
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    t = now.replace(minute=0, second=0, microsecond=0, hour=12 if now.hour >= 12 else 0)
    for _ in range(6):
        ymd, hh = t.strftime("%Y%m%d"), t.strftime("%H")
        urls = [fetch.gfs_url(ymd, hh, 120) + ".idx", fetch.ec_url("ifs", ymd, hh, 120),
                fetch.ec_url("aifs-single", ymd, hh, 120), fetch.ec_url("ifs", ymd, hh, 120, "enfo", "ef")]
        if all(fetch.exists(u) for u in urls):
            return ymd + hh
        t -= dt.timedelta(hours=12)
    raise RuntimeError("no complete cycle in the last three days")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycle", help="YYYYMMDDHH (default: newest complete 00/12Z cycle)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cycle = a.cycle or newest_cycle()
    ymd, hh = cycle[:8], cycle[8:]
    os.makedirs(a.out, exist_ok=True)
    base = dt.datetime.strptime(cycle, "%Y%m%d%H")
    steps = []
    for step in STEPS:
        path = os.path.join(a.out, "f%03d.bin" % step)
        done = os.path.join(a.out, "f%03d.json" % step)
        if os.path.exists(path) and os.path.exists(done):  # resume a partial run of the same cycle
            steps.append(json.load(open(done)))
            continue
        packed, stats = step_fields(ymd, hh, step)
        with open(path, "wb") as f:
            f.write(packed.tobytes())
        stats["valid"] = (base + dt.timedelta(hours=step)).strftime("%Y-%m-%dT%H:00Z")
        stats["k"] = k_for(step)
        steps.append(stats)
        with open(done, "w") as f:
            json.dump(stats, f)
        print("+%03dh members %d max %.0f kt gale cells %d focus %d lone %d" % (
            step, stats["members"], stats["max_wind"], stats["gale_cells"], stats["focus_cells"], stats["lone_cells"]), flush=True)
    manifest = dict(
        cycle=base.strftime("%Y-%m-%dT%H:00Z"), built=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%MZ"),
        grid=dict(north=NORTH, south=SOUTH, west=WEST, east=EAST, ny=NY, nx=NX, res=0.25),
        fields=[dict(name=n, scale=s, unit=u, desc=d) for n, s, u, d in FIELDS],
        cap_kt=CAP_KT, steps=steps)
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)


if __name__ == "__main__":
    main()
