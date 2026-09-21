"""ERA5 access for the precursor study.

ARCO-ERA5 on Google Cloud, read anonymously -- no credentials, nothing
stored. The store is chunked one timestep at a time across the whole globe
(MSLP is [1, 721, 1440]), so a regional slice costs the same as a global
one: there is no saving in asking for a box, and every field here is taken
whole and then sampled. A timestep is about 0.3 s for MSLP.

Nothing is cached to disk on purpose. The container's disk is a fixed
allowance and the study touches thousands of timesteps; holding them would
run it out for no gain, since each is read once.
"""
from __future__ import annotations

import functools
from datetime import timezone

import numpy as np
import xarray as xr

from pressure_field import Field

STORE = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"


@functools.lru_cache(maxsize=1)
def dataset():
    return xr.open_zarr(STORE, chunks=None, storage_options=dict(token="anon"))


@functools.lru_cache(maxsize=1)
def axes():
    ds = dataset()
    return ds.latitude.values, ds.longitude.values


def _stamp(when):
    """A tz-aware UTC datetime as the naive np.datetime64 the store indexes
    on. Archive times carry UTC explicitly; numpy has no timezone, so the
    offset is dropped here once rather than warned about on every read."""
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    return np.datetime64(when.replace(minute=0, second=0, microsecond=0))


def mslp(when):
    """MSLP as a `Field` in hPa at `when` (datetime), nearest hour."""
    ds = dataset()
    lats, lons = axes()
    v = ds.mean_sea_level_pressure.sel(
        time=_stamp(when), method="nearest").values
    return Field(v / 100.0, lats, lons)


def heights(when, levels=(1000, 925, 850, 700, 500, 400, 300)):
    """Geopotential HEIGHT (m) on `levels` at `when`.

    ERA5 stores geopotential in m2/s2; the CPS package wants height in
    metres, so this divides by g rather than leaving the caller to remember.
    """
    ds = dataset()
    z = ds.geopotential.sel(
        time=_stamp(when), method="nearest", level=list(levels)).values
    return {p: z[i] / 9.80665 for i, p in enumerate(levels)}
