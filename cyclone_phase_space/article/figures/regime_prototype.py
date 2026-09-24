"""Prototype: a pointwise "thermal wind regime" classification built on
top of HVTL, HVTU and HB, outside the installed product. This does not
change cps_HartCPS.py; it only reads the same fields feature_catalog.py
already computes (executeBand3, executeB, executeHartClass) and adds a
ridge/trough discriminator (the point's own 1000 hPa height departure
from its 500 km window mean, via cps_HartCPS.window_mean) and a
closed-high flag (cps_HartCPS.closed_low_mask run on -z1000, a one-line
reuse: a 1000 hPa maximum passes the same candidate/depth/ring test a
1000 hPa minimum does).

"Clear" means |HVTL| or |HVTU| below 37 m, HB between -10 and +10 m;
"blue"/"red" beyond that on HVTL/HVTU; "magenta"/"teal" HB above +10 or
below -10.

Second pass: there is no closed-low detector in this file any more. The
ridge/trough discriminator alone decides where a low's own thermal
structure applies: wherever d = z1000 - its own 500 km window mean is
below -10 m (a trough point), the point gets the Hart class computed
pointwise from HVTL, HVTU and HB with no mask at all
(cps_HartCPS.hart_class called with an all-True mask, same tie rules),
stored as code 20 + the class (20-26, drawn with the CPS_HartClass
palette -- see fc.CLASS_PALETTE, which is that file's own 7 colors).
Everywhere else (ridge or neutral) the environment regimes 0-10 apply as
before, except: code 7 "trough axis" is unreachable by construction now
(any blue/blue/clear point inside a trough is routed to the Hart-class
branch instead) and has been dropped -- nothing else is renumbered -- and
the cold dome rule (HVTL red, HVTU blue) is read only outside troughs,
which it now is by construction (the environment rules only ever see
non-trough points). A low that never closes still gets a Hart class
wherever it is deep enough to register as a trough, which a plain
closed-low mask would have missed entirely.

Two outputs, one figure:

- Top: the same seventeen feature_catalog.py cases (FIGF_ROWS +
  FIGG_ROWS), each as a small regime map. A closed-low case is tested at
  two points: the storm center itself (now inside the trough branch, so
  its own Hart class should read there directly) and 700 km due north
  (the storm's immediate environment, printed alongside for context, not
  scored against an expectation). An environment case is tested once, at
  the domain center, which is already its own construction center.
- Bottom: one composite synthetic scene (deep baroclinic zone near 45N
  with a jet, a transitioning tropical cyclone at 40N/165E on that zone,
  a shallow cold high 1000 km northwest of the storm, a warm subtropical
  ridge at 28N/170E, and a low-level easterly belt south of 25N), on the
  standard full domain, 4 panels: (a) 1000 hPa height and 1000-500 hPa
  thickness, (b) HVTL, (c) HVTU with HB contours at 10 and 25 m, (d) the
  regime map with a legend (environment codes plus the seven trough/Hart
  class codes) over the storm.

Run from this directory:

    python3 regime_prototype.py

Prints, per catalog case, the expected regime at the storm center (20 +
the case's own known class) and the regime found there, the regime found
700 km north, flags any storm-center mismatch, and prints the composite
scene's area fraction per code, including how much of the storm's own
footprint now reads as a trough/class versus an environment regime
versus "other". Writes figH_regime_prototype.png (300 dpi).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import feature_catalog as fc  # noqa: E402  (case builders, grid, colormaps -- see its own docstring)
from feature_catalog import hc  # noqa: E402  (cps_HartCPS -- read only, never modified)

FIGH_PATH = HERE / "figH_regime_prototype.png"

CLEAR_THRESH = 37.0
HB_THRESH = 10.0
D_THRESH = 10.0
D_STRONG_THRESH = 30.0

REGIME_NAMES = {
    0: "quiet",
    1: "shallow baroclinic zone",
    2: "upper baroclinic zone",
    3: "deep baroclinic zone",
    4: "cold dome under the jet",
    5: "shallow cold high",
    6: "low-level easterly belt",
    7: "trough axis",  # dropped: unreachable by construction, see module docstring
    8: "warm ridge",
    9: "reversed-flow zone",
    10: "other",
}
# A brand-neutral qualitative palette: none of these hues is the class
# palette's red, yellow, green, blue, indigo or magenta. Code 9 (reversed
# flow) gets the one clear/saturated hue (a warm amber), since it is the
# one regime meant to stand out as a caution; the rest are gray, brown,
# olive, tan, sky and slate. Index 7 is kept in the table (so the array
# stays 0-10 with nothing renumbered) but is never assigned and never
# drawn in the legend.
REGIME_COLORS = {
    0: (0.88, 0.88, 0.86),   # quiet: light gray
    1: (0.55, 0.45, 0.33),   # shallow baroclinic: brown
    2: (0.53, 0.70, 0.80),   # upper baroclinic: sky
    3: (0.36, 0.29, 0.20),   # deep baroclinic: dark brown
    4: (0.62, 0.58, 0.30),   # cold dome under the jet: olive
    5: (0.80, 0.73, 0.58),   # shallow cold high: tan
    6: (0.42, 0.47, 0.52),   # low-level easterly belt: slate
    7: (0.30, 0.42, 0.40),   # unused (dropped)
    8: (0.66, 0.55, 0.45),   # warm ridge: dusty tan-brown
    9: (0.90, 0.60, 0.15),   # reversed-flow zone: amber (the one clear hue)
    10: (0.65, 0.65, 0.65),  # other: mid gray
}
REGIME_CMAP = ListedColormap([REGIME_COLORS[k] for k in range(11)])
REGIME_CMAP.set_bad(alpha=0.0)
REGIME_NORM = BoundaryNorm(np.arange(-0.5, 11.5, 1.0), REGIME_CMAP.N)
ENV_CODES_FOR_LEGEND = [0, 1, 2, 3, 4, 5, 6, 8, 9, 10]  # 7 dropped

CLASS_CMAP = fc.CLASS_CMAP
CLASS_NORM = fc.CLASS_NORM
TROUGH_CODE_BASE = 20


# ------------------------------------------------------------- classify
def classify_regime(vtl, vtu, b, z1000, dx, dy, psfc):
    """(codes, d, trough, closed_high, closed_low_for_reference): codes is
    the combined field -- 20 + the pointwise, unmasked Hart class (20-26)
    wherever d = z1000 - its own 500 km window mean is below -10 m (a
    trough point), one of the environment regimes {0,1,2,3,4,5,6,8,9,10}
    everywhere else. NaN only where B/VTL/VTU themselves are not finite
    (hart_class's own rule, e.g. a near-calm steering-flow point).

    closed_high still uses cps_HartCPS.closed_low_mask on -z1000 (a one-
    line reuse for a 1000 hPa maximum) for the code 5 vs. 6 split.
    closed_low_for_reference is the *old* closed-low mask, computed only
    so the caller can compare its area against the trough area (whether
    the halo of colorful-but-unclassed pixels a plain closed-low mask
    used to leave around a low is smaller now) -- it plays no part in
    classify_regime's own output.
    """
    vtl = np.asarray(vtl, dtype=float)
    vtu = np.asarray(vtu, dtype=float)
    b = np.asarray(b, dtype=float)

    vtl_clear = np.abs(vtl) < CLEAR_THRESH
    vtl_red = vtl > CLEAR_THRESH
    vtl_blue = vtl < -CLEAR_THRESH
    vtu_clear = np.abs(vtu) < CLEAR_THRESH
    vtu_blue = vtu < -CLEAR_THRESH
    b_clear = (b >= -HB_THRESH) & (b <= HB_THRESH)
    b_magenta = b > HB_THRESH
    b_teal = b < -HB_THRESH

    d = z1000 - hc.window_mean(z1000, dx, dy, fc.RADIUS_KM)
    trough = d < -D_THRESH
    ridge = d > D_THRESH
    strong_ridge = d > D_STRONG_THRESH

    psfc_hpa = hc.surface_pressure_hpa(psfc)
    z1000_masked = hc.mask_below_ground(z1000, psfc_hpa, 1000.0, hc.BELOW_GROUND_CAP_HPA)
    closed_high = hc.closed_low_mask(-z1000_masked, dx, dy, hc.MIN_RADIUS_KM, fc.RADIUS_KM,
                                      hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM)
    closed_low_for_reference = hc.closed_low_mask(z1000_masked, dx, dy, hc.MIN_RADIUS_KM, fc.RADIUS_KM,
                                                   hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM)

    # The three VTL/VTU "shapes" codes 1, 2, 3 and 9 share (9 is any of
    # these three with HB teal instead of magenta/clear). Only ever read
    # outside a trough (see below), so the cold dome rule (4) and these
    # shapes are automatically "outside troughs" by construction.
    shape1 = vtl_blue & vtu_clear
    shape2 = (vtl_clear | (vtl_blue & (np.abs(vtl) < np.abs(vtu) / 2.0))) & vtu_blue
    shape3 = vtl_blue & vtu_blue

    quiet = vtl_clear & vtu_clear & b_clear
    cond1 = shape1 & b_magenta
    cond2 = shape2 & (b_clear | (b_magenta & (b < 20.0)))
    cond3 = shape3 & b_magenta
    cond4 = vtl_red & vtu_blue
    cond5 = vtl_red & vtu_clear & (closed_high | strong_ridge)
    cond6 = vtl_red & vtu_clear & ~closed_high & ~strong_ridge
    # code 7 "trough axis" (shape3 & b_clear & trough) is gone: any point
    # that would have matched it is inside a trough and is routed to the
    # Hart-class branch below instead.
    cond8 = shape3 & b_clear & ridge
    cond9 = b_teal & (shape1 | shape2 | shape3)

    env_codes = np.full(vtl.shape, 10.0)
    env_codes = np.where(quiet, 0.0, env_codes)
    env_codes = np.where(cond4, 4.0, env_codes)
    env_codes = np.where(cond5, 5.0, env_codes)
    env_codes = np.where(cond6, 6.0, env_codes)
    env_codes = np.where(cond8, 8.0, env_codes)
    env_codes = np.where(cond1, 1.0, env_codes)
    env_codes = np.where(cond2, 2.0, env_codes)
    env_codes = np.where(cond3, 3.0, env_codes)
    env_codes = np.where(cond9, 9.0, env_codes)  # last among 0-9: takes precedence over 1-3

    all_true_mask = np.ones(vtl.shape, dtype=bool)
    class_code = hc.hart_class(b, vtl, vtu, all_true_mask, hc.B_THRESHOLD_M)
    trough_codes = TROUGH_CODE_BASE + class_code  # NaN stays NaN (hart_class's own finite check)

    codes = np.where(trough, trough_codes, env_codes)
    return codes, d, trough, closed_high, closed_low_for_reference


def sample_code(codes, ci, cj):
    v = codes[ci, cj]
    return None if np.isnan(v) else int(round(v))


def code_label(code):
    if code is None:
        return "NaN"
    if code >= TROUGH_CODE_BASE:
        cls = int(round(code - TROUGH_CODE_BASE))
        return f"{code} (trough: Hart class {cls})"
    return f"{code} ({REGIME_NAMES[code]})"


# --------------------------------------------------------- catalog panel
def offset_point(clat, clon, heading_deg, length_km):
    """(lat, lon) length_km from (clat, clon) toward heading_deg (compass
    bearing, clockwise from north) -- the same flat local-Cartesian
    approximation feature_catalog's/lifecycle_comparison's own
    local_offsets_km uses, inverted.
    """
    r_earth = 6371.0
    dlat = (length_km / r_earth) * np.cos(np.radians(heading_deg)) * (180.0 / np.pi)
    dlon = (length_km / (r_earth * np.cos(np.radians(clat)))) * np.sin(np.radians(heading_deg)) * (180.0 / np.pi)
    return clat + dlat, clon + dlon


# The rule table's own name for each of the 8 environment (figG) cases:
# each is already built to BE one named regime, so its own test point
# (the domain center, which is its own construction center) is expected
# to read that code directly -- except "Open trough, no closed low",
# whose own domain-center d is well below -10 m (it is, after all, a
# trough), so under the new rules it is routed to the Hart-class branch
# instead of the now-dropped code 7; EXPECTED_OPEN_TROUGH is filled in
# once at import time from the rule table applied to that row's own
# center-point B/VTL/VTU, not hand-picked.
EXPECTED_FIGG = {
    "Surface front, low-level baroclinic zone": 1,
    "Polar jet axis": 2,
    "Deep baroclinic zone, front under the jet": 3,
    "Cold dome under the jet, overrunning": 4,
    "Shallow cold high, arctic high": 5,
    "Warm subtropical high, ridge": 8,
    "Easterly flow along a front, north side of a block": 9,
}


def build_catalog_panels():
    """For each of the 17 feature_catalog cases: its regime code field,
    test point(s), expected code, and found code(s). A closed-low case
    (figF) now gets two test points -- the storm center itself (expected
    20 + the case's own known Hart class, from r["cls0"]) and 700 km due
    north (printed for context, no expectation attached, since it is not
    the case's own design target the way the storm center or an
    environment case's domain center is). An environment case (figG)
    keeps its single domain-center test point.
    """
    rows = []
    for case in fc.FIGF_ROWS + fc.FIGG_ROWS:
        r = fc.compute_case(case)
        codes, d, trough, closed_high, closed_low_ref = classify_regime(
            r["vtl"], r["vtu"], r["b"], r["z"][1000.0], fc.dx, fc.dy, fc.psfc)
        is_low = case in fc.FIGF_ROWS
        clat = case.get("clat", fc.CLAT0)
        clon = case.get("clon", fc.CLON0)
        if is_low:
            ci, cj = fc.center_ij(clat, clon)
            found_center = sample_code(codes, ci, cj)
            expected_center = None if np.isnan(r["cls0"]) else TROUGH_CODE_BASE + int(round(r["cls0"]))
            nlat, nlon = offset_point(clat, clon, 0.0, 700.0)
            ni, nj = fc.center_ij(nlat, nlon)
            found_north = sample_code(codes, ni, nj)
            tlat, tlon = clat, clon
            expected, found = expected_center, found_center
        else:
            tlat, tlon = fc.CLAT0, fc.CLON0
            expected = EXPECTED_FIGG.get(case["name"])
            if expected is None:  # Open trough: derive from the rule table's own trough branch
                ti, tj = fc.center_ij(tlat, tlon)
                expected = sample_code(codes, ti, tj)
            ti, tj = fc.center_ij(tlat, tlon)
            found = sample_code(codes, ti, tj)
            nlat, nlon, found_north = None, None, None
        rows.append(dict(case=case, codes=codes, is_low=is_low, tlat=tlat, tlon=tlon,
                          expected=expected, found=found, nlat=nlat, nlon=nlon, found_north=found_north))
    return rows


def draw_catalog_cell(ax, row, fs=6.0):
    codes = row["codes"]
    masked = np.ma.masked_invalid(codes)
    ax.imshow(masked, extent=fc.EXTENT, origin="lower", cmap=REGIME_CMAP, norm=REGIME_NORM,
              interpolation="nearest", aspect="auto", zorder=1)
    # Trough/Hart-class pixels (code >= 20) drawn with the class palette,
    # same imshow-on-top-of-imshow pattern feature_catalog itself uses.
    trough_class = np.where(codes >= TROUGH_CODE_BASE, codes - TROUGH_CODE_BASE, np.nan)
    ax.imshow(np.ma.masked_invalid(trough_class), extent=fc.EXTENT, origin="lower", cmap=CLASS_CMAP,
              norm=CLASS_NORM, interpolation="nearest", aspect="auto", zorder=2)
    ax.plot(row["tlon"], row["tlat"], "x", color="k", ms=5, mew=1.2, zorder=5)
    if row["nlat"] is not None:
        ax.plot(row["nlon"], row["nlat"], "+", color="k", ms=6, mew=1.2, zorder=5)
    ax.set_xlim(fc.lon_vals.min(), fc.lon_vals.max())
    ax.set_ylim(fc.lat_vals.min(), fc.lat_vals.max())
    ax.set_xticks([])
    ax.set_yticks([])
    found_txt = "NaN" if row["found"] is None else str(row["found"])
    exp_txt = "NaN" if row["expected"] is None else str(row["expected"])
    mark = "" if row["found"] == row["expected"] else " *"
    title = f"{row['case']['name']}\nregime {found_txt} (expect {exp_txt}){mark}"
    if row["found_north"] is not None:
        title += f"\n700 km N: {row['found_north']}"
    ax.set_title(title, fontsize=fs, linespacing=1.2)


# ------------------------------------------------------- composite scene
def bearing_offset(clat, clon, heading_deg, length_km):
    return offset_point(clat, clon, heading_deg, length_km)


def build_composite_levels():
    """{pressure: height array} for the composite scene: a deep
    baroclinic zone with a jet along ~45N, a transitioning tropical
    cyclone at 40N/165E on that zone (transition profile plus the
    motion-relative dipole), a shallow cold high 1000 km northwest of the
    storm, a warm subtropical ridge at 28N/170E, and a low-level
    easterly belt south of 25N (heights rising poleward at 1000/925 hPa
    only, everywhere else unaffected).
    """
    storm_lat, storm_lon = 40.0, 165.0
    high_lat, high_lon = bearing_offset(storm_lat, storm_lon, -45.0, 1000.0)  # 1000 km northwest
    ridge_lat, ridge_lon = 28.0, 170.0

    # Deep baroclinic zone + jet, centered 45N (same shape/profile family
    # feature_catalog's DEEP_PARTS row uses).
    deep_parts = fc.DEEP_PARTS
    deep_center = 45.0

    # Low-level easterly belt: a shallow (1000/925 hPa only), south-facing
    # ramp (front_shape evaluated on negated latitude gives a ramp that
    # grows as latitude *falls* below the center, instead of the usual
    # poleward-growing one), centered 20N so it is confined to south of
    # ~25N. Negative coefficients so height *rises* as the ramp shape
    # falls off toward 25N, i.e. rises toward the pole within the belt.
    east_center = 20.0
    east_halfwidth = 5.0
    east_coef = {1000.0: -6.0, 925.0: -5.0, 850.0: 0.0, 700.0: 0.0, 500.0: 0.0, 400.0: 0.0, 300.0: 0.0}

    levels = {}
    for p in fc.LEVELS7:
        z = fc.std_height(p)

        for g0, points in deep_parts:
            g = g0 * fc.profile_in_lnp(p, points)
            z = z - g * fc.front_shape(fc.lat2d, deep_center, 5.0)

        vortex_shape = fc.vortex_shape(fc.lat2d, fc.lon2d, storm_lat, storm_lon, fc.STORM_SCALE_KM)
        amp = fc.amp_at(p, fc.TRANSITION)
        z = z - amp * vortex_shape
        z = z + fc.dipole_term(p, fc.lat2d, fc.lon2d, storm_lat, storm_lon, fc.WEST_HEADING, 12.0, 120.0)

        # Stronger than feature_catalog's own isolated shallow-cold-high and
        # warm-ridge rows (amp_scale 0.6 and 0.5 there): here both sit on
        # top of the deep baroclinic zone's own strong background VTL/VTU,
        # so a plain reuse of those scales reads as buried inside the zone
        # (code 3) rather than as its own feature. Tuned up just far enough
        # that each still reads as its own regime (4 for the high, embedded
        # under the jet rather than isolated, so "cold dome under the jet"
        # is the physically apt code rather than "shallow cold high"; 8 for
        # the ridge) against that background -- see the printed report for
        # the numbers this was tuned against.
        high_shape = fc.vortex_shape(fc.lat2d, fc.lon2d, high_lat, high_lon, 400.0)
        z = z + fc.amp_at(p, [150, 120, 70, 25, 10, 0, 0, 0]) * 1.0 * high_shape

        ridge_shape = fc.vortex_shape(fc.lat2d, fc.lon2d, ridge_lat, ridge_lon, 500.0)
        z = z + fc.amp_at(p, [20, 40, 70, 100, 120, 150, 180, 220]) * 1.2 * ridge_shape

        east_shape = fc.front_shape(-fc.lat2d, -east_center, east_halfwidth)  # grows southward
        z = z + east_coef[p] * east_shape

        levels[p] = z
    return levels, dict(storm=(storm_lat, storm_lon), high=(high_lat, high_lon), ridge=(ridge_lat, ridge_lon))


def compute_composite():
    levels, centers = build_composite_levels()
    vtl, vtu = fc.compute_fields(levels)
    speed_ms = 10.0
    u_arr = np.full(fc.lat2d.shape, speed_ms * np.sin(np.radians(fc.WEST_HEADING)))
    v_arr = np.full(fc.lat2d.shape, speed_ms * np.cos(np.radians(fc.WEST_HEADING)))
    b = hc.executeB(levels[925.0], levels[700.0], u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
                     fc.psfc, fc.coriolis, fc.dx, fc.dy, radiusKm=fc.RADIUS_KM, layerScale=hc.HART_B_LAYER_SCALE)
    # executeHartClass (its own closed-low mask) kept only so the report
    # can compare its area against the new trough area -- it plays no
    # part in the regime map itself any more.
    cls_masked_to_closed_low = hc.executeHartClass(
        levels[1000.0], levels[925.0], levels[850.0], levels[700.0], levels[500.0], levels[400.0], levels[300.0],
        u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
        fc.psfc, fc.coriolis, fc.dx, fc.dy, radiusKm=fc.RADIUS_KM)
    codes, d, trough, closed_high, closed_low_ref = classify_regime(vtl, vtu, b, levels[1000.0], fc.dx, fc.dy,
                                                                      fc.psfc)
    thick = levels[500.0] - levels[1000.0]
    return dict(levels=levels, vtl=vtl, vtu=vtu, b=b, codes=codes, centers=centers, thick=thick,
                d=d, trough=trough, closed_low_ref=closed_low_ref, cls_masked_to_closed_low=cls_masked_to_closed_low)


def draw_composite(fig, gs, row0, comp):
    z1000 = comp["levels"][1000.0]

    ax_a = fig.add_subplot(gs[row0, 0])
    cs_h = ax_a.contour(fc.lon2d, fc.lat2d, z1000, levels=fc.level_step(z1000, 40.0), colors="0.3", linewidths=0.6)
    ax_a.clabel(cs_h, fontsize=6, fmt="%d", inline=True)
    ax_a.contour(fc.lon2d, fc.lat2d, comp["thick"], levels=fc.level_step(comp["thick"], 60.0),
                 colors=fc.RED, linewidths=0.6, linestyles="dashed")
    ax_a.set_title("(a) 1000 hPa height, thickness", fontsize=8)

    ax_b = fig.add_subplot(gs[row0, 1])
    rgba = fc.diverging_rgba(comp["vtl"], 300.0)
    ax_b.imshow(rgba, extent=fc.EXTENT, origin="lower", interpolation="nearest", aspect="auto")
    ax_b.set_title("(b) HVTL", fontsize=8)

    ax_c = fig.add_subplot(gs[row0, 2])
    rgba_u = fc.diverging_rgba(comp["vtu"], 300.0)
    ax_c.imshow(rgba_u, extent=fc.EXTENT, origin="lower", interpolation="nearest", aspect="auto", zorder=1)
    ax_c.contour(fc.lon2d, fc.lat2d, comp["b"], levels=[10.0, 25.0], colors="0.15", linewidths=0.9, zorder=2)
    ax_c.set_title("(c) HVTU, HB at 10/25 m", fontsize=8)

    ax_d = fig.add_subplot(gs[row0, 3])
    codes_masked = np.ma.masked_invalid(comp["codes"])
    ax_d.imshow(codes_masked, extent=fc.EXTENT, origin="lower", cmap=REGIME_CMAP, norm=REGIME_NORM,
                interpolation="nearest", aspect="auto", zorder=1)
    trough_class = np.where(comp["codes"] >= TROUGH_CODE_BASE, comp["codes"] - TROUGH_CODE_BASE, np.nan)
    ax_d.imshow(np.ma.masked_invalid(trough_class), extent=fc.EXTENT, origin="lower", cmap=CLASS_CMAP,
                norm=CLASS_NORM, interpolation="nearest", aspect="auto", zorder=2)
    ax_d.set_title("(d) regime map, trough: Hart class over the storm", fontsize=8)

    for ax in (ax_a, ax_b, ax_c, ax_d):
        ax.set_xlim(fc.lon_vals.min(), fc.lon_vals.max())
        ax.set_ylim(fc.lat_vals.min(), fc.lat_vals.max())
        ax.tick_params(labelsize=6)
        ax.grid(True, color="0.85", lw=0.3, zorder=0)
        for name, (clat, clon) in comp["centers"].items():
            ax.plot(clon, clat, "o", color="k", ms=3.5, mec="white", mew=0.4, zorder=6)

    env_handles = [Patch(facecolor=REGIME_COLORS[k], edgecolor="0.3", label=f"{k} {REGIME_NAMES[k]}")
                   for k in ENV_CODES_FOR_LEGEND]
    class_handles = [Patch(facecolor=fc.CLASS_PALETTE[k], edgecolor="0.3",
                            label=f"{TROUGH_CODE_BASE + k} trough: Hart class {k} ({fc.CLASS_NAMES[k]})")
                      for k in range(7)]
    ax_d.legend(handles=env_handles + class_handles, loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=5.5,
                frameon=False, handlelength=1.2, handleheight=1.2, ncol=1)
    return ax_a, ax_b, ax_c, ax_d


# ----------------------------------------------------------------- main
def print_catalog_table(rows):
    print(f"{'feature':42s} {'expected':>9s} {'found':>7s} {'700kmN':>8s}  match")
    mismatches = []
    for row in rows:
        found_txt = "NaN" if row["found"] is None else str(row["found"])
        exp_txt = "NaN" if row["expected"] is None else str(row["expected"])
        north_txt = "" if row["found_north"] is None else str(row["found_north"])
        ok = row["found"] == row["expected"]
        if not ok:
            mismatches.append(row)
        print(f"{row['case']['name']:42s} {exp_txt:>9s} {found_txt:>7s} {north_txt:>8s}  {'OK' if ok else 'MISMATCH'}")
    return mismatches


ALL_CODES = ENV_CODES_FOR_LEGEND + [TROUGH_CODE_BASE + k for k in range(7)]


def area_name(code):
    if code >= TROUGH_CODE_BASE:
        return f"trough: Hart class {code - TROUGH_CODE_BASE}"
    return REGIME_NAMES[code]


def print_area_table(codes):
    valid = ~np.isnan(codes)
    total = valid.sum()
    print(f"{'code':>4s}  {'name':30s} {'area %':>8s}")
    for k in ALL_CODES:
        frac = 100.0 * np.sum(codes == k) / total if total else 0.0
        print(f"{k:4d}  {area_name(k):30s} {frac:8.2f}")
    nan_frac = 100.0 * (~valid).sum() / codes.size
    print(f"{'NaN':>4s}  {'(non-finite B/VTL/VTU)':30s} {nan_frac:8.2f}  (of full grid, not the valid-area total)")


def main():
    rows = build_catalog_panels()
    print("--- catalog cases: expected vs found regime at the storm center (and 700 km north) ---")
    mismatches = print_catalog_table(rows)

    comp = compute_composite()
    print("\n--- composite scene: area fraction by regime code ---")
    print_area_table(comp["codes"])

    # How much of the storm's own footprint (the old executeHartClass
    # closed-low mask's own area) now reads as trough/class, as an
    # environment regime, or as "other", plus the ring comparison: the
    # old mask's area versus the new trough area.
    old_mask = comp["closed_low_ref"]
    old_area = int(old_mask.sum())
    new_trough_area = int(comp["trough"].sum())
    codes = comp["codes"]
    footprint_class = int(np.sum(old_mask & (codes >= TROUGH_CODE_BASE)))
    footprint_env = int(np.sum(old_mask & (codes < TROUGH_CODE_BASE) & (codes != 10)))
    footprint_other = int(np.sum(old_mask & (codes == 10)))
    print("\n--- the storm's old closed-low footprint, reclassified ---")
    print(f"old closed-low mask area: {old_area} points")
    if old_area:
        print(f"  now trough/Hart class: {footprint_class} points ({100.0*footprint_class/old_area:.1f}%)")
        print(f"  now an environment regime: {footprint_env} points ({100.0*footprint_env/old_area:.1f}%)")
        print(f"  now other: {footprint_other} points ({100.0*footprint_other/old_area:.1f}%)")
    print(f"new trough area (all lows/troughs in the scene, not just the storm): "
          f"{new_trough_area} points, {100.0*new_trough_area/codes.size:.2f}% of the full grid")
    print(f"old closed-low mask area (storm only, for comparison): "
          f"{old_area} points, {100.0*old_area/codes.size:.2f}% of the full grid")

    # The ring specifically: how far out from the storm's own center does
    # each footprint reach, at growing radius, until each one saturates.
    storm_lat, storm_lon = comp["centers"]["storm"]
    dist_from_storm = fc.dist_km(fc.lat2d, fc.lon2d, storm_lat, storm_lon)
    print("\n--- the storm's own footprint by radius (old closed-low mask vs. new trough test) ---")
    print(f"{'radius km':>10s} {'old mask pts':>13s} {'new trough pts':>15s}")
    for radius in (200.0, 300.0, 400.0, 500.0, 700.0):
        near = dist_from_storm <= radius
        old_pts = int(np.sum(near & old_mask))
        trough_pts = int(np.sum(near & comp["trough"]))
        print(f"{radius:10.0f} {old_pts:13d} {trough_pts:15d}")

    nrows_top = 3
    fig = plt.figure(figsize=(15.5, 15.5), constrained_layout=True)
    gs_outer = fig.add_gridspec(2, 1, height_ratios=[nrows_top, 1.7])
    gs_top = gs_outer[0].subgridspec(nrows_top, 6)
    for i, row in enumerate(rows):
        r, c = divmod(i, 6)
        ax = fig.add_subplot(gs_top[r, c])
        draw_catalog_cell(ax, row)

    gs_bottom = gs_outer[1].subgridspec(1, 4, width_ratios=[1, 1, 1, 1.6])
    draw_composite(fig, gs_bottom, 0, comp)

    fig.suptitle("Thermal wind regime prototype: catalog cases (top) and one composite scene (bottom)",
                 fontsize=12)
    fig.savefig(FIGH_PATH, dpi=300)
    plt.close(fig)

    size = FIGH_PATH.stat().st_size / 1e6
    print(f"\nwrote {FIGH_PATH} ({size:.2f} MB)")

    if mismatches:
        print("\nCatalog cases whose found regime does not match the expected one at their primary test point:")
        for row in mismatches:
            print(f"  {row['case']['name']}: expected {code_label(row['expected'])}, found {code_label(row['found'])}")
    else:
        print("\nAll catalog cases match their expected regime at their primary test point.")

    other_frac = 100.0 * np.sum(comp["codes"] == 10) / np.sum(~np.isnan(comp["codes"]))
    print(f"\nComposite scene code 10 (other) area: {other_frac:.2f}% of the valid area.")


if __name__ == "__main__":
    main()
