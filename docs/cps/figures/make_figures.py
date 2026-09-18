#!/usr/bin/env python3
"""
make_figures.py -- regenerates every figure on the GitHub Pages article
(../index.html) from the package's own code (D2D/derivedParameters/functions/
HartCPS.py and CycloneCore.py) run on synthetic fields, plus one photograph
of the real CAVE display that is cropped/resized only (fig6).

Run from the repository root:

    python3 docs/cps/figures/make_figures.py

Outputs land next to this script, in docs/cps/figures/:
    fig1_phase_space.png   fig2_method.png       fig3_gridded.png
    fig4_tilt.png           fig5_performance.png   fig6_cave_typhoon.jpg
    fig7_parameter_b.png

No test fixtures are reused: everything is built here so the figures are
reproducible from nothing but this file, HartCPS.py, CycloneCore.py and
numpy/matplotlib.

---------------------------------------------------------------------------
Synthetic field definition (documented here so the HTML captions can
quote it precisely; every number below matches what is actually computed)
---------------------------------------------------------------------------

Grid
    Regular lat/lon, 0.5 degree spacing, longitude -160 to -100 (west to
    east), latitude 15 to 65 (south to north; array row 0 is the
    southernmost row, i.e. rows increase northward -- CycloneCore's
    ORIENTATION_MODE 0 convention).  ``dy`` is a scalar, 0.5 degree of
    latitude = 55.6 km, in meters.  ``dx`` is a full 2D array in meters,
    ``dx[i, j] = 55.6 km * cos(lat[i])`` -- 0.5 degree of longitude at
    that row's latitude -- passed as AWIPS itself would pass it (a
    pseudo-field that varies across the grid).

Background height
    Z_std(p) = 100 m + 7000 m * ln(1000 hPa / p) (the same "standard-ish"
    background HartCPS.py's own standalone demo uses), plus a weak
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
    ``TILT_KM`` at 300 hPa (400 km per the spec; the script checks the
    vorticity-family dipole this is meant to demonstrate and re-runs at
    600 km if the 400 km tilt does not produce it -- see
    ``_verify_or_increase_tilt`` and the printed report).

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
      HartCPS.py's own module docstring, "Parameter B and ET stage", for
      the projection HartCPS.parameter_b_grid computes, and this
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

    HartCPS.ORIENTATION_MODE is set to 0 for this figure, same reason
    and same convention as CycloneCore.ORIENTATION_MODE in Figure 4:
    HartCPS.gradient_2d (the one function in that module that takes a
    spatial derivative) needs to know that this synthetic grid's rows
    increase northward.
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
from matplotlib.patches import Rectangle, Circle
from matplotlib.lines import Line2D

# ---------------------------------------------------------------------------
# Make HartCPS.py / CycloneCore.py importable exactly as CAVE imports them
# (bare modules, no package), per tests/d2d_cps/conftest.py's own approach.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent  # docs/cps/figures -> docs/cps -> docs -> repo root
FUNCTIONS_DIR = REPO_ROOT / "D2D" / "derivedParameters" / "functions"
sys.path.insert(0, str(FUNCTIONS_DIR))
sys.path.insert(0, str(REPO_ROOT))

import HartCPS  # noqa: E402
import CycloneCore  # noqa: E402

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
CATEGORY_NAMES = [
    "0  mid-level vortex",
    "1  cold core",
    "2  neutral",
    "3  shallow warm core",
    "4  deep warm core",
]
CMAP_CATEGORY = ListedColormap(CATEGORY_COLORS)
NORM_CATEGORY = BoundaryNorm(np.arange(-0.5, 5.5, 1.0), CMAP_CATEGORY.N)

VORTEX_A_COLOR = "#e34948"
VORTEX_B_COLOR = "#2a78d6"

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
    """HartCPS.band_slope wants 2D grid arrays; wrap plain floats as 1x1
    arrays so the point-evaluation in Figure 2(a) goes through the
    package's own function, not a hand-rolled slope.
    """
    arrs = [np.array([[dz_by_level[p]]], dtype=float) for p in band_levels]
    return float(HartCPS.band_slope(arrs, band_levels)[0, 0])


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
        (-lim, 0, 0, lim, "#4a3aa7", "mid-level or hybrid"),
    ]
    for x0, x1, y0, y1, color, label in quadrants:
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=color, alpha=0.11, edgecolor="none", zorder=0))

    label_pos = {
        "deep warm core": (lim * 0.55, lim * 0.90),
        "shallow warm core": (lim * 0.55, -lim * 0.90),
        "cold core": (-lim * 0.95, -lim * 0.90),
        "mid-level or hybrid": (-lim * 0.95, lim * 0.68),
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

    dz_full = {p: HartCPS.delta_z(z_std_stack[p], dx2d, dy_m, HartCPS.RADIUS_KM) for p in STANDARD_LEVELS}
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
    ann_anchor_p = {"L": HartCPS.LOWER_BAND[-1], "U": HartCPS.UPPER_BAND[1]}  # 700, 400

    for vortex_id, dz_dict, color in (("A", dzA, VORTEX_A_COLOR), ("B", dzB, VORTEX_B_COLOR)):
        xs = [dz_dict[p] for p in STANDARD_LEVELS]
        ax_a.plot(xs, STANDARD_LEVELS, marker="o", markersize=6, linewidth=0, markerfacecolor=color, markeredgecolor="white", markeredgewidth=0.6, zorder=5)

        for band, band_name in ((HartCPS.LOWER_BAND, "L"), (HartCPS.UPPER_BAND, "U")):
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
    hvtl = HartCPS.executeBand3(
        z_std_stack[925.0], z_std_stack[850.0], z_std_stack[700.0], psfc, dx2d, dy_m,
        500.0, 925.0, 850.0, 700.0,
    )
    hvtu = HartCPS.executeBand3(
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

    # (d) HCPScat
    cat = HartCPS.executeClassStd(
        z_std_stack[1000.0], z_std_stack[925.0], z_std_stack[850.0], z_std_stack[700.0],
        z_std_stack[500.0], z_std_stack[400.0], z_std_stack[300.0],
        psfc, dx2d, dy_m,
    )
    draw_terrain_box(ax_d)
    pm_d = ax_d.pcolormesh(lon2d, lat2d, cat, cmap=CMAP_CATEGORY, norm=NORM_CATEGORY, shading="auto", zorder=2)
    ax_d.contour(lon2d, lat2d, z1000, levels=np.arange(np.floor(z1000.min() / 20) * 20, z1000.max() + 20, 20), colors="#8a8a86", linewidths=0.35, zorder=3)
    panel_letter(ax_d, "d")
    cb_d = fig.colorbar(pm_d, ax=ax_d, pad=0.02, fraction=0.05, ticks=range(5))
    cb_d.ax.set_yticklabels(CATEGORY_NAMES, fontsize=6.8)

    fig.savefig(OUT_DIR / "fig3_gridded.png")
    plt.close(fig)


# ===========================================================================
# Figure 4: vorticity family versus Hart family on the tilted cold core
# ===========================================================================

OMEGA_EARTH = 7.2921159e-5
G_ACCEL = 9.81


def geostrophic_wind(z, dx2d, dy_m, f):
    dzdy = np.gradient(z, axis=0) / dy_m
    dzdx = np.gradient(z, axis=1) / dx2d
    u = -(G_ACCEL / f) * dzdy
    v = (G_ACCEL / f) * dzdx
    return u, v


def _fig4_fields(lat2d, lon2d, dx2d, dy_m, psfc, tilt_km):
    f50 = 2.0 * OMEGA_EARTH * np.sin(np.radians(50.0))

    z850 = height_field(lat2d, lon2d, 850.0, tilt_km=tilt_km)
    z600 = height_field(lat2d, lon2d, 600.0, tilt_km=tilt_km)
    z300 = height_field(lat2d, lon2d, 300.0, tilt_km=tilt_km)
    z925 = height_field(lat2d, lon2d, 925.0, tilt_km=tilt_km)
    z700 = height_field(lat2d, lon2d, 700.0, tilt_km=tilt_km)
    z500 = height_field(lat2d, lon2d, 500.0, tilt_km=tilt_km)
    z400 = height_field(lat2d, lon2d, 400.0, tilt_km=tilt_km)

    u850, v850 = geostrophic_wind(z850, dx2d, dy_m, f50)
    u600, v600 = geostrophic_wind(z600, dx2d, dy_m, f50)
    u300, v300 = geostrophic_wind(z300, dx2d, dy_m, f50)

    CycloneCore.ORIENTATION_MODE = 0  # rows increase northward on this synthetic grid
    HartCPS.ORIENTATION_MODE = 0  # rows increase northward on this synthetic grid
    vtl = CycloneCore.execute(u850, v850, u600, v600, dx2d, dy_m, 100.0)
    vtu = CycloneCore.execute(u600, v600, u300, v300, dx2d, dy_m, 100.0)

    hvtl = HartCPS.executeBand3(z925, z850, z700, psfc, dx2d, dy_m, 500.0, 925.0, 850.0, 700.0)
    hvtu = HartCPS.executeBand3(z500, z400, z300, psfc, dx2d, dy_m, 500.0, 500.0, 400.0, 300.0)

    return vtl, vtu, hvtl, hvtu


def make_fig4(lat_vals, lon_vals, lat2d, lon2d, dx2d, dy_m, psfc):
    tilt_km = DEFAULT_TILT_KM
    iC, jC = nearest_index(lat_vals, lon_vals, VORTEX_B["lat"], VORTEX_B["lon"])

    report_lines = []
    for attempt_tilt in (DEFAULT_TILT_KM, 600.0):
        vtl, vtu, hvtl, hvtu = _fig4_fields(lat2d, lon2d, dx2d, dy_m, psfc, attempt_tilt)
        vtl_c = float(vtl[iC, jC])
        # "displaced west" -> sample a few grid columns west of center.
        j_west = max(jC - 8, 0)
        vtl_west = float(vtl[iC, j_west])
        dipole_present = (vtl_c >= -1.0) and (vtl_west < vtl_c - 1.0)
        report_lines.append(
            f"tilt={attempt_tilt:.0f} km: VTL at center={vtl_c:.2f} (1e-5/s), "
            f"VTL 8 pts west={vtl_west:.2f} (1e-5/s), dipole_present={dipole_present}"
        )
        tilt_km = attempt_tilt
        if dipole_present:
            break

    print("Figure 4 tilt/dipole check:")
    for line in report_lines:
        print("  " + line)

    fig, axes = plt.subplots(2, 2, figsize=(FULL_WIDTH_IN, 7.6), constrained_layout=True)
    fig.get_layout_engine().set(h_pad=0.06, w_pad=0.04, hspace=0.02, wspace=0.02)
    (ax_a, ax_b), (ax_c, ax_d) = axes

    lon_min, lon_max = -155.0, -125.0
    lat_min, lat_max = 35.0, 62.0
    for ax in (ax_a, ax_b, ax_c, ax_d):
        style_map_axes(ax, lon_min, lon_max, lat_min, lat_max)

    vort_lim = float(np.nanmax(np.abs(np.concatenate([vtl.ravel(), vtu.ravel()]))))
    vort_lim = max(vort_lim, 1.0)
    hart_lim = float(np.nanmax(np.abs(np.concatenate([hvtl.ravel(), hvtu.ravel()]))))
    hart_lim = max(hart_lim, 1.0)

    clat, clon = VORTEX_B["lat"], VORTEX_B["lon"]

    def mark_center(ax, value, unit):
        ax.plot(clon, clat, marker="+", markersize=11, markeredgewidth=2.2, color="black", zorder=10)
        sign = "+" if value >= 0 else "−"
        # Always offset down-left of the plus: every panel has a colorbar
        # hugging its right edge, so this keeps the label clear of both.
        ax.annotate(
            f"at center: {sign}{abs(value):.0f} {unit}",
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

    pm_a = ax_a.pcolormesh(lon2d, lat2d, vtl, cmap=CMAP_DIVERGING, vmin=-vort_lim, vmax=vort_lim, shading="auto", zorder=2)
    mark_center(ax_a, float(vtl[iC, jC]), r"$\times 10^{-5}$ s$^{-1}$")
    panel_letter(ax_a, "a")

    pm_b = ax_b.pcolormesh(lon2d, lat2d, vtu, cmap=CMAP_DIVERGING, vmin=-vort_lim, vmax=vort_lim, shading="auto", zorder=2)
    mark_center(ax_b, float(vtu[iC, jC]), r"$\times 10^{-5}$ s$^{-1}$")
    panel_letter(ax_b, "b")

    cb_ab = fig.colorbar(pm_b, ax=[ax_a, ax_b], location="right", pad=0.02, fraction=0.035, shrink=0.9)
    cb_ab.set_label("vorticity proxy VTL, VTU (1e-5 / s)", fontsize=8)
    cb_ab.ax.tick_params(labelsize=7.5)

    pm_c = ax_c.pcolormesh(lon2d, lat2d, hvtl, cmap=CMAP_DIVERGING, vmin=-hart_lim, vmax=hart_lim, shading="auto", zorder=2)
    mark_center(ax_c, float(hvtl[iC, jC]), "m")
    panel_letter(ax_c, "c")

    pm_d = ax_d.pcolormesh(lon2d, lat2d, hvtu, cmap=CMAP_DIVERGING, vmin=-hart_lim, vmax=hart_lim, shading="auto", zorder=2)
    mark_center(ax_d, float(hvtu[iC, jC]), "m")
    panel_letter(ax_d, "d")

    cb_cd = fig.colorbar(pm_d, ax=[ax_c, ax_d], location="right", pad=0.02, fraction=0.035, shrink=0.9)
    cb_cd.set_label(r"Hart family $-V_T^L$, $-V_T^U$ (m)", fontsize=8)
    cb_cd.ax.tick_params(labelsize=7.5)

    fig.savefig(OUT_DIR / "fig4_tilt.png")
    plt.close(fig)

    center_values = dict(
        vtl_center=float(vtl[iC, jC]),
        vtu_center=float(vtu[iC, jC]),
        hvtl_center=float(hvtl[iC, jC]),
        hvtu_center=float(hvtu[iC, jC]),
        tilt_km_used=tilt_km,
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


def _time_execute_class_std(ny, nx, rng):
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

    t0 = time.perf_counter()
    HartCPS.executeClassStd(z[1000.0], z[925.0], z[850.0], z[700.0], z[500.0], z[400.0], z[300.0], psfc, dx2d, dy_m)
    return time.perf_counter() - t0


def make_fig5():
    rng = np.random.default_rng(20260917)
    sizes = [(181, 360), (361, 720), (721, 1440)]
    labels = ["181×360\n(1°)", "361×720\n(0.5°)", "721×1440\n(0.25°)"]
    medians = []
    for ny, nx in sizes:
        runs = [_time_execute_class_std(ny, nx, rng) for _ in range(3)]
        med = float(np.median(runs))
        medians.append(med)
        print(f"executeClassStd timing, {ny}x{nx}: runs={[f'{r:.3f}' for r in runs]} s, median={med:.3f} s")

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

# HartCPS.ORIENTATION_MODE = 0 is set inside _fig4_fields (above), next to
# CycloneCore's own assignment; that is a real mutation of the imported
# module's attribute, so it is still in effect here (make_fig7 runs after
# make_fig4 in main()). Set again here anyway, defensively, so this
# function is correct even if called on its own.

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

STAGE_COLORS = [CATEGORY_COLORS[2], CATEGORY_COLORS[3], CATEGORY_COLORS[1]]  # pale gray, orange, blue
STAGE_NAMES = ["0  pre-onset", "1  onset", "2  complete"]
CMAP_STAGE = ListedColormap(STAGE_COLORS)
NORM_STAGE = BoundaryNorm(np.arange(-0.5, 3.5, 1.0), CMAP_STAGE.N)


def fig7_rate_per_1000km(p):
    """Meridional rate (m per 1000 km) of Figure 7's own background
    height gradient at pressure p: 0 at 925 hPa, FIG7_THICKNESS_GRADIENT_
    M_PER_1000KM at 700 hPa, linear in ln(p) (same style as
    _linear_in_lnp/meridional_gradient_m) and extended by that same line
    to 1000 and 850 hPa, so every level HartCPS needs for this figure
    gets one smooth background rather than a rate that jumps between
    just two levels. The *difference* rate(700) - rate(925) is what sets
    the 925-700 hPa thickness gradient; extending it smoothly to 1000/850
    hPa only matters for HVTL and the closed-low mask, not for B itself.
    """
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
    HartCPS.ORIENTATION_MODE = 0  # rows increase northward on this synthetic grid

    center1 = (VORTEX_A["lat"], VORTEX_A["lon"])
    center2 = (FIG7_VORTEX_A2_LAT, FIG7_VORTEX_A2_LON)

    z1000 = fig7_height_field(lat2d, lon2d, 1000.0)
    z925 = fig7_height_field(lat2d, lon2d, 925.0)
    z850 = fig7_height_field(lat2d, lon2d, 850.0)
    z700 = fig7_height_field(lat2d, lon2d, 700.0)
    thickness = z700 - z925

    psfc = np.full(lat2d.shape, 1013.0)
    u_steer = fig7_steering_u(lat2d)
    v_steer = fig7_steering_v(lat2d)
    coriolis = 2.0 * OMEGA_EARTH * np.sin(np.radians(lat2d))

    hb = HartCPS.executeB(
        z925, z700,
        u_steer, v_steer, u_steer, v_steer, u_steer, v_steer, u_steer, v_steer,
        psfc, coriolis, dx2d, dy_m,
        500.0, HartCPS.HART_B_LAYER_SCALE, 900.0,
    )
    vtl = HartCPS.thermal_wind_grid(
        [z925, z850, z700], HartCPS.LOWER_BAND, dx2d, dy_m, HartCPS.RADIUS_KM,
        psfc_hpa=psfc, cap_hpa=900.0,
    )
    het_stage = HartCPS.executeETStage(
        z1000, z925, z850, z700,
        u_steer, v_steer, u_steer, v_steer, u_steer, v_steer, u_steer, v_steer,
        psfc, coriolis, dx2d, dy_m,
        500.0, HartCPS.B_THRESHOLD_M, HartCPS.HART_B_LAYER_SCALE,
        HartCPS.DEFAULT_DEPTH_M, HartCPS.DEFAULT_BLOB_RADIUS_KM, 900.0,
    )

    i1, j1 = nearest_index(lat_vals, lon_vals, center1[0], center1[1])
    i2, j2 = nearest_index(lat_vals, lon_vals, center2[0], center2[1])
    b1, b2 = float(hb[i1, j1]), float(hb[i2, j2])
    vtl1, vtl2 = float(vtl[i1, j1]), float(vtl[i2, j2])

    print("Figure 7 (Parameter B and ET stage), synthetic transitioning-storm case:")
    print(f"  925-700 hPa thickness gradient used: {FIG7_THICKNESS_GRADIENT_M_PER_1000KM:.0f} m per 1000 km, decreasing northward")
    print(f"  vortex A,  28N 130W, easterly steering ({FIG7_STEERING_EASTERLY_MS:+.0f} m/s far south): B = {b1:+.1f} m, -V_T^L = {vtl1:+.1f} m")
    print(f"  vortex A', 42N 140W, westerly steering ({FIG7_STEERING_WESTERLY_MS:+.0f} m/s far north): B = {b2:+.1f} m, -V_T^L = {vtl2:+.1f} m")
    print(
        "  sign reasoning: thickness is largest (warmest) toward the south domain edge "
        "everywhere. Vortex A' moves east (westerly steering): facing east, its right side "
        "faces south, the warm side, so B is positive. Vortex A moves west (easterly "
        "steering): facing west, its right side faces north, the cold side, so B is "
        "negative. Both vortices are the identical warm core (same amplitude, same scale); "
        "only the ambient thickness gradient and the direction of motion set B's sign."
    )
    onset_ok = b2 > HartCPS.B_THRESHOLD_M
    cold_ok = b1 < -HartCPS.B_THRESHOLD_M
    print(
        f"  check: westerly B ({b2:+.1f} m) > {HartCPS.B_THRESHOLD_M:.0f} m onset threshold: {onset_ok}; "
        f"easterly B ({b1:+.1f} m) < -{HartCPS.B_THRESHOLD_M:.0f} m: {cold_ok}"
    )
    if not (onset_ok and cold_ok):
        print("  WARNING: gradient too weak to clear the 10 m threshold comfortably on both sides.")

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
    ax_b.contour(lon2d, lat2d, hb, levels=[HartCPS.B_THRESHOLD_M], colors=TEXT_DARK, linewidths=1.4, zorder=5)
    # Manual label, away from vortex A's marker: near the west edge of the
    # domain, at the same latitude the B=10 m line actually crosses there
    # (found by scanning a column far from both vortices, rather than
    # matplotlib's automatic clabel, which kept landing on top of vortex A).
    label_lon = LON_MIN + 5.0
    j_label = nearest_index(lat_vals, lon_vals, LAT_MIN, label_lon)[1]
    label_lat = _interp_crossing(np.column_stack([hb[:, j_label], lat_vals]), 0, HartCPS.B_THRESHOLD_M)
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

    # --- (c) HETstage ---------------------------------------------------------
    pm_c = ax_c.pcolormesh(lon2d, lat2d, het_stage, cmap=CMAP_STAGE, norm=NORM_STAGE, shading="auto", zorder=2)
    z1000_levels = np.arange(np.floor(z1000.min() / 20) * 20, z1000.max() + 20, 20)
    ax_c.contour(lon2d, lat2d, z1000, levels=z1000_levels, colors="#8a8a86", linewidths=0.35, zorder=3)
    mark_vortex_centers(ax_c)
    cb_c = fig.colorbar(pm_c, ax=ax_c, pad=0.02, fraction=0.05, ticks=range(3))
    cb_c.ax.set_yticklabels(STAGE_NAMES, fontsize=7.2)
    panel_letter(ax_c, "c")

    # --- (d) Hart's Phase 1 diagram: B vs -V_T^L -----------------------------
    xlim = (min(-20.0, 1.15 * b1), 80.0)
    ylim = (-300.0, 300.0)
    ax_d.set_xlim(*xlim)
    ax_d.set_ylim(*ylim)

    quadrants = [
        (-1e4, HartCPS.B_THRESHOLD_M, 0, 1e4, STAGE_COLORS[0], "symmetric\nwarm core"),
        (HartCPS.B_THRESHOLD_M, 1e4, 0, 1e4, STAGE_COLORS[1], "asymmetric warm core"),
        (HartCPS.B_THRESHOLD_M, 1e4, -1e4, 0, STAGE_COLORS[2], "asymmetric cold core"),
        (-1e4, HartCPS.B_THRESHOLD_M, -1e4, 0, "#4a3aa7", "symmetric\ncold core"),
    ]
    for x0, x1, y0, y1, color, _ in quadrants:
        x0c, x1c = max(x0, xlim[0]), min(x1, xlim[1])
        y0c, y1c = max(y0, ylim[0]), min(y1, ylim[1])
        ax_d.add_patch(Rectangle((x0c, y0c), x1c - x0c, y1c - y0c, facecolor=color, alpha=0.30, edgecolor="none", zorder=0))

    label_pos = {
        "symmetric\nwarm core": (xlim[0] + 3, 205, "left"),
        "asymmetric warm core": (xlim[1] - 3, 260, "right"),
        "asymmetric cold core": (xlim[1] - 3, -190, "right"),
        "symmetric\ncold core": (0.5 * xlim[0], -230, "center"),
    }
    for _, _, _, _, _, label in quadrants:
        x, y, ha = label_pos[label]
        va = "top" if label == "symmetric\nwarm core" else "center"
        ax_d.text(x, y, label, color=TEXT_SECONDARY, fontsize=7.5, ha=ha, va=va, style="italic", zorder=1)

    ax_d.axhline(0, color=TEXT_DARK, linewidth=1.0, zorder=2)
    ax_d.axvline(HartCPS.B_THRESHOLD_M, color=TEXT_DARK, linewidth=1.0, zorder=2)

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
            # Pulled up and to the left of its own point, clear of "24 h"
            # (which keeps the default above-right placement) and of the
            # "symmetric warm core" label lower in this same quadrant.
            dx_txt, dy_txt, ha, va = -8, 16, "right", "bottom"
        elif hours[k] == 120:
            dx_txt, dy_txt = 16, 18  # clear of the "asymmetric cold core" label just above
        elif hours[k] == 72:
            dx_txt, dy_txt = 22, 2  # clear of the "A' (westerly)" annotation just below
        ax_d.annotate(f"{hours[k]} h", (x, y), textcoords="offset points", xytext=(dx_txt, dy_txt), fontsize=7.2, color=TEXT_SECONDARY, ha=ha, va=va)

    onset_xy = _interp_crossing(traj, 0, HartCPS.B_THRESHOLD_M)
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

    for (bval, vval), label, off in (
        ((b1, vtl1), "A (easterly)", (0, -18)),
        ((b2, vtl2), "A′ (westerly)", (0, -18)),
    ):
        ax_d.plot(bval, vval, marker="D", markersize=8, markerfacecolor=VORTEX_A_COLOR, markeredgecolor="white", markeredgewidth=1.0, zorder=9)
        ax_d.annotate(
            f"{label}\nB={bval:+.0f} m", (bval, vval), textcoords="offset points", xytext=off, ha="center",
            fontsize=7.2, color=TEXT_DARK, fontweight="bold", va="top",
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

    hvtl_amb = HartCPS.executeBand3(
        z_std_stack[925.0], z_std_stack[850.0], z_std_stack[700.0], psfc, dx2d, dy_m,
        500.0, 925.0, 850.0, 700.0,
    )
    hvtu_amb = HartCPS.executeBand3(
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

    print("Building Figure 4 (vorticity vs Hart family, tilted cold core) ...")
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

    print("Done. Figures written to", OUT_DIR)


if __name__ == "__main__":
    main()
