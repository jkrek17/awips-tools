"""
cps_HartCPS.py -- AWIPS II D2D derived parameter: Hart (2003) actual thermal
wind parameters, computed pointwise on the grid.

*** EXPERIMENTAL.  NOT OPERATIONALLY VETTED. ***

This is the operational cyclone phase space module. It computes Hart's
own quantity -- the actual -V_T^L / -V_T^U thermal wind parameters from
`cps/hart.py`'s `thermal_wind` -- at every point of the grid, from
geopotential height, plus parameter B (from 925-700 hPa thickness and
the steering wind) and the joint class (which also needs mean sea level
pressure, for its closed-low mask).


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
storm center.

Sign convention: identical to `cps.hart.thermal_wind` -- **positive
means warm core**. A tropical cyclone has more low-level thickness
right over its center than 500 km out, and that excess shrinks with
height, so `dZ` is larger at high pressure (large ln p) than at low
pressure (small ln p): a positive slope of `dZ` against `ln(p)`. A
cold-core system is the opposite and comes back negative.

Units: like Hart's own VTL/VTU, the output is in meters (of `dZ`) per
unit of `ln(pressure in hPa)` -- i.e. plain meters, since `ln(p)` is
dimensionless. A mature hurricane typically samples in the +100 to
+300 m range; a cold-core low typically samples -100 to -300 m.

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
warm-core vortex.

Longitude wrap on global grids
--------------------------------

`window_extreme_2d`/`window_sum_2d` (and, through them, `delta_z`,
`window_mean`, and `closed_low_mask`), and `half_disk_means`, slide
their x-direction pass
along axis 1 of the field array. On a regional grid that is exactly
right: there is real "off the edge of the grid" on both sides, and the
window should shrink there rather than wrap. On a *global* lat/lon
grid, axis 1 is longitude running all the way around the planet, so
column 0's true west neighbor is the *last* column, not nothing --
clipping the window at the array edge instead of wrapping it silently
halves the effective window (and so `dZ`) for every point within
`RADIUS_KM` of the seam. `is_global_lon(nx, dy_m)` detects this case:
for an equal-angular-spacing lat/lon grid, `nx` columns times the
(latitude-independent) row spacing `dy_m` equals the Earth's
circumference if and only if those `nx` columns span the full 360
degrees of longitude at the same angular spacing as `dy_m`'s
north-south step -- true for a genuinely global grid, false for a
regional one (whose `nx` columns span less than 360 degrees) purely by
how many columns happen to fit the same test. `delta_z`, `window_mean`,
`half_disk_means`, and `closed_low_mask` each take an optional
`global_lon` keyword
(`None`, the default, means "decide with `is_global_lon`"; `True`/
`False` forces the decision either way, mainly so a test can exercise
both code paths on the same grid) and pass the resulting `wrap_x` flag
down to `window_extreme_2d`/`window_sum_2d`, which cyclically pad the
columns (by the largest per-row half-width actually needed, clamped to
`nx // 2`) before the x pass and crop the padding back off afterward
(`half_disk_means` pads the same way, internally).

Closed-low mask
----------------

`closed_low_mask` (used by `executeHartClass`/`executeIndexStd` to blank
every point outside a real closed low) is computed from **mean sea level
pressure** (`pmsl`, AWIPS's PMSL field, Pa or hPa), a separate argument
from the six `LOWER_BAND`/`UPPER_BAND` heights the thermal wind itself
is built from. MSLP is one field, the same surface a forecaster already
contours, so the closed low the mask finds is the closed low drawn on
the chart -- which is the point of masking at all. It is defined
everywhere (reduced to sea level over terrain), so it needs no
below-ground masking of its own, and unlike 1000 hPa height (which an
earlier version of this module used, at about 8 m per hPa) it involves
no extrapolation below sea level inside a deep low. The ring depth test
reads directly in pressure: `DEFAULT_DEPTH_HPA` (5 hPa), with a
`DEFAULT_CENTER_TOL_HPA` (0.6 hPa) candidate tolerance. Terrain blanking
of the masked products comes from the band levels instead, which are NaN
below ground (see "Below-ground masking" below): a point whose 925 hPa
height is below ground has a NaN lower thermal wind and so a NaN class
or index, whatever the mask says.

Below-ground masking
----------------------

Every height level this module uses -- the six `LOWER_BAND`/
`UPPER_BAND` levels -- can be below the ground surface
over major terrain, or below sea level itself inside a sufficiently
deep low, where the model is extrapolating rather than reporting an
analyzed height. Over the open ocean that extrapolation is harmless (a
deep low's surface pressure legitimately drops well under 1000 or
925 hPa at its own center, and the height there is still meaningful).
Over ice sheets and high mountains it is not: a level whose pressure
is below the local surface pressure is fictitious, and letting it into
a window's max/min or parameter B's half-disk means can quietly bias
the result.

`mask_below_ground(z, psfc_hpa, level_hpa, cap_hpa)` blanks (NaN) `z`
wherever a point is below ground for pressure level `level_hpa`:

    psfc_hpa < min(level_hpa, cap_hpa)

`cap_hpa` (`BELOW_GROUND_CAP_HPA`, default 900 hPa) keeps the ocean
case above from being caught by this rule: without it, a deep low's
own surface pressure (which can legitimately fall well under 1000 or
925 hPa at its center) would mask the very feature this family exists
to find. With the cap, a point only counts as below ground for the
925 hPa level (or 1000 hPa, for a caller that uses it) when the
surface pressure drops under 900 hPa
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
already be hPa. `mslp_hpa` applies the same rule to the MSLP field the
closed-low mask reads.

`thermal_wind_grid` applies `mask_below_ground` to each of its
`z_levels` (matched to its own `pressures`) before `delta_z`, when
given an optional `psfc_hpa` (paired with `cap_hpa`); `psfc_hpa=None`
(the default) skips this entirely, so callers with no terrain to
mask -- including this module's own reference tests -- are
unaffected. `executeHartClass`/`executeIndexStd`/`executeBand3`/
`executeBand4`/`executeBand7` all take a `psfc` argument and a
`capHpa` constant (default `BELOW_GROUND_CAP_HPA`) and apply the mask
to every height argument (`executeB` does the same for its two). The
MSLP argument of `executeHartClass`/`executeIndexStd` is not masked (see
"Closed-low mask" above). Because the sliding window extrema
(`window_extreme_2d`), box sums (`window_sum_2d`) and half-disk means
(`half_disk_means`) this module uses are already NaN-aware, a
below-ground point's neighbors just see one fewer valid sample in
their own window -- no
extra plumbing was needed beyond masking the input before it reaches
them.

Parameter B and the joint class
---------------------------------

Hart's (2003) third CPS number, B (thermal asymmetry), is the
right-minus-left half-window mean of 900-600 hPa thickness across the
storm's own direction of motion, over the same 500 km circle VTL/VTU
use: `B = h * (mean_right - mean_left)`, `h = +1` in the Northern
Hemisphere, `-1` in the Southern, so that the asymmetric configuration
(warm/thick air to the right of the track in the Northern Hemisphere,
to the left in the Southern) always reads positive. B is relative to
the direction of motion, not to latitude -- it is not "warm air on the
equatorward flank": a storm moving east has its warm side to the
south, but a storm moving west has its warm side to the north, for the
identical physical thickness field. `B_THRESHOLD_M` (10 m) separates a
symmetric, tropical-like
thickness field (below) from an asymmetric one (above), and
Evans and Hart (2003) define the extratropical transition **onset**
as the first time `B` exceeds this threshold, with **completion** at
the point VTL (the lower thermal wind) turns negative.

Hart's B is a semicircle difference, and this module computes exactly
that at every grid point: `half_disk_means` gives the NaN-aware,
area-weighted mean thickness over the north, south, east and west
half-disks of radius `R` (500 km) around each point, built row offset
by row offset from one cumulative sum along x (cost of order the number
of row offsets times the number of grid points, about 0.4 s on a
721 x 1440 grid), and `parameter_b_grid` combines them with the unit
motion vector `(mx, my)` (east, north):

    ZR - ZL = mx * (mean_south - mean_north) + my * (mean_east - mean_west)
    B       = h * (ZR - ZL) * layer_scale

This is the wavenumber-one interpolation between the two axis-aligned
splits. Expanding the thickness about the point in azimuthal harmonics,
harmonic `k` contributes nothing to any semicircle difference when `k`
is even and `(4/pi)/k` times its area-mean amplitude (with sign
`sin(k*pi/2)`) when `k` is odd; the `k = 1` contribution turns with the
motion direction exactly as the formula above does, so B is exact (up to
the grid's discretization of the disk) for any wavenumber-one pattern
about the point. That covers a uniform thickness gradient, for which it
reduces to the older first-order form `(8*R/(3*pi))` times the
window-mean gradient projected on the right-hand normal of motion (kept
as `parameter_b_grid_gradient` for comparison; see `b_geometry_km`), and
it covers the storm-scale dipole that the first-order form reads at only
about 55-60%: for a thickness dipole `A*(x_R/L)*exp(-r**2/(2*L**2))`
with `L = 400 km` and `R = 500 km` the semicircle means recover Hart's
difference to well within 1%, the gradient form about 0.55 of it (see
`tests/d2d_cps/test_hart_cps.py`). What the interpolation does not
capture is the odd harmonics `k >= 3` of the thickness field about the
point, whose weight in Hart's semicircle difference is at most `(4/pi)/k`
of their area-mean amplitude (0.42 for `k = 3`, against 1.27 for
`k = 1`); a sharply folded warm-seclusion tongue can carry some of that.
The lattice discretization of the disk (whole cells, row by row) costs
well under 1% at 0.25 degree spacing, and a few percent at 1 degree.

**Motion**: Hart's own B needs the storm's own track heading; a
gridded pointwise field has no storm to track, so the motion at each
grid point is taken from the **steering flow**, meant as a proxy for
the environmental deep-layer flow that carries a storm along -- not
for the storm's own circulation. The pointwise vertical mean of the
wind at 850, 700, 500, and 300 hPa (`steering`) is *not* that
environmental flow by itself: inside any developed cyclone, the
pointwise deep-layer mean wind at a point near the center is
dominated by the vortex's own rotating circulation, which sweeps
through every compass heading within a degree or so of the center, so
using it directly as "storm motion" mixes the vortex into its own
motion proxy. `steering_window_mean` fixes this by area-averaging each
component of `steering`'s output over the same `RADIUS_KM` (500 km)
analysis window `delta_z`/parameter B's half-disks use (via
`window_mean`) *before* `parameter_b_grid` takes its direction: a
symmetric vortex's own tangential wind averages out over a window that
large, leaving the environmental flow the vortex is actually embedded
in and steered by. `executeB` and `executeHartClass` both call
`steering` then `steering_window_mean` in sequence; a caller of
`parameter_b_grid` directly is responsible for passing already
window-averaged `u_s`/`v_s`. This window-averaged steering is still
only a proxy for translation speed and direction on most systems, not
a substitute for Hart's own track: a storm moving against its own
steering flow (unusual, but not unheard of at landfall or during a
sharp recurvature), or a nearly stationary system (`MIN_STEERING_MS`,
2 m/s, below which B is blanked to NaN rather than divide by a
near-zero speed and amplify noise), gets an unreliable or missing B
from this method even where Hart's own track-based B would be well
defined.

**Right of motion**: for steering `(u_s, v_s)`, the right-hand
normal used in the Northern Hemisphere is `(v_s, -u_s)/|V_s|` (e.g.
moving due north, `(u_s, v_s) = (0, +V)`, gives normal `(1, 0)`, i.e.
east -- the intuitive "right" when facing north), which is why moving
north reads the east-minus-west half-disk difference and moving east
the south-minus-north one. This is the same left/right convention
`cps.hart.parameter_b` uses via its cross product (moving north, a
point due east has `cross < 0`, defined there as "right of track"),
checked against it numerically in the tests. The hemisphere factor
`h = sign(coriolis)` (exact zero treated as `+1`, matching the Northern
Hemisphere convention) then multiplies the semicircle difference so the "warm air on
the right in the NH, on the left in the SH" reading is positive in
both hemispheres, exactly mirroring `cps.hart.parameter_b`'s own
`hemisphere_sign`. `coriolis` may be handed in as a 2D pseudo-field (so
a grid straddling the equator gets the correct sign on each side) or a
scalar (assume one hemisphere everywhere).

**Layer scaling**: this module's thickness layer is 925-700 hPa (for
consistency with `LOWER_BAND`, the same standard-level lower
thermal-wind band), not Hart's 900-600 hPa. Because thickness scales
with the log-pressure depth of the layer, `B` is multiplied by
`HART_B_LAYER_SCALE = ln(900/600)/ln(925/700)` (~1.4548) by default,
so the result reads as a "900-600 equivalent" against Hart's own 10 m
threshold; a caller wanting the raw, unscaled 925-700 hPa value passes
`layerScale=1.0`.

This entire scheme -- the semicircle means, the steering-flow motion
proxy, and the layer scaling -- is orientation- and sign-free by
construction except for one place: which half-disk is north and which
is east (`half_disk_means`; and, for the first-order comparison form,
the sign of `gradient_2d`'s derivative) depends on which way the
grid's axes actually run. `ORIENTATION_MODE` (module level; see its
own comment for the full description of the four conventions)
controls this; every other function in this module (`window_mean`,
`steering`, `hart_class`) is orientation-free. Mode 1 is confirmed on
the OPC build.

`hart_class` reports a single joint category (0-6) at every point
inside a closed low (`closed_low_mask` on mean sea level pressure, same as
`executeIndexStd`), NaN elsewhere, from all three Hart parameters at
once -- B, the lower thermal wind VTL, and the upper thermal wind VTU
-- as a single categorical field. See `hart_class`'s own docstring for
the full table, the boundary convention it uses (warm/asymmetric on the
line, not cold/symmetric), and why a joint class carries information
neither parameter alone does. `hart_class` does not use history: it looks
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
    "DEFAULT_DEPTH_HPA",
    "DEFAULT_BLOB_RADIUS_KM",
    "DEFAULT_CENTER_TOL_HPA",
    "LOWER_BAND",
    "UPPER_BAND",
    "BELOW_GROUND_CAP_HPA",
    "ORIENTATION_MODE",
    "B_THRESHOLD_M",
    "HART_B_LAYER_SCALE",
    "MIN_STEERING_MS",
    "MIN_VALID_FRACTION",
    "EARTH_CIRCUMFERENCE_KM",
    "surface_pressure_hpa",
    "mslp_hpa",
    "mask_below_ground",
    "running_extreme_1d",
    "is_global_lon",
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
    "steering_window_mean",
    "half_disk_means",
    "parameter_b_grid",
    "parameter_b_grid_gradient",
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
#: missing.
MISSING_THRESHOLD = -99990.0

#: Half-width (km) of the small window closed_low_mask() uses for its
#: "is this point (about) the minimum of its own neighborhood" candidate
#: test, and the inner edge of the annulus its ring-mean depth test is
#: measured over. Deliberately smaller than RING_RADIUS_KM/RADIUS_KM (Hart's
#: analysis window) -- this is "how big a box finds a low's own local
#: minimum", not the same thing as "how big a box the thermal wind or the
#: depth test integrates over".
MIN_RADIUS_KM = 300.0

#: hPa; closed_low_mask() requires the mean sea level pressure of the
#: annulus between MIN_RADIUS_KM and its own ring_radius_km argument to
#: exceed the point's own MSLP by at least this much before the point
#: counts as being inside a real closed low, not merely a local dip on a
#: monotonic slope (see closed_low_mask's docstring for why a plain
#: "shallower than the far field" window max-minus-min test is not enough
#: by itself). 5 hPa is about the 40 m of 1000 hPa height an earlier,
#: height-based version of this test used (about 8 m per hPa).
DEFAULT_DEPTH_HPA = 5.0

#: Half-width (km) closed_low_mask() dilates its raw (candidate-and-deep)
#: point detections by, so the mask paints a blob of about this radius
#: around each detected low's center instead of a single pixel -- meant to
#: read as "the low is here", not to imply the low's own true physical
#: radius.
DEFAULT_BLOB_RADIUS_KM = 200.0

#: hPa; closed_low_mask() requires a point's own MSLP to be within this
#: of the local minimum MSLP found over MIN_RADIUS_KM before the point is
#: even a *candidate* center -- tight on purpose (much tighter than a
#: low's typical depth) so that a point out on a monotonic slope, which
#: is only ever approximately its own neighborhood's minimum in the single
#: direction the slope descends, does not qualify; the annulus depth test
#: (see DEFAULT_DEPTH_HPA) is what actually distinguishes a real closed
#: low from a slope, but both tests must pass together (see
#: closed_low_mask's docstring). 0.6 hPa is about 5 m of 1000 hPa height.
DEFAULT_CENTER_TOL_HPA = 0.6

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

#: Grid orientation mode used by `half_disk_means` (and, through it,
#: `parameter_b_grid`/`executeB`/`executeHartClass`) and by `gradient_2d`
#: (and `parameter_b_grid_gradient`) when no explicit `mode` argument is
#: given: which way the grid's axes actually run, so that "north" and
#: "east" (and so the sign of B) come out right no matter how a site's
#: grid is laid out.
#:
#:     0: axis 0 (rows) increases northward, axis 1 (columns) increases
#:        eastward -- the plain numpy/mathematical default layout.
#:     1: same axis assignment as 0, but axis 0 increases southward (row
#:        0 is the north edge, as most raster and AWIPS grids are
#:        stored) -- the y-derivative's sign is flipped, and the north
#:        half-disk is taken toward decreasing row index, to compensate.
#:     2: axes swapped relative to 0 -- axis 0 is the eastward direction,
#:        axis 1 the northward one; the field and its gradients are
#:        transposed into mode 0's layout internally, and back on the
#:        way out.
#:     3: axes swapped as in 2, with axis 1 (now the north-south axis)
#:        increasing southward -- mode 2's counterpart to mode 1.
#:
#: Only `half_disk_means` (which half is north, which east) and
#: `gradient_2d` (the sign of a derivative) depend on it; every other
#: function here (`window_mean`, `steering`, the rest of
#: `parameter_b_grid`, `hart_class`) is orientation-free. Mode 1 is confirmed correct on the OPC build (see
#: D2D/README.md's "Orientation verification" procedure) -- it is not
#: merely the untested default here either.
ORIENTATION_MODE = 1

#: Meters; Evans and Hart (2003) extratropical transition **onset**
#: threshold for parameter B -- below this, the thickness field is read as
#: symmetric/tropical-like; at or above it, asymmetric. Hart's own
#: threshold, unchanged from `cps.hart.B_SYMMETRIC_THRESHOLD_M`.
B_THRESHOLD_M = 10.0

#: Dimensionless; multiplies parameter B to rescale it from this module's
#: 925-700 hPa thickness layer (`LOWER_BAND`'s own band, used for
#: consistency with VTL) to a "900-600 hPa equivalent" magnitude, so Hart's
#: 10 m `B_THRESHOLD_M` applies correctly -- see the module docstring's
#: "Parameter B and the joint class" section for the derivation
#: (`ln(900/600)/ln(925/700)`, about 1.4548). Pass `layerScale=1.0` to
#: `executeB`/`executeHartClass` for the raw, unscaled 925-700 hPa value.
HART_B_LAYER_SCALE = math.log(900.0 / 600.0) / math.log(925.0 / 700.0)

#: m/s; `parameter_b_grid` blanks (NaN) any point where the steering-flow
#: speed is below this -- a near-stationary or dead-calm-steering point has
#: no well defined "right of motion", and dividing by a near-zero speed to
#: normalize the motion vector would otherwise amplify noise into a huge,
#: meaningless B. See the module docstring's "Parameter B and the joint
#: class" section, "Motion", for the (window-averaged) steering-flow proxy
#: this guards.
MIN_STEERING_MS = 2.0

#: Dimensionless fraction in (0, 1]; `delta_z` blanks (NaN) any point whose
#: `RADIUS_KM` window has fewer than this fraction of valid (finite,
#: above-ground) cells out of the cells the window geometrically covers --
#: see `delta_z`'s own docstring. Guards against a window that is mostly
#: below ground (e.g. within `RADIUS_KM` of the Greenland ice sheet or the
#: Iceland highlands) silently returning a max-minus-min computed from
#: whatever handful of valid cells happened to survive clipping, which
#: biases the slope without any visible sign that anything was wrong.
MIN_VALID_FRACTION = 0.5

#: km; the Earth's mean circumference, used only by `is_global_lon` to
#: recognize a global lat/lon grid (see the module docstring's "Longitude
#: wrap on global grids" section). Not a claim of geodetic precision --
#: `is_global_lon`'s own 2% tolerance is far looser than the difference
#: between the equatorial and polar circumference, so this single value is
#: adequate for the yes/no "is this grid global" decision it is used for.
EARTH_CIRCUMFERENCE_KM = 40030.0


# ---------------------------------------------------------------------------
# Missing-data handling
# ---------------------------------------------------------------------------


def _missing_mask(*arrays: np.ndarray) -> np.ndarray:
    """True wherever any of `arrays` is non-finite or below
    `MISSING_THRESHOLD`, broadcast together. Kept self-contained here
    rather than imported from elsewhere, since this file must be
    self-contained -- see the module docstring.
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
    into a plain float.
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



def mslp_hpa(pmsl: np.ndarray) -> np.ndarray:
    """Coerce a mean sea level pressure field to hPa, with exactly the
    rule `surface_pressure_hpa` uses: missing input becomes NaN, and a
    field whose finite median is above 2000 is taken to be Pa and
    divided by 100 (sea level is roughly 101325 Pa, and no real MSLP is
    above 2000 hPa), otherwise it is assumed to be hPa already. Used by
    `closed_low_mask`, so `executeHartClass`/`executeIndexStd` accept
    AWIPS's PMSL field in either unit.
    """
    return surface_pressure_hpa(pmsl)

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
    wrap_x: bool = False,
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

    `wrap_x` (default `False`): if `True`, the x-direction pass treats
    axis 1 as cyclic (column 0's left neighbor is the last column, and
    vice versa) instead of clipping at the array edge -- the caller
    (`delta_z`/`window_mean`/`closed_low_mask`, via `is_global_lon`) sets
    this on a genuinely global lat/lon grid, where axis 1 really is a
    full circle of longitude; see the module docstring's "Longitude wrap
    on global grids" section. Implemented by cyclically padding the
    columns -- by the largest half-width actually needed among the rows
    processed in a given group, clamped to `nx // 2` (padding any more
    than half the grid width cannot reach any column that padding by
    `nx // 2` does not already reach) -- before that group's
    `running_extreme_1d` call, then cropping the padding back off. The
    y-direction pass is never wrapped (poles are not a wraparound case).

    Rows are grouped by their (post-clamp) half-width value and processed
    together: for each distinct half-width, the matching rows are pulled
    out with fancy indexing, `running_extreme_1d` is run once along axis
    1 for that whole group, and the result is written back into those
    rows -- so the number of `running_extreme_1d` calls along axis 1 is
    the number of *distinct* half-width values, not the number of rows.
    A second `running_extreme_1d` call along axis 0 (with the single
    scalar `half_y_cells`) then does the y-direction pass over the whole
    array at once.

    Any half-width -- x or y -- is clamped to at most `n - 1` for its own
    axis (length-`n`): a half-width of `n - 1` already makes every
    position's clipped window span the whole axis (`lo = max(0, j -
    (n-1))` is 0 and `hi = min(n-1, j + (n-1))` is `n-1` for every valid
    `j`), so nothing larger can mean anything different. `(n-1)//2` (an
    earlier version of this clamp) is too tight: with a window `w = 2*
    half_width+1`, `half_width = (n-1)//2` gives `w` short of `2*n-1`,
    the window length needed for every position's clip to reach both
    edges, so it silently returned a *smaller*, off-center window at a
    row/column near either edge instead of "the whole axis" as intended.
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
    max_half_x = max(nx - 1, 0)
    half_x = np.clip(half_x, 0, max_half_x)

    max_half_y = max(ny - 1, 0)
    half_y = int(np.clip(int(half_y_cells), 0, max_half_y))

    out_x = np.empty_like(field)
    if wrap_x and nx > 1 and half_x.size:
        pad = min(nx // 2, int(half_x.max()))
        if pad > 0:
            padded_field = np.concatenate([field[:, nx - pad :], field, field[:, :pad]], axis=1)
        else:
            padded_field = field
        for hw in np.unique(half_x):
            hw_eff = min(int(hw), pad)
            rows = np.nonzero(half_x == hw)[0]
            res = running_extreme_1d(padded_field[rows, :], hw_eff, axis=1, kind=kind)
            if pad > 0:
                res = res[:, pad : pad + nx]
            out_x[rows, :] = res
    else:
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
    clipped to `[0, n]`): an O(N) trick whose cost does not depend on
    `half_width`.
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
    wrap_x: bool = False,
):
    """2D sliding-window sum and valid-point count, with the same
    per-row half-width along x (and clamping) that `window_extreme_2d`
    uses -- the box-sum analogue needed for `closed_low_mask`'s ring-mean
    depth test (a box mean over an annulus is a difference of two box
    sums divided by a difference of two box counts, computed by calling
    this function twice with different radii and letting the caller take
    that difference -- see `closed_low_mask`).

    NaN (or otherwise missing, per whatever the caller has already done
    to `field`) entries are excluded from both the sum and the count:
    they contribute 0 to the sum and 0 to the count, so a window's mean
    (`sum / count`, left to the caller) is the mean of only the valid
    points in it, and a window that is entirely missing comes back with
    `count == 0` (the caller must guard the division).

    `wrap_x` (default `False`): same cyclic-column meaning as
    `window_extreme_2d`'s own `wrap_x` -- set on a genuinely global
    lat/lon grid (see the module docstring's "Longitude wrap on global
    grids" section), implemented the same way (cyclic padding by the
    group's needed half-width, clamped to `nx // 2`, cropped back off
    after the box-sum pass). The y-direction pass is never wrapped.

    Rows are grouped by their (post-clamp) half-width value exactly as
    `window_extreme_2d` groups them (same fancy-indexing pass, same
    number of `_box_sum_1d` calls along axis 1 as there are distinct
    half-width values), then a single `_box_sum_1d` call along axis 0
    with the scalar `half_y_cells` finishes the box sum/count over the
    full 2D window. Edges are clipped (unless `wrap_x`), like
    `window_extreme_2d`; any half-width is clamped to at most `n - 1`
    for its own axis, matching `window_extreme_2d`'s own corrected
    clamp (see its docstring for why `(n-1)//2` is too tight).

    Returns `(sum_field, count)`, two arrays the same shape as `field`.
    """
    field = np.asarray(field, dtype=float)
    if field.ndim != 2:
        raise ValueError("field must be 2D")
    ny, nx = field.shape

    half_x = np.asarray(half_x_cells_per_row).astype(int)
    if half_x.shape != (ny,):
        raise ValueError(f"half_x_cells_per_row must have shape ({ny},); got {half_x.shape}")
    max_half_x = max(nx - 1, 0)
    half_x = np.clip(half_x, 0, max_half_x)

    max_half_y = max(ny - 1, 0)
    half_y = int(np.clip(int(half_y_cells), 0, max_half_y))

    valid = np.isfinite(field)
    values = np.where(valid, field, 0.0)
    counts = valid.astype(float)

    sum_x = np.empty_like(field)
    cnt_x = np.empty_like(field)
    if wrap_x and nx > 1 and half_x.size:
        pad = min(nx // 2, int(half_x.max()))
        if pad > 0:
            values_p = np.concatenate([values[:, nx - pad :], values, values[:, :pad]], axis=1)
            counts_p = np.concatenate([counts[:, nx - pad :], counts, counts[:, :pad]], axis=1)
        else:
            values_p, counts_p = values, counts
        for hw in np.unique(half_x):
            hw_eff = min(int(hw), pad)
            rows = np.nonzero(half_x == hw)[0]
            s, c = _box_sum_1d(values_p[rows, :], counts_p[rows, :], hw_eff, axis=1)
            if pad > 0:
                s = s[:, pad : pad + nx]
                c = c[:, pad : pad + nx]
            sum_x[rows, :], cnt_x[rows, :] = s, c
    else:
        for hw in np.unique(half_x):
            rows = np.nonzero(half_x == hw)[0]
            sum_x[rows, :], cnt_x[rows, :] = _box_sum_1d(values[rows, :], counts[rows, :], int(hw), axis=1)

    return _box_sum_1d(sum_x, cnt_x, half_y, axis=0)


# ---------------------------------------------------------------------------
# Distance-to-cells conversion
# ---------------------------------------------------------------------------


def _row_spacing_m(dx: np.ndarray, ny: int, nx: int) -> np.ndarray:
    """Per-row x spacing (meters), shape `(ny,)`: `dx` itself if it is a
    scalar, otherwise the `nanmean` of each row of a `(ny, nx)` `dx`
    pseudo-field. Shared by `cells_per_row` and `half_disk_means`, so
    both convert a distance to a per-row cell count with the same
    cos-latitude scaling. Non-finite or non-positive entries are left
    for the caller to handle.
    """
    dx_arr = np.asarray(dx, dtype=float)
    if dx_arr.ndim == 0:
        return np.full(ny, float(dx_arr))
    if dx_arr.ndim == 2:
        if dx_arr.shape != (ny, nx):
            raise ValueError(f"dx must have shape ({ny}, {nx}); got {dx_arr.shape}")
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            return np.nanmean(dx_arr, axis=1)
    raise ValueError("dx must be a scalar or a 2D array")


def cells_per_row(radius_km: float, dx: np.ndarray, ny: int, nx: int) -> np.ndarray:
    """Per-row half-width (grid cells) for a `radius_km` window along x.

    `dx` (meters) may be a scalar (every row gets the same half-width) or
    a 2D array of shape `(ny, nx)` (AWIPS supplies `dx` as a pseudo-field
    that varies across the grid on most map projections); each row's
    half-width uses that row's own `nanmean` of `dx`. Result is
    `round(radius_km * 1000 / row_dx)`, floored at a minimum of 1 cell (a
    window of half-width 0 would just be the point itself, never useful
    for a max-minus-min diagnostic) and clamped to at most `nx // 2` --
    without this, a row near the pole on a global grid (`row_dx` shrinking
    toward 0 as `cos(lat) -> 0`) can compute a half-width many times
    larger than the grid is wide, which is meaningless and, pre-wrap, was
    only ever silently rescued downstream by `window_extreme_2d`'s/
    `window_sum_2d`'s own per-axis clamp -- see the module docstring's
    "Longitude wrap on global grids" section.
    """
    row_dx = _row_spacing_m(dx, ny, nx)

    radius_m = float(radius_km) * 1000.0
    max_cells = max(int(nx) // 2, 1)
    cells = np.empty(ny, dtype=int)
    for i in range(ny):
        spacing = row_dx[i]
        if not np.isfinite(spacing) or spacing <= 0:
            cells[i] = 1
        else:
            cells[i] = min(max(1, int(round(radius_m / spacing))), max_cells)
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


def is_global_lon(nx: int, dy_m: float) -> bool:
    """True if a lat/lon grid with `nx` columns and (latitude-independent)
    row spacing `dy_m` (meters) is, to within 2%, a global grid running
    all the way around in longitude -- see the module docstring's
    "Longitude wrap on global grids" section for why `dy_m` (not `dx`) is
    the right spacing to test with.

    Detection: for a regular lat/lon grid with equal angular spacing in
    both directions (the overwhelmingly common case -- e.g. a 1 degree x
    1 degree or 0.25 degree x 0.25 degree grid), `dy_m` (constant across
    every row) is the same physical distance as `dx` at the equator. If
    the grid's `nx` columns span the full 360 degrees of longitude at
    that same angular spacing, then `nx * dy_m` equals the Earth's
    circumference (`EARTH_CIRCUMFERENCE_KM`); a regional grid's `nx`
    columns span less than 360 degrees, so the product falls well short.
    `abs(nx * dy_m - circumference) <= 0.02 * circumference` is the
    global/regional decision.

    Returns False for a non-finite, non-positive `dy_m`, or `nx <= 0`
    (nothing to test).
    """
    dy = float(dy_m)
    if not np.isfinite(dy) or dy <= 0 or int(nx) <= 0:
        return False
    circumference_m = EARTH_CIRCUMFERENCE_KM * 1000.0
    span_m = float(nx) * dy
    return abs(span_m - circumference_m) <= 0.02 * circumference_m


# ---------------------------------------------------------------------------
# dZ and the band slope
# ---------------------------------------------------------------------------


def delta_z(
    z: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    radius_km: float,
    global_lon: bool | None = None,
) -> np.ndarray:
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

    `global_lon` (default `None`) decides whether the x-direction window
    wraps cyclically at the longitude seam: `None` auto-detects with
    `is_global_lon(nx, dy)`, `True`/`False` forces the decision either
    way -- see the module docstring's "Longitude wrap on global grids"
    section. Without the wrap, a point within `radius_km` of column 0 or
    the last column of a genuinely global grid sees its window clipped
    at the array edge instead of continuing around the planet, silently
    shrinking (and biasing) `dZ` there.

    A point's `dZ` is also forced to NaN if fewer than `MIN_VALID_FRACTION`
    of the cells its own window geometrically covers are valid (finite)
    `z` -- computed as a valid-cell count and a total-cell count, both
    from a single `window_sum_2d` call on a 0/1 valid-cell indicator (an
    indicator array has no NaN of its own, so the sum it returns is the
    valid-cell count and the count it returns is the total cell count the
    window covers, including cells shrunk off by the domain edge). This
    guards a window that is mostly below ground or otherwise missing
    (e.g. within `RADIUS_KM` of the Greenland ice sheet or the Iceland
    highlands) from returning a max-minus-min computed from whatever
    handful of valid cells happened to survive clipping -- a result that
    would otherwise look like an ordinary, fully-sampled `dZ` with no
    visible sign that most of its window was missing.
    """
    z_arr = np.asarray(z, dtype=float)
    ny, nx = z_arr.shape
    bad = _missing_mask(z_arr)
    z_clean = np.where(bad, np.nan, z_arr)

    half_x = cells_per_row(radius_km, dx, ny, nx)
    half_y = cells_y(radius_km, dy)

    dy_m = float(np.nanmean(np.asarray(dy, dtype=float)))
    wrap = is_global_lon(nx, dy_m) if global_lon is None else bool(global_lon)

    z_max = window_extreme_2d(z_clean, half_x, half_y, "max", wrap_x=wrap)
    z_min = window_extreme_2d(z_clean, half_x, half_y, "min", wrap_x=wrap)
    dz = z_max - z_min

    valid_indicator = np.where(bad, 0.0, 1.0)
    valid_count, total_count = window_sum_2d(valid_indicator, half_x, half_y, wrap_x=wrap)
    with np.errstate(invalid="ignore", divide="ignore"):
        valid_fraction = np.where(total_count > 0, valid_count / total_count, 0.0)
    dz = np.where(valid_fraction < MIN_VALID_FRACTION, np.nan, dz)

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
    pmsl: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    min_radius_km: float = MIN_RADIUS_KM,
    ring_radius_km: float = RADIUS_KM,
    depth_hpa: float = DEFAULT_DEPTH_HPA,
    blob_radius_km: float = DEFAULT_BLOB_RADIUS_KM,
    center_tol_hpa: float = DEFAULT_CENTER_TOL_HPA,
    global_lon: bool | None = None,
) -> np.ndarray:
    """Boolean mask: True within `blob_radius_km` of a real closed low's
    center in the mean sea level pressure field `pmsl` (passed by
    `executeHartClass`/`executeIndexStd` from AWIPS's PMSL field). `pmsl`
    may be in Pa or hPa: it is normalized with `mslp_hpa` (the same
    median rule `surface_pressure_hpa` uses) before anything else, and
    `depth_hpa`/`center_tol_hpa` are always hPa.

    Why MSLP: it is one field, the same surface the forecaster already
    contours, so the closed low this mask finds is the closed low drawn
    on the chart; it is defined everywhere (reduced to sea level over
    terrain), so it needs no below-ground masking of its own; unlike
    1000 hPa height it involves no extrapolation below sea level inside
    a deep low; and the depth test reads directly in pressure (5 hPa by
    default). Terrain blanking of the products that use this mask comes
    from their thermal-wind band levels, which are NaN below ground
    (see `mask_below_ground`), not from the mask itself.

    A plain "is this point close to the local minimum of a box that also
    has a big max-minus-min" test (an earlier version of this function)
    turns out to accept far more than closed lows: on a *uniform slope*
    (no low at all -- e.g. a steady 5-8 hPa per 1000 km pressure gradient
    across a front) every point is, to within a fraction of a hPa,
    already the minimum of its own neighborhood in the single direction
    the slope descends, and the same window's max-minus-min is large
    simply because the slope has covered a lot of pressure by the time
    it reaches the far edge of a 500 km box -- so both tests passed
    *everywhere*, not just at an actual low. This function instead uses
    two tests that a monotonic slope cannot satisfy simultaneously:

    1. **Candidate test**: `p - window_min(p, min_radius_km) <=
       center_tol_hpa` -- the point is (within a tight tolerance) the
       minimum of its own `min_radius_km` neighborhood. `center_tol_hpa`
       is deliberately tight (much tighter than a real low's depth) so
       this alone is a weak filter, not a claim of "this is a low".
    2. **Depth test**: `ring_mean - p >= depth_hpa`, where `ring_mean`
       is the mean MSLP of the *annulus* between `min_radius_km` and
       `ring_radius_km` around the point (computed from two box sums via
       `window_sum_2d`: `(sum_outer - sum_inner) / (count_outer -
       count_inner)`). On a closed low, the annulus sits in the
       surrounding higher pressure and exceeds the center by roughly the
       low's depth. On a uniform slope, the annulus is centered on the
       same point as the candidate itself, so its mean pressure equals
       the point's own pressure to first order (a symmetric ring around
       a point on a linear slope averages back to that point's own
       value) -- the depth comes back ~0 and the test correctly rejects
       it.

    Points passing both tests are `raw` detections (typically a single
    pixel, or a couple, right at each low's true minimum); the returned
    mask is `raw` dilated by `window_extreme_2d(..., kind="max")` over a
    `blob_radius_km` half-width, so each detected low paints a blob of
    about that radius on the map instead of a single point (this radius
    is about "how big to paint the low", unrelated to the low's own true
    physical size).

    NaN-safe throughout: any comparison against a NaN intermediate value
    is False in numpy already, but missing input (see `_missing_mask`) is
    also explicitly excluded before dilation, so a bad `pmsl` value can
    never masquerade as "yes, this is a low center."

    `global_lon` (default `None`) is the same longitude-wrap decision
    `delta_z`/`window_mean` take: `None` auto-detects with
    `is_global_lon(nx, dy)`, `True`/`False` forces it -- see the module
    docstring's "Longitude wrap on global grids" section. The one
    decision is made once and used for every sliding-window call this
    function makes (the candidate/local-min pass, both box sums of the
    ring-mean depth test, and the final dilation), so a low near the
    seam of a global grid is found and painted consistently on both
    sides of it.
    """
    p_arr = mslp_hpa(pmsl)
    ny, nx = p_arr.shape
    bad = _missing_mask(p_arr)
    p_clean = np.where(bad, np.nan, p_arr)

    dy_m = float(np.nanmean(np.asarray(dy, dtype=float)))
    wrap = is_global_lon(nx, dy_m) if global_lon is None else bool(global_lon)

    half_x_min = cells_per_row(min_radius_km, dx, ny, nx)
    half_y_min = cells_y(min_radius_km, dy)
    local_min = window_extreme_2d(p_clean, half_x_min, half_y_min, "min", wrap_x=wrap)

    with np.errstate(invalid="ignore"):
        candidate = (p_clean - local_min) <= float(center_tol_hpa)

    half_x_ring = cells_per_row(ring_radius_km, dx, ny, nx)
    half_y_ring = cells_y(ring_radius_km, dy)
    sum_outer, count_outer = window_sum_2d(p_clean, half_x_ring, half_y_ring, wrap_x=wrap)
    sum_inner, count_inner = window_sum_2d(p_clean, half_x_min, half_y_min, wrap_x=wrap)

    ring_sum = sum_outer - sum_inner
    ring_count = count_outer - count_inner
    with np.errstate(invalid="ignore", divide="ignore"):
        ring_mean = np.where(ring_count > 0, ring_sum / ring_count, np.nan)
        depth_ok = (ring_mean - p_clean) >= float(depth_hpa)

    valid = ~bad & np.isfinite(local_min) & np.isfinite(ring_mean)
    raw = (candidate & depth_ok & valid).astype(float)

    half_x_blob = cells_per_row(blob_radius_km, dx, ny, nx)
    half_y_blob = cells_y(blob_radius_km, dy)
    dilated = window_extreme_2d(raw, half_x_blob, half_y_blob, "max", wrap_x=wrap)
    return dilated > 0.5


# ---------------------------------------------------------------------------
# Parameter B (thermal asymmetry) and the joint class
# ---------------------------------------------------------------------------


def b_geometry_km(radius_km: float) -> float:
    """`8*radius_km/(3*pi)` -- the geometric constant that converts a
    uniform thickness gradient into Hart's right-minus-left half-disk
    mean difference (the half-disk centroid sits `4R/(3*pi)` from the
    center, so the two centroids are `8R/(3*pi)` apart). Used by
    `parameter_b_grid_gradient`, the first-order form kept for
    comparison; `parameter_b_grid` itself does not need it (see the
    module docstring's "Parameter B and the joint class" section). Computed from
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
    actually laid out in (see `ORIENTATION_MODE`, module level, for the
    full description of the four conventions); `None` (the default)
    means "use `ORIENTATION_MODE`", read fresh from the module on every
    call so a monkeypatch takes effect without touching this function.
    Modes 2 and 3 (transposed axes) transpose `field`/`dx`/`dy` on the
    way in and transpose both result arrays back on the way out --
    `d(field)/dx` and `d(field)/dy` are themselves scalar fields (not
    vector components tied to an axis), so transposing them back needs
    no swap between the two, only a reshape. Modes 1 and 3 negate the
    y-derivative (axis 0 increasing southward instead of northward).

    Missing values (see `_missing_mask`) in `field`, `dx`, or `dy` are set
    to NaN before differencing and any resulting NaN (including the
    immediate-neighbor contamination `np.gradient`'s centered-difference
    stencil unavoidably causes) is left as NaN in the output.

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


def window_mean(
    field: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    radius_km: float,
    global_lon: bool | None = None,
) -> np.ndarray:
    """NaN-aware box mean of `field`, half-width `radius_km`, at every
    grid point -- `window_sum_2d`'s sum divided by its count, using the
    same per-row `dx`/scalar `dy` half-width conversion (`cells_per_row`,
    `cells_y`) `delta_z`/`closed_low_mask` use. NaN where the window's
    valid-point count is 0 (every point in it was missing).

    `global_lon` (default `None`) is the same longitude-wrap decision
    `delta_z` takes: `None` auto-detects with `is_global_lon(nx, dy)`,
    `True`/`False` forces it -- see the module docstring's "Longitude
    wrap on global grids" section.
    """
    field = np.asarray(field, dtype=float)
    ny, nx = field.shape
    half_x = cells_per_row(radius_km, dx, ny, nx)
    half_y = cells_y(radius_km, dy)
    dy_m = float(np.nanmean(np.asarray(dy, dtype=float)))
    wrap = is_global_lon(nx, dy_m) if global_lon is None else bool(global_lon)
    total, count = window_sum_2d(field, half_x, half_y, wrap_x=wrap)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / count, np.nan)
    return mean


def half_disk_means(
    field: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    radius_km: float,
    global_lon: bool | None = None,
    mode: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """NaN-aware means of `field` over the north, south, east and west
    half-disks of radius `radius_km` centered on every grid point.
    Returns `(mean_north, mean_south, mean_east, mean_west)`, each the
    same shape as `field`. A half-disk is the disk split by the line
    through its center perpendicular to the direction it is named for:
    the north half-disk is every point of the disk north of the
    east-west line through the center, the east half-disk every point
    east of the north-south line, and so on. These are the building
    blocks of `parameter_b_grid`'s semicircle difference (see the module
    docstring's "Parameter B and the joint class" section).

    Discretization. The disk is the set of grid points whose local
    planar offset `(x, y)` from the center satisfies `x**2 + y**2 <=
    R**2`, with `y = j * dy` for row offset `j` and `x` measured in the
    source row's own `dx`. Row by row: for each row offset `j` with
    `|j * dy| <= R`, the disk's chord half-width along x is `w_j =
    sqrt(R**2 - (j*dy)**2)`, converted to whole cells separately for
    every row as `floor(w_j / row_dx)` with the same per-row `dx`
    (`nanmean` of that row of `dx`, so the cos-latitude growth of the
    cell count toward the poles is followed exactly as `cells_per_row`
    follows it). The x-direction box sum of that half-width, and the
    partial sums from the center column to `+w_j` (east) and from
    `-w_j` to the center (west), all come from a single cumulative sum
    along x computed once; each row offset then only gathers from it
    and shifts the result by `j` rows into the north (`j > 0`) or south
    (`j < 0`) accumulators. The center row (`j = 0`) is split half and
    half between north and south, and the center column half and half
    between east and west, so `north + south` and `east + west` each
    cover the whole disk exactly once. Cost is O(number of row offsets
    x N), vectorized, with no Python loop over grid points (about 18
    row offsets on a 0.25 degree grid with R = 500 km).

    Orientation. Row offset `j > 0` always means **north**. Which way
    that is in array terms follows `ORIENTATION_MODE` (or the explicit
    `mode` argument, same four conventions as `gradient_2d`): in modes 0
    and 2 north is increasing row index (after the transpose modes 2
    and 3 apply), in modes 1 and 3 (row 0 is the north edge, the AWIPS
    layout) north is decreasing row index. Axis 1 (after any transpose)
    always increases eastward, so east is increasing column index in
    every mode. Modes 2 and 3 transpose `field`, `dx`, `dy` on the way
    in and the four results back on the way out.

    Area weighting and missing data. Every cell is weighted by its own
    row's `dx` (its area, since `dy` is the same for every row), the
    gridded counterpart of the cos-latitude weighting `cps.hart`'s
    `weighted_mean` uses: on a lat/lon grid the cells in the poleward
    rows of the disk are smaller, and an unweighted mean would count
    them too heavily. With a scalar `dx` every weight is 1. NaN or
    otherwise missing input (see `_missing_mask`) contributes to neither
    the weighted sum nor the weight total, as in `window_sum_2d`, so each
    result is the area-weighted mean of the valid points in that
    half-disk; a half-disk with no valid point at all is NaN.

    Edges and wrap. `global_lon` is the same longitude-wrap decision
    `delta_z`/`window_mean` take (`None` auto-detects with
    `is_global_lon`; see the module docstring's "Longitude wrap on
    global grids" section): on a global grid the x sums wrap cyclically
    across the seam, otherwise they are clipped at the array edge. Rows
    beyond the first or last row (the poles on a global grid, the edge
    of a regional one) are dropped: the half-disk shrinks there, it is
    never reflected, consistent with every other window in this module.
    The per-row half-width is clamped to `(nx - 1) // 2` when wrapping
    (so a near-pole row never counts a column twice) and to `nx - 1`
    otherwise.
    """
    field = np.asarray(field, dtype=float)
    if field.ndim != 2:
        raise ValueError("field must be 2D")
    dx_arr = np.asarray(dx, dtype=float)
    dy_arr = np.asarray(dy, dtype=float)

    if mode is None:
        mode = ORIENTATION_MODE
    mode = int(mode)
    if mode not in (0, 1, 2, 3):
        raise ValueError(f"mode must be 0, 1, 2, or 3; got {mode!r}")
    transposed = mode in (2, 3)
    if transposed:
        field = field.T
        if dx_arr.ndim == 2:
            dx_arr = dx_arr.T
        if dy_arr.ndim == 2:
            dy_arr = dy_arr.T
    # Row-index step that moves one row north.
    north_step = -1 if mode in (1, 3) else 1

    ny, nx = field.shape
    row_dx = _row_spacing_m(dx_arr, ny, nx)
    good_dx = np.isfinite(row_dx) & (row_dx > 0)

    # Area weight of one cell in each row (proportional to that row's
    # dx; dy is the same for every row), normalized to at most 1.
    if good_dx.any():
        row_weight = np.where(good_dx, row_dx, 0.0) / float(np.max(row_dx[good_dx]))
    else:
        row_weight = np.ones(ny)
    bad = _missing_mask(field)
    counts = np.where(bad, 0.0, row_weight[:, np.newaxis])
    values = np.where(bad, 0.0, field) * counts

    with np.errstate(invalid="ignore"):
        dy_m = float(np.nanmean(dy_arr))
    wrap = is_global_lon(nx, dy_m) if global_lon is None else bool(global_lon)

    radius_m = float(radius_km) * 1000.0
    if np.isfinite(dy_m) and dy_m > 0 and radius_m > 0:
        j_max = min(int(math.floor(radius_m / dy_m + 1e-9)), ny - 1)
    else:
        j_max = 0

    # Per-row x half-width (cells) for every row offset 0..j_max.
    half_cap = max((nx - 1) // 2, 0) if wrap else max(nx - 1, 0)
    safe_dx = np.where(good_dx, row_dx, 1.0)
    offsets_m = np.arange(j_max + 1) * (dy_m if j_max > 0 else 0.0)
    chord_m = np.sqrt(np.maximum(radius_m ** 2 - offsets_m ** 2, 0.0))
    half = np.floor(chord_m[:, np.newaxis] / safe_dx[np.newaxis, :] + 1e-9)
    half = np.where(good_dx[np.newaxis, :], half, 0.0)
    half = np.clip(half, 0, half_cap).astype(np.intp)  # shape (j_max+1, ny)

    # Pad the columns once by the largest half-width needed: cyclically
    # on a global grid, with zeros (no value, no count) otherwise, so
    # every gather below is in bounds and clipping falls out for free.
    pad = int(half.max()) if half.size else 0
    if pad > 0:
        if wrap:
            values_p = np.concatenate([values[:, nx - pad :], values, values[:, :pad]], axis=1)
            counts_p = np.concatenate([counts[:, nx - pad :], counts, counts[:, :pad]], axis=1)
        else:
            zeros = np.zeros((ny, pad))
            values_p = np.concatenate([zeros, values, zeros], axis=1)
            counts_p = np.concatenate([zeros, counts, zeros], axis=1)
    else:
        values_p, counts_p = values, counts
    width = values_p.shape[1] + 1
    cs_v = np.zeros((ny, width))
    cs_c = np.zeros((ny, width))
    np.cumsum(values_p, axis=1, out=cs_v[:, 1:])
    np.cumsum(counts_p, axis=1, out=cs_c[:, 1:])
    flat_v = cs_v.ravel()
    flat_c = cs_c.ravel()

    # Flat index of the cumulative-sum entry just left of each point's
    # own column; the strict-east sum from a gather at `hi` is
    # cs[hi] - cs[center + 1], so fold the constant part (plus half the
    # center column) in once here.
    base = np.arange(ny, dtype=np.intp)[:, np.newaxis] * width + (np.arange(nx, dtype=np.intp) + pad)[np.newaxis, :]
    east_const_v = 0.5 * values - cs_v[:, pad + 1 : pad + 1 + nx]
    east_const_c = 0.5 * counts - cs_c[:, pad + 1 : pad + 1 + nx]

    north_v = np.zeros((ny, nx))
    south_v = np.zeros((ny, nx))
    east_v = np.zeros((ny, nx))
    north_c = np.zeros((ny, nx))
    south_c = np.zeros((ny, nx))
    east_c = np.zeros((ny, nx))

    # Work buffers reused across row offsets (allocation, not
    # arithmetic, dominates at this size).
    idx_hi = np.empty((ny, nx), dtype=np.intp)
    idx_lo = np.empty((ny, nx), dtype=np.intp)
    hi_v = np.empty((ny, nx))
    hi_c = np.empty((ny, nx))
    full_v = np.empty((ny, nx))
    full_c = np.empty((ny, nx))
    e_v = np.empty((ny, nx))
    e_c = np.empty((ny, nx))

    for j in range(j_max + 1):
        h = half[j][:, np.newaxis]
        np.add(base, h + 1, out=idx_hi)
        np.subtract(base, h, out=idx_lo)
        # Every index is in bounds by construction (the padding);
        # mode="clip" only lets `take` write straight into `out`.
        np.take(flat_v, idx_hi, out=hi_v, mode="clip")
        np.take(flat_c, idx_hi, out=hi_c, mode="clip")
        np.take(flat_v, idx_lo, out=full_v, mode="clip")
        np.take(flat_c, idx_lo, out=full_c, mode="clip")
        np.subtract(hi_v, full_v, out=full_v)
        np.subtract(hi_c, full_c, out=full_c)
        np.add(hi_v, east_const_v, out=e_v)
        np.add(hi_c, east_const_c, out=e_c)
        if j == 0:
            full_v *= 0.5
            full_c *= 0.5
            north_v += full_v
            south_v += full_v
            north_c += full_c
            south_c += full_c
            east_v += e_v
            east_c += e_c
            continue
        # Output row i takes source row i + north_step*j into its north
        # half and source row i - north_step*j into its south half.
        up_out, up_src = (slice(0, ny - j), slice(j, ny))
        dn_out, dn_src = (slice(j, ny), slice(0, ny - j))
        n_out, n_src, s_out, s_src = (
            (up_out, up_src, dn_out, dn_src) if north_step == 1 else (dn_out, dn_src, up_out, up_src)
        )
        north_v[n_out] += full_v[n_src]
        north_c[n_out] += full_c[n_src]
        south_v[s_out] += full_v[s_src]
        south_c[s_out] += full_c[s_src]
        east_v[up_out] += e_v[up_src]
        east_v[dn_out] += e_v[dn_src]
        east_c[up_out] += e_c[up_src]
        east_c[dn_out] += e_c[dn_src]

    # West is the whole disk minus the east half (both carry the center
    # column at half weight). Reuse the work buffers for it.
    west_v = np.add(north_v, south_v, out=hi_v)
    west_v -= east_v
    west_c = np.add(north_c, south_c, out=hi_c)
    west_c -= east_c

    # A half-disk whose total weight is zero up to rounding (the west
    # sums are differences) has no valid point: NaN. Divide in place.
    tiny = 1e-9
    means = []
    for v, c in ((north_v, north_c), (south_v, south_c), (east_v, east_c), (west_v, west_c)):
        empty = c <= tiny
        np.divide(v, c, out=v, where=~empty)
        v[empty] = np.nan
        means.append(v)
    means = tuple(means)
    if transposed:
        means = tuple(m.T for m in means)
    return means


def steering(u_levels, v_levels) -> tuple[np.ndarray, np.ndarray]:
    """`(u_s, v_s)`: the elementwise (NaN-aware) mean of a list of u
    arrays and a list of v arrays, the steering-flow proxy for a storm's
    motion at every grid point (see the module docstring's "Parameter B
    and the joint class" section, "Motion") -- typically the 850/700/500/300 hPa
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


def steering_window_mean(
    u_s: np.ndarray,
    v_s: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    radius_km: float,
    global_lon: bool | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Area-average `steering`'s pointwise `(u_s, v_s)` output over a
    `radius_km` window (via `window_mean`), one component at a time --
    see the module docstring's "Parameter B and the joint class" section,
    "Motion", for why this step is necessary before the result is used
    as a motion proxy.

    `steering`'s pointwise vertical mean is, by itself, the deep-layer
    wind *at that point* -- inside a developed cyclone that is
    dominated by the vortex's own circulation, not by the larger-scale
    flow that actually carries the storm along. Averaging each
    component horizontally over the same `radius_km` (500 km) analysis
    window `delta_z`/parameter B's own half-disk means use lets a
    roughly axisymmetric vortex's own tangential wind cancel out over
    the window (it circles the center, so its horizontal mean over a
    large enough symmetric window is small), leaving the environmental
    steering flow the vortex is embedded in and actually steered by.

    `radius_km` should match the `radius_km` the caller's own B
    computation uses (`executeB`/`executeHartClass` both pass the same
    `radiusKm` here as they pass to `parameter_b_grid`), so the motion
    proxy and the thickness half-disks agree on what "the analysis
    window" means. `global_lon` is passed straight through to
    `window_mean` (see its own docstring and the module docstring's
    "Longitude wrap on global grids" section).

    Returns `(u_s_mean, v_s_mean)`, each the same shape as the input.
    """
    u_mean = window_mean(u_s, dx, dy, radius_km, global_lon=global_lon)
    v_mean = window_mean(v_s, dx, dy, radius_km, global_lon=global_lon)
    return u_mean, v_mean


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
    """Hart's parameter B at every grid point, from semicircle means --
    see the module docstring's "Parameter B and the joint class" section.

    `thickness` is a layer thickness field (meters, e.g. 700 hPa height
    minus 925 hPa height). `half_disk_means` gives its mean over the
    north, south, east and west half-disks of radius `radius_km` around
    every point. With the unit motion vector `m = (mx, my) = (u_s, v_s)
    / speed` (east, north components), the right-minus-left semicircle
    difference is

        ZR - ZL = mx * (mean_south - mean_north) + my * (mean_east - mean_west)

    (moving north, `m = (0, 1)`, the right half is the east half; moving
    east, `m = (1, 0)`, the right half is the south half), and

        B = h * (ZR - ZL) * layer_scale

    with `h = sign(hemisphere)` (exact zero treated as `+1`, the
    Northern Hemisphere). `hemisphere` may be a scalar or a 2D array
    (the coriolis pseudo-field), so a grid straddling the equator gets
    the right sign on each side.

    Why the two axis-aligned splits are enough: write the thickness
    field about the point as a sum of azimuthal harmonics `f_k(r)
    cos(k*theta - phi_k)`. Harmonic `k` contributes nothing to any
    semicircle difference when `k` is even (including the axisymmetric
    `k = 0` part), and `(4/pi) * sin(k*pi/2) / k` times its area-mean
    amplitude when `k` is odd. For `k = 1` that contribution varies with
    the motion direction exactly as `cos` and `sin` of the heading, so
    the combination above, which interpolates between the north-south
    and east-west splits, is exact for any wavenumber-one pattern about
    the point: a uniform gradient (for which it reduces to the
    `8*R/(3*pi)` gradient form of `parameter_b_grid_gradient`) and the
    storm-scale dipole that form under-reads alike. Odd harmonics
    `k >= 3` are not captured correctly by the interpolation (it
    evaluates them only along the two axes); their weight in Hart's
    semicircle difference is bounded by `(4/pi)/k` times their
    area-mean amplitude (about 0.42 for `k = 3`, against 1.27 for
    `k = 1`), which is the size of the error they can introduce.

    `u_s`/`v_s` (m/s) are the storm's motion proxy at each point --
    typically `steering`'s output *after* `steering_window_mean` (both
    `executeB` and `executeHartClass` do this), so the vortex's own
    circulation does not steer its own motion proxy; see the module
    docstring's "Parameter B and the joint class" section, "Motion".

    Sign convention: identical to `cps.hart.parameter_b` -- warm (thick)
    air to the right of motion in the Northern Hemisphere, or to the
    left in the Southern, is positive.

    NaN wherever `speed < min_speed` (see `MIN_STEERING_MS`), wherever
    `thickness` itself is missing at the point (below ground, for
    example), or wherever a half-disk has no valid thickness at all.
    """
    thickness = np.asarray(thickness, dtype=float)
    bad_thk = _missing_mask(thickness)
    thickness_clean = np.where(bad_thk, np.nan, thickness)

    mean_n, mean_s, mean_e, mean_w = half_disk_means(thickness_clean, dx, dy, radius_km)

    u_s_arr = np.asarray(u_s, dtype=float)
    v_s_arr = np.asarray(v_s, dtype=float)
    bad_uv = _missing_mask(u_s_arr, v_s_arr)
    u_s_clean = np.where(bad_uv, np.nan, u_s_arr)
    v_s_clean = np.where(bad_uv, np.nan, v_s_arr)

    speed = np.hypot(u_s_clean, v_s_clean)
    with np.errstate(invalid="ignore", divide="ignore"):
        mx = u_s_clean / speed
        my = v_s_clean / speed
        right_minus_left = mx * (mean_s - mean_n) + my * (mean_e - mean_w)

    hemi = np.asarray(hemisphere, dtype=float)
    h_sign = np.sign(hemi)
    h_sign = np.where(h_sign == 0, 1.0, h_sign)

    b = h_sign * right_minus_left * float(layer_scale)

    with np.errstate(invalid="ignore"):
        invalid = (
            ~np.isfinite(speed)
            | (speed < float(min_speed))
            | ~np.isfinite(right_minus_left)
            | bad_thk
        )
    return np.where(invalid, np.nan, b)


def parameter_b_grid_gradient(
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
    """The earlier, first-order form of gridded parameter B, kept for
    comparison with `parameter_b_grid` (same signature, same motion,
    hemisphere, layer-scale and `min_speed` conventions). It replaces
    Hart's semicircle difference with `(8*R/(3*pi))` times the
    window-mean thickness gradient projected on the right-hand normal of
    motion. That is exact for a uniform thickness gradient but reads a
    storm-scale wavenumber-one asymmetry at only about 60% of Hart's
    semicircle difference (the gradient at and near the point
    under-represents structure that peaks a few hundred km out); see the
    module docstring's "Parameter B and the joint class" section.
    `executeB` and `executeHartClass` use `parameter_b_grid`, not this.

    `thickness` is a layer thickness field (meters, e.g. 700 hPa height
    minus 925 hPa height). Its gradient (`gradient_2d`) is computed once,
    then each component is box-averaged (`window_mean`) over a
    `radius_km` window -- computing the gradient first and then
    window-meaning each component, rather than differencing a
    window-meaned thickness, so a locally noisy `thickness` is smoothed
    the same way `dZ`'s own window extrema effectively are elsewhere in
    this module.

    `u_s`/`v_s` (m/s) are the storm's motion at each point -- typically
    `steering`'s output *after* `steering_window_mean` (both `executeB`
    and `executeHartClass` call `steering` then `steering_window_mean`
    in sequence before reaching this function); passing `steering`'s
    raw, un-window-averaged output instead reintroduces the vortex's own
    circulation into the motion proxy this function's normal direction
    is built from -- see the module docstring's "Parameter B and the
    joint class" section, "Motion". `speed = hypot(u_s, v_s)`; the
    right-hand normal
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
    thermal wind), and VTU (upper thermal wind) -- combined into a
    single categorical field (see the module docstring's "Relation to
    Hart's storm-centered diagrams" section for why a single joint class
    carries information neither parameter alone does).

    NaN outside `mask` (typically `closed_low_mask` on MSLP)
    or wherever any of `B`, `vtl`, `vtu` is not finite -- `B` is NaN
    whenever the steering-flow speed is below `MIN_STEERING_MS` (a
    near-stationary or dead-calm-steering point; see `parameter_b_grid`),
    which is rare but not impossible for a slow-moving or recurving
    system, and this is documented here rather than silently treated as
    some default category.

    Otherwise, one of:

        Code  Name                                         B      lower VT  upper VT
        0     symmetric deep warm core                    <= thr  >= 0      >= 0
        1     symmetric shallow warm core                 <= thr  >= 0      <  0
        2     asymmetric deep warm core                   >  thr  >= 0      >= 0
        3     asymmetric shallow warm core                >  thr  >= 0      <  0
        4     asymmetric cold core                        >  thr  <  0      < 0 (row 6 takes lower cold, upper warm first)
        5     symmetric cold core                         <= thr  <  0      < 0 (row 6 takes lower cold, upper warm first)
        6     shallow cold core (lower cold, upper warm)   any     <  0      >= 0

    Row 6 is checked first and takes precedence over rows 4 and 5
    wherever `lower VT < 0 and upper VT >= 0` at once (see "Ordering"
    below); rows 4/5's own `upper VT` cell is therefore always `< 0` in
    practice, never "any".

    Tie convention: a thermal wind term of exactly 0 counts as warm
    (`>= 0`), and B of exactly `b_threshold` (10 m by default) counts as
    symmetric (`<= b_threshold`).

    Boundary convention: **B is asymmetric at `B > b_threshold` (10 m by
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
    lines*, not a neutral band: Hart's own thresholds (10 m for
    B, 0 m for VTL/VTU) are themselves strict lines with no neutral zone,
    and the continuous `HB`/`HVTL`/`HVTU` fields already carry the
    magnitude a forecaster needs to judge "how marginal" a call at the
    line actually is -- a categorical field's job is to draw the line
    Hart drew, not to soften it with a second, invented threshold.

    Ordering / precedence: row 6 (shallow cold core: cold at low
    levels, warm aloft) is checked before rows 4 and 5, so it wins the
    corner of `(B, vtl, vtu)` space that would otherwise also satisfy
    "lower VT negative" -- a genuine shallow cold core is a different
    structure from an asymmetric or symmetric cold core (which are cold at
    *both* levels), not a third way of being one of those two,
    regardless of B. Every other row is a disjoint partition of the
    remaining `(vtl >= 0 or < 0) x (vtu >= 0 or < 0)` quadrants by the
    B line, so the six remaining codes plus row 6 exhaust the space
    with no gaps and no overlaps for finite input.

    Rationale for the code numbering: codes rise, in order, along a
    typical extratropical transition -- 0 (symmetric deep warm core,
    the tropical-cyclone-like starting state) to 2 (asymmetric, still deep
    warm, B has crossed 10 m: Evans and Hart's onset) to 3 (asymmetric
    shallow warm core, the upper thermal wind has gone negative first)
    to 4 (asymmetric cold core, VTL has now gone negative too: Evans and
    Hart's completion). A warm seclusion is a storm that reaches 4 and
    then re-forms a warm core at low levels while still asymmetric, i.e.
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
            (vtl < 0.0) & (vtu >= 0.0),                    # 6 shallow cold core (checked first)
            (B <= thr) & (vtl >= 0.0) & (vtu >= 0.0),      # 0 symmetric deep warm core
            (B <= thr) & (vtl >= 0.0) & (vtu < 0.0),       # 1 symmetric shallow warm core
            (B > thr) & (vtl >= 0.0) & (vtu >= 0.0),       # 2 asymmetric deep warm core
            (B > thr) & (vtl >= 0.0) & (vtu < 0.0),        # 3 asymmetric shallow warm core
            (B > thr) & (vtl < 0.0),                        # 4 asymmetric cold core
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
    pmsl, z925, z850, z700, z500, z400, z300,
    u850, v850, u700, v700, u500, v500, u300, v300,
    psfc, coriolis, dx, dy,
    radiusKm=RADIUS_KM,
    bThresholdM=B_THRESHOLD_M,
    layerScale=HART_B_LAYER_SCALE,
    depthHpa=DEFAULT_DEPTH_HPA,
    blobKm=DEFAULT_BLOB_RADIUS_KM,
    capHpa=BELOW_GROUND_CAP_HPA,
):
    """AWIPS derived-parameter entry point for HCPSclass (cps_HCPSclass.xml):
    the joint Hart CPS class -- see `hart_class`'s own docstring for the
    full 7-code table, the boundary convention, and the ordering
    rationale, and the module docstring's "Parameter B and the joint
    class" and "Relation to Hart's storm-centered diagrams" sections for
    why a single joint class carries information neither parameter alone
    does.

    Computes the lower thermal wind (`LOWER_BAND`, 925/850/700 hPa) and
    upper thermal wind (`UPPER_BAND`, 500/400/300 hPa, both via
    `thermal_wind_grid`), parameter B (the right-minus-left semicircle
    difference of 925-700 hPa thickness across the window-averaged
    steering flow, via `steering`, `steering_window_mean`, and
    `parameter_b_grid` -- same method as `executeB`), and
    `closed_low_mask` on `pmsl` (same mask `executeIndexStd` uses), then
    combines all three with `hart_class`.

    `pmsl` is mean sea level pressure (Pa or hPa -- normalized by
    `mslp_hpa`); `z925`...`z300` are geopotential height (meters) at the
    six band levels; `u850`/`v850`...`u300`/`v300` are the four
    steering-flow wind level pairs (as in `executeB`). `psfc` is AWIPS
    surface pressure (Pa or hPa -- `surface_pressure_hpa` auto-detects
    which); `coriolis` is the AWIPS coriolis pseudo-field (as in
    `executeB`) whose sign is parameter B's hemisphere factor. `dx`,
    `dy` are the grid spacing pseudo-fields (meters).

    Every one of the six height arguments is run through
    `mask_below_ground` against its own pressure and `capHpa` -- see the
    module docstring's "Below-ground masking" section. `pmsl` is not:
    MSLP is defined everywhere, and terrain blanking of the class comes
    from the band levels instead (a point whose 925 hPa height is below
    ground has a NaN lower thermal wind, hence a NaN class).

    `radiusKm`, `bThresholdM`, `layerScale`, `depthHpa`, `blobKm`,
    `capHpa` may each arrive as a float, a 0-d numpy array, or a
    1-element numpy array (AWIPS `<ConstantField>` values) and are
    coerced with `_coerce_scalar`. `closed_low_mask`'s
    `min_radius_km`/`center_tol_hpa` are not exposed (they stay at
    `MIN_RADIUS_KM`/`DEFAULT_CENTER_TOL_HPA`): they tune how a low's own
    center is located, while `depthHpa` is what decides whether there is
    a low at all.

    Returns a float32 array: NaN outside the closed-low mask, below
    ground, or wherever B is NaN (the steering-flow speed below
    `MIN_STEERING_MS` -- rare, but see `parameter_b_grid`'s docstring);
    otherwise one of 0.0 through 6.0 (dimensionless) per `hart_class`'s
    table.
    """
    radius_km = _coerce_scalar(radiusKm)
    b_threshold_m = _coerce_scalar(bThresholdM)
    layer_scale = _coerce_scalar(layerScale)
    depth_hpa = _coerce_scalar(depthHpa)
    blob_radius_km = _coerce_scalar(blobKm)
    cap_hpa = _coerce_scalar(capHpa)

    psfc_hpa = surface_pressure_hpa(psfc)

    vtl = thermal_wind_grid([z925, z850, z700], LOWER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    vtu = thermal_wind_grid([z500, z400, z300], UPPER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)

    z925_masked = mask_below_ground(z925, psfc_hpa, 925.0, cap_hpa)
    z700_masked = mask_below_ground(z700, psfc_hpa, 700.0, cap_hpa)
    thickness = np.asarray(z700_masked, dtype=float) - np.asarray(z925_masked, dtype=float)
    u_s, v_s = steering([u850, u700, u500, u300], [v850, v700, v500, v300])
    u_s, v_s = steering_window_mean(u_s, v_s, dx, dy, radius_km)
    b = parameter_b_grid(thickness, u_s, v_s, dx, dy, coriolis, radius_km, layer_scale)

    mask = closed_low_mask(pmsl, dx, dy, MIN_RADIUS_KM, radius_km, depth_hpa, blob_radius_km)

    return hart_class(b, vtl, vtu, mask, b_threshold_m)


def executeIndexStd(
    pmsl, z925, z850, z700, z500, z400, z300, psfc, dx, dy,
    radiusKm=RADIUS_KM,
    scaleM=100.0,
    depthHpa=DEFAULT_DEPTH_HPA,
    blobKm=DEFAULT_BLOB_RADIUS_KM,
    capHpa=BELOW_GROUND_CAP_HPA,
):
    """AWIPS derived-parameter entry point for HCPSidx (cps_HCPSidx.xml).

    Same lower/upper thermal wind and mask as `executeHartClass`, combined
    into `2*tanh(VTL/scaleM) + tanh(VTU/scaleM)` (range -3 to +3, `scaleM`
    already in meters), blanked (NaN) outside the same `closed_low_mask`
    computed from `pmsl` (mean sea level pressure, Pa or hPa), and the
    same below-ground masking of the six band levels via `psfc`/`capHpa`
    -- see `executeHartClass`'s docstring for the full explanation (why
    MSLP is used for the mask, why it is not itself masked below ground,
    and why the below-ground threshold is capped at `capHpa` rather than
    applied at each level's own literal pressure). `radiusKm`, `scaleM`,
    `depthHpa`, `blobKm`, `capHpa` are coerced the same way as
    `executeHartClass`'s constants; see that function's docstring for why
    `closed_low_mask`'s `min_radius_km`/`center_tol_hpa` are not exposed
    here either.

    Returns a float32 array, NaN outside the mask or below ground,
    otherwise in [-3, 3].
    """
    radius_km = _coerce_scalar(radiusKm)
    scale_m = _coerce_scalar(scaleM)
    depth_hpa = _coerce_scalar(depthHpa)
    blob_radius_km = _coerce_scalar(blobKm)
    cap_hpa = _coerce_scalar(capHpa)

    psfc_hpa = surface_pressure_hpa(psfc)

    vtl = thermal_wind_grid([z925, z850, z700], LOWER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    vtu = thermal_wind_grid([z500, z400, z300], UPPER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    mask = closed_low_mask(pmsl, dx, dy, MIN_RADIUS_KM, radius_km, depth_hpa, blob_radius_km)

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
    parameter B (thermal asymmetry), gridded as the right-minus-left
    semicircle difference of thickness (`parameter_b_grid`) -- see the
    module docstring's "Parameter B and the joint class" section for the
    full method.

    `z925`/`z700` are geopotential height (meters); their difference
    (`z700 - z925`) is this module's thickness layer (see the module
    docstring for why 925-700 hPa rather than Hart's own 900-600 hPa, and
    `layerScale`'s role in rescaling for it). Each is blanked (NaN) below
    ground for its own pressure and `capHpa` before the difference is
    taken (`mask_below_ground`), so `B` comes back NaN wherever either
    height input was masked (`parameter_b_grid` blanks any point whose
    own thickness is missing; its half-disk means simply skip masked
    neighbors).

    `u850`/`v850`, `u700`/`v700`, `u500`/`v500`, `u300`/`v300` are the
    wind components at those four levels, averaged by `steering` and
    then area-averaged over `radiusKm` by `steering_window_mean` (see
    the module docstring's "Parameter B and the joint class" section,
    "Motion") into the motion proxy `parameter_b_grid` uses. `psfc` is
    AWIPS surface
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
    asymmetric configuration; NaN below `MIN_STEERING_MS` or
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
    u_s, v_s = steering_window_mean(u_s, v_s, dx, dy, radius_km)

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
    # gets the largest amplitude of all, so the low is deepest there, the
    # same way it deepens toward the surface in a real warm-core vortex;
    # it is only used below to make a matching MSLP field for the
    # closed-low mask (see the module docstring's "Closed-low mask"
    # section), at about 8 m of 1000 hPa height per hPa.
    amp_by_level = {1000.0: 200.0, 925.0: 180.0, 850.0: 150.0, 700.0: 110.0, 500.0: 50.0, 400.0: 25.0, 300.0: 5.0}
    z_by_level = {}
    for p, amp in amp_by_level.items():
        background = 100.0 + 7000.0 * np.log(1000.0 / p)
        z_by_level[p] = background - amp * decay

    pmsl_demo = 1000.0 + z_by_level[1000.0] / 8.0  # hPa; a 25 hPa low on a 1012.5 hPa background

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
        pmsl_demo,
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        u_westerly, v_zero, u_westerly, v_zero, u_westerly, v_zero, u_westerly, v_zero,
        psfc_ocean, coriolis_nh, dx2d, dy_m,
    )
    print("class at center, 8 m/s westerly steering (expect 0.0, symmetric deep warm core):", cls_westerly[ci, cj])
    print("class far from the vortex (expect nan, outside the closed-low mask):", cls_westerly[0, 0])

    u_easterly = np.full(lat2d.shape, -8.0)
    cls_easterly = executeHartClass(
        pmsl_demo,
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
        pmsl_demo,
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
    # sites). Setting it here is a plain module-level assignment that
    # gradient_2d (and so parameter_b_grid/executeB) picks up with no
    # other change needed.
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

    # Analytic expectation: moving due east, the right half-disk is the
    # south one; for a uniform gradient the south-minus-north half-disk
    # mean difference is the gradient times the 8R/(3*pi) distance
    # between the two half-disk centroids.
    analytic_b = b_geometry_km(RADIUS_KM) * 1000.0 * (GRADIENT_M_PER_KM / 1000.0) * HART_B_LAYER_SCALE
    b_linear_old = parameter_b_grid_gradient(
        thickness_linear, u_s_demo, v_s_demo, dx2d, dy_m, coriolis_nh, RADIUS_KM, HART_B_LAYER_SCALE,
    )
    print("Parameter B on a linear thickness gradient, steering due east along the contours:")
    print("  gridded B at center, semicircle means, m (900-600 equivalent):", b_linear[ci, cj])
    print("  gridded B at center, first-order gradient form, m:", b_linear_old[ci, cj])
    print("  analytic expectation, m:", analytic_b)

    # ---------------------------------------------------------------------
    # Parameter B on a storm-scale wavenumber-one dipole: thickness
    # A*(x_R/L)*exp(-r**2/(2*L**2)) with x_R the distance to the right of
    # the (due east) motion, i.e. southward, L = 400 km. Hart's semicircle
    # difference over R = 500 km is (4/pi) times the area mean of
    # A*(r/L)*exp(-r**2/(2*L**2)) over the disk; the semicircle-mean B
    # recovers it, the first-order gradient form reads only about 55-60%.
    DIPOLE_A_M, DIPOLE_L_KM = 20.0, 400.0
    x_km_from_center = EARTH_RADIUS_KM * np.cos(np.radians(lat2d)) * np.radians(lon2d - CENTER_LON)
    r2_km = x_km_from_center ** 2 + y_km_from_center ** 2
    thickness_dipole = DIPOLE_A_M * (-y_km_from_center / DIPOLE_L_KM) * np.exp(-r2_km / (2.0 * DIPOLE_L_KM ** 2))
    r_quad = np.linspace(0.0, RADIUS_KM, 20001)
    f_quad = DIPOLE_A_M * (r_quad / DIPOLE_L_KM) * np.exp(-r_quad ** 2 / (2.0 * DIPOLE_L_KM ** 2)) * r_quad
    area_mean = float(np.sum((f_quad[1:] + f_quad[:-1]) * np.diff(r_quad)) / 2.0) / (RADIUS_KM ** 2 / 2.0)
    b_dipole = parameter_b_grid(thickness_dipole, u_s_demo, v_s_demo, dx2d, dy_m, coriolis_nh, RADIUS_KM, 1.0)
    b_dipole_old = parameter_b_grid_gradient(thickness_dipole, u_s_demo, v_s_demo, dx2d, dy_m, coriolis_nh, RADIUS_KM, 1.0)
    print("Parameter B on a 400 km wavenumber-one dipole (unscaled layer):")
    print("  semicircle means, m:", b_dipole[ci, cj])
    print("  first-order gradient form, m:", b_dipole_old[ci, cj])
    print("  continuum semicircle difference, m:", 4.0 / math.pi * area_mean)
