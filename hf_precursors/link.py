"""Link detected lows into tracks, then label the tracks from the archive.

LINKING. Greedy nearest-neighbour between consecutive synoptic times, with a
motion first guess once a track has two points: a low is expected to continue
its last displacement, and the candidate nearest that expectation wins,
provided it is within a plausible step. This is the standard approach and it
is much safer here than in the earlier backward tracker, because every low at
the next time has already been detected -- the linker chooses among real
candidates rather than searching a radius and taking whatever minimum it
finds.

A track is not required to be continuous through a missing detection: a low
that drops below the depth floor for one step and returns is treated as two
tracks. That is conservative and it is preferred to bridging gaps with
guesses.

LABELLING. A track is a hurricane-force track if any archive fix categorized
HF lies within MATCH_KM and MATCH_HOURS of any of its points. The archive
supplies the label and nothing else -- no position, no pressure, no timing
beyond the match. The onset recorded is the track's own time nearest that
first matching fix, so every time in the table comes from one clock.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import build_hf_lows as bh  # noqa: E402
from archive_cases import build_cases  # noqa: E402
from pressure_field import great_circle_km  # noqa: E402

MAX_LINK_KM = 600.0        # one 6 h step, about 54 kt
GUESS_RADIUS_KM = 350.0    # once a motion exists, how far from the guess
MATCH_KM = 750.0
MATCH_HOURS = 6.0
MIN_TRACK_POINTS = 3       # 18 h; shorter is not a life cycle
import os
# How long a low may go undetected and still be the same track.
# Breaking on every miss fragments one storm into several and makes
# measured lifetimes shorter than the storms are.
MAX_GAP_H = float(os.environ.get("MAX_GAP_H", "6"))


def load_instances(paths):
    rows = []
    for p in paths:
        with open(p) as fh:
            for r in csv.DictReader(fh):
                r["when"] = datetime.strptime(r["when"], "%Y-%m-%d %H").replace(
                    tzinfo=timezone.utc)
                for k in ("lat", "lon", "p_centre", "depth", "scale_km",
                          "grad_hpa_per_100km", "vg_kt", "wind_kt", "gust_kt",
                          "wind_dist_km", "fit_rms"):
                    r[k] = float(r[k]) if r[k] not in ("", "nan") else np.nan
                rows.append(r)
    rows.sort(key=lambda r: r["when"])
    return rows


def link(rows):
    """Assign a track id to every instance."""
    by_time = {}
    for r in rows:
        by_time.setdefault(r["when"], []).append(r)
    times = sorted(by_time)

    next_id = 0
    live = []          # (track_id, last_row, prev_row or None)
    for t in times:
        current = by_time[t]
        claimed = set()
        still = []
        for tid, last, prev in live:
            if (t - last["when"]) > timedelta(hours=MAX_GAP_H, minutes=1):
                continue                                  # track ended
            if prev is None:
                glat, glon, radius = last["lat"], last["lon"], MAX_LINK_KM
            else:
                dlat = last["lat"] - prev["lat"]
                dlon = ((last["lon"] - prev["lon"] + 180.0) % 360.0) - 180.0
                glat, glon = last["lat"] + dlat, (last["lon"] + dlon) % 360.0
                radius = GUESS_RADIUS_KM
            best, best_d = None, np.inf
            for c in current:
                if id(c) in claimed:
                    continue
                d = great_circle_km(glat, glon, c["lat"], c["lon"])
                if d < min(radius, best_d):
                    best, best_d = c, d
            if best is not None:
                claimed.add(id(best))
                best["track"] = tid
                still.append((tid, best, last))
        for c in current:
            if id(c) not in claimed:
                c["track"] = next_id
                still.append((next_id, c, None))
                next_id += 1
        live = still
    return rows


def label(rows):
    """Mark each track that matches an archive hurricane-force fix."""
    cases = [c for c in build_cases() if c.basin == "pac" and c.season >= 2020]
    by_track = {}
    for r in rows:
        by_track.setdefault(r["track"], []).append(r)

    hf, onset = set(), {}
    for c in cases:
        best, best_key = None, None
        for tid, pts in by_track.items():
            for p in pts:
                if abs((p["when"] - c.onset).total_seconds()) > MATCH_HOURS * 3600:
                    continue
                d = great_circle_km(c.lat, c.lon % 360.0, p["lat"], p["lon"])
                if d <= MATCH_KM and (best is None or d < best):
                    best, best_key = d, (tid, p["when"])
        if best_key is not None:
            tid, when = best_key
            hf.add(tid)
            if tid not in onset or when < onset[tid]:
                onset[tid] = when
    return hf, onset, len(cases)


def summarize(rows, hf, onset):
    """One row per track: its life cycle in the quantities under test."""
    by_track = {}
    for r in rows:
        by_track.setdefault(r["track"], []).append(r)

    out = []
    for tid, pts in by_track.items():
        if len(pts) < MIN_TRACK_POINTS:
            continue
        pts.sort(key=lambda r: r["when"])
        peak = min(pts, key=lambda r: r["p_centre"])
        i_peak = pts.index(peak)
        # State 24 h before the track's own deepest moment: the same point in
        # every storm's life, which is what the earlier design could not do.
        pre = pts[i_peak - 4] if i_peak >= 4 else None
        winds = [p["wind_kt"] for p in pts if np.isfinite(p["wind_kt"])]
        gusts = [p["gust_kt"] for p in pts if np.isfinite(p["gust_kt"])]
        out.append({
            "track": tid, "hf": int(tid in hf),
            "onset": onset[tid].strftime("%Y-%m-%d %H") if tid in onset else "",
            "n": len(pts),
            "start": pts[0]["when"].strftime("%Y-%m-%d %H"),
            "peak_when": peak["when"].strftime("%Y-%m-%d %H"),
            "peak_lat": peak["lat"], "peak_lon": peak["lon"],
            "min_p": peak["p_centre"], "peak_depth": peak["depth"],
            "peak_scale_km": peak["scale_km"],
            "peak_grad": peak["grad_hpa_per_100km"], "peak_vg_kt": peak["vg_kt"],
            "max_wind_kt": max(winds) if winds else np.nan,
            "max_gust_kt": max(gusts) if gusts else np.nan,
            "peak_wind_dist_km": peak["wind_dist_km"],
            "pre_depth": pre["depth"] if pre else np.nan,
            "pre_scale_km": pre["scale_km"] if pre else np.nan,
            "pre_grad": pre["grad_hpa_per_100km"] if pre else np.nan,
            "pre_vg_kt": pre["vg_kt"] if pre else np.nan,
            "pre_p": pre["p_centre"] if pre else np.nan,
            "pre_lat": pre["lat"] if pre else np.nan,
            "deepen24": (peak["p_centre"] - pre["p_centre"]) if pre else np.nan,
            "month": peak["when"].month,
            "season": bh.season_from_date(int(peak["when"].strftime("%Y%m%d%H"))),
        })
    return out


def main():
    paths = sorted((HERE / "data").glob("scan_*.csv"))
    print(f"reading {len(paths)} season scans", flush=True)
    rows = load_instances(paths)
    print(f"{len(rows)} low-instances", flush=True)
    rows = link(rows)
    hf, onset, n_cases = label(rows)
    tracks = summarize(rows, hf, onset)
    n_hf = sum(t["hf"] for t in tracks)
    print(f"{len(tracks)} tracks of >= {MIN_TRACK_POINTS} points, "
          f"{n_hf} matched to an archive hurricane-force event "
          f"({n_hf}/{n_cases} of the archive's own cases found)", flush=True)

    dst = HERE / "data" / "tracks.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(tracks[0].keys()))
        w.writeheader()
        w.writerows(tracks)
    print(f"wrote {dst.name}", flush=True)

    # The linked instances themselves, so any lead time can be read off
    # later without re-linking. Track summaries fix one lead; the lead-time
    # study needs every point.
    keep = {t["track"] for t in tracks}
    inst = HERE / "data" / "instances.csv"
    cols = ["track", "hf", "when", "lat", "lon", "p_centre", "p_env", "depth",
            "scale_km", "fit_rms", "grad_hpa_per_100km", "vg_kt", "vgeo_kt",
            "wind_kt", "gust_kt", "wind_dist_km"]
    with open(inst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            if r.get("track") in keep:
                w.writerow(dict(r, hf=int(r["track"] in hf),
                                when=r["when"].strftime("%Y-%m-%d %H")))
    print(f"wrote {inst.name}", flush=True)


if __name__ == "__main__":
    main()
