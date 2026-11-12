import datetime as dt
import gzip
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nwp import rss_ascat as rss  # noqa: E402


class R:
    def __init__(self, content):
        self.content = content


def synthetic():
    """Two passes: pass 0 has a 20 m/s wind at row 600 (lat 60.125), column 0 (lon 0.125) from the east-going
    direction byte 0 (toward north, so the wind is FROM the south, 180), time byte 100 (10:00); a cell outside
    15-70N; a no-data cell. Pass 1 has one cell at lon 359.875 (-0.125) with the rain bit and direction byte 120
    (toward 180, FROM 0)."""
    a = np.full((2, 5, 720, 1440), 255, np.uint8)
    a[0, 0, 600, 0], a[0, 1, 600, 0], a[0, 2, 600, 0], a[0, 3, 600, 0] = 100, 100, 0, 0
    a[0, 0, 10, 5], a[0, 1, 10, 5], a[0, 2, 10, 5], a[0, 3, 10, 5] = 100, 100, 0, 0         # lat -87.4: outside
    a[0, 0, 650, 7], a[0, 1, 650, 7] = 100, 255                                           # no wind
    a[1, 0, 630, 1439], a[1, 1, 630, 1439], a[1, 2, 630, 1439], a[1, 3, 630, 1439] = 240, 50, 120, 1 | (3 << 2)
    return a


def test_cells_units_direction_node_and_lon():
    c = rss.cells(synthetic())
    assert c["lat"].size == 2
    i, j = (int(np.nonzero(c["node"] == n)[0][0]) for n in (0, 1))
    assert c["lat"][i] == pytest.approx(-89.875 + 0.25 * 600) and c["lon"][i] == pytest.approx(0.125)
    assert c["spd_kt"][i] == pytest.approx(100 * 0.2 * 1.943844, rel=1e-5)
    assert c["dir_deg"][i] == pytest.approx(180.0)          # RSS direction is toward north: wind from the south
    assert c["t_min"][i] == 600 and c["rain"][i] == 0
    assert c["lon"][j] == pytest.approx(-0.125)             # 359.875 wraps to -0.125
    assert c["dir_deg"][j] == pytest.approx(0.0) and c["rain"][j] == 1 and c["t_min"][j] == 1440
    assert all(c[k].size == 2 for k in c)


def test_day_url_and_404(monkeypatch):
    seen = []

    def g(u, rng=None, tries=8):
        seen.append(u)
        return None if "ascatc" in u else R(gzip.compress(synthetic().tobytes()))
    monkeypatch.setattr(rss, "get", g)
    assert rss.day("b", dt.datetime(2026, 11, 7, 13))["lat"].size == 2
    assert rss.day("Metop-C", dt.date(2026, 11, 7)) is None
    assert seen == ["https://data.remss.com/ascat/metopb/bmaps_v02.1/y2026/m11/ascatb_20261107_v02.1.gz",
                    "https://data.remss.com/ascat/metopc/bmaps_v02.1/y2026/m11/ascatc_20261107_v02.1.gz"]
    with pytest.raises(ValueError):
        rss.sat_letter("a")
