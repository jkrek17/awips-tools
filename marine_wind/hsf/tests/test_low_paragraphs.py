"""HSF writer: each low keeps its own paragraph (Jason 11-07, 06Z 7 Nov Pacific NDFD draft).

A fast low runs east; a second low forms behind it, shares its wind area for a few hours (so the
two are one complex low then), and later deepens on its own with a storm core 30 degrees west.
The trailing low's storm core must get its own paragraph, not ride as an ALSO area under the
departing low's 30 and 48 h forecasts.

    python3 marine_wind/hsf/tests/test_low_paragraphs.py
"""
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from writer import Grid, Rules, Tier, continuous_ranges, write_product  # noqa: E402

FAIL = []


def check(name, ok, got=None):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  %s" % (got,)))
    if not ok:
        FAIL.append(name)


lats = 62.0 - 0.25 * np.arange(129)        # 62N..30N
lons = 160.0 + 0.25 * np.arange(361)       # 160E..130W
grid = Grid(lats, lons)
LAT, LON = grid.LAT, grid.LON
sea = np.ones(LAT.shape, bool)


def low_at(h, kind):
    """(lat, lon, depth hPa, peak wind kt) or None."""
    if kind == "A":                                   # 46N173W moving E ~35 kt, gale
        return 46.0, 187.0 + 0.85 * h, 22.0, 42.0
    if h < 6:                                         # B forms behind A at +6 h
        return None
    lon = 183.0 + 0.1 * (h - 6)                       # 47N177W, nearly stationary
    return 47.0, lon, 8.0 + 0.3 * (h - 6), 30.0 + (h - 6) * 0.55   # 30 kt at +6, 53 kt at +48


fields = {}
for h in range(0, 49, 6):
    msl = np.full(LAT.shape, 1016.0)
    wind = np.full(LAT.shape, 10.0)
    for kind in "AB":
        lw = low_at(h, kind)
        if lw is None:
            continue
        la, lo, dp, pk = lw
        r2 = ((LAT - la) / 4.0) ** 2 + ((LON - lo) * np.cos(np.radians(la)) / 4.0) ** 2
        msl -= dp * np.exp(-r2)
        # ring of wind 1.5-4 deg south of the centre
        rr2 = ((LAT - (la - 2.5)) / 2.0) ** 2 + ((LON - lo) * np.cos(np.radians(la)) / 5.0) ** 2
        wind = np.maximum(wind, pk * np.exp(-rr2))
    if 6 <= h <= 12:   # the two share one wind area while close: one complex low then
        band = (LAT >= 43.0) & (LAT <= 45.0) & (LON >= low_at(h, "B")[1]) & (LON <= low_at(h, "A")[1])
        wind[band] = np.maximum(wind[band], 28.0)
    fields[h] = dict(wind=wind, msl=msl, hs=np.full(LAT.shape, 4.0))

warn, syn, dbg = write_product(fields, grid, sea, Rules())
paras = [p for p in warn.split("\n\n") if p.strip()]
print(warn)


def lons_in(text):
    return [int(x) for x in re.findall(r"(\d+)W", text)]


a = [p for p in paras if ".LOW 46N173W" in p]
check("the departing low has a paragraph from the synopsis", len(a) == 1, paras)
if a:
    later = [ln for ln in a[0].split("\n") if ln.startswith(".30 HOUR") or ln.startswith(".48 HOUR")]
    west = [x for ln in later for x in lons_in(ln) if x >= 170]
    check("no area near the trailing low (170W-180W) in the departing low's 30/48 h lines", not west, later)
b = [p for p in paras if "NEW LOW" in p]
check("the trailing low has its own paragraph", len(b) == 1, paras)
if b:
    check("... under a storm warning", b[0].startswith("...STORM WARNING..."), b[0][:40])
    check("... that carries it to 48 h", ".48 HOUR FORECAST LOW 47N1" in b[0], b[0])

gaps = []
for ln in (warn + "\n" + syn).split("\n"):
    w = [tuple(map(int, x)) for x in re.findall(r"WINDS (\d+) TO (\d+) KT", ln)]
    gaps += [(a_, b_) for a_, b_ in zip(w, w[1:]) if b_[1] < a_[0]]
check("wind ranges run on without gaps (55 TO 70, 40 TO 55, 25 TO 40)", not gaps, gaps)

z = np.zeros((2, 2), bool)
got = [t.wind for t in continuous_ranges([Tier(64, {}, (55, 70), None, z), Tier(48, {}, (45, 60), None, z),
                                          Tier(25, {}, (20, 30), None, z)])]
check("HF tiers read 55 TO 70, 40 TO 55, 25 TO 40 (Jason 11-07)", got == [(55, 70), (40, 55), (25, 40)], got)

print("FAIL: %s" % FAIL if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
