"""Hart's cyclone phase space in three dimensions, with the seven HCPSclass
cells and the synthetic 168 h life cycle of `lifecycle_comparison.py`.

Hart's phase space is three numbers per storm: B (thermal asymmetry, m),
minus V_T^L (lower thermal wind, m) and minus V_T^U (upper thermal wind,
m). The gridded product's HCPSclass (`cps_HartCPS.hart_class`) is a
partition of that space: the planes B = 10 m, -V_T^L = 0 and -V_T^U = 0 cut
it into eight boxes, and the two boxes with a cold lower and warm upper
layer (either B) are merged into class 6. This script draws those seven
cells and the life cycle's two trajectories (Hart's storm-centered method
and the gridded method, exactly the arrays behind Figure 13,
`figD_lifecycle.png`) through them.

The physics is not copied: the script imports `lifecycle_comparison` and
runs the same per-frame loop its `main()` runs (make_hours,
build_track_and_motion, build_grid, env_fields, compute_frame), because
`main()` prints and plots but does not return its arrays.

Outputs (both in this directory):

    figJ_phase_space_3d.png   static, two viewing angles (matplotlib mplot3d)
    phase_space_3d.html       interactive, self-contained Plotly page
                              (Plotly itself is loaded from the jsDelivr CDN)

Run from this directory:

    python3 phase_space_3d.py
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
from matplotlib.colors import LinearSegmentedColormap, to_hex
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d import proj3d
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

HERE = Path(__file__).resolve().parent
OUT_PNG = HERE / "figJ_phase_space_3d.png"
OUT_HTML = HERE / "phase_space_3d.html"

B_THR = float(lc.hc.B_THRESHOLD_M)  # 10 m

# Axis limits: x = -V_T^L, y = B, z = -V_T^U (all m). Widened (never
# narrowed) by diagram_style.widen_limits plus a margin if the data exceed them.
BASE_XLIM = (-320.0, 320.0)
BASE_YLIM = (-20.0, 80.0)
BASE_ZLIM = (-320.0, 320.0)

# HCPSclass colors: D2D/colormaps/Grid/CPS_HartClass.cmap, identical to
# lifecycle_comparison.CLASS_PALETTE (the Figure 13 class strips).
CLASS_PALETTE = lc.CLASS_PALETTE
CLASS_NAMES = lc.CLASS_NAMES
CLASS_HEX = {k: to_hex(v) for k, v in CLASS_PALETTE.items()}

# Trajectory colors and hour ramps exactly as lifecycle_comparison.make_figure.
HART_LINE = "#bfbfbf"
HART_RAMP = ("#c9c9c9", "#000000")
GRID_LINE = lc.RED
GRID_RAMP = ("#fbdede", lc.RED)

CELL_ALPHA = 0.12
PANEL_VIEWS = (("a", 22, -55), ("b", 22, 35))

# Screen offsets (points) of the event labels in each panel, chosen so the
# labels clear each other and the paths at these two viewing angles.
LABEL_OFFSETS = {
    "a": {"0 h": (-14, 8, "right"), "onset": (10, 9, "left"), "completion": (0, 10, "center"),
          "end": (0, -14, "center")},
    "b": {"0 h": (-6, 10, "right"), "onset": (10, 9, "left"), "completion": (0, 10, "center"),
          "end": (0, -14, "center")},
}


# ------------------------------------------------------------------ data
def compute_arrays():
    """The life cycle arrays of lifecycle_comparison.main(), computed by the
    same loop over the same functions."""
    hours = lc.make_hours()
    n = len(hours)
    lats, lons, headings, speeds = lc.build_track_and_motion(hours)
    lat_vals, lon_vals, lat2d, lon2d, dx, dy = lc.build_grid()
    psfc, coriolis = lc.env_fields(lat2d)
    keys = ("B_hart", "VTL_hart", "VTU_hart", "CLS_hart", "B_grid", "VTL_grid", "VTU_grid", "CLS_grid")
    out = {k: np.full(n, np.nan) for k in keys}
    for i, t in enumerate(hours):
        r = lc.compute_frame(t, float(lats[i]), float(lons[i]), headings[i], speeds[i], lat2d, lon2d,
                             lat_vals, lon_vals, dx, dy, psfc, coriolis)
        for k in keys:
            out[k][i] = r[k]
    out["hours"] = hours
    return out


def first_cross(hours, arr, op, thresh):
    """Index of the first frame where op(arr, thresh) holds (None if never),
    the same rule lifecycle_comparison.main() uses for onset/completion."""
    idx = np.where(op(arr, thresh))[0]
    return int(idx[0]) if idx.size else None


def class_runs(hours, cls):
    """[(start_hour, end_hour, class)] for consecutive frames sharing a class."""
    runs, start = [], 0
    for i in range(1, len(hours) + 1):
        if i == len(hours) or cls[i] != cls[start]:
            c = int(round(cls[start])) if np.isfinite(cls[start]) else None
            runs.append((float(hours[start]), float(hours[i - 1]), c))
            start = i
    return runs


def axis_limits(d):
    def widen(base, *arrs):
        lo, hi = ds.widen_limits(base, *arrs)
        pad = 0.05 * (base[1] - base[0])
        return (min(base[0], lo - pad) if lo < base[0] else base[0],
                max(base[1], hi + pad) if hi > base[1] else base[1])
    return (widen(BASE_XLIM, d["VTL_hart"], d["VTL_grid"]),
            widen(BASE_YLIM, d["B_hart"], d["B_grid"]),
            widen(BASE_ZLIM, d["VTU_hart"], d["VTU_grid"]))


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
    """Where a cell's class number goes: the cell's centroid in -V_T^L and
    -V_T^U, but pushed along B to the cell's outer B face (just inside it),
    where the life cycle (B about 0 to 40 m) never goes, so the numbers do
    not sit on the trajectories. Class 6 spans all B and keeps its centroid.
    """
    x0, x1, y0, y1, z0, z1 = box
    if c == 6:
        y = (y0 + y1) / 2
    elif y1 <= B_THR:
        y = y0 + 0.1 * (ylim[1] - ylim[0])
    else:
        y = y1 - 0.1 * (ylim[1] - ylim[0])
    return (x0 + x1) / 2, y, (z0 + z1) / 2


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
    lines = [
        [(0, ya, za), (0, yb, za), (0, yb, zb), (0, ya, zb), (0, ya, za)],   # -VTL = 0
        [(xa, ya, 0), (xb, ya, 0), (xb, yb, 0), (xa, yb, 0), (xa, ya, 0)],   # -VTU = 0
        # B = 10: L-shaped (the x < 0, z > 0 quadrant belongs to class 6)
        [(0, B_THR, zb), (xb, B_THR, zb), (xb, B_THR, za), (xa, B_THR, za), (xa, B_THR, 0), (0, B_THR, 0),
         (0, B_THR, zb)],
    ]
    return lines


# --------------------------------------------------------------- figure
def make_png(d, events):
    hours = d["hours"]
    xlim, ylim, zlim = axis_limits(d)
    cells = class_cells(xlim, ylim, zlim)
    cmap_hart = LinearSegmentedColormap.from_list("hart_gray", list(HART_RAMP))
    cmap_grid = LinearSegmentedColormap.from_list("grid_red", list(GRID_RAMP))

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9, "text.color": ds.TEXT_DARK,
        "axes.labelcolor": ds.TEXT_DARK, "xtick.color": ds.TEXT_SECONDARY, "ytick.color": ds.TEXT_SECONDARY,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.linewidth": 0.6, "legend.fontsize": 8,
    })
    fig = plt.figure(figsize=(12.0, 6.2))
    axes = [fig.add_axes([-0.02, 0.15, 0.52, 0.82], projection="3d", computed_zorder=False),
            fig.add_axes([0.49, 0.15, 0.52, 0.82], projection="3d", computed_zorder=False)]

    i_on, i_comp = events["onset_grid"], events["completion_grid"]
    for ax, (letter, elev, azim) in zip(axes, PANEL_VIEWS):
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_zlim(*zlim)
        ax.set_box_aspect((1.0, 1.0, 0.9), zoom=1.0)
        ax.view_init(elev=elev, azim=azim)
        for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
            pane.set_facecolor((1, 1, 1, 0))
            pane.set_edgecolor(ds.GRID_COLOR)
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis._axinfo["grid"].update(color=ds.GRID_COLOR, linewidth=0.4)

        # -- the seven cells, translucent, edges light
        for c, (x0, x1, y0, y1, z0, z1) in cells.items():
            poly = Poly3DCollection(box_faces(x0, x1, y0, y1, z0, z1), facecolor=CLASS_PALETTE[c],
                                    alpha=CELL_ALPHA, edgecolor=(0.3, 0.3, 0.3, 0.18), linewidth=0.3)
            poly.set_zorder(1)
            ax.add_collection3d(poly)
        # -- dividing planes' outlines
        for line in dividing_plane_outlines(xlim, ylim, zlim):
            p = np.array(line, dtype=float)
            ax.plot(p[:, 0], p[:, 1], p[:, 2], color=ds.TEXT_SECONDARY, lw=0.6, alpha=0.7, zorder=2)
        # -- class numbers, one per cell, placed clear of the paths in this view
        traj = np.concatenate([np.column_stack([d[f"VTL_{m}"], d[f"B_{m}"], d[f"VTU_{m}"]])
                               for m in ("hart", "grid")])
        for c, pos in place_cell_labels(ax, cells, traj, (xlim, ylim, zlim)).items():
            ax.text(*pos, str(c), color=CLASS_PALETTE[c],
                    fontsize=11, fontweight="bold", ha="center", va="center", zorder=3,
                    path_effects=[_halo()])

        # -- trajectories (on top of the cells: computed_zorder=False)
        ax.plot(d["VTL_hart"], d["B_hart"], d["VTU_hart"], "-", color=HART_LINE, lw=1.1, zorder=5)
        ax.plot(d["VTL_grid"], d["B_grid"], d["VTU_grid"], "-", color=GRID_LINE, alpha=0.5, lw=1.1, zorder=6)
        ax.scatter(d["VTL_hart"], d["B_hart"], d["VTU_hart"], c=hours, cmap=cmap_hart, s=22, marker="o",
                   edgecolor="white", linewidth=0.4, depthshade=False, zorder=7)
        ax.scatter(d["VTL_grid"], d["B_grid"], d["VTU_grid"], c=hours, cmap=cmap_grid, s=22, marker="s",
                   edgecolor="white", linewidth=0.4, depthshade=False, zorder=8)
        for i, lab in ((i_on, "onset"), (i_comp, "completion")):
            if i is None:
                continue
            ax.scatter([d["VTL_grid"][i]], [d["B_grid"][i]], [d["VTU_grid"][i]], marker="x", s=70,
                       color=ds.TEXT_DARK, linewidth=1.5, depthshade=False, zorder=9)
            _annotate3d(ax, (d["VTL_grid"][i], d["B_grid"][i], d["VTU_grid"][i]), f"{lab} {hours[i]:.0f} h",
                        LABEL_OFFSETS[letter][lab], fontsize=7.5)
        # 0 h and 168 h: the two methods start and end close together, so one label each
        for i, lab, key in ((0, "0 h", "0 h"), (-1, f"{hours[-1]:.0f} h", "end")):
            xs = (d["VTL_hart"][i] + d["VTL_grid"][i]) / 2
            ys = (d["B_hart"][i] + d["B_grid"][i]) / 2
            zs = (d["VTU_hart"][i] + d["VTU_grid"][i]) / 2
            _annotate3d(ax, (xs, ys, zs), lab, LABEL_OFFSETS[letter][key], fontsize=8, fontweight="bold")

        ax.set_xlabel(ds.AXIS_LABEL_VTL, labelpad=2)
        ax.set_ylabel(ds.AXIS_LABEL_B, labelpad=2)
        ax.zaxis.set_rotate_label(False)
        ax.set_zlabel(ds.AXIS_LABEL_VTU, labelpad=4, rotation=90)
        ax.set_yticks([-20, 0, 20, 40, 60, 80])
        pos = ax.get_position()
        fig.text(pos.x0 + 0.04, 0.975, f"({letter}) elevation {elev}\u00b0, azimuth {azim}\u00b0", fontsize=10,
                 ha="left", va="top")

    class_handles = [Patch(facecolor=CLASS_PALETTE[c], alpha=0.55, edgecolor="none", label=f"{c}  {CLASS_NAMES[c]}")
                     for c in range(7)]
    fig.legend(handles=class_handles, loc="lower left", bbox_to_anchor=(0.03, 0.005), ncol=4, fontsize=7.5,
               frameon=False, title="HCPSclass cells (B = 10 m, $-V_T^L$ = 0, $-V_T^U$ = 0)", title_fontsize=8,
               handlelength=1.4, columnspacing=1.2)
    traj_handles = [
        Line2D([0], [0], marker="o", color="0.4", lw=1.0, markersize=5, label="Hart, circular window"),
        Line2D([0], [0], marker="s", color=GRID_LINE, lw=1.0, markersize=5, label="gridded, square window"),
        Line2D([0], [0], marker="x", color=ds.TEXT_DARK, lw=0, markersize=6, markeredgewidth=1.4,
               label="gridded onset (B > 10 m), completion ($-V_T^L$ < 0)"),
    ]
    fig.legend(handles=traj_handles, loc="lower right", bbox_to_anchor=(0.99, 0.005), ncol=1, fontsize=7.5,
               frameon=False, title="Life cycle, 0 to 168 h (markers light to dark by hour)", title_fontsize=8)
    fig.savefig(OUT_PNG, dpi=200, facecolor="white")
    plt.close(fig)
    return xlim, ylim, zlim


def _annotate3d(ax, xyz, text, offset, **kw):
    """Label a 3-D point at a fixed screen offset (points): the point is
    projected with this view's own projection matrix and annotated in the
    axes' 2-D projected coordinates (the view is fixed before this call)."""
    x2, y2, _ = proj3d.proj_transform(*xyz, ax.get_proj())
    dx, dy, ha = offset
    ax.annotate(text, xy=(x2, y2), xycoords="data", xytext=(dx, dy), textcoords="offset points",
                ha=ha, va="bottom" if dy > 0 else "top", color=ds.TEXT_DARK, zorder=10,
                path_effects=[_halo()], **kw)


def place_cell_labels(ax, cells, traj, lims):
    """{class: (x, y, z)} for the class numbers in this panel's view: of a
    5 x 5 x 5 lattice of candidate points inside each cell, the one nearest
    the cell's centroid whose screen projection keeps a set clearance from
    both trajectories (densified along their segments) and from the labels
    already placed; failing that, the candidate with the most clearance."""
    M = ax.get_proj()

    def proj(p):
        x2, y2, _ = proj3d.proj_transform(p[:, 0], p[:, 1], p[:, 2], M)
        return np.column_stack([x2, y2])

    dense = np.concatenate([np.linspace(a, b, 8, endpoint=False) for a, b in zip(traj[:-1], traj[1:])]
                           + [traj[-1:]])
    avoid = proj(dense[np.all(np.isfinite(dense), axis=1)])
    corners = np.array([[x, y, z] for x in lims[0] for y in lims[1] for z in lims[2]])
    span = np.ptp(proj(corners), axis=0).max()
    clearance = 0.045 * span
    fr = np.linspace(0.15, 0.85, 5)
    placed = {}
    for c, (x0, x1, y0, y1, z0, z1) in cells.items():
        g = np.array([[x0 + a * (x1 - x0), y0 + b * (y1 - y0), z0 + e * (z1 - z0)]
                      for a in fr for b in fr for e in fr])
        rel = np.array([[a - 0.5, b - 0.5, e - 0.5] for a in fr for b in fr for e in fr])
        g2 = proj(g)
        pts = avoid if not placed else np.vstack([avoid, proj(np.array(list(placed.values())))])
        dist = np.min(np.linalg.norm(g2[:, None, :] - pts[None, :, :], axis=2), axis=1)
        ok = dist >= clearance
        best = np.argmin(np.where(ok, np.linalg.norm(rel, axis=1), np.inf)) if ok.any() else np.argmax(dist)
        placed[c] = tuple(g[best])
    return placed


def _halo():
    from matplotlib import patheffects
    return patheffects.withStroke(linewidth=2.2, foreground="white")


# ----------------------------------------------------------------- html
def _r(a):
    return [None if not np.isfinite(v) else round(float(v), 1) for v in np.asarray(a, dtype=float)]


def _cls_label(c):
    if not np.isfinite(c):
        return "none"
    c = int(round(c))
    return f"{c} ({CLASS_NAMES[c]})"


def make_html(d, events, lims):
    xlim, ylim, zlim = lims
    hours = d["hours"]
    cells = class_cells(xlim, ylim, zlim)
    traces = []

    # cells: mesh3d boxes, 8 vertices, 12 triangles
    tri_i = [0, 0, 4, 4, 0, 0, 3, 3, 1, 1, 0, 0]
    tri_j = [1, 2, 5, 6, 1, 5, 2, 6, 2, 6, 3, 7]
    tri_k = [2, 3, 6, 7, 5, 4, 6, 7, 6, 5, 7, 4]
    for c, (x0, x1, y0, y1, z0, z1) in cells.items():
        traces.append(dict(
            type="mesh3d", name=f"class {c}: {CLASS_NAMES[c]}", legendgroup=f"c{c}", showlegend=True,
            x=[x0, x1, x1, x0, x0, x1, x1, x0], y=[y0, y0, y1, y1, y0, y0, y1, y1],
            z=[z0, z0, z0, z0, z1, z1, z1, z1], i=tri_i, j=tri_j, k=tri_k,
            color=CLASS_HEX[c], opacity=0.15, flatshading=True,
            lighting=dict(ambient=1.0, diffuse=0.0, specular=0.0, fresnel=0.0),
            hovertemplate=f"class {c}<br>{CLASS_NAMES[c]}<extra></extra>",
        ))
        traces.append(dict(
            type="scatter3d", mode="text", legendgroup=f"c{c}", showlegend=False, hoverinfo="skip",
            **dict(zip("xyz", ([v] for v in label_position(c, (x0, x1, y0, y1, z0, z1), ylim)))), text=[str(c)],
            textfont=dict(color=CLASS_HEX[c], size=16, family="Arial Black, Arial, sans-serif"),
        ))

    # dividing planes: thin lines on the axis-box faces
    xs, ys, zs = [], [], []
    for line in dividing_plane_outlines(xlim, ylim, zlim):
        for p in line:
            xs.append(p[0]); ys.append(p[1]); zs.append(p[2])
        xs.append(None); ys.append(None); zs.append(None)
    traces.append(dict(type="scatter3d", mode="lines", name="dividing planes (B = 10 m, -VTL = 0, -VTU = 0)",
                       x=xs, y=ys, z=zs, hoverinfo="skip", line=dict(color="#52514e", width=2)))

    def hover(i):
        return (f"hour {hours[i]:.0f}<br>B {d_r('B', i)} m<br>-V<sub>T</sub><sup>L</sup> {d_r('VTL', i)} m"
                f"<br>-V<sub>T</sub><sup>U</sup> {d_r('VTU', i)} m"
                f"<br>gridded class {_cls_label(d['CLS_grid'][i])}<br>Hart class {_cls_label(d['CLS_hart'][i])}")

    for method, label, line_color, ramp, symbol in (
            ("hart", "Hart, circular window", HART_LINE, HART_RAMP, "circle"),
            ("grid", "gridded, square window", GRID_LINE, GRID_RAMP, "square")):
        def d_r(k, i, m=method):
            return f"{d[f'{k}_{m}'][i]:.1f}"
        traces.append(dict(
            type="scatter3d", mode="lines+markers", name=label,
            x=_r(d[f"VTL_{method}"]), y=_r(d[f"B_{method}"]), z=_r(d[f"VTU_{method}"]),
            line=dict(color=line_color, width=4),
            marker=dict(size=4, symbol=symbol, color=[float(h) for h in hours],
                        colorscale=[[0, ramp[0]], [1, ramp[1]]], cmin=0, cmax=float(hours[-1]),
                        line=dict(color="#ffffff", width=0.5)),
            text=[f"{label}<br>" + hover(i) for i in range(len(hours))],
            hovertemplate="%{text}<extra></extra>",
        ))

    ev_x, ev_y, ev_z, ev_t = [], [], [], []
    for key, lab in (("onset_grid", "gridded onset (B first > 10 m)"),
                     ("completion_grid", "gridded completion (-VTL first < 0)")):
        i = events[key]
        if i is None:
            continue
        ev_x.append(round(float(d["VTL_grid"][i]), 1)); ev_y.append(round(float(d["B_grid"][i]), 1))
        ev_z.append(round(float(d["VTU_grid"][i]), 1)); ev_t.append(f"{lab}, {hours[i]:.0f} h")
    traces.append(dict(type="scatter3d", mode="markers+text", name="gridded onset and completion",
                       x=ev_x, y=ev_y, z=ev_z, hovertext=ev_t, hovertemplate="%{hovertext}<extra></extra>",
                       text=[t.split(" (")[0].replace("gridded ", "") + t.split(",")[-1] for t in ev_t],
                       textposition=["middle right", "top center"][:len(ev_t)],
                       textfont=dict(color="#0b0b0b", size=12),
                       marker=dict(symbol="x", size=4, color="#0b0b0b")))
    end_x = [round(float((d["VTL_hart"][i] + d["VTL_grid"][i]) / 2), 1) for i in (0, -1)]
    end_y = [round(float((d["B_hart"][i] + d["B_grid"][i]) / 2), 1) for i in (0, -1)]
    end_z = [round(float((d["VTU_hart"][i] + d["VTU_grid"][i]) / 2) + s, 1) for i, s in ((0, 30), (-1, -30))]
    traces.append(dict(type="scatter3d", mode="text", showlegend=False, x=end_x, y=end_y, z=end_z,
                       text=["0 h", f"{hours[-1]:.0f} h"], hoverinfo="skip",
                       textfont=dict(color="#0b0b0b", size=13)))

    def axis(title, rng, dtick):
        return dict(title=dict(text=title), range=list(rng), dtick=dtick, backgroundcolor="#ffffff",
                    gridcolor="#dedcd5", zerolinecolor="#dedcd5", showbackground=False)

    layout = dict(
        paper_bgcolor="#ffffff", margin=dict(l=0, r=0, t=10, b=0),
        font=dict(family='-apple-system, "Segoe UI", Helvetica, Arial, sans-serif', size=12, color="#1a1a1a"),
        legend=dict(x=0.0, y=1.0, bgcolor="rgba(255,255,255,0.8)", font=dict(size=11), itemsizing="constant"),
        scene=dict(
            xaxis=axis("-V<sub>T</sub><sup>L</sup> (m)", xlim, 100),
            yaxis=axis("B (m)", ylim, 20),
            zaxis=axis("-V<sub>T</sub><sup>U</sup> (m)", zlim, 100),
            aspectmode="manual", aspectratio=dict(x=1, y=1, z=0.9),
            camera=dict(eye=dict(x=1.35, y=-1.65, z=0.8)),
        ),
    )
    config = dict(responsive=True, displaylogo=False)
    fig_json = json.dumps(dict(data=traces, layout=layout, config=config), separators=(",", ":"))
    fig_json = fig_json.replace("</", "<\\/")

    title = "Cyclone phase space: the seven HCPSclass cells and the synthetic life cycle"
    on, comp = events["onset_grid"], events["completion_grid"]
    note = (
        "Each axis is one of Hart's three phase-space parameters: the lower thermal wind "
        "-V<sub>T</sub><sup>L</sup>, the thermal asymmetry B and the upper thermal wind "
        "-V<sub>T</sub><sup>U</sup>, all in meters. The planes B = 10 m, -V<sub>T</sub><sup>L</sup> = 0 and "
        "-V<sub>T</sub><sup>U</sup> = 0 divide the space into the seven colored HCPSclass cells; class 6 "
        "(cold below, warm above) spans both sides of B = 10 m. The two paths are the synthetic 168 h "
        "life cycle of Figure 13 evaluated by Hart's storm-centered method (gray circles) and by the "
        "gridded method (red squares), each shaded light to dark from 0 h to 168 h; the x marks the "
        f"gridded onset ({hours[on]:.0f} h) and completion ({hours[comp]:.0f} h). Hover over a point for "
        "its hour, its three values and the class each method assigns. Drag to rotate, scroll to zoom, "
        "and click a legend entry to hide or show that series."
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
  h1 {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 1.15em;
        line-height: 1.3; margin: 0.8em 0 0.4em; }}
  #plot {{ width: 100%; height: 70vh; min-height: 360px; }}
  @media (max-width: 899px) {{ #plot {{ height: 92vh; min-height: 560px; }} }}
  p.note {{ max-width: 46em; margin: 0.6em 0 1.2em; font-size: 0.9em; color: #3a3a37; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<div id="plot"></div>
<p class="note">{note}</p>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.3/plotly.min.js"></script>
<script>
  (function () {{
    var fig = {fig_json};
    var el = document.getElementById("plot");
    // Legend beside the scene on wide screens, below it on narrow ones
    // (phones, or the page inside a narrow iframe).
    var wideLegend = fig.layout.legend;
    var narrowLegend = {{orientation: "h", x: 0, y: 0, yanchor: "top", font: {{size: 10}},
                         itemsizing: "constant", bgcolor: "rgba(255,255,255,0)"}};
    function legendFor(w) {{ return w < 900 ? narrowLegend : wideLegend; }}
    if (window.Plotly) {{
      var narrow = el.clientWidth < 900;
      fig.layout.legend = legendFor(el.clientWidth);
      if (narrow) {{
        var eye = fig.layout.scene.camera.eye;
        fig.layout.scene.camera.eye = {{x: eye.x * 1.3, y: eye.y * 1.3, z: eye.z * 1.3}};
      }}
      Plotly.newPlot(el, fig.data, fig.layout, fig.config);
      window.addEventListener("resize", function () {{
        var nowNarrow = el.clientWidth < 900;
        if (nowNarrow !== narrow) {{
          narrow = nowNarrow;
          Plotly.relayout(el, {{legend: legendFor(el.clientWidth)}});
        }}
      }});
    }} else {{
      el.textContent = "The interactive plot needs Plotly, loaded from cdn.jsdelivr.net, which did not load.";
    }}
  }})();
</script>
</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")


# ----------------------------------------------------------------- main
def main(arrays=None):
    t0 = time.perf_counter()
    d = compute_arrays() if arrays is None else arrays
    t_compute = time.perf_counter() - t0
    hours = d["hours"]
    events = dict(
        onset_grid=first_cross(hours, d["B_grid"], np.greater, B_THR),
        completion_grid=first_cross(hours, d["VTL_grid"], np.less, 0.0),
        onset_hart=first_cross(hours, d["B_hart"], np.greater, B_THR),
        completion_hart=first_cross(hours, d["VTL_hart"], np.less, 0.0),
    )
    for k, i in events.items():
        print(f"{k}: {hours[i]:.0f} h" if i is not None else f"{k}: never")
    for label, key in (("Gridded", "CLS_grid"), ("Hart", "CLS_hart")):
        print(f"{label} class sequence:")
        for h0, h1, c in class_runs(hours, d[key]):
            print(f"  {h0:.0f} to {h1:.0f} h: class {c} ({CLASS_NAMES.get(c, 'nan')})")
    for k in ("B", "VTL", "VTU"):
        both = np.concatenate([d[f"{k}_hart"], d[f"{k}_grid"]])
        print(f"{k} range over both methods: {np.nanmin(both):.1f} to {np.nanmax(both):.1f} m")
    lims = make_png(d, events)
    print(f"axis limits: -VTL {lims[0]}, B {lims[1]}, -VTU {lims[2]}")
    make_html(d, events, lims)
    print(f"wrote {OUT_PNG}\nwrote {OUT_HTML} ({OUT_HTML.stat().st_size / 1024:.1f} KB)")
    print(f"compute {t_compute:.1f} s, total {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
