#!/usr/bin/env python3
"""Plot the days 6-7 extension: KROVANH carried past its warning.

Runs Procedure.execute() through test_procedure_harness.py on the real
KROVANH warning (ends at 120 h) with two forecaster points - 144 h tropical,
168 h extratropical at 985 mb with a one-sided gale field - and draws the
WindJTWC and pmslJTWC preview grids at 120, 144 and 168 h.

    python3 plot_extension.py [-o out.png]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out",
                        default=os.path.join(HERE, "out", "extension.png"))
    args = parser.parse_args()

    taus = H._krovanhTaus()
    t0 = taus[0].epoch
    points = [
        {"epoch": t0 + 144 * 3600, "lat": 29.5, "lon": 131.0, "vmax": 45.0,
         "pressureMb": None, "extratropical": False,
         "r34": {"NE": 200.0, "SE": 180.0, "SW": 90.0, "NW": 120.0}},
        {"epoch": t0 + 168 * 3600, "lat": 32.0, "lon": 134.0, "vmax": 50.0,
         "pressureMb": 985.0, "extratropical": True,
         "r34": {"NE": 300.0, "SE": 330.0, "SW": 80.0, "NW": 60.0}}]
    path = H._withStore(points)
    ext, _, _ = tc.extendTrack(taus, points)
    # The model has the storm 1.5 degrees NE of the track all the way,
    # forecaster points included.
    proc, _, _, lat, lon = H._run_pmsl(
        H._modelPmsl(ext), extra={tc.EXTENSION_LABEL: "Use saved"},
        pmsl_until_hours=168)
    os.remove(path)
    pmsl = dict((k, v[1]) for k, v in H._pmslWrites(proc).items())
    wind = dict((a[4].startTime().unixTime(), np.asarray(a[3][0]))
                for a, _ in proc.created if a[2] == "VECTOR")

    hours = (120, 144, 168)
    labels = ("120 h - warning's last time",
              "144 h - forecaster point",
              "168 h - forecaster point, extratropical, 985 mb")
    fig, axes = plt.subplots(1, 3, figsize=(15.0, 5.9), dpi=130)
    for ax, h, label in zip(axes, hours, labels):
        when = t0 + h * 3600
        ax.contourf(lon, lat, wind[when], levels=[34, 48, 200],
                    colors=[GALE, STORM], alpha=0.55)
        cs = ax.contour(lon, lat, pmsl[when], levels=np.arange(960, 1021, 4),
                        colors=INK2, linewidths=0.8)
        ax.clabel(cs, fontsize=6.5, fmt="%d")
        ax.plot([t.lon for t in ext], [t.lat for t in ext], color=BLUE,
                linewidth=1.0, linestyle=(0, (3, 2)))
        ax.plot([t.lon for t in ext if t.synthetic],
                [t.lat for t in ext if t.synthetic], "s", color=BLUE,
                markersize=5)
        snap = tc.interpolateTrack(ext, when)
        ax.plot(snap.lon, snap.lat, "x", color=BLUE, markersize=10,
                markeredgewidth=2.2)
        p = [q for q in points if q["epoch"] == when]
        if p:
            r = p[0]["r34"]
            xs, ys = [], []
            for q, (b0, b1) in zip(tc.QUADS, ((0, 90), (90, 180), (180, 270),
                                              (270, 360))):
                for b in np.linspace(b0, b1, 20):
                    ys.append(snap.lat + r[q] / 60.0 * np.cos(np.radians(b)))
                    xs.append(snap.lon + r[q] / 60.0 * np.sin(np.radians(b)) /
                              np.cos(np.radians(snap.lat)))
            ax.plot(xs + xs[:1], ys + ys[:1], color=BLUE, linewidth=1.3)
        field = pmsl[when]
        i, j = np.unravel_index(np.argmin(field), field.shape)
        ax.annotate("L %.0f" % field[i, j], (lon[i, j], lat[i, j]),
                    textcoords="offset points", xytext=(18, -22),
                    fontsize=8.5, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="#e6e5e0"),
                    arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
        ax.set_xlim(122, 140)
        ax.set_ylim(18, 35)
        ax.set_aspect(1.0 / np.cos(np.radians(27.0)))
        ax.tick_params(labelsize=7, colors="#8a8984")
        ax.set_title("%s  (%s)" % (label, time.strftime(
            "%d/%HZ", time.gmtime(when))), fontsize=9, loc="left")
    fig.legend(handles=[
        Patch(color=GALE, alpha=0.55, label="WindJTWC 34-47 kt"),
        Patch(color=STORM, alpha=0.55, label="48 kt+"),
        Line2D([], [], color=BLUE, lw=1.3,
               label="forecaster's 34 kt radii"),
        Line2D([], [], color=BLUE, ls=(0, (3, 2)), marker="s", ms=4,
               label="track, forecaster points as squares"),
        Line2D([], [], color=INK2, lw=0.8, label="pmslJTWC, 4 mb")],
        loc="lower center", ncol=5, frameon=False, fontsize=8.5)
    fig.suptitle("Days 6-7: KROVANH carried past its warning", x=0.04,
                 ha="left", fontsize=13, y=0.98)
    fig.text(0.04, 0.905, "Real warning to 120 h; two forecaster points "
             "added in the days 6-7 dialog.  Preview grids as the run "
             "wrote them.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.035, right=0.99, top=0.84, bottom=0.12,
                        wspace=0.12)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, facecolor="white")
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
