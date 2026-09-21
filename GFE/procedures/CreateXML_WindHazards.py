# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# CreateXML_WindHazards.py
#
# Builds one PGEN XML holding 34-47, 48-63 and 64+ kt wind polygons for the
# F000-024 and F024-048 periods, plus mean sea level pressure Lows at F000,
# F024 and F048.
#
# It is a background field to overlay in D2D while writing the High Seas
# text: a guide to what the grids hold, on the same screen as the text,
# instead of a second screen showing the grids themselves.  The text is far
# coarser than the grids - quadrants, semicircles and boxes around a low, not
# gridpoints - so the outline here is deliberately smoothed and simplified
# into something that can be read off and written down.  What that does not
# excuse is an area disappearing quietly, so every contour dropped by the
# noise filters is reported by name and size on the status bar.
#
# The band labels match the Marine Weather Forecast Viewer's legend - Gale
# 34-47, Storm 48-63, Hurricane 64+ - so this overlay and the viewer's
# rendering of the issued text read the same way, and the colors follow the
# usual marine warning convention: yellow gale, orange storm, red hurricane
# force.  Sub-gale is not drawn; adding ("SubGale", "<34", 0.0) to WIND_BANDS
# would draw it.
#
# Patterned on CreateXML.py (stephanie.stevenson) and, like it, subclasses
# A2GraphicsFunctions so the site's own XmlUtils/MathUtils and the
# A2GraphicsConfig dictionaries do the product, layer, pressure extrema and
# storage work.
#
# What it does
# ------------
# * Cycle: "Auto" takes the most recent 00/06/12/18Z cycle at or before now,
#   so 20Z runs the 18Z cycle.  An explicit cycle picks the most recent
#   occurrence of that hour at or before now (18z asked for at 05Z means
#   yesterday's 18Z).
# * Wind: each period's polygons come from the per-gridpoint MAXIMUM Wind
#   magnitude over every grid in the window (F000,006,...,024 for the first
#   period; F024,030,...,048 for the second), so a polygon covers anywhere
#   reaching that force at any point in the period.
# * Bands: 34-48, 48-64 and 64+ kt.  Each band's polygon is the closed
#   contour at its LOWER bound, so the bands overlap - the 34-48 polygon is
#   the whole gale-or-greater area with the 48-64 and 64+ polygons nested
#   inside it.  A PGEN Line cannot carry a hole, and overlapping closed
#   contours are how these charts are drawn anyway.
# * Polygons: the max-wind field is lightly smoothed, optionally zeroed over
#   the Land edit area, then contoured.  Each closed contour becomes a PGEN
#   Line with closed="true".
# * pmsl: Lows only, at F000, F024 and F048 - the endpoints of whichever
#   periods are selected - each hour in its own layer.
# * Output: a single XML with both periods, layers named per band and period
#   (Gale_34-48_F000-024 ... Hurricane_64+_F024-048) plus Lows_F000,
#   Lows_F024 and Lows_F048.
#
# Telling the periods apart
# -------------------------
# "Color by:" in the dialog chooses which dimension carries the color:
#   Band   - each band gets its own color (BAND_COLORS) and each period gets
#            its own line pattern (PERIOD_LINE_TYPES).
#   Period - each period gets its own color (PERIOD_COLORS) and the band is
#            carried by line width (LINE_WIDTH).
# "Hatch fill:" On additionally fills each polygon with the period's hatch
# pattern (PERIOD_FILL_PATTERNS) instead of leaving it as an outline.
#
# One thing to check on first run
# -------------------------------
# The site's XmlUtils has no polygon writer to borrow, so addPolygonToXml
# below emits the PGEN Line element itself.  Open the first XML this writes
# and compare its <Line> against one your existing charts produce (the
# Isobars layer is the closest thing); if the element or color spelling
# differs, addPolygonToXml is the only place to change.
# ----------------------------------------------------------------------------

# The MenuItems list defines the GFE menu item(s) under which the
# Procedure is to appear.
MenuItems = ["Consistency"]

VariableList = [("Cycle:", "Auto", "radio", ["Auto", "00z", "06z", "12z", "18z"]),
                ("Periods:", ["F000-024", "F024-048"], "check", ["F000-024", "F024-048"]),
                ("Input Grid:", "Fcst", "radio", ["Fcst", "Official"]),
                ("Color by:", "Band", "radio", ["Band", "Period"]),
                ("Hatch fill:", "Off", "radio", ["Off", "On"]),
                ("Mask land:", "On", "radio", ["On", "Off"])]

import calendar
import os
import time
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

import numpy as np

try:
    import AbsTime
    import TimeRange
    import A2GraphicsFunctions
    from A2GraphicsFunctions import MathUtils as MathUtils
    from A2GraphicsFunctions import XmlUtils as XmlUtils
    from A2GraphicsConfig import *
    _IN_GFE = True
except ImportError:
    _IN_GFE = False


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Wind bands, weakest first: (name, label, lower bound in knots).  The
# polygon for a band is the closed contour at its lower bound, so the bands
# overlap - Gale is the whole 34 kt-or-greater area, with Storm and Hurricane
# nested inside it.
WIND_BANDS = [("Gale", "34-47", 34.0),
              ("Storm", "48-63", 48.0),
              ("Hurricane", "64+", 64.0)]

# (layer suffix, first forecast hour, last forecast hour) per period.
PERIODS = [("F000-024", 0, 24), ("F024-048", 24, 48)]

# Cycle hours this tool recognizes, and the spacing of the Wind grids read
# inside each period.  Lows are plotted at the endpoints of the selected
# periods, so both periods selected gives F000, F024 and F048.
CYCLE_HOURS = [0, 6, 12, 18]
WIND_GRID_INTERVAL_HRS = 6

# Color by band: the band carries the color, the period carries the pattern.
# The usual marine warning convention - yellow, orange, red.
BAND_COLORS = {"Gale": (255, 255, 0),
               "Storm": (255, 165, 0),
               "Hurricane": (255, 0, 0)}

# Color by period: the period carries the color, the band carries the width.
# Kept clear of the warning colors above so the two modes never look alike.
PERIOD_COLORS = {"F000-024": (0, 255, 255),
                 "F024-048": (0, 150, 255)}

PERIOD_LINE_TYPES = {"F000-024": "LINE_SOLID",
                     "F024-048": "LINE_DASHED_4"}

PERIOD_FILL_PATTERNS = {"F000-024": "FILL_PATTERN_2",
                        "F024-048": "FILL_PATTERN_4"}

LINE_WIDTH = {"Gale": 3.0, "Storm": 4.0, "Hurricane": 5.0}

# PGEN's own render-time smoothing of the polygon it is handed.
SMOOTH_FACTOR = 2

# 3x3 box smoothing passes over the max-wind field before contouring.  Two
# passes take out the gridpoint noise and the scalloping a period maximum
# leaves along a fast track, at the cost of a little drift in the boundary -
# far less drift than the text's own resolution.
SMOOTH_PASSES = 2

# Polygons smaller than either of these are dropped as noise, and every drop
# is reported on the status bar so nothing leaves the chart unannounced.
# 1 sq deg is roughly a 60 x 40 NM box at high-seas latitudes - below
# anything the text would call out.  Polygons with more points than
# MAX_POLYGON_POINTS are decimated so PGEN stays editable.
MIN_POLYGON_POINTS = 4
MIN_POLYGON_AREA_DEG2 = 1.0
MAX_POLYGON_POINTS = 60

# Edit area zeroed out when "Mask land:" is On.
MASK_EDIT_AREA = "Land"

# Delete XML files in outDir older than this.
PURGE_AGE_DAYS = 7


# ---------------------------------------------------------------------------
# Cycle and time handling
#
# Naive datetimes here are always UTC.  Epoch seconds come from
# calendar.timegm, not datetime.timestamp(), so the workstation's TZ cannot
# shift the grids being read.
# ---------------------------------------------------------------------------

def utcNow():
    """Current UTC time as a naive datetime."""
    return datetime(*time.gmtime()[:6])


def resolveCycle(now, cycle=None, cycleHours=None):
    """Return the model cycle datetime to run.

    ``cycle`` None picks the most recent of ``cycleHours`` at or before
    ``now`` - 20Z gives 18Z the same day.  An explicit ``cycle`` hour gives
    the most recent occurrence of that hour at or before ``now``, stepping
    back a day when that hour has not come round yet today.
    """
    if cycleHours is None:
        cycleHours = CYCLE_HOURS
    now = now.replace(minute=0, second=0, microsecond=0)
    if cycle is None:
        hour = max([h for h in sorted(cycleHours) if h <= now.hour])
        return now.replace(hour=hour)
    base = now.replace(hour=int(cycle))
    if base > now:
        base = base - timedelta(days=1)
    return base


def epochSeconds(when):
    """Epoch seconds for a naive UTC datetime, independent of local TZ."""
    return calendar.timegm(when.timetuple())


def makeTimeRange(start, hours=1):
    """One AWIPS TimeRange starting at ``start`` and ``hours`` long."""
    startSecs = epochSeconds(start)
    endSecs = epochSeconds(start + timedelta(hours=hours))
    return TimeRange.TimeRange(AbsTime.AbsTime(startSecs),
                               AbsTime.AbsTime(endSecs))


def periodForecastHours(startHr, endHr, interval=None):
    """Forecast hours to read for a period, both endpoints included."""
    if interval is None:
        interval = WIND_GRID_INTERVAL_HRS
    hours = list(range(int(startHr), int(endHr) + 1, int(interval)))
    if hours and hours[-1] != int(endHr):
        hours.append(int(endHr))
    return hours


def lowHours(selected, periods=None):
    """Forecast hours to plot Lows at: the endpoints of selected periods.

    Both periods gives F000, F024 and F048; F024 is shared and read once.
    """
    if periods is None:
        periods = PERIODS
    hours = set()
    for period, startHr, endHr in periods:
        if period in selected:
            hours.add(int(startHr))
            hours.add(int(endHr))
    return sorted(hours)


# ---------------------------------------------------------------------------
# Grid handling
# ---------------------------------------------------------------------------

def scalarGrid(result):
    """Pull one scalar grid out of whatever getGrids handed back.

    getGrids returns a bare grid for a scalar, an (mag, dir) tuple for a
    vector, or a list of either when more than one grid overlaps the range.
    """
    if result is None:
        return None
    if isinstance(result, (list,)) and len(result) and isinstance(result[0], (tuple, list)):
        return np.asarray(result[0][0], dtype=float)
    if isinstance(result, tuple):
        return np.asarray(result[0], dtype=float)
    grid = np.asarray(result, dtype=float)
    if grid.ndim == 3:
        return grid[0]
    return grid


def magnitudeGrid(result):
    """Wind magnitude from a getGrids result, taking the max if it is a list."""
    if result is None:
        return None
    if isinstance(result, list):
        mags = [magnitudeGrid(item) for item in result]
        mags = [m for m in mags if m is not None]
        if not mags:
            return None
        return np.maximum.reduce(mags)
    if isinstance(result, tuple):
        return np.asarray(result[0], dtype=float)
    grid = np.asarray(result, dtype=float)
    if grid.ndim == 3:
        return np.maximum.reduce([g for g in grid])
    return grid


def maxOverGrids(grids):
    """Per-gridpoint maximum over a list of grids."""
    grids = [np.asarray(g, dtype=float) for g in grids if g is not None]
    if not grids:
        return None
    return np.maximum.reduce(grids)


def smoothGrid(grid, passes=1):
    """Light 3x3 box smoothing, edge-padded.  numpy only, no scipy."""
    out = np.asarray(grid, dtype=float).copy()
    out[~np.isfinite(out)] = 0.0
    for _ in range(max(0, int(passes))):
        p = np.pad(out, 1, mode="edge")
        out = (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] +
               p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:] +
               p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 9.0
    return out


# ---------------------------------------------------------------------------
# Polygon extraction
# ---------------------------------------------------------------------------

def contourSegments(lon, lat, grid, level):
    """Contour ``grid`` at ``level``, returning (lon, lat) point arrays."""
    import matplotlib
    matplotlib.use("Agg", force=False)
    from matplotlib import pyplot as plt

    fig = plt.figure()
    try:
        ax = fig.add_subplot(111)
        cs = ax.contour(np.asarray(lon), np.asarray(lat),
                        np.asarray(grid, dtype=float), levels=[float(level)])
        segs = [np.asarray(seg, dtype=float) for seg in cs.allsegs[0]]
    finally:
        plt.close(fig)
    return segs


def decimatePoints(points, maxPoints=None):
    """Thin ``points`` to at most ``maxPoints``, keeping the first."""
    if maxPoints is None:
        maxPoints = MAX_POLYGON_POINTS
    points = np.asarray(points, dtype=float)
    if maxPoints and len(points) > maxPoints:
        step = int(np.ceil(len(points) / float(maxPoints)))
        points = points[::step]
    return points


def openRing(points):
    """Drop a repeated closing point - PGEN closes the ring itself."""
    points = np.asarray(points, dtype=float)
    if len(points) > 1 and np.allclose(points[0], points[-1]):
        points = points[:-1]
    return points


def ringAreaDeg2(points):
    """Shoelace area of a ring, in square degrees.  Sign discarded."""
    points = openRing(points)
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return abs(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) / 2.0


def extractHazardPolygons(lon, lat, grid, level, minPoints=None, minArea=None,
                          maxPoints=None):
    """Contour ``grid`` at ``level``, returning ``(polygons, dropped)``.

    Polygons are (lat, lon) point arrays.  ``dropped`` holds one
    ``(area, points)`` pair per contour rejected as noise, so the caller can
    say what was left off the chart instead of losing it silently.

    Segments that run off the edge of the domain come back open; PGEN's
    closed="true" joins their ends, which is how a gale area clipped by the
    domain boundary is drawn on these charts.
    """
    if minPoints is None:
        minPoints = MIN_POLYGON_POINTS
    if minArea is None:
        minArea = MIN_POLYGON_AREA_DEG2

    polygons, dropped = [], []
    for seg in contourSegments(lon, lat, grid, level):
        ring = openRing(decimatePoints(seg, maxPoints))
        if len(ring) < 3:
            # Degenerate: cannot enclose an area, so there is nothing to
            # report as having been left off the chart.
            continue
        area = ringAreaDeg2(ring)
        if len(ring) < minPoints or area < minArea:
            dropped.append((area, len(ring)))
            continue
        # contour works in (lon, lat); PGEN wants (lat, lon)
        polygons.append(np.column_stack([ring[:, 1], ring[:, 0]]))
    return polygons, dropped


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------

def polygonStyle(band, period, colorBy="band", hatch=False):
    """PGEN attributes for one band/period combination."""
    colorBy = str(colorBy).lower()
    if colorBy == "period":
        color = PERIOD_COLORS.get(period, (255, 255, 255))
    else:
        color = BAND_COLORS.get(band, (255, 255, 255))
    return {"color": color,
            "pgenType": PERIOD_LINE_TYPES.get(period, "LINE_SOLID"),
            "fillPattern": PERIOD_FILL_PATTERNS.get(period, "FILL_PATTERN_2"),
            "lineWidth": LINE_WIDTH.get(band, 3.0),
            "smoothFactor": SMOOTH_FACTOR,
            "filled": bool(hatch)}


def addPolygonToXml(de, points, style):
    """Append one closed PGEN Line to a DrawableElement element."""
    attrs = {"pgenCategory": "Lines",
             "pgenType": style["pgenType"],
             "closed": "true",
             "filled": "true" if style["filled"] else "false",
             "flagColor": "false",
             "lineWidth": "%.1f" % float(style["lineWidth"]),
             "sizeScale": "1.0",
             "smoothFactor": str(int(style["smoothFactor"]))}
    if style["filled"]:
        attrs["fillPattern"] = style["fillPattern"]

    line = ET.SubElement(de, "Line", attrs)
    red, green, blue = style["color"]
    ET.SubElement(line, "colors", {"red": str(int(red)),
                                   "green": str(int(green)),
                                   "blue": str(int(blue)),
                                   "alpha": "255"})
    for plat, plon in points:
        ET.SubElement(line, "linePoints", {"Lat": "%.4f" % float(plat),
                                           "Lon": "%.4f" % float(plon)})
    return line


# ---------------------------------------------------------------------------
# GFE Procedure
# ---------------------------------------------------------------------------

if _IN_GFE:

    class Procedure(A2GraphicsFunctions.A2GraphicsFunctions):

        def __init__(self, dbss):
            A2GraphicsFunctions.A2GraphicsFunctions.__init__(self, dbss)
            A2GraphicsFunctions.MathUtils.__init__(self, dbss)
            A2GraphicsFunctions.XmlUtils.__init__(self, dbss)

        # -------------------------------------------------------------
        # Grid reads
        # -------------------------------------------------------------

        def _readMaxWind(self, dbase, cycleTime, startHr, endHr):
            """Per-gridpoint max Wind magnitude over one forecast period."""
            mags = []
            for hr in periodForecastHours(startHr, endHr):
                timeRange = makeTimeRange(cycleTime + timedelta(hours=hr))
                result = self.getGrids(dbase, "Wind", "SFC", timeRange,
                                       noDataError=0)
                mag = magnitudeGrid(result)
                if mag is None:
                    self.statusBarMsg("No Wind grid at F%03d - skipped" % hr, "R")
                    continue
                mags.append(mag)
            if not mags:
                return None
            self.statusBarMsg("F%03d-%03d: max wind %.0f kt from %d grid(s)"
                              % (startHr, endHr, np.max(maxOverGrids(mags)),
                                 len(mags)), "R")
            return maxOverGrids(mags)

        def _readPmsl(self, dbase, cycleTime, hr):
            """pmsl grid at one forecast hour, or None."""
            timeRange = makeTimeRange(cycleTime + timedelta(hours=hr))
            result = self.getGrids(dbase, "pmsl", "SFC", timeRange,
                                   noDataError=0)
            return scalarGrid(result)

        # -------------------------------------------------------------
        # Layers
        # -------------------------------------------------------------

        def _windLayers(self, product, saveLayers, defaultDe, wind, lon, lat,
                        period, colorBy, hatch):
            """Add one overlapping polygon layer per wind band for this period."""
            for band, label, level in WIND_BANDS:
                polygons, dropped = extractHazardPolygons(lon, lat, wind, level)

                layerName = band + "_" + label + "_" + period
                # Never lose an area silently - the text has to match the
                # grids, so say what was contoured and left off.
                if dropped:
                    self.statusBarMsg(
                        "%s: %d area(s) below the %.2f sq deg minimum NOT "
                        "drawn (largest %.2f sq deg)"
                        % (layerName, len(dropped), MIN_POLYGON_AREA_DEG2,
                           max(d[0] for d in dropped)), "R")
                if not polygons:
                    self.statusBarMsg("No %s kt area for %s" % (label, period),
                                      "R")
                    continue
                if saveLayers:
                    de = XmlUtils.createXmlLayer(product, layerName)
                else:
                    de = defaultDe
                style = polygonStyle(band, period, colorBy, hatch)
                for polygon in polygons:
                    addPolygonToXml(de, polygon, style)
                self.statusBarMsg("%s: %d polygon(s) at %d kt+"
                                  % (layerName, len(polygons), int(level)), "R")

        def _lowsLayer(self, product, saveLayers, defaultDe, pmsl, lon, lat,
                       basin, hr):
            """Add the pmsl Lows, and their labels, for one forecast hour."""
            pa = pgenAttr_dict["Features"]
            if saveLayers:
                de = XmlUtils.createXmlLayer(product, "Lows_F%03d" % hr)
            else:
                de = defaultDe

            eLon, eLat, eVal = MathUtils.findPressureExtrema(pmsl, lon, lat,
                                                             type="Min")
            xLon, xLat, xVal = XmlUtils.plotPeakPressureLocations(
                eLon, eLat, eVal, basin)
            XmlUtils.xmladdPressureSymbol(xVal, xLat, xLon, de,
                                          pa["low_attr"], pa["low_color"])
            XmlUtils.xmladdPressureExtremaLabel(xVal, xLat, xLon, de,
                                                pa["text_attr"],
                                                pa["text_color"])
            self.statusBarMsg("Lows_F%03d: %d low(s)" % (hr, len(xVal)), "R")

        # -------------------------------------------------------------
        # Housekeeping
        # -------------------------------------------------------------

        def _purgeOldFiles(self):
            cutoff = time.time() - (24 * 60 * 60 * PURGE_AGE_DAYS)
            for filename in os.listdir(outDir):
                filePath = os.path.join(outDir, filename)
                if not os.path.isfile(filePath):
                    continue
                try:
                    if os.path.getmtime(filePath) < cutoff:
                        os.remove(filePath)
                        print("Successfully deleted: %s" % filename)
                except Exception as exc:
                    print("Skipped %s due to error: %s" % (filename, exc))

        # -------------------------------------------------------------
        # Entry point
        # -------------------------------------------------------------

        def execute(self, varDict):

            self.statusBarMsg("Starting CreateXML_WindHazards", "R")

            # --- Read data from user input ---
            cycleOpt = varDict["Cycle:"]
            selected = varDict["Periods:"]
            inputOpt = varDict["Input Grid:"]
            colorBy = str(varDict["Color by:"]).lower()
            hatch = varDict["Hatch fill:"] == "On"
            maskLand = varDict["Mask land:"] == "On"

            if not selected:
                self.statusBarMsg("ERROR: no forecast period selected", "S")
                return

            # --- Resolve the cycle to run ---
            cycle = None if cycleOpt == "Auto" else int(cycleOpt[:2])
            cycleTime = resolveCycle(utcNow(), cycle)
            gridstart = cycleTime.strftime("%Y%m%d%H")
            self.statusBarMsg("Using the %sZ cycle (%s)"
                              % (cycleTime.strftime("%H"), gridstart), "R")

            # --- Set other variables based on environment ---
            basin = self.getSiteID()
            fcstr = os.environ["USER"].split('.')[-1].upper()
            dbase = inputOpt
            if dbase != "Fcst":
                dbase = self.findDatabase(dbase, 0)

            lat, lon = self.getLatLonGrids()

            landmask = None
            if maskLand:
                runEditArea = self.getEditArea(MASK_EDIT_AREA)
                landmask = self.encodeEditArea(runEditArea)

            # --- Create the XML product ---
            pd = pgenProd_dict[basin]
            basin_long = pd["basin"]
            outputFile = (outDir + basin_long + "_WindHazards_" + str(dbase) +
                          "_" + gridstart + ".xml")
            typeSubtype = basin_long + "_WindHazards"

            products, product = XmlUtils.createXmlProduct(
                outputFile, pd["useFile"], pd["saveLayers"], pd["onOff"],
                pd["status"], pd["center"], fcstr, typeSubtype, typeSubtype)

            # Set layer name to Default if saveLayers is false
            saveLayers = str(pd["saveLayers"]).lower() == "true"
            defaultDe = None
            if not saveLayers:
                defaultDe = XmlUtils.createXmlLayer(product, "Default")

            # --- One set of wind band layers per selected period ---
            for period, startHr, endHr in PERIODS:

                if period not in selected:
                    continue
                self.statusBarMsg("creating XML layers for " + period, "R")

                maxWind = self._readMaxWind(dbase, cycleTime, startHr, endHr)
                if maxWind is None:
                    self.statusBarMsg("ERROR: no Wind grids found for " + period,
                                      "S")
                    continue
                wind = smoothGrid(maxWind, SMOOTH_PASSES)
                if landmask is not None:
                    wind = np.where(landmask, 0.0, wind)
                self._windLayers(product, saveLayers, defaultDe, wind, lon, lat,
                                 period, colorBy, hatch)

            # --- Lows at the endpoints of the selected periods ---
            for hr in lowHours(selected):

                pmsl = self._readPmsl(dbase, cycleTime, hr)
                if pmsl is None:
                    self.statusBarMsg("No pmsl grid at F%03d - Lows layer "
                                      "skipped" % hr, "S")
                    continue
                self._lowsLayer(product, saveLayers, defaultDe, pmsl, lon, lat,
                                basin, hr)

            # --- Write XML to a file, then store it to the PGEN database ---
            XmlUtils.writeXML(products, outputFile)
            XmlUtils.storeXML(outputFile)
            self.statusBarMsg("Wrote " + outputFile, "R")

            # --- Attempt to delete XML files older than PURGE_AGE_DAYS ---
            self._purgeOldFiles()

            return
