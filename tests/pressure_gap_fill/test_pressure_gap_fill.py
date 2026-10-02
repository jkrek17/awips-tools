#!/usr/bin/env python3
"""Checks for GFE/utilities/PressureGapFill.py.

The module fills the strip between a chart's southern edge (17N) and the GFE
grid's southern edge (30N) with a seam-matched blend of global model pmsl.
Outside AWIPS there is no DataAccessLayer, so a fake one stands in: it holds
analytic pmsl fields per model, answers parameter, level and time queries the
way the real one does, and records every request so the tests can check what
was asked for.

    python3 test_pressure_gap_fill.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.join(HERE, "..", "..", "GFE", "utilities")
_BUNDLE = os.path.join(HERE, "..")
sys.path.insert(0, _REPO if os.path.isfile(
    os.path.join(_REPO, "PressureGapFill.py")) else _BUNDLE)

import PressureGapFill as G                                    # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# A fake DataAccessLayer
# ---------------------------------------------------------------------------

VALID = 1790000000.0            # the chart's valid time, epoch seconds


class FakeDate(object):
    def __init__(self, epoch):
        self.epoch = epoch

    def getTime(self):
        return self.epoch * 1000.0


class FakeDataTime(object):
    def __init__(self, ref, fcst):
        self.ref, self.fcst = ref, fcst

    def getRefTime(self):
        return FakeDate(self.ref)

    def getFcstTime(self):
        return self.fcst


class FakeGrid(object):
    def __init__(self, lon, lat, data):
        self.lon, self.lat, self.data = lon, lat, data

    def getLatLonCoords(self):
        return self.lon, self.lat

    def getRawData(self):
        return self.data


class FakeRequest(object):
    def __init__(self):
        self.location = self.param = self.level = self.envelope = None

    def setDatatype(self, kind):
        self.kind = kind

    def setLocationNames(self, name):
        self.location = name

    def setParameters(self, param):
        self.param = param

    def setLevels(self, level):
        self.level = level

    def setEnvelope(self, env):
        self.envelope = env


class FakeDAL(object):
    """Models keyed by DAL location; each a dict of what it offers."""

    def __init__(self, models):
        self.models = models
        self.requests = []

    def newDataRequest(self):
        return FakeRequest()

    def getAvailableParameters(self, req):
        return self.models[req.location]["params"]

    def getAvailableLevels(self, req):
        return self.models[req.location]["levels"]

    def getAvailableTimes(self, req):
        out = []
        for ref, fcsts in self.models[req.location]["runs"]:
            out.extend(FakeDataTime(ref, f) for f in fcsts)
        return out

    def getGridData(self, req, times):
        self.requests.append((req.location, req.param, req.level,
                              req.envelope, times[0].ref))
        model = self.models[req.location]
        w, s, e, n = req.envelope
        res = model.get("res", 0.25)
        lon1d = np.arange(w, e + res / 2.0, res)
        lat1d = np.arange(s, n + res / 2.0, res)
        lon, lat = np.meshgrid(lon1d, lat1d)
        data = model["field"](lon, lat)
        if model.get("pascals"):
            data = data * 100.0
        return [FakeGrid(lon, lat, data)]


def model(field, params=("PMSL",), levels=("0.0MSL",), runs=None,
          pascals=True, res=0.25):
    return {"field": field, "params": list(params), "levels": list(levels),
            "runs": runs or [(VALID - 12 * 3600, [12 * 3600])],
            "pascals": pascals, "res": res}


def gfeGrid(west, east, south=30.0, north=60.0, res=0.5):
    """A Mercator-style GFE grid in -180..180 longitudes, bottom row first."""
    lon1d = np.arange(west, east + res / 2.0, res)
    lat1d = np.arange(south, north + res / 2.0, res)
    lon, lat = np.meshgrid(lon1d, lat1d)
    return lat, ((lon + 180.0) % 360.0) - 180.0


# Analytic pmsl fields (mb), smooth enough that linear interpolation is
# near-exact, distinct enough per model that a blend is checkable.
def gfsField(lon, lat):
    return 1012.0 + 0.10 * (lat - 20.0) + 0.02 * np.sin(np.radians(lon))


def ecmwfField(lon, lat):
    return gfsField(lon, lat) + 2.0


def typhoon(centerLat, centerLon, depth):
    def field(lon, lat):
        dLon = ((lon - centerLon + 180.0) % 360.0) - 180.0
        r2 = (lat - centerLat) ** 2 + (dLon * np.cos(np.radians(lat))) ** 2
        return gfsField(lon, lat) - depth * np.exp(-r2 / (2.0 * 1.5 ** 2))
    return field


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_regrid_and_blend():
    print("\ntest_regrid_and_blend")
    lon1d = np.arange(-80.0, -20.0 + 0.25, 0.5)
    lat1d = np.arange(15.0, 32.0 + 0.25, 0.5)
    sLon, sLat = np.meshgrid(lon1d, lat1d)
    linear = 1000.0 + 0.5 * sLat + 0.1 * sLon
    tLon, tLat = np.meshgrid(np.arange(-79.0, -21.0, 0.25),
                             np.arange(17.0, 30.0, 0.25))
    out = G.regrid(sLon, sLat, linear, tLon, tLat)
    check("a linear field regrids exactly",
          float(np.nanmax(np.abs(out - (1000.0 + 0.5 * tLat + 0.1 * tLon))))
          < 1e-6)
    outside = G.regrid(sLon, sLat, linear, np.array([[0.0]]),
                       np.array([[0.0]]))
    check("a point outside the source comes back NaN",
          bool(np.isnan(outside).all()))

    a = np.array([[1.0, 2.0], [np.nan, 4.0]])
    b = np.array([[3.0, np.nan], [np.nan, 6.0]])
    blended = G.blendFields([a, b])
    check("the blend is the equal-weight mean", blended[0, 0] == 2.0)
    check("a model with no data there is left out, not counted as zero",
          blended[0, 1] == 2.0)
    check("nowhere covered stays NaN", bool(np.isnan(blended[1, 0])))


def test_regrid_both_kinds_of_grid():
    print("\ntest_regrid_both_kinds_of_grid")
    plane = lambda x, y: 1000.0 + 0.3 * x + 0.2 * y
    tLon, tLat = np.meshgrid(np.arange(125.0, 155.0, 0.7),
                             np.arange(12.0, 28.0, 0.7))
    y, x = np.mgrid[10.0:30.01:0.25, 120.0:160.01:0.25]
    check("a lat/lon grid goes the fast way",
          G._onLatLonGrid(x.ravel(), y.ravel(), plane(x, y).ravel())
          is not None)
    err = np.nanmax(np.abs(G.regrid(x, y, plane(x, y), tLon, tLat) -
                           plane(tLon, tLat)))
    check("and is exact on a plane", err < 1e-9, "%.2g" % err)
    # Two envelopes meeting at the dateline both carry the 180 column.
    west = (x <= 140.0)
    east = (x >= 140.0)
    lon2 = np.concatenate([x[west], x[east]])
    lat2 = np.concatenate([y[west], y[east]])
    err = np.nanmax(np.abs(G.regrid(lon2, lat2, plane(lon2, lat2), tLon,
                                    tLat) - plane(tLon, tLat)))
    check("a column shared where two envelopes meet is fine", err < 1e-9)
    skew = x + 0.4 * np.sin(np.radians(y * 20.0))
    check("a projected grid is not mistaken for one",
          G._onLatLonGrid(skew.ravel(), y.ravel(), plane(skew, y).ravel())
          is None)
    err = np.nanmax(np.abs(G.regrid(skew, y, plane(skew, y), tLon, tLat) -
                           plane(tLon, tLat)))
    check("and still interpolates, by triangulation", err < 1e-9)
    out = G.regrid(x, y, plane(x, y), np.array([170.0, 140.0]),
                   np.array([20.0, 40.0]))
    check("outside the source is NaN", np.isnan(out).all())


def test_southern_edge_and_seam():
    print("\ntest_southern_edge_and_seam")
    lat, lon = gfeGrid(-80.0, -20.0)
    pmsl = gfsField(lon, lat) + 4.0            # the forecaster's grid
    tLon1d = np.arange(-80.0, -20.0 + 0.125, 0.25)
    edgeLat, edgeVal = G.southernEdge(lat, lon, pmsl, tLon1d, False, 0.25)
    check("the edge is 30N all the way across",
          bool(np.allclose(edgeLat, 30.0)), str(edgeLat[:4]))
    check("the edge pmsl is the GFE bottom row",
          abs(edgeVal[0] - pmsl[0, 0]) < 1e-9)

    tLat1d = np.arange(17.0, 30.0 + 0.125, 0.25)
    tLon2d, tLat2d = np.meshgrid(tLon1d, tLat1d)
    modelField = gfsField(tLon2d, tLat2d)     # 4 mb under the grid
    matched, corr = G.seamMatch(modelField, tLat1d, edgeLat, edgeVal)
    check("on the seam the gap equals the forecaster's grid",
          float(np.max(np.abs(matched[-1] - edgeVal))) < 0.05,
          "%.3f" % float(np.max(np.abs(matched[-1] - edgeVal))))
    fade = tLat1d <= 30.0 - G.SEAM_FADE_DEG
    check("SEAM_FADE_DEG south of the seam the model is untouched",
          float(np.max(np.abs(matched[fade] - modelField[fade]))) < 1e-9)
    check("the correction applied is the grid-model difference",
          bool(np.allclose(corr, 4.0, atol=0.05)), str(corr[:3]))


def test_atlantic_gap_blend():
    print("\ntest_atlantic_gap_blend")
    lat, lon = gfeGrid(-80.0, -20.0)
    pmsl = gfsField(lon, lat) + 1.0            # grid sits between the models
    dal = FakeDAL({"gfs0p25": model(gfsField),
                   "ecmwf0p25": model(ecmwfField)})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS", "ECMWF"],
                             dal=dal)
    check("the gap is built", gap.hasGap())
    check("both models were used",
          [m for m, _ in gap.used] == ["GFS", "ECMWF"], str(gap.used))
    check("an Atlantic gap is one piece", len(gap.pieces) == 1)
    piece = gap.pieces[0]
    check("it runs from 17N to the grid edge",
          abs(piece.lat.min() - 17.0) < 1e-9 and
          abs(piece.lat.max() - 30.0) < 1e-9,
          "%.2f..%.2f" % (piece.lat.min(), piece.lat.max()))
    check("nothing is covered on a grid whose edge is a parallel",
          not piece.covered.any())
    check("no NaN for the site's smoother", bool(np.isfinite(piece.filled).all()))

    deep = piece.lat <= 30.0 - G.SEAM_FADE_DEG
    expected = gfsField(piece.lon, piece.lat) + 1.0      # mean of +0 and +2
    check("away from the seam it is the equal-weight blend",
          float(np.max(np.abs(piece.filled[deep] - expected[deep]))) < 0.01)
    check("the requests asked for pmsl at MSL",
          all(r[1] == "PMSL" and r[2] == "0.0MSL" for r in dal.requests))


def test_pacific_dateline():
    print("\ntest_pacific_dateline")
    # 160E across the dateline to 110W, as the Pacific chart is clipped.
    lat, lon = gfeGrid(160.0, 250.0)
    pmsl = gfsField(lon, lat)
    dal = FakeDAL({"gfs0p25": model(gfsField)})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"], dal=dal)

    check("a dateline gap is split into two pieces", len(gap.pieces) == 2,
          str(len(gap.pieces)))
    westPiece, eastPiece = gap.pieces
    check("the west piece runs to 180",
          abs(westPiece.lon.max() - 180.0) < 1e-9, str(westPiece.lon.max()))
    check("the east piece starts at -180 in -180..180 longitudes",
          abs(eastPiece.lon.min() + 180.0) < 1e-9 and
          eastPiece.lon.max() <= -110.0 + 1e-9,
          "%.2f..%.2f" % (eastPiece.lon.min(), eastPiece.lon.max()))
    check("both keep the 180 column so contours meet there",
          bool(np.allclose(westPiece.filled[:, -1], eastPiece.filled[:, 0])))
    check("the DAL was asked for each side of the dateline separately",
          sorted((r[3][0], r[3][2]) for r in dal.requests) ==
          [(-180.0, -109.0), (159.0, 180.0)],
          str([(r[3][0], r[3][2]) for r in dal.requests]))


def test_grid_given_in_0_360():
    print("\ntest_grid_given_in_0_360")
    # A Pacific grid handed over in 0..360 has no jump - its gap should not
    # grow one, or the gap's isobars and Lows land in a different longitude
    # space from the rest of the chart.
    lat, lon = gfeGrid(160.0, 250.0)
    lon360 = np.where(lon < 0.0, lon + 360.0, lon)
    storm = typhoon(21.0, 200.0, 30.0)
    dal = FakeDAL({"gfs0p25": model(storm)})
    gap = G.buildGapPressure(lat, lon360, gfsField(lon360, lat), VALID,
                             ["GFS"], dal=dal)
    check("a 0..360 grid gets one unsplit piece", len(gap.pieces) == 1,
          str(len(gap.pieces)))
    check("in 0..360, like the grid",
          abs(gap.pieces[0].lon.min() - 160.0) < 1e-9 and
          abs(gap.pieces[0].lon.max() - 250.0) < 1e-9,
          "%.1f..%.1f" % (gap.pieces[0].lon.min(), gap.pieces[0].lon.max()))
    check("the whole field too",
          gap.whole.lon.min() >= 0.0 and gap.whole.lon.max() > 180.0)
    i, j = np.unravel_index(np.argmin(gap.whole.filled), gap.whole.filled.shape)
    lons, lats, vals = gap.pickExtrema([gap.whole.lon[i, j]],
                                       [gap.whole.lat[i, j]],
                                       [gap.whole.filled[i, j]])
    check("and its Lows come back in 0..360",
          len(lons) == 1 and abs(lons[0] - 200.0) <= 0.3, str(lons))
    check("the DAL is still asked in -180..180, split at the dateline",
          sorted((r[3][0], r[3][2]) for r in dal.requests) ==
          [(-180.0, -109.0), (159.0, 180.0)],
          str([(r[3][0], r[3][2]) for r in dal.requests]))


def test_wpac_typhoon():
    print("\ntest_wpac_typhoon")
    # A 40 mb typhoon at 20N 140E, well inside the gap, on a domain that
    # reaches 130E so the storm is on the chart.
    storm = typhoon(20.0, 140.0, 40.0)
    lat, lon = gfeGrid(130.0, 250.0)
    pmsl = gfsField(lon, lat)
    dal = FakeDAL({"gfs0p25": model(storm)})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"], dal=dal)
    piece = gap.pieces[0]
    i, j = np.unravel_index(np.argmin(piece.filled), piece.filled.shape)
    check("the typhoon's center is in the gap where the model put it",
          abs(piece.lat[i, j] - 20.0) <= 0.25 and
          abs(piece.lon[i, j] - 140.0) <= 0.25,
          "%.2fN %.2fE" % (piece.lat[i, j], piece.lon[i, j]))
    check("at full depth - the seam correction does not reach it",
          abs(piece.filled[i, j] - storm(140.0, 20.0)) < 0.5,
          "%.1f vs %.1f" % (piece.filled[i, j], storm(140.0, 20.0)))
    check("its center is in the gap for the Lows",
          gap.isInGap(piece.lat[i, j], piece.lon[i, j]))
    check("as formatted strings too",
          gap.isInGap("%.2f" % piece.lat[i, j], "%.2f" % piece.lon[i, j]))
    check("a center hard against the seam is left to the GFE grid",
          not gap.isInGap(29.6, 140.0))
    check("a center north of the seam is never the gap's",
          not gap.isInGap(35.0, 140.0))


def test_extrema_across_the_dateline():
    print("\ntest_extrema_across_the_dateline")
    # A typhoon right on 180: in the split pieces it would sit on the cut
    # edge of both.  The whole field holds it as one interior center.
    storm = typhoon(21.0, 180.0, 30.0)
    lat, lon = gfeGrid(160.0, 250.0)
    gap = G.buildGapPressure(lat, lon, gfsField(lon, lat), VALID, ["GFS"],
                             dal=FakeDAL({"gfs0p25": model(storm)}))
    whole = gap.whole
    check("the whole field is unsplit, in -180..180 like getLatLonGrids",
          whole.lon.shape[1] == sum(p.lon.shape[1] for p in gap.pieces) - 1
          and whole.lon.min() >= -180.0 and whole.lon.max() <= 180.0)
    i, j = np.unravel_index(np.argmin(whole.filled), whole.filled.shape)
    lons, lats, vals = gap.pickExtrema([whole.lon[i, j]], [whole.lat[i, j]],
                                       [whole.filled[i, j]])
    check("the typhoon on the dateline is kept once",
          len(lons) == 1, str(lons))
    check("with its longitude back in -180..180",
          len(lons) == 1 and abs(abs(lons[0]) - 180.0) < 0.3, str(lons))

    # Artifacts at the gap's other edges are dropped, the seam is respected,
    # and strings are accepted.
    lons, lats, vals = gap.pickExtrema(
        ["160.5", 200.0, 200.0, 200.0], ["20", 17.2, 29.5, 22.0],
        [1000.0, 1001.0, 1002.0, 1003.0])
    check("edge artifacts and seam centers go, a real one stays",
          list(vals) == [1003.0], str(vals))
    check("and the kept one is in -180..180",
          abs(lons[0] + 160.0) < 1e-9, str(lons))


def test_dal_details():
    print("\ntest_dal_details")
    lat, lon = gfeGrid(-80.0, -20.0)
    pmsl = gfsField(lon, lat)

    # Parameter and level naming differ by model: the first offered is used.
    dal = FakeDAL({"Canadian-NH": model(gfsField, params=("PRMSL", "T"),
                                        levels=("0.0SFC",))})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["CMC"], dal=dal)
    check("a model offering PRMSL at 0.0SFC is still read",
          gap.hasGap() and dal.requests[0][1:3] == ("PRMSL", "0.0SFC"),
          str(dal.requests[:1]))

    # Newest run with the valid time wins; one without it is passed over.
    runs = [(VALID - 24 * 3600, [24 * 3600]),       # 24h-old run, valid
            (VALID - 6 * 3600, [6 * 3600]),         # newest run, valid
            (VALID, [6 * 3600])]                    # newer still, wrong time
    dal = FakeDAL({"gfs0p25": model(gfsField, runs=runs)})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"], dal=dal)
    check("the newest run valid at the chart's time is used",
          dal.requests[0][4] == VALID - 6 * 3600, str(dal.requests[0][4]))
    check("and reported", gap.used[0][1] == VALID - 6 * 3600)

    # Already in mb: left alone.
    dal = FakeDAL({"gfs0p25": model(gfsField, pascals=False)})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"], dal=dal)
    check("a field already in mb is not divided again",
          900.0 < float(np.nanmean(gap.pieces[0].filled)) < 1100.0)


def test_nothing_breaks_the_chart():
    print("\ntest_nothing_breaks_the_chart")
    lat, lon = gfeGrid(-80.0, -20.0)
    pmsl = gfsField(lon, lat)

    dal = FakeDAL({"gfs0p25": model(gfsField,
                                    runs=[(VALID, [12 * 3600])])})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"], dal=dal)
    check("no run valid at the time: no gap, and no exception",
          not gap.hasGap())
    check("with the reason recorded", gap.skipped and
          "no gfs0p25 run" in gap.skipped[0][1], str(gap.skipped))

    dal = FakeDAL({"gfs0p25": model(gfsField, params=("T",))})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS", "UKMET"], dal=dal)
    check("a model with no pmsl and an unknown model are both skipped",
          not gap.hasGap() and len(gap.skipped) == 2, str(gap.skipped))

    dal = FakeDAL({"gfs0p25": model(gfsField),
                   "ecmwf0p25": model(gfsField, params=("T",))})
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS", "ECMWF"], dal=dal)
    check("one model failing leaves the blend to the others",
          gap.hasGap() and [m for m, _ in gap.used] == ["GFS"])

    lat2, lon2 = gfeGrid(-80.0, -20.0, south=15.0)
    gap = G.buildGapPressure(lat2, lon2, gfsField(lon2, lat2), VALID,
                             ["GFS"], dal=FakeDAL({"gfs0p25": model(gfsField)}))
    check("a grid that already reaches 17N needs no gap", not gap.hasGap())

    gap = G.buildGapPressure(lat, lon, pmsl, VALID, [],
                             dal=FakeDAL({}))
    check("no models picked: no gap", not gap.hasGap())


def warningStorm(lat, lon, vmax=100.0, anchorMb=None, name="TESTER"):
    """A storm dict as TCPressure.stormsAt hands them over."""
    storm = {"lat": lat, "lon": lon, "vmax": vmax, "a": 5.0, "rm": 18.0,
             "ri": 60.0, "x1": 0.6, "x2": 0.5, "r34": 140.0, "name": name}
    if anchorMb:
        storm["anchor"] = (dict(storm), anchorMb)
    return storm


def test_typhoon_moved_to_the_warning():
    print("\ntest_typhoon_moved_to_the_warning")
    # The models have a 40 mb typhoon at 21.5N 140.5E; the warning says
    # 19.5N 137.5E, 950 mb.
    lat, lon = gfeGrid(130.0, 250.0)
    pmsl = gfsField(lon, lat)
    wrong = model(typhoon(21.5, 140.5, 40.0))
    storm = warningStorm(19.5, 137.5, anchorMb=950.0)
    gap = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"],
                             dal=FakeDAL({"gfs0p25": wrong}), storms=[storm])
    piece = gap.pieces[0]
    i, j = np.unravel_index(np.argmin(piece.filled), piece.filled.shape)
    check("the gap's low is where the warning has it",
          abs(piece.lat[i, j] - 19.5) <= 0.25 and
          abs(piece.lon[i, j] - 137.5) <= 0.25,
          "%.2fN %.2fE" % (piece.lat[i, j], piece.lon[i, j]))
    check("as deep as the warning says",
          abs(piece.filled[i, j] - 950.0) < 1.5, "%.1f" % piece.filled[i, j])

    # The same storm put into a model with no typhoon of its own: whatever
    # differs is what the removal left behind.
    clean = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"],
                               dal=FakeDAL({"gfs0p25": model(gfsField)}),
                               storms=[storm])
    left = np.abs(piece.filled - clean.pieces[0].filled).max()
    check("nothing of the model's typhoon is left", left < 0.5,
          "%.2f mb" % left)

    report = gap.tcReport
    check("one storm reported", len(report) == 1, str(report))
    if report:
        e = report[0]
        check("the model's low found where the model had it",
              e["background"] is not None and
              abs(e["background"][0] - 21.5) <= 0.3 and
              abs(e["background"][1] - 140.5) <= 0.3, str(e["background"]))
        check("with the distance it was off", 180.0 < e["offsetNm"] < 230.0,
              "%.0f nm" % e["offsetNm"])
        check("and the storm itself in the gap", e["inGap"] is True)
        check("a status line for it", "TESTER" in gap.tcLines()[0],
              gap.tcLines()[0])

    edgeRow = piece.filled[-1]
    check("still matched to the GFE grid at the seam",
          np.abs(edgeRow - gfsField(piece.lon[-1], piece.lat[-1])).max()
          < 0.1)

    far = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"],
                             dal=FakeDAL({"gfs0p25": wrong}),
                             storms=[warningStorm(50.0, 160.0)])
    none = G.buildGapPressure(lat, lon, pmsl, VALID, ["GFS"],
                              dal=FakeDAL({"gfs0p25": wrong}))
    check("a storm far north of the gap changes nothing",
          far.tcReport == [] and
          np.array_equal(far.pieces[0].filled, none.pieces[0].filled))

    # A storm at 33N is the GFE grid's: the grid carries it already, at the
    # warning position.  Its outer isobars reach the gap, and with the
    # models moved to match, the gap meets the grid with almost nothing for
    # the seam to correct.
    import TCPressure
    inGrid = warningStorm(33.0, 150.0)
    gridded, _ = TCPressure.relocateStorms(pmsl, lat, lon, [inGrid])
    north = G.buildGapPressure(lat, lon, gridded, VALID, ["GFS"],
                               dal=FakeDAL({"gfs0p25": model(gfsField)}),
                               storms=[inGrid])
    unmoved = G.buildGapPressure(lat, lon, gridded, VALID, ["GFS"],
                                 dal=FakeDAL({"gfs0p25": model(gfsField)}))
    check("a storm in the GFE grid just north is reported as such",
          len(north.tcReport) == 1 and north.tcReport[0]["inGap"] is False)
    k = np.argmin(np.abs(north.pieces[0].lon[0] - 150.0))
    seamFix = np.abs(north.seamCorrection[k - 8:k + 9]).max()
    unmovedFix = np.abs(unmoved.seamCorrection[k - 8:k + 9]).max()
    check("its outer isobars carry on into the gap, so the seam has "
          "almost nothing to correct",
          seamFix < 0.3 and unmovedFix > 1.5,
          "%.2f mb, vs %.2f without" % (seamFix, unmovedFix))


def test_typhoon_moved_across_the_dateline():
    print("\ntest_typhoon_moved_across_the_dateline")
    # Grid in -180..180; the model has it at 21N 179E, the warning at
    # 22N 178W - given in -180..180 as TCWind_JTWC hands them.
    lat, lon = gfeGrid(130.0, 250.0)
    gap = G.buildGapPressure(lat, lon, gfsField(lon, lat), VALID, ["GFS"],
                             dal=FakeDAL({"gfs0p25":
                                          model(typhoon(21.0, 179.0, 35.0))}),
                             storms=[warningStorm(22.0, -178.0, 90.0)])
    w = gap.whole
    i, j = np.unravel_index(np.argmin(w.filled), w.filled.shape)
    check("the low is at the warning position, east of the dateline",
          abs(w.lat[i, j] - 22.0) <= 0.25 and abs(w.lon[i, j] + 178.0) <= 0.25,
          "%.2f %.2f" % (w.lat[i, j], w.lon[i, j]))
    e = gap.tcReport[0] if gap.tcReport else {}
    check("reported in the warning's own longitudes",
          e.get("lon") == -178.0 and e.get("background") and
          abs(e["background"][1] - 179.0) <= 0.3, str(e.get("background")))


def main():
    test_regrid_and_blend()
    test_regrid_both_kinds_of_grid()
    test_southern_edge_and_seam()
    test_atlantic_gap_blend()
    test_pacific_dateline()
    test_grid_given_in_0_360()
    test_wpac_typhoon()
    test_extrema_across_the_dateline()
    test_dal_details()
    test_nothing_breaks_the_chart()
    test_typhoon_moved_to_the_warning()
    test_typhoon_moved_across_the_dateline()
    print("")
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
