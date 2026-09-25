#!/usr/bin/env python3
"""Draw a synthetic case through CreateXML_WindHazards.py and plot the result.

Builds a deepening North Atlantic low that tracks northeast over 48 hours,
plus a weaker gale-only feature in the east, drives the real procedure over
it through the fakes in test_windhazard_xml.py, then plots *the XML the
procedure wrote* - every polygon, Low and track vertex comes back out of the
file, not from the fields.  So the picture is what PGEN would be handed.

The four layers are drawn as a forecaster would see them with everything
switched on: one panel per wind period, with the shared Lows and Track layers
repeated on both.

    python3 plot_synthetic_case.py [-o out.png]

Colors are the procedure's own BAND_COLORS, which is the point: the marine
warning convention, yellow/orange/red, is what PGEN will draw.  Nothing here
is real weather.
"""
import argparse
import os
import sys
from datetime import datetime
from xml.etree import ElementTree as ET

import numpy as np

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.path import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_windhazard_xml as harness            # noqa: E402  (fakes live here)

# The procedure resolves "18z" against the real clock, so the fake database
# has to sit on the day it picks rather than a fixed date.
CYCLE = harness.mostRecentCycle(18)

# --- Domain: western North Atlantic, half-degree ---------------------------
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, STEP = 25.0, 62.0, -75.0, -15.0, 0.5

# --- A crude east-coast outline.  Doubles as the "Land" edit area, so the
# --- polygons are clipped by exactly the coast that gets drawn.
COAST = [(-75, 25), (-81, 25), (-81, 31), (-79, 33), (-76.5, 35), (-75, 38),
         (-73.5, 40.5), (-70, 42), (-67, 44.5), (-64, 45), (-60, 46.5),
         (-55, 47), (-52.5, 48), (-55.5, 52), (-62, 55), (-68, 58),
         (-75, 61), (-81, 61)]

# --- The primary low: (forecast hour, lat, lon, central pressure, peak wind)
TRACK = [(0, 36.0, -66.0, 992.0, 46.0),
         (6, 38.5, -63.0, 984.0, 54.0),
         (12, 41.0, -59.5, 975.0, 62.0),
         (18, 43.0, -57.0, 970.0, 66.0),
         (24, 45.0, -54.0, 966.0, 68.0),
         (30, 47.5, -50.0, 961.0, 74.0),
         (36, 50.0, -45.5, 956.0, 80.0),
         (42, 52.0, -41.0, 958.0, 72.0),
         (48, 53.5, -37.0, 963.0, 64.0)]

# --- A second, weaker low that never gets past gale force.
# 36 kt peak, so even the +30% asymmetric flank stays under 48 kt.
TRACK2 = [(hr, 43.0 + 0.10 * hr, -27.0 + 0.16 * hr, 1000.0 - 0.10 * hr, 36.0)
          for hr, _, _, _, _ in TRACK]

# A High, to show it is not plotted: only Lows are wanted on the chart.
HIGH = (31.0, -34.0, 1028.0)

ENV_PRESSURE = 1016.0
RMAX_KM = 220.0          # radius of maximum wind
LSCALE_KM = 520.0        # pressure field length scale


def domainGrids():
    lats = np.arange(LAT_MIN, LAT_MAX + STEP, STEP)
    lons = np.arange(LON_MIN, LON_MAX + STEP, STEP)
    lon2d, lat2d = np.meshgrid(lons, lats)
    return lat2d, lon2d


def rangeAndBearing(lat2d, lon2d, clat, clon):
    """Great-circle-ish range in km and bearing from a center, flat-earth."""
    dy = (lat2d - clat) * 111.2
    dx = (lon2d - clon) * 111.2 * np.cos(np.radians(lat2d))
    return np.hypot(dx, dy), np.degrees(np.arctan2(dx, dy)) % 360.0


def interpTrack(track, hr):
    hrs = [t[0] for t in track]
    return [np.interp(hr, hrs, [t[i] for t in track]) for i in (1, 2, 3, 4)]


def vortexWind(lat2d, lon2d, clat, clon, vmax, rmax=RMAX_KM):
    """Modified Rankine vortex, stronger on the south side of the center."""
    rng, brg = rangeAndBearing(lat2d, lon2d, clat, clon)
    inner = vmax * (rng / rmax)
    outer = vmax * np.power(np.maximum(rng, 1.0) / rmax, -0.62)
    mag = np.where(rng <= rmax, inner, outer)
    # Asymmetry: peak on the southern flank, as a fast-moving low usually is.
    mag = mag * (1.0 + 0.30 * np.cos(np.radians(brg - 190.0)))
    direc = (brg + 110.0) % 360.0        # cyclonic inflow
    return mag, direc


def windFn(hr, lat2d, lon2d):
    """Wind grid the fake getGrids hands back for forecast hour ``hr``."""
    mag = np.full(lat2d.shape, 8.0)
    direc = np.full(lat2d.shape, 270.0)
    for track in (TRACK, TRACK2):
        clat, clon, _, vmax = interpTrack(track, hr)
        m, d = vortexWind(lat2d, lon2d, clat, clon, vmax)
        direc = np.where(m > mag, d, direc)
        mag = np.maximum(mag, m)
    return mag, direc


def pmslFn(hr, lat2d, lon2d):
    """pmsl grid: both lows plus a High that must not be plotted."""
    grid = np.full(lat2d.shape, ENV_PRESSURE)
    for track in (TRACK, TRACK2):
        clat, clon, pmin, _ = interpTrack(track, hr)
        rng, _ = rangeAndBearing(lat2d, lon2d, clat, clon)
        grid = grid - (ENV_PRESSURE - pmin) * np.exp(-(rng / LSCALE_KM) ** 2)
    hlat, hlon, hval = HIGH
    rng, _ = rangeAndBearing(lat2d, lon2d, hlat, hlon)
    grid = grid + (hval - ENV_PRESSURE) * np.exp(-(rng / (1.4 * LSCALE_KM)) ** 2)
    return grid


def landFn(lat2d, lon2d):
    path = Path(COAST + [(LON_MIN - 8, LAT_MAX + 4), (LON_MIN - 8, LAT_MIN - 4)])
    pts = np.column_stack([lon2d.ravel(), lat2d.ravel()])
    return path.contains_points(pts).reshape(lat2d.shape)


# ---------------------------------------------------------------------------
# Run the real procedure over the case
# ---------------------------------------------------------------------------

def runCase(varDict):
    lat2d, lon2d = domainGrids()
    harness._installFakes(CYCLE, windFn=windFn, pmslFn=pmslFn, landFn=landFn,
                          domain=(lat2d, lon2d))
    module = harness.loadProcedureModule()
    os.environ.setdefault("USER", "first.last")
    module.Procedure(None).execute(dict(varDict))
    return module, harness.STORED[-1], lat2d, lon2d


def periodMaxWind(module, lat2d, lon2d, startHr, endHr):
    """The field the procedure contoured, recomputed for background shading."""
    mags = [windFn(hr, lat2d, lon2d)[0]
            for hr in range(startHr, endHr + 1, 6)]
    wind = module.smoothGrid(np.maximum.reduce(mags), module.SMOOTH_PASSES)
    return np.where(landFn(lat2d, lon2d), 0.0, wind)


# ---------------------------------------------------------------------------
# Plot what the XML says
# ---------------------------------------------------------------------------

def xmlLayers(xmlPath):
    """{layer name: {"lines": [...], "lows": [...]}} straight from the file."""
    layers = {}
    for layer in ET.parse(xmlPath).getroot().iter("Layer"):
        lines, lows = [], []
        for line in layer.iter("Line"):
            pts = np.asarray([(float(p.get("Lon")), float(p.get("Lat")))
                              for p in line.iter("Point")])
            lines.append({"points": pts,
                          "color": tuple(int(c.get(k)) / 255.0
                                         for c in line.iter("Color")
                                         for k in ("red", "green", "blue")),
                          "dashed": "DASH" in (line.get("pgenType") or ""),
                          "closed": line.get("closed") == "true",
                          "width": float(line.get("lineWidth"))})
        # Lows carry a pressure label and a forecast-hour text box, written
        # in the same order as the symbols.
        for symbol, label, box in zip(layer.iter("SymbolAttribute"),
                                      layer.iter("TextAttribute"),
                                      layer.iter("TextBox")):
            lows.append({"lon": float(symbol.get("Lon")),
                         "lat": float(symbol.get("Lat")),
                         "value": label.get("text"),
                         "hour": int(box.get("text")[1:])})
        layers[layer.get("name")] = {"lines": lines, "lows": lows}
    return layers


LABELLED_HOURS = (0, 12, 24, 36, 48)


def drawPanel(ax, module, layers, lat2d, lon2d, period, startHr, endHr):
    wind = periodMaxWind(module, lat2d, lon2d, startHr, endHr)

    # Recessive background: the max-wind field the polygons came from.
    ax.contourf(lon2d, lat2d, wind, levels=[20, 34, 48, 64, 120],
                colors=["#eef1f5", "#dfe5ec", "#cdd6e2", "#b9c5d6"], zorder=1)

    # Land, drawn from the same outline used as the Land edit area.
    ax.fill(*zip(*(COAST + [(LON_MIN - 8, LAT_MAX + 4),
                            (LON_MIN - 8, LAT_MIN - 4)])),
            facecolor="#e8e3d9", edgecolor="#9aa3ad", linewidth=0.8, zorder=2)

    # This period's band polygons, exactly as written to the XML.  Bands are
    # told apart inside the layer by color, so count them that way.
    for line in layers.get(period, {}).get("lines", []):
        ring = np.vstack([line["points"], line["points"][:1]])
        ax.plot(ring[:, 0], ring[:, 1], color=line["color"],
                linewidth=line["width"] * 0.7,
                linestyle="--" if line["dashed"] else "-",
                solid_capstyle="round", zorder=4)
    counts = []
    for band, label, _ in module.WIND_BANDS:
        want = tuple(c / 255.0 for c in module.BAND_COLORS[band])
        n = sum(1 for line in layers.get(period, {}).get("lines", [])
                if line["color"] == want)
        if n:
            counts.append("%s kt x%d" % (label, n))

    # The Track layer - the same on both panels, as in D2D with both on.
    for line in layers.get("Track", {}).get("lines", []):
        ax.plot(line["points"][:, 0], line["points"][:, 1],
                color=line["color"], linewidth=1.6, marker="o",
                markersize=2.5, zorder=5, alpha=0.9)

    # The Lows layer, also shared.  Every plot time gets a mark; the 12-hourly
    # ones get the full symbol and label, so the track stays readable.
    for low in layers.get("Lows", {}).get("lows", []):
        lon, lat, hr = low["lon"], low["lat"], low["hour"]
        if hr not in LABELLED_HOURS:
            ax.plot(lon, lat, marker="o", markersize=4.5,
                    markerfacecolor="white", markeredgecolor="#1f4e8c",
                    markeredgewidth=1.0, zorder=6)
            continue
        ax.plot(lon, lat, marker="o", markersize=15, markerfacecolor="white",
                markeredgecolor="#1f4e8c", markeredgewidth=1.6, zorder=6)
        ax.text(lon, lat, "L", ha="center", va="center", fontsize=9,
                fontweight="bold", color="#1f4e8c", zorder=7)
        # Alternate the label above and below, so a slow-moving low's
        # labels do not stack on each other.
        offset = (0, -17) if LABELLED_HOURS.index(hr) % 2 == 0 else (0, 12)
        ax.annotate("%s / F%03d" % (low["value"], hr), (lon, lat),
                    textcoords="offset points", xytext=offset,
                    ha="center", fontsize=7.5, color="#33404f", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                              edgecolor="none", alpha=0.85))

    ax.set_xlim(LON_MIN, LON_MAX)
    ax.set_ylim(LAT_MIN, LAT_MAX)
    ax.set_xticks(range(int(LON_MIN), int(LON_MAX) + 1, 10))
    ax.set_yticks(range(int(LAT_MIN) + 5, int(LAT_MAX) + 1, 5))
    ax.tick_params(labelsize=7.5, colors="#6b7684", length=3)
    ax.grid(True, color="#dfe3e8", linewidth=0.5, zorder=0)
    for spine in ax.spines.values():
        spine.set_color("#c3cad2")
    style = "dashed" if period == "F024-048" else "solid"
    ax.set_title("%s   (%s outline)\n%s" % (period, style, ",  ".join(counts)),
                 fontsize=9.5, color="#1c2530", pad=8)
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out",
                        default=os.path.join(HERE, "out", "synthetic_case.png"))
    parser.add_argument("--color-by", default="Band", choices=["Band", "Period"])
    parser.add_argument("--hatch", action="store_true")
    args = parser.parse_args()

    varDict = {"Cycle:": "18z",
               "Periods:": ["F000-024", "F024-048"],
               "Input Grid:": "Fcst",
               "Color by:": args.color_by,
               "Hatch fill:": "On" if args.hatch else "Off",
               "Mask land:": "On"}

    module, xmlPath, lat2d, lon2d = runCase(varDict)
    layers = xmlLayers(xmlPath)
    print("\nXML: %s" % xmlPath)
    for name, content in layers.items():
        print("  %-12s %d line(s), %d low(s)"
              % (name, len(content["lines"]), len(content["lows"])))

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.6), dpi=140)
    fig.patch.set_facecolor("white")
    drawPanel(axes[0], module, layers, lat2d, lon2d, "F000-024", 0, 24)
    drawPanel(axes[1], module, layers, lat2d, lon2d, "F024-048", 24, 48)

    handles = [Line2D([], [], color=tuple(c / 255.0 for c in
                                          module.BAND_COLORS[band]),
                      linewidth=2.4, label="%s kt" % label)
               for band, label, _ in module.WIND_BANDS]
    handles.append(Line2D([], [], marker="o", markersize=8, linestyle="none",
                          markerfacecolor="white", markeredgecolor="#1f4e8c",
                          label="Low (mb / valid hour)"))
    handles.append(Line2D([], [], color=tuple(c / 255.0
                                              for c in module.TRACK_COLOR),
                          linewidth=1.6, marker="o", markersize=3,
                          label="Track"))
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False,
               fontsize=8.5, bbox_to_anchor=(0.5, 0.005))

    fig.suptitle("CreateXML_WindHazards - synthetic case, 18Z cycle",
                 fontsize=12.5, color="#111820", y=0.975)
    fig.text(0.5, 0.93, "Every polygon and Low is read back out of the PGEN "
             "XML the procedure wrote.  Shading is the period max wind it "
             "contoured; land is the masked edit area.", ha="center",
             fontsize=8, color="#6b7684")
    fig.text(0.5, 0.905, "Vertices are drawn raw - PGEN renders them with "
             "smoothFactor %d, so the scalloping a period maximum leaves "
             "along a fast-moving track comes out smoother.  Synthetic data."
             % module.SMOOTH_FACTOR, ha="center", fontsize=8, color="#6b7684")
    fig.subplots_adjust(left=0.045, right=0.985, top=0.835, bottom=0.085,
                        wspace=0.1)

    if not os.path.isdir(os.path.dirname(args.out)):
        os.makedirs(os.path.dirname(args.out))
    fig.savefig(args.out, facecolor="white")
    print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
