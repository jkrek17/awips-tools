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
   `cyclone_phase_space/D2D/derivedParameters/functions/cps_HartCPS.py`
   (`executeBand3`, `executeB`, `executeHartClass`) on the seven
   standard levels (1000/925/850/700/500/400/300 hPa), sampled at the
   grid point nearest the storm center.

Both methods are handed the same storm motion (finite difference of the
track, via `cps.track_motion`), and both take the max/min over the same
500 km circle (the gridded module's WINDOW_SHAPE "circle"), so any
difference between their thermal wind terms is the standard-level versus
50 hPa band difference (and the grid's discretization of the disk), not
a difference in motion or window.

The height field is the sum of an axisymmetric vortex (which the storm
center itself sees as flat, contributing nothing to B there) plus a
baroclinic environment (a meridional gradient the storm meets as it
crosses 30-40N) plus a storm-attached, motion-relative thickness dipole
(cold to the left of the track, warm to the right), so the storm
actually passes through Hart's asymmetric classes (B > 10 m) the way a
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

Scenarios. The life cycle above is the first of several named archetypes
in SCENARIOS (see Scenario and the scenario_* functions, whose docstrings
describe each one's fields): the extratropical transition of a tropical
cyclone (the default everywhere, and the only one main() and
figD_lifecycle.png use), a tropical cyclone that decays without
transition, a warm seclusion, a cold-core low that occludes, the tropical
transition of a subtropical storm, and a hybrid oscillating about
B = 10 m. Each is built from the same ingredients (vortex amplitude at the
anchor levels, vortex radius, storm-attached dipole, background gradient,
track and motion) and computed by the same per-frame loop (run_scenario,
compute_frame). To print every scenario's class sequence, onset and
completion hours and plane crossings (no figure):

    python3 lifecycle_comparison.py --scenarios [key ...]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent  # article/figures -> article -> cyclone_phase_space
sys.path.insert(0, str(REPO_ROOT / "D2D" / "derivedParameters" / "functions"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

import cps_HartCPS as hc  # noqa: E402
import cps as ch  # noqa: E402
from experiments import make_grid, dist_km, std_height, LEVELS, ANCHOR_P  # noqa: E402
from band_comparison import ARCHETYPES  # noqa: E402
import diagram_style as ds  # noqa: E402  (make_fig10's own quadrant colors/labels/lines/limits)

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
    2: "asymmetric deep warm core",
    3: "asymmetric shallow warm core",
    4: "asymmetric cold core",
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


def build_track(hours, scenario=None):
    """Integrate the scenario's speed and heading profiles (fine sub-steps
    between the 6 h output frames) into a lat/lon track from the
    scenario's start. The default scenario (extratropical transition)
    integrates speed_profile/heading_profile from 22N, 150E.
    """
    sc = get_scenario(scenario)
    lat, lon = sc.start
    lats, lons = [lat], [lon]
    for i in range(1, len(hours)):
        t0, t1 = hours[i - 1], hours[i]
        nsub = 60
        dt_s = (t1 - t0) * 3600.0 / nsub
        for k in range(nsub):
            tt = t0 + (t1 - t0) * (k + 0.5) / nsub
            spd = sc.speed(tt)
            hdg = sc.heading(tt)
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


def height_field(p, lat2d, lon2d, clat, clon, scale_km_val, anchor_vals, g0=4.0):
    amp_p = amp_interp(anchor_vals, p)
    r = dist_km(lat2d, lon2d, clat, clon)
    shape = np.exp(-((r / scale_km_val) ** 2))
    bg = g_of_p(p, g0) * s_of_lat_integral(lat2d)
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
    earlier than an initial 36/84/108/144 h draft so the asymmetric deep
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


def dipole_coefficient(t, x_r, r, amplitude=None):
    """A(t) * (x_R / L) * exp(-r^2 / (2 L^2)): the part of dZ_dipole that
    does not depend on level, shared by every pressure level (each level
    just scales it by its own s_of_p(p)). Positive on the right of the
    track (x_R > 0), so thickness (900-600, or 925-700) -- warmer/thicker
    where the perturbation is more positive at 600/700 than at 900/925,
    since s_of_p grows with height -- ends up larger on the right,
    giving B > 0 in the Northern Hemisphere, per cps.hart.parameter_b's
    and cps_HartCPS's own sign convention. `amplitude` is the A(t)
    profile (m); the default is the extratropical transition's
    dipole_amplitude.
    """
    a_t = dipole_amplitude(t) if amplitude is None else amplitude(t)
    if a_t == 0.0:
        return np.zeros_like(r)
    return a_t * (x_r / DIPOLE_L_KM) * np.exp(-(r ** 2) / (2.0 * DIPOLE_L_KM ** 2))


def build_heights(t, clat, clon, lat2d, lon2d, heading_deg, speed_ms, levels, scenario=None):
    """Height (m) on every pressure level in `levels`, at time `t` (h)
    for a storm centered at (clat, clon) moving (heading_deg, speed_ms):
    vortex + baroclinic background (height_field) plus the storm-attached
    dipole, each from the scenario's own profiles (default: the
    extratropical transition). Factored out so the main loop and the
    peak-frame diagnostic build the exact same fields.
    """
    sc = get_scenario(scenario)
    anchor = sc.amp(t)
    scale_km_val = sc.scale_km(t)
    x_r, r_dipole = across_track_km(lat2d, lon2d, clat, clon, heading_deg, speed_ms)
    dipole_coef = dipole_coefficient(t, x_r, r_dipole, sc.dipole)
    return {
        p: height_field(p, lat2d, lon2d, clat, clon, scale_km_val, anchor, sc.g0) + s_of_p(p) * dipole_coef
        for p in levels
    }


# ------------------------------------------------------------ scenarios
# A scenario is one synthetic life cycle, written entirely as the ingredients
# of the height field and the track, each a function of the hour t: the
# vortex's height-perturbation amplitude at the eight ANCHOR_P levels (m,
# positive for a depression; warm core where it shrinks upward, cold core
# where it grows upward), its e-folding radius, the amplitude A(t) of the
# storm-attached motion-relative thickness dipole (the frontal asymmetry that
# B measures, warm to the right of the track), the strength g0 of the
# meridional background gradient of the 30-40N baroclinic zone, and the track
# (start point, speed and heading). Every scenario goes through the same
# build_heights/compute_frame, so its phase-space path is whatever Hart's
# method and the gridded module read from those fields, not a drawn curve.
# The first scenario is the extratropical transition above, unchanged.

@dataclass(frozen=True)
class Scenario:
    """The ingredients of one synthetic life cycle (see the comment above).

    amp(t) returns the eight anchor amplitudes (m) at ANCHOR_P; scale_km(t)
    the vortex e-folding radius (km); dipole(t) the dipole amplitude A(t)
    (m); speed(t) (m/s) and heading(t) (degrees clockwise from north) the
    motion integrated by build_track from `start` (lat, lon); g0 the
    background gradient strength handed to g_of_p (m per degree of latitude
    at 1000 hPa, growing with height). `summary` is one line for listings.
    """
    key: str
    title: str
    amp: Callable[[float], np.ndarray]
    scale_km: Callable[[float], float]
    dipole: Callable[[float], float]
    speed: Callable[[float], float]
    heading: Callable[[float], float]
    start: tuple
    g0: float = 4.0
    summary: str = ""


def staged(*knots):
    """t -> value from (hour, value) knots: the first value held until its
    hour, cosine blends (cosine_blend) between consecutive knots, the last
    value held after its hour. Values may be scalars or anchor profiles.
    """
    ks = [(float(h), np.asarray(v, dtype=float)) for h, v in knots]

    def f(t):
        if t <= ks[0][0]:
            out = ks[0][1]
        elif t >= ks[-1][0]:
            out = ks[-1][1]
        else:
            for (h0, v0), (h1, v1) in zip(ks, ks[1:]):
                if t <= h1:
                    w = cosine_blend((t - h0) / (h1 - h0))
                    out = (1.0 - w) * v0 + w * v1
                    break
        return float(out) if out.ndim == 0 else out.copy()
    return f


# Anchor profiles (m at ANCHOR_P = 1000, 925, 850, 700, 600, 500, 400, 300 hPa)
# beyond band_comparison.ARCHETYPES, for the archetypes below.
DEEP_WARM = np.array(ARCHETYPES["deep warm core (mature typhoon)"], float)
SECLUSION = np.array(ARCHETYPES["shallow warm core (seclusion)"], float)
DEEP_COLD = np.array(ARCHETYPES["deep cold core (extratropical)"], float)
# A mature frontal cyclone: a deep surface low whose depression still grows
# upward through the column (cold core in both layers), deep enough at
# 1000 hPa to stay a closed low against the baroclinic zone's own gradient.
FRONTAL_COLD = np.array([110, 120, 135, 165, 190, 225, 265, 300], float)
# A cutoff cold low: a modest depression growing upward through the column.
CUTOFF_COLD = np.array([70, 80, 95, 120, 135, 150, 160, 165], float)
# A subtropical storm: convection has built a lower-tropospheric warm core
# (amplitude shrinking from 1000 to 600 hPa) under the cold low aloft
# (amplitude still growing from 600 to 300 hPa).
SUBTROPICAL = np.array([165, 150, 132, 105, 100, 112, 130, 142], float)


def scenario_extratropical_transition():
    """Extratropical transition of a tropical cyclone: symmetric deep warm
    core, then asymmetric, then cold core (the life cycle of Figure 13,
    unchanged).

    Fields: the vortex keeps the deep warm core profile to 48 h, then blends
    through the transitioning profile (warm below 850 hPa, cold aloft) to the
    deep cold core by 126 h and toward the seclusion profile by 168 h
    (blended_amp); its radius grows from 150 to 350 km (scale_km_of). The
    storm-attached dipole ramps up from 24 h to 65 m at 72 h, holds to 108 h
    and is gone by 144 h (dipole_amplitude). The track starts at 22N 150E,
    slow and north-northwest, recurves to the northeast into the baroclinic
    zone (g0 = 4) accelerating to 16 m/s at 120 h, and slows to 6 m/s
    (speed_profile, heading_profile).
    """
    return Scenario(
        key="extratropical_transition",
        title="Extratropical transition",
        amp=blended_amp, scale_km=scale_km_of, dipole=dipole_amplitude,
        speed=speed_profile, heading=heading_profile, start=(22.0, 150.0), g0=4.0,
        summary="tropical cyclone to extratropical low: symmetric deep warm, asymmetric, cold core",
    )


def scenario_tropical_decay():
    """A tropical cyclone that stays tropical and decays without transition.

    Fields: the vortex keeps the deep warm core profile's shape at every
    frame while its amplitude at every level falls to 30 percent between
    36 h and 168 h (the storm spinning down over cooler water), and its
    radius broadens from 150 to 250 km. There is no dipole (A = 0). The
    track starts at 21N 176E and moves west-northwest at 5 m/s, turning
    northwest and slowing to 3.5 m/s, so it stays south of 30N where the
    background gradient is zero: nothing gives the storm a thermal
    asymmetry or a cold layer, so B stays near 0 and both thermal wind terms
    shrink toward zero while remaining warm.
    """
    return Scenario(
        key="tropical_decay",
        title="Tropical cyclone decay",
        amp=staged((36.0, DEEP_WARM), (168.0, 0.30 * DEEP_WARM)),
        scale_km=staged((0.0, 150.0), (168.0, 250.0)),
        dipole=lambda t: 0.0,
        speed=staged((24.0, 4.5), (168.0, 3.0)),
        heading=staged((24.0, -82.0), (144.0, -55.0)),
        start=(20.0, 179.0), g0=4.0,
        summary="stays symmetric deep warm core while it weakens",
    )


def scenario_warm_seclusion():
    """Warm seclusion of a frontal low (Shapiro-Keyser).

    Fields: the vortex starts as a deep cold core (amplitude growing upward,
    80 percent of the deep cold core profile) with a strong storm-attached
    dipole (A = 55 m, the frontal thickness contrast across the track), so
    it reads asymmetric cold core. Between 30 and 78 h the profile blends to
    the seclusion profile: warm air wrapped into the center deepens the
    lower-tropospheric depression and makes it shrink upward below 600 hPa
    (a shallow warm core) while the cold core aloft remains. The dipole
    holds to 66 h and decays to zero by 102 h as the warm air is cut off
    from the warm sector and the core becomes symmetric. From 114 h the
    profile blends back to a weakened deep cold core (the secluded warm
    pocket mixes out and the low fills). The radius shrinks from 300 to
    250 km during the seclusion and broadens to 350 km as it fills. The
    track starts at 36N 149E in the baroclinic zone (g0 = 4), moving
    east-northeast at 11 m/s, slowing to 3.5 m/s and turning north.
    """
    return Scenario(
        key="warm_seclusion",
        title="Warm seclusion",
        amp=staged((30.0, FRONTAL_COLD), (78.0, SECLUSION), (114.0, SECLUSION), (168.0, 0.75 * FRONTAL_COLD)),
        scale_km=staged((30.0, 300.0), (78.0, 250.0), (114.0, 250.0), (168.0, 350.0)),
        dipole=staged((66.0, 55.0), (102.0, 0.0)),
        speed=staged((12.0, 10.0), (84.0, 3.0)),
        heading=staged((12.0, 65.0), (120.0, 10.0)),
        start=(35.0, 148.0), g0=4.0,
        summary="asymmetric cold core develops a shallow symmetric warm core, then decays cold",
    )


def scenario_cold_occlusion():
    """A cold-core extratropical low that occludes.

    Fields: the vortex has the deep cold core profile throughout (amplitude
    growing upward), deepening from 70 to 100 percent of it by 60 h and
    filling to 75 percent by 168 h, its radius growing from 300 to 400 km.
    The storm-attached dipole starts at A = 60 m (the open frontal wave,
    warm sector to the right of the track), holds to 30 h and decays to
    zero by 90 h as the occlusion lifts the warm sector off the center and
    the thickness around the low becomes symmetric. The track starts at 35N
    151E in the baroclinic zone (g0 = 4), moving northeast at 12 m/s,
    slowing to 3 m/s and curling north-northwest, as occluded lows do.
    """
    return Scenario(
        key="cold_occlusion",
        title="Cold-core occlusion",
        amp=staged((0.0, 0.8 * FRONTAL_COLD), (60.0, FRONTAL_COLD), (168.0, 0.8 * FRONTAL_COLD)),
        scale_km=staged((0.0, 300.0), (168.0, 400.0)),
        dipole=staged((30.0, 60.0), (90.0, 0.0)),
        speed=staged((12.0, 11.0), (78.0, 2.5)),
        heading=staged((12.0, 50.0), (120.0, -60.0)),
        start=(34.0, 150.0), g0=4.0,
        summary="asymmetric cold core becomes symmetric cold core",
    )


def scenario_tropical_transition():
    """Tropical transition of a subtropical storm.

    Fields: the vortex starts as a cutoff cold low (amplitude growing
    upward through the column) with a weak storm-attached dipole
    (A = 22 m, a weak thickness contrast across the track), so it reads
    weakly asymmetric cold core. Between 18 and 60 h convection builds a
    lower-tropospheric warm core under the cold low aloft (the subtropical
    profile), between 54 and 90 h the dipole decays to zero, and between 96
    and 150 h the warm core deepens through the column to 80 percent of the
    deep warm core profile, the cold low aloft eroded. The radius contracts
    from 350 to 180 km. The track starts at 29N 163E, drifting
    west-southwest at 3.5 m/s and turning west-northwest, in a weak
    background gradient (g0 = 2) whose zone begins at 30N.
    """
    return Scenario(
        key="tropical_transition",
        title="Tropical transition",
        amp=staged((18.0, CUTOFF_COLD), (60.0, SUBTROPICAL), (96.0, SUBTROPICAL), (150.0, 0.8 * DEEP_WARM)),
        scale_km=staged((18.0, 350.0), (150.0, 180.0)),
        dipole=staged((54.0, 26.0), (90.0, 0.0)),
        speed=staged((0.0, 3.0), (168.0, 3.5)),
        heading=staged((24.0, 250.0), (144.0, 300.0)),
        start=(29.0, 170.0), g0=2.0,
        summary="weakly asymmetric cold low to shallow warm to symmetric deep warm core",
    )


def scenario_hybrid():
    """A hybrid storm that oscillates about the B = 10 m plane.

    Fields: the vortex has the subtropical profile throughout (a
    lower-tropospheric warm core under a cold core aloft, the shallow warm
    core of a hybrid or subtropical storm) at a 250 km radius, its
    amplitude growing steadily from 60 to 140 percent of that profile as
    the storm slowly deepens, which carries the path outward in both
    thermal wind terms. The
    storm-attached dipole pulses between 0 and 36 m,
    A(t) = 18 + 18 sin(2 pi t / 56 h), as a succession of short-wave troughs
    passing to its north sharpens and then relaxes the thickness contrast
    across the track, so B swings through 10 m about every 28 h while the
    lower term stays warm and the upper term cold (the lower term also
    swings a little, because the dipole's own contrast grows with height up
    to 600 hPa and reads there as a cold contribution). The track starts at 28N 156E and moves northeast at 5 m/s,
    slowing to 4 m/s and turning east-northeast, into a weak background
    gradient (g0 = 2).
    """
    def pulsing_dipole(t):
        return 18.0 + 18.0 * np.sin(2.0 * np.pi * t / 56.0)

    return Scenario(
        key="hybrid",
        title="Hybrid near the B = 10 m plane",
        amp=staged((0.0, 0.6 * SUBTROPICAL), (168.0, 1.4 * SUBTROPICAL)),
        scale_km=lambda t: 250.0,
        dipole=pulsing_dipole,
        speed=staged((0.0, 5.0), (168.0, 4.0)),
        heading=staged((0.0, 40.0), (168.0, 70.0)),
        start=(28.0, 156.0), g0=2.0,
        summary="shallow warm core whose asymmetry pulses about B = 10 m",
    )


def _scenario_list():
    return [scenario_extratropical_transition(), scenario_tropical_decay(), scenario_warm_seclusion(),
            scenario_cold_occlusion(), scenario_tropical_transition(), scenario_hybrid()]


#: The life cycles by key, the extratropical transition (the default) first.
SCENARIOS = {sc.key: sc for sc in _scenario_list()}
DEFAULT_SCENARIO = "extratropical_transition"


def get_scenario(scenario=None):
    """A Scenario from None (the default, extratropical transition), a key
    of SCENARIOS, or a Scenario (returned as is)."""
    if scenario is None:
        return SCENARIOS[DEFAULT_SCENARIO]
    if isinstance(scenario, Scenario):
        return scenario
    return SCENARIOS[scenario]


# ------------------------------------------------------- shared setup
# These four are the single source of truth for the grid, the track, and the two
# methods, so `lifecycle_storyboard.py` (and anything else) gets bit-identical
# numbers to this script's own printed table, not a second, drifting copy of the
# same logic.

GRID_DLAT = 0.25
GRID_KWARGS = dict(lat0=15.0, lat1=60.0, lon0=140.0, lon1=190.0)


def build_grid(dlat=None, lat0=None, lat1=None, lon0=None, lon1=None):
    """(lat_vals, lon_vals, lat2d, lon2d, dx, dy) for this life cycle's regional
    0.25 deg grid -- see the module docstring for why this domain (not
    experiments.make_grid's own default) is wide enough that the 500 km
    analysis window never touches the edge.

    Every argument defaults to this life cycle's own fixed domain
    (GRID_DLAT/GRID_KWARGS), unchanged from before this optional-domain
    argument existed. Pass any subset to build a grid over a different
    domain with the same make_grid machinery -- e.g. a full ocean basin
    for a scene wider than one storm's own regional window.
    """
    dlat = GRID_DLAT if dlat is None else dlat
    lat0 = GRID_KWARGS["lat0"] if lat0 is None else lat0
    lat1 = GRID_KWARGS["lat1"] if lat1 is None else lat1
    lon0 = GRID_KWARGS["lon0"] if lon0 is None else lon0
    lon1 = GRID_KWARGS["lon1"] if lon1 is None else lon1
    return make_grid(dlat, lat0=lat0, lat1=lat1, lon0=lon0, lon1=lon1)


def env_fields(lat2d):
    """(psfc, coriolis): uniform open-ocean surface pressure (1013 hPa, so
    mask_below_ground never trips) and uniform Northern Hemisphere coriolis
    sign (the storm stays north of the equator throughout).
    """
    return np.full(lat2d.shape, 1013.0), np.full(lat2d.shape, 1.0)


def make_hours():
    """The 29 output frames: 0 to 168 h, 6 h steps."""
    return np.arange(0.0, 168.0 + 1e-9, 6.0)


def build_track_and_motion(hours, scenario=None):
    """(lats, lons, headings, speeds) for the full track: build_track's
    integrated positions, then cps.track_motion's own finite-difference
    heading/speed at each of those same points -- the one motion both
    methods are handed. `scenario` defaults to the extratropical
    transition.
    """
    lats, lons = build_track(hours, scenario)
    headings, speeds = ch.track_motion(lats, lons, hours * 3600.0)
    return lats, lons, headings, speeds


def compute_frame(t, clat, clon, heading_deg, speed_ms, lat2d, lon2d, lat_vals, lon_vals, dx, dy, psfc, coriolis,
                   return_fields=False, scenario=None):
    """Both methods' B/VTL/VTU/class at one frame: the storm-centered Hart
    scalars (circular window, `cps.hart`) and the gridded fields sampled at
    the grid point nearest (clat, clon) (circular window, `cps_HartCPS`).

    Returns a dict with the nine scalars (`VTL_hart`, `VTU_hart`, `B_hart`,
    `CLS_hart`, `VTL_grid`, `VTU_grid`, `B_grid`, `CLS_grid`, `B_grid_former`)
    plus `ci`/`cj` (the sampled grid indices). `B_grid_former` is parameter B
    from the earlier first-order gradient form (`parameter_b_grid_gradient`,
    kept in cps_HartCPS.py for comparison against the current, exact
    half-disk-mean `parameter_b_grid` that `B_grid`/`executeB` use), computed
    on the exact same thickness and motion fields `B_grid` uses -- see the
    module docstring's "Parameter B and the joint class" section. With
    `return_fields=True` it also includes the full 2D fields a map needs:
    `z` (level -> height array, for every level in `NEEDED_LEVELS`),
    `vtl_full`, `vtu_full`, `b_full`, `b_full_former`, `cls_full`, `u_arr`,
    `v_arr` (the gridded module's own outputs before sampling).
    `scenario` (a Scenario or a key of SCENARIOS) picks the life cycle
    whose height fields are built; the default is the extratropical
    transition.
    """
    z = build_heights(t, clat, clon, lat2d, lon2d, heading_deg, speed_ms, NEEDED_LEVELS, scenario)

    # -- Hart: circular window, storm-centered, 50 hPa levels
    z_stack = np.stack([z[p] for p in P50], axis=0)
    tw = ch.thermal_wind(P50.tolist(), z_stack, lat2d, lon2d, clat, clon, radius_km=RADIUS_KM)
    vtl_hart = tw["VTL"]
    vtu_hart = tw["VTU"]
    b_hart = ch.parameter_b(z[900], z[600], lat2d, lon2d, clat, clon, heading_deg=heading_deg, radius_km=RADIUS_KM)
    # Hart's own class: the same seven-code rule cps_HartCPS.hart_class applies to the
    # gridded fields, applied here to Hart's three storm-centered scalars for this one
    # frame (1-element arrays in, `mask=True` since there is no closed-low mask concept
    # for a storm-centered point, only for a gridded field).
    cls_hart = hc.hart_class(
        np.array([b_hart]), np.array([vtl_hart]), np.array([vtu_hart]), np.array([True]), hc.B_THRESHOLD_M,
    )[0]

    # -- gridded: circular window (WINDOW_SHAPE), pointwise, standard levels
    u_arr = np.full(lat2d.shape, speed_ms * np.sin(np.radians(heading_deg)))
    v_arr = np.full(lat2d.shape, speed_ms * np.cos(np.radians(heading_deg)))
    vtl_full = hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy, RADIUS_KM, 925.0, 850.0, 700.0)
    vtu_full = hc.executeBand3(z[500], z[400], z[300], psfc, dx, dy, RADIUS_KM, 500.0, 400.0, 300.0)
    b_full = hc.executeB(
        z[925], z[700],
        u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
        psfc, coriolis, dx, dy, radiusKm=RADIUS_KM, layerScale=hc.HART_B_LAYER_SCALE,
    )

    # Former, first-order gradient form of gridded B (parameter_b_grid_gradient),
    # kept only for comparison in figD_lifecycle.png -- built from the exact same
    # 925-700 hPa thickness and (window-averaged) steering motion executeB's own
    # parameter_b_grid call uses, so the two differ only in the half-disk-mean
    # versus gradient method itself, not in their inputs. u_arr/v_arr are already
    # spatially uniform, so steering()/steering_window_mean() would just hand
    # them straight back -- passed directly here for the identical result.
    psfc_hpa = hc.surface_pressure_hpa(psfc)
    z925_masked = hc.mask_below_ground(z[925], psfc_hpa, 925.0, hc.BELOW_GROUND_CAP_HPA)
    z700_masked = hc.mask_below_ground(z[700], psfc_hpa, 700.0, hc.BELOW_GROUND_CAP_HPA)
    thickness = np.asarray(z700_masked, dtype=float) - np.asarray(z925_masked, dtype=float)
    b_full_former = hc.parameter_b_grid_gradient(
        thickness, u_arr, v_arr, dx, dy, coriolis, RADIUS_KM, hc.HART_B_LAYER_SCALE,
    )

    # closed_low_mask (via executeHartClass) reads mean sea level pressure, not
    # 1000 hPa height: build a synthetic MSLP field (hPa) from this life cycle's
    # own 1000 hPa height at about 8 m per hPa. Passing z[1000] unchanged here
    # would raise no error but silently test 5 m of "depth" instead of 5 hPa
    # (DEFAULT_DEPTH_HPA) -- see cps_HartCPS.py's module docstring.
    pmsl = 1000.0 + z[1000] / 8.0
    cls_full = hc.executeHartClass(
        pmsl, z[925], z[850], z[700], z[500], z[400], z[300],
        u_arr, v_arr, u_arr, v_arr, u_arr, v_arr, u_arr, v_arr,
        psfc, coriolis, dx, dy, radiusKm=RADIUS_KM,
    )

    ci = int(np.argmin(np.abs(lat_vals - clat)))
    cj = int(np.argmin(np.abs(lon_vals - clon)))

    result = dict(
        VTL_hart=float(vtl_hart), VTU_hart=float(vtu_hart), B_hart=float(b_hart), CLS_hart=float(cls_hart),
        VTL_grid=float(vtl_full[ci, cj]), VTU_grid=float(vtu_full[ci, cj]), B_grid=float(b_full[ci, cj]),
        CLS_grid=float(cls_full[ci, cj]), B_grid_former=float(b_full_former[ci, cj]), ci=ci, cj=cj,
    )
    if return_fields:
        result.update(z=z, vtl_full=vtl_full, vtu_full=vtu_full, b_full=b_full, b_full_former=b_full_former,
                       cls_full=cls_full, u_arr=u_arr, v_arr=v_arr, pmsl=pmsl)
    return result


# ------------------------------------------------------- scenario runs
FRAME_KEYS = ("B_hart", "VTL_hart", "VTU_hart", "CLS_hart", "B_grid", "VTL_grid", "VTU_grid", "CLS_grid",
              "B_grid_former")


def run_scenario(scenario=None):
    """The per-frame loop of main() for any scenario: build the track and
    motion, then compute_frame at every hour on build_grid's grid. Returns
    a dict of arrays (hours, lats, lons, headings, speeds and FRAME_KEYS)
    plus `scenario` (the Scenario) and `edge_margin_km` (the smallest
    distance between the track and the grid edge, which must exceed the
    500 km window)."""
    sc = get_scenario(scenario)
    hours = make_hours()
    n = len(hours)
    lats, lons, headings, speeds = build_track_and_motion(hours, sc)
    lat_vals, lon_vals, lat2d, lon2d, dx, dy = build_grid()
    psfc, coriolis = env_fields(lat2d)
    out = {k: np.full(n, np.nan) for k in FRAME_KEYS}
    for i, t in enumerate(hours):
        r = compute_frame(t, float(lats[i]), float(lons[i]), headings[i], speeds[i], lat2d, lon2d,
                          lat_vals, lon_vals, dx, dy, psfc, coriolis, scenario=sc)
        for k in FRAME_KEYS:
            out[k][i] = r[k]
    margin_lat = min(lats.min() - lat_vals.min(), lat_vals.max() - lats.max()) * 111.0
    margin_lon = min((lons - lon_vals.min()) * 111.0 * np.cos(np.radians(lats))).item()
    margin_lon = min(margin_lon, float(np.min((lon_vals.max() - lons) * 111.0 * np.cos(np.radians(lats)))))
    out.update(hours=hours, lats=lats, lons=lons, headings=headings, speeds=speeds, scenario=sc,
               edge_margin_km=float(min(margin_lat, margin_lon)))
    return out


def class_runs(hours, cls):
    """[(start_hour, end_hour, class or None)] for consecutive frames
    sharing a class."""
    runs, start = [], 0
    for i in range(1, len(hours) + 1):
        if i == len(hours) or cls[i] != cls[start]:
            c = int(round(cls[start])) if np.isfinite(cls[start]) else None
            runs.append((float(hours[start]), float(hours[i - 1]), c))
            start = i
    return runs


def plane_crossings(hours, b, vtl, vtu, b_thr=10.0):
    """[(index, kind)] for every frame at which the path has crossed one
    of the three class planes since the frame before, with the same
    conventions as hart_class (B of exactly 10 m is symmetric, a term of
    exactly 0 is warm). kind is "B over 10 m", "B under 10 m", "lower cold"
    (-V_T^L turns negative), "lower warm" (-V_T^L turns warm), "upper cold"
    (-V_T^U turns negative) or "upper warm" (-V_T^U turns warm). Onset and
    completion are the first "B over 10 m" and "lower cold" crossings of a
    storm that did not start past them (see onset_completion)."""
    out = []
    for i in range(1, len(hours)):
        for prev, now, up, down in ((b[i - 1] > b_thr, b[i] > b_thr, "B over 10 m", "B under 10 m"),
                                    (vtl[i - 1] < 0.0, vtl[i] < 0.0, "lower cold", "lower warm"),
                                    (vtu[i - 1] < 0.0, vtu[i] < 0.0, "upper cold", "upper warm")):
            if now and not prev:
                out.append((i, up))
            elif prev and not now:
                out.append((i, down))
    return out


def onset_completion(hours, b, vtl, b_thr=10.0):
    """(onset, completion) hours by main()'s rule: the first frame with
    B > 10 m and the first with -V_T^L < 0 (NaN if never). A value of 0 h
    means the storm starts on that side of the plane."""
    def first(mask):
        idx = np.where(mask)[0]
        return float(hours[idx[0]]) if idx.size else float("nan")
    return first(b > b_thr), first(vtl < 0.0)


def print_scenario_summary(d):
    """Class sequence, onset/completion and plane crossings of a
    run_scenario result, both methods."""
    sc, hours = d["scenario"], d["hours"]
    print(f"\n== {sc.title} ({sc.key}): {sc.summary}")
    print(f"   track {d['lats'][0]:.1f}N {d['lons'][0]:.1f}E to {d['lats'][-1]:.1f}N {d['lons'][-1]:.1f}E, "
          f"speed {d['speeds'].min():.1f} to {d['speeds'].max():.1f} m/s, "
          f"smallest margin to the grid edge {d['edge_margin_km']:.0f} km")
    for m, label in (("grid", "gridded"), ("hart", "Hart")):
        b, vtl, vtu = d[f"B_{m}"], d[f"VTL_{m}"], d[f"VTU_{m}"]
        runs = class_runs(hours, d[f"CLS_{m}"])
        seq = ", ".join(f"{c}" if c is not None else "nan" for _, _, c in runs)
        print(f"   {label:8s} classes {seq}:  " + ";  ".join(
            f"{h0:.0f}-{h1:.0f} h {c}" for h0, h1, c in runs))
        on, comp = onset_completion(hours, b, vtl)
        cross = plane_crossings(hours, b, vtl, vtu)
        def hr(x):
            return "never" if not np.isfinite(x) else ("0 h (from the start)" if x == hours[0] else f"{x:.0f} h")
        print(f"   {'':8s} onset {hr(on)}, completion {hr(comp)}; crossings: "
              + (", ".join(f"{k} {hours[i]:.0f} h" for i, k in cross) or "none"))
        print(f"   {'':8s} B {np.nanmin(b):.1f} to {np.nanmax(b):.1f} m, -VTL {np.nanmin(vtl):.1f} to "
              f"{np.nanmax(vtl):.1f} m, -VTU {np.nanmin(vtu):.1f} to {np.nanmax(vtu):.1f} m")


# --------------------------------------------------------------- main
def main():
    hours = make_hours()
    n = len(hours)
    lats, lons, headings, speeds = build_track_and_motion(hours)

    print(f"Track: {n} frames, 0 to 168 h, 6 h steps")
    print(f"  start {lats[0]:.2f}N {lons[0]:.2f}E, end {lats[-1]:.2f}N {lons[-1]:.2f}E "
          f"(target: 22N 150E to near 52N 175E)")
    print(f"  lat range {lats.min():.2f} to {lats.max():.2f}, lon range {lons.min():.2f} to {lons.max():.2f}")

    lat_vals, lon_vals, lat2d, lon2d, dx, dy = build_grid()
    margin_lat = min(lats.min() - lat_vals.min(), lat_vals.max() - lats.max())
    margin_lon = min(lons.min() - lon_vals.min(), lon_vals.max() - lons.max())
    print(f"  grid: {lat2d.shape[0]} x {lat2d.shape[1]} at 0.25 deg, "
          f"lat {lat_vals.min():.1f} to {lat_vals.max():.1f}, lon {lon_vals.min():.1f} to {lon_vals.max():.1f}")
    print(f"  smallest margin between track and grid edge: {min(margin_lat, margin_lon) * 111.0:.0f} km "
          f"(need > {RADIUS_KM:.0f} km for the 500 km window to never touch the edge)")

    psfc, coriolis = env_fields(lat2d)

    B_hart = np.full(n, np.nan)
    VTL_hart = np.full(n, np.nan)
    VTU_hart = np.full(n, np.nan)
    B_grid = np.full(n, np.nan)
    VTL_grid = np.full(n, np.nan)
    VTU_grid = np.full(n, np.nan)
    CLS_grid = np.full(n, np.nan)
    CLS_hart = np.full(n, np.nan)
    B_grid_former = np.full(n, np.nan)

    for i, t in enumerate(hours):
        clat, clon = float(lats[i]), float(lons[i])
        # x_R = 0 at the center, so the dipole leaves the center-point VTL/VTU unchanged.
        r = compute_frame(t, clat, clon, headings[i], speeds[i], lat2d, lon2d, lat_vals, lon_vals, dx, dy,
                           psfc, coriolis)
        VTL_hart[i], VTU_hart[i], B_hart[i], CLS_hart[i] = r["VTL_hart"], r["VTU_hart"], r["B_hart"], r["CLS_hart"]
        VTL_grid[i], VTU_grid[i], B_grid[i], CLS_grid[i] = r["VTL_grid"], r["VTU_grid"], r["B_grid"], r["CLS_grid"]
        B_grid_former[i] = r["B_grid_former"]

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
    onset_former = first_cross(B_grid_former, np.greater, 10.0)
    completion_hart = first_cross(VTL_hart, np.less, 0.0)
    completion_grid = first_cross(VTL_grid, np.less, 0.0)
    # The former B form only changes B itself, not VTL (thermal_wind_grid is
    # untouched by which parameter_b_grid* form is used), so completion --
    # defined purely from VTL -- is identical for "new gridded" and "former".
    completion_former = completion_grid
    fall_below_hart = first_cross_after_peak(B_hart, np.less, 10.0)
    fall_below_grid = first_cross_after_peak(B_grid, np.less, 10.0)
    fall_below_former = first_cross_after_peak(B_grid_former, np.less, 10.0)

    rms = {}
    for name, hart_arr, grid_arr in (("B", B_hart, B_grid), ("VTL", VTL_hart, VTL_grid), ("VTU", VTU_hart, VTU_grid)):
        diff = grid_arr - hart_arr
        rms[name] = float(np.sqrt(np.nanmean(diff ** 2)))
    rms["B_former"] = float(np.sqrt(np.nanmean((B_grid_former - B_hart) ** 2)))

    deep_mask = hours <= 48.0
    ratio_lower_deep = float(np.nanmean(VTL_grid[deep_mask]) / np.nanmean(VTL_hart[deep_mask]))

    peak_idx_hart = int(np.nanargmax(B_hart))
    peak_idx_grid = int(np.nanargmax(B_grid))
    peak_idx_former = int(np.nanargmax(B_grid_former))
    b_peak_ratio = float(B_grid[peak_idx_grid] / B_hart[peak_idx_hart])
    b_peak_ratio_former = float(B_grid_former[peak_idx_former] / B_hart[peak_idx_hart])

    print()
    print(f"Onset (B first exceeds 10 m):          Hart {onset_hart:.0f} h,  gridded {onset_grid:.0f} h,  "
          f"former gridded {onset_former:.0f} h")
    print(f"Completion (VTL first turns negative): Hart {completion_hart:.0f} h,  gridded {completion_grid:.0f} h,  "
          f"former gridded {completion_former:.0f} h (same VTL as gridded)")
    print(f"B falls back under 10 m (after the peak): Hart {fall_below_hart:.0f} h,  gridded {fall_below_grid:.0f} h,  "
          f"former gridded {fall_below_former:.0f} h")
    print()
    print(f"B peak: Hart {B_hart[peak_idx_hart]:.1f} m at {hours[peak_idx_hart]:.0f} h,  "
          f"gridded {B_grid[peak_idx_grid]:.1f} m at {hours[peak_idx_grid]:.0f} h,  "
          f"former gridded {B_grid_former[peak_idx_former]:.1f} m at {hours[peak_idx_former]:.0f} h")
    print(f"Ratio of the gridded B peak to the Hart B peak: {b_peak_ratio:.3f}")
    print(f"Ratio of the former gridded B peak to the Hart B peak: {b_peak_ratio_former:.3f}")
    print()
    print("RMS difference between methods over the life cycle (gridded minus Hart):")
    print(f"  B (new, half-disk means):      {rms['B']:6.2f} m")
    print(f"  B (former, first-order gradient): {rms['B_former']:6.2f} m")
    print(f"  VTL (lower term):               {rms['VTL']:6.2f} m")
    print(f"  VTU (upper term):               {rms['VTU']:6.2f} m")
    print()
    print(f"Ratio gridded/Hart of the lower term during the deep warm core phase (0 to 48 h): {ratio_lower_deep:.3f}")
    print(f"Seclusion-phase lower term (last frame, hour {hours[-1]:.0f}): "
          f"gridded {VTL_grid[-1]:.1f} m,  Hart {VTL_hart[-1]:.1f} m")

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
                onset_hart, onset_grid, completion_hart, completion_grid, B_grid_former)


# ------------------------------------------------------------- figure
def make_figure(hours, lats, lons, B_hart, VTL_hart, VTU_hart, B_grid, VTL_grid, VTU_grid, CLS_grid, CLS_hart,
                 onset_hart, onset_grid, completion_hart, completion_grid, B_grid_former):
    cmap_hart = LinearSegmentedColormap.from_list("hart_gray", ["#c9c9c9", "#000000"])
    cmap_grid = LinearSegmentedColormap.from_list("grid_red", ["#fbdede", RED])

    # Panels (a)/(b)'s background (quadrant colors/labels, reference lines,
    # grid, axis labels) and limits match make_figures.make_fig10 (the
    # article's Figure 1) exactly, via diagram_style -- widened past its
    # fixed limits only where this life cycle's own data actually exceeds
    # them (see PHASE_XLIM_VTL/PHASE_YLIM_B/PHASE_YLIM_VTU below).
    xlim_vtl = ds.widen_limits(ds.FIG10_VTL_LIM, VTL_hart, VTL_grid)
    ylim_b = ds.widen_limits(ds.FIG10_B_LIM, B_hart, B_grid, B_grid_former)
    ylim_vtu = ds.widen_limits(ds.FIG10_VTU_LIM, VTU_hart, VTU_grid)
    for lim, base, name in ((xlim_vtl, ds.FIG10_VTL_LIM, "-V_T^L"), (ylim_b, ds.FIG10_B_LIM, "B"),
                             (ylim_vtu, ds.FIG10_VTU_LIM, "-V_T^U")):
        if lim != base:
            print(f"Note: {name} axis widened from {base} to {lim} (figD_lifecycle.png), "
                  f"data exceeded make_fig10's own limit.")

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.0))

    # -- (a) B vs -VTL (Hart's Phase 1 diagram)
    ax = axes[0]
    ax.set_xlim(*xlim_vtl)
    ax.set_ylim(*ylim_b)
    ds.draw_b_vtl_quadrants(ax, xlim_vtl, ylim_b, 10.0)
    ax.plot(VTL_hart, B_hart, "-", color="0.75", lw=1.0, zorder=1)
    ax.plot(VTL_grid, B_grid, "-", color=RED, alpha=0.35, lw=1.0, zorder=1)
    # Former, first-order gradient form of gridded B (parameter_b_grid_gradient),
    # plotted against the SAME VTL_grid (VTL does not depend on which B form is
    # used) -- thin dotted, no markers, so it reads as a comparison trace behind
    # the two marker series rather than competing with them for attention.
    ax.plot(VTL_grid, B_grid_former, ":", color=RED, alpha=0.55, lw=1.0, zorder=1)
    ax.scatter(VTL_hart, B_hart, c=hours, cmap=cmap_hart, s=32, marker="o", zorder=3, edgecolor="white", linewidth=0.4)
    ax.scatter(VTL_grid, B_grid, c=hours, cmap=cmap_grid, s=32, marker="s", zorder=4, edgecolor="white", linewidth=0.4)
    ax.axhline(10.0, color=ds.TEXT_DARK, lw=1.0, zorder=2)
    ax.axvline(0.0, color=ds.TEXT_DARK, lw=1.0, zorder=2)
    ax.set_xlabel(ds.AXIS_LABEL_VTL)
    ax.set_ylabel(ds.AXIS_LABEL_B)
    ax.set_title("(a) B versus $-V_T^L$", loc="left", fontsize=10)
    ax.grid(True, color=ds.GRID_COLOR, linewidth=0.5, zorder=0.2)

    # -- (b) -VTU vs -VTL (Hart's Phase 2 diagram)
    ax = axes[1]
    ax.set_xlim(*xlim_vtl)
    ax.set_ylim(*ylim_vtu)
    # "deep cold core"/"shallow warm core" nudged up off the x axis (make_fig10's
    # own y0*0.90 corner, where this life cycle's own trajectory actually passes,
    # unlike make_fig10's schematic one) into the clear gap around VTU = -100.
    label_overrides_b = {
        "deep cold core": (xlim_vtl[0] * 0.95, ylim_vtu[0] * 0.33),
        "shallow warm core": (xlim_vtl[1] * 0.55, ylim_vtu[0] * 0.33),
    }
    ds.draw_vtu_vtl_quadrants(ax, xlim_vtl, ylim_vtu, label_overrides=label_overrides_b)
    ax.plot(VTL_hart, VTU_hart, "-", color="0.75", lw=1.0, zorder=1)
    ax.plot(VTL_grid, VTU_grid, "-", color=RED, alpha=0.35, lw=1.0, zorder=1)
    ax.scatter(VTL_hart, VTU_hart, c=hours, cmap=cmap_hart, s=32, marker="o", zorder=3, edgecolor="white", linewidth=0.4)
    ax.scatter(VTL_grid, VTU_grid, c=hours, cmap=cmap_grid, s=32, marker="s", zorder=4, edgecolor="white", linewidth=0.4)
    ax.axhline(0.0, color=ds.TEXT_DARK, lw=1.0, zorder=2)
    ax.axvline(0.0, color=ds.TEXT_DARK, lw=1.0, zorder=2)
    ax.set_xlabel(ds.AXIS_LABEL_VTL)
    ax.set_ylabel(ds.AXIS_LABEL_VTU)
    ax.set_title("(b) $-V_T^U$ versus $-V_T^L$", loc="left", fontsize=10)
    ax.grid(True, color=ds.GRID_COLOR, linewidth=0.5, zorder=0.2)

    handles = [
        Line2D([0], [0], marker="o", color="0.4", lw=1.0, markersize=6, label="Hart, 50 hPa levels"),
        Line2D([0], [0], marker="s", color=RED, lw=1.0, markersize=6, label="gridded, standard levels"),
        Line2D([0], [0], ls=":", color=RED, alpha=0.55, lw=1.4,
               label="gridded, first-order gradient (former)"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=3, fontsize=8, bbox_to_anchor=(0.5, 1.0), frameon=False)

    # -- (c) time series, with the gridded class as a strip along the top
    ax = axes[2]
    ax.plot(hours, B_hart, "--", color=PURPLE, lw=1.2, label="B, Hart")
    ax.plot(hours, B_grid, "-", color=PURPLE, lw=1.2, label="B, gridded")
    ax.plot(hours, B_grid_former, ":", color=PURPLE, lw=1.0, alpha=0.75,
            label="B, gridded (former)")
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


def main_scenarios(keys=None):
    """Run the named scenarios (all of SCENARIOS by default) through
    run_scenario and print each one's summary: track, class sequence,
    onset and completion hours and plane crossings, for both methods.
    Writes no figure."""
    for key in (keys or list(SCENARIOS)):
        print_scenario_summary(run_scenario(key))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--scenarios":
        main_scenarios(sys.argv[2:])
    else:
        main()
