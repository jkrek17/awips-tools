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

csv rather than netCDF: nothing in the requirements reads netCDF. NaN marks no data.

Two routes to the same file: ERDDAP first; if ERDDAP refuses (403, as it may for some cloud addresses) or fails, the
source THREDDS server's OPeNDAP ASCII answer (same grid: lat -89.875 + 0.25 i, lon -179.875 + 0.25 j, one time step per
day). `day` prints which route served it when ERDDAP did not."""
from __future__ import annotations

import datetime as dt
import io
import urllib.parse

import numpy as np

from .http import get, _session

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


THREDDS = "https://cwcgom.aoml.noaa.gov/thredds/dodsC/ASCAT/METOPB.nc"
_times = None


def _status(u):
    """HTTP status of a GET (for the log), or the exception name."""
    try:
        return _session.get(u, timeout=60).status_code
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def time_index(date, times):
    """Index of the day's time step (stamped 12 UTC, seconds since 1970) in times, or None."""
    t = (dt.datetime(date.year, date.month, date.day, 12, tzinfo=dt.timezone.utc).timestamp())
    k = np.nonzero(np.abs(np.asarray(times) - t) < 3600)[0]
    return int(k[0]) if k.size else None


def parse_ascii(text):
    """OPeNDAP ASCII answer -> {name: 2-d array} for each grid array (time dimension of 1 dropped)."""
    out, name, rows = {}, None, []
    for line in text.splitlines():
        line = line.strip()
        if "." in line and line.endswith("]") and line.split("[")[0].count(".") == 1 and not line.startswith("["):
            a, b = line.split("[")[0].split(".")
            if name and rows:
                out[name] = np.array(rows, float)
            name, rows = (a if a == b else None), []
        elif line.startswith("[") and name:
            rows.append([float(x) for x in line.split(",")[1:]])
        elif not line and name and rows:
            out[name] = np.array(rows, float)
            name, rows = None, []
    if name and rows:
        out[name] = np.array(rows, float)
    return out


def ascii_url(k, south, north, west, east):
    i0, i1 = int(round((south + 89.875) / 0.25)), int(round((north + 89.875) / 0.25))
    j0, j1 = int(round((west + 179.875) / 0.25)), int(round((east + 179.875) / 0.25))
    i0, j0, i1, j1 = max(i0, 0), max(j0, 0), min(i1, 719), min(j1, 1439)
    q = ",".join("%s_%s[%d][%d:1:%d][%d:1:%d]" % (v, n, k, i0, i1, j0, j1) for v in VARS for n in NODES)
    return THREDDS + ".ascii?" + urllib.parse.quote(q, safe=",=:"), (i0, i1, j0, j1)


def thredds_cells(date, south, north, west, east):
    """The same cells as `cells`, read from the THREDDS server; None when the day is not there."""
    global _times
    if _times is None:
        r = get(THREDDS + ".ascii?time", tries=TRIES)
        if r is None:
            return None
        _times = [float(x) for x in r.text.split("time[")[-1].split("\n", 1)[1].replace("\n", ",").split(",") if x.strip()]
    k = time_index(date, _times)
    if k is None:
        return None
    u, (i0, i1, j0, j1) = ascii_url(k, south, north, west, east)
    r = get(u, tries=TRIES)
    if r is None:
        return None
    g = parse_ascii(r.text)
    lat = -89.875 + 0.25 * np.arange(i0, i1 + 1)
    lon = -179.875 + 0.25 * np.arange(j0, j1 + 1)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    cols = [la.ravel(), lo.ravel()] + [g["%s_%s" % (v, n)].ravel() for v in VARS for n in NODES]
    a = np.column_stack(cols)
    a[a <= -999] = np.nan
    buf = io.StringIO()
    buf.write("h\nu\n")
    np.savetxt(buf, np.column_stack([np.zeros(len(a)), a]), delimiter=",", fmt="%.6g")
    return cells(buf.getvalue())


def day(date, box):
    """The valid cells of a UTC day (date or datetime) inside box (module doc) -> dict; None when the day is not there."""
    south, north, west, east = box
    got = []
    for w, e in pieces(west, east):
        u = url(date, south, north, w, e)
        try:
            r = get(u, tries=TRIES)
        except RuntimeError:
            r = None
        if r is not None:
            got.append(cells(r.text))
            continue
        c = thredds_cells(date, south, north, w, e)
        print("NESDIS %s: ERDDAP answered %s; THREDDS %s" % (date, _status(u), "used" if c is not None else "has no such day"),
              flush=True)
        if c is None:
            return None
        got.append(c)
    return {k: np.concatenate([g[k] for g in got]) for k in got[0]}
