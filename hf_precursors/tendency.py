"""Add the pressure tendency each record was carrying when it was observed.

The first analysis pass compared cases and controls on depth, scale and
gradient alone and found the cases slightly WEAKER than their matched
controls -- the wrong sign. The likely reason is that life-cycle stage is
not matched: a case is a low 24 h before it produces hurricane force, so it
is still developing, while a control drawn at a random time is often at or
past its own peak. At equal depth those are different animals, and what
separates them is not how deep they are but which way they are going.

So each record gains the 12 and 24 h change in its own central pressure,
tracked back through ERA5 from where the low actually was rather than read
off a fixed point. Negative is deepening.

This is the variable the whole compactness argument turns on: a compact low
falling fast has a large gradient of pressure tendency, which is the
isallobaric forcing that spins up the low-level jet, and that is a different
quantity from the depth it has reached so far.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import era5  # noqa: E402
from pressure_field import describe_low  # noqa: E402

STEP_H = 6.0
MAX_STEP_KM = 550.0


def back_pressure(lat, lon, when, hours):
    """Central pressure of the same low `hours` earlier, and how far the
    track moved in total. Returns (pressure, path_km) or (nan, nan)."""
    cur_lat, cur_lon, t = float(lat), float(lon) % 360.0, when
    path = 0.0
    p = np.nan
    for _ in range(int(round(hours / STEP_H))):
        t = t - timedelta(hours=STEP_H)
        try:
            field = era5.mslp(t)
        except Exception:                              # noqa: BLE001
            return np.nan, np.nan
        d = describe_low(field, cur_lat, cur_lon, refine_km=MAX_STEP_KM)
        path += d["shift_km"]
        cur_lat, cur_lon, p = d["lat"], d["lon"], d["p_centre"]
    return p, path


def annotate(src, dst, lags=(12.0, 24.0)):
    """Add a tendency column per lag in `lags` to every row of `src`.

    Each lag is walked back independently rather than reusing the 12 h
    track for the 24 h one: the tracker can follow a different low over a
    longer walk, and two short walks agreeing is not the same evidence as
    one long walk. The longest lag's path length is kept so a track that
    wandered can be filtered afterwards.
    """
    with open(src) as fh:
        rows = list(csv.DictReader(fh))
    cols = [f"tend{int(h)}" for h in lags]
    out_fields = [c for c in rows[0].keys() if c not in cols + ["back_path_km"]]
    out_fields += cols + ["back_path_km"]

    t0 = time.time()
    for n, r in enumerate(rows, 1):
        when = datetime.strptime(r["when"], "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        p_now = float(r["p_centre"])
        longest = np.nan
        for h in lags:
            p_then, path = back_pressure(r["lat"], r["lon"], when, h)
            r[f"tend{int(h)}"] = round(p_now - p_then, 1) if np.isfinite(p_then) else ""
            if h == max(lags):
                longest = path
        r["back_path_km"] = round(longest, 0) if np.isfinite(longest) else ""
        if n % 200 == 0:
            rate = (time.time() - t0) / n
            print(f"  {n}/{len(rows)}  {time.time() - t0:.0f}s  "
                  f"eta {rate * (len(rows) - n):.0f}s", flush=True)

    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {Path(dst).name}: {len(rows)} rows", flush=True)


def main():
    args = sys.argv[1:]
    if args:
        src, dst = Path(args[0]), Path(args[1])
        lags = tuple(float(x) for x in args[2:]) or (12.0, 24.0)
    else:
        src = HERE / "data" / "matched.csv"
        dst = HERE / "data" / "matched_tend.csv"
        lags = (12.0, 24.0)
    annotate(src, dst, lags)


if __name__ == "__main__":
    main()
