"""High Seas Forecast areas and small grid helpers that need no extra libraries.

AREAS holds each forecast area's outline as (lon, lat) points, longitudes 0-360 east
(the Pacific runs across the date line).
"""
import numpy as np

AREAS = {
    # FZPN01 HSFEP1: 30N-67N, east of a line 30N160E-50N160E-65N170W-67N170W, to 110W
    "pac": [(160, 30), (160, 50), (190, 65), (190, 67), (250, 67), (250, 30)],
    # FZNT01 HSFAT1: "NORTH OF 31N TO 67N AND WEST OF 35W" to the coast. The west edge only
    # keeps out inland water the wave grid carries (Great Lakes, Hudson Bay); the sea mask
    # does the coast. 75W from 37N to 46N, then 71W north of 46N (Gulf of St Lawrence and
    # Ungava Bay in, Hudson Bay and Lake Ontario out)
    "atl": [(278, 31), (278, 37), (285, 37), (285, 46), (289, 46), (289, 67), (325, 67), (325, 31)],
}


def inside(poly, lon, lat):
    """Even-odd point-in-polygon test on arrays of lon (0-360) and lat."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    out = np.zeros(np.broadcast(lon, lat).shape, bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if y1 == y2:
            continue
        cross = ((y1 > lat) != (y2 > lat)) & (lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1))
        out ^= cross
    return out


def outline(mask, lats, lons):
    """Outlines of a cell mask as closed rings of [lon, lat] cell corners (pixel-exact,
    straight runs merged). lats, lons: cell centres of a regular grid."""
    mask = np.asarray(mask, bool)
    ny, nx = mask.shape
    dy, dx = lats[1] - lats[0], lons[1] - lons[0]
    m = np.pad(mask, 1)
    nxt = {}   # corner -> list of next corners (two where cells touch only at a corner)
    # directed edges with the inside on the left, between corner points (row, col)
    for r, c in zip(*np.nonzero(m[1:-1, 1:-1])):
        R, C = r + 1, c + 1
        if not m[R - 1, C]:
            nxt.setdefault((r, c + 1), []).append((r, c))
        if not m[R + 1, C]:
            nxt.setdefault((r + 1, c), []).append((r + 1, c + 1))
        if not m[R, C - 1]:
            nxt.setdefault((r, c), []).append((r + 1, c))
        if not m[R, C + 1]:
            nxt.setdefault((r + 1, c + 1), []).append((r, c + 1))
    rings = []
    def take(k):
        v = nxt[k].pop()
        if not nxt[k]:
            del nxt[k]
        return v
    while nxt:
        start = next(iter(nxt))
        ring, p = [start], take(start)
        while p != start and p in nxt:
            ring.append(p)
            p = take(p)
        pts = [ring[i] for i in range(len(ring))
               if (ring[i - 1][0] - ring[i][0], ring[i - 1][1] - ring[i][1])
               != (ring[i][0] - ring[(i + 1) % len(ring)][0], ring[i][1] - ring[(i + 1) % len(ring)][1])]
        pts.append(pts[0])
        rings.append([[round(float(lons[0] + (c - 0.5) * dx), 3), round(float(lats[0] + (r - 0.5) * dy), 3)] for r, c in pts])
    return rings

