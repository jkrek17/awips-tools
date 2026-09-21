"""Phase 0 and 0.5: what the archive alone can say, before any reanalysis.

Two questions, both answerable from `data/hf_lows/` with no ERA5 at all.

PHASE 0 -- is the record homogeneous enough to use?
    Hurricane-force counts per season. The archive's HF determination depends
    on what the analyst could see, and that changed: ASCAT-A from 2007,
    ASCAT-B from late 2012, ASCAT-C from late 2018. A third scatterometer
    mainly improves revisit, which preferentially helps catch small,
    short-lived wind maxima -- exactly the population the compactness
    hypothesis is about. A step in the counts at 2019 would mean a predictor
    correlated with era could masquerade as a predictor of wind.

PHASE 0.5 -- is there any support for the compactness hypothesis?
    The forecaster's claim under test: hurricane force comes from a TIGHT
    pressure gradient, not from a deep centre, so a compact low that is
    falling fast can reach hurricane force at a central pressure in the 980s,
    while a broad low spreads the same depth over too much area to do it.

    WHAT THIS CANNOT TEST. The archive records position, central pressure and
    category. It carries no footprint, no radius, no environmental pressure --
    nothing about the SCALE of the pressure field, which is half the
    hypothesis. So this phase cannot test gradient-versus-scale. It tests the
    corollary: if depth alone does not make hurricane force, then events that
    reach it at modest depth should be the fast-falling ones. Support here is
    necessary, not sufficient, and the scale half needs ERA5.

    The trap in reading the result: deeper lows have generally fallen further
    to get deep, so total fall and depth are coupled by construction. What
    matters is the RATE among events that all reached the same outcome, which
    is why every number below is conditioned on being a hurricane-force event.

Run from the repository root:

    python3 hf_precursors/phase0_archive.py
"""
from __future__ import annotations

import collections
import statistics as stats
import sys
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "hf_precursors"))

import build_hf_lows as bh  # noqa: E402
from archive_cases import build_cases, _low_fields, _fix_fields  # noqa: E402

SHALLOW_HPA = 980.0     # "hurricane force in the 980s" -- the case under test
DEEP_HPA = 955.0        # the unambiguously deep comparison group
FAST_FALL_HPA = 20.0    # the fall the hypothesis says can substitute for depth
TEND_HOURS = 12.0


def pressure_falls(fixes, ff, hours=TEND_HOURS):
    """Every `hours`-hour pressure change available in one track, as
    (end_datetime, delta_hPa). Negative is deepening.

    Fix spacing is nominally 6 h but not guaranteed, so pairs are matched on
    their actual time difference rather than on index arithmetic.
    """
    stamped = [(bh.to_dt(f[ff["date"]]), f[ff["pres"]]) for f in fixes]
    want = timedelta(hours=hours)
    out = []
    for i, (t1, p1) in enumerate(stamped):
        if p1 is None:
            continue
        for t0, p0 in stamped[:i]:
            if p0 is not None and t1 - t0 == want:
                out.append((t1, p1 - p0))
                break
    return out


def track_metrics(row, lf, ff, onset):
    """Per-event pressure-tendency metrics: the fastest `TEND_HOURS` fall
    anywhere in the track, and the fall ending at hurricane-force onset."""
    falls = pressure_falls(row[lf["fixes"]], ff)
    best = min((d for _, d in falls), default=None)
    at_onset = next((d for t, d in falls if t == onset), None)
    return best, at_onset


def load(min_season=2016, basin=None):
    payload = bh.build()
    lf, ff = _low_fields(payload), _fix_fields(payload)
    cases = build_cases(payload, min_season=1900)
    by_id = {row[lf["id"]]: row for row in payload["lows"]}

    out = []
    for c in cases:
        if basin and c.basin != basin:
            continue
        best, at_onset = track_metrics(by_id[c.id], lf, ff, c.onset)
        out.append((c, best, at_onset))
    return payload, out


def phase0(records):
    print("=" * 74)
    print("PHASE 0  Is the record homogeneous? HF events per season")
    print("=" * 74)
    print("  ASCAT-A from 2007, ASCAT-B from late 2012, ASCAT-C from late 2018.")
    print("  A step at 2019 would mean the observing system, not the weather.\n")
    for basin in ("pac", "atl"):
        per = collections.Counter(c.season for c, _, _ in records if c.basin == basin)
        seasons = sorted(s for s in per if s >= 2004)
        print(f"  {basin}:")
        line = "   "
        for s in seasons:
            mark = "|" if s == 2019 else " "
            line += f"{mark}{s % 100:02d}:{per[s]:<4}"
        print(line)
        pre = [per[s] for s in seasons if 2013 <= s <= 2018]
        post = [per[s] for s in seasons if s >= 2019]
        if pre and post:
            print(f"    mean 2013-2018 {stats.mean(pre):.1f}/season   "
                  f"mean 2019+ {stats.mean(post):.1f}/season   "
                  f"ratio {stats.mean(post) / stats.mean(pre):.2f}")
        print()


def phase05(records, label):
    print("=" * 74)
    print(f"PHASE 0.5  Do shallow HF events fall faster?   [{label}]")
    print("=" * 74)

    have = [(c, b) for c, b, _ in records if b is not None and c.min_pres is not None]
    print(f"  {len(have)} of {len(records)} events carry a {TEND_HOURS:.0f} h "
          f"pressure pair; the rest have too few analyzed pressures.\n")
    if not have:
        return

    shallow = [(c, b) for c, b in have if c.min_pres >= SHALLOW_HPA]
    mid = [(c, b) for c, b in have if DEEP_HPA < c.min_pres < SHALLOW_HPA]
    deep = [(c, b) for c, b in have if c.min_pres <= DEEP_HPA]

    print(f"  {'group':<28} {'n':>5} {'median fastest 12 h fall':>26} {'>= 20 hPa':>11}")
    print("  " + "-" * 72)
    for name, grp in ((f"shallow  (minP >= {SHALLOW_HPA:.0f})", shallow),
                      (f"middle   ({DEEP_HPA:.0f}-{SHALLOW_HPA:.0f})", mid),
                      (f"deep     (minP <= {DEEP_HPA:.0f})", deep)):
        if not grp:
            print(f"  {name:<28} {0:>5}")
            continue
        falls = [b for _, b in grp]
        fast = sum(1 for f in falls if f <= -FAST_FALL_HPA)
        print(f"  {name:<28} {len(grp):>5} {stats.median(falls):>22.1f} hPa "
              f"{100.0 * fast / len(grp):>9.0f}%")

    print()
    print("  The hypothesis predicts the SHALLOW group falls fastest: if depth")
    print("  did not make the wind, rate had to. The deep group is free to be")
    print("  slow, because it has the depth already.")
    print()

    # The specific claim: hurricane force in the 980s with a 20 hPa/12 h fall.
    named = [(c, b) for c, b in shallow if b <= -FAST_FALL_HPA]
    print(f"  Events matching the stated signature exactly -- minP >= "
          f"{SHALLOW_HPA:.0f} hPa AND a {TEND_HOURS:.0f} h fall of "
          f"{FAST_FALL_HPA:.0f} hPa or more: {len(named)}")
    if named:
        print(f"    {'id':<16} {'onset':<13} {'minP':>6} {'fall':>7} {'lat':>6}")
        for c, b in sorted(named, key=lambda x: x[1])[:10]:
            print(f"    {c.id:<16} {c.onset.strftime('%Y-%m-%d %H'):<13} "
                  f"{c.min_pres:>6.0f} {b:>6.1f} {c.lat:>6.1f}")
    print()

    # The converse: deep events that never fell fast -- broad, slow, still HF.
    slow_deep = [(c, b) for c, b in deep if b > -10.0]
    print(f"  The converse -- deep (<= {DEEP_HPA:.0f} hPa) but never falling more")
    print(f"  than 10 hPa/12 h: {len(slow_deep)} of {len(deep)}")
    print("    These are the ones depth alone explains; they should be the")
    print("    broad storms, which only ERA5 can confirm.")


if __name__ == "__main__":
    payload, all_rec = load()
    phase0(all_rec)
    pac = [r for r in all_rec if r[0].basin == "pac" and r[0].season >= 2016]
    phase05(pac, "Pacific, 2016-2025 -- the study sample")
    print()
    phase05([r for r in all_rec if r[0].season >= 2004],
            "both basins, 2004-2025 -- context only, not the study sample")
