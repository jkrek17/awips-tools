#!/usr/bin/env python3
"""Checks for the recording-practice fix in tools/build_hf_lows.py.

The archive began logging developing-hurricane-force fixes before each storm's
first hurricane-force (HF) fix, and storm-force fixes after its last, from the
2013-14 Pacific and 2017-18 Atlantic seasons. Anything measured over the whole
recorded track therefore steps up with the practice, not the weather. These
tests pin down that the default deepening/track figures no longer do:

  * SYNTHETIC events show the mechanism in isolation: lead fixes inflate the
    all-fix deepening and leave the HF-window deepening alone;
  * the REAL payload shows the symptom is gone: the all-fix explosive share
    steps by tens of points across 2017 (the guard: if it did not, the other
    assertions would be vacuous) while the HF-only share does not, and lead
    fixes per event predict the first but not the second;
  * the expected values come from independent code below, not from the
    module's own deepening arithmetic, so a bug cannot cancel against itself.

  * the pre-HF BACKFILL (data/hf_lows/precursors.csv) is exercised on synthetic
    events and synthetic CSV files written to a temp directory - never the
    development precursors.csv in the repo, whose contents are not real - so
    the sign of deepRelH, the coverage rule, and every rejection path are
    pinned by numbers worked out by hand below.

    python3 tests/hf_lows/test_hf_lows.py
"""
import copy
import importlib.util
import json
import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

spec = importlib.util.spec_from_file_location(
    "build_hf_lows", os.path.join(ROOT, "tools", "build_hf_lows.py"))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

SPLIT = 2017          # first season in which both basins log lead fixes


def stamp(t0, hours):
    d = t0 + timedelta(hours=hours)
    return d.year * 1000000 + d.month * 10000 + d.day * 100 + d.hour


T0 = datetime(2020, 1, 10, 0)


def make_low(spec_rows, basin="atl", low_id="2019202001"):
    """spec_rows: [(hours since T0, lat, lon, cat, pres)] -> a derived low."""
    low = {"basin": basin, "id": low_id, "season": 2019, "num": 1, "idOk": True,
           "fixes": [[stamp(T0, h), lat, lon, cat, p] for h, lat, lon, cat, p in spec_rows]}
    tool.derive(low, tool.QC())
    return low


def independent_berg(fixes):
    """Best 18-24 h normalized fall among time-sorted fixes, written out
    separately from the module: (dp * 24/h / 24) * sin60 / sin(mean lat)."""
    best = None
    for i, a in enumerate(fixes):
        for b in fixes[i + 1:]:
            if a[4] is None or b[4] is None:
                continue
            ha = datetime(a[0] // 1000000, a[0] // 10000 % 100, a[0] // 100 % 100, a[0] % 100)
            hb = datetime(b[0] // 1000000, b[0] // 10000 % 100, b[0] // 100 % 100, b[0] % 100)
            h = (hb - ha).total_seconds() / 3600.0
            if h < 18 or h > 24:
                continue
            drop = (a[4] - b[4]) * 24.0 / h
            berg = drop / 24.0 * math.sin(math.radians(60)) / math.sin(math.radians((a[1] + b[1]) / 2))
            if best is None or drop > best[0]:
                best = (drop, berg)
    return best


class Mechanism(unittest.TestCase):
    """Synthetic storms, one mechanism each."""

    def test_lead_fixes_inflate_recorded_deepening_only(self):
        # A storm that deepens 30 hPa in the 24 h BEFORE its hurricane-force
        # period, which is then only 6 h long. The new practice records the
        # deepening as DHF fixes; the old practice would have started at HF.
        low = make_low([
            (0, 50.0, -40.0, "DHF", 1000.0), (6, 50.0, -40.0, "DHF", 992.0),
            (12, 50.0, -40.0, "DHF", 985.0), (18, 50.0, -40.0, "DHF", 978.0),
            (24, 50.0, -40.0, "HF", 970.0), (30, 50.0, -40.0, "HF", 968.0),
            (36, 50.0, -40.0, "S", 972.0)])
        self.assertTrue(low["bombAll"], "the recorded track contains the deepening")
        self.assertAlmostEqual(low["deep24All"], 30.0)
        self.assertIsNone(low["deep24"], "HF window is 6 h: nothing to measure")
        self.assertIsNone(low["berg"])
        self.assertFalse(low["bomb"])
        # Not a field the lead fixes may touch.
        self.assertEqual(low["minP"], 968.0)
        self.assertEqual(low["hfN"], 2)
        self.assertEqual(low["hfH"], 12)

    def test_same_storm_without_the_lead_fixes_agrees_with_hf_figures(self):
        with_lead = make_low([
            (0, 50.0, -40.0, "DHF", 1000.0), (6, 50.0, -40.0, "DHF", 990.0),
            (12, 50.0, -40.0, "HF", 980.0), (18, 50.0, -40.0, "HF", 972.0),
            (24, 50.0, -40.0, "HF", 966.0), (30, 50.0, -40.0, "HF", 960.0),
            (36, 50.0, -40.0, "S", 962.0)])
        old_practice = make_low([
            (12, 50.0, -40.0, "HF", 980.0), (18, 50.0, -40.0, "HF", 972.0),
            (24, 50.0, -40.0, "HF", 966.0), (30, 50.0, -40.0, "HF", 960.0)])
        for k in ("deep24", "berg", "bomb", "hfDurH", "hfDistNm", "hfSpdKt", "hfN", "hfH", "minP"):
            self.assertEqual(with_lead[k], old_practice[k], k)
        # ...whereas the recorded-track figures differ, which is the whole problem.
        self.assertNotEqual(with_lead["durH"], old_practice["durH"])
        self.assertNotEqual(with_lead["deep24All"], old_practice["deep24All"])

    def test_hf_window_keeps_interior_fixes_in_the_path(self):
        # An S fix between two HF fixes is part of the path: the HF-window
        # distance is the path through it, not the corner-cutting chord.
        low = make_low([
            (0, 50.0, -40.0, "HF", 970.0), (6, 54.0, -40.0, "S", 972.0),
            (12, 50.0, -40.0, "HF", 968.0)])
        chord = tool.great_circle_nm(50.0, -40.0, 50.0, -40.0)
        self.assertEqual(chord, 0.0)
        self.assertGreater(low["hfDistNm"], 400)
        self.assertEqual(low["hfDistNm"], low["distNm"])
        self.assertEqual(low["hfDurH"], 12)

    def test_single_and_no_hf_fix(self):
        one = make_low([(0, 50.0, -40.0, "DHF", 990.0), (6, 51.0, -40.0, "HF", 980.0),
                        (12, 52.0, -40.0, "S", 982.0)])
        self.assertEqual((one["hfDurH"], one["hfDistNm"], one["hfSpdKt"]), (0, 0, None))
        none = make_low([(0, 50.0, -40.0, "S", 990.0), (6, 51.0, -40.0, "S", 985.0)])
        self.assertEqual((none["hfDurH"], none["hfDistNm"], none["hfN"]), (None, None, 0))
        self.assertIsNone(none["berg"])
        self.assertFalse(none["bomb"])

    def test_explosive_when_hf_window_really_deepens(self):
        low = make_low([
            (0, 60.0, -30.0, "HF", 990.0), (6, 60.0, -30.0, "HF", 980.0),
            (12, 60.0, -30.0, "HF", 972.0), (18, 60.0, -30.0, "HF", 966.0),
            (24, 60.0, -30.0, "HF", 960.0)])
        # Best pair is 990 -> 966 over 18 h: 24 hPa scaled by 24/18 = 32 hPa/24 h,
        # and at 60 N exactly 24 hPa/24 h is 1 B, so 32/24 = 1.33 B (not the
        # 24 h pair, 30 hPa = 1.25 B: the scaled shorter window wins).
        self.assertAlmostEqual(low["deep24"], 32.0)
        self.assertAlmostEqual(low["berg"], 32.0 / 24.0, places=2)
        self.assertTrue(low["bomb"])
        self.assertTrue(low["bombAll"])


class RealPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Without the backfill: these tests are about the archive's own figures,
        # and must not depend on whatever precursors.csv is lying in the repo.
        cls.payload = tool.build(precursors=None)
        fields = cls.payload["lowFields"]
        cls.lows = [dict(zip(fields, row)) for row in cls.payload["lows"]]
        cls.practice = cls.payload["practice"]

    def share(self, lows, bomb):
        return 100.0 * sum(1 for l in lows if l[bomb]) / len(lows)

    def era(self, lo, hi, basin=None):
        return [l for l in self.lows if lo <= l["season"] <= hi
                and (basin is None or l["basin"] == basin)]

    def test_wire_format_only_appended(self):
        original = ["id", "basin", "season", "num", "start", "end", "durH", "n", "peak",
                    "hfN", "hfH", "minP", "minPAt", "minPLat", "minPLon", "lat0", "lon0",
                    "latMax", "deep24", "berg", "bomb", "distNm", "spdKt", "spdMaxKt",
                    "idOk", "timesSuspect", "split", "month", "cls", "noPresN", "glFixes", "fixes"]
        self.assertEqual(tool.LOW_FIELDS[:len(original)], original)
        for name in ("deep24All", "bergAll", "bombAll", "hfDurH", "hfDistNm", "hfSpdKt", "hfSpdMaxKt"):
            self.assertIn(name, tool.LOW_FIELDS[len(original):])

    def test_stored_figures_match_independent_code(self):
        # Both versions of the deepening, recomputed here from the fixes.
        for l in self.lows:
            hf = [f for f in l["fixes"] if f[3] == "HF"]
            for fixes, deep, berg, bomb in ((l["fixes"], "deep24All", "bergAll", "bombAll"),
                                            (hf, "deep24", "berg", "bomb")):
                want = independent_berg(fixes)
                if want is None:
                    self.assertIsNone(l[deep], l["id"])
                    self.assertFalse(l[bomb], l["id"])
                else:
                    self.assertAlmostEqual(l[deep], want[0], delta=0.051, msg=l["id"])
                    self.assertAlmostEqual(l[berg], want[1], delta=0.011, msg=l["id"])
                    self.assertEqual(l[bomb], round(want[1], 2) >= 1.0, l["id"])

    def test_hf_figures_never_exceed_what_the_recorded_track_holds(self):
        # The HF fixes are a subset of the recorded fixes, so the best HF-window
        # deepening can never beat the best recorded-track deepening.
        for l in self.lows:
            if l["deep24"] is not None:
                self.assertIsNotNone(l["deep24All"], l["id"])
                self.assertLessEqual(l["deep24"], l["deep24All"] + 1e-9, l["id"])
            if l["bomb"]:
                self.assertTrue(l["bombAll"], l["id"])
            if l["hfDurH"] is not None:
                self.assertLessEqual(l["hfDurH"], l["durH"], l["id"])
                self.assertLessEqual(l["hfDistNm"], l["distNm"] + 1, l["id"])

    def test_practice_change_is_in_the_data(self):
        # Guard. If the recorded track did not change with the practice, the
        # assertions below would pass trivially.
        b = self.practice["basins"]
        self.assertEqual(b["pac"]["onset"], 2013)
        self.assertEqual(b["atl"]["onset"], 2017)
        self.assertLess(b["atl"]["before"]["lead"], 0.01)
        self.assertGreater(b["atl"]["after"]["lead"], 1.0)
        self.assertGreater(b["pac"]["after"]["lead"], 0.5)
        self.assertGreater(b["pac"]["after"]["trail"], 0.5)

    def test_all_fix_explosive_share_steps_across_2017(self):
        pre = self.share(self.era(2004, SPLIT - 1), "bombAll")
        post = self.share(self.era(SPLIT, 2100), "bombAll")
        self.assertGreater(post - pre, 20.0,
                           "recorded-track share should step up sharply: %.1f -> %.1f" % (pre, post))
        for basin in ("atl", "pac"):
            p0 = self.share(self.era(2004, SPLIT - 1, basin), "bombAll")
            p1 = self.share(self.era(SPLIT, 2100, basin), "bombAll")
            self.assertGreater(p1 - p0, 15.0, basin)

    def test_hf_only_explosive_share_does_not_step_across_2017(self):
        """The point of the fix."""
        all_pre = self.share(self.era(2004, SPLIT - 1), "bombAll")
        all_post = self.share(self.era(SPLIT, 2100), "bombAll")
        pre = self.share(self.era(2004, SPLIT - 1), "bomb")
        post = self.share(self.era(SPLIT, 2100), "bomb")
        step, all_step = post - pre, all_post - all_pre
        # A few points at most (the real residual is ~3), and a small fraction
        # of the step the recorded track shows (~28).
        self.assertLess(abs(step), 5.0, "HF-only share stepped: %.1f -> %.1f" % (pre, post))
        self.assertLess(abs(step), all_step / 4.0)
        # Same in each basin separately, where the practice changed in different years.
        for basin in ("atl", "pac"):
            p0 = self.share(self.era(2004, SPLIT - 1, basin), "bomb")
            p1 = self.share(self.era(SPLIT, 2100, basin), "bomb")
            self.assertLess(abs(p1 - p0), 6.0, "%s: %.1f -> %.1f" % (basin, p0, p1))
        # And the Pacific's own earlier change (2013), which the 2017 split alone
        # would miss: before/after it, within the Pacific.
        pac_a = self.share(self.era(2004, 2012, "pac"), "bomb")
        pac_b = self.share(self.era(2013, 2025, "pac"), "bomb")
        self.assertLess(abs(pac_b - pac_a), 6.0, "Pacific 2013: %.1f -> %.1f" % (pac_a, pac_b))

    def test_season_basin_shares_track_practice_only_on_the_recorded_track(self):
        corr = self.practice["corr"]
        self.assertEqual(corr["n"], 44)
        self.assertGreater(corr["all"], 0.85, "recorded-track share should follow lead fixes")
        self.assertLess(abs(corr["hf"]), 0.5, "HF-only share should not")
        # Recompute from the per-season rows rather than trust the stored r.
        rows = [r for r in self.practice["perSeason"] if r["lead"] is not None]
        xs = [r["lead"] for r in rows]
        for key, bound in (("bombAll", None), ("bombHf", None)):
            ys = [r[key] / r["events"] for r in rows]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            r = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) /
                 math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)))
            self.assertAlmostEqual(r, corr["all"] if key == "bombAll" else corr["hf"], delta=0.001)

    def test_unaffected_quantities_are_unaffected(self):
        # Event counts per season are flat across the split, and the lead/trail
        # change moves neither season assignment nor the pressure minimum.
        per_season = {}
        for l in self.lows:
            if l["season"] >= tool.RECORD_START:
                per_season[l["season"]] = per_season.get(l["season"], 0) + 1
        pre = [n for s, n in per_season.items() if s < SPLIT]
        post = [n for s, n in per_season.items() if s >= SPLIT]
        self.assertLess(abs(sum(post) / len(post) - sum(pre) / len(pre)), 10.0)
        for l in self.lows:
            if l["minP"] is not None:
                self.assertEqual(l["minP"], min(f[4] for f in l["fixes"] if f[4] is not None))

    def test_qc_report_records_the_practice_change(self):
        notes = [n for n in self.payload["qc"]["notes"] if n["kind"] == "practice-change"]
        self.assertEqual(len(notes), 3)           # one per basin + the explosive-share contrast
        report = tool.qc_report(self.payload)
        self.assertIn("practice-change (3)", report)
        self.assertIn("2013-14", report)
        self.assertIn("2017-18", report)
        self.assertLess(report.index("practice-change"), report.index("date-bad"))

    def test_committed_payload_is_current(self):
        """docs/data/hf-lows.json is what the page reads; a stale one would put
        the old, contaminated figures back on screen."""
        with open(os.path.join(ROOT, "docs", "data", "hf-lows.json"), encoding="utf-8") as fh:
            committed = json.load(fh)
        fresh = json.loads(json.dumps(self.payload))
        for k in ("generated", "build"):
            committed.pop(k, None)
            fresh.pop(k, None)
        # Compare the columns the committed payload has. The backfill columns
        # are appended after them (and are null without a precursors file), so
        # a committed payload from before they existed is not stale for lacking
        # them - but every column it does have must still match.
        n = len(committed["lowFields"])
        self.assertEqual(committed["lowFields"], fresh["lowFields"][:n])
        self.assertEqual(committed["lows"], [row[:n] for row in fresh["lows"]],
                         "docs/data/hf-lows.json is stale: run python3 tools/build_hf_lows.py")
        self.assertEqual(committed["practice"], fresh["practice"])


# ---------------------------------------------------------------------------
# Pre-HF backfill
# ---------------------------------------------------------------------------

HEADER = "basin,event_id,valid,lat,lon,pres,warn_cat,source,match_nm,conf"


def valid_str(hours, fmt="iso"):
    d = T0 + timedelta(hours=hours)
    if fmt == "digits":
        return d.strftime("%Y%m%d%H")
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def prow(hours, pres, basin="atl", low_id="2019202001", lat=50.0, lon=-40.0,
         warn="S", source="hsf", match="10", conf="high", fmt="iso"):
    """One precursors.csv line; `hours` is since T0 like make_low()."""
    return ",".join(str(x) for x in (basin, low_id, valid_str(hours, fmt), lat, lon,
                                     "" if pres is None else pres, warn, source, match, conf))


def write_csv(directory, rows, header=HEADER, comments=()):
    path = os.path.join(directory, "precursors.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        for c in comments:
            fh.write("# " + c + "\n")
        fh.write(header + "\n")
        for r in rows:
            fh.write(r + "\n")
    return path


def backfill(lows, rows, **kw):
    """Run a synthetic precursors file through the module -> (lows, qc)."""
    qc = tool.QC()
    with tempfile.TemporaryDirectory() as d:
        records, comments = tool.read_precursors(write_csv(d, rows, **kw), qc)
    tool.attach_backfill(lows, records, qc)
    return lows, qc


def kinds(qc):
    return sorted(n["kind"] for n in qc.notes)


# A storm whose first HF fix is at hour 48. HF fixes at 48/54/60 h; the
# pre-HF record is whatever the test supplies.
HF_TAIL = [(48, 50.0, -40.0, "HF", 976.0), (54, 50.0, -40.0, "HF", 975.0),
           (60, 50.0, -40.0, "HF", 975.0)]


def pre_rows(profile, **kw):
    """profile: {hours since T0: pressure} -> precursor CSV lines."""
    return [prow(h, p, **kw) for h, p in sorted(profile.items())]


# Steepest fall happens well BEFORE onset. Worked by hand (24 h pairs, and
# 18 h pairs scaled by 24/18): 12->30 h is 1006-982 = 24 hPa in 18 h = 32 hPa/24 h,
# which beats every 24-h pair (best 12->36: 28) and every other 18-h pair. It
# ends at hour 30, i.e. 18 h before the first HF fix at hour 48.
EARLY = {0: 1010, 6: 1009, 12: 1006, 18: 998, 24: 990, 30: 982, 36: 978, 42: 977}
# Flat until onset, then the HF segment itself falls fast.
LATE_HF = [(48, 50.0, -40.0, "HF", 990.0), (54, 50.0, -40.0, "HF", 980.0),
           (60, 50.0, -40.0, "HF", 972.0), (66, 50.0, -40.0, "HF", 966.0)]
LATE = {18: 992, 24: 991, 30: 991, 36: 990, 42: 990}


def window_end_hours(fixes_hours_pres):
    """Independent check of the steepest 18-24 h pair's END, in hours: [(h, p)]."""
    best = None
    for i, (ha, pa) in enumerate(fixes_hours_pres):
        for hb, pb in fixes_hours_pres[i + 1:]:
            h = hb - ha
            if h < 18 or h > 24:
                continue
            drop = (pa - pb) * 24.0 / h
            if best is None or drop > best[0]:
                best = (drop, hb)
    return best


class BackfillMechanism(unittest.TestCase):
    """Synthetic storms, one mechanism each."""

    def test_deepRelH_is_negative_when_the_deepening_ended_before_onset(self):
        # The question that motivated the whole exercise. Sign convention:
        # hours of the window END relative to the first HF fix; before = negative.
        low = make_low(HF_TAIL)
        backfill([low], pre_rows(EARLY))
        series = sorted(EARLY.items()) + [(48, 976), (54, 975), (60, 975)]
        drop, end_h = window_end_hours(series)
        self.assertEqual(end_h, 30)
        self.assertEqual(low["deepRelH"], -18, "window ends 18 h BEFORE the first HF fix")
        self.assertEqual(low["deepRelH"], end_h - 48)
        self.assertLess(low["deepRelH"], 0)
        self.assertAlmostEqual(low["deep24Bf"], round(drop, 1))
        self.assertAlmostEqual(low["bergBf"], 32.0 / 24.0 * math.sin(math.radians(60))
                               / math.sin(math.radians(50.0)), places=2)
        self.assertTrue(low["bombBf"])
        # The HF segment alone (976 -> 975, 12 h) has no 24-h window at all:
        # the blindness the backfill exists to cure.
        self.assertIsNone(low["deep24"])

    def test_deepRelH_is_positive_when_the_deepening_is_inside_the_HF_period(self):
        low = make_low(LATE_HF)
        backfill([low], pre_rows(LATE))
        series = sorted(LATE.items()) + [(48, 990), (54, 980), (60, 972), (66, 966)]
        drop, end_h = window_end_hours(series)
        self.assertEqual(low["deepRelH"], end_h - 48)
        self.assertEqual(low["deepRelH"], 18)       # 48 -> 66 h: 24 hPa in 18 h
        self.assertGreater(low["deepRelH"], 0)
        self.assertAlmostEqual(low["deep24Bf"], round(drop, 1))
        self.assertAlmostEqual(low["deep24Bf"], low["deep24"])   # all of it is HF

    def test_bf_is_never_below_the_hf_only_floor(self):
        # Bf's series contains every HF fix, so where both exist Bf >= HF-only.
        low = make_low(LATE_HF)
        backfill([low], pre_rows(LATE))
        self.assertGreaterEqual(low["deep24Bf"], low["deep24"])

    def test_coverage_rule(self):
        def run(profile, hf=HF_TAIL):
            low = make_low(hf)
            backfill([low], pre_rows(profile))
            return low
        # Exactly the minimum: a gapless 24 h behind onset (24..42 + onset 48).
        ok = run({24: 990, 30: 982, 36: 978, 42: 977})
        self.assertIsNotNone(ok["deep24Bf"])
        # Nothing earlier than an 18-h pair fits: the earliest observable end is
        # (18 - lead) h from onset, here -6.
        self.assertEqual(ok["deepRelH"], 18 - 24)
        self.assertEqual(ok["bfLeadH"], 24)
        self.assertGreaterEqual(ok["deepRelH"], 18 - ok["bfLeadH"], "the censoring floor")
        # Six hours short: half-covered, so null - and NOT the HF-only value.
        short = run({30: 982, 36: 978, 42: 977}, hf=LATE_HF)
        self.assertIsNotNone(short["deep24"], "the HF-only figure exists here...")
        for k in ("deep24Bf", "bergBf", "bombBf", "deepRelH"):
            self.assertIsNone(short[k], k + " must be null, not a fallback to the HF-only value")
        self.assertEqual(short["bfLeadH"], 18, "the lead is reported even when it is too short")
        # A missing synoptic fix (no 36 h) breaks the chain even though the
        # record reaches back far enough.
        gap = run({0: 1010, 6: 1009, 12: 1006, 18: 998, 24: 990, 30: 982, 42: 977})
        self.assertEqual(gap["preN"], 7)
        self.assertIsNone(gap["deep24Bf"])
        self.assertEqual(gap["bfLeadH"], 6, "the chain stops at the missing 36 h fix")
        # So does a recovered fix with no pressure: it is not a link in the chain.
        nopres = make_low(HF_TAIL)
        backfill([nopres], pre_rows({0: 1010, 6: 1009, 12: 1006, 18: 998, 24: 990, 30: 982,
                                     36: None, 42: 977}))
        self.assertIsNone(nopres["deep24Bf"])
        # A first HF fix without a pressure has nothing to anchor the chain to.
        anchorless = make_low([(48, 50.0, -40.0, "HF", None)] + HF_TAIL[1:])
        backfill([anchorless], pre_rows(EARLY))
        self.assertIsNone(anchorless["deep24Bf"])
        self.assertEqual(anchorless["bfLeadH"], 0)
        nohf = make_low([(48, 50.0, -40.0, "S", 976.0)])
        backfill([nohf], [])
        self.assertIsNone(nohf["bfLeadH"], "no HF fix, no window, no lead")

    def test_recovered_series_is_separate_and_tagged(self):
        low = make_low(HF_TAIL)
        before = copy.deepcopy(low["fixes"])
        rows = [prow(42, 977, source="hsf", warn="HF"), prow(36, 978, source="era5", warn="S"),
                prow(30, 982, source="hsf", lat=49.5, lon=-41.5, warn="")]
        backfill([low], rows)
        self.assertEqual(low["fixes"], before, "the archive fix list is never touched")
        self.assertEqual(low["n"], 3)
        self.assertEqual(low["preN"], 3)
        self.assertEqual(low["preH"], 18)            # earliest recovered fix, 30 h -> 48 h
        self.assertEqual(low["preSrc"], "mixed")
        fix = [stamp(T0, 30), 49.5, -41.5, 982.0, "", "hsf"]
        self.assertEqual(low["preFixes"][0], fix)    # [date,lat,lon,pres,warn_cat,source], oldest first
        self.assertEqual([f[0] for f in low["preFixes"]], sorted(f[0] for f in low["preFixes"]))
        only_hsf = make_low(HF_TAIL)
        backfill([only_hsf], [prow(42, 977)])
        self.assertEqual(only_hsf["preSrc"], "hsf")
        only_era5 = make_low(HF_TAIL)
        backfill([only_era5], [prow(42, 977, source="era5")])
        self.assertEqual(only_era5["preSrc"], "era5")

    def test_event_without_recovered_rows_is_looked_at_and_empty(self):
        low = make_low(HF_TAIL)
        backfill([low], [])
        self.assertEqual((low["preFixes"], low["preN"], low["preH"], low["preSrc"]),
                         ([], 0, 0, None))
        self.assertIsNone(low["deep24Bf"])

    def test_archive_lead_fixes_count_towards_the_window(self):
        # The recent seasons carry DHF lead fixes of their own. A recovered row
        # landing on one is dropped (archive wins), so the series must include
        # the archive's own fixes in the window or coverage would collapse
        # exactly where the archive is richest.
        archive = [(30, 50.0, -40.0, "DHF", 982.0), (36, 50.0, -40.0, "DHF", 978.0),
                   (42, 50.0, -40.0, "DHF", 977.0), (24, 50.0, -40.0, "DHF", 990.0)] + HF_TAIL
        low = make_low(archive)
        _, qc = backfill([low], pre_rows({30: 982, 36: 978, 42: 977}))
        self.assertEqual(low["preN"], 0)
        self.assertEqual(kinds(qc), ["precursor-duplicate"])
        self.assertIsNotNone(low["deep24Bf"], "the archive's own lead fixes cover the window")
        self.assertEqual(low["deepRelH"], 18 - 24)


class BackfillGuards(unittest.TestCase):
    """Rows that duplicate, contradict, post-date or mis-key an archive fix."""

    def attach(self, rows, low=None, **kw):
        low = low or make_low(HF_TAIL)
        _, qc = backfill([low], rows, **kw)
        return low, qc

    def test_row_after_first_hf_fix_is_rejected(self):
        low, qc = self.attach(pre_rows(EARLY) + [prow(54, 970), prow(66, 970)])
        self.assertEqual(low["preN"], len(EARLY), "post-onset rows are not used")
        late = [n for n in qc.notes if n["kind"] == "precursor-late"]
        self.assertEqual(len(late), 2)
        self.assertIn("6 h after the first HF fix", late[0]["detail"])
        self.assertEqual(qc.counts["precRefused_late"], 2)
        self.assertNotIn(stamp(T0, 66), [f[0] for f in low["preFixes"]])

    def test_row_more_than_72h_before_is_rejected(self):
        low, qc = self.attach([prow(-30, 1000), prow(-24, 1000), prow(42, 977)])
        # first HF is at hour 48: hour -24 is exactly 72 h before (inside), -30 is 78 h.
        self.assertEqual([f[0] for f in low["preFixes"]], [stamp(T0, -24), stamp(T0, 42)])
        self.assertEqual(kinds(qc), ["precursor-early"])

    def test_contradicting_an_archive_fix_never_overrides_it(self):
        archive = [(42, 50.0, -40.0, "DHF", 985.0)] + HF_TAIL
        low = make_low(archive)
        before = copy.deepcopy(low["fixes"])
        _, qc = backfill([low], [prow(42, 960)])        # archive says 985 at 42 h
        self.assertEqual(low["fixes"], before)
        self.assertEqual(low["preN"], 0)
        self.assertEqual(low["preFixes"], [])
        self.assertEqual(kinds(qc), ["precursor-contradiction"])
        detail = qc.notes[0]["detail"]
        self.assertIn("985", detail)
        self.assertIn("960", detail)
        self.assertIn("archive kept", detail)

    def test_position_disagreement_alone_is_a_contradiction(self):
        archive = [(42, 50.0, -40.0, "DHF", 985.0)] + HF_TAIL
        low = make_low(archive)
        _, qc = backfill([low], [prow(42, 985, lat=58.0, lon=-20.0)])
        self.assertEqual(kinds(qc), ["precursor-contradiction"])

    def test_agreeing_duplicate_of_an_archive_fix_is_counted_not_used(self):
        archive = [(42, 50.0, -40.0, "DHF", 985.0)] + HF_TAIL
        low = make_low(archive)
        # Whole-degree HSF position against the archive's finer one, same pressure.
        _, qc = backfill([low], [prow(42, 985, lat=50.0, lon=-39.5)])
        self.assertEqual(low["preN"], 0)
        self.assertEqual(kinds(qc), ["precursor-duplicate"])
        self.assertEqual(qc.counts["precDuplicatesOfArchive"], 1)

    def test_row_at_the_first_hf_fix_collides_with_it(self):
        low, qc = self.attach([prow(48, 960)])
        self.assertEqual(low["preN"], 0)
        self.assertEqual(kinds(qc), ["precursor-contradiction"])

    def test_two_recovered_rows_for_one_time(self):
        low, qc = self.attach([prow(42, 977), prow(42, 977, source="era5")])
        self.assertEqual(low["preN"], 1)
        self.assertEqual(low["preFixes"][0][5], "hsf", "hsf is preferred when they agree")
        self.assertEqual(qc.counts["precDuplicatesOfRecovered"], 1)
        low, qc = self.attach([prow(42, 977), prow(42, 960, source="era5")])
        self.assertEqual(low["preN"], 0, "disagreeing rows: neither can be preferred")
        self.assertEqual(kinds(qc), ["precursor-contradiction", "precursor-contradiction"])

    def test_event_without_an_hf_fix_has_no_window(self):
        low = make_low([(48, 50.0, -40.0, "S", 976.0), (54, 50.0, -40.0, "S", 975.0)])
        low, qc = self.attach([prow(42, 977)], low=low)
        self.assertEqual(low["preN"], 0)
        self.assertEqual(kinds(qc), ["precursor-no-anchor"])
        self.assertIsNone(low["deep24Bf"])

    def test_keys_are_basin_and_event_id(self):
        # "2006200718" exists in both atl and pac in the real archive.
        atl = make_low(HF_TAIL, basin="atl", low_id="2006200718")
        pac = make_low(HF_TAIL, basin="pac", low_id="2006200718")
        _, qc = backfill([atl, pac], [prow(42, 977, basin="pac", low_id="2006200718", lon=-150.0)])
        self.assertEqual((atl["preN"], pac["preN"]), (0, 1))
        self.assertEqual(qc.notes, [])
        _, qc = backfill([atl], [prow(42, 977, basin="pac", low_id="2006200718", lon=-150.0)])
        self.assertEqual(kinds(qc), ["precursor-unknown-event"])

    def test_split_ids_are_not_guessed(self):
        a = make_low(HF_TAIL, low_id="2019202001a")
        b = make_low(HF_TAIL, low_id="2019202001b")
        a["split"] = b["split"] = True
        _, qc = backfill([a, b], [prow(42, 977, low_id="2019202001")])
        self.assertEqual((a["preN"], b["preN"]), (0, 0))
        self.assertEqual(kinds(qc), ["precursor-ambiguous-id"])
        _, qc = backfill([a, b], [prow(42, 977, low_id="2019202001b")])
        self.assertEqual((a["preN"], b["preN"]), (0, 1))

    def test_malformed_rows_are_refused_not_repaired(self):
        bad = [prow(42, 977, basin="indian"),
               prow(42, 977, source="radar"),
               prow(42, 977, conf="great"),
               prow(42, 977, warn="DHF"),
               prow(42, 1200),                         # outside the pressure range
               prow(42, 977, lat="abc"),
               prow(42, 977, match="far"),
               prow(40, 977),                          # 16Z: not a synoptic time
               "atl,2019202001,not-a-date,50,-40,977,S,hsf,10,high",
               prow(42, 977, lat=-50.0)]               # southern hemisphere
        low, qc = self.attach(bad)
        self.assertEqual(low["preN"], 0)
        self.assertEqual(kinds(qc), ["precursor-malformed"] * len(bad))

    def test_low_confidence_is_refused(self):
        low, qc = self.attach([prow(42, 977, conf="low"), prow(36, 978, conf="medium")])
        self.assertEqual(low["preN"], 1)
        self.assertEqual(kinds(qc), ["precursor-low-conf"])

    def test_valid_accepts_iso_and_digits(self):
        low, qc = self.attach([prow(42, 977, fmt="digits"), prow(36, 978, fmt="iso")])
        self.assertEqual(low["preN"], 2)
        self.assertEqual(qc.notes, [])
        self.assertIsNone(tool.parse_valid("2020-01-11T18:30:00Z")["value"])
        self.assertEqual(tool.parse_valid("2020-01-11 18:00")["value"], 2020011118)
        self.assertEqual(tool.parse_valid("2020-01-11T18Z")["value"], 2020011118)

    def test_wrong_header_is_fatal_and_comments_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_csv(d, [], header="basin,event_id,valid,lat,lon")
            with self.assertRaises(SystemExit):
                tool.read_precursors(path, tool.QC())
            path = write_csv(d, [prow(42, 977)], comments=["a comment", "another"])
            records, comments = tool.read_precursors(path, tool.QC())
            self.assertEqual(len(records), 1)
            self.assertEqual(comments, ["a comment", "another"])


class BackfillPayload(unittest.TestCase):
    """The whole build, on the real archive."""

    @classmethod
    def setUpClass(cls):
        cls.base = tool.build(precursors=None)
        fields = cls.base["lowFields"]
        cls.lows = [dict(zip(fields, r)) for r in cls.base["lows"]]

    def hf_event(self, basin, low_id=None, season=None):
        for l in self.lows:
            if (l["basin"] == basin and l["hfN"] and l["n"] == l["hfN"] and l["noPresN"] == 0
                    and (low_id is None or l["id"] == low_id)
                    and (season is None or l["season"] == season)):
                return l
        self.fail("no suitable event")

    def synthetic_file(self, directory, events, comments=()):
        """48 h of 6-hourly precursors for each of `events`, the early-deepening profile."""
        rows = []
        for l in events:
            first = next(f for f in l["fixes"] if f[3] == "HF")
            t0 = tool.to_dt(first[0])
            p0 = first[4]
            for k in range(1, 9):
                d = t0 - timedelta(hours=6 * k)
                pres = int(round(p0 + EARLY[48 - 6 * k] - 976 + 1))
                rows.append(",".join(str(x) for x in (
                    l["basin"], l["id"], d.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    first[1] - 0.4 * k, first[2] - 1.0 * k, pres, "S", "hsf", 12, "high")))
        return write_csv(directory, rows, comments=comments)

    def test_absent_file_changes_nothing(self):
        n = len(tool.LOW_FIELDS) - 9
        self.assertEqual(tool.LOW_FIELDS[n:], ["preFixes", "preN", "preH", "preSrc",
                                              "deep24Bf", "bergBf", "bombBf", "deepRelH",
                                              "bfLeadH"])
        for l in self.lows:
            for k in tool.LOW_FIELDS[n:]:
                self.assertIsNone(l[k], k)
        self.assertIsNone(self.base["backfill"])
        self.assertFalse([k for k in self.base["qc"]["counts"]
                          if k.startswith(("prec", "bf"))])
        self.assertNotIn("Backfill coverage", tool.qc_report(self.base))
        # A path that does not exist is the same as no path.
        with tempfile.TemporaryDirectory() as d:
            missing = tool.build(precursors=os.path.join(d, "nope.csv"))
        missing, base = (json.loads(json.dumps(p)) for p in (missing, self.base))
        for payload in (missing, base):
            for k in ("generated", "build"):
                payload.pop(k)
        self.assertEqual(missing, base)

    def test_present_file_leaves_every_archive_column_alone(self):
        events = [self.hf_event("atl"), self.hf_event("pac")]
        with tempfile.TemporaryDirectory() as d:
            payload = tool.build(precursors=self.synthetic_file(d, events))
        n = len(tool.LOW_FIELDS) - 9
        self.assertEqual([r[:n] for r in payload["lows"]], [r[:n] for r in self.base["lows"]],
                         "backfill must not alter a single archive field, fix list included")
        got = {(l[1], l[0]): dict(zip(payload["lowFields"], l)) for l in payload["lows"]}
        for e in events:
            row = got[(e["basin"], e["id"])]
            self.assertEqual(row["preN"], 8)
            self.assertEqual(row["preH"], 48)
            self.assertEqual(row["preSrc"], "hsf")
            self.assertIsNotNone(row["deep24Bf"])
            self.assertEqual(row["fixes"], e["fixes"])
        # Events the file does not mention were looked at and found empty.
        other = next(r for r in got.values() if r["preN"] == 0)
        self.assertEqual(other["preFixes"], [])

    def test_cross_basin_id_attaches_to_the_right_basin(self):
        atl = next((l for l in self.lows if l["basin"] == "atl" and l["id"] == "2006200718"), None)
        pac = next((l for l in self.lows if l["basin"] == "pac" and l["id"] == "2006200718"), None)
        self.assertTrue(atl and pac, "the id that exists in both basins")
        if not (atl["hfN"] and pac["hfN"]):
            self.skipTest("one of the shared-id events has no HF fix")
        with tempfile.TemporaryDirectory() as d:
            payload = tool.build(precursors=self.synthetic_file(d, [pac]))
        got = {(r[1], r[0]): dict(zip(payload["lowFields"], r)) for r in payload["lows"]}
        self.assertEqual(got[("pac", "2006200718")]["preN"], 8)
        self.assertEqual(got[("atl", "2006200718")]["preN"], 0)

    def test_qc_reports_coverage_by_season_and_basin(self):
        events = [self.hf_event("atl"), self.hf_event("pac")]
        with tempfile.TemporaryDirectory() as d:
            payload = tool.build(precursors=self.synthetic_file(
                d, events, comments=["SYNTHETIC test data"]))
        bf = payload["backfill"]
        self.assertTrue(bf["synthetic"])
        self.assertEqual(bf["minLeadH"], 24)
        usable = {(r["basin"], r["season"]): r["usable"] for r in bf["coverage"]}
        recovered = {(r["basin"], r["season"]): r["recovered"] for r in bf["coverage"]}
        for e in events:
            self.assertGreaterEqual(usable[(e["basin"], e["season"])], 1)
            self.assertGreaterEqual(recovered[(e["basin"], e["season"])], 1)
        fields = payload["lowFields"]
        lows = [dict(zip(fields, r)) for r in payload["lows"]]
        self.assertEqual(sum(usable.values()),
                         sum(1 for l in lows if l["hfN"] and l["deep24Bf"] is not None))
        self.assertEqual(sum(r["events"] for r in bf["coverage"]),
                         sum(1 for l in lows if l["hfN"]))
        report = tool.qc_report(payload)
        self.assertIn("Backfill coverage", report)
        self.assertIn("SYNTHETIC", report)
        self.assertIn("precursor-synthetic", report)
        self.assertEqual(payload["qc"]["counts"]["bfUsable"], sum(usable.values()))

    def test_coverage_collapse_in_a_season_is_a_note(self):
        # A file that recovers nothing at all: every well-populated season-basin
        # is flagged rather than quietly blank.
        with tempfile.TemporaryDirectory() as d:
            payload = tool.build(precursors=write_csv(d, []))
        notes = [n for n in payload["qc"]["notes"] if n["kind"] == "backfill-coverage"]
        self.assertGreater(len(notes), 5)
        self.assertIn("none of", notes[0]["detail"])

    def test_deepening_has_one_code_path(self):
        # All three bases come out of deepening_stats(): feed it the same fixes
        # and the HF-only and Bf figures agree to the last digit.
        low = make_low(LATE_HF)
        backfill([low], pre_rows(LATE))
        hf = tool.deepening_stats([f for f in low["fixes"] if f[3] == "HF"])
        self.assertEqual((low["deep24"], low["berg"], low["bomb"]),
                         (hf["deep24"], hf["berg"], hf["bomb"]))
        self.assertEqual((low["deep24Bf"], low["bergBf"], low["bombBf"]),
                         (hf["deep24"], hf["berg"], hf["bomb"]))


class BackfillCoverageGate(unittest.TestCase):
    """Is Bf coverage uniform across seasons? The risk that remains once Bf is
    allowed to use the archive's own fixes."""

    @staticmethod
    def rows(shares, events=100, basin="atl", first=2004):
        return [{"basin": basin, "season": first + i, "events": events,
                 "recovered": events, "usable": int(round(events * p / 100.0))}
                for i, p in enumerate(shares)]

    def test_ols_against_a_worked_example(self):
        # x = 0..3, y = 1,3,2,5: slope 5.5/5 = 1.1; residual SS 2.7 on 2 df, so
        # se = sqrt(1.35 / 5) = 0.5196.
        slope, se = tool._ols([0, 1, 2, 3], [1, 3, 2, 5])
        self.assertAlmostEqual(slope, 1.1)
        self.assertAlmostEqual(se, math.sqrt(0.27))
        self.assertEqual(tool._ols([0, 1], [1, 2]), (None, None))

    def test_flat_noisy_coverage_does_not_trip(self):
        shares = [50 + (3 if i % 2 else -3) for i in range(20)]
        stats, tripped = tool.coverage_trend(self.rows(shares))
        self.assertEqual(tripped, [])
        self.assertEqual(stats["atl"]["spread"], 6.0)
        self.assertLess(abs(stats["atl"]["slope"]), 2 * stats["atl"]["se"])

    def test_wide_spread_trips(self):
        stats, tripped = tool.coverage_trend(self.rows([20, 25, 30, 45, 25, 30] * 3))
        self.assertEqual(stats["atl"]["spread"], 25.0)
        self.assertTrue(any("spans 25.0 points" in t for t in tripped), tripped)

    def test_a_steady_slope_trips_even_with_a_small_spread(self):
        # 0.5 points per season for 21 seasons is a 10-point spread, under the
        # spread limit, but it is a trend: coverage drifting is what would
        # fabricate a trend in the explosive share.
        shares = [40 + 0.5 * i + (0.4 if i % 2 else -0.4) for i in range(21)]
        stats, tripped = tool.coverage_trend(self.rows(shares))
        self.assertLess(stats["atl"]["spread"], tool.COVERAGE_SPREAD_PTS)
        self.assertAlmostEqual(stats["atl"]["slope"], 0.5, places=1)
        self.assertEqual(len(tripped), 2, "the basin and the pooled series both trip")
        self.assertTrue(all("standard errors from zero" in t for t in tripped), tripped)

    def test_seasons_before_the_period_of_record_are_left_out(self):
        early = self.rows([0], events=1, first=2001)
        stats, tripped = tool.coverage_trend(early + self.rows([50] * 10))
        self.assertEqual(tripped, [])
        self.assertEqual(stats["atl"]["min"], 50.0)

    def test_basins_are_judged_separately_and_pooled(self):
        rows = self.rows([50] * 10) + self.rows([10, 90] * 5, basin="pac")
        stats, tripped = tool.coverage_trend(rows)
        self.assertEqual(set(stats), {"atl", "pac", "all"})
        self.assertTrue(any(t.startswith("pac:") for t in tripped))
        self.assertFalse(any(t.startswith("atl:") for t in tripped))

    def test_covered_vs_uncovered_selection(self):
        def ev(basin, min_p, lat, usable):
            return {"basin": basin, "season": 2010, "hfN": 2, "minP": min_p,
                    "fixes": [[2010010100, lat - 5.0, -40.0, "DHF", 1000.0],
                              [2010010106, lat, -40.0, "HF", min_p]],
                    "deep24Bf": 20.0 if usable else None}
        lows = [ev("atl", 950.0, 60.0, True), ev("atl", 960.0, 58.0, True),
                ev("atl", 990.0, 50.0, False), ev("atl", 980.0, 48.0, False),
                ev("pac", 970.0, 45.0, True),
                dict(ev("atl", 900.0, 70.0, True), hfN=0)]           # no HF fix: not counted
        sel = tool.coverage_selection(lows)
        self.assertEqual(sel["atl"]["covered"], {"n": 2, "medianMinP": 955.0, "medianLat": 59.0})
        self.assertEqual(sel["atl"]["uncovered"], {"n": 2, "medianMinP": 985.0, "medianLat": 49.0})
        self.assertEqual(sel["all"]["covered"]["n"], 3)
        self.assertEqual(sel["pac"]["uncovered"], {"n": 0, "medianMinP": None, "medianLat": None})

    def test_flag_and_note_in_a_whole_build(self):
        # Recover only the recent half of the record: coverage is wildly uneven.
        base = tool.build(precursors=None)
        lows = [dict(zip(base["lowFields"], r)) for r in base["lows"]]
        recent = [l for l in lows if l["hfN"] and l["season"] >= 2014
                  and next(f for f in l["fixes"] if f[3] == "HF")[4] is not None
                  and l["id"] not in {x["id"] for x in lows if x["id"].endswith(("a", "b"))}]
        helper = BackfillPayload(methodName="test_absent_file_changes_nothing")
        with tempfile.TemporaryDirectory() as d:
            path = helper.synthetic_file(d, recent)
            payload = tool.build(precursors=path)
        bf = payload["backfill"]
        self.assertTrue(bf["coverageTrend"])
        self.assertTrue(bf["coverageTrendWhy"])
        notes = [n for n in payload["qc"]["notes"] if n["kind"] == "backfill-coverage-trend"]
        self.assertEqual(len(notes), 1)
        self.assertIn("not safe to compare across seasons", notes[0]["detail"])
        report = tool.qc_report(payload)
        self.assertIn("COVERAGE TREND", report)
        self.assertIn("Coverage uniformity", report)
        self.assertIn("Covered vs uncovered", report)
        # The flag suppresses nothing: Bf values are still emitted.
        out = [dict(zip(payload["lowFields"], r)) for r in payload["lows"]]
        self.assertTrue(any(l["deep24Bf"] is not None for l in out))
        self.assertTrue(all(l["bfLeadH"] is not None for l in out if l["hfN"]))
        self.assertTrue(all(l["bfLeadH"] is None for l in out if not l["hfN"]))
        self.assertEqual(bf["selection"]["all"]["covered"]["n"]
                         + bf["selection"]["all"]["uncovered"]["n"],
                         sum(1 for l in out if l["hfN"] and l["season"] >= tool.RECORD_START))


if __name__ == "__main__":
    unittest.main(verbosity=2)
