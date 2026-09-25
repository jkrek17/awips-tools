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
#   magnitude over whatever grids the inventory holds in the window, read one
#   at a time and taking wind[0] explicitly the way CreateXML.py does - a
#   vector read is (magnitude, direction), and a direction in the contours
#   reads as hurricane force everywhere.  A polygon covers anywhere reaching
#   that force at any point in the period.
# * Bands: 34-47, 48-63 and 64+ kt.  Each band's polygon is the closed
#   contour at its LOWER bound, so the bands overlap - the gale polygon is
#   the whole gale-or-greater area with the storm and hurricane polygons
#   nested inside it.  A PGEN Line cannot carry a hole, and overlapping closed
#   contours are how these charts are drawn anyway.
# * Polygons: the max-wind field is lightly smoothed, optionally zeroed over
#   the Land edit area, then contoured.  A contour that comes back on itself
#   becomes a PGEN Line with closed="true"; one that runs off the edge of the
#   domain stays OPEN, because closing it would draw a chord straight across
#   the chart.
# * pmsl: Lows only, at the times a pmsl grid actually exists.  The
#   inventory over the selected span decides the plot times - nothing is
#   forced onto a 6-hourly schedule - and they are then thinned to no closer
#   than LOW_INTERVAL_HRS so an hourly database does not put 49 Lows on the
#   chart.  The Lows are joined into track lines by nearest-neighbor matching
#   from one plot time to the next.
# * Activity: ACTIVITY_NAME, "Default" while testing, or the name built
#   from ACTIVITY_AREA/_PRODUCT/_FHR the way CreateXML.py builds its own.  It
#   goes into both the type and the name, which is what a real chart's
#   Product carries.  The file name follows the real charts either way:
#   <Basin>_<Area>_<Product>.<Fhr>.xml.
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
# The Lows
# --------
# "Lows every:" thins the plotted Low SYMBOLS to 6, 12 or 24 hours apart, or
# takes them off the chart entirely along with the track.  The track is
# always built from every position read (TRACK_INTERVAL_HRS), so drawing a
# mark once a day still leaves a complete line through the low.  "Hour
# labels:" drops the F0xx text beside each mark, and "Low track:" drops the
# line while keeping the marks.  The positions still come from the pmsl
# inventory, so these only ever thin what is there.
#
# Two things to check on first run
# --------------------------------
# 1. The site's XmlUtils has no polygon writer to borrow, so addLineToXml
#    below emits the PGEN Line element itself.  It is matched against a real
#    OPC Isobars Line - <Point Lon Lat> children and a single <Color> - so
#    if a future PGEN changes that, addLineToXml is the only place to edit.
# 2. The forecast-hour label beside each Low goes through the site's
#    XmlUtils.xmladdTextBox, which CreateXML.py only ever calls with the
#    disclaimer box.  It is offset LOW_HOUR_LABEL_OFFSET_DEG degrees of
#    latitude from the Low so it does not land on the symbol and its
#    pressure; widen that if it still crowds them, or set LABEL_LOW_HOURS to
#    False and the hours come off entirely - symbols and pressures stay.
# ----------------------------------------------------------------------------

# The MenuItems list defines the GFE menu item(s) under which the
# Procedure is to appear.
MenuItems = ["Consistency"]

VariableList = [("Cycle:", "Auto", "radio", ["Auto", "00z", "06z", "12z", "18z"]),
                ("Periods:", ["F000-024", "F024-048"], "check", ["F000-024", "F024-048"]),
                ("Input Grid:", "Fcst", "radio", ["Fcst", "Official"]),
                ("Color by:", "Band", "radio", ["Band", "Period"]),
                ("Hatch fill:", "Off", "radio", ["Off", "On"]),
                ("Mask land:", "On", "radio", ["On", "Off"]),
                ("Lows every:", "6 h", "radio", ["6 h", "12 h", "24 h", "Off"]),
                ("Hour labels:", "On", "radio", ["On", "Off"]),
                ("Low track:", "On", "radio", ["On", "Off"])]

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

# The cadence the TRACK is built from.  The track wants every position it
# can get - a line through three marks in 48 hours is not a track - while the
# symbols on the chart want thinning, so the two are separate: "Lows every:"
# thins the symbols only, and the line through them stays complete.
TRACK_INTERVAL_HRS = 6

# The default for "Lows every:", and the closest two plotted Lows may be.
# The plot times come from the pmsl inventory over the selected span, so a
# sparser database simply gives fewer Lows; this only stops a denser one from
# crowding the chart.  It is also the fallback cadence if the inventory
# cannot be read at all.  The dialog overrides it per run.
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
# The site's xmladdPressureSymbol and xmladdPressureExtremaLabel both draw at
# the Low's exact position, so the hour is offset in degrees of latitude
# (negative is south) to keep it off the symbol and its pressure.  One degree
# of latitude is 60 NM everywhere, so the offset reads the same at any
# latitude.
LABEL_LOW_HOURS = True
LOW_HOUR_LABEL_OFFSET_DEG = -2.0

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

# A contour that runs off the edge of the domain comes back OPEN.  Closing it
# would join its two ends with a chord straight across the map, so it is
# drawn as an open line instead and kept only if it is at least this long,
# in degrees.
MIN_OPEN_LINE_DEG = 2.0

# Consecutive contour points further apart than this do not belong to one
# line - a wrap in the longitudes, say - so the contour is split there
# rather than drawn across the gap.
MAX_POINT_JUMP_DEG = 20.0

# The PGEN activity, built the way CreateXML.py builds it:
#
#     basin_long + "_" + area + "_" + prod + "(" + fhr_opt + ")"
#
# giving "Atlantic_HS_WindHazards(F048)", passed twice: a real chart's
# Product carries type and name - no subtype - and both hold that one string.
#
#     <Product outputFile="Atlantic_HS_Surface.F000.xml" ... center="OPC"
#              type="Atlantic_HS_Surface(F000)"
#              name="Atlantic_HS_Surface(F000)">
#
# ACTIVITY_PRODUCT is WindHazards rather than Surface on purpose: an activity
# is identified by that name, so reusing "Surface" would store this chart
# over the real one.
ACTIVITY_AREA = "HS"
ACTIVITY_PRODUCT = "WindHazards"
ACTIVITY_FHR = "F048"

# Set this to use a name of its own instead of the one built above; it goes
# into both type and name.  "Default" while testing, so the chart lands in
# PGEN's stock activity and nothing has to be registered.  None builds
# <basin>_HS_WindHazards(F048) from the three pieces above, which is what to
# use once that activity exists in the site's list.
ACTIVITY_NAME = "Default"

# The output file name follows the real charts' own shape - the forecast
# hour after a dot, no cycle or database in it:
#
#     <Basin>_<Area>_<Product>.<Fhr>.xml      Atlantic_HS_Surface.F000.xml

# The Product's forecaster field.  "" leaves it blank, which PGEN accepts.
# None fills it from $USER in the form a real chart's XML carries -
# "jason.krekeler", the whole user name; CreateXML.py instead keeps the last
# name in capitals ("KREKELER").  Either way nothing here depends on $USER
# being set.
FORECASTER = ""

# A tripwire, not a limit: no marine wind grid holds a value like this, so
# anything above it means the wrong half of a vector grid is being read - a
# direction, which runs to 360 - and the run says so rather than drawing
# hurricane force over the whole basin.
MAX_PLAUSIBLE_WIND_KT = 250.0

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


def vectorMagnitude(result):
    """The MAGNITUDE half of a vector getGrids result, never the direction.

    A vector read is (magnitude, direction).  Direction runs to 360, so
    anything that maxes across that pair - or mistakes a (2, ny, nx) array
    for two separate grids - reports a hurricane-force wind at every
    gridpoint.  CreateXML.py takes wind[0] explicitly for exactly this
    reason, and so does this.
    """
    if result is None:
        return None
    if isinstance(result, tuple):
        return np.asarray(result[0], dtype=float)
    if isinstance(result, list):
        mags = [vectorMagnitude(item) for item in result]
        mags = [m for m in mags if m is not None]
        if not mags:
            return None
        return np.maximum.reduce(mags)
    grid = np.asarray(result, dtype=float)
    if grid.ndim == 3 and grid.shape[0] == 2:
        return grid[0]              # (magnitude, direction)
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


def splitOnJumps(points, maxJump=None):
    """Split a contour wherever consecutive points jump implausibly far.

    A jump like that is not part of the line - it is a wrap in the
    longitudes, or two pieces matplotlib handed back joined - and drawing
    through it puts a stripe across the chart.
    """
    if maxJump is None:
        maxJump = MAX_POINT_JUMP_DEG
    points = np.asarray(points, dtype=float)
    if len(points) < 2:
        return [points]
    steps = np.hypot(np.diff(points[:, 0]), np.diff(points[:, 1]))
    breaks = np.nonzero(steps > maxJump)[0]
    if not len(breaks):
        return [points]
    pieces, start = [], 0
    for b in breaks:
        pieces.append(points[start:b + 1])
        start = b + 1
    pieces.append(points[start:])
    return [p for p in pieces if len(p) > 1]


def isClosedRing(points):
    """True when the contour comes back to where it started."""
    points = np.asarray(points, dtype=float)
    return len(points) > 2 and bool(np.allclose(points[0], points[-1]))


def lineLengthDeg(points):
    """Length of an open line, in degrees."""
    points = np.asarray(points, dtype=float)
    if len(points) < 2:
        return 0.0
    return float(np.sum(np.hypot(np.diff(points[:, 0]),
                                 np.diff(points[:, 1]))))


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
                          maxPoints=None, minOpenLength=None):
    """Contour ``grid`` at ``level``, returning ``(shapes, dropped)``.

    Each shape is ``(points, closed)`` - (lat, lon) point arrays, and whether
    the contour actually came back on itself.  A contour that runs off the
    edge of the domain does NOT: closing it would draw a chord straight
    across the chart, so it is emitted as an open line and kept on its length
    rather than an area that means nothing for an open line.

    ``dropped`` holds one ``(area, points)`` pair per contour rejected as
    noise, so the caller can say what was left off the chart instead of
    losing it silently.
    """
    if minPoints is None:
        minPoints = MIN_POLYGON_POINTS
    if minArea is None:
        minArea = MIN_POLYGON_AREA_DEG2
    if minOpenLength is None:
        minOpenLength = MIN_OPEN_LINE_DEG

    shapes, dropped = [], []
    for seg in contourSegments(lon, lat, grid, level):
        for piece in splitOnJumps(seg):

            if len(piece) < 2:
                # Nothing at all - matplotlib hands back an empty segment
                # when the field never reaches the level.  Not a drop.
                continue

            closed = isClosedRing(piece)
            points = decimatePoints(piece, maxPoints)
            if closed:
                points = openRing(points)
                if len(points) < 3:
                    # Cannot enclose an area, so nothing was left off.
                    continue
                area = ringAreaDeg2(points)
                if len(points) < minPoints or area < minArea:
                    dropped.append((area, len(points)))
                    continue
            else:
                if len(points) < 2 or lineLengthDeg(points) < minOpenLength:
                    dropped.append((0.0, len(points)))
                    continue

            # contour works in (lon, lat); PGEN wants (lat, lon)
            shapes.append((np.column_stack([points[:, 1], points[:, 0]]),
                           closed))
    return shapes, dropped


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
            "fillPattern": "SOLID",
            "lineWidth": TRACK_LINE_WIDTH,
            "smoothFactor": SMOOTH_FACTOR,
            "filled": False}


def addLineToXml(de, points, style, closed=True):
    """Append one PGEN Line, closed or open, to a DrawableElement element.

    Matched attribute for attribute against a Line from a real OPC chart:

        <Line flipSide="false" fillPattern="SOLID" filled="false"
              closed="true" smoothFactor="2" sizeScale="1.0" lineWidth="3.0"
              pgenCategory="Lines" pgenType="LINE_SOLID">
          <Color alpha="255" blue="0" green="255" red="255" />
          <Point Lon="-175.639999" Lat="59.009998" />

    The points are <Point Lon Lat>, not <linePoints>, and the color is a
    single <Color>, not <colors> - PGEN cannot deserialize an activity whose
    elements it does not recognize.
    """
    attrs = {"pgenCategory": "Lines",
             "pgenType": style["pgenType"],
             "closed": "true" if closed else "false",
             "filled": "true" if style["filled"] else "false",
             "flipSide": "false",
             # A real unfilled Line still carries fillPattern="SOLID"; the
             # hatch pattern only applies when the polygon is filled.
             "fillPattern": ((style["fillPattern"] or "SOLID")
                             if style["filled"] else "SOLID"),
             "lineWidth": "%.1f" % float(style["lineWidth"]),
             "sizeScale": "1.0",
             "smoothFactor": str(int(style["smoothFactor"]))}

    line = ET.SubElement(de, "Line", attrs)
    red, green, blue = style["color"]
    ET.SubElement(line, "Color", {"alpha": "255",
                                  "blue": str(int(blue)),
                                  "green": str(int(green)),
                                  "red": str(int(red))})
    for plat, plon in points:
        ET.SubElement(line, "Point", {"Lon": "%.6f" % float(plon),
                                      "Lat": "%.6f" % float(plat)})
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

            One grid at a time, at the hours the inventory actually holds, so
            each read is a plain (magnitude, direction) pair and the
            magnitude can be taken explicitly - the way CreateXML.py does it.
            A ranged read returns those pairs wrapped in ways that are easy
            to mistake for a stack of scalar grids, and mistaking them puts
            the direction into the contours.
            """
            hours = self._inventoryHours(dbase, "Wind", cycleTime, startHr,
                                         endHr)
            if not hours:
                hours = list(range(int(startHr), int(endHr) + 1,
                                   WIND_GRID_INTERVAL_HRS))

            mags = []
            for hr in hours:
                timeRange = makeTimeRange(cycleTime + timedelta(hours=hr))
                result = self.getGrids(dbase, "Wind", "SFC", timeRange,
                                       noDataError=0)
                mag = vectorMagnitude(result)
                if mag is None:
                    continue
                mags.append(mag)

            if not mags:
                return None
            maxWind = maxOverGrids(mags)
            peak = float(np.max(maxWind))

            if peak > MAX_PLAUSIBLE_WIND_KT:
                self.statusBarMsg(
                    "ERROR: F%03d-%03d peaks at %.0f - that is not a wind "
                    "speed.  The direction half of the Wind grid is being "
                    "read, so every band would be wrong.  Nothing drawn."
                    % (startHr, endHr, peak), "S")
                return None

            self.statusBarMsg("F%03d-%03d: max wind %.0f kt from %d grid(s)"
                              % (startHr, endHr, peak, len(mags)), "R")
            return maxWind

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

        def _lowPlotHours(self, dbase, cycleTime, selected, interval=None):
            """When to plot Lows: the pmsl grids there are, thinned."""
            if interval is None:
                interval = LOW_INTERVAL_HRS
            span = periodSpan(selected)
            if span is None:
                return []
            startHr, endHr = span

            hours = self._inventoryHours(dbase, "pmsl", cycleTime, startHr,
                                         endHr)
            if hours is None:
                return lowHours(selected, interval=interval)
            if not hours:
                self.statusBarMsg("No pmsl grids between F%03d and F%03d - no "
                                  "Lows and no track" % (startHr, endHr), "S")
                return []

            thinned = thinHours(hours, interval)
            self.statusBarMsg("pmsl grids at %d time(s) between F%03d and "
                              "F%03d; plotting %d of them, no closer than "
                              "%d h apart"
                              % (len(hours), startHr, endHr, len(thinned),
                                 interval), "R")
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
                shapes, dropped = extractHazardPolygons(lon, lat, wind, level)

                # Never lose an area silently - say what was left off.
                if dropped:
                    self.statusBarMsg(
                        "%s %s kt: %d area(s) below the %.2f sq deg minimum "
                        "NOT drawn (largest %.2f sq deg)"
                        % (period, label, len(dropped), MIN_POLYGON_AREA_DEG2,
                           max(d[0] for d in dropped)), "R")
                if not shapes:
                    self.statusBarMsg("No %s kt area for %s" % (label, period),
                                      "R")
                    continue

                if de is None:
                    de = XmlUtils.createXmlLayer(product, LAYER_NAMES[period])
                style = polygonStyle(band, period, colorBy, hatch)
                for points, closed in shapes:
                    addLineToXml(de, points, style, closed=closed)

                openCount = sum(1 for _, closed in shapes if not closed)
                if openCount:
                    self.statusBarMsg(
                        "%s %s kt: %d area(s) run off the edge of the domain "
                        "and are drawn as open lines, not closed"
                        % (period, label, openCount), "R")
                self.statusBarMsg("%s %s kt: %d shape(s)"
                                  % (period, label, len(shapes)), "R")
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

        def _lowsLayer(self, product, defaultDe, positions, labelHours=None):
            """Add every plotted Low, with its pressure and forecast hour."""
            if labelHours is None:
                labelHours = LABEL_LOW_HOURS
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
                if labelHours:
                    for plat, plon in zip(lats, lons):
                        labelLat = asFloat(plat)
                        if labelLat is None:
                            labelLat = plat          # leave it where it was
                        else:
                            labelLat = labelLat + LOW_HOUR_LABEL_OFFSET_DEG
                        XmlUtils.xmladdTextBox("F%03d" % hr, labelLat, plon,
                                               de, pa["text_attr"],
                                               pa["text_color"])
                total += len(lows)

            self.statusBarMsg("%s: %d low(s) over %d hour(s)"
                              % (LAYER_NAMES["lows"], total, len(positions)),
                              "R")
            return de

        def _trackLayer(self, product, defaultDe, positions, interval=None):
            """Add a line through the Lows that track from one hour to the next.

            ``interval`` is the cadence the Lows were plotted at.  The gap a
            track may survive has to follow it: at 24 h apart, every mark
            would otherwise look like a broken track against the 12 h
            default.  The distance a low may move is scaled by the gap
            against LOW_INTERVAL_HRS, so a day between marks already allows
            four times the movement of six hours.
            """
            if interval is None:
                interval = LOW_INTERVAL_HRS
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

            tracks = buildTracks(trackable,
                                 maxGapHrs=max(TRACK_MAX_GAP_HRS,
                                               2 * int(interval)))
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

            # Defaulted with .get so an older dialog still runs.
            lowEvery = varDict.get("Lows every:", "%d h" % LOW_INTERVAL_HRS)
            labelHours = varDict.get("Hour labels:", "On") == "On"
            wantTrack = varDict.get("Low track:", "On") == "On"

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
            fcstr = FORECASTER
            if fcstr is None:
                fcstr = os.environ.get("USER", "")
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
            outputFile = (outDir + basin_long + "_" + ACTIVITY_AREA + "_" +
                          ACTIVITY_PRODUCT + "." + ACTIVITY_FHR + ".xml")
            typeSubtype = ACTIVITY_NAME
            if typeSubtype is None:
                typeSubtype = (basin_long + "_" + ACTIVITY_AREA + "_" +
                               ACTIVITY_PRODUCT + "(" + ACTIVITY_FHR + ")")
            self.statusBarMsg("PGEN activity: " + typeSubtype, "R")

            products, product = XmlUtils.createXmlProduct(
                outputFile, pd["useFile"], pd["saveLayers"], pd["onOff"],
                pd["status"], pd["center"], fcstr, typeSubtype, typeSubtype)

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

            # --- Lows at the chosen cadence, and the track through them ---
            positions = []
            interval = LOW_INTERVAL_HRS
            if lowEvery == "Off":
                self.statusBarMsg("Lows and track switched off", "R")
            else:
                interval = int(str(lowEvery).split()[0])
                # Read every position the track can use, whatever cadence the
                # symbols end up being drawn at.
                positions = self._readLowPositions(
                    dbase, cycleTime, lon, lat, basin,
                    self._lowPlotHours(dbase, cycleTime, selected,
                                       TRACK_INTERVAL_HRS))

            if positions:
                # Symbols thinned to the chosen cadence; the track keeps every
                # position, so it stays complete however few marks are drawn.
                plotHours = set(thinHours([hr for hr, _ in positions],
                                          interval))
                plotted = [(hr, lows) for hr, lows in positions
                           if hr in plotHours]
                self.statusBarMsg("Lows drawn at %d of the %d position(s) "
                                  "read; the track uses all of them"
                                  % (len(plotted), len(positions)), "R")

                self._lowsLayer(product, defaultDe, plotted, labelHours)
                if wantTrack:
                    self._trackLayer(product, defaultDe, positions,
                                     TRACK_INTERVAL_HRS)
                else:
                    self.statusBarMsg("Track switched off", "R")

            # --- Write XML to a file, then store it to the PGEN database ---
            XmlUtils.writeXML(products, outputFile)
            XmlUtils.storeXML(outputFile)
            self.statusBarMsg("Wrote " + outputFile, "R")

            # --- Attempt to delete XML files older than PURGE_AGE_DAYS ---
            self._purgeOldFiles()

            return
