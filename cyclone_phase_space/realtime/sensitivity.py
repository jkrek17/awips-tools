#!/usr/bin/env python3
"""Sensitivity of the Hart class (HCPSclass) to the class boundaries, to the
center position, and to the closed-low detector.

    python3 sensitivity.py [--data-dir DIR] [--cycle 2026100200] [--hours 96 138 168]
                           [--cache DIR] [--out-dir DIR] [--reuse-frames]

1. Boundary margins, from every track.csv of the daily archive: per fix,
   the distance of B (hb, the product's steering-proxy B) from 10 m and of
   each thermal wind (hvtl, hvtu) from 0, the margin to the nearest
   boundary that can change the class (B is irrelevant for code 6, shallow
   cold core; for a code 0 to 5 fix all three count), and the fractions of
   fixes within 2, 5 and 10 m of it, overall and per class; and class
   flicker: the fraction of 6 h steps at which the class changes and is
   back to the previous class 6 or 12 h later.
2. Center displacement, on real fields: three frames of one archived cycle
   (global grid, Hart's levels, as collect_daily fetches them) run through
   compute_products. Centers are the exporter's (export_web.lows_features):
   one per connected blob of finite HCPSclass, at the blob's MSLP minimum;
   the tracker's candidates inside a blob (track_cps.all_centers with a
   finite class) are a second set. At each center the class and the
   three values are compared with the eight grid points one cell away and
   with the four points 50 km and 100 km away along the axes (class at the
   nearest grid point, values bilinear, as the tracker samples them).
3. Detector selection, same frames: the tracker's candidate minima
   (all_centers), how many lie inside the closed-low mask with a 2 hPa ring
   (track_cps.closed_mask) and with the product's 5 hPa ring
   (closed_low_mask as executeHartClass calls it), and how many have a
   class, by central pressure and latitude band.

Writes <out-dir>/sensitivity.md, fig_sensitivity.png and
sensitivity_frames.json (the per-frame results, reused with
--reuse-frames).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gfs_cps as g  # noqa: E402
import track_cps as tc  # noqa: E402

hc = g.hc
DATA = HERE / "data"
B_THR = 10.0
NEAR_M = (2.0, 5.0, 10.0)
RINGS_KM = (50.0, 100.0)
P_BINS = (("below 980", -np.inf, 980.0), ("980 to 1000", 980.0, 1000.0), ("above 1000", 1000.0, np.inf))
LAT_BINS = (("0 to 25", 0.0, 25.0), ("25 to 60", 25.0, 60.0), ("60 to 85", 60.0, 85.0 + 1e-9))
CLASS_NAMES = tc.CLASS_SHORT


def code_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True,
                              check=True, timeout=60).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def fnum(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return float("nan")


# ------------------------------------------------------------------ 1. margins
def relevant_margin(cls: float, hb: float, vtl: float, vtu: float) -> float:
    """Distance (m) to the nearest boundary that can change this class: for
    code 6 only the two thermal winds count (B does not enter it); otherwise
    all three. NaN where a needed value is missing."""
    if not np.isfinite(cls):
        return float("nan")
    terms = [abs(vtl), abs(vtu)] if int(cls) == 6 else [abs(hb - B_THR), abs(vtl), abs(vtu)]
    return float(min(terms)) if all(np.isfinite(terms)) else float("nan")


def read_archive(data_dir: Path) -> list[list[dict]]:
    tracks = []
    for tp in sorted(data_dir.glob("[0-9]" * 10 + "/*/track.csv")):
        with tp.open() as fh:
            rows = list(csv.DictReader(fh))
        fixes = [dict(cycle=tp.parent.parent.name, storm=tp.parent.name, fhr=int(r["fhr"]), cls=fnum(r["class"]),
                      hb=fnum(r["hb"]), vtl=fnum(r["hvtl"]), vtu=fnum(r["hvtu"])) for r in rows]
        tracks.append(fixes)
    return tracks


def margins(tracks: list[list[dict]]) -> dict:
    fx = [f for t in tracks for f in t]
    out = {"tracks": len(tracks), "fixes": len(fx)}
    cls = np.array([f["cls"] for f in fx])
    hb = np.array([f["hb"] for f in fx])
    vtl = np.array([f["vtl"] for f in fx])
    vtu = np.array([f["vtu"] for f in fx])
    rel = np.array([relevant_margin(*v) for v in zip(cls, hb, vtl, vtu)])
    out["classed"] = int(np.isfinite(cls).sum())
    out["dist"] = {"B": np.abs(hb - B_THR), "VTL": np.abs(vtl), "VTU": np.abs(vtu), "relevant": rel}

    def frac(a):
        a = a[np.isfinite(a)]
        return {"n": int(a.size), **{f"{m:g}": float((a < m).mean()) if a.size else float("nan") for m in NEAR_M},
                "median": float(np.median(a)) if a.size else float("nan")}

    out["overall"] = {k: frac(v[np.isfinite(cls)]) for k, v in out["dist"].items()}
    out["all_fixes"] = {k: frac(v) for k, v in out["dist"].items() if k != "relevant"}
    out["per_class"] = {}
    for c in range(7):
        sel = cls == c
        if sel.any():
            out["per_class"][c] = {k: frac(v[sel]) for k, v in out["dist"].items()}
    # flicker
    steps = changes = flick = flick6 = 0
    for t in tracks:
        by = {f["fhr"]: f["cls"] for f in t}
        for f in t:
            h0 = f["fhr"]
            a, b = by.get(h0), by.get(h0 + 6)
            if a is None or b is None or not (np.isfinite(a) and np.isfinite(b)):
                continue
            steps += 1
            if a == b:
                continue
            changes += 1
            back6 = by.get(h0 + 12)
            back12 = by.get(h0 + 18)
            if back6 is not None and back6 == a:
                flick += 1
                flick6 += 1
            elif back12 is not None and back12 == a:
                flick += 1
    out["flicker"] = dict(steps=steps, changes=changes, flickers=flick, flickers_6h=flick6,
                          frac_steps=flick / steps if steps else float("nan"),
                          frac_changes=flick / changes if changes else float("nan"),
                          change_rate=changes / steps if steps else float("nan"))
    return out


# ------------------------------------------------------------------ frames
def mask5(f: dict) -> np.ndarray:
    """closed_low_mask as executeHartClass calls it (5 hPa ring, 200 km blob)."""
    dx, dy, _ = g.grid_metrics(f["lat"], f["lon"].size)
    return hc.closed_low_mask(hc.pmsl_input_hpa(f["pmsl"], hc.PMSL_KIND_PRESSURE), dx, dy, hc.MIN_RADIUS_KM,
                              hc.RADIUS_KM, hc.DEFAULT_DEPTH_HPA, hc.DEFAULT_BLOB_RADIUS_KM)


def exporter_centers(f: dict, p: dict) -> list[tuple[int, int]]:
    """export_web.lows_features's rule: one center per connected blob of
    finite HCPSclass, at the blob's MSLP minimum."""
    pm = f["pmsl"]
    out = []
    for blob in g.label_blobs(np.isfinite(p["cls"]), wrap=True):
        k = int(blob[np.argmin(pm.flat[blob])])
        out.append(divmod(k, pm.shape[1]))
    return out


def displacement(f: dict, p: dict, centers: list[tuple[int, int]]) -> list[dict]:
    cls, ny, nx = p["cls"], p["cls"].shape[0], p["cls"].shape[1]
    dy_km = g.RES_DEG * g.KM_PER_DEG
    recs = []
    for i, j in centers:
        lat = float(f["lat"][i])
        c0 = float(cls[i, j])
        v0 = {k: float(p[k][i, j]) for k in ("hb", "hvtl", "hvtu")}
        rec = dict(lat=lat, lon=float(tc.wrap180(f["lon"][j])), mslp=float(f["pmsl"][i, j] / 100.0), cls=c0,
                   **{k: v for k, v in v0.items()}, rings={})
        pts = {"1 cell": [(i + di, j + dj, True) for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj]}
        for d in RINGS_KM:
            dj = d / (dy_km * max(math.cos(math.radians(lat)), 0.05))
            di = d / dy_km
            pts[f"{d:g} km"] = [(i + di, j, False), (i - di, j, False), (i, j + dj, False), (i, j - dj, False)]
        for ring, plist in pts.items():
            diff = nan = 0
            dv = {k: [] for k in v0}
            for fi, fj, on_grid in plist:
                if fi < 0 or fi > ny - 1:
                    continue
                c1 = tc.nearest(cls, fi, fj)
                if not np.isfinite(c1):
                    nan += 1
                    diff += 1
                elif c1 != c0:
                    diff += 1
                for k in v0:
                    v1 = float(p[k][int(fi), int(fj) % nx]) if on_grid else tc.bilinear(p[k], fi, fj)
                    if np.isfinite(v1) and np.isfinite(v0[k]):
                        dv[k].append(abs(v1 - v0[k]))
            rec["rings"][ring] = dict(points=len(plist), differ=diff, blank=nan, dv=dv)
        recs.append(rec)
    return recs


def detector(f: dict, p: dict) -> list[dict]:
    m2 = tc.closed_mask(f)
    m5 = mask5(f)
    out = []
    for i, j, m in tc.all_centers(f, True):
        lat = float(f["lat"][i])
        out.append(dict(lat=lat, mslp=m, c2=bool(m2[i, j]), c5=bool(m5[i, j]),
                        c2_at=bool(tc.closed_at(f, m2, lat, float(f["lon"][j]), True)),
                        cls=bool(np.isfinite(p["cls"][i, j]))))
    return out


def run_frames(cycle: str, hours: list[int], cache: Path) -> dict:
    res = {"cycle": cycle, "hours": hours, "frames": {}}
    for h in hours:
        grib = g.get_grib(cycle, h, "global", cache, "nomads", True)
        f = g.decode(grib, "global", True)
        p = g.compute_products(f)
        exp = exporter_centers(f, p)
        cand = [(i, j) for i, j, _ in tc.all_centers(f, True) if np.isfinite(p["cls"][i, j])]
        res["frames"][str(h)] = dict(source=grib.name, exporter=displacement(f, p, exp),
                                     candidates=displacement(f, p, cand), detector=detector(f, p))
        print(f"f{h:03d}: {len(exp)} exporter centers, {len(cand)} candidate centers with a class, "
              f"{len(res['frames'][str(h)]['detector'])} candidate minima", flush=True)
    return res


def summarize_displacement(recs: list[dict]) -> dict:
    out = {"centers": len(recs)}
    for ring in ["1 cell"] + [f"{d:g} km" for d in RINGS_KM]:
        rs = [r["rings"][ring] for r in recs]
        n_pts = sum(r["points"] for r in rs)
        dv = {k: [x for r in rs for x in r["dv"][k]] for k in ("hb", "hvtl", "hvtu")}
        out[ring] = dict(any_differ=sum(r["differ"] > 0 for r in rs), points=n_pts,
                         any_flip=sum(r["differ"] - r["blank"] > 0 for r in rs),
                         points_differ=sum(r["differ"] for r in rs), points_blank=sum(r["blank"] for r in rs),
                         majority_differ=sum(r["differ"] * 2 > r["points"] for r in rs),
                         median={k: float(np.median(v)) if v else float("nan") for k, v in dv.items()},
                         p90={k: float(np.percentile(v, 90)) if v else float("nan") for k, v in dv.items()})
    return out


def bin_of(v: float, bins) -> str:
    for name, lo, hi in bins:
        if lo <= v < hi:
            return name
    return "other"


# ------------------------------------------------------------------ report
def pct(a, b) -> str:
    return "n/a" if not b else f"{100.0 * a / b:.0f}% ({a}/{b})"


def write_report(out_dir: Path, mg: dict, fr: dict, head: str, data_dir: Path) -> None:
    L = [f"# Sensitivity of the class to boundaries, center position and detector", "",
         f"Code version: `{head}` (git rev-parse --short HEAD). Written by `sensitivity.py`. Archive: "
         f"`{data_dir.name}/` ({mg['tracks']} tracks, {mg['fixes']} fixes, {mg['classed']} with a class). Frames: "
         f"GFS {fr['cycle']} at " + ", ".join(f"F{h:03d}" for h in fr["hours"]) + " (global 0.25 degree grid, "
         "Hart's levels, compute_products as in collect_daily).", "",
         "## 1. Boundary margins in the archive", "",
         "Per fix: |B - 10 m| (hb, the product's steering-proxy B), |V_T^L| and |V_T^U| (hvtl, hvtu, m), and the "
         "margin to the nearest boundary that can change the fix's class (B does not enter code 6). Fixes with a "
         "class (class at the nearest grid point of the center).", "",
         "| Distance | Fixes | within 2 m | within 5 m | within 10 m | median (m) |", "|---|---|---|---|---|---|"]
    for k, lab in (("relevant", "nearest relevant boundary"), ("B", "B from 10 m"), ("VTL", "V_T^L from 0"),
                   ("VTU", "V_T^U from 0")):
        o = mg["overall"][k]
        L.append(f"| {lab} | {o['n']} | {100 * o['2']:.0f}% | {100 * o['5']:.0f}% | {100 * o['10']:.0f}% | "
                 f"{o['median']:.1f} |")
    L += ["", "Per class (nearest relevant boundary; the B, V_T^L and V_T^U columns give the share within 5 m of "
          "each line):", "",
          "| Class | Fixes | within 2 m | within 5 m | within 10 m | median (m) | B within 5 m | V_T^L within 5 m | "
          "V_T^U within 5 m |", "|---|---|---|---|---|---|---|---|---|"]
    for c, d in sorted(mg["per_class"].items()):
        o = d["relevant"]
        L.append(f"| {c} {CLASS_NAMES[c]} | {o['n']} | {100 * o['2']:.0f}% | {100 * o['5']:.0f}% | "
                 f"{100 * o['10']:.0f}% | {o['median']:.1f} | {100 * d['B']['5']:.0f}% | {100 * d['VTL']['5']:.0f}% | "
                 f"{100 * d['VTU']['5']:.0f}% |")
    fl = mg["flicker"]
    L += ["", f"Flicker: of {fl['steps']} 6 h steps with a class at both ends, the class changes at "
          f"{fl['changes']} ({100 * fl['change_rate']:.0f}%); {fl['flickers']} of those changes "
          f"({100 * fl['frac_changes']:.0f}% of changes, {100 * fl['frac_steps']:.1f}% of steps) are back to the "
          f"previous class within 12 h ({fl['flickers_6h']} after a single 6 h fix, the rest after two). Steps "
          "into or out of a blank class (no closed low, B blank) are not counted.", ""]
    # displacement
    L += ["## 2. Class change under a center displacement", "",
          "Each center's class (grid point) against the eight grid points one cell (0.25 degree, about 28 km "
          "north-south) away and the four points 50 km and 100 km away along the axes (class at the nearest "
          "grid point, values bilinear). A blank point (outside the class blob, below ground or B blank) counts "
          "as a different class; the column \"another non-blank class\" counts only a real change of class. "
          "Centers: first the tracker's candidate minima that have a class (`all_centers`: terrain masked, under "
          "1018 hPa, within 85 degrees of the equator); then the exporter's, one per connected class blob at its "
          "MSLP minimum. The exporter's set includes blob fragments cut by below-ground blanking (Antarctica, "
          "the Andes, the Tibetan plateau, the Rockies), whose MSLP minimum lies on the edge of the fragment, "
          "so its blank counts are high; the first set is the one that describes tracked lows.", ""]
    for key, lab in (("candidates", "Tracker candidates with a class"), ("exporter", "Exporter centers")):
        recs = [r for h in fr["frames"].values() for r in h[key]]
        s = summarize_displacement(recs)
        per = ", ".join(f"F{int(h):03d} {len(v[key])}" for h, v in fr["frames"].items())
        L += [f"**{lab}**: {s['centers']} ({per}).", "",
              "| Displacement | Centers with any point of another class | Centers with any point of another "
              "non-blank class | Points of another class | of them blank | Centers where most points differ | "
              "median abs change B / V_T^L / V_T^U (m) | 90th percentile (m) |",
              "|---|---|---|---|---|---|---|---|"]
        for ring in ["1 cell"] + [f"{d:g} km" for d in RINGS_KM]:
            o = s[ring]
            L.append(f"| {ring} | {pct(o['any_differ'], s['centers'])} | {pct(o['any_flip'], s['centers'])} | "
                     f"{pct(o['points_differ'], o['points'])} | "
                     f"{o['points_blank']} | {pct(o['majority_differ'], s['centers'])} | "
                     f"{o['median']['hb']:.1f} / {o['median']['hvtl']:.1f} / {o['median']['hvtu']:.1f} | "
                     f"{o['p90']['hb']:.1f} / {o['p90']['hvtl']:.1f} / {o['p90']['hvtu']:.1f} |")
        L.append("")
    # detector
    det = [d for h in fr["frames"].values() for d in h["detector"]]
    L += ["## 3. Detector selection", "",
          "Candidate minima: every point `track_cps.all_centers` accepts (lowest of its +/- 1 degree box after "
          "terrain is masked, MSLP under 1018 hPa, within 85 degrees of the equator), both hemispheres, summed "
          "over the three frames (" + ", ".join(f"F{int(h):03d} {len(v['detector'])}" for h, v in
                                                 fr["frames"].items()) + "). Closed 2 hPa: inside "
          "`closed_low_mask` with a 2 hPa ring (the tracker's `closed_mask`) at the minimum itself; in brackets "
          "the tracker's own test (`closed_at`, the mask at the deepest MSLP within 300 km). Closed 5 hPa: inside "
          "the product's mask (`closed_low_mask` with depth 5 hPa, as `executeHartClass` calls it). Class: "
          "HCPSclass finite at the minimum (also needs B and the band levels).", "",
          "| Bin | Minima | Closed 2 hPa (closed_at) | Closed 5 hPa | With a class |", "|---|---|---|---|---|"]

    def rows(sel_name, bins, key):
        for name, _, _ in bins:
            ds = [d for d in det if bin_of(key(d), bins) == name]
            n = len(ds)
            L.append(f"| {sel_name} {name} | {n} | {pct(sum(d['c2'] for d in ds), n)} "
                     f"({pct(sum(d['c2_at'] for d in ds), n)}) | {pct(sum(d['c5'] for d in ds), n)} | "
                     f"{pct(sum(d['cls'] for d in ds), n)} |")

    n = len(det)
    L.append(f"| all | {n} | {pct(sum(d['c2'] for d in det), n)} ({pct(sum(d['c2_at'] for d in det), n)}) | "
             f"{pct(sum(d['c5'] for d in det), n)} | {pct(sum(d['cls'] for d in det), n)} |")
    rows("MSLP (hPa)", P_BINS, lambda d: d["mslp"])
    rows("latitude", LAT_BINS, lambda d: abs(d["lat"]))
    L += ["", "Central pressure by latitude band (minima, then the share with a class):", "",
          "| Latitude | " + " | ".join(b[0] + " hPa" for b in P_BINS) + " |", "|---" * (len(P_BINS) + 1) + "|"]
    for lname, lo, hi in LAT_BINS:
        cells = []
        for pname, plo, phi in P_BINS:
            ds = [d for d in det if lo <= abs(d["lat"]) < hi and plo <= d["mslp"] < phi]
            cells.append(f"{len(ds)}, {pct(sum(d['cls'] for d in ds), len(ds))}")
        L.append(f"| {lname} | " + " | ".join(cells) + " |")
    L += ["", "![Margins and displacement](fig_sensitivity.png)", ""]
    (out_dir / "sensitivity.md").write_text("\n".join(L) + "\n")


def write_figure(out_dir: Path, mg: dict, fr: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2, grid = "#0b0b0b", "#52514e", "#e4e3df"
    cols = {"relevant": "#2a78d6", "B": "#eb6834", "VTL": "#1baf7a", "VTU": "#eda100"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), dpi=150, facecolor="#fcfcfb")
    ax = axes[0]
    xs = np.linspace(0, 40, 401)
    for k, lab in (("relevant", "nearest relevant boundary"), ("B", "|B - 10|"), ("VTL", "|V_T^L|"),
                   ("VTU", "|V_T^U|")):
        a = mg["dist"][k]
        a = np.sort(a[np.isfinite(a)])
        ax.plot(xs, 100 * np.searchsorted(a, xs, side="right") / max(a.size, 1), lw=2.4 if k == "relevant" else 1.6,
                color=cols[k], label=lab)
    for m in NEAR_M:
        ax.axvline(m, color=grid, lw=1, zorder=0)
    ax.set_xlim(0, 40)
    ax.set_ylim(0, 100)
    ax.set_xlabel("distance from the class boundary (m)", color=ink2)
    ax.set_ylabel("share of classed archive fixes within that distance (%)", color=ink2)
    ax.set_title(f"(a) Boundary margins, {mg['classed']} classed fixes", color=ink, loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax = axes[1]
    s = summarize_displacement([r for h in fr["frames"].values() for r in h["candidates"]])
    rings = ["1 cell"] + [f"{d:g} km" for d in RINGS_KM]
    x = np.arange(len(rings))
    series = [("centers with any displaced point of another class or blank", "#2a78d6",
               [100 * s[r]["any_differ"] / max(s["centers"], 1) for r in rings]),
              ("centers with any displaced point of another non-blank class", "#1baf7a",
               [100 * s[r]["any_flip"] / max(s["centers"], 1) for r in rings]),
              ("displaced points of another class or blank", "#eb6834",
               [100 * s[r]["points_differ"] / max(s[r]["points"], 1) for r in rings])]
    w = 0.26
    for k, (lab, col, vals) in enumerate(series):
        xs = x + (k - 1) * w
        ax.bar(xs, vals, w - 0.03, color=col, label=lab)
        for xi, v in zip(xs, vals):
            ax.text(xi, v + 1, f"{v:.0f}%", ha="center", fontsize=8, color=ink)
    ax.set_xticks(x, rings)
    ax.set_ylim(0, 105)
    ax.set_ylabel("%", color=ink2)
    ax.set_title(f"(b) Class at displaced points, {s['centers']} classed minima, GFS {fr['cycle']}", color=ink,
                 loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    for a in axes:
        a.set_facecolor("#fcfcfb")
        a.grid(axis="y", color=grid, lw=0.8)
        a.set_axisbelow(True)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            a.spines[sp].set_color(ink2)
        a.tick_params(colors=ink2)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_sensitivity.png", facecolor=fig.get_facecolor())


def jsonable(o):
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, (np.integer, np.bool_)):
        return o.item()
    return o


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--cycle", default="2026100200")
    ap.add_argument("--hours", type=int, nargs="+", default=[96, 138, 168])
    ap.add_argument("--cache", type=Path, default=HERE / "out" / "cache" / "sensitivity")
    ap.add_argument("--out-dir", type=Path, default=DATA / "validation")
    ap.add_argument("--reuse-frames", action="store_true", help="reuse sensitivity_frames.json")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    fj = a.out_dir / "sensitivity_frames.json"
    if a.reuse_frames and fj.exists():
        fr = json.loads(fj.read_text())
    else:
        fr = jsonable(run_frames(a.cycle, a.hours, a.cache / a.cycle))
        fj.write_text(json.dumps(fr, separators=(",", ":")) + "\n")
    for h in fr["frames"].values():  # JSON nulls back to NaN
        for key in ("exporter", "candidates"):
            for r in h[key]:
                if r["cls"] is None:
                    r["cls"] = float("nan")
    mg = margins(read_archive(a.data_dir))
    head = code_version()
    write_report(a.out_dir, mg, fr, head, a.data_dir)
    write_figure(a.out_dir, mg, fr)
    print(f"wrote {a.out_dir / 'sensitivity.md'} and fig_sensitivity.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
