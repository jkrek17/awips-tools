#!/usr/bin/env python3
"""Audit of the daily CPS archive (data/<cycle>/<STORM>/) for the two tracker
rules fixed on 2 October 2026 (commit "Keep the 2 Oct 2026 typhoon case and
fix two tracker rules it exposed"):

- terrain: the old test masked every point with surface pressure below
  950 hPa, so a low deeper than about 950 hPa could not be a fix and the
  track sat on 950 hPa secondary minima. Flag: min MSLP at or below
  952 hPa, or any fix at exactly 950.0 hPa.
- reach: the old search reach was a fixed 90 km/h. Flag: track_end
  mentions "no minimum within" or "reach"; such an end is marked "fast"
  when the storm's last step was faster than SPEED_KMH / FAST_FACTOR
  (60 km/h), the only case where the new reach is wider than the old.

    python3 archive_audit.py [--data-dir DIR] [--out FILE] [--title TEXT]
    python3 archive_audit.py --data-dir DIR --before OLD_DIR --compare-out FILE

With --before, also writes a before/after table per storm-cycle (min MSLP,
end hour, end reason, class sequence, onset and completion hours) and a
summary of what changed. Provenance: for each storm-cycle, whether the
last commit that wrote its track.csv descends from the fix commit (git
log, read only), and the code_version recorded in meta.json if any.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIX_SUBJECT = "fix two tracker rules it exposed"
TERRAIN_MIN_HPA = 952.0
FAST_KMH = 60.0  # track_cps.SPEED_KMH / FAST_FACTOR


def gc_km(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(max(a, 0.0), 1.0)))


def git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True,
                              timeout=120).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def fix_commit() -> str:
    out = git("log", "--no-merges", "--format=%h", f"--grep={FIX_SUBJECT}", "--fixed-strings", "-1")
    return out.split()[0] if out else ""


def after_fix_paths(fix: str) -> set[str]:
    """Paths (relative to realtime/) of the track.csv files written by the
    fix commit itself or by a commit that descends from it."""
    if not fix:
        return set()
    out = git("log", "--ancestry-path", "--name-only", "--relative", "--format=", f"{fix}..HEAD", "--",
              str(DATA.relative_to(HERE)))
    out += "\n" + git("show", "--name-only", "--relative", "--format=", fix, "--", str(DATA.relative_to(HERE)))
    return {p.strip() for p in out.splitlines() if p.strip().endswith("track.csv")}


def end_kind(m: dict) -> str:
    if m.get("status") != "ok":
        return m.get("status", "?")
    t = m.get("track_end") or ""
    if not t:
        return "ran to the last hour" if m.get("end_fhr") == 198 else "ran out of frames"
    if t.startswith("no minimum within") or re.search(r"\breach\b", t):
        return "no minimum within reach"
    if t.startswith("outside a closed low"):
        return "outside a closed low"
    if t.startswith("merged into"):
        return "merged into another track"
    if t.startswith("FHR1"):
        return "FHR1 reached"
    return t


def read_rows(path: Path) -> list[dict]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


def load(data_dir: Path) -> dict[tuple[str, str], dict]:
    recs = {}
    for mp in sorted(data_dir.glob("[0-9]" * 10 + "/*/meta.json")):
        m = json.loads(mp.read_text())
        cyc, name = mp.parent.parent.name, mp.parent.name
        r = dict(cycle=cyc, storm=name, status=m.get("status"), meta=m, code=m.get("code_version", ""),
                 kind=end_kind(m), track_end=m.get("track_end") or "", min=m.get("min_mslp_hpa"),
                 start=m.get("start_fhr"), end=m.get("end_fhr"), seq=m.get("class_sequence") or "",
                 on_s=m.get("onset_standard_h"), co_s=m.get("completion_standard_h"),
                 on_h=m.get("onset_hart_h"), co_h=m.get("completion_hart_h"), fsu=m.get("fsu_number"),
                 n950=0, last_kmh=None)
        tp = mp.parent / "track.csv"
        r["fixes"] = {}
        if tp.exists():
            rows = read_rows(tp)
            r["fixes"] = {int(x["fhr"]): x for x in rows}
            r["n950"] = sum(1 for x in rows if x["mslp_hpa"] and abs(float(x["mslp_hpa"]) - 950.0) < 1e-6)
            if len(rows) >= 2:
                a, b = rows[-2], rows[-1]
                h = int(b["fhr"]) - int(a["fhr"])
                if h > 0:
                    r["last_kmh"] = gc_km(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"])) / h
        r["terrain"] = r["status"] == "ok" and ((r["min"] is not None and r["min"] <= TERRAIN_MIN_HPA) or r["n950"] > 0)
        r["reach"] = r["kind"] == "no minimum within reach"
        r["fast"] = r["reach"] and r["last_kmh"] is not None and r["last_kmh"] > FAST_KMH
        recs[(cyc, name)] = r
    return recs


def h(v) -> str:
    return "none" if v is None else str(v)


def fmt_min(v) -> str:
    return "" if v is None else f"{v:.1f}"


def audit_md(recs: dict, title: str, data_dir, head: str) -> str:
    fix = fix_commit()
    after = after_fix_paths(fix)
    rel = DATA.relative_to(HERE)
    ok = [r for r in recs.values() if r["status"] == "ok"]
    cycles = sorted({r["cycle"] for r in recs.values()})
    lines = [f"# {title}", "", f"Code version at audit time: `{head}` (git rev-parse --short HEAD). "
             f"Data: `{data_dir}`. Written by `archive_audit.py`.", "",
             f"{len(recs)} storm-cycles in {len(cycles)} cycles ({cycles[0]} to {cycles[-1]}); "
             f"{len(ok)} tracked (status ok), "
             + ", ".join(f"{v} {k}" for k, v in sorted(collections.Counter(
                 r["status"] for r in recs.values() if r["status"] != "ok").items())) + ".", ""]
    codes = collections.Counter(r["code"] or "not recorded" for r in recs.values())
    lines += ["Code version recorded in meta.json: " + ", ".join(f"`{k}` {v}" for k, v in codes.most_common())
              + "."]
    if fix:
        n_after = sum(1 for r in ok if str(rel / r["cycle"] / r["storm"] / "track.csv") in after)
        lines += ["", f"Fix commit `{fix}`. Tracks whose last committed track.csv is from it or a commit descending from it: {n_after} of "
                  f"{len(ok)} (git log --ancestry-path; uncommitted files count as not after)."]
    for r in recs.values():
        if r["code"]:
            r["prov"] = r["code"]
        else:
            r["prov"] = "after fix" if str(rel / r["cycle"] / r["storm"] / "track.csv") in after else "before fix"
    old = [r for r in ok if r["prov"] == "before fix"]
    t = [r for r in ok if r["terrain"]]
    rr = [r for r in ok if r["reach"]]
    rf = [r for r in rr if r["fast"]]
    lines += ["", "## Rule flags", "",
              f"- Terrain floor (min MSLP at or below {TERRAIN_MIN_HPA:.0f} hPa, or a fix at exactly 950.0 hPa): "
              f"{len(t)} storm-cycles, {sum(1 for r in t if r['n950'])} of them with a 950.0 hPa fix "
              f"({sum(r['n950'] for r in t)} fixes).",
              f"- Fixed reach (track_end \"no minimum within ...\" or mentioning reach): {len(rr)} storm-cycles; "
              f"{len(rf)} of them moving faster than {FAST_KMH:.0f} km/h over the last step, where the "
              "speed-scaled reach is wider than the fixed one.",
              f"- Written before the fix (no code_version, last committed track.csv neither from the fix commit "
              f"nor from one descending from it): {len(old)} tracks; among them {sum(r['terrain'] for r in old)} with the terrain flag "
              f"and {sum(r['reach'] for r in old)} with the reach flag ({sum(r['fast'] for r in old)} fast). "
              "A flag on a track written after the fix is not a symptom: it is a deep low or an ordinary "
              "end of track under the current rules.", "",
              "## End reasons", "", "| End reason | Storm-cycles |", "|---|---|"]
    for k, v in collections.Counter(r["kind"] for r in recs.values()).most_common():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Flagged storm-cycles", "",
              "| Cycle | Storm | Min MSLP (hPa) | 950.0 fixes | Hours | Last step (km/h) | Flags | Track end | "
              "Provenance |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(t + [x for x in rr if x not in t], key=lambda r: (r["cycle"], r["storm"])):
        flags = ", ".join(f for f, on in (("terrain", r["terrain"]), ("reach fast" if r["fast"] else "reach",
                                                                       r["reach"])) if on)
        sp = "" if r["last_kmh"] is None else f"{r['last_kmh']:.0f}"
        af = r["prov"]
        lines.append(f"| {r['cycle']} | {r['storm']} | {fmt_min(r['min'])} | {r['n950']} | "
                     f"{r['start']}-{r['end']} | {sp} | {flags} | {r['track_end']} | {af} |")
    lines += ["", "## Per cycle", "", "| Cycle | Storm-cycles | Tracked | Terrain flag | Reach flag | "
              "Reach flag, fast |", "|---|---|---|---|---|---|"]
    for c in cycles:
        rs = [r for r in recs.values() if r["cycle"] == c]
        lines.append(f"| {c} | {len(rs)} | {sum(r['status'] == 'ok' for r in rs)} | "
                     f"{sum(r['terrain'] for r in rs)} | {sum(r['reach'] for r in rs)} | "
                     f"{sum(r['fast'] for r in rs)} |")
    return "\n".join(lines) + "\n"


def onco(r) -> str:
    return f"{h(r['on_s'])}/{h(r['co_s'])}; {h(r['on_h'])}/{h(r['co_h'])}"


VALUE_COLS = ("mslp_hpa", "hvtl", "hvtu", "hb", "class", "hvtl_hart", "hvtu_hart", "hb_track")


def track_diff(b: dict, a: dict) -> dict:
    """Fix-by-fix comparison of two tracks over their common hours: fixes
    moved by more than 5 km, and fixes at the same place whose values
    differ (by more than 0.15 in the last printed digit's units)."""
    common = sorted(set(b["fixes"]) & set(a["fixes"]))
    moved = vals = 0
    for hh in common:
        x, y = b["fixes"][hh], a["fixes"][hh]
        if gc_km(float(x["lat"]), float(x["lon"]), float(y["lat"]), float(y["lon"])) > 5.0:
            moved += 1
            continue
        for c in VALUE_COLS:
            u, v = x.get(c, ""), y.get(c, "")
            if (u == "") != (v == "") or (u and v and abs(float(u) - float(v)) > 0.15):
                vals += 1
                break
    return dict(common=len(common), moved=moved, values=vals, first_moved=next(
        (hh for hh in common if gc_km(float(b["fixes"][hh]["lat"]), float(b["fixes"][hh]["lon"]),
                                      float(a["fixes"][hh]["lat"]), float(a["fixes"][hh]["lon"])) > 5.0), None))


def compare_md(before: dict, after: dict, head: str, notes: str = "") -> str:
    keys = sorted(set(before) | set(after))
    stamps = collections.Counter(r["code"] or "not recorded" for r in after.values())
    lines = ["# Daily CPS archive before and after the recompute", "",
             f"HEAD when this was written: `{head}` (git rev-parse --short HEAD). code_version in the recomputed "
             "meta.json files: " + ", ".join(f"`{k}` {v}" for k, v in stamps.most_common()) + ". "
             "Written by `archive_audit.py --before`.", ""]
    if notes:
        lines += [notes.strip(), ""]
    lines += [
             "Every storm-cycle of the archive, before (as archived, computed with the code of its day) and "
             "after (recomputed with one code version, same seeds). Onset/completion: standard bands, then "
             "Hart bands (hours; none when not reached). End: the last forecast hour of the track and why it "
             "stopped. Class codes: 0 sym deep warm, 1 sym shallow warm, 2 asym deep warm, 3 asym shallow "
             "warm, 4 asym cold, 5 sym cold, 6 shallow cold, - no class (outside the product's closed low or "
             "B blank).", ""]
    stats = collections.Counter()
    why = collections.defaultdict(list)
    rows = []
    for k in keys:
        b, a = before.get(k), after.get(k)
        if b is None or a is None:
            stats["only after" if b is None else "only before"] += 1
            why["new storm-cycle (automatic discovery of the recompute)" if b is None
                else "storm-cycle missing after the recompute"].append(k)
            continue
        ch = {f: b[f] != a[f] for f in ("status", "min", "end", "kind", "seq", "on_s", "co_s", "on_h", "co_h",
                                        "start", "fsu")}
        td = track_diff(b, a)
        for f, c in ch.items():
            stats[f] += c
        stats["moved"] += td["moved"] > 0
        stats["values"] += td["values"] > 0
        changed = any(v for f, v in ch.items() if f != "fsu") or td["moved"] or td["values"]
        stats["any"] += changed
        if not changed:
            if ch["fsu"]:
                why["FSU match only (fsu_number differs; track identical)"].append(k)
        else:
            if ch["status"]:
                cause = f"status {b['status']} -> {a['status']}"
            elif (b["terrain"] and (ch["min"] or td["moved"])) or (
                    a["min"] is not None and b["min"] is not None and a["min"] <= TERRAIN_MIN_HPA
                    and a["min"] < b["min"] - 1.0):
                cause = "terrain rule: a low deeper than about 950 hPa is now followed"
            elif b["reach"] and b["fast"] and ch["end"]:
                cause = "reach rule: fast mover followed further"
            elif td["moved"]:
                cause = "track positions differ (no rule flag: terrain test near high ground or a knock-on effect)"
            elif td["values"]:
                cause = "same positions, different values (product or B code changed since the original run)"
            else:
                cause = "end hour or end reason only (a knock-on effect: another track of the run changed)"
            why[cause].append(k)
        r_td = td
        rows.append((k, b, a, ch, r_td))
    lines += ["## Summary", "",
              f"{len(keys)} storm-cycles; {stats['any']} changed in at least one listed field, "
              f"{len(rows) - stats['any']} identical. Field changes: "
              + ", ".join(f"{lab} {stats[f]}" for f, lab in (
                  ("status", "status"), ("start", "start hour"), ("min", "min MSLP"), ("end", "end hour"),
                  ("kind", "end reason"), ("seq", "class sequence"), ("on_s", "onset std"),
                  ("co_s", "completion std"), ("on_h", "onset Hart"), ("co_h", "completion Hart"),
                  ("moved", "tracks with a fix moved over 5 km"),
                  ("values", "tracks with a value changed at an unmoved fix"), ("fsu", "FSU number"))) + "."
              + (f" Only before: {stats['only before']}; only after: {stats['only after']}."
                 if stats['only before'] or stats['only after'] else ""), "",
              "| Attributed cause | Storm-cycles |", "|---|---|"]
    for c, ks in sorted(why.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {c} | {len(ks)}: " + ", ".join(f"{cy} {s}" for cy, s in ks[:40])
                     + (" ..." if len(ks) > 40 else "") + " |")
    lines += ["", "## Changed storm-cycles", "",
              "| Cycle | Storm | Min MSLP | End h | End reason | Class sequence | Onset/completion std; Hart | "
              "Fixes moved / values changed (of common, first moved hour) |",
              "|---|---|---|---|---|---|---|---|"]

    def pair(x, y):
        return f"{x}" if x == y else f"{x} -> {y}"

    for k, b, a, ch, td in rows:
        if not (any(v for f, v in ch.items() if f != "fsu") or td["moved"] or td["values"]):
            continue
        lines.append(f"| {k[0]} | {k[1]} | {pair(fmt_min(b['min']), fmt_min(a['min']))} | "
                     f"{pair(h(b['end']), h(a['end']))} | {pair(b['kind'] if b['status'] == 'ok' else b['status'], a['kind'] if a['status'] == 'ok' else a['status'])} | "
                     f"{pair(b['seq'], a['seq'])} | {pair(onco(b), onco(a))} | "
                     f"{td['moved']} / {td['values']} (of {td['common']}, {h(td['first_moved'])}) |")
    for k in keys:
        if k not in before or k not in after:
            r = after.get(k) or before.get(k)
            lines.append(f"| {k[0]} | {k[1]} | {'(new) ' if k not in before else '(gone) '}{fmt_min(r['min'])} | "
                         f"{h(r['end'])} | {r['kind']} | {r['seq']} | {onco(r)} | |")
    lines += ["", "## All storm-cycles, before and after", "",
              "| Cycle | Storm | Status b/a | Min MSLP b | Min MSLP a | End b | End a | End reason b | End reason a | "
              "Class sequence b | Class sequence a | On/co b | On/co a |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, b, a, ch, td in rows:
        lines.append(f"| {k[0]} | {k[1]} | {b['status']}/{a['status']} | {fmt_min(b['min'])} | {fmt_min(a['min'])} | "
                     f"{h(b['end'])} | {h(a['end'])} | {b['kind']} | {a['kind']} | {b['seq']} | {a['seq']} | "
                     f"{onco(b)} | {onco(a)} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, help="audit markdown to write")
    ap.add_argument("--title", default="Daily CPS archive audit")
    ap.add_argument("--data-label", help="how to name the data directory in the report (default: its path "
                                         "relative to realtime/)")
    ap.add_argument("--before", type=Path, help="archive copy before the recompute, for the comparison")
    ap.add_argument("--compare-out", type=Path, help="before/after markdown to write (with --before)")
    ap.add_argument("--notes", type=Path, help="markdown inserted under the title of the comparison")
    a = ap.parse_args(argv)
    head = git("rev-parse", "--short", "HEAD") or "unknown"
    recs = load(a.data_dir)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        try:
            label = a.data_label or str(a.data_dir.resolve().relative_to(HERE))
        except ValueError:
            label = a.data_dir.name
        a.out.write_text(audit_md(recs, a.title, label, head))
        print(f"wrote {a.out}")
    if a.before and a.compare_out:
        notes = a.notes.read_text() if a.notes else ""
        a.compare_out.write_text(compare_md(load(a.before), recs, head, notes))
        print(f"wrote {a.compare_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
