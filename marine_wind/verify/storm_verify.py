"""Daily verification of the storm layers (pipeline/storm.py), one basin per run.

For one 12 UTC valid time (default: two days ago, so the RSS ASCAT day is complete), the
+24 to +120 h forecasts from the 12 UTC runs are rebuilt with the page's own pipeline
(build.step_fields) and scored:

  ascat     Metop-B/C ASCAT within 90 min of 12 UTC (RSS bytemaps, no login), rain-flagged
            cells dropped, one ob per cell (nearest 12 UTC), equivalent-neutral wind turned
            into real 10 m wind with the analysed air-minus-sea temperature (as in training)
  analysis  GFS + ECMWF IFS analysis mean (open, ice-free water), both basins every day
            (ASCAT barely covers the Pacific at 12 UTC)

Products, one CSV row per (valid, basin, lead, referee, product) holding a 2x2 table:
  wind, windcore   5x5 degree tiles with 150+ scored cells: storm force forecast (any cell
                   48+ kt) against storm force seen (any cell 48+ kt). Catches peaks the way
                   the study did (blend 15% / core lift 49% caught, Atlantic winter ASCAT).
  gale, storm, hf  hazard lines, cell by cell: hit = ob at 34/48/64+ kt inside the line,
                   miss = outside, fa = cell inside the line below the threshold
  track            ensemble low positions against the lows in the analysis mean pressure:
                   hit = analysed low inside the cone, miss = matched but outside,
                   fa = forecast low with no analysed low within 1000 km; err_km, dp_hpa sums

Usage:
  python3 storm_verify.py --basin natl --out new.csv [--valid YYYYMMDD]
  python3 storm_verify.py --summary storm_scores.csv --md storm_summary.md
"""
import argparse, csv, datetime as dt, gzip, os, sys, time, urllib.error, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, "..", "pipeline")
KT = 1.943844
STEPS = [24, 48, 72, 96, 120]
FIELDS = ["valid", "basin", "lead", "referee", "product", "hit", "miss", "fa", "cn", "err_km", "dp_hpa"]
ASCAT_URL = "https://data.remss.com/ascat/metop{s}/bmaps_v02.1/y{y}/m{m}/ascat{s}_{d}_v02.1.gz"
MAX_DT = 90          # minutes from 12 UTC
TILE_MIN = 150       # scored cells for a tile to count
HZ = {"gale": (1, 34), "storm": (2, 48), "hf": (4, 64)}


# ------------------------------------------------------------------ ASCAT
def ascat_day(ymd):
    """All Metop-B/C cells within MAX_DT of 12 UTC: lat, lon (0-360), spd (ENW kt), dt."""
    parts = []
    for s in ("b", "c"):
        u = ASCAT_URL.format(s=s, y=ymd[:4], m=ymd[4:6], d=ymd)
        a = None
        for k in range(6):
            try:
                with urllib.request.urlopen(u, timeout=120) as r:
                    a = np.frombuffer(gzip.decompress(r.read()), np.uint8).reshape(2, 5, 720, 1440)
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                time.sleep(2 ** k)
            except Exception:
                time.sleep(2 ** k)
        if a is None:
            continue
        for p in range(2):
            t, w, rn = a[p, 0], a[p, 1], a[p, 3]
            d = t.astype(np.int16) * 6 - 720
            ok = (w <= 250) & (np.abs(d) <= MAX_DT) & ((rn & 1) == 0) & ((rn >> 2) < 2)
            iy, ix = np.nonzero(ok)
            parts.append(np.stack([-89.875 + 0.25 * iy, 0.125 + 0.25 * ix, w[iy, ix] * 0.2 * KT, np.abs(d[iy, ix])], 1))
    if not parts:
        return None
    return np.concatenate(parts)


def psi(zeta, kind):
    zeta = np.asarray(zeta, float)
    out = np.zeros_like(zeta)
    u = zeta < 0
    x = (1 - 16 * zeta[u]) ** 0.25
    if kind == "m":
        out[u] = 2 * np.log((1 + x) / 2) + np.log((1 + x * x) / 2) - 2 * np.arctan(x) + np.pi / 2
    else:
        out[u] = 2 * np.log((1 + x * x) / 2)
    zs = np.minimum(zeta[~u], 10)          # Beljaars-Holtslag stable functions
    a, b, c, d = 1.0, 0.667, 5.0, 0.35
    if kind == "m":
        out[~u] = -(a * zs + b * (zs - c / d) * np.exp(-d * zs) + b * c / d)
    else:
        out[~u] = -((1 + 2 * a * zs / 3) ** 1.5 + b * (zs - c / d) * np.exp(-d * zs) + b * c / d - 1)
    return out


def enw_to_real(enw_kt, dT, T=285.0, k=0.4, g=9.81, alpha=0.011, nu=1.5e-5, zt=2.0):
    """Equivalent-neutral 10 m wind -> real 10 m wind for air-minus-sea dT (K); the study's
    conversion (lower in unstable air, higher in stable air)."""
    U = np.maximum(np.asarray(enw_kt, float) / KT, 0.5)
    us = U * k / np.log(10 / 1e-4)
    for _ in range(20):
        z0 = alpha * us ** 2 / g + 0.11 * nu / us
        us = U * k / np.log(10 / z0)
    z0 = alpha * us ** 2 / g + 0.11 * nu / us
    Linv = np.zeros_like(U)
    for _ in range(30):
        ts = k * np.asarray(dT, float) / (np.log(zt / 1e-4) - psi(zt * Linv, "h"))
        Linv = np.clip(k * g * ts / (T * us ** 2), -5, 2)
    return us / k * (np.log(10 / z0) - psi(10 * Linv, "m")) * KT


def ascat_on_grid(raw, lats, lons, mask, dT):
    """ASCAT onto the page grid -> rows, cols, kt. ASCAT cells sit half way between grid points,
    so each takes the grid point to its north-west (one to one); a cell seen twice keeps the ob
    nearest 12 UTC."""
    if raw is None or not len(raw):
        return None
    r = np.floor((lats[0] - raw[:, 0]) / 0.25).astype(int)
    c = np.floor(((raw[:, 1] - lons[0]) % 360) / 0.25).astype(int)
    ok = (r >= 0) & (r < len(lats)) & (c >= 0) & (c < len(lons))
    r, c, sp, d = r[ok], c[ok], raw[ok, 2], raw[ok, 3]
    o = np.lexsort((d, c, r))
    r, c, sp = r[o], c[o], sp[o]
    first = np.r_[True, (np.diff(r) != 0) | (np.diff(c) != 0)]
    r, c, sp = r[first], c[first], sp[first]
    ok = mask[r, c]
    r, c, sp = r[ok], c[ok], sp[ok]
    return r, c, enw_to_real(sp, dT[r, c])


# ------------------------------------------------------------------ scoring
def tiles(lats, lons, r, c):
    return (np.floor(lats[r] / 5) * 1000 + np.floor((lons[c] % 360) / 5)).astype(int)


def tile_table(tl, obs, fc):
    """2x2 over tiles: storm force (48+) anywhere in the tile's scored cells."""
    h = m = f = n = 0
    for t in np.unique(tl):
        s = tl == t
        if s.sum() < TILE_MIN:
            continue
        o, p = obs[s].max() >= 48, fc[s].max() >= 48
        h += o and p; m += o and not p; f += p and not o; n += not o and not p
    return h, m, f, n


def cell_table(obs, inside, thr):
    o = obs >= thr
    return int((o & inside).sum()), int((o & ~inside).sum()), int((~o & inside).sum()), int((~o & ~inside).sum())


def rows_for(valid, basin, lead, referee, obs, r, c, f, lats, lons):
    out = []
    tl = tiles(lats, lons, r, c)
    for prod in ("wind", "windcore"):
        out.append(dict(product=prod, **dict(zip("hit miss fa cn".split(), tile_table(tl, obs, f[prod][r, c])))))
    for prod, (bit, thr) in HZ.items():
        out.append(dict(product=prod, **dict(zip("hit miss fa cn".split(), cell_table(obs, (f["hazard"][r, c] & bit) > 0, thr)))))
    return [dict(valid=valid, basin=basin, lead=lead, referee=referee, err_km="", dp_hpa="", **x) for x in out]


def track_row(valid, basin, lead, fc_lows, anl_lows, lats, lons, storm):
    hit = miss = fa = 0
    err = dp = 0.0
    for l in fc_lows:
        d = [storm.km(lats, lons, l["r"], l["c"], a[0], a[1]) for a in anl_lows]
        if not d or min(d) > 1000:
            fa += 1
            continue
        j = int(np.argmin(d))
        cone = storm.CONE_K.get(lead, 1.2) * max(l["spread"], 30.0)
        hit += d[j] <= cone; miss += d[j] > cone
        err += d[j]; dp += l["p"] - anl_lows[j][2]
    return dict(valid=valid, basin=basin, lead=lead, referee="analysis", product="track", hit=hit, miss=miss,
                fa=fa, cn=0, err_km=round(err, 1), dp_hpa=round(dp, 2))


def run(valid, basin):
    os.environ["MARINE_DOMAIN"] = basin
    sys.path.insert(0, PIPE)
    import build, fetch, storm
    from domain import LATS, LONS
    g, e, gl = fetch.gfs(valid, "12", 0), fetch.ec_det("ifs", valid, "12", 0), fetch.gfs_low(valid, "12", 0)
    if g is None or e is None or gl is None:
        print("analysis missing for", valid)
        return []
    anl = (np.hypot(g["u"], g["v"]) + np.hypot(e["u"], e["v"])) / 2 * KT
    anl_msl = (g["msl"] + e["msl"]) / 200.0
    mask = (gl["land"] < 0.01) & ~(np.nan_to_num(gl["ice"]) > 0.15)
    dT = gl["t2"] - gl["skt"]
    anl_lows = storm.lows(anl_msl, 1005.0)
    asc = ascat_on_grid(ascat_day(valid), LATS, LONS, mask, dT)
    print("%s %s: ASCAT %s cells, analysed lows %d" % (valid, basin, 0 if asc is None else len(asc[0]), len(anl_lows)), flush=True)
    ar, ac = np.nonzero(mask)
    names = [f[0] for f in build.FIELDS]
    rows = []
    for lead in STEPS:
        cyc = (dt.datetime.strptime(valid, "%Y%m%d") - dt.timedelta(hours=lead)).replace(hour=12)
        try:
            packed, stats = build.step_fields(cyc.strftime("%Y%m%d"), "12", lead)
        except Exception as ex:
            print("  +%dh: build failed (%s)" % (lead, ex), flush=True)
            continue
        f = {}
        for i, fd in enumerate(build.FIELDS):
            if fd[0] in ("wind", "windcore", "hazard"):
                f[fd[0]] = packed[i].astype(np.float32) / fd[1] - (fd[4] if len(fd) > 4 else 0)
        f["hazard"] = f["hazard"].astype(np.uint8)
        if not stats.get("core_model"):
            print("  +%dh: core model inputs missing, skipped" % lead, flush=True)
            continue
        if asc is not None:
            rows += rows_for(valid, basin, lead, "ascat", asc[2], asc[0], asc[1], f, LATS, LONS)
        rows += rows_for(valid, basin, lead, "analysis", anl[ar, ac], ar, ac, f, LATS, LONS)
        rows.append(track_row(valid, basin, lead, stats.get("lows", []), anl_lows, LATS, LONS, storm))
        print("  +%dh ok" % lead, flush=True)
    return rows


# ------------------------------------------------------------------ summary
def summarize(path, md):
    rows = list(csv.DictReader(open(path)))
    if not rows:
        return
    last = max(r["valid"] for r in rows)
    d_last = dt.datetime.strptime(last, "%Y%m%d")
    windows = [("Last 7 days", 7), ("Last 30 days", 30), ("All days", 100000)]
    out = ["# Storm layers verification", "",
           "Through %s 12 UTC. Rebuilt +24 to +120 h forecasts from the 12 UTC runs." % last, "",
           "- **Peaks** (5x5 degree tiles): caught = share of tiles with storm force seen that had storm force "
           "forecast; false alarm = share of storm-force forecast tiles without it. `wind` is the live blend, "
           "`windcore` the blend + 5 kt where the core likelihood is 35%+. Study (Atlantic winter ASCAT): "
           "blend 15% caught / 4% false alarm, core lift 49% / 15%.",
           "- **Hazard lines** (cells): inside = share of obs at 34/48/64+ kt inside the gale/storm/HF line; "
           "verified = share of outlined cells at the threshold; area = outlined cells / cells at the threshold. "
           "Study: gale 75% inside, 1.2x area; storm 77% inside, 1.7x; HF 57% inside.",
           "- **Track**: mean distance from the ensemble low to the analysed low, and the share inside the cone "
           "(cone sized to hold it about 2 in 3).",
           "- ASCAT barely covers the Pacific at 12 UTC; the analysis smooths peaks, so it sees fewer storm-force tiles than ASCAT.", ""]

    def pct(a, b):
        return "%d%%" % round(100 * a / b) if b else "-"

    for title, days in windows:
        sel = [r for r in rows if (d_last - dt.datetime.strptime(r["valid"], "%Y%m%d")).days < days]
        if not sel:
            continue
        nd = len({r["valid"] for r in sel})
        out += ["## %s (%d days)" % (title, nd), ""]
        for basin in sorted({r["basin"] for r in sel}):
            out += ["### %s" % {"natl": "North Atlantic", "npac": "North Pacific"}.get(basin, basin), ""]
            for ref in ("ascat", "analysis"):
                s = [r for r in sel if r["basin"] == basin and r["referee"] == ref]
                if not s:
                    continue
                out += ["**Peaks vs %s**" % ref, "", "| Lead | wind caught | wind FA | windcore caught | windcore FA | storm tiles seen |",
                        "|---|---|---|---|---|---|"]
                for lead in STEPS:
                    t = {p: [sum(int(r[k]) for r in s if r["product"] == p and int(r["lead"]) == lead) for k in ("hit", "miss", "fa")]
                         for p in ("wind", "windcore")}
                    if not any(sum(v) for v in t.values()):
                        continue
                    w, c = t["wind"], t["windcore"]
                    out.append("| +%d h | %s | %s | %s | %s | %d |" % (lead, pct(w[0], w[0] + w[1]), pct(w[2], w[0] + w[2]),
                                                                     pct(c[0], c[0] + c[1]), pct(c[2], c[0] + c[2]), w[0] + w[1]))
                out += ["", "**Hazard lines vs %s** (all leads)" % ref, "", "| Line | inside | verified | area | obs at threshold |", "|---|---|---|---|---|"]
                for p in HZ:
                    h, m, fa = (sum(int(r[k]) for r in s if r["product"] == p) for k in ("hit", "miss", "fa"))
                    out.append("| %s | %s | %s | %s | %d |" % (p, pct(h, h + m), pct(h, h + fa),
                                                             "%.1fx" % ((h + fa) / (h + m)) if h + m else "-", h + m))
                out.append("")
            s = [r for r in sel if r["basin"] == basin and r["product"] == "track"]
            if s:
                out += ["**Ensemble low track vs analysis**", "", "| Lead | lows matched | mean error | in cone | pressure bias | unmatched |",
                        "|---|---|---|---|---|---|"]
                for lead in STEPS:
                    t = [r for r in s if int(r["lead"]) == lead]
                    h, m, fa = (sum(int(r[k]) for r in t) for k in ("hit", "miss", "fa"))
                    e, p = sum(float(r["err_km"]) for r in t), sum(float(r["dp_hpa"]) for r in t)
                    if h + m + fa == 0:
                        continue
                    out.append("| +%d h | %d | %s | %s | %s | %d |" % (lead, h + m, "%d km" % round(e / (h + m)) if h + m else "-",
                                                                   pct(h, h + m), "%+.1f hPa" % (p / (h + m)) if h + m else "-", fa))
                out.append("")
    open(md, "w").write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--valid")
    ap.add_argument("--basin", default="natl")
    ap.add_argument("--out")
    ap.add_argument("--summary")
    ap.add_argument("--md")
    a = ap.parse_args()
    if a.summary:
        summarize(a.summary, a.md)
        return
    valid = a.valid or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).strftime("%Y%m%d")
    rows = run(valid, a.basin)
    if not rows:
        sys.exit(1)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
