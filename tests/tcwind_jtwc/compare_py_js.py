#!/usr/bin/env python3
"""Cross-check the Python and JavaScript implementations against each other.

Independent of whether either side is "correct" against expected/, this
catches the two drifting apart - the actual risk called out in both files'
own comments, and the reason a divergent third copy of resolveRmax() (with
`<=` where the tool has `<`) once shipped in Findings.html.

Four check groups:

  1. parseJTWC(), Python vs **Code.gs**        - the Apps Script server parser
  2. parseJTWC(), Python vs **Vortex.html**    - the shared client parser
  2b. the same, on reformatted bulletins       - whitespace and line-wrap
  3. GTCM vortex, Python vs **Vortex.html**    - the tool's current default
  4. per-quadrant vortex, Python vs Index.html - the retired construction

Group 3 is the one that matters operationally: VORTEX_METHOD is "gtcm", so
that is the field the GFE procedure builds and the field the web preview
must show. Group 4 exists only so the retired construction cannot rot
silently while it is still reachable; it SKIPs itself, loudly, once
Index.html stops carrying its own vortexAt().

Groups 1 and 2 both run because there really are two JavaScript parsers in
the repo and they cannot be merged: Code.gs is server-side Apps Script
(parsePasted/getBulletins run there, and .gs code cannot call into an HTML
<script> block), while Vortex.html is what the pages use client-side.
Comparing both against the same Python catches them drifting from each
other as well as from the reference.

    python3 compare_py_js.py

Tolerances are the build contract's: 0.5 kt on magnitude, 1 nm on radii,
1 degree on direction. Do not loosen them to make a run pass - report the
divergence instead.

Known benign residual, group 4 only: a sample point landing almost exactly
on a reported ring radius can be assigned to different piecewise segments
on the two sides. Python's per-quadrant grids are float32 (matching real
AWIPS grid precision, hence the deliberate .astype(np.float32) casts in
buildVortex()); JS is float64 throughout, and a ~1e-12 nm difference in the
recovered radius is enough to land a razor's-edge point a hair either side
of a knot. BOUNDARY_TOL covers exactly those points and nothing else.

The GTCM construction has no equivalent residual. Its only float32 exposure
is the final .astype(np.float32) on mag/dir/r34 in _buildVortexGTCM(), worth
about 1e-6 kt at hurricane strength - five orders of magnitude inside
tolerance, and the whole of the observed group-3 difference. The JS mirrors
the r34 cast (Math.fround) because there the quantity is a radius compared
at 1 nm; mag and dir are left in float64, which is strictly better and
costs 1e-6 kt of agreement.

GTCM does step at ri, but IDENTICALLY on both sides. _gtcmProfile()'s
continuity factor A is the reciprocal of the one continuity requires - see
the KNOWN DEFECT note in Vortex.html's gtcmProfile() - so the profile jumps
at ri by up to ~12 kt on the fits exercised here. This suite deliberately
probes exactly on ri and does NOT paper over it: both ports must jump by
the same amount, and they do. Fixing the defect means changing
TCWind_JTWC.py and Vortex.html in one commit and re-running this suite.
"""
import glob
import json
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = sorted(glob.glob(os.path.join(HERE, "fixtures", "*.txt")))

sys.path.insert(0, os.path.join(HERE, "..", "..", "GFE", "procedures"))
import numpy as np                      # noqa: E402
import TCWind_JTWC as tc                # noqa: E402

# Scratch lives outside the repo: this script writes snapshot/point JSON for
# the Node side to read, and none of it belongs in version control.
SCRATCH = tempfile.mkdtemp(prefix="tcwind_compare_")

# --- tolerances -------------------------------------------------------------
FLOAT_TOL = 1e-3      # parse fields and the geometry both sides share
BOUNDARY_TOL = 2.0    # kt, group 4's documented on-a-ring probes only

# Build contract, section 4.
MAG_TOL = 0.5         # kt
RAD_TOL = 1.0         # nm  - applies to r, r34, and the fitted rm / ri
DIR_TOL = 1.0         # degrees, compared as a circular difference
# Not fixed by the contract: x1/x2 are the dimensionless Rankine exponents.
# 0.01 is roughly the change that moves the modelled R34 by a nautical mile
# on a typical fit, so it is the same claim as RAD_TOL expressed in the
# parameter the field is actually built from.
EXP_TOL = 0.01

EXIT_UNAVAILABLE = 3


def run(cmd, allow_unavailable=False):
    out = subprocess.run(cmd, capture_output=True, text=True)
    if allow_unavailable and out.returncode == EXIT_UNAVAILABLE:
        return None, out.stderr.strip()
    if out.returncode != 0:
        raise RuntimeError("command failed: %s\n%s" % (" ".join(cmd), out.stderr))
    return json.loads(out.stdout), None


def jnum(x):
    """JSON has no NaN; normalise both sides to None so a radii-less fit
    (rms = NaN) compares equal instead of blowing up."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def angdiff(a, b):
    """Smallest absolute difference between two bearings, in degrees. A
    plain subtraction reports 359.8 for 359.9 vs 0.1, which is why the
    0/360 seam needs its own comparison and is deliberately sampled."""
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


# ---------------------------------------------------------------------------
# Generic diffing (groups 1, 2 and 4)
# ---------------------------------------------------------------------------

def diff_scalar(path, a, b, out):
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            if a != b:
                out.append("%s: py=%r js=%r" % (path, a, b))
        elif abs(float(a) - float(b)) > FLOAT_TOL:
            out.append("%s: py=%r js=%r (diff %.4g)" % (path, a, b, abs(a - b)))
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append("%s.%s: missing on py side" % (path, k))
            elif k not in b:
                out.append("%s.%s: missing on js side" % (path, k))
            else:
                diff_scalar("%s.%s" % (path, k), a[k], b[k], out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s: length py=%d js=%d" % (path, len(a), len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            diff_scalar("%s[%d]" % (path, i), x, y, out)
    else:
        if a != b:
            out.append("%s: py=%r js=%r" % (path, a, b))


# ---------------------------------------------------------------------------
# Groups 1 and 2: the parsers
# ---------------------------------------------------------------------------

def check_parse(js_cmd, title):
    print("=== parseJTWC(): Python vs %s ===" % title)
    failed = 0
    for fixture in FIXTURES:
        name = os.path.basename(fixture)
        py, _ = run([sys.executable, os.path.join(HERE, "tools_py.py"),
                     "parse", fixture])
        js, why = run(["node", os.path.join(HERE, "tools_js.js"), js_cmd, fixture],
                      allow_unavailable=True)
        if js is None:
            print("SKIP   %s - %s" % (name, why))
            continue
        diffs = []
        diff_scalar(name, py, js, diffs)
        if diffs:
            failed += 1
            print("FAIL   %s" % name)
            for d in diffs[:20]:
                print("       " + d)
        else:
            print("PASS   %s" % name)
    return failed


# ---------------------------------------------------------------------------
# Group 2b: parser whitespace / formatting variants
# ---------------------------------------------------------------------------

def whitespace_variants(text):
    """Reformattings of a real bulletin that a `\\s+` in the Python and a
    literal space in the JavaScript would disagree about.

    This group exists because comparing two parsers on the SAME seven
    fixtures can only ever catch a divergence the fixtures happen to
    exercise, and none of them contains a doubled space, a tab, or a phrase
    broken across a line - which is exactly the shape of the bug being
    guarded against. Bulletins are word-wrapped at ~72 columns by a system
    that has no obligation to be consistent about it.

    The variants are generated here rather than added to fixtures/ on
    purpose: fixtures/ is the golden-snapshot corpus for
    test_parser_golden.py, and adding to it would silently invalidate that
    suite's committed expectations. These go to a scratch directory instead.

    Correctness is not the claim - if a variant makes the Python parser
    produce nonsense, the JavaScript must produce the same nonsense. The
    claim is only that the two agree.
    """
    variants = [("verbatim", text)]

    # CRLF. Python's parseJTWC splits on "\n" only and keeps the trailing
    # "\r" on every line; the JS splits on /\r?\n/ and drops it. Every
    # pattern that could see one is either unanchored or ends in `\s*$`, so
    # the two should agree anyway - this variant is what proves it.
    variants.append(("crlf", text.replace("\n", "\r\n")))

    # Doubled spaces at each `\s+` site in the Python regexes.
    t = text
    t = t.replace("RADIUS OF ", "RADIUS OF  ")
    t = t.replace(" NM NORTHEAST QUADRANT", " NM  NORTHEAST  QUADRANT")
    t = t.replace(" NM SOUTHEAST QUADRANT", " NM  SOUTHEAST  QUADRANT")
    t = t.replace(" HRS, VALID AT:", "  HRS,  VALID AT:")
    t = t.replace("VECTOR TO ", "VECTOR TO  ")
    t = t.replace("WARNING NR ", "WARNING  NR  ")
    variants.append(("doubled spaces", t))

    # Tabs, which \s matches on both sides and a literal space does not.
    variants.append(("tabs", text.replace(" NM SOUTHWEST QUADRANT",
                                          " NM\tSOUTHWEST\tQUADRANT")))

    # "MINIMUM CENTRAL PRESSURE" split across a line break, which is the
    # documented reason RE_PRESSURE uses `\s+` and re.DOTALL. Appended
    # inside the remarks block, where it appears in real products.
    variants.append(("wrapped pressure",
                     text.rstrip("\n") + "\n   MINIMUM CENTRAL\n"
                     "   PRESSURE AT 312100Z IS 950 MB//\n"))

    # Leading zeros on the forecast hour: Python int("012") is 12, and so is
    # parseInt("012", 10) - but parseInt("012") without a radix is a live
    # hazard and this is where it would show.
    t = text
    for hh in ("12", "24", "36", "48", "72", "96"):
        t = t.replace("\n   %s HRS, VALID AT:" % hh, "\n   0%s HRS, VALID AT:" % hh)
    variants.append(("zero-padded tau hours", t))

    return variants


def check_parse_variants():
    print("\n=== parseJTWC(): whitespace / formatting variants, "
          "Python vs Code.gs vs Vortex.html ===")
    path = os.path.join(SCRATCH, "variant.txt")
    failed = 0
    for fixture in FIXTURES:
        base = os.path.basename(fixture)
        with open(fixture) as f:
            text = f.read()
        for vname, vtext in whitespace_variants(text):
            with open(path, "w", newline="") as f:
                f.write(vtext)
            label = "%s [%s]" % (base, vname)
            try:
                py, _ = run([sys.executable, os.path.join(HERE, "tools_py.py"),
                             "parse", path])
            except RuntimeError as exc:
                # The Python is the reference: if it refuses the input, the
                # JS must refuse it too.
                js_ok = True
                for cmd in ("parse", "parsev"):
                    out = subprocess.run(
                        ["node", os.path.join(HERE, "tools_js.js"), cmd, path],
                        capture_output=True, text=True)
                    if out.returncode == 0:
                        js_ok = False
                        print("FAIL   %s - Python rejected the input, %s "
                              "accepted it" % (label, cmd))
                if js_ok:
                    print("PASS   %s (both sides reject: %s)"
                          % (label, str(exc).splitlines()[-1][:60]))
                else:
                    failed += 1
                continue

            diffs = []
            for cmd, who in (("parse", "Code.gs"), ("parsev", "Vortex.html")):
                js, why = run(["node", os.path.join(HERE, "tools_js.js"),
                               cmd, path], allow_unavailable=True)
                if js is None:
                    print("SKIP   %s (%s) - %s" % (label, who, why))
                    continue
                diff_scalar("%s/%s" % (label, who), py, js, diffs)
            if diffs:
                failed += 1
                print("FAIL   %s" % label)
                for d in diffs[:10]:
                    print("       " + d)
                if len(diffs) > 10:
                    print("       ... and %d more" % (len(diffs) - 10))
            else:
                print("PASS   %s" % label)
    return failed


# ---------------------------------------------------------------------------
# Snapshots under test
# ---------------------------------------------------------------------------

def snapshot_cases():
    """(label, snapshot-dict) pairs driven through the GTCM path.

    The fixtures are all northern-hemisphere WestPac typhoons with radii, so
    the synthetic cases below carry the structural situations the parity
    suite would otherwise never see. Each one exists because it is a place
    the two ports can diverge without anything else noticing:

      no radii at all      fitGTCM()'s step-2c early return - climatology
                           only, n = 0, rms = NaN. NaN crosses a JSON
                           boundary differently in each language.
      000 NM quadrant      a reported 000 contributes no fit target. A JS
                           port that reads it as a zero-radius constraint,
                           or lets `undefined` through as NaN, breaks here
                           and nowhere else.
      southern hemisphere  the tangential term reverses (lat < 0) while the
                           asymmetry vector does NOT. The Users Guide is
                           NHC's and describes only the northern hemisphere,
                           so this behaviour exists in the Python and in
                           nothing the guide says.
      stale inner ring     vmax below a reported threshold. resolveRmax()
                           and _gtcmTargets() both guard with `<`, not
                           `<=`; a `<=` copy passes every other case here.
      exact-threshold vmax vmax == a reported threshold - the case the `<`
                           guard exists to keep, and the one a `<=` copy
                           silently drops.
      no motion            motionSpd 0, so a = 0 and fitGTCM() skips the
                           whole asymmetry-release stage.
      dateline / seam      centre on the dateline, so sample azimuths land
                           either side of the 0/360 longitude wrap as well
                           as the 0/360 azimuth wrap.
    """
    cases = []

    for fixture in FIXTURES:
        py, _ = run([sys.executable, os.path.join(HERE, "tools_py.py"),
                     "parse", fixture])
        taus = [t for t in py["taus"] if t["radii"]] or py["taus"]
        if not taus:
            continue
        t = taus[0]
        cases.append((os.path.basename(fixture), {
            "lat": t["lat"], "lon": t["lon"], "vmax": t["vmax"],
            "radii": t["radii"], "motionDir": t["motionDir"],
            "motionSpd": t["motionSpd"],
        }))

    cases.append(("synthetic: no radii at all", {
        "lat": 12.5, "lon": 138.0, "vmax": 35.0, "radii": {},
        "motionDir": 285.0, "motionSpd": 11.0}))

    cases.append(("synthetic: 000 NM quadrants", {
        "lat": 19.0, "lon": 129.5, "vmax": 95.0,
        "radii": {"34": {"NE": 150, "SE": 120, "SW": 0, "NW": 90},
                  "50": {"NE": 80, "SE": 0, "SW": 0, "NW": 45},
                  "64": {"NE": 45, "SE": 0, "SW": 0, "NW": 0}},
        "motionDir": 310.0, "motionSpd": 14.0}))

    cases.append(("synthetic: southern hemisphere", {
        "lat": -18.4, "lon": 168.2, "vmax": 105.0,
        "radii": {"34": {"NE": 110, "SE": 130, "SW": 95, "NW": 80},
                  "50": {"NE": 60, "SE": 70, "SW": 50, "NW": 40},
                  "64": {"NE": 35, "SE": 40, "SW": 25, "NW": 20}},
        "motionDir": 195.0, "motionSpd": 9.0}))

    cases.append(("synthetic: southern hemisphere, no radii", {
        "lat": -9.8, "lon": -175.0, "vmax": 40.0, "radii": {},
        "motionDir": 200.0, "motionSpd": 6.0}))

    cases.append(("synthetic: stale inner ring (vmax 45 < R50)", {
        "lat": 22.0, "lon": 142.0, "vmax": 45.0,
        "radii": {"34": {"NE": 100, "SE": 90, "SW": 60, "NW": 70},
                  "50": {"NE": 40, "SE": 35, "SW": 25, "NW": 30}},
        "motionDir": 20.0, "motionSpd": 18.0}))

    cases.append(("synthetic: vmax exactly on a threshold (50)", {
        "lat": 16.0, "lon": 145.0, "vmax": 50.0,
        "radii": {"34": {"NE": 95, "SE": 85, "SW": 55, "NW": 65},
                  "50": {"NE": 30, "SE": 25, "SW": 15, "NW": 20}},
        "motionDir": 300.0, "motionSpd": 8.0}))

    # Quadrant keys MISSING entirely, not reported as 000. The Python reads
    # these with dict.get(q, 0.0); a JS port that writes snap.radii[thr][q]
    # gets undefined, and undefined propagates into NaN through every
    # arithmetic step without ever raising. Nothing else in this suite
    # exercises that path - every other case supplies all four quadrants.
    cases.append(("synthetic: missing quadrant keys", {
        "lat": 27.5, "lon": -158.0, "vmax": 60.0,
        "radii": {"34": {"NE": 120, "SE": 95},
                  "50": {"NE": 50}},
        "motionDir": 55.0, "motionSpd": 13.0}))

    cases.append(("synthetic: no motion", {
        "lat": 8.0, "lon": 155.0, "vmax": 70.0,
        "radii": {"34": {"NE": 90, "SE": 80, "SW": 70, "NW": 75},
                  "50": {"NE": 45, "SE": 40, "SW": 35, "NW": 38}},
        "motionDir": 0.0, "motionSpd": 0.0}))

    cases.append(("synthetic: dateline centre", {
        "lat": 24.0, "lon": 179.9, "vmax": 115.0,
        "radii": {"34": {"NE": 160, "SE": 140, "SW": 100, "NW": 120},
                  "50": {"NE": 85, "SE": 75, "SW": 55, "NW": 65},
                  "64": {"NE": 50, "SE": 45, "SW": 30, "NW": 35}},
        "motionDir": 350.0, "motionSpd": 16.0}))

    return cases


def to_snapshot(d):
    s = tc.Snapshot()
    s.lat = float(d["lat"])
    s.lon = float(d["lon"])
    s.vmax = float(d["vmax"])
    s.radii = dict((int(k), v) for k, v in d.get("radii", {}).items())
    s.motionDir = d.get("motionDir", 0.0)
    s.motionSpd = d.get("motionSpd", 0.0)
    return s


# ---------------------------------------------------------------------------
# Group 3: the GTCM vortex
# ---------------------------------------------------------------------------

def py_r34_at(snap, fit, az_deg):
    """The modelled 34 kt radius on one bearing, exactly as
    _buildVortexGTCM() derives it (outermost probe still at 34 kt)."""
    probe = np.linspace(1.0, 900.0, 900)
    prof = tc._gtcmProfile(probe, snap.vmax, fit["a"], fit["rm"], fit["ri"],
                           fit["x1"], fit["x2"])
    u, v = tc._gtcmUV(prof, np.full(probe.shape, float(az_deg)),
                      fit["ax"], fit["ay"], snap.lat)
    mag = np.sqrt(u * u + v * v)
    above = mag >= 34.0
    if not above.any():
        return float(np.float32(fit["rm"] * 3.0))
    return float(probe[len(probe) - 1 - int(np.argmax(above[::-1]))])


def gtcm_sample_points(snap):
    """Sample points chosen where two ports actually diverge, not where the
    field is smooth and forgiving.

    Radially, on every azimuth: the centre itself (r = 0); exactly Rmax;
    exactly the fitted rm and ri, which are eq. (3)'s two branch boundaries;
    every reported radius, both as reported and after the 0.85 quadrant-
    average scaling that the fit actually sees; and - the point of the whole
    exercise - exactly ON the modelled R34 and just outside it, where the
    outer taper takes over on a strict `>`.

    Azimuthally: the four quadrant bisectors the radii are reported on, the
    cardinal directions between them, and a tight cluster straddling the
    0/360 seam, where a `%` that keeps its sign (JavaScript's does, Python's
    does not) turns a bearing of 359.99 into -0.01 and moves the point into
    the wrong quadrant.
    """
    fit = tc.fitGTCM(snap)
    rmax = tc.resolveRmax(snap, 0.0)

    reported = sorted({float(v)
                       for q in snap.radii.values()
                       for v in q.values() if v > 0})
    scaled = [r * tc.GTCM_QUAD_AVG_FACTOR for r in reported]

    az_list = [0.0, 0.001, 0.5, 45.0, 89.999, 90.0, 135.0, 180.0, 225.0,
               270.0, 315.0, 359.5, 359.999]

    points, labels = [], []
    for az in az_list:
        r34 = py_r34_at(snap, fit, az)
        radii = ([0.0, rmax, fit["rm"], fit["ri"]]
                 + reported + scaled
                 + [r34, r34 + 0.25, r34 + 5.0, r34 * 1.5, r34 * 3.0])
        for r in radii:
            if r <= 0.0:
                points.append([snap.lat, snap.lon])
            else:
                lat, lon = tc_dest(snap.lat, snap.lon, az, r)
                points.append([lat, lon])
            labels.append("az=%g r=%g" % (az, r))
    return points, labels


def tc_dest(clat, clon, brg_deg, dist_nm):
    """Point at a bearing/distance from a centre. Only used to place sample
    points; both sides then recover r and az from the same lat/lon."""
    d = dist_nm / tc.EARTH_R_NM
    b = math.radians(brg_deg)
    l1, o1 = math.radians(clat), math.radians(clon)
    l2 = math.asin(math.sin(l1) * math.cos(d) +
                   math.cos(l1) * math.sin(d) * math.cos(b))
    o2 = o1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(l1),
                         math.cos(d) - math.sin(l1) * math.sin(l2))
    return math.degrees(l2), (math.degrees(o2) + 540.0) % 360.0 - 180.0


def py_gtcm(snap, points):
    """The reference side of group 3, straight out of TCWind_JTWC.py.

    normalizePeak=False on purpose: the peak-core correction rescales
    relative to the strongest cell of whatever raster it is handed, so
    comparing it here would compare two grid resolutions rather than two
    ports. It is applied by the page that draws the field, not by the model.
    """
    fit = tc.fitGTCM(snap)
    rmax = tc.resolveRmax(snap, 0.0)
    lat = np.array([p[0] for p in points], dtype=np.float64)
    lon = np.array([p[1] for p in points], dtype=np.float64)
    mag, direc, r, r34 = tc._buildVortexGTCM(
        lat, lon, snap, rmax, tc.OUTER_DECAY_FACTOR, False)
    _, az = tc._distBearingGrids(lat, lon, snap.lat, snap.lon)
    return {
        "rmax": rmax,
        "fit": dict((k, jnum(float(v)) if k not in ("n", "rmSource") else v)
                    for k, v in fit.items()),
        "points": [{"lat": points[i][0], "lon": points[i][1],
                    "mag": float(mag[i]), "dir": float(direc[i]),
                    "r": float(r[i]), "r34": float(r34[i]),
                    "az": float(az[i])}
                   for i in range(len(points))],
    }


FIT_TOL = {"rm": RAD_TOL, "ri": RAD_TOL, "x1": EXP_TOL, "x2": EXP_TOL,
           "ax": MAG_TOL, "ay": MAG_TOL, "a": MAG_TOL, "rms": MAG_TOL}


def check_gtcm():
    print("\n=== GTCM vortex: Python _buildVortexGTCM() vs Vortex.html "
          "vortexFieldGTCM() ===")
    print("    tolerances: %.2f kt magnitude, %.2f nm radius, %.2f deg direction"
          % (MAG_TOL, RAD_TOL, DIR_TOL))
    snap_path = os.path.join(SCRATCH, "gtcm_snap.json")
    pts_path = os.path.join(SCRATCH, "gtcm_points.json")

    failed = 0
    worst_all = {"mag": 0.0, "dir": 0.0, "r": 0.0, "r34": 0.0}
    for label, raw in snapshot_cases():
        snap = to_snapshot(raw)
        points, plabels = gtcm_sample_points(snap)

        with open(snap_path, "w") as f:
            json.dump(raw, f)
        with open(pts_path, "w") as f:
            json.dump(points, f)

        py = py_gtcm(snap, points)
        js, why = run(["node", os.path.join(HERE, "tools_js.js"), "gtcm",
                       snap_path, pts_path], allow_unavailable=True)
        if js is None:
            print("SKIP   %s - %s" % (label, why))
            continue

        diffs = []

        if abs(py["rmax"] - js["rmax"]) > RAD_TOL:
            diffs.append("rmax: py=%.6f js=%.6f (diff %.4g nm)"
                         % (py["rmax"], js["rmax"], abs(py["rmax"] - js["rmax"])))

        if py["fit"]["n"] != js["fit"]["n"]:
            diffs.append("fit.n: py=%r js=%r" % (py["fit"]["n"], js["fit"]["n"]))
        if int(py["fit"]["freeParams"]) != int(js["fit"]["freeParams"]):
            diffs.append("fit.freeParams: py=%r js=%r"
                         % (py["fit"]["freeParams"], js["fit"]["freeParams"]))
        if py["fit"]["rmSource"] != js["fit"]["rmSource"]:
            diffs.append("fit.rmSource: py=%r js=%r"
                         % (py["fit"]["rmSource"], js["fit"]["rmSource"]))
        for k, tol in FIT_TOL.items():
            a, b = py["fit"][k], js["fit"][k]
            if a is None or b is None:
                if a != b:
                    diffs.append("fit.%s: py=%r js=%r" % (k, a, b))
                continue
            if abs(a - b) > tol:
                diffs.append("fit.%s: py=%.9g js=%.9g (diff %.4g, tol %.4g)"
                             % (k, a, b, abs(a - b), tol))

        worst = {"mag": 0.0, "dir": 0.0, "r": 0.0, "r34": 0.0}
        for i, (p, j) in enumerate(zip(py["points"], js["points"])):
            # A non-finite result on either side is a failure, not a
            # comparison: jnum() turned it into None, and subtracting None
            # would abort the whole run and read as "no failures" to
            # anything counting FAIL lines.
            nonfinite = [f for f in ("mag", "dir", "r", "r34")
                         if p[f] is None or j[f] is None]
            if nonfinite:
                diffs.append("points[%d] (%s): non-finite %s - py=%r js=%r"
                             % (i, plabels[i], ",".join(nonfinite),
                                {f: p[f] for f in nonfinite},
                                {f: j[f] for f in nonfinite}))
                continue
            checks = (("mag", MAG_TOL, abs(p["mag"] - j["mag"])),
                      ("dir", DIR_TOL, angdiff(p["dir"], j["dir"])),
                      ("r", RAD_TOL, abs(p["r"] - j["r"])),
                      ("r34", RAD_TOL, abs(p["r34"] - j["r34"])))
            for field, tol, d in checks:
                if d > worst[field]:
                    worst[field] = d
                if d > tol:
                    diffs.append("points[%d] (%s) %s: py=%.6f js=%.6f "
                                 "(diff %.4g, tol %.4g)"
                                 % (i, plabels[i], field, p[field], j[field], d, tol))
        for k in worst:
            worst_all[k] = max(worst_all[k], worst[k])

        summary = ("max |dmag|=%.3g kt |ddir|=%.3g deg |dr|=%.3g nm |dr34|=%.3g nm"
                   % (worst["mag"], worst["dir"], worst["r"], worst["r34"]))
        if diffs:
            failed += 1
            print("FAIL   %s (%d points; %s)" % (label, len(points), summary))
            for d in diffs[:20]:
                print("       " + d)
            if len(diffs) > 20:
                print("       ... and %d more" % (len(diffs) - 20))
        else:
            print("PASS   %s (%d points; %s)" % (label, len(points), summary))

    print("    worst across all cases: mag %.3g kt, dir %.3g deg, "
          "r %.3g nm, r34 %.3g nm"
          % (worst_all["mag"], worst_all["dir"], worst_all["r"], worst_all["r34"]))
    return failed


# ---------------------------------------------------------------------------
# Group 4: the retired per-quadrant vortex
# ---------------------------------------------------------------------------

def perquad_sample_points(snap):
    """The original group-4 grid: inside the core, between each pair of
    reported rings, and past the outermost one. Also returns which points
    sit exactly ON a reported ring - by value, not by which factor produced
    them, because these fixtures' rings are round numbers and 0.5x a 40 nm
    ring lands on a real 20 nm ring."""
    lat0, lon0 = snap["lat"], snap["lon"]
    present = sorted({r for q in snap["radii"].values()
                      for r in q.values() if r > 0}, reverse=True)
    rings = present or [40.0]
    test_radii = ([3.0] + [r * f for r in rings for f in (0.5, 1.0, 1.5)]
                  + [max(rings) * 4.0])

    points, on_ring = [], []
    for az in (45, 135, 225, 315):
        for r_nm in test_radii:
            lat, lon = tc_dest(lat0, lon0, az, r_nm)
            points.append([lat, lon])
            on_ring.append(any(abs(r_nm - rr) < 1e-6 for rr in rings))
    return points, on_ring


def diff_points(name, py_points, js_points, on_ring, out):
    if len(py_points) != len(js_points):
        out.append("%s.points: length py=%d js=%d"
                   % (name, len(py_points), len(js_points)))
        return
    for i, (p, j) in enumerate(zip(py_points, js_points)):
        tol = {"mag": BOUNDARY_TOL, "dir": BOUNDARY_TOL} if on_ring[i] else {}
        for field in ("lat", "lon", "mag", "dir", "r", "r34"):
            a, b = p[field], j[field]
            t = tol.get(field, FLOAT_TOL)
            if abs(float(a) - float(b)) > t:
                tag = " (on-ring probe)" if on_ring[i] else ""
                out.append("%s.points[%d].%s: py=%r js=%r (diff %.4g)%s"
                           % (name, i, field, a, b, abs(a - b), tag))


def check_perquad():
    print("\n=== per-quadrant vortex (RETIRED): Python buildVortex"
          "(method='perquad') vs Index.html vortexAt() ===")
    failed = 0
    for fixture in FIXTURES:
        name = os.path.basename(fixture)
        py_parsed, _ = run([sys.executable, os.path.join(HERE, "tools_py.py"),
                            "parse", fixture])
        taus = [t for t in py_parsed["taus"] if t["radii"]] or py_parsed["taus"]
        if not taus:
            continue
        snap = taus[0]
        points, on_ring = perquad_sample_points(snap)

        snap_path = os.path.join(SCRATCH, "perquad_snap.json")
        pts_path = os.path.join(SCRATCH, "perquad_points.json")
        with open(snap_path, "w") as f:
            json.dump(snap, f)
        with open(pts_path, "w") as f:
            json.dump(points, f)

        py, _ = run([sys.executable, os.path.join(HERE, "tools_py.py"),
                     "vortex", snap_path, pts_path])
        js, why = run(["node", os.path.join(HERE, "tools_js.js"), "perquad",
                       snap_path, pts_path], allow_unavailable=True)
        if js is None:
            print("SKIP   %s - %s" % (name, why))
            continue

        diffs = []
        diff_scalar(name + ".rmax", py["rmax"], js["rmax"], diffs)
        diff_points(name, py["points"], js["points"], on_ring, diffs)
        if diffs:
            failed += 1
            print("FAIL   %s (%d sample points)" % (name, len(points)))
            for d in diffs[:20]:
                print("       " + d)
            if len(diffs) > 20:
                print("       ... and %d more" % (len(diffs) - 20))
        else:
            print("PASS   %s (%d sample points)" % (name, len(points)))
    return failed


def main():
    failed = 0
    failed += check_parse("parse", "Code.gs (server)")
    print()
    failed += check_parse("parsev", "Vortex.html (client)")
    failed += check_parse_variants()
    failed += check_gtcm()
    failed += check_perquad()
    print("\n%d check(s) failed" % failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
