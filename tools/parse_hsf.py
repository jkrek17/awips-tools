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

# Headers are "...WORDS..." on a line of their own. Requiring the closing dots
# matters: a hard wrap can leave a continuation line that starts with "..."
# ("...AND E OF 59N N OF 45N."), and that must stay part of its statement.
HEADER = re.compile(r"^\.{3}\s*([A-Z][A-Z /&-]*?)\s*\.{3}$")
SECTION_WARN = re.compile(r"^\.?\s*WARNINGS\s*\.?$")
SECTION_SYN = re.compile(r"^\.?\s*SYNOPSIS\s+AND\s+FORECAST\s*\.?$")

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
LOW_KEYWORD = (r"(?:LOW(?:\s+PRES(?:SURE)?)?"
               r"|(?:MEAN|MAIN|SECONDARY|SECOND|THIRD|ONE|FIRST)\s+CENTER"
               r"|(?:DEVELOPING\s+)?(?:HURRICANE\s+FORCE\s+LOW|STORM|GALE))")
LOW_QUALIFIER = (r"(?:(?:JUST|WELL|NEAR|INLAND|RELOCATED"
                 r"|(?:N|S|E|W|NE|NW|SE|SW)\s+OF\s+(?:THE\s+)?(?:FORECAST\s+)?(?:AREA|REGION))\s+){0,4}")
LOW_POS = re.compile(
    r"\b(?P<kw>" + LOW_KEYWORD + r")(?:\s+|\.\.\.)" + LOW_QUALIFIER +
    r"(?P<lat>\d{1,2}(?:\.\d)?)\s*N\s*"
    r"(?P<lon>\d{1,3}(?:\.\d)?)(?:\s*(?P<h>[EW])\b|(?=\s))"
    # A pressure is 3-4 digits not followed by a unit. "120 NM" after a
    # position is a radius, not a pressure.
    r"(?:\s+(?P<pres>\d{3,4})(?!\d)(?!\s*(?:NM|KT|FT|N\b|S\b|E\b|W\b))(?:\s*(?:MB|HPA))?)?")

# What may precede the FIRST position in a statement. An analysis statement
# opens with its low, so anything else in front of a position ("IN ASSOCIATION
# WITH THE DEVELOPING STORM 38N 59W ... AT 0000 UTC 2 JAN", "EXCEPT WHERE NOTED
# WITH LOW 54N 53W") is a reference to a low described elsewhere or a position
# valid at another time, and taking it would duplicate a low or smuggle in a
# forecast. The words listed are the ones OPC puts in front of a real centre.
OPENING = re.compile(
    r"^\.*\s*(?:(?:COMPLEX|SYSTEM|LOW|WITH|ONE|FIRST|MAIN|MEAN|DEVELOPING"
    r"|HURRICANE|FORCE|INLAND)\s+)*$")
# A later position in the same statement is accepted only as a named additional
# centre of a complex system ("...AND A SECOND LOW 36N 140W 1004 MB").
ADDITIONAL = re.compile(
    r"\b(?:AND|WITH|\.\.\.)\s*(?:A\s+)?(?:SECOND|SECONDARY|THIRD)\s+(?:LOW|CENTER)\b")
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
    """[(time_match_or_None, body)] - one per 'SYNOPSIS VALID' line.

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
        segs.append((SYNOPSIS_TIME.search(m.group(0)), body))
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
        if TIME_TAGGED.match(head, m.end()):
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


def pil_of(product_id, default=""):
    m = re.search(r"(HSF[A-Z0-9]{3})(?:-[A-Z0-9]+)?$", product_id or "")
    return m.group(1) if m else default


def parse_product(text, issued, product_id="", pil="", all_segments=False,
                  stats=None):
    """Parse one product. Returns (valid or None, [row dicts])."""
    st = stats if stats is not None else Stats()
    pil = pil or pil_of(product_id)
    segs = split_segments(text)
    if not segs:
        st.no_valid += 1
        return None, []
    valid0 = None
    rows = []
    for idx, (m, body) in enumerate(segs):
        if idx > 0 and not all_segments:
            # Count what the tropical block would have contributed so the
            # exclusion is visible, without letting any of it into the output.
            for sec, cat, s in statements(body):
                if not is_forecast(s):
                    st.other_segment_lows += len(lows_in(s, strict=False)[0])
            continue
        mon = MONTHS.get(m.group(2)) if m else None
        valid = resolve_year(m.group(1), mon, int(m.group(3)), issued) if mon else None
        if idx == 0:
            valid0 = valid
        if valid is None:
            if idx == 0:
                st.no_valid += 1
            continue
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
                    "pil": pil, "product_id": product_id, "issued": iso(issued),
                    "valid": iso(valid), "section": sec,
                    "warn_cat": cat_for(f["kw"], cat),
                    "lat": f["lat"], "lon": f["lon"], "pres": f["pres"],
                    "mot_dir": f["mot_dir"], "mot_kt": f["mot_kt"], "raw": s})
    return valid0, rows


# -------------------------------------------------------------- stats ------

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
        self.low_no_centre_year = Counter()
        self.prod_year = Counter()       # products with a valid time, by year
        self.nov_year = Counter()        # products whose valid time failed
        self.lows_year = Counter()
        self.lows_pres_year = Counter()
        self.lows_hf_year = Counter()
        self.empty_year = Counter()      # valid products that yielded no low

    def report(self, file=sys.stderr):
        w = lambda s="": print(s, file=file)
        w("parse_hsf statistics")
        w("  products read                      %7d" % self.products)
        w("  valid time not determined          %7d" % self.no_valid)
        w("  duplicate products dropped         %7d" % self.dup_dropped)
        w("  statements, analysis               %7d" % self.an_statements)
        w("  statements, forecast (not emitted) %7d" % self.fc_statements)
        w("  positions cut after a forecast word %6d" % self.cut_after_stop)
        w("  positions refused (prefix/tag/form) %6d" % self.refused)
        w("  analysis LOW statements, no centre  %6d" % self.low_no_centre)
        w("  pressures rejected (outside %d-%d) %7d" % (PRES_MIN, PRES_MAX, self.pres_rejected))
        w("  lows in non-OPC segments, excluded %7d" % self.other_segment_lows)
        w("  lows emitted                       %7d" % sum(self.lows_year.values()))
        w()
        w("  year  products  no-valid  empty  lows  with-pres  HF-hdr  lows/prod  no-centre")
        years = sorted(set(self.prod_year) | set(self.nov_year) | set(self.lows_year))
        for y in years:
            n = self.prod_year[y]
            w("  %d  %8d  %8d  %5d  %4d  %9d  %6d  %9.2f  %9d" % (
                y, n, self.nov_year[y], self.empty_year[y], self.lows_year[y],
                self.lows_pres_year[y], self.lows_hf_year[y],
                (self.lows_year[y] / n) if n else 0.0,
                self.low_no_centre_year[y]))


def tally(stats, issued, valid, rows):
    """Credit a product's outcome to the year of its ANALYSIS time."""
    y = (valid or issued).year
    if valid is None:
        stats.nov_year[y] += 1
        return
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


def dedupe(parsed, stats):
    """One product per (basin, synopsis time).

    The wire carries each issuance more than once - a re-transmission minutes
    later, an -RRA/-CCA correction, and HSFEPI beside HSFEP1 - and the
    duplicates share a synopsis time. Prefer HSFEP1 over HSFEPI, then the
    latest issuance, because a correction supersedes what it corrects.
    """
    best = {}
    for p in parsed:
        key = (PIL_BASIN.get(p["pil"], p["pil"]), p["valid"])
        cur = best.get(key)
        rank = (PIL_RANK.get(p["pil"], 9), -p["issued_dt"].timestamp())
        if cur is None or rank < cur[0]:
            if cur is not None:
                stats.dup_dropped += 1
            best[key] = (rank, p)
        else:
            stats.dup_dropped += 1
    return [v[1] for v in best.values()]


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
        valid, rows = parse_product(rec.get("text", ""), issued,
                                    rec.get("product_id", ""), pil,
                                    args.all_segments, stats)
        parsed.append({"pil": pil, "valid": valid, "issued_dt": issued,
                       "rows": rows})
        if valid is None:
            tally(stats, issued, None, rows)
    # Tally after de-duplication so a doubly-transmitted product is not
    # counted twice in the yield table.
    keep = dedupe([p for p in parsed if p["valid"] is not None], stats)
    out = []
    for p in keep:
        tally(stats, p["issued_dt"], p["valid"], p["rows"])
        out.extend(p["rows"])
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
    valid, rows = parse_product(text, issued, pid, args.pil[0] if args.pil else "",
                                args.all_segments, stats)
    tally(stats, issued, valid, rows)
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
