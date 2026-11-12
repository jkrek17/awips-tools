"""KNMI / OSI SAF Metop-C ASCAT 25 km Level 2 ocean surface winds, near real time, from NASA PO.DAAC (collection
ASCATC-L2-25km, provider POCLOUD). One netCDF file per orbit (about 100 minutes, 1 MB), listed about 2.5-4 hours after the
orbit starts. Full swaths over the open ocean.

    granules(start, end, short_name="ASCATC-L2-25km") -> [dict(title, start, end, url, size_mb)], newest first
        NASA CMR search (public, no login). start and end are UTC datetimes; granules overlapping them are listed.
    credentials() -> (user, password) from env EARTHDATA_USER / EARTHDATA_PASS, or None
    session(user, password) -> requests session whose login survives the redirect to urs.earthdata.nasa.gov
    download(url, sess) -> bytes of the file (retries; raises AuthError when the login is refused)
    cells(path_or_bytes, day=None) -> dict of cell arrays (the shape of rss_ascat.day)
        lat, lon (-180..180)   cell centres (25 km spacing, irregular)
        spd_kt                 wind speed, knots (wind_speed, m/s x 1.943844; KNMI's stress-equivalent 10 m wind)
        dir_deg                meteorological direction, the wind blows FROM
        t_min                  float32 minutes after 00 UTC of `day` (default: the UTC day of the earliest valid cell);
                               absolute cell time from `time`, seconds since 1990-01-01, so it can pass 1440
        rain                   uint8, 1 = rain_detected (wvc_quality_flag bit 512)
        node                   uint8, 0 ascending (latitude rising along track), 1 descending

Product facts, from the OSI SAF ASCAT Wind Product User Manual v1.17 (SAF/OSI/CDOP/KNMI/TEC/MA/126, appendix B,
https://scatterometer.knmi.nl/publications/pdf/ASCAT_Product_Manual.pdf), and the PO.DAAC collection record (netCDF
version 3, one full orbit, latency about 2 h):
  - variables time, lat, lon (int, scaled), wind_speed (m s-1), wind_dir (degree), wvc_quality_flag (int bit flags),
    model_speed, model_dir; dimensions NUMROWS (along track) x NUMCELLS (42 across track). lon is 0..360.
  - "In the NetCDF products, the wind direction is in oceanographic convention: 0 degrees corresponds to a wind flowing
    to the North with a clockwise increment" (manual 5.1.2; file comment "All wind directions in oceanographic convention
    (0 deg. flowing North)"). So the wind blows TOWARD wind_dir and dir_deg here is (wind_dir + 180) % 360. If a file's
    wind_dir says standard_name wind_from_direction (or its comments say meteorological), it is taken as FROM.
  - wvc_quality_flag bits (flag_masks): 64 distance to GMF too large, 128 data redundant, 256 no meteorological
    background, 512 rain detected, 1024 rain flag not usable, 2048 wind <= 3 m/s, 4096 wind > 30 m/s, 8192 inversion not
    successful, 16384 ice, 32768 land, 65536 variational QC fails, 131072 KNMI QC fails, 262144 product monitoring event,
    524288 product monitoring not used, 1048576 beam noise, 2097152 poor azimuth diversity, 4194304 not enough sigma-0.
    Cells with any of DROP are left out; 262144 counts only when 524288 is clear (the file is monitored). 4096 (strong
    wind) and 2048 (light wind) are kept: they are not errors. Cells with rain_detected stay, with rain = 1.

Reader: netCDF4 (reads the version 3 file from memory or a path; scaling and fill values are applied by the library).
The first run on real data is in GitHub Actions (this module has no credentials of its own), so
`cells` raises a clear error for anything that is not a netCDF file and `download` checks the first bytes."""
from __future__ import annotations

import datetime as dt
import os
import time
from urllib.parse import urlparse

import numpy as np
import requests

from .http import get

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
SHORT_NAME = "ASCATC-L2-25km"
AUTH_HOST = "urs.earthdata.nasa.gov"
KT = 1.943844                  # m/s to knots
EPOCH = dt.datetime(1990, 1, 1)
DROP = 8192 | 16384 | 32768 | 65536 | 131072 | 1048576 | 2097152 | 4194304
MONITOR_EVENT, MONITOR_UNUSED = 262144, 524288
RAIN = 512
PAGE = 100


class AuthError(RuntimeError):
    """Earthdata refused the login (401/403 at the end of the redirect chain, or a login page instead of the file)."""


def _parse(s):
    return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def granules(start, end, short_name=SHORT_NAME, fetch=None):
    """Granules overlapping [start, end] (naive UTC datetimes) -> [dict(title, start, end, url, size_mb)], newest first.
    `fetch(url)` -> response with .json() (default nwp.http.get, 3 tries); CMR is public."""
    fetch = fetch or (lambda u: get(u, tries=3))
    out, page = [], 1
    while page <= 20:
        q = "%s?short_name=%s&provider=POCLOUD&sort_key=-start_date&temporal=%s,%s&page_size=%d&page_num=%d" % (
            CMR, short_name, start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ"), PAGE, page)
        r = fetch(q)
        if r is None:
            raise RuntimeError("CMR search refused")
        entries = r.json()["feed"]["entry"]
        for e in entries:
            href = next((l["href"] for l in e.get("links", [])
                         if l.get("href", "").endswith(".nc") and l.get("href", "").startswith("https://") and "data#" in l.get("rel", "")), None)
            if href is None:
                continue
            out.append(dict(title=e["title"], start=_parse(e["time_start"]), end=_parse(e["time_end"]), url=href,
                            size_mb=float(e.get("granule_size", 0) or 0)))
        if len(entries) < PAGE:
            break
        page += 1
    return sorted(out, key=lambda g: g["start"], reverse=True)


def credentials(env=None):
    """(user, password) from EARTHDATA_USER and EARTHDATA_PASS, or None when either is missing or empty."""
    env = os.environ if env is None else env
    u, p = env.get("EARTHDATA_USER", "").strip(), env.get("EARTHDATA_PASS", "").strip("\r\n")
    return (u, p) if u and p else None


TOKEN_URL = "https://urs.earthdata.nasa.gov/api/users/find_or_create_token"


def token(user, password, post=None):
    """An Earthdata bearer token (NASA's token API, basic auth) -> str. A refusal raises AuthError carrying NASA's own
    error text (for example "Invalid user credentials" or an unaccepted EULA), never the credentials."""
    post = post or requests.post
    r = post(TOKEN_URL, auth=(user, password), timeout=60)
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code == 200 and j.get("access_token"):
        return j["access_token"]
    raise AuthError("token API HTTP %d: %s" % (r.status_code, j.get("error_description") or j.get("error") or "no reason given"))


class EarthdataSession(requests.Session):
    """Keeps the Authorization header only for urs.earthdata.nasa.gov and for requests that come back from it: PO.DAAC
    redirects to the login host, which answers with basic auth, then redirects back with a cookie (NASA's documented
    pattern). Other redirects (for example to a CDN) lose it."""

    def __init__(self, user, password, bearer=None):
        super().__init__()
        self.auth = (user, password) if user else None
        self.bearer = bearer

    def request(self, method, url, **kw):
        # With a token: send it as a bearer header to PO.DAAC itself (no login redirect), basic auth not used.
        if self.bearer and urlparse(url).hostname == DATA_HOST:
            kw.setdefault("headers", {})["Authorization"] = "Bearer " + self.bearer
            kw["auth"] = None
            saved, self.auth = self.auth, None
            try:
                return super().request(method, url, **kw)
            finally:
                self.auth = saved
        return super().request(method, url, **kw)

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        if "Authorization" in headers:
            before = urlparse(response.request.url).hostname
            after = urlparse(prepared_request.url).hostname
            if before != after and AUTH_HOST not in (before, after):
                del headers["Authorization"]


DATA_HOST = "archive.podaac.earthdata.nasa.gov"


def session(user, password, get_token=None):
    """A session for PO.DAAC downloads: with a bearer token from NASA's token API when it gives one (the most reliable
    route), else basic auth through the login redirect. A token refusal is raised (AuthError) so the log says why."""
    tok = (get_token or token)(user, password)
    return EarthdataSession(user, password, bearer=tok)


def _is_netcdf(b):
    return b[:3] == b"CDF" or b[:4] == b"\x89HDF"


def download(url, sess, tries=3, pause=5.0):
    """The file at url -> bytes, through an EarthdataSession. 401/403 raise AuthError at once (no retry: a wrong login would
    be tried again and again); other failures retry; a body that is not netCDF (a login page) raises AuthError too.
    Nothing here prints the credentials or the headers."""
    last = None
    for k in range(tries):
        try:
            r = sess.get(url, timeout=180)
        except requests.RequestException as e:
            last = type(e).__name__
        else:
            if r.status_code in (401, 403):
                raise AuthError("HTTP %d from %s" % (r.status_code, urlparse(r.url).hostname))
            if r.status_code == 200:
                if _is_netcdf(r.content[:8]):
                    return r.content
                raise AuthError("answer is not netCDF (content-type %s, host %s): login not accepted"
                                % (r.headers.get("content-type", "?"), urlparse(r.url).hostname))
            last = "HTTP %d" % r.status_code
        time.sleep(pause * (k + 1))
    raise RuntimeError("download failed (%s): %s" % (last, os.path.basename(urlparse(url).path)))


# ---------- reading ----------

def _open(src):
    """(get(name) -> (masked array, attrs dict), global attrs, close) for a path or bytes."""
    import netCDF4   # pip install netCDF4 (marine_wind/scat/requirements.txt)
    ds = netCDF4.Dataset("mem.nc", memory=bytes(src)) if isinstance(src, (bytes, bytearray)) else netCDF4.Dataset(src)

    def var(name):
        v = ds.variables[name]
        return v[:], {a: v.getncattr(a) for a in v.ncattrs()}
    return var, {a: ds.getncattr(a) for a in ds.ncattrs()}, ds.close


def wind_is_from(attrs, gattrs):
    """Does the file's wind_dir say the wind blows FROM that direction? Default no: the KNMI netCDF is oceanographic (TOWARD)."""
    sn = str(attrs.get("standard_name", "")).lower()
    if "from" in sn:
        return True
    if "to_direction" in sn:
        return False
    text = (str(attrs.get("comment", "")) + str(attrs.get("long_name", "")) + str(gattrs.get("comment", ""))).lower()
    return "meteorological" in text and "oceanographic" not in text


def _f(a):
    return np.ma.filled(np.ma.asarray(a).astype(np.float64), np.nan)


def cells(src, day=None):
    """A KNMI ASCAT 25 km L2 netCDF (path or bytes) -> the valid, QC-passed cells of the orbit (module doc)."""
    if isinstance(src, (bytes, bytearray)) and not _is_netcdf(bytes(src[:8])):
        raise ValueError("not a netCDF file")
    var, gattrs, close = _open(src)
    try:
        lat, _ = var("lat")
        lon, _ = var("lon")
        tm, _ = var("time")
        ws, _ = var("wind_speed")
        wd, dattrs = var("wind_dir")
        try:
            fl, _ = var("wvc_quality_flag")
        except KeyError:
            fl = None
    finally:
        close()
    lat, lon, tm, ws, wd = (_f(x) for x in (lat, lon, tm, ws, wd))
    flag = np.zeros(lat.shape, np.int64) if fl is None else np.ma.filled(np.ma.asarray(fl), 0).astype(np.int64)
    ok = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(tm) & np.isfinite(ws) & np.isfinite(wd) & (ws >= 0) & (ws < 100)
    ok &= (flag & DROP) == 0
    ok &= ~(((flag & MONITOR_EVENT) != 0) & ((flag & MONITOR_UNUSED) == 0))
    rowlat = np.nanmean(np.where(np.isfinite(lat), lat, np.nan), axis=1) if lat.ndim == 2 else lat
    slope = np.gradient(np.nan_to_num(rowlat)) if rowlat.size > 1 else np.zeros(rowlat.shape)
    node = np.broadcast_to((slope < 0).astype(np.uint8)[:, None], lat.shape) if lat.ndim == 2 else (slope < 0).astype(np.uint8)
    secs = tm[ok]
    if day is None:
        first = EPOCH + dt.timedelta(seconds=float(secs.min())) if secs.size else dt.datetime(1990, 1, 1)
        day = dt.datetime(first.year, first.month, first.day)
    base = (dt.datetime(day.year, day.month, day.day) - EPOCH).total_seconds()
    from_deg = wd[ok] % 360 if wind_is_from(dattrs, gattrs) else (wd[ok] + 180.0) % 360
    return dict(lat=lat[ok].astype(np.float32), lon=(((lon[ok] + 180) % 360) - 180).astype(np.float32),
                spd_kt=(ws[ok] * KT).astype(np.float32), dir_deg=from_deg.astype(np.float32),
                t_min=((secs - base) / 60.0).astype(np.float32), rain=((flag[ok] & RAIN) != 0).astype(np.uint8),
                node=np.asarray(node)[ok].astype(np.uint8))
