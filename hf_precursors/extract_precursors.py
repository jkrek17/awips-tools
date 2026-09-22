"""Compute the literature's ingredients for a sample of lows.

Labels each sampled instance with whether hurricane force follows within
24 and 48 h, so a predictor is scored against the event rather than against
a structural proxy for it.

SAMPLING. Every instance inside the 48 h before an archive hurricane-force
onset, plus a random draw from tracks that never reached one. Positives are
taken at every lead in that window rather than at one lead, so the same fit
can be read at 6, 12, 24 and 48 h without a separate extraction each time.

COST. Geopotential is the expensive field -- the store chunks a whole
timestep of all 37 levels together, so asking for seven costs the same as
asking for all of them. Instances are therefore grouped by time and each
timestep is read once however many lows sit in it.
"""
from __future__ import annotations

import csv
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import era5  # noqa: E402
import precursors as pre  # noqa: E402
from pressure_field import Field  # noqa: E402

LEVELS = (1000, 925, 850, 700, 500, 400, 300)
POSITIVE_WINDOW_H = 48
MAX_POSITIVES = 1100
MAX_NEGATIVES = 1600


def load(tag="_d5"):
    with open(HERE / "data" / f"instances{tag}.csv") as fh:
        inst = list(csv.DictReader(fh))
    with open(HERE / "data" / f"tracks{tag}.csv") as fh:
        onsets = {r["track"]: r["onset"] for r in csv.DictReader(fh)
                  if r["onset"]}
    for r in inst:
        r["when"] = datetime.strptime(r["when"], "%Y-%m-%d %H").replace(
            tzinfo=timezone.utc)
        r["lat"] = float(r["lat"])
        r["lon"] = float(r["lon"])
        r["hf"] = int(r["hf"])
    return inst, {k: datetime.strptime(v, "%Y-%m-%d %H").replace(
        tzinfo=timezone.utc) for k, v in onsets.items()}


def choose(inst, onsets, seed=41):
    rng = random.Random(seed)
    pos, neg = [], []
    for r in inst:
        onset = onsets.get(r["track"])
        if onset is not None:
            lead = (onset - r["when"]).total_seconds() / 3600.0
            if 0 <= lead <= POSITIVE_WINDOW_H:
                pos.append(dict(r, lead_h=lead,
                                hf24=int(lead <= 24), hf48=1))
        elif r["hf"] == 0:
            neg.append(dict(r, lead_h=np.nan, hf24=0, hf48=0))
    rng.shuffle(pos)
    rng.shuffle(neg)
    return pos[:MAX_POSITIVES] + neg[:MAX_NEGATIVES]


def compute(rows, chunk, nchunks):
    by_time = defaultdict(list)
    for r in rows:
        by_time[r["when"]].append(r)
    times = sorted(by_time)[chunk::nchunks]
    lats, lons = era5.axes()
    out, t0 = [], time.time()
    for n, when in enumerate(times, 1):
        try:
            mslp = era5.mslp(when)
            z = era5.heights(when, LEVELS)
            sst = era5.dataset()["sea_surface_temperature"].sel(
                time=era5._stamp(when), method="nearest").values
        except Exception as exc:                        # noqa: BLE001
            print(f"  {when}: {exc}", flush=True)
            continue
        for r in by_time[when]:
            la, lo = r["lat"], r["lon"]
            rec = dict(track=r["track"], when=when.strftime("%Y-%m-%d %H"),
                       lat=la, lon=lo, lead_h=r["lead_h"],
                       hf24=r["hf24"], hf48=r["hf48"],
                       depth=r["depth"], scale_km=r["scale_km"],
                       grad=r["grad_hpa_per_100km"], vg_kt=r["vg_kt"],
                       gust_kt=r["gust_kt"], p_centre=r["p_centre"])
            try:
                rec.update(pre.sector_pressures(mslp, la, lo))
                rec.update(pre.thickness_anomaly(z[1000], z[500], lats, lons, la, lo))
                rec.update(pre.trough_vector(z[500], lats, lons, la, lo))
                rec.update(pre.sst_gradient(sst, lats, lons, la, lo))
                rec.update(pre.cps_fields(z, lats, lons, la, lo))
            except Exception as exc:                    # noqa: BLE001
                print(f"  {when} {la},{lo}: {exc}", flush=True)
                continue
            out.append(rec)
        if n % 25 == 0:
            rate = (time.time() - t0) / n
            print(f"  chunk {chunk}: {n}/{len(times)} times, {len(out)} lows, "
                  f"eta {rate * (len(times) - n):.0f}s", flush=True)
    return out


def main():
    chunk, nchunks = int(sys.argv[1]), int(sys.argv[2])
    inst, onsets = load()
    rows = choose(inst, onsets)
    if chunk == 0:
        print(f"{len(rows)} sampled lows "
              f"({sum(r['hf48'] for r in rows)} within 48 h of an onset)",
              flush=True)
    out = compute(rows, chunk, nchunks)
    dst = HERE / "data" / f"precursors_{chunk}.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"chunk {chunk}: {len(out)} rows -> {dst.name}", flush=True)


if __name__ == "__main__":
    main()
