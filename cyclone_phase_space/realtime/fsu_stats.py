#!/usr/bin/env python3
"""Compare our tracked cyclone phase space series with Florida State
University's, over the whole daily collection.

For every storm-cycle in data/<cycle>/<STORM>/ with an FSU match
(the fsu_phase1.png and fsu_phase2.png the collector saved beside the
track; meta.json's "fsu_number" is reported where it is set, since a
rerun of a cycle that could not reach FSU's page leaves it empty),
the two FSU plots are digitized (fsu_digitize.digitize_pair), our
track.csv gets the same 24 h centered running mean the diagrams use
(track_cps.running_mean; FSU's trajectory already is a 24 h mean), and
the two are paired at the valid hours both have. Over the archive this
computes, for B, -V_T^L and -V_T^U and for both of our band choices
(Hart's, the website's primary set: hb_hart, hvtl_hart, hvtu_hart;
standard, what AWIPS CAVE shows: hb, hvtl, hvtu):
the mean difference (ours minus FSU), the RMS difference and the count,
overall and split by FSU's lower thermal regime (warm: FSU -V_T^L >= 0,
cold: < 0) and by our track speed (motion_kt above 20 kt or not); the
agreement of the joint class (hart_class rule: B > 10 m asymmetric, a
thermal wind term warm if >= 0); and the difference of the onset and
completion hours (track_cps.onset_completion) where both sides cross.
From our own tracks alone (all storm-cycles, raw 6-hourly values) it
also gives hb - hb_track and the class disagreement between the two B
choices against motion_kt, hb_hart - hb_track (Hart's 900-600 hPa
thickness against the rescaled 925-700 hPa one, both with the track
motion), and hvtl - hvtl_hart, hvtu - hvtu_hart.

Points enter the FSU statistics in two sets: 'verified' (the hour was
timed independently on both FSU plots and their -V_T^L agree; the
headline set) and 'usable' (also hours timed on one plot only, or
carried to the other plot by matching its marker). Outputs, in
data/validation/: fsu_stats.json, fsu_pairs.csv, fsu_stats.md,
fig_fsu_scatter.png, fig_fsu_timing.png. Re-runnable; digitizing the
whole archive takes a few minutes with four worker processes.

    python3 fsu_stats.py [--data-dir DIR] [--out DIR] [--workers N] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fsu_digitize as fd  # noqa: E402

B_THR = 10.0
FAST_KT = 20.0
SMOOTH_H = 24.0
MOTION_BINS = [0, 10, 20, 30, 40, 1e9]
TERMS = ("b", "vtl", "vtu")
BANDS = {"hart": {"b": "hb_hart", "vtl": "hvtl_hart", "vtu": "hvtu_hart"},
         "standard": {"b": "hb", "vtl": "hvtl", "vtu": "hvtu"}}
TRACK_COLS = ("hvtl", "hvtu", "hb", "hvtl_hart", "hvtu_hart", "hb_track", "hb_hart")
TERM_LABEL = {"b": "B", "vtl": "-V_T^L", "vtu": "-V_T^U"}


# ------------------------------------------------------------------ helpers shared with the collector
def running_mean(hours, vals, width_h: float = SMOOTH_H) -> np.ndarray:
    """track_cps.running_mean (imported lazily: track_cps pulls in the GFS
    stack); the same centered, NaN-aware mean over +/- width_h / 2."""
    try:
        import track_cps as tc
        return tc.running_mean(np.asarray(hours, float), np.asarray(vals, float), width_h)
    except ImportError:  # pragma: no cover - same algorithm, for a machine without the GFS stack
        hours = np.asarray(hours, float)
        vals = np.asarray(vals, float)
        out = np.full(vals.shape, np.nan)
        for k, h in enumerate(hours):
            w = vals[np.abs(hours - h) <= width_h / 2 + 1e-6]
            w = w[np.isfinite(w)]
            if w.size:
                out[k] = w.mean()
        return out


def hart_class(b, vtl, vtu, b_thr: float = B_THR):
    """The joint class (0-6) of the D2D table (cps_HartCPS.hart_class):
    B > b_thr asymmetric, a thermal wind term warm if >= 0; row 6 (lower
    cold, upper warm) first. None when a value is missing."""
    if b is None or vtl is None or vtu is None or not all(map(np.isfinite, (b, vtl, vtu))):
        return None
    if vtl < 0 and vtu >= 0:
        return 6
    asym = b > b_thr
    if vtl >= 0:
        return (2 if asym else 0) if vtu >= 0 else (3 if asym else 1)
    return 4 if asym else 5


def onset_completion(hours, b, vtl) -> tuple[float, float]:
    """track_cps.onset_completion: onset is the first hour B > 10 m;
    completion the first hour at or after onset (from the start without
    one) that -V_T^L < 0."""
    on = next((float(h) for h, v in zip(hours, b) if np.isfinite(v) and v > B_THR), float("nan"))
    comp = next((float(h) for h, v in zip(hours, vtl)
                 if np.isfinite(v) and v < 0 and (np.isnan(on) or h >= on)), float("nan"))
    return on, comp


def fnum(s) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return float("nan")


def read_track(path: Path) -> dict[str, np.ndarray]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    cols = ["fhr", *TRACK_COLS, "motion_kt", "mslp_hpa"]
    out = {c: np.array([fnum(r.get(c)) for r in rows]) for c in cols}
    out["valid"] = [r.get("valid", "") for r in rows]
    return out


def stats(d) -> dict:
    d = np.asarray([v for v in d if v is not None and np.isfinite(v)], float)
    if d.size == 0:
        return {"n": 0, "mean": None, "rms": None, "sd": None, "median": None}
    return {"n": int(d.size), "mean": round(float(d.mean()), 2), "rms": round(float(np.sqrt((d ** 2).mean())), 2),
            "sd": round(float(d.std(ddof=1)), 2) if d.size > 1 else None,
            "median": round(float(np.median(d)), 2)}


# ------------------------------------------------------------------ one storm-cycle
def storm_cycles(data_dir: Path) -> list[tuple[str, str, Path]]:
    out = []
    for meta in sorted(data_dir.glob("*/*/meta.json")):
        sdir = meta.parent
        try:
            m = json.loads(meta.read_text())
        except ValueError:
            continue
        if m.get("status") != "ok" or not (sdir / "track.csv").exists():
            continue
        out.append((sdir.parent.name, sdir.name, sdir))
    return out


def cycle_time(cycle: str) -> dt.datetime:
    return dt.datetime.strptime(cycle, "%Y%m%d%H")


def digitize_one(args) -> dict:
    cycle, storm, sdir = args
    t0 = time.time()
    try:
        res = fd.digitize_pair(sdir / "fsu_phase1.png", sdir / "fsu_phase2.png", cycle_time(cycle))
        out = {"cycle": cycle, "storm": storm, "rows": res["rows"], "error": None,
               "quality": [res["phase1"]["quality"], res["phase2"]["quality"]],
               "notes": [res["phase1"]["notes"], res["phase2"]["notes"]],
               "header": res["phase1"].get("header"),
               "background": [res["phase1"].get("axes", {}).get("background"),
                              res["phase2"].get("axes", {}).get("background")],
               "n_discs": [len(res["phase1"]["discs"]), len(res["phase2"]["discs"])],
               "untimed": [sum(1 for d in r["discs"] if d["hour"] is None) for r in (res["phase1"], res["phase2"])]}
    except Exception as e:  # one bad plot must not stop the archive
        out = {"cycle": cycle, "storm": storm, "rows": [], "error": f"{type(e).__name__}: {e}",
               "quality": ["error", "error"], "notes": [], "header": None, "background": [None, None],
               "n_discs": [0, 0], "untimed": [0, 0]}
    out["seconds"] = round(time.time() - t0, 2)
    return out


def pair_rows(dig: dict, track: dict, fsu_number) -> list[dict]:
    """Our smoothed values at each FSU hour that our track also has."""
    hours = track["fhr"]
    sm = {c: running_mean(hours, track[c]) for c in TRACK_COLS}
    idx = {int(h): k for k, h in enumerate(hours) if np.isfinite(h)}
    out = []
    for r in dig["rows"]:
        k = idx.get(int(r["hour"]))
        if k is None:
            continue
        vtl_f = [v for v in (r["vtl"], r["vtl2"]) if v is not None]
        f1, f2 = r["flag1"].split("/")[0], r["flag2"].split("/")[0]
        verified = f1 == "verified" and f2 == "verified"
        row = {"cycle": dig["cycle"], "storm": dig["storm"], "fsu_number": fsu_number,
               "valid": track["valid"][k], "fhr": int(r["hour"]),
               "fsu_b": r["b"], "fsu_vtl": float(np.mean(vtl_f)) if vtl_f else None, "fsu_vtu": r["vtu"],
               "fsu_vtl_phase1": r["vtl"], "fsu_vtl_phase2": r["vtl2"],
               "err_b": r["e_b"], "err_vtl": r["e_vtl"], "err_vtu": r["e_vtu"],
               "flag_phase1": r["flag1"], "flag_phase2": r["flag2"], "verified": verified,
               "motion_kt": float(track["motion_kt"][k]), "mslp_hpa": float(track["mslp_hpa"][k])}
        for c in sm:
            row[c] = float(sm[c][k]) if np.isfinite(sm[c][k]) else None
        row["class_fsu"] = hart_class(row["fsu_b"], row["fsu_vtl"], row["fsu_vtu"])
        for band, cols in BANDS.items():
            row["class_" + band] = hart_class(row[cols["b"]], row[cols["vtl"]], row[cols["vtu"]])
        out.append(row)
    return out


# ------------------------------------------------------------------ statistics
def term_stats(rows: list[dict]) -> dict:
    """Bias / RMS / count per band choice and term, overall, by FSU lower
    thermal regime and by our speed."""
    out = {}
    groups = {
        "all": lambda r: True,
        "warm_lower": lambda r: r["fsu_vtl"] is not None and r["fsu_vtl"] >= 0,
        "cold_lower": lambda r: r["fsu_vtl"] is not None and r["fsu_vtl"] < 0,
        "fast_gt20kt": lambda r: np.isfinite(r["motion_kt"]) and r["motion_kt"] > FAST_KT,
        "slow_le20kt": lambda r: np.isfinite(r["motion_kt"]) and r["motion_kt"] <= FAST_KT,
    }
    for band, cols in BANDS.items():
        out[band] = {}
        for term in TERMS:
            ours, fsu = cols[term], "fsu_" + term
            out[band][term] = {}
            for g, test in groups.items():
                d = [r[ours] - r[fsu] for r in rows if test(r) and r[ours] is not None and r[fsu] is not None]
                out[band][term][g] = stats(d)
    return out


def class_stats(rows: list[dict]) -> dict:
    out = {}
    for band in BANDS:
        key = "class_" + band
        pr = [(r[key], r["class_fsu"]) for r in rows if r[key] is not None and r["class_fsu"] is not None]
        conf = np.zeros((7, 7), int)
        for a, b in pr:
            conf[a, b] += 1
        fast = [(r[key], r["class_fsu"]) for r in rows if r[key] is not None and r["class_fsu"] is not None
                and np.isfinite(r["motion_kt"]) and r["motion_kt"] > FAST_KT]
        slow = [(r[key], r["class_fsu"]) for r in rows if r[key] is not None and r["class_fsu"] is not None
                and np.isfinite(r["motion_kt"]) and r["motion_kt"] <= FAST_KT]

        def rate(p):
            return {"n": len(p), "agree": sum(a == b for a, b in p),
                    "rate": round(sum(a == b for a, b in p) / len(p), 3) if p else None}
        # agreement of the B side alone (symmetric / asymmetric) and of each thermal sign
        bsym = [((r[BANDS[band]["b"]] > B_THR), (r["fsu_b"] > B_THR)) for r in rows
                if r[BANDS[band]["b"]] is not None and r["fsu_b"] is not None]
        out[band] = {"all": rate(pr), "fast_gt20kt": rate(fast), "slow_le20kt": rate(slow),
                     "b_side_agree": rate(bsym),
                     "confusion_ours_rows_fsu_cols": conf.tolist()}
    return out


def timing_stats(rows: list[dict]) -> dict:
    """Onset and completion, per storm-cycle, on the hours both sides
    have. A pair is counted only where both series start on the near
    side of the threshold at the first shared hour (B <= 10 m for onset,
    -V_T^L >= 0 for completion), both cross later, and both series are
    6-hourly without a gap up to the crossing (so it cannot have
    happened unseen in a gap)."""
    by: dict = {}
    for r in rows:
        by.setdefault((r["cycle"], r["storm"]), []).append(r)
    out = {}
    for band, cols in BANDS.items():
        on_d, comp_d, cases = [], [], []
        for key, rs in by.items():
            rs = sorted([r for r in rs if r["fsu_b"] is not None and r["fsu_vtl"] is not None
                         and r[cols["b"]] is not None and r[cols["vtl"]] is not None], key=lambda r: r["fhr"])
            if len(rs) < 3:
                continue
            h = np.array([r["fhr"] for r in rs], float)
            gaps = np.r_[0, np.diff(h)]
            on_o, comp_o = onset_completion(h, [r[cols["b"]] for r in rs], [r[cols["vtl"]] for r in rs])
            on_f, comp_f = onset_completion(h, [r["fsu_b"] for r in rs], [r["fsu_vtl"] for r in rs])

            def contiguous(t):
                return np.isfinite(t) and np.all(gaps[h <= t] <= fd.STEP_H)
            rec = {"cycle": key[0], "storm": key[1], "onset_ours": on_o, "onset_fsu": on_f,
                   "completion_ours": comp_o, "completion_fsu": comp_f}
            # a crossing counts only when both series start on the near side of it
            # (already asymmetric, or already cold, at the first shared hour is no crossing)
            b0 = (rs[0][cols["b"]] <= B_THR, rs[0]["fsu_b"] <= B_THR)
            v0 = (rs[0][cols["vtl"]] >= 0, rs[0]["fsu_vtl"] >= 0)
            if all(b0) and np.isfinite(on_o) and contiguous(on_f) and contiguous(on_o):
                on_d.append(on_o - on_f)
                rec["onset_diff_h"] = on_o - on_f
            if all(v0) and np.isfinite(comp_o) and contiguous(comp_f) and contiguous(comp_o):
                comp_d.append(comp_o - comp_f)
                rec["completion_diff_h"] = comp_o - comp_f
            cases.append(rec)
        out[band] = {"onset_diff_h": stats(on_d), "completion_diff_h": stats(comp_d),
                     "onset_within_6h": sum(abs(v) <= 6 for v in on_d),
                     "completion_within_6h": sum(abs(v) <= 6 for v in comp_d),
                     "onset_values": on_d, "completion_values": comp_d,
                     "onset_hist": dict(zip(*np.unique(on_d, return_counts=True))) if on_d else {},
                     "completion_hist": dict(zip(*np.unique(comp_d, return_counts=True))) if comp_d else {},
                     "cases": cases}
        for k in ("onset_hist", "completion_hist"):
            out[band][k] = {str(int(a)): int(b) for a, b in out[band][k].items()}
    return out


def own_stats(tracks: list[dict]) -> dict:
    """From our tracks alone (raw 6-hourly values): hb - hb_track and the
    class disagreement between the two B choices against motion_kt;
    hb_hart - hb_track (the two track-motion B, Hart's 900-600 hPa
    thickness against the rescaled 925-700 hPa one), overall and by
    motion_kt; hvtl - hvtl_hart and hvtu - hvtu_hart."""
    hb, hbt, hbh, mot, vl, vlh, vu, vuh = [], [], [], [], [], [], [], []
    for t in tracks:
        hb += list(t["hb"])
        hbt += list(t["hb_track"])
        hbh += list(t.get("hb_hart", [np.nan] * len(t["hb"])))
        mot += list(t["motion_kt"])
        vl += list(t["hvtl"])
        vlh += list(t["hvtl_hart"])
        vu += list(t["hvtu"])
        vuh += list(t["hvtu_hart"])
    hb, hbt, hbh, mot = np.array(hb), np.array(hbt), np.array(hbh, float), np.array(mot)
    vl, vlh, vu, vuh = np.array(vl), np.array(vlh), np.array(vu), np.array(vuh)
    out = {"by_motion_kt": []}
    for lo, hi in zip(MOTION_BINS[:-1], MOTION_BINS[1:]):
        inbin = (mot >= lo) & (mot < hi)
        mh = inbin & np.isfinite(hbh) & np.isfinite(hbt)
        m = inbin & np.isfinite(hb) & np.isfinite(hbt)
        d = hb[m] - hbt[m]
        cls_a = [hart_class(a, b, c) for a, b, c in zip(hb[m], vl[m], vu[m])]
        cls_b = [hart_class(a, b, c) for a, b, c in zip(hbt[m], vl[m], vu[m])]
        pr = [(a, b) for a, b in zip(cls_a, cls_b) if a is not None and b is not None]
        side = [((a > B_THR) != (b > B_THR)) for a, b in zip(hb[m], hbt[m])]
        rec = {"motion_kt": [lo, None if hi > 1e8 else hi], "hb_minus_hb_track": stats(d),
               "abs_p90": round(float(np.percentile(np.abs(d), 90)), 2) if d.size else None,
               "class_differs": {"n": len(pr), "differ": sum(a != b for a, b in pr),
                                 "rate": round(sum(a != b for a, b in pr) / len(pr), 3) if pr else None},
               "b_side_differs_rate": round(float(np.mean(side)), 3) if side else None,
               "hb_hart_minus_hb_track": stats(hbh[mh] - hbt[mh])}
        out["by_motion_kt"].append(rec)
    m = np.isfinite(hb) & np.isfinite(hbt)
    out["hb_minus_hb_track_all"] = stats(hb[m] - hbt[m])
    out["n_steering_blank"] = int(np.sum(~np.isfinite(hb) & np.isfinite(hbt)))
    m = np.isfinite(hbh) & np.isfinite(hbt)
    out["hb_hart_minus_hb_track"] = stats(hbh[m] - hbt[m])
    out["hb_hart_minus_hb_track_pct"] = ([round(float(v), 1) for v in np.percentile(hbh[m] - hbt[m], [5, 25, 50, 75, 95])]
                                        if m.any() else None)
    side = (hbh[m] > B_THR) != (hbt[m] > B_THR)
    out["hb_hart_vs_hb_track_b_side_differs"] = {"n": int(m.sum()), "differ": int(side.sum()),
                                                 "rate": round(float(side.mean()), 3) if m.any() else None}
    m = np.isfinite(vl) & np.isfinite(vlh)
    out["hvtl_minus_hvtl_hart"] = stats(vl[m] - vlh[m])
    out["hvtl_minus_hvtl_hart_pct"] = [round(float(v), 1) for v in np.percentile(vl[m] - vlh[m], [5, 25, 50, 75, 95])]
    m = np.isfinite(vu) & np.isfinite(vuh)
    out["hvtu_minus_hvtu_hart"] = stats(vu[m] - vuh[m])
    out["hvtu_minus_hvtu_hart_pct"] = [round(float(v), 1) for v in np.percentile(vu[m] - vuh[m], [5, 25, 50, 75, 95])]
    out["n_storm_cycles"] = len(tracks)
    out["n_points"] = int(np.isfinite(hb).sum() + np.sum(~np.isfinite(hb) & np.isfinite(hbt)))
    return out


def digitizer_stats(digs: list[dict], rows: list[dict]) -> dict:
    """How much was digitized and how well."""
    n_plots = 2 * len(digs)
    q = {}
    for d in digs:
        for x in d["quality"]:
            q[x] = q.get(x, 0) + 1
    allrows = [r for d in digs for r in d["rows"]]
    flags = {}
    for r in allrows:
        for k in ("flag1", "flag2"):
            flags[r[k]] = flags.get(r[k], 0) + 1
    ver = [r for r in rows if r["verified"]]
    dx = [r["fsu_vtl_phase1"] - r["fsu_vtl_phase2"] for r in ver]
    both = [r for r in allrows if r["flag1"].startswith(("verified", "inconsistent"))
            or r["flag2"].startswith(("verified", "inconsistent"))]
    n_inc = sum(1 for r in both if "inconsistent" in r["flag1"] + r["flag2"])
    bg = {"phase1_x0": [], "phase1_y10": [], "phase2_x0": [], "phase2_y0": []}
    for d in digs:
        for k, b in enumerate(d["background"]):
            if not b:
                continue
            if b.get("x_boundary") is not None:
                bg[f"phase{k + 1}_x0"].append(b["x_boundary"])
            if b.get("y_boundary") is not None:
                bg["phase1_y10" if k == 0 else "phase2_y0"].append(b["y_boundary"])
    return {
        "storm_cycles": len(digs), "plots": n_plots, "plot_quality": q,
        "errors": [f"{d['cycle']}/{d['storm']}: {d['error']}" for d in digs if d["error"]],
        "hours_with_a_point_on_either_plot": len(allrows),
        "point_flags": flags,
        "untimed_discs": int(sum(sum(d["untimed"]) for d in digs)),
        "discs": int(sum(sum(d["n_discs"]) for d in digs)),
        "paired_hours_usable": len(rows), "paired_hours_verified": len(ver),
        "phase1_minus_phase2_vtl_on_verified": stats(dx),
        "hours_timed_on_both_plots": len(both), "of_which_inconsistent": n_inc,
        "inconsistent_rate": round(n_inc / len(both), 3) if both else None,
        "median_error_estimate_m": {
            "b": round(float(np.median([r["err_b"] for r in rows if r["err_b"] is not None])), 2) if rows else None,
            "vtl": round(float(np.median([r["err_vtl"] for r in rows if r["err_vtl"] is not None])), 2) if rows else None,
            "vtu": round(float(np.median([r["err_vtu"] for r in rows if r["err_vtu"] is not None])), 2) if rows else None},
        "background_boundaries_median": {k: (round(float(np.median(v)), 1) if v else None) for k, v in bg.items()},
        "background_boundaries_n": {k: len(v) for k, v in bg.items()},
        "seconds_total": round(sum(d["seconds"] for d in digs), 1),
    }


def hand_check(digs_by_key: dict, hand_csv: Path) -> dict | None:
    """Compare the digitizer with hand readings (hand_digitized.csv:
    cycle, storm, plot, hour, x, y), when that file exists."""
    if not hand_csv.exists():
        return None
    with open(hand_csv, newline="") as f:
        hand = list(csv.DictReader(line for line in f if not line.startswith("#")))
    dx, dy, missing, rows = [], [], 0, []
    for h in hand:
        d = digs_by_key.get((h["cycle"], h["storm"]))
        if d is None:
            continue
        hr = int(h["hour"])
        r = next((q for q in d["rows"] if q["hour"] == hr), None)
        k = 1 if h["plot"] == "phase1" else 2
        if r is None or (k == 1 and r["b"] is None) or (k == 2 and r["vtu"] is None):
            missing += 1
            rows.append({**h, "digitized": None})
            continue
        x = r["vtl"] if k == 1 else r["vtl2"]
        y = r["b"] if k == 1 else r["vtu"]
        dx.append(x - float(h["x"]))
        dy.append(y - float(h["y"]))
        rows.append({**h, "digitized_x": round(x, 2), "digitized_y": round(y, 2),
                     "flag": r["flag1"] if k == 1 else r["flag2"]})
    return {"n_hand": len(hand), "n_compared": len(dx), "n_not_digitized": missing,
            "x_minus_hand": stats(dx), "y_minus_hand": stats(dy), "points": rows}


# ------------------------------------------------------------------ outputs
PAIR_COLS = ["cycle", "storm", "fsu_number", "valid", "fhr", "verified", "flag_phase1", "flag_phase2",
             "fsu_b", "fsu_vtl", "fsu_vtu", "fsu_vtl_phase1", "fsu_vtl_phase2", "err_b", "err_vtl", "err_vtu",
             "hb", "hvtl", "hvtu", "hb_track", "hb_hart", "hvtl_hart", "hvtu_hart", "motion_kt", "mslp_hpa",
             "class_fsu", "class_standard", "class_hart"]


def fmt(v, nd=2):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return "" if not np.isfinite(v) else f"{v:.{nd}f}"
    return str(v)


def write_pairs(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(PAIR_COLS)
        for r in rows:
            w.writerow([fmt(r.get(c)) for c in PAIR_COLS])


def scatter_figure(path: Path, rows: list[dict], err: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(2, 3, figsize=(15, 9.6), constrained_layout=True)
    for i, (band, cols) in enumerate(BANDS.items()):
        for j, term in enumerate(TERMS):
            ax = axs[i, j]
            for verified, mk, lab in ((False, "o", "one plot only"), (True, "o", "verified on both plots")):
                for warm, col in ((True, "#c0392b"), (False, "#2471a3")):
                    sel = [r for r in rows if r["verified"] == verified and r[cols[term]] is not None
                           and r["fsu_" + term] is not None and r["fsu_vtl"] is not None
                           and (r["fsu_vtl"] >= 0) == warm]
                    if not sel:
                        continue
                    ax.scatter([r["fsu_" + term] for r in sel], [r[cols[term]] for r in sel], s=10 if verified else 7,
                               marker=mk, facecolors=col if verified else "none", edgecolors=col, linewidths=0.6,
                               alpha=0.75 if verified else 0.45,
                               label=f"{'warm' if warm else 'cold'} lower core, {lab}")
            allv = [v for r in rows for v in (r[cols[term]], r["fsu_" + term]) if v is not None]
            if allv:
                lo, hi = min(allv), max(allv)
                pad = 0.05 * (hi - lo + 1)
                ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], color="0.3", lw=0.8)
                ax.set_xlim(lo - pad, hi + pad)
                ax.set_ylim(lo - pad, hi + pad)
            s = err[band][term]["all"]
            ax.set_title(f"{TERM_LABEL[term]}, {band} bands ({cols[term]})\nverified: bias {s['mean']:+.1f} m, "
                         f"RMS {s['rms']:.1f} m, n {s['n']}", fontsize=9.5)
            ax.set_xlabel(f"FSU {TERM_LABEL[term]} (m, digitized)")
            ax.set_ylabel(f"ours {cols[term]} (m, 24 h mean)")
            ax.grid(alpha=0.3)
            if i == 0 and j == 0:
                ax.legend(fontsize=7.5, loc="upper left")
    fig.suptitle("Our GFS 0.25 degree phase space against FSU's (digitized), paired at shared valid hours", fontsize=12)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def timing_figure(path: Path, timing: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for ax, key, name in ((axs[0], "onset_values", "onset (first B > 10 m)"),
                          (axs[1], "completion_values", "completion (first -V_T^L < 0 after onset)")):
        vals = [timing[b][key] for b in BANDS]
        allv = [v for vv in vals for v in vv]
        if allv:
            lo, hi = min(allv) - 9, max(allv) + 9
            bins = np.arange(6 * math.floor(lo / 6) - 3, 6 * math.ceil(hi / 6) + 4, 6)
        else:
            bins = np.arange(-27, 28, 6)
        for vv, band, col in zip(vals, BANDS, ("#2471a3", "#d35400")):
            ax.hist(vv, bins=bins, histtype="step", lw=2, color=col,
                    label=f"{band} bands (n {len(vv)}, median {np.median(vv) if vv else float('nan'):.0f} h)")
        ax.axvline(0, color="0.4", lw=0.8)
        ax.set_xlabel("ours minus FSU (h)")
        ax.set_ylabel("storm-cycles")
        ax.set_title(name)
        ax.legend(fontsize=8.5)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def write_md(path: Path, S: dict) -> None:
    def cell(s):
        return f"{s['mean']:+.1f} / {s['rms']:.1f} ({s['n']})" if s["n"] else "n/a (0)"

    L = []
    D = S["digitizing"]
    L.append("# Our cyclone phase space against FSU's, digitized")
    L.append("")
    L.append(f"Generated {S['generated']} by `realtime/fsu_stats.py` from `realtime/data/` "
             f"({D['storm_cycles']} storm-cycles with an FSU match, {D['plots']} FSU plots). "
             "FSU publishes only images; their values here are read off the plots by "
             "`realtime/fsu_digitize.py`. Ours: GFS 0.25 degree, 24 h centered running mean, "
             "paired with FSU (GFS 0.5 degree, its own 24 h mean) at shared valid hours of the same run. "
             "Differences are ours minus FSU, in m. Two band sets: Hart's (hb_hart from the 900-600 hPa "
             "thickness with the track motion, hvtl_hart over 900-600 hPa, hvtu_hart over 600-300 hPa) is the "
             "website's primary set and leads every table; the standard set (hb with the steering-flow motion "
             "from the 925-700 hPa thickness rescaled, hvtl over 925-700 hPa, hvtu over 500-300 hPa) is what "
             "AWIPS CAVE shows.")
    L.append("")
    L.append("## Digitizing")
    L.append("")
    hc = S.get("hand_check")
    L.append(f"- Hours with a timed point on either FSU plot: {D['hours_with_a_point_on_either_plot']}; "
             f"paired with our track: {D['paired_hours_usable']} usable, of which {D['paired_hours_verified']} "
             "verified (timed independently on both plots, with agreeing -V_T^L).")
    s = D["phase1_minus_phase2_vtl_on_verified"]
    L.append(f"- -V_T^L read on phase1 minus phase2 on verified hours: mean {s['mean']} m, RMS {s['rms']} m "
             f"(n {s['n']}); the median error estimate per point is {D['median_error_estimate_m']['b']} m for B, "
             f"{D['median_error_estimate_m']['vtl']} m for -V_T^L and {D['median_error_estimate_m']['vtu']} m "
             "for -V_T^U (0.7 px of center uncertainty, more for a covered or crowded marker, times the axis scale).")
    L.append(f"- Hours timed independently on both plots: {D['hours_timed_on_both_plots']}, of which "
             f"{D['of_which_inconsistent']} ({100 * (D['inconsistent_rate'] or 0):.0f}%) disagreed on -V_T^L "
             "(a walk miscounted a hidden marker or picked a wrong neighbor) and were dropped with the rest of that "
             "walk; the same rate is the best estimate of the timing error among usable points timed on one plot only, "
             "which is why the verified set is the headline.")
    if hc:
        L.append(f"- Against hand readings of {hc['n_hand']} points on five plots: {hc['n_compared']} compared, "
                 f"x RMS {hc['x_minus_hand']['rms']} m (mean {hc['x_minus_hand']['mean']}), "
                 f"y RMS {hc['y_minus_hand']['rms']} m (mean {hc['y_minus_hand']['mean']}); "
                 f"{hc['n_not_digitized']} hand points the digitizer left untimed or dropped.")
    q = D["plot_quality"]
    L.append(f"- Plots: {q.get('closed', 0)} closed, {q.get('partial', 0)} partial, {q.get('failed', 0)} failed, "
             f"{q.get('error', 0)} errors (closed: a walk from the end marker reached the analysis marker, or one "
             "from the start marker of a future cyclone reached the end, with the right count; partial: some hours "
             "timed; failed: none timed, mostly because neither end of the forecast trajectory could be found: the "
             "end under the inset map or in a cluster, the analysis marker's ring hidden). "
             f"Discs found {D['discs']}, of which {D['untimed_discs']} left untimed (clusters of overlapping "
             "markers, markers under the inset map, tangled tracks, analysis hours before the run).")
    bgm = D["background_boundaries_median"]
    L.append(f"- Shading check on the calibration (median over plots of where the background hue changes): "
             f"phase1 B boundary at {bgm['phase1_y10']} m (expected 10), phase2 -V_T^U boundary at "
             f"{bgm['phase2_y0']} m (expected 0); the -V_T^L boundary is a white band of shading around 0 "
             f"(medians {bgm['phase1_x0']} and {bgm['phase2_x0']} m), so it only bounds the calibration loosely.")
    L.append("")
    for setname in ("verified", "usable"):
        T = S["terms"][setname]
        L.append(f"## Bias / RMS (count), {setname} points")
        L.append("")
        L.append("| Term | Bands | All | Warm lower core | Cold lower core | Faster than 20 kt | 20 kt or slower |")
        L.append("|---|---|---|---|---|---|---|")
        for term in TERMS:
            for band, cols in BANDS.items():
                g = T[band][term]
                L.append(f"| {TERM_LABEL[term]} | {band} ({cols[term]}) | {cell(g['all'])} | {cell(g['warm_lower'])} | "
                         f"{cell(g['cold_lower'])} | {cell(g['fast_gt20kt'])} | {cell(g['slow_le20kt'])} |")
        L.append("")
    L.append("## Class agreement (verified points)")
    L.append("")
    L.append("| Bands | All | Faster than 20 kt | 20 kt or slower | B side only (B > 10 m) |")
    L.append("|---|---|---|---|---|")
    for band in BANDS:
        c = S["classes"]["verified"][band]

        def rc(x):
            return f"{100 * x['rate']:.0f}% ({x['agree']}/{x['n']})" if x["n"] else "n/a"
        L.append(f"| {band} | {rc(c['all'])} | {rc(c['fast_gt20kt'])} | {rc(c['slow_le20kt'])} | {rc(c['b_side_agree'])} |")
    L.append("")
    L.append("## Onset and completion timing, ours minus FSU (h), usable points")
    L.append("")
    L.append("Storm-cycles where both sides start symmetric (B <= 10 m) and both cross B = 10 m later (onset), or "
             "start warm and both cross -V_T^L = 0 later, at or after onset (completion).")
    L.append("")
    L.append("| Bands | Onset median / mean (n), within 6 h | Completion median / mean (n), within 6 h |")
    L.append("|---|---|---|")
    for band in BANDS:
        t = S["timing"][band]
        o, c = t["onset_diff_h"], t["completion_diff_h"]
        L.append(f"| {band} | {o['median']} / {o['mean']} ({o['n']}), {t['onset_within_6h']} | "
                 f"{c['median']} / {c['mean']} ({c['n']}), {t['completion_within_6h']} |")
    L.append("")
    L.append("## Our tracks alone: the three B")
    L.append("")
    O = S["own"]
    L.append(f"All {O['n_storm_cycles']} storm-cycles, raw 6-hourly values. hb_hart is Hart's B (900-600 hPa "
             "thickness, track motion), hb_track the rescaled 925-700 hPa thickness with the same track motion, "
             "hb the standard (CAVE) B with the steering-flow motion.")
    L.append("")
    L.append("| motion_kt | hb_hart - hb_track mean / RMS (n) | hb - hb_track mean / RMS (n) | 90th pct of abs | "
             "class differs | B side differs |")
    L.append("|---|---|---|---|---|---|")
    for rec in O["by_motion_kt"]:
        lo, hi = rec["motion_kt"]
        s = rec["hb_minus_hb_track"]
        cd = rec["class_differs"]
        rng = f"{lo} to {hi}" if hi is not None else f"{lo} and up"
        cdr = "n/a" if cd["rate"] is None else f"{100 * cd['rate']:.0f}%"
        bsr = "n/a" if rec["b_side_differs_rate"] is None else f"{100 * rec['b_side_differs_rate']:.0f}%"
        L.append(f"| {rng} | {cell(rec['hb_hart_minus_hb_track'])} | {cell(s)} | {rec['abs_p90']} | "
                 f"{cdr} ({cd['differ']}/{cd['n']}) | {bsr} |")
    L.append("")
    L.append("The last three columns compare hb with hb_track (the steering-flow motion against the track "
             "motion, same thickness).")
    L.append("")
    sh, bs = O["hb_hart_minus_hb_track"], O["hb_hart_vs_hb_track_b_side_differs"]
    bsr = "n/a" if bs["rate"] is None else f"{100 * bs['rate']:.0f}%"
    L.append(f"hb_hart - hb_track (same motion, Hart's thickness against the rescaled one): mean {sh['mean']} m, "
             f"RMS {sh['rms']} m (n {sh['n']}), 5/25/50/75/95th percentiles {O['hb_hart_minus_hb_track_pct']}; "
             f"the two fall on different sides of B = 10 m at {bsr} ({bs['differ']}/{bs['n']}) of the fixes.")
    L.append("")
    s1, s2 = O["hvtl_minus_hvtl_hart"], O["hvtu_minus_hvtu_hart"]
    L.append(f"hvtl - hvtl_hart: mean {s1['mean']} m, RMS {s1['rms']} m (n {s1['n']}), 5/25/50/75/95th percentiles "
             f"{O['hvtl_minus_hvtl_hart_pct']}. hvtu - hvtu_hart: mean {s2['mean']} m, RMS {s2['rms']} m "
             f"(n {s2['n']}), percentiles {O['hvtu_minus_hvtu_hart_pct']}.")
    L.append("")
    L.append("## Caveats")
    L.append("")
    for c in S["caveats"]:
        L.append(f"- {c}")
    L.append("")
    path.write_text("\n".join(L))


CAVEATS = [
    "FSU's values are digitized from 1024 x 768 images: a marker center is good to about a pixel, "
    "which is 0.3 to 3 m depending on the plot's axis range; markers drawn over one another, under the "
    "inset map or along tangled tracks are left untimed rather than guessed.",
    "FSU uses the 0.5 degree GFS and its own tracker; its 24 h running mean includes the days before the run, "
    "ours only the frames of the run, so the first 12 h of a run are smoothed differently.",
    "FSU's B uses its tracker's motion; our Hart set's B (hb_hart) uses the track motion and the 900-600 hPa "
    "thickness, hb_track the track motion with the rescaled 925-700 hPa thickness, and the standard (CAVE) B the "
    "steering-flow proxy; hb is blank where the steering flow is under 2 m/s.",
    "The pairs are not independent: consecutive 6-hourly points of one storm-cycle, and the same storm on "
    "consecutive days, are strongly correlated, so the counts overstate the effective sample size.",
    "Cycles collected before 2026-09-27 used the module's former square 500 km window for the thermal wind "
    "terms (cold cores about 50 m more negative); the archive is to be recomputed.",
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", default=str(HERE / "data"))
    ap.add_argument("--out", default=None, help="output directory (default DATA_DIR/validation)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="only the first N storm-cycles (testing)")
    a = ap.parse_args(argv)
    data = Path(a.data_dir)
    out = Path(a.out) if a.out else data / "validation"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    scs = storm_cycles(data)
    tracks = {(c, s): read_track(d / "track.csv") for c, s, d in scs}
    metas = {(c, s): json.loads((d / "meta.json").read_text()) for c, s, d in scs}
    # a storm-cycle is matched when the collector saved FSU's two plots beside it; a later rerun of
    # a cycle that could not reach FSU's page keeps the plots but leaves meta.json's fsu_number empty
    matched = [(c, s, d) for c, s, d in scs
               if (d / "fsu_phase1.png").exists() and (d / "fsu_phase2.png").exists()]
    n_meta = sum(1 for c, s, d in matched if metas[(c, s)].get("fsu_number") is not None)
    if a.limit:
        matched = matched[:a.limit]
    print(f"{len(scs)} storm-cycles, {len(matched)} with FSU plots ({n_meta} with fsu_number in meta.json); "
          f"digitizing with {a.workers} workers", flush=True)
    if a.workers > 1:
        with Pool(a.workers) as pool:
            digs = pool.map(digitize_one, matched, chunksize=1)
    else:
        digs = [digitize_one(m) for m in matched]
    rows = []
    for d in digs:
        key = (d["cycle"], d["storm"])
        rows += pair_rows(d, tracks[key], metas[key].get("fsu_number"))
    ver = [r for r in rows if r["verified"]]
    S = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
         "definitions": {
             "difference": "ours minus FSU, m; ours is the 24 h centered running mean (track_cps.running_mean)",
             "bands": BANDS, "warm_lower": "FSU -V_T^L >= 0", "fast": f"our motion_kt > {FAST_KT:g}",
             "class": "cps_HartCPS.hart_class table: B > 10 m asymmetric, thermal wind term warm if >= 0",
             "onset": "first hour B > 10 m", "completion": "first hour -V_T^L < 0 at or after onset",
             "verified": "hour timed independently on both FSU plots, -V_T^L agreeing within max(1.5 m, 3 sigma)",
             "usable": "verified plus hours timed on one FSU plot (or carried to the other by marker matching)"},
         "digitizing": digitizer_stats(digs, rows),
         "storm_cycles": {"ok": len(scs), "with_fsu_plots": len(matched), "with_fsu_number_in_meta": n_meta},
         "terms": {"verified": term_stats(ver), "usable": term_stats(rows),
                   "verified_fsu_number_in_meta": term_stats([r for r in ver if r["fsu_number"] is not None])},
         "classes": {"verified": class_stats(ver), "usable": class_stats(rows)},
         "timing": timing_stats(rows),
         "own": own_stats(list(tracks.values())),
         "caveats": CAVEATS}
    S["hand_check"] = hand_check({(d["cycle"], d["storm"]): d for d in digs}, out / "hand_digitized.csv")
    S["per_storm_cycle"] = [{"cycle": d["cycle"], "storm": d["storm"], "quality": d["quality"],
                             "header": d["header"], "points": len(d["rows"]), "error": d["error"],
                             "notes": d["notes"], "seconds": d["seconds"]} for d in digs]
    write_pairs(out / "fsu_pairs.csv", rows)
    (out / "fsu_stats.json").write_text(json.dumps(S, indent=1, default=lambda o: None if o is None else
                                                   (float(o) if isinstance(o, (np.floating, np.integer)) else str(o))) + "\n")
    write_md(out / "fsu_stats.md", S)
    scatter_figure(out / "fig_fsu_scatter.png", rows, S["terms"]["verified"])
    timing_figure(out / "fig_fsu_timing.png", S["timing"])
    print(f"{len(rows)} paired hours ({len(ver)} verified); wrote {out} in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
