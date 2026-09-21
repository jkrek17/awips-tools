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


def main():
    src = HERE / "data" / "matched.csv"
    dst = HERE / "data" / "matched_tend.csv"
    with open(src) as fh:
        rows = list(csv.DictReader(fh))

    out_fields = list(rows[0].keys()) + ["tend12", "tend24", "back_path_km"]
    t0 = time.time()
    for n, r in enumerate(rows, 1):
        when = datetime.strptime(r["when"], "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        p_now = float(r["p_centre"])
        p12, path12 = back_pressure(r["lat"], r["lon"], when, 12.0)
        p24, path24 = back_pressure(r["lat"], r["lon"], when, 24.0)
        r["tend12"] = round(p_now - p12, 1) if np.isfinite(p12) else ""
        r["tend24"] = round(p_now - p24, 1) if np.isfinite(p24) else ""
        r["back_path_km"] = round(path24, 0) if np.isfinite(path24) else ""
        if n % 100 == 0:
            print(f"  {n}/{len(rows)}  {time.time() - t0:.0f}s", flush=True)

    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {dst.name}: {len(rows)} rows", flush=True)


if __name__ == "__main__":
    main()
