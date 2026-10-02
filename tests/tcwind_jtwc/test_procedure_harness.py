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
        """Records every dialog; answers from `answers` in turn, where a
        dict fills varDict and "CANCEL" cancels."""
        answers = []
        calls = []

        def __init__(self, title=None, variableList=None, varDict=None,
                     *args, **kwargs):
            _FakeProcessVariableList.calls.append((title, variableList))
            self._status = "OK"
            if _FakeProcessVariableList.answers:
                answer = _FakeProcessVariableList.answers.pop(0)
                if answer == "CANCEL":
                    self._status = "Cancel"
                elif varDict is not None:
                    varDict.update(answer)

        def status(self):
            return self._status

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
        # pmsl: a callable (lat, lon, startEpoch) -> field, and the Fcst
        # pmsl inventory as (start, end) tuples.  None = no pmsl grids.
        self.pmsl_fn = None
        self.pmsl_blocks = None

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
        if elem == "pmsl":
            for start, end in self.pmsl_blocks or ():
                out.append(_FakeGridInfo(TimeRange.TimeRange(
                    AbsTime.AbsTime(start), AbsTime.AbsTime(end))))
            return out
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
        if elem == "pmsl":
            if self.pmsl_fn is None:
                return None
            return self.pmsl_fn(self._lat, self._lon,
                                tr.startTime().unixTime()).astype(np.float32)
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

# TCPressure (the pmsl option) is a GFE utility: GFE/utilities/ in the repo,
# the bundle root alongside TCWind_JTWC.py in the export.
_REPO_UTIL_DIR = os.path.join(HERE, "..", "..", "GFE", "utilities")


def _import_tcwind_jtwc():
    _install_fake_awips_modules()
    if PROC_DIR not in sys.path:
        sys.path.insert(0, PROC_DIR)
    if os.path.isdir(_REPO_UTIL_DIR) and _REPO_UTIL_DIR not in sys.path:
        sys.path.insert(0, _REPO_UTIL_DIR)
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


# ---------------------------------------------------------------------------
# pmsl: the storms moved to the warnings
# ---------------------------------------------------------------------------

KROVANH = "real_2026-09-02_wtpn31_krovanh.txt"


def _modelPmsl(taus, offsetDeg=(1.5, 1.5), depth=8.0):
    """pmsl as a model might have it: a sloping environment and a low
    `offsetDeg` (dlat, dlon) from wherever the warning has the storm."""
    def field(lat, lon, epoch):
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        # Near 1004 mb under the storm, as in the monsoon trough Krovanh
        # was in, rising northward.
        env = 1001.0 + 0.3 * (lat - 15.0) + 0.05 * (lon - 120.0)
        if not depth:
            return env
        snap = tc.interpolateTrack(taus, epoch)
        clat, clon = snap.lat + offsetDeg[0], snap.lon + offsetDeg[1]
        r2 = (lat - clat) ** 2 + ((lon - clon) *
                                  np.cos(np.radians(clat))) ** 2
        return env - depth * np.exp(-r2 / (2.0 * 1.2 ** 2))
    return field


def _run_pmsl(pmsl_fn, write_to="Preview grid", ack="No", label="Yes",
              block_hours=6, extra=None, pmsl_until_hours=None):
    """Krovanh, with a Fcst pmsl inventory of `block_hours` blocks over
    the warning's span and `pmsl_fn` behind it."""
    text = _load_fixture(KROVANH)
    taus, header, _kind = tc.parseBulletin(text)
    t0, t1 = taus[0].epoch, taus[-1].epoch
    latGrid, lonGrid = _mesh()
    proc = tc.Procedure(dbss=None)
    proc.configure(texts={"NFDTCPWP1": text}, now_epoch=t0 + 3 * 3600,
                   inv_start=t0, inv_end=t1 + 3 * 3600,
                   lat=latGrid, lon=lonGrid)
    step = block_hours * 3600
    if pmsl_until_hours is not None:
        t1 = t0 + pmsl_until_hours * 3600
    proc.pmsl_blocks = [(w, w + step) for w in range(t0, t1 + 1, step)]
    proc.pmsl_fn = pmsl_fn
    varDict = {
        "Basin:": "West Pac",
        "Write to:": write_to,
        "Run over selected time range only?": "No",
        "I understand this tool is experimental and I have reviewed "
        "the output:": ack,
    }
    if label is not None:
        varDict[tc.PMSL_LABEL] = label
    varDict.update(extra or {})
    proc.execute(None, None, varDict)
    return proc, taus, header, latGrid, lonGrid


def _pmslWrites(proc):
    """{start epoch: (element, field, kwargs)} for every pmsl grid written."""
    out = {}
    for args, kwargs in proc.created:
        if args[2] == "SCALAR":
            out[args[4].startTime().unixTime()] = (args[1],
                                                   np.asarray(args[3]),
                                                   kwargs)
    return out


def case_pmsl_preview_moves_the_storm():
    """The model's low is 1.5 degrees NE of the warning position all along
    the track.  In the preview pmsl grids the low must be where the warning
    has it, at the bulletin's 994 mb at tau 0, with nothing of the model's
    low left - checked against the same run on a field that never had one."""
    fails = []
    if tc.TCPressure is None:
        return ["TCPressure did not import"], None
    proc, taus, header, lat, lon = _run_pmsl(_modelPmsl(taus=tc.parseBulletin(
        _load_fixture(KROVANH))[0]))
    writes = _pmslWrites(proc)
    t0 = taus[0].epoch
    expected = set(range(t0, taus[-1].epoch + 1, 6 * 3600))
    if set(writes) != expected:
        fails.append("pmsl grids written at %d times, expected one per "
                     "6-hourly pmsl grid in the span (%d)"
                     % (len(writes), len(expected)))
    for start, (element, field, kwargs) in writes.items():
        if element != tc.PMSL_PREVIEW_ELEMENT:
            fails.append("pmsl written to %r, not the preview element"
                         % element)
            break
        if kwargs.get("units") != "mb" or "descriptiveName" not in kwargs:
            fails.append("preview pmsl not created as a temporary parm "
                         "(kwargs %r)" % sorted(kwargs))
            break
    winds = [a[1] for a, _ in proc.created if a[2] == "VECTOR"]
    if not winds or set(winds) != {tc.PREVIEW_ELEMENT}:
        fails.append("Wind preview grids not written alongside: %r"
                     % sorted(set(winds)))

    if t0 in writes:
        field = writes[t0][1]
        i, j = np.unravel_index(np.argmin(field), field.shape)
        if abs(lat[i, j] - taus[0].lat) > 0.3 or \
                abs(lon[i, j] - taus[0].lon) > 0.3:
            fails.append("tau-0 low at %.2fN %.2fE, warning has %.1fN %.1fE"
                         % (lat[i, j], lon[i, j], taus[0].lat, taus[0].lon))
        if abs(field[i, j] - header["pressureMb"]) > 2.0:
            fails.append("tau-0 central pressure %.1f mb, bulletin %d mb"
                         % (field[i, j], header["pressureMb"]))

    clean, _, _, _, _ = _run_pmsl(_modelPmsl(taus, depth=0.0))
    cleanWrites = _pmslWrites(clean)
    worst = max(float(np.abs(writes[k][1] - cleanWrites[k][1]).max())
                for k in writes if k in cleanWrites)
    if worst > 0.6:
        fails.append("%.2f mb of the model's low left behind" % worst)

    model = _modelPmsl(taus)(lat, lon, t0)
    if t0 in writes and abs(writes[t0][1][0, 0] - model[0, 0]) > 1e-3:
        fails.append("the far corner of the grid changed")

    msg = _final_status(proc)
    for want in (tc.PMSL_PREVIEW_ELEMENT, "KROVANH", "nm off"):
        if want not in msg:
            fails.append("status does not mention %r: %r" % (want, msg))
    return fails, proc


def case_pmsl_fcst_needs_ack_and_writes_pmsl():
    fails = []
    taus = tc.parseBulletin(_load_fixture(KROVANH))[0]
    proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus), write_to="Fcst Wind",
                                 ack="Yes")
    elements = set(e for e, _, _ in _pmslWrites(proc).values())
    if elements != {"pmsl"}:
        fails.append("Fcst run wrote pmsl to %r" % sorted(elements))
    proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus), write_to="Fcst Wind",
                                 ack="No")
    if proc.created:
        fails.append("Fcst run without the acknowledgement wrote %d grids"
                     % len(proc.created))
    return fails, proc


def case_pmsl_only_when_asked():
    fails = []
    taus = tc.parseBulletin(_load_fixture(KROVANH))[0]
    for label in ("No", None):
        proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus), label=label)
        if _pmslWrites(proc):
            fails.append("pmsl written with the option %r" % (label,))
        if not proc.created:
            fails.append("Wind not written with the pmsl option %r"
                         % (label,))
    return fails, proc


def case_pmsl_run_twice_is_stable():
    """Running on a grid the tool already adjusted changes almost nothing:
    the second run finds the first run's storm and puts it back in place."""
    fails = []
    taus = tc.parseBulletin(_load_fixture(KROVANH))[0]
    first, _, _, _, _ = _run_pmsl(_modelPmsl(taus))
    firstWrites = _pmslWrites(first)
    again = lambda lat, lon, epoch: firstWrites[epoch][1].astype(float)
    second, _, _, _, _ = _run_pmsl(again)
    secondWrites = _pmslWrites(second)
    worst = max(float(np.abs(secondWrites[k][1] - firstWrites[k][1]).max())
                for k in firstWrites)
    if worst > 0.5:
        fails.append("a second run moved pmsl by up to %.2f mb" % worst)
    return fails, second


def case_pmsl_without_tcpressure():
    fails = []
    taus = tc.parseBulletin(_load_fixture(KROVANH))[0]
    saved = tc.TCPressure
    tc.TCPressure = None
    try:
        proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus))
    finally:
        tc.TCPressure = saved
    if _pmslWrites(proc):
        fails.append("pmsl written without TCPressure")
    if not proc.created:
        fails.append("Wind not written without TCPressure")
    if "TCPressure.py is not installed" not in _final_status(proc):
        fails.append("status does not say why pmsl was left alone: %r"
                     % _final_status(proc))
    return fails, proc


def case_pmsl_grids_outside_the_span():
    fails = []
    taus = tc.parseBulletin(_load_fixture(KROVANH))[0]
    text = _load_fixture(KROVANH)
    latGrid, lonGrid = _mesh()
    t0 = taus[0].epoch
    proc = tc.Procedure(dbss=None)
    proc.configure(texts={"NFDTCPWP1": text}, now_epoch=t0 + 3 * 3600,
                   inv_start=t0, inv_end=taus[-1].epoch + 3 * 3600,
                   lat=latGrid, lon=lonGrid)
    proc.pmsl_blocks = [(t0 - 48 * 3600, t0 - 42 * 3600)]
    proc.pmsl_fn = _modelPmsl(taus)
    proc.execute(None, None, {
        "Basin:": "West Pac", "Write to:": "Preview grid",
        "Run over selected time range only?": "No", tc.PMSL_LABEL: "Yes"})
    if _pmslWrites(proc):
        fails.append("pmsl written outside the warning's span")
    if "no Fcst pmsl grids inside" not in _final_status(proc):
        fails.append("status does not say there were none: %r"
                     % _final_status(proc))
    return fails, proc


# ---------------------------------------------------------------------------
# Forecaster points past the warning (days 6-7), and extratropical storms
# ---------------------------------------------------------------------------

import tempfile                                                 # noqa: E402

FakePVL = sys.modules["ProcessVariableList"].ProcessVariableList


def _krovanhTaus():
    return tc.parseBulletin(_load_fixture(KROVANH))[0]


def _withStore(points=None, key="22W"):
    """A fresh temporary store, optionally holding `points` for KROVANH."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    tc.EXTENSION_STORE = path
    if points is not None:
        tc.saveExtensions({key: {"name": "KROVANH", "saved": time.time(),
                                 "points": points}}, path)
    return path


def _extPoints(taus, et=False, pressure=None):
    t0 = taus[0].epoch
    return [{"epoch": t0 + 144 * 3600, "lat": 30.0, "lon": 131.0,
             "vmax": 45.0, "pressureMb": None,
             "r34": {"NE": 200.0, "SE": 180.0, "SW": 90.0, "NW": 120.0},
             "extratropical": False},
            {"epoch": t0 + 168 * 3600, "lat": 34.0, "lon": 136.0,
             "vmax": 50.0, "pressureMb": pressure,
             "r34": {"NE": 300.0, "SE": 260.0, "SW": 80.0, "NW": 60.0},
             "extratropical": et}]


def case_extension_parsing():
    fails = []
    P = tc.parseCoord
    for text, kind, want in (("38.5N", "lat", 38.5), ("12S", "lat", -12.0),
                             ("-12", "lat", -12.0), ("165.0E", "lon", 165.0),
                             ("170W", "lon", -170.0), ("195", "lon", -165.0),
                             (" 140.5 e ", "lon", 140.5), ("", "lat", None)):
        got = P(text, kind)
        if got != want:
            fails.append("parseCoord(%r) = %r, want %r" % (text, got, want))
    for bad, kind in (("95N", "lat"), ("40E", "lat"), ("abc", "lon")):
        try:
            P(bad, kind)
            fails.append("parseCoord(%r) did not refuse" % bad)
        except ValueError:
            pass
    if tc.parseRadii("300 250, 60/40") != {"NE": 300.0, "SE": 250.0,
                                           "SW": 60.0, "NW": 40.0}:
        fails.append("parseRadii mixed separators")
    if tc.parseRadii("120") != dict((q, 120.0) for q in tc.QUADS):
        fails.append("parseRadii one value")
    if tc.parseRadii("  ") is not None:
        fails.append("parseRadii blank")
    try:
        tc.parseRadii("100 200 300")
        fails.append("parseRadii took three radii")
    except ValueError:
        pass
    ref = 1790812800                     # 2026-10-01 00Z
    if tc.parseValidTime("071800", ref) != ref + 6 * 86400 + 18 * 3600:
        fails.append("parseValidTime DDHHMM")
    if tc.parseValidTime("0718Z", ref) != ref + 6 * 86400 + 18 * 3600:
        fails.append("parseValidTime DDHHZ")
    late = 1792540800                    # 2026-10-21 00Z
    if time.gmtime(tc.parseValidTime("021200", late)).tm_mon != 11:
        fails.append("parseValidTime month rollover")
    return fails, None


def case_extension_track_and_pressure():
    fails = []
    taus = _krovanhTaus()
    t0, last = taus[0].epoch, taus[-1].epoch
    covered = {"epoch": last - 6 * 3600, "lat": 1, "lon": 1, "vmax": 40}
    points = _extPoints(taus, et=True, pressure=990.0) + [covered]
    ext, used, dropped = tc.extendTrack(taus, points)
    if len(ext) != len(taus) + 2 or dropped != [covered]:
        fails.append("extendTrack: %d taus, %d dropped"
                     % (len(ext), len(dropped)))
    if ext[-1].tau != 168 or not ext[-1].synthetic:
        fails.append("last tau %r synthetic %r" % (ext[-1].tau,
                                                   ext[-1].synthetic))
    if ext[-1].conf != tc.CONF_SUBTROPICAL or ext[-2].conf != 1.0:
        fails.append("ET point not flagged, or the flag leaked backward")
    if ext[-1].radii[34]["SW"] != 80.0 or ext[-1].motionSpd is None:
        fails.append("radii or motion missing on the new point")
    if abs(ext[len(taus) - 1].motionDir -
           tc._bearing_speed(ext[len(taus) - 1], ext[len(taus)])[0]) > 1e-6:
        fails.append("motion at the warning's last time not recomputed "
                     "toward the first new point")
    if len(taus) != len(_krovanhTaus()):
        fails.append("extendTrack changed the caller's list")
    snap = tc.interpolateTrack(ext, t0 + 156 * 3600)
    if abs(snap.lat - 32.0) > 1e-6 or abs(snap.vmax - 47.5) > 1e-6:
        fails.append("interpolation between the new points: %.2f %.1f"
                     % (snap.lat, snap.vmax))

    # Pressure: none at the 144 h point, 990 at 168 h.
    target = tc.pressureTargetAt(ext, t0 + 156 * 3600)
    if target is None or target[0] != 990.0 or abs(target[1] - 0.5) > 1e-9:
        fails.append("pressure target half way to the 990 point: %r"
                     % (target,))
    if tc.pressureTargetAt(ext, t0 + 168 * 3600) != (990.0, 1.0):
        fails.append("pressure target at the 990 point")
    if tc.pressureTargetAt(ext, t0 + 48 * 3600) is not None:
        fails.append("pressure target inside the warning")
    return fails, None


def case_extension_store():
    fails = []
    path = _withStore()
    if tc.loadExtensions(path) != {}:
        fails.append("a missing store is not empty")
    with open(path, "w") as fh:
        fh.write("{not json")
    if tc.loadExtensions(path) != {}:
        fails.append("a corrupt store is not empty")
    now = time.time()
    problem = tc.saveExtensions({
        "A": {"saved": now, "points": [{"epoch": 1}]},
        "OLD": {"saved": now - 11 * 86400, "points": [{"epoch": 1}]},
        "EMPTY": {"saved": now, "points": []}}, path, nowSecs=now)
    if problem or sorted(tc.loadExtensions(path)) != ["A"]:
        fails.append("store keeps %r (%s)"
                     % (sorted(tc.loadExtensions(path)), problem))
    if not tc.saveExtensions({"A": {"saved": now, "points": [{}]}},
                             "/nonexistent-dir/x.json"):
        fails.append("an unwritable store did not say so")
    os.remove(path)
    return fails, None


def case_extension_use_saved_wind_and_pmsl():
    """Saved points carry KROVANH to 168 h: Wind grids every 3 h to the
    last point, pmsl moved there too, at the forecaster's 990 mb."""
    fails = []
    taus = _krovanhTaus()
    t0 = taus[0].epoch
    path = _withStore(_extPoints(taus, pressure=990.0))
    proc, _, _, lat, lon = _run_pmsl(
        _modelPmsl(taus), extra={tc.EXTENSION_LABEL: "Use saved"},
        pmsl_until_hours=168)
    winds = sorted(a[4].startTime().unixTime() for a, _ in proc.created
                   if a[2] == "VECTOR")
    if not winds or winds[-1] != t0 + 168 * 3600:
        fails.append("Wind grids end at %s, not 168 h"
                     % (winds and (winds[-1] - t0) // 3600))
    writes = _pmslWrites(proc)
    end = t0 + 168 * 3600
    if end not in writes:
        fails.append("no pmsl grid moved at 168 h")
    else:
        field = writes[end][1]
        i, j = np.unravel_index(np.argmin(field), field.shape)
        if abs(lat[i, j] - 34.0) > 0.3 or abs(lon[i, j] - 136.0) > 0.3:
            fails.append("168 h low at %.2f %.2f, point is 34.0 136.0"
                         % (lat[i, j], lon[i, j]))
        if abs(field[i, j] - 990.0) > 1.5:
            fails.append("168 h central %.1f, forecaster said 990"
                         % field[i, j])
    msg = _final_status(proc)
    if "extended to" not in msg or "2 forecaster point" not in msg:
        fails.append("status does not report the extension: %r" % msg)
    os.remove(path)
    return fails, proc


def case_extension_off_by_default():
    fails = []
    taus = _krovanhTaus()
    path = _withStore(_extPoints(taus))
    proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus), pmsl_until_hours=168)
    last = max(a[4].startTime().unixTime() for a, _ in proc.created)
    if last > taus[-1].epoch:
        fails.append("a run without the option used the saved points")
    proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus),
                                 extra={tc.EXTENSION_LABEL: "Off"},
                                 pmsl_until_hours=168)
    last = max(a[4].startTime().unixTime() for a, _ in proc.created)
    if last > taus[-1].epoch:
        fails.append("Off used the saved points")
    os.remove(path)
    return fails, proc


def case_extension_edit_dialog():
    """Edit pre-fills the saved points, takes the forecaster's changes,
    files them, and Cancel stops the run."""
    fails = []
    taus = _krovanhTaus()
    t0 = taus[0].epoch
    path = _withStore(_extPoints(taus, pressure=990.0))
    F = tc.EXT_FIELDS
    del FakePVL.calls[:]
    FakePVL.answers[:] = [{
        F["valid"] % 1: time.strftime("%d%H%M", time.gmtime(
            t0 + 144 * 3600)),
        F["lat"] % 1: "31.0N", F["lon"] % 1: "132.0E",
        F["vmax"] % 1: "45", F["pressure"] % 1: "",
        F["r34"] % 1: "200 180 90 120", F["et"] % 1: "No",
        F["valid"] % 2: time.strftime("%d%H", time.gmtime(t0 + 168 * 3600)),
        F["lat"] % 2: "35N", F["lon"] % 2: "138E", F["vmax"] % 2: "55",
        F["pressure"] % 2: "985", F["r34"] % 2: "350 300 90 60",
        F["et"] % 2: "Yes",
        F["lat"] % 3: "", F["lat"] % 4: "bogus", F["lon"] % 4: "1",
        F["vmax"] % 4: "1", F["valid"] % 4: "010000"}]
    proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus),
                                 extra={tc.EXTENSION_LABEL: "Edit"},
                                 pmsl_until_hours=168)
    if len(FakePVL.calls) != 1:
        fails.append("%d dialogs shown, expected one per storm"
                     % len(FakePVL.calls))
    else:
        title, vlist = FakePVL.calls[0]
        defaults = dict((v[0], v[1]) for v in vlist)
        # Rows run in time order: blank rows at 132 and 156 h interleave
        # with the saved 144 and 168 h points.
        times = [defaults.get(F["valid"] % k) for k in range(1, 5)]
        want = [time.strftime("%d%H%M", time.gmtime(t0 + h * 3600))
                for h in (132, 144, 156, 168)]
        if times != want:
            fails.append("row times %r, want %r" % (times, want))
        if defaults.get(F["pressure"] % 4) != "990" or \
                defaults.get(F["lat"] % 4) != "34.0N" or \
                defaults.get(F["r34"] % 4) != "300 260 80 60" or \
                defaults.get(F["et"] % 4) != "No" or \
                defaults.get(F["lat"] % 3) != "":
            fails.append("saved point not pre-filled: %r"
                         % [(k, defaults.get(F[k] % 4)) for k in
                            ("lat", "pressure", "r34")])
        if len([v for v in vlist if v[0].endswith("lat (38.5N):")]) != 4:
            fails.append("not four rows")
        if any(len(v) > 2 and v[2] not in ("label", "alphaNumeric", "radio")
               for v in vlist):
            fails.append("unexpected dialog widget types")
    saved = tc.loadExtensions(path).get("22W", {}).get("points", [])
    if [(p["lat"], p.get("pressureMb"), p["extratropical"]) for p in saved] \
            != [(31.0, None, False), (35.0, 985.0, True)]:
        fails.append("store holds %r" % [(p["lat"], p.get("pressureMb"),
                                          p["extratropical"])
                                         for p in saved])
    msg = _final_status(proc)
    if "point 4" not in msg or "extended to" not in msg:
        fails.append("bad row not reported, or no extension: %r" % msg)

    FakePVL.answers[:] = ["CANCEL"]
    proc, _, _, _, _ = _run_pmsl(_modelPmsl(taus),
                                 extra={tc.EXTENSION_LABEL: "Edit"})
    if proc.created or "Cancelled" not in _final_status(proc):
        fails.append("Cancel did not stop the run")
    FakePVL.answers[:] = []
    os.remove(path)
    return fails, proc


def case_extension_covered_points_dropped():
    fails = []
    taus = _krovanhTaus()
    pts = _extPoints(taus)
    pts[0]["epoch"] = taus[-1].epoch - 3600      # now inside the warning
    path = _withStore(pts)
    _run_pmsl(_modelPmsl(taus), extra={tc.EXTENSION_LABEL: "Use saved"})
    saved = tc.loadExtensions(path).get("22W", {}).get("points", [])
    if len(saved) != 1 or saved[0]["epoch"] != pts[1]["epoch"]:
        fails.append("store after a covered point: %d points" % len(saved))
    os.remove(path)
    return fails, None


def case_extratropical_follows_the_radio():
    """An extratropical point is moved in Wind and pmsl with Include, and
    left alone in both with Skip."""
    fails = []
    taus = _krovanhTaus()
    end = taus[0].epoch + 168 * 3600
    for choice, want in (("Include", True), ("Skip", False)):
        path = _withStore(_extPoints(taus, et=True, pressure=990.0))
        proc, _, _, _, _ = _run_pmsl(
            _modelPmsl(taus), pmsl_until_hours=168,
            extra={tc.EXTENSION_LABEL: "Use saved",
                   "Subtropical / extratropical systems:": choice})
        wind = any(a[2] == "VECTOR" and a[4].startTime().unixTime() == end
                   for a, _ in proc.created)
        pmsl = end in _pmslWrites(proc)
        if wind != want or pmsl != want:
            fails.append("%s: wind %r pmsl %r at the ET point"
                         % (choice, wind, pmsl))
        os.remove(path)
    return fails, None


def case_extratropical_fit_honors_lopsided_radii():
    """A slow storm with gales on one side: the extratropical fit reaches
    much closer to the radii than the tropical cap allows."""
    fails = []
    out = {}
    for et in (False, True):
        t = tc.Tau(144)
        t.epoch, t.lat, t.lon, t.vmax = 0, 40.0, 165.0, 55.0
        t.radii = {34: {"NE": 300.0, "SE": 250.0, "SW": 60.0, "NW": 40.0}}
        t.motionDir, t.motionSpd = 45.0, 5.0
        t.extratropical = et
        out[et] = tc.fitGTCM(t)
    if not out[True]["rms"] < 0.5 * out[False]["rms"]:
        fails.append("ET fit rms %.1f vs tropical %.1f kt"
                     % (out[True]["rms"], out[False]["rms"]))
    return fails, None


# ---------------------------------------------------------------------------
# Basins: a checklist, and one storm warned on in two basins
# ---------------------------------------------------------------------------

def _runBasins(texts, basins, extra=None):
    taus = _krovanhTaus()
    t0 = taus[0].epoch
    latGrid, lonGrid = _mesh()
    proc = tc.Procedure(dbss=None)
    proc.configure(texts=texts, now_epoch=t0 + 3 * 3600, inv_start=t0,
                   inv_end=taus[-1].epoch + 3 * 3600, lat=latGrid,
                   lon=lonGrid)
    varDict = {"Write to:": "Preview grid",
               "Run over selected time range only?": "No"}
    if basins is not None:
        varDict[tc.BASINS_LABEL] = basins
    varDict.update(extra or {})
    proc.execute(None, None, varDict)
    return proc


def case_basins_checklist():
    fails = []
    pick = tc.selectedBasins
    for given, want in (({tc.BASINS_LABEL: ["Central Pac", "West Pac"]},
                         ["West Pac", "Central Pac"]),
                        ({tc.BASINS_LABEL: "East Pac"}, ["East Pac"]),
                        ({tc.BASINS_LABEL: []}, []),
                        ({tc.BASINS_LABEL: ["Mars"]}, []),
                        ({"Basin:": "Atlantic"}, ["Atlantic"]),
                        ({}, [])):
        if pick(given) != want:
            fails.append("selectedBasins(%r) = %r" % (given, pick(given)))

    del FakePVL.calls[:]
    tc.Procedure(dbss=None)._buildVarDict()
    row = [v for v in FakePVL.calls[-1][1] if v[0] == tc.BASINS_LABEL]
    if not row or row[0][1] != [] or row[0][2] != "check" or \
            row[0][3] != tc.BASIN_LABELS:
        fails.append("dialog row is %r, want an unticked checklist" % row)

    text = _load_fixture(KROVANH)
    proc = _runBasins({"NFDTCPWP1": text}, [])
    if proc.created or "No basin selected" not in _final_status(proc):
        fails.append("nothing ticked did not refuse: %r"
                     % _final_status(proc))
    proc = _runBasins({"NFDTCPWP1": text}, None)
    if proc.created:
        fails.append("no basin key at all still wrote grids")
    # Each ticked basin's slots are read, and only those.
    proc = _runBasins({"HFOTCMCP2": text}, ["West Pac", "Central Pac"])
    if not proc.created or "HFOTCMCP2" not in _final_status(proc):
        fails.append("Central Pac slot not read with both ticked: %r"
                     % _final_status(proc))
    proc = _runBasins({"HFOTCMCP2": text}, ["West Pac"])
    if proc.created:
        fails.append("Central Pac slot read with only West Pac ticked")
    return fails, proc


def case_one_storm_in_two_basins():
    """The same storm in a CPHC slot and a JTWC slot - as during a dateline
    crossing - is inserted once, from the newer bulletin."""
    fails = []
    text = _load_fixture(KROVANH)
    proc = _runBasins({"NFDTCPWP1": text, "HFOTCMCP1": text},
                      ["West Pac", "Central Pac"])
    msg = _final_status(proc)
    if "same storm" not in msg:
        fails.append("duplicate not reported: %r" % msg)
    if msg.count("(KROVANH) warning 5 (") != 1:
        fails.append("storm inserted twice: %r" % msg)

    taus, header, _ = tc.parseBulletin(text)

    def storm(pil, dHours=0.0, dLat=0.0, name="KROVANH"):
        ts = tc.parseBulletin(text)[0]
        for t in ts:
            t.epoch += int(dHours * 3600)
            t.lat += dLat
        h = dict(header)
        h["stormName"] = name
        return {"pil": pil, "taus": ts, "header": h}

    old, new = storm("HFOTCMCP1", -6), storm("NFDTCPWP1")
    kept, notes = tc.dropDuplicateStorms([old, new])
    if [k["pil"] for k in kept] != ["NFDTCPWP1"] or len(notes) != 1:
        fails.append("same name: kept %r" % [k["pil"] for k in kept])
    kept, _ = tc.dropDuplicateStorms([storm("A", 0, 0.5, "ONE"),
                                      storm("B", 0, 0.0, "TWO")])
    if len(kept) != 2:
        fails.append("two differently named storms 30 nm apart merged")
    kept, _ = tc.dropDuplicateStorms([storm("A", 0, 0.5, ""),
                                      storm("B", -6, 0.0, "")])
    if [k["pil"] for k in kept] != ["A"]:
        fails.append("unnamed, 30 nm apart: kept %r"
                     % [k["pil"] for k in kept])
    kept, _ = tc.dropDuplicateStorms([storm("A", 0, 3.0, ""),
                                      storm("B", 0, 0.0, "")])
    if len(kept) != 2:
        fails.append("unnamed storms 180 nm apart merged")
    return fails, proc


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
        ("pmsl_preview_moves_the_storm", case_pmsl_preview_moves_the_storm),
        ("pmsl_fcst_needs_ack_and_writes_pmsl",
         case_pmsl_fcst_needs_ack_and_writes_pmsl),
        ("pmsl_only_when_asked", case_pmsl_only_when_asked),
        ("pmsl_run_twice_is_stable", case_pmsl_run_twice_is_stable),
        ("pmsl_without_tcpressure", case_pmsl_without_tcpressure),
        ("pmsl_grids_outside_the_span", case_pmsl_grids_outside_the_span),
        ("extension_parsing", case_extension_parsing),
        ("extension_track_and_pressure", case_extension_track_and_pressure),
        ("extension_store", case_extension_store),
        ("extension_use_saved_wind_and_pmsl",
         case_extension_use_saved_wind_and_pmsl),
        ("extension_off_by_default", case_extension_off_by_default),
        ("extension_edit_dialog", case_extension_edit_dialog),
        ("extension_covered_points_dropped",
         case_extension_covered_points_dropped),
        ("extratropical_follows_the_radio",
         case_extratropical_follows_the_radio),
        ("extratropical_fit_honors_lopsided_radii",
         case_extratropical_fit_honors_lopsided_radii),
        ("basins_checklist", case_basins_checklist),
        ("one_storm_in_two_basins", case_one_storm_in_two_basins),
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
