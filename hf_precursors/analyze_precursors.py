"""Screen the literature's ingredients against hurricane force within 24 h.

Two questions per ingredient, and the second matters more:

    alone -- how well does it separate lows that go on to hurricane force
    from lows that do not, as an AUC;

    added -- what does it contribute BEYOND what is already known from the
    low itself, its depth and the wind currently blowing near it. An
    ingredient that only restates the depth is not worth a field in D2D.

Exploration seasons only unless --confirm is passed. The ingredients come
from published findings rather than from a search of this data, so the
screen is confirmatory in spirit, but the thresholds and the combination are
not, and those are what a held-out season has to check.
"""
from __future__ import annotations

import csv
import glob
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

# name -> (column, sign) where sign +1 means larger values should mean more
# likely hurricane force. The signs are taken from the papers, not fitted.
INGREDIENTS = [
    ("depth (hPa)",                      "depth",             +1),
    ("gradient depth/scale",             "grad",              +1),
    ("gradient wind Vg",                 "vg_kt",             +1),
    ("gust now",                         "gust_kt",           +1),
    ("scale (km)",                       "scale_km",          -1),
    ("S&G: trough distance",             "trough_km",         -1),
    ("S&G: trough depth (anomaly)",      "trough_anom_m",     -1),
    ("S&G: SST gradient",                "sst_grad",          +1),
    ("S&G: SST itself",                  "sst_c",             +1),
    ("G&D: upstream anticyclone",        "up_high_rel",       +1),
    ("G&D: downstream cyclone",          "down_low_rel",      -1),
    ("G&D: thickness anomaly",           "thick_anom_m",      -1),
    ("G&D: thickness anomaly 1500 km E", "thick_anom_east_m", -1),
    ("Hart: HVTL",                       "hvtl",              +1),
    ("Hart: HVTU",                       "hvtu",              +1),
]

BASELINE = ["depth", "gust_kt"]


def load():
    rows = []
    for p in sorted(glob.glob(str(HERE / "data" / "precursors_*.csv"))):
        with open(p) as fh:
            rows += list(csv.DictReader(fh))
    for r in rows:
        for k, v in list(r.items()):
            if k in ("track", "when"):
                continue
            r[k] = float(v) if v not in ("", "nan") else np.nan
        d = datetime.strptime(r["when"], "%Y-%m-%d %H")
        r["season"] = d.year if d.month >= 7 else d.year - 1
    return rows


def fit_auc(train, test, cols):
    tr = [r for r in train if all(np.isfinite(r[c]) for c in cols)]
    te = [r for r in test if all(np.isfinite(r[c]) for c in cols)]
    if len(tr) < 50 or len(te) < 50:
        return np.nan, 0
    X = np.column_stack([[r[c] for r in tr] for c in cols])
    y = np.array([r["hf24"] for r in tr], float)
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        b, _ = logistic(y, X, cols)
    Xte = np.column_stack([np.ones(len(te))]
                          + [[r[c] for r in te] for c in cols])
    return auc([int(r["hf24"]) for r in te], list(Xte @ b)), len(te)


def run(rows, seasons, label):
    tr = [r for r in rows if r["season"] not in seasons]
    te = [r for r in rows if r["season"] in seasons]
    base_auc, n = fit_auc(tr, te, BASELINE)
    print(f"\n{'=' * 76}\n{label}: {len(te)} lows scored, "
          f"{sum(int(r['hf24']) for r in te)} with hurricane force within 24 h")
    print("=" * 76)
    print(f"  baseline (depth + gust now): AUC {base_auc:.3f}\n")
    print(f"  {'ingredient':<36} {'alone':>8} {'+baseline':>11} {'gain':>8}")
    print("  " + "-" * 68)
    scored = []
    for name, col, sign in INGREDIENTS:
        if col in BASELINE:
            continue          # already in the baseline; adding it again is a
                              # duplicate column and the fit is singular
        ok = [r for r in te if np.isfinite(r[col])]
        if len(ok) < 50:
            continue
        a = auc([int(r["hf24"]) for r in ok], [sign * r[col] for r in ok])
        # An AUC below 0.5 is skill with the opposite sign, not absence of
        # skill. Report the oriented value and flag where the direction the
        # paper implies is contradicted here -- that is a finding, not noise.
        flipped = a < 0.5
        a_or = max(a, 1.0 - a)
        comb, _ = fit_auc(tr, te, BASELINE + [col])
        scored.append((comb - base_auc, name, a_or, comb, flipped))
    scored.sort(reverse=True)
    for gain, name, a, comb, flipped in scored:
        mark = "  <- sign opposite to expected" if flipped else ""
        print(f"  {name:<36} {a:>8.3f} {comb:>11.3f} {gain:>+8.3f}{mark}")
    return tr, te, base_auc


def combo(tr, te, base_auc):
    print("\n  Combinations, over the same baseline:")
    for name, cols in [
        ("baseline + the two G&D sector terms",
         ["up_high_rel", "down_low_rel"]),
        ("baseline + S&G trough distance + SST gradient",
         ["trough_km", "sst_grad"]),
        ("baseline + both Hart terms", ["hvtl", "hvtu"]),
        ("baseline + best of each paper",
         ["up_high_rel", "trough_km", "thick_anom_m"]),
        ("everything", [c for _, c, _ in INGREDIENTS if c not in BASELINE]),
    ]:
        a, n = fit_auc(tr, te, BASELINE + cols)
        if np.isfinite(a):
            print(f"    {name:<48} AUC {a:.3f}  ({a - base_auc:+.3f})")


if __name__ == "__main__":
    rows = load()
    print(f"{len(rows)} lows with precursors computed")
    tr, te, b = run(rows, EXPLORE, "EXPLORATION seasons 2020, 2022, 2024")
    combo(tr, te, b)
    if "--confirm" in sys.argv:
        tr, te, b = run(rows, CONFIRM, "CONFIRMATION seasons 2021, 2023, 2025")
        combo(tr, te, b)
