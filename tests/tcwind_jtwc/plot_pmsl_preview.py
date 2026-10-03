#!/usr/bin/env python3
"""Plot the pmsl option: Fcst pmsl against the pmslJTWC preview.

Runs Procedure.execute() through test_procedure_harness.py on the real
KROVANH warning, with a Fcst pmsl that has the storm 1.5 degrees northeast of
the warning all along the track, and draws the input grid and the preview
the run wrote side by side at three times.

    python3 plot_pmsl_preview.py [-o out.png]
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_procedure_harness as H                            # noqa: E402

tc = H.tc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out",
                        default=os.path.join(HERE, "out", "pmsl_preview.png"))
    args = parser.parse_args()

    taus = tc.parseBulletin(H._load_fixture(H.KROVANH))[0]
    fcst = H._modelPmsl(taus)
    proc, taus, header, lat, lon = H._run_pmsl(fcst)
    writes = H._pmslWrites(proc)
    t0 = taus[0].epoch
    times = [t0, t0 + 24 * 3600, t0 + 48 * 3600]

    fig, axes = plt.subplots(2, 3, figsize=(13.0, 8.4), dpi=130)
    levels = np.arange(960.0, 1020.1, 2.0)
    for col, when in enumerate(times):
        snap = tc.interpolateTrack(taus, when)
        for row, (field, title) in enumerate((
                (fcst(lat, lon, when), "Fcst pmsl"),
                (writes[when][1], "pmslJTWC preview"))):
            ax = axes[row, col]
            cs = ax.contour(lon, lat, field, levels=levels,
                            colors="#33404f", linewidths=0.8)
            ax.clabel(cs, levels[::2], fontsize=6.5, fmt="%d")
            ax.plot([t.lon for t in taus], [t.lat for t in taus],
                    color="#1f5fbf", linewidth=1.0, linestyle=(0, (3, 2)))
            ax.plot(snap.lon, snap.lat, marker="x", color="#1f5fbf",
                    markersize=10, markeredgewidth=2.2)
            i, j = np.unravel_index(np.argmin(field), field.shape)
            ax.plot(lon[i, j], lat[i, j], "o", markersize=13,
                    markerfacecolor="white", markeredgecolor="#b3261e",
                    markeredgewidth=1.5)
            ax.text(lon[i, j], lat[i, j], "L", ha="center", va="center",
                    fontsize=8, fontweight="bold", color="#b3261e")
            ax.annotate("%.0f" % field[i, j], (lon[i, j], lat[i, j]),
                        textcoords="offset points", xytext=(0, -16),
                        ha="center", fontsize=8, color="#b3261e")
            ax.set_xlim(122, 138)
            ax.set_ylim(18, 34)
            ax.set_aspect(1.0 / np.cos(np.radians(26.0)))
            ax.tick_params(labelsize=7, colors="#6b7684")
            ax.set_title("%s  tau %d  (%s)" % (
                title, (when - t0) // 3600,
                time.strftime("%d/%HZ", time.gmtime(when))), fontsize=9)
    fig.legend(handles=[
        Line2D([], [], color="#1f5fbf", linestyle=(0, (3, 2)),
               label="JTWC warning track (KROVANH, warning 5)"),
        Line2D([], [], color="#1f5fbf", marker="x", linestyle="none",
               markersize=8, markeredgewidth=2,
               label="Warning position at that time"),
        Line2D([], [], marker="o", linestyle="none", markersize=9,
               markerfacecolor="white", markeredgecolor="#b3261e",
               label="Lowest pressure in the grid")],
        loc="lower center", ncol=3, frameon=False, fontsize=8.5)
    fig.suptitle("TCWind_JTWC pmsl option: the storm moved to the warning",
                 fontsize=12.5, y=0.985)
    fig.text(0.5, 0.945, "Real warning, synthetic Fcst pmsl with the storm "
             "1.5 deg NE of the warning; the bulletin's tau-0 central "
             "pressure is %d mb.  2 mb isobars." % header["pressureMb"],
             ha="center", fontsize=8, color="#6b7684")
    fig.subplots_adjust(left=0.04, right=0.99, top=0.9, bottom=0.08,
                        hspace=0.22, wspace=0.08)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, facecolor="white")
    print("wrote %s" % args.out)
    print(H._final_status(proc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
