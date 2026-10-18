#!/usr/bin/env python3
"""Restore the FSU matches of the daily archive after a forced recompute run
without the FSU step (collect_daily.py --force --no-fsu), offline: no FSU
requests.

    python3 restore_fsu_matches.py [--data-dir DIR] [--matches FILE] [--dry-run]

fsu_matches_before.json (beside this script) holds the match of every
storm-cycle as committed before the recompute. For each one whose recomputed
meta.json has status ok and no "fsu" block, and whose fsu_phase1.png and
fsu_phase2.png are in the storm folder: the great-circle distance from the
recomputed start position to the matched FSU cyclone's position is computed;
within collect_daily.MATCH_KM (400 km), fsu_number and the fsu block are
written back (distance_km updated, plus "fsu_source" saying the match was
carried over) and compare.png is rebuilt with collect_daily.build_compare from
the saved FSU diagrams and the storm's phase.png. Farther than MATCH_KM, the
storm-cycle is left unmatched and listed. Re-running is harmless: a meta.json
that already has an fsu block is left alone. Afterwards, run collect_daily.py
for the cycle without --force (and with --no-fsu) to rewrite summary.md and
log.csv from the restored meta.json files; that does no GFS work for storms
whose meta.json says ok.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RT = HERE.parents[1]
sys.path.insert(0, str(RT))
import collect_daily as cd  # noqa: E402
import track_cps as tc  # noqa: E402

SOURCE = ("carried over offline from the match of the original collection (FSU's page for older cycles is no "
          "longer online); compare.png rebuilt with the recomputed phase.png")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=RT / "data")
    ap.add_argument("--matches", type=Path, default=HERE / "fsu_matches_before.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    matches = json.loads(a.matches.read_text())["matches"]
    counts = {"before": len(matches), "restored": 0, "kept": 0, "too_far": 0, "not_ok": 0, "no_images": 0,
              "missing": 0}
    for key, old in sorted(matches.items()):
        sdir = a.data_dir / key
        mp = sdir / "meta.json"
        if not mp.exists():
            counts["missing"] += 1
            print(f"{key}: no meta.json after the recompute")
            continue
        m = json.loads(mp.read_text())
        if m.get("fsu"):
            counts["kept"] += 1
            same = "same" if m["fsu_number"] == old["fsu_number"] else f"was {old['fsu_number']}"
            print(f"{key}: already matched to FSU {m['fsu_number']} ({same})")
            continue
        if m.get("status") != "ok":
            counts["not_ok"] += 1
            print(f"{key}: status {m.get('status')} after the recompute; not restored")
            continue
        p1, p2 = sdir / "fsu_phase1.png", sdir / "fsu_phase2.png"
        if not (p1.exists() and p2.exists()):
            counts["no_images"] += 1
            print(f"{key}: FSU diagrams missing; not restored")
            continue
        f = old["fsu"]
        d = float(tc.gc_km(m["start"]["lat"], m["start"]["lon"], f["lat"], f["lon"]))
        if d > cd.MATCH_KM:
            counts["too_far"] += 1
            print(f"{key}: FSU {f['number']} is {d:.0f} km from the recomputed start (over {cd.MATCH_KM:.0f} km); "
                  "left unmatched")
            continue
        counts["restored"] += 1
        print(f"{key}: FSU {f['number']} restored, {d:.0f} km (archived {f.get('distance_km')} km)")
        if a.dry_run:
            continue
        m["fsu_number"] = old["fsu_number"]
        m["fsu"] = dict(f, distance_km=round(d))
        m["fsu_source"] = SOURCE
        cd.write_json(mp, m)
        cd.build_compare(p1, p2, sdir / "phase.png", sdir / "compare.png")
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
