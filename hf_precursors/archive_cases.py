"""Hurricane-force onset cases, from the HF extratropical low archive.

The archive (`data/hf_lows/`, built by `tools/build_hf_lows.py`) is an
OUTCOME catalog: it records where and when lows reached hurricane force,
not what the atmosphere looked like beforehand. This module turns it into
the case list a precursor study needs -- one record per event, keyed on the
moment hurricane force began, which is the instant everything else is
measured relative to.

It calls `build_hf_lows.build()` rather than re-reading the CSVs, so every
case inherits that script's QC: repaired dates, dropped duplicates, split
reused IDs, mapped category aliases, and the event classification.

What is excluded, and why:

- `cls != "low"`. Tip jets and other events with no analyzed centre anywhere
  in their track are not cyclones with a phase space to compute. The archive
  already separates them; a study of cyclone structure must not quietly
  average them in.
- `season < RECORD_START` (2004). Both basin tabs begin mid-record, so
  earlier seasons are short-counted rather than quiet -- `build_hf_lows`
  says so itself, and a control set matched on month and season cannot be
  built against a partial record.
- No fix categorized HF. DHF means "expected to reach hurricane force", which
  is a forecast, not an outcome.

Onset is the FIRST fix categorized HF. The archive is 6-hourly, so onset is
known to +/- 3 h at best, and that uncertainty is larger than it looks: the
"time at hurricane force" histogram peaks at 12 h, so a typical event is only
two or three fixes long and an onset misplaced by one fix is a large
fraction of the event.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import build_hf_lows as bh  # noqa: E402


@dataclass(frozen=True)
class Case:
    """One hurricane-force onset."""
    id: str
    basin: str            # "atl" or "pac"
    season: int           # season start year, as the archive numbers them
    onset: datetime       # first fix categorized HF
    lat: float
    lon: float            # degrees east, negative west, as the archive stores it
    pres_at_onset: float | None
    min_pres: float | None       # lowest analyzed pressure anywhere in the track
    bergerons: float | None      # best 18-24 h deepening, latitude-normalized
    bomb: bool
    hours_at_hf: int             # HF fixes x 6 h, the archive's own interval estimate
    n_fixes_before_onset: int    # run-up carried by the archive itself

    @property
    def month(self) -> int:
        return self.onset.month

    def lead_time(self, hours: float) -> datetime:
        """The valid time `hours` before onset -- where a predictor is sampled."""
        return self.onset - timedelta(hours=float(hours))


def _fix_fields(payload):
    return {name: i for i, name in enumerate(payload["fixFields"])}


def _low_fields(payload):
    return {name: i for i, name in enumerate(payload["lowFields"])}


def build_cases(payload=None, min_season: int | None = None):
    """Every hurricane-force onset in the archive, as `Case` records.

    `min_season` defaults to the archive's own RECORD_START.
    """
    payload = payload or bh.build()
    lf, ff = _low_fields(payload), _fix_fields(payload)
    floor = bh.RECORD_START if min_season is None else min_season

    cases = []
    for row in payload["lows"]:
        if row[lf["cls"]] != "low" or row[lf["season"]] < floor:
            continue
        fixes = row[lf["fixes"]]
        cats = [f[ff["cat"]] for f in fixes]
        if "HF" not in cats:
            continue
        i = cats.index("HF")
        onset_fix = fixes[i]
        cases.append(Case(
            id=row[lf["id"]],
            basin=row[lf["basin"]],
            season=row[lf["season"]],
            onset=bh.to_dt(onset_fix[ff["date"]]),
            lat=float(onset_fix[ff["lat"]]),
            lon=float(onset_fix[ff["lon"]]),
            pres_at_onset=onset_fix[ff["pres"]],
            min_pres=row[lf["minP"]],
            bergerons=row[lf["berg"]],
            bomb=bool(row[lf["bomb"]]),
            hours_at_hf=row[lf["hfH"]] or 0,
            n_fixes_before_onset=i,
        ))
    return cases


def summarize(cases):
    import collections
    import statistics as st

    by_basin = collections.Counter(c.basin for c in cases)
    months = collections.Counter(c.month for c in cases)
    pres = [c.min_pres for c in cases if c.min_pres is not None]
    berg = [c.bergerons for c in cases if c.bergerons is not None]
    bombs = [c for c in cases if c.bomb]
    runup = collections.Counter(min(c.n_fixes_before_onset, 4) for c in cases)

    print(f"cases: {len(cases)}   {dict(by_basin)}")
    print(f"seasons: {min(c.season for c in cases)}-{max(c.season for c in cases)}")
    print(f"month of onset, most common: "
          f"{[(m, n) for m, n in months.most_common(5)]}")
    print(f"min central pressure: median {st.median(pres):.0f} hPa, "
          f"range {min(pres):.0f}-{max(pres):.0f}  (n={len(pres)})")
    print(f"bergerons: median {st.median(berg):.2f}  (n={len(berg)})")
    print(f"explosive (bomb): {len(bombs)} of {len(berg)} with a Bergeron value "
          f"= {100.0 * len(bombs) / len(berg):.0f}%")
    print(f"hours at HF: median {st.median([c.hours_at_hf for c in cases]):.0f} h")
    print(f"fixes before onset: {dict(sorted(runup.items()))}  (4 = 4 or more)")


if __name__ == "__main__":
    summarize(build_cases())
