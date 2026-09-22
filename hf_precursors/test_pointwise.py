"""Compare the fitted-depth screen against its pointwise D2D equivalent.

Three models, each fitted on the exploration seasons and scored on the
confirmation seasons:

    baseline        what a forecaster already reads off the surface
    + phase space   the two Hart terms added
    and both of those run twice -- once with the DEPTH THE SCREEN USED (a
    Gaussian fit around a detected centre) and once with the DEPTH A PANEL
    COULD SHOW (max pressure within 500 km minus the value here).

If the second pair reproduces the first, the panel is worth building. If the
gain collapses, the finding does not survive contact with what D2D can
actually compute, and it belongs in a note rather than on a screen.
"""
from __future__ import annotations

import contextlib
import csv
import io
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from analyze_tracks import logistic  # noqa: E402
from leadtime import auc  # noqa: E402

EXPLORE = (2020, 2022, 2024)
CONFIRM = (2021, 2023, 2025)


def load():
    with open(HERE / "data" / "precursors_pointwise.csv") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k, v in list(r.items()):
            if k in ("track", "when"):
                continue
            r[k] = float(v) if v not in ("", "nan") else np.nan
        d = datetime.strptime(r["when"], "%Y-%m-%d %H")
        r["season"] = d.year if d.month >= 7 else d.year - 1
    return rows


def score(rows, cols):
    tr = [r for r in rows if r["season"] in EXPLORE
          and all(np.isfinite(r[c]) for c in cols)]
    te = [r for r in rows if r["season"] in CONFIRM
          and all(np.isfinite(r[c]) for c in cols)]
    X = np.column_stack([[r[c] for r in tr] for c in cols])
    y = np.array([r["hf24"] for r in tr], float)
    with contextlib.redirect_stdout(io.StringIO()):
        b, _ = logistic(y, X, cols)
    Xte = np.column_stack([np.ones(len(te))] + [[r[c] for r in te] for c in cols])
    p = 1.0 / (1.0 + np.exp(-(Xte @ b)))
    lab = np.array([int(r["hf24"]) for r in te])
    return auc(list(lab), list(p)), lab, p


def far_at_pod(lab, p, target=0.80):
    for thr in np.linspace(0.99, 0.01, 400):
        f = p >= thr
        tp = int((f & (lab == 1)).sum())
        fp = int((f & (lab == 0)).sum())
        fn = int((~f & (lab == 1)).sum())
        if tp + fn and tp / (tp + fn) >= target:
            return fp / (tp + fp), fp
    return np.nan, np.nan


def main():
    rows = load()
    print(f"{len(rows)} lows, {sum(int(r['hf24']) for r in rows)} reaching "
          "hurricane force within 24 h\n")
    print(f"  {'depth used':<34} {'baseline':>9} {'+ Hart':>9} {'gain':>8} "
          f"{'FAR@POD.80':>12}")
    print("  " + "-" * 76)
    for label, dcol in (("fitted profile (what the screen used)", "depth"),
                        ("pointwise 500 km window (what D2D can show)",
                         "depth_pw")):
        base = [dcol, "gust_kt"]
        a0, l0, p0 = score(rows, base)
        a1, l1, p1 = score(rows, base + ["hvtl", "hvtu"])
        far0, n0 = far_at_pod(l0, p0)
        far1, n1 = far_at_pod(l1, p1)
        print(f"  {label:<34} {a0:>9.3f} {a1:>9.3f} {a1 - a0:>+8.3f} "
              f"{far0:>5.2f} -> {far1:<5.2f}")
    print()
    d = np.array([r["depth"] for r in rows])
    dp = np.array([r["depth_pw"] for r in rows])
    ok = np.isfinite(d) & np.isfinite(dp)
    print(f"  the two depths correlate at r = {np.corrcoef(d[ok], dp[ok])[0, 1]:.3f}"
          f"; pointwise runs {np.median(dp[ok] - d[ok]):+.1f} hPa "
          "against the fitted one")


if __name__ == "__main__":
    main()
