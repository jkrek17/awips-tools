# awips-tools

AWIPS/GFE tools and procedures for the Ocean Prediction Center.

Most of this repository is a collection of independent GFE Smart Tools and
procedures — model blending, spot forecasts, visibility and weather grid
population, ice accretion, and so on. They share the helper modules in
`GFE/utilities/` but are otherwise unrelated to each other.

One project in here is larger than the rest and has its own subdirectories, so
it gets the rest of this file.

---

# TCWind_JTWC - a gridded wind field for JTWC tropical cyclones

**EXPERIMENTAL. NOT OPERATIONALLY VETTED.** Every grid needs forecaster review
before it informs any product.

## The problem

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

## What is here

```
GFE/procedures/TCWind_JTWC.py      the GFE procedure - the operational deliverable
web/TCWind_JTWC/                   Apps Script web app: live tool, archive, findings
tests/tcwind_jtwc/                 parser goldens, Python/JS parity, GTCM verification
.claude/skills/clasp/              how to deploy the web app
```

### The GFE procedure

`TCWind_JTWC.py` fetches the five NW Pacific JTWC warnings from the AWIPS text
database, parses them, builds a wind field per forecast hour, and inserts it
over the background wind grid. `VORTEX_METHOD` selects `"gtcm"` (the shipped
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

### The web app

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

### The archive

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

## What the field is, and how it is built

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

## What the evidence actually shows

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

## Known gaps

- No land-roughness reduction; the field is too strong over land.
- Forecast hours are unverified: every check scores against best-track
  analysis times, not forecast bulletins.
- The outer taper is a local heuristic, not a documented part of GTCM.
- No comparison against any real wind observation, of any kind.

## Running the checks and deploying

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
