import os
import sys

import eccodes
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nwp  # noqa: E402
from nwp import cycles, http, index  # noqa: E402

IDX = """1:0:d=2026101500:PRMSL:mean sea level:24 hour fcst:
2:100:d=2026101500:UGRD:10 m above ground:24 hour fcst:
3:250:d=2026101500:UGRD:10 m above ground:24 hour fcst:ens
4:400:d=2026101500:MSLET:mean sea level:24 hour fcst:
"""


class R:
    def __init__(self, text="", code=200, content=b"", headers=None):
        self.text, self.status_code, self.content, self.headers = text, code, content, headers or {}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    index.forget()
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def fake_get(monkeypatch, table):
    calls = []

    def g(url, rng=None, tries=8):
        calls.append((url, rng))
        return table.get(url)
    monkeypatch.setattr(index, "get", g)
    return calls


def test_ncep_index_first_wins_and_open_end(monkeypatch):
    fake_get(monkeypatch, {"u.idx": R(IDX)})
    idx = index.ncep_index("u")
    assert idx["UGRD:10 m above ground"] == (100, 249)
    assert idx["PRMSL:mean sea level"] == (0, 99)
    assert idx["MSLET:mean sea level"] == (400, None)
    recs = index.ncep_records("u")
    assert [r[0] for r in recs].count("UGRD:10 m above ground") == 2 and recs[-1][2] is None


def test_index_missing_is_none(monkeypatch):
    fake_get(monkeypatch, {})
    assert index.ncep_index("u") is None and index.ec_records("b") is None


def test_ncep_mslet_fallback(monkeypatch):
    idx = IDX.replace("PRMSL", "XXXX")
    fake_get(monkeypatch, {"u.idx": R(idx)})
    seen = []
    monkeypatch.setattr(nwp, "get", lambda url, rng: seen.append(rng) or R(content=b"x"))
    monkeypatch.setattr(nwp, "decode", lambda blob, crop=None: np.zeros(1))
    out = nwp.ncep("u", {"PRMSL:mean sea level": "msl"})
    assert seen == [(400, None)] and "msl" in out
    assert nwp.ncep("u", {"PRMSL:mean sea level": "p"}) is None


def test_record_missing_after_index(monkeypatch):
    """Index posted, record 404 (a half-posted file): None, not a crash, and the index is re-read next time."""
    calls = fake_get(monkeypatch, {"u.idx": R(IDX), "b.index": R('{"param":"10u","levtype":"sfc","_offset":10,"_length":5}')})
    monkeypatch.setattr(nwp, "get", lambda url, rng: None)
    assert nwp.ncep("u", {"UGRD:10 m above ground": "u"}) is None
    nwp.ncep_index("u")
    assert [c[0] for c in calls].count("u.idx") == 2
    assert nwp.ec_fields("b", {("sfc", "10u", None): "u"}) == {}


def test_index_read_once_and_bounded(monkeypatch):
    calls = fake_get(monkeypatch, {"u.idx": R(IDX)})
    index.ncep_index("u"); index.ncep_records("u")
    assert len(calls) == 1
    monkeypatch.setattr(index, "MAXURLS", 3)
    fake_get(monkeypatch, {"f%d.idx" % i: R(IDX) for i in range(10)})
    for i in range(10):
        index.ncep_index("f%d" % i)
    assert len(index._cache) == 3 and "f9.idx" in index._cache


def test_ec_records_and_span(monkeypatch):
    txt = '{"param":"10u","levtype":"sfc","_offset":10,"_length":5}\n\nnot json\n'
    fake_get(monkeypatch, {"b.index": R(txt)})
    recs = index.ec_records("b")
    assert len(recs) == 1 and index.span(recs[0]) == (10, 14)


def test_ec_fields_select(monkeypatch):
    txt = ('{"param":"10u","levtype":"sfc","_offset":0,"_length":5}\n'
           '{"param":"u","levtype":"pl","levelist":"850","_offset":5,"_length":5}\n'
           '{"param":"u","levtype":"pl","levelist":"500","_offset":10,"_length":5}\n')
    fake_get(monkeypatch, {"b.index": R(txt)})
    rngs = []
    monkeypatch.setattr(nwp, "get", lambda url, rng: rngs.append(rng) or R(content=b"x"))
    monkeypatch.setattr(nwp, "decode", lambda blob, crop=None: np.zeros(1))
    out = nwp.ec_fields("b", {("sfc", "10u", None): "u", ("pl", "u", "850"): "u850"})
    assert set(out) == {"u", "u850"} and rngs == [(0, 4), (5, 9)]


def msg(lat_first, lon_first, ni=8, nj=4):
    h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    for k, v in (("Ni", ni), ("Nj", nj), ("latitudeOfFirstGridPointInDegrees", lat_first),
                 ("latitudeOfLastGridPointInDegrees", -lat_first), ("longitudeOfFirstGridPointInDegrees", lon_first),
                 ("longitudeOfLastGridPointInDegrees", lon_first + 360 - 360 / ni), ("iDirectionIncrementInDegrees", 360 / ni),
                 ("jDirectionIncrementInDegrees", 2 * abs(lat_first) / (nj - 1)),
                 ("jScansPositively", 0 if lat_first > 0 else 1)):
        eccodes.codes_set(h, k, v)
    eccodes.codes_set_values(h, np.arange(ni * nj, dtype=float))
    blob = eccodes.codes_get_message(h)
    eccodes.codes_release(h)
    return blob


def test_decode_orientation_and_crop():
    base = np.arange(32, dtype=np.float32).reshape(4, 8)
    v = nwp.decode(msg(45, 0))                     # north first, lon 0
    assert v.dtype == np.float32 and np.array_equal(v, base)
    v = nwp.decode(msg(-45, 0))                    # south first: flipped
    assert np.array_equal(v, base[::-1])
    v = nwp.decode(msg(45, 180))                   # starts at -180 (stored 180): rolled
    assert np.array_equal(v, np.roll(base, 4, axis=1))
    iy, ix = slice(1, 3), np.array([6, 7, 0])
    c = nwp.decode(msg(45, 0), (iy, ix))
    assert np.array_equal(c, base[iy, ix]) and c.flags.owndata


def test_get_semantics(monkeypatch):
    seq = []

    class S:
        def get(self, url, headers=None, timeout=None):
            seq.append(headers)
            r = resp.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    monkeypatch.setattr(http, "_session", S())
    resp = [R(code=503), R(code=500), http.requests.ConnectionError(), R(code=206, content=b"ok")]
    assert http.get("u", (5, None)).content == b"ok"
    assert seq[0] == {"Range": "bytes=5-"}
    resp[:] = [R(code=404)]
    assert http.get("u") is None
    resp[:] = [R(code=403)]
    assert http.get("u") is None
    resp[:] = [R(code=500)] * 3
    with pytest.raises(RuntimeError):
        http.get("u", tries=3)
    resp[:] = [R(code=503)] * 61
    with pytest.raises(RuntimeError):
        http.get("u")


def test_urls():
    s = nwp.sources
    assert s.gfs("20261015", "00", 24).endswith("gfs.20261015/00/atmos/gfs.t00z.pgrb2.0p25.f024")
    assert s.gdas("20261015", "00", 6).endswith("gdas.20261015/00/atmos/gdas.t00z.pgrb2.0p25.f006")
    assert s.gefs("20261015", "00", 24, "p05").endswith("pgrb2sp25/gep05.t00z.pgrb2s.0p25.f024")
    assert s.ecmwf("ifs", "oper", "fc", "20261015", "00", 24).endswith(
        "20261015/00z/ifs/0p25/oper/20261015000000-24h-oper-fc")


def test_ec_ens_sorted_members(monkeypatch):
    recs = [{"param": p, "levtype": "sfc", "number": n, "_offset": 0, "_length": 1}
            for n in (3, 1, 2) for p in ("10u", "10v")] + [{"param": "10u", "levtype": "sfc", "number": 9,
                                                            "_offset": 0, "_length": 1}]
    monkeypatch.setattr(nwp, "ec_records", lambda base: recs)
    monkeypatch.setattr(nwp, "get", lambda url, rng: R(content=b"x"))
    monkeypatch.setattr(nwp, "decode", lambda blob, crop=None: np.zeros((2, 2)))
    out = nwp.ec_ens("ifs", "20261015", "00", 24, {"10u": "u", "10v": "v"})
    assert out["u"].shape == (3, 2, 2) and list(out) == ["u", "v"]


def test_newest_cycle_and_wait(monkeypatch):
    monkeypatch.setattr(cycles, "exists", lambda u: u in ("a", "b"))
    assert cycles.newest_cycle(["c1", "c2"], lambda c: ["x"] if c == "c1" else ["a", "b"]) == "c2"
    assert cycles.newest_cycle(["c1"], lambda c: ["x"]) is None
    assert cycles.cycle_list(__import__("datetime").datetime(2026, 10, 15, 13, tzinfo=__import__("datetime").timezone.utc),
                             6, 3) == ["2026101512", "2026101506", "2026101500"]
    sigs = iter([("1", "a"), ("2", "b"), ("2", "b")])

    class S:
        def head(self, url, timeout=None):
            return R(headers=dict(zip(("Content-Length", "ETag"), next(sigs))))
    monkeypatch.setattr(cycles, "_session", S())
    assert cycles.wait_for_quiet("u", every=1, timeout=100, sleep=lambda s: None) is True
    t = iter(range(0, 1000, 60))
    monkeypatch.setattr(cycles, "_session", type("S", (), {"head": lambda s, u, timeout=None: R(headers={"ETag": str(next(t))})})())
    clock = iter(range(0, 10000, 30))
    assert cycles.wait_for_quiet("u", every=30, timeout=100, sleep=lambda s: None, clock=lambda: next(clock)) is False


def test_ndfd_issued_after(monkeypatch):
    import datetime as dt
    from nwp import ndfd
    snaps = {dt.date(2026, 10, 16): [(dt.datetime(2026, 10, 16, h, 8), "k%02d" % h) for h in (10, 13, 16, 19, 22)],
             dt.date(2026, 10, 17): [(dt.datetime(2026, 10, 17, 1, 6), "k01n"), (dt.datetime(2026, 10, 17, 4, 7), "k04n")]}
    monkeypatch.setattr(ndfd, "snapshots", lambda day, product="YCYZ98": snaps.get(day, []))
    assert ndfd.issued_after(dt.datetime(2026, 10, 16, 12, 30)) == "k13"
    assert ndfd.issued_after(dt.datetime(2026, 10, 16, 13, 8)) == "k13"          # at or after
    assert ndfd.issued_after(dt.datetime(2026, 10, 16, 22, 30)) == "k01n"        # next date
    assert ndfd.issued_after(dt.datetime(2026, 10, 16, 13, 9), within_h=1) is None
    assert ndfd.issued_after(dt.datetime(2026, 10, 18, 0, 0)) is None
