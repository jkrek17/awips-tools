#!/usr/bin/env python3
"""
make_figures.py -- regenerates every figure on the GitHub Pages article
(../index.html) from the package's own operational code
(D2D/derivedParameters/functions/cps_HartCPS.py), run on synthetic fields,
plus one photograph of the real CAVE display that is cropped/resized only
(fig6).

Run from the repository root:

    python3 docs/cps/figures/make_figures.py

Outputs land next to this script, in docs/cps/figures/:
    fig1_phase_space.png    fig2_method.png       fig3_gridded.png
    fig4_tilt.png           fig5_performance.png   fig6_cave_typhoon.jpg
    fig7_parameter_b.png    fig8_thermal_wind_concept.png
    fig9_b_concept.png      fig10_two_diagrams.png

No test fixtures are reused: everything is built here so the figures are
reproducible from nothing but this file, cps_HartCPS.py, and
numpy/matplotlib.

---------------------------------------------------------------------------
Synthetic field definition (documented here so the HTML captions can
quote it precisely; every number below matches what is actually computed)
---------------------------------------------------------------------------

Grid
    Regular lat/lon, 0.5 degree spacing, longitude -160 to -100 (west to
    east), latitude 15 to 65 (south to north; array row 0 is the
    southernmost row, i.e. rows increase northward -- cps_HartCPS.py's
    own ORIENTATION_MODE 0 convention).  ``dy`` is a scalar, 0.5 degree of
    latitude = 55.6 km, in meters.  ``dx`` is a full 2D array in meters,
    ``dx[i, j] = 55.6 km * cos(lat[i])`` -- 0.5 degree of longitude at
    that row's latitude -- passed as AWIPS itself would pass it (a
    pseudo-field that varies across the grid).

Background height
    Z_std(p) = 100 m + 7000 m * ln(1000 hPa / p) (the same "standard-ish"
    background cps_HartCPS.py's own standalone demo uses), plus a weak
    meridional gradient that grows only modestly with height: 40 m per
    1000 km at 1000 hPa, linear in ln(p), to 60 m per 1000 km at 300 hPa.
    Height decreases northward at that rate from the grid's south edge,
    giving a baroclinic background whose thermal wind is uniform (a
    linear gradient has zero curl, so it never masquerades as a vortex)
    and whose ambient HVTL/HVTU, away from either vortex, stays within
    about +/-25 m -- inside the diverging colormap's neutral gray band,
    not painting the whole map cold.

Vortex A -- deep warm core, center 28N, 130W
    Gaussian height depression, horizontal scale (e-folding radius)
    150 km, amplitude A(p) linear in ln(p) from 250 m at 1000 hPa to
    20 m at 300 hPa (amplitude shrinks with height -> positive VTL/VTU,
    warm core).

Vortex B -- cold core, center 50N, 140W, tilted
    Gaussian height depression, horizontal scale 350 km, amplitude
    linear in ln(p) from 120 m at 1000 hPa to 450 m at 300 hPa (amplitude
    grows with height -> negative VTL/VTU, cold core).  The center is
    displaced westward with height, linearly in ln(p), by
    ``TILT_KM`` at 300 hPa (400 km per the spec; the script checks that
    this displaces the 300 hPa center at least a few grid points from
    the surface center and re-runs at 600 km if 400 km does not -- see
    ``make_fig4`` and the printed report).

Terrain
    Surface pressure 750 hPa over the rectangle 118W-108W, 35N-48N;
    1013 hPa elsewhere (open ocean).

Levels
    1000, 925, 850, 700, 500, 400, 300 hPa everywhere; Figure 4 also
    builds 600 hPa by the same ln(p) interpolation, used nowhere else.

Figure 7 -- transitioning-storm case (Parameter B and the ET stage)
    A separate, self-contained synthetic case built only for Figure 7
    (fig7_height_field/fig7_gradient_offset_m/fig7_steering_u below), on
    the same grid and the same vortex A amplitude profile as everywhere
    else, but with two changes so a transitioning storm is represented:

    * The background 925-700 hPa thickness gradient is raised to 90 m
      per 1000 km, decreasing northward (warm/thick to the south) --
      much stronger than the modest background above, on purpose, since
      the point of this figure is an environment strong enough to move
      parameter B past Hart's 10 m onset threshold.
    * Two identical copies of vortex A (same amplitude, same 150 km
      scale, no tilt) sit in different steering flow: one at 28N 130W
      (vortex A's own center) in a uniform 6 m/s easterly, one at 42N
      140W in a uniform 12 m/s westerly, blended smoothly (tanh) between
      25N and 35N. Because the steering is (almost) purely zonal, the
      right-hand normal of motion is due south for the westerly copy and
      due north for the easterly one, so the same southward thickness
      gradient projects with opposite sign at the two centers -- see
      cps_HartCPS.py's own module docstring, "Parameter B and ET stage", for
      the projection cps_HartCPS.parameter_b_grid computes, and this
      script's own printed report for the two centers' actual (B, VTL)
      values and the sign reasoning. A small, short-lived poleward turn
      (FIG7_STEERING_TURN_MS, a few m/s) is superimposed only on the
      reversal itself, negligible by the time either vortex center is
      reached: parameter_b_grid's right-hand normal is a unit vector, so
      a purely zonal reversal flips its sign in a single step with no B
      value anywhere near the 10 m onset threshold to draw a contour
      through; the brief turn (a storm recurving, not stopping dead)
      sweeps that normal continuously through the intermediate
      directions instead, which is what gives Figure 7b an actual B=10 m
      contour to draw.

    cps_HartCPS.ORIENTATION_MODE is set to 0 for this figure, same reason
    and same convention as Figure 4's own setting: cps_HartCPS.gradient_2d
    (the one function in that module that takes a spatial derivative)
    needs to know that this synthetic grid's rows increase northward.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, BoundaryNorm
from matplotlib.patches import Rectangle, Circle, Wedge
from matplotlib.lines import Line2D

# ---------------------------------------------------------------------------
# Make cps_HartCPS.py importable exactly as CAVE imports it (a bare module,
# no package), per tests/d2d_cps/conftest.py's own approach.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent  # docs/cps/figures -> docs/cps -> docs -> repo root
FUNCTIONS_DIR = REPO_ROOT / "D2D" / "derivedParameters" / "functions"
SYNTHETIC_TEST_DIR = REPO_ROOT / "tests" / "cps"
sys.path.insert(0, str(FUNCTIONS_DIR))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SYNTHETIC_TEST_DIR))

import cps_HartCPS  # noqa: E402

# Figures 8-10 (teaching figures) are built with cps/hart.py, the pure-numpy
# reference implementation of Hart (2003) itself -- Hart's own 900-600/
# 600-300 hPa, 50 hPa-spaced bands and a circular window -- rather than
# cps_HartCPS.py's operational, standard-level approximation (925/850/700 and
# 500/400/300 hPa, a square window) used by every other figure in this
# script. tests/cps/synthetic.py's make_grid/warm_core_heights (a second,
# independently written implementation of the same offset geometry, per its
# own module docstring) builds the small lat/lon grid these three figures
# need.
import cps.hart as hart  # noqa: E402
import synthetic as cps_synthetic  # noqa: E402  (tests/cps/synthetic.py)

OUT_DIR = HERE
UPLOAD_PHOTO = Path("/root/.claude/uploads/3a4711f2-52b1-52e4-8d45-df8bae2bffec/2bca2450-image.jpg")

# ---------------------------------------------------------------------------
# Palette (fixed, per the article's style rules)
# ---------------------------------------------------------------------------

TEXT_DARK = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID_COLOR = "#dedcd5"

DIVERGING_STOPS = [
    (0.00, "#104281"),
    (0.25, "#2a78d6"),
    (0.50, "#f0efec"),
    (0.75, "#e34948"),
    (1.00, "#7a1f1f"),
]
CMAP_DIVERGING = LinearSegmentedColormap.from_list("cps_diverging", DIVERGING_STOPS)

CMAP_SEQ_BLUE = LinearSegmentedColormap.from_list("cps_seq_blue", ["#cde2fb", "#0d366b"])

CATEGORY_COLORS = ["#4a3aa7", "#2a78d6", "#c3c2b7", "#eb6834", "#e34948"]

# HCPSclass (the joint Hart CPS class): 7 entries in code order, matching
# D2D/colormaps/Grid/CPS_HartClass.cmap's own colors exactly, so the
# figure and the shipped D2D colormap read identically. Warm states
# (codes 0-3) are warm hues, cold states (4-5) are cool hues, and the
# mid-level vortex (6) is neutral gray -- see that .cmap file's header
# comment for the same convention.
HARTCLASS_COLORS = [
    (0.89, 0.29, 0.28, 1.0),  # 0 symmetric deep warm core -- red
    (0.92, 0.41, 0.20, 1.0),  # 1 symmetric shallow warm core -- orange
    (0.91, 0.48, 0.64, 1.0),  # 2 frontal deep warm core -- magenta
    (0.93, 0.63, 0.00, 1.0),  # 3 frontal shallow warm core -- yellow
    (0.16, 0.47, 0.84, 1.0),  # 4 frontal cold core -- blue
    (0.29, 0.23, 0.65, 1.0),  # 5 symmetric cold core -- violet
    (0.76, 0.76, 0.72, 1.0),  # 6 mid-level vortex -- gray
]
HARTCLASS_NAMES = [
    "0  sym. deep warm core",
    "1  sym. shallow warm core",
    "2  frontal deep warm core",
    "3  frontal shallow warm core",
    "4  frontal cold core",
    "5  sym. cold core",
    "6  mid-level vortex",
]
CMAP_HARTCLASS = ListedColormap(HARTCLASS_COLORS)
NORM_HARTCLASS = BoundaryNorm(np.arange(-0.5, 7.5, 1.0), CMAP_HARTCLASS.N)

VORTEX_A_COLOR = "#e34948"
VORTEX_B_COLOR = "#2a78d6"

# Light fill tints for Figure 8's cross-sections: VORTEX_A/B_COLOR blended
# 30% color / 70% white.
LIGHT_RED = "#f7c8c8"
LIGHT_BLUE = "#bfd7f3"

# Very light, non-thermal neutral tints for Figure 9a's left/right split
# (deliberately not red/blue, since that panel carries no warm/cold
# meaning -- only Figure 9b's flanks do).
NEUTRAL_TINT_1 = "#c3c2b7"
NEUTRAL_TINT_2 = "#e8e7e2"

FULL_WIDTH_IN = 7.0
HALF_WIDTH_IN = 3.4

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "text.color": TEXT_DARK,
        "axes.edgecolor": TEXT_SECONDARY,
        "axes.labelcolor": TEXT_DARK,
        "axes.titlesize": 9,
        "xtick.color": TEXT_SECONDARY,
        "ytick.color": TEXT_SECONDARY,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "axes.linewidth": 0.6,
        "grid.color": GRID_COLOR,
        "grid.linewidth": 0.5,
        "legend.fontsize": 8,
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    }
)


def panel_letter(ax, letter):
    """Small bold panel letter, top-left, per the style rules."""
    ax.text(
        0.02,
        0.96,
        f"({letter})",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        fontweight="bold",
        color=TEXT_DARK,
        zorder=20,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1.5),
    )


# ---------------------------------------------------------------------------
# Synthetic grid and field construction
# ---------------------------------------------------------------------------

EARTH_RADIUS_KM = 6371.0
LAT_MIN, LAT_MAX = 15.0, 65.0
LON_MIN, LON_MAX = -160.0, -100.0
DLAT = DLON = 0.5
STANDARD_LEVELS = (1000.0, 925.0, 850.0, 700.0, 500.0, 400.0, 300.0)
HART_50HPA_LEVELS = (900, 850, 800, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300)

VORTEX_A = dict(lat=28.0, lon=-130.0, scale_km=150.0, amp1000=250.0, amp300=20.0)
VORTEX_B = dict(lat=50.0, lon=-140.0, scale_km=350.0, amp1000=120.0, amp300=450.0)
DEFAULT_TILT_KM = 400.0

TERRAIN_LON = (-118.0, -108.0)
TERRAIN_LAT = (35.0, 48.0)
PSFC_TERRAIN_HPA = 750.0
PSFC_OCEAN_HPA = 1013.0


def haversine_km(lat1, lon1, lat2, lon2):
    lat1r, lat2r = np.radians(lat1), np.radians(lat2)
    dlat = lat2r - lat1r
    dlon = np.radians(((np.asarray(lon2, dtype=float) - np.asarray(lon1, dtype=float)) + 180.0) % 360.0 - 180.0)
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def build_grid():
    """Regular 0.5 deg lat/lon grid; dx a 2D array (m), dy a scalar (m)."""
    lat_vals = np.arange(LAT_MIN, LAT_MAX + 1e-9, DLAT)
    lon_vals = np.arange(LON_MIN, LON_MAX + 1e-9, DLON)
    lon2d, lat2d = np.meshgrid(lon_vals, lat_vals)
    dy_m = 55.6e3
    dx2d = 55.6e3 * np.cos(np.radians(lat2d))
    return lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m


def nearest_index(lat_vals, lon_vals, lat0, lon0):
    i = int(np.argmin(np.abs(lat_vals - lat0)))
    j = int(np.argmin(np.abs(lon_vals - lon0)))
    return i, j


def z_std(p):
    """'Standard-ish' background height profile, meters."""
    return 100.0 + 7000.0 * np.log(1000.0 / p)


def meridional_gradient_m(lat2d, p):
    """Height offset (m), decreasing northward from the grid's south
    edge at a rate that grows only modestly with height: 40 m/1000km at
    1000 hPa, linear in ln(p) to 60 m/1000km at 300 hPa. (Earlier this
    rate grew much faster with height -- 60 to 132 m/1000km -- which made
    ambient HVTL/HVTU away from either vortex read around -80 m, painting
    the whole map light blue instead of the diverging colormap's neutral
    gray; this modest range keeps ambient values within about +/-25 m.)
    """
    rate_per_1000km = _linear_in_lnp(p, 1000.0, 40.0, 300.0, 60.0)
    y_km = (lat2d - LAT_MIN) * 111.2
    return -rate_per_1000km * (y_km / 1000.0)


def _linear_in_lnp(p, p_lo, val_lo, p_hi, val_hi):
    """Linear interpolation in ln(p) between (p_lo, val_lo) and (p_hi, val_hi)."""
    x = np.log(p)
    x_lo, x_hi = np.log(p_lo), np.log(p_hi)
    return val_lo + (val_hi - val_lo) * (x - x_lo) / (x_hi - x_lo)


def vortex_a_amp(p):
    return _linear_in_lnp(p, 1000.0, VORTEX_A["amp1000"], 300.0, VORTEX_A["amp300"])


def vortex_b_amp(p):
    return _linear_in_lnp(p, 1000.0, VORTEX_B["amp1000"], 300.0, VORTEX_B["amp300"])


def vortex_b_westward_shift_km(p, tilt_km):
    """0 at 1000 hPa, tilt_km at 300 hPa, linear in ln(p)."""
    return _linear_in_lnp(p, 1000.0, 0.0, 300.0, tilt_km)


def height_field(lat2d, lon2d, p, tilt_km=DEFAULT_TILT_KM, include_a=True, include_b=True):
    """Full synthetic height field (m) at pressure p (any value, not just
    a standard level -- used to build the 600 hPa level for Figure 4).
    """
    z = z_std(p) + meridional_gradient_m(lat2d, p)

    if include_a:
        r_a = haversine_km(lat2d, lon2d, VORTEX_A["lat"], VORTEX_A["lon"])
        decay_a = np.exp(-(r_a / VORTEX_A["scale_km"]) ** 2)
        z = z - vortex_a_amp(p) * decay_a

    if include_b:
        shift_km = vortex_b_westward_shift_km(p, tilt_km)
        # Westward shift: more negative longitude, at vortex B's latitude.
        shift_deg_lon = shift_km / (111.2 * np.cos(np.radians(VORTEX_B["lat"])))
        lon_center_b = VORTEX_B["lon"] - shift_deg_lon
        r_b = haversine_km(lat2d, lon2d, VORTEX_B["lat"], lon_center_b)
        decay_b = np.exp(-(r_b / VORTEX_B["scale_km"]) ** 2)
        z = z - vortex_b_amp(p) * decay_b

    return z


def build_level_stack(lat2d, lon2d, levels=STANDARD_LEVELS, tilt_km=DEFAULT_TILT_KM, **kw):
    return {p: height_field(lat2d, lon2d, p, tilt_km=tilt_km, **kw) for p in levels}


def build_psfc(lat2d, lon2d):
    psfc = np.full(lat2d.shape, PSFC_OCEAN_HPA)
    in_box = (
        (lon2d >= TERRAIN_LON[0])
        & (lon2d <= TERRAIN_LON[1])
        & (lat2d >= TERRAIN_LAT[0])
        & (lat2d <= TERRAIN_LAT[1])
    )
    psfc[in_box] = PSFC_TERRAIN_HPA
    return psfc


def scalar_band_slope(dz_by_level, band_levels):
    """cps_HartCPS.band_slope wants 2D grid arrays; wrap plain floats as 1x1
    arrays so the point-evaluation in Figure 2(a) goes through the
    package's own function, not a hand-rolled slope.
    """
    arrs = [np.array([[dz_by_level[p]]], dtype=float) for p in band_levels]
    return float(cps_HartCPS.band_slope(arrs, band_levels)[0, 0])


# ---------------------------------------------------------------------------
# Map helpers
# ---------------------------------------------------------------------------


def _fmt_lon(lon):
    lon = ((lon + 180.0) % 360.0) - 180.0
    if abs(lon) < 1e-6:
        return "0°"
    return f"{abs(lon):.0f}°{'W' if lon < 0 else 'E'}"


def _fmt_lat(lat):
    if abs(lat) < 1e-6:
        return "0°"
    return f"{abs(lat):.0f}°{'N' if lat > 0 else 'S'}"


def style_map_axes(ax, lon_min, lon_max, lat_min, lat_max, tick_step=10.0):
    xt = np.arange(np.ceil(lon_min / tick_step) * tick_step, lon_max + 1e-6, tick_step)
    yt = np.arange(np.ceil(lat_min / tick_step) * tick_step, lat_max + 1e-6, tick_step)
    ax.set_xticks(xt)
    ax.set_xticklabels([_fmt_lon(v) for v in xt], rotation=30, ha="right", fontsize=7.5)
    ax.set_yticks(yt)
    ax.set_yticklabels([_fmt_lat(v) for v in yt], fontsize=7.5)
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_aspect(1.0 / np.cos(np.radians(0.5 * (lat_min + lat_max))))
    ax.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0.5)
    ax.tick_params(length=3)


def draw_terrain_box(ax, hatch=False):
    if hatch:
        ax.add_patch(
            Rectangle(
                (TERRAIN_LON[0], TERRAIN_LAT[0]),
                TERRAIN_LON[1] - TERRAIN_LON[0],
                TERRAIN_LAT[1] - TERRAIN_LAT[0],
                facecolor="none",
                edgecolor=TEXT_SECONDARY,
                hatch="////",
                linewidth=0.0,
                zorder=1.5,
            )
        )
    ax.add_patch(
        Rectangle(
            (TERRAIN_LON[0], TERRAIN_LAT[0]),
            TERRAIN_LON[1] - TERRAIN_LON[0],
            TERRAIN_LAT[1] - TERRAIN_LAT[0],
            facecolor="none",
            edgecolor=TEXT_SECONDARY,
            linestyle="--",
            linewidth=1.0,
            zorder=8,
        )
    )


# ===========================================================================
# Figure 1: Hart's phase-space diagram, schematic
# ===========================================================================


def make_fig1(lat2d=None, lon2d=None):
    fig, ax = plt.subplots(figsize=(FULL_WIDTH_IN, 5.0))

    lim = 300.0
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)

    quadrants = [
        (0, lim, 0, lim, "#e34948", "deep warm core"),
        (0, lim, -lim, 0, "#eb6834", "shallow warm core"),
        (-lim, 0, -lim, 0, "#2a78d6", "cold core"),
        (-lim, 0, 0, lim, "#4a3aa7", "lower cold, upper warm"),
    ]
    for x0, x1, y0, y1, color, label in quadrants:
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=color, alpha=0.11, edgecolor="none", zorder=0))

    label_pos = {
        "deep warm core": (lim * 0.55, lim * 0.90),
        "shallow warm core": (lim * 0.55, -lim * 0.90),
        "cold core": (-lim * 0.95, -lim * 0.90),
        "lower cold, upper warm": (-lim * 0.95, lim * 0.68),
    }
    for _, _, _, _, _, label in quadrants:
        x, y = label_pos[label]
        ha = "left" if x > 0 else "left"
        ax.text(x, y, label, color=TEXT_SECONDARY, fontsize=8.5, ha=ha, va="center", style="italic")

    ax.axhline(0, color=TEXT_DARK, linewidth=1.0, zorder=2)
    ax.axvline(0, color=TEXT_DARK, linewidth=1.0, zorder=2)

    # Schematic ET trajectory, 0-168 h every 24 h.
    traj = np.array(
        [
            (240, 200),
            (210, 150),
            (160, 80),
            (110, 10),
            (60, -70),
            (0, -140),
            (-80, -200),
            (-150, -230),
        ],
        dtype=float,
    )
    hours = np.arange(0, 24 * traj.shape[0], 24)
    ax.plot(traj[:, 0], traj[:, 1], color=TEXT_SECONDARY, linewidth=2.0, zorder=5)
    for k, (x, y) in enumerate(traj):
        color = CMAP_SEQ_BLUE(k / (traj.shape[0] - 1))
        ax.plot(x, y, marker="o", markersize=7, markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.8, zorder=6)
        dx_txt, dy_txt = 10, 10
        va = "bottom"
        if k == traj.shape[0] - 1:
            dy_txt = -14
            va = "top"
        ax.annotate(
            f"{hours[k]} h",
            (x, y),
            textcoords="offset points",
            xytext=(dx_txt, dy_txt),
            fontsize=7.5,
            color=TEXT_SECONDARY,
            va=va,
        )

    # Validation-case star.
    ax.plot(120, 180, marker="*", markersize=15, markerfacecolor="#e34948", markeredgecolor="white", markeredgewidth=0.8, zorder=7)
    ax.annotate(
        "Typhoon, GFS 72 h forecast\n(validation case)",
        (120, 180),
        textcoords="offset points",
        xytext=(10, 16),
        fontsize=7.8,
        color=TEXT_DARK,
        va="bottom",
        ha="left",
    )

    ax.set_xlabel(r"$-V_T^L$  (m)")
    ax.set_ylabel(r"$-V_T^U$  (m)")
    ax.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0.2)
    ax.tick_params(length=3)
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)

    panel_letter(ax, "a")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig1_phase_space.png")
    plt.close(fig)


# ===========================================================================
# Figure 2: method (dZ profile + window)
# ===========================================================================


def make_fig2(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, z_std_stack):
    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH_IN, 3.5))
    ax_a, ax_b = axes

    # --- panel (a): dZ profile at each vortex's own center -----------------
    iA, jA = nearest_index(lat_vals, lon_vals, VORTEX_A["lat"], VORTEX_A["lon"])
    iB, jB = nearest_index(lat_vals, lon_vals, VORTEX_B["lat"], VORTEX_B["lon"])

    dz_full = {p: cps_HartCPS.delta_z(z_std_stack[p], dx2d, dy_m, cps_HartCPS.RADIUS_KM) for p in STANDARD_LEVELS}
    dzA = {p: float(dz_full[p][iA, jA]) for p in STANDARD_LEVELS}
    dzB = {p: float(dz_full[p][iB, jB]) for p in STANDARD_LEVELS}

    # Offsets (points) for each vortex/band annotation, hand-tuned so the
    # four labels sit beside the middle of their own fit line rather than
    # colliding with each other, a marker, or the axes frame. The lower
    # band anchors at its own top level (700 hPa); the upper band anchors
    # at its *middle* level (400 hPa) rather than its top (300 hPa, the
    # very edge of the axes) so there is room on either side to place
    # vortex A's label to the right of its line and vortex B's to the
    # left of its line, well clear of one another.
    ann_offset = {
        ("A", "L"): (10, 10),
        ("B", "L"): (10, -16),
        ("A", "U"): (14, -4),
        ("B", "U"): (-85, 4),
    }
    ann_anchor_p = {"L": cps_HartCPS.LOWER_BAND[-1], "U": cps_HartCPS.UPPER_BAND[1]}  # 700, 400

    for vortex_id, dz_dict, color in (("A", dzA, VORTEX_A_COLOR), ("B", dzB, VORTEX_B_COLOR)):
        xs = [dz_dict[p] for p in STANDARD_LEVELS]
        ax_a.plot(xs, STANDARD_LEVELS, marker="o", markersize=6, linewidth=0, markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.6, zorder=5)

        for band, band_name in ((cps_HartCPS.LOWER_BAND, "L"), (cps_HartCPS.UPPER_BAND, "U")):
            slope = scalar_band_slope(dz_dict, band)
            ybar = np.mean([dz_dict[p] for p in band])
            xbar = np.mean(np.log(band))
            p_line = np.linspace(min(band), max(band), 30)
            dz_line = ybar + slope * (np.log(p_line) - xbar)
            ax_a.plot(dz_line, p_line, color=color, linewidth=1.8, linestyle="-", zorder=4)
            p_anchor = ann_anchor_p[band_name]
            dz_anchor = ybar + slope * (np.log(p_anchor) - xbar)
            ax_a.annotate(
                f"$-V_T^{band_name}$ = {slope:+.0f} m",
                (dz_anchor, p_anchor),
                textcoords="offset points",
                xytext=ann_offset[(vortex_id, band_name)],
                fontsize=7.5,
                color=color,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=0.8),
            )

    ax_a.set_yscale("log")
    ax_a.invert_yaxis()
    ax_a.set_ylim(1030, 280)
    # Left bound pulled in to about 50 m: vortex A's small upper-band dZ
    # (down near 130-170 m) would otherwise sit right under the "(a)"
    # panel letter in the top-left corner; this pushes it away from that
    # corner without moving the letter.
    ax_a.set_xlim(left=50.0)
    ax_a.yaxis.set_major_locator(plt.FixedLocator(STANDARD_LEVELS))
    ax_a.yaxis.set_minor_locator(plt.NullLocator())
    ax_a.set_yticklabels([f"{int(p)}" for p in STANDARD_LEVELS])
    ax_a.set_ylabel("pressure (hPa)")
    ax_a.set_xlabel(r"$\Delta Z$ (m)")
    ax_a.grid(True, which="major", color=GRID_COLOR, linewidth=0.5)

    # Faint right-axis ticks at Hart's original 50 hPa levels, to show
    # what the seven standard levels on the left axis omit.
    secax = ax_a.secondary_yaxis("right")
    secax.set_yticks(HART_50HPA_LEVELS)
    secax.set_yticklabels([])
    secax.tick_params(length=4, width=0.8, color="#9a9993")
    secax.spines["right"].set_color("#9a9993")

    legend_handles = [
        Line2D([0], [0], color=VORTEX_A_COLOR, marker="o", markerfacecolor=VORTEX_A_COLOR, markeredgecolor="white", linewidth=1.8, markersize=6, label="Vortex A"),
        Line2D([0], [0], color=VORTEX_B_COLOR, marker="o", markerfacecolor=VORTEX_B_COLOR, markeredgecolor="white", linewidth=1.8, markersize=6, label="Vortex B"),
    ]
    ax_a.legend(handles=legend_handles, loc="lower right", frameon=False)
    panel_letter(ax_a, "a")

    # --- panel (b): the window, Z925 of vortex A only -----------------------
    z925_a_only = height_field(lat2d, lon2d, 925.0, include_b=False)

    # Local Cartesian offsets (km) from vortex A's center, exact haversine-based.
    dlat_deg = lat2d - VORTEX_A["lat"]
    dlon_deg = ((lon2d - VORTEX_A["lon"] + 180.0) % 360.0) - 180.0
    x_km_full = EARTH_RADIUS_KM * np.cos(np.radians(VORTEX_A["lat"])) * np.radians(dlon_deg)
    y_km_full = EARTH_RADIUS_KM * np.radians(dlat_deg)

    win = 750.0
    mask = (np.abs(x_km_full) <= win) & (np.abs(y_km_full) <= win)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    r0, r1 = rows.min(), rows.max() + 1
    c0, c1 = cols.min(), cols.max() + 1

    x_km = x_km_full[r0:r1, c0:c1]
    y_km = y_km_full[r0:r1, c0:c1]
    z_sub = z925_a_only[r0:r1, c0:c1]

    cf = ax_b.contourf(x_km, y_km, z_sub, levels=20, cmap=CMAP_SEQ_BLUE, zorder=1)
    ax_b.contour(x_km, y_km, z_sub, levels=10, colors=TEXT_SECONDARY, linewidths=0.5, zorder=2)
    cbar = fig.colorbar(cf, ax=ax_b, pad=0.02, fraction=0.05)
    cbar.set_label("Z925 (m)", fontsize=8)
    cbar.ax.tick_params(labelsize=7.5)

    ax_b.add_patch(Rectangle((-500, -500), 1000, 1000, facecolor="none", edgecolor=TEXT_DARK, linewidth=1.5, zorder=6))
    circle = Circle((0, 0), 500, facecolor="none", edgecolor=TEXT_DARK, linewidth=1.5, linestyle="--", zorder=6)
    ax_b.add_patch(circle)
    ax_b.text(495, 460, "1000 km square", fontsize=7.5, color=TEXT_DARK, ha="right", va="top")
    ax_b.text(0, -560, "Hart's 500 km circle", fontsize=7.5, color=TEXT_DARK, ha="center", va="top", style="italic")

    win_mask = (np.abs(x_km) <= 500.0) & (np.abs(y_km) <= 500.0)
    z_win = np.where(win_mask, z_sub, np.nan)
    i_max = np.unravel_index(np.nanargmax(z_win), z_win.shape)
    i_min = np.unravel_index(np.nanargmin(z_win), z_win.shape)
    ax_b.plot(x_km[i_max], y_km[i_max], marker="^", markersize=8, markerfacecolor="white", markeredgecolor=TEXT_DARK, markeredgewidth=1.2, zorder=7)
    ax_b.annotate(f"max {z_sub[i_max]:.0f} m", (x_km[i_max], y_km[i_max]), textcoords="offset points", xytext=(6, 6), fontsize=7.5, color=TEXT_DARK)
    ax_b.plot(x_km[i_min], y_km[i_min], marker="v", markersize=8, markerfacecolor="white", markeredgecolor=TEXT_DARK, markeredgewidth=1.2, zorder=7)
    ax_b.annotate(f"min {z_sub[i_min]:.0f} m", (x_km[i_min], y_km[i_min]), textcoords="offset points", xytext=(6, -12), fontsize=7.5, color=TEXT_DARK)

    ax_b.set_xlabel("km east of center")
    ax_b.set_ylabel("km north of center")
    ax_b.set_aspect("equal")
    ax_b.set_xlim(-win, win)
    ax_b.set_ylim(-win, win)
    ax_b.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0.2)
    panel_letter(ax_b, "b")

    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig2_method.png")
    plt.close(fig)


# ===========================================================================
# Figure 3: gridded fields, 2x2
# ===========================================================================


def make_fig3(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, z_std_stack, psfc):
    # The map axes are forced to equal aspect (style_map_axes), so with
    # constrained_layout the figure height, not the pad settings, is what
    # controls the gap between rows: too tall for the panels' own aspect
    # and constrained_layout parks the leftover space as a band between
    # rows. 5.4 in keeps that gap close to the column gap.
    fig, axes = plt.subplots(2, 2, figsize=(FULL_WIDTH_IN, 5.4), constrained_layout=True)
    fig.get_layout_engine().set(h_pad=0.06, w_pad=0.04, hspace=0.02, wspace=0.02)
    (ax_a, ax_b), (ax_c, ax_d) = axes

    for ax in (ax_a, ax_b, ax_c, ax_d):
        style_map_axes(ax, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)

    # (a) 1000 hPa height
    z1000 = z_std_stack[1000.0]
    cf_a = ax_a.contourf(lon2d, lat2d, z1000, levels=20, cmap=CMAP_SEQ_BLUE, zorder=1)
    ax_a.contour(lon2d, lat2d, z1000, levels=np.arange(np.floor(z1000.min() / 20) * 20, z1000.max() + 20, 20), colors=TEXT_SECONDARY, linewidths=0.4, zorder=2)
    draw_terrain_box(ax_a)
    cb_a = fig.colorbar(cf_a, ax=ax_a, pad=0.02, fraction=0.05)
    cb_a.set_label("Z1000 (m)", fontsize=8)
    cb_a.ax.tick_params(labelsize=7.5)
    panel_letter(ax_a, "a")

    # (b) HVTL, (c) HVTU
    hvtl = cps_HartCPS.executeBand3(
        z_std_stack[925.0], z_std_stack[850.0], z_std_stack[700.0], psfc, dx2d, dy_m,
        500.0, 925.0, 850.0, 700.0,
    )
    hvtu = cps_HartCPS.executeBand3(
        z_std_stack[500.0], z_std_stack[400.0], z_std_stack[300.0], psfc, dx2d, dy_m,
        500.0, 500.0, 400.0, 300.0,
    )
    # (b) and (c) sit on the diagonal of this reading-order grid (top-right,
    # bottom-left), so a single matplotlib colorbar spanning both axes lays
    # out badly (it spans the two axes' bounding box, which collides with
    # panel (d)'s own colorbar). Two colorbars with the identical -300/300
    # range give the same "shared scale" comparison the two panels need,
    # without that layout bug.
    vlim = 300.0
    draw_terrain_box(ax_b, hatch=True)
    pm_b = ax_b.pcolormesh(lon2d, lat2d, hvtl, cmap=CMAP_DIVERGING, vmin=-vlim, vmax=vlim, shading="auto", zorder=2)
    draw_terrain_box(ax_c, hatch=True)
    pm_c = ax_c.pcolormesh(lon2d, lat2d, hvtu, cmap=CMAP_DIVERGING, vmin=-vlim, vmax=vlim, shading="auto", zorder=2)
    panel_letter(ax_b, "b")
    panel_letter(ax_c, "c")
    cb_b = fig.colorbar(pm_b, ax=ax_b, pad=0.02, fraction=0.05)
    cb_b.set_label(r"$-V_T^L$ (m)", fontsize=8)
    cb_b.ax.tick_params(labelsize=7.5)
    cb_c = fig.colorbar(pm_c, ax=ax_c, pad=0.02, fraction=0.05)
    cb_c.set_label(r"$-V_T^U$ (m)", fontsize=8)
    cb_c.ax.tick_params(labelsize=7.5)

    # (d) HCPSclass -- the joint Hart CPS class. Needs a steering flow
    # and a coriolis pseudo-field that
    # HVTL/HVTU do not: a uniform 8 m/s westerly everywhere (the figure's
    # own spec -- uniform steering is enough to demonstrate the class,
    # since the point here is B's sign/magnitude relative to the 10 m
    # line, not a realistic storm motion) and coriolis from this grid's
    # own latitude. cps_HartCPS.gradient_2d (used inside parameter_b_grid)
    # needs to know this synthetic grid's rows increase northward, same
    # reason Figure 4/7 set this.
    cps_HartCPS.ORIENTATION_MODE = 0
    u_steer_fig3 = np.full(lat2d.shape, 8.0)
    v_steer_fig3 = np.zeros_like(u_steer_fig3)
    coriolis_fig3 = 2.0 * OMEGA_EARTH * np.sin(np.radians(lat2d))
    cat = cps_HartCPS.executeHartClass(
        z_std_stack[1000.0], z_std_stack[925.0], z_std_stack[850.0], z_std_stack[700.0],
        z_std_stack[500.0], z_std_stack[400.0], z_std_stack[300.0],
        u_steer_fig3, v_steer_fig3, u_steer_fig3, v_steer_fig3,
        u_steer_fig3, v_steer_fig3, u_steer_fig3, v_steer_fig3,
        psfc, coriolis_fig3, dx2d, dy_m,
    )
    i_a, j_a = nearest_index(lat_vals, lon_vals, VORTEX_A["lat"], VORTEX_A["lon"])
    i_b, j_b = nearest_index(lat_vals, lon_vals, VORTEX_B["lat"], VORTEX_B["lon"])
    print(f"Figure 3(d) HCPSclass at vortex A ({VORTEX_A['lat']:.0f}N {abs(VORTEX_A['lon']):.0f}W): {cat[i_a, j_a]!r}")
    print(f"Figure 3(d) HCPSclass at vortex B ({VORTEX_B['lat']:.0f}N {abs(VORTEX_B['lon']):.0f}W): {cat[i_b, j_b]!r}")

    draw_terrain_box(ax_d)
    pm_d = ax_d.pcolormesh(lon2d, lat2d, cat, cmap=CMAP_HARTCLASS, norm=NORM_HARTCLASS, shading="auto", zorder=2)
    ax_d.contour(lon2d, lat2d, z1000, levels=np.arange(np.floor(z1000.min() / 20) * 20, z1000.max() + 20, 20), colors="#8a8a86", linewidths=0.35, zorder=3)
    panel_letter(ax_d, "d")
    cb_d = fig.colorbar(pm_d, ax=ax_d, pad=0.02, fraction=0.05, ticks=range(7))
    cb_d.ax.set_yticklabels(HARTCLASS_NAMES, fontsize=6.2)

    fig.savefig(OUT_DIR / "fig3_gridded.png")
    plt.close(fig)


# ===========================================================================
# Figure 4: the Hart family alone on a vertically tilted cold-core
# cyclone (Vortex B) -- HVTL, HVTU and HCPSclass, all from cps_HartCPS.py,
# evaluated at the surface-level center even though the vortex's own
# upper-level center has moved several grid points away.
# ===========================================================================

OMEGA_EARTH = 7.2921159e-5
G_ACCEL = 9.81


def geostrophic_wind(z, dx2d, dy_m, f):
    dzdy = np.gradient(z, axis=0) / dy_m
    dzdx = np.gradient(z, axis=1) / dx2d
    u = -(G_ACCEL / f) * dzdy
    v = (G_ACCEL / f) * dzdx
    return u, v


def _fig4_fields(lat2d, lon2d, dx2d, dy_m, tilt_km):
    """Height fields (1000-300 hPa) and their geostrophic winds (850,
    700, 500, 300 hPa) for Figure 4's tilted cold-core cyclone (Vortex
    B), at the given 300 hPa tilt. A single, fixed f (this synthetic
    grid's own f at Vortex B's 50N) is used for every level's
    geostrophic wind, the same simplification the module docstring's
    "Grid" section already makes for this whole script's synthetic dx.
    """
    z1000 = height_field(lat2d, lon2d, 1000.0, tilt_km=tilt_km)
    z925 = height_field(lat2d, lon2d, 925.0, tilt_km=tilt_km)
    z850 = height_field(lat2d, lon2d, 850.0, tilt_km=tilt_km)
    z700 = height_field(lat2d, lon2d, 700.0, tilt_km=tilt_km)
    z500 = height_field(lat2d, lon2d, 500.0, tilt_km=tilt_km)
    z400 = height_field(lat2d, lon2d, 400.0, tilt_km=tilt_km)
    z300 = height_field(lat2d, lon2d, 300.0, tilt_km=tilt_km)

    f50 = 2.0 * OMEGA_EARTH * np.sin(np.radians(50.0))
    u850, v850 = geostrophic_wind(z850, dx2d, dy_m, f50)
    u700, v700 = geostrophic_wind(z700, dx2d, dy_m, f50)
    u500, v500 = geostrophic_wind(z500, dx2d, dy_m, f50)
    u300, v300 = geostrophic_wind(z300, dx2d, dy_m, f50)

    return dict(
        z1000=z1000, z925=z925, z850=z850, z700=z700, z500=z500, z400=z400, z300=z300,
        u850=u850, v850=v850, u700=u700, v700=v700, u500=u500, v500=v500, u300=u300, v300=v300,
    )


def _fig4_hart_class(fields, lat2d, dx2d, dy_m, psfc, depth_m):
    """HCPSclass for Figure 4's fields, with closed_low_mask's own depth
    threshold overridden to `depth_m` -- see make_fig4's own report for
    why this figure's synthetic low needs a lower value than
    cps_HartCPS.DEFAULT_DEPTH_M. Everything else matches Figure 7's own
    executeHartClass call: the same constants, and coriolis from this
    grid's own latitude.
    """
    coriolis = 2.0 * OMEGA_EARTH * np.sin(np.radians(lat2d))
    return cps_HartCPS.executeHartClass(
        fields["z1000"], fields["z925"], fields["z850"], fields["z700"],
        fields["z500"], fields["z400"], fields["z300"],
        fields["u850"], fields["v850"], fields["u700"], fields["v700"],
        fields["u500"], fields["v500"], fields["u300"], fields["v300"],
        psfc, coriolis, dx2d, dy_m,
        500.0, cps_HartCPS.B_THRESHOLD_M, cps_HartCPS.HART_B_LAYER_SCALE,
        depth_m, cps_HartCPS.DEFAULT_BLOB_RADIUS_KM, 900.0,
    )


def make_fig4(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, psfc):
    """Figure 4: Vortex B, its 300 hPa center displaced DEFAULT_TILT_KM
    (or further, if that is not yet enough -- see below) west of its own
    surface-level center. HVTL, HVTU and HCPSclass are all evaluated at
    the *surface-level* center, to show that cps_HartCPS.py's whole-depth
    diagnostics still read cold core there even though the vortex's own
    upper-level center has moved several grid points away.

    The surface pressure is uniform ocean here: this figure isolates the
    effect of tilt, so the synthetic terrain block used by Figure 3 is
    not included (its edge would otherwise sit inside the map window).
    """
    psfc = np.full(lat2d.shape, PSFC_OCEAN_HPA)  # flat ocean, see docstring
    cps_HartCPS.ORIENTATION_MODE = 0  # rows increase northward on this synthetic grid

    iC, jC = nearest_index(lat_vals, lon_vals, VORTEX_B["lat"], VORTEX_B["lon"])

    # A box around Vortex B's own nominal location, wide enough to hold
    # its 300 hPa center at either candidate tilt below, but far enough
    # from the domain edges that the background meridional gradient
    # (which keeps falling northward across the whole grid) cannot be
    # mistaken for the vortex's own minimum.
    near_b = (
        (lat2d >= VORTEX_B["lat"] - 8.0) & (lat2d <= VORTEX_B["lat"] + 8.0)
        & (lon2d >= VORTEX_B["lon"] - 12.0) & (lon2d <= VORTEX_B["lon"] + 4.0)
    )

    tilt_km = DEFAULT_TILT_KM
    fields = i300 = j300 = displacement_km = None
    for attempt_tilt in (DEFAULT_TILT_KM, 600.0):
        fields = _fig4_fields(lat2d, lon2d, dx2d, dy_m, attempt_tilt)
        z300_near = np.where(near_b, fields["z300"], np.nan)
        i300, j300 = np.unravel_index(np.nanargmin(z300_near), z300_near.shape)
        col_shift = jC - j300  # positive: the 300 hPa center sits west of the surface center
        displacement_km = float(haversine_km(lat_vals[iC], lon_vals[jC], lat_vals[i300], lon_vals[j300]))
        displaced_enough = col_shift >= 3
        tilt_km = attempt_tilt
        print(
            f"Figure 4 tilt check: tilt={attempt_tilt:.0f} km: 300 hPa center is "
            f"{displacement_km:.0f} km ({col_shift} grid columns) west of the surface "
            f"center; displaced_enough={displaced_enough}"
        )
        if displaced_enough:
            break

    hvtl = cps_HartCPS.executeBand3(
        fields["z925"], fields["z850"], fields["z700"], psfc, dx2d, dy_m,
        500.0, 925.0, 850.0, 700.0,
    )
    hvtu = cps_HartCPS.executeBand3(
        fields["z500"], fields["z400"], fields["z300"], psfc, dx2d, dy_m,
        500.0, 500.0, 400.0, 300.0,
    )

    depth_m_used = cps_HartCPS.DEFAULT_DEPTH_M
    hart_cls = _fig4_hart_class(fields, lat2d, dx2d, dy_m, psfc, depth_m_used)
    if not np.isfinite(hart_cls[iC, jC]):
        # closed_low_mask's own DEFAULT_DEPTH_M (40 m) test compares the
        # point's height against the mean height of the annulus between
        # MIN_RADIUS_KM and RADIUS_KM (300-500 km) around it. Vortex B's
        # own e-folding scale is 350 km, close enough to that annulus
        # that the ring mean is still well down inside the vortex's own
        # depression rather than sitting on the surrounding background,
        # so the annulus-minus-center depth comes back under 40 m even
        # though this is a real, closed low. A lower depthM, applied
        # here only, is what a low this broad relative to the mask's
        # own annulus needs; cps_HartCPS.DEFAULT_DEPTH_M itself is left
        # unchanged, since a real analyzed low is deep enough that the
        # shipped 40 m default is no obstacle.
        depth_m_used = 15.0
        hart_cls = _fig4_hart_class(fields, lat2d, dx2d, dy_m, psfc, depth_m_used)
        print(
            f"  HCPSclass at the surface center is NaN at cps_HartCPS.DEFAULT_DEPTH_M "
            f"({cps_HartCPS.DEFAULT_DEPTH_M:.0f} m); re-evaluated for this figure only "
            f"at depthM={depth_m_used:.0f} m."
        )

    fig, axes = plt.subplots(2, 2, figsize=(FULL_WIDTH_IN, 6.0), constrained_layout=True)
    fig.get_layout_engine().set(h_pad=0.06, w_pad=0.04, hspace=0.02, wspace=0.02)
    (ax_a, ax_b), (ax_c, ax_d) = axes

    lon_min, lon_max = -155.0, -125.0
    lat_min, lat_max = 35.0, 62.0
    for ax in (ax_a, ax_b, ax_c, ax_d):
        style_map_axes(ax, lon_min, lon_max, lat_min, lat_max)

    clat, clon = VORTEX_B["lat"], VORTEX_B["lon"]
    clat300, clon300 = lat_vals[i300], lon_vals[j300]

    def mark_center(ax, label):
        ax.plot(clon, clat, marker="+", markersize=11, markeredgewidth=2.2, color="black", zorder=10)
        # Always offset down-left of the plus: every panel has a colorbar
        # hugging its right edge, so this keeps the label clear of both.
        ax.annotate(
            label,
            (clon, clat),
            textcoords="offset points",
            xytext=(-10, -16),
            ha="right",
            va="top",
            fontsize=7.5,
            color=TEXT_DARK,
            zorder=11,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=1.2),
        )

    # (a) tilt geometry alone: 925 hPa (solid) and 300 hPa (dashed)
    # height contours, the two level centers, and the displacement
    # between them -- no HVTL/HVTU/class field, so the reader sees the
    # tilt itself before any diagnostic built on top of it.
    ax_a.contour(lon2d, lat2d, fields["z925"], levels=12, colors=TEXT_DARK, linewidths=0.8, linestyles="solid", zorder=2)
    ax_a.contour(lon2d, lat2d, fields["z300"], levels=12, colors=VORTEX_B_COLOR, linewidths=1.1, linestyles="dashed", zorder=3)
    ax_a.plot(clon, clat, marker="+", markersize=11, markeredgewidth=2.2, color="black", zorder=10)
    ax_a.plot(clon300, clat300, marker="o", markersize=8, markerfacecolor="none", markeredgecolor=VORTEX_B_COLOR, markeredgewidth=1.8, zorder=10)
    ax_a.annotate(
        "",
        xy=(clon300, clat300),
        xytext=(clon, clat),
        arrowprops=dict(arrowstyle="->", color=TEXT_SECONDARY, linewidth=1.3, shrinkA=6, shrinkB=6),
        zorder=9,
    )
    ax_a.annotate(
        f"{displacement_km:.0f} km",
        (0.5 * (clon + clon300), 0.5 * (clat + clat300)),
        textcoords="offset points",
        xytext=(8, 6),
        fontsize=7.5,
        color=TEXT_DARK,
        zorder=11,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=1.0),
    )
    legend_handles = [
        Line2D([0], [0], color=TEXT_DARK, linewidth=1.4, label="925 hPa"),
        Line2D([0], [0], color=VORTEX_B_COLOR, linewidth=1.4, linestyle="--", label="300 hPa"),
        Line2D([0], [0], marker="+", color="black", markersize=9, markeredgewidth=2.0, linewidth=0, label="surface center"),
        Line2D([0], [0], marker="o", markerfacecolor="none", markeredgecolor=VORTEX_B_COLOR, markersize=7, markeredgewidth=1.6, linewidth=0, label="300 hPa center"),
    ]
    ax_a.legend(handles=legend_handles, loc="lower left", frameon=True, framealpha=0.85, edgecolor="none", fontsize=6.8)
    panel_letter(ax_a, "a")

    # (b) HVTL, (c) HVTU -- identical +/- range so the two panels read
    # on the same scale.
    hart_lim = float(np.nanmax(np.abs(np.concatenate([hvtl.ravel(), hvtu.ravel()]))))
    hart_lim = max(hart_lim, 1.0)

    pm_b = ax_b.pcolormesh(lon2d, lat2d, hvtl, cmap=CMAP_DIVERGING, vmin=-hart_lim, vmax=hart_lim, shading="auto", zorder=2)
    mark_center(ax_b, f"at center: {'+' if hvtl[iC, jC] >= 0 else '-'}{abs(float(hvtl[iC, jC])):.0f} m")
    panel_letter(ax_b, "b")
    cb_b = fig.colorbar(pm_b, ax=ax_b, pad=0.02, fraction=0.05)
    cb_b.set_label(r"$-V_T^L$ (m)", fontsize=8)
    cb_b.ax.tick_params(labelsize=7.5)

    pm_c = ax_c.pcolormesh(lon2d, lat2d, hvtu, cmap=CMAP_DIVERGING, vmin=-hart_lim, vmax=hart_lim, shading="auto", zorder=2)
    mark_center(ax_c, f"at center: {'+' if hvtu[iC, jC] >= 0 else '-'}{abs(float(hvtu[iC, jC])):.0f} m")
    panel_letter(ax_c, "c")
    cb_c = fig.colorbar(pm_c, ax=ax_c, pad=0.02, fraction=0.05)
    cb_c.set_label(r"$-V_T^U$ (m)", fontsize=8)
    cb_c.ax.tick_params(labelsize=7.5)

    # (d) HCPSclass
    cls_c = float(hart_cls[iC, jC])
    cls_label = f"{cls_c:.0f}" if np.isfinite(cls_c) else "NaN"
    pm_d = ax_d.pcolormesh(lon2d, lat2d, hart_cls, cmap=CMAP_HARTCLASS, norm=NORM_HARTCLASS, shading="auto", zorder=2)
    ax_d.contour(lon2d, lat2d, fields["z1000"], levels=12, colors="#8a8a86", linewidths=0.35, zorder=3)
    mark_center(ax_d, f"at center: class {cls_label}")
    panel_letter(ax_d, "d")
    cb_d = fig.colorbar(pm_d, ax=ax_d, pad=0.02, fraction=0.05, ticks=range(7))
    cb_d.ax.set_yticklabels(HARTCLASS_NAMES, fontsize=6.2)

    fig.savefig(OUT_DIR / "fig4_tilt.png")
    plt.close(fig)

    center_values = dict(
        hvtl_center=float(hvtl[iC, jC]),
        hvtu_center=float(hvtu[iC, jC]),
        class_center=cls_c,
        tilt_km=tilt_km,
        displacement_km=displacement_km,
        depth_m_used=depth_m_used,
    )
    return center_values


# ===========================================================================
# Figure 5: performance
# ===========================================================================


def random_smooth_field(shape, rng, base=5000.0, amp=60.0):
    """Cheap O(N) smooth-ish random field: a double running sum of noise
    (a discrete Brownian sheet), normalized -- smooth on grid scales
    without a convolution pass.
    """
    steps = rng.standard_normal(shape).astype(np.float64)
    field = np.cumsum(steps, axis=0)
    field = np.cumsum(field, axis=1)
    field -= field.mean()
    std = field.std()
    if std > 0:
        field = field / std * amp
    return base + field


def _time_execute_hart_class(ny, nx, rng):
    lat_vals = np.linspace(-90.0, 90.0, ny)
    lon_vals = np.linspace(0.0, 360.0, nx, endpoint=False)
    lon2d, lat2d = np.meshgrid(lon_vals, lat_vals)
    dlat_rad = np.radians(180.0 / (ny - 1))
    dlon_rad = np.radians(360.0 / nx)
    dy_m = EARTH_RADIUS_KM * 1000.0 * dlat_rad
    dx2d = EARTH_RADIUS_KM * 1000.0 * dlon_rad * np.cos(np.radians(lat2d))

    levels = STANDARD_LEVELS
    z = {p: random_smooth_field((ny, nx), rng, base=z_std(p)) for p in levels}
    psfc = np.full((ny, nx), PSFC_OCEAN_HPA)
    u_steer = np.full((ny, nx), 8.0)
    v_steer = np.zeros((ny, nx))
    coriolis = 2.0 * OMEGA_EARTH * np.sin(np.radians(lat2d))

    t0 = time.perf_counter()
    cps_HartCPS.executeHartClass(
        z[1000.0], z[925.0], z[850.0], z[700.0], z[500.0], z[400.0], z[300.0],
        u_steer, v_steer, u_steer, v_steer, u_steer, v_steer, u_steer, v_steer,
        psfc, coriolis, dx2d, dy_m,
    )
    return time.perf_counter() - t0


def make_fig5():
    rng = np.random.default_rng(20260917)
    sizes = [(181, 360), (361, 720), (721, 1440)]
    labels = ["181×360\n(1°)", "361×720\n(0.5°)", "721×1440\n(0.25°)"]
    medians = []
    for ny, nx in sizes:
        runs = [_time_execute_hart_class(ny, nx, rng) for _ in range(3)]
        med = float(np.median(runs))
        medians.append(med)
        print(f"executeHartClass timing, {ny}x{nx}: runs={[f'{r:.3f}' for r in runs]} s, median={med:.3f} s")

    fig, ax = plt.subplots(figsize=(HALF_WIDTH_IN, 3.1))
    xs = np.arange(len(sizes))
    ax.plot(xs, medians, marker="o", markersize=6.5, color=VORTEX_B_COLOR, linewidth=1.8, markerfacecolor=VORTEX_B_COLOR, markeredgecolor="white", markeredgewidth=0.6, zorder=5)
    for x, m in zip(xs, medians):
        # To the right of the marker, so the label clears both the line
        # and the y-axis tick labels (the first point sits low, right by
        # the "0.0"/"0.2" ticks).
        ax.annotate(f"{m:.2f} s", (x, m), textcoords="offset points", xytext=(10, 6), ha="left", fontsize=8, color=TEXT_DARK)

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_xlim(-0.3, len(sizes) - 1 + 0.55)
    ax.set_ylim(0, max(medians) * 1.35)
    ax.set_ylabel("wall-clock time (s)")
    ax.grid(True, axis="y", color=GRID_COLOR, linewidth=0.5)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig5_performance.png")
    plt.close(fig)
    return dict(zip(["181x360", "361x720", "721x1440"], medians))


# ===========================================================================
# Figure 6: CAVE photograph -- crop / resize only, no synthetic content
# ===========================================================================


def make_fig6():
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not available; skipping fig6_cave_typhoon.jpg")
        return

    if not UPLOAD_PHOTO.exists():
        print(f"Photo not found at {UPLOAD_PHOTO}; skipping fig6_cave_typhoon.jpg")
        return

    im = Image.open(UPLOAD_PHOTO)
    w, h = im.size
    box = (int(0.03 * w), int(0.21 * h), int(0.95 * w), int(0.92 * h))
    cropped = im.crop(box)
    new_w = 1600
    new_h = int(round(cropped.size[1] * new_w / cropped.size[0]))
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)
    resized.convert("RGB").save(OUT_DIR / "fig6_cave_typhoon.jpg", "JPEG", quality=85)
    print(f"fig6_cave_typhoon.jpg written, {new_w}x{new_h}, cropped from box {box} of {w}x{h}")


# ===========================================================================
# Figure 7: Parameter B and the ET stage (transitioning-storm case)
# ===========================================================================

# cps_HartCPS.ORIENTATION_MODE = 0 is set inside make_fig4 (above); that is
# a real mutation of the imported module's attribute, so it is still in
# effect here (make_fig7 runs after make_fig4 in main()). Set again here
# anyway, defensively, so this function is correct even if called on its
# own.

FIG7_VORTEX_A2_LAT, FIG7_VORTEX_A2_LON = 42.0, -140.0
FIG7_THICKNESS_GRADIENT_M_PER_1000KM = 40.0  # 925-700 hPa thickness, decreasing northward
FIG7_STEERING_WESTERLY_MS = 12.0   # north of 35N
FIG7_STEERING_EASTERLY_MS = -6.0   # south of 25N (negative = easterly, i.e. blowing from the east)
FIG7_STEERING_BLEND_CENTER_LAT = 30.0
FIG7_STEERING_BLEND_WIDTH_DEG = 3.0
# A small, short-lived poleward turn superimposed only on the blend itself
# (a Gaussian in latitude, centered on the same blend and negligible by the
# time either vortex center is reached -- see fig7_steering_v): physically,
# a storm recurving from easterly to westerly steering does not reverse
# through a dead calm along a single compass line, it turns, and
# mathematically this is also what keeps parameter_b_grid's right-hand
# normal -- a unit vector -- sweeping smoothly through the intermediate
# directions between "due south" and "due north" instead of jumping
# straight from one to the other. Without it the steering reversal is
# still smooth in speed and direction *separately*, but B (which depends
# on the normal's direction alone, not the steering's speed) would still
# flip sign in a single grid step with no valid B=10 m crossing to draw.
FIG7_STEERING_TURN_MS = 2.5
FIG7_STEERING_TURN_WIDTH_DEG = 1.2

#: Colors reused for Hart's own Phase 1 diagram quadrants (panel (d) of
#: this figure, and Figure 10) -- a schematic of Hart's own B-vs-VTL
#: plot; three colors borrowed from CATEGORY_COLORS purely
#: for visual consistency with the rest of this script's palette.
STAGE_COLORS = [CATEGORY_COLORS[2], CATEGORY_COLORS[3], CATEGORY_COLORS[1]]  # pale gray, orange, blue


def fig7_rate_per_1000km(p):
    """Meridional rate (m per 1000 km) of Figure 7's own background
    height gradient at pressure p: 0 at 925 hPa, FIG7_THICKNESS_GRADIENT_
    M_PER_1000KM at 700 hPa, linear in ln(p) (same style as
    _linear_in_lnp/meridional_gradient_m) and extended by that same line
    to 1000 and 850 hPa, so every level cps_HartCPS needs for this figure
    gets one smooth background rather than a rate that jumps between
    just two levels. The *difference* rate(700) - rate(925) is what sets
    the 925-700 hPa thickness gradient; extending it smoothly to 1000/850
    hPa only matters for HVTL and the closed-low mask, not for B itself.

    Above 700 hPa (500/400/300 hPa, needed for HVTU/HCPSclass since this
    figure also reports the joint class, not just B and VTL) the rate is
    held flat at
    its own 700 hPa value rather than continuing the same line: the
    raised background here represents a *low-level* baroclinic zone (a
    frontal environment near the surface), and letting the line
    extrapolate unclamped to 300 hPa would quadruple it by then (about
    160 m/1000 km), swamping the vortex's own upper-level warm-core
    signal and flipping HVTU negative for reasons that have nothing to
    do with the transition being demonstrated.
    """
    rate_700 = _linear_in_lnp(700.0, 925.0, 0.0, 700.0, FIG7_THICKNESS_GRADIENT_M_PER_1000KM)
    if p <= 700.0:
        return rate_700
    return _linear_in_lnp(p, 925.0, 0.0, 700.0, FIG7_THICKNESS_GRADIENT_M_PER_1000KM)


def fig7_gradient_offset_m(lat2d, p):
    """Height offset (m) for Figure 7's own, deliberately raised
    background: decreasing northward from the grid's south edge at
    fig7_rate_per_1000km(p) -- independent of, and much stronger than,
    meridional_gradient_m's modest background every other figure uses
    (that one keeps ambient HVTL/HVTU inside the diverging colormap's
    neutral band; this one instead represents a transitioning storm's
    own baroclinic environment -- see this script's module docstring,
    "Figure 7", and the article's Section 2).
    """
    rate = fig7_rate_per_1000km(p)
    y_km = (lat2d - LAT_MIN) * 111.2
    return -rate * (y_km / 1000.0)


def fig7_height_field(lat2d, lon2d, p):
    """Z(p) (m) for Figure 7: z_std(p) plus fig7_gradient_offset_m(p),
    minus two independent copies of vortex A's own Gaussian depression
    (identical amplitude profile, vortex_a_amp -- see VORTEX_A) -- one at
    vortex A's usual center (28N 130W), one at (FIG7_VORTEX_A2_LAT,
    FIG7_VORTEX_A2_LON) (42N 140W). No vortex B, no terrain: Figure 7
    passes a uniform 1013 hPa psfc, per the figure's own spec.
    """
    z = z_std(p) + fig7_gradient_offset_m(lat2d, p)
    amp = vortex_a_amp(p)
    r1 = haversine_km(lat2d, lon2d, VORTEX_A["lat"], VORTEX_A["lon"])
    z = z - amp * np.exp(-(r1 / VORTEX_A["scale_km"]) ** 2)
    r2 = haversine_km(lat2d, lon2d, FIG7_VORTEX_A2_LAT, FIG7_VORTEX_A2_LON)
    z = z - amp * np.exp(-(r2 / VORTEX_A["scale_km"]) ** 2)
    return z


def fig7_steering_u(lat2d):
    """Zonal steering wind (m/s) for Figure 7: FIG7_STEERING_EASTERLY_MS
    (negative, i.e. blowing from the east) south of 25N,
    FIG7_STEERING_WESTERLY_MS (positive) north of 35N, a smooth tanh
    blend of the two centered on FIG7_STEERING_BLEND_CENTER_LAT. The
    meridional component is always 0 -- both regimes, and the blend
    between them, are purely zonal.
    """
    mid = 0.5 * (FIG7_STEERING_WESTERLY_MS + FIG7_STEERING_EASTERLY_MS)
    half_range = 0.5 * (FIG7_STEERING_WESTERLY_MS - FIG7_STEERING_EASTERLY_MS)
    return mid + half_range * np.tanh((lat2d - FIG7_STEERING_BLEND_CENTER_LAT) / FIG7_STEERING_BLEND_WIDTH_DEG)


def fig7_steering_v(lat2d):
    """Meridional steering wind (m/s) for Figure 7: 0 in both the pure
    easterly and pure westerly regimes, rising to FIG7_STEERING_TURN_MS
    only in a narrow Gaussian centered on FIG7_STEERING_BLEND_CENTER_LAT
    -- see FIG7_STEERING_TURN_MS's own comment for why the reversal turns
    briefly rather than passing straight through a due-east/due-west
    flip.
    """
    return FIG7_STEERING_TURN_MS * np.exp(-((lat2d - FIG7_STEERING_BLEND_CENTER_LAT) / FIG7_STEERING_TURN_WIDTH_DEG) ** 2)


def _interp_crossing(traj, key, target):
    """First point along polyline `traj` (an (N,2) array of (B, VTL)
    pairs, in trajectory order) where column `key` (0 for B, 1 for VTL)
    crosses `target`, by linear interpolation between the two points
    that bracket it. Returns (B, VTL) at the crossing, or None if the
    column never crosses `target` between consecutive points.
    """
    for k in range(traj.shape[0] - 1):
        a, b = traj[k, key], traj[k + 1, key]
        if (a - target) == 0:
            return tuple(traj[k])
        if (a - target) * (b - target) < 0:
            frac = (target - a) / (b - a)
            return tuple(traj[k] + frac * (traj[k + 1] - traj[k]))
    return None


def make_fig7(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m):
    cps_HartCPS.ORIENTATION_MODE = 0  # rows increase northward on this synthetic grid

    center1 = (VORTEX_A["lat"], VORTEX_A["lon"])
    center2 = (FIG7_VORTEX_A2_LAT, FIG7_VORTEX_A2_LON)

    z1000 = fig7_height_field(lat2d, lon2d, 1000.0)
    z925 = fig7_height_field(lat2d, lon2d, 925.0)
    z850 = fig7_height_field(lat2d, lon2d, 850.0)
    z700 = fig7_height_field(lat2d, lon2d, 700.0)
    z500 = fig7_height_field(lat2d, lon2d, 500.0)
    z400 = fig7_height_field(lat2d, lon2d, 400.0)
    z300 = fig7_height_field(lat2d, lon2d, 300.0)
    thickness = z700 - z925

    psfc = np.full(lat2d.shape, 1013.0)
    u_steer = fig7_steering_u(lat2d)
    v_steer = fig7_steering_v(lat2d)
    coriolis = 2.0 * OMEGA_EARTH * np.sin(np.radians(lat2d))

    hb = cps_HartCPS.executeB(
        z925, z700,
        u_steer, v_steer, u_steer, v_steer, u_steer, v_steer, u_steer, v_steer,
        psfc, coriolis, dx2d, dy_m,
        500.0, cps_HartCPS.HART_B_LAYER_SCALE, 900.0,
    )
    vtl = cps_HartCPS.thermal_wind_grid(
        [z925, z850, z700], cps_HartCPS.LOWER_BAND, dx2d, dy_m, cps_HartCPS.RADIUS_KM,
        psfc_hpa=psfc, cap_hpa=900.0,
    )
    hart_cls = cps_HartCPS.executeHartClass(
        z1000, z925, z850, z700, z500, z400, z300,
        u_steer, v_steer, u_steer, v_steer, u_steer, v_steer, u_steer, v_steer,
        psfc, coriolis, dx2d, dy_m,
        500.0, cps_HartCPS.B_THRESHOLD_M, cps_HartCPS.HART_B_LAYER_SCALE,
        cps_HartCPS.DEFAULT_DEPTH_M, cps_HartCPS.DEFAULT_BLOB_RADIUS_KM, 900.0,
    )

    i1, j1 = nearest_index(lat_vals, lon_vals, center1[0], center1[1])
    i2, j2 = nearest_index(lat_vals, lon_vals, center2[0], center2[1])
    b1, b2 = float(hb[i1, j1]), float(hb[i2, j2])
    vtl1, vtl2 = float(vtl[i1, j1]), float(vtl[i2, j2])
    cls1, cls2 = float(hart_cls[i1, j1]), float(hart_cls[i2, j2])

    print("Figure 7 (Parameter B and the joint class), synthetic transitioning-storm case:")
    print(f"  925-700 hPa thickness gradient used: {FIG7_THICKNESS_GRADIENT_M_PER_1000KM:.0f} m per 1000 km, decreasing northward")
    print(f"  vortex A,  28N 130W, easterly steering ({FIG7_STEERING_EASTERLY_MS:+.0f} m/s far south): B = {b1:+.1f} m, -V_T^L = {vtl1:+.1f} m, HCPSclass = {cls1:.0f}")
    print(f"  vortex A', 42N 140W, westerly steering ({FIG7_STEERING_WESTERLY_MS:+.0f} m/s far north): B = {b2:+.1f} m, -V_T^L = {vtl2:+.1f} m, HCPSclass = {cls2:.0f}")
    print(
        "  sign reasoning: thickness is largest (warmest) toward the south domain edge "
        "everywhere. Vortex A' moves east (westerly steering): facing east, its right side "
        "faces south, the warm side, so B is positive. Vortex A moves west (easterly "
        "steering): facing west, its right side faces north, the cold side, so B is "
        "negative. Both vortices are the identical warm core (same amplitude, same scale); "
        "only the ambient thickness gradient and the direction of motion set B's sign."
    )
    onset_ok = b2 > cps_HartCPS.B_THRESHOLD_M
    cold_ok = b1 < -cps_HartCPS.B_THRESHOLD_M
    print(
        f"  check: westerly B ({b2:+.1f} m) > {cps_HartCPS.B_THRESHOLD_M:.0f} m onset threshold: {onset_ok}; "
        f"easterly B ({b1:+.1f} m) < -{cps_HartCPS.B_THRESHOLD_M:.0f} m: {cold_ok}"
    )
    if not (onset_ok and cold_ok):
        print("  WARNING: gradient too weak to clear the 10 m threshold comfortably on both sides.")
    class_ok = (cls1 == 0.0) and (cls2 == 2.0)
    print(
        f"  check: HCPSclass at A is {cls1:.0f} (expect 0, symmetric deep warm core) and at "
        f"A' is {cls2:.0f} (expect 2, frontal deep warm core): {class_ok}"
    )
    if not class_ok:
        print("  WARNING: HCPSclass at A/A' did not land on the expected 0/2 codes.")

    fig, axes = plt.subplots(2, 2, figsize=(FULL_WIDTH_IN, 7.6), constrained_layout=True)
    fig.get_layout_engine().set(h_pad=0.08, w_pad=0.06, hspace=0.04, wspace=0.04)
    (ax_a, ax_b), (ax_c, ax_d) = axes

    for ax in (ax_a, ax_b, ax_c):
        style_map_axes(ax, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)

    def mark_vortex_centers(ax):
        for (clat, clon), label, dxo, dyo in (
            (center1, "A", 8, 8),
            (center2, "A′", 8, 8),
        ):
            ax.plot(clon, clat, marker="o", markersize=7, markerfacecolor="white", markeredgecolor=TEXT_DARK, markeredgewidth=1.3, zorder=9)
            ax.annotate(label, (clon, clat), textcoords="offset points", xytext=(dxo, dyo), fontsize=8, fontweight="bold", color=TEXT_DARK, zorder=10)

    # --- (a) 925-700 hPa thickness + steering arrows ------------------------
    levels_a = np.arange(np.floor(thickness.min() / 20) * 20, thickness.max() + 20, 20)
    cf_a = ax_a.contourf(lon2d, lat2d, thickness, levels=levels_a, cmap=CMAP_SEQ_BLUE, zorder=1)
    ax_a.contour(lon2d, lat2d, thickness, levels=levels_a, colors=TEXT_SECONDARY, linewidths=0.5, zorder=2)
    step = 7
    ax_a.quiver(
        lon2d[::step, ::step], lat2d[::step, ::step],
        u_steer[::step, ::step], v_steer[::step, ::step],
        color=TEXT_SECONDARY, angles="uv", scale_units="xy", scale=4.5,
        width=0.006, headwidth=4.0, zorder=6,
    )
    ax_a.text(
        LON_MAX - 1.0, LAT_MIN + 1.5,
        f"steering: {FIG7_STEERING_EASTERLY_MS:.0f} to {FIG7_STEERING_WESTERLY_MS:.0f} m/s",
        fontsize=7, color=TEXT_SECONDARY, ha="right", va="bottom", style="italic",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=1.0), zorder=6,
    )
    mark_vortex_centers(ax_a)
    cb_a = fig.colorbar(cf_a, ax=ax_a, pad=0.02, fraction=0.05)
    cb_a.set_label("925-700 hPa thickness (m)", fontsize=8)
    cb_a.ax.tick_params(labelsize=7.5)
    panel_letter(ax_a, "a")

    # --- (b) HB (parameter B) ------------------------------------------------
    hb_lim = 30.0
    pm_b = ax_b.pcolormesh(lon2d, lat2d, hb, cmap=CMAP_DIVERGING, vmin=-hb_lim, vmax=hb_lim, shading="auto", zorder=2)
    ax_b.contour(lon2d, lat2d, hb, levels=[cps_HartCPS.B_THRESHOLD_M], colors=TEXT_DARK, linewidths=1.4, zorder=5)
    # Manual label, away from vortex A's marker: near the west edge of the
    # domain, at the same latitude the B=10 m line actually crosses there
    # (found by scanning a column far from both vortices, rather than
    # matplotlib's automatic clabel, which kept landing on top of vortex A).
    label_lon = LON_MIN + 5.0
    j_label = nearest_index(lat_vals, lon_vals, LAT_MIN, label_lon)[1]
    label_lat = _interp_crossing(np.column_stack([hb[:, j_label], lat_vals]), 0, cps_HartCPS.B_THRESHOLD_M)
    if label_lat is not None:
        ax_b.text(
            label_lon, label_lat[1] + 1.2, "B = 10 m", fontsize=7.5, color=TEXT_DARK,
            ha="left", va="bottom", zorder=6,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1.0),
        )
    mark_vortex_centers(ax_b)
    cb_b = fig.colorbar(pm_b, ax=ax_b, pad=0.02, fraction=0.05)
    cb_b.set_label("HB (m, 900-600 equivalent)", fontsize=8)
    cb_b.ax.tick_params(labelsize=7.5)
    panel_letter(ax_b, "b")

    # --- (c) HCPSclass ------------------------------------------------------
    pm_c = ax_c.pcolormesh(lon2d, lat2d, hart_cls, cmap=CMAP_HARTCLASS, norm=NORM_HARTCLASS, shading="auto", zorder=2)
    z1000_levels = np.arange(np.floor(z1000.min() / 20) * 20, z1000.max() + 20, 20)
    ax_c.contour(lon2d, lat2d, z1000, levels=z1000_levels, colors="#8a8a86", linewidths=0.35, zorder=3)
    mark_vortex_centers(ax_c)
    cb_c = fig.colorbar(pm_c, ax=ax_c, pad=0.02, fraction=0.05, ticks=range(7))
    cb_c.ax.set_yticklabels(HARTCLASS_NAMES, fontsize=6.2)
    panel_letter(ax_c, "c")

    # --- (d) Hart's Phase 1 diagram: B vs -V_T^L -----------------------------
    xlim = (min(-20.0, 1.15 * b1), 80.0)
    ylim = (-300.0, 300.0)
    ax_d.set_xlim(*xlim)
    ax_d.set_ylim(*ylim)

    quadrants = [
        (-1e4, cps_HartCPS.B_THRESHOLD_M, 0, 1e4, STAGE_COLORS[0], "symmetric\nwarm core"),
        (cps_HartCPS.B_THRESHOLD_M, 1e4, 0, 1e4, STAGE_COLORS[1], "asymmetric warm core"),
        (cps_HartCPS.B_THRESHOLD_M, 1e4, -1e4, 0, STAGE_COLORS[2], "asymmetric cold core"),
        (-1e4, cps_HartCPS.B_THRESHOLD_M, -1e4, 0, "#4a3aa7", "symmetric\ncold core"),
    ]
    for x0, x1, y0, y1, color, _ in quadrants:
        x0c, x1c = max(x0, xlim[0]), min(x1, xlim[1])
        y0c, y1c = max(y0, ylim[0]), min(y1, ylim[1])
        ax_d.add_patch(Rectangle((x0c, y0c), x1c - x0c, y1c - y0c, facecolor=color, alpha=0.30, edgecolor="none", zorder=0))

    label_pos = {
        # Lower part of the quadrant, well clear of the 0 h/24 h points
        # (which sit up near y=200-240) and of the trajectory itself.
        "symmetric\nwarm core": (-18, 25, "left"),
        "asymmetric warm core": (xlim[1] - 3, 260, "right"),
        "asymmetric cold core": (xlim[1] - 3, -190, "right"),
        "symmetric\ncold core": (0.5 * xlim[0], -230, "center"),
    }
    for _, _, _, _, _, label in quadrants:
        x, y, ha = label_pos[label]
        ax_d.text(x, y, label, color=TEXT_SECONDARY, fontsize=7.5, ha=ha, va="center", style="italic", zorder=1)

    ax_d.axhline(0, color=TEXT_DARK, linewidth=1.0, zorder=2)
    ax_d.axvline(cps_HartCPS.B_THRESHOLD_M, color=TEXT_DARK, linewidth=1.0, zorder=2)

    traj = np.array(
        [
            (3, 240), (6, 200), (12, 150), (25, 90),
            (40, 20), (45, -60), (35, -150), (20, -220),
        ],
        dtype=float,
    )
    hours = np.arange(0, 24 * traj.shape[0], 24)
    ax_d.plot(traj[:, 0], traj[:, 1], color=TEXT_SECONDARY, linewidth=2.0, zorder=5)
    for k, (x, y) in enumerate(traj):
        color = CMAP_SEQ_BLUE(k / (traj.shape[0] - 1))
        ax_d.plot(x, y, marker="o", markersize=7, markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.8, zorder=6)
        va, ha, dx_txt, dy_txt = "bottom", "left", 8, 10
        if k == traj.shape[0] - 1:
            dx_txt, dy_txt, va = 8, -14, "top"
        elif k == 0:
            # Directly to the left of its own point (not above it, which
            # pushed the label up against the top axis edge at y=240 on
            # a ylim topping out at 300).
            dx_txt, dy_txt, ha, va = -10, 0, "right", "center"
        elif hours[k] == 120:
            dx_txt, dy_txt = 16, 18  # clear of the "asymmetric cold core" label just above
        elif hours[k] == 72:
            # dy=0 instead of the default 10 -- the "A' (westerly)"
            # annotation now anchors at a fixed (32, 130) and reaches down
            # to about y=109, which the default's extra upward push
            # clipped into.
            dx_txt, dy_txt = 8, 0
        ax_d.annotate(f"{hours[k]} h", (x, y), textcoords="offset points", xytext=(dx_txt, dy_txt), fontsize=7.2, color=TEXT_SECONDARY, ha=ha, va=va)

    onset_xy = _interp_crossing(traj, 0, cps_HartCPS.B_THRESHOLD_M)
    completion_xy = _interp_crossing(traj, 1, 0.0)
    if onset_xy is not None:
        ax_d.plot(*onset_xy, marker="x", markersize=7, color=TEXT_DARK, markeredgewidth=1.6, zorder=7)
        ax_d.annotate(
            "onset: B > 10 m\n(Evans and Hart 2003)", onset_xy, textcoords="offset points",
            xytext=(34, 16), fontsize=7.0, color=TEXT_DARK, va="bottom", ha="left",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.0), zorder=7,
        )
    if completion_xy is not None:
        ax_d.plot(*completion_xy, marker="x", markersize=7, color=TEXT_DARK, markeredgewidth=1.6, zorder=7)
        ax_d.annotate(
            "completion: −V_T^L < 0", completion_xy, textcoords="offset points",
            xytext=(10, -28), fontsize=7.0, color=TEXT_DARK, va="top", ha="left",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.0), zorder=7,
        )

    # Fixed data-space anchors, not offsets from each diamond: after the
    # background-gradient clamp (see fig7_rate_per_1000km) both diamonds
    # sit close together around VTL=120 m, so an offset-from-point
    # placement put the two annotations on top of each other and on the
    # trajectory. A's label goes below-and-left of its own diamond;
    # A''s goes to the right of its own diamond, clear of both A's label
    # and the trajectory line between them.
    for (bval, vval), label, anchor, ha, va in (
        ((b1, vtl1), "A (easterly)", (-28, 90), "left", "top"),
        ((b2, vtl2), "A′ (westerly)", (32, 130), "left", "center"),
    ):
        ax_d.plot(bval, vval, marker="D", markersize=8, markerfacecolor=VORTEX_A_COLOR, markeredgecolor="white", markeredgewidth=1.0, zorder=9)
        ax_d.annotate(
            f"{label}\nB={bval:+.0f} m", (bval, vval), xytext=anchor, textcoords="data", ha=ha, va=va,
            fontsize=7.2, color=TEXT_DARK, fontweight="bold",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.0), zorder=9,
        )

    ax_d.set_xlabel("B (m)")
    ax_d.set_ylabel(r"$-V_T^L$  (m)")
    ax_d.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0.2)
    ax_d.tick_params(length=3)
    for spine in ax_d.spines.values():
        spine.set_linewidth(0.6)
    panel_letter(ax_d, "d")

    fig.savefig(OUT_DIR / "fig7_parameter_b.png")
    plt.close(fig)

    return dict(b1=b1, b2=b2, vtl1=vtl1, vtl2=vtl2)


# ===========================================================================
# Figure 8: the thermal wind concept, as a vertical cross-section
# ===========================================================================
#
# A(p) profiles for the two synthetic cores, linear in ln(p) between
# 1000 and 300 hPa (the same construction VORTEX_A/VORTEX_B use, but with
# the exact amplitudes this teaching figure's own spec calls for).

FIG8_WARM_AMP1000, FIG8_WARM_AMP300 = 250.0, 20.0   # warm core (panel a)
FIG8_COLD_AMP1000, FIG8_COLD_AMP300 = 100.0, 450.0  # cold core (panel b)
FIG8_SCALE_KM = 150.0
FIG8_XLIM_KM = 800.0
FIG8_CIRCLE_KM = 500.0
FIG8_CENTER_LAT, FIG8_CENTER_LON = 30.0, 0.0
FIG8_HALF_WIDTH_DEG = 6.0  # ~+/-667 km, safely past the 500 km circle

# Single vertical scale for both cross-section panels, in meters per
# ln(p) axis unit, chosen so 250 m (panel a's largest amplitude, at
# 1000 hPa) draws as about one third of the 1000-925 hPa tick spacing.
FIG8_LNP_UNIT_M = FIG8_WARM_AMP1000 / (np.log(1000.0 / 925.0) / 3.0)


def fig8_amp_warm(p):
    return _linear_in_lnp(p, 1000.0, FIG8_WARM_AMP1000, 300.0, FIG8_WARM_AMP300)


def fig8_amp_cold(p):
    return _linear_in_lnp(p, 1000.0, FIG8_COLD_AMP1000, 300.0, FIG8_COLD_AMP300)


def _fig8_pressure_axis(ax):
    ax.set_yscale("log")
    ax.invert_yaxis()
    # Bottom limit well past 1000 hPa (not just to 1030) so the deepest
    # dip -- up to ~1026 hPa for the 250 m warm-core amplitude at
    # 1000 hPa -- has visible clearance above the axis frame instead of
    # sitting right on it; 1000 remains the lowest tick regardless.
    ax.set_ylim(1075, 280)
    ax.yaxis.set_major_locator(plt.FixedLocator(STANDARD_LEVELS))
    ax.yaxis.set_minor_locator(plt.NullLocator())
    ax.set_yticklabels([f"{int(p)}" for p in STANDARD_LEVELS])
    ax.grid(True, which="major", color=GRID_COLOR, linewidth=0.5, zorder=0.2)
    ax.tick_params(length=3)


def _fig8_cross_section(ax, amp_fn, fill_color, line_color):
    """Draw one cross-section panel: for every standard level, a flat
    reference line at that pressure and a curve dipping toward higher
    (visual) pressure by Z'(x, p)/FIG8_LNP_UNIT_M, filled between the
    two. Returns {level: (A(p), range_within_circle_m)} for the caption.
    """
    x = np.linspace(-FIG8_XLIM_KM, FIG8_XLIM_KM, 400)
    edge_factor = np.exp(-(FIG8_CIRCLE_KM / FIG8_SCALE_KM) ** 2)  # ~1.5e-5, negligible
    out = {}

    for p in STANDARD_LEVELS:
        amp = amp_fn(p)
        zprime = -amp * np.exp(-(x / FIG8_SCALE_KM) ** 2)  # <= 0, meters
        p_visual = p * np.exp(-zprime / FIG8_LNP_UNIT_M)  # >= p: dips "below" the line
        flat = np.full_like(x, p)
        ax.fill_between(x, flat, p_visual, color=fill_color, linewidth=0, zorder=2)
        ax.plot(x, flat, color=TEXT_SECONDARY, linewidth=0.7, zorder=3)
        ax.plot(x, p_visual, color=line_color, linewidth=1.3, zorder=4)
        out[p] = (float(amp), float(amp * (1.0 - edge_factor)))

    for p in (925.0, 500.0):
        amp, rng = out[p]
        p_bot = p * np.exp(rng / FIG8_LNP_UNIT_M)
        ax.annotate(
            "", xy=(0, p_bot), xytext=(0, p),
            arrowprops=dict(arrowstyle="<->", color=TEXT_DARK, linewidth=1.1, shrinkA=0, shrinkB=0),
            zorder=6,
        )
        ax.annotate(
            f"{rng:.0f} m",
            (0, np.sqrt(p * p_bot)),
            textcoords="offset points",
            xytext=(10, 0),
            fontsize=7.0,
            color=TEXT_DARK,
            va="center",
            ha="left",
            zorder=6,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=0.8),
        )

    for xline in (-FIG8_CIRCLE_KM, FIG8_CIRCLE_KM):
        ax.axvline(xline, color=TEXT_SECONDARY, linewidth=0.9, linestyle="--", zorder=5)

    ax.set_xlim(-FIG8_XLIM_KM, FIG8_XLIM_KM)
    ax.set_xlabel("x, distance from center (km)")
    _fig8_pressure_axis(ax)
    return out


def make_fig8():
    fig, axes = plt.subplots(1, 3, figsize=(FULL_WIDTH_IN, 3.0))
    ax_a, ax_b, ax_c = axes

    warm_ranges = _fig8_cross_section(ax_a, fig8_amp_warm, LIGHT_RED, VORTEX_A_COLOR)
    ax_a.text(
        0, 340, "warm core:\nrange shrinks upward\n" + r"$-V_T$ > 0",
        ha="center", va="top", fontsize=7.0, color=TEXT_DARK, zorder=7,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=1.0),
    )
    ax_a.set_ylabel("pressure (hPa)")
    panel_letter(ax_a, "a")

    cold_ranges = _fig8_cross_section(ax_b, fig8_amp_cold, LIGHT_BLUE, VORTEX_B_COLOR)
    ax_b.text(
        0, 340, "cold core:\nrange grows upward\n" + r"$-V_T$ < 0",
        ha="center", va="top", fontsize=7.0, color=TEXT_DARK, zorder=7,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=1.0),
    )
    panel_letter(ax_b, "b")

    # --- panel (c): height range vs ln(p), both cases, from cps.hart -------
    lat2d_c, lon2d_c = cps_synthetic.make_grid(
        FIG8_CENTER_LAT, FIG8_CENTER_LON, half_width_deg=FIG8_HALF_WIDTH_DEG, dlat=0.5, dlon=0.5
    )
    # Union of the seven standard levels (markers) and Hart's own 13
    # 50 hPa levels (900-300, exactly hart.LOWER_LEVELS + hart.UPPER_LEVELS)
    # -- the band fits need the latter; only the former is plotted with
    # its own marker.
    union_levels = sorted(set(int(p) for p in STANDARD_LEVELS) | set(HART_50HPA_LEVELS), reverse=True)

    # Per (core, band) anchor pressure and text side: warm-core labels
    # sit to the right of the red line (ha="left", anchored a fixed
    # number of *data* units to the right of the line's own value),
    # cold-core labels to the left of the blue line (ha="right", the
    # same fixed pad to the left). A data-unit pad (not an offset in
    # points) is what actually keeps text off the line here: this axis
    # is only ~2 inches wide for a 0-500+ m data range, so even a few
    # points of offset is a huge swing in data space. The two cores'
    # anchor pressures are also deliberately offset from each other
    # within each band (the two lines' dZ values are nearly equal at
    # the band's own mean pressure, which is what made the two labels
    # collide before) so the labels stay vertically separated even
    # where the lines themselves pass close together. The label text
    # itself is just the number: the shaded band, the outside "lower/
    # upper band" tag, and the legend's color already say what it is.
    DZ_LABEL_PAD = 16.0
    ann_spec = {
        ("warm", "lower"): dict(p_anchor=820.0, ha="left"),
        ("warm", "upper"): dict(p_anchor=480.0, ha="left"),
        ("cold", "lower"): dict(p_anchor=660.0, ha="right"),
        ("cold", "upper"): dict(p_anchor=390.0, ha="right"),
    }
    results = {}
    for name, amp_fn, color in (("warm", fig8_amp_warm, VORTEX_A_COLOR), ("cold", fig8_amp_cold, VORTEX_B_COLOR)):
        z_stack = cps_synthetic.warm_core_heights(
            lat2d_c, lon2d_c, FIG8_CENTER_LAT, FIG8_CENTER_LON, union_levels, amp_fn, scale_km=FIG8_SCALE_KM
        )
        tw = hart.thermal_wind(
            union_levels, z_stack, lat2d_c, lon2d_c, FIG8_CENTER_LAT, FIG8_CENTER_LON, radius_km=FIG8_CIRCLE_KM
        )
        results[name] = tw

        xs = [tw["dz_by_level"][int(p)] for p in STANDARD_LEVELS]
        ax_c.plot(
            xs, STANDARD_LEVELS, marker="o", markersize=5.5, linewidth=1.2, color=color,
            markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.5, zorder=5,
        )

        for band, band_name, slope_key in ((hart.LOWER_LEVELS, "lower", "VTL"), (hart.UPPER_LEVELS, "upper", "VTU")):
            slope = tw[slope_key]
            band_dz = [tw["dz_by_level"][lvl] for lvl in band]
            ybar = np.mean(band_dz)
            xbar = np.mean(np.log(band))
            p_line = np.linspace(min(band), max(band), 30)
            dz_line = ybar + slope * (np.log(p_line) - xbar)
            ax_c.plot(dz_line, p_line, color=color, linewidth=1.8, linestyle="-", zorder=4)
            spec = ann_spec[(name, band_name)]
            p_anchor = spec["p_anchor"]
            dz_anchor = ybar + slope * (np.log(p_anchor) - xbar)
            dz_text = dz_anchor + (DZ_LABEL_PAD if spec["ha"] == "left" else -DZ_LABEL_PAD)
            ax_c.text(
                dz_text, p_anchor, f"{slope:+.0f} m",
                ha=spec["ha"], va="center", fontsize=7.2, color=color, fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.8),
                zorder=6,
            )

    xmax = 1.15 * max(
        max(results["warm"]["dz_by_level"].values()),
        max(results["cold"]["dz_by_level"].values()),
    )
    ax_c.axhspan(min(hart.LOWER_LEVELS), max(hart.LOWER_LEVELS), color=NEUTRAL_TINT_1, alpha=0.35, zorder=0)
    ax_c.axhspan(min(hart.UPPER_LEVELS), max(hart.UPPER_LEVELS), color=NEUTRAL_TINT_2, alpha=0.6, zorder=0)
    # Placed just outside the right edge of the axes (axes-fraction x,
    # data-coordinate y) so the two band labels never collide with the
    # curves, markers, or slope annotations inside the panel.
    band_label_kw = dict(transform=ax_c.get_yaxis_transform(), fontsize=7.2, color=TEXT_SECONDARY, ha="left", va="center", style="italic", zorder=1)
    ax_c.text(1.02, np.sqrt(min(hart.LOWER_LEVELS) * max(hart.LOWER_LEVELS)), "lower\nband", **band_label_kw)
    ax_c.text(1.02, np.sqrt(min(hart.UPPER_LEVELS) * max(hart.UPPER_LEVELS)), "upper\nband", **band_label_kw)

    ax_c.set_xlim(0, xmax)
    ax_c.set_xlabel(r"height range, max $-$ min (m)")
    _fig8_pressure_axis(ax_c)

    legend_handles = [
        Line2D([0], [0], color=VORTEX_A_COLOR, marker="o", markerfacecolor=VORTEX_A_COLOR, markeredgecolor="white", linewidth=1.8, markersize=5.5, label="warm core"),
        Line2D([0], [0], color=VORTEX_B_COLOR, marker="o", markerfacecolor=VORTEX_B_COLOR, markeredgecolor="white", linewidth=1.8, markersize=5.5, label="cold core"),
    ]
    # "Lower right" (the literal bottom-right corner) sits on top of the
    # 1000 hPa markers, since the legend box is wide enough to reach
    # left of the corner it anchors on; center-right, well above the
    # 1000 hPa row and well right of both lines at that pressure, is
    # clear of everything.
    ax_c.legend(handles=legend_handles, loc="center right", bbox_to_anchor=(0.99, 0.42), frameon=False, fontsize=7.0)
    panel_letter(ax_c, "c")

    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig8_thermal_wind_concept.png")
    plt.close(fig)

    report = dict(
        lnp_unit_m=float(FIG8_LNP_UNIT_M),
        warm_range_925=warm_ranges[925.0][1],
        warm_range_500=warm_ranges[500.0][1],
        cold_range_925=cold_ranges[925.0][1],
        cold_range_500=cold_ranges[500.0][1],
        warm_VTL=results["warm"]["VTL"],
        warm_VTU=results["warm"]["VTU"],
        cold_VTL=results["cold"]["VTL"],
        cold_VTU=results["cold"]["VTU"],
    )
    print("Figure 8 (thermal wind concept):")
    print(f"  vertical scale: 1 ln(p) unit = {report['lnp_unit_m']:.0f} m")
    print(f"  warm core: range(925 hPa)={report['warm_range_925']:.0f} m, range(500 hPa)={report['warm_range_500']:.0f} m, "
          f"cps.hart -V_T^L={report['warm_VTL']:+.1f} m, -V_T^U={report['warm_VTU']:+.1f} m")
    print(f"  cold core: range(925 hPa)={report['cold_range_925']:.0f} m, range(500 hPa)={report['cold_range_500']:.0f} m, "
          f"cps.hart -V_T^L={report['cold_VTL']:+.1f} m, -V_T^U={report['cold_VTU']:+.1f} m")
    return report


# ===========================================================================
# Figure 9: parameter B as a plan view
# ===========================================================================

FIG9_CENTER_LAT, FIG9_CENTER_LON = 30.0, 0.0
FIG9_HALF_WIDTH_DEG = 8.0  # ~+/-890 km, past the 1200 km/2 = 600 km box half-width
FIG9_BOX_KM = 1200.0
FIG9_CIRCLE_KM = 500.0
FIG9_VORTEX_AMP_M = 60.0
FIG9_VORTEX_SCALE_KM = 150.0
FIG9_BACKGROUND_THICKNESS_M = 2480.0
FIG9_HEADING_DEG = 45.0  # northeast
FIG9_GRADIENT_M_PER_1000KM = 40.0  # 925-700 hPa thickness, warm (thick) to the south


def _fig9_thickness_and_b(lat2d, lon2d, x_km, y_km, r_km, with_gradient):
    vortex = FIG9_VORTEX_AMP_M * np.exp(-(r_km / FIG9_VORTEX_SCALE_KM) ** 2)
    thickness = np.full_like(x_km, FIG9_BACKGROUND_THICKNESS_M) + vortex
    if with_gradient:
        # Warm (thick) to the south: thickness decreases northward (+y).
        thickness = thickness - (FIG9_GRADIENT_M_PER_1000KM / 1000.0) * y_km
    z900 = np.zeros_like(thickness)
    z600 = z900 + thickness  # only the difference (thickness) matters to parameter_b
    b_value = hart.parameter_b(
        z900, z600, lat2d, lon2d, FIG9_CENTER_LAT, FIG9_CENTER_LON, FIG9_HEADING_DEG, radius_km=FIG9_CIRCLE_KM
    )
    return thickness, float(b_value)


def _fig9_panel(ax, lon2d, lat2d, x_km, y_km, r_km, mx, my, thickness, b_value, label_text):
    half = 0.5 * FIG9_BOX_KM
    levels = np.arange(np.floor(thickness.min() / 10.0) * 10.0, thickness.max() + 10.0, 10.0)
    ax.contourf(x_km, y_km, thickness, levels=levels, cmap=CMAP_SEQ_BLUE, zorder=1)
    ax.contour(x_km, y_km, thickness, levels=levels, colors=TEXT_SECONDARY, linewidths=0.4, zorder=2)

    # Left/right split of the analysis circle, exactly the half-planes
    # hart.parameter_b uses (cross = mx*dy - my*dx; right where cross < 0
    # -- algebraically cross = r*sin(alpha - theta_m) for a point at math
    # angle alpha, theta_m the motion vector's own math angle, so "right"
    # is the 180 deg wedge from theta_m-180 to theta_m and "left" is
    # theta_m to theta_m+180). Drawn as vector Wedge patches (no raster
    # edges), under the contour lines but over the filled contourf.
    theta_m = 90.0 - FIG9_HEADING_DEG  # math-convention angle of the motion vector
    right_wedge = Wedge((0, 0), FIG9_CIRCLE_KM, theta_m - 180.0, theta_m, facecolor=NEUTRAL_TINT_2, edgecolor="none", alpha=0.55, zorder=1.5)
    left_wedge = Wedge((0, 0), FIG9_CIRCLE_KM, theta_m, theta_m + 180.0, facecolor=NEUTRAL_TINT_1, edgecolor="none", alpha=0.55, zorder=1.5)
    ax.add_patch(right_wedge)
    ax.add_patch(left_wedge)

    circle = Circle((0, 0), FIG9_CIRCLE_KM, facecolor="none", edgecolor=TEXT_DARK, linewidth=1.3, linestyle="--", zorder=6)
    ax.add_patch(circle)

    arrow_len = 320.0
    ax.annotate(
        "", xy=(arrow_len * mx, arrow_len * my), xytext=(0, 0),
        arrowprops=dict(arrowstyle="-|>", color=TEXT_DARK, linewidth=1.8, mutation_scale=16),
        zorder=8,
    )
    ax.annotate("motion", (arrow_len * mx, arrow_len * my), textcoords="offset points", xytext=(8, -14), fontsize=7.3, color=TEXT_DARK, fontweight="bold", ha="left", va="top", zorder=8)

    ax.plot(0, 0, marker="+", markersize=10, markeredgewidth=1.8, color=TEXT_DARK, zorder=8)

    ax.text(
        0.03, 0.03, f"B = {b_value:+.1f} m\n({label_text})",
        transform=ax.transAxes, fontsize=8.0, color=TEXT_DARK, ha="left", va="bottom",
        bbox=dict(facecolor="white", edgecolor=TEXT_SECONDARY, linewidth=0.6, alpha=0.9, pad=2.5), zorder=9,
    )

    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)
    ax.set_aspect("equal")
    ax.set_xlabel("km east of storm")
    ax.grid(True, color=GRID_COLOR, linewidth=0.4, zorder=0.3)
    ax.tick_params(length=3)


def make_fig9():
    lat2d, lon2d = cps_synthetic.make_grid(
        FIG9_CENTER_LAT, FIG9_CENTER_LON, half_width_deg=FIG9_HALF_WIDTH_DEG, dlat=0.25, dlon=0.25
    )
    x_km, y_km = hart.local_offsets_km(lat2d, lon2d, FIG9_CENTER_LAT, FIG9_CENTER_LON)
    r_km = hart.great_circle_km(lat2d, lon2d, FIG9_CENTER_LAT, FIG9_CENTER_LON)
    heading_rad = np.radians(FIG9_HEADING_DEG)
    mx, my = np.sin(heading_rad), np.cos(heading_rad)

    thickness_sym, b_sym = _fig9_thickness_and_b(lat2d, lon2d, x_km, y_km, r_km, with_gradient=False)
    thickness_front, b_front = _fig9_thickness_and_b(lat2d, lon2d, x_km, y_km, r_km, with_gradient=True)

    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH_IN, 3.7))
    ax_a, ax_b = axes

    _fig9_panel(ax_a, lon2d, lat2d, x_km, y_km, r_km, mx, my, thickness_sym, b_sym, "symmetric")
    ax_a.set_ylabel("km north of storm")
    # Right of NE motion is the south/east half (cross < 0, per
    # hart.parameter_b's own convention), left is north/west; place each
    # label at its half's own angular midpoint (northwest, southeast),
    # near the rim but inside the circle (radius 420 < 500).
    theta_m = 90.0 - FIG9_HEADING_DEG
    label_r = 420.0
    nw_deg, se_deg = np.radians(theta_m + 90.0), np.radians(theta_m - 90.0)
    ax_a.text(label_r * np.cos(nw_deg), label_r * np.sin(nw_deg), "left", fontsize=7.8, color=TEXT_SECONDARY, ha="center", va="center", style="italic", zorder=7)
    ax_a.text(label_r * np.cos(se_deg), label_r * np.sin(se_deg), "right", fontsize=7.8, color=TEXT_SECONDARY, ha="center", va="center", style="italic", zorder=7)
    panel_letter(ax_a, "a")

    _fig9_panel(ax_b, lon2d, lat2d, x_km, y_km, r_km, mx, my, thickness_front, b_front, "frontal, above the 10 m line")
    ax_b.text(0.95, 0.22, "warm flank (south)", transform=ax_b.transAxes, fontsize=7.3, color=TEXT_DARK, ha="right", va="bottom", style="italic",
               bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1.2), clip_on=False)
    ax_b.text(0.95, 0.92, "cold flank (north)", transform=ax_b.transAxes, fontsize=7.3, color=TEXT_DARK, ha="right", va="top", style="italic",
               bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1.2), clip_on=False)
    panel_letter(ax_b, "b")

    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig9_b_concept.png")
    plt.close(fig)

    print("Figure 9 (parameter B, plan view):")
    print(f"  (a) symmetric vortex alone: B = {b_sym:+.2f} m")
    print(f"  (b) vortex + {FIG9_GRADIENT_M_PER_1000KM:.0f} m/1000km southward-warm gradient, heading {FIG9_HEADING_DEG:.0f} deg (NE): B = {b_front:+.2f} m")
    return dict(b_symmetric=b_sym, b_frontal=b_front)


# ===========================================================================
# Figure 10: Hart's two diagrams, one schematic life cycle drawn on both
# ===========================================================================

# Columns: B (m), -V_T^L (m), -V_T^U (m), at 24 h spacing.
FIG10_TRAJ = np.array(
    [
        (3, 240, 200),
        (6, 210, 150),
        (12, 160, 80),
        (25, 110, 10),
        (40, 60, -70),
        (45, 0, -140),
        (35, -80, -200),
        (20, -150, -230),
    ],
    dtype=float,
)
FIG10_SECLUSION_END = np.array([5.0, 60.0, -180.0])
FIG10_XLIM_A = (-20.0, 80.0)
FIG10_YLIM = (-300.0, 300.0)


def make_fig10():
    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH_IN, 3.6))
    ax_a, ax_b = axes
    hours = np.arange(0, 24 * FIG10_TRAJ.shape[0], 24)
    b_thr = cps_HartCPS.B_THRESHOLD_M  # 10 m, Evans and Hart (2003)

    # --- panel (a): Phase 1, B vs -V_T^L, quadrants as Figure 7(d) ---------
    xlim, ylim = FIG10_XLIM_A, FIG10_YLIM
    ax_a.set_xlim(*xlim)
    ax_a.set_ylim(*ylim)

    quadrants_a = [
        (-1e4, b_thr, 0, 1e4, STAGE_COLORS[0], "symmetric\nwarm core"),
        (b_thr, 1e4, 0, 1e4, STAGE_COLORS[1], "asymmetric warm core"),
        (b_thr, 1e4, -1e4, 0, STAGE_COLORS[2], "asymmetric cold core"),
        (-1e4, b_thr, -1e4, 0, "#4a3aa7", "symmetric\ncold core"),
    ]
    for x0, x1, y0, y1, color, _ in quadrants_a:
        x0c, x1c = max(x0, xlim[0]), min(x1, xlim[1])
        y0c, y1c = max(y0, ylim[0]), min(y1, ylim[1])
        ax_a.add_patch(Rectangle((x0c, y0c), x1c - x0c, y1c - y0c, facecolor=color, alpha=0.30, edgecolor="none", zorder=0))
    label_pos_a = {
        "symmetric\nwarm core": (-15, 130, "left", "center"),
        "asymmetric warm core": (xlim[1] - 3, 275, "right", "center"),
        "asymmetric cold core": (xlim[1] - 3, -270, "right", "center"),
        "symmetric\ncold core": (xlim[0] + 3, -235, "left", "center"),
    }
    for _, _, _, _, _, label in quadrants_a:
        x, y, ha, va = label_pos_a[label]
        ax_a.text(x, y, label, color=TEXT_SECONDARY, fontsize=7.2, ha=ha, va=va, style="italic", zorder=1)

    ax_a.axhline(0, color=TEXT_DARK, linewidth=1.0, zorder=2)
    ax_a.axvline(b_thr, color=TEXT_DARK, linewidth=1.0, zorder=2)

    ax_a.plot(FIG10_TRAJ[:, 0], FIG10_TRAJ[:, 1], color=TEXT_SECONDARY, linewidth=2.0, zorder=5)
    for k in range(FIG10_TRAJ.shape[0]):
        bval, vtl = FIG10_TRAJ[k, 0], FIG10_TRAJ[k, 1]
        color = CMAP_SEQ_BLUE(k / (FIG10_TRAJ.shape[0] - 1))
        ax_a.plot(bval, vtl, marker="o", markersize=7, markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.8, zorder=6)
        dx_txt, dy_txt, va = 8, 8, "bottom"
        if k == FIG10_TRAJ.shape[0] - 1:
            dx_txt, dy_txt, va = 8, -14, "top"
        ax_a.annotate(f"{hours[k]:.0f} h", (bval, vtl), textcoords="offset points", xytext=(dx_txt, dy_txt), fontsize=6.7, color=TEXT_SECONDARY, va=va)

    seclusion_a = np.vstack([FIG10_TRAJ[-1, [0, 1]], FIG10_SECLUSION_END[[0, 1]]])
    ax_a.plot(seclusion_a[:, 0], seclusion_a[:, 1], color=TEXT_SECONDARY, linewidth=1.6, linestyle="--", zorder=5)
    ax_a.plot(FIG10_SECLUSION_END[0], FIG10_SECLUSION_END[1], marker="D", markersize=6.5, markerfacecolor=CMAP_SEQ_BLUE(1.0), markeredgecolor="white", markeredgewidth=0.8, zorder=6)
    ax_a.annotate(
        "warm seclusion\n(some storms)", (FIG10_SECLUSION_END[0], FIG10_SECLUSION_END[1]),
        textcoords="offset points", xytext=(-14, 4), fontsize=6.7, color=TEXT_SECONDARY, style="italic", ha="right", va="center",
    )

    onset_xy = _interp_crossing(FIG10_TRAJ[:, [0, 1]], 0, b_thr)
    completion_xy = _interp_crossing(FIG10_TRAJ[:, [0, 1]], 1, 0.0)
    if onset_xy is not None:
        ax_a.plot(*onset_xy, marker="x", markersize=7, color=TEXT_DARK, markeredgewidth=1.6, zorder=7)
        ax_a.annotate(
            "onset: B > 10 m", onset_xy, textcoords="offset points", xytext=(10, 14), fontsize=6.8, color=TEXT_DARK,
            va="bottom", bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.8), zorder=7,
        )
    if completion_xy is not None:
        ax_a.plot(*completion_xy, marker="x", markersize=7, color=TEXT_DARK, markeredgewidth=1.6, zorder=7)
        ax_a.annotate(
            "completion:\n" + r"$-V_T^L$ < 0", completion_xy, textcoords="offset points", xytext=(10, -32),
            fontsize=6.8, color=TEXT_DARK, va="top", bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.8), zorder=7,
        )

    ax_a.set_xlabel("B (m)")
    ax_a.set_ylabel(r"$-V_T^L$  (m)")
    ax_a.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0.2)
    ax_a.tick_params(length=3)
    panel_letter(ax_a, "a")

    # --- panel (b): Phase 2, -V_T^L vs -V_T^U, quadrants as Figure 1 -------
    lim = 300.0
    ax_b.set_xlim(-lim, lim)
    ax_b.set_ylim(-lim, lim)
    quadrants_b = [
        (0, lim, 0, lim, "#e34948", "deep warm core"),
        (0, lim, -lim, 0, "#eb6834", "shallow warm core"),
        (-lim, 0, -lim, 0, "#2a78d6", "cold core"),
        (-lim, 0, 0, lim, "#4a3aa7", "lower cold, upper warm"),
    ]
    for x0, x1, y0, y1, color, _ in quadrants_b:
        ax_b.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=color, alpha=0.11, edgecolor="none", zorder=0))
    # Same quadrant labels and positions as Figure 1's own single-panel
    # version of this diagram.
    label_pos_b = {
        "deep warm core": (lim * 0.55, lim * 0.90),
        "shallow warm core": (lim * 0.55, -lim * 0.90),
        "cold core": (-lim * 0.95, -lim * 0.90),
        "lower cold, upper warm": (-lim * 0.95, lim * 0.68),
    }
    for _, _, _, _, _, label in quadrants_b:
        x, y = label_pos_b[label]
        ax_b.text(x, y, label, color=TEXT_SECONDARY, fontsize=7.3, ha="left", va="center", style="italic", zorder=1)
    ax_b.axhline(0, color=TEXT_DARK, linewidth=1.0, zorder=2)
    ax_b.axvline(0, color=TEXT_DARK, linewidth=1.0, zorder=2)

    ax_b.plot(FIG10_TRAJ[:, 1], FIG10_TRAJ[:, 2], color=TEXT_SECONDARY, linewidth=2.0, zorder=5)
    for k in range(FIG10_TRAJ.shape[0]):
        vtl, vtu = FIG10_TRAJ[k, 1], FIG10_TRAJ[k, 2]
        color = CMAP_SEQ_BLUE(k / (FIG10_TRAJ.shape[0] - 1))
        ax_b.plot(vtl, vtu, marker="o", markersize=7, markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.8, zorder=6)
        dx_txt, dy_txt, va, ha = 8, 8, "bottom", "left"
        if k == FIG10_TRAJ.shape[0] - 1:
            dx_txt, dy_txt, va = 8, -14, "top"
        elif hours[k] == 144:
            # Default placement sits right on the solid trajectory line
            # here (it continues up-right toward 120 h) and close to the
            # dashed warm-seclusion branch passing just below; up-and-left
            # clears both.
            dx_txt, dy_txt, va, ha = -8, 14, "bottom", "right"
        ax_b.annotate(f"{hours[k]:.0f} h", (vtl, vtu), textcoords="offset points", xytext=(dx_txt, dy_txt), fontsize=6.7, color=TEXT_SECONDARY, va=va, ha=ha)

    seclusion_b = np.vstack([FIG10_TRAJ[-1, [1, 2]], FIG10_SECLUSION_END[[1, 2]]])
    ax_b.plot(seclusion_b[:, 0], seclusion_b[:, 1], color=TEXT_SECONDARY, linewidth=1.6, linestyle="--", zorder=5)
    ax_b.plot(FIG10_SECLUSION_END[1], FIG10_SECLUSION_END[2], marker="D", markersize=6.5, markerfacecolor=CMAP_SEQ_BLUE(1.0), markeredgecolor="white", markeredgewidth=0.8, zorder=6)
    ax_b.annotate(
        "warm seclusion\n(some storms)", (FIG10_SECLUSION_END[1], FIG10_SECLUSION_END[2]),
        textcoords="offset points", xytext=(10, -4), fontsize=6.7, color=TEXT_SECONDARY, style="italic", ha="left", va="top",
    )

    ax_b.set_xlabel(r"$-V_T^L$  (m)")
    ax_b.set_ylabel(r"$-V_T^U$  (m)")
    ax_b.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0.2)
    ax_b.tick_params(length=3)
    panel_letter(ax_b, "b")

    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig10_two_diagrams.png")
    plt.close(fig)

    report = dict(onset_B=onset_xy[0] if onset_xy else None, onset_VTL=onset_xy[1] if onset_xy else None,
                  completion_B=completion_xy[0] if completion_xy else None, completion_VTL=completion_xy[1] if completion_xy else None)
    print("Figure 10 (Hart's two diagrams, schematic life cycle):")
    print(f"  onset crossing (B=10 m): {report}")
    return report


# ===========================================================================
# Main
# ===========================================================================


def print_ambient_check(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, z_std_stack, psfc):
    """Sample HVTL/HVTU far from both vortices, to confirm the background
    gradient alone (per the header docstring's revised rate) reads near
    the diverging colormap's neutral gray rather than painting the whole
    map cold.
    """
    far_lat, far_lon = 20.0, -155.0  # >2500 km from both vortex centers
    i_far, j_far = nearest_index(lat_vals, lon_vals, far_lat, far_lon)

    hvtl_amb = cps_HartCPS.executeBand3(
        z_std_stack[925.0], z_std_stack[850.0], z_std_stack[700.0], psfc, dx2d, dy_m,
        500.0, 925.0, 850.0, 700.0,
    )
    hvtu_amb = cps_HartCPS.executeBand3(
        z_std_stack[500.0], z_std_stack[400.0], z_std_stack[300.0], psfc, dx2d, dy_m,
        500.0, 500.0, 400.0, 300.0,
    )
    print(
        f"Ambient check at ({far_lat:.0f}N, {abs(far_lon):.0f}W), far from both vortices: "
        f"HVTL={float(hvtl_amb[i_far, j_far]):+.1f} m, HVTU={float(hvtu_amb[i_far, j_far]):+.1f} m "
        "(expect roughly within +/-25 m)"
    )


def main():
    lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m = build_grid()
    z_std_stack = build_level_stack(lat2d, lon2d)
    psfc = build_psfc(lat2d, lon2d)

    print_ambient_check(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, z_std_stack, psfc)

    print("Building Figure 1 (phase-space schematic) ...")
    make_fig1()

    print("Building Figure 2 (method: dZ profile + window) ...")
    make_fig2(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, z_std_stack)

    print("Building Figure 3 (gridded fields) ...")
    make_fig3(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, z_std_stack, psfc)

    print("Building Figure 4 (Hart family, tilted cold core) ...")
    center_values = make_fig4(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, psfc)
    print("Figure 4 center values:", center_values)

    print("Building Figure 5 (performance) ...")
    timings = make_fig5()
    print("Figure 5 timings (s):", timings)

    print("Building Figure 6 (CAVE photograph, crop/resize only) ...")
    make_fig6()

    print("Building Figure 7 (parameter B and the ET stage) ...")
    fig7_values = make_fig7(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m)
    print("Figure 7 center values:", fig7_values)

    print("Building Figure 8 (thermal wind concept, cross-section) ...")
    fig8_values = make_fig8()
    print("Figure 8 values:", fig8_values)

    print("Building Figure 9 (parameter B, plan view) ...")
    fig9_values = make_fig9()
    print("Figure 9 values:", fig9_values)

    print("Building Figure 10 (Hart's two diagrams, schematic life cycle) ...")
    fig10_values = make_fig10()
    print("Figure 10 values:", fig10_values)

    print("Done. Figures written to", OUT_DIR)


if __name__ == "__main__":
    main()
