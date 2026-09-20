#!/usr/bin/env python3
"""End-to-end harness test for GFE/procedures/TCWind_JTWC.py's `Procedure`.

`Procedure` only exists when the AWIPS `SmartScript`/`ProcessVariableList`/
`TimeRange`/`AbsTime` modules import cleanly (`_IN_GFE`), so it has never
run anywhere near a real test. This script fakes the minimum surface those
modules provide, imports TCWind_JTWC.py fresh against the fakes so
`_IN_GFE` comes up True and `Procedure` gets defined, then drives
`Procedure.execute()` exactly the way GFE would: with a fully-built
varDict (bypassing the interactive dialog), a real parsed bulletin behind
`getTextProductFromDB`, a synthetic lat/lon grid and background wind, and
an inventory of pre-existing "Fcst Wind" blocks.

`Procedure.execute()` writes its own fixed `OUTPUT_GRID_INTERVAL_SECONDS`
-wide (3-hourly, by default) time series across the whole bulletin span,
independent of the background Fcst Wind inventory's own block boundaries
or cadence - so several cases here deliberately build a background
inventory that is narrower than the bulletin's span, or mixes 3-hourly
and 6-hourly blocks, to prove the written grids' own timing never takes
its cue from that inventory.

    python3 test_procedure_harness.py
"""
import os
import sys
import time
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# Repo layout: this file lives at tests/tcwind_jtwc/, and the procedure is
# two levels up and back down at GFE/procedures/. AWIPS export bundle layout
# (see tools/export_awips.py): this file is copied to selfcheck/ inside the
# bundle, and the procedure sits one level up at the bundle root instead.
# Try the repo layout first and fall back to the bundle root, so this exact
# file runs unmodified in both places.
_REPO_PROC_DIR = os.path.join(HERE, "..", "..", "GFE", "procedures")
_BUNDLE_PROC_DIR = os.path.join(HERE, "..")
if os.path.isfile(os.path.join(_REPO_PROC_DIR, "TCWind_JTWC.py")):
    PROC_DIR = _REPO_PROC_DIR
else:
    PROC_DIR = _BUNDLE_PROC_DIR

# Fixtures live alongside this file in both layouts: tests/tcwind_jtwc/
# fixtures/ in the repo, selfcheck/fixtures/ in the exported bundle.
FIXTURES = os.path.join(HERE, "fixtures")


# ---------------------------------------------------------------------------
# Fake AWIPS/GFE modules, installed into sys.modules before TCWind_JTWC.py
# is imported so its `import SmartScript` etc. at module scope succeed and
# `_IN_GFE` becomes True.
# ---------------------------------------------------------------------------

def _install_fake_awips_modules():
    # --- AbsTime ------------------------------------------------------
    abstime_mod = types.ModuleType("AbsTime")

    class _FakeAbsTime(object):
        def __init__(self, epoch):
            self._epoch = int(epoch)

        def unixTime(self):
            return self._epoch

        def timetuple(self):
            return time.gmtime(self._epoch)

        def __repr__(self):
            return "AbsTime(%d)" % self._epoch

    abstime_mod.AbsTime = _FakeAbsTime
    sys.modules["AbsTime"] = abstime_mod

    # --- TimeRange ------------------------------------------------------
    timerange_mod = types.ModuleType("TimeRange")

    class _FakeTimeRange(object):
        def __init__(self, start, end):
            self._start = start
            self._end = end

        def startTime(self):
            return self._start

        def endTime(self):
            return self._end

        def duration(self):
            return self._end.unixTime() - self._start.unixTime()

        def __repr__(self):
            return "TimeRange(%r, %r)" % (self._start, self._end)

    timerange_mod.TimeRange = _FakeTimeRange
    sys.modules["TimeRange"] = timerange_mod

    # --- ProcessVariableList ---------------------------------------------
    # Never actually invoked by these tests (varDict is always passed in
    # directly, so Procedure._buildVarDict() / the interactive dialog path
    # is never reached), but TCWind_JTWC.py imports it at module scope.
    pvl_mod = types.ModuleType("ProcessVariableList")

    class _FakeProcessVariableList(object):
        def __init__(self, *args, **kwargs):
            pass

        def status(self):
            return "OK"

    pvl_mod.ProcessVariableList = _FakeProcessVariableList
    sys.modules["ProcessVariableList"] = pvl_mod

    # --- SmartScript ------------------------------------------------------
    smartscript_mod = types.ModuleType("SmartScript")
    smartscript_mod.SmartScript = _FakeSmartScriptBase
    sys.modules["SmartScript"] = smartscript_mod


class _FakeGridInfo(object):
    """Stand-in for whatever getGridInfo() normally returns; Procedure
    only ever calls .gridTime() on it."""

    def __init__(self, tr):
        self._tr = tr

    def gridTime(self):
        return self._tr


class _FakeSmartScriptBase(object):
    """Fakes exactly the SmartScript surface Procedure.execute() touches.

    Configured after construction (configure()) rather than via __init__,
    since Procedure.__init__ controls the constructor call
    (`SmartScript.SmartScript.__init__(self, dbss)`).
    """

    def __init__(self, dbss):
        self.dbss = dbss
        self.messages = []     # [(level, msg), ...]
        self.created = []      # [(args, kwargs) to createGrid, ...]
        self.fragment_calls = []
        self.texts = {}        # pil -> bulletin text
        self._now_epoch = None
        self._inv_start = None
        self._inv_end = None
        self._inv_step = 3 * 3600
        self._inv_blocks = None
        self._lat = None
        self._lon = None

    def configure(self, texts, now_epoch, inv_start, inv_end,
                 lat, lon, inv_step=3 * 3600, inv_blocks=None):
        """`inv_blocks`, when given, is an explicit list of (start_epoch,
        end_epoch) tuples used verbatim as the fake Fcst Wind inventory -
        for building a mixed-cadence inventory (part 3-hourly, part
        6-hourly) that the uniform inv_start/inv_end/inv_step generator
        below can't express. `inv_start`/`inv_end`/`inv_step` are then
        unused (still required as positional-friendly args for callers that
        don't need the explicit form)."""
        self.texts = texts
        self._now_epoch = now_epoch
        self._inv_start = inv_start
        self._inv_end = inv_end
        self._inv_step = inv_step
        self._inv_blocks = inv_blocks
        self._lat = lat
        self._lon = lon

    # ---- text database ---------------------------------------------------
    def getTextProductFromDB(self, pil):
        return self.texts.get(pil)

    # ---- status ---------------------------------------------------------
    def statusBarMsg(self, msg, level):
        self.messages.append((level, msg))

    # ---- time -----------------------------------------------------------
    def _gmtime(self):
        import AbsTime
        return AbsTime.AbsTime(self._now_epoch)

    def createTimeRange(self, startHr, endHr, zone="Zulu"):
        import AbsTime
        import TimeRange
        dayStart = (self._now_epoch // 86400) * 86400
        return TimeRange.TimeRange(
            AbsTime.AbsTime(dayStart + startHr * 3600),
            AbsTime.AbsTime(dayStart + endHr * 3600))

    # ---- grid inventory / data --------------------------------------------
    def getGridInfo(self, model, elem, level, tr):
        import AbsTime
        import TimeRange
        out = []
        if self._inv_blocks is not None:
            for start, end in self._inv_blocks:
                blockTR = TimeRange.TimeRange(
                    AbsTime.AbsTime(start), AbsTime.AbsTime(end))
                out.append(_FakeGridInfo(blockTR))
            return out
        cur = self._inv_start
        while cur < self._inv_end:
            blockTR = TimeRange.TimeRange(
                AbsTime.AbsTime(cur), AbsTime.AbsTime(cur + self._inv_step))
            out.append(_FakeGridInfo(blockTR))
            cur += self._inv_step
        return out

    def getLatLonGrids(self):
        return self._lat, self._lon

    def getGrids(self, model, elem, level, tr, mode="First", noDataError=0):
        # 10 kt westerlies (wind FROM the west -> direction 270, met
        # convention, matching magDirToUV()'s -sin/-cos construction).
        shape = self._lat.shape
        mag = np.full(shape, 10.0, dtype=np.float32)
        direc = np.full(shape, 270.0, dtype=np.float32)
        return mag, direc

    def createGrid(self, *args, **kwargs):
        self.created.append((args, kwargs))

    # ---- fragmentation -----------------------------------------------------
    def fragmentCmd(self, elements, tr):
        self.fragment_calls.append((tuple(elements), tr))

    # Deliberately no smoothGrid(): Procedure._smooth() must fall back to
    # boxSmooth() when hasattr(self, "smoothGrid") is False.


# ---------------------------------------------------------------------------
# Import TCWind_JTWC.py fresh, against the fakes.
# ---------------------------------------------------------------------------

def _import_tcwind_jtwc():
    _install_fake_awips_modules()
    if PROC_DIR not in sys.path:
        sys.path.insert(0, PROC_DIR)
    sys.modules.pop("TCWind_JTWC", None)
    import importlib
    tc = importlib.import_module("TCWind_JTWC")
    return tc


tc = _import_tcwind_jtwc()

if not tc._IN_GFE:
    print("FAIL   _IN_GFE is False after installing fake AWIPS modules; "
         "Procedure was never defined. Aborting.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Grid / fixture plumbing shared by both cases.
# ---------------------------------------------------------------------------

def _mesh(n=120, basin="West Pac"):
    """A grid domain wide enough for the basin's fixture tracks.

    West Pac is 15-35N, 120-140E - the original domain, unchanged, so every
    pre-existing case grids exactly where it always did. Atlantic covers the
    LEE fixture's 22-34N, 62-67W track. An Atlantic storm run on the West
    Pac mesh lands entirely off-grid and writes nothing, which reads as a
    pass rather than the miss it is.
    """
    if basin == "Atlantic":
        lats = np.linspace(15.0, 40.0, n, dtype=np.float32)
        lons = np.linspace(-75.0, -50.0, n, dtype=np.float32)
    else:
        lats = np.linspace(15.0, 35.0, n, dtype=np.float32)
        lons = np.linspace(120.0, 140.0, n, dtype=np.float32)
    lonGrid, latGrid = np.meshgrid(lons, lats)
    return latGrid.astype(np.float32), lonGrid.astype(np.float32)


def _load_fixture(name):
    """Find a fixture in the repo layout or the exported bundle's flat one.

    In the repo, TCM products live in fixtures/tcm/ so the WTPN-only globs
    elsewhere never pick them up; the AWIPS bundle copies every fixture flat
    into selfcheck/fixtures/. Trying both keeps one harness working in both.
    """
    for path in (os.path.join(FIXTURES, name),
                 os.path.join(FIXTURES, "tcm", name)):
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
    raise IOError("fixture not found in either layout: %s" % name)


def _run(pil, fixture_name, inv_stop_hours, basin="West Pac"):
    """Parse `fixture_name`, run Procedure.execute() against it under
    `pil`, with a pre-existing Fcst Wind inventory of 3-hourly blocks
    running from the bulletin's analysis time out to `inv_stop_hours`
    hours after it (None = cover the whole bulletin). Returns
    (proc, taus, header).

    parseBulletin(), not parseJTWC(): the procedure dispatches on the text
    rather than the PIL, so the harness exercises the same path or it only
    ever proves the JTWC half works.
    """
    text = _load_fixture(fixture_name)
    taus, header, _kind = tc.parseBulletin(text)

    analysisEpoch = taus[0].epoch
    lastEpoch = taus[-1].epoch
    nowEpoch = analysisEpoch + 3 * 3600   # 3h after analysis: not stale

    if inv_stop_hours is None:
        invEnd = lastEpoch + 3 * 3600
    else:
        invEnd = analysisEpoch + inv_stop_hours * 3600 + 3 * 3600

    latGrid, lonGrid = _mesh(basin=basin)

    proc = tc.Procedure(dbss=None)
    proc.configure(
        texts={pil: text},
        now_epoch=nowEpoch,
        inv_start=analysisEpoch,
        inv_end=invEnd,
        lat=latGrid,
        lon=lonGrid)

    varDict = {
        "Basin:": basin,
        "Write to:": "Fcst Wind",
        "Run over selected time range only?": "No",
        "I understand this tool is experimental and I have reviewed "
        "the output:": "Yes",
    }

    proc.execute(None, None, varDict)
    return proc, taus, header


def _final_status(proc):
    return proc.messages[-1][1] if proc.messages else ""


def _peak_written_kt(proc):
    peak = 0.0
    for args, _kwargs in proc.created:
        # createGrid(model, element, type_, data, tr, ...); data is
        # (mag, dir) for a VECTOR grid, which is the only kind this
        # procedure ever writes.
        data = args[3]
        mag = data[0]
        peak = max(peak, float(np.asarray(mag).max()))
    return peak


def _run_test_case(write_to, ack="No", now_epoch=None):
    """Run Procedure.execute() with the "Run test case (no live storm
    needed):" toggle set to "Yes" - no fixture, no textdb, the procedure's
    own bundled TEST_CASE_BULLETIN. Builds a Fcst Wind inventory (3-hourly,
    same convention as _run()) wide enough to cover the rebased track,
    computed from TEST_CASE_BULLETIN's own (pre-rebase) span so this stays
    correct if the bundled bulletin ever changes.

    Returns (proc, origTaus, nowEpoch, latGrid, lonGrid). origTaus is the
    freshly, independently parsed (never rebased) TEST_CASE_BULLETIN, for
    computing expectations (bulletin peak Vmax, track duration) without
    depending on the procedure's internal state.
    """
    origTaus, _origHeader = tc.parseJTWC(tc.TEST_CASE_BULLETIN)
    if now_epoch is None:
        now_epoch = int(time.time())

    expectedAnalysis = now_epoch - 3 * 3600
    duration = origTaus[-1].epoch - origTaus[0].epoch
    expectedLast = expectedAnalysis + duration

    latGrid, lonGrid = _mesh()

    proc = tc.Procedure(dbss=None)
    proc.configure(
        texts={},
        now_epoch=now_epoch,
        inv_start=expectedAnalysis,
        inv_end=expectedLast + 3 * 3600,
        lat=latGrid,
        lon=lonGrid)

    varDict = {
        tc.TEST_CASE_LABEL: "Yes",
        "Basin:": "West Pac",   # ignored: the test case never reads textdb
        "Write to:": write_to,
        "Run over selected time range only?": "No",
        "I understand this tool is experimental and I have reviewed "
        "the output:": ack,
    }

    proc.execute(None, None, varDict)
    return proc, origTaus, now_epoch, latGrid, lonGrid


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def case_krovanh_full_span_3_hourly():
    """Real, live bulletin with full quadrant radii (Tropical Storm
    22W/KROVANH). The fake background Fcst Wind inventory deliberately
    covers only part of the bulletin's span - 3-hourly from the analysis
    time out to 96h, stopping one tau group short of the bulletin's last
    forecast hour (120h) - so the fixed-interval series has to write
    blocks over a stretch the background inventory doesn't natively have
    at all. The point: the written grids come out complete and uniformly
    3-hourly across the WHOLE 0-120h span regardless, because this tool
    computes its own time series rather than following the background's
    block boundaries."""
    fails = []

    proc, taus, header = _run(
        "NFDTCPWP1", "real_2026-09-02_wtpn31_krovanh.txt", inv_stop_hours=96)

    if not proc.created:
        fails.append("no grids were written at all")

    bulletinPeak = max(t.vmax for t in taus)
    peak = _peak_written_kt(proc)
    if abs(peak - bulletinPeak) > 3.0:
        fails.append("peak written %.1f kt not within 3 kt of bulletin "
                     "max %.1f kt" % (peak, bulletinPeak))

    interval = tc.OUTPUT_GRID_INTERVAL_SECONDS
    written = {}
    for args, _kwargs in proc.created:
        tr = args[4]
        start = tr.startTime().unixTime()
        end = tr.endTime().unixTime()
        written[start] = end - start

    for start, dur in written.items():
        if dur != interval:
            fails.append("block starting at %d has duration %d s, not the "
                         "fixed %d s interval" % (start, dur, interval))
        if start % interval != 0:
            fails.append("block start %d is not a multiple of the %d s "
                         "interval" % (start, interval))

    # The series must cover the WHOLE bulletin span (0-120h), including
    # the 96h-120h stretch the background inventory never had any blocks
    # in at all - proving this tool's own time series, not the
    # background's coverage, decides what gets written.
    spanStart, spanEnd = taus[0].epoch, taus[-1].epoch
    expected = set(range(spanStart, spanEnd + 1, interval))
    missing = expected - set(written)
    if missing:
        fails.append("missing 3-hourly blocks at %r; the fixed-interval "
                     "series must cover the whole span regardless of what "
                     "the background inventory covers"
                     % [time.strftime("%d/%H%MZ", time.gmtime(w))
                        for w in sorted(missing)])

    stormName = header.get("stormName") or ""
    finalMsg = _final_status(proc)
    if not stormName or stormName not in finalMsg:
        fails.append("final status does not mention the storm (%r): %r"
                     % (stormName, finalMsg))
    if "3-hourly" not in finalMsg:
        fails.append("final status does not mention the 3-hourly cadence "
                     "it wrote at: %r" % finalMsg)

    return fails, proc


def case_mixed_cadence_background_still_writes_3_hourly():
    """Regression case for the "grids get created in random 3 or 6 hour
    chunks" bug report: a fake Fcst Wind inventory that is 3-hourly out to
    72h and 6-hourly from 72h to 90h - mirroring real office practice and
    the KROVANH fixture's own tau spacing (12-hourly out to 72h, 24-hourly
    beyond) - with two deliberate gaps (no block starting at 60h, and the
    6-hourly run stopping short of 96h) so the background inventory itself
    can't be mistaken for a complete source of block boundaries either.

    An earlier fix keyed each created block's duration off whatever
    cadence was locally in effect in this same mixed inventory, so a
    block created in the 3-hourly region came out 3-hourly and one
    created in the 6-hourly region came out 6-hourly - which was still
    wrong, just differently: the OFFICE'S inventory, not this bulletin,
    was deciding the tool's own output granularity, and which region a
    given created block landed in could shift run to run. Under the
    fixed design there is no such lookup at all: every block this run
    writes, everywhere across the whole span, must come out with the
    fixed OUTPUT_GRID_INTERVAL_SECONDS duration and a start on that
    interval's own boundary, regardless of what duration the nearest
    background block happens to have. This asserts that for EVERY block
    the run actually writes, not just the two taus the old test singled
    out."""
    fails = []

    text = _load_fixture("real_2026-09-02_wtpn31_krovanh.txt")
    taus, header = tc.parseJTWC(text)
    analysisEpoch = taus[0].epoch
    nowEpoch = analysisEpoch + 3 * 3600

    invBlocks = []
    t = analysisEpoch
    for _ in range(24):     # 0h .. 72h, 3-hourly
        if t == analysisEpoch + 60 * 3600:
            t += 3 * 3600
            continue        # the deliberate gap: no block starts at 60h
        invBlocks.append((t, t + 3 * 3600))
        t += 3 * 3600
    t = analysisEpoch + 72 * 3600
    for _ in range(3):      # 72h, 78h, 84h - stop short of 96h
        invBlocks.append((t, t + 6 * 3600))
        t += 6 * 3600

    latGrid, lonGrid = _mesh()

    proc = tc.Procedure(dbss=None)
    proc.configure(
        texts={"NFDTCPWP1": text},
        now_epoch=nowEpoch,
        inv_start=None,
        inv_end=None,
        lat=latGrid,
        lon=lonGrid,
        inv_blocks=invBlocks)

    varDict = {
        "Basin:": "West Pac",
        "Write to:": "Fcst Wind",
        "Run over selected time range only?": "No",
        "I understand this tool is experimental and I have reviewed "
        "the output:": "Yes",
    }

    proc.execute(None, None, varDict)

    if not proc.created:
        fails.append("no grids were written at all")

    # Pull (start_epoch, end_epoch, duration) for EVERY grid actually
    # written this run, straight from the fake createGrid recorder's
    # captured TimeRange (args[4], per _storeGrid's call shape) - not just
    # the two taus that happen to sit in each cadence region, since the
    # whole point of the fix is that NEITHER region's cadence has any
    # effect on ANY block this run writes.
    interval = tc.OUTPUT_GRID_INTERVAL_SECONDS
    for args, _kwargs in proc.created:
        tr = args[4]
        start = tr.startTime().unixTime()
        end = tr.endTime().unixTime()
        dur = end - start
        if dur != interval:
            fails.append("block starting at %d has duration %d s; the "
                         "mixed-cadence background inventory must have no "
                         "effect - every block must be the fixed %d s "
                         "interval" % (start, dur, interval))
        if start % interval != 0:
            fails.append("block start %d is not a multiple of the fixed "
                         "%d s interval" % (start, interval))

    return fails, proc


def case_selected_time_range_only_respects_bounds():
    """"Run over selected time range only?" = Yes with a `timeRange`
    narrower than the bulletin's full 0-120h span, and deliberately OFF
    the fixed interval's own boundaries (25h/58h past the analysis time,
    neither a multiple of 3h) to exercise the snap-without-a-fencepost-
    -gap rule: the effective lower bound rounds UP to the next 3-hourly
    boundary (27h) and the upper bound rounds DOWN to the previous one
    (57h). Every block this run writes must start inside the original
    selected range, on a 3-hour boundary, and none may start outside it -
    proving `selectedTimeOnly` still bounds the run the same way it
    always has, now applied to this tool's own fixed-interval series
    rather than to the background inventory's own blocks."""
    fails = []

    import AbsTime
    import TimeRange

    text = _load_fixture("real_2026-09-02_wtpn31_krovanh.txt")
    taus, header = tc.parseJTWC(text)
    analysisEpoch = taus[0].epoch
    lastEpoch = taus[-1].epoch
    nowEpoch = analysisEpoch + 3 * 3600

    interval = tc.OUTPUT_GRID_INTERVAL_SECONDS
    selStart = analysisEpoch + 25 * 3600   # not a 3h boundary
    selEnd = analysisEpoch + 58 * 3600     # not a 3h boundary either

    latGrid, lonGrid = _mesh()

    proc = tc.Procedure(dbss=None)
    proc.configure(
        texts={"NFDTCPWP1": text},
        now_epoch=nowEpoch,
        inv_start=analysisEpoch,
        inv_end=lastEpoch + 3 * 3600,
        lat=latGrid,
        lon=lonGrid)

    selectedTR = TimeRange.TimeRange(
        AbsTime.AbsTime(selStart), AbsTime.AbsTime(selEnd))

    varDict = {
        "Basin:": "West Pac",
        "Write to:": "Fcst Wind",
        "Run over selected time range only?": "Yes",
        "I understand this tool is experimental and I have reviewed "
        "the output:": "Yes",
    }

    proc.execute(None, selectedTR, varDict)

    if not proc.created:
        fails.append("no grids were written at all")

    starts = set()
    for args, _kwargs in proc.created:
        tr = args[4]
        start = tr.startTime().unixTime()
        starts.add(start)
        if start % interval != 0:
            fails.append("block start %d is not a multiple of the %d s "
                         "interval" % (start, interval))
        if start < selStart or start > selEnd:
            fails.append("block starting at %d falls outside the "
                         "selected range [%d, %d]"
                         % (start, selStart, selEnd))

    expectedLo = -(-selStart // interval) * interval   # ceil -> 27h
    expectedHi = (selEnd // interval) * interval        # floor -> 57h
    if expectedLo not in starts:
        fails.append("expected a block at the snapped lower bound %d "
                     "(27h, ceiled up from the selected 25h start); got "
                     "starts %r" % (expectedLo, sorted(starts)))
    if expectedHi not in starts:
        fails.append("expected a block at the snapped upper bound %d "
                     "(57h, floored down from the selected 58h end); got "
                     "starts %r" % (expectedHi, sorted(starts)))

    return fails, proc


def case_saudel():
    """Real, live bulletin with NO wind radii at all (Tropical Depression
    17W/SAUDEL, entirely below 34 kt throughout its forecast). Every tau
    is skipped as sub-tropical-storm strength, so no grid is ever written
    - the assertion here is just that this runs cleanly end to end."""
    fails = []
    try:
        proc, taus, header = _run(
            "NFDTCPWP2", "real_2026-09-02_wtpn32_saudel.txt",
            inv_stop_hours=None)
    except Exception as exc:
        fails.append("execute() raised %r" % (exc,))
        return fails, None

    if not proc.messages:
        fails.append("no status message was ever posted")

    return fails, proc


def case_lee_atlantic_tcm():
    """An NHC Atlantic TCM, end to end: parse, fit, grid, write.

    compare_py_js.py already holds the parser to the JavaScript and
    test_parser_golden.py to a snapshot. Neither shows that a TCM survives
    the REST of the procedure - the basin radio, the vortex fit, the insert
    and the grid writing - on a basin whose longitudes are negative and
    whose forecast hours are not JTWC's neat multiples of 12 (NHC anchors to
    00/12Z synoptic times, so a 15Z advisory runs 0/9/21/33...). HURRICANE
    LEE is strong and well sampled, with radii at all three thresholds, so
    grids are expected here - not merely the absence of a crash.
    """
    fails = []
    try:
        proc, taus, header = _run(
            "MIATCMAT3", "real_2023-09-10_wtnt23_lee.txt",
            inv_stop_hours=None, basin="Atlantic")
    except Exception as exc:
        fails.append("execute() raised %r" % (exc,))
        return fails, None

    if header.get("stormName") != "LEE":
        fails.append("stormName was %r, expected 'LEE'"
                     % header.get("stormName"))
    if header.get("basin") != "AT":
        fails.append("header basin was %r, expected 'AT'"
                     % header.get("basin"))
    if not proc.created:
        fails.append("no grids written for a 105 kt hurricane reporting "
                     "radii at all three thresholds")

    # The written peak has to be in the bulletin's league. Far too low means
    # the storm missed the grid entirely; higher than the bulletin means the
    # vortex overshot.
    peak = _peak_written_kt(proc)
    bulletinMax = max(t.vmax for t in taus)
    if peak < 0.5 * bulletinMax:
        fails.append("peak written %.0f kt is under half the bulletin's "
                     "%.0f kt - is the storm on the grid at all?"
                     % (peak, bulletinMax))
    if peak > bulletinMax + 5.0:
        fails.append("peak written %.0f kt exceeds the bulletin's %.0f kt"
                     % (peak, bulletinMax))

    return fails, proc


def case_test_case_forces_preview_despite_fcst_wind_and_ack():
    """"Run test case" = Yes, "Write to:" = Fcst Wind, acknowledgement =
    Yes. This is the safety-property case: even though the forecaster
    picked Fcst Wind AND acknowledged writing to it, a synthetic test
    storm must never land there - the override has to be enforced in code,
    not just by graying the dialog out. Also checks the track was
    translated onto the fake grid's own center, and that the peak written
    tracks the bundled bulletin's own Vmax."""
    fails = []

    proc, origTaus, nowEpoch, latGrid, lonGrid = _run_test_case(
        write_to="Fcst Wind", ack="Yes")

    if not proc.created:
        fails.append("no grids were written at all")

    finalMsg = _final_status(proc)
    if "TEST CASE" not in finalMsg:
        fails.append("final status does not say TEST CASE: %r" % finalMsg)
    if "Test case always writes to the preview grid." not in finalMsg:
        fails.append("final status does not explain the forced-preview "
                     "override even though Write to: was Fcst Wind and "
                     "the acknowledgement was Yes: %r" % finalMsg)
    if "Fcst Wind grids" in finalMsg:
        fails.append("final status reports writing to real Fcst Wind "
                     "grids: %r" % finalMsg)

    # Code-level safety check on every grid actually written this run: the
    # element name must always be the preview element, and the temporary
    # (createGrid(..., descriptiveName=...)) branch must be the one that
    # ran - _storeGrid() only passes descriptiveName on the temporary
    # (preview) path, so its presence is direct evidence createGrid was
    # never called with temporary=False here.
    for args, kwargs in proc.created:
        element = args[1]
        if element != tc.PREVIEW_ELEMENT:
            fails.append("createGrid called with element %r, not the "
                         "preview element %r" % (element, tc.PREVIEW_ELEMENT))
        if "descriptiveName" not in kwargs:
            fails.append("createGrid call missing descriptiveName kwarg - "
                         "the non-temporary (real Fcst Wind) branch ran: "
                         "args=%r kwargs=%r" % (args, kwargs))

    # The track must be translated so tau 0 sits at the fake grid's own
    # center - computed the same way the procedure does (tc._gridCenterLatLon
    # on the exact grid getLatLonGrids() returned), independently re-run
    # here on a fresh, unrebased parse of TEST_CASE_BULLETIN.
    freshTaus, freshHeader = tc.parseJTWC(tc.TEST_CASE_BULLETIN)
    rebasedTaus, _rebasedHeader = tc._rebaseTestCaseTrack(
        freshTaus, freshHeader, nowEpoch, latGrid, lonGrid)
    clat, clon = tc._gridCenterLatLon(latGrid, lonGrid)
    latCell = abs(float(latGrid[1, 0] - latGrid[0, 0]))
    lonCell = abs(float(lonGrid[0, 1] - lonGrid[0, 0]))
    tol = 0.5 * max(latCell, lonCell)
    tau0 = rebasedTaus[0]
    if abs(tau0.lat - clat) > tol or abs(tau0.lon - clon) > tol:
        fails.append(
            "translated tau-0 (%.3f, %.3f) is not within half a grid cell "
            "(%.4f deg) of the fake grid's own center (%.3f, %.3f)"
            % (tau0.lat, tau0.lon, tol, clat, clon))

    bulletinPeak = max(t.vmax for t in origTaus)
    peak = _peak_written_kt(proc)
    if abs(peak - bulletinPeak) > 5.0:
        fails.append("peak written %.1f kt not within a few kt of the "
                     "bundled bulletin's max %.1f kt" % (peak, bulletinPeak))

    return fails, proc


def case_test_case_preview_default():
    """Lighter case: "Run test case" = Yes with "Write to:" left at its
    normal default, Preview grid. Confirms test mode works there too, not
    only under the forced-override path above."""
    fails = []

    proc, origTaus, _nowEpoch, _latGrid, _lonGrid = _run_test_case(
        write_to="Preview grid", ack="No")

    if not proc.created:
        fails.append("no grids were written at all")

    finalMsg = _final_status(proc)
    if "TEST CASE" not in finalMsg:
        fails.append("final status does not say TEST CASE: %r" % finalMsg)

    for args, _kwargs in proc.created:
        if args[1] != tc.PREVIEW_ELEMENT:
            fails.append("createGrid used element %r, expected preview "
                         "element %r" % (args[1], tc.PREVIEW_ELEMENT))

    bulletinPeak = max(t.vmax for t in origTaus)
    peak = _peak_written_kt(proc)
    if abs(peak - bulletinPeak) > 5.0:
        fails.append("peak written %.1f kt not within a few kt of the "
                     "bundled bulletin's max %.1f kt" % (peak, bulletinPeak))

    return fails, proc


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    cases = [
        ("krovanh_full_span_3_hourly", case_krovanh_full_span_3_hourly),
        ("mixed_cadence_background_still_writes_3_hourly",
         case_mixed_cadence_background_still_writes_3_hourly),
        ("selected_time_range_only_respects_bounds",
         case_selected_time_range_only_respects_bounds),
        ("saudel_weak_no_radii_runs_clean", case_saudel),
        ("lee_atlantic_tcm_end_to_end", case_lee_atlantic_tcm),
        ("test_case_forces_preview_despite_fcst_wind_and_ack",
         case_test_case_forces_preview_despite_fcst_wind_and_ack),
        ("test_case_preview_default", case_test_case_preview_default),
    ]

    failed = 0
    for name, fn in cases:
        try:
            fails, proc = fn()
        except Exception as exc:
            failed += 1
            print("FAIL   %s" % name)
            print("       execute() raised: %r" % (exc,))
            import traceback
            traceback.print_exc()
            continue

        if fails:
            failed += 1
            print("FAIL   %s" % name)
            for f in fails:
                print("       " + f)
        else:
            print("PASS   %s" % name)
        if proc is not None and proc.messages:
            print("       final status: %s" % _final_status(proc))

    print("\n%d case(s), %d failed" % (len(cases), failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
