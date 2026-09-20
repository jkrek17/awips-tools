#!/usr/bin/env python3
"""Build the full-globe coastline outlines used by the globe view.

Downloads Natural Earth's 110m land polygons (public domain) - every
continent, both hemispheres, since the globe can be rotated freely and a
forecaster spinning south should see land, not a blank sphere - rounds
coordinates for a small payload, and writes:

    docs/data/coastlines.js   window.HF_COAST = { polygons: [...] }

Only outer rings are kept: at 110m resolution the land masses in view have no
donut holes worth the extra points, and the globe draws a filled disc anyway
so an unrendered hole would not read as one.

The script is stdlib-only and idempotent - re-running it re-downloads the
same public source and overwrites the same output with the same result.

Usage:
    python3 tools/build_coastlines.py                # fetch, build, write
    python3 tools/build_coastlines.py --check         # build, but write nothing
    python3 tools/build_coastlines.py --input FILE    # use a local geojson
                                                       # instead of downloading
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
              "master/geojson/ne_110m_land.geojson")

# Coordinates are rounded to this many decimal places. At 110m resolution the
# source data itself is only accurate to ~0.01 deg, so this loses nothing.
ROUND_DIGITS = 2

# A ring this short after clipping and de-duplication cannot enclose an area
# worth drawing; drop it rather than pass a degenerate shape to canvas.
MIN_RING_POINTS = 4


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_source(url: str) -> dict:
    """Download the Natural Earth land geojson. Trusts the environment's CA
    bundle and HTTPS_PROXY the same way every other tool in this session
    does; no special-casing here."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "awips-tools/build_coastlines"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Ring cleanup - no hemisphere clip any more (the globe covers the whole
# world), just rounding, de-duplication and re-closing.
# ---------------------------------------------------------------------------

def round_ring(ring, digits):
    return [[round(lon, digits), round(lat, digits)] for lon, lat in ring]


def dedupe_consecutive(ring):
    out = []
    for pt in ring:
        if not out or out[-1] != pt:
            out.append(pt)
    return out


def close_ring(ring):
    if len(ring) >= 2 and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return ring


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def outer_rings(geometry):
    """Yield each polygon's outer ring (first ring) as a list of [lon, lat]."""
    gtype = geometry.get("type")
    if gtype == "Polygon":
        coords = geometry.get("coordinates") or []
        if coords:
            yield coords[0]
    elif gtype == "MultiPolygon":
        for poly in geometry.get("coordinates") or []:
            if poly:
                yield poly[0]


def build(source: dict):
    polygons = []
    kept, dropped = 0, 0

    for feature in source.get("features", []):
        geometry = feature.get("geometry") or {}
        for ring in outer_rings(geometry):
            if len(ring) < 3:
                dropped += 1
                continue
            closed = close_ring(ring)
            rounded = round_ring(closed, ROUND_DIGITS)
            rounded = dedupe_consecutive(rounded)
            if len(rounded) < MIN_RING_POINTS:
                dropped += 1
                continue
            polygons.append(rounded)
            kept += 1

    return polygons, kept, dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build but write nothing")
    ap.add_argument("--input", metavar="FILE",
                    help="use a local Natural Earth geojson instead of downloading")
    args = ap.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            source = json.load(fh)
    else:
        source = fetch_source(SOURCE_URL)

    polygons, kept, dropped = build(source)
    total_points = sum(len(p) for p in polygons)
    print(f"polygons {kept}  points {total_points}  rings dropped (degenerate) {dropped}")

    if args.check:
        return

    data_dir = os.path.join(ROOT, "docs", "data")
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "coastlines.js")

    compact = json.dumps({"polygons": polygons}, separators=(",", ":"), allow_nan=False)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("/* generated by tools/build_coastlines.py - do not edit */\n")
        fh.write("/* Natural Earth 110m land, public domain. */\n")
        fh.write("window.HF_COAST = " + compact + ";\n")

    size = os.path.getsize(out_path)
    print(f"wrote docs/data/coastlines.js ({size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
