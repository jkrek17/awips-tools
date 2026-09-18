# D2D cyclone core structure (VTL, VTU, CPScat, CPSidx, cpsZ850)

*** EXPERIMENTAL. NOT OPERATIONALLY VETTED. *** This is a pointwise D2D
derived-parameter shortcut, not Hart's (2003) Cyclone Phase Space
method (`cps/hart.py`, `web/CPS/PLAN.md`). It only rhymes with Hart's
VTL/VTU: same sign convention (positive = warm core), same rough level
bands, computed a completely different way because a D2D derived
parameter has no concept of "the storm's center" -- it runs pointwise
over the whole grid.

## Guides

- `docs/USER_GUIDE.md`: for forecasters, how to load and read the
  products and where they mislead.
- `docs/TECHNICAL_GUIDE.md`: method, wiring, every tunable, install,
  troubleshooting, tests, limitations.

## What the fields are

**Unit convention: VTL, VTU, and cpsZ850 sample in units of 1e-5 /s,
not raw 1/s.** These fields' real physical magnitude is order 1e-4 1/s,
and CAVE's sampling readout rounds to two decimal places -- an unscaled
value always samples as "0.00 sec^-1", everywhere, useless to a
forecaster. So `CycloneCore.py` multiplies its SI (1/s) result by
`UNIT_SCALE` (1e5) before returning it from `execute()` /
`executeVorticity()`, and the definitions declare `unit=""` (not
`unit="/s"`) since the value is no longer literally in per-second units.
**A sampled value of 12 means 1.2e-4 /s in SI** -- divide by 1e5 (or
multiply by 1e-5) to get back to physical units. CPScat and CPSidx are
unaffected: they are already dimensionless (a category code / a -3..3
index), so nothing about them is rescaled, though the `band`/
`vortexMin`/`scale` `<ConstantField>` values that feed into them are
in the same 1e-5 /s units as VTL/VTU (see "Combined fields" below and
CPScat.xml/CPSidx.xml).

- **VTL** ("CPS Lower Core"): relative vorticity at 850 hPa minus
  relative vorticity at 600 hPa, smoothed over a ~100 km box, scaled to
  1e-5 /s.
- **VTU** ("CPS Upper Core"): relative vorticity at 600 hPa minus
  relative vorticity at 300 hPa, same smoothing, same 1e-5 /s scaling.
- **CPScat** and **CPSidx** ("CPS Core Class" / "CPS Core Index"):
  VTL and VTU combined into a single field, blanked (NaN) outside a
  cyclonic vortex. See "Combined fields" below.
- **cpsZ850**: relative vorticity at 850 hPa alone, no vertical
  difference, no smoothing, scaled to 1e-5 /s like VTL/VTU. Debug-only
  field for the orientation check below.

Two more fields, **HB** and **HCPSclass**, exist in the separate, more
physically faithful Hart CPS family below (`HVTL`, `HVTU`, `HCPSclass`,
`HCPSidx`, `HB`) and are **not** in the 1e-5 /s convention above: `HB`
is Hart's frontal-asymmetry parameter in meters, and `HCPSclass` is the
joint classification of all three Hart parameters into Hart's six
named structures. See "Hart CPS family" below for both.

850/600 and 600/300 were picked to bracket Hart's 900-600 and 600-300
bands using pressure levels every model carries at every AWIPS site
(900 and 800 hPa are not universal on all D2D grids; 850, 600, and 300
are). The level pair is set entirely in the XML `<Field level="...">`
attributes in `derivedParameters/definitions/VTL.xml` and `VTU.xml` --
changing the bracketing levels needs no Python change, just an edit to
those two files (and to `cpsStyleRules.xml`'s comment, if the new
levels change the expected magnitude range).

## How to read it

**A second, more physically faithful family (HVTL, HVTU, HCPSclass,
HCPSidx) is now available -- see "Hart CPS family" below.** It computes
Hart's actual max-minus-min-of-height/least-squares-slope quantity
pointwise, using only geopotential height, instead of the vorticity
proxy this section describes. Once it is installed at your site, prefer
it over VTL/VTU/CPScat/CPSidx for cold-core detection: it does not carry
the vorticity proxy's tilt bias, its sensitivity to whatever upper-level
feature happens to be overhead, or its vorticity-based mask-selection
bias (see "Hart CPS family" for all three). The vorticity-proxy family
documented in the rest of this file remains available and unchanged --
the two are meant to be compared side by side, not to replace one
another outright, until a site has calibrated both against real cases.

Read VTL/VTU only in the neighborhood of a **closed low in the MSLP
field**. Away from a low center this is just the vertical shear of
whatever vorticity happens to be sitting there -- a jet streak, an
open shortwave trough -- and "warm core"/"cold core" language does not
apply.

- **Positive** = the cyclonic circulation weakens with height =
  tropical-like, warm-core structure.
- **Negative** = the circulation holds up or strengthens with height
  = baroclinic, cold-core structure (an upper trough over the surface
  low).

The magnitudes are **not** Hart's VTL/VTU numbers -- do not plot them
on Hart's phase-space axes or compare them to published Hart values.
What is meaningful here is the **sign** and its **trend in time**: a
system whose VTL/VTU climb from negative toward positive over a
forecast is one that is warming its core, i.e. undergoing (or
completing) tropical transition; the reverse trend is extratropical
transition.

### Known limitation: Southern Hemisphere sign

Relative vorticity of a Southern Hemisphere cyclone (clockwise
rotation) is **negative**, not positive. A SH tropical cyclone whose
clockwise circulation weakens with height therefore has
`zeta_lo - zeta_hi < 0` -- i.e. **a SH warm core reads NEGATIVE**,
the opposite of the Northern Hemisphere convention described above.
Hart's own B parameter has the same problem and fixes it with an
explicit hemisphere sign factor (`h = +1` NH, `-1` SH -- see
`cps/hart.py`'s `parameter_b`). The correct fix here would be
multiplying the output by `sign(latitude)`, which needs a latitude
pseudo-field as an extra input; this is a **TODO**, not implemented.
For now: south of the equator, mentally flip the sign of VTL/VTU (or
just remember "weakening circulation with height = warm core"
regardless of the number's sign).

## Combined fields: CPScat and CPSidx

VTL and VTU are two separate fields, and reading two overlaid fields
by eye to decide "is this warm-core or cold-core, and how much" is
exactly the kind of thing a derived parameter can do for a forecaster
instead. **CPScat** and **CPSidx** do that: both are computed from the
same three-level vorticity (see `CycloneCore.core_fields`) as VTL/VTU,
but combined into one field each, and both are **blanked (NaN)
outside of a cyclonic vortex** using the smoothed 850 hPa relative
vorticity as a mask -- see "Vortex mask" below.

### CPScat: categorical core class

`CPScat` buckets VTL and VTU into 5 integer categories:

| code | meaning                          | condition                                   |
|-----:|----------------------------------|----------------------------------------------|
|    4 | deep warm core                   | `vtl > band` and `vtu > band`                 |
|    3 | shallow warm core                | `vtl > band` and `vtu <= band`                |
|    1 | cold core                        | `\|vtl\| <= band` and `vtu < -band`           |
|    2 | neutral                          | `\|vtl\| <= band` and `vtu >= -band`          |
|    0 | mid-level vortex (rare, transient) | `vtl < -band` and `vtu > band`              |
|    1 | cold core                        | `vtl < -band` and `vtu <= band`               |

(code 1, cold core, has two rows because it covers both "VTL is
neutral but VTU is cold" and "VTL is cold" -- see
`CycloneCore.classify`'s docstring for the full decision table and how
the boundary values are assigned.) `band` is `DEFAULT_NEUTRAL_BAND`
unless overridden by CPScat.xml's `<ConstantField>`, which sets it in
the same 1e-5 /s units as VTL/VTU's readout (see "What the fields
are"); `executeClass()` divides that `<ConstantField>` value by
`UNIT_SCALE` before comparing it against `vtl`/`vtu`, which stay in SI
1/s internally throughout `classify()`.

### CPSidx: continuous core index

`CPSidx` is `2*tanh(vtl/scale) + tanh(vtu/scale)`, a single number
from -3 to +3: about +3 is a deep warm core (both terms saturated
positive), +1 to +2 a shallow warm core, near 0 neutral, negative cold
core. `scale` is `DEFAULT_INDEX_SCALE` unless overridden by
CPSidx.xml's `<ConstantField>`, in the same 1e-5 /s units as
`band` above. Use CPSidx where a continuous
trend matters (e.g. animating tropical transition); use CPScat where
a discrete label is easier to read at a glance or contour.

### Vortex mask

Both fields are masked to NaN wherever the smoothed 850 hPa relative
vorticity (computed once inside `core_fields`, the same smoothing as
VTL/VTU) is below `vortex_min` (`DEFAULT_VORTEX_MIN`), or wherever any
of VTL, VTU, or that vorticity is itself NaN (missing data). The point
is to keep "warm core"/"cold core" language from being printed over a
jet streak or open trough that just happens to have some vorticity
shear but is not a cyclonic vortex at all -- the same caveat VTL/VTU
carry in prose ("read it only near a closed low"), enforced here in
the data instead of left to the forecaster's judgment. `vortex_min` is
also given via a `<ConstantField>` in 1e-5 /s units, same as `band`.

```
DEFAULT_NEUTRAL_BAND = 3.0e-5   # SI 1/s internally; 3.0 (x1e-5 /s) at the
                                 # CPScat.xml <ConstantField> -- |VTL| or
                                 # |VTU| below this is "neutral"
DEFAULT_VORTEX_MIN   = 5.0e-5   # SI 1/s internally; 5.0 (x1e-5 /s) at the
                                 # <ConstantField> -- classify only where
                                 # smoothed 850 hPa relative vorticity
                                 # exceeds this
DEFAULT_INDEX_SCALE  = 1.0e-4   # SI 1/s internally; 10.0 (x1e-5 /s) at the
                                 # CPSidx.xml <ConstantField> -- scale for
                                 # CPSidx's tanh squashing
```

The SI values are what `classify()`/`continuous_index()` actually
compare against internally; the `<ConstantField>` values in
CPScat.xml/CPSidx.xml (and the `band`/`vortexMin`/`scale` keyword
defaults on `executeClass()`/`executeIndex()`) are those same numbers
times `UNIT_SCALE` (1e5), i.e. in the same 1e-5 /s units VTL/VTU
sample in. All three are just starting points (see the comments
beside each constant in `CycloneCore.py`) -- they have not been
calibrated against real cases.

### Calibration procedure

1. Pick three known systems from past cases: a mature hurricane (deep
   warm core), a deep extratropical low (cold core), and a
   subtropical storm (shallow/transitional warm core).
2. Install CPScat/CPSidx (below) alongside VTL/VTU and load VTL/VTU
   as point values (Volume Browser sampling, or a script against the
   same grids) at each system's surface low center, across a few
   forecast hours per case. Remember VTL/VTU sample in 1e-5 /s (a
   sampled value of 6 means 6e-5 /s in SI).
3. Set `band` (`DEFAULT_NEUTRAL_BAND`) to roughly **half the smallest
   clear signal** you see -- e.g. if the weakest genuinely-warm-core
   case still shows `vtl` sampling around 6, set the CPScat.xml/
   CPSidx.xml `band` `<ConstantField>` near 3 (i.e. 3e-5 /s in SI) so
   it clears the neutral zone without also swallowing genuine noise.
4. Set `vortex_min` (`DEFAULT_VORTEX_MIN`) **just below the smoothed
   850 hPa vorticity of the weakest low you still want classified** --
   low enough that your subtropical/weak case is not masked out, high
   enough that random open-wave vorticity does not get labeled. Set
   this as a `<ConstantField>` in the same 1e-5 /s units as `band`
   (the shipped default is 5, i.e. 5e-5 /s in SI).
5. Re-run all three cases against the new constants (pass them as
   the `band`/`vortexMin`/`scale` `<ConstantField>` values, in 1e-5 /s
   units, or call `classify`/`continuous_index` directly in SI 1/s)
   and check the codes/index match forecaster judgment before
   trusting either field operationally at your site.

### Known limitation: Southern Hemisphere masking

The vortex mask is the smoothed 850 hPa relative vorticity itself, and
(as above) that vorticity is **negative**, not positive, for a
Southern Hemisphere cyclone. `zeta_lo < vortex_min` is therefore true
almost everywhere in the SH, and CPScat/CPSidx come out **entirely
NaN over SH cyclones** -- not merely sign-flipped like VTL/VTU, but
blanked outright. The fix is the same TODO as VTL/VTU's: a latitude
pseudo-field to flip the mask's sign (and threshold) south of the
equator. Not implemented. For now, CPScat/CPSidx are Northern
Hemisphere fields only; use VTL/VTU with the mental sign-flip
described above for SH systems instead.

## Install

EDEX, site-level `common_static`:

```
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/VTL.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/VTU.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/CPScat.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/CPSidx.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cpsZ850.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/functions/CycloneCore.py
```

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
`CoreClass.cmap` to
`/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/Grid/`.
Restart CAVE. Even without the style rules, both then appear in the
right-click legend menu under Change Colormap, listed under Grid (a
separate colormap subfolder at site level was not possible on the
OPC build, so both live in the existing Grid folder with the `CPS_`
prefix telling them apart, not in a submenu of their own).

Colormaps (referenced by the imagery style rules above instead of a
base colormap like `Grid/Difference`, which is not guaranteed to exist
at every site):

```
/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/Grid/CPS_CoreDiverging.cmap
/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/Grid/CPS_CoreClass.cmap
```

(VERIFY the exact colormaps path for your AWIPS version.) `CoreDiverging`
is used by VTL, VTU, and CPSidx; `CoreClass` is used by CPScat only. See
the comments inside each `.cmap` file and in `cpsStyleRules.xml` for the
color/category tables and the file-format VERIFY note.

## Orientation verification (do this once per site, before trusting the sign)

D2D derived parameters receive grids exactly as AWIPS stores them, and
the array layout -- whether row index (axis 0) increases toward the
north or the south, and whether the axes are x/y or y/x at all -- is a
property of the grid's projection and storage, not something this file
can know in advance. `CycloneCore.py` calls this layout the
`ORIENTATION_MODE`, an integer 0-3 (see the comment block above that
constant in `CycloneCore.py` for exactly what each mode means); the
module default is `1`, which is correct for most AWIPS D2D grids, but
verify it at your site with the procedure below before trusting VTL,
VTU, CPScat, or CPSidx's sign.

The debug field `cpsZ850.xml` (relative vorticity at 850 hPa alone, no
vertical difference, no smoothing) carries its own `mode`
`<ConstantField>`, set to `1` out of the box, so a site can try modes
by editing one number in the XML instead of editing and redeploying
`CycloneCore.py` for every guess:

1. Install `cpsZ850.xml` (above) alongside VTL/VTU, with its `mode`
   `<ConstantField>` left at `1`.
2. In the Volume Browser, load **cpsZ850** and D2D's own base
   **relative vorticity** field, both at 850 mb, over a real Northern
   Hemisphere hurricane (i.e. a system you know is cyclonic there).
3. Compare the two fields at the storm's core:
   - **cpsZ850 is a single positive blob matching D2D's field**
     (same sign, same single-centered shape) -- mode 1 is correct.
     Done: set `ORIENTATION_MODE = 1` in `CycloneCore.py` (already the
     default) and skip to step 5.
   - **cpsZ850 is lobed** (a deformation-like pattern, not a single
     blob) **or has the opposite sign** -- edit `cpsZ850.xml`'s
     `<ConstantField>` from `1` to `2`, reload the field (restart CAVE
     if your version does not reload an edited definition on its own),
     and compare again.
4. Repeat step 3's comparison with mode `3` if mode `2` did not match
   either. One of 1, 2, or 3 matches for every known AWIPS grid
   convention; if none do, something else is wrong (see
   Troubleshooting) -- do not guess past mode 3.
5. Once a mode's cpsZ850 matches D2D's own relative vorticity, open
   `derivedParameters/functions/CycloneCore.py`, set `ORIENTATION_MODE`
   to that value at the top of the file, and restart CAVE. VTL, VTU,
   CPScat, and CPSidx all call `relative_vorticity()` with no explicit
   mode, so they pick up `ORIENTATION_MODE` from the module as soon as
   it is redeployed -- the `mode` constant in `cpsZ850.xml` only
   overrides the module default for that one debug field, and has no
   effect on the other four fields.

Do this before relying on VTL/VTU's sign for any real decision.

## Suggested display recipe

A useful overlay/4-panel for a tropical or transitioning system:

1. MSLP contours (locate the closed low).
2. VTL as filled imagery (diverging colormap, warm core pops as one
   color, cold core the other). VTL/VTU and CPSidx fills are
   intentionally transparent near zero (the neutral, near-boundary
   values) so the MSLP contours from step 1 still show through
   underneath instead of being painted over.
3. VTU as contours, overlaid on the same panel or a second panel, to
   see whether the lower and upper troposphere agree.
4. 10 m wind barbs, for context on the surface circulation.
5. 850-500 hPa thickness, for a classic warm/cold-core cross-check
   against a field forecasters already trust.

CPScat should be displayed as filled imagery, not as contours - it is
a categorical code (see "CPScat: categorical core class" above), and
contouring a categorical field draws misleading lines through what are
really just five discrete color bins.

A 4-panel layout (MSLP+VTL, VTU alone, 10 m wind, 850-500 thickness)
or a single overlay of all five on one map both work; which is more
useful depends on screen space and personal preference.

## Tests

```
python3 -m pytest tests/d2d_cps -q
```

`tests/d2d_cps/conftest.py` puts `D2D/derivedParameters/functions` on
`sys.path` so the tests can `import CycloneCore` the same way AWIPS's
embedded interpreter would (as a bare module, not a package), without
needing any AWIPS runtime present.

You can also just run the module directly for a quick sanity check
with no pytest involved:

```
python3 D2D/derivedParameters/functions/CycloneCore.py
```

It builds a synthetic solid-body vortex and prints the analytic and
computed vorticity/execute() values side by side.

## Troubleshooting

**DataCubeException on CPScat or CPSidx while VTL/VTU work.** Two known
causes, distinguishable from the cause line in the CAVE log:

1. Unit parsing or a null pointer in the derived parameter description:
   the definition had no `unit` attribute. CPScat.xml and CPSidx.xml
   now declare `unit=""`. If that is also rejected, try `unit="1"`.
   (VTL.xml, VTU.xml, and cpsZ850.xml also declare `unit=""` now, but
   for a different reason: their values are scaled by `UNIT_SCALE` for
   readable sampling -- see "What the fields are" -- so `unit="/s"`
   would mislabel them; `unit=""` was confirmed to load on a real site
   for these too.)
2. A Python traceback ending in `has no attribute 'executeClass'` (or
   `executeIndex`): CAVE is still running the first CycloneCore.py.
   Replace the file on EDEX and restart CAVE; the embedded interpreter
   caches modules until restart.

**Dipole (positive next to negative) on CPSidx or VTL at a low.** Two
causes:

1. Vertical tilt, which is physical. The low-level vortex and the upper
   vortex sit in different places on a sheared or baroclinic system, so
   a pointwise level difference is positive under one and negative under
   the other. Hart's 500 km circle integrates over this; the pointwise
   method does not. Fix: raise the smoothKm ConstantField in CPScat.xml
   and CPSidx.xml from 100 to 250 (a 500 km box, close to Hart's radius)
   or 350 for large extratropical lows. The box mean of vorticity is
   circulation over the box, so this is the intended move toward a
   vortex-scale number.
2. Wrong grid orientation, which is a bug. Then cpsZ850 itself shows
   lobes (or the wrong sign) rather than a single blob matching D2D's
   own relative vorticity at a hurricane. Run the "Orientation
   verification" procedure above to find the right `ORIENTATION_MODE`
   for your site.

**The five Hart fields (HVTL, HVTU, HCPSclass, HCPSidx, HB)
disappear from the Product Browser after adding the below-ground
mask.** The first suspect is the `P` (surface pressure)
`<Field level="Surface"/>` in cps_HVTL.xml/cps_HVTU.xml/cps_HCPSclass.xml/cps_HCPSidx.xml/
cps_HB.xml -- specifically its level spelling. This site's
other Field level spellings in these files ("925MB", "Surface" on the
`<Method>` itself, etc.) are already confirmed to load; `P`'s own
level was not independently re-verified against a base surface-pressure
definition when this mask was added. Some AWIPS builds spell the
surface plane `level="0.0SFC"` instead of `level="Surface"` for a Field
reference (as opposed to the `<Method levels="...">` attribute, which
is a different thing and unaffected). Check a base definition that
already uses surface pressure (or GRIB metadata for the `P` parameter)
and adjust the `level` attribute on that one `<Field>` line in all five
files if needed -- everything else in the definitions is unchanged. If
only `HB`/`HCPSclass` fail to load while the other three still work, the
more likely cause is the `coriolis` pseudo-field, not `P` -- see "Hart
CPS family" below.

## Hart CPS family (HVTL, HVTU, HCPSclass, HCPSidx, HB)

*** EXPERIMENTAL. NOT OPERATIONALLY VETTED. *** This is a second,
independent derived-parameter family (`cps_HartCPS.py`, `cps_HVTL.xml`,
`cps_HVTU.xml`, `cps_HCPSclass.xml`, `cps_HCPSidx.xml`, `cps_HB.xml`)
alongside everything above (`CycloneCore.py` and
VTL/VTU/CPScat/CPSidx/cpsZ850). `CycloneCore.py` is completely
untouched by this family -- the two exist so a site can compare them
side by side, not so one replaces the other in the code. `HB` (Hart's
parameter B, thermal asymmetry) feeds `HCPSclass` (the joint
classification below) as well as standing on its own; see "Parameter
B (HB) and its role in HCPSclass" below.

**Retired 2026-09-18: `HCPScat` (Phase 2 class) and `HETstage` (ET
stage) are gone.** Both are replaced by the single joint classification
`HCPSclass`, computed from all three Hart parameters (`HVTL`, `HVTU`,
and `B`) at once instead of two separate two-term views. See "Joint
classification (HCPSclass) and index (HCPSidx)" below for why one
field replaces both, and the validation log's note for how to read an
old `HCPScat` value against the new field.

### What it is, and why it replaces the vorticity proxy

Everything above this section is a *vorticity-based proxy* for Hart's
(2003) thermal wind parameters: a vertical difference of relative
vorticity, chosen because it is cheap to compute pointwise and because
forecasters already read vorticity fields. It only *rhymes* with
Hart's VTL/VTU -- same sign convention, same rough level bands -- it is
not the same quantity.

`cps_HartCPS.py` instead computes **Hart's actual quantity**: at every grid
point, `dZ(level) = max(Z) - min(Z)` of geopotential height over a
window of half-width 500 km centered on that point (Hart's own analysis
radius, evaluated at every point instead of only at one storm's moving
center -- see `cps_HartCPS.py`'s module docstring for why a square window is
used instead of Hart's circle, and why the difference is small in
practice), then `-V_T` is the least-squares slope of `dZ` against
`ln(pressure)` over a band of levels. This uses **geopotential height
only** -- no wind field, no vorticity, no smoothing choice.

This is meant to replace the vorticity proxy for **cold-core
detection** specifically, because the proxy has three known biases the
height-based method does not share:

- **Tilt bias.** A pointwise vertical vorticity *difference* at one
  grid point compares the lower and upper vortex centers only if they
  happen to sit at the same (x, y) -- on a sheared or baroclinic system
  they usually do not, producing a spurious dipole (see
  "Troubleshooting" above) that the vorticity proxy can only paper over
  by widening its smoothing box toward Hart's own radius. The
  height-based `dZ` is already an integral over a 500 km window by
  construction, so it does not need that workaround.
- **Broad-upper-feature bias.** Relative vorticity aloft responds to
  whatever upper-level feature happens to be overhead -- a jet streak,
  an unrelated shortwave -- not only to the storm's own upper warm
  core. `dZ` responds to the height field's own local max-minus-min,
  which is far less sensitive to a passing unrelated feature at the
  edge of the window.
- **Mask-selection bias.** CPScat/CPSidx mask on the smoothed 850 hPa
  relative vorticity itself -- the same quantity VTL/VTU are built
  from -- so the vortex test and the warm/cold-core signal are not
  independent. HCPSclass/HCPSidx mask on `closed_low_mask`, a genuinely
  different measurement (1000 hPa height's own local shape), so a point
  being "inside a real low" is decided independently of what its
  thermal wind sign turns out to be.

The magnitudes here are meters (of `dZ`) per unit of `ln(pressure in
hPa)` -- plain meters -- **not** the same unit as `CycloneCore.py`'s
scaled relative-vorticity VTL/VTU, and the two families should never be
plotted on the same axis. A mature hurricane typically samples HVTL/
HVTU in the +100 to +300 m range; a cold-core low typically samples
-100 to -300 m. These are **near but not equal to** the published Hart
(2003)/FSU CPS values for the same real storms -- both because of the
square-vs-circle window difference (typically well under the ~2%
agreement measured against `cps.hart.thermal_wind` on a synthetic
vortex in `tests/d2d_cps/test_hart_cps.py`) and because the standard
levels used here are not exactly Hart's own bands (next section). Do
not report HVTL/HVTU numbers as if they were the published FSU CPS
diagnostic for a storm -- read the sign and the trend, the same caution
as VTL/VTU above, just for a different reason (the proxy's biases
described above do not apply here, but the window-shape and
level-band approximations still mean the exact number will differ
slightly from FSU's own website for the same case).

### Standard-level bands

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

### Closed-low mask

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

An earlier version of this mask used a plain "close to the local
minimum, and the window max-minus-min is big enough" test, and turned
out to pass
**everywhere** on a uniform height gradient (e.g. a steady 40-60 m per
1000 km slope across a front, no low at all): every point on a slope
is, to a few meters, already the minimum of its own neighborhood in
the one direction the slope descends, and the window max-minus-min
over a 500 km box is large simply because the slope has covered a lot
of height by the time it reaches the box's far edge. The current mask
uses two tests a monotonic slope cannot satisfy together:

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

All of `centerTolM`, `depthM`, `blobKm` are already in meters/km -- no
`UNIT_SCALE` round trip like CycloneCore.py's `vortexMin`, since this
field was never rescaled to begin with. `centerTolM` itself is not
exposed as a public `<ConstantField>` on cps_HCPSclass.xml/cps_HCPSidx.xml (see
`cps_HartCPS.executeHartClass`'s docstring) -- only `radiusKm`, `depthM`,
`blobKm`, and (below) `capHpa` are.

### Below-ground masking

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

### Joint classification (HCPSclass) and index (HCPSidx)

`HCPSclass` replaces the retired `HCPScat`/`HETstage` pair with one
field computed from all three Hart parameters at once: `B` (against
Hart's frontal threshold of 10 m) and both thermal wind terms (each
against 0, strictly; warm if greater than or equal to 0, cold if
less than 0). Hart's own two diagrams are two projections of this same
three-dimensional space that happen to share the lower thermal wind
axis; each diagram alone carries one piece of information the other
lacks (frontal or not, from `B`; deep or shallow warm core, from
`HVTU`). Classifying on all three numbers at once carries both and
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
| 6 | mid-level vortex | any | cold | warm | rare, treat as unclassified |
| blank | | | | | no closed low, or B undefined (steering below 1 m/s) |

The codes rise along a typical extratropical transition (0, 2, 3, 4)
and a warm seclusion is 4 then back to 1. `HCPSclass` is NaN outside
`closed_low_mask`, same as the retired `HCPScat`. There is no neutral
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

`HCPSidx` is unchanged: `2*tanh(HVTL/scaleM) + tanh(HVTU/scaleM)`
(default `scaleM` = 100 m), range -3 to +3, same reading as
CycloneCore.py's CPSidx, and still the only place in this family a
neutral band (via `scaleM`) survives.

### Parameter B (HB) and its role in HCPSclass

Hart's (2003) third CPS number, **B** (thermal asymmetry), is the
right-minus-left half-window mean of 900-600 hPa thickness across the
storm's own direction of motion, over the same 500 km analysis circle
VTL/VTU use: `B = h * (mean_right - mean_left)`, `h = +1` in the
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

### No orientation mode, no hemisphere sign issue

Unlike `CycloneCore.py`, `HVTL`/`HVTU`/`HCPSidx` have **no
`ORIENTATION_MODE` to verify** and **no Southern Hemisphere sign
caveat**. Both of `CycloneCore.py`'s known limitations come from using
relative vorticity, which depends on the grid's axis layout (hence
`ORIENTATION_MODE`) and flips sign with hemisphere (cyclonic rotation
is negative vorticity south of the equator). `max(Z) - min(Z)` and a
least-squares slope are both orientation-independent and
hemisphere-independent by construction, so those three fields read the
same way (positive = warm core) at every latitude, with no
verification procedure needed before trusting the sign.

`HB` and `HCPSclass` are the exception in this family: both need `B`,
which needs the thickness field's own spatial *gradient* (`cps_HartCPS.
gradient_2d`), which -- like `CycloneCore.relative_vorticity` -- does
depend on the grid's axis layout. `cps_HartCPS.py` therefore has its own
`ORIENTATION_MODE` (same 0..3 semantics as `CycloneCore.py`'s, default
1, confirmed on the OPC build), used only by `gradient_2d`; every other
function in `cps_HartCPS.py`, including `HVTL`/`HVTU`/`HCPSidx`'s own
computation, is unaffected and needs no orientation check. Hemisphere
is handled explicitly for `HB`/`HCPSclass` via the coriolis
pseudo-field's sign (see "Parameter B (HB) and its role in HCPSclass"
above), not by an assumption baked into the math the way relative
vorticity's sign is, so there is still no Southern Hemisphere caveat to
carry over.

### Performance

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

### Adding a GFS-only 13-level definition

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

### Install

EDEX, site-level `common_static` (in addition to the CycloneCore.py
files under "Install" above -- this family does not replace them):

```
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HVTL.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HVTU.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HCPSclass.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HCPSidx.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/cps_HB.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/functions/cps_HartCPS.py
/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/Grid/CPS_HartClass.cmap
```

The `cps_` file prefix is only so the family sorts together in the
Localization perspective and on disk; AWIPS keys each definition on the
`abbreviation` inside the XML (HVTL, HVTU, HB, HCPSidx, HCPSclass) and
the function module on the `Method name` in the XML, so the product
names in D2D are unchanged. If you are upgrading from the unprefixed
files, delete the old `HVTL.xml`, `HVTU.xml`, `HB.xml`, `HCPSidx.xml`,
`HCPSclass.xml` and `HartCPS.py` from the same directories first, or
the two copies of each definition will collide.

Restart CAVE (and EDEX, if new definitions do not show up in the
Volume Browser on their own -- see the CycloneCore.py "Install" note
above) after copying these in.

The updated `cpsFields.xml` (with the new "Hart CPS (height based,
experimental)" title and its five menu items, including `HB` and
`HCPSclass`) and the additions to `cpsStyleRules.xml` (HVTL/HVTU/
HCPSidx imagery and contour `<styleRule>` blocks, plus `HB` imagery and
contour and `HCPSclass` imagery blocks) install the same way as the
rest of those two files -- see "Install" above; they are not drop-in
files either.

### Tests

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
vortices. Run
`python3 D2D/derivedParameters/functions/cps_HartCPS.py` directly for a
quick standalone sanity check (a synthetic warm-core vortex, printing
the lower/upper slope and the class at its center, plus a parameter B
demo on a linear thickness gradient with its analytic expectation)
with no pytest or AWIPS runtime involved.

## Validation log

Real cases sampled at the MSLP center in D2D. Add to this as cases
accumulate; it is the calibration record for the thresholds.

| Date sampled | Model, cycle, fhr | System | VTL | VTU | CPScat | CPSidx | HVTL (m) | HVTU (m) | HCPScat | HCPSidx |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-09-14 | GFS 12Z, 72 h | Typhoon, 24N 147E, 984 mb | 6.45 | 12.24 | 4 | 1.98 | | | | |
| 2026-09-14 | GFS 12Z, 72 h | Post-tropical low, 62N 20W, 978 mb, tilted | -1.07 | 5.05 | 2 (cold ring) | 0.31 | | | | |
| 2026-09-17 | GFS 12Z, 72 h | Same typhoon, 31N 139E, 984 mb | | | | | 120 | 180 | 4 | 2.5 |
| 2026-09-17 | GFS 12Z, series | Typhoon Dujuan, loss of deep warm core | | | | | | | drops from 4 at Mon 21 Sep 18Z | |
| 2026-09-17 | GFS 12Z | Deep extratropical low, North Atlantic | | | | | negative (value not recorded) | negative (value not recorded) | 1 | negative |

**Note (2026-09-18):** `HCPScat` and `HETstage` were retired on this
date in favor of the single joint classification `HCPSclass` (see
"Joint classification (HCPSclass) and index (HCPSidx)" above). The
rows above predate the change and are kept as recorded; reading them
against the new field, `HCPScat` = 4 (deep warm core) corresponds to
`HCPSclass` 0 (symmetric) or 2 (frontal) depending on `B`, which was
not computed for those rows.

Notes: the vorticity family read the tilted post-tropical low as
neutral at the center with a cold ring where the upper trough sat,
which is the tilt bias the Hart family was built to remove. The Hart
values for the typhoon are in Hart's published hurricane range. The
Hart family validated on a cold-core case (class 1, both terms
negative). External check: the first forecast hour at which the
storm's classification left its deep-warm-core state for Typhoon
Dujuan (Mon 21 Sep 2026 18Z, `HCPScat` dropping below 4 in the
now-retired product) matches the hour the FSU cyclone phase page shows
the same GFS run moving from deep to shallow warm core. This is the
loss of the upper warm core, not the Evans and Hart (2003) onset, which
is read from the animation as the first frame `HCPSclass` reaches 2 or
3 (`B` above 10 m) and awaits validation on a real case. After
the surface-pressure mask, Greenland and the
high terrain of western North America are blank rather than
contaminated, which is the intended behavior. A few very weak closed
lows (under about 5 hPa deep) get no class blob at the shipped depth of
40 m; set depthM to 25 in cps_HCPSclass.xml and cps_HCPSidx.xml to include them.

**Status: the D2D version is release-ready as of 2026-09-17**, still
labeled experimental pending a season of use. Known limitations: the
raw HVTL/HVTU fields paint a square footprint around each low (the
window shape, cosmetic); the vorticity family reads Southern Hemisphere
warm cores with the wrong sign (the Hart family does not); style rules
did not auto-apply on the OPC build, so colors come from a saved
procedure.
