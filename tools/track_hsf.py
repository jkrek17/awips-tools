#!/usr/bin/env python3
"""Attribute parsed High Seas Forecast lows to archive events, walking backwards.

Stage 3 of the pre-hurricane-force backfill. Reads

    data/hf_lows/HF_Data_-_Atl.csv, HF_Data_-_Pac.csv   the human archive
    data/hf_lows/hsf_lows.csv                           tools/parse_hsf.py output

and writes

    data/hf_lows/precursors.csv
        basin,event_id,valid,lat,lon,pres,warn_cat,source,match_nm,conf

One row per recovered fix in the 72 h before an event's first hurricane-force
(HF) fix. Stage 4 (tools/build_hf_lows.py) attaches them as a separate series;
the archive itself is never altered.

THE ONE RULE.  A missing precursor costs one event out of ~1,900. A wrong one
puts a fabricated pressure fall under a forecaster's name on a public NOAA
page. Every choice below resolves toward emitting nothing. A short honest
track beats a long invented one, and the lowest confidence grade is refused by
the build, so "low" is a label for rows we do not stand behind.

HOW IT WORKS.  For each event, a Viterbi (dynamic programming) search over 13
six-hourly slots from t0-72 h to t0, where t0 is the event's first HF fix.

  * The state at t0 is PINNED to the archive's own first HF fix: observed, not
    chosen. In production every other archive fix inside the window is pinned
    too (the archive is a known-good backbone; the build refuses a recovered
    row at a time the archive already has a fix anyway).
  * The states at earlier slots are the parsed analysis lows at that valid
    time in that basin. A single "missing" slot may be bridged (12 h step),
    and two consecutive missing slots END the track: the storm is lost, and
    anything beyond is a guess. The search is arranged so that a lost track
    costs the same flat price per remaining slot as a gap, so it cannot be
    pulled into a long guess by evidence beyond the point it would stop.
  * Truncation, not interpolation. No fix is ever invented between two others.
  * The archive's first two HF fixes give the storm's heading at t0; the first
    backward step must continue it.

WHAT TO KNOW BEFORE TRUSTING A ROW (measured by --validate; numbers in the report):
  * `conf` is graded on the PREFIX of the track from t0 to that fix, so a track
    whose far end is shaky still keeps its trustworthy near end. "high" needs
    every slot matched, no gap, every step in the low band, a verified anchor
    (a parsed low within 100 nm of the archive's fix at t0), a heading seed (two
    HF fixes), no ambiguity, and a printed pressure. Unverified or unseeded
    tracks cannot be better than "medium". Measured against the archive's own
    pre-HF analysis, "high" is far more reliable than "medium".
  * A step that costs more than a gap ends the track (see solve()). An earlier
    version let the search buy one dreadful link with the credit of a long
    pleasant chain beyond it; it then bridged over good candidates near the
    anchor. That, and widening the heading band for HSF's whole-degree
    positions, are the two structural changes made after the first V1 run.
    No weight was fitted to V1; the three derived constants follow stated rules
    from the archive's own step-cost table.
  * Pressure continuity is symmetric by design, so the search does not prefer
    deepening, and its scale is calibrated on the pre-HF regime (see the weights
    block). Even so, storms that fell >= 16 hPa into their first HF fix are
    recovered about half as often (50%) as the rest (~72%): the missing-slot
    price caps what a single step may cost. The recovered subset still
    under-represents the fastest deepeners.
  * Events whose first HF fix, or (in production) an archive lead fix, is a
    suspected mistyped position (archive_position_suspects) are not tracked.
  * Chains of ROWS in precursors.csv have holes where the archive owns a slot,
    which happens only in the 2017+ lead-fix era. For an era-neutral coverage
    measure use --chain-out (tracker alone, archive pre-HF fixes ignored).
  * `warn_cat` is the header the product filed the low under, which for a
    developing storm is the warning for what it WILL become: a 1008 hPa low can
    carry HF. It is not an observation of hurricane-force winds at that time.
  * Tropical and post-tropical systems are not in the parsed input, so
    extratropical-transition events recover little or nothing.

COST TERMS (all in one unit; every constant says which archive statistic it
came from. `python3 tools/track_hsf.py --calibrate` recomputes them):
  speed, heading, pressure, reported motion, and the flat missing-slot price.
The pressure term is SYMMETRIC in sign, on purpose - see pressure_cost().

Usage:
    python3 tools/track_hsf.py                     # -> data/hf_lows/precursors.csv
    python3 tools/track_hsf.py --event atl:2006200718          # one track, as a table
    python3 tools/track_hsf.py --calibrate         # re-derive the weights' sources
    python3 tools/track_hsf.py --validate          # V1, V1b, V2, coverage, dumps, build check
    python3 tools/track_hsf.py --chain-out F --archive-qc-out G   # sidecars: recovered-only chain
                                                   # hours per event; suspected archive position errors
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build_hf_lows as B                                   # noqa: E402

LOWS_CSV = os.path.join(ROOT, "data", "hf_lows", "hsf_lows.csv")
OUT_CSV = os.path.join(ROOT, "data", "hf_lows", "precursors.csv")
COLUMNS = ["basin", "event_id", "valid", "lat", "lon", "pres", "warn_cat",
           "source", "match_nm", "conf"]

STEP_H = 6
SLOTS = B.BACKFILL_WINDOW_H // STEP_H          # 12 slots behind t0 (t0 is slot 0)
PIL_BASIN = {"HSFAT1": "atl", "HSFEP1": "pac", "HSFEPI": "pac"}

# ---------------------------------------------------------------------------
# Weights. Every number is either an archive statistic or derived from one.
# Speed, heading and the missing-slot price come from the archive's HF-category
# fixes (6-hourly HF -> HF steps, 3,770 of them), so the pre-HF fixes used to
# validate the tracker (V1) have no say in them.
#
#   archive HF->HF 6-h steps        p50    p75    p90    p95    p99
#     translation speed, kt         24.5   33.5   42.3   49.1   88.7 (tail = errors)
#     heading change, deg           12.3   22.4   37.9   52.4   (steps >= 20 kt)
#   HSF reported motion vs the archive's next-6h motion, 2,936 matched lows:
#     vector difference, kt         10.5   15.8   21.4   25.9   43.4
#
# THE PRESSURE TERM IS CALIBRATED ON THE PRE-HF REGIME, NOT THE MATURE ONE.
# The first version took its scale from HF -> HF steps (|dp| p90 = 8 hPa), but
# the tracker works in the DEEPENING phase before HF onset, where a 6-h fall of
# 16 hPa is a 1-in-18 event against 1-in-100 in the mature segment. That made
# the cost ~5x too steep exactly where it has to follow the deepening, and
# recall for storms that fell >= 16 hPa into onset was 16%, against ~72% for the
# rest. Sample used: the 1,216 archive 6-h steps whose later fix is at or before
# the event's first HF fix (any category):
#
#   6-h pressure change, hPa            n     p1    p5   p10  median  min
#     HF -> HF (mature)               3,617  -15   -10   -8     -1    -23
#     pre-HF (the regime tracked)     1,216  -20   -16  -14     -7    -31
#   |dp|, pre-HF:  p50 7  p90 14  p95 16  p99 21  max 31
#
# The scale is the p90 of |dp| (14 hPa), the same rule as before applied to the
# right sample, and the hard reject moves to 33 hPa because the observed pre-HF
# extreme is 31 and a real step must not be rejected as impossible. The term is
# still SYMMETRIC in sign (see pressure_cost); the sample was the problem, not
# the symmetry. Two caveats, stated so nobody has to find them: (1) the pre-HF
# sample comes from the 2017+ lead fixes, a selected set - storms someone was
# watching closely, so biased toward rapid deepeners. For a TOLERANCE that bias
# is the conservative direction (it makes the gate more permissive, not less),
# which is why it is still the right sample. (2) It is the same set of archive
# fixes V1 scores against. Only one scalar (a marginal quantile of |dp|) is
# taken from it, but V1's pressure tolerance is therefore not independent of its
# truth; V1b (mature-phase HF fixes) is the check that is not affected.
# Position and motion terms are unchanged: a wrong storm is wrong in position,
# not in pressure, so the loosening is spent on pressure alone.
# ---------------------------------------------------------------------------

SPEED_HARD_KT = B.SPEED_IMPLAUSIBLE_KT         # 90: the build already calls this an error
SPEED_FREE_KT = 45.0                           # ~archive p93; free to here
SPEED_STEEP_KT = 65.0                          # ~the archive's fastest-leg p95 (68)
SPEED_BASE = 0.3                               # (v/40)^2 * 0.3: mild preference for the nearer low

HEADING_FREE_DEG = 40.0                        # archive p90 is 38
HEADING_SCALE_DEG = 30.0                       # cost 1 at 70 deg, 4 at 100, 21 at 180
HSF_POSITION_NOISE_NM = 30.0                   # whole-degree rounding, see heading_cost()
HEADING_FULL_WEIGHT_NM = 120.0                 # below 20 kt of motion a bearing is mostly rounding noise

PRES_SCALE_HPA = 14.0                          # p90 of |6-h dp| in the PRE-HF regime: cost 1 at p90, 0.25 at the median
PRES_HARD_HPA = 33.0                           # pre-HF extreme is 31; the contract said "about 25" for the mature regime
PRES_UNKNOWN_COST = 1.0                        # a low printed without a pressure: weaker evidence

MOTION_FREE_KT = 15.0                          # HSF motion vs archive motion: p75 is 15.8
MOTION_SCALE_KT = 10.0
MOTION_CAP = 4.0                               # a mistyped motion must not veto a good match on its own

# The three constants below come from --calibrate: the cost, under THIS cost
# function, of the archive's 2,281 genuine HF -> HF steps that have a step on
# either side (so the heading term applies):  p50 0.30  p75 0.76  p90 1.66
# p95 3.21  p97.5 5.70  p99 10.2.  The rule for each is fixed (p95, p90, p75)
# and the values are re-derived from the table whenever the cost function
# changes; they are not adjusted against any validation result. (Recalibrating
# the pressure term on the pre-HF regime shrank the pressure share of a true
# step's cost, so by the same rule these came DOWN: the position, motion and
# heading terms are held, and the budget they are allowed to spend is tighter.)
MISSING_COST = 3.2        # flat price of a missing slot = the p95 of a TRUE step's cost.
                          # A real candidate beats a gap iff it is no worse than 95% of
                          # genuine steps; the other 5% of real steps are traded for not
                          # accepting a poor match (p97.5 was judged too loose).
LOW_BAND_COST = 1.7       # "all transition costs in the low band": the p90 of a true step
AMBIGUITY_MARGIN = 0.8    # the p75 of a true step: if the runner-up explains the data
                          # within a typical step's worth of cost, the choice is a coin flip

ANCHOR_MATCH_NM = 100.0   # a parsed low within this of the anchor "verifies" it (V2 uses it too)
DUPLICATE_NM = 25.0       # two candidates this close with the same pressure are one low listed twice
COLLISION_NM = 150.0      # BACKFILL/TRACKER spec: cross-event collision radius

COMPASS = {"N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
           "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SW": 225.0,
           "WSW": 247.5, "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5}

INF = float("inf")


# ---------------------------------------------------------------------------
# Geometry and time
# ---------------------------------------------------------------------------

def bearing(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing, degrees clockwise from north."""
    dl = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def angle_diff(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def displacement_nm(lat1, lon1, lat2, lon2):
    """(east, north) nm from point 1 to point 2, dateline-safe."""
    dlon = ((lon2 - lon1 + 180.0) % 360.0) - 180.0
    mid = math.radians((lat1 + lat2) / 2.0)
    return dlon * 60.0 * math.cos(mid), (lat2 - lat1) * 60.0


def extrapolate(a, z, steps):
    """Position `steps` slots beyond a, continuing the motion z -> a (z is the
    node `steps_za` slots behind it in the walk, passed as (node, slots))."""
    node, n = z
    dx, dy = displacement_nm(node["lat"], node["lon"], a["lat"], a["lon"])
    k = steps / float(n)
    lat = a["lat"] + (dy * k) / 60.0
    lon = a["lon"] + (dx * k) / (60.0 * max(0.05, math.cos(math.radians(a["lat"]))))
    lat = max(-89.0, min(89.0, lat))
    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon


def stamp(dt):
    return dt.year * 1000000 + dt.month * 10000 + dt.day * 100 + dt.hour


def shift(t, hours):
    """YYYYMMDDHH shifted by `hours` (negative = earlier)."""
    return stamp(B.to_dt(t) + timedelta(hours=hours))


def iso(t):
    return B.to_dt(t).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def load_events():
    """The archive's events exactly as the build derives them, split ids and
    all. This runs the build's own reader, split rule and derive() rather than
    copying them: the id a precursors row carries must be the id the build
    uses, and a second copy of the split rule would drift."""
    qc = B.QC()
    lows = {}
    for key, label, rel, lon_range in B.BASINS:
        B.read_basin(os.path.join(ROOT, rel), key, label, lon_range, qc, lows)
    out = []
    for low in lows.values():
        if not low["fixes"]:
            continue
        for part in B.split_reused_ids(low, qc):
            B.derive(part, qc)
            out.append(part)
    out.sort(key=lambda l: (l["start"], l["basin"]))
    return out


def new_node(lat, lon, pres, vx=None, vy=None, cat="", pinned=False, src="hsf", section=""):
    return {"lat": lat, "lon": lon, "pres": pres, "vx": vx, "vy": vy, "cat": cat,
            "pinned": pinned, "src": src, "section": section}


def load_lows(path=LOWS_CSV):
    """{(basin, YYYYMMDDHH): [node, ...]} from tools/parse_hsf.py's CSV.

    Candidates the build would refuse as positions (wrong hemisphere, longitude
    outside the basin's usual range) are left out: they could not be emitted,
    and the build treats a doubtful position as a refusal, not a fix. A low the
    product lists twice (same place, same pressure) is kept once."""
    by_time = defaultdict(list)
    lon_ranges = {b[0]: (b[1], b[3]) for b in B.BASINS}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            basin = PIL_BASIN.get(r["pil"])
            if basin is None or not r["valid"]:
                continue
            v = r["valid"]
            t = int(v[0:4] + v[5:7] + v[8:10] + v[11:13])
            lat, lon = float(r["lat"]), float(r["lon"])
            label, lon_range = lon_ranges[basin]
            pos = B.normalize_position(str(lat), str(lon), label, lon_range)
            if not pos["ok"] or pos["detail"]:
                continue
            pres = float(r["pres"]) if r["pres"] else None
            vx = vy = None
            d = COMPASS.get(r["mot_dir"])
            if d is not None and r["mot_kt"]:
                kt = float(r["mot_kt"])
                vx, vy = kt * math.sin(math.radians(d)), kt * math.cos(math.radians(d))
            node = new_node(pos["lat"], pos["lon"], pres, vx, vy, r["warn_cat"], False, "hsf",
                            r["section"])
            group = by_time[(basin, t)]
            if any(B.great_circle_nm(g["lat"], g["lon"], node["lat"], node["lon"]) <= DUPLICATE_NM
                   and (g["pres"] == node["pres"] or None in (g["pres"], node["pres"]))
                   for g in group):
                continue
            group.append(node)
    return by_time


# ---------------------------------------------------------------------------
# Cost terms
# ---------------------------------------------------------------------------

def speed_cost(v_kt):
    """Near zero to ~45 kt, steep past ~65, forbidden at 90 (None)."""
    if v_kt >= SPEED_HARD_KT:
        return None
    return (SPEED_BASE * (v_kt / 40.0) ** 2
            + (max(0.0, v_kt - SPEED_FREE_KT) / 15.0) ** 2
            + (max(0.0, v_kt - SPEED_STEEP_KT) / 10.0) ** 2)


def pressure_cost(p_a, p_b, dt_h):
    """Cost of the pressure change between two consecutive lows; None = forbidden.

    SYMMETRIC IN SIGN, AND THAT IS THE POINT - DO NOT "FIX" IT. Only abs(p_a -
    p_b) is used. Physically one is tempted to expect pressure to RISE as the
    walk goes backwards in time (a storm is younger and shallower earlier), and
    to reward that. Do not. Among competing candidates such a term would pick
    whichever one makes the storm look like it deepened the most, so the
    deepening recovered from the backfill would be a statement about this
    cost function and not about the weather: the statistic would measure its
    own prior. A sign-blind magnitude penalty can only prefer a candidate for
    being CONSISTENT with the storm, never for making it look more explosive.
    tests/track_hsf checks that mirrored candidates (one deeper, one shallower
    by the same amount) cost exactly the same.
    """
    if p_a is None or p_b is None:
        return PRES_UNKNOWN_COST
    scale = math.sqrt(dt_h / float(STEP_H))
    dp = abs(p_a - p_b)
    if dp > PRES_HARD_HPA * scale:
        return None
    return (dp / (PRES_SCALE_HPA * scale)) ** 2


def motion_cost(a, b, dx, dy, dt_h):
    """Does the step b -> a agree with the motion the product PRINTED for the
    lows? The product states "MOVING NE 25 KT" for every low; the archive's
    own motion differs from it by 10.5 kt at the median (p95 26 kt), which is
    tight enough to expose a different storm. Uses the mean of whichever
    reported vectors exist; no vector, no cost."""
    vecs = [(n["vx"], n["vy"]) for n in (a, b) if n["vx"] is not None]
    if not vecs:
        return 0.0
    rx = sum(v[0] for v in vecs) / len(vecs)
    ry = sum(v[1] for v in vecs) / len(vecs)
    diff = math.hypot(dx / dt_h - rx, dy / dt_h - ry)
    return min(MOTION_CAP, (max(0.0, diff - MOTION_FREE_KT) / MOTION_SCALE_KT) ** 2)


def heading_cost(prev_bearing, prev_d6, bearing_now, d6_now):
    """Extratropical lows do not reverse course in 6 h. Weighted down when the
    storm is nearly stationary, where a bearing is rounding noise.

    HSF prints whole degrees, so a position is good to about 30 nm (a uniform
    half-degree error is 17 nm in latitude and less in longitude; two ends of
    a step add in quadrature). The archive's heading statistic (free band 40
    deg) came from steps of 120 nm or more with finely entered positions. For
    a short HSF step the same 30 nm swings the bearing by atan(30/d), so the
    free band is widened by that much: a 70 nm step gets 40+23 deg, a 200 nm
    step 40+9 deg."""
    if prev_bearing is None or bearing_now is None:
        return 0.0
    d_min = max(1.0, min(prev_d6, d6_now))
    w = min(1.0, d_min / HEADING_FULL_WEIGHT_NM)
    free = HEADING_FREE_DEG + math.degrees(math.atan2(HSF_POSITION_NOISE_NM, d_min))
    return w * (max(0.0, angle_diff(prev_bearing, bearing_now) - free)
                / HEADING_SCALE_DEG) ** 2


def edge_cost(a, b, dt_h):
    """Cost of the step from a (later) back to b (earlier), exclusive of the
    heading and the missing-slot price. None means a hard reject.
    Returns (cost, distance_nm, bearing_deg)."""
    if a["pinned"] and b["pinned"]:
        # Both ends are archive data; nothing here is ours to judge.
        d = B.great_circle_nm(a["lat"], a["lon"], b["lat"], b["lon"])
        return 0.0, d, bearing(a["lat"], a["lon"], b["lat"], b["lon"])
    d = B.great_circle_nm(a["lat"], a["lon"], b["lat"], b["lon"])
    sc = speed_cost(d / dt_h)
    if sc is None:
        return None
    pc = pressure_cost(a["pres"], b["pres"], dt_h)
    if pc is None:
        return None
    # b -> a is the FORWARD displacement, which is what a printed motion describes.
    dx, dy = displacement_nm(b["lat"], b["lon"], a["lat"], a["lon"])
    mc = motion_cost(a, b, dx, dy, dt_h)
    return sc + pc + mc, d, bearing(a["lat"], a["lon"], b["lat"], b["lon"])


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------

def solve(slots, seed=None, exclude=None, must_visit=None):
    """Minimum-cost walk from slot 0 (the pinned anchor) backwards.

    slots[j] is the list of candidate nodes at slot j (t0 - 6j hours); a slot
    holding one pinned node is archive data and must be visited. `seed` is
    (node, hours_ahead) - the archive's later HF fix - and fixes the heading
    entering the anchor. `exclude` is a set of (slot, node index) removed from
    play, `must_visit` a slot the walk may neither skip nor stop short of; the
    two together ask "what is the best walk that does NOT use this candidate",
    which is how ambiguity is measured.

    The state is an EDGE (a -> b), because the heading term compares the step
    into a node with the step out of it. Returns (total cost, path) where path
    is a list of dicts {slot, idx, node, edge_cost, heading_cost, gap_before,
    jump, d6}, anchor first; or (INF, None) when no walk satisfies the
    constraints."""
    n_slots = len(slots) - 1
    exclude = exclude or set()
    anchor = slots[0][0]
    pinned_slot = [len(s) == 1 and s[0]["pinned"] for s in slots]

    def alive(j, i):
        return (j, i) not in exclude

    # states[(j, i)] = {prev (j, i) or None: (cost, back_state_key, bearing, d6, comps)}
    states = defaultdict(dict)
    seed_bearing, seed_d6 = None, 0.0
    if seed is not None:
        z, hrs = seed
        seed_bearing = bearing(z["lat"], z["lon"], anchor["lat"], anchor["lon"])
        seed_d6 = B.great_circle_nm(z["lat"], z["lon"], anchor["lat"], anchor["lon"]) / (hrs / 6.0)
    states[(0, 0)][None] = (0.0, None, seed_bearing, seed_d6, None)

    for ja in range(n_slots):
        for ia, a in enumerate(slots[ja]):
            if (ja, ia) not in states:
                continue
            incoming = states[(ja, ia)]
            for jb in range(ja + 1, n_slots + 1):
                span = jb - ja
                if span >= 2:
                    # A skip over free slots only. Never over a pinned archive fix, and
                    # never onto a free node more than one slot away: two consecutive
                    # missing slots end the track. The one exception is re-acquiring a
                    # pinned archive fix, priced at the missing slots between.
                    if any(pinned_slot[k] for k in range(ja + 1, jb)):
                        break
                    if must_visit is not None and ja < must_visit < jb:
                        break
                    if span >= 3 and not pinned_slot[jb]:
                        continue
                for ib, b in enumerate(slots[jb]):
                    if not alive(jb, ib):
                        continue
                    dt_h = span * float(STEP_H)
                    if span >= 3:                     # re-acquire: archive fix, no step to judge
                        step = (0.0, 0.0, None)
                    else:
                        step = edge_cost(a, b, dt_h)
                    if step is None:
                        continue
                    ec, dist, brg = step
                    d6 = dist / (dt_h / 6.0)
                    gap = MISSING_COST * (span - 1)
                    for prev_key, (cost, _, pb, pd6, _c) in incoming.items():
                        hc = 0.0
                        if not (a["pinned"] and b["pinned"]) and span < 3:
                            hc = heading_cost(pb, pd6, brg, d6)
                        # A step that costs as much as a gap is not a match. Without this
                        # the search can buy one dreadful link (cost 15) with the credit of a
                        # long pleasant chain beyond it - every slot saved from being "lost"
                        # is worth MISSING_COST - and so bridge OVER a perfectly good
                        # candidate near the anchor to reach it. The track nearest the
                        # anchor must stand on its own links.
                        if span < 3 and not (a["pinned"] and b["pinned"]) \
                                and ec + hc >= MISSING_COST:
                            continue
                        total = cost + ec + hc + gap
                        cur = states[(jb, ib)].get((ja, ia))
                        if cur is None or total < cur[0]:
                            states[(jb, ib)][(ja, ia)] = (
                                total, (ja, ia, prev_key), None if span >= 3 else brg, d6,
                                (ec, hc, gap, span))
        # states for slot ja are final once every earlier slot was relaxed

    # Pick the cheapest ending: the last real node, then every slot after it is lost.
    best_total, best_end = INF, None
    last_pinned = max([j for j in range(n_slots + 1) if pinned_slot[j]] or [0])
    if last_pinned == 0 and must_visit is None:
        best_total, best_end = MISSING_COST * n_slots, ((0, 0), None)
    for (j, i), by_prev in states.items():
        if (j, i) == (0, 0) and None in by_prev:
            continue
        if j < last_pinned:
            continue
        if must_visit is not None and j < must_visit:
            continue
        for prev, (cost, *_rest) in by_prev.items():
            total = cost + MISSING_COST * (n_slots - j)
            if total < best_total:
                best_total, best_end = total, ((j, i), prev)
    if best_end is None:
        return INF, None

    # Walk the back pointers.
    path, key = [], best_end
    chain = []
    node_key, prev = key
    while True:
        if prev is None and node_key == (0, 0):
            chain.append((node_key, None))
            break
        chain.append((node_key, prev))
        entry = states[node_key][prev]
        back = entry[1]                                  # (ja, ia, prev_key_of_a)
        node_key, prev = (back[0], back[1]), back[2]
    chain.reverse()
    for node_key, prev in chain:
        j, i = node_key
        entry = states[node_key][prev]
        comps = entry[4]
        path.append({"slot": j, "idx": i, "node": slots[j][i],
                     "edge_cost": 0.0 if comps is None else comps[0],
                     "heading_cost": 0.0 if comps is None else comps[1],
                     "gap_before": 0 if comps is None else comps[3] - 1,
                     "jump": 0 if comps is None else comps[3],
                     "d6": entry[3]})
    return best_total, path


# ---------------------------------------------------------------------------
# Per-event tracking
# ---------------------------------------------------------------------------

def first_hf(event):
    fixes = sorted(event["fixes"], key=lambda f: f[0])
    return next((f for f in fixes if f[3] == "HF"), None), fixes


def hf_seed(fixes, t0):
    """The archive's own motion at t0, from its first two HF fixes: the next HF
    fix 6 h later (or 12 h later when 6 h is missing). None when the storm has
    a single HF fix, or the second comes too late to describe the same motion."""
    by_t = {f[0]: f for f in fixes if f[3] == "HF"}
    for hrs in (6, 12):
        f = by_t.get(shift(t0, hrs))
        if f is not None:
            return new_node(f[1], f[2], f[4], None, None, "HF", True, "archive"), hrs
    return None


def archive_node(f):
    return new_node(f[1], f[2], f[4], None, None, f[3], True, "archive")


# POST-V1 CHANGE: the archive-suspect refusal below was added after the V1 runs, on
# principle (never anchor on a probable typo), and removes 16 events from tracking.
# (basin, event_id, valid) of archive fixes that archive_position_suspects() judges to be
# mistyped. Filled by set_suspects(); empty means no check (unit tests, ad-hoc use).
ARCHIVE_SUSPECTS = set()


def set_suspects(events, lows):
    """Compute the suspected archive position errors once and make prepare() refuse
    to build a track on one: an anchor whose position is probably mistyped would
    attach a stranger's low to the event, and a pinned lead fix that is mistyped
    corrupts every step next to it. The event is skipped (status archive-suspect),
    not repaired - the archive is never altered."""
    suspects = archive_position_suspects(events, lows)
    ARCHIVE_SUSPECTS.clear()
    ARCHIVE_SUSPECTS.update((x["basin"], x["event"], x["valid"]) for x in suspects)
    return suspects


def prepare(event, lows, mode="production", anchor_time=None):
    """Everything the search needs for one event, or (None, reason).

    mode "production": pin every archive fix in the window.
    mode "hidden":     V1. Only HF-category fixes are visible; the event's
                       pre-HF fixes are hidden, to be compared afterwards.
    anchor_time:       V1b. Treat the HF fix at this time as the anchor and
                       hide every earlier fix of the event."""
    hf, fixes = first_hf(event)
    if hf is None:
        return None, "no-hf-fix"
    t0 = anchor_time if anchor_time is not None else hf[0]
    anchor_fix = next((f for f in fixes if f[0] == t0 and f[3] == "HF"), None)
    if anchor_fix is None:
        return None, "no-anchor"
    if anchor_fix[4] is None:
        return None, "anchor-no-pressure"
    times = Counter(f[0] for f in fixes)
    window = [shift(t0, -h) for h in range(0, B.BACKFILL_WINDOW_H + 1, STEP_H)]
    if any(times[t] > 1 for t in window):
        return None, "duplicate-times"

    basin = event["basin"]
    watched = [t0] + ([t for t in window[1:] if t in times] if mode == "production" else [])
    if any((basin, event["id"], t) in ARCHIVE_SUSPECTS for t in watched):
        return None, "archive-suspect"
    anchor = archive_node(anchor_fix)
    verified, anchor_match = False, None
    for c in lows.get((basin, t0), []):
        d = B.great_circle_nm(anchor["lat"], anchor["lon"], c["lat"], c["lon"])
        if d <= ANCHOR_MATCH_NM and (anchor_match is None or d < anchor_match[0]):
            anchor_match = (d, c)
    if anchor_match is not None:
        verified = True
        anchor["vx"], anchor["vy"] = anchor_match[1]["vx"], anchor_match[1]["vy"]

    slots = [[anchor]]
    by_t = {f[0]: f for f in fixes}
    for j in range(1, SLOTS + 1):
        t = shift(t0, -STEP_H * j)
        arch = by_t.get(t)
        if mode == "production" and arch is not None and arch[3] != "ABS":
            slots.append([archive_node(arch)])
        else:
            slots.append([dict(c) for c in lows.get((basin, t), [])])
    seed = hf_seed(fixes, t0)
    return {"event": event, "t0": t0, "anchor": anchor, "slots": slots, "seed": seed,
            "verified": verified, "anchor_match": anchor_match}, None


def pooled_duplicates(slot, idx):
    """Indexes of candidates in `slot` that are the same low as slot[idx]: so
    close, with a pressure within 2 hPa, that choosing either gives the same
    fix for any purpose we have. They do not make a choice ambiguous."""
    n = slot[idx]
    out = {idx}
    for k, c in enumerate(slot):
        if k != idx and B.great_circle_nm(n["lat"], n["lon"], c["lat"], c["lon"]) <= 45.0 \
                and (None in (n["pres"], c["pres"]) or abs(n["pres"] - c["pres"]) <= 2.0):
            out.add(k)
    return out


def track(prep):
    """Run the search for one prepared event -> a result dict.

    result["fixes"] is the list of RECOVERED (non-pinned) fixes of the track,
    truncated, each with its prefix confidence."""
    slots = prep["slots"]
    total, path = solve(slots, prep["seed"])
    res = {"prep": prep, "total": total, "path": path, "fixes": [], "ambiguous": {}}
    if path is None:
        return res

    # Walk the path from the anchor, stopping where the storm is lost.
    walk = [path[0]]
    for p in path[1:]:
        if p["jump"] >= 3:                       # two consecutive missing slots
            break
        walk.append(p)
    res["walk"] = walk

    # Ambiguity at each recovered slot: the best walk that cannot use this
    # candidate (nor a duplicate listing of it). If it is nearly as cheap, the
    # choice is a coin flip, whatever the pressures say.
    for p in walk[1:]:
        if p["node"]["pinned"]:
            continue
        excl = {(p["slot"], k) for k in pooled_duplicates(slots[p["slot"]], p["idx"])}
        alt_total, alt_path = solve(slots, prep["seed"], exclude=excl, must_visit=p["slot"])
        res["ambiguous"][p["slot"]] = alt_total - total

    # Confidence is graded on the PREFIX of the track from the anchor to each
    # fix. A track whose far end is shaky still has a trustworthy near end, and
    # the build only wants the near end to be good enough; the whole point of
    # truncating rather than discarding is to keep what we do stand behind.
    gaps, worst, amb_seen = 0, 0.0, False
    capped = (prep["seed"] is None) or (not prep["verified"])
    for k, p in enumerate(walk[1:], start=1):
        gaps += p["gap_before"]
        worst = max(worst, p["edge_cost"] + p["heading_cost"])
        if not p["node"]["pinned"] and res["ambiguous"].get(p["slot"], INF) < AMBIGUITY_MARGIN:
            amb_seen = True
        if gaps >= 2 or amb_seen or worst > MISSING_COST:
            conf = "low"
        elif gaps == 0 and worst <= LOW_BAND_COST and not capped \
                and p["node"]["pres"] is not None:
            conf = "high"
        else:
            conf = "medium"
        if not p["node"]["pinned"]:
            # Predicted position: carry on the motion of the two nodes just before it in
            # the walk (the seed fix stands in for the one before the anchor).
            before = walk[k - 1]
            if k >= 2:
                z = (walk[k - 2]["node"], before["slot"] - walk[k - 2]["slot"])
            elif prep["seed"] is not None:
                z = (prep["seed"][0], prep["seed"][1] // STEP_H)
            else:
                z = None
            if z is not None:
                plat, plon = extrapolate(before["node"], z, p["slot"] - before["slot"])
            else:
                plat, plon = before["node"]["lat"], before["node"]["lon"]
            res["fixes"].append({
                "slot": p["slot"], "valid": shift(prep["t0"], -STEP_H * p["slot"]),
                "node": p["node"], "conf": conf, "cost": p["edge_cost"] + p["heading_cost"],
                "gap_before": p["gap_before"],
                "match_nm": B.great_circle_nm(plat, plon, p["node"]["lat"], p["node"]["lon"]),
                "ambiguity": res["ambiguous"].get(p["slot"], INF)})
    return res


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def rows_for(res):
    ev = res["prep"]["event"]
    out = []
    for f in sorted(res["fixes"], key=lambda f: f["valid"]):
        n = f["node"]
        out.append([ev["basin"], ev["id"], iso(f["valid"]), "%.1f" % n["lat"], "%.1f" % n["lon"],
                    "" if n["pres"] is None else "%d" % round(n["pres"]), n["cat"], "hsf",
                    "%.0f" % f["match_nm"], f["conf"]])
    return out


def collisions(results, events):
    """QC, not failure: a recovered fix within COLLISION_NM of ANOTHER archive
    event's fix at the same valid time means two archive events are probably
    one storm (the archive splits a low that lapses below hurricane force and
    returns). Both (basin, event_id) pairs are named; nothing is merged or
    dropped. Note this is a different phenomenon from the build's `split` flag,
    which means one id was REUSED for unrelated lows across a >48 h gap."""
    index = defaultdict(list)
    for ev in events:
        for f in ev["fixes"]:
            index[(ev["basin"], f[0])].append((ev["id"], f))
    notes = []
    for res in results:
        ev = res["prep"]["event"]
        for f in res["fixes"]:
            n = f["node"]
            for other_id, of in index.get((ev["basin"], f["valid"]), []):
                if other_id == ev["id"]:
                    continue
                d = B.great_circle_nm(n["lat"], n["lon"], of[1], of[2])
                if d <= COLLISION_NM:
                    notes.append({"basin": ev["basin"], "event": ev["id"], "other": other_id,
                                  "valid": f["valid"], "nm": d, "conf": f["conf"],
                                  "other_cat": of[3]})
    return notes


def write_csv(path, results, notes, header_comments=(), min_conf="low"):
    """Write precursors.csv. `min_conf` drops rows below that grade: the contract
    says emit all three and let the build decide, but the build refuses `low`
    outright (one QC note per row), so the committed file is written at
    min_conf="medium"."""
    rows = []
    for res in results:
        rows.extend(r for r in rows_for(res)
                    if B.CONF_RANK[r[9]] >= B.CONF_RANK[min_conf])
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        for c in header_comments:
            fh.write("# " + c + "\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        w.writerows(rows)
    return len(rows)


def run_all(events, lows, mode="production"):
    results, skipped = [], Counter()
    for ev in events:
        prep, why = prepare(ev, lows, mode)
        if prep is None:
            skipped[why] += 1
            continue
        results.append(track(prep))
    return results, skipped


# ---------------------------------------------------------------------------
# Calibration of the three derived constants
# ---------------------------------------------------------------------------

def quantile(values, p):
    v = sorted(values)
    return v[min(len(v) - 1, int(p * len(v)))] if v else None


def true_step_costs(events, lows):
    """Cost of every genuine archive HF -> HF step with a preceding step, scored
    by the very cost function the tracker uses (the motion term where a parsed
    low sits within 100 nm of the step's later fix). These are the numbers
    MISSING_COST, LOW_BAND_COST and AMBIGUITY_MARGIN come from."""
    costs = []
    for ev in events:
        hf = {f[0]: f for f in ev["fixes"] if f[3] == "HF"}
        for t in sorted(hf):
            t_prev, t_next = shift(t, -6), shift(t, 6)      # z=t_next(later) -> a=t -> b=t_prev(earlier)
            if t_prev not in hf or t_next not in hf:
                continue
            nodes = []
            for tt in (t_next, t, t_prev):
                f = hf[tt]
                n = archive_node(f)
                m = None
                for c in lows.get((ev["basin"], tt), []):
                    d = B.great_circle_nm(f[1], f[2], c["lat"], c["lon"])
                    if d <= ANCHOR_MATCH_NM and (m is None or d < m[0]):
                        m = (d, c)
                if m is not None:
                    n["vx"], n["vy"] = m[1]["vx"], m[1]["vy"]
                n["pinned"] = False
                nodes.append(n)
            z, a, b = nodes
            e_in = edge_cost(z, a, 6.0)
            e_out = edge_cost(a, b, 6.0)
            if e_in is None or e_out is None:
                continue
            hc = heading_cost(e_in[2], e_in[1], e_out[2], e_out[1])
            costs.append(e_out[0] + hc)
    return costs


def prehf_pressure_steps(events):
    """Signed 6-h pressure changes (later minus earlier) over archive steps whose
    later fix is at or before the event's first HF fix, and over HF -> HF steps."""
    pre, mature = [], []
    for ev in events:
        hf = [f for f in sorted(ev["fixes"]) if f[3] == "HF"]
        if not hf:
            continue
        by = {f[0]: f for f in ev["fixes"] if f[3] != "ABS"}
        for t, f in by.items():
            prev = by.get(shift(t, -STEP_H))
            if prev is None or f[4] is None or prev[4] is None:
                continue
            if t <= hf[0][0]:
                pre.append(f[4] - prev[4])
            if f[3] == "HF" and prev[3] == "HF":
                mature.append(f[4] - prev[4])
    return pre, mature


def calibrate(events, lows, out=sys.stdout):
    pre, mature = prehf_pressure_steps(events)
    out.write("6-h pressure change (later minus earlier), hPa:\n")
    for name, v in (("HF -> HF (mature)", mature), ("pre-HF (regime tracked)", pre)):
        sv = sorted(v)
        q = lambda p: sv[min(len(sv) - 1, int(p * len(sv)))]
        out.write("  %-26s n %5d  p1 %4.0f p5 %4.0f p10 %4.0f median %4.0f min %4.0f   "
                  "|dp| p50 %.0f p90 %.0f p95 %.0f p99 %.0f max %.0f\n" % (
                      name, len(sv), q(.01), q(.05), q(.1), q(.5), sv[0],
                      quantile([abs(x) for x in sv], .5), quantile([abs(x) for x in sv], .9),
                      quantile([abs(x) for x in sv], .95), quantile([abs(x) for x in sv], .99),
                      max(abs(x) for x in sv)))
    out.write("shipped: PRES_SCALE_HPA=%.0f (rule: p90 of pre-HF |dp|)  PRES_HARD_HPA=%.0f\n"
              % (PRES_SCALE_HPA, PRES_HARD_HPA))
    c = true_step_costs(events, lows)
    out.write("true HF->HF step cost over %d steps (cost function as shipped):\n" % len(c))
    for p in (0.5, 0.75, 0.9, 0.95, 0.975, 0.99):
        out.write("  p%-5g %.2f\n" % (p * 100, quantile(c, p)))
    out.write("shipped: MISSING_COST=%.2f (rule: p95)  LOW_BAND_COST=%.2f (rule: p90)  "
              "AMBIGUITY_MARGIN=%.2f (rule: p75)\n"
              % (MISSING_COST, LOW_BAND_COST, AMBIGUITY_MARGIN))
    return c


# ---------------------------------------------------------------------------
# Recovered-only chains, and suspected archive errors
# ---------------------------------------------------------------------------

CHAIN_COLUMNS = ["basin", "event_id", "season", "t0", "status", "seeded", "anchor_verified",
                 "chain_h_any", "chain_h_medium_plus", "chain_h_high"]


def hidden_chains(events, lows):
    """Per HF event, the hours of gapless RECOVERED pressure-bearing chain behind the
    first HF fix when every pre-HF archive fix is ignored (the tracker alone).

    Why a sidecar rather than counting rows of precursors.csv: in production the
    archive's own pre-HF fixes are pinned and the tracker emits nothing at those
    slots (the build would refuse a recovered row at a time the archive has a
    fix), so the chain of ROWS has holes exactly where the archive recorded lead
    fixes - 2017+ - and would carry the recording-practice artefact in the other
    direction. This is the era-neutral measure: archive practice cannot reach it.
    Three tiers, by the prefix confidence of the fixes in the chain."""
    out = []
    for ev in events:
        if not ev["hfN"]:
            continue
        hf = first_hf(ev)[0]
        rec = {"basin": ev["basin"], "event": ev["id"], "season": ev["season"], "t0": hf[0],
               "minP": ev["minP"], "lat0": hf[1], "status": "tracked", "seeded": False,
               "verified": False, "chain_h_any": 0, "chain_h_usable": 0, "chain_h_high": 0}
        prep, why = prepare(ev, lows, "hidden")
        if prep is None:
            rec["status"] = why
            out.append(rec)
            continue
        res = track(prep)
        rec["seeded"] = prep["seed"] is not None
        rec["verified"] = prep["verified"]
        fx = {f["slot"]: f for f in res["fixes"] if f["node"]["pres"] is not None}
        for key, ok in (("chain_h_any", lambda c: True), ("chain_h_usable", lambda c: c != "low"),
                        ("chain_h_high", lambda c: c == "high")):
            k = 0
            while k + 1 in fx and ok(fx[k + 1]["conf"]) and k < SLOTS:
                k += 1
            rec[key] = k * STEP_H
        out.append(rec)
    return out


CHAIN_HEADER = [
    "Recovered-only chain hours per HF event, written by tools/track_hsf.py (--chain-out).",
    "NOT the precursors file: this is a per-event table, one row per archive event with an HF fix.",
    "Each chain_h_* is the hours of gapless, pressure-bearing, 6-hourly RECOVERED chain behind the",
    "event's first HF fix, found with EVERY pre-HF archive fix ignored (the tracker alone), so the",
    "archive's 2013/2017 change of recording practice cannot reach it. Use this, not the row chain",
    "of precursors.csv, for era-neutral coverage: precursors.csv omits the slots the archive owns.",
    "  basin, event_id    the build's keys (suffixed split ids included)",
    "  season, t0         storm season label, and the first HF fix (UTC)",
    "  status             tracked | anchor-no-pressure | archive-suspect | duplicate-times",
    "  seeded             1 if the archive has a second HF fix 6-12 h later (heading seed)",
    "  anchor_verified    1 if a parsed HSF low lies within 100 nm of the first HF fix at t0",
    "  chain_h_any        hours of chain counting fixes of any confidence",
    "  chain_h_medium_plus  ... counting only medium or high fixes (the shipping floor)",
    "  chain_h_high       ... counting only high fixes",
    "A chain of 24 or more is what the build's Bf rule needs. 0 for every untracked status.",
]


def write_chain_csv(path, chains, header_comments=CHAIN_HEADER):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        for c in header_comments:
            fh.write("# " + c + "\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(CHAIN_COLUMNS)
        for c in sorted(chains, key=lambda c: (c["basin"], c["event"])):
            w.writerow([c["basin"], c["event"], B.season_label(c["season"]), iso(c["t0"]), c["status"],
                        int(c["seeded"]), int(c["verified"]), c["chain_h_any"], c["chain_h_usable"],
                        c["chain_h_high"]])


def archive_position_suspects(events, lows):
    """Archive fixes whose POSITION is probably mistyped, found by the HSF.

    A fix is listed when (1) a parsed low at the same valid time has exactly the
    archive fix's pressure yet sits more than WRONG_STORM_NM from it, and (2)
    moving the fix to that low turns an implausible leg into a plausible one:
    the fastest adjacent leg is >= 60 kt as archived, <= 50 kt if moved, and the
    move buys at least 20 kt. (1) alone is a one-in-ten coincidence per
    candidate low; (2) is what makes it evidence. Independent of the build's
    90 kt check, which flags a subset of these. Nothing is corrected - the human
    archive is never altered - this is a worklist for fixing it upstream."""
    out = []
    for ev in events:
        by = {}
        for f in ev["fixes"]:
            if f[3] != "ABS":
                by.setdefault(f[0], []).append(f)
        for t, fs in sorted(by.items()):
            if len(fs) != 1 or fs[0][4] is None:
                continue
            f = fs[0]
            nbrs = [by[tt][0] for tt in (shift(t, -STEP_H), shift(t, STEP_H))
                    if tt in by and len(by[tt]) == 1]
            if not nbrs:
                continue

            def worst(lat, lon):
                return max(B.great_circle_nm(lat, lon, n[1], n[2]) / STEP_H for n in nbrs)
            before = worst(f[1], f[2])
            if before < 60.0:
                continue
            best = None
            for c in lows.get((ev["basin"], t), []):
                if c["pres"] != f[4]:
                    continue
                d = B.great_circle_nm(f[1], f[2], c["lat"], c["lon"])
                if d <= WRONG_STORM_NM:
                    continue
                after = worst(c["lat"], c["lon"])
                if after <= 50.0 and before - after >= 20.0 and (best is None or after < best[0]):
                    best = (after, d, c)
            if best is not None:
                out.append({"basin": ev["basin"], "event": ev["id"], "valid": t, "cat": f[3],
                            "a_lat": f[1], "a_lon": f[2], "pres": f[4], "h_lat": best[2]["lat"],
                            "h_lon": best[2]["lon"], "nm": best[1], "speed_before": before,
                            "speed_after": best[0]})
    return out


def write_suspects_csv(path, suspects):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["basin", "event_id", "valid", "category", "archive_lat", "archive_lon", "pres",
                    "hsf_lat", "hsf_lon", "distance_nm", "speed_kt_as_archived", "speed_kt_if_moved",
                    "build_speed_flag"])
        for x in suspects:
            w.writerow([x["basin"], x["event"], iso(x["valid"]), x["cat"], "%.1f" % x["a_lat"],
                        "%.1f" % x["a_lon"], "%d" % x["pres"], "%.1f" % x["h_lat"], "%.1f" % x["h_lon"],
                        "%.0f" % x["nm"], "%.0f" % x["speed_before"], "%.0f" % x["speed_after"],
                        int(x["speed_before"] >= B.SPEED_IMPLAUSIBLE_KT)])


# ---------------------------------------------------------------------------
# Validation. V1 (hidden pre-HF fixes), V1b (pseudo-anchor), V2 (anchor check),
# coverage uniformity, selection, dumps, and what the build makes of the file.
# Nothing here feeds back into a weight.
# ---------------------------------------------------------------------------

ERAS = [(2002, 2006), (2007, 2011), (2012, 2016), (2017, 2021), (2022, 2099)]
WRONG_STORM_NM = 200.0


def era_of(t):
    y = t // 1000000
    for lo, hi in ERAS:
        if lo <= y <= hi:
            return "%d-%d" % (lo, hi) if hi < 2099 else "%d+" % lo
    return "?"


def median(v):
    v = sorted(v)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def fmt(x, nd=1):
    return "-" if x is None else ("%.*f" % (nd, x))


def stats_row(values):
    """n, median, p90, max of a list of non-negative numbers."""
    if not values:
        return (0, None, None, None)
    return (len(values), median(values), quantile(values, 0.9), max(values))


def truth_by_time(event):
    return {f[0]: f for f in event["fixes"] if f[3] != "ABS"}


def score_fixes(res, truth, t0):
    """Per recovered fix that has a human analysis at the same time: errors."""
    out = []
    for f in res["fixes"]:
        tr = truth.get(f["valid"])
        if tr is None:
            continue
        n = f["node"]
        out.append({"slot": f["slot"], "lead": f["slot"] * STEP_H, "conf": f["conf"],
                    "pos": B.great_circle_nm(n["lat"], n["lon"], tr[1], tr[2]),
                    "dp": None if (n["pres"] is None or tr[4] is None) else n["pres"] - tr[4],
                    "valid": f["valid"], "cat": tr[3]})
    return out


def is_wrong(score, excl_exact_pressure=False):
    """A fix more than WRONG_STORM_NM from the archive's own analysis at that time.

    With `excl_exact_pressure`, fixes whose pressure matches the archive's to the
    exact hPa are not counted. HSF and the archive state the same office's same
    analysis, so they agree to the hPa 97% of the time; a recovered fix 400 nm
    from the archive position that matches its pressure exactly is far more often
    a mistyped ARCHIVE coordinate than a different storm (chance agreement to the
    hPa between two different lows is about one in ten). Both readings are
    reported; neither is tuned. Suspected archive errors are listed by
    archive_position_suspects()."""
    if score["pos"] <= WRONG_STORM_NM:
        return False
    if not excl_exact_pressure:
        return True
    return score["dp"] is None or score["dp"] != 0


def contiguous_lead(truth, t0):
    """Hours of unbroken 6-hourly archive record immediately before t0."""
    h = 0
    while shift(t0, -STEP_H * (h // STEP_H + 1)) in truth:
        h += STEP_H
    return h


def deepening_pair(event, t0, res, usable):
    """(truth deep24, recovered deep24, uses_pre_hf) over the same slots.

    Both series hold the event's HF-category fixes; the truth series adds the
    archive's own pre-HF fixes and the recovered series the tracker's, at ONLY
    those slots where both exist and `usable(conf)`. Same span, same fixes
    times, so the difference is the attribution and nothing else."""
    truth = truth_by_time(event)
    rec = {f["valid"]: f for f in res["fixes"] if usable(f["conf"])}
    common = [t for t in rec if t in truth and truth[t][4] is not None
              and rec[t]["node"]["pres"] is not None]
    hf = [list(f) for f in sorted(event["fixes"]) if f[3] == "HF"]
    s_true = sorted(hf + [list(truth[t]) for t in common], key=lambda f: f[0])
    s_rec = sorted(hf + [[t, rec[t]["node"]["lat"], rec[t]["node"]["lon"], "", rec[t]["node"]["pres"]]
                         for t in common], key=lambda f: f[0])
    a, b = B.max_deepening(s_true), B.max_deepening(s_rec)
    if a is None or b is None:
        return None
    return a[0], b[0], (a[2] < t0 or b[2] < t0), len(common)


def validate(events, lows, out_path, out=sys.stdout, chain_out=None, archive_qc_out=None):
    w = out.write
    t_start = datetime.now(timezone.utc)
    suspects_all = set_suspects(events, lows)

    # ----- V2: the anchor check ------------------------------------------------
    w("\n=== V2  anchor check: parsed low nearest the archive's first HF fix, same valid time, "
      "within %d nm ===\n" % ANCHOR_MATCH_NM)
    v2 = defaultdict(list)
    for ev in events:
        hf, _ = first_hf(ev)
        if hf is None or hf[4] is None:
            continue
        best = None
        for c in lows.get((ev["basin"], hf[0]), []):
            d = B.great_circle_nm(hf[1], hf[2], c["lat"], c["lon"])
            if d <= ANCHOR_MATCH_NM and c["pres"] is not None and (best is None or d < best[0]):
                best = (d, c)
        key = (ev["basin"], era_of(hf[0]))
        v2[key].append(None if best is None else best[1]["pres"] - hf[4])
    w("  %-5s %-10s %7s %8s %6s %9s %7s %7s\n" % ("basin", "era", "events", "matched", "rate",
                                                  "exact", "median", "|d|>2"))
    tot = [0, 0, 0, 0]
    for b in ("atl", "pac"):
        for lo, hi in ERAS:
            era = "%d-%d" % (lo, hi) if hi < 2099 else "%d+" % lo
            v = v2.get((b, era), [])
            m = [x for x in v if x is not None]
            if not v:
                continue
            exact = sum(1 for x in m if x == 0)
            big = sum(1 for x in m if abs(x) > 2)
            w("  %-5s %-10s %7d %8d %5.0f%% %8.0f%% %7s %7d\n" % (
                b, era, len(v), len(m), 100.0 * len(m) / len(v), 100.0 * exact / max(1, len(m)),
                fmt(median(m)), big))
            tot[0] += len(v); tot[1] += len(m); tot[2] += exact; tot[3] += big
    w("  pooled: %d events, %d matched (%.0f%%), %.1f%% agree to the exact hPa, %d differ by more "
      "than 2 hPa\n" % (tot[0], tot[1], 100.0 * tot[1] / tot[0], 100.0 * tot[2] / max(1, tot[1]),
                       tot[3]))

    # ----- production run ------------------------------------------------------
    results, skipped = run_all(events, lows, "production")
    hf_events = [e for e in events if e["hfN"]]
    w("\n=== production run: %d events with an HF fix; tracked %d; not tracked: %s ===\n" % (
        len(hf_events), len(results), dict(skipped)))
    conf = Counter(f["conf"] for r in results for f in r["fixes"])
    w("  recovered rows: %d  (high %d, medium %d, low %d)\n" % (
        sum(conf.values()), conf["high"], conf["medium"], conf["low"]))
    w("  tracked events with any recovered row: %d; anchor verified against a parsed low: %d of %d\n"
      % (sum(1 for r in results if r["fixes"]), sum(1 for r in results if r["prep"]["verified"]),
         len(results)))
    w("  tracked events without a heading seed (single HF fix): %d\n"
      % sum(1 for r in results if r["prep"]["seed"] is None))

    # ----- V1 -------------------------------------------------------------------
    w("\n=== V1  pre-HF fixes HIDDEN; anchored on HF-category fixes only; scored against the "
      "archive's own pre-HF analysis ===\n")
    v1 = []
    for ev in events:
        prep, why = prepare(ev, lows, "hidden")
        if prep is None:
            continue
        truth = truth_by_time(ev)
        lead = contiguous_lead(truth, prep["t0"])
        if lead < 6:
            continue
        res = track(prep)
        v1.append({"ev": ev, "res": res, "lead": lead, "truth": truth, "t0": prep["t0"],
                   "scores": score_fixes(res, truth, prep["t0"])})
    n6 = len(v1)
    n12 = sum(1 for r in v1 if r["lead"] >= 12)
    w("  events with >= 6 h of own pre-HF record: %d   (>= 12 h: %d)\n" % (n6, n12))

    def v1_table(title, filt):
        w("  %s\n" % title)
        w("  %-26s %7s %7s %6s %7s | %-24s | %-22s | %s\n" % (
            "subset", "events", "scored", "wrong", "wrongX", "position nm  med/p90/max",
            "pressure hPa |err| med/p90/max", "bias hPa"))
        for name, sel in (("all confidences", lambda c: True),
                          ("medium or high (usable)", lambda c: c != "low"),
                          ("high only", lambda c: c == "high")):
            rows = [(r, s) for r in v1 if filt(r) for s in r["scores"] if sel(s["conf"])]
            if not rows:
                continue
            pos = [s["pos"] for _, s in rows]
            dp = [abs(s["dp"]) for _, s in rows if s["dp"] is not None]
            sg = [s["dp"] for _, s in rows if s["dp"] is not None]
            wrong = sum(1 for p in pos if p > WRONG_STORM_NM)
            wrong_dp = sum(1 for _, s in rows if is_wrong(s, True))
            evs = len({id(r) for r, _ in rows})
            ps, ds = stats_row(pos), stats_row(dp)
            w("  %-26s %7d %7d %5.1f%% %6.1f%% | %6s %7s %8s | %5s %6s %6s | %s\n" % (
                name, evs, len(rows), 100.0 * wrong / len(rows), 100.0 * wrong_dp / len(rows),
                fmt(ps[1], 0), fmt(ps[2], 0),
                fmt(ps[3], 0), fmt(ds[1], 0), fmt(ds[2], 0), fmt(ds[3], 0),
                fmt(sum(sg) / len(sg) if sg else None, 2)))
    v1_table("population: >= 6 h of own pre-HF record", lambda r: True)
    v1_table("population: >= 12 h of own pre-HF record", lambda r: r["lead"] >= 12)

    w("\n  by lead behind the first HF fix (all confidences / usable):\n")
    w("  %-8s %8s %7s %6s %9s %7s %9s\n" % ("lead h", "scored", "wrong", "rate", "pos med", "pos p90",
                                          "usable n/wrong"))
    for lead in range(6, 49, 6):
        rows = [s for r in v1 for s in r["scores"] if s["lead"] == lead]
        if not rows:
            continue
        us = [s for s in rows if s["conf"] != "low"]
        w("  %-8d %8d %7d %5.1f%% %9s %7s %9s\n" % (
            lead, len(rows), sum(1 for s in rows if s["pos"] > WRONG_STORM_NM),
            100.0 * sum(1 for s in rows if s["pos"] > WRONG_STORM_NM) / len(rows),
            fmt(median([s["pos"] for s in rows]), 0), fmt(quantile([s["pos"] for s in rows], .9), 0),
            "%d/%d" % (len(us), sum(1 for s in us if s["pos"] > WRONG_STORM_NM))))

    n_truth_slots = 0
    n_recovered_slots = 0
    for r in v1:
        for h in range(STEP_H, B.BACKFILL_WINDOW_H + 1, STEP_H):
            t = shift(r["t0"], -h)
            if t in r["truth"]:
                n_truth_slots += 1
                if any(f["valid"] == t for f in r["res"]["fixes"]):
                    n_recovered_slots += 1
    w("\n  recall: of %d slots where the archive has its own fix, the tracker emitted a fix at "
      "%d (%.0f%%)\n" % (n_truth_slots, n_recovered_slots,
                         100.0 * n_recovered_slots / max(1, n_truth_slots)))
    w("\n  what the tracker recovers, by how fast the storm was deepening into its first HF fix\n"
      "  (archive pressure at t0-6 h minus at t0; larger = deepened more in that 6 h):\n")
    w("  %-14s %7s %9s %8s %12s\n" % ("fall into t0", "slots", "emitted", "recall", "usable wrong"))
    bins = [("<= 0 hPa", -99, 0), ("1-5", 1, 5), ("6-10", 6, 10), ("11-15", 11, 15), (">= 16", 16, 99)]
    for label, lo, hi in bins:
        n = e = uw = 0
        for r in v1:
            t1 = shift(r["t0"], -STEP_H)
            tr = r["truth"].get(t1)
            p0 = r["res"]["prep"]["anchor"]["pres"]
            if tr is None or tr[4] is None or not (lo <= tr[4] - p0 <= hi):
                continue
            n += 1
            f = next((f for f in r["res"]["fixes"] if f["slot"] == 1), None)
            if f is not None:
                e += 1
                sc = next(x for x in r["scores"] if x["slot"] == 1)
                uw += 1 if (f["conf"] != "low" and is_wrong(sc)) else 0
        if n:
            w("  %-14s %7d %9d %7.0f%% %12d\n" % (label, n, e, 100.0 * e / n, uw))
    wrong_events = {id(r) for r in v1 for s in r["scores"] if s["pos"] > WRONG_STORM_NM}
    wrong_events_u = {id(r) for r in v1 for s in r["scores"]
                      if s["pos"] > WRONG_STORM_NM and s["conf"] != "low"}
    w("  events with at least one wrong-storm fix: %d of %d (%.1f%%); counting only usable (medium/"
      "high) fixes: %d (%.1f%%)\n" % (len(wrong_events), n6, 100.0 * len(wrong_events) / n6,
                                      len(wrong_events_u), 100.0 * len(wrong_events_u) / n6))

    w("  ... excluding fixes whose pressure matches the archive exactly: usable fixes %d "
      "of %d (%.1f%%)\n" % (sum(1 for r in v1 for s in r["scores"] if s["conf"] != "low" and is_wrong(s, True)),
                            sum(1 for r in v1 for s in r["scores"] if s["conf"] != "low"),
                            100.0 * sum(1 for r in v1 for s in r["scores"] if s["conf"] != "low" and is_wrong(s, True))
                            / max(1, sum(1 for r in v1 for s in r["scores"] if s["conf"] != "low"))))
    w("  V1 usable fixes by era (calendar year of the first HF fix):\n")
    for lo, hi in ERAS:
        rows = [s for r in v1 for s in r["scores"]
                if s["conf"] != "low" and lo <= r["t0"] // 1000000 <= hi]
        if rows:
            w("   %-10s scored %4d  wrong %5.1f%%  (excl. exact-P %5.1f%%)  events %d\n" % (
                "%d-%d" % (lo, hi) if hi < 2099 else "%d+" % lo, len(rows),
                100.0 * sum(1 for s in rows if is_wrong(s)) / len(rows),
                100.0 * sum(1 for s in rows if is_wrong(s, True)) / len(rows),
                len({id(r) for r in v1 if lo <= r["t0"] // 1000000 <= hi and r["scores"]})))

    w("\n  derived 24-h deepening, recovered vs the archive's own, over the SAME slots "
      "(hPa / 24 h; recovered minus archive):\n")
    w("  %-34s %7s %8s %8s %8s %8s %7s\n" % ("subset", "events", "bias", "med|err|", "p90|err|",
                                           "max|err|", "exact"))
    for label, usable in (("all confidences", lambda c: True),
                          ("medium or high (usable)", lambda c: c != "low")):
        pairs = []
        for r in v1:
            pr = deepening_pair(r["ev"], r["t0"], r["res"], usable)
            if pr is not None:
                pairs.append(pr)
        for sub, sel in (("any", lambda p: p[3] > 0),
                         ("window uses a pre-HF fix", lambda p: p[2] and p[3] > 0)):
            ps = [p for p in pairs if sel(p)]
            if not ps:
                continue
            err = [p[1] - p[0] for p in ps]
            ae = [abs(x) for x in err]
            w("  %-34s %7d %8.2f %8.1f %8.1f %8.1f %6.0f%%\n" % (
                label + ", " + sub, len(ps), sum(err) / len(err), median(ae), quantile(ae, .9),
                max(ae), 100.0 * sum(1 for x in ae if x < 0.05) / len(ae)))
    w("  (a positive bias would mean the tracker overstates deepening; the pressure term is "
      "sign-blind by construction, so none is expected)\n")

    # ----- V1 split by whether the anchor was verified ------------------------
    w("\n  V1 wrong-storm rate by the tracker's own confidence tag:\n")
    for tag in ("high", "medium", "low"):
        rows = [s for r in v1 for s in r["scores"] if s["conf"] == tag]
        if rows:
            w("   %-8s scored %5d  wrong %5.1f%%  (excl. exact-P %5.1f%%)\n" % (
                tag, len(rows), 100.0 * sum(1 for s in rows if is_wrong(s)) / len(rows),
                100.0 * sum(1 for s in rows if is_wrong(s, True)) / len(rows)))
    w("\n  V1 wrong-storm rate by anchor status (usable fixes only):\n")
    for label, sel in (("anchor verified by a parsed low", lambda r: r["res"]["prep"]["verified"]),
                       ("anchor NOT verified", lambda r: not r["res"]["prep"]["verified"]),
                       ("heading seeded", lambda r: r["res"]["prep"]["seed"] is not None),
                       ("no seed (single HF fix)", lambda r: r["res"]["prep"]["seed"] is None)):
        rows = [s for r in v1 if sel(r) for s in r["scores"] if s["conf"] != "low"]
        if rows:
            w("   %-34s scored %5d  wrong %5.1f%%  pos med %s\n" % (
                label, len(rows), 100.0 * sum(1 for s in rows if s["pos"] > WRONG_STORM_NM) / len(rows),
                fmt(median([s["pos"] for s in rows]), 0)))

    # ----- V1b ------------------------------------------------------------------
    w("\n=== V1b  pseudo-anchor: anchor on a later HF fix, hide everything before it, score against "
      "up to 48 h of the archive's own track (longer leads than V1 can reach) ===\n")
    v1b = []
    for ev in events:
        truth = truth_by_time(ev)
        hf_t = sorted(f[0] for f in ev["fixes"] if f[3] == "HF" and f[4] is not None)
        cands = [t for t in hf_t
                 if contiguous_lead(truth, t) >= 24
                 and (shift(t, 6) in truth and truth[shift(t, 6)][3] == "HF")]
        if not cands:
            continue
        t_a = cands[-1]                      # the latest such fix: the storm at its most mature
        prep, why = prepare(ev, lows, "hidden", anchor_time=t_a)
        if prep is None:
            continue
        res = track(prep)
        v1b.append({"ev": ev, "res": res, "scores": score_fixes(res, truth, t_a), "t0": t_a})
    w("  events: %d\n" % len(v1b))
    w("  %-8s %8s %7s %6s %9s %7s %12s %12s\n" % ("lead h", "scored", "wrong", "rate", "pos med",
                                                  "pos p90", "usable n", "usable wrong"))
    for lead in range(6, 49, 6):
        rows = [s for r in v1b for s in r["scores"] if s["lead"] == lead]
        if not rows:
            continue
        us = [s for s in rows if s["conf"] != "low"]
        wr = sum(1 for s in rows if s["pos"] > WRONG_STORM_NM)
        uw = sum(1 for s in us if s["pos"] > WRONG_STORM_NM)
        w("  %-8d %8d %7d %5.1f%% %9s %7s %12d %7d (%.1f%%)\n" % (
            lead, len(rows), wr, 100.0 * wr / len(rows), fmt(median([s["pos"] for s in rows]), 0),
            fmt(quantile([s["pos"] for s in rows], .9), 0), len(us), uw,
            100.0 * uw / max(1, len(us))))
    chain_n = chain_wrong = chain_wrong_dp = 0
    end_err = []
    for r in v1b:
        fx = {f["slot"]: f for f in r["res"]["fixes"]}
        if not all(k in fx and fx[k]["conf"] != "low" for k in (1, 2, 3, 4)):
            continue
        chain_n += 1
        sc = {s["slot"]: s for s in r["scores"]}
        chain_wrong += any(k in sc and is_wrong(sc[k]) for k in (1, 2, 3, 4))
        chain_wrong_dp += any(k in sc and is_wrong(sc[k], True) for k in (1, 2, 3, 4))
        if 4 in sc and sc[4]["dp"] is not None:
            end_err.append(sc[4]["dp"])
    ae = sorted(abs(e) for e in end_err)
    w("  events whose usable chain reaches 24 h (slots 1-4 all usable; what the build would use): %d\n"
      "    with any fix > %d nm from the archive: %d (%.1f%%); of those, excl. exact-P: %d "
      "(%.1f%%)\n" % (chain_n, WRONG_STORM_NM, chain_wrong, 100.0 * chain_wrong / max(1, chain_n),
                      chain_wrong_dp, 100.0 * chain_wrong_dp / max(1, chain_n)))
    if ae:
        w("    24-h-back pressure (the end of the deepening window) vs archive: n %d, exact %d, "
          "within 2 hPa %d, > 5 hPa %d, > 10 hPa %d, max %.0f\n" % (
              len(ae), sum(1 for e in ae if e == 0), sum(1 for e in ae if e <= 2),
              sum(1 for e in ae if e > 5), sum(1 for e in ae if e > 10), ae[-1]))
    w("  V1b usable fixes by era:\n")
    for lo, hi in ERAS:
        rows = [s for r in v1b for s in r["scores"]
                if s["conf"] != "low" and lo <= r["t0"] // 1000000 <= hi]
        if rows:
            w("   %-10s scored %4d  wrong %5.1f%%  (excl. exact-P %5.1f%%)  events %d\n" % (
                "%d-%d" % (lo, hi) if hi < 2099 else "%d+" % lo, len(rows),
                100.0 * sum(1 for s in rows if is_wrong(s)) / len(rows),
                100.0 * sum(1 for s in rows if is_wrong(s, True)) / len(rows),
                len({id(r) for r in v1b if lo <= r["t0"] // 1000000 <= hi and r["scores"]})))
    w("  V1b by the tracker's own confidence tag (per fix / per 24 h chain):\n")
    for tag, ok in (("high", lambda c: c == "high"), ("medium", lambda c: c == "medium"),
                    ("medium or high", lambda c: c != "low")):
        rows = [s for r in v1b for s in r["scores"] if ok(s["conf"])]
        chains_ = 0
        cw = cwx = 0
        for r in v1b:
            fx = {f["slot"]: f for f in r["res"]["fixes"]}
            if not all(k in fx and ok(fx[k]["conf"]) for k in (1, 2, 3, 4)):
                continue
            chains_ += 1
            sc = {s["slot"]: s for s in r["scores"]}
            cw += any(k in sc and is_wrong(sc[k]) for k in (1, 2, 3, 4))
            cwx += any(k in sc and is_wrong(sc[k], True) for k in (1, 2, 3, 4))
        if rows:
            w("   %-15s fixes %5d wrong %4.1f%% (excl. exact-P %4.1f%%) | 24 h chains %3d: any wrong %d (%.1f%%), "
              "excl. exact-P %d (%.1f%%)\n" % (
                  tag, len(rows), 100.0 * sum(1 for s in rows if is_wrong(s)) / len(rows),
                  100.0 * sum(1 for s in rows if is_wrong(s, True)) / len(rows), chains_, cw,
                  100.0 * cw / max(1, chains_), cwx, 100.0 * cwx / max(1, chains_)))
    allr = [s for r in v1b for s in r["scores"]]
    usr = [s for s in allr if s["conf"] != "low"]
    w("  all leads: scored %d, wrong %.1f%%;  usable: %d, wrong %.1f%%;  pressure |err| median %s "
      "p90 %s (usable)\n" % (
          len(allr), 100.0 * sum(1 for s in allr if s["pos"] > WRONG_STORM_NM) / max(1, len(allr)),
          len(usr), 100.0 * sum(1 for s in usr if s["pos"] > WRONG_STORM_NM) / max(1, len(usr)),
          fmt(median([abs(s["dp"]) for s in usr if s["dp"] is not None]), 0),
          fmt(quantile([abs(s["dp"]) for s in usr if s["dp"] is not None], .9), 0)))

    # ----- write the file and let the build judge it --------------------------
    notes = collisions(results, events)
    n_rows = write_csv(out_path, results, notes)
    w("\n=== what the build makes of %s (%d rows) ===\n" % (os.path.relpath(out_path, ROOT), n_rows))
    payload = B.build(precursors=out_path)
    c = payload["qc"]["counts"]
    w("  rows read %s, accepted %s, refused %s\n" % (c.get("precursorRows"), c.get("precursorsAccepted"),
                                                    c.get("precursorsRefused", 0)))
    for k in sorted(c):
        if k.startswith("precRefused_") or k.startswith("precDuplicates"):
            w("    %-34s %d\n" % (k, c[k]))
    w("  accepted rows by confidence: %s\n" % dict(conf))
    kinds = Counter(n["kind"] for n in payload["qc"]["notes"] if n["kind"].startswith("precursor"))
    w("  precursor QC notes by kind: %s\n" % dict(kinds))
    bf = payload["backfill"]

    w("\n=== coverage: per season and basin, HF events vs events reaching the build's 24 h gapless "
      "pressure chain ===\n")
    w("  (attempted = events with an HF fix, the build's denominator; trackable = of those, the "
      "tracker could anchor)\n")
    track_ok = Counter((r["prep"]["event"]["basin"], r["prep"]["event"]["season"]) for r in results)
    w("  %-8s %-5s %9s %9s %9s %7s %9s\n" % ("season", "basin", "attempted", "trackable", "any row",
                                            "24h chain", "share"))
    cov = bf["coverage"]
    for row in cov:
        w("  %-8s %-5s %9d %9d %9d %9d %6.1f%%\n" % (
            B.season_label(row["season"]), row["basin"], row["events"],
            track_ok[(row["basin"], row["season"])], row["recovered"], row["usable"],
            row["share"] if row["share"] is not None else 0.0))
    w("\n  share spread over seasons from %d (the build's RECORD_START):\n" % bf["trendFrom"])
    for k, st in bf["trend"].items():
        w("   %-4s seasons %2d  min %5.1f%%  max %5.1f%%  spread %5.1f pts  slope %s pts/season "
          "(se %s)\n" % (k, st["seasons"], st["min"], st["max"], st["spread"], st["slope"], st["se"]))
    w("  build coverageTrend flag: %s\n" % bf["coverageTrend"])
    for why in bf["coverageTrendWhy"]:
        w("    - %s\n" % why)
    w("\n  selection (from %d on): events with a usable 24 h chain vs without\n" % bf["trendFrom"])
    w("   %-5s %-10s %6s %12s %14s\n" % ("basin", "", "n", "median minP", "median lat"))
    for k, sel in bf["selection"].items():
        for lab in ("covered", "uncovered"):
            s = sel[lab]
            w("   %-5s %-10s %6d %12s %14s\n" % (k, lab, s["n"], fmt(s["medianMinP"], 1),
                                                 fmt(s["medianLat"], 1)))

    saved = B.BACKFILL_MIN_CONF
    try:
        B.BACKFILL_MIN_CONF = "high"
        pay_hi = B.build(precursors=out_path)
    finally:
        B.BACKFILL_MIN_CONF = saved
    bh = pay_hi["backfill"]
    w("\n=== the same, if the build kept only conf = high (BACKFILL_MIN_CONF = high) ===\n")
    w("  rows accepted %s of %s\n" % (pay_hi["qc"]["counts"].get("precursorsAccepted"),
                                     pay_hi["qc"]["counts"].get("precursorRows")))
    for k, st in bh["trend"].items():
        w("   %-4s seasons %2d  min %5.1f%%  max %5.1f%%  spread %5.1f pts  slope %s pts/season "
          "(se %s)\n" % (k, st["seasons"], st["min"], st["max"], st["spread"], st["slope"], st["se"]))
    for why in bh["coverageTrendWhy"]:
        w("    - %s\n" % why)
    for k, sel in bh["selection"].items():
        for lab in ("covered", "uncovered"):
            x = sel[lab]
            w("   %-5s %-10s %6d %12s %14s\n" % (k, lab, x["n"], fmt(x["medianMinP"], 1),
                                                 fmt(x["medianLat"], 1)))
    by_era_hi = defaultdict(lambda: [0, 0])
    for row in bh["coverage"]:
        if row["season"] >= B.RECORD_START:
            y = row["season"]
            era = next(("%d-%d" % (lo, hi) if hi < 2099 else "%d+" % lo) for lo, hi in ERAS if lo <= y <= hi)
            by_era_hi[(row["basin"], era)][0] += row["events"]
            by_era_hi[(row["basin"], era)][1] += row["usable"]
    w("  pooled by era: " + "; ".join("%s %s %.0f%% (%d/%d)" % (b, e, 100.0 * u / n, u, n)
                                      for (b, e), (n, u) in sorted(by_era_hi.items())) + "\n")
    by_era_md = defaultdict(lambda: [0, 0])
    for row in bf["coverage"]:
        if row["season"] >= B.RECORD_START:
            y = row["season"]
            era = next(("%d-%d" % (lo, hi) if hi < 2099 else "%d+" % lo) for lo, hi in ERAS if lo <= y <= hi)
            by_era_md[(row["basin"], era)][0] += row["events"]
            by_era_md[(row["basin"], era)][1] += row["usable"]
    w("  (for comparison, kept medium or high, pooled by era: " +
      "; ".join("%s %s %.0f%%" % (b, e, 100.0 * u / n) for (b, e), (n, u) in sorted(by_era_md.items()))
      + ")\n")

    # ----- coverage with the archive's own lead fixes taken OUT --------------------
    w("\n=== coverage by the TRACKER ALONE: every event's pre-HF archive fixes hidden, so the archive's "
      "2013/2017 change of recording practice cannot contribute ===\n")
    w("  (the build's table above lets the archive's own DHF/S lead fixes complete a chain, so it "
      "partly measures practice; this one measures the tracker)\n")
    chains = hidden_chains(hf_events, lows)
    tiers = (("medium or high (usable)", "chain_h_usable"), ("high only", "chain_h_high"))
    for tier, key in tiers:
        w("\n  --- tier: %s; an event counts if slots 1-4 (24 h) are all in the tier ---\n" % tier)
        own = defaultdict(lambda: [0, 0, 0])
        grp = {True: [], False: []}
        for c in chains:
            row = own[(c["basin"], c["season"])]
            row[0] += 1
            row[1] += 1 if c["chain_h_any"] > 0 else 0
            ok = c[key] >= 24
            row[2] += 1 if ok else 0
            if c["season"] >= B.RECORD_START:
                grp[ok].append((c["minP"], c["lat0"], c["basin"]))
        rows = [{"basin": b_, "season": se, "events": c[0], "recovered": c[1], "usable": c[2]}
                for (b_, se), c in sorted(own.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
        if key == "chain_h_usable":
            w("  %-8s %-5s %9s %9s %9s\n" % ("season", "basin", "attempted", "any usable", "24h chain"))
            for row in rows:
                w("  %-8s %-5s %9d %9d %9d %6.1f%%\n" % (
                    B.season_label(row["season"]), row["basin"], row["events"], row["recovered"],
                    row["usable"], 100.0 * row["usable"] / row["events"]))
        trend, tripped = B.coverage_trend(rows)
        for k, st in trend.items():
            w("   %-4s seasons %2d  min %5.1f%%  max %5.1f%%  spread %5.1f pts  slope %s pts/season "
              "(se %s)\n" % (k, st["seasons"], st["min"], st["max"], st["spread"], st["slope"], st["se"]))
        for why in tripped:
            w("    - %s\n" % why)
        # How much spread would a perfectly uniform tracker show? Seasons hold only 25-65 HF
        # events, so a constant success probability still scatters the seasonal share.
        rr = random.Random(1)
        for k2 in ("atl", "pac", "all"):
            sel = [r for r in rows if r["season"] >= B.RECORD_START and (k2 == "all" or r["basin"] == k2)]
            by_season = defaultdict(lambda: [0, 0])
            for r in sel:
                by_season[r["season"]][0] += r["events"]
                by_season[r["season"]][1] += r["usable"]
            p_all = sum(v[1] for v in by_season.values()) / float(sum(v[0] for v in by_season.values()))
            spreads = []
            for _ in range(2000):
                shares = [100.0 * sum(rr.random() < p_all for _ in range(n)) / n
                          for n, _u in by_season.values()]
                spreads.append(max(shares) - min(shares))
            w("   %-4s a constant %.1f%% success rate would scatter the seasonal share over a spread of "
              "%.0f-%.0f points (5th-95th percentile of 2000 draws)\n" % (
                  k2, 100.0 * p_all, quantile(spreads, .05), quantile(spreads, .95)))
        by_era = defaultdict(lambda: [0, 0])
        for row in rows:
            if row["season"] >= B.RECORD_START:
                y = row["season"]
                era = next(("%d-%d" % (lo, hi) if hi < 2099 else "%d+" % lo) for lo, hi in ERAS if lo <= y <= hi)
                by_era[(row["basin"], era)][0] += row["events"]
                by_era[(row["basin"], era)][1] += row["usable"]
        w("  pooled by era (season start year): ")
        w("; ".join("%s %s %.0f%% (%d/%d)" % (b_, e, 100.0 * u / n, u, n)
                    for (b_, e), (n, u) in sorted(by_era.items())) + "\n")
        w("  selection (tracker alone, from %d on): events with a 24 h chain vs without\n" % B.RECORD_START)
        for k2 in ("atl", "pac", "all"):
            for lab, ok in (("covered", True), ("uncovered", False)):
                g = [x for x in grp[ok] if k2 == "all" or x[2] == k2]
                w("   %-5s %-10s %6d %12s %14s\n" % (k2, lab, len(g),
                                                     fmt(median([x[0] for x in g if x[0] is not None]), 1),
                                                     fmt(median([x[1] for x in g]), 1)))
    if chain_out:
        write_chain_csv(chain_out, chains)
        w("\n  recovered-only chain lengths per event written to %s\n" % chain_out)
    suspects = suspects_all
    if archive_qc_out:
        write_suspects_csv(archive_qc_out, suspects)
    w("\n=== suspected ARCHIVE position errors: %d fixes (%d events); %d already flagged by the build's "
      "%d kt check ===\n" % (len(suspects), len({(x["basin"], x["event"]) for x in suspects}),
                             sum(1 for x in suspects if x["speed_before"] >= B.SPEED_IMPLAUSIBLE_KT),
                             int(B.SPEED_IMPLAUSIBLE_KT)))
    for x in suspects[:15]:
        w("   %s:%s %s %s archive %.1f/%.1f %s hPa -> HSF low %.0f nm away with the SAME pressure; "
          "implied speed %.0f kt as archived, %.0f kt if moved\n" % (
              x["basin"], x["event"], iso(x["valid"]), x["cat"], x["a_lat"], x["a_lon"], x["pres"],
              x["nm"], x["speed_before"], x["speed_after"]))
    w("   (the same-pressure rule alone is a one-in-ten coincidence per candidate; a fix is listed only if "
      "moving it to the HSF low also removes an implausible leg)\n")

    # ----- cross-event collisions ----------------------------------------------
    w("\n=== cross-event collision QC notes: %d (recovered fix within %d nm of ANOTHER archive "
      "event's fix at the same valid time) ===\n" % (len(notes), COLLISION_NM))
    pairs = Counter((n["basin"], n["event"], n["other"]) for n in notes)
    w("  distinct event pairs: %d; by conf %s\n" % (len(pairs), dict(Counter(n["conf"] for n in notes))))
    for n in sorted(notes, key=lambda n: (n["basin"], n["event"], n["valid"]))[:12]:
        w("   %s:%s fix %s is %.0f nm from %s:%s's %s fix  [%s]\n" % (
            n["basin"], n["event"], iso(n["valid"]), n["nm"], n["basin"], n["other"], n["other_cat"],
            n["conf"]))

    # ----- V3 dumps --------------------------------------------------------------
    w("\n=== V3  20 recovered tracks (production mode, the tracker as shipped; random, seed 20261007) ===\n")
    w("    5 are tracks the tracker rated low confidence somewhere; 4 are events that fell >= 16 hPa into\n"
      "    t0; the rest are one per basin x era. 'archive' rows are pinned archive fixes, not recovered.\n")
    rnd = random.Random(20261007)
    have = [r for r in results if r["fixes"]]
    any_low = [r for r in have if any(f["conf"] == "low" for f in r["fixes"])]
    steep = [r for r in have if (fall_into_t0(r["prep"]["event"], r["prep"]["t0"]) or 0) >= 16]
    cells = defaultdict(list)
    for r in have:
        ev = r["prep"]["event"]
        cells[(ev["basin"], era_of(r["prep"]["t0"]))].append(r)
    chosen = rnd.sample(any_low, min(5, len(any_low)))          # what "unsure" looks like
    chosen += rnd.sample([r for r in steep if r not in chosen], min(4, len(steep)))
    for key in sorted(cells):                                   # one per basin x era
        pick = rnd.choice([r for r in cells[key] if r not in chosen] or cells[key])
        if pick not in chosen:
            chosen.append(pick)
    pool = [r for r in have if r not in chosen]
    chosen.extend(rnd.sample(pool, max(0, 20 - len(chosen))))
    chosen = chosen[:20]
    chosen.sort(key=lambda r: (r["prep"]["event"]["basin"], r["prep"]["t0"]))
    for r in chosen:
        falls = fall_into_t0(r["prep"]["event"], r["prep"]["t0"])
        extra = []
        if r in any_low:
            extra.append("has LOW-confidence fixes")
        if falls is not None and falls >= 16:
            extra.append("fell %d hPa into t0" % falls)
        print_track(r, out)
        if extra:
            w("  [%s]\n" % "; ".join(extra))
        w("\n")
    w("=== V3b  the same steep events with the archive's lead fixes HIDDEN: tracker vs the archive's own ===\n")
    shown = 0
    for r in chosen:
        ev = r["prep"]["event"]
        falls = fall_into_t0(ev, r["prep"]["t0"])
        if falls is None or falls < 16:
            continue
        prep, why = prepare(ev, lows, "hidden")
        if prep is None:
            continue
        print_track_vs_truth(track(prep), truth_by_time(ev), out)
        w("\n")
        shown += 1
    if not shown:
        w("  (none of the chosen steep events could be re-run hidden)\n")
    w("elapsed %.0f s\n" % (datetime.now(timezone.utc) - t_start).total_seconds())
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def fall_into_t0(event, t0):
    """hPa the archive says the storm deepened in the 6 h before t0 (positive = fell),
    or None when either pressure is missing."""
    by = {f[0]: f for f in event["fixes"]}
    a, b = by.get(t0), by.get(shift(t0, -STEP_H))
    if a is None or b is None or a[4] is None or b[4] is None:
        return None
    return int(round(b[4] - a[4]))


def print_track_vs_truth(res, truth, out=sys.stdout):
    prep = res["prep"]
    ev = prep["event"]
    out.write("%s:%s  t0=%s  [hidden mode: archive pre-HF fixes not seen]  anchor %.1fN %.1f %s hPa\n" % (
        ev["basin"], ev["id"], iso(prep["t0"]), prep["anchor"]["lat"], prep["anchor"]["lon"],
        prep["anchor"]["pres"]))
    out.write("  %-20s %6s %7s %6s  %-6s | %-28s %s\n" % (
        "valid", "lat", "lon", "pres", "conf", "archive's own (cat lat lon pres)", "error"))
    for f in sorted(res["fixes"], key=lambda f: f["slot"]):
        n = f["node"]
        tr = truth.get(f["valid"])
        tx = "-"
        err = ""
        if tr is not None:
            tx = "%-4s %5.1f %6.1f %s" % (tr[3], tr[1], tr[2], "-" if tr[4] is None else "%d" % tr[4])
            err = "%.0f nm%s" % (B.great_circle_nm(n["lat"], n["lon"], tr[1], tr[2]),
                                 "" if tr[4] is None or n["pres"] is None else ", %+d hPa" % (n["pres"] - tr[4]))
        out.write("  %-20s %6.1f %7.1f %6s  %-6s | %-28s %s\n" % (
            iso(f["valid"]), n["lat"], n["lon"], "" if n["pres"] is None else "%d" % n["pres"],
            f["conf"], tx, err))


def print_track(res, out=sys.stdout):
    prep = res["prep"]
    ev = prep["event"]
    out.write("%s:%s  t0=%s  anchor %.1fN %.1f %s hPa  verified=%s seed=%s total=%.2f\n" % (
        ev["basin"], ev["id"], iso(prep["t0"]), prep["anchor"]["lat"], prep["anchor"]["lon"],
        prep["anchor"]["pres"], prep["verified"],
        "yes" if prep["seed"] else "no", res["total"]))
    out.write("  %-20s %6s %7s %6s %7s  %-5s %-6s %s\n" %
              ("valid", "lat", "lon", "pres", "cost", "cat", "conf", "source"))
    for p in (res.get("walk") or []):
        n = p["node"]
        f = next((f for f in res["fixes"] if f["slot"] == p["slot"]), None)
        out.write("  %-20s %6.1f %7.1f %6s %7.2f  %-5s %-6s %s%s\n" % (
            iso(shift(prep["t0"], -STEP_H * p["slot"])), n["lat"], n["lon"],
            "" if n["pres"] is None else "%d" % n["pres"],
            p["edge_cost"] + p["heading_cost"], n["cat"],
            "anchor" if p["slot"] == 0 else (f["conf"] if f else "archive"),
            "archive" if n["pinned"] else "hsf",
            "  (bridged %d)" % p["gap_before"] if p["gap_before"] else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lows", default=LOWS_CSV, help="parse_hsf.py output (default %(default)s)")
    ap.add_argument("--out", default=OUT_CSV, help="precursors CSV to write (default %(default)s)")
    ap.add_argument("--event", help="basin:id - print that event's track and write nothing")
    ap.add_argument("--hidden", action="store_true",
                    help="with --event: V1 mode, hide the event's pre-HF fixes")
    ap.add_argument("--calibrate", action="store_true", help="print the archive step-cost quantiles")
    ap.add_argument("--validate", action="store_true", help="V1, V1b, V2, coverage, dumps")
    ap.add_argument("--qc-out", help="write the cross-event collision notes here (CSV)")
    ap.add_argument("--archive-qc-out", help="write suspected ARCHIVE position errors here (CSV)")
    ap.add_argument("--chain-out", help="write per-event recovered-only chain lengths here (CSV)")
    ap.add_argument("--min-conf", choices=("low", "medium", "high"), default="low",
                    help="drop precursor rows below this grade (default low = emit all three; "
                         "the committed file uses medium, the build's floor)")
    args = ap.parse_args(argv)

    events = load_events()
    lows = load_lows(args.lows)
    suspects = set_suspects(events, lows)

    if args.calibrate:
        calibrate(events, lows)
        return 0
    if args.validate:
        return validate(events, lows, args.out, chain_out=args.chain_out,
                        archive_qc_out=args.archive_qc_out)
    if args.event:
        basin, _, eid = args.event.partition(":")
        ev = next((e for e in events if e["basin"] == basin and e["id"] == eid), None)
        if ev is None:
            raise SystemExit("no such event: " + args.event)
        prep, why = prepare(ev, lows, "hidden" if args.hidden else "production")
        if prep is None:
            raise SystemExit("not tracked: " + why)
        print_track(track(prep))
        return 0

    results, skipped = run_all(events, lows)
    notes = collisions(results, events)
    header = ["Pre-HF precursors recovered from OPC High Seas Forecasts by tools/track_hsf.py.",
              "Floor: conf >= %s. source=hsf. Production run: archive lead fixes are pinned, so no row" % args.min_conf,
              "is written at a time the archive already has a fix for the event.",
              "warn_cat is the header the product filed the low under; for a developing storm that is the",
              "warning for what it WILL become, not an observation of hurricane-force wind at that time.",
              "Recovered-only chain hours per event are in recovered_chain_hours.csv, not derivable here."]
    n = write_csv(args.out, results, notes, header, args.min_conf)
    conf = Counter(f["conf"] for r in results for f in r["fixes"])
    sys.stderr.write("events %d, tracked %d, skipped %s\nrows written %d (%s) -> %s\n"
                     % (len(events), len(results), dict(skipped), n,
                        ", ".join("%s %d" % (k, conf[k]) for k in ("high", "medium", "low")),
                        os.path.relpath(args.out, ROOT)))
    sys.stderr.write("cross-event collision notes: %d\n" % len(notes))
    if args.chain_out:
        write_chain_csv(args.chain_out, hidden_chains(events, lows))
    if args.archive_qc_out:
        write_suspects_csv(args.archive_qc_out, suspects)
    if args.qc_out:
        with open(args.qc_out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["basin", "event", "other_event", "valid", "nm", "conf", "other_cat"])
            for x in notes:
                w.writerow([x["basin"], x["event"], x["other"], iso(x["valid"]), "%.0f" % x["nm"],
                            x["conf"], x["other_cat"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
