"""Scatterometer passes over the two OPC basins, gridded and scored against the marine wind page.

Each hour the workflow runs this against the previous state (the `scatterometer-data` branch) and the
newest marine wind data (the `marine-wind-live` branch), and writes the new state:

    OUT/data/index.json            the pass list with scores (the page reads this); `rss` = days of RSS ASCAT in (days, through); `nesdis.newest` = end of the newest NESDIS pass
    OUT/data/pass/<id>-<basin>.bin one file per pass and basin (format below)
    OUT/data/mosaic/<basin>-<YYYYMMDDHH>.bin
                                   one file per 00/12Z time and basin: the passes of the 12 h around it stitched into one
                                   map, scored cell by cell, with the Best Wind and warning areas of the whole basin box
                                   at that time (format below)
    OUT/cache/<YYYYMMDDHH>/{natl,npac}.npz + meta.json
                                   Best Wind and warning areas of every marine wind cycle seen, steps 6..54,
                                   cut to the OPC boxes (uint8 as served), kept 4 days: the passes are scored
                                   against the run the desk had at the time, and the runs 24 and 48 h earlier
    OUT/cache/mask.npz             water mask (GFS land and ice at 0.25 deg), refreshed daily
    OUT/cache/seen.json            passes already handled (key -> id, files), so the hourly run downloads
                                   only what is new
    OUT/cache/rss.json             RSS ASCAT days (YYYYMMDD -> done, satellites posted, last try), see below
    OUT/cache/nesdis.json          NESDIS Metop-B days (YYYYMMDD -> fetched, tried, n: cells per pseudo-pass key), see below

Sources. NOAA STAR (nwp/nwp/star.py): OSCAT-3 and Metop-B/C coastal ultra-high-resolution ASCAT, posted 3-4 h after the
pass; the ASCAT is a coastal product, about 9-12% of a basin per 12 h. Remote Sensing Systems (nwp/nwp/rss_ascat.py): daily
0.25 degree Metop-B and Metop-C maps with full swaths over the open ocean, posted about 2 days after the day ends (lately
about 5). NESDIS (nwp/nwp/nesdis_ascat.py): Metop-B ASCAT, full swaths, from NOAA AOML's daily 0.25 degree maps through NOAA
ERDDAP, about 1 h after the pass (Metop-C is not served). Winds are the 10 m wind as served, in knots (RSS's is
equivalent-neutral, used as STAR's are, no conversion; NESDIS's is the 10 m neutral wind, m/s x 1.94384).

RSS ASCAT. Each UTC day in the 7-day window that is not done (cache/rss.json) is asked for, both satellites, at most once
every 55 min, until it is 10 days old. When both are posted, or one is and the day is 7 or more days old, the day is used
and marked done; otherwise nothing is kept and it is asked again. The cells (15-70N) inside an OPC box on water become
pseudo-passes, one per (satellite, node, basin, nearest synoptic hour 00/06/12/18Z of the cell time; node: AS ascending, DS
descending): prefix rss_metopb_AS (_DS, rss_metopc_...), satellite label "RSS Metop-B" / "RSS Metop-C", id
<YYYYMMDDTHHMM of the earliest cell>-<prefix>, start and end the earliest and latest cell time, middle the mean cell time.
(A pseudo-pass holds one basin, so its times are those of its basin; STAR passes can hold both.) A basin with under 200
cells in a group is dropped. RSS cell centres sit at x.125 degrees, on the corner of four page cells: each is given to the
page cell at its north-west corner (lat + 0.125, lon - 0.125, rss_points), one RSS cell to one page cell and none twice, a
shift of half an RSS cell. The rain bit is the cell's flag. From there the pseudo-passes go through the same pipeline as
STAR passes (bins, leads, scores, Passes tab, mosaics) and count as ASCAT.

NESDIS Metop-B ASCAT. The dataset has one growing map per UTC day (cells appear as passes are processed, about an hour
after the flight). Each run asks for today, yesterday, and any other day of the 7-day window that is not final and that RSS
has not covered with Metop-B (cache/rss.json: done, with b): at most 3 requests a day (the Atlantic box one, the Pacific box
two, split at the date line), so 6 when nothing is old; a day older than yesterday is asked for at most once an hour. A day is
final when it is 2 days old and was fetched after it ended; a day the server does not have yet gives nothing and is asked for
again. The cells become pseudo-passes by the same code as RSS (split_passes): one per (node, synoptic hour, basin), prefix
nesdis_metopb_AS (_DS), satellite label "Metop-B (NESDIS)". A pass grows as the day fills, so its id does not come from the
earliest cell: it is <synoptic hour YYYYMMDDTHH00>-<prefix> (<day>T2400 for the cells after 21Z, which come in that day's
file but are the next 00Z), which stays put (a basin's pseudo-pass is the key
(id, basin)). A run keeps cache/nesdis.json's cell count per pseudo-pass key and, when a pass has more cells than last time,
replaces it where it stands: same id and file, scored again against the forecast at its new middle, and the mosaics holding it
are built again; a pass that did not grow is left alone. When RSS posts the day its Metop-B cells replace the NESDIS ones in
every mosaic (the passes stay in the list). NESDIS's own node numbers are the other way round from RSS's (RSS node 0 is the
descending pass; its AS/DS prefixes follow the reader's node, so rss_metop*_AS holds descending cells).

Passes. UHR ASCAT comes as regional chunks of one orbit: files of the same prefix starting <= 20 min apart
are one pass. An OSCAT-3 file is one half-orbit and is one pass. OSCAT-3 file names carry the time the file
was made, not the time of the pass, when STAR catches up (a run of files stamped within minutes of each
other, orbits apart): those get a start time from their orbit number (a line through the files with a good
stamp). A pass's time is a bracket [start, end]: the first file's start to the last file's start plus a
nominal length (UHR chunk 10 min, OSCAT-3 half-orbit 55 min).

Each pass is put on the global 0.25 degree grid (iy = round((90 - lat) * 4), ix = round((lon + 180) * 4) % 1440):
per cell the mean speed of the unflagged points (all flagged: the mean of all, flag 1), direction from the
vector mean (degrees the wind blows from). Only water cells (GFS land < 0.5 and ice < 0.15) inside an OPC box
are kept (natl 18-67N 95W-10E, npac 18-67N 135E-115W); a basin with under 200 cells is dropped.

Forecast leads, each with Best Wind (kt) and the warning bits (1 gale, 2 storm, 4 hurricane force):
    latest  the newest cached run built before the pass's middle (the run the desk had), step the multiple
            of 6 h nearest to the middle, 6..54, else none
    f24     the run 24 h before the synoptic hour (00/06/12/18) nearest the middle, step 24
    f48     the same, 48 h before, step 48
When the job's own cache lacks the cycle for f24 or f48 (the cache starts empty and keeps 4 days), the step is
taken from the marine wind job's forecast record artifact `forecast-record-YYYYMMDDHH-fLLL` (marine_wind/pipeline/
record.py, kept 14 days, needs GITHUB_TOKEN; about 90 MB each) and stored in the cache as a partial cycle holding
that step only. Passes already in the index whose f24 or f48 was null are scored again when it turns up (their
observed winds then come from the stored whole-knot values). A record not found is remembered in
cache/record_misses.json and asked again after a day; one without `best` (before about 6 Nov 2026) never again.
At most --record-max downloads a run, newest passes first. Full cycles older than 4 days shrink to steps 24 and 48
and go at 10 days.

Scores per lead use unflagged cells only: observed and grid area at 34/48/64 kt, highest wind, and the
warning lines' catch of the observed cells (34 in gale|storm|HF, 48 in storm|HF, 64 in HF) beside the cells
each line covers. Counts are cells of 0.25 degree.

Pass .bin (gzip, little endian): uint32 n; uint32 idx[n] (global flat index iy * 1440 + ix, ascending);
uint8 obs[n] (kt, rounded, at most 254); uint8 dir[n] (degrees / 2, rounded, 0-179); uint8 flag[n]; then for
latest, f24 and f48 in turn uint8 grid[n] (kt rounded, 255 = no forecast) and uint8 warn[n] (bits, 255 = none).

Mosaics (index `format` 2). For each time V = 00Z and 12Z of the last 7 days (14 per basin) and each basin, every pass
whose middle is in [V - 6 h, V + 6 h) (the end is excluded, so a pass belongs to one mosaic) is stitched into one map; where
swaths overlap RSS ASCAT wins over NESDIS Metop-B, which wins over STAR ASCAT, which wins over OSCAT-3, then the pass whose
middle is nearest V, a tie goes to the newer. A mosaic that gains RSS or NESDIS cells is built again. A mosaic whose
window closed less than 4 h ago is `open` (STAR posts 3-4 h after a pass): it is shown but left out of the summary.

Each observed cell is scored against the forecast its own pass was given (pick_leads at the pass's middle: the forecast step
nearest to that pass, so valid at V - 6, V or V + 6), not against V. The mosaic keeps, per observed cell, the grid and
warning bytes of the three leads. A lead counts for the mosaic (`fc[lead]` not null) when the passes that have it hold at
least 80% of the observed cells; the cells of a pass that lacks it are left out of that lead's score, and `unscored` (and
`unscored_ascat`) says how many. `score` is the pass score (see above) on the unflagged, scored cells of the whole mosaic,
`score_ascat` the same on the ASCAT cells only (`n` is the number of cells scored). `peak` has, per lead, the highest
unflagged observed cell (`all` and `ascat`): idx (global flat index), obs, grid and warn at that cell. `sats` counts
all observed cells by satellite family (`ASCAT` includes `RSS` and `NESDIS`, the cells of those alone; STAR's coastal ASCAT is the rest), `water` the water cells of the basin box (coverage = n / water). The map lines
are those of V: `vsel` is the run and step picked for V, `fc[lead]` repeats it (null cycle when V has none) and
`grid_area_box` counts the water cells of the whole box at or above 34/48/64 kt per lead. A mosaic is built again when its
pass set changes, a pass in it is redone or gains a lead, or V's own forecast changed.

Summary (index `summary`, basin -> lead -> "ascat" | "all"): the sums over the closed mosaics of the week of the
scores above: `obs`, `grid`, `catch`, `line` at 34/48/64 (observed cells at the threshold, grid cells at it on the same
cells, observed cells inside the gale|storm|HF lines, scored cells inside them: catch / line is the share of line cells that
were seen and reached the threshold), `nmos_obs` and `nmos_line` (mosaics with any), `enough` and `enough_line` (at least
50 cells and 3 mosaics: otherwise no ratio), `mosaics`, `n`, coverage of the basin water per mosaic (`times`, `with_rss` and `with_nesdis` (mosaics with any
RSS or NESDIS cell), `cov_mean`, `cov_min`, `cov_max`) and `worst`, the 8 highest mosaic peaks of the week (valid, obs, grid at the peak cell, grid_max over
the seen cells, warn bits, idx).

Mosaic .bin (gzip, little endian): uint32 n; uint32 idx[n] (global flat index, ascending); uint8 obs[n], dir[n],
flag[n] (as in a pass file); uint8 pass[n] (index into the entry's `passes` list in index.json); then for latest, f24 and
f48 in turn uint8 grid[n] and warn[n] of the cell's own pass (255 = pass has no such forecast); then for each lead whose
`fc` entry has a cycle (latest, f24, f48 in that order) uint8 grid[ny*nx] (whole kt, 255 = none: land and water the OPC does
not forecast) and uint8 warn[ny*nx] (bits as above, 255 = none) over the basin box (`box` in the index entry: iy0, ny, ix0,
nx; rows north first, columns west first, see box_cols) at V.

    python3 build.py --live DIR --state DIR --out DIR [--days 1] [--workers 5]
        --live   a checkout holding latest/global/ of marine-wind-live (manifest.json, fSSS/best.gz, warn.gz)
        --state  the previous state (the scatterometer-data branch checked out; may be empty or missing)"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "nwp"))
from nwp import nesdis_ascat, rss_ascat, star  # noqa: E402

NX, NY = 1440, 721
BOXES = {"natl": dict(north=67.0, south=18.0, west=-95.0, east=10.0),
         "npac": dict(north=67.0, south=18.0, west=135.0, east=245.0)}
STEPS = tuple(range(6, 55, 6))
LEADS = ("latest", "f24", "f48")
KEEP_DAYS = 7
CACHE_DAYS = 4                 # full cycles (steps 6..54) are kept this long
PARTIAL_DAYS = 10              # then steps 24 and 48 only, this long (the record artifacts last 14 days)
RECORD_MAX = 40                # record downloads per run
RECORD_RETRY = dt.timedelta(days=1)
RECORD_LIFE = dt.timedelta(days=14)
MIN_CELLS = 200
GROUP_MIN = 20                 # UHR chunks of one pass start at most this far apart
NOMINAL_MIN = {"uhr": 10, "oscat": 55}   # length of the last file of a pass (minutes)
SAT = {"oscat3": "OSCAT-3", "UHR_METOP-B": "Metop-B", "UHR_METOP-C": "Metop-C", "rss_metopb": "RSS Metop-B",
       "rss_metopc": "RSS Metop-C", "nesdis_metopb": "Metop-B (NESDIS)"}
RSS_SATS = ("b", "c")
RSS_RETRY = dt.timedelta(minutes=55)    # an RSS day not posted yet is asked for again after this
RSS_LATE = dt.timedelta(days=7)         # a day this old is used with only one satellite posted
RSS_GIVE_UP = dt.timedelta(days=10)     # and not asked for any more after this
NESDIS_RETRY = dt.timedelta(minutes=55)  # a NESDIS day older than yesterday that failed is asked for again after this
NESDIS_FINAL = dt.timedelta(days=2)     # a NESDIS day is done when it is this old and was fetched after it ended
ISO = "%Y-%m-%dT%H:%MZ"
THRESH = (34, 48, 64)
LINES = (7, 6, 4)              # warn bits that count for 34, 48, 64 kt
MIN_LEAD_SHARE = (4, 5)        # a lead counts for a mosaic when passes with it hold at least 4/5 of the observed cells
MIN_SEEN = 50                  # summary: fewer observed cells than this at a threshold, no ratio
MIN_MOSAICS = 3                # ... and fewer mosaics contributing than this
WORST_N = 8                    # summary: peaks listed
FORMAT = 2


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# ---------- the grid and the boxes ----------

def box_cols(key):
    """(iy0, ny, ix0, nx) of an OPC box on the global grid; columns run west to east from ix0, wrapping."""
    b = BOXES[key]
    iy0 = int(round((90 - b["north"]) * 4))
    ny = int(round((b["north"] - b["south"]) * 4)) + 1
    ix0 = int(round((b["west"] + 180) * 4)) % NX
    nx = int(round((b["east"] - b["west"]) * 4)) + 1
    return iy0, ny, ix0, nx


# inland water the GFS mask keeps but OPC does not forecast for: (south, north, west, east), lon -180..180
INLAND = [(51.0, 66.0, -96.0, -77.0),    # Hudson and James Bay
          (41.0, 49.5, -93.0, -75.5)]    # Great Lakes


def box_mask(key):
    iy0, ny, ix0, nx = box_cols(key)
    m = np.zeros((NY, NX), bool)
    m[iy0:iy0 + ny, (ix0 + np.arange(nx)) % NX] = True
    lat = 90.0 - 0.25 * np.arange(NY)
    lon = -180.0 + 0.25 * np.arange(NX)
    for s, n, w, e in INLAND:
        m[np.ix_((lat >= s) & (lat <= n), (lon >= w) & (lon <= e))] = False
    return m


def box_pos(key, idx):
    """Flat global indices -> (row, col) in the box arrays."""
    iy0, _, ix0, _ = box_cols(key)
    return idx // NX - iy0, (idx % NX - ix0) % NX


def grid_points(p, lat_range=(15.0, 70.0)):
    """Points dict (nwp.star) -> per 0.25 degree cell (idx, spd kt, dir deg from, flag), idx ascending."""
    k = (p["lat"] >= lat_range[0]) & (p["lat"] <= lat_range[1])
    if not k.any():
        return (np.zeros(0, np.int64), np.zeros(0, np.float32), np.zeros(0, np.float32), np.zeros(0, np.uint8))
    iy = np.round((90 - p["lat"][k]) * 4).astype(np.int64)
    ix = np.round((p["lon"][k].astype(np.float64) + 180) * 4).astype(np.int64) % NX
    flat = iy * NX + ix
    cells, inv = np.unique(flat, return_inverse=True)
    n = cells.size
    good = (p["q"][k] != 1)
    spd, u, v = p["spd"][k].astype(np.float64), p["u"][k].astype(np.float64), p["v"][k].astype(np.float64)

    wg = good.astype(np.float64)
    ng = np.bincount(inv, wg, n)
    na = np.bincount(inv, None, n).astype(np.float64)
    use_good = ng > 0
    # weights per point: the unflagged ones where the cell has any, else all
    w = np.where(use_good[inv], wg, 1.0)
    den = np.where(use_good, ng, na)
    ms = np.bincount(inv, w * spd, n) / den
    mu = np.bincount(inv, w * u, n) / den
    mv = np.bincount(inv, w * v, n) / den
    direction = np.degrees(np.arctan2(-mu, -mv)) % 360
    return cells, ms.astype(np.float32), direction.astype(np.float32), (~use_good).astype(np.uint8)


# ---------- the marine wind cache ----------

def decode_field(blob, scale):
    """OUT/fSSS/NAME.gz of the marine wind data: gzip of uint8 rows [721 x 1440] as differences from the cell to
    the west -> the raw uint8 bytes (cumulative sum along each row, mod 256) and value = byte / scale."""
    a = np.frombuffer(gzip.decompress(blob), np.uint8).reshape(NY, NX)
    return np.cumsum(a, axis=1, dtype=np.uint8)


def crop_box(a, key):
    iy0, ny, ix0, nx = box_cols(key)
    return np.ascontiguousarray(a[iy0:iy0 + ny][:, (ix0 + np.arange(nx)) % NX])


def cyc_name(manifest_cycle):
    return dt.datetime.strptime(manifest_cycle, ISO).strftime("%Y%m%d%H")


def cache_live(live, cache, now):
    """Save the live cycle to cache/<YYYYMMDDHH>/ unless it is there; prune. -> (cycle name, new?)"""
    with open(os.path.join(live, "latest", "global", "manifest.json")) as f:
        man = json.load(f)
    scale = {f["name"]: f["scale"] for f in man["fields"]}
    cyc = cyc_name(man["cycle"])
    d = os.path.join(cache, cyc)
    new = not os.path.exists(os.path.join(d, "meta.json"))
    if new:
        os.makedirs(d, exist_ok=True)
        arrs = {k: {} for k in BOXES}
        for step in STEPS:
            for name in ("best", "warn"):
                with open(os.path.join(live, "latest", "global", "f%03d" % step, name + ".gz"), "rb") as f:
                    a = decode_field(f.read(), scale[name])
                for k in BOXES:
                    arrs[k]["%s%03d" % (name, step)] = crop_box(a, k)
        for k in BOXES:
            np.savez_compressed(os.path.join(d, k + ".npz"), **arrs[k])
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump(dict(cycle=cyc, built=man["built"], best_scale=scale["best"], warn_scale=scale["warn"]), f)
    prune(cache, now)
    return cyc, new


def prune(cache, now):
    """Full cycles older than CACHE_DAYS shrink to steps 24 and 48 (what the f24 and f48 leads use); partial
    cycles go after PARTIAL_DAYS."""
    for name in os.listdir(cache):
        p = os.path.join(cache, name)
        if not (os.path.isdir(p) and re.fullmatch(r"\d{10}", name)):
            continue
        age = now - dt.datetime.strptime(name, "%Y%m%d%H")
        meta = read_json(os.path.join(p, "meta.json"), None)
        if age > dt.timedelta(days=PARTIAL_DAYS) or meta is None:
            shutil.rmtree(p)
        elif age > dt.timedelta(days=CACHE_DAYS) and not meta.get("steps"):
            for k in BOXES:
                with np.load(os.path.join(p, k + ".npz")) as z:
                    keep = {n: z[n] for n in z.files if n[-3:] in ("024", "048")}
                np.savez_compressed(os.path.join(p, k + ".npz"), **keep)
            meta["steps"] = [24, 48]
            with open(os.path.join(p, "meta.json"), "w") as f:
                json.dump(meta, f)


def load_cycles(cache):
    """cache/ -> {cycle name: dict(built datetime, best_scale, dir)}"""
    out = {}
    for name in sorted(os.listdir(cache)) if os.path.isdir(cache) else []:
        m = os.path.join(cache, name, "meta.json")
        if re.fullmatch(r"\d{10}", name) and os.path.exists(m):
            with open(m) as f:
                j = json.load(f)
            out[name] = dict(built=dt.datetime.strptime(j["built"], ISO), best_scale=j["best_scale"], dir=os.path.join(cache, name),
                             steps=j.get("steps") or list(STEPS), partial=bool(j.get("steps")))
    return out


class Forecasts:
    """Lazy reader of the cached cycles."""

    def __init__(self, cycles):
        self.cycles, self._npz = cycles, {}

    def field(self, cyc, basin, name, step):
        k = (cyc, basin)
        if k not in self._npz:
            with np.load(os.path.join(self.cycles[cyc]["dir"], basin + ".npz")) as z:
                self._npz[k] = {n: z[n] for n in z.files}
        return self._npz[k]["%s%03d" % (name, step)]


# ---------- forecast records (f24 and f48 for cycles the cache does not hold) ----------

def _record_module():
    spec = importlib.util.spec_from_file_location("mw_record", os.path.join(HERE, "..", "pipeline", "record.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fetch_record(cycle, step):
    """Best Wind and warning areas of one lead from the forecast record artifact (pipeline/record.py) ->
    (best uint8 as kt x 2, warn uint8), each [721, 1440]; "none" when there is no live artifact, "nobest" when the
    record has no `best` field (before about 6 Nov 2026). Raises on network errors."""
    rec = _record_module()
    tmp = tempfile.mkdtemp(prefix="record-")
    try:
        if not rec._artifact(tmp, cycle, step):
            return "none"
        d = os.path.join(tmp, cycle)
        os.makedirs(d)
        for ext in (".json", ".npz"):
            os.replace(os.path.join(tmp, "%s-%s%s" % (cycle, rec._name(step), ext)), os.path.join(d, rec._name(step) + ext))
        vals, _, _ = rec.load(d, cycle, step)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if "best" not in vals or "warn" not in vals or np.shape(vals["best"]) != (NY, NX) or np.shape(vals["warn"]) != (NY, NX):
        return "nobest"
    best = np.clip(np.round(np.nan_to_num(np.asarray(vals["best"], np.float32)) * 2), 0, 255).astype(np.uint8)
    return best, np.asarray(vals["warn"]).astype(np.uint8)


def store_step(cache, cycle, step, best, warn):
    """Add one step to cache/<cycle>/ (a partial cycle with that step only when the cycle is not cached)."""
    d = os.path.join(cache, cycle)
    meta = read_json(os.path.join(d, "meta.json"), None)
    if meta is not None and "steps" not in meta:
        return   # a full cycle already has every step
    if meta is None:
        os.makedirs(d, exist_ok=True)
        meta = dict(cycle=cycle, built=dt.datetime.strptime(cycle, "%Y%m%d%H").strftime(ISO), best_scale=2, warn_scale=1, steps=[])
    for k in BOXES:
        p = os.path.join(d, k + ".npz")
        arrs = {}
        if os.path.exists(p):
            with np.load(p) as z:
                arrs = {n: z[n] for n in z.files}
        arrs["best%03d" % step], arrs["warn%03d" % step] = crop_box(best, k), crop_box(warn, k)
        np.savez_compressed(p, **arrs)
    meta["steps"] = sorted(set(meta["steps"]) | {step})
    with open(os.path.join(d, "meta.json"), "w") as f:   # meta last: its presence marks a usable cycle
        json.dump(meta, f)


def ensure_records(cache, cycles, wants, now, budget, fetch=None):
    """wants [(cycle, step)], newest first: fetch the ones neither cached nor recently missed, at most `budget`
    downloads -> number stored. Misses are kept in cache/record_misses.json."""
    fetch = fetch or fetch_record
    mp = os.path.join(cache, "record_misses.json")
    misses = read_json(mp, {})
    stored = tries = 0
    for c, step in dict.fromkeys(wants):
        key = "%s-f%03d" % (c, step)
        t = dt.datetime.strptime(c, "%Y%m%d%H")
        if step in cycles.get(c, {}).get("steps", ()) or now - t > RECORD_LIFE:
            continue
        m = misses.get(key)
        if m and (m["why"] == "nobest" or now - dt.datetime.strptime(m["t"], ISO) < RECORD_RETRY):
            continue
        if tries >= budget:
            print("record budget of %d downloads used; the rest next run" % budget, flush=True)
            break
        tries += 1
        try:
            r = fetch(c, step)
        except Exception as e:   # network or a bad zip: try again next run
            print("record %s failed (%s: %s)" % (key, type(e).__name__, e), file=sys.stderr, flush=True)
            continue
        if isinstance(r, str):
            misses[key] = dict(t=now.strftime(ISO), why=r)
            print("record %s: %s" % (key, r), flush=True)
        else:
            store_step(cache, c, step, *r)
            misses.pop(key, None)
            stored += 1
            print("record %s stored" % key, flush=True)
    cut = (now - RECORD_LIFE - dt.timedelta(days=2)).strftime(ISO)
    misses = {k: v for k, v in misses.items() if v["t"] >= cut}
    with open(mp, "w") as f:
        json.dump(misses, f)
    return stored


def rescore(entries, cycles, fc, pass_dir, state_dir, cut):
    """Fill f24 and f48 of entries that have them null where the forecast is cached now: rewrite the pass file
    (grid and warn bytes of that lead) and the entry. -> number of entries changed."""
    n = 0
    for e in entries:
        if e["start"] < cut or (e["fc"]["f24"] and e["fc"]["f48"]):
            continue
        sel = pick_leads(cycles, dt.datetime.strptime(e["mid"], ISO))
        fill = [l for l in ("f24", "f48") if e["fc"][l] is None and sel[l] is not None]
        if not fill:
            continue
        name = os.path.basename(e["file"])
        src = next((p for p in (os.path.join(pass_dir, name), os.path.join(state_dir, "data", e["file"])) if os.path.exists(p)), None)
        if src is None:
            continue
        with open(src, "rb") as f:
            u = unpack_pass(f.read())
        leads = {l: (v[0].copy(), v[1].copy()) if (v[0] != 255).any() else None for l, v in u["leads"].items()}
        for l in fill:
            grid, warn = lead_fields(fc, sel[l], e["basin"], u["idx"].astype(np.int64))
            leads[l] = (np.clip(np.round(grid), 0, 254).astype(np.uint8), warn)
            e["fc"][l] = lead_info(sel[l])
            e["score"][l] = score(u["obs"].astype(np.float32), u["flag"], grid, warn)
        with open(os.path.join(pass_dir, name), "wb") as f:
            f.write(pack_raw(u["idx"], u["obs"], u["dir"], u["flag"], leads))
        n += 1
    return n


def pick_leads(cycles, mid):
    """cycles {name: dict(built=datetime)}, mid datetime -> {lead: (cycle name, step) or None} (see module doc)."""
    out = dict.fromkeys(LEADS)
    ready = [c for c, v in cycles.items() if v["built"] <= mid and not v.get("partial")]
    if ready:
        c = max(ready)
        h = (mid - dt.datetime.strptime(c, "%Y%m%d%H")).total_seconds() / 3600
        step = int(np.floor(h / 6 + 0.5)) * 6
        if STEPS[0] <= step <= STEPS[-1]:
            out["latest"] = (c, step)
    for lead, (c, h) in record_cycles(mid).items():
        if c in cycles and h in cycles[c].get("steps", STEPS):
            out[lead] = (c, h)
    return out


def record_cycles(mid):
    """{lead: (cycle name, step)} that f24 and f48 use for a pass middle: the run 24 and 48 h before the nearest
    synoptic hour."""
    v = _nearest_synoptic(mid)
    return {lead: ((v - dt.timedelta(hours=h)).strftime("%Y%m%d%H"), h) for lead, h in (("f24", 24), ("f48", 48))}


def _nearest_synoptic(t):
    base = t.replace(hour=0, minute=0, second=0, microsecond=0)
    h = (t - base).total_seconds() / 3600
    return base + dt.timedelta(hours=6 * int(np.floor(h / 6 + 0.5)))


def lead_info(sel):
    if sel is None:
        return None
    c, step = sel
    valid = dt.datetime.strptime(c, "%Y%m%d%H") + dt.timedelta(hours=step)
    return dict(cycle=c, step=step, valid=valid.strftime(ISO))


def lead_fields(fc, sel, basin, idx):
    """-> (grid kt float32 [n], warn uint8 [n]) for the cells idx, or None when the lead is missing."""
    if sel is None:
        return None
    c, step = sel
    r, col = box_pos(basin, idx)
    best = fc.field(c, basin, "best", step)[r, col].astype(np.float32) / fc.cycles[c]["best_scale"]
    return best, fc.field(c, basin, "warn", step)[r, col]


def score(obs, flag, grid, warn):
    """Scores of one lead on the unflagged cells (see module doc)."""
    k = flag == 0
    o, g, w = obs[k], grid[k], warn[k]
    if not o.size:
        z = [0, 0, 0]
        return dict(n=0, obs=z, grid=list(z), obs_max=0.0, grid_max=0.0, catch=list(z), line=list(z))
    return dict(n=int(o.size), obs=[int((o >= t).sum()) for t in THRESH], grid=[int((g >= t).sum()) for t in THRESH],
                obs_max=round(float(o.max()), 1), grid_max=round(float(g.max()), 1),
                catch=[int(((o >= t) & ((w & b) > 0)).sum()) for t, b in zip(THRESH, LINES)],
                line=[int(((w & b) > 0).sum()) for b in LINES])


# ---------- water mask ----------

def load_mask(cache, now):
    """cache/mask.npz (water, made), refreshed when older than a day from the newest GFS cycle that has it."""
    p = os.path.join(cache, "mask.npz")
    old = None
    if os.path.exists(p):
        with np.load(p) as z:
            old = dict(water=z["water"], made=dt.datetime.strptime(str(z["made"]), ISO))
        if now - old["made"] < dt.timedelta(days=1):
            return old["water"]
    import nwp
    t = now.replace(minute=0, second=0, microsecond=0)
    t = t.replace(hour=t.hour // 6 * 6)
    for k in range(9):
        c = t - dt.timedelta(hours=6 * k)
        f = nwp.ncep(nwp.sources.gfs(c.strftime("%Y%m%d"), c.strftime("%H"), 0), {"LAND:surface": "land", "ICEC:surface": "ice"})
        if f is not None:
            land, ice = (np.roll(np.nan_to_num(f[n], nan=0.0), NX // 2, axis=1) for n in ("land", "ice"))   # 0..360 -> -180..179.75
            water = (land < 0.5) & (ice < 0.15)
            os.makedirs(cache, exist_ok=True)
            np.savez_compressed(p, water=water, made=np.str_(now.strftime(ISO)))
            return water
    if old is not None:
        print("warning: no GFS cycle with LAND/ICEC; keeping the old mask", file=sys.stderr)
        return old["water"]
    raise SystemExit("no GFS land/ice mask available")


# ---------- passes ----------

def _orbit(url):
    m = re.search(r"oscat3_\d{7}_(\d+)_\d+_", url)
    return int(m.group(1)) if m else None


def fix_oscat_times(files):
    """files [(prefix, url, start)] -> same with OSCAT-3 starts replaced by an estimate from the orbit number where
    the stamp is a catch-up time: two or more files of the prefix stamped within 3 minutes of each other (they are
    different orbits), or a stamp more than 8 minutes off the line through the others (orbit number against time).
    Files with no estimate possible (under 4 good stamps) are dropped."""
    out = [f for f in files if not f[0].startswith("oscat3")]
    for prefix in sorted({f[0] for f in files if f[0].startswith("oscat3")}):
        fs = sorted((f for f in files if f[0] == prefix), key=lambda f: f[2])
        t = np.array([(f[2] - dt.datetime(2000, 1, 1)).total_seconds() / 60 for f in fs])
        n = np.array([_orbit(f[1]) for f in fs], float)
        good = np.array([((np.abs(t - t[i]) <= 3) & (n != n[i])).sum() == 0 for i in range(len(fs))])
        for _ in range(2):
            if good.sum() < 4:
                break
            # local fit: the 12 good orbits nearest in number
            res = np.full(len(fs), np.inf)
            for i in range(len(fs)):
                j = np.nonzero(good & (np.arange(len(fs)) != i))[0]
                j = j[np.argsort(np.abs(n[j] - n[i]))[:12]]
                if len(j) >= 3:
                    res[i] = t[i] - np.polyval(np.polyfit(n[j], t[j], 1), n[i])
            good &= np.abs(res) <= 8
        for i, f in enumerate(fs):
            if good[i]:
                out.append(f)
            elif good.sum() >= 4:
                j = np.nonzero(good)[0]
                j = j[np.argsort(np.abs(n[j] - n[i]))[:12]]
                est = float(np.polyval(np.polyfit(n[j], t[j], 1), n[i]))
                out.append((f[0], f[1], dt.datetime(2000, 1, 1) + dt.timedelta(minutes=round(est))))
    return sorted(out, key=lambda f: (f[0], f[2]))


def group_passes(files):
    """files [(prefix, url, start)] -> passes [dict(key, id, prefix, start, end, files [(url, start)])], newest first."""
    out = []
    for prefix in sorted({f[0] for f in files}):
        fs = sorted((f for f in files if f[0] == prefix), key=lambda f: f[2])
        oscat = prefix.startswith("oscat3")
        groups = [[f] for f in fs] if oscat else []
        if not oscat:
            for f in fs:
                if groups and f[2] - groups[-1][-1][2] <= dt.timedelta(minutes=GROUP_MIN):
                    groups[-1].append(f)
                else:
                    groups.append([f])
        for g in groups:
            start, last = g[0][2], g[-1][2]
            end = last + dt.timedelta(minutes=NOMINAL_MIN["oscat" if oscat else "uhr"])
            key = ("%s-%s-%s" % (prefix, _orbit(g[0][1]), "x") if oscat else "%s-%s" % (prefix, g[0][2].strftime("%Y%m%dT%H%M%S")))
            out.append(dict(key=key, id="%s-%s" % (start.strftime("%Y%m%dT%H%M"), prefix), prefix=prefix, start=start,
                            end=end, files=[(f[1], f[2]) for f in g]))
    return sorted(out, key=lambda p: p["start"], reverse=True)


def merge_points(parts):
    keys = ("lat", "lon", "u", "v", "spd", "q")
    return {k: np.concatenate([p[k] for p in parts]) for k in keys}


def process_pass(p, water, inbox):
    """Download and grid one pass -> {basin: (idx, spd, dir, flag)} for the basins with enough water cells."""
    parts = []
    if "pts" in p:   # an RSS pseudo-pass: the cells are already in hand
        inbox = {b: m for b, m in inbox.items() if b == p["basin"]}
        parts.append(p["pts"])
    for url, _ in p["files"]:
        pts = star.points(url)
        if pts is not None and pts["lat"].size:
            parts.append(pts)
    if not parts:
        return {}
    idx, spd, direction, flag = grid_points(merge_points(parts))
    out = {}
    for b, m in inbox.items():
        k = (m & water).ravel()[idx]
        if k.sum() >= MIN_CELLS:
            out[b] = (idx[k], spd[k], direction[k], flag[k])
    return out


# ---------- RSS ASCAT ----------

def rss_points(c):
    """RSS cells (nwp.rss_ascat) -> points dict for grid_points, each cell put at the centre of the page cell it maps to.
    RSS cell centres sit at x.125 degrees, on the corner of four page cells (centres at multiples of 0.25). Each RSS
    cell is given to the page cell at its north-west corner: lat + 0.125, lon - 0.125 (a shift of half an RSS cell,
    the same for every cell, so the map is 1:1 and no page cell gets two). Speed is kept, direction (from) becomes u, v."""
    th = np.radians(c["dir_deg"].astype(np.float64))
    spd = c["spd_kt"].astype(np.float64)
    return dict(lat=(c["lat"].astype(np.float64) + 0.125).astype(np.float32),
                lon=(c["lon"].astype(np.float64) - 0.125).astype(np.float32),
                u=(-spd * np.sin(th)).astype(np.float32), v=(-spd * np.cos(th)).astype(np.float32),
                spd=c["spd_kt"].astype(np.float32), q=c["rain"].astype(np.uint8))


def split_passes(tag, day, c, water, inbox, stable=False):
    """One satellite-day of cells (nwp.rss_ascat / nwp.nesdis_ascat dict) -> pseudo-passes, one per (node, nearest synoptic
    hour of the cell time, basin) that has MIN_CELLS water cells inside the OPC box: dict(key, id, prefix, basin, start,
    end, mid, files [], pts). start and end are the earliest and latest cell time, mid the mean. The prefix is
    <tag>_<AS|DS> (AS ascending, DS descending). The id is <earliest cell YYYYMMDDTHHMM>-<prefix>, or with `stable` (a
    day that is still filling) <synoptic hour YYYYMMDDTHH00>-<prefix> (the cells after 21Z, which belong to the 00Z of the next day but come in this
    day's file, <YYYYMMDDT2400>), which does not move when later cells arrive. The key
    (<prefix>-<synoptic hour>-<basin>) is the same either way. A pseudo-pass never holds two basins, so its times are
    those of its own basin."""
    pts = rss_points(c)
    iy = np.round((90 - pts["lat"].astype(np.float64)) * 4).astype(np.int64)
    ix = np.round((pts["lon"].astype(np.float64) + 180) * 4).astype(np.int64) % NX
    flat = iy * NX + ix
    syn = np.floor(c["t_min"].astype(np.float64) / 360 + 0.5).astype(np.int64)   # synoptic hour / 6: 0..4 (4 = 00Z of the next day)
    day0 = dt.datetime(day.year, day.month, day.day)
    out = []
    for basin, m in inbox.items():
        inside = (m & water).ravel()[flat] & (iy >= 0) & (iy < NY)
        for node in (0, 1):
            for sh in np.unique(syn[inside & (c["node"] == node)]):
                k = inside & (c["node"] == node) & (syn == sh)
                if k.sum() < MIN_CELLS:
                    continue
                t = c["t_min"][k].astype(np.float64)
                start, end = day0 + dt.timedelta(minutes=float(t.min())), day0 + dt.timedelta(minutes=float(t.max()))
                mid = day0 + dt.timedelta(minutes=round(float(t.mean())))
                prefix = "%s_%s" % (tag, "AS" if node == 0 else "DS")
                # the synoptic stamp: 00, 06, 12, 18Z of the day; the cells after 21Z (syn 4) are 00Z of the next day but their own
                # pass here (the next day's file holds the other cells of that 00Z), so they are stamped <day>T2400
                stamp = day0.strftime("%Y%m%dT") + "%02d" % (6 * int(sh))
                out.append(dict(key="%s-%s-%s" % (prefix, stamp, basin),
                                id="%s-%s" % (stamp + "00" if stable else start.strftime("%Y%m%dT%H%M"), prefix), prefix=prefix,
                                basin=basin, start=start, end=end, mid=mid, files=[], pts={n: v[k] for n, v in pts.items()}))
    return out


def rss_passes(sat, day, c, water, inbox):
    """One satellite-day of RSS cells -> pseudo-passes (split_passes), prefix rss_metop<b|c>_<AS|DS>, id from the earliest cell."""
    return split_passes("rss_metop%s" % sat, day, c, water, inbox)


def rss_days(now):
    """UTC days (datetime at 00) whose cells can still be in the window and that are not older than RSS_GIVE_UP, oldest first."""
    d0 = (now - dt.timedelta(days=KEEP_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    while d0 <= now:
        if now - d0 <= RSS_GIVE_UP:
            out.append(d0)
        d0 += dt.timedelta(days=1)
    return out


def rss_ready(got, day, now):
    """got: satellites posted ('' 'b' 'c' 'bc') -> use the day? Both are in, or one is and the day is RSS_LATE old."""
    return len(got) == len(RSS_SATS) or (len(got) > 0 and now - day >= RSS_LATE)


def fetch_rss(now, rs, water, inbox, fetch=None):
    """Ask RSS for every day of the window not done yet (at most once per RSS_RETRY each) and turn the days that are ready
    into pseudo-passes. rs (cache/rss.json: YYYYMMDD -> dict(done, sats, tried)) is updated in place -> new pass dicts."""
    fetch = fetch or rss_ascat.day
    new = []
    for d in rss_days(now):
        key = d.strftime("%Y%m%d")
        st = rs.get(key, {})
        if st.get("done") or (st.get("tried") and now - _t(st["tried"]) < RSS_RETRY):
            continue
        got, failed = {}, False
        for s in RSS_SATS:
            try:
                c = fetch(s, d)
            except Exception as e:   # network: ask again next run
                print("RSS %s %s failed (%s: %s)" % (s, key, type(e).__name__, e), file=sys.stderr, flush=True)
                failed = True
                continue
            if c is not None:
                got[s] = c
        st = rs[key] = dict(tried=now.strftime(ISO), sats="".join(got), done=False)
        if failed or not rss_ready(got, d, now):
            print("RSS %s: %s posted, not used yet" % (key, st["sats"] or "none"), flush=True)
            continue
        st["done"] = True
        ps = [p for s, c in got.items() for p in rss_passes(s, d, c, water, inbox) if p["start"] > now - dt.timedelta(days=KEEP_DAYS)]
        new += ps
        print("RSS %s: %s posted, %d pseudo-passes" % (key, st["sats"], len(ps)), flush=True)
    cut = (now - RSS_GIVE_UP - dt.timedelta(days=2)).strftime("%Y%m%d")
    for k in [k for k in rs if k < cut]:
        del rs[k]
    return new


# ---------- NESDIS Metop-B ASCAT (near real time) ----------

def nesdis_done(day, st, now):
    """NESDIS day state st (cache/nesdis.json: fetched, tried, n) -> is the day final? It is NESDIS_FINAL old and was fetched
    after it ended (the last cells of a day are in by the time it is over, so no later fetch can add any)."""
    return bool(st.get("fetched")) and now - day >= NESDIS_FINAL and _t(st["fetched"]) >= day + dt.timedelta(days=1)


def nesdis_sig(ns, now):
    """What counts as a change in cache/nesdis.json: the cell counts and which days are final (not the times asked)."""
    return json.dumps({k: [v.get("n"), nesdis_done(dt.datetime.strptime(k, "%Y%m%d"), v, now)] for k, v in ns.items()}, sort_keys=True)


def rss_covers(rs, key):
    """Is the day used from RSS with Metop-B in it? Then NESDIS's Metop-B is not needed for it."""
    st = rs.get(key) or {}
    return bool(st.get("done")) and "b" in st.get("sats", "")


def fetch_nesdis(now, ns, rs, water, inbox, fetch=None):
    """Ask NESDIS for Metop-B on today, yesterday, and every day of the window that is not final yet and that RSS has not
    covered, and turn the passes that are new or have more cells than before into pseudo-passes (stable ids, so a pass
    that grew is replaced where it stands). A day older than yesterday is asked for at most once per NESDIS_RETRY. A day
    the server does not have gives nothing and is asked for again unless it is final. ns (cache/nesdis.json: YYYYMMDD ->
    dict(fetched, tried, n {key: cells})) is updated in place; rs is rss.json. At most 1 (Atlantic) + 2 (Pacific, across
    the date line) requests a day -> new pass dicts."""
    fetch = fetch or nesdis_ascat.day
    new = []
    d0 = (now - dt.timedelta(days=KEEP_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    days = []
    while d0 <= now:
        days.append(d0)
        d0 += dt.timedelta(days=1)
    for d in reversed(days):   # newest first
        key = d.strftime("%Y%m%d")
        st = ns.get(key, {})
        if rss_covers(rs, key) or nesdis_done(d, st, now):
            continue
        recent = now - d < dt.timedelta(days=2)   # today or yesterday: every run
        if not recent and st.get("tried") and now - _t(st["tried"]) < NESDIS_RETRY:
            continue
        got, failed = {}, False
        for basin in inbox:
            b = BOXES[basin]
            try:
                c = fetch(d, (b["south"], b["north"], b["west"], b["east"]))
            except Exception as e:   # network: ask again next run
                print("NESDIS %s %s failed (%s: %s)" % (basin, key, type(e).__name__, e), file=sys.stderr, flush=True)
                failed = True
                continue
            if c is not None:
                got[basin] = c
        st = ns[key] = dict(st, tried=now.strftime(ISO))
        st.setdefault("n", {})
        if failed or len(got) < len(inbox):
            print("NESDIS %s: not there yet" % key if not failed else "NESDIS %s: failed" % key, flush=True)
            continue
        st["fetched"] = now.strftime(ISO)
        ps, grew = [], 0
        for basin, c in got.items():
            for p in split_passes("nesdis_metopb", d, c, water, {basin: inbox[basin]}, stable=True):
                n = int(p["pts"]["lat"].size)
                if p["start"] <= now - dt.timedelta(days=KEEP_DAYS) or n <= st["n"].get(p["key"], 0):
                    continue
                grew += p["key"] in st["n"]
                st["n"][p["key"]] = n
                ps.append(p)
        new += ps
        print("NESDIS %s: %d passes new or grown (%d of them grown)" % (key, len(ps), grew), flush=True)
    cut = (now - dt.timedelta(days=KEEP_DAYS + 2)).strftime("%Y%m%d")
    for k in [k for k in ns if k < cut]:
        del ns[k]
    return new


def pass_key(p):
    """What a pass dict (new, or grown) replaces in the entries: its id, or for a pseudo-pass (id, basin) -> predicate."""
    return (lambda k: k == (p["id"], p["basin"])) if "pts" in p else (lambda k: k[0] == p["id"])


def drop_redone(entries, todo):
    """entries {(id, basin): entry} without those the passes in todo are redone for. A STAR pass holds both basins and
    replaces both; a pseudo-pass holds one, and its id (a NESDIS one is the synoptic hour) is shared with the other basin's."""
    gone = [pass_key(p) for p in todo]
    return {k: e for k, e in entries.items() if not any(f(k) for f in gone)}


def pass_mid(p):
    return p.get("mid") or p["start"] + (p["end"] - p["start"]) / 2


# ---------- mosaics ----------

MOSAIC_HALF = dt.timedelta(hours=6)     # a mosaic holds the passes in [V - 6 h, V + 6 h)
MOSAIC_HOURS = 12                       # V = 00Z and 12Z
SETTLE = dt.timedelta(hours=4)          # STAR posts a pass 3-4 h after it flew


def mosaic_times(now):
    """Times V (00Z and 12Z) from the last KEEP_DAYS, not after `now`, newest first. The oldest is at least 7 h
    inside the window so that every pass of its [V - 6 h, V + 6 h) is still kept."""
    t = now.replace(minute=0, second=0, microsecond=0)
    t = t.replace(hour=t.hour // MOSAIC_HOURS * MOSAIC_HOURS)
    first = now - dt.timedelta(days=KEEP_DAYS) + MOSAIC_HALF + dt.timedelta(hours=1)
    out = []
    while t >= first:
        out.append(t)
        t -= dt.timedelta(hours=MOSAIC_HOURS)
    return out


def _t(s):
    return dt.datetime.strptime(s, ISO)


def window_entries(entries, basin, v):
    """Pass entries of a basin whose middle is in [V - 6 h, V + 6 h), ordered by middle time (the mosaic's pass order)."""
    return sorted((e for e in entries if e["basin"] == basin and v - MOSAIC_HALF <= _t(e["mid"]) < v + MOSAIC_HALF),
                  key=lambda e: (e["mid"], e["id"]))


def stitch(v, members):
    """members [(entry, unpacked pass)] in mosaic order -> (idx int64, obs, dir, flag, pass index, position of the cell
    in its pass) of the union of their cells; where passes overlap RSS ASCAT wins over NESDIS Metop-B, which wins over STAR ASCAT, which wins over OSCAT-3
    (the better referee: OSCAT-3 reads low at gale force and above, marine-research study 2026-11-12), then the one
    nearest V, a tie the newer."""
    obs = np.full(NX * NY, 255, np.uint8)
    dr, fl, pi = (np.zeros(NX * NY, np.uint8) for _ in range(3))
    pos = np.zeros(NX * NY, np.int32)
    order = sorted(range(len(members)), key=lambda i: (source_rank(members[i][0]["sat"]), -abs(_t(members[i][0]["mid"]) - v),
                                                       members[i][0]["mid"]))
    for i in order:   # the winner is written last
        u = members[i][1]
        k = u["idx"].astype(np.int64)
        obs[k], dr[k], fl[k], pi[k], pos[k] = u["obs"], u["dir"], u["flag"], i, np.arange(k.size)
    idx = np.nonzero(obs != 255)[0]
    return idx, obs[idx], dr[idx], fl[idx], pi[idx], pos[idx]


def _score_on(sel_cells, obs, flag, g, w):
    return score(obs[sel_cells], flag[sel_cells], g[sel_cells], w[sel_cells])


def cell_leads(members, pi, pos):
    """Per observed cell the grid and warning bytes of its own pass -> {lead: (grid, warn, has)}; has is False where the
    pass lacks the lead (bytes 255)."""
    n = pi.size
    out = {}
    for lead in LEADS:
        g, w, has = np.full(n, 255, np.uint8), np.full(n, 255, np.uint8), np.zeros(n, bool)
        for i, (e, u) in enumerate(members):
            if not (e.get("fc") or {}).get(lead):
                continue
            k = pi == i
            g[k], w[k], has[k] = u["leads"][lead][0][pos[k]], u["leads"][lead][1][pos[k]], True
        out[lead] = (g, w, has)
    return out


def peak_cell(idx, obs, flag, g, w, sel):
    """The highest unflagged observed cell among `sel` (the first on a tie) -> dict(idx, obs, grid, warn) or None."""
    k = np.nonzero(sel & (flag == 0))[0]
    if not k.size:
        return None
    j = k[int(np.argmax(obs[k]))]
    return dict(idx=int(idx[j]), obs=int(obs[j]), grid=int(g[j]), warn=int(w[j]))


def pass_sig(e):
    return [[e["fc"][l]["cycle"], e["fc"][l]["step"]] if e["fc"].get(l) else None for l in LEADS]


def build_mosaic(basin, v, members, sel, fc, water_box):
    """-> (gzip bytes, index entry minus `file`). sel = pick_leads(cycles, v) (the lines drawn); water_box bool [ny, nx]."""
    idx, obs, dr, fl, pi, pos = stitch(v, members)
    n = int(idx.size)
    iy0, ny, ix0, nx = box_cols(basin)
    obsf = obs.astype(np.float32)
    ascat = np.array([is_ascat(e["sat"]) for e, _ in members], bool)[pi]
    rss = np.array([is_rss(e["sat"]) for e, _ in members], bool)[pi]
    nes = np.array([is_nesdis(e["sat"]) for e, _ in members], bool)[pi]
    cell = cell_leads(members, pi, pos)
    blobs = [np.uint32(n).tobytes(), idx.astype("<u4").tobytes(), obs.tobytes(), dr.tobytes(), fl.tobytes(), pi.tobytes()]
    for lead in LEADS:
        blobs += [cell[lead][0].tobytes(), cell[lead][1].tobytes()]
    fcinfo, sc, sca, area, peak, uns, uns_a, vsel = {}, {}, {}, {}, {}, {}, {}, {}
    for lead in LEADS:
        g, w, has = cell[lead]
        s = sel.get(lead)
        vsel[lead] = None if s is None else dict(cycle=s[0], step=s[1])
        uns[lead], uns_a[lead] = int((~has).sum()), int((ascat & ~has).sum())
        if has.sum() * MIN_LEAD_SHARE[1] < n * MIN_LEAD_SHARE[0]:
            fcinfo[lead] = sc[lead] = sca[lead] = area[lead] = peak[lead] = None
            continue
        gf = g.astype(np.float32)
        sc[lead] = _score_on(has, obsf, fl, gf, w)
        sca[lead] = _score_on(has & ascat, obsf, fl, gf, w)
        peak[lead] = dict(all=peak_cell(idx, obsf, fl, g, w, has), ascat=peak_cell(idx, obsf, fl, g, w, has & ascat))
        if s is None:
            fcinfo[lead], area[lead] = dict(cycle=None, step=None), None
            continue
        fcinfo[lead] = dict(vsel[lead])
        cyc, step = s
        best = fc.field(cyc, basin, "best", step).astype(np.float32) / fc.cycles[cyc]["best_scale"]
        warn = fc.field(cyc, basin, "warn", step)
        area[lead] = [int(((best >= t) & water_box).sum()) for t in THRESH]
        gb = np.where(water_box, np.clip(np.round(best), 0, 254), 255).astype(np.uint8)
        wb = np.where(water_box, warn, 255).astype(np.uint8)
        blobs += [gb.tobytes(), wb.tobytes()]
    ok = fl == 0
    ent = dict(format=FORMAT, basin=basin, valid=v.strftime(ISO), passes=[e["id"] for e, _ in members], n=n, flagged=int((~ok).sum()),
               obs_max=round(float(obsf[ok].max()), 1) if ok.any() else 0.0, water=int(water_box.sum()),
               box=dict(iy0=iy0, ny=ny, ix0=ix0, nx=nx), fc=fcinfo, vsel=vsel, score=sc, score_ascat=sca, peak=peak,
               unscored=uns, unscored_ascat=uns_a, grid_area_box=area, sig=[pass_sig(e) for e, _ in members],
               sats={"ASCAT": int(ascat.sum()), "OSCAT-3": int((~ascat).sum()), "RSS": int(rss.sum()), "NESDIS": int(nes.sum())})
    return gzip.compress(b"".join(blobs), 9, mtime=0), ent


def is_rss(sat):
    return sat.startswith("RSS")


def is_nesdis(sat):
    return sat.endswith("(NESDIS)")


def is_ascat(sat):
    return is_rss(sat) or sat.startswith("Metop")


def source_rank(sat):
    """Overlap priority in the stitch: RSS ASCAT 3, NESDIS Metop-B 2, STAR ASCAT 1, OSCAT-3 0."""
    return 3 if is_rss(sat) else 2 if is_nesdis(sat) else 1 if is_ascat(sat) else 0


def unpack_mosaic(blob, ent):
    """Inverse of build_mosaic's bytes -> dict(idx, obs, dir, flag, pass_, cell {lead: (grid, warn) [n]},
    leads {lead: (grid, warn) [ny, nx]} at V)."""
    raw = gzip.decompress(blob)
    n = int(np.frombuffer(raw, "<u4", 1)[0])
    o = 4
    idx = np.frombuffer(raw, "<u4", n, o); o += 4 * n
    take = []
    for _ in range(4):
        take.append(np.frombuffer(raw, np.uint8, n, o)); o += n
    cell = {}
    for lead in LEADS:
        g = np.frombuffer(raw, np.uint8, n, o); o += n
        w = np.frombuffer(raw, np.uint8, n, o); o += n
        cell[lead] = (g, w)
    ny, nx = ent["box"]["ny"], ent["box"]["nx"]
    leads = {}
    for lead in LEADS:
        if (ent["fc"].get(lead) or {}).get("cycle"):
            g = np.frombuffer(raw, np.uint8, ny * nx, o).reshape(ny, nx); o += ny * nx
            w = np.frombuffer(raw, np.uint8, ny * nx, o).reshape(ny, nx); o += ny * nx
            leads[lead] = (g, w)
    return dict(idx=idx, obs=take[0], dir=take[1], flag=take[2], pass_=take[3], cell=cell, leads=leads)


def update_mosaics(now, entries, prev_mosaics, cycles, fc, water, inbox, pdir, mdir, state_dir, touched):
    """Build or rebuild the mosaic of every time that needs one (module doc) from the pass files in pdir ->
    (index entries newest first, number built)."""
    prev = {(m["basin"], m["valid"]): m for m in prev_mosaics}
    entries = [e for e in entries if os.path.exists(os.path.join(pdir, os.path.basename(e["file"])))]
    out, built = [], 0
    os.makedirs(mdir, exist_ok=True)
    keep = set()
    for v in mosaic_times(now):
        sel = pick_leads(cycles, v)
        want_fc = {l: None if sel[l] is None else dict(cycle=sel[l][0], step=sel[l][1]) for l in LEADS}
        is_open = now < v + MOSAIC_HALF + SETTLE
        for basin in BOXES:
            ws = window_entries(entries, basin, v)
            if not ws:
                continue
            key = (basin, v.strftime(ISO))
            old = prev.get(key)
            fn = "mosaic/%s-%s.bin" % (basin, v.strftime("%Y%m%d%H"))
            dst = os.path.join(mdir, os.path.basename(fn))
            if old and not os.path.exists(dst) and os.path.exists(os.path.join(state_dir, "data", fn)):
                shutil.copy2(os.path.join(state_dir, "data", fn), dst)
            ids = [e["id"] for e in ws]
            if (old and old.get("format") == FORMAT and os.path.exists(dst) and old["passes"] == ids and not (set(ids) & touched) and not any((i, basin) in touched for i in ids)
                    and old.get("vsel") == want_fc and old.get("sig") == [pass_sig(e) for e in ws]):
                out.append(dict(old, open=is_open))
                keep.add(os.path.basename(fn))
                continue
            members = []
            for e in ws:
                with open(os.path.join(pdir, os.path.basename(e["file"])), "rb") as f:
                    members.append((e, unpack_pass(f.read())))
            wb = crop_box(water & inbox[basin], basin)
            blob, ent = build_mosaic(basin, v, members, sel, fc, wb)
            ent["file"], ent["open"] = fn, is_open
            with open(dst, "wb") as f:
                f.write(blob)
            out.append(ent)
            keep.add(os.path.basename(fn))
            built += 1
    for fn in os.listdir(mdir):
        if fn not in keep:
            os.remove(os.path.join(mdir, fn))
    out.sort(key=lambda m: (m["valid"], m["basin"]), reverse=True)
    return out, built


def _group_summary(ms, lead, group):
    key = "score_ascat" if group == "ascat" else "score"
    cov = [(m["sats"]["ASCAT"] if group == "ascat" else m["n"]) / m["water"] for m in ms if m["water"]]
    S = dict(times=len(ms), with_rss=sum(1 for m in ms if (m.get("sats") or {}).get("RSS", 0) > 0),
             with_nesdis=sum(1 for m in ms if (m.get("sats") or {}).get("NESDIS", 0) > 0), cov_mean=round(float(np.mean(cov)), 4) if cov else None, cov_min=round(min(cov), 4) if cov else None,
             cov_max=round(max(cov), 4) if cov else None, mosaics=0, n=0, obs=[0] * 3, grid=[0] * 3, catch=[0] * 3, line=[0] * 3,
             nmos_obs=[0] * 3, nmos_line=[0] * 3, min_seen=MIN_SEEN, min_mosaics=MIN_MOSAICS)
    worst = []
    for m in ms:
        s = (m.get(key) or {}).get(lead)
        if s is None:
            continue
        S["mosaics"] += 1
        S["n"] += s["n"]
        for i in range(3):
            for k in ("obs", "grid", "catch", "line"):
                S[k][i] += s[k][i]
            S["nmos_obs"][i] += s["obs"][i] > 0
            S["nmos_line"][i] += s["line"][i] > 0
        p = ((m.get("peak") or {}).get(lead) or {}).get(group)
        if p:
            worst.append(dict(valid=m["valid"], obs=p["obs"], grid=p["grid"], grid_max=s["grid_max"], warn=p["warn"], idx=p["idx"]))
    worst.sort(key=lambda x: (x["obs"], x["valid"]), reverse=True)
    S["worst"] = worst[:WORST_N]
    S["enough"] = [S["obs"][i] >= MIN_SEEN and S["nmos_obs"][i] >= MIN_MOSAICS for i in range(3)]
    S["enough_line"] = [S["line"][i] >= MIN_SEEN and S["nmos_line"][i] >= MIN_MOSAICS for i in range(3)]
    return S


def summarize(mosaics):
    """The week's sums over the closed mosaics (module doc) -> {basin: {lead: {"ascat": ..., "all": ...}}}."""
    closed = [m for m in mosaics if not m.get("open")]
    return {b: {lead: {g: _group_summary([m for m in closed if m["basin"] == b], lead, g) for g in ("ascat", "all")}
                for lead in LEADS} for b in BOXES}


# ---------- output ----------

def pack_pass(idx, spd, direction, flag, leads):
    """leads {lead: (grid kt, warn) or None} -> gzip bytes (module doc)."""
    raw = {}
    for lead in LEADS:
        f = leads.get(lead)
        raw[lead] = None if f is None else (np.clip(np.round(f[0]), 0, 254).astype(np.uint8), f[1].astype(np.uint8))
    return pack_raw(idx, np.clip(np.round(spd), 0, 254).astype(np.uint8),
                    (np.round(direction / 2).astype(np.int64) % 180).astype(np.uint8), flag, raw)


def pack_raw(idx, obs, dirb, flag, leads):
    """The same from the stored bytes; leads {lead: (grid uint8, warn uint8) or None}."""
    n = idx.size
    b = [np.uint32(n).tobytes(), idx.astype("<u4").tobytes(), obs.astype(np.uint8).tobytes(),
         dirb.astype(np.uint8).tobytes(), flag.astype(np.uint8).tobytes()]
    for lead in LEADS:
        f = leads.get(lead)
        b += [np.full(n, 255, np.uint8).tobytes()] * 2 if f is None else [f[0].tobytes(), f[1].tobytes()]
    return gzip.compress(b"".join(b), 6, mtime=0)


def unpack_pass(blob):
    """Inverse of pack_pass -> dict(idx, obs, dir, flag, leads {lead: (grid, warn)}) (raw bytes as stored)."""
    raw = gzip.decompress(blob)
    n = int(np.frombuffer(raw, "<u4", 1)[0])
    o = 4
    idx = np.frombuffer(raw, "<u4", n, o); o += 4 * n
    take = []
    for _ in range(3 + 2 * len(LEADS)):
        take.append(np.frombuffer(raw, np.uint8, n, o)); o += n
    return dict(idx=idx, obs=take[0], dir=take[1], flag=take[2],
                leads={l: (take[3 + 2 * i], take[4 + 2 * i]) for i, l in enumerate(LEADS)})


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=1, help="days back from today to list (0-8; default 1: today and yesterday)")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--record-max", type=int, default=RECORD_MAX, help="most forecast record artifacts to download per run")
    ap.add_argument("--changed-file", help="write 'true' or 'false' here: whether the state gained a pass or a cycle")
    a = ap.parse_args()
    t0 = time.time()
    now = utcnow()
    days = max(0, min(8, a.days))
    same = os.path.exists(a.out) and os.path.exists(a.state) and os.path.samefile(a.state, a.out)
    os.makedirs(os.path.join(a.out, "data", "pass"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "cache"), exist_ok=True)
    if not same and os.path.isdir(os.path.join(a.state, "cache")):
        shutil.copytree(os.path.join(a.state, "cache"), os.path.join(a.out, "cache"), dirs_exist_ok=True)
    cache = os.path.join(a.out, "cache")

    live_cycle, new_cycle = cache_live(a.live, cache, now)
    cycles = load_cycles(cache)
    fc = Forecasts(cycles)
    water = load_mask(cache, now)
    inbox = {k: box_mask(k) for k in BOXES}

    prev = read_json(os.path.join(a.state, "data", "index.json"), {"passes": []})
    seen = read_json(os.path.join(a.state, "cache", "seen.json"), {})
    files = []
    for k in range(days + 1):
        files += star.passes(now - dt.timedelta(days=k))
    files = sorted(set(files), key=lambda f: (f[0], f[2]))
    files = fix_oscat_times(files)
    passes = group_passes(files)
    todo = [p for p in passes if seen.get(p["key"], {}).get("files") != len(p["files"])
            and p["start"] > now - dt.timedelta(days=KEEP_DAYS)]
    print("%d files, %d passes, %d new or grown" % (len(files), len(passes), len(todo)), flush=True)
    rs = read_json(os.path.join(a.state, "cache", "rss.json"), {})
    rs_done0 = sorted(k for k, v in rs.items() if v.get("done"))
    todo += fetch_rss(now, rs, water, inbox)
    ns = read_json(os.path.join(a.state, "cache", "nesdis.json"), {})
    ns0 = nesdis_sig(ns, now)
    todo += fetch_nesdis(now, ns, rs, water, inbox)

    entries = {(e["id"], e["basin"]): e for e in prev["passes"]}
    # f24 and f48 from the forecast records where the cache lacks the cycle: for the new passes and for
    # entries that have a lead null
    n_rec = 0
    mp = os.path.join(cache, "record_misses.json")
    misses0 = read_json(mp, {})
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        mids = [pass_mid(p) for p in todo]
        mids += [dt.datetime.strptime(e["mid"], ISO) for e in entries.values() if not (e["fc"]["f24"] and e["fc"]["f48"])]
        # and for the times that have a mosaic (the lines drawn are those of V)
        allmid = [dt.datetime.strptime(e["mid"], ISO) for e in entries.values()] + [pass_mid(p) for p in todo]
        mids += [v for v in mosaic_times(now) if any(v - MOSAIC_HALF <= m < v + MOSAIC_HALF for m in allmid)]
        wants = [cs for m in sorted(mids, reverse=True) for cs in record_cycles(m).values()]
        n_rec = ensure_records(cache, cycles, wants, now, a.record_max)
        if n_rec:
            cycles = load_cycles(cache)
            fc = Forecasts(cycles)
    else:
        print("no GITHUB_TOKEN: forecast records not fetched")
    # a pass seen before with more files is redone under its first id
    for p in todo:
        if p["key"] in seen:
            p["id"] = seen[p["key"]]["id"]
    entries = drop_redone(entries, todo)

    def work(p):
        try:
            return p, process_pass(p, water, inbox)
        except Exception as e:   # one bad file must not stop the rest
            print("failed %s: %s" % (p["id"], e), file=sys.stderr)
            return p, None
    n_new = 0
    touched = set()   # ids of the passes (re)built this run
    pdir = os.path.join(a.out, "data", "pass")
    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        for p, res in ex.map(work, todo):
            if res is None:
                continue
            if "pts" not in p:   # RSS days are tracked in rss.json
                seen[p["key"]] = dict(id=p["id"], files=len(p["files"]))
            touched.add((p["id"], p["basin"]) if "pts" in p else p["id"])
            mid = pass_mid(p)
            sel = pick_leads(cycles, mid)
            for basin, (idx, spd, direction, flag) in res.items():
                leads, fcinfo, sc = {}, {}, {}
                for lead in LEADS:
                    leads[lead] = lead_fields(fc, sel[lead], basin, idx)
                    fcinfo[lead] = lead_info(sel[lead])
                    sc[lead] = None if leads[lead] is None else score(spd, flag, leads[lead][0], leads[lead][1])
                name = "%s-%s" % (p["id"], basin)
                with open(os.path.join(pdir, name + ".bin"), "wb") as f:
                    f.write(pack_pass(idx, spd, direction, flag, leads))
                ok = flag == 0
                entries[(p["id"], basin)] = dict(
                    id=p["id"], basin=basin, sat=SAT[p["prefix"][:-3]], prefix=p["prefix"],
                    start=p["start"].strftime(ISO), end=p["end"].strftime(ISO), mid=mid.strftime(ISO),
                    n=int(idx.size), flagged=int((~ok).sum()), obs_max=round(float(spd[ok].max()), 1) if ok.any() else 0.0,
                    fc=fcinfo, score=sc, file="pass/%s.bin" % name)
                n_new += 1
            print("  %s: %s" % (p["id"], ", ".join("%s %d" % (b, r[0].size) for b, r in res.items()) or "no cells"), flush=True)

    cut = (now - dt.timedelta(days=KEEP_DAYS)).strftime(ISO)
    n_fill = rescore(list(entries.values()), cycles, fc, pdir, a.state, cut)
    # keep the last week; carry the files over
    kept = sorted((e for e in entries.values() if e["start"] >= cut), key=lambda e: (e["start"], e["basin"]), reverse=True)
    if not same:
        for e in kept:
            dst = os.path.join(a.out, "data", e["file"])
            src = os.path.join(a.state, "data", e["file"])
            if not os.path.exists(dst) and os.path.exists(src):
                shutil.copy2(src, dst)
    mosaics, n_mos = update_mosaics(now, kept, prev.get("mosaics", []), cycles, fc, water, inbox, pdir,
                                    os.path.join(a.out, "data", "mosaic"), a.state, touched)
    live_files = {os.path.basename(e["file"]) for e in kept}
    for fn in os.listdir(pdir):
        if fn not in live_files:
            os.remove(os.path.join(pdir, fn))
    seen = {k: v for k, v in seen.items() if v["id"][:8] >= (now - dt.timedelta(days=KEEP_DAYS + 1)).strftime("%Y%m%d")}
    with open(os.path.join(cache, "seen.json"), "w") as f:
        json.dump(seen, f)
    with open(os.path.join(cache, "rss.json"), "w") as f:
        json.dump(rs, f)
    with open(os.path.join(cache, "nesdis.json"), "w") as f:
        json.dump(ns, f)
    rs_done = sorted(k for k, v in rs.items() if v.get("done"))
    index = dict(built=now.strftime("%Y-%m-%dT%H:%M:%SZ"), keep_days=KEEP_DAYS,
                 grid=dict(res=0.25, north=90, west=-180, nx=NX), cycle=live_cycle, format=FORMAT, rss=dict(days=rs_done, through=rs_done[-1] if rs_done else None),
                 nesdis=dict(newest=max((e["end"] for e in kept if e["sat"].endswith("(NESDIS)")), default=None)), passes=kept, mosaics=mosaics,
                 summary=summarize(mosaics))
    with open(os.path.join(a.out, "data", "index.json"), "w") as f:
        json.dump(index, f, separators=(",", ":"))
    changed = bool(n_new) or new_cycle or bool(n_fill) or bool(n_rec) or bool(n_mos) or rs_done != rs_done0 or nesdis_sig(ns, now) != ns0 or read_json(mp, {}) != misses0
    if a.changed_file:
        with open(a.changed_file, "w") as f:
            f.write("true" if changed else "false")
    size = sum(os.path.getsize(os.path.join(pdir, x)) for x in os.listdir(pdir))
    mdir = os.path.join(a.out, "data", "mosaic")
    msize = sum(os.path.getsize(os.path.join(mdir, x)) for x in os.listdir(mdir))
    print("%d mosaics kept (%d built), data/mosaic %.1f MB" % (len(mosaics), n_mos, msize / 1e6))
    print("%d records stored, %d passes given f24/f48" % (n_rec, n_fill))
    print("%d pass entries kept (%d new), cycle %s%s, data/pass %.1f MB, %.0f s" % (
        len(kept), n_new, live_cycle, " (new)" if new_cycle else "", size / 1e6, time.time() - t0))


if __name__ == "__main__":
    main()
