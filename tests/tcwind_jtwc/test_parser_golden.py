#!/usr/bin/env python3
"""Golden-snapshot regression test for the parsers (Python side).

Runs parseJTWC() against every fixture in fixtures/ and parseTCM() against
every fixture in fixtures/tcm/, and diffs each result against the committed
JSON in expected/. A fixture with no matching
expected/<name>.json is reported and skipped rather than failed, so a new
fixture doesn't break the suite before its snapshot is reviewed and added
(run with --write to generate/refresh one after eyeballing the diff).

    python3 test_parser_golden.py            # check
    python3 test_parser_golden.py --write     # (re)generate expected/*.json
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = sorted(glob.glob(os.path.join(HERE, "fixtures", "*.txt")))
# TCM fixtures sit one level down so the flat glob above - which assumes a
# JTWC WTPN warning - never picks them up. They need the other parser.
TCM_FIXTURES = sorted(glob.glob(os.path.join(HERE, "fixtures", "tcm", "*.txt")))
FLOAT_TOL = 1e-6

# The wall clock every golden is evaluated against: 2026-08-24 22:00Z, an
# hour after the WTPN35 Soulik fixture's own 242100 header time.
#
# This is not decoration. parseJTWC() falls back to the WMO header day plus
# the CURRENT time when a warning's REMARKS block carries no DDMMMYY, so
# real_2026-08-24_wtpn35_soulik_no_refdate re-dates itself as the calendar
# moves: its golden was recorded in September against an August bulletin and
# failed from the following month onward, reporting month 9 where the
# snapshot said 8. A golden test that depends on the day it is run cannot
# ever be green, and a permanently red test hides every real regression
# behind it. Pinning the clock is the fix; the parser was doing what it was
# asked.
#
# Fixtures that carry their own reference date - every other WTPN warning,
# and every TCM, which always prints its issuance date - ignore this.
GOLDEN_NOW = 1787598000.0


def run_parse(fixture_path, kind="jtwc"):
    cmd = [sys.executable, os.path.join(HERE, "tools_py.py"),
           "parsetcm" if kind == "tcm" else "parse", fixture_path]
    if kind != "tcm":
        cmd += ["--now", repr(GOLDEN_NOW)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def diff(path, got, want, out):
    if isinstance(want, dict):
        if not isinstance(got, dict):
            out.append("%s: expected object, got %r" % (path, got))
            return
        for k in want:
            if k not in got:
                out.append("%s.%s: missing in actual output" % (path, k))
            else:
                diff("%s.%s" % (path, k), got[k], want[k], out)
        for k in got:
            if k not in want:
                out.append("%s.%s: unexpected key in actual output (%r)" % (path, k, got[k]))
    elif isinstance(want, list):
        if not isinstance(got, list) or len(got) != len(want):
            out.append("%s: length mismatch, expected %d got %s"
                       % (path, len(want), len(got) if isinstance(got, list) else got))
            return
        for i, (g, w) in enumerate(zip(got, want)):
            diff("%s[%d]" % (path, i), g, w, out)
    elif isinstance(want, float) or isinstance(got, float):
        if want is None or got is None:
            if want != got:
                out.append("%s: expected %r, got %r" % (path, want, got))
        elif abs(float(got) - float(want)) > FLOAT_TOL:
            out.append("%s: expected %r, got %r" % (path, want, got))
    else:
        if got != want:
            out.append("%s: expected %r, got %r" % (path, want, got))


def main():
    write = "--write" in sys.argv
    failed = 0
    skipped = 0
    # (fixture, kind) so both parsers are covered by one loop and one
    # snapshot directory. TCM names are already distinct from WTPN ones, so
    # expected/ needs no sub-directory of its own.
    cases = ([(f, "jtwc") for f in FIXTURES] +
             [(f, "tcm") for f in TCM_FIXTURES])
    for fixture, kind in cases:
        name = os.path.splitext(os.path.basename(fixture))[0]
        expected_path = os.path.join(HERE, "expected", name + ".json")
        got = run_parse(fixture, kind)

        if write or not os.path.exists(expected_path):
            with open(expected_path, "w") as f:
                json.dump(got, f, sort_keys=True, indent=2)
                f.write("\n")
            if not write:
                print("WRITE  %s (no prior snapshot - wrote one, review it)" % name)
                skipped += 1
            else:
                print("WRITE  %s" % name)
            continue

        with open(expected_path) as f:
            want = json.load(f)
        diffs = []
        diff(name, got, want, diffs)
        if diffs:
            failed += 1
            print("FAIL   %s" % name)
            for d in diffs[:20]:
                print("       " + d)
            if len(diffs) > 20:
                print("       ... and %d more" % (len(diffs) - 20))
        else:
            print("PASS   %s" % name)

    print("\n%d fixture(s) (%d WTPN, %d TCM), %d failed, %d newly written"
          % (len(cases), len(FIXTURES), len(TCM_FIXTURES), failed, skipped))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
