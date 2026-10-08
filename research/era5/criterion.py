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
import io
import math
import os
import sys

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
        step = np.linalg.solve(H, g)
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
    d.X = np.array([[c["g500"] / 10.0, math.log1p(c["a64"] / 1000.0) , c["gradmax"],
                     (c["pmin"] - 980.0) / 10.0] for c in rows])
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
            ba, br = [], []
            for _ in range(NBOOT):
                i1, i2 = boot_idx(tr_), boot_idx(te_)
                bb = fit_logit(tr_.X[i1][:, cols], tr_.y[i1])
                pp = predict(bb, te_.X[i2][:, cols])
                ba.append(auc(te_.y[i2], pp))
                br.append(pp.mean() / te_.y[i2].mean())
            res[(mname, tn)] = (a, cal, np.percentile(ba, [2.5, 97.5]), np.percentile(br, [2.5, 97.5]))
    P("   %-3s %-24s %7s %17s %7s %7s %7s %7s %7s %s" % (
        "mod", "direction", "AUC", "AUC 95% CI", "obs", "pred", "ratio", "slope", "shift", "ratio 95% CI"))
    for (mname, tn), (a, c, ci, cr) in res.items():
        P("   %-3s %-24s %7.3f  [%5.3f, %5.3f] %7.3f %7.3f %7.2f %7.2f %7.2f  [%.2f, %.2f]" % (
            mname, tn, a, ci[0], ci[1], c["obs"], c["pred"], c["ratio"], c["slope"], c["shift"], cr[0], cr[1]))
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
            a, c, ci, cr = res[(mname, tn)]
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
    open(OUT, "w").write(buf.getvalue())
    print("wrote", OUT)


if __name__ == "__main__":
    run()
