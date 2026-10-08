"""Match ERA5 tracks to archive HF events, calibrate the gust-index threshold,
score it, and apply it to every season.

Inputs: track_points.csv (track.py), docs/data/hf-lows.json (the archive).
"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("ERA5_WORK", os.path.join(HERE, "work"))

import json, sys, collections
import numpy as np, pandas as pd

ARCH = os.path.join(HERE, "..", "..", "..", "docs", "data", "hf-lows.json")
CAL = list(range(2021, 2026))      # seasons 2021-22 .. 2025-26
MATCH_KM = 400
MATCH_KM_NOCENTRE = 800            # tip jets and centreless events
RE = 6371.0


def hav(la1, lo1, la2, lo2):
    la1, lo1, la2, lo2 = map(np.radians, (la1, lo1, la2, lo2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * RE * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def load():
    P = pd.read_csv(os.path.join(WORK, "track_points.csv"), dtype={"time": str})
    d = json.load(open(ARCH))
    ev = [dict(zip(d["lowFields"], r)) for r in d["lows"]]
    for e in ev:
        e["fixes"] = [dict(zip(d["fixFields"], f)) for f in e["fixes"]]
    return P, ev


def tracks_table(P, metric):
    dom = P[P.basin.fillna("") != ""]
    g = dom.groupby("track")
    T = pd.DataFrame({
        "basin": g.basin.agg(lambda s: s.value_counts().index[0]),
        "n_dom": g.size(),
        "index": g[metric].max(),
        "minp": g.msl.min(),
    })
    # season and peak time: the in-domain fix with the highest index
    pk = dom.loc[dom.groupby("track")[metric].idxmax()].set_index("track")
    T["peak_time"] = pk.time
    T["peak_lat"], T["peak_lon"] = pk.lat, pk.lon
    T["season"] = pk.season
    span = P.groupby("track").time.agg(["min", "max", "size"])
    T["start"], T["end"], T["n_fix"] = span["min"], span["max"], span["size"]
    return T[T.n_dom >= 2]


def match(P, ev, seasons):
    """Archive event key -> ERA track id (or None)."""
    by_time = {t: g for t, g in P.groupby("time")}
    out = {}
    for e in ev:
        if e["season"] not in seasons:
            continue
        lim = MATCH_KM if e["cls"] == "low" else MATCH_KM_NOCENTRE
        votes = collections.Counter()
        for f in e["fixes"]:
            if f["lat"] is None or f["lon"] is None:
                continue
            g = by_time.get(str(f["date"]))
            if g is None:
                continue
            d = hav(f["lat"], f["lon"] % 360, g.lat.values, g.lon.values)
            j = int(np.argmin(d))
            if d[j] <= lim:
                votes[int(g.track.values[j])] += 2 if f["cat"] == "HF" else 1
        out[e["basin"] + ":" + e["id"]] = (votes.most_common(1)[0][0] if votes else None, e)
    return out


def score(T, M, seasons, thr):
    """Track-level contingency. Positives: tracks matched to an archive HF event.
    Archive events with no ERA track count as misses."""
    Ts = T[T.season.isin(seasons)]
    pos_tracks = {t for t, e in M.values() if t is not None and e["season"] in seasons}
    unmatched = sum(1 for t, e in M.values() if t is None and e["season"] in seasons)
    yes = Ts["index"] >= thr
    obs = Ts.index.isin(pos_tracks)
    a = int((yes & obs).sum()); b = int((yes & ~obs).sum())
    c = int((~yes & obs).sum()) + unmatched; d = int((~yes & ~obs).sum())
    n = a + b + c + d
    pod = a / max(a + c, 1); far = b / max(a + b, 1); csi = a / max(a + b + c, 1)
    e_ = ((a + b) * (a + c) + (c + d) * (b + d)) / n
    hss = (a + d - e_) / (n - e_)
    return dict(thr=thr, a=a, b=b, c=c, d=d, pod=pod, far=far, csi=csi, hss=hss,
                bias=(a + b) / max(a + c, 1), n_obs=a + c, n_fc=a + b)


def fit(T, M, seasons, grid):
    """Threshold whose forecast count matches the archive count (bias 1)."""
    rows = [score(T, M, seasons, x) for x in grid]
    return min(rows, key=lambda r: abs(r["bias"] - 1))
