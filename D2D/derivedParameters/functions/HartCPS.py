"""
HartCPS.py -- AWIPS II D2D derived parameter: Hart (2003) actual thermal
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
`executeClassStd`/`executeIndexStd`/`HVTL`/`HVTU` use exactly:

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

`closed_low_mask` (used by `executeClassStd`/`executeIndexStd` to blank
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
unaffected. `executeClassStd`/`executeIndexStd`/`executeBand3`/
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

This file must import nothing from outside itself plus the standard
library and numpy: in AWIPS it runs inside CAVE's embedded Python
interpreter, which only has numpy and whatever else lives in the same
derivedParameters/functions directory on the classpath. It is written
so it can also be run standalone for a sanity check with no AWIPS
present at all:

    python3 D2D/derivedParameters/functions/HartCPS.py
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "RADIUS_KM",
    "MISSING_THRESHOLD",
    "DEFAULT_NEUTRAL_M",
    "MIN_RADIUS_KM",
    "DEFAULT_DEPTH_M",
    "DEFAULT_BLOB_RADIUS_KM",
    "DEFAULT_CENTER_TOL_M",
    "LOWER_BAND",
    "UPPER_BAND",
    "BELOW_GROUND_CAP_HPA",
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
    "executeBand3",
    "executeBand4",
    "executeBand7",
    "executeClassStd",
    "executeIndexStd",
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

#: Meters; |VTL| or |VTU| below this is "neutral" for executeClassStd -- not
#: clearly warm-core or cold-core, just noise around zero. Unlike
#: CycloneCore's vorticity-based DEFAULT_NEUTRAL_BAND, this is already in
#: the field's own physical unit (meters), no UNIT_SCALE round trip needed.
DEFAULT_NEUTRAL_M = 25.0

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
    `executeClassStd`/`executeIndexStd` as `z1000`). 1000 hPa height is
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
    `mask_below_ground` (as `executeClassStd`/`executeIndexStd` do)
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


def executeClassStd(
    z1000, z925, z850, z700, z500, z400, z300, psfc, dx, dy,
    radiusKm=RADIUS_KM,
    neutralM=DEFAULT_NEUTRAL_M,
    depthM=DEFAULT_DEPTH_M,
    blobKm=DEFAULT_BLOB_RADIUS_KM,
    capHpa=BELOW_GROUND_CAP_HPA,
):
    """AWIPS derived-parameter entry point for HCPScat (HCPScat.xml).

    Computes the lower thermal wind (`LOWER_BAND`, 925/850/700 hPa) and
    upper thermal wind (`UPPER_BAND`, 500/400/300 hPa) at every grid
    point, buckets them into the same 5-category table
    `CycloneCore.classify` uses (0 mid-level vortex, 1 cold core, 2
    neutral, 3 shallow warm core, 4 deep warm core) with `band = neutralM`
    (already in meters -- no unit rescaling needed here, unlike
    `CycloneCore.py`'s vorticity units), and blanks (NaN) every point
    outside `closed_low_mask` computed from `z1000`, using `radiusKm` as
    both the thermal-wind window and the mask's own `ring_radius_km`. The
    thermal-wind bands themselves are unchanged by this: the mask level
    (`z1000`) and the band levels (`z925`...`z300`) are independent
    arguments.

    `z1000` (1000 hPa height) is used for the mask rather than a level
    from `LOWER_BAND`/`UPPER_BAND` because it is nearly a linear function
    of MSLP (about 8 m per hPa), so the closed low the mask finds is the
    same closed low a forecaster already sees drawn on the MSLP
    contours; `depthM`'s default of 40 m is therefore about 5 hPa of
    MSLP.

    `psfc` is AWIPS surface pressure (Pa or hPa -- `surface_pressure_hpa`
    auto-detects which). Before anything else, every one of the seven
    height arguments (`z1000` and the six band levels) is run through
    `mask_below_ground` against its own pressure and `capHpa`: a point
    below ground there is blanked (NaN) rather than left at whatever
    fictitious extrapolated height the model assigned it, since 1000 hPa
    (and, less often, 925/850 hPa) is below the ground surface over
    major terrain -- see the module docstring's "Below-ground masking"
    section and `BELOW_GROUND_CAP_HPA`'s own docstring for why the
    threshold is capped (so a deep low's own legitimately low surface
    pressure over open water is never mistaken for terrain). Masking
    happens before `delta_z`'s window max/min and before
    `closed_low_mask`'s own candidate/depth tests, so a below-ground
    point (and, through the NaN-aware sliding windows this module uses
    throughout, its neighbors) never contaminates either computation.

    `radiusKm`, `neutralM`, `depthM`, `blobKm`, `capHpa` may each arrive
    as a float, a 0-d numpy array, or a 1-element numpy array (AWIPS
    `<ConstantField>` values) and are coerced with `_coerce_scalar`.
    `capHpa` defaults to `BELOW_GROUND_CAP_HPA` (900 hPa). `closed_low_mask`'s
    `min_radius_km` and `center_tol_m` are left at their module defaults
    (`MIN_RADIUS_KM`, `DEFAULT_CENTER_TOL_M`) and not exposed as
    `<ConstantField>` values -- they are fixed properties of "how big a
    box finds a low's own local minimum" and "how tight a tolerance
    counts as being at it", not something a site is expected to tune per
    case the way `neutralM`/`depthM`/`blobKm`/`capHpa` are.

    Returns a float32 array, NaN outside the mask or below ground,
    otherwise one of 0.0/1.0/2.0/3.0/4.0 (dimensionless).
    """
    radius_km = _coerce_scalar(radiusKm)
    neutral_m = _coerce_scalar(neutralM)
    depth_m = _coerce_scalar(depthM)
    blob_radius_km = _coerce_scalar(blobKm)
    cap_hpa = _coerce_scalar(capHpa)

    psfc_hpa = surface_pressure_hpa(psfc)

    vtl = thermal_wind_grid([z925, z850, z700], LOWER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    vtu = thermal_wind_grid([z500, z400, z300], UPPER_BAND, dx, dy, radius_km, psfc_hpa=psfc_hpa, cap_hpa=cap_hpa)
    z1000_masked = mask_below_ground(z1000, psfc_hpa, 1000.0, cap_hpa)
    mask = closed_low_mask(z1000_masked, dx, dy, MIN_RADIUS_KM, radius_km, depth_m, blob_radius_km)

    band = neutral_m
    conditions = [
        (vtl > band) & (vtu > band),
        (vtl > band) & (vtu <= band),
        (np.abs(vtl) <= band) & (vtu < -band),
        (np.abs(vtl) <= band) & (vtu >= -band),
        (vtl < -band) & (vtu > band),
        (vtl < -band) & (vtu <= band),
    ]
    choices = [4, 3, 1, 2, 0, 1]
    code = np.select(conditions, choices, default=np.nan)

    masked = ~mask | ~np.isfinite(vtl) | ~np.isfinite(vtu)
    code = np.where(masked, np.nan, code)
    return code.astype(np.float32)


def executeIndexStd(
    z1000, z925, z850, z700, z500, z400, z300, psfc, dx, dy,
    radiusKm=RADIUS_KM,
    scaleM=100.0,
    depthM=DEFAULT_DEPTH_M,
    blobKm=DEFAULT_BLOB_RADIUS_KM,
    capHpa=BELOW_GROUND_CAP_HPA,
):
    """AWIPS derived-parameter entry point for HCPSidx (HCPSidx.xml).

    Same lower/upper thermal wind and mask as `executeClassStd`, combined
    into `2*tanh(VTL/scaleM) + tanh(VTU/scaleM)` (range -3 to +3, `scaleM`
    already in meters), blanked (NaN) outside the same `closed_low_mask`
    computed from `z1000`, and the same below-ground masking of `z1000`
    and the six band levels via `psfc`/`capHpa` -- see `executeClassStd`'s
    docstring for the full explanation (why `z1000` rather than a band
    level is used for the mask, and why the below-ground threshold is
    capped at `capHpa` rather than applied at each level's own literal
    pressure). `radiusKm`, `scaleM`, `depthM`, `blobKm`, `capHpa` are
    coerced the same way as `executeClassStd`'s constants; see that
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

    cls = executeClassStd(
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        psfc_ocean, dx2d, dy_m,
    )
    print("class at center (expect 4.0, deep warm core):", cls[ci, cj])
    print("class far from the vortex (expect nan, outside the closed-low mask):", cls[0, 0])

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

    cls_terrain = executeClassStd(
        z_by_level[1000.0],
        z_by_level[925.0], z_by_level[850.0], z_by_level[700.0],
        z_by_level[500.0], z_by_level[400.0], z_by_level[300.0],
        psfc_terrain, dx2d, dy_m,
    )
    print("class at center with a terrain block 800 km west (expect unchanged, 4.0):", cls_terrain[ci, cj])
    block_i, block_j = np.argwhere(block_mask)[0]
    print("class over the terrain block (expect nan, below ground):", cls_terrain[block_i, block_j])
