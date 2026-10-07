#!/usr/bin/env python3
"""Checks for tools/parse_hsf.py, the High Seas Forecast analysis-low parser.

The rule that matters most: a FORECAST position of a low must never come out
as an ANALYSIS row. A High Seas Forecast prints the analysed low and its
12/18/24/36/48-hour positions inside one warning section; a forecast that leaks
becomes a fabricated fix, and the build downstream would report deepening
between a fix and a prediction as storm intensification. So most tests here try
to make the parser leak:

  * hand-built products where the analysis names no low and the forecasts do,
    where a forecast statement is hard-wrapped so a LOW lands at the start of a
    line, where a forecast starts mid-line after a full stop, and where the
    pre-2004 layout runs analysis and forecast together in one paragraph;
  * an oracle over every real product in fixtures/ that does not use the
    parser's own regexes: no emitted row may open with a forecast marker, its
    printed position must precede any FORECAST word in its statement, and its
    (lat, lon, pressure) must not equal a forecast low's in the same product.

fixtures/ holds real products fetched from the Iowa State IEM archive (one
HSFAT1 and one HSFEP1 per year, 2002-2026, plus awkward cases found while
reading the archive). Two files named *.excerpt.txt are cut down from the
4-6 MB archive records they come from; everything else is the product as
served. The expected values below were checked by reading the product text.

    python3 tests/hsf_parse/test_parse_hsf.py
"""
import csv
import glob
import gzip
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIX = os.path.join(HERE, "fixtures")
TOOL = os.path.join(ROOT, "tools", "parse_hsf.py")

spec = importlib.util.spec_from_file_location("parse_hsf", TOOL)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

SPEC_COLUMNS = ["pil", "product_id", "issued", "valid", "section", "warn_cat",
                "lat", "lon", "pres", "mot_dir", "mot_kt", "raw"]


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def issued_of(name):
    return datetime.strptime(name[:12], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


def read_fixture(name):
    with open(os.path.join(FIX, name + ".txt"), encoding="utf-8") as fh:
        return fh.read()


def parse_text(text, issued, product_id="synthetic-HSFAT1", stats=None, **kw):
    """(analyses, rows) for a raw text."""
    an = P.parse_product(text, issued, product_id, "", stats=stats, **kw)
    return an, [r for a in an for r in a["rows"]]


def parse_fixture(name, **kw):
    return parse_text(read_fixture(name), issued_of(name), name, **kw)


def bulletin(body, synopsis="0000 UTC DEC 10", heading="FZNT01 KWBC 100420",
             pil="HSFAT1", extra=""):
    """A minimal modern-layout product around `body` (the warnings text)."""
    return ("000 \n%s\n%s\n\nHIGH SEAS FORECAST\n0430 UTC DEC 10 2006\n\nSECURITE\n"
            "NORTH ATLANTIC NORTH OF 31N TO 67N AND WEST OF 35W.\n\n"
            "SYNOPSIS VALID %s.\n24 HOUR FORECAST VALID 0000 UTC DEC 11.\n\n"
            ".WARNINGS.\n\n%s\n\n.SYNOPSIS AND FORECAST.\n\n%s\n\n"
            ".FORECASTER TEST. OCEAN PREDICTION CENTER.\n"
            % (heading, pil, synopsis, body, extra))


ISS = utc(2006, 12, 10, 4, 20)


def lows(body, **kw):
    return parse_text(bulletin(body, **kw), ISS)[1]


FIXTURES = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(FIX, "*.txt")))

# Analysis lows emitted per fixture. Reviewed by reading the products; a change here
# means the parser's yield moved and someone should look at why.
GOLDEN = {
    "200201010349-KWBC-FZPN01-HSFEP1": 5,
    "200201011032-KWBC-FZNT01-HSFAT1": 4,
    "200201130422-KWBC-FZNT01-HSFAT1": 4,
    "200201181615-KWBC-FZNT01-HSFAT1.excerpt": 4,
    "200202151013-KWBC-FZPN01-HSFEP1": 5,
    "200202170427-KWBC-FZNT01-HSFAT1": 4,
    "200205021009-KWBC-FZNT01-HSFAT1": 2,
    "200205211628-KWBC-FZNT01-HSFAT1": 0,
    "200206260959-KZID-SRUS27-HSFAT1.excerpt": 3,
    "200207010410-KWBC-FZNT01-HSFAT1": 1,
    "200207051612-KWBC-FZNT01-HSFAT1": 5,
    "200208101015-KWBC-FZNT01-HSFAT1": 2,
    "200211121628-KWBC-FZNT01-HSFAT1": 1,
    "200212100422-KWBC-FZPN01-HSFEP1": 4,
    "200212100425-KWBC-FZNT01-HSFAT1": 2,
    "200212102226-KWBC-FZNT01-HSFAT1": 2,
    "200212310414-KWBC-FZPN01-HSFEP1": 3,
    "200212310422-KWBC-FZPN01-HSFEP1-CCA": 4,
    "200303260939-KWBC-FZNT01-HSFAT1": 0,
    "200312100418-KWBC-FZPN01-HSFEP1": 4,
    "200312100423-KWBC-FZNT01-HSFAT1": 2,
    "200312311631-KWBC-FZNT01-HSFAT1": 1,
    "200412100423-KWBC-FZNT01-HSFAT1": 3,
    "200412100425-KWBC-FZPN01-HSFEP1": 5,
    "200412311558-KWBC-FZNT01-HSFAT1": 2,
    "200501010417-KWBC-FZPN01-HSFEP1": 4,
    "200501010442-KWBC-FZNT01-HSFAT1": 2,
    "200512100425-KWBC-FZNT01-HSFAT1": 3,
    "200512100429-KWBC-FZPN01-HSFEP1": 5,
    "200612100416-KWBC-FZPN01-HSFEP1": 5,
    "200612100420-KWBC-FZNT01-HSFAT1": 1,
    "200612100423-KWBC-FZNT01-HSFAT1": 1,
    "200612100502-KWBC-FZNT01-HSFAT1-RRA": 1,
    "200712100402-KWBC-FZNT01-HSFAT1": 2,
    "200712100425-KWBC-FZPN01-HSFEP1": 6,
    "200812100430-KWBC-FZNT01-HSFAT1": 1,
    "200812100545-KWBC-FZPN01-HSFEP1": 4,
    "200812101145-KWBC-FZPN01-HSFEP1": 3,
    "200812101145-KWBC-FZPN02-HSFEPI": 3,
    "200911051710-KWBC-FZNT01-HSFAT1": 3,
    "200912100430-KWBC-FZNT01-HSFAT1": 3,
    "200912100545-KWBC-FZPN01-HSFEP1": 7,
    "201001010545-KWBC-FZPN01-HSFEP1": 5,
    "201012100430-KWBC-FZNT01-HSFAT1": 2,
    "201012100545-KWBC-FZPN01-HSFEP1": 2,
    "201111052230-KWBC-FZNT01-HSFAT1": 4,
    "201112100430-KWBC-FZNT01-HSFAT1": 2,
    "201112100545-KWBC-FZPN01-HSFEP1": 3,
    "201202152345-KWBC-FZPN01-HSFEP1": 4,
    "201212100430-KWBC-FZNT01-HSFAT1": 1,
    "201212100430-KWBC-FZPN01-HSFEP1": 4,
    "201312100430-KWBC-FZNT01-HSFAT1": 3,
    "201312100430-KWBC-FZPN01-HSFEP1": 5,
    "201401010350-KWBC-FZNT01-HSFAT1": 4,
    "201412100430-KWBC-FZNT01-HSFAT1": 5,
    "201412100430-KWBC-FZPN01-HSFEP1": 4,
    "201511052230-KWBC-FZNT01-HSFAT1": 1,
    "201512100430-KWBC-FZNT01-HSFAT1": 3,
    "201512100430-KWBC-FZPN01-HSFEP1": 4,
    "201612100430-KWBC-FZNT01-HSFAT1": 4,
    "201612100430-KWBC-FZPN01-HSFEP1": 7,
    "201701011030-KWBC-FZNT01-HSFAT1": 2,
    "201712100430-KWBC-FZNT01-HSFAT1": 3,
    "201712100430-KWBC-FZPN01-HSFEP1": 4,
    "201801012230-KWBC-FZPN01-HSFEP1": 5,
    "201807151030-KWBC-FZNT01-HSFAT1": 0,
    "201812100430-KWBC-FZNT01-HSFAT1": 3,
    "201812100430-KWBC-FZPN01-HSFEP1": 5,
    "201912100430-KWBC-FZNT01-HSFAT1": 3,
    "201912100430-KWBC-FZPN01-HSFEP1": 4,
    "202012100430-KWBC-FZNT01-HSFAT1": 2,
    "202012100430-KWBC-FZPN01-HSFEP1": 6,
    "202112100430-KWBC-FZNT01-HSFAT1": 1,
    "202112100430-KWBC-FZPN01-HSFEP1": 4,
    "202201010430-KWBC-FZPN01-HSFEP1": 4,
    "202212100430-KWBC-FZNT01-HSFAT1": 4,
    "202212100430-KWBC-FZPN01-HSFEP1": 5,
    "202311050430-KWBC-FZNT01-HSFAT1": 3,
    "202312100430-KWBC-FZNT01-HSFAT1": 1,
    "202312100430-KWBC-FZPN01-HSFEP1": 5,
    "202412100430-KWBC-FZNT01-HSFAT1": 3,
    "202412100430-KWBC-FZPN01-HSFEP1": 7,
    "202412230430-KWBC-FZNT01-HSFAT1": 3,
    "202412231030-KWBC-FZNT01-HSFAT1": 3,
    "202412231630-KWBC-FZNT01-HSFAT1": 1,
    "202412231630-KWBC-FZPN01-HSFEP1": 4,
    "202412232230-KWBC-FZPN01-HSFEP1": 4,
    "202502150430-KWBC-FZPN01-HSFEP1": 3,
    "202512100430-KWBC-FZNT01-HSFAT1": 3,
    "202512100430-KWBC-FZPN01-HSFEP1": 6,
    "202601010430-KWBC-FZNT01-HSFAT1": 4,
    "202601010430-KWBC-FZPN01-HSFEP1": 5,
}


class SpecProducts(unittest.TestCase):
    """The products the contract names, checked against the product text."""

    def test_2006_hurricane_force_low_is_the_only_analysis(self):
        an, rows = parse_fixture("200612100420-KWBC-FZNT01-HSFAT1")
        self.assertEqual(len(rows), 1, [r["raw"][:60] for r in rows])
        r = rows[0]
        self.assertEqual((r["section"], r["warn_cat"]), ("warning", "HF"))
        self.assertEqual((r["lat"], r["lon"], r["pres"]), (62.0, -35.0, 933))
        self.assertEqual((r["mot_dir"], r["mot_kt"]), ("E", 10))
        self.assertEqual(r["valid"], "2006-12-10T00:00:00Z")
        self.assertTrue(r["raw"].startswith(".LOW 62N 35W 933 MB MOVING E 10 KT."))

    def test_2006_forecast_lines_are_not_rows(self):
        _, rows = parse_fixture("200612100420-KWBC-FZNT01-HSFAT1")
        for r in rows:
            self.assertNotIn("E OF AREA", r["raw"][:40])
            self.assertFalse(r["raw"].startswith(".24 HOUR"))
        # The product also holds forecast lows at 60N 57W 986 and 40N 44W 1016.
        self.assertFalse([r for r in rows if r["pres"] in (986, 1016)])

    def test_2024_area_only_storm_section_yields_nothing(self):
        # STORM WARNING: ".FROM 55N TO 60N E OF 45W ..." has no centre; the only
        # lows in that section are the 12/24/48 h forecasts (62N39W 990,
        # 65N38W 968, NE of area 66N33W 965). Zero rows may come from it.
        an, rows = parse_fixture("202412231630-KWBC-FZNT01-HSFAT1")
        self.assertEqual([r for r in rows if r["warn_cat"] == "S"], [])
        self.assertFalse([r for r in rows if r["pres"] in (990, 968, 965, 1002, 1018)])
        self.assertEqual([(r["lat"], r["lon"], r["pres"], r["warn_cat"]) for r in rows],
                         [(47.0, -42.0, 1003, "G")])

    def test_2024_trailing_area_coordinates_are_not_taken(self):
        # ".LOW 47N42W 1003 MB MOVING NE 25 KT. E OF A LINE FROM 49N44W TO
        # 45N48W TO 35N49W ..." - only the pair bound to LOW.
        _, rows = parse_fixture("202412231630-KWBC-FZNT01-HSFAT1")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["lat"], rows[0]["lon"]), (47.0, -42.0))
        self.assertEqual((rows[0]["mot_dir"], rows[0]["mot_kt"]), ("NE", 25))

    def test_2024_complex_low_with_new_second_low(self):
        _, rows = parse_fixture("202412230430-KWBC-FZNT01-HSFAT1")
        got = sorted((r["lat"], r["lon"], r["pres"], r["warn_cat"]) for r in rows)
        # Main 58N44W 973 and "A NEW SECOND LOW 62N37W 969" under the HF header,
        # plus the gale low. The 06 h forecast "SECOND LOW NEAR 64N35W 960" and
        # the 24 h "NEW LOW 62N38W 980" are forecasts.
        self.assertEqual(got, [(41.0, -50.0, 1007, "G"), (58.0, -44.0, 973, "HF"),
                               (62.0, -37.0, 969, "HF")])


class ForecastNeverLeaks(unittest.TestCase):
    """Adversarial: every way a forecast low could be mistaken for an analysis."""

    def test_analysis_without_a_low_and_forecast_lows_gives_zero(self):
        body = ("...STORM WARNING...\n"
                ".FROM 55N TO 60N E OF 45W WINDS 25 TO 40 KT. SEAS 18 TO 24 FT.\n"
                ".12 HOUR FORECAST LOW 62N39W 990 MB. FROM 58N TO 61N E OF 45W\n"
                "WINDS 40 TO 50 KT.\n"
                ".24 HOUR FORECAST LOW 65N38W 968 MB.\n"
                ".48 HOUR FORECAST LOW NE OF AREA 66N33W 965 MB.\n")
        self.assertEqual(lows(body), [])

    def test_every_forecast_opening_form(self):
        for opening in (".24 HOUR FORECAST", ".12 HR FORECAST", ".06 HOUR FORECAST",
                        ".36 HOURS FORECAST", ".FORECAST", "..24 HOUR FORECAST",
                        ".48 HR FCST", ".18 HOUR FORECAST NEW"):
            with self.subTest(opening=opening):
                body = "...STORM WARNING...\n%s LOW 50N 150W 990 MB. WINDS 30 KT.\n" % opening
                self.assertEqual(lows(body), [])

    def test_forecast_low_starting_a_wrapped_line(self):
        body = ("...STORM WARNING...\n.24 HOUR FORECAST\nLOW 50N 150W 990 MB. WINDS\n"
                "30 KT.\n.48 HOUR FORECAST NEW\nLOW 52N 140W 985 MB.\n")
        self.assertEqual(lows(body), [])

    def test_forecast_statement_starting_mid_line(self):
        # Seen in 2012: "SEAS 15 TO 20 FT. .48 HOUR FORECAST ..." - the forecast
        # must not be folded into (or hide behind) the statement above it.
        body = ("...STORM WARNING...\n"
                ".LOW 52N 56W 992 MB MOVING NE 20 KT. WINDS 30 KT SEAS 15 TO 20\n"
                "FT. .48 HOUR FORECAST LOW 56N 37W 994 MB. WINDS 25 KT.\n"
                ".24 HOUR FORECAST AREA OF NW WINDS 25 TO 35 KT SEAS 8 TO 12\nFT. "
                ".48 HOUR FORECAST LOW 40N 40W 1000 MB.\n")
        got = lows(body)
        self.assertEqual([(r["lat"], r["lon"], r["pres"]) for r in got], [(52.0, -56.0, 992)])

    def test_forecast_inside_the_analysis_paragraph_pre_2004_layout(self):
        # No dots, one paragraph: analysis, then "BY 1800 UTC ...", then
        # "FORECAST ..." positions of the same storm.
        body = ("DEVELOPING STORM 43N 173E 998 MB MOVING E 30 KT. WINDS 25 TO 40 \n"
                "KT SEAS 12 TO 24 WITHIN 720 NM S AND SW QUADRANTS. BY 1800 UTC \n"
                "JAN 1...STORM 42N 171W 990 MB WITH WINDS 35 TO 50 KT. FORECAST \n"
                "STORM 42N 161W 983 MB. FORECAST LOW 41N 150W 980 MB.\n")
        got = lows(body)
        self.assertEqual([(r["lat"], r["lon"], r["pres"]) for r in got], [(43.0, 173.0, 998)])

    def test_forecast_low_after_an_analysis_with_no_centre(self):
        body = ("...GALE WARNING...\n.LOW E OF AREA. FORECAST LOW 50N 40W 990 MB.\n"
                ".LOW ABSORBED. FORECAST LOW 51N 41W 991 MB.\n")
        self.assertEqual(lows(body), [])

    def test_reference_to_another_low_is_not_a_second_fix(self):
        body = ("...STORM WARNING...\n"
                ".LOW 46N160W 988 MB MOVING N 35 KT. EXCEPT AS NOTED WITH LOW\n"
                "53N168W ABOVE...FROM 33N TO 46N WINDS 25 TO 40 KT.\n"
                ".LOW 40N 150W 990 MB MOVING E 10 KT. ABSORBED BY LOW 46N 151W\n"
                "DESCRIBED BELOW.\n")
        got = lows(body)
        self.assertEqual([(r["lat"], r["lon"]) for r in got], [(46.0, -160.0), (40.0, -150.0)])

    def test_position_tagged_with_another_time_is_refused(self):
        body = ("DEVELOPING STORM 33N 74W 1010 MB AT 0000 UTC 2 JAN...AREA OF WINDS\n"
                "20 TO 30 KT.\n")
        self.assertEqual(lows(body), [])

    def test_header_after_forecast_does_not_relabel_earlier_rows(self):
        body = ("...HURRICANE FORCE WIND WARNING...\n"
                ".LOW 50N 150W 960 MB MOVING NE 20 KT. WINDS 65 KT.\n"
                ".24 HOUR FORECAST LOW 54N 140W 955 MB.\n"
                "...GALE WARNING...\n"
                ".LOW 40N 130W 1004 MB MOVING E 15 KT.\n")
        got = lows(body)
        self.assertEqual([(r["warn_cat"], r["pres"]) for r in got], [("HF", 960), ("G", 1004)])

    def test_synopsis_section_forecast_lows(self):
        got = parse_text(bulletin("...GALE WARNING...\n.NONE.\n", extra=(
            ".LOW 45N 40W 1001 MB MOVING E 10 KT.\n"
            ".24 HOUR FORECAST LOW 46N 30W 1003 MB.\n")), ISS)[1]
        self.assertEqual([(r["section"], r["warn_cat"], r["pres"]) for r in got],
                         [("synopsis", "", 1001)])

    def test_oracle_over_every_real_fixture(self):
        """Independent of the parser's regexes: see the module docstring."""
        fc_open = re.compile(r"^\.*\s*(?:\d+\s*(?:HOUR|HR)|FORECAST|FCST)")
        checked = 0
        for name in FIXTURES:
            text = read_fixture(name)
            fc_triples = set()
            for st in re.split(r"\n(?=\.)|\n\n", text):
                st = re.sub(r"\s+", " ", st).strip()
                if fc_open.match(st):
                    for m in re.finditer(r"(\d{1,2})N\s*(\d{1,3})\s*([EW])\s+(\d{3,4})", st):
                        fc_triples.add((float(m.group(1)),
                                        float(m.group(2)) * (-1 if m.group(3) == "W" else 1),
                                        int(m.group(4))))
            _, rows = parse_fixture(name)
            for r in rows:
                checked += 1
                raw = r["raw"]
                self.assertFalse(fc_open.match(raw), (name, raw[:80]))
                lat, lon = "%d" % r["lat"], "%d" % abs(r["lon"])
                m = re.search(r"\b0*%s(?:\.\d)?N\s*0*%s(?:\.\d)?\s*[EW]?" % (lat, lon), raw)
                self.assertTrue(m, (name, raw[:80]))
                cut = re.sub(r"FORECAST (AREA|REGION)", "XXXXXXXXXXXXXX", raw).find("FORECAST")
                if cut >= 0:
                    self.assertLess(m.start(), cut, (name, raw[:120]))
                self.assertNotIn((r["lat"], r["lon"], r["pres"]), fc_triples, (name, raw[:80]))
        self.assertGreater(checked, 250)


class ValidTime(unittest.TestCase):
    def test_year_wrap_issued_jan_1_synopsis_dec_31(self):
        # Real product: issued 2014-01-01 03:50, synopsis 1800 UTC DEC 31.
        an, rows = parse_fixture("201401010350-KWBC-FZNT01-HSFAT1")
        self.assertEqual(an[0]["valid"], utc(2013, 12, 31, 18))
        self.assertTrue(rows)
        self.assertTrue(all(r["valid"] == "2013-12-31T18:00:00Z" for r in rows))

    def test_year_wrap_issued_dec_31_synopsis_jan_1(self):
        # The reverse direction. No real product shows it, so it is built.
        text = bulletin(".LOW 50N 40W 990 MB.\n", synopsis="0000 UTC JAN 01")
        an, rows = parse_text(text, utc(2006, 12, 31, 23, 50))
        self.assertEqual(an[0]["valid"], utc(2007, 1, 1, 0))
        self.assertEqual(rows[0]["valid"], "2007-01-01T00:00:00Z")

    def test_no_wrap_in_the_middle_of_a_year(self):
        an, _ = parse_text(bulletin(".LOW 50N 40W 990 MB.\n", synopsis="1800 UTC JUN 14"),
                           utc(2010, 6, 15, 4, 20))
        self.assertEqual(an[0]["valid"], utc(2010, 6, 14, 18))

    def test_resolve_year_directly(self):
        f = P.resolve_year
        self.assertEqual(f("0000", 12, 31, utc(2008, 1, 1, 4)), utc(2007, 12, 31))
        self.assertEqual(f("0000", 1, 1, utc(2007, 12, 31, 23)), utc(2008, 1, 1))
        self.assertEqual(f("0000", 2, 29, utc(2008, 3, 1, 4)), utc(2008, 2, 29))
        self.assertIsNone(f("0000", 2, 30, utc(2008, 3, 1, 4)))
        self.assertIsNone(f("0000", 3, 12, utc(2003, 3, 26, 9)))   # 14 days away

    def test_issued_is_not_the_analysis_time(self):
        an, rows = parse_fixture("200612100420-KWBC-FZNT01-HSFAT1")
        self.assertEqual(rows[0]["issued"], "2006-12-10T04:20:00Z")
        self.assertEqual(rows[0]["valid"], "2006-12-10T00:00:00Z")

    def test_stale_text_is_rejected_not_dated_by_issuance(self):
        # Issued 2003-03-26 09:39 but the text is the 12 March bulletin.
        stats = P.Stats()
        an, rows = parse_fixture("200303260939-KWBC-FZNT01-HSFAT1", stats=stats)
        self.assertEqual(rows, [])
        self.assertIsNone(an[0]["valid"])
        self.assertEqual(stats.no_valid, 1)

    def test_garbled_synopsis_line_is_rejected(self):
        stats = P.Stats()
        an, rows = parse_fixture("200205211628-KWBC-FZNT01-HSFAT1", stats=stats)
        self.assertEqual((rows, stats.no_valid), ([], 1))

    def test_previous_month_typo_on_the_first_is_repaired(self):
        # "SYNOPSIS VALID 0000 UTC JUN 01" in a product issued 1 July whose
        # 24-hour line says JUL 02. About one bulletin day in thirty.
        stats = P.Stats()
        an, rows = parse_fixture("200207010410-KWBC-FZNT01-HSFAT1", stats=stats)
        self.assertEqual(an[0]["valid"], utc(2002, 7, 1, 0))
        self.assertEqual(stats.month_repaired, 1)
        self.assertEqual(len(rows), 1)

    def test_month_typo_across_the_year_boundary(self):
        stats = P.Stats()
        an, rows = parse_fixture("200501010417-KWBC-FZPN01-HSFEP1", stats=stats)
        self.assertEqual(an[0]["valid"], utc(2005, 1, 1, 0))
        self.assertEqual(stats.month_repaired, 1)
        self.assertEqual(len(rows), 4)

    def test_wrong_month_with_no_corroboration_is_not_guessed(self):
        text = bulletin(".LOW 50N 40W 990 MB.\n", synopsis="0000 UTC NOV 10").replace(
            "24 HOUR FORECAST VALID 0000 UTC DEC 11.", "")
        an, rows = parse_text(text, ISS)
        self.assertEqual((an[0]["valid"], rows), (None, []))


class Pressure(unittest.TestCase):
    def test_bounds(self):
        for p, ok in ((880, True), (1050, True), (879, False), (1051, False),
                      (1100, False), (870, False), (933, True)):
            with self.subTest(p=p):
                st = P.Stats()
                _, rows = parse_text(bulletin(".LOW 50N 150W %d MB MOVING NE 20 KT.\n" % p),
                                     ISS, stats=st)
                self.assertEqual(len(rows), 1)       # the position is still real
                self.assertEqual(rows[0]["pres"], p if ok else None)
                self.assertEqual(st.pres_rejected, 0 if ok else 1)

    def test_radius_after_position_is_not_a_pressure(self):
        got = lows("...GALE WARNING...\n.LOW 50N 150W 120 NM WINDS 30 KT.\n")
        self.assertEqual((len(got), got[0]["pres"]), (1, None))

    def test_blank_pressure_is_blank_in_the_csv(self):
        row = P.fmt_row(lows("...GALE WARNING...\n.LOW 44N 160W MOVING NE 45 KT.\n")[0])
        self.assertEqual(row[8], "")


class FormatVariants(unittest.TestCase):
    def one(self, statement):
        got = lows("...STORM WARNING...\n" + statement + "\n")
        self.assertEqual(len(got), 1, statement)
        return got[0]

    def test_spaces_with_mb(self):
        r = self.one(".LOW 62N 35W 933 MB MOVING E 10 KT.")
        self.assertEqual((r["lat"], r["lon"], r["pres"], r["mot_dir"], r["mot_kt"]),
                         (62.0, -35.0, 933, "E", 10))

    def test_no_mb_keyword(self):
        r = self.one(".LOW 44N 160W 994 MOVING NE 45 KT...")
        self.assertEqual((r["lat"], r["lon"], r["pres"], r["mot_dir"], r["mot_kt"]),
                         (44.0, -160.0, 994, "NE", 45))

    def test_no_spaces(self):
        r = self.one(".LOW 47N42W 1003 MB MOVING NE 25 KT. E OF A LINE FROM 49N44W TO 45N48W.")
        self.assertEqual((r["lat"], r["lon"], r["pres"]), (47.0, -42.0, 1003))

    def test_low_pres(self):
        r = self.one(".LOW PRES 25N89W 1013 MB")
        self.assertEqual((r["lat"], r["lon"], r["pres"]), (25.0, -89.0, 1013))

    def test_east_longitude_positive_and_180_without_letter(self):
        self.assertEqual(self.one(".LOW 38N 151E 1004 MB MOVING NE 35 KT.")["lon"], 151.0)
        r = self.one(".LOW 41N 180 1004 MB MOVING ENE 25 KT.")
        self.assertEqual((r["lon"], r["pres"]), (180.0, 1004))

    def test_longitude_without_hemisphere_is_refused_unless_180(self):
        self.assertEqual(lows("...STORM WARNING...\n.LOW 31N 45N 1016 MB MOVING N 10 KT.\n"), [])
        self.assertEqual(lows("...STORM WARNING...\n.LOW 38N1516E 1004 MB MOVING NE 35 KT.\n"), [])

    def test_two_word_bearing_and_decimals(self):
        r = self.one(".LOW 57N 152W 970 MB MOVING E NE 15 KT.")
        self.assertEqual(r["mot_dir"], "ENE")
        r = self.one(".LOW 57.5N 152.5W 970 MB DRIFTING W NW 5 KT.")
        self.assertEqual((r["lat"], r["lon"], r["mot_dir"], r["mot_kt"]), (57.5, -152.5, "WNW", 5))

    def test_stationary_and_unstated_motion(self):
        r = self.one(".LOW 48N 143W 1007 MB NEARLY STATIONARY. WINDS 25 TO 35 KT.")
        self.assertEqual((r["mot_dir"], r["mot_kt"]), ("", 0))
        r = self.one(".LOW 47N 45W 990 MB. WINDS 30 TO 40 KT.")
        self.assertEqual((r["mot_dir"], r["mot_kt"]), ("", None))

    def test_attached_mb(self):
        self.assertEqual(self.one(".LOW 47N 45W 990MB MOVING E 10 KT.")["pres"], 990)

    def test_off_area_qualifiers_that_still_print_a_centre(self):
        for st in (".LOW INLAND 44N 121W 990 MB MOVING E NE 40 KT.",
                   ".LOW W OF AREA NEAR 41N 154E 993 MB MOVING NE 25 KT.",
                   ".LOW E OF AREA 63N 32W 987 MB DRIFTING NE.",
                   ".INTENSIFYING LOW 50N58W 976 MB MOVING NE 35 KT.",
                   ".NEW LOW 41N74W 998 MB.",
                   ".COMPLEX LOW WITH MEAN CENTER 45N 146W 1004 MB DRIFTING SE 05 KT.",
                   ".COMPLEX SYSTEM WITH MAIN LOW NEAR 56N 179W 978 MB MOVING E 25 KT."):
            with self.subTest(st=st):
                self.assertEqual(len(lows("...STORM WARNING...\n" + st + "\n")), 1)

    def test_statements_with_no_usable_centre_give_nothing(self):
        for st in (".LOW ABSORBED.", ".LOW E OF AREA.", ".LOW DISSIPATED. WINDS 25 KT.",
                   ".LOW NOTED EARLIER NEAR 62N 28W 975 MB AND ASSOCIATED CONDITIONS MOVED E.",
                   ".FROM 55N TO 60N E OF 45W WINDS 25 TO 40 KT.",
                   ".COMPLEX LOW WITH MAIN CENTER 87N 51W 980 MB MOVING N 15 KT.",
                   ".SEMISOPOCHNOI VOLCANO (AT POSITION 51.6N 179.4E) IS EXPERIENCING LOW "
                   "LEVEL ERUPTIVE ACTIVITY."):
            with self.subTest(st=st):
                self.assertEqual(lows("...STORM WARNING...\n" + st + "\n"), [])

    def test_additional_centres_of_a_complex_system(self):
        got = lows("...GALE WARNING...\n.COMPLEX LOW WITH MAIN LOW 36N57W 996 MB MOVING S 10 KT AND\n"
                   "SECOND LOW 40N63W 1002 MB MOVING SE 20 KT. WITHIN 420 NM NW WINDS 30 KT.\n")
        self.assertEqual([(r["lat"], r["lon"], r["pres"], r["mot_dir"], r["mot_kt"]) for r in got],
                         [(36.0, -57.0, 996, "S", 10), (40.0, -63.0, 1002, "SE", 20)])

    def test_front_geometry_is_not_a_second_low(self):
        got = lows("...STORM WARNING...\n.COMPLEX LOW WITH MAIN CENTER 55N 51W 990 MB MOVING N 20 KT.\n"
                   "FRONT EXTENDS FROM 55N 48W TO 45N 52W TO SECOND LOW 43N 54W TO 35N 59W.\n")
        self.assertEqual(len(got), 1)

    def test_hard_wrap_inside_the_position(self):
        got = lows("...STORM WARNING...\n.LOW 47N\n42W 1003 MB MOVING\nNE 25 KT.\n")
        self.assertEqual((got[0]["lat"], got[0]["lon"], got[0]["pres"], got[0]["mot_kt"]),
                         (47.0, -42.0, 1003, 25))

    def test_wrapped_line_beginning_with_three_dots_is_not_a_header(self):
        got = lows("...HURRICANE FORCE WIND WARNING...\n"
                   ".LOW 50N 150W 960 MB MOVING NE 20 KT. WINDS 65 TO 90 KT SEAS 12 TO 18 FT FROM\n"
                   "...AND E OF 59N N OF 45N.\n"
                   ".LOW 41N 130W 1000 MB MOVING E 10 KT.\n")
        self.assertEqual([r["warn_cat"] for r in got], ["HF", "HF"])


class Categories(unittest.TestCase):
    def test_header_mapping(self):
        body = ("...HURRICANE FORCE WIND WARNING...\n.LOW 50N 150W 960 MB MOVING NE 20 KT.\n"
                "...STORM WARNING...\n.LOW 51N 150W 970 MB MOVING NE 20 KT.\n"
                "...GALE WARNING...\n.LOW 52N 150W 980 MB MOVING NE 20 KT.\n"
                "...HEAVY FREEZING SPRAY WARNING...\n.LOW 53N 150W 990 MB MOVING NE 20 KT.\n")
        self.assertEqual([r["warn_cat"] for r in lows(body)], ["HF", "S", "G", ""])

    def test_sloppy_header_dots(self):
        body = ("..STORM WARNING...\n.LOW 51N 150W 970 MB MOVING NE 20 KT.\n"
                "...GALE WARNING..\n.LOW 52N 150W 980 MB MOVING NE 20 KT.\n")
        self.assertEqual([r["warn_cat"] for r in lows(body)], ["S", "G"])

    def test_synopsis_section_has_no_category_and_is_labelled(self):
        body = "...STORM WARNING...\n.LOW 51N 150W 970 MB MOVING NE 20 KT.\n"
        got = parse_text(bulletin(body, extra=".LOW 45N 40W 1001 MB MOVING E 10 KT.\n"), ISS)[1]
        self.assertEqual([(r["section"], r["warn_cat"]) for r in got],
                         [("warning", "S"), ("synopsis", "")])

    def test_synopsis_header_with_stray_dots(self):
        text = bulletin("...GALE WARNING...\n.NONE.\n",
                        extra=".LOW 45N 40W 1001 MB MOVING E 10 KT.\n").replace(
            ".SYNOPSIS AND FORECAST.", ".SYNOPSIS AND FORECAST...")
        got = parse_text(text, ISS)[1]
        self.assertEqual([(r["section"], r["warn_cat"]) for r in got], [("synopsis", "")])

    def test_old_layout_takes_the_category_from_the_keyword(self):
        _, rows = parse_fixture("200201010349-KWBC-FZPN01-HSFEP1")
        self.assertEqual([r["warn_cat"] for r in rows], ["S", "G", "G", "G", "G"])
        self.assertEqual([(r["lat"], r["lon"], r["pres"]) for r in rows],
                         [(43.0, 173.0, 998), (51.0, -165.0, 978), (40.0, -147.0, 987),
                          (55.0, -146.0, 986), (46.0, -138.0, 986)])


class EarlyLayout(unittest.TestCase):
    """2002 prints its fields joined by ellipses and prefixes lows with words."""

    def lows_of(self, name):
        return [(r["section"], r["warn_cat"], r["lat"], r["lon"], r["pres"])
                for r in parse_fixture(name)[1]]

    def test_ellipsis_separated_fields(self):
        got = self.lows_of("200207051612-KWBC-FZNT01-HSFAT1")
        # ".LOW 62N 31W...E OF FORECAST AREA...995 MB" and ".LOW INLAND...47N 67W 1004 MB"
        self.assertEqual(got[:2], [("warning", "G", 62.0, -31.0, 995),
                                   ("warning", "G", 47.0, -67.0, 1004)])
        got = self.lows_of("200208101015-KWBC-FZNT01-HSFAT1")
        self.assertIn(("synopsis", "", 56.0, -32.0, 1000), got)   # ".LOW...E OF AREA...56N 32W 1000 MB"

    def test_developing_gale_and_hurricane_force_prefixes(self):
        self.assertIn(("warning", "", 45.0, -52.0, 1009), self.lows_of("200205021009-KWBC-FZNT01-HSFAT1"))
        got = self.lows_of("200201130422-KWBC-FZNT01-HSFAT1")
        # "DEVELOPING HURRICANE FORCE...LOW 34N 78W 1004 MB" is the analysis; the
        # "BY 0600 UTC JAN 13...GALE 36N 75W 1001 MB" and "...STORM 39N 71W 990 MB"
        # that follow it in the same paragraph are forecasts.
        self.assertIn(("warning", "", 34.0, -78.0, 1004), got)
        self.assertFalse([g for g in got if g[4] in (1001, 990)])

    def test_downgraded_from_gale_and_complex_low_center(self):
        self.assertIn(("synopsis", "", 31.0, -44.0, 1011), self.lows_of("200202170427-KWBC-FZNT01-HSFAT1"))
        self.assertEqual(self.lows_of("200211121628-KWBC-FZNT01-HSFAT1"), [("warning", "G", 61.0, -63.0, 984)])


class Bulletins(unittest.TestCase):
    """Which text is OPC's, decided by the WMO heading and nothing else."""

    def test_misfiled_hydrology_is_rejected_and_counted(self):
        text = ("000 \nSRUS27 KZID 260959\nRVAIND\n\nRIVER STAGE 40N 85W FLOOD LOW 41N 86W "
                "980 MB\n.LOW 42N 87W 985 MB MOVING NE 10 KT.\n")
        st = P.Stats()
        an, rows = parse_text(text, utc(2002, 6, 26, 9, 59), "x-HSFAT1", stats=st)
        self.assertEqual((an, rows), ([], []))
        self.assertEqual((st.rejected_records, st.rejected_year[2002]), (1, 1))
        self.assertEqual(st.rejected_headings["SRUS27 KZID"], 1)

    def test_no_wmo_heading_is_rejected_not_parsed_hopefully(self):
        text = bulletin(".LOW 50N 40W 990 MB MOVING E 10 KT.\n").split("\n", 2)[2]
        st = P.Stats()
        an, rows = parse_text(text, ISS, stats=st)
        self.assertEqual((an, rows, st.rejected_records), ([], [], 1))

    def test_heading_must_match_an_opc_product(self):
        for heading, ok in (("FZNT01 KWBC 100420", True), ("FZPN01 KWBC 100420", True),
                            ("FZPN02 KWBC 100420", True), ("FZNT02 KNHC 100420", False),
                            ("FZPN03 KNHC 100420", False), ("FZNT01 KNHC 100420", False),
                            ("FZHW40 PHFO 100420", False)):
            with self.subTest(heading=heading):
                _, rows = parse_text(bulletin(".LOW 50N 40W 990 MB.\n", heading=heading), ISS)
                self.assertEqual(len(rows), 1 if ok else 0)

    def test_pil_comes_from_the_heading_not_the_filing(self):
        _, rows = parse_text(bulletin(".LOW 50N 150W 990 MB.\n", heading="FZPN01 KWBC 100420"), ISS)
        self.assertEqual(rows[0]["pil"], "HSFEP1")
        st = P.Stats()
        P.parse_product(bulletin(".LOW 50N 150W 990 MB.\n", heading="FZPN01 KWBC 100420"),
                        ISS, "x", "HSFAT1", stats=st)
        self.assertEqual(st.pil_mismatch, 1)

    def test_bundled_nhc_bulletin_contributes_nothing(self):
        # Real: an HSFEP1 record that continues into NHC's HSFEP2 (FZPN03 KNHC).
        st = P.Stats()
        an, rows = parse_fixture("200202151013-KWBC-FZPN01-HSFEP1", stats=st)
        self.assertEqual(len(an), 1)
        self.assertEqual(len(rows), 5)
        self.assertEqual(st.rejected_headings["FZPN03 KNHC"], 1)

    def test_giant_record_with_thousands_of_bulletins(self):
        # Real, cut down: the 6 MB 2002-01-18 record holds an HSFAT1 and an
        # HSFEPI amongst unrelated bulletins; the OPC ones are recovered under
        # their own PIL and nothing else is read.
        st = P.Stats()
        an, rows = parse_fixture("200201181615-KWBC-FZNT01-HSFAT1.excerpt", stats=st)
        self.assertEqual(sorted(a["pil"] for a in an), ["HSFAT1", "HSFEPI"])
        self.assertTrue(rows)
        self.assertTrue(all(r["valid"] == "2002-01-18T12:00:00Z" for r in rows))

    def test_misfiled_record_that_also_holds_opc_bulletins(self):
        # Real, cut down: 200206260959-KZID-SRUS27-HSFAT1 (4 MB).
        st = P.Stats()
        an, rows = parse_fixture("200206260959-KZID-SRUS27-HSFAT1.excerpt", stats=st)
        self.assertEqual(sorted(a["pil"] for a in an), ["HSFAT1", "HSFEP1"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(st.rejected_bulletins, 4)
        self.assertEqual(st.rejected_records, 0)

    def test_doubled_heading_is_one_bulletin(self):
        # Real 2003 records begin "FZNT01 KWBC 100429 / HSFAT1 / FZNT01 KWBC
        # 092218 / HSFAT1" and then the bulletin.
        text = "000 \nFZNT01 KWBC 100429\nHSFAT1\n" + bulletin(".LOW 50N 40W 990 MB.\n")[len("000 \n"):]
        st = P.Stats()
        an, rows = parse_text(text, ISS, stats=st)
        self.assertEqual((len(an), len(rows), st.no_valid), (1, 1, 0))

    def test_tropical_bulletin_is_excluded_by_default(self):
        # Real, cut down: the second and third SYNOPSIS VALID blocks are the
        # tropical offices' text, with LOW PRES lows at 10N 119W.
        st = P.Stats()
        an, rows = parse_fixture("200206260959-KZID-SRUS27-HSFAT1.excerpt", stats=st)
        self.assertTrue(rows)
        self.assertTrue(all(r["lat"] >= 31 for r in rows), [r["lat"] for r in rows])
        self.assertGreater(st.other_segment_lows, 0)

    def test_all_segments_flag_brings_tropical_lows_with_their_own_time(self):
        _, rows = parse_fixture("200206260959-KZID-SRUS27-HSFAT1.excerpt", all_segments=True)
        trop = [r for r in rows if r["lat"] < 31]
        self.assertTrue(any("LOW PRES" in r["raw"] for r in trop), [r["raw"][:40] for r in rows])
        text = bulletin(".LOW 50N 40W 990 MB.\n").replace(
            ".FORECASTER TEST.", "SYNOPSIS VALID 1800 UTC TUE DEC 09\n\n.WARNINGS.\n\n"
            ".LOW PRES 25N89W 1013 MB.\n\n.FORECASTER TEST.")
        _, rows = parse_text(text, ISS, all_segments=True)
        self.assertEqual(sorted((r["valid"], r["lat"]) for r in rows),
                         [("2006-12-09T18:00:00Z", 25.0), ("2006-12-10T00:00:00Z", 50.0)])
        _, rows = parse_text(text, ISS)
        self.assertEqual([r["lat"] for r in rows], [50.0])


class CacheAndDedupe(unittest.TestCase):
    def build_cache(self, records):
        """records: [(pil, record dict)] -> cache dir path."""
        tmp = tempfile.mkdtemp(prefix="hsfcache")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        by = {}
        for pil, rec in records:
            by.setdefault((pil, rec["issued"][:7]), []).append(rec)
        for (pil, ym), recs in by.items():
            os.makedirs(os.path.join(tmp, pil), exist_ok=True)
            with gzip.open(os.path.join(tmp, pil, ym + ".jsonl.gz"), "wt") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")
        return tmp

    def rec(self, name, text=None):
        issued = issued_of(name).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"product_id": name, "issued": issued, "text": text or read_fixture(name)}

    def run_cache(self, cache, *extra):
        out = os.path.join(cache, "out.csv")
        r = subprocess.run([sys.executable, TOOL, "--cache", cache, "--out", out, *extra],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, newline="") as fh:
            return list(csv.DictReader(fh)), r.stderr

    def test_amendments_and_retransmissions_count_one_low_set(self):
        # Real 2006-12-10 04:20 bulletin: two transmissions and an -RRA.
        names = ["200612100420-KWBC-FZNT01-HSFAT1", "200612100423-KWBC-FZNT01-HSFAT1",
                 "200612100502-KWBC-FZNT01-HSFAT1-RRA"]
        cache = self.build_cache([("HSFAT1", self.rec(n)) for n in names])
        rows, err = self.run_cache(cache)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_id"], "200612100502-KWBC-FZNT01-HSFAT1-RRA")
        self.assertIn("duplicate analyses dropped", err)

    def test_later_transmission_wins_even_if_cached_earlier(self):
        a = self.rec("200612100420-KWBC-FZNT01-HSFAT1")
        b = self.rec("200612100502-KWBC-FZNT01-HSFAT1-RRA",
                     read_fixture("200612100420-KWBC-FZNT01-HSFAT1").replace("933 MB", "931 MB"))
        for order in ([a, b], [b, a]):
            cache = self.build_cache([("HSFAT1", r) for r in order])
            rows, _ = self.run_cache(cache)
            self.assertEqual([r["pres"] for r in rows], ["931"])

    def test_same_id_same_minute_last_read_wins(self):
        # The archive can serve two same-minute transmissions under one product
        # id; the cache keeps them in transmission order, so the last read is
        # the later transmission.
        base = read_fixture("200612100420-KWBC-FZNT01-HSFAT1")
        first = self.rec("200612100420-KWBC-FZNT01-HSFAT1", base)
        second = self.rec("200612100420-KWBC-FZNT01-HSFAT1", base.replace("933 MB", "929 MB"))
        rows, _ = self.run_cache(self.build_cache([("HSFAT1", first), ("HSFAT1", second)]))
        self.assertEqual([r["pres"] for r in rows], ["929"])

    def test_hsfep1_beats_hsfepi_for_one_valid_time(self):
        p1 = self.rec("200812101145-KWBC-FZPN01-HSFEP1")
        pi = self.rec("200812101145-KWBC-FZPN02-HSFEPI")
        rows, _ = self.run_cache(self.build_cache([("HSFEP1", p1), ("HSFEPI", pi)]))
        self.assertTrue(rows)
        self.assertEqual({r["pil"] for r in rows}, {"HSFEP1"})
        # and when HSFEP1 is missing for that time, HSFEPI is used
        rows, _ = self.run_cache(self.build_cache([("HSFEPI", pi)]))
        self.assertEqual({r["pil"] for r in rows}, {"HSFEPI"})

    def test_different_valid_times_are_kept(self):
        names = ["202412230430-KWBC-FZNT01-HSFAT1", "202412231030-KWBC-FZNT01-HSFAT1"]
        rows, _ = self.run_cache(self.build_cache([("HSFAT1", self.rec(n)) for n in names]))
        self.assertEqual({r["valid"] for r in rows},
                         {"2024-12-23T00:00:00Z", "2024-12-23T06:00:00Z"})

    def test_csv_columns_exact_and_order(self):
        rows, err = self.run_cache(self.build_cache(
            [("HSFAT1", self.rec("200612100420-KWBC-FZNT01-HSFAT1"))]))
        self.assertEqual(list(rows[0].keys()), SPEC_COLUMNS)
        self.assertEqual(P.COLUMNS, SPEC_COLUMNS)
        r = rows[0]
        self.assertEqual((r["pil"], r["lat"], r["lon"], r["pres"], r["mot_dir"], r["mot_kt"]),
                         ("HSFAT1", "62.0", "-35.0", "933", "E", "10"))

    def test_statistics_are_printed_by_year_and_era(self):
        names = ["200612100420-KWBC-FZNT01-HSFAT1", "202412230430-KWBC-FZNT01-HSFAT1"]
        _, err = self.run_cache(self.build_cache([("HSFAT1", self.rec(n)) for n in names]))
        for needle in ("products read", "valid time not determined", "statements, analysis",
                       "statements, forecast", "lows emitted", "with-pres", "2006", "2024",
                       "2006-2010", "2021+", "records rejected on WMO heading"):
            self.assertIn(needle, err)

    def test_rejections_reported_by_era(self):
        bad = {"product_id": "200206260959-KZID-SRUS27-HSFAT1", "issued": "2002-06-26T09:59:00Z",
               "text": "000 \nSRUS27 KZID 260959\nRVAIND\nRIVER 41N 86W\n"}
        cache = self.build_cache([("HSFAT1", bad),
                                  ("HSFAT1", self.rec("200612100420-KWBC-FZNT01-HSFAT1"))])
        rows, err = self.run_cache(cache)
        self.assertEqual(len(rows), 1)
        self.assertIn("rejected records by era (issued year): 2002-2005: 1", err)

    def test_from_text_cli_and_stdin(self):
        path = os.path.join(FIX, "200612100420-KWBC-FZNT01-HSFAT1.txt")
        r = subprocess.run([sys.executable, TOOL, "--from-text", path, "--quiet"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(r.stdout)))), 1)
        with open(path) as fh:
            r = subprocess.run([sys.executable, TOOL, "--from-text", "-", "--quiet",
                                "--issued", "2006-12-10T04:20:00Z"],
                               stdin=fh, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0].split(","), SPEC_COLUMNS)

    def test_from_text_without_issue_time_is_an_error(self):
        r = subprocess.run([sys.executable, TOOL, "--from-text", "-", "--quiet"],
                           input="FZNT01 KWBC 100420\nHSFAT1\n", capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


class Yield(unittest.TestCase):
    """Pins the yield of every fixture, so a silent drop shows up here."""

    def test_golden_counts(self):
        bad = {}
        for name, want in GOLDEN.items():
            got = len(parse_fixture(name)[1])
            if got != want:
                bad[name] = (want, got)
        self.assertEqual(bad, {}, "analysis-low counts changed; inspect before re-pinning")
        self.assertEqual(sorted(GOLDEN), FIXTURES)

    def test_every_winter_product_in_every_era_yields_lows(self):
        # One HSFAT1 and one HSFEP1 per year on 10 December (2026: January):
        # there is always an analysed low somewhere in the north Atlantic or
        # Pacific in winter, so an empty product means the parser went blind.
        empty = []
        for name in FIXTURES:
            if re.match(r"(\d{4}1210|20260101)\d{4}-KWBC-FZ(NT01|PN01)-HSF(AT1|EP1)$", name):
                if not parse_fixture(name)[1]:
                    empty.append(name)
        self.assertEqual(empty, [])

    def test_no_era_is_thin(self):
        per = {}
        for name in FIXTURES:
            if not re.match(r"(\d{4})1210\d{4}-KWBC-FZ(NT01|PN01)-HSF(AT1|EP1)$", name):
                continue
            an, rows = parse_fixture(name)
            a = per.setdefault(P.era_of(int(name[:4])), [0, 0])
            a[0] += len(an)
            a[1] += len([r for r in rows if r["pres"] is not None])
        rate = {k: v[1] / v[0] for k, v in per.items()}
        med = sorted(rate.values())[len(rate) // 2]
        thin = {k: round(v, 2) for k, v in rate.items() if v < P.THIN_SHARE * med}
        self.assertEqual(thin, {}, rate)

    def test_per_year_table_over_the_corpus(self):
        st = P.Stats()
        for name in FIXTURES:
            if name.endswith(".excerpt"):
                continue
            an, rows = parse_fixture(name, stats=st)
            for a in an:
                P.tally(st, a["valid"], a["rows"], issued_of(name))
        years = sorted(st.prod_year)
        print("\nper-year yield over fixtures (not de-duplicated):")
        for y in years:
            print("  %d analyses=%3d lows=%3d with-pres=%3d" % (
                y, st.prod_year[y], st.lows_year[y], st.lows_pres_year[y]))
        self.assertEqual(years[0], 2002)
        self.assertEqual(years[-1], 2026)
        self.assertGreater(sum(st.lows_pres_year.values()), 250)


if __name__ == "__main__":
    unittest.main(verbosity=2)
