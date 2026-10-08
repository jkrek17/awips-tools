"""Apply the calibrated gust-index threshold to every season, pick matched
null cases, and write the catalog and per-season counts.

usage: apply.py track_points.csv THRESHOLD_KT OUTDIR
"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("ERA5_WORK", os.path.join(HERE, "work"))

import sys, json
import numpy as np, pandas as pd
sys.path.insert(0, HERE)
import calib

NULL_WINDOW_H = 7 * 24
NULL_MIN_FIX = 8          # 48 h
NULL_MAX_MINP = 1000.0    # hPa


def hours(t):
    return pd.to_datetime(t, format="%Y%m%d%H")


if __name__ == "__main__":
    P = pd.read_csv(sys.argv[1], dtype={"time": str})
    thr = float(sys.argv[2])
    out = sys.argv[3]
    T = calib.tracks_table(P, "g800")
    T = T[(T.season >= 1979) & (T.season <= 2025)].copy()
    T["hf_equiv"] = T["index"] >= thr
    T["peak_dt"] = hours(T.peak_time)

    # archive link, for the overlap seasons
    d = json.load(open(calib.ARCH))
    ev = [dict(zip(d["lowFields"], r)) for r in d["lows"]]
    for e in ev:
        e["fixes"] = [dict(zip(d["fixFields"], f)) for f in e["fixes"]]
    M = calib.match(P, ev, set(range(2001, 2026)))
    arch = {}
    for k, (t, e) in M.items():
        if t is not None:
            arch.setdefault(t, []).append(k)
    T["archive_events"] = [";".join(arch.get(t, [])) for t in T.index]

    # matched nulls: same basin and season, peak within +/-7 days, a real cyclone
    # (>= 48 h, min MSLP <= 1000 hPa) that never reaches the threshold; nearest
    # peak time first, each null used once
    pool = T[(~T.hf_equiv) & (T.n_fix >= NULL_MIN_FIX) & (T.minp <= NULL_MAX_MINP)]
    used = set()
    T["null_for"] = ""
    T["role"] = np.where(T.hf_equiv, "event", "")
    nulls = {}
    for tid, r in T[T.hf_equiv].sort_values("peak_dt").iterrows():
        c = pool[(pool.basin == r.basin) & (pool.season == r.season)]
        dt = (c.peak_dt - r.peak_dt).abs().dt.total_seconds() / 3600
        c = c[(dt <= NULL_WINDOW_H) & (~c.index.isin(used))]
        if len(c):
            j = (c.peak_dt - r.peak_dt).abs().idxmin()
            used.add(j)
            nulls[j] = tid
    for j, tid in nulls.items():
        T.loc[j, "role"] = "null_case"
        T.loc[j, "null_for"] = str(tid)
    T["unmatched_event"] = T.hf_equiv & ~T.index.isin(list(nulls.values()))

    cat = T[T.role != ""].drop(columns=["peak_dt"]).copy()
    cat.index.name = "track"
    cat = cat.reset_index().sort_values(["basin", "peak_time"])
    cols = ["track", "role", "null_for", "basin", "season", "start", "end", "n_fix", "peak_time",
            "peak_lat", "peak_lon", "index", "minp", "archive_events"]
    cat.rename(columns={"index": "gust800_kt"}, inplace=True)
    cols[cols.index("index")] = "gust800_kt"
    cat[cols].to_csv(f"{out}/era5_hf_catalog.csv", index=False)

    pts = P[P.track.isin(cat.track)][["track", "time", "lat", "lon", "msl", "g800", "basin"]]
    pts.to_csv(f"{out}/era5_hf_catalog_tracks.csv", index=False)

    # per-season counts, with the archive alongside where it exists
    ac = pd.Series([(e["basin"], e["season"]) for e in ev]).value_counts()
    rows = []
    for s in range(1979, 2026):
        row = {"season": f"{s}-{(s + 1) % 100:02d}"}
        for b in ("atl", "pac"):
            x = T[(T.season == s) & (T.basin == b)]
            row[f"{b}_era5"] = int(x.hf_equiv.sum())
            row[f"{b}_nulls"] = int(((x.role == "null_case")).sum())
            row[f"{b}_archive"] = int(ac.get((b, s), 0)) if s >= 2001 else ""
        rows.append(row)
    pd.DataFrame(rows).to_csv(f"{out}/era5_hf_counts_by_season.csv", index=False)
    print("events", int(T.hf_equiv.sum()), "nulls", len(nulls), "events without a null", int(T.unmatched_event.sum()))
