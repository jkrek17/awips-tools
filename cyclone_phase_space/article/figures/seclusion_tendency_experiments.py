"""Experiments on the HVTL tendency index of `seclusion_tendency.py`.

Four questions, in decreasing order of how much the answer can be trusted:

1. THRESHOLD. `seclusion_tendency.py` found that sign alone does not
   separate the two cases and picked +50 m per 12 h by eye. What does the
   whole trade-off curve look like -- how much lead does each threshold
   buy, and where does the decaying storm start raising false alarms?

2. INTERVAL. The 12 h difference is one choice. Does 6 h fire earlier at
   the cost of noise, and 24 h later but cleaner?

3. MARGINAL CASES AND NOISE. A storm that only partly recovers its warm
   core is the case that matters -- the clean seclusion and the clean
   decay are the easy ones. And a difference of two fields amplifies
   noise, so: does the index survive height fields with realistic noise
   on them? HVTL is a window max-minus-min, and the max-minus-min of a
   noisy field is biased upward, so this is not a formality.

4. WIND TIMING. Can the index see hurricane-force winds coming, and by
   how long?

   READ 4 WITH CARE. In this synthetic the surface wind and the phase
   space evolution are both deterministic consequences of the SAME
   prescribed archetype table (`band_comparison.ARCHETYPES`, blended by
   `lifecycle_comparison.blended_amp`). The wind is not an independent
   physical outcome that the index gets to predict; it is the same
   prescription read through a different equation. A lead time measured
   between two consequences of one prescription is a property of the
   prescription. It is reported here because it is worth knowing what
   this synthetic implies, and it is NOT evidence about lead over real
   hurricane-force winds. Only the case set can answer that.

The wind proxy is the gradient wind from the 1000 hPa height field, which
for a cyclonically curved flow is meaningfully below the geostrophic wind
at these radii; both are printed so the difference is visible rather than
hidden in a choice.

Run from this directory:

    python3 seclusion_tendency_experiments.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lifecycle_comparison as lc  # noqa: E402
import seclusion_tendency as st  # noqa: E402
from band_comparison import ARCHETYPES  # noqa: E402
from experiments import dist_km  # noqa: E402

G = 9.80665
OMEGA = 7.2921e-5
MS_TO_KT = 1.943844
HURRICANE_FORCE_KT = 64.0
STORM_FORCE_KT = 48.0
WIND_SEARCH_KM = 800.0  # radius within which the peak wind is taken

COLD = np.array(ARCHETYPES["deep cold core (extratropical)"], float)
SECL = np.array(ARCHETYPES["shallow warm core (seclusion)"], float)


# ------------------------------------------------------------ scenarios
def make_amp(recovery, base):
    """`base` (lifecycle_comparison.blended_amp) with the post-126 h target
    scaled by `recovery`: 1.0 is the full seclusion archetype, 0.0 holds the
    deep cold core, and values between are a storm that only partly rebuilds
    its lower warm core.

    `base` is passed in, not looked up, for the reason `scenario_amp` gives.
    """
    target = COLD + float(recovery) * (SECL - COLD)

    def amp(t):
        if t <= 126.0:
            return base(t)
        w = lc.cosine_blend((t - 126.0) / (168.0 - 126.0))
        return (1.0 - w) * COLD + w * target

    return amp


def run(recovery, hours, track, grid, psfc, noise_m=0.0, seed=0):
    """(hvtl_trace, wind_kt_trace) for one recovery fraction.

    `noise_m`, when nonzero, adds independent Gaussian noise of that
    standard deviation to every height level at every frame before the
    diagnostics see it -- the height field a model would actually hand over,
    not the analytic one.
    """
    lats, lons, headings, speeds = track
    lat_vals, lon_vals, lat2d, lon2d, dx, dy = grid
    rng = np.random.default_rng(seed)
    hvtl, wind = [], []

    original = lc.blended_amp
    lc.blended_amp = make_amp(recovery, original)
    try:
        for t, clat, clon, hdg, spd in zip(hours, lats, lons, headings, speeds):
            z = lc.build_heights(t, clat, clon, lat2d, lon2d, hdg, spd, lc.NEEDED_LEVELS)
            if noise_m > 0.0:
                z = {p: v + rng.normal(0.0, noise_m, v.shape) for p, v in z.items()}
            f = lc.hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy,
                                    lc.RADIUS_KM, 925.0, 850.0, 700.0)
            ci = int(np.argmin(np.abs(lat_vals - clat)))
            cj = int(np.argmin(np.abs(lon_vals - clon)))
            hvtl.append(float(f[ci, cj]))
            wind.append(peak_wind_kt(z[1000], lat2d, lon2d, dx, dy, clat, clon))
    finally:
        lc.blended_amp = original
    return np.array(hvtl), np.array(wind)


# ---------------------------------------------------------- wind proxy
def peak_wind_kt(z1000, lat2d, lon2d, dx, dy, clat, clon, geostrophic=False):
    """Peak gradient wind (kt) from the 1000 hPa height field within
    WIND_SEARCH_KM of the storm center.

    Gradient rather than geostrophic because the flow is cyclonically
    curved: V^2/r + fV = g dZ/dr, solved for V, which is below the
    geostrophic wind at these radii. `geostrophic=True` returns g|grad Z|/f
    instead, for the comparison the module docstring mentions.
    """
    gy, gx = np.gradient(z1000)
    grad = np.hypot(gx / dx, gy / dy)
    f = 2.0 * OMEGA * np.sin(np.radians(np.abs(lat2d)))
    r_km = dist_km(lat2d, lon2d, clat, clon)
    near = r_km <= WIND_SEARCH_KM
    if geostrophic:
        v = G * grad / f
        return float(np.nanmax(v[near]) * MS_TO_KT)
    r = np.maximum(r_km * 1000.0, 1.0)
    disc = (f * r) ** 2 + 4.0 * r * G * grad
    v = 0.5 * (-f * r + np.sqrt(np.maximum(disc, 0.0)))
    return float(np.nanmax(v[near]) * MS_TO_KT)


# ------------------------------------------------------------- helpers
def fire_hour(hours, trace, interval_h, threshold, after):
    """Hour the index first passes `threshold`, using an `interval_h`
    difference of `trace`, searching only after `after`."""
    step = float(hours[1] - hours[0])
    back = int(round(interval_h / step))
    tend = np.full(len(trace), np.nan)
    tend[back:] = trace[back:] - trace[:-back]
    return st.first_crossing(hours, tend, threshold, True, after=after), tend


def et_hour(hours, hvtl):
    """Hour HVTL first crosses below zero -- transition complete."""
    return st.first_crossing(hours, hvtl, 0.0, positive=False)


def fmt(x, unit=""):
    return "never" if x is None else f"{x:.0f}{unit}"


# --------------------------------------------------------- experiments
def experiment_threshold(hours, base, et):
    print("\n" + "=" * 72)
    print("1. THRESHOLD SWEEP  (12 h interval)")
    print("=" * 72)
    print("  Every threshold's lead over HVTL's own zero crossing, and whether")
    print("  the decaying storm raises a false alarm at it.\n")
    sec_hvtl = base[1.0][0]
    dec_hvtl = base[0.0][0]
    crossing = st.first_crossing(hours, sec_hvtl, 0.0, True, after=et)
    print(f"  {'threshold':>10}  {'seclusion fires':>16}  {'lead':>7}  {'decay fires':>12}")
    print("  " + "-" * 54)
    for thr in (0, 10, 20, 30, 40, 50, 75, 100, 125):
        s, _ = fire_hour(hours, sec_hvtl, 12.0, thr, et)
        d, _ = fire_hour(hours, dec_hvtl, 12.0, thr, et)
        lead = None if s is None else crossing - s
        flag = "  <- FALSE ALARM" if d is not None else ""
        print(f"  {thr:>8} m  {fmt(s,' h'):>16}  {fmt(lead,' h'):>7}  {fmt(d,' h'):>12}{flag}")
    print(f"\n  HVTL itself crosses zero at hour {crossing:.0f}.")
    print("  Lead is bought by lowering the threshold, and paid for in false alarms.")


def experiment_interval(hours, base, et):
    print("\n" + "=" * 72)
    print("2. TENDENCY INTERVAL")
    print("=" * 72)
    print("  Does a shorter difference fire earlier? Threshold scaled with the")
    print("  interval so each is the same rate (50 m per 12 h).\n")
    sec_hvtl, dec_hvtl = base[1.0][0], base[0.0][0]
    crossing = st.first_crossing(hours, sec_hvtl, 0.0, True, after=et)
    print(f"  {'interval':>9}  {'threshold':>10}  {'seclusion':>10}  {'lead':>7}  {'decay':>8}")
    print("  " + "-" * 52)
    for iv in (6.0, 12.0, 24.0):
        thr = 50.0 * iv / 12.0
        s, _ = fire_hour(hours, sec_hvtl, iv, thr, et)
        d, _ = fire_hour(hours, dec_hvtl, iv, thr, et)
        lead = None if s is None else crossing - s
        print(f"  {iv:>7.0f} h  {thr:>8.0f} m  {fmt(s,' h'):>10}  {fmt(lead,' h'):>7}  {fmt(d,' h'):>8}")


def experiment_marginal(hours, track, grid, psfc, et):
    print("\n" + "=" * 72)
    print("3. MARGINAL RECOVERY, AND NOISE")
    print("=" * 72)
    print("  (a) Partial recovery: the storm rebuilds only part of its lower")
    print("      warm core. 1.0 is the full seclusion, 0.0 the clean decay.\n")
    print(f"  {'recovery':>9}  {'peak tendency':>14}  {'fires (50 m)':>13}  {'HVTL back > 0':>14}")
    print("  " + "-" * 56)
    rows = {}
    for rec in (1.0, 0.7, 0.5, 0.3, 0.0):
        hvtl, _ = run(rec, hours, track, grid, psfc)
        s, tend = fire_hour(hours, hvtl, 12.0, 50.0, et)
        back = st.first_crossing(hours, hvtl, 0.0, True, after=et)
        rows[rec] = (s, back)
        peak = np.nanmax(tend[hours > et])
        print(f"  {rec:>9.1f}  {peak:>12.0f} m  {fmt(s,' h'):>13}  {fmt(back,' h'):>14}")
    print("\n      The index is useful exactly where it fires AND the crossing")
    print("      happens. Where it fires and the crossing never comes, it is a")
    print("      false alarm; where the crossing comes and it never fires, a miss.")

    print("\n  (b) Noise on the height fields, 3 seeds each. HVTL is a window")
    print("      max minus min, and max-minus-min of noise is biased upward,")
    print("      so watch the peak tendency inflate as well as scatter.\n")
    print(f"  {'noise':>7}  {'case':>9}  {'peak tendency (3 seeds)':>26}  {'fires (50 m)':>22}")
    print("  " + "-" * 70)
    for noise in (0.0, 2.0, 5.0, 10.0):
        for rec, name in ((1.0, "seclusion"), (0.0, "decay")):
            peaks, fires = [], []
            for seed in range(3):
                hvtl, _ = run(rec, hours, track, grid, psfc, noise_m=noise, seed=seed)
                s, tend = fire_hour(hours, hvtl, 12.0, 50.0, et)
                peaks.append(np.nanmax(tend[hours > et]))
                fires.append(fmt(s))
            print(f"  {noise:>5.0f} m  {name:>9}  "
                  f"{', '.join(f'{p:.0f}' for p in peaks):>26}  {', '.join(fires):>22}")


def experiment_wind(hours, base, et):
    print("\n" + "=" * 72)
    print("4. WIND TIMING  -- see the module docstring before using these")
    print("=" * 72)
    print("  The wind and the phase space here are two readings of the same")
    print("  prescribed archetypes. This is what this synthetic implies, not")
    print("  evidence about lead over real hurricane-force winds.\n")

    for rec, name in ((1.0, "seclusion"), (0.0, "decay")):
        hvtl, wind = base[rec]
        fire, _ = fire_hour(hours, hvtl, 12.0, 50.0, et)
        after = hours > et
        w_after, h_after = wind[after], hours[after]
        i_min = int(np.nanargmin(w_after))
        w_min, h_min = float(w_after[i_min]), float(h_after[i_min])
        w_end = float(w_after[-1])

        print(f"  {name}:")
        print(f"    peak wind overall        {np.nanmax(wind):.0f} kt "
              f"at hour {hours[int(np.nanargmax(wind))]:.0f}  (the tropical phase)")
        print(f"    minimum after ET         {w_min:.0f} kt at hour {h_min:.0f}")
        print(f"    wind at hour 168         {w_end:.0f} kt "
              f"({w_end - w_min:+.0f} kt from the minimum)")
        if fire is not None:
            print(f"    index fires              hour {fire:.0f}")
            print(f"      lead over the wind turning point   {h_min - fire:+.0f} h")
        else:
            print("    index fires              never")
        print()

    print("  READ THIS BEFORE QUOTING ANY OF IT:")
    print()
    print("  * The wind never reaches hurricane force after transition in this")
    print("    synthetic -- it never reaches storm force either. It peaks at 76 kt")
    print("    during the tropical phase, falls to about 26 kt by hour 126, and the")
    print("    secluding storm recovers only to about 41 kt. So this synthetic")
    print("    contains no hurricane-force onset for the index to lead, and cannot")
    print("    answer the question 'how long before hurricane-force winds'.")
    print()
    print("  * Worse for the index: the wind turns UP BEFORE the index fires. The")
    print("    17 h figure is lead over HVTL's own zero crossing, a structural")
    print("    milestone that happens long after the wind has already begun")
    print("    recovering. Against the wind itself the index does not lead at all.")
    print()
    print("  * The archetypes were written to demonstrate the phase space, and the")
    print("    1000 hPa vortex broadens as it deepens, which holds the gradient")
    print("    down. A real seclusion tightens. Nothing here rules the index out;")
    print("    it means the wind question is outside what this synthetic can test.")


# ------------------------------------------------------------------ main
def main():
    hours = lc.make_hours()
    track = lc.build_track_and_motion(hours)
    grid = lc.build_grid()
    psfc, _ = lc.env_fields(grid[2])

    print("Computing the two reference cases ...", flush=True)
    base = {rec: run(rec, hours, track, grid, psfc) for rec in (1.0, 0.0)}
    et = et_hour(hours, base[1.0][0])
    print(f"ET completes (HVTL crosses below 0) at hour {et:.0f}; "
          "both storms are identical until hour 126.")

    experiment_threshold(hours, base, et)
    experiment_interval(hours, base, et)
    experiment_marginal(hours, track, grid, psfc, et)
    experiment_wind(hours, base, et)


if __name__ == "__main__":
    main()
