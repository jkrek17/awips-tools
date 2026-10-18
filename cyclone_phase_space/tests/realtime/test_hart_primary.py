"""Hart's set as the primary trace of the daily collection: the class_hart
column (track_cps.class_hart_value, add_class_hart), the CSV round trip
with and without the column (write_csv, read_fixes), plot_phase's events,
the meta.json class sequences (collect_daily.build_meta, write_summary)
and the offline backfill (backfill_hart_class) on a small synthetic
archive."""

from __future__ import annotations

import csv
import datetime as dt
import itertools
import json
import math

import numpy as np
import pytest
from PIL import Image

import backfill_hart_class as bf
import collect_daily as cd
import fsu_stats as fs
import track_cps as tc

NAN = float("nan")


# ------------------------------------------------------------------ the rule
def test_class_hart_value_matches_the_d2d_table_and_fsu_stats():
    for b, vl, vu in itertools.product([-5.0, 10.0, 10.0001, 30.0], [-50.0, -0.001, 0.0, 40.0],
                                       [-50.0, -0.001, 0.0, 40.0]):
        want = tc.hc.hart_class(np.array([b]), np.array([vl]), np.array([vu]), np.array([True]))[0]
        assert tc.class_hart_value(b, vl, vu, True) == float(want) == fs.hart_class(b, vl, vu), (b, vl, vu)
    f = tc.class_hart_value
    assert f(0.0, 50.0, 50.0) == 0 and f(30.0, 50.0, 50.0) == 2 and f(0.0, 50.0, -50.0) == 1
    assert f(30.0, 50.0, -50.0) == 3 and f(30.0, -50.0, -50.0) == 4 and f(0.0, -50.0, -50.0) == 5
    assert f(0.0, -50.0, 50.0) == 6 and f(30.0, -50.0, 50.0) == 6  # lower cold, upper warm, whatever B
    assert f(10.0, 0.0, 0.0) == 0 and f(10.01, 0.0, 0.0) == 2  # ties: B at 10 m symmetric, a term at 0 warm


def test_class_hart_value_is_nan_outside_a_closed_low_or_with_a_missing_term():
    assert math.isnan(tc.class_hart_value(30.0, 50.0, 50.0, False))
    for b, vl, vu in ((NAN, 1.0, 1.0), (1.0, NAN, 1.0), (1.0, 1.0, NAN)):
        assert math.isnan(tc.class_hart_value(b, vl, vu, True))


def test_add_class_hart_uses_the_gridded_class_as_the_closed_low_test():
    fixes = [dict(hb_hart=20.0, hvtl_hart=5.0, hvtu_hart=5.0, **{"class": 0.0}),  # inside: Hart says 2
             dict(hb_hart=20.0, hvtl_hart=5.0, hvtu_hart=5.0, **{"class": NAN}),  # outside the mask
             dict(hb_hart=NAN, hvtl_hart=5.0, hvtu_hart=5.0, **{"class": 1.0}),  # no track motion yet
             dict(hb_hart=2.0, hvtl_hart=-5.0, hvtu_hart=5.0, **{"class": 4.0})]  # inside: 6
    tc.add_class_hart(fixes)
    got = [fx["class_hart"] for fx in fixes]
    assert got[0] == 2.0 and math.isnan(got[1]) and math.isnan(got[2]) and got[3] == 6.0
    tc.add_class_hart([{}])  # a fix with none of the columns is simply NaN


# ------------------------------------------------------------------ CSV
def make_fixes(n=6, hb_hart=None, hb_track=None, hvtl_hart=None, closed=None):
    t0 = dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc)
    out = []
    for k in range(n):
        inside = True if closed is None else closed[k]
        fx = dict(fhr=6 * k, valid=t0 + dt.timedelta(hours=6 * k), lat=40.0 + 0.5 * k, lon=-60.0 + k,
                  mslp_hpa=990.0 - k, hvtl=30.0, hvtu=-20.0, hb=5.0, idx=0.5, hvtl_hart=25.0, hvtu_hart=-10.0,
                  hb_track=4.0, motion_kt=20.0, heading_deg=45.0, steering_heading_deg=50.0, steering_kt=15.0,
                  hb_hart=3.0)
        fx["class"] = 1.0 if inside else NAN
        if hb_hart is not None:
            fx["hb_hart"] = hb_hart[k]
        if hb_track is not None:
            fx["hb_track"] = hb_track[k]
        if hvtl_hart is not None:
            fx["hvtl_hart"] = hvtl_hart[k]
        out.append(fx)
    return out


def test_csv_round_trip_with_the_column(tmp_path):
    fixes = make_fixes(hb_hart=[3.0, 12.0, 20.0, NAN, 20.0, 20.0], closed=[True, True, True, True, False, True])
    tc.add_class_hart(fixes)
    assert [fx["class_hart"] for fx in fixes][:3] == [1.0, 3.0, 3.0]
    assert math.isnan(fixes[3]["class_hart"]) and math.isnan(fixes[4]["class_hart"])
    p = tmp_path / "track.csv"
    tc.write_csv(p, fixes)
    with p.open() as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == tc.CSV_COLS and rows[0][-1] == "class_hart"
    assert [r[-1] for r in rows[1:]] == ["1", "3", "3", "", "", "3"]
    back = tc.read_fixes(p)
    assert len(back) == 6 and back[0]["valid"] == fixes[0]["valid"] and back[2]["fhr"] == 12
    for fx, b in zip(fixes, back):
        for k in tc.CSV_COLS:
            if k == "valid":
                continue
            if isinstance(fx[k], float) and math.isnan(fx[k]):
                assert math.isnan(b[k]), k
            else:
                assert b[k] == pytest.approx(fx[k], abs=0.05), k
    # writing the read fixes again reproduces the file exactly
    q = tmp_path / "again.csv"
    tc.write_csv(q, back)
    assert q.read_text() == p.read_text()


def test_old_csv_without_the_column_loads_with_nan(tmp_path):
    fixes = make_fixes(n=3)
    old_cols = [c for c in tc.CSV_COLS if c != "class_hart"]
    p = tmp_path / "track.csv"
    with p.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(old_cols)
        for fx in fixes:
            w.writerow([fx["valid"].strftime(tc.VALID_FMT) if k == "valid" else fx[k] for k in old_cols])
    back = tc.read_fixes(p)
    assert all(math.isnan(fx["class_hart"]) for fx in back)
    assert back[1]["hb_hart"] == 3.0 and back[1]["class"] == 1.0
    # a fix that never had the key is written blank, not rejected
    tc.write_csv(tmp_path / "out.csv", [{k: v for k, v in fx.items() if k != "class_hart"} for fx in back])
    with (tmp_path / "out.csv").open() as fh:
        rows = list(csv.reader(fh))
    assert rows[0][-1] == "class_hart" and all(r[-1] == "" for r in rows[1:])


# ------------------------------------------------------------------ events and meta
def test_plot_phase_hart_events_use_hb_hart(tmp_path):
    # hb_hart jumps to 40 m at 18 h, hb_track only at 30 h, hb (standard) never; hvtl_hart turns cold at 18 h
    fixes = make_fixes(n=8, hb_hart=[0, 0, 0, 40, 40, 40, 40, 40], hb_track=[0, 0, 0, 0, 0, 40, 40, 40],
                       hvtl_hart=[50, 50, 50, -80, -80, -80, -80, -80])
    tc.add_class_hart(fixes)
    ev = tc.plot_phase(tmp_path / "phase.png", "T", "2026100112", fixes, True)
    assert list(ev) == ["hart", "standard"]
    on, comp = ev["hart"]
    # 24 h mean (+/- 12 h) of hb_hart: 0 at 0 h, 10 at 6 h (not above), 16 at 12 h -> onset 12 h;
    # of hvtl_hart: 50, 17.5, -2 -> completion 12 h. With hb_track the onset would be 24 h.
    assert on == 12.0 and comp == 12.0
    assert tc.onset_completion(np.arange(0, 48, 6.0), tc.running_mean(np.arange(0, 48, 6.0), np.array(
        [fx["hb_track"] for fx in fixes], float)), np.full(8, 50.0))[0] == 24.0
    assert math.isnan(ev["standard"][0])  # hb stays at 5 m: no standard onset
    assert (tmp_path / "phase.png").exists()
    ev2 = tc.plot_phase(tmp_path / "phase2.png", "T", "2026100112", fixes, False)
    assert list(ev2) == ["standard"]
    for fx in fixes:  # no Hart levels fetched: the standard set stays the primary trace
        fx["hvtl_hart"] = fx["hvtu_hart"] = fx["hb_hart"] = NAN
    ev3 = tc.plot_phase(tmp_path / "phase3.png", "T", "2026100112", fixes, True)
    assert list(ev3) == ["standard"]


def test_build_meta_class_sequences(tmp_path):
    fixes = make_fixes(n=5, hb_hart=[20, 20, 2, 2, 2], closed=[True, True, True, False, True])
    tc.add_class_hart(fixes)
    track = tc.Track("T:40,-60")
    track.fixes = fixes
    job = {"name": "T", "track": track, "events": {"hart": (6.0, NAN), "standard": (NAN, 12.0)},
           "seed": dict(lat=40.0, lon=-60.0, fhr0=0, fhr1=None, source="test")}
    meta = cd.build_meta("2026100112", job, "abc1234")
    assert meta["bands"] == "hart"
    assert meta["class_sequence"] == "3 0-6, 1 12, - 18, 1 24"
    assert meta["class_sequence_standard"] == "1 0-12, - 18, 1 24"
    assert meta["onset_hart_h"] == 6 and meta["completion_hart_h"] is None
    assert meta["onset_standard_h"] is None and meta["completion_standard_h"] == 12
    for k in ("onset_standard_h", "completion_standard_h", "onset_hart_h", "completion_hart_h", "code_version"):
        assert k in meta
    cdir = tmp_path / "2026100112"
    (cdir / "T").mkdir(parents=True)
    cd.write_json(cdir / "T" / "meta.json", meta)
    cd.write_summary("2026100112", cdir)
    md = (cdir / "summary.md").read_text()
    head = next(line for line in md.splitlines() if line.startswith("| Storm"))
    cols = [c.strip() for c in head.strip("|").split("|")]
    assert cols[5:] == ["Class sequence Hart (h)", "Class sequence std (h)", "Onset Hart", "Completion Hart",
                        "Onset std", "Completion std"]
    row = next(line for line in md.splitlines() if line.startswith("| [T]"))
    assert "| 3 0-6, 1 12, - 18, 1 24 | 1 0-12, - 18, 1 24 | 6 | none | none | 12 |" in row
    assert "900-600 and 600-300 hPa" in md and "as in CAVE" in md
    assert chr(0x2014) not in md  # no em-dash anywhere in the summary


# ------------------------------------------------------------------ backfill
def old_track_csv(path, fixes):
    """A track.csv as the collector wrote it before class_hart existed."""
    cols = [c for c in tc.CSV_COLS if c != "class_hart"]
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for fx in fixes:
            w.writerow([fx["valid"].strftime(tc.VALID_FMT) if k == "valid" else
                        ("" if isinstance(fx[k], float) and math.isnan(fx[k]) else
                         (str(int(fx[k])) if k == "class" else fx[k])) for k in cols])


def old_meta(cycle, name, fixes, fsu):
    return {"cycle": cycle, "name": name, "status": "ok", "code_version": "0ld0000", "seed": {"lat": 40.0},
            "start_fhr": fixes[0]["fhr"], "end_fhr": fixes[-1]["fhr"], "fixes": len(fixes),
            "start": {"lat": 40.0, "lon": -60.0, "mslp_hpa": 990.0}, "end": {"lat": 41.0, "lon": -59.0,
                                                                            "mslp_hpa": 985.0},
            "min_mslp_hpa": 985.0, "onset_standard_h": None, "completion_standard_h": 12,
            "onset_hart_h": 24, "completion_hart_h": None,
            "class_sequence": cd.class_seq_str(cd.class_runs(fixes, "class")),
            "fsu_number": fsu, "fsu": None, "track_end": "test"}


def test_backfill_small_archive(tmp_path):
    cycle = "2026100112"
    data = tmp_path / "data"
    cdir = data / cycle
    a = make_fixes(n=8, hb_hart=[0, 0, 0, 40, 40, 40, 40, 40], hb_track=[0] * 8, closed=[True] * 7 + [False])
    b = make_fixes(n=4, hb_hart=[2, 2, 2, 2])
    for name, fixes, fsu in (("ALPHA", a, 7), ("BRAVO", b, None)):
        (cdir / name).mkdir(parents=True)
        old_track_csv(cdir / name / "track.csv", fixes)
        cd.write_json(cdir / name / "meta.json", old_meta(cycle, name, fixes, fsu))
        (cdir / name / "phase.png").write_bytes(b"old")
    for k in ("fsu_phase1.png", "fsu_phase2.png"):  # ALPHA has its FSU diagrams
        Image.new("RGB", (1024, 768), "white").save(cdir / "ALPHA" / k)
    (cdir / "LOST").mkdir()
    cd.write_json(cdir / "LOST" / "meta.json", {"cycle": cycle, "name": "LOST", "status": "lost", "reason": "x",
                                                "code_version": "0ld0000", "fsu_number": None})
    (data / "log.csv").write_text("cycle,storm,fsu_number,status\n2026093012,ZULU,3,ok\n")

    n = bf.backfill(data, workdir=tmp_path / "out")
    assert n == {"cycles": 1, "storms": 3, "track": 2, "meta": 2, "phase": 2, "compare": 1, "summary": 1}
    # track.csv: the column added, everything else as it was
    for name in ("ALPHA", "BRAVO"):
        with (cdir / name / "track.csv").open() as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == tc.CSV_COLS
    with (cdir / "ALPHA" / "track.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert [r["class_hart"] for r in rows] == ["1", "1", "1", "3", "3", "3", "3", ""]
    assert [r["class"] for r in rows] == ["1"] * 7 + [""]
    # meta.json: existing keys and code_version kept, the sequences and bands set, Hart events from hb_hart
    m = json.loads((cdir / "ALPHA" / "meta.json").read_text())
    assert m["code_version"] == "0ld0000" and m["bands"] == "hart" and m["track_end"] == "test"
    assert m["class_sequence"] == "1 0-12, 3 18-36, - 42"
    assert m["class_sequence_standard"] == "1 0-36, - 42"
    assert m["onset_hart_h"] == 12 and m["completion_hart_h"] is None  # was 24 (from hb_track) before
    assert m["onset_standard_h"] is None and m["completion_standard_h"] == 12  # untouched
    keys = list(m)
    assert keys.index("bands") == keys.index("completion_hart_h") + 1
    assert keys.index("class_sequence_standard") == keys.index("class_sequence") + 1
    lost = json.loads((cdir / "LOST" / "meta.json").read_text())
    assert lost["status"] == "lost" and "bands" not in lost
    # figures
    assert Image.open(cdir / "ALPHA" / "phase.png").width == cd.PHASE_WIDTH
    assert Image.open(cdir / "ALPHA" / "compare.png").width == cd.COMPARE_WIDTH
    assert not (cdir / "BRAVO" / "compare.png").exists()
    # summary and log
    md = (cdir / "summary.md").read_text()
    assert "| [ALPHA](ALPHA/) | none | " in md and "| 1 0-12, 3 18-36, - 42 | 1 0-36, - 42 | 12 | none | none | 12 |" in md
    assert "LOST: lost. x" in md
    with (data / "log.csv").open() as fh:
        logrows = list(csv.reader(fh))
    assert logrows[1:] == [["2026093012", "ZULU", "3", "ok"], [cycle, "ALPHA", "7", "ok"], [cycle, "BRAVO", "", "ok"],
                           [cycle, "LOST", "", "lost"]]
    # a second pass changes nothing
    before = {p: p.read_bytes() for p in cdir.rglob("*") if p.is_file() and p.suffix != ".png"}
    n2 = bf.backfill(data, workdir=tmp_path / "out", plots=False)
    assert n2["track"] == 0 and n2["meta"] == 0 and n2["summary"] == 0
    assert {p: p.read_bytes() for p in cdir.rglob("*") if p.is_file() and p.suffix != ".png"} == before
