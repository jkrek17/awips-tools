"""One GRIB2 message -> a north-up, lon 0..360 float32 grid."""
from __future__ import annotations

import numpy as np


def decode(blob, crop=None):
    """crop: optional (IY, IX) index pair, applied as v[IY, IX].copy(). Without it
    the full grid comes back."""
    import eccodes
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
    if crop is not None:
        return v[crop[0], crop[1]].copy()
    return np.ascontiguousarray(v)
