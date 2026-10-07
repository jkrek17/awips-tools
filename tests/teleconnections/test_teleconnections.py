#!/usr/bin/env python3
"""Checks for tools/build_teleconnections.py and the data it emits.

Two halves:
  * the emitted docs/data/teleconnections.json - schema, no sentinels leaked,
    dates dense/monotonic, JS wrapper identical to the JSON;
  * the parsers and the MJO sign-convention check, against small SYNTHETIC
    fixtures written below (the pentad fixture follows the real CPC file's
    layout - out-of-order INDEX_n header over a PENTAD/longitude line, "*****"
    missing cells, trailing pre-allocated rows, a 6-day step across a leap
    day - but the numbers are invented).

    python3 tests/teleconnections/test_teleconnections.py
"""
import datetime as dt
import importlib.util
import json
import math
import os
import random
import re
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
LONS_EAST = ["20E", "70E", "80E", "100E", "120E", "140E", "160E", "120W", "40W", "10W"]


def parse_date(s):
    return dt.date.fromisoformat(s)


def int_date(n):
    return dt.datetime.strptime(str(n), "%Y%m%d").date()


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
        for k in ("mean5", "mjoRow", "mjoLag", "mjoNotRmm", "dayIndex"):
            self.assertIn(k, d["derived"])

    def test_provenance_and_public_domain_on_every_block(self):
        for k in ("oni", "nao", "pna", "ao", "mjo"):
            b = self.d[k]
            for f in ("source", "url", "license", "attribution"):
                self.assertTrue(b.get(f), f"{k}.{f}")
            self.assertTrue(b["url"].startswith("https://"))
            self.assertRegex(b["retrieved"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertIn("public domain", b["license"])
            self.assertNotIn("UNCONFIRMED", b["license"])
            self.assertIn("cpc.ncep.noaa.gov", b["url"])      # no non-NOAA source

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
        for lon, vals in self.d["mjo"]["series"].items():
            for v in vals:
                if v is not None:
                    self.assertIsInstance(v, float, lon)
                    self.assertLess(abs(v), tool.MJO_PLAUSIBLE_ABS)
                    self.assertNotIn(v, SENTINELS)

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
        self.assertEqual(m["cadence"], "pentad")
        # Not RMM: none of the RMM fields exist, and the payload says so. The locally
        # derived pair is deliberately named eofPhase / eofAmplitude, never phase / amp /
        # amplitude, so a consumer cannot mistake it for RMM by key name.
        for key in ("phase", "amp", "amplitude", "rmm1", "rmm2", "epoch", "epochs"):
            self.assertNotIn(key, m)
        self.assertIn("NOT the Wheeler-Hendon", m["notRmm"])
        self.assertIn("pentad", m["pentadLabel"].lower())
        # keyed by longitude, eastward, every column present once
        self.assertEqual(m["longitudes"], LONS_EAST)
        self.assertEqual(sorted(m["series"]), sorted(LONS_EAST))
        self.assertEqual(sorted(c["lon"] for c in m["sourceColumns"]), sorted(LONS_EAST))
        self.assertEqual([m["lonDegE"][l] for l in LONS_EAST],
                         [20, 70, 80, 100, 120, 140, 160, 240, 320, 350])
        # explicit, strictly increasing pentad-centre dates: 5-day steps, 6 across a leap day
        dates = [int_date(n) for n in m["dates"]]
        self.assertEqual(len(dates), m["n"])
        self.assertEqual(dates[0], parse_date(m["start"]))
        self.assertEqual(dates[-1], parse_date(m["end"]))
        for a, b in zip(dates, dates[1:]):
            leap_step = (a.month, a.day, b.month, b.day) == (2, 27, 3, 4) and a.year % 4 == 0
            self.assertEqual((b - a).days, 6 if leap_step else 5, (a, b))
        for d in dates:
            self.assertTrue(tool.pentad_centre_ok(d), d)
        for lon, vals in m["series"].items():
            self.assertEqual(len(vals), m["n"], lon)
        # coverage end marked explicitly; arrays not padded with a null tail
        self.assertEqual(m["noDataAfter"], m["end"])
        self.assertIn("No MJO data after", m["coverageNote"])
        self.assertLess(parse_date(m["end"]), parse_date("2026-12-01"))
        self.assertTrue(any(m["series"][l][-1] is not None for l in LONS_EAST))
        self.assertEqual(m["missing"],
                         sum(all(m["series"][l][i] is None for l in LONS_EAST) for i in range(m["n"])))

    def test_mjo_convention_stated_and_evidenced(self):
        m = self.d["mjo"]
        self.assertEqual(m["convention"], tool.MJO_CONVENTION)
        ev = m["conventionEvidence"]
        self.assertGreater(ev["enso"]["meanR100E_140E"], tool.MJO_ENSO_MIN_MEAN_R)
        self.assertEqual(sorted(ev["enso"]["r"]), sorted(LONS_EAST))
        p = ev["propagation"]
        self.assertEqual(p["negative"], 0)
        self.assertEqual(p["positive"] + p["zero"] + p["negative"], len(p["pairs"]))
        self.assertGreaterEqual(p["positive"] / len(p["pairs"]), tool.MJO_PAIR_MIN_POSITIVE_FRAC)

    # --- derived EOF phase space (mjo.eof / eofPhase / eofAmplitude) --------

    def test_eof_provenance_present(self):
        m = self.d["mjo"]
        e = m["eof"]
        for k in ("notRmm", "method", "pcFormula", "decomposition", "means", "eigenvalues", "totalVariance",
                  "varianceExplainedPct", "loadings", "pcStd", "signConvention", "phaseConvention",
                  "validation"):
            self.assertIn(k, e, k)
        self.assertEqual(e["longitudes"], LONS_EAST)
        for k in ("eof1", "eof2"):
            self.assertEqual(sorted(e["loadings"][k]), sorted(LONS_EAST), k)
            self.assertAlmostEqual(sum(v * v for v in e["loadings"][k].values()), 1.0, places=4)
        self.assertAlmostEqual(sum(a * b for a, b in zip(e["loadings"]["eof1"].values(),
                                                         e["loadings"]["eof2"].values())), 0.0, places=4)
        self.assertEqual(sorted(e["means"]), sorted(LONS_EAST))
        self.assertEqual(len(e["varianceExplainedPct"]), 3)
        self.assertEqual(len(e["eigenvalues"]), 3)
        self.assertGreater(e["pcStd"]["pc1"], 0)
        self.assertGreater(e["pcStd"]["pc2"], 0)
        self.assertIn(e["signConvention"]["pc2Sign"], (-1, 1))
        self.assertTrue(e["signConvention"]["why"])
        # decomposition = pentads with all ten longitudes present, and nothing else
        full = [i for i in range(m["n"]) if all(m["series"][l][i] is not None for l in LONS_EAST)]
        self.assertEqual(e["decomposition"]["pentads"], len(full))
        self.assertEqual(e["decomposition"]["of"], m["n"])
        self.assertEqual(e["decomposition"]["first"], m["dates"][full[0]])
        self.assertEqual(e["decomposition"]["last"], m["dates"][full[-1]])

    def test_eof_states_it_is_not_rmm(self):
        m = self.d["mjo"]
        self.assertIn("NOT the Wheeler-Hendon", m["notRmm"])           # the existing flag survives
        self.assertIn("NOT the Wheeler-Hendon", m["eof"]["notRmm"])
        self.assertIn("DERIVED LOCALLY", m["eof"]["notRmm"])
        self.assertIn("not an octant", m["eof"]["notRmm"])
        # a continuous angle: no octant / phase-number field anywhere in the block
        for key in m["eof"]:
            self.assertNotRegex(key.lower(), r"octant|rmm1|rmm2")
        self.assertNotIn("octant", [k.lower() for k in m])

    def test_eof_phase_convention_is_spelled_out(self):
        c = self.d["mjo"]["eof"]["phaseConvention"]
        self.assertIn("EASTWARD", c["advances"])
        self.assertIn("radians", c["units"])
        self.assertIn("enhanced convection", c["phase0"])
        self.assertTrue(0 <= c["phase0ConvectionLonDegE"] < 360)
        t = c["convectionLonByPhase"]
        self.assertEqual(len(t["phaseDeg"]), len(t["convectionLonDegE"]))
        self.assertEqual(t["phaseDeg"], list(range(0, 360, tool.MJO_EOF_TABLE_STEP_DEG)))
        self.assertEqual(len(t["phaseDeg"]), 12)      # 30-degree steps, not eight octants
        self.assertEqual(t["convectionLonDegE"][0], c["phase0ConvectionLonDegE"])
        # the table is the emitted proof of "eastward": every step east, one full circuit
        lon = t["convectionLonDegE"]
        steps = [(lon[(k + 1) % len(lon)] - lon[k] + 180) % 360 - 180 for k in range(len(lon))]
        self.assertTrue(all(0 < s < 180 for s in steps), steps)
        self.assertAlmostEqual(sum(steps), 360.0, delta=1e-6)

    def test_eof_arrays_align_with_dates(self):
        m = self.d["mjo"]
        self.assertEqual(len(m["eofPhase"]), len(m["dates"]))
        self.assertEqual(len(m["eofAmplitude"]), len(m["dates"]))

    def test_eof_nulls_line_up_with_null_series_rows(self):
        m = self.d["mjo"]
        nulls = 0
        for i in range(m["n"]):
            any_null = any(m["series"][l][i] is None for l in LONS_EAST)
            self.assertEqual(m["eofPhase"][i] is None, any_null, i)
            self.assertEqual(m["eofAmplitude"][i] is None, any_null, i)
            nulls += any_null
        self.assertGreater(nulls, 0)                     # the real record has missing pentads
        self.assertEqual(nulls, m["missing"])            # ...and none of them got a value
        self.assertEqual(sum(v is not None for v in m["eofPhase"]), m["eof"]["decomposition"]["pentads"])

    def test_eof_amplitude_non_negative_and_phase_in_range(self):
        m = self.d["mjo"]
        for a in m["eofAmplitude"]:
            if a is not None:
                self.assertIsInstance(a, float)
                self.assertGreaterEqual(a, 0.0)
        for ph in m["eofPhase"]:
            if ph is not None:
                self.assertIsInstance(ph, float)
                self.assertGreaterEqual(ph, -math.pi)
                self.assertLessEqual(ph, math.pi)

    def test_eof_reproducible_from_the_payload_alone(self):
        """Recompute phase and amplitude for every pentad from nothing but the
        emitted series, means, loadings, pcStd and pc2Sign."""
        m = self.d["mjo"]
        e = m["eof"]
        l1, l2, mean = e["loadings"]["eof1"], e["loadings"]["eof2"], e["means"]
        sgn = e["signConvention"]["pc2Sign"]
        for i in range(m["n"]):
            if m["eofPhase"][i] is None:
                continue
            x = {l: m["series"][l][i] - mean[l] for l in LONS_EAST}
            z1 = sum(l1[l] * x[l] for l in LONS_EAST) / e["pcStd"]["pc1"]
            z2 = sum(l2[l] * x[l] for l in LONS_EAST) / e["pcStd"]["pc2"]
            dphi = (math.atan2(sgn * z2, z1) - m["eofPhase"][i] + math.pi) % (2 * math.pi) - math.pi
            self.assertLess(abs(dphi), 1e-4, i)
            self.assertAlmostEqual(math.hypot(z1, z2), m["eofAmplitude"][i], delta=1e-3)

    def test_eof_validation_recorded_and_inside_thresholds(self):
        v = self.d["mjo"]["eof"]["validation"]
        e = self.d["mjo"]["eof"]
        self.assertGreaterEqual(e["variance12Pct"], 100 * tool.MJO_EOF_MIN_VAR12)
        self.assertGreaterEqual(e["pairRatio"], tool.MJO_EOF_MIN_PAIR_RATIO)
        lo, hi = tool.MJO_EOF_PERIOD_BAND_DAYS
        self.assertTrue(lo <= v["periodDays"]["value"] <= hi)
        self.assertGreater(v["medianAdvanceDegPerPentad"], 0)               # eastward
        self.assertGreaterEqual(v["forwardStepFraction"]["value"], tool.MJO_EOF_MIN_FORWARD_FRAC)
        self.assertGreater(v["patternEastwardNetDeg"], 180)
        # the near-equal pair and negligible third mode that make it a wave
        a, b, c = e["varianceExplainedPct"]
        self.assertGreater(a + b, 90)
        self.assertLess(c, 5)
        # the phase series itself advances eastward: forward steps dominate, measured on the
        # emitted phase and amplitude (not on the build's internal numbers)
        m = self.d["mjo"]
        fwd = tot = 0
        for i in range(m["n"] - 1):
            if all(m[k][j] is not None for k in ("eofPhase", "eofAmplitude") for j in (i, i + 1)) \
                    and min(m["eofAmplitude"][i], m["eofAmplitude"][i + 1]) >= 1.0:
                d = (m["eofPhase"][i + 1] - m["eofPhase"][i] + math.pi) % (2 * math.pi) - math.pi
                fwd += d > 0
                tot += 1
        self.assertGreater(tot, 500)
        self.assertGreater(fwd / tot, 0.8)

    def test_eof_does_not_alter_existing_mjo_arrays(self):
        m = self.d["mjo"]
        self.assertEqual(m["n"], len(m["dates"]))
        for lon in LONS_EAST:
            self.assertEqual(len(m["series"][lon]), m["n"])

    def test_pentad_lookup_rule(self):
        m = self.d["mjo"]
        labels = [int_date(n) for n in m["dates"]]
        for d in (parse_date("2003-01-01"), parse_date("2016-02-29"), parse_date("2020-12-31"),
                  parse_date("2011-03-01")):
            i = tool.pentad_row(labels, d)
            self.assertLessEqual(abs((labels[i] - d).days), 3, d)
            if i + 1 < len(labels):
                self.assertGreater(labels[i + 1] - dt.timedelta(days=2), d)   # next row starts after d

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

# Header in the real file's NON-numeric order. Rows: a normal one, one
# across the leap-day 6-day step (Feb 27 -> Mar 4 2024), an all-missing
# interior row, then trailing pre-allocated rows.
PENTAD_FIXTURE = """\
           INDEX_9  INDEX_1  INDEX_2
 PENTAD       20E      80E     100E
20240222     0.10     0.20     0.30
20240227    -0.10    -0.20    -0.30
20240304    *****    *****    *****
20240309     1.50     *****     2.50
20240314    *****    *****    *****
20240319    *****    *****    *****
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

    def test_mjo_header_order_missing_and_leap_step(self):
        columns, rows = tool.parse_mjo(PENTAD_FIXTURE)
        # mapping comes from the header, not from column position
        self.assertEqual([(c["index"], c["lon"]) for c in columns],
                         [(9, "20E"), (1, "80E"), (2, "100E")])
        self.assertEqual([d.isoformat() for d, _ in rows],
                         ["2024-02-22", "2024-02-27", "2024-03-04", "2024-03-09",
                          "2024-03-14", "2024-03-19"])
        self.assertEqual(rows[0][1], [0.10, 0.20, 0.30])
        self.assertEqual(rows[2][1], [None, None, None])
        self.assertEqual(rows[3][1], [1.50, None, 2.50])

    def test_mjo_keyed_by_longitude_and_trailing_trim(self):
        columns, rows = tool.parse_mjo(PENTAD_FIXTURE)
        m, info = tool.build_mjo(columns, rows, {}, dt.date(2024, 2, 20), "2026-01-01")
        self.assertEqual(m["end"], "2024-03-09")                 # trailing "*****" rows trimmed
        self.assertEqual(m["noDataAfter"], "2024-03-09")
        self.assertEqual(info["trailingMissingRows"], 2)
        self.assertEqual(m["dates"], [20240222, 20240227, 20240304, 20240309])
        self.assertEqual(m["longitudes"], ["20E", "80E", "100E"])
        self.assertEqual(m["series"]["20E"], [0.10, -0.10, None, 1.50])
        self.assertEqual(m["series"]["80E"], [0.20, -0.20, None, None])   # interior and cell nulls kept
        self.assertEqual(m["series"]["100E"], [0.30, -0.30, None, 2.50])
        self.assertEqual(info["interiorMissing"], ["2024-03-04"])
        self.assertEqual(m["missing"], 1)

    def test_mjo_reordered_header_gives_same_series(self):
        swapped = PENTAD_FIXTURE.replace("INDEX_9  INDEX_1  INDEX_2", "INDEX_2  INDEX_9  INDEX_1") \
                                .replace("20E      80E     100E", "100E      20E      80E")
        lines = swapped.splitlines()
        out = lines[:2]
        for ln in lines[2:]:
            p = ln.split()
            out.append(" ".join([p[0], p[3], p[1], p[2]]))      # reorder data columns to match
        c1, r1 = tool.parse_mjo(PENTAD_FIXTURE)
        c2, r2 = tool.parse_mjo("\n".join(out) + "\n")
        m1, _ = tool.build_mjo(c1, r1, {}, dt.date(2024, 2, 20), "x")
        m2, _ = tool.build_mjo(c2, r2, {}, dt.date(2024, 2, 20), "x")
        self.assertEqual(m1["series"], m2["series"])
        self.assertEqual(m1["longitudes"], m2["longitudes"])

    def test_mjo_bad_inputs_are_errors(self):
        head = PENTAD_FIXTURE.splitlines()[:2]
        bad = {
            "label not a pentad centre": head + ["20240223 0.1 0.2 0.3"],
            "wrong step": head + ["20240222 0.1 0.2 0.3", "20240309 0.1 0.2 0.3"],
            "implausible value": head + ["20240222 99.0 0.2 0.3"],
            "wrong column count": head + ["20240222 0.1 0.2"],
            "duplicate longitude": [head[0], " PENTAD 20E 20E 100E", "20240222 0.1 0.2 0.3"],
            "header length mismatch": [head[0], " PENTAD 20E 80E", "20240222 0.1 0.2"],
        }
        for name, lines in bad.items():
            with self.subTest(name), self.assertRaises(RuntimeError):
                tool.parse_mjo("\n".join(lines) + "\n")

    def test_pentad_centre_rule(self):
        for s in ("2023-01-03", "2023-12-29", "2024-02-27", "2024-03-04", "2023-03-04"):
            self.assertTrue(tool.pentad_centre_ok(parse_date(s)), s)
        for s in ("2024-02-29", "2024-03-05", "2023-01-04"):
            self.assertFalse(tool.pentad_centre_ok(parse_date(s)), s)

    def test_pentad_row_lookup(self):
        labels = [parse_date(s) for s in ("2023-01-03", "2023-01-08", "2023-01-13")]
        self.assertEqual(tool.pentad_row(labels, parse_date("2023-01-01")), 0)
        self.assertEqual(tool.pentad_row(labels, parse_date("2023-01-05")), 0)
        self.assertEqual(tool.pentad_row(labels, parse_date("2023-01-06")), 1)
        self.assertEqual(tool.pentad_row(labels, parse_date("2023-01-10")), 1)
        self.assertEqual(tool.pentad_row(labels, parse_date("2023-01-11")), 2)
        self.assertIsNone(tool.pentad_row(labels, parse_date("2022-12-25")))

    # --- sign-convention check, on a synthetic eastward wave -------------

    @staticmethod
    def synthetic(enso_sign):
        """Ten years of pentad rows: an eastward-travelling wave (period 9
        pentads) in every column, plus an ENSO-tied slow component at
        100E/120E/140E whose sign is enso_sign. Returns (columns, rows,
        oni_rows)."""
        columns = [{"index": n, "lon": lon} for n, lon in
                   zip((9, 10, 1, 2, 3, 4, 5, 6, 7, 8), LONS_EAST)]
        oni = {}
        rows = []
        day = dt.date(2000, 1, 3)
        for t in range(730):
            key = (day.year, day.month)
            oni.setdefault(key, 1.5 * math.sin(2 * math.pi * (day.year * 12 + day.month) / 40))
            vals = []
            for c in columns:
                lam = tool.lon_deg_east(c["lon"])
                v = math.sin(2 * math.pi * (t / 9.0 - lam / 360.0))
                if c["lon"] in tool.MJO_ENSO_LONS:
                    v += enso_sign * 2.0 * oni[key]
                vals.append(round(v, 2))
            rows.append((day, vals))
            day += dt.timedelta(days=5)
        oni_rows = [(y, m, round(v, 2)) for (y, m), v in sorted(oni.items())]
        return columns, rows, oni_rows

    def test_verify_convention_accepts_positive_equals_suppressed(self):
        columns, rows, oni_rows = self.synthetic(+1)
        ev = tool.verify_convention(columns, rows, oni_rows)
        self.assertGreater(ev["enso"]["meanR100E_140E"], tool.MJO_ENSO_MIN_MEAN_R)
        self.assertEqual(ev["propagation"]["negative"], 0)
        self.assertGreater(ev["propagation"]["positive"], 0)

    def test_verify_convention_rejects_flipped_sign(self):
        columns, rows, oni_rows = self.synthetic(-1)
        with self.assertRaises(RuntimeError) as cm:
            tool.verify_convention(columns, rows, oni_rows)
        self.assertIn("sign convention", str(cm.exception))

    def test_verify_convention_rejects_westward_propagation(self):
        columns, rows, oni_rows = self.synthetic(+1)
        # mirror the longitudes: same data, labels attached to the wrong columns
        flipped = [dict(c, lon=lon) for c, lon in zip(columns, reversed([c["lon"] for c in columns]))]
        with self.assertRaises(RuntimeError):
            tool.verify_convention(flipped, rows, oni_rows)

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


class EofDerivation(unittest.TestCase):
    """derive_mjo_eof on synthetic ten-longitude blocks: it must accept an
    eastward wave in the MJO band and refuse everything else."""

    N = 800

    @staticmethod
    def block(fn, n=N, seed=1, noise=0.05):
        """MJO-block-shaped dict whose series[lon][t] = fn(t, lon_deg_east) plus
        small deterministic noise, 2 decimals like the real file."""
        rng = random.Random(seed)
        day0 = dt.date(2000, 1, 3)
        dates = [int((day0 + dt.timedelta(days=5 * t)).strftime("%Y%m%d")) for t in range(n)]
        series = {lon: [round(fn(t, tool.lon_deg_east(lon)) + noise * rng.gauss(0, 1), 2) for t in range(n)]
                  for lon in LONS_EAST}
        return {"longitudes": list(LONS_EAST), "dates": dates, "series": series,
                "lonDegE": {lon: tool.lon_deg_east(lon) for lon in LONS_EAST}}

    @staticmethod
    def wave(period_pentads, direction=+1):
        return lambda t, lam: math.sin(2 * math.pi * (t / period_pentads - direction * lam / 360.0))

    def test_jacobi_matches_a_known_matrix(self):
        vals, vecs = tool.jacobi_eigh([[2.0, 1.0], [1.0, 2.0]])
        self.assertAlmostEqual(vals[0], 3.0, places=9)
        self.assertAlmostEqual(vals[1], 1.0, places=9)
        self.assertAlmostEqual(abs(vecs[0][0]), math.sqrt(0.5), places=9)
        self.assertAlmostEqual(vecs[0][0] * vecs[0][1], 0.5, places=9)

    def test_jacobi_eigenpairs_on_a_random_symmetric_matrix(self):
        rng = random.Random(7)
        n = 10
        b = [[rng.gauss(0, 1) for _ in range(n)] for _ in range(n)]
        a = [[sum(b[k][i] * b[k][j] for k in range(n)) for j in range(n)] for i in range(n)]
        vals, vecs = tool.jacobi_eigh(a)
        self.assertEqual(vals, sorted(vals, reverse=True))
        self.assertAlmostEqual(sum(vals), sum(a[i][i] for i in range(n)), places=8)     # trace
        for lam, v in zip(vals, vecs):
            av = [sum(a[i][j] * v[j] for j in range(n)) for i in range(n)]
            for x, y in zip(av, v):
                self.assertAlmostEqual(x, lam * y, places=8)
            self.assertAlmostEqual(sum(x * x for x in v), 1.0, places=9)
        for i in range(n):
            for j in range(i):
                self.assertAlmostEqual(sum(x * y for x, y in zip(vecs[i], vecs[j])), 0.0, places=9)

    def test_jacobi_rejects_asymmetric(self):
        with self.assertRaises(RuntimeError):
            tool.jacobi_eigh([[1.0, 2.0], [0.0, 1.0]])

    def test_eastward_wave_in_band_is_accepted(self):
        m = self.block(self.wave(9.0))                       # 45-day eastward wave
        eof, phase, amp = tool.derive_mjo_eof(m)
        v = eof["validation"]
        self.assertGreater(eof["variance12Pct"], 98)
        self.assertGreater(eof["pairRatio"], 0.6)       # ~0.69: uneven station spacing, not the wave
        self.assertAlmostEqual(v["periodDays"]["value"], 45.0, delta=1.0)
        self.assertAlmostEqual(v["medianAdvanceDegPerPentad"], 40.0, delta=1.0)
        self.assertGreater(v["patternEastwardNetDeg"], 180)
        self.assertEqual(len(phase), self.N)
        self.assertEqual(len(amp), self.N)
        self.assertTrue(all(-math.pi <= p <= math.pi for p in phase))
        self.assertTrue(all(a >= 0 for a in amp))
        # whichever raw EOF signs fell out, the emitted phase moves forward in time
        steps = [(phase[i + 1] - phase[i] + math.pi) % (2 * math.pi) - math.pi for i in range(self.N - 1)]
        self.assertGreater(sum(s > 0 for s in steps) / len(steps), 0.95)

    def test_missing_pentads_get_null_phase(self):
        m = self.block(self.wave(9.0))
        m["series"]["100E"][50] = None                       # one longitude missing
        for lon in LONS_EAST:
            m["series"][lon][60] = None                      # whole row missing
        eof, phase, amp = tool.derive_mjo_eof(m)
        for i in range(self.N):
            absent = i in (50, 60)
            self.assertEqual(phase[i] is None, absent, i)
            self.assertEqual(amp[i] is None, absent, i)
        self.assertEqual(eof["decomposition"]["pentads"], self.N - 2)

    def test_boundary_phase_never_exceeds_pi_after_rounding(self):
        # rounding 3.14159265 to 4 places gives 3.1416 > pi; the emitter must not do that
        m = self.block(self.wave(9.0), n=2000, noise=0.0)
        _eof, phase, _amp = tool.derive_mjo_eof(m)
        self.assertLessEqual(max(phase), math.pi)
        self.assertGreaterEqual(min(phase), -math.pi)

    def test_westward_wave_is_refused(self):
        # same band, same variance structure, wrong direction: pc2Sign would be chosen to make the
        # angle advance in time, so only the loadings-based pattern check can catch it
        m = self.block(self.wave(9.0, direction=-1))
        with self.assertRaises(RuntimeError) as cm:
            tool.derive_mjo_eof(m)
        self.assertIn("west", str(cm.exception))

    def test_independent_noise_fails_the_variance_check(self):
        rng = random.Random(3)
        m = self.block(lambda t, lam: rng.gauss(0, 1), noise=0.0)
        with self.assertRaises(RuntimeError) as cm:
            tool.derive_mjo_eof(m)
        self.assertIn("EOF1+EOF2 explain", str(cm.exception))

    def test_variance_threshold_is_the_one_that_fires(self):
        # a wave plus enough noise that EOF1+EOF2 fall just below 90% must be refused...
        m = self.block(self.wave(9.0), noise=1.0, seed=5)
        try:
            tool.derive_mjo_eof(m)
        except RuntimeError as err:
            self.assertIn("EOF1+EOF2 explain", str(err))
        else:
            self.fail("noisy field was accepted")
        # ...and the same wave with little noise is not
        tool.derive_mjo_eof(self.block(self.wave(9.0), noise=0.2, seed=5))

    def test_standing_oscillation_fails_the_pair_check(self):
        # one mode oscillating in place: EOF1 holds nearly everything, so the 90% variance test
        # passes and only the pair-balance (and direction) checks can reject it
        m = self.block(lambda t, lam: math.cos(math.radians(lam - 100)) * math.sin(2 * math.pi * t / 9.0),
                       noise=0.03)
        with self.assertRaises(RuntimeError) as cm:
            tool.derive_mjo_eof(m)
        self.assertIn("EOF2/EOF1", str(cm.exception))      # so the 90% variance test had passed

    def test_period_outside_the_mjo_band_is_refused(self):
        for period, label in ((24.0, "slow, 120 d"), (4.0, "fast, 20 d")):
            with self.subTest(label):
                m = self.block(self.wave(period))
                with self.assertRaises(RuntimeError) as cm:
                    tool.derive_mjo_eof(m)
                self.assertIn("implied period", str(cm.exception))
                self.assertIn("band", str(cm.exception))

    def test_period_band_edges_are_the_documented_ones(self):
        self.assertEqual(tool.MJO_EOF_PERIOD_BAND_DAYS, (25.0, 70.0))
        for period in (6.0, 13.0):        # 30 d and 65 d: inside the band
            tool.derive_mjo_eof(self.block(self.wave(period)))

    def test_too_few_pentads_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            tool.derive_mjo_eof(self.block(self.wave(9.0), n=tool.MJO_EOF_MIN_PENTADS - 1))
        self.assertIn("pentads", str(cm.exception))

    def test_phase_amplitude_reproduce_from_provenance(self):
        m = self.block(self.wave(9.0))
        eof, phase, amp = tool.derive_mjo_eof(m)
        l1, l2 = eof["loadings"]["eof1"], eof["loadings"]["eof2"]
        for i in (0, 123, 456, 799):
            x = {l: m["series"][l][i] - eof["means"][l] for l in LONS_EAST}
            z1 = sum(l1[l] * x[l] for l in LONS_EAST) / eof["pcStd"]["pc1"]
            z2 = sum(l2[l] * x[l] for l in LONS_EAST) / eof["pcStd"]["pc2"]
            ph = math.atan2(eof["signConvention"]["pc2Sign"] * z2, z1)
            self.assertLess(abs((ph - phase[i] + math.pi) % (2 * math.pi) - math.pi), 1e-4)
            self.assertAlmostEqual(math.hypot(z1, z2), amp[i], delta=1e-3)

    def test_wave1_min_lon(self):
        lons = [20, 70, 80, 100, 120, 140, 160, 240, 320, 350]
        for centre in (10.0, 100.0, 215.0, 300.0):
            field = [-math.cos(math.radians(x - centre)) for x in lons]
            got, r2 = tool.wave1_min_lon(lons, field)
            self.assertAlmostEqual(got, centre, delta=1e-6)
            self.assertAlmostEqual(r2, 1.0, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
