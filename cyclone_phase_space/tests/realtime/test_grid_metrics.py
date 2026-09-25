"""gfs_cps.grid_metrics: the dx/dy/coriolis pseudo-fields every product
function is handed. Per its docstring, dx scales each row by cos(lat),
dy is constant, and coriolis is `2 * OMEGA * sin(lat)` -- so it flips
sign between hemispheres and vanishes at the equator.
"""

from __future__ import annotations

import numpy as np

import gfs_cps as g


def _cell_km():
    return g.RES_DEG * g.KM_PER_DEG * 1000.0


def test_shapes_and_dy_constant():
    lat = np.array([-60.0, -20.0, 0.0, 20.0, 60.0])
    nx = 7
    dx, dy, cor = g.grid_metrics(lat, nx)
    assert dx.shape == (lat.size, nx) == dy.shape == cor.shape
    # dy does not depend on latitude or the row's position.
    assert np.allclose(dy, _cell_km())


def test_dx_scales_with_cos_latitude():
    lat = np.array([0.0, 30.0, 60.0, 89.0])
    dx, _, _ = g.grid_metrics(lat, nx=4)
    expected = _cell_km() * np.cos(np.radians(lat))
    assert np.allclose(dx[:, 0], expected)
    # Every column of a row is identical (dx varies by row only).
    assert np.allclose(dx, dx[:, :1])
    # dx shrinks monotonically from the equator to high latitude.
    assert np.all(np.diff(dx[:, 0]) < 0.0)
    # At the equator dx equals the flat cell width; near the pole it is
    # much smaller.
    assert np.isclose(dx[0, 0], _cell_km())
    assert dx[-1, 0] < 0.1 * _cell_km()


def test_coriolis_sign_by_hemisphere():
    lat = np.array([-45.0, 0.0, 45.0])
    _, _, cor = g.grid_metrics(lat, nx=3)
    assert cor[0, 0] < 0.0  # Southern Hemisphere: negative
    assert cor[1, 0] == 0.0  # equator: zero
    assert cor[2, 0] > 0.0  # Northern Hemisphere: positive
    # Antisymmetric about the equator for symmetric latitudes.
    assert np.isclose(cor[0, 0], -cor[2, 0])


def test_coriolis_magnitude():
    lat = np.array([90.0])
    _, _, cor = g.grid_metrics(lat, nx=1)
    assert np.isclose(cor[0, 0], 2.0 * g.OMEGA)
