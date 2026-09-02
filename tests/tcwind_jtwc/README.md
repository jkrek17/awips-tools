# TCWind_JTWC test / evaluation suite

Regression and verification tooling for `GFE/procedures/TCWind_JTWC.py`
and its web-preview port, `web/TCWind_JTWC/{Code.gs,Index.html}`. Three
independent questions, three scripts:

| Question | Script |
|---|---|
| Does the parser still produce what we expect on known inputs? | `test_parser_golden.py` |
| Do the Python and JS ports actually agree with each other? | `compare_py_js.py` |
| Is the tool's physics (Rmax) actually right, checked against ground truth? | `verify_besttrack_rmax.py` |

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
last 3 years, n=1347) - something no real-time bulletin can ever check
against, since JTWC doesn't report an observed Rmax operationally. The
result: **the tool underestimates Rmax by roughly 12-14 nm on average**,
worst for weak systems (TD: bias -22 nm, and the regression doesn't
even correlate with the true value in the right direction, r=-0.28)
and much better for typhoon-strength systems (TY+: bias -3 nm, r=0.36).
The radii clamp helps when it binds (26% of records) but doesn't fully
correct the underlying regression's bias. Full breakdown in the
script's output. This confirms, with a number instead of a hunch, the
tool's own code comment that Willoughby (2006) is an Atlantic-tuned
prior that doesn't transfer cleanly to WestPac - and specifically says
*how* it fails (systematic underestimate, worst for weak systems) - so
a forecaster relying on Rmax for a weak, radii-less system like SAUDEL
should treat it as optimistic (too small) rather than as a neutral
guess.
