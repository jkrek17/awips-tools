"""Byte-range fetch of 10 m wind and MSLP from the AWS open-data mirrors.

Only the needed GRIB records are downloaded (from the .idx / .index files) and
each is decoded straight to the page's domain, so a full run (3 models plus
82 ensemble members at 10 lead times) streams about 2.5 GB and keeps a few MB.

Sources (all public, no account):
    GFS        noaa-gfs-bdp-pds   gfs.YYYYMMDD/HH/atmos/gfs.tHHz.pgrb2.0p25.fFFF
    GEFS       noaa-gefs-pds      gefs.YYYYMMDD/HH/atmos/pgrb2sp25/geMMM.tHHz.pgrb2s.0p25.fFFF
    ECMWF IFS, AIFS and ENS       ecmwf-forecasts YYYYMMDD/HHz/{ifs,aifs-single}/0p25/{oper,enfo}/

A thin shim over the shared nwp package (<repo>/nwp); the page's domain crop is applied here.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "nwp"))
import nwp  # noqa: E402
from nwp import sources  # noqa: E402
from nwp import http as _http  # noqa: E402

from domain import IX, IY  # noqa: E402

GFS, GEFS, EC, GEFS_MEMBERS = sources.GFS, sources.GEFS, sources.EC, sources.GEFS_MEMBERS
CROP = (IY, IX)

_session = _http._session
get = nwp.get
exists = nwp.exists


def decode(blob):
    """One GRIB2 message -> the domain crop, north-up, lon 0..360 order."""
    return nwp.decode(blob, CROP)


def _ncep(url, want):
    """want: {'UGRD:10 m above ground': 'u', ...} -> {'u': array, ...} or None."""
    return nwp.ncep(url, want, CROP)


UV = {"UGRD:10 m above ground": "u", "VGRD:10 m above ground": "v"}
UVP = dict(UV, **{"PRMSL:mean sea level": "msl"})


def gfs_url(ymd, hh, fh):
    return sources.gfs(ymd, hh, fh)


def gfs(ymd, hh, fh):
    return _ncep(gfs_url(ymd, hh, fh), UVP)


# extra GFS fields for the storm layers' core model (storm.py): low-level wind and temperature,
# 2 m and surface temperature, and the land / sea-ice masks
GFS_LOW = {"TMP:2 m above ground": "t2", "TMP:surface": "skt", "UGRD:925 mb": "u925", "VGRD:925 mb": "v925",
           "TMP:925 mb": "t925", "UGRD:850 mb": "u850", "VGRD:850 mb": "v850", "TMP:850 mb": "t850",
           "LAND:surface": "land", "ICEC:surface": "ice"}


def gfs_low(ymd, hh, fh):
    return _ncep(gfs_url(ymd, hh, fh), GFS_LOW)


def gefs(ymd, hh, fh, mem, msl=False):
    return _ncep(sources.gefs(ymd, hh, fh, mem), UVP if msl else UV)


EC_PARAMS = {"10u": "u", "10v": "v", "msl": "msl"}


def _ec_base(model, stream, typ, ymd, hh, step):
    return sources.ecmwf(model, stream, typ, ymd, hh, step)


def _ec_records(base):
    return nwp.ec_records(base)


def ec_url(model, ymd, hh, step, stream="oper", typ="fc"):
    return _ec_base(model, stream, typ, ymd, hh, step) + ".index"


_EC_DET = {("sfc", p, None): n for p, n in EC_PARAMS.items()}


def ec_det(model, ymd, hh, step):
    """model 'ifs' or 'aifs-single' -> {'u','v','msl'} or None."""
    out = nwp.ec_fields(_ec_base(model, "oper", "fc", ymd, hh, step), _EC_DET, CROP)
    return out if out is not None and len(out) == 3 else None


EC_LOW_SFC = {"2t": "t2", "skt": "skt"}
EC_LOW_PL = {(p, lev): p + lev for p in ("u", "v", "t") for lev in ("925", "850")}
_EC_LOW = {("sfc", p, None): n for p, n in EC_LOW_SFC.items()}
_EC_LOW.update({("pl", p, lev): n for (p, lev), n in EC_LOW_PL.items()})


def ec_low(model, ymd, hh, step):
    """model 'ifs' or 'aifs-single' -> {'t2','skt','u925','v925','t925','u850','v850','t850'} or None."""
    out = nwp.ec_fields(_ec_base(model, "oper", "fc", ymd, hh, step), _EC_LOW, CROP)
    return out if out is not None and len(out) == 8 else None


def ec_ens(ymd, hh, step, model="ifs", msl=False):
    """All members' 10 m u and v (and msl if asked) -> {'u': [n,y,x], 'v': [n,y,x](, 'msl')} or None.
    model "ifs": ENS, 50 perturbed plus the control when posted, in one -ef file.
    model "aifs-ens": AIFS ensemble, the control (-cf) and 50 perturbed (-pf) files."""
    select = {p: n for p, n in EC_PARAMS.items() if msl or p != "msl"}
    return nwp.ec_ens(model, ymd, hh, step, select, CROP)
