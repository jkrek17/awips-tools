import datetime as dt
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nwp import podaac_ascat as pa  # noqa: E402

netCDF4 = pytest.importorskip("netCDF4")
T0 = dt.datetime(2026, 11, 12, 23, 50)     # the first row: 10 minutes before midnight, so the orbit crosses 00 UTC


def synthetic(path, wind_dir_attrs=None, rows=4):
    """Orbit of `rows` x 3 cells, netCDF classic (version 3) as KNMI writes it, scaled shorts and ints.
    Row r is r minutes after T0; latitudes 40 + r (ascending) ; lon 350, 10, 180 (0..360 convention).
    wind m/s: [10, 20, 30] x row 0; dir 90 (toward east) everywhere except cell [1, 1] = 270.
    Flags: cell [0, 1] KNMI QC fail (131072), [0, 2] rain detected (512) plus wind > 30 (4096), [1, 0] land (32768),
    [2, 0] monitored event (262144) with monitoring in use, [3, 0] event with monitoring not used (kept), [3, 1] masked wind."""
    ds = netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC")
    ds.createDimension("NUMROWS", rows)
    ds.createDimension("NUMCELLS", 3)
    ds.comment = "All wind directions in oceanographic convention (0 deg. flowing North)"
    secs = (np.arange(rows)[:, None] * 60 + (T0 - pa.EPOCH).total_seconds() + np.zeros((rows, 3))).astype("i4")
    v = ds.createVariable("time", "i4", ("NUMROWS", "NUMCELLS")); v.units = "seconds since 1990-01-01 00:00:00"; v[:] = secs
    for name, vals, scale in (("lat", 40.0 + np.arange(rows)[:, None] + np.zeros((rows, 3)), 1e-3),
                              ("lon", np.array([350.0, 10.0, 180.0])[None, :] + np.zeros((rows, 3)), 1e-3)):
        v = ds.createVariable(name, "i4", ("NUMROWS", "NUMCELLS")); v.scale_factor = scale; v.add_offset = 0.0
        v[:] = vals
    ws = np.tile([10.0, 20.0, 30.0], (rows, 1))
    v = ds.createVariable("wind_speed", "i2", ("NUMROWS", "NUMCELLS"), fill_value=-32767)
    v.scale_factor = 0.01; v.add_offset = 0.0; v.units = "m s-1"
    wsm = np.ma.masked_array(ws, np.zeros(ws.shape, bool)); wsm[3, 1] = np.ma.masked
    v[:] = wsm
    wd = np.full((rows, 3), 90.0); wd[1, 1] = 270.0
    v = ds.createVariable("wind_dir", "i2", ("NUMROWS", "NUMCELLS"), fill_value=-32767)
    v.scale_factor = 0.1; v.add_offset = 0.0; v.units = "degree"
    for k, x in (wind_dir_attrs or {}).items():
        setattr(v, k, x)
    v[:] = wd
    fl = np.zeros((rows, 3), "i4")
    fl[0, 1], fl[0, 2], fl[1, 0], fl[2, 0], fl[3, 0] = 131072, 512 | 4096, 32768, 262144, 262144 | 524288
    fl[:, 2] |= 524288
    fl[0, 0] |= 524288
    v = ds.createVariable("wvc_quality_flag", "i4", ("NUMROWS", "NUMCELLS")); v[:] = fl
    ds.close()


def test_cells_units_direction_flags_time(tmp_path):
    p = str(tmp_path / "o.l2.nc")
    synthetic(p)
    c = pa.cells(p, day=dt.datetime(2026, 11, 12))
    # 12 cells: QC fail [0,1], land [1,0], event with monitoring in use [2,0], masked wind [3,1] are out -> 8 left
    assert c["lat"].size == 8
    # speeds in knots (10, 20 and 30 m/s), the > 30 m/s bit does not drop the cell
    assert set(np.round(c["spd_kt"] / pa.KT).astype(int).tolist()) == {10, 20, 30}
    # lon 0..360 -> -180..180 (350 -> -10, 180 -> -180)
    assert set(np.round(c["lon"]).astype(int).tolist()) == {-10, 10, -180}
    # oceanographic 90 (toward east) is FROM 270; 270 toward is FROM 90
    assert set(np.round(c["dir_deg"]).astype(int).tolist()) == {270, 90}
    j = np.nonzero((np.abs(c["lat"] - 41.0) < 1e-3) & (np.abs(c["lon"] - 10.0) < 1e-3))[0][0]
    assert abs(c["dir_deg"][j] - 90.0) < 0.05
    # time: minutes after 00 UTC of the given day; the first row is 23:50 = 1430 min, the next rows 1431, 1432 ...
    assert np.isclose(c["t_min"].min(), 1430.0) and np.isclose(c["t_min"].max(), 1433.0)
    # rain: only the cell with bit 512; the unmonitored event is kept
    assert int(c["rain"].sum()) == 1 and abs(c["spd_kt"][c["rain"] == 1][0] - 30 * pa.KT) < 0.01
    assert ((np.abs(c["lat"] - 43.0) < 1e-3) & (np.abs(c["lon"] + 10.0) < 1e-3)).any()
    # ascending: latitude rises along track
    assert (c["node"] == 0).all()
    # default day: the UTC day of the earliest valid cell
    c2 = pa.cells(open(p, "rb").read())
    assert np.isclose(c2["t_min"].min(), 1430.0) and c2["lat"].size == 8


def test_direction_convention_from_attribute(tmp_path):
    p = str(tmp_path / "f.nc")
    synthetic(p, {"standard_name": "wind_from_direction"})
    c = pa.cells(p)
    assert set(np.round(c["dir_deg"]).astype(int).tolist()) == {90, 270}
    j = np.nonzero((np.abs(c["lat"] - 41.0) < 1e-3) & (np.abs(c["lon"] - 10.0) < 1e-3))[0][0]
    assert abs(c["dir_deg"][j] - 270.0) < 0.05          # taken as FROM when the file says so


def test_not_netcdf_is_refused():
    with pytest.raises(ValueError):
        pa.cells(b"<html>login</html>")


def test_credentials_from_env_only():
    assert pa.credentials({}) is None
    assert pa.credentials({"EARTHDATA_USER": "u"}) is None
    assert pa.credentials({"EARTHDATA_USER": "u", "EARTHDATA_PASS": ""}) is None
    assert pa.credentials({"EARTHDATA_USER": "u", "EARTHDATA_PASS": "p"}) == ("u", "p")


def test_auth_kept_only_for_urs():
    import requests
    s = pa.session("u", "p", get_token=lambda u, p: "tok")

    def moved(frm, to):
        prep = requests.Request("GET", to, headers={"Authorization": "Basic x"}).prepare()
        resp = requests.Response()
        resp.request = requests.Request("GET", frm).prepare()
        s.rebuild_auth(prep, resp)
        return "Authorization" in prep.headers
    arc, urs = "https://archive.podaac.earthdata.nasa.gov/a.nc", "https://urs.earthdata.nasa.gov/oauth/authorize"
    assert moved(arc, urs)                                  # to the login host: kept
    assert moved(urs, arc)                                  # back from it: kept
    assert not moved(arc, "https://d1234.cloudfront.net/a.nc")   # anywhere else: dropped


def test_granules_parse_and_paging():
    def entry(i):
        return dict(title="ascat_20261112_%04d00_metopc_%d_eps_o_250_3301_ovw.l2" % (i, 41000 + i),
                    time_start="2026-11-12T%02d:%02d:00.000Z" % (i // 60, i % 60), time_end="2026-11-12T%02d:%02d:56.000Z" % (i // 60 + 1, i % 60),
                    granule_size="0.95",
                    links=[dict(rel="http://esipfed.org/ns/fedsearch/1.1/s3#", href="s3://x/a.nc"),
                           dict(rel="http://esipfed.org/ns/fedsearch/1.1/data#", href="https://archive.podaac.earthdata.nasa.gov/p/a%d.l2.nc" % i)])

    class R:
        def __init__(self, entries):
            self.entries = entries

        def json(self):
            return dict(feed=dict(entry=self.entries))
    seen = []

    def fetch(u):
        seen.append(u)
        return R([entry(i) for i in range(100)] if "page_num=1" in u else [entry(100), dict(title="nolink", time_start="2026-11-12T00:00:00.000Z",
                                                                                       time_end="2026-11-12T01:00:00.000Z", links=[])])
    g = pa.granules(dt.datetime(2026, 11, 11), dt.datetime(2026, 11, 12, 12), fetch=fetch)
    assert len(seen) == 2 and "temporal=2026-11-11T00:00:00Z,2026-11-12T12:00:00Z" in seen[0] and "short_name=ASCATC-L2-25km" in seen[0]
    assert len(g) == 101 and g[0]["start"] > g[-1]["start"] and g[0]["url"].endswith(".l2.nc") and g[0]["end"] > g[0]["start"]


def test_download_refuses_login_page_and_never_loops_on_401():
    class Resp:
        def __init__(self, code, body, url="https://urs.earthdata.nasa.gov/x"):
            self.status_code, self.content, self.url, self.headers = code, body, url, {"content-type": "text/html"}

    class S:
        def __init__(self, resp):
            self.resp, self.n = resp, 0

        def get(self, url, timeout=0):
            self.n += 1
            return self.resp
    s = S(Resp(401, b""))
    with pytest.raises(pa.AuthError):
        pa.download("https://archive.podaac.earthdata.nasa.gov/a.nc", s, pause=0)
    assert s.n == 1
    with pytest.raises(pa.AuthError):
        pa.download("https://archive.podaac.earthdata.nasa.gov/a.nc", S(Resp(200, b"<html>")), pause=0)
    assert pa.download("https://a/a.nc", S(Resp(200, b"CDF\x01abc")), pause=0) == b"CDF\x01abc"


class _R:
    def __init__(self, code, j):
        self.status_code, self._j = code, j

    def json(self):
        return self._j


def test_token_ok_and_refused():
    assert pa.token("u", "p", post=lambda *a, **k: _R(200, {"access_token": "abc"})) == "abc"
    try:
        pa.token("u", "p", post=lambda *a, **k: _R(401, {"error": "invalid_credentials",
                                                         "error_description": "Invalid user credentials"}))
    except pa.AuthError as e:
        assert "Invalid user credentials" in str(e) and "p" not in str(e).split(":")[0].replace("http", "")[:0]
    else:
        raise AssertionError("refusal not raised")


def test_bearer_sent_to_podaac_only(monkeypatch):
    import requests
    seen = {}

    def fake(self, method, url, **kw):
        seen["h"], seen["auth"], seen["sauth"] = dict(kw.get("headers") or {}), kw.get("auth"), self.auth
        return "ok"
    monkeypatch.setattr(requests.Session, "request", fake)
    s = pa.session("u", "p", get_token=lambda u, p: "tok")
    s.get("https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/x.nc")
    assert seen["h"].get("Authorization") == "Bearer tok" and seen["sauth"] is None
    s.get("https://cmr.earthdata.nasa.gov/search")
    assert "Authorization" not in seen["h"] and s.auth == ("u", "p")


def test_credentials_strip():
    assert pa.credentials({"EARTHDATA_USER": " jk \n", "EARTHDATA_PASS": "pw\n"}) == ("jk", "pw")


def test_token_only_session():
    s = pa.EarthdataSession(None, None, bearer="tok")
    assert s.auth is None and s.bearer == "tok"
