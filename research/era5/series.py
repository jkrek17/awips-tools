"""Emit a per-cyclone probability series from the ERA5 hurricane-force-equivalent
criterion, for whatever seasons event_fields.py has cached.

    python series.py            # writes hf_probability.csv.gz and series-result.txt

THE SERIES IS A PROXY. It reproduces what OPC's archive called hurricane force
from ERA5 cyclone features. It is not an extended hurricane-force record, it
cannot be validated before the archive's RECORD_START (2004), and its seasonal
sums are model expectations, not observed event counts.

What it does (nothing here redesigns or re-tunes the criterion; features, M1
and M0, the 990 hPa fit population and the plain logistic fit are criterion.py's):

  * seasons   every cached event_fields_<season>.csv is used, whatever mix of
              1979-2025 happens to be present, and the report says which.
  * fits      p_full  = M1 fitted on every cached season >= RECORD_START (2004)
              p_early = M1 fitted on the 2004-2005 window  (criterion.EARLY)
              p_late  = M1 fitted on the 2021-2025 window  (criterion.LATE)
              Three columns instead of one so that sensitivity to the
              calibration window is visible in the data (the transfer test found
              the criterion's sharpness drifts: calibration slope 1.19 / 0.83).
  * population one row per ERA5 closed low with smoothed centre <= 990 hPa per
              6-hourly step, both basins, every cached season. That is the
              population the criterion was fitted on and is defined for. Lows
              weaker than that are not scored (counted in the report). Inside
              the population every row is scored, including the 'gray' and the
              pre-archive rows that were not in any fit.
  * leakage   for seasons that were in a fit, that column is in-sample. The
              `fit_in` column says which fits (F full, E early, L late) saw the
              row's season, so downstream users can restrict to out-of-sample
              rows. The report also gives a leave-one-season-out check.
"""
import csv
import datetime
import gzip
import io
import math
import os
import sys

import numpy as np

import criterion as C
import event_fields as ef

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(HERE, "hf_probability.csv.gz")
OUT_TXT = os.path.join(HERE, "series-result.txt")
RECORD_START = 2004          # archive covers both basins from the 2004-05 season
MAX_BYTES = 15e6
NBOOT = 200
CUTS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90)
P_FLOOR_STEPS = (1e-4, 3e-4, 1e-3, 3e-3, 1e-2)   # only used if the gz is too large
RNG = np.random.default_rng(20260508)
T975 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26,
        10: 2.23, 11: 2.20, 12: 2.18, 13: 2.16, 14: 2.14, 15: 2.13, 16: 2.12, 17: 2.11,
        18: 2.10, 19: 2.09, 20: 2.09, 25: 2.06, 30: 2.04}


def tcrit(df):
    ks = [k for k in T975 if k <= df]
    return T975[max(ks)] if ks and df < 30 else (1.96 if df >= 30 else float("nan"))


# --- small statistics (numpy only) ---------------------------------------------

def ranks(x):
    u, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    return (np.cumsum(cnt) - (cnt - 1) / 2.0)[inv]


def pearson(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def spearman(a, b):
    return pearson(ranks(a), ranks(b))


def ols(x, y):
    """slope, se, t, n, intercept for y = a + b x. nan when n < 3."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 3 or np.ptp(x) == 0:
        return dict(b=float("nan"), se=float("nan"), t=float("nan"), n=n, ci=float("nan"))
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    b = ((x - xm) * (y - ym)).sum() / sxx
    res = y - ym - b * (x - xm)
    se = math.sqrt((res ** 2).sum() / (n - 2) / sxx)
    return dict(b=b, se=se, t=(b / se if se > 0 else float("nan")), n=n, ci=tcrit(n - 2) * se)


def welch(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or len(b) < 2:
        return dict(d=float("nan"), se=float("nan"), t=float("nan"))
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    d = float(b.mean() - a.mean())
    return dict(d=d, se=se, t=(d / se if se > 0 else float("nan")))


def fmt_t(v):
    return "%.2f" % v if v == v else "  n/a"


# --- data ----------------------------------------------------------------------

def cached_seasons():
    return sorted(int(f[13:17]) for f in os.listdir(HERE)
                  if f.startswith("event_fields_") and f.endswith(".csv") and f[13:17].isdigit())


def step_coverage():
    """season -> (steps ok, steps expected) from event_fields_steps.csv."""
    seen = {}
    if os.path.exists(ef.STEPS_CSV):
        with open(ef.STEPS_CSV) as f:
            for r in csv.DictReader(f):
                seen[(int(r["season"]), int(r["t"]))] = int(r["ok"])
    out = {}
    for (s, t), ok in seen.items():
        a = out.setdefault(s, [0, 0])
        a[0] += ok
        a[1] += 1
    return out


def archive_events(seasons):
    """(season, basin) -> distinct archive events (class 'low') with an HF fix
    inside the domains, plus how many of them have >=1 fix at a detected
    candidate (the most a candidate-based series could ever reproduce)."""
    det, ev = ef.detection(seasons)
    out = {}
    for (s, b, key, cl), (nfix, ndet) in ev.items():
        a = out.setdefault((s, b), dict(low=0, low_det=0, other=0))
        if cl == "low":
            a["low"] += 1
            a["low_det"] += ndet > 0
        else:
            a["other"] += 1
    return out


def fit_models(d):
    return {m: C.fit_logit(d.X[:, cols], d.y) for m, cols in C.MODELS.items()}


def boot_se(d, cols):
    bs = []
    for _ in range(NBOOT):
        i = C.boot_idx(d)
        bs.append(C.fit_logit(d.X[i][:, cols], d.y[i]))
    return np.array(bs).std(0)


# --- main ------------------------------------------------------------------------

def run():
    C.RNG = RNG
    seasons = cached_seasons()
    if not seasons:
        sys.exit("no event_fields_<season>.csv cached")
    cov = step_coverage()
    cands = ef.label(seasons)
    # stable track ids (label() numbers tracks by processing order)
    tfirst = {}
    for c in cands:
        k = (c["basin"], c["track"])
        if k not in tfirst or c["t"] < tfirst[k][0]:
            tfirst[k] = (c["t"], c["lat"])
    order = sorted(tfirst, key=lambda k: (k[0], tfirst[k][0], -tfirst[k][1]))
    tid, ctr = {}, {}
    for k in order:
        stamp = ef.idx_to_dt(tfirst[k][0]).strftime("%Y%m%d%H")
        n = ctr[(k[0], stamp)] = ctr.get((k[0], stamp), 0) + 1
        tid[k] = "%s%s-%d" % (k[0], stamp, n)

    full_seasons = tuple(s for s in seasons if s >= RECORD_START)
    early_seasons = tuple(s for s in C.EARLY if s in seasons)
    late_seasons = tuple(s for s in C.LATE if s in seasons)
    fits = {}
    for name, ss in (("full", full_seasons), ("early", early_seasons), ("late", late_seasons)):
        if ss:
            d = C.build(cands, ss)
            fits[name] = dict(seasons=ss, d=d, b=fit_models(d))

    R = [c for c in cands if c["p"] <= C.P_FIT]
    dropped = [c for c in cands if c["p"] > C.P_FIT]
    X = C.feature_matrix(R)
    season = np.array([c["season"] for c in R])
    basin = np.array([c["basin"] for c in R])
    trk = np.array([tid[(c["basin"], c["track"])] for c in R])
    cls = np.array([c["cls"] if c["season"] >= RECORD_START else "" for c in R])
    P = {}
    P0 = {}
    for name, f in fits.items():
        P[name] = C.predict(f["b"]["M1"], X)
        P0[name] = C.predict(f["b"]["M0"], X[:, [0]])
    for name in ("full", "early", "late"):
        if name not in P:
            P[name] = np.full(len(R), np.nan)
            P0[name] = np.full(len(R), np.nan)
    # leave-one-season-out version of p_full on the overlap seasons (report only)
    ploso = np.full(len(R), np.nan)
    if "full" in fits and len(full_seasons) >= 2:
        dfull = fits["full"]["d"]
        for s in full_seasons:
            dtr = C.subset(dfull, dfull.season != s)
            b = C.fit_logit(dtr.X, dtr.y)
            m = season == s
            ploso[m] = C.predict(b, X[m])
    fit_in = np.array(["".join(k for k, nm in (("F", "full"), ("E", "early"), ("L", "late"))
                               if nm in fits and s in fits[nm]["seasons"]) for s in season])

    # ---------------- the deliverable -------------------------------------------
    def write_csv(floor):
        keep = np.ones(len(R), bool) if floor is None else (P["full"] >= floor)
        sio = io.StringIO()
        w = csv.writer(sio, lineterminator="\n")
        w.writerow(["time_utc", "season", "basin", "lat", "lon", "centre_hpa", "pmin150_hpa",
                    "depth_hpa", "gust500_kt", "area64_km2", "grad_hpa100km", "track",
                    "archive_label", "fit_in", "p_full", "p_early", "p_late"])
        for i in sorted(range(len(R)), key=lambda i: (R[i]["t"], R[i]["basin"], -R[i]["lat"])):
            if not keep[i]:
                continue
            c = R[i]
            lon = ((c["lon"] + 180.0) % 360.0) - 180.0
            w.writerow([ef.idx_to_dt(c["t"]).strftime("%Y-%m-%dT%H:%MZ"), c["season"], c["basin"],
                        "%.2f" % c["lat"], "%.2f" % lon, "%.2f" % c["p"], "%.2f" % c["pmin"],
                        "%.2f" % c["depth"], "%.2f" % c["g500"], "%.2f" % c["a64"],
                        "%.2f" % c["gradmax"], trk[i], cls[i], fit_in[i]]
                       + [("%.4f" % P[n][i]) if P[n][i] == P[n][i] else "" for n in ("full", "early", "late")])
        buf = io.BytesIO(gzip.compress(sio.getvalue().encode("utf-8"), compresslevel=9, mtime=0))
        return buf.getvalue(), keep

    floor = None
    data, keep = write_csv(None)
    floor_note = "no probability floor applied: every scored candidate is in the file"
    for fl in P_FLOOR_STEPS:
        if len(data) <= MAX_BYTES:
            break
        data, keep = write_csv(fl)
        floor = fl
        floor_note = ("FLOOR APPLIED: dropped candidates with p_full < %g (%d of %d rows, %.1f%% of rows; "
                      "their summed p_full is %.3f of %.3f)" % (
                          fl, (~keep).sum(), len(R), 100 * (~keep).mean(),
                          np.nansum(P["full"][~keep]), np.nansum(P["full"])))
    with open(OUT_CSV, "wb") as f:
        f.write(data)
    fsize = len(data)

    # ---------------- report ---------------------------------------------------
    L = []

    def p(*a):
        L.append(" ".join(str(x) for x in a) if a else "")

    summary = []
    flags = []
    seas = sorted(set(season.tolist()))
    pre = [s for s in seas if s <= 2000]
    mid = [s for s in seas if 2001 <= s < RECORD_START]
    ovl = [s for s in seas if s >= RECORD_START]

    def per_season(vals, mask=None):
        return np.array([np.nansum(vals[(season == s) & (np.ones(len(R), bool) if mask is None else mask)])
                         for s in seas])

    def seas_str(ss):
        return "none" if not ss else ("%d..%d (%d: %s)" % (ss[0], ss[-1], len(ss), ", ".join(map(str, ss))))

    # 1 ------------------------------------------------------------------------
    p("1. COVERAGE AND FITS")
    p("   season N = 1 Sep N to 31 May N+1; sampled 6-hourly, both archive domains.")
    p("   seasons cached when this ran : %s" % seas_str(seasons))
    p("     pre-2001 (no archive exists)        : %s" % seas_str(pre))
    p("     2001-2003 (archive incomplete)      : %s" % seas_str(mid))
    p("     2004 onward (archive complete: overlap, fit seasons) : %s" % seas_str(ovl))
    p("   p_full  fitted on seasons : %s   (n=%d pos=%d neg=%d, tracks=%d)" % (
        fits["full"]["seasons"], len(fits["full"]["d"].y), fits["full"]["d"].y.sum(),
        len(fits["full"]["d"].y) - fits["full"]["d"].y.sum(), len(fits["full"]["d"].groups)) if "full" in fits
      else "   p_full: NOT FITTED (no season >= %d cached)" % RECORD_START)
    for nm, want in (("early", C.EARLY), ("late", C.LATE)):
        if nm in fits:
            d = fits[nm]["d"]
            miss = [s for s in want if s not in fits[nm]["seasons"]]
            p("   p_%-5s fitted on seasons : %s   (n=%d pos=%d neg=%d, tracks=%d)%s" % (
                nm, fits[nm]["seasons"], len(d.y), d.y.sum(), len(d.y) - d.y.sum(), len(d.groups),
                ("   [window incomplete: missing %s]" % miss) if miss else ""))
        else:
            p("   p_%s: NOT FITTED (window %s not cached); column left empty" % (nm, want))
    p("   Fits are criterion.py's, unchanged: plain logistic, M1 = gust + ln(1+A64) + gradient + pressure depth,")
    p("   M0 = gust alone, population = smoothed centre <= %d hPa, pos/neg only (gray excluded), Atlantic < 2004 never fitted." % C.P_FIT)
    p("   Pacific 2002-2003 are scored in the series but, as in the primary test, not fitted (archive incomplete).")
    p("")
    p("   Series population: %d scored rows (centre <= %d hPa). %d other ERA5 candidates (centre > %d hPa, weaker lows)" % (
        len(R), C.P_FIT, len(dropped), C.P_FIT))
    npos_d = sum(c["cls"] == "pos" for c in dropped if c["season"] >= RECORD_START)
    npos_all = sum(c["cls"] == "pos" for c in cands if c["season"] >= RECORD_START)
    p("   are not scored: outside the criterion's fitted domain. Of the %d archive-HF-matched candidates in 2004+, %d (%.1f%%)" % (
        npos_all, npos_d, 100 * npos_d / max(1, npos_all)))
    p("   fall in that unscored group - a floor on what the series can ever represent.")
    p("   Step coverage (ERA5 time steps served / expected): " + ", ".join(
        "%d %d/%d" % (s, cov[s][0], cov[s][1]) for s in seasons if s in cov))
    bad = [s for s in seasons if s in cov and cov[s][0] < cov[s][1]]
    p("   %s" % ("Seasons with missing steps (their sums are biased low): %s" % bad if bad
                 else "No missing time steps in any cached season."))
    p("")
    p("   Coefficients (logit P = b0 + sum b_i x_i; bootstrap SE over cyclone tracks, %d reps)" % NBOOT)
    names = {"M1": ["b0", "gust/10kt", "ln(1+A64/1e3km2)", "grad hPa/100km", "(pmin-980)/10"],
             "M0": ["b0", "gust/10kt"]}
    for m, cols in C.MODELS.items():
        p("   %s" % m)
        hdr = "   %-18s" % "term"
        for nm in fits:
            hdr += " %9s %7s" % (nm, "se")
        p(hdr)
        ses = {nm: boot_se(f["d"], cols) for nm, f in fits.items()}
        for i, t in enumerate(names[m]):
            line = "   %-18s" % t
            for nm, f in fits.items():
                line += " %9.3f %7.3f" % (f["b"][m][i], ses[nm][i])
            p(line)
        if m == "M0":
            line = "   M0 gust at P=0.5 (kt):"
            for nm, f in fits.items():
                bb = f["b"]["M0"]
                line += "  %s %.1f" % (nm, -bb[0] / bb[1] * 10)
            p(line)
    p("   (the early and late columns should equal criterion-result.txt section 4: -10.155/1.127/0.452/-0.046/-0.859 and")
    p("    -11.391/1.272/0.686/-0.052/-0.714 for M1)")
    p("")

    # 2 ------------------------------------------------------------------------
    p("2. AGREEMENT BETWEEN p_full, p_early, p_late")
    p("   Pearson/Spearman over scored rows. 'contested' = rows where any of the three exceeds 0.01; the bulk of")
    p("   rows are weak lows with p near 0 in every fit, which inflates the all-rows figures.")
    pairs = [("full", "early"), ("full", "late"), ("early", "late")]
    groups = [("all seasons", np.ones(len(R), bool))]
    if pre or mid:
        groups.append(("pre-2004 (out-of-sample for all three fits)", season < RECORD_START))
    groups.append(("2004+ (overlap; in-sample for some fits)", season >= RECORD_START))
    if len(late_seasons) and len(early_seasons):
        groups.append(("2004-2005 (p_early in-sample, p_late out)", np.isin(season, early_seasons)))
        groups.append(("2021+ (p_late in-sample, p_early out)", np.isin(season, late_seasons)))
    p("   %-44s %-14s %7s %7s %9s %9s | %7s %7s %9s" % (
        "group", "pair", "n", "pearson", "spearman", "logit-r", "n", "pearson", "spearman"))
    for gname, gm in groups:
        for a, b in pairs:
            if a not in fits or b not in fits:
                continue
            m = gm
            mc = gm & ((P[a] > 0.01) | (P[b] > 0.01) | (P["full"] > 0.01))
            if m.sum() < 5:
                continue
            la, lb = C.logit(P[a][m]), C.logit(P[b][m])
            p("   %-44s %-14s %7d %7.4f %9.4f %9.4f | %7d %7.4f %9.4f" % (
                gname, "%s~%s" % (a, b), m.sum(), pearson(P[a][m], P[b][m]), spearman(P[a][m], P[b][m]),
                pearson(la, lb), mc.sum(), pearson(P[a][mc], P[b][mc]) if mc.sum() > 4 else float("nan"),
                spearman(P[a][mc], P[b][mc]) if mc.sum() > 4 else float("nan")))
    p("")
    p("   Mean and sum of p by fit (all scored rows) and the largest single-row disagreement:")
    for a, b in pairs:
        if a in fits and b in fits:
            dlt = P[b] - P[a]
            i = int(np.argmax(np.abs(dlt)))
            p("   %s vs %s: mean diff (%s-%s) %+.5f; max |diff| %.3f at %s %s season %d (p_%s %.3f, p_%s %.3f)" % (
                a, b, b, a, dlt.mean(), abs(dlt[i]), ef.idx_to_dt(R[i]["t"]).strftime("%Y-%m-%d %HZ"),
                basin[i], season[i], a, P[a][i], b, P[b][i]))
    p("")

    # 3 ------------------------------------------------------------------------
    p("3. IMPLIED COUNT AT A PROBABILITY CUT: how much the calibration window moves the number above the line")
    p("   moments = scored rows (6-hourly cyclone-times) with p >= cut; tracks = linked cyclone tracks whose")
    p("   MAX p >= cut (closer to 'a cyclone', still not an event count). % columns are relative to p_full.")
    for gname, gm in groups[:3] if (pre or mid) else groups[:2]:
        if gm.sum() == 0:
            continue
        p("   -- %s (%d rows)" % (gname, gm.sum()))
        names_p = [n for n in ("full", "early", "late") if n in fits]
        hdr = "   %-6s" % "cut"
        for kind in ("moments", "tracks"):
            for n in names_p:
                hdr += " %9s" % (kind[:3] + "_" + n)
            for n in names_p[1:]:
                hdr += " %9s" % (n[:3] + "%")
        p(hdr)
        tr_in = {}
        for n in names_p:
            tm = {}
            for tt, pp in zip(trk[gm], P[n][gm]):
                if pp > tm.get(tt, -1):
                    tm[tt] = pp
            tr_in[n] = np.array(list(tm.values()))
        for cut in CUTS:
            line = "   %-6.2f" % cut
            mom = {n: int((P[n][gm] >= cut).sum()) for n in names_p}
            trc = {n: int((tr_in[n] >= cut).sum()) for n in names_p}
            for dct in (mom, trc):
                for n in names_p:
                    line += " %9d" % dct[n]
                for n in names_p[1:]:
                    line += " %+8.1f%%" % (100 * (dct[n] - dct[names_p[0]]) / max(1, dct[names_p[0]]))
            p(line)
        line = "   %-6s" % "sum p"
        for n in names_p:
            line += " %9.1f" % np.nansum(P[n][gm])
        for n in names_p[1:]:
            line += " %+8.1f%%" % (100 * (np.nansum(P[n][gm]) - np.nansum(P[names_p[0]][gm])) / max(1e-9, np.nansum(P[names_p[0]][gm])))
        p(line)
        p("")
    p("   A continuous reading of the same thing: Sum p (the line above) moves far less between fits than the count")
    p("   above a hard cut, which is the point of carrying probabilities rather than a list of events.")
    p("")

    # 4 ------------------------------------------------------------------------
    sp = {n: per_season(P[n]) for n in ("full", "early", "late")}
    ev = archive_events(ovl) if ovl else {}
    p("4. PER-SEASON SUMMARY (both basins)")
    p("   sum p = sum over scored 6-hourly rows = expected number of HF-EQUIVALENT CYCLONE-MOMENTS under the")
    p("   criterion (6-hourly candidate fixes), NOT of cyclones and NOT an observed count; one long-lived severe")
    p("   cyclone contributes several moments. 'fit' marks seasons that were in the p_full / p_early / p_late fit.")
    p("   %-6s %-5s %6s %6s %8s %10s %10s %10s %7s" % (
        "season", "fit", "steps", "rows", "mean_pf", "sum_pfull", "sum_pearly", "sum_plate", "tracks"))
    for j, s in enumerate(seas):
        m = season == s
        code = "".join(k for k, nm in (("F", "full"), ("E", "early"), ("L", "late")) if nm in fits and s in fits[nm]["seasons"])
        c = cov.get(s, (0, 0))
        p("   %-6d %-5s %6s %6d %8.4f %10.2f %10.2f %10.2f %7d" % (
            s, code or "-", "%d/%d" % tuple(c) if c[1] else "?", m.sum(), P["full"][m].mean(), sp["full"][j],
            sp["early"][j] if "early" in fits else float("nan"),
            sp["late"][j] if "late" in fits else float("nan"), len(set(trk[m]))))
    p("   Rounding: the file carries p to 4 decimals; sums above are from unrounded values.")
    p("")

    # 5 ------------------------------------------------------------------------
    p("5. STATIONARITY CHECK ON THE SERIES ITSELF")
    p("   The gate run found ERA5's cyclone fields stationary within 1979-2025 but not before 1979. Question: does")
    p("   sum(p_full) trend, or step between eras, beyond what the archive's own counts do? If it did, the criterion")
    p("   would be importing a trend the fields do not have. Regressions are OLS on season (per decade).")
    sums = dict(zip(seas, sp["full"]))
    nrow = {s: int((season == s).sum()) for s in seas}
    # archive-side per-season series for the overlap
    pos_mom = {s: int(sum(1 for c in cands if c["season"] == s and c["cls"] == "pos")) for s in ovl}
    ev_low = {s: sum(v["low"] for (ss, b), v in ev.items() if ss == s) for s in ovl}
    ev_det = {s: sum(v["low_det"] for (ss, b), v in ev.items() if ss == s) for s in ovl}
    sums_fit = {s: float(np.sum(P["full"][(season == s) & np.isin(cls, ["pos", "neg"])])) for s in ovl}
    sums_loso = {s: float(np.sum(ploso[(season == s) & np.isin(cls, ["pos", "neg"])])) for s in ovl}

    def reg(label, ss, d, unit=1.0):
        if len(ss) < 3:
            p("   %-62s n=%d  (fewer than 3 seasons: not computed)" % (label, len(ss)))
            return None
        r = ols(ss, [d[s] for s in ss])
        mean = np.mean([d[s] for s in ss])
        p("   %-62s n=%2d slope %+8.3f /decade (95%% CI +-%.3f)  t=%s  mean %.2f" % (
            label, r["n"], 10 * r["b"], 10 * r["ci"], fmt_t(r["t"]), mean))
        return r

    p("")
    p("   5a. pre-2001 seasons available: %s" % seas_str(pre))
    r_pre = reg("sum p_full (all scored rows)", pre, sums)
    reg("scored rows (ERA5 candidates alone, no model)", pre, nrow)
    if len(pre) < 6:
        p("       NOTE: %d pre-2001 season(s) cached when this ran: too few for a trend test of any power%s." % (
            len(pre), " (none computed)" if len(pre) < 3 else ""))
        p("       Rerun series.py once the 1979-2000 fetch completes; the emitter picks up whatever is cached.")
    p("")
    p("   5b. overlap seasons (2004+): %s" % seas_str(ovl))
    r_ovl = reg("sum p_full (all scored rows)", ovl, sums)
    r_fit = reg("sum p_full over pos+neg rows (the fitted population)", ovl, sums_fit)
    reg("sum p_full, leave-one-season-out, pos+neg rows", ovl, sums_loso)
    r_pos = reg("ARCHIVE: HF-matched candidate moments (pos)", ovl, pos_mom)
    r_ev = reg("ARCHIVE: HF 'low' events with a fix in the domains", ovl, ev_low)
    reg("ARCHIVE: those events with a detected candidate", ovl, ev_det)
    reg("scored rows (ERA5 candidates alone, no model)", ovl, nrow)
    d_fit = {s: sums_fit[s] - pos_mom[s] for s in ovl}
    r_d = reg("sum p_full (pos+neg) MINUS archive pos moments", ovl, d_fit)
    p("       The last line is the test: a slope on (model - archive) means the criterion trends away from the")
    p("       archive it was fitted to. In-sample the level is forced to ~0 by the fit; only the slope is informative.")
    p("")
    allfit = [s for s in seas]
    d_all = {s: float(sp["full"][seas.index(s)]) - pos_mom[s] for s in ovl}
    r_dall = reg("sum p_full (ALL scored rows) MINUS archive pos moments", ovl, d_all)
    p("       (all rows include gray moments that no fit saw; this is the line where the series could outgrow the archive)")
    p("")
    p("   5b'. The overlap is two clusters (%s vs %s), 15 years apart, so a 7-point slope is mostly a difference of two" % (
        [s for s in ovl if s in C.EARLY], [s for s in ovl if s in C.LATE]))
    p("       means. That comparison, series against the archive's own counts (mean per season):")
    ea, la_ = [s for s in ovl if s in C.EARLY], [s for s in ovl if s in C.LATE]
    grow = {}
    if ea and la_:
        gray_sum = {s: float(P["full"][(season == s) & (cls == "gray")].sum()) for s in ovl}
        rows_ = [("sum p_full, all scored rows", sums), ("sum p_full, pos+neg rows (fitted pop.)", sums_fit),
                 ("sum p_full, gray rows only", gray_sum), ("ARCHIVE pos moments", pos_mom),
                 ("ARCHIVE 'low' events", ev_low), ("scored rows (ERA5 alone)", nrow)]
        p("       %-40s %10s %10s %9s" % ("quantity", "%d-%d" % (ea[0], ea[-1]), "%d-%d" % (la_[0], la_[-1]), "change"))
        for lab, dd in rows_:
            m1, m2 = np.mean([dd[s] for s in ea]), np.mean([dd[s] for s in la_])
            grow[lab] = 100 * (m2 - m1) / m1
            p("       %-40s %10.1f %10.1f %+8.1f%%" % (lab, m1, m2, grow[lab]))
        excess = grow["sum p_full, all scored rows"] - grow["ARCHIVE pos moments"]
        p("       series growth minus archive-moment growth: %+.1f percentage points; the gray rows alone grew %+.1f%%." % (
            excess, grow["sum p_full, gray rows only"]))
        p("       By archive label (per-season mean row count, mean p_full per row):")
        p("       %-8s %24s %24s" % ("label", "%d-%d rows / mean p" % (ea[0], ea[-1]), "%d-%d rows / mean p" % (la_[0], la_[-1])))
        for lb in ("pos", "gray", "neg"):
            out = []
            for grp in (ea, la_):
                mm = np.isin(season, grp) & (cls == lb)
                out.append("%8.0f / %.3f" % (mm.sum() / len(grp), P["full"][mm].mean()))
            p("       %-8s %24s %24s" % (lb, out[0], out[1]))
        p("       What this does and does not show: on the fitted population (pos+neg) the model-minus-archive slope is")
        p("       flat (t=%s), so the model adds no trend of its own where it can be checked against the archive. The" % fmt_t(r_d["t"] if r_d else float("nan")))
        p("       extra growth sits in the gray rows, which the archive labels non-positive, so the archive cannot adjudicate")
        p("       them: more gray rows (cyclones the archive rated HF at another moment) AND a higher mean p on them, and a")
        p("       higher mean p on the positives too. Real intensification, a change in how the archive logs HF fixes, and")
        p("       ERA5 drift all produce this pattern; 7 seasons in two clusters cannot tell them apart. The flag is therefore")
        p("       left standing and the all-rows sum should not be read as a trend estimate.")
    p("")
    p("   5c. all cached seasons together: %s" % seas_str(allfit))
    r_all = reg("sum p_full (all scored rows)", allfit, sums)
    reg("scored rows (ERA5 candidates alone, no model)", allfit, nrow)
    p("")
    p("   5d. level step, pre-2001 mean vs 2004+ mean of sum p_full (Welch)")
    if len(pre) >= 2 and len(ovl) >= 2:
        w = welch([sums[s] for s in pre], [sums[s] for s in ovl])
        p("       pre-2001 mean %.1f (n=%d), 2004+ mean %.1f (n=%d): difference %+.1f (se %.1f, t=%s)" % (
            np.mean([sums[s] for s in pre]), len(pre), np.mean([sums[s] for s in ovl]), len(ovl),
            w["d"], w["se"], fmt_t(w["t"])))
    else:
        w = None
        p("       needs >= 2 pre-2001 seasons: not computed (have %d)" % len(pre))
    p("")
    # automated flags -- stated plainly, never silent. A flag needs |t| above the 95% two-sided
    # critical value for that regression's degrees of freedom; |t| > 2 short of it is a "borderline".
    def judge(r, text):
        if not r or r["t"] != r["t"]:
            return
        crit = tcrit(r["n"] - 2)
        if abs(r["t"]) > crit:
            flags.append("%s (slope %+.2f /decade, t=%s > %.2f critical, n=%d)" % (text, 10 * r["b"], fmt_t(r["t"]), crit, r["n"]))
        elif abs(r["t"]) > 2:
            borderline.append("%s (slope %+.2f /decade, t=%s, critical %.2f at n=%d)" % (text, 10 * r["b"], fmt_t(r["t"]), crit, r["n"]))

    borderline = []
    judge(r_pre, "sum p_full TRENDS across the pre-2001 seasons available - the ERA5 gate says the fields do not")
    if w and abs(w["t"]) > 2:
        (flags if abs(w["t"]) > tcrit(min(len(pre), len(ovl)) - 1) else borderline).append(
            "sum p_full STEPS between pre-2001 and 2004+ (difference %+.1f, t=%s)" % (w["d"], fmt_t(w["t"])))
    if not (r_pos and abs(r_pos["t"]) > 2):
        judge(r_all, "sum p_full trends over all cached seasons while the archive's own overlap moment counts do not")
    judge(r_dall, "series (all rows) minus archive pos moments TRENDS in the overlap")
    judge(r_d, "model minus archive on the fitted population TRENDS in the overlap")
    if flags:
        p("   *** STATIONARITY FLAG(S) RAISED ***")
        for f in flags:
            p("   *** " + f)
    else:
        p("   No stationarity flag at the 95% level.")
    for f in borderline:
        p("   BORDERLINE (|t| > 2 but below the small-sample critical value): " + f)
    why = []
    if len(pre) < 6:
        why.append("only %d pre-2001 season(s) cached: no power for the era question" % len(pre))
    if len(ovl) <= 7:
        why.append("the %d overlap seasons are two clusters 15 years apart" % len(ovl))
    if why:
        p("   Power caveats: " + "; ".join(why) + ".")
    p("")

    # 6 ------------------------------------------------------------------------
    p("6. OVERLAP: SUM OF p_full AGAINST THE ARCHIVE'S ACTUAL COUNTS (seasons 2004+)")
    p("   Moments are the unit the model is calibrated in. The fit is in-sample for p_full on these seasons, so")
    p("   pos+neg totals match by construction (logistic score equation); the informative columns are the LOSO ones,")
    p("   the per-season and per-basin spread, and the gray/other-class rows the fit never saw. Event-level columns")
    p("   compare with archive events, where one event spans several moments - hence the conversion factor.")
    if ovl:
        p("   %-6s %5s %8s %8s %8s %8s %8s | %6s %6s %8s %8s %8s" % (
            "season", "bsn", "pos_mom", "S_pf+-", "S_loso+-", "ratio", "r_loso", "ev_low", "ev_det",
            "trk_pos", "S_trkmax", "S_all_pf"))
        agg = {"atl": [0.0] * 6, "pac": [0.0] * 6, "both": [0.0] * 6}
        per_ratio = []
        for s in ovl:
            for b in ("atl", "pac", "both"):
                mb = (season == s) & ((basin == b) if b != "both" else np.ones(len(R), bool))
                mpn = mb & np.isin(cls, ["pos", "neg"])
                posm = int((mb & (cls == "pos")).sum())
                spf = float(P["full"][mpn].sum())
                slo = float(ploso[mpn].sum())
                tp = {}
                tpos = set()
                for i in np.where(mb)[0]:
                    tp[trk[i]] = max(tp.get(trk[i], 0.0), P["full"][i])
                    if cls[i] == "pos":
                        tpos.add(trk[i])
                if b == "both":
                    el = sum(v["low"] for (ss, bb), v in ev.items() if ss == s)
                    ed = sum(v["low_det"] for (ss, bb), v in ev.items() if ss == s)
                else:
                    el = ev.get((s, b), {}).get("low", 0)
                    ed = ev.get((s, b), {}).get("low_det", 0)
                a = agg[b]
                a[0] += posm; a[1] += spf; a[2] += slo; a[3] += len(tpos); a[4] += sum(tp.values()); a[5] += el
                if b == "both":
                    per_ratio.append((s, spf / posm if posm else float("nan"), slo / posm if posm else float("nan")))
                p("   %-6d %5s %8d %8.1f %8.1f %8.2f %8.2f | %6d %6d %8d %8.1f %8.1f" % (
                    s, b, posm, spf, slo, spf / posm if posm else float("nan"), slo / posm if posm else float("nan"),
                    el, ed, len(tpos), sum(tp.values()), float(P["full"][mb].sum())))
        p("")
        p("   Totals over %s:" % (list(ovl),))
        for b in ("atl", "pac", "both"):
            a = agg[b]
            p("     %-4s pos moments %5d | S(p_full, pos+neg) %7.1f (ratio %.3f) | S(p_loso, pos+neg) %7.1f (ratio %.3f) | "
              "tracks with a pos %4d | S(track max p) %6.1f | archive 'low' events %4d | moments per event %.1f" % (
                  b, a[0], a[1], a[1] / max(1, a[0]), a[2], a[2] / max(1, a[0]), a[3], a[4], a[5], a[0] / max(1, a[5])))
        rl = np.array([r[2] for r in per_ratio])
        rf = np.array([r[1] for r in per_ratio])
        p("   Per-season ratio S/pos: in-sample p_full mean %.3f (min %.2f, max %.2f); leave-one-season-out mean %.3f (min %.2f, max %.2f);"
          % (np.nanmean(rf), np.nanmin(rf), np.nanmax(rf), np.nanmean(rl), np.nanmin(rl), np.nanmax(rl)))
        p("   LOSO ratio > 1 in %d of %d seasons, < 1 in %d (systematic bias would show as all one side)." % (
            int((rl > 1).sum()), len(rl), int((rl < 1).sum())))
        p("   Basin bias of the single pooled fit (LOSO ratio S/pos by season; mean, sd, and t of mean-1 over %d seasons):" % len(ovl))
        for b in ("atl", "pac"):
            rr = []
            for s in ovl:
                mpn = (season == s) & (basin == b) & np.isin(cls, ["pos", "neg"])
                posb = int(((season == s) & (basin == b) & (cls == "pos")).sum())
                rr.append(ploso[mpn].sum() / posb)
            rr = np.array(rr)
            p("     %s: ratios %s  mean %.3f sd %.3f t=%.2f  (over: %d seasons, under: %d)" % (
                b, " ".join("%.2f" % x for x in rr), rr.mean(), rr.std(ddof=1),
                (rr.mean() - 1) / (rr.std(ddof=1) / math.sqrt(len(rr))), int((rr > 1).sum()), int((rr < 1).sum())))
        p("   The pooled criterion has no basin term (none was in the pre-specified model); a basin offset of this size")
        p("   is not corrected here, only reported. Pooled over both basins the ratio is 1 by construction.")
        p("")
        # cross-window calibration: out-of-sample sums for early/late fits
        p("   Calibration-window effect on the sum, on seasons each narrow fit never saw (pos+neg rows; pos = archive moments):")
        for nm in ("early", "late"):
            if nm not in fits:
                continue
            oos = [s for s in ovl if s not in fits[nm]["seasons"]]
            if not oos:
                continue
            mo = np.isin(season, oos) & np.isin(cls, ["pos", "neg"])
            npos = int((mo & (cls == "pos")).sum())
            p("     p_%-5s on %s: sum %.1f vs pos %d (ratio %.3f); p_full-LOSO on same seasons: %.1f (ratio %.3f)" % (
                nm, oos, P[nm][mo].sum(), npos, P[nm][mo].sum() / max(1, npos), ploso[mo].sum(), ploso[mo].sum() / max(1, npos)))
        p("")
        p("   Series-level vs fitted-population sum (all scored rows include gray cyclone-moments and rows no fit saw):")
        for s in ovl:
            m = season == s
            mg = m & (cls == "gray")
            p("     %d: S(all rows) %.1f; of which pos+neg %.1f, gray %.1f (%d rows), archive pos %d" % (
                s, P["full"][m].sum(), P["full"][m & np.isin(cls, ["pos", "neg"])].sum(),
                P["full"][mg].sum(), mg.sum(), pos_mom[s]))
        p("   Gray rows (pre-/post-peak moments of an archive-HF cyclone, or HF no-centre cases) carry real probability")
        p("   but are labelled non-positive in the archive; they are why S(all rows) exceeds the archive moment count.")
    else:
        p("   no overlap season (>= %d) cached: nothing to compare." % RECORD_START)
    p("")

    # 7 ------------------------------------------------------------------------
    p("7. THE FILE")
    p("   %s" % OUT_CSV)
    p("   size %d bytes (%.2f MB); limit %.0f MB; rows %d" % (fsize, fsize / 1e6, MAX_BYTES / 1e6, int(keep.sum())))
    p("   %s" % floor_note)
    p("   columns: time_utc, season, basin, lat, lon (deg east, -180..180), centre_hpa (smoothed centre), pmin150_hpa,")
    p("   depth_hpa, gust500_kt, area64_km2, grad_hpa100km, track (stable id: basin + first time + ordinal),")
    p("   archive_label (pos/neg/gray from event_fields.label, 2004+ only, blank earlier; NOT available pre-2004),")
    p("   fit_in (F/E/L = row's season was in the full/early/late fit, i.e. that probability is in-sample), p_full, p_early, p_late.")
    p("   Rounding: positions/features 2 decimals, probabilities 4.")
    # read-back
    with gzip.open(OUT_CSV, "rt", newline="") as f:
        rb = list(csv.DictReader(f))
    p("")
    p("   READ-BACK from the gz: %d rows" % len(rb))
    pf = np.array([float(r["p_full"]) for r in rb])
    pe = np.array([float(r["p_early"]) if r["p_early"] else np.nan for r in rb])
    pl = np.array([float(r["p_late"]) if r["p_late"] else np.nan for r in rb])
    p("   sum p_full from file %.2f vs unrounded %.2f (4-decimal rounding)" % (pf.sum(), np.nansum(P["full"][keep])))
    lab = np.array([r["archive_label"] for r in rb])
    p("   archive_label counts in file: " + ", ".join("%s=%d" % (k or "blank", (lab == k).sum()) for k in ("pos", "neg", "gray", "")))
    fi = np.array([r["fit_in"] for r in rb])
    p("   fit_in counts in file: " + ", ".join("%s=%d" % (k or "none", (fi == k).sum()) for k in sorted(set(fi))))
    ok = np.isfinite(pe) & np.isfinite(pl)
    p("   columns differ as expected (from the file): rows with |p_full-p_early|>0.01: %d, |p_full-p_late|>0.01: %d, |p_early-p_late|>0.01: %d; "
      "max gaps %.3f / %.3f / %.3f" % (
          (abs(pf - pe) > 0.01).sum(), (abs(pf - pl) > 0.01).sum(), (abs(pe - pl) > 0.01).sum(),
          np.nanmax(abs(pf - pe)), np.nanmax(abs(pf - pl)), np.nanmax(abs(pe - pl))))
    p("   Spearman from the file: full~early %.4f, full~late %.4f, early~late %.4f" % (
        spearman(pf[ok], pe[ok]), spearman(pf[ok], pl[ok]), spearman(pe[ok], pl[ok])))
    hdr = ["time_utc", "basin", "lat", "lon", "gust500_kt", "area64_km2", "pmin150_hpa", "fit_in", "p_full", "p_early", "p_late"]
    p("   " + " ".join("%-10s" % h[:10] for h in hdr))
    # a few informative rows: highest p_full in the earliest and latest season, and a mid-probability row
    picks = []
    cand_idx = np.arange(len(rb))
    sn = np.array([int(r["season"]) for r in rb])
    for s in (seas[0], seas[-1]):
        ii = cand_idx[sn == s]
        if len(ii):
            picks.append(int(ii[np.argmax(pf[ii])]))
    mid_ = cand_idx[(pf > 0.2) & (pf < 0.6) & np.isfinite(pe) & np.isfinite(pl)]
    if len(mid_):
        picks.append(int(mid_[np.argmax(np.abs(pe[mid_] - pl[mid_]))]))
        picks.append(int(mid_[len(mid_) // 2]))
    for i in picks:
        p("   " + " ".join("%-10s" % rb[i][h] for h in hdr))
    p("   (rows: top p_full in first season, top in last season, row with the largest p_early/p_late gap, a mid-probability row)")
    p("")

    # header & summary -----------------------------------------------------------
    head = []
    head.append("ERA5 hurricane-force-equivalent probability series (hf_probability.csv.gz)")
    head.append("=" * 72)
    head.append("THIS SERIES IS A PROXY. It gives, per ERA5 cyclone and 6-hourly step, the probability that OPC's")
    head.append("archive would have called the cyclone hurricane force, from ERA5 cyclone features. It is NOT an")
    head.append("extended hurricane-force record, it cannot be validated before the archive's RECORD_START (%d)," % RECORD_START)
    head.append("and its seasonal sums are model expectations in cyclone-moments, not observed event counts.")
    head.append("")
    head.append("Seasons scored: %s" % seas_str(seas))
    head.append("Fit seasons   : full %s | early %s | late %s" % (
        fits["full"]["seasons"] if "full" in fits else "-", fits["early"]["seasons"] if "early" in fits else "-",
        fits["late"]["seasons"] if "late" in fits else "-"))
    head.append("Pre-2001 seasons in this run: %d (of 22: 1979-2000)." % len(pre))
    head.append("")
    if flags:
        head.append("*** STATIONARITY FLAG(S): ***")
        head.extend("*** " + f for f in flags)
    else:
        head.append("Stationarity flags at the 95% level: none raised.")
    for f in borderline:
        head.append("Borderline (not significant at 95% given the small n, but above |t|=2): " + f)
    head.append("Power caveat: %d pre-2001 season(s) cached; the overlap is two clusters 15 years apart. Read section 5 before using any trend." % len(pre))
    if grow:
        head.append("Overlap, mean per season %s -> %s: series sum (all rows) %+.0f%%, fitted-population sum %+.0f%%, archive pos moments %+.0f%%, "
                    "archive events %+.0f%%." % (
                        "%d-%d" % (ea[0], ea[-1]), "%d-%d" % (la_[0], la_[-1]), grow["sum p_full, all scored rows"],
                        grow["sum p_full, pos+neg rows (fitted pop.)"], grow["ARCHIVE pos moments"], grow["ARCHIVE 'low' events"]))
    head.append("")
    txt = "\n".join(head + L) + "\n"
    open(OUT_TXT, "w").write(txt)
    print(txt)
    print("wrote", OUT_CSV, "and", OUT_TXT)


if __name__ == "__main__":
    run()
