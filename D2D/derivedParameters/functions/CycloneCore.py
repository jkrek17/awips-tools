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
this is trusted (see Y_INCREASES_NORTHWARD below).

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
    "Y_INCREASES_NORTHWARD",
    "DEFAULT_SMOOTH_KM",
    "MISSING_THRESHOLD",
    "relative_vorticity",
    "box_smooth",
    "cells_for_km",
    "execute",
    "executeVorticity",
]

# ---------------------------------------------------------------------------
# Tunables / grid-orientation flag
# ---------------------------------------------------------------------------

#: Whether row index (axis 0) increases toward the north on the grids AWIPS
#: hands to this function. True is correct for the great majority of AWIPS
#: D2D grids (row 0 at the south edge). See D2D/README.md "Orientation
#: verification" for the one-time check every site should do: load the
#: cpsZ850 debug field and D2D's own relative vorticity at 850 mb on a
#: known hurricane and compare signs. Flip this to False if cpsZ850 comes
#: out with the opposite sign of D2D's own relative vorticity.
Y_INCREASES_NORTHWARD = True

#: Default half-width of the smoothing box, in kilometers, used by execute()
#: when the definition XML's <ConstantField> is not supplied or is missing.
DEFAULT_SMOOTH_KM = 100.0

#: AWIPS may hand us -999999 (or similar) fill values for missing data.
#: Anything below this threshold, or non-finite (NaN/Inf), is treated as
#: missing.
MISSING_THRESHOLD = -99990.0


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


def relative_vorticity(u: np.ndarray, v: np.ndarray, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """Relative vorticity zeta = dv/dx - du/dy, via centered differences.

    `u`, `v` are 2D wind component arrays (m/s) of identical shape, indexed
    [y, x] (axis 0 is the north-south grid direction, axis 1 is east-west).
    `dx`, `dy` are the grid spacing in meters along x and y respectively;
    each may be a scalar or a 2D array of the same shape as `u`/`v` (AWIPS
    supplies these as "dx"/"dy" pseudo-fields that vary across the grid on
    most map projections).

    `np.gradient` is used for the centered difference: `dv/dx` along axis
    1, `du/dy` along axis 0. If `Y_INCREASES_NORTHWARD` is False, the
    du/dy term is negated (equivalent to flipping the sign convention of
    the y axis without touching the input arrays).

    Missing values (see `_missing_mask`) in `u`, `v`, `dx`, or `dy` are set
    to NaN before differencing and any resulting NaN is left as NaN in the
    output. Because `np.gradient` uses centered differences, a missing
    input point contaminates its immediate neighbors' derivative too --
    this is unavoidable with a centered-difference stencil and is why
    `execute()` smooths afterward rather than trying to patch it up.
    """
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    dx = np.asarray(dx, dtype=float)
    dy = np.asarray(dy, dtype=float)

    bad = _missing_mask(u, v, dx, dy)
    bad = np.broadcast_to(bad, u.shape)

    u_clean = np.where(bad, np.nan, u)
    v_clean = np.where(bad, np.nan, v)

    dv_dx = np.gradient(v_clean, axis=1) / dx
    du_dy = np.gradient(u_clean, axis=0) / dy

    if not Y_INCREASES_NORTHWARD:
        du_dy = -du_dy

    zeta = dv_dx - du_dy
    zeta = np.where(bad, np.nan, zeta)
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


def executeVorticity(u, v, dx, dy):
    """AWIPS debug entry point: relative vorticity alone, float32, 1/s.

    Used by the cpsZ850 definition (D2D/derivedParameters/definitions/
    cpsZ850.xml) so a site can compare its sign against D2D's own
    relative vorticity field on a known hurricane -- see the "Orientation
    verification" procedure in D2D/README.md.
    """
    return relative_vorticity(u, v, dx, dy).astype(np.float32)


# ---------------------------------------------------------------------------
# Standalone sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
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
