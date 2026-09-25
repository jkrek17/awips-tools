"""track_cps.merge_close: two tracks whose current-frame centers are
within `km` of each other (MERGE_TRACK_KM by default) follow the same
low; per its own docstring, the one whose track started later stops at
its previous fix.
"""

from __future__ import annotations

import numpy as np
import pytest

import track_cps as tc


def _fix(fhr, lat, lon, mslp_hpa=990.0):
    return dict(fhr=fhr, lat=lat, lon=lon, mslp_hpa=mslp_hpa)


def _track(name, seed_lat, seed_lon, fixes):
    tr = tc.Track(f"{name}:{seed_lat},{seed_lon}")
    tr.fixes = fixes
    return tr


def test_later_starting_track_stops_when_within_merge_distance():
    lat, lon = 35.0, -70.0
    near_lon = lon + 1.0  # about 90 km east at this latitude, well under MERGE_TRACK_KM (150 km)
    km_apart = float(tc.gc_km(lat, lon, lat, near_lon))
    assert km_apart < tc.MERGE_TRACK_KM

    early = _track("EARLY", lat, lon, [_fix(0, lat, lon), _fix(12, lat, lon)])
    late = _track("LATE", lat, near_lon, [_fix(6, lat, near_lon), _fix(12, lat, near_lon)])

    out = tc.merge_close([early, late], fhr=12)

    assert len(out) == 1
    stopped, kept, dist = out[0]
    assert stopped is late
    assert kept is early
    assert dist == pytest.approx(km_apart, abs=1.0)

    assert late.done is True
    assert late.merged == (early.name, 12, pytest.approx(km_apart, abs=1.0))
    # The later track's current fix was popped: only its earlier fix (fhr=6) remains.
    assert len(late.fixes) == 1
    assert late.fixes[-1]["fhr"] == 6

    # The earlier-starting, kept track is untouched.
    assert early.done is False
    assert early.merged is None
    assert len(early.fixes) == 2


def test_tracks_farther_than_km_are_both_kept():
    lat, lon = 35.0, -70.0
    far_lon = lon + 10.0  # roughly 900 km east: outside MERGE_TRACK_KM
    a = _track("A", lat, lon, [_fix(0, lat, lon), _fix(6, lat, lon)])
    b = _track("B", lat, far_lon, [_fix(0, lat, far_lon), _fix(6, lat, far_lon)])

    out = tc.merge_close([a, b], fhr=6)

    assert out == []
    assert a.done is False and b.done is False
    assert len(a.fixes) == 2 and len(b.fixes) == 2


def test_custom_km_overrides_default():
    lat, lon = 35.0, -70.0
    near_lon = lon + 1.0
    km_apart = float(tc.gc_km(lat, lon, lat, near_lon))

    early = _track("EARLY", lat, lon, [_fix(0, lat, lon)])
    late = _track("LATE", lat, near_lon, [_fix(0, lat, near_lon)])
    # Same start hour: merge_close's own tie-break falls back to shallower
    # MSLP first, then to later list position -- both fixes here share the
    # same fhr=0 start, so give `late` (later in the list) a shallower
    # (higher) MSLP to make it the one that stops under this tie-break.
    late.fixes[0]["mslp_hpa"] = early.fixes[0]["mslp_hpa"] + 5.0

    # With a km smaller than the actual separation, nothing merges.
    out_small = tc.merge_close([early, late], fhr=0, km=km_apart / 2.0)
    assert out_small == []

    # With a km larger than the separation, the later-tie-break track stops.
    out_big = tc.merge_close([early, late], fhr=0, km=km_apart * 2.0)
    assert len(out_big) == 1
    assert out_big[0][0] is late
