"""Byte-range fetch of 10 m wind and MSLP from the AWS open-data mirrors.

Only the needed GRIB records are downloaded (from the .idx / .index files) and
each is decoded straight to the page's domain, so a full run (3 models plus
82 ensemble members at 10 lead times) streams about 1.5 GB and keeps a few MB.

Sources (all public, no account):
    GFS        noaa-gfs-bdp-pds   gfs.YYYYMMDD/HH/atmos/gfs.tHHz.pgrb2.0p25.fFFF
    GEFS       noaa-gefs-pds      gefs.YYYYMMDD/HH/atmos/pgrb2sp25/geMMM.tHHz.pgrb2s.0p25.fFFF
    ECMWF IFS, AIFS and ENS       ecmwf-forecasts YYYYMMDD/HHz/{ifs,aifs-single}/0p25/{oper,enfo}/
"""
from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor

import eccodes
import numpy as np
import requests

from domain import IX, IY

GFS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
GEFS = "https://noaa-gefs-pds.s3.amazonaws.com"
EC = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
GEFS_MEMBERS = ["c00"] + ["p%02d" % i for i in range(1, 31)]

_session = requests.Session()


def get(url, rng=None, tries=8):
    """GET (optionally a byte range); None on 403/404. S3 answers 503 SlowDown
    when a freshly posted file gets many range requests at once (everyone is
    pulling the new run), so 503 is retried quickly and often; anything else
    backs off exponentially."""
    headers = {"Range": "bytes=%d-%s" % (rng[0], "" if rng[1] is None else rng[1])} if rng else None
    fails = slow = 0
    while fails < tries and slow < 60:
        try:
            r = _session.get(url, headers=headers, timeout=180)
            if r.status_code in (200, 206):
                return r
            if r.status_code in (403, 404):
                return None
            if r.status_code == 503:
                slow += 1
                time.sleep(0.5 + 1.5 * random.random())
                continue
        except requests.RequestException:
            pass
        fails += 1
        time.sleep(min(2 ** fails, 60) * (0.5 + random.random()))
    raise RuntimeError("failed: " + url)


def exists(url):
    try:
        return _session.head(url, timeout=60).status_code == 200
    except requests.RequestException:
        return False


def decode(blob):
    """One GRIB2 message -> the domain crop, north-up, lon 0..360 order."""
    h = eccodes.codes_new_from_message(blob)
    try:
        ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
        v = eccodes.codes_get_values(h).reshape(nj, ni).astype(np.float32)
        lat0 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
        lon0 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
    finally:
        eccodes.codes_release(h)
    if lat0 < 0:
        v = v[::-1]
    if lon0 > 100:  # ECMWF open data starts at -180 (stored as 180)
        v = np.roll(v, ni // 2, axis=1)
    return v[IY, IX].copy()


def _ncep(url, want):
    """want: {'UGRD:10 m above ground': 'u', ...} -> {'u': array, ...} or None."""
    r = get(url + ".idx")
    if r is None:
        return None
    lines = [l.split(":") for l in r.text.splitlines() if l.strip()]
    idx = {}
    for i, f in enumerate(lines):
        end = int(lines[i + 1][1]) - 1 if i + 1 < len(lines) else None
        idx.setdefault(f[3] + ":" + f[4], (int(f[1]), end))
    out = {}
    for key, name in want.items():
        if key not in idx:
            if name == "msl" and "MSLET:mean sea level" in idx:
                key = "MSLET:mean sea level"
            else:
                return None
        out[name] = decode(get(url, idx[key]).content)
    return out


UV = {"UGRD:10 m above ground": "u", "VGRD:10 m above ground": "v"}
UVP = dict(UV, **{"PRMSL:mean sea level": "msl"})


def gfs_url(ymd, hh, fh):
    return "%s/gfs.%s/%s/atmos/gfs.t%sz.pgrb2.0p25.f%03d" % (GFS, ymd, hh, hh, fh)


def gfs(ymd, hh, fh):
    return _ncep(gfs_url(ymd, hh, fh), UVP)


def gefs(ymd, hh, fh, mem):
    url = "%s/gefs.%s/%s/atmos/pgrb2sp25/ge%s.t%sz.pgrb2s.0p25.f%03d" % (GEFS, ymd, hh, mem, hh, fh)
    return _ncep(url, UV)


EC_PARAMS = {"10u": "u", "10v": "v", "msl": "msl"}


def _ec_base(model, stream, typ, ymd, hh, step):
    return "%s/%s/%sz/%s/0p25/%s/%s%s0000-%dh-%s-%s" % (EC, ymd, hh, model, stream, ymd, hh, step, stream, typ)


def _ec_records(base):
    r = get(base + ".index")
    if r is None:
        return None
    return [json.loads(l) for l in r.text.splitlines() if l.strip().startswith("{")]


def ec_url(model, ymd, hh, step, stream="oper", typ="fc"):
    return _ec_base(model, stream, typ, ymd, hh, step) + ".index"


def ec_det(model, ymd, hh, step):
    """model 'ifs' or 'aifs-single' -> {'u','v','msl'} or None."""
    base = _ec_base(model, "oper", "fc", ymd, hh, step)
    recs = _ec_records(base)
    if recs is None:
        return None
    out = {}
    for r in recs:
        if r.get("levtype") == "sfc" and r["param"] in EC_PARAMS:
            out[EC_PARAMS[r["param"]]] = decode(get(base + ".grib2", (r["_offset"], r["_offset"] + r["_length"] - 1)).content)
    return out if len(out) == 3 else None


def ec_ens(ymd, hh, step, model="ifs"):
    """All members' 10 m u and v -> {'u': [n,y,x], 'v': [n,y,x]} or None.
    model "ifs": ENS, 50 perturbed plus the control when posted, in one -ef file.
    model "aifs-ens": AIFS ensemble, the control (-cf) and 50 perturbed (-pf) files."""
    typs = ("ef",) if model == "ifs" else ("cf", "pf")
    jobs = []
    for typ in typs:
        base = _ec_base(model, "enfo", typ, ymd, hh, step)
        recs = _ec_records(base)
        if recs is None:
            return None
        jobs += [(base, r) for r in recs if r.get("levtype") == "sfc" and r["param"] in ("10u", "10v")]

    def one(job):
        base, r = job
        return int(r.get("number", 0)), EC_PARAMS[r["param"]], decode(
            get(base + ".grib2", (r["_offset"], r["_offset"] + r["_length"] - 1)).content)

    mem = {}
    with ThreadPoolExecutor(6) as ex:
        for m, name, v in ex.map(one, jobs):
            mem.setdefault(m, {})[name] = v
    keys = sorted(k for k, d in mem.items() if len(d) == 2)
    if not keys:
        return None
    return {"u": np.array([mem[k]["u"] for k in keys]), "v": np.array([mem[k]["v"] for k in keys])}
