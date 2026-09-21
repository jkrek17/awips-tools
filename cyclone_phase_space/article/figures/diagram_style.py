"""Shared style for Hart's two cyclone-phase-space diagrams (the article's
Figure 1, `make_fig10` in `make_figures.py`) -- the quadrant colors and
corner labels, the onset/completion reference lines, the grid, the axis
labels, and the axis limits -- so `make_figures.py`, `lifecycle_comparison.py`
and `lifecycle_storyboard.py` share one definition of each instead of three
copies that can drift apart.

Importing this module does no work beyond defining constants and functions:
no sys.path insertion, no other module's import side effects, and no
matplotlib rcParams changes. `make_figures.py` sets `plt.rcParams` globally
at its own import time (its own font, colors, dpi, savefig settings for the
article's other figures) -- importing `make_figures.py` itself from the
lifecycle scripts would silently apply that same global styling to their own
figures too, which is why this module exists as the seam between them
instead.
"""
from __future__ import annotations

import numpy as np
from matplotlib.patches import Rectangle

TEXT_DARK = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID_COLOR = "#dedcd5"

CATEGORY_COLORS = ["#4a3aa7", "#2a78d6", "#c3c2b7", "#eb6834", "#e34948"]

# Panel (a)/(d): B versus -V_T^L. Colors and corner positions exactly as
# make_figures.make_fig10's own quadrants_a/label_pos_a.
B_VTL_QUADRANT_COLORS = {
    "symmetric warm core": CATEGORY_COLORS[2],
    "asymmetric warm core": CATEGORY_COLORS[3],
    "asymmetric cold core": CATEGORY_COLORS[1],
    "symmetric cold core": CATEGORY_COLORS[0],
}
B_VTL_LABEL_POS = {
    "asymmetric cold core": (0.04, 0.83, "left", "top"),
    "asymmetric warm core": (0.97, 0.96, "right", "top"),
    "symmetric cold core": (0.04, 0.04, "left", "bottom"),
    "symmetric warm core": (0.97, 0.04, "right", "bottom"),
}
B_VTL_QUADRANT_ALPHA = 0.30
B_VTL_LABEL_FONTSIZE = 7.2

# Panel (b)/(e): -V_T^U versus -V_T^L. Colors exactly as quadrants_b;
# label positions generalize label_pos_b's "lim * fraction" formula to
# separate x/y limits (reduces to the original when xlim == ylim == (-lim,
# lim), which is what make_fig10 itself passes).
VTU_VTL_QUADRANT_COLORS = {
    "deep warm core": "#e34948",
    "shallow warm core": "#eb6834",
    "deep cold core": "#2a78d6",
    "shallow cold core": "#4a3aa7",
}
VTU_VTL_QUADRANT_ALPHA = 0.11
VTU_VTL_LABEL_FONTSIZE = 7.3

# make_fig10's own axis limits, for lining up with it exactly. Panel (a)/(d):
# B (m) vertical, -V_T^L (m) horizontal. Panel (b)/(e): -V_T^U versus
# -V_T^L (m), both +/-300.
FIG10_B_LIM = (-20.0, 80.0)
FIG10_VTL_LIM = (-300.0, 300.0)
FIG10_VTU_LIM = (-300.0, 300.0)

AXIS_LABEL_VTL = r"$-V_T^L$  (m)"
AXIS_LABEL_B = "B (m)"
AXIS_LABEL_VTU = r"$-V_T^U$  (m)"


def widen_limits(lim, *value_arrays):
    """`lim`, widened (never narrowed) just enough to contain every finite
    value in `value_arrays` -- so a shared article limit is used as-is
    unless a particular dataset actually exceeds it, and then only by the
    amount needed.
    """
    lo, hi = lim
    vals = np.concatenate([np.asarray(v, dtype=float).ravel() for v in value_arrays])
    vals = vals[np.isfinite(vals)]
    if vals.size:
        lo = min(lo, float(vals.min()))
        hi = max(hi, float(vals.max()))
    return (lo, hi)


def draw_b_vtl_quadrants(ax, xlim, ylim, b_thr, label_overrides=None, fontsize=None):
    """The four B-vs-$-V_T^L$ quadrant rectangles (alpha 0.30, zorder 0)
    and their italic corner labels, exactly as make_fig10 panel (a):
    symmetric/asymmetric split by `b_thr` (B's own onset threshold),
    warm/cold split at $-V_T^L$ = 0.

    `label_overrides` (default None, i.e. make_fig10's own positions
    exactly): an optional {label: (x, y)} of axes-fraction positions to use
    in place of B_VTL_LABEL_POS's default for just those labels -- for a
    caller whose own trajectory (unlike make_fig10's schematic one) happens
    to pass through a default corner position. `fontsize` (default None,
    i.e. B_VTL_LABEL_FONTSIZE exactly): override for a panel small enough
    (e.g. one column of a multi-panel grid) that the article's own corner
    label size would run opposite corners' labels into each other.
    """
    quadrants = [
        (0.0, 1e4, -1e4, b_thr, B_VTL_QUADRANT_COLORS["symmetric warm core"], "symmetric warm core"),
        (0.0, 1e4, b_thr, 1e4, B_VTL_QUADRANT_COLORS["asymmetric warm core"], "asymmetric warm core"),
        (-1e4, 0.0, b_thr, 1e4, B_VTL_QUADRANT_COLORS["asymmetric cold core"], "asymmetric cold core"),
        (-1e4, 0.0, -1e4, b_thr, B_VTL_QUADRANT_COLORS["symmetric cold core"], "symmetric cold core"),
    ]
    overrides = label_overrides or {}
    fs = B_VTL_LABEL_FONTSIZE if fontsize is None else fontsize
    for x0, x1, y0, y1, color, _ in quadrants:
        x0c, x1c = max(x0, xlim[0]), min(x1, xlim[1])
        y0c, y1c = max(y0, ylim[0]), min(y1, ylim[1])
        ax.add_patch(Rectangle((x0c, y0c), x1c - x0c, y1c - y0c, facecolor=color,
                                alpha=B_VTL_QUADRANT_ALPHA, edgecolor="none", zorder=0))
    for _, _, _, _, _, label in quadrants:
        default_x, default_y, ha, va = B_VTL_LABEL_POS[label]
        x, y = overrides.get(label, (default_x, default_y))
        ax.text(x, y, label, transform=ax.transAxes, color=TEXT_SECONDARY, fontsize=fs,
                 ha=ha, va=va, style="italic", zorder=1)


def draw_vtu_vtl_quadrants(ax, xlim, ylim, label_overrides=None, fontsize=None):
    """The four $-V_T^U$-vs-$-V_T^L$ quadrant rectangles (alpha 0.11,
    zorder 0) and their italic corner labels, exactly as make_fig10 panel
    (b): deep/shallow split by $-V_T^U$ = 0, warm/cold split by
    $-V_T^L$ = 0.

    `label_overrides` (default None, i.e. make_fig10's own positions
    exactly): an optional {label: (x, y)} of data-coordinate positions to
    use in place of the default `label_pos` for just those labels -- for a
    caller whose own trajectory (unlike make_fig10's schematic one) happens
    to pass through a default corner position. `fontsize` (default None,
    i.e. VTU_VTL_LABEL_FONTSIZE exactly): override for a panel small enough
    (e.g. one column of a multi-panel grid) that the article's own corner
    label size would run opposite corners' labels into each other.
    """
    x0lim, x1lim = xlim
    y0lim, y1lim = ylim
    quadrants = [
        (0.0, x1lim, 0.0, y1lim, VTU_VTL_QUADRANT_COLORS["deep warm core"], "deep warm core"),
        (0.0, x1lim, y0lim, 0.0, VTU_VTL_QUADRANT_COLORS["shallow warm core"], "shallow warm core"),
        (x0lim, 0.0, y0lim, 0.0, VTU_VTL_QUADRANT_COLORS["deep cold core"], "deep cold core"),
        (x0lim, 0.0, 0.0, y1lim, VTU_VTL_QUADRANT_COLORS["shallow cold core"], "shallow cold core"),
    ]
    overrides = label_overrides or {}
    fs = VTU_VTL_LABEL_FONTSIZE if fontsize is None else fontsize
    for x0, x1, y0, y1, color, _ in quadrants:
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=color,
                                alpha=VTU_VTL_QUADRANT_ALPHA, edgecolor="none", zorder=0))
    label_pos = {
        "deep warm core": (x1lim * 0.55, y1lim * 0.90),
        "shallow warm core": (x1lim * 0.55, y0lim * 0.90),
        "deep cold core": (x0lim * 0.95, y0lim * 0.90),
        "shallow cold core": (x0lim * 0.95, y1lim * 0.68),
    }
    for _, _, _, _, _, label in quadrants:
        x, y = overrides.get(label, label_pos[label])
        ax.text(x, y, label, color=TEXT_SECONDARY, fontsize=fs, ha="left", va="center",
                 style="italic", zorder=1)
