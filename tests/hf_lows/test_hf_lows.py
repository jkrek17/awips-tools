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

    python3 tests/hf_lows/test_hf_lows.py
"""
import importlib.util
import json
import math
import os
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


def make_low(spec_rows):
    """spec_rows: [(hours since T0, lat, lon, cat, pres)] -> a derived low."""
    low = {"basin": "atl", "id": "2019202001", "season": 2019, "num": 1, "idOk": True,
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
        cls.payload = tool.build()
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
        self.assertEqual(committed["lowFields"], fresh["lowFields"])
        self.assertEqual(committed["lows"], fresh["lows"],
                         "docs/data/hf-lows.json is stale: run python3 tools/build_hf_lows.py")
        self.assertEqual(committed["practice"], fresh["practice"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
