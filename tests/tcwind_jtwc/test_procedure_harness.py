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
an inventory of pre-existing "Fcst Wind" blocks that is deliberately made
to stop short of the bulletin's last forecast hour - so the
CREATE_MISSING_TAU_BLOCKS path (`buildFor(when, None)` inside the missing-
tau loop) actually runs. That is precisely the path Task 1's fix touches:
on the unfixed code, `buildFor()` returns a 3-tuple and the loop's
`built, stFlag = buildFor(when, None)` raises ValueError after some grids
have already been written.

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
        self._lat = None
        self._lon = None

    def configure(self, texts, now_epoch, inv_start, inv_end,
                 lat, lon, inv_step=3 * 3600):
        self.texts = texts
        self._now_epoch = now_epoch
        self._inv_start = inv_start
        self._inv_end = inv_end
        self._inv_step = inv_step
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

def _mesh(n=120):
    """15-35N, 120-140E - comfortably covers both fixtures' tracks."""
    lats = np.linspace(15.0, 35.0, n, dtype=np.float32)
    lons = np.linspace(120.0, 140.0, n, dtype=np.float32)
    lonGrid, latGrid = np.meshgrid(lons, lats)
    return latGrid.astype(np.float32), lonGrid.astype(np.float32)


def _load_fixture(name):
    path = os.path.join(FIXTURES, name)
    with open(path) as f:
        return f.read()


def _run(pil, fixture_name, inv_stop_hours):
    """Parse `fixture_name`, run Procedure.execute() against it under
    `pil`, with a pre-existing Fcst Wind inventory of 3-hourly blocks
    running from the bulletin's analysis time out to `inv_stop_hours`
    hours after it (None = cover the whole bulletin). Returns
    (proc, taus, header).
    """
    text = _load_fixture(fixture_name)
    taus, header = tc.parseJTWC(text)

    analysisEpoch = taus[0].epoch
    lastEpoch = taus[-1].epoch
    nowEpoch = analysisEpoch + 3 * 3600   # 3h after analysis: not stale

    if inv_stop_hours is None:
        invEnd = lastEpoch + 3 * 3600
    else:
        invEnd = analysisEpoch + inv_stop_hours * 3600 + 3 * 3600

    latGrid, lonGrid = _mesh()

    proc = tc.Procedure(dbss=None)
    proc.configure(
        texts={pil: text},
        now_epoch=nowEpoch,
        inv_start=analysisEpoch,
        inv_end=invEnd,
        lat=latGrid,
        lon=lonGrid)

    varDict = {
        "Bulletins to process:": [pil],
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


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def case_krovanh():
    """Real, live bulletin with full quadrant radii (Tropical Storm
    22W/KROVANH). The fake inventory is built 3-hourly from the analysis
    time out to 96h - one short of the bulletin's last forecast hour
    (120h) - so CREATE_MISSING_TAU_BLOCKS has to build that last block
    itself. That is exactly the path Task 1's fix is in."""
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

    # The 120h forecast time falls outside the fake inventory (which stops
    # at 96h), so it must have been created via CREATE_MISSING_TAU_BLOCKS.
    lastEpoch = taus[-1].epoch
    createdLabel = time.strftime("%d/%H%MZ", time.gmtime(lastEpoch))
    finalMsg = _final_status(proc)
    if "Created blocks at" not in finalMsg or createdLabel not in finalMsg:
        fails.append("expected the final status to report a created block "
                     "at %s (the forecast hour with no pre-existing Fcst "
                     "Wind block); got: %r" % (createdLabel, finalMsg))

    stormName = header.get("stormName") or ""
    if not stormName or stormName not in finalMsg:
        fails.append("final status does not mention the storm (%r): %r"
                     % (stormName, finalMsg))

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


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    cases = [
        ("krovanh_create_missing_tau_block", case_krovanh),
        ("saudel_weak_no_radii_runs_clean", case_saudel),
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
