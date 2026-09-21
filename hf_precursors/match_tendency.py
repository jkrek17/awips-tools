"""The inverted design: match on tendency, then ask whether structure adds.

The depth-matched pass found every structural coefficient pointing the wrong
way, because depth at an instant conflates how strong a low is with how far
along it is. A case is developing 24 h short of its peak; a control drawn at
a random time is often at or past its own; matching them on depth pairs a
developing low with a mature one.

Tendency is the variable that tracks how far along a low is, so matching on
it pairs lows at the same stage and leaves depth, scale and gradient free to
vary inside the stratum -- which is exactly what has to happen for the
conditional likelihood to say anything about them.

The question this asks, in one line: among lows deepening at the same rate,
at the same latitude and time of year, does the COMPACT one go on to make
hurricane force and the broad one not?

Matching on tendency and not on depth is deliberate. Matching on both would
leave almost nothing varying inside a stratum, and depth is a predictor
under test here rather than a nuisance to be held fixed.
"""
from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

TEND_TOL = 3.0      # hPa per 12 h
LAT_TOL = 5.0
PER_CASE = 3


def read(path):
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        if r.get("tend12", "") == "":
            continue
        r["tend12"] = float(r["tend12"])
        r["lat"] = float(r["lat"])
        r["season"] = int(r["season"])
        r["month"] = int(r["month"])
        r["label"] = int(r["label"])
        out.append(r)
    return out


def match(cases, pool, per_case=PER_CASE, seed=31):
    rng = random.Random(seed)
    by_key = {}
    for r in pool:
        by_key.setdefault((r["season"], r["month"]), []).append(r)
    for v in by_key.values():
        rng.shuffle(v)

    used, out = set(), []
    for k, c in enumerate(cases):
        stratum = f"t{k:04d}"
        picks = []
        for r in by_key.get((c["season"], c["month"]), []):
            if id(r) in used:
                continue
            if abs(r["tend12"] - c["tend12"]) > TEND_TOL:
                continue
            if abs(r["lat"] - c["lat"]) > LAT_TOL:
                continue
            picks.append(r)
            if len(picks) == per_case:
                break
        if not picks:
            continue
        out.append(dict(c, stratum=stratum))
        for r in picks:
            used.add(id(r))
            out.append(dict(r, stratum=stratum))
    return out


def main():
    matched = read(HERE / "data" / "matched_tend.csv")
    cases = [r for r in matched if r["label"] == 1]
    pool = read(HERE / "data" / "pool_tend.csv")
    print(f"cases with a tendency: {len(cases)}   pool with a tendency: {len(pool)}")

    rows = match(cases, pool)
    n_case = sum(1 for r in rows if r["label"] == 1)
    fields = [c for c in rows[0].keys()]
    dst = HERE / "data" / "matched_by_tend.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"matched on tendency: {n_case} strata, {len(rows) - n_case} controls "
          f"-> {dst.name}")


if __name__ == "__main__":
    main()
