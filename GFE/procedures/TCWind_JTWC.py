# ----------------------------------------------------------------------------
# TCWind_JTWC.py
#
# GFE Procedure: build Wind grids from JTWC tropical cyclone warnings
# retrieved from the AWIPS text database.
#
# *** EXPERIMENTAL.  NOT OPERATIONALLY VETTED. ***
# Wind fields come from an analytic modified-Rankine vortex fit to the
# quadrant wind radii in the warning text, not from any gridded product.
# The output has not been verified against observations.  Every grid needs
# forecaster review before it informs any product.  See the EXPERIMENTAL
# flag in the tunables block below.
#
# Install to:
#   /awips2/edex/data/utility/common_static/site/<SITE>/gfe/userPython/procedures/
#
# The parser and vortex math have no AWIPS dependencies, so this file can be
# run standalone for testing:
#   python TCWind_JTWC.py sample_bulletin.txt
#
# Author: (OPC)
# ----------------------------------------------------------------------------

MenuItems = ["Populate"]

import re
import sys
import time
import calendar
import subprocess

import numpy as np

try:
    import SmartScript
    import ProcessVariableList
    import TimeRange
    import AbsTime
    _IN_GFE = True
except ImportError:
    _IN_GFE = False


# AWIPS text database product IDs, not the WMO headings.  The WTPN33 PGTW
# heading appears on the bulletin itself, but textdb stores it under NFDTCPWP.
JTWC_PILS_WESTPAC = ["NFDTCPWP1", "NFDTCPWP2", "NFDTCPWP3",
                     "NFDTCPWP4", "NFDTCPWP5"]

# Locations of the command-line textdb, tried in order for the fallback.
TEXTDB_PATHS = ["/awips/fxa/bin/textdb", "/awips2/fxa/bin/textdb", "textdb"]


# ---------------------------------------------------------------------------
# Tunables.  Set these once for the office; they are deliberately not exposed
# in the dialog, because none of them is a per-run decision.
# ---------------------------------------------------------------------------

# Which vortex construction to use.
#
#   "gtcm"     NHC's Gridded TCM / WTCM model, implemented from the Gridded TCM
#              Users Guide v1.9.1 (Santos & DeMaria, 12/4/2023).  One symmetric
#              modified Rankine vortex (Rappin et al. 2013) plus a wavenumber-1
#              asymmetry, fit by weighted least squares to the reported radii.
#              This is what produces NHC's Atlantic/EastPac grids, so a JTWC
#              grid built this way looks like the ones OPC already ingests.
#              It does not pass exactly through the reported radii, and that is
#              deliberate: the guide minimises WIND error rather than radius
#              error precisely because forcing the radii produces unrealistic
#              structure (eq. 7 and the note beneath it).
#
#   "perquad"  Per-quadrant radial fit, tangentially interpolated between
#              quadrant bisectors.  Reproduces every reported radius exactly.
#              This is what NHC's legacy TCMWindTool did - equation (4) in the
#              guide - and what this tool did before the GTCM port.  Kept for
#              comparison; see tests/tcwind_jtwc/compare_vortex_methods.py.
VORTEX_METHOD = "gtcm"

# --- GTCM/WTCM parameters, all from the Users Guide -------------------------
# Schwerdt (1979) asymmetry magnitude, a = A*c**B with c the storm speed in kt.
GTCM_ASYM_A = 1.6                       # eq. (2)
GTCM_ASYM_B = 0.63

# TCM radii are the MAXIMUM extent of that wind in the quadrant; the vortex is
# fit to the quadrant AVERAGE.  The guide converts with this factor, citing the
# Wind Speed Probability model (DeMaria et al. 2009).
GTCM_QUAD_AVG_FACTOR = 0.85

# Weights in the error function.  The Rankine profile is flat at large radii,
# so an unweighted fit is insensitive to the 34 kt points and decays too slowly
# out there; the guide raises their weight to five.
GTCM_W_34 = 5.0                         # eq. (7)
GTCM_W_INNER = 1.0

# The asymmetry is not always aligned with the motion vector, particularly at
# higher latitudes and during extratropical transition.  After the size
# parameters are fit, the guide lets the asymmetry components move up to this
# far from their motion-derived first guess to further reduce the error.
GTCM_ASYM_MAX_DEV_KT = 10.0

# Equations (8) and (9) build the wind field from the tangential wind and the
# asymmetry vector alone - there is no inflow term.  Set this True to rotate
# the result toward the centre by INFLOW_ANGLE_DEG anyway, which departs from
# the guide but matches what the "perquad" construction has always done.
GTCM_APPLY_INFLOW = False

# Iteration limits for the fits.  These bound run time inside GFE; the fits
# converge well inside them on real bulletins.
GTCM_MAX_ITER = 220
GTCM_ASYM_STEPS = 9

# Share of the storm's translation speed added to the field, which makes the
# right of track stronger than the left.  Raising it also pushes the field
# off the reported radii, roughly 3.4 kt of error at 0.5 on a 16 kt mover.
# Applies to "perquad" only; "gtcm" uses GTCM_ASYM_A/B above instead.
MOTION_ASYMMETRY_FRACTION = 0.5

# Degrees the surface wind is rotated toward the center.  Open-water value;
# affects direction only, never speed.
INFLOW_ANGLE_DEG = 22.0

# Radius of maximum wind, in nm.  0 uses the Willoughby-form regression
# (see willoughbyRmax()), clamped below the innermost reported ring.  A
# nonzero value is also clamped, so only settings below the clamp have
# any effect.
RMAX_OVERRIDE_NM = 0.0

# Outside R34 the bulletin says nothing, so the profile tapers exponentially
# rather than extrapolating the inner power law, which decays far too slowly
# and leaves 20 kt winds hundreds of miles out.  The e-folding length is this
# multiple of R34: 1.0 puts 34 kt down to 12.5 kt at twice R34.
OUTER_DECAY_FACTOR = 1.0
MIN_OUTER_DECAY_NM = 30.0

# Hard outer bound on the edit, as a multiple of R34.  With the taper above
# the field self-terminates well inside this, so it is a backstop rather than
# the thing defining the footprint.
MAX_INSERT_RADIUS_FACTOR = 5.0

# Background wind is capped to this inside the footprint before the insert,
# so a model's own copy of the cyclone cannot leave a stronger blob beside
# the analytic one.  None disables it.
BACKGROUND_CAP_KT = 30.0

# Seam smoothing.  Applies only to the ring at the edge of the footprint and
# never inside any storm's R34.  Factor 1 means no smoothing.
SMOOTH_SEAM = True
SMOOTH_FACTOR = 2

# Keep inserting once JTWC flags subtropical or extratropical transition.
INSERT_AFTER_SUBTROPICAL = True

# 1.0 keeps JTWC's 1-minute sustained winds; 0.88 converts to 10-minute.
WIND_AVERAGING_FACTOR = 1.0

# The peak wind sits on a ring at Rmax, which on a coarse grid is often
# narrower than one cell, so whether any grid point samples it depends on
# where the storm center happens to fall between cell corners.  That leaves
# the grid maximum a few knots light, and occasionally much worse, varying
# run to run for no meteorological reason.  With this on, the core is scaled
# so the strongest cell reaches the bulletin's max wind exactly.  The
# correction tapers to zero at the innermost reported ring, so the 64, 50 and
# 34 kt radii do not move.  It only ever corrects upward.
NORMALIZE_CORE_PEAK = True
PEAK_NORMALIZE_MAX_FACTOR = 2.0

# A grid block is valid from its start time on, so each forecast time
# populates the block that begins at it.  If no block begins there, create
# one, otherwise the final group of a bulletin is silently lost whenever the
# Fcst inventory happens to stop at that hour.
CREATE_MISSING_TAU_BLOCKS = True

# Name of the scratch weather element used for preview runs.  It is created
# on the fly as a temporary parm, so it needs no serverConfig entry, is not
# saved or published, and disappears when the forecaster clears it.
PREVIEW_ELEMENT = "WindJTWC"
PREVIEW_MAX_KT = 200.0

# This tool is experimental and has not been operationally vetted.  While
# that is true, the dialog says so and a forecaster must acknowledge it
# before anything is written to Fcst.  Preview runs are always allowed
# without acknowledgement, so evaluating the tool costs nothing.  Set this
# to False once the tool has been through local vetting.
EXPERIMENTAL = True
REQUIRE_ACKNOWLEDGEMENT = True

# Shown in the dialog title and the status bar.  Bump it on every install so
# there is never any doubt about which copy GFE actually loaded.
VERSION = "2026-09-02a"

# A bulletin older than this is treated as a dead slot and skipped.  textdb
# returns whatever was last stored under a PIL, so without this check a storm
# that dissipated days ago is rebuilt on every run.  JTWC issues every six
# hours, so anything past 12 is either stale or the feed has stopped.
MAX_BULLETIN_AGE_HOURS = 12.0


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EARTH_R_NM = 3440.065
KT2MS = 0.514444
KM2NM = 1.0 / 1.852

QUADS = ["NE", "SE", "SW", "NW"]
QUAD_WORD = {
    "NORTHEAST": "NE",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
    "NORTHWEST": "NW",
}
QUAD_AZ = {"NE": 45.0, "SE": 135.0, "SW": 225.0, "NW": 315.0}

MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
          "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}

# Confidence weight applied to the vortex as the system loses tropical
# structure.  The Rankine assumption stops being defensible once JTWC flags
# subtropical transition, so we hand the field back to the background.
CONF_TROPICAL = 1.00
CONF_BECOMING = 0.60
CONF_SUBTROPICAL = 0.25


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

RE_REFDATE = re.compile(r"\b(\d{2})([A-Z]{3})(\d{2})\b")
RE_POSITION = re.compile(
    r"(\d{6})Z\s*---\s*(?:NEAR\s+)?(\d+(?:\.\d+)?)\s*([NS])\s+(\d+(?:\.\d+)?)\s*([EW])")
RE_TAU = re.compile(r"^\s*(\d+)\s+HRS,\s+VALID AT:")
RE_WARNPOS = re.compile(r"^\s*WARNING POSITION:")
RE_WINDS = re.compile(
    r"MAX SUSTAINED WINDS\s*-\s*(\d+)\s*KT(?:\s*,\s*GUSTS\s*(\d+)\s*KT)?")
RE_RAD_START = re.compile(
    r"RADIUS OF\s+(\d+)\s*KT WINDS\s*-\s*(\d+)\s*NM\s+(\w+)\s+QUADRANT")
RE_RAD_CONT = re.compile(r"^\s*(\d+)\s*NM\s+(\w+)\s+QUADRANT")
RE_VECTOR = re.compile(
    r"VECTOR TO\s+(\d+)\s*HR POSIT:\s*(\d+)\s*DEG/\s*(\d+)\s*KTS")
RE_MOVEMENT = re.compile(
    r"MOVEMENT PAST SIX HOURS\s*-\s*(\d+)\s*DEGREES AT\s*(\d+)\s*KTS")
RE_REMARKS = re.compile(r"^\s*REMARKS:")
RE_STORM = re.compile(
    r"(SUPER TYPHOON|TYPHOON|TROPICAL STORM|TROPICAL DEPRESSION|"
    r"SUBTROPICAL STORM|SUBTROPICAL DEPRESSION)\s+(\d{1,2}[A-Z])"
    r"\s*(?:\(([^)]+)\))?")
RE_WARNNR = re.compile(r"WARNING\s+NR\s+(\d+)")
# \s+ between words, not a literal space: REMARKS text is word-wrapped at
# ~72 columns and "MINIMUM CENTRAL PRESSURE" does land split across a line
# break in real bulletins, which a literal space would silently miss.
RE_PRESSURE = re.compile(
    r"MINIMUM\s+CENTRAL\s+PRESSURE.*?(\d+)\s*MB", re.DOTALL)


class Tau(object):
    """One forecast time from the warning."""

    def __init__(self, tau):
        self.tau = tau              # forecast hour
        self.epoch = None           # unix seconds, valid time
        self.lat = None
        self.lon = None             # negative west
        self.vmax = None            # kt, 1-min sustained
        self.gust = None
        self.radii = {}             # {34: {"NE": nm, ...}, 50: {...}, 64: {...}}
        self.motionDir = None       # heading toward next position
        self.motionSpd = None       # kt
        self.conf = CONF_TROPICAL

    def quad(self, threshold):
        """Radii dict for a threshold, zeros if the threshold is absent."""
        return self.radii.get(threshold, dict((q, 0.0) for q in QUADS))

    def __repr__(self):
        return "<Tau %02dh %.1f/%.1f vmax=%s conf=%.2f radii=%s>" % (
            self.tau, self.lat, self.lon, self.vmax, self.conf,
            sorted(self.radii.keys()))


def _dtg_to_epoch(ddhhmm, ref_day, ref_month, ref_year):
    """Resolve a DDHHMM group against the bulletin's reference date."""
    dd = int(ddhhmm[0:2])
    hh = int(ddhhmm[2:4])
    mm = int(ddhhmm[4:6])

    month, year = ref_month, ref_year
    if dd < ref_day and (ref_day - dd) > 15:
        month += 1
        if month > 12:
            month = 1
            year += 1
    elif dd > ref_day and (dd - ref_day) > 15:
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    return calendar.timegm((year, month, dd, hh, mm, 0, 0, 0, 0))


def parseJTWC(text):
    """Parse a WTPN warning into a time-ordered list of Tau objects.

    Returns (taus, header) where header is a dict of odds and ends.
    """
    if isinstance(text, (list, tuple)):
        lines = list(text)
    else:
        lines = text.split("\n")

    # Reference date lives in the remarks block ("27AUG26.").
    ref_day = ref_month = ref_year = None
    for ln in lines:
        m = RE_REFDATE.search(ln)
        if m and m.group(2) in MONTHS:
            ref_day = int(m.group(1))
            ref_month = MONTHS[m.group(2)]
            ref_year = 2000 + int(m.group(3))
            break
    if ref_day is None:
        raise ValueError("Could not find a DDMMMYY reference date in the "
                         "bulletin remarks; cannot resolve DTGs.")

    taus = []
    cur = None
    cur_threshold = None
    in_remarks = False
    pending_vectors = {}   # tau hour -> (dir, spd) taken from VECTOR TO lines

    for ln in lines:
        if RE_REMARKS.match(ln):
            in_remarks = True

        if not in_remarks:
            if RE_WARNPOS.match(ln):
                cur = Tau(0)
                taus.append(cur)
                cur_threshold = None
                continue

            m = RE_TAU.match(ln)
            if m:
                cur = Tau(int(m.group(1)))
                taus.append(cur)
                cur_threshold = None
                continue

        if cur is None:
            continue

        if not in_remarks:
            m = RE_POSITION.search(ln)
            if m and cur.lat is None:
                cur.epoch = _dtg_to_epoch(m.group(1), ref_day, ref_month,
                                          ref_year)
                lat = float(m.group(2))
                if m.group(3) == "S":
                    lat = -lat
                lon = float(m.group(4))
                if m.group(5) == "W":
                    lon = -lon
                cur.lat, cur.lon = lat, lon
                continue

            m = RE_WINDS.search(ln)
            if m:
                cur.vmax = float(m.group(1))
                if m.group(2):
                    cur.gust = float(m.group(2))
                continue

            m = RE_RAD_START.search(ln)
            if m:
                cur_threshold = int(m.group(1))
                cur.radii.setdefault(cur_threshold,
                                     dict((q, 0.0) for q in QUADS))
                q = QUAD_WORD.get(m.group(3).upper())
                if q:
                    cur.radii[cur_threshold][q] = float(m.group(2))
                continue

            m = RE_RAD_CONT.match(ln)
            if m and cur_threshold is not None:
                q = QUAD_WORD.get(m.group(2).upper())
                if q:
                    cur.radii[cur_threshold][q] = float(m.group(1))
                continue

            m = RE_MOVEMENT.search(ln)
            if m:
                cur.motionDir = float(m.group(1))
                cur.motionSpd = float(m.group(2))
                continue

            m = RE_VECTOR.search(ln)
            if m:
                # "VECTOR TO 24 HR POSIT" appears in the 12 HR block and
                # describes motion out of that block.
                cur.motionDir = float(m.group(2))
                cur.motionSpd = float(m.group(3))
                pending_vectors[int(m.group(1))] = (cur.motionDir,
                                                    cur.motionSpd)
                continue

            if "BECOMING SUBTROPICAL" in ln or "BECOMING EXTRATROPICAL" in ln:
                cur.conf = CONF_BECOMING
            elif re.search(r"^\s*(SUB|EXTRA)TROPICAL\s*$", ln):
                cur.conf = CONF_SUBTROPICAL

    # Drop anything incomplete, then order by valid time.
    taus = [t for t in taus
            if t.lat is not None and t.epoch is not None and t.vmax is not None]
    taus.sort(key=lambda t: t.epoch)

    # Once a system is flagged subtropical it stays that way downstream.
    worst = CONF_TROPICAL
    for t in taus:
        worst = min(worst, t.conf)
        t.conf = worst

    # Backfill motion where a block had no vector line.
    for i, t in enumerate(taus):
        if t.motionSpd is None:
            if i + 1 < len(taus):
                t.motionDir, t.motionSpd = _bearing_speed(taus[i], taus[i + 1])
            elif i > 0:
                t.motionDir = taus[i - 1].motionDir
                t.motionSpd = taus[i - 1].motionSpd
            else:
                t.motionDir, t.motionSpd = 0.0, 0.0

    full = "\n".join(lines)
    header = {"refDate": (ref_day, ref_month, ref_year),
              "systemType": None, "stormId": None, "stormName": None,
              "warningNumber": None, "pressureMb": None}

    m = RE_STORM.search(full)
    if m:
        header["systemType"] = m.group(1)
        header["stormId"] = m.group(2)
        header["stormName"] = m.group(3)

    m = RE_WARNNR.search(full)
    if m:
        header["warningNumber"] = int(m.group(1))

    m = RE_PRESSURE.search(full)
    if m:
        header["pressureMb"] = int(m.group(1))

    return taus, header


def describeStorm(header):
    """Short human label for the parsed system, for status messages."""
    bits = []
    if header.get("systemType"):
        bits.append(header["systemType"])
    if header.get("stormId"):
        bits.append(header["stormId"])
    if header.get("stormName"):
        bits.append("(%s)" % header["stormName"])
    label = " ".join(bits) if bits else "unidentified system"
    if header.get("warningNumber") is not None:
        label += " warning %d" % header["warningNumber"]
    return label


def _bearing_speed(t1, t2):
    """Great-circle heading (deg) and speed (kt) between two Tau positions."""
    lat1, lon1 = np.radians(t1.lat), np.radians(t1.lon)
    lat2, lon2 = np.radians(t2.lat), np.radians(t2.lon)
    dlon = lon2 - lon1
    y = np.sin(dlon) * np.cos(lat2)
    x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    brg = np.degrees(np.arctan2(y, x)) % 360.0

    a = (np.sin((lat2 - lat1) / 2.0) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2)
    dist = 2.0 * EARTH_R_NM * np.arcsin(np.sqrt(min(max(a, 0.0), 1.0)))
    dt = max(t2.epoch - t1.epoch, 1) / 3600.0
    return float(brg), float(dist / dt)


# ---------------------------------------------------------------------------
# Track interpolation
# ---------------------------------------------------------------------------

class Snapshot(object):
    """Fully specified storm state at an arbitrary time."""

    def __init__(self):
        self.epoch = None
        self.lat = self.lon = None
        self.vmax = None
        self.radii = {}
        self.motionDir = self.motionSpd = None
        self.conf = CONF_TROPICAL


def interpolateTrack(taus, epoch):
    """Linear interpolation of the storm state to an arbitrary valid time."""
    if epoch <= taus[0].epoch:
        lo = hi = taus[0]
        f = 0.0
    elif epoch >= taus[-1].epoch:
        lo = hi = taus[-1]
        f = 0.0
    else:
        lo = hi = taus[0]
        for i in range(len(taus) - 1):
            if taus[i].epoch <= epoch <= taus[i + 1].epoch:
                lo, hi = taus[i], taus[i + 1]
                break
        span = float(hi.epoch - lo.epoch)
        f = (epoch - lo.epoch) / span if span > 0 else 0.0

    s = Snapshot()
    s.epoch = epoch
    s.lat = lo.lat + f * (hi.lat - lo.lat)

    # Guard the dateline.
    dlon = hi.lon - lo.lon
    if dlon > 180.0:
        dlon -= 360.0
    elif dlon < -180.0:
        dlon += 360.0
    s.lon = ((lo.lon + f * dlon + 180.0) % 360.0) - 180.0

    s.vmax = lo.vmax + f * (hi.vmax - lo.vmax)
    s.conf = lo.conf + f * (hi.conf - lo.conf)
    s.motionDir = lo.motionDir
    s.motionSpd = lo.motionSpd + f * (hi.motionSpd - lo.motionSpd)

    # Radii: a threshold missing at one end interpolates from zero, so a
    # 64-kt ring that first appears at 24h grows in rather than popping.
    for threshold in (64, 50, 34):
        a = lo.quad(threshold)
        b = hi.quad(threshold)
        vals = dict((q, a[q] + f * (b[q] - a[q])) for q in QUADS)
        if max(vals.values()) > 0.0:
            s.radii[threshold] = vals
    return s


# ---------------------------------------------------------------------------
# Vortex construction
# ---------------------------------------------------------------------------

def willoughbyRmax(vmax_kt, lat_deg):
    """Rmax regression, returned in nautical miles.

    Same functional form as Willoughby et al. (2006) - exponential in
    intensity and latitude - but refit against 13,834 real JTWC WestPac
    best-track records (2005-2024, IBTrACS, agency jtwc_wp - see
    besttrack_common.MIN_SEASON for why 2005, not 2001) rather than
    Willoughby's original Atlantic coefficients (A=46.4, B=-0.0155,
    C=0.0169). Those underestimated JTWC's own post-season RMW by ~10 nm
    on average across this dataset (worst for weak systems); this refit's
    out-of-sample bias on a held-out 20% of storms (never used for
    fitting) is -1.9 nm, MAE 9.0 nm, vs -9.4 nm / 12.4 nm for the
    original coefficients over the same held-out storms. See
    tests/tcwind_jtwc/fit_westpac_rmax.py, which produced these
    coefficients and reports the full validation, and
    tests/tcwind_jtwc/verify_besttrack_rmax.py, which reproduces the
    original comparison this replaces.
    """
    v_ms = vmax_kt * KT2MS
    rmax_km = 98.392 * np.exp(-0.025088 * v_ms + 0.003021 * abs(lat_deg))
    return rmax_km * KM2NM


def resolveRmax(snapshot, override_nm=0.0):
    """Rmax estimate, clamped so it stays inside the highest reported ring.

    JTWC never gives Rmax.  willoughbyRmax() is fit to WestPac best-track
    data and is unbiased on average (see verify_besttrack_rmax.py), but a
    2-parameter (intensity, latitude) regression has essentially no skill
    predicting any *individual* storm's Rmax, especially a weak one - the
    reported radii, when there are any, are real per-storm information the
    regression cannot have, so they win.
    """
    if override_nm and override_nm > 0:
        rmax = float(override_nm)
    else:
        rmax = willoughbyRmax(snapshot.vmax, snapshot.lat)

    for threshold in (64, 50, 34):
        if threshold not in snapshot.radii:
            continue
        # vmax < threshold (not <=): a storm whose peak exactly equals a
        # threshold (e.g. a 50kt storm reporting R50) still reaches it -
        # JTWC would not report a radius for a threshold it hadn't reached,
        # so only a *stale* radius (already below the storm's current
        # threshold) should be excluded here.
        if snapshot.vmax < threshold:
            continue
        nonzero = [v for v in snapshot.radii[threshold].values() if v > 0.0]
        if nonzero:
            rmax = min(rmax, 0.7 * min(nonzero))
        break

    return max(rmax, 3.0)


def _distBearingGrids(latGrid, lonGrid, clat, clon):
    """Great-circle distance (nm) and bearing from center (deg true)."""
    lat1 = np.radians(clat)
    lon1 = np.radians(clon)
    lat2 = np.radians(latGrid)
    lon2 = np.radians(((lonGrid + 180.0) % 360.0) - 180.0)
    dlon = lon2 - lon1

    sin_lat1, cos_lat1 = np.sin(lat1), np.cos(lat1)
    sin_lat2, cos_lat2 = np.sin(lat2), np.cos(lat2)

    a = (np.sin((lat2 - lat1) / 2.0) ** 2
         + cos_lat1 * cos_lat2 * np.sin(dlon / 2.0) ** 2)
    dist = 2.0 * EARTH_R_NM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))

    y = np.sin(dlon) * cos_lat2
    x = cos_lat1 * sin_lat2 - sin_lat1 * cos_lat2 * np.cos(dlon)
    brg = np.degrees(np.arctan2(y, x)) % 360.0
    return dist, brg


def _azimuthalRadii(azGrid, quadDict, floor_nm):
    """Interpolate the four quadrant radii smoothly around the compass.

    A 000 NM quadrant means the profile never reaches that speed there, not
    that the radius is zero.  Collapsing it onto the core produces the steep
    gradient that is actually implied.
    """
    vals = []
    for q in QUADS:
        v = quadDict.get(q, 0.0)
        vals.append(v if v > 0.0 else floor_nm)

    knots_x = np.array([45.0, 135.0, 225.0, 315.0, 405.0])
    knots_y = np.array(vals + [vals[0]])
    az = np.where(azGrid < 45.0, azGrid + 360.0, azGrid)
    return np.interp(az, knots_x, knots_y)


def _gtcmClimoRmax(vmax, lat):
    """Climatological RMW in nm.  Users Guide eq. (5)."""
    return float(np.exp(3.7450 - 0.01338 * float(vmax) + 0.01908 * abs(float(lat))))


def _gtcmClimoX(vmax, lat):
    """Climatological size parameter, non-dimensional.  Users Guide eq. (6)."""
    return float(0.1989 + 0.00475 * float(vmax) + 0.00142 * abs(float(lat)))


def _gtcmAsymmetry(motionSpd):
    """Schwerdt (1979) asymmetry magnitude in kt.  Users Guide eq. (2)."""
    if not motionSpd or motionSpd <= 0:
        return 0.0
    return GTCM_ASYM_A * float(motionSpd) ** GTCM_ASYM_B


def _gtcmProfile(r, vmax, a, rm, ri, x1, x2):
    """Symmetric modified Rankine tangential wind.  Users Guide eq. (3).

        V = (Vm-a)(r/rm)            r  < rm
            (Vm-a)(rm/r)**x1        rm <= r < ri
            A(Vm-a)(rm/r)**x2       ri <= r          A = (ri/rm)**x1 (rm/ri)**x2

    A makes V continuous across ri.  Two exponents, not one: the inner and
    outer parts of a real vortex do not share a decay rate, and forcing them
    to was the single biggest error in the pre-guide reconstruction of this.
    """
    vs = max(float(vmax) - float(a), 0.0)
    rm = max(float(rm), 1e-3)
    ri = max(float(ri), rm * 1.0001)
    safe = np.maximum(np.asarray(r, dtype=float), 1e-6)
    # A exists solely to make V continuous across ri, which the Users Guide
    # states in words. Continuity requires
    #     (rm/ri)**x1 == A * (rm/ri)**x2   ->   A = (rm/ri)**(x1 - x2)
    # The guide PRINTS A = (ri/rm)**x1 (rm/ri)**x2, which does not satisfy
    # that except in the degenerate x1 == x2 case - it is a typo, or a
    # superscript mangled in the PDF. Transcribing it literally left a mean
    # +4.4 kt step at ri (max +44 kt) and made the GTCM field measurably
    # rougher than the per-quadrant construction it replaced, which is the
    # opposite of the reason for the switch. Caught by the coherence check
    # in tests/tcwind_jtwc/verify_gtcm.py; see its radial-value-jump column.
    A = (rm / ri) ** (x1 - x2)
    return np.where(safe < rm, vs * (safe / rm),
                    np.where(safe < ri,
                             vs * (rm / safe) ** x1,
                             A * vs * (rm / safe) ** x2))


def _gtcmUV(V, azDeg, ax, ay, lat):
    """2-D wind from tangential wind plus asymmetry.  Users Guide eq. (8)/(9).

    The guide writes u = ax - V sin(theta), v = ay + V cos(theta) with theta
    measured counterclockwise from east.  This file carries azimuth as a
    compass bearing from the centre, and theta = 90 - bearing, so sin(theta)
    becomes cos(bearing) and cos(theta) becomes sin(bearing).

    The guide is NHC's, so it only ever describes the northern hemisphere.
    JTWC warns on southern-hemisphere basins too, where the tangential flow
    reverses; `sign` handles that.  The asymmetry vector is not reversed - it
    still points with the motion.
    """
    azr = np.radians(np.asarray(azDeg, dtype=float))
    sign = 1.0 if lat >= 0 else -1.0
    u = ax - sign * V * np.cos(azr)
    v = ay + sign * V * np.sin(azr)
    return u, v


def _gtcmTargets(snapshot):
    """Fit points: (radius_nm, bearing_deg, threshold_kt, weight).

    Reported radii are the maximum extent in the quadrant; the vortex is fit
    to the quadrant average, so each radius is scaled by GTCM_QUAD_AVG_FACTOR
    first.  Weights follow eq. (7): five on the 34 kt points, one elsewhere.
    """
    out = []
    for threshold in (64, 50, 34):
        quad = snapshot.radii.get(threshold)
        if not quad or snapshot.vmax < threshold:
            continue
        for q in QUADS:
            rep = quad.get(q, 0.0)
            if rep and rep > 0.0:
                out.append((float(rep) * GTCM_QUAD_AVG_FACTOR, QUAD_AZ[q],
                            float(threshold),
                            GTCM_W_34 if threshold == 34 else GTCM_W_INNER))
    return out


def _nelderMead(fn, guess, step, maxIter):
    """Small Nelder-Mead, so the fit needs no scipy inside AWIPS."""
    n = len(guess)
    simplex = [list(guess)]
    for i in range(n):
        pt = list(guess)
        pt[i] += step[i]
        simplex.append(pt)
    vals = [fn(p) for p in simplex]
    for _ in range(maxIter):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        simplex = [simplex[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) <= 1e-9 * (abs(vals[0]) + 1e-9):
            break
        centroid = [sum(p[i] for p in simplex[:-1]) / n for i in range(n)]
        refl = [centroid[i] + (centroid[i] - simplex[-1][i]) for i in range(n)]
        fr = fn(refl)
        if fr < vals[0]:
            exp = [centroid[i] + 2.0 * (centroid[i] - simplex[-1][i])
                   for i in range(n)]
            fe = fn(exp)
            simplex[-1], vals[-1] = (exp, fe) if fe < fr else (refl, fr)
        elif fr < vals[-2]:
            simplex[-1], vals[-1] = refl, fr
        else:
            con = [centroid[i] + 0.5 * (simplex[-1][i] - centroid[i])
                   for i in range(n)]
            fc = fn(con)
            if fc < vals[-1]:
                simplex[-1], vals[-1] = con, fc
            else:
                for i in range(1, n + 1):
                    simplex[i] = [simplex[0][j] + 0.5 * (simplex[i][j] - simplex[0][j])
                                  for j in range(n)]
                    vals[i] = fn(simplex[i])
    best = min(range(n + 1), key=lambda i: vals[i])
    return simplex[best], vals[best]


def fitGTCM(snapshot):
    """Fit the GTCM vortex to one storm-time.

    Returns dict(rm, ri, x1, x2, ax, ay, a, n, rms).  Users Guide steps 2b-3:
    climatological first guess from (5)/(6); ri at the median reported radius;
    (rm, x1, x2) by weighted least squares on WIND error (7); then ax/ay
    released within GTCM_ASYM_MAX_DEV_KT with the size parameters held fixed.
    """
    vmax = float(snapshot.vmax)
    lat = float(snapshot.lat)
    a = _gtcmAsymmetry(snapshot.motionSpd)
    motionDir = snapshot.motionDir if snapshot.motionDir is not None else 0.0
    mr = np.radians(motionDir)
    ax0, ay0 = a * np.sin(mr), a * np.cos(mr)   # eq. (1)

    rmc = _gtcmClimoRmax(vmax, lat)
    xc = _gtcmClimoX(vmax, lat)

    targets = _gtcmTargets(snapshot)
    if not targets:
        # No radii anywhere: climatology is all there is.  Guide step 2c.
        return dict(rm=rmc, ri=rmc * 3.0, x1=xc, x2=xc,
                    ax=float(ax0), ay=float(ay0), a=a, n=0, rms=float("nan"))

    rr = np.array([t[0] for t in targets])
    az = np.array([t[1] for t in targets])
    vt = np.array([t[2] for t in targets])
    wt = np.array([t[3] for t in targets])
    ri = float(np.median(rr))

    def err(rm, x1, x2, ax, ay):
        V = _gtcmProfile(rr, vmax, a, rm, ri, x1, x2)
        u, v = _gtcmUV(V, az, ax, ay, lat)
        return float(np.sum(wt * (np.sqrt(u * u + v * v) - vt) ** 2))

    def sizeObj(p):
        rm, x1, x2 = p
        if rm < 2.0 or rm > 150.0 or not (0.05 <= x1 <= 2.0) or not (0.05 <= x2 <= 2.0):
            return 1e12
        return err(rm, x1, x2, ax0, ay0)

    (rm, x1, x2), _ = _nelderMead(sizeObj, [rmc, xc, xc],
                                  [max(rmc * 0.35, 4.0), 0.12, 0.12],
                                  GTCM_MAX_ITER)

    # Step 3: release the asymmetry, size parameters fixed.
    best = (err(rm, x1, x2, ax0, ay0), float(ax0), float(ay0))
    if a > 0.0:
        grid = np.linspace(-GTCM_ASYM_MAX_DEV_KT, GTCM_ASYM_MAX_DEV_KT,
                           GTCM_ASYM_STEPS)
        for dx in grid:
            for dy in grid:
                e = err(rm, x1, x2, ax0 + dx, ay0 + dy)
                if e < best[0]:
                    best = (e, float(ax0 + dx), float(ay0 + dy))
        def asymObj(p):
            dx, dy = p[0] - ax0, p[1] - ay0
            if dx * dx + dy * dy > GTCM_ASYM_MAX_DEV_KT ** 2:
                return 1e12
            return err(rm, x1, x2, p[0], p[1])
        (axf, ayf), ef = _nelderMead(asymObj, [best[1], best[2]], [2.0, 2.0], 80)
        if ef < best[0]:
            best = (ef, float(axf), float(ayf))

    return dict(rm=float(rm), ri=ri, x1=float(x1), x2=float(x2),
                ax=best[1], ay=best[2], a=a, n=len(targets),
                rms=float(np.sqrt(best[0] / np.sum(wt))))


def _buildVortexGTCM(latGrid, lonGrid, snapshot, rmax_nm, outerDecayFactor,
                     normalizePeak):
    """GTCM field for one time.  Users Guide eq. (3), (8), (9).

    Two deliberate departures from the guide, both documented rather than
    silent:

      * The guide's grids are missing outside the 34 kt radii and NHC leaves
        the blend to the receiving office.  This tool inserts into a
        background instead, so the profile is tapered exponentially beyond
        the modelled 34 kt radius, as the "perquad" construction does.  A bare
        Rankine tail decays too slowly to terminate on its own.
      * Step 4's boundary-layer/land-roughness reduction is NOT implemented.
        It needs the USGS land-surface database, which this procedure does not
        have.  The field is therefore marine-exposure everywhere, and will be
        too strong over land.
    """
    r, az = _distBearingGrids(latGrid, lonGrid, snapshot.lat, snapshot.lon)
    fit = fitGTCM(snapshot)

    V = _gtcmProfile(r, snapshot.vmax, fit["a"], fit["rm"], fit["ri"],
                     fit["x1"], fit["x2"])
    u, v = _gtcmUV(V, az, fit["ax"], fit["ay"], snapshot.lat)
    mag = np.sqrt(u * u + v * v)

    # Modelled 34 kt radius per azimuth, for the insert footprint and taper.
    probe = np.linspace(1.0, 900.0, 900)
    prof = _gtcmProfile(probe, snapshot.vmax, fit["a"], fit["rm"], fit["ri"],
                        fit["x1"], fit["x2"])
    uu, vv = _gtcmUV(prof[None, :], np.asarray(az).ravel()[:, None],
                     fit["ax"], fit["ay"], snapshot.lat)
    prof2d = np.sqrt(uu * uu + vv * vv)
    # The OUTERMOST radius still at 34 kt.  Not the first crossing: the profile
    # is also below 34 kt inside the eye, and taking that would collapse the
    # footprint onto the centre and taper the entire field away.
    above = prof2d >= 34.0
    anyAbove = above.any(axis=1)
    last = prof2d.shape[1] - 1 - np.argmax(above[:, ::-1], axis=1)

    # Interpolate the crossing rather than snapping to the probe grid.  probe[last]
    # is the last sample still AT or ABOVE 34 kt, so the field there is >= 34 while
    # the taper below restarts at exactly 34 - the difference lands as a step at the
    # footprint boundary.  On a 1 nm probe that was a 3.36 kt mean jump, which made
    # this taper the largest single source of roughness in the GTCM field, larger
    # than anything in the vortex itself.  Solving for the exact radius where the
    # field equals 34 makes the boundary continuous by construction.
    rows = np.arange(prof2d.shape[0])
    nxt = np.minimum(last + 1, prof2d.shape[1] - 1)
    v_hi = prof2d[rows, last]
    v_lo = prof2d[rows, nxt]
    span = v_hi - v_lo
    frac = np.where(span > 1e-9, (v_hi - 34.0) / np.maximum(span, 1e-9), 0.0)
    frac = np.clip(frac, 0.0, 1.0)
    r34_exact = probe[last] + frac * (probe[nxt] - probe[last])

    r34 = np.where(anyAbove, r34_exact, fit["rm"] * 3.0)
    r34 = r34.reshape(r.shape).astype(np.float32)

    # Anchor the taper on the field's OWN value at r34, not on a constant 34.
    # Where the field does reach 34 kt these are the same number, because r34
    # is solved as the radius where it does.  Where it never reaches 34 - a
    # weak system, or a quadrant of a marginal one where the asymmetry vector
    # opposes the flow after the Vm-a reduction - r34 falls back to 3*rm, and
    # anchoring on 34 there made the field jump UP at that radius: a 30 kt
    # system came out with its peak of 34 kt sitting 113 nm from the centre
    # instead of in its core.  Evaluating the profile at r34 handles both
    # branches with one expression.
    az1d = np.asarray(az).ravel()
    r341d = np.asarray(r34).ravel()
    Vanchor = _gtcmProfile(r341d, snapshot.vmax, fit["a"], fit["rm"],
                           fit["ri"], fit["x1"], fit["x2"])
    ua, va = _gtcmUV(Vanchor, az1d, fit["ax"], fit["ay"], snapshot.lat)
    anchorV = np.sqrt(ua * ua + va * va).reshape(r.shape)

    decayL = np.maximum(r34 * float(outerDecayFactor), MIN_OUTER_DECAY_NM)
    outer = r > r34
    mag = np.where(outer, anchorV * np.exp(-(r - r34) / decayL), mag)

    if GTCM_APPLY_INFLOW:
        sign = 1.0 if snapshot.lat >= 0 else -1.0
        metFrom = (az + sign * (90.0 - INFLOW_ANGLE_DEG)) % 360.0
        rad = np.radians(metFrom)
        u, v = -mag * np.sin(rad), -mag * np.cos(rad)
    else:
        scale = np.where(mag > 0, mag / np.maximum(np.sqrt(u * u + v * v), 1e-6), 0.0)
        u, v = u * scale, v * scale

    dirOut = (np.degrees(np.arctan2(-u, -v))) % 360.0

    if normalizePeak and snapshot.vmax > 0:
        weight = np.clip((fit["rm"] - r) / max(fit["rm"], 1e-3), 0.0, 1.0)
        core = weight > 0.0
        if core.any():
            i = int(np.argmax(np.where(core, mag, -1.0)))
            peak, w0 = float(mag.flat[i]), float(weight.flat[i])
            if peak > 0.0 and w0 > 0.05 and peak < snapshot.vmax:
                factor = min(1.0 + (snapshot.vmax / peak - 1.0) / w0,
                             PEAK_NORMALIZE_MAX_FACTOR)
                mag = mag * (1.0 + (factor - 1.0) * weight)

    return (mag.astype(np.float32), dirOut.astype(np.float32), r, r34)



def buildVortex(latGrid, lonGrid, snapshot, rmax_nm,
                asymFrac=MOTION_ASYMMETRY_FRACTION,
                inflowDeg=INFLOW_ANGLE_DEG,
                outerDecayFactor=OUTER_DECAY_FACTOR,
                normalizePeak=NORMALIZE_CORE_PEAK,
                method=None):
    """Return (magGrid_kt, dirGrid_deg, r_nm, r34_nm) for one time."""
    if (method or VORTEX_METHOD) == "gtcm":
        return _buildVortexGTCM(latGrid, lonGrid, snapshot, rmax_nm,
                                outerDecayFactor, normalizePeak)
    # A reported quadrant radius already IS this storm's real asymmetry -
    # translation-driven or otherwise (shear, extratropical transition,
    # ...) - so adding the synthetic motion vector below on top of it is
    # double counting, not reinforcement. Confirmed against NHC's own
    # Gridded TCM (WTCM/GTCM) Users Guide: WTCM never independently shapes
    # a per-quadrant vortex from the radii and then ALSO adds a motion
    # vector - it has exactly one asymmetry mechanism. It fits a single
    # SYMMETRIC modified-Rankine vortex (Rappin et al. 2013) plus one
    # wavenumber-1 motion term (Schwerdt 1979: a = 1.6*c^0.63, c = storm
    # speed in kt) by least-squares against ALL the reported radii
    # together (eq. 7 in the guide), not fit per quadrant the way this
    # function's knot_r construction above is. (Its legacy predecessor,
    # TCMWindTool, instead did what this function does - a per-quadrant
    # radial fit, tangentially interpolated between quadrants - but with
    # no separate motion vector either; WTCM replaced it rather than
    # adding the motion term on top of it.) Skip the motion term whenever
    # there is anything to be asymmetric about already; keep it as a
    # shaping fallback for the radii-less case (weak/developing systems
    # where only Vmax is known), so those aren't left perfectly circular.
    if snapshot.radii:
        asymFrac = 0.0

    r, az = _distBearingGrids(latGrid, lonGrid, snapshot.lat, snapshot.lon)

    floor = rmax_nm * 1.05

    # Assemble the profile knots from strongest to weakest, keeping only the
    # thresholds the storm actually reaches.
    knot_r = [np.full(r.shape, rmax_nm, dtype=np.float32)]
    knot_v = [snapshot.vmax]
    prev = knot_r[0]

    # WTCM also subtracts the asymmetry magnitude from Vm inside the vortex
    # itself (V = (Vm-a)*(...)) specifically so the vortex peak plus the
    # vector added back in below sum to Vm, not Vm+a. Mirror that here:
    # reduce the core/peak reference speed (knot_v[0], which the solid body
    # and outer-taper formulas both key off) by the largest contribution
    # the vector below can make, before adding that vector back in.
    # knot_v only ever holds this single knot whenever asymFrac is nonzero
    # here - radii present forces asymFrac to 0 above, and only the
    # radii-less case ever reaches this - so nothing else in knot_v needs
    # touching, and this is a no-op whenever it doesn't apply.
    if asymFrac and snapshot.motionSpd:
        knot_v[0] = max(snapshot.vmax - asymFrac * snapshot.motionSpd, 0.0)
    for threshold in (64, 50, 34):
        if threshold not in snapshot.radii:
            continue
        # See the matching comment in resolveRmax(): vmax < threshold, not
        # <=, so a storm whose peak exactly equals a reported ring's
        # threshold (a 50kt storm reporting R50, say - not rare, since
        # JTWC rounds Vmax to 5kt bins) still gets that ring built into its
        # profile instead of the knot list jumping straight past it to the
        # next-weaker ring.
        if snapshot.vmax < threshold:
            continue
        rr = _azimuthalRadii(az, snapshot.radii[threshold], floor)
        rr = np.maximum(rr, prev * 1.02)      # enforce monotonicity
        knot_r.append(rr)
        knot_v.append(float(threshold))
        prev = rr

    mag = np.zeros(r.shape, dtype=np.float32)
    safe_r = np.maximum(r, 1e-3)

    # Solid-body rotation inside the core.
    inner = r <= knot_r[0]
    mag = np.where(inner, knot_v[0] * (safe_r / np.maximum(knot_r[0], 1e-3)),
                   mag)

    # Piecewise modified-Rankine between consecutive knots.  A single global
    # exponent cannot pass through all three rings, so each segment gets its
    # own.
    for i in range(len(knot_r) - 1):
        r1, v1 = knot_r[i], knot_v[i]
        r2, v2 = knot_r[i + 1], knot_v[i + 1]
        ratio = np.maximum(r2 / np.maximum(r1, 1e-3), 1.0001)
        # x solves v1*(r1/r2)^x = v2 exactly, so the profile passes through
        # the reported radius/threshold at r2 by construction - that
        # boundary match is the entire point of solving for x per segment
        # instead of using one global exponent. Floor at 0.0, not some
        # higher value like the 0.05 this used to have: a storm whose Vmax
        # barely clears the next ring's threshold (a common case - e.g.
        # 35kt Vmax vs. a 34kt ring, or 65kt vs. 64kt) combined with a wide
        # ratio (a large reported radius relative to Rmax, equally common)
        # naturally needs a very shallow exponent to cover that distance on
        # only a 1kt drop. A higher floor overrides that with an
        # unrelated, steeper minimum decay rate, which breaks the boundary
        # match: verified on a real bulletin (35kt TS, Rmax 36.5nm, R34
        # 120nm reported in one quadrant) that the 0.05 floor made the
        # modeled field fall under 34kt by ~65nm instead of the reported
        # 120nm - a 46% shortfall the tool's own "fit check" against a
        # sample of reported points can miss, since it only ever tests
        # exactly at the reported radius (where, per this same bug, a
        # sample landing there could tip into the next segment or the
        # outer taper on floating-point noise and read correctly by
        # accident - see compare_py_js.py's "Known benign residual").
        # v1 < v2 is unreachable (every segment is built strictly weaker
        # than the last); v1 == v2 (the exact-threshold case above) is
        # naturally x=0 here already, with no special-casing needed.
        x = np.log(v1 / v2) / np.log(ratio)
        x = np.clip(x, 0.0, 2.5)
        seg = (r > r1) & (r <= r2)
        mag = np.where(seg,
                       v1 * (np.maximum(r1, 1e-3) / safe_r) ** x,
                       mag)

    # Outside the outermost ring the bulletin gives no information.  The
    # inner power law is the wrong thing to extrapolate: the R50-to-R34 slope
    # describes the core-to-gale transition, and continuing it leaves 20 kt
    # winds several hundred miles out.  Taper exponentially instead, anchored
    # on the outermost ring.
    anchorR = knot_r[-1]
    anchorV = knot_v[-1]
    decayL = np.maximum(anchorR * float(outerDecayFactor), MIN_OUTER_DECAY_NM)

    outer = r > anchorR
    mag = np.where(outer,
                   anchorV * np.exp(-(r - anchorR) / decayL),
                   mag)

    # Cyclonic tangential flow with inflow.  Southern hemisphere reverses.
    sign = 1.0 if snapshot.lat >= 0 else -1.0
    metFrom = (az + sign * (90.0 - inflowDeg)) % 360.0

    rad = np.radians(metFrom)
    u = -mag * np.sin(rad)
    v = -mag * np.cos(rad)

    # Storm-motion asymmetry, strongest near the core.
    if snapshot.motionSpd:
        # knot_v[0], not snapshot.vmax: the same reduced core reference
        # used to cap mag above, so frac still reaches its ceiling
        # (asymFrac) exactly at the peak - see the knot_v[0] reduction
        # comment above.
        frac = asymFrac * np.clip(mag / max(knot_v[0], 1.0), 0.0, 1.0)

        # asymFrac above is forced to 0 across the whole anchored band
        # (Rmax through the outermost reported ring) whenever any radius
        # was reported, to avoid double-counting that ring's own real
        # asymmetry. But Rmax itself is never a reported value - JTWC
        # has no per-quadrant RMW - so strictly inside it (r <= Rmax)
        # there is nothing to double-count. Give that zone its own,
        # always-on vector, using the same MOTION_ASYMMETRY_FRACTION
        # already vetted for the radii-less case above (not a new,
        # separately-tuned number). Ramped to exactly 0 at the dead
        # center (r=0, no direction to speak of there) and at Rmax's own
        # boundary (continuous with the anchored band's forced 0 just
        # outside it, so this introduces no seam at the ring itself).
        # normalizePeak() below already runs unconditionally and never
        # touches cells at or beyond the first REPORTED ring, so it
        # recovers the exact Vmax peak afterward without any separate
        # Vm-a-style correction here.
        #
        # UNLIKE every other correction in this file, this one cannot be
        # checked against IBTrACS: best-track RMW is a single scalar per
        # storm-time, never per-quadrant, so there is no ground truth
        # anywhere in the archive for how Rmax's own wind field actually
        # varies by azimuth. This rests on the same wavenumber-1
        # mechanism already used for the radii-less fallback, not on
        # anything verified here - see tests/tcwind_jtwc/README.md.
        # Left the far-field taper (beyond the outermost ring) alone:
        # it is already its own unverified heuristic (see the comment
        # above the outer-taper block), and stacking a second one on
        # top of it, more cheaply, less usefully (weaker winds, farther
        # from anything operationally decided), was not worth doing.
        if snapshot.radii and MOTION_ASYMMETRY_FRACTION:
            core = np.clip(r / np.maximum(knot_r[0], 1e-3), 0.0, 1.0)
            coreFrac = MOTION_ASYMMETRY_FRACTION * 4.0 * core * (1.0 - core)
            frac = np.where(r <= knot_r[0], coreFrac, frac)

        mrad = np.radians(snapshot.motionDir)
        u = u + frac * snapshot.motionSpd * np.sin(mrad)
        v = v + frac * snapshot.motionSpd * np.cos(mrad)

    magOut = np.sqrt(u * u + v * v)
    dirOut = (np.degrees(np.arctan2(-u, -v))) % 360.0

    # Recover the peak the grid failed to sample.  The weight is 1 at the
    # center and 0 at the innermost reported ring, so nothing outside that
    # ring is touched and the reported radii stay exact.  Solving for the
    # factor at the strongest core cell makes the corrected peak land on
    # Vmax in a single pass.
    if normalizePeak and snapshot.vmax > 0:
        innerR = knot_r[1] if len(knot_r) > 1 else anchorR
        weight = np.clip((innerR - r) / np.maximum(innerR, 1e-3), 0.0, 1.0)
        coreCells = weight > 0.0
        if coreCells.any():
            idx = int(np.argmax(np.where(coreCells, magOut, -1.0)))
            peak = float(magOut.flat[idx])
            w0 = float(weight.flat[idx])
            if peak > 0.0 and w0 > 0.05 and peak < snapshot.vmax:
                factor = 1.0 + (snapshot.vmax / peak - 1.0) / w0
                factor = min(factor, PEAK_NORMALIZE_MAX_FACTOR)
                magOut = magOut * (1.0 + (factor - 1.0) * weight)

    r34 = knot_r[-1] if len(knot_r) > 1 else np.full(r.shape, rmax_nm * 3.0)
    return magOut.astype(np.float32), dirOut.astype(np.float32), r, r34


def magDirToUV(mag, direc):
    rad = np.radians(direc)
    return -mag * np.sin(rad), -mag * np.cos(rad)


def uvToMagDir(u, v):
    mag = np.sqrt(u * u + v * v)
    direc = (np.degrees(np.arctan2(-u, -v))) % 360.0
    return mag, direc


def boxSmooth(grid, factor):
    """Separable box average, as a fallback when the base class has no
    smoothGrid.  Edges are handled by edge padding so the domain border
    does not pull values toward zero."""
    k = max(int(factor), 1)
    if k < 2:
        return grid.astype(np.float32).copy()

    pad = k // 2
    win = 2 * pad + 1
    a = np.pad(grid.astype(np.float64), pad, mode="edge")

    cs = np.cumsum(a, axis=0)
    cs = np.concatenate([np.zeros((1, a.shape[1])), cs], axis=0)
    a = (cs[win:, :] - cs[:-win, :]) / win

    cs = np.cumsum(a, axis=1)
    cs = np.concatenate([np.zeros((a.shape[0], 1)), cs], axis=1)
    a = (cs[:, win:] - cs[:, :-win]) / win

    return a.astype(np.float32)


def _limitRadius(storm):
    return storm["r34"] * max(float(storm.get("limitFactor", 3.0)), 1.0)


def insertStorms(bMag, bDir, storms, capKt=None):
    """Hard-insert one or more warning wind fields over the background.

    No blending.  Inside its R34 each warning wins outright, so the 34, 50
    and 64 kt contours land on JTWC's reported radii.  Between R34 and the
    outer limit a vortex is inserted only where it is stronger than what is
    already there, which puts each seam where the two fields are equal and
    keeps the speed continuous without averaging anything.

    Storms are applied outer-first, then cores, so a core always survives a
    neighbouring storm's tail.  Where two storms genuinely overlap, the
    stronger wind wins rather than the last one processed.

    Each storm is a dict with vMag, vDir, r, r34 and limitFactor.
    Returns (mag, dir, footprint, coreMask).
    """
    mag = bMag.astype(np.float32).copy()
    direc = bDir.astype(np.float32).copy()
    applied = np.zeros(mag.shape, dtype=bool)

    # Everything any storm is allowed to touch, this time step.
    withinAny = np.zeros(mag.shape, dtype=bool)
    for s in storms:
        withinAny |= s["r"] <= _limitRadius(s)

    # Cap the background so a model's own tropical circulation cannot leave
    # a stronger blob just outside a footprint.  Confined to withinAny:
    # applied domain-wide it would flatten every unrelated system.
    if capKt is not None:
        capMask = (mag >= capKt) & withinAny
        mag[capMask] = capKt

    # Outer envelopes: strongest wins.
    for s in storms:
        outer = ((s["r"] > s["r34"])
                 & (s["r"] <= _limitRadius(s))
                 & (s["vMag"] > mag))
        mag = np.where(outer, s["vMag"], mag)
        direc = np.where(outer, s["vDir"], direc)
        applied |= outer

    # Cores override everything, including another storm's tail.
    coreMask = np.zeros(mag.shape, dtype=bool)
    coreBest = np.full(mag.shape, -1.0, dtype=np.float32)
    for s in storms:
        core = s["r"] <= s["r34"]
        take = core & (s["vMag"] > coreBest)
        coreBest = np.where(take, s["vMag"], coreBest)
        mag = np.where(take, s["vMag"], mag)
        direc = np.where(take, s["vDir"], direc)
        coreMask |= core
        applied |= core

    return (mag.astype(np.float32), direc.astype(np.float32),
            applied, coreMask)


def insertVortex(vMag, vDir, bMag, bDir, r, r34, maxRadiusFactor=3.0,
                 capKt=None):
    """Single-storm convenience wrapper around insertStorms."""
    mag, direc, footprint, _core = insertStorms(
        bMag, bDir,
        [{"vMag": vMag, "vDir": vDir, "r": r, "r34": r34,
          "limitFactor": maxRadiusFactor}],
        capKt=capKt)
    return mag, direc, footprint


# ---------------------------------------------------------------------------
# GFE Procedure
# ---------------------------------------------------------------------------

if _IN_GFE:

    class Procedure(SmartScript.SmartScript):

        def __init__(self, dbss):
            SmartScript.SmartScript.__init__(self, dbss)

        # -------------------------------------------------------------
        # Dialog
        # -------------------------------------------------------------

        def _buildVarDict(self):
            pilList = list(JTWC_PILS_WESTPAC)

            # Everything else lives in the tunables block at the top of this
            # file.  None of it is a per-run decision, and two of the old
            # sliders did nothing at most of their range.
            VariableList = []

            if EXPERIMENTAL:
                # Each label must have distinct text: varDict is keyed by it.
                VariableList += [
                    ("*** EXPERIMENTAL TOOL - NOT OPERATIONALLY VETTED ***",
                     "", "label"),
                    ("Wind fields are built from an analytic vortex fit to "
                     "the JTWC wind radii, not from a gridded product.",
                     "", "label"),
                    ("Output has not been verified against observations. "
                     "Review every grid before use in any product.",
                     "", "label"),
                    ("Preview first. Report problems before this is used "
                     "operationally.", "", "label"),
                    (" ", "", "label"),
                ]

            VariableList += [
                ("Bulletins to process:", pilList, "check", pilList),
                ("Write to:", "Preview grid", "radio",
                 ["Preview grid", "Fcst Wind"]),
                ("Run over selected time range only?", "No", "radio",
                 ["Yes", "No"]),
            ]

            if EXPERIMENTAL and REQUIRE_ACKNOWLEDGEMENT:
                VariableList += [
                    ("I understand this tool is experimental and I have "
                     "reviewed the output:", "No", "radio", ["No", "Yes"]),
                ]

            title = "JTWC Tropical Cyclone Wind  (v%s)" % VERSION
            if EXPERIMENTAL:
                title += "  ***  EXPERIMENTAL  ***"

            varDict = {}
            pvl = ProcessVariableList.ProcessVariableList(
                title, VariableList, varDict, None)
            if pvl.status() != "OK":
                return None
            return varDict

        # -------------------------------------------------------------
        # Helpers (self-contained equivalents of the GM_* utilities)
        # -------------------------------------------------------------

        def _retrieveBulletin(self, pil):
            """Bulletin text, preferring the in-process text database.

            Falls back to the command-line textdb, which is the retrieval
            path already in use at OPC for these PILs.  Uses Popen-style
            arguments rather than capture_output/text so it works on the
            older Python in the AWIPS stack.
            """
            try:
                raw = self.getTextProductFromDB(pil)
            except Exception:
                raw = None
            if raw:
                return raw

            for exe in TEXTDB_PATHS:
                try:
                    proc = subprocess.run(
                        [exe, "-r", pil],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=30)
                except (OSError, ValueError, subprocess.SubprocessError):
                    continue
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout
            return None

        @staticmethod
        def _trBounds(tr):
            """Start and end of a time range in unix seconds.

            Handles both the Python TimeRange wrapper and a raw Java
            TimeRange, which turn up depending on which call produced it.
            """
            try:
                return (tr.startTime().unixTime(), tr.endTime().unixTime())
            except AttributeError:
                pass
            try:
                return (tr.getStart().getTime() // 1000,
                        tr.getEnd().getTime() // 1000)
            except AttributeError:
                raise TypeError("Unrecognized time range object: %r" % (tr,))

        def _fcstInventory(self, activeTR):
            """Existing Fcst Wind time ranges overlapping activeTR.

            getWEInventory belongs to TropicalUtility, not SmartScript, so
            the SmartScript path is getGridInfo.  Both are tried, since a
            site may have a base class that provides either.
            """
            inv = []

            try:
                infos = self.getGridInfo("Fcst", "Wind", "SFC", activeTR)
            except Exception:
                infos = None

            if infos:
                for info in infos:
                    try:
                        inv.append(info.gridTime())
                    except AttributeError:
                        inv.append(info)

            if not inv and hasattr(self, "getWEInventory"):
                try:
                    inv = list(
                        self.getWEInventory("Fcst", "Wind", "SFC", activeTR))
                except TypeError:
                    inv = list(self.getWEInventory("Fcst", "Wind", "SFC"))
                except Exception:
                    inv = []

            lo, hi = self._trBounds(activeTR)
            out = []
            for tr in inv:
                try:
                    start, end = self._trBounds(tr)
                except TypeError:
                    continue
                if end <= lo or start >= hi:
                    continue
                out.append(tr)

            out.sort(key=lambda t: self._trBounds(t)[0])
            return out

        def _smooth(self, grid, factor):
            """smoothGrid if the base class has it, box average otherwise."""
            if hasattr(self, "smoothGrid"):
                try:
                    return self.smoothGrid(grid, int(factor))
                except Exception:
                    pass
            return boxSmooth(grid, factor)

        def _fragment(self, activeTR):
            """Fragment Fcst Wind so partial blocks can be written."""
            if not hasattr(self, "fragmentCmd"):
                return
            try:
                self.fragmentCmd(["Wind"], activeTR)
            except Exception as exc:
                self.statusBarMsg(
                    "fragmentCmd failed (%s); writing to existing blocks "
                    "as they stand." % exc, "S")

        def _storeGrid(self, element, data, tr, temporary):
            """Write a vector grid, creating a temporary parm if previewing.

            GFE builds a temporary weather element on demand when createGrid
            names one that is not in the configuration, provided the parm
            metadata is supplied.  Older signatures reject those keywords, so
            fall back to the plain call.
            """
            if temporary:
                try:
                    self.createGrid(
                        "Fcst", element, "VECTOR", data, tr,
                        descriptiveName="JTWC TC Wind (preview)",
                        precision=0, minAllowedValue=0.0,
                        maxAllowedValue=PREVIEW_MAX_KT, units="kts")
                    return
                except TypeError:
                    pass
            self.createGrid("Fcst", element, "VECTOR", data, tr)

        def _seamMask(self, footprint, coreMask, factor):
            """Ring straddling the edge of the inserted region.

            Same construction GTCM uses: smooth a 0/1 footprint and keep the
            values strictly between.  Every storm's core is excluded, so the
            smoother can never touch a wind field the warnings specify.
            """
            fp = np.zeros(footprint.shape, dtype=np.float32)
            fp[footprint] = 1.0
            smoothed = self._smooth(fp, int(factor))
            return (smoothed < 1.0) & (smoothed > 0.0) & (~coreMask)

        # -------------------------------------------------------------
        # Main
        # -------------------------------------------------------------

        def execute(self, editArea, timeRange, varDict):
            # editArea is accepted because GFE passes it, and ignored.

            if varDict is None:
                varDict = self._buildVarDict()
                if varDict is None:
                    return

            pils = list(varDict.get("Bulletins to process:") or [])

            if not pils:
                self.statusBarMsg("No bulletins selected.", "S")
                return

            preview = varDict.get("Write to:", "Preview grid") == "Preview grid"

            # Writing to Fcst needs an explicit acknowledgement while the
            # tool is experimental.  Preview runs never do, so nothing stops
            # a forecaster from evaluating it.
            if not preview and EXPERIMENTAL and REQUIRE_ACKNOWLEDGEMENT:
                ack = varDict.get(
                    "I understand this tool is experimental and I have "
                    "reviewed the output:", "No")
                if ack != "Yes":
                    self.statusBarMsg(
                        "This tool is experimental and has not been "
                        "operationally vetted. Run it to the preview grid "
                        "and review the output, then acknowledge in the "
                        "dialog to write to Fcst Wind.", "S")
                    return

            targetElement = PREVIEW_ELEMENT if preview else "Wind"

            selectedTimeOnly = \
                varDict["Run over selected time range only?"] == "Yes"

            capKt = BACKGROUND_CAP_KT

            # No edit area is needed or used.  The bulletins define their own
            # regions of influence and the footprints are what limit the
            # edit, so an unhatched domain is the normal case.

            # --- time range ------------------------------------------
            nowSecs = self._gmtime().unixTime()
            if selectedTimeOnly:
                if timeRange.duration() < 3600:
                    self.statusBarMsg(
                        "You selected to run over selected time range only "
                        "but none was selected.", "S")
                    return
                activeTR = timeRange
            else:
                utcHr = self._gmtime().timetuple().tm_hour
                activeTR = self.createTimeRange(utcHr - 6, utcHr + 175, "Zulu")

            # --- collect every bulletin with a live storm in it -------
            storms = []
            stale = []
            problems = []
            for pil in pils:
                raw = self._retrieveBulletin(pil)
                if not raw:
                    continue          # empty slot, entirely normal
                try:
                    taus, header = parseJTWC(raw)
                except Exception as exc:
                    problems.append("%s: %s" % (pil, exc))
                    continue
                if len(taus) < 2:
                    problems.append("%s: only %d usable forecast times"
                                    % (pil, len(taus)))
                    continue

                # textdb hands back whatever was last stored under this PIL,
                # so a dissipated storm sits there indefinitely.  Judge the
                # slot by the bulletin's own analysis time.
                ageHours = (nowSecs - taus[0].epoch) / 3600.0
                if ageHours > MAX_BULLETIN_AGE_HOURS:
                    stale.append("%s %s is %.0f h old"
                                 % (pil, describeStorm(header), ageHours))
                    continue
                if taus[-1].epoch <= nowSecs:
                    stale.append("%s %s forecast period has ended"
                                 % (pil, describeStorm(header)))
                    continue

                storms.append({"pil": pil, "taus": taus, "header": header})

            if not storms:
                msg = "No live bulletins found in %s." % ", ".join(pils)
                if stale:
                    msg += " Stale: " + "; ".join(stale) + "."
                if problems:
                    msg += " Problems: " + "; ".join(problems) + "."
                self.statusBarMsg(msg, "S")
                return

            # Run the full length of the bulletins, whatever that is.  JTWC
            # products carry 96 or 120 hour groups depending on the system,
            # and each storm gets its own span.
            spanStart = min(s["taus"][0].epoch for s in storms)
            spanEnd = max(s["taus"][-1].epoch for s in storms)

            fcstTRList = self._fcstInventory(activeTR)
            if not fcstTRList:
                self.statusBarMsg(
                    "No existing Fcst Wind grids in the active time range. "
                    "Populate Wind from a model first.", "S")
                return

            # Fragment so partially overlapping blocks can be written.  A
            # preview run must not touch Fcst at all, and fragmenting would
            # rewrite its inventory, so it is skipped.
            if not preview:
                self._fragment(activeTR)
                fcstTRList = self._fcstInventory(activeTR)

            latGrid, lonGrid = self.getLatLonGrids()

            # A grid block is valid from its start time onward, so a
            # forecast time populates the block that BEGINS at it.  Every
            # block is evaluated at its own start; blocks between two
            # forecast times interpolate to their start.  This means a tau
            # landing on a block start is hit exactly, which is how the
            # forecast peak reaches the grid.
            blockBounds = [self._trBounds(tr) for tr in fcstTRList]
            blockStarts = set(a for a, _b in blockBounds)

            durations = [b - a for a, b in blockBounds]
            if durations:
                blockDur = max(set(durations), key=durations.count)
            else:
                blockDur = 3600

            written = 0
            skippedST = 0
            skippedTD = 0
            contributed = {}
            peakWritten = 0.0
            bulletinPeak = max(t.vmax for s in storms for t in s["taus"])

            def buildFor(when, tr):
                """Storm fields valid at `when`, for the block `tr`."""
                out = []
                tdSkipped = 0
                for s in storms:
                    taus = s["taus"]
                    if when < taus[0].epoch or when > taus[-1].epoch:
                        continue
                    snap = interpolateTrack(taus, when)
                    if not INSERT_AFTER_SUBTROPICAL and snap.conf < 1.0:
                        return None, True, 0
                    if snap.vmax < 34.0:
                        # Tropical Depression strength: no organized 34kt-
                        # or-greater wind field to speak of, and - per
                        # JTWC's own reporting practice - essentially
                        # never any wind radii to build one from even if
                        # there were. This tool's parametric vortex is
                        # built to represent an organized TC circulation;
                        # inserting it over the background model's own
                        # winds here would invent structure that isn't
                        # really there, not add real information. Leave
                        # the background untouched for this storm at this
                        # time - any other, stronger storm in the same
                        # bulletin is unaffected.
                        tdSkipped += 1
                        continue
                    rmax = resolveRmax(snap, RMAX_OVERRIDE_NM)
                    vMag, vDir, r, r34 = buildVortex(
                        latGrid, lonGrid, snap, rmax,
                        asymFrac=MOTION_ASYMMETRY_FRACTION,
                        inflowDeg=INFLOW_ANGLE_DEG,
                        outerDecayFactor=OUTER_DECAY_FACTOR)
                    if WIND_AVERAGING_FACTOR != 1.0:
                        vMag = vMag * WIND_AVERAGING_FACTOR
                    out.append({"vMag": vMag, "vDir": vDir, "r": r,
                                "r34": r34,
                                "limitFactor": MAX_INSERT_RADIUS_FACTOR})
                    contributed[s["pil"]] = contributed.get(s["pil"], 0) + 1
                return out, False, tdSkipped

            def writeBlock(tr, built):
                """Insert `built` over the background and store the grid."""
                bkg = self.getGrids("Fcst", "Wind", "SFC", tr,
                                    mode="First", noDataError=0)
                if bkg is None:
                    shape = latGrid.shape
                    bMag = np.zeros(shape, dtype=np.float32)
                    bDir = np.zeros(shape, dtype=np.float32)
                else:
                    bMag, bDir = bkg[0], bkg[1]

                mag, direc, footprint, coreMask = insertStorms(
                    bMag, bDir, built, capKt=BACKGROUND_CAP_KT)
                if not footprint.any():
                    return 0.0

                if SMOOTH_SEAM and int(SMOOTH_FACTOR) > 1:
                    ring = self._seamMask(footprint, coreMask, SMOOTH_FACTOR)
                    if ring.any():
                        u, v = magDirToUV(mag, direc)
                        us = self._smooth(u, int(SMOOTH_FACTOR))
                        vs = self._smooth(v, int(SMOOTH_FACTOR))
                        u[ring] = us[ring]
                        v[ring] = vs[ring]
                        mag, direc = uvToMagDir(u, v)

                self._storeGrid(targetElement,
                                (mag.astype(np.float32),
                                 direc.astype(np.float32)), tr, preview)
                return float(mag[footprint].max())

            for tr in fcstTRList:
                trStart, _trEnd = self._trBounds(tr)
                if trStart < spanStart or trStart > spanEnd:
                    continue

                built, stFlag, tdCount = buildFor(trStart, tr)
                skippedTD += tdCount
                if stFlag:
                    skippedST += 1
                    continue
                if not built:
                    continue

                peak = writeBlock(tr, built)
                if peak:
                    peakWritten = max(peakWritten, peak)
                    written += 1

            # A forecast time with no block beginning at it gets one created,
            # so the last group of a bulletin is never lost just because the
            # Fcst inventory happened to stop there.
            created = []
            unplaced = []
            if CREATE_MISSING_TAU_BLOCKS:
                wanted = sorted(set(
                    x.epoch for s in storms for x in s["taus"]
                    if x.epoch not in blockStarts))
                for when in wanted:
                    built, stFlag = buildFor(when, None)
                    if stFlag or not built:
                        continue
                    try:
                        tr = TimeRange.TimeRange(
                            AbsTime.AbsTime(int(when)),
                            AbsTime.AbsTime(int(when + blockDur)))
                        peak = writeBlock(tr, built)
                    except Exception as exc:
                        unplaced.append("%s (%s)" % (
                            time.strftime("%d/%H%MZ", time.gmtime(when)), exc))
                        continue
                    if peak:
                        peakWritten = max(peakWritten, peak)
                        written += 1
                        created.append(
                            time.strftime("%d/%H%MZ", time.gmtime(when)))

            if not written:
                self.statusBarMsg(
                    "Parsed %d live bulletin(s), but no Fcst Wind grids fell "
                    "inside their valid periods." % len(storms), "S")
                return

            parts = []
            for s in storms:
                count = contributed.get(s["pil"], 0)
                if not count:
                    continue
                parts.append("%s %s (%d)"
                             % (s["pil"], describeStorm(s["header"]), count))

            where = "%s preview grids" % PREVIEW_ELEMENT if preview \
                else "Fcst Wind grids"
            msg = "v%s. " % VERSION
            if EXPERIMENTAL:
                msg += "EXPERIMENTAL, verify before use. "
            msg += "Updated %d %s. " % (written, where) + "; ".join(parts) + "."
            msg += " Peak wind written %.0f kt vs bulletin max %.0f kt." % (
                peakWritten, bulletinPeak)
            if created:
                msg += " Created blocks at " + ", ".join(created) + "."
            if unplaced:
                msg += " Could not create a block at " + \
                       "; ".join(unplaced) + "."
            if skippedST:
                msg += " Skipped %d storm-times after subtropical " \
                       "transition." % skippedST
            if skippedTD:
                msg += " Skipped %d storm-times below tropical storm " \
                       "strength (no 34kt wind)." % skippedTD
            if stale:
                msg += " Skipped stale: " + "; ".join(stale) + "."
            if problems:
                msg += " Problems: " + "; ".join(problems) + "."
            self.statusBarMsg(msg, "R")


# ---------------------------------------------------------------------------
# Standalone parser test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python TCWind_JTWC.py <bulletin.txt>")
        sys.exit(1)

    with open(sys.argv[1]) as fh:
        text = fh.read()

    taus, header = parseJTWC(text)
    print("system: %s" % describeStorm(header))
    if header.get("pressureMb"):
        print("min central pressure: %d mb" % header["pressureMb"])
    print("reference date (dd, mm, yyyy): %s" % (header["refDate"],))
    print("")
    for t in taus:
        snap = interpolateTrack(taus, t.epoch)
        rmax = resolveRmax(snap)
        auto = willoughbyRmax(t.vmax, t.lat)
        print("tau %02dh  %6.1f %7.1f  vmax %3.0f kt  motion %03.0f/%02.0f  "
              "conf %.2f" % (t.tau, t.lat, t.lon, t.vmax,
                             t.motionDir or 0, t.motionSpd or 0, t.conf))
        print("          Rmax: regression %5.1f nm -> used %5.1f nm" %
              (auto, rmax))
        for threshold in (64, 50, 34):
            if threshold in t.radii:
                q = t.radii[threshold]
                print("          R%02d: NE %3.0f  SE %3.0f  SW %3.0f  NW %3.0f"
                      % (threshold, q["NE"], q["SE"], q["SW"], q["NW"]))
        print("")
