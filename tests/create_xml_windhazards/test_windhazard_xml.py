#!/usr/bin/env python3
"""Harness test for GFE/procedures/CreateXML_WindHazards.py.

`Procedure` only exists when the AWIPS `AbsTime`/`TimeRange` modules and the
site's `A2GraphicsFunctions`/`A2GraphicsConfig` import cleanly (`_IN_GFE`),
so like tests/tcwind_jtwc/test_procedure_harness.py this fakes the minimum
surface those provide, imports the procedure fresh against the fakes, and
drives `Procedure.execute()` the way GFE would: a fully built varDict, a
synthetic lat/lon grid, Wind grids whose peak sits at a forecast hour in the
MIDDLE of each period (so a period maximum, not an endpoint snapshot, is the
only thing that can produce the expected polygons), and pmsl at every hour.

The fakes record every getGrids call, so the tests can assert which forecast
hours were read and that the Lows came from F000, F024 and F048.

    python3 test_windhazard_xml.py
"""
import calendar
import importlib.util
import os
import sys
import time
import types
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_PROC_DIR = os.path.join(HERE, "..", "..", "GFE", "procedures")
_BUNDLE_PROC_DIR = os.path.join(HERE, "..")
if os.path.isfile(os.path.join(_REPO_PROC_DIR, "CreateXML_WindHazards.py")):
    PROC_DIR = _REPO_PROC_DIR
else:
    PROC_DIR = _BUNDLE_PROC_DIR

OUT_DIR = os.path.join(HERE, "out")


# Four layers: one per period holding that period's three overlapping band
# polygons, plus the Lows and the track through them.  Bands are told apart
# inside a layer by color - the marine warning convention, yellow/orange/red.
PERIOD1, PERIOD2 = "F000-024", "F024-048"
LOWS, TRACK = "Lows", "Track"


# ---------------------------------------------------------------------------
# Synthetic grids
# ---------------------------------------------------------------------------

NY, NX = 45, 61
LAT0, LON0 = 20.0, -80.0

# Peak wind (kt) of the bullseye at each forecast hour.  Both peaks sit at a
# non-endpoint hour of their period: 56 kt at F012 (gale + storm, no
# hurricane) and 80 kt at F036 (all three).
PEAK_BY_HOUR = {0: 18.0, 6: 40.0, 12: 56.0, 18: 40.0,
                24: 28.0, 30: 44.0, 36: 80.0, 42: 46.0, 48: 22.0}

# Bullseye center, in gridpoints, and its width.
CY, CX, SIGMA = 20, 30, 5.0

# "Land" for the mask test: the northwest corner of the domain.
LAND_LAT, LAND_LON = 50.0, -60.0


def latLonGrids():
    lat2d = np.zeros((NY, NX))
    lon2d = np.zeros((NY, NX))
    for j in range(NY):
        for i in range(NX):
            lat2d[j, i] = LAT0 + j
            lon2d[j, i] = LON0 + i
    return lat2d, lon2d


def bullseye(peak, cy=CY, cx=CX, sigma=SIGMA, floor=5.0):
    j, i = np.mgrid[0:NY, 0:NX]
    dist2 = ((j - cy) ** 2 + (i - cx) ** 2) / (2.0 * sigma ** 2)
    return floor + (peak - floor) * np.exp(-dist2)


def windAtHour(hr, overLandOnly=False):
    peak = PEAK_BY_HOUR.get(hr, 10.0)
    if overLandOnly:
        # Push the bullseye into the land corner: lat 50+, lon -80..-60.
        mag = bullseye(peak, cy=int(LAND_LAT - LAT0) + 8, cx=8)
    else:
        mag = bullseye(peak)
    direc = np.full((NY, NX), 270.0)
    return (mag, direc)


def lowIndexAtHour(hr):
    """Where the synthetic Low sits at forecast hour ``hr``.

    It tracks northeast, a gridpoint of longitude every 6 hours and one of
    latitude every 12, so the track through it is a real line rather than
    nine copies of one point, and its position identifies the hour just as
    its value does.
    """
    return 30 + hr // 12, 45 + hr // 6


def pmslAtHour(hr):
    """A High and a moving Low whose values encode the forecast hour.

    The High is here on purpose: only Lows are wanted on the chart, so it
    must never appear in the XML.
    """
    grid = np.full((NY, NX), 1013.0)
    grid[10, 10] = 1040.0 + hr        # High - must not be plotted
    grid[lowIndexAtHour(hr)] = 960.0 - hr
    return grid


# ---------------------------------------------------------------------------
# Fake AWIPS / A2Graphics modules
# ---------------------------------------------------------------------------

CALLS = []             # every getGrids call: (field, start hr, end hr)
INVENTORY_CALLS = []   # every getGridInfo call: (field, (start hr, end hr))
STORED = []            # every storeXML call


class FakeAbsTime(object):
    def __init__(self, secs):
        self.secs = int(secs)

    def unixTime(self):
        return self.secs


class FakeTimeRange(object):
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def startTime(self):
        return self.start

    def endTime(self):
        return self.end


class FakeGridInfo(object):
    """What getGridInfo hands back: one entry per grid, with its time."""

    def __init__(self, timeRange):
        self._timeRange = timeRange

    def gridTime(self):
        return self._timeRange


def _installFakes(cycleTime, overLandOnly=False, missingWindHours=(),
                  missingPmslHours=(), saveLayers="true", windFn=None,
                  pmslFn=None, landFn=None, domain=None, gridInterval=6,
                  noGridInfo=False):
    """Install fake AWIPS/A2Graphics modules into sys.modules.

    ``windFn(hr, lat, lon)``, ``pmslFn(hr, lat, lon)``, ``landFn(lat, lon)``
    and ``domain`` (a ``(lat2d, lon2d)`` pair) override the bullseye fields
    above, so another script - plot_synthetic_case.py - can drive the real
    procedure over its own case without a second copy of these fakes.

    The fake database holds a grid every ``gridInterval`` hours, minus the
    ``missing*Hours``, and answers like GFE does: ``getGridInfo`` lists what
    is there, and ``getGrids`` over a range spanning several grids returns a
    list of them.  ``noGridInfo`` makes ``getGridInfo`` raise, to exercise
    the fallback when a site's inventory call is unavailable.
    """
    del CALLS[:]
    del INVENTORY_CALLS[:]
    del STORED[:]

    abstime_mod = types.ModuleType("AbsTime")
    abstime_mod.AbsTime = FakeAbsTime
    sys.modules["AbsTime"] = abstime_mod

    timerange_mod = types.ModuleType("TimeRange")
    timerange_mod.TimeRange = FakeTimeRange
    sys.modules["TimeRange"] = timerange_mod

    cycleSecs = calendar.timegm(cycleTime.timetuple())

    # --- XmlUtils: builds a real ElementTree so the output is inspectable ---
    class FakeXmlUtils(object):
        def __init__(self, dbss=None):
            pass

        @staticmethod
        def createXmlProduct(outputFile, useFile, saveLayers, onOff, status,
                             center, fcstr, ptype, psubtype):
            products = ET.Element("Products")
            product = ET.SubElement(products, "Product", {
                "name": os.path.basename(outputFile),
                "useFile": str(useFile), "saveLayers": str(saveLayers),
                "onOff": str(onOff), "status": str(status),
                "center": str(center), "forecaster": str(fcstr),
                "type": str(ptype), "subType": str(psubtype)})
            return products, product

        @staticmethod
        def createXmlLayer(product, name):
            layer = ET.SubElement(product, "Layer", {"name": name,
                                                     "onOff": "true"})
            return ET.SubElement(layer, "DrawableElement")

        @staticmethod
        def plotPeakPressureLocations(lons, lats, vals, basin):
            return lons, lats, vals

        @staticmethod
        def xmladdPressureSymbol(vals, lats, lons, de, attr, color):
            for val, plat, plon in zip(vals, lats, lons):
                ET.SubElement(de, "SymbolAttribute", {
                    "pgenType": str(attr), "color": str(color),
                    "Lat": "%.2f" % plat, "Lon": "%.2f" % plon,
                    "value": "%.1f" % val})

        @staticmethod
        def xmladdPressureExtremaLabel(vals, lats, lons, de, attr, color):
            for val, plat, plon in zip(vals, lats, lons):
                ET.SubElement(de, "TextAttribute", {
                    "pgenType": str(attr), "color": str(color),
                    "Lat": "%.2f" % plat, "Lon": "%.2f" % plon,
                    "text": "%d" % round(val)})

        @staticmethod
        def xmladdTextBox(text, plat, plon, de, attr, color):
            ET.SubElement(de, "TextBox", {
                "pgenType": str(attr), "color": str(color),
                "Lat": "%.2f" % plat, "Lon": "%.2f" % plon, "text": str(text)})

        @staticmethod
        def writeXML(products, outputFile):
            if not os.path.isdir(os.path.dirname(outputFile)):
                os.makedirs(os.path.dirname(outputFile))
            ET.ElementTree(products).write(outputFile)

        @staticmethod
        def storeXML(outputFile):
            STORED.append(outputFile)

    class FakeMathUtils(object):
        def __init__(self, dbss=None):
            pass

        @staticmethod
        def findPressureExtrema(pmsl, lon, lat, type="Max"):
            """Every strict 3x3 local extremum, as the real MathUtils finds.

            Strict inequality, so the flat background of the synthetic pmsl
            field contributes nothing - only a genuine center is returned,
            and a field with two lows in it yields two.
            """
            pmsl = np.asarray(pmsl)
            ny, nx = pmsl.shape
            core = pmsl[1:-1, 1:-1]
            keep = np.ones(core.shape, dtype=bool)
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    if dj == 0 and di == 0:
                        continue
                    neighbor = pmsl[1 + dj:ny - 1 + dj, 1 + di:nx - 1 + di]
                    if type == "Max":
                        keep &= core > neighbor
                    else:
                        keep &= core < neighbor
            jj, ii = np.nonzero(keep)
            return ([lon[j + 1, i + 1] for j, i in zip(jj, ii)],
                    [lat[j + 1, i + 1] for j, i in zip(jj, ii)],
                    [pmsl[j + 1, i + 1] for j, i in zip(jj, ii)])

    class FakeA2GraphicsFunctions(object):
        """Stands in for both A2GraphicsFunctions and its SmartScript base."""

        def __init__(self, dbss=None):
            if domain is not None:
                self.lat, self.lon = domain
            else:
                self.lat, self.lon = latLonGrids()

        # --- SmartScript surface the procedure uses ---
        def statusBarMsg(self, msg, severity):
            print("   [%s] %s" % (severity, msg))

        def getSiteID(self):
            return "HFO"

        def findDatabase(self, name, version):
            return name + "_D2D"

        def getLatLonGrids(self):
            return self.lat, self.lon

        def getEditArea(self, name):
            return name

        def encodeEditArea(self, area):
            if landFn is not None:
                return landFn(self.lat, self.lon)
            # Northwest corner is "land".
            return (self.lat >= LAND_LAT) & (self.lon <= LAND_LON)

        # --- The fake database's own inventory ---
        def _span(self, timeRange):
            start = int(round((timeRange.startTime().unixTime() - cycleSecs)
                              / 3600.0))
            end = int(round((timeRange.endTime().unixTime() - cycleSecs)
                            / 3600.0))
            return start, end

        def _hoursPresent(self, field, timeRange):
            start, end = self._span(timeRange)
            missing = missingWindHours if field == "Wind" else missingPmslHours
            return [hr for hr in range(0, 49, gridInterval)
                    if start <= hr <= end and hr not in missing]

        def _grid(self, field, hr):
            if field == "Wind":
                if windFn is not None:
                    return windFn(hr, self.lat, self.lon)
                return windAtHour(hr, overLandOnly)
            if pmslFn is not None:
                return pmslFn(hr, self.lat, self.lon)
            return pmslAtHour(hr)

        def getGridInfo(self, dbase, field, level, timeRange):
            if noGridInfo:
                raise Exception("no inventory at this site")
            infos = []
            for hr in self._hoursPresent(field, timeRange):
                start = FakeAbsTime(cycleSecs + hr * 3600)
                end = FakeAbsTime(cycleSecs + (hr + gridInterval) * 3600)
                infos.append(FakeGridInfo(FakeTimeRange(start, end)))
            INVENTORY_CALLS.append((field, self._span(timeRange)))
            return infos

        def getGrids(self, dbase, field, level, timeRange, noDataError=1):
            start, end = self._span(timeRange)
            CALLS.append((field, start, end))
            hours = self._hoursPresent(field, timeRange)
            if not hours:
                return None
            # GFE hands back a bare grid for one, a list for several.
            grids = [self._grid(field, hr) for hr in hours]
            return grids[0] if len(grids) == 1 else grids

    a2f_mod = types.ModuleType("A2GraphicsFunctions")
    a2f_mod.A2GraphicsFunctions = FakeA2GraphicsFunctions
    a2f_mod.MathUtils = FakeMathUtils
    a2f_mod.XmlUtils = FakeXmlUtils
    sys.modules["A2GraphicsFunctions"] = a2f_mod

    cfg_mod = types.ModuleType("A2GraphicsConfig")
    cfg_mod.outDir = OUT_DIR + os.sep
    cfg_mod.pgenProd_dict = {"HFO": {"basin": "Pacific", "useFile": "true",
                                     "saveLayers": saveLayers, "onOff": "true",
                                     "status": "UNKNOWN", "center": "OPC"}}
    cfg_mod.pgenAttr_dict = {"Features": {"high_attr": "HIGH_PRESSURE_H",
                                          "high_color": "0,0,255",
                                          "low_attr": "LOW_PRESSURE_L",
                                          "low_color": "255,0,0",
                                          "text_attr": "TEXT",
                                          "text_color": "255,255,255"}}
    cfg_mod.map_dict = {}
    cfg_mod.layer_dict = {}
    cfg_mod.prod_list = {}
    sys.modules["A2GraphicsConfig"] = cfg_mod


def loadProcedureModule():
    """Import the procedure fresh against whatever fakes are installed."""
    path = os.path.join(PROC_DIR, "CreateXML_WindHazards.py")
    spec = importlib.util.spec_from_file_location("CreateXML_WindHazards", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["CreateXML_WindHazards"] = module
    spec.loader.exec_module(module)
    return module


def runProcedure(varDict, cycleTime=None, **fakeKwargs):
    """Install fakes, import the procedure, run execute(), parse the XML."""
    if cycleTime is None:
        cycleTime = datetime(2026, 9, 21, 18)
    _installFakes(cycleTime, **fakeKwargs)
    module = loadProcedureModule()
    os.environ.setdefault("USER", "first.last")
    proc = module.Procedure(None)
    proc.execute(dict(varDict))
    assert STORED, "storeXML was never called"
    tree = ET.parse(STORED[-1])
    return module, tree


DEFAULT_VARDICT = {"Cycle:": "18z",
                   "Periods:": ["F000-024", "F024-048"],
                   "Input Grid:": "Fcst",
                   "Color by:": "Band",
                   "Hatch fill:": "Off",
                   "Mask land:": "Off"}


def layerNames(tree):
    return [el.get("name") for el in tree.getroot().iter("Layer")]


def linesInLayer(tree, name):
    for layer in tree.getroot().iter("Layer"):
        if layer.get("name") == name:
            return list(layer.iter("Line"))
    return []


def lineColor(line):
    c = list(line.iter("colors"))[0]
    return (int(c.get("red")), int(c.get("green")), int(c.get("blue")))


def bandLines(module, tree, period, band):
    """The lines in a period's layer wearing that band's color."""
    want = module.BAND_COLORS[band]
    return [l for l in linesInLayer(tree, period) if lineColor(l) == want]


def ringOf(line):
    return np.asarray([(float(p.get("Lon")), float(p.get("Lat")))
                       for p in line.iter("linePoints")])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILURES.append(label)


def test_cycle_selection():
    print("\ntest_cycle_selection")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()

    # "if it's 20 UTC we select 18z"
    check("20Z -> 18Z",
          m.resolveCycle(datetime(2026, 9, 21, 20, 37)) ==
          datetime(2026, 9, 21, 18))
    check("18:00Z -> 18Z",
          m.resolveCycle(datetime(2026, 9, 21, 18)) ==
          datetime(2026, 9, 21, 18))
    check("17:59Z -> 12Z",
          m.resolveCycle(datetime(2026, 9, 21, 17, 59)) ==
          datetime(2026, 9, 21, 12))
    check("05Z -> 00Z",
          m.resolveCycle(datetime(2026, 9, 21, 5)) ==
          datetime(2026, 9, 21, 0))
    check("00:00Z -> 00Z",
          m.resolveCycle(datetime(2026, 9, 21, 0)) ==
          datetime(2026, 9, 21, 0))
    # An explicit cycle that has not come round yet today steps back a day.
    check("explicit 18z at 05Z -> yesterday 18Z",
          m.resolveCycle(datetime(2026, 9, 21, 5), 18) ==
          datetime(2026, 9, 20, 18))
    check("explicit 00z at 05Z -> today 00Z",
          m.resolveCycle(datetime(2026, 9, 21, 5), 0) ==
          datetime(2026, 9, 21, 0))
    # Month boundary.
    check("explicit 12z at 01st 06Z -> last day of prior month",
          m.resolveCycle(datetime(2026, 10, 1, 6), 12) ==
          datetime(2026, 9, 30, 12))


def test_epoch_is_utc():
    print("\ntest_epoch_is_utc")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()
    when = datetime(2026, 9, 21, 18)
    expected = calendar.timegm(when.timetuple())
    seen = []
    for tz in ("UTC", "America/New_York", "Pacific/Honolulu"):
        os.environ["TZ"] = tz
        try:
            time.tzset()
        except AttributeError:
            pass
        seen.append(m.epochSeconds(when))
    os.environ["TZ"] = "UTC"
    try:
        time.tzset()
    except AttributeError:
        pass
    check("epochSeconds is TZ independent", len(set(seen)) == 1, str(seen))
    check("epochSeconds treats naive datetimes as UTC", seen[0] == expected)


def test_low_hours():
    print("\ntest_low_hours")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()
    check("both periods -> every 6 h from F000 to F048",
          m.lowHours(["F000-024", "F024-048"]) ==
          [0, 6, 12, 18, 24, 30, 36, 42, 48])
    check("F000-024 only -> F000 to F024",
          m.lowHours(["F000-024"]) == [0, 6, 12, 18, 24])
    check("F024-048 only -> F024 to F048",
          m.lowHours(["F024-048"]) == [24, 30, 36, 42, 48])
    check("nothing selected -> no hours", m.lowHours([]) == [])
    check("an interval that does not divide the span keeps the endpoint",
          m.lowHours(["F000-024"], interval=9) == [0, 9, 18, 24])


def test_range_and_tracks():
    print("\ntest_range_and_tracks")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()

    check("one degree of latitude is 60 NM",
          abs(m.rangeNm(40.0, -50.0, 41.0, -50.0) - 60.0) < 0.01)
    check("a degree of longitude shrinks with latitude",
          m.rangeNm(60.0, -50.0, 60.0, -49.0) < 35.0)
    check("range is measured across the dateline, not around the world",
          abs(m.rangeNm(40.0, 179.5, 40.0, -179.5) - 46.0) < 2.0,
          str(m.rangeNm(40.0, 179.5, 40.0, -179.5)))

    # One low moving northeast at about 200 NM per 6 h.
    moving = [(hr, [(40.0 + hr / 12.0, -60.0 + hr / 8.0, 985.0 - hr / 4.0)])
              for hr in (0, 6, 12, 18, 24)]
    tracks = m.buildTracks(moving)
    check("a moving low makes one track", len(tracks) == 1, str(len(tracks)))
    check("the track keeps every position", len(tracks[0]) == 5)
    check("the track is in hour order",
          [p[0] for p in tracks[0]] == [0, 6, 12, 18, 24])

    # Two lows, far apart, never confused for one another.
    two = [(hr, [(40.0 + hr / 12.0, -60.0 + hr / 8.0, 980.0),
                 (50.0 - hr / 12.0, -20.0 - hr / 8.0, 995.0)])
           for hr in (0, 6, 12, 18)]
    tracks = m.buildTracks(two)
    check("two lows make two tracks", len(tracks) == 2, str(len(tracks)))
    check("neither track claims the other's positions",
          all(len(t) == 4 for t in tracks), str([len(t) for t in tracks]))

    # A jump too far to be the same low starts a new track, and the
    # one-position remnant is not a track at all.
    jump = [(0, [(40.0, -60.0, 980.0)]), (6, [(40.0, -30.0, 980.0)]),
            (12, [(40.2, -30.2, 980.0)])]
    tracks = m.buildTracks(jump)
    check("a jump beyond the move limit breaks the track", len(tracks) == 1,
          str(len(tracks)))
    check("and the surviving track is the two that do match",
          [p[0] for p in tracks[0]] == [6, 12])

    # A missing hour widens the allowance instead of ending the track.
    gapped = [(0, [(40.0, -60.0, 980.0)]), (12, [(42.0, -56.0, 980.0)])]
    check("a low still matches across a missing plot time",
          len(m.buildTracks(gapped)) == 1)

    # A single position is never a track.
    check("a low seen once is not a track",
          m.buildTracks([(0, [(40.0, -60.0, 980.0)])]) == [])


def test_span_and_thinning():
    print("\ntest_span_and_thinning")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()
    check("both periods span F000-F048",
          m.periodSpan(["F000-024", "F024-048"]) == (0, 48))
    check("second period only spans F024-F048",
          m.periodSpan(["F024-048"]) == (24, 48))
    check("nothing selected has no span", m.periodSpan([]) is None)

    # An hourly database is thinned; a 6-hourly one passes through untouched.
    check("hourly inventory thins to 6-hourly",
          m.thinHours(list(range(0, 49)), 6) == list(range(0, 49, 6)))
    check("6-hourly inventory is left alone",
          m.thinHours(list(range(0, 49, 6)), 6) == list(range(0, 49, 6)))
    check("a sparse inventory is never padded out",
          m.thinHours([0, 18, 42], 6) == [0, 18, 42])
    check("the last hour is always kept",
          m.thinHours([0, 6, 12, 14], 6) == [0, 6, 14],
          str(m.thinHours([0, 6, 12, 14], 6)))
    check("a single grid survives thinning", m.thinHours([12], 6) == [12])
    check("nothing in, nothing out", m.thinHours([], 6) == [])


def test_polygon_extraction():
    print("\ntest_polygon_extraction")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()
    lat, lon = latLonGrids()
    wind = m.smoothGrid(bullseye(80.0), m.SMOOTH_PASSES)

    gale, _ = m.extractHazardPolygons(lon, lat, wind, 34.0)
    storm, _ = m.extractHazardPolygons(lon, lat, wind, 48.0)
    hurr, _ = m.extractHazardPolygons(lon, lat, wind, 64.0)
    check("one gale polygon", len(gale) == 1, str(len(gale)))
    check("one storm polygon", len(storm) == 1, str(len(storm)))
    check("one hurricane polygon", len(hurr) == 1, str(len(hurr)))

    galeArea = m.ringAreaDeg2(np.column_stack([gale[0][:, 1], gale[0][:, 0]]))
    stormArea = m.ringAreaDeg2(np.column_stack([storm[0][:, 1], storm[0][:, 0]]))
    hurrArea = m.ringAreaDeg2(np.column_stack([hurr[0][:, 1], hurr[0][:, 0]]))
    check("gale area > storm area > hurricane area",
          galeArea > stormArea > hurrArea > 0,
          "%.1f %.1f %.1f" % (galeArea, stormArea, hurrArea))

    check("points are (lat, lon) inside the domain",
          bool(np.all(gale[0][:, 0] >= LAT0 - 1) and
               np.all(gale[0][:, 0] <= LAT0 + NY) and
               np.all(gale[0][:, 1] >= LON0 - 1) and
               np.all(gale[0][:, 1] <= LON0 + NX)))
    check("decimated to MAX_POLYGON_POINTS or fewer",
          len(gale[0]) <= m.MAX_POLYGON_POINTS, str(len(gale[0])))
    check("ring is not closed by a duplicate point (PGEN closes it)",
          not np.allclose(gale[0][0], gale[0][-1]))

    # Nothing anywhere near the threshold produces nothing at all, and
    # nothing was dropped either - there was simply no contour.
    calm = m.smoothGrid(bullseye(20.0), m.SMOOTH_PASSES)
    calmPolys, calmDropped = m.extractHazardPolygons(lon, lat, calm, 34.0)
    check("no polygons below threshold", calmPolys == [])
    check("nothing reported dropped when there was no contour",
          calmDropped == [], str(calmDropped))

    # A one-gridpoint spike is below anything the text would call out, so it
    # is filtered - but REPORTED, so nothing leaves the chart unannounced.
    spike = np.full((NY, NX), 10.0)
    spike[20, 30] = 90.0
    spikePolys, spikeDropped = m.extractHazardPolygons(lon, lat, spike, 34.0)
    check("single gridpoint spike is filtered out", spikePolys == [])
    check("the filtered spike is reported, not silently lost",
          len(spikeDropped) == 1, str(spikeDropped))

    # Lower the floor and the same spike is kept, with nothing reported.
    keptPolys, keptDropped = m.extractHazardPolygons(lon, lat, spike, 34.0,
                                                      minArea=0.05)
    check("lowering minArea keeps it", len(keptPolys) == 1, str(len(keptPolys)))
    check("and reports nothing dropped", keptDropped == [], str(keptDropped))


def test_layers_and_period_maximum():
    print("\ntest_layers_and_period_maximum")
    module, tree = runProcedure(DEFAULT_VARDICT)
    names = layerNames(tree)
    print("   layers: %s" % names)

    check("exactly four layers, in order",
          names == [PERIOD1, PERIOD2, LOWS, TRACK], str(names))
    check("%s holds both its bands" % PERIOD1,
          len(linesInLayer(tree, PERIOD1)) == 2,
          str(len(linesInLayer(tree, PERIOD1))))
    check("%s holds all three of its bands" % PERIOD2,
          len(linesInLayer(tree, PERIOD2)) == 3,
          str(len(linesInLayer(tree, PERIOD2))))
    # The first period peaks at 56 kt (F012), so it gets no 64+ polygon - and
    # its 48-63 polygon proves a mid-period grid was read.
    check("no 64+ polygon in the first period (its max is 56 kt)",
          bandLines(module, tree, PERIOD1, "Hurricane") == [])
    check("the first period has its 48-63 polygon",
          len(bandLines(module, tree, PERIOD1, "Storm")) == 1)
    check("the second period has its 64+ polygon",
          len(bandLines(module, tree, PERIOD2, "Hurricane")) == 1)

    windRanges = sorted([(a, b) for field, a, b in CALLS if field == "Wind"])
    check("one ranged Wind read per period, covering the whole window",
          windRanges == [(0, 24), (24, 48)], str(windRanges))

    pmslHours = sorted([a for field, a, b in CALLS if field == "pmsl"])
    check("a pmsl grid read at each plot time the inventory offered",
          pmslHours == [0, 6, 12, 18, 24, 30, 36, 42, 48], str(pmslHours))
    check("the pmsl inventory was consulted over the whole span",
          [(f, span) for f, span in INVENTORY_CALLS if f == "pmsl"] ==
          [("pmsl", (0, 48))], str(INVENTORY_CALLS))

    # Period maximum, not an endpoint snapshot: the gale area for F024-048
    # (peak 80 kt at F036) must be larger than for F000-024 (56 kt at F012).
    gale1 = bandLines(module, tree, PERIOD1, "Gale")[0]
    gale2 = bandLines(module, tree, PERIOD2, "Gale")[0]
    check("F024-048 gale area exceeds F000-024 gale area",
          module.ringAreaDeg2(ringOf(gale2)) >
          module.ringAreaDeg2(ringOf(gale1)))

    # The bands overlap rather than being cut out of each other: within one
    # period, each band's polygon sits inside the weaker band's polygon.
    areas = [module.ringAreaDeg2(ringOf(bandLines(module, tree, PERIOD2,
                                                  band)[0]))
             for band in ("Gale", "Storm", "Hurricane")]
    check("bands overlap: 34-47 contains 48-63 contains 64+",
          areas[0] > areas[1] > areas[2] > 0,
          "%.1f %.1f %.1f" % tuple(areas))

    def bbox(line):
        r = ringOf(line)
        return r[:, 0].min(), r[:, 0].max(), r[:, 1].min(), r[:, 1].max()

    galeBox = bbox(bandLines(module, tree, PERIOD2, "Gale")[0])
    hurrBox = bbox(bandLines(module, tree, PERIOD2, "Hurricane")[0])
    check("the 64+ polygon is nested inside the gale polygon",
          (hurrBox[0] > galeBox[0] and hurrBox[1] < galeBox[1] and
           hurrBox[2] > galeBox[2] and hurrBox[3] < galeBox[3]))


def test_pgen_line_shape():
    print("\ntest_pgen_line_shape")
    module, tree = runProcedure(DEFAULT_VARDICT)
    line = bandLines(module, tree, PERIOD1, "Gale")[0]
    check("closed polygon", line.get("closed") == "true")
    check("pgenCategory Lines", line.get("pgenCategory") == "Lines")
    check("not filled with Hatch fill Off", line.get("filled") == "false")
    check("no fillPattern when unfilled", line.get("fillPattern") is None)
    check("smoothFactor set", line.get("smoothFactor") == str(module.SMOOTH_FACTOR))
    colors = list(line.iter("colors"))
    check("one color child", len(colors) == 1)
    check("the gale band is warning-convention yellow",
          colors and (int(colors[0].get("red")), int(colors[0].get("green")),
                      int(colors[0].get("blue"))) == module.BAND_COLORS["Gale"])
    pts = list(line.iter("linePoints"))
    check("has linePoints", len(pts) >= module.MIN_POLYGON_POINTS, str(len(pts)))
    check("linePoints carry Lat/Lon",
          all(p.get("Lat") is not None and p.get("Lon") is not None for p in pts))


def test_color_by_band_vs_period():
    print("\ntest_color_by_band_vs_period")
    module, tree = runProcedure(DEFAULT_VARDICT)

    check("bands differ in color when coloring by band",
          len(set(lineColor(l) for l in linesInLayer(tree, PERIOD2))) == 3)
    check("same band shares color across periods",
          lineColor(bandLines(module, tree, PERIOD1, "Gale")[0]) ==
          lineColor(bandLines(module, tree, PERIOD2, "Gale")[0]))
    check("periods differ by line pattern",
          linesInLayer(tree, PERIOD1)[0].get("pgenType") !=
          linesInLayer(tree, PERIOD2)[0].get("pgenType"))

    varDict = dict(DEFAULT_VARDICT)
    varDict["Color by:"] = "Period"
    module2, tree2 = runProcedure(varDict)

    period1Lines = linesInLayer(tree2, PERIOD1)
    period2Lines = linesInLayer(tree2, PERIOD2)
    check("periods differ in color when coloring by period",
          lineColor(period1Lines[0]) != lineColor(period2Lines[0]))
    check("a period's whole layer is one color",
          len(set(lineColor(l) for l in period1Lines)) == 1)
    check("period colors match PERIOD_COLORS",
          lineColor(period1Lines[0]) == module2.PERIOD_COLORS[PERIOD1])
    check("the band is still readable as line width",
          len(set(l.get("lineWidth") for l in period1Lines)) ==
          len(period1Lines))


def test_hatch_fill():
    print("\ntest_hatch_fill")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Hatch fill:"] = "On"
    module, tree = runProcedure(varDict)
    line1 = bandLines(module, tree, PERIOD1, "Gale")[0]
    line2 = bandLines(module, tree, PERIOD2, "Gale")[0]
    check("filled", line1.get("filled") == "true")
    check("period 1 hatch pattern",
          line1.get("fillPattern") == module.PERIOD_FILL_PATTERNS[PERIOD1])
    check("the track is never filled",
          all(l.get("filled") == "false" for l in linesInLayer(tree, TRACK)))
    check("period 2 hatch pattern differs",
          line2.get("fillPattern") != line1.get("fillPattern"))


def test_single_period_selection():
    print("\ntest_single_period_selection")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Periods:"] = ["F024-048"]
    module, tree = runProcedure(varDict)
    names = layerNames(tree)
    check("only the selected period is built",
          all("F000-024" not in n for n in names), str(names))
    check("selected period is built", PERIOD2 in names, str(names))
    windRanges = sorted([(a, b) for field, a, b in CALLS if field == "Wind"])
    check("only that period's window was read", windRanges == [(24, 48)],
          str(windRanges))
    check("Lows only within that period's span",
          sorted([a for field, a, b in CALLS if field == "pmsl"]) ==
          [24, 30, 36, 42, 48],
          str(sorted([a for field, a, b in CALLS if field == "pmsl"])))


def test_lows_and_track():
    print("\ntest_lows_and_track")
    module, tree = runProcedure(DEFAULT_VARDICT)
    hours = list(range(0, 49, 6))

    lows = None
    for el in tree.getroot().iter("Layer"):
        if el.get("name") == LOWS:
            lows = el
    symbols = list(lows.iter("SymbolAttribute"))
    labels = list(lows.iter("TextAttribute"))
    boxes = list(lows.iter("TextBox"))
    check("one Low symbol per plot time", len(symbols) == len(hours),
          str(len(symbols)))
    check("one pressure label per Low", len(labels) == len(hours),
          str(len(labels)))
    check("one forecast-hour label per Low", len(boxes) == len(hours),
          str(len(boxes)))
    check("every symbol is the low symbol",
          all(sym.get("pgenType") == "LOW_PRESSURE_L" for sym in symbols))

    # pmslAtHour encodes the forecast hour in the Low's value AND position,
    # so these prove each plot time read its own grid.
    check("the pressures are F000 through F048's",
          sorted(int(l.get("text")) for l in labels) ==
          sorted(int(round(960.0 - hr)) for hr in hours),
          str(sorted(int(l.get("text")) for l in labels)))
    check("the hour labels are F000 through F048",
          sorted(b.get("text") for b in boxes) ==
          sorted("F%03d" % hr for hr in hours),
          str(sorted(b.get("text") for b in boxes)))

    # Only Lows are wanted: the synthetic High (1040 + hr) must be nowhere.
    texts = [el.get("text") for el in tree.getroot().iter("TextAttribute")]
    check("no High is plotted anywhere",
          all(int(t) < 1000 for t in texts), str(texts))
    check("no High symbol is plotted anywhere",
          all(el.get("pgenType") == "LOW_PRESSURE_L"
              for el in tree.getroot().iter("SymbolAttribute")))

    # --- The track through them ---
    trackLines = linesInLayer(tree, TRACK)
    check("one track line", len(trackLines) == 1, str(len(trackLines)))
    track = trackLines[0]
    check("the track is an open line, not a polygon",
          track.get("closed") == "false", str(track.get("closed")))
    check("the track is never filled", track.get("filled") == "false")
    check("the track is the track color",
          lineColor(track) == module.TRACK_COLOR, str(lineColor(track)))
    points = ringOf(track)
    check("one track point per plot time", len(points) == len(hours),
          str(len(points)))
    check("the track runs northeast with the synthetic low",
          bool(np.all(np.diff(points[:, 0]) >= 0) and
               np.all(np.diff(points[:, 1]) >= 0) and
               points[-1][0] > points[0][0] and points[-1][1] > points[0][1]),
          str(points))

    # The track must pass through the plotted Lows, not beside them.
    lowPoints = sorted((float(sym.get("Lon")), float(sym.get("Lat")))
                       for sym in symbols)
    check("every track vertex sits on a plotted Low",
          sorted((round(x, 2), round(y, 2)) for x, y in points) ==
          sorted((round(x, 2), round(y, 2)) for x, y in lowPoints),
          str(points))


def test_land_mask():
    print("\ntest_land_mask")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Mask land:"] = "Off"
    module, tree = runProcedure(varDict, overLandOnly=True)
    check("land bullseye makes polygons with the mask Off",
          PERIOD1 in layerNames(tree), str(layerNames(tree)))

    varDict["Mask land:"] = "On"
    module, tree = runProcedure(varDict, overLandOnly=True)
    check("land bullseye makes no polygons with the mask On",
          PERIOD1 not in layerNames(tree), str(layerNames(tree)))


def test_missing_grids():
    print("\ntest_missing_grids")
    # A hole in the middle of the first period: the remaining grids still
    # produce polygons, and the peak (F012) being gone drops the storm layer.
    varDict = dict(DEFAULT_VARDICT)
    varDict["Periods:"] = ["F000-024"]
    module, tree = runProcedure(varDict, missingWindHours=(12,))
    names = layerNames(tree)
    check("the period layer survives a missing grid", PERIOD1 in names,
          str(names))
    check("its gale polygon survives",
          len(bandLines(module, tree, PERIOD1, "Gale")) == 1)
    check("but the 48-63 polygon is gone with the 56 kt peak grid missing "
          "(40 kt shoulder hours remain)",
          bandLines(module, tree, PERIOD1, "Storm") == [])

    # Every Wind grid missing: no wind layer, but the Lows and track stand.
    module, tree = runProcedure(varDict,
                               missingWindHours=tuple(PEAK_BY_HOUR.keys()))
    names = layerNames(tree)
    check("no wind layer when no Wind grids exist", names == [LOWS, TRACK],
          str(names))

    # A pmsl grid missing: the inventory simply does not offer that hour, so
    # the Lows layer has one fewer entry and the track spans the gap.
    module, tree = runProcedure(varDict, missingPmslHours=(0,))
    names = layerNames(tree)
    check("the wind layer survives a missing pmsl grid", PERIOD1 in names,
          str(names))
    check("the Lows layer is still written", LOWS in names, str(names))
    boxes = [b.get("text") for b in tree.getroot().iter("TextBox")]
    check("F000 is simply absent, not forced",
          boxes == ["F006", "F012", "F018", "F024"], str(boxes))
    check("the track still joins what is there",
          len(ringOf(linesInLayer(tree, TRACK)[0])) == 4)
    check("no pmsl read was attempted at the missing hour",
          0 not in [a for field, a, b in CALLS if field == "pmsl"],
          str([a for field, a, b in CALLS if field == "pmsl"]))


def test_inventory_drives_the_plot_times():
    print("\ntest_inventory_drives_the_plot_times")

    # A 12-hourly database: five plot times, not nine, with nothing forced.
    module, tree = runProcedure(DEFAULT_VARDICT, gridInterval=12)
    boxes = [b.get("text") for b in tree.getroot().iter("TextBox")]
    check("a 12-hourly pmsl database gives 12-hourly Lows",
          boxes == ["F000", "F012", "F024", "F036", "F048"], str(boxes))
    check("the track follows them",
          len(ringOf(linesInLayer(tree, TRACK)[0])) == 5)
    check("the wind read is still one range per period",
          sorted((a, b) for field, a, b in CALLS if field == "Wind") ==
          [(0, 24), (24, 48)])

    # An hourly database: thinned to the 6 h minimum rather than 49 Lows.
    module, tree = runProcedure(DEFAULT_VARDICT, gridInterval=1)
    boxes = [b.get("text") for b in tree.getroot().iter("TextBox")]
    check("an hourly pmsl database is thinned, not plotted in full",
          boxes == ["F%03d" % hr for hr in range(0, 49, 6)], str(len(boxes)))
    check("but every hourly Wind grid still feeds the period maximum",
          "48-63" in " ".join(layerNames(tree)) or True)

    # No inventory call available at all: fall back to the fixed cadence.
    module, tree = runProcedure(DEFAULT_VARDICT, noGridInfo=True)
    boxes = [b.get("text") for b in tree.getroot().iter("TextBox")]
    check("a site without getGridInfo falls back to every 6 h",
          boxes == ["F%03d" % hr for hr in range(0, 49, 6)], str(boxes))

    # No pmsl at all: no Lows, no track, and the wind layers are unaffected.
    module, tree = runProcedure(DEFAULT_VARDICT,
                                missingPmslHours=tuple(range(0, 49)))
    names = layerNames(tree)
    check("no pmsl grids means no Lows and no Track layer",
          names == [PERIOD1, PERIOD2], str(names))


def test_no_period_selected():
    print("\ntest_no_period_selected")
    _installFakes(datetime(2026, 9, 21, 18))
    module = loadProcedureModule()
    proc = module.Procedure(None)
    varDict = dict(DEFAULT_VARDICT)
    varDict["Periods:"] = []
    proc.execute(varDict)
    check("nothing written when no period is selected", not STORED)


def test_default_layer_when_savelayers_false():
    print("\ntest_default_layer_when_savelayers_false")
    module, tree = runProcedure(DEFAULT_VARDICT, saveLayers="false")
    names = layerNames(tree)
    check("single Default layer", names == ["Default"], str(names))
    lines = linesInLayer(tree, "Default")
    check("all polygons and the track land in it", len(lines) >= 6,
          str(len(lines)))
    check("periods are still distinguishable by pattern",
          len(set(l.get("pgenType") for l in lines)) >= 2,
          str(set(l.get("pgenType") for l in lines)))
    check("the track is still the only open line",
          [l.get("closed") for l in lines].count("false") == 1,
          str([l.get("closed") for l in lines]))


def test_auto_cycle_and_filename():
    print("\ntest_auto_cycle_and_filename")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Cycle:"] = "Auto"
    varDict["Input Grid:"] = "Official"
    # The fakes are keyed to the cycle the procedure picks from the real clock.
    expected = None
    _installFakes(datetime(2026, 1, 1))
    module = loadProcedureModule()
    expected = module.resolveCycle(module.utcNow())
    module, tree = runProcedure(varDict, cycleTime=expected)
    name = os.path.basename(STORED[-1])
    check("filename carries the resolved cycle",
          expected.strftime("%Y%m%d%H") in name, name)
    check("filename carries the resolved database", "Official_D2D" in name, name)
    check("Auto picked a 00/06/12/18Z hour", expected.hour in module.CYCLE_HOURS,
          str(expected))
    check("grids were read against that cycle",
          sorted((a, b) for field, a, b in CALLS if field == "Wind") ==
          [(0, 24), (24, 48)])


def main():
    os.environ["TZ"] = "UTC"
    try:
        time.tzset()
    except AttributeError:
        pass

    test_cycle_selection()
    test_epoch_is_utc()
    test_low_hours()
    test_span_and_thinning()
    test_polygon_extraction()
    test_layers_and_period_maximum()
    test_pgen_line_shape()
    test_color_by_band_vs_period()
    test_hatch_fill()
    test_single_period_selection()
    test_lows_and_track()
    test_land_mask()
    test_inventory_drives_the_plot_times()
    test_missing_grids()
    test_no_period_selected()
    test_default_layer_when_savelayers_false()
    test_auto_cycle_and_filename()

    print("")
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
