"""What predicts the wind, and how far ahead does it still work?

THE FORECAST FRAMING. At each lead L, a track is read at the instance L
hours before its own deepest moment, and the outcome is the maximum ERA5
gust FROM THAT MOMENT ONWARD. Taking the track's overall maximum instead
would leak: for a long lead the peak gust can already have happened, and a
predictor would be scored on a wind it was standing in rather than one it
foresaw.

That definition also makes persistence a fair baseline, and persistence --
"it is already windy" -- is the baseline that matters. A structural
predictor that cannot beat the gust currently blowing is not worth a
product.

FITTING AND SCORING ARE SEPARATED. Every model is fitted on the exploration
seasons and scored on the confirmation seasons, so the R2 reported is out of
sample. An in-sample R2 at these sample sizes would flatter every predictor
and flatter the complicated ones most.

WHAT THE LEADS COST. The sample falls away quickly with lead, and not for
want of data: these lows develop fast. Half the tracks are 36 h long, so by
72 or 96 h before its own peak most of a storm does not exist yet as a
closed low. Past about 48 h the question stops being "how will this low
evolve" and becomes "will a low form", which the low's own depth and scale
cannot answer because there is not yet a low to measure.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import build_hf_lows as bh  # noqa: E402

EXPLORE = (2020, 2022, 2024)
CONFIRM = (2021, 2023, 2025)
LEADS = (0, 12, 24, 48, 72, 96)
STEP_H = 6

NUM = ("lat", "lon", "p_centre", "p_env", "depth", "scale_km", "fit_rms",
       "grad_hpa_per_100km", "vg_kt", "vgeo_kt", "wind_kt", "gust_kt",
       "wind_dist_km")


def load_tracks():
    with open(HERE / "data" / "instances.csv") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["when"] = datetime.strptime(r["when"], "%Y-%m-%d %H").replace(
            tzinfo=timezone.utc)
        for k in NUM:
            r[k] = float(r[k]) if r[k] not in ("", "nan") else np.nan
        r["hf"] = int(r["hf"])
    by = defaultdict(list)
    for r in rows:
        by[r["track"]].append(r)
    for v in by.values():
        v.sort(key=lambda r: r["when"])
    return by


def enrich(pts):
    """Add each point's own recent deepening, from the track itself."""
    for i, p in enumerate(pts):
        for lag in (12, 24):
            k = lag // STEP_H
            j = i - k
            if j >= 0 and (p["when"] - pts[j]["when"]) == timedelta(hours=lag):
                p[f"deep{lag}"] = p["p_centre"] - pts[j]["p_centre"]
            else:
                p[f"deep{lag}"] = np.nan
    return pts


def sample(by, lead):
    """One row per track: predictors at peak-lead, outcome from then on."""
    out = []
    for tid, pts in by.items():
        pts = enrich(pts)
        i_peak = int(np.argmin([p["p_centre"] for p in pts]))
        j = i_peak - lead // STEP_H
        if j < 0:
            continue
        p = pts[j]
        if (pts[i_peak]["when"] - p["when"]) != timedelta(hours=lead):
            continue
        # STRICTLY after the predictor time. Including the current instance
        # lets persistence predict itself: if the gust now happens to be the
        # largest of what follows, the outcome IS the predictor, and its R2
        # is scoring an identity rather than a forecast.
        future = [q["gust_kt"] for q in pts[j + 1:] if np.isfinite(q["gust_kt"])]
        if not future:
            continue
        out.append(dict(
            track=tid, hf=p["hf"],
            season=bh.season_from_date(int(p["when"].strftime("%Y%m%d%H"))),
            y_gust=max(future),
            depth=p["depth"], scale_km=p["scale_km"],
            gradient=p["grad_hpa_per_100km"], vg_kt=p["vg_kt"],
            gust_now=p["gust_kt"], wind_now=p["wind_kt"],
            p_centre=p["p_centre"], lat=abs(p["lat"]),
            deep12=p["deep12"], deep24=p["deep24"],
        ))
    return out


def fit_score(train, test, names):
    """Fit on `train`, score on `test`. Returns out-of-sample R2, or nan."""
    def design(rows):
        X = np.column_stack([np.ones(len(rows))]
                            + [[r[n] for r in rows] for n in names])
        y = np.array([r["y_gust"] for r in rows])
        return X, y
    tr = [r for r in train if all(np.isfinite(r[n]) for n in names)]
    te = [r for r in test if all(np.isfinite(r[n]) for n in names)]
    if len(tr) < 3 * (len(names) + 1) or len(te) < 5:
        return np.nan, len(tr), len(te)
    Xtr, ytr = design(tr)
    Xte, yte = design(te)
    beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
    pred = Xte @ beta
    ss_res = float(((yte - pred) ** 2).sum())
    ss_tot = float(((yte - yte.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot, len(tr), len(te)


def auc(labels, scores):
    """Rank-based AUC; ties get half credit."""
    pairs = sorted(zip(scores, labels))
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return np.nan
    ranks = {}
    i = 0
    vals = [p[0] for p in pairs]
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[i]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = r
        i = j + 1
    s = sum(ranks[k] for k, (_, lab) in enumerate(pairs) if lab == 1)
    return (s - pos * (pos + 1) / 2.0) / (pos * neg)


CANDIDATES = [
    ("gust now (persistence)", ["gust_now"]),
    ("gradient = depth/scale", ["gradient"]),
    ("gradient wind Vg", ["vg_kt"]),
    ("depth", ["depth"]),
    ("scale", ["scale_km"]),
    ("central pressure", ["p_centre"]),
    ("deepening, past 12 h", ["deep12"]),
    ("deepening, past 24 h", ["deep24"]),
    ("depth + scale", ["depth", "scale_km"]),
    ("gradient + persistence", ["gradient", "gust_now"]),
    ("gradient + deepening", ["gradient", "deep12"]),
    ("depth + scale + persistence", ["depth", "scale_km", "gust_now"]),
    ("depth + scale + deepening", ["depth", "scale_km", "deep12"]),
    ("everything", ["depth", "scale_km", "gust_now", "deep12", "lat"]),
]


def main():
    by = load_tracks()
    for lead in LEADS:
        rows = sample(by, lead)
        tr = [r for r in rows if r["season"] in EXPLORE]
        te = [r for r in rows if r["season"] in CONFIRM]
        n_hf = sum(r["hf"] for r in te)
        print(f"\n{'=' * 74}")
        print(f"LEAD {lead:3d} h before the track's own peak   "
              f"train {len(tr)}, test {len(te)} ({n_hf} hurricane-force)")
        print("=" * 74)
        if len(te) < 20:
            print("  too few tracks exist this far ahead of their own peak "
                  "to score anything")
            continue
        scored = []
        for name, feats in CANDIDATES:
            r2, ntr, nte = fit_score(tr, te, feats)
            if np.isfinite(r2):
                scored.append((r2, name, feats, nte))
        scored.sort(reverse=True)
        print(f"  {'predictor':<30} {'out-of-sample R2':>17} {'AUC for HF':>12}")
        print("  " + "-" * 62)
        for r2, name, feats, nte in scored:
            ok = [r for r in te if all(np.isfinite(r[f]) for f in feats)]
            if len(feats) == 1:
                sign = -1.0 if feats[0] in ("scale_km", "p_centre",
                                            "deep12", "deep24") else 1.0
                a = auc([r["hf"] for r in ok],
                        [sign * r[feats[0]] for r in ok])
            else:
                a = np.nan
            astr = f"{a:.3f}" if np.isfinite(a) else "  -"
            print(f"  {name:<30} {r2:>17.3f} {astr:>12}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# The forward-window framing
#
# Anchoring on each track's own peak asks "what did this low look like L hours
# before it bottomed out", and that question runs out of data fast: not because
# the lows are unobserved but because they have not existed for that long. At
# 72 h before its own peak there are five tracks in six seasons; at 96 h, one.
#
# The operational question does not need the peak. It is: given a low on the
# chart now, how windy does it get in the next N hours, and does it reach
# hurricane force? Every instance of every track can answer that, and a track
# that ends inside the window answers "it did not" -- which is a real outcome,
# not missing data.
#
# One consequence to keep in view: instances from the same track are not
# independent, so the effective sample is nearer the number of tracks than the
# number of rows. The out-of-sample split is by SEASON, so no track is ever
# split across fit and score, and the R2 reported is still honest about
# generalization even though the nominal n is large.
# ---------------------------------------------------------------------------

def sample_forward(by, window_h):
    """One row per instance: predictors now, outcome over the next window."""
    out = []
    for tid, pts in by.items():
        pts = enrich(pts)
        for i, p in enumerate(pts):
            if not np.isfinite(p["gust_kt"]):
                continue
            horizon = p["when"] + timedelta(hours=window_h)
            future = [q["gust_kt"] for q in pts[i + 1:]
                      if q["when"] <= horizon and np.isfinite(q["gust_kt"])]
            if not future:
                continue
            out.append(dict(
                track=tid, hf=p["hf"],
                season=bh.season_from_date(int(p["when"].strftime("%Y%m%d%H"))),
                y_gust=max(future),
                hf_ahead=int(max(future) >= 64.0),
                depth=p["depth"], scale_km=p["scale_km"],
                gradient=p["grad_hpa_per_100km"], vg_kt=p["vg_kt"],
                gust_now=p["gust_kt"], wind_now=p["wind_kt"],
                p_centre=p["p_centre"], lat=abs(p["lat"]),
                deep12=p["deep12"], deep24=p["deep24"],
            ))
    return out


def forward_report():
    by = load_tracks()
    for window in (12, 24, 48, 72, 96):
        rows = sample_forward(by, window)
        tr = [r for r in rows if r["season"] in EXPLORE]
        te = [r for r in rows if r["season"] in CONFIRM]
        tracks_te = len({r["track"] for r in te})
        print(f"\n{'=' * 74}")
        print(f"MAX GUST IN THE NEXT {window:3d} h   train {len(tr)} rows, "
              f"test {len(te)} rows from {tracks_te} tracks")
        print("=" * 74)
        scored = []
        for name, feats in CANDIDATES:
            r2, _, _ = fit_score(tr, te, feats)
            if np.isfinite(r2):
                scored.append((r2, name, feats))
        scored.sort(reverse=True)
        print(f"  {'predictor':<30} {'out-of-sample R2':>17} "
              f"{'AUC, 64 kt ahead':>18}")
        print("  " + "-" * 68)
        for r2, name, feats in scored:
            ok = [r for r in te if all(np.isfinite(r[f]) for f in feats)]
            if len(feats) == 1:
                sign = -1.0 if feats[0] in ("scale_km", "p_centre",
                                            "deep12", "deep24") else 1.0
                a = auc([r["hf_ahead"] for r in ok],
                        [sign * r[feats[0]] for r in ok])
            else:
                a = np.nan
            astr = f"{a:.3f}" if np.isfinite(a) else "  -"
            print(f"  {name:<30} {r2:>17.3f} {astr:>18}")
