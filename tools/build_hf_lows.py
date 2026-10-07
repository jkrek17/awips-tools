#!/usr/bin/env python3
"""Build the HF extratropical low archive site data from the raw CSV exports.

Reads the per-basin CSV exports of the HF low archive spreadsheet, normalizes
two decades of hand-entered rows, derives the per-low climatology metrics the
web page needs, and writes:

    docs/data/hf-lows.js     window.HF_DATA = {...}   (works from file://)
    docs/data/hf-lows.json   the same payload, for anyone else who wants it
    docs/data/qc-report.txt  every repair, flag and drop, in plain text

Optionally reads data/hf_lows/precursors.csv - fixes recovered from the OPC High
Seas Forecasts for the 72 h before each event's first hurricane-force fix - and
attaches them as a separate series (see "Pre-HF backfill" below). The file is
optional: without it every backfill field is null and nothing else changes.

The reader is deliberately tolerant: it repairs what is unambiguous, drops what
is not, and reports every decision. Nothing is silently discarded.

Usage:
    python3 tools/build_hf_lows.py                 # uses data/hf_lows/*.csv
    python3 tools/build_hf_lows.py --check         # build, but write nothing
    python3 tools/build_hf_lows.py --no-backfill   # ignore precursors.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import re
import subprocess
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

# Fastest plausible translation speed for a cyclone centre, in knots. Above
# this the build reports a position error rather than a storm - see the note
# in derive() for how the number was chosen from the archive's own
# distribution.
SPEED_IMPLAUSIBLE_KT = 90.0

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
    # Appended after the original wire format (never reorder). See the block
    # comment above derive() for why the archive carries two versions of the
    # deepening and track figures, and what each one is for.
    "deep24All", "bergAll", "bombAll", "hfDurH", "hfDistNm", "hfSpdKt", "hfSpdMaxKt",
    # The pre-HF backfill (data/hf_lows/precursors.csv), appended after the
    # above. All null when that file is absent. `Bf` is the third basis for the
    # deepening - see "Pre-HF backfill" below.
    "preFixes", "preN", "preH", "preSrc", "deep24Bf", "bergBf", "bombBf", "deepRelH",
    # Hours of gapless pressure record behind the first HF fix, whether or not
    # it reached BACKFILL_MIN_LEAD_H. deepRelH >= 18 - bfLeadH by construction,
    # so no statement about WHEN the deepening happened is safe without it.
    "bfLeadH",
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


SEASON_START_MONTH = 6   # storm season runs 1 Jun - 31 May (confirmed by the archive owner)


def season_from_date(yyyymmddhh: int) -> int:
    """Season start year for a date: the season labelled 2001-02 runs 1 Jun 2001
    to 31 May 2002, so June-December belong to that year and January-May to the
    year before."""
    y = yyyymmddhh // 1000000
    mo = (yyyymmddhh // 10000) % 100
    return y if mo >= SEASON_START_MONTH else y - 1


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


def max_deepening(fixes):
    """Largest 24-h-normalized pressure fall among `fixes` (time-sorted), as
    (hPa per 24 h, Bergerons or None) - or None when no pair of pressures sits
    18-24 h apart. Pairs closer than 18 h are skipped: that is most of a day or
    nothing."""
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
    return best24


def deepening_stats(fixes):
    """max_deepening() in the shape the payload stores. One code path for every
    basis (HF-only, whole track, HF + backfill): three copies of a Bergeron
    calculation would drift apart the first time one of them is fixed.

    Returns {"deep24": hPa/24 h rounded to 0.1, "berg": Bergerons rounded to
    0.01 or None, "bomb": bool, "start", "end": the best pair's times}, with
    deep24/berg/start/end None and bomb False when no pair is 18-24 h apart."""
    best = max_deepening(fixes)
    if not best:
        return {"deep24": None, "berg": None, "bomb": False, "start": None, "end": None}
    drop, berg, t_i, t_j = best
    return {"deep24": round(drop, 1),
            "berg": round(berg, 2) if berg is not None else None,
            "bomb": bool(berg is not None and berg >= 1.0),
            "start": t_i, "end": t_j}


def track_stats(fixes):
    """(path length nm, mean speed kt or None, fastest leg kt or None) along
    time-sorted `fixes`, skipping legs with a duplicate timestamp."""
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
    return (dist,
            round(dist / hours, 1) if hours > 0 else None,
            round(fastest, 1) if fastest is not None else None)


# ---------------------------------------------------------------------------
# Two windows on one storm
#
# The archive's recording practice changed. From about the 2013-14 Pacific and
# 2017-18 Atlantic seasons, analysts began logging developing-hurricane-force
# (DHF) fixes before a storm's first hurricane-force fix and storm-force (S)
# fixes after its last. The storms did not change - HF fixes per event, events
# per season and median minimum pressure are flat across the whole record - but
# each event's recorded track grew at both ends. Anything measured over "the
# whole recorded track" therefore measures recording practice as much as
# weather. The sharpest case is the 24-h deepening: the extra lead fixes reach
# back into the deepening phase, so far more events clear 1 Bergeron.
#
# So the derived figures come in two versions:
#
#   HF window  (the default; the names the page and the regressions use)
#       deep24  berg  bomb                     pressures at HF-category fixes only
#       hfDurH  hfDistNm  hfSpdKt  hfSpdMaxKt  first HF fix to last HF fix
#       hfN  hfH                               HF fixes / hours (always HF-only)
#     The same observational window in every era, so they compare backwards.
#
#   Recorded track  (the original definitions, kept)
#       deep24All  bergAll  bombAll            every fix
#       durH  n  distNm  spdKt  spdMaxKt       first fix to last fix
#     Richer after the change - it genuinely contains more of the deepening
#     phase - but not comparable with seasons before it.
#
# Unaffected and left alone: event counts, minP/minPAt (the pressure minimum
# sits in the HF period in either practice), peak, and season/month (assigned
# from the ID and first fix, so they do not move).
# ---------------------------------------------------------------------------

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

    # Deepening, twice. `deep24`/`berg`/`bomb` are measured on the HF-category
    # fixes only; `deep24All`/`bergAll`/`bombAll` on every recorded fix. See the
    # block comment above derive() for why.
    #
    # Bergerons normalize the 24-h pressure fall by latitude:
    #   B = (dp/24h) * sin(60) / sin(mean lat);  B >= 1 is the classic "bomb".
    # Most HF tracks run < 18 h, so this is available for a minority of lows -
    # which is itself worth showing.
    # A third basis, `Bf` (HF fixes + the pre-HF backfill), is added by
    # attach_backfill() through the same deepening_stats().
    for suffix, subset in (("", [f for f in fixes if f[3] == "HF"]), ("All", fixes)):
        stats = deepening_stats(subset)
        low["deep24" + suffix] = stats["deep24"]
        low["berg" + suffix] = stats["berg"]
        low["bomb" + suffix] = stats["bomb"]

    # Translation speed along the track (kt), skipping duplicate timestamps.
    low["distNm"], low["spdKt"], low["spdMaxKt"] = track_stats(fixes)
    low["distNm"] = int(round(low["distNm"]))

    # A centre that appears to move faster than any cyclone can is a position
    # error, not a fast storm. The build has always computed spdMaxKt and
    # never said anything about it, so errors of this kind have sat in the
    # archive unremarked: atl:2006200703 implied 133 kt for years because two
    # latitudes read 56.3/56.9 where the track and ERA5 both say 46.3/46.9.
    #
    # The threshold is empirical. Across the archive's multi-fix events the
    # fastest leg has a median of 33 kt and a 95th percentile of 68 kt - a
    # deeply embedded low in a strong jet really can run at 60-70 kt - and
    # then the distribution breaks into a tail reaching 542 kt. SPEED_IMPLAUSIBLE_KT
    # sits above that break, so a genuinely fast storm is not flagged and
    # roughly 2.5% of events are, which is a reviewable list rather than noise.
    #
    # One threshold catches three different mistakes, because each shows up as
    # impossible motion: a mistyped digit (atl:2006200703), a flipped longitude
    # sign (pac:2016201716, 123W to 132E in one step), and a duplicated
    # timestamp carrying a contradictory position.
    if low["spdMaxKt"] is not None and low["spdMaxKt"] >= SPEED_IMPLAUSIBLE_KT:
        qc.note(low["basin"], None, low["id"], low["start"], "speed-implausible",
                f"fastest leg {low['spdMaxKt']:.0f} kt between consecutive fixes; "
                f"a cyclone centre does not move that fast, so check these "
                f"positions for a mistyped digit or a sign error")
        qc.bump("speedImplausible")

    # The same track figures over the hurricane-force window only: first HF fix
    # to last HF fix, keeping any fix in between (a dip to storm force between
    # two HF fixes is still part of the path; cutting the corner would
    # understate the distance). An event with a single HF fix has no window.
    hf_idx = [i for i, f in enumerate(fixes) if f[3] == "HF"]
    if len(hf_idx) >= 2:
        window = fixes[hf_idx[0]:hf_idx[-1] + 1]
        dist, spd, spd_max = track_stats(window)
        low["hfDurH"] = int(round((to_dt(window[-1][0]) - to_dt(window[0][0]))
                                  .total_seconds() / 3600.0))
        low["hfDistNm"] = int(round(dist))
        low["hfSpdKt"] = spd
        low["hfSpdMaxKt"] = spd_max
    else:
        low["hfDurH"] = 0 if hf_idx else None
        low["hfDistNm"] = 0 if hf_idx else None
        low["hfSpdKt"] = None
        low["hfSpdMaxKt"] = None


# ---------------------------------------------------------------------------
# Pre-HF backfill
#
# The archive records the hurricane-force segment and almost nothing before it,
# and the deepening is mostly over by the time the first HF fix is logged. So
# the HF-only statistic is comparable across eras but blind to the deepening.
# tools/track_hsf.py recovers the missing phase from the OPC High Seas
# Forecasts into data/hf_lows/precursors.csv; this section attaches it.
#
# The human archive is never altered. Recovered fixes live in their own series
# (preFixes) with a per-fix source tag, so a reader can always tell a recovered
# fix from a human-analysed one, and a recovered fix never replaces or edits an
# archive fix. A third basis for the deepening results:
#
#   no suffix  HF-category fixes only                 era-safe floor, undercounts
#   All        the whole recorded archive track       not comparable across years
#   Bf         HF fixes + backfill (+ the archive's own fixes inside the same
#              window - see backfill_low)             the intended measure
#
# Why Bf may use the archive's non-HF fixes when `All` may not. What makes `All`
# era-contaminated is not that it uses non-HF fixes; it is that the AVAILABILITY
# of those fixes jumped in 2013/2017, so the same storm is measured over a
# longer record afterwards. A recovered fix and an archive lead fix at the same
# valid time are the same analysis by the same office (where checked, the
# pressures agree exactly), so preferring the human-analysed one is strictly
# better and costs no era-safety. Bf is era-safe if and only if its COVERAGE is
# era-uniform; the basis is not the thing to police, coverage is. That is why
# the build measures coverage season by season and trips `coverageTrend` (see
# backfill_summary) instead of trusting the basis.
#
# All three go through deepening_stats(); Bf is emitted only when the record
# genuinely covers the window (BACKFILL_MIN_LEAD_H below) and is null otherwise,
# never the HF-only number under another name.
# ---------------------------------------------------------------------------

BACKFILL_PATH = "data/hf_lows/precursors.csv"
PRECURSOR_COLUMNS = ["basin", "event_id", "valid", "lat", "lon", "pres", "warn_cat",
                     "source", "match_nm", "conf"]

# The agreed window: 72 h ending at each event's first HF fix, identical in
# every era. A row before it is outside the definition; a row after the first
# HF fix is not "pre-HF" at all (the archive owns that period).
BACKFILL_WINDOW_H = 72

# Coverage needed before a Bf statistic is emitted: a gapless chain of
# pressures, steps no longer than BACKFILL_MAX_STEP_H, running back at least
# BACKFILL_MIN_LEAD_H from the first HF fix.
#
#   24 h is the shortest lead that observes one complete 24-h window ending at
#   HF onset - the window the HF-only statistic can never see. With less, every
#   window that reaches back before onset is half-observed: its far end is
#   simply missing, and the best *observed* window would be reported as if it
#   were the best window - the HF-only number again, under a Bf name. A 24-h
#   pair that merely reaches a few hours into the lead is the half-covered
#   case, so "a 24-h pair can be computed" is not the test.
#
#   6 h steps because the source is 4x-daily on the 00/06/12/18Z grid: a longer
#   step is a missing analysis or an attribution the track tool refused, not
#   normal sampling, so the record is not continuous across it. Pressure-less
#   fixes are not links in the chain.
#
#   The choice is deliberately independent of the pressures themselves.
#   Requiring, say, that the steepest window not touch the edge of the record
#   would select on the outcome and bias the very statistic being measured.
#
#   Consequence worth knowing: a lead of L hours cannot observe a window that
#   ends earlier than (18 - L) h from onset (the shortest accepted pair is
#   18 h), so deepRelH >= 18 - L by construction - at the minimum lead, no
#   earlier than -6. The sign of deepRelH is censored towards "late" for short
#   leads, and a consumer asking *when* the deepening happened should condition
#   on lead rather than pool every event. The payload does not carry the chain
#   lead itself (preH, the span of the recovered fixes, is the nearest proxy).
BACKFILL_MIN_LEAD_H = 24
BACKFILL_MAX_STEP_H = 6

# `conf` is the track tool's own grading of an attribution. A wrong precursor
# corrupts the statistic and a missing one is recoverable later, so the lowest
# grade is refused here rather than averaged in.
CONF_RANK = {"low": 0, "medium": 1, "high": 2}
BACKFILL_MIN_CONF = "medium"
PRECURSOR_SOURCES = ("hsf", "era5")
PRECURSOR_WARN_CATS = ("HF", "S", "G", "")

# A recovered fix that lands on an archive fix "agrees" when its pressure
# matches (same office, same analysis, so it should match exactly - the
# tolerance is only for float parsing) and its position is close. HSF gives
# whole degrees, so up to half a degree of rounding (~30 nm in latitude) is
# expected against the archive's finer positions.
AGREE_HPA = 0.5
AGREE_NM = 60.0

# The coverage-uniformity gate. Bf is era-safe only if the share of HF events
# with a usable window is flat across seasons. Early HSFs state the analysis as
# ".LOW 62N 35W 933 MB ..." reliably while recent ones are often area-only, so
# recovery may be BETTER early and a Bf explosive share would then inherit a
# spurious downward trend, hiding in the denominator. The gate trips when the
# seasonal share spreads over COVERAGE_SPREAD_PTS points, or its least-squares
# slope on season is more than COVERAGE_SLOPE_SE standard errors from zero. It
# only raises a flag and a QC note; what the page does about it is not decided
# here. Seasons before RECORD_START are short-counted (see RECORD_START) and
# would dominate the spread with a handful of events, so they are left out of
# the statistics (though not out of the table).
COVERAGE_SPREAD_PTS = 20.0
COVERAGE_SLOPE_SE = 2.0

# A season-basin with at least this many HF events and not one usable Bf window
# is reported as a coverage gap: the table shows every season, this makes a
# collapse in one era a QC note rather than something to be spotted by eye.
COVERAGE_ALARM_MIN_EVENTS = 5

_ISO_VALID = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2})(?::?(\d{2}))?(?::?(\d{2}))?Z?$")


def _hours(t_a: int, t_b: int) -> float:
    """Hours from YYYYMMDDHH t_a to t_b (positive when t_b is later)."""
    return (to_dt(t_b) - to_dt(t_a)).total_seconds() / 3600.0


def parse_valid(raw):
    """A precursor's valid time as YYYYMMDDHH. Accepts the archive's own 10-digit
    form and ISO 8601 ("2006-12-10T06:00:00Z"); the interface contract does not
    say which the track tool writes. Synoptic hours only: the source is the
    00/06/12/18Z analysis, and an off-grid time would break the chain test."""
    s = (raw or "").strip()
    m = _ISO_VALID.match(s)
    if m:
        y, mo, d, h, mi, sec = m.groups()
        if (mi or "00") != "00" or (sec or "00") != "00":
            return {"value": None, "detail": f'valid "{s}" is not on the hour'}
        s = y + mo + d + h
    parsed = parse_date_digits(s)
    if not parsed or parsed["rolled"]:
        return {"value": None, "detail": f'valid "{(raw or "").strip()}" is not a real date/time'}
    if not parsed["synoptic"]:
        return {"value": None,
                "detail": f'valid "{(raw or "").strip()}" is not a 00/06/12/18Z time'}
    return {"value": parsed["value"], "detail": None}


def parse_precursor(cells, row_no):
    """One precursors.csv row -> ({record}, None) or (None, (kind, detail, date)).
    Everything that cannot be trusted is refused here; nothing is guessed."""
    def bad(kind, detail, date=None):
        return None, (kind, detail, date)

    basin = cells["basin"].strip().lower()
    lon_range = next((b[3] for b in BASINS if b[0] == basin), None)
    if lon_range is None:
        return bad("precursor-malformed", f'basin "{cells["basin"].strip()}" is not one of '
                   f'{", ".join(b[0] for b in BASINS)}')
    event_id = cells["event_id"].strip()
    if not event_id:
        return bad("precursor-malformed", "row has no event_id")

    valid = parse_valid(cells["valid"])
    if valid["value"] is None:
        return bad("precursor-malformed", valid["detail"])
    date = valid["value"]

    label = next(b[1] for b in BASINS if b[0] == basin)
    pos = normalize_position(cells["lat"], cells["lon"], label, lon_range)
    if not pos["ok"]:
        return bad("precursor-malformed", pos["detail"], date)
    if pos["detail"]:
        # The archive keeps a doubtful position and notes it. A recovered one is
        # refused: there is no human analyst vouching for it.
        return bad("precursor-malformed", pos["detail"].replace("kept but check the sign",
                                                                "recovered fix refused"), date)

    pres = normalize_pressure(cells["pres"])
    if pres["kind"] == "dropped":
        return bad("precursor-malformed", pres["detail"], date)

    warn = cells["warn_cat"].strip().upper()
    if warn not in PRECURSOR_WARN_CATS:
        return bad("precursor-malformed", f'warn_cat "{warn}" is not HF, S, G or blank', date)
    source = cells["source"].strip().lower()
    if source not in PRECURSOR_SOURCES:
        return bad("precursor-malformed", f'source "{source}" is not hsf or era5', date)
    conf = cells["conf"].strip().lower()
    if conf not in CONF_RANK:
        return bad("precursor-malformed", f'conf "{conf}" is not high, medium or low', date)
    if cells["match_nm"].strip() and to_number(cells["match_nm"]) is None:
        return bad("precursor-malformed", f'match_nm "{cells["match_nm"].strip()}" is not numeric', date)
    if CONF_RANK[conf] < CONF_RANK[BACKFILL_MIN_CONF]:
        return bad("precursor-low-conf", f"attribution confidence is {conf}; "
                   f"below the {BACKFILL_MIN_CONF} minimum, not used", date)

    return ({"row": row_no, "basin": basin, "id": event_id, "date": date,
             "lat": pos["lat"], "lon": pos["lon"], "pres": pres["value"],
             "cat": warn, "source": source, "conf": conf}, None)


def read_precursors(path, qc):
    """Read and validate precursors.csv -> (records, comments).

    A wrong header is fatal, like the archive CSVs: a mis-shaped file silently
    read as empty would look exactly like "nothing recovered". Individual bad
    rows are refused with a QC note. Lines starting with '#' are comments; they
    exist so a development file can say it is synthetic."""
    records, comments, header = [], [], None
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if row and row[0].lstrip().startswith("#"):
                comments.append(",".join(row).lstrip().lstrip("#").strip())
                continue
            if not any(str(c).strip() for c in row):
                continue
            if header is None:
                header = {str(n).strip().lower(): i for i, n in enumerate(row)}
                missing = [c for c in PRECURSOR_COLUMNS if c not in header]
                if missing:
                    raise SystemExit(f"{path}: no column found for {', '.join(missing)}")
                continue
            qc.bump("precursorRows")
            cells = {c: (str(row[header[c]]) if header[c] < len(row) else "")
                     for c in PRECURSOR_COLUMNS}
            rec, err = parse_precursor(cells, reader.line_num)
            if err:
                kind, detail, date = err
                qc.note(cells["basin"].strip().lower(), reader.line_num,
                        cells["event_id"].strip(), date, kind, detail)
                qc.bump("precursorsRefused")
                qc.bump("precRefused_" + kind[len("precursor-"):])
                continue
            records.append(rec)
    return records, comments


def _same_fix(rec_pres, rec_lat, rec_lon, fix_pres, fix_lat, fix_lon):
    """Do a recovered fix and another fix at the same time describe one analysis?"""
    if (rec_pres is None) != (fix_pres is None):
        return False
    if rec_pres is not None and abs(rec_pres - fix_pres) > AGREE_HPA:
        return False
    return great_circle_nm(rec_lat, rec_lon, fix_lat, fix_lon) <= AGREE_NM


def screen_precursors(low, recs, qc):
    """The recovered rows of one event that may enter its backfill series.

    Refused, each with a QC note (the archive is the authority throughout):
      - the event has no HF fix, so there is no window to anchor;
      - later than the first HF fix: outside the agreed window, and the period
        after onset belongs to the archive;
      - more than 72 h before it: outside the agreed window;
      - at a time the archive already has a fix for this event. If it agrees
        with the archive fix it is a harmless duplicate and is counted; if it
        does not, it is a contradiction, noted in full. Either way the human
        analysis stays and the recovered row is dropped;
      - two rows for one time that disagree (neither can be preferred).
    """
    if not recs:
        return []
    first_hf = next((f for f in low["fixes"] if f[3] == "HF"), None)

    def refuse(rec, kind, detail):
        qc.note(rec["basin"], rec["row"], rec["id"], rec["date"], kind, detail)
        qc.bump("precursorsRefused")
        qc.bump("precRefused_" + kind[len("precursor-"):])

    if first_hf is None:
        for rec in recs:
            refuse(rec, "precursor-no-anchor",
                   "event has no HF fix, so there is no window to attach a precursor to")
        return []

    t_hf = first_hf[0]
    at_time = defaultdict(list)
    for f in low["fixes"]:
        at_time[f[0]].append(f)

    candidates, agreeing = [], 0
    for rec in recs:
        lead = -_hours(t_hf, rec["date"])           # hours BEFORE the first HF fix
        if lead < 0:
            refuse(rec, "precursor-late",
                   f"valid {rec['date']}Z is {-lead:g} h after the first HF fix "
                   f"({t_hf}Z); outside the {BACKFILL_WINDOW_H}-h pre-HF window, rejected")
        elif lead > BACKFILL_WINDOW_H:
            refuse(rec, "precursor-early",
                   f"valid {rec['date']}Z is {lead:g} h before the first HF fix "
                   f"({t_hf}Z); outside the {BACKFILL_WINDOW_H}-h pre-HF window, rejected")
        elif rec["date"] in at_time:
            arch = at_time[rec["date"]]
            if any(_same_fix(rec["pres"], rec["lat"], rec["lon"], a[4], a[1], a[2])
                   for a in arch):
                agreeing += 1
                qc.bump("precDuplicatesOfArchive")
            else:
                a = arch[0]
                refuse(rec, "precursor-contradiction",
                       f"archive already has a fix at {rec['date']}Z "
                       f"({a[1]:g}, {a[2]:g}, {a[3]}, {a[4] if a[4] is not None else 'no pres'}) "
                       f"that this {rec['source']} fix does not match "
                       f"({rec['lat']:g}, {rec['lon']:g}, "
                       f"{rec['pres'] if rec['pres'] is not None else 'no pres'}); "
                       f"archive kept, recovered fix dropped")
        else:
            candidates.append(rec)
    if agreeing:
        qc.note(low["basin"], None, low["id"], t_hf, "precursor-duplicate",
                f"{agreeing} recovered fix{'es' if agreeing != 1 else ''} landed on archive "
                f"fixes and agree with them; the archive fixes stand and the recovered rows "
                f"are not used")

    # Two recovered rows for one time: keep one only if they say the same thing.
    by_time = defaultdict(list)
    for rec in candidates:
        by_time[rec["date"]].append(rec)
    accepted = []
    for date in sorted(by_time):
        group = sorted(by_time[date], key=lambda r: (r["source"] != "hsf", r["row"]))
        head = group[0]
        if all(_same_fix(r["pres"], r["lat"], r["lon"], head["pres"], head["lat"], head["lon"])
               for r in group[1:]):
            accepted.append(head)
            for dup in group[1:]:
                qc.bump("precDuplicatesOfRecovered")
        else:
            for r in group:
                refuse(r, "precursor-contradiction",
                       f"{len(group)} recovered rows for {date}Z disagree with each other; "
                       f"none is used")
    return accepted


def chain_lead_h(series, t_hf):
    """Hours of gapless pressure record running back from the first HF fix.

    Walks backwards from the first HF fix through the pressure-bearing fixes of
    `series` (time-sorted) while each step is <= BACKFILL_MAX_STEP_H. 0 when the
    first HF fix itself has no pressure: there is then nothing to attach the
    chain to."""
    pressured = [f for f in series if f[4] is not None]
    anchor = next((i for i, f in enumerate(pressured)
                   if f[0] == t_hf and f[3] == "HF"), None)
    if anchor is None:
        return 0.0
    reach = t_hf
    for prev in reversed(pressured[:anchor]):
        if _hours(prev[0], reach) > BACKFILL_MAX_STEP_H:
            break
        reach = prev[0]
    return _hours(reach, t_hf)


def backfill_low(low, accepted):
    """Attach the backfill fields to one derived low. Never touches low["fixes"].

    The Bf series is the recovered fixes + the archive's HF fixes + any archive
    fix of its own that falls inside the same 72 h window. The last group is
    not in the contract's wording ("archive HF fixes + backfill") but cannot be
    left out: a recovered row that lands on one of those fixes is rejected so
    the human analysis wins, so leaving them out of the series would punch a
    hole exactly where the archive is best (the DHF lead fixes of the recent
    seasons) and make coverage look worst in the eras where it is richest.

    It does not readmit the contamination the HF-only statistic removes: the
    recovered and the archive fix at one valid time are the same analysis, so
    which one is used changes no number. The risk that remains is uneven
    coverage across eras, which backfill_summary() measures."""
    low["preFixes"] = [[r["date"], r["lat"], r["lon"], r["pres"], r["cat"], r["source"]]
                       for r in accepted]
    low["preN"] = len(accepted)
    sources = {r["source"] for r in accepted}
    low["preSrc"] = None if not sources else (sources.pop() if len(sources) == 1 else "mixed")

    first_hf = next((f for f in low["fixes"] if f[3] == "HF"), None)
    low["preH"] = int(round(_hours(accepted[0]["date"], first_hf[0]))) \
        if accepted and first_hf else 0
    for k in ("deep24Bf", "bergBf", "bombBf", "deepRelH", "bfLeadH"):
        low[k] = None
    if first_hf is None:
        return
    t_hf = first_hf[0]

    series = [[r["date"], r["lat"], r["lon"], r["cat"], r["pres"]] for r in accepted]
    series += [f for f in low["fixes"]
               if f[3] == "HF" or -BACKFILL_WINDOW_H <= _hours(t_hf, f[0]) < 0]
    series.sort(key=lambda f: f[0])

    lead = chain_lead_h(series, t_hf)
    low["bfLeadH"] = int(round(lead))
    if lead < BACKFILL_MIN_LEAD_H:
        return                                  # not covered: null, never the HF-only value
    stats = deepening_stats(series)
    if stats["deep24"] is None:
        return
    low["deep24Bf"] = stats["deep24"]
    low["bergBf"] = stats["berg"]
    low["bombBf"] = stats["bomb"]
    # Negative = the steepest 24-h window ended before hurricane-force onset.
    low["deepRelH"] = int(round(_hours(t_hf, stats["end"])))


def attach_backfill(lows, records, qc):
    """Attach recovered fixes to the derived lows, keyed on (basin, event id) -
    ids repeat across basins ("2006200718" is in both) and, once split, carry
    a/b suffixes."""
    index = {(l["basin"], l["id"]): l for l in lows}
    split_bases = {(l["basin"], l["id"][:-1]) for l in lows if l.get("split")}
    by_low = defaultdict(list)
    for rec in records:
        key = (rec["basin"], rec["id"])
        if key in index:
            by_low[key].append(rec)
        elif key in split_bases:
            qc.note(rec["basin"], rec["row"], rec["id"], rec["date"], "precursor-ambiguous-id",
                    "archive id was split into separate events (a/b/...) because of a time "
                    "gap; which one this row belongs to is not knowable from the id. Rejected")
            qc.bump("precursorsRefused")
            qc.bump("precRefused_ambiguous-id")
        else:
            qc.note(rec["basin"], rec["row"], rec["id"], rec["date"], "precursor-unknown-event",
                    "no archive event with this (basin, event_id); rejected")
            qc.bump("precursorsRefused")
            qc.bump("precRefused_unknown-event")
    for low in lows:
        accepted = screen_precursors(low, by_low.get((low["basin"], low["id"]), []), qc)
        backfill_low(low, accepted)
        qc.bump("precursorsAccepted", len(accepted))


def _ols(xs, ys):
    """Least-squares slope of ys on xs and its standard error, or (None, None)
    when there are fewer than three points or no spread in xs."""
    n = len(xs)
    if n < 3:
        return None, None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    sse = sum((y - my - slope * (x - mx)) ** 2 for x, y in zip(xs, ys))
    return slope, math.sqrt(sse / (n - 2) / sxx)


def _pct(usable, events):
    return round(100.0 * usable / events, 1) if events else None


def coverage_trend(coverage):
    """Is Bf coverage uniform across seasons? One series per basin and one
    pooled, over the seasons from RECORD_START: the share of HF events with a
    usable window, its spread, and the OLS slope on season (points per season)
    with its standard error. Returns ({key: stats}, tripped), where `tripped`
    lists the reasons the gate fired."""
    by_key = {b[0]: defaultdict(lambda: [0, 0]) for b in BASINS}
    by_key["all"] = defaultdict(lambda: [0, 0])
    for r in coverage:
        if r["season"] < RECORD_START:
            continue
        for k in (r["basin"], "all"):
            by_key[k][r["season"]][0] += r["events"]
            by_key[k][r["season"]][1] += r["usable"]
    stats, tripped = {}, []
    for key, seasons in by_key.items():
        pts = [(s, 100.0 * u / e) for s, (e, u) in sorted(seasons.items()) if e]
        if not pts:
            continue
        shares = [p[1] for p in pts]
        slope, se = _ols([p[0] for p in pts], shares)
        spread = max(shares) - min(shares)
        st = {"seasons": len(pts), "min": round(min(shares), 1), "max": round(max(shares), 1),
              "spread": round(spread, 1),
              "slope": round(slope, 2) if slope is not None else None,
              "se": round(se, 2) if se is not None else None}
        if spread > COVERAGE_SPREAD_PTS:
            tripped.append(f"{key}: seasonal share spans {spread:.1f} points "
                           f"({min(shares):.1f}% to {max(shares):.1f}%), more than "
                           f"{COVERAGE_SPREAD_PTS:g}")
        if slope is not None and (abs(slope) > COVERAGE_SLOPE_SE * se if se else slope != 0):
            tripped.append(f"{key}: share trends {slope:+.2f} points per season "
                           f"(standard error {se:.2f}), more than {COVERAGE_SLOPE_SE:g} "
                           f"standard errors from zero")
        stats[key] = st
    return stats, tripped


def coverage_selection(lows):
    """Median minimum pressure and first-HF-fix latitude of the events with a
    usable Bf window versus those without, from RECORD_START on. If recovery
    succeeds preferentially on deep or high-latitude storms the covered subset
    is not a random sample, and a Bf share quoted from it is not the archive's."""
    def summarize(group):
        return {"n": len(group),
                "medianMinP": _median([l["minP"] for l in group]),
                "medianLat": _median([next(f for f in l["fixes"] if f[3] == "HF")[1]
                                      for l in group])}
    out = {}
    pop = [l for l in lows if l["hfN"] and l["season"] >= RECORD_START]
    for key in [b[0] for b in BASINS] + ["all"]:
        sel = [l for l in pop if key == "all" or l["basin"] == key]
        out[key] = {"covered": summarize([l for l in sel if l["deep24Bf"] is not None]),
                    "uncovered": summarize([l for l in sel if l["deep24Bf"] is None])}
    return out


def backfill_summary(lows, qc, path, comments):
    """Coverage of the backfill by season and basin, for the QC report and the
    page. Events counted are those with an HF fix: the rest have no window.
    `usable` is an event with a Bf statistic emitted.

    Also the era-uniformity diagnostics (coverage_trend, coverage_selection)
    and the `coverageTrend` flag they set. The flag suppresses nothing."""
    cells = defaultdict(lambda: [0, 0, 0])
    for l in lows:
        if not l["hfN"]:
            continue
        c = cells[(l["basin"], l["season"])]
        c[0] += 1
        c[1] += 1 if l["preN"] else 0
        c[2] += 1 if l["deep24Bf"] is not None else 0
    coverage = [{"basin": b, "season": s, "events": c[0], "recovered": c[1], "usable": c[2],
                 "share": _pct(c[2], c[0])}
                for (b, s), c in sorted(cells.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
    for row in coverage:
        qc.bump("bfEvents", row["events"])
        qc.bump("bfRecovered", row["recovered"])
        qc.bump("bfUsable", row["usable"])
        if row["events"] >= COVERAGE_ALARM_MIN_EVENTS and row["usable"] == 0:
            qc.note(row["basin"], None, "(all lows)", None, "backfill-coverage",
                    f"season {season_label(row['season'])}: none of {row['events']} HF events "
                    f"has a usable Bf window ({row['recovered']} have any recovered fix); "
                    f"the Bf statistics are blank for this whole season")

    trend, tripped = coverage_trend(coverage)
    if tripped:
        qc.note("all", None, "(all lows)", None, "backfill-coverage-trend",
                "Bf coverage is NOT uniform across seasons, so the Bf statistics are not safe "
                "to compare across seasons (a trend in what can be measured would read as a "
                "trend in the weather): " + "; ".join(tripped))
        qc.bump("coverageTrend")

    synthetic = any("SYNTHETIC" in c.upper() for c in comments)
    if synthetic:
        qc.note("all", None, "(precursors.csv)", None, "precursor-synthetic",
                "the precursors file declares itself SYNTHETIC development data; every Bf "
                "figure in this build is fabricated and must not be published")
    return {"source": os.path.relpath(path, ROOT) if os.path.isabs(path) else path,
            "synthetic": synthetic, "windowH": BACKFILL_WINDOW_H,
            "minLeadH": BACKFILL_MIN_LEAD_H, "maxStepH": BACKFILL_MAX_STEP_H,
            "minConf": BACKFILL_MIN_CONF, "coverage": coverage,
            "trendFrom": RECORD_START, "trend": trend,
            "coverageTrend": bool(tripped), "coverageTrendWhy": tripped,
            "spreadPts": COVERAGE_SPREAD_PTS, "slopeSe": COVERAGE_SLOPE_SE,
            "selection": coverage_selection(lows)}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


# GIT_TIMEOUT_S bounds how long a hung/misbehaving `git` can stall a build -
# provenance is a nice-to-have, never worth blocking the site over.
GIT_TIMEOUT_S = 5


def _git_build_info(root: str) -> dict | None:
    """Best-effort git provenance: {"commit": short sha, "dirty": bool}.

    Returns None on anything but a clean success - git not installed, ROOT
    not inside a git repo (the normal case on the production server, which
    has no .git directory at all because the code is copied out of GitHub by
    hand), a timeout, or any other surprise. Never raises."""
    try:
        sha = subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
        )
        if sha.returncode != 0 or not sha.stdout.strip():
            return None
        status = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return {"commit": sha.stdout.strip(), "dirty": dirty}
    except Exception:
        return None


def _build_host() -> str | None:
    """Best-effort, non-sensitive hostname of the machine that ran the build
    (e.g. a GitHub Actions runner, a forecaster's workstation, the NOAA
    server). Never raises."""
    try:
        return platform.node() or None
    except Exception:
        return None


# A season's mean lead fixes per event at or above this counts as "the new
# practice is in use that season". One-off blips below it (the 2004-05 Pacific
# season logs 0.42 and then nothing for eight years) do not count.
PRACTICE_MIN_LEAD = 0.1

# The comparison eras. 2017 is the first season in which BOTH basins log lead
# fixes (the Pacific began in 2013, the Atlantic in 2017), so before/after it
# the whole archive is in one practice or the other, except for the Pacific's
# 2013-16 ramp. The page leads with this split because it is the one a reader
# can hold in their head.
PRACTICE_SPLIT = 2017


def _median(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2.0


def _mean(values):
    v = [x for x in values if x is not None]
    return sum(v) / len(v) if v else None


def _r2(x):
    return round(x, 2) if x is not None else None


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def _lead_trail(low):
    """Fixes logged before the first / after the last HF fix, or None when the
    event has no HF fix at all."""
    cats = [f[3] for f in low["fixes"]]
    if "HF" not in cats:
        return None
    first = cats.index("HF")
    last = len(cats) - 1 - cats[::-1].index("HF")
    return first, len(cats) - 1 - last


def _share(lows, bomb, berg):
    """Explosive count over all events, and how many events could be measured.

    The denominator is every event, not just the measurable ones: a hurricane
    force period shorter than ~18 h has no 24-h deepening to measure, and
    dropping those events would make the share a statement about the minority
    of long-lived HF lows. Counting them as not explosive makes it a lower
    bound, but one whose meaning does not depend on how many fixes an analyst
    logged around the HF period."""
    n = len(lows)
    explosive = sum(1 for l in lows if l.get(bomb))
    measurable = sum(1 for l in lows if l.get(berg) is not None)
    return {"explosive": explosive, "events": n, "measurable": measurable,
            "pct": round(100.0 * explosive / n, 1) if n else None}


def practice_summary(out, qc):
    """Quantify the change in recording practice and record it in the QC notes.

    Measured over every event from RECORD_START on, which is the population the
    page's KPIs describe. Lead and trail fixes are averaged over the events that
    have an HF fix to anchor them to (all but four); shares use every event."""
    rows = []
    for l in out:
        if l["season"] < RECORD_START:
            continue
        lt = _lead_trail(l) or (None, None)
        rows.append((l, lt[0], lt[1]))
    last_season = max(l["season"] for l, _, _ in rows)

    per_season = []
    for basin, _label, _rel, _rng in BASINS:
        for season in range(RECORD_START, last_season + 1):
            grp = [r for r in rows if r[0]["basin"] == basin and r[0]["season"] == season]
            if not grp:
                continue
            lows = [r[0] for r in grp]
            a, h = _share(lows, "bombAll", "bergAll"), _share(lows, "bomb", "berg")
            per_season.append({
                "basin": basin, "season": season, "events": len(grp),
                "lead": _r2(_mean([r[1] for r in grp])),
                "trail": _r2(_mean([r[2] for r in grp])),
                "bombAll": a["explosive"], "bombHf": h["explosive"],
                "measAll": a["measurable"], "measHf": h["measurable"]})

    basins = {}
    for basin, label, _rel, _rng in BASINS:
        seq = [r for r in per_season if r["basin"] == basin]
        # Onset: the first season from which every later season is in the new
        # practice (so an isolated early blip does not count as the onset).
        onset = None
        for i in range(len(seq)):
            if all((r["lead"] or 0) >= PRACTICE_MIN_LEAD for r in seq[i:]):
                onset = seq[i]["season"]
                break

        def side(sel):
            grp = [r for r in rows if r[0]["basin"] == basin and sel(r[0]["season"])]
            if not grp:
                return None
            return {"events": len(grp), "lead": _r2(_mean([r[1] for r in grp])),
                    "trail": _r2(_mean([r[2] for r in grp]))}
        basins[basin] = {
            "label": label, "onset": onset,
            "before": side(lambda y: onset is None or y < onset),
            "after": side(lambda y: onset is not None and y >= onset)}

    def era(lo, hi):
        grp = [r for r in rows if lo <= r[0]["season"] <= hi]
        lows = [r[0] for r in grp]
        a, h = _share(lows, "bombAll", "bergAll"), _share(lows, "bomb", "berg")

        def stat(key):
            vals = [l[key] for l in lows]
            mean = _mean(vals)
            return {"median": _median(vals),
                    "mean": round(mean, 2) if mean is not None else None}
        return {
            "from": lo, "to": hi, "events": len(lows),
            "lead": _r2(_mean([r[1] for r in grp])),
            "trail": _r2(_mean([r[2] for r in grp])),
            "explosiveAll": a, "explosiveHf": h,
            # Medians sit on a coarse 6-hourly grid (a median of 12 h can tick
            # to 6 h on a small shift in the mix), so the mean travels with it.
            "stats": {k: stat(k) for k in (
                "durH", "hfDurH", "distNm", "hfDistNm", "n", "hfN", "spdKt", "hfSpdKt",
                "minP")},
        }

    eras = {"before": era(RECORD_START, PRACTICE_SPLIT - 1),
            "after": era(PRACTICE_SPLIT, last_season)}

    # The share of events that are explosive, season by season and basin,
    # against the lead fixes per event of the same season-basin. If the share
    # were weather, recording practice would not predict it.
    xs, ys_all, ys_hf = [], [], []
    for r in per_season:
        if r["lead"] is None:
            continue
        xs.append(r["lead"])
        ys_all.append(r["bombAll"] / r["events"])
        ys_hf.append(r["bombHf"] / r["events"])
    corr = {"n": len(xs), "all": _corr(xs, ys_all), "hf": _corr(xs, ys_hf)}
    for k in ("all", "hf"):
        corr[k] = round(corr[k], 3) if corr[k] is not None else None

    summary = {
        "split": PRACTICE_SPLIT, "minLead": PRACTICE_MIN_LEAD,
        "from": RECORD_START, "to": last_season,
        "perSeason": per_season, "basins": basins, "eras": eras, "corr": corr}

    for basin, label, _rel, _rng in BASINS:
        b = basins[basin]
        if b["onset"] is None:
            continue
        qc.note(basin, None, "(all lows)", None, "practice-change",
                f"{label}: from the {season_label(b['onset'])} season, analysts log "
                f"developing-hurricane-force fixes before each event's first HF fix and "
                f"storm-force fixes after its last. Lead/trail fixes per event: "
                f"{b['before']['lead']:.2f}/{b['before']['trail']:.2f} before, "
                f"{b['after']['lead']:.2f}/{b['after']['trail']:.2f} from then on. "
                f"The storms did not change; the recorded track did. Deepening, "
                f"duration and distance over the recorded track are not comparable "
                f"across this boundary - use the HF-window figures (deep24, berg, bomb, "
                f"hfDurH, hfDistNm, hfSpdKt).")
    b4, af = eras["before"], eras["after"]
    qc.note("all", None, "(all lows)", None, "practice-change",
            f"Explosive share (>= 1 Bergeron, of all events with an HF fix): on the "
            f"recorded track {b4['explosiveAll']['pct']}% ({b4['from']}-{b4['to']}) -> "
            f"{af['explosiveAll']['pct']}% ({af['from']}-{af['to']}); on HF fixes only "
            f"{b4['explosiveHf']['pct']}% -> {af['explosiveHf']['pct']}%. Across the "
            f"{corr['n']} season-basins, lead fixes per event correlate with the "
            f"recorded-track share at r = {corr['all']:+.3f} and with the HF-only "
            f"share at r = {corr['hf']:+.3f}.")
    qc.bump("practiceChangeBasins", sum(1 for b in basins.values() if b["onset"] is not None))
    return summary


def build(data_source: str | None = None, precursors: str | None = BACKFILL_PATH):
    """Build the payload. `precursors` is the backfill CSV (relative to ROOT, or
    absolute); None, or a path that does not exist, builds without a backfill."""
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

    # The backfill is optional input. Absent, the eight backfill fields stay
    # unset (null on the wire) and not one other number moves.
    backfill = None
    precursors_path = os.path.join(ROOT, precursors) if precursors else None
    if precursors_path and os.path.exists(precursors_path):
        records, comments = read_precursors(precursors_path, qc)
        attach_backfill(out, records, qc)
        backfill = backfill_summary(out, qc, precursors_path, comments)

    seasons = sorted({l["season"] for l in out})
    for info in basin_info:
        info["lows"] = sum(1 for l in out if l["basin"] == info["key"])

    practice = practice_summary(out, qc)

    # Records go out array-encoded against LOW_FIELDS rather than as objects:
    # repeating 20-odd key names across ~1900 lows tripled the payload. The
    # page rebuilds objects from these on load.
    lows_encoded = [[low.get(f) for f in LOW_FIELDS] for low in out]

    git_info = _git_build_info(ROOT)
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Provenance for telling the GitHub Pages preview, a local dev build
        # and the production copy on the NOAA server apart. commit/dirty are
        # None on a checkout with no .git (production); dataSource is None
        # unless the caller (tools/publish.py) says how the CSVs arrived.
        "build": {
            "commit": git_info["commit"] if git_info else None,
            "dirty": git_info["dirty"] if git_info else None,
            "dataSource": data_source,
            "host": _build_host(),
        },
        "basins": basin_info,
        "categories": CATEGORIES,
        "eventClasses": EVENT_CLASSES,
        "recordStart": RECORD_START,
        "seasons": [{"start": s, "label": season_label(s)} for s in seasons],
        "lowFields": LOW_FIELDS,
        "fixFields": FIX_FIELDS,
        "lows": lows_encoded,
        # The recording-practice change, quantified. The page's Method note and
        # the Climatology boundary markers read this rather than recomputing it.
        "practice": practice,
        # Backfill provenance and coverage by season and basin; null when no
        # precursors file was read.
        "backfill": backfill,
        "qc": {"counts": dict(sorted(qc.counts.items())), "notes": qc.notes},
    }
    return payload


def backfill_report(bf) -> list:
    """The coverage tables: by season and basin, then the era-uniformity
    diagnostics, then covered versus uncovered storms."""
    keys = [b[0] for b in BASINS]
    lines = [f"Backfill coverage ({bf['source']})"]
    if bf["synthetic"]:
        lines.append("  *** SYNTHETIC DEVELOPMENT DATA - these figures are not real ***")
    if bf["coverageTrend"]:
        lines.append("  *** COVERAGE TREND: Bf statistics are NOT safe to compare across seasons ***")
    lines.append(f"  usable = gapless pressure chain, steps <= {bf['maxStepH']} h, reaching back "
                 f">= {bf['minLeadH']} h from the first HF fix (window {bf['windowH']} h, "
                 f"recovered fixes of confidence >= {bf['minConf']})")
    lines.append("  cells: events with an HF fix / with any recovered fix / with a usable window / share %")
    lines.append("  " + "season".ljust(10) + "".join(k.ljust(26) for k in keys))
    by = {(r["basin"], r["season"]): r for r in bf["coverage"]}
    totals = {k: [0, 0, 0] for k in keys}

    def cell(e, r, u):
        return f"{e:>3} {r:>4} {u:>4} {_pct(u, e) if e else 0:>6.1f}".ljust(26)
    for season in sorted({r["season"] for r in bf["coverage"]}):
        cells = []
        for k in keys:
            r = by.get((k, season))
            cells.append(cell(r["events"], r["recovered"], r["usable"]) if r else "-".ljust(26))
            if r:
                totals[k] = [totals[k][0] + r["events"], totals[k][1] + r["recovered"],
                             totals[k][2] + r["usable"]]
        lines.append("  " + season_label(season).ljust(10) + "".join(cells))
    lines.append("  " + "all".ljust(10) + "".join(cell(*totals[k]) for k in keys))
    lines.append("")

    lines.append(f"Coverage uniformity, seasons from {season_label(bf['trendFrom'])} "
                 f"(share of HF events with a usable window; gate: spread > "
                 f"{bf['spreadPts']:g} points or slope > {bf['slopeSe']:g} standard errors)")
    lines.append("  " + "series".ljust(8) + "seasons".rjust(8) + "min %".rjust(8) + "max %".rjust(8)
                 + "spread".rjust(8) + "slope/season".rjust(14) + "std err".rjust(9))
    for key, t in bf["trend"].items():
        slope = f"{t['slope']:+.2f}" if t["slope"] is not None else "-"
        se = f"{t['se']:.2f}" if t["se"] is not None else "-"
        lines.append("  " + key.ljust(8) + str(t["seasons"]).rjust(8) + f"{t['min']:.1f}".rjust(8)
                     + f"{t['max']:.1f}".rjust(8) + f"{t['spread']:.1f}".rjust(8)
                     + slope.rjust(14) + se.rjust(9))
    lines.append("  coverageTrend: " + ("TRUE - " + "; ".join(bf["coverageTrendWhy"])
                                       if bf["coverageTrend"] else "false"))
    lines.append("")

    lines.append(f"Covered vs uncovered storms, seasons from {season_label(bf['trendFrom'])} "
                 f"(is recovery selective? median minimum pressure hPa / latitude of first HF fix)")
    lines.append("  " + "series".ljust(8) + "group".ljust(11) + "events".rjust(7)
                 + "median minP".rjust(13) + "median lat".rjust(12))
    for key, groups in bf["selection"].items():
        for name in ("covered", "uncovered"):
            g = groups[name]
            minp = f"{g['medianMinP']:.1f}" if g["medianMinP"] is not None else "-"
            lat = f"{g['medianLat']:.1f}" if g["medianLat"] is not None else "-"
            lines.append("  " + key.ljust(8) + name.ljust(11) + str(g["n"]).rjust(7)
                         + minp.rjust(13) + lat.rjust(12))
    lines.append("")
    return lines


def qc_report(payload) -> str:
    lines = ["HF extratropical low archive - data quality report",
             f"generated {payload['generated']}", ""]
    for k, v in payload["qc"]["counts"].items():
        lines.append(f"  {k:24s} {v}")
    lines.append("")
    if payload.get("backfill"):
        lines += backfill_report(payload["backfill"])
    by_kind = defaultdict(list)
    for n in payload["qc"]["notes"]:
        by_kind[n["kind"]].append(n)
    # The recording-practice change reads as context for everything below it,
    # so it leads the by-kind listing instead of sorting alphabetically.
    for kind in sorted(by_kind, key=lambda k: (k != "practice-change", k)):
        lines.append(f"{kind} ({len(by_kind[kind])})")
        for n in by_kind[kind]:
            where = f'{n["basin"]} row {n["row"]}' if n["row"] else f'{n["basin"]}'
            when = f' date={n["date"]}' if n["date"] is not None else ""
            lines.append(f'  {where}  id={n["id"]}{when}: {n["detail"]}')
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build but write nothing")
    ap.add_argument("--data-source", default=None, metavar="SOURCE",
                     help="how the CSVs in data/hf_lows/ got there, recorded in the "
                          "payload's build.dataSource (e.g. 'fetched', 'local'); "
                          "tools/publish.py sets this itself. Defaults to unknown.")
    ap.add_argument("--no-backfill", action="store_true",
                    help=f"ignore {BACKFILL_PATH} even if it exists")
    args = ap.parse_args()

    payload = build(data_source=args.data_source,
                    precursors=None if args.no_backfill else BACKFILL_PATH)
    counts = payload["qc"]["counts"]
    print(f"lows {counts.get('lows', 0)}  fixes {counts.get('fixes', 0)}  "
          f"seasons {len(payload['seasons'])}  "
          f"dropped rows {counts.get('rowsDropped', 0)}  "
          f"notes {len(payload['qc']['notes'])}")

    if payload["backfill"]:
        bf = payload["backfill"]
        usable = sum(r["usable"] for r in bf["coverage"])
        events = sum(r["events"] for r in bf["coverage"])
        print(f"backfill {bf['source']}: {counts.get('precursorsAccepted', 0)} fixes used, "
              f"{counts.get('precursorsRefused', 0)} refused; "
              f"{usable}/{events} HF events have a usable Bf window"
              + ("  ** SYNTHETIC DATA **" if bf["synthetic"] else "")
              + ("  ** COVERAGE TREND: Bf not safe to compare across seasons **"
                 if bf["coverageTrend"] else ""))

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
