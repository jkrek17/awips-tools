"""Best Wind (storm.best_wind): ramps on the stronger of GFS/ECMWF and the GEFS-gated HF core.

    python3 marine_wind/pipeline/tests/test_best_wind.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import storm  # noqa: E402

FAIL = []


def check(name, ok, got=None):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  %s" % (got,)))
    if not ok:
        FAIL.append(name)


ny, nx = 20, 30
lats = np.linspace(60, 20, ny)       # rows north to south, 1-D as domain.LATS
wind = np.full((ny, nx), 30.0, np.float32)
ocean = np.ones((ny, nx), bool)
gfs = np.zeros((ny, nx), np.float32)
ifs = np.zeros((ny, nx), np.float32)
p48 = np.zeros((ny, nx), np.float32)
row = 2
for i, s in enumerate((35, 38, 40, 42, 44, 46, 48, 50, 54, 56)):
    gfs[row, 2 * i] = s
b = storm.best_wind(wind, gfs, ifs, p48, ocean, lats)
add = b[row, ::2][:10] - 30
check("ramps 36-40 (+6) and 44-48 (+4)", np.allclose(add, [0, 3, 6, 6, 6, 8, 10, 10, 10, 10]), add)
p48[:] = 0.0
p48[row, 16] = 0.35                  # one cell >= 30%: spreads ~100 km (NB box)
b = storm.best_wind(wind, gfs, ifs, p48, ocean, lats)
add = b[row, ::2][:10] - 30
check("HF core where GEFS P48 >= 30% nearby: 54 -> +3, 56 -> +6", np.allclose(add[8:], [13, 16]), add)
p48[row, 16] = 0.25
check("no HF core under 30%", np.allclose(storm.best_wind(wind, gfs, ifs, p48, ocean, lats)[row, 18] - 30, 10))
check("stronger model: ECMWF counts too", storm.best_wind(wind, ifs, gfs, p48, ocean, lats)[row, 4] - 30 == 6)
land = ocean.copy()
land[row, 4] = False
check("land not lifted", storm.best_wind(wind, gfs, ifs, p48, land, lats)[row, 4] == 30)
g2 = np.zeros((ny, nx), np.float32)
g2[-1, 4] = 42                       # row at 20N
check("no lift within 25 deg of the equator", storm.best_wind(wind, g2, ifs, p48, ocean, lats)[-1, 4] == 30)
check("NaN model ignored", storm.best_wind(wind, gfs, np.full((ny, nx), np.nan), p48, ocean, lats)[row, 4] == 36)

# gale floor: Core Lifted at 60%, Best Wind at 80% (7 Nov 2026)
w = np.array([30.0, 30.0, 30.0, 40.0]); pg = np.array([0.59, 0.7, 0.85, 0.9])
check("Core Lifted floor at 60%", list(storm.gale_lift(w, pg)) == [30, 34, 34, 40])
check("Best Wind floor at 80%", list(storm.gale_lift(w, pg, storm.BEST_GALE_P)) == [30, 30, 34, 40])

print()
print("FAILED: %s" % FAIL if FAIL else "all ok")
sys.exit(1 if FAIL else 0)
