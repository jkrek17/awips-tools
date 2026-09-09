# D2D cyclone core structure (VTL, VTU, CPScat, CPSidx, cpsZ850)

*** EXPERIMENTAL. NOT OPERATIONALLY VETTED. *** This is a pointwise D2D
derived-parameter shortcut, not Hart's (2003) Cyclone Phase Space
method (`cps/hart.py`, `web/CPS/PLAN.md`). It only rhymes with Hart's
VTL/VTU: same sign convention (positive = warm core), same rough level
bands, computed a completely different way because a D2D derived
parameter has no concept of "the storm's center" -- it runs pointwise
over the whole grid.

## What the fields are

- **VTL** ("CPS Lower Core"): relative vorticity at 850 hPa minus
  relative vorticity at 600 hPa, smoothed over a ~100 km box.
- **VTU** ("CPS Upper Core"): relative vorticity at 600 hPa minus
  relative vorticity at 300 hPa, same smoothing.
- **CPScat** and **CPSidx** ("CPS Core Class" / "CPS Core Index"):
  VTL and VTU combined into a single field, blanked (NaN) outside a
  cyclonic vortex. See "Combined fields" below.
- **cpsZ850**: relative vorticity at 850 hPa alone, no vertical
  difference, no smoothing. Debug-only field for the orientation check
  below.

850/600 and 600/300 were picked to bracket Hart's 900-600 and 600-300
bands using pressure levels every model carries at every AWIPS site
(900 and 800 hPa are not universal on all D2D grids; 850, 600, and 300
are). The level pair is set entirely in the XML `<Field level="...">`
attributes in `derivedParameters/definitions/VTL.xml` and `VTU.xml` --
changing the bracketing levels needs no Python change, just an edit to
those two files (and to `cpsStyleRules.xml`'s comment, if the new
levels change the expected magnitude range).

## How to read it

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
unless overridden by CPScat.xml's `<ConstantField>`.

### CPSidx: continuous core index

`CPSidx` is `2*tanh(vtl/scale) + tanh(vtu/scale)`, a single number
from -3 to +3: about +3 is a deep warm core (both terms saturated
positive), +1 to +2 a shallow warm core, near 0 neutral, negative cold
core. `scale` is `DEFAULT_INDEX_SCALE` unless overridden by
CPSidx.xml's `<ConstantField>`. Use CPSidx where a continuous
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
the data instead of left to the forecaster's judgment.

```
DEFAULT_NEUTRAL_BAND = 3.0e-5   # 1/s; |VTL| or |VTU| below this is "neutral"
DEFAULT_VORTEX_MIN   = 5.0e-5   # 1/s; classify only where smoothed 850 hPa
                                 # relative vorticity exceeds this
DEFAULT_INDEX_SCALE  = 1.0e-4   # 1/s; scale for CPSidx's tanh squashing
```

All three are just starting points (see the comments beside each
constant in `CycloneCore.py`) -- they have not been calibrated against
real cases.

### Calibration procedure

1. Pick three known systems from past cases: a mature hurricane (deep
   warm core), a deep extratropical low (cold core), and a
   subtropical storm (shallow/transitional warm core).
2. Install CPScat/CPSidx (below) alongside VTL/VTU and load VTL/VTU
   as point values (Volume Browser sampling, or a script against the
   same grids) at each system's surface low center, across a few
   forecast hours per case.
3. Set `band` (`DEFAULT_NEUTRAL_BAND`) to roughly **half the smallest
   clear signal** you see -- e.g. if the weakest genuinely-warm-core
   case still shows `vtl` around 6e-5, set `band` near 3e-5 so it
   clears the neutral zone without also swallowing genuine noise.
4. Set `vortex_min` (`DEFAULT_VORTEX_MIN`) **just below the smoothed
   850 hPa vorticity of the weakest low you still want classified** --
   low enough that your subtropical/weak case is not masked out, high
   enough that random open-wave vorticity does not get labeled.
5. Re-run all three cases against the new constants (pass them as
   the `band`/`vortexMin`/`scale` `<ConstantField>` values, or call
   `classify`/`continuous_index` directly) and check the codes/index
   match forecaster judgment before trusting either field
   operationally at your site.

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

Style rules: `D2D/styleRules/cpsStyleRules.xml` is not a drop-in file.
Merge its imagery `<styleRule>` block into the site's
`gridImageryStyleRules.xml` and its contour `<styleRule>` block into
`gridContourStyleRules.xml`, matching whatever element/attribute names
your site's base files actually use.

Colormaps (referenced by the imagery style rules above instead of a
base colormap like `Grid/Difference`, which is not guaranteed to exist
at every site):

```
/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/CPS/CoreDiverging.cmap
/awips2/edex/data/utility/common_static/site/<SITE>/colormaps/CPS/CoreClass.cmap
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
   the definition had no `unit` attribute. Both files now declare
   `unit=""`. If that is also rejected, try `unit="1"`.
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
