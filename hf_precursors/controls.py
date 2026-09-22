"""Cases and matched controls as (low, time) pairs.

THE UNIT OF ANALYSIS. Not "a storm", but a low observed at an instant, with
the question: given what this low looks like now, does it produce hurricane
force within the next 24 h? That framing avoids inventing an onset for
controls, which have none, and it is the question a forecaster actually asks.

    case     the low 24 h before its hurricane-force onset        label 1
    control  a low at some time with no archive fix near it in
             space or in the 48 h either side                     label 0

BACKWARD TRACKING. Pacific archive tracks begin at onset, so the low's
position 24 h earlier is not recorded and has to be recovered from ERA5:
step back 6 h at a time, taking the pressure minimum within a radius a storm
could plausibly have covered. Each step's displacement is kept so that
implausible jumps -- the tracker latching onto a different low -- can be
filtered rather than silently averaged in.

MATCHING. Controls are matched to cases on depth, latitude and month, within
season. Matching on season is what cancels the observing-system era; matching
on depth and latitude is what stops the study rediscovering that deeper lows
are windier. Crucially the match is on the state at OBSERVATION time, not on
anything the low went on to do: matching on an outcome would leak the future
into the comparison.

CONTAMINATION IS SAFE. Where the archive has missed a real hurricane-force
low, that low becomes a control and makes the test harder, never easier.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.ndimage import minimum_filter

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "hf_precursors"))

import build_hf_lows as bh  # noqa: E402
import era5  # noqa: E402
from archive_cases import build_cases, _low_fields, _fix_fields  # noqa: E402
from pressure_field import describe_low, great_circle_km  # noqa: E402

LEAD_HOURS = 24.0
TRACK_STEP_H = 6.0
MAX_STEP_KM = 550.0        # 6 h of storm motion, generous but bounded
EXCLUDE_KM = 750.0
EXCLUDE_HOURS = 48.0
import os
# A candidate has to be a real low to be comparable. Settable because
# this floor also decides when a track is deemed to BEGIN: a low only
# enters the database once it is this deep, so "lifetime" measured
# against it is time spent deeper than the floor, not time in existence.
MIN_DEPTH_HPA = float(os.environ.get("MIN_DEPTH_HPA", "15.0"))
SYNOPTIC_HOURS = (0, 6, 12, 18)

# North Pacific, set from where the archive's own Pacific fixes are.
LAT_RANGE = (25.0, 62.0)
LON_RANGE = (140.0, 240.0)   # deg east 0-360: 140E to 120W

DEPTH_TOL = 5.0
LAT_TOL = 5.0


def archive_fixes():
    """(datetime, lat, lon 0-360) for every fix in the archive, both basins.

    Both basins, deliberately: the exclusion asks "is this low an archive
    event", and an event's basin label is not a statement about where its
    fixes are.
    """
    payload = bh.build()
    lf, ff = _low_fields(payload), _fix_fields(payload)
    out = []
    for row in payload["lows"]:
        for f in row[lf["fixes"]]:
            out.append((bh.to_dt(f[ff["date"]]), float(f[ff["lat"]]),
                        float(f[ff["lon"]]) % 360.0))
    return out


class Excluder:
    """Is a (time, place) near any archive fix? Bucketed by day so the check
    is over a handful of fixes rather than eight thousand."""

    def __init__(self, fixes, km=EXCLUDE_KM, hours=EXCLUDE_HOURS):
        self.km, self.hours = km, hours
        self.by_day = {}
        for t, la, lo in fixes:
            self.by_day.setdefault(t.toordinal(), []).append((t, la, lo))

    def hits(self, when, lat, lon):
        span = int(self.hours // 24) + 1
        day = when.toordinal()
        for d in range(day - span, day + span + 1):
            for t, la, lo in self.by_day.get(d, ()):
                if abs((t - when).total_seconds()) > self.hours * 3600.0:
                    continue
                if great_circle_km(lat, lon, la, lo % 360.0) <= self.km:
                    return True
        return False


def find_lows(field, min_depth=MIN_DEPTH_HPA, window_deg=4.0):
    """Every closed low in the domain, described.

    A grid point is a candidate if it is the minimum of its own
    `window_deg` box; the box is a little under the smallest scale the fit
    can resolve, so two genuinely separate lows are not merged while a
    single low does not yield several candidates.
    """
    lats, lons = field.lats, field.lons
    rows = np.where((lats >= LAT_RANGE[0]) & (lats <= LAT_RANGE[1]))[0]
    cols = np.where((lons >= LON_RANGE[0]) & (lons <= LON_RANGE[1]))[0]
    sub = field.v[np.ix_(rows, cols)]
    half = int(round(window_deg / field.dlat))

    # A plain double loop over the subdomain is about 46 million box
    # comparisons per field, tens of seconds in Python; the filter is the
    # same test done once.
    local_min = sub <= minimum_filter(sub, size=2 * half + 1, mode="nearest")
    local_min[:half, :] = local_min[-half:, :] = False
    local_min[:, :half] = local_min[:, -half:] = False

    order = np.argsort(sub[local_min])
    ii, jj = np.nonzero(local_min)
    found = []
    for k in order:
        i, j = int(ii[k]), int(jj[k])
        lat, lon = float(lats[rows[i]]), float(lons[cols[j]])
        if any(great_circle_km(lat, lon, f["lat"], f["lon"]) < 600.0
               for f in found):
            continue
        d = describe_low(field, lat, lon, refine_km=100.0)
        if d["depth"] >= min_depth and np.isfinite(d["scale_km"]):
            found.append(d)
    return found


def track_back(lat, lon, when, hours=LEAD_HOURS, step=TRACK_STEP_H):
    """The low `hours` before `when`, walked back one step at a time.

    Returns the description at the earliest step plus the per-step
    displacements, so a tracker that jumped to a neighbouring low can be
    spotted afterwards instead of being trusted.
    """
    cur_lat, cur_lon, t = lat, lon % 360.0, when
    steps = []
    desc = None
    for _ in range(int(round(hours / step))):
        t = t - timedelta(hours=step)
        field = era5.mslp(t)
        desc = describe_low(field, cur_lat, cur_lon, refine_km=MAX_STEP_KM)
        steps.append(great_circle_km(cur_lat, cur_lon, desc["lat"], desc["lon"]))
        cur_lat, cur_lon = desc["lat"], desc["lon"]
    if desc is not None:
        desc = dict(desc, when=t, max_step_km=max(steps) if steps else 0.0)
    return desc


def sample_times(cases, per_case=3, seed=17):
    """Candidate observation times drawn from the cases' own (season, month)
    distribution, so the control pool cannot differ from the cases by when
    it was sampled."""
    rng = random.Random(seed)
    want = []
    for c in cases:
        for _ in range(per_case):
            want.append((c.season, c.onset.year, c.onset.month))
    out = []
    for _, year, month in want:
        day = rng.randint(1, 28)
        out.append(datetime(year, month, day, rng.choice(SYNOPTIC_HOURS),
                            tzinfo=timezone.utc))
    return sorted(set(out))
