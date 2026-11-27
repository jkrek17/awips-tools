"""HSF writer: a wind area is written under a low only when it lies near that low (Jason 11-25).

12Z 24 Nov Pacific draft: "COMPLEX LOW WITH MAIN CENTER 58N146W" carried a storm area at
55N176E, 1,140 nm away, because a 939 MB low over Kamchatka (the one driving that storm) was not
followed and the area went to a far secondary centre of the complex. Limits from the issued
HSFEP1/HSFAT1 (named low to its first warning area): 450 nm for a low in the area, 650 nm for a
low outside it; deep lows over land within 600 nm of the area are followed as "LOW W OF AREA".

    python3 marine_wind/hsf/tests/test_area_reach.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from writer import Grid, Rules, areas_for_time, write_product  # noqa: E402

FAIL = []


def check(name, ok, got=None):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  %s" % (got,)))
    if not ok:
        FAIL.append(name)


lats = 66.0 - 0.25 * np.arange(145)        # 66N..30N
lons = 150.0 + 0.25 * np.arange(441)       # 150E..120W
grid = Grid(lats, lons)
LAT, LON = grid.LAT, grid.LON
R = Rules()


def blob(la, lo, r_deg, kt):
    return kt * np.exp(-(((LAT - la) / r_deg) ** 2 + ((LON - lo) * np.cos(np.radians(la)) / r_deg) ** 2))


def far_nm(low, mask):
    return float(grid.dist_bearing(low[0], low[1])[0][mask].min())


# 1. complex low: main centre A (deep) and secondary B 9 deg west share a 28 kt band. A storm
# patch 5 deg west of B is ~330 nm from B and ~760 nm from A: it must not be written under A.
sea = np.ones(LAT.shape, bool)
hs = np.full(LAT.shape, 4.0)
A = (52.0, 210.0, 975, None, 1)
B = (54.0, 196.0, 990, None, 2)
wind = np.full(LAT.shape, 10.0)
band = (LAT >= 52.0) & (LAT <= 54.0) & (LON >= 196.0) & (LON <= 210.0)
wind[band] = 28.0
wind = np.maximum(wind, blob(53.0, 186.0, 1.5, 52.0))
systems = areas_for_time(wind, hs, sea, grid, [A, B], R)
storm = (wind >= 39)
for s in systems:
    if s["low"] is not None and (s["region"] & storm).any():
        lim = R.own_in_nm
        check("storm patch's named low within %d nm (got %s)" % (lim, s["low"][:3]), far_nm(s["low"], s["region"] & storm) <= lim,
              far_nm(s["low"], s["region"] & storm))
owner = [s for s in systems if (s["region"] & storm).any()]
check("storm patch has one owner", len(owner) == 1, len(owner))
check("storm patch goes to B, not complex main centre A", owner and owner[0]["low"] is not None and owner[0]["low"][4] == 2,
      owner and owner[0]["low"])

# 2. an isolated gale 10 deg from every low stands alone (no low)
wind2 = np.full(LAT.shape, 10.0)
wind2 = np.maximum(wind2, blob(50.0, 222.0, 2.0, 42.0))
wind2 = np.maximum(wind2, blob(40.0, 175.0, 2.0, 42.0))   # 40N175E, ~850 nm from the low
systems2 = areas_for_time(wind2, hs, sea, grid, [(50.0, 222.0, 980, None, 1)], R)
far = (wind2 >= 30) & (LON < 190)
fo = [s for s in systems2 if (s["region"] & far).any()]
check("far gale stands alone", len(fo) == 1 and fo[0]["low"] is None, [s["low"] for s in fo])
check("the low keeps its own gale", any(s["low"] is not None and s["low"][4] == 1 for s in systems2))

# 3. a deep low over land 500 nm west of the area drives a storm just inside the area: it is
# followed and named "LOW W OF AREA"; the storm is not written under the distant in-area low
land = LON < 170.0                       # land west of 170E (Kamchatka stand-in)
sea3 = (LON >= 180.0)                    # the forecast area east of 180
fields = {}
for h in range(0, 49, 6):
    msl = np.full(LAT.shape, 1014.0)
    msl -= 70.0 * np.exp(-(((LAT - 60.0) / 5.0) ** 2 + ((LON - 163.0) * 0.5 / 5.0) ** 2))   # 944 mb at 60N163E
    msl -= 30.0 * np.exp(-(((LAT - 57.0) / 4.0) ** 2 + ((LON - 214.0) * 0.55 / 4.0) ** 2))  # 57N146W in the area
    w = np.full(LAT.shape, 10.0)
    w = np.maximum(w, blob(55.0, 182.0, 1.5, 50.0))     # Bering storm at 55N178W
    w = np.maximum(w, blob(55.0, 214.0, 1.5, 36.0))     # the in-area low's own gale
    hs3 = np.where(land, np.nan, 4.0)
    fields[h] = dict(wind=w, msl=msl, hs=hs3)
warn, syn, dbg = write_product(fields, grid, sea3, R)
print(warn)
paras = [p for p in warn.split("\n\n") if p.strip()]
st = [p for p in paras if p.startswith("...STORM WARNING")]
check("one storm warning", len(st) == 1, paras)
check("storm warning names the land low as LOW W OF AREA 60N163E",
      bool(st) and "W OF AREA 60N163E" in st[0], st)
check("no area written more than 650 nm from its named low",
      all(p["low"] is None or not p["tiers"] or
          far_nm(p["low"], p["tiers"][0].mask) <= R.own_out_nm for p in dbg["pieces"]))

# 4. a gale that shows only at 12 and 18 h (gone by 24 h) is not written as a warning; one that
# lasts to 24 h is (Jason 11-25)
def run(hours_on):
    f = {}
    for h in range(0, 49, 6):
        w = np.full(LAT.shape, 10.0)
        if h in hours_on:
            w = np.maximum(w, blob(45.0, 200.0, 1.5, 42.0))
        f[h] = dict(wind=w, msl=np.full(LAT.shape, 1016.0), hs=np.full(LAT.shape, 4.0))
    return write_product(f, grid, np.ones(LAT.shape, bool), R)[0]
check("gale only at 12-18 h: no warning", "WARNING" not in run((12, 18)), run((12, 18)))
check("gale 12-24 h: a gale warning", "GALE WARNING" in run((12, 18, 24)), run((12, 18, 24)))

print("\n%d failed" % len(FAIL) if FAIL else "\nall passed")
sys.exit(1 if FAIL else 0)
