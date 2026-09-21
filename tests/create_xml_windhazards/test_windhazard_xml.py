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


# Layer names the procedure builds, per band and period.  The bands overlap:
# Gale is the whole 34 kt-or-greater area, with Storm and Hurricane nested
# inside it.
# The labels match the Marine Weather Forecast Viewer's warning legend.
GALE1, STORM1, HURR1 = ("Gale_34-47_F000-024", "Storm_48-63_F000-024",
                        "Hurricane_64+_F000-024")
GALE2, STORM2, HURR2 = ("Gale_34-47_F024-048", "Storm_48-63_F024-048",
                        "Hurricane_64+_F024-048")


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
    """A High and a Low whose values encode the forecast hour.

    The High is here on purpose: only Lows are wanted on the chart, so it
    must never appear in the XML.
    """
    grid = np.full((NY, NX), 1013.0)
    grid[10, 10] = 1040.0 + hr        # High - must not be plotted
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
                  missingPmslHours=(), saveLayers="true", windFn=None,
                  pmslFn=None, landFn=None, domain=None):
    """Install fake AWIPS/A2Graphics modules into sys.modules.

    ``windFn(hr, lat, lon)``, ``pmslFn(hr, lat, lon)``, ``landFn(lat, lon)``
    and ``domain`` (a ``(lat2d, lon2d)`` pair) override the bullseye fields
    above, so another script - plot_synthetic_case.py - can drive the real
    procedure over its own case without a second copy of these fakes.
    """
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

        def getGrids(self, dbase, field, level, timeRange, noDataError=1):
            hr = int(round((timeRange.startTime().unixTime() - cycleSecs)
                           / 3600.0))
            CALLS.append((field, hr))
            if field == "Wind":
                if hr in missingWindHours:
                    return None
                if windFn is not None:
                    return windFn(hr, self.lat, self.lon)
                return windAtHour(hr, overLandOnly)
            if field == "pmsl":
                if hr in missingPmslHours:
                    return None
                if pmslFn is not None:
                    return pmslFn(hr, self.lat, self.lon)
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
    check("both periods -> F000, F024, F048",
          m.lowHours(["F000-024", "F024-048"]) == [0, 24, 48])
    check("F000-024 only -> F000, F024", m.lowHours(["F000-024"]) == [0, 24])
    check("F024-048 only -> F024, F048", m.lowHours(["F024-048"]) == [24, 48])
    check("nothing selected -> no hours", m.lowHours([]) == [])


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

    for expected in (GALE1, STORM1, GALE2, STORM2, HURR2,
                     "Lows_F000", "Lows_F024", "Lows_F048"):
        check("layer %s present" % expected, expected in names)
    # The first period peaks at 56 kt (F012), so there must be no 64+ layer
    # for it - and its 48-64 polygon proves a mid-period grid was read.
    check("no %s layer (period max is 56 kt)" % HURR1, HURR1 not in names)
    check("%s has a polygon" % STORM1, len(linesInLayer(tree, STORM1)) == 1)
    check("%s has a polygon" % HURR2, len(linesInLayer(tree, HURR2)) == 1)

    windHours = sorted([hr for field, hr in CALLS if field == "Wind"])
    check("every 6-hourly Wind grid in both periods was read",
          windHours == [0, 6, 12, 18, 24, 24, 30, 36, 42, 48], str(windHours))

    pmslHours = sorted([hr for field, hr in CALLS if field == "pmsl"])
    check("pmsl read at F000, F024 and F048, F024 read once",
          pmslHours == [0, 24, 48], str(pmslHours))

    # Period maximum, not an endpoint snapshot: the gale area for F024-048
    # (peak 80 kt at F036) must be larger than for F000-024 (56 kt at F012).
    gale1 = linesInLayer(tree, GALE1)[0]
    gale2 = linesInLayer(tree, GALE2)[0]

    def ringOf(line):
        pts = [(float(p.get("Lon")), float(p.get("Lat")))
               for p in line.iter("linePoints")]
        return np.asarray(pts)

    check("F024-048 gale area exceeds F000-024 gale area",
          module.ringAreaDeg2(ringOf(gale2)) >
          module.ringAreaDeg2(ringOf(gale1)))

    # The bands overlap rather than being cut out of each other: within one
    # period, each band's polygon sits inside the weaker band's polygon.
    areas = [module.ringAreaDeg2(ringOf(linesInLayer(tree, name)[0]))
             for name in (GALE2, STORM2, HURR2)]
    check("bands overlap: 34-47 contains 48-63 contains 64+",
          areas[0] > areas[1] > areas[2] > 0,
          "%.1f %.1f %.1f" % tuple(areas))

    def bbox(line):
        r = ringOf(line)
        return r[:, 0].min(), r[:, 0].max(), r[:, 1].min(), r[:, 1].max()

    galeBox = bbox(linesInLayer(tree, GALE2)[0])
    hurrBox = bbox(linesInLayer(tree, HURR2)[0])
    check("the 64+ polygon is nested inside the gale polygon",
          (hurrBox[0] > galeBox[0] and hurrBox[1] < galeBox[1] and
           hurrBox[2] > galeBox[2] and hurrBox[3] < galeBox[3]))


def test_pgen_line_shape():
    print("\ntest_pgen_line_shape")
    module, tree = runProcedure(DEFAULT_VARDICT)
    line = linesInLayer(tree, GALE1)[0]
    check("closed polygon", line.get("closed") == "true")
    check("pgenCategory Lines", line.get("pgenCategory") == "Lines")
    check("not filled with Hatch fill Off", line.get("filled") == "false")
    check("no fillPattern when unfilled", line.get("fillPattern") is None)
    check("smoothFactor set", line.get("smoothFactor") == str(module.SMOOTH_FACTOR))
    colors = list(line.iter("colors"))
    check("one color child", len(colors) == 1)
    check("the gale band is the viewer's orange",
          colors and (int(colors[0].get("red")), int(colors[0].get("green")),
                      int(colors[0].get("blue"))) == module.BAND_COLORS["Gale"])
    pts = list(line.iter("linePoints"))
    check("has linePoints", len(pts) >= module.MIN_POLYGON_POINTS, str(len(pts)))
    check("linePoints carry Lat/Lon",
          all(p.get("Lat") is not None and p.get("Lon") is not None for p in pts))


def test_color_by_band_vs_period():
    print("\ntest_color_by_band_vs_period")
    module, tree = runProcedure(DEFAULT_VARDICT)

    def colorOf(layer):
        line = linesInLayer(tree, layer)[0]
        c = list(line.iter("colors"))[0]
        return (int(c.get("red")), int(c.get("green")), int(c.get("blue")))

    def typeOf(t, layer):
        return linesInLayer(t, layer)[0].get("pgenType")

    check("bands differ in color when coloring by band",
          colorOf(GALE1) != colorOf(STORM1))
    check("same band shares color across periods",
          colorOf(GALE1) == colorOf(GALE2))
    check("periods differ by line pattern",
          typeOf(tree, GALE1) != typeOf(tree, GALE2),
          "%s vs %s" % (typeOf(tree, GALE1), typeOf(tree, GALE2)))

    varDict = dict(DEFAULT_VARDICT)
    varDict["Color by:"] = "Period"
    module2, tree2 = runProcedure(varDict)

    def colorOf2(layer):
        line = linesInLayer(tree2, layer)[0]
        c = list(line.iter("colors"))[0]
        return (int(c.get("red")), int(c.get("green")), int(c.get("blue")))

    check("periods differ in color when coloring by period",
          colorOf2(GALE1) != colorOf2(GALE2))
    check("same period shares color across bands",
          colorOf2(GALE1) == colorOf2(STORM1))
    check("period colors match PERIOD_COLORS",
          colorOf2(GALE1) == module2.PERIOD_COLORS["F000-024"])
    check("the band is still readable as line width",
          (linesInLayer(tree2, GALE1)[0].get("lineWidth") !=
           linesInLayer(tree2, STORM1)[0].get("lineWidth")))


def test_hatch_fill():
    print("\ntest_hatch_fill")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Hatch fill:"] = "On"
    module, tree = runProcedure(varDict)
    line1 = linesInLayer(tree, GALE1)[0]
    line2 = linesInLayer(tree, GALE2)[0]
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
    check("selected period is built", GALE2 in names)
    check("no Lows_F000 layer for a period that does not start at F000",
          "Lows_F000" not in names, str(names))
    windHours = sorted([hr for field, hr in CALLS if field == "Wind"])
    check("only that period's Wind grids were read",
          windHours == [24, 30, 36, 42, 48], str(windHours))
    check("pmsl read at that period's endpoints only",
          sorted([hr for field, hr in CALLS if field == "pmsl"]) == [24, 48])


def test_lows_layers():
    print("\ntest_lows_layers")
    module, tree = runProcedure(DEFAULT_VARDICT)
    for hr in (0, 24, 48):
        layer = None
        for el in tree.getroot().iter("Layer"):
            if el.get("name") == "Lows_F%03d" % hr:
                layer = el
        check("Lows_F%03d layer exists" % hr, layer is not None)
        symbols = list(layer.iter("SymbolAttribute"))
        labels = list(layer.iter("TextAttribute"))
        check("Lows_F%03d has one symbol" % hr, len(symbols) == 1,
              str(len(symbols)))
        check("Lows_F%03d has one label" % hr, len(labels) == 1,
              str(len(labels)))
        check("Lows_F%03d uses the low symbol" % hr,
              symbols[0].get("pgenType") == "LOW_PRESSURE_L",
              str(symbols[0].get("pgenType")))
        # pmslAtHour encodes the forecast hour in the extrema values, so the
        # label proves which grid the Low came from.
        check("Lows_F%03d came from F%03d pmsl" % (hr, hr),
              int(labels[0].get("text")) == int(round(960.0 - hr)),
              str(labels[0].get("text")))

    # Only Lows are wanted: the synthetic High (1040 + hr) must be nowhere.
    texts = [el.get("text") for el in tree.getroot().iter("TextAttribute")]
    check("no High is plotted anywhere",
          all(int(t) < 1000 for t in texts), str(texts))
    check("no High symbol is plotted anywhere",
          all(el.get("pgenType") == "LOW_PRESSURE_L"
              for el in tree.getroot().iter("SymbolAttribute")))


def test_land_mask():
    print("\ntest_land_mask")
    varDict = dict(DEFAULT_VARDICT)
    varDict["Mask land:"] = "Off"
    module, tree = runProcedure(varDict, overLandOnly=True)
    check("land bullseye makes polygons with the mask Off",
          GALE1 in layerNames(tree))

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
    check("gale layer survives a missing grid", GALE1 in names, str(names))
    check("storm layer gone with the 56 kt peak grid missing "
          "(40 kt shoulder hours remain)", STORM1 not in names, str(names))

    # Every Wind grid missing: no wind layers, but the Lows are still written.
    module, tree = runProcedure(varDict,
                               missingWindHours=tuple(PEAK_BY_HOUR.keys()))
    names = layerNames(tree)
    check("no wind layers when no Wind grids exist",
          all(n.startswith("Lows") for n in names), str(names))
    check("Lows layers still written", names == ["Lows_F000", "Lows_F024"],
          str(names))

    # One pmsl hour missing: that Lows layer is skipped, the other is not,
    # and the wind layers are untouched.
    module, tree = runProcedure(varDict, missingPmslHours=(0,))
    names = layerNames(tree)
    check("wind layers survive missing pmsl", GALE1 in names)
    check("no Lows_F000 layer without its pmsl grid", "Lows_F000" not in names,
          str(names))
    check("Lows_F024 still written", "Lows_F024" in names, str(names))


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
    test_low_hours()
    test_period_hours()
    test_polygon_extraction()
    test_layers_and_period_maximum()
    test_pgen_line_shape()
    test_color_by_band_vs_period()
    test_hatch_fill()
    test_single_period_selection()
    test_lows_layers()
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
