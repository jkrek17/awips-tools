#!/usr/bin/env python3
"""Backfill the daily collection for Hart's set as the primary trace, offline.

    python3 backfill_hart_class.py [--data-dir DIR] [--cycle C [C ...]] [--no-plots]

No GRIB is downloaded and no track is recomputed. For every
data/<cycle>/<STORM>/ whose meta.json says ok:

- track.csv gets the class_hart column (track_cps.add_class_hart from
  the hb_hart, hvtl_hart, hvtu_hart and class columns already there;
  every other column is written back unchanged);
- phase.png is drawn again with track_cps.plot_phase (Hart's set solid,
  the standard set dashed, the two class strips) from the fixes read
  back from track.csv, and compare.png is rebuilt with
  collect_daily.build_compare where the two FSU diagrams were saved;
- meta.json keeps every key and its code_version, and gets
  "bands": "hart", class_sequence (now from class_hart),
  class_sequence_standard (what class_sequence used to hold, from the
  class column) and the onset_hart_h / completion_hart_h of the new
  diagram (B = hb_hart; they were from hb_track before).

Then every cycle's summary.md and data/log.csv are rewritten from the
meta.json files (collect_daily.write_summary and update_log). Re-runnable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect_daily as cd  # noqa: E402
import track_cps as tc  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def backfill_storm(cycle: str, sdir: Path, workdir: Path, plots: bool = True) -> dict:
    """One storm folder; returns what changed: {"track", "meta", "phase",
    "compare"} as booleans, plus "events" (the diagram's onset/completion)."""
    out = {"track": False, "meta": False, "phase": False, "compare": False, "events": {}}
    meta = cd.read_meta(sdir / "meta.json")
    track = sdir / "track.csv"
    if not meta or meta.get("status") != "ok" or not track.exists():
        return out
    name = meta["name"]
    fixes = tc.read_fixes(track)
    tc.add_class_hart(fixes)
    before = track.read_text()
    tc.write_csv(track, fixes)
    out["track"] = track.read_text() != before
    if plots:
        workdir.mkdir(parents=True, exist_ok=True)
        full = workdir / f"phase_{name}.png"
        ev = tc.plot_phase(full, name, cycle, fixes, True)
        out["events"] = ev
        cd.save_phase(full, sdir / "phase.png")
        out["phase"] = True
        fsu1, fsu2 = sdir / "fsu_phase1.png", sdir / "fsu_phase2.png"
        if fsu1.exists() and fsu2.exists():
            cd.build_compare(fsu1, fsu2, full, sdir / "compare.png")
            out["compare"] = True
        if "hart" in ev:
            meta["onset_hart_h"], meta["completion_hart_h"] = cd.num(ev["hart"][0]), cd.num(ev["hart"][1])
    std = cd.class_seq_str(cd.class_runs(fixes, "class"))
    old = meta.get("class_sequence")
    if meta.get("bands") != "hart" and old is not None and old != std:
        log(f"  {cycle}/{name}: class_sequence in meta.json ({old}) differs from the track's class column ({std}); "
            "using the track")
    # keep the key order of a collected meta.json: the sequences sit after completion_hart_h
    new = {}
    for k, v in meta.items():
        if k in ("bands", "class_sequence", "class_sequence_standard"):
            continue
        new[k] = v
        if k == "completion_hart_h":
            new["bands"] = "hart"
            new["class_sequence"] = cd.class_seq_str(cd.class_runs(fixes, "class_hart"))
            new["class_sequence_standard"] = std
    if "bands" not in new:  # a meta.json without the event keys: append
        new.update(bands="hart", class_sequence=cd.class_seq_str(cd.class_runs(fixes, "class_hart")),
                   class_sequence_standard=std)
    text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    if (sdir / "meta.json").read_text() != text:
        (sdir / "meta.json").write_text(text)
        out["meta"] = True
    return out


def backfill(data_dir: Path, cycles: list[str] | None = None, workdir: Path | None = None,
             plots: bool = True) -> dict:
    """Every cycle of data_dir (or the given ones); returns the counts."""
    data_dir = Path(data_dir)
    workdir = workdir or cd.OUT
    n = {"cycles": 0, "storms": 0, "track": 0, "meta": 0, "phase": 0, "compare": 0, "summary": 0}
    rows = []
    for cdir in sorted(p for p in data_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{10}", p.name)):
        cycle = cdir.name
        if cycles and cycle not in cycles:
            continue
        n["cycles"] += 1
        for mp in sorted(cdir.glob("*/meta.json")):
            sdir = mp.parent
            n["storms"] += 1
            res = backfill_storm(cycle, sdir, workdir / cycle, plots)
            for k in ("track", "meta", "phase", "compare"):
                n[k] += int(res[k])
            meta = cd.read_meta(mp) or {}
            status = "merged" if meta.get("merged_into") else meta.get("status", "ok")
            rows.append((cycle, sdir.name, meta.get("fsu_number"), status))
            log(f"  {cycle}/{sdir.name}: " + ", ".join(k for k in ("track", "meta", "phase", "compare") if res[k])
                + (f"; Hart onset/completion {res['events'].get('hart')}" if res["events"].get("hart") else ""))
        before = (cdir / "summary.md").read_text() if (cdir / "summary.md").exists() else None
        cd.write_summary(cycle, cdir)
        n["summary"] += int((cdir / "summary.md").read_text() != before)
        log(f"{cycle}: summary.md written")
    if rows:
        cd.update_log(data_dir / "log.csv", rows)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=cd.DATA)
    ap.add_argument("--cycle", nargs="*", help="only these cycles (default all)")
    ap.add_argument("--no-plots", action="store_true", help="only the CSV, meta, summary and log (no figures)")
    a = ap.parse_args(argv)
    n = backfill(a.data_dir.resolve(), a.cycle, plots=not a.no_plots)
    log(f"done: {n['cycles']} cycles, {n['storms']} storm folders; rewrote {n['track']} track.csv, {n['meta']} "
        f"meta.json, {n['phase']} phase.png, {n['compare']} compare.png, {n['summary']} summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
