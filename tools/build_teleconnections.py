#!/usr/bin/env python3
"""Build the climate teleconnection index series baked into the site data.

Why this exists: the archive's explosive-cyclogenesis events need large-scale
context - ENSO phase, the NAO/PNA/AO state around genesis, and where the MJO
was a week or two earlier. This script fetches those indices once, at build
time, and writes them as plain time series. It does NOT do any per-event
attribution; whoever attributes events looks values up in this file.

Sources (all fetched here; the site itself makes no runtime requests; all are
NOAA Climate Prediction Center, U.S. Government work, public domain):
    ONI   3-month overlapping seasons (monthly)
          https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
    NAO, PNA, AO   daily, 1950-01-01 on
          https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.{nao,pna,ao}.index.b500101.current.ascii
    MJO   ten CPC velocity-potential MJO indices, PENTAD rows, 1978 on
          https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_mjo_index/proj_norm_order.ascii

The MJO series is NOT the Wheeler-Hendon RMM index. There is no phase 1-8 and
no amplitude. CPC builds ten indices from an extended EOF of 200-hPa velocity
potential (CHI200, ENSO-neutral and weak-ENSO Nov-Apr winters, 1979-2000); each
index is named for the longitude at the centre of enhanced convection in one
of the ten time-lagged patterns of the first EEOF (20E, 70E, 80E, 100E, 120E,
140E, 160E, 120W, 40W, 10W). Consumers must composite on the longitude series
directly; anything that assumes an 8-phase diagram is wrong for this data.

Things that are easy to get wrong, and are handled explicitly:

* CPC daily files are fixed-width. A negative value butts up against the day
  field ("2006 10 26-99.000"), so a whitespace split sees three columns and
  silently drops or mis-reads exactly the missing-value rows. parse_cpc_daily()
  uses a regex that does not need a separator. The only sentinel actually
  present in these three files is -99.000 (2 days in NAO and PNA, 1 in AO);
  any other implausible value stops the build rather than being guessed at.
* The MJO file is PENTAD data, not daily. Each row is a calendar pentad
  (days 1-5, 6-10, ... of the year) labelled by its CENTRE date: 19780103,
  19780108, ... 73 rows a year. parse_mjo() checks that every label really is a
  pentad centre (day-of-year 3, 8, 13 ... not counting Feb 29), so steps are 5
  days except one 6-day step per leap year (Feb 27 -> Mar 4); a file that does
  not follow that pattern stops the build. Pentads are kept as pentads - an
  explicit "dates" array, no interpolation to daily, which would invent
  precision the source does not have.
* The MJO column headers are NOT in numeric order (INDEX_9 INDEX_10 INDEX_1 ...
  INDEX_8, with the longitude on the second header line). Column position is
  not the index number, so the header is parsed and every series is keyed by
  LONGITUDE; nothing is hardcoded to the current order. The mapping read from
  the header is cross-checked against the one CPC documents on its MJO page,
  and a disagreement prints a warning.
* Missing MJO values are "*****", and the file is pre-allocated to the end of
  the current year. Trailing all-missing rows are trimmed (the series ends at
  the last pentad with data and is never padded - a null tail would read as
  "quiet MJO"); interior missing rows become null. The summary prints where
  real data ends, and the block carries noDataAfter.
* SIGN CONVENTION. The numbers are velocity-potential projections, where
  negative means upper-level divergence (enhanced convection) and positive
  means suppressed convection - unless CPC flipped the sign. That is checked
  from the data at every build (verify_convention) and the result is written
  into the payload ("convention", "conventionEvidence"), and the build stops
  if the data contradict it:
    - ENSO: during El Nino the Maritime Continent / western Pacific is anomalously
      DRY (suppressed convection), so under "positive = suppressed" the 100E,
      120E and 140E indices correlate POSITIVELY with ONI. They do (about +0.5).
    - Propagation: for index pairs 60-100 degrees apart, the lag at which the
      western index best predicts the eastern one must not be negative
      (eastward). Sign-independent, so it checks the longitude mapping, not
      the sign. At pentad resolution the lags are coarse (0 to +4 pentads), so
      this confirms direction, not a 5 m/s phase speed.
* The ONI season for a date is the 3-month season CENTERED on the date's
  calendar month (15 Jan 2016 -> DJF 2016, i.e. Dec 2015 - Feb 2016, the file's
  own labelling: YR is the year of the centre month). Phase is the threshold
  class (>= +0.5 El Nino, <= -0.5 La Nina, else Neutral). CPC only calls an
  *episode* after 5 consecutive overlapping seasons past the threshold, so a
  separate "episode" flag says whether the season sits in such a run (1), does
  not (0), or cannot be told because the data ends mid-run (null).

Output shape (decision, with reasons): the daily series (NAO/PNA/AO) are DENSE
arrays, one slot per calendar day from "start", nulls for missing. That makes
the date key implicit and exact - index = days since start - so a consumer
windows it with plain array arithmetic and cannot get a gap wrong, and it is
what keeps the payload small. ONI is dense per month. The MJO is a dense array
per pentad ROW with an explicit "dates" array (the row spacing is not constant
across leap years, so it cannot be implied). The 5-day antecedent mean is NOT
pre-computed (a trivial window over the daily array). MJO lags are NOT
pre-computed either: a pentad is already a 5-day mean, and a lag of 1, 2 or 3
pentad rows is 5, 10 or 15 days, which spans the usual extratropical response
window - the consumer just steps back through the rows. The definitions every
consumer must share are written into the payload ("derived").

Trimming: the source series start in 1950 / 1978; the archive only needs 2001
on, so daily series start at --start (default 2001-05-01, a month ahead of the
first 1 June season so the antecedent window and MJO pentad lags have data for
the earliest events). ONI is trimmed to the same start month and the MJO to
the pentad containing --start. The end dates are whatever the sources hold.

Writes:
    docs/data/teleconnections.js     window.HF_TELECONNECTIONS = {...}   (works from file://)
    docs/data/teleconnections.json   same payload, plain JSON

Usage:
    python3 tools/build_teleconnections.py                  # fetch, build, write
    python3 tools/build_teleconnections.py --check           # build, but write nothing
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
MJO_URL = ("https://www.cpc.ncep.noaa.gov/products/precip/CWlink/"
           "daily_mjo_index/proj_norm_order.ascii")
MJO_DOC_URL = ("https://www.cpc.ncep.noaa.gov/products/precip/CWlink/"
               "daily_mjo_index/mjo_index.shtml")

# Descriptive UA, so the request is attributable.
USER_AGENT = "awips-tools/build_teleconnections (build-time research data fetch; no runtime scraping)"

DEFAULT_START = "2001-05-01"

ROUND_DIGITS = 3               # CPC daily files publish 3 decimals

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

# MJO pentad file. Values are normalized indices (observed extremes about +-3);
# anything past this is neither data nor the "*****" missing marker, so it stops
# the build.
MJO_PLAUSIBLE_ABS = 20.0
MJO_PENTADS_PER_YEAR = 73

# CPC's own index-number -> longitude table, from the MJO page. Cross-check
# ONLY: the emitted mapping always comes from the file's header lines.
MJO_DOCUMENTED_LON = {1: "80E", 2: "100E", 3: "120E", 4: "140E", 5: "160E",
                      6: "120W", 7: "40W", 8: "10W", 9: "20E", 10: "70E"}

# What verify_convention() looks for, and the string it licenses. Thresholds
# are far inside what the data show (mean ONI r about +0.5; 13 of 14 pairs
# with a positive peak lag, none negative), so a real flip is unmistakable.
MJO_CONVENTION = ("negative = enhanced convection (upper-level divergence, velocity-potential sign); "
                  "positive = suppressed convection")
MJO_ENSO_LONS = ("100E", "120E", "140E")   # Maritime Continent / W Pacific: dry in El Nino
MJO_ENSO_MIN_MEAN_R = 0.25
MJO_PAIR_SEP_DEG = (60, 100)               # eastward separation for the propagation pairs
MJO_PAIR_MAX_LAG = 4                       # pentads
MJO_PAIR_MIN_POSITIVE_FRAC = 0.75

ONI_SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]

FETCH_RETRIES = 4
FETCH_TIMEOUT_S = 60

_CPC_RE = re.compile(r"^\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s*(-?\d+(?:\.\d+)?)\s*$")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def http_get(url: str) -> str:
    """GET with retry/backoff on network errors and 5xx. A 4xx is a refusal,
    not a glitch, so it raises immediately rather than repeating it."""
    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(FETCH_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, context=ctx, timeout=FETCH_TIMEOUT_S) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as err:
            if 400 <= err.code < 500:
                raise RuntimeError(f"{url}: HTTP {err.code} {err.reason}") from err
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


def pentad_centre_ok(d: dt.date) -> bool:
    """True if d is the centre of a calendar pentad: day-of-year 3, 8, 13 ...
    counting without Feb 29 (a leap year's later days are shifted back one so
    Mar 4 stays a pentad centre). This is what the label pattern in the file
    actually is, checked rather than assumed."""
    doy = d.timetuple().tm_yday
    leap = (d.year % 4 == 0 and d.year % 100 != 0) or d.year % 400 == 0
    if leap and d >= dt.date(d.year, 3, 1):
        doy -= 1
    return (doy - 3) % 5 == 0


def parse_mjo(text: str):
    """CPC MJO pentad file -> (columns, rows). Line 1 holds INDEX_n names
    in the file's own (non-numeric) order, line 2 the matching longitudes;
    columns is [{"index": n, "lon": "80E"}, ...] in file order, read from the
    header. rows is [(date, [value-or-None, ...])] with values in that column
    order. A cell of asterisks is missing -> None; a whole row of them is a
    pre-allocated or missing pentad."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        raise RuntimeError("MJO: file too short")
    names = lines[0].split()
    head2 = lines[1].split()
    if not head2 or head2[0].upper() != "PENTAD":
        raise RuntimeError(f"MJO: second header line should start with PENTAD: {lines[1]!r}")
    lons = head2[1:]
    if len(names) != len(lons):
        raise RuntimeError(f"MJO: {len(names)} index names but {len(lons)} longitudes in the header")
    columns = []
    for nm, lon in zip(names, lons):
        m = re.fullmatch(r"INDEX_(\d+)", nm)
        if not m or not re.fullmatch(r"\d{1,3}[EW]", lon):
            raise RuntimeError(f"MJO: unexpected header pair {nm!r} / {lon!r}")
        columns.append({"index": int(m.group(1)), "lon": lon})
    if len({c["lon"] for c in columns}) != len(columns) or len({c["index"] for c in columns}) != len(columns):
        raise RuntimeError("MJO: duplicate index or longitude in header")

    rows = []
    prev = None
    for lineno, line in enumerate(lines[2:], 3):
        parts = line.split()
        if len(parts) != len(columns) + 1 or not re.fullmatch(r"\d{8}", parts[0]):
            raise RuntimeError(f"MJO: line {lineno}: expected a YYYYMMDD label and "
                               f"{len(columns)} values: {line!r}")
        day = dt.datetime.strptime(parts[0], "%Y%m%d").date()
        if not pentad_centre_ok(day):
            raise RuntimeError(f"MJO: line {lineno}: {day} is not a calendar-pentad centre - the "
                               f"file's labelling is not what this tool was written against")
        if prev is not None:
            step = (day - prev).days
            leap_step = (prev.month == 2 and prev.day == 27 and day.month == 3 and day.day == 4
                         and (prev.year % 4 == 0 and prev.year % 100 != 0 or prev.year % 400 == 0))
            if step != (6 if leap_step else 5):
                raise RuntimeError(f"MJO: line {lineno}: {day} follows {prev} by {step} days")
        prev = day
        vals = []
        for tok in parts[1:]:
            if re.fullmatch(r"\*+", tok):
                vals.append(None)
                continue
            v = float(tok)
            if abs(v) > MJO_PLAUSIBLE_ABS:
                raise RuntimeError(f"MJO: line {lineno}: value {tok} is implausible for a "
                                   f"normalized index - inspect the source")
            vals.append(round(v, 2))
        rows.append((day, vals))
    return columns, rows


def lon_deg_east(lon: str) -> int:
    """'80E' -> 80, '120W' -> 240: degrees east, 0-360."""
    n = int(lon[:-1])
    return n % 360 if lon[-1] == "E" else (360 - n) % 360


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


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        raise RuntimeError("MJO: too few overlapping points to correlate")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        raise RuntimeError("MJO: constant series - cannot correlate")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sxx * syy) ** 0.5


def lagged_pairs(a, b, lag):
    """Pairs (a[t], b[t+lag]) skipping any with a missing end."""
    if lag >= 0:
        pairs = zip(a[:len(a) - lag] if lag else a, b[lag:])
    else:
        pairs = zip(a[-lag:], b[:len(b) + lag])
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    return [x for x, _ in pairs], [y for _, y in pairs]


def verify_convention(columns, rows, oni_rows):
    """Establish from the data, at every build, which way the MJO numbers
    point, and refuse to continue if they contradict MJO_CONVENTION. Two
    self-contained checks (no external data beyond the ONI already fetched):

    ENSO. El Nino suppresses convection over the Maritime Continent / western
    Pacific (upper-level convergence, positive velocity potential), so if
    positive = suppressed, the 100E-140E indices correlate positively with
    ONI. Monthly means of the pentad rows vs the ONI season centred on the
    same month, whole record. This is the sign check.

    Propagation. For index pairs 60-100 degrees apart (eastward), the lag at
    which the western index best predicts the eastern one must not be
    negative. This does not depend on the sign; it checks that the longitude
    labels were attached to the right columns. Peak lag is in pentads, so it
    shows direction, not a phase speed."""
    col = {c["lon"]: j for j, c in enumerate(columns)}
    for lon in MJO_ENSO_LONS:
        if lon not in col:
            raise RuntimeError(f"MJO: header has no {lon} column - cannot verify the sign convention")
    oni = {(y, m): v for y, m, v in oni_rows if v is not None}
    by_month = {}
    for day, vals in rows:
        slot = by_month.setdefault((day.year, day.month), [[] for _ in columns])
        for j, v in enumerate(vals):
            if v is not None:
                slot[j].append(v)
    r_by_lon, n_months = {}, 0
    for c in sorted(columns, key=lambda c: lon_deg_east(c["lon"])):
        xs, ys = [], []
        for key, slot in sorted(by_month.items()):
            j = col[c["lon"]]
            if key in oni and len(slot[j]) >= 4:
                xs.append(sum(slot[j]) / len(slot[j]))
                ys.append(oni[key])
        r_by_lon[c["lon"]] = round(pearson(xs, ys), 3)
        n_months = len(xs)
    mean_r = sum(r_by_lon[lon] for lon in MJO_ENSO_LONS) / len(MJO_ENSO_LONS)
    if mean_r < MJO_ENSO_MIN_MEAN_R:
        raise RuntimeError(
            f"MJO: mean correlation of the {'/'.join(MJO_ENSO_LONS)} indices with ONI is "
            f"{mean_r:+.2f}, expected >= {MJO_ENSO_MIN_MEAN_R:+.2f} if positive = suppressed "
            f"convection. The sign convention may have changed - inspect the source before "
            f"publishing anything composited on it.")

    series = [[vals[j] for _d, vals in rows] for j in range(len(columns))]
    pairs, lo, hi = [], *MJO_PAIR_SEP_DEG
    for ca in columns:
        for cb in columns:
            sep = (lon_deg_east(cb["lon"]) - lon_deg_east(ca["lon"])) % 360
            if not lo <= sep <= hi:
                continue
            a, b = series[col[ca["lon"]]], series[col[cb["lon"]]]
            cs = {}
            for lag in range(-MJO_PAIR_MAX_LAG, MJO_PAIR_MAX_LAG + 1):
                x, y = lagged_pairs(a, b, lag)
                cs[lag] = pearson(x, y)
            peak = max(cs, key=lambda k: cs[k])
            pairs.append({"from": ca["lon"], "to": cb["lon"], "eastDeg": sep,
                          "peakLag": peak, "r": round(cs[peak], 2)})
    pos = sum(p["peakLag"] > 0 for p in pairs)
    zero = sum(p["peakLag"] == 0 for p in pairs)
    neg = sum(p["peakLag"] < 0 for p in pairs)
    if not pairs or neg or pos / len(pairs) < MJO_PAIR_MIN_POSITIVE_FRAC:
        raise RuntimeError(
            f"MJO: eastward-propagation check failed ({pos} positive, {zero} zero, {neg} negative "
            f"peak lags over {len(pairs)} pairs) - the longitude mapping of the columns may be wrong.")
    return {
        "enso": {
            "test": ("Pearson r of each index's monthly mean (pentad rows binned by label month) with the "
                     "ONI season centred on that month. El Nino dries the Maritime Continent / W Pacific "
                     "(suppressed convection), so r > 0 at 100E-140E means positive = suppressed."),
            "months": n_months,
            "period": f"{rows[0][0].isoformat()[:7]}..{rows[-1][0].isoformat()[:7]} (rows with data)",
            "r": r_by_lon,
            "meanR100E_140E": round(mean_r, 3),
        },
        "propagation": {
            "test": ("Pairs of indices 60-100 degrees apart eastward; peak lag of corr(west(t), east(t+lag)), "
                     "lags -4..+4 pentads. Peak lag >= 0 means the eastern index follows: eastward. "
                     "Sign-independent; checks the longitude mapping. Pentad resolution: direction only."),
            "unit": "pentads", "positive": pos, "zero": zero, "negative": neg, "pairs": pairs,
        },
    }


def pentad_row(labels, d: dt.date):
    """Index of the pentad row containing date d: the last row whose label is
    <= d + 2 days (labels are pentad centres). None if d is before the first
    row. A Feb 29 falls in the Feb-27 pentad (the 6-day one) - that is the
    one assumption here, since the file does not say where it goes."""
    limit = d + dt.timedelta(days=2)
    idx = None
    for i, lab in enumerate(labels):
        if lab <= limit:
            idx = i
        else:
            break
    return idx


def build_mjo(columns, rows, evidence, start: dt.date, retrieved: str):
    live = [i for i, (_d, vals) in enumerate(rows) if any(v is not None for v in vals)]
    if not live:
        raise RuntimeError("MJO: every row is missing")
    last = live[-1]
    trailing = len(rows) - 1 - last
    labels = [d for d, _ in rows]
    i0 = pentad_row(labels[:last + 1], start) or 0
    kept = rows[i0:last + 1]
    order = sorted(columns, key=lambda c: lon_deg_east(c["lon"]))
    col = {c["lon"]: j for j, c in enumerate(columns)}
    interior_missing = [d.isoformat() for d, vals in kept if all(v is None for v in vals)]
    cells_missing = sum(v is None for _d, vals in kept for v in vals)
    return {
        "kind": "CPC 200-hPa velocity-potential MJO indices (ten longitude-keyed indices), PENTAD resolution",
        "notRmm": ("This is NOT the Wheeler-Hendon RMM index. There is no phase 1-8 and no amplitude. "
                   "Composite on the longitude series directly; anything written assuming an 8-phase "
                   "diagram is wrong for this data."),
        "method": ("Extended EOF of pentad 200-hPa velocity potential (ENSO-neutral and weak-ENSO Nov-Apr "
                   "winters 1979-2000); ten indices from regressing data onto the ten time-lagged patterns "
                   "of the first EEOF, each named for the longitude of enhanced convection in its pattern; "
                   f"normalized (per CPC, {MJO_DOC_URL})."),
        "source": "NOAA Climate Prediction Center, MJO indices (proj_norm_order.ascii)",
        "url": MJO_URL,
        "docUrl": MJO_DOC_URL,
        "retrieved": retrieved,
        "license": "U.S. Government work; public domain",
        "attribution": "NOAA/NWS Climate Prediction Center",
        "units": "normalized index (dimensionless), 2 decimals",
        "convention": MJO_CONVENTION,
        "conventionEvidence": evidence,
        "cadence": "pentad",
        "pentadLabel": ("dates[i] is the CENTRE date of a calendar pentad (day-of-year 3, 8, 13 ...; 73 rows a "
                        "year; Feb 29 not counted), so the row covers dates[i]-2 .. dates[i]+2 days. Spacing is "
                        "5 days, or 6 across a leap day (Feb 27 -> Mar 4). Whether a row is exactly the mean over "
                        "that window is CPC's definition, not stated in the file. Not interpolated to daily."),
        "start": kept[0][0].isoformat(),
        "end": kept[-1][0].isoformat(),
        "noDataAfter": kept[-1][0].isoformat(),
        "coverageNote": (f"No MJO data after the pentad centred {kept[-1][0].isoformat()}: the arrays end there. "
                         f"The source file is pre-allocated ({trailing} trailing all-missing row(s) trimmed); "
                         f"a date past the end is missing, not a quiet MJO."),
        "n": len(kept),
        "missing": len(interior_missing),
        "sourceColumns": columns,
        "longitudes": [c["lon"] for c in order],
        "lonDegE": {c["lon"]: lon_deg_east(c["lon"]) for c in order},
        "dates": [int(d.strftime("%Y%m%d")) for d, _ in kept],
        "series": {c["lon"]: [vals[col[c["lon"]]] for _d, vals in kept] for c in order},
    }, {"sourceSpan": (rows[0][0].isoformat(), rows[-1][0].isoformat()), "sourceRows": len(rows),
        "lastValid": rows[last][0].isoformat(), "trailingMissingRows": trailing,
        "interiorMissing": interior_missing, "cellsMissing": cells_missing,
        "dropped": i0}


def season_label(d: dt.date) -> int:
    """Archive season (1 June boundary) as its starting year: 2001 means
    2001-02 (1 Jun 2001 to 31 May 2002)."""
    return d.year if d.month >= 6 else d.year - 1


def coverage_table(payload, first_year=2001, last_year=2025):
    def counts(block, key):
        start = dt.date.fromisoformat(block["start"])
        c = Counter()
        for i, v in enumerate(block[key]):
            if v is not None:
                c[season_label(start + dt.timedelta(days=i))] += 1
        return c
    cols = {k: counts(payload[k], "values") for k in ("nao", "pna", "ao")}
    m = payload["mjo"]
    mjo_ok, mjo_rows = Counter(), Counter()
    for i, date_int in enumerate(m["dates"]):
        d = dt.datetime.strptime(str(date_int), "%Y%m%d").date()
        mjo_rows[season_label(d)] += 1
        if any(m["series"][lon][i] is not None for lon in m["longitudes"]):
            mjo_ok[season_label(d)] += 1
    lines = ["season     days   NAO   PNA    AO   MJO pentads (with data/rows)"]
    for y in range(first_year, last_year + 1):
        days = (dt.date(y + 1, 6, 1) - dt.date(y, 6, 1)).days
        cells = [f"{cols[k].get(y, 0):5d}" for k in ("nao", "pna", "ao")]
        lines.append(f"{y}-{(y + 1) % 100:02d}  {days:5d} " + " ".join(cells)
                     + f"   {mjo_ok.get(y, 0):3d}/{mjo_rows.get(y, 0):<3d}")
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
                 "attribution here. nao/pna/ao are daily dense arrays - slot i is start + i days - with null "
                 "for missing; oni is dense per month; mjo is PENTAD rows with an explicit dates array. "
                 "Do not read a value past a block's end as zero or quiet."),
        "derived": {
            "dayIndex": "daily blocks: index = days between block.start and the date (UTC calendar days)",
            "mean5": ("NAO/PNA/AO only (genuinely daily): 5-day antecedent mean ending on day d = mean of days "
                      "d-4..d inclusive; null unless all five values are present. Computed by the consumer."),
            "mjoRow": ("MJO attribution is by pentad: the row containing date d is the last row of mjo.dates "
                       "whose label is <= d + 2 days (labels are pentad centres). A Feb 29 is taken to fall in "
                       "the Feb-27 pentad (unverified)."),
            "mjoLag": ("A pentad is already a ~5-day mean, so the MJO has no separate antecedent mean. Lag k "
                       "is row i-k: k = 1, 2, 3 are 5, 10, 15 days between pentad centres (6 across a leap "
                       "day), spanning the usual extratropical response window. The event can sit anywhere "
                       "in its own pentad, so a lag is good to about +-2 days. Null / unavailable if i-k "
                       "precedes mjo.dates[0]."),
            "mjoNotRmm": ("The MJO block is not Wheeler-Hendon RMM: no phase 1-8, no amplitude. Use the "
                          "longitude-keyed series with the stated mjo.convention."),
        },
        "start": args.start,
        "oni": oni,
    }
    for name, label in (("nao", "NAO"), ("pna", "PNA"), ("ao", "AO")):
        rows, sentinels = parse_cpc_daily(http_get(CPC_DAILY_URL.format(name=name)), name)
        payload[name], info[name] = build_cpc(name, label, rows, sentinels, start, retrieved)

    columns, mrows = parse_mjo(http_get(MJO_URL))
    mapped = {c["index"]: c["lon"] for c in columns}
    info["mjoMappingWarnings"] = [
        f"INDEX_{k}: header says {mapped.get(k)}, CPC's MJO page says {v}"
        for k, v in MJO_DOCUMENTED_LON.items() if mapped.get(k) != v]
    evidence = verify_convention(columns, mrows, oni_rows)
    payload["mjo"], info["mjo"] = build_mjo(columns, mrows, evidence, start, retrieved)
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
    m, i = payload["mjo"], info["mjo"]
    print(f"MJO   PENTAD rows, NOT daily and NOT Wheeler-Hendon RMM (no phase 1-8, no amplitude)")
    print(f"      source {i['sourceSpan'][0]}..{i['sourceSpan'][1]} ({i['sourceRows']} rows, pre-allocated)  "
          f"kept {m['start']}..{m['end']} ({m['n']} pentads, {i['dropped']} dropped before start)")
    print(f"      REAL DATA ENDS at the pentad centred {i['lastValid']}; {i['trailingMissingRows']} trailing "
          f"all-'*****' rows trimmed; CPC daily series run to {payload['nao']['end']}")
    print(f"      interior missing pentads in kept span: "
          f"{', '.join(i['interiorMissing']) if i['interiorMissing'] else 'none'}; "
          f"missing cells: {i['cellsMissing']}")
    print("      header column order -> longitude: " +
          ", ".join(f"INDEX_{c['index']}={c['lon']}" for c in m["sourceColumns"]))
    print(f"      emitted keyed by longitude, eastward: {' '.join(m['longitudes'])}")
    for w in info["mjoMappingWarnings"]:
        print(f"      WARNING: header mapping differs from CPC's documented table: {w}")
    ev = m["conventionEvidence"]
    print(f"      convention (verified): {m['convention']}")
    print("      ENSO check r(index, ONI): " +
          " ".join(f"{k}={v:+.2f}" for k, v in ev["enso"]["r"].items()) +
          f"  | mean r at {'/'.join(MJO_ENSO_LONS)} = {ev['enso']['meanR100E_140E']:+.2f} ({ev['enso']['months']} months)")
    p = ev["propagation"]
    print(f"      propagation check: {p['positive']} of {len(p['pairs'])} eastward pairs peak at a positive "
          f"pentad lag, {p['zero']} at zero, {p['negative']} negative")
    print("licence: ONI/NAO/PNA/AO/MJO - all NOAA CPC, U.S. Government work, public domain "
          "(as stated by the project brief; not independently verified here).")
    if coverage:
        print()
        print(coverage_table(payload))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build but write nothing")
    ap.add_argument("--start", default=DEFAULT_START, metavar="YYYY-MM-DD",
                    help=f"first day kept in the series (default {DEFAULT_START})")
    ap.add_argument("--coverage", action="store_true",
                    help="also print per-season valid counts for 2001-02 .. 2025-26")
    args = ap.parse_args()

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
        fh.write("/* ONI, NAO, PNA, AO and CPC pentad MJO indices: NOAA Climate Prediction Center, "
                  "US Government work, public domain. */\n")
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
