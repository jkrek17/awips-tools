"""P(hurricane force) per ERA5 cyclone, from the gust index, with and without
a basin term, fitted on the calibration seasons.

usage: probability.py track_points.csv [catalog.csv]

Logistic regression of "matched to an archive HF event" on the track's gust
index (kt), fitted on calib.CAL. Writes results/probability.txt and, given a
catalog, adds p_hf and p_hf_basin columns to it in place.

A probability is a property of the track's index and basin alone, so it can be
attached to catalog rows without re-tracking every season. Seasonal sums of p
over the catalog are NOT expected HF counts: the catalog holds events and
their nulls, not every sub-threshold track.
"""
import os, sys, json
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calib

CENTRE_KT = 70.0          # index is centred so the intercept is P at 70 kt


def design(x, basin, with_basin):
    cols = [np.ones_like(x), x - CENTRE_KT]
    if with_basin:
        cols.append((basin == "pac").astype(float))
    return np.column_stack(cols)


def logit_fit(X, y, iters=50):
    """Maximum likelihood by IRLS. Returns coefficients and their standard errors."""
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        w = p * (1 - p)
        H = X.T @ (X * w[:, None])
        step = np.linalg.solve(H, X.T @ (y - p))
        b += step
        if np.max(np.abs(step)) < 1e-10:
            break
    p = 1 / (1 + np.exp(-X @ b))
    cov = np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))
    return b, np.sqrt(np.diag(cov))


def predict(b, X):
    return 1 / (1 + np.exp(-X @ b))


def loglik(p, y):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return float(np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))


if __name__ == "__main__":
    P = pd.read_csv(sys.argv[1], dtype={"time": str})
    d = json.load(open(calib.ARCH))
    ev = [dict(zip(d["lowFields"], r)) for r in d["lows"]]
    for e in ev:
        e["fixes"] = [dict(zip(d["fixFields"], f)) for f in e["fixes"]]
    S = calib.CAL
    M = calib.match(P, ev, set(S))
    T = calib.tracks_table(P, "g800")
    T = T[T.season.isin(S)].copy()
    pos = {t for t, e in M.values() if t is not None}
    T["y"] = T.index.isin(pos).astype(float)
    x, bas, y = T["index"].values, T["basin"].values, T["y"].values
    unmatched = sum(t is None for t, _ in M.values())

    out = []
    say = lambda s="": (print(s), out.append(s))
    say(f"Seasons {S[0]}-{(S[0] + 1) % 100:02d} .. {S[-1]}-{(S[-1] + 1) % 100:02d}: "
        f"{len(T)} ERA5 tracks, {int(y.sum())} matched to archive HF events "
        f"({unmatched} archive events have no ERA5 track and are not in the fit)")
    say(f"Model: logit P(HF) = b0 + b1 (gust index - {CENTRE_KT:.0f} kt) [+ b2 Pacific]")
    say()
    fits = {}
    for name, wb in (("p_hf", False), ("p_hf_basin", True)):
        X = design(x, bas, wb)
        b, se = logit_fit(X, y)
        fits[name] = (b, wb)
        p = predict(b, X)
        terms = ["b0", "b1", "b2"][:len(b)]
        say(f"{name}:  " + "  ".join(f"{t}={v:+.3f} (se {s:.3f})" for t, v, s in zip(terms, b, se)))
        say(f"  P = 0.5 at {CENTRE_KT - b[0] / b[1]:.1f} kt" +
            (f" (Atlantic), {CENTRE_KT - (b[0] + b[2]) / b[1]:.1f} kt (Pacific)" if wb else ""))
        say(f"  log-likelihood {loglik(p, y):.1f}   Brier {np.mean((p - y) ** 2):.4f}")
        for bn in ("atl", "pac"):
            m = bas == bn
            say(f"  {bn}: sum p {p[m].sum():.1f} vs observed {int(y[m].sum())} "
                f"({100 * (p[m].sum() / y[m].sum() - 1):+.1f}%)")
        # leave-one-season-out: refit without the season, score it
        ll = 0.0
        for s in S:
            tr = T.season.values != s
            bb, _ = logit_fit(X[tr], y[tr])
            ll += loglik(predict(bb, X[~tr]), y[~tr])
        say(f"  leave-one-season-out log-likelihood {ll:.1f}")
        say()
    # likelihood-ratio test for the basin term
    l0 = loglik(predict(fits["p_hf"][0], design(x, bas, False)), y)
    l1 = loglik(predict(fits["p_hf_basin"][0], design(x, bas, True)), y)
    say(f"Basin term: likelihood-ratio statistic {2 * (l1 - l0):.2f} on 1 df "
        f"(3.84 is p = 0.05)")
    say()
    say("Reliability, p_hf (deciles of predicted probability among tracks with p >= 0.01)")
    p = predict(fits["p_hf"][0], design(x, bas, False))
    m = p >= 0.01
    q = pd.qcut(p[m], 10, duplicates="drop")
    tab = pd.DataFrame({"p": p[m], "y": y[m], "q": q}).groupby("q", observed=True).agg(
        n=("y", "size"), mean_p=("p", "mean"), obs=("y", "mean"))
    for _, r in tab.iterrows():
        say(f"  n={int(r.n):4d}  mean p {r.mean_p:.3f}  observed {r.obs:.3f}")

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    open(os.path.join(HERE, "results", "probability.txt"), "w").write("\n".join(out) + "\n")
    json.dump({k: {"coef": [round(float(v), 5) for v in b], "basin_term": wb, "centre_kt": CENTRE_KT}
               for k, (b, wb) in fits.items()},
              open(os.path.join(HERE, "results", "probability.json"), "w"), indent=1)

    if len(sys.argv) > 2:
        cat = pd.read_csv(sys.argv[2], dtype=str, keep_default_na=False)
        g = cat["gust800_kt"].astype(float).values
        cb = cat["basin"].values
        for k, (b, wb) in fits.items():
            cat[k] = np.round(predict(b, design(g, cb, wb)), 4)
        cat.to_csv(sys.argv[2], index=False)
        print("added", ", ".join(fits), "to", sys.argv[2])
