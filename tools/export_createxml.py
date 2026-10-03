#!/usr/bin/env python3
"""Build the install bundle for CreateXML's gap fill and typhoon matching.

    dist/CreateXML_GapFill_<date>/
        INSTALL.md
        CreateXML.py              procedure - replaces the site's copy
        CreateXML_changes.diff    every change against the original upload
        PressureGapFill.py        GFE utility
        TCPressure.py             GFE utility
        TCWind_JTWC.py            procedure - its parser reads the warnings

...zipped to dist/CreateXML_GapFill_<date>.zip.  <date> is the date of the
last commit that touched any of the shipped files, so a rebuild of the same
code gets the same name.  Stdlib and git only.

    python3 tools/export_createxml.py
"""
import os
import shutil
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(REPO, "dist")

# The commit holding CreateXML.py exactly as the site uploaded it.
BASELINE = "4e72162"

FILES = [
    ("GFE/procedures/CreateXML.py", "CreateXML.py"),
    ("GFE/utilities/PressureGapFill.py", "PressureGapFill.py"),
    ("GFE/utilities/TCPressure.py", "TCPressure.py"),
    ("GFE/procedures/TCWind_JTWC.py", "TCWind_JTWC.py"),
]

INSTALL = """# CreateXML: isobars and typhoons south of the GFE grid

Built %(date)s.  CreateXML.py here is your original, with the changes in
`CreateXML_changes.diff` and nothing else (77 lines added, 1 changed), and
Unix line endings - the Windows ones came from the copy's trip through
email.

## What it does

The GFE grid stops at 30N but the charts run to 17N.  CreateXML now:

1. draws isobars and Highs/Lows north of 30N from your pmsl grid, exactly
   as before;
2. fills 17N-30N from the models you pick (GFS + ECMWF by default), joined
   to your grid along 30N so isobars do not jog;
3. moves every warned tropical cyclone in that strip to the warning's
   position for each chart's valid time, at the warning's pressure, and
   writes its L with the central pressure.

The XML is the output.  Nothing needs checking in GFE first.

## Install

Do this at **User** level first, in the Localization perspective.

| File | Where | Note |
|---|---|---|
| `CreateXML.py` | GFE > Procedures | replaces your current copy |
| `PressureGapFill.py` | GFE > Utilities | next to A2GraphicsFunctions.py |
| `TCPressure.py` | GFE > Utilities | |
| `TCWind_JTWC.py` | GFE > Procedures | its parser reads the warnings; same file as in the TCWind_JTWC bundle - skip it if that is already installed at the same version (`VERSION = "%(tcwind)s"`) |

Without `TCWind_JTWC.py` the gap is still filled; storms stay where the
models have them and the status bar says why.

## The dialog

Three new rows at the bottom; leave them on their defaults:

| Row | Default | Effect |
|---|---|---|
| Fill south of grid: | On | Off draws the chart exactly as before |
| Gap models: | GFS, ECMWF | blended with equal weight; CMC and GEFS also offered |
| Match TC warnings: | On | Off leaves storms where the models have them |

Pick F024, F048, F072 and F096 as usual.  Each must be in your
`A2GraphicsConfig` `prod_list`, as before.

## What to look for

On the status bar, per chart:

```
gap fill: GFS run 20261002 06Z
F024 TC GUCHOL at 17.6N 136.9E, 942 mb - model low 124 nm off (19.1N 138.4E), moved
```

In D2D, with the XML loaded:

| Check | Expected |
|---|---|
| Isobars south of 30N | Continuous to 17N, joining your grid's isobars at 30N without a jog |
| Each typhoon's L | At the warning position for that chart's time, its pressure near the warning's |
| A typhoon near 17N | Still has its L |
| A storm on the dateline | One L, not two |

A model that cannot supply pmsl for the chart time is skipped with the
reason on the status bar; with none left, the chart goes out as before.
"""


def run(*args):
    return subprocess.check_output(args, cwd=REPO).decode().strip()


def main():
    paths = [src for src, _ in FILES]
    date = run("git", "log", "-1", "--format=%cs", "--", *paths)
    with open(os.path.join(REPO, "GFE/procedures/TCWind_JTWC.py")) as fh:
        tcwind = [line.split('"')[1] for line in fh
                  if line.startswith("VERSION = ")][0]
    name = "CreateXML_GapFill_%s" % date
    out = os.path.join(DIST, name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    for src, dst in FILES:
        shutil.copyfile(os.path.join(REPO, src), os.path.join(out, dst))
    # The baseline came by email with Windows line endings; the shipped file
    # has Unix ones.  Show only the real changes.
    diff = subprocess.check_output(
        ["git", "diff", "--ignore-cr-at-eol", BASELINE, "--",
         "GFE/procedures/CreateXML.py"], cwd=REPO)
    if not diff.strip():
        raise SystemExit("error: no changes against the baseline")
    with open(os.path.join(out, "CreateXML_changes.diff"), "wb") as fh:
        fh.write(diff)
    with open(os.path.join(out, "INSTALL.md"), "w") as fh:
        fh.write(INSTALL % {"date": date, "tcwind": tcwind})

    zpath = os.path.join(DIST, name + ".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in sorted(os.listdir(out)):
            zf.write(os.path.join(out, fname), os.path.join(name, fname))
    print(zpath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
