#!/usr/bin/env python3
"""Classify the cross-event collisions in the recovered precursors.

A collision is a recovered pre-HF fix of one archive event lying within
track_hsf.COLLISION_NM of ANOTHER archive event's fix at the same valid time.
This reads the committed data/hf_lows/precursors.csv (medium and high
confidence only, so fewer than track_hsf's own count, which includes low)
and groups the collisions by event pair:

  sequential  the other event ends before this one starts. The High Seas
              analyses carry one low through both ids, so the archive has
              probably split one storm that lapsed below hurricane force
              and returned. link_kt is the speed implied from the other
              event's last fix to this event's first; above ~50 kt the two
              are more likely successive storms on one track.
  concurrent  both events are live at once, so this event's recovered lead
              fixes sit on a neighbouring storm the archive already tracks.
              Those precursor rows describe the other storm, not this one.

Nothing is merged or dropped; this is a worklist.

    python3 tools/review_collisions.py [--out data/hf_lows/collision_pairs.csv]
"""

import argparse
import csv
import datetime as dt
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import track_hsf as T  # noqa: E402

B = T.B
ROOT = os.path.dirname(HERE)
PRECURSORS = os.path.join(ROOT, "data", "hf_lows", "precursors.csv")
FIELDS = ["basin", "event", "other_event", "kind", "notes", "same_pres", "gap_h",
          "link_nm", "link_kt", "min_sim_nm", "conf", "event_span", "other_span"]


def when(t):
    return dt.datetime.strptime(str(t), "%Y%m%d%H")


def collisions(events, rows):
    index = defaultdict(list)
    for ev in events:
        for f in ev["fixes"]:
            index[(ev["basin"], f[0])].append((ev["id"], f))
    out = []
    for r in rows:
        v = r["valid"]
        key = int(v[0:4] + v[5:7] + v[8:10] + v[11:13])
        for oid, of in index.get((r["basin"], key), []):
            if oid == r["event_id"]:
                continue
            d = B.great_circle_nm(float(r["lat"]), float(r["lon"]), of[1], of[2])
            if d <= T.COLLISION_NM:
                same = r["pres"] != "" and of[4] is not None and abs(float(r["pres"]) - of[4]) < 0.5
                out.append((r["basin"], r["event_id"], oid, r["conf"], same))
    return out


def pairs(events, notes):
    byid = {(e["basin"], e["id"]): e for e in events}
    grouped = defaultdict(list)
    for b, e, o, conf, same in notes:
        grouped[(b, e, o)].append((conf, same))
    out = []
    for (b, e, o), ns in sorted(grouped.items()):
        E, O = byid[(b, e)], byid[(b, o)]
        es, ee = when(E["fixes"][0][0]), when(E["fixes"][-1][0])
        os_, oe = when(O["fixes"][0][0]), when(O["fixes"][-1][0])
        row = {"basin": b, "event": e, "other_event": o, "notes": len(ns),
               "same_pres": sum(s for _, s in ns),
               "conf": ",".join(sorted({c for c, _ in ns})),
               "event_span": "%s-%s" % (E["fixes"][0][0], E["fixes"][-1][0]),
               "other_span": "%s-%s" % (O["fixes"][0][0], O["fixes"][-1][0]),
               "gap_h": "", "link_nm": "", "link_kt": "", "min_sim_nm": ""}
        if oe < es:
            gap = (es - oe).total_seconds() / 3600
            a, c = O["fixes"][-1], E["fixes"][0]
            nm = B.great_circle_nm(a[1], a[2], c[1], c[2])
            row.update(kind="sequential", gap_h=round(gap), link_nm=round(nm),
                       link_kt=round(nm / gap))
        else:
            other = {f[0]: f for f in O["fixes"]}
            sim = [B.great_circle_nm(f[1], f[2], other[f[0]][1], other[f[0]][2])
                   for f in E["fixes"] if f[0] in other]
            row.update(kind="concurrent", min_sim_nm=round(min(sim)) if sim else "")
        out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", help="write the pair table here (CSV)")
    args = ap.parse_args(argv)
    events = T.load_events()
    with open(PRECURSORS, encoding="utf-8") as fh:
        rows = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    notes = collisions(events, rows)
    table = pairs(events, notes)
    seq = [p for p in table if p["kind"] == "sequential"]
    slow = [p for p in seq if p["link_kt"] <= 50]
    sys.stderr.write(
        "collision notes %d (same pressure %d) across %d event pairs\n"
        "  sequential %d (link <= 50 kt: %d, involving %d later events)\n"
        "  concurrent %d\n"
        % (len(notes), sum(n[4] for n in notes), len(table), len(seq), len(slow),
           len({(p["basin"], p["event"]) for p in slow}), len(table) - len(seq)))
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
