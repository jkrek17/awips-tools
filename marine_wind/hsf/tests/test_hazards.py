"""HSF draft: fog and freezing spray paragraphs (Jason 11-11: synopsis, 24 h and 48 h only;
spray from the Overland predictor, fog from GFS surface visibility).

    python3 marine_wind/hsf/tests/test_hazards.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hazards import hazard_text, overland_ppr, spray_class  # noqa: E402
from writer import Grid, Rules  # noqa: E402

FAIL = []


def check(name, ok, got=None):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  %s" % (got,)))
    if not ok:
        FAIL.append(name)


# Overland: 30 kt, air -10 C, sea 2 C -> 15.4 * 8.3 / (1 + 0.3 * 3.7) = 60.6 (heavy)
p = float(overland_ppr(30.0, -10.0, 2.0))
check("Overland PPR 30 kt / -10 C air / 2 C sea", abs(p - 60.6) < 0.5, p)
check("no spray with air above -1.7 C", float(overland_ppr(50.0, -1.0, 0.0)) == 0.0)
check("classes light / moderate / heavy",
      list(spray_class(np.array([10.0, 25.0, 40.0]), np.array([-4.0, -8.0, -12.0]), np.array([4.0, 4.0, 2.0]))) == [1, 2, 3],
      spray_class(np.array([10.0, 25.0, 40.0]), np.array([-4.0, -8.0, -12.0]), np.array([4.0, 4.0, 2.0])))
check("none over sea ice", int(spray_class(40.0, -20.0, -1.7, ice=np.array(0.9))) == 0)

lats = 66.0 - 0.25 * np.arange(97)          # 66N..42N
lons = 180.0 + 0.25 * np.arange(161)        # 180..140W (0-360)
grid = Grid(lats, lons)
LAT, LON = grid.LAT, grid.LON
sea = np.ones(LAT.shape, bool)
shape = LAT.shape


def fields(fog_box=None, cold_n=None, wind=20.0):
    out = {}
    for h in (0, 6, 24, 48):
        vis = np.full(shape, 20000.0)
        if fog_box:
            s, n, w, e = fog_box
            vis[(LAT >= s) & (LAT <= n) & (LON >= w) & (LON <= e)] = 400.0
        t2 = np.where(LAT >= cold_n, -14.0, 5.0) if cold_n else np.full(shape, 5.0)
        out[h] = dict(wind=np.full(shape, wind), t2=t2, sst=np.full(shape, 1.0), vis=vis, ice=np.zeros(shape))
    return out


# fog box 50-53N, 160-165W, every time
warn, syn, areas = hazard_text(fields(fog_box=(50, 53, 195, 200)), sea, grid, Rules())
check("fog only: no warning", warn == "", warn)
check("fog paragraph opens with the visibility line",
      syn and syn[0].startswith(".DENSE FOG. VSBY OCCASIONALLY LESS THAN 1 NM FROM 50N TO 53N BETWEEN 160W AND 165W."), syn)
check("fog at 24 and 48 h, no 6 h step",
      ".24 HOUR FORECAST DENSE FOG FROM" in syn[0] and ".48 HOUR FORECAST DENSE FOG FROM" in syn[0] and "6 HOUR" not in syn[0].replace("36 HOUR", ""), syn)
check("fog areas carry kind and hour", sorted(a["hour"] for a in areas if a["kind"] == "fog") == [0, 24, 48], areas)

# cold air north of 58N with 20 kt: PPR = 10.3 * 12.3 / 1.81 = 70 -> heavy -> warning block
warn, syn, areas = hazard_text(fields(cold_n=58), sea, grid, Rules())
check("heavy spray goes under WARNINGS", warn.startswith("...HEAVY FREEZING SPRAY WARNING...\n.MODERATE TO HEAVY FREEZING SPRAY "), warn)
check("heavy spray lines at 24 and 48 h", ".24 HOUR FORECAST MODERATE TO HEAVY FREEZING SPRAY" in warn and ".48 HOUR FORECAST" in warn, warn)
check("no spray paragraph left in the synopsis", not any("FREEZING SPRAY" in s for s in syn), syn)

# 8 kt in the same cold air: PPR = 4.1 * 12.3 / 1.81 = 28 -> moderate -> synopsis paragraph
warn, syn, areas = hazard_text(fields(cold_n=58, wind=8.0), sea, grid, Rules())
check("moderate spray stays in the synopsis", warn == "" and syn and syn[-1].startswith(".LIGHT TO MODERATE FREEZING SPRAY "), (warn, syn))

# nothing: no paragraphs at all
warn, syn, areas = hazard_text(fields(), sea, grid, Rules())
check("no fog, no spray: nothing written", warn == "" and syn == [] and areas == [], (warn, syn))

print("FAILED: %s" % FAIL if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
