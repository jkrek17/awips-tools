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


# ------------------------------------------------------------------ tracking
def track_storms(cycle: str, hours: list[int], jobs: list[dict], workdir: Path) -> set[int]:
    """Follow every job's low through the run with track_cps's tracker (the
    frames are shared); sets job['track'] and job['events'], writes
    track_<NAME>.csv and phase_<NAME>.png (2400 px) to workdir. Returns the
    hours whose frame could not be fetched."""
    workdir.mkdir(parents=True, exist_ok=True)
    cache = OUT / "cache" / cycle
    for j in jobs:
        s = j["seed"]
        spec = f"{j['name']}:{s['lat']},{s['lon']}:{s['fhr0']}" + (f":{s['fhr1']}" if s["fhr1"] is not None else "")
        j["track"] = tc.Track(spec)
    tracks = [j["track"] for j in jobs]
    skipped: set[int] = set()
    t0 = time.time()
    log(f"tracking {', '.join(j['name'] for j in jobs)} through {len(hours)} frames of {cycle}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {h: pool.submit(g.get_grib, cycle, h, REGION, cache, "nomads", True) for h in hours}
        for fhr in hours:
            if all(t.done for t in tracks):
                for fu in futs.values():
                    fu.cancel()
                break
            try:
                grib = futs[fhr].result()
            except Exception as exc:  # a late hour may not be posted yet
                log(f"  f{fhr:03d}: skipped ({exc})")
                skipped.add(fhr)
                continue
            f = g.decode(grib, REGION, True)
            p = g.compute_products(f)
            p.update(g.compute_hart_bands(f))
            for t in tracks:
                tc.sample_frame(t, f, p, fhr, True)
            where = "; ".join(f"{t.name} {t.fixes[-1]['lat']:.1f},{t.fixes[-1]['lon']:.1f} "
                              f"{t.fixes[-1]['mslp_hpa']:.0f}" for t in tracks if t.fixes and t.fixes[-1]["fhr"] == fhr)
            log(f"  f{fhr:03d}: {time.time() - t0:.0f} s   {where}")
    for j in jobs:
        t = j["track"]
        j["events"] = {}
        if not t.fixes:
            continue
        tc.track_motion(t.fixes)
        tc.b_with_track_motion(t.fixes)
        tc.write_csv(workdir / f"track_{t.name}.csv", t.fixes)
        j["events"] = tc.plot_phase(workdir / f"phase_{t.name}.png", t.name, cycle, t.fixes, True)
    log(f"tracking done in {time.time() - t0:.0f} s")
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
    for m in lost:
        lines += ["", f"{m['name']}: {m['status']}. {m.get('reason', '')}".rstrip()]
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

    skipped: set[int] = set()
    if jobs:
        skipped = track_storms(cycle, hours, jobs, workdir)
        if len(skipped) == len(hours):
            log(f"no frame of {cycle} could be fetched; nothing written")
            return 1

    log_rows = []
    metas: dict[str, tuple[dict, Path]] = {}
    for j in jobs:
        st, s, name = j["entry"], j["seed"], j["name"]
        sdir = cdir / name
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
            if hours_between(st["cycle"], cycle) >= 0:
                st["active"] = False
                st["ended_cycle"] = cycle
                st["notes"] = (st.get("notes", "") + f" Inactive from {cycle}: no closed low within "
                               f"{tc.SEED_KM:.0f} km of the seed.").strip()
            log_rows.append((cycle, name, None, "lost"))
            continue
        sdir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workdir / f"track_{name}.csv", sdir / "track.csv")
        save_phase(workdir / f"phase_{name}.png", sdir / "phase.png")
        meta = build_meta(cycle, j)
        metas[name] = (meta, workdir / f"phase_{name}.png")
        if hours_between(st["cycle"], cycle) >= 0:
            fx = j["track"].fixes[0]
            st.update(lat=round(fx["lat"], 2), lon=round(fx["lon"], 2), cycle=cycle, fhr0=fx["fhr"], fhr1=s["fhr1"])
            if s["fhr1_expired"]:
                st["notes"] = (st.get("notes", "") + f" fhr1 cap passed by {cycle}; tracked to the end.").strip()
    for st in done:
        mp = cdir / st["name"] / "meta.json"
        metas[st["name"]] = (json.loads(mp.read_text()), workdir / f"phase_{st['name']}.png")

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
        log_rows.append((cycle, name, meta.get("fsu_number"), "ok"))
    log(f"FSU: {FSU.requests} requests this run")

    write_json(a.watch, watch)
    if cdir.exists():
        write_summary(cycle, cdir)
    update_log(data_dir / "log.csv", log_rows)
    log(f"done: {cdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
