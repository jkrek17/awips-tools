#!/usr/bin/env python3
"""Build an AWIPS/GFE export bundle for TCWind_JTWC.

Packages GFE/procedures/TCWind_JTWC.py together with a forecaster-runnable
self-check (a copy of tests/tcwind_jtwc/test_procedure_harness.py, its real
fixtures, and a driver shell script) and an AWIPS_TEST.md walkthrough, into:

    dist/TCWind_JTWC_<VERSION>/
        TCWind_JTWC.py
        AWIPS_TEST.md
        selfcheck/
            run_selfcheck.sh
            test_procedure_harness.py
            fixtures/
                real_2026-09-02_wtpn31_krovanh.txt
                real_2026-09-02_wtpn32_saudel.txt

...and zips that directory to dist/TCWind_JTWC_<VERSION>.zip.

VERSION is read out of the procedure file itself (the `VERSION = "..."`
tunable), so the bundle name always matches what the status bar will report
once it is installed.

This script is stdlib-only and targets Python 3.6+ (it does not itself run
under the AWIPS interpreter -- it is run on a normal development machine to
produce the bundle a forecaster then copies to the AWIPS host).

Usage:
    python3 tools/export_awips.py
"""
from __future__ import print_function

import os
import re
import shutil
import stat
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC_SRC = os.path.join(REPO_ROOT, "GFE", "procedures", "TCWind_JTWC.py")
HARNESS_SRC = os.path.join(
    REPO_ROOT, "tests", "tcwind_jtwc", "test_procedure_harness.py")
FIXTURES_SRC_DIR = os.path.join(REPO_ROOT, "tests", "tcwind_jtwc", "fixtures")
DIST_DIR = os.path.join(REPO_ROOT, "dist")

REAL_FIXTURES = [
    "real_2026-09-02_wtpn31_krovanh.txt",
    "real_2026-09-02_wtpn32_saudel.txt",
]

VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


def read_version(proc_path):
    with open(proc_path, "r") as fh:
        text = fh.read()
    m = VERSION_RE.search(text)
    if not m:
        raise SystemExit(
            "error: could not find VERSION = \"...\" in %s" % proc_path)
    return m.group(1)


RUN_SELFCHECK_SH = """#!/bin/sh
# Self-check for the TCWind_JTWC AWIPS export bundle.
#
# Run this from the bundle root, e.g.:
#     cd TCWind_JTWC_<VERSION>
#     selfcheck/run_selfcheck.sh
#
# Uses the real AWIPS python interpreter by default (the same one GFE will
# run this procedure under), so a pass here means the bundle will actually
# load in GFE. Override with AWIPS_PYTHON if the AWIPS python is not at the
# default path on this host, e.g.:
#     AWIPS_PYTHON=/some/other/path/python selfcheck/run_selfcheck.sh

PY="${AWIPS_PYTHON:-/awips2/python/bin/python}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BUNDLE_DIR" || exit 1

echo "============================================================"
echo "TCWind_JTWC AWIPS export self-check"
echo "Interpreter: $PY"
"$PY" --version 2>&1 | sed 's/^/  /'
echo "Bundle dir:  $BUNDLE_DIR"
echo "============================================================"

FAILED=0

echo ""
echo "[1/3] python -m py_compile TCWind_JTWC.py"
if "$PY" -m py_compile TCWind_JTWC.py; then
    echo "  PASS: TCWind_JTWC.py compiles cleanly under $PY"
else
    echo "  FAIL: py_compile TCWind_JTWC.py"
    FAILED=1
fi

echo ""
echo "[2/3] python TCWind_JTWC.py selfcheck/fixtures/real_2026-09-02_wtpn31_krovanh.txt"
if "$PY" TCWind_JTWC.py selfcheck/fixtures/real_2026-09-02_wtpn31_krovanh.txt; then
    echo "  PASS: standalone parse+fit printout ran cleanly"
else
    echo "  FAIL: standalone parse+fit on the KROVANH fixture"
    FAILED=1
fi

echo ""
echo "[3/3] python selfcheck/test_procedure_harness.py"
if "$PY" selfcheck/test_procedure_harness.py; then
    echo "  PASS: end-to-end Procedure harness"
else
    echo "  FAIL: end-to-end Procedure harness"
    FAILED=1
fi

echo ""
echo "============================================================"
if [ "$FAILED" -eq 0 ]; then
    echo "SELF-CHECK: PASS -- all 3 checks passed on $PY."
    echo "Safe to move on to Step 2 of AWIPS_TEST.md (install into GFE)."
else
    echo "SELF-CHECK: FAIL -- see the output above."
    echo "Send this full output back before installing this into GFE."
fi
echo "============================================================"

exit $FAILED
"""


AWIPS_TEST_TEMPLATE = """# Testing TCWind_JTWC in AWIPS / GFE

## What this is

TCWind_JTWC is an experimental GFE procedure. It reads the JTWC tropical
cyclone warning text out of the AWIPS text database and builds a Wind grid
from it, using an analytic vortex model fit to the reported wind radii. It
has not been operationally vetted. Every grid it produces needs your review
before it goes anywhere near a real forecast. That is why the procedure
defaults to writing a temporary preview grid instead of Fcst Wind, and why
Fcst Wind requires an explicit acknowledgement in the dialog. Run it to the
preview grid first, every time, until you and your office trust it.

This document walks through testing this bundle (version %(version)s) on a
real AWIPS host, in order. Do not skip ahead to Step 6.

## Step 1: pre-flight, before touching GFE

Copy this whole bundle folder to the AWIPS host (a workstation with the
AWIPS python and CAVE installed), anywhere in your home directory is fine.
Then, from inside the bundle folder, run:

```
selfcheck/run_selfcheck.sh
```

This uses the real AWIPS python interpreter by default
(`/awips2/python/bin/python`). If yours lives somewhere else, set
`AWIPS_PYTHON` first:

```
AWIPS_PYTHON=/path/to/python selfcheck/run_selfcheck.sh
```

It runs three checks in order: the file compiles under the AWIPS python,
the standalone parser runs cleanly against a real bulletin, and a full
end-to-end run of the GFE procedure logic (outside GFE, with fakes standing
in for the AWIPS modules).

**What PASS looks like:** the script prints `[1/3]`, `[2/3]`, `[3/3]`, each
followed by a `PASS:` line, then a final block that says:

```
SELF-CHECK: PASS -- all 3 checks passed on <path to python>.
```

**If it fails:** copy the full terminal output, from the first line to the
last, and send it back before doing anything else. Do not try to install
the procedure into GFE if this fails. The output tells us which of the
three checks failed and why, which is exactly what we need to fix it.

### Also confirm the parser reads today's real product

The self-check above uses a fixture file, not live data. Confirm the parser
also reads whatever JTWC has actually posted today. From the same bundle
folder:

```
textdb -r NFDTCPWP1 > live.txt
python TCWind_JTWC.py live.txt
```

(Use the same AWIPS python here too, i.e. `/awips2/python/bin/python
TCWind_JTWC.py live.txt` if `python` is not already that interpreter on
your PATH.)

If there is a live storm in slot NFDTCPWP1, you should see a `system:`
line naming it, followed by one block per forecast hour (tau) with lat/lon,
vmax, motion, and the wind radii JTWC reported. If NFDTCPWP1 is empty right
now, this prints little or nothing, which is normal outside an active
NW Pacific storm; try NFDTCPWP2 through NFDTCPWP5, or wait for one, before
worrying about it.

## Step 2: install into GFE

Do this at **User** level first, not Site, so nobody else sees it while
you are testing.

1. Open CAVE and go to the **Localization** perspective.
2. Under **GFE**, find **Procedures**.
3. Set the localization level to **User** (your own name), not Site or
   Base.
4. Add a new procedure file named exactly `TCWind_JTWC.py` and paste in
   (or import) the contents of the `TCWind_JTWC.py` file from this bundle.
5. Save.

Once saved at User level, the procedure appears in the GFE **Populate**
menu (its `MenuItems` entry is `"Populate"`), under your own name only.
Nobody else's GFE session will see it until it is promoted to Site level,
which should not happen until it has been tested and reviewed.

**For admins, the alternative direct path** (from the file's own header)
is to place the file on the AWIPS EDEX server at:

```
/awips2/edex/data/utility/common_static/site/<SITE>/gfe/userPython/procedures/
```

replacing `<SITE>` with your site identifier. This is a Site-level install
and is visible to everyone, so it should only be used once User-level
testing here is done.

## Step 3: first run, in GFE Practice mode

Do this in a GFE **Practice** database, not Operational.

The procedure inserts its wind field on top of the existing Fcst Wind
grids; it refuses to run if there are none. Before running it, populate
Fcst Wind from a model over the full period you plan to test (a normal
model population, the same as any other forecast prep).

Then, from the **Populate** menu, run **TCWind_JTWC**. In the dialog, leave
**Write to:** on its default, **Preview grid**. Select the bulletins you
want to test (the NFDTCPWP1-5 checkboxes) and run it.

**What the status bar should say**, roughly:

```
v%(version)s. EXPERIMENTAL, verify before use. Updated N WindJTWC preview
grids. <PIL> <storm name> (<count>). Peak wind written <X> kt vs bulletin
max <Y> kt. ...
```

`N` is the number of preview grids written, one per forecast block. The
peak wind written should be close to the bulletin's own reported max wind
(see the checklist in Step 4). The message may also mention created
blocks, skipped storm-times, or problems parsing a bulletin; read the
whole line.

**What `WindJTWC` is:** a temporary preview weather element, created on
the fly by the procedure. It is not part of your site's normal parm
configuration, is never saved or published, and disappears the moment you
clear it (or exit GFE without it). It costs nothing to run repeatedly.

## Step 4: what to look at

Go through this checklist against the `WindJTWC` preview grid. For each
storm you test, note whether it matches the expected result.

| Check | Expected result |
|---|---|
| Peak wind near the storm centre | Within a few kt of the bulletin's reported Vmax |
| 34/50/64 kt contours | Land just inside the reported radii, roughly 15 percent smaller. This is by design (the model fits the quadrant average, not the quadrant maximum), not an error. |
| Overall shape | One smooth storm. No seams or kinks at the NE/SE/SW/NW quadrant boundaries. |
| Stepping through 3-hourly blocks | Core size and peak wind change smoothly from one block to the next. No sudden jumps. |
| Footprint edge | Blends into the background wind field. No sharp ring or halo at the edge of the insert. |
| A storm below 34 kt (e.g. a tropical depression) | Leaves the background wind completely untouched at that time. |
| Runtime | Under about a minute for one storm's full forecast period. Note the actual time it took. |
| CAVE log | No Python traceback. Check `~/caveData/logs` on the workstation after the run. |

## Step 5: known limits, not defects

These are expected behavior, not bugs. Do not report them as problems
(though feel free to say if they cause a real operational issue):

- **No inland decay.** A landfalling storm keeps its over-water wind
  speeds after the centre crosses land.
- **No wind reduction over land.** Related to the above; the field is
  built for open water everywhere.
- **Subtropical/extratropical flags are parsed but not blended in.** The
  procedure reads JTWC's subtropical/extratropical remarks and can flag
  them, but the wind field construction itself does not change shape for
  a transitioning storm.
- **34 kt-only bulletins use a climatological core size.** If a bulletin
  only reports 34 kt radii (no 50 or 64 kt), the storm's inner core size
  (Rmax) comes from a regression fit to historical storms, not from
  anything in that specific bulletin.
- **Weak-side winds on a one-sided storm may look low.** If a storm's
  reported radii are lopsided (gales on one side only, e.g. from wind
  shear or an asymmetric structure), the far side of the modelled field
  can look weaker than you might expect. This is a deliberate cap in the
  fit (the fitted asymmetry is limited to 1.5 times the motion-derived value; see the GTCM_ASYM tunables at the top of the
  file) meant to stop the fit from overreacting to a one-sided report;
  flag it if it looks wrong on a specific storm, but expect some of this.

## Step 6: writing to Fcst Wind

Only do this after Steps 1-5 look right to you, and still in **Practice**
mode first, never Operational, for this first round of testing.

In the dialog, set **Write to:** to **Fcst Wind**. A new radio button
appears: "I understand this tool is experimental and I have reviewed the
output". You must set this to **Yes** before the procedure will write
anything to Fcst Wind; leaving it on the default **No** stops the run
with a status bar message and writes nothing. This acknowledgement gate
only applies to Fcst Wind; preview runs never require it.

## What to report back

Whether the self-check passed or failed, and its full output if it
failed. For a GFE run, please send:

- The exact status bar text after the run.
- A screenshot of the preview (or Fcst) grid.
- The relevant excerpt from the CAVE log (`~/caveData/logs`) if anything
  looked wrong or a traceback appeared.
- The runtime for one storm's full run.
"""


def _rmtree_onerror(func, path, exc_info):
    # Handle read-only files on a re-export over a previous dist/ build.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build_bundle():
    if not os.path.isfile(PROC_SRC):
        raise SystemExit("error: procedure not found at %s" % PROC_SRC)
    if not os.path.isfile(HARNESS_SRC):
        raise SystemExit("error: harness not found at %s" % HARNESS_SRC)

    version = read_version(PROC_SRC)
    bundle_name = "TCWind_JTWC_%s" % version
    bundle_dir = os.path.join(DIST_DIR, bundle_name)

    if not os.path.isdir(DIST_DIR):
        os.makedirs(DIST_DIR)
    if os.path.isdir(bundle_dir):
        shutil.rmtree(bundle_dir, onerror=_rmtree_onerror)

    selfcheck_dir = os.path.join(bundle_dir, "selfcheck")
    fixtures_dir = os.path.join(selfcheck_dir, "fixtures")
    os.makedirs(fixtures_dir)

    # TCWind_JTWC.py, verbatim.
    shutil.copyfile(PROC_SRC, os.path.join(bundle_dir, "TCWind_JTWC.py"))

    # selfcheck/test_procedure_harness.py, verbatim (its own repo/bundle
    # fallback logic finds TCWind_JTWC.py and the fixtures in either
    # layout, so no source changes are needed here).
    shutil.copyfile(
        HARNESS_SRC, os.path.join(selfcheck_dir, "test_procedure_harness.py"))

    # selfcheck/fixtures/, the two real bulletins only.
    for name in REAL_FIXTURES:
        src = os.path.join(FIXTURES_SRC_DIR, name)
        if not os.path.isfile(src):
            raise SystemExit("error: fixture not found at %s" % src)
        shutil.copyfile(src, os.path.join(fixtures_dir, name))

    # selfcheck/run_selfcheck.sh
    run_sh_path = os.path.join(selfcheck_dir, "run_selfcheck.sh")
    with open(run_sh_path, "w") as fh:
        fh.write(RUN_SELFCHECK_SH)
    os.chmod(
        run_sh_path,
        os.stat(run_sh_path).st_mode | stat.S_IXUSR | stat.S_IXGRP |
        stat.S_IXOTH)

    # AWIPS_TEST.md
    with open(os.path.join(bundle_dir, "AWIPS_TEST.md"), "w") as fh:
        fh.write(AWIPS_TEST_TEMPLATE % {"version": version})

    return bundle_dir, bundle_name, version


def zip_bundle(bundle_dir, bundle_name):
    zip_path = os.path.join(DIST_DIR, "%s.zip" % bundle_name)
    if os.path.isfile(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(bundle_dir):
            for fname in files:
                full = os.path.join(root, fname)
                arcname = os.path.join(
                    bundle_name, os.path.relpath(full, bundle_dir))
                zf.write(full, arcname)
    return zip_path


def main():
    bundle_dir, bundle_name, version = build_bundle()
    zip_path = zip_bundle(bundle_dir, bundle_name)

    print("Built AWIPS export bundle for TCWind_JTWC version %s" % version)
    print("  directory: %s" % bundle_dir)
    print("  zip:       %s" % zip_path)
    print("")
    print("Contents:")
    for root, dirs, files in os.walk(bundle_dir):
        dirs.sort()
        for fname in sorted(files):
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, bundle_dir)
            print("  %s" % rel)


if __name__ == "__main__":
    sys.exit(main())
