"""Synthetic extratropical-transition life cycle, two ways.

Builds one synthetic storm, 0 to 168 h in 6 h steps (29 frames), moving
from the deep tropics into a baroclinic zone and recurving, the way a
transitioning typhoon does. At every frame Hart's (2003) cyclone phase
space parameters (B, the lower thermal wind VTL, the upper thermal wind
VTU) are computed two ways at the storm's own center grid point:

1. "Hart": the storm-centered, circular-window reference implementation
   in `cps/hart.py` (`thermal_wind`, `parameter_b`), on 50 hPa levels
   from 900 to 300 hPa, radius 500 km.
2. "Gridded": the operational, pointwise D2D module
   `D2D/derivedParameters/functions/cps_HartCPS.py`
   (`executeBand3`, `executeB`, `executeHartClass`) on the seven
   standard levels (1000/925/850/700/500/400/300 hPa), sampled at the
   grid point nearest the storm center.

Both methods are handed the same storm motion (finite difference of the
track, via `cps.track_motion`), so any difference between them is the
circle-vs-square window and the 900-600/500 hPa lower-band difference,
not a difference in motion.

The height field is the sum of an axisymmetric vortex (which the storm
center itself sees as flat, contributing nothing to B there) plus a
baroclinic environment (a meridional gradient the storm meets as it
crosses 30-40N) plus a storm-attached, motion-relative thickness dipole
(cold to the left of the track, warm to the right), so the storm
actually passes through Hart's frontal classes (B > 10 m) the way a
real transition does, not just the cold-core/warm-core classes B alone
cannot distinguish. Run from this directory:

    python3 lifecycle_comparison.py

Prints one row per frame, the onset (B first exceeds 10 m) and
completion (VTL first turns negative) hour for each method, the hour B
falls back under 10 m after its peak, the B peak itself, the rms
difference between methods for B/VTL/VTU over the life cycle, the
gridded/Hart ratio of the lower term during the deep warm core phase
(0 to 48 h), and the gridded class sequence. Writes figD_lifecycle.png
(300 dpi) next to this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "D2D" / "derivedParameters" / "functions"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

import cps_HartCPS as hc  # noqa: E402
import cps as ch  # noqa: E402
from experiments import make_grid, dist_km, std_height, LEVELS, ANCHOR_P  # noqa: E402
from band_comparison import ARCHETYPES  # noqa: E402

hc.ORIENTATION_MODE = 0  # rows increase northward on these grids, as in experiments_extensions.py

RADIUS_KM = 500.0
P50 = np.arange(1000, 299, -50)  # Hart's own 50 hPa levels, 1000 down to 300
NEEDED_LEVELS = sorted(set(P50.tolist()) | set(LEVELS), reverse=True)

DIPOLE_L_KM = 400.0  # across-track length scale of the storm-attached asymmetry
DIPOLE_PEAK_AMP = 65.0  # m; tuned below so Hart's B peaks near 40 m

RED = "#e34948"
BLUE = "#2a78d6"
PURPLE = "#8e44ad"

CLASS_PALETTE = {
    0: (0.85, 0.15, 0.15),
    1: (0.80, 0.20, 0.75),
    2: (0.98, 0.85, 0.10),
    3: (0.20, 0.68, 0.25),
    4: (0.15, 0.50, 0.90),
    5: (0.35, 0.22, 0.72),
    6: (0.72, 0.72, 0.70),
}
CLASS_NAMES = {
    0: "symmetric deep warm core",
    1: "symmetric shallow warm core",
    2: "frontal deep warm core",
    3: "frontal shallow warm core",
    4: "frontal cold core",
    5: "symmetric cold core",
    6: "shallow cold core",
}


# ---------------------------------------------------------------- track
def cosine_blend(x):
    """Smooth 0 to 1 ease, clipped outside [0, 1]."""
    return 0.5 * (1.0 - np.cos(np.pi * np.clip(x, 0.0, 1.0)))


def speed_profile(t):
    """Storm translation speed (m/s): 4 m/s at t=0, most of the rise
    held back until late, reaching 16 m/s at t=120 h (a steep power-law
    ramp, not a straight ramp, so the storm is genuinely slow for most
    of the first 120 h and only accelerates hard near recurvature),
    then easing back to 6 m/s by 168 h as the secluded low slows down.
    """
    if t <= 120.0:
        return 4.0 + (16.0 - 4.0) * (t / 120.0) ** 6.5
    return 16.0 + (6.0 - 16.0) * cosine_blend((t - 120.0) / 48.0)


def heading_profile(t):
    """Heading (degrees, clockwise from north): north-northwest (-22.5,
    i.e. 337.5) until the recurve starts at t=24 h, easing to northeast
    (46) by t=120 h, held thereafter.
    """
    return -22.5 + (46.0 - (-22.5)) * cosine_blend((t - 24.0) / (120.0 - 24.0))


def build_track(hours):
    """Integrate speed_profile/heading_profile (fine sub-steps between
    the 6 h output frames) into a lat/lon track starting at 22N, 150E.
    """
    lat, lon = 22.0, 150.0
    lats, lons = [lat], [lon]
    for i in range(1, len(hours)):
        t0, t1 = hours[i - 1], hours[i]
        nsub = 60
        dt_s = (t1 - t0) * 3600.0 / nsub
        for k in range(nsub):
            tt = t0 + (t1 - t0) * (k + 0.5) / nsub
            spd = speed_profile(tt)
            hdg = heading_profile(tt)
            dx_km = spd * dt_s / 1000.0 * np.sin(np.radians(hdg))
            dy_km = spd * dt_s / 1000.0 * np.cos(np.radians(hdg))
            lat += dy_km / 111.32
            lon += dx_km / (111.32 * np.cos(np.radians(lat)))
        lats.append(lat)
        lons.append(lon)
    return np.array(lats), np.array(lons)


# ------------------------------------------------------- height field
def blended_amp(t):
    """dZ(p) amplitude at the eight archetype anchor pressures, cosine
    blended between band_comparison.ARCHETYPES across the four life
    cycle stages.
    """
    a = ARCHETYPES
    if t <= 48.0:
        return np.array(a["deep warm core (mature typhoon)"], float)
    if t <= 96.0:
        w = cosine_blend((t - 48.0) / (96.0 - 48.0))
        lo, hi = a["deep warm core (mature typhoon)"], a["transitioning (warm below 850)"]
    elif t <= 126.0:
        w = cosine_blend((t - 96.0) / (126.0 - 96.0))
        lo, hi = a["transitioning (warm below 850)"], a["deep cold core (extratropical)"]
    else:
        w = cosine_blend((t - 126.0) / (168.0 - 126.0))
        lo, hi = a["deep cold core (extratropical)"], a["shallow warm core (seclusion)"]
    return (1.0 - w) * np.array(lo, float) + w * np.array(hi, float)


def scale_km_of(t):
    """Vortex e-folding radius (km): 150 km at t=0 growing linearly to
    350 km at t=168 h, as the circulation broadens during transition.
    """
    return 150.0 + (350.0 - 150.0) * (t / 168.0)


def amp_interp(anchor_vals, p):
    """dZ at pressure p (hPa), linear in ln p between ANCHOR_P."""
    xa = np.log(ANCHOR_P.astype(float))
    x = np.log(float(p))
    return float(np.interp(x, xa[::-1], np.asarray(anchor_vals, float)[::-1]))


def g_of_p(p, g0=4.0):
    """Background meridional gradient strength (m), growing with height."""
    return g0 * (1.0 + 1.5 * np.log(1000.0 / p))


def s_of_lat(lat2d):
    """The meridional gradient's own shape: a smooth step, 0 south of
    30N, 1 north of 40N (so the local dHeight/dlat contributed by the
    background is 0 below 30N, g(p) above 40N, and eases between).
    """
    x = np.clip((lat2d - 30.0) / 10.0, 0.0, 1.0)
    return 0.5 * (1.0 - np.cos(np.pi * x))


def s_of_lat_integral(lat2d):
    """Antiderivative of s_of_lat with respect to latitude (in degrees),
    zero south of 30N: background(p, lat) = g(p) * s_of_lat_integral(lat)
    is the field whose own meridional gradient is g(p) * s_of_lat(lat),
    per the task's specification -- a field that is flat (no gradient)
    south of 30N, ramps up through the 30-40N transition zone, and above
    40N keeps growing at the full g(p) m/degree rate, the way a real
    mid-latitude baroclinic zone the storm is recurving into does not
    stop at any one latitude.
    """
    lat2d = np.asarray(lat2d, dtype=float)
    u = np.clip((lat2d - 30.0) / 10.0, 0.0, 1.0)
    ramp = 5.0 * (u - np.sin(np.pi * u) / np.pi)  # integral of s_of_lat over the 30-40N ramp
    beyond = np.clip(lat2d - 40.0, 0.0, None)
    return ramp + beyond


def height_field(p, lat2d, lon2d, clat, clon, scale_km_val, anchor_vals):
    amp_p = amp_interp(anchor_vals, p)
    r = dist_km(lat2d, lon2d, clat, clon)
    shape = np.exp(-((r / scale_km_val) ** 2))
    bg = g_of_p(p) * s_of_lat_integral(lat2d)
    return std_height(p) - amp_p * shape - bg


# ----------------------------------------------- storm-attached asymmetry
def s_of_p(p):
    """0 at 1000 hPa, rising linearly in ln p to 1 at 600 hPa, held at 1
    above (i.e. for p <= 600 hPa): the dipole's own vertical shape, so it
    only touches the lower/mid troposphere the way a real frontal
    thickness dipole does.
    """
    x = (np.log(1000.0) - np.log(p)) / (np.log(1000.0) - np.log(600.0))
    return float(np.clip(x, 0.0, 1.0))


def dipole_amplitude(t, peak=DIPOLE_PEAK_AMP):
    """A(t): 0 until 24 h, a cosine ramp up to its peak at 72 h, held to
    108 h, a cosine decay back to 0 by 144 h as the warm air is wrapped
    into the seclusion and the asymmetry disappears again. Ramped
    earlier than an initial 36/84/108/144 h draft so the frontal deep
    warm core (class 2, B > 10 m with both thermal winds still warm)
    falls inside a printed 6 h frame instead of being aliased out
    between two samples.
    """
    if t <= 24.0:
        return 0.0
    if t <= 72.0:
        return peak * cosine_blend((t - 24.0) / (72.0 - 24.0))
    if t <= 108.0:
        return peak
    if t <= 144.0:
        return peak * (1.0 - cosine_blend((t - 108.0) / (144.0 - 108.0)))
    return 0.0


def local_offsets_km(lat2d, lon2d, clat, clon):
    """East (dx_km) and north (dy_km) offsets of every grid point from a
    center, flat local Cartesian, matching cps.hart.local_offsets_km's
    own convention.
    """
    r_earth = 6371.0
    dlon = ((np.asarray(lon2d, float) - clon + 180.0) % 360.0) - 180.0
    dx_km = r_earth * np.cos(np.radians(clat)) * np.radians(dlon)
    dy_km = r_earth * np.radians(np.asarray(lat2d, float) - clat)
    return dx_km, dy_km


def across_track_km(lat2d, lon2d, clat, clon, heading_deg, speed_ms):
    """(x_R, r): the across-track coordinate (km, positive to the right
    of the motion vector, using cps_HartCPS.parameter_b_grid's own
    right-hand normal (v, -u)/speed so both methods agree on "right")
    and the plain radial distance (km) from the storm center, for every
    grid point.
    """
    dx_km, dy_km = local_offsets_km(lat2d, lon2d, clat, clon)
    u = speed_ms * np.sin(np.radians(heading_deg))
    v = speed_ms * np.cos(np.radians(heading_deg))
    spd = np.hypot(u, v)
    if spd <= 0.0:
        nrx, nry = 0.0, 0.0
    else:
        nrx, nry = v / spd, -u / spd
    x_r = dx_km * nrx + dy_km * nry
    r = np.hypot(dx_km, dy_km)
    return x_r, r


def dipole_coefficient(t, x_r, r):
    """A(t) * (x_R / L) * exp(-r^2 / (2 L^2)): the part of dZ_dipole that
    does not depend on level, shared by every pressure level (each level
    just scales it by its own s_of_p(p)). Positive on the right of the
    track (x_R > 0), so thickness (900-600, or 925-700) -- warmer/thicker
    where the perturbation is more positive at 600/700 than at 900/925,
    since s_of_p grows with height -- ends up larger on the right,
    giving B > 0 in the Northern Hemisphere, per cps.hart.parameter_b's
    and cps_HartCPS's own sign convention.
    """
    a_t = dipole_amplitude(t)
    if a_t == 0.0:
        return np.zeros_like(r)
    return a_t * (x_r / DIPOLE_L_KM) * np.exp(-(r ** 2) / (2.0 * DIPOLE_L_KM ** 2))


def build_heights(t, clat, clon, lat2d, lon2d, heading_deg, speed_ms, levels):
    """Height (m) on every pressure level in `levels`, at time `t` (h)
    for a storm centered at (clat, clon) moving (heading_deg, speed_ms):
    vortex + baroclinic background (height_field) plus the storm-attached
    dipole. Factored out so the main loop and the peak-frame diagnostic
    build the exact same fields.
    """
    anchor = blended_amp(t)
    scale_km_val = scale_km_of(t)
    x_r, r_dipole = across_track_km(lat2d, lon2d, clat, clon, heading_deg, speed_ms)
    dipole_coef = dipole_coefficient(t, x_r, r_dipole)
    return {
        p: height_field(p, lat2d, lon2d, clat, clon, scale_km_val, anchor) + s_of_p(p) * dipole_coef
        for p in levels
    }


# --------------------------------------------------------------- main
def main():
    hours = np.arange(0.0, 168.0 + 1e-9, 6.0)
    n = len(hours)
    lats, lons = build_track(hours)
    headings, speeds = ch.track_motion(lats, lons, hours * 3600.0)
    u_mot = speeds * np.sin(np.radians(headings))
    v_mot = speeds * np.cos(np.radians(headings))

    print(f"Track: {n} frames, 0 to 168 h, 6 h steps")
    print(f"  start {lats[0]:.2f}N {lons[0]:.2f}E, end {lats[-1]:.2f}N {lons[-1]:.2f}E "
          f"(target: 22N 150E to near 52N 175E)")
    print(f"  lat range {lats.min():.2f} to {lats.max():.2f}, lon range {lons.min():.2f} to {lons.max():.2f}")

    lat_vals, lon_vals, lat2d, lon2d, dx, dy = make_grid(0.25, lat0=15.0, lat1=60.0, lon0=140.0, lon1=190.0)
    margin_lat = min(lats.min() - lat_vals.min(), lat_vals.max() - lats.max())
    margin_lon = min(lons.min() - lon_vals.min(), lon_vals.max() - lons.max())
    print(f"  grid: {lat2d.shape[0]} x {lat2d.shape[1]} at 0.25 deg, "
          f"lat {lat_vals.min():.1f} to {lat_vals.max():.1f}, lon {lon_vals.min():.1f} to {lon_vals.max():.1f}")
    print(f"  smallest margin between track and grid edge: {min(margin_lat, margin_lon) * 111.0:.0f} km "
          f"(need > {RADIUS_KM:.0f} km for the 500 km window to never touch the edge)")

    psfc = np.full(lat2d.shape, 1013.0)
    coriolis = np.full(lat2d.shape, 1.0)  # storm stays in the Northern Hemisphere throughout

    B_hart = np.full(n, np.nan)
    VTL_hart = np.full(n, np.nan)
    VTU_hart = np.full(n, np.nan)
    B_grid = np.full(n, np.nan)
    VTL_grid = np.full(n, np.nan)
    VTU_grid = np.full(n, np.nan)
    CLS_grid = np.full(n, np.nan)
    CLS_hart = np.full(n, np.nan)

    for i, t in enumerate(hours):
        clat, clon = float(lats[i]), float(lons[i])
        # x_R = 0 at the center, so the dipole leaves the center-point VTL/VTU unchanged.
        z = build_heights(t, clat, clon, lat2d, lon2d, headings[i], speeds[i], NEEDED_LEVELS)

        # -- Hart: circular window, storm-centered, 50 hPa levels
        z_stack = np.stack([z[p] for p in P50], axis=0)
        tw = ch.thermal_wind(P50.tolist(), z_stack, lat2d, lon2d, clat, clon, radius_km=RADIUS_KM)
        VTL_hart[i] = tw["VTL"]
        VTU_hart[i] = tw["VTU"]
        B_hart[i] = ch.parameter_b(z[900], z[600], lat2d, lon2d, clat, clon, heading_deg=headings[i], radius_km=RADIUS_KM)
        # Hart's own class: the same seven-code rule cps_HartCPS.hart_class applies to the
        # gridded fields, applied here to Hart's three storm-centered scalars for this one
        # frame (1-element arrays in, `mask=True` since there is no closed-low mask concept
        # for a storm-centered point, only for a gridded field).
        CLS_hart[i] = hc.hart_class(
            np.array([B_hart[i]]), np.array([VTL_hart[i]]), np.array([VTU_hart[i]]), np.array([True]),
            hc.B_THRESHOLD_M,
        )[0]

        # -- gridded: square window, pointwise, standard levels
        u_arr = np.full(lat2d.shape, u_mot[i])
        v_arr = np.full(lat2d.shape, v_mot[i])
        vtl_full = hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy, RADIUS_KM, 925.0, 850.0, 700.0)
        vtu_full = hc.executeBand3(z[500], z[400], z[300], psfc, dx, dy, RADIUS_KM, 500.0, 400.0, 300.0)
        b_full = hc.executeB(
            z[925], z[700],
            u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
            psfc, coriolis, dx, dy, radiusKm=RADIUS_KM, layerScale=hc.HART_B_LAYER_SCALE,
        )
        cls_full = hc.executeHartClass(
            z[1000], z[925], z[850], z[700], z[500], z[400], z[300],
            u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
            psfc, coriolis, dx, dy, radiusKm=RADIUS_KM,
        )

        ci = int(np.argmin(np.abs(lat_vals - clat)))
        cj = int(np.argmin(np.abs(lon_vals - clon)))
        VTL_grid[i] = vtl_full[ci, cj]
        VTU_grid[i] = vtu_full[ci, cj]
        B_grid[i] = b_full[ci, cj]
        CLS_grid[i] = cls_full[ci, cj]

    # ---------------------------------------------------------- table
    print()
    header = f"{'hour':>5} {'lat':>6} {'lon':>7} {'spd':>5}  {'B_hart':>7} {'VTL_hart':>9} {'VTU_hart':>9}  {'B_grid':>7} {'VTL_grid':>9} {'VTU_grid':>9}  {'class':>5}"
    print(header)
    print("-" * len(header))
    for i, t in enumerate(hours):
        cls = CLS_grid[i]
        cls_str = f"{cls:.0f}" if np.isfinite(cls) else "nan"
        print(
            f"{t:5.0f} {lats[i]:6.2f} {lons[i]:7.2f} {speeds[i]:5.1f}  "
            f"{B_hart[i]:7.1f} {VTL_hart[i]:9.1f} {VTU_hart[i]:9.1f}  "
            f"{B_grid[i]:7.1f} {VTL_grid[i]:9.1f} {VTU_grid[i]:9.1f}  {cls_str:>5}"
        )

    def first_cross(arr, op, thresh):
        idx = np.where(op(arr, thresh))[0]
        return hours[idx[0]] if idx.size else float("nan")

    def first_cross_after_peak(arr, op, thresh):
        """First hour, after the array's own peak, where op(arr, thresh)
        holds -- used for "B falls back under 10 m" (which must be
        looked for after the peak, not the first low value near t=0).
        """
        peak_idx = int(np.nanargmax(arr))
        tail = arr[peak_idx:]
        idx = np.where(op(tail, thresh))[0]
        return hours[peak_idx + idx[0]] if idx.size else float("nan")

    onset_hart = first_cross(B_hart, np.greater, 10.0)
    onset_grid = first_cross(B_grid, np.greater, 10.0)
    completion_hart = first_cross(VTL_hart, np.less, 0.0)
    completion_grid = first_cross(VTL_grid, np.less, 0.0)
    fall_below_hart = first_cross_after_peak(B_hart, np.less, 10.0)
    fall_below_grid = first_cross_after_peak(B_grid, np.less, 10.0)

    rms = {}
    for name, hart_arr, grid_arr in (("B", B_hart, B_grid), ("VTL", VTL_hart, VTL_grid), ("VTU", VTU_hart, VTU_grid)):
        diff = grid_arr - hart_arr
        rms[name] = float(np.sqrt(np.nanmean(diff ** 2)))

    deep_mask = hours <= 48.0
    ratio_lower_deep = float(np.nanmean(VTL_grid[deep_mask]) / np.nanmean(VTL_hart[deep_mask]))

    peak_idx_hart = int(np.nanargmax(B_hart))
    peak_idx_grid = int(np.nanargmax(B_grid))
    b_peak_ratio = float(B_grid[peak_idx_grid] / B_hart[peak_idx_hart])

    print()
    print(f"Onset (B first exceeds 10 m):          Hart {onset_hart:.0f} h,  gridded {onset_grid:.0f} h")
    print(f"Completion (VTL first turns negative): Hart {completion_hart:.0f} h,  gridded {completion_grid:.0f} h")
    print(f"B falls back under 10 m (after the peak): Hart {fall_below_hart:.0f} h,  gridded {fall_below_grid:.0f} h")
    print()
    print(f"B peak: Hart {B_hart[peak_idx_hart]:.1f} m at {hours[peak_idx_hart]:.0f} h,  "
          f"gridded {B_grid[peak_idx_grid]:.1f} m at {hours[peak_idx_grid]:.0f} h")
    print(f"Ratio of the gridded B peak to the Hart B peak: {b_peak_ratio:.3f}")
    print()
    print("RMS difference between methods over the life cycle (gridded minus Hart):")
    print(f"  B:   {rms['B']:6.2f} m")
    print(f"  VTL: {rms['VTL']:6.2f} m")
    print(f"  VTU: {rms['VTU']:6.2f} m")
    print()
    print(f"Ratio gridded/Hart of the lower term during the deep warm core phase (0 to 48 h): {ratio_lower_deep:.3f}")

    n_nan_hart = int(np.sum(~np.isfinite(VTL_hart) | ~np.isfinite(B_hart)))
    n_nan_grid = int(np.sum(~np.isfinite(VTL_grid) | ~np.isfinite(B_grid)))
    n_nan_cls = int(np.sum(~np.isfinite(CLS_grid)))
    print()
    print(f"NaN frames: Hart {n_nan_hart}, gridded B/VTL/VTU {n_nan_grid}, gridded class {n_nan_cls}")

    def print_class_sequence(label, cls_arr):
        print(f"\n{label} class sequence (consecutive hours sharing a class):")
        seq_start = 0
        for i in range(1, n + 1):
            if i == n or cls_arr[i] != cls_arr[seq_start]:
                cls = cls_arr[seq_start]
                if np.isfinite(cls):
                    name = CLASS_NAMES[int(round(cls))]
                    print(f"  {hours[seq_start]:.0f} to {hours[i - 1]:.0f} h: class {cls:.0f} ({name})")
                else:
                    print(f"  {hours[seq_start]:.0f} to {hours[i - 1]:.0f} h: nan")
                seq_start = i

    print_class_sequence("Gridded", CLS_grid)
    print_class_sequence("Hart", CLS_hart)

    # -- window-geometry vs. layer diagnostic at the frame of Hart's B peak:
    # gridded B there (executeB's own window-mean-of-gradient method, 925-700 hPa x
    # lambda) versus Hart's true semicircle-difference method evaluated on that SAME
    # 925-700 hPa layer x lambda (isolates the window-geometry effect, same layer) versus
    # Hart's own native 900-600 hPa semicircle B (isolates the layer effect, same method).
    t_peak = float(hours[peak_idx_hart])
    clat_peak, clon_peak = float(lats[peak_idx_hart]), float(lons[peak_idx_hart])
    z_peak = build_heights(t_peak, clat_peak, clon_peak, lat2d, lon2d, headings[peak_idx_hart], speeds[peak_idx_hart], [925, 700])
    b_hart_925_700 = ch.parameter_b(
        z_peak[925], z_peak[700], lat2d, lon2d, clat_peak, clon_peak,
        heading_deg=headings[peak_idx_hart], radius_km=RADIUS_KM,
    ) * hc.HART_B_LAYER_SCALE

    print()
    print(f"Window-geometry versus layer diagnostic at the Hart B peak frame (hour {t_peak:.0f}):")
    print(f"  gridded B (window-mean-of-gradient method, 925-700 hPa x lambda):        {B_grid[peak_idx_hart]:7.1f} m")
    print(f"  Hart semicircle-difference method, SAME 925-700 hPa layer x lambda:      {b_hart_925_700:7.1f} m")
    print(f"  Hart semicircle-difference method, native 900-600 hPa layer (no rescale): {B_hart[peak_idx_hart]:7.1f} m")
    print(f"  gridded / Hart-on-same-layer (window geometry only):  {B_grid[peak_idx_hart] / b_hart_925_700:.3f}")
    print(f"  Hart 925-700(x lambda) / Hart 900-600 (layer only, both semicircle):     {b_hart_925_700 / B_hart[peak_idx_hart]:.3f}")

    make_figure(hours, lats, lons, B_hart, VTL_hart, VTU_hart, B_grid, VTL_grid, VTU_grid, CLS_grid, CLS_hart,
                onset_hart, onset_grid, completion_hart, completion_grid)


# ------------------------------------------------------------- figure
def make_figure(hours, lats, lons, B_hart, VTL_hart, VTU_hart, B_grid, VTL_grid, VTU_grid, CLS_grid, CLS_hart,
                 onset_hart, onset_grid, completion_hart, completion_grid):
    cmap_hart = LinearSegmentedColormap.from_list("hart_gray", ["#c9c9c9", "#000000"])
    cmap_grid = LinearSegmentedColormap.from_list("grid_red", ["#fbdede", RED])

    def pad_limits(ax, frac=0.22):
        """Expand xlim/ylim by frac of the data range, so corner labels
        placed in axes-fraction coordinates land in blank space instead
        of on top of the data itself."""
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        dx, dy = x1 - x0, y1 - y0
        ax.set_xlim(x0 - frac * dx, x1 + frac * dx)
        ax.set_ylim(y0 - frac * dy, y1 + frac * dy)

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.0))

    # -- (a) B vs -VTL (Hart's Phase 1 diagram)
    ax = axes[0]
    ax.plot(VTL_hart, B_hart, "-", color="0.75", lw=1.0, zorder=1)
    ax.plot(VTL_grid, B_grid, "-", color=RED, alpha=0.35, lw=1.0, zorder=1)
    ax.scatter(VTL_hart, B_hart, c=hours, cmap=cmap_hart, s=32, marker="o", zorder=3, edgecolor="white", linewidth=0.4)
    ax.scatter(VTL_grid, B_grid, c=hours, cmap=cmap_grid, s=32, marker="s", zorder=4, edgecolor="white", linewidth=0.4)
    ax.axhline(10.0, color="k", lw=0.8, ls="--")
    ax.axvline(0.0, color="k", lw=0.8, ls="--")
    ax.set_xlabel("$-V_T^L$ (m)")
    ax.set_ylabel("B (m)")
    ax.set_title("(a) B versus $-V_T^L$", loc="left", fontsize=10)
    pad_limits(ax)
    ax.text(0.03, 0.03, "symmetric\ncold", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="left", va="bottom")
    ax.text(0.97, 0.03, "symmetric\nwarm", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="right", va="bottom")
    ax.text(0.97, 0.97, "frontal\nwarm", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="right", va="top")
    ax.text(0.03, 0.97, "frontal\ncold", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="left", va="top")

    # -- (b) -VTU vs -VTL (Hart's Phase 2 diagram)
    ax = axes[1]
    ax.plot(VTL_hart, VTU_hart, "-", color="0.75", lw=1.0, zorder=1)
    ax.plot(VTL_grid, VTU_grid, "-", color=RED, alpha=0.35, lw=1.0, zorder=1)
    ax.scatter(VTL_hart, VTU_hart, c=hours, cmap=cmap_hart, s=32, marker="o", zorder=3, edgecolor="white", linewidth=0.4)
    ax.scatter(VTL_grid, VTU_grid, c=hours, cmap=cmap_grid, s=32, marker="s", zorder=4, edgecolor="white", linewidth=0.4)
    ax.axhline(0.0, color="k", lw=0.8, ls="--")
    ax.axvline(0.0, color="k", lw=0.8, ls="--")
    ax.set_xlabel("$-V_T^L$ (m)")
    ax.set_ylabel("$-V_T^U$ (m)")
    ax.set_title("(b) $-V_T^U$ versus $-V_T^L$", loc="left", fontsize=10)
    pad_limits(ax)
    ax.text(0.03, 0.03, "deep\ncold", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="left", va="bottom")
    ax.text(0.97, 0.03, "shallow\nwarm", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="right", va="bottom")
    ax.text(0.97, 0.97, "deep\nwarm", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="right", va="top")
    ax.text(0.03, 0.97, "shallow\ncold", transform=ax.transAxes, fontsize=6.5, color="0.35", ha="left", va="top")

    handles = [
        Line2D([0], [0], marker="o", color="0.4", lw=1.0, markersize=6, label="Hart, circular window"),
        Line2D([0], [0], marker="s", color=RED, lw=1.0, markersize=6, label="gridded, square window"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=2, fontsize=8, bbox_to_anchor=(0.5, 1.0), frameon=False)

    # -- (c) time series, with the gridded class as a strip along the top
    ax = axes[2]
    ax.plot(hours, B_hart, "--", color=PURPLE, lw=1.2, label="B, Hart")
    ax.plot(hours, B_grid, "-", color=PURPLE, lw=1.2, label="B, gridded")
    ax.plot(hours, VTL_hart, "--", color=RED, lw=1.2, label="$-V_T^L$, Hart")
    ax.plot(hours, VTL_grid, "-", color=RED, lw=1.2, label="$-V_T^L$, gridded")
    ax.plot(hours, VTU_hart, "--", color=BLUE, lw=1.2, label="$-V_T^U$, Hart")
    ax.plot(hours, VTU_grid, "-", color=BLUE, lw=1.2, label="$-V_T^U$, gridded")
    ax.axhline(0.0, color="k", lw=0.6)
    ax.set_xlabel("hour")
    ax.set_ylabel("m")
    ax.set_title("(c) time series and class (Hart and gridded)", loc="left", fontsize=10)
    right_pad = 0.16 * (hours.max() - hours.min())
    ax.set_xlim(hours.min(), hours.max() + right_pad)

    # Fixed data-coordinate headroom above the curves (which never exceed 302 m), so
    # the class strips, ticks and labels below live in their own blank band and cannot
    # be crossed by -VTL/-VTU/B, wherever those happen to sit. y ticks stay at -300..300.
    ax.set_ylim(-330.0, 470.0)
    ax.set_yticks([-300, -200, -100, 0, 100, 200, 300])
    ax.set_autoscaley_on(False)

    GRID_STRIP_Y = (420.0, 465.0)
    HART_STRIP_Y = (370.0, 415.0)
    TICK_BAND_Y = (320.0, 360.0)
    TICK_LABEL_Y = 312.0

    # Two class strips: gridded on top, Hart just below it, same palette, row-labeled
    # beside the strips in the margin opened up on the right by right_pad.
    strip_rows = (("gridded", CLS_grid, GRID_STRIP_Y), ("Hart", CLS_hart, HART_STRIP_Y))
    for label, cls_arr, (y0, y1) in strip_rows:
        for h, cls in zip(hours, cls_arr):
            if not np.isfinite(cls):
                continue
            ax.add_patch(Rectangle((h - 3.0, y0), 6.0, y1 - y0, facecolor=CLASS_PALETTE[int(round(cls))],
                                    edgecolor="none", zorder=2))
        ax.text(hours.max() + 0.08 * right_pad, (y0 + y1) / 2.0, label, fontsize=8, color="0.2",
                ha="left", va="center")

    # Onset/completion ticks in their own data-coordinate band above the strips'
    # blank gap, dashed for Hart, solid for gridded, one small centered label per pair.
    y0, y1 = TICK_BAND_Y
    tick_kw = dict(lw=1.6)
    if np.isfinite(onset_hart):
        ax.plot([onset_hart, onset_hart], [y0, y1], color=PURPLE, ls="--", **tick_kw)
    if np.isfinite(onset_grid):
        ax.plot([onset_grid, onset_grid], [y0, y1], color=PURPLE, ls="-", **tick_kw)
    if np.isfinite(completion_hart):
        ax.plot([completion_hart, completion_hart], [y0, y1], color=RED, ls="--", **tick_kw)
    if np.isfinite(completion_grid):
        ax.plot([completion_grid, completion_grid], [y0, y1], color=RED, ls="-", **tick_kw)
    if np.isfinite(onset_hart) and np.isfinite(onset_grid):
        ax.text((onset_hart + onset_grid) / 2.0, TICK_LABEL_Y, "onset", fontsize=7, color=PURPLE,
                ha="center", va="top")
    if np.isfinite(completion_hart) and np.isfinite(completion_grid):
        ax.text((completion_hart + completion_grid) / 2.0, TICK_LABEL_Y, "completion", fontsize=7, color=RED,
                ha="center", va="top")

    style_handles = [
        Line2D([0], [0], color="0.25", lw=1.4, ls="--", label="Hart (dashed)"),
        Line2D([0], [0], color="0.25", lw=1.4, ls="-", label="gridded (solid)"),
    ]
    param_handles, param_labels = ax.get_legend_handles_labels()
    ax.legend(handles=style_handles + param_handles, labels=[h.get_label() for h in style_handles] + param_labels,
              fontsize=6, loc="lower left", ncol=1, framealpha=0.9)

    # Re-applied last, with autoscale explicitly turned off on both axes: the Rectangle/
    # plot/text calls above (and tight_layout's own internal draw pass) otherwise
    # re-trigger matplotlib's autoscale-view on the next draw and quietly undo the
    # right margin and the fixed headroom the strips/ticks/labels rely on.
    ax.set_xlim(hours.min(), hours.max() + right_pad)
    ax.set_ylim(-330.0, 470.0)
    ax.set_autoscalex_on(False)
    ax.set_autoscaley_on(False)

    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))
    out = HERE / "figD_lifecycle.png"
    fig.savefig(out, dpi=300)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
