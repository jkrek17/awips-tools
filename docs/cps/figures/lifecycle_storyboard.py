"""Storyboard and animation for the synthetic extratropical-transition life
cycle built by lifecycle_comparison.py.

Everything numeric here (the track, the height fields, both methods' B/VTL/
VTU/class) comes from lifecycle_comparison's own functions
(`compute_frame`, `build_heights`, `build_track_and_motion`, `build_grid`,
`env_fields`, `make_hours`) -- this script adds no physics or diagnostics of
its own, only maps and the two phase diagrams built from those same numbers.
Run from this directory:

    python3 lifecycle_storyboard.py

Writes two files next to this one:

- figE_lifecycle_storyboard.png (300 dpi): 6 rows (hour 0, 60, 90, 120, 144,
  168 -- the life cycle's six gridded classes 0, 2, 3, 4, 5, 1) by 5 columns:
  (a) 1000 hPa height and 1000-500 hPa thickness, (b) the gridded HCPSclass
  field, (c) 900-600 hPa thickness with the 500 km Hart circle, the 1000 km
  gridded square, and the motion arrow, (d) B versus -V_T^L, (e) -V_T^U
  versus -V_T^L, the last two drawn up to each row's own hour.
- lifecycle_storyboard.gif: the same five panels in one row, one frame per
  6 h (29 frames total), 500 ms per frame.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lifecycle_comparison import (  # noqa: E402
    hc, ch,
    make_hours, build_track_and_motion, build_grid, env_fields, compute_frame,
    RADIUS_KM, CLASS_PALETTE, CLASS_NAMES, RED, BLUE, PURPLE,
)
import diagram_style as ds  # noqa: E402  (make_fig10's own quadrant colors/labels/lines/limits)

SNAPSHOT_HOURS = [0.0, 60.0, 90.0, 120.0, 144.0, 168.0]
FIG_PATH = HERE / "figE_lifecycle_storyboard.png"
GIF_PATH = HERE / "lifecycle_storyboard.gif"

KM_PER_DEG_LAT = 111.32
CLASS_CMAP = ListedColormap([CLASS_PALETTE[k] for k in range(7)])
CLASS_CMAP.set_bad(alpha=0.0)
CLASS_NORM = BoundaryNorm(np.arange(-0.5, 7.5, 1.0), CLASS_CMAP.N)


# ----------------------------------------------------------- geometry
def km_circle(clat, clon, radius_km, n=73):
    """(lons, lats) tracing a circle of radius_km around (clat, clon), in
    the same flat local-Cartesian approximation lifecycle_comparison's own
    across_track_km/local_offsets_km use.
    """
    ang = np.linspace(0.0, 2.0 * np.pi, n)
    dlat = (radius_km / KM_PER_DEG_LAT) * np.cos(ang)
    dlon = (radius_km / (KM_PER_DEG_LAT * np.cos(np.radians(clat)))) * np.sin(ang)
    return clon + dlon, clat + dlat


def km_square(clat, clon, half_km):
    """(lons, lats) tracing a square of half-width half_km (so side
    2*half_km) around (clat, clon) -- the gridded module's own square
    analysis window, matching RADIUS_KM as its half-width.
    """
    dlat = half_km / KM_PER_DEG_LAT
    dlon = half_km / (KM_PER_DEG_LAT * np.cos(np.radians(clat)))
    lons = [clon - dlon, clon + dlon, clon + dlon, clon - dlon, clon - dlon]
    lats = [clat - dlat, clat - dlat, clat + dlat, clat + dlat, clat - dlat]
    return lons, lats


def motion_arrow_tip(clat, clon, heading_deg, length_km=400.0):
    """(lon, lat) of the tip of a motion arrow length_km long, pointing
    heading_deg (clockwise from north), starting at (clat, clon).
    """
    dlat = (length_km / KM_PER_DEG_LAT) * np.cos(np.radians(heading_deg))
    dlon = (length_km / (KM_PER_DEG_LAT * np.cos(np.radians(clat)))) * np.sin(np.radians(heading_deg))
    return clon + dlon, clat + dlat


def level_step(field, step):
    """np.arange levels spanning field's own min/max, snapped to step."""
    lo = np.floor(np.nanmin(field) / step) * step
    hi = np.ceil(np.nanmax(field) / step) * step
    if hi <= lo:
        hi = lo + step
    return np.arange(lo, hi + step, step)


def phase_diagram_limits(d):
    """(xlim_vtl, ylim_b, ylim_vtu): the same fixed article limits
    (diagram_style.FIG10_VTL_LIM/FIG10_B_LIM/FIG10_VTU_LIM) figD_lifecycle.png
    uses, widened only where this life cycle's own data exceeds them --
    identical computation to lifecycle_comparison.make_figure's, from the
    same data, so the storyboard and gif line up with figD_lifecycle.png
    exactly rather than approximating it.
    """
    xlim_vtl = ds.widen_limits(ds.FIG10_VTL_LIM, d["VTL_hart"], d["VTL_grid"])
    ylim_b = ds.widen_limits(ds.FIG10_B_LIM, d["B_hart"], d["B_grid"])
    ylim_vtu = ds.widen_limits(ds.FIG10_VTU_LIM, d["VTU_hart"], d["VTU_grid"])
    return xlim_vtl, ylim_b, ylim_vtu


# ------------------------------------------------------- data assembly
def compute_all_frames():
    """Every scalar and every map field this storyboard needs, for all 29
    frames, computed once via lifecycle_comparison.compute_frame (the exact
    same function lifecycle_comparison.py's own main() uses) so the numbers
    here cannot drift from figD_lifecycle.png's.
    """
    hours = make_hours()
    n = len(hours)
    lats, lons, headings, speeds = build_track_and_motion(hours)
    lat_vals, lon_vals, lat2d, lon2d, dx, dy = build_grid()
    psfc, coriolis = env_fields(lat2d)

    B_hart = np.full(n, np.nan)
    VTL_hart = np.full(n, np.nan)
    VTU_hart = np.full(n, np.nan)
    B_grid = np.full(n, np.nan)
    VTL_grid = np.full(n, np.nan)
    VTU_grid = np.full(n, np.nan)
    CLS_grid = np.full(n, np.nan)
    CLS_hart = np.full(n, np.nan)
    maps = []

    for i, t in enumerate(hours):
        clat, clon = float(lats[i]), float(lons[i])
        r = compute_frame(t, clat, clon, headings[i], speeds[i], lat2d, lon2d, lat_vals, lon_vals, dx, dy,
                           psfc, coriolis, return_fields=True)
        VTL_hart[i], VTU_hart[i], B_hart[i], CLS_hart[i] = r["VTL_hart"], r["VTU_hart"], r["B_hart"], r["CLS_hart"]
        VTL_grid[i], VTU_grid[i], B_grid[i], CLS_grid[i] = r["VTL_grid"], r["VTU_grid"], r["B_grid"], r["CLS_grid"]
        z = r["z"]
        maps.append(dict(
            z1000=z[1000],
            thick_1000_500=z[500] - z[1000],
            thick_900_600=z[600] - z[900],
            cls_full=r["cls_full"],
        ))

    return dict(
        hours=hours, lats=lats, lons=lons, headings=headings, speeds=speeds,
        lat_vals=lat_vals, lon_vals=lon_vals, lat2d=lat2d, lon2d=lon2d,
        B_hart=B_hart, VTL_hart=VTL_hart, VTU_hart=VTU_hart,
        B_grid=B_grid, VTL_grid=VTL_grid, VTU_grid=VTU_grid,
        CLS_grid=CLS_grid, CLS_hart=CLS_hart, maps=maps,
    )


# ------------------------------------------------------------- panels
def draw_panel_a(ax, d, i, fs=7):
    """1000 hPa height (solid dark gray, 40 m) and 1000-500 hPa thickness
    (dashed red, 60 m), the full track, and the current center.
    """
    m = d["maps"][i]
    cs_h = ax.contour(d["lon2d"], d["lat2d"], m["z1000"], levels=level_step(m["z1000"], 40.0),
                       colors="0.3", linewidths=0.6)
    ax.clabel(cs_h, fontsize=fs - 1, fmt="%d", inline=True)
    ax.contour(d["lon2d"], d["lat2d"], m["thick_1000_500"], levels=level_step(m["thick_1000_500"], 60.0),
               colors=RED, linewidths=0.6, linestyles="dashed")
    ax.plot(d["lons"], d["lats"], "-", color="0.6", lw=0.8, zorder=3)
    ax.plot(d["lons"][i], d["lats"][i], "o", color="k", ms=5, mec="white", mew=0.6, zorder=5)
    _map_axes(ax, d, fs)


def draw_panel_b(ax, d, i, fs=7):
    """The gridded HCPSclass field (NaN transparent), 1000 hPa height
    contours for context, the full track, and the current center.
    """
    m = d["maps"][i]
    lon_vals, lat_vals = d["lon_vals"], d["lat_vals"]
    extent = (lon_vals.min(), lon_vals.max(), lat_vals.min(), lat_vals.max())
    cls_masked = np.ma.masked_invalid(m["cls_full"])
    ax.imshow(cls_masked, extent=extent, origin="lower", cmap=CLASS_CMAP, norm=CLASS_NORM,
              interpolation="nearest", aspect="auto", zorder=1)
    ax.contour(d["lon2d"], d["lat2d"], m["z1000"], levels=level_step(m["z1000"], 40.0),
               colors="0.3", linewidths=0.5, zorder=2)
    ax.plot(d["lons"], d["lats"], "-", color="0.3", lw=0.8, zorder=3)
    ax.plot(d["lons"][i], d["lats"][i], "o", color="k", ms=5, mec="white", mew=0.6, zorder=5)
    _map_axes(ax, d, fs)


THICK_ANOM_LEVELS = np.arange(-88.0, 89.0, 16.0)  # bin -8..8 sits at the colormap's white center


def draw_panel_c(ax, d, i, fs=7):
    """Two layers, since the full 900-600 hPa thickness field saturates
    into two solid blocks (cold south, warm north) once the storm is deep
    in the baroclinic zone, hiding the one thing B actually samples (the
    storm's own motion-relative dipole):

    1. Filled contours of the thickness ANOMALY from its own zonal mean at
       each latitude (a fixed -80 to 80 m, 16 m scale, so the color scale
       never saturates or rescales frame to frame) -- this isolates the
       storm's warm core and dipole from the broad environmental gradient.
    2. Thin, unlabeled gray contour lines of the full thickness every 20 m,
       so the environmental gradient still reads as line spacing.

    Plus the 500 km Hart circle, the 1000 km gridded square, and the
    motion arrow.
    """
    m = d["maps"][i]
    clat, clon = d["lats"][i], d["lons"][i]
    thick = m["thick_900_600"]
    anomaly = thick - np.nanmean(thick, axis=1, keepdims=True)  # thick's own zonal (row-wise) mean

    ax.contourf(d["lon2d"], d["lat2d"], anomaly, levels=THICK_ANOM_LEVELS, cmap="RdBu_r", extend="both", zorder=1)
    ax.contour(d["lon2d"], d["lat2d"], thick, levels=level_step(thick, 20.0), colors="0.55", linewidths=0.4,
               zorder=2)

    circ_lon, circ_lat = km_circle(clat, clon, RADIUS_KM)
    ax.plot(circ_lon, circ_lat, "-", color="k", lw=1.1, zorder=4)
    sq_lon, sq_lat = km_square(clat, clon, RADIUS_KM)
    ax.plot(sq_lon, sq_lat, "--", color="k", lw=1.1, zorder=4)
    tip_lon, tip_lat = motion_arrow_tip(clat, clon, d["headings"][i])
    ax.annotate("", xy=(tip_lon, tip_lat), xytext=(clon, clat),
                arrowprops=dict(arrowstyle="-|>", color="k", lw=1.3), zorder=5)
    ax.plot(clon, clat, "o", color="k", ms=4, mec="white", mew=0.5, zorder=6)
    _map_axes(ax, d, fs)


def _map_axes(ax, d, fs):
    ax.set_xlim(d["lon_vals"].min(), d["lon_vals"].max())
    ax.set_ylim(d["lat_vals"].min(), d["lat_vals"].max())
    ax.grid(True, color="0.85", lw=0.4, zorder=0)
    ax.tick_params(labelsize=fs - 1)
    ax.set_xticks(np.arange(140, 191, 10))
    ax.set_yticks(np.arange(20, 61, 10))


def draw_panel_d(ax, d, i, xlim, ylim, fs=7, quad_fontsize=None):
    """B versus -V_T^L, both trajectories up to hour i, current points as
    large markers. Background (quadrant colors/labels, reference lines,
    grid, axis labels) and limits match make_figures.make_fig10 (the
    article's Figure 1) exactly, via diagram_style -- as in figD panel (a).

    `quad_fontsize` (default None, i.e. make_fig10's own corner-label size):
    the storyboard grid's own panels are narrower than figD's or the gif's,
    so build_storyboard passes a smaller size there to keep opposite
    corners' labels from running into each other.
    """
    j = i + 1
    ds.draw_b_vtl_quadrants(ax, xlim, ylim, 10.0, fontsize=quad_fontsize)
    ax.plot(d["VTL_hart"][:j], d["B_hart"][:j], "-o", color="0.6", ms=2.5, lw=0.9, mfc="0.6", zorder=2)
    ax.plot(d["VTL_grid"][:j], d["B_grid"][:j], "-s", color=RED, alpha=0.55, ms=2.5, lw=0.9, zorder=2)
    ax.plot(d["VTL_hart"][i], d["B_hart"][i], "o", color="0.15", ms=9, zorder=5)
    ax.plot(d["VTL_grid"][i], d["B_grid"][i], "s", color=RED, ms=9, zorder=5)
    ax.axhline(10.0, color=ds.TEXT_DARK, lw=1.0, zorder=3)
    ax.axvline(0.0, color=ds.TEXT_DARK, lw=1.0, zorder=3)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel(ds.AXIS_LABEL_VTL, fontsize=fs - 1)
    ax.set_ylabel(ds.AXIS_LABEL_B, fontsize=fs - 1)
    ax.grid(True, color=ds.GRID_COLOR, linewidth=0.5, zorder=0.2)
    ax.tick_params(labelsize=fs - 1)


def draw_panel_e(ax, d, i, xlim, ylim, fs=7, quad_fontsize=None):
    """-V_T^U versus -V_T^L, same treatment as panel (d) -- as in figD
    panel (b). "deep cold core"/"shallow warm core" nudged up off the x
    axis (make_fig10's own corner, where this life cycle's own trajectory
    actually passes, unlike make_fig10's schematic one) into the clear
    gap around -V_T^U = -100, same as figD_lifecycle.png panel (b).
    `quad_fontsize`: see draw_panel_d.
    """
    j = i + 1
    label_overrides = {
        "deep cold core": (xlim[0] * 0.95, ylim[0] * 0.33),
        "shallow warm core": (xlim[1] * 0.55, ylim[0] * 0.33),
    }
    ds.draw_vtu_vtl_quadrants(ax, xlim, ylim, label_overrides=label_overrides, fontsize=quad_fontsize)
    ax.plot(d["VTL_hart"][:j], d["VTU_hart"][:j], "-o", color="0.6", ms=2.5, lw=0.9, mfc="0.6", zorder=2)
    ax.plot(d["VTL_grid"][:j], d["VTU_grid"][:j], "-s", color=RED, alpha=0.55, ms=2.5, lw=0.9, zorder=2)
    ax.plot(d["VTL_hart"][i], d["VTU_hart"][i], "o", color="0.15", ms=9, zorder=5)
    ax.plot(d["VTL_grid"][i], d["VTU_grid"][i], "s", color=RED, ms=9, zorder=5)
    ax.axhline(0.0, color=ds.TEXT_DARK, lw=1.0, zorder=3)
    ax.axvline(0.0, color=ds.TEXT_DARK, lw=1.0, zorder=3)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel(ds.AXIS_LABEL_VTL, fontsize=fs - 1)
    ax.set_ylabel(ds.AXIS_LABEL_VTU, fontsize=fs - 1)
    ax.grid(True, color=ds.GRID_COLOR, linewidth=0.5, zorder=0.2)
    ax.tick_params(labelsize=fs - 1)


COLUMN_TITLES = (
    "(a) 1000 hPa height (m, about 8 m per hPa),\n1000-500 hPa thickness",
    "(b) HCPSclass",
    "(c) 900-600 hPa thickness (lines) and\nits anomaly from the zonal mean (fill)",
    "(d) B vs $-V_T^L$",
    "(e) $-V_T^U$ vs $-V_T^L$",
)


def row_label(hour, cls_code):
    name = CLASS_NAMES[int(round(cls_code))]
    name = name.replace(" ", "\n", 1) if len(name) > 12 else name  # wrap a long class name onto 2 lines
    return f"{hour:.0f} h\nclass {cls_code:.0f}\n({name})"


# ---------------------------------------------------------------- (1)
def build_storyboard(d):
    xlim_vtl, ylim_b, ylim_vtu = phase_diagram_limits(d)

    idxs = [int(round(h / 6.0)) for h in SNAPSHOT_HOURS]
    nrows = len(idxs)
    fig = plt.figure(figsize=(15.0, 17.0), constrained_layout=True)
    gs = fig.add_gridspec(nrows, 6, width_ratios=[0.5, 1, 1, 1, 1, 1])

    draw_fns = (draw_panel_a, draw_panel_b, draw_panel_c, draw_panel_d, draw_panel_e)
    for row, i in enumerate(idxs):
        label_ax = fig.add_subplot(gs[row, 0])
        label_ax.axis("off")
        label_ax.text(0.5, 0.5, row_label(d["hours"][i], d["CLS_grid"][i]), fontsize=8,
                       ha="center", va="center", linespacing=1.4)

        for col, draw_fn in enumerate(draw_fns):
            ax = fig.add_subplot(gs[row, col + 1])
            if draw_fn in (draw_panel_d, draw_panel_e):
                # Narrower panels than figD's or the gif's own (1 of 5.5 gridspec
                # columns in a 15 in figure): a smaller corner-label size than
                # make_fig10's own keeps opposite corners' labels apart.
                if draw_fn is draw_panel_d:
                    draw_fn(ax, d, i, xlim_vtl, ylim_b, quad_fontsize=5.0)
                else:
                    draw_fn(ax, d, i, xlim_vtl, ylim_vtu, quad_fontsize=5.0)
            else:
                draw_fn(ax, d, i)
            if row == 0:
                ax.set_title(COLUMN_TITLES[col], fontsize=8)

    fig.suptitle("Synthetic extratropical transition: storm-centered Hart method versus the gridded module",
                 fontsize=11)
    fig.savefig(FIG_PATH, dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------- (2)
def build_gif(d):
    """Render each of the 29 frames to its own Figure (100 dpi), each PNG
    encoded to an in-memory buffer, then hand the resulting list of images
    to Pillow's own GIF writer (Image.save(..., save_all=True)), 500 ms per
    frame. Verify a saved multi-frame GIF's distinct frames with
    Image.seek(i) (not ImageSequence.Iterator collected into a list and
    read back afterward: the Iterator yields the same underlying Image
    object at each seek position, so a list of it is a list of aliases to
    wherever that Image was last seeked, not independent per-frame copies).
    """
    xlim_vtl, ylim_b, ylim_vtu = phase_diagram_limits(d)

    n = len(d["hours"])
    draw_fns = (draw_panel_a, draw_panel_b, draw_panel_c, draw_panel_d, draw_panel_e)
    frame_images = []

    for i in range(n):
        fig, axes = plt.subplots(1, 5, figsize=(18.0, 3.8), dpi=100)
        for col, (ax, draw_fn) in enumerate(zip(axes, draw_fns)):
            if draw_fn is draw_panel_d:
                draw_fn(ax, d, i, xlim_vtl, ylim_b, fs=8)
            elif draw_fn is draw_panel_e:
                draw_fn(ax, d, i, xlim_vtl, ylim_vtu, fs=8)
            else:
                draw_fn(ax, d, i, fs=8)
            ax.set_title(COLUMN_TITLES[col], fontsize=8)
        fig.suptitle(f"hour {d['hours'][i]:.0f}, gridded class {d['CLS_grid'][i]:.0f} "
                     f"({CLASS_NAMES[int(round(d['CLS_grid'][i]))]})", fontsize=10)
        fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        plt.close(fig)
        buf.seek(0)
        frame_images.append(Image.open(buf).convert("RGB"))

    frame_images[0].save(
        GIF_PATH, save_all=True, append_images=frame_images[1:], duration=500, loop=0, optimize=True,
    )


def main():
    d = compute_all_frames()
    print(f"Computed {len(d['hours'])} frames "
          f"({d['lat2d'].shape[0]} x {d['lat2d'].shape[1]} grid) for the storyboard and gif.")

    build_storyboard(d)
    size_png = FIG_PATH.stat().st_size / 1e6
    print(f"wrote {FIG_PATH} ({size_png:.2f} MB)")

    build_gif(d)
    size_gif = GIF_PATH.stat().st_size / 1e6
    print(f"wrote {GIF_PATH} ({size_gif:.2f} MB)")


if __name__ == "__main__":
    main()
