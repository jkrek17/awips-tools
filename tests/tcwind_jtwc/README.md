# TCWind_JTWC test / evaluation suite

Regression and verification tooling for `GFE/procedures/TCWind_JTWC.py`
and its web-preview port, `web/TCWind_JTWC/{Code.gs,Index.html}`. Four
independent questions, four scripts:

| Question | Script |
|---|---|
| Does the parser still produce what we expect on known inputs? | `test_parser_golden.py` |
| Do the Python and JS ports actually agree with each other? | `compare_py_js.py` |
| Is the tool's physics (Rmax) actually right, checked against ground truth? | `verify_besttrack_rmax.py` |
| Can that regression be made to fit WestPac better? | `fit_westpac_rmax.py` |

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
