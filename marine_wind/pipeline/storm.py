"""Storm layers for the marine wind page: core likelihood, the Core Lifted wind,
gale / storm / hurricane-force "possible" areas, and the ensemble low track.

Design and scores (winter 2025-26, Atlantic ASCAT; Jason's choices of 15 Oct 2026):

    core      chance (%) that ASCAT sees 48+ kt within about 50 km of the cell. A
              gradient-boosted model (core_model.json) of the models' and members'
              winds, the AIFS ensemble, 925/850 mb wind and temperature and sea
              temperature; scored only on weeks it did not see (BSS 0.47).
    windcore  Core Lifted: blended wind + 5 kt where core >= 35%. Any-48-kt-pixel tiles vs ASCAT:
              caught 49% (live blend 15%), false alarms 15% (4%); gales unchanged.
              In the two OPC boxes also raised to at least 34 kt where the gale core is 60%+
              (Jason 17 Oct 2026, held-out vs ASCAT: Atlantic gale caught 63% -> 76%, area 0.84 ->
              1.19x ASCAT, gale-tile CSI .618 -> .659, false alarms .125 -> .179; Pacific, all
              ASCAT hours, 55% -> 67%, 0.85 -> 1.25x, .526 -> .562, .193 -> .233).
    galecore  chance (%) that ASCAT sees 34+ kt within about 50 km (gale_core_model.json: the
              core features plus basin_pac, candidate cells blend >= 24 kt or a model >= 30 kt).
    hazard    bit 1 gale possible (30%+ of GEFS+ENS members at 34+ kt), bit 2 storm
              possible (core >= 30%), bit 4 hurricane force possible (core >= 90% and
              30%+ of members at 48+ kt); drawn straight from the chances, no padding.
    tracks    ensemble low track: each member's own low matched within 700 km of a
              3-model-mean low (< 1005 hPa, 40+ kt within 800 km), median position and
              central pressure; cone radius = K(lead) x median member distance from it,
              K holding the analysed low 2 in 3 (1.02, 1.13, 1.17, 1.27, 1.33 at +24..+120 h).
"""
from __future__ import annotations

import json
import os

import numpy as np
from scipy import ndimage

KT = 1.943844
R_EARTH = 6371000.0
HERE = os.path.dirname(os.path.abspath(__file__))
LIFT_KT, LIFT_P = 5.0, 0.35
GALE_LIFT_KT, GALE_LIFT_P = 34.0, 0.60
GALE_P, STORM_P, HF_P, HF_M48 = 0.30, 0.30, 0.90, 0.30
CONE_K = {24: 1.02, 48: 1.13, 72: 1.17, 96: 1.27, 120: 1.33}
NB = (9, 13)          # ~100 km box on the 0.25 degree grid
WRAP = False          # True on the global grid (build.py --domain glob): filters wrap round the date line


def _mode():
    return ("nearest", "wrap") if WRAP else "nearest"


def load_model(path=os.path.join(HERE, "core_model.json")):
    return json.load(open(path))


def core_predict(X, model):
    """X [n, nfeat] -> probability, evaluating the exported trees (NaN follows missing_go_to_left)."""
    raw = np.full(len(X), model["baseline"])
    for t in model["trees"]:
        f, th, ml, lf, rt, leaf, v = (np.asarray(t[k]) for k in ("f", "t", "ml", "l", "r", "leaf", "v"))
        node = np.zeros(len(X), int)
        active = ~leaf[node].astype(bool)
        while active.any():
            n = node[active]
            x = X[active, f[n]]
            go_left = np.where(np.isnan(x), ml[n].astype(bool), x <= th[n])
            node[active] = np.where(go_left, lf[n], rt[n])
            active = ~leaf[node].astype(bool)
        raw += v[node]
    return 1.0 / (1.0 + np.exp(-raw))


def _sm(a, s=1.5):
    a = np.asarray(a, np.float32)
    return ndimage.gaussian_filter(np.nan_to_num(a, nan=float(np.nanmean(a))), s, mode=_mode())


def core_features(lats, wind, boost, speeds, members, aens, low):
    """Feature grids for the core model, defined exactly as in the study (features.py).

    wind, boost: blended wind and its added part (kt); speeds [3, y, x] GFS/IFS/AIFS 10 m (kt);
    members [n, y, x] GEFS+ENS speeds (kt); aens [m, y, x] AIFS ENS speeds or None;
    low: 3-model means of u925 v925 u850 v850 (kt), t925 t850 t2 skt (K)."""
    LAT = np.repeat(lats[:, None], wind.shape[1], 1)
    dx = R_EARTH * np.cos(np.deg2rad(LAT)) * np.deg2rad(0.25); dy = R_EARTH * np.deg2rad(0.25)
    ddx = lambda a: np.gradient(a, axis=1) / dx
    ddy = lambda a: -np.gradient(a, axis=0) / dy
    c = {"r10": wind, "boost": boost, "s10_gfs": speeds[0], "s10_ifs": speeds[1], "s10_aifs": speeds[2],
         "mod_max": speeds.max(0), "mod_min": speeds.min(0), "mod_sd": speeds.std(0),
         "p34": (members >= 34).mean(0), "p48": (members >= 48).mean(0), "p64": (members >= 64).mean(0),
         "pa48": (aens >= 48).mean(0) if aens is not None and len(aens) else np.full(wind.shape, np.nan),
         "m90": np.percentile(members, 90, axis=0), "mmean": members.mean(0), "lat": LAT}
    for k in ("p48", "p34", "m90"):
        c[k + "_nb"] = ndimage.maximum_filter(c[k], size=NB, mode=_mode())
    c["modmax_nb"] = ndimage.maximum_filter(c["mod_max"], size=NB, mode=_mode())
    c["r10_nbmax"] = ndimage.maximum_filter(wind, size=(21, 31), mode=_mode())
    c["s925"] = np.hypot(low["u925"], low["v925"])
    c["s925_minus_r10"] = c["s925"] - wind
    c["dT"] = low["t2"] - low["skt"]; c["sst_t850"] = low["skt"] - low["t850"]; c["sst_t925"] = low["skt"] - low["t925"]
    t9, u9, v9 = _sm(low["t925"]), _sm(low["u925"]) / KT, _sm(low["v925"]) / KT
    c["tadv925"] = -(u9 * ddx(t9) + v9 * ddy(t9)) * 21600
    t8, u8, v8 = _sm(low["t850"]), _sm(low["u850"]) / KT, _sm(low["v850"]) / KT
    tx, ty = ddx(t8), ddy(t8)
    c["gradT850"] = np.maximum(np.hypot(tx, ty), 1e-7) * 1e5
    c["tadv850"] = -(u8 * tx + v8 * ty) * 21600
    return c


def core_grid(feats, ocean, model, r10_min=28, mod_min=34):
    """Core likelihood (0-1) on candidate ocean cells (blend >= r10_min kt or a model >= mod_min kt),
    0 elsewhere: 28/34 for the storm core, 24/30 for the gale core (whose feats carry basin_pac)."""
    cand = ocean & ((feats["r10"] >= r10_min) | (feats["mod_max"] >= mod_min))
    P = np.zeros(feats["r10"].shape, np.float32)
    if cand.any():
        X = np.column_stack([np.asarray(feats[f], np.float64)[cand] for f in model["features"]])
        P[cand] = core_predict(X, model)
    return P


def products(wind, P, members):
    """windcore (kt) and the hazard bit field."""
    windcore = np.where(P >= LIFT_P, wind + LIFT_KT, wind)
    pc = ndimage.gaussian_filter(P.astype(np.float32), 1.0, mode=_mode())
    p34 = ndimage.gaussian_filter((members >= 34).mean(0).astype(np.float32), 1.0, mode=_mode())
    p48 = ndimage.gaussian_filter((members >= 48).mean(0).astype(np.float32), 1.0, mode=_mode())
    hz = (p34 >= GALE_P).astype(np.uint8) | ((pc >= STORM_P).astype(np.uint8) << 1) | \
         (((pc >= HF_P) & (p48 >= HF_M48)).astype(np.uint8) << 2)
    return windcore, hz


def gale_lift(windcore, Pg):
    """Core Lifted raised to at least 34 kt where the gale core is 60%+."""
    return np.where(Pg >= GALE_LIFT_P, np.maximum(windcore, GALE_LIFT_KT), windcore)


# ---------------------------------------------------------------- ensemble low track

def lows(msl, thr):
    """Low centres (row, col, hPa) from a smoothed MSLP field (hPa), as in the study."""
    s = ndimage.gaussian_filter(np.asarray(msl, np.float32), 2.0, mode=_mode())
    mn = ndimage.minimum_filter(s, size=(17, 25), mode=_mode())
    ny, nx = s.shape
    rr, cc = np.where((s == mn) & (s < thr))
    return [(int(r), int(c), float(s[r, c])) for r, c in zip(rr, cc) if 3 <= r < ny - 3 and (WRAP or 3 <= c < nx - 3)]


def km(lats, lons, r1, c1, r2, c2):
    la1, la2 = np.deg2rad(lats[r1]), np.deg2rad(lats[r2])
    dlo = np.deg2rad((lons[c2] - lons[c1] + 180.0) % 360.0 - 180.0)
    return R_EARTH / 1000.0 * float(np.hypot(dlo * np.cos((la1 + la2) / 2), la2 - la1))


def step_lows(lats, lons, det_msl, det_speeds, mem_msl):
    """Most likely low positions at one lead: list of dicts (row, col, hPa, spread_km, n, nmem)."""
    ref = np.mean(det_msl, 0)
    mod_max = det_speeds.max(0)
    LAT = np.deg2rad(np.repeat(lats[:, None], len(lons), 1)); LON = np.deg2rad(np.repeat(lons[None], len(lats), 0))
    mem_lows = [lows(m, 1015.0) for m in mem_msl]
    out = []
    for r, c, p in lows(ref, 1005.0):
        x = ((LON - LON[r, c] + np.pi) % (2 * np.pi) - np.pi) * np.cos((LAT + LAT[r, c]) / 2) * R_EARTH / 1000
        y = (LAT - LAT[r, c]) * R_EARTH / 1000
        if np.nanmax(np.where(np.hypot(x, y) < 800, mod_max, 0)) < 40:
            continue
        mm = []
        for L in mem_lows:
            if not L:
                continue
            d = [km(lats, lons, rr, cc, r, c) for rr, cc, _ in L]
            j = int(np.argmin(d))
            if d[j] < 700:
                mm.append(L[j])
        if len(mm) < 0.5 * len(mem_msl):
            continue
        pr, pc_ = np.array([m[0] for m in mm]), np.array([m[1] for m in mm])
        rs, cs = int(np.median(pr)), int(np.median(pc_))
        out.append(dict(r=rs, c=cs, p=float(np.median([m[2] for m in mm])),
                        spread=float(np.median([km(lats, lons, a, b, rs, cs) for a, b in zip(pr, pc_)])),
                        n=len(mm), nmem=len(mem_msl)))
    return out


def link_tracks(lats, lons, by_step):
    """Join the per-lead lows into tracks: deepest +24 h low first; nearest to a damped
    motion extrapolation, charging 15 km per hPa jump and westward retreat beyond 300 km;
    a low already taken ends the track there (merger)."""
    steps = sorted(by_step)
    if not steps:
        return []
    claimed, tracks = set(), []
    for start in sorted(by_step[steps[0]], key=lambda l: l["p"]):
        pts = [dict(start, step=steps[0])]
        if (steps[0], start["r"], start["c"]) in claimed:
            continue
        claimed.add((steps[0], start["r"], start["c"]))
        for st in steps[1:]:
            last = pts[-1]
            if len(pts) >= 2:
                pr = int(np.clip(last["r"] + 0.6 * (last["r"] - pts[-2]["r"]), 0, len(lats) - 1))
                dc = (last["c"] - pts[-2]["c"] + len(lons) // 2) % len(lons) - len(lons) // 2 if WRAP else last["c"] - pts[-2]["c"]
                pc_ = int(last["c"] + 0.6 * dc)
                pc_ = pc_ % len(lons) if WRAP else int(np.clip(pc_, 0, len(lons) - 1))
            else:
                pr, pc_ = last["r"], last["c"]
            best, cost = None, 1e9
            for l in by_step[st]:
                if km(lats, lons, l["r"], l["c"], last["r"], last["c"]) > 1500:
                    continue
                west = ((lons[last["c"]] - lons[l["c"]] + 180) % 360 - 180) * 111 * np.cos(np.deg2rad(lats[last["r"]]))
                cst = km(lats, lons, l["r"], l["c"], pr, pc_) + 15 * abs(l["p"] - last["p"]) + 2 * max(0.0, west - 300)
                if cst < cost:
                    best, cost = l, cst
            if best is None or cost > (1800 if len(pts) < 2 else 1100):
                break
            pts.append(dict(best, step=st))
            key = (st, best["r"], best["c"])
            if key in claimed:
                break
            claimed.add(key)
        # longitudes kept continuous along a track, so one crossing the date line has no jump
        out, prev = [], None
        for p in pts:
            lon = float(lons[p["c"]])
            if prev is not None:
                lon = prev + (lon - prev + 180.0) % 360.0 - 180.0
            prev = lon
            out.append(dict(step=p["step"], lat=round(float(lats[p["r"]]), 2), lon=round(lon, 2),
                            hpa=round(p["p"], 1), spread_km=round(p["spread"]), members=p["n"], of=p["nmem"],
                            cone_km=round(CONE_K.get(p["step"], 1.2) * max(p["spread"], 30.0))))
        tracks.append(out)
    return tracks
