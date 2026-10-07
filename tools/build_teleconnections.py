#!/usr/bin/env python3
"""Build the climate teleconnection index series baked into the site data.

Why this exists: the archive's explosive-cyclogenesis events need large-scale
context - ENSO phase, the NAO/PNA/AO state around genesis, and where the MJO
was a week or two earlier. This script fetches those indices once, at build
time, and writes them as plain daily/monthly time series. It does NOT do any
per-event attribution; whoever attributes events looks values up in this file.

Sources (all fetched here; the site itself makes no runtime requests):
    ONI   NOAA CPC, 3-month overlapping seasons (monthly)
          https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
    NAO, PNA, AO   NOAA CPC daily, 1950-01-01 on
          https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.{nao,pna,ao}.index.b500101.current.ascii
    MJO   Australian Bureau of Meteorology RMM, daily, 1974-06-01 on
          https://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt
CPC/NOAA data are U.S. Government work, public domain. The BoM file is NOT
automatically public domain - it is Commonwealth of Australia material under
the Bureau's own copyright notice - so its attribution/licence is recorded as
UNCONFIRMED in the output and main() prints that on every run. BoM's server
also answers a plain scripted request with a "does not support web scraping"
block page (HTTP 403); a User-Agent is required, and even with one the fetch
may be refused. If it is, download the file by hand (BoM points automated
users at its anonymous FTP service, which is subject to the same copyright
notice) and pass --rmm-input FILE, or build without MJO using --no-mjo. This
tool never disguises its User-Agent to get past that block.

Things that are easy to get wrong, and are handled explicitly:

* CPC daily files are fixed-width. A negative value butts up against the day
  field ("2006 10 26-99.000"), so a whitespace split sees three columns and
  silently drops or mis-reads exactly the missing-value rows. parse_cpc_daily()
  uses a regex that does not need a separator. The only sentinel actually
  present in these three files is -99.000 (2 days in NAO and PNA, 1 in AO);
  any other implausible value stops the build rather than being guessed at.
* The RMM index is NOT one homogeneous definition. Per the file's own header,
  1974-06-01 to 2013-12-31 has both SST1 (ENSO-related) variability and the
  120-day mean removed (method WH04), while 2014-01-01 on has only the
  120-day mean removed (method Gottschalk10). The trailing method column
  switches at that boundary. Every RMM day carries an epoch id into the
  "epochs" list so a consumer can restrict a composite to a single definition;
  an unrecognised method label stops the build instead of being merged in.
* RMM stops well before the CPC series do. The output's mjo block carries
  "noDataAfter" (the last day with a valid RMM value) and its arrays end
  there - they are never padded with nulls out to the CPC end date, because a
  null run would read as "quiet MJO" rather than "no data". Trailing sentinel
  rows are trimmed; sentinel rows in the interior (1.E36 / 999) become null.
* The ONI season for a date is the 3-month season CENTERED on the date's
  calendar month (15 Jan 2016 -> DJF 2016, i.e. Dec 2015 - Feb 2016, the file's
  own labelling: YR is the year of the centre month). Phase is the threshold
  class (>= +0.5 El Nino, <= -0.5 La Nina, else Neutral). CPC only calls an
  *episode* after 5 consecutive overlapping seasons past the threshold, so a
  separate "episode" flag says whether the season sits in such a run (1), does
  not (0), or cannot be told because the data ends mid-run (null).

Output shape (decision, with reasons): every series is a DENSE array, one slot
per calendar day (ONI: per month) from "start", nulls for missing. That makes
the date key implicit and exact - index = days since start - so a consumer
windows it with plain array arithmetic and cannot get a gap wrong. It is also
what keeps the payload small: carrying a date string per value would roughly
triple it. Antecedent means and lagged MJO values are NOT pre-computed: the
5-day mean is a trivial window over the daily array, and the MJO lag (5-15
days is a research choice - one lag, a range, a composite) would multiply the
payload by the number of lags to save a few array reads. The one definition
every consumer must share is written into the payload ("derived.mean5"):
mean of days d-4..d inclusive, null unless all five are present.

Trimming: the source series start in 1950 / 1974; the archive only needs 2001
on, so daily series start at --start (default 2001-05-01, a month ahead of the
first 1 June season so the antecedent window and MJO lags up to ~31 days have
data for the earliest events). ONI is trimmed to the same start month. The
CPC end date and the ONI end are whatever the source holds.

Writes:
    docs/data/teleconnections.js     window.HF_TELECONNECTIONS = {...}   (works from file://)
    docs/data/teleconnections.json   same payload, plain JSON

Usage:
    python3 tools/build_teleconnections.py                  # fetch, build, write
    python3 tools/build_teleconnections.py --check           # build, but write nothing
    python3 tools/build_teleconnections.py --rmm-input FILE  # local RMM file (BoM blocked)
    python3 tools/build_teleconnections.py --no-mjo          # build without MJO
    python3 tools/build_teleconnections.py --coverage        # also print per-season counts
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA_VERSION = 1

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
CPC_DAILY_URL = ("https://ftp.cpc.ncep.noaa.gov/cwlinks/"
                 "norm.daily.{name}.index.b500101.current.ascii")
RMM_URL = "https://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
BOM_COPYRIGHT_URL = "http://www.bom.gov.au/other/copyright.shtml"

# Honest, descriptive UA. BoM refuses requests without one.
USER_AGENT = "awips-tools/build_teleconnections (build-time research data fetch; no runtime scraping)"

DEFAULT_START = "2001-05-01"

ROUND_DIGITS = 3               # CPC publishes 3 decimals; RMM is rounded to match

# ONI thresholds - the standard CPC definition. Inclusive on both sides.
EL_NINO_MIN = 0.5
LA_NINA_MAX = -0.5
CPC_EPISODE_MIN_SEASONS = 5    # consecutive overlapping seasons for an official episode

# Anything at or below this in a CPC daily file is a missing-value sentinel
# (-99.0 is what the files use; this also catches -99.9 / -999 should they
# ever appear). Between this and PLAUSIBLE_ABS the value is real; beyond
# PLAUSIBLE_ABS but above the sentinel cut is neither, and stops the build.
CPC_SENTINEL_AT_OR_BELOW = -90.0
CPC_PLAUSIBLE_ABS = 20.0       # observed extremes are |AO| ~ 7.4

# RMM missing-value markers: 1.E36 in the component/amplitude columns, 999 in
# phase. Anything this large is a sentinel; real components are O(1-5).
RMM_SENTINEL_AT_OR_ABOVE = 900.0

# RMM method labels as they appear in the trailing column, keyed by the id
# written to the output. Order here is chronological. The definition text
# mirrors the file's own header (also captured verbatim into sourceHeader).
RMM_METHODS = [
    {"id": "WH04", "pattern": re.compile(r"WH04", re.I), "label": "WH04_method",
     "expectedStart": "1974-06-01", "expectedEnd": "2013-12-31",
     "definition": "Both SST1 variability (ENSO) and the 120-day mean removed"},
    {"id": "Gottschalk10", "pattern": re.compile(r"Gottschalk", re.I), "label": "Gottschalk10_method",
     "expectedStart": "2014-01-01", "expectedEnd": None,
     "definition": "Only the 120-day mean removed (ENSO-related SST1 variability NOT removed)"},
]

ONI_SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]

FETCH_RETRIES = 4
FETCH_TIMEOUT_S = 60

_CPC_RE = re.compile(r"^\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s*(-?\d+(?:\.\d+)?)\s*$")


class FetchBlocked(RuntimeError):
    """The server answered, but refused (4xx). Not retried: retrying a
    refusal just repeats it."""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def http_get(url: str) -> str:
    """GET with retry/backoff on network errors and 5xx. A 4xx is a refusal,
    not a glitch, so it raises FetchBlocked immediately (BoM's 403 for an
    automated client is the case that matters here)."""
    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(FETCH_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, context=ctx, timeout=FETCH_TIMEOUT_S) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as err:
            if 400 <= err.code < 500:
                raise FetchBlocked(f"{url}: HTTP {err.code} {err.reason}") from err
            last_err = err
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err:
            last_err = err
        if attempt == FETCH_RETRIES - 1:
            break
        wait = 2 ** attempt
        print(f"  fetch failed ({last_err}) - retrying in {wait}s "
              f"(attempt {attempt + 2}/{FETCH_RETRIES})...", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError(f"giving up on {url}: {last_err}")


def today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def iso(d: dt.date) -> str:
    return d.isoformat()


def parse_cpc_daily(text: str, name: str):
    """CPC daily index -> (list of (date, value-or-None), Counter of sentinel
    tokens seen). Dates must run strictly one day at a time; a gap or a
    repeat means the file is not what this tool was written against, so it
    stops rather than letting positional arithmetic downstream go quietly
    wrong."""
    rows = []
    sentinels = Counter()
    prev = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        m = _CPC_RE.match(line)
        if not m:
            raise RuntimeError(f"{name}: line {lineno} not in 'YYYY M D value' form: {line!r}")
        day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if prev is not None and (day - prev).days != 1:
            raise RuntimeError(f"{name}: line {lineno}: {day} does not follow {prev} by one day")
        prev = day
        raw = m.group(4)
        v = float(raw)
        if v <= CPC_SENTINEL_AT_OR_BELOW:
            sentinels[raw] += 1
            rows.append((day, None))
        elif abs(v) > CPC_PLAUSIBLE_ABS:
            raise RuntimeError(f"{name}: line {lineno}: value {raw} is neither a known "
                               f"sentinel nor plausible - inspect the source")
        else:
            rows.append((day, round(v, ROUND_DIGITS)))
    if not rows:
        raise RuntimeError(f"{name}: no data rows parsed")
    return rows, sentinels


def parse_oni(text: str):
    """ONI file -> list of (year, month, oni) keyed by the CENTRE month of
    each 3-month season, contiguous. The file's YR is the year of the centre
    month, so DJF 2016 is centred on Jan 2016."""
    out = []
    prev = None
    for lineno, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if len(parts) != 4 or parts[0] == "SEAS":
            if parts and parts[0] != "SEAS":
                raise RuntimeError(f"ONI: line {lineno} unexpected: {line!r}")
            continue
        seas, yr, _total, anom = parts
        if seas not in ONI_SEASONS:
            raise RuntimeError(f"ONI: line {lineno}: unknown season {seas!r}")
        year, month = int(yr), ONI_SEASONS.index(seas) + 1
        if prev is not None and (year * 12 + month) - (prev[0] * 12 + prev[1]) != 1:
            raise RuntimeError(f"ONI: line {lineno}: {seas} {yr} does not follow previous season")
        prev = (year, month)
        v = float(anom)
        out.append((year, month, None if v <= -90 else round(v, 2)))
    if not out:
        raise RuntimeError("ONI: no data rows parsed")
    return out


def parse_rmm(text: str):
    """BoM RMM file -> (header_lines, rows, sentinel Counter). Each row is a
    dict: date, rmm1, rmm2, phase, amp, method (id or None). Header lines are
    whatever precedes the first data row; once data starts, anything
    unparseable is an error. Method is resolved from the trailing label and
    must be one of RMM_METHODS for any row that carries a valid value."""
    header, rows = [], []
    sentinels = Counter()
    prev = None
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[,\s]+", s) if p]
        try:
            y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
            r1, r2, ph, amp = (float(parts[3]), float(parts[4]),
                               float(parts[5]), float(parts[6]))
        except (ValueError, IndexError):
            if rows:
                raise RuntimeError(f"RMM: line {lineno} unparseable after data began: {s!r}")
            header.append(s)
            continue
        note = " ".join(parts[7:])
        day = dt.date(y, mo, d)
        if prev is not None and (day - prev).days != 1:
            raise RuntimeError(f"RMM: line {lineno}: {day} does not follow {prev} by one day")
        prev = day

        missing = (abs(r1) >= RMM_SENTINEL_AT_OR_ABOVE or abs(r2) >= RMM_SENTINEL_AT_OR_ABOVE
                   or abs(amp) >= RMM_SENTINEL_AT_OR_ABOVE or abs(ph) >= RMM_SENTINEL_AT_OR_ABOVE)
        if missing:
            for tok in parts[3:7]:
                if abs(float(tok)) >= RMM_SENTINEL_AT_OR_ABOVE:
                    sentinels[tok] += 1
            rows.append({"date": day, "rmm1": None, "rmm2": None, "phase": None,
                         "amp": None, "method": None})
            continue
        if ph != int(ph) or not (1 <= int(ph) <= 8):
            raise RuntimeError(f"RMM: line {lineno}: phase {parts[5]} is neither 1-8 nor a "
                               f"known sentinel: {s!r}")
        method = next((m["id"] for m in RMM_METHODS if m["pattern"].search(note)), None)
        if method is None:
            raise RuntimeError(f"RMM: line {lineno}: unrecognised method label {note!r} - the "
                               f"definition may have changed again; add it to RMM_METHODS "
                               f"deliberately rather than merging it into an existing epoch")
        rows.append({"date": day, "rmm1": round(r1, ROUND_DIGITS), "rmm2": round(r2, ROUND_DIGITS),
                     "phase": int(ph), "amp": round(amp, ROUND_DIGITS), "method": method})
    if not rows:
        raise RuntimeError("RMM: no data rows parsed")
    return header, rows, sentinels


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def phase_of(v):
    if v is None:
        return None
    if v >= EL_NINO_MIN:
        return "E"
    if v <= LA_NINA_MAX:
        return "L"
    return "N"


def episode_flags(phases):
    """CPC episode membership over the FULL ONI record (before trimming, so
    a run that straddles the trim point is measured whole): 1 if the season is
    in a run of >= 5 consecutive same-sign E/L seasons, 0 if not, None if the
    run touches the end of the data and is still shorter than 5 (cannot be
    told yet) or the value is missing."""
    n = len(phases)
    flags = [0] * n
    i = 0
    while i < n:
        p = phases[i]
        if p in ("E", "L"):
            j = i
            while j + 1 < n and phases[j + 1] == p:
                j += 1
            length = j - i + 1
            for k in range(i, j + 1):
                if length >= CPC_EPISODE_MIN_SEASONS:
                    flags[k] = 1
                elif j == n - 1:
                    flags[k] = None
            i = j + 1
        else:
            if p is None:
                flags[i] = None
            i += 1
    return flags


def dense(rows, start: dt.date, end: dt.date):
    """rows [(date, value)] -> list of values, one per day start..end, None
    where the source has no row."""
    by_day = dict(rows)
    n = (end - start).days + 1
    return [by_day.get((start + dt.timedelta(days=i))) for i in range(n)]


def build_oni(rows, start: dt.date, retrieved: str):
    phases_all = [phase_of(v) for _y, _m, v in rows]
    flags_all = episode_flags(phases_all)
    keep = [i for i, (y, m, _v) in enumerate(rows) if (y, m) >= (start.year, start.month)]
    if not keep:
        raise RuntimeError("ONI: nothing left after trimming to --start")
    sel = [rows[i] for i in keep]
    return {
        "source": "NOAA Climate Prediction Center, Oceanic Nino Index (ERSSTv5, 3-month running mean of Nino-3.4 SST anomalies)",
        "url": ONI_URL,
        "retrieved": retrieved,
        "license": "U.S. Government work; public domain",
        "attribution": "NOAA/NWS Climate Prediction Center",
        "units": "degC",
        "thresholds": {"elNino": EL_NINO_MIN, "laNina": LA_NINA_MAX},
        "seasonMapping": ("Monthly array keyed by the CENTRE month of each 3-month season "
                          "(DJF 2016 -> 2016-01). For an event date use the season centred on "
                          "the date's calendar month: index = (year - startYear) * 12 + "
                          "(month - startMonth)."),
        "phase": "E = El Nino (>= +0.5), L = La Nina (<= -0.5), N = Neutral; threshold class of the single season",
        "episode": ("1 if the season is within a CPC episode (>= 5 consecutive overlapping seasons "
                    "at/past the same threshold), 0 if not, null if undeterminable because the "
                    "data ends mid-run"),
        "start": f"{sel[0][0]:04d}-{sel[0][1]:02d}",
        "end": f"{sel[-1][0]:04d}-{sel[-1][1]:02d}",
        "n": len(sel),
        "seas": [ONI_SEASONS[m - 1] for _y, m, _v in sel],
        "values": [v for _y, _m, v in sel],
        "phases": [phases_all[i] for i in keep],
        "episodes": [flags_all[i] for i in keep],
    }, {"sourceSpan": (f"{rows[0][0]:04d}-{rows[0][1]:02d}", f"{rows[-1][0]:04d}-{rows[-1][1]:02d}"),
        "trimmedSeasons": len(rows) - len(sel)}


def build_cpc(name: str, label: str, rows, sentinels: Counter, start: dt.date, retrieved: str):
    src_start, src_end = rows[0][0], rows[-1][0]
    first = max(start, src_start)
    full = dense(rows, first, src_end)
    n_missing = sum(1 for v in full if v is None)
    return {
        "source": f"NOAA Climate Prediction Center, daily {label} index (norm.daily.{name}.index.b500101)",
        "url": CPC_DAILY_URL.format(name=name),
        "retrieved": retrieved,
        "license": "U.S. Government work; public domain",
        "attribution": "NOAA/NWS Climate Prediction Center",
        "units": "standardized index (dimensionless)",
        "start": iso(first),
        "end": iso(src_end),
        "n": len(full),
        "missing": n_missing,
        "values": full,
    }, {"sourceSpan": (iso(src_start), iso(src_end)),
        "sourceDays": len(rows),
        "trimmedDays": (first - src_start).days,
        "sentinels": dict(sentinels),
        "missingInSource": sum(1 for _d, v in rows if v is None)}


def build_mjo(header, rows, sentinels: Counter, start: dt.date, retrieved: str, source_note: str):
    valid = [r for r in rows if r["method"] is not None]
    if not valid:
        raise RuntimeError("RMM: every row is a missing-value sentinel")
    src_start, src_end = rows[0]["date"], rows[-1]["date"]
    last_valid = valid[-1]["date"]
    trailing_missing = (src_end - last_valid).days

    # Epochs, discovered from the data rather than assumed, then checked
    # against the boundary the file header declares.
    seen = []
    for r in valid:
        if not seen or seen[-1]["id"] != r["method"]:
            if any(e["id"] == r["method"] for e in seen):
                raise RuntimeError(f"RMM: method {r['method']} reappears after another - "
                                   f"epochs are not contiguous; refusing to guess")
            seen.append({"id": r["method"], "start": r["date"], "end": r["date"], "n": 0})
        seen[-1]["end"] = r["date"]
        seen[-1]["n"] += 1
    epochs = []
    boundary_warnings = []
    for i, e in enumerate(seen):
        meta = next(m for m in RMM_METHODS if m["id"] == e["id"])
        if iso(e["start"]) != meta["expectedStart"]:
            boundary_warnings.append(f"{e['id']} starts {iso(e['start'])}, header says {meta['expectedStart']}")
        if meta["expectedEnd"] and iso(e["end"]) != meta["expectedEnd"]:
            boundary_warnings.append(f"{e['id']} ends {iso(e['end'])}, header says {meta['expectedEnd']}")
        epochs.append({"id": i, "name": e["id"], "method": meta["label"],
                       "definition": meta["definition"],
                       "start": iso(e["start"]), "end": iso(e["end"]), "nValid": e["n"]})
    ep_index = {e["name"]: e["id"] for e in epochs}

    first = max(start, src_start)
    by_day = {r["date"]: r for r in rows if r["date"] <= last_valid}
    n = (last_valid - first).days + 1
    cols = {"rmm1": [], "rmm2": [], "phase": [], "amp": [], "epoch": []}
    for i in range(n):
        r = by_day.get(first + dt.timedelta(days=i))
        if r is None or r["method"] is None:
            for c in cols.values():
                c.append(None)
        else:
            cols["rmm1"].append(r["rmm1"])
            cols["rmm2"].append(r["rmm2"])
            cols["phase"].append(r["phase"])
            cols["amp"].append(r["amp"])
            cols["epoch"].append(ep_index[r["method"]])
    n_missing = sum(1 for v in cols["phase"] if v is None)

    return {
        "available": True,
        "source": "Australian Bureau of Meteorology, Real-time Multivariate MJO (RMM) index (Wheeler and Hendon 2004; daily series 1974 to near-real-time)",
        "url": RMM_URL,
        "retrieved": retrieved,
        "retrievedFrom": source_note,
        "license": "UNCONFIRMED - Commonwealth of Australia / Bureau of Meteorology material, not automatically public domain; confirm terms before publication",
        "licenseReference": BOM_COPYRIGHT_URL,
        "attribution": "Australian Bureau of Meteorology (RMM index of Wheeler and Hendon, 2004) - wording to be confirmed with BoM",
        "units": "RMM1/RMM2 normalized PC amplitudes; amp = sqrt(RMM1^2 + RMM2^2); phase 1-8",
        "sourceHeader": header,
        "epochs": epochs,
        "epochNote": ("The definition changed within this record: restrict composites to a single "
                      "epoch for a homogeneous sample. epoch[i] is the id (index into epochs) of "
                      "the definition in force on day i; null where RMM is missing."),
        "start": iso(first),
        "end": iso(last_valid),
        "noDataAfter": iso(last_valid),
        "coverageNote": (f"No MJO data after {iso(last_valid)}: the arrays end there and are not "
                         f"padded - a day past the end is missing, not a quiet MJO. "
                         f"Weak-MJO days (amp < 1) are real data with low amplitude."),
        "n": n,
        "missing": n_missing,
        "rmm1": cols["rmm1"], "rmm2": cols["rmm2"],
        "phase": cols["phase"], "amp": cols["amp"],
        "epoch": cols["epoch"],
    }, {"sourceSpan": (iso(src_start), iso(src_end)), "lastValid": iso(last_valid),
        "trailingMissingRows": trailing_missing,
        "sentinels": dict(sentinels),
        "epochs": epochs, "boundaryWarnings": boundary_warnings,
        "missingInWindow": n_missing}


def mjo_unavailable(reason: str):
    return {
        "available": False,
        "reason": reason,
        "source": "Australian Bureau of Meteorology, Real-time Multivariate MJO (RMM) index",
        "url": RMM_URL,
        "license": "UNCONFIRMED - Commonwealth of Australia / Bureau of Meteorology material, not automatically public domain; confirm terms before publication",
        "licenseReference": BOM_COPYRIGHT_URL,
        "coverageNote": "MJO data were not baked into this build; there is no MJO information here, quiet or otherwise.",
    }


def season_label(d: dt.date) -> int:
    """Archive season (1 June boundary) as its starting year: 2001 means
    2001-02 (1 Jun 2001 to 31 May 2002)."""
    return d.year if d.month >= 6 else d.year - 1


def coverage_table(payload, first_year=2001, last_year=2025):
    def counts(block, key):
        if not block or block.get("available") is False:
            return None
        start = dt.date.fromisoformat(block["start"])
        c = Counter()
        for i, v in enumerate(block[key]):
            if v is not None:
                c[season_label(start + dt.timedelta(days=i))] += 1
        return c
    cols = {k: counts(payload[k], "values") for k in ("nao", "pna", "ao")}
    cols["rmm"] = counts(payload["mjo"], "phase")
    lines = ["season     days   NAO   PNA    AO   RMM"]
    for y in range(first_year, last_year + 1):
        days = (dt.date(y + 1, 6, 1) - dt.date(y, 6, 1)).days
        cells = []
        for k in ("nao", "pna", "ao", "rmm"):
            cells.append("    -" if cols[k] is None else f"{cols[k].get(y, 0):5d}")
        lines.append(f"{y}-{(y + 1) % 100:02d}  {days:5d} " + " ".join(cells))
    return "\n".join(lines)


def build(args):
    start = dt.date.fromisoformat(args.start)
    retrieved = today_utc()
    info = {}

    oni_rows = parse_oni(http_get(ONI_URL))
    oni, info["oni"] = build_oni(oni_rows, start, retrieved)

    payload = {
        "schema": SCHEMA_VERSION,
        "note": ("Plain time series of climate teleconnection indices, baked at build time; no per-event "
                 "attribution here. Daily series (nao, pna, ao, mjo) are dense arrays - slot i is "
                 "start + i days - with null for missing; oni is dense per month. A date lookup is "
                 "index = days since start. Do not read a value past a block's end as zero or quiet."),
        "derived": {
            "mean5": ("5-day antecedent mean ending on day d = mean of days d-4..d inclusive; "
                      "null unless all five values are present. Computed by the consumer from "
                      "the daily array."),
            "mjoLag": ("Lagged MJO at lag L days = the mjo arrays at day d-L (L ~ 5-15 for the "
                       "extratropical response). Not pre-computed; null if d-L precedes mjo.start."),
            "dayIndex": "index = days between block.start and the date (UTC calendar days)",
        },
        "start": args.start,
        "oni": oni,
    }
    for name, label in (("nao", "NAO"), ("pna", "PNA"), ("ao", "AO")):
        rows, sentinels = parse_cpc_daily(http_get(CPC_DAILY_URL.format(name=name)), name)
        payload[name], info[name] = build_cpc(name, label, rows, sentinels, start, retrieved)

    if args.no_mjo:
        payload["mjo"] = mjo_unavailable("built with --no-mjo")
        info["mjo"] = None
    else:
        if args.rmm_input:
            with open(args.rmm_input, encoding="utf-8") as fh:
                text = fh.read()
            note = f"local file {os.path.basename(args.rmm_input)}"
        else:
            try:
                text = http_get(RMM_URL)
            except FetchBlocked as err:
                raise RuntimeError(
                    f"BoM refused the RMM download ({err}). BoM does not support automated "
                    f"scraping; fetch the file by other means and re-run with --rmm-input FILE, "
                    f"or use --no-mjo. This tool does not work around the block.") from err
            note = "fetched at build time"
        header, rrows, rsent = parse_rmm(text)
        payload["mjo"], info["mjo"] = build_mjo(header, rrows, rsent, start, retrieved, note)
    return payload, info


def print_summary(payload, info, coverage: bool):
    o = info["oni"]
    print(f"ONI   source {o['sourceSpan'][0]}..{o['sourceSpan'][1]}  kept {payload['oni']['start']}.."
          f"{payload['oni']['end']} ({payload['oni']['n']} seasons, {o['trimmedSeasons']} trimmed)")
    for name in ("nao", "pna", "ao"):
        i, b = info[name], payload[name]
        sent = ", ".join(f"{k} x{v}" for k, v in i["sentinels"].items()) or "none"
        print(f"{name.upper():5s} source {i['sourceSpan'][0]}..{i['sourceSpan'][1]} ({i['sourceDays']} days)  "
              f"kept {b['start']}..{b['end']} ({b['n']} days, {i['trimmedDays']} trimmed)  "
              f"sentinels -> null: {sent}")
    m = payload["mjo"]
    if m.get("available"):
        i = info["mjo"]
        sent = ", ".join(f"{k} x{v}" for k, v in i["sentinels"].items()) or "none"
        print(f"MJO   source {i['sourceSpan'][0]}..{i['sourceSpan'][1]}  kept {m['start']}..{m['end']} "
              f"({m['n']} days, {m['missing']} missing)  sentinels -> null: {sent}")
        print(f"      NO MJO DATA AFTER {m['noDataAfter']} "
              f"({i['trailingMissingRows']} trailing sentinel row(s) trimmed); "
              f"CPC series run to {payload['nao']['end']}")
        for e in i["epochs"]:
            print(f"      RMM epoch {e['id']}: {e['name']} ({e['method']}) {e['start']}..{e['end']} "
                  f"- {e['definition']}")
        if len(i["epochs"]) > 1:
            print(f"      definition changes at {i['epochs'][1]['start']}; "
                  f"do not composite across it without accounting for the change")
        for w in i["boundaryWarnings"]:
            print(f"      WARNING: epoch boundary differs from the file header: {w}")
    else:
        print(f"MJO   NOT INCLUDED: {m['reason']}  (payload marks mjo.available = false)")
    print("licence: ONI/NAO/PNA/AO - NOAA CPC, U.S. Government work, public domain (as stated by the "
          "project brief; not independently verified here).")
    print("licence: MJO RMM - Australian BoM. NOT automatically public domain. ATTRIBUTION/LICENCE "
          f"NEEDS CONFIRMING BEFORE PUBLICATION (terms: {BOM_COPYRIGHT_URL}).")
    if coverage:
        print()
        print(coverage_table(payload))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build but write nothing")
    ap.add_argument("--start", default=DEFAULT_START, metavar="YYYY-MM-DD",
                    help=f"first day kept in the daily series (default {DEFAULT_START})")
    ap.add_argument("--rmm-input", metavar="FILE",
                    help="use a local BoM RMM file instead of downloading it")
    ap.add_argument("--no-mjo", action="store_true",
                    help="skip the MJO entirely; the payload says so explicitly")
    ap.add_argument("--coverage", action="store_true",
                    help="also print per-season valid-day counts for 2001-02 .. 2025-26")
    args = ap.parse_args()
    if args.no_mjo and args.rmm_input:
        ap.error("--no-mjo and --rmm-input are mutually exclusive")

    payload, info = build(args)
    print_summary(payload, info, args.coverage)

    if args.check:
        return

    data_dir = os.path.join(ROOT, "docs", "data")
    os.makedirs(data_dir, exist_ok=True)
    compact = json.dumps(payload, separators=(",", ":"), allow_nan=False)

    js_path = os.path.join(data_dir, "teleconnections.js")
    with open(js_path, "w", encoding="utf-8") as fh:
        fh.write("/* generated by tools/build_teleconnections.py - do not edit */\n")
        fh.write("/* ONI/NAO/PNA/AO: NOAA CPC, US Government work, public domain. "
                  "MJO RMM: Australian BoM - licence/attribution UNCONFIRMED. */\n")
        fh.write("window.HF_TELECONNECTIONS = " + compact + ";\n")
    json_path = os.path.join(data_dir, "teleconnections.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        fh.write(compact + "\n")

    for path in (js_path, json_path):
        print(f"wrote docs/data/{os.path.basename(path)} ({os.path.getsize(path) / 1024:.1f} KB)")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)
