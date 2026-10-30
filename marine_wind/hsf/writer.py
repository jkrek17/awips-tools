"""Write High Seas Forecast text from wind / seas / pressure grids.

Plain numpy arrays in, text out: the same code serves the marine wind page (build_hsf.py)
and, later, a GFE formatter fed from the forecaster's own grids.

One valid time:
  areas_for_time(wind, hs, sea, lows, rules) -> list of systems, each with tiers of
  (phrase, wind range, seas range, mask)

Describing a region (a mask of grid cells), in Jason's order of preference:
  1. a whole-degree lat/lon box ("FROM 51N TO 56N BETWEEN 130W AND 135W")
  2. quadrants / semicircles around the low, radii in 60 nm steps
  3. within X nm of a line through the region
A later form is used only when it describes the region clearly better than the box
(rules.box_margin): mariners can plot a box by hand.
Each candidate is scored by catch (share of the region inside) minus a penalty for
empty sea added (share of the candidate outside the region).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

R_NM = 3440.065
DIR8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
STD_RANGES = [(20, 30), (25, 35), (25, 40), (30, 40), (30, 45), (35, 45), (35, 50), (40, 50), (40, 55),
              (45, 55), (45, 60), (50, 60), (50, 65), (55, 70), (60, 75), (65, 80), (70, 85)]


@dataclass
class Rules:
    outer_kt: float = 25.0        # grid wind that starts the outer (ELSEWHERE) area
    levels: tuple = (34, 48, 64)  # gale, storm, hurricane force
    seas_min: float = 4.0         # seas that make an area worth describing on their own
    min_cells: int = 20           # ignore specks smaller than this (0.25 deg cells)
    # draw each warning area this many kt below its level. Winter 2025-26 Pacific vs ASCAT, 60 nm
    # ring billed (hsf/stats/rescore_2026-10-17): gale at 30 kt covers 94% of ASCAT gale water at
    # 43% of the desk's area. Storm at 39 kt on Core Lifted, held-out weeks: 66% of storm water
    # (44 kt: 48%), matching the page's storm hazard line (Core Lifted >= 39, Jason 10-17)
    draw_offset: dict = field(default_factory=lambda: {34: 4.0, 48: 9.0, 64: 4.0})
    core_min_cells: int = 1       # a warning-level core is kept down to this size ("a few pixels of storm = storm warning")
    extra_weight: float = 0.6     # penalty per unit of empty sea added (as share of candidate)
    box_margin: float = 0.08      # a non-box form must beat the box by this much
    attach_nm: float = 900.0      # a region within this of a low belongs to that low
    hi_from: str = "max"          # top of the wind range from the region's max ("few pixels" rule)
    hi_add: float = 0.0           # kt added to the grid peak before picking the range
    hi_pct: float = 99.0          # percentile used when hi_from == "pct"
    hi_round: str = "up"          # round the grid peak up to 5 kt (matches the desk: top ~ GFS max rounded up)
    complex_nm: float = 600.0     # lows this close that share one 25 kt+ area form one complex low
    share_nm: float = 300.0       # a low "touches" a wind area when the area comes this close to it
    area_buffer_deg: float = 3.0  # lows must be inside the forecast area or this close to it
    seas_peak_ratio: float = 2.0  # seas range wider than this (high over low): say where the highest are
    absorb_share: float = 0.25    # a gale core under this share of the area round it, and
    absorb_cells: int = 200       # under this many cells (~12 sq deg), joins that area


def lon_txt(x):
    x = round(x) % 360   # rounded first, so 179.8 reads 180W, not 180E
    if x == 180:
        return "180W"
    return "%dE" % round(x) if x < 180 else "%dW" % round(360 - x)


def lat_txt(y):
    return "%dN" % round(y)


def ll_txt(y, x):
    return lat_txt(y) + lon_txt(x)


# ---------------------------------------------------------------- geometry helpers
class Grid:
    def __init__(self, lats, lons):
        self.lats, self.lons = np.asarray(lats), np.asarray(lons)
        self.LON, self.LAT = np.meshgrid(self.lons, self.lats)
        self.dlat = abs(self.lats[1] - self.lats[0])

    def dist_bearing(self, lat, lon):
        p1, p2 = math.radians(lat), np.radians(self.LAT)
        dl = np.radians(self.LON - lon)
        a = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
        d = 2 * R_NM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        y = np.sin(dl) * np.cos(p2)
        x = math.cos(p1) * np.sin(p2) - math.sin(p1) * np.cos(p2) * np.cos(dl)
        b = (np.degrees(np.arctan2(y, x)) + 360) % 360
        return d, b


def score(cand, region, sea, w):
    c = cand & sea
    n = c.sum()
    if n == 0:
        return -1.0, 0.0, 1.0
    catch = (c & region).sum() / region.sum()
    extra = (c & ~region).sum() / n
    return catch - w * extra, catch, extra


# ---------------------------------------------------------------- 1. box
def best_box(region, sea, grid, rules):
    ys, xs = np.nonzero(region)
    la, lo = grid.lats[ys], grid.lons[xs]
    s0, n0 = math.floor(la.min()), math.ceil(la.max())
    w0, e0 = math.floor(lo.min()), math.ceil(lo.max())
    n0, e0 = max(n0, s0 + 1), max(e0, w0 + 1)
    # trim long tails: try edges between the 0th and 15th percentile inwards
    S = range(s0, int(math.floor(np.percentile(la, 15))) + 1)
    N = range(min(int(math.ceil(np.percentile(la, 85))), n0), n0 + 1)
    W = range(w0, int(math.floor(np.percentile(lo, 15))) + 1)
    E = range(min(int(math.ceil(np.percentile(lo, 85))), e0), e0 + 1)
    # summed-area tables for fast box sums
    R = np.pad(region.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    Sm = np.pad(sea.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    lat_idx = lambda v: int(round((grid.lats[0] - v) / grid.dlat))  # north-first rows
    lon_idx = lambda v: int(round((v - grid.lons[0]) / grid.dlat))
    total = region.sum()
    best = None
    for s in S:
        for n in N:
            if n <= s:
                continue
            r0, r1 = max(lat_idx(n), 0), min(lat_idx(s), region.shape[0] - 1) + 1
            for w in W:
                for e in E:
                    if e <= w:
                        continue
                    c0, c1 = max(lon_idx(w), 0), min(lon_idx(e), region.shape[1] - 1) + 1
                    rin = R[r1, c1] - R[r0, c1] - R[r1, c0] + R[r0, c0]
                    sin = Sm[r1, c1] - Sm[r0, c1] - Sm[r1, c0] + Sm[r0, c0]
                    if sin == 0:
                        continue
                    catch, extra = rin / total, (sin - rin) / sin
                    sc = catch - rules.extra_weight * extra
                    if best is None or sc > best[0]:
                        best = (sc, catch, extra, s, n, w, e, (r0, r1, c0, c1))
    sc, catch, extra, s, n, w, e, (r0, r1, c0, c1) = best
    mask = np.zeros_like(region)
    mask[r0:r1, c0:c1] = True
    text = "FROM %s TO %s BETWEEN %s AND %s" % (lat_txt(s), lat_txt(n), lon_txt(e), lon_txt(w))
    return dict(kind="box", text=text, score=sc, catch=catch, extra=extra, mask=mask & sea)


# ---------------------------------------------------------------- 2. quadrants / semicircles
def _ang_mask(b, center, half):
    d = (b - center + 540) % 360 - 180
    return np.abs(d) <= half + 1e-6


def _group_text(radius, dirs, semi):
    names = [DIR8[i] for i in dirs]
    word = ("SEMICIRCLE" if semi else "QUADRANT") + ("S" if len(names) > 1 else "")
    if len(names) == 1:
        return "%d NM %s %s" % (radius, names[0], word), word
    return "%d NM %s AND %s %s" % (radius, "...".join(names[:-1]) if len(names) > 2 else names[0], names[-1], word), word


def best_radial(region, sea, grid, low, rules):
    d, b = grid.dist_bearing(low[0], low[1])
    if d[region].min() > rules.attach_nm:
        return None
    shapes = []
    for c in range(8):
        for ln in (1, 2, 3):           # runs of quadrants: N / N AND NE / N...NE AND E
            dirs = [(c + k) % 8 for k in range(ln)]
            ang = np.zeros_like(region)
            for k in dirs:
                ang |= _ang_mask(b, k * 45, 45)
            shapes.append((dirs, False, ang))
        shapes.append(([c], True, _ang_mask(b, c * 45, 90)))
    shapes.append(([], None, np.ones_like(region)))   # WITHIN X NM OF THE LOW (circle)
    radii = np.arange(60, 1501, 60)
    cands = []
    for dirs, semi, ang in shapes:
        for r in radii:
            m = ang & (d <= r)
            sc, catch, extra = score(m, region, sea, rules.extra_weight)
            cands.append((sc, catch, extra, r, dirs, semi, m))
    cands.sort(key=lambda t: -t[0])
    best = cands[0]
    # try adding a second radius group ("WITHIN 420 NM SE AND 300 NM E QUADRANTS")
    two = None
    for c2 in cands[:400]:
        if c2[4] == best[4] and c2[5] == best[5]:
            continue
        if c2[5] is None or best[5] is None or set(c2[4]) & set(best[4]):
            continue
        m = best[6] | c2[6]
        sc, catch, extra = score(m, region, sea, rules.extra_weight)
        if two is None or sc > two[0]:
            two = (sc, catch, extra, m, c2)
    if two and two[0] > best[0] + 0.03:
        g1, w1 = _group_text(best[3], best[4], best[5])
        g2, w2 = _group_text(two[4][3], two[4][4], two[4][5])
        if w1.rstrip("S") == w2.rstrip("S"):   # same kind: "WITHIN 420 NM SE AND 300 NM E QUADRANTS"
            text = "WITHIN %s AND %s" % (g1.rsplit(" ", 1)[0], g2.rsplit(" ", 1)[0] + " " + w1.rstrip("S") + "S")
        else:
            text = "WITHIN %s AND %s" % (g1, g2)
        return dict(kind="radial2", text=text, score=two[0], catch=two[1], extra=two[2], mask=two[3] & sea)
    sc, catch, extra, r, dirs, semi, m = best
    if semi is None:
        text = "WITHIN %d NM OF CENTER" % r
    else:
        text = "WITHIN " + _group_text(r, dirs, semi)[0]
    return dict(kind="radial", text=text, score=sc, catch=catch, extra=extra, mask=m & sea)


# ---------------------------------------------------------------- 3. within X nm of a line
def best_line(region, sea, grid, rules):
    ys, xs = np.nonzero(region)
    if ys.size < 6:            # a few pixels: a box says it better
        return None
    la, lo = grid.lats[ys], grid.lons[xs]
    k = math.cos(math.radians(la.mean()))
    X = np.c_[(lo - lo.mean()) * k, la - la.mean()]
    u, s, vt = np.linalg.svd(X, full_matrices=False)
    t = X @ vt[0]
    if s[0] < 2.0 * s[1]:      # not elongated: a line won't help
        return None
    pts = []
    for q in (2, 50, 98):
        sel = np.abs(t - np.percentile(t, q)) <= (t.max() - t.min()) * 0.08
        if not sel.any():
            sel = np.argsort(np.abs(t - np.percentile(t, q)))[:5]
        pts.append((round(la[sel].mean()), round(lo[sel].mean())))
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    if len(pts) < 2:
        return None
    # distance from every cell to the polyline (densified)
    dense = []
    for (a0, b0), (a1, b1) in zip(pts[:-1], pts[1:]):
        for f in np.linspace(0, 1, 30):
            dense.append((a0 + (a1 - a0) * f, b0 + (b1 - b0) * f))
    # nearest line pixel by a local flat-earth distance transform, then the great-circle
    # distance to that pixel (much faster than one full-grid distance per line point)
    on = np.zeros(region.shape, bool)
    for a, b in dense:
        iy = int(round((grid.lats[0] - a) / grid.dlat))
        ix = int(round((b - grid.lons[0]) / grid.dlat))
        if 0 <= iy < on.shape[0] and 0 <= ix < on.shape[1]:
            on[iy, ix] = True
    if not on.any():
        return None
    _, (iy, ix) = ndimage.distance_transform_edt(~on, sampling=(1.0, k), return_indices=True)
    p1, p2 = np.radians(grid.LAT), np.radians(grid.lats[iy])
    dl = np.radians(grid.LON - grid.lons[ix])
    a_ = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    dmin = 2 * R_NM * np.arcsin(np.sqrt(np.clip(a_, 0, 1)))
    best = None
    for r in np.arange(60, 601, 60):
        m = dmin <= r
        sc, catch, extra = score(m, region, sea, rules.extra_weight)
        if best is None or sc > best[0]:
            best = (sc, catch, extra, r, m)
    sc, catch, extra, r, m = best
    text = "WITHIN %d NM OF A LINE FROM %s" % (r, " TO ".join(ll_txt(a, b) for a, b in pts))
    return dict(kind="line", text=text, score=sc, catch=catch, extra=extra, mask=m & sea)


CENTER_NAMES = ["MAIN CENTER", "SECOND CENTER", "THIRD CENTER", "FOURTH CENTER"]


def describe(region, sea, grid, lows, rules):
    """Pick the phrase for one region, box first. With several centers (a complex low) a
    quadrant phrase names its center: '... QUADRANT OF SECOND CENTER'."""
    box_c = best_box(region, sea, grid, rules)
    others = []
    for i, low in enumerate(lows):
        r = best_radial(region, sea, grid, low, rules)
        if r:
            if len(lows) > 1:
                r["text"] += " OF " + CENTER_NAMES[min(i, 3)]
            r["low"] = low
            others.append(r)
    ln = best_line(region, sea, grid, rules)
    if ln:
        others.append(ln)
    best = box_c
    for o in others:
        if o["score"] > best["score"] + (rules.box_margin if best is box_c else 0):
            best = o
    best["box"] = box_c
    return best


def describe_parts(region, sea, grid, lows, rules, max_parts=2):
    """Describe a level as one shape, or as up to three separate shapes joined with '...AND'
    when its pieces lie apart (two separate gale areas around one low)."""
    one = describe(region, sea, grid, lows, rules)
    lab, n = ndimage.label(region, structure=np.ones((3, 3)))
    if n < 2:
        return one
    sizes = ndimage.sum(region, lab, range(1, n + 1))
    order = np.argsort(sizes)[::-1][:max_parts]
    # only pieces that hold a real share of the level get their own phrase
    parts = [describe(lab == (i + 1), sea, grid, lows, rules) for i in order
             if sizes[i] >= max(rules.min_cells, 0.15 * region.sum())]
    if len(parts) < 2:
        return one
    m = np.zeros_like(region)
    for p in parts:
        m |= p["mask"]
    sc, catch, extra = score(m, region, sea, rules.extra_weight)
    if sc <= one["score"] + 0.05:
        return one
    return dict(kind="+".join(p["kind"] for p in parts), text="...AND ".join(p["text"] for p in parts),
                score=sc, catch=catch, extra=extra, mask=m & sea)


# ---------------------------------------------------------------- ranges
LO_FOR_HI = {25: 15, 30: 20, 35: 25, 40: 25, 45: 30, 50: 35, 55: 40, 60: 45, 65: 50, 70: 55, 75: 60, 80: 65, 85: 70}


def wind_range(vals, rules, top_level=None):
    """Top of the range from the grid peak (rounded to 5 kt by rules.hi_round), bottom from the
    desk's usual pairing (25 TO 35, 25 TO 40, 30 TO 45, 35 TO 50, 40 TO 55, 50 TO 65 ...)."""
    peak = (vals.max() if rules.hi_from == "max" else np.percentile(vals, rules.hi_pct)) + rules.hi_add
    hi = int(5 * (math.ceil(peak / 5.0) if rules.hi_round == "up" else round(peak / 5.0)))
    hi = min(max(hi, 25), 85)
    return LO_FOR_HI[hi], hi


def seas_range(vals):
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None
    hi = math.ceil(np.percentile(vals, 99) * 2) / 2
    lo = max(2.5, math.floor(np.percentile(vals, 10) * 2) / 2)
    if hi <= lo:
        return (None, hi)
    return (lo, hi)


def fmt_wind(r):
    return "WINDS %d TO %d KT." % r


def seas_peak(hs, mask):
    """(lat, lon, m) of the highest seas inside mask, or None."""
    v = np.where(mask & np.isfinite(hs), hs, -np.inf)
    i = np.unravel_index(np.argmax(v), v.shape)
    return None if not np.isfinite(v[i]) else (i, float(v[i]))


def fmt_seas(r, at=None, ratio=2.0):
    """' SEAS 3 TO 8 M...HIGHEST NEAR 35N175W.': the desk names where the seas peak when the
    range is wide (issued 2025-26: on 65% of ranges over 2.5x, 40% at 2-2.5x, 11% at 2x);
    Jason 10-30: whenever the high is more than double the low."""
    if r is None:
        return ""
    lo, hi = r
    f = lambda v: ("%g" % v)
    if lo is None:
        return " SEAS TO %s M." % f(hi)
    near = "...HIGHEST NEAR %s" % ll_txt(at[0], at[1]) if at and hi > ratio * lo else ""
    return " SEAS %s TO %s M%s." % (f(lo), f(hi), near)


# ---------------------------------------------------------------- one valid time
@dataclass
class Tier:
    level: int
    phrase: dict
    wind: tuple
    seas: tuple | None
    mask: np.ndarray = field(repr=False)
    seas_at: tuple | None = None   # (lat, lon, m) of the highest seas in the tier


def regions_at(wind, sea, thr, rules):
    lab, n = ndimage.label((wind >= thr) & sea, structure=np.ones((3, 3)))
    out = []
    for k in range(1, n + 1):
        m = lab == k
        if m.sum() >= rules.min_cells:
            out.append(m)
    return out


def clean(mask, sea, rules, min_cells=None):
    """Smooth a level mask the way a forecaster would draw it: close small gaps, drop specks."""
    min_cells = rules.min_cells if min_cells is None else min_cells
    m = ndimage.binary_closing(mask, structure=np.ones((5, 5)), iterations=1) & sea
    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    if n == 0:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    keep = np.isin(lab, [i + 1 for i, s_ in enumerate(sizes) if s_ >= min_cells])
    return keep


def areas_for_time(wind, hs, sea, grid, lows, rules=Rules()):
    """lows: list of (lat, lon, mb, motion, id). Returns list of dict(low, tiers[Tier], top, region).
    Each low owns the wind regions closest to it (within attach_nm); regions with no low near
    stand alone. Per system, at most three tiers: the top level core, the next level down
    (only under a storm or hurricane-force core), then everything at outer_kt and up (ELSEWHERE)."""
    outer = regions_at(wind, sea, rules.outer_kt, rules)
    # complex lows: lows that touch the same wind area and lie within complex_nm of each other
    dists = [grid.dist_bearing(l[0], l[1])[0] for l in lows]
    parent = list(range(len(lows)))
    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for reg in outer:
        touch = [i for i in range(len(lows)) if dists[i][reg].min() <= rules.share_nm]
        for i in touch:
            for j in touch:
                if i < j and grid_dist(lows[i][0], lows[i][1], lows[j][0], lows[j][1]) <= rules.complex_nm:
                    parent[root(j)] = root(i)
    groups = {}
    for i in range(len(lows)):
        groups.setdefault(root(i), []).append(i)
    # every wind cell goes to its nearest low (within attach_nm); a complex low takes the cells
    # of all its centres. Cells with no low near form stand-alone areas.
    owned = {}
    allw = np.zeros_like(sea)
    for reg in outer:
        allw |= reg
    if lows:
        D = np.stack(dists)
        near_i = D.argmin(0)
        near_d = D.min(0)
        for r_ in set(root(i) for i in range(len(lows))):
            idx = [i for i in range(len(lows)) if root(i) == r_]
            reg = allw & np.isin(near_i, idx) & (near_d <= rules.attach_nm)
            if reg.sum() >= rules.min_cells:
                owned[("g", r_)] = [sorted((lows[k] for k in idx), key=lambda l: l[2]), reg]
        rest = allw & (near_d > rules.attach_nm)
    else:
        rest = allw
    # stand-alone areas within about a degree of each other form one paragraph
    lab, n = ndimage.label(ndimage.binary_dilation(rest, iterations=4), structure=np.ones((3, 3)))
    for k in range(1, n + 1):
        reg = rest & (lab == k)
        if reg.sum() >= rules.min_cells:
            owned[("free", k)] = [[], reg]
    systems = []
    for key, (members, reg) in owned.items():
        low = members[0] if members else None
        top = max([0] + [lv for lv in rules.levels if clean(reg & (wind >= lv), sea, rules, rules.core_min_cells).any()])
        levels = [lv for lv in sorted(rules.levels, reverse=True) if lv <= top]
        levels = levels[:2] if top >= 48 else levels[:1]
        levels = [lv for lv in levels] + [rules.outer_kt]
        tiers, done = [], np.zeros_like(reg)
        upper = None
        for lv in levels:
            core = lv in rules.levels
            off = rules.draw_offset if isinstance(rules.draw_offset, (int, float)) else rules.draw_offset.get(lv, 0.0)
            thr = lv - off if core else lv
            sub = clean(reg & (wind >= thr), sea, rules, rules.core_min_cells if core else None)
            if sub.sum() < (rules.core_min_cells if core else rules.min_cells):
                continue
            ph = describe_parts(sub, sea, grid, members[:1], rules)
            new = ph["mask"] & ~done
            if tiers and new.sum() < 0.15 * ph["mask"].sum():
                continue   # same shape as the tier above: nothing new to say
            src = sub & ~done
            if upper is not None:
                src &= wind < upper
            if not src.any():
                src = sub
            wr = wind_range(wind[src], rules)
            # each tier tops out at its own category: warning-level winds sit in their own core,
            # lesser winds get a lower range (gale tier 45, the outer tier 30)
            cap = min(85 if lv >= 64 else 60 if lv >= 48 else 45 if lv >= 34 else 30,
                      {0: 30, 34: 45, 48: 60}.get(top, 85))
            if wr[1] > cap:
                wr = (LO_FOR_HI[cap], cap)
            sm = (new if new.any() else ph["mask"]) & sea
            tiers.append(Tier(lv, ph, wr, seas_range(hs[sm]), ph["mask"], _peak_at(hs, sm, grid)))
            done |= ph["mask"]
            upper = thr
        tiers = absorb_small_core(tiers, hs, sea, grid, members[:1], rules)
        if tiers:
            systems.append(dict(low=low, lows=members, tiers=tiers, top=top, region=reg))
    return systems


def _peak_at(hs, mask, grid):
    pk = seas_peak(hs, mask)
    return None if pk is None else (float(grid.lats[pk[0][0]]), float(grid.lons[pk[0][1]]), pk[1])


def absorb_small_core(tiers, hs, sea, grid, lows, rules):
    """A gale core much smaller than the sub-gale area round it is written as one area with the
    wider range ('FROM 54N TO 61N BETWEEN 144W AND 151W WINDS 25 TO 40 KT'), as the desk would,
    not as a separate small box beside the big one (Jason 10-30, 00Z 30 Oct Gulf of Alaska +6 h).
    The paragraph keeps its gale warning heading."""
    if len(tiers) < 2:
        return tiers
    core, outer = tiers[-2], tiers[-1]
    if core.level != 34 or outer.level != rules.outer_kt or core.mask.sum() >= min(rules.absorb_share * outer.mask.sum(), rules.absorb_cells):
        return tiers
    region = core.mask | outer.mask
    # the outer area's own shape when it already holds the core, else one shape round both
    ph = outer.phrase if not (core.mask & ~outer.mask).any() else describe_parts(region, sea, grid, lows, rules)
    hi = core.wind[1]
    upper = tiers[-3].mask if len(tiers) > 2 else np.zeros_like(region)
    sm = ph["mask"] & sea & ~upper
    if not sm.any():
        sm = ph["mask"] & sea
    merged = Tier(rules.outer_kt, ph, (LO_FOR_HI[hi], hi), seas_range(hs[sm]), ph["mask"], _peak_at(hs, sm, grid))
    return tiers[:-2] + [merged]


WARN = {64: "HURRICANE FORCE WIND WARNING", 48: "STORM WARNING", 34: "GALE WARNING", 0: ""}


def time_text(sysd, hour, lead_word=None, ratio=2.0):
    """One paragraph: '.24 HOUR FORECAST LOW 56N149W 983 MB. WITHIN ... WINDS .. SEAS ..'"""
    head = "" if hour == 0 else "%d HOUR FORECAST " % hour
    low = sysd["low"]
    lows = sysd.get("lows") or ([low] if low else [])
    lw = lead_word + " " if lead_word else ""
    if len(lows) > 1:
        head += "%sCOMPLEX LOW WITH MAIN CENTER %s %d MB%s." % (lw, ll_txt(lows[0][0], lows[0][1]), lows[0][2],
                                                             " " + lows[0][3] if len(lows[0]) > 3 and lows[0][3] else "")
    elif low:
        head += "%sLOW %s %d MB." % (lw, ll_txt(low[0], low[1]), low[2])
        if len(low) > 3 and low[3]:
            head = head[:-1] + " " + low[3] + "."
    if sysd.get("note"):
        head += " " + sysd["note"]
    # areas with the same wind range share one sentence: "FROM ... AND FROM ... WINDS 20 TO 30 KT."
    groups = []
    for t in sysd["tiers"]:
        if groups and tuple(groups[-1][0].wind) == tuple(t.wind):
            groups[-1].append(t)
        else:
            groups.append([t])
    parts = []
    for i, g in enumerate(groups):
        last = groups[-1][0]
        pre = "" if i == 0 else ("ELSEWHERE " if g[0].level == last.level and i == len(groups) - 1 else "ALSO ")
        seas = [t.seas for t in g if t.seas]
        if seas:
            seas = (None if any(x[0] is None for x in seas) else min(x[0] for x in seas), max(x[1] for x in seas))
        else:
            seas = None
        pk = [t.seas_at for t in g if t.seas_at]
        at = max(pk, key=lambda p: p[2]) if pk else None
        parts.append("%s%s %s%s" % (pre, "...AND ".join(t.phrase["text"] for t in g), fmt_wind(g[0].wind),
                                     fmt_seas(seas, at, ratio)))
    return "." + " ".join(x for x in (head.strip(), " ".join(parts)) if x)


# ---------------------------------------------------------------- lows and tracks
def find_lows(msl, sea_or_all, grid, max_mb=1012.0, win=13, depth=2.0):
    """Local MSLP minima (lat, lon, mb): lowest in a ~3 deg window and `depth` hPa below its
    ~5 deg surroundings."""
    mn = ndimage.minimum_filter(msl, size=win, mode="nearest")
    big = ndimage.uniform_filter(msl, size=41, mode="nearest")
    ys, xs = np.nonzero((msl == mn) & (msl <= max_mb) & (big - msl >= depth))
    out = []
    for y, x in zip(ys, xs):
        out.append((float(round(grid.lats[y])), float(round(grid.lons[x])), int(round(msl[y, x])), grid.lats[y], grid.lons[x]))
    out.sort(key=lambda t: t[2])
    keep = []
    for o in out:   # one centre per 300 nm
        if all(grid_dist(o[3], o[4], k[3], k[4]) > 300 for k in keep):
            keep.append(o)
    return keep


def grid_dist(la1, lo1, la2, lo2):
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(min(1, a)))


def bearing(la1, lo1, la2, lo2):
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def link_tracks(lows_by_hour, max_kt=70.0):
    """lows_by_hour: {hour: [low,...]} at any steps -> {hour: [(track_id, low), ...]}. A low links
    to the nearest unclaimed low of the previous step within max_kt x the step length."""
    out, nid, prev, ph = {}, 0, [], None
    for h in sorted(lows_by_hour):
        max_nm = max_kt * (h - ph if ph is not None else 6)
        ph = h
        cur = []
        used = set()
        for lw in lows_by_hour[h]:
            best = None
            for tid, pl in prev:
                if tid in used:
                    continue
                d = grid_dist(lw[3], lw[4], pl[3], pl[4])
                if d <= max_nm and (best is None or d < best[0]):
                    best = (d, tid)
            if best:
                tid = best[1]
            else:
                tid, nid = nid, nid + 1
            used.add(tid)
            cur.append((tid, lw))
        out[h] = cur
        prev = cur
    return out


def motion(track_now, track_next, hours=6):
    if track_next is None:
        return "STATIONARY"
    d = grid_dist(track_now[3], track_now[4], track_next[3], track_next[4])
    kt = d / hours
    if kt < 3:
        return "NEARLY STATIONARY"
    b = bearing(track_now[3], track_now[4], track_next[3], track_next[4])
    return "MOVING %s %d KT" % (DIR8[int((b + 22.5) // 45) % 8], 5 * round(kt / 5) or 5)


# ---------------------------------------------------------------- whole product
def write_product(fields, grid, sea, rules=Rules(), hours=None):
    """fields: {hour: dict(wind, hs, msl)} from the synopsis (hour 0) to 48, at 6 or 12 h steps
    (0, 24 and 48 must be there). Returns (warnings_text, synopsis_text, debug)."""
    hours = sorted(fields) if hours is None else sorted(hours)
    nxt_h = {a: b for a, b in zip(hours[:-1], hours[1:])}
    prv_h = {b: a for a, b in zip(hours[:-1], hours[1:])}
    near = ndimage.binary_dilation(sea, iterations=int(rules.area_buffer_deg * 4))
    lows = {}
    for h in hours:
        if h in fields:
            lows[h] = [l for l in find_lows(fields[h]["msl"], sea, grid)
                       if near[int(round((grid.lats[0] - l[3]) * 4)), int(round((l[4] - grid.lons[0]) * 4))]]
    tracks = link_tracks(lows)
    per = {}          # system id (first track id, or 'free<n>') -> {hour: system}
    free = 0
    sys_of_tid = {}
    for h in lows:
        tl = tracks[h]
        lowlist = []
        nxt = {t: l for t, l in tracks.get(nxt_h.get(h), [])}
        for tid, lw in tl:
            lowlist.append((lw[0], lw[1], lw[2], motion(lw, nxt.get(tid), nxt_h.get(h, 6) - h) if h == 0 else None, tid))
        systems = areas_for_time(fields[h]["wind"], fields[h]["hs"], sea, grid, [l for l in lowlist], rules)
        # merge several regions owned by the same low into one system entry
        for s in systems:
            if s["low"]:
                key = None
                for m in s["lows"]:
                    if m[4] in sys_of_tid:
                        key = sys_of_tid[m[4]]
                        break
                if key is None:
                    key = s["low"][4]
                for m in s["lows"]:
                    sys_of_tid[m[4]] = key
            else:
                # free areas: link to a free area at the previous time that overlaps
                key = None
                for k, v in per.items():
                    if str(k).startswith("free") and prv_h.get(h) in v and (v[prv_h[h]]["region"] & s["region"]).sum() > 0:
                        key = k
                if key is None:
                    key, free = "free%d" % free, free + 1
            ent = per.setdefault(key, {})
            if h in ent:
                ent[h]["tiers"] += s["tiers"]
                ent[h]["top"] = max(ent[h]["top"], s["top"])
                ent[h]["region"] |= s["region"]
                ent[h]["lows"] = sorted({m[4]: m for m in ent[h]["lows"] + s["lows"]}.values(), key=lambda l: l[2])
            else:
                ent[h] = s
    # choose times: synopsis, 24, 48, plus 6-hourly steps where the level goes up
    paras, pieces = {}, []
    for key, ent in per.items():
        # synopsis, 24 and 48 h; add an in-between step only where the warning category goes up
        # (none to gale, gale to storm, storm to hurricane force; Jason 10-17): the first step at
        # each higher category, if it holds for the next step or peaks in between
        cat = {h: (ent[h]["top"] if h in ent else 0) for h in hours}
        shown, out = [0, 24, 48], []
        for a_, b_ in ((0, 24), (24, 48)):
            now = cat[a_]
            for h in [x for x in hours if a_ < x < b_]:
                if cat[h] >= 34 and cat[h] > now and (cat.get(nxt_h.get(h), 0) >= cat[h] or cat[h] > cat[b_]):
                    shown.append(h)
                    now = cat[h]
        shown.sort()
        top = max(cat.get(h, 0) for h in shown)   # the heading follows the times the text shows
        first_seen = min(ent)
        prev_present = False
        prev_n = None
        for h in shown:
            if h in ent and ent[h]["tiers"]:
                lead = "NEW" if (h > 0 and h == first_seen) else None
                n_now = len(ent[h].get("lows") or [])
                prev_n = n_now
                out.append(time_text(ent[h], h, lead, rules.seas_peak_ratio))
                pieces.append(dict(key=key, hour=h, text=out[-1], top=top, tiers=ent[h]["tiers"], low=ent[h]["low"]))
                prev_present = True
            elif prev_present:
                gone = h not in ent
                low_alive = any(sys_of_tid.get(tid) == key for tid, _ in tracks.get(h, []))
                if not ent.get(h) and low_alive:
                    out.append(".%d HOUR FORECAST CONDITIONS DIMINISHED." % h)
                    pieces.append(dict(key=key, hour=h, text=out[-1], top=top, tiers=[], low=None))
                elif ent.get(h) is None and isinstance(key, int) and not low_alive:
                    # absorbed: the system's last centre ends up within complex_nm of another low
                    last_h = max(x for x in ent if x < h)
                    last = ent[last_h]["low"]
                    absorbed = last and any(grid_dist(last[0], last[1], l[3], l[4]) <= rules.complex_nm
                                            for _, l in tracks.get(h, []))
                    out.append(".%d HOUR FORECAST LOW %s." % (h, "ABSORBED" if absorbed else "DISSIPATED"))
                    pieces.append(dict(key=key, hour=h, text=out[-1], top=top, tiers=[], low=None))
                else:
                    out.append(".%d HOUR FORECAST CONDITIONS DIMINISHED." % h)
                    pieces.append(dict(key=key, hour=h, text=out[-1], top=top, tiers=[], low=None))
                prev_present = False
                break
        if out:
            paras[key] = (top, out)
    warn = []
    for lv in (64, 48, 34):
        for key, (top, out) in sorted(paras.items(), key=lambda kv: str(kv[0])):
            if top == lv:
                warn.append("...%s...\n" % WARN[lv] + "\n".join(out))
    syn = [("\n".join(out)) for key, (top, out) in paras.items() if top < 34]
    return "\n\n".join(warn), "\n\n".join(syn), dict(per=per, tracks=tracks, pieces=pieces)
