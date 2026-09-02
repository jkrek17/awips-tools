#!/usr/bin/env python3
"""Golden-snapshot regression test for parseJTWC() (Python side).

Runs the parser against every fixture in fixtures/ and diffs the result
against the committed JSON in expected/. A fixture with no matching
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
FLOAT_TOL = 1e-6


def run_parse(fixture_path):
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, "tools_py.py"), "parse", fixture_path],
        capture_output=True, text=True, check=True)
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
    for fixture in FIXTURES:
        name = os.path.splitext(os.path.basename(fixture))[0]
        expected_path = os.path.join(HERE, "expected", name + ".json")
        got = run_parse(fixture)

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

    print("\n%d fixture(s), %d failed, %d newly written"
          % (len(FIXTURES), failed, skipped))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
