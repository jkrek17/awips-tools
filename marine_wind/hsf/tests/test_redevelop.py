"""HSF writer: a gale that passes from a filling low to a new centre forming in its winds stays
one warning (Jason 11-11, 06Z 11 Nov Atlantic NDFD draft: "LOW 61N68W ... 24 HOUR FORECAST LOW
DISSIPATED" and a separate "6 HOUR FORECAST NEW LOW 61N63W" warning over the same gale).

Low A sits at 61N68W at the synopsis and runs SW inland and fills; low B forms at 6 h under A's gale
and carries it east. The text must keep one paragraph for the gale, named after A at the
synopsis and B later, moving the way the text moves (E), with no NEW and no LOW DISSIPATED.

    python3 marine_wind/hsf/tests/test_redevelop.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from writer import Grid, Rules, link_tracks, write_product  # noqa: E402

FAIL = []


def check(name, ok, got=None):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  %s" % (got,)))
    if not ok:
        FAIL.append(name)


lats = 70.0 - 0.25 * np.arange(81)          # 70N..50N
lons = -80.0 + 0.25 * np.arange(201)        # 80W..30W
grid = Grid(lats, lons)
LAT, LON = grid.LAT, grid.LON
land = (LAT < 60.0) & (LON < -66.0)           # Ungava: A fills over land, as on 11 Nov
sea = ~land


def bowl(la, lo, depth, size=3.0):
    return depth * np.exp(-(((LAT - la) / size) ** 2 + ((LON - lo) * np.cos(np.radians(la)) / size) ** 2))


def blob(la, lo, peak):
    return peak * np.exp(-(((LAT - la) / 1.5) ** 2 + ((LON - lo) * np.cos(np.radians(la)) / 3.0) ** 2))


fields = {}
for h in range(0, 49, 6):
    msl = np.full(LAT.shape, 1016.0)
    if h <= 6:                                   # A: 61N68W, then SW and filling, gone by 12 h
        msl -= bowl(61.0 - h * 0.67, -68.0 - h * 0.85, 16.0 - h / 3.0)
    if h >= 6:                                   # B: forms at 61N62W at 6 h, runs E
        msl -= bowl(61.0, -62.0 + (h - 6) * 0.5, min(14.0, 8.0 + (h - 6) / 2.0))
    gl, go = (64.0, -62.0) if h == 0 else (64.0, -61.0 + (h - 6) * 0.5)
    wind = np.maximum(10.0, blob(gl, go, 42.0 if h <= 30 else 25.0))
    fields[h] = dict(wind=wind, msl=msl, hs=np.where(land, np.nan, 4.0))

warn, syn, dbg = write_product(fields, grid, sea, Rules())
print(warn)
print(syn)
paras = [p for p in (warn + "\n\n" + syn).split("\n\n") if p.strip()]
gale = [p for p in paras if p.startswith("...GALE WARNING...")]
check("one gale warning", len(gale) == 1, paras)
if gale:
    g = gale[0]
    check("... starts at the synopsis low 61N68W", "\n.LOW 61N68W" in g, g)
    check("... moving the way the text moves (E)", "61N68W 1000 MB MOVING E" in g or "MOVING E " in g.split("\n")[1], g)
    check("... no NEW", "NEW" not in g, g)
    check("... no LOW DISSIPATED", "DISSIPATED" not in g, g)
    check("... carried to 24 h on the new centre", ".24 HOUR FORECAST LOW 61N" in g, g)

# a track may skip one 6 h step, but only to a centre one ordinary step away: a 12 h bridge once
# joined 44N62W to a different low 600 nm WSW, and its later gale headed a "GALE WARNING" whose
# text showed only 20 TO 30 KT (Jason 11-11, same draft)
def lw(la, lo):
    return (la, lo, 1004, la, lo)


t = link_tracks({0: [lw(44, -64)], 6: [lw(44, -62)], 12: [], 18: [lw(38, -73)]})
check("a 12 h gap does not bridge 600 nm", t[18][0][0] != t[6][0][0], t)
t = link_tracks({0: [lw(44, -64)], 6: [lw(44, -62)], 12: [], 18: [lw(45, -58)]})
check("... but bridges a nearby centre", t[18][0][0] == t[6][0][0], t)

print("FAIL: %s" % FAIL if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
