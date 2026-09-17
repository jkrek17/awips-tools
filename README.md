# awips-tools

AWIPS tools and procedures.

## Contents

| Path | What it is |
|---|---|
| `GFE/` | GFE procedures, smart tools and shared utilities. |
| `legacy_tools/` | Earlier versions kept for reference; see `legacy_tools/VERSION_CONTROL.md`. |
| `tests/tcwind_jtwc/` | Parser goldens, Python/JavaScript parity, and the GTCM verification. |
| `GFE/procedures/TCWind_JTWC.py` | Builds GFE Wind grids from JTWC tropical cyclone warnings. See below. |
| `web/TCWind_JTWC/` | Google Apps Script web app for that tool: live bulletins, a best-track archive, and the verification findings. |
| `web/HFArchiveExport/` | Google Apps Script web app that exports the restricted HF low sheet as CSV for `tools/publish.py`. |
| `data/hf_lows/` | CSV exports of the hurricane force extratropical low archive workbook, committed here on purpose (see below). |
| `tools/build_hf_lows.py` | Normalizes those CSVs into the site data under `docs/data/`. |
| `tools/publish.py` | Production path: fetches, builds, reports the delta, and (on request) deploys to the NOAA web root. |
| `docs/` | The HF extratropical low archive site. GitHub Pages serves it as a development preview; production is a separate copy on a NOAA web server. |
| `flat/` | Generated. The same site collapsed into one directory for upload UIs that cannot take folders. Never edit by hand - see below. |

## HF extratropical low archive site

A static page for browsing and summarizing hurricane force extratropical lows in
the North Atlantic and North Pacific - tracks, climatology charts, a searchable
event table, and a data quality report. See `docs/README.md`.

There are **two environments**, deliberately kept apart. Both build the same
`docs/` from the same code; they differ only in where the data comes from and
where the result is served. See "Which environment am I looking at?" below
for how to tell them apart on the page itself.

### Development: this repo + GitHub Pages

This repo is public, and the two decades of hand-entered archive CSVs under
`data/hf_lows/` are committed to it - that's intentional, confirmed by the
archive's owner, not an oversight. Edit, commit and push here; a GitHub
Actions workflow (`.github/workflows/pages.yml`) rebuilds `docs/` from those
committed CSVs and publishes it to GitHub Pages on every push to `main`. That
workflow also runs `html-validate` over `docs/` before publishing - the same
check (and defaults) the forecaster's downstream `ocean-weather-gov` CI runs
- so an invalid page fails here instead of blocking their merge request.

```bash
# 1. export each basin tab of the workbook over the CSVs in data/hf_lows/
# 2. rebuild the site data
python3 tools/build_hf_lows.py
# 3. commit both the CSVs and docs/data, then push - Actions does the rest
```

Preview locally with `python3 -m http.server 8000 --directory docs`.

This published Pages site is a **preview of the code and of whatever data
happens to be committed** - it is not the operational page, and it can lag or
lead the real archive depending on when someone last exported and committed.

### Production: `tools/publish.py` + the NOAA web server

The operational page lives on a NOAA web server the forecaster controls, and
the code reaches it by hand - copied out of this GitHub repo, not deployed
from it. **GitHub is not in the production path at all**: nothing there
pulls from GitHub, calls its API, or depends on Pages, Actions, or the
service being reachable. A GitHub outage, a policy change, or the repo going
private or disappearing cannot take the operational page down.

Data reaches production through `tools/publish.py`, which wraps the whole
workflow - fetch, build, review, deploy - into one deliberate command. It
never runs `git` and never needs a Google account, OAuth token or service
account: the sheet stays restricted to "anyone in NOAA", and it fetches
through a companion Apps Script web app (`web/HFArchiveExport/`, run by
someone who already has the sheet open) rather than reading the sheet
directly. Every publish is a decision a human makes after reading a
plain-English delta report - see "Publishing" below.

### Which environment am I looking at?

The page cannot know for certain which copy it is, but it makes a good-faith
guess and says so:

- A small **"Preview build"** or **"Local build"** marker appears next to the
  "Experimental" badge in the masthead when the page is served from a
  `*.github.io` host or from `localhost`/`127.0.0.1`. No marker at all means
  the page believes it's production (any other hostname) - it is never shown
  on the real NOAA server.
- The **Method** tab's footnote (below "Rebuilding") always states when the
  page was built, from which git commit (or "commit unknown" - expected on
  the production server, which is a plain code copy with no `.git`
  directory), and whether the data was fetched via Apps Script or built from
  CSVs already on disk.

If two people are looking at different numbers, check these two things
before anything else.

## Publishing

### One-time setup - pick one of two input modes

- **Fetch from the sheet automatically.** The sheet can't be link-shared, so
  the anonymous CSV export URL won't work; instead have the sheet owner deploy
  a small Apps Script web app that exports each tab as CSV over HTTPS
  (`?token=...&tab=atl|pac`), deployed "Execute as: Me" / "Who has access:
  Anyone" so the sheet itself never has to leave "anyone in NOAA". Then set:

  ```bash
  export HF_EXPORT_URL="https://script.google.com/macros/s/AKfycb.../exec"
  export HF_EXPORT_TOKEN="<the shared secret the Apps Script checks>"
  ```

  or put the same two values in `tools/publish.local.json` (already
  gitignored - the token is a secret and must never land in a commit):

  ```json
  {"url": "https://script.google.com/macros/s/AKfycb.../exec",
   "token": "<the shared secret the Apps Script checks>"}
  ```

- **Export by hand.** Download each basin tab as CSV (File > Download > Comma
  Separated Values) into `data/hf_lows/` yourself, and always run with
  `--no-fetch`. No setup needed, and it works today even before the Apps
  Script exists.

Both modes feed the same build, review and deploy steps below.

### Normal workflow

```bash
python3 tools/publish.py                        # fetch, build, print what changed
python3 tools/publish.py --no-fetch              # same, but build from CSVs already on disk
python3 tools/publish.py --deploy /var/www/hf    # also publish, after you type y to confirm
python3 tools/publish.py --deploy /var/www/hf --yes   # publish with no prompt, e.g. from cron
```

Run it without `--deploy` first and read the report before deciding anything:
events added, removed or modified (with dates and basins for the additions),
any season whose event count moved, data-quality notes that appeared or
disappeared, and the total event/fix counts before and after. "No changes"
means the sheet hasn't moved since the last publish - that's the common case
and it says so in one line.

Only pass `--deploy PATH` once that report looks right. It copies `docs/`
into an existing web root as one atomic directory swap, so the live site is
never caught half-updated mid-copy, prints exactly what it wrote, and leaves
anything already in that directory that the site doesn't own untouched.
Without `--yes` it shows the delta report and waits for you to type `y`.

### Flat deploys (`--flat`)

Some web servers are only reachable through an upload UI that takes
individual files, not a directory tree - it cannot recreate `docs/`'s
`assets/` and `data/` subdirectories. `--flat` handles that: it writes every
file directly into the target with no subdirectories, and rewrites the
deployed copy of `index.html` so its `src=`/`href=` references point at the
bare filenames instead. `docs/index.html` itself is never modified - only the
copy written to the target.

```bash
python3 tools/publish.py --no-fetch --deploy /var/www/flat --flat --yes
```

Before writing anything, `--flat` re-checks the assumption that makes
flattening safe - no two files share a basename, and no CSS/JS outside
`index.html` hardcodes an `assets/...` or `data/...` path - and refuses to
deploy, naming exactly what it found, if either check fails.

A copy of that flattened build is committed to this repo as `flat/`, so the
files can be browsed and downloaded one at a time from GitHub without running
the tool. It is generated output: edit `docs/`, never `flat/`. Regenerate it
with

```bash
python3 tools/publish.py --no-fetch --deploy flat --flat --yes
rm -f flat/.awips-publish-manifest.json
cp docs/data/hf-lows.js docs/data/hf-lows.json docs/data/qc-report.txt flat/
```

The last line matters: a rebuild stamps a fresh `generated` timestamp into the
three generated data files, so copying `docs/`'s versions across keeps the two
trees byte-identical and the CI drift check quiet. That check compares `flat/`
against `docs/` on every push and fails if they diverge, since a stale `flat/`
would quietly hand someone the wrong files to upload.

Don't point a flat deploy and a normal deploy at the same directory. Each
mode leaves the other layout's files in place unless this tool's own manifest
in that directory already tracks them (i.e. this tool made the previous
deploy there in the *other* mode); mixing them can leave stale files sitting
next to the current site, and `--flat`/normal will warn if it finds files
that look like the other layout in the target. Use a dedicated directory
per layout.

### Moving to cron

Once you trust the report, drop the confirmation and let it run unattended:

```cron
0 6 * * * cd /path/to/awips-tools && python3 tools/publish.py --deploy /var/www/hf --yes >> /var/log/hf-publish.log 2>&1
```

It exits non-zero on any failure (a bad fetch, a bad deploy target) and 0
otherwise, whether or not anything changed - point cron's mail, or whatever
alerts on a non-zero exit, at it, and watch the log for a while before fully
trusting an unattended run.

## JTWC tropical cyclone wind field

**EXPERIMENTAL. NOT OPERATIONALLY VETTED.** Every grid needs forecaster review
before it informs any product.

### The problem

When a tropical cyclone threatens the Atlantic or East Pacific, NHC issues two
things: the TCM text advisory, and a **gridded** TCM built from it. OPC ingests
that grid directly and blends it into the Fcst wind field.

JTWC issues only the text. For the NW Pacific there is no grid, so there is
nothing to ingest, and the forecaster is left building a tropical wind field by
hand or doing without. `GFE/procedures/TCWind_JTWC.py` builds the missing one:
it reads the JTWC warning text and constructs the wind field the bulletin
describes.

### The approach, and why

The field uses **NHC's own GTCM/WTCM vortex model**, implemented from the
*Gridded TCM User Guide v1.9.1* (Santos & DeMaria, 4 Dec 2023): one symmetric
modified Rankine vortex (eq. 3) plus a wavenumber-1 motion asymmetry (Schwerdt
1979, eq. 1-2), with the size parameters fitted by weighted least squares
against the reported quadrant radii (eq. 7).

Using NHC's construction rather than inventing one is the point. A forecaster
working a WestPac system should see a field built the same way as the Atlantic
grid they saw last week - same vortex shape, same asymmetry mechanism, same
conventions. Consistency across basins is worth more here than any local
improvement.

Two things about the output are easy to mistake for bugs:

- **The field does not pass exactly through the reported radii, deliberately.**
  GTCM minimises *wind* error rather than radius error, because forcing the
  radii produces unrealistic structure - the guide says so under eq. 7. The
  earlier per-quadrant construction did hit every ring exactly and produced a
  field with a kink at each quadrant boundary. The trade was made in favour of
  a coherent field.
- **Reported radii are quadrant *maxima*; the vortex represents the quadrant
  *average*.** The guide converts with a 0.85 factor, so modelled rings sit
  about 15% inside the reported ones. That is the model working as specified.

Two departures from the guide, both commented where they occur: the profile is
tapered beyond the modelled 34 kt radius so the GFE insert terminates (NHC
leaves its grids missing out there and lets the receiving office blend), and
step 4's boundary-layer / land-roughness reduction is **not** implemented - it
needs the USGS land-surface database, so the field is marine exposure
everywhere and will be too strong over land.

### The web app

Three pages from one Apps Script deployment - a live view of the five current
bulletins, an archive of 220 real storms replayed through the same code, and
the verification findings. `web/TCWind_JTWC/README.md` has the detail,
including why `Vortex.html` and `Theme.html` are single-source and must stay
that way. Deploying is covered by `.claude/skills/clasp/SKILL.md`.

The archive draws on IBTrACS post-season best track: 100 WestPac storms
(`jtwc_wp`, 2005-2024), 63 North Atlantic and 57 East Pacific (`hurdat_atl` /
`hurdat_epa`, 2004-2024). Those cutoffs are not arbitrary - R64 reporting is
essentially absent before them, so an earlier storm would show the tool
"failing" when there is simply nothing to compare against.

### What is verified, and what is not

**Verified:** that the field is internally coherent, and consistent with JTWC's
and NHC's own post-season analyses. The switch to GTCM was made for physical
plausibility, so that is what `tests/tcwind_jtwc/verify_gtcm.py` measures -
azimuthal kink at the quadrant bisectors, radial slope breaks and steps at the
profile knots, monotonicity, and whole-field roughness. GTCM is smoother than
the construction it replaced on every one of those.

**Not verified:** anything about the wind that actually blew. There is no
comparison against scatterometer, buoy or any other observation; best track
gives analyst-assigned radii quantized to 5 nm, not gridded truth. The forecast
hours are unverified too - every check scores against best-track *analysis*
times, so nothing here says whether the tau-96 field is any good.

The claim this tool can defend is that **it renders faithfully what JTWC said,
in the shape NHC would have rendered it.** Not that the wind is right.

### Running the checks

```bash
pip install numpy
python3 tests/tcwind_jtwc/test_parser_golden.py       # parser vs committed fixtures
python3 tests/tcwind_jtwc/compare_py_js.py            # Python vs both JavaScript ports
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
python3 tests/tcwind_jtwc/compare_vortex_methods.py   # gtcm vs the retired perquad
python3 tests/tcwind_jtwc/verify_gtcm.py              # regenerates the findings data
```

The first three are hermetic - real bulletins are committed, so they need only
numpy and node, with no network - and are worth running before every push.
`verify_gtcm.py` regenerates `tests/tcwind_jtwc/data/gtcm_findings.json`, which
is what the findings page displays; that page hardcodes no statistics.

### Known gaps

- No land-roughness reduction (guide step 4); the field is too strong over land.
- The forecast hours are unverified.
- The outer taper is a local heuristic, not part of GTCM.
- `tests/tcwind_jtwc/README.md` still describes a superseded Rmax-vs-RMW
  framing and coefficients that no longer exist.
