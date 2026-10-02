# ----------------------------------------------------------------------------
# TCWind_JTWC.py
#
# GFE Procedure: build Wind grids from tropical cyclone forecast text in the
# AWIPS text database.  Four basins, two product formats, one wind field.
#
#   Atlantic     NHC  TCM forecast/advisory   MIATCMAT1-5   parseTCM()
#   East Pac     NHC  TCM forecast/advisory   MIATCMEP1-5   parseTCM()
#   West Pac     JTWC WTPN warning            NFDTCPWP1-5   parseJTWC()
#   Central Pac  CPHC TCM forecast/advisory   HFOTCMCP1-5   parseTCM()
#
# *** EXPERIMENTAL.  NOT OPERATIONALLY VETTED. ***  Wind comes from an
# analytic vortex fitted to the quadrant wind radii in the text, not from any
# gridded product, and has not been verified against observations.  Every
# grid needs forecaster review before it informs any product.
#
# Install to:
#   /awips2/edex/data/utility/common_static/site/<SITE>/gfe/userPython/procedures/
#
# Runs standalone for testing, and reports which product format it detected:
#   python TCWind_JTWC.py sample_bulletin.txt
#
# WHY ANYTHING HERE IS THE WAY IT IS: TCWind_JTWC_TECHNICAL.md, alongside this
# file.  A "# [doc N]" marker below points at numbered note N in it.
#
# Author: (OPC)
# ----------------------------------------------------------------------------
MenuItems = ["Populate"]

import os
import re
import sys
import json
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

# The pmsl option needs TCPressure, a GFE utility.  Without it the Wind grids
# are built exactly as before and the status bar says pmsl was left alone.
try:
    import TCPressure
except ImportError:
    TCPressure = None


# AWIPS text database product IDs, not the WMO headings.  The WTPN33 PGTW
# heading appears on the bulletin itself, but textdb stores it under NFDTCPWP.
JTWC_PILS_WESTPAC = ["NFDTCPWP1", "NFDTCPWP2", "NFDTCPWP3",
                     "NFDTCPWP4", "NFDTCPWP5"]

# [doc 2]
NHC_PILS_ATLANTIC = ["MIATCMAT1", "MIATCMAT2", "MIATCMAT3",
                     "MIATCMAT4", "MIATCMAT5"]
NHC_PILS_EASTPAC = ["MIATCMEP1", "MIATCMEP2", "MIATCMEP3",
                    "MIATCMEP4", "MIATCMEP5"]
CPHC_PILS_CENTPAC = ["HFOTCMCP1", "HFOTCMCP2", "HFOTCMCP3",
                     "HFOTCMCP4", "HFOTCMCP5"]

# [doc 3]
BASINS = [
    ("Atlantic", NHC_PILS_ATLANTIC),
    ("East Pac", NHC_PILS_EASTPAC),
    ("West Pac", JTWC_PILS_WESTPAC),
    ("Central Pac", CPHC_PILS_CENTPAC),
]
BASIN_PILS = dict(BASINS)
BASIN_LABELS = [label for label, _ in BASINS]
DEFAULT_BASIN = BASIN_LABELS[0]

# [doc 4]

# Locations of the command-line textdb, tried in order for the fallback.
TEXTDB_PATHS = ["/awips/fxa/bin/textdb", "/awips2/fxa/bin/textdb", "textdb"]


# ---------------------------------------------------------------------------
# [doc 5]
# ---------------------------------------------------------------------------

TEST_CASE_BULLETIN = """WTPN31 PGTW 020900
MSGID/GENADMIN/JOINT TYPHOON WRNCEN PEARL HARBOR HI//
SUBJ/TROPICAL STORM 22W (KROVANH) WARNING NR 005//
RMKS/
1. TROPICAL STORM 22W (KROVANH) WARNING NR 005
   UPGRADED FROM TROPICAL DEPRESSION 22W
   02 ACTIVE TROPICAL CYCLONES IN NORTHWESTPAC
   MAX SUSTAINED WINDS BASED ON ONE-MINUTE AVERAGE
   WIND RADII VALID OVER OPEN WATER ONLY
    ---
   WARNING POSITION:
   020600Z --- NEAR 23.1N 132.4E
     MOVEMENT PAST SIX HOURS - 310 DEGREES AT 06 KTS
     POSITION ACCURATE TO WITHIN 030 NM
     POSITION BASED ON CENTER LOCATED BY SATELLITE
   PRESENT WIND DISTRIBUTION:
   MAX SUSTAINED WINDS - 035 KT, GUSTS 045 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 120 NM NORTHEAST QUADRANT
                            090 NM SOUTHEAST QUADRANT
                            080 NM SOUTHWEST QUADRANT
                            100 NM NORTHWEST QUADRANT
   REPEAT POSIT: 23.1N 132.4E
    ---
   FORECASTS:
   12 HRS, VALID AT:
   021800Z --- 24.7N 130.9E
   MAX SUSTAINED WINDS - 035 KT, GUSTS 045 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 130 NM NORTHEAST QUADRANT
                            080 NM SOUTHEAST QUADRANT
                            080 NM SOUTHWEST QUADRANT
                            100 NM NORTHWEST QUADRANT
   VECTOR TO 24 HR POSIT: 325 DEG/ 11 KTS
    ---
   24 HRS, VALID AT:
   030600Z --- 26.5N 129.5E
   MAX SUSTAINED WINDS - 040 KT, GUSTS 050 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 130 NM NORTHEAST QUADRANT
                            080 NM SOUTHEAST QUADRANT
                            080 NM SOUTHWEST QUADRANT
                            100 NM NORTHWEST QUADRANT
   VECTOR TO 36 HR POSIT: 325 DEG/ 09 KTS
    ---
   36 HRS, VALID AT:
   031800Z --- 28.0N 128.4E
   MAX SUSTAINED WINDS - 040 KT, GUSTS 050 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 130 NM NORTHEAST QUADRANT
                            080 NM SOUTHEAST QUADRANT
                            080 NM SOUTHWEST QUADRANT
                            100 NM NORTHWEST QUADRANT
   VECTOR TO 48 HR POSIT: 330 DEG/ 03 KTS
    ---
   EXTENDED OUTLOOK:
   48 HRS, VALID AT:
   040600Z --- 28.6N 128.0E
   MAX SUSTAINED WINDS - 045 KT, GUSTS 055 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 190 NM NORTHEAST QUADRANT
                            090 NM SOUTHEAST QUADRANT
                            090 NM SOUTHWEST QUADRANT
                            160 NM NORTHWEST QUADRANT
   VECTOR TO 60 HR POSIT: 180 DEG/ 02 KTS
    ---
   60 HRS, VALID AT:
   041800Z --- 28.3N 128.0E
   MAX SUSTAINED WINDS - 040 KT, GUSTS 050 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 190 NM NORTHEAST QUADRANT
                            080 NM SOUTHEAST QUADRANT
                            090 NM SOUTHWEST QUADRANT
                            160 NM NORTHWEST QUADRANT
   VECTOR TO 72 HR POSIT: 160 DEG/ 04 KTS
    ---
   72 HRS, VALID AT:
   050600Z --- 27.5N 128.3E
   MAX SUSTAINED WINDS - 040 KT, GUSTS 050 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 190 NM NORTHEAST QUADRANT
                            080 NM SOUTHEAST QUADRANT
                            080 NM SOUTHWEST QUADRANT
                            160 NM NORTHWEST QUADRANT
   VECTOR TO 96 HR POSIT: 150 DEG/ 03 KTS
    ---
   LONG RANGE OUTLOOK:
    ---
   96 HRS, VALID AT:
   060600Z --- 26.4N 129.0E
   MAX SUSTAINED WINDS - 035 KT, GUSTS 045 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 190 NM NORTHEAST QUADRANT
                            080 NM SOUTHEAST QUADRANT
                            080 NM SOUTHWEST QUADRANT
                            160 NM NORTHWEST QUADRANT
   VECTOR TO 120 HR POSIT: 110 DEG/ 03 KTS
    ---
   120 HRS, VALID AT:
   070600Z --- 26.0N 130.2E
   MAX SUSTAINED WINDS - 035 KT, GUSTS 045 KT
   WIND RADII VALID OVER OPEN WATER ONLY
   RADIUS OF 034 KT WINDS - 190 NM NORTHEAST QUADRANT
                            080 NM SOUTHEAST QUADRANT
                            080 NM SOUTHWEST QUADRANT
                            150 NM NORTHWEST QUADRANT
    ---
REMARKS:
020900Z POSITION NEAR 23.5N 132.0E. 02SEP26. TROPICAL STORM 22W
(KROVANH), LOCATED APPROXIMATELY 323 NM SOUTHEAST OF KADENA AB, HAS
TRACKED NORTHWESTWARD AT 06 KNOTS OVER THE PAST SIX HOURS. MINIMUM
CENTRAL PRESSURE AT 020600Z IS 994 MB. MAXIMUM SIGNIFICANT WAVE HEIGHT
AT 020600Z IS 18 FEET. NEXT WARNINGS AT 021500Z, 022100Z, 030300Z AND
030900Z. REFER TO TROPICAL DEPRESSION 17W (SAUDEL) WARNINGS (WTPN32
PGTW) FOR SIX-HOURLY UPDATES.//
NNNN


"""

# Dialog label for the "Run test case" toggle.  Also the varDict key it is
# read back under (see _buildVarDict()/execute()) - a module constant so the
# two stay in sync and the test harness can reuse it exactly.
TEST_CASE_LABEL = "Run test case (no live storm needed):"


# ---------------------------------------------------------------------------
# [doc 6]
# ---------------------------------------------------------------------------

# [doc 7]
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

# [doc 8]
GTCM_ASYM_MAX_DEV_KT = 10.0

# [doc 9]
GTCM_ASYM_MIN_CAP_KT = 3.0

# [doc 10]
GTCM_APPLY_INFLOW = False

# [doc 11]
GTCM_X_MIN = 0.20
GTCM_X_MAX = 1.20

GTCM_MAX_ITER = 220
GTCM_ASYM_STEPS = 9

# [doc 12]
GTCM_R34_PROBE_MAX_NM = 900
GTCM_R34_AZ_BINS = 360

# [doc 13]
MOTION_ASYMMETRY_FRACTION = 0.5

# Degrees the surface wind is rotated toward the center.  Open-water value;
# affects direction only, never speed.
INFLOW_ANGLE_DEG = 22.0

# [doc 14]
RMAX_OVERRIDE_NM = 0.0

# [doc 15]
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

# [doc 67]
# Forecaster points past the end of a warning - days 6 and 7 - entered in a
# second dialog, appended to the warning's own track, and saved so the next
# run pre-fills them.  Rows are offered at these hours after the warning's
# initial time.  EXTENSION_STORE should be a directory every forecaster's
# account can read and write if the points are to survive a shift change.
EXTENSION_LABEL = "Forecaster points past the warning (days 6-7):"
EXTENSION_HOURS = (132, 144, 156, 168)
EXTENSION_STORE = os.path.join(os.path.expanduser("~"),
                               ".TCWind_JTWC_extensions.json")
EXTENSION_KEEP_DAYS = 10.0

# [doc 68]
# An extratropical point's wind field is lopsided in a way the tropical fit
# refuses on purpose: its asymmetry is searched this far from the motion
# vector, and capped at this fraction of the max wind instead of 1.5 times
# the motion-derived value.
ET_ASYM_MAX_DEV_KT = 30.0
ET_ASYM_CAP_FRACTION = 0.45

# 1.0 keeps JTWC's 1-minute sustained winds; 0.88 converts to 10-minute.
WIND_AVERAGING_FACTOR = 1.0

# [doc 16]
NORMALIZE_CORE_PEAK = True
PEAK_NORMALIZE_MAX_FACTOR = 2.0

# [doc 17]
OUTPUT_GRID_INTERVAL_SECONDS = 3 * 3600  # 3 hours, always, regardless of the background Fcst Wind grid cadence.

# Name of the scratch weather element used for preview runs.  It is created
# on the fly as a temporary parm, so it needs no serverConfig entry, is not
# saved or published, and disappears when the forecaster clears it.
PREVIEW_ELEMENT = "WindJTWC"
PREVIEW_MAX_KT = 200.0

# [doc 64]
# pmsl: each storm is moved, in every existing pmsl grid the warnings cover,
# to the warning's position and central pressure by TCPressure (a GFE
# utility).  Previews go to this scratch element, made like PREVIEW_ELEMENT.
PMSL_LABEL = "Also move the storms in pmsl to the warnings:"
PMSL_PREVIEW_ELEMENT = "pmslJTWC"
PMSL_PREVIEW_LIMITS_MB = (850.0, 1100.0)

# [doc 18]
EXPERIMENTAL = True
REQUIRE_ACKNOWLEDGEMENT = True

# Shown in the dialog title and the status bar.  Bump it on every install so
# there is never any doubt about which copy GFE actually loaded.
VERSION = "2026-10-02b"

# [doc 19]
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

# [doc 20]
CONF_TROPICAL = 1.00
CONF_BECOMING = 0.60
CONF_SUBTROPICAL = 0.25


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

RE_REFDATE = re.compile(r"\b(\d{2})([A-Z]{3})(\d{2})\b")
# [doc 21]
RE_WMO_HEADER = re.compile(
    r"^[A-Z]{4}\d{2}\s+[A-Z]{4}\s+(\d{2})(\d{2})(\d{2})\s*$", re.MULTILINE)
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
        self.fit = None             # cache: fitGTCM(self), set by _fitTau()
        # Forecaster points (extendTrack) only.
        self.synthetic = False
        self.extratropical = False
        self.pressureMb = None

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


def parseJTWC(text, nowSecs=None):
    """Parse a WTPN warning into a time-ordered list of Tau objects."""
    if isinstance(text, (list, tuple)):
        lines = list(text)
    else:
        lines = text.split("\n")

    # [doc 22]
    ref_day = ref_month = ref_year = None
    for ln in lines:
        m = RE_REFDATE.search(ln)
        if m and m.group(2) in MONTHS:
            ref_day = int(m.group(1))
            ref_month = MONTHS[m.group(2)]
            ref_year = 2000 + int(m.group(3))
            break

    if ref_day is None:
        # [doc 23]
        mh = RE_WMO_HEADER.search("\n".join(lines))
        if mh is None:
            raise ValueError(
                "Could not find a DDMMMYY reference date in the bulletin "
                "remarks, and no WMO header DDHHMM group to fall back to; "
                "cannot resolve DTGs.")
        if nowSecs is None:
            nowSecs = time.time()
        now = time.gmtime(nowSecs)
        fallback_epoch = _dtg_to_epoch(mh.group(1) + mh.group(2) + mh.group(3),
                                       now.tm_mday, now.tm_mon, now.tm_year)
        resolved = time.gmtime(fallback_epoch)
        ref_day = resolved.tm_mday
        ref_month = resolved.tm_mon
        ref_year = resolved.tm_year

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


# ---------------------------------------------------------------------------
# [doc 24]
# ---------------------------------------------------------------------------

_TCM_TYPES = (r"HURRICANE|TROPICAL STORM|TROPICAL DEPRESSION|"
              r"POTENTIAL TROPICAL CYCLONE|SUBTROPICAL STORM|"
              r"SUBTROPICAL DEPRESSION|POST-TROPICAL CYCLONE|REMNANTS OF")

# re.M: matched against the whole product, so ^ must anchor at the start of
# the title line rather than only at offset 0.
RE_TCM_TITLE = re.compile(
    r"^\s*(" + _TCM_TYPES + r")\s+(.+?)\s+FORECAST/ADVISORY NUMBER\s+(\d+)",
    re.M)
RE_TCM_ATCFID = re.compile(r"\b(AL|EP|CP)(\d{2})(\d{4})\b")
RE_TCM_ISSUE = re.compile(
    r"(\d{3,4})\s+UTC\s+[A-Z]{3}\s+([A-Z]{3})\s+(\d{1,2})\s+(\d{4})")
RE_TCM_CURPOS = re.compile(
    r"^\s*(" + _TCM_TYPES + r")\s+CENTER LOCATED NEAR\s+"
    r"(\d+(?:\.\d+)?)\s*([NS])\s+(\d+(?:\.\d+)?)\s*([EW])\s+AT\s+"
    r"(\d{2})/(\d{4})Z")
RE_TCM_BACKFILL = re.compile(
    r"^\s*AT\s+(\d{2})/(\d{4})Z\s+CENTER WAS LOCATED NEAR\s+"
    r"(\d+(?:\.\d+)?)\s*([NS])\s+(\d+(?:\.\d+)?)\s*([EW])")
RE_TCM_FCST = re.compile(
    r"^\s*(FORECAST|OUTLOOK)\s+VALID\s+(\d{2})/(\d{4})Z\s+"
    r"(\d+(?:\.\d+)?)\s*([NS])\s+(\d+(?:\.\d+)?)\s*([EW])"
    r"(?:\.\.\.([A-Z][A-Z\- ]*))?")
RE_TCM_MOVEMENT = re.compile(
    r"PRESENT MOVEMENT.*?(\d+)\s*DEGREES AT\s+(\d+)\s*KT")
RE_TCM_WINDS_CUR = re.compile(
    r"MAX SUSTAINED WINDS\s+(\d+)\s*KT WITH GUSTS TO\s+(\d+)\s*KT")
RE_TCM_WINDS_FCST = re.compile(r"MAX WIND\s+(\d+)\s*KT\.*\s*GUSTS\s+(\d+)\s*KT")
# Anchored at the line start so it cannot match the seas line - difference 5.
RE_TCM_RADII = re.compile(r"^\s*(\d+)\s*KT\.+\s*(.+?)\.?\s*$")
RE_TCM_QUAD = re.compile(r"(\d+)\s*(NE|SE|SW|NW)")
RE_TCM_PRESSURE = re.compile(
    r"(?:ESTIMATED\s+)?MINIMUM\s+CENTRAL\s+PRESSURE\s+(\d+)\s*MB")
RE_TCM_TERM = re.compile(r"^\s*\$\$\s*$")

# [doc 25]
TCM_TYPE_CONF = {
    "HURRICANE": CONF_TROPICAL,
    "TROPICAL STORM": CONF_TROPICAL,
    "TROPICAL DEPRESSION": CONF_TROPICAL,
    "POTENTIAL TROPICAL CYCLONE": CONF_TROPICAL,
    "SUBTROPICAL STORM": CONF_SUBTROPICAL,
    "SUBTROPICAL DEPRESSION": CONF_SUBTROPICAL,
    "POST-TROPICAL CYCLONE": CONF_BECOMING,
    "REMNANTS OF": CONF_BECOMING,
}


def parseTCM(text, nowSecs=None):
    """Parse an NHC/CPHC TCM into the same (taus, header) parseJTWC() returns."""
    if isinstance(text, (list, tuple)):
        lines = list(text)
        text = "\n".join(lines)
    else:
        lines = text.split("\n")
    full = "\n".join(lines)

    m = RE_TCM_ISSUE.search(full)
    if not m or m.group(2) not in MONTHS:
        raise ValueError(
            'Could not find a "<time> UTC <dow> <mon> <day> <year>" issuance '
            'line in the bulletin; cannot resolve DTGs.')
    ref_day = int(m.group(3))
    ref_month = MONTHS[m.group(2)]
    ref_year = int(m.group(4))

    taus = []
    cur = None
    prior_pos = None        # difference 6: a backfill point, never a tau

    for ln in lines:
        if RE_TCM_TERM.match(ln):
            break           # "$$" - hard stop, difference 9

        m = RE_TCM_CURPOS.search(ln)
        if m:
            cur = Tau(0)    # real tau assigned once every epoch is known
            cur.epoch = _dtg_to_epoch(m.group(6) + m.group(7),
                                      ref_day, ref_month, ref_year)
            lat = float(m.group(2))
            lon = float(m.group(4))
            cur.lat = -lat if m.group(3) == "S" else lat
            cur.lon = -lon if m.group(5) == "W" else lon
            if m.group(1) in TCM_TYPE_CONF:
                cur.conf = TCM_TYPE_CONF[m.group(1)]
            taus.append(cur)
            continue

        m = RE_TCM_FCST.search(ln)
        if m:
            cur = Tau(0)
            cur.epoch = _dtg_to_epoch(m.group(2) + m.group(3),
                                      ref_day, ref_month, ref_year)
            lat = float(m.group(4))
            lon = float(m.group(6))
            cur.lat = -lat if m.group(5) == "S" else lat
            cur.lon = -lon if m.group(7) == "W" else lon
            # Difference 7: a status word can ride on this line with no line
            # break.  Downgrade the same way a JTWC "BECOMING EXTRATROPICAL"
            # line does, and ignore anything else it might say.
            status = (m.group(8) or "").upper()
            if "POST-TROPICAL" in status or "EXTRATROPICAL" in status:
                cur.conf = CONF_BECOMING
            elif "SUBTROPICAL" in status:
                cur.conf = CONF_SUBTROPICAL
            taus.append(cur)
            continue

        m = RE_TCM_BACKFILL.search(ln)
        if m:
            lat = float(m.group(3))
            lon = float(m.group(5))
            prior_pos = Tau(0)
            prior_pos.lat = -lat if m.group(4) == "S" else lat
            prior_pos.lon = -lon if m.group(6) == "W" else lon
            prior_pos.epoch = _dtg_to_epoch(m.group(1) + m.group(2),
                                            ref_day, ref_month, ref_year)
            continue

        if cur is None:
            continue

        m = RE_TCM_WINDS_CUR.search(ln)
        if m:
            cur.vmax = float(m.group(1))
            cur.gust = float(m.group(2))
            continue

        m = RE_TCM_WINDS_FCST.search(ln)
        if m:
            cur.vmax = float(m.group(1))
            cur.gust = float(m.group(2))
            continue

        m = RE_TCM_RADII.match(ln)
        if m:
            threshold = int(m.group(1))
            if threshold not in cur.radii:
                cur.radii[threshold] = dict((q, 0.0) for q in QUADS)
            for tok in RE_TCM_QUAD.finditer(m.group(2)):
                cur.radii[threshold][tok.group(2)] = float(tok.group(1))
            continue

        m = RE_TCM_MOVEMENT.search(ln)
        if m:
            cur.motionDir = float(m.group(1))
            cur.motionSpd = float(m.group(2))
            continue

        if "BECOMING SUBTROPICAL" in ln or "BECOMING EXTRATROPICAL" in ln:
            cur.conf = CONF_BECOMING
        elif re.search(r"^\s*(SUB|EXTRA)TROPICAL\s*$", ln):
            cur.conf = CONF_SUBTROPICAL

    # Drop anything incomplete - a DISSIPATED block carries a valid time and
    # no position (difference 7) - then order by valid time.
    taus = [t for t in taus
            if t.lat is not None and t.epoch is not None and t.vmax is not None]
    taus.sort(key=lambda t: t.epoch)
    if not taus:
        raise ValueError("No usable FORECAST/ADVISORY position blocks parsed "
                         "from this bulletin.")

    # Difference 7: no printed tau label, so derive it from the epochs.
    t0 = taus[0].epoch
    for t in taus:
        t.tau = int(round((t.epoch - t0) / 3600.0))

    # Once flagged sub/post-tropical it stays that way, exactly as parseJTWC().
    worst = CONF_TROPICAL
    for t in taus:
        worst = min(worst, t.conf)
        t.conf = worst

    # Backfill the current block's motion from the six-hour-earlier position
    # when no PRESENT MOVEMENT line supplied it (differences 3 and 6).
    if taus[0].motionSpd is None and prior_pos is not None:
        taus[0].motionDir, taus[0].motionSpd = _bearing_speed(prior_pos, taus[0])
    # Everything else exactly as parseJTWC() does it: forward from the next
    # tau, else carried back from the previous one.
    for i, t in enumerate(taus):
        if t.motionSpd is None:
            if i + 1 < len(taus):
                t.motionDir, t.motionSpd = _bearing_speed(t, taus[i + 1])
            elif i > 0:
                t.motionDir = taus[i - 1].motionDir
                t.motionSpd = taus[i - 1].motionSpd
            else:
                t.motionDir = 0.0
                t.motionSpd = 0.0

    header = {"refDate": (ref_day, ref_month, ref_year),
              "systemType": None, "stormId": None, "stormName": None,
              "warningNumber": None, "pressureMb": None, "basin": None}

    m = RE_TCM_TITLE.search(full)
    if m:
        header["systemType"] = m.group(1)
        header["stormName"] = m.group(2).rstrip()
        header["warningNumber"] = int(m.group(3))
    m = RE_TCM_ATCFID.search(full)
    if m:
        header["stormId"] = m.group(1) + m.group(2)
        header["basin"] = "AT" if m.group(1) == "AL" else m.group(1)
    m = RE_TCM_PRESSURE.search(full)
    if m:
        header["pressureMb"] = int(m.group(1))

    return taus, header


# [doc 26]
RE_TCM_SNIFF = re.compile(r"FORECAST/ADVISORY NUMBER", re.I)


def parseBulletin(text, nowSecs=None):
    """Parse either product, choosing by content rather than by PIL."""
    if RE_TCM_SNIFF.search(text or ""):
        taus, header = parseTCM(text, nowSecs)
        return taus, header, "tcm"
    taus, header = parseJTWC(text, nowSecs)
    return taus, header, "jtwc"


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


def _gridCenterLatLon(latGrid, lonGrid):
    """Center lat/lon of a GFE grid, wrapped to -180..180."""
    clat = float(np.mean(latGrid))
    lonRad = np.radians(np.asarray(lonGrid, dtype=np.float64))
    clon = float(np.degrees(np.arctan2(np.mean(np.sin(lonRad)),
                                       np.mean(np.cos(lonRad)))))
    return clat, clon


def _rebaseTestCaseTrack(taus, header, nowSecs, latGrid, lonGrid):
    """Rebase TEST_CASE_BULLETIN's parsed track onto "now" and the active
    grid, so the built-in test case never looks stale and always lands
    somewhere the forecaster can see it, regardless of where or when it is
    run.
    """
    if not taus:
        return taus, header

    targetEpoch0 = nowSecs - 3 * 3600.0
    epochShift = targetEpoch0 - taus[0].epoch
    for t in taus:
        t.epoch += epochShift

    refStruct = time.gmtime(taus[0].epoch)
    header = dict(header)
    header["refDate"] = (refStruct.tm_mday, refStruct.tm_mon, refStruct.tm_year)

    clat, clon = _gridCenterLatLon(latGrid, lonGrid)
    dlat = clat - taus[0].lat
    dlon = clon - taus[0].lon
    if dlon > 180.0:
        dlon -= 360.0
    elif dlon < -180.0:
        dlon += 360.0

    for t in taus:
        t.lat += dlat
        t.lon = ((t.lon + dlon + 180.0) % 360.0) - 180.0

    return taus, header


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
        self.fit = None             # GTCM fit params for this instant, or
                                    # [doc 27]
        self.fitInterpolated = False  # True if .fit was blended from two
                                      # taus rather than fit directly


def _fitTau(tau):
    """GTCM fit for one Tau's own reported radii, lazily computed and
    cached on the Tau (see Tau.fit).
    """
    if tau.fit is None:
        tau.fit = fitGTCM(tau)
    return tau.fit


# [doc 28]
_GTCM_FIT_BLEND_KEYS = ("rm", "ri", "x1", "x2", "ax", "ay", "a")


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

    # [doc 29]
    for threshold in (64, 50, 34):
        a = lo.quad(threshold)
        b = hi.quad(threshold)
        vals = dict((q, a[q] + f * (b[q] - a[q])) for q in QUADS)
        if max(vals.values()) > 0.0:
            s.radii[threshold] = vals

    # The vortex FIELD comes from interpolating each tau's OWN fit (each
    # fit exactly once, from that tau's own reported radii, and cached).
    loFit = _fitTau(lo)
    if hi is lo:
        s.fit = dict(loFit)
        s.fitInterpolated = False
    else:
        hiFit = _fitTau(hi)
        blended = dict((k, loFit[k] + f * (hiFit[k] - loFit[k]))
                       for k in _GTCM_FIT_BLEND_KEYS)
        nearer = hiFit if f >= 0.5 else loFit
        blended["n"] = nearer["n"]
        blended["rms"] = nearer["rms"]
        blended["freeParams"] = nearer["freeParams"]
        # rmSource is categorical (climatology/fit), not a number to blend -
        # rm itself interpolates linearly either way (_GTCM_FIT_BLEND_KEYS
        # above), so this only labels which one the blended rm is nearer to.
        blended["rmSource"] = nearer["rmSource"]
        s.fit = blended
        s.fitInterpolated = True
    return s


# ---------------------------------------------------------------------------
# Vortex construction
# ---------------------------------------------------------------------------

def willoughbyRmax(vmax_kt, lat_deg):
    """Rmax regression, returned in nautical miles."""
    v_ms = vmax_kt * KT2MS
    rmax_km = 98.392 * np.exp(-0.025088 * v_ms + 0.003021 * abs(lat_deg))
    return rmax_km * KM2NM


def resolveRmax(snapshot, override_nm=0.0):
    """Rmax estimate, clamped so it stays inside the highest reported ring."""
    if override_nm and override_nm > 0:
        rmax = float(override_nm)
    else:
        rmax = willoughbyRmax(snapshot.vmax, snapshot.lat)

    for threshold in (64, 50, 34):
        if threshold not in snapshot.radii:
            continue
        # [doc 30]
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
    """Interpolate the four quadrant radii smoothly around the compass."""
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
    """Symmetric modified Rankine tangential wind.  Users Guide eq. (3)."""
    vs = max(float(vmax) - float(a), 0.0)
    rm = max(float(rm), 1e-3)
    ri = max(float(ri), rm * 1.0001)
    safe = np.maximum(np.asarray(r, dtype=float), 1e-6)
    # [doc 31]
    A = (rm / ri) ** (x1 - x2)
    return np.where(safe < rm, vs * (safe / rm),
                    np.where(safe < ri,
                             vs * (rm / safe) ** x1,
                             A * vs * (rm / safe) ** x2))


def _gtcmUV(V, azDeg, ax, ay, lat):
    """2-D wind from tangential wind plus asymmetry.  Users Guide eq. (8)/(9)."""
    azr = np.radians(np.asarray(azDeg, dtype=float))
    sign = 1.0 if lat >= 0 else -1.0
    u = ax - sign * V * np.cos(azr)
    v = ay + sign * V * np.sin(azr)
    return u, v


def _gtcmTargets(snapshot):
    """Fit points: (radius_nm, bearing_deg, threshold_kt, weight)."""
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
    """Fit the GTCM vortex to one storm-time."""
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
        # [doc 32]
        return dict(rm=rmc, ri=rmc * 3.0, x1=xc, x2=xc,
                    ax=float(ax0), ay=float(ay0), a=a, n=0, freeParams=0,
                    rms=float("nan"), rmSource="climatology")

    rr = np.array([t[0] for t in targets])
    az = np.array([t[1] for t in targets])
    vt = np.array([t[2] for t in targets])
    wt = np.array([t[3] for t in targets])
    ri = float(np.median(rr))

    def err(rm, x1, x2, ax, ay):
        # [doc 33]
        amag = float(np.hypot(ax, ay))
        V = _gtcmProfile(rr, vmax, amag, rm, ri, x1, x2)
        u, v = _gtcmUV(V, az, ax, ay, lat)
        return float(np.sum(wt * (np.sqrt(u * u + v * v) - vt) ** 2))

    # [doc 34]
    hasHigherTargets = any(t[2] > 34.0 for t in targets)

    if not hasHigherTargets:
        rmSource = "climatology"
        rm = willoughbyRmax(vmax, lat)
        freeParams = 1           # the shared decay exponent only

        def sizeObj(p):
            x_ = p[0]
            if not (GTCM_X_MIN <= x_ <= GTCM_X_MAX):
                return 1e12
            return err(rm, x_, x_, ax0, ay0)
        # [doc 35]
        (xf,), _ = _nelderMead(sizeObj, [xc], [0.12], GTCM_MAX_ITER)
        x1 = x2 = xf
    else:
        rmSource = "fit"

        # [doc 36]
        nfit = len(targets)
        if nfit >= 5:
            freeParams = 3          # rm, x1, x2 all identifiable
        elif nfit >= 3:
            freeParams = 2          # rm and one shared exponent
        else:
            freeParams = 1          # rm only; exponent stays at climatology

        # [doc 37]
        rmLo, rmHi = (2.0, 150.0) if freeParams == 3 else (
            (0.4 * rmc, 2.5 * rmc) if freeParams == 2 else (0.5 * rmc, 2.0 * rmc))

        if freeParams == 3:
            def sizeObj(p):
                rm_, x1_, x2_ = p
                if not (rmLo <= rm_ <= rmHi) or not (GTCM_X_MIN <= x1_ <= GTCM_X_MAX) \
                   or not (GTCM_X_MIN <= x2_ <= GTCM_X_MAX):
                    return 1e12
                return err(rm_, x1_, x2_, ax0, ay0)
            (rm, x1, x2), _ = _nelderMead(sizeObj, [rmc, xc, xc],
                                          [max(rmc * 0.35, 4.0), 0.12, 0.12],
                                          GTCM_MAX_ITER)
        elif freeParams == 2:
            def sizeObj(p):
                rm_, x_ = p
                if not (rmLo <= rm_ <= rmHi) or not (GTCM_X_MIN <= x_ <= GTCM_X_MAX):
                    return 1e12
                return err(rm_, x_, x_, ax0, ay0)
            (rm, xs), _ = _nelderMead(sizeObj, [rmc, xc],
                                      [max(rmc * 0.35, 4.0), 0.12], GTCM_MAX_ITER)
            x1 = x2 = xs
        else:
            def sizeObj(p):
                rm_ = p[0]
                if not (rmLo <= rm_ <= rmHi):
                    return 1e12
                return err(rm_, xc, xc, ax0, ay0)
            (rm,), _ = _nelderMead(sizeObj, [rmc], [max(rmc * 0.35, 4.0)],
                                   GTCM_MAX_ITER)
            x1 = x2 = xc

    # [doc 38]
    asymCap = max(1.5 * a, GTCM_ASYM_MIN_CAP_KT)
    maxDev = GTCM_ASYM_MAX_DEV_KT
    if getattr(snapshot, "extratropical", False):
        asymCap = max(asymCap, ET_ASYM_CAP_FRACTION * vmax)
        maxDev = ET_ASYM_MAX_DEV_KT
    asymCap2 = asymCap * asymCap
    best = (err(rm, x1, x2, ax0, ay0), float(ax0), float(ay0))
    grid = np.linspace(-maxDev, maxDev, GTCM_ASYM_STEPS)
    for dx in grid:
        for dy in grid:
            axc, ayc = ax0 + dx, ay0 + dy
            if axc * axc + ayc * ayc > asymCap2:
                continue          # magnitude cap rejects this candidate
            e = err(rm, x1, x2, axc, ayc)
            if e < best[0]:
                best = (e, float(axc), float(ayc))
    def asymObj(p):
        dx, dy = p[0] - ax0, p[1] - ay0
        if dx * dx + dy * dy > maxDev ** 2:
            return 1e12
        if p[0] * p[0] + p[1] * p[1] > asymCap2:
            return 1e12
        return err(rm, x1, x2, p[0], p[1])
    (axf, ayf), ef = _nelderMead(asymObj, [best[1], best[2]], [2.0, 2.0], 80)
    if ef < best[0]:
        best = (ef, float(axf), float(ayf))

    return dict(rm=float(rm), ri=ri, x1=float(x1), x2=float(x2),
                ax=best[1], ay=best[2], a=a, n=len(targets),
                freeParams=freeParams, rmSource=rmSource,
                rms=float(np.sqrt(best[0] / np.sum(wt))))


def _buildVortexGTCM(latGrid, lonGrid, snapshot, rmax_nm, outerDecayFactor,
                     normalizePeak):
    """GTCM field for one time.  Users Guide eq. (3), (8), (9)."""
    r, az = _distBearingGrids(latGrid, lonGrid, snapshot.lat, snapshot.lon)
    fit = snapshot.fit if getattr(snapshot, "fit", None) is not None \
        else fitGTCM(snapshot)

    # [doc 39]
    amag = float(np.hypot(fit["ax"], fit["ay"]))

    V = _gtcmProfile(r, snapshot.vmax, amag, fit["rm"], fit["ri"],
                     fit["x1"], fit["x2"])
    u, v = _gtcmUV(V, az, fit["ax"], fit["ay"], snapshot.lat)
    mag = np.sqrt(u * u + v * v)

    # [doc 40]
    probe = np.linspace(1.0, GTCM_R34_PROBE_MAX_NM, GTCM_R34_PROBE_MAX_NM)
    prof = _gtcmProfile(probe, snapshot.vmax, amag, fit["rm"], fit["ri"],
                        fit["x1"], fit["x2"])
    azTable = np.linspace(0.0, 360.0, GTCM_R34_AZ_BINS, endpoint=False)
    uu, vv = _gtcmUV(prof[None, :], azTable[:, None],
                     fit["ax"], fit["ay"], snapshot.lat)
    prof2d = np.sqrt(uu * uu + vv * vv)
    # The OUTERMOST radius still at 34 kt.  Not the first crossing: the profile
    # is also below 34 kt inside the eye, and taking that would collapse the
    # footprint onto the centre and taper the entire field away.
    above = prof2d >= 34.0
    anyAbove = above.any(axis=1)
    last = prof2d.shape[1] - 1 - np.argmax(above[:, ::-1], axis=1)

    # [doc 41]
    rows = np.arange(prof2d.shape[0])
    nxt = np.minimum(last + 1, prof2d.shape[1] - 1)
    v_hi = prof2d[rows, last]
    v_lo = prof2d[rows, nxt]
    span = v_hi - v_lo
    frac = np.where(span > 1e-9, (v_hi - 34.0) / np.maximum(span, 1e-9), 0.0)
    frac = np.clip(frac, 0.0, 1.0)
    r34_exact = probe[last] + frac * (probe[nxt] - probe[last])

    # [doc 42]
    peakIdx = np.argmax(prof2d, axis=1)
    peakR = probe[peakIdx]
    r34_table = np.where(anyAbove, r34_exact, peakR)

    # Interpolate r34(az) onto the grid's own azimuths, linear and wrapping
    # at 360 so the 0/360 seam stays continuous (azTable's last bin is
    # centered below 360, so it and azTable[0] must both anchor the wrap).
    azTableWrap = np.concatenate([azTable, [360.0]])
    r34TableWrap = np.concatenate([r34_table, r34_table[:1]])
    azFlat = np.asarray(az, dtype=float).ravel() % 360.0
    r34 = np.interp(azFlat, azTableWrap, r34TableWrap)
    r34 = r34.reshape(r.shape).astype(np.float32)

    # [doc 43]
    az1d = np.asarray(az).ravel()
    r341d = np.asarray(r34).ravel()
    Vanchor = _gtcmProfile(r341d, snapshot.vmax, amag, fit["rm"],
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
    # [doc 44]
    if snapshot.radii:
        asymFrac = 0.0

    r, az = _distBearingGrids(latGrid, lonGrid, snapshot.lat, snapshot.lon)

    floor = rmax_nm * 1.05

    # Assemble the profile knots from strongest to weakest, keeping only the
    # thresholds the storm actually reaches.
    knot_r = [np.full(r.shape, rmax_nm, dtype=np.float32)]
    knot_v = [snapshot.vmax]
    prev = knot_r[0]

    # [doc 45]
    if asymFrac and snapshot.motionSpd:
        knot_v[0] = max(snapshot.vmax - asymFrac * snapshot.motionSpd, 0.0)
    for threshold in (64, 50, 34):
        if threshold not in snapshot.radii:
            continue
        # [doc 46]
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
        # [doc 47]
        x = np.log(v1 / v2) / np.log(ratio)
        x = np.clip(x, 0.0, 2.5)
        seg = (r > r1) & (r <= r2)
        mag = np.where(seg,
                       v1 * (np.maximum(r1, 1e-3) / safe_r) ** x,
                       mag)

    # [doc 48]
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
        # [doc 49]
        frac = asymFrac * np.clip(mag / max(knot_v[0], 1.0), 0.0, 1.0)

        # [doc 50]
        if snapshot.radii and MOTION_ASYMMETRY_FRACTION:
            core = np.clip(r / np.maximum(knot_r[0], 1e-3), 0.0, 1.0)
            coreFrac = MOTION_ASYMMETRY_FRACTION * 4.0 * core * (1.0 - core)
            frac = np.where(r <= knot_r[0], coreFrac, frac)

        mrad = np.radians(snapshot.motionDir)
        u = u + frac * snapshot.motionSpd * np.sin(mrad)
        v = v + frac * snapshot.motionSpd * np.cos(mrad)

    magOut = np.sqrt(u * u + v * v)
    dirOut = (np.degrees(np.arctan2(-u, -v))) % 360.0

    # [doc 51]
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
    """Hard-insert one or more warning wind fields over the background."""
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

# ---------------------------------------------------------------------------
# Forecaster points past the warning (days 6-7)
# ---------------------------------------------------------------------------

def parseCoord(text, kind):
    """Latitude or longitude from what a forecaster types.

    "38.5N", "38.5", "-12S"... and "165E", "165.0W", "-165", "195" (east of
    the dateline in 0..360).  Returns degrees (longitude in -180..180), or
    None for a blank box; raises ValueError for anything unreadable.
    """
    t = (text or "").strip().upper().replace(" ", "")
    if not t:
        return None
    hemi = t[-1] if t[-1] in "NSEW" else ""
    if hemi:
        t = t[:-1]
    value = float(t)
    if kind == "lat":
        if hemi in ("E", "W"):
            raise ValueError("latitude ends in %s" % hemi)
        if hemi == "S":
            value = -abs(value)
        if not -90.0 <= value <= 90.0:
            raise ValueError("latitude %s out of range" % text.strip())
        return value
    if hemi in ("N", "S"):
        raise ValueError("longitude ends in %s" % hemi)
    if hemi == "W":
        value = -abs(value)
    if not -360.0 <= value <= 360.0:
        raise ValueError("longitude %s out of range" % text.strip())
    return ((value + 180.0) % 360.0) - 180.0


def formatCoord(value, kind):
    if kind == "lat":
        return "%.1f%s" % (abs(value), "N" if value >= 0 else "S")
    return "%.1f%s" % (abs(value), "E" if value >= 0 else "W")


def parseRadii(text):
    """Four quadrant radii, NE SE SW NW, from "300 250 60 40" (commas or
    slashes too).  One number means the same in every quadrant.  Blank is
    None.  Raises ValueError otherwise."""
    t = re.sub(r"[,/;]", " ", (text or "")).split()
    if not t:
        return None
    vals = [float(v) for v in t]
    if len(vals) == 1:
        vals = vals * 4
    if len(vals) != 4:
        raise ValueError("give four radii, NE SE SW NW (got %d)" % len(vals))
    if any(v < 0.0 or v > 1500.0 for v in vals):
        raise ValueError("radii must be 0-1500 nm")
    return dict(zip(QUADS, vals))


def parseValidTime(text, refEpoch):
    """A DDHHMM / DDHH group, with or without Z, as unix seconds, resolved
    against the warning's initial time for the month."""
    t = (text or "").strip().upper().rstrip("Z")
    if not re.match(r"^\d{4}(\d{2})?$", t):
        raise ValueError("valid time %r is not DDHH or DDHHMM" % text)
    if len(t) == 4:
        t += "00"
    ref = time.gmtime(refEpoch)
    return _dtg_to_epoch(t, ref.tm_mday, ref.tm_mon, ref.tm_year)


def TCPressureName(header):
    """The storm's name as status lines give it."""
    return header.get("stormName") or header.get("stormId") or "unnamed"


def stormKey(header, pil=None):
    """What a saved extension is filed under: the storm's ID ("22W",
    "AL13"), which survives the 6-hourly warnings and a name change."""
    return (header.get("stormId") or header.get("stormName") or pil or
            "unknown")


def loadExtensions(path=None):
    """{stormKey: {"name", "saved", "points": [...]}} - empty when there is
    no file yet or it cannot be read."""
    path = path or EXTENSION_STORE
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def saveExtensions(data, path=None, nowSecs=None):
    """Write the store, dropping storms not touched for EXTENSION_KEEP_DAYS.
    Returns None, or why it could not be written."""
    path = path or EXTENSION_STORE
    nowSecs = time.time() if nowSecs is None else nowSecs
    keep = dict((k, v) for k, v in data.items()
                if v.get("points") and
                nowSecs - v.get("saved", nowSecs) <=
                EXTENSION_KEEP_DAYS * 86400.0)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(keep, fh, indent=1, sort_keys=True)
        os.rename(tmp, path)
    except (IOError, OSError) as exc:
        return "could not save the points to %s (%s)" % (path, exc)
    return None


def extendTrack(taus, points):
    """The warning's taus with the forecaster's points appended.

    Returns (taus, used, dropped): points at or before the warning's last
    time are covered by the warning and dropped.  An extratropical point is
    flagged the way the parser flags the warning's own transition, so the
    "Subtropical / extratropical" choice governs it, and once flagged the
    track stays flagged.  Motion is recomputed across the join.
    """
    taus = list(taus)
    last = taus[-1]
    used, dropped = [], []
    for p in sorted(points, key=lambda q: q["epoch"]):
        if p["epoch"] <= taus[-1].epoch:
            dropped.append(p)
            continue
        t = Tau(int(round((p["epoch"] - taus[0].epoch) / 3600.0)))
        t.epoch = int(p["epoch"])
        t.lat, t.lon = float(p["lat"]), float(p["lon"])
        t.vmax = float(p["vmax"])
        if p.get("r34") and max(p["r34"].values()) > 0.0:
            t.radii = {34: dict((q, float(p["r34"][q])) for q in QUADS)}
        t.synthetic = True
        t.extratropical = bool(p.get("extratropical"))
        t.pressureMb = p.get("pressureMb")
        t.conf = min(taus[-1].conf,
                     CONF_SUBTROPICAL if t.extratropical else CONF_TROPICAL)
        taus.append(t)
        used.append(p)
    if used:
        start = taus.index(last)
        for i in range(start, len(taus)):
            if i + 1 < len(taus):
                taus[i].motionDir, taus[i].motionSpd = \
                    _bearing_speed(taus[i], taus[i + 1])
            else:
                taus[i].motionDir = taus[i - 1].motionDir
                taus[i].motionSpd = taus[i - 1].motionSpd
            if taus[i].synthetic:
                taus[i].fit = None
    return taus, used, dropped


def pressureTargetAt(taus, epoch):
    """The forecaster's central pressure at `epoch`, and how much it counts.

    Returns (mb, weight) or None.  Between two points with a pressure it is
    interpolated at full weight; from the warning's last time (pressure from
    the winds) to the first point with one, its weight ramps from 0 to 1, so
    the depth hands over from the warning's to the forecaster's smoothly.
    """
    for i in range(len(taus) - 1):
        lo, hi = taus[i], taus[i + 1]
        if not lo.epoch <= epoch <= hi.epoch:
            continue
        f = (epoch - lo.epoch) / float(max(hi.epoch - lo.epoch, 1))
        pLo = lo.pressureMb if lo.synthetic else None
        pHi = hi.pressureMb if hi.synthetic else None
        if pLo and pHi:
            return pLo + f * (pHi - pLo), 1.0
        if pHi:
            return float(pHi), f
        if pLo:
            return float(pLo), 1.0 - f
        return None
    t = taus[-1]
    if t.synthetic and t.pressureMb and abs(epoch - t.epoch) < 1:
        return float(t.pressureMb), 1.0
    return None


def extensionRowsFromVarDict(varDict, nRows, refEpoch):
    """The dialog's rows as points.  Returns (points, problems); a row
    with no latitude is an empty row, not a problem."""
    points, problems = [], []
    for k in range(1, nRows + 1):
        get = lambda name: str(varDict.get(EXT_FIELDS[name] % k, "") or "")
        if not get("lat").strip():
            continue
        try:
            p = {"epoch": parseValidTime(get("valid"), refEpoch),
                 "lat": parseCoord(get("lat"), "lat"),
                 "lon": parseCoord(get("lon"), "lon"),
                 "vmax": float(get("vmax")),
                 "r34": parseRadii(get("r34")),
                 "extratropical": get("et").strip() == "Yes"}
            if p["lon"] is None:
                raise ValueError("no longitude")
            pressure = get("pressure").strip()
            p["pressureMb"] = float(pressure) if pressure else None
            if p["pressureMb"] is not None and \
                    not 850.0 <= p["pressureMb"] <= 1050.0:
                raise ValueError("pressure %s mb out of range" % pressure)
            if not 0.0 <= p["vmax"] <= 200.0:
                raise ValueError("max wind %s kt out of range"
                                 % get("vmax"))
        except ValueError as exc:
            problems.append("point %d: %s" % (k, exc))
            continue
        points.append(p)
    return points, problems


# Dialog labels for one row; varDict is keyed by label, so each carries the
# row number.
EXT_FIELDS = {
    "valid": "%d  valid DDHHMM Z:",
    "lat": "%d  lat (38.5N):",
    "lon": "%d  lon (165.0E / 170.0W):",
    "vmax": "%d  max wind kt:",
    "pressure": "%d  central pressure mb (optional):",
    "r34": "%d  34 kt radii NE SE SW NW nm:",
    "et": "%d  extratropical:",
}


if _IN_GFE:

    class Procedure(SmartScript.SmartScript):

        def __init__(self, dbss):
            SmartScript.SmartScript.__init__(self, dbss)

        # -------------------------------------------------------------
        # Dialog
        # -------------------------------------------------------------

        def _buildVarDict(self):
            basinList = list(BASIN_LABELS)

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

            # [doc 52]
            VariableList += [
                ("Select the basin to process:", "", "label"),
                # [doc 53]
                ("Basin:", DEFAULT_BASIN, "radio", basinList),
                ("  ", "", "label"),
                ("Choose where to write the output:", "", "label"),
                ("Write to:", "Preview grid", "radio",
                 ["Preview grid", "Fcst Wind"]),
                ("Run over selected time range only?", "No", "radio",
                 ["Yes", "No"]),
                # [doc 54]
                ("Subtropical / extratropical systems:",
                 "Include" if INSERT_AFTER_SUBTROPICAL else "Skip", "radio",
                 ["Include", "Skip"]),
                # pmsl goes where Wind goes: preview or Fcst.
                (PMSL_LABEL, "Yes", "radio", ["Yes", "No"]),
                # [doc 67]
                (EXTENSION_LABEL, "Use saved", "radio",
                 ["Use saved", "Edit", "Off"]),
            ]

            if EXPERIMENTAL and REQUIRE_ACKNOWLEDGEMENT:
                VariableList += [
                    ("   ", "", "label"),
                    ("I understand this tool is experimental and I have "
                     "reviewed the output:", "No", "radio", ["No", "Yes"]),
                ]

            VariableList += [
                ("    ", "", "label"),
                ("Testing only:", "", "label"),
                (TEST_CASE_LABEL, "No", "radio", ["No", "Yes"]),
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
            """Bulletin text, preferring the in-process text database."""
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
            """Start and end of a time range in unix seconds."""
            try:
                return (tr.startTime().unixTime(), tr.endTime().unixTime())
            except AttributeError:
                pass
            try:
                return (tr.getStart().getTime() // 1000,
                        tr.getEnd().getTime() // 1000)
            except AttributeError:
                raise TypeError("Unrecognized time range object: %r" % (tr,))

        def _fcstInventory(self, activeTR, element="Wind"):
            """Existing Fcst time ranges of `element` overlapping activeTR."""
            inv = []

            try:
                infos = self.getGridInfo("Fcst", element, "SFC", activeTR)
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
                        self.getWEInventory("Fcst", element, "SFC", activeTR))
                except TypeError:
                    inv = list(self.getWEInventory("Fcst", element, "SFC"))
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
            """Write a vector grid, creating a temporary parm if previewing."""
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
            """Ring straddling the edge of the inserted region."""
            fp = np.zeros(footprint.shape, dtype=np.float32)
            fp[footprint] = 1.0
            smoothed = self._smooth(fp, int(factor))
            return (smoothed < 1.0) & (smoothed > 0.0) & (~coreMask)

        # [doc 69]
        def _askExtension(self, storm, saved):
            """The days 6-7 dialog for one storm.

            Returns (points, problems), or None if the forecaster cancelled.
            Rows are pre-filled with the saved points still past the
            warning, then offered at EXTENSION_HOURS after its initial time;
            a row left without a latitude is no point.
            """
            taus = storm["taus"]
            t0, last = taus[0].epoch, taus[-1].epoch
            nRows = len(EXTENSION_HOURS)
            rows = [p for p in sorted(saved, key=lambda q: q["epoch"])
                    if p["epoch"] > last][:nRows]
            taken = set(p["epoch"] for p in rows)
            for h in EXTENSION_HOURS:
                if len(rows) >= nRows:
                    break
                when = t0 + h * 3600
                if when > last and when not in taken:
                    rows.append({"epoch": when})
            rows.sort(key=lambda q: q["epoch"])

            VariableList = [
                ("%s - warning ends %s" % (
                    describeStorm(storm["header"]),
                    time.strftime("%d/%H%MZ", time.gmtime(last))), "",
                 "label"),
                ("Leave a row's latitude blank to drop that point.", "",
                 "label"),
            ]
            for k, p in enumerate(rows, 1):
                fill = lambda key, fmt: fmt(p[key]) \
                    if p.get(key) is not None else ""
                VariableList += [
                    (" " * k, "", "label"),
                    (EXT_FIELDS["valid"] % k,
                     time.strftime("%d%H%M", time.gmtime(p["epoch"])),
                     "alphaNumeric"),
                    (EXT_FIELDS["lat"] % k,
                     fill("lat", lambda v: formatCoord(v, "lat")),
                     "alphaNumeric"),
                    (EXT_FIELDS["lon"] % k,
                     fill("lon", lambda v: formatCoord(v, "lon")),
                     "alphaNumeric"),
                    (EXT_FIELDS["vmax"] % k, fill("vmax", "%.0f".__mod__),
                     "alphaNumeric"),
                    (EXT_FIELDS["pressure"] % k,
                     fill("pressureMb", "%.0f".__mod__), "alphaNumeric"),
                    (EXT_FIELDS["r34"] % k,
                     fill("r34", lambda r: " ".join(
                         "%.0f" % r[q] for q in QUADS)), "alphaNumeric"),
                    (EXT_FIELDS["et"] % k,
                     "Yes" if p.get("extratropical") else "No", "radio",
                     ["No", "Yes"]),
                ]
            answers = {}
            pvl = ProcessVariableList.ProcessVariableList(
                "Days 6-7: %s" % describeStorm(storm["header"]),
                VariableList, answers, None)
            if pvl.status() != "OK":
                return None
            return extensionRowsFromVarDict(answers, len(rows), t0)

        def _extendStorms(self, storms, mode, nowSecs):
            """Append the forecaster's points to each live storm's track.

            Returns (summary, cancelled).  "Use saved" applies what is on
            file; "Edit" shows the dialog per storm and saves what comes
            back.  Points the warning now covers are dropped from the file.
            """
            store = loadExtensions()
            notes, changed = [], False
            for s in storms:
                key = stormKey(s["header"], s["pil"])
                entry = store.get(key) or {}
                saved = entry.get("points") or []
                if mode == "Edit":
                    asked = self._askExtension(s, saved)
                    if asked is None:
                        return "", True
                    saved, problems = asked
                    for problem in problems:
                        notes.append("%s %s - skipped" % (key, problem))
                    changed = True
                if not saved:
                    continue
                taus, used, dropped = extendTrack(s["taus"], saved)
                if dropped:
                    changed = True
                if used:
                    s["taus"] = taus
                    et = sum(1 for p in used if p.get("extratropical"))
                    notes.append("%s extended to %s with %d forecaster "
                                 "point(s)%s" % (
                                     key, time.strftime(
                                         "%d/%HZ",
                                         time.gmtime(taus[-1].epoch)),
                                     len(used), ", %d extratropical" % et
                                     if et else ""))
                store[key] = {"name": TCPressureName(s["header"]),
                              "saved": nowSecs, "points": used}
            if changed or mode == "Edit":
                problem = saveExtensions(store, nowSecs=nowSecs)
                if problem:
                    notes.append(problem)
            return ("; ".join(notes) + ".") if notes else "", False

        def _storePmsl(self, data, tr, preview):
            """Write a pmsl grid, to a temporary parm if previewing."""
            if preview:
                lo, hi = PMSL_PREVIEW_LIMITS_MB
                try:
                    self.createGrid(
                        "Fcst", PMSL_PREVIEW_ELEMENT, "SCALAR", data, tr,
                        descriptiveName="JTWC TC pmsl (preview)",
                        precision=1, minAllowedValue=lo,
                        maxAllowedValue=hi, units="mb")
                    return
                except TypeError:
                    pass
                self.createGrid("Fcst", PMSL_PREVIEW_ELEMENT, "SCALAR",
                                data, tr)
                return
            self.createGrid("Fcst", "pmsl", "SCALAR", data, tr)

        # [doc 65]
        def _movePmsl(self, storms, activeTR, spanStart, spanEnd, preview,
                      insertST, latGrid, lonGrid):
            """Move the storms in every Fcst pmsl grid the warnings cover.

            Returns a status-bar sentence.  Each grid's own vortex is taken
            out where the warning has the storm, and the warning's put in
            at its position and central pressure.  A storm-time below
            34 kt, or subtropical when those are skipped, is left alone, as
            in the Wind grids.  A storm counts when its vortex reaches the
            grid at all: one just south of the grid still has its outer
            isobars in it.
            """
            if TCPressure is None:
                return ("pmsl left alone: TCPressure.py is not installed "
                        "with the GFE utilities.")
            module = sys.modules[__name__]
            warnings = [{"pil": s["pil"], "name": TCPressure.shortName(
                s["header"]), "taus": s["taus"], "header": s["header"]}
                for s in storms]
            tausByName = dict((w["name"], w["taus"]) for w in warnings)

            lo, hi = self._trBounds(activeTR)
            lo, hi = max(lo, spanStart), min(hi, spanEnd + 1)
            inventory = []
            for tr in self._fcstInventory(activeTR, "pmsl"):
                start = self._trBounds(tr)[0]
                if lo <= start < hi:
                    inventory.append(tr)
            if not inventory:
                return ("pmsl left alone: no Fcst pmsl grids inside the "
                        "warnings' valid periods.")

            written, perStorm, edge, problems = 0, {}, set(), []
            # One scale per storm, fixed at the earliest grid with its center
            # on it - for a storm in the grid all along, the one nearest the
            # warning's tau 0 - and carried through the rest.
            scales = {}
            for tr in inventory:
                when = self._trBounds(tr)[0]
                candidates, _notes = TCPressure.stormsAt(
                    warnings, when, module, includeSubtropical=insertST)
                moving = []
                for storm in candidates:
                    if storm["vmax"] < 34.0:
                        continue
                    if not insertST and storm.get("conf", 1.0) < 1.0:
                        continue
                    reach = TCPressure.outerRadius(storm)
                    near = TCPressure.distanceNm(latGrid, lonGrid,
                                                 storm["lat"], storm["lon"])
                    if float(np.min(near)) <= reach:
                        moving.append(storm)
                if not moving:
                    continue
                for storm in moving:
                    if storm["name"] in scales:
                        storm["scale"], storm["scaleNote"] = \
                            scales[storm["name"]]
                    # [doc 70]
                    target = pressureTargetAt(tausByName[storm["name"]],
                                              when)
                    if target is not None:
                        storm["pressureTarget"] = target

                pmsl = self.getGrids("Fcst", "pmsl", "SFC", tr,
                                     mode="First", noDataError=0)
                if pmsl is None:
                    continue
                try:
                    out, report = TCPressure.relocateStorms(
                        np.asarray(pmsl, dtype=float), latGrid, lonGrid,
                        moving)
                except Exception as exc:
                    problems.append("%s: %s" % (
                        time.strftime("%d/%HZ", time.gmtime(when)), exc))
                    continue
                self._storePmsl(out.astype(np.float32), tr, preview)
                written += 1

                for e in report:
                    # Only from a grid the center is on: off it, the
                    # environment under the "warning position" is just the
                    # nearest edge point.
                    if e["onField"]:
                        scales.setdefault(e["name"],
                                          (e["scale"], e["anchorNote"]))
                    rec = perStorm.setdefault(
                        e["name"], {"grids": 0, "off": [], "central": [],
                                    "unanchored": set()})
                    rec["grids"] += 1
                    if e["onField"]:
                        rec["central"].append(e["centralMb"])
                    if e["offsetNm"] is not None:
                        rec["off"].append(e["offsetNm"])
                    elif e["onField"]:
                        edge.add(e["name"])
                    if "unanchored" in (e.get("anchorNote") or ""):
                        rec["unanchored"].add(e["anchorNote"])

            if not written:
                return ("pmsl left alone: no storm reaches the grid at the "
                        "times of the Fcst pmsl grids.")

            where = "%s preview grids" % PMSL_PREVIEW_ELEMENT if preview \
                else "Fcst pmsl grids"
            parts = []
            for name, rec in perStorm.items():
                bits = ["%d grids" % rec["grids"]]
                if rec["central"]:
                    bits.append("%.0f-%.0f mb" % (min(rec["central"]),
                                                  max(rec["central"])))
                if rec["off"]:
                    bits.append("grid's own low %.0f-%.0f nm off" % (
                        min(rec["off"]), max(rec["off"])))
                bits.extend(sorted(rec["unanchored"]))
                parts.append("%s (%s)" % (name, ", ".join(bits)))
            msg = "Moved the storms in %d %s: %s." % (
                written, where, "; ".join(parts))
            if edge:
                msg += (" No low of the grid's own found near %s at some "
                        "times - added to the background as it stands; "
                        "check for a second low there." %
                        ", ".join(sorted(edge)))
            if problems:
                msg += " pmsl problems: " + "; ".join(problems) + "."
            return msg

        # -------------------------------------------------------------
        # Main
        # -------------------------------------------------------------

        def execute(self, editArea, timeRange, varDict):
            # editArea is accepted because GFE passes it, and ignored.

            if varDict is None:
                varDict = self._buildVarDict()
                if varDict is None:
                    return

            testCase = varDict.get(TEST_CASE_LABEL, "No") == "Yes"

            # One basin per run.  An unrecognised or missing value falls
            # back to the default rather than silently reading nothing.
            basin = varDict.get("Basin:") or DEFAULT_BASIN
            pils = list(BASIN_PILS.get(basin, BASIN_PILS[DEFAULT_BASIN]))

            # [doc 55]
            if not pils and not testCase:
                self.statusBarMsg("No bulletins selected.", "S")
                return

            preview = varDict.get("Write to:", "Preview grid") == "Preview grid"

            # [doc 56]
            forcedPreviewMsg = ""
            if testCase and not preview:
                preview = True
                forcedPreviewMsg = "Test case always writes to the preview grid. "

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

            # Needed by the test-case track translation below, so this is
            # fetched before the storms are collected rather than after, as
            # a live-bulletin-only run used to do.
            latGrid, lonGrid = self.getLatLonGrids()

            # --- collect every bulletin with a live storm in it -------
            storms = []
            # Per-run override of INSERT_AFTER_SUBTROPICAL.
            insertST = varDict.get(
                "Subtropical / extratropical systems:",
                "Include" if INSERT_AFTER_SUBTROPICAL else "Skip") == "Include"

            stale = []
            problems = []
            if testCase:
                taus, header = parseJTWC(TEST_CASE_BULLETIN)
                taus, header = _rebaseTestCaseTrack(
                    taus, header, nowSecs, latGrid, lonGrid)
                storms.append(
                    {"pil": "TESTCASE", "taus": taus, "header": header})
            else:
                for pil in pils:
                    raw = self._retrieveBulletin(pil)
                    if not raw:
                        continue          # empty slot, entirely normal
                    try:
                        # [doc 57]
                        taus, header, _kind = parseBulletin(raw, nowSecs)
                    except Exception as exc:
                        problems.append("%s: %s" % (pil, exc))
                        continue
                    if len(taus) < 2:
                        problems.append("%s: only %d usable forecast times"
                                        % (pil, len(taus)))
                        continue

                    # textdb hands back whatever was last stored under this
                    # PIL, so a dissipated storm sits there indefinitely.
                    # Judge the slot by the bulletin's own analysis time.
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

            # [doc 71]
            # Forecaster points past the warnings.  Missing from an older
            # saved varDict means off.  Never for the test case, which is
            # not a real storm to file points under.
            extensionMsg = ""
            extensionMode = varDict.get(EXTENSION_LABEL, "Off")
            if extensionMode != "Off" and not testCase:
                extensionMsg, cancelled = self._extendStorms(
                    storms, extensionMode, nowSecs)
                if cancelled:
                    self.statusBarMsg("Cancelled at the days 6-7 dialog; "
                                      "nothing written.", "S")
                    return
                if extensionMsg:
                    extensionMsg = " " + extensionMsg

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

            # [doc 58]
            if not preview:
                self._fragment(activeTR)

            # [doc 59]
            interval = OUTPUT_GRID_INTERVAL_SECONDS
            seriesLo = (int(spanStart) // interval) * interval
            seriesHi = -(-int(spanEnd) // interval) * interval  # ceil

            if selectedTimeOnly:
                # [doc 60]
                trLo, trHi = self._trBounds(activeTR)
                seriesLo = max(seriesLo, -(-int(trLo) // interval) * interval)
                seriesHi = min(seriesHi, (int(trHi) // interval) * interval)

            series = []
            when = seriesLo
            while when <= seriesHi:
                series.append(when)
                when += interval

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
                    if not insertST and snap.conf < 1.0:
                        return None, True, 0
                    if snap.vmax < 34.0:
                        # [doc 61]
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

            # [doc 62]
            for when in series:
                tr = TimeRange.TimeRange(
                    AbsTime.AbsTime(int(when)),
                    AbsTime.AbsTime(int(when + interval)))

                built, stFlag, tdCount = buildFor(when, tr)
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

            # [doc 66]
            # Missing from an older saved varDict means no: the pmsl grids
            # are never touched by a run that did not offer the choice.
            pmslMsg = ""
            if varDict.get(PMSL_LABEL, "No") == "Yes":
                pmslMsg = " " + self._movePmsl(
                    storms, activeTR, spanStart, spanEnd, preview, insertST,
                    latGrid, lonGrid)

            if not written:
                msg = "Parsed %d live bulletin(s), but no Fcst Wind grids " \
                      "fell inside their valid periods." % len(storms)
                if testCase:
                    msg = "TEST CASE (not a live storm). " + msg
                self.statusBarMsg(msg + extensionMsg + pmslMsg, "S")
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
            intervalHours = interval // 3600
            msg = ""
            if testCase:
                msg += "TEST CASE (not a live storm). "
            if forcedPreviewMsg:
                msg += forcedPreviewMsg
            msg += "v%s. " % VERSION
            if EXPERIMENTAL:
                msg += "EXPERIMENTAL, verify before use. "
            # [doc 63]
            msg += "Wrote %d %d-hourly %s. " % (
                written, intervalHours, where) + "; ".join(parts) + "."
            msg += " Peak wind written %.0f kt vs bulletin max %.0f kt." % (
                peakWritten, bulletinPeak)
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
            self.statusBarMsg(msg + extensionMsg + pmslMsg, "R")


# ---------------------------------------------------------------------------
# Standalone parser test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python TCWind_JTWC.py <bulletin.txt>")
        sys.exit(1)

    with open(sys.argv[1]) as fh:
        text = fh.read()

    taus, header, kind = parseBulletin(text)
    print("product: %s" % ("NHC/CPHC TCM" if kind == "tcm"
                           else "JTWC WTPN warning"))
    print("system: %s" % describeStorm(header))
    if header.get("basin"):
        print("basin: %s" % header["basin"])
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
