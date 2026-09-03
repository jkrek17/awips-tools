# awips-tools

AWIPS/GFE tools and procedures for the Ocean Prediction Center.

Most of this repository is a collection of independent GFE Smart Tools and
procedures — model blending, spot forecasts, visibility and weather grid
population, ice accretion, and so on. They share the helper modules in
`GFE/utilities/` but are otherwise unrelated to each other.

One project in here is larger than the rest and has its own subdirectories, so
it gets the rest of this file.

---

# TCWind_JTWC — a gridded wind field for JTWC tropical cyclones

**EXPERIMENTAL. NOT OPERATIONALLY VETTED.** Every grid needs forecaster review
before it informs any product.

## The problem

When a tropical cyclone threatens the Atlantic or East Pacific, NHC issues two
things: the TCM text advisory, and a **gridded** TCM built from it. OPC ingests
that grid directly and blends it into the Fcst wind field.

JTWC issues only the text. For the NW Pacific there is no grid, so there is
nothing to ingest and the forecaster is left constructing a tropical wind field
by hand, or doing without.

**This project builds the missing grid.** It reads the JTWC warning text and
constructs the wind field the bulletin describes.

## The approach, and why

The field is built with **NHC's own GTCM/WTCM vortex model**, implemented from
the *Gridded TCM User Guide v1.9.1* (Santos & DeMaria, 4 Dec 2023): one
symmetric modified Rankine vortex (eq. 3) plus a wavenumber-1 motion asymmetry
(Schwerdt 1979, eq. 1–2), with the size parameters fitted by weighted least
squares against the reported quadrant radii (eq. 7).

Using NHC's construction rather than inventing one is the point. An OPC
forecaster working a WestPac system should see a wind field built the same way
as the Atlantic grid they saw last week — same vortex shape, same asymmetry
mechanism, same conventions. Structural consistency across basins is worth more
here than any local improvement.

Two consequences worth understanding before reading the output:

- **The field does not pass exactly through the reported radii, by design.**
  GTCM minimises *wind* error, not radius error, because forcing the radii
  produces unrealistic structure (the guide says so explicitly, under eq. 7).
  The tool's earlier per-quadrant construction did hit every ring exactly, and
  produced a field with a kink at each quadrant boundary. The trade was made
  deliberately in favour of a physically coherent field.
- **Reported radii are quadrant *maxima*; the vortex represents the quadrant
  *average*.** The guide converts between them with a 0.85 factor, so modelled
  rings sit systematically ~15% inside the reported ones. That is the model
  working as specified, not an error — it is the single most misread number in
  the output.

Two documented departures from the guide, both commented where they occur:

1. The profile is tapered beyond the modelled 34 kt radius so the GFE insert
   terminates. NHC leaves its grids missing out there and lets the receiving
   office blend.
2. Step 4's boundary-layer / land-roughness reduction is **not** implemented —
   it needs the USGS land-surface database. The field is marine-exposure
   everywhere and will be too strong over land.

## What is here

```
GFE/procedures/TCWind_JTWC.py      the GFE procedure - the operational deliverable
web/TCWind_JTWC/                   Apps Script web app: live tool, archive, findings
tests/tcwind_jtwc/                 parser goldens, Python/JS parity, GTCM verification
.claude/skills/clasp/              how to deploy the web app
```

### The GFE procedure

`TCWind_JTWC.py` fetches the five NW Pacific JTWC warnings from the AWIPS text
database, parses them, builds a GTCM field per forecast hour, and inserts it
over the background wind grid. `VORTEX_METHOD` selects `"gtcm"` (default) or
`"perquad"` (the retired per-quadrant construction, kept for comparison).
Tunables are at the top of the file and are deliberately not exposed in the
dialog — none of them is a per-run decision.

The parser and vortex math have no AWIPS dependencies, so the file runs
standalone for testing.

### The web app

Three pages, served from one Apps Script deployment:

| page | what it is for |
|---|---|
| `?page=live` (default) | the five live JTWC bulletins, parsed, on a map, with the fit diagnostics |
| `?page=archive` | 220 real storms across three basins, replayed through the same code |
| `?page=findings` | what the verification actually shows, and what it does not |

`Vortex.html` is the **single** client-side source of truth for the wind-field
math and the parser; `Theme.html` is the single source for the design system.
Every page includes both. This is not stylistic: duplicated logic has caused
four separate bugs in this project — a second `resolveRmax()` that used `<=`
where the tool used `<`, a second `parseJTWC()`, a second `r34` calculation in
the verification, and a second colour palette. Three of them shipped wrong
numbers. Do not add a fifth copy.

`Code.gs` must keep its own server-side parser, because Apps Script cannot
include an HTML file's script server-side. `parserFingerprint()` and
`checkParserParity()` exist to detect that copy drifting.

### The archive

220 storms from IBTrACS post-season best track, browsable and comparable:

| basin | agency | seasons | storms |
|---|---|---|---|
| West Pacific | `jtwc_wp` | 2005–2024 | 100 |
| North Atlantic | `hurdat_atl` | 2004–2024 | 63 |
| East Pacific | `hurdat_epa` | 2004–2024 | 57 |

The season cutoffs are not arbitrary: R64 reporting is essentially absent
before 2004 in the NHC basins and before 2005 for JTWC WestPac, so an earlier
storm would show the tool "failing" when there is simply nothing to compare
against.

The archive exists so the tool can be evaluated on cases where the answer is
known. Best track carries what a live bulletin never does — observed RMW, ROCI,
the storm-nature flag, distance to land.

## What is verified, and what is not

**Verified:** that the field is internally coherent, and that it is consistent
with JTWC's and NHC's own post-season analyses. The switch to GTCM was made for
physical plausibility, so that is what `tests/tcwind_jtwc/verify_gtcm.py`
measures — azimuthal kink at quadrant bisectors, radial slope breaks and steps
at the profile knots, monotonicity, and whole-field roughness. GTCM is smoother
than the construction it replaced on every one of those.

**Not verified:** anything about the wind that actually blew. There is no
comparison against scatterometer, buoy, or any other observation. Best track
gives analyst-assigned radii quantized to 5 nm, not gridded truth. The forecast
hours are unverified — every check scores against best-track *analysis* times,
so nothing here says whether the tau-96 field is any good.

The honest claim is: **this renders faithfully what JTWC said, in the same
shape NHC would have rendered it.** Not that the wind is right.

## Running the checks

```bash
pip install numpy
python3 tests/tcwind_jtwc/test_parser_golden.py       # parser vs committed fixtures
python3 tests/tcwind_jtwc/compare_py_js.py            # Python vs both JS ports
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
python3 tests/tcwind_jtwc/compare_vortex_methods.py   # gtcm vs perquad
python3 tests/tcwind_jtwc/verify_gtcm.py              # regenerates the findings data
```

The first three are hermetic — real bulletins are committed, so they need only
numpy and node, with no network. They are worth running before every push.

`verify_gtcm.py` regenerates `tests/tcwind_jtwc/data/gtcm_findings.json`, which
is what the findings page displays. That page hardcodes no statistics.

## Deploying

See `.claude/skills/clasp/SKILL.md`. Briefly:

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

## Known gaps

- No land-roughness reduction (guide step 4); the field is too strong over land.
- Forecast hours are unverified.
- The outer taper is a local heuristic, not part of GTCM.
- `tests/tcwind_jtwc/README.md` still describes a superseded Rmax-vs-RMW
  framing and coefficients that no longer exist.
