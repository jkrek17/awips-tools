import datetime as dt
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nwp import star  # noqa: E402


class R:
    def __init__(self, content):
        self.content = content


def test_start_time_both_layouts():
    assert star.start_time("/x/oscat3_AS_2026-301T02-32-14_lite5.json") == dt.datetime(2026, 10, 28, 2, 32, 14)
    assert star.start_time("/x/UHR_METOP-B_20261028T003525_73213_rev1of1_ec.json") == dt.datetime(2026, 10, 28, 0, 35, 25)
    assert star.start_time("a_2024-061T00-00-00_x.json") == dt.datetime(2024, 3, 1)   # leap year
    with pytest.raises(ValueError):
        star.start_time("nothing.json")


def test_points_oscat_records():
    p = star.parse([dict(la=50.0, lo=350.0, u=3.0, v=4.0, q=0), dict(la=51.0, lo=-10.0, u=-6.0, v=8.0, q=1)])
    assert p["lon"].tolist() == [-10.0, -10.0]
    assert np.allclose(p["spd"], [5, 10])
    assert p["q"].tolist() == [0, 1] and p["q"].dtype == np.uint8
    assert set(p) == {"lat", "lon", "u", "v", "spd", "q"}


def test_points_uhr_grid():
    hd = dict(lo1=190.0, la1=60.0, dx=0.5, dy=0.5, nx=3, ny=2)
    recs = [dict(header=dict(hd, parameterNumber=2), data=[1, None, 3, 0, 0, None]),
            dict(header=dict(hd, parameterNumber=3), data=[1, None, 4, 0, 0, None]),
            dict(header=dict(hd, parameterNumber=0), data=[0, None, 1, 0, 0, None])]
    p = star.parse(recs)
    assert p["lat"].tolist() == [60.0, 60.0, 59.5, 59.5]      # grid runs southward from la1
    assert p["lon"].tolist() == [-170.0, -169.0, -170.0, -169.5]
    assert np.allclose(p["spd"], [2 ** 0.5, 5, 0, 0])
    assert p["q"].tolist() == [0, 1, 0, 0]


def test_points_empty():
    assert star.parse([])["lat"].size == 0


def test_passes_and_points(monkeypatch):
    lst = {"json_urls": ["/d/UHR_METOP-C_20261028T120000_1_rev1of2_ec.json", "/d/UHR_METOP-C_20261028T113000_1_rev1of2_ec.json"]}

    def g(url, rng=None, tries=8):
        if "prefix=UHR_METOP-C_AS" in url:
            assert "date=20261028" in url
            return R(json.dumps(lst).encode())
        if url.endswith("11.json"):
            return R(json.dumps([dict(la=1, lo=2, u=3, v=4, q=0)]).encode())
        return None
    monkeypatch.setattr(star, "get", g)
    out = star.passes(dt.date(2026, 10, 28))
    assert [o[2] for o in out] == [dt.datetime(2026, 10, 28, 11, 30), dt.datetime(2026, 10, 28, 12, 0)]
    assert out[0][0] == "UHR_METOP-C_AS" and out[0][1].startswith(star.URL + "/d/")
    assert star.points(star.URL + "/x/11.json")["spd"][0] == pytest.approx(5)
    assert star.points(star.URL + "/x/gone.json") is None
