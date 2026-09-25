"""export_web's web rasters: the diverging ramps, the bilinear sampler and
the fade mask (see export_web.py, "Rasters"). No GRIB or network."""

from __future__ import annotations

import numpy as np
import pytest

import export_web as ew


def test_ramp_is_transparent_at_zero_and_opaque_outside_the_fade():
    for name in ew.WEB_RAMPS:
        rgba = ew.ramp_rgba(name)
        assert rgba.shape == (ew.RAMP_N, 4)
        mid = ew.RAMP_N // 2
        assert rgba[mid, 3] == 0
        assert rgba[0, 3] == 255 and rgba[-1, 3] == 255
        edge = int(round((ew.RAMP_N - 1) / 2 * (1 + ew.RAMP_FADE))) + 1
        assert rgba[edge, 3] == 255
        # alpha rises monotonically away from zero
        a = rgba[mid:, 3].astype(int)
        assert np.all(np.diff(a) >= 0)


def test_ramp_ends_match_the_anchors():
    neg, pos = ew.WEB_RAMPS["core"]
    rgba = ew.ramp_rgba("core")
    assert rgba[0, :3].tolist() == ew.hex_rgb(neg[-1]).astype(int).tolist()
    assert rgba[-1, :3].tolist() == ew.hex_rgb(pos[-1]).astype(int).tolist()


def test_cmap_index_covers_the_range_and_marks_nan():
    n = ew.RAMP_N
    k = ew.cmap_index(np.array([-300.0, 0.0, 299.9, 300.0, 1000.0, -1000.0, np.nan]), n, -300.0, 300.0)
    assert k[0] == 0 and k[1] == n // 2 and k[2] == n - 1
    assert k[3] == n - 1 and k[4] == n - 1 and k[5] == 0  # ends clipped onto the ramp
    assert k[6] == n  # the transparent entry


@pytest.fixture
def grid():
    lat = np.arange(-90.0, 90.01, 0.25)
    lon = np.arange(0.0, 360.0, 0.25)
    return lat, lon


def test_sampler_bilinear_reproduces_a_linear_field(grid):
    lat, lon = grid
    smp = ew.Sampler(lat, lon, width=256)
    field = 2.0 * lat[:, None] + 0.0 * lon[None, :]
    out = smp(field)
    assert out.shape == (smp.height, 256)
    # the sampled value at each output row is the field at that row's latitude
    ymax = np.log(np.tan(np.pi / 4 + np.radians(ew.LAT_MAX) / 2))
    y = ymax - (np.arange(smp.height) + 0.5) * (2 * ymax / smp.height)
    lat_out = np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)
    assert np.allclose(out[:, 0], 2.0 * lat_out, atol=1e-6)
    # nearest sampling differs from the exact value by up to half a cell
    assert np.max(np.abs(smp.nearest(field)[:, 0] - 2.0 * lat_out)) <= 0.25 + 1e-9


def test_sampler_bilinear_wraps_the_seam_and_skips_nan(grid):
    lat, lon = grid
    smp = ew.Sampler(lat, lon, width=256)
    field = np.ones((lat.size, lon.size))
    field[:, 0] = np.nan  # the column at 0 E is missing
    out = smp(field)
    assert np.all(np.isfinite(out))  # the finite neighbours carry the seam
    assert np.allclose(out, 1.0)
    field[:] = np.nan
    assert np.all(np.isnan(smp(field)))


def test_fade_mask_is_one_inside_and_dim_far_away():
    cls = np.full((200, 400), np.nan)
    cls[90:110, 190:230] = 3.0
    m = ew.fade_mask(cls)
    assert m.min() == pytest.approx(ew.MASK_DIM)
    assert m.max() == pytest.approx(1.0)
    assert m[100, 210] == pytest.approx(1.0)
    assert m[10, 10] == pytest.approx(ew.MASK_DIM)
    # eases outward: closer to the footprint means heavier
    row = m[110:130, 210]
    assert np.all(np.diff(row) <= 1e-12)
    assert m[130, 210] == pytest.approx(ew.MASK_DIM, abs=0.02)


def test_box_mean_of_a_constant_is_the_constant():
    a = np.full((30, 50), 0.7)
    assert np.allclose(ew.box_mean(a, 4), 0.7)


def test_save_mask_png_round_trip(tmp_path):
    from PIL import Image
    w = np.linspace(0.35, 1.0, 64)[None, :].repeat(8, axis=0)
    ew.save_mask_png(w, tmp_path / "mask.png")
    im = Image.open(tmp_path / "mask.png")
    assert im.mode == "LA" and im.size == (64, 8)
    a = np.array(im)[..., 1] / 255.0
    assert np.allclose(a, w, atol=1 / 255)
