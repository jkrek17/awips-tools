# TCWind_JTWC test / evaluation suite

Regression and verification tooling for `GFE/procedures/TCWind_JTWC.py`
and its web-preview port, `web/TCWind_JTWC/{Code.gs,Index.html,Vortex.html,
Archive.html,Findings.html,Theme.html,Help.html}`. Thirteen questions,
thirteen scripts (`besttrack_common.py` is shared plumbing, not a check
on its own):

| Question | Script |
|---|---|
| Does the parser still produce what we expect on known inputs? | `test_parser_golden.py` |
| Do the Python and JS ports actually agree with each other? | `compare_py_js.py` |
| Does the GFE `Procedure` (dialog-less, end to end) still run against real bulletins outside AWIPS? | `test_procedure_harness.py` |
| How do the two wind-field constructions (GTCM, the shipped default, vs the retired per-quadrant build) compare - ring reproduction and field difference? | `compare_vortex_methods.py` |
| Is GTCM's field smoother than per-quadrant's (the actual reason for the switch), and does GTCM predict anything it wasn't fit to? Builds `data/gtcm_findings.json`, everything `Findings.html` shows. | `verify_gtcm.py` |
| Fit GTCM/perquad to a SUBSET of one record's reported radii and score the prediction of the radii withheld - the one genuine held-out-skill test in this suite. | `verify_holdout.py` |
| Do the ring-fit and holdout numbers above hold up near land and during extratropical/subtropical transition, or do they quietly get worse exactly where it matters operationally? | `verify_stratified.py` |
| Is the tool's physics (Rmax) actually right, checked against ground truth? SUPERSEDED under the shipped GTCM default - see the script's own header. | `verify_besttrack_rmax.py` |
| Can that regression be made to fit WestPac better? SUPERSEDED alongside its parent. | `fit_westpac_rmax.py` |
| Where does that ground truth for the web app come from? | `prep_besttrack_data.py` |
| Is the field's overall *size* realistic, checked against something the model never sees? | `verify_besttrack_roci.py` |
| Is the field's *shape* between/beyond the reported radii realistic? | `verify_besttrack_holland.py` |
| Does accuracy hold up near land / during transition? SUPERSEDED by `verify_stratified.py` for the Findings pipeline - kept as a standalone, WP-only, CSV-driven check of the legacy Rmax path. | `verify_besttrack_context.py` |

`verify_gtcm.py` is the one that matters most for what `Findings.html`
shows: it imports `compare_vortex_methods.py` for ring/field numbers,
`verify_holdout.py` for the held-out-skill block, and `verify_stratified.py`
for the by-nature/by-land blocks, and writes all of it plus its own
coherence measurements to `data/gtcm_findings.json` in one run. See its
docstring for the full schema (including the `holdout`/`byNature`/`byLand`
additions) and `python3 verify_gtcm.py --help` for the runtime knobs.

## Setup

```bash
pip install numpy          # TCWind_JTWC.py needs it; not required outside GFE otherwise
```

Node is only needed for `compare_py_js.py` (drives `tools_js.js`).

## Fixtures (`fixtures/`)

Two are **real, live JTWC bulletins**, fetched verbatim from
`https://tgftp.nws.noaa.gov/data/raw/wt/` on 2026-09-02 and committed
as-is:

- `real_2026-09-02_wtpn31_krovanh.txt` - Tropical Storm 22W (KROVANH),
  full R64/R50/R34 quadrant radii.
- `real_2026-09-02_wtpn32_saudel.txt` - Tropical Depression 17W
  (SAUDEL), no wind radii at all (too weak to warrant them) - the
  "unconstrained" case where the tool has nothing but the Willoughby
  regression to go on.

The rest are **hand-built synthetic fixtures**, clearly labeled as such
in their own REMARKS text, each targeting one parser edge case real
traffic didn't happen to exercise on the day these were pulled:

- `synth_dateline_crossing.txt` - forecast track crosses 180°.
- `synth_missing_vector_line.txt` - a middle forecast block with
  neither `MOVEMENT PAST SIX HOURS` nor `VECTOR TO ... HR POSIT`,
  exercising the bearing/speed motion backfill.
- `synth_subtropical_transition.txt` - a `BECOMING EXTRATROPICAL`
  sentence embedded in one block, then a standalone `EXTRATROPICAL`
  line in a later one, exercising the confidence downgrade (and that
  it stays downgraded once flagged).
- `synth_partial_radii_no_near.txt` - a `WARNING POSITION` line
  without the optional `NEAR`, and wind radii where two of four
  quadrants are `000 NM` (should stay 0, not be dropped or floored).
- `synth_month_rollover.txt` - reference date `31AUG26` with forecast
  DTGs rolling into September, exercising the DTG month/year rollover
  in `dtgToEpoch()`.

New fixtures need a golden snapshot before `test_parser_golden.py` will
check them: run it once (it writes `expected/<name>.json` for anything
missing), read the diff/output, and commit the snapshot once it looks
right.

## `tools_py.py` / `tools_js.js`

Thin CLI wrappers so the two implementations can be driven identically
from a shell:

```bash
python3 tools_py.py parse fixtures/real_2026-09-02_wtpn31_krovanh.txt
node    tools_js.js  parse fixtures/real_2026-09-02_wtpn31_krovanh.txt

python3 tools_py.py vortex snapshot.json points.json
node    tools_js.js  vortex snapshot.json points.json
```

`tools_js.js vortex` loads Index.html's `<script>` block truncated
right before the Leaflet map section (everything before that is pure
tunables + math, safe to run outside a browser) - see the comment at
the top of the file for why that has to happen in one `vm` call rather
than two.

## Findings so far

Running this suite once already found and fixed two real bugs (see git
history for the fixes):

1. **Word-wrapped pressure regex.** `MINIMUM CENTRAL PRESSURE` matched
   as a literal string in both parsers; JTWC's REMARKS text wraps at
   ~72 columns and that exact phrase lands split across a line break
   in real traffic (confirmed on the live KROVANH fixture above), so
   `pressureMb` silently came back `null` on an otherwise normal
   bulletin. Fixed to `\s+` between words in both languages.

2. **`r34` footprint fallback missing in JS.** For a storm with no
   reported wind radii at all (SAUDEL, above), Python's `buildVortex()`
   treats the footprint's outer radius as 3x Rmax so a weak/unreported
   system still gets a sensibly-sized insert region; the JS port had
   no equivalent and was using Rmax itself, giving the web preview a
   much smaller (and inconsistent-with-the-real-tool) footprint cutoff
   for exactly the kind of weak system where this matters most. Fixed
   by adding the same fallback to `vortexAt()`'s returned `r34`.

`compare_py_js.py` has one known, understood, benign residual left: a
sample point landing within about 1e-12 nm of an exact reported ring
radius can occasionally get sorted into a different piecewise segment
on the float32 (Python/GFE-grid-precision) side than on the float64
(JS) side, producing a <2 kt difference at that single point. Documented
in the script's docstring; not something a real (much coarser) grid can
actually trigger.

**Historical note, SUPERSEDED by the GTCM switch below** - kept because it
is real work that is still cited by name from shipped source (see
`verify_besttrack_rmax.py`'s own current header for exactly what still
applies and what does not): under `VORTEX_METHOD="gtcm"` (the shipped
default since the GTCM-era commits described in the next section), Rmax is
not regressed from climatology at all - `fitGTCM()` fits it (`rm`) directly
to the reported radii. `willoughbyRmax()`/`resolveRmax()` are only read by
the retired `"perquad"` construction now. The paragraphs below describe that
retired path, for the record:

**`verify_besttrack_rmax.py`** (as it ran under `"perquad"`) compared the
tool's Rmax against real JTWC post-season best-track RMW (IBTrACS,
`agency=jtwc_wp`, WP basin) - something no real-time bulletin can ever
check against, since JTWC doesn't report an observed Rmax operationally.
The original Willoughby (2006) coefficients underestimated Rmax by ~10 nm
on average, worst for weak systems, and much better for typhoon-strength
systems.

**`fit_westpac_rmax.py`** refit the same functional form (still exponential
in intensity and latitude), split by storm into 80% train / 20% held-out
test so the validation isn't just measuring how well it memorized the
fitting data. **This refit is now what's live** in both `willoughbyRmax()`
implementations - but the numbers actually compiled into
`GFE/procedures/TCWind_JTWC.py` today are **A=98.392, B=-0.025088,
C=0.003021**, fit against **13,834** real JTWC WestPac best-track records,
**2005-2024** (not the A=97.892/B=-0.023895/C=0.002528/2001-2024 figures a
previous revision of this file quoted - those did not match the shipped
source; `willoughbyRmax()`'s own docstring is the authority on this number,
not this file, precisely because this kind of drift has happened here
before). Out-of-sample on a held-out 20% of storms never used for fitting:
bias -9.4 nm -> -1.9 nm, MAE 12.4 nm -> 9.0 nm, vs the original Willoughby
coefficients over the same held-out storms. That's an honest limit of a
2-parameter (intensity, latitude) regression to begin with, which is
exactly why GTCM does not use it: `fitGTCM()` fits `rm` per storm-time
against whatever radii that specific bulletin reports, rather than only a
climatological function of Vmax and latitude. Whether that fitted `rm` is
actually a *better* RMW predictor than this legacy regression, especially
when the bulletin is thin, is checked directly (not assumed) in
`verify_holdout.py`'s `rmwContext` block - see just below.

### The GTCM switch: coherence, and does it predict anything it wasn't fit to?

The shipped default moved from the per-quadrant ("perquad") construction
above to GTCM (NHC's Gridded TCM/WTCM, one symmetric modified-Rankine
vortex plus a wavenumber-1 asymmetry, least-squares fit to the reported
radii) for **physical plausibility, not accuracy** -
`compare_vortex_methods.py` and `verify_gtcm.py` say this plainly in their
own headers, and it is worth repeating here because it changes how to read
every number in this subsection. GTCM does not try to pass through the
reported radii the way perquad does by construction; it fits the
quadrant-*average* wind (reported quadrant maximum x
`GTCM_QUAD_AVG_FACTOR`, 0.85 - a citation from the Gridded TCM Users Guide,
not a value measured anywhere in this project's own data, since IBTrACS
never reports a quadrant average to check it against).

**Coherence** (`verify_gtcm.py`'s `coherence` block) is the actual reason
for the switch, measured directly for the first time by this suite: how
smooth is each construction's field, independent of whether it reproduces
the reported radii. perquad interpolates four reported radii linearly in
azimuth, so it has a corner in the wind field at each quadrant bisector (45/
135/225/315 deg) *by construction*; GTCM is one analytic vortex and should
have none. Both a real (bisector) and control (0/90/180/270 deg, no corner
either way - the estimator's own noise floor) measurement are taken, so the
comparison is against each method's own floor, not an absolute threshold.
Run `verify_gtcm.py` yourself (`python3 verify_gtcm.py`, whole archive by
default now - see the runtime numbers it prints) for current figures; from a
sample run (`--basins WP --coherence-cases 20`, 20 storm-times): GTCM's
azimuthal kink at the bisector is 0.0042 kt/deg against its own control of
0.0038 kt/deg - indistinguishable from its own noise floor, i.e. no real
corner - while perquad's bisector value is 0.0662 kt/deg against a control
of 0.0019 kt/deg, roughly **35x** its own floor. Radial slope break at the
Rmax/knot corners tells the same story (perquad 2.34 kt/nm excluding the
outer taper vs GTCM 1.10 kt/nm). A real, if modest, coherence win, exactly
as advertised - and `coherenceDiagnostics.riStep` confirms the eq. (3)
continuity fix (commit 530f876) is live: measured step at `ri`, every run,
is 0.00 kt.

**Held-out skill** (`verify_holdout.py`, new): every OTHER check GTCM has
ever had - `compare_vortex_methods.ringFit`, `verify_gtcm.py`'s own
`fitQuality`, `verify_besttrack_holland.py` - either scores the field at
the exact points it was fit to (self-consistency, not a skill score) or
scores a *different* model (Holland). Nothing fit GTCM to a SUBSET of one
record's reported radii and scored its prediction of the radii withheld,
until now. Run against the full committed archive (WP+NA+EP pooled,
Vmax>64kt with R34/R50/R64 all reported, n=1,931 records / 127 distinct
storms):

| fit -> predict | method | bias (nm) | MAE (nm) | r | never reached |
|---|---|---|---|---|---|
| R34 -> R50 | gtcm | -10.0 | 17.1 | 0.64 | 0.8% |
| R34 -> R50 | perquad | -6.7 | 14.4 | 0.83 | 0.0% |
| R34 -> R64 | gtcm | +2.2 | 13.5 | 0.55 | 14.3% |
| R34 -> R64 | perquad | -0.4 | 11.0 | 0.60 | 0.0% |
| R34+R50 -> R64 | gtcm | -4.8 | 8.5 | 0.78 | 14.1% |
| R34+R50 -> R64 | perquad | +0.2 | 8.0 | 0.74 | 0.0% |
| `rm`/`resolveRmax()` vs actual RMW (full radii, context) | gtcm `rm` | -2.8 | 7.6 | 0.70 | n/a |
| `rm`/`resolveRmax()` vs actual RMW (full radii, context) | legacy regression | -6.1 | 7.6 | 0.62 | n/a |

Read the caveat in `verify_holdout.py`'s own docstring before over-reading
this table: `R34 -> R50/R64` is a deliberately *harder*, synthetic task than
the tool's real situation (a bulletin reporting R34 on a Vmax>64kt system
usually also reports R50), and `R34+R50 -> R64` is the more representative
row. On this evidence, honestly: **GTCM has no accuracy edge over the
method it replaced on the one genuine extrapolation test this archive can
build, and MAE-for-MAE is a bit behind it**, with a real gap in "never
reached" (a symmetric vortex fit to thin data sometimes cannot geometrically
reach a withheld ring at all; perquad's tangential interpolation always
can). Its `r` is competitive-to-better in the more realistic `R34+R50 ->
R64` row, which is some evidence GTCM's shape assumption pays off once it
has enough to work with. The one comparison GTCM's own live parameter
clearly wins is `rm` vs RMW when the fit sees everything - a smaller bias
than the legacy regression, at a comparable MAE. This is exactly the
coherence-vs-accuracy tradeoff the switch was framed as being about, made
concrete with a real number instead of an assumption: smoother is
confirmed; "also at least as accurate" is not, on the one test built to
check it. See `data/gtcm_findings.json`'s `holdout` block (schema
documented in `verify_holdout.py`'s and `verify_gtcm.py`'s docstrings) for
the full per-quadrant, per-basin breakdown, and `byNature`/`byLand` for
whether this holds up near land and during storm transition.

## Archive and Findings pages (in the web app)

`prep_besttrack_data.py` turns three basins of IBTrACS best track (WP
from JTWC, NA/EP from NHC HURDAT2 - see its own docstring for the exact
provenance of each) into `web/TCWind_JTWC/BestTrackData.gs` (generated,
do not hand-edit; `tests/tcwind_jtwc/data/archive_index.json` and
`archive_storms.json` hold the same data for reference/regeneration).
That file also embeds `tests/tcwind_jtwc/data/gtcm_findings.json`
verbatim (or `--rebundle` to refresh just that embed after re-running
`verify_gtcm.py`, without touching the archive or needing a CSV).
`Code.gs` serves it via three functions, the same `google.script.run`
idiom as fetching live bulletins: `getArchiveIndex()` (light per-storm
metadata, no track points, for the storm picker), `getArchiveStorm(sid)`
(one storm's full record series), and `getFindings()` (the entire
`gtcm_findings.json` object).

These feed two separate pages, not panels inside the live tool: `?page=archive`
(`Archive.html`) is the storm-by-storm browser - pick a storm and see it
rendered exactly like a live bulletin would be (`drawRadii`, `drawField`,
the time-history and azimuthal-profile charts, all unchanged), plus a
second tab that pools ring-fit and held-out statistics client-side over
whatever subset of the archive is currently filtered, broken out by
basin, storm nature and individual storm. `?page=findings`
(`Findings.html`) is the aggregate findings page: a short "In one
minute" summary, "What we measured and how" cards, then the full
technical detail behind every number, all read live from
`getFindings()` - the page hardcodes no statistics of its own.
`Code.gs`'s `doGet(e)` routes `e.parameter.page` to whichever template,
via `HtmlService.createTemplateFromFile`, injecting `baseUrl`, `page`,
`pageNote` and `version` into all three so each can link to the others
and show a consistent build string.

Re-run `prep_besttrack_data.py` (needs the basin CSVs, or `--rebundle`
for the findings-only refresh) and re-push `BestTrackData.gs` whenever
it is worth refreshing this - e.g. after a season closes out and best
track for it is finalized. The season windows themselves (WP 2005-2024,
NA/EP 2004-2024) are not arbitrary: 64 kt radii are reported as zero
everywhere before those years in the respective basins, so an earlier
storm would show the tool "failing" when there is simply nothing to
compare against.

## Beyond Rmax: is the wind field's *shape* actually right?

Every check above is either about Rmax specifically, or about points the
field is *built* to pass through exactly (the live tool's "fit check" is
always near zero at the reported radii, by construction - that's not
independent evidence the field is right, just that the algebra works).
Two more scripts check things the model never sees at all:

**`verify_besttrack_roci.py`** compares the tool's own radial wind
profile - literally the `buildVortex()` field, including motion
asymmetry from real consecutive best-track positions - against ROCI
(radius of the outermost closed isobar), which the model has no access
to. Caveat up front: ROCI is a *pressure*-based size measure; "radius
where modeled *wind* drops below N kt" is related but not the same
thing (Chavas & Emanuel 2010 found ROCI correlates with the theoretical
radius of vanishing wind, which is the closest analogue) - so this is a
same-order-of-magnitude plausibility/bias check, not an exact one, and
three thresholds (10/15/20 kt) are checked rather than picking one.
Result (n=16,251): **the tool's field is dramatically too small for
weak systems** - TD bias -83 to -109 nm depending on threshold, with
essentially zero skill (r=0.01) predicting which TD will be bigger or
smaller than another. That's not entirely a tool failure (TDs mostly
have no reported radii at all, so there's little for the field to be
built from, and ROCI is expected to run well outside R10-R20 anyway),
but it does confirm there's nothing in a radii-less TD bulletin for the
tool to construct a realistic areal extent from. TY+ systems tell a
different story: bias flips from oversized at the 10 kt threshold
(+77 nm - the exponential outer taper may be too slow for intense
storms specifically) to close to neutral at 20 kt (-11 nm), with decent
correlation throughout (r≈0.48) - the field's overall size is
considerably more trustworthy for a strong, well-observed system than a
weak one.

**`verify_besttrack_holland.py`** takes a different approach: fit an
independent, published model (Holland 1980, using its dimensionless
V(r) = Vmax*sqrt((Rmax/r)^B * exp(1-(Rmax/r)^B)) form) to the *same* two
anchors the tool has (Vmax/Rmax, and the storm's own reported R34),
solving for Holland's shape parameter B - then see how far Holland's
prediction and the tool's actual field diverge in between and beyond
those anchors, where there's no ground truth for either model to be
checked against directly. Two findings (n=8,572 records with both RMW
and R34 reported):
- Asked to predict R50 and R64 - values it was never fit to - Holland's
  simple 2-parameter curve gets respectably close to the real reported
  values (R50: bias +4.0 nm, r=0.84; R64: bias +9.4 nm, r=0.69). That's
  a useful benchmark: a lot of a storm's radial structure is recoverable
  from just Vmax, Rmax and one radius, which is reassuring context for
  judging the tool's own (exactly-correct-by-construction) R50/R64.
- Where the tool's own curve and Holland's curve disagree with each
  other (both anchored identically, so the gap is pure shape
  disagreement): it's worst **right next to the core**, between Rmax and
  R64 (mean |diff| 11.0 kt, spikes to 72.5 kt) and steadily improves
  moving outward (R64-R50: 7.5 kt, R50-R34: 3.7 kt, beyond R34: 4.4 kt).
  That's the region where two reasonable models disagree most - and
  it's also the eyewall/near-core region where getting the wind wrong
  matters most operationally. Worth flagging in the tool's own output
  as the zone with the least structural certainty, rather than treating
  every part of the field as equally trustworthy.
