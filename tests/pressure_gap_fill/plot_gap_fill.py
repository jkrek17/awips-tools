#!/usr/bin/env python3
"""Plot a synthetic WPAC case through the gap-filled CreateXML.py.

Runs the site's CreateXML through the harness in test_createxml_gapfill.py
twice - seam-matched, and with the seam matching switched off - and draws the
isobars and Lows straight out of the XML each run wrote.  Isobars from the
GFE grid are drawn in grey, the gap's in orange, so the seam is visible.

    python3 plot_gap_fill.py [-o out.png]

Synthetic data: a 40 mb typhoon at 20N 140E, a weaker low at 24N 172W
across the dateline, and a forecaster's grid edited 3 mb above the models
with a local wave on top - so a hard cut has something to jog over.
"""
import argparse
import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_createxml_gapfill as H                            # noqa: E402
import test_pressure_gap_fill as T                            # noqa: E402


def background(lon, lat):
    """A ridge-and-trough pattern with enough gradient that isobars cross
    30N - otherwise there is no seam to see."""
    return (1004.0 + 0.6 * (lat - 17.0) +
            6.0 * np.sin(np.radians(lon * 3.0)))


def dip(lon, lat, centerLat, centerLon, depth, sigma=1.5):
    dLon = ((lon - centerLon + 180.0) % 360.0) - 180.0
    r2 = (lat - centerLat) ** 2 + (dLon * np.cos(np.radians(lat))) ** 2
    return depth * np.exp(-r2 / (2.0 * sigma ** 2))


def storms(lon, lat):
    """The models: a typhoon at 20N 140E and a low across the dateline."""
    return (background(lon, lat) - dip(lon, lat, 20.0, 140.0, 40.0) -
            dip(lon, lat, 24.0, -172.0, 18.0, 2.0))


def grid(lon, lat):
    """The forecaster's grid: 3 mb above the models, plus a local edit."""
    return storms(lon, lat) + 3.0 + 2.0 * np.sin(np.radians(lon * 9.0))


def run(seamMatched):
    # The GFE grid in 0..360, so there is no dateline jump for the fake
    # contourer to trip over - the gap follows whichever convention it gets.
    lat, lon = T.gfeGrid(120.0, 220.0)
    lon = np.where(lon < 0.0, lon + 360.0, lon)
    import PressureGapFill
    original = PressureGapFill.seamMatch
    if not seamMatched:
        PressureGapFill.seamMatch = lambda field, *a, **k: (
            np.asarray(field, dtype=float), None)
    try:
        return H.runChart(lat, lon, grid(lon, lat),
                          {"gfs0p25": H.model(storms)},
                          {"Gap models:": ["GFS"]})
    finally:
        PressureGapFill.seamMatch = original


def to360(x):
    x = np.asarray(x, dtype=float)
    return np.where(x < 0.0, x + 360.0, x)


def draw(ax, tree, title):
    for level, pts in H.layerLines(tree, "Isobars"):
        gap = (pts[:, 1] <= 30.0 + 1e-6).all()
        xs = to360(pts[:, 0])
        # Split where a line crosses the plot's own wrap, never draw across.
        breaks = np.nonzero(np.abs(np.diff(xs)) > 20.0)[0]
        for seg in np.split(np.column_stack([xs, pts[:, 1]]), breaks + 1):
            ax.plot(seg[:, 0], seg[:, 1],
                    color="#e8820c" if gap else "#8a96a3",
                    linewidth=1.3 if gap else 1.0, zorder=3 if gap else 2)
    for kind, la, lo, v in H.symbols(tree):
        if kind != "LOW":
            continue
        x = float(to360(lo))
        ax.plot(x, la, marker="o", markersize=15, markerfacecolor="white",
                markeredgecolor="#b3261e", markeredgewidth=1.6, zorder=5)
        ax.text(x, la, "L", ha="center", va="center", fontsize=9,
                fontweight="bold", color="#b3261e", zorder=6)
        ax.annotate("%d" % round(v), (x, la), textcoords="offset points",
                    xytext=(0, -17), ha="center", fontsize=7.5,
                    color="#33404f", zorder=6)
    ax.axhline(30.0, color="#33404f", linewidth=0.8, linestyle=(0, (4, 3)),
               zorder=4)
    ax.text(121.0, 30.4, "GFE grid edge, 30N", fontsize=7.5, color="#33404f")
    ax.axhspan(17.0, 30.0, color="#fdf3e6", zorder=0)
    ax.set_xlim(120, 220)
    ax.set_ylim(17, 45)
    ax.set_xticks(range(120, 221, 20))
    ax.set_xticklabels(["%dE" % x if x <= 180 else "%dW" % (360 - x)
                        for x in range(120, 221, 20)], fontsize=7.5)
    ax.set_yticks(range(20, 46, 5))
    ax.set_yticklabels(["%dN" % y for y in range(20, 46, 5)], fontsize=7.5)
    ax.tick_params(colors="#6b7684", length=3)
    ax.grid(True, color="#e3e7ec", linewidth=0.5, zorder=1)
    for spine in ax.spines.values():
        spine.set_color("#c3cad2")
    ax.set_title(title, fontsize=10, color="#1c2530", pad=7)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out",
                        default=os.path.join(HERE, "out", "gap_fill.png"))
    args = parser.parse_args()

    os.environ["TZ"] = "UTC"
    matched = run(True)
    raw = run(False)

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 9.6), dpi=140)
    draw(axes[0], matched, "Seam-matched (what CreateXML now draws)")
    draw(axes[1], raw, "Hard cut - the same models with no seam matching")
    fig.legend(handles=[
        Line2D([], [], color="#8a96a3", label="Isobars from the GFE grid"),
        Line2D([], [], color="#e8820c", linewidth=1.3,
               label="Isobars filled from the models"),
        Line2D([], [], marker="o", linestyle="none", markersize=8,
               markerfacecolor="white", markeredgecolor="#b3261e",
               label="Low")],
        loc="lower center", ncol=3, frameon=False, fontsize=8.5)
    fig.suptitle("CreateXML gap fill - 17N to the GFE grid edge",
                 fontsize=12.5, color="#111820", y=0.985)
    fig.text(0.5, 0.947, "Synthetic: a 40 mb typhoon at 20N 140E and a low "
             "across the dateline; the forecaster's grid is 3 mb above the "
             "models.  Drawn from the XML each run wrote.",
             ha="center", fontsize=8, color="#6b7684")
    fig.subplots_adjust(left=0.06, right=0.98, top=0.9, bottom=0.08,
                        hspace=0.28)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, facecolor="white")
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
