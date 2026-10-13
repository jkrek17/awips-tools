#!/usr/bin/env python3
"""Checks for GFE/procedures/Blend_WindGustWavePmsl.py against a fake GFE.

Each scenario builds a small model inventory, runs Procedure.execute() with a
varDict the way another procedure would, and asserts on what was written -
or that nothing was.

    python3 test_blend.py
"""
import sys

import numpy as np

import gfe_fakes

SS = gfe_fakes.install()
import Blend_WindGustWavePmsl as B  # noqa: E402

H = 3600
SHAPE = SS.shape
FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILURES.append(label)


def tr(h0, h1):
    return gfe_fakes.TimeRange(gfe_fakes.AbsTime(h0 * H), gfe_fakes.AbsTime(h1 * H))


def field(val, noise=True):
    g = np.full(SHAPE, float(val))
    if noise:
        g[0, 0] += 0.5  # so a real field is never one value everywhere
    return g


def series(h0, h1, step, make):
    return [(tr(h, h + 1), make(h)) for h in range(h0, h1 + 1, step)]


GFS18, GFS12 = "X_GRID__GFS_19700102_1800", "X_GRID__GFS_19700102_1200"
DGFS18, DGFS12 = "X_D2D_GFS_19700102_1800", "X_D2D_GFS_19700102_1200"
GWAVE = "X_GRID__GFSWave_19700102_1800"
EC12, ECWAVE = "X_D2D_ECMWF_19700102_1200", "X_GRID__ECMWFwave_19700102_1200"
CMC = "X_D2D_CMC_19700102_1200"


def base_store():
    """Fcst grids 3-hourly 48-72 h; GFS 18Z incomplete (to 60 h), 12Z complete."""
    s, d = {}, {}
    s[("Fcst", "Wind", "SFC")] = {"units": "kts", "grids": series(48, 72, 3, lambda h: (field(5), field(90, False)))}
    s[("Fcst", "WindGust", "SFC")] = {"units": "kts", "grids": series(48, 72, 3, lambda h: field(7))}
    s[("Fcst", "WaveHeight", "SFC")] = {"units": "ft", "grids": series(48, 72, 3, lambda h: field(3))}
    s[("Fcst", "pmsl", "SFC")] = {"units": "mb", "grids": series(48, 72, 3, lambda h: field(1000))}
    # GFS: GFE copy in kt, D2D pmsl in Pa
    d["GFS"] = [GFS18, GFS12]
    s[(GFS18, "Wind", "SFC")] = {"units": "kts", "grids": series(48, 60, 3, lambda h: (field(30), field(270, False)))}
    s[(GFS12, "Wind", "SFC")] = {"units": "kts", "grids": series(45, 78, 3, lambda h: (field(20), field(270, False)))}
    s[(GFS12, "WindGust", "SFC")] = {"units": "kts", "grids": series(45, 78, 3, lambda h: field(25))}
    d["D2D_GFS"] = [DGFS18, DGFS12]
    s[(DGFS18, "pmsl", "MSL")] = {"units": "Pa", "grids": series(48, 60, 3, lambda h: field(101000))}
    s[(DGFS12, "pmsl", "MSL")] = {"units": "Pa", "grids": series(45, 78, 3, lambda h: field(101000))}
    d["GFSWave"] = [GWAVE]
    s[(GWAVE, "WaveHeight", "SFC")] = {"units": "m", "grids": series(48, 78, 3, lambda h: field(2))}
    # ECMWF: D2D only, 6-hourly, m/s, no gusts
    d["D2D_ECMWF"] = [EC12]
    s[(EC12, "wind", "FHAG10")] = {"units": "m/s", "grids": series(48, 78, 6, lambda h: (field(10), field(270, False)))}
    s[(EC12, "pmsl", "MSL")] = {"units": "Pa", "grids": series(48, 78, 6, lambda h: field(100800))}
    d["ECMWFwave"] = [ECWAVE]
    s[(ECWAVE, "WaveHeight", "MSL")] = {"units": "m", "grids": series(48, 78, 6, lambda h: field(3))}
    # CMC: wind only
    d["D2D_CMC"] = [CMC]
    s[(CMC, "wind", "FHAG10")] = {"units": "m/s", "grids": series(48, 78, 3, lambda h: (field(10), field(270, False)))}
    return s, d


def run(weights, elements=None, mutate=None, mask=None):
    s, d = base_store()
    if mutate:
        mutate(s, d)
    SS.store, SS.dbs = s, d
    proc = B.Procedure(None)
    var = {"weights": weights, "gust_factor": 1.3}
    if elements:
        var["elements"] = elements
    proc.execute(mask, tr(48, 72), var)
    return proc


def written(proc, elem):
    return [(c[4], c[3]) for c in proc.created if c[1] == elem]


def last_msg(proc):
    return proc.msgs[-1] if proc.msgs else ("", "")


KT = 1.943844
FT = 1 / 0.3048

print("1. GFS 3 + ECMWF 2, all elements")
p = run({"GFS": 3, "ECMWF": 2})
check("32 grids written (4 elements x 8 times)", len(p.created) == 32, len(p.created))
w = written(p, "Wind")[1][1]  # 51 h: ECMWF interpolated between 48 and 54
check("wind speed = 0.6 GFS + 0.4 ECMWF (m/s -> kt, interpolated)",
      abs(w[0][5, 5] - (0.6 * 20 + 0.4 * 10 * KT)) < 1e-3, w[0][5, 5])
check("wind direction kept", abs(w[1][5, 5] - 270) < 1e-6, w[1][5, 5])
g = written(p, "WindGust")[0][1]
check("gust: GFS gust grid + ECMWF wind x 1.3", abs(g[5, 5] - (0.6 * 25 + 0.4 * 10 * KT * 1.3)) < 1e-3, g[5, 5])
wv = written(p, "WaveHeight")[0][1]
check("waves m -> ft", abs(wv[5, 5] - (0.6 * 2 + 0.4 * 3) * FT) < 1e-3, wv[5, 5])
pm = written(p, "pmsl")[0][1]
check("pmsl Pa -> mb", abs(pm[5, 5] - (0.6 * 1010 + 0.4 * 1008)) < 1e-3, pm[5, 5])
check("incomplete GFS 18Z skipped and reported", "18Z run" in last_msg(p)[1] and last_msg(p)[0] == "R", last_msg(p))

print("2. CMC has no pmsl")
p = run({"GFS": 1, "CMC": 1})
check("nothing written", not p.created, len(p.created))
check("urgent error names CMC and pmsl", last_msg(p)[0] == "U" and "CMC" in last_msg(p)[1] and "pmsl" in last_msg(p)[1], last_msg(p))

print("3. UKMET: no database and no wave pairing")
p = run({"GFS": 1, "UKMET": 1})
check("nothing written", not p.created, len(p.created))
check("error says UKMET has no wave model", "no paired wave model" in last_msg(p)[1], last_msg(p))


def zero_pmsl(s, d):
    s[(DGFS12, "pmsl", "MSL")]["grids"][4] = (tr(57, 58), np.zeros(SHAPE))


print("4. An all-zero GFS pmsl grid")
p = run({"GFS": 1, "ECMWF": 1}, mutate=zero_pmsl)
check("nothing written", not p.created, len(p.created))
check("error calls the grid empty", last_msg(p)[0] == "U" and "empty" in last_msg(p)[1], last_msg(p))

print("5. Edit area")
m = np.zeros(SHAPE, bool)
m[:10] = True
p = run({"GFS": 1}, elements=["Wind", "pmsl"], mask=m)
w = written(p, "Wind")[0][1]
check("wind changed inside, kept outside", w[0][5, 5] == 20 and w[0][15, 5] == 5, (w[0][5, 5], w[0][15, 5]))
pm = written(p, "pmsl")[0][1]
check("pmsl changed inside, kept outside", abs(pm[5, 5] - 1010) < 1e-3 and pm[15, 5] == 1000, (pm[5, 5], pm[15, 5]))

print("6. Gusts only, from a model without gust grids")
p = run({"ECMWF": 1}, elements=["WindGust"])
g = written(p, "WindGust")[0][1]
check("gust = ECMWF wind x 1.3", abs(g[5, 5] - 10 * KT * 1.3) < 1e-3, g[5, 5])


def complete_18z(s, d):
    s[(GFS18, "Wind", "SFC")]["grids"] = series(45, 78, 3, lambda h: (field(30), field(270, False)))
    s[(GFS18, "WindGust", "SFC")] = {"units": "kts", "grids": series(45, 78, 3, lambda h: field(35))}
    s[(DGFS18, "pmsl", "MSL")]["grids"] = series(45, 78, 3, lambda h: field(101000))


print("7. GFS 18Z complete")
p = run({"GFS": 1}, elements=["Wind", "WindGust", "pmsl"], mutate=complete_18z)
check("newest run used", written(p, "Wind")[0][1][0][5, 5] == 30)
check("status names GFS 18Z", "GFS 18Z" in last_msg(p)[1], last_msg(p))


def wave_gap(s, d):
    s[(ECWAVE, "WaveHeight", "MSL")]["grids"] = (series(48, 54, 6, lambda h: field(3))
                                                 + series(66, 78, 6, lambda h: field(3)))


print("8. A 12 h gap in the ECMWF wave grids")
p = run({"ECMWF": 1}, elements=["WaveHeight"], mutate=wave_gap)
check("nothing written", not p.created, len(p.created))
check("error names the missing time", "no grid at or near" in last_msg(p)[1], last_msg(p))


def land_nan(s, d):
    def wave(val):
        g = field(val)
        g[:, :5] = np.nan  # land in both wave models
        g[0, 10] += 0.5    # keep a varying sea point
        return g
    s[(GWAVE, "WaveHeight", "SFC")]["grids"] = series(48, 78, 3, lambda h: wave(2))
    s[(ECWAVE, "WaveHeight", "MSL")]["grids"] = series(48, 78, 6, lambda h: wave(3))


print("9. Wave grids with land masked out")
p = run({"GFS": 1, "ECMWF": 1}, elements=["WaveHeight"], mutate=land_nan)
wv = written(p, "WaveHeight")[0][1]
check("land keeps the Fcst value, sea is blended", wv[5, 2] == 3 and abs(wv[5, 10] - 2.5 * FT) < 1e-3,
      (wv[5, 2], wv[5, 10]))

print()
if FAILURES:
    print("%d check(s) failed: %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("all checks passed")
