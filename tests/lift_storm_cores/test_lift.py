#!/usr/bin/env python3
"""Checks for GFE/smarttools/Lift_StormCores.py against a fake GFE.

    python3 test_lift.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(REPO, "tests", "blend_wind_gust_wave_pmsl"))
sys.path.insert(0, os.path.join(REPO, "GFE", "smarttools"))

import gfe_fakes  # noqa: E402

SS = gfe_fakes.install()
import Lift_StormCores as L  # noqa: E402

KT = 1.943844
SHAPE = SS.shape
FAILURES = []
GFS, EC, GEFS = "X_GRID__GFS_19700102_1200", "X_D2D_ECMWF_19700102_1200", "X_D2D_GEFS_19700102_1200"
TR = gfe_fakes.TimeRange(gfe_fakes.AbsTime(0), gfe_fakes.AbsTime(3600))
G = [(TR, None)]


def check(label, condition, detail=""):
    print("  %s %s%s" % ("ok  " if condition else "FAIL", label, "" if condition else " " + str(detail)))
    if not condition:
        FAILURES.append(label)


class Info:
    def getUnitString(self):
        return "kts"


def grid(vals):
    """Field of 10 everywhere with vals {(row, col): value} set."""
    g = np.full(SHAPE, 10.0)
    for k, v in vals.items():
        g[k] = v
    return g


def entry(units, g):
    return {"units": units, "grids": [(TR, g)]}


def vec(mag):
    return (mag, np.full(SHAPE, 270.0))


def run(store, dbs, var=None, area=None, wind=None):
    SS.store, SS.dbs = store, dbs
    v = {"Lift (kt)": 6.0, "Lift starts where the stronger of GFS/ECMWF reaches (kt)": 44.0,
         "Full lift at (kt)": 44.0, "Extra lift for HF (kt, 0 = off)": 0.0,
         "GEFS storm floor": "Off", "HF ceiling check": "Off"}  # plain step at 44, one step
    v.update(var or {})
    tool = L.Tool(None)
    w = wind if wind is not None else vec(np.full(SHAPE, 40.0))
    return tool, tool.execute(w, Info(), TR, v, area)


def models(gfs_kt=None, ec_ms=None):
    s, d = {}, {}
    if gfs_kt is not None:
        s[(GFS, "wind", "FHAG10")] = entry("kts", vec(gfs_kt))
        d["GFS"] = [GFS]
    if ec_ms is not None:
        s[(EC, "wind", "FHAG10")] = entry("m/s", vec(ec_ms))
        d["D2D_ECMWF"] = [EC]
    return s, d


print("1. lift only where the stronger model >= threshold; m/s converted")
s, d = models(gfs_kt=grid({(1, 1): 50}), ec_ms=grid({(2, 2): 25, (3, 3): 22}))  # 25 m/s=48.6 kt, 22 m/s=42.8 kt
tool, (mag, dr) = run(s, d)
check("GFS 50 kt cell lifted", abs(mag[1, 1] - 46) < 1e-6, mag[1, 1])
check("ECMWF 25 m/s (48.6 kt) cell lifted", abs(mag[2, 2] - 46) < 1e-6, mag[2, 2])
check("ECMWF 22 m/s (42.8 kt) cell not lifted", mag[3, 3] == 40, mag[3, 3])
check("weak cell unchanged", mag[10, 10] == 40)
check("direction unchanged", np.all(dr == 270.0))
check("message names both runs and 2 cells", tool.msgs[-1][0] == "R" and GFS in tool.msgs[-1][1]
      and EC in tool.msgs[-1][1] and "2 cells lifted" in tool.msgs[-1][1], tool.msgs[-1])

print("2. missing models")
s, d = models(gfs_kt=grid({(1, 1): 50}))
tool, (mag, _) = run(s, d)
check("ECMWF missing: GFS used", mag[1, 1] == 46)
check("message names ECMWF", "ECMWF missing" in tool.msgs[-1][1], tool.msgs[-1])
s, d = models()
w = vec(np.full(SHAPE, 40.0))
tool, out = run(s, d, wind=w)
check("both missing: grid unchanged", out is w and np.all(out[0] == 40))
check("both missing: urgent message", tool.msgs[-1][0] == "U", tool.msgs[-1])

print("3. edit area")
s, d = models(gfs_kt=grid({(1, 1): 50, (8, 8): 50}))
area = np.zeros(SHAPE, bool)
area[:5, :5] = True
tool, (mag, _) = run(s, d, area=area)
check("inside area lifted", mag[1, 1] == 46)
check("outside area unchanged", mag[8, 8] == 40)

print("4. GEFS floor")
p48 = L.GEFS_P48_SOURCES[0]
for label, scale in (("fraction 0-1", 0.01), ("percent 0-100", 1.0)):
    s, d = models(gfs_kt=grid({}))
    prob = np.zeros(SHAPE)
    prob[4, 4], prob[5, 5] = 60 * scale, 40 * scale
    s[(GEFS, p48[0], p48[1])] = entry("%", prob)
    d["D2D_GEFS"] = [GEFS]
    tool, (mag, _) = run(s, d, var={"GEFS storm floor": "On"})
    check("%s: P>=50 raised to 48" % label, mag[4, 4] == 48, mag[4, 4])
    check("%s: P<50 unchanged" % label, mag[5, 5] == 40, mag[5, 5])
    check("%s: floored count reported" % label, "1 floored" in tool.msgs[-1][1], tool.msgs[-1])

print("5. HF ceiling check")
s, d = models(gfs_kt=grid({(1, 1): 70, (2, 2): 70}))
wind = vec(np.full(SHAPE, 66.0))
tool, (mag, _) = run(s, d, var={"HF ceiling check": "On"}, wind=wind)
check("missing inputs: skipped and said so", "HF check skipped" in tool.msgs[-1][1], tool.msgs[-1])
w925 = np.full(SHAPE, 70.0)
w925[2, 2] = 90.0  # 90 x 0.70 = 63 >= 60: not flagged; 70 x 0.70 = 49: flagged
s[(GFS, "wind", "MB925")] = entry("kts", vec(w925))
s[(GFS, "t", "SFC")] = entry("K", np.full(SHAPE, 281.0))
s[(GFS, "t", "FHAG2")] = entry("K", np.full(SHAPE, 280.0))  # diff 1 C -> factor 0.70
tool, (mag, _) = run(s, d, var={"HF ceiling check": "On"}, wind=wind)
n = SHAPE[0] * SHAPE[1]
check("flagged count in message", "%d of %d hurricane-force cells" % (n - 1, n) in tool.msgs[-1][1], tool.msgs[-1])
check("wind not changed by the check (only the lift)", mag[10, 10] == 66.0 and mag[1, 1] == 72.0, (mag[10, 10], mag[1, 1]))
tool, (mag, _) = run(s, d, var={"HF ceiling check": "On", "Lift (kt)": 0.0}, wind=wind)
check("with no lift the grid is identical", np.all(mag == 66.0))

print("6. ramps and second (HF) step")
s, d = models(gfs_kt=grid({(1, 1): 45, (2, 2): 50, (3, 3): 40, (4, 4): 37, (5, 5): 55}))
ramped = {"Lift starts where the stronger of GFS/ECMWF reaches (kt)": 38.0, "Full lift at (kt)": 42.0,
          "Extra lift for HF (kt, 0 = off)": 4.0, "Extra lift starts at (kt)": 48.0, "Full extra lift at (kt)": 52.0}
tool, (mag, _) = run(s, d, var=ramped)
check("37 kt: below the ramp", mag[4, 4] == 40, mag[4, 4])
check("40 kt: half way up the first ramp (+3)", abs(mag[3, 3] - 43) < 1e-6, mag[3, 3])
check("45 kt: full first lift only", abs(mag[1, 1] - 46) < 1e-6, mag[1, 1])
check("50 kt: +6 and half the extra (+2)", abs(mag[2, 2] - 48) < 1e-6, mag[2, 2])
check("55 kt: +6 +4", abs(mag[5, 5] - 50) < 1e-6, mag[5, 5])
x = np.linspace(30, 60, 301)
step = np.diff(L.ramp(x, 6, 38, 42) + L.ramp(x, 4, 48, 52))
check("ramp has no jump bigger than 0.2 kt per 0.1 kt", step.max() <= 0.15 + 1e-9, step.max())
check("full <= start is a plain step", L.ramp(np.array([41.9, 42.0]), 6, 42, 42).tolist() == [0.0, 6.0])
tool, (mag, _) = run(s, d, var=dict(ramped, **{"Extra lift for HF (kt, 0 = off)": 0.0}))
check("extra lift 0: first ramp only", abs(mag[5, 5] - 46) < 1e-6, mag[5, 5])
nums = [v[1] for v in L.VariableList if v[2] == "numeric"][:6]
check("dialog defaults are the picked ramps 6 (38-42) + 4 (48-52)", nums == [6.0, 38.0, 42.0, 4.0, 48.0, 52.0], nums)
check("default trigger is GFS/ECMWF", L.VariableList[0][1] == L.TRIGGER_MODELS, L.VariableList[0])

print("7. own-wind trigger (no models needed)")
w = np.full(SHAPE, 30.0)
w[1, 1], w[2, 2], w[3, 3], w[4, 4] = 38.0, 41.0, 46.0, 50.0
tool, (mag, _) = run({}, {}, var={"Lift where": L.TRIGGER_OWN, "Extra lift for HF (kt, 0 = off)": 4.0}, wind=vec(w))
check("30 kt untouched", mag[10, 10] == 30, mag[10, 10])
check("38 kt: half the first ramp (+3)", abs(mag[1, 1] - 41) < 1e-6, mag[1, 1])
check("41 kt: full first lift (+6)", abs(mag[2, 2] - 47) < 1e-6, mag[2, 2])
check("46 kt: +6 and half the extra (+2)", abs(mag[3, 3] - 54) < 1e-6, mag[3, 3])
check("50 kt: +10", abs(mag[4, 4] - 60) < 1e-6, mag[4, 4])
check("message says the grid itself", "Fcst Wind itself" in tool.msgs[-1][1], tool.msgs[-1])

print()
print("FAILED: %s" % FAILURES if FAILURES else "all ok")
sys.exit(1 if FAILURES else 0)
