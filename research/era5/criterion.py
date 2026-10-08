"""Fit a small hurricane-force-equivalent criterion on ERA5 cyclone features and
test whether it transfers across 20 years of ERA5's own evolution.

THIS SCRIPT WAS WRITTEN BEFORE ITS RESULT WAS SEEN, and nothing in it was
changed afterwards in response to the cross-period numbers. The choices below
were fixed in advance from the physics and from the archive's own metadata:

  Population   Candidate cyclone-times from event_fields.py with smoothed
               centre pressure <= 990 hPa (the pilot's track filter; HF events
               have a median minimum pressure near 964 hPa), cls = pos or neg.
               'gray' candidates (a non-HF moment of a cyclone that reached HF
               at another time) are excluded from the primary fit.

  Windows      Early = season starts 2004 and 2005. NOT 2001-2005: the archive
               itself declares that "both basins are only consistently covered
               from the 2004-05 season" (RECORD_START in tools/build_hf_lows.py;
               the Pacific tab begins Feb 2002, the Atlantic Sep 2003, and the
               Atlantic 2003 season has 11 events against ~45 in a full one).
               Treating an uncovered season as "no hurricane force" would label
               real HF cyclones negative and make the label noise itself
               period dependent. Late = 2021-2025.
               Pre-specified sensitivity S2 adds the Pacific seasons 2002 and
               2003 to the early window (Atlantic excluded there).

  Features     Fixed physical units, so coefficients are comparable across
               fits and are never re-standardised per period:
                 gust    maximum instantaneous 10 m gust within 500 km, in 10 kt
                 larea   log(1 + area of gust >= 64 kt within 500 km / 1000 km^2)
                 grad    maximum MSLP gradient within 500 km, hPa per 100 km
                 pdep    (raw minimum pressure within 150 km - 980 hPa) / 10
               M1 = gust + larea + grad + pdep  (4 slopes + intercept)
               M0 = gust alone                  (1 slope + intercept; the
                    nearest thing to a single threshold, kept as the reference)
               The 50 kt area and the pressure Laplacian are in the table but
               NOT in the model: they are near-collinear with gust/area64 and
               with pdep respectively, and a coefficient the physics does not
               need is one more thing to drift.

  Fit          Plain logistic regression (tiny ridge for numerical stability).

Uncertainty comes from a bootstrap that resamples whole cyclone TRACKS, not
candidates, because the 6-hourly candidates of one storm are not independent.

Nothing here is a validation for backward use. It is a necessary condition.
"""
import csv
import datetime
import io
import math
import os
import sys
import tempfile

import numpy as np

import event_fields as ef

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "criterion-result.txt")
P_FIT = 990.0
EARLY = (2004, 2005)
LATE = (2021, 2022, 2023, 2024, 2025)
EARLY_S2_PAC = (2002, 2003)
NBOOT = 400
RNG = np.random.default_rng(20260507)
FEATS = ["gust", "larea", "grad", "pdep"]
MODELS = {"M1": [0, 1, 2, 3], "M0": [0]}


# --- numerics (numpy only) ----------------------------------------------------

def fit_logit(X, y, iters=50, ridge=1e-6, offset=None):
    """IRLS logistic regression. X without intercept. Returns [b0, b1...]."""
    n, k = X.shape
    A = np.column_stack([np.ones(n), X])
    off = np.zeros(n) if offset is None else offset
    b = np.zeros(k + 1)
    pen = np.eye(k + 1) * ridge
    pen[0, 0] = 0
    for _ in range(iters):
        z = np.clip(A @ b + off, -30, 30)
        p = 1 / (1 + np.exp(-z))
        w = np.maximum(p * (1 - p), 1e-9)
        H = A.T @ (A * w[:, None]) + pen
        g = A.T @ (y - p) - pen @ b
        # lstsq + a capped step: calibration regressions on extreme predicted
        # probabilities (near-zero weights) can make H singular
        step = np.clip(np.linalg.lstsq(H + 1e-9 * np.eye(k + 1), g, rcond=None)[0], -3, 3)
        b = b + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def predict(b, X):
    return 1 / (1 + np.exp(-np.clip(b[0] + X @ b[1:], -30, 30)))


def auc(y, s):
    y = np.asarray(y)
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    u, inv, cnt = np.unique(s, return_inverse=True, return_counts=True)
    avg = np.cumsum(cnt) - (cnt - 1) / 2.0
    r = avg[inv]
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def calib(y, p):
    """observed rate, predicted mean, ratio, calibration slope, calibration-in-
    the-large offset (log-odds shift needed at slope 1)."""
    lp = logit(p)
    sl = fit_logit(lp[:, None], y)[1]
    # offset-only fit: intercept with the linear predictor held at slope 1
    a = fit_logit(np.zeros((len(y), 0)), y, offset=lp)[0]
    return dict(obs=float(y.mean()), pred=float(p.mean()),
                ratio=float(p.mean() / y.mean()) if y.mean() > 0 else float("nan"),
                slope=float(sl), shift=float(a))


# --- data ---------------------------------------------------------------------

class D:
    pass


def feature_matrix(rows):
    """The four model features, in the fixed units of the header (columns match
    FEATS). Single definition shared by build() and series.py."""
    return np.array([[c["g500"] / 10.0, math.log1p(c["a64"] / 1000.0), c["gradmax"],
                      (c["pmin"] - 980.0) / 10.0] for c in rows]).reshape(len(rows), 4)


def build(cands, seasons, cls=("pos", "neg"), pac_only_seasons=()):
    rows = []
    for c in cands:
        if c["season"] not in seasons:
            continue
        if c["basin"] == "atl" and c["season"] < ef_record_start():
            continue
        if c["cls"] not in cls or c["p"] > P_FIT:
            continue
        rows.append(c)
    d = D()
    d.rows = rows
    d.y = np.array([1 if c["cls"] == "pos" else 0 for c in rows], float)
    d.X = feature_matrix(rows)
    d.season = np.array([c["season"] for c in rows])
    d.basin = np.array([c["basin"] for c in rows])
    tr = {}
    d.track = np.array([tr.setdefault((c["basin"], c["season"], c["track"]), len(tr)) for c in rows])
    d.groups = [np.where(d.track == k)[0] for k in range(len(tr))]
    return d


def ef_record_start():
    # Atlantic is only covered by the archive from the 2004-05 season on.
    return 2004


def subset(d, mask):
    s = D()
    s.rows = [r for r, m in zip(d.rows, mask) if m]
    s.y, s.X, s.season, s.basin = d.y[mask], d.X[mask], d.season[mask], d.basin[mask]
    tr = {}
    s.track = np.array([tr.setdefault(t, len(tr)) for t in d.track[mask]], int)
    s.groups = [np.where(s.track == k)[0] for k in range(len(tr))]
    return s


def boot_idx(d):
    pick = RNG.integers(0, len(d.groups), len(d.groups))
    return np.concatenate([d.groups[k] for k in pick])


def concat(a, b):
    s = D()
    s.rows = a.rows + b.rows
    s.y = np.concatenate([a.y, b.y])
    s.X = np.vstack([a.X, b.X])
    s.season = np.concatenate([a.season, b.season])
    s.basin = np.concatenate([a.basin, b.basin])
    tr = {}
    keys = [("a", t) for t in a.track] + [("b", t) for t in b.track]
    s.track = np.array([tr.setdefault(k, len(tr)) for k in keys])
    s.groups = [np.where(s.track == k)[0] for k in range(len(tr))]
    return s


# --- extension: forecaster skill scores, TC contaminant, basin term, series check ---
#
# Everything below was specified before it was run (the coordinator's four items):
#   10. HSS / POD / FAR at the probability cut that makes the flagged count equal
#       the archive count in the fit window;
#   11. transitioning-tropical-cyclone contaminant: mask, refit, compare skill;
#   12. an a-priori basin indicator (Pacific = 1), with and without;
#   13. the series-level stationarity check on all overlap seasons, with and
#       without the basin term.
# None of these changes the primary transfer test (sections 1-9), which is
# unchanged in design and re-run on ocean-masked gust features.

IBTRACS_DIR = os.environ.get("IBTRACS_DIR", os.path.join(tempfile.gettempdir(), "ibtracs"))
IBTRACS_URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
               "stewardship-ibtracs/v04r01/access/csv/ibtracs.%s.list.v04r01.csv")
TC_MATCH_KM = 400.0
TC_CSV = os.path.join(HERE, "tc_candidates.csv")


def design(d, model):
    if model == "M0":
        return d.X[:, [0]]
    if model == "M1":
        return d.X
    if model == "M1B":                       # M1 + Pacific indicator
        return np.column_stack([d.X, (d.basin == "pac").astype(float)])
    raise KeyError(model)


def count_cut(p, n):
    """Cut at which n of the values in p are flagged (p >= cut), up to ties."""
    n = int(min(max(n, 1), len(p)))
    return float(np.sort(p)[::-1][n - 1])


def skill(y, flag):
    y = np.asarray(y) == 1
    a = int((flag & y).sum())
    b = int((flag & ~y).sum())
    c = int((~flag & y).sum())
    d_ = int((~flag & ~y).sum())
    den = (a + c) * (c + d_) + (a + b) * (b + d_)
    nan = float("nan")
    return dict(hits=a, fa=b, miss=c, cn=d_, flagged=a + b, obs=a + c,
                pod=a / (a + c) if a + c else nan, far=b / (a + b) if a + b else nan,
                hss=2.0 * (a * d_ - b * c) / den if den else nan,
                csi=a / (a + b + c) if a + b + c else nan)


def boot_skill(d, flag, key, nboot=NBOOT):
    """95% interval of one skill key, resampling whole tracks of the evaluation
    set (the fit is held fixed, so refit noise is not in this interval)."""
    vals = []
    for _ in range(nboot):
        i = boot_idx(d)
        vals.append(skill(d.y[i], flag[i])[key])
    return np.nanpercentile(vals, [2.5, 97.5])


def gust_equiv(b, model, cut, x_ref):
    """Gust (kt) at which the model reaches `cut`, other features at x_ref.
    M0: exact (the model is a gust threshold). M1/M1B: x_ref = median of the
    training positives for the non-gust terms."""
    t = logit(np.array([cut]))[0] - b[0]
    rest = 0.0 if model == "M0" else float(np.dot(b[2:5], x_ref[1:4]))
    return (t - rest) / b[1] * 10.0


def loso(d, model, fit_mask=None, eval_mask=None):
    """Leave one season out. Training cut = count-matched on the training rows
    that would be evaluated (flagged count = positives there). Returns held-out
    p and flag for every row (NaN / False where the row is not evaluated)."""
    X = design(d, model)
    p = np.full(len(d.y), np.nan)
    flag = np.zeros(len(d.y), bool)
    fm = np.ones(len(d.y), bool) if fit_mask is None else fit_mask
    em = np.ones(len(d.y), bool) if eval_mask is None else eval_mask
    for s in sorted(set(d.season.tolist())):
        te = d.season == s
        tr = ~te & fm
        b = fit_logit(X[tr], d.y[tr])
        trm = ~te & em
        cut = count_cut(predict(b, X[trm]), int(d.y[trm].sum()))
        p[te] = predict(b, X[te])
        flag[te] = p[te] >= cut
    return p, flag


def fmt_sk(lab, s, cut=None, g=None, ci=None):
    return "   %-34s flagged %5d obs %5d  hits %5d FA %5d miss %5d  POD %.3f FAR %.3f HSS %.3f%s CSI %.3f%s%s" % (
        lab, s["flagged"], s["obs"], s["hits"], s["fa"], s["miss"], s["pod"], s["far"], s["hss"],
        (" [%.3f,%.3f]" % tuple(ci)) if ci is not None else "", s["csi"],
        (" cut p=%.3f" % cut) if cut is not None else "",
        (" ~%.1f kt" % g) if g is not None else "")


def ibtracs_storms():
    """sid -> list of (time_index, lat, lon, nature) for storms with at least one
    NATURE == 'TS' record, synoptic hours, Sep-May, 1979 onward. Downloads the
    NA / EP / WP lists from NCEI into IBTRACS_DIR if they are not there."""
    os.makedirs(IBTRACS_DIR, exist_ok=True)
    storms, tropical = {}, set()
    for b in ("NA", "EP", "WP"):
        path = os.path.join(IBTRACS_DIR, "ibtracs.%s.list.v04r01.csv" % b)
        if not os.path.exists(path):
            import urllib.request
            urllib.request.urlretrieve(IBTRACS_URL % b, path)
        with open(path, newline="") as f:
            r = csv.reader(f)
            hdr = next(r)
            next(r)                                   # units row
            ix = {h: i for i, h in enumerate(hdr)}
            i_sid, i_t, i_n, i_la, i_lo = (ix[k] for k in ("SID", "ISO_TIME", "NATURE", "LAT", "LON"))
            for row in r:
                nat = row[i_n]
                if nat == "TS":
                    tropical.add(row[i_sid])
                ts = row[i_t]
                y, mo, hh = int(ts[:4]), int(ts[5:7]), int(ts[11:13])
                if y < 1978 or hh % 6 or not (mo >= 9 or mo <= 5) or not row[i_la].strip():
                    continue
                t = ef.tidx(datetime.datetime(y, mo, int(ts[8:10]), hh))
                storms.setdefault(row[i_sid], []).append((t, float(row[i_la]), float(row[i_lo]), nat))
    return {k: v for k, v in storms.items() if k in tropical}, len(tropical)


def tag_tc(cands):
    """Mark candidates within TC_MATCH_KM of an IBTrACS point (any nature) of a
    storm that was tropical at some time, at the same valid time ('tc'), then
    the whole linked track of any marked candidate ('tctrack'). Writes the
    marked candidates to tc_candidates.csv. Returns (n_storms, n_marked)."""
    storms, ntrop = ibtracs_storms()
    byt = {}
    for sid, pts in storms.items():
        for t, la, lo, nat in pts:
            byt.setdefault(t, []).append((la, lo, sid))
    for c in cands:
        c["tc"] = 0
        c["sid"] = ""
        best = None
        for la, lo, sid in byt.get(c["t"], []):
            dd = ef.hav1(c["lat"], c["lon"], la, lo)
            if dd <= TC_MATCH_KM and (best is None or dd < best[0]):
                best = (dd, sid)
        if best:
            c["tc"], c["sid"] = 1, best[1]
    bad = {(c["basin"], c["season"], c["track"]) for c in cands if c["tc"]}
    for c in cands:
        c["tctrack"] = int((c["basin"], c["season"], c["track"]) in bad)
    with open(TC_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "basin", "lat", "lon", "ibtracs_sid"])
        for c in sorted((c for c in cands if c["tc"]), key=lambda c: (c["t"], c["basin"], c["lat"])):
            lon = ((c["lon"] + 180.0) % 360.0) - 180.0
            w.writerow([ef.idx_to_dt(c["t"]).strftime("%Y-%m-%dT%H:%MZ"), c["basin"],
                        "%.2f" % c["lat"], "%.2f" % lon, c["sid"]])
    return ntrop, int(sum(c["tc"] for c in cands))


def extended(P, cands, seasons):
    ovl = [s for s in seasons if s >= 2004]
    covered = [c for c in cands if not (c["basin"] == "atl" and c["season"] < 2004)]
    dall = build(covered, tuple(ovl))
    d_e, d_l = subset(dall, np.isin(dall.season, EARLY)), subset(dall, np.isin(dall.season, LATE))
    P("")
    P("=" * 72)
    P("EXTENSION (coordinator's four items). Overlap seasons used: %d (%d..%d); n=%d pos=%d neg=%d tracks=%d" % (
        len(ovl), ovl[0], ovl[-1], len(dall.y), dall.y.sum(), len(dall.y) - dall.y.sum(), len(dall.groups)))
    P("=" * 72)

    # ------------------------------------------------------------- 10 HSS/POD/FAR
    P("")
    P("10. HSS, POD, FAR AT THE COUNT-MATCHED CUT")
    P("   Unit: a 6-hourly cyclone-moment (fit population, pos/neg). Yes-forecast = p >= cut, where the cut is")
    P("   the probability at which the number of flagged moments EQUALS the archive's HF-moment count in the")
    P("   fit window (so flagged = obs there, and POD = 1 - FAR by construction in-sample). POD = hits/(hits+miss);")
    P("   FAR = false alarms / flagged (a ratio, not a rate); HSS = 2(ad-bc)/[(a+c)(c+d)+(a+b)(b+d)], 0 = no skill")
    P("   over chance, 1 = perfect; CSI = hits/(hits+FA+miss). 'cut ~kt' = the gust the cut equals: exact for M0")
    P("   (a gust-only model IS a gust threshold); for M1 the gust at which M1 reaches the cut with its other")
    P("   features at the median of the training positives. Transfer rows apply the TRAINING window's cut to the")
    P("   other window, so flagged vs obs there is the count error a backward extension would inherit.")
    P("   Intervals in brackets: 95%% on HSS, resampling evaluation tracks, fit held fixed (%d reps)." % NBOOT)
    for model in ("M1", "M0"):
        P("")
        P("   %s" % model)
        Xall = design(dall, model)
        rows = []
        for lab, tr_, te_ in (("fit early, scored early (in-sample)", d_e, d_e),
                              ("fit late, scored late (in-sample)", d_l, d_l),
                              ("fit early -> late (cut from early)", d_e, d_l),
                              ("fit late -> early (cut from late)", d_l, d_e)):
            b = fit_logit(design(tr_, model), tr_.y)
            cut = count_cut(predict(b, design(tr_, model)), int(tr_.y.sum()))
            flag = predict(b, design(te_, model)) >= cut
            xref = np.median(tr_.X[tr_.y == 1], 0)
            g = gust_equiv(b, model, cut, xref)
            sk = skill(te_.y, flag)
            P(fmt_sk(lab, sk, cut, g, boot_skill(te_, flag, "hss")))
        p, flag = loso(dall, model)
        sk = skill(dall.y, flag)
        bfull = fit_logit(Xall, dall.y)
        cutf = count_cut(predict(bfull, Xall), int(dall.y.sum()))
        gf = gust_equiv(bfull, model, cutf, np.median(dall.X[dall.y == 1], 0))
        P(fmt_sk("LOSO over all %d seasons" % len(ovl), sk, None, None, boot_skill(dall, flag, "hss")))
        P("   %-34s full-fit cut p=%.3f, equivalent gust %.1f kt (the count-matched criterion over %d seasons)" % (
            "", cutf, gf, len(ovl)))
        ps = [skill(dall.y[dall.season == s], flag[dall.season == s]) for s in ovl]
        P("   per held-out season flagged/obs (LOSO): " + " ".join("%d:%.2f" % (s, x["flagged"] / max(1, x["obs"])) for s, x in zip(ovl, ps)))
        P("   AUC pooled over LOSO folds %.3f; mean of per-season AUC %.3f" % (
            auc(dall.y, p), np.mean([auc(dall.y[dall.season == s], p[dall.season == s]) for s in ovl])))

    # ------------------------------------------------------------- 11 TC contaminant
    P("")
    P("11. TRANSITIONING TROPICAL CYCLONES")
    P("   Flag: an ERA5 candidate within %d km, at the same valid time, of an IBTrACS v04r01 position (any nature," % TC_MATCH_KM)
    P("   NA+EP+WP) of a storm that was tropical (NATURE=TS) at some time; then the whole linked track. The archive")
    P("   itself marks only a handful of tropical fixes (category TC), far too few to mask from.")
    try:
        ntrop, nmark = tag_tc(cands)
    except Exception as e:                                      # no network, say so
        P("   IBTrACS unavailable (%r): section 11 NOT RUN." % (e,))
        ntrop = None
    if ntrop is not None:
        P("   IBTrACS: %d storms with a tropical record; %d candidates (of %d) within %d km of one; written to %s" % (
            ntrop, nmark, len(cands), TC_MATCH_KM, os.path.basename(TC_CSV)))
        P("   Check against the archive: archive fixes it labels TC (tropical), matched to an ERA5 candidate within 400 km,")
        P("   and whether the IBTrACS flag caught them.")
        byt = {}
        for c in cands:
            byt.setdefault((c["basin"], c["t"]), []).append(c)
        n_tc = n_cand = n_flag = 0
        for f in ef.load_archive():
            if f["cat"] != "TC" or f["season"] not in seasons:
                continue
            n_tc += 1
            best = None
            for c in byt.get((f["basin"], f["t"]), []):
                dd = ef.hav1(f["lat"], f["lon"], c["lat"], c["lon"])
                if dd <= ef.MATCH_KM and (best is None or dd < best[0]):
                    best = (dd, c)
            if best:
                n_cand += 1
                n_flag += best[1]["tctrack"]
        P("   archive TC fixes in the cached seasons: %d; with an ERA5 candidate %d; of those on a flagged track %d" % (n_tc, n_cand, n_flag))
        tcm = np.array([r["tctrack"] for r in dall.rows], bool)
        P("   Fit population (pos+neg, %d seasons): flagged rows %d (%.1f%%); positives on flagged tracks %d of %d (%.1f%%)" % (
            len(ovl), tcm.sum(), 100 * tcm.mean(), int((tcm & (dall.y == 1)).sum()), int(dall.y.sum()),
            100 * (tcm & (dall.y == 1)).sum() / dall.y.sum()))
        for lab, ss in (("early", EARLY), ("late", LATE)):
            m = np.isin(dall.season, ss)
            P("     %-5s window: flagged rows %.1f%% of rows, flagged positives %.1f%% of positives" % (
                lab, 100 * tcm[m].mean(), 100 * (tcm & m & (dall.y == 1)).sum() / max(1, (m & (dall.y == 1)).sum())))
        for bs in ("atl", "pac"):
            m = dall.basin == bs
            P("     %-5s basin : flagged rows %.1f%%, flagged positives %.1f%% of positives" % (
                bs, 100 * tcm[m].mean(), 100 * (tcm & m & (dall.y == 1)).sum() / max(1, (m & (dall.y == 1)).sum())))
        keep = ~tcm
        # model A: fit on everything, scored on the non-TC rows. model B: fit on non-TC rows, scored on them.
        P("   (M0 is a gust threshold, so at a count-matched cut refitting it on fewer rows cannot change which rows are")
        P("   flagged; it is shown once below only to say so.)")
        for model in ("M1", "M0"):
            pA, fA = loso(dall, model, None, keep)
            pB, fB = loso(dall, model, keep, keep)
            dk = subset(dall, keep)
            yk = dall.y[keep]
            sA, sB = skill(yk, fA[keep]), skill(yk, fB[keep])
            aA, aB = auc(yk, pA[keep]), auc(yk, pB[keep])
            dh, da = [], []
            for _ in range(NBOOT):
                i = boot_idx(dk)
                a_, b_ = skill(yk[i], fA[keep][i]), skill(yk[i], fB[keep][i])
                dh.append(b_["hss"] - a_["hss"])
                da.append(auc(yk[i], pB[keep][i]) - auc(yk[i], pA[keep][i]))
            P("")
            P("   %s, scored on the %d non-TC rows (LOSO over %d seasons, cut count-matched on the non-TC training rows)" % (model, keep.sum(), len(ovl)))
            P(fmt_sk("A: fit on all rows (TC included)", sA))
            P(fmt_sk("B: fit on non-TC rows only", sB))
            P("   AUC A %.4f  B %.4f   B-A %+.4f [%+.4f, %+.4f];  HSS B-A %+.4f [%+.4f, %+.4f]" % (
                aA, aB, aB - aA, *np.percentile(da, [2.5, 97.5]), sB["hss"] - sA["hss"], *np.percentile(dh, [2.5, 97.5])))
            cols_ = MODELS[model] if model in MODELS else [0]
            bA = fit_logit(design(dall, model), dall.y)
            bB = fit_logit(design(dall, model)[keep], dall.y[keep])
            P("   coefficients, full fit: all rows " + " ".join("%.3f" % v for v in bA) + " | non-TC rows " + " ".join("%.3f" % v for v in bB))
            if model == "M1":
                tcrows = tcm
                pT = loso(dall, model)[0]
                P("   Model A on the TC-flagged rows alone: n=%d pos=%d, AUC %.3f (non-TC rows: %.3f); mean p %.3f vs observed %.3f" % (
                    tcrows.sum(), int(dall.y[tcrows].sum()), auc(dall.y[tcrows], pT[tcrows]) if dall.y[tcrows].sum() else float("nan"),
                    auc(yk, pT[keep]), pT[tcrows].mean(), dall.y[tcrows].mean()))

    # ------------------------------------------------------------- 12 basin term
    P("")
    P("12. BASIN TERM (a priori: the basins differ in cyclone structure and in land influence; model M1B = M1 + 1[Pacific])")
    pM, fM = loso(dall, "M1")
    pB, fB = loso(dall, "M1B")
    bB = fit_logit(design(dall, "M1B"), dall.y)
    bM = fit_logit(design(dall, "M1"), dall.y)
    bs = np.array([fit_logit(design(dall, "M1B")[i], dall.y[i]) for i in [boot_idx(dall) for _ in range(NBOOT // 2)]])
    se = bs.std(0)
    P("   full-fit coefficients with the basin term (bootstrap se over tracks):")
    for nm, v, s_ in zip(["b0", "gust/10kt", "ln(1+A64/1e3km2)", "grad hPa/100km", "(pmin-980)/10", "Pacific"], bB, se):
        P("     %-18s %8.3f  se %.3f  z %.1f" % (nm, v, s_, v / s_))
    P("   without: " + " ".join("%.3f" % v for v in bM))
    P("   LOSO calibration by basin: sum of held-out p over pos+neg rows divided by archive HF moments")
    P("   %-5s %-7s %8s %8s %8s | %s" % ("basin", "model", "sum p", "obs", "ratio", "per-season ratios; mean sd t(mean-1)"))
    for bsn in ("atl", "pac"):
        for nm, pp in (("M1", pM), ("M1B", pB)):
            m = dall.basin == bsn
            rr = np.array([pp[m & (dall.season == s)].sum() / max(1, dall.y[m & (dall.season == s)].sum()) for s in ovl])
            P("   %-5s %-7s %8.1f %8d %8.3f | mean %.3f sd %.3f t=%.2f (over %d, under %d of %d seasons)" % (
                bsn, nm, pp[m].sum(), int(dall.y[m].sum()), pp[m].sum() / dall.y[m].sum(), rr.mean(), rr.std(ddof=1),
                (rr.mean() - 1) / (rr.std(ddof=1) / math.sqrt(len(rr))), int((rr > 1).sum()), int((rr < 1).sum()), len(rr)))
    for nm, pp, ff in (("M1", pM, fM), ("M1B", pB, fB)):
        s_ = skill(dall.y, ff)
        P("   %-4s LOSO pooled AUC %.4f; HSS %.3f POD %.3f FAR %.3f at the count-matched cut (flagged %d, obs %d)" % (
            nm, auc(dall.y, pp), s_["hss"], s_["pod"], s_["far"], s_["flagged"], s_["obs"]))
        for bsn in ("atl", "pac"):
            m = dall.basin == bsn
            s2 = skill(dall.y[m], ff[m])
            P("        %s basin: flagged %d obs %d  POD %.3f FAR %.3f HSS %.3f  AUC %.4f" % (
                bsn, s2["flagged"], s2["obs"], s2["pod"], s2["far"], s2["hss"], auc(dall.y[m], pp[m])))

    # ------------------------------------------------------------- 14 position check (placed before 13 in code)
    land = np.array([r["land500"] for r in dall.rows])
    P("")
    P("14. DOES THE MASKED CRITERION STILL DEPEND ON LAND NEARBY? (the position-contamination concern)")
    P("   Held-out (LOSO) M1 probability summed over pos+neg rows divided by archive HF moments, by the land share")
    P("   of the 500 km disc around the centre (land500; the gust features see sea only). A criterion free of")
    P("   land/orographic leakage should sit near 1.00 in every stratum; the sea-only mask removes the land gusts")
    P("   but cannot remove a centre's proximity to land from the other features, so this is a check, not a guarantee.")
    P("   stratum (land500)      rows    obs   sum p  ratio    AUC")
    for lo_, hi_ in ((0.0, 0.05), (0.05, 0.2), (0.2, 0.4), (0.4, 1.01)):
        m = (land >= lo_) & (land < hi_)
        P("   %.2f <= land < %.2f %7d %6d %7.1f %6.2f %6.3f" % (
            lo_, min(hi_, 1.0), m.sum(), int(dall.y[m].sum()), pM[m].sum(), pM[m].sum() / max(1, dall.y[m].sum()),
            auc(dall.y[m], pM[m]) if dall.y[m].sum() else float("nan")))
    lat_ = np.array([r["lat"] for r in dall.rows])
    P("   by centre latitude:")
    for lo_, hi_ in ((30, 40), (40, 50), (50, 60), (60, 71)):
        m = (lat_ >= lo_) & (lat_ < hi_)
        P("   %2d <= lat < %2d    %7d %6d %7.1f %6.2f %6.3f" % (
            lo_, hi_, m.sum(), int(dall.y[m].sum()), pM[m].sum(), pM[m].sum() / max(1, dall.y[m].sum()),
            auc(dall.y[m], pM[m]) if dall.y[m].sum() else float("nan")))
    allc = [c for c in cands if c["p"] <= P_FIT]
    la_ = np.array([c["land500"] for c in allc])
    P("   exposure left after masking, all scored rows (centre <= %d hPa): land500 > 0.10 in %.0f%% of rows, > 0.30 in %.0f%%" % (
        P_FIT, 100 * (la_ > 0.10).mean(), 100 * (la_ > 0.30).mean()))
    pos_ = np.array([r["land500"] for r, y in zip(dall.rows, dall.y) if y == 1])
    P("   archive-HF positives: median land500 %.2f, share with land500 > 0.30: %.0f%%" % (np.median(pos_), 100 * (pos_ > 0.30).mean()))

    # ------------------------------------------------------------- 13 series check
    P("")
    P("13. SERIES-LEVEL STATIONARITY CHECK, WITH AND WITHOUT THE BASIN TERM")
    P("   Same quantities as series.py section 5, computed here for both M1 and M1B so they are comparable.")
    P("   p is the full-overlap fit (in-sample, all %d seasons 2004+) applied to EVERY scored row (centre <= %d hPa)" % (len(ovl), P_FIT))
    P("   in every cached season; 'sum' is per season; archive pos = HF-matched candidate moments (all pressures).")
    import series as S
    R = [c for c in cands if c["p"] <= P_FIT]
    Xr = feature_matrix(R)
    Xr5 = np.column_stack([Xr, [1.0 if c["basin"] == "pac" else 0.0 for c in R]])
    seas = sorted({c["season"] for c in R})
    season = np.array([c["season"] for c in R])
    cls = np.array([c["cls"] if c["season"] >= 2004 else "" for c in R])
    pos_mom = {s: sum(1 for c in cands if c["season"] == s and c["cls"] == "pos") for s in ovl}
    out = {}
    for nm, X_, b_ in (("M1", Xr, bM), ("M1B", Xr5, bB)):
        pr = predict(b_, X_)
        sums = {s: float(pr[season == s].sum()) for s in seas}
        sfit = {s: float(pr[(season == s) & np.isin(cls, ["pos", "neg"])].sum()) for s in ovl}
        out[nm] = (pr, sums, sfit)
    def reg(label, ss, dct):
        r = S.ols(ss, [dct[s] for s in ss])
        crit = S.tcrit(r["n"] - 2)
        P("   %-58s n=%2d slope %+8.2f /decade (+-%.2f) t=%s crit %.2f %s" % (
            label, r["n"], 10 * r["b"], 10 * r["ci"], S.fmt_t(r["t"]), crit,
            "SIGNIFICANT" if abs(r["t"]) > crit else ("borderline" if abs(r["t"]) > 2 else "")))
        return r
    for nm in ("M1", "M1B"):
        pr, sums, sfit = out[nm]
        P("   --- %s" % nm)
        reg("sum p, all scored rows, %d overlap seasons" % len(ovl), ovl, sums)
        reg("sum p, pos+neg rows (fitted population)", ovl, sfit)
        reg("ARCHIVE HF-matched moments (same for both models)", ovl, pos_mom)
        reg("(sum p, pos+neg) MINUS archive moments", ovl, {s: sfit[s] - pos_mom[s] for s in ovl})
        r_all = reg("(sum p, ALL scored rows) MINUS archive moments  [the series.py flag line]", ovl,
                    {s: sums[s] - pos_mom[s] for s in ovl})
        gray = {s: float(pr[(season == s) & (cls == "gray")].sum()) for s in ovl}
        reg("sum p, gray rows only", ovl, gray)
        reg("sum p, all rows, ALL %d seasons %d..%d" % (len(seas), seas[0], seas[-1]), seas, sums)
        pre = [s for s in seas if s <= 2000]
        reg("sum p, all rows, pre-2001 (%d seasons)" % len(pre), pre, sums)
        post = [s for s in seas if s >= 2004]
        w = S.welch([sums[s] for s in pre], [sums[s] for s in post])
        P("   %-58s pre-2001 mean %.1f, 2004+ mean %.1f, diff %+.1f (se %.1f, t=%s)" % (
            "level step pre-2001 -> 2004+ (Welch)", np.mean([sums[s] for s in pre]), np.mean([sums[s] for s in post]),
            w["d"], w["se"], S.fmt_t(w["t"])))
        # the same by tercile of the full record for a model-free feel
        scored = {s: int((season == s).sum()) for s in seas}
        if nm == "M1":
            reg("scored rows alone (no model), all seasons", seas, scored)
    # ---- robustness of the flag line, and where the trend sits
    pr, sums, sfit = out["M1"]
    gap = {s: sums[s] - pos_mom[s] for s in ovl}
    xs = np.array(ovl, float)
    ys = np.array([gap[s] for s in ovl])
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i]) for i in range(len(xs)) for j in range(i + 1, len(xs))]
    sgn = sum(np.sign(ys[j] - ys[i]) for i in range(len(xs)) for j in range(i + 1, len(xs)))
    nn = len(xs)
    mk = (sgn - np.sign(sgn)) / math.sqrt(nn * (nn - 1) * (2 * nn + 5) / 18.0)
    jk = []
    for k in range(nn):
        m = np.arange(nn) != k
        r = S.ols(xs[m], ys[m])
        jk.append((r["t"], 10 * r["b"], int(xs[k])))
    P("")
    P("   Robustness of the flag line, (sum p ALL rows) MINUS archive moments, M1:")
    P("     Theil-Sen slope %+.2f /decade; Mann-Kendall z %+.2f (|z|>1.96 is significant at 95%%)" % (10 * np.median(slopes), mk))
    P("     leave-one-season-out OLS: slope range %+.1f .. %+.1f /decade, t range %.2f .. %.2f (dropping %d gives the smallest |t|)" % (
        min(j[1] for j in jk), max(j[1] for j in jk), min(j[0] for j in jk), max(j[0] for j in jk), min(jk, key=lambda j: abs(j[0]))[2]))
    # where the model sum sits: subtype of gray rows, per-season table
    amb = np.array([bool(c["amb"]) for c in R])
    gtrk = lambda s: float(pr[(season == s) & (cls == "gray") & ~amb].sum())
    gamb = lambda s: float(pr[(season == s) & (cls == "gray") & amb].sum())
    pre_sum = lambda s: float(pr[(season == s) & (cls == "")].sum())
    reg("sum p, gray rows ON an HF-matched track (not tip-jet related)", ovl, {s: gtrk(s) for s in ovl})
    reg("sum p, gray rows near an archive tip-jet / no-centre HF fix", ovl, {s: gamb(s) for s in ovl})
    P("   per season (M1): archive moments | sum p pos+neg | gray on HF track | gray tip-jet | all rows | all - archive | M1B all rows")
    for s in ovl:
        P("     %d  %5d | %7.1f | %7.1f | %6.1f | %7.1f | %+7.1f | %7.1f" % (
            s, pos_mom[s], sfit[s], gtrk(s), gamb(s), sums[s], gap[s], out["M1B"][1][s]))
    # archive-side and track-side decomposition of the gray growth
    det_, ev_ = ef.detection(seasons)
    ev_n = {s: sum(1 for k in ev_ if k[0] == s and k[3] == "low") for s in ovl}
    ev_fix = {s: sum(v[0] for k, v in ev_.items() if k[0] == s and k[3] == "low") for s in ovl}
    ngray = {s: float(((season == s) & (cls == "gray") & ~amb).sum()) for s in ovl}
    ptrk = {s: float(len({(c["basin"], c["track"]) for c in R if c["season"] == s and c["cls"] == "pos"})) for s in ovl}
    P("")
    P("   Where does the gray growth come from? Archive side vs ERA5 side (22 overlap seasons):")
    reg("ARCHIVE: HF 'low' events with a fix in the domains", ovl, ev_n)
    reg("ARCHIVE: HF fixes in the domains (all, incl. undetected)", ovl, ev_fix)
    reg("ARCHIVE: HF fixes per event", ovl, {s: ev_fix[s] / ev_n[s] for s in ovl})
    reg("ERA5: linked tracks containing an archive-HF match", ovl, ptrk)
    reg("ERA5: gray rows on those tracks (count)", ovl, ngray)
    reg("ERA5: gray rows per HF track", ovl, {s: ngray[s] / ptrk[s] for s in ovl})
    reg("ERA5: mean p per gray row (M1)", ovl, {s: gtrk(s) / ngray[s] for s in ovl})
    # does ERA5's own sea-gust field trend, given the pressure? (model-free)
    P("")
    P("   Model-free: do the ERA5 FEATURES trend over the overlap seasons? Rows are scored cyclone-moments (centre <= %d hPa)." % P_FIT)
    g500 = np.array([c["g500"] for c in R])
    pm = np.array([c["pmin"] for c in R])
    a64 = np.array([c["a64"] for c in R])
    band = (pm >= 955) & (pm <= 975)
    def per(f):
        return {s: float(f(season == s)) for s in seas}
    feats = [("rows scored", per(lambda m: m.sum())),
             ("rows with pmin <= 960 hPa (depth only)", per(lambda m: (m & (pm <= 960)).sum())),
             ("rows with sea gust >= 64 kt", per(lambda m: (m & (g500 >= 64)).sum())),
             ("rows with sea gust >= 64 kt and pmin > 975 hPa", per(lambda m: (m & (g500 >= 64) & (pm > 975)).sum())),
             ("mean sea gust, rows with 955 <= pmin <= 975 (kt)", per(lambda m: g500[m & band].mean())),
             ("mean ln(1+A64), rows with 955 <= pmin <= 975", per(lambda m: np.log1p(a64[m & band] / 1000.0).mean()))]
    for lab, dct in feats:
        reg(lab + " [%d seasons]" % len(ovl), ovl, dct)
    for lab, dct in feats[1:4]:
        reg(lab + " [all %d seasons]" % len(seas), seas, dct)
    pre_ = [s for s in seas if s <= 2000]
    if len(pre_) >= 6:
        P("   The same model-free features in the 1979-2000 seasons alone (%d seasons, before any archive exists):" % len(pre_))
        for lab, dct in feats[1:]:
            reg(lab + " [pre-2001]", pre_, dct)
        reg("sum p (M1, all rows) [pre-2001]", pre_, sums)
    P("")
    P("   Per season, all %d: sum p (M1, all rows) | rows pmin<=960 | rows gust>=64 kt | rows gust>=64 & pmin>975 | mean gust (955<=pmin<=975)" % len(seas))
    for s in seas:
        P("     %d  %7.1f | %5d | %5d | %5d | %5.1f%s" % (
            s, sums[s], feats[1][1][s], feats[2][1][s], feats[3][1][s], feats[4][1][s], "   (archive overlap)" if s >= 2004 else ""))
    P("   Reading: the trend in (series - archive) over the overlap is the test. The archive counts are the")
    P("   benchmark; a slope beyond what they do means the criterion imports a trend the fields lack.")
    return dict(dall=dall, bM=bM, bB=bB)


# --- report ---------------------------------------------------------------------

def run():
    buf = io.StringIO()

    def P(*a):
        print(*a, file=buf)
        print(*a, flush=True)

    seasons = sorted(int(f[13:17]) for f in os.listdir(HERE)
                     if f.startswith("event_fields_") and f.endswith(".csv")
                     and f[13:17].isdigit())
    cands = ef.write_labelled(seasons)
    # basin-seasons the archive does not cover completely (see header)
    covered = [c for c in cands if not (c["basin"] == "atl" and c["season"] < 2004)]

    P("ERA5 hurricane-force-equivalent criterion: cross-period transfer test")
    P("=" * 72)
    P("The criterion is a PROXY: it reproduces what OPC's archive called hurricane")
    P("force from ERA5 cyclone features. It cannot be validated before 2001. These")
    P("results are a necessary condition for backward use, not a sufficient one.")
    P("")
    P("Seasons fetched: %s   (season N = 1 Sep N to 31 May N+1)" % seasons)
    P("Early window used: %s (both basins; archive RECORD_START = 2004)" % (EARLY,))
    P("Late window used : %s" % (LATE,))
    P("Sensitivity S2   : early window plus Pacific %s" % (EARLY_S2_PAC,))
    P("NOT the nominal 2001-2005: the archive is short-counted before 2004-05 (Pacific")
    P("begins Feb 2002, Atlantic Sep 2003), so uncovered HF cyclones would be labelled")
    P("negative and the label noise would differ by period. Windows are 2 and 5 seasons.")
    P("")

    # ---- 1. counts
    P("1. CANDIDATE AND POSITIVE COUNTS")
    P("   cand = ERA5 closed lows >=4 hPa deep and <1005 hPa (month.py detector)")
    P("   fit  = cand with smoothed centre <= %d hPa; pos/neg/gray as in event_fields.py" % P_FIT)
    P("   tracks = linked cyclone tracks among fit candidates")
    P("   season basin   cand    fit    pos    neg   gray  tracks  pos-rate(pos/(pos+neg))")
    for s in seasons:
        for b in ("atl", "pac"):
            cs = [c for c in cands if c["season"] == s and c["basin"] == b]
            if not cs:
                continue
            fit = [c for c in cs if c["p"] <= P_FIT]
            n = {k: sum(c["cls"] == k for c in fit) for k in ("pos", "neg", "gray")}
            tr = len({c["track"] for c in fit})
            flag = "   (archive not complete: excluded)" if (b == "atl" and s < 2004) else ""
            P("   %d  %s  %6d %6d %6d %6d %6d %7d   %.3f%s" % (
                s, b, len(cs), len(fit), n["pos"], n["neg"], n["gray"], tr,
                n["pos"] / max(1, n["pos"] + n["neg"]), flag))
    P("")

    # ---- 2. detection
    det, ev = ef.detection(seasons)
    P("2. DETECTION OF ARCHIVE HF FIXES")
    P("   An archive HF fix is 'detected' if an ERA5 candidate (>=4 hPa deep, <1005 hPa)")
    P("   lies within 400 km at the same valid time. Fixes outside the domains or at")
    P("   time steps ERA5 failed to serve are not counted. The pilot reported 95%.")
    P("   Archive event class matters: 'tipjet' and 'nocentre' HF fixes have no analysed")
    P("   cyclone centre (Greenland terrain jets mostly), so no centre detector can find")
    P("   them; 'low' is the population a cyclone criterion is about.")
    P("   season basin  low fixes  detected   rate   (centre<=%d)   | tipjet/nocentre fixes  detected" % P_FIT)
    tot = {}
    seen = sorted({(s, b) for (s, b, k) in det})
    for (s, b) in seen:
        lo = det.get((s, b, "low"), [0, 0, 0])
        oth = [sum(det.get((s, b, k), [0, 0, 0])[i] for k in ("tipjet", "nocentre")) for i in range(3)]
        inc = b == "atl" and s < 2004
        P("   %d  %s   %7d  %8d  %5.1f%%   %5.1f%%        | %10d %17d%s" % (
            s, b, lo[0], lo[1], 100 * lo[1] / max(1, lo[0]), 100 * lo[2] / max(1, lo[0]), oth[0], oth[1],
            "   (archive incomplete)" if inc else ""))
        if not inc:
            for key in ("all",) + (("early",) if s in EARLY else ()) + (("late",) if s in LATE else ()):
                t = tot.setdefault(key, [0, 0, 0, 0, 0])
                t[0] += lo[0]; t[1] += lo[1]; t[2] += lo[2]; t[3] += oth[0]; t[4] += oth[1]
    for k, (n, h, h990, on, oh) in tot.items():
        P("   TOTAL %-5s 'low' HF fixes %d, detected %d (%.1f%%), detected with centre <=%d hPa %d (%.1f%%); tipjet/nocentre %d, detected %d (%.1f%%)" % (
            k, n, h, 100 * h / n, P_FIT, h990, 100 * h990 / n, on, oh, 100 * oh / max(1, on)))
    en = [(v, k[3]) for k, v in ev.items() if not (k[1] == "atl" and k[0] < 2004)]
    for cl in ("low", "tipjet", "nocentre"):
        e = [v for v, c_ in en if c_ == cl]
        if e:
            P("   EVENT level, class %-8s: %d archive HF events with a fix in the domains; %d have >=1 fix detected (%.1f%%)" % (
                cl, len(e), sum(v[1] > 0 for v in e), 100 * sum(v[1] > 0 for v in e) / len(e)))
    P("")

    # ---- data
    early = build(covered, EARLY)
    late = build(covered, LATE)
    P("3. ANALYSIS SAMPLE (fit population, pos + neg only)")
    for name, d in (("early", early), ("late", late)):
        P("   %-5s n=%d  pos=%d  neg=%d  tracks=%d  pos-rate=%.3f" % (
            name, len(d.y), d.y.sum(), len(d.y) - d.y.sum(), len(d.groups), d.y.mean()))
    allfit = [c for c in covered if c["p"] <= P_FIT and c["season"] in EARLY + LATE]
    gray = {k: sum(c["cls"] == "gray" and ((c["season"] in EARLY) == (k == "early")) for c in allfit)
            for k in ("early", "late")}
    P("   gray (excluded from the primary fit): early %d, late %d" % (gray["early"], gray["late"]))
    P("")
    P("   Feature medians (descriptive only; nothing here chose the model)")
    P("   %-8s %-5s %9s %9s %9s %9s" % ("", "", "gust kt", "area64 km2", "grad", "pmin hPa"))
    for name, d in (("early", early), ("late", late)):
        for lab, m in (("pos", d.y == 1), ("neg", d.y == 0)):
            P("   %-8s %-5s %9.1f %9.0f %9.2f %9.1f" % (
                name, lab, np.median(d.X[m, 0] * 10), np.median(np.expm1(d.X[m, 1]) * 1000),
                np.median(d.X[m, 2]), np.median(d.X[m, 3] * 10 + 980)))
    P("   Univariate AUC, pos vs neg, in-period (descriptive; pilot reported track-level 0.93):")
    for j, nm in enumerate(["gust", "log area64", "gradient", "-pmin"]):
        sgn = -1 if nm == "-pmin" else 1
        P("     %-11s early %.3f   late %.3f" % (
            nm, auc(early.y, sgn * early.X[:, j]), auc(late.y, sgn * late.X[:, j])))
    P("")

    def fitmodel(d, cols):
        return fit_logit(d.X[:, cols], d.y)

    # ---- 4. coefficients
    P("4. COEFFICIENTS: fit once per period, bootstrap SE over cyclone tracks (%d reps)" % NBOOT)
    P("   logit P(HF-equivalent) = b0 + sum(b_i x_i); x in the fixed units listed in the header")
    names = {"M1": ["b0", "gust/10kt", "ln(1+A64/1e3km2)", "grad hPa/100km", "(pmin-980)/10"],
             "M0": ["b0", "gust/10kt"]}
    coef = {}
    for mname, cols in MODELS.items():
        be = fitmodel(early, cols)
        bl = fitmodel(late, cols)
        bs_e, bs_l = [], []
        for _ in range(NBOOT):
            ie, il = boot_idx(early), boot_idx(late)
            bs_e.append(fit_logit(early.X[ie][:, cols], early.y[ie]))
            bs_l.append(fit_logit(late.X[il][:, cols], late.y[il]))
        bs_e, bs_l = np.array(bs_e), np.array(bs_l)
        se_e, se_l = bs_e.std(0), bs_l.std(0)
        coef[mname] = (be, bl, se_e, se_l)
        P("   %s" % mname)
        P("   %-18s %9s %7s %9s %7s %9s %7s %7s" % ("term", "early", "se", "late", "se", "late-early", "se", "z"))
        for i, nm in enumerate(names[mname]):
            dd = bl[i] - be[i]
            sd = math.hypot(se_e[i], se_l[i])
            P("   %-18s %9.3f %7.3f %9.3f %7.3f %9.3f %7.3f %7.2f" % (
                nm, be[i], se_e[i], bl[i], se_l[i], dd, sd, dd / sd))
        if mname == "M0":
            ge = -be[0] / be[1] * 10
            gl = -bl[0] / bl[1] * 10
            gb_e = -bs_e[:, 0] / bs_e[:, 1] * 10
            gb_l = -bs_l[:, 0] / bs_l[:, 1] * 10
            P("   M0 gust at which P = 0.5 (kt): early %.1f (se %.1f), late %.1f (se %.1f), shift %.1f kt (se %.1f)" % (
                ge, gb_e.std(), gl, gb_l.std(), gl - ge, math.hypot(gb_e.std(), gb_l.std())))
            allg = np.array([c["g500"] for c in covered if c["p"] <= P_FIT and c["season"] in LATE])
            nhi, nlo = (allg >= max(ge, gl)).sum(), (allg >= min(ge, gl)).sum()
            P("   Scale of that shift: in the late window %d fit-population candidates have gust >= %.1f kt and %d have >= %.1f kt (%.1f%% more)" % (
                nhi, max(ge, gl), nlo, min(ge, gl), 100 * (nlo - nhi) / nhi))
            P("   (the P=0.5 point sits where the class mix is, so it moves with the pos-rate;")
            P("    the slope on gust is the cleaner drift measure)")
    # M1 shift expressed in decision terms: log-odds difference at the pooled mean feature vector
    xbar = np.vstack([early.X, late.X]).mean(0)
    be, bl, se_e, se_l = coef["M1"]
    for lab, x in (("pooled-mean cyclone", xbar),
                   ("typical HF moment (pos median)", np.median(np.vstack([early.X[early.y == 1], late.X[late.y == 1]]), 0))):
        le = be[0] + x @ be[1:]
        ll = bl[0] + x @ bl[1:]
        P("   M1 predicted P at %s: early-fit %.3f, late-fit %.3f" % (lab, 1 / (1 + math.exp(-le)), 1 / (1 + math.exp(-ll))))
    P("")

    # ---- 5. transfer
    P("5. TRANSFER TEST (fit on one window, evaluate on the other; 95%% CI from track bootstrap of both sets, %d reps)" % NBOOT)
    P("   calibration: ratio = mean predicted / observed rate; slope = calibration slope")
    P("   (1 = perfect, <1 = the fitted model is too extreme for the new period); shift =")
    P("   log-odds offset the new period needs at slope 1.")
    res = {}
    for mname, cols in MODELS.items():
        for (tn, tr_, te_) in (("fit early -> test late", early, late), ("fit late -> test early", late, early)):
            b = fitmodel(tr_, cols)
            p = predict(b, te_.X[:, cols])
            a = auc(te_.y, p)
            cal = calib(te_.y, p)
            ba, br, bsl = [], [], []
            for _ in range(NBOOT):
                i1, i2 = boot_idx(tr_), boot_idx(te_)
                bb = fit_logit(tr_.X[i1][:, cols], tr_.y[i1])
                pp = predict(bb, te_.X[i2][:, cols])
                ba.append(auc(te_.y[i2], pp))
                br.append(pp.mean() / te_.y[i2].mean())
                bsl.append(calib(te_.y[i2], pp)["slope"])
            res[(mname, tn)] = (a, cal, np.percentile(ba, [2.5, 97.5]), np.percentile(br, [2.5, 97.5]), np.percentile(bsl, [2.5, 97.5]))
    P("   %-3s %-24s %7s %17s %7s %7s %7s %7s %7s %s" % (
        "mod", "direction", "AUC", "AUC 95% CI", "obs", "pred", "ratio", "slope", "shift", "ratio 95% CI"))
    for (mname, tn), (a, c, ci, cr, cs) in res.items():
        P("   %-3s %-24s %7.3f  [%5.3f, %5.3f] %7.3f %7.3f %7.2f %7.2f %7.2f  [%.2f, %.2f]  slope CI [%.2f, %.2f]" % (
            mname, tn, a, ci[0], ci[1], c["obs"], c["pred"], c["ratio"], c["slope"], c["shift"], cr[0], cr[1], cs[0], cs[1]))
    P("")
    P("   In-sample reference (fit and score on the same window; optimistic):")
    for mname, cols in MODELS.items():
        for nm, d in (("early", early), ("late", late)):
            b = fitmodel(d, cols)
            P("     %s %-5s AUC %.3f" % (mname, nm, auc(d.y, predict(b, d.X[:, cols]))))
    P("")
    P("   Reliability, M1, five equal-count bins of predicted probability on the test window")
    for tn, tr_, te_ in (("fit early -> test late", early, late), ("fit late -> test early", late, early)):
        b = fitmodel(tr_, MODELS["M1"])
        p = predict(b, te_.X)
        order = np.argsort(p)
        P("   %s" % tn)
        P("     bin   n    predicted   observed")
        for k, ix in enumerate(np.array_split(order, 5)):
            P("     %d  %5d    %.3f       %.3f" % (k + 1, len(ix), p[ix].mean(), te_.y[ix].mean()))
    P("")
    P("   By basin (M1, same coefficients, AUC on that basin's test candidates)")
    for tn, tr_, te_ in (("fit early -> test late", early, late), ("fit late -> test early", late, early)):
        b = fitmodel(tr_, MODELS["M1"])
        out = []
        for bs in ("atl", "pac"):
            m = te_.basin == bs
            out.append("%s %.3f (n=%d, pos=%d)" % (bs, auc(te_.y[m], predict(b, te_.X[m])), m.sum(), te_.y[m].sum()))
        P("     %-24s %s" % (tn, "   ".join(out)))
    P("")

    # ---- 6. within-period baselines
    P("6. WITHIN-PERIOD BASELINE: leave one season out (fit on the window's other seasons)")
    base = {}
    for mname, cols in MODELS.items():
        for nm, d, ss in (("early", early, EARLY), ("late", late, LATE)):
            aucs, ratios, slopes = [], [], []
            for s in ss:
                te = subset(d, d.season == s)
                tr_ = subset(d, d.season != s)
                b = fitmodel(tr_, cols)
                p = predict(b, te.X[:, cols])
                aucs.append(auc(te.y, p))
                c = calib(te.y, p)
                ratios.append(c["ratio"]); slopes.append(c["slope"])
                P("   %s %-5s hold out %d (train n=%d): AUC %.3f  pred/obs %.2f  cal-slope %.2f" % (
                    mname, nm, s, len(tr_.y), aucs[-1], ratios[-1], slopes[-1]))
            base[(mname, nm)] = (np.mean(aucs), np.min(aucs), np.max(aucs), np.mean(ratios), np.min(ratios), np.max(ratios))
            P("   %s %-5s mean AUC %.3f (folds %.3f-%.3f), mean pred/obs %.2f (folds %.2f-%.2f)" % (
                (mname, nm) + base[(mname, nm)]))
    P("")
    P("   Size-matched baseline for fit early -> test late: fit on any 2 late seasons,")
    P("   test on the other 3 (10 combinations). Early window has only 2 seasons, so")
    P("   the plain LOSO above trains the early window on 1 season and flatters nothing.")
    import itertools
    for mname, cols in MODELS.items():
        aucs, ratios = [], []
        for pair in itertools.combinations(LATE, 2):
            m = np.isin(late.season, pair)
            tr_, te = subset(late, m), subset(late, ~m)
            p = predict(fitmodel(tr_, cols), te.X[:, cols])
            aucs.append(auc(te.y, p))
            ratios.append(p.mean() / te.y.mean())
        P("   %s train 2 late seasons -> test other 3: AUC mean %.3f (range %.3f-%.3f), pred/obs mean %.2f (range %.2f-%.2f)" % (
            mname, np.mean(aucs), min(aucs), max(aucs), np.mean(ratios), min(ratios), max(ratios)))
    P("")

    P("7. HOW THE CROSS-PERIOD NUMBERS READ AGAINST THE WITHIN-PERIOD ONES")
    for mname in MODELS:
        for tn, nm in (("fit early -> test late", "late"), ("fit late -> test early", "early")):
            a, c, ci, cr, cs = res[(mname, tn)]
            bm = base[(mname, nm)]
            P("   %s %-24s cross AUC %.3f vs within-%s LOSO mean %.3f (folds %.3f-%.3f): gap %+.3f;  pred/obs %.2f vs within %.2f (folds %.2f-%.2f)" % (
                mname, tn, a, nm, bm[0], bm[1], bm[2], a - bm[0], c["ratio"], bm[3], bm[4], bm[5]))
    P("")

    # ---- 8. sensitivities (pre-specified, reported regardless of outcome)
    P("8. PRE-SPECIFIED SENSITIVITIES (reported whatever they show; the primary result is Section 5)")
    # S1: gray counted as negative
    e1 = build(covered, EARLY, cls=("pos", "neg", "gray"))
    l1 = build(covered, LATE, cls=("pos", "neg", "gray"))
    # build() labels gray as y=0 already
    for tn, tr_, te_ in (("fit early -> test late", e1, l1), ("fit late -> test early", l1, e1)):
        b = fitmodel(tr_, MODELS["M1"])
        p = predict(b, te_.X)
        c = calib(te_.y, p)
        P("   S1 gray as negative, M1 %-24s AUC %.3f  pred/obs %.2f  slope %.2f  (n test %d, pos %d)" % (
            tn, auc(te_.y, p), c["ratio"], c["slope"], len(te_.y), te_.y.sum()))
    # S2: add Pacific 2002 and 2003 to the early window
    s2 = build([c for c in cands if c["basin"] == "pac" and c["season"] in EARLY_S2_PAC], EARLY_S2_PAC) \
        if all(os.path.exists(ef.raw_path(s)) for s in EARLY_S2_PAC) else None
    if s2 is not None and len(s2.y):
        e2 = concat(early, s2)
        P("   S2 early window + Pacific 2002-03: n=%d pos=%d" % (len(e2.y), e2.y.sum()))
        for tn, tr_, te_ in (("fit early2 -> test late", e2, late), ("fit late -> test early2", late, e2)):
            b = fitmodel(tr_, MODELS["M1"])
            p = predict(b, te_.X)
            c = calib(te_.y, p)
            P("   S2 M1 %-24s AUC %.3f  pred/obs %.2f  slope %.2f" % (tn, auc(te_.y, p), c["ratio"], c["slope"]))
        aucs, ratios = [], []
        for s in tuple(EARLY) + EARLY_S2_PAC:
            te = subset(e2, e2.season == s)
            tr_ = subset(e2, e2.season != s)
            p = predict(fitmodel(tr_, MODELS["M1"]), te.X)
            aucs.append(auc(te.y, p)); ratios.append(p.mean() / te.y.mean())
        P("   S2 M1 within early2 LOSO (4 folds): AUC mean %.3f (folds %s), pred/obs %s" % (
            np.mean(aucs), "/".join("%.3f" % a for a in aucs), "/".join("%.2f" % r for r in ratios)))
    else:
        P("   S2 skipped (Pacific 2002/2003 not fetched)")
    P("")
    # ---- 9. post-hoc harder subset
    P("9. POST-HOC (added AFTER seeing that full-population AUC sits near 0.95-0.98; NOT part of the")
    P("   pre-specified analysis, and the model is NOT refit or altered - only the test set is narrowed)")
    P("   The primary negatives are mostly weak lows (median gust ~50 kt), which any gust feature")
    P("   separates easily. Here the same primary-fit models are scored only on 'contender'")
    P("   cyclones, raw minimum pressure <= 975 hPa, where the HF/non-HF call is genuinely hard.")
    for mname, cols in MODELS.items():
        for tn, tr_, te_ in (("fit early -> test late", early, late), ("fit late -> test early", late, early)):
            b = fitmodel(tr_, cols)
            m = (te_.X[:, 3] * 10 + 980) <= 975
            p = predict(b, te_.X[m][:, cols])
            c = calib(te_.y[m], p)
            P("   %s %-24s n=%d pos=%d (%.0f%% of pos) AUC %.3f  obs %.3f pred %.3f ratio %.2f slope %.2f" % (
                mname, tn, m.sum(), te_.y[m].sum(), 100 * te_.y[m].sum() / te_.y.sum(),
                auc(te_.y[m], p), c["obs"], c["pred"], c["ratio"], c["slope"]))
        for nm, d, ss in (("early", early, EARLY), ("late", late, LATE)):
            aucs, ratios = [], []
            for s in ss:
                te = subset(d, d.season == s)
                tr_ = subset(d, d.season != s)
                m = (te.X[:, 3] * 10 + 980) <= 975
                p = predict(fitmodel(tr_, cols), te.X[m][:, cols])
                aucs.append(auc(te.y[m], p)); ratios.append(p.mean() / te.y[m].mean())
            P("   %s within-%s LOSO on contenders: AUC mean %.3f (folds %s), pred/obs %s" % (
                mname, nm, np.mean(aucs), "/".join("%.3f" % a for a in aucs), "/".join("%.2f" % r for r in ratios)))
    P("")
    extended(P, cands, seasons)
    open(OUT, "w").write(buf.getvalue())
    print("wrote", OUT)


if __name__ == "__main__":
    run()
