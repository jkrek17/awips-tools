# D2D Hart CPS family (HVTL, HVTU, HB, HCPSidx, HCPSclass)

*** EXPERIMENTAL. NOT OPERATIONALLY VETTED. *** This is a D2D
derived-parameter implementation of Hart's (2003) Cyclone Phase Space
(`cps/hart.py`, `web/CPS/PLAN.md`). It computes Hart's actual
thermal-wind and thermal-asymmetry quantities from geopotential height
and wind, evaluated pointwise over the whole grid instead of only at
one storm's moving center -- a D2D derived parameter has no concept of
"the storm's center". `tests/cps` exercises the storm-centered
reference implementation (`cps/hart.py`) this family is checked
against; see "Tests" below.

## Guides

- `docs/USER_GUIDE.md`: for forecasters, how to load and read the
  products and where they mislead.
- `docs/TECHNICAL_GUIDE.md`: method, wiring, every tunable, install,
  troubleshooting, tests, limitations.

## What it is

`cps_HartCPS.py` computes Hart's actual quantity: at every grid point,
`dZ(level) = max(Z) - min(Z)` of geopotential height over the 500 km
window (a square of 500 km half-width, 1000 km across) centered on
that point (Hart's own analysis radius, evaluated at every point
instead of only at one storm's moving center -- see `cps_HartCPS.py`'s
module docstring for why a square window is used instead of Hart's
circle, and why the difference is small in practice), then `-V_T` is
the least-squares slope of `dZ` against `ln(pressure)` over a band of
levels. This uses **geopotential height only** -- no wind field, no
vorticity, no smoothing choice. On a global lat/lon grid the 500 km
window wraps across the longitude seam instead of clipping there; a
regional grid, which has no seam, is unchanged.

The magnitudes here are meters (of `dZ`) per unit of `ln(pressure in
hPa)` -- plain meters. Warm cores read positive (order +100 m and
above for a mature tropical cyclone) and cold cores negative. These
are **not** the published Hart (2003) or FSU values for the same
storm: the lower band (925-700 hPa) lies entirely below Hart's 900-600
hPa layer, the upper band omits 600-500 hPa, and the square window
inflates dZ for broad anomalies. On plausible core profiles the lower
term can differ from Hart's by tens of percent, and the size of the
difference on real storms has not been measured. Do not report
HVTL/HVTU numbers as if they were the FSU diagnostic for a storm; read
the sign, the zero crossings and the trend, which carry over.

## Standard-level bands

Hart's own bands are 900-600 hPa (lower) and 600-300 hPa (upper), each
sampled every 50 hPa. Most AWIPS D2D grids do not carry that 50 hPa
resolution -- GFS's own native grid does, but many downstream/thinned
grids only carry the standard-level set. HVTL/HVTU/HCPSclass/HCPSidx use:

```
LOWER_BAND = 925, 850, 700 hPa   (HVTL)
UPPER_BAND = 500, 400, 300 hPa   (HVTU)
```

both on the universal standard-level list. **The 700-500 hPa layer is
deliberately left unassigned** -- neither band claims it. Forcing it
into either band would average a layer that straddles Hart's actual
600 hPa boundary into a band it does not belong to, biasing that
band's slope toward whichever side got glued on; a small gap between
the two bands is a smaller, more honest error than that.

A future GFS-only, Hart-exact definition using the true 900-600/
600-300 hPa bands at 50 hPa spacing is supported by `cps_HartCPS.
executeBand7` and needs only a new XML definition, no Python change
-- see "Adding a GFS-only seven-level definition" below.

### Band experiment (2026-09-20)

`docs/cps/figures/band_comparison.py` fits Hart's 900-600 hPa band
(seven levels at 50 hPa), the package's 925/850/700 band and a
proposed 925/850/700/500 band to five prescribed height-perturbation
profiles. For profiles that are linear in ln p all three agree. For a
shallow warm core (warm below 700 hPa, cold above, the seclusion
profile) Hart's band gives +79 m, 925/850/700 gives +139 m and
925/850/700/500 gives +11 m; for a transitioning profile the three
give +181, +241 and +57 m. The deeper band dilutes a shallow warm core
far more than Hart's does, so the seclusion signal would nearly vanish;
the current band overstates it. The mean of the 925/850/700 and
850/700/500 slopes tracks Hart's band best of the simple estimators
tried (rms 25 m across the five profiles against 44 m for the current
band and 66 m for the proposed one) and is exact for the deep cold
profile. The conclusion is to keep 925/850/700 rather than move to
925/850/700/500, and to test the two-slope average against Hart's own
levels on real GFS data before adopting it.

`docs/cps/figures/experiments.py` runs five further sensitivity tests
with the operational code on synthetic fields:

1. Timing. Morphing a profile from deep warm core through the
   transition shape to deep cold core, completion (lower term crossing
   zero) falls at progress 0.71 on Hart's band, 0.77 on 925/850/700,
   0.59 on 925/850/700/500 and 0.67 on the two-slope mean; the upper
   crossing is 0.17 on Hart's 600-300 and 0.15 on 500/400/300. The band
   in use calls completion slightly late (about 3 h on a 48 h
   transition); the deeper band would call it about 6 h early.
2. Closed-low detector. At the shipped 40 m ring test a low of 40 m
   central depth is never detected; 50 m is detected out to a 300 km
   e-folding scale, 80 m out to 500 km, 100 m out to 600 km, and an
   800 km scale low is missed even at 120 m. The effective floor is
   therefore about 6 hPa for a compact low and 10 to 12 hPa for a broad
   one. An open trough with a 40 m per 1000 km cross-trough gradient
   produces no detection; a flat-centered 80 m low and an elongated
   700 by 150 km low are both detected (figure figB_detector.png).
3. Resolution. The same vortex on 0.25, 0.5 and 1.0 degree grids gives
   the same lower term to 0.1 m at 150 km scale and within 1.4 percent
   at 400 km scale.
4. Steering. With 20 and 40 percent wavenumber-one asymmetry in the
   vortex, the window-averaged proxy still returns the imposed 8 m/s
   westerly exactly at the center, while the pointwise wind one degree
   away reads 44 to 55 m/s. The area mean of the geostrophic wind over
   a window depends only on the height on the window boundary, so any
   vortex whose perturbation vanishes at the boundary contributes
   nothing, symmetric or not.
5. Noise. With 5 m of uncorrelated height noise on every level, the
   terms at a storm center scatter with standard deviations of 15 m
   (HVTL), 9 m (HVTU) and 0.6 m (HB) over 60 realizations. A class can
   flicker when a thermal wind term is within about 15 m of zero or B
   within about 1 m of 10 m.

## Closed-low mask

HCPSclass and HCPSidx are blanked (NaN) outside of `cps_HartCPS.
closed_low_mask`, computed from **1000 hPa height alone** (`executeHartClass`/
`executeIndexStd`'s leading `z1000` argument), not from any of the six
HVTL/HVTU band levels. 1000 hPa height is used because it is nearly a
linear function of MSLP (about **8 m per hPa**), so the closed low the
mask finds is, to a good approximation, the same closed low a
forecaster already sees drawn on the MSLP contours -- the mask's
`depthM` (default 40 m) is therefore about **5 hPa of MSLP**.

1000 hPa is below the ground surface over major terrain, and below
sea level itself inside a sufficiently deep low, so in both cases the
model is extrapolating rather than reporting a directly analyzed
height there. Over the open ocean -- most of this family's intended
use -- that extrapolation is harmless. Over ice sheets and high
mountains it is not, so `z1000` (like every other height level this
family uses) is run through the below-ground mask described next
before it ever reaches this function.

A test based only on "close to the local minimum, and the window
max-minus-min is big enough" passes
**everywhere** on a uniform height gradient (e.g. a steady 40-60 m per
1000 km slope across a front, no low at all): every point on a slope
is, to a few meters, already the minimum of its own neighborhood in
the one direction the slope descends, and the window max-minus-min
over a 500 km box is large simply because the slope has covered a lot
of height by the time it reaches the box's far edge. The mask
therefore uses two tests a monotonic slope cannot satisfy together:

1. **Candidate test**: the point is within `centerTolM` (default
   **5 m** -- deliberately tight) of the local minimum height found
   within a `minRadiusKm` search box (module default `MIN_RADIUS_KM`,
   300 km, fixed, not a `<ConstantField>` -- "how big a box finds a
   low's own local minimum", not something meant to be tuned per case).
2. **Depth test**: the mean height of the **annulus** (a square ring,
   the difference of two square box sums, not a circular one) between
   `minRadiusKm` and `radiusKm` (the same 500 km `<ConstantField>` used
   for HVTL/HVTU) exceeds the point's own height by at least `depthM`
   (default 40 m). The annulus mean is a difference of two NaN-aware
   box sums (`cps_HartCPS.window_sum_2d`, called once for the outer
   `radiusKm` box and once for the inner `minRadiusKm` box, then
   `(sum_outer - sum_inner) / (count_outer - count_inner)`). On a real
   closed low the surrounding annulus sits on higher ground and this
   comes back close to the low's true depth; on a uniform slope the
   annulus is symmetric around the point and its mean height equals
   the point's own height to first order, so the depth comes back ~0
   and the test correctly rejects it.

**In forecaster terms**, the depth test is about 40 m (roughly 5 hPa)
of height rise between the center and the square 300 to 500 km ring
around it, not a literal "closed low at least 5 hPa deep" statement.
For a compact 300 km low the effective floor works out closer to 6 hPa
once the ring mean and the height-to-MSLP conversion are folded in; a
broader, flatter low needs more than 5 hPa of true depth to clear the
same 40 m test and can go unclassified even though a forecaster would
call it closed. An elongated trough with a strong gradient across it
(rather than along it) can pass both tests at a point that is not
really a closed low's center, producing a spurious blob; check the
MSLP field before trusting an isolated one. Lowering `depthM` to 25 (a
`<ConstantField>` in `cps_HCPSclass.xml` and `cps_HCPSidx.xml`) admits
weaker lows at the cost of more of these false detections.

**Neighboring lows.** Two lows within about 1000 km of each other have
overlapping 500 km windows and can share detections, and the `blobKm`
dilation (200 km) can then merge their two blobs into one on the
display. Check the MSLP field for a second low inside a blob's
footprint before reading it as a single system.

Points passing both tests are dilated by `blobKm` (default 200 km, via
`window_extreme_2d(..., kind="max")` on the boolean detections cast to
float) so each detected low paints a blob of about that radius on the
map instead of a single pixel -- `blobKm` is a *display* radius, not a
claim about the low's own physical size.

All of `centerTolM`, `depthM`, `blobKm` are already in meters/km. `centerTolM`
itself is not exposed as a public `<ConstantField>` on cps_HCPSclass.xml/
cps_HCPSidx.xml (see `cps_HartCPS.executeHartClass`'s docstring) -- only
`radiusKm`, `depthM`, `blobKm`, and (below) `capHpa` are.

## Below-ground masking

Every height level this family uses -- `z1000` and the six HVTL/HVTU
band levels -- can be below the ground surface over major terrain, or
below sea level itself inside a sufficiently deep low, where the
model is extrapolating rather than reporting an analyzed height. Over
the open ocean that extrapolation is harmless (a deep low's own
surface pressure legitimately drops well under 1000 or 925 hPa at its
center, and the height there is still meaningful); over ice sheets and
high mountains it is not, and letting a fictitious below-ground level
into a window's max/min or the closed-low mask's ring mean can quietly
bias the result.

`cps_HartCPS.mask_below_ground(z, psfc_hpa, level_hpa, cap_hpa)` blanks
(NaN) `z` wherever a point is below ground for pressure level
`level_hpa`:

```
psfc_hpa < min(level_hpa, capHpa)
```

`capHpa` (`<ConstantField>`, default **900 hPa**, `cps_HartCPS.
BELOW_GROUND_CAP_HPA`) is a cap on the threshold, not the literal level
pressure. Without it, a deep low's own surface pressure (which can
legitimately fall well under 1000 or 925 hPa at its center) would be
mistaken for terrain and mask out the very feature this family exists
to find. With the cap, a point only counts as below ground for the
1000 and 925 hPa levels when the surface pressure drops under 900 hPa
-- true over the **Greenland ice sheet** (surface pressure roughly
700-800 hPa) and the **Iceland highlands** (roughly 850-900 hPa), not
true over an open-ocean low (surface pressure rarely below 900 hPa
even in a deep cyclone). 850 hPa is masked by the same 900 hPa
threshold; 700 hPa and above are masked only where the surface itself
is at or below that level's own pressure -- effectively never, except
over the Himalaya and Antarctica.

`cps_HartCPS.surface_pressure_hpa(psfc)` coerces the surface pressure
input field (`P`, `level="Surface"` in the XML) to hPa, auto-detecting
units: AWIPS normally hands pressure in Pa (sea level is roughly
101325 Pa), but this checks the field's own finite median rather than
trusting a caller's label -- a median above 2000 can only be Pa (no
real surface pressure is above 2000 hPa), so the whole field is
divided by 100; at or below 2000 it is assumed to already be hPa.

Every Hart entry point -- `HVTL`/`HVTU` (`executeBand3`), `HCPSclass`
(`executeHartClass`), `HCPSidx` (`executeIndexStd`) -- takes the `P`
field and a `capHpa` `<ConstantField>` and masks every one of its
height arguments before doing anything else with them: before
`delta_z`'s window max/min for the band levels, and before
`closed_low_mask`'s candidate/depth tests for `z1000`. Because the
sliding window extrema and box sums this family uses throughout are
already NaN-aware, a below-ground point's neighbors simply see one
fewer valid sample in their own window -- no extra plumbing was needed
beyond masking the input before it reaches them. See `cps_HartCPS.py`'s
module docstring ("Below-ground masking") for the full explanation.

A level is below ground wherever the surface pressure is lower than
that level's pressure. In any low deeper than 1000 hPa the 1000 hPa
height at the center is the model's post-processor extrapolating below
its own analyzed surface; that level feeds only the closed-low
detector. The 925 hPa level, the lowest level in `HVTL`, is
extrapolated only where the surface pressure is between 900 and
925 hPa, which at sea means the core of a major hurricane. Different
models extrapolate differently, so keep that in mind before comparing
`HVTL` between models in that rare case; the difference can be the
extrapolation scheme,
not the storm.

**Window valid-fraction masking.** Even after the below-ground mask, a
level's 500 km window can still be mostly over masked terrain near a
coastline or an ice sheet's edge -- within a few hundred kilometers of
Greenland or Iceland, most often for `HVTL`'s lower band. Fitting the
band's least-squares slope through a window that is mostly missing
data would carry a silent bias toward whichever few valid points
remain. `cps_HartCPS.py` instead requires at least half of a level's
500 km window to hold valid data; a level that falls short is set to
NaN outright rather than fit, so `HVTL`, `HVTU`, and (through them)
`HCPSclass` go blank within a few hundred km of Greenland and Iceland
instead of carrying a hidden bias there.

## Joint classification (HCPSclass) and index (HCPSidx)

`HCPSclass` is computed from all three Hart parameters at once:
`B` (against Hart's frontal threshold of 10 m) and both thermal wind
terms (each against 0, strictly; warm if greater than or equal to 0,
cold if less than 0). Hart's own two diagrams are two projections of
this same three-dimensional space that happen to share the lower
thermal wind axis; each diagram alone carries one piece of information
the other lacks (frontal or not, from `B`; deep or shallow warm core,
from `HVTU`). The full joint space of `B` (symmetric or frontal),
`HVTL` (warm or cold), and `HVTU` (warm or cold) has eight cells;
`HCPSclass` gives seven codes because code 6 merges the two cells
where `HVTL` is cold and `HVTU` is warm (symmetric and frontal) into
one code, since a cold lower core under a warm upper core is treated
as its own quadrant regardless of `B`. Classifying on all three
numbers at once turns "sample two panels and combine them by eye" into
"sample one number at the low center":

| Code | Name | B | HVTL | HVTU | Typical system |
| ---: | :--- | :--- | :--- | :--- | :--- |
| 0 | symmetric deep warm core | <= 10 | warm | warm | hurricane, typhoon |
| 1 | symmetric shallow warm core | <= 10 | warm | cold | subtropical storm, or warm seclusion after transition |
| 2 | frontal deep warm core | > 10 | warm | warm | hurricane meeting a trough, transition beginning |
| 3 | frontal shallow warm core | > 10 | warm | cold | transition under way |
| 4 | frontal cold core | > 10 | cold | cold (code 6 takes lower cold, upper warm first) | extratropical low, transition complete |
| 5 | symmetric cold core | <= 10 | cold | cold (code 6 takes lower cold, upper warm first) | occluded or cutoff cold low |
| 6 | shallow cold core (lower cold, upper warm) | any | cold | warm | perturbation peaking at mid-levels; rarely occupied |
| blank | | | | | no closed low, or B undefined (steering below 2 m/s) |

Ties go to the warm side and the symmetric side: `B` exactly at 10 m
counts as symmetric, and either thermal wind term exactly at 0 counts
as warm.

The codes rise along a typical extratropical transition (0, 2, 3, 4).
A warm seclusion typically runs 4 to 3, or 4 to 1 if `B` also falls at
or below 10 m; the signature to watch is `HVTL` crossing back above 0,
not which code color is on screen. `HCPSclass` is NaN outside
`closed_low_mask`. There is no neutral
band on `B` or on either thermal wind term here: Hart's own strict
lines (10 m, 0, 0) are used exactly, unlike `HCPSidx` below, which
keeps its 25 m neutral band because a continuous index needs one to
avoid painting noise as a trend. A storm sitting on a strict line
therefore flickers between adjacent codes frame to frame; that is
expected, and the continuous fields (`HVTL`, `HVTU`, `HB`) are where to
look for the underlying trend when it happens.

`HCPSclass` names states, one per frame; onset and completion are
events, which need history across frames. Read them from `HB` and
`HVTL` directly, not from `HCPSclass`: onset is the first frame `HB`
crosses above 10 m, and completion is the first frame `HVTL` crosses
below 0. `HCPSclass` is a convenient summary of where those two fields
stand at a given frame, not the event detector itself, and a storm can
jump straight from class 0 to class 4 in one frame if both crossings
land in the same forecast hour.

`HCPSidx` is `2*tanh(HVTL/scaleM) + tanh(HVTU/scaleM)` (default
`scaleM` = 100 m), range -3 to +3, and still the only place in
this family a neutral band (via `scaleM`) survives.

## Parameter B (HB) and its role in HCPSclass

Hart's (2003) third CPS number, **B** (thermal asymmetry), is the
right-minus-left half-window mean of 900-600 hPa thickness across the
storm's own direction of motion, over the same 500 km window HVTL/HVTU
use: `B = h * (mean_right - mean_left)`. `B` is motion-relative, not
compass-relative: "right" and "left" are defined by the direction of
travel, so warm air to the right of the track reads positive in the
Northern Hemisphere (to the left in the Southern), and a large negative
`B` means warm air sits to the *left* of the motion vector, not that
the storm is symmetric -- symmetric means small `|B|` in either sign,
not a particular side of the track. Hart's own line for calling a
storm frontal rather than symmetric is `B` above 10 m; `HCPSclass` uses
that line exactly, with no neutral band, to pick between its symmetric
(0, 1, 5) and frontal (2, 3, 4) codes.

**The gridded approximation.** A single grid point has no "left half"
or "right half" of an analysis circle the way a storm-centered
computation does (`cps.hart.parameter_b`'s true half-disk means). This
family instead uses a **linear-gradient approximation**: for a
thickness field that varies smoothly across the window, the
right-minus-left half-window mean difference equals `(8*R/(3*pi))`
times the window-mean gradient of thickness, projected onto the
right-hand normal of the storm's motion (`R` the 500 km `radiusKm`,
about 424.4 km for the default). This is exact for a perfectly linear
thickness field; it degrades for a genuinely nonlinear structure inside
the window -- most notably a warm-seclusion tongue folding back into
one side of the circle -- captured only to first order. Read a
marginal gridded `HB` alongside the thickness overlay itself, not on
its own.

**Motion**: with no storm to track, the motion at each grid point is
the **deep-layer steering wind** (850, 700, 500, and 300 hPa),
horizontally area-averaged over the same 500 km window before its
direction is taken. Averaging over the window first, rather than
reading the wind at the point itself, is what makes this a steering
proxy instead of a reading of the storm's own circulation: a symmetric
vortex's wind reverses sign across the window and cancels out of the
average, leaving the environmental flow the storm sits in. This is a
reasonable proxy on most systems, but a storm moving against its own
steering flow, or a nearly stationary system (`MIN_STEERING_MS`,
2 m/s, below which `HB` is blanked to NaN), gets an unreliable or
missing `HB` from this method even where Hart's own track-based B
would be well defined.

**`HB` is a full field, not masked to closed lows.** Away from a
detected low, `HB` still reports whatever the window-mean thickness
gradient and steering wind give it there: the ambient baroclinicity
across the flow at that point, which says nothing about a storm
because there usually isn't one. A large `|HB|` of either sign, on or
off a detected low, is worth checking against the thickness field
before it is read as anything -- under the first-order method above, a
genuinely symmetric vortex contributes nothing to `B` at all, so a
large reading at a low center is entirely the environment and the
motion, not the storm's own asymmetry.

**Layer scaling**: this family's thickness layer is 925-700 hPa (for
consistency with `HVTL`'s own band), not Hart's 900-600 hPa. Because
thickness scales with the log-pressure depth of the layer, `HB` is
multiplied by `layerScale = ln(900/600)/ln(925/700)` (about 1.4548) by
default so the result reads as a "900-600 hPa equivalent" against
Hart's 10 m threshold; pass `layerScale=1.0` for the raw, unscaled
925-700 hPa value.

**Hemisphere**: same convention as `cps.hart.parameter_b` -- the
Northern Hemisphere right-hand normal of steering `(u_s, v_s)` is
`(v_s, -u_s)/|V_s|`, and the AWIPS coriolis pseudo-field's sign
(positive north, negative south) is the hemisphere factor `h` that
multiplies the projected gradient so warm air to the right of the
motion vector in the NH (or to the left in the SH) reads positive.
**VERIFY**: the
coriolis pseudo-field is referenced by base vorticity definitions on
most AWIPS sites; if `cps_HB.xml`/`cps_HCPSclass.xml` fail to load, replace the
`coriolis` `<Field>` with `<ConstantField value="1.0"/>` at the same
position to assume the Northern Hemisphere everywhere.

Constants (all `<ConstantField>` values in `cps_HB.xml`/`cps_HCPSclass.xml`):

| Constant | Meaning | Default |
| :--- | :--- | :--- |
| `radiusKm` | analysis-window half-width (also the `8*radiusKm/(3*pi)` geometry constant) | 500.0 |
| `layerScale` | rescales 925-700 hPa `HB` to a 900-600 hPa equivalent | 1.4548 |
| `bThresholdM` | Hart's frontal threshold for `B` (`HCPSclass` only) | 10.0 |

## Orientation verification

`HVTL`, `HVTU`, and `HCPSidx` need no orientation check: `max(Z) -
min(Z)` and a least-squares slope are orientation-independent and
hemisphere-independent by construction, so those three fields read the
same way (positive = warm core) at every latitude and on any grid axis
layout.

`HB` and `HCPSclass` are the exception. Both need `B`, which needs the
thickness field's own spatial *gradient* (`cps_HartCPS.gradient_2d`),
and a gradient's sign depends on which way the grid's axes actually run
-- whether row index (axis 0) increases toward the north or the south,
and whether the axes are x/y or y/x at all, a property of the grid's
projection and storage that this file cannot know in advance for every
site. `cps_HartCPS.py` carries its own `ORIENTATION_MODE` (module
level, integer 0-3, see the comment block above the constant for what
each mode means), used only by `gradient_2d`; every other function in
the module, including `HVTL`/`HVTU`/`HCPSidx`'s own computation, is
unaffected. The module default, `ORIENTATION_MODE = 1`, is confirmed
correct on the OPC build.

Hemisphere is handled explicitly for `HB`/`HCPSclass` through the
coriolis pseudo-field's sign (see "Parameter B (HB) and its role in
HCPSclass" above), not by an assumption baked into the math, so there
is no Southern Hemisphere sign caveat to verify for this family.

## Performance

Expect a few sliding-window passes per level (one `max` and one `min`
each, via the doubling/sparse-table trick in `cps_HartCPS.
running_extreme_1d` -- see that function's docstring). The full
`executeHartClass` computation runs at about 2.6 s per forecast hour on
a 0.25 degree global grid. Measured in this repo's
environment, on a 721x1440 grid (`tests/d2d_cps/test_hart_cps.py`'s
performance tests -- see their `-s` output for the exact numbers on
your own machine):

- `thermal_wind_grid`, 3 levels (one HVTL or HVTU band alone): well
  under a second.
- `executeHartClass`, all 7 standard levels plus `B` (both thermal wind
  bands, the area-averaged steering pass `B` needs, `closed_low_mask`'s
  candidate test, its two `window_sum_2d` ring box sums, and its blob
  dilation): about 2.6 s per forecast hour on a 0.25 degree global
  grid; the mask and `B` pass add a modest, not a dominant, amount of
  work on top of the two `thermal_wind_grid` calls it also makes.

Both are comfortably inside an 8 second budget. A regional subset
(e.g. an Atlantic-basin CONUS-scale grid instead of a global one) is
proportionally faster, since the cost scales with the number of grid
points times `log(window width in cells)`, not with the window's
physical size.

## Adding a GFS-only seven-level definition

To use Hart's exact 900-600/600-300 hPa bands (50 hPa spacing) instead
of the 3-level standard-level approximation above, on a site that
confirms its grid actually carries every 50 hPa level from 900 to 300:

1. Write a new definition XML (e.g. `HVTLexact.xml`) shaped exactly
   like `cps_HVTL.xml`, but with `Method name="cps_HartCPS.executeBand7"` and
   seven `<Field abbreviation="GH" level="...MB"/>` entries (900, 850,
   800, 750, 700, 650, 600 hPa) followed by the `P` (`level="Surface"`)
   field, then `dx`, `dy`, the `radiusKm` `<ConstantField>`, then seven
   pressure `<ConstantField>` values (900, 850, 800, 750, 700, 650, 600)
   matching the seven height fields by position, then the `capHpa`
   `<ConstantField>` (900.0) last.
2. Do the same for the upper band (600, 550, 500, 450, 400, 350, 300
   hPa) in a second file (e.g. `HVTUexact.xml`).
3. No change to `cps_HartCPS.py` is needed -- `executeBand7` already takes
   7 heights, `psfc`, `dx`/`dy`, `radiusKm`, 7 pressures, and `capHpa`,
   in exactly that shape.

## Install

EDEX, site-level `common_static`:

```
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HVTL.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HVTU.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HB.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HCPSidx.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HCPSclass.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/functions/cps_HartCPS.py
```

The `cps_` file prefix is only so the family sorts together in the
Localization perspective and on disk; AWIPS keys each definition on the
`abbreviation` inside the XML (HVTL, HVTU, HB, HCPSidx, HCPSclass) and
the function module on the `Method name` in the XML, so the product
names in D2D are unchanged.

Restart CAVE (not necessarily EDEX, depending on your version's
derived-parameter caching -- some versions pick up new definitions
without an EDEX restart, some need one; if the fields do not show up
in the Volume Browser, restart EDEX too) after copying these in.

CAVE, site-level `cave_static`, Volume Browser fields menu:

```
/awips2/cave/etc/... (or the site cave_static location your build uses)/menus/volumebrowser/cpsFields.xml
```

This file is a starting point (see the VERIFY comment inside it) --
AWIPS versions differ in how a fields-menu contribution is wired in
(some need an `<include>` from a parent menu file). Check an existing
contribution under `cave_static/base/menus/volumebrowser/` on your
build and match its shape.

Style rules: on the OPC build a separate `cpsStyleRules.xml` at the
site level did NOT apply automatically; the colormap had to be chosen
from the legend right-click menu. Two working routes:

1. Set up the display (colormaps and ranges) once and save it as a CAVE
   procedure. The bundle stores colormap and range per resource, so the
   procedure loads with the right colors and no style rule is needed.
   This is the recommended route.
2. Untested fallback for ad hoc Volume Browser loads: copy the base
   gridImageryStyleRules.xml and gridContourStyleRules.xml to the site
   level and paste the matching rules from `D2D/styleRules/cpsStyleRules.xml`
   into them. The file is kept in the base schema for that purpose.

Colormaps: copy `D2D/colormaps/Grid/CPS_CoreDiverging.cmap` and
`CPS_HartClass.cmap` to
`/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/Grid/`:

```
/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/Grid/CPS_CoreDiverging.cmap
/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/Grid/CPS_HartClass.cmap
```

(VERIFY the exact colormaps path for your AWIPS version.)
`CPS_CoreDiverging` is used by `HVTL`, `HVTU`, `HCPSidx`, and `HB`;
`CPS_HartClass` is used by `HCPSclass` only. Restart CAVE. Even
without the style rules, both then appear in the right-click legend
menu under Change Colormap, listed under Grid (a separate colormap
subfolder at site level was not possible on the OPC build, so both
live in the existing Grid folder with the `CPS_` prefix telling them
apart, not in a submenu of their own). See the comments inside each
`.cmap` file and in `cpsStyleRules.xml` for the color/category tables.

The `cpsFields.xml` menu file (the "Hart CPS (height based,
experimental)" title and its five menu items, including `HB` and
`HCPSclass`) and `cpsStyleRules.xml` (HVTL/HVTU/HCPSidx imagery and
contour `<styleRule>` blocks, plus `HB` imagery and contour and
`HCPSclass` imagery blocks) install the same way described above; they
are not drop-in files either.

## Troubleshooting

**The five Hart fields (HVTL, HVTU, HCPSclass, HCPSidx, HB) disappear
from the Product Browser after adding the below-ground mask.** The
first suspect is the `P` (surface pressure) `<Field level="Surface"/>`
in cps_HVTL.xml/cps_HVTU.xml/cps_HCPSclass.xml/cps_HCPSidx.xml/
cps_HB.xml -- specifically its level spelling. This site's other Field
level spellings in these files ("925MB", "Surface" on the `<Method>`
itself, etc.) are already confirmed to load; `P`'s own level was not
independently re-verified against a base surface-pressure definition
when this mask was added. Some AWIPS builds spell the surface plane
`level="0.0SFC"` instead of `level="Surface"` for a Field reference (as
opposed to the `<Method levels="...">` attribute, which is a different
thing and unaffected). Check a base definition that already uses
surface pressure (or GRIB metadata for the `P` parameter) and adjust
the `level` attribute on that one `<Field>` line in all five files if
needed -- everything else in the definitions is unchanged. If only
`HB`/`HCPSclass` fail to load while the other three still work, the
more likely cause is the `coriolis` pseudo-field, not `P` -- see
"Parameter B (HB) and its role in HCPSclass" above.

## Tests

```
python3 -m pytest tests/d2d_cps -q
```

`tests/d2d_cps/test_hart_cps.py` covers the sliding-window doubling
trick against a brute-force reference, the closed-form band-slope
formula, `closed_low_mask`, the classification/index entry points, a
direct numerical comparison against `cps.hart.thermal_wind` on a
synthetic warm/cold-core vortex (within 2%, per the square-vs-circle
window difference discussed above), `gradient_2d`'s orientation modes
on a plane field, `parameter_b_grid`'s sign reasoning on a linear
thickness gradient (steering west/east/north, both hemispheres), a
cross-check against `cps.hart.parameter_b`'s true half-disk means
(within 5%), the joint classification decision table, `executeB` with
a 2D coriolis field straddling the equator, and `executeHartClass`'s
behavior across Hart's strict B/thermal-wind lines on synthetic
vortices. `tests/d2d_cps/conftest.py` puts `D2D/derivedParameters/
functions` on `sys.path` so the tests can import `cps_HartCPS` the same
way AWIPS's embedded interpreter would (as a bare module, not a
package), without needing any AWIPS runtime present.

```
python3 -m pytest tests/cps -q
```

`tests/cps` is the storm-centered reference implementation this family
approximates: analytic verification of `cps/hart.py` (Hart 2003 cyclone
phase space math) against closed-form synthetic vortices. The
`test_hart_cps.py` comparisons above check `cps_HartCPS.py`'s pointwise,
windowed numbers against this module directly.

Run `python3 D2D/derivedParameters/functions/cps_HartCPS.py` directly
for a quick standalone sanity check (a synthetic warm-core vortex,
printing the lower/upper slope and the class at its center, plus a
parameter B demo on a linear thickness gradient with its analytic
expectation) with no pytest or AWIPS runtime involved.

## Validation log

Real cases sampled at the MSLP center in D2D. This is **experimental:
three GFS cases from one model cycle, a smoke test**, not a calibrated
or representative sample. Add to this table as cases accumulate.

| Date sampled | Model, cycle, fhr | System | HVTL (m) | HVTU (m) | HCPSclass | HCPSidx |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-09-17 | GFS 2026-09-17 12Z, 72 h | Typhoon, 31N 139E, 984 mb | 120 | 180 | deep warm core (0 or 2; B not sampled) | 2.5 (sampled near, not at, the point where HVTL/HVTU were read; see notes) |
| 2026-09-17 | GFS 2026-09-17 12Z, valid 2026-09-21 18Z | Typhoon Dujuan, loss of deep warm core | not recorded | not recorded | leaves the deep warm core classes (0 or 2) at this valid time | not recorded |
| 2026-09-17 | GFS 12Z | Deep extratropical low, North Atlantic | not recorded, to be re-sampled | not recorded, to be re-sampled | a cold-core class (underlying values not recorded) | not recorded, to be re-sampled |
| 2026-09-19 | GFS 12Z, 12 to 144 h | Western Pacific typhoon through transition to a 946 hPa Bering Sea low (class only; terms and B to be sampled) | | | 0 at 12 h (29.7N 137.7E); 2 at 30 h (32.2N 137.0E); 4 at 96 h (45.3N 168.4E, 981 hPa); 3 at 114 h (53.8N 179.6E, 964 hPa); 0 at 126 h (56.4N 174.3W, 946 hPa); 1 at 144 h (57.8N 179.5E, 946 hPa) | |
| 2026-09-20 | GFS 06Z, 0 h | Typhoon, 29.5N 138.0E, 975 hPa | 128 | 176 | 0 (HB 5.9) | 2.66 |
| 2026-09-20 | GFS 06Z, 24 h | same storm, 33.1N 139.2E | 107 | 147 | 2 (HB 13.1) | 2.48 |
| 2026-09-20 | GFS 06Z, 48 h | same storm, 38.2N 148.5E, 976 hPa | 114 | -102 | 3 (HB 36.0) | 0.87 |
| 2026-09-20 | GFS 06Z, 72 h | same storm, 41.3N 163.7E, 992 hPa | 22 | -284 | 3 (HB 45.9) | -0.56 |
| 2026-09-20 | GFS 06Z, 96 h | same storm, 55.2N 171.9W, 976 hPa | 241 | -295 | 1 (HB 0.5) | 0.97 |
| 2026-09-20 | GFS 06Z, 120 h | same storm, 56.0N 165.2W, 971 hPa | -33 | 3 | 6 (HB 20.1); HVTU is +3 m, a threshold artifact, effectively class 4 | -0.61 |

Notes: the 2026-09-20 06Z rows are the same storm in the next cycle
with all four products sampled at one point per frame. Onset falls
between 0 and 24 h (B crosses 10 m with both cores warm), the upper
core is lost between 24 and 48 h, the lower core erodes to +22 m by 72 h
with B at 46 m, and the seclusion forms by 96 h (lower term back to
+241 m, upper still -295 m, B 0.5 m, class 1). The cold-phase upper
term (-284 to -295 m) matches the FSU diagram's -300 m; the seclusion
lower term (+241 m) is about twice the FSU value, which is the expected
direction for the 925-700 band and the square window on a broad low.
The index equals its definition at every sampled point (for example
2 tanh(0.22) + tanh(-2.84) = -0.56 at 72 h). The 120 h class 6 has
HVTU = +3 m, zero for practical purposes: a threshold artifact, read as
class 4. The 2026-09-19 case is the first full Evans and Hart life
cycle recorded with this package: onset before 30 h, completion before
96 h, then a warm seclusion during rapid deepening (4 to 3 to 1, with a
single 6 h frame of 0 at peak intensity). The 0 at 126 h means the upper
term crossed zero for one frame; whether that is a genuine deep warm
seclusion or a marginal upper term is decided by the HVTU magnitude,
still to be sampled. The FSU cyclone phase page's diagrams for the same
run (0.5 degree GFS, cyclone 2, 24 h running mean) show the same
sequence: a symmetric deep warm core cluster near B 0 to 10 m and
-VTL +100 m for the typhoon; B rising past 10 m with the lower core
still warm; an asymmetric deep cold core phase with -VTL near -80 m,
-VTU near -300 m and B near 70 m at 980 hPa; then a return through
-VTL near +5 m with B near 50 m at 960 hPa to a symmetric warm core at
950 hPa with -VTU straddling zero between about -30 and +20 m, filling
to 1000 hPa by 198 h. The class sequence 0, 2, 4, 3, 0, 1 reproduces
that path, and the FSU upper term at peak shows the 126 h class 0 to be
a marginal upper term rather than a deep warm core. At 946 hPa every level of both bands is above the
surface, so the terms there stand on analyzed levels; only the 1000 hPa
detector level is extrapolated. The typhoon values have the expected sign and order of
magnitude for a deep warm core; they are not compared with Hart's
published magnitudes because the bands differ (see "What it is").
`B` was not sampled for any of the three cases above
and should be added when this table is next updated. The index column
for the typhoon (2.5) was sampled near, not exactly at, the grid point
where HVTL=120 and HVTU=180 were read; the index definition,
`2*tanh(HVTL/100) + tanh(HVTU/100)`, gives 2.6 evaluated at that exact
point, and a future pass should resample HVTL, HVTU, and HCPSidx
together at one point. The North Atlantic case's HVTL, HVTU, and
HCPSidx values were only recorded as negative at the time, not to the
number; that row is marked for re-sampling above rather than backfilled
with a guess. External check: the first forecast hour at which
HCPSclass leaves the deep warm core classes for Typhoon Dujuan, valid
2026-09-21 18Z, matches the hour the FSU cyclone phase page shows the
same GFS run moving from deep to shallow warm core. This is the loss of
the upper warm core, not the Evans and Hart (2003) onset (now read as
the first frame `HB` crosses above 10 m) or completion (the first frame
`HVTL` crosses below 0), neither of which has been checked against a
real case yet. After the surface-pressure mask, Greenland and the high
terrain of western North America are blank rather than contaminated,
which is the intended behavior. A few very weak closed lows (under
about 5 hPa deep) get no class blob at the shipped depth of 40 m; set
depthM to 25 in cps_HCPSclass.xml and cps_HCPSidx.xml to include them,
at the cost of more false detections on broad flat lows and elongated
troughs (see "Closed-low mask" above).

**Status: experimental.** Three GFS cases from one model cycle is a
smoke test, not a season of use, and the package stays labeled
experimental until each of the following has been checked and
recorded: extratropical transition cases run against the FSU cyclone
phase page on at least two models; a null case, a recurving storm that
does not transition, correctly staying warm-core throughout; a warm
seclusion case; a subtropical storm case; a false-positive count on
weak frontal waves that are not tropical or subtropical systems at
all; and a comparison of gridded `B` against storm-centered `B`
computed from finite-differenced storm centers on a tracked case.
Known limitations: the raw HVTL/HVTU fields paint a square footprint
around each low (the window shape, cosmetic); style rules did not
auto-apply on the OPC build, so colors come from a saved procedure.
