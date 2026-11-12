"""Offline tests of build.py: python3 test_build.py"""
import datetime as dt
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build as b  # noqa: E402

D = dt.datetime


def pts(rows):
    r = np.array(rows, np.float32)
    u, v = r[:, 2], r[:, 3]
    return dict(lat=r[:, 0], lon=r[:, 1], u=u, v=v, spd=np.hypot(u, v), q=r[:, 4].astype(np.uint8))


def test_grid_mean_flag_direction():
    # two unflagged points in one cell (speeds 5 and 10, both from the south), one flagged strong one;
    # a second cell with only a flagged point; a third cell outside 15-70N
    p = pts([(50.01, -30.01, 0, 5, 0), (49.99, -29.99, 0, 10, 0), (50.0, -30.0, 0, 40, 1),
             (51.0, -30.0, -3, -4, 1), (5.0, -30.0, 3, 4, 0)])
    idx, spd, d, flag = b.grid_points(p)
    assert idx.tolist() == sorted(idx.tolist()) and len(idx) == 2
    c = int(round((90 - 50) * 4)) * 1440 + int(round((-30 + 180) * 4))
    assert idx[1] == c or idx[0] == c
    i = list(idx).index(c)
    assert abs(spd[i] - 7.5) < 1e-4 and flag[i] == 0 and abs(d[i] - 180) < 1e-3   # from the south
    j = 1 - i
    assert abs(spd[j] - 5) < 1e-4 and flag[j] == 1 and abs(d[j] - np.degrees(np.arctan2(3, 4))) < 1e-3   # all flagged: mean of all


def test_direction_convention():
    for u, v, want in ((0, -10, 0), (-10, 0, 90), (0, 10, 180), (10, 0, 270)):
        _, _, d, _ = b.grid_points(pts([(40.0, 0.0, u, v, 0)]))
        assert abs(d[0] - want) < 1e-3, (u, v, d)


def test_lon_wrap_and_boxes():
    idx, *_ = b.grid_points(pts([(40.0, 190.0, 1, 1, 0), (40.0, -170.0, 1, 1, 0)]))
    assert idx.size == 1   # 190E is 170W
    m = b.box_mask("npac")
    iy = (90 - 40) * 4
    assert m[iy, (-170 + 180) * 4 % 1440] and m[iy, (140 + 180) * 4] and not m[iy, (100 + 180) * 4] and not m[iy, (-100 + 180) * 4]
    assert b.box_mask("natl")[iy, (0 + 180) * 4] and not b.box_mask("natl")[iy, (11 + 180) * 4]
    r, c = b.box_pos("npac", np.array([iy * 1440 + (-170 + 180) * 4]))
    assert r[0] == (67 - 40) * 4 and c[0] == (190 - 135) * 4
    r, c = b.box_pos("natl", np.array([iy * 1440 + (-95 + 180) * 4]))
    assert r[0] == (67 - 40) * 4 and c[0] == 0


def test_decode_roundtrip():
    import gzip
    a = (np.arange(721 * 1440) * 7 % 256).astype(np.uint8).reshape(721, 1440)
    diff = np.diff(a, axis=1, prepend=np.uint8(0)).astype(np.uint8)
    assert (b.decode_field(gzip.compress(diff.tobytes()), 2) == a).all()


def cyc(name, built):
    return dict(built=built, best_scale=2, dir="")


def test_lead_selection():
    cycles = {"2026111100": cyc("", D(2026, 11, 11, 8, 40)), "2026111106": cyc("", D(2026, 11, 11, 14, 40)),
              "2026111200": cyc("", D(2026, 11, 12, 8, 47)), "2026111012": cyc("", D(2026, 11, 10, 20, 40)),
              "2026111018": cyc("", D(2026, 11, 11, 2, 40))}
    s = b.pick_leads(cycles, D(2026, 11, 12, 11, 10))
    assert s["latest"] == ("2026111200", 12)            # 11.2 h -> 12
    assert s["f24"] is None             # V = 12Z: the 12Z run of the 11th is not cached and s["f48"] == ("2026111012", 48)
    s = b.pick_leads(cycles, D(2026, 11, 12, 1, 0))      # before the 00Z run was built: the newest built is 06Z of the 11th
    assert s["latest"] == ("2026111106", 18)             # 18.9 h -> 18
    assert s["f24"] == ("2026111100", 24) and s["f48"] is None   # V = 00Z of the 12th
    s = b.pick_leads(cycles, D(2026, 11, 12, 20, 0))
    assert s["latest"] == ("2026111200", 18)             # 20 h -> 18
    s = b.pick_leads(cycles, D(2026, 11, 14, 9, 0))      # 57 h: past step 54
    assert s["latest"] is None
    s = b.pick_leads(cycles, D(2026, 11, 11, 3, 0))      # only the 10th's 12Z and 18Z runs are built; 9 h after 18Z: a tie goes up
    assert s["latest"] == ("2026111018", 12)
    assert b.pick_leads({}, D(2026, 11, 12, 0, 0)) == dict(latest=None, f24=None, f48=None)


def test_synoptic_nearest():
    assert b._nearest_synoptic(D(2026, 11, 12, 2, 59)) == D(2026, 11, 12, 0)
    assert b._nearest_synoptic(D(2026, 11, 12, 3, 0)) == D(2026, 11, 12, 6)
    assert b._nearest_synoptic(D(2026, 11, 12, 22, 0)) == D(2026, 11, 13, 0)


def test_scores():
    obs = np.array([30, 36, 40, 50, 66, 70], np.float32)
    flag = np.array([0, 0, 0, 0, 0, 1], np.uint8)       # the 70 is flagged: ignored
    grid = np.array([36, 30, 50, 50, 60, 90], np.float32)
    warn = np.array([0, 1, 1, 2, 4, 7], np.uint8)
    s = b.score(obs, flag, grid, warn)
    assert s["obs"] == [4, 2, 1] and s["grid"] == [4, 3, 0] and s["obs_max"] == 66.0 and s["grid_max"] == 60.0
    assert s["catch"] == [4, 2, 1]       # 36 and 40 in the gale line, 50 in storm, 66 in HF
    assert s["line"] == [4, 2, 1]
    e = b.score(obs[5:], flag[5:], grid[5:], warn[5:])   # nothing unflagged
    assert e["obs"] == [0, 0, 0] and e["obs_max"] == 0.0


def test_bin_roundtrip():
    idx = np.array([5, 900, 70000], np.int64)
    spd, d, flag = np.array([10.4, 300.0, 33.5], np.float32), np.array([0, 179.2, 359.9], np.float32), np.array([0, 1, 0], np.uint8)
    leads = {"latest": (np.array([12.6, 40.0, 255.0], np.float32), np.array([0, 3, 7], np.uint8)), "f24": None, "f48": None}
    u = b.unpack_pass(b.pack_pass(idx, spd, d, flag, leads))
    assert u["idx"].tolist() == [5, 900, 70000]
    assert u["obs"].tolist() == [10, 254, 34]              # capped at 254; 33.5 rounds to even
    assert u["dir"].tolist() == [0, 90, 0]                 # 359.9 / 2 = 180 wraps to 0
    assert u["flag"].tolist() == [0, 1, 0]
    assert u["leads"]["latest"][0].tolist() == [13, 40, 254] and u["leads"]["latest"][1].tolist() == [0, 3, 7]
    assert (u["leads"]["f24"][0] == 255).all() and (u["leads"]["f48"][1] == 255).all()


def test_oscat_time_fix_and_grouping():
    t0 = D(2026, 11, 11, 0, 0)
    oscat = []
    for k in range(12):      # a good stamp every 100 minutes, orbit number 20900 + k
        oscat.append(("oscat3_AS", "/x/oscat3_2026315_%d_%d_SN_2026-315T00-00-00_lite5.json" % (20900 + k, 20901 + k), t0 + dt.timedelta(minutes=100 * k)))
    # orbits 20912..20914 stamped within a minute of each other, hours after their time
    late = D(2026, 11, 12, 6, 0)
    for k in range(3):
        oscat.append(("oscat3_AS", "/x/oscat3_2026315_%d_%d_SN_x_lite5.json" % (20912 + k, 20913 + k), late + dt.timedelta(seconds=5 * k)))
    fixed = b.fix_oscat_times(oscat)
    assert len(fixed) == 15
    est = {b._orbit(f[1]): f[2] for f in fixed}
    for k in range(15):
        assert abs((est[20900 + k] - (t0 + dt.timedelta(minutes=100 * k))).total_seconds()) <= 120, k
    ps = b.group_passes(fixed)
    assert len(ps) == 15 and ps[0]["start"] > ps[-1]["start"]       # an OSCAT file is a pass
    assert ps[0]["end"] - ps[0]["start"] == dt.timedelta(minutes=55)
    # UHR chunks: 3 within 20 min of the previous one, then a new pass
    uhr = [("UHR_METOP-B_AS", "/x/UHR_METOP-B_AS_%s_1_rev1of1_ec.json" % s.strftime("%Y%m%dT%H%M%S"), s)
           for s in (D(2026, 11, 11, 2, 22), D(2026, 11, 11, 2, 24), D(2026, 11, 11, 2, 40), D(2026, 11, 11, 4, 7))]
    ps = b.group_passes(uhr)
    assert [len(p["files"]) for p in ps] == [1, 3]
    assert ps[1]["id"] == "20261111T0222-UHR_METOP-B_AS" and ps[1]["end"] == D(2026, 11, 11, 2, 50)
    assert len({p["key"] for p in ps}) == 2



def make_cache(tmp, cycle="2026111200", built="2026-11-12T08:47Z"):
    import json
    d = os.path.join(tmp, "cache", cycle)
    os.makedirs(d)
    for k in b.BOXES:
        iy0, ny, ix0, nx = b.box_cols(k)
        np.savez_compressed(os.path.join(d, k + ".npz"), **{"%s%03d" % (n, st): np.full((ny, nx), 80 if n == "best" else 1, np.uint8)
                                                           for n in ("best", "warn") for st in b.STEPS})
    json.dump(dict(cycle=cycle, built=built, best_scale=2, warn_scale=1), open(os.path.join(d, "meta.json"), "w"))
    return os.path.join(tmp, "cache")


def test_records_partial_cycles_and_misses():
    import tempfile
    now = D(2026, 11, 12, 12, 0)
    with tempfile.TemporaryDirectory() as tmp:
        cache = make_cache(tmp)
        cycles = b.load_cycles(cache)
        calls = []

        def fetch(c, step):
            calls.append((c, step))
            if c == "2026111018":
                return "none"
            if c == "2026111012":
                return "nobest"
            return np.full((721, 1440), 100, np.uint8), np.full((721, 1440), 4, np.uint8)
        wants = [("2026111112", 24), ("2026111018", 48), ("2026111012", 48), ("2026111200", 24), ("2026111100", 24), ("2026111100", 24)]
        n = b.ensure_records(cache, cycles, wants, now, 10, fetch)
        assert n == 2 and calls == [("2026111112", 24), ("2026111018", 48), ("2026111012", 48), ("2026111100", 24)]   # cached cycle and the duplicate skipped
        cyc = b.load_cycles(cache)
        assert cyc["2026111112"]["steps"] == [24] and cyc["2026111112"]["partial"] and not cyc["2026111200"]["partial"]
        # a partial cycle is never the "latest" run, and serves f24 only for its step
        s = b.pick_leads(cyc, D(2026, 11, 12, 12, 0))
        assert s["latest"][0] == "2026111200" and s["f24"] == ("2026111112", 24) and s["f48"] is None
        fc = b.Forecasts(cyc)
        r, c = b.box_pos("natl", np.array([(90 - 50) * 1440 + (-30 + 180) * 4]))
        assert fc.field("2026111112", "natl", "best", 24)[r, c][0] == 100 and fc.field("2026111112", "natl", "warn", 24)[r, c][0] == 4
        # misses: not asked again within a day, asked again after; "nobest" never
        calls.clear()
        assert b.ensure_records(cache, cyc, wants, now + dt.timedelta(hours=1), 10, fetch) == 0 and calls == []
        b.ensure_records(cache, cyc, wants, now + dt.timedelta(days=1, hours=1), 10, fetch)
        assert calls == [("2026111018", 48)]
        # budget
        calls.clear()
        os.remove(os.path.join(cache, "record_misses.json"))
        shutil_rm = __import__("shutil").rmtree
        shutil_rm(os.path.join(cache, "2026111112"))
        b.ensure_records(cache, b.load_cycles(cache), [("2026111112", 24), ("2026111106", 24), ("2026111100", 48)], now, 2, fetch)
        assert len(calls) == 2
        # an old cycle (artifacts last 14 days) is not asked for
        calls.clear()
        b.ensure_records(cache, cyc, [("2026102000", 24)], now, 5, fetch)
        assert calls == []


def test_prune_shrinks_then_drops():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cache = make_cache(tmp, "2026110700", "2026-11-07T08:47Z")
        b.prune(cache, D(2026, 11, 12, 12, 0))      # 5.5 days: steps 24 and 48 only
        c = b.load_cycles(cache)["2026110700"]
        assert c["steps"] == [24, 48] and c["partial"]
        with np.load(os.path.join(cache, "2026110700", "natl.npz")) as z:
            assert sorted(z.files) == ["best024", "best048", "warn024", "warn048"]
        b.prune(cache, D(2026, 11, 20, 0, 0))
        assert b.load_cycles(cache) == {}


def test_rescore_fills_a_null_lead():
    import tempfile
    import json
    with tempfile.TemporaryDirectory() as tmp:
        cache = os.path.join(tmp, "cache")      # the f24 cycle of a pass at 2026-11-12 00Z, only from a record
        os.makedirs(cache)
        b.store_step(cache, "2026111100", 24, np.full((721, 1440), 90, np.uint8), np.full((721, 1440), 2, np.uint8))
        cycles = b.load_cycles(cache)
        fc = b.Forecasts(cycles)
        idx = np.array([(90 - 50) * 1440 + (-30 + 180) * 4 + i for i in range(3)], np.int64)
        obs, flag = np.array([40, 50, 20], np.float32), np.array([0, 0, 1], np.uint8)
        pdir = os.path.join(tmp, "pass")
        os.makedirs(pdir)
        latest = (np.array([30, 31, 32], np.float32), np.array([1, 1, 1], np.uint8))
        open(os.path.join(pdir, "x-natl.bin"), "wb").write(b.pack_pass(idx, obs, np.zeros(3, np.float32), flag, {"latest": latest, "f24": None, "f48": None}))
        e = dict(id="x", basin="natl", start="2026-11-11T23:50Z", mid="2026-11-12T00:00Z", file="pass/x-natl.bin",
                 fc=dict(latest=b.lead_info(("2026111100", 24)), f24=None, f48=None), score=dict(latest={"keep": 1}, f24=None, f48=None))
        assert b.rescore([e], cycles, fc, pdir, tmp, "2026-11-01T00:00Z") == 1
        assert e["fc"]["f24"]["cycle"] == "2026111100" and e["fc"]["f24"]["valid"] == "2026-11-12T00:00Z" and e["fc"]["f48"] is None
        assert e["score"]["latest"] == {"keep": 1}
        assert e["score"]["f24"]["grid"] == [2, 0, 0]       # 45 kt on the two unflagged cells: 34 yes, 48 no
        assert e["score"]["f24"]["catch"] == [2, 1, 0] and e["score"]["f24"]["line"] == [2, 2, 0]   # warn 2 = storm line
        u = b.unpack_pass(open(os.path.join(pdir, "x-natl.bin"), "rb").read())
        assert u["leads"]["f24"][0].tolist() == [45, 45, 45] and u["leads"]["f24"][1].tolist() == [2, 2, 2]
        assert u["leads"]["latest"][0].tolist() == [30, 31, 32] and (u["leads"]["f48"][0] == 255).all()
        assert u["obs"].tolist() == [40, 50, 20] and u["flag"].tolist() == [0, 0, 1]
        assert b.rescore([e], cycles, fc, pdir, tmp, "2026-11-01T00:00Z") == 0


def _entry(pid, sat, mid, basin="natl"):
    return dict(id=pid, basin=basin, sat=sat, mid=mid, file="pass/%s-%s.bin" % (pid, basin))


def _unp(cells, obs, flag=None):
    n = len(cells)
    return dict(idx=np.array(cells, np.uint32), obs=np.array(obs, np.uint8), dir=np.full(n, 20, np.uint8),
                flag=np.array(flag if flag is not None else [0] * n, np.uint8))


def test_mosaic_window_membership():
    v = D(2026, 11, 12, 12, 0)
    es = [_entry("a", "Metop-B", "2026-11-12T09:00Z"), _entry("b", "OSCAT-3", "2026-11-12T15:00Z"),
          _entry("c", "Metop-C", "2026-11-12T15:01Z"), _entry("d", "Metop-C", "2026-11-12T08:59Z"),
          _entry("e", "Metop-C", "2026-11-12T12:00Z", "npac"), _entry("f", "Metop-C", "2026-11-12T11:00Z")]
    assert [e["id"] for e in b.window_entries(es, "natl", v)] == ["a", "f", "b"]   # +-3 h inclusive, by middle time
    assert [e["id"] for e in b.window_entries(es, "npac", v)] == ["e"]
    ts = b.mosaic_times(D(2026, 11, 12, 14, 30))
    assert ts[0] == D(2026, 11, 12, 12) and ts[1] == D(2026, 11, 12, 6) and len(ts) == 27 and ts[-1] == D(2026, 11, 6, 0)
    assert len(b.mosaic_times(D(2026, 11, 12, 12, 10))) == 28   # 27 or 28 times: the oldest keeps all its passes


def test_mosaic_nearest_to_v_wins_tie_newer():
    v = D(2026, 11, 12, 12, 0)
    far = (_entry("far", "Metop-B", "2026-11-12T09:30Z"), _unp([100, 101, 102], [10, 11, 12]))
    near = (_entry("near", "Metop-C", "2026-11-12T11:30Z"), _unp([101, 102, 103], [20, 21, 22]))
    late = (_entry("late", "Metop-C", "2026-11-12T12:30Z"), _unp([102, 103, 104], [30, 31, 32]))
    members = [far, near, late]       # in mid order
    idx, obs, dr, fl, pi = b.stitch(v, members)
    assert idx.tolist() == [100, 101, 102, 103, 104]
    # 100: far only; 101: near beats far; 102 and 103: near and late are both 30 min away, the newer (late) wins; 104: late
    assert obs.tolist() == [10, 20, 30, 31, 32] and pi.tolist() == [0, 1, 2, 2, 2]
    # ASCAT beats OSCAT-3 where they overlap, even when the OSCAT-3 pass is nearer V
    osc = (_entry("osc", "OSCAT-3", "2026-11-12T12:00Z"), _unp([100, 105], [40, 41]))
    idx, obs, dr, fl, pi = b.stitch(v, [far, osc])
    assert idx.tolist() == [100, 101, 102, 105] and obs.tolist() == [10, 11, 12, 41] and pi.tolist() == [0, 0, 0, 1]


def test_mosaic_lead_selection_at_v():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cache = os.path.join(tmp, "cache")
        os.makedirs(cache)
        full = np.zeros((721, 1440), np.uint8)
        for c, built in (("2026111200", "2026-11-12T04:00Z"), ("2026111206", "2026-11-12T10:00Z"), ("2026111212", "2026-11-12T16:00Z")):
            d = os.path.join(cache, c)
            os.makedirs(d)
            for k in b.BOXES:
                np.savez_compressed(os.path.join(d, k + ".npz"), **{"%s%03d" % (n, s): full for n in ("best", "warn") for s in b.STEPS})
            import json
            json.dump(dict(cycle=c, built=built, best_scale=2, warn_scale=1), open(os.path.join(d, "meta.json"), "w"))
        b.store_step(cache, "2026111112", 24, full, full)     # a partial cycle: f24 for V = 12Z on the 12th
        cycles = b.load_cycles(cache)
        sel = b.pick_leads(cycles, D(2026, 11, 12, 12, 0))
        # the 06Z run was built at 10Z, before V; the 12Z run only at 16Z: the desk had the 06Z run, step 6
        assert sel["latest"] == ("2026111206", 6) and sel["f24"] == ("2026111112", 24) and sel["f48"] is None
        assert b.pick_leads(cycles, D(2026, 11, 12, 18, 0))["latest"] == ("2026111212", 6)
        assert b.pick_leads(cycles, D(2026, 11, 12, 0, 0))["latest"] is None   # nothing built by 00Z in the cache


def test_mosaic_bin_round_trip_and_ascat_only_score():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cache = os.path.join(tmp, "cache")
        os.makedirs(cache)
        best = np.full((721, 1440), 60, np.uint8)         # 30 kt everywhere ...
        warn = np.zeros((721, 1440), np.uint8)
        best[:, :] = 80                                     # ... 40 kt
        warn[:, :] = 1
        b.store_step(cache, "2026111112", 24, best, warn)
        cycles = b.load_cycles(cache)
        fc = b.Forecasts(cycles)
        v = D(2026, 11, 12, 12, 0)
        iy = (90 - 50) * 1440 + (-30 + 180) * 4
        # the ASCAT pass sees 3 cells (50, 36, 20 kt; the last flagged), OSCAT sees 2 others (30 and 52 kt)
        a = (_entry("asc", "Metop-B", "2026-11-12T11:00Z"), _unp([iy, iy + 1, iy + 2], [50, 36, 20], [0, 0, 1]))
        o = (_entry("osc", "OSCAT-3", "2026-11-12T12:30Z"), _unp([iy + 3, iy + 4], [30, 52]))
        water = np.ones((721, 1440), bool)
        wb = b.crop_box(water & b.box_mask("natl"), "natl")
        wb[0, 0] = False                                   # one cell of the box is land
        sel = b.pick_leads(cycles, v)
        blob, ent = b.build_mosaic("natl", v, [a, o], sel, fc, wb)
        assert ent["passes"] == ["asc", "osc"] and ent["n"] == 5 and ent["flagged"] == 1 and ent["obs_max"] == 52.0
        assert ent["sats"] == {"ASCAT": 3, "OSCAT-3": 2} and ent["water"] == int(wb.sum())
        assert ent["fc"]["latest"] is None and ent["fc"]["f48"] is None and ent["fc"]["f24"] == dict(cycle="2026111112", step=24)
        assert ent["score"]["latest"] is None and ent["score_ascat"]["latest"] is None
        s, sa = ent["score"]["f24"], ent["score_ascat"]["f24"]
        assert s["obs"] == [3, 2, 0] and s["grid"] == [4, 0, 0] and s["catch"] == [3, 0, 0]   # unflagged 50, 36, 30, 52 kt; grid 40, gale line only
        assert sa["obs"] == [2, 1, 0] and sa["grid"] == [2, 0, 0] and sa["obs_max"] == 50.0 and sa["grid_max"] == 40.0 and sa["catch"] == [2, 0, 0]
        assert ent["grid_area_box"]["f24"] == [int(wb.sum()), 0, 0] and ent["grid_area_box"]["latest"] is None
        u = b.unpack_mosaic(blob, ent)
        assert u["idx"].tolist() == [iy + i for i in range(5)] and u["obs"].tolist() == [50, 36, 20, 30, 52]
        assert u["flag"].tolist() == [0, 0, 1, 0, 0] and u["pass_"].tolist() == [0, 0, 0, 1, 1] and list(u["leads"]) == ["f24"]
        g, w = u["leads"]["f24"]
        assert g.shape == (ent["box"]["ny"], ent["box"]["nx"]) and g[1, 1] == 40 and w[1, 1] == 1
        assert g[0, 0] == 255 and w[0, 0] == 255               # land: none


if __name__ == "__main__":
    n = 0
    for name, f in sorted(globals().items()):
        if name.startswith("test_"):
            f()
            n += 1
    print("%d tests passed" % n)
