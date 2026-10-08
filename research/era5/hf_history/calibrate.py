"""Fit the gust-index threshold on the calibration seasons and score it.

usage: calibrate.py [track_points.csv]
Prints the skill report and writes results/skill.txt and results/threshold.json.
"""
import os, sys, json
import numpy as np, pandas as pd
from scipy.stats import mannwhitneyu

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calib

METRIC = "g800"
GRID = np.round(np.arange(60, 85, 0.1), 1)
KEYS = ["n_obs", "n_fc", "bias", "pod", "far", "csi", "hss"]


def fmt(r):
    return "  ".join(f"{k}={r[k]:.2f}" if isinstance(r[k], float) else f"{k}={r[k]}" for k in KEYS)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(calib.WORK, "track_points.csv")
    P = pd.read_csv(path, dtype={"time": str})
    d = json.load(open(calib.ARCH))
    ev = [dict(zip(d["lowFields"], r)) for r in d["lows"]]
    for e in ev:
        e["fixes"] = [dict(zip(d["fixFields"], f)) for f in e["fixes"]]
    S = calib.CAL
    M = calib.match(P, ev, set(range(2001, 2026)))
    T = calib.tracks_table(P, METRIC)
    out = []
    say = lambda s="": (print(s), out.append(s))

    inS = {k: v for k, v in M.items() if v[1]["season"] in S}
    say(f"Calibration seasons {S[0]}-{(S[0] + 1) % 100:02d} .. {S[-1]}-{(S[-1] + 1) % 100:02d}: "
        f"{len(inS)} archive events, {sum(t is not None for t, _ in inS.values())} matched to an ERA5 track")
    pos = {t for t, _ in inS.values() if t is not None}
    Ts = T[T.season.isin(S)]
    y = Ts.index.isin(pos); x = Ts["index"].values
    auc = mannwhitneyu(x[y], x[~y]).statistic / (y.sum() * (~y).sum())
    f = calib.fit(T, M, S, GRID)
    thr = float(f["thr"])
    say(f"Index: max ERA5 instantaneous 10 m gust over ocean within 800 km of the centre, max over the track")
    say(f"AUC {auc:.3f} over {len(Ts)} tracks")
    say(f"Threshold (forecast count = archive count): {thr:.1f} kt")
    say("  " + fmt(f))
    say()
    say("Leave-one-season-out (threshold refitted without the held-out season)")
    for s in S:
        g = calib.fit(T, M, [z for z in S if z != s], GRID)
        say(f"  {s}-{(s + 1) % 100:02d}  thr={g['thr']:.1f}  " + fmt(calib.score(T, M, [s], g["thr"])))
    say()
    say("By basin, calibration seasons")
    for b in ("atl", "pac"):
        r = calib.score(T[T.basin == b], {k: v for k, v in M.items() if v[1]["basin"] == b}, S, thr)
        say(f"  {b}  " + fmt(r))
    say()
    say("Transfer to earlier archive seasons at the fixed threshold")
    for lo in (2001, 2006, 2011, 2016):
        blk = list(range(lo, lo + 5))
        g = calib.fit(T, M, blk, GRID)
        say(f"  {lo}-{lo + 5}  " + fmt(calib.score(T, M, blk, thr)) + f"  (own count-matching thr {g['thr']:.1f})")
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    open(os.path.join(HERE, "results", "skill.txt"), "w").write("\n".join(out) + "\n")
    json.dump({"metric": METRIC, "threshold_kt": thr, "auc": round(float(auc), 4)},
              open(os.path.join(HERE, "results", "threshold.json"), "w"), indent=1)
