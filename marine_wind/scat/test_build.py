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


if __name__ == "__main__":
    n = 0
    for name, f in sorted(globals().items()):
        if name.startswith("test_"):
            f()
            n += 1
    print("%d tests passed" % n)
