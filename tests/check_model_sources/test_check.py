#!/usr/bin/env python3
"""Check_ModelSources against the fake GFE from the blend tests.

    python3 test_check.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blend_wind_gust_wave_pmsl"))
import gfe_fakes  # noqa: E402

SS = gfe_fakes.install()
import Check_ModelSources as C  # noqa: E402

H = 3600
NOW = 1_800_000_000 // (12 * H) * (12 * H)  # a 00Z or 12Z
FAILURES = []


def check(label, condition, detail=""):
    print("  %s %s %s" % ("ok  " if condition else "FAIL", label, "" if condition else detail))
    if not condition:
        FAILURES.append(label)


def mid(db, cycle):
    return "X_D2D_%s_%s" % (db.replace("_", "-"), C.time.strftime("%Y%m%d_%H00", C.time.gmtime(cycle)))


SS.store, SS.dbs = {}, {}
for db, step_h, n in (("D2D_GFS", 6, 5), ("D2D_ECMWF", 12, 2), ("D2D_AIFS", 12, 3)):
    ids = [mid(db, NOW - i * step_h * H) for i in range(n)]
    SS.dbs[db] = ids
    for i, m in enumerate(ids):
        c = NOW - i * step_h * H
        SS.store[(m, "wind", "FHAG10")] = {"units": "m/s", "grids": [
            (gfe_fakes.time_range(c + h * H), (np.zeros(SS.shape), np.zeros(SS.shape))) for h in range(0, 241, 6)]}

C.time.time = lambda: NOW + 3 * H
proc = C.Procedure(None)
proc.execute(None, None, {"no_window": True})
text = "\n".join(proc.report())

check("GFS listed with 5 runs", "D2D_GFS\n  5 runs kept" in text, text)
check("ECMWF listed with 2 runs", "D2D_ECMWF\n  2 runs kept" in text)
check("wind found with its reach", "wind FHAG10, 41 grids to +240 h" in text)
check("GFS has now, -12 h, -24 h", "GFS    newest" in text and "has now, -12 h, -24 h" in text.split("GFS    ")[1].split("\n")[0])
check("ECMWF misses -24 h", "(missing -24 h)" in text.split("ECMWF  ")[1].split("\n")[0], text.split("ECMWF  ")[1])
check("AIFS found under the D2D_AIFS guess", "AIFS   newest" in text)
check("names not on the server listed", "Not found:" in text and "UKMEThires4" in text)
check("nothing written", not proc.created)

print()
if FAILURES:
    print("%d check(s) failed" % len(FAILURES))
    sys.exit(1)
print("all checks passed")
