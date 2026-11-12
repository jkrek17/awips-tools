import datetime as dt
import os
import sys
import urllib.parse

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nwp import nesdis_ascat as nes  # noqa: E402

HEAD = ("time,latitude,longitude,WSPD_Ascending,WSPD_Descending,uwnd_Ascending,uwnd_Descending,vwnd_Ascending,vwnd_Descending,"
        "Rain_Flag_Ascending,Rain_Flag_Descending,Time_Ascending,Time_Descending\n"
        "UTC,degrees_north,degrees_east,m s-1,m s-1,m s-1,m s-1,m s-1,m s-1,,,hour,hour\n")


class R:
    def __init__(self, text):
        self.text = text


def synthetic():
    """Row 1: no data in either pass. Row 2: an ascending cell, 10 m/s with u = 0 and v = -10 (blows toward the south, so
    FROM the north, 0), at 3840 s (64 min), rain 1. Row 3: a descending cell, u = -5, v = 0 (toward the west, FROM the east,
    90), 20 m/s, time 86272 s, no rain."""
    nan = "NaN"
    rows = ["2026-11-06T12:00:00Z,18.125,-94.875," + ",".join([nan] * 10),
            "2026-11-06T12:00:00Z,40.125,-30.125,10.0,NaN,0.0,NaN,-10.0,NaN,1.0,NaN,3840.0,NaN",
            "2026-11-06T12:00:00Z,41.375,-30.375,NaN,20.0,NaN,-5.0,NaN,0.0,NaN,0.0,NaN,86272.0"]
    return HEAD + "\n".join(rows) + "\n"


def test_cells_units_direction_time_node_rain():
    c = nes.cells(synthetic())
    assert all(c[k].size == 2 for k in c)
    i, j = (int(np.nonzero(c["node"] == n)[0][0]) for n in (0, 1))
    assert c["spd_kt"][i] == pytest.approx(10 * 1.94384, rel=1e-5) and c["spd_kt"][j] == pytest.approx(20 * 1.94384, rel=1e-5)
    assert c["dir_deg"][i] == pytest.approx(0.0) or c["dir_deg"][i] == pytest.approx(360.0)   # toward south: FROM north
    assert c["dir_deg"][j] == pytest.approx(90.0)                                            # toward west: FROM east
    assert c["t_min"][i] == 64 and c["t_min"][j] == round(86272 / 60)
    assert c["rain"][i] == 1 and c["rain"][j] == 0
    assert c["lat"][i] == pytest.approx(40.125) and c["lon"][j] == pytest.approx(-30.375)


def test_cells_empty_and_single_row():
    assert nes.cells(HEAD + "2026-11-06T12:00:00Z,18.125,-94.875," + ",".join(["NaN"] * 10) + "\n")["lat"].size == 0
    assert nes.cells(HEAD + "2026-11-06T12:00:00Z,40.125,-30.125,10,NaN,0,NaN,-10,NaN,0,NaN,100,NaN\n")["lat"].size == 1


def test_pieces_split_at_the_date_line():
    assert nes.pieces(-95, 10) == [(-95, 10)]
    assert nes.pieces(135, 245) == [(135, 180.0), (-180.0, -115)]
    assert nes.pieces(-180, 180) == [(-180.0, 180.0)]


def test_day_requests_and_none(monkeypatch):
    seen = []

    def g(u, rng=None, tries=8):
        seen.append(urllib.parse.unquote(u))
        return None if "2026-11-09" in u else R(synthetic())
    monkeypatch.setattr(nes, "get", g)
    c = nes.day(dt.datetime(2026, 11, 6, 15), (18, 67, 135, 245))
    assert c["lat"].size == 4                                  # two pieces, two cells each
    assert len(seen) == 2 and all("(2026-11-06T12:00:00Z)" in u for u in seen)
    assert "[(18):1:(67)][(135):1:(180)]" in seen[0] and "[(-180):1:(-115)]" in seen[1]
    assert "WSPD_Ascending" in seen[0] and "Time_Descending" in seen[0] and seen[0].count(",") == 9
    assert nes.day(dt.date(2026, 11, 9), (18, 67, -95, 10)) is None
    assert len(seen) == 3
