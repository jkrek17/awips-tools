"""export_web's frame-to-frame low tracker.

See export_web.py, section "# ---- tracks": link_tracks joins each
frame's non-terrain closed-low centers to the next frame's closest
unclaimed candidate within TRACK_REACH_KM per 6 h elapsed (predicted
from half the track's last motion), closest pairs first; a track may
skip up to TRACK_GAP_FRAMES frames; a track shorter than
TRACK_MIN_FRAMES points is dropped. match_collection pairs a track
with the daily collection storm sharing the most valid times (at
least two, and at least half of the shared hours) within
TRACK_MATCH_KM. build_storms runs link_tracks over an export's frames,
names each track after the collection storm it matches or L01, L02,
..., appends unmatched collection storms as C01, C02, ..., and writes
a "track" property onto the linked lows.geojson centers.

No GRIB or network: centers are built by hand in the same shape
lows_features writes them (kind, id, lat, lon, mslp, hvtl, hvtu, hb,
idx, cls, psfc, terrain, radius_km, name), and build_storms is driven
against lows.geojson files written straight to tmp_path.
"""

from __future__ import annotations

import datetime as dt
import json
import math

import pytest

import export_web as ew
import track_cps as tc

EARTH_R_KM = tc.EARTH_R_KM
BASE_VALID = dt.datetime(2026, 9, 24, 0, tzinfo=dt.timezone.utc)


def valid_of(fhr: int) -> str:
    return ew.iso(BASE_VALID + dt.timedelta(hours=fhr))


def east_deg(lat: float, km: float) -> float:
    """Degrees of longitude at latitude `lat` that cover `km` along a
    great circle, using track_cps's own gc_km so the distance moved
    between two centers matches exactly what the tracker measures."""
    lo, hi = 0.0, 180.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if float(tc.gc_km(lat, 0.0, lat, mid)) < km:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def center(id_, lat, lon, mslp=990.0, cls=5, terrain=False, name=None) -> dict:
    """A center dict in exactly the shape lows_features writes (the
    "kind": "center" properties dict)."""
    return {
        "kind": "center", "id": id_, "lat": round(lat, 2), "lon": round(lon, 2),
        "mslp": round(mslp, 1), "hvtl": 10.0, "hvtu": -20.0, "hb": 5.0, "idx": 1.2,
        "cls": cls, "psfc": 1005.0, "terrain": terrain, "radius_km": 200,
        "name": tc.CLASS_SHORT[cls],
    }


def frame(fhr: int, centers: list[dict]) -> dict:
    return {"fhr": fhr, "valid": valid_of(fhr), "centers": centers}


# ------------------------------------------------------------------ link_tracks: steady motion


def test_steady_300km_motion_over_8_frames_is_one_track():
    lat = 0.0
    step_deg = east_deg(lat, 300.0)
    fhrs = list(range(0, 48, 6))  # 8 frames, 6 h apart
    frames = [frame(fhr, [center(1, lat, k * step_deg, mslp=990.0 - k)]) for k, fhr in enumerate(fhrs)]

    tracks = ew.link_tracks(frames)

    assert len(tracks) == 1
    pts = tracks[0]
    assert len(pts) == 8
    assert [p["fhr"] for p in pts] == fhrs  # already ordered by fhr
    assert all(p["id"] == 1 for p in pts)  # frame center id kept on every point
    for k, p in enumerate(pts):
        assert p["lat"] == pytest.approx(lat)
        # center() rounds lat/lon to 2 decimals, same as lows_features itself.
        assert p["lon"] == pytest.approx(k * step_deg, abs=0.01)


# ------------------------------------------------------------------ link_tracks: separation


def test_two_lows_2000km_apart_never_merge():
    lat = 0.0
    sep_deg = east_deg(lat, 2000.0)
    fhrs = list(range(0, 30, 6))  # 5 frames
    frames = [
        frame(fhr, [center(1, lat, 0.0, mslp=980.0), center(2, lat, sep_deg, mslp=995.0)])
        for fhr in fhrs
    ]

    tracks = ew.link_tracks(frames)

    assert len(tracks) == 2
    lons = sorted(round(pts[0]["lon"]) for pts in tracks)
    assert lons == [0, round(sep_deg)]
    for pts in tracks:
        assert len(pts) == 5
        lon0 = pts[0]["lon"]
        for p in pts:
            assert p["lon"] == pytest.approx(lon0, abs=1e-6)  # each track stayed on its own low


# ------------------------------------------------------------------ link_tracks: min_frames


def test_track_shorter_than_min_frames_is_dropped_exact_is_kept():
    lat = 0.0
    sep_deg = east_deg(lat, 3000.0)  # far enough apart that the two never interact
    short_fhrs = [0, 6, 12, 18]  # 4 frames: one short of TRACK_MIN_FRAMES (5)
    long_fhrs = [0, 6, 12, 18, 24]  # exactly TRACK_MIN_FRAMES

    frames = []
    for fhr in long_fhrs:
        cs = [center(2, lat, sep_deg, mslp=1000.0)]
        if fhr in short_fhrs:
            cs.append(center(1, lat, 0.0, mslp=980.0))
        frames.append(frame(fhr, cs))

    tracks = ew.link_tracks(frames)

    assert len(tracks) == 1
    kept = tracks[0]
    assert len(kept) == ew.TRACK_MIN_FRAMES
    assert all(p["lon"] == pytest.approx(sep_deg, abs=0.01) for p in kept)


# ------------------------------------------------------------------ link_tracks: gap bridging


def test_one_missing_frame_is_bridged():
    lat = 0.0
    step_deg = east_deg(lat, 100.0)  # small, unambiguous motion
    fhrs = [0, 6, 12, 18, 24, 30]  # 6 nominal frames
    frames = []
    for k, fhr in enumerate(fhrs):
        cs = [] if fhr == 12 else [center(1, lat, k * step_deg, mslp=990.0)]
        frames.append(frame(fhr, cs))

    tracks = ew.link_tracks(frames)  # default min_frames=5; 5 frames present

    assert len(tracks) == 1
    pts = tracks[0]
    assert [p["fhr"] for p in pts] == [0, 6, 18, 24, 30]
    assert len(pts) == 5


def test_two_consecutive_missing_frames_starts_a_new_track():
    lat = 0.0
    fhrs = [0, 6, 12, 18, 24]
    frames = []
    for fhr in fhrs:
        cs = [] if fhr in (6, 12) else [center(1, lat, 0.0, mslp=990.0)]
        frames.append(frame(fhr, cs))

    tracks = ew.link_tracks(frames, min_frames=1)

    assert len(tracks) == 2
    lengths = sorted(len(t) for t in tracks)
    assert lengths == [1, 2]
    solo = next(t for t in tracks if len(t) == 1)
    pair = next(t for t in tracks if len(t) == 2)
    assert solo[0]["fhr"] == 0
    assert [p["fhr"] for p in pair] == [18, 24]


# ------------------------------------------------------------------ link_tracks: terrain


def test_terrain_center_is_never_linked():
    """A center flagged terrain=True is dropped from the candidates of its
    own frame (export_web.py: `cands = [c for c in fr["centers"] if not
    c.get("terrain")]`), so it neither joins nor starts a track; the
    surrounding non-terrain fixes still bridge across it like a missing
    frame."""
    lat = 0.0
    step_deg = east_deg(lat, 100.0)
    fhrs = [0, 6, 12, 18, 24, 30]
    frames = []
    for k, fhr in enumerate(fhrs):
        if fhr == 12:
            cs = [center(1, lat, k * step_deg, mslp=990.0, terrain=True)]
        else:
            cs = [center(1, lat, k * step_deg, mslp=990.0)]
        frames.append(frame(fhr, cs))

    tracks = ew.link_tracks(frames)

    assert len(tracks) == 1
    pts = tracks[0]
    assert [p["fhr"] for p in pts] == [0, 6, 18, 24, 30]  # fhr=12 (terrain) excluded


def test_lone_terrain_frame_starts_nothing():
    frames = [frame(0, [center(1, 0.0, 0.0, terrain=True)])]
    assert ew.link_tracks(frames, min_frames=1) == []


# ------------------------------------------------------------------ link_tracks: reach


def test_jump_farther_than_reach_in_6h_starts_a_new_track():
    lat = 0.0
    small_deg = east_deg(lat, 100.0)
    jump_deg = east_deg(lat, ew.TRACK_REACH_KM + 100.0)  # farther than the 600 km/6h cap
    frames = [
        frame(0, [center(1, lat, 0.0, mslp=990.0)]),
        frame(6, [center(1, lat, small_deg, mslp=990.0)]),
        frame(12, [center(1, lat, small_deg + jump_deg, mslp=990.0)]),
    ]

    tracks = ew.link_tracks(frames, min_frames=1)

    assert len(tracks) == 2
    lengths = sorted(len(t) for t in tracks)
    assert lengths == [1, 2]
    solo = next(t for t in tracks if len(t) == 1)
    assert solo[0]["fhr"] == 12


def test_jump_within_reach_stays_one_track():
    lat = 0.0
    ok_deg = east_deg(lat, ew.TRACK_REACH_KM - 50.0)
    frames = [
        frame(0, [center(1, lat, 0.0, mslp=990.0)]),
        frame(6, [center(1, lat, ok_deg, mslp=990.0)]),
    ]

    tracks = ew.link_tracks(frames, min_frames=1)

    assert len(tracks) == 1
    assert len(tracks[0]) == 2


# ------------------------------------------------------------------ match_collection


def _track_pt(fhr, lat, lon, mslp=990.0):
    return {"fhr": fhr, "valid": valid_of(fhr), "id": 1, "lat": lat, "lon": lon, "mslp": mslp,
            "cls": 5, "hvtl": 10.0, "hvtu": -20.0, "hb": 5.0, "idx": 1.2}


def _collection_pt(fhr, lat, lon, mslp=990.0):
    return {"fhr": fhr, "valid": valid_of(fhr), "lat": lat, "lon": lon, "mslp": mslp,
            "cls": 5, "hvtl": 10.0, "hvtu": -20.0, "hb": 5.0}


def _storm(name, pts):
    return {"name": name, "cycle": "2026092400", "fsu": 3, "points": pts,
            "cls_seq": [p["cls"] for p in pts], "phase_png": f"../storms/x/{name}/phase.png",
            "compare_png": None}


def test_match_collection_close_same_hours_is_returned():
    lat = 20.0
    fhrs = [0, 6, 12, 18, 24]
    track = [_track_pt(fhr, lat, fhr * 0.1) for fhr in fhrs]
    close = _storm("CLOSE", [_collection_pt(fhr, lat, fhr * 0.1 + 0.5) for fhr in fhrs])  # ~55 km east

    hit = ew.match_collection(track, [close])

    assert hit is close


def test_match_collection_other_valid_times_not_returned():
    lat = 20.0
    track = [_track_pt(fhr, lat, 0.0) for fhr in [0, 6, 12, 18, 24]]
    other_hours = _storm("OTHER_HOURS", [_collection_pt(fhr, lat, 0.0) for fhr in [30, 36, 42]])

    assert ew.match_collection(track, [other_hours]) is None


def test_match_collection_far_away_not_returned():
    lat = 20.0
    far_deg = east_deg(lat, ew.TRACK_MATCH_KM + 200.0)
    fhrs = [0, 6, 12, 18, 24]
    track = [_track_pt(fhr, lat, 0.0) for fhr in fhrs]
    far = _storm("FAR", [_collection_pt(fhr, lat, far_deg) for fhr in fhrs])

    assert ew.match_collection(track, [far]) is None


def test_match_collection_fewer_than_two_shared_hours_not_returned():
    lat = 20.0
    fhrs = [0, 6, 12, 18, 24]
    track = [_track_pt(fhr, lat, 0.0) for fhr in fhrs]
    # Only one valid time in common (fhr=0), even though it is right on top of the track.
    one_shared = _storm("ONE_SHARED", [_collection_pt(0, lat, 0.0)] + [_collection_pt(fhr, lat, 0.0) for fhr in [48, 54]])

    assert ew.match_collection(track, [one_shared]) is None


def test_match_collection_picks_best_of_several():
    lat = 20.0
    fhrs = [0, 6, 12, 18, 24]
    track = [_track_pt(fhr, lat, 0.0) for fhr in fhrs]
    close = _storm("CLOSE", [_collection_pt(fhr, lat, 0.0) for fhr in fhrs])  # all 5 hours, exact
    partial = _storm("PARTIAL", [_collection_pt(fhr, lat, 0.0) for fhr in [0, 6, 12]])  # 3 hours, exact

    assert ew.match_collection(track, [partial, close]) is close


# ------------------------------------------------------------------ build_storms


def _write_frame(out, fhr, centers):
    fdir = out / "frames" / f"f{fhr:03d}"
    fdir.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection",
          "features": [{"type": "Feature", "properties": c,
                        "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]}} for c in centers]}
    (fdir / "lows.geojson").write_text(json.dumps(fc))


def _read_frame(out, fhr):
    return json.loads((out / "frames" / f"f{fhr:03d}" / "lows.geojson").read_text())


def test_build_storms(tmp_path):
    lat_x, lat_y, lat_q = 0.0, 40.0, -40.0
    fhrs = [0, 6, 12, 18, 24]  # exactly TRACK_MIN_FRAMES frames

    # Low X: deepest track, no matching collection storm -> named L01.
    # Low Y: shallower track, matched by collection storm "AL01" -> keeps its name.
    # Low Q: appears in only one frame -> too short to become a track at all.
    for k, fhr in enumerate(fhrs):
        centers = [
            center(1, lat_x, k * 0.1, mslp=960.0, cls=0),
            center(2, lat_y, k * 0.1, mslp=985.0, cls=5),
        ]
        if fhr == 0:
            centers.append(center(3, lat_q, 0.0, mslp=1000.0, cls=6))
        _write_frame(tmp_path, fhr, centers)

    collection = [
        _storm("AL01", [_collection_pt(fhr, lat_y, k * 0.1) for k, fhr in enumerate(fhrs)]),
        _storm("UNMATCHED", [_collection_pt(fhr, 70.0, 0.0) for fhr in fhrs]),
    ]

    storms = ew.build_storms(tmp_path, fhrs, [valid_of(fhr) for fhr in fhrs], collection)

    by_id = {s["id"]: s for s in storms}
    assert set(by_id) == {"T01", "T02", "C01"}

    # Deepest first: X (960 hPa) is T01, Y (985 hPa) is T02.
    assert by_id["T01"]["min_mslp"] == pytest.approx(960.0)
    assert by_id["T02"]["min_mslp"] == pytest.approx(985.0)
    assert by_id["T01"]["source"] == "track"
    assert by_id["T02"]["source"] == "track"

    # X matched nothing collected -> L01. Y matched "AL01" -> keeps its name/fsu/diagrams.
    assert by_id["T01"]["name"] == "L01"
    assert by_id["T01"]["fsu"] is None
    assert by_id["T01"]["phase_png"] is None
    assert by_id["T01"]["compare_png"] is None

    assert by_id["T02"]["name"] == "AL01"
    assert by_id["T02"]["fsu"] == 3
    assert by_id["T02"]["phase_png"] == "../storms/x/AL01/phase.png"

    # The matched collection storm is not duplicated as its own entry.
    names = [s.get("name") for s in storms]
    assert names.count("AL01") == 1

    # The unmatched collection storm is appended as C01.
    assert by_id["C01"]["source"] == "collection"
    assert by_id["C01"]["name"] == "UNMATCHED"

    # Sorted deepest (lowest min_mslp) first among the tracks.
    ids_in_order = [s["id"] for s in storms]
    assert ids_in_order.index("T01") < ids_in_order.index("T02")

    # Each frame's lows.geojson was rewritten with "track" on the linked centers only.
    for fhr in fhrs:
        fc = _read_frame(tmp_path, fhr)
        props_by_id = {ft["properties"]["id"]: ft["properties"] for ft in fc["features"]}
        assert props_by_id[1].get("track") == "T01"
        assert props_by_id[2].get("track") == "T02"
        if fhr == 0:
            assert "track" not in props_by_id[3]  # low Q never made a track


def test_build_storms_all_unmatched_collection_when_no_tracks(tmp_path):
    fhrs = [0, 6]
    for fhr in fhrs:
        _write_frame(tmp_path, fhr, [])  # no lows at all -> no tracks possible

    collection = [_storm("LONER", [_collection_pt(fhr, 10.0, 10.0) for fhr in fhrs])]
    storms = ew.build_storms(tmp_path, fhrs, [valid_of(fhr) for fhr in fhrs], collection)

    assert len(storms) == 1
    assert storms[0]["id"] == "C01"
    assert storms[0]["source"] == "collection"
    assert storms[0]["name"] == "LONER"
