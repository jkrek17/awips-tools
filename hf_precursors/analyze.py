"""Does depth, scale, or their ratio separate hurricane-force lows?

THE TEST. The compactness hypothesis makes a geometric prediction, which is
much stronger than a correlation. Plot every low in (depth, scale) space:

    if the wind follows depth/scale, the boundary between cases and
    controls is a RAY THROUGH THE ORIGIN -- compact, modest-depth lows fall
    on the hurricane-force side;

    if it follows depth alone, the boundary is HORIZONTAL and scale is
    noise.

Those cannot both be true, and the difference is visible rather than
inferred.

THE MODEL. Matched case-control data needs conditional logistic
regression, not ordinary logistic: within a stratum of one case and its
controls, the likelihood is the probability that the case is the one that
happened, exp(bx_case) / sum_j exp(bx_j). That conditions away everything
the matching held fixed -- season, month, depth, latitude -- and estimates
only what varies inside the stratum. Fitting ordinary logistic here would
credit the matched variables with skill that the design removed.

Reported as odds ratios per unit, because that is what a forecaster can
reason about: "each 100 km of extra compactness multiplies the odds by X".

THE HOLDOUT, declared before any of this was run. Seasons are split
interleaved -- explore 2020, 2022, 2024; confirm 2021, 2023, 2025 -- rather
than in blocks, so the ASCAT-C step and any trend fall on both sides. This
module refuses to touch the confirmation seasons unless asked with
`--confirm`, and that is meant to be asked once, after the exploration
result and the thresholds are written down.
"""
from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
EXPLORE_SEASONS = (2020, 2022, 2024)
CONFIRM_SEASONS = (2021, 2023, 2025)


def load(path=None):
    if path is None:
        tend = HERE / "data" / "matched_tend.csv"
        path = tend if tend.exists() else HERE / "data" / "matched.csv"
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("lat", "lon", "p_centre", "p_env", "depth", "fit_depth",
                  "scale_km", "fit_rms", "grad_hpa_per_100km", "vg_kt",
                  "vgeo_kt", "max_step_km", "tend12", "tend24"):
            if k in r and not isinstance(r[k], float):
                r[k] = float(r[k]) if r[k] != "" else float("nan")
        r["label"] = int(r["label"])
        r["season"] = int(r["season"])
    return rows


def strata(rows, seasons):
    """Usable strata: one case with at least one control, in `seasons`."""
    by = defaultdict(list)
    for r in rows:
        if r["season"] in seasons:
            by[r["stratum"]].append(r)
    out = []
    for members in by.values():
        cases = [m for m in members if m["label"] == 1]
        ctrls = [m for m in members if m["label"] == 0]
        if len(cases) == 1 and ctrls:
            out.append((cases[0], ctrls))
    return out


def clogit(sets, features):
    """Conditional logistic fit. Returns (beta, se, loglik).

    Standard errors come from the numerical Hessian of the negative
    log-likelihood at the optimum -- the usual observed-information
    estimate.
    """
    X = [np.array([[m[f] for f in features] for m in [case] + ctrls])
         for case, ctrls in sets]

    def nll(b):
        total = 0.0
        for x in X:
            eta = x @ b
            total -= eta[0] - np.logaddexp.reduce(eta)
        return total

    b0 = np.zeros(len(features))
    res = minimize(nll, b0, method="BFGS")

    # BFGS's own hess_inv is an approximation accumulated during the search,
    # not the observed information, and with correlated predictors it can be
    # off by an order of magnitude -- it reported a standard error three
    # times too small for depth as soon as scale was added beside it. The
    # Hessian is differenced explicitly instead.
    se = _observed_se(nll, res.x)
    return res.x, se, -res.fun


def _observed_se(nll, b, eps=1e-4):
    """Standard errors from a central-difference Hessian of the negative
    log-likelihood at `b`."""
    k = len(b)
    H = np.empty((k, k))
    for i in range(k):
        for j in range(k):
            bpp, bpm, bmp, bmm = (b.copy() for _ in range(4))
            bpp[i] += eps; bpp[j] += eps
            bpm[i] += eps; bpm[j] -= eps
            bmp[i] -= eps; bmp[j] += eps
            bmm[i] -= eps; bmm[j] -= eps
            H[i, j] = (nll(bpp) - nll(bpm) - nll(bmp) + nll(bmm)) / (4 * eps * eps)
    try:
        cov = np.linalg.inv(H)
        return np.sqrt(np.clip(np.diag(cov), 0.0, None))
    except np.linalg.LinAlgError:
        return np.full(k, np.nan)


def report_fit(name, sets, features, base_ll=None):
    b, se, ll = clogit(sets, features)
    n = len(sets)
    print(f"  {name}")
    for f, bi, si in zip(features, b, se):
        z = bi / si if si > 0 else float("nan")
        print(f"      {f:<26} OR {math.exp(bi):6.3f}  per unit   "
              f"beta {bi:+.4f} +/- {si:.4f}   z {z:+.2f}")
    null = -len(sets) * math.log(1 + len(sets[0][1])) if sets else float("nan")
    print(f"      log-likelihood {ll:.2f}   (n strata = {n})", end="")
    if base_ll is not None:
        lr = 2.0 * (ll - base_ll)
        print(f"   LR vs previous = {lr:+.2f} on {len(features)} df")
    else:
        print()
    return ll


def descriptive(sets, label):
    print(f"\n  {label}")
    print(f"  {'variable':<24} {'cases':>10} {'controls':>10} {'difference':>12}")
    print("  " + "-" * 58)
    cases = [c for c, _ in sets]
    ctrls = [m for _, cs in sets for m in cs]
    for var, unit in (("depth", "hPa"), ("scale_km", "km"),
                      ("grad_hpa_per_100km", "hPa/100km"), ("vg_kt", "kt"),
                      ("p_centre", "hPa"), ("tend12", "hPa/12h"),
                      ("tend24", "hPa/24h")):
        if var not in cases[0]:
            continue
        a = np.nanmedian([c[var] for c in cases])
        b = np.nanmedian([c[var] for c in ctrls])
        print(f"  {var:<24} {a:>10.1f} {b:>10.1f} {a - b:>+12.1f}  {unit}")


def geometry_test(sets):
    """Ray or horizontal? Compare a depth-only fit with a gradient fit on
    the same strata; if compactness matters, the gradient term carries
    signal that depth alone does not."""
    print("\n  GEOMETRY: is the boundary a ray through the origin, or flat?")
    ll_depth = report_fit("depth only", sets, ["depth"])
    report_fit("depth + scale", sets, ["depth", "scale_km"], ll_depth)
    report_fit("gradient only (depth/scale)", sets, ["grad_hpa_per_100km"])
    report_fit("gradient wind only", sets, ["vg_kt"])


def tendency_ladder(sets):
    """Does which way the low is going beat how deep it has got?

    Depth says where a low has reached; the tendency says where it is
    headed. A control drawn at a random time can match a case's depth while
    being past its own peak, so the ladder puts tendency in on its own
    before combining it with the structure terms.
    """
    usable = [(c, [m for m in cs if np.isfinite(m["tend12"])])
              for c, cs in sets if np.isfinite(c["tend12"])]
    usable = [(c, cs) for c, cs in usable if cs]
    if not usable:
        print("\n  TENDENCY: no strata carry a 12 h tendency")
        return
    print(f"\n  TENDENCY LADDER  ({len(usable)} strata carry one)")
    ll0 = report_fit("depth only", usable, ["depth"])
    ll1 = report_fit("tendency only (12 h)", usable, ["tend12"])
    report_fit("tendency only (24 h)", usable, ["tend24"])
    report_fit("depth + tendency", usable, ["depth", "tend12"], ll1)
    report_fit("scale + tendency", usable, ["scale_km", "tend12"], ll1)
    report_fit("gradient + tendency", usable, ["grad_hpa_per_100km", "tend12"], ll1)
    report_fit("depth + scale + tendency", usable,
               ["depth", "scale_km", "tend12"], ll1)


def run(rows, seasons, label):
    sets = strata(rows, seasons)
    if not sets:
        print(f"  no usable strata in {label}")
        return
    ncase = len(sets)
    nctrl = sum(len(c) for _, c in sets)
    print(f"\n{'=' * 70}\n{label}: {ncase} strata, {ncase} cases, {nctrl} controls\n{'=' * 70}")
    descriptive(sets, "Medians")
    geometry_test(sets)
    tendency_ladder(sets)


def structure_ladder(sets):
    """On strata matched by TENDENCY: does structure add anything?

    Here the maturity confound is held fixed by the matching, so depth,
    scale and gradient vary inside a stratum for reasons other than how far
    along the low is. A positive coefficient on depth or on gradient now
    means what it says.
    """
    print("\n  STRUCTURE LADDER  (strata matched on 12 h tendency)")
    ll0 = report_fit("depth only", sets, ["depth"])
    report_fit("scale only", sets, ["scale_km"])
    report_fit("gradient only (depth/scale)", sets, ["grad_hpa_per_100km"])
    report_fit("gradient wind only", sets, ["vg_kt"])
    report_fit("depth + scale", sets, ["depth", "scale_km"], ll0)
    resid = [c["tend12"] - np.mean([m["tend12"] for m in [c] + cs])
             for c, cs in sets]
    print(f"      (residual tendency spread inside strata: "
          f"{np.std(resid):.2f} hPa/12 h -- the matching tolerance is 3.0)")


def run_by_tendency(path, seasons, label):
    rows = load(path)
    sets = strata(rows, seasons)
    if not sets:
        print(f"  no usable strata in {label}")
        return
    nctrl = sum(len(c) for _, c in sets)
    print(f"\n{'=' * 70}\n{label}: {len(sets)} strata, {len(sets)} cases, "
          f"{nctrl} controls\n{'=' * 70}")
    descriptive(sets, "Medians")
    structure_ladder(sets)


if __name__ == "__main__":
    if "--by-tendency" in sys.argv:
        path = HERE / "data" / "matched_by_tend.csv"
        run_by_tendency(path, EXPLORE_SEASONS,
                        "TENDENCY-MATCHED, exploration seasons 2020, 2022, 2024")
        if "--confirm" in sys.argv:
            run_by_tendency(path, CONFIRM_SEASONS,
                            "TENDENCY-MATCHED, confirmation seasons 2021, 2023, 2025")
        else:
            print("\n(confirmation seasons withheld)")
    else:
        rows = load()
        run(rows, EXPLORE_SEASONS, "EXPLORATION seasons 2020, 2022, 2024")
        if "--confirm" in sys.argv:
            run(rows, CONFIRM_SEASONS, "CONFIRMATION seasons 2021, 2023, 2025")
        else:
            print("\n(confirmation seasons withheld; rerun with --confirm once the "
                  "exploration result is written down)")
