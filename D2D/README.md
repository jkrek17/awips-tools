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
`dZ(level) = max(Z) - min(Z)` of geopotential height over a window of
half-width 500 km centered on that point (Hart's own analysis radius,
evaluated at every point instead of only at one storm's moving center
-- see `cps_HartCPS.py`'s module docstring for why a square window is
used instead of Hart's circle, and why the difference is small in
practice), then `-V_T` is the least-squares slope of `dZ` against
`ln(pressure)` over a band of levels. This uses **geopotential height
only** -- no wind field, no vorticity, no smoothing choice.

The magnitudes here are meters (of `dZ`) per unit of `ln(pressure in
hPa)` -- plain meters. A mature hurricane typically samples HVTL/HVTU
in the +100 to +300 m range; a cold-core low typically samples -100 to
-300 m. These are **near but not equal to** the published Hart
(2003)/FSU CPS values for the same real storms, both because of
the square-vs-circle window difference and because the standard levels
used here are not exactly Hart's own bands (next section). Do not
report HVTL/HVTU numbers as if they were the published FSU CPS
diagnostic for a storm -- read the sign and the trend; the window-shape
and level-band approximations mean the exact number will differ
slightly from FSU's own website for the same case.

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
-- see "Adding a GFS-only 13-level definition" below.

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
2. **Depth test**: the mean height of the **annulus** between
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

## Joint classification (HCPSclass) and index (HCPSidx)

`HCPSclass` is computed from all three Hart parameters at once:
`B` (against Hart's frontal threshold of 10 m) and both thermal wind
terms (each against 0, strictly; warm if greater than or equal to 0,
cold if less than 0). Hart's own two diagrams are two projections of
this same three-dimensional space that happen to share the lower
thermal wind axis; each diagram alone carries one piece of information
the other lacks (frontal or not, from `B`; deep or shallow warm core,
from `HVTU`). Classifying on all three numbers at once carries both and
loses neither, and it turns "sample two panels and combine them by
eye" into "sample one number at the low center":

| Code | Name | B | HVTL | HVTU | Typical system |
| ---: | :--- | :--- | :--- | :--- | :--- |
| 0 | symmetric deep warm core | <= 10 | warm | warm | hurricane, typhoon |
| 1 | symmetric shallow warm core | <= 10 | warm | cold | subtropical storm, or warm seclusion after transition |
| 2 | frontal deep warm core | > 10 | warm | warm | hurricane meeting a trough, transition beginning |
| 3 | frontal shallow warm core | > 10 | warm | cold | transition under way |
| 4 | frontal cold core | > 10 | cold | any | extratropical low, transition complete |
| 5 | symmetric cold core | <= 10 | cold | any | occluded or cutoff cold low |
| 6 | mid-level vortex (lower cold, upper warm) | any | cold | warm | perturbation peaking at mid-levels; rarely occupied |
| blank | | | | | no closed low, or B undefined (steering below 1 m/s) |

The codes rise along a typical extratropical transition (0, 2, 3, 4)
and a warm seclusion is 4 then back to 1. `HCPSclass` is NaN outside
`closed_low_mask`. There is no neutral
band on `B` or on either thermal wind term here: Hart's own strict
lines (10 m, 0, 0) are used exactly, unlike `HCPSidx` below, which
keeps its 25 m neutral band because a continuous index needs one to
avoid painting noise as a trend. A storm sitting on a strict line
therefore flickers between adjacent codes frame to frame; that is
expected, and the continuous fields (`HVTL`, `HVTU`, `HB`) are where to
look for the underlying trend when it happens.

`HCPSclass` names states, one per frame; onset and completion are
events, which need history across frames, so they are read from how
the class changes in the animation (the first frame in class 2 or 3 is
onset, the first frame in class 4 or 5 is completion), never from a
single frame.

`HCPSidx` is `2*tanh(HVTL/scaleM) + tanh(HVTU/scaleM)` (default
`scaleM` = 100 m), range -3 to +3, and still the only place in
this family a neutral band (via `scaleM`) survives.

## Parameter B (HB) and its role in HCPSclass

Hart's (2003) third CPS number, **B** (thermal asymmetry), is the
right-minus-left half-window mean of 900-600 hPa thickness across the
storm's own direction of motion, over the same 500 km analysis circle
HVTL/HVTU use: `B = h * (mean_right - mean_left)`, `h = +1` in the
Northern Hemisphere, `-1` in the Southern, so the frontal configuration
(warm/thick air on the equatorward flank of the track) always reads
positive. Hart's own line for calling a storm frontal rather than
symmetric is `B` above 10 m; `HCPSclass` uses that line exactly, with
no neutral band, to pick between its symmetric (0, 1, 5) and frontal
(2, 3, 4) codes.

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
the **steering flow**, the mean of the wind at 850, 700, 500, and
300 hPa. This is a reasonable proxy on most systems, but a storm
moving against its own steering flow, or a nearly stationary system
(`MIN_STEERING_MS`, 1 m/s, below which `HB` is blanked to NaN), gets an
unreliable or missing `HB` from this method even where Hart's own
track-based B would be well defined.

**Layer scaling**: this family's thickness layer is 925-700 hPa (for
consistency with `HVTL`'s own band), not Hart's 900-600 hPa. Because
thickness scales with the log-pressure depth of the layer, `HB` is
multiplied by `layerScale = ln(900/600)/ln(925/700)` (about 1.4553) by
default so the result reads as a "900-600 hPa equivalent" against
Hart's 10 m threshold; pass `layerScale=1.0` for the raw, unscaled
925-700 hPa value.

**Hemisphere**: same convention as `cps.hart.parameter_b` -- the
Northern Hemisphere right-hand normal of steering `(u_s, v_s)` is
`(v_s, -u_s)/|V_s|`, and the AWIPS coriolis pseudo-field's sign
(positive north, negative south) is the hemisphere factor `h` that
multiplies the projected gradient so warm air on the right in the NH
(or on the left in the SH) always reads positive. **VERIFY**: the
coriolis pseudo-field is referenced by base vorticity definitions on
most AWIPS sites; if `cps_HB.xml`/`cps_HCPSclass.xml` fail to load, replace the
`coriolis` `<Field>` with `<ConstantField value="1.0"/>` at the same
position to assume the Northern Hemisphere everywhere.

Constants (all `<ConstantField>` values in `cps_HB.xml`/`cps_HCPSclass.xml`):

| Constant | Meaning | Default |
| :--- | :--- | :--- |
| `radiusKm` | analysis-window half-width (also the `8*radiusKm/(3*pi)` geometry constant) | 500.0 |
| `layerScale` | rescales 925-700 hPa `HB` to a 900-600 hPa equivalent | 1.4553 |
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
running_extreme_1d` -- see that function's docstring), so a few seconds
per analysis time on a global 0.25 degree grid. Measured in this repo's
environment, on a 721x1440 grid (`tests/d2d_cps/test_hart_cps.py`'s
performance tests -- see their `-s` output for the exact numbers on
your own machine):

- `thermal_wind_grid`, 3 levels (one HVTL or HVTU band alone): well
  under a second.
- `executeHartClass`, all 7 standard levels plus `B` (both thermal wind
  bands, the gradient/steering pass `B` needs, `closed_low_mask`'s
  candidate test, its two `window_sum_2d` ring box sums, and its blob
  dilation): about 2 seconds; the mask and `B` pass add a
  modest, not a dominant, amount of work on top of the two
  `thermal_wind_grid` calls it also makes.

Both are comfortably inside an 8 second budget. A regional subset
(e.g. an Atlantic-basin CONUS-scale grid instead of a global one) is
proportionally faster, since the cost scales with the number of grid
points times `log(window width in cells)`, not with the window's
physical size.

## Adding a GFS-only 13-level definition

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

Real cases sampled at the MSLP center in D2D. Add to this as cases
accumulate; it is the calibration record for the thresholds.

| Date sampled | Model, cycle, fhr | System | HVTL (m) | HVTU (m) | HCPSclass | HCPSidx |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-09-17 | GFS 12Z, 72 h | Typhoon, 31N 139E, 984 mb | 120 | 180 | deep warm core (0 or 2; B not sampled) | 2.5 |
| 2026-09-17 | GFS 12Z, series | Typhoon Dujuan, loss of deep warm core | | | leaves the deep warm core classes (0 or 2) at Mon 21 Sep 2026 18Z | |
| 2026-09-17 | GFS 12Z | Deep extratropical low, North Atlantic | negative (value not recorded) | negative (value not recorded) | a cold-core class | negative |

Notes: the Hart values for the typhoon are in Hart's published
hurricane range. The Hart family validated on a cold-core case, both
thermal wind terms negative, HCPSclass reading a cold-core class.
External check: the first forecast hour at which HCPSclass leaves the
deep warm core classes for Typhoon Dujuan (Mon 21 Sep 2026 18Z) matches
the hour the FSU cyclone phase page shows the same GFS run moving from
deep to shallow warm core. This is the loss of the upper warm core,
not the Evans and Hart (2003) onset, which is read from the animation
as the first frame `HCPSclass` reaches 2 or 3 (`B` above 10 m) and
awaits validation on a real case. After the surface-pressure mask,
Greenland and the high terrain of western North America are blank
rather than contaminated, which is the intended behavior. A few very
weak closed lows (under about 5 hPa deep) get no class blob at the
shipped depth of 40 m; set depthM to 25 in cps_HCPSclass.xml and
cps_HCPSidx.xml to include them.

**Status: the D2D version is release-ready as of 2026-09-17**, still
labeled experimental pending a season of use. Known limitations: the
raw HVTL/HVTU fields paint a square footprint around each low (the
window shape, cosmetic); style rules did not auto-apply on the OPC
build, so colors come from a saved procedure.
