# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# PressureGapFill.py
#
# Sea level pressure for the strip between a chart's southern edge and the
# southern edge of the GFE grid - 17N up to the grid's edge near 30N on the
# OPC charts - so isobars and pressure centers no longer stop at the grid and
# have to be drawn by hand.  That strip is where the WPAC tropical cyclones
# live, which is why it matters.
#
# The GFE grid has no data there, so the pressure comes from global models
# through the DataAccessLayer - the same route OutOfDomainSpot already uses -
# blended with equal weight across whichever models the forecaster picks.
#
# The blend is then SEAM-MATCHED to the GFE field: along the grid's southern
# edge the model pmsl is corrected to equal the forecaster's grid exactly,
# and that correction fades out over SEAM_FADE_DEG southward.  Isobars cross
# the seam without a jog, the edited grids stay authoritative where they
# exist, and the models govern the tropics.
#
# Nothing here writes XML.  The caller hands each piece to the site's own
# MathUtils.makePressureContours / XmlUtils.xmladdPressureContour (and
# findPressureExtrema for Highs and Lows), so the gap comes out in exactly the
# schema the rest of the chart already uses.
#
# A caveat on blending: averaging models that place a tropical cyclone 100 NM
# apart gives a broader, shallower low than any one of them.  That is fine
# for the synoptic isobars but under-draws a compact typhoon - pick a single
# model when one matters.
# ----------------------------------------------------------------------------

import calendar

import numpy as np

try:
    from ufpy.dataaccess import DataAccessLayer
except ImportError:
    DataAccessLayer = None

try:
    from shapely.geometry import box as envelopeBox
except ImportError:
    envelopeBox = None


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# The chart's southern edge - where the gap starts.
GAP_SOUTH_LAT = 17.0

# Resolution of the grid the gap field is built on, in degrees.
GAP_RES_DEG = 0.25

# The seam correction is full strength at the GFE grid's edge and fades to
# nothing this many degrees south of it.
SEAM_FADE_DEG = 5.0

# The correction is smoothed along the seam over this many columns, so a
# single noisy gridpoint on the edge does not kink every isobar crossing it.
SEAM_SMOOTH_COLS = 9

# A High or Low closer than this to the seam is left to the GFE grid, so the
# same center is never drawn twice - once from each side.
SEAM_MARGIN_DEG = 1.0

# Model data is fetched a little beyond the target so interpolation covers
# its edges.
FETCH_MARGIN_DEG = 1.0

# A High or Low this close to the gap's west, east or south edge is an edge
# artifact - pressure still falling toward the boundary - not a center.
EDGE_MARGIN_DEG = 1.0

# Models the DataAccessLayer reaches at the site, as (dialog name, DAL
# location).  The locations are the ones model_aliases.py and
# OutOfDomainSpot.py already use.
GAP_MODELS = [("GFS", "gfs0p25"),
              ("ECMWF", "ecmwf0p25"),
              ("CMC", "Canadian-NH"),
              ("GEFS", "gefs0p50")]
DEFAULT_GAP_MODELS = ["GFS", "ECMWF"]

# Parameter and level names are tried in order; the first the DAL actually
# offers for that model is used, since naming differs between models.
PMSL_PARAMETERS = ("PMSL", "PRMSL", "MSLP", "MSL", "MSLMA")
PMSL_LEVELS = ("0.0MSL", "0.0SFC")

# How far a model's valid time may sit from the chart's and still count.
VALID_TIME_TOLERANCE_S = 1800


class GapFillError(Exception):
    """A model could not supply the gap - the caller reports it and moves on."""


# ---------------------------------------------------------------------------
# Longitudes
#
# A Pacific chart crosses the dateline, so everything is worked in a frame
# with no jump in it (0..360 when the domain crosses, -180..180 otherwise).
# What goes back to the caller is in whichever convention the GFE grid's own
# longitudes use, so the gap sits in the same longitude space as the rest of
# the chart: a grid given in 0..360 gets 0..360 back, unsplit; one given in
# -180..180 with a jump at the dateline gets -180..180 back, split there.
# ---------------------------------------------------------------------------

def crossesDateline(lon):
    """True when a -180..180 longitude grid wraps across the dateline."""
    lon = np.asarray(lon, dtype=float)
    return float(np.nanmax(lon) - np.nanmin(lon)) > 180.0


def toFrame(lon, use360):
    """Longitudes in the working frame."""
    lon = np.asarray(lon, dtype=float)
    if use360:
        return np.where(lon < 0.0, lon + 360.0, lon)
    return lon


def envelopes(west, east, use360):
    """DAL envelope longitude spans, -180..180, split at the dateline."""
    if not use360:
        return [(west, east)]
    if east <= 180.0:
        return [(west, east)]
    if west >= 180.0:
        return [(west - 360.0, east - 360.0)]
    return [(west, 180.0), (-180.0, east - 360.0)]


# ---------------------------------------------------------------------------
# Grid work
# ---------------------------------------------------------------------------

def regrid(srcLon, srcLat, srcVal, tgtLon, tgtLat):
    """Linear interpolation from any source grid onto target points.

    matplotlib's triangulation handles regular and curvilinear source grids
    alike, with no scipy needed.  Target points outside the source come back
    NaN.
    """
    import matplotlib.tri as mtri

    srcLon = np.asarray(srcLon, dtype=float).ravel()
    srcLat = np.asarray(srcLat, dtype=float).ravel()
    srcVal = np.asarray(srcVal, dtype=float).ravel()
    ok = np.isfinite(srcLon) & np.isfinite(srcLat) & np.isfinite(srcVal)
    if ok.sum() < 3:
        return np.full(np.shape(tgtLon), np.nan)
    tri = mtri.Triangulation(srcLon[ok], srcLat[ok])
    interp = mtri.LinearTriInterpolator(tri, srcVal[ok])
    out = interp(np.asarray(tgtLon, dtype=float),
                 np.asarray(tgtLat, dtype=float))
    return np.ma.filled(np.ma.asarray(out, dtype=float), np.nan)


def blendFields(fields):
    """Equal-weight mean, ignoring a model wherever it has no data."""
    stack = np.array([np.asarray(f, dtype=float) for f in fields])
    count = np.sum(np.isfinite(stack), axis=0)
    total = np.nansum(stack, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def runningMean(values, width):
    """NaN-aware running mean along one axis."""
    values = np.asarray(values, dtype=float)
    if width <= 1 or len(values) < 2:
        return values.copy()
    half = int(width) // 2
    out = np.full(values.shape, np.nan)
    for i in range(len(values)):
        window = values[max(0, i - half):i + half + 1]
        window = window[np.isfinite(window)]
        if len(window):
            out[i] = window.mean()
    return out


def fillAlong(values):
    """Fill NaN by linear interpolation along the axis, holding the ends."""
    values = np.asarray(values, dtype=float)
    good = np.isfinite(values)
    if not good.any():
        return values.copy()
    idx = np.arange(len(values))
    return np.interp(idx, idx[good], values[good])


def southernEdge(gfeLat, gfeLon, gfePmsl, tgtLon1d, use360, res):
    """The GFE grid's southern edge, sampled at each target column.

    Returns (edgeLat, edgePmsl): the lowest latitude the GFE grid reaches in
    each column and its pmsl there.  Works for any projection - for a
    Mercator grid it is simply the bottom row - and columns the GFE grid is
    too coarse to land in are filled along the edge.
    """
    lonF = toFrame(gfeLon, use360).ravel()
    lat = np.asarray(gfeLat, dtype=float).ravel()
    val = np.asarray(gfePmsl, dtype=float).ravel()
    n = len(tgtLon1d)

    cols = np.rint((lonF - tgtLon1d[0]) / res).astype(int)
    ok = (cols >= 0) & (cols < n) & np.isfinite(lat) & np.isfinite(val)
    idx = np.nonzero(ok)[0]
    order = idx[np.lexsort((lat[idx], cols[idx]))]
    c = cols[order]
    first = np.r_[True, c[1:] != c[:-1]] if len(c) else np.array([], bool)

    edgeLat = np.full(n, np.nan)
    edgeVal = np.full(n, np.nan)
    edgeLat[c[first]] = lat[order[first]]
    edgeVal[c[first]] = val[order[first]]
    return fillAlong(edgeLat), fillAlong(edgeVal)


def seamMatch(field, tgtLat1d, edgeLat, edgePmsl, fadeDeg=None,
              smoothCols=None):
    """Correct ``field`` to equal the GFE pmsl along the seam, fading south.

    Returns the corrected field and the per-column correction applied at the
    seam (mb), for reporting.
    """
    if fadeDeg is None:
        fadeDeg = SEAM_FADE_DEG
    if smoothCols is None:
        smoothCols = SEAM_SMOOTH_COLS
    field = np.asarray(field, dtype=float)
    nLat, nLon = field.shape

    # The model's value on the row at, or just south of, the seam.
    rows = np.searchsorted(tgtLat1d, edgeLat + 1e-6, side="right") - 1
    rows = np.clip(rows, 0, nLat - 1)
    atSeam = field[rows, np.arange(nLon)]

    correction = fillAlong(runningMean(edgePmsl - atSeam, smoothCols))
    correction = np.where(np.isfinite(correction), correction, 0.0)

    lat2d = tgtLat1d[:, None]
    weight = np.clip(1.0 - (edgeLat[None, :] - lat2d) / float(fadeDeg),
                     0.0, 1.0)
    return field + weight * correction[None, :], correction


# ---------------------------------------------------------------------------
# DataAccessLayer
# ---------------------------------------------------------------------------

def _epoch(value):
    """Epoch seconds from the date-ish objects the DAL hands back."""
    if value is None:
        return None
    if hasattr(value, "getTime"):                  # java Date: milliseconds
        return value.getTime() / 1000.0
    if hasattr(value, "timetuple"):                # datetime, naive = UTC
        return float(calendar.timegm(value.timetuple()))
    return float(value)


def refEpoch(dataTime):
    return _epoch(dataTime.getRefTime())


def validEpoch(dataTime):
    """When a DataTime is valid: run time plus forecast hour."""
    try:
        return refEpoch(dataTime) + float(dataTime.getFcstTime())
    except Exception:
        return _epoch(dataTime.getValidPeriod().getStart())


def pickDataTime(times, wantEpoch, tolerance=None):
    """The newest model run that has a forecast valid at ``wantEpoch``."""
    if tolerance is None:
        tolerance = VALID_TIME_TOLERANCE_S
    best, bestRef = None, None
    for t in times or []:
        try:
            valid = validEpoch(t)
            ref = refEpoch(t)
        except Exception:
            continue
        if valid is None or abs(valid - wantEpoch) > tolerance:
            continue
        if best is None or ref > bestRef:
            best, bestRef = t, ref
    return best


def _firstOffered(wanted, offered):
    offered = [str(o) for o in (offered or [])]
    for name in wanted:
        if name in offered:
            return name
    return None


def fetchModelPmsl(location, wantEpoch, west, east, south, north, use360,
                   dal=None):
    """pmsl in mb from one model over a box, as flat (lon, lat, value).

    Longitudes come back in the working frame.  Raises GapFillError with a
    reason the caller can show when the model cannot supply it.
    """
    dal = dal if dal is not None else DataAccessLayer
    if dal is None:
        raise GapFillError("DataAccessLayer is not available")

    lons, lats, vals, runs = [], [], [], set()
    for w, e in envelopes(west, east, use360):
        req = dal.newDataRequest()
        req.setDatatype("grid")
        req.setLocationNames(location)

        param = _firstOffered(PMSL_PARAMETERS,
                              dal.getAvailableParameters(req))
        if param is None:
            raise GapFillError("%s offers none of %s"
                               % (location, ", ".join(PMSL_PARAMETERS)))
        req.setParameters(param)

        level = _firstOffered(PMSL_LEVELS, dal.getAvailableLevels(req))
        if level is None:
            raise GapFillError("%s %s has none of the levels %s"
                               % (location, param, ", ".join(PMSL_LEVELS)))
        req.setLevels(level)

        if envelopeBox is not None:
            req.setEnvelope(envelopeBox(w, south, e, north))
        else:
            req.setEnvelope((w, south, e, north))

        dataTime = pickDataTime(dal.getAvailableTimes(req), wantEpoch)
        if dataTime is None:
            raise GapFillError("no %s run has a forecast valid then"
                               % location)
        grids = dal.getGridData(req, [dataTime])
        if not grids:
            raise GapFillError("%s returned no grid" % location)

        grid = grids[0]
        gLon, gLat = grid.getLatLonCoords()
        value = np.asarray(grid.getRawData(), dtype=float)
        if np.nanmax(value) > 2000.0:              # Pa, not mb
            value = value / 100.0
        lons.append(toFrame(gLon, use360).ravel())
        lats.append(np.asarray(gLat, dtype=float).ravel())
        vals.append(value.ravel())
        runs.add(refEpoch(dataTime))

    return (np.concatenate(lons), np.concatenate(lats), np.concatenate(vals),
            max(runs))


# ---------------------------------------------------------------------------
# The gap field
# ---------------------------------------------------------------------------

class GapPiece(object):
    """One contourable piece of the gap, in -180..180 longitudes.

    ``filled`` has no NaN in it, so it can go straight through the site's
    smoothPressure; ``covered`` marks points the GFE grid already has, which
    the caller sets back to NaN after smoothing.  On a grid whose southern
    edge is a line of latitude nothing is covered.
    """

    def __init__(self, lon, lat, filled, covered):
        self.lon = lon
        self.lat = lat
        self.filled = filled
        self.covered = covered

    def field(self):
        """The gap pmsl with GFE-covered points NaN."""
        return np.where(self.covered, np.nan, self.filled)


class GapField(object):
    """The gap's pressure, ready to contour, plus what went into it.

    ``pieces`` are for contouring.  ``whole`` is the same field unsplit, for
    finding Highs and Lows - a center near 180 would otherwise sit on the cut
    edge of both pieces.  Longitudes throughout are in the GFE grid's own
    convention (see the Longitudes section): split at the dateline only when
    that convention is -180..180, and pickExtrema tidies any jump afterwards.
    """

    def __init__(self):
        self.pieces = []
        self.whole = None
        self.used = []          # (model, run epoch)
        self.skipped = []       # (model, reason)
        self.seamCorrection = None
        self.south = GAP_SOUTH_LAT
        self._west = None
        self._edgeLat = None
        self._use360 = False
        self._given360 = False

    def toGiven(self, lonFrame):
        """Working-frame longitudes back in the GFE grid's own convention."""
        lonFrame = np.asarray(lonFrame, dtype=float)
        if self._given360:
            return lonFrame
        return ((lonFrame + 180.0) % 360.0) - 180.0

    def hasGap(self):
        return bool(self.pieces)

    def isInGap(self, lat, lon, margin=None):
        """True for a point in the gap and clear of the seam.

        Used to keep the gap's Highs and Lows away from the seam, where the
        GFE grid draws its own.  Accepts the formatted strings some sites'
        plotPeakPressureLocations hands back.
        """
        if margin is None:
            margin = SEAM_MARGIN_DEG
        if self._edgeLat is None:
            return False
        try:
            lat = float(lat)
            lonF = float(toFrame(float(lon), self._use360))
        except (TypeError, ValueError):
            return False
        col = int(round((lonF - self._west) / GAP_RES_DEG))
        if col < 0 or col >= len(self._edgeLat):
            return False
        return self.south <= lat <= self._edgeLat[col] - margin

    def pickExtrema(self, lons, lats, values):
        """Keep the Highs or Lows that belong to the gap.

        Takes findPressureExtrema's output on ``whole`` and drops centers too
        close to the seam (the GFE grid draws those) or to the gap's other
        edges (artifacts, not centers).  Returns float arrays with
        longitudes in the GFE grid's own convention, ready for
        plotPeakPressureLocations.
        """
        keepLon, keepLat, keepVal = [], [], []
        east = self._west + GAP_RES_DEG * (len(self._edgeLat) - 1) \
            if self._edgeLat is not None else None
        for lon, lat, value in zip(lons, lats, values):
            if not self.isInGap(lat, lon):
                continue
            lonF = float(toFrame(float(lon), self._use360))
            if lonF < self._west + EDGE_MARGIN_DEG or \
                    lonF > east - EDGE_MARGIN_DEG or \
                    float(lat) < self.south + EDGE_MARGIN_DEG:
                continue
            keepLon.append(float(self.toGiven(lonF)))
            keepLat.append(float(lat))
            keepVal.append(float(value))
        return np.array(keepLon), np.array(keepLat), np.array(keepVal)


def buildGapPressure(gfeLat, gfeLon, gfePmsl, wantEpoch, models,
                     dal=None, south=None, fetch=None):
    """Blend, seam-match and cut the gap pmsl for one valid time.

    ``models`` are dialog names from GAP_MODELS.  A model that cannot supply
    the field is skipped with its reason recorded, never fatal: an empty
    GapField simply means the chart goes out as it always has.
    """
    if south is None:
        south = GAP_SOUTH_LAT
    if fetch is None:
        fetch = fetchModelPmsl
    gap = GapField()
    gap.south = float(south)

    gfeLat = np.asarray(gfeLat, dtype=float)
    gfeLon = np.asarray(gfeLon, dtype=float)
    gfePmsl = np.asarray(gfePmsl, dtype=float)
    given360 = bool(np.nanmax(gfeLon) > 180.0)    # the grid's own convention
    use360 = given360 or crossesDateline(gfeLon)
    res = GAP_RES_DEG

    lonF = toFrame(gfeLon, use360)
    west = np.floor(np.nanmin(lonF) / res) * res
    east = np.ceil(np.nanmax(lonF) / res) * res
    tgtLon1d = np.arange(west, east + res / 2.0, res)

    edgeLat, edgePmsl = southernEdge(gfeLat, gfeLon, gfePmsl, tgtLon1d,
                                     use360, res)
    north = float(np.nanmax(edgeLat))
    if not np.isfinite(north) or north <= gap.south + res:
        return gap                      # the grid already reaches the edge

    tgtLat1d = np.arange(gap.south, north + res / 2.0, res)
    tgtLat1d = tgtLat1d[tgtLat1d <= north + 1e-6]
    tgtLon2d, tgtLat2d = np.meshgrid(tgtLon1d, tgtLat1d)

    locations = dict(GAP_MODELS)
    fields = []
    for name in models:
        location = locations.get(name)
        if location is None:
            gap.skipped.append((name, "not a gap model"))
            continue
        try:
            sLon, sLat, sVal, run = fetch(
                location, wantEpoch,
                west - FETCH_MARGIN_DEG, east + FETCH_MARGIN_DEG,
                gap.south - FETCH_MARGIN_DEG, north + FETCH_MARGIN_DEG,
                use360, dal=dal)
        except GapFillError as exc:
            gap.skipped.append((name, str(exc)))
            continue
        except Exception as exc:
            gap.skipped.append((name, "%s: %s" % (type(exc).__name__, exc)))
            continue
        field = regrid(sLon, sLat, sVal, tgtLon2d, tgtLat2d)
        if not np.isfinite(field).any():
            gap.skipped.append((name, "no data over the gap"))
            continue
        fields.append(field)
        gap.used.append((name, run))

    if not fields:
        return gap

    blended = blendFields(fields)
    matched, gap.seamCorrection = seamMatch(blended, tgtLat1d, edgeLat,
                                            edgePmsl)

    # Anywhere no model reached: fill along each row so the site's smoother
    # never sees a NaN.  Global models cover the strip, so this is a guard.
    for i in range(matched.shape[0]):
        matched[i] = fillAlong(matched[i])

    covered = tgtLat2d > edgeLat[None, :] + 1e-6

    gap._west = west
    gap._edgeLat = edgeLat
    gap._use360 = use360
    gap._given360 = given360
    gap.whole = GapPiece(gap.toGiven(tgtLon2d), tgtLat2d, matched, covered)

    # A grid given in 0..360 has no jump, so neither does its gap: one piece.
    if given360:
        gap.pieces.append(GapPiece(tgtLon2d, tgtLat2d, matched, covered))
        return gap

    # A -180..180 gap is split at the dateline, both pieces keeping the 180
    # column so contours meet there.
    if use360 and tgtLon1d[0] < 180.0 < tgtLon1d[-1]:
        westCols = tgtLon1d <= 180.0 + 1e-6
        eastCols = tgtLon1d >= 180.0 - 1e-6
        for cols, shift in ((westCols, 0.0), (eastCols, -360.0)):
            gap.pieces.append(GapPiece(tgtLon2d[:, cols] + shift,
                                       tgtLat2d[:, cols],
                                       matched[:, cols], covered[:, cols]))
    else:
        outLon = tgtLon2d - 360.0 if (use360 and tgtLon1d[0] >= 180.0) \
            else tgtLon2d
        gap.pieces.append(GapPiece(outLon, tgtLat2d, matched, covered))
    return gap
