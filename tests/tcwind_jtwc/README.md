# TCWind_JTWC test / evaluation suite

Regression and verification tooling for `GFE/procedures/TCWind_JTWC.py`
and its web-preview port, `web/TCWind_JTWC/{Code.gs,Index.html}`. Seven
independent questions, seven scripts (`besttrack_common.py` is shared
plumbing, not a check on its own):

| Question | Script |
|---|---|
| Does the parser still produce what we expect on known inputs? | `test_parser_golden.py` |
| Do the Python and JS ports actually agree with each other? | `compare_py_js.py` |
| Does the GFE `Procedure` (dialog-less, end to end) still run against real bulletins outside AWIPS? | `test_procedure_harness.py` |
| Is the tool's physics (Rmax) actually right, checked against ground truth? | `verify_besttrack_rmax.py` |
| Can that regression be made to fit WestPac better? | `fit_westpac_rmax.py` |
| Where does that ground truth for the web app come from? | `prep_besttrack_data.py` |
| Is the field's overall *size* realistic, checked against something the model never sees? | `verify_besttrack_roci.py` |
| Is the field's *shape* between/beyond the reported radii realistic? | `verify_besttrack_holland.py` |

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

**`verify_besttrack_rmax.py`** compared the tool's Rmax against real
JTWC post-season best-track RMW (IBTrACS, `agency=jtwc_wp`, WP basin,
2001-2024, n=16,103) - something no real-time bulletin can ever check
against, since JTWC doesn't report an observed Rmax operationally. The
original Willoughby (2006) coefficients underestimated Rmax by ~10 nm
on average, worst for weak systems (TD: bias -22 nm on the 3-year
sample this was first measured on, and the regression didn't even
correlate with the true value in the right direction, r=-0.28) and much
better for typhoon-strength systems.

**`fit_westpac_rmax.py`** refit the same functional form (still
exponential in intensity and latitude) against this data, split by
storm into 80% train / 20% held-out test so the validation isn't just
measuring how well it memorized the fitting data. Out-of-sample on the
held-out storms: bias -11.5 nm -> -3.3 nm, MAE 14.4 -> 10.7 nm, RMSE
20.7 -> 16.7 nm, r 0.43 -> 0.50. **This refit is now what's live** in
both `willoughbyRmax()` implementations (coefficients A=97.892,
B=-0.023895, C=0.002528, replacing Willoughby's A=46.4, B=-0.0155,
C=0.0169).

Re-running `verify_besttrack_rmax.py` against the now-live regression
(full dataset, in-sample): bias -10.2 -> -2.7 nm, MAE 13.1 -> 9.7 nm,
RMSE 19.5 -> 15.5 nm, r 0.51 -> 0.59. By category, the refit fixed the
*systematic* underestimate everywhere (TD bias -22 -> -3.6 nm, TS -15.5
-> -7.6 nm, TY+ -3.2 -> -2.5 nm) but weak systems are still barely
predictable at all beyond that average correction - TD's correlation is
r=0.04, essentially no skill storm-to-storm even now. That's an honest
limit of a 2-parameter (intensity, latitude) regression, not something
a coefficient refit can fix: expect a WestPac Rmax estimate to be
unbiased on average for a weak system, but not to be *right* for any
particular one. The radii clamp still helps on top of that when it
binds (22% of records, bias -6.0 nm vs -4.3 nm where it doesn't). Full
breakdown in each script's output.

## Archived Cases and Findings panels (in the web app)

`prep_besttrack_data.py` turns the same IBTrACS WP-basin archive into
three datasets baked into the deployed web app itself
(`web/TCWind_JTWC/BestTrackData.gs`, ~1 MB, generated - don't hand-edit;
`tests/tcwind_jtwc/data/*.json` holds the same data for reference), and
exposed via `getBestTrackSample()`/`getBestTrackScatter()`/
`getHollandZoneSummary()` in `Code.gs`, the same `google.script.run`
idiom as fetching live bulletins. These feed two separate destinations
- "Archived Cases" (a panel inside the map tool, `web/TCWind_JTWC/
Index.html`, for the storm-by-storm viewer) and "Findings" (its own
standalone page, `web/TCWind_JTWC/Findings.html`, for the aggregate
charts and a written summary) - so picking a case to inspect and
reading the overall verification results aren't competing for the same
screen, and Findings has its own linkable/shareable URL
(`<web app URL>?page=findings`) rather than living as a panel toggled
inside the live tool. `Code.gs`'s `doGet(e)` routes on `e.parameter.page`
to serve one template or the other, both via `HtmlService.createTemplateFromFile`
so each can inject the deployment's own URL (`<?= baseUrl ?>`, from
`ScriptApp.getService().getUrl()`) for the link between them:

- **A 100-storm random sample** (2001-2024, seeded, so it's
  reproducible; capped at 100 so the storm-picker dropdown and the map
  stay responsive - the underlying archive has ~2,200 eligible storms),
  each with its full track: position, Vmax, reported wind radii, and
  observed RMW/ROCI wherever JTWC's post-season analysis reported them.
  The "Archived Cases" tab builds a synthetic `storm` object from
  whichever one is picked, in the exact shape a parsed live bulletin
  produces, so every existing map/diagnostics function (`drawRadii`,
  `drawField`, `resolveRmax`, the time-history and azimuthal-profile
  charts) draws it with no changes at all. The only new drawing code
  is a dashed ring each for the storm's actual RMW (magenta) and ROCI
  (teal), a Rmax-vs-RMW delta in the status line, and - in the
  azimuthal-profile chart - an overlaid Holland (1980) curve, solved
  from the same Vmax/Rmax/R34 anchors, so its divergence from the
  tool's own quadrant curves is visible per-storm.
- **Every usable record in the full archive** (~16,200, not just the
  100-storm sample), compacted to `[vmax, lat, rmw, r64min, r50min,
  r34min]` per record - just enough for the client to run the real
  `resolveRmax()` unmodified (its clamp only ever needs the minimum
  nonzero quadrant at a threshold, so that's all that's shipped, rather
  than duplicating the clamp formula in the prep script). Drawn as a
  scatter (predicted Rmax vs actual RMW, colored by intensity category,
  with a live-computed bias/MAE/RMSE) - this is `verify_besttrack_rmax.py`
  made visible and explorable in the tool itself, rather than a
  terminal report.
- **The Holland zone-divergence summary** (mean/90th-percentile
  |tool-Holland| per radial zone, from `verify_besttrack_holland.py`'s
  own computation, condensed) - drawn as a small bar chart next to the
  scatter, so the "near-core disagreement is worst" finding is visible
  as a chart rather than only as a paragraph of numbers.

Both panels carry a written guide (not just chart captions): Archived
Cases explains how to read the map's rings/raster for whichever storm
is picked; Findings explains where the live data and the best-track
data each come from and states the headline conclusions from all three
checks in plain language - so a forecaster using either tab doesn't
have to separately go read this file or the scripts' terminal output
to know what to make of it.

2001 is the cutoff for both datasets: JTWC's WestPac wind-radii/RMW
reporting is present on well under half of records before that, so an
older storm would show the panel "failing" when really there's just
nothing to compare against.

Re-run `prep_besttrack_data.py` (needs a WP-basin IBTrACS CSV, same as
the other scripts) and re-push `BestTrackData.gs` whenever it's worth
refreshing this - e.g. after a season closes out and JTWC's best track
for it is finalized. As of this writing, 2001-2024 is not a cutoff we
chose: it's the full range with usable data. JTWC's WestPac wind-radii/
RMW reporting is essentially absent before 2001 (checked year by year,
0% coverage), and 2025-2026 aren't in IBTrACS yet even in a freshly
re-fetched copy - best-track finalization runs a season or more behind.

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
