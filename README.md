# awips-tools

AWIPS tools and procedures.

## Contents

| Path | What it is |
|---|---|
| `cyclone_phase_space/` | Hart cyclone phase space as AWIPS D2D derived parameters: the AWIPS install tree, a storm-centered reference implementation, tests, guides and the published article. See `cyclone_phase_space/README.md`. |
| `docs/cps/` | Not committed - staged from `cyclone_phase_space/article/` by the Pages workflow (`.github/workflows/pages.yml`) on every build. |
| `GFE/` | GFE procedures, smart tools and shared utilities. |
| `legacy_tools/` | Earlier versions kept for reference; see `legacy_tools/VERSION_CONTROL.md`. |
| `tests/tcwind_jtwc/` | Parser goldens, Python/JavaScript parity, and the GTCM verification. |
| `GFE/procedures/TCWind_JTWC.py` | Builds GFE Wind grids from JTWC tropical cyclone warnings. See below. |
| `GFE/procedures/CreateXML_WindHazards.py` | Builds a PGEN XML of gale/storm/hurricane force wind polygons for F000-024 and F024-048, plus pmsl Highs and Lows. See below. |
| `tests/create_xml_windhazards/` | Harness test for that procedure - fakes the AWIPS and A2Graphics surface and asserts against the XML it writes. |
| `web/TCWind_JTWC/` | Google Apps Script web app for that tool: live JTWC and NHC bulletins, a best-track archive, and the verification findings. |
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

## TCWind_JTWC - a gridded wind field for JTWC tropical cyclones

**EXPERIMENTAL. NOT OPERATIONALLY VETTED.** Every grid needs forecaster review
before it informs any product.

### The problem

When a tropical cyclone threatens the Atlantic or East Pacific, NHC issues two
things: the TCM text advisory, and a **gridded** TCM built from it. OPC ingests
that grid directly and blends it into the Fcst wind field.

JTWC issues only the text. For the NW Pacific there is no grid, so there is
nothing to ingest, and the forecaster is left constructing a tropical wind
field by hand, or doing without.

**This project builds the missing grid.** It reads the JTWC warning text and
constructs the wind field the bulletin describes, using NHC's own GTCM/WTCM
vortex model rather than inventing a new one, so a WestPac grid looks and
behaves like the Atlantic and East Pacific grids a forecaster already knows.

### What is here

```
GFE/procedures/TCWind_JTWC.py      the GFE procedure - the operational deliverable
web/TCWind_JTWC/                   Apps Script web app: live tool, archive, findings
tests/tcwind_jtwc/                 parser goldens, Python/JS parity, GTCM verification
.claude/skills/clasp/              how to deploy the web app
```

#### The GFE procedure

`TCWind_JTWC.py` fetches tropical cyclone forecast text from the AWIPS text
database, parses it, builds a wind field per forecast hour, and inserts it
over the background wind grid. It reads two products across four basins:

| Basin | Product | AWIPS PILs | Parser |
|---|---|---|---|
| WP | JTWC WTPN warning | `NFDTCPWP1-5` | `parseJTWC()` |
| AT | NHC TCM forecast/advisory | `MIATCMAT1-5` | `parseTCM()` |
| EP | NHC TCM forecast/advisory | `MIATCMEP1-5` | `parseTCM()` |
| CP | CPHC TCM forecast/advisory | `HFOTCMCP1-5` | `parseTCM()` |

Both parsers return the identical `(taus, header)` shape, so everything
downstream is shared and knows nothing about which product produced it.
`parseBulletin()` chooses the parser by inspecting the text, not by trusting
the bin the bulletin arrived in — an office can put anything in any PIL, and a
wrong guess would yield a confident parse of the wrong shape rather than an
error. The dialog has a basin row and a per-slot row; a PIL runs only if both
agree.

JTWC's WestPac is the case with no gridded alternative and the reason this
tool exists. **NHC and CPHC do publish a gridded TCM**, and AWIPS already
ships `TCMWindTool` to consume it — for those basins that grid stays
authoritative, and this is a text-only fallback and cross-check rather than a
replacement. `VORTEX_METHOD` selects `"gtcm"` (the shipped
default) or `"perquad"` (the retired per-quadrant construction, kept only for
comparison). Tunables are at the top of the file and are deliberately not
exposed in the dialog: none of them is a per-run decision.

The parser and vortex math have no AWIPS dependencies, so the file runs
standalone for testing.

The dialog's "Run test case" toggle runs the procedure end to end against a
bundled real bulletin, translated onto the office's own grid and rebased onto
"now" — useful for confirming the install and seeing example output with no
live storm in the text database (outside NW Pacific season, or between
storms). It always writes to the preview grid only, never Fcst Wind.

#### The web app

Three pages, served from one Apps Script deployment:

| page | what it is for |
|---|---|
| `?page=live` (default) | the five live JTWC bulletins, parsed, on a map, with the fit diagnostics |
| `?page=archive` | 220 real storms across three basins, replayed through the same code, with a cross-storm comparison tab |
| `?page=findings` | a plain-language summary of what the verification shows, and the full technical detail behind it |

`Vortex.html` is the single client-side source of truth for the wind-field
math and the parser. `Theme.html` is the single source for the design system.
`Help.html` is the single source for the glossary that all three pages
hover-link technical terms to. Every page includes all three. This is not
stylistic: duplicated logic has caused several real bugs in this project,
including a second `resolveRmax()` that disagreed with the first and a second
colour palette. Do not add a new copy of anything already in one of these
files.

`Code.gs` must keep its own server-side parser, because Apps Script cannot
include an HTML file's script server-side. `parserFingerprint()` and
`checkParserParity()` exist to detect that copy drifting.

#### The archive

220 storms from IBTrACS post-season best track, browsable and comparable:

| basin | agency | seasons | storms |
|---|---|---|---|
| West Pacific | `jtwc_wp` | 2005-2024 | 100 |
| North Atlantic | `hurdat_atl` | 2004-2024 | 63 |
| East Pacific | `hurdat_epa` | 2004-2024 | 57 |

The season cutoffs are not arbitrary: 64 kt radii are reported as zero
everywhere before those years in the respective basins, so an earlier storm
would show the tool "failing" when there is simply nothing to compare against.

The archive exists so the tool can be evaluated on cases where the answer is
known. Best track carries what a live bulletin never does: observed RMW, ROCI,
the storm-nature flag, and distance to land.

### What the field is, and how it is built

The field is built with NHC's own GTCM/WTCM vortex model, implemented from the
*Gridded TCM Users Guide v1.9.1* (Santos & DeMaria, 4 Dec 2023): one symmetric
modified Rankine vortex plus a wavenumber-1 motion asymmetry (Schwerdt 1979),
with the size parameters fit by weighted least squares against the reported
quadrant radii. Using NHC's own construction rather than inventing one is the
point: structural consistency across basins is worth more here than any local
improvement.

Two things worth understanding before reading the output:

- **The field does not pass exactly through the reported radii, by design.**
  GTCM minimises *wind* error, not radius error, because forcing the radii
  produces unrealistic structure (the guide says so explicitly). The earlier
  per-quadrant construction did hit every ring exactly, and produced a field
  with a kink at each quadrant boundary; the trade toward a physically
  coherent field was made deliberately, and both halves of that trade are on
  the Findings page.
- **Reported radii are quadrant maxima; the vortex targets the quadrant
  average**, per the guide's own conversion factor. Modelled rings therefore
  sit inside the reported ones by design. That is the model working as
  specified, not an error, and it is the single most misread number in the
  output.

Two documented departures from the guide, both commented where they occur:

1. The profile is tapered beyond the modelled 34 kt radius so the GFE insert
   terminates. NHC's own grids are simply left missing out there.
2. The guide's boundary-layer / land-roughness reduction is **not**
   implemented. The field is marine exposure everywhere and is too strong
   over land.

### What the evidence actually shows

The `?page=findings` page is the source of truth for this, not this file.
Numbers are deliberately not repeated here: they change every time the
verification script is re-run against a refreshed archive, and a number
copied into this README would drift out of date silently. Read the Findings
page for the current figures behind each of these plain statements:

- The field is coherent, and built from the warning text alone, with no
  observations and no climatology beyond the guide's own fitted shape.
- It predicts withheld radii with real, measurable skill: fit to some of a
  bulletin's reported radii, it can predict a radius withheld from the fit.
- On that same held-out test it is **not** more accurate than the
  per-quadrant construction it replaced, and it misses a real share of 64 kt
  targets outright, something the per-quadrant construction never does.
- Modelled rings sit inside the reported radii by design, for the
  quadrant-maximum/quadrant-average reason above, not because of a fitting
  error.
- Accuracy is measurably worse for storms undergoing extratropical
  transition than for purely tropical ones.
- The field is untested over land and against any real observation (buoy,
  aircraft, scatterometer). Everything is measured against post-season
  best-track analyses, which are themselves a reanalysis product, not ground
  truth.

See Findings' "In one minute" section for the current numbers behind each
point above, and its "Technical detail" section for the estimator
definitions, the caveats, and this page's own list of what it asked for and
did not get.

### Known gaps

- No land-roughness reduction; the field is too strong over land.
- Forecast hours are unverified: every check scores against best-track
  analysis times, not forecast bulletins.
- The outer taper is a local heuristic, not a documented part of GTCM.
- No comparison against any real wind observation, of any kind.

### Running the checks and deploying

```bash
pip install numpy
python3 tests/tcwind_jtwc/test_parser_golden.py       # parser vs committed fixtures
python3 tests/tcwind_jtwc/compare_py_js.py            # Python vs both JS ports
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
python3 tests/tcwind_jtwc/test_procedure_harness.py   # the GFE Procedure, end to end, outside AWIPS
python3 tests/tcwind_jtwc/verify_gtcm.py              # regenerates the findings data
```

The first four are hermetic: real bulletins are committed, so they need only
numpy and node, with no network. They are worth running before every push.
`verify_gtcm.py` regenerates `tests/tcwind_jtwc/data/gtcm_findings.json`,
which is what the Findings page displays; that page hardcodes no statistics
of its own.

See `tests/tcwind_jtwc/README.md` for the full suite (thirteen scripts, what
each one answers, and the fixtures behind them), and
`web/TCWind_JTWC/README.md` for the web app's own files, its "one copy of
everything" rule, and its own pre-push checks.

To deploy the web app, see `.claude/skills/clasp/SKILL.md` for the full
non-interactive `clasp` flow, including from a container. Briefly:

```bash
cd web/TCWind_JTWC
clasp login && clasp push
clasp list-deployments
clasp deploy -i <existing deployment id> -d "what changed"
```

`clasp deploy` **without `-i` mints a new deployment with a new URL**, leaving
everyone holding the old link on the old build.

`BestTrackData.gs` (~2 MB) is generated by `prep_besttrack_data.py`. Never
hand-edit it.

## CreateXML_WindHazards - warning wind polygons as PGEN XML

`GFE/procedures/CreateXML_WindHazards.py` writes **one** PGEN XML per run
holding, for each of the F000-024 and F024-048 periods, closed polygons at
gale (34 kt), storm (48 kt) and hurricane (64 kt) force, plus mean sea level
pressure Highs and Lows. It appears under GFE's **Consistency** menu.

It follows `CreateXML.py`: it subclasses `A2GraphicsFunctions` and leaves the
product, layer, pressure extrema and `storeXML` work to the site's own
`XmlUtils`/`MathUtils` and the `A2GraphicsConfig` dictionaries (`outDir`,
`pgenProd_dict`, `pgenAttr_dict["Features"]`).

### The cycle

`Cycle: Auto` takes the most recent 00/06/12/18Z cycle at or before now, so a
20Z run uses 18Z. Naming a cycle explicitly takes the most recent occurrence
of that hour at or before now - asking for `18z` at 05Z means yesterday's 18Z.

All times are UTC, and epoch seconds come from `calendar.timegm`, not
`datetime.timestamp()`, so the workstation's `TZ` cannot shift which grids get
read.

### The polygons

Each period's polygons come from the **per-gridpoint maximum** Wind magnitude
over every grid in the window (F000, F006 ... F024 for the first period; F024,
F030 ... F048 for the second), so a polygon covers anywhere reaching that force
at any point in the period. That field is lightly smoothed (`SMOOTH_PASSES`),
optionally zeroed over the `Land` edit area, then contoured. Contours smaller
than `MIN_POLYGON_AREA_DEG2` or `MIN_POLYGON_POINTS` are dropped as noise, and
longer ones are decimated to `MAX_POLYGON_POINTS` so the result stays editable
in PGEN. Polygons are emitted with `closed="true"`, which is also what joins the
ends of an area clipped by the edge of the domain.

`pmsl` is read at each period's **start** valid time (F000 and F024) and its
extrema go in a `Features` layer per period.

Layers are named per period - `Gale_F000-024`, `Storm_F000-024`,
`Hurricane_F024-048`, `Features_F024-048` - or all collapse into one `Default`
layer when the basin's `pgenProd_dict["saveLayers"]` is false.

### Telling the periods apart

`Color by:` chooses which dimension carries the color:

| Setting | Color | Period shown by | Severity shown by |
|---|---|---|---|
| `Threshold` (default) | `THRESHOLD_COLORS` - gale yellow, storm red, hurricane magenta | line pattern (`PERIOD_LINE_TYPES`: solid vs dashed) | color |
| `Period` | `PERIOD_COLORS` - cyan and orange | color | line width (`LINE_WIDTH`) |

`Hatch fill: On` additionally fills each polygon with its period's hatch
pattern (`PERIOD_FILL_PATTERNS`) instead of leaving it as an outline. Every one
of those tables is a module constant at the top of the file - retune without
touching the logic.

### One thing to check on the first run

The site's `XmlUtils` has no polygon writer to borrow (`CreateXML.py` only ever
asks it for contours, barbs, symbols and text), so `addPolygonToXml` emits the
PGEN `Line` element itself:

```xml
<Line pgenCategory="Lines" pgenType="LINE_SOLID" closed="true" filled="false"
      flagColor="false" lineWidth="3.0" sizeScale="1.0" smoothFactor="2">
  <colors red="255" green="255" blue="0" alpha="255"/>
  <linePoints Lat="34.9010" Lon="-51.0000"/>
</Line>
```

Compare that against a `Line` from a chart your existing procedures produce
(the `Isobars` layer is the closest thing). If the element or color spelling
differs at your site, `addPolygonToXml` is the only place to change.

See `tests/create_xml_windhazards/README.md` for the harness test.
