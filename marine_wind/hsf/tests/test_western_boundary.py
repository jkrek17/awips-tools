"""HSF writer: a low that crosses into the forecast area keeps one paragraph and is named while
still outside it (Jason 11-07, 12Z 7 Nov Pacific NDFD draft: winds coming in across 180W were
split into a paragraph with no low, a NEW LOW and a gale absorbed an hour later).

A gale low runs east from 165E, so its winds reach the 180W edge before its centre does. The
writer must name it "LOW W OF AREA ..." while the centre is west of 180W, not call it NEW
(it was on the map at the synopsis), keep it in one paragraph to 48 h, and write no paragraph
without a low.

    python3 marine_wind/hsf/tests/test_western_boundary.py
"""
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from writer import Grid, Rules, write_product  # noqa: E402

FAIL = []


def check(name, ok, got=None):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  %s" % (got,)))
    if not ok:
        FAIL.append(name)


lats = 62.0 - 0.25 * np.arange(129)        # 62N..30N
lons = 150.0 + 0.25 * np.arange(401)       # 150E..110W
grid = Grid(lats, lons)
LAT, LON = grid.LAT, grid.LON
sea = LON >= 180.0                         # the forecast area: east of 180W, all water


def centre(h):
    return 45.0, 165.0 + 1.0 * h            # 45N165E moving E ~40 kt


fields = {}
for h in range(0, 49, 6):
    la, lo = centre(h)
    r2 = ((LAT - la) / 4.0) ** 2 + ((LON - lo) * np.cos(np.radians(la)) / 4.0) ** 2
    msl = 1016.0 - 22.0 * np.exp(-r2)
    # gales in a band 1.5-4 deg south of the centre, reaching ~12 deg east of it
    rr2 = ((LAT - (la - 2.5)) / 2.0) ** 2 + ((LON - lo - 4.0) * np.cos(np.radians(la)) / 6.0) ** 2
    wind = np.maximum(10.0, 44.0 * np.exp(-rr2))
    fields[h] = dict(wind=wind, msl=msl, hs=np.full(LAT.shape, 4.0))   # seas everywhere: open ocean

warn, syn, dbg = write_product(fields, grid, sea, Rules())
print(warn)
print(syn)
paras = [p for p in (warn + "\n\n" + syn).split("\n\n") if p.strip()]
gale = [p for p in paras if "LOW" in p and "45N" in p]
check("one paragraph follows the low", len(gale) == 1, paras)
if gale:
    g = gale[0]
    check("... named W OF AREA while its centre is west of 180W", re.search(r"LOW W OF AREA 45N1\d\dE ", g), g)
    check("... not called NEW (it was there at the synopsis)", "NEW" not in g, g)
    check("... under a gale warning", g.startswith("...GALE WARNING..."), g[:40])
    check("... carried to 48 h", ".48 HOUR FORECAST LOW 45N" in g, g)
orphans = [p for p in paras if "LOW" not in p.split("\n")[1 if p.startswith("...") else 0]]
check("no paragraph without a low", not orphans, orphans)

print("FAIL: %s" % FAIL if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
