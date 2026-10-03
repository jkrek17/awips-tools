#!/usr/bin/env python3
"""Plot a typhoon in the gap with and without matching the warning.

Runs the site's CreateXML through the harness in test_createxml_gapfill.py
twice - "Match TC warnings:" Off, then On - with the models' typhoon 200 nm
from where a JTWC warning has it, and draws the isobars and Lows straight
out of the XML each run wrote.  The warning's track is drawn on both.

    python3 plot_tc_match.py [-o out.png]
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
sys.path.insert(0, os.path.join(HERE, "..", "tc_pressure"))
import test_createxml_gapfill as H                            # noqa: E402
import plot_gap_fill as PG                                    # noqa: E402
from synth_warning import jtwcWarning                         # noqa: E402

TAU0 = H.VALID - 6 * 3600
TRACK = [(0, 19.0, 138.0, 100, 150), (12, 20.0, 137.0, 100, 150),
         (24, 21.0, 136.0, 95, 160), (36, 22.5, 135.2, 90, 170)]


def models(lon, lat):
    """The models: a 40 mb typhoon at 21.5N 140.5E, a weaker low east."""
    return (PG.background(lon, lat) -
            PG.dip(lon, lat, 21.5, 140.5, 40.0) -
            PG.dip(lon, lat, 24.0, -172.0, 18.0, 2.0))


def run(match):
    import TCPressure
    H.TEXT.clear()
    H.TEXT["NFDTCPWP1"] = jtwcWarning(TAU0, TRACK, 950, "TESTER")
    TCPressure.now = lambda: TAU0 + 3 * 3600
    lat, lon = PG.T.gfeGrid(120.0, 220.0)
    lon = np.where(lon < 0.0, lon + 360.0, lon)
    del H.STATUS[:]
    tree = H.runChart(lat, lon, models(lon, lat) + 2.0,
                      {"gfs0p25": H.model(models)},
                      {"Gap models:": ["GFS"],
                       "Match TC warnings:": "On" if match else "Off"})
    return tree, [m for _, m in H.STATUS if "TC " in m]


def drawTrack(ax):
    xs = [t[2] for t in TRACK]
    ys = [t[1] for t in TRACK]
    ax.plot(xs, ys, color="#1f5fbf", linewidth=1.2, linestyle=(0, (3, 2)),
            zorder=4)
    ax.plot(xs, ys, "o", color="#1f5fbf", markersize=3.5, zorder=4)
    ax.plot(137.5, 19.5, marker="x", color="#1f5fbf", markersize=9,
            markeredgewidth=2.0, zorder=7)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out",
                        default=os.path.join(HERE, "out", "tc_match.png"))
    args = parser.parse_args()
    os.environ["TZ"] = "UTC"

    off, _ = run(False)
    on, said = run(True)

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 6.2), dpi=140)
    for ax, tree, title in ((axes[0], off, "Match TC warnings: Off"),
                            (axes[1], on, "Match TC warnings: On")):
        PG.draw(ax, tree, title)
        drawTrack(ax)
        ax.set_xlim(122, 158)
        ax.set_ylim(12, 36)
        ax.set_xticks(range(125, 158, 5))
        ax.set_xticklabels(["%dE" % x for x in range(125, 158, 5)],
                           fontsize=7.5)
        ax.set_yticks(range(15, 36, 5))
        ax.set_yticklabels(["%dN" % y for y in range(15, 36, 5)],
                           fontsize=7.5)
    fig.legend(handles=[
        Line2D([], [], color="#8a96a3", label="Isobars from the GFE grid"),
        Line2D([], [], color="#e8820c", linewidth=1.3,
               label="Isobars filled from the models"),
        Line2D([], [], color="#1f5fbf", linestyle=(0, (3, 2)), marker="o",
               markersize=3.5, label="JTWC warning track"),
        Line2D([], [], color="#1f5fbf", marker="x", linestyle="none",
               markersize=8, markeredgewidth=2,
               label="Warning position at chart time")],
        loc="lower center", ncol=4, frameon=False, fontsize=8.5)
    fig.suptitle("Typhoon in the gap: the models' position vs the warning's",
                 fontsize=12.5, color="#111820", y=0.985)
    fig.text(0.5, 0.925, "Synthetic: the models put a 40 mb typhoon 200 nm "
             "northeast of the warning position; the warning says 950 mb.  "
             "F024 chart, drawn from the XML each run wrote.",
             ha="center", fontsize=8, color="#6b7684")
    if said:
        fig.text(0.5, 0.895, "Status bar: " + said[0], ha="center",
                 fontsize=7.5, color="#33404f", family="monospace")
    fig.subplots_adjust(left=0.05, right=0.98, top=0.85, bottom=0.12,
                        wspace=0.12)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, facecolor="white")
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
