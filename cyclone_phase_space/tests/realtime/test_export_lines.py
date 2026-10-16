"""export_web's display smoothing, contour lines and 250 hPa jet raster.

smooth is a Gaussian over grid cells, wrapped in longitude and clamped in
latitude; contour_features writes one LineString per contour with the
level divided by `scale`; save_jet_png puts each pixel in its
JET_BANDS_KT band, clear below the first. No GRIB or network.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

import export_web as ew

LAT = np.arange(-60.0, 60.25, 0.25)
LON = np.arange(-180.0, 180.0, 0.25)


def test_smooth_keeps_a_constant_field():
    a = np.full((LAT.size, LON.size), 1012.0)
    assert np.allclose(ew.smooth(a, 2.0), 1012.0)


def test_smooth_wraps_across_the_dateline():
    a = np.zeros((LAT.size, LON.size))
    a[:, 0] = 1.0  # a ridge on the first column (lon -180)
    s = ew.smooth(a, 2.0)
    assert s[:, -1].min() > 0.1  # spread onto the last column (lon 179.75)
    assert np.isclose(s[:, -1].mean(), s[:, 1].mean())
    assert np.isclose(s.sum(), a.sum())


def test_smooth_damps_grid_noise():
    rng = np.random.default_rng(0)
    a = 1000.0 + rng.normal(0.0, 1.0, (LAT.size, LON.size))
    assert ew.smooth(a, 2.0).std() < 0.2 * a.std()


def test_contour_levels_are_scaled_to_dam():
    z = np.repeat((5400.0 + 10.0 * LAT)[:, None], LON.size, axis=1)  # 5 m per 0.25 deg northward
    feats = ew.contour_features(z, LAT, LON, 60.0, 0.15, scale=10.0)
    levels = sorted({f["properties"]["level"] for f in feats})
    assert levels[:3] == [480, 486, 492]
    assert all(f["geometry"]["type"] == "LineString" for f in feats)
    lons = [c[0] for f in feats for c in f["geometry"]["coordinates"]]
    assert min(lons) == -180.0 and max(lons) == 180.0  # lines reach both sides of the dateline


def test_jet_bands(tmp_path):
    kt = np.repeat(np.linspace(0.0, 160.0, LON.size)[None, :], LAT.size, axis=0)
    f = {"u250": kt / ew.MS_TO_KT, "v250": np.zeros_like(kt)}
    smp = ew.Sampler(LAT, LON, width=512, lat_max=50.0)
    ew.save_jet_png(f, smp, tmp_path / "jet.png")
    idx = np.asarray(Image.open(tmp_path / "jet.png"))[smp.height // 2]
    spd = smp(np.hypot(f["u250"], f["v250"]) * ew.MS_TO_KT)[smp.height // 2]
    clear = len(ew.JET_COLORS)
    assert (idx[spd < 69] == clear).all()
    assert (idx[(spd > 71) & (spd < 89)] == 0).all()
    assert (idx[(spd > 111) & (spd < 129)] == 2).all()
    assert (idx[spd > 131] == 3).all()
