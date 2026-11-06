#!/usr/bin/env python3
"""Checks for GFE/procedures/Make_BestWind.py against a fake GFE.

    python3 test_make_best_wind.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(REPO, "tests", "blend_wind_gust_wave_pmsl"))

import gfe_fakes  # noqa: E402

SS = gfe_fakes.install()
import types  # noqa: E402
sys.modules["grid_fetch"] = types.ModuleType("grid_fetch")   # an old server copy without grid_times: must not matter
import Make_BestWind as M  # noqa: E402

KT = 1.943844
SHAPE = SS.shape
H = 3600
T0 = 100 * 86400            # a 00Z valid time
FAILURES = []
TR = gfe_fakes.time_range(T0, 3 * H)   # the Fcst Wind grid


def check(label, condition, detail=""):
    print("  %s %s%s" % ("ok  " if condition else "FAIL", label, "" if condition else " " + str(detail)))
    if not condition:
        FAILURES.append(label)


def rid(kind, model, cycle):
    """Model id with the cycle (unix seconds) in the name, as AWIPS names them."""
    import time
    return "X_%s_%s_%s" % (kind, model, time.strftime("%Y%m%d_%H%M", time.gmtime(cycle)))


def vec(speed, direction=270.0):
    return (np.asarray(speed, float), np.full(SHAPE, float(direction)))


def const(v):
    return np.full(SHAPE, float(v))


def setup(gfs=None, ec=None, fcst_units="kts", fcst=True, ec_units="m/s"):
    """gfs / ec: {hours older than the newest 12Z-ish cycle: speed array}; GFS in kt, ECMWF in ec_units.

    Newest cycle is T0 - 12 h; "lag 12" is 12 h before that.  Keys are the lag in hours.
    """
    store, dbs = {}, {}
    newest = T0 - 12 * H
    for alias, runs, kind, name, units, unit_key in (("GFS", gfs, "GRID_", "GFS", "kts", "GFS"),
                                                     ("ECMWF", ec, "D2D", "ECMWF", ec_units, "D2D_ECMWF")):
        ids = []
        for lag in sorted(runs or {}):
            cycle = newest - lag * H
            mid = rid(kind, name, cycle)
            ids.append(mid)
            store[(mid, "wind", "FHAG10")] = {"units": units, "grids": [(gfe_fakes.time_range(T0), runs[lag] if isinstance(runs[lag], tuple) else vec(runs[lag]))]}
        if ids:
            dbs[unit_key] = ids
    if fcst:
        store[("Fcst", "Wind", "SFC")] = {"units": fcst_units, "grids": [(TR, vec(const(0)))]}
    return store, dbs


def run(store, dbs, var=None, area=None):
    SS.store, SS.dbs = store, dbs
    proc = M.Procedure(None)
    v = {"Core lift": "Off"}
    v.update(var or {})
    proc.execute(area, TR, v)
    return proc


def written(proc):
    assert proc.created, "nothing written"
    c = proc.created[-1]
    assert (c[0], c[1], c[2]) == ("Fcst", "Wind", "VECTOR")
    return c[3]


def det_blend_direct(runs, cur):
    """The rk.features.det_blend formula written out plainly."""
    runs = np.array(runs, float)
    w = [np.mean(np.exp(-0.5 * ((runs - s) / 5.0) ** 2), axis=0) + 1e-6 for s in cur]
    base = sum(wi * s for wi, s in zip(w, cur)) / sum(w)
    if len(runs) < 2:
        return base
    return base + np.minimum(0.3 * np.std(runs, axis=0), 5.0)


print("1. blend vs the det_blend formula, 6 runs")
rng = np.random.RandomState(0)
g = {lag: 20 + 25 * rng.rand(*SHAPE) for lag in (0, 12, 24)}
e = {lag: 20 + 25 * rng.rand(*SHAPE) for lag in (0, 12, 24)}
s, d = setup(g, {k: v / KT for k, v in e.items()})
p = run(s, d)
mag, direction = written(p)
want = det_blend_direct([g[0], g[12], g[24], e[0], e[12], e[24]], [g[0], e[0]])
check("speed equals the direct numpy computation", np.allclose(mag, want, atol=1e-3), np.abs(mag - want).max())
check("message names 6 runs", all(x in p.msgs[-1][1] for x in ("GFS", "ECMWF", "-12h", "-24h")), p.msgs[-1])
check("no missing runs reported", "missing" not in p.msgs[-1][1], p.msgs[-1])
check("grid written once, status R", len(p.created) == 1 and p.msgs[-1][0] == "R")

print("2. a lagged run missing")
s, d = setup({0: const(30), 12: const(32)}, {0: const(36) / KT, 12: const(34) / KT, 24: const(35) / KT})
p = run(s, d)
mag, _ = written(p)
want = det_blend_direct([const(30), const(32), const(36), const(34), const(35)], [const(30), const(36)])
check("blend uses the 5 runs left", np.allclose(mag, want, atol=1e-3), (mag[0, 0], want[0, 0]))
check("GFS -24h named as missing", "GFS -24h" in p.msgs[-1][1] and "missing" in p.msgs[-1][1], p.msgs[-1])

print("3. one model missing")
s, d = setup({0: const(30), 12: const(34), 24: const(32)}, None)
p = run(s, d)
mag, _ = written(p)
want = det_blend_direct([const(30), const(34), const(32)], [const(30)])
check("GFS alone, its own lagged runs", np.allclose(mag, want, atol=1e-3), (mag[0, 0], want[0, 0]))
check("message says ECMWF missing, GFS alone", "ECMWF current" in p.msgs[-1][1] and "alone" in p.msgs[-1][1], p.msgs[-1])
s, d = setup({0: const(30)}, None)
p = run(s, d)
mag, _ = written(p)
check("single run: no spread term", np.allclose(mag, 30.0, atol=1e-4), mag[0, 0])

print("4. both missing: unchanged")
s, d = setup(None, None)
p = run(s, d)
check("nothing written", not p.created)
check("urgent message says left unchanged", p.msgs[-1][0] == "U" and "unchanged" in p.msgs[-1][1], p.msgs[-1])

print("5. m/s conversion and Fcst units")
s, d = setup({0: const(40)}, {0: const(40 / KT)})
p = run(s, d)
mag, _ = written(p)
check("GFS 40 kt + ECMWF 20.58 m/s = 40 kt (kt Fcst)", np.allclose(mag, 40.0, atol=1e-3), mag[0, 0])
s, d = setup({0: const(40)}, {0: const(40 / KT)}, fcst_units="m/s")
p = run(s, d)
mag, _ = written(p)
check("Fcst in m/s: handed back in m/s", np.allclose(mag, 40 / KT, atol=1e-3), mag[0, 0])
s, d = setup({0: const(40)}, {0: const(40 / KT)}, ec_units="")
p = run(s, d)
mag, _ = written(p)
check("unknown D2D unit, max < 60: assumed m/s and said so", "assumed m/s" in p.msgs[-1][1], p.msgs[-1])

print("6. direction from the mean u/v of the current runs")
s, d = setup({0: vec(const(20), 270.0)}, {0: vec(const(20 / KT), 180.0)})
SS.store, SS.dbs = s, d
# direction grids: GFS from the west, ECMWF from the south -> mean from the south-west (225)
s[[k for k in s if k[0].find("GFS") > 0][0]]["grids"] = [(gfe_fakes.time_range(T0), vec(const(20), 270.0))]
s[[k for k in s if k[0].find("ECMWF") > 0][0]]["grids"] = [(gfe_fakes.time_range(T0), vec(const(20 / KT), 180.0))]
p = run(s, d)
_, direction = written(p)
check("from 225 deg", np.allclose(direction, 225.0, atol=1e-3), direction[0, 0])
s, d = setup({0: vec(const(30), 350.0), 12: vec(const(60), 90.0)}, {0: vec(const(30 / KT), 10.0)})
p = run(s, d)
_, direction = written(p)
check("lagged runs do not enter the direction (350 and 10 -> 0)",
      np.allclose(np.minimum(direction, 360 - direction), 0.0, atol=1e-3), direction[0, 0])

print("7. ramps, stronger-model trigger and the blend's own wind")
cells = [37, 40, 45, 50, 55]
spd = const(10)
for i, v in enumerate(cells):
    spd[i, 0] = v
s, d = setup({0: spd}, {0: spd / KT})
base = written(run(s, d))[0]
mag, _ = written(run(s, d, {"Core lift": "On"}))
add = mag - base
expect = [0, 3, 6, 8, 10]
check("model trigger: +0 +3 +6 +8 +10 at 37/40/45/50/55",
      np.allclose(add[:5, 0], expect, atol=1e-3), add[:5, 0])
check("weak cells not lifted", np.allclose(add[10:, :], 0, atol=1e-6))
# stronger of the two: only ECMWF strong
ecs = const(10)
ecs[0, 0] = 45
s, d = setup({0: const(10)}, {0: ecs / KT})
base = written(run(s, d))[0]
mag, _ = written(run(s, d, {"Core lift": "On"}))
check("lift follows the stronger model (ECMWF alone at 45)", abs((mag - base)[0, 0] - 6.0) < 1e-3, (mag - base)[0, 0])
# own trigger on the blended speed: all runs the same, so blend = the speed
spd = const(10)
vals = [35, 38, 40, 46, 48, 52]
for i, v in enumerate(vals):
    spd[i, 0] = v
s, d = setup({0: spd}, {0: spd / KT})
base = written(run(s, d))[0]
mag, _ = written(run(s, d, {"Core lift": "On", "Lift where": M.TRIGGER_OWN}))
add = (mag - base)[:6, 0]
check("own trigger: 36-40 / 44-48 ramps", np.allclose(add, [0, 3, 6, 8, 10, 10], atol=1e-3), add)
tool_dialog = {k: (k, v) for k, v in M.DEFAULTS.items()}
check("dialog defaults On / models / 6 / 4", tool_dialog["Core lift"][1] == "On"
      and tool_dialog["Lift where"][1] == M.TRIGGER_MODELS and tool_dialog["Lift (kt)"][1] == 6.0
      and tool_dialog["Extra lift for HF (kt, 0 = off)"][1] == 4.0)
mag, _ = written(run(s, d, {"Core lift": "On", "Lift (kt)": 3.0, "Extra lift for HF (kt, 0 = off)": 0.0}))
check("dialog lift 3, extra 0", abs((mag - base)[5, 0] - 3.0) < 1e-3, (mag - base)[5, 0])

print("8. lift Off = plain blend")
spd = const(55)
s, d = setup({0: spd}, {0: spd / KT})
off = written(run(s, d, {"Core lift": "Off"}))[0]
on = written(run(s, d, {"Core lift": "On"}))[0]
check("Off equals the det_blend of the runs", np.allclose(off, 55.0, atol=1e-3), off[0, 0])
check("On is 10 kt above", np.allclose(on - off, 10.0, atol=1e-3))

print("9. edit area")
area = np.zeros(SHAPE, bool)
area[:5, :5] = True
p = run(s, d, {"Core lift": "On"}, area)
mag, _ = written(p)
check("inside the area lifted", abs(mag[1, 1] - 65) < 1e-3, mag[1, 1])
check("outside the area plain blend", abs(mag[8, 8] - 55) < 1e-3, mag[8, 8])
check("message counts the 25 lifted cells", "25 cells lifted" in p.msgs[-1][1], p.msgs[-1])

print("10. time interpolation of a 6-hourly model")
mid = T0 + 3 * H
trs = gfe_fakes.time_range(mid, 3 * H)
store, dbs = {}, {}
mid_ec = rid("D2D", "ECMWF", T0 - 12 * H)
store[(mid_ec, "wind", "FHAG10")] = {"units": "kts", "grids": [(gfe_fakes.time_range(T0), vec(const(20))),
                                                              (gfe_fakes.time_range(T0 + 6 * H), vec(const(40)))]}
dbs["D2D_ECMWF"] = [mid_ec]
store[("Fcst", "Wind", "SFC")] = {"units": "kts", "grids": [(trs, vec(const(0)))]}
SS.store, SS.dbs = store, dbs
p = M.Procedure(None)
p.execute(None, trs, {"Core lift": "Off"})
check("halfway between 20 and 40 -> 30 kt", np.allclose(written(p)[0], 30.0, atol=1e-3), written(p)[0][0, 0])

print("11. HF core: targeted by 925 mb wind x stability")
spd = const(10)
for i, v in enumerate([50, 54, 56, 56]):
    spd[i, 0] = v
s, d = setup({0: spd}, {0: spd / KT})
lift_on = {"Core lift": "On"}
base = written(run(s, d, lift_on))[0]
hf_on = dict(lift_on, **{"HF core (targeted by 925 mb wind and stability)": "On"})
p = run(s, d, hf_on)
check("no 925 data: HF core skipped, grid as without it", np.allclose(written(p)[0], base))
check("skip is said", any("HF core inputs not found" in m[1] for m in p.msgs), p.msgs[-1:])
gfs_id = d["GFS"][0]
w925 = const(90.0)       # x 0.70 = 63 >= 55: open
w925[3, 0] = 70.0        # x 0.70 = 49: too stable, closed
tr0 = gfe_fakes.time_range(T0)
s[(gfs_id, "wind", "MB925")] = {"units": "kts", "grids": [(tr0, vec(w925))]}
s[(gfs_id, "t", "SFC")] = {"units": "K", "grids": [(tr0, const(281.0))]}
s[(gfs_id, "t", "FHAG2")] = {"units": "K", "grids": [(tr0, const(280.0))]}   # sea - air 1 C -> 0.70
p = run(s, d, hf_on)
add = (written(p)[0] - base)[:4, 0]
msg = p.msgs[-1][1]
check("HF core CHECK in message: inputs, gate and cells raised",
      "HF core CHECK: read 1 of 1 grids; peak GFS 925 mb 90 kt; sea minus air 1 to 1 C; "
      "peak 925 x stability 63 kt (gate 55); 599 cells past gate" in msg and "2 cells raised" in msg and "WARNING" not in msg, msg)
s[(gfs_id, "wind", "MB925")]["units"] = "m/s"
s[(gfs_id, "wind", "MB925")]["grids"] = [(tr0, vec(const(400.0)))]
msg = run(s, d, hf_on).msgs[-1][1]
check("implausible 925 wind is flagged", "WARNING 925 mb wind peak" in msg, msg)
s[(gfs_id, "wind", "MB925")] = {"units": "kts", "grids": [(tr0, vec(w925))]}
p = run(s, d, {M.K_CEILING: "On"})   # lift off: the temp grid is still made
ceil = [c for c in p.created if c[1] == M.CEILING_GRID]
wind = [c for c in p.created if c[1] == "Wind"]
check("temp grid written once per time, SCALAR, beside Wind", len(ceil) == 1 and len(wind) == 1
      and ceil[0][2] == "SCALAR", [c[:3] for c in p.created])
g = ceil[0][3]
check("temp grid: 925 x 0.70 where >= 55 (63 kt), 0 where 49", np.isclose(g[0, 0], 63.0) and g[3, 0] == 0.0,
      g[:4, 0])
sa = [c for c in p.created if c[1] == M.SEA_AIR_GRID]
check("SeaMinusAir temp grid = 1 C", len(sa) == 1 and np.allclose(sa[0][3], 1.0))
check("temp grid said in message", "temp grids HFCeiling925" in p.msgs[-1][1] and "1 of 1 times" in p.msgs[-1][1])
check("temp grid default Off, none written", not [c for c in run(s, d).created if c[1] == M.CEILING_GRID])
quiet = M.HFCheck()
quiet.add(np.full((2, 2), 40.0), np.full((2, 2), 3.0), np.full((2, 2), 35.0), np.ones((2, 2), bool), np.zeros((2, 2)))
qt = quiet.text(1)
check("quiet day: inputs shown, nothing raised", "peak GFS 925 mb 40 kt" in qt and "peak 925 x stability 32 kt"
      in qt and "0 cells past gate" in qt and "0 cells raised" in qt and "WARNING" not in qt, qt)
check("not read: says so", "not read" in M.HFCheck().text(3))
check("HF core: +0 at 50, +3 at 54, +6 at 56, +0 where 925 x 0.70 < 55",
      np.allclose(add, [0, 3, 6, 0], atol=1e-3), add)
check("HF core default Off", M.DEFAULTS["HF core (targeted by 925 mb wind and stability)"] == "Off")
check("stability factors 0.70 / 0.79 / 0.83", np.allclose(M.stability_factor(np.array([1.0, 3.0, 6.0])), [0.70, 0.79, 0.83]))

print("13. lagged runs Off: current runs only")
rng = np.random.RandomState(1)
g = {lag: 20 + 25 * rng.rand(*SHAPE) for lag in (0, 12, 24)}
e = {lag: 20 + 25 * rng.rand(*SHAPE) for lag in (0, 12, 24)}
s, d = setup(g, {k: v / KT for k, v in e.items()})
p = run(s, d, {"Lagged runs (12 h and 24 h older GFS/ECMWF)": "Off"})
want = det_blend_direct([g[0], e[0]], [g[0], e[0]])
check("blend from the two current runs only", np.allclose(written(p)[0], want, atol=1e-3))
check("message says lagged runs off", "lagged runs off" in p.msgs[-1][1], p.msgs[-1])
check("default On", M.DEFAULTS["Lagged runs (12 h and 24 h older GFS/ECMWF)"] == "On")

print("12. self-contained: no grid_fetch, database names without model_aliases")
check("does not use grid_fetch", not hasattr(M, "grid_fetch"))
saved = M.model_aliases
M.model_aliases = None
check("fallback names GFS", M.database_candidates("GFS") == ["GFS", "D2D_GFS"], M.database_candidates("GFS"))
check("fallback names ECMWF", M.database_candidates("ECMWF") == ["D2D_ECMWF", "nECMWF0p25"], M.database_candidates("ECMWF"))
M.model_aliases = saved
check("run time parsed from id", M.model_run_time("X_D2D_GFS_19700102_1200") == 86400 + 12 * 3600)

print("14. settings window")
check("GFE variable list empty (own window)", M.VariableList == [])
check("dialog defaults match", M.DEFAULTS[M.K_LIFT] == 6.0 and M.DEFAULTS[M.K_LIFT2] == 4.0
      and M.DEFAULTS[M.K_HF] == "Off" and M.DEFAULTS[M.K_LAGGED] == "On")
SS.store, SS.dbs = s, d
proc = M.Procedure(None)
proc._show_gui = lambda: None
proc.execute(None, TR, {})
check("Cancel writes nothing", not proc.created)
proc = M.Procedure(None)
proc._show_gui = lambda: dict(M.DEFAULTS, **{M.K_LIFT_ON: "Off"})
proc.execute(None, TR, None)
plain = written(run(s, d))
check("window settings are used", np.allclose(written(proc)[0], plain[0]))

print()
print("FAILED: %s" % FAILURES if FAILURES else "all ok")
sys.exit(1 if FAILURES else 0)
