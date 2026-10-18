"""export_web.hart_products and collection_point: the web's products use
Hart's own layers (900-600 and 600-300 hPa), B from the 900-600 hPa
thickness with no rescaling, and the class from the three inside the
closed-low mask; collection points prefer the collector's Hart columns."""

from __future__ import annotations

import numpy as np
import pytest

import export_web as ew
import gfs_cps as g
from rt_synthetic import make_frame, add_gaussian_low, nearest_index


def _frame_with_levels(warm_core_m: float = 0.0):
    """A 20 x 40 degree frame at 0.25 degree with a 20 hPa closed low, flat
    heights at every level (plus a warm core whose perturbation shrinks
    with height when warm_core_m is set), and a 10 m/s westerly at every
    wind level so the steering heading is defined everywhere."""
    f = make_frame(30.0, 50.0, -40.0, 0.0)
    add_gaussian_low(f, 40.0, -20.0, 20.0, 300.0)
    la = f["lat"][:, None]
    lo = f["lon"][None, :]
    r2 = ((la - 40.0) * 111.0) ** 2 + ((lo + 20.0) * 111.0 * np.cos(np.radians(40.0))) ** 2
    bump = np.exp(-r2 / (2 * 200.0 ** 2))
    levels = sorted(set(g.HGT_LEVELS) | set(g.HART_LOWER) | set(g.HART_UPPER) | {1000})
    for p in levels:
        base = 11000.0 * np.log(1013.0 / p)  # a rough standard height
        # a warm core lowers the heights least at the top: perturbation falls with height
        pert = -warm_core_m * bump * (p / 900.0)
        f[f"z{p}"] = np.full(f["pmsl"].shape, base) + pert
    for p in g.WIND_LEVELS:
        f[f"u{p}"] = np.full(f["pmsl"].shape, 10.0)
        f[f"v{p}"] = np.zeros(f["pmsl"].shape)
    return f


def test_hart_products_keys_and_mask():
    f = _frame_with_levels()
    p = ew.hart_products(f)
    assert set(p) == {"hvtl", "hvtu", "hb", "cls", "idx"}
    i, j = nearest_index(f, 40.0, -20.0)
    assert np.isfinite(p["cls"][i, j])  # inside the closed low
    assert not np.isfinite(p["cls"][2, 2])  # far corner: no closed low
    # flat heights: no thermal wind and no asymmetry, so the class is 0 at the center
    assert p["hvtl"][i, j] == pytest.approx(0.0, abs=1e-6)
    assert p["hvtu"][i, j] == pytest.approx(0.0, abs=1e-6)
    assert p["hb"][i, j] == pytest.approx(0.0, abs=1e-6)
    assert p["cls"][i, j] == 0
    assert p["idx"][i, j] == pytest.approx(0.0, abs=1e-6)
    assert not np.isfinite(p["idx"][2, 2])


def test_hart_products_warm_core_reads_warm_in_both_bands():
    f = _frame_with_levels(warm_core_m=120.0)
    p = ew.hart_products(f)
    i, j = nearest_index(f, 40.0, -20.0)
    # the perturbation shrinks with height, so both of Hart's bands read a warm core
    assert p["hvtl"][i, j] > 20.0
    assert p["hvtu"][i, j] > 5.0
    assert p["cls"][i, j] in (0, 2)


def test_b_thickness_is_the_900_600_layer():
    f = _frame_with_levels()
    thk = ew.b_thickness(f)
    assert thk[5, 5] == pytest.approx(float(f["z600"][5, 5] - f["z900"][5, 5]))


def _row(**kw):
    base = {"fhr": "6", "valid": "2026-10-01T06Z", "lat": "40.0", "lon": "-20.0", "mslp_hpa": "980.0",
            "class": "3", "hvtl": "50.0", "hvtu": "-30.0", "hb": "20.0"}
    base.update(kw)
    return base


def test_collection_point_prefers_the_hart_columns_and_reclassifies():
    pt = ew.collection_point(_row(hvtl_hart="40.0", hvtu_hart="-10.0", hb_hart="4.0"))
    assert (pt["hvtl"], pt["hvtu"], pt["hb"]) == (40.0, -10.0, 4.0)
    assert pt["cls"] == 1  # symmetric shallow warm core from Hart's values, not the row's standard class 3
    assert pt["valid"] == "2026-10-01T06:00Z"


def test_collection_point_falls_back_to_the_standard_columns():
    pt = ew.collection_point(_row())
    assert (pt["hvtl"], pt["hvtu"], pt["hb"], pt["cls"]) == (50.0, -30.0, 20.0, 3)
    pt = ew.collection_point(_row(hvtl_hart="", hvtu_hart="nan", hb_hart=""))
    assert pt["cls"] == 3


def test_collection_point_outside_a_closed_low_has_no_class():
    pt = ew.collection_point(_row(**{"class": "", "hvtl_hart": "40.0", "hvtu_hart": "-10.0", "hb_hart": "4.0"}))
    assert pt["cls"] is None
