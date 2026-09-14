#!/usr/bin/env python3
"""Build the HF extratropical low archive site data from the raw CSV exports.

Reads the per-basin CSV exports of the HF low archive spreadsheet, normalizes
two decades of hand-entered rows, derives the per-low climatology metrics the
web page needs, and writes:

    docs/data/hf-lows.js     window.HF_DATA = {...}   (works from file://)
    docs/data/hf-lows.json   the same payload, for anyone else who wants it
    docs/data/qc-report.txt  every repair, flag and drop, in plain text

The reader is deliberately tolerant: it repairs what is unambiguous, drops what
is not, and reports every decision. Nothing is silently discarded.

Usage:
    python3 tools/build_hf_lows.py                 # uses data/hf_lows/*.csv
    python3 tools/build_hf_lows.py --check         # build, but write nothing
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASINS = [
    # key, label, csv file, plausible longitude range (lo, hi); a range with
    # lo > hi wraps the dateline.
    ("atl", "Atlantic", "data/hf_lows/HF_Data_-_Atl.csv", (-100.0, 40.0)),
    ("pac", "Pacific", "data/hf_lows/HF_Data_-_Pac.csv", (100.0, -100.0)),
]

# Category codes, with the rank used for "peak category". Anything unlisted is
# normalized to UNK and reported.
CATEGORIES = {
    "HF":  {"rank": 5, "label": "Hurricane force", "short": "HF",
            "desc": "Sustained winds >= 64 kt"},
    "DHF": {"rank": 4, "label": "Developing hurricane force", "short": "DHF",
            "desc": "Expected to reach hurricane force"},
    "S":   {"rank": 3, "label": "Storm force", "short": "S",
            "desc": "Sustained winds 48-63 kt"},
    "DS":  {"rank": 2, "label": "Developing storm force", "short": "DS",
            "desc": "Expected to reach storm force"},
    "G":   {"rank": 1, "label": "Gale force", "short": "G",
            "desc": "Sustained winds 34-47 kt"},
    "TC":  {"rank": 0, "label": "Tropical", "short": "TC",
            "desc": "Fix made while the cyclone was still tropical"},
    "ABS": {"rank": 0, "label": "Absorbed / dissipated", "short": "ABS",
            "desc": "End-of-track marker"},
    "UNK": {"rank": 0, "label": "Unclassified", "short": "UNK",
            "desc": "Category missing or unrecognized in the archive"},
}

CATEGORY_ALIASES = {
    "TY": "TC", "TYPH": "TC", "TYPHOON": "TC", "TS": "TC", "TD": "TC", "TC": "TC",
    "ABSORBED": "ABS", "ABS": "ABS",
    "MISSING": "UNK", "NA": "UNK", "UNKNOWN": "UNK", "": "UNK",
    # "IL" appears once in the Pacific tab; it is not a documented code.
}

PRESSURE_SENTINELS = {"NOPRES", "XXX", "NA", "N/A", "MISSING", "-", ""}
PRESSURE_MIN, PRESSURE_MAX = 880.0, 1060.0
SYNOPTIC_HOURS = (0, 6, 12, 18)

# Period of record. Both basins are only consistently covered from the 2004-05
# season: the Pacific tab begins in February 2002 and the Atlantic in September
# 2003, so earlier seasons are short-counted rather than quiet. Earlier seasons
# stay in the payload and remain selectable on the page, but the default view
# starts here so per-season statistics are not distorted by partial coverage.
RECORD_START = 2004

# Cape Farewell, the southern tip of Greenland. Forward and reverse tip jets
# accelerate around this terrain and routinely produce hurricane force winds
# with no closed low centre to analyze a pressure for; barrier jets down the
# southeast coast do the same. Events with no analyzed pressure anywhere in
# their track, centred in this region, are flagged as terrain-forced candidates
# rather than being quietly dropped from a pressure-based climatology.
CAPE_FAREWELL = (59.8, -43.9)
TIPJET_RADIUS_KM = 550.0
TIPJET_FIX_FRACTION = 0.5

EVENT_CLASSES = {
    "low": {"label": "Synoptic low",
            "desc": "A central pressure was analyzed for at least one fix."},
    "tipjet": {"label": "Terrain-forced (tip jet candidate)",
               "desc": "No analyzed central pressure anywhere in the track, and most "
                       "fixes within %d km of Cape Farewell - the signature of a "
                       "Greenland tip jet or barrier jet rather than a cyclone centre."
                       % int(TIPJET_RADIUS_KM)},
    "nocentre": {"label": "No analyzed centre",
                 "desc": "No analyzed central pressure anywhere in the track, away from "
                         "the Greenland terrain-forced region. Cause not established."},
}

# Wire format. Lows and fixes are emitted as plain arrays in these orders; the
# page turns them back into objects. Append to the end when adding a field -
# never reorder, or an old cached payload decodes into the wrong columns.
LOW_FIELDS = [
    "id", "basin", "season", "num", "start", "end", "durH", "n", "peak",
    "hfN", "hfH", "minP", "minPAt", "minPLat", "minPLon", "lat0", "lon0",
    "latMax", "deep24", "berg", "bomb", "distNm", "spdKt", "spdMaxKt",
    "idOk", "timesSuspect", "split", "month", "cls", "noPresN", "glFixes", "fixes",
]
FIX_FIELDS = ["date", "lat", "lon", "cat", "pres"]

COLUMN_ALIASES = {
    "id": ("id", "stormid", "lowid"),
    "date": ("date", "datetime", "yyyymmddhh"),
    "lat": ("latitude", "lat"),
    "lon": ("longitude", "lon", "long"),
    "cat": ("category", "cat", "class"),
    "pres": ("pressure", "pres", "mslp", "minpressure"),
}


# ---------------------------------------------------------------------------
# QC reporting
# ---------------------------------------------------------------------------

class QC:
    def __init__(self) -> None:
        self.notes: list[dict] = []
        self.counts: Counter = Counter()

    def note(self, basin, row, low_id, date, kind, detail) -> None:
        self.notes.append({"basin": basin, "row": row, "id": low_id,
                           "date": date, "kind": kind, "detail": detail})

    def bump(self, key, by=1) -> None:
        self.counts[key] += by


# ---------------------------------------------------------------------------
# Field normalization
# ---------------------------------------------------------------------------

def normalize_id(raw: str):
    """Low IDs are SSSSEEEEnn: season start year, season end year, sequence."""
    s = (raw or "").strip()
    if len(s) == 10 and s.isdigit():
        start, end, num = int(s[:4]), int(s[4:8]), int(s[8:])
        if end == start + 1:
            return {"id": s, "ok": True, "season": start, "num": num, "detail": None}
        return {"id": s, "ok": False, "season": start, "num": num,
                "detail": f"ID season halves are not consecutive years ({start}/{end})"}
    if not s:
        return {"id": "(blank)", "ok": False, "season": None, "num": None,
                "detail": "Row has no low ID"}
    return {"id": s, "ok": False, "season": None, "num": None,
            "detail": f'ID "{s}" is not a 10-digit season+sequence ID; '
                      f"season inferred from the date"}


def days_in_month(y: int, mo: int) -> int:
    dim = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
    if mo == 2 and ((y % 4 == 0 and y % 100 != 0) or y % 400 == 0):
        dim = 29
    return dim


def parse_date_digits(s: str):
    if len(s) != 10 or not s.isdigit():
        return None
    y, mo, d, h = int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:])
    if not (1900 <= y <= 2100) or not (1 <= mo <= 12) or d < 1 or not (0 <= h <= 23):
        return None
    dim = days_in_month(y, mo)
    rolled = False
    if d > dim:
        if d > dim + 3:            # a typo this far out is not a month roll-over
            return None
        d -= dim
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
        rolled = True
    return {"value": y * 1000000 + mo * 10000 + d * 100 + h,
            "rolled": rolled, "synoptic": h in SYNOPTIC_HOURS}


def normalize_date(raw: str):
    """YYYYMMDDHH, with repairs for the malformed dates present in the archive."""
    s = "".join(ch for ch in (raw or "").strip() if ch.isdigit())
    if not s:
        return {"value": None, "kind": "date-bad", "detail": "Blank date"}

    if len(s) == 8:
        padded = parse_date_digits(s + "00")
        if padded:
            return {"value": padded["value"], "kind": "date-repaired",
                    "detail": f'Date had no hour; read as {padded["value"]} (00Z assumed)'}

    if len(s) == 11:
        # One stray digit. Accept only if exactly one deletion yields a valid
        # synoptic time (the archive has 20241101018 -> 2024110118).
        cands = set()
        for i in range(len(s)):
            trial = parse_date_digits(s[:i] + s[i + 1:])
            if trial and trial["synoptic"] and not trial["rolled"]:
                cands.add(trial["value"])
        if len(cands) == 1:
            value = cands.pop()
            return {"value": value, "kind": "date-repaired",
                    "detail": f'11-digit date "{s}" read as {value} (one stray digit removed)'}
        return {"value": None, "kind": "date-bad",
                "detail": f'11-digit date "{s}" has {len(cands)} equally valid readings; row dropped'}

    if len(s) != 10:
        return {"value": None, "kind": "date-bad",
                "detail": f'Date "{s}" is {len(s)} digits, expected 10 (YYYYMMDDHH)'}

    parsed = parse_date_digits(s)
    if not parsed:
        return {"value": None, "kind": "date-bad",
                "detail": f'Date "{s}" is not a real date/time'}
    if parsed["rolled"]:
        return {"value": parsed["value"], "kind": "date-repaired",
                "detail": f'Date "{s}" has a day past the end of that month; '
                          f'rolled to {parsed["value"]}'}
    if not parsed["synoptic"]:
        return {"value": parsed["value"], "kind": "date-note",
                "detail": f"Off-synoptic hour ({s[8:]}Z); kept as-is"}
    return {"value": parsed["value"], "kind": "date-note", "detail": None}


def to_number(raw):
    s = (raw or "").strip()
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def in_basin(lon: float, lo: float, hi: float) -> bool:
    if lo <= hi:
        return lo <= lon <= hi
    return lon >= lo or lon <= hi          # range wraps the dateline


def normalize_position(raw_lat, raw_lon, basin_label, lon_range):
    """A fix with no usable position is dropped.

    The archive uses NA positions as an "absorbed here, position not analyzed"
    marker; plotting those at 0,0 would put a hurricane force low on the equator.
    """
    lat, lon = to_number(raw_lat), to_number(raw_lon)
    if lat is None or lon is None:
        return {"ok": False,
                "detail": f'Position "{(raw_lat or "").strip()}, {(raw_lon or "").strip()}" '
                          f"is not numeric; fix dropped"}
    if not (-90.0 <= lat <= 90.0):
        return {"ok": False, "detail": f"Latitude {lat} is out of range; fix dropped"}

    while lon > 180.0:
        lon -= 360.0
    while lon < -180.0:
        lon += 360.0

    detail = None
    if lat < 0:
        detail = f"Latitude {lat} is in the Southern Hemisphere; kept but check the sign"
    elif not in_basin(lon, *lon_range):
        detail = (f"Longitude {lon} is outside the usual {basin_label} range; "
                  f"kept but check the sign")
    return {"ok": True, "lat": round(lat, 2), "lon": round(lon, 2), "detail": detail}


def normalize_category(raw):
    s = "".join(ch for ch in (raw or "").strip().upper() if ch.isalnum() or ch == "/")
    if s in CATEGORIES:
        return {"code": s, "kind": "ok", "detail": None}
    if s in CATEGORY_ALIASES:
        mapped = CATEGORY_ALIASES[s]
        return {"code": mapped, "kind": "mapped",
                "detail": f'Category "{(raw or "").strip()}" read as {mapped} '
                          f'({CATEGORIES[mapped]["label"]})'}
    return {"code": "UNK", "kind": "unknown",
            "detail": f'Category "{(raw or "").strip()}" is not a known code; '
                      f"shown as Unclassified"}


def normalize_pressure(raw):
    s = (raw or "").strip().upper()
    if s in PRESSURE_SENTINELS:
        return {"value": None, "kind": "none", "detail": None}
    starred = s.endswith("*")
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    try:
        n = float(cleaned)
    except ValueError:
        return {"value": None, "kind": "dropped",
                "detail": f'Pressure "{(raw or "").strip()}" is not a number; '
                          f"shown as no pressure"}
    if not (PRESSURE_MIN <= n <= PRESSURE_MAX):
        return {"value": None, "kind": "dropped",
                "detail": f"Pressure {n:g} hPa is outside {PRESSURE_MIN:g}-{PRESSURE_MAX:g}; "
                          f"shown as no pressure"}
    if starred:
        return {"value": n, "kind": "repaired",
                "detail": f'Pressure "{(raw or "").strip()}" read as {n:g} hPa '
                          f"(annotation dropped)"}
    return {"value": n, "kind": "ok", "detail": None}


def season_from_date(yyyymmddhh: int) -> int:
    y = yyyymmddhh // 1000000
    mo = (yyyymmddhh // 10000) % 100
    return y if mo >= 7 else y - 1


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def map_columns(header):
    cols = {}
    for i, name in enumerate(header):
        key = "".join(ch for ch in str(name).lower() if ch.isalnum())
        for field, aliases in COLUMN_ALIASES.items():
            if field not in cols and key in aliases:
                cols[field] = i
    return cols


def read_basin(path, key, label, lon_range, qc, lows):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if len(rows) < 2:
        return 0

    cols = map_columns(rows[0])
    missing = [f for f in COLUMN_ALIASES if f not in cols]
    if missing:
        raise SystemExit(f"{path}: no column found for {', '.join(missing)}")

    seen = set()
    data_rows = 0

    for idx, row in enumerate(rows[1:], start=2):
        if not any(str(c).strip() for c in row):
            continue
        data_rows += 1

        def cell(field):
            i = cols[field]
            return str(row[i]).strip() if i < len(row) else ""

        raw_id, raw_date = cell("id"), cell("date")
        id_info = normalize_id(raw_id)
        date_info = normalize_date(raw_date)

        if date_info["value"] is None:
            qc.note(key, idx, raw_id, raw_date, "date-bad", date_info["detail"])
            qc.bump("rowsDropped")
            continue
        if date_info["detail"]:
            qc.note(key, idx, raw_id, raw_date, date_info["kind"], date_info["detail"])
            qc.bump("datesRepaired" if date_info["kind"] == "date-repaired" else "dateNotes")

        pos = normalize_position(cell("lat"), cell("lon"), label, lon_range)
        if not pos["ok"]:
            qc.note(key, idx, raw_id, date_info["value"], "position-bad", pos["detail"])
            qc.bump("rowsDropped")
            continue
        if pos["detail"]:
            qc.note(key, idx, raw_id, date_info["value"], "position-note", pos["detail"])
            qc.bump("positionNotes")

        cat = normalize_category(cell("cat"))
        if cat["detail"]:
            qc.note(key, idx, raw_id, date_info["value"], "category-" + cat["kind"],
                    cat["detail"])
            qc.bump("categoriesMapped" if cat["kind"] == "mapped" else "categoriesUnknown")

        pres = normalize_pressure(cell("pres"))
        if pres["detail"]:
            qc.note(key, idx, raw_id, date_info["value"], "pressure-" + pres["kind"],
                    pres["detail"])
            qc.bump("pressuresRepaired" if pres["kind"] == "repaired" else "pressuresDropped")

        fingerprint = (id_info["id"], date_info["value"], pos["lat"], pos["lon"],
                       cat["code"], pres["value"])
        if fingerprint in seen:
            qc.bump("exactDuplicates")
            continue
        seen.add(fingerprint)

        if not id_info["ok"]:
            qc.note(key, idx, raw_id, date_info["value"], "id-bad", id_info["detail"])
            qc.bump("idsSuspect")

        season = id_info["season"] if id_info["season"] is not None \
            else season_from_date(date_info["value"])
        low_key = f'{key}:{id_info["id"]}'
        low = lows.get(low_key)
        if low is None:
            low = {"key": low_key, "id": id_info["id"], "basin": key, "season": season,
                   "num": id_info["num"], "idOk": id_info["ok"], "fixes": []}
            lows[low_key] = low
        low["fixes"].append([date_info["value"], pos["lat"], pos["lon"],
                             cat["code"], pres["value"]])
        qc.bump("fixes")

    qc.bump("rowsRead", data_rows)
    return data_rows


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

def to_dt(yyyymmddhh: int) -> datetime:
    s = str(yyyymmddhh)
    return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:]), tzinfo=timezone.utc)


def great_circle_nm(lat1, lon1, lat2, lon2) -> float:
    r = 3440.065                                    # nautical miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    # Keep the shorter way round when a track crosses the dateline.
    if dl > math.pi:
        dl -= 2 * math.pi
    elif dl < -math.pi:
        dl += 2 * math.pi
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


# Two unrelated lows months apart sometimes share one sequence number in the
# archive. Consecutive fixes further apart than this are treated as separate
# events (suffixed a/b/...) rather than one impossibly long-lived low - a
# 6-hourly track with a multi-day hole is not one cyclone.
SPLIT_GAP_HOURS = 48


def split_reused_ids(low, qc):
    """Split one archive ID into separate events across implausible time gaps."""
    fixes = sorted(low["fixes"], key=lambda f: f[0])
    segments, current = [], [fixes[0]]
    for prev, cur in zip(fixes, fixes[1:]):
        gap = (to_dt(cur[0]) - to_dt(prev[0])).total_seconds() / 3600.0
        if gap > SPLIT_GAP_HOURS:
            segments.append(current)
            current = []
        current.append(cur)
    segments.append(current)

    if len(segments) == 1:
        low["fixes"] = fixes
        return [low]

    qc.note(low["basin"], None, low["id"], fixes[0][0], "id-reused",
            f'ID {low["id"]} covers {len(segments)} groups of fixes separated by more '
            f"than {SPLIT_GAP_HOURS} h; split into separate events "
            f'({", ".join(low["id"] + chr(97 + i) for i in range(len(segments)))})')
    qc.bump("idsReused")

    out = []
    for i, seg in enumerate(segments):
        part = dict(low)
        part["id"] = low["id"] + chr(97 + i)
        part["key"] = f'{low["basin"]}:{part["id"]}'
        part["fixes"] = seg
        part["idOk"] = False
        part["split"] = True
        # The season on a reused ID cannot be trusted; take it from the fixes.
        part["season"] = season_from_date(seg[0][0])
        out.append(part)
    return out


def classify(low):
    """Split pressure-less events from synoptic lows, and flag the tip jets.

    No analyzed pressure is not missing data in the usual sense: for a tip jet
    there is no cyclone centre to analyze. Lumping those in with synoptic lows
    makes every pressure statistic a statement about a different population
    than the event count, so they get their own class.
    """
    fixes = low["fixes"]
    near = sum(1 for f in fixes
               if great_circle_nm(f[1], f[2], *CAPE_FAREWELL) * 1.852 <= TIPJET_RADIUS_KM)
    low["glFixes"] = near
    low["noPresN"] = sum(1 for f in fixes if f[4] is None)

    if any(f[4] is not None for f in fixes):
        low["cls"] = "low"
    elif fixes and near / len(fixes) >= TIPJET_FIX_FRACTION:
        low["cls"] = "tipjet"
    else:
        low["cls"] = "nocentre"


def derive(low, qc):
    """Add the per-low climatology metrics the page displays."""
    fixes = sorted(low["fixes"], key=lambda f: f[0])
    low["fixes"] = fixes

    # Two fixes sharing a timestamp mean one date is mistyped. Both are kept -
    # they are real positions - but the low's duration is not trustworthy.
    for a, b in zip(fixes, fixes[1:]):
        if a[0] == b[0]:
            low["timesSuspect"] = True
            qc.note(low["basin"], None, low["id"], a[0], "time-duplicate",
                    f"Two different fixes share {a[0]}Z; both kept, but one date is "
                    f"probably mistyped")
            qc.bump("duplicateTimes")
            break

    start_dt, end_dt = to_dt(fixes[0][0]), to_dt(fixes[-1][0])
    low["start"] = fixes[0][0]
    low["end"] = fixes[-1][0]
    low["durH"] = int(round((end_dt - start_dt).total_seconds() / 3600.0))
    low["n"] = len(fixes)
    low["month"] = (fixes[0][0] // 10000) % 100

    ranked = max(fixes, key=lambda f: CATEGORIES[f[3]]["rank"])
    low["peak"] = ranked[3]

    # Hours spent at hurricane force: each HF fix represents the 6-hourly
    # analysis interval it sits in. With 6-hourly data this is a count x 6,
    # which is an interval estimate, not a measured duration.
    hf_fixes = [f for f in fixes if f[3] == "HF"]
    low["hfN"] = len(hf_fixes)
    low["hfH"] = len(hf_fixes) * 6

    pressures = [(f[0], f[4], f[1], f[2]) for f in fixes if f[4] is not None]
    if pressures:
        best = min(pressures, key=lambda p: p[1])
        low["minP"] = best[1]
        low["minPAt"] = best[0]
        low["minPLat"] = best[2]
        low["minPLon"] = best[3]
    else:
        low["minP"] = None
        low["minPAt"] = None

    low["lat0"], low["lon0"] = fixes[0][1], fixes[0][2]
    low["latMax"] = max(f[1] for f in fixes)

    # Deepening. Bergerons normalize the 24-h pressure fall by latitude:
    #   B = (dp/24h) * sin(60) / sin(mean lat);  B >= 1 is the classic "bomb".
    # Most archive tracks begin at or near HF onset and run < 24 h, so this is
    # available for a minority of lows - which is itself worth showing.
    best24 = None
    for i, (t_i, _, _, _, p_i) in enumerate(fixes):
        if p_i is None:
            continue
        for t_j, lat_j, _, _, p_j in fixes[i + 1:]:
            hours = (to_dt(t_j) - to_dt(t_i)).total_seconds() / 3600.0
            if p_j is None or hours <= 0:
                continue
            if hours > 24.0:
                break
            if hours < 18.0:                     # need most of a day to call it
                continue
            drop = (p_i - p_j) * (24.0 / hours)  # hPa per 24 h
            mean_lat = (fixes[i][1] + lat_j) / 2.0
            sin_lat = math.sin(math.radians(abs(mean_lat)))
            # 1 Bergeron = 24 hPa/24 h at 60 deg N (Sanders & Gyakum 1980).
            berg = (drop / 24.0) * math.sin(math.radians(60.0)) / sin_lat \
                if sin_lat > 0.05 else None
            if best24 is None or drop > best24[0]:
                best24 = (drop, berg, t_i, t_j)
    if best24:
        low["deep24"] = round(best24[0], 1)
        low["berg"] = round(best24[1], 2) if best24[1] is not None else None
        low["bomb"] = bool(best24[1] is not None and best24[1] >= 1.0)
    else:
        low["deep24"] = None
        low["berg"] = None
        low["bomb"] = False

    # Translation speed along the track (kt), skipping duplicate timestamps.
    dist = 0.0
    hours = 0.0
    fastest = None
    for a, b in zip(fixes, fixes[1:]):
        dh = (to_dt(b[0]) - to_dt(a[0])).total_seconds() / 3600.0
        if dh <= 0:
            continue
        d = great_circle_nm(a[1], a[2], b[1], b[2])
        dist += d
        hours += dh
        leg = d / dh
        if fastest is None or leg > fastest:
            fastest = leg
    low["distNm"] = int(round(dist))
    low["spdKt"] = round(dist / hours, 1) if hours > 0 else None
    low["spdMaxKt"] = round(fastest, 1) if fastest is not None else None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def build():
    qc = QC()
    lows: dict[str, dict] = {}
    basin_info = []

    for key, label, rel, lon_range in BASINS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            raise SystemExit(f"missing input: {rel}")
        rows = read_basin(path, key, label, lon_range, qc, lows)
        basin_info.append({"key": key, "label": label, "source": rel, "rows": rows})

    out = []
    for low in lows.values():
        if not low["fixes"]:
            qc.note(low["basin"], None, low["id"], None, "low-empty",
                    "Every row for this low was unusable; the low is not plotted")
            qc.bump("lowsDropped")
            continue
        for part in split_reused_ids(low, qc):
            derive(part, qc)
            classify(part)
            qc.bump("class_" + part["cls"])
            out.append(part)

    out.sort(key=lambda l: (l["start"], l["basin"]))
    qc.bump("lows", len(out))

    seasons = sorted({l["season"] for l in out})
    for info in basin_info:
        info["lows"] = sum(1 for l in out if l["basin"] == info["key"])

    # Records go out array-encoded against LOW_FIELDS rather than as objects:
    # repeating 20-odd key names across ~1900 lows tripled the payload. The
    # page rebuilds objects from these on load.
    lows_encoded = [[low.get(f) for f in LOW_FIELDS] for low in out]

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "basins": basin_info,
        "categories": CATEGORIES,
        "eventClasses": EVENT_CLASSES,
        "recordStart": RECORD_START,
        "seasons": [{"start": s, "label": season_label(s)} for s in seasons],
        "lowFields": LOW_FIELDS,
        "fixFields": FIX_FIELDS,
        "lows": lows_encoded,
        "qc": {"counts": dict(sorted(qc.counts.items())), "notes": qc.notes},
    }
    return payload


def qc_report(payload) -> str:
    lines = ["HF extratropical low archive - data quality report",
             f"generated {payload['generated']}", ""]
    for k, v in payload["qc"]["counts"].items():
        lines.append(f"  {k:24s} {v}")
    lines.append("")
    by_kind = defaultdict(list)
    for n in payload["qc"]["notes"]:
        by_kind[n["kind"]].append(n)
    for kind in sorted(by_kind):
        lines.append(f"{kind} ({len(by_kind[kind])})")
        for n in by_kind[kind]:
            where = f'{n["basin"]} row {n["row"]}' if n["row"] else f'{n["basin"]}'
            lines.append(f'  {where}  id={n["id"]} date={n["date"]}: {n["detail"]}')
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build but write nothing")
    args = ap.parse_args()

    payload = build()
    counts = payload["qc"]["counts"]
    print(f"lows {counts.get('lows', 0)}  fixes {counts.get('fixes', 0)}  "
          f"seasons {len(payload['seasons'])}  "
          f"dropped rows {counts.get('rowsDropped', 0)}  "
          f"notes {len(payload['qc']['notes'])}")

    if args.check:
        return

    data_dir = os.path.join(ROOT, "docs", "data")
    os.makedirs(data_dir, exist_ok=True)
    compact = json.dumps(payload, separators=(",", ":"), allow_nan=False)

    with open(os.path.join(data_dir, "hf-lows.json"), "w", encoding="utf-8") as fh:
        fh.write(compact)
    # A .js twin so the page also works when opened straight off disk, where
    # fetch() of a local JSON file is blocked by the file:// origin rules.
    with open(os.path.join(data_dir, "hf-lows.js"), "w", encoding="utf-8") as fh:
        fh.write("/* generated by tools/build_hf_lows.py - do not edit */\n")
        fh.write("window.HF_DATA = " + compact + ";\n")
    with open(os.path.join(data_dir, "qc-report.txt"), "w", encoding="utf-8") as fh:
        fh.write(qc_report(payload))

    size = os.path.getsize(os.path.join(data_dir, "hf-lows.js"))
    print(f"wrote docs/data/hf-lows.js ({size / 1024:.0f} KB), hf-lows.json, qc-report.txt")


if __name__ == "__main__":
    main()
