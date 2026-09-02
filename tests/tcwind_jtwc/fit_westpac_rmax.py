#!/usr/bin/env python3
"""Refit the Willoughby-form Rmax regression on WestPac best-track data.

TCWind_JTWC.py's willoughbyRmax() uses Willoughby et al. (2006)'s
Atlantic-fit coefficients:

    Rmax_km = 46.4 * exp(-0.0155 * Vmax_ms + 0.0169 * |lat|)

verify_besttrack_rmax.py showed this underestimates JTWC's own
post-season RMW by ~12-14 nm on average in WestPac, worst for weak
systems. This script keeps the same functional form (it's a reasonable
shape - decreasing with intensity, increasing with latitude) and refits
just its three coefficients (A, B, C) by ordinary least squares in log
space, against the same real JTWC best-track RMW data:

    ln(Rmax_km) = ln(A) + B * Vmax_ms + C * |lat|

Split by STORM (not by record) into train/test, 80/20, so records from
the same storm six hours apart don't leak across the split and inflate
the validation score. Reports the original vs. refit coefficients'
out-of-sample skill on the held-out storms, then refits on the full
dataset for the coefficients actually shipped.

Usage:
    python3 fit_westpac_rmax.py [path/to/ibtracs.csv]
"""
import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                 "GFE", "procedures"))
import TCWind_JTWC as tc
from verify_besttrack_rmax import load_rows, build_record, CACHE, stats, fmt

KT2MS = 0.514444
KM2NM = 1.0 / 1.852
SEED = 20260902


def fit_coeffs(records):
    """OLS fit of ln(Rmax_km) = ln(A) + B*Vms + C*|lat|."""
    X = np.array([[1.0, r["vmax"] * KT2MS, abs(r["lat"])] for r in records])
    y = np.array([math.log(r["rmw"] / KM2NM) for r in records])  # nm -> km
    coeffs, *_ = np.linalg.lstsq(X, y, rcond=None)
    lnA, B, C = coeffs
    return math.exp(lnA), B, C


def rmax_with(A, B, C, vmax_kt, lat_deg):
    v_ms = vmax_kt * KT2MS
    rmax_km = A * math.exp(B * v_ms + C * abs(lat_deg))
    return rmax_km * KM2NM


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE
    records = [rec for row in load_rows(path)
               if (rec := build_record(row)) is not None]
    print("%d usable JTWC best-track records\n" % len(records))

    sids = sorted({r["sid"] for r in records})
    rnd = random.Random(SEED)
    rnd.shuffle(sids)
    n_test = max(1, len(sids) // 5)
    test_sids = set(sids[:n_test])
    train = [r for r in records if r["sid"] not in test_sids]
    test = [r for r in records if r["sid"] in test_sids]
    print("%d storms total -> %d train storms (%d records), "
          "%d test storms (%d records)\n"
          % (len(sids), len(sids) - n_test, len(train), n_test, len(test)))

    A0, B0, C0 = 46.4, -0.0155, 0.0169  # original Willoughby (2006)
    A1, B1, C1 = fit_coeffs(train)

    print("Original Willoughby (2006):  A=%.2f  B=%.5f  C=%.5f" % (A0, B0, C0))
    print("WestPac refit (train only):  A=%.2f  B=%.5f  C=%.5f\n" % (A1, B1, C1))

    orig_test = [(rmax_with(A0, B0, C0, r["vmax"], r["lat"]), r["rmw"]) for r in test]
    refit_test = [(rmax_with(A1, B1, C1, r["vmax"], r["lat"]), r["rmw"]) for r in test]

    print("Out-of-sample skill on the %d held-out test storms:" % n_test)
    fmt("original Willoughby (2006)", stats(orig_test))
    fmt("WestPac refit", stats(refit_test))

    # Final coefficients: refit on every available record for deployment.
    A2, B2, C2 = fit_coeffs(records)
    print("\nFinal coefficients (refit on all %d records, for deployment):"
          % len(records))
    print("  A=%.3f  B=%.6f  C=%.6f" % (A2, B2, C2))

    full_orig = [(rmax_with(A0, B0, C0, r["vmax"], r["lat"]), r["rmw"]) for r in records]
    full_new = [(rmax_with(A2, B2, C2, r["vmax"], r["lat"]), r["rmw"]) for r in records]
    print("\nIn-sample skill, full dataset, original vs. final:")
    fmt("original Willoughby (2006)", stats(full_orig))
    fmt("final WestPac coefficients", stats(full_new))


if __name__ == "__main__":
    main()
