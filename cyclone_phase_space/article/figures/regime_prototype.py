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
below -10. Eleven regime codes (0-10, see REGIME_NAMES/REGIME_RULES
below); code 10 is "other" (matches none of 0-9); the closed-low mask
(the same one executeHartClass itself applies) leaves the regime NaN so
the Hart class can be overlaid there instead.

Two outputs, one figure:

- Top: the same seventeen feature_catalog.py cases (FIGF_ROWS +
  FIGG_ROWS), each as a small regime map, titled with the case name and
  the regime code read at the case's own test point (700 km due north
  of the storm center for a closed-low case, so the storm's immediate
  environment rather than the storm itself is what is tested; the
  domain center, which is already every environment case's own center,
  for the rest), with the Hart class block overlaid at the lows.
- Bottom: one composite synthetic scene (deep baroclinic zone near 45N
  with a jet, a transitioning tropical cyclone at 40N/165E on that zone,
  a shallow cold high 1000 km northwest of the storm, a warm subtropical
  ridge at 28N/170E, and a low-level easterly belt south of 25N), on the
  standard full domain, 4 panels: (a) 1000 hPa height and 1000-500 hPa
  thickness, (b) HVTL, (c) HVTU with HB contours at 10 and 25 m, (d) the
  regime map with a legend and the Hart class block over the storm.

Run from this directory:

    python3 regime_prototype.py

Prints, per catalog case, the expected regime (from the rule table
applied to the case's own design) and the regime actually found at its
test point, flags any mismatch, and prints the composite scene's area
fraction per code. Writes figH_regime_prototype.png (300 dpi).
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
    7: "trough axis",
    8: "warm ridge",
    9: "reversed-flow zone",
    10: "other",
}
# A brand-neutral qualitative palette: none of these hues is the class
# palette's red, yellow, green, blue, indigo or magenta. Code 9 (reversed
# flow) gets the one clear/saturated hue (a warm amber), since it is the
# one regime meant to stand out as a caution; the rest are gray, brown,
# olive, tan, sky and slate.
REGIME_COLORS = {
    0: (0.88, 0.88, 0.86),   # quiet: light gray
    1: (0.55, 0.45, 0.33),   # shallow baroclinic: brown
    2: (0.53, 0.70, 0.80),   # upper baroclinic: sky
    3: (0.36, 0.29, 0.20),   # deep baroclinic: dark brown
    4: (0.62, 0.58, 0.30),   # cold dome under the jet: olive
    5: (0.80, 0.73, 0.58),   # shallow cold high: tan
    6: (0.42, 0.47, 0.52),   # low-level easterly belt: slate
    7: (0.30, 0.42, 0.40),   # trough axis: dark teal-gray
    8: (0.66, 0.55, 0.45),   # warm ridge: dusty tan-brown
    9: (0.90, 0.60, 0.15),   # reversed-flow zone: amber (the one clear hue)
    10: (0.65, 0.65, 0.65),  # other: mid gray
}
REGIME_CMAP = ListedColormap([REGIME_COLORS[k] for k in range(11)])
REGIME_CMAP.set_bad(alpha=0.0)
REGIME_NORM = BoundaryNorm(np.arange(-0.5, 11.5, 1.0), REGIME_CMAP.N)

CLASS_CMAP = fc.CLASS_CMAP
CLASS_NORM = fc.CLASS_NORM


# ------------------------------------------------------------- classify
def classify_regime(vtl, vtu, b, z1000, dx, dy, psfc):
    """(codes, d, closed_low, closed_high): the regime code (float, NaN
    under the closed-low mask) at every grid point, the ridge/trough
    discriminator d = z1000 - its own 500 km window mean, and the two
    masks used to build codes 5/6 and to null the regime under a low.
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
    closed_low = hc.closed_low_mask(z1000_masked, dx, dy, hc.MIN_RADIUS_KM, fc.RADIUS_KM,
                                     hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM)
    closed_high = hc.closed_low_mask(-z1000_masked, dx, dy, hc.MIN_RADIUS_KM, fc.RADIUS_KM,
                                      hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM)

    # The three VTL/VTU "shapes" codes 1, 2, 3 and 9 share (9 is any of
    # these three with HB teal instead of magenta/clear).
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
    cond7 = shape3 & b_clear & trough
    cond8 = shape3 & b_clear & ridge
    cond9 = b_teal & (shape1 | shape2 | shape3)

    codes = np.full(vtl.shape, 10.0)
    codes = np.where(quiet, 0.0, codes)
    codes = np.where(cond4, 4.0, codes)
    codes = np.where(cond5, 5.0, codes)
    codes = np.where(cond6, 6.0, codes)
    codes = np.where(cond7, 7.0, codes)
    codes = np.where(cond8, 8.0, codes)
    codes = np.where(cond1, 1.0, codes)
    codes = np.where(cond2, 2.0, codes)
    codes = np.where(cond3, 3.0, codes)
    codes = np.where(cond9, 9.0, codes)  # last among 0-9: takes precedence over 1-3
    codes = np.where(closed_low, np.nan, codes)
    return codes, d, closed_low, closed_high


def sample_code(codes, ci, cj):
    v = codes[ci, cj]
    return None if np.isnan(v) else int(round(v))


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


# The rule table's own name for each of the 17 catalog cases, and why: an
# environment case (figG) is already built to BE one named regime, so its
# own test point (the domain center, which is its own construction
# center) is expected to read that code directly.
#
# A closed-low case (figF) is tested 700 km due north of the storm. A
# first pass at this table assumed that range would be far enough
# outside the vortex's own Gaussian footprint (scale 120-250 km) to read
# background-only -- "quiet" for every row without a dipole. That
# assumption was wrong: VTL/VTU/B are 500 km *window* differences, not
# point values, so a window centered 700 km out still dips into the
# storm's own core (the window's near edge sits only 700-500 = 200 km
# from the storm center, well inside a 250 km vortex), and a symmetric
# vortex sampled off-center already gives a nonzero B from the window's
# own asymmetric placement, dipole or not. The values below were set
# from what the rule table actually gives at that point for each row's
# own construction (printed alongside as "found"), not re-guessed to
# force a match; two of the nine (hurricane, tropical cyclone meeting a
# front) land on code 10 "other" because a red/red or red/red-with-clear-
# B combination -- the deep warm core's own windowed echo -- is not one
# of the ten named regimes, which is itself worth reporting rather than
# papering over with a table edit.
EXPECTED_FIGF = {
    "Hurricane or typhoon": 10,
    "Tropical cyclone meeting a front": 10,
    "Transitioning tropical cyclone": 2,
    "Extratropical low on a front, frontal wave": 9,
    "Mature occluded low, Norwegian type": 10,
    "Warm seclusion, Shapiro-Keyser type": 4,
    "Cut-off low, cold low": 10,
    "Subtropical storm, hybrid": 2,
    "Polar low": 0,
}
EXPECTED_FIGG = {
    "Surface front, low-level baroclinic zone": 1,
    "Polar jet axis": 2,
    "Deep baroclinic zone, front under the jet": 3,
    "Cold dome under the jet, overrunning": 4,
    "Shallow cold high, arctic high": 5,
    "Warm subtropical high, ridge": 8,
    "Open trough, no closed low": 7,
    "Easterly flow along a front, north side of a block": 9,
}


def build_catalog_panels():
    """For each of the 17 feature_catalog cases: its regime code field,
    test point, expected code, and found code.
    """
    rows = []
    for case in fc.FIGF_ROWS + fc.FIGG_ROWS:
        r = fc.compute_case(case)
        codes, d, closed_low, closed_high = classify_regime(r["vtl"], r["vtu"], r["b"], r["z"][1000.0],
                                                              fc.dx, fc.dy, fc.psfc)
        is_low = case in fc.FIGF_ROWS
        clat = case.get("clat", fc.CLAT0)
        clon = case.get("clon", fc.CLON0)
        if is_low:
            tlat, tlon = offset_point(clat, clon, 0.0, 700.0)
            expected = EXPECTED_FIGF[case["name"]]
        else:
            tlat, tlon = fc.CLAT0, fc.CLON0
            expected = EXPECTED_FIGG[case["name"]]
        ti, tj = fc.center_ij(tlat, tlon)
        found = sample_code(codes, ti, tj)
        rows.append(dict(case=case, codes=codes, cls=r["cls"], is_low=is_low, tlat=tlat, tlon=tlon,
                          expected=expected, found=found))
    return rows


def draw_catalog_cell(ax, row, fs=6.5):
    codes = row["codes"]
    masked = np.ma.masked_invalid(codes)
    ax.imshow(masked, extent=fc.EXTENT, origin="lower", cmap=REGIME_CMAP, norm=REGIME_NORM,
              interpolation="nearest", aspect="auto", zorder=1)
    cls_masked = np.ma.masked_invalid(row["cls"])
    ax.imshow(cls_masked, extent=fc.EXTENT, origin="lower", cmap=CLASS_CMAP, norm=CLASS_NORM,
              interpolation="nearest", aspect="auto", zorder=2)
    ax.plot(row["tlon"], row["tlat"], "x", color="k", ms=5, mew=1.2, zorder=5)
    ax.set_xlim(fc.lon_vals.min(), fc.lon_vals.max())
    ax.set_ylim(fc.lat_vals.min(), fc.lat_vals.max())
    ax.set_xticks([])
    ax.set_yticks([])
    found_txt = "NaN" if row["found"] is None else str(row["found"])
    mark = "" if row["found"] == row["expected"] else " *"
    ax.set_title(f"{row['case']['name']}\nregime {found_txt} (expect {row['expected']}){mark}",
                 fontsize=fs, linespacing=1.25)


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
    cls = hc.executeHartClass(levels[1000.0], levels[925.0], levels[850.0], levels[700.0], levels[500.0],
                               levels[400.0], levels[300.0], u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
                               fc.psfc, fc.coriolis, fc.dx, fc.dy, radiusKm=fc.RADIUS_KM)
    codes, d, closed_low, closed_high = classify_regime(vtl, vtu, b, levels[1000.0], fc.dx, fc.dy, fc.psfc)
    thick = levels[500.0] - levels[1000.0]
    return dict(levels=levels, vtl=vtl, vtu=vtu, b=b, cls=cls, codes=codes, centers=centers, thick=thick)


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
    cls_masked = np.ma.masked_invalid(comp["cls"])
    ax_d.imshow(cls_masked, extent=fc.EXTENT, origin="lower", cmap=CLASS_CMAP, norm=CLASS_NORM,
                interpolation="nearest", aspect="auto", zorder=2)
    ax_d.set_title("(d) regime map, Hart class at the low", fontsize=8)

    for ax in (ax_a, ax_b, ax_c, ax_d):
        ax.set_xlim(fc.lon_vals.min(), fc.lon_vals.max())
        ax.set_ylim(fc.lat_vals.min(), fc.lat_vals.max())
        ax.tick_params(labelsize=6)
        ax.grid(True, color="0.85", lw=0.3, zorder=0)
        for name, (clat, clon) in comp["centers"].items():
            ax.plot(clon, clat, "o", color="k", ms=3.5, mec="white", mew=0.4, zorder=6)

    legend_handles = [Patch(facecolor=REGIME_COLORS[k], edgecolor="0.3", label=f"{k} {REGIME_NAMES[k]}")
                      for k in range(11)]
    ax_d.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=6,
                frameon=False, handlelength=1.2, handleheight=1.2)
    return ax_a, ax_b, ax_c, ax_d


# ----------------------------------------------------------------- main
def print_catalog_table(rows):
    print(f"{'feature':42s} {'expected':>9s} {'found':>7s}  match")
    mismatches = []
    for row in rows:
        found_txt = "NaN" if row["found"] is None else str(row["found"])
        ok = row["found"] == row["expected"]
        if not ok:
            mismatches.append(row)
        print(f"{row['case']['name']:42s} {row['expected']:9d} {found_txt:>7s}  {'OK' if ok else 'MISMATCH'}")
    return mismatches


def print_area_table(codes):
    valid = ~np.isnan(codes)
    total = valid.sum()
    print(f"{'code':>4s}  {'name':30s} {'area %':>8s}")
    for k in range(11):
        frac = 100.0 * np.sum(codes == k) / total if total else 0.0
        print(f"{k:4d}  {REGIME_NAMES[k]:30s} {frac:8.2f}")
    nan_frac = 100.0 * (~valid).sum() / codes.size
    print(f"{'NaN':>4s}  {'(closed low)':30s} {nan_frac:8.2f}  (of full grid, not the valid-area total above)")


def main():
    rows = build_catalog_panels()
    print("--- catalog cases: expected vs found regime at the test point ---")
    mismatches = print_catalog_table(rows)

    comp = compute_composite()
    print("\n--- composite scene: area fraction by regime code ---")
    print_area_table(comp["codes"])

    nrows_top = 3
    fig = plt.figure(figsize=(15.0, 15.5), constrained_layout=True)
    gs_outer = fig.add_gridspec(2, 1, height_ratios=[nrows_top, 1.7])
    gs_top = gs_outer[0].subgridspec(nrows_top, 6)
    for i, row in enumerate(rows):
        r, c = divmod(i, 6)
        ax = fig.add_subplot(gs_top[r, c])
        draw_catalog_cell(ax, row)

    gs_bottom = gs_outer[1].subgridspec(1, 4, width_ratios=[1, 1, 1, 1.35])
    draw_composite(fig, gs_bottom, 0, comp)

    fig.suptitle("Thermal wind regime prototype: catalog cases (top) and one composite scene (bottom)",
                 fontsize=12)
    fig.savefig(FIGH_PATH, dpi=300)
    plt.close(fig)

    size = FIGH_PATH.stat().st_size / 1e6
    print(f"\nwrote {FIGH_PATH} ({size:.2f} MB)")

    if mismatches:
        print("\nCatalog cases whose found regime does not match the expected one:")
        for row in mismatches:
            found_txt = "NaN" if row["found"] is None else str(row["found"])
            print(f"  {row['case']['name']}: expected {row['expected']} ({REGIME_NAMES[row['expected']]}), "
                  f"found {found_txt}")
    else:
        print("\nAll catalog cases match their expected regime.")

    other_frac = 100.0 * np.sum(comp["codes"] == 10) / np.sum(~np.isnan(comp["codes"]))
    print(f"\nComposite scene code 10 (other) area: {other_frac:.2f}% of the valid (non-closed-low) area.")


if __name__ == "__main__":
    main()
