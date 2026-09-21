"""Build the case and control table for Pacific 2020-2025.

Writes three files under `hf_precursors/data/`:

    cases.csv     one row per hurricane-force onset, describing the low
                  24 h BEFORE onset -- the moment a forecast would be made
    pool.csv      every low found at sampled times that is not an archive
                  event, the population controls are drawn from
    matched.csv   cases plus their matched controls, the analysis table

Each stage checkpoints to its own file and is skipped if that file is
already complete, so a long run can be resumed rather than restarted.
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import build_hf_lows as bh  # noqa: E402
import era5  # noqa: E402
from archive_cases import build_cases  # noqa: E402
from controls import (  # noqa: E402
    Excluder, archive_fixes, find_lows, track_back, sample_times,
    LEAD_HOURS, DEPTH_TOL, LAT_TOL,
)

DATA = HERE / "data"
# Draws per case when sampling control times. The matching is tight -- same
# season and month, depth within 5 hPa, latitude within 5 deg -- so a thin
# pool leaves most cases with no comparable low at all.
POOL_PER_CASE = int(os.environ.get("POOL_PER_CASE", "12"))
FIELDS = ["label", "id", "when", "lat", "lon", "p_centre", "p_env", "depth",
          "fit_depth", "scale_km", "fit_rms", "grad_hpa_per_100km",
          "vg_kt", "vgeo_kt", "max_step_km", "season", "month", "stratum"]


def row_from(desc, label, ident, season, month, stratum=""):
    return {
        "label": label, "id": ident,
        "when": desc["when"].strftime("%Y-%m-%d %H"),
        "lat": round(desc["lat"], 2), "lon": round(desc["lon"], 2),
        "p_centre": round(desc["p_centre"], 1), "p_env": round(desc["p_env"], 1),
        "depth": round(desc["depth"], 1), "fit_depth": round(desc["fit_depth"], 1),
        "scale_km": round(desc["scale_km"], 0), "fit_rms": round(desc["fit_rms"], 2),
        "grad_hpa_per_100km": round(desc["grad_hpa_per_100km"], 3),
        "vg_kt": round(desc["vg_kt"], 1), "vgeo_kt": round(desc["vgeo_kt"], 1),
        "max_step_km": round(desc.get("max_step_km", 0.0), 0),
        "season": season, "month": month, "stratum": stratum,
    }


def write(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def read(path):
    """Rows back from a checkpoint, with the keys the matching joins on
    restored to integers.

    csv gives every field back as a string, so a checkpointed case row
    would key on ("2020", 11) while a freshly built pool row keys on
    (2020, 11); the two never meet and every stratum comes back with no
    controls. Coercing here keeps that from depending on which stage was
    resumed.
    """
    if not path.exists():
        return None
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("label", "season", "month"):
            r[k] = int(r[k])
    return rows


def build_case_rows(cases):
    out, t0 = [], time.time()
    for n, c in enumerate(cases, 1):
        try:
            d = track_back(c.lat, c.lon, c.onset, hours=LEAD_HOURS)
        except Exception as exc:                      # noqa: BLE001
            print(f"  case {c.id} failed: {exc}", flush=True)
            continue
        if d is None or not np.isfinite(d["scale_km"]):
            continue
        out.append(row_from(d, 1, c.id, c.season, c.onset.month))
        if n % 25 == 0:
            print(f"  cases {n}/{len(cases)}  {time.time() - t0:.0f}s", flush=True)
    return out


def build_pool(cases, excluder, per_case=12):
    times = sample_times(cases, per_case=per_case)
    print(f"  {len(times)} sampled times", flush=True)
    out, t0 = [], time.time()
    for n, when in enumerate(times, 1):
        try:
            field = era5.mslp(when)
            lows = find_lows(field)
        except Exception as exc:                      # noqa: BLE001
            print(f"  {when} failed: {exc}", flush=True)
            continue
        for d in lows:
            if excluder.hits(when, d["lat"], d["lon"]):
                continue
            season = bh.season_from_date(int(when.strftime("%Y%m%d%H")))
            out.append(row_from(dict(d, when=when), 0,
                                f"pool_{when:%Y%m%d%H}_{d['lat']:.0f}_{d['lon']:.0f}",
                                season, when.month))
        if n % 50 == 0:
            print(f"  pool {n}/{len(times)}  {len(out)} lows  "
                  f"{time.time() - t0:.0f}s", flush=True)
    return out


def match(case_rows, pool_rows, per_case=3, seed=23):
    """Nearest matching on depth and latitude, within season and month.

    Controls are consumed without replacement so one unusually well-placed
    low cannot stand in for many cases and shrink the effective sample.
    """
    import random
    rng = random.Random(seed)
    by_key = {}
    for r in pool_rows:
        by_key.setdefault((r["season"], r["month"]), []).append(r)
    for v in by_key.values():
        rng.shuffle(v)

    used, out = set(), []
    for k, c in enumerate(case_rows):
        stratum = f"s{k:04d}"
        out.append(dict(c, stratum=stratum))
        cand = by_key.get((c["season"], c["month"]), [])
        picks = []
        for r in cand:
            if id(r) in used:
                continue
            if abs(float(r["depth"]) - float(c["depth"])) > DEPTH_TOL:
                continue
            if abs(float(r["lat"]) - float(c["lat"])) > LAT_TOL:
                continue
            picks.append(r)
            if len(picks) == per_case:
                break
        for r in picks:
            used.add(id(r))
            out.append(dict(r, stratum=stratum))
    return out


def main():
    cases = [c for c in build_cases()
             if c.basin == "pac" and c.season >= 2020]
    print(f"Pacific 2020-2025: {len(cases)} hurricane-force onsets", flush=True)

    case_path, pool_path, matched_path = (DATA / "cases.csv",
                                          DATA / "pool.csv",
                                          DATA / "matched.csv")

    case_rows = read(case_path)
    if case_rows is None:
        print(f"Describing each low {LEAD_HOURS:.0f} h before onset ...", flush=True)
        case_rows = build_case_rows(cases)
        write(case_path, case_rows)
    print(f"cases: {len(case_rows)}", flush=True)

    pool_rows = read(pool_path)
    if pool_rows is None:
        print("Building the control pool ...", flush=True)
        excluder = Excluder(archive_fixes())
        pool_rows = build_pool(cases, excluder, per_case=POOL_PER_CASE)
        write(pool_path, pool_rows)
    print(f"pool: {len(pool_rows)}", flush=True)

    matched = match(case_rows, pool_rows)
    write(matched_path, matched)
    n_ctrl = sum(1 for r in matched if int(r["label"]) == 0)
    print(f"matched: {len(matched)} rows, {len(matched) - n_ctrl} cases "
          f"and {n_ctrl} controls", flush=True)


if __name__ == "__main__":
    main()
