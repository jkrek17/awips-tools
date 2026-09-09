# D2D cyclone core structure (VTL, VTU, cpsZ850)

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

## Install

EDEX, site-level `common_static`:

```
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/VTL.xml
/awips2/edex/data/utility/common_static/site/<SITE>/derivedParameters/definitions/VTU.xml
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

## Orientation verification (do this once per site, before trusting the sign)

D2D derived parameters receive grids exactly as AWIPS stores them, and
whether row index (grid axis 0) increases toward the north or the
south is a property of the grid's projection and storage, not
something this file can know in advance. `CycloneCore.py` assumes
`Y_INCREASES_NORTHWARD = True`, which is correct for the great
majority of AWIPS D2D grids, but verify it:

1. Install `cpsZ850.xml` (above) alongside VTL/VTU.
2. In the Volume Browser, load **cpsZ850** and D2D's own base
   **relative vorticity** field, both at 850 mb, over a real Northern
   Hemisphere hurricane (i.e. a system you know is cyclonic there).
3. Compare signs at the storm's core:
   - **Both positive** (or both negative, but matching) -- orientation
     is correct, no change needed.
   - **Opposite signs** -- open `derivedParameters/functions/
     CycloneCore.py` and set `Y_INCREASES_NORTHWARD = False` at the top
     of the file, then repeat the check.

Do this before relying on VTL/VTU's sign for any real decision.

## Suggested display recipe

A useful overlay/4-panel for a tropical or transitioning system:

1. MSLP contours (locate the closed low).
2. VTL as filled imagery (diverging colormap, warm core pops as one
   color, cold core the other).
3. VTU as contours, overlaid on the same panel or a second panel, to
   see whether the lower and upper troposphere agree.
4. 10 m wind barbs, for context on the surface circulation.
5. 850-500 hPa thickness, for a classic warm/cold-core cross-check
   against a field forecasters already trust.

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
