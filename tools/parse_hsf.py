#!/usr/bin/env python3
"""Turn raw OPC High Seas Forecast text into a table of ANALYSIS low centres.

Stage 2 of the pre-hurricane-force backfill (see the interface contract in the
project notes). Reads the cache written by tools/fetch_hsf.py and writes:

    data/hf_lows/hsf_lows.csv
        pil,product_id,issued,valid,section,warn_cat,lat,lon,pres,mot_dir,mot_kt,raw

One row per low that the product ANALYSES at its synopsis time. A low that the
product merely FORECASTS is never a row. A High Seas Forecast prints the
analysed position of a low and then its 12/18/24/36/48-hour positions inside
the same warning section, so a parser that is careless about which is which
turns a forecast into an observation, and the build downstream would measure
deepening between a fix and a prediction and publish it as storm
intensification. Every choice below that looks over-strict is guarding that.
When in doubt this parser emits nothing: a missing fix costs a gap in a track,
a wrong one corrupts a statistic.

What counts as an OPC bulletin is decided by the WMO heading (FZNT01 KWBC,
FZPN01 KWBC, FZPN02 KWBC), never by the PIL the archive filed it under, and
records without one are rejected and counted by era. The archive holds each
bulletin several times (re-transmissions, -RRA/-CCA/-CCB corrections, HSFEPI
beside HSFEP1), so the output has one analysis per basin and synopsis time,
the later transmission winning.

Usage:
    python3 tools/parse_hsf.py                       # whole cache -> CSV
    python3 tools/parse_hsf.py --from-text FILE      # one raw product -> stdout
    cat product.txt | python3 tools/parse_hsf.py --from-text - --issued 2006-12-10T04:20:00Z

Parse statistics go to stderr, including a per-year yield table. A silent drop
in yield across an era is the failure that is hardest to see afterwards, so
the table is always printed.
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "hsf_cache")
OUT_CSV = os.path.join(ROOT, "data", "hf_lows", "hsf_lows.csv")

COLUMNS = ["pil", "product_id", "issued", "valid", "section", "warn_cat",
           "lat", "lon", "pres", "mot_dir", "mot_kt", "raw"]

# Same bounds the archive builder applies to hand-entered pressures. Wider than
# any real extratropical analysis, so a number outside it is a typo or a
# mis-bound token (a wind speed, a range in nm), not a storm.
PRES_MIN, PRES_MAX = 880, 1050

# HSFEPI is a byte-for-byte duplicate of HSFEP1 under another header. When both
# exist for one synopsis time the lower rank wins; emitting both would count
# one low twice.
PIL_RANK = {"HSFAT1": 0, "HSFEP1": 0, "HSFEPI": 1}
PIL_BASIN = {"HSFAT1": "atl", "HSFEP1": "pac", "HSFEPI": "pac"}

MONTHS = {m: i + 1 for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}

# The line that carries the analysis time. A weekday is printed by the tropical
# sections ("SYNOPSIS VALID 0000 UTC TUE JAN 01") and not by OPC's; accepting
# both lets the same pattern delimit every section of the text. Two quirks are
# tolerated when recognising the line as a section start: a leading '.' (some
# 2011 products print every preamble line with one) and a mangled date (the
# tropical bulletin has printed "NOV 03NOV 02"). The line must still open its
# section even when its time cannot be trusted, or the next bulletin's lows
# would be read as OPC's.
SYNOPSIS_MARK = re.compile(r"^[ \t]*\.?[ \t]*SYNOPSIS\s+VALID\b.*$", re.M)
SYNOPSIS_TIME = re.compile(
    r"SYNOPSIS\s+VALID\s+(\d{4})\s+UTC\s+(?:[A-Z]{3}\s+)?([A-Z]{3})\s+(\d{1,2})")
# OPC signs off with a FORECASTER line. What follows it in the raw text is the
# neighbouring office's bulletin, not OPC's.
SIGNOFF = re.compile(r"^[ \t]*(?:\.?\s*FORECASTER\b|\$\$)", re.M)

# A product's own issuance stamp, "0430 UTC DEC 10 2006". Used only when a raw
# text arrives without a record around it; the cache supplies `issued`.
ISSUED_LINE = re.compile(
    r"^\s*(\d{4})\s+UTC\s+([A-Z]{3})\s+(\d{1,2})\s+(\d{4})\b", re.M)

# Headers are "...WORDS..." on a line of their own, but the typed products are
# sloppy about the dots: "..STORM WARNING..." and ".SYNOPSIS AND FORECAST..."
# both occur. A missed header is not harmless - the lows below it would keep the
# previous category, or be filed under the wrong section - so the dots are
# matched loosely and the title is what carries the meaning. Requiring the
# closing dots (and no digits in the title) keeps a hard-wrapped continuation
# like "...AND E OF 59N N OF 45N." from being taken for one.
HEADER = re.compile(r"^\.{2,3}\s*([A-Z][A-Z /&-]*?)\s*\.{2,3}$")
SECTION_WARN = re.compile(r"^\.*\s*WARNINGS\s*\.*$")
SECTION_SYN = re.compile(r"^\.*\s*SYNOPSIS\s+AND\s+FORECAST\s*\.*$")

# A statement is a forecast if it opens with a lead time or the word FORECAST.
# "36 HOUR", "12 HR" and "48 HOURS" have all been printed.
FORECAST_OPEN = re.compile(
    r"^\.*\s*(?:\d+\s*(?:HOURS?|HRS?)\b|FORECAST\b|FCST\b|OUTLOOK\b"
    r"|(?:BY|AT|AFTER)\s+\d{3,4}\s+UTC\b)")

# Words that, once seen inside an otherwise-analysis statement, mean everything
# after them is about the future or about another system. The pre-2004 layout
# runs the analysis and its forecast together in one paragraph ("...STORM 43N
# 173E 998 MB MOVING E 30 KT. BY 1800 UTC JAN 1...STORM 42N 171W 990 MB ...
# FORECAST STORM 42N 161W 983 MB"), and a modern statement can end with
# "ABSORBED BY LOW 46N 151W DESCRIBED BELOW". Cutting the statement at the first
# such word, before any position is looked for, makes it structurally
# impossible to pick a later position up.
STOP_WORDS = re.compile(
    r"\b(?:FORECASTS?|FCST"
    r"|(?:BY|AT|AFTER|IN|WITHIN|NEXT(?:\s+[A-Z]+)?)\s+\d{0,4}\s*(?:UTC|HOURS?|HRS?)"
    r"|ABSORBED|ABSORBING|DESCRIBED|MERGES?|MERGING|EXPECTED"
    r"|WILL\s+(?:DEVELOP|FORM|BECOME|MERGE))\b")

# The position bound to a low. The keyword, with at most a short whitelist of
# location qualifiers, must be directly followed by the coordinates. That is
# what keeps the area descriptions that trail a low ("...MOVING NE 25 KT. E OF A
# LINE FROM 49N44W TO 45N48W") out: they carry no LOW keyword. The qualifiers
# are the ones OPC actually prints for a centre that is real but off the map
# ("LOW INLAND 44N 121W", "LOW W OF AREA NEAR 41N 154E", "COMPLEX LOW WITH MEAN
# CENTER 45N 146W"); anything else between keyword and coordinates, such as
# ".LOW NOTED EARLIER NEAR ..." (a past position, not the analysis) or ".LOW
# NE OF AREA." with no coordinates, fails to match and yields nothing.
# Latitude letter is always N. Longitude 180 is printed with no hemisphere
# letter ("LOW 41N 180 1004 MB"); any other longitude without one is refused
# rather than guessed.
LOW_KEYWORD = (r"(?:LOW(?:\s+PRES(?:SURE)?|\s+CENTER)?"
               r"|(?:MEAN|MAIN|PRIMARY|STRONGER|WEAKER|SECONDARY|SECOND|THIRD|ONE|FIRST)\s+(?:LOW\s+)?CENTER"
               r"|(?:DEVELOPING\s+)?(?:HURRICANE\s+FORCE\s+LOW|STORM|GALE))")
DIRECTION_OF_AREA = (r"(?:N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST|NORTHEAST|NORTHWEST"
                     r"|SOUTHEAST|SOUTHWEST)\s+OF\s+(?:THE\s+)?(?:FORECAST\s+)?(?:AREA|REGION)")
# The 2002 text strings its fields together with ellipses ("LOW INLAND...47N
# 67W 1004 MB", "LOW E OF AREA...51N 31W 992 MB", "47N 34W...978 MB"), so an
# ellipsis counts as a separator wherever a space does.
SEP = r"(?:\s|\.\.\.)+"
LOW_QUALIFIER = (r"(?:(?:JUST|WELL|NEAR|INLAND|RELOCATED"
                 r"|(?:DOWNGRADED|UPGRADED)\s+FROM\s+(?:GALE|STORM|HURRICANE\s+FORCE)"
                 r"|" + DIRECTION_OF_AREA + r")" + SEP + r"){0,4}")
LOW_POS = re.compile(
    r"\b(?P<kw>" + LOW_KEYWORD + r")" + SEP + LOW_QUALIFIER +
    r"(?P<lat>\d{1,2}(?:\.\d)?)\s*N\s*"
    r"(?P<lon>\d{1,3}(?:\.\d)?)(?:\s*(?P<h>[EW])\b|(?=\s))"
    # A pressure is 3-4 digits not followed by a unit. "120 NM" after a
    # position is a radius, not a pressure.
    # ".LOW 62N 31W...E OF FORECAST AREA...995 MB" puts the area note between
    # position and pressure.
    r"(?:" + SEP + DIRECTION_OF_AREA + r")?"
    r"(?:" + SEP + r"(?P<pres>\d{3,4})(?!\d)(?!\s*(?:NM|KT|FT|N\b|S\b|E\b|W\b))(?:\s*(?:MB|HPA))?)?")

# What may precede the FIRST position in a statement. An analysis statement
# opens with its low, so anything else in front of a position ("IN ASSOCIATION
# WITH THE DEVELOPING STORM 38N 59W ... AT 0000 UTC 2 JAN", "EXCEPT WHERE NOTED
# WITH LOW 54N 53W") is a reference to a low described elsewhere or a position
# valid at another time, and taking it would duplicate a low or smuggle in a
# forecast. The words listed are the ones OPC puts in front of a real centre.
OPENING = re.compile(
    r"^\.*\s*(?:(?:COMPLEX|SYSTEM|LOW|PRESSURE|CENTER|WITH|WITHIN|ONE|FIRST|MAIN|MEAN|PRIMARY"
    r"|DEVELOPING|GALE|STORM|NEW|NEWLY|FORMED|COMBINED|HURRICANE|FORCE|INLAND|RAPIDLY"
    r"|INTENSIFYING|WEAKENING|" + DIRECTION_OF_AREA + r")(?:\s+|\.{1,3}\s*))*$")
# A later position in the same statement is accepted only as a named additional
# centre of a complex system ("...AND A SECOND LOW 36N 140W 1004 MB").
ADDITIONAL = re.compile(
    r"\b(?:AND|WITH|\.\.\.)\s*(?:A\s+)?(?:NEW\s+)?(?:SECOND|SECONDARY|THIRD)\s+(?:LOW|CENTER)\b")
# A position tagged with its own time is not the analysis time.
TIME_TAGGED = re.compile(r"\s*(?:AT|BY)\s+\d{3,4}\s+UTC")

# "MOVING E NE 15 KT", "DRIFTING NE 5 KT", "WILL MOVE N 20 KT". The old layout
# prints the bearing as two words ("N NE"), which is read as one compass point.
MOTION = re.compile(
    r"\b(?:MOVING|MOVE|DRIFTING|DRIFT|TRACKING)\s+"
    r"(?P<dir>(?:N|NE|E|SE|S|SW|W|NW)(?:\s+(?:N|NE|E|SE|S|SW|W|NW)\b)?)\s+"
    r"(?:AT\s+)?(?P<kt>\d{1,2})\s*KT\b")
STATIONARY = re.compile(r"\b(?:STATIONARY|STNRY|QUASI-?STATIONARY)\b")

# Any mention of a low at all, used only to report how many analysis statements
# name a low but give no usable centre (".LOW ABSORBED.", ".LOW E OF AREA.").
LOW_WORD = re.compile(r"\bLOW\b")

CAT_FROM_HEADER = (("HURRICANE FORCE", "HF"), ("STORM", "S"), ("GALE", "G"))


# --------------------------------------------------------------- time ------

def parse_iso(s):
    """'2006-12-10T04:20:00Z' -> aware UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_year(hhmm, mon, day, issued):
    """Datetime for a month/day that carries no year, nearest to `issued`.

    A product issued 1 Jan can carry a 31 Dec synopsis and one issued 31 Dec
    can carry a 1 Jan one, so the neighbouring years are candidates too and the
    closest to the issuance wins. Three days is the cutoff: nothing in this
    series reaches further than the 6-hourly cycle, so a larger gap means the
    month or day was mis-read, and no valid time is better than a wrong one.
    """
    best = None
    for yr in (issued.year - 1, issued.year, issued.year + 1):
        try:
            t = datetime(yr, mon, day, int(hhmm[:2]), int(hhmm[2:]),
                         tzinfo=timezone.utc)
        except ValueError:
            continue
        gap = abs((t - issued).total_seconds())
        if best is None or gap < best[0]:
            best = (gap, t)
    if best is None or best[0] > 3 * 86400:
        return None
    return best[1]


# The 24-hour forecast time is printed under the synopsis time, and is the
# synopsis time plus a day.
FORECAST24_TIME = re.compile(
    r"24\s+HOUR\s+FORECAST\s+VALID\s+(\d{4})\s+UTC\s+(?:[A-Z]{3}\s+)?([A-Z]{3})\s+(\d{1,2})")


def synopsis_time(m, line, body, issued):
    """(valid or None, repaired) for a segment's SYNOPSIS VALID line.

    OPC's template prints the previous month's name on the first day of the
    month ("SYNOPSIS VALID 0000 UTC JUN 01" in a product issued 1 July, whose
    header and 24-hour line both say JUL), about one bulletin day in thirty.
    Dropping those would blank every month start, so when the stated date is
    nowhere near the issuance the time is re-derived from the 24-hour forecast
    line minus one day, and used only if it agrees with the stated hour and
    lands within the usual window of the issuance. Reported as a repair count.
    """
    mon = MONTHS.get(m.group(2)) if m else None
    valid = resolve_year(m.group(1), mon, int(m.group(3)), issued) if mon else None
    if valid is not None or m is None:
        return valid, False
    f = FORECAST24_TIME.search(line + " " + body[:400])
    fmon = MONTHS.get(f.group(2)) if f else None
    if not fmon or f.group(1) != m.group(1):
        return None, False
    t24 = resolve_year(f.group(1), fmon, int(f.group(3)), issued + timedelta(days=1))
    if t24 is None:
        return None, False
    t = t24 - timedelta(days=1)
    if abs((t - issued).total_seconds()) > 3 * 86400:
        return None, False
    return t, True


def issued_from_text(text):
    m = ISSUED_LINE.search(text)
    if not m or m.group(2) not in MONTHS:
        return None
    try:
        return datetime(int(m.group(4)), MONTHS[m.group(2)], int(m.group(3)),
                        int(m.group(1)[:2]), int(m.group(1)[2:]),
                        tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------- segmentation ----

def split_segments(text):
    """[(time_match_or_None, body, synopsis_line)] - one per 'SYNOPSIS VALID' line.

    The raw text of an OPC product continues into the tropical bulletin of the
    neighbouring office (NHC for the Atlantic, TAFB for the east Pacific), which
    has its own synopsis time and its own "WARNINGS" and "SYNOPSIS AND
    FORECAST" blocks. Those lows are not OPC's, are outside the domain this
    series is about, and are stamped with a different valid time, so each
    SYNOPSIS VALID line opens a segment that is parsed against its own time,
    and OPC's segment ends at its FORECASTER sign-off.
    """
    marks = list(SYNOPSIS_MARK.finditer(text))
    segs = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        so = SIGNOFF.search(body)
        if so:
            body = body[:so.start()]
        segs.append((SYNOPSIS_TIME.search(m.group(0)), body, m.group(0)))
    return segs


# A statement can begin in the middle of a line, straight after the full stop
# that ends the previous one ("...SEAS 15 TO 20 FT. .48 HOUR FORECAST N OF
# 65N..."). Line-start detection alone would fold that forecast into the
# statement above it; splitting at ". ." keeps every statement judged on its
# own opening words.
MIDLINE_START = re.compile(r"(?<=\.)\s+(?=\.(?!\.)\S)")


def statements(body):
    """Yield (section, warn_cat, statement) with hard-wrapped lines joined.

    A statement starts at a line beginning with a single '.', at a header, or
    after a blank line (the pre-2004 layout has no leading dots at all); every
    other non-blank line continues the statement above it.
    """
    section, cat = None, ""
    cur = []

    def flush():
        if cur:
            st = re.sub(r"\s+", " ", " ".join(cur)).strip()
            del cur[:]
            return [(section, cat, piece) for piece in MIDLINE_START.split(st)]
        return []

    for raw in body.split("\n"):
        s = raw.strip()
        if not s:
            for out in flush():
                yield out
            continue
        # Section and category changes first, so a statement is stamped with
        # the header above it and never the one below.
        h = HEADER.match(s)
        if h and "WARNING" not in h.group(1) and cur and not cur[-1].endswith("."):
            # An untitled-looking "...WORDS..." line in the middle of an
            # unfinished sentence is the wrapped tail of that sentence.
            h = None
        if h or SECTION_WARN.match(s) or SECTION_SYN.match(s):
            for out in flush():
                yield out
            if SECTION_WARN.match(s):
                section, cat = "warning", ""
            elif SECTION_SYN.match(s):
                # The synopsis block carries no warning headers; a category
                # inherited from the warnings above would mislabel its lows.
                section, cat = "synopsis", ""
            else:
                title = h.group(1)
                cat = ""
                for needle, code in CAT_FROM_HEADER:
                    if needle in title:
                        cat = code
                        break
            continue
        if s.startswith(".") and not s.startswith("..."):
            for out in flush():
                yield out
        cur.append(s)
    for out in flush():
        yield out


def is_forecast(st):
    return bool(FORECAST_OPEN.match(st))


def analysis_head(st):
    """The part of an analysis statement that is still about the analysis."""
    # "NW OF FORECAST AREA NEAR 56N 168E" is a real analysis position whose
    # qualifier happens to contain the stop word. Masked at equal length so the
    # cut index still lines up with the original text.
    masked = re.sub(r"\bFORECAST(?=\s+(?:AREA|REGION)\b)", "XXXXXXXX", st)
    m = STOP_WORDS.search(masked)
    return st[:m.start()] if m else st


# --------------------------------------------------------------- lows ------

def lows_in(st, strict=True):
    """(lows, rejected_pressures, positions_cut, positions_refused) for one analysis statement.

    `strict` applies the OPENING / ADDITIONAL rules, which is what keeps
    references and forecasts out of the OPC text. It is turned off only for the
    tropical bulletin, whose statements ("FRONT 23N82W TO LOW PRES 25N93W 1013
    MB") put the low mid-sentence.
    """
    head = analysis_head(st)
    found = []
    rejected = refused = 0
    first = True
    for m in LOW_POS.finditer(head):
        if strict:
            if first:
                ok = bool(OPENING.match(head[:m.start()]))
            else:
                ok = bool(ADDITIONAL.search(head[max(0, m.start() - 40):m.start("lat")]))
            if not ok:
                refused += 1
                continue
        # Looked up in the whole statement: the cut at "AT 0000 UTC" would
        # otherwise hide the very tag being tested for.
        if TIME_TAGGED.match(st, m.end()):
            refused += 1
            continue
        lat = float(m.group("lat"))
        lon = float(m.group("lon"))
        hemi = m.group("h")
        if hemi is None:
            if lon != 180:
                refused += 1
                continue
        elif hemi == "W":
            lon = -lon
        # Nothing OPC analyses lies poleward of 75N; a latitude of 87 is a
        # mistyped 57 and there is no telling which digit was meant.
        if not (0 <= lat <= 75 and -180 <= lon <= 180):
            refused += 1
            continue
        first = False
        pres = None
        if m.group("pres"):
            p = int(m.group("pres"))
            if PRES_MIN <= p <= PRES_MAX:
                pres = p
            else:
                rejected += 1
        # Motion is read only from the text between this position and the next
        # one, so a second low's motion is not credited to the first.
        nxt = LOW_POS.search(head, m.end())
        tail = head[m.end(): nxt.start() if nxt else len(head)]
        mdir, mkt = "", None
        mm = MOTION.search(tail)
        if mm:
            mdir = re.sub(r"\s+", "", mm.group("dir"))
            mkt = int(mm.group("kt"))
        elif STATIONARY.search(tail):
            mkt = 0
        found.append({"lat": lat, "lon": lon, "pres": pres,
                      "mot_dir": mdir, "mot_kt": mkt, "kw": m.group("kw")})
    # The statement is cut at the first forecast marker, so anything dropped
    # there is a position we deliberately did not look at. Counted so that
    # over-cutting shows up as a yield drop instead of vanishing.
    cut = len(LOW_POS.findall(st[len(head):]))
    return found, rejected, cut, refused


def cat_for(kw, header_cat):
    """Header category wins; the pre-2004 layout has no headers, so it falls back to the keyword."""
    if header_cat:
        return header_cat
    k = kw.replace("DEVELOPING ", "")
    if k.startswith("HURRICANE FORCE"):
        return "HF"
    if k == "STORM":
        return "S"
    if k == "GALE":
        return "G"
    return ""


# A WMO abbreviated heading ("FZNT01 KWBC 100420") opens every bulletin on the
# wire, and it - not the AFOS PIL the archive filed the text under - is what
# says what the text is. The archive has bulletins misfiled under these PILs
# (a 4 MB run of SRUS27 hydrology bulletins from KZID sits in HSFAT1), and
# river-stage text read for coordinate pairs and warning headers would be
# attributed to North Atlantic storms. So a bulletin is accepted only when its
# heading is one of the three OPC products, and a record with no heading at all
# is rejected rather than parsed hopefully.
WMO_HEADING = re.compile(
    r"^[ \t]*([A-Z]{4}\d{2})[ \t]+([A-Z]{4})[ \t]+\d{6}(?:[ \t]+[A-Z]{3})?[ \t]*$", re.M)
WMO_PIL = {("FZNT01", "KWBC"): "HSFAT1",
           ("FZPN01", "KWBC"): "HSFEP1",
           ("FZPN02", "KWBC"): "HSFEPI"}


def split_bulletins(text):
    """[(heading "TTAAii CCCC" or None, text)] - one per WMO heading.

    Some archive records carry more than one bulletin (an HSFEP1 followed by
    the HSFEP2 of NHC Miami), so a heading is a hard boundary: nothing before
    it can contribute lows to the bulletin after it. Text that precedes the
    first heading belongs to no bulletin and is ignored.
    """
    marks = list(WMO_HEADING.finditer(text))
    if not marks:
        return [(None, text)]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        # Two headings back to back (one record starts "FZNT01 KWBC 100429 /
        # HSFAT1 / FZNT01 KWBC 092218 / HSFAT1") leave the first with nothing
        # but its PIL line; it is a header, not a bulletin.
        if i + 1 < len(marks) and re.fullmatch(r"\s*(?:HSF[A-Z0-9]{3})?\s*", body):
            continue
        out.append(("%s %s" % (m.group(1), m.group(2)), body))
    return out


def parse_product(text, issued, product_id="", pil="", all_segments=False,
                  stats=None):
    """Parse one archive record.

    Returns a list of analyses, one per accepted OPC bulletin in the record:
    {"pil", "valid" (datetime or None), "rows": [...]}. Normally a record is
    one bulletin and the list has one entry; a rejected record gives [].
    `pil` is the PIL the archive filed the record under; it is only compared
    with the PIL the heading implies, never trusted over it.
    """
    st = stats if stats is not None else Stats()
    analyses = []
    rejected = []
    for heading, btext in split_bulletins(text):
        bpil = WMO_PIL.get(tuple(heading.split())) if heading else None
        if bpil is None:
            rejected.append(heading or "(no WMO heading)")
            continue
        if pil and pil != bpil:
            st.pil_mismatch += 1
        segs = split_segments(btext)
        if not segs:
            st.no_valid += 1
            analyses.append({"pil": bpil, "valid": None, "rows": []})
            continue
        for idx, (m, body, line) in enumerate(segs):
            if idx > 0 and not all_segments:
                # What the tropical block would have contributed, counted so
                # the exclusion is visible, without letting it into the output.
                for sec, cat, s in statements(body):
                    if not is_forecast(s):
                        st.other_segment_lows += len(lows_in(s, strict=False)[0])
                continue
            valid, repaired = synopsis_time(m, line, body, issued)
            if repaired:
                st.month_repaired += 1
                st.repaired_year[valid.year] += 1
            if valid is None:
                if idx == 0:
                    st.no_valid += 1
                    analyses.append({"pil": bpil, "valid": None, "rows": []})
                continue
            rows = []
            for sec, cat, s in statements(body):
                if sec is None:
                    continue
                if is_forecast(s):
                    st.fc_statements += 1
                    continue
                st.an_statements += 1
                found, rej, cut, refused = lows_in(s, strict=(idx == 0))
                st.pres_rejected += rej
                st.cut_after_stop += cut
                st.refused += refused
                if not found and LOW_WORD.search(analysis_head(s)):
                    st.low_no_centre += 1
                    st.low_no_centre_year[valid.year] += 1
                    if len(st.no_centre_examples) < 400:
                        st.no_centre_examples.append((product_id or "-", s))
                for f in found:
                    rows.append({
                        "pil": bpil, "product_id": product_id,
                        "issued": iso(issued), "valid": iso(valid),
                        "section": sec, "warn_cat": cat_for(f["kw"], cat),
                        "lat": f["lat"], "lon": f["lon"], "pres": f["pres"],
                        "mot_dir": f["mot_dir"], "mot_kt": f["mot_kt"], "raw": s})
            analyses.append({"pil": bpil, "valid": valid, "rows": rows, "seg": idx})
    st.rejected_bulletins += len(rejected)
    for h in rejected:
        st.rejected_headings[h] += 1
    if rejected and not analyses:
        st.rejected_records += 1
        st.rejected_year[issued.year] += 1
    return analyses


# -------------------------------------------------------------- stats ------

# Eras for the yield table. The 2002-2005 text is laid out differently from
# everything after it (no leading dots, analysis and forecast in one paragraph,
# STORM/GALE keywords instead of LOW), so it is the era most likely to yield
# thin, and the one the backfill most needs. Reported on its own so a coverage
# trend cannot hide inside per-year noise.
ERAS = [(2002, 2005), (2006, 2010), (2011, 2015), (2016, 2020), (2021, 2099)]
# An era yielding fewer lows per analysis than this share of the median era is
# flagged. Seasons and sampling move the number by tens of percent; a format
# the parser has stopped understanding moves it by much more.
THIN_SHARE = 0.75


def era_of(year):
    for lo, hi in ERAS:
        if lo <= year <= hi:
            return (lo, hi)
    return (year, year)


class Stats:
    def __init__(self):
        self.products = 0
        self.no_valid = 0
        self.fc_statements = 0
        self.an_statements = 0
        self.pres_rejected = 0
        self.cut_after_stop = 0
        self.refused = 0
        self.no_centre_examples = []
        self.low_no_centre = 0
        self.other_segment_lows = 0
        self.dup_dropped = 0
        self.rejected_records = 0        # records with no accepted OPC bulletin
        self.rejected_bulletins = 0
        self.pil_mismatch = 0
        self.month_repaired = 0
        self.repaired_year = Counter()
        self.rejected_year = Counter()   # by year of `issued`: no valid time exists
        self.rejected_headings = Counter()
        self.low_no_centre_year = Counter()
        self.prod_year = Counter()       # analyses with a valid time, by year
        self.nov_year = Counter()        # analyses whose valid time failed
        self.lows_year = Counter()
        self.lows_pres_year = Counter()
        self.lows_hf_year = Counter()
        self.empty_year = Counter()      # valid analyses that yielded no low

    def _table(self, w, label, keyf, keys):
        w("  %-9s analyses  no-valid  empty  lows  with-pres  HF-hdr  lows/an  pres/an" % label)
        agg = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0])
        for y in sorted(set(self.prod_year) | set(self.nov_year) | set(self.lows_year)):
            a = agg[keyf(y)]
            for i, v in enumerate((self.prod_year[y], self.nov_year[y], self.empty_year[y],
                                   self.lows_year[y], self.lows_pres_year[y],
                                   self.lows_hf_year[y])):
                a[i] += v
        per = {}
        for k in sorted(agg):
            n, nv, em, lo, lp, hf, _ = agg[k]
            per[k] = (lo / n if n else 0.0)
            w("  %-9s %8d  %8d  %5d  %4d  %9d  %6d  %7.2f  %7.2f" % (
                keys(k), n, nv, em, lo, lp, hf, per[k], (lp / n if n else 0.0)))
        return per

    def _rej_eras(self):
        out = Counter()
        for y, n in self.rejected_year.items():
            out[era_of(y)] += n
        return out

    def report(self, file=sys.stderr):
        w = lambda s="": print(s, file=file)
        w("parse_hsf statistics")
        w("  products read                       %7d" % self.products)
        w("  records rejected on WMO heading     %7d" % self.rejected_records)
        w("  valid time not determined           %7d" % self.no_valid)
        w("  valid time repaired (month typo)    %7d" % self.month_repaired)
        w("  duplicate analyses dropped          %7d" % self.dup_dropped)
        w("  statements, analysis                %7d" % self.an_statements)
        w("  statements, forecast (not emitted)  %7d" % self.fc_statements)
        w("  positions cut after a forecast word %7d" % self.cut_after_stop)
        w("  positions refused (prefix/tag/form) %7d" % self.refused)
        w("  analysis LOW statements, no centre  %7d" % self.low_no_centre)
        w("  pressures rejected (outside %d-%d) %7d" % (PRES_MIN, PRES_MAX, self.pres_rejected))
        w("  lows in non-OPC bulletins, excluded %7d" % self.other_segment_lows)
        w("  lows emitted                        %7d" % sum(self.lows_year.values()))
        w("  (an analysis = one OPC bulletin after de-duplication on pil+valid time)")
        if self.pil_mismatch:
            w("  bulletins filed under a PIL other than their heading's %d" % self.pil_mismatch)
        if self.rejected_bulletins:
            w()
            w("  rejected on WMO heading, by heading: " + ", ".join(
                "%s x%d" % (h, n) for h, n in self.rejected_headings.most_common(8)))
            w("  rejected records by era (issued year): " + (", ".join(
                "%s: %d" % ("%d-%d" % e if e[1] < 2099 else "%d+" % e[0], n)
                for e, n in sorted(self._rej_eras().items())) or "none"))
        w()
        w("  analysis lows with a pressure, by year:")
        self._table(w, "year", lambda y: y, lambda k: "%d" % k)
        w()
        per = self._table(w, "era", era_of, lambda k: "%d-%d" % k if k[1] < 2099 else "%d+" % k[0])
        vals = sorted(v for v in per.values() if v > 0)
        if len(vals) >= 2:
            med = vals[len(vals) // 2]
            for k, v in per.items():
                if v < THIN_SHARE * med:
                    w("  WARNING: era %s yields %.2f lows/analysis against a median of %.2f"
                      " - thin, check the parser for that era" % (k, v, med))


def tally(stats, valid, rows, issued=None):
    """Credit an analysis to the year of its ANALYSIS time."""
    if valid is None:
        stats.nov_year[(issued or datetime.now(timezone.utc)).year] += 1
        return
    y = valid.year
    stats.prod_year[y] += 1
    if not rows:
        stats.empty_year[y] += 1
    for r in rows:
        stats.lows_year[y] += 1
        if r["pres"] is not None:
            stats.lows_pres_year[y] += 1
        if r["warn_cat"] == "HF":
            stats.lows_hf_year[y] += 1


# ----------------------------------------------------------------- I/O -----

def fmt_row(r):
    return [r["pil"], r["product_id"], r["issued"], r["valid"], r["section"],
            r["warn_cat"], "%.1f" % r["lat"], "%.1f" % r["lon"],
            "" if r["pres"] is None else r["pres"],
            r["mot_dir"], "" if r["mot_kt"] is None else r["mot_kt"], r["raw"]]


def iter_cache(cache_dir, pils=None):
    """Yield (pil, record) for every cached product, oldest month first."""
    for d in sorted(glob.glob(os.path.join(cache_dir, "HSF*"))):
        pil = os.path.basename(d)
        if pils and pil not in pils:
            continue
        for fn in sorted(glob.glob(os.path.join(d, "*.jsonl.gz"))):
            with gzip.open(fn, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield pil, json.loads(line)


def dedupe(analyses, stats):
    """One analysis per (basin, synopsis time); the later transmission wins.

    The archive holds each bulletin more than once: a re-transmission minutes
    later (04:20 and 04:23 for one 0430 UTC bulletin), -RRA/-CCA/-CCB
    corrections, HSFEPI beside HSFEP1, and same-minute transmissions that share
    a product id and differ only in the LDM sequence number (or, when they
    differ meteorologically, in being the correction). All share a synopsis
    time, and keeping them all would count one low several times.

    HSFEP1 beats HSFEPI (the spec's preference). Within a PIL the later
    transmission wins: later `issued` first, then, among equals, the one read
    last, because the cache keeps products in the order the archive served
    them, which is transmission order. One rule covers amendments and
    same-minute repeats. `issued` is the archive's entry time, not the header
    time, so it only orders transmissions.
    """
    best = {}
    for a in analyses:
        key = (PIL_BASIN.get(a["pil"], a["pil"]), a["valid"], a.get("seg", 0))
        cur = best.get(key)
        if cur is not None:
            stats.dup_dropped += 1
        if cur is None or _supersedes(a, cur):
            best[key] = a
    return list(best.values())


def _supersedes(a, b):
    """True if analysis `a` should replace `b` for the same synopsis time."""
    ra, rb = PIL_RANK.get(a["pil"], 9), PIL_RANK.get(b["pil"], 9)
    if ra != rb:
        return ra < rb
    if a["issued_dt"] != b["issued_dt"]:
        return a["issued_dt"] > b["issued_dt"]
    return a["seq"] > b["seq"]


def run_cache(args):
    stats = Stats()
    parsed = []
    for pil, rec in iter_cache(args.cache, set(args.pil) if args.pil else None):
        stats.products += 1
        try:
            issued = parse_iso(rec["issued"])
        except (KeyError, ValueError):
            stats.no_valid += 1
            continue
        pid = rec.get("product_id", "")
        for a in parse_product(rec.get("text", ""), issued, pid, pil,
                               args.all_segments, stats):
            a["issued_dt"], a["product_id"], a["seq"] = issued, pid, stats.products
            if a["valid"] is None:
                tally(stats, None, [], issued)
            else:
                parsed.append(a)
    # Tally after de-duplication so a re-transmitted bulletin is not counted
    # twice in the yield table.
    out = []
    for a in dedupe(parsed, stats):
        tally(stats, a["valid"], a["rows"])
        out.extend(a["rows"])
    out.sort(key=lambda r: (r["valid"], r["pil"], r["product_id"]))
    return out, stats


def run_text(args):
    stats = Stats()
    text = sys.stdin.read() if args.from_text == "-" else open(
        args.from_text, encoding="utf-8", errors="replace").read()
    name = "" if args.from_text == "-" else os.path.splitext(
        os.path.basename(args.from_text))[0]
    pid = args.product_id or name
    if args.issued:
        issued = parse_iso(args.issued)
    elif re.match(r"\d{12}-", pid):
        issued = datetime.strptime(pid[:12], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    else:
        issued = issued_from_text(text)
    if issued is None:
        sys.exit("cannot determine the issue time; pass --issued YYYY-MM-DDTHH:MM:SSZ")
    stats.products = 1
    rows = []
    for a in parse_product(text, issued, pid, args.pil[0] if args.pil else "",
                           args.all_segments, stats):
        tally(stats, a["valid"], a["rows"], issued)
        rows.extend(a["rows"])
    return rows, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-text", metavar="FILE",
                    help="parse one raw product ('-' for stdin) instead of the cache")
    ap.add_argument("--issued", help="issue time of a --from-text product, ISO 8601 Z")
    ap.add_argument("--product-id", help="product id to record for a --from-text product")
    ap.add_argument("--cache", default=CACHE_DIR, help="cache directory (default %(default)s)")
    ap.add_argument("--out", help="CSV path ('-' for stdout); default data/hf_lows/hsf_lows.csv, "
                                  "or stdout with --from-text")
    ap.add_argument("--pil", action="append", help="restrict to a PIL (repeatable)")
    ap.add_argument("--all-segments", action="store_true",
                    help="also emit lows from the tropical bulletin that follows OPC's text "
                         "(off: those are NHC/TAFB lows, outside this series)")
    ap.add_argument("--quiet", action="store_true", help="suppress the statistics")
    ap.add_argument("--show-unmatched", action="store_true",
                    help="list analysis statements that name a LOW but yielded no centre, "
                         "to audit what the parser is leaving behind")
    args = ap.parse_args(argv)

    rows, stats = run_text(args) if args.from_text else run_cache(args)
    out = args.out or ("-" if args.from_text else OUT_CSV)
    if out == "-":
        fh = sys.stdout
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        fh = open(out, "w", newline="", encoding="utf-8")
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow(fmt_row(r))
    if fh is not sys.stdout:
        fh.close()
    if not args.quiet:
        stats.report()
        if args.show_unmatched:
            seen = set()
            for pid, st_ in stats.no_centre_examples:
                key = re.sub(r"\d+", "#", st_[:70])
                if key not in seen:
                    seen.add(key)
                    print("  unmatched %s: %s" % (pid[:12], st_[:150]), file=sys.stderr)
        if out != "-":
            print("  wrote %s (%d rows)" % (out, len(rows)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
