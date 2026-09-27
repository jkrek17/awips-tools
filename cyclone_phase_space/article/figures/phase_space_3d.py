"""Hart's cyclone phase space in three dimensions, with the seven HCPSclass
cells and the synthetic archetype life cycles of `lifecycle_comparison.py`.

Hart's phase space is three numbers per storm: B (thermal asymmetry, m),
minus V_T^L (lower thermal wind, m) and minus V_T^U (upper thermal wind,
m). The gridded product's HCPSclass (`cps_HartCPS.hart_class`) is a
partition of that space: the planes B = 10 m, -V_T^L = 0 and -V_T^U = 0 cut
it into eight boxes, and the two boxes with a cold lower and warm upper
layer (either B) are merged into class 6. This script draws those seven
cells and, through them, the 168 h paths of the named life cycles in
`lifecycle_comparison.SCENARIOS`: the extratropical transition of Figure 13
(`figD_lifecycle.png`, the same arrays), a tropical cyclone that decays
without transition, a warm seclusion, a cold-core low that occludes, the
tropical transition of a subtropical storm and a hybrid that oscillates
about B = 10 m.

The physics is not copied: every path comes from
`lifecycle_comparison.run_scenario`, the per-frame loop of that script's
`main()` (make_hours, build_track_and_motion, build_grid, env_fields,
compute_frame) applied to the scenario's own synthetic height fields, with
Hart's storm-centered method (`cps.hart`) and the gridded method
(`cps_HartCPS`) evaluated at every frame.

Outputs (both in this directory):

    figJ_phase_space_3d.png   static small multiples, one panel per life
                              cycle from one viewing angle (matplotlib
                              mplot3d), 300 dpi
    phase_space_3d.html       interactive, self-contained Plotly page with
                              a button per life cycle (Plotly itself is
                              loaded from the jsDelivr CDN)

Run from this directory:

    python3 phase_space_3d.py

It prints each life cycle's class sequence (both methods), its onset
(first frame with B > 10 m) and completion (first frame with -V_T^L < 0)
hours and its plane crossings, then the axis limits and the timings.
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

import numpy as np

import lifecycle_comparison as lc  # sets up sys.path, Agg backend, hc.ORIENTATION_MODE
import diagram_style as ds

import matplotlib.pyplot as plt
from matplotlib import patheffects
from matplotlib.colors import to_hex
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d import proj3d
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

HERE = Path(__file__).resolve().parent
OUT_PNG = HERE / "figJ_phase_space_3d.png"
OUT_HTML = HERE / "phase_space_3d.html"

B_THR = float(lc.hc.B_THRESHOLD_M)  # 10 m

# Axis limits: x = -V_T^L, y = B, z = -V_T^U (all m), shared by every panel
# and every example. Widened (never narrowed) by diagram_style.widen_limits
# plus a margin if any life cycle exceeds them.
BASE_XLIM = (-320.0, 320.0)
BASE_YLIM = (-20.0, 80.0)
BASE_ZLIM = (-320.0, 320.0)

# HCPSclass colors: D2D/colormaps/Grid/CPS_HartClass.cmap, identical to
# lifecycle_comparison.CLASS_PALETTE (the Figure 13 class strips).
CLASS_PALETTE = lc.CLASS_PALETTE
CLASS_NAMES = lc.CLASS_NAMES
CLASS_HEX = {k: to_hex(v) for k, v in CLASS_PALETTE.items()}

HART_COLOR = "#8f8e89"
PATH_EDGE = "#3a3a37"
CELL_ALPHA = 0.10
VIEW = (20, -40)  # elevation, azimuth (degrees) of every static panel
BOX_ASPECT = (1.0, 1.2, 0.9)  # -V_T^L, B, -V_T^U: B drawn a little longer, its range being narrow
HOUR_STEP = 24.0

# Short button labels for the interactive page (the panel titles otherwise).
BUTTON_LABELS = {
    "extratropical_transition": "Extratropical transition",
    "tropical_decay": "Tropical decay",
    "warm_seclusion": "Warm seclusion",
    "cold_occlusion": "Cold occlusion",
    "tropical_transition": "Tropical transition",
    "hybrid": "Hybrid",
}

# One or two sentences per life cycle for the interactive page, in terms of
# the fields; the class sequence and the event hours are appended from the
# computed arrays.
NOTES = {
    "extratropical_transition": (
        "A typhoon recurving into the westerlies (Figure 13): the deep warm core profile blends to a "
        "transitioning and then a cold core profile while a storm-attached thickness dipole, warm to "
        "the right of the track, grows and then wraps into a late seclusion."),
    "tropical_decay": (
        "A tropical cyclone that weakens over cooler water south of the baroclinic zone: the deep warm "
        "core profile keeps its shape while its amplitude falls to 30 percent, with no dipole and no "
        "background gradient, so it never leaves the symmetric deep warm core cell."),
    "warm_seclusion": (
        "A frontal low (Shapiro-Keyser): a deep cold core with a strong dipole develops a shallow warm "
        "core as warm air is wrapped into the center, the dipole then decays so the secluded core is "
        "symmetric, and the low finally fills and turns cold again."),
    "cold_occlusion": (
        "An extratropical low that occludes: a deep cold core throughout, with a frontal dipole that "
        "decays as the warm sector is lifted off the center, so the low goes from asymmetric to "
        "symmetric cold core."),
    "tropical_transition": (
        "A subtropical storm becoming tropical: a cutoff cold low with a weak dipole builds a "
        "lower-tropospheric warm core under the cold air aloft, loses its asymmetry, and then its warm "
        "core deepens through the column."),
    "hybrid": (
        "A hybrid storm with a shallow warm core whose thickness dipole pulses with a 56 h period as "
        "short-wave troughs pass, so B swings back and forth across 10 m while both thermal wind "
        "terms hold their sign and the storm slowly deepens."),
}


# ------------------------------------------------------------------ data
def compute_all(keys=None):
    """[run_scenario result] for every scenario in lifecycle_comparison.SCENARIOS
    (or the given keys), in that order: the extratropical transition first."""
    return [lc.run_scenario(k) for k in (keys or list(lc.SCENARIOS))]


def events_of(d):
    """{"onset": i, "completion": i} for the gridded path, by the rule of
    lifecycle_comparison.main(): onset is the first frame with B > 10 m and
    completion the first with -V_T^L < 0. Each is kept only when it is a
    crossing, that is, when the storm did not start on that side of the
    plane: a low that is already asymmetric or cold core at 0 h has no
    onset or completion, and a later return across the plane (a seclusion
    turning cold again, say) is not one either."""
    hours = d["hours"]
    on, comp = lc.onset_completion(hours, d["B_grid"], d["VTL_grid"], B_THR)
    ev = {}
    for kind, h in (("onset", on), ("completion", comp)):
        if np.isfinite(h) and h > hours[0]:
            ev[kind] = int(np.argmin(np.abs(hours - h)))
    return ev


def class_sequence(d, method="grid"):
    return [c for _, _, c in lc.class_runs(d["hours"], d[f"CLS_{method}"])]


def sequence_text(d, method="grid", arrow=" → "):
    return arrow.join("none" if c is None else str(c) for c in class_sequence(d, method))


def axis_limits(ds_list):
    def widen(base, *arrs):
        lo, hi = ds.widen_limits(base, *arrs)
        pad = 0.05 * (base[1] - base[0])
        return (min(base[0], lo - pad) if lo < base[0] else base[0],
                max(base[1], hi + pad) if hi > base[1] else base[1])
    cat = {k: np.concatenate([d[f"{k}_{m}"] for d in ds_list for m in ("hart", "grid")])
           for k in ("VTL", "B", "VTU")}
    return widen(BASE_XLIM, cat["VTL"]), widen(BASE_YLIM, cat["B"]), widen(BASE_ZLIM, cat["VTU"])


def class_cells(xlim, ylim, zlim):
    """{class: (x0, x1, y0, y1, z0, z1)}: the seven HCPSclass cells clipped to
    the axis limits (x = -V_T^L, y = B, z = -V_T^U)."""
    (xa, xb), (ya, yb), (za, zb) = xlim, ylim, zlim
    return {
        0: (0.0, xb, ya, B_THR, 0.0, zb),
        1: (0.0, xb, ya, B_THR, za, 0.0),
        2: (0.0, xb, B_THR, yb, 0.0, zb),
        3: (0.0, xb, B_THR, yb, za, 0.0),
        4: (xa, 0.0, B_THR, yb, za, 0.0),
        5: (xa, 0.0, ya, B_THR, za, 0.0),
        6: (xa, 0.0, ya, yb, 0.0, zb),
    }


def label_position(c, box, ylim):
    """Where a cell's label goes in the interactive page: toward the cell's
    outer corner, 70 percent of the way out in -V_T^L and 85 percent in
    -V_T^U, and just inside its outer B face, where the life cycles (B
    about -10 to 40 m, thermal winds mostly inside +/-250 m) seldom go.
    Class 6 spans all B and is labeled at mid B."""
    x0, x1, y0, y1, z0, z1 = box
    if c == 6:
        y = (y0 + y1) / 2
    elif y1 <= B_THR:
        y = y0 + 0.08 * (ylim[1] - ylim[0])
    else:
        y = y1 - 0.08 * (ylim[1] - ylim[0])
    x = 0.7 * (x1 if abs(x1) > abs(x0) else x0)
    z = 0.85 * (z1 if abs(z1) > abs(z0) else z0)
    return x, y, z


def box_faces(x0, x1, y0, y1, z0, z1):
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
    idx = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4)]
    return [[v[i] for i in f] for f in idx]


def dividing_plane_outlines(xlim, ylim, zlim):
    """Polylines (lists of (x, y, z)) where each dividing plane meets the
    faces of the axis box, only where it actually separates two classes:
    -V_T^L = 0 and -V_T^U = 0 everywhere; B = 10 m everywhere except inside
    class 6 (cold lower, warm upper), which spans both sides of it."""
    (xa, xb), (ya, yb), (za, zb) = xlim, ylim, zlim
    return [
        [(0, ya, za), (0, yb, za), (0, yb, zb), (0, ya, zb), (0, ya, za)],   # -VTL = 0
        [(xa, ya, 0), (xb, ya, 0), (xb, yb, 0), (xa, yb, 0), (xa, ya, 0)],   # -VTU = 0
        # B = 10: L-shaped (the x < 0, z > 0 quadrant belongs to class 6)
        [(0, B_THR, zb), (xb, B_THR, zb), (xb, B_THR, za), (xa, B_THR, za), (xa, B_THR, 0), (0, B_THR, 0),
         (0, B_THR, zb)],
    ]


def class_segments(x, y, z, cls):
    """{class: [polyline]} splitting a path at the midpoints between frames, so
    each frame's stretch of path (half a segment either side of it) carries
    that frame's class color and a change of class shows exactly between the
    two frames where it happens."""
    p = np.column_stack([x, y, z]).astype(float)
    n = len(p)
    out = {}
    for i in range(n):
        if not np.isfinite(cls[i]) or not np.all(np.isfinite(p[i])):
            continue
        pts = []
        if i > 0 and np.all(np.isfinite(p[i - 1])):
            pts.append((p[i - 1] + p[i]) / 2)
        pts.append(p[i])
        if i < n - 1 and np.all(np.isfinite(p[i + 1])):
            pts.append((p[i] + p[i + 1]) / 2)
        if len(pts) > 1:
            out.setdefault(int(round(cls[i])), []).append(np.array(pts))
    return out


# --------------------------------------------------------------- figure
def _halo(width=2.2):
    return patheffects.withStroke(linewidth=width, foreground="white")


def _annotate3d(ax, xyz, text, offset, **kw):
    """Label a 3-D point at a fixed screen offset (points): the point is
    projected with this view's own projection matrix and annotated in the
    axes' 2-D projected coordinates (the view is fixed before this call)."""
    x2, y2, _ = proj3d.proj_transform(*xyz, ax.get_proj())
    dx, dy, ha = offset
    ax.annotate(text, xy=(x2, y2), xycoords="data", xytext=(dx, dy), textcoords="offset points",
                ha=ha, va="bottom" if dy > 0 else "top", color=ds.TEXT_DARK, zorder=12,
                path_effects=[_halo()], **kw)


def _proj2d(ax, pts):
    x2, y2, _ = proj3d.proj_transform(pts[:, 0], pts[:, 1], pts[:, 2], ax.get_proj())
    return np.column_stack([x2, y2])


def place_cell_labels(ax, cells, traj, lims, extra_avoid=None):
    """{class: (x, y, z)} for the class numbers in this panel's view: of a
    5 x 5 x 5 lattice of candidate points inside each cell, the one nearest
    the cell's centroid whose screen projection keeps a set clearance from
    the paths (densified along their segments) and from the labels already
    placed; failing that, the candidate with the most clearance."""
    traj = traj[np.all(np.isfinite(traj), axis=1)]
    dense = np.concatenate([np.linspace(a, b, 8, endpoint=False) for a, b in zip(traj[:-1], traj[1:])]
                           + [traj[-1:]])
    avoid = _proj2d(ax, dense)
    if extra_avoid is not None and len(extra_avoid):
        avoid = np.vstack([avoid, extra_avoid])
    corners = np.array([[x, y, z] for x in lims[0] for y in lims[1] for z in lims[2]])
    span = np.ptp(_proj2d(ax, corners), axis=0).max()
    clearance = 0.06 * span
    fr = np.linspace(0.15, 0.85, 5)
    placed = {}
    for c, (x0, x1, y0, y1, z0, z1) in cells.items():
        g = np.array([[x0 + a * (x1 - x0), y0 + b * (y1 - y0), z0 + e * (z1 - z0)]
                      for a in fr for b in fr for e in fr])
        rel = np.array([[a - 0.5, b - 0.5, e - 0.5] for a in fr for b in fr for e in fr])
        g2 = _proj2d(ax, g)
        pts = avoid if not placed else np.vstack([avoid, _proj2d(ax, np.array(list(placed.values())))])
        dist = np.min(np.linalg.norm(g2[:, None, :] - pts[None, :, :], axis=2), axis=1)
        ok = dist >= clearance
        best = np.argmin(np.where(ok, np.linalg.norm(rel, axis=1), np.inf)) if ok.any() else np.argmax(dist)
        placed[c] = tuple(g[best])
    return placed


def _label_box(anchor, off, text, fontsize):
    """(x0, y0, x1, y1) in points of a label of `text` placed at `off`
    (dx, dy, ha) from `anchor`, approximating glyph widths."""
    dx, dy, ha = off
    w, h = 0.6 * fontsize * len(text), 1.1 * fontsize
    x = anchor[0] + dx
    x0 = x if ha == "left" else (x - w if ha == "right" else x - w / 2)
    y0 = anchor[1] + dy if dy > 0 else anchor[1] + dy - h
    return np.array([x0, y0, x0 + w, y0 + h])


def _choose_label(anchor, text, fontsize, dist, path_pts, boxes):
    """(offset, box, clash) for a label near `anchor` (points): of eight
    directions at `dist` points, the one whose box covers the fewest path
    points and does not overlap a label already placed (`boxes`); `clash`
    is True when every direction overlaps one."""
    best = None
    for k, ang in enumerate(np.radians([45, 135, -45, -135, 90, -90, 0, 180])):
        ux, uy = np.cos(ang), np.sin(ang)
        off = (dist * ux, dist * uy if abs(uy) > 0.1 else 0.1 * dist, "left" if ux > 0.3 else
               ("right" if ux < -0.3 else "center"))
        box = _label_box(anchor, off, text, fontsize)
        pad = 1.5
        inside = np.sum((path_pts[:, 0] > box[0] - pad) & (path_pts[:, 0] < box[2] + pad)
                        & (path_pts[:, 1] > box[1] - pad) & (path_pts[:, 1] < box[3] + pad))
        clash = any(box[0] < b[2] + 2 and b[0] < box[2] + 2 and box[1] < b[3] + 2 and b[1] < box[3] + 2
                    for b in boxes)
        score = (1000 if clash else 0) + inside + 0.01 * k
        if best is None or score < best[0]:
            best = (score, off, box, clash)
    return best[1], best[2], best[3]


def draw_panel(ax, d, lims, letter):
    xlim, ylim, zlim = lims
    hours = d["hours"]
    cells = class_cells(*lims)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_zlim(*zlim)
    ax.set_box_aspect(BOX_ASPECT, zoom=0.95)
    ax.view_init(elev=VIEW[0], azim=VIEW[1])
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.set_facecolor((1, 1, 1, 0))
        pane.set_edgecolor(ds.GRID_COLOR)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis._axinfo["grid"].update(color=ds.GRID_COLOR, linewidth=0.35)

    # -- the seven cells, translucent, edges light
    for c, box in cells.items():
        poly = Poly3DCollection(box_faces(*box), facecolor=CLASS_PALETTE[c], alpha=CELL_ALPHA,
                                edgecolor=(0.3, 0.3, 0.3, 0.12), linewidth=0.25)
        poly.set_zorder(1)
        ax.add_collection3d(poly)
    for line in dividing_plane_outlines(*lims):
        p = np.array(line, dtype=float)
        ax.plot(p[:, 0], p[:, 1], p[:, 2], color=ds.TEXT_SECONDARY, lw=0.5, alpha=0.6, zorder=2)

    # -- hour labels (start, end, every 24 h), chosen first so the class
    # numbers can keep clear of them too: each in the direction that covers
    # the least of the paths, skipped where it would overlap one already
    # placed (the ends are placed first)
    n = len(hours) - 1
    pts = np.column_stack([d["VTL_grid"], d["B_grid"], d["VTU_grid"]])
    to_pt = 72.0 / ax.figure.dpi
    screen = ax.transData.transform(_proj2d(ax, pts)) * to_pt  # points
    both = np.concatenate([np.column_stack([d[f"VTL_{m}"], d[f"B_{m}"], d[f"VTU_{m}"]]) for m in ("grid", "hart")])
    both = both[np.all(np.isfinite(both), axis=1)]
    dense = np.concatenate([np.linspace(a, b, 6, endpoint=False) for a, b in zip(both[:-1], both[1:])])
    path_pts = ax.transData.transform(_proj2d(ax, dense)) * to_pt
    hour_labels, boxes = [], []
    order = [0, n] + [i for i, h in enumerate(hours) if h % HOUR_STEP == 0 and 0 < i < n]
    for i in order:
        bold = i in (0, n)
        text = f"{hours[i]:.0f}" + (" h" if bold else "")
        fs = 7.0 if bold else 6.3
        off, box, clash = _choose_label(screen[i], text, fs, 7.5 if bold else 5.0, path_pts, boxes)
        if clash:
            continue
        boxes.append(box)
        hour_labels.append((i, bold, off))
    anchors = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    label_avoid = (ax.transData.inverted().transform(np.array(anchors) / to_pt) if anchors else None)

    traj = np.concatenate([np.column_stack([d[f"VTL_{m}"], d[f"B_{m}"], d[f"VTU_{m}"]]) for m in ("hart", "grid")])
    for c, pos in place_cell_labels(ax, cells, traj, lims, label_avoid).items():
        ax.text(*pos, str(c), color=CLASS_PALETTE[c], fontsize=9, fontweight="bold", ha="center", va="center",
                zorder=3, path_effects=[_halo(2.0)])

    # -- Hart's path: thin gray line and small open circles
    ax.plot(d["VTL_hart"], d["B_hart"], d["VTU_hart"], "-", color=HART_COLOR, lw=0.8, alpha=0.9, zorder=4)
    ax.scatter(d["VTL_hart"], d["B_hart"], d["VTU_hart"], s=7, marker="o", facecolor="white",
               edgecolor=HART_COLOR, linewidth=0.6, depthshade=False, zorder=5)

    # -- gridded path colored by class: a dark casing, then class-colored halves
    ax.plot(d["VTL_grid"], d["B_grid"], d["VTU_grid"], "-", color=PATH_EDGE, lw=2.6, alpha=0.85, zorder=6,
            solid_capstyle="round")
    for c, segs in class_segments(d["VTL_grid"], d["B_grid"], d["VTU_grid"], d["CLS_grid"]).items():
        lc3 = Line3DCollection(segs, colors=[CLASS_PALETTE[c]], linewidths=1.6, zorder=7)
        ax.add_collection3d(lc3)
    ok = np.isfinite(d["CLS_grid"])
    cols = [CLASS_PALETTE[int(round(c))] for c in d["CLS_grid"][ok]]
    ax.scatter(d["VTL_grid"][ok], d["B_grid"][ok], d["VTU_grid"][ok], s=13, marker="s", c=cols,
               edgecolor=PATH_EDGE, linewidth=0.45, depthshade=False, zorder=8)

    # -- start and end markers, then the hour labels chosen above
    for i, marker, size in ((0, "o", 46), (n, "s", 40)):
        ax.scatter([d["VTL_grid"][i]], [d["B_grid"][i]], [d["VTU_grid"][i]], s=size, marker=marker,
                   facecolor="none", edgecolor=ds.TEXT_DARK, linewidth=1.2, depthshade=False, zorder=9)
    for i, bold, off in hour_labels:
        _annotate3d(ax, tuple(pts[i]), f"{hours[i]:.0f}" + (" h" if bold else ""), off,
                    fontsize=6.3 if not bold else 7.0, fontweight="bold" if bold else "normal")

    # -- onset and completion crossings of the gridded path
    for kind, i in events_of(d).items():
        ax.scatter([d["VTL_grid"][i]], [d["B_grid"][i]], [d["VTU_grid"][i]], marker="x", s=48,
                   color=ds.TEXT_DARK, linewidth=1.4, depthshade=False, zorder=10)

    ax.set_xlabel(ds.AXIS_LABEL_VTL, labelpad=-4, fontsize=8)
    ax.set_ylabel(ds.AXIS_LABEL_B, labelpad=-4, fontsize=8)
    ax.zaxis.set_rotate_label(False)
    ax.set_zlabel(ds.AXIS_LABEL_VTU, labelpad=-2, rotation=90, fontsize=8)
    ax.set_xticks([-300, -150, 0, 150, 300])
    ax.set_yticks([-20, 10, 40, 70] if ylim == BASE_YLIM else ax.get_yticks())
    ax.set_zticks([-300, -150, 0, 150, 300])
    ax.tick_params(axis="both", which="major", pad=-2, labelsize=6.5)


def panel_title(d, letter):
    sc = d["scenario"]
    ev = events_of(d)
    parts = []
    if "onset" in ev:
        parts.append(f"onset {d['hours'][ev['onset']]:.0f} h")
    if "completion" in ev:
        parts.append(f"completion {d['hours'][ev['completion']]:.0f} h")
    line2 = "classes " + sequence_text(d)
    if parts:
        line2 += " (" + ", ".join(parts) + ")"
    return f"({letter}) {sc.title}", line2


def make_png(ds_list, lims):
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8, "text.color": ds.TEXT_DARK,
        "axes.labelcolor": ds.TEXT_DARK, "xtick.color": ds.TEXT_SECONDARY, "ytick.color": ds.TEXT_SECONDARY,
        "axes.linewidth": 0.6, "legend.fontsize": 7.5,
    })
    ncol = 3
    nrow = int(np.ceil(len(ds_list) / ncol))
    fig_w, row_h, legend_h = 12.0, 4.05, 1.1
    fig_h = nrow * row_h + legend_h
    fig = plt.figure(figsize=(fig_w, fig_h))
    pw, ph = 1.0 / ncol, row_h / fig_h
    for k, d in enumerate(ds_list):
        r, c = divmod(k, ncol)
        x0 = c * pw
        y0 = 1.0 - (r + 1) * ph
        ax = fig.add_axes([x0 - 0.022, y0 - 0.012, pw - 0.004, ph * 0.93], projection="3d", computed_zorder=False)
        letter = "abcdefghij"[k]
        draw_panel(ax, d, lims, letter)
        t1, t2 = panel_title(d, letter)
        fig.text(x0 + 0.018, y0 + ph - 0.012, t1, fontsize=9.5, fontweight="bold", ha="left", va="top")
        fig.text(x0 + 0.018, y0 + ph - 0.012 - 0.20 / fig_h, t2, fontsize=7.8, color=ds.TEXT_SECONDARY,
                 ha="left", va="top")

    class_handles = [Patch(facecolor=CLASS_PALETTE[c], alpha=0.6, edgecolor="none", label=f"{c}  {CLASS_NAMES[c]}")
                     for c in range(7)]
    fig.legend(handles=class_handles, loc="lower left", bbox_to_anchor=(0.015, 0.004), ncol=4, fontsize=7.3,
               frameon=False, title="HCPSclass cells (B = 10 m, $-V_T^L$ = 0, $-V_T^U$ = 0), path colored by class",
               title_fontsize=7.8, handlelength=1.3, columnspacing=1.1, alignment="left")
    path_handles = [
        Line2D([0], [0], marker="s", color=PATH_EDGE, markerfacecolor=CLASS_HEX[0], markeredgecolor=PATH_EDGE,
               lw=1.6, markersize=4.5, label="gridded, standard levels"),
        Line2D([0], [0], marker="o", color=HART_COLOR, markerfacecolor="white", lw=0.8, markersize=3.5,
               label="Hart, 50 hPa levels"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="none", markeredgecolor=ds.TEXT_DARK,
               markersize=6.5, markeredgewidth=1.1, label="start (0 h), hours every 24 h"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="none", markeredgecolor=ds.TEXT_DARK,
               markersize=6, markeredgewidth=1.1, label="end (168 h)"),
        Line2D([0], [0], marker="x", color=ds.TEXT_DARK, lw=0, markersize=6, markeredgewidth=1.4,
               label="onset (B rises past 10 m), completion ($-V_T^L$ turns negative)"),
    ]
    fig.legend(handles=path_handles, loc="lower right", bbox_to_anchor=(0.995, 0.004), ncol=1, fontsize=7.3,
               frameon=False, title="Synthetic life cycles, 0 to 168 h, 6 h frames", title_fontsize=7.8,
               handlelength=1.8, columnspacing=1.1, alignment="left")
    fig.savefig(OUT_PNG, dpi=300, facecolor="white")
    plt.close(fig)


# ----------------------------------------------------------------- html
def _r(a):
    return [None if not np.isfinite(v) else round(float(v), 1) for v in np.asarray(a, dtype=float)]


def _cls_label(c):
    if not np.isfinite(c):
        return "none"
    c = int(round(c))
    return f"{c} ({CLASS_NAMES[c]})"


def _vtl_html():
    return "&minus;V<sub>T</sub><sup>L</sup>"


def _vtu_html():
    return "&minus;V<sub>T</sub><sup>U</sup>"


def scenario_traces(d, key):
    """The Plotly traces of one life cycle, each tagged with meta = key."""
    hours = d["hours"]
    traces = []

    def hover(i, m):
        return (f"hour {hours[i]:.0f}<br>B {d[f'B_{m}'][i]:.1f} m<br>{_vtl_html()} {d[f'VTL_{m}'][i]:.1f} m"
                f"<br>{_vtu_html()} {d[f'VTU_{m}'][i]:.1f} m<br>class {_cls_label(d[f'CLS_{m}'][i])}")

    # Hart's storm-centered path: thin gray line, small open circles
    traces.append(dict(
        type="scatter3d", mode="lines+markers", name="Hart, 50 hPa levels", legendgroup="hart",
        x=_r(d["VTL_hart"]), y=_r(d["B_hart"]), z=_r(d["VTU_hart"]),
        line=dict(color=HART_COLOR, width=2),
        marker=dict(size=2.5, symbol="circle", color="#ffffff", line=dict(color=HART_COLOR, width=1)),
        text=["Hart, 50 hPa levels<br>" + hover(i, "hart") for i in range(len(hours))],
        hovertemplate="%{text}<extra></extra>",
    ))
    # gridded path: dark casing, then one trace per class of half-segments
    traces.append(dict(
        type="scatter3d", mode="lines", name="gridded, standard levels", legendgroup="grid", showlegend=False,
        x=_r(d["VTL_grid"]), y=_r(d["B_grid"]), z=_r(d["VTU_grid"]), hoverinfo="skip",
        line=dict(color=PATH_EDGE, width=9),
    ))
    for c, segs in sorted(class_segments(d["VTL_grid"], d["B_grid"], d["VTU_grid"], d["CLS_grid"]).items()):
        xs, ys, zs = [], [], []
        for s in segs:
            xs += _r(s[:, 0]) + [None]
            ys += _r(s[:, 1]) + [None]
            zs += _r(s[:, 2]) + [None]
        traces.append(dict(type="scatter3d", mode="lines", legendgroup="grid", showlegend=False,
                           x=xs, y=ys, z=zs, hoverinfo="skip", line=dict(color=CLASS_HEX[c], width=6)))
    cols = [CLASS_HEX[int(round(c))] if np.isfinite(c) else "#ffffff" for c in d["CLS_grid"]]
    traces.append(dict(
        type="scatter3d", mode="markers", name="gridded, standard levels (colored by class)", legendgroup="grid",
        x=_r(d["VTL_grid"]), y=_r(d["B_grid"]), z=_r(d["VTU_grid"]),
        marker=dict(size=4, symbol="square", color=cols, line=dict(color=PATH_EDGE, width=1)),
        text=["gridded, standard levels<br>" + hover(i, "grid") for i in range(len(hours))],
        hovertemplate="%{text}<extra></extra>",
    ))
    # start and end
    n = len(hours) - 1
    traces.append(dict(
        type="scatter3d", mode="markers", name="start (0 h) and end (168 h)", legendgroup="ends",
        x=_r(d["VTL_grid"][[0, n]]), y=_r(d["B_grid"][[0, n]]), z=_r(d["VTU_grid"][[0, n]]),
        marker=dict(size=[12, 11], symbol=["circle-open", "square-open"], color=ds.TEXT_DARK, line=dict(width=3)),
        text=[f"start, {hours[0]:.0f} h", f"end, {hours[n]:.0f} h"], hovertemplate="%{text}<extra></extra>",
    ))
    # hour labels every 24 h, nudged up the -VTU axis so they sit beside the
    # path; a label is left out where it would sit on one already kept (the
    # ends first), measured in axis-range units
    span = np.array([BASE_XLIM[1] - BASE_XLIM[0], BASE_YLIM[1] - BASE_YLIM[0], BASE_ZLIM[1] - BASE_ZLIM[0]])
    pts = np.column_stack([d["VTL_grid"], d["B_grid"], d["VTU_grid"]]) / span
    idx = []
    for i in [0, n] + [i for i, h in enumerate(hours) if h % HOUR_STEP == 0 and 0 < i < n]:
        if all(np.linalg.norm(pts[i] - pts[j]) > 0.08 for j in idx):
            idx.append(i)
    idx.sort()
    traces.append(dict(
        type="scatter3d", mode="text", name="hours every 24 h", legendgroup="hours", showlegend=True,
        x=_r(d["VTL_grid"][idx]), y=_r(d["B_grid"][idx]), z=_r(d["VTU_grid"][idx] + 18.0),
        text=[f"{hours[i]:.0f} h" for i in idx], hoverinfo="skip",
        textfont=dict(color=ds.TEXT_DARK, size=[13 if i in (0, n) else 11 for i in idx]),
    ))
    # onset and completion crossings
    ev = events_of(d)
    if ev:
        ii = [ev[k] for k in ("onset", "completion") if k in ev]
        labels = [f"{k} {hours[ev[k]]:.0f} h" for k in ("onset", "completion") if k in ev]
        traces.append(dict(
            type="scatter3d", mode="markers+text", name="onset and completion", legendgroup="events",
            x=_r(d["VTL_grid"][ii]), y=_r(d["B_grid"][ii]), z=_r(d["VTU_grid"][ii]),
            text=labels, textposition="middle right", textfont=dict(color=ds.TEXT_DARK, size=12),
            hovertext=[{"onset": "onset: B first rises above 10 m",
                        "completion": "completion: " + "-V<sub>T</sub><sup>L</sup> first turns negative"}[k]
                       + f", {hours[ev[k]]:.0f} h" for k in ("onset", "completion") if k in ev],
            hovertemplate="%{hovertext}<extra></extra>",
            marker=dict(symbol="x", size=6, color=ds.TEXT_DARK),
        ))
    for t in traces:
        t["meta"] = key
        t["visible"] = False
    return traces


def shared_traces(lims):
    xlim, ylim, zlim = lims
    cells = class_cells(xlim, ylim, zlim)
    traces = []
    tri_i = [0, 0, 4, 4, 0, 0, 3, 3, 1, 1, 0, 0]
    tri_j = [1, 2, 5, 6, 1, 5, 2, 6, 2, 6, 3, 7]
    tri_k = [2, 3, 6, 7, 5, 4, 6, 7, 6, 5, 7, 4]
    for c, (x0, x1, y0, y1, z0, z1) in cells.items():
        traces.append(dict(
            type="mesh3d", name=f"{c}  {CLASS_NAMES[c]}", legendgroup=f"c{c}", showlegend=True,
            x=[x0, x1, x1, x0, x0, x1, x1, x0], y=[y0, y0, y1, y1, y0, y0, y1, y1],
            z=[z0, z0, z0, z0, z1, z1, z1, z1], i=tri_i, j=tri_j, k=tri_k,
            color=CLASS_HEX[c], opacity=0.12, flatshading=True,
            lighting=dict(ambient=1.0, diffuse=0.0, specular=0.0, fresnel=0.0),
            hovertemplate=f"class {c}<br>{CLASS_NAMES[c]}<extra></extra>",
        ))
        x, y, z = label_position(c, (x0, x1, y0, y1, z0, z1), ylim)
        traces.append(dict(
            type="scatter3d", mode="text", legendgroup=f"c{c}", showlegend=False, hoverinfo="skip",
            x=[x], y=[y], z=[z], text=[f"<b>{c}</b> {CLASS_NAMES[c]}"],
            textfont=dict(color=CLASS_HEX[c] if c not in (2, 6) else {2: "#a88b00", 6: "#77766f"}[c], size=11),
        ))
    xs, ys, zs = [], [], []
    for line in dividing_plane_outlines(xlim, ylim, zlim):
        for p in line:
            xs.append(p[0]); ys.append(p[1]); zs.append(p[2])
        xs.append(None); ys.append(None); zs.append(None)
    traces.append(dict(type="scatter3d", mode="lines", name="planes B = 10 m, -VTL = 0, -VTU = 0",
                       x=xs, y=ys, z=zs, hoverinfo="skip", line=dict(color=ds.TEXT_SECONDARY, width=2)))
    for t in traces:
        t["meta"] = "shared"
        t["visible"] = True
    return traces


def scenario_note(d):
    sc, hours = d["scenario"], d["hours"]
    runs = lc.class_runs(hours, d["CLS_grid"])
    seq = ", ".join(f"{c} from {h0:.0f} to {h1:.0f} h" if h1 > h0 else f"{c} at {h0:.0f} h"
                    for h0, h1, c in runs)
    ev = events_of(d)
    if ev:
        evs = " and ".join(f"{k} at {hours[i]:.0f} h" for k, i in ev.items())
        evs = f"The x marks {evs}."
    else:
        evs = "There is no onset or completion crossing to mark."
    same = class_sequence(d, "hart") == class_sequence(d, "grid")
    hart = ("Hart's storm-centered method passes through the same classes in the same order."
            if same else f"Hart's storm-centered method reads {sequence_text(d, 'hart', ', ')}.")
    return f"{NOTES.get(sc.key, sc.summary)} Gridded classes: {seq}. {evs} {hart}"


def make_html(ds_list, lims):
    xlim, ylim, zlim = lims
    traces = shared_traces(lims)
    examples = []
    for d in ds_list:
        key = d["scenario"].key
        traces += scenario_traces(d, key)
        ev = events_of(d)
        evs = "; ".join(f"{k} {d['hours'][i]:.0f} h" for k, i in ev.items()) or "no onset or completion crossing"
        examples.append(dict(key=key, title=d["scenario"].title,
                             summary=f"Gridded classes {sequence_text(d)}; {evs}.",
                             note=scenario_note(d)))

    def axis(title, rng, dtick):
        return dict(title=dict(text=title), range=list(rng), dtick=dtick, backgroundcolor="#ffffff",
                    gridcolor="#dedcd5", zerolinecolor="#dedcd5", showbackground=False)

    layout = dict(
        paper_bgcolor="#ffffff", margin=dict(l=0, r=0, t=0, b=0), uirevision="keep",
        font=dict(family='-apple-system, "Segoe UI", Helvetica, Arial, sans-serif', size=12, color="#1a1a1a"),
        legend=dict(x=0.0, y=1.0, bgcolor="rgba(255,255,255,0.8)", font=dict(size=11), itemsizing="constant"),
        scene=dict(
            xaxis=axis("-V<sub>T</sub><sup>L</sup>, lower thermal wind (m)", xlim, 100),
            yaxis=axis("B, thermal asymmetry (m)", ylim, 20),
            zaxis=axis("-V<sub>T</sub><sup>U</sup>, upper thermal wind (m)", zlim, 100),
            aspectmode="manual", aspectratio=dict(x=1, y=1, z=0.9),
            camera=dict(eye=dict(x=1.35, y=-1.65, z=0.8)),
            uirevision="keep",
        ),
    )
    config = dict(responsive=True, displaylogo=False)
    payload = dict(data=traces, layout=layout, config=config, examples=examples)
    fig_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    buttons = "\n".join(
        f'  <button type="button" data-key="{html.escape(e["key"])}" aria-pressed="false">'
        f'{html.escape(BUTTON_LABELS.get(e["key"], e["title"]))}</button>' for e in examples)
    title = "Cyclone phase space: the seven HCPSclass cells and six synthetic life cycles"
    intro = (
        "Each axis is one of Hart's three phase-space parameters: the lower thermal wind "
        f"{_vtl_html()}, the thermal asymmetry B and the upper thermal wind {_vtu_html()}, all in meters. "
        f"The planes B = 10 m, {_vtl_html()} = 0 and {_vtu_html()} = 0 divide the space into the seven "
        "colored HCPSclass cells; class 6 (cold below, warm above) spans both sides of B = 10 m. Choose a "
        "life cycle with the buttons: each is a synthetic 168 h storm whose height fields are built from a "
        "vortex profile, a thermal dipole across the track, a background gradient and a track, and whose "
        "path is computed frame by frame by the gridded method (squares, colored by class) and by Hart's "
        "storm-centered method (gray circles). Hover over a point for its hour, values and class; drag to "
        "rotate, scroll to zoom; the view is kept when you switch."
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cyclone phase space 3D</title>
<style>
  html, body {{ background: #ffffff; color: #1a1a1a; margin: 0; }}
  body {{ font-family: Georgia, "Times New Roman", serif; font-size: 17px; line-height: 1.55; padding: 0 16px; }}
  h1 {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 1.05em;
        line-height: 1.3; margin: 0.7em 0 0.45em; }}
  .examples {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 0.35em; }}
  .examples button {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 13px;
        line-height: 1.2; color: #1a1a1a; background: #f7f6f2; border: 1px solid #d8d5cc; border-radius: 4px;
        padding: 5px 9px; cursor: pointer; }}
  .examples button:hover {{ border-color: #8f8e89; }}
  .examples button:focus-visible {{ outline: 2px solid #1a4f8b; outline-offset: 1px; }}
  .examples button[aria-pressed="true"] {{ background: #1a1a1a; border-color: #1a1a1a; color: #ffffff; }}
  p.current {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 13px;
        color: #52514e; margin: 0 0 0.2em; }}
  #plot {{ width: 100%; height: 72vh; min-height: 380px; }}
  @media (max-width: 899px) {{ #plot {{ height: 92vh; min-height: 560px; }} }}
  body.embedded h1 {{ display: none; }}
  body.embedded .examples {{ margin-top: 8px; }}
  body.embedded #plot {{ min-height: 360px; }}
  p.about {{ max-width: 46em; margin: 0.6em 0 0; font-size: 0.9em; color: #1a1a1a; }}
  p.note {{ max-width: 46em; margin: 0.6em 0 1.2em; font-size: 0.9em; color: #3a3a37; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<div class="examples" role="group" aria-label="Life cycle shown">
{buttons}
</div>
<p class="current" id="current" aria-live="polite"></p>
<div id="plot"></div>
<p class="about" id="about"></p>
<p class="note">{intro}</p>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.3/plotly.min.js"></script>
<script>
  (function () {{
    var fig = {fig_json};
    var el = document.getElementById("plot");
    var current = document.getElementById("current");
    var about = document.getElementById("about");
    // Inside the article's iframe the article supplies the title, and the
    // plot fills the frame below the buttons.
    var embedded = window.self !== window.top;
    if (embedded) {{ document.body.className = "embedded"; }}
    // On a narrow screen the plot is kept not much taller than it is wide,
    // since the scene scales to the shorter side.
    function fitPlot() {{
      if (embedded) {{
        var top = el.getBoundingClientRect().top + window.pageYOffset;
        el.style.height = Math.max(360, window.innerHeight - top - 6) + "px";
      }} else if (el.clientWidth < 900) {{
        el.style.height = Math.round(Math.min(window.innerHeight * 0.92, Math.max(420, el.clientWidth * 1.25))) + "px";
      }} else {{
        el.style.height = "";
      }}
    }}
    fitPlot();
    var buttons = Array.prototype.slice.call(document.querySelectorAll(".examples button"));
    var keys = fig.examples.map(function (e) {{ return e.key; }});
    // Legend beside the scene on wide screens, across the top of it on
    // narrow ones (phones, or the page inside the article's iframe), where
    // the scene leaves a band free.
    var wideLegend = fig.layout.legend;
    var narrowLegend = {{orientation: "h", x: 0, y: 1, yanchor: "top", font: {{size: 10}},
                         itemsizing: "constant", bgcolor: "rgba(255,255,255,0.8)"}};
    function legendFor(w) {{ return w < 900 ? narrowLegend : wideLegend; }}
    // On narrow screens the cells are named in the scene only, which keeps
    // the legend below the plot to the path symbols.
    var meshIdx = [];
    fig.data.forEach(function (t, i) {{ if (t.type === "mesh3d") {{ meshIdx.push(i); }} }});
    function visibleFor(key) {{
      return fig.data.map(function (t) {{ return t.meta === "shared" || t.meta === key; }});
    }}
    function show(key, push) {{
      if (keys.indexOf(key) < 0) {{ key = keys[0]; }}
      var ex = fig.examples[keys.indexOf(key)];
      buttons.forEach(function (b) {{ b.setAttribute("aria-pressed", b.dataset.key === key ? "true" : "false"); }});
      current.textContent = ex.summary;
      about.innerHTML = "<strong>" + ex.title + ".<\\/strong> " + ex.note;
      if (window.Plotly && el.data) {{ Plotly.restyle(el, {{visible: visibleFor(key)}}); }}
      if (push && window.history && history.replaceState) {{ history.replaceState(null, "", "#" + key); }}
    }}
    var start = (location.hash || "").replace("#", "");
    if (keys.indexOf(start) < 0) {{ start = keys[0]; }}
    buttons.forEach(function (b) {{
      b.addEventListener("click", function () {{ show(b.dataset.key, true); }});
    }});
    if (window.Plotly) {{
      var narrow = el.clientWidth < 900;
      fig.layout.legend = legendFor(el.clientWidth);
      if (narrow) {{
        var eye = fig.layout.scene.camera.eye, f = el.clientWidth < 520 ? 1.75 : 1.15;
        fig.layout.scene.camera.eye = {{x: eye.x * f, y: eye.y * f, z: eye.z * f}};
      }}
      meshIdx.forEach(function (i) {{ fig.data[i].showlegend = !narrow; }});
      var vis = visibleFor(start);
      fig.data.forEach(function (t, i) {{ t.visible = vis[i]; }});
      Plotly.newPlot(el, fig.data, fig.layout, fig.config);
      window.addEventListener("resize", function () {{
        fitPlot();
        Plotly.Plots.resize(el);
        var nowNarrow = el.clientWidth < 900;
        if (nowNarrow !== narrow) {{
          narrow = nowNarrow;
          Plotly.relayout(el, {{legend: legendFor(el.clientWidth)}});
          Plotly.restyle(el, {{showlegend: !narrow}}, meshIdx);
        }}
      }});
    }} else {{
      el.textContent = "The interactive plot needs Plotly, loaded from cdn.jsdelivr.net, which did not load.";
    }}
    show(start, false);
  }})();
</script>
</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")


# ----------------------------------------------------------------- main
def main(keys=None):
    t0 = time.perf_counter()
    ds_list = compute_all(keys)
    t_compute = time.perf_counter() - t0
    for d in ds_list:
        lc.print_scenario_summary(d)
    lims = axis_limits(ds_list)
    print(f"\naxis limits: -VTL {lims[0]}, B {lims[1]}, -VTU {lims[2]}")
    make_png(ds_list, lims)
    make_html(ds_list, lims)
    print(f"wrote {OUT_PNG}\nwrote {OUT_HTML} ({OUT_HTML.stat().st_size / 1024:.1f} KB)")
    print(f"compute {t_compute:.1f} s, total {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
