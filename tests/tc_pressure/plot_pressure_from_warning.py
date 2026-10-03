#!/usr/bin/env python3
"""Walk one synthetic typhoon from its warning to the pmsl field, step by step.

A JTWC warning for a 100 kt typhoon, 950 mb, is written in the real layout,
parsed and fitted by TCWind_JTWC, and turned into pressure by TCPressure:

    1. the warning: position and quadrant wind radii
    2. the wind profile fitted to them, and the gradient wind it implies
    3. gradient-wind balance, integrated in: the pressure profile
    4. a model's pmsl, with its own typhoon 110 nm off and too shallow
    5. that model's typhoon removed
    6. the warning's typhoon implanted

    python3 plot_pressure_from_warning.py [-o out.png]
"""
import argparse
import calendar
import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "..")
for sub in ("GFE/utilities", "GFE/procedures"):
    sys.path.insert(0, os.path.join(REPO, sub))
sys.path.insert(0, HERE)

import TCPressure as P                                          # noqa: E402
import TCWind_JTWC as W                                         # noqa: E402
from synth_warning import jtwcWarning                           # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8984"
GRID = "#e6e5e0"
BLUE = "#2a78d6"        # the warning
ORANGE = "#eb6834"      # the model
AQUA = "#1baf7a"        # the gradient wind / scaled profile

T0 = calendar.timegm((2026, 10, 2, 18, 0, 0))
TRACK = [(0, 20.0, 137.0, 100, 150), (12, 21.0, 136.0, 105, 160),
         (24, 22.2, 135.0, 105, 170)]
BULLETIN_MB = 950
MODEL_LOW = (21.2, 138.6, 26.0, 1.7)     # lat, lon, depth mb, size deg


def environment(lat, lon):
    """A ridge to the north, a monsoon trough to the south."""
    return (1005.0 + 0.35 * (lat - 15.0) +
            1.2 * np.sin(np.radians((lon - 120.0) * 8.0)))


def modelPmsl(lat, lon):
    clat, clon, depth, size = MODEL_LOW
    d = P.distanceNm(lat, lon, clat, clon) / 60.0
    return environment(lat, lon) - depth * np.exp(-(d / size) ** 2)


def style(ax, title):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=7.5, length=3)
    ax.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.set_title(title, loc="left", fontsize=10, color=INK, pad=8,
                 fontweight="bold")


def radiiOutline(snap, kt):
    """Quarter circles through the warning's quadrant radii, lat/lon."""
    quad = snap.radii.get(kt)
    if not quad:
        return None
    lats, lons = [], []
    for name, (b0, b1) in (("NE", (0, 90)), ("SE", (90, 180)),
                           ("SW", (180, 270)), ("NW", (270, 360))):
        r = quad[name] / 60.0
        for b in np.linspace(b0, b1, 24):
            lats.append(snap.lat + r * np.cos(np.radians(b)))
            lons.append(snap.lon + r * np.sin(np.radians(b)) /
                        np.cos(np.radians(snap.lat)))
    return np.array(lons + lons[:1]), np.array(lats + lats[:1])


def mapPanel(ax, lat, lon, field, title, snap=None, model=False,
             radii=False):
    style(ax, title)
    # Contour only what is in view, so no label lands off the edge.
    view = ((lon[0] >= 130.5) & (lon[0] <= 144.5))
    rows = ((lat[:, 0] >= 14.0) & (lat[:, 0] <= 28.0))
    lat, lon, field = lat[rows][:, view], lon[rows][:, view], \
        field[rows][:, view]
    levels = np.arange(940.0, 1024.1, 4.0)
    cs = ax.contour(lon, lat, field, levels=levels, colors=INK2,
                    linewidths=0.8, zorder=2)
    # Label every 8 mb, and only outside the packed core.
    ax.clabel(cs, [v for v in levels if v % 8 == 0 and v >= 992],
              fontsize=6.5, fmt="%d", inline_spacing=2)
    i, j = np.unravel_index(np.argmin(field), field.shape)
    if field[i, j] < environment(lat[i, j], lon[i, j]) - 2.0:
        ax.annotate("L %.0f" % field[i, j], (lon[i, j], lat[i, j]),
                    textcoords="offset points", xytext=(30, 30),
                    fontsize=8.5, fontweight="bold", color=INK, zorder=7,
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                              edgecolor=GRID),
                    arrowprops=dict(arrowstyle="-", color=INK2,
                                    linewidth=0.8))
    if model:
        ax.plot(MODEL_LOW[1], MODEL_LOW[0], marker="o", markersize=9,
                markerfacecolor="none", markeredgecolor=ORANGE,
                markeredgewidth=2, zorder=4)
    if snap is not None:
        ax.plot(snap.lon, snap.lat, marker="x", markersize=10,
                color=BLUE, markeredgewidth=2.2, zorder=6)
    if radii and snap is not None:
        outline = radiiOutline(snap, 34)
        if outline is not None:
            ax.plot(outline[0], outline[1], color=BLUE, linewidth=1.4,
                    linestyle=(0, (4, 2)), zorder=3)
    ax.set_xlim(130.5, 144.5)
    ax.set_ylim(14, 28)
    ax.set_aspect(1.0 / np.cos(np.radians(21.0)))
    ax.set_xticks(range(132, 145, 4))
    ax.set_xticklabels(["%dE" % x for x in range(132, 145, 4)])
    ax.set_yticks(range(16, 29, 4))
    ax.set_yticklabels(["%dN" % y for y in range(16, 29, 4)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out", default=os.path.join(
        HERE, "out", "pressure_from_warning.png"))
    args = parser.parse_args()

    text = jtwcWarning(T0, TRACK, BULLETIN_MB, "TESTER")
    taus, header, _ = W.parseBulletin(text, T0 + 3 * 3600)
    snap = W.interpolateTrack(taus, T0)
    storm = P.stormFromSnapshot(snap, "TESTER")
    storm["anchor"] = (dict(storm), float(BULLETIN_MB))

    lat1, lon1 = np.arange(12.0, 30.01, 0.1), np.arange(128.0, 147.01, 0.1)
    lon, lat = np.meshgrid(lon1, lat1)
    model = modelPmsl(lat, lon)
    hit = P.findBackgroundCenter(model, lat, lon, storm["lat"], storm["lon"])
    removed = P.removeVortex(model, lat, lon, hit[0], hit[1])
    final, report = P.relocateStorms(model, lat, lon, [storm])
    rep = report[0]
    env, scale = rep["envMb"], rep["scale"]

    rOut = P.outerRadius(storm)
    r = np.linspace(0.5, rOut * 1.08, 1200)
    vSfc = P.symmetricWind(r, storm)
    rTaper = P.TAPER_FROM * rOut
    t = np.clip((r - rTaper) / (rOut - rTaper), 0.0, 1.0)
    vGrad = vSfc / P.SFC_TO_GRADIENT * np.cos(0.5 * np.pi * t) ** 2
    rD, deficit = P.pressureDeficit(storm)

    fig = plt.figure(figsize=(14.5, 9.6), dpi=130, facecolor=SURFACE)
    gs = fig.add_gridspec(2, 3, left=0.05, right=0.985, top=0.87,
                          bottom=0.09, wspace=0.22, hspace=0.36)

    # 1. The warning.
    ax = fig.add_subplot(gs[0, 0])
    style(ax, "1  The warning")
    for kt, alpha in ((34, 1.0), (50, 0.75), (64, 0.5)):
        outline = radiiOutline(snap, kt)
        if outline is not None:
            ax.fill(outline[0], outline[1], color=BLUE, alpha=0.12 * alpha,
                    zorder=2, linewidth=0)
            ax.plot(outline[0], outline[1], color=BLUE, linewidth=1.2,
                    alpha=alpha, zorder=3)
            ax.annotate("%d kt" % kt, (outline[0][0], outline[1][0]),
                        textcoords="offset points", xytext=(3, 2),
                        fontsize=7.5, color=INK2)
    ax.plot(snap.lon, snap.lat, marker="x", markersize=10, color=BLUE,
            markeredgewidth=2.2, zorder=4)
    q = snap.radii[34]
    ax.text(0.03, 0.04, "TY 25W (TESTER)  %s\n%.1fN %.1fE\n"
            "%d kt, %d mb\nR34  NE %d  SE %d  SW %d  NW %d nm" % (
                "02/18Z", snap.lat, snap.lon, snap.vmax, BULLETIN_MB,
                q["NE"], q["SE"], q["SW"], q["NW"]),
            transform=ax.transAxes, fontsize=7.5, color=INK,
            family="monospace", va="bottom",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor=GRID))
    ax.set_xlim(snap.lon - 4.5, snap.lon + 4.5)
    ax.set_ylim(snap.lat - 4.0, snap.lat + 4.0)
    ax.set_aspect(1.0 / np.cos(np.radians(snap.lat)))
    ax.tick_params(labelsize=7.5)

    # 2. The wind profile.
    ax = fig.add_subplot(gs[0, 1])
    style(ax, "2  Wind profile fitted to the radii")
    ax.plot(r, vSfc, color=BLUE, linewidth=2.0, label="surface wind (fit)")
    ax.plot(r, vGrad, color=AQUA, linewidth=2.0,
            label="gradient wind = surface / 0.85, tapered")
    for kt in (34, 50, 64):
        quad = snap.radii.get(kt) or {}
        xs = [v for v in quad.values() if v > 0]
        ax.plot(xs, [kt] * len(xs), "o", markersize=4.5, color=INK2,
                zorder=4)
    ax.plot([], [], "o", markersize=4.5, color=INK2,
            label="warning's quadrant radii")
    for x, name in ((storm["rm"], "rm"), (rTaper, "taper"),
                    (rOut, "outer edge")):
        ax.axvline(x, color=MUTED, linewidth=0.8, linestyle=(0, (2, 2)))
        ax.text(x, 128, " " + name, fontsize=7, color=MUTED, va="top")
    ax.set_xlim(0, rOut * 1.08)
    ax.set_ylim(0, 130)
    ax.set_xlabel("distance from center, nm", fontsize=8, color=INK2)
    ax.set_ylabel("kt", fontsize=8, color=INK2)
    ax.legend(fontsize=7.5, frameon=False, loc="upper right",
              bbox_to_anchor=(1.0, 0.86))

    # 3. Pressure.
    ax = fig.add_subplot(gs[0, 2])
    style(ax, "3  Gradient-wind balance, integrated inward")
    ax.plot(rD, env - deficit, color=MUTED, linewidth=1.6,
            linestyle=(0, (4, 2)), label="unscaled: %.0f mb" %
            (env - deficit[0]))
    ax.plot(rD, env - scale * deficit, color=BLUE, linewidth=2.0,
            label="scaled x%.2f: %.0f mb = bulletin" %
            (scale, env - scale * deficit[0]))
    ax.axhline(env, color=INK2, linewidth=0.8)
    ax.text(rOut * 1.06, env - 2.8, "environment %.1f mb" % env,
            fontsize=7.5, color=INK2, ha="right")
    ax.set_xlim(0, rOut * 1.08)
    ax.set_ylim(940, env + 3)
    ax.set_xlabel("distance from center, nm", fontsize=8, color=INK2)
    ax.set_ylabel("mb", fontsize=8, color=INK2)
    ax.legend(fontsize=7.5, frameon=False, loc="lower right")
    ax.text(0.97, 0.62, "dp/dr = \u03c1 (vg\u00b2/r + f vg)\n"
            "deficit zero at the outer edge,\nsummed inward to the center",
            transform=ax.transAxes, fontsize=7.5, color=INK2, va="top",
            ha="right")

    # 4-6. The field.
    mapPanel(fig.add_subplot(gs[1, 0]), lat, lon, model,
             "4  Model pmsl", snap=snap, model=True)
    mapPanel(fig.add_subplot(gs[1, 1]), lat, lon, removed,
             "5  Model's typhoon removed", snap=snap, model=True)
    mapPanel(fig.add_subplot(gs[1, 2]), lat, lon, final,
             "6  Warning's typhoon implanted", snap=snap, radii=True)

    fig.legend(handles=[
        Line2D([], [], color=BLUE, marker="x", linestyle="none",
               markersize=8, markeredgewidth=2, label="warning position"),
        Line2D([], [], color=BLUE, linestyle=(0, (4, 2)),
               label="warning's 34 kt radii"),
        Line2D([], [], color=ORANGE, marker="o", linestyle="none",
               markerfacecolor="none", markersize=8, markeredgewidth=2,
               label="where the model had it"),
        Line2D([], [], color=INK2, linewidth=0.8, label="isobars, 4 mb")],
        loc="lower center", ncol=4, frameon=False, fontsize=8.5)
    fig.suptitle("From a warning to a pmsl field - synthetic typhoon",
                 x=0.05, ha="left", fontsize=14, color=INK, y=0.975)
    fig.text(0.05, 0.925,
             "A 100 kt, 950 mb typhoon. The model has it %.0f nm to the "
             "northeast and %.0f mb too shallow; the result is %.0f mb at the "
             "warning position." % (rep["offsetNm"],
                                    model.min() - BULLETIN_MB,
                                    final.min()),
             fontsize=9, color=INK2)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, facecolor=SURFACE)
    print("wrote %s" % args.out)
    print("fit: rm %.1f ri %.1f x1 %.2f x2 %.2f a %.1f; R34 %.0f; Rout %.0f;"
          " env %.1f scale %.2f deficit %.1f; model min %.1f; final %.1f; "
          "offset %.0f nm" % (storm["rm"], storm["ri"], storm["x1"],
                              storm["x2"], storm["a"], storm["r34"], rOut,
                              env, scale, deficit[0], model.min(),
                              final.min(), rep["offsetNm"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
