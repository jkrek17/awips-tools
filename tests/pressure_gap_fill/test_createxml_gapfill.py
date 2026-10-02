#!/usr/bin/env python3
"""End-to-end check of the gap fill inside GFE/procedures/CreateXML.py.

Runs the site's CreateXML.execute() for a Surface chart with Isobars and
Features layers, against fakes of A2GraphicsFunctions / A2GraphicsConfig and
the fake DataAccessLayer from test_pressure_gap_fill.py.  The fake
MathUtils.makePressureContours contours for real with matplotlib, so the
isobars that come out can be checked for what matters: that they continue
south of the grid, and that they JOIN the grid's isobars at the seam rather
than jogging.

    python3 test_createxml_gapfill.py
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
sys.path.insert(0, HERE)
for candidate in (os.path.join(HERE, "..", "..", "GFE", "utilities"),
                  os.path.join(HERE, "..")):
    if os.path.isfile(os.path.join(candidate, "PressureGapFill.py")):
        sys.path.insert(0, candidate)
        break
for candidate in (os.path.join(HERE, "..", "..", "GFE", "procedures"),
                  os.path.join(HERE, "..")):
    if os.path.isfile(os.path.join(candidate, "CreateXML.py")):
        PROC = os.path.join(candidate, "CreateXML.py")
        sys.path.insert(0, candidate)       # TCWind_JTWC, as in GFE
        break

import test_pressure_gap_fill as T                             # noqa: E402

OUT_DIR = os.path.join(HERE, "out")
GRIDSTART = "2026100212"
FHR = 24
VALID = calendar.timegm((datetime(2026, 10, 2, 12) +
                         timedelta(hours=FHR)).timetuple())
STATUS = []
STORED = []
FAILURES = []
TEXT = {}               # the text database: PIL -> bulletin


def check(label, condition, detail=""):
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Fakes of the site's modules
# ---------------------------------------------------------------------------

def installFakes(gfeLat, gfeLon, gfePmsl):
    del STATUS[:]
    del STORED[:]

    for name in ("LogStream", "SmartScript"):
        sys.modules[name] = types.ModuleType(name)

    abstime = types.ModuleType("AbsTime")
    abstime.AbsTime = lambda secs: secs
    sys.modules["AbsTime"] = abstime
    timerange = types.ModuleType("TimeRange")
    timerange.TimeRange = lambda start, end: (start, end)
    sys.modules["TimeRange"] = timerange

    class MathUtils(object):
        def __init__(self, dbss=None):
            pass

        @staticmethod
        def find_nearest(array, value):
            idx = int(np.argmin(np.abs(np.asarray(array) - value)))
            return array[idx], idx

        @staticmethod
        def findCycleDate(cycle):
            return GRIDSTART

        @staticmethod
        def smoothPressure(pmsl):
            return np.asarray(pmsl, dtype=float)

        @staticmethod
        def makePressureContours(lon, lat, pmsl, basin):
            import matplotlib
            matplotlib.use("Agg")
            from matplotlib import pyplot as plt
            fig = plt.figure()
            try:
                cs = fig.add_subplot(111).contour(
                    lon, lat, pmsl, levels=np.arange(960.0, 1061.0, 4.0))
                return [(float(level), [np.asarray(s) for s in segs])
                        for level, segs in zip(cs.levels, cs.allsegs) if segs]
            finally:
                plt.close(fig)

        @staticmethod
        def findPressureExtrema(pmsl, lon, lat, type="Max"):
            pmsl = np.asarray(pmsl, dtype=float)
            ny, nx = pmsl.shape
            core = pmsl[1:-1, 1:-1]
            keep = np.ones(core.shape, dtype=bool)
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    if dj or di:
                        nb = pmsl[1 + dj:ny - 1 + dj, 1 + di:nx - 1 + di]
                        keep &= (core > nb) if type == "Max" else (core < nb)
            jj, ii = np.nonzero(keep)
            return ([lon[j + 1, i + 1] for j, i in zip(jj, ii)],
                    [lat[j + 1, i + 1] for j, i in zip(jj, ii)],
                    [pmsl[j + 1, i + 1] for j, i in zip(jj, ii)])

    class XmlUtils(object):
        def __init__(self, dbss=None):
            pass

        @staticmethod
        def createXmlProduct(outputFile, useFile, saveLayers, onOff, status,
                             center, fcstr, ptype, pname):
            products = ET.Element("Products")
            product = ET.SubElement(products, "Product", {
                "outputFile": os.path.basename(outputFile), "type": ptype,
                "name": pname})
            return products, product

        @staticmethod
        def createXmlLayer(product, name):
            layer = ET.SubElement(product, "Layer", {"name": name})
            return ET.SubElement(layer, "DrawableElement")

        @staticmethod
        def xmladdPressureContour(con_info, de, *attrs):
            for level, segs in con_info:
                for seg in segs:
                    if len(seg) < 2:
                        continue
                    line = ET.SubElement(de, "Line", {"level": "%g" % level})
                    for x, y in seg:
                        ET.SubElement(line, "Point", {"Lon": "%.4f" % x,
                                                      "Lat": "%.4f" % y})

        @staticmethod
        def plotPeakPressureLocations(lons, lats, vals, basin):
            return lons, lats, vals

        @staticmethod
        def xmladdPressureSymbol(vals, lats, lons, de, attr, color):
            for v, la, lo in zip(vals, lats, lons):
                ET.SubElement(de, "Symbol", {"pgenType": attr,
                                             "Lat": "%.2f" % float(la),
                                             "Lon": "%.2f" % float(lo),
                                             "value": "%.1f" % float(v)})

        @staticmethod
        def xmladdPressureExtremaLabel(vals, lats, lons, de, attr, color):
            pass

        @staticmethod
        def writeXML(products, outputFile):
            os.makedirs(os.path.dirname(outputFile), exist_ok=True)
            ET.ElementTree(products).write(outputFile)

        @staticmethod
        def storeXML(outputFile):
            STORED.append(outputFile)

    class A2GraphicsFunctions(object):
        def __init__(self, dbss=None):
            pass

        def statusBarMsg(self, msg, severity):
            STATUS.append((severity, msg))

        def getSiteID(self):
            return "OPC"

        def getTextProductFromDB(self, pil):
            return TEXT.get(pil)

        def getLatLonGrids(self):
            return gfeLat, gfeLon

        def findDatabase(self, name, version):
            return name

        def getGrids(self, dbase, field, level, timeRange, **kw):
            assert field == "pmsl", field
            return gfePmsl

    a2f = types.ModuleType("A2GraphicsFunctions")
    a2f.A2GraphicsFunctions = A2GraphicsFunctions
    a2f.MathUtils = MathUtils
    a2f.XmlUtils = XmlUtils
    sys.modules["A2GraphicsFunctions"] = a2f

    cfg = types.ModuleType("A2GraphicsConfig")
    cfg.outDir = OUT_DIR + os.sep
    cfg.map_dict = {"OPC": {"den_ss": 4, "den_warningwinds": 4,
                            "start_index1_ss": 0, "start_index2_ss": 0,
                            "start_index1_wind": 0, "start_index2_wind": 0,
                            "extra_pts_ss": []}}
    cfg.prod_list = {"OPC": ["12z_HS_Surface_F024"]}
    cfg.layer_dict = {"HS_Surface_Fcst": {"gfeFields": ["pmsl"],
                                          "layers": ["Isobars", "Features"]}}
    cfg.pgenProd_dict = {"OPC": {"basin": "Atlantic", "useFile": "false",
                                 "saveLayers": "true", "onOff": "true",
                                 "status": "UNKNOWN", "center": "OPC"}}
    cfg.pgenAttr_dict = {
        "Isobars": {"cont_attr": "c", "line_attr": "l", "line_color": "y",
                    "line_text_attr": "t", "line_text_color": "w"},
        "Features": {"high_attr": "HIGH", "high_color": "b",
                     "low_attr": "LOW", "low_color": "r",
                     "text_attr": "t", "text_color": "w"}}
    cfg.disclaimer_box_dict = {}
    sys.modules["A2GraphicsConfig"] = cfg


def runChart(gfeLat, gfeLon, gfePmsl, models, extra=None):
    """Run CreateXML once; returns the parsed XML."""
    installFakes(gfeLat, gfeLon, gfePmsl)
    import PressureGapFill
    PressureGapFill.DataAccessLayer = T.FakeDAL(models)

    spec = importlib.util.spec_from_file_location("CreateXML", PROC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    os.environ.setdefault("USER", "first.last")
    varDict = {"Input Grid:": "Fcst", "Area:": "HS", "Product:": "Surface",
               "Fcst Hr:": ["F%03d" % FHR], "Cycle:": "12z"}
    varDict.update(extra or {})
    module.Procedure(None).execute(varDict)
    return ET.parse(STORED[-1])


def layerLines(tree, name):
    for layer in tree.getroot().iter("Layer"):
        if layer.get("name") == name:
            return [(float(line.get("level")),
                     np.array([(float(p.get("Lon")), float(p.get("Lat")))
                               for p in line.iter("Point")]))
                    for line in layer.iter("Line")]
    return []


def symbols(tree):
    return [(s.get("pgenType"), float(s.get("Lat")), float(s.get("Lon")),
             float(s.get("value"))) for s in tree.getroot().iter("Symbol")]


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def model(field, **kw):
    """A fake model whose run has a forecast valid at THIS chart's time."""
    return T.model(field, runs=[(VALID - FHR * 3600, [FHR * 3600])], **kw)


def edited(lon, lat):
    """The forecaster's grid: the GFS field, edited up 3 mb plus a wave, so
    the seam correction has real work to do."""
    return T.gfsField(lon, lat) + 3.0 + 1.5 * np.sin(np.radians(lon * 3.0))


def gfsWithHurricane(lon, lat):
    return T.typhoon(22.0, -50.0, 40.0)(lon, lat)


def ecmwfWithHurricane(lon, lat):
    return T.typhoon(22.5, -50.5, 36.0)(lon, lat) + 1.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_isobars_continue_and_join():
    print("\ntest_isobars_continue_and_join")
    lat, lon = T.gfeGrid(-80.0, -20.0)
    models = {"gfs0p25": model(gfsWithHurricane),
              "ecmwf0p25": model(ecmwfWithHurricane)}
    tree = runChart(lat, lon, edited(lon, lat), models)

    lines = layerLines(tree, "Isobars")
    south = [pts for _, pts in lines if (pts[:, 1] < 29.99).any()]
    check("isobars now continue south of the grid", len(south) > 0,
          str(len(south)))
    check("down to the chart's southern edge",
          min(float(pts[:, 1].min()) for _, pts in lines) < 18.0)
    check("the status bar names the models used",
          any("gap fill: GFS run" in m for _, m in STATUS) and
          any("gap fill: ECMWF run" in m for _, m in STATUS),
          str([m for _, m in STATUS if "gap" in m]))

    gfeEnds, misses = seamMisses(lines)
    check("every GFE isobar meeting the seam is met by a gap isobar",
          gfeEnds and not misses, "unmatched: %s" % misses[:5])

    # And the check has teeth: with the seam matching switched off, the raw
    # blend sits 3 mb under the edited grid and the isobars jog at 30N.
    import PressureGapFill
    original = PressureGapFill.seamMatch
    PressureGapFill.seamMatch = lambda field, *a, **k: (
        np.asarray(field, dtype=float), None)
    try:
        raw = runChart(lat, lon, edited(lon, lat), models)
    finally:
        PressureGapFill.seamMatch = original
    _, rawMisses = seamMisses(layerLines(raw, "Isobars"))
    check("without seam matching the same check finds the jogs",
          len(rawMisses) > 0, str(rawMisses[:3]))


def seamMisses(lines, tolerance=0.3):
    """GFE isobar ends on the 30N edge with no gap isobar of the same value
    ending within ``tolerance`` degrees of longitude."""
    gfeEnds, gapEnds = {}, {}
    for level, pts in lines:
        for end in (pts[0], pts[-1]):
            if abs(end[1] - 30.0) < 0.01:
                north = (pts[:, 1] >= 30.0 - 1e-6).all()
                (gfeEnds if north else gapEnds).setdefault(level, []).append(
                    end[0])
    misses = []
    for level, ends in gfeEnds.items():
        for x in ends:
            near = [abs(x - g) for g in gapEnds.get(level, [])]
            if not near or min(near) > tolerance:
                misses.append((level, round(float(x), 2)))
    return gfeEnds, misses


def test_the_hurricane_gets_its_low():
    print("\ntest_the_hurricane_gets_its_low")
    lat, lon = T.gfeGrid(-80.0, -20.0)
    tree = runChart(lat, lon, edited(lon, lat),
                    {"gfs0p25": model(gfsWithHurricane)},
                    {"Gap models:": ["GFS"]})
    lows = [s for s in symbols(tree) if s[0] == "LOW" and s[1] < 30.0]
    check("one Low in the gap", len(lows) == 1, str(lows))
    if lows:
        _, la, lo, v = lows[0]
        check("where the model put the hurricane",
              abs(la - 22.0) <= 0.3 and abs(lo + 50.0) <= 0.3,
              "%.2fN %.2fW" % (la, -lo))
        check("at the model's depth",
              abs(v - gfsWithHurricane(-50.0, 22.0)) < 1.0, "%.1f" % v)


def test_switched_off_or_unavailable():
    print("\ntest_switched_off_or_unavailable")
    lat, lon = T.gfeGrid(-80.0, -20.0)
    models = {"gfs0p25": model(gfsWithHurricane)}

    def southPoints(tree):
        return sum(int((pts[:, 1] < 29.99).sum())
                   for _, pts in layerLines(tree, "Isobars"))

    off = runChart(lat, lon, edited(lon, lat), models,
                   {"Fill south of grid:": "Off"})
    check("Off: nothing south of the grid, as before", southPoints(off) == 0)
    check("Off: no gap Lows",
          not [s for s in symbols(off) if s[1] < 30.0])

    none = runChart(lat, lon, edited(lon, lat),
                    {"gfs0p25": model(gfsWithHurricane, params=("T",))},
                    {"Gap models:": ["GFS"]})
    check("no model available: the chart still goes out",
          len(layerLines(none, "Isobars")) > 0)
    check("with nothing south of the grid", southPoints(none) == 0)
    check("and the reason on the status bar",
          any(sev == "S" and "GFS skipped" in m for sev, m in STATUS),
          str([m for _, m in STATUS if "gap" in m]))

    old = runChart(lat, lon, edited(lon, lat),
                   {"gfs0p25": model(gfsWithHurricane),
                    "ecmwf0p25": model(ecmwfWithHurricane)})
    check("a dialog without the new rows fills with GFS and ECMWF",
          southPoints(old) > 0 and
          any("gap fill: ECMWF" in m for _, m in STATUS))


def test_pacific_typhoon_on_the_dateline():
    print("\ntest_pacific_typhoon_on_the_dateline")
    lat, lon = T.gfeGrid(130.0, 250.0)
    storm = T.typhoon(21.0, 180.0, 35.0)
    tree = runChart(lat, lon, T.gfsField(lon, lat),
                    {"gfs0p25": model(storm)}, {"Gap models:": ["GFS"]})
    lows = [s for s in symbols(tree) if s[0] == "LOW" and s[1] < 30.0]
    check("a typhoon on 180 is one Low, not two", len(lows) == 1, str(lows))
    if lows:
        check("on the dateline", abs(abs(lows[0][2]) - 180.0) <= 0.3,
              str(lows[0]))
    gapLines = [pts for _, pts in layerLines(tree, "Isobars")
                if (pts[:, 1] < 29.99).all()]
    check("its isobars come out on both sides of the dateline",
          any((pts[:, 0] > 170.0).any() for pts in gapLines) and
          any((pts[:, 0] < -170.0).any() for pts in gapLines))
    check("and every gap point is in -180..180",
          all(((pts[:, 0] >= -180.0) & (pts[:, 0] <= 180.0)).all()
              for pts in gapLines))


def test_typhoon_follows_the_warning():
    print("\ntest_typhoon_follows_the_warning")
    sys.path.insert(0, os.path.join(HERE, "..", "tc_pressure"))
    from synth_warning import jtwcWarning
    import TCPressure
    # The models have a 40 mb typhoon at 21.5N 140.5E at the chart time; the
    # warning, issued 6 h before it, has it at 19.5N 137.5E by then, 950 mb
    # at its initial time.
    tau0 = VALID - 6 * 3600
    TEXT.clear()
    TEXT["NFDTCPWP2"] = jtwcWarning(
        tau0, [(0, 19.0, 138.0, 100, 150), (12, 20.0, 137.0, 100, 150),
               (24, 21.0, 136.0, 95, 160)], 950)
    TCPressure.now = lambda: tau0 + 3 * 3600
    lat, lon = T.gfeGrid(130.0, 250.0)
    models = {"gfs0p25": model(T.typhoon(21.5, 140.5, 40.0))}

    del STATUS[:]
    tree = runChart(lat, lon, T.gfsField(lon, lat), models,
                    {"Gap models:": ["GFS"]})
    lows = [s for s in symbols(tree) if s[0] == "LOW" and s[1] < 30.0]
    check("one Low in the gap", len(lows) == 1, str(lows))
    if lows:
        _, la, lo, v = lows[0]
        check("at the warning position for the chart time, not the model's",
              abs(la - 19.5) <= 0.3 and abs(lo - 137.5) <= 0.3,
              "%.2fN %.2fE" % (la, lo))
        check("near the warning's central pressure", abs(v - 950.0) < 4.0,
              "%.1f" % v)
    said = [m for _, m in STATUS if "TC TESTER" in m]
    check("the status bar says what was moved", len(said) == 1 and
          "F024" in said[0] and "nm off" in said[0], str(said))

    del STATUS[:]
    tree = runChart(lat, lon, T.gfsField(lon, lat), models,
                    {"Gap models:": ["GFS"], "Match TC warnings:": "Off"})
    lows = [s for s in symbols(tree) if s[0] == "LOW" and s[1] < 30.0]
    check("switched off: the Low stays where the model put it",
          len(lows) == 1 and abs(lows[0][1] - 21.5) <= 0.3 and
          abs(lows[0][2] - 140.5) <= 0.3, str(lows))
    check("and nothing is said about warnings",
          not any("TC" in m for _, m in STATUS))
    TEXT.clear()
    TCPressure.now = time.time


def main():
    os.environ["TZ"] = "UTC"
    time.tzset()
    test_isobars_continue_and_join()
    test_the_hurricane_gets_its_low()
    test_switched_off_or_unavailable()
    test_pacific_typhoon_on_the_dateline()
    test_typhoon_follows_the_warning()
    print("")
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
