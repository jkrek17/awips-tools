"""Synthetic feature catalog: what each synoptic feature in
cyclone_phase_space/docs/ANALYSIS_GUIDE.md section 4 ("Feature catalog")
looks like on HVTL, HVTU, HB and HCPSclass, built analytically and run
through the real operational module
(cyclone_phase_space/D2D/derivedParameters/functions/cps_HartCPS.py),
the same way lifecycle_comparison.py and experiments.py do.

Two figures, one row per feature, five panels per row:

- figF_catalog_lows.png: nine features at a closed low (hurricane,
  tropical cyclone meeting a front, transitioning tropical cyclone,
  extratropical low on a front, mature occluded low, warm seclusion,
  cut-off low, subtropical storm, polar low). Each is an axisymmetric
  (or, for the two frontal rows, dipole-perturbed) vortex built from
  band_comparison.ARCHETYPES amplitude profiles, sampled at the
  storm's own center grid point.
- figG_catalog_environment.png: eight features away from any closed
  low (surface front, polar jet axis, deep baroclinic zone, cold dome
  under the jet, shallow cold high, warm ridge, open trough, easterly
  flow along a front), built as a meridional background gradient (a
  smooth-step "front" whose curvature, not its slope, is what the
  pointwise window operators actually see) or an isolated anticyclone
  blob, sampled at the domain center.

Panels: (a) 1000 hPa height (solid, 40 m) with 1000-500 hPa thickness
(dashed red, 60 m); (b) HVTL; (c) HVTU; (d) HB; (e) HCPSclass. (b)-(d)
are rendered with a manual RGBA composite that mimics the shipped
diverging colormaps rather than a plain matplotlib Colormap/Normalize,
so hue and alpha can be controlled independently:

- HVTL, HVTU: a hand-built red/blue mimic of
  D2D/colormaps/Grid/CPS_CoreDiverging.cmap (red positive/warm core,
  blue negative/cold core), fully transparent within the middle 1/8 of
  the +/-300 m range and fading to opaque over the next 3/16 on each
  side.
- HB: the real D2D/colormaps/Grid/CPS_Asymmetry.cmap, its 64 rgba
  entries read directly from the file and used as a matplotlib
  ListedColormap (teal negative, magenta positive, transparent middle,
  first opaque magenta step at +10 m), over +/-40 m.

Run from this directory:

    python3 feature_catalog.py

Prints one row per feature (HVTL/HVTU/HB/class at the sample point),
writes both PNGs (300 dpi) next to this file, and reports any row
whose sampled values do not match the catalog signature.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent  # article/figures -> article -> cyclone_phase_space
sys.path.insert(0, str(REPO_ROOT / "D2D" / "derivedParameters" / "functions"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

import cps_HartCPS as hc  # noqa: E402
from experiments import dist_km, std_height, ANCHOR_P  # noqa: E402
from band_comparison import ARCHETYPES  # noqa: E402
from lifecycle_comparison import (  # noqa: E402
    build_grid, env_fields, across_track_km, local_offsets_km, s_of_p, DIPOLE_L_KM,
    RADIUS_KM, CLASS_PALETTE, CLASS_NAMES, RED,
)

hc.ORIENTATION_MODE = 0

FIGF_PATH = HERE / "figF_catalog_lows.png"
FIGG_PATH = HERE / "figG_catalog_environment.png"

LEVELS7 = [1000.0, 925.0, 850.0, 700.0, 500.0, 400.0, 300.0]
DOME_CMAP_PATH = REPO_ROOT / "D2D" / "colormaps" / "Grid" / "CPS_Asymmetry.cmap"

CLASS_CMAP = ListedColormap([CLASS_PALETTE[k] for k in range(7)])
CLASS_CMAP.set_bad(alpha=0.0)
CLASS_NORM = BoundaryNorm(np.arange(-0.5, 7.5, 1.0), CLASS_CMAP.N)


# ------------------------------------------------------------- colormaps
def load_cmap_rgba(path):
    """(N, 4) array of r,g,b,a floats from a CAVE-style .cmap XML file, in
    index order -- the same <colorMap><color r g b a/></colorMap> schema
    documented in CPS_CoreDiverging.cmap's and CPS_Asymmetry.cmap's own
    header comments.
    """
    root = ET.parse(path).getroot()
    rows = []
    for c in root.findall("color"):
        rows.append([float(c.get("r")), float(c.get("g")), float(c.get("b")), float(c.get("a"))])
    return np.array(rows, dtype=float)


ASYMMETRY_CMAP = ListedColormap(load_cmap_rgba(DOME_CMAP_PATH))
ASYMMETRY_CMAP.set_bad(alpha=0.0)
HB_RANGE = 40.0


def diverging_rgba(field, vmax):
    """RGBA array mimicking CPS_CoreDiverging.cmap for one field: red
    positive (warm core), blue negative (cold core), fully transparent
    within the middle 1/8 of +/-vmax, fading to opaque over the next
    3/16 on each side, solid beyond that. NaN is fully transparent.
    """
    field = np.asarray(field, dtype=float)
    t = np.clip(field / vmax, -1.0, 1.0)
    frac = np.abs(t)
    c_blue = np.array([0.05, 0.15, 0.60])
    c_red = np.array([0.60, 0.05, 0.05])
    s = (t + 1.0) / 2.0
    rgb = c_blue[None, None, :] * (1 - s)[..., None] + c_red[None, None, :] * s[..., None]
    lo, hi = 1.0 / 8.0, 1.0 / 8.0 + 3.0 / 16.0
    alpha = np.clip((frac - lo) / (hi - lo), 0.0, 1.0)
    alpha = np.where(np.isnan(field), 0.0, alpha)
    return np.concatenate([rgb, alpha[..., None]], axis=-1)


# --------------------------------------------------------------- grid
lat_vals, lon_vals, lat2d, lon2d, dx, dy = build_grid()
psfc, coriolis = env_fields(lat2d)
CLAT0, CLON0 = 37.5, 165.0  # domain center (also the default feature center)
EXTENT = (lon_vals.min(), lon_vals.max(), lat_vals.min(), lat_vals.max())
# figF_catalog_lows.png only: a storm-centered zoom (the full domain stays
# the computation grid, so the 500 km analysis window never touches an
# edge -- only these panels' axes limits are cropped to it).
FIGF_VIEW_EXTENT = (148.0, 182.0, 25.0, 50.0)


def center_ij(clat=CLAT0, clon=CLON0):
    ci = int(np.argmin(np.abs(lat_vals - clat)))
    cj = int(np.argmin(np.abs(lon_vals - clon)))
    return ci, cj


# ---------------------------------------------------- height builders
def amp_at(p, anchors):
    """dZ at pressure p (hPa), linear in ln p between ANCHOR_P, same
    convention as lifecycle_comparison.amp_interp / experiments.LEVELS.
    """
    xa = np.log(ANCHOR_P.astype(float))
    x = np.log(float(p))
    return float(np.interp(x, xa[::-1], np.asarray(anchors, float)[::-1]))


def vortex_shape(lat2d, lon2d, clat, clon, scale_km, elong=None):
    """Gaussian shape, 1 at the center falling to 0 away from it: a
    plain radial Gaussian, or (elong given) an elongated one -- an open
    trough's long, narrow anomaly with no closed contour a
    min_radius_km/depth_m/blob_radius_km closed-low search would find.
    """
    if elong is None:
        r = dist_km(lat2d, lon2d, clat, clon)
        return np.exp(-((r / scale_km) ** 2))
    along_km, across_km, angle_deg = elong
    ex, ey = local_offsets_km(lat2d, lon2d, clat, clon)
    theta = np.radians(angle_deg)
    along = ex * np.sin(theta) + ey * np.cos(theta)
    across = ex * np.cos(theta) - ey * np.sin(theta)
    return np.exp(-((along / along_km) ** 2) - ((across / across_km) ** 2))


def front_shape(lat2d, center, halfwidth):
    """The meridional shape whose own d/dlat is a smooth step (0 south of
    center-halfwidth, ramping to 1 by center+halfwidth, and held at 1
    -- i.e. a fixed further poleward slope -- beyond): a front embedded
    in a broader baroclinic zone, not an isolated ridge. Curvature (not
    slope) is concentrated in the ramp, which is what the pointwise
    window-difference operators (delta_z, parameter_b_grid) actually
    see -- a plain linear gradient has zero local curvature and gives
    zero VTL/VTU/B everywhere, so a front's signature has to come from
    a *kink* in the gradient like this one, exactly as
    lifecycle_comparison.s_of_lat_integral uses for its own baroclinic
    zone (this is the same construction, parameterized by center).
    """
    u = np.clip((lat2d - (center - halfwidth)) / (2.0 * halfwidth), 0.0, 1.0)
    ramp = halfwidth * 2.0 * (u - np.sin(np.pi * u) / np.pi)
    beyond = np.clip(lat2d - (center + halfwidth), 0.0, None)
    return ramp + beyond


def profile_in_lnp(p, points):
    """Piecewise-linear-in-ln(p) interpolation through (pressure, value)
    control points -- the vertical shape of a background gradient's own
    strength g(p), e.g. "grows with height only below 700 hPa".
    """
    ps = np.array([pt[0] for pt in points], dtype=float)
    vs = np.array([pt[1] for pt in points], dtype=float)
    x = np.log(p)
    xp = np.log(ps)
    return float(np.interp(x, xp[::-1], vs[::-1]))


def dipole_term(p, lat2d, lon2d, clat, clon, heading_deg, speed_ms, peak):
    """The storm-attached, motion-relative thickness-dipole height
    perturbation at pressure p -- lifecycle_comparison's own mechanism
    (across_track_km, s_of_p, DIPOLE_L_KM), reused unchanged. Vanishes
    exactly at the storm center (x_r = 0 there) by construction, so it
    perturbs only B (the asymmetry), never the center-point VTL/VTU.
    """
    if peak == 0.0:
        return 0.0
    x_r, r = across_track_km(lat2d, lon2d, clat, clon, heading_deg, speed_ms)
    coef = peak * (x_r / DIPOLE_L_KM) * np.exp(-(r ** 2) / (2.0 * DIPOLE_L_KM ** 2))
    return s_of_p(p) * coef


def build_case_levels(case, levels=LEVELS7):
    """{pressure: height array} for one feature-row's recipe. `case` is a
    dict; see the FIGF_ROWS/FIGG_ROWS recipes below for the fields each
    "kind" uses.
    """
    kind = case["kind"]
    clat = case.get("clat", CLAT0)
    clon = case.get("clon", CLON0)
    out = {}
    for p in levels:
        z = std_height(p)
        if kind == "vortex":
            shape = vortex_shape(lat2d, lon2d, clat, clon, case["scale_km"], case.get("elong"))
            amp = amp_at(p, case["anchors"]) * case["amp_scale"]
            z = z + case["sign"] * amp * shape
            z = z + dipole_term(p, lat2d, lon2d, clat, clon, case.get("heading_deg", 90.0),
                                 case.get("speed_ms", 10.0), case.get("dipole_peak", 0.0))
        elif kind == "front":
            for g0, points in case["parts"]:
                g = g0 * profile_in_lnp(p, points)
                z = z - g * front_shape(lat2d, clat, case.get("halfwidth", 5.0))
        else:
            raise ValueError(f"unknown case kind {kind!r}")
        out[p] = z
    return out


def compute_fields(z):
    """(vtl, vtu, b, cls) full 2D gridded fields from a {pressure: height}
    dict, plus the u_arr/v_arr steering used -- executeBand3/executeB/
    executeHartClass, exactly as lifecycle_comparison.compute_frame's own
    gridded branch calls them.
    """
    vtl = hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy, RADIUS_KM, 925.0, 850.0, 700.0)
    vtu = hc.executeBand3(z[500], z[400], z[300], psfc, dx, dy, RADIUS_KM, 500.0, 400.0, 300.0)
    return vtl, vtu


def compute_case(case):
    """All five panels' fields for one row, plus the sampled scalars at
    the row's own center (clat/clon for a vortex row, the domain center
    for a front row).
    """
    z = build_case_levels(case)
    u_speed = case.get("speed_ms", 10.0) if case["kind"] == "vortex" else case.get("speed_ms", 10.0)
    heading = case.get("heading_deg", 90.0)
    u_arr = np.full(lat2d.shape, u_speed * np.sin(np.radians(heading)))
    v_arr = np.full(lat2d.shape, u_speed * np.cos(np.radians(heading)))

    vtl, vtu = compute_fields(z)
    b = hc.executeB(z[925], z[700], u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
                     psfc, coriolis, dx, dy, radiusKm=RADIUS_KM, layerScale=hc.HART_B_LAYER_SCALE)
    # Synthetic mean sea level pressure (hPa) for the closed-low mask: 8 m of
    # 1000 hPa height per hPa of surface pressure (the standard rule of
    # thumb), applied to the *full* z[1000] field (not a perturbation-only
    # anomaly) -- std_height(1000) ~ 110.9 m maps to ~1013.9 hPa, matching
    # standard MSLP, so a feature's own height depression reads back as a
    # depression of the right order in hPa. executeHartClass now takes MSLP
    # as its first positional argument, in place of the old 1000 hPa height;
    # passing z[1000] unchanged here would silently test the mask's 5 hPa
    # depth floor against 5 m of *height* instead (no error, just a wrong,
    # far-too-permissive answer), which is the pitfall this conversion
    # avoids.
    pmsl = 1000.0 + z[1000] / 8.0
    cls = hc.executeHartClass(pmsl, z[925], z[850], z[700], z[500], z[400], z[300],
                               u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
                               psfc, coriolis, dx, dy, radiusKm=RADIUS_KM)
    thick_1000_500 = z[500] - z[1000]

    clat = case.get("clat", CLAT0)
    clon = case.get("clon", CLON0)
    ci, cj = center_ij(clat, clon)
    return dict(z=z, vtl=vtl, vtu=vtu, b=b, cls=cls, thick_1000_500=thick_1000_500,
                vtl0=float(vtl[ci, cj]), vtu0=float(vtu[ci, cj]), b0=float(b[ci, cj]),
                cls0=cls[ci, cj], ci=ci, cj=cj)


# ------------------------------------------------------------ recipes
DEEP_WARM = ARCHETYPES["deep warm core (mature typhoon)"]
TRANSITION = ARCHETYPES["transitioning (warm below 850)"]
DEEP_COLD = ARCHETYPES["deep cold core (extratropical)"]
SHALLOW_WARM = ARCHETYPES["shallow warm core (seclusion)"]
# Upper anomaly (500/400/300 hPa) scaled so HVTU lands near -350 m (still off
# the bottom of the +/-300 m color scale, the point of a cut-off low's
# "strongly blue" upper thermal wind, but not by a factor of three the way a
# plain doubled 300 hPa anchor did): HVTL, sampled only from 925/850/700, is
# unaffected and stays near -200 m.
CUTOFF_UPPER_SCALE = 1.65
CUTOFF_ANCHORS = list(DEEP_COLD[:5]) + [v * CUTOFF_UPPER_SCALE for v in DEEP_COLD[5:]]

STORM_SCALE_KM = 250.0
WEST_HEADING = 90.0  # u = +speed (a westerly wind, blowing from west to east)
EAST_HEADING = -90.0  # the reversed steering for the one "easterly" row

FIGF_ROWS = [
    dict(name="Hurricane or typhoon", kind="vortex", sign=-1, anchors=DEEP_WARM, amp_scale=0.99,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0),
    dict(name="Tropical cyclone meeting a front", kind="vortex", sign=-1, anchors=DEEP_WARM, amp_scale=1.0,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=12.0, dipole_peak=40.0),
    dict(name="Transitioning tropical cyclone", kind="vortex", sign=-1, anchors=TRANSITION, amp_scale=1.0,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=12.0, dipole_peak=120.0),
    dict(name="Extratropical low on a front, frontal wave", kind="vortex", sign=-1, anchors=DEEP_COLD,
         amp_scale=1.0, scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=12.0, dipole_peak=40.0),
    dict(name="Mature occluded low, Norwegian type", kind="vortex", sign=-1, anchors=DEEP_COLD, amp_scale=1.0,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0),
    dict(name="Warm seclusion, Shapiro-Keyser type", kind="vortex", sign=-1, anchors=SHALLOW_WARM, amp_scale=1.0,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0),
    dict(name="Cut-off low, cold low", kind="vortex", sign=-1, anchors=CUTOFF_ANCHORS, amp_scale=1.0,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0),
    dict(name="Subtropical storm, hybrid", kind="vortex", sign=-1, anchors=SHALLOW_WARM, amp_scale=0.40,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=20.0),
    dict(name="Polar low", kind="vortex", sign=-1, anchors=SHALLOW_WARM, amp_scale=0.30,
         scale_km=120.0, heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0),
]

# Catalog targets (from ANALYSIS_GUIDE.md 4.1), for the printed match check.
# `b` upper bounds for the two dipole-driven rows below (transitioning TC,
# subtropical storm) are widened from their pre-half-disk values: with
# parameter_b_grid's true half-disk means (see the D2D module docstring's
# "Parameter B and the joint class" section), this synthetic dipole reads
# about 1.8x what the older window-mean-gradient form read, so the old
# (30, 50) and (None, 10.0) ranges, tuned against the gradient form, now
# undershoot the gridded module's own output even though the class each
# row lands in is unchanged (still {3} and {1, 3} respectively).
FIGF_TARGETS = [
    dict(vtl=(100, 300), vtu=(100, 250), b=(None, 5.0), cls={0}),
    dict(vtl=(0, None), vtu=(0, None), b=(10, 30), cls={2}),
    dict(vtl=(0, None), vtu=(None, 0), b=(30, 80), cls={3}),
    dict(vtl=(None, 0), vtu=(None, 0), b=(5.0, None), cls={4}),
    dict(vtl=(None, 0), vtu=(None, 0), b=(None, 12.5), cls={5}),
    dict(vtl=(50, 250), vtu=(None, 0), b=(None, 5.0), cls={1}),
    dict(vtl=(None, 0), vtu=(None, -131.25), b=(None, 5.0), cls={5}),
    dict(vtl=(30, 80), vtu=(None, 0), b=(None, 15.0), cls={1, 3}),
    dict(vtl=(0, None), vtu=(None, 0), b=(None, 5.0), cls={1, None}),  # guide allows "1, or blank"
]

SFC_FRONT_PARTS = [(14.0, [(1000, 0.5), (925, 0.8), (850, 1.0), (700, 1.0), (500, 0.0), (400, 0.0), (300, 0.0)])]
JET_PARTS = [(15.0, [(1000, 0.03), (925, 0.06), (850, 0.10), (700, 0.15), (500, 0.3), (400, 0.7), (300, 1.0)])]
DEEP_PARTS = [(9.0, [(1000, 1.0), (925, 1.15), (850, 1.35), (700, 1.7), (500, 2.2), (400, 2.6), (300, 3.0)])]
# A cold dome under the jet is a surface anticyclone in the cold air: at
# 1000/925 hPa heights rise toward the cold (poleward) side (an easterly
# geostrophic wind under the dome), the gradient crosses zero near 850 hPa,
# and above 700 hPa heights fall toward the cold side as usual, growing
# through 500-300 hPa as the westerlies strengthen with height. front_shape
# is 0 south of center and grows poleward, and build_case_levels computes
# z = std_height - g(p)*front_shape, so g(p) here is the *negative* of the
# "positive means heights rise poleward" coefficients: -a at 1000 hPa,
# ramping through 0 near 850 hPa, to +b*2 at 300 hPa. a=4.4, b=5.0 (m per
# degree) land HVTL at +40 to +100 m and HB at +10 to +25 m, per the
# coordinator's corrected profile.
DOME_A = 4.4
DOME_B = 5.0
DOME_PARTS = [
    (1.0, [
        (1000, -DOME_A * 1.00),
        (925, -DOME_A * 0.70),
        (850, -DOME_A * 0.15),
        (700, DOME_A * 0.30),
        (600, DOME_A * 0.60),
        (500, DOME_B * 1.0),
        (400, DOME_B * 1.5),
        (300, DOME_B * 2.0),
    ]),
]

FIGG_ROWS = [
    dict(name="Surface front, low-level baroclinic zone", kind="front", parts=SFC_FRONT_PARTS,
         heading_deg=WEST_HEADING, speed_ms=10.0),
    dict(name="Polar jet axis", kind="front", parts=JET_PARTS, heading_deg=WEST_HEADING, speed_ms=10.0),
    dict(name="Deep baroclinic zone, front under the jet", kind="front", parts=DEEP_PARTS,
         heading_deg=WEST_HEADING, speed_ms=10.0),
    dict(name="Cold dome under the jet, overrunning", kind="front", parts=DOME_PARTS,
         heading_deg=WEST_HEADING, speed_ms=10.0),
    dict(name="Shallow cold high, arctic high", kind="vortex", sign=+1,
         anchors=[150, 120, 70, 25, 10, 0, 0, 0], amp_scale=0.6, scale_km=400.0,
         heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0),
    dict(name="Warm subtropical high, ridge", kind="vortex", sign=+1,
         anchors=[20, 40, 70, 100, 120, 150, 180, 220], amp_scale=0.5, scale_km=500.0,
         heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0),
    dict(name="Open trough, no closed low", kind="vortex", sign=-1, anchors=DEEP_COLD, amp_scale=0.5,
         scale_km=STORM_SCALE_KM, heading_deg=WEST_HEADING, speed_ms=10.0, dipole_peak=0.0,
         elong=(750.0, 150.0, 0.0)),
    dict(name="Easterly flow along a front, north side of a block", kind="front", parts=SFC_FRONT_PARTS,
         heading_deg=EAST_HEADING, speed_ms=10.0),
]

FIGG_TARGETS = [
    dict(vtl=(None, -37.5), vtu=None, b=(10, 30)),
    dict(vtl=None, vtu=(None, -37.5), b=(0.0, None)),
    dict(vtl=(None, 0), vtu=(None, 0), b=(10, 30)),
    dict(vtl=(40.0, 100.0), vtu=(None, 0), b=(10.0, 25.0)),
    dict(vtl=(0, None), vtu=(-37.5, 37.5), b=(-5.0, 5.0)),
    dict(vtl=(-131.25, -37.5), vtu=(-131.25, -37.5), b=(-5.0, 5.0)),
    dict(vtl=(None, 0), vtu=(None, 0), b=None),
    dict(vtl=None, vtu=None, b=(None, -10.0)),
]


def in_range(val, rng):
    if rng is None:
        return True
    lo, hi = rng
    if lo is not None and val < lo:
        return False
    if hi is not None and val > hi:
        return False
    return True


# ------------------------------------------------------------- panels
def level_step(field, step):
    lo = np.floor(np.nanmin(field) / step) * step
    hi = np.ceil(np.nanmax(field) / step) * step
    if hi <= lo:
        hi = lo + step
    return np.arange(lo, hi + step, step)


def _map_axes(ax, fs, view_extent=None):
    """view_extent, if given, is (lon0, lon1, lat0, lat1) -- a storm-centered
    zoom for figF_catalog_lows.png's axes limits only. The underlying
    fields are still computed (and imshow'd) on the full domain, so the
    500 km analysis window never touches an edge; only what the panel
    shows is cropped.
    """
    if view_extent is None:
        lon0, lon1, lat0, lat1 = lon_vals.min(), lon_vals.max(), lat_vals.min(), lat_vals.max()
        tick_step = 10
    else:
        lon0, lon1, lat0, lat1 = view_extent
        tick_step = 5
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    ax.grid(True, color="0.85", lw=0.4, zorder=0)
    ax.tick_params(labelsize=fs - 1)
    ax.set_xticks(np.arange(int(np.ceil(lon0 / tick_step)) * tick_step, int(lon1) + 1, tick_step))
    ax.set_yticks(np.arange(int(np.ceil(lat0 / tick_step)) * tick_step, int(lat1) + 1, tick_step))


def draw_panel_a(ax, r, case, fs=7, view_extent=None, z1000_step=40.0):
    z1000 = r["z"][1000.0]
    cs_h = ax.contour(lon2d, lat2d, z1000, levels=level_step(z1000, z1000_step), colors="0.3", linewidths=0.6)
    ax.clabel(cs_h, fontsize=fs - 1, fmt="%d", inline=True)
    ax.contour(lon2d, lat2d, r["thick_1000_500"], levels=level_step(r["thick_1000_500"], 60.0),
               colors=RED, linewidths=0.6, linestyles="dashed")
    clat, clon = case.get("clat", CLAT0), case.get("clon", CLON0)
    ax.plot(clon, clat, "o", color="k", ms=5, mec="white", mew=0.6, zorder=5)
    _map_axes(ax, fs, view_extent)


def draw_diverging_panel(ax, field, vmax, r, fs=7, view_extent=None, z1000_step=40.0):
    rgba = diverging_rgba(field, vmax)
    ax.imshow(rgba, extent=EXTENT, origin="lower", interpolation="nearest", aspect="auto", zorder=1)
    ax.contour(lon2d, lat2d, r["z"][1000.0], levels=level_step(r["z"][1000.0], z1000_step),
               colors="0.4", linewidths=0.5, zorder=2)
    _map_axes(ax, fs, view_extent)


def draw_hb_panel(ax, r, fs=7, view_extent=None, z1000_step=40.0):
    masked = np.ma.masked_invalid(r["b"])
    ax.imshow(masked, extent=EXTENT, origin="lower", cmap=ASYMMETRY_CMAP,
               vmin=-HB_RANGE, vmax=HB_RANGE, interpolation="nearest", aspect="auto", zorder=1)
    ax.contour(lon2d, lat2d, r["z"][1000.0], levels=level_step(r["z"][1000.0], z1000_step),
               colors="0.4", linewidths=0.5, zorder=2)
    _map_axes(ax, fs, view_extent)


def draw_class_panel(ax, r, fs=7, view_extent=None, z1000_step=40.0):
    masked = np.ma.masked_invalid(r["cls"])
    ax.imshow(masked, extent=EXTENT, origin="lower", cmap=CLASS_CMAP, norm=CLASS_NORM,
               interpolation="nearest", aspect="auto", zorder=1)
    ax.contour(lon2d, lat2d, r["z"][1000.0], levels=level_step(r["z"][1000.0], z1000_step),
               colors="0.3", linewidths=0.5, zorder=2)
    _map_axes(ax, fs, view_extent)


COLUMN_TITLES = (
    "(a) 1000 hPa height,\n1000-500 hPa thickness",
    "(b) HVTL",
    "(c) HVTU",
    "(d) HB, CPS_Asymmetry",
    "(e) HCPSclass",
)


def draw_row(fig, gs, row, case, r, show_titles, with_class_name, view_extent=None, z1000_step=40.0):
    label_ax = fig.add_subplot(gs[row, 0])
    label_ax.axis("off")
    label = case["name"]
    if with_class_name:
        cls0 = r["cls0"]
        cls_txt = "blank" if np.isnan(cls0) else f"{int(round(cls0))} ({CLASS_NAMES[int(round(cls0))]})"
        label = f"{label}\nclass {cls_txt}"
    label_ax.text(0.5, 0.5, label, fontsize=7.5, ha="center", va="center", linespacing=1.4, wrap=True)

    ax_a = fig.add_subplot(gs[row, 1])
    draw_panel_a(ax_a, r, case, view_extent=view_extent, z1000_step=z1000_step)
    ax_b = fig.add_subplot(gs[row, 2])
    draw_diverging_panel(ax_b, r["vtl"], 300.0, r, view_extent=view_extent, z1000_step=z1000_step)
    ax_c = fig.add_subplot(gs[row, 3])
    draw_diverging_panel(ax_c, r["vtu"], 300.0, r, view_extent=view_extent, z1000_step=z1000_step)
    ax_d = fig.add_subplot(gs[row, 4])
    draw_hb_panel(ax_d, r, view_extent=view_extent, z1000_step=z1000_step)
    ax_e = fig.add_subplot(gs[row, 5])
    draw_class_panel(ax_e, r, view_extent=view_extent, z1000_step=z1000_step)

    if show_titles:
        for ax, title in zip((ax_a, ax_b, ax_c, ax_d, ax_e), COLUMN_TITLES):
            ax.set_title(title, fontsize=8)


def build_figure(rows, results, out_path, suptitle, with_class_name, view_extent=None, z1000_step=40.0):
    nrows = len(rows)
    fig = plt.figure(figsize=(16.0, 2.15 * nrows + 0.6), constrained_layout=True)
    gs = fig.add_gridspec(nrows, 6, width_ratios=[0.62, 1, 1, 1, 1, 1])
    for row, (case, r) in enumerate(zip(rows, results)):
        draw_row(fig, gs, row, case, r, show_titles=(row == 0), with_class_name=with_class_name,
                 view_extent=view_extent, z1000_step=z1000_step)
    fig.suptitle(suptitle, fontsize=11)
    fig.savefig(out_path, dpi=300)
    plt.close(fig)


# ----------------------------------------------------------------- main
def fmt_cls(v):
    return "blank" if (v is None or np.isnan(v)) else str(int(round(v)))


def main():
    print(f"Grid: {lat2d.shape[0]} x {lat2d.shape[1]} points, {lat_vals.min():.1f}-{lat_vals.max():.1f}N, "
          f"{lon_vals.min():.1f}-{lon_vals.max():.1f}E")

    print("\n--- figF_catalog_lows.png: at a closed low (sampled at the storm center) ---")
    print(f"{'feature':42s} {'HVTL':>8s} {'HVTU':>8s} {'HB':>7s} {'class':>6s}  match")
    figf_results = []
    figf_mismatches = []
    for case, target in zip(FIGF_ROWS, FIGF_TARGETS):
        r = compute_case(case)
        figf_results.append(r)
        cls_int = None if np.isnan(r["cls0"]) else int(round(r["cls0"]))
        ok = (in_range(r["vtl0"], target["vtl"]) and in_range(r["vtu0"], target["vtu"])
              and in_range(r["b0"], target["b"]) and (cls_int in target["cls"]))
        if not ok:
            figf_mismatches.append(case["name"])
        print(f"{case['name']:42s} {r['vtl0']:8.1f} {r['vtu0']:8.1f} {r['b0']:7.2f} "
              f"{fmt_cls(r['cls0']):>6s}  {'OK' if ok else 'MISMATCH'}")

    print("\n--- figG_catalog_environment.png: away from lows (sampled at the domain center) ---")
    print(f"{'feature':42s} {'HVTL':>8s} {'HVTU':>8s} {'HB':>7s}  match")
    figg_results = []
    figg_mismatches = []
    for case, target in zip(FIGG_ROWS, FIGG_TARGETS):
        r = compute_case(case)
        figg_results.append(r)
        ok = (in_range(r["vtl0"], target["vtl"]) and in_range(r["vtu0"], target["vtu"])
              and in_range(r["b0"], target["b"]))
        if not ok:
            figg_mismatches.append(case["name"])
        print(f"{case['name']:42s} {r['vtl0']:8.1f} {r['vtu0']:8.1f} {r['b0']:7.2f}  {'OK' if ok else 'MISMATCH'}")

    build_figure(FIGF_ROWS, figf_results, FIGF_PATH,
                 "Feature catalog: nine synoptic features at a closed low (synthetic, gridded module)",
                 with_class_name=True, view_extent=FIGF_VIEW_EXTENT, z1000_step=20.0)
    build_figure(FIGG_ROWS, figg_results, FIGG_PATH,
                 "Feature catalog: eight synoptic features away from any closed low (synthetic, gridded module)",
                 with_class_name=False)

    size_f = FIGF_PATH.stat().st_size / 1e6
    size_g = FIGG_PATH.stat().st_size / 1e6
    print(f"\nwrote {FIGF_PATH} ({size_f:.2f} MB)")
    print(f"wrote {FIGG_PATH} ({size_g:.2f} MB)")

    if figf_mismatches or figg_mismatches:
        print("\nRows that do not match the catalog signature:")
        for name in figf_mismatches:
            print(f"  figF: {name}")
        for name in figg_mismatches:
            print(f"  figG: {name}")
    else:
        print("\nAll rows match their catalog signature.")


if __name__ == "__main__":
    main()
