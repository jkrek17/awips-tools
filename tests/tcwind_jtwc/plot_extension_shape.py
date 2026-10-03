#!/usr/bin/env python3
"""Plot a lopsided forecaster point: 50 kt, 34 kt radii 300/250/60/40 nm.

Runs Procedure.execute() through test_procedure_harness.py on the real
KROVANH warning (ends at 120 h) with a forecaster point at 144 h, and draws
the WindJTWC grid it writes there - once with the 34 kt line made to follow
the entered radii, once without (the wind model's own circle-plus-shift) -
and at 132 h, half way through the fade-in.

    python3 plot_extension_shape.py [-o out.png]
"""
import argparse
import os
import sys
import time

import numpy as np

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_procedure_harness as H                            # noqa: E402

tc = H.tc
INK2 = "#52514e"
BLUE = "#2a78d6"
GALE = "#eda100"
STORM = "#eb6834"

LAT, LON = 27.0, 130.0
RADII = {"NE": 300.0, "SE": 250.0, "SW": 60.0, "NW": 40.0}


def run(shaped):
    taus = H._krovanhTaus()
    t0 = taus[0].epoch
    pts = [{"epoch": t0 + 144 * 3600, "lat": LAT, "lon": LON, "vmax": 50.0,
            "pressureMb": None, "extratropical": False, "r34": dict(RADII)},
           {"epoch": t0 + 168 * 3600, "lat": LAT + 3.0, "lon": LON + 4.0,
            "vmax": 50.0, "pressureMb": None, "extratropical": False,
            "r34": dict(RADII)}]
    path = H._withStore(pts)
    saved = tc.shapeWeightAt
    if not shaped:
        tc.shapeWeightAt = lambda taus, epoch: 0.0
    try:
        proc, _, _, lat, lon = H._run_pmsl(
            H._modelPmsl(taus), label="No",
            extra={tc.EXTENSION_LABEL: "Use saved"})
    finally:
        tc.shapeWeightAt = saved
        os.remove(path)
    winds = dict((a[4].startTime().unixTime(), np.asarray(a[3][0]))
                 for a, _ in proc.created if a[2] == "VECTOR")
    ext, _, _ = tc.extendTrack(taus, pts)
    return winds, lat, lon, ext, t0


def outline(clat, clon, quad):
    az = np.arange(0.0, 360.1, 2.0)
    r = tc._quadrantTable(quad, az) / 60.0
    return (clon + r * np.sin(np.radians(az)) / np.cos(np.radians(clat)),
            clat + r * np.cos(np.radians(az)))


def extents(field, lat, lon, clat, clon):
    dist = np.vectorize(tc._gcDistanceNm)(lat, lon, clat, clon)
    b = np.degrees(np.arctan2((lon - clon) * np.cos(np.radians(clat)),
                              lat - clat)) % 360.0
    out = []
    for c in (45.0, 135.0, 225.0, 315.0):
        g = (np.abs(((b - c + 180.0) % 360.0) - 180.0) < 15.0) & \
            (field >= 34.0)
        out.append(int(round(dist[g].max())) if g.any() else 0)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out", default=os.path.join(
        HERE, "out", "extension_shape.png"))
    args = parser.parse_args()

    plain, lat, lon, ext, t0 = run(False)
    shaped, _, _, _, _ = run(True)
    panels = [(plain, 144, "Before: the wind model's own shape"),
              (shaped, 132, "After, 132 h: half way in"),
              (shaped, 144, "After, 144 h: 85 % of the radii")]

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 6.2), dpi=130)
    for ax, (winds, h, title) in zip(axes, panels):
        when = t0 + h * 3600
        snap = tc.interpolateTrack(ext, when)
        f = winds[when]
        ax.contourf(lon, lat, f, levels=[34, 48, 200], colors=[GALE, STORM],
                    alpha=0.6)
        ax.contour(lon, lat, f, levels=[34], colors="#8a6100",
                   linewidths=0.8)
        if snap.radii.get(34):
            x, y = outline(snap.lat, snap.lon, snap.radii[34])
            ax.plot(x, y, color=BLUE, linewidth=1.2, linestyle=(0, (4, 2)))
            target = dict((q, tc.SHAPE_RADIUS_FACTOR * v)
                          for q, v in snap.radii[34].items())
            x, y = outline(snap.lat, snap.lon, target)
            ax.plot(x, y, color=BLUE, linewidth=1.6)
        ax.plot(snap.lon, snap.lat, "x", color=BLUE, markersize=9,
                markeredgewidth=2)
        got = extents(f, lat, lon, snap.lat, snap.lon)
        ax.text(0.03, 0.04, "34 kt extent NE/SE/SW/NW: %d/%d/%d/%d nm\n"
                "entered at 144 h:     300/250/60/40\n"
                "85%% target:           255/213/51/34" % tuple(got),
                transform=ax.transAxes, fontsize=8, family="monospace",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#ddd"))
        ax.set_xlim(LON - 7, LON + 9)
        ax.set_ylim(LAT - 7, LAT + 7)
        ax.set_aspect(1.0 / np.cos(np.radians(LAT)))
        ax.tick_params(labelsize=7, colors="#8a8984")
        ax.grid(True, color="#eee", linewidth=0.5)
        ax.set_title("%s  (%s)" % (title, time.strftime(
            "%d/%HZ", time.gmtime(when))), fontsize=9.5, loc="left")
    fig.legend(handles=[
        Patch(color=GALE, alpha=0.6, label="WindJTWC 34-47 kt"),
        Patch(color=STORM, alpha=0.6, label="48 kt+"),
        Line2D([], [], color=BLUE, lw=1.2, ls=(0, (4, 2)),
               label="entered 34 kt radii (interpolated at 132 h)"),
        Line2D([], [], color=BLUE, lw=1.6, label="85 % of them: the target"),
        Line2D([], [], color=BLUE, marker="x", ls="none", ms=8, mew=2,
               label="center")],
        loc="lower center", ncol=5, frameon=False, fontsize=8.5)
    fig.suptitle("Days 6-7 forecaster point: 50 kt, 34 kt radii "
                 "300/250/60/40 nm", x=0.035, ha="left", fontsize=13,
                 y=0.975)
    fig.text(0.035, 0.905, "Synthetic point added after the real KROVANH "
             "warning (ends 120 h).  Wind grids as the procedure writes "
             "them; 10 kt background.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.035, right=0.99, top=0.85, bottom=0.12,
                        wspace=0.12)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, facecolor="white")
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
