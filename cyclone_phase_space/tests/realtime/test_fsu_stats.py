"""fsu_stats: pairing our smoothed track with digitized FSU points, and
the statistics, on a small hand-made case whose answers are worked out
by hand below."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

import fsu_stats as fs
import track_cps as tc


def test_class_rule_matches_the_module():
    vals_b = [-5.0, 10.0, 10.0001, 30.0]
    vals_t = [-50.0, -0.001, 0.0, 40.0]
    for b, vl, vu in itertools.product(vals_b, vals_t, vals_t):
        want = tc.hc.hart_class(np.array([[b]]), np.array([[vl]]), np.array([[vu]]), np.array([[True]]))[0, 0]
        assert fs.hart_class(b, vl, vu) == int(want), (b, vl, vu)
    assert fs.hart_class(None, 1.0, 1.0) is None
    assert fs.hart_class(float("nan"), 1.0, 1.0) is None


def test_onset_completion_matches_the_collector():
    h = np.arange(0, 61, 6.0)
    b = np.array([0, 5, 9, 11, 20, 30, 40, 40, 40, 40, 40.0])
    vtl = np.array([50, -5, 30, 20, 10, 5, -1, -20, -40, -60, -80.0])
    assert fs.onset_completion(h, b, vtl) == tc.onset_completion(h, b, vtl) == (18.0, 36.0)


def make_track(hours, **cols):
    n = len(hours)
    t = {"fhr": np.array(hours, float), "valid": [f"v{h}" for h in hours]}
    for c in (*fs.TRACK_COLS, "motion_kt", "mslp_hpa"):
        t[c] = np.array(cols.get(c, [np.nan] * n), float)
    return t


def fsu_row(h, b, vtl, vtu, flag="verified/ok"):
    return {"hour": h, "valid": f"v{h}", "b": b, "vtl": vtl, "vtl2": vtl, "vtu": vtu, "e_b": 0.1, "e_vtl": 0.3,
            "e_vtu": 0.5, "flag1": flag, "flag2": flag}


def test_pair_rows_smooth_ours_and_pair_at_shared_hours():
    hours = [0, 6, 12, 18, 24]
    tr = make_track(hours, hb=[0, 10, 20, 30, 40], hvtl=[100, 100, 100, 100, 100], hvtu=[50, 50, 50, 50, 50],
                    hb_track=[5, 5, 5, 5, 5], hb_hart=[12, 12, 12, 12, 12], hvtl_hart=[90] * 5, hvtu_hart=[40] * 5,
                    motion_kt=[10, 10, 25, 25, 25], mslp_hpa=[990] * 5)
    dig = {"cycle": "2026100112", "storm": "X",
           "rows": [fsu_row(0, 8.0, 95.0, 45.0), fsu_row(12, 18.0, 110.0, -5.0), fsu_row(30, 1.0, 1.0, 1.0),
                    fsu_row(18, 30.0, -10.0, 60.0, flag="single/open")]}
    rows = fs.pair_rows(dig, tr, 5)
    assert [r["fhr"] for r in rows] == [0, 12, 18]  # 30 h is past our track
    r0, r12, r18 = rows
    # 24 h centered mean: at 0 h the frames 0, 6, 12 -> 10; at 12 h all five -> 20; at 18 h 6..24 -> 25
    assert r0["hb"] == pytest.approx(10.0) and r12["hb"] == pytest.approx(20.0) and r18["hb"] == pytest.approx(25.0)
    assert r0["verified"] and r12["verified"] and not r18["verified"]
    assert r0["class_fsu"] == 0 and r12["class_fsu"] == 3 and r18["class_fsu"] == 6
    assert r12["class_standard"] == 2  # B 20 > 10, both terms warm
    assert r12["class_hart"] == 2 and r12["hb_hart"] == pytest.approx(12.0)  # Hart's class uses hb_hart, not hb_track
    assert r0["motion_kt"] == 10 and r12["motion_kt"] == 25
    assert list(fs.BANDS) == ["hart", "standard"] and fs.BANDS["hart"]["b"] == "hb_hart"
    assert fs.PAIR_COLS.index("hb_hart") > fs.PAIR_COLS.index("hb_track")


def test_term_class_and_timing_statistics():
    hours = [0, 6, 12, 18, 24, 30]
    tr = make_track(hours, hb=[0, 0, 20, 20, 20, 20], hvtl=[50, 50, 50, -50, -50, -50], hvtu=[10] * 6,
                    hb_track=[0] * 6, hb_hart=[0] * 6, hvtl_hart=[50] * 6, hvtu_hart=[10] * 6,
                    motion_kt=[5, 5, 5, 30, 30, 30], mslp_hpa=[990] * 6)
    # running_mean would blur the step; use a 0 h window so the hand numbers stay simple
    orig = fs.running_mean
    fs.running_mean = lambda h, v, width_h=0.0: orig(h, v, 0.0)
    try:
        dig = {"cycle": "c", "storm": "s",
               "rows": [fsu_row(h, b, vl, 10.0) for h, b, vl in
                        zip(hours, [0, 0, 0, 20, 20, 20], [52, 52, 52, -46, -46, -46])]}
        rows = fs.pair_rows(dig, tr, 1)
    finally:
        fs.running_mean = orig
    T = fs.term_stats(rows)
    # B, standard: differences 0, 0, 20, 0, 0, 0 -> mean 3.33, RMS sqrt(400/6)
    s = T["standard"]["b"]["all"]
    assert s["n"] == 6 and s["mean"] == pytest.approx(20 / 6, abs=0.01)
    assert s["rms"] == pytest.approx(np.sqrt(400 / 6), abs=0.01)
    # -V_T^L, standard: warm (FSU 52) -2, -2, -2; cold (FSU -46) -4, -4, -4
    assert T["standard"]["vtl"]["warm_lower"]["mean"] == pytest.approx(-2.0)
    assert T["standard"]["vtl"]["cold_lower"]["mean"] == pytest.approx(-4.0)
    assert T["standard"]["vtl"]["fast_gt20kt"]["n"] == 3 and T["standard"]["vtl"]["slow_le20kt"]["n"] == 3
    # Hart: hvtl_hart 50 everywhere -> warm -2, cold +96
    assert T["hart"]["vtl"]["cold_lower"]["mean"] == pytest.approx(96.0)
    C = fs.class_stats(rows)
    # ours standard: 0,0,2,6,6,6 ; FSU: 0,0,0,6,6,6 (lower cold, upper warm) -> 5 of 6
    assert C["standard"]["all"]["agree"] == 5 and C["standard"]["all"]["n"] == 6
    # ours hart (B 0, warm): 0 everywhere -> 3 of 6
    assert C["hart"]["all"]["agree"] == 3
    tm = fs.timing_stats(rows)
    # onset: ours 12 h, FSU 18 h -> -6; completion: ours 18, FSU 18 -> 0
    assert tm["standard"]["onset_values"] == [-6.0]
    assert tm["standard"]["completion_values"] == [0.0]
    # Hart band choice: our B never crosses -> no onset pair; completion from the start: never (vtl 50)
    assert tm["hart"]["onset_values"] == [] and tm["hart"]["completion_values"] == []


def test_own_track_statistics_by_speed():
    t = make_track([0, 6, 12, 18], hb=[20, 0, 5, np.nan], hb_track=[5, 0, 5, 3], hb_hart=[15, 1, np.nan, 4],
                   hvtl=[10, 10, 10, 10], hvtu=[10, 10, 10, 10], hvtl_hart=[0, 0, 0, 0], hvtu_hart=[20, 20, 20, 20],
                   motion_kt=[5, 5, 35, 35])
    O = fs.own_stats([t])
    # hb_hart - hb_track: 10, 1, (blank), 1 -> mean 4, n 3; 15 against 5 is the one B-side disagreement
    assert O["hb_hart_minus_hb_track"]["n"] == 3 and O["hb_hart_minus_hb_track"]["mean"] == pytest.approx(4.0)
    assert O["hb_hart_vs_hb_track_b_side_differs"] == {"n": 3, "differ": 1, "rate": pytest.approx(1 / 3, abs=0.001)}
    assert O["by_motion_kt"][0]["hb_hart_minus_hb_track"]["n"] == 2
    assert O["by_motion_kt"][3]["hb_hart_minus_hb_track"]["n"] == 1
    slow = O["by_motion_kt"][0]
    assert slow["hb_minus_hb_track"]["n"] == 2 and slow["hb_minus_hb_track"]["mean"] == pytest.approx(7.5)
    assert slow["class_differs"]["differ"] == 1  # 20 vs 5 crosses 10 m
    fast = O["by_motion_kt"][3]
    assert fast["hb_minus_hb_track"]["n"] == 1 and fast["class_differs"]["differ"] == 0
    assert O["n_steering_blank"] == 1
    assert O["hvtl_minus_hvtl_hart"]["mean"] == pytest.approx(10.0)
    assert O["hvtu_minus_hvtu_hart"]["mean"] == pytest.approx(-10.0)
