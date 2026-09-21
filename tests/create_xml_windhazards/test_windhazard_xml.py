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
hours were read and that pmsl came from each period's START time.

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


def pmslAtHour(hr):
    """A High and a Low whose values encode the forecast hour."""
    grid = np.full((NY, NX), 1013.0)
    grid[10, 10] = 1040.0 + hr        # High
    grid[30, 45] = 960.0 - hr         # Low
    return grid


# ---------------------------------------------------------------------------
# Fake AWIPS / A2Graphics modules
# ---------------------------------------------------------------------------

CALLS = []          # every getGrids call: (field, forecast hour)
STORED = []         # every storeXML call


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


def _installFakes(cycleTime, overLandOnly=False, missingWindHours=(),
                  missingPmslHours=(), saveLayers="true"):
    """Install fake AWIPS/A2Graphics modules into sys.modules."""
    del CALLS[:]
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
            pmsl = np.asarray(pmsl)
            if type == "Max":
                idx = np.unravel_index(np.argmax(pmsl), pmsl.shape)
            else:
                idx = np.unravel_index(np.argmin(pmsl), pmsl.shape)
            return ([lon[idx]], [lat[idx]], [pmsl[idx]])

    class FakeA2GraphicsFunctions(object):
        """Stands in for both A2GraphicsFunctions and its SmartScript base."""

        def __init__(self, dbss=None):
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
            # Northwest corner is "land".
            return (self.lat >= LAND_LAT) & (self.lon <= LAND_LON)

        def getGrids(self, dbase, field, level, timeRange, noDataError=1):
            hr = int(round((timeRange.startTime().unixTime() - cycleSecs)
                           / 3600.0))
            CALLS.append((field, hr))
            if field == "Wind":
                if hr in missingWindHours:
                    return None
                return windAtHour(hr, overLandOnly)
            if field == "pmsl":
                if hr in missingPmslHours:
                    return None
                return pmslAtHour(hr)
            return None

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
                   "Color by:": "Threshold",
                   "Hatch fill:": "Off",
                   "Mask land:": "Off"}


def layerNames(tree):
    return [el.get("name") for el in tree.getroot().iter("Layer")]


def linesInLayer(tree, name):
    for layer in tree.getroot().iter("Layer"):
        if layer.get("name") == name:
            return list(layer.iter("Line"))
    return []


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


def test_period_hours():
    print("\ntest_period_hours")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()
    check("F000-024 hours", m.periodForecastHours(0, 24) == [0, 6, 12, 18, 24])
    check("F024-048 hours", m.periodForecastHours(24, 48) == [24, 30, 36, 42, 48])
    check("uneven interval keeps the endpoint",
          m.periodForecastHours(0, 24, 9) == [0, 9, 18, 24])


def test_polygon_extraction():
    print("\ntest_polygon_extraction")
    _installFakes(datetime(2026, 9, 21, 18))
    m = loadProcedureModule()
    lat, lon = latLonGrids()
    wind = m.smoothGrid(bullseye(80.0), m.SMOOTH_PASSES)

    gale = m.extractHazardPolygons(lon, lat, wind, 34.0)
    storm = m.extractHazardPolygons(lon, lat, wind, 48.0)
    hurr = m.extractHazardPolygons(lon, lat, wind, 64.0)
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

    # Nothing anywhere near the threshold produces nothing at all.
    calm = m.smoothGrid(bullseye(20.0), m.SMOOTH_PASSES)
    check("no polygons below threshold",
          m.extractHazardPolygons(lon, lat, calm, 34.0) == [])

    # A one-gridpoint spike is noise, not a polygon.
    spike = np.full((NY, NX), 10.0)
    spike[20, 30] = 90.0
    check("single gridpoint spike is filtered out",
          m.extractHazardPolygons(lon, lat, m.smoothGrid(spike, 0), 34.0) == [])


def test_layers_and_period_maximum():
    print("\ntest_layers_and_period_maximum")
    module, tree = runProcedure(DEFAULT_VARDICT)
    names = layerNames(tree)
    print("   layers: %s" % names)

    for expected in ("Gale_F000-024", "Storm_F000-024", "Features_F000-024",
                     "Gale_F024-048", "Storm_F024-048", "Hurricane_F024-048",
                     "Features_F024-048"):
        check("layer %s present" % expected, expected in names)
    # The first period peaks at 56 kt (F012), so there must be no hurricane
    # layer for it - and its storm polygon proves a mid-period grid was read.
    check("no Hurricane_F000-024 layer (period max is 56 kt)",
          "Hurricane_F000-024" not in names)
    check("Storm_F000-024 has a polygon",
          len(linesInLayer(tree, "Storm_F000-024")) == 1)
    check("Hurricane_F024-048 has a polygon",
          len(linesInLayer(tree, "Hurricane_F024-048")) == 1)

    windHours = sorted([hr for field, hr in CALLS if field == "Wind"])
    check("every 6-hourly Wind grid in both periods was read",
          windHours == [0, 6, 12, 18, 24, 24, 30, 36, 42, 48], str(windHours))

    pmslHours = sorted([hr for field, hr in CALLS if field == "pmsl"])
    check("pmsl read at each period START only",
          pmslHours == [0, 24], str(pmslHours))

    # Period maximum, not an endpoint snapshot: the gale area for F024-048
    # (peak 80 kt at F036) must be larger than for F000-024 (56 kt at F012).
    gale1 = linesInLayer(tree, "Gale_F000-024")[0]
    gale2 = linesInLayer(tree, "Gale_F024-048")[0]

    def ringOf(line):
        pts = [(float(p.get("Lon")), float(p.get("Lat")))
               for p in line.iter("linePoints")]
        return np.asarray(pts)

    check("F024-048 gale area exceeds F000-024 gale area",
          module.ringAreaDeg2(ringOf(gale2)) >
          module.ringAreaDeg2(ringOf(gale1)))


def test_pgen_line_shape():
    print("\ntest_pgen_line_shape")
    module, tree = runProcedure(DEFAULT_VARDICT)
    line = linesInLayer(tree, "Gale_F000-024")[0]
    check("closed polygon", line.get("closed") == "true")
    check("pgenCategory Lines", line.get("pgenCategory") == "Lines")
    check("not filled with Hatch fill Off", line.get("filled") == "false")
    check("no fillPattern when unfilled", line.get("fillPattern") is None)
    check("smoothFactor set", line.get("smoothFactor") == str(module.SMOOTH_FACTOR))
    colors = list(line.iter("colors"))
    check("one color child", len(colors) == 1)
    check("gale is yellow",
          colors and (int(colors[0].get("red")), int(colors[0].get("green")),
                      int(colors[0].get("blue"))) == module.THRESHOLD_COLORS["Gale"])
    pts = list(line.iter("linePoints"))
    check("has linePoints", len(pts) >= module.MIN_POLYGON_POINTS, str(len(pts)))
    check("linePoints carry Lat/Lon",
          all(p.get("Lat") is not None and p.get("Lon") is not None for p in pts))


def test_color_by_threshold_vs_period():
    print("\ntest_color_by_threshold_vs_period")
    module, tree = runProcedure(DEFAULT_VARDICT)

    def colorOf(layer):
        line = linesInLayer(tree, layer)[0]
        c = list(line.iter("colors"))[0]
        return (int(c.get("red")), int(c.get("green")), int(c.get("blue")))

    def typeOf(t, layer):
        return linesInLayer(t, layer)[0].get("pgenType")

    check("gale and storm differ in color when coloring by threshold",
          colorOf("Gale_F000-024") != colorOf("Storm_F000-024"))
    check("same threshold shares color across periods",
          colorOf("Gale_F000-024") == colorOf("Gale_F024-048"))
    check("periods differ by line pattern",
          typeOf(tree, "Gale_F000-024") != typeOf(tree, "Gale_F024-048"),
          "%s vs %s" % (typeOf(tree, "Gale_F000-024"),
                        typeOf(tree, "Gale_F024-048")))

    varDict = dict(DEFAULT_VARDICT)
    varDict["Color by:"] = "Period"
    module2, tree2 = runProcedure(varDict)

    def colorOf2(layer):
        line = linesInLayer(tree2, layer)[0]
        c = list(line.iter("colors"))[0]
        return (int(c.get("red")), int(c.get("green")), int(c.get("blue")))

    check("periods differ in color when coloring by period",
          colorOf2("Gale_F000-024") != colorOf2("Gale_F024-048"))
    check("same period shares color across thresholds",
          colorOf2("Gale_F000-024") == colorOf2("Storm_F000-024"))
    check("period colors match PERIOD_COLORS",
          colorOf2("Gale_F000-024") == module2.PERIOD_COLORS["F000-024"])
    check("severity still readable as line width",
          (linesInLayer(tree2, "Gale_F000-024")[0].get("lineWidth") !=
           linesInLayer(tree2, "Storm_F000-024")[0].get("lineWidth")))


def test_hatch_fill():
    print("\ntest_hatch_fill")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Hatch fill:"] = "On"
    module, tree = runProcedure(varDict)
    line1 = linesInLayer(tree, "Gale_F000-024")[0]
    line2 = linesInLayer(tree, "Gale_F024-048")[0]
    check("filled", line1.get("filled") == "true")
    check("period 1 hatch pattern",
          line1.get("fillPattern") == module.PERIOD_FILL_PATTERNS["F000-024"])
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
    check("selected period is built", "Gale_F024-048" in names)
    windHours = sorted([hr for field, hr in CALLS if field == "Wind"])
    check("only that period's Wind grids were read",
          windHours == [24, 30, 36, 42, 48], str(windHours))
    check("pmsl read at F024 only",
          sorted([hr for field, hr in CALLS if field == "pmsl"]) == [24])


def test_features_layer():
    print("\ntest_features_layer")
    module, tree = runProcedure(DEFAULT_VARDICT)
    for period, hr in (("F000-024", 0), ("F024-048", 24)):
        layer = None
        for el in tree.getroot().iter("Layer"):
            if el.get("name") == "Features_" + period:
                layer = el
        symbols = list(layer.iter("SymbolAttribute"))
        labels = list(layer.iter("TextAttribute"))
        check("%s has a High and a Low symbol" % period, len(symbols) == 2,
              str(len(symbols)))
        check("%s has both labels" % period, len(labels) == 2, str(len(labels)))
        # pmslAtHour encodes the forecast hour in the extrema values, so the
        # labels prove the grid came from the period's start time.
        values = sorted(int(l.get("text")) for l in labels)
        check("%s extrema came from F%03d pmsl" % (period, hr),
              values == sorted([int(round(1040.0 + hr)), int(round(960.0 - hr))]),
              str(values))


def test_land_mask():
    print("\ntest_land_mask")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Mask land:"] = "Off"
    module, tree = runProcedure(varDict, overLandOnly=True)
    check("land bullseye makes polygons with the mask Off",
          "Gale_F000-024" in layerNames(tree))

    varDict["Mask land:"] = "On"
    module, tree = runProcedure(varDict, overLandOnly=True)
    check("land bullseye makes no polygons with the mask On",
          all("Gale" not in n for n in layerNames(tree)),
          str(layerNames(tree)))


def test_missing_grids():
    print("\ntest_missing_grids")
    # A hole in the middle of the first period: the remaining grids still
    # produce polygons, and the peak (F012) being gone drops the storm layer.
    varDict = dict(DEFAULT_VARDICT)
    varDict["Periods:"] = ["F000-024"]
    module, tree = runProcedure(varDict, missingWindHours=(12,))
    names = layerNames(tree)
    check("gale layer survives a missing grid", "Gale_F000-024" in names,
          str(names))
    check("storm layer gone with the 56 kt peak grid missing "
          "(40 kt shoulder hours remain)",
          "Storm_F000-024" not in names, str(names))

    # Every Wind grid missing: no wind layers, but Features still written.
    module, tree = runProcedure(varDict,
                               missingWindHours=tuple(PEAK_BY_HOUR.keys()))
    names = layerNames(tree)
    check("no wind layers when no Wind grids exist",
          all(n.startswith("Features") for n in names), str(names))
    check("Features layer still written", "Features_F000-024" in names)

    # pmsl missing: wind layers still written, no Features layer.
    module, tree = runProcedure(varDict, missingPmslHours=(0,))
    names = layerNames(tree)
    check("wind layers survive missing pmsl", "Gale_F000-024" in names)
    check("no Features layer without pmsl", "Features_F000-024" not in names,
          str(names))


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
    check("all polygons land in it", len(lines) >= 5, str(len(lines)))
    check("periods are still distinguishable by pattern",
          len(set(l.get("pgenType") for l in lines)) == 2,
          str(set(l.get("pgenType") for l in lines)))


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
          sorted(set(hr for field, hr in CALLS if field == "Wind")) ==
          [0, 6, 12, 18, 24, 30, 36, 42, 48])


def main():
    os.environ["TZ"] = "UTC"
    try:
        time.tzset()
    except AttributeError:
        pass

    test_cycle_selection()
    test_epoch_is_utc()
    test_period_hours()
    test_polygon_extraction()
    test_layers_and_period_maximum()
    test_pgen_line_shape()
    test_color_by_threshold_vs_period()
    test_hatch_fill()
    test_single_period_selection()
    test_features_layer()
    test_land_mask()
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
