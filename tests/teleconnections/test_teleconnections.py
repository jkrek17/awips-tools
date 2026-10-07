#!/usr/bin/env python3
"""Checks for tools/build_teleconnections.py and the data it emits.

Two halves:
  * the emitted docs/data/teleconnections.json - schema, no sentinels leaked,
    dates dense and consistent, JS wrapper identical to the JSON;
  * the parsers, against small SYNTHETIC fixtures written below (the RMM one
    follows the format as described in the task - two header lines, then
    'year month day RMM1 RMM2 phase amplitude method' - not a copy of the real
    BoM file, which this repo's build could not download when this test was
    written).

    python3 tests/teleconnections/test_teleconnections.py
"""
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
JSON_PATH = os.path.join(ROOT, "docs", "data", "teleconnections.json")
JS_PATH = os.path.join(ROOT, "docs", "data", "teleconnections.js")

spec = importlib.util.spec_from_file_location(
    "build_teleconnections", os.path.join(ROOT, "tools", "build_teleconnections.py"))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

SENTINELS = (-99.0, -999.0, -99.9, 1e36, 999.0)
DAILY = ("nao", "pna", "ao")


def parse_date(s):
    return dt.date.fromisoformat(s)


class EmittedData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(JSON_PATH, encoding="utf-8") as fh:
            cls.d = json.load(fh)

    def test_top_level_schema(self):
        d = self.d
        self.assertEqual(d["schema"], tool.SCHEMA_VERSION)
        for k in ("note", "derived", "start", "oni", "nao", "pna", "ao", "mjo"):
            self.assertIn(k, d)
        for k in ("mean5", "mjoLag", "dayIndex"):
            self.assertIn(k, d["derived"])

    def test_provenance_on_every_block(self):
        for k in ("oni", "nao", "pna", "ao", "mjo"):
            b = self.d[k]
            for f in ("source", "url", "license"):
                self.assertTrue(b.get(f), f"{k}.{f}")
            self.assertTrue(b["url"].startswith("https://"))
        for k in ("oni", "nao", "pna", "ao"):
            self.assertTrue(re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.d[k]["retrieved"]))
        # BoM licence must stay flagged until someone actually confirms it.
        self.assertIn("UNCONFIRMED", self.d["mjo"]["license"])

    def test_daily_dense_and_ends_consistent(self):
        for k in DAILY:
            b = self.d[k]
            start, end = parse_date(b["start"]), parse_date(b["end"])
            self.assertLess(start, end)
            self.assertEqual(len(b["values"]), b["n"])
            # one slot per calendar day: with no gaps or repeats possible,
            # dates are monotonic by construction iff end - start + 1 == n.
            self.assertEqual((end - start).days + 1, b["n"], k)
            self.assertEqual(b["missing"], sum(v is None for v in b["values"]))
            self.assertGreaterEqual(start, parse_date(self.d["start"]))

    def test_daily_series_share_a_span(self):
        spans = {(self.d[k]["start"], self.d[k]["end"]) for k in DAILY}
        self.assertEqual(len(spans), 1, spans)

    def test_no_sentinels_leaked(self):
        for k in DAILY:
            for v in self.d[k]["values"]:
                if v is not None:
                    self.assertIsInstance(v, float)
                    self.assertLess(abs(v), tool.CPC_PLAUSIBLE_ABS)
                    self.assertNotIn(v, SENTINELS)
        for v in self.d["oni"]["values"]:
            if v is not None:
                self.assertLess(abs(v), 10)
        m = self.d["mjo"]
        if m["available"]:
            for key in ("rmm1", "rmm2", "amp"):
                for v in m[key]:
                    if v is not None:
                        self.assertLess(abs(v), 50, key)
            for v in m["phase"]:
                self.assertTrue(v is None or v in range(1, 9))

    def test_oni(self):
        o = self.d["oni"]
        n = o["n"]
        for key in ("seas", "values", "phases", "episodes"):
            self.assertEqual(len(o[key]), n, key)
        sy, sm = map(int, o["start"].split("-"))
        ey, em = map(int, o["end"].split("-"))
        self.assertEqual((ey * 12 + em) - (sy * 12 + sm) + 1, n)
        for i, (v, p) in enumerate(zip(o["values"], o["phases"])):
            self.assertEqual(p, tool.phase_of(v))
            month = (sm - 1 + i) % 12 + 1
            self.assertEqual(o["seas"][i], tool.ONI_SEASONS[month - 1])
        self.assertTrue(all(e in (0, 1, None) for e in o["episodes"]))

    def test_known_enso_events(self):
        o = self.d["oni"]
        sy, sm = map(int, o["start"].split("-"))

        def at(year, month):
            i = (year - sy) * 12 + (month - sm)
            return o["seas"][i], o["values"][i], o["phases"][i], o["episodes"][i]
        seas, v, p, ep = at(2016, 1)          # 2015-16 El Nino peak
        self.assertEqual((seas, p, ep), ("DJF", "E", 1))
        self.assertGreater(v, 2.3)
        seas, v, p, ep = at(2011, 1)          # 2010-11 La Nina
        self.assertEqual((seas, p, ep), ("DJF", "L", 1))
        self.assertLess(v, -1.2)

    def test_mjo_block(self):
        m = self.d["mjo"]
        if not m["available"]:
            self.assertTrue(m["reason"])
            self.assertIn("coverageNote", m)
            for key in ("rmm1", "phase", "epoch", "noDataAfter"):
                self.assertNotIn(key, m)
            return
        start, end = parse_date(m["start"]), parse_date(m["end"])
        self.assertEqual((end - start).days + 1, m["n"])
        for key in ("rmm1", "rmm2", "phase", "amp", "epoch"):
            self.assertEqual(len(m[key]), m["n"], key)
        self.assertEqual(m["noDataAfter"], m["end"])
        self.assertLess(end, parse_date(self.d["nao"]["end"]))   # RMM must not be padded to the CPC end
        self.assertIsNotNone(m["phase"][-1])                      # last slot is real data, not a null tail
        ids = [e["id"] for e in m["epochs"]]
        self.assertEqual(ids, list(range(len(ids))))
        for i in range(m["n"]):
            valid = m["phase"][i] is not None
            self.assertEqual(valid, m["epoch"][i] is not None)
            if valid:
                self.assertIn(m["epoch"][i], ids)

    def test_js_wrapper_matches_json(self):
        with open(JS_PATH, encoding="utf-8") as fh:
            text = fh.read()
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("/* generated by tools/build_teleconnections.py"))
        body = text[text.index("window.HF_TELECONNECTIONS = ") + len("window.HF_TELECONNECTIONS = "):]
        self.assertEqual(json.loads(body.rstrip().rstrip(";")), self.d)


CPC_FIXTURE = """\
2006 10 25  0.500
2006 10 26-99.000
2006 10 27  1.250
2006 10 28 -0.250
"""

RMM_FIXTURE = """\
SYNTHETIC FIXTURE - not BoM data
year, month, day, RMM1, RMM2, phase, amplitude, 19740601-20131231: both SST1 and 120-day mean removed; 20140101-: only 120-day removed
2013 12 30  0.50  0.60  6  0.78  WH04_method
2013 12 31  1.00 -1.00  8  1.41  WH04_method
2014  1  1  1.20  0.10  5  1.20  Gottschalk10_method
2014  1  2  1.E36 1.E36 999 1.E36 Gottschalk10_method
2014  1  3  0.30  0.40  7  0.50  Gottschalk10_method
2014  1  4  1.E36 1.E36 999 1.E36 Gottschalk10_method
2014  1  5  1.E36 1.E36 999 1.E36 Gottschalk10_method
"""


class Parsers(unittest.TestCase):
    def test_cpc_fused_negative_field(self):
        rows, sent = tool.parse_cpc_daily(CPC_FIXTURE, "t")
        self.assertEqual([v for _d, v in rows], [0.5, None, 1.25, -0.25])
        self.assertEqual(dict(sent), {"-99.000": 1})

    def test_cpc_gap_is_an_error(self):
        with self.assertRaises(RuntimeError):
            tool.parse_cpc_daily("2006 10 25 0.1\n2006 10 27 0.2\n", "t")

    def test_cpc_implausible_value_is_an_error(self):
        with self.assertRaises(RuntimeError):
            tool.parse_cpc_daily("2006 10 25 55.0\n", "t")

    def test_rmm_epochs_and_trailing_trim(self):
        header, rows, sent = tool.parse_rmm(RMM_FIXTURE)
        self.assertEqual(len(header), 2)
        block, info = tool.build_mjo(header, rows, sent, dt.date(2013, 12, 30), "2026-01-01", "fixture")
        self.assertEqual([e["name"] for e in block["epochs"]], ["WH04", "Gottschalk10"])
        self.assertEqual(block["epochs"][1]["start"], "2014-01-01")
        self.assertEqual(block["end"], "2014-01-03")          # trailing sentinel rows trimmed
        self.assertEqual(block["noDataAfter"], "2014-01-03")
        self.assertEqual(block["phase"], [6, 8, 5, None, 7])   # interior sentinel -> null
        self.assertEqual(block["epoch"], [0, 0, 1, None, 1])
        self.assertEqual(info["trailingMissingRows"], 2)
        # the fixture is a truncated file, so only the 1974 start is off; the
        # 2013-12-31 / 2014-01-01 boundary matches the header and must not warn.
        self.assertEqual(info["boundaryWarnings"],
                         ["WH04 starts 2013-12-30, header says 1974-06-01"])
        self.assertEqual(dict(sent), {"1.E36": 9, "999": 3})

    def test_rmm_unknown_method_is_an_error(self):
        with self.assertRaises(RuntimeError):
            tool.parse_rmm("2015 1 1 0.5 0.5 5 0.7 SomeNewMethod\n")

    def test_oni_episode_flags(self):
        ph = ["N", "E", "E", "E", "E", "E", "N", "L", "L", "N", "E", "E"]
        self.assertEqual(tool.episode_flags(ph), [0, 1, 1, 1, 1, 1, 0, 0, 0, 0, None, None])
        self.assertEqual(tool.phase_of(0.5), "E")
        self.assertEqual(tool.phase_of(-0.5), "L")
        self.assertEqual(tool.phase_of(0.49), "N")

    def test_oni_season_centre_mapping(self):
        rows = tool.parse_oni(" SEAS  YR   TOTAL   ANOM\n  NDJ 2015 27.0 2.0\n  DJF 2016 27.0 2.5\n")
        self.assertEqual([(y, m) for y, m, _v in rows], [(2015, 12), (2016, 1)])

    def test_season_boundary_is_1_june(self):
        self.assertEqual(tool.season_label(dt.date(2002, 5, 31)), 2001)
        self.assertEqual(tool.season_label(dt.date(2002, 6, 1)), 2002)


if __name__ == "__main__":
    unittest.main(verbosity=2)
