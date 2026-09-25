"""Build the self-hosted Natural Earth basemap for the live CPS map.

Writes small GeoJSON files next to this script from the Natural Earth
shapefiles in the cartopy cache (cartopy downloads any that are missing):

    land_110m.json   land polygons, simplified 0.2 deg (zoom 3 and below)
    land_50m.json    land polygons, simplified 0.05 deg (zoom 4 and up)
    coast_50m.json   coastlines, simplified 0.05 deg
    borders_50m.json land boundaries between countries, simplified 0.05 deg
    lakes_50m.json   lakes larger than about 1 square degree, simplified 0.05 deg

Coordinates are rounded to 2 decimals. Run from anywhere:

    python3 cyclone_phase_space/article/live/basemap/build_basemap.py
"""
import json
import os

import cartopy.io.shapereader as shpreader
import numpy as np
import shapely
from shapely.geometry import mapping

HERE = os.path.dirname(os.path.abspath(__file__))

# (output name, resolution, category, layer, tolerance, minimum area in deg^2)
LAYERS = [
    ('land_110m', '110m', 'physical', 'land', 0.2, 0.0),
    ('land_50m', '50m', 'physical', 'land', 0.05, 0.0),
    ('coast_50m', '50m', 'physical', 'coastline', 0.05, 0.0),
    ('borders_50m', '50m', 'cultural', 'admin_0_boundary_lines_land', 0.05, 0.0),
    ('lakes_50m', '50m', 'physical', 'lakes', 0.05, 1.0),
]


def clean(coords):
    """Round to 2 decimals and drop repeated points."""
    out = []
    for x, y in coords:
        p = [round(x, 2), round(y, 2)]
        if not out or p != out[-1]:
            out.append(p)
    return out


def rings(geom):
    """Yield cleaned coordinate lists for a line or polygon geometry."""
    if geom.geom_type == 'Polygon':
        poly = [clean(r.coords) for r in [geom.exterior, *geom.interiors]]
        poly = [r for r in poly if len(r) >= 4]
        if poly:
            yield 'Polygon', poly
    elif geom.geom_type == 'LineString':
        line = clean(geom.coords)
        if len(line) >= 2:
            yield 'LineString', line
    else:
        for part in getattr(geom, 'geoms', []):
            yield from rings(part)


def build(name, res, cat, layer, tol, min_area):
    path = shpreader.natural_earth(resolution=res, category=cat, name=layer)
    polys, lines = [], []
    for geom in shpreader.Reader(path).geometries():
        if min_area and geom.area < min_area:
            continue
        geom = shapely.simplify(geom, tol, preserve_topology=True)
        for kind, coords in rings(geom):
            (polys if kind == 'Polygon' else lines).append(coords)
    if polys:
        geometry = {'type': 'MultiPolygon', 'coordinates': polys}
    else:
        geometry = {'type': 'MultiLineString', 'coordinates': lines}
    fc = {'type': 'FeatureCollection',
          'features': [{'type': 'Feature', 'properties': {}, 'geometry': geometry}]}
    out = os.path.join(HERE, f'{name}.json')
    with open(out, 'w') as f:
        json.dump(fc, f, separators=(',', ':'))
    print(f'{name}: {len(polys) or len(lines)} parts, {os.path.getsize(out) / 1024:.0f} KB')


if __name__ == '__main__':
    for spec in LAYERS:
        build(*spec)
