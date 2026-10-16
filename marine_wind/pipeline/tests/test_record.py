"""Offline tests for record.py (run: python3 -m pytest marine_wind/pipeline/tests)."""
import io
import os
import sys
import types
import zipfile

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("MARINE_DOMAIN", "glob")
import record  # noqa: E402

CYC = "2026101012"


def sample():
    rng = np.random.default_rng(1)
    vals = {"wind": rng.random((9, 12), dtype=np.float32) * 50, "hazard": rng.integers(0, 8, (9, 12)).astype(np.uint8),
            "p34": rng.random((9, 12)) * 100}   # float64 in, float32 out
    stats = dict(step=24, members=80, core_model=True, lows=[dict(r=4, c=5, p=990.5)])
    extra = {"gefs_mean": rng.random((9, 12), dtype=np.float32), "ens_mean": None, "aifsens_mean": None}
    return vals, stats, extra


def test_round_trip(tmp_path):
    vals, stats, extra = sample()
    record.save(str(tmp_path), CYC, 24, vals, stats, extra)
    v, s, e = record.load(str(tmp_path), CYC, 24)
    assert s == stats and set(v) == set(vals)
    assert v["hazard"].dtype == np.uint8 and np.array_equal(v["hazard"], vals["hazard"])
    assert v["wind"].dtype == np.float32 and np.array_equal(v["wind"], vals["wind"])
    assert v["p34"].dtype == vals["p34"].dtype and np.array_equal(v["p34"], vals["p34"])
    assert set(e) == set(record.EXTRAS) and e["ens_mean"] is None and e["aifsens_mean"] is None
    assert np.array_equal(e["gefs_mean"], extra["gefs_mean"])
    with pytest.raises(ValueError):
        record.load(str(tmp_path), "2026101000", 24)


def fake_build(calls):
    b = types.ModuleType("build")
    def step_values(ymd, hh, step):
        calls.append((ymd, hh, step))
        return "built"
    b.step_values = step_values
    return b


def test_fallback_without_token(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "build", fake_build(calls))
    monkeypatch.setenv("RECORD_CACHE", str(tmp_path))
    for k in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert record.load_or_build(CYC, 48) == "built" and calls == [("20261010", "12", 48)]


def test_cache_hit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "build", fake_build(calls))
    monkeypatch.setenv("RECORD_CACHE", str(tmp_path))
    vals, stats, extra = sample()
    record.save(str(tmp_path / CYC), CYC, 24, vals, stats, extra)
    v, s, e = record.load_or_build(CYC, 24)
    assert not calls and np.array_equal(v["wind"], vals["wind"])


class Resp:
    def __init__(self, js=None, content=b""):
        self.js, self.content = js, content
    def raise_for_status(self):
        pass
    def json(self):
        return self.js


def test_artifact(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "build", fake_build(calls))
    monkeypatch.setenv("RECORD_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    vals, stats, extra = sample()
    src = tmp_path / "src"
    record.save(str(src), CYC, 24, vals, stats, extra)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for ext in (".npz", ".json"):
            z.write(src / ("f024" + ext), "f024" + ext)
    seen = []
    def get(url, **kw):
        seen.append((url, kw))
        if url.endswith("/actions/artifacts"):
            assert kw["params"]["name"] == "forecast-record-%s-f024" % CYC
            return Resp({"artifacts": [
                {"archive_download_url": "https://x/old", "created_at": "2026-10-10T01:00:00Z", "expired": False},
                {"archive_download_url": "https://x/new", "created_at": "2026-10-10T20:00:00Z", "expired": False},
                {"archive_download_url": "https://x/exp", "created_at": "2026-10-11T20:00:00Z", "expired": True}]})
        assert url == "https://x/new" and kw["headers"]["Authorization"] == "Bearer t"
        return Resp(content=buf.getvalue())
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get))
    v, s, e = record.load_or_build(CYC, 24)
    assert not calls and s == stats and np.array_equal(v["wind"], vals["wind"])
    n = len(seen)
    record.load_or_build(CYC, 24)   # now from the cache
    assert len(seen) == n


def test_artifact_error_falls_back(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "build", fake_build(calls))
    monkeypatch.setenv("RECORD_CACHE", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    def get(url, **kw):
        raise OSError("down")
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get))
    assert record.load_or_build(CYC, 24) == "built" and calls


def test_crop(monkeypatch):
    """The Atlantic box (95W-10E) cut from the global record, whose columns start at 180W."""
    col = np.tile(np.arange(1440, dtype=np.float32), (721, 1))
    vals, extra = {"wind": col}, {"gefs_mean": col, "ens_mean": None, "aifsens_mean": None}
    ix = (int(round((-95.0 % 360) * 4)) + np.arange(421)) % 1440      # as domain.py: counts from 0E
    dom = types.SimpleNamespace(GLOBAL=False, IY=slice(92, 289), IX=ix, NY=197, NX=421)
    monkeypatch.setitem(sys.modules, "domain", dom)
    lows = [dict(r=150, c=400, p=1), dict(r=150, c=1000, p=2), dict(r=150, c=341, p=3), dict(r=93, c=400, p=4)]
    v, s, e = record._crop(vals, {"lows": lows}, extra)
    assert v["wind"].shape == (197, 421) and e["ens_mean"] is None
    assert v["wind"][0, 0] == 340 and v["wind"][0, -1] == 760     # 95W and 10E in the global record
    assert s["lows"] == [dict(r=58, c=60, p=1)]   # 1000 off the box, 341 and row 93 too near its edge
