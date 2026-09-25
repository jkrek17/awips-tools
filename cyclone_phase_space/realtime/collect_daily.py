#!/usr/bin/env python3
"""Daily collection of storm-following cyclone phase diagrams from the 12 UTC GFS.

    python3 collect_daily.py [--cycle YYYYMMDDHH] [--hours 0 6 ... 198] [--data-dir DIR]

For every active storm in watch.json: derive this cycle's seed from the
storm's stored seed (or from the previous run's track), follow the low
through the run with track_cps (global grid, Hart's bands), and keep the
track table, the phase diagrams and a meta.json under
data/<cycle>/<NAME>/. The storm is then matched to the Florida State
University cyclone of the same GFS run (the nearest one on FSU's
clickable map, within MATCH_KM of our first fix), whose two zoomed phase
diagrams and track map are downloaded and stacked above ours in
compare.png. Writes data/<cycle>/summary.md, appends to data/log.csv and
moves every tracked storm's seed in watch.json to its first fix of this
cycle. A storm with no closed low within 400 km of its seed is marked
inactive. See README.md, "Daily collection".

At the 0 h frame, every closed low deeper than AUTO_MSLP_HPA north of
AUTO_LAT_MIN that no watched storm covers is added to watch.json as
AUTO_<YYMMDD>_<NN> (at most AUTO_MAX_PER_DAY a day) and tracked in the
same run; of two active storms within MERGE_KM at 0 h the newer entry
ends as merged, and an AUTO storm above FILL_HPA at 0 h for FILL_CYCLES
collected cycles ends as filled. See README.md, "Automatic discovery".

A rerun for a cycle already collected reuses what is there (no GFS work
for storms whose meta.json says ok, cached FSU files, no duplicate log
lines); it only retries the FSU match where there was none. --force
recomputes the tracks.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gfs_cps as g  # noqa: E402
import track_cps as tc  # noqa: E402

from PIL import Image  # noqa: E402  (pillow comes with matplotlib)

WATCH = HERE / "watch.json"
DATA = HERE / "data"
OUT = HERE / "out"  # GRIB cache and full-size working outputs (gitignored)
REGION = "global"
DEFAULT_HOURS = list(range(0, 199, 6))
PROBE_DAYS = 4  # default cycle: today's 12 UTC run or up to this many days back

# Automatic discovery of deep lows at 0 h (README, "Automatic discovery").
AUTO_PREFIX = "AUTO_"
AUTO_MSLP_HPA = 980.0  # a closed low at 0 h below this MSLP is added ...
AUTO_LAT_MIN = 0.0  # ... if it lies north of this latitude (northern hemisphere only)
AUTO_MAX_PER_DAY = 6  # at most this many AUTO_<YYMMDD>_NN storms per day (deepest first)
AUTO_SYSTEM_KM = 500.0  # minima within this of a deeper one belong to the same system
AUTO_KNOWN_KM = 500.0  # no new storm within this of a watched storm's 0 h position
MERGE_KM = 300.0  # two active storms closer than this at 0 h: the newer entry ends
FILL_HPA = 1000.0  # an AUTO storm whose 0 h MSLP is above this ...
FILL_CYCLES = 2  # ... for this many consecutive collected cycles ends as filled
NEXT_CYCLE_H = 24  # a storm merged into another by this hour has no seed for the next daily cycle

PHASE_WIDTH = 1600  # phase.png kept in the repository, downscaled from 2400 px
COMPARE_WIDTH = 2048  # compare.png: two 1024 px FSU diagrams over our diagram
FSU_PANEL = 1024
COMPARE_GAP = 10

# ------------------------------------------------------------------ FSU
FSU_HOST = "moe.met.fsu.edu"
FSU_DIR = "cyclonephase/gfs/fcst/archive"
USER_AGENT = ("awips-tools CPS daily collection (https://github.com/jkrek17/awips-tools, "
              "cyclone_phase_space/realtime/collect_daily.py)")
FSU_MIN_INTERVAL_S = 1.0
MATCH_KM = 400.0
# alltrack.png (1024 x 768) is a plate carree map of 30E to 390E by 80S to
# 80N whose colored frame spans x 47..977, y 154..636. Calibrated on the
# axis labels and ticks (180 at x 434, 120W at 589, 0 at 899.5; 60N at
# y 214, the equator at 395.5), with the offsets set so that FSU cyclone 1
# of 26092412 (square centered at 495, 350) lands at 15.2N 156.3W.
MAP_FRAME = (47, 154, 977, 636)
X_LON0 = 899.0  # x of longitude 0
PX_PER_DEG_LON = 930.0 / 360.0
Y_EQ = 396.0  # y of the equator
PX_PER_DEG_LAT = 3.02


def log(msg: str) -> None:
    print(msg, flush=True)


def ymd_h(cycle: str) -> str:
    """2026092412 -> 12 UTC 2026-09-24."""
    return f"{cycle[8:]} UTC {cycle[:4]}-{cycle[4:6]}-{cycle[6:8]}"


def hours_between(c0: str, c1: str) -> int:
    """Hours from cycle c0 to cycle c1."""
    return int(round((g.cycle_time(c1) - g.cycle_time(c0)).total_seconds() / 3600.0))


def fmt_pos(lat: float, lon: float) -> str:
    return f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'} {abs(lon):.1f}{'W' if lon < 0 else 'E'}"


def num(v):
    """An hour for JSON: int, or None for NaN."""
    return None if v is None or not np.isfinite(v) else int(round(float(v)))


# ------------------------------------------------------------------ cycle
def f_exists(cycle: str, fhr: int) -> str | None:
    """'nomads' or 'aws' if the cycle's f<fhr> index is posted there, else None."""
    d, f = g.gfs_name(cycle, fhr)
    for src, root in (("nomads", f"{g.NOMADS}/pub/data/nccf/com/gfs/prod"), ("aws", g.AWS)):
        try:
            if requests.head(f"{root}/{d}/{f}.idx", timeout=g.TIMEOUT).status_code == 200:
                return src
        except requests.RequestException:
            pass
    return None


def default_cycle(last_fhr: int, now: dt.datetime | None = None) -> str:
    """Today's 12 UTC run if its last hour is posted, else the most recent
    12 UTC run that has it (NOMADS first, then the AWS bucket)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    t = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if t > now:
        t -= dt.timedelta(days=1)
    for _ in range(PROBE_DAYS + 1):
        cyc = t.strftime("%Y%m%d%H")
        src = f_exists(cyc, last_fhr)
        if src:
            log(f"default cycle {cyc}: f{last_fhr:03d} found on {src}")
            return cyc
        log(f"cycle {cyc}: f{last_fhr:03d} not posted")
        t -= dt.timedelta(days=1)
    raise SystemExit(f"no 12 UTC GFS run with f{last_fhr:03d} in the last {PROBE_DAYS} days")


# ------------------------------------------------------------------ seeds
def read_track(path: Path) -> list[dict]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


def derive_seed(st: dict, cycle: str, data_dir: Path) -> dict:
    """This cycle's seed for a watch entry: the stored seed if it is for this
    cycle (or still ahead of it); otherwise the position, in the newest
    earlier collected track, at the forecast hour that is valid now
    (normally +24 h of yesterday's run); otherwise the stored seed."""
    dh = hours_between(st["cycle"], cycle)
    fhr1 = st.get("fhr1")
    fhr1_eff, expired = None, False
    if fhr1 is not None:
        fhr1_eff = int(fhr1) - dh
        if fhr1_eff < 6:
            fhr1_eff, expired = None, True
    seed = dict(lat=float(st["lat"]), lon=float(st["lon"]), fhr0=int(st.get("fhr0") or 0), fhr1=fhr1_eff,
                fhr1_expired=expired)
    if dh == 0:
        return dict(seed, source="stored seed")
    if seed["fhr0"] - dh >= 0:  # seeded at an hour still ahead of this cycle
        return dict(seed, fhr0=seed["fhr0"] - dh, source=f"stored seed, +{st.get('fhr0') or 0} h of {st['cycle']}")
    cands = sorted((p.name for p in data_dir.iterdir() if re.fullmatch(r"\d{10}", p.name) and p.name < cycle
                    and (dh < 0 or p.name >= st["cycle"]) and (p / st["name"] / "track.csv").exists()),
                   reverse=True) if data_dir.exists() else []
    for c in cands:
        want = hours_between(c, cycle)
        for row in read_track(data_dir / c / st["name"] / "track.csv"):
            if int(row["fhr"]) == want:
                return dict(seed, lat=float(row["lat"]), lon=float(row["lon"]), fhr0=0,
                            source=f"track of {c} at +{want} h")
    note = f"stored seed of {st['cycle']}" + (" (a later cycle)" if dh < 0 else "")
    if cands:
        note += f"; the track of {cands[0]} has no fix at +{hours_between(cands[0], cycle)} h"
    return dict(seed, fhr0=0, source=note)


# ------------------------------------------------------------------ discovery
def basin(lat: float, lon: float) -> str:
    """NATL (100W to 20E), NPAC (west of 100W or east of 100E) north of 20N,
    TROP south of 20N, else the position."""
    if lat < 20.0:
        return "TROP"
    if -100.0 <= lon <= 20.0:
        return "NATL"
    if lon < -100.0 or lon > 100.0:
        return "NPAC"
    return fmt_pos(lat, lon)


def deep_lows(f: dict) -> list[dict]:
    """Closed lows of the frame below AUTO_MSLP_HPA north of AUTO_LAT_MIN, one
    per system: the tracker's candidate centers (tc.all_centers), deepest
    first, dropping any within AUTO_SYSTEM_KM of a deeper one kept. Positions
    are refined to a fraction of a cell as the tracker does."""
    cands = sorted((m, i, j) for i, j, m in tc.all_centers(f, True)
                   if m < AUTO_MSLP_HPA and f["lat"][i] > AUTO_LAT_MIN)
    kept: list[dict] = []
    for m, i, j in cands:
        lat, lon = float(f["lat"][i]), float(tc.wrap180(f["lon"][j]))
        if any(tc.gc_km(lat, lon, k["lat"], k["lon"]) < AUTO_SYSTEM_KM for k in kept):
            continue
        hit = tc.find_center(f, lat, lon, 30.0, True)
        if hit is not None:
            fi, fj, m = hit
            lat = float(f["lat"][0] + fi * g.RES_DEG)
            lon = float(tc.wrap180(f["lon"][0] + fj * g.RES_DEG))
        kept.append(dict(lat=round(lat, 2), lon=round(lon, 2), mslp_hpa=round(m, 2), basin=basin(lat, lon)))
    return kept


def pos_zero(meta: dict | None) -> tuple[float, float] | None:
    """A collected storm's position at 0 h from its meta.json: its first fix
    if that is at 0 h, else its seed if the seed was for 0 h (a lost or
    merged storm)."""
    if not meta:
        return None
    if meta.get("status") == "ok":
        return (meta["start"]["lat"], meta["start"]["lon"]) if meta.get("start_fhr") == 0 else None
    s = meta.get("seed") or {}
    return (s["lat"], s["lon"]) if s.get("fhr0") == 0 and "lat" in s else None


def read_meta(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def earlier_metas(data_dir: Path, cycle: str, name: str) -> list[dict]:
    """The storm's meta.json of the collected cycles before this one, newest first."""
    out = []
    if data_dir.exists():
        for c in sorted((p.name for p in data_dir.iterdir() if re.fullmatch(r"\d{10}", p.name) and p.name < cycle),
                        reverse=True):
            m = read_meta(data_dir / c / name / "meta.json")
            if m:
                out.append(m)
    return out


def filled(data_dir: Path, cycle: str, name: str, mslp0: float) -> bool:
    """True for an AUTO storm whose 0 h MSLP is above FILL_HPA in this cycle
    and in the FILL_CYCLES - 1 collected cycles before it."""
    if not name.startswith(AUTO_PREFIX) or mslp0 <= FILL_HPA:
        return False
    prev = earlier_metas(data_dir, cycle, name)[:FILL_CYCLES - 1]
    return len(prev) == FILL_CYCLES - 1 and all(
        m.get("status") == "ok" and m.get("start_fhr") == 0 and m["start"]["mslp_hpa"] > FILL_HPA for m in prev)


def end_note(st: dict, cycle: str, text: str) -> None:
    st["active"] = False
    st["ended_cycle"] = cycle
    st["notes"] = (st.get("notes", "") + f" Inactive from {cycle}: {text}.").strip()


# ------------------------------------------------------------------ tracking
def make_track(job: dict) -> tc.Track:
    s = job["seed"]
    spec = f"{job['name']}:{s['lat']},{s['lon']}:{s['fhr0']}" + (f":{s['fhr1']}" if s["fhr1"] is not None else "")
    return tc.Track(spec)


def track_storms(cycle: str, hours: list[int], jobs: list[dict], workdir: Path, at_zero=None) -> set[int]:
    """Follow every job's low through the run with track_cps's tracker. Each
    frame is fetched, decoded and run through the module (and Hart's bands,
    and the closed-low mask) once, and every track samples that one set of
    fields; two tracks on the same low in a frame are resolved there
    (tc.merge_close). at_zero, if given,
    is called as at_zero(f, p, jobs) once the tracks have sampled the 0 h
    frame; it may mark jobs merged and returns new jobs, which are sampled
    at 0 h and followed with the rest. Sets job['track'] and job['events'],
    writes track_<NAME>.csv and phase_<NAME>.png (2400 px) to workdir.
    Returns the hours whose frame could not be fetched."""
    workdir.mkdir(parents=True, exist_ok=True)
    cache = OUT / "cache" / cycle
    for j in jobs:
        j["track"] = make_track(j)
    skipped: set[int] = set()
    t0 = time.time()
    pending = at_zero is not None and 0 in hours
    log(f"tracking {', '.join(j['name'] for j in jobs) or 'no storm yet'} through {len(hours)} frames of {cycle}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {h: pool.submit(g.get_grib, cycle, h, REGION, cache, "nomads", True) for h in hours}
        for fhr in hours:
            if not pending and all(j["track"].done for j in jobs):
                for fu in futs.values():
                    fu.cancel()
                break
            try:
                grib = futs[fhr].result()
            except Exception as exc:  # a late hour may not be posted yet
                log(f"  f{fhr:03d}: skipped ({exc})")
                skipped.add(fhr)
                if fhr == 0:
                    pending = False
                continue
            t1 = time.time()
            f = g.decode(grib, REGION, True)
            p = g.compute_products(f)
            p.update(g.compute_hart_bands(f))
            p["closed"] = tc.closed_mask(f)
            t2 = time.time()
            for j in jobs:
                tc.sample_frame(j["track"], f, p, fhr, True)
            if pending and fhr == 0:
                pending = False
                for nj in at_zero(f, p, jobs):
                    nj["track"] = make_track(nj)
                    tc.sample_frame(nj["track"], f, p, fhr, True)
                    jobs.append(nj)
            tc.merge_close([j["track"] for j in jobs if not j.get("merged_into")], fhr)
            tracks = [j["track"] for j in jobs if not j.get("merged_into")]
            where = "; ".join(f"{t.name} {t.fixes[-1]['lat']:.1f},{t.fixes[-1]['lon']:.1f} "
                              f"{t.fixes[-1]['mslp_hpa']:.0f}" for t in tracks if t.fixes and t.fixes[-1]["fhr"] == fhr)
            log(f"  f{fhr:03d}: {time.time() - t0:.0f} s (fields {t2 - t1:.1f} s, {len(tracks)} tracks "
                f"{time.time() - t2:.1f} s)   {where}")
    t3 = time.time()
    for j in jobs:
        t = j["track"]
        j["events"] = {}
        if not t.fixes or j.get("merged_into"):
            continue
        tc.track_motion(t.fixes)
        tc.b_with_track_motion(t.fixes)
        tc.write_csv(workdir / f"track_{t.name}.csv", t.fixes)
        j["events"] = tc.plot_phase(workdir / f"phase_{t.name}.png", t.name, cycle, t.fixes, True)
    log(f"tracking done in {time.time() - t0:.0f} s ({time.time() - t3:.0f} s of it for B and the diagrams)")
    return skipped


def class_runs(fixes: list[dict]) -> list[list]:
    """[[class or None, first hour, last hour], ...] over consecutive fixes."""
    runs: list[list] = []
    for fx in fixes:
        c = None if not np.isfinite(fx["class"]) else int(fx["class"])
        if runs and runs[-1][0] == c:
            runs[-1][2] = fx["fhr"]
        else:
            runs.append([c, fx["fhr"], fx["fhr"]])
    return runs


def build_meta(cycle: str, job: dict) -> dict:
    fx = job["track"].fixes
    a, z = fx[0], fx[-1]
    ev = job["events"]
    std = ev.get("standard", (float("nan"),) * 2)
    hart = ev.get("hart", (float("nan"),) * 2)
    s = job["seed"]
    return {
        "cycle": cycle,
        "name": job["name"],
        "status": "ok",
        "seed": {"lat": s["lat"], "lon": s["lon"], "fhr0": s["fhr0"], "fhr1": s["fhr1"], "source": s["source"]},
        "start_fhr": a["fhr"],
        "end_fhr": z["fhr"],
        "fixes": len(fx),
        "start": {"lat": round(a["lat"], 2), "lon": round(a["lon"], 2), "mslp_hpa": round(a["mslp_hpa"], 1)},
        "end": {"lat": round(z["lat"], 2), "lon": round(z["lon"], 2), "mslp_hpa": round(z["mslp_hpa"], 1)},
        "min_mslp_hpa": round(min(f["mslp_hpa"] for f in fx), 1),
        "onset_standard_h": num(std[0]),
        "completion_standard_h": num(std[1]),
        "onset_hart_h": num(hart[0]),
        "completion_hart_h": num(hart[1]),
        "class_sequence": class_seq_str(class_runs(fx)),
        "fsu_number": None,
        "fsu": None,
    }


def save_small(im: Image.Image, dest: Path) -> None:
    """PNG with a 256-color palette (no dithering): about a quarter of the
    RGB size for these flat-colored plots, with no visible change."""
    im.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(dest, optimize=True)


def save_phase(src: Path, dest: Path) -> None:
    """phase.png downscaled to PHASE_WIDTH to keep the repository small."""
    im = Image.open(src).convert("RGB")
    h = round(im.height * PHASE_WIDTH / im.width)
    save_small(im.resize((PHASE_WIDTH, h), Image.LANCZOS), dest)


# ------------------------------------------------------------------ FSU
class Polite:
    """HTTP GET for the FSU server: one request per FSU_MIN_INTERVAL_S at
    most, a User-Agent naming this repository, https first and then http
    (remembering the scheme that answered), never raising."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.last = 0.0
        self.scheme: str | None = None
        self.requests = 0

    def get(self, path: str) -> bytes | None:
        for scheme in ([self.scheme] if self.scheme else ["https", "http"]):
            wait = self.last + FSU_MIN_INTERVAL_S - time.time()
            if wait > 0:
                time.sleep(wait)
            url = f"{scheme}://{FSU_HOST}/{path}"
            self.requests += 1
            try:
                r = self.session.get(url, timeout=30)
            except requests.RequestException as exc:
                log(f"  FSU: {url}: {type(exc).__name__}")
                continue
            finally:
                self.last = time.time()
            if r.status_code == 200:
                self.scheme = scheme
                return r.content
            log(f"  FSU: {url}: HTTP {r.status_code}")
            if r.status_code == 404:
                self.scheme = scheme
                return None
        return None

    def fetch(self, path: str, dest: Path) -> Path | None:
        """dest if it is already there, else download it; None on failure."""
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        data = self.get(path)
        if not data:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        tmp.rename(dest)
        return dest


FSU = Polite()


def fsu_dir(cycle: str) -> str:
    return f"{FSU_DIR}/{cycle[2:]}"


def fsu_page(cycle: str, n: int) -> str:
    return f"http://{FSU_HOST}/{fsu_dir(cycle)}/{n}.html"


def map_frame(png: Path) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) of the colored map in alltrack.png: the longest run
    of rows that are mostly saturated color, and the columns saturated over
    most of that run."""
    try:
        a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    except Exception:
        return None
    sat = (a.max(axis=2) - a.min(axis=2)) > 60
    rows = sat.sum(axis=1) > 0.6 * a.shape[1]
    best, start = (0, 0), None
    for y, on in enumerate(np.append(rows, False)):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start > best[1] - best[0]:
                best = (start, y)
            start = None
    y0, y1 = best
    if y1 - y0 < 100:
        return None
    cols = np.flatnonzero(sat[y0:y1].sum(axis=0) > 0.6 * (y1 - y0))
    if cols.size < 100:
        return None
    return int(cols[0]), y0, int(cols[-1]) + 1, y1


def fsu_cyclones(cycle: str, cache: Path | None = None) -> list[tuple[int, float, float]]:
    """[(number, lat, lon), ...] from the clickable map of the FSU GFS page
    for the cycle: the center of each <area> square, converted with the
    map calibration (checked against the frame of alltrack.png when it can
    be fetched). Existing cyclones sit at their analysis position, future
    ones where FSU first finds them. Empty if the page cannot be read."""
    cache = cache or OUT / "cache" / cycle / "fsu"
    idx = FSU.fetch(f"{fsu_dir(cycle)}/index.html", cache / "index.html")
    if idx is None:
        log(f"FSU: no page for {cycle[2:]}")
        return []
    html = idx.read_text(errors="replace")
    x0, y0, x1, y1 = MAP_FRAME
    xl0, px_lon, yeq, px_lat = X_LON0, PX_PER_DEG_LON, Y_EQ, PX_PER_DEG_LAT
    m = re.search(r"<img[^>]*src=[\"']?([^\"'\s>]*alltrack\.png)", html, re.I)
    if m:
        png = FSU.fetch(f"{fsu_dir(cycle)}/alltrack.png", cache / "alltrack.png")
        fr = map_frame(png) if png else None
        if fr and max(abs(p - q) for p, q in zip(fr, MAP_FRAME)) > 2:
            sx, sy = (fr[2] - fr[0]) / (x1 - x0), (fr[3] - fr[1]) / (y1 - y0)
            log(f"FSU: map frame {fr} differs from {MAP_FRAME}; rescaling the calibration")
            xl0, px_lon = fr[0] + (X_LON0 - x0) * sx, PX_PER_DEG_LON * sx
            yeq, px_lat = fr[1] + (Y_EQ - y0) * sy, PX_PER_DEG_LAT * sy
    out = []
    for area in re.findall(r"<area\b[^>]*>", html, re.I):
        c = re.search(r"coords\s*=\s*[\"']?([\d\s,.]+)", area, re.I)
        h = re.search(r"href\s*=\s*[\"']?[^\"'\s>]*?/?(\d+)\.html", area, re.I)
        if not c or not h:
            continue
        xy = [float(v) for v in c.group(1).replace(" ", "").split(",") if v]
        if len(xy) == 4:
            x, y = 0.5 * (xy[0] + xy[2]), 0.5 * (xy[1] + xy[3])
        elif len(xy) == 3:  # circle
            x, y = xy[0], xy[1]
        else:
            continue
        lat = (yeq - y) / px_lat
        lon = float(tc.wrap180((x - xl0) / px_lon))
        out.append((int(h.group(1)), round(lat, 2), round(lon, 2)))
    if not out:
        log("FSU: no <area> elements found on the page; the map layout may have changed")
    return sorted(set(out))


def build_compare(fsu1: Path, fsu2: Path, phase: Path, dest: Path) -> None:
    """The two FSU diagrams side by side (FSU_PANEL px each) above our
    phase diagram scaled to COMPARE_WIDTH, COMPARE_GAP px of white between."""
    tops = []
    for p in (fsu1, fsu2):
        im = Image.open(p).convert("RGB")
        if im.width != FSU_PANEL:
            im = im.resize((FSU_PANEL, round(im.height * FSU_PANEL / im.width)), Image.LANCZOS)
        tops.append(im)
    ours = Image.open(phase).convert("RGB")
    ours = ours.resize((COMPARE_WIDTH, round(ours.height * COMPARE_WIDTH / ours.width)), Image.LANCZOS)
    top_h = max(im.height for im in tops)
    out = Image.new("RGB", (COMPARE_WIDTH, top_h + COMPARE_GAP + ours.height), "white")
    out.paste(tops[0], (0, 0))
    out.paste(tops[1], (FSU_PANEL, 0))
    out.paste(ours, (0, top_h + COMPARE_GAP))
    save_small(out, dest)


def match_fsu(cycle: str, meta: dict, sdir: Path, cyclones: list, full_phase: Path | None) -> None:
    """Nearest FSU cyclone within MATCH_KM of the storm's first fix; fetch its
    diagrams and build compare.png. Updates meta in place."""
    lat, lon = meta["start"]["lat"], meta["start"]["lon"]
    best = min(((float(tc.gc_km(lat, lon, la, lo)), n, la, lo) for n, la, lo in cyclones), default=None)
    if best is None or best[0] > MATCH_KM:
        near = f"; nearest is {best[1]} at {best[0]:.0f} km" if best else ""
        log(f"{meta['name']}: no FSU cyclone within {MATCH_KM:.0f} km of {fmt_pos(lat, lon)}{near}")
        return
    d, n, la, lo = best
    got = {}
    for key, fname in (("phase1", f"{n}.phase1.zoom.png"), ("phase2", f"{n}.phase2.zoom.png"),
                       ("track", f"{n}.track.png")):
        got[key] = FSU.fetch(f"{fsu_dir(cycle)}/{fname}", sdir / f"fsu_{key}.png")
    meta["fsu_number"] = n
    meta["fsu"] = {"number": n, "lat": la, "lon": lo, "distance_km": round(d), "url": fsu_page(cycle, n)}
    log(f"{meta['name']}: FSU cyclone {n} at {fmt_pos(la, lo)}, {d:.0f} km from our first fix")
    if got["phase1"] and got["phase2"]:
        phase = full_phase if full_phase and full_phase.exists() else sdir / "phase.png"
        build_compare(got["phase1"], got["phase2"], phase, sdir / "compare.png")
    else:
        log(f"{meta['name']}: FSU diagrams for cyclone {n} not available; no compare.png")


# ------------------------------------------------------------------ outputs
def write_json(path: Path, obj) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def hstr(v) -> str:
    return "none" if v is None else f"{int(v)}"


def class_seq_str(runs: list) -> str:
    """'- 0-6, 0 12-42, ...': class code (- for no closed low) and hours."""
    return ", ".join(f"{'-' if c is None else c} {a}" + (f"-{b}" if b != a else "") for c, a, b in runs)


def write_summary(cycle: str, cdir: Path) -> None:
    metas = [json.loads(p.read_text()) for p in sorted(cdir.glob("*/meta.json"))]
    lines = [f"# CPS daily collection, GFS {cycle}", "",
             f"Storm-following phase diagrams from the {ymd_h(cycle)} GFS 0.25 degree run, from the seeds in "
             "watch.json (generated by collect_daily.py). Hours are forecast hours. Onset: first hour the 24 h "
             "mean B exceeds 10 m; completion: first hour from onset the 24 h mean -V_T^L is below 0. Standard: "
             "925-700 and 500-300 hPa with the steering-proxy B; Hart: 900-600 and 600-300 hPa with the "
             "track-motion B.", "",
             "| Storm | FSU | Start position | MSLP (hPa) | Track (h) | Class sequence (h) | Onset std | "
             "Completion std | Onset Hart | Completion Hart |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    lost = []
    for m in metas:
        if m["status"] != "ok":
            lost.append(m)
            continue
        fsu = f"[{m['fsu_number']}]({m['fsu']['url']})" if m.get("fsu") else "none"
        s = m["start"]
        start = fmt_pos(s["lat"], s["lon"]) + (f" (+{m['start_fhr']} h)" if m["start_fhr"] else "")
        lines.append(f"| [{m['name']}]({m['name']}/) | {fsu} | {start} | {s['mslp_hpa']:.0f} | "
                     f"{m['start_fhr']}-{m['end_fhr']} | {m['class_sequence']} | "
                     f"{hstr(m['onset_standard_h'])} | {hstr(m['completion_standard_h'])} | "
                     f"{hstr(m['onset_hart_h'])} | {hstr(m['completion_hart_h'])} |")
    lines += ["", "Class codes (HCPSclass at the center): "
              + ", ".join(f"{k} {n}" for k, n in enumerate(tc.CLASS_SHORT)) + "; - no closed low."]
    for m in metas:
        if m.get("note"):
            lines += ["", f"{m['name']}: {m['note']}; its track stops at +{m['end_fhr']} h."]
        if m.get("ended"):
            lines += ["", f"{m['name']}: {m['ended']}."]
    for m in lost:
        lines += ["", f"{m['name']}: {m['status']}. {m.get('reason', '')}".rstrip()]
    disc = read_meta(cdir / "discovery.json")
    if disc:
        lows = disc.get("lows", [])
        lines += ["", "## Automatic discovery", "",
                  f"Closed lows at 0 h below {disc['mslp_below_hpa']:.0f} hPa north of {disc['lat_above']:g}N, one "
                  f"per system (minima within {AUTO_SYSTEM_KM:.0f} km of a deeper one dropped), not within "
                  f"{AUTO_KNOWN_KM:.0f} km of a watched storm; at most {disc['max_per_day']} new storms per day."]
        if not lows:
            lines += ["", "No such low this cycle."]
        else:
            lines += ["", "| Position | MSLP (hPa) | Basin | Result |", "|---|---|---|---|"]
            for low in lows:
                act = low.get("action")
                res = {"added": f"added as {low.get('storm')}",
                       "known": f"skipped, {low.get('distance_km')} km from {low.get('storm')}",
                       "cap": f"skipped, daily cap of {disc['max_per_day']} reached"}.get(act, act)
                lines.append(f"| {fmt_pos(low['lat'], low['lon'])} | {low['mslp_hpa']:.2f} | {low['basin']} | "
                             f"{res} |")
    text = "\n".join(lines) + "\n"
    p = cdir / "summary.md"
    if not p.exists() or p.read_text() != text:
        p.write_text(text)


def update_log(path: Path, rows: list[tuple]) -> None:
    """data/log.csv: one row per (cycle, storm); a rerun replaces its rows."""
    head = ["cycle", "storm", "fsu_number", "status"]
    old = []
    if path.exists():
        with path.open() as fh:
            old = [tuple(r) for r in list(csv.reader(fh))[1:] if r]
    new = {(r[0], r[1]): tuple("" if v is None else str(v) for v in r) for r in rows}
    merged = [new.pop((r[0], r[1]), r) for r in old] + list(new.values())
    if merged != old or not path.exists():
        with path.open("w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(head)
            wr.writerows(merged)


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycle", help="YYYYMMDDHH (default: today's 12 UTC run, or the newest 12 UTC run with the "
                                    "last requested hour posted)")
    ap.add_argument("--hours", type=int, nargs="+", default=DEFAULT_HOURS, help="forecast hours (default 0 to 198 "
                                                                                 "step 6)")
    ap.add_argument("--data-dir", type=Path, default=DATA, help="collection root (default realtime/data)")
    ap.add_argument("--watch", type=Path, default=WATCH, help="watch list (default realtime/watch.json)")
    ap.add_argument("--force", action="store_true", help="recompute storms already collected for the cycle")
    ap.add_argument("--no-fsu", action="store_true", help="skip the FSU matching")
    a = ap.parse_args(argv)
    hours = sorted(set(a.hours))
    cycle = a.cycle or default_cycle(hours[-1])
    if not re.fullmatch(r"\d{10}", cycle):
        raise SystemExit(f"--cycle {cycle!r}: expected YYYYMMDDHH")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"cycle={cycle}\n")
    data_dir = a.data_dir.resolve()
    cdir = data_dir / cycle
    workdir = OUT / cycle
    watch = json.loads(a.watch.read_text())
    storms = watch["storms"]
    log(f"cycle {cycle}, {len(hours)} hours, data in {data_dir}")

    jobs, done = [], []
    for st in storms:
        if not st.get("active", True):
            continue
        mp = cdir / st["name"] / "meta.json"
        if mp.exists() and not a.force and json.loads(mp.read_text()).get("status") == "ok":
            log(f"{st['name']}: already collected for {cycle}; reusing (--force recomputes)")
            done.append(st)
            continue
        seed = derive_seed(st, cycle, data_dir)
        log(f"{st['name']}: seed {seed['lat']:.2f},{seed['lon']:.2f} at +{seed['fhr0']} h"
            + (f" to +{seed['fhr1']} h" if seed["fhr1"] is not None else "") + f" ({seed['source']})")
        jobs.append(dict(name=st["name"], seed=seed, entry=st))

    disc_path = cdir / "discovery.json"
    discover = 0 in hours and (a.force or not disc_path.exists())
    if 0 not in hours:
        log("no 0 h frame requested; no automatic discovery")
    elif not discover:
        log(f"automatic discovery already done for {cycle} ({disc_path.name}; --force redoes it)")
    disc: dict | None = None
    merged_done: dict[str, tuple[str, float]] = {}

    def at_zero(f: dict, p: dict, jobs_now: list[dict]) -> list[dict]:
        """At the 0 h frame: end the newer of two active storms within MERGE_KM,
        then add the deep lows no watched storm covers."""
        nonlocal disc
        by_name = {j["name"]: j for j in jobs_now}
        done_names = {st["name"] for st in done}
        active, known = [], []  # (name, lat, lon)
        for st in storms:
            name = st["name"]
            if name in by_name:
                j = by_name[name]
                fx = j["track"].fixes
                if fx and fx[0]["fhr"] == 0:
                    active.append((name, fx[0]["lat"], fx[0]["lon"]))
                elif j["seed"]["fhr0"] == 0:  # lost at 0 h: inactive from this cycle
                    known.append((name, j["seed"]["lat"], j["seed"]["lon"]))
            elif name in done_names:
                pz = pos_zero(read_meta(cdir / name / "meta.json"))
                if pz:
                    active.append((name, *pz))
            elif st.get("ended_cycle") == cycle:
                pz = pos_zero(read_meta(cdir / name / "meta.json"))
                if pz is None and st.get("cycle") == cycle and int(st.get("fhr0") or 0) == 0:
                    pz = (float(st["lat"]), float(st["lon"]))
                if pz:
                    known.append((name, *pz))
            elif not st.get("active", True) and not st.get("ended_cycle"):
                # stopped by hand: keep its low from coming back while its last track covers this time
                sd = derive_seed(st, cycle, data_dir)
                if sd["source"].startswith("track of") and sd["fhr0"] == 0:
                    known.append((name, sd["lat"], sd["lon"]))
        merged: set[str] = set()
        for k, (name, la, lo) in enumerate(active):
            for older, la0, lo0 in active[:k]:
                d = float(tc.gc_km(la, lo, la0, lo0))
                if older in merged or d >= MERGE_KM:
                    continue
                merged.add(name)
                log(f"{name}: at 0 h {d:.0f} km from {older} ({fmt_pos(la0, lo0)}); merged into {older}")
                if name in by_name:
                    by_name[name]["merged_into"] = (older, d)
                    by_name[name]["track"].done = True
                else:
                    merged_done[name] = (older, d)
                break
        known += active
        if not discover:
            return []
        day = cycle[2:8]
        taken = [int(m.group(1)) for st in storms
                 if (m := re.fullmatch(rf"{AUTO_PREFIX}{day}_(\d+)", st["name"]))]
        room = max(AUTO_MAX_PER_DAY - len(taken), 0)
        serial = max(taken, default=0)
        lows = deep_lows(f)
        prev = read_meta(disc_path) or {}  # a --force rerun: storms this cycle's discovery added before
        prev_added = {low.get("storm") for low in prev.get("lows", []) if low.get("action") == "added"}
        new_jobs = []
        for low in lows:
            near = min(((float(tc.gc_km(low["lat"], low["lon"], la, lo)), n) for n, la, lo in known), default=None)
            where = f"{fmt_pos(low['lat'], low['lon'])} {low['mslp_hpa']:.2f} hPa ({low['basin']})"
            if near and near[0] < AUTO_KNOWN_KM and near[1] in prev_added:
                low.update(action="added", storm=near[1])
                log(f"discovery: {where}: added as {near[1]} by an earlier run of {cycle}")
                continue
            if near and near[0] < AUTO_KNOWN_KM:
                low.update(action="known", storm=near[1], distance_km=round(near[0]))
                log(f"discovery: {where}: {near[0]:.0f} km from {near[1]}; not added")
                continue
            if room == 0:
                low.update(action="cap")
                log(f"discovery: {where}: not added, {AUTO_MAX_PER_DAY} AUTO storms for {day} reached")
                continue
            serial += 1
            room -= 1
            name = f"{AUTO_PREFIX}{day}_{serial:02d}"
            low.update(action="added", storm=name)
            st = {"name": name, "lat": low["lat"], "lon": low["lon"], "cycle": cycle, "fhr0": 0, "fhr1": None,
                  "notes": f"Found automatically at 0 h of {cycle}: {low['mslp_hpa']:.2f} hPa, {low['basin']}.",
                  "active": True}
            storms.append(st)
            known.append((name, low["lat"], low["lon"]))
            seed = dict(lat=low["lat"], lon=low["lon"], fhr0=0, fhr1=None, fhr1_expired=False,
                        source=f"automatic discovery at 0 h of {cycle}")
            new_jobs.append(dict(name=name, seed=seed, entry=st, auto=low))
            log(f"discovery: {where}: added as {name}")
        disc = {"cycle": cycle, "mslp_below_hpa": AUTO_MSLP_HPA, "lat_above": AUTO_LAT_MIN,
                "max_per_day": AUTO_MAX_PER_DAY, "lows": lows}
        log(f"discovery: {len(lows)} closed lows below {AUTO_MSLP_HPA:.0f} hPa north of {AUTO_LAT_MIN:g}N, "
            f"{len(new_jobs)} added")
        return new_jobs

    skipped: set[int] = set()
    if jobs or discover:
        skipped = track_storms(cycle, hours, jobs, workdir, at_zero)
        if len(skipped) == len(hours):
            log(f"no frame of {cycle} could be fetched; nothing written")
            return 1
    if disc is not None:
        cdir.mkdir(parents=True, exist_ok=True)
        write_json(disc_path, disc)

    log_rows = []
    metas: dict[str, tuple[dict, Path]] = {}
    for j in jobs:
        st, s, name = j["entry"], j["seed"], j["name"]
        sdir = cdir / name
        current = hours_between(st["cycle"], cycle) >= 0  # not a backfill behind the entry's cycle
        tm = j["track"].merged
        if tm and not j["track"].fixes:  # stopped for another track at its first frame
            j["merged_into"] = (tm[0], tm[2])
        if j.get("merged_into"):
            older, d = j["merged_into"]
            at = f"+{tm[1]} h" if tm else "0 h"
            reason = f"At {at} of {cycle} within {d:.0f} km of {older}; merged into {older}, marked inactive."
            sdir.mkdir(parents=True, exist_ok=True)
            write_json(sdir / "meta.json", {"cycle": cycle, "name": name, "status": "merged", "reason": reason,
                                            "seed": {k: s[k] for k in ("lat", "lon", "fhr0", "fhr1", "source")},
                                            "fsu_number": None})
            if current:
                end_note(st, cycle, f"merged into {older}" + (f" at {at}" if tm else ""))
            log_rows.append((cycle, name, None, "merged"))
            continue
        if not j["track"].fixes:
            if s["fhr0"] in skipped:
                log(f"{name}: the frame at +{s['fhr0']} h could not be fetched; left active")
                log_rows.append((cycle, name, None, "error"))
                continue
            reason = (f"No closed low within {tc.SEED_KM:.0f} km of the seed {fmt_pos(s['lat'], s['lon'])} at "
                      f"+{s['fhr0']} h of {cycle} ({s['source']}); marked inactive.")
            log(f"{name}: {reason}")
            sdir.mkdir(parents=True, exist_ok=True)
            write_json(sdir / "meta.json", {"cycle": cycle, "name": name, "status": "lost", "reason": reason,
                                            "seed": {k: s[k] for k in ("lat", "lon", "fhr0", "fhr1", "source")},
                                            "fsu_number": None})
            if current:
                end_note(st, cycle, f"no closed low within {tc.SEED_KM:.0f} km of the seed")
            log_rows.append((cycle, name, None, "lost"))
            continue
        sdir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workdir / f"track_{name}.csv", sdir / "track.csv")
        save_phase(workdir / f"phase_{name}.png", sdir / "phase.png")
        meta = build_meta(cycle, j)
        if j["track"].end_reason:
            meta["track_end"] = j["track"].end_reason
        if tm:
            meta["merged_into"] = {"name": tm[0], "fhr": tm[1], "distance_km": round(tm[2])}
            meta["note"] = f"merged into {tm[0]} at +{tm[1]} h"
            log(f"{name}: {meta['note']}")
            if current and tm[1] <= NEXT_CYCLE_H:
                end_note(st, cycle, meta["note"])
        found = j.get("auto") or next((low for low in (disc or read_meta(disc_path) or {}).get("lows", [])
                                       if low.get("action") == "added" and low.get("storm") == name), None)
        if found:
            meta["discovered"] = {k: found[k] for k in ("lat", "lon", "mslp_hpa", "basin")}
        metas[name] = (meta, workdir / f"phase_{name}.png")
        fx = j["track"].fixes[0]
        if current:
            st.update(lat=round(fx["lat"], 2), lon=round(fx["lon"], 2), cycle=cycle, fhr0=fx["fhr"], fhr1=s["fhr1"])
            if s["fhr1_expired"]:
                st["notes"] = (st.get("notes", "") + f" fhr1 cap passed by {cycle}; tracked to the end.").strip()
            if st.get("active", True) and fx["fhr"] == 0 and filled(data_dir, cycle, name, fx["mslp_hpa"]):
                meta["ended"] = (f"filled: 0 h MSLP above {FILL_HPA:.0f} hPa in {FILL_CYCLES} consecutive "
                                 "cycles; marked inactive")
                log(f"{name}: {meta['ended']}")
                end_note(st, cycle, "filled")
    for st in done:
        name = st["name"]
        mp = cdir / name / "meta.json"
        meta = json.loads(mp.read_text())
        if name in merged_done:
            older, d = merged_done[name]
            meta.update(status="merged", reason=f"At 0 h of {cycle} within {d:.0f} km of {older}; merged into "
                                                f"{older}, marked inactive.")
            write_json(mp, meta)
            if hours_between(st["cycle"], cycle) >= 0:
                end_note(st, cycle, f"merged into {older}")
            log_rows.append((cycle, name, None, "merged"))
            continue
        metas[name] = (meta, workdir / f"phase_{name}.png")

    cyclones = None
    for name, (meta, full_phase) in metas.items():
        sdir = cdir / name
        need = meta.get("fsu_number") is None or not (sdir / "compare.png").exists()
        if need and not a.no_fsu:
            if cyclones is None:
                try:
                    cyclones = fsu_cyclones(cycle)
                    log(f"FSU: {len(cyclones)} cyclones on the {cycle[2:]} map")
                except Exception as exc:  # never fail the run for FSU
                    log(f"FSU: could not read the map ({type(exc).__name__}: {exc}); continuing without FSU")
                    cyclones = []
            try:
                match_fsu(cycle, meta, sdir, cyclones, full_phase)
            except Exception as exc:
                log(f"{name}: FSU matching failed ({type(exc).__name__}: {exc}); continuing")
        write_json(sdir / "meta.json", meta)
        log_rows.append((cycle, name, meta.get("fsu_number"), "merged" if meta.get("merged_into") else "ok"))
    log(f"FSU: {FSU.requests} requests this run")

    write_json(a.watch, watch)
    if cdir.exists():
        write_summary(cycle, cdir)
    update_log(data_dir / "log.csv", log_rows)
    log(f"done: {cdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
