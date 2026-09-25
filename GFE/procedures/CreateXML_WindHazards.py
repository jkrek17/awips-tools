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
#   magnitude over whatever grids exist in the window - one ranged getGrids
#   call, so the cadence is whatever the grids actually have - and a polygon
#   covers anywhere reaching that force at any point in the period.
# * Bands: 34-47, 48-63 and 64+ kt.  Each band's polygon is the closed
#   contour at its LOWER bound, so the bands overlap - the gale polygon is
#   the whole gale-or-greater area with the storm and hurricane polygons
#   nested inside it.  A PGEN Line cannot carry a hole, and overlapping closed
#   contours are how these charts are drawn anyway.
# * Polygons: the max-wind field is lightly smoothed, optionally zeroed over
#   the Land edit area, then contoured.  Each closed contour becomes a PGEN
#   Line with closed="true".
# * pmsl: Lows only, at the times a pmsl grid actually exists.  The
#   inventory over the selected span decides the plot times - nothing is
#   forced onto a 6-hourly schedule - and they are then thinned to no closer
#   than LOW_INTERVAL_HRS so an hourly database does not put 49 Lows on the
#   chart.  The Lows are joined into track lines by nearest-neighbor matching
#   from one plot time to the next.
# * Activity: stored as PGEN's stock "Default" type (ACTIVITY_TYPE), with
#   <basin>_WindHazards as the subtype label, so nothing has to be added to
#   the site's PGEN activity list.
# * Output: a single XML with four layers - "F000-024" and "F024-048", each
#   holding that period's three band polygons; "Lows", holding every 6-hourly
#   Low with its pressure and forecast hour; and "Track", holding the lines
#   through them.  Layer names are LAYER_NAMES below.
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
# Two things to check on first run
# --------------------------------
# 1. The site's XmlUtils has no polygon writer to borrow, so addLineToXml
#    below emits the PGEN Line element itself.  Open the first XML this
#    writes and compare its <Line> against one your existing charts produce
#    (the Isobars layer is the closest thing); if the element or color
#    spelling differs, addLineToXml is the only place to change.
# 2. The forecast-hour label beside each Low goes through the site's
#    XmlUtils.xmladdTextBox, which CreateXML.py only ever calls with the
#    disclaimer box.  If it wants something other than a plain string, or if
#    the label lands on top of the pressure value, set LABEL_LOW_HOURS to
#    False and the hours come off - the Low symbols and pressures stay.
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
# inside each period.
CYCLE_HOURS = [0, 6, 12, 18]
WIND_GRID_INTERVAL_HRS = 6

# The closest two plotted Lows may be.  The plot times come from the pmsl
# inventory over the selected span, so a sparser database simply gives fewer
# Lows; this only stops a denser one from crowding the chart.  It is also
# the fallback cadence if the inventory cannot be read at all.
LOW_INTERVAL_HRS = 6

# The four layers.  The wind bands share one layer per period, so a period
# can be switched on or off in D2D in one go; the Lows and the track they
# form get a layer each, so the track can come off without losing the
# positions.
LAYER_NAMES = {"F000-024": "F000-024", "F024-048": "F024-048",
               "lows": "Lows", "track": "Track"}

# Track building.  Lows weaker than TRACK_MAX_PRESSURE are still plotted but
# not tracked; a low may move TRACK_MAX_MOVE_NM between consecutive plots and
# still count as the same low (scaled up if a grid is missing and the gap
# widens); a track that goes TRACK_MAX_GAP_HRS unmatched has ended; and a
# single position is not a track.
TRACK_MAX_PRESSURE = 1008.0
TRACK_MAX_MOVE_NM = 600.0
TRACK_MAX_GAP_HRS = 12
MIN_TRACK_POINTS = 2

TRACK_COLOR = (255, 0, 255)
TRACK_LINE_TYPE = "LINE_SOLID"
TRACK_LINE_WIDTH = 2.0

# Label each plotted Low with its forecast hour.  See note 2 in the header.
LABEL_LOW_HOURS = True

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

# The PGEN activity this is stored as.  "Default" is the stock activity
# type, so nothing has to be registered in the site's PGEN activity list -
# unlike a name of its own, which PGEN would not know.  The subtype is the
# label that rides along with it; None means <basin>_WindHazards, so the
# activity is still identifiable among other Default ones.  Set it to "" or
# "Default" if the site's PGEN wants a registered subtype too.
ACTIVITY_TYPE = "Default"
ACTIVITY_SUBTYPE = None

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


def periodSpan(selected, periods=None):
    """The (first hour, last hour) the selected periods cover, or None."""
    if periods is None:
        periods = PERIODS
    bounds = [(s, e) for period, s, e in periods if period in selected]
    if not bounds:
        return None
    return int(min(s for s, _ in bounds)), int(max(e for _, e in bounds))


def thinHours(hours, minSpacing=None):
    """Thin an inventory to hours no closer together than ``minSpacing``.

    The first and last hour are always kept, so the span the grids cover is
    never shortened by the thinning.
    """
    if minSpacing is None:
        minSpacing = LOW_INTERVAL_HRS
    hours = sorted(set(int(h) for h in hours))
    if len(hours) < 2:
        return hours
    kept = [hours[0]]
    for hr in hours[1:-1]:
        if hr - kept[-1] >= minSpacing:
            kept.append(hr)
    if hours[-1] - kept[-1] >= minSpacing:
        kept.append(hours[-1])
    else:
        kept[-1] = hours[-1]
    return kept


def lowHours(selected, periods=None, interval=None):
    """The fallback Low plot times, used only when the inventory is unreadable.

    Both periods at the default interval gives F000, F006 ... F048; only the
    second gives F024 ... F048.
    """
    if interval is None:
        interval = LOW_INTERVAL_HRS
    span = periodSpan(selected, periods)
    if span is None:
        return []
    start, end = span
    hours = list(range(start, end + 1, int(interval)))
    if hours[-1] != end:
        hours.append(end)
    return hours


def asFloat(value, default=None):
    """Coerce a value that may arrive as an already-formatted string.

    plotPeakPressureLocations is the site's own, and some sites hand back
    formatted strings ("968") rather than numbers.  Anything this procedure
    compares or measures goes through here first; what gets handed back to
    XmlUtils stays exactly as the site produced it, so labels are unchanged.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rangeNm(lat1, lon1, lat2, lon2):
    """Range in nautical miles, flat-earth, and safe across the dateline."""
    dLat = (lat2 - lat1) * 60.0
    dLon = (((lon2 - lon1) + 180.0) % 360.0 - 180.0) * 60.0 * np.cos(
        np.radians((lat1 + lat2) / 2.0))
    return float(np.hypot(dLat, dLon))


def buildTracks(positions, maxMoveNm=None, interval=None, maxGapHrs=None,
                minPoints=None):
    """Join Lows from one plot time to the next into tracks.

    ``positions`` is ``[(hr, [(lat, lon, value), ...]), ...]`` in increasing
    hour order.  Each plot time's Lows are matched to the open tracks nearest
    them, shortest distance first, so two tracks never claim the same Low;
    anything unmatched starts a track of its own.  Returns a list of tracks,
    each a list of ``(hr, lat, lon, value)``, dropping any left shorter than
    ``minPoints``.
    """
    if maxMoveNm is None:
        maxMoveNm = TRACK_MAX_MOVE_NM
    if interval is None:
        interval = LOW_INTERVAL_HRS
    if maxGapHrs is None:
        maxGapHrs = TRACK_MAX_GAP_HRS
    if minPoints is None:
        minPoints = MIN_TRACK_POINTS

    tracks = []
    for hr, lows in positions:
        lows = list(lows)
        openTracks = [t for t in tracks if hr - t[-1][0] <= maxGapHrs]

        pairs = []
        for ti, track in enumerate(openTracks):
            lastHr, lastLat, lastLon = track[-1][0], track[-1][1], track[-1][2]
            gap = max(hr - lastHr, interval)
            limit = maxMoveNm * (float(gap) / float(interval))
            for li, (lat, lon, value) in enumerate(lows):
                distance = rangeNm(lastLat, lastLon, lat, lon)
                if distance <= limit:
                    pairs.append((distance, ti, li))
        pairs.sort()

        usedTracks, usedLows = set(), set()
        for _, ti, li in pairs:
            if ti in usedTracks or li in usedLows:
                continue
            usedTracks.add(ti)
            usedLows.add(li)
            lat, lon, value = lows[li]
            openTracks[ti].append((hr, lat, lon, value))

        for li, (lat, lon, value) in enumerate(lows):
            if li not in usedLows:
                tracks.append([(hr, lat, lon, value)])

    return [t for t in tracks if len(t) >= minPoints]


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


def trackStyle():
    """PGEN attributes for a Low track line."""
    return {"color": TRACK_COLOR,
            "pgenType": TRACK_LINE_TYPE,
            "fillPattern": None,
            "lineWidth": TRACK_LINE_WIDTH,
            "smoothFactor": SMOOTH_FACTOR,
            "filled": False}


def addLineToXml(de, points, style, closed=True):
    """Append one PGEN Line, closed or open, to a DrawableElement element."""
    attrs = {"pgenCategory": "Lines",
             "pgenType": style["pgenType"],
             "closed": "true" if closed else "false",
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


def addPolygonToXml(de, points, style):
    """Append one closed wind band polygon."""
    return addLineToXml(de, points, style, closed=True)


def addTrackToXml(de, track):
    """Append one open track line through ``(hr, lat, lon, value)`` points."""
    return addLineToXml(de, [(lat, lon) for _, lat, lon, _ in track],
                        trackStyle(), closed=False)


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
            """Per-gridpoint max Wind magnitude over one forecast period.

            One ranged read, so the grids in the window set their own
            cadence: however many there are, and whatever hours they sit on,
            all of them go into the maximum.
            """
            timeRange = makeTimeRange(cycleTime + timedelta(hours=startHr),
                                      endHr - startHr)
            result = self.getGrids(dbase, "Wind", "SFC", timeRange,
                                   noDataError=0)
            mag = magnitudeGrid(result)
            if mag is None:
                return None
            count = len(result) if isinstance(result, list) else 1
            self.statusBarMsg("F%03d-%03d: max wind %.0f kt from %d grid(s)"
                              % (startHr, endHr, np.max(mag), count), "R")
            return mag

        def _inventoryHours(self, dbase, element, cycleTime, startHr, endHr):
            """Forecast hours where a grid for ``element`` actually exists.

            None means the inventory could not be read at all, which is the
            caller's cue to fall back to a fixed cadence; an empty list means
            it was read and there is genuinely nothing there.
            """
            timeRange = makeTimeRange(cycleTime + timedelta(hours=startHr),
                                      endHr - startHr)
            try:
                infos = self.getGridInfo(dbase, element, "SFC", timeRange)
            except Exception as exc:
                self.statusBarMsg("Could not read the %s inventory (%s) - "
                                  "falling back to every %d h"
                                  % (element, exc, LOW_INTERVAL_HRS), "R")
                return None

            base = epochSeconds(cycleTime)
            hours = []
            for info in infos:
                secs = info.gridTime().startTime().unixTime()
                hr = int(round((secs - base) / 3600.0))
                if startHr <= hr <= endHr:
                    hours.append(hr)
            return sorted(set(hours))

        def _lowPlotHours(self, dbase, cycleTime, selected):
            """When to plot Lows: the pmsl grids there are, thinned."""
            span = periodSpan(selected)
            if span is None:
                return []
            startHr, endHr = span

            hours = self._inventoryHours(dbase, "pmsl", cycleTime, startHr,
                                         endHr)
            if hours is None:
                return lowHours(selected)
            if not hours:
                self.statusBarMsg("No pmsl grids between F%03d and F%03d - no "
                                  "Lows and no track" % (startHr, endHr), "S")
                return []

            thinned = thinHours(hours, LOW_INTERVAL_HRS)
            self.statusBarMsg("pmsl grids at %d time(s) between F%03d and "
                              "F%03d; plotting %d of them"
                              % (len(hours), startHr, endHr, len(thinned)), "R")
            return thinned

        def _readPmsl(self, dbase, cycleTime, hr):
            """pmsl grid at one forecast hour, or None."""
            timeRange = makeTimeRange(cycleTime + timedelta(hours=hr))
            result = self.getGrids(dbase, "pmsl", "SFC", timeRange,
                                   noDataError=0)
            return scalarGrid(result)

        # -------------------------------------------------------------
        # Layers
        # -------------------------------------------------------------

        def _windLayer(self, product, defaultDe, wind, lon, lat, period,
                       colorBy, hatch):
            """Add this period's three overlapping band polygons, one layer.

            ``defaultDe`` None means make a layer of this period's own, and
            only once there is something to put in it - an empty period adds
            no empty layer.
            """
            de = defaultDe

            for band, label, level in WIND_BANDS:
                polygons, dropped = extractHazardPolygons(lon, lat, wind, level)

                # Never lose an area silently - say what was left off.
                if dropped:
                    self.statusBarMsg(
                        "%s %s kt: %d area(s) below the %.2f sq deg minimum "
                        "NOT drawn (largest %.2f sq deg)"
                        % (period, label, len(dropped), MIN_POLYGON_AREA_DEG2,
                           max(d[0] for d in dropped)), "R")
                if not polygons:
                    self.statusBarMsg("No %s kt area for %s" % (label, period),
                                      "R")
                    continue

                if de is None:
                    de = XmlUtils.createXmlLayer(product, LAYER_NAMES[period])
                style = polygonStyle(band, period, colorBy, hatch)
                for polygon in polygons:
                    addPolygonToXml(de, polygon, style)
                self.statusBarMsg("%s %s kt: %d polygon(s)"
                                  % (period, label, len(polygons)), "R")
            return de

        def _readLowPositions(self, dbase, cycleTime, lon, lat, basin, hours):
            """The plotted Lows at each forecast hour, in hour order.

            The positions are the ones plotPeakPressureLocations hands back,
            not the raw extrema, so the track line runs through the symbols
            as they are actually drawn.
            """
            positions = []
            for hr in hours:
                pmsl = self._readPmsl(dbase, cycleTime, hr)
                if pmsl is None:
                    self.statusBarMsg("No pmsl grid at F%03d - no Low plotted "
                                      "for that hour" % hr, "S")
                    continue
                eLon, eLat, eVal = MathUtils.findPressureExtrema(
                    pmsl, lon, lat, type="Min")
                xLon, xLat, xVal = XmlUtils.plotPeakPressureLocations(
                    eLon, eLat, eVal, basin)
                positions.append((hr, [(la, lo, va) for la, lo, va
                                       in zip(xLat, xLon, xVal)]))
            return positions

        def _lowsLayer(self, product, defaultDe, positions):
            """Add every plotted Low, with its pressure and forecast hour."""
            pa = pgenAttr_dict["Features"]
            de = defaultDe
            total = 0

            for hr, lows in positions:
                if not lows:
                    continue
                if de is None:
                    de = XmlUtils.createXmlLayer(product, LAYER_NAMES["lows"])
                lats = [low[0] for low in lows]
                lons = [low[1] for low in lows]
                values = [low[2] for low in lows]
                XmlUtils.xmladdPressureSymbol(values, lats, lons, de,
                                              pa["low_attr"], pa["low_color"])
                XmlUtils.xmladdPressureExtremaLabel(values, lats, lons, de,
                                                    pa["text_attr"],
                                                    pa["text_color"])
                if LABEL_LOW_HOURS:
                    for plat, plon in zip(lats, lons):
                        XmlUtils.xmladdTextBox("F%03d" % hr, plat, plon, de,
                                               pa["text_attr"],
                                               pa["text_color"])
                total += len(lows)

            self.statusBarMsg("%s: %d low(s) over %d hour(s)"
                              % (LAYER_NAMES["lows"], total, len(positions)),
                              "R")
            return de

        def _trackLayer(self, product, defaultDe, positions):
            """Add a line through the Lows that track from one hour to the next."""
            # The site's plotPeakPressureLocations may hand back formatted
            # strings, so coerce before comparing or measuring anything.
            trackable, unusable = [], 0
            for hr, lows in positions:
                kept = []
                for lat, lon, value in lows:
                    fLat = asFloat(lat)
                    fLon = asFloat(lon)
                    fValue = asFloat(value)
                    if fLat is None or fLon is None or fValue is None:
                        unusable += 1
                        continue
                    if fValue <= TRACK_MAX_PRESSURE:
                        kept.append((fLat, fLon, fValue))
                trackable.append((hr, kept))
            if unusable:
                self.statusBarMsg("%d low(s) had no usable position or "
                                  "pressure - not tracked" % unusable, "R")

            tracks = buildTracks(trackable)
            if not tracks:
                self.statusBarMsg("No Low tracked across two or more hours",
                                  "R")
                return defaultDe

            de = defaultDe
            if de is None:
                de = XmlUtils.createXmlLayer(product, LAYER_NAMES["track"])
            for track in tracks:
                addTrackToXml(de, track)
                self.statusBarMsg("Track: F%03d %.0f mb to F%03d %.0f mb, "
                                  "%d position(s)"
                                  % (track[0][0], track[0][3], track[-1][0],
                                     track[-1][3], len(track)), "R")
            return de

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
            subtype = ACTIVITY_SUBTYPE
            if subtype is None:
                subtype = basin_long + "_WindHazards"

            products, product = XmlUtils.createXmlProduct(
                outputFile, pd["useFile"], pd["saveLayers"], pd["onOff"],
                pd["status"], pd["center"], fcstr, ACTIVITY_TYPE, subtype)

            # Set layer name to Default if saveLayers is false
            saveLayers = str(pd["saveLayers"]).lower() == "true"
            defaultDe = None
            if not saveLayers:
                defaultDe = XmlUtils.createXmlLayer(product, "Default")

            # --- One layer of band polygons per selected period ---
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
                self._windLayer(product, defaultDe, wind, lon, lat, period,
                                colorBy, hatch)

            # --- Lows every LOW_INTERVAL_HRS, and the track through them ---
            positions = self._readLowPositions(
                dbase, cycleTime, lon, lat, basin,
                self._lowPlotHours(dbase, cycleTime, selected))
            if positions:
                self._lowsLayer(product, defaultDe, positions)
                self._trackLayer(product, defaultDe, positions)

            # --- Write XML to a file, then store it to the PGEN database ---
            XmlUtils.writeXML(products, outputFile)
            XmlUtils.storeXML(outputFile)
            self.statusBarMsg("Wrote " + outputFile, "R")

            # --- Attempt to delete XML files older than PURGE_AGE_DAYS ---
            self._purgeOldFiles()

            return
