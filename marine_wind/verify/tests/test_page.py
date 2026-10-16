"""Offline tests for page_scores.py's chance rows and page_data.py's merge with mixed hours
(run: python3 -m pytest marine_wind/verify/tests)."""
import csv
import gzip
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import page_data as pd_  # noqa: E402
import page_scores as ps  # noqa: E402


def test_core_event_is_ascat_48_within_a_5x7_box():
    shape = (40, 40)
    r = np.array([10, 10, 10, 30, 12])
    c = np.array([10, 13, 20, 30, 10])
    kt = np.array([50.0, 30.0, 20.0, 47.9, 30.0])
    ev = ps.core_event(r, c, kt, shape)
    # (10,10) is 50 kt itself; (10,13) is 3 columns away (inside +-3) -> yes; (10,20) is 10 columns away -> no;
    # (30,30) peaks at 47.9 -> no; (12,10) is 2 rows away (inside +-2) -> yes
    assert ev.tolist() == [True, True, False, False, True]
    # unseen cells (-1) never make an event
    assert not ps.core_event(np.array([5]), np.array([5]), np.array([10.0]), shape)[0]


def test_chance_rows_extra_labels_and_bins():
    pp = np.array([0.0, 0.05, 0.5, 1.0])
    items = {48: (pp, np.array([0, 0, 1, 1], bool)), "48raw": (pp, np.array([0, 0, 1, 1], bool)),
             "core": (pp, np.array([1, 0, 0, 1], bool))}
    rows = ps.chance_rows(dict(valid="20261014", basin="natl", hour=18, lead=24, referee="ascat"), items)
    assert [r["thr"] for r in rows] == [48, "48raw", "core"]
    core = rows[2]
    assert core["n"] == 4 and core["events"] == 2 and core["hour"] == 18
    assert (core["n0"], core["n5"], core["n9"]) == (2, 1, 1) and core["e0"] == 1 and core["e9"] == 1
    assert abs(core["bs"] - (1 + 0.05 ** 2 + 0.25 + 0)) < 1e-3


def test_lowbins():
    pp = np.array([0.0, 0.004, 0.01, 0.019, 0.02, 0.049, 0.05, 0.099, 0.10, 0.5])
    ev = np.array([0, 1, 0, 0, 1, 0, 0, 1, 1, 1], bool)
    (row,) = ps.lowbin_rows(dict(valid="20261014", basin="natl", hour=6, lead=48, referee="ascat"), {"core": (pp, ev)})
    assert [row["n%d" % i] for i in range(4)] == [2, 2, 2, 2]          # [0,1) [1,2) [2,5) [5,10) %; 10% and up excluded
    assert [row["e%d" % i] for i in range(4)] == [1, 0, 1, 1]
    assert abs(row["p1"] - 0.029) < 1e-6 and row["thr"] == "core"


def write_day(d, name, fields, rows):
    with open(os.path.join(d, name), "w", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def score_row(valid, basin, hour, ref="ascat", method="blend", lead=24):
    r = {k: 1 for k in ps.SCORE_FIELDS}
    r.update(valid=valid, basin=basin, hour=hour, lead=lead, method=method, referee=ref)
    return r


def chance_row(valid, basin, hour, thr, lead=24, ref="ascat"):
    r = {k: 0 for k in ps.CHANCE_FIELDS}
    r.update(valid=valid, basin=basin, hour=hour, lead=lead, referee=ref, thr=thr, n=10, events=1, bs=0.5)
    return r


def test_merge_keeps_hours_and_old_rows(tmp_path):
    tables, new = tmp_path / "tables", tmp_path / "new"
    tables.mkdir()
    new.mkdir()
    # history from before the hours: natl 12 Z and npac 00 Z, one with the hour column blank
    old = [score_row("20261001", "natl", 12), dict(score_row("20261001", "npac", 0), hour="")]
    with gzip.open(tables / "scores.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, ps.SCORE_FIELDS)
        w.writeheader()
        w.writerows(old)
    # new: natl 12 Z again for 20261001 (replaces), natl 18 Z (adds), npac 00 Z blank-hour day is untouched
    write_day(str(new), "scores_20261001_natl_12.csv", ps.SCORE_FIELDS, [dict(score_row("20261001", "natl", 12), n=99)])
    write_day(str(new), "scores_20261001_natl_18.csv", ps.SCORE_FIELDS, [score_row("20261001", "natl", 18)])
    write_day(str(new), "chances_20261001_natl_18.csv", ps.CHANCE_FIELDS,
              [chance_row("20261001", "natl", 18, t) for t in (34, 48, 64, "core", "48raw")])
    pd_.merge(str(tables), [str(new)])
    rows = pd_.read(str(tables / "scores.csv.gz"))
    assert sorted((r["basin"], pd_.hour_of(r)) for r in rows) == [("natl", 12), ("natl", 18), ("npac", 0)]
    assert [r["n"] for r in rows if r["basin"] == "natl" and r["hour"] == "12"] == ["99"]
    # re-adding the same day-hour replaces it, never duplicates
    pd_.merge(str(tables), [str(new)])
    assert len(pd_.read(str(tables / "scores.csv.gz"))) == 3
    ch = pd_.read(str(tables / "chances.csv.gz"))
    assert [r["thr"] for r in ch] == ["34", "48", "64", "48raw", "core"]    # numeric labels first, then names


def test_page_json_has_hours_and_ignores_extra_labels(tmp_path):
    tables, out = tmp_path / "tables", tmp_path / "data"
    tables.mkdir()
    sc = [score_row("20261001", "natl", 12), score_row("20261001", "natl", 18), score_row("20261001", "npac", 0),
          score_row("20261002", "npac", 6)]
    ch = [chance_row("20261001", "natl", h, t) for h in (12, 18) for t in (34, 48, 64, "core", "48raw", "64raw")]
    for name, fields, rows in (("scores", ps.SCORE_FIELDS, sc), ("chances", ps.CHANCE_FIELDS, ch)):
        with gzip.open(tables / (name + ".csv.gz"), "wt", newline="") as f:
            w = csv.DictWriter(f, fields)
            w.writeheader()
            w.writerows(rows)
    pd_.write_json(str(tables), str(out))
    idx = json.load(open(out / "index.json"))
    assert idx["basins"]["natl"]["hours"] == [12, 18] and idx["basins"]["npac"]["hours"] == [0, 6]
    assert idx["hours"] == [0, 6, 12, 18]
    d = json.load(open(out / "natl_ascat.json"))
    assert d["hour"] == [12, 18] and "hour" in d["cols"]
    c = json.load(open(out / "natl_chances.json"))
    assert sorted(set(c["thr"])) == [34, 48, 64] and c["hour"] == [12, 12, 12, 18, 18, 18]
