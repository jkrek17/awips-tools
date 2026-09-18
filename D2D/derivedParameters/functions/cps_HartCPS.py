"""
cps_HartCPS.py -- AWIPS II D2D derived parameter: Hart (2003) actual thermal
wind parameters, computed pointwise on the grid.

*** EXPERIMENTAL.  NOT OPERATIONALLY VETTED. ***

This is a second, independent implementation of the cyclone-core-
structure idea already covered by `CycloneCore.py` (VTL, VTU, CPScat,
CPSidx) in this same directory. That family is a vorticity-based proxy
chosen because it is cheap and because relative vorticity is what a
forecaster already has muscle memory for reading. This family instead
computes Hart's own quantity -- the actual -V_T^L / -V_T^U thermal wind
parameters from `cps/hart.py`'s `thermal_wind` -- at every point of the
grid, using nothing but geopotential height. `CycloneCore.py` is left
completely untouched; the two families are meant to be compared against
each other, not merged.

Method
------

Hart's (2003) diagnostic, as done storm-centered in `cps/hart.py`, is:
at each pressure level, `dZ = max(Z) - min(Z)` over a 500 km-radius
circle centered on the storm's own analysis center; then -V_T (the
sign flipped so that positive means warm core, matching Hart's own
axis label) is the least-squares slope of `dZ` against `ln(pressure)`
over a band of levels. A D2D derived parameter has no notion of "the
storm's center" -- it runs pointwise over the whole model grid -- so
this module re-centers that same circle on *every* grid point instead
of on one storm: `dZ(level)` at grid point `(i, j)` is `max(Z) - min(Z)`
over a window of half-width `RADIUS_KM` centered on `(i, j)`, and the
thermal wind at `(i, j)` is the least-squares slope of that pointwise
`dZ` against `ln(pressure)` over a band of levels. This is exactly
Hart's formula, just evaluated at every point instead of at one moving
storm center -- unlike `CycloneCore.py`, which computes a genuinely
different quantity (a vertical vorticity difference) that only rhymes
with Hart's sign convention. The two should be read as complementary:
this family is the more physically faithful one and is meant to
eventually replace the vorticity proxy for cold-core detection (see
D2D/README.md for the vorticity proxy's known biases -- vertical tilt,
sensitivity to which upper-level feature happens to sit overhead, and
mask-selection bias from using vorticity itself as the vortex test).

Sign convention: identical to `cps.hart.thermal_wind` -- **positive
means warm core**. A tropical cyclone has more low-level thickness
right over its center than 500 km out, and that excess shrinks with
height, so `dZ` is larger at high pressure (large ln p) than at low
pressure (small ln p): a positive slope of `dZ` against `ln(p)`. A
cold-core system is the opposite and comes back negative.

Units: like Hart's own VTL/VTU, the output is in meters (of `dZ`) per
unit of `ln(pressure in hPa)` -- i.e. plain meters, since `ln(p)` is
dimensionless. A mature hurricane typically samples in the +100 to
+300 m range; a cold-core low typically samples -100 to -300 m. These
are not the same units as `CycloneCore.py`'s VTL/VTU (which are scaled
relative vorticity, 1e-5 /s) and the two should never be plotted on
the same axis or compared numerically -- only by sign and trend.

Standard level bands
---------------------

Hart's own bands are 900-600 hPa (lower) and 600-300 hPa (upper), each
sampled every 50 hPa (900, 850, 800, 750, 700, 650, 600 / 600, 550,
500, 450, 400, 350, 300). Most AWIPS D2D grids do not carry 50 hPa
resolution in the mid-troposphere -- GFS's own native grid does, but
many downstream/thinned grids only carry the "standard" set (1000,
925, 850, 700, 500, 400, 300, 250, 200, ...). Rather than depend on
levels that are only reliably present on one model, this module's
`executeHartClass`/`executeIndexStd`/`HVTL`/`HVTU` use exactly:

    LOWER_BAND = (925, 850, 700)   hPa
    UPPER_BAND = (500, 400, 300)   hPa

both of which are on the universal standard-level list. This leaves
the 700-500 hPa layer **unassigned** -- neither band claims it -- on
purpose: forcing it into either band would mean averaging a layer that
straddles the actual 600 hPa boundary Hart uses into a band it does
not belong to, which would bias that band's slope toward whichever
side 700-500 got glued onto. Leaving a small gap between the two bands
is a smaller, more honest error than that. A future GFS-only,
Hart-exact definition, using the true 7-level bands at 50 hPa spacing,
is supported by `executeBand7` below and needs only a new XML
definition (no Python change) once a site confirms its grid actually
carries every 50 hPa level from 900 to 300.

Square window versus Hart's circle
-----------------------------------

Hart's `max`/`min` is taken over a *circle* of radius `RADIUS_KM`. This
module instead uses a *square* window of half-width `RADIUS_KM` (i.e.
`window_extreme_2d`'s sliding-window max/min), because a square window
along grid axes can be computed with a fast doubling/sparse-table
sliding-window algorithm, while an arbitrarily-oriented circular
window on a lat/lon grid cannot be done nearly as cheaply pointwise
for every grid cell. The square's corners reach `sqrt(2) * RADIUS_KM`
(~1.41x Hart's true radius) from the center, so the square window is
mildly larger than Hart's circle along the diagonals. In practice this
makes little difference: for a smooth, roughly axisymmetric height
field around a vortex (or a smoothly varying background field away
from one), the window's `max` is attained at or very near the center
point itself and the window's `min` is attained somewhere out in the
smooth far field, and the far field's value changes little between
`RADIUS_KM` and `1.41 * RADIUS_KM` out -- so the extra reach of the
square's corners rarely changes which value gets picked, or changes it
only slightly. See `tests/d2d_cps/test_hart_cps.py` for a direct
numerical comparison against `cps.hart.thermal_wind` on a synthetic
warm-core vortex (agreement within 2%).

Closed-low mask level
----------------------

`closed_low_mask` (used by `executeHartClass`/`executeIndexStd` to blank
every point outside a real closed low) is computed from **1000 hPa
height** (`z1000`), a separate argument from the six `LOWER_BAND`/
`UPPER_BAND` heights the thermal wind itself is built from. 1000 hPa
height is nearly a linear function of MSLP (about 8 m per hPa), so the
closed low the mask finds is, to a good approximation, the same closed
low a forecaster already sees drawn on the MSLP contours -- which is
the point of masking at all. `DEFAULT_DEPTH_M` (40 m) is therefore
about 5 hPa of MSLP. 1000 hPa is below ground over major terrain and
below sea level inside a sufficiently deep low, so the model is
extrapolating there rather than reporting an analyzed height; see
"Below-ground masking" below for how that is handled.

Below-ground masking
----------------------

Every height level this module uses -- `z1000` and the six
`LOWER_BAND`/`UPPER_BAND` levels -- can be below the ground surface
over major terrain, or below sea level itself inside a sufficiently
deep low, where the model is extrapolating rather than reporting an
analyzed height. Over the open ocean that extrapolation is harmless (a
deep low's surface pressure legitimately drops well under 1000 or
925 hPa at its own center, and the height there is still meaningful).
Over ice sheets and high mountains it is not: a level whose pressure
is below the local surface pressure is fictitious, and letting it into
a window's max/min or the closed-low mask's ring mean can quietly bias
the result.

`mask_below_ground(z, psfc_hpa, level_hpa, cap_hpa)` blanks (NaN) `z`
wherever a point is below ground for pressure level `level_hpa`:

    psfc_hpa < min(level_hpa, cap_hpa)

`cap_hpa` (`BELOW_GROUND_CAP_HPA`, default 900 hPa) keeps the ocean
case above from being caught by this rule: without it, a deep low's
own surface pressure (which can legitimately fall well under 1000 or
925 hPa at its center) would mask the very feature this family exists
to find. With the cap, a point only counts as below ground for the
1000 and 925 hPa levels when the surface pressure drops under 900 hPa
-- true over the Greenland ice sheet (surface pressure roughly
700-800 hPa) and the Iceland highlands (roughly 850-900 hPa), not
true over an open-ocean low (surface pressure rarely below 900 hPa
even in a deep cyclone). 850 hPa is masked by the same 900 hPa
threshold; 700 hPa and above are masked only where the surface itself
is at or below that level's own pressure -- effectively never, except
over the Himalaya and Antarctica. See `BELOW_GROUND_CAP_HPA`'s own
docstring for more.

`surface_pressure_hpa(psfc)` coerces AWIPS's surface pressure field to
hPa, auto-detecting units: AWIPS normally hands pressure in Pa (sea
level is roughly 101325 Pa), but this checks the field's own finite
median rather than trusting a caller's label -- a median above 2000
can only be Pa (no real surface pressure is above 2000 hPa), so the
whole field is divided by 100; at or below 2000 it is assumed to
already be hPa.

`thermal_wind_grid` applies `mask_below_ground` to each of its
`z_levels` (matched to its own `pressures`) before `delta_z`, when
given an optional `psfc_hpa` (paired with `cap_hpa`); `psfc_hpa=None`
(the default) skips this entirely, so callers with no terrain to
mask -- including this module's own reference tests -- are
unaffected. `executeHartClass`/`executeIndexStd`/`executeBand3`/
`executeBand4`/`executeBand7` all take a `psfc` argument and a
`capHpa` constant (default `BELOW_GROUND_CAP_HPA`) and apply the mask
to every height argument, including `z1000` before it reaches
`closed_low_mask` (`closed_low_mask` itself is unchanged -- it is
simply handed an already-masked `z_low`). Because the sliding window
extrema (`window_extreme_2d`) and box sums (`window_sum_2d`) this
module uses throughout are already NaN-aware, a below-ground point's
neighbors just see one fewer valid sample in their own window -- no
extra plumbing was needed beyond masking the input before it reaches
them.

Parameter B and the joint class
---------------------------------

Hart's (2003) third CPS number, B (thermal asymmetry), is the
right-minus-left half-window mean of 900-600 hPa thickness across the
storm's own direction of motion, over the same 500 km circle VTL/VTU
use: `B = h * (mean_right - mean_left)`, `h = +1` in the Northern
Hemisphere, `-1` in the Southern, so that the frontal configuration
(warm/thick air on the equatorward flank of the track) always reads
positive. `B_THRESHOLD_M` (10 m) separates a symmetric, tropical-like
thickness field (below) from an asymmetric, frontal one (above), and
Evans and Hart (2003) define the extratropical transition **onset**
as the first time `B` exceeds this threshold, with **completion** at
the point VTL (the lower thermal wind) turns negative.

`parameter_b`'s storm-centered half-disk means (`cps/hart.py`) have no
pointwise analogue -- there is no "left half" or "right half" of a
single grid point. This module instead uses a **linear-gradient
approximation**: for a thickness field that varies smoothly across the
analysis window, the right-minus-left half-window mean difference
equals `(8*R/(3*pi))` times the window-mean gradient of thickness,
projected onto the right-hand normal of the storm's motion (`R` the
500 km analysis radius; see `b_geometry_km`, ~424.4 km for R=500).
This is exact for a perfectly linear thickness field (the square
window's mean gradient recovers the field's own gradient exactly, and
the half-plane-mean-vs-gradient constant is a fixed geometric fact of
a disk); it degrades for a genuinely nonlinear thickness structure
inside the window -- most notably a warm-seclusion tongue folding back
into one side of the circle -- which this approximation only captures
to first order (the gradient at/near the point), not the true
half-disk integral a real occlusion would produce. Read a gridded B
that looks marginal alongside the thickness overlay itself, not on
its own.

**Motion**: Hart's own B needs the storm's own track heading; a
gridded pointwise field has no storm to track, so the motion at each
grid point is taken from the **steering flow**, the mean of the wind
at 850, 700, 500, and 300 hPa (`steering`). This is a reasonable proxy
for translation speed and direction on most systems, but it is only a
proxy: a storm moving against its own steering flow (unusual, but not
unheard of at landfall or during a sharp recurvature), or a nearly
stationary system (`MIN_STEERING_MS`, 1 m/s, below which B is blanked
to NaN rather than divide by a near-zero speed and amplify noise),
gets an unreliable or missing B from this method even where Hart's own
track-based B would be well defined.

**Right-hand normal**: for steering `(u_s, v_s)`, the right-hand
normal used in the Northern Hemisphere is `(v_s, -u_s)/|V_s|` (e.g.
moving due north, `(u_s, v_s) = (0, +V)`, gives normal `(1, 0)`, i.e.
east -- the intuitive "right" when facing north). This is the same
left/right convention `cps.hart.parameter_b` uses via its cross
product (moving north, a point due east has `cross < 0`, defined
there as "right of track"). The hemisphere factor `h = sign(coriolis)`
(exact zero treated as `+1`, matching the Northern Hemisphere
convention) then multiplies the projected gradient so the "warm air on
the right in the NH, on the left in the SH" reading is positive in
both hemispheres, exactly mirroring `cps.hart.parameter_b`'s own
`hemisphere_sign`. `coriolis` may be handed in as a 2D pseudo-field (so
a grid straddling the equator gets the correct sign on each side) or a
scalar (assume one hemisphere everywhere).

**Layer scaling**: this module's thickness layer is 925-700 hPa (for
consistency with `LOWER_BAND`, the same standard-level lower
thermal-wind band), not Hart's 900-600 hPa. Because thickness scales
with the log-pressure depth of the layer, `B` is multiplied by
`HART_B_LAYER_SCALE = ln(900/600)/ln(925/700)` (~1.4553) by default,
so the result reads as a "900-600 equivalent" against Hart's own 10 m
threshold; a caller wanting the raw, unscaled 925-700 hPa value passes
`layerScale=1.0`.

This entire scheme -- the linear-gradient approximation, the
steering-flow motion proxy, and the layer scaling -- is orientation-
and sign-free by construction except for one place: computing the
thickness gradient itself (`gradient_2d`) takes a spatial derivative,
and like `CycloneCore.relative_vorticity`, that derivative's sign
depends on which way the grid's axes actually run. `ORIENTATION_MODE`
(module level, same 0..3 semantics as `CycloneCore.ORIENTATION_MODE`)
controls this; every other function in this module (`window_mean`,
`steering`, `parameter_b_grid`'s cross-product-style normal, `hart_class`)
takes no derivative and is orientation-free. Mode 1 is confirmed on
the OPC build, matching `CycloneCore.py`'s own default.

`hart_class` reports a single joint category (0-6) at every point
inside a closed low (`closed_low_mask` on 1000 hPa height, same as
`executeIndexStd`), NaN elsewhere, from all three Hart parameters at
once -- B, the lower thermal wind VTL, and the upper thermal wind VTU
-- rather than reporting VTL/VTU's Phase 2 category and B/VTL's
extratropical-transition stage as two separate categorical fields
(`HCPScat`/`HETstage`, retired). See `hart_class`'s own docstring for
the full table, the boundary convention it uses (warm/frontal on the
line, not cold/symmetric), and why a joint class carries information
neither field alone does. `hart_class` does not use history: it looks
only at the current frame's B, VTL, and VTU, so a storm that re-forms
a low-level warm core after transitioning (a warm seclusion) reads
back as a warm class (0/1) rather than staying "stuck" at a cold one
-- this is the warm-seclusion signature, read off the joint class
turning warm again, not a sign the transition never completed.

Relation to Hart's storm-centered diagrams
---------------------------------------------

Hart's own two diagrams -- the Phase 2 "cyclone phase" plot (VTL vs.
VTU) and the Phase 1 "asymmetry vs. thermal wind" plot (B vs. VTL) --
are each a *projection* of one underlying three-dimensional state, the
point `(B, VTL, VTU)` at a given time. Phase 2 shows that point's VTL/
VTU shadow and says nothing about B; Phase 1 shows its B/VTL shadow
and says nothing about VTU. Reading both diagrams side by side (as a
forecaster tracking a transitioning storm already does) is exactly an
attempt to reassemble the one 3D point from its two 2D shadows in the
forecaster's head. `hart_class` carries the information of both
projections at once, in a single number: it is a partition of that
same `(B, VTL, VTU)` space, so its code already reflects where the
point sits on *both* diagrams simultaneously. A single number at the
storm's low center is what a forecaster actually samples off a D2D
display -- one glance, not two diagrams held in mind together -- and
that is the point of collapsing the two families into one.

This file must import nothing from outside itself plus the standard
library and numpy: in AWIPS it runs inside CAVE's embedded Python
interpreter, which only has numpy and whatever else lives in the same
derivedParameters/functions directory on the classpath. It is written
so it can also be run standalone for a sanity check with no AWIPS
present at all:

    python3 D2D/derivedParameters/functions/cps_HartCPS.py
"""

from __future__ import annotations

import math
import warnings

import numpy as np

__all__ = [
    "RADIUS_KM",
    "MISSING_THRESHOLD",
    "MIN_RADIUS_KM",
    "DEFAULT_DEPTH_M",
    "DEFAULT_BLOB_RADIUS_KM",
    "DEFAULT_CENTER_TOL_M",
    "LOWER_BAND",
    "UPPER_BAND",
    "BELOW_GROUND_CAP_HPA",
    "ORIENTATION_MODE",
    "B_THRESHOLD_M",
    "HART_B_LAYER_SCALE",
    "MIN_STEERING_MS",
    "surface_pressure_hpa",
    "mask_below_ground",
    "running_extreme_1d",
    "window_extreme_2d",
    "window_sum_2d",
    "cells_per_row",
    "cells_y",
    "delta_z",
    "band_slope",
    "thermal_wind_grid",
    "closed_low_mask",
    "b_geometry_km",
    "gradient_2d",
    "window_mean",
    "steering",
    "parameter_b_grid",
    "hart_class",
    "executeBand3",
    "executeBand4",
    "executeBand7",
    "executeIndexStd",
    "executeB",
    "executeHartClass",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Half-width (km) of the max-minus-min analysis window, matching Hart's
#: (2003) 500 km analysis circle radius -- see the module docstring for why
#: this module uses a square window of this half-width instead of a circle
#: of this radius.
RADIUS_KM = 500.0

#: AWIPS may hand us -999999 (or similar) fill values for missing data.
#: Anything below this threshold, or non-finite (NaN/Inf), is treated as
#: missing. Same value and meaning as CycloneCore.py's constant of the same
#: name.
MISSING_THRESHOLD = -99990.0

#: Half-width (km) of the small window closed_low_mask() uses for its
#: "is this point (about) the minimum of its own neighborhood" candidate
#: test, and the inner edge of the annulus its ring-mean depth test is
#: measured over. Deliberately smaller than RING_RADIUS_KM/RADIUS_KM (Hart's
#: analysis window) -- this is "how big a box finds a low's own local
#: minimum", not the same thing as "how big a box the thermal wind or the
#: depth test integrates over".
MIN_RADIUS_KM = 300.0

#: Meters; closed_low_mask() requires the mean height of the annulus between
#: MIN_RADIUS_KM and its own ring_radius_km argument to exceed the point's
#: own height by at least this much before the point counts as being inside
#: a real closed low, not merely a local dip on a monotonic slope (see
#: closed_low_mask's docstring for why a plain "shallower than the far
#: field" window max-minus-min test is not enough by itself). closed_low_mask
#: is evaluated on 1000 hPa height, which is nearly a linear function of
#: MSLP (about 8 m per hPa), so this 40 m is about 5 hPa of MSLP.
DEFAULT_DEPTH_M = 40.0

#: Half-width (km) closed_low_mask() dilates its raw (candidate-and-deep)
#: point detections by, so the mask paints a blob of about this radius
#: around each detected low's center instead of a single pixel -- meant to
#: read as "the low is here", not to imply the low's own true physical
#: radius.
DEFAULT_BLOB_RADIUS_KM = 200.0

#: Meters; closed_low_mask() requires a point's own height to be within
#: this of the local minimum height found over MIN_RADIUS_KM before the
#: point is even a *candidate* center -- tight on purpose (much tighter
#: than a low's typical depth) so that a point out on a monotonic slope,
#: which is only ever approximately its own neighborhood's minimum in the
#: single direction the slope descends, does not qualify; the annulus
#: depth test (see DEFAULT_DEPTH_M) is what actually distinguishes a real
#: closed low from a slope, but both tests must pass together (see
#: closed_low_mask's docstring).
DEFAULT_CENTER_TOL_M = 5.0

#: Pressure levels (hPa) for the lower-tropospheric standard-level band --
#: see the module docstring's "Standard level bands" section for why these
#: three (not Hart's 900-600 hPa/50 hPa-spaced set) were chosen.
LOWER_BAND = (925.0, 850.0, 700.0)

#: Pressure levels (hPa) for the upper-tropospheric standard-level band.
UPPER_BAND = (500.0, 400.0, 300.0)

#: hPa; cap on the below-ground threshold `mask_below_ground` applies (a
#: point at level `level_hpa` is below ground when its own surface
#: pressure is under `min(level_hpa, BELOW_GROUND_CAP_HPA)`). Without the
#: cap, a deep low's own legitimately low surface pressure (e.g. 960 hPa
#: over open water) would be treated as terrain and blank out the very
#: feature this family looks for; with it, only genuinely high terrain --
#: the Greenland ice sheet (surface pressure roughly 700-800 hPa) and the
#: Iceland highlands (roughly 850-900 hPa) -- masks the 1000/925/850 hPa
#: levels, while an open-ocean low (rarely below ~900 hPa even at its
#: deepest) is left alone. 700 hPa and above are masked only where the
#: surface itself is at or below that level's own (uncapped) pressure --
#: effectively never, except over the Himalaya and Antarctica.
BELOW_GROUND_CAP_HPA = 900.0

#: Grid orientation mode used by `gradient_2d` (and, through it,
#: `parameter_b_grid`/`executeB`/`executeHartClass`) when no explicit `mode`
#: argument is given. Same 0..3 semantics as `CycloneCore.ORIENTATION_MODE`
#: -- see that constant's own comment for the full description of the four
#: conventions. Only `gradient_2d`'s thickness-gradient computation in this
#: module takes a spatial derivative; every other function here (`window_mean`,
#: `steering`, the rest of `parameter_b_grid`, `hart_class`) is orientation-free,
#: unlike `CycloneCore.py` where every VTL/VTU/CPScat/CPSidx call goes through
#: `relative_vorticity`. Mode 1 is confirmed correct on the OPC build (see
#: `CycloneCore.ORIENTATION_MODE`'s own comment and D2D/README.md's
#: "Orientation verification" procedure) -- it is not merely the untested
#: default here either.
ORIENTATION_MODE = 1

#: Meters; Evans and Hart (2003) extratropical transition **onset**
#: threshold for parameter B -- below this, the thickness field is read as
#: symmetric/tropical-like; at or above it, asymmetric/frontal. Hart's own
#: threshold, unchanged from `cps.hart.B_SYMMETRIC_THRESHOLD_M`.
B_THRESHOLD_M = 10.0

#: Dimensionless; multiplies parameter B to rescale it from this module's
#: 925-700 hPa thickness layer (`LOWER_BAND`'s own band, used for
#: consistency with VTL) to a "900-600 hPa equivalent" magnitude, so Hart's
#: 10 m `B_THRESHOLD_M` applies correctly -- see the module docstring's
#: "Parameter B and the joint class" section for the derivation
#: (`ln(900/600)/ln(925/700)`, about 1.4553). Pass `layerScale=1.0` to
#: `executeB`/`executeHartClass` for the raw, unscaled 925-700 hPa value.
HART_B_LAYER_SCALE = math.log(900.0 / 600.0) / math.log(925.0 / 700.0)

#: m/s; `parameter_b_grid` blanks (NaN) any point where the steering-flow
#: speed is below this -- a near-stationary or dead-calm-steering point has
#: no well defined "right of motion", and dividing by a near-zero speed to
#: normalize the motion vector would otherwise amplify noise into a huge,
#: meaningless B. See the module docstring's "Parameter B and ET stage"
#: section, "Motion", for the steering-flow proxy this guards.
MIN_STEERING_MS = 1.0


# ---------------------------------------------------------------------------
# Missing-data handling
# ---------------------------------------------------------------------------


def _missing_mask(*arrays: np.ndarray) -> np.ndarray:
    """True wherever any of `arrays` is non-finite or below
    `MISSING_THRESHOLD`, broadcast together. Identical in behavior to
    CycloneCore.py's function of the same name (duplicated here rather than
    imported, since this file must be self-contained -- see the module
    docstring).
    """
    mask = None
    for arr in arrays:
        a = np.asarray(arr, dtype=float)
        bad = ~np.isfinite(a) | (a < MISSING_THRESHOLD)
        mask = bad if mask is None else (mask | bad)
    if mask is None:
        return np.array(False)
    return mask


def _coerce_scalar(x) -> float:
    """Coerce a value that may arrive as a Python float, a 0-d numpy
    array, or a 1-element numpy array (as AWIPS ConstantField values do)
    into a plain float. Identical to CycloneCore.py's function of the same
    name.
    """
    return float(np.asarray(x).ravel()[0])


# ---------------------------------------------------------------------------
# Below-ground masking
# ---------------------------------------------------------------------------


def surface_pressure_hpa(psfc: np.ndarray) -> np.ndarray:
    """Coerce AWIPS's surface pressure field `psfc` to hPa, as a float
    array the same shape as `psfc`, auto-detecting Pa vs hPa and
    treating missing input (see `_missing_mask`) as NaN.

    AWIPS hands pressure fields in Pa (sea level is roughly 101325 Pa),
    but this does not trust a caller's unit label -- it looks at the
    field's own finite median: a median above 2000 can only be Pa (no
    real surface pressure is above 2000 hPa), so the whole field is
    divided by 100; a median at or below 2000 is assumed to already be
    hPa. The decision is made once for the whole array, not per
    element, since a real pressure field does not mix units within
    itself. A field with no finite values at all (an undefined median)
    is returned unconverted -- it is all-NaN either way.
    """
    p = np.asarray(psfc, dtype=float)
    bad = _missing_mask(p)
    p = np.where(bad, np.nan, p)
    finite = p[np.isfinite(p)]
    if finite.size == 0:
        return p
    median = float(np.median(finite))
    if median > 2000.0:
        p = p / 100.0
    return p


def mask_below_ground(
    z: np.ndarray,
    psfc_hpa: np.ndarray,
    level_hpa: float,
    cap_hpa: float = BELOW_GROUND_CAP_HPA,
) -> np.ndarray:
    """Return `z` with NaN wherever the grid point is below ground for
    pressure level `level_hpa`: `psfc_hpa < min(level_hpa, cap_hpa)`, or
    `psfc_hpa` itself is not finite there. See `BELOW_GROUND_CAP_HPA`
    and the module docstring's "Below-ground masking" section for why
    the threshold is capped rather than a plain `psfc_hpa < level_hpa`,
    and `surface_pressure_hpa` for getting `psfc_hpa` from a raw AWIPS
    surface pressure field (which may be in Pa).

    `z` and `psfc_hpa` must be broadcastable to the same shape (in
    practice, the same grid). `level_hpa`/`cap_hpa` are plain scalars,
    not AWIPS `<ConstantField>` values -- callers that receive
    `<ConstantField>` values coerce them first (see `_coerce_scalar`).
    """
    z_arr = np.asarray(z, dtype=float)
    p_arr = np.asarray(psfc_hpa, dtype=float)
    threshold = min(float(level_hpa), float(cap_hpa))
    with np.errstate(invalid="ignore"):
        below = ~np.isfinite(p_arr) | (p_arr < threshold)
    return np.where(below, np.nan, z_arr)


# ---------------------------------------------------------------------------
# Sliding-window max/min (doubling / sparse-table trick)
# ---------------------------------------------------------------------------


def running_extreme_1d(a: np.ndarray, half_width: int, axis: int, kind: str) -> np.ndarray:
    """Sliding max or min of `a` along `axis`, window length
    `2*half_width+1`, NaN-ignoring (via `np.fmax`/`np.fmin`), edges
    clipped -- the window shrinks rather than wraps or reflects at the
    domain boundary.

    `kind` is `"max"` or `"min"`. `half_width == 0` returns an unchanged
    copy of `a` (a window of length 1 is just the point itself).

    Implementation: pad `a` along `axis` with `half_width` sentinel values
    on each side (`-inf` for `"max"`, `+inf` for `"min"`) so that a
    *fixed*-length sliding window of length `L = 2*half_width+1` over the
    padded array reproduces the edge-shrinking behavior exactly (a window
    that would have run off the real edge instead sees sentinel values,
    which `fmax`/`fmin` treat the same as "no real data there" -- see
    below). The fixed-length sliding extreme is then computed with the
    doubling trick (a disjoint sparse table): build `level` arrays for
    window sizes 1, 2, 4, 8, ... (each built from the previous one with a
    single vectorized `fmax`/`fmin` combine, in O(N) per doubling step)
    until the largest power of two `size <= L` is reached, then answer
    every output position with one more combine of two overlapping
    `size`-length windows that together cover the full length-`L` window.
    Total cost is O(N log L) numpy operations (not O(N) python-level
    iterations over each of the N output positions), independent of the
    window length `w = 2*half_width+1` beyond the log factor.

    `np.fmax`/`np.fmin` ignore NaN when the other operand is finite (that
    is the NaN-ignoring behavior asked for), but if *every* value seen by
    a window -- real data and sentinel padding alike -- is NaN or the
    sentinel value, the combine collapses to the sentinel itself
    (`-inf`/`+inf`). Such positions are converted to NaN before returning
    (`"treating all-inf as NaN"`): a window that is all sentinel only
    happens past the domain edge, and a window that is all-NaN real data
    has no meaningful extreme either way.

    Works for any axis of a 2D (or higher-dimensional) array: the working
    axis is moved to position 0 internally and moved back before
    returning, so the other axes are carried along untouched.
    """
    if kind not in ("max", "min"):
        raise ValueError(f"kind must be 'max' or 'min'; got {kind!r}")
    a = np.asarray(a, dtype=float)
    half_width = int(half_width)
    if half_width < 0:
        raise ValueError("half_width must be >= 0")
    if half_width == 0:
        return a.copy()

    combine = np.fmax if kind == "max" else np.fmin
    sentinel = -np.inf if kind == "max" else np.inf

    a_moved = np.moveaxis(a, axis, 0)
    n = a_moved.shape[0]
    window_len = 2 * half_width + 1

    pad_width = [(half_width, half_width)] + [(0, 0)] * (a_moved.ndim - 1)
    padded = np.pad(a_moved, pad_width, mode="constant", constant_values=sentinel)
    total = padded.shape[0]  # == n + 2*half_width

    # Doubling table: `level` holds window-size-`size` extremes, valid at
    # positions [0, total - size]; start at size 1 (the padded array
    # itself), then repeatedly double until the largest power of two
    # <= window_len is reached.
    level = padded
    size = 1
    while size * 2 <= window_len:
        new_size = size * 2
        keep = total - new_size + 1
        level = combine(level[:keep], level[size : size + keep])
        size = new_size

    # Two overlapping size-length windows starting at s and at
    # s + window_len - size together cover the full length-window_len
    # window [s, s + window_len); valid s ranges over [0, n-1] (the padded
    # array has exactly enough headroom, by construction of the padding).
    starts = np.arange(n)
    left = level[starts]
    right = level[starts + window_len - size]
    result = combine(left, right)

    if kind == "max":
        result = np.where(np.isneginf(result), np.nan, result)
    else:
        result = np.where(np.isposinf(result), np.nan, result)

    return np.moveaxis(result, 0, axis)


def window_extreme_2d(
    field: np.ndarray,
    half_x_cells_per_row: np.ndarray,
    half_y_cells: int,
    kind: str,
) -> np.ndarray:
    """2D sliding-window max or min, with a per-row half-width along x.

    On a lat/lon grid the number of grid cells spanned by a fixed
    distance (e.g. 500 km) along the x (longitude) direction grows with
    latitude, since the physical spacing `dx` shrinks toward the poles
    (`dx ~ cos(lat)`). `half_x_cells_per_row` is therefore a 1D integer
    array, one entry per row (per axis-0 index), giving that row's
    half-width in grid cells for the x-direction window; `half_y_cells`
    is a single scalar half-width for the y-direction window, since the
    y (latitude) spacing does not vary across a regular lat/lon grid.

    On a non-lat/lon (projected) grid, `dx` can vary in both directions
    at once (not just row-to-row), which this function cannot represent
    exactly with a single half-width per row: the caller (`cells_per_row`)
    reduces each row to its own `nanmean` of `dx`, an approximation that
    is exact on a regular lat/lon grid and only approximate elsewhere.

    Rows are grouped by their (post-clamp) half-width value and processed
    together: for each distinct half-width, the matching rows are pulled
    out with fancy indexing, `running_extreme_1d` is run once along axis
    1 for that whole group, and the result is written back into those
    rows -- so the number of `running_extreme_1d` calls along axis 1 is
    the number of *distinct* half-width values, not the number of rows.
    A second `running_extreme_1d` call along axis 0 (with the single
    scalar `half_y_cells`) then does the y-direction pass over the whole
    array at once.

    Any half-width -- x or y -- is clamped to at most `(n-1)//2` for its
    own axis (a window half-width any larger cannot mean anything
    different from using the whole axis).
    """
    if kind not in ("max", "min"):
        raise ValueError(f"kind must be 'max' or 'min'; got {kind!r}")
    field = np.asarray(field, dtype=float)
    if field.ndim != 2:
        raise ValueError("field must be 2D")
    ny, nx = field.shape

    half_x = np.asarray(half_x_cells_per_row).astype(int)
    if half_x.shape != (ny,):
        raise ValueError(f"half_x_cells_per_row must have shape ({ny},); got {half_x.shape}")
    max_half_x = max((nx - 1) // 2, 0)
    half_x = np.clip(half_x, 0, max_half_x)

    max_half_y = max((ny - 1) // 2, 0)
    half_y = int(np.clip(int(half_y_cells), 0, max_half_y))

    out_x = np.empty_like(field)
    for hw in np.unique(half_x):
        rows = np.nonzero(half_x == hw)[0]
        out_x[rows, :] = running_extreme_1d(field[rows, :], int(hw), axis=1, kind=kind)

    return running_extreme_1d(out_x, half_y, axis=0, kind=kind)


def _box_sum_1d(values: np.ndarray, counts: np.ndarray, half_width: int, axis: int):
    """Sliding box sum of `values` and, in the same pass, of `counts`,
    length `2*half_width+1` along `axis`, edges clipped (the window
    shrinks at the domain boundary, exactly like `running_extreme_1d`).
    `values` must already have missing/NaN entries replaced by 0 and
    `counts` must be the matching 0/1 validity mask -- see `window_sum_2d`,
    the only caller. `half_width == 0` returns both inputs unchanged.

    Implemented with a cumulative sum along `axis` (a leading zero
    prepended so `windowsum[i] = cumsum[hi] - cumsum[lo]`, `lo`/`hi`
    clipped to `[0, n]`), the same O(N) trick `CycloneCore.box_smooth`
    uses -- cost does not depend on `half_width`.
    """
    if half_width == 0:
        return values.copy(), counts.copy()

    n = values.shape[axis]
    zero_shape = list(values.shape)
    zero_shape[axis] = 1
    zeros = np.zeros(zero_shape, dtype=values.dtype)

    cs_v = np.concatenate([zeros, np.cumsum(values, axis=axis)], axis=axis)
    cs_c = np.concatenate([zeros, np.cumsum(counts, axis=axis)], axis=axis)

    idx = np.arange(n)
    lo = np.clip(idx - half_width, 0, n)
    hi = np.clip(idx + half_width + 1, 0, n)

    sum_v = np.take(cs_v, hi, axis=axis) - np.take(cs_v, lo, axis=axis)
    sum_c = np.take(cs_c, hi, axis=axis) - np.take(cs_c, lo, axis=axis)
    return sum_v, sum_c


def window_sum_2d(
    field: np.ndarray,
    half_x_cells_per_row: np.ndarray,
    half_y_cells: int,
):
    """2D sliding-window sum and valid-point count, with the same
    per-row half-width along x (and clamping) that `window_extreme_2d`
    uses -- the box-sum analogue needed for `closed_low_mask`'s ring-mean
    depth test (a box mean over an annulus is a difference of two box
    sums divided by a difference of two box counts, computed by calling
    this function twice with different radii and letting the caller take
    that difference -- see `closed_low_mask`).

    NaN (or otherwise missing, per whatever the caller has already done
    to `field`) entries are excluded from both the sum and the count,
    the same way `CycloneCore.box_smooth` excludes them: they contribute
    0 to the sum and 0 to the count, so a window's mean (`sum / count`,
    left to the caller) is the mean of only the valid points in it, and a
    window that is entirely missing comes back with `count == 0` (the
    caller must guard the division).

    Rows are grouped by their (post-clamp) half-width value exactly as
    `window_extreme_2d` groups them (same fancy-indexing pass, same
    number of `_box_sum_1d` calls along axis 1 as there are distinct
    half-width values), then a single `_box_sum_1d` call along axis 0
    with the scalar `half_y_cells` finishes the box sum/count over the
    full 2D window. Edges are clipped, like `window_extreme_2d`.

    Returns `(sum_field, count)`, two arrays the same shape as `field`.
    """
    field = np.asarray(field, dtype=float)
    if field.ndim != 2:
        raise ValueError("field must be 2D")
    ny, nx = field.shape

    half_x = np.asarray(half_x_cells_per_row).astype(int)
    if half_x.shape != (ny,):
        raise ValueError(f"half_x_cells_per_row must have shape ({ny},); got {half_x.shape}")
    max_half_x = max((nx - 1) // 2, 0)
    half_x = np.clip(half_x, 0, max_half_x)

    max_half_y = max((ny - 1) // 2, 0)
    half_y = int(np.clip(int(half_y_cells), 0, max_half_y))

    valid = np.isfinite(field)
    values = np.where(valid, field, 0.0)
    counts = valid.astype(float)

    sum_x = np.empty_like(field)
    cnt_x = np.empty_like(field)
    for hw in np.unique(half_x):
        rows = np.nonzero(half_x == hw)[0]
        sum_x[rows, :], cnt_x[rows, :] = _box_sum_1d(values[rows, :], counts[rows, :], int(hw), axis=1)

    return _box_sum_1d(sum_x, cnt_x, half_y, axis=0)


# ---------------------------------------------------------------------------
# Distance-to-cells conversion
# ---------------------------------------------------------------------------


def cells_per_row(radius_km: float, dx: np.ndarray, ny: int, nx: int) -> np.ndarray:
    """Per-row half-width (grid cells) for a `radius_km` window along x.

    `dx` (meters) may be a scalar (every row gets the same half-width) or
    a 2D array of shape `(ny, nx)` (AWIPS supplies `dx` as a pseudo-field
    that varies across the grid on most map projections); each row's
    half-width uses that row's own `nanmean` of `dx`. Result is
    `round(radius_km * 1000 / row_dx)`, floored at a minimum of 1 cell (a
    window of half-width 0 would just be the point itself, never useful
    for a max-minus-min diagnostic).
    """
    dx_arr = np.asarray(dx, dtype=float)
    if dx_arr.ndim == 0:
        row_dx = np.full(ny, float(dx_arr))
    elif dx_arr.ndim == 2:
        if dx_arr.shape != (ny, nx):
            raise ValueError(f"dx must have shape ({ny}, {nx}); got {dx_arr.shape}")
        with np.errstate(invalid="ignore"):
            row_dx = np.nanmean(dx_arr, axis=1)
    else:
        raise ValueError("dx must be a scalar or a 2D array")

    radius_m = float(radius_km) * 1000.0
    cells = np.empty(ny, dtype=int)
    for i in range(ny):
        spacing = row_dx[i]
        if not np.isfinite(spacing) or spacing <= 0:
            cells[i] = 1
        else:
            cells[i] = max(1, int(round(radius_m / spacing)))
    return cells


def cells_y(radius_km: float, dy: np.ndarray) -> int:
    """Scalar half-width (grid cells) for a `radius_km` window along y.

    `dy` (meters) may be a scalar or an array of any shape; the whole
    array's `nanmean` is used (the y spacing does not vary across a
    regular lat/lon grid, so a single representative value is
    appropriate -- unlike `cells_per_row`'s per-row treatment of `dx`).
    Result is `round(radius_km * 1000 / mean_dy)`, floored at a minimum of
    1 cell.
    """
    dy_arr = np.asarray(dy, dtype=float)
    with np.errstate(invalid="ignore"):
        spacing = np.nanmean(dy_arr)
    if not np.isfinite(spacing) or spacing <= 0:
        return 1
    return max(1, int(round(float(radius_km) * 1000.0 / float(spacing))))


# ---------------------------------------------------------------------------
# dZ and the band slope
# ---------------------------------------------------------------------------


def delta_z(z: np.ndarray, dx: np.ndarray, dy: np.ndarray, radius_km: float) -> np.ndarray:
    """`window_max(z) - window_min(z)`, half-width `radius_km`, at every
    grid point -- the pointwise analogue of Hart's per-level `dZ`.

    Missing input (see `_missing_mask`) is replaced with NaN before
    computing the window extremes (so a bad point cannot masquerade as a
    real height and cannot contaminate a window average through
    `cells_per_row`'s `nanmean`, since `dx`/`dy` are the grid-spacing
    pseudo-fields, not `z`, and are not run through this same missing
    check -- only `z` is). The result is explicitly forced to NaN at any
    point where `z` itself was missing, even if that point's window
    happened to contain enough valid neighbors to compute *something*:
    `dZ` at a missing point is not meaningful.
    """
    z_arr = np.asarray(z, dtype=float)
    ny, nx = z_arr.shape
    bad = _missing_mask(z_arr)
    z_clean = np.where(bad, np.nan, z_arr)

    half_x = cells_per_row(radius_km, dx, ny, nx)
    half_y = cells_y(radius_km, dy)

    z_max = window_extreme_2d(z_clean, half_x, half_y, "max")
    z_min = window_extreme_2d(z_clean, half_x, half_y, "min")

    dz = z_max - z_min
    return np.where(bad, np.nan, dz)


def band_slope(dz_list, pressures) -> np.ndarray:
    """Least-squares slope of `dz` against `ln(pressure)`, elementwise
    over the grid, using the closed-form formula

        slope = sum((x - xbar) * (y - ybar)) / sum((x - xbar)**2)

    with `x = ln(p)` (no `np.polyfit` call in a loop over grid points --
    this is vectorized over the whole `dz` stack at once).

    `dz_list` is a sequence of 2D arrays (one per level, all the same
    shape), `pressures` the matching sequence of pressures (hPa, any
    order -- matched to `dz_list` by position). At least 2 levels are
    required. The result is NaN at any grid point where *any* level's
    `dz` is NaN there (a partial band average would silently bias the
    slope toward whichever levels happened to be valid).
    """
    if len(dz_list) != len(pressures):
        raise ValueError("dz_list and pressures must have the same length")
    if len(dz_list) < 2:
        raise ValueError("band_slope needs at least 2 levels")

    dz_stack = np.stack([np.asarray(d, dtype=float) for d in dz_list], axis=0)
    x = np.log(np.asarray(pressures, dtype=float))
    xbar = float(np.mean(x))
    dx = x - xbar
    denom = float(np.sum(dx ** 2))

    any_nan = np.any(~np.isfinite(dz_stack), axis=0)

    ybar = np.mean(dz_stack, axis=0)
    numer = np.sum(dx[:, np.newaxis, np.newaxis] * (dz_stack - ybar[np.newaxis, :, :]), axis=0)

    with np.errstate(invalid="ignore", divide="ignore"):
        slope = numer / denom
    return np.where(any_nan, np.nan, slope)


def thermal_wind_grid(
    z_levels,
    pressures,
    dx,
    dy,
    radius_km: float = RADIUS_KM,
    psfc_hpa: np.ndarray = None,
    cap_hpa: float = BELOW_GROUND_CAP_HPA,
) -> np.ndarray:
    """`band_slope` of `delta_z` at every level in `z_levels` -- the full
    pointwise Hart thermal-wind computation for one band. `z_levels` is a
    sequence of 2D height arrays (meters), `pressures` the matching
    sequence of pressures (hPa). Returns a float64 grid, same shape as
    each entry of `z_levels`.

    If `psfc_hpa` (surface pressure, hPa -- see `surface_pressure_hpa`)
    is given, each level in `z_levels` is first run through
    `mask_below_ground` against its own matching entry in `pressures`
    and `cap_hpa`, before `delta_z` -- see the module docstring's
    "Below-ground masking" section. `psfc_hpa=None` (the default) skips
    this entirely -- the pre-below-ground-masking behavior, for callers
    with no terrain to mask.
    """
    if psfc_hpa is not None:
        z_levels = [mask_below_ground(z, psfc_hpa, p, cap_hpa) for z, p in zip(z_levels, pressures)]
    dz_list = [delta_z(z, dx, dy, radius_km) for z in z_levels]
    return band_slope(dz_list, pressures).astype(np.float64)


# ---------------------------------------------------------------------------
# Closed-low mask
# ---------------------------------------------------------------------------


def closed_low_mask(
    z_low: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    min_radius_km: float = MIN_RADIUS_KM,
    ring_radius_km: float = RADIUS_KM,
    depth_m: float = DEFAULT_DEPTH_M,
    blob_radius_km: float = DEFAULT_BLOB_RADIUS_KM,
    center_tol_m: float = DEFAULT_CENTER_TOL_M,
) -> np.ndarray:
    """Boolean mask: True within `blob_radius_km` of a real closed low's
    center in `z_low` (typically 1000 hPa height, passed by
    `executeHartClass`/`executeIndexStd` as `z1000`). 1000 hPa height is
    used rather than a level from `LOWER_BAND`/`UPPER_BAND` because it is
    nearly a linear function of MSLP (about 8 m per hPa), so the closed
    low this mask finds is the same closed low a forecaster already sees
    drawn on the MSLP contours -- `depth_m`'s default of 40 m is
    therefore about 5 hPa of MSLP.

    1000 hPa is below the ground surface over major terrain, and below
    sea level itself inside a sufficiently deep low, so in both cases
    the model is extrapolating rather than reporting a directly
    analyzed height there. Over the open ocean -- most of this family's
    intended use -- that extrapolation is harmless. Over ice sheets and
    high mountains it is not: callers should pre-mask `z_low` with
    `mask_below_ground` (as `executeHartClass`/`executeIndexStd` do)
    before calling this function, rather than relying on
    `closed_low_mask` itself to know about terrain -- it takes `z_low`
    exactly as given and has no notion of surface pressure of its own.

    A plain "is this point close to the local minimum of a box that also
    has a big max-minus-min" test (an earlier version of this function)
    turns out to accept far more than closed lows: on a *uniform slope*
    (no low at all -- e.g. a steady 40-60 m per 1000 km height gradient
    across a front) every point is, to within a few meters, already the
    minimum of its own neighborhood in the single direction the slope
    descends, and the same window's max-minus-min is large simply because
    the slope has covered a lot of height by the time it reaches the far
    edge of a 500 km box -- so both tests passed *everywhere*, not just at
    an actual low. This function instead uses two tests that a monotonic
    slope cannot satisfy simultaneously:

    1. **Candidate test**: `z_low - window_min(z_low, min_radius_km) <=
       center_tol_m` -- the point is (within a tight tolerance) the
       minimum of its own `min_radius_km` neighborhood. `center_tol_m`
       is deliberately tight (much tighter than a real low's depth) so
       this alone is a weak filter, not a claim of "this is a low".
    2. **Depth test**: `ring_mean - z_low >= depth_m`, where `ring_mean`
       is the mean height of the *annulus* between `min_radius_km` and
       `ring_radius_km` around the point (computed from two box sums via
       `window_sum_2d`: `(sum_outer - sum_inner) / (count_outer -
       count_inner)`). On a closed low, the annulus sits on the
       surrounding higher terrain/background and is higher than the
       center by roughly the low's depth. On a uniform slope, the
       annulus is centered on the same point as the candidate itself, so
       its mean height equals the point's own height to first order (a
       symmetric ring around a point on a linear slope averages back to
       that point's own value) -- the depth comes back ~0 and the test
       correctly rejects it.

    Points passing both tests are `raw` detections (typically a single
    pixel, or a couple, right at each low's true minimum); the returned
    mask is `raw` dilated by `window_extreme_2d(..., kind="max")` over a
    `blob_radius_km` half-width, so each detected low paints a blob of
    about that radius on the map instead of a single point (this radius
    is about "how big to paint the low", unrelated to the low's own true
    physical size).

    NaN-safe throughout: any comparison against a NaN intermediate value
    is False in numpy already, but missing input (see `_missing_mask`) is
    also explicitly excluded before dilation, so a bad `z_low` value can
    never masquerade as "yes, this is a low center."
    """
    z_arr = np.asarray(z_low, dtype=float)
    ny, nx = z_arr.shape
    bad = _missing_mask(z_arr)
    z_clean = np.where(bad, np.nan, z_arr)

    half_x_min = cells_per_row(min_radius_km, dx, ny, nx)
    half_y_min = cells_y(min_radius_km, dy)
    local_min = window_extreme_2d(z_clean, half_x_min, half_y_min, "min")

    with np.errstate(invalid="ignore"):
        candidate = (z_clean - local_min) <= center_tol_m

    half_x_ring = cells_per_row(ring_radius_km, dx, ny, nx)
    half_y_ring = cells_y(ring_radius_km, dy)
    sum_outer, count_outer = window_sum_2d(z_clean, half_x_ring, half_y_ring)
    sum_inner, count_inner = window_sum_2d(z_clean, half_x_min, half_y_min)

    ring_sum = sum_outer - sum_inner
    ring_count = count_outer - count_inner
    with np.errstate(invalid="ignore", divide="ignore"):
        ring_mean = np.where(ring_count > 0, ring_sum / ring_count, np.nan)
        depth_ok = (ring_mean - z_clean) >= depth_m

    valid = ~bad & np.isfinite(local_min) & np.isfinite(ring_mean)
    raw = (candidate & depth_ok & valid).astype(float)

    half_x_blob = cells_per_row(blob_radius_km, dx, ny, nx)
    half_y_blob = cells_y(blob_radius_km, dy)
    dilated = window_extreme_2d(raw, half_x_blob, half_y_blob, "max")
    return dilated > 0.5


# ---------------------------------------------------------------------------
# Parameter B (thermal asymmetry) and ET stage
# ---------------------------------------------------------------------------


def b_geometry_km(radius_km: float) -> float:
    """`8*radius_km/(3*pi)` -- the geometric constant that converts a
    window-mean thickness gradient into an approximation of Hart's
    right-minus-left half-window mean difference (see the module
    docstring's "Parameter B and ET stage" section). Computed from
    `radius_km` at call time rather than baked into a module constant, so
    a caller using a non-default `radiusKm` gets the matching constant.
    For Hart's own 500 km radius this is about 424.4 km.
    """
    return 8.0 * float(radius_km) / (3.0 * math.pi)


def gradient_2d(
    field: np.ndarray, dx: np.ndarray, dy: np.ndarray, mode: int | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """`(d(field)/dx, d(field)/dy)` via centered differences (`np.gradient`),
    the x-derivative along axis 1 divided by `dx`, the y-derivative along
    axis 0 divided by `dy`. `dx`/`dy` (meters) may each be a scalar or a 2D
    array the same shape as `field`.

    `mode` selects the grid-orientation convention `field`/`dx`/`dy` are
    actually laid out in, exactly the same four conventions
    `CycloneCore.relative_vorticity` uses (see `ORIENTATION_MODE`, module
    level, for the full description); `None` (the default) means "use
    `ORIENTATION_MODE`", read fresh from the module on every call so a
    monkeypatch takes effect without touching this function. Modes 2 and 3
    (transposed axes) transpose `field`/`dx`/`dy` on the way in and both
    result arrays back on the way out, exactly as `relative_vorticity`
    does for `zeta` -- `d(field)/dx` and `d(field)/dy` are themselves
    scalar fields (not vector components tied to an axis), so transposing
    them back needs no swap between the two, only a reshape. Modes 1 and 3
    negate the y-derivative (axis 0 increasing southward instead of
    northward), also exactly as `relative_vorticity` does.

    Missing values (see `_missing_mask`) in `field`, `dx`, or `dy` are set
    to NaN before differencing and any resulting NaN (including the
    immediate-neighbor contamination `np.gradient`'s centered-difference
    stencil causes -- unavoidable, same caveat as `relative_vorticity`) is
    left as NaN in the output.

    Raises `ValueError` if `mode` (after defaulting) is not one of 0, 1,
    2, 3.
    """
    field = np.asarray(field, dtype=float)
    dx = np.asarray(dx, dtype=float)
    dy = np.asarray(dy, dtype=float)

    if mode is None:
        mode = ORIENTATION_MODE
    mode = int(mode)
    if mode not in (0, 1, 2, 3):
        raise ValueError(f"mode must be 0, 1, 2, or 3; got {mode!r}")

    transposed = mode in (2, 3)
    if transposed:
        field = field.T
        if dx.ndim == 2:
            dx = dx.T
        if dy.ndim == 2:
            dy = dy.T

    bad = _missing_mask(field, dx, dy)
    bad = np.broadcast_to(bad, field.shape)
    field_clean = np.where(bad, np.nan, field)

    d_dx = np.gradient(field_clean, axis=1) / dx
    d_dy = np.gradient(field_clean, axis=0) / dy

    if mode in (1, 3):
        d_dy = -d_dy

    d_dx = np.where(bad, np.nan, d_dx)
    d_dy = np.where(bad, np.nan, d_dy)

    if transposed:
        d_dx = d_dx.T
        d_dy = d_dy.T

    return d_dx, d_dy


def window_mean(field: np.ndarray, dx: np.ndarray, dy: np.ndarray, radius_km: float) -> np.ndarray:
    """NaN-aware box mean of `field`, half-width `radius_km`, at every
    grid point -- `window_sum_2d`'s sum divided by its count, using the
    same per-row `dx`/scalar `dy` half-width conversion (`cells_per_row`,
    `cells_y`) `delta_z`/`closed_low_mask` use. NaN where the window's
    valid-point count is 0 (every point in it was missing).
    """
    field = np.asarray(field, dtype=float)
    ny, nx = field.shape
    half_x = cells_per_row(radius_km, dx, ny, nx)
    half_y = cells_y(radius_km, dy)
    total, count = window_sum_2d(field, half_x, half_y)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / count, np.nan)
    return mean


def steering(u_levels, v_levels) -> tuple[np.ndarray, np.ndarray]:
    """`(u_s, v_s)`: the elementwise (NaN-aware) mean of a list of u
    arrays and a list of v arrays, the steering-flow proxy for a storm's
    motion at every grid point (see the module docstring's "Parameter B
    and ET stage" section, "Motion") -- typically the 850/700/500/300 hPa
    wind components, one entry per level, all the same shape.

    Missing values (see `_missing_mask`) in any individual level are set
    to NaN before averaging, so a bad level does not masquerade as a real
    wind value; the average itself is `np.nanmean` over the stacked
    levels (axis 0), so a point with at least one valid level still gets
    an averaged value, and only a point missing at *every* level comes
    back NaN.
    """
    u_arrays = [np.asarray(u, dtype=float) for u in u_levels]
    v_arrays = [np.asarray(v, dtype=float) for v in v_levels]

    u_clean = [np.where(_missing_mask(u), np.nan, u) for u in u_arrays]
    v_clean = [np.where(_missing_mask(v), np.nan, v) for v in v_arrays]

    u_stack = np.stack(u_clean, axis=0)
    v_stack = np.stack(v_clean, axis=0)

    # np.nanmean warns ("Mean of empty slice") at a point missing in
    # every level -- that point is supposed to come back NaN quietly,
    # not print a warning every call.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        u_s = np.nanmean(u_stack, axis=0)
        v_s = np.nanmean(v_stack, axis=0)
    return u_s, v_s


def parameter_b_grid(
    thickness: np.ndarray,
    u_s: np.ndarray,
    v_s: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    hemisphere,
    radius_km: float,
    layer_scale: float,
    min_speed: float = MIN_STEERING_MS,
) -> np.ndarray:
    """Gridded approximation of Hart's parameter B at every grid point --
    see the module docstring's "Parameter B and ET stage" section for the
    full derivation.

    `thickness` is a layer thickness field (meters, e.g. 700 hPa height
    minus 925 hPa height). Its gradient (`gradient_2d`) is computed once,
    then each component is box-averaged (`window_mean`) over a
    `radius_km` window -- computing the gradient first and then
    window-meaning each component, rather than differencing a
    window-meaned thickness, so a locally noisy `thickness` is smoothed
    the same way `dZ`'s own window extrema effectively are elsewhere in
    this module.

    `u_s`/`v_s` (m/s) are the storm's motion at each point -- typically
    `steering`'s output. `speed = hypot(u_s, v_s)`; the right-hand normal
    of motion (Northern Hemisphere convention) is `(v_s, -u_s)/speed`.
    `hemisphere` may be a scalar or a 2D array (e.g. a coriolis
    pseudo-field): `np.sign(hemisphere)` gives the hemisphere factor `h`
    (exact zero is treated as `+1`, the Northern Hemisphere default).

        B = h * b_geometry_km(radius_km)*1000 * (n_right . grad(thickness)) * layer_scale

    NaN wherever `speed < min_speed` (see `MIN_STEERING_MS`) or either
    window-meaned gradient component is not finite.
    """
    thickness = np.asarray(thickness, dtype=float)
    thickness_clean = np.where(_missing_mask(thickness), np.nan, thickness)

    gx_point, gy_point = gradient_2d(thickness_clean, dx, dy)
    gx = window_mean(gx_point, dx, dy, radius_km)
    gy = window_mean(gy_point, dx, dy, radius_km)

    u_s_arr = np.asarray(u_s, dtype=float)
    v_s_arr = np.asarray(v_s, dtype=float)
    bad_uv = _missing_mask(u_s_arr, v_s_arr)
    u_s_clean = np.where(bad_uv, np.nan, u_s_arr)
    v_s_clean = np.where(bad_uv, np.nan, v_s_arr)

    speed = np.hypot(u_s_clean, v_s_clean)
    with np.errstate(invalid="ignore", divide="ignore"):
        n_right_x = v_s_clean / speed
        n_right_y = -u_s_clean / speed

    hemi = np.asarray(hemisphere, dtype=float)
    h_sign = np.sign(hemi)
    h_sign = np.where(h_sign == 0, 1.0, h_sign)

    geom_m = b_geometry_km(radius_km) * 1000.0
    projected = n_right_x * gx + n_right_y * gy
    b = h_sign * geom_m * projected * float(layer_scale)

    invalid = (
        ~np.isfinite(speed)
        | (speed < float(min_speed))
        | ~np.isfinite(gx)
        | ~np.isfinite(gy)
    )
    return np.where(invalid, np.nan, b)


def hart_class(
    B: np.ndarray,
    vtl: np.ndarray,
    vtu: np.ndarray,
    mask: np.ndarray,
    b_threshold: float = B_THRESHOLD_M,
) -> np.ndarray:
    """The joint Hart CPS class (0-6) at every grid point, from all three
    Hart (2003) parameters at once -- B (thermal asymmetry), VTL (lower
    thermal wind), and VTU (upper thermal wind) -- replacing the two,
    separately-categorical `HCPScat` (Phase 2 class)/`HETstage`
    (extratropical transition stage) fields this package used to publish
    (both retired; see the module docstring's "Relation to Hart's
    storm-centered diagrams" section for why one joint class is a strict
    improvement over reading two separate categorical fields side by
    side).

    NaN outside `mask` (typically `closed_low_mask` on 1000 hPa height)
    or wherever any of `B`, `vtl`, `vtu` is not finite -- `B` is NaN
    whenever the steering-flow speed is below `MIN_STEERING_MS` (a
    near-stationary or dead-calm-steering point; see `parameter_b_grid`),
    which is rare but not impossible for a slow-moving or recurving
    system, and this is documented here rather than silently treated as
    some default category.

    Otherwise, one of:

        Code  Name                          B        lower VT   upper VT
        0     symmetric deep warm core      <= thr   >= 0       >= 0
        1     symmetric shallow warm core   <= thr   >= 0       <  0
        2     frontal deep warm core        >  thr   >= 0       >= 0
        3     frontal shallow warm core     >  thr   >= 0       <  0
        4     frontal cold core             >  thr   <  0        (*)
        5     symmetric cold core           <= thr   <  0        (*)
        6     mid-level vortex              any      <  0       >= 0

    (*) "any" for rows 4/5 means "whatever `vtu` is left once row 6 has
    claimed the `lower VT < 0 and upper VT >= 0` corner" -- row 6 is
    checked first and takes precedence over rows 4 and 5 there (see
    "Ordering" below); in practice this means `vtu < 0` for rows 4/5.

    Boundary convention: **B is frontal at `B > b_threshold` (10 m by
    default), symmetric at `B <= b_threshold`** -- Hart's own strict
    line, no neutral band. **Each thermal wind term is warm at
    `>= 0`, cold only at strictly `< 0`** -- this is not the arbitrary
    half of two equally defensible choices: Evans and Hart (2003) define
    extratropical transition *completion* as the point VTL "turns
    negative", i.e. the moment it goes strictly below zero, so a VTL of
    exactly 0.0 has not yet turned negative and must still read as warm,
    not cold, for the completion criterion embedded in this table (rows
    4/5 vs. rows 0-3) to reproduce Evans and Hart's own definition
    exactly. The same `>= 0` warm / `< 0` cold split is used for VTU for
    consistency (Hart's own Phase 2 diagram treats the two thermal wind
    axes identically). This module deliberately draws these as *strict
    lines*, not a neutral band the way the retired `HCPScat`'s 5-category
    table used one (a fixed-width band around zero, now removed along
    with that function): Hart's own thresholds (10 m for
    B, 0 m for VTL/VTU) are themselves strict lines with no neutral zone,
    and the continuous `HB`/`HVTL`/`HVTU` fields already carry the
    magnitude a forecaster needs to judge "how marginal" a call at the
    line actually is -- a categorical field's job is to draw the line
    Hart drew, not to soften it with a second, invented threshold.

    Ordering / precedence: row 6 (mid-level vortex: cold at low levels,
    warm aloft) is checked before rows 4 and 5, so it wins the corner of
    `(B, vtl, vtu)` space that would otherwise also satisfy "lower VT
    negative" -- a genuine mid-level vortex is a different structure
    from a frontal or symmetric cold core (which are cold at *both*
    levels), not a third way of being one of those two, regardless of
    B. Every other row is a disjoint partition of the remaining
    `(vtl >= 0 or < 0) x (vtu >= 0 or < 0)` quadrants by the B line, so
    the six remaining codes plus row 6 exhaust the space with no gaps
    and no overlaps for finite input.

    Rationale for the code numbering: codes rise, in order, along a
    typical extratropical transition -- 0 (symmetric deep warm core,
    the tropical-cyclone-like starting state) to 2 (frontal, still deep
    warm, B has crossed 10 m: Evans and Hart's onset) to 3 (frontal
    shallow warm core, the upper thermal wind has gone negative first)
    to 4 (frontal cold core, VTL has now gone negative too: Evans and
    Hart's completion). A warm seclusion is a storm that reaches 4 and
    then re-forms a warm core at low levels while still frontal, i.e.
    4 then back to 1 (not 0, since B commonly stays above 10 m through
    the seclusion) -- a drop in code number that looks like a
    regression only if the sequence is read as strictly increasing;
    read correctly, it is the seclusion signature itself. Evans and
    Hart's own onset is the first frame whose code is 2 or 3 (B crossed
    10 m while still warm-core), and completion is the first frame whose
    code is 4 or 5 (VTL crossed 0); both are read off a *sequence* of
    frames in an animation or loop, the same way a forecaster already
    reads Hart's own two diagrams over time -- this field reports only
    the current frame's class, with no memory of any earlier one (see
    the module docstring's "Parameter B and the joint class" section).

    Returns a float32 array.
    """
    B = np.asarray(B, dtype=float)
    vtl = np.asarray(vtl, dtype=float)
    vtu = np.asarray(vtu, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    thr = float(b_threshold)

    with np.errstate(invalid="ignore"):
        conditions = [
            (vtl < 0.0) & (vtu >= 0.0),                    # 6 mid-level vortex (checked first)
            (B <= thr) & (vtl >= 0.0) & (vtu >= 0.0),      # 0 symmetric deep warm core
            (B <= thr) & (vtl >= 0.0) & (vtu < 0.0),       # 1 symmetric shallow warm core
            (B > thr) & (vtl >= 0.0) & (vtu >= 0.0),       # 2 frontal deep warm core
            (B > thr) & (vtl >= 0.0) & (vtu < 0.0),        # 3 frontal shallow warm core
            (B > thr) & (vtl < 0.0),                        # 4 frontal cold core
            (B <= thr) & (vtl < 0.0),                       # 5 symmetric cold core
        ]
        choices = [6, 0, 1, 2, 3, 4, 5]
        code = np.select(conditions, choices, default=np.nan)

    valid = mask & np.isfinite(B) & np.isfinite(vtl) & np.isfinite(vtu)
    code = np.where(valid, code, np.nan)
    return code.astype(np.float32)


# ---------------------------------------------------------------------------
# AWIPS entry points
# ---------------------------------------------------------------------------


def executeBand3(z1, z2, z3, psfc, dx, dy, radiusKm, p1, p2, p3, capHpa=BELOW_GROUND_CAP_HPA):
    """AWIPS derived-parameter entry point: thermal wind over 3 levels.

    `z1`/`z2`/`z3` are geopotential height (meters) at three pressure
    levels (any order); `p1`/`p2`/`p3` are the matching pressures (hPa),
    matched to `z1`/`z2`/`z3` by position. `psfc` is AWIPS surface
    pressure (Pa or hPa -- `surface_pressure_hpa` auto-detects which);
    each height level is blanked (NaN) wherever it is below ground for
    its own pressure and `capHpa` (see `mask_below_ground` and the
    module docstring's "Below-ground masking" section) before the
    thermal wind is computed. `dx`, `dy` are the grid spacing
    pseudo-fields (meters). `radiusKm`/`capHpa` may arrive as a float, a
    0-d numpy array, or a 1-element numpy array (an AWIPS `<ConstantField>`
    value). Returns a float32 array, units meters (see the module
    docstring); positive = warm core.
    """
    radius_km = _coerce_scalar(radiusKm)
    cap_hpa = _coerce_scalar(capHpa)
    pressures = [_coerce_scalar(p1), _coerce_scalar(p2), _coerce_scalar(p3)]
    psfc_hpa = surface_pressure_hpa(psfc)
    slope = thermal_wind_grid([z1, z2, z3], pressures, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    return slope.astype(np.float32)


def executeBand4(z1, z2, z3, z4, psfc, dx, dy, radiusKm, p1, p2, p3, p4, capHpa=BELOW_GROUND_CAP_HPA):
    """AWIPS derived-parameter entry point: thermal wind over 4 levels.
    Same conventions as `executeBand3`, including `psfc`/`capHpa`
    below-ground masking.
    """
    radius_km = _coerce_scalar(radiusKm)
    cap_hpa = _coerce_scalar(capHpa)
    pressures = [_coerce_scalar(p1), _coerce_scalar(p2), _coerce_scalar(p3), _coerce_scalar(p4)]
    psfc_hpa = surface_pressure_hpa(psfc)
    slope = thermal_wind_grid([z1, z2, z3, z4], pressures, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    return slope.astype(np.float32)


def executeBand7(z1, z2, z3, z4, z5, z6, z7, psfc, dx, dy, radiusKm, p1, p2, p3, p4, p5, p6, p7, capHpa=BELOW_GROUND_CAP_HPA):
    """AWIPS derived-parameter entry point: thermal wind over 7 levels.

    For a future GFS-only definition using Hart's exact 50 hPa-spaced
    bands (900, 850, 800, 750, 700, 650, 600 hPa or 600, 550, 500, 450,
    400, 350, 300 hPa) rather than the 3-level `LOWER_BAND`/`UPPER_BAND`
    standard-level approximation `executeBand3` is meant for -- see the
    module docstring's "Standard level bands" section. Same conventions
    as `executeBand3` (including `psfc`/`capHpa` below-ground masking),
    just with 7 height/pressure pairs instead of 3.
    """
    radius_km = _coerce_scalar(radiusKm)
    cap_hpa = _coerce_scalar(capHpa)
    pressures = [
        _coerce_scalar(p1), _coerce_scalar(p2), _coerce_scalar(p3), _coerce_scalar(p4),
        _coerce_scalar(p5), _coerce_scalar(p6), _coerce_scalar(p7),
    ]
    psfc_hpa = surface_pressure_hpa(psfc)
    slope = thermal_wind_grid(
        [z1, z2, z3, z4, z5, z6, z7], pressures, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa,
    )
    return slope.astype(np.float32)


def executeHartClass(
    z1000, z925, z850, z700, z500, z400, z300,
    u850, v850, u700, v700, u500, v500, u300, v300,
    psfc, coriolis, dx, dy,
    radiusKm=RADIUS_KM,
    bThresholdM=B_THRESHOLD_M,
    layerScale=HART_B_LAYER_SCALE,
    depthM=DEFAULT_DEPTH_M,
    blobKm=DEFAULT_BLOB_RADIUS_KM,
    capHpa=BELOW_GROUND_CAP_HPA,
):
    """AWIPS derived-parameter entry point for HCPSclass (cps_HCPSclass.xml):
    the joint Hart CPS class -- see `hart_class`'s own docstring for the
    full 7-code table, the boundary convention, and the ordering
    rationale, and the module docstring's "Parameter B and the joint
    class" and "Relation to Hart's storm-centered diagrams" sections for
    why this single field replaces the retired `HCPScat` (Phase 2 class)
    and `HETstage` (extratropical transition stage) fields.

    Computes the lower thermal wind (`LOWER_BAND`, 925/850/700 hPa) and
    upper thermal wind (`UPPER_BAND`, 500/400/300 hPa, both via
    `thermal_wind_grid`), parameter B (925-700 hPa thickness gradient
    projected onto the steering-flow's right-hand normal, via `steering`
    and `parameter_b_grid` -- same method as `executeB`), and
    `closed_low_mask` on `z1000` (same mask `executeIndexStd` uses), then
    combines all three with `hart_class`.

    `z1000`...`z300` are geopotential height (meters) at the seven
    standard levels; `u850`/`v850`...`u300`/`v300` are the four
    steering-flow wind level pairs (as in `executeB`). `psfc` is AWIPS
    surface pressure (Pa or hPa -- `surface_pressure_hpa` auto-detects
    which); `coriolis` is the AWIPS coriolis pseudo-field (as in
    `executeB`) whose sign is parameter B's hemisphere factor. `dx`,
    `dy` are the grid spacing pseudo-fields (meters).

    Before anything else, every one of the seven height arguments is run
    through `mask_below_ground` against its own pressure and `capHpa` --
    see the module docstring's "Below-ground masking" section and
    `executeIndexStd`'s docstring for the full explanation (why `z1000`
    is used for the mask rather than a band level, and why the
    below-ground threshold is capped rather than applied at each level's
    own literal pressure).

    `radiusKm`, `bThresholdM`, `layerScale`, `depthM`, `blobKm`, `capHpa`
    may each arrive as a float, a 0-d numpy array, or a 1-element numpy
    array (AWIPS `<ConstantField>` values) and are coerced with
    `_coerce_scalar`; see `executeIndexStd`'s docstring for why
    `closed_low_mask`'s `min_radius_km`/`center_tol_m` are not exposed
    here either.

    Returns a float32 array: NaN outside the closed-low mask, below
    ground, or wherever B is NaN (the steering-flow speed below
    `MIN_STEERING_MS` -- rare, but see `parameter_b_grid`'s docstring);
    otherwise one of 0.0 through 6.0 (dimensionless) per `hart_class`'s
    table.
    """
    radius_km = _coerce_scalar(radiusKm)
    b_threshold_m = _coerce_scalar(bThresholdM)
    layer_scale = _coerce_scalar(layerScale)
    depth_m = _coerce_scalar(depthM)
    blob_radius_km = _coerce_scalar(blobKm)
    cap_hpa = _coerce_scalar(capHpa)

    psfc_hpa = surface_pressure_hpa(psfc)

    vtl = thermal_wind_grid([z925, z850, z700], LOWER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    vtu = thermal_wind_grid([z500, z400, z300], UPPER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)

    z925_masked = mask_below_ground(z925, psfc_hpa, 925.0, cap_hpa)
    z700_masked = mask_below_ground(z700, psfc_hpa, 700.0, cap_hpa)
    thickness = np.asarray(z700_masked, dtype=float) - np.asarray(z925_masked, dtype=float)
    u_s, v_s = steering([u850, u700, u500, u300], [v850, v700, v500, v300])
    b = parameter_b_grid(thickness, u_s, v_s, dx, dy, coriolis, radius_km, layer_scale)

    z1000_masked = mask_below_ground(z1000, psfc_hpa, 1000.0, cap_hpa)
    mask = closed_low_mask(z1000_masked, dx, dy, MIN_RADIUS_KM, radius_km, depth_m, blob_radius_km)

    return hart_class(b, vtl, vtu, mask, b_threshold_m)


def executeIndexStd(
    z1000, z925, z850, z700, z500, z400, z300, psfc, dx, dy,
    radiusKm=RADIUS_KM,
    scaleM=100.0,
    depthM=DEFAULT_DEPTH_M,
    blobKm=DEFAULT_BLOB_RADIUS_KM,
    capHpa=BELOW_GROUND_CAP_HPA,
):
    """AWIPS derived-parameter entry point for HCPSidx (cps_HCPSidx.xml).

    Same lower/upper thermal wind and mask as `executeHartClass`, combined
    into `2*tanh(VTL/scaleM) + tanh(VTU/scaleM)` (range -3 to +3, `scaleM`
    already in meters), blanked (NaN) outside the same `closed_low_mask`
    computed from `z1000`, and the same below-ground masking of `z1000`
    and the six band levels via `psfc`/`capHpa` -- see `executeHartClass`'s
    docstring for the full explanation (why `z1000` rather than a band
    level is used for the mask, and why the below-ground threshold is
    capped at `capHpa` rather than applied at each level's own literal
    pressure). `radiusKm`, `scaleM`, `depthM`, `blobKm`, `capHpa` are
    coerced the same way as `executeHartClass`'s constants; see that
    function's docstring for why `closed_low_mask`'s
    `min_radius_km`/`center_tol_m` are not exposed here either.

    Returns a float32 array, NaN outside the mask or below ground,
    otherwise in [-3, 3].
    """
    radius_km = _coerce_scalar(radiusKm)
    scale_m = _coerce_scalar(scaleM)
    depth_m = _coerce_scalar(depthM)
    blob_radius_km = _coerce_scalar(blobKm)
    cap_hpa = _coerce_scalar(capHpa)

    psfc_hpa = surface_pressure_hpa(psfc)

    vtl = thermal_wind_grid([z925, z850, z700], LOWER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    vtu = thermal_wind_grid([z500, z400, z300], UPPER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    z1000_masked = mask_below_ground(z1000, psfc_hpa, 1000.0, cap_hpa)
    mask = closed_low_mask(z1000_masked, dx, dy, MIN_RADIUS_KM, radius_km, depth_m, blob_radius_km)

    index = 2.0 * np.tanh(vtl / scale_m) + np.tanh(vtu / scale_m)
    masked = ~mask | ~np.isfinite(vtl) | ~np.isfinite(vtu)
    index = np.where(masked, np.nan, index)
    return index.astype(np.float32)


def executeB(
    z925, z700,
    u850, v850, u700, v700, u500, v500, u300, v300,
    psfc, coriolis, dx, dy,
    radiusKm=RADIUS_KM,
    layerScale=HART_B_LAYER_SCALE,
    capHpa=BELOW_GROUND_CAP_HPA,
):
    """AWIPS derived-parameter entry point for HB (cps_HB.xml): Hart's
    parameter B (thermal asymmetry), gridded -- see the module
    docstring's "Parameter B and the joint class" section for the full
    method.

    `z925`/`z700` are geopotential height (meters); their difference
    (`z700 - z925`) is this module's thickness layer (see the module
    docstring for why 925-700 hPa rather than Hart's own 900-600 hPa, and
    `layerScale`'s role in rescaling for it). Each is blanked (NaN) below
    ground for its own pressure and `capHpa` before the difference is
    taken (`mask_below_ground`), so `B` comes back NaN wherever either
    height input was masked -- via the resulting NaN thickness
    propagating through `parameter_b_grid`'s gradient and window mean.

    `u850`/`v850`, `u700`/`v700`, `u500`/`v500`, `u300`/`v300` are the
    wind components at those four levels, averaged by `steering` into
    the motion proxy `parameter_b_grid` uses. `psfc` is AWIPS surface
    pressure (Pa or hPa -- `surface_pressure_hpa` auto-detects which).
    `coriolis` is the AWIPS coriolis pseudo-field (positive Northern
    Hemisphere, negative Southern) -- `parameter_b_grid` uses its sign as
    the hemisphere factor `h`; a 2D field lets a grid straddling the
    equator get the correct sign on each side. `dx`, `dy` are the grid
    spacing pseudo-fields (meters).

    `radiusKm`, `layerScale`, `capHpa` may each arrive as a float, a 0-d
    numpy array, or a 1-element numpy array (AWIPS `<ConstantField>`
    values) and are coerced with `_coerce_scalar`. Returns a float32
    array, units meters ("900-600 hPa equivalent" -- see the module
    docstring); positive = warm/thick air on the right of motion in the
    Northern Hemisphere (or on the left in the Southern), i.e. the
    frontal/asymmetric configuration; NaN below `MIN_STEERING_MS` or
    below ground.
    """
    radius_km = _coerce_scalar(radiusKm)
    layer_scale = _coerce_scalar(layerScale)
    cap_hpa = _coerce_scalar(capHpa)

    psfc_hpa = surface_pressure_hpa(psfc)
    z925_masked = mask_below_ground(z925, psfc_hpa, 925.0, cap_hpa)
    z700_masked = mask_below_ground(z700, psfc_hpa, 700.0, cap_hpa)
    thickness = np.asarray(z700_masked, dtype=float) - np.asarray(z925_masked, dtype=float)

    u_s, v_s = steering([u850, u700, u500, u300], [v850, v700, v500, v300])

    b = parameter_b_grid(thickness, u_s, v_s, dx, dy, coriolis, radius_km, layer_scale)
    return b.astype(np.float32)


# ---------------------------------------------------------------------------
# Standalone sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Synthetic Gaussian warm-core vortex on a 0.5 degree lat/lon grid,
    # centered at 20N, 0E -- the same style of test fixture cps/hart.py's
    # own test suite uses (tests/cps/synthetic.py), built inline here so
    # this module has no import dependency on the test tree.
    EARTH_RADIUS_KM = 6371.0
    HALF_WIDTH_DEG = 20.0
    GRID_STEP_DEG = 0.5
    CENTER_LAT, CENTER_LON = 20.0, 0.0

    lat_vals = np.arange(CENTER_LAT - HALF_WIDTH_DEG, CENTER_LAT + HALF_WIDTH_DEG + 1e-9, GRID_STEP_DEG)
    lon_vals = np.arange(CENTER_LON - HALF_WIDTH_DEG, CENTER_LON + HALF_WIDTH_DEG + 1e-9, GRID_STEP_DEG)
    lon2d, lat2d = np.meshgrid(lon_vals, lat_vals)

    # dx varies row-to-row (per-latitude cos(lat) factor); dy is uniform.
    dx_row_m = EARTH_RADIUS_KM * np.cos(np.radians(lat_vals)) * np.radians(GRID_STEP_DEG) * 1000.0
    dx2d = np.repeat(dx_row_m[:, np.newaxis], lon_vals.size, axis=1)
    dy_m = EARTH_RADIUS_KM * np.radians(GRID_STEP_DEG) * 1000.0

    def _haversine_km(lat1, lon1, lat2, lon2):
        lat1r, lat2r = np.radians(lat1), np.radians(lat2)
        dlat = lat2r - lat1r
        dlon = np.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
        a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
        return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))

    r_km = _haversine_km(lat2d, lon2d, CENTER_LAT, CENTER_LON)
    scale_km = 150.0
    decay = np.exp(-(r_km / scale_km) ** 2)

    # Amplitude decreasing with height (larger at 925 than at 300 hPa) --
    # a warm core, per the module docstring's sign derivation. 1000 hPa
    # (the mask level -- see the module docstring's "Closed-low mask
    # level" section) gets the largest amplitude of all, so the low is
    # deepest there, the same way it deepens toward the surface in a
    # real warm-core vortex.
    amp_by_level = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    z_by_level = {}
    for p, amp in amp_by_level.items():
        background = 100.0 + 7000.0 * np.log(1000.0 / p)
        z_by_level[p] = background - amp * decay

    vtl = thermal_wind_grid([z_by_level[p] for p in LOWER_BAND], LOWER_BAND, dx2d, dy_m, RADIUS_KM)
    vtu = thermal_wind_grid([z_by_level[p] for p in UPPER_BAND], UPPER_BAND, dx2d, dy_m, RADIUS_KM)

    ci = lat_vals.size // 2
    cj = lon_vals.size // 2
    print("VTL (lower, 925-700) at center, m (expect roughly +100 to +300):", vtl[ci, cj])
    print("VTU (upper, 500-300) at center, m (expect roughly +100 to +300):", vtu[ci, cj])

    # No terrain: ordinary open-ocean surface pressure everywhere.
    psfc_ocean = np.full(lat2d.shape, 1013.0)

    # Joint class demo: this vortex sits in a purely radial background
    # (no ambient thickness gradient at all -- see amp_by_level above),
    # so parameter B at the exact center is near zero regardless of the
    # steering direction; run it once in a westerly and once in an
    # easterly steering flow to show that a real vortex's own class does
    # not flip just because the storm is moving a different way when
    # there is no environment to make B direction-dependent (contrast
    # with the linear-thickness-gradient demo below, where direction is
    # exactly what flips B's sign).
    coriolis_nh = np.full(lat2d.shape, 1.0)  # Northern Hemisphere everywhere
    v_zero = np.full(lat2d.shape, 0.0)

    u_westerly = np.full(lat2d.shape, 8.0)
    cls_westerly = executeHartClass(
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        u_westerly, v_zero, u_westerly, v_zero, u_westerly, v_zero, u_westerly, v_zero,
        psfc_ocean, coriolis_nh, dx2d, dy_m,
    )
    print("class at center, 8 m/s westerly steering (expect 0.0, symmetric deep warm core):", cls_westerly[ci, cj])
    print("class far from the vortex (expect nan, outside the closed-low mask):", cls_westerly[0, 0])

    u_easterly = np.full(lat2d.shape, -8.0)
    cls_easterly = executeHartClass(
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        u_easterly, v_zero, u_easterly, v_zero, u_easterly, v_zero, u_easterly, v_zero,
        psfc_ocean, coriolis_nh, dx2d, dy_m,
    )
    print("class at center, 8 m/s easterly steering (expect 0.0, same symmetric deep warm core):", cls_easterly[ci, cj])

    # Below-ground masking demo: a fake terrain block (surface pressure
    # 750 hPa, well under BELOW_GROUND_CAP_HPA's 900) 800 km due west of
    # the vortex center -- outside the vortex's own 500 km analysis
    # window, so it should not change the class at the vortex center.
    psfc_terrain = psfc_ocean.copy()
    block_dlon_deg = np.degrees(800.0 / (EARTH_RADIUS_KM * np.cos(np.radians(CENTER_LAT))))
    block_lon_center = CENTER_LON - block_dlon_deg
    block_half_deg = 1.0
    block_mask = (
        (np.abs(lon2d - block_lon_center) <= block_half_deg)
        & (np.abs(lat2d - CENTER_LAT) <= block_half_deg)
    )
    psfc_terrain[block_mask] = 750.0

    cls_terrain = executeHartClass(
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        u_westerly, v_zero, u_westerly, v_zero, u_westerly, v_zero, u_westerly, v_zero,
        psfc_terrain, coriolis_nh, dx2d, dy_m,
    )
    print("class at center with a terrain block 800 km west (expect unchanged, 0.0):", cls_terrain[ci, cj])
    block_i, block_j = np.argwhere(block_mask)[0]
    print("class over the terrain block (expect nan, below ground):", cls_terrain[block_i, block_j])

    # ---------------------------------------------------------------------
    # Parameter B demo: a linear thickness gradient and a steering flow
    # along the thickness contours (i.e. perpendicular to the gradient --
    # a system riding along a front, not crossing it), which is the case
    # that produces a clean, full-magnitude B rather than the near-zero B
    # a steering flow *along* the gradient would give (see
    # tests/d2d_cps/test_hart_cps.py for that case).
    #
    # This grid (lat_vals increasing northward, axis 0 = y increasing
    # northward) is the plain numpy-default layout, i.e. ORIENTATION_MODE
    # mode 0 -- not this module's real default (mode 1, tuned for AWIPS
    # sites). Setting it here, like CycloneCore.py's own __main__ demo,
    # is a plain module-level assignment that gradient_2d (and so
    # parameter_b_grid/executeB) picks up with no other change needed.
    ORIENTATION_MODE = 0

    y_km_from_center = EARTH_RADIUS_KM * np.radians(lat2d - CENTER_LAT)
    GRADIENT_M_PER_KM = 0.05  # gentle 925-700 hPa thickness gradient, warmer/thicker to the south
    thickness_linear = -GRADIENT_M_PER_KM * y_km_from_center  # m; dThickness/dy = -GRADIENT_M_PER_KM/1000 m/m

    STEERING_MS = 15.0  # due east, i.e. along the (east-west) thickness contours
    u_level = np.full(lat2d.shape, STEERING_MS)
    v_level = np.full(lat2d.shape, 0.0)
    coriolis_nh = np.full(lat2d.shape, 1.0)  # Northern Hemisphere everywhere

    u_s_demo, v_s_demo = steering([u_level] * 4, [v_level] * 4)
    b_linear = parameter_b_grid(thickness_linear, u_s_demo, v_s_demo, dx2d, dy_m, coriolis_nh, RADIUS_KM, HART_B_LAYER_SCALE)

    # Analytic expectation: n_right for due-east motion is (0, -1) (south);
    # dThickness/dy = -GRADIENT_M_PER_KM/1000 m/m, so
    # n_right . grad = -1 * (-GRADIENT_M_PER_KM/1000) = GRADIENT_M_PER_KM/1000.
    analytic_b = b_geometry_km(RADIUS_KM) * 1000.0 * (GRADIENT_M_PER_KM / 1000.0) * HART_B_LAYER_SCALE
    print("Parameter B on a linear thickness gradient, steering due east along the contours:")
    print("  gridded B at center, m (900-600 equivalent):", b_linear[ci, cj])
    print("  analytic expectation, m:", analytic_b)
