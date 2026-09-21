"""Following a low through ERA5, with a check that it was the same low.

WHY THIS EXISTS. The first tracker searched a fixed 550 km radius around the
previous position at each 6 h step. 550 km in 6 h is 48 kt of storm motion,
far more than most of these systems manage, so the search routinely reached
past the storm and took whatever deeper minimum lay inside it: 147 of 190
cases came back with a step pinned at the radius limit. Cases were described
at the position that tracker returned; controls were described exactly where
they were detected and never tracked at all. So every bit of tracker
degradation landed on the cases and none on the controls, which is enough on
its own to make cases look systematically weaker than their controls -- which
is what both analyses found.

WHAT IS DIFFERENT. Two changes and a test.

    Motion first guess. After the first step the previous displacement is
    extrapolated and the search is centred on where the low should be, not
    on where it was, so the radius only has to cover the error in that guess
    rather than the whole distance travelled.

    A radius that means something. 350 km for the first step (about 31 kt)
    and 250 km around the extrapolated point after that.

    A round trip. Track back, then track forward again from where you
    landed, and see whether you return to where you started. A track that
    changed low will not come back. Cases whose round trip misses are
    dropped rather than quietly carried into the table as a weak low that
    was never the storm.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import era5  # noqa: E402
from pressure_field import describe_low, great_circle_km, offset_point  # noqa: E402

STEP_H = 6.0
FIRST_RADIUS_KM = 350.0
GUESS_RADIUS_KM = 250.0
ROUND_TRIP_TOL_KM = 200.0


def _extrapolate(prev, cur, sign):
    """Where the low should be one step on, continuing its last motion."""
    d = great_circle_km(prev["lat"], prev["lon"], cur["lat"], cur["lon"])
    if d < 1.0:
        return cur["lat"], cur["lon"]
    dlat = cur["lat"] - prev["lat"]
    dlon = ((cur["lon"] - prev["lon"] + 180.0) % 360.0) - 180.0
    brg = np.degrees(np.arctan2(dlon * np.cos(np.radians(cur["lat"])), dlat))
    return offset_point(cur["lat"], cur["lon"], brg, d)


def track(lat, lon, when, hours, sign=-1, step=STEP_H):
    """Follow a low `hours` backward (sign -1) or forward (sign +1).

    Returns the list of per-step descriptions, each carrying the distance
    from the position that was searched around.
    """
    cur = dict(lat=float(lat), lon=float(lon) % 360.0)
    prev = None
    t = when
    out = []
    for k in range(int(round(hours / step))):
        t = t + sign * timedelta(hours=step)
        if prev is None:
            guess_lat, guess_lon, radius = cur["lat"], cur["lon"], FIRST_RADIUS_KM
        else:
            guess_lat, guess_lon = _extrapolate(prev, cur, sign)
            radius = GUESS_RADIUS_KM
        d = describe_low(era5.mslp(t), guess_lat, guess_lon, refine_km=radius)
        d["when"] = t
        d["step_km"] = great_circle_km(cur["lat"], cur["lon"], d["lat"], d["lon"])
        d["guess_miss_km"] = great_circle_km(guess_lat, guess_lon, d["lat"], d["lon"])
        out.append(d)
        prev, cur = cur, d
    return out


def track_with_round_trip(lat, lon, when, hours):
    """Track back `hours`, then forward again, and report the miss.

    Returns (description_at_the_far_end, round_trip_km) with the distance
    between where the forward track came back to and where it started. A
    track that swapped onto a neighbouring low does not return.
    """
    back = track(lat, lon, when, hours, sign=-1)
    if not back:
        return None, np.nan
    far = back[-1]
    fwd = track(far["lat"], far["lon"], far["when"], hours, sign=+1)
    if not fwd:
        return far, np.nan
    home = fwd[-1]
    return far, float(great_circle_km(lat, lon, home["lat"], home["lon"]))
