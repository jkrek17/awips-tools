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
                       the AIFS ensemble (51) when it is posted. p34 is the share of members;
                       p48 and p64 are that share recalibrated to how often it verified in the
                       2025-26 hindcast (calibration.json; the raw shares stay in p48raw, p64raw)
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

and writes OUT/manifest.json plus one OUT/fFFF.bin per lead (uint8 fields,
row-major, north row first, in the order of manifest["fields"]).

    python3 build.py --out site_data                # newest complete cycle, North Atlantic
    python3 build.py --domain npac --out site_data/npac
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
# the basin must be known before domain.py is imported (fetch.py crops with it)
if "--domain" in sys.argv:
    os.environ["MARINE_DOMAIN"] = sys.argv[sys.argv.index("--domain") + 1]
import fetch  # noqa: E402
from domain import BASIN, EAST, KEY, NORTH, NX, NY, SOUTH, WEST  # noqa: E402

KT = 1.943844
STEPS = list(range(12, 121, 12))
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
    ("p34", 1, "%", "Members at 34 kt or more"),
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
]


CALIB = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")))


def calibrate(pct, thr, step):
    """Member share (%) -> chance (%) from the hindcast table for this basin and lead."""
    g = "le48" if step <= 48 else ("72" if step <= 84 else "ge96")
    t = CALIB["thresholds"][str(thr)][KEY][g]
    return np.interp(pct, t["raw"], t["cal"])


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


def step_fields(ymd, hh, step):
    lag12, lag24 = prior_speeds(ymd, hh, step, 12), prior_speeds(ymd, hh, step, 24)
    prev = None if lag24 is None else lag24.mean(0)
    with ThreadPoolExecutor(12) as ex:
        det_f = [ex.submit(fetch.gfs, ymd, hh, step), ex.submit(fetch.ec_det, "ifs", ymd, hh, step),
                 ex.submit(fetch.ec_det, "aifs-single", ymd, hh, step)]
        gefs_f = [ex.submit(fetch.gefs, ymd, hh, step, m) for m in fetch.GEFS_MEMBERS]
        ens_f = ex.submit(fetch.ec_ens, ymd, hh, step)
        aens_f = ex.submit(fetch.ec_ens, ymd, hh, step, "aifs-ens")
        dets = [f.result() for f in det_f]
        gefs = [f.result() for f in gefs_f]
        ens = ens_f.result()
        try:
            aens = aens_f.result()
        except Exception as e:  # optional: probabilities fall back to GEFS + ENS
            print("AIFS ensemble +%dh unavailable: %s" % (step, e), flush=True)
            aens = None
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
    p48raw, p64raw = 100 * (pmem >= 48).mean(0), 100 * (pmem >= 64).mean(0)
    trend = np.zeros_like(mean) if prev is None else speeds.mean(0) - prev
    lagged = [x for x in (lag12, lag24) if x is not None]
    nomem = nomem_blend(speeds, lagged)
    vals = {
        "wind": mean + boost, "dir": wdir, "mean": mean, "boost": boost, "sigma": sigma,
        "gfs": speeds[0], "ecmwf": speeds[1], "aifs": speeds[2],
        "p34": 100 * (pmem >= 34).mean(0), "p48": calibrate(p48raw, 48, step), "p64": calibrate(p64raw, 64, step),
        "p48raw": p48raw, "p64raw": p64raw, "trend": trend,
        "nomem": nomem, "nomemdiff": nomem - (mean + boost),
        "focus": focus_grid(speeds), "lone": lone_flags(speeds), "msl": msl - 900.0,
    }
    packed = np.stack([np.clip(np.rint((vals[f[0]] + (f[4] if len(f) > 4 else 0)) * f[1]), 0, 255).astype(np.uint8)
                       for f in FIELDS])
    stats = dict(step=step, members=len(mu), gefs=len(gefs), ens=0 if ens is None else len(ens["u"]),
                 aifs_ens=0 if aens is None else len(aens["u"]), prob_members=len(pmem), trend=prev is not None,
                 nomem_runs=3 * (1 + len(lagged)),
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
    ap.add_argument("--domain", default=KEY, choices=["natl", "npac"], help="basin (default natl)")
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
        basin=KEY, basin_name=BASIN["name"],
        cycle=base.strftime("%Y-%m-%dT%H:00Z"), built=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%MZ"),
        grid=dict(north=NORTH, south=SOUTH, west=WEST, east=EAST, ny=NY, nx=NX, res=0.25),
        fields=[dict(name=f[0], scale=f[1], unit=f[2], desc=f[3], offset=f[4] if len(f) > 4 else 0) for f in FIELDS],
        cap_kt=CAP_KT, steps=steps)
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)


if __name__ == "__main__":
    main()
