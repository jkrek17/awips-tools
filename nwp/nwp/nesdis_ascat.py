"""NESDIS Metop-B ASCAT, near real time (about 1 hour after the pass): the 0.25 degree daily wind maps NOAA AOML serves
from its THREDDS server (https://cwcgom.aoml.noaa.gov/thredds/dodsC/ASCAT/METOPB.nc), read through NOAA's ERDDAP
(dataset noaa_aoml_8c7c_16cc_8cde). Full swaths over the open ocean. Metop-C is not served there.

    day(date, box) -> dict of cell arrays (the same shape as rss_ascat.day), or None when the day is not there yet
        box = (south, north, west, east) degrees; west and east may run past 180 (the OPC Pacific box is 135 to 245):
        the request is split at the date line, one ERDDAP request per piece, a few MB of csv each.
        lat, lon (-180..180)   cell centres, x.125 degrees (lat ascending, 0.25 degree grid)
        spd_kt                 wind speed, knots (WSPD, the 10 m neutral wind in m/s x 1.94384)
        dir_deg                meteorological direction, the wind blows FROM (from the uwnd, vwnd components, which point
                               the way the wind blows: from = atan2(-u, -v); checked against RSS Metop-B)
        t_min                  minutes after 00 UTC of the day (the server's "hour" variable is seconds after 00 UTC,
                               steps of 128 s; checked against RSS cell times: median difference under 2 minutes)
        rain                   uint8, the rain flag (1 = rain)
        node                   uint8, 0 ascending pass, 1 descending pass
The dataset has one time step per UTC day, stamped T12:00:00Z, that grows as passes arrive (the day's newest cells are
about an hour old). A day not in the dataset yet answers 404 and gives None. A day with no cell in the box gives empty
arrays. Compared with RSS Metop-B on 7 Nov 2026 (46,000 cells, same pass): speed bias 0.0 kt, SD 1.0 kt, r 0.99; direction
mean absolute difference 7 degrees. (RSS's own node numbers are the other way round: its node 0 is NESDIS's descending
pass.)

csv rather than netCDF: nothing in the requirements reads netCDF. NaN marks no data."""
from __future__ import annotations

import io
import urllib.parse

import numpy as np

from .http import get

ERDDAP = "https://upwell.pfeg.noaa.gov/erddap/griddap/noaa_aoml_8c7c_16cc_8cde.csv"
KT = 1.94384                   # m/s to knots
VARS = ("WSPD", "uwnd", "vwnd", "Rain_Flag", "Time")
NODES = ("Ascending", "Descending")
TRIES = 3                      # ERDDAP answers 404 for a day it does not have; anything else is retried this often


def query(date, south, north, west, east):
    """The ERDDAP constraint string for one piece of the box (west, east within -180..180)."""
    stamp = "%04d-%02d-%02dT12:00:00Z" % (date.year, date.month, date.day)
    return ",".join("%s_%s[(%s)][(%g):1:(%g)][(%g):1:(%g)]" % (v, n, stamp, south, north, west, east)
                    for v in VARS for n in NODES)


def pieces(west, east):
    """(west, east) in degrees, east up to west + 360 -> [(west, east)] within -180..180, split at the date line."""
    if east - west >= 360:
        return [(-180.0, 180.0)]
    w, e = (west + 180) % 360 - 180, (east + 180) % 360 - 180
    return [(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]


def url(date, south, north, west, east):
    return ERDDAP + "?" + urllib.parse.quote(query(date, south, north, west, east), safe=",=:()")


def cells(text):
    """The csv text of one request -> the valid cells of both passes (module doc)."""
    a = np.loadtxt(io.StringIO(text), delimiter=",", skiprows=2, usecols=range(1, 13), ndmin=2)
    lat, lon = a[:, 0], a[:, 1]
    parts = []
    for p in range(2):
        spd, u, v, rain, t = (a[:, 2 + 2 * i + p] for i in range(5))
        k = ~(np.isnan(spd) | np.isnan(u) | np.isnan(v) | np.isnan(t))
        parts.append(dict(
            lat=lat[k].astype(np.float32), lon=lon[k].astype(np.float32),
            spd_kt=(spd[k] * KT).astype(np.float32),
            dir_deg=(np.degrees(np.arctan2(-u[k], -v[k])) % 360).astype(np.float32),
            t_min=np.round(t[k] / 60).astype(np.int16),
            rain=(rain[k] == 1).astype(np.uint8),
            node=np.full(int(k.sum()), p, np.uint8)))
    return {k: np.concatenate([q[k] for q in parts]) for k in parts[0]}


def day(date, box):
    """The valid cells of a UTC day (date or datetime) inside box (module doc) -> dict; None when the day is not there."""
    south, north, west, east = box
    got = []
    for w, e in pieces(west, east):
        r = get(url(date, south, north, w, e), tries=TRIES)
        if r is None:
            return None
        got.append(cells(r.text))
    return {k: np.concatenate([g[k] for g in got]) for k in got[0]}
