"""One-time build of the 500 mb height climatology used for the anomaly correlation.

Source: WeatherBench 2's ERA5 hourly climatology, 1990-2019, 1.5 degree grid
(gs://weatherbench2/datasets/era5-hourly-climatology/, public, no account).
Keeps 12 UTC, 500 hPa geopotential height for 18-82N, every longitude, by day of
year, as int16 metres in z500_clim.npz (lat north first, lon 0..358.5).

    pip install xarray zarr gcsfs
    python3 make_climo.py
"""
import os

import numpy as np
import xarray as xr

URL = ("gs://weatherbench2/datasets/era5-hourly-climatology/"
       "1990-2019_6h_240x121_equiangular_with_poles_conservative.zarr")

ds = xr.open_zarr(URL, storage_options={"token": "anon"})
z = ds["geopotential"].sel(hour=12, level=500).sel(latitude=slice(18, 82))
z = (z / 9.80665).transpose("dayofyear", "latitude", "longitude").load()
z = z.isel(latitude=slice(None, None, -1))          # north first
np.savez_compressed(os.path.join(os.path.dirname(os.path.abspath(__file__)), "z500_clim.npz"),
                    z=np.round(z.values).astype(np.int16), lat=z.latitude.values.astype(np.float32),
                    lon=z.longitude.values.astype(np.float32), doy=z.dayofyear.values.astype(np.int16))
print(z.shape, float(z.min()), float(z.max()))
