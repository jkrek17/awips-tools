"""
CycloneCore.py -- AWIPS II D2D derived parameter: cyclone core structure.

*** EXPERIMENTAL.  NOT OPERATIONALLY VETTED. ***
This is a pointwise, gridded analogue of Hart's (2003) thermal wind
parameters (see `cps/hart.py` and `web/CPS/PLAN.md` section 4 in this
repo for the storm-centered version this is derived from), not a
reimplementation of Hart's method itself. Hart's VTL/VTU are computed
from the max-minus-min of geopotential height over a 500 km circle
around a storm's *own* center, at 900-600 hPa and 600-300 hPa. That is
not something a D2D derived parameter can do: D2D derived parameters
run pointwise over a whole model grid with no notion of "the storm's
center" and no access to a moving analysis circle. What follows instead
is a shortcut that is easy to compute pointwise and easy to read as a
forecaster's overlay, at the cost of being a genuinely
different diagnostic that only rhymes with Hart's:

    zeta_lo - zeta_hi

the vertical change of relative vorticity between a lower and an upper
isobaric level, lightly smoothed. A cyclone's core is warm when its
cyclonic circulation weakens with height (the classic tropical
structure: strong low-level vortex, weak/anticyclonic outflow aloft).
That weakening shows up here as zeta_lo > zeta_hi, i.e. a POSITIVE
value. A cold-core / baroclinic system tends to have vorticity that
holds up or increases with height (an upper trough over the surface
low), which shows up as a NEGATIVE value. This is the same sign
convention Hart uses for VTL/VTU: positive = warm core.

Read this field only where it means something: at and immediately
around a closed low in the MSLP field. Away from a low center this is
just the vertical shear of vorticity for whatever happens to be there
(a jet streak, an open trough) and "warm core" / "cold core" language
does not apply. See D2D/README.md for the reading guide, the
Northern/Southern Hemisphere sign caveat, and the orientation
verification procedure that must be done once per AWIPS site before
this is trusted (see ORIENTATION_MODE below).

Two more derived parameters, CPScat and CPSidx, combine VTL and VTU
into a single field instead of making a forecaster eyeball two. Both
are computed pointwise, just like VTL/VTU, but both are also BLANKED
(NaN) outside of a cyclonic vortex, using the smoothed 850 hPa
relative vorticity as a mask (see `classify`/`continuous_index`
below): a point is only classified where that vorticity exceeds
`DEFAULT_VORTEX_MIN` (or the site's chosen threshold), which is meant
to keep "warm core"/"cold core" language from leaking into the
open-trough/jet-streak regions VTL/VTU alone can't tell apart from a
real low. CPScat buckets VTL/VTU into 5 categories (mid-level vortex,
cold core, neutral, shallow warm core, deep warm core); CPSidx
squashes them into one continuous number from -3 (cold) to +3 (deep
warm) via tanh. Because the mask is relative vorticity and cyclonic
vorticity is NEGATIVE in the Southern Hemisphere, this mask blanks SH
cyclones entirely -- the same known limitation as VTL/VTU's sign
(see D2D/README.md), TODO: a latitude pseudo-field to flip the mask's
sign south of the equator.

This file must import nothing from outside itself plus the standard
library and numpy: in AWIPS it runs inside CAVE's embedded Python
interpreter, which only has numpy and whatever else lives in the same
derivedParameters/functions directory on the classpath. It is written
so it can also be run standalone for a sanity check with no AWIPS
present at all:

    python3 D2D/derivedParameters/functions/CycloneCore.py
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "ORIENTATION_MODE",
    "DEFAULT_SMOOTH_KM",
    "MISSING_THRESHOLD",
    "DEFAULT_NEUTRAL_BAND",
    "DEFAULT_VORTEX_MIN",
    "DEFAULT_INDEX_SCALE",
    "relative_vorticity",
    "box_smooth",
    "cells_for_km",
    "core_fields",
    "classify",
    "continuous_index",
    "execute",
    "executeVorticity",
    "executeClass",
    "executeIndex",
]

# ---------------------------------------------------------------------------
# Tunables / grid-orientation flag
# ---------------------------------------------------------------------------

#: Grid orientation mode used by relative_vorticity() (and, through its
#: default, by execute()/core_fields()/executeClass()/executeIndex()) when
#: no explicit `mode` argument is given. AWIPS hands this function 2D wind
#: and grid-spacing arrays whose axis layout is a property of the site's
#: grid projection and storage order, which this file cannot know in
#: advance. Four conventions are distinguishable from here:
#:
#:   0: axis 0 = y increasing northward, axis 1 = x (the numpy-default
#:      assumption: row 0 is the south edge, columns run east).
#:   1: axis 0 = y increasing SOUTHWARD, axis 1 = x (row 0 is the north
#:      edge instead, so the du/dy term's sign is flipped relative to
#:      mode 0).
#:   2: arrays transposed: axis 0 = x, axis 1 = y increasing northward.
#:   3: arrays transposed AND y increasing southward (mode 2 with the
#:      du/dy flip of mode 1 as well).
#:
#: Mode 0 was observed to give a lobed, deformation-like cpsZ850 pattern
#: around a hurricane on a real AWIPS site -- instead of a single positive
#: blob -- which is what running mode-0's vorticity formula over a
#: transposed-axis grid (mode 2) or a south-up grid (mode 1) looks like.
#: That is why the default here is 1, not 0. Use the cpsZ850 debug field
#: (D2D/derivedParameters/definitions/cpsZ850.xml), whose `mode`
#: ConstantField can be edited without touching this file, to find which
#: mode makes cpsZ850 match D2D's own relative vorticity at 850 mb on a
#: known hurricane (see D2D/README.md "Orientation verification"), then
#: set this constant to that value -- it is shared by VTL, VTU, CPScat,
#: and CPSidx, all of which call relative_vorticity() with mode=None.
ORIENTATION_MODE = 1

#: Default half-width of the smoothing box, in kilometers, used by execute()
#: when the definition XML's <ConstantField> is not supplied or is missing.
DEFAULT_SMOOTH_KM = 100.0

#: AWIPS may hand us -999999 (or similar) fill values for missing data.
#: Anything below this threshold, or non-finite (NaN/Inf), is treated as
#: missing.
MISSING_THRESHOLD = -99990.0

#: 1/s; |VTL| or |VTU| below this is "neutral" for CPScat/CPSidx -- i.e. not
#: clearly warm-core or cold-core, just noise around zero. Tune after
#: calibration on real cases (see D2D/README.md "Calibration procedure").
DEFAULT_NEUTRAL_BAND = 3.0e-5

#: 1/s; CPScat/CPSidx classify a point only where the smoothed 850 hPa
#: relative vorticity exceeds this (cyclonic in the NH) -- see `classify`'s
#: vortex mask. Everywhere else the output is NaN. Tune after calibration.
DEFAULT_VORTEX_MIN = 5.0e-5

#: 1/s; scale for CPSidx's continuous index tanh squashing -- roughly the
#: |VTL|/|VTU| magnitude that reads as "fully" warm/cold (tanh saturates by
#: about 3x this). Tune after calibration.
DEFAULT_INDEX_SCALE = 1.0e-4


# ---------------------------------------------------------------------------
# Missing-data handling
# ---------------------------------------------------------------------------


def _missing_mask(*arrays: np.ndarray) -> np.ndarray:
    """True wherever any of `arrays` is non-finite or below
    `MISSING_THRESHOLD`, broadcast together. All arrays must be the same
    shape (or broadcastable); this is used to seed NaNs into fields before
    doing arithmetic on them so a single bad AWIPS fill value cannot
    silently masquerade as real data.
    """
    mask = None
    for arr in arrays:
        a = np.asarray(arr, dtype=float)
        bad = ~np.isfinite(a) | (a < MISSING_THRESHOLD)
        mask = bad if mask is None else (mask | bad)
    if mask is None:
        return np.array(False)
    return mask


# ---------------------------------------------------------------------------
# Relative vorticity
# ---------------------------------------------------------------------------


def relative_vorticity(
    u: np.ndarray, v: np.ndarray, dx: np.ndarray, dy: np.ndarray, mode: int | None = None
) -> np.ndarray:
    """Relative vorticity zeta = dv/dx - du/dy, via centered differences.

    `u`, `v` are 2D wind component arrays (m/s) of identical shape. `dx`,
    `dy` are the grid spacing in meters along x and y respectively; each
    may be a scalar or a 2D array of the same shape as `u`/`v` (AWIPS
    supplies these as "dx"/"dy" pseudo-fields that vary across the grid on
    most map projections).

    `mode` selects which of the four grid-orientation conventions
    described at `ORIENTATION_MODE` (module level) the *input* arrays are
    actually in; `None` (the default) means "use `ORIENTATION_MODE`",
    read fresh from the module on every call so a monkeypatch or a later
    assignment to it takes effect without touching this function. Modes
    0 and 1 assume `u`/`v`/`dx`/`dy` are already laid out [y, x] (axis 0
    north-south, axis 1 east-west) and differ only in whether axis 0
    increases northward (0) or southward (1, which negates the du/dy
    term -- equivalent to flipping the sign convention of the y axis
    without touching the input arrays).

    Modes 2 and 3 are for a site where the arrays instead arrive
    transposed, axis 0 = x and axis 1 = y: `u`, `v`, and any 2D `dx`/`dy`
    (a scalar spacing is left alone -- transposing a 0-d array is a
    no-op anyway) are transposed on the way in so axis 0 = y and axis 1 =
    x, matching modes 0/1, and the zeta result is transposed back on the
    way out so its shape and axis layout match the *original*, untransposed
    inputs. `dx` and `dy` are transposed, not swapped: the value at
    `dx[i, j]` is still "the x-direction spacing at this grid point" after
    transposing (`dx.T[j, i] == dx[i, j]`), it has just been relabeled
    into the [y, x] layout the differencing below expects, and is still
    divided into the axis-1 (x) gradient -- exactly as `dy.T` is still
    divided into the axis-0 (y) gradient. Nothing about which pseudo-field
    means "x spacing" versus "y spacing" changes; only the array layout
    each is expressed in does. Mode 3 additionally negates du/dy like
    mode 1, since a transposed grid can independently have its (new) y
    axis run either direction.

    Missing values (see `_missing_mask`) in `u`, `v`, `dx`, or `dy` are set
    to NaN before differencing and any resulting NaN is left as NaN in the
    output. Because `np.gradient` uses centered differences, a missing
    input point contaminates its immediate neighbors' derivative too --
    this is unavoidable with a centered-difference stencil and is why
    `execute()` smooths afterward rather than trying to patch it up.

    Raises `ValueError` if `mode` (after defaulting) is not one of 0, 1,
    2, 3.
    """
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    dx = np.asarray(dx, dtype=float)
    dy = np.asarray(dy, dtype=float)

    if mode is None:
        mode = ORIENTATION_MODE
    mode = int(mode)
    if mode not in (0, 1, 2, 3):
        raise ValueError(f"mode must be 0, 1, 2, or 3; got {mode!r}")

    transposed = mode in (2, 3)
    if transposed:
        u = u.T
        v = v.T
        if dx.ndim == 2:
            dx = dx.T
        if dy.ndim == 2:
            dy = dy.T

    bad = _missing_mask(u, v, dx, dy)
    bad = np.broadcast_to(bad, u.shape)

    u_clean = np.where(bad, np.nan, u)
    v_clean = np.where(bad, np.nan, v)

    dv_dx = np.gradient(v_clean, axis=1) / dx
    du_dy = np.gradient(u_clean, axis=0) / dy

    if mode in (1, 3):
        du_dy = -du_dy

    zeta = dv_dx - du_dy
    zeta = np.where(bad, np.nan, zeta)

    if transposed:
        zeta = zeta.T

    return zeta


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------


def box_smooth(field: np.ndarray, cells: int) -> np.ndarray:
    """NaN-aware separable box mean with half-width `cells`.

    The averaging window for output point (i, j) is
    field[i-cells:i+cells+1, j-cells:j+cells+1], clipped at the domain
    edges (the mean is taken over whatever part of the window actually
    falls inside the grid -- edges are not padded, so edge and corner
    points are averages of a smaller window, not a mirrored/extended one).

    `cells` must be an integer >= 0; 0 returns an unchanged copy of
    `field`. NaN input points are excluded from every window mean they
    fall in (both as numerator and denominator); an output point comes
    back NaN only if every point in its window is NaN.

    Implemented with cumulative sums along each axis, so the cost does
    not depend on the window size (each axis pass is O(n) regardless of
    `cells`).
    """
    field = np.asarray(field, dtype=float)
    cells = int(cells)
    if cells < 0:
        raise ValueError("cells must be >= 0")
    if cells == 0:
        return field.copy()

    valid = np.isfinite(field)
    values = np.where(valid, field, 0.0)
    counts = valid.astype(float)

    def _box_sum_1d(arr: np.ndarray, half_width: int, axis: int) -> np.ndarray:
        n = arr.shape[axis]
        # Cumulative sum with a leading zero so that
        # windowsum[i] = cumsum[hi] - cumsum[lo], lo/hi clipped to [0, n].
        cs = np.cumsum(arr, axis=axis)
        zero_shape = list(arr.shape)
        zero_shape[axis] = 1
        cs = np.concatenate([np.zeros(zero_shape, dtype=arr.dtype), cs], axis=axis)

        idx = np.arange(n)
        lo = np.clip(idx - half_width, 0, n)
        hi = np.clip(idx + half_width + 1, 0, n)

        take_hi = np.take(cs, hi, axis=axis)
        take_lo = np.take(cs, lo, axis=axis)
        return take_hi - take_lo

    sum_x = _box_sum_1d(values, cells, axis=1)
    sum_xy = _box_sum_1d(sum_x, cells, axis=0)
    cnt_x = _box_sum_1d(counts, cells, axis=1)
    cnt_xy = _box_sum_1d(cnt_x, cells, axis=0)

    with np.errstate(invalid="ignore", divide="ignore"):
        result = sum_xy / cnt_xy
    result = np.where(cnt_xy > 0, result, np.nan)
    return result


def cells_for_km(km: float, dx: np.ndarray, dy: np.ndarray) -> int:
    """Convert a half-width in kilometers to a half-width in grid cells.

    `dx`/`dy` may be scalars or arrays (meters); the mean grid spacing
    used for the conversion is `nanmean` of both combined, so a spatially
    varying map projection still gets a single representative cell count.
    Result is `round(km * 1000 / mean_spacing)`, floored at 0.
    """
    spacing = np.nanmean(np.concatenate([np.asarray(dx, dtype=float).ravel(), np.asarray(dy, dtype=float).ravel()]))
    if not np.isfinite(spacing) or spacing <= 0:
        return 0
    cells = int(round(float(km) * 1000.0 / spacing))
    return max(cells, 0)


# ---------------------------------------------------------------------------
# AWIPS entry points
# ---------------------------------------------------------------------------


def _coerce_scalar(x) -> float:
    """Coerce a value that may arrive as a Python float, a 0-d numpy
    array, or a 1-element numpy array (as AWIPS ConstantField values do)
    into a plain float.
    """
    return float(np.asarray(x).ravel()[0])


def execute(uLo, vLo, uHi, vHi, dx, dy, smoothKm=DEFAULT_SMOOTH_KM):
    """AWIPS derived-parameter entry point for VTL/VTU.

    `uLo`, `vLo` are the wind components at the lower (higher-pressure)
    level; `uHi`, `vHi` at the upper (lower-pressure) level. `dx`, `dy`
    are the grid spacing pseudo-fields (meters). `smoothKm` is the box
    smoothing half-width in kilometers (may arrive as a float, a 0-d
    numpy array, or a 1-element numpy array -- an AWIPS <ConstantField>
    value).

    Returns `box_smooth(zeta_lo - zeta_hi, cells)` as float32, units 1/s,
    with no additional scaling. NaN wherever the inputs were missing.
    Positive = warm core (see the module docstring for the sign
    derivation); negative = cold core.
    """
    smooth_km = _coerce_scalar(smoothKm)
    zeta_lo = relative_vorticity(uLo, vLo, dx, dy)
    zeta_hi = relative_vorticity(uHi, vHi, dx, dy)
    diff = zeta_lo - zeta_hi
    cells = cells_for_km(smooth_km, dx, dy)
    smoothed = box_smooth(diff, cells)
    return smoothed.astype(np.float32)


def executeVorticity(u, v, dx, dy, mode=None):
    """AWIPS debug entry point: relative vorticity alone, float32, 1/s.

    Used by the cpsZ850 definition (D2D/derivedParameters/definitions/
    cpsZ850.xml) so a site can compare its sign and pattern against
    D2D's own relative vorticity field on a known hurricane -- see the
    "Orientation verification" procedure in D2D/README.md. `mode` is the
    cpsZ850.xml `<ConstantField>` value, letting a site try each of the
    four `ORIENTATION_MODE` conventions (see CycloneCore.py's module
    docstring) without editing this file; it may arrive as a float, a 0-d
    numpy array, or a 1-element numpy array (an AWIPS `<ConstantField>`
    value) and is coerced with `_coerce_scalar` to an int when given.
    `None` (the ConstantField omitted) falls through to
    `relative_vorticity`'s own default, `ORIENTATION_MODE`.
    """
    if mode is not None:
        mode = int(_coerce_scalar(mode))
    return relative_vorticity(u, v, dx, dy, mode=mode).astype(np.float32)


# ---------------------------------------------------------------------------
# Combined fields (CPScat, CPSidx): VTL + VTU + a vortex mask
# ---------------------------------------------------------------------------


def core_fields(
    uLo: np.ndarray,
    vLo: np.ndarray,
    uMid: np.ndarray,
    vMid: np.ndarray,
    uHi: np.ndarray,
    vHi: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    smooth_km: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shared building blocks for CPScat/CPSidx: VTL, VTU, and the mask field.

    Computes relative vorticity at the three levels (lo/mid/hi, in
    decreasing pressure -- e.g. 850/600/300 hPa) exactly once each, then
    returns `(vtl, vtu, zeta_lo_smoothed)` where

        vtl             = box_smooth(zeta_lo - zeta_mid, cells)
        vtu             = box_smooth(zeta_mid - zeta_hi, cells)
        zeta_lo_smoothed = box_smooth(zeta_lo, cells)

    with `cells = cells_for_km(smooth_km, dx, dy)`. Because the mid level
    is shared between the lower and upper differences, this gives exactly
    the same VTL and VTU as the separate `execute()` calls in VTL.xml and
    VTU.xml would, provided the same three levels are used -- it is just
    computed once instead of twice.

    `zeta_lo_smoothed` (the smoothed 850 hPa relative vorticity, in the
    usual bracketing) is the vortex mask input for `classify()` and
    `continuous_index()`: it is what tells those functions whether a grid
    point is inside a cyclonic circulation at all.
    """
    zeta_lo = relative_vorticity(uLo, vLo, dx, dy)
    zeta_mid = relative_vorticity(uMid, vMid, dx, dy)
    zeta_hi = relative_vorticity(uHi, vHi, dx, dy)

    cells = cells_for_km(smooth_km, dx, dy)
    vtl = box_smooth(zeta_lo - zeta_mid, cells)
    vtu = box_smooth(zeta_mid - zeta_hi, cells)
    zeta_lo_smoothed = box_smooth(zeta_lo, cells)
    return vtl, vtu, zeta_lo_smoothed


def classify(
    vtl: np.ndarray,
    vtu: np.ndarray,
    zeta_lo: np.ndarray,
    band: float = DEFAULT_NEUTRAL_BAND,
    vortex_min: float = DEFAULT_VORTEX_MIN,
) -> np.ndarray:
    """Bucket VTL/VTU into a 5-category core class, masked to cyclonic points.

    `zeta_lo` is the vortex mask input (smoothed 850 hPa relative vorticity,
    from `core_fields`). A point is masked to NaN if `zeta_lo < vortex_min`
    (not cyclonic enough, or on the wrong side of the equator -- see the
    module docstring's Southern Hemisphere note) or if any of `vtl`, `vtu`,
    `zeta_lo` is NaN there. Everywhere else, the code is decided by this
    table (applied elementwise, `band = DEFAULT_NEUTRAL_BAND` by default):

        vtl condition        vtu condition   code  meaning
        --------------------  --------------  ----  -----------------------
        vtl >  band           vtu >  band      4    deep warm core
        vtl >  band           vtu <= band      3    shallow warm core
        |vtl| <= band         vtu <  -band      1    cold core
        |vtl| <= band         vtu >= -band      2    neutral
        vtl <  -band          vtu >  band       0    mid-level vortex (rare,
                                                      transient)
        vtl <  -band          vtu <= band       1    cold core

    The three `vtl` conditions (`> band`, `|.| <= band`, `< -band`) and,
    within each, the two `vtu` conditions partition the real line exactly
    once each, so every finite, unmasked `(vtl, vtu)` pair matches exactly
    one row above -- boundary values (`vtl` or `vtu` exactly `+-band`) are
    written explicitly into one side of each split, not left ambiguous.

    Returns a float32 array (NaN where masked, otherwise one of
    0.0/1.0/2.0/3.0/4.0).
    """
    vtl = np.asarray(vtl, dtype=float)
    vtu = np.asarray(vtu, dtype=float)
    zeta_lo = np.asarray(zeta_lo, dtype=float)

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

    masked = (zeta_lo < vortex_min) | ~np.isfinite(vtl) | ~np.isfinite(vtu) | ~np.isfinite(zeta_lo)
    code = np.where(masked, np.nan, code)
    return code.astype(np.float32)


def continuous_index(
    vtl: np.ndarray,
    vtu: np.ndarray,
    zeta_lo: np.ndarray,
    scale: float = DEFAULT_INDEX_SCALE,
    vortex_min: float = DEFAULT_VORTEX_MIN,
) -> np.ndarray:
    """Continuous cold-to-warm-core index, masked to cyclonic points.

    `2*tanh(vtl/scale) + tanh(vtu/scale)`, so the range is -3 to +3: near
    +3 is a deep warm core (both terms saturated positive), +1 to +2 a
    shallow warm core (vtl saturated, vtu near zero or negative), near 0 is
    neutral, and negative is cold core. Masked to NaN by the same rule as
    `classify()`: `zeta_lo < vortex_min`, or any of `vtl`, `vtu`, `zeta_lo`
    NaN.

    Returns a float32 array.
    """
    vtl = np.asarray(vtl, dtype=float)
    vtu = np.asarray(vtu, dtype=float)
    zeta_lo = np.asarray(zeta_lo, dtype=float)

    index = 2.0 * np.tanh(vtl / scale) + np.tanh(vtu / scale)

    masked = (zeta_lo < vortex_min) | ~np.isfinite(vtl) | ~np.isfinite(vtu) | ~np.isfinite(zeta_lo)
    index = np.where(masked, np.nan, index)
    return index.astype(np.float32)


def executeClass(
    uLo,
    vLo,
    uMid,
    vMid,
    uHi,
    vHi,
    dx,
    dy,
    smoothKm=DEFAULT_SMOOTH_KM,
    band=DEFAULT_NEUTRAL_BAND,
    vortexMin=DEFAULT_VORTEX_MIN,
):
    """AWIPS derived-parameter entry point for CPScat (CPScat.xml).

    `uLo`/`vLo`, `uMid`/`vMid`, `uHi`/`vHi` are the wind components at the
    lower, middle, and upper levels (e.g. 850/600/300 hPa). `dx`, `dy` are
    the grid spacing pseudo-fields (meters). `smoothKm`, `band`,
    `vortexMin` may each arrive as a float, a 0-d numpy array, or a
    1-element numpy array (AWIPS `<ConstantField>` values) and are coerced
    with `_coerce_scalar`.

    Computes `core_fields()` then `classify()`; see `classify`'s docstring
    for the decision table. Returns a float32 array, NaN outside cyclonic
    vortices (per the vortex mask), otherwise 0-4.
    """
    smooth_km = _coerce_scalar(smoothKm)
    band_v = _coerce_scalar(band)
    vortex_min_v = _coerce_scalar(vortexMin)
    vtl, vtu, zeta_lo = core_fields(uLo, vLo, uMid, vMid, uHi, vHi, dx, dy, smooth_km)
    return classify(vtl, vtu, zeta_lo, band=band_v, vortex_min=vortex_min_v)


def executeIndex(
    uLo,
    vLo,
    uMid,
    vMid,
    uHi,
    vHi,
    dx,
    dy,
    smoothKm=DEFAULT_SMOOTH_KM,
    scale=DEFAULT_INDEX_SCALE,
    vortexMin=DEFAULT_VORTEX_MIN,
):
    """AWIPS derived-parameter entry point for CPSidx (CPSidx.xml).

    Same inputs as `executeClass`, `scale` in place of `band` (see
    `continuous_index`'s docstring). Returns a float32 array, NaN outside
    cyclonic vortices, otherwise in [-3, 3].
    """
    smooth_km = _coerce_scalar(smoothKm)
    scale_v = _coerce_scalar(scale)
    vortex_min_v = _coerce_scalar(vortexMin)
    vtl, vtu, zeta_lo = core_fields(uLo, vLo, uMid, vMid, uHi, vHi, dx, dy, smooth_km)
    return continuous_index(vtl, vtu, zeta_lo, scale=scale_v, vortex_min=vortex_min_v)


# ---------------------------------------------------------------------------
# Standalone sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # This demo describes the plain numpy grid layout (mode 0: axis 0 = y
    # increasing northward), not ORIENTATION_MODE's real default (1,
    # tuned for AWIPS sites -- see the comment above that constant and
    # D2D/README.md "Orientation verification"). Setting it here is a
    # plain module-level assignment (this block runs at module scope),
    # so relative_vorticity()/execute()/etc. below, which all default to
    # "use ORIENTATION_MODE", pick it up with no other change needed.
    ORIENTATION_MODE = 0

    # Solid-body vortex: u = -W*y, v = W*x on a uniform grid, in local
    # meters centered on the domain. Analytic relative vorticity of a
    # solid-body rotation is 2*W everywhere (no edge effects, unlike a
    # real vortex profile), which makes it a convenient standalone check
    # that does not depend on any AWIPS machinery.
    n = 41
    spacing_m = 1000.0
    coords = (np.arange(n) - n // 2) * spacing_m
    x, y = np.meshgrid(coords, coords)

    W_lo = 1.0e-4  # rad/s, lower-level rotation rate
    W_hi = 0.4e-4  # rad/s, weaker upper-level rotation rate (warm core)

    u_lo, v_lo = -W_lo * y, W_lo * x
    u_hi, v_hi = -W_hi * y, W_hi * x

    zeta_lo = relative_vorticity(u_lo, v_lo, spacing_m, spacing_m)
    interior = slice(2, -2)
    print("interior zeta_lo (expect 2*W_lo = %.6e):" % (2.0 * W_lo))
    print(zeta_lo[interior, interior].mean())

    result = execute(u_lo, v_lo, u_hi, v_hi, spacing_m, spacing_m, smoothKm=0.0)
    print("execute() interior (expect 2*(W_lo-W_hi) = %.6e):" % (2.0 * (W_lo - W_hi)))
    print(result[interior, interior].mean())

    # Three-level solid-body vortex, W_lo > W_mid > W_hi: a textbook deep
    # warm core (cyclonic circulation weakens steadily with height).
    W_mid = 0.6e-4  # rad/s, between W_lo and W_hi
    u_mid, v_mid = -W_mid * y, W_mid * x

    cls = executeClass(u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, spacing_m, spacing_m, smoothKm=0.0)
    idx = executeIndex(u_lo, v_lo, u_mid, v_mid, u_hi, v_hi, spacing_m, spacing_m, smoothKm=0.0)
    print("executeClass() interior (expect 4.0, deep warm core):")
    print(cls[interior, interior].mean())
    print("executeIndex() interior value (positive, deep warm core):")
    print(idx[interior, interior].mean())
