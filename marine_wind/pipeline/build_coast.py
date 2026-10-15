#!/usr/bin/env python3
"""Write the page's land from Natural Earth 50m land (public domain), outer rings only,
rounded to 0.01 degree, as one GeoJSON MultiPolygon for the whole globe:
    page/land.json

    python3 marine_wind/pipeline/build_coast.py
"""
import json
import os
import urllib.request

SRC = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson"
PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "page")
OUT = os.path.join(PAGE, "land.json")


def main():
    with urllib.request.urlopen(SRC, timeout=120) as r:
        gj = json.load(r)
    polys = []
    for f in gj["features"]:
        g = f["geometry"]
        for p in g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]:
            out = []
            for x, y in p[0]:
                pt = [round(x, 2), round(y, 2)]
                if not out or out[-1] != pt:
                    out.append(pt)
            if len(out) >= 4:
                if out[0] != out[-1]:
                    out.append(out[0])
                polys.append([out])
    land = {"type": "Feature", "properties": {"source": "Natural Earth 50m land, public domain"},
            "geometry": {"type": "MultiPolygon", "coordinates": polys}}
    with open(OUT, "w") as f:
        json.dump(land, f, separators=(",", ":"))
    print(len(polys), "rings ->", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
