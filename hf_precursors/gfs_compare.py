"""The operational test: does the phase space add to the model's own forecast?

SPLIT. GFS on the AWS archive begins in 2021, which covers the confirmation
seasons but not all of the exploration ones, so the fit/score split used
everywhere else is unavailable here. Instead the confirmation seasons are
split among themselves: fitted on 2021 and 2023, scored on 2025. That is a
smaller test than the rest of this study and it is a genuinely held-out
season, which matters more than its size.

LADDER.
    1  depth + sustained wind now                      the surface, as before
    2  + GFS f024 wind                       what a forecaster actually has
    3  + HVTL and HVTU                       what a panel would add
Rung 3 over rung 2 is the whole question. Rung 2 over rung 1 is worth seeing
too: it says how much the model's forecast is worth over the analysis.
"""
from __future__ import annotations

import contextlib
import csv
import glob
import io
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from analyze_tracks import logistic  # noqa: E402
from leadtime import auc  # noqa: E402

FIT = (2021, 2023)
TEST = (2025,)


def load():
    rows = []
    for p in sorted([str(HERE / "data" / "gfs_all.csv")]):
        with open(p) as fh:
            rows += list(csv.DictReader(fh))
    out = []
    for r in rows:
        for k, v in list(r.items()):
            if k in ("track", "when", "dt"):
                continue
            r[k] = float(v) if v not in ("", "nan") else np.nan
        d = datetime.strptime(r["when"], "%Y-%m-%d %H")
        r["season"] = d.year if d.month >= 7 else d.year - 1
        out.append(r)
    return out


def fit_score(rows, cols):
    tr = [r for r in rows if r["season"] in FIT
          and all(np.isfinite(r[c]) for c in cols)]
    te = [r for r in rows if r["season"] in TEST
          and all(np.isfinite(r[c]) for c in cols)]
    if len(tr) < 40 or len(te) < 40:
        return np.nan, None, None
    X = np.column_stack([[r[c] for r in tr] for c in cols])
    y = np.array([r["hf24"] for r in tr], float)
    with contextlib.redirect_stdout(io.StringIO()):
        b, _ = logistic(y, X, cols)
    Xte = np.column_stack([np.ones(len(te))] + [[r[c] for r in te] for c in cols])
    p = 1.0 / (1.0 + np.exp(-(Xte @ b)))
    lab = np.array([int(r["hf24"]) for r in te])
    return auc(list(lab), list(p)), lab, p


def far_at(lab, p, target=0.80):
    for thr in np.linspace(0.99, 0.01, 400):
        f = p >= thr
        tp = int((f & (lab == 1)).sum())
        fp = int((f & (lab == 0)).sum())
        fn = int((~f & (lab == 1)).sum())
        if tp + fn and tp / (tp + fn) >= target:
            return fp / (tp + fp), fp, fn
    return np.nan, np.nan, np.nan


LADDER = [
    ("1  depth + sustained wind now", ["depth_pw", "wind_kt"]),
    ("2  + GFS f024 forecast wind", ["depth_pw", "wind_kt", "gfs_f024_kt"]),
    ("3  + HVTL and HVTU", ["depth_pw", "wind_kt", "gfs_f024_kt", "hvtl", "hvtu"]),
    ("   GFS f024 wind alone", ["gfs_f024_kt"]),
    ("   phase space without the forecast",
     ["depth_pw", "wind_kt", "hvtl", "hvtu"]),
]


def main():
    rows = load()
    have = [r for r in rows if np.isfinite(r["gfs_f024_kt"])]
    te_n = sum(1 for r in have if r["season"] in TEST)
    print(f"{len(rows)} lows, {len(have)} with a GFS f024 forecast")
    print(f"fit on seasons {FIT} ({len(have) - te_n} lows), "
          f"score on {TEST} ({te_n} lows)\n")
    print(f"  {'model':<40} {'AUC':>7} {'FAR@POD.80':>12} {'false':>7}")
    print("  " + "-" * 70)
    prev = None
    for name, cols in LADDER:
        a, lab, p = fit_score(have, cols)
        if not np.isfinite(a):
            print(f"  {name:<40}   too few")
            continue
        far, fp, fn = far_at(lab, p)
        gain = f"  ({a - prev:+.3f})" if prev is not None and name.startswith(("2", "3")) else ""
        print(f"  {name:<40} {a:>7.3f} {far:>12.2f} {fp:>7.0f}{gain}")
        if name.startswith(("1", "2")):
            prev = a
    g = np.array([r["gfs_f024_kt"] for r in have])
    o = np.array([r["wind_kt"] for r in have])
    print(f"\n  GFS f024 sustained wind near the low 24 h out: "
          f"median {np.median(g):.0f} kt; ERA5 sustained at the low now: "
          f"{np.median(o):.0f} kt")
    print("  Neither reaches 64 kt: both are smoothed model winds at 0.25 deg, "
          "and\n  the archive's hurricane force is an analyst's determination "
          "from\n  scatterometer data. They discriminate; they do not measure.")


if __name__ == "__main__":
    main()
