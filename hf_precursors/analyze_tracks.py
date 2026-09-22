"""The reformulated analysis: one cohort, one detector, two outcomes.

Every low in the basin was found, described and tracked the same way, so
hurricane-force tracks and the rest differ in what happened to them, not in
how they were measured. That removes the defect that invalidated the matched
case-control pass, and it makes the plain comparisons below meaningful
without any matching at all.

Two outcomes are carried side by side:

    the ARCHIVE LABEL -- did an analyst record hurricane force. Ground truth
    about wind, but conditioned on someone having seen it.

    ERA5's own MAX GUST near the low -- measured identically for every track
    in the record, and continuous, so it carries far more information than a
    binary. It under-represents real peak winds, being a smoothed analysis,
    but it is uniformly smoothed.

Where the two agree, the finding is about weather. Where they disagree, the
difference is about the observing system, and that is worth knowing too.

THE HYPOTHESIS UNDER TEST. Hurricane force comes from a tight gradient
rather than a deep centre, so at a given depth the COMPACT low should be the
windy one. In a regression of wind on depth and scale that is a NEGATIVE
coefficient on scale. A positive one says the opposite: bigger storms are
windier. The sign is the whole test.
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXPLORE = (2020, 2022, 2024)
CONFIRM = (2021, 2023, 2025)

NUM = ("min_p", "peak_depth", "peak_scale_km", "peak_grad", "peak_vg_kt",
       "max_wind_kt", "max_gust_kt", "peak_wind_dist_km", "pre_depth",
       "pre_scale_km", "pre_grad", "pre_vg_kt", "pre_p", "pre_lat",
       "deepen24", "peak_lat")


def load():
    with open(HERE / "data" / "tracks.csv") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in NUM:
            r[k] = float(r[k]) if r[k] not in ("", "nan") else np.nan
        r["hf"] = int(r["hf"])
        r["season"] = int(r["season"])
        r["n"] = int(r["n"])
    return rows


def ols(y, X, names):
    """Least squares with standard errors. X without an intercept column."""
    A = np.column_stack([np.ones(len(y))] + [X[:, i] for i in range(X.shape[1])])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    dof = len(y) - A.shape[1]
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.inv(A.T @ A)
    se = np.sqrt(np.diag(cov))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / ss_tot
    print(f"      {'term':<22} {'coef':>10} {'se':>9} {'t':>7}")
    for nm, b, s in zip(["intercept"] + names, beta, se):
        print(f"      {nm:<22} {b:>10.4f} {s:>9.4f} {b / s:>7.2f}")
    print(f"      R2 = {r2:.3f}   n = {len(y)}")
    return beta, se, r2


def logistic(y, X, names, iters=60):
    """Newton-Raphson logistic regression, with standard errors."""
    A = np.column_stack([np.ones(len(y))] + [X[:, i] for i in range(X.shape[1])])
    b = np.zeros(A.shape[1])
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-A @ b))
        W = p * (1 - p)
        g = A.T @ (y - p)
        H = (A * W[:, None]).T @ A
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        b = b + step
        if np.max(np.abs(step)) < 1e-9:
            break
    p = 1.0 / (1.0 + np.exp(-A @ b))
    W = p * (1 - p)
    try:
        se = np.sqrt(np.diag(np.linalg.inv((A * W[:, None]).T @ A)))
    except np.linalg.LinAlgError:
        se = np.full(len(b), np.nan)
    print(f"      {'term':<22} {'coef':>10} {'se':>9} {'z':>7} {'OR':>9}")
    for nm, bi, s in zip(["intercept"] + names, b, se):
        print(f"      {nm:<22} {bi:>10.4f} {s:>9.4f} {bi / s:>7.2f} "
              f"{math.exp(bi) if abs(bi) < 20 else float('inf'):>9.4f}")
    return b, se


def clean(rows, cols):
    keep = [r for r in rows if all(np.isfinite(r[c]) for c in cols)]
    return keep


def compare(rows, label):
    hf = [r for r in rows if r["hf"] == 1]
    no = [r for r in rows if r["hf"] == 0]
    print(f"\n  {label}: {len(hf)} hurricane-force tracks, {len(no)} others")
    print(f"  {'variable':<20} {'HF':>10} {'not HF':>10} {'diff':>10}")
    print("  " + "-" * 54)
    for v in ("min_p", "peak_depth", "peak_scale_km", "peak_grad", "peak_vg_kt",
              "max_wind_kt", "max_gust_kt", "peak_wind_dist_km", "deepen24"):
        a = np.nanmedian([r[v] for r in hf])
        b = np.nanmedian([r[v] for r in no])
        print(f"  {v:<20} {a:>10.1f} {b:>10.1f} {a - b:>+10.1f}")


def label_check(rows):
    """How well does the archive's label line up with ERA5's own wind?"""
    print("\n  DO THE TWO OUTCOMES AGREE?")
    ok = clean(rows, ["max_gust_kt"])
    hf = np.array([r["max_gust_kt"] for r in ok if r["hf"] == 1])
    no = np.array([r["max_gust_kt"] for r in ok if r["hf"] == 0])
    print(f"      ERA5 max gust, HF tracks:     median {np.median(hf):.0f} kt, "
          f"10th-90th {np.percentile(hf, 10):.0f}-{np.percentile(hf, 90):.0f}")
    print(f"      ERA5 max gust, other tracks:  median {np.median(no):.0f} kt, "
          f"10th-90th {np.percentile(no, 10):.0f}-{np.percentile(no, 90):.0f}")
    # Where would a gust threshold put the two populations?
    for thr in (50, 60, 64, 70):
        tp = (hf >= thr).mean() * 100
        fp = (no >= thr).mean() * 100
        print(f"      gust >= {thr} kt: {tp:4.0f}% of HF tracks, {fp:4.0f}% of others")
    over = (no >= np.median(hf)).sum()
    print(f"      {over} non-HF tracks reach the HF tracks' median gust -- "
          "either missed events or lows that were strong without being seen")


def hypothesis(rows, when, dcol, scol, gcol, vcol):
    print(f"\n  THE SIGN TEST, {when}")
    ok = clean(rows, [dcol, scol, "max_gust_kt"])
    y = np.array([r["max_gust_kt"] for r in ok])
    X = np.column_stack([[r[dcol] for r in ok], [r[scol] for r in ok]])
    print("    ERA5 max gust on depth and scale:")
    beta, se, _ = ols(y, X, ["depth (hPa)", "scale (km)"])
    sign = "NEGATIVE -- compact is windier" if beta[2] < 0 else \
           "POSITIVE -- broad is windier"
    print(f"    -> scale coefficient is {sign}")

    print("\n    archive hurricane-force label on depth and scale:")
    yb = np.array([float(r["hf"]) for r in ok])
    logistic(yb, X, ["depth (hPa)", "scale (km)"])

    print("\n    gradient alone (depth/scale), against each outcome:")
    ok2 = clean(rows, [gcol, "max_gust_kt"])
    y2 = np.array([r["max_gust_kt"] for r in ok2])
    X2 = np.column_stack([[r[gcol] for r in ok2]])
    ols(y2, X2, ["gradient (hPa/100km)"])
    logistic(np.array([float(r["hf"]) for r in ok2]), X2,
             ["gradient (hPa/100km)"])


def run(rows, seasons, label):
    sel = [r for r in rows if r["season"] in seasons]
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    compare(sel, "tracks")
    label_check(sel)
    hypothesis(sel, "AT THE TRACK'S OWN PEAK",
               "peak_depth", "peak_scale_km", "peak_grad", "peak_vg_kt")
    hypothesis(sel, "24 H BEFORE THE PEAK (the forecast position)",
               "pre_depth", "pre_scale_km", "pre_grad", "pre_vg_kt")


if __name__ == "__main__":
    rows = load()
    run(rows, EXPLORE, "EXPLORATION seasons 2020, 2022, 2024")
    if "--confirm" in sys.argv:
        run(rows, CONFIRM, "CONFIRMATION seasons 2021, 2023, 2025")
    else:
        print("\n(confirmation seasons withheld)")
