#!/usr/bin/env python3
"""Plot a lopsided forecaster point - by default 50 kt, 34 kt radii
300/250/60/40 nm.

Runs Procedure.execute() through test_procedure_harness.py on the real
KROVANH warning (ends at 120 h) with a forecaster point at 144 h, and draws
the WindJTWC grid it writes there - once with the 34 kt line made to follow
the entered radii, once without (the wind model's own circle-plus-shift) -
and at 132 h, half way through the fade-in.

    python3 plot_extension_shape.py [-o out.png]
        [--radii NE SE SW NW] [--vmax KT] [--lat LAT] [--lon LON]
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
VMAX = 50.0
RADII = {"NE": 300.0, "SE": 250.0, "SW": 60.0, "NW": 40.0}


def setup():
    """(warning text, PIL, store key, lat grid, lon grid) for the run.

    At the default position, the real KROVANH warning on the harness's own
    grid.  Anywhere else (--lat/--lon), a synthetic warning written in the
    JTWC layout whose track ends 24 h before the point and a few degrees
    short of it, on a grid around the point - in 0..360 longitudes, so a
    point near the dateline is one piece.
    """
    if (LAT, LON) == (27.0, 130.0):
        latGrid, lonGrid = H._mesh()
        return (H._load_fixture(H.KROVANH), "NFDTCPWP1", "22W",
                latGrid, lonGrid)
    sys.path.insert(0, os.path.join(HERE, "..", "tc_pressure"))
    from synth_warning import jtwcWarning
    t0 = int(time.time()) // 21600 * 21600 - 6 * 3600
    lon360 = LON % 360.0
    track = [(tau, LAT - 6.0 + 4.0 * tau / 120.0,
              lon360 - 8.0 + 5.0 * tau / 120.0, 55, 200)
             for tau in (0, 24, 48, 72, 96, 120)]
    reach = max(RADII.values()) / 60.0 + 3.0
    lat1d = np.arange(LAT - reach, LAT + reach, 0.1)
    lon1d = np.arange(lon360 - reach / np.cos(np.radians(LAT)),
                      lon360 + reach / np.cos(np.radians(LAT)), 0.1)
    lonGrid, latGrid = np.meshgrid(lon1d, lat1d)
    return (jtwcWarning(t0, track, None, "TESTER"), "NFDTCPWP1", "25W",
            latGrid.astype(np.float32), lonGrid.astype(np.float32))


def run(shaped):
    text, pil, key, latGrid, lonGrid = setup()
    taus = tc.parseBulletin(text)[0]
    t0 = taus[0].epoch
    pts = [{"epoch": t0 + 144 * 3600, "lat": LAT, "lon": LON, "vmax": VMAX,
            "pressureMb": None, "extratropical": False, "r34": dict(RADII)},
           {"epoch": t0 + 168 * 3600, "lat": LAT + 2.0, "lon": LON + 4.0,
            "vmax": VMAX, "pressureMb": None, "extratropical": False,
            "r34": dict(RADII)}]
    path = H._withStore(pts, key=key)
    saved = tc.shapeWeightAt
    if not shaped:
        tc.shapeWeightAt = lambda taus, epoch: 0.0
    try:
        proc = tc.Procedure(dbss=None)
        proc.configure(texts={pil: text}, now_epoch=t0 + 3 * 3600,
                       inv_start=t0, inv_end=t0 + 171 * 3600,
                       lat=latGrid, lon=lonGrid)
        proc.execute(None, None, {
            tc.BASINS_LABEL: ["West Pac"], "Write to:": "Preview grid",
            "Run over selected time range only?": "No",
            tc.PMSL_LABEL: "No", tc.EXTENSION_LABEL: "Use saved"})
    finally:
        tc.shapeWeightAt = saved
        os.remove(path)
    winds = dict((a[4].startTime().unixTime(), np.asarray(a[3][0]))
                 for a, _ in proc.created if a[2] == "VECTOR")
    ext, _, _ = tc.extendTrack(taus, pts)
    return winds, latGrid, lonGrid, ext, t0


def outline(clat, clon, quad):
    az = np.arange(0.0, 360.1, 2.0)
    r = tc._quadrantTable(quad, az) / 60.0
    return (clon + r * np.sin(np.radians(az)) / np.cos(np.radians(clat)),
            clat + r * np.cos(np.radians(az)))


def gridLon(lon, ref):
    """``lon`` in the same 360 degrees as the grid's ``ref``."""
    return ref + ((lon - ref + 180.0) % 360.0) - 180.0


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
    parser.add_argument("--radii", nargs=4, type=float,
                        metavar=("NE", "SE", "SW", "NW"))
    parser.add_argument("--vmax", type=float)
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    args = parser.parse_args()
    global LAT, LON, VMAX
    if args.radii:
        RADII.update(zip(tc.QUADS, args.radii))
    VMAX = args.vmax or VMAX
    LAT = args.lat if args.lat is not None else LAT
    LON = args.lon if args.lon is not None else LON
    entered = "/".join("%.0f" % RADII[q] for q in tc.QUADS)
    targetText = "/".join("%.0f" % (tc.SHAPE_RADIUS_FACTOR * RADII[q])
                          for q in tc.QUADS)
    reach = max(RADII.values()) / 60.0 + 1.5

    plain, lat, lon, ext, t0 = run(False)
    shaped, _, _, _, _ = run(True)
    panels = [(plain, 144, "Before: the wind model's own shape"),
              (shaped, 132, "After, 132 h: half way in"),
              (shaped, 144, "After, 144 h: 85 % of the radii")]

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 6.2), dpi=130)
    for ax, (winds, h, title) in zip(axes, panels):
        when = t0 + h * 3600
        snap = tc.interpolateTrack(ext, when)
        snapLon = gridLon(snap.lon, float(lon.mean()))
        f = winds[when]
        ax.contourf(lon, lat, f, levels=[34, 48, 200], colors=[GALE, STORM],
                    alpha=0.6)
        ax.contour(lon, lat, f, levels=[34], colors="#8a6100",
                   linewidths=0.8)
        if snap.radii.get(34):
            x, y = outline(snap.lat, snapLon, snap.radii[34])
            ax.plot(x, y, color=BLUE, linewidth=1.2, linestyle=(0, (4, 2)))
            target = dict((q, tc.SHAPE_RADIUS_FACTOR * v)
                          for q, v in snap.radii[34].items())
            x, y = outline(snap.lat, snapLon, target)
            ax.plot(x, y, color=BLUE, linewidth=1.6)
        ax.plot(snapLon, snap.lat, "x", color=BLUE, markersize=9,
                markeredgewidth=2)
        got = extents(f, lat, lon, snap.lat, snapLon)
        ax.text(0.03, 0.04, "34 kt extent NE/SE/SW/NW: %d/%d/%d/%d nm\n"
                "entered at 144 h:     %s\n"
                "85%% target:           %s" % (tuple(got) + (entered,
                                                            targetText)),
                transform=ax.transAxes, fontsize=8, family="monospace",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#ddd"))
        centre = gridLon(LON, float(lon.mean()))
        ax.set_xlim(centre - reach / np.cos(np.radians(LAT)),
                    centre + reach / np.cos(np.radians(LAT)))
        ticks = ax.get_xticks()
        ax.set_xticks(ticks)
        ax.set_xticklabels(["%.0f%s" % (abs(((t + 180) % 360) - 180),
                                        "E" if ((t + 180) % 360) - 180 >= 0
                                        else "W") for t in ticks])
        ax.set_ylim(LAT - reach, LAT + reach)
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
    fig.suptitle("Days 6-7 forecaster point: %.0f kt, 34 kt radii %s nm"
                 % (VMAX, entered), x=0.035, ha="left", fontsize=13,
                 y=0.975)
    fig.text(0.035, 0.905, "Synthetic point at %.1f%s %.1f%s, added after "
             "a %s warning (ends 120 h).  Wind grids as the procedure writes "
             "them; 10 kt background." % (
                 abs(LAT), "N" if LAT >= 0 else "S", abs(LON),
                 "E" if LON >= 0 else "W",
                 "the real KROVANH" if (LAT, LON) == (27.0, 130.0)
                 else "synthetic"), fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.035, right=0.99, top=0.85, bottom=0.12,
                        wspace=0.12)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, facecolor="white")
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
