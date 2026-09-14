#!/usr/bin/env python3
"""Build the northern-hemisphere coastline outlines used by the globe view.

Downloads Natural Earth's 110m land polygons (public domain), clips them to
the hemisphere the archive actually needs - the Arctic, North America,
Europe and Asia, where both basins' tracks live - rounds coordinates for a
small payload, and writes:

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

# Everything south of this latitude is clipped away: Africa, South America,
# Australia and Antarctica play no part in a North Atlantic / North Pacific
# extratropical low archive, and dropping them is most of the size saving.
MIN_LAT = 0.0

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
# Clipping - Sutherland-Hodgman against the half-plane lat >= MIN_LAT
# ---------------------------------------------------------------------------

def clip_ring_to_min_lat(ring, min_lat):
    """Clip a closed [lon, lat] ring to the half-plane lat >= min_lat.

    Standard Sutherland-Hodgman against a single straight edge. This clips on
    latitude only, so it does not care whether the ring's longitudes wrap the
    antimeridian - each vertex is judged solely on its latitude, and an
    interpolated crossing point keeps whatever longitude the edge implies at
    that latitude. The globe view projects each point independently onto a
    sphere, so a ring that spans -180/180 in longitude still draws correctly
    with no antimeridian splitting needed (unlike a flat map).
    """
    if not ring:
        return []

    def inside(pt):
        return pt[1] >= min_lat

    def intersect(a, b):
        # Point where segment a->b crosses lat == min_lat.
        if b[1] == a[1]:
            return b
        t = (min_lat - a[1]) / (b[1] - a[1])
        lon = a[0] + t * (b[0] - a[0])
        return [lon, min_lat]

    out = []
    n = len(ring)
    for i in range(n):
        cur = ring[i]
        prev = ring[i - 1]          # ring[-1] == ring[0] wrap on i == 0 is fine here
        cur_in, prev_in = inside(cur), inside(prev)
        if cur_in:
            if not prev_in:
                out.append(intersect(prev, cur))
            out.append(cur)
        elif prev_in:
            out.append(intersect(prev, cur))
    return out


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
            clipped = clip_ring_to_min_lat(ring, MIN_LAT)
            if len(clipped) < 3:
                dropped += 1
                continue
            clipped = close_ring(clipped)
            rounded = round_ring(clipped, ROUND_DIGITS)
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
