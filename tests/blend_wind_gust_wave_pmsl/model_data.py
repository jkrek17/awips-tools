"""Real GFS / ECMWF open-data grids on a 0.25 deg lat/lon box, cached on disk.

GFS and GFS Wave come from the NOMADS grib filter, cut to the box server-side;
ECMWF and ECMWF wave from the ECMWF open-data server, by byte range from each
step's .index, so only the needed fields are downloaded.  With source "aws"
both come from their AWS open-data mirrors instead (noaa-gfs-bdp-pds and
ecmwf-forecasts), for networks that can reach S3 but not NOMADS or
data.ecmwf.int; GFS is then fetched by byte range from its .idx as well, as
whole-globe fields cut to the box locally.  Each decoded step is cached as
.npz under CACHE.  Call configure() before anything else.
"""
import json, os, re, time, calendar
import numpy as np
import requests
import eccodes

CACHE = None
LATS = LONS = None
NOMADS = "https://nomads.ncep.noaa.gov"
ECMWF = "https://data.ecmwf.int/forecasts"
GFS_AWS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
ECMWF_AWS = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
SOURCE = "direct"
S = requests.Session()

def configure(cache, lat0, lat1, lon0, lon1, source="direct"):
    """Cache directory, box (lon in -180..180, multiples of 0.25) and source
    ("direct": NOMADS and data.ecmwf.int, "aws": their S3 mirrors)."""
    global CACHE, LATS, LONS, SOURCE
    CACHE, SOURCE = cache, source
    os.makedirs(cache, exist_ok=True)
    LATS = np.arange(lat0, lat1 + 0.001, 0.25)
    LONS = np.arange(lon0, lon1 + 0.001, 0.25)


def _get(url, headers=None, tries=6):  # S3 answers an occasional 503 SlowDown
    for i in range(tries):
        try:
            r = S.get(url, headers=headers, timeout=120)
            if r.status_code in (200, 206):
                return r
            if r.status_code in (403, 404):  # NOMADS answers 403 for a cycle not posted yet
                return None
        except requests.RequestException:
            pass
        time.sleep(2 ** (i + 1))
    raise RuntimeError("failed: " + url)

def cycle_unix(ymd, hh):
    return calendar.timegm(time.strptime(ymd + hh, "%Y%m%d%H"))

# ---------------------------------------------------------------- inventories
def _s3_list(bucket, prefix):
    """Keys under prefix, as raw ListObjectsV2 XML (one page is enough here)."""
    return _get("%s/?list-type=2&max-keys=1000&prefix=%s" % (bucket, prefix))

def gfs_hours(ymd, hh, kind):
    if SOURCE == "aws":
        if kind == "atmos":
            r = _s3_list(GFS_AWS, "gfs.%s/%s/atmos/gfs.t%sz.pgrb2.0p25.f" % (ymd, hh, hh))
            pat = r"gfs\.t%sz\.pgrb2\.0p25\.f(\d{3})\.idx" % hh
        else:
            r = _s3_list(GFS_AWS, "gfs.%s/%s/wave/gridded/gfswave.t%sz.global.0p25.f" % (ymd, hh, hh))
            pat = r"gfswave\.t%sz\.global\.0p25\.f(\d{3})\.grib2\.idx" % hh
    elif kind == "atmos":
        r = _get("%s/pub/data/nccf/com/gfs/prod/gfs.%s/%s/atmos/" % (NOMADS, ymd, hh))
        pat = r"gfs\.t%sz\.pgrb2\.0p25\.f(\d{3})\.idx" % hh
    else:
        r = _get("%s/pub/data/nccf/com/gfs/prod/gfs.%s/%s/wave/gridded/" % (NOMADS, ymd, hh))
        pat = r"gfswave\.t%sz\.global\.0p25\.f(\d{3})\.grib2\.idx" % hh
    return sorted({int(h) for h in re.findall(pat, r.text)}) if r is not None else []

def ec_steps(ymd, hh, stream):
    if SOURCE == "aws":
        r = _s3_list(ECMWF_AWS, "%s/%sz/ifs/0p25/%s/" % (ymd, hh, stream))
    else:
        r = _get("%s/%s/%sz/ifs/0p25/%s/" % (ECMWF, ymd, hh, stream))
    pat = r"%s%s0000-(\d+)h-%s-fc\.index" % (ymd, hh, stream)
    return sorted({int(s) for s in re.findall(pat, r.text)}) if r is not None else []

# ---------------------------------------------------------------- decoding
def _decode(blob):
    """GRIB messages -> {shortName: field on LATS x LONS}."""
    out = {}
    pos = 0
    while True:
        start = blob.find(b"GRIB", pos)
        if start < 0:
            break
        length = int.from_bytes(blob[start + 8:start + 16], "big")
        h = eccodes.codes_new_from_message(blob[start:start + length])
        try:
            name = eccodes.codes_get(h, "shortName")
            ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
            vals = eccodes.codes_get_values(h).reshape(nj, ni).astype(float)
            miss = eccodes.codes_get(h, "missingValue")
            if eccodes.codes_get(h, "bitmapPresent"):
                vals[vals == miss] = np.nan
            lats = eccodes.codes_get_array(h, "distinctLatitudes")
            lons = eccodes.codes_get_array(h, "distinctLongitudes")
            lons = np.where(lons > 180, lons - 360, lons)
            iy = [int(np.argmin(np.abs(lats - y))) for y in LATS]
            ix = [int(np.argmin(np.abs(lons - x))) for x in LONS]
            assert np.allclose(lats[iy], LATS) and np.allclose(lons[ix], LONS)
            out[name] = vals[np.ix_(iy, ix)]
        finally:
            eccodes.codes_release(h)
        pos = start + length
    return out

def _cached(key, fetch):
    path = os.path.join(CACHE, key + ".npz")
    if os.path.exists(path):
        return dict(np.load(path))
    fields = _decode(fetch())
    np.savez_compressed(path, **fields)
    return fields

def _gfs_aws(ymd, hh, fhr, kind):
    """The wanted records of one GFS file, by byte range from its .idx."""
    if kind == "atmos":
        url = "%s/gfs.%s/%s/atmos/gfs.t%sz.pgrb2.0p25.f%03d" % (GFS_AWS, ymd, hh, hh, fhr)
        idx_url, want = url + ".idx", ("UGRD:10 m above ground", "VGRD:10 m above ground",
                                       "GUST:surface", "PRMSL:mean sea level")
    else:
        url = "%s/gfs.%s/%s/wave/gridded/gfswave.t%sz.global.0p25.f%03d.grib2" % (GFS_AWS, ymd, hh, hh, fhr)
        idx_url, want = url + ".idx", ("HTSGW:surface",)
    lines = [l.split(":") for l in _get(idx_url).text.splitlines() if l.strip()]
    blob = b""
    for i, f in enumerate(lines):
        if ":".join(f[3:5]) in want:
            end = "%d" % (int(lines[i + 1][1]) - 1) if i + 1 < len(lines) else ""
            blob += _get(url, headers={"Range": "bytes=%s-%s" % (f[1], end)}).content
    return blob

def gfs_fields(ymd, hh, fhr, kind):
    def fetch():
        if SOURCE == "aws":
            return _gfs_aws(ymd, hh, fhr, kind)
        if kind == "atmos":
            q = ("filter_gfs_0p25.pl?dir=%%2Fgfs.%s%%2F%s%%2Fatmos&file=gfs.t%sz.pgrb2.0p25.f%03d"
                 "&var_UGRD=on&var_VGRD=on&var_GUST=on&var_PRMSL=on"
                 "&lev_10_m_above_ground=on&lev_surface=on&lev_mean_sea_level=on" % (ymd, hh, hh, fhr))
        else:
            q = ("filter_gfswave.pl?dir=%%2Fgfs.%s%%2F%s%%2Fwave%%2Fgridded&file=gfswave.t%sz.global.0p25.f%03d.grib2"
                 "&var_HTSGW=on&lev_surface=on" % (ymd, hh, hh, fhr))
        q += "&subregion=&toplat=%g&leftlon=%g&rightlon=%g&bottomlat=%g" % (
            LATS[-1] + 1, (LONS[0] - 1) % 360, (LONS[-1] + 1) % 360, LATS[0] - 1)
        time.sleep(0.6)
        return _get("%s/cgi-bin/%s" % (NOMADS, q)).content
    return _cached("gfs_%s_%s_%s_f%03d_%s" % (kind, ymd, hh, fhr, _box()), fetch)

def ec_fields(ymd, hh, step, stream, params):
    def fetch():
        root = ECMWF_AWS if SOURCE == "aws" else ECMWF
        base = "%s/%s/%sz/ifs/0p25/%s/%s%s0000-%dh-%s-fc" % (root, ymd, hh, stream, ymd, hh, step, stream)
        idx = [json.loads(l) for l in _get(base + ".index").text.splitlines() if l.strip()]
        blob = b""
        for rec in idx:
            if rec["param"] in params and rec.get("levtype") == "sfc":
                a, n = rec["_offset"], rec["_length"]
                blob += _get(base + ".grib2", headers={"Range": "bytes=%d-%d" % (a, a + n - 1)}).content
        return blob
    return _cached("ec_%s_%s_%s_%03d_%s" % (stream, ymd, hh, step, _box()), fetch)


def _box():
    return "%g_%g_%g_%g" % (LATS[0], LATS[-1], LONS[0], LONS[-1])
