#!/usr/bin/env python3
"""Build tests/tcwind_jtwc/data/gtcm_findings.json - every number the
Findings page shows.

The page hardcodes no statistics.  If a field is missing here, the page has a
hole in it, so this script writes the whole block or fails loudly.

WHAT IS MEASURED, AND WHY
-------------------------
The office moved TCWind_JTWC from the per-quadrant construction to GTCM for
PHYSICAL PLAUSIBILITY, not for accuracy against the reported radii.  GTCM
deliberately does not pass through those radii - it minimises WIND error
against the quadrant-average radii (Users Guide eq. 7) precisely because
forcing the radii produces unrealistic structure.  So "how close are the
rings" is a description, not a score, and on its own it makes the switch look
like a regression.

Nothing in this repo had ever measured the thing the switch was actually for.
That is what the `coherence` block below is: four measurements of how smooth
each construction's field is, defined precisely here and echoed into the JSON
so the page can state the definition next to the number.

    azimuthalKinkKtPerDeg   The per-quadrant construction interpolates the
        four reported radii LINEARLY in azimuth (_azimuthalRadii), so the
        radius-vs-azimuth curve has a corner at each quadrant bisector - 45,
        135, 225, 315 - and the wind field therefore has a slope break in
        dV/dtheta there BY CONSTRUCTION.  GTCM is one analytic vortex plus a
        wavenumber-1 asymmetry and should have none.

        At each of ten radii spanning the anchored band (1.2*Rmax out to 1.2 x
        the largest reported radius), V is sampled every 0.5 deg of azimuth.
        At each bisector a straight line is fit to V over the 0.5-5.0 deg
        sector on each side; the kink is |slope_outside - slope_inside| in
        kt/deg.  Reported as the mean over bisectors, radii and cases.

        azimuthalKinkControlKtPerDeg applies the identical estimator at 0/90/
        180/270 - mid-sector azimuths where neither construction has a corner.
        It is the noise floor of the estimator: a bisector number that is not
        clearly above its own control number means nothing.

    radialKinkKtPerNm / radialJumpKt   Slope break and VALUE step in the
        radial profile at each construction's own knots, along 8 rays (every
        45 deg).  perquad's knots are Rmax and each reported ring radius at
        that azimuth; GTCM's are rm, ri and the azimuth's modelled 34 kt
        radius where the documented outer taper starts.  Straight lines are
        fit on each side of the knot over a window w = clip(half the distance
        to the nearest other knot, 2, 10) nm, skipping the innermost 0.5 nm on
        each side; the slope break is |slope_out - slope_in| in kt/nm and the
        jump is the difference of the two fits extrapolated to the knot, in
        kt.  A jump is worse than a break: it is a step in the wind field.

        radialKinkExclTaperKtPerNm / radialJumpExclTaperKt repeat both without
        the outer-taper knot, which is this tool's documented departure from
        the guide and is present in BOTH constructions - it is not a property
        of either vortex model.

    monotonicityViolationPct   Along the same 8 rays, the fraction of adjacent
        radial samples (0.25 nm apart) outside the ray's own wind maximum, and
        at or above 15 kt, where the wind INCREASES outward by more than 0.01
        kt.  Outside the eyewall a tropical cyclone's wind decreases outward;
        anywhere it does not, the construction has invented a secondary
        maximum.  The reference radius is each ray's own field maximum rather
        than either method's Rmax parameter, so the two are judged the same
        way.

    fieldRoughnessPctVmax   A global roughness over the 2-D field: the mean
        absolute discrete second difference of V, radially and azimuthally, on
        a fixed polar grid (5 to 405 nm every 5 nm, every 2 deg), expressed as
        a percentage of Vmax.  Both constructions are evaluated on the same
        grid and the same mask (cells where either reaches 15 kt), so this is
        a paired comparison.  It is a roughness AT THAT SAMPLING SCALE, not a
        continuum derivative, and only the comparison between the two columns
        is meaningful.

Ring and field numbers are NOT recomputed here - compare_vortex_methods.py
owns them and this script imports it, so there is one implementation.

SCHEMA ADDITIONS (holdout / byNature / byLand)
-----------------------------------------------
Three new top-level blocks, each built by its own script and embedded here
verbatim (same "one implementation" discipline as ringFit/fieldDiff above):

    holdout    verify_holdout.compute()'s return value directly. Answers
               the question nothing else in this pipeline asks: fit GTCM/
               perquad to a SUBSET of one record's reported radii and score
               the prediction of the radii withheld from the fit. See that
               script's own docstring for the full method, its CAVEAT
               (read this before quoting a holdout number - r34Only is a
               harder, synthetic task; r34R50 is the more representative
               one), and the exact JSON shape (byBasin/pooled, each holding
               r34Only/r34R50/rmwContext).
    byNature   verify_stratified.compute()["byNature"]. The SAME ringFit
               and holdout statistics above, pooled by IBTrACS storm-nature
               flag (TS/ET/SS/MX/other) instead of by basin.
    byLand     verify_stratified.compute()["byLand"]. The same statistics
               again, pooled by distance-to-nearest-land bucket instead.

byNature/byLand fold verify_besttrack_context.py's question (does accuracy
hold up near land and during transition?) into this hermetic, archive-based,
all-three-basin pipeline; see verify_stratified.py's docstring for why that
script, not the original CSV-driven one, now feeds this JSON. Every group in
both blocks carries n and nStorms - some strata (ET, SS especially) are thin
even pooled across three basins; read nStorms before trusting a stratum's
number, and see verify_stratified.py's own caveat.

Every stat everywhere in this file - not just the three new blocks - carries
both n (records) and nStorms (distinct storms): compare_vortex_methods.stats()
and this script's own accumulators were extended to track storm SIDs
alongside every value for exactly this reason. Records are not independent
by storm (see the top-level notes.independence below); n alone overstates
how much independent evidence a number rests on.

    python3 verify_gtcm.py [--cases N] [--coherence-cases N] [--seed N]
                           [--basins WP,NA,EP] [--out PATH]
                           [--no-holdout] [--no-stratified]

--cases 0 (the default) means the WHOLE usable population of each basin,
not a sample - see the CLI help and the runtime numbers this script prints
and writes to findings["runtime"]. --coherence-cases keeps a real subsample
(that block's cost scales with grid points x cases, not just cases) but
its default (50) is chosen so seeded round-robin sampling still covers at
least 40 distinct storms in every basin (compare_vortex_methods.load_cases's
docstring explains why a small --cases used to silently collapse onto 1-3
storms; this default is the fix applied to this script's own defaults).
"""

import argparse
import datetime
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "GFE", "procedures"))

import TCWind_JTWC as T                # noqa: E402
import compare_vortex_methods as C     # noqa: E402
import verify_holdout               # noqa: E402
import verify_stratified            # noqa: E402

OUT = os.path.join(HERE, "data", "gtcm_findings.json")

BISECTORS = (45.0, 135.0, 225.0, 315.0)
CONTROLS = (0.0, 90.0, 180.0, 270.0)

# Azimuthal sampling
AZ_STEP_DEG = 0.5
AZ_FIT_INNER_DEG = 0.5      # skip this close to the corner (the corner itself)
AZ_FIT_OUTER_DEG = 5.0
AZ_N_RADII = 10

# Radial sampling
RAY_AZ = tuple(float(a) for a in range(0, 360, 45))
RAY_STEP_NM = 0.25
RAY_MAX_NM = 420.0
KNOT_FIT_INNER_NM = 0.5
KNOT_FIT_MIN_W_NM = 2.0
KNOT_FIT_MAX_W_NM = 10.0
MONO_MIN_KT = 15.0
MONO_EPS_KT = 0.01

# Field roughness grid
ROUGH_R_NM = np.arange(5.0, 405.1, 5.0)
ROUGH_AZ_DEG = np.arange(0.0, 360.0, 2.0)
ROUGH_MIN_KT = 15.0

COHERENCE_DEFS = {
    "azimuthalKinkKtPerDeg":
        "Mean |slope break| in dV/dtheta at the quadrant bisectors "
        "(45/135/225/315 deg), kt per degree of azimuth. Straight lines fit "
        "to V over 0.5-5.0 deg either side of the bisector, at 10 radii from "
        "1.2*Rmax to 1.2 x the largest reported radius, sampled every 0.5 deg. "
        "The per-quadrant construction interpolates the reported radii "
        "linearly in azimuth and so has a corner at each bisector by "
        "construction; one analytic vortex should not.",
    "azimuthalKinkControlKtPerDeg":
        "The identical estimator at 0/90/180/270 deg, where neither "
        "construction has a corner. This is the estimator's noise floor - "
        "compare each method's bisector value against its own control value.",
    "radialKinkKtPerNm":
        "Mean |slope break| in dV/dr at the construction's own profile knots, "
        "kt per nm, over 8 rays. perquad knots: Rmax and each reported ring "
        "radius at that azimuth. GTCM knots: rm, ri, and the modelled 34 kt "
        "radius where the outer taper starts.",
    "radialJumpKt":
        "Mean |step| in V across those same knots, in kt: the two one-sided "
        "linear fits extrapolated to the knot radius and differenced. A "
        "nonzero value is a discontinuity in the wind field, which is worse "
        "than a slope break.",
    "radialKinkExclTaperKtPerNm":
        "radialKinkKtPerNm excluding the outer-taper knot, which is this "
        "tool's documented departure from the guide and is present in both "
        "constructions. For perquad the taper is anchored on the outermost "
        "reported ring, so excluding it also drops that ring's knot - which "
        "is why perquad's excl-taper value is the LARGER of the two: what is "
        "left is dominated by the sharp Rmax corner.",
    "radialJumpExclTaperKt":
        "radialJumpKt excluding the outer-taper knot.",
    "monotonicityViolationPct":
        "Percentage of adjacent radial samples (0.25 nm apart, 8 rays) "
        "outside the ray's own wind maximum and at or above 15 kt where the "
        "wind increases outward by more than 0.01 kt - i.e. where the "
        "construction invents a secondary wind maximum.",
    "fieldRoughnessPctVmax":
        "Mean absolute discrete second difference of V, radial plus "
        "azimuthal, on a fixed polar grid (5-405 nm every 5 nm, every 2 deg), "
        "as a percentage of Vmax. Both methods use the same grid and the same "
        "mask (cells where either reaches 15 kt), so it is a paired "
        "comparison; it is a roughness at that sampling scale, not a "
        "continuum derivative.",
    "byKnot":
        "radialKinkKtPerNm and radialJumpKt broken out by which knot they "
        "were measured at. perquad: Rmax is the solid-body / Rankine corner "
        "and R64/R50/R34 are the reported rings, the outermost of which is "
        "also where the outer taper starts. GTCM: rm is the same corner, ri "
        "is the x1 -> x2 junction of eq. (3), and r34taper is where the "
        "documented outer taper starts.",
    "cases":
        "Storm-times contributing to this method's coherence numbers.",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _one_sided_fit(x, y, x0, lo, hi):
    """Line fit to (x, y) over x0+lo .. x0+hi. Returns (slope, value at x0)."""
    sel = (x >= x0 + min(lo, hi)) & (x <= x0 + max(lo, hi))
    if int(np.count_nonzero(sel)) < 3:
        return None
    slope, intercept = np.polyfit(x[sel] - x0, y[sel], 1)
    return float(slope), float(intercept)


def _step_across(x, y, x0):
    """Magnitude of the field's step across x0, in kt.

    The two samples either side of x0 on the ray grid, differenced.  On a
    RAY_STEP_NM grid this also picks up one grid step of ordinary gradient,
    which is the honest floor on what a sampled field can distinguish a
    discontinuity from - a genuinely continuous knot reads as the local
    gradient times the grid step, not as zero.
    """
    j = int(np.searchsorted(x, x0))
    if j <= 0 or j >= len(x):
        return None
    return abs(float(y[j]) - float(y[j - 1]))


def _perquad_knots(snap, rmax, az):
    """Knot radii per azimuth for the per-quadrant construction.

    Mirrors buildVortex()'s knot assembly exactly (floor, the 1.02
    monotonicity enforcement, the vmax < threshold skip).  Returns
    (array of shape (nknot, naz), labels, taper_row).  The outer taper is
    anchored on the OUTERMOST reported ring, so for this construction the
    taper knot and the outermost ring knot are the same radius.
    """
    az = np.asarray(az, dtype=float)
    floor = rmax * 1.05
    prev = np.full(az.shape, rmax)
    knots = [np.full(az.shape, rmax)]
    labels = ["Rmax"]
    for threshold in (64, 50, 34):
        if threshold not in snap.radii or snap.vmax < threshold:
            continue
        rr = T._azimuthalRadii(az, snap.radii[threshold], floor)
        rr = np.maximum(rr, prev * 1.02)
        knots.append(rr)
        labels.append("R%d" % threshold)
        prev = rr
    return np.array(knots), labels, len(labels) - 1


def _gtcm_knots(snap, az, fit, r34):
    """rm, ri and the per-azimuth modelled R34 where the taper starts.

    r34 comes from buildVortex()'s own fourth return value rather than being
    recomputed here.  It used to be recomputed, with a docstring warning that
    the copy would describe the wrong knot if the builder ever changed - which
    is exactly what happened.  When the builder switched from snapping r34 to
    the whole-nm probe grid to interpolating the 34 kt crossing, this copy kept
    snapping, so the estimator sampled either side of a radius that was no
    longer the knot and reported a 3.3 kt "value jump" across a boundary that
    is in fact continuous to 0.001 kt.  Taking the builder's own value removes
    the class of bug rather than resynchronising it.
    """
    az = np.asarray(az, dtype=float)
    return (np.array([np.full(az.shape, fit["rm"]),
                      np.full(az.shape, fit["ri"]),
                      np.asarray(r34, dtype=float)]),
            ["rm", "ri", "r34taper"], 2)


# ---------------------------------------------------------------------------
# coherence
# ---------------------------------------------------------------------------

def azimuthal_kinks(snap, rmax):
    """{method: {'bisector': [...], 'control': [...]}} in kt/deg."""
    reported = [v for d in snap.radii.values() for v in d.values() if v > 0]
    if not reported:
        return None
    inner = 1.2 * rmax
    outer = max(1.2 * max(reported), inner * 1.5)
    radii = np.geomspace(inner, outer, AZ_N_RADII)
    az = np.arange(0.0, 360.0, AZ_STEP_DEG)
    lats, lons = C.ray_grid(snap.lat, snap.lon, az, radii)

    out = {}
    for method in C.METHODS:
        mag = np.asarray(T.buildVortex(lats, lons, snap, rmax,
                                       method=method)[0], dtype=float)
        res = {"bisector": [], "control": []}
        for label, azimuths in (("bisector", BISECTORS), ("control", CONTROLS)):
            for a0 in azimuths:
                # index into the wrapped azimuth axis relative to a0
                d = np.arange(-AZ_FIT_OUTER_DEG, AZ_FIT_OUTER_DEG + 1e-9,
                              AZ_STEP_DEG)
                idx = (((a0 + d) % 360.0) / AZ_STEP_DEG).round().astype(int)
                sub = mag[idx, :]                       # (nd, nradii)
                lo = d <= -AZ_FIT_INNER_DEG
                hi = d >= AZ_FIT_INNER_DEG
                for j in range(sub.shape[1]):
                    s_in = np.polyfit(d[lo], sub[lo, j], 1)[0]
                    s_out = np.polyfit(d[hi], sub[hi, j], 1)[0]
                    res[label].append(abs(float(s_out - s_in)))
        out[method] = res
    return out


def radial_kinks_and_monotonicity(snap, rmax, fit):
    """Per-method knot slope breaks, knot value jumps, and monotonicity."""
    rr = np.arange(RAY_STEP_NM, RAY_MAX_NM + RAY_STEP_NM, RAY_STEP_NM)
    lats, lons = C.ray_grid(snap.lat, snap.lon, RAY_AZ, rr)
    # Build both fields first, so the GTCM knot list can use the builder's own
    # r34 instead of a second, drifting copy of the calculation.
    fields = {}
    for method in C.METHODS:
        m, _dir, _r, r34 = T.buildVortex(lats, lons, snap, rmax, method=method)
        fields[method] = (np.asarray(m, dtype=float),
                          np.asarray(r34, dtype=float))

    # r34 varies only with azimuth, so one column is the per-azimuth value.
    gtcm_r34 = fields["gtcm"][1]
    gtcm_r34 = gtcm_r34[:, 0] if gtcm_r34.ndim == 2 else gtcm_r34
    knots = {"perquad": _perquad_knots(snap, rmax, RAY_AZ),
             "gtcm": _gtcm_knots(snap, RAY_AZ, fit, gtcm_r34)}

    out = {}
    for method in C.METHODS:
        mag = fields[method][0]
        kn, labels, taper_row = knots[method]
        breaks, jumps, breaks_nt, jumps_nt = [], [], [], []
        detail = {}
        for i in range(len(RAY_AZ)):
            col = kn[:, i]
            for row in range(len(col)):
                r0 = float(col[row])
                others = [float(col[k]) for k in range(len(col)) if k != row]
                gap = min([abs(o - r0) for o in others]) if others else 1e9
                w = float(np.clip(0.5 * gap, KNOT_FIT_MIN_W_NM,
                                  KNOT_FIT_MAX_W_NM))
                if r0 - w <= rr[0] or r0 + w >= rr[-1]:
                    continue
                a = _one_sided_fit(rr, mag[i], r0, -w, -KNOT_FIT_INNER_NM)
                b = _one_sided_fit(rr, mag[i], r0, KNOT_FIT_INNER_NM, w)
                if a is None or b is None:
                    continue
                brk = abs(b[0] - a[0])
                # The jump is the STEP across the knot, measured between the two
                # samples straddling it, not the gap between two linear
                # extrapolations.  Extrapolating over a window this wide turns
                # any curvature difference across the knot into a phantom jump:
                # on a deliberately continuous power-law-into-exponential test
                # function the old estimator reported 0.02, 0.09 and 0.30 kt at
                # 2, 5 and 10 nm windows respectively, for a true step of 1e-6.
                # The vortex is a power law and the taper is an exponential, so
                # that mismatch is exactly the shape this knot has.
                jmp = _step_across(rr, mag[i], r0)
                if jmp is None:
                    continue
                breaks.append(brk)
                jumps.append(jmp)
                d = detail.setdefault(labels[row], {"break": [], "jump": []})
                d["break"].append(brk)
                d["jump"].append(jmp)
                if row != taper_row:
                    breaks_nt.append(brk)
                    jumps_nt.append(jmp)

        viol = tot = 0
        peak = np.argmax(mag, axis=1)
        for i in range(len(RAY_AZ)):
            mm = mag[i]
            sel = np.zeros(mm.shape, dtype=bool)
            sel[peak[i] + 1:] = True
            sel &= mm >= MONO_MIN_KT
            pair = sel[:-1] & sel[1:]
            viol += int(np.count_nonzero((np.diff(mm) > MONO_EPS_KT) & pair))
            tot += int(np.count_nonzero(pair))
        out[method] = {"breaks": breaks, "jumps": jumps,
                       "breaksNoTaper": breaks_nt, "jumpsNoTaper": jumps_nt,
                       "monoViol": viol, "monoTotal": tot, "detail": detail}
    return out


def field_roughness(snap, rmax):
    """{method: roughness as a percentage of Vmax}, paired on one grid/mask."""
    lats, lons = C.ray_grid(snap.lat, snap.lon, ROUGH_AZ_DEG, ROUGH_R_NM)
    fields = {}
    for method in C.METHODS:
        fields[method] = np.asarray(T.buildVortex(lats, lons, snap, rmax,
                                                  method=method)[0], dtype=float)
    mask = np.zeros(fields["gtcm"].shape, dtype=bool)
    for f in fields.values():
        mask |= f >= ROUGH_MIN_KT
    out = {}
    for method, f in fields.items():
        d_r = np.abs(f[:, :-2] - 2.0 * f[:, 1:-1] + f[:, 2:])
        d_a = np.abs(np.roll(f, 1, axis=0) - 2.0 * f + np.roll(f, -1, axis=0))
        m = mask[:, 1:-1]
        if not m.any():
            out[method] = float("nan")
            continue
        tot = float(np.mean(d_r[m] + d_a[:, 1:-1][m]))
        out[method] = 100.0 * tot / max(float(snap.vmax), 1.0)
    return out


def coherence_for(cases, progress=None):
    """Accumulate the coherence measurements over a list of (sid, record)."""
    acc = _new_acc()
    n = 0
    for sid, rec in cases:
        snap = C._snapshot(rec)
        if not snap.radii:
            continue
        rmax = T.resolveRmax(snap, 0.0)
        fit = T.fitGTCM(snap)
        ak = azimuthal_kinks(snap, rmax)
        rk = radial_kinks_and_monotonicity(snap, rmax, fit)
        fr = field_roughness(snap, rmax)
        for m in C.METHODS:
            if ak:
                acc[m]["az"].extend(ak[m]["bisector"])
                acc[m]["azc"].extend(ak[m]["control"])
            acc[m]["brk"].extend(rk[m]["breaks"])
            acc[m]["jmp"].extend(rk[m]["jumps"])
            acc[m]["brkNT"].extend(rk[m]["breaksNoTaper"])
            acc[m]["jmpNT"].extend(rk[m]["jumpsNoTaper"])
            acc[m]["mv"] += rk[m]["monoViol"]
            acc[m]["mt"] += rk[m]["monoTotal"]
            for label, d in rk[m]["detail"].items():
                tgt = acc[m]["detail"].setdefault(label,
                                                  {"break": [], "jump": []})
                tgt["break"].extend(d["break"])
                tgt["jump"].extend(d["jump"])
            if np.isfinite(fr[m]):
                acc[m]["rough"].append(fr[m])
            acc[m]["cases"] += 1
            acc[m]["storms"].add(sid)
        n += 1
        if progress and n % progress == 0:
            sys.stderr.write("      coherence %d cases (%s)\n" % (n, sid))
            sys.stderr.flush()
    return acc


def _new_acc():
    return dict((m, {"az": [], "azc": [], "brk": [], "jmp": [],
                     "brkNT": [], "jmpNT": [], "mv": 0, "mt": 0,
                     "rough": [], "cases": 0, "storms": set(), "detail": {}})
                for m in C.METHODS)


def _mean(v):
    return float(np.mean(v)) if len(v) else float("nan")


def coherence_block(acc):
    out = {}
    for m in C.METHODS:
        a = acc[m]
        out[m] = {
            "azimuthalKinkKtPerDeg": _mean(a["az"]),
            "azimuthalKinkControlKtPerDeg": _mean(a["azc"]),
            "radialKinkKtPerNm": _mean(a["brk"]),
            "radialJumpKt": _mean(a["jmp"]),
            "radialKinkExclTaperKtPerNm": _mean(a["brkNT"]),
            "radialJumpExclTaperKt": _mean(a["jmpNT"]),
            "monotonicityViolationPct": (100.0 * a["mv"] / a["mt"]
                                         if a["mt"] else float("nan")),
            "fieldRoughnessPctVmax": _mean(a["rough"]),
            "cases": a["cases"],
            "casesStorms": len(a["storms"]),
            "byKnot": dict((label,
                            {"kinkKtPerNm": _mean(d["break"]),
                             "jumpKt": _mean(d["jump"]),
                             "n": len(d["break"])})
                           for label, d in sorted(a["detail"].items())),
        }
    return out


def merge_acc(dst, src):
    for m in C.METHODS:
        for k in ("az", "azc", "brk", "jmp", "brkNT", "jmpNT", "rough"):
            dst[m][k].extend(src[m][k])
        for label, d in src[m]["detail"].items():
            tgt = dst[m]["detail"].setdefault(label, {"break": [], "jump": []})
            tgt["break"].extend(d["break"])
            tgt["jump"].extend(d["jump"])
        dst[m]["mv"] += src[m]["mv"]
        dst[m]["mt"] += src[m]["mt"]
        dst[m]["cases"] += src[m]["cases"]
        dst[m]["storms"] |= src[m]["storms"]
    return dst


# ---------------------------------------------------------------------------
# diagnostic: what GTCM would look like with a continuous eq. (3)
# ---------------------------------------------------------------------------

def _gtcm_profile_continuous(r, vmax, a, rm, ri, x1, x2):
    """_gtcmProfile with a continuity factor that actually is one.

    TCWind_JTWC._gtcmProfile uses A = (ri/rm)**x1 * (rm/ri)**x2.  Matching the
    two branches at r = ri requires (rm/ri)**x1 == A*(rm/ri)**x2, i.e.
    A = (rm/ri)**x1 * (ri/rm)**x2 - the RECIPROCAL of what is there.  As
    written the outer branch is scaled by (ri/rm)**(2*(x1-x2)) and V steps at
    ri; with the typical fitted x1 > x2 that is a step UP.

    This build does not own GFE/procedures/TCWind_JTWC.py, so nothing is fixed
    here.  This function exists only to answer "how much of GTCM's measured
    incoherence is the model and how much is that one line", by re-running the
    coherence block with it patched in at runtime.
    """
    vs = max(float(vmax) - float(a), 0.0)
    rm = max(float(rm), 1e-3)
    ri = max(float(ri), rm * 1.0001)
    safe = np.maximum(np.asarray(r, dtype=float), 1e-6)
    A = (rm / ri) ** x1 * (ri / rm) ** x2
    return np.where(safe < rm, vs * (safe / rm),
                    np.where(safe < ri,
                             vs * (rm / safe) ** x1,
                             A * vs * (rm / safe) ** x2))


def coherence_with_continuous_ri(cases, progress=None):
    """coherence_for() with the continuity-preserving eq. (3) patched in.

    fitGTCM() calls _gtcmProfile too, so the fit is redone against the
    corrected profile - which is what a corrected implementation would do.

    compare_vortex_methods.py memoises T.fitGTCM by the snapshot's own
    content, which says nothing about which T._gtcmProfile is active - so a
    snapshot already fit under the normal profile (by the ring/field/
    coherence passes above) would otherwise hand back its stale, wrong-
    profile fit here instead of being re-fit under this patched one. Clear
    the cache around the swap so every fit in this pass is genuinely
    recomputed, and again on the way out so the normal profile's callers
    after this don't inherit a fit computed under the patched one either.
    """
    C.clear_fit_cache()
    original = T._gtcmProfile
    T._gtcmProfile = _gtcm_profile_continuous
    try:
        return coherence_for(cases, progress=progress)
    finally:
        C.clear_fit_cache()
        T._gtcmProfile = original


def ri_step_stats(cases):
    """Size of the step in V at ri, as the shipped profile builds it."""
    ratios, kt = [], []
    storms = set()
    for sid, rec in cases:
        snap = C._snapshot(rec)
        if not snap.radii:
            continue
        f = T.fitGTCM(snap)
        ri = f["ri"]
        lo = float(T._gtcmProfile(np.array([ri * (1.0 - 1e-9)]), snap.vmax,
                                  f["a"], f["rm"], ri, f["x1"], f["x2"])[0])
        hi = float(T._gtcmProfile(np.array([ri * (1.0 + 1e-9)]), snap.vmax,
                                  f["a"], f["rm"], ri, f["x1"], f["x2"])[0])
        if lo > 0:
            ratios.append(hi / lo)
            kt.append(hi - lo)
            storms.add(sid)
    if not ratios:
        return {}
    r = np.asarray(ratios)
    return {"n": len(ratios), "nStorms": len(storms),
            "meanRatio": float(np.mean(r)),
            "medianRatio": float(np.median(r)),
            "maxRatio": float(np.max(r)),
            "meanStepKt": float(np.mean(kt)),
            "medianStepKt": float(np.median(kt)),
            "maxStepKt": float(np.max(kt)),
            "pctStepUp": float(100.0 * np.mean(r > 1.0005))}


# ---------------------------------------------------------------------------
# fit quality
# ---------------------------------------------------------------------------

def fit_quality(cases):
    rms, rm, x1, x2, ri = [], [], [], [], []
    storms = set()
    for sid, rec in cases:
        snap = C._snapshot(rec)
        if not snap.radii:
            continue
        f = T.fitGTCM(snap)
        if np.isfinite(f["rms"]):
            rms.append(f["rms"])
        rm.append(f["rm"])
        ri.append(f["ri"])
        x1.append(f["x1"])
        x2.append(f["x2"])
        storms.add(sid)

    def med(v):
        return float(np.median(v)) if len(v) else float("nan")
    return {"rmsWindErrKt": _mean(rms), "medianRmsWindErrKt": med(rms),
            "medianRm": med(rm), "medianRi": med(ri),
            "medianX1": med(x1), "medianX2": med(x2),
            "n": len(rm), "nStorms": len(storms)}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=int, default=0,
                    help="storm-times per basin for ring/field numbers. "
                         "0 (default) = the whole usable population of "
                         "each basin, sampled by seeded round-robin across "
                         "storms if a smaller value is given (see "
                         "compare_vortex_methods.load_cases)")
    ap.add_argument("--coherence-cases", type=int, default=50,
                    help="storm-times per basin for the coherence block "
                         "(default 50 - a real subsample, not the whole "
                         "archive, because that block's cost scales with "
                         "grid points x cases; chosen so seeded round-robin "
                         "still covers at least 40 distinct storms in "
                         "every basin, all of which have >=57 usable "
                         "storms)")
    ap.add_argument("--seed", type=int, default=C.DEFAULT_SEED,
                    help="storm-shuffle seed for --cases/--coherence-cases "
                         "sampling (default %d)" % C.DEFAULT_SEED)
    ap.add_argument("--basins", default="WP,NA,EP")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--progress", type=int, default=20)
    ap.add_argument("--no-ri-diagnostic", action="store_true",
                    help="skip the continuous-eq-(3) diagnostic pass")
    ap.add_argument("--no-holdout", action="store_true",
                    help="skip verify_holdout.py's held-out-radius block "
                         "(fast - only skip this for a quick smoke test)")
    ap.add_argument("--no-stratified", action="store_true",
                    help="skip verify_stratified.py's byNature/byLand "
                         "blocks (the slowest part of a full run - its "
                         "ringFit pass touches every usable() record)")
    args = ap.parse_args()

    t_start = time.time()
    basins = [b.strip().upper() for b in args.basins.split(",") if b.strip()]
    cases_limit = args.cases if args.cases and args.cases > 0 else None

    findings = {
        "generated": datetime.date.today().isoformat(),
        "model": {
            "name": "GTCM/WTCM",
            "guide": "Gridded TCM Users Guide v1.9.1 (Santos & DeMaria, "
                     "4 Dec 2023)",
            "method": T.VORTEX_METHOD,
            "departures": [
                "The profile is tapered exponentially beyond the modelled "
                "34 kt radius so the GFE insert terminates. NHC leaves its "
                "own grids missing outside R34 and lets the receiving office "
                "blend; this tool inserts into a background instead, so it "
                "needs a finite edge.",
                "Step 4's boundary-layer / land-roughness reduction is not "
                "implemented - it needs the USGS land-surface database, which "
                "this procedure does not have. The field is marine-exposure "
                "everywhere and will be too strong over land.",
            ],
        },
        "scope": {}, "ringFit": {}, "ringFitVsTarget": {}, "neverReached": {},
        "fieldDiff": {}, "fitQuality": {}, "coherence": {},
        "coherenceByBasin": {}, "coherenceDefinitions": COHERENCE_DEFS,
        "coherenceDiagnostics": {}, "holdout": {}, "byNature": {},
        "byLand": {}, "runtime": {}, "notes": {},
    }

    pooled = _new_acc()
    pooled_fix = _new_acc()
    ri_cases = []
    runtime = {}

    for basin in basins:
        scope = C.basin_scope(basin)
        if scope is None:
            sys.stderr.write("%s: no data on disk, skipped\n" % basin)
            continue
        t0 = time.time()
        cases = C.load_cases(basin, cases_limit, seed=args.seed)
        sys.stderr.write("%s: %d storms, %d records, %d usable; "
                         "evaluating %d (%d distinct storms)\n"
                         % (basin, scope["storms"], scope["records"],
                            scope["usableRecords"], len(cases),
                            len(C.case_storms(cases))))
        res = C.evaluate(cases, progress=args.progress)
        findings["ringFit"][basin] = res["ringFit"]
        findings["ringFitVsTarget"][basin] = res["ringFitVsTarget"]
        findings["neverReached"][basin] = res["neverReached"]
        findings["fieldDiff"][basin] = res["fieldDiff"]
        findings["fitQuality"][basin] = fit_quality(cases)
        t_ring = time.time()

        ccases = cases[:args.coherence_cases] if args.coherence_cases else cases
        acc = coherence_for(ccases, progress=args.progress)
        findings["coherenceByBasin"][basin] = coherence_block(acc)
        merge_acc(pooled, acc)
        ri_cases.extend(ccases)
        if not args.no_ri_diagnostic:
            merge_acc(pooled_fix,
                      coherence_with_continuous_ri(ccases,
                                                   progress=args.progress))
        t_coh = time.time()

        scope = dict(scope)
        scope["casesEvaluated"] = res["cases"]
        scope["casesEvaluatedStorms"] = res["storms"]
        scope["coherenceCases"] = len(ccases)
        scope["coherenceCasesStorms"] = len(C.case_storms(ccases))
        scope["agency"] = {"WP": "jtwc_wp", "NA": "hurdat_atl",
                           "EP": "hurdat_epa"}.get(basin, "")
        findings["scope"][basin] = scope
        runtime[basin] = {"ringFieldSec": round(t_ring - t0, 1),
                          "coherenceSec": round(t_coh - t_ring, 1)}

    findings["coherence"] = coherence_block(pooled)
    if not args.no_ri_diagnostic and ri_cases:
        findings["coherenceDiagnostics"] = {
            "riStep": ri_step_stats(ri_cases),
            "gtcmWithContinuousRi": coherence_block(pooled_fix)["gtcm"],
            "note":
                "HISTORICAL, NOT A LIVE BUG - kept as a regression "
                "indicator. TCWind_JTWC._gtcmProfile's continuity factor "
                "for eq. (3) was A = (ri/rm)**x1 * (rm/ri)**x2. Matching "
                "the two branches at r = ri requires the reciprocal, "
                "A = (rm/ri)**x1 * (ri/rm)**x2; as originally written the "
                "outer branch was scaled by (ri/rm)**(2*(x1-x2)) and the "
                "modelled wind STEPPED at ri. That was fixed in "
                "GFE/procedures/TCWind_JTWC.py (commit 530f876, 'Fix "
                "eq. (3) continuity factor...') before this note was last "
                "edited - the fix is live: _gtcmProfile now uses the "
                "reciprocal form, and riStep below (computed from the "
                "SHIPPED profile, every run) is the proof: it should read "
                "at or near zero. riStep measures the step in the field as "
                "built, whatever that currently is. gtcmWithContinuousRi is "
                "the whole coherence block recomputed with the continuity-"
                "preserving factor patched in at runtime (the fit is redone "
                "too, via a temporary T._gtcmProfile swap - see "
                "coherence_with_continuous_ri()), so a reader can separate "
                "what the GTCM model does from what this one line does. "
                "This diagnostic changes no source: GFE/procedures/"
                "TCWind_JTWC.py is the reference implementation and this "
                "verification does not own it - kept running every time so "
                "a regression here (riStep drifting back off zero) would be "
                "caught, not so it can keep describing a bug that is gone.",
        }

    findings["runtime"] = {
        "byBasin": runtime,
        "totalSec": round(time.time() - t_start, 1),
        "note":
            "ringFieldSec/coherenceSec are wall-clock seconds for THIS run "
            "(this machine, this --cases/--coherence-cases), not a "
            "portable benchmark - see tests/tcwind_jtwc/README.md for a "
            "worked full-archive example. compare_vortex_methods.py "
            "memoises T.fitGTCM per snapshot and uses a coarser (but still "
            "sub-nm-accurate) radial search grid than its original 12000-"
            "step version specifically to make a whole-archive default run "
            "tractable - see that module's own comments on R_STEPS and "
            "_cached_fit_gtcm.",
    }

    findings["notes"] = {
        "ringFit":
            "Signed radial error, in nm, of the modelled isotach crossing "
            "against the radius the bulletin reported, along each quadrant "
            "bisector. This is a description of where the field lands, not a "
            "skill score: GTCM is specified to fit the quadrant-AVERAGE wind "
            "and so sits inside the reported quadrant maximum on purpose.",
        "ringFitVsTarget":
            "The same errors against 0.85 x the reported radius - the "
            "quadrant-average radius the GTCM fit is actually aimed at "
            "(Users Guide step 2c, GTCM_QUAD_AVG_FACTOR). BOTH methods are "
            "scored against that same target, so perquad's positive bias here "
            "is the correct reading that it reproduces the quadrant maximum "
            "and therefore overshoots the quadrant average.",
        "neverReached":
            "Reported rings the modelled field never reaches at any radius "
            "along that quadrant bisector. perquad is 0 by construction. For "
            "GTCM these are mostly inner rings on storms whose reported "
            "structure one symmetric vortex cannot hold at once.",
        "fieldDiff":
            "gtcm minus perquad over a polar grid out to 400 nm. Area ratios "
            "are gtcm area / perquad area for that isotach, reported as the "
            "median over cases; the ratio is unbounded above and its mean is "
            "skewed by cases where the perquad area nearly vanishes. Cases "
            "with no perquad area at all are undefined and excluded (see "
            "areaRatio<N>N for how many contributed).",
        "coherence":
            "The reason for the switch. Higher is rougher for every entry. "
            "Compare each method's azimuthalKink against its own "
            "azimuthalKinkControl, which is the estimator's noise floor. "
            "Definitions are in coherenceDefinitions.",
        "fitQuality":
            "rmsWindErrKt is the weighted RMS wind error of the GTCM least-"
            "squares fit at its own target points (eq. 7), in kt - a measure "
            "of how well one symmetric vortex plus a wavenumber-1 asymmetry "
            "can hold the reported structure, not of forecast accuracy.",
        "verification":
            "Everything here is a comparison against best-track ANALYSES of "
            "storm structure, not against observations. It shows internal "
            "consistency and the difference between two constructions; it is "
            "not a validation of the wind field.",
        "sources":
            "WP: JTWC best track via IBTrACS, agency jtwc_wp, from the "
            "committed 100-storm sample. NA/EP: NHC HURDAT via IBTrACS, "
            "agencies hurdat_atl / hurdat_epa, from the generated archive.",
        "holdout":
            "verify_holdout.py's held-out-radius skill check - see its own "
            "docstring/caveat and findings.holdout.caveat. The only block "
            "here that scores GTCM against radii it was NOT fit to; every "
            "other block above is self-consistency (scored at the fit's "
            "own target points) or coherence (smoothness, explicitly not "
            "accuracy).",
        "byNature": "verify_stratified.py's byNature block - the ringFit "
            "and holdout statistics above, split by IBTrACS storm-nature "
            "flag instead of by basin. See its own docstring/caveat.",
        "byLand": "verify_stratified.py's byLand block - the same "
            "statistics again, split by distance to nearest land instead. "
            "See its own docstring/caveat.",
        "independence":
            "STORM-LEVEL INDEPENDENCE CAVEAT, applies to every n/nStorms "
            "pair in this file. Every stat's n counts individual 6-hourly "
            "storm-time RECORDS, and consecutive records of one storm are "
            "highly autocorrelated - same Vmax within a few kt, same radii "
            "within one report, same motion. nStorms (the distinct-storm "
            "count behind those n records) is reported alongside every "
            "stat for this reason: treat n as the sample size for the "
            "estimate's precision, but nStorms as the sample size for how "
            "many genuinely independent storms that estimate is drawn "
            "from - a stat with a large n but a small nStorms (a handful "
            "of storms reporting many records each) generalizes less than "
            "the same n spread across many storms would. Nothing here "
            "does a storm-level train/test split or a storm-clustered "
            "variance correction; fit_westpac_rmax.py is the one script in "
            "this suite that does (an 80/20 split by storm SID).",
        "quadAvgFactor":
            "T.GTCM_QUAD_AVG_FACTOR (0.85), used throughout ringFitVsTarget "
            "above, is a CITATION, not a local measurement: it comes from "
            "the Gridded TCM Users Guide (step 2c), which in turn cites the "
            "Wind Speed Probability model (DeMaria et al. 2009) - see the "
            "comment at GFE/procedures/TCWind_JTWC.py's GTCM_QUAD_AVG_"
            "FACTOR definition. No script in this suite independently "
            "measures a quadrant-max/quadrant-average ratio against this "
            "project's own archive data, and IBTrACS best-track only ever "
            "reports the quadrant MAXIMUM, never the quadrant average, so "
            "there is no ground truth in this project's data to check the "
            "0.85 figure against directly. Read ringFitVsTarget as scoring "
            "against an imported, unvalidated-here convention, not a "
            "locally-verified target.",
    }

    if not args.no_holdout:
        sys.stderr.write("holdout: scoring verify_holdout.py's held-out-"
                         "radius experiments...\n")
        findings["holdout"] = verify_holdout.compute(
            tuple(basins), progress=args.progress)
    if not args.no_stratified:
        sys.stderr.write("byNature/byLand: scoring verify_stratified.py's "
                         "stratified pipeline (the slowest part of a full "
                         "run - touches every usable() record)...\n")
        strat = verify_stratified.compute(tuple(basins),
                                          progress=args.progress)
        findings["byNature"] = strat["byNature"]
        findings["byLand"] = strat["byLand"]
        findings["runtime"]["stratifiedSec"] = strat["runtimeSec"]
    if findings.get("holdout"):
        findings["runtime"]["holdoutSec"] = findings["holdout"].get(
            "runtimeSec")
    findings["runtime"]["totalSec"] = round(time.time() - t_start, 1)

    with open(args.out, "w") as fh:
        json.dump(findings, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote %s" % args.out)

    # Console summary - the coherence table is the point, so print it.
    print("\nCOHERENCE (pooled over %s; higher = rougher)"
          % ", ".join(b for b in basins if b in findings["scope"]))
    rows = [("azimuthal kink at bisectors", "azimuthalKinkKtPerDeg", "kt/deg"),
            ("   same estimator, control", "azimuthalKinkControlKtPerDeg",
             "kt/deg"),
            ("radial slope break at knots", "radialKinkKtPerNm", "kt/nm"),
            ("   excluding the outer taper", "radialKinkExclTaperKtPerNm",
             "kt/nm"),
            ("radial VALUE jump at knots", "radialJumpKt", "kt"),
            ("   excluding the outer taper", "radialJumpExclTaperKt", "kt"),
            ("monotonicity violations", "monotonicityViolationPct", "%"),
            ("2-D field roughness", "fieldRoughnessPctVmax", "% Vmax")]
    print("   %-30s %10s %10s   %s" % ("", "perquad", "gtcm", "units"))
    for label, key, units in rows:
        print("   %-30s %10.4f %10.4f   %s"
              % (label, findings["coherence"]["perquad"][key],
                 findings["coherence"]["gtcm"][key], units))
    print("   %-30s %10d %10d" % ("cases",
                                  findings["coherence"]["perquad"]["cases"],
                                  findings["coherence"]["gtcm"]["cases"]))
    diag = findings.get("coherenceDiagnostics") or {}
    if diag:
        st = diag["riStep"]
        print("\n   eq. (3) continuity at ri, as built: mean step %+.2f kt "
              "(x%.4f), median %+.2f kt, max %+.2f kt, %.0f%% step UP, n=%d"
              % (st["meanStepKt"], st["meanRatio"], st["medianStepKt"],
                 st["maxStepKt"], st["pctStepUp"], st["n"]))
        fixed = diag["gtcmWithContinuousRi"]
        print("   the same gtcm column with a CONTINUOUS eq. (3):")
        for label, key, units in rows:
            print("   %-30s %10s %10.4f   %s" % (label, "", fixed[key], units))
    print("\n   per knot (slope break kt/nm, value jump kt)")
    for method in C.METHODS:
        for label, d in findings["coherence"][method]["byKnot"].items():
            print("   %-9s %-10s break %8.4f   jump %8.4f   n=%d"
                  % (method, label, d["kinkKtPerNm"], d["jumpKt"], d["n"]))

    print("\nRUNTIME (this run, this machine)")
    for basin, rt in findings["runtime"].get("byBasin", {}).items():
        print("   %-4s ring/field %6.1fs   coherence %6.1fs"
              % (basin, rt["ringFieldSec"], rt["coherenceSec"]))
    if "holdoutSec" in findings["runtime"]:
        print("   holdout      %6.1fs" % findings["runtime"]["holdoutSec"])
    if "stratifiedSec" in findings["runtime"]:
        print("   stratified   %6.1fs" % findings["runtime"]["stratifiedSec"])
    print("   TOTAL        %6.1fs" % findings["runtime"]["totalSec"])


if __name__ == "__main__":
    main()
