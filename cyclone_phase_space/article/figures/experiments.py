"""Sensitivity experiments on synthetic fields with the operational code.

Run from this directory: python3 experiments.py. Prints five tables and
writes figB_experiments.png. Everything is analytic or built from
Gaussian vortices on a 0.25 degree latitude-longitude grid, and the
diagnostics are computed by cps_HartCPS.py itself, so the numbers are
the package's own behavior, not a model of it.

1. Timing: a storm's height-perturbation profile is morphed from deep
   warm core through a transitioning shape to deep cold core with a
   progress parameter t in [0, 1]. The t at which each band's lower
   term crosses zero (completion) and each upper band crosses zero is
   reported. A band that crosses later than Hart's would call
   completion late.
2. Closed-low detector: detection of a Gaussian low as a function of
   its central depth and e-folding scale, plus two false-positive
   tests (an open trough with a strong cross-trough gradient, and a
   broad flat-centered low).
3. Resolution: the same vortex on 0.25, 0.5 and 1.0 degree grids.
4. Steering: a wavenumber-one asymmetric vortex in an 8 m/s westerly;
   heading error of the window-averaged proxy at the center.
5. Noise: Gaussian height noise added to every level; standard
   deviation of the terms and B at the center over 60 realizations.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "D2D" / "derivedParameters" / "functions"))
import cps_HartCPS as hc  # noqa: E402

hc.ORIENTATION_MODE = 0  # rows increase northward on these grids
R_EARTH = 6371.0e3
LEVELS = [1000, 925, 850, 700, 500, 400, 300]
P50 = np.arange(1000, 299, -50)


# ---------------------------------------------------------------- grids
def make_grid(dlat, lat0=30.0, lat1=60.0, lon0=130.0, lon1=200.0):
    lats = np.arange(lat0, lat1 + 1e-9, dlat)
    lons = np.arange(lon0, lon1 + 1e-9, dlat)
    lon2d, lat2d = np.meshgrid(lons, lats)
    dy = np.full(lat2d.shape, R_EARTH * np.radians(dlat))
    dx = R_EARTH * np.cos(np.radians(lat2d)) * np.radians(dlat)
    return lats, lons, lat2d, lon2d, dx, dy


def dist_km(lat2d, lon2d, clat, clon):
    dlat = np.radians(lat2d - clat)
    dlon = np.radians(lon2d - clon)
    a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(clat)) * np.cos(np.radians(lat2d)) * np.sin(dlon / 2) ** 2
    return 2 * R_EARTH / 1e3 * np.arcsin(np.sqrt(a))


def std_height(p):
    """Standard-atmosphere height (m) of pressure p (hPa)."""
    return 44330.0 * (1 - (p / 1013.25) ** 0.1903)


def vortex_heights(lat2d, lon2d, clat, clon, scale_km, amp_by_level, background_m_per_deg=0.0, asym=0.0):
    """Height on each level: standard height minus a Gaussian depression
    of amplitude amp_by_level[p], optional meridional background
    gradient (m per degree latitude, growing with height), optional
    wavenumber-one asymmetry (fraction, deeper to the east)."""
    r = dist_km(lat2d, lon2d, clat, clon)
    ang = np.arctan2(lat2d - clat, (lon2d - clon) * np.cos(np.radians(clat)))
    shape = np.exp(-((r / scale_km) ** 2)) * (1 + asym * np.cos(ang))
    out = {}
    for p in LEVELS:
        bg = background_m_per_deg * (lat2d - 45.0) * (np.log(1000 / p) + 0.3)
        out[p] = std_height(p) - amp_by_level[p] * shape - bg
    return out


def linear_amp(a1000, a300):
    x = np.log(np.array(LEVELS, float))
    return dict(zip(LEVELS, np.interp(x, [np.log(300), np.log(1000)], [a300, a1000])))


# ------------------------------------------------ 1. timing (analytic)
ANCHOR_P = np.array([1000, 925, 850, 700, 600, 500, 400, 300])
DEEP_WARM = np.array([260, 235, 205, 150, 115, 85, 50, 20], float)
TRANSITION = np.array([200, 190, 165, 120, 110, 150, 220, 300], float)
DEEP_COLD = np.array([60, 70, 90, 130, 180, 240, 300, 350], float)


def profile_at(t):
    if t <= 0.5:
        return DEEP_WARM + (TRANSITION - DEEP_WARM) * (t / 0.5)
    return TRANSITION + (DEEP_COLD - TRANSITION) * ((t - 0.5) / 0.5)


def band_slope(levels, anchors):
    x = np.log(np.asarray(levels, float))
    y = np.interp(x[::-1], np.log(ANCHOR_P)[::-1], anchors[::-1])[::-1]
    return np.polyfit(x, y, 1)[0]


def crossing(fn, ts):
    v = np.array([fn(t) for t in ts])
    idx = np.where(np.sign(v[:-1]) != np.sign(v[1:]))[0]
    if len(idx) == 0:
        return np.nan
    i = idx[0]
    return ts[i] + (ts[i + 1] - ts[i]) * v[i] / (v[i] - v[i + 1])


def timing():
    ts = np.linspace(0, 1, 2001)
    lower = {
        "Hart 900-600": lambda t: band_slope(np.arange(900, 599, -50), profile_at(t)),
        "925/850/700 (in use)": lambda t: band_slope([925, 850, 700], profile_at(t)),
        "925/850/700/500": lambda t: band_slope([925, 850, 700, 500], profile_at(t)),
        "mean of two 3-level slopes": lambda t: 0.5 * (band_slope([925, 850, 700], profile_at(t)) + band_slope([850, 700, 500], profile_at(t))),
    }
    upper = {
        "Hart 600-300": lambda t: band_slope(np.arange(600, 299, -50), profile_at(t)),
        "500/400/300 (in use)": lambda t: band_slope([500, 400, 300], profile_at(t)),
    }
    print("1. Transition timing: progress t at which the term crosses zero (0 = deep warm, 0.5 = transitioning profile, 1 = deep cold)")
    for k, f in lower.items():
        print(f"   lower term, {k:30s} t = {crossing(f, ts):.3f}")
    for k, f in upper.items():
        print(f"   upper term, {k:30s} t = {crossing(f, ts):.3f}")
    return {k: crossing(f, ts) for k, f in {**lower, **upper}.items()}


# ------------------------------------------------ 2. closed-low detector
def detector_map():
    lats, lons, lat2d, lon2d, dx, dy = make_grid(0.25)
    depths = [20, 30, 40, 50, 60, 80, 100, 120]
    scales = [100, 150, 200, 300, 400, 500, 600, 800]
    hit = np.zeros((len(depths), len(scales)), bool)
    clat, clon = 45.0, 165.0
    ci = int(np.argmin(abs(lats - clat)))
    cj = int(np.argmin(abs(lons - clon)))
    for i, d in enumerate(depths):
        for j, s in enumerate(scales):
            z = std_height(1000) - d * np.exp(-((dist_km(lat2d, lon2d, clat, clon) / s) ** 2))
            m = hc.closed_low_mask(z, dx, dy, hc.MIN_RADIUS_KM, hc.RADIUS_KM, hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM, hc.DEFAULT_CENTER_TOL_M)
            hit[i, j] = bool(m[ci, cj])
    print("\n2. Closed-low detector: detected (X) or not (.) at the center, by central depth (rows, m) and e-folding scale (columns, km)")
    print("   depth\\scale " + " ".join(f"{s:>4d}" for s in scales))
    for i, d in enumerate(depths):
        print(f"   {d:>6d} m    " + " ".join(f"{'X' if hit[i, j] else '.':>4s}" for j in range(len(scales))))
    # false positive tests
    r = dist_km(lat2d, lon2d, clat, clon)
    x_km = (lon2d - clon) * 111.0 * np.cos(np.radians(clat))
    y_km = (lat2d - clat) * 111.0
    trough = std_height(1000) + 0.04 * abs(x_km) - 0.03 * y_km  # V-shaped trough, 40 m per 1000 km each side, 30 m per 1000 km along
    m_trough = hc.closed_low_mask(trough, dx, dy, hc.MIN_RADIUS_KM, hc.RADIUS_KM, hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM, hc.DEFAULT_CENTER_TOL_M)
    flat = std_height(1000) - 80.0 * np.exp(-((np.clip(r - 300.0, 0, None) / 250.0) ** 2))  # 80 m deep, flat within 300 km
    m_flat = hc.closed_low_mask(flat, dx, dy, hc.MIN_RADIUS_KM, hc.RADIUS_KM, hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM, hc.DEFAULT_CENTER_TOL_M)
    elong = std_height(1000) - 80.0 * np.exp(-((x_km / 700.0) ** 2) - ((y_km / 150.0) ** 2))  # elongated 80 m low, 700 by 150 km
    m_elong = hc.closed_low_mask(elong, dx, dy, hc.MIN_RADIUS_KM, hc.RADIUS_KM, hc.DEFAULT_DEPTH_M, hc.DEFAULT_BLOB_RADIUS_KM, hc.DEFAULT_CENTER_TOL_M)
    print(f"   open V trough, 40 m per 1000 km cross-trough gradient: detected anywhere = {bool(np.nanmax(m_trough))}")
    print(f"   80 m low with a flat 300 km center:                      detected at center = {bool(m_flat[ci, cj])}, anywhere = {bool(np.nanmax(m_flat))}")
    print(f"   80 m elongated low, 700 by 150 km:                       detected at center = {bool(m_elong[ci, cj])}")
    return depths, scales, hit


# ------------------------------------------------ 3. resolution
def resolution():
    print("\n3. Resolution: the same deep warm core (150 km scale, 250 m at 1000 hPa, 20 m at 300 hPa) on three grids")
    amp = linear_amp(250.0, 20.0)
    out = {}
    for dlat in (0.25, 0.5, 1.0):
        lats, lons, lat2d, lon2d, dx, dy = make_grid(dlat)
        z = vortex_heights(lat2d, lon2d, 45.0, 165.0, 150.0, amp)
        psfc = np.full(lat2d.shape, 1013.0)
        vtl = hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy, 500.0, 925.0, 850.0, 700.0)
        vtu = hc.executeBand3(z[500], z[400], z[300], psfc, dx, dy, 500.0, 500.0, 400.0, 300.0)
        ci = int(np.argmin(abs(lats - 45.0))); cj = int(np.argmin(abs(lons - 165.0)))
        out[dlat] = (float(vtl[ci, cj]), float(vtu[ci, cj]))
        print(f"   {dlat:4.2f} deg: HVTL = {vtl[ci, cj]:7.1f} m   HVTU = {vtu[ci, cj]:7.1f} m")
    amp2 = linear_amp(250.0, 20.0)
    print("   same vortex at 400 km scale:")
    for dlat in (0.25, 0.5, 1.0):
        lats, lons, lat2d, lon2d, dx, dy = make_grid(dlat)
        z = vortex_heights(lat2d, lon2d, 45.0, 165.0, 400.0, amp2)
        psfc = np.full(lat2d.shape, 1013.0)
        vtl = hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy, 500.0, 925.0, 850.0, 700.0)
        ci = int(np.argmin(abs(lats - 45.0))); cj = int(np.argmin(abs(lons - 165.0)))
        print(f"   {dlat:4.2f} deg: HVTL = {vtl[ci, cj]:7.1f} m")
    return out


# ------------------------------------------------ 4. steering with an asymmetric vortex
def steering_asym():
    print("\n4. Steering proxy at the center: gradient-wind-like vortex circulation plus an 8 m/s westerly, with wavenumber-one asymmetry")
    lats, lons, lat2d, lon2d, dx, dy = make_grid(0.25)
    f = 2 * 7.292e-5 * np.sin(np.radians(45.0))
    for asym in (0.0, 0.2, 0.4):
        amp = linear_amp(250.0, 20.0)
        z = vortex_heights(lat2d, lon2d, 45.0, 165.0, 200.0, amp, asym=asym)
        us, vs = [], []
        for p in (850, 700, 500, 300):
            gy, gx = np.gradient(z[p], axis=0), np.gradient(z[p], axis=1)
            ug = -9.81 / f * gy / dy
            vg = 9.81 / f * gx / dx
            us.append(ug + 8.0); vs.append(vg)
        u_s, v_s = hc.steering(us, vs)
        u_w, v_w = hc.steering_window_mean(u_s, v_s, dx, dy, 500.0)
        ci = int(np.argmin(abs(lats - 45.0))); cj = int(np.argmin(abs(lons - 165.0)))
        spd = np.hypot(u_w[ci, cj], v_w[ci, cj]); hdg = (np.degrees(np.arctan2(u_w[ci, cj], v_w[ci, cj])) + 360) % 360
        raw = np.hypot(u_s[ci + 4, cj], v_s[ci + 4, cj])
        print(f"   asymmetry {asym:.1f}: window-mean speed {spd:5.2f} m/s, heading {hdg:5.1f} deg (truth 8.00 m/s, 090); pointwise speed 1 deg north of center {raw:5.1f} m/s")


# ------------------------------------------------ 5. noise
def noise():
    print("\n5. Noise: 5 m Gaussian height noise on every level, 60 realizations; standard deviation of the terms and B at the center")
    rng = np.random.default_rng(0)
    lats, lons, lat2d, lon2d, dx, dy = make_grid(0.25)
    amp = linear_amp(250.0, 20.0)
    z0 = vortex_heights(lat2d, lon2d, 45.0, 165.0, 200.0, amp, background_m_per_deg=6.0)
    psfc = np.full(lat2d.shape, 1013.0)
    ci = int(np.argmin(abs(lats - 45.0))); cj = int(np.argmin(abs(lons - 165.0)))
    u = np.full(lat2d.shape, 8.0); v = np.zeros_like(u); cor = np.full(lat2d.shape, 1e-4)
    vals = []
    for _ in range(60):
        z = {p: z0[p] + rng.normal(0, 5.0, z0[p].shape) for p in LEVELS}
        vtl = hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy, 500.0, 925.0, 850.0, 700.0)[ci, cj]
        vtu = hc.executeBand3(z[500], z[400], z[300], psfc, dx, dy, 500.0, 500.0, 400.0, 300.0)[ci, cj]
        b = hc.executeB(z[925], z[700], u, v, u, v, u, v, u, v, psfc, cor, dx, dy, 500.0, hc.HART_B_LAYER_SCALE, 900.0)[ci, cj]
        vals.append((vtl, vtu, b))
    vals = np.array(vals)
    print(f"   HVTL: mean {vals[:,0].mean():7.1f} m, sd {vals[:,0].std():5.1f} m")
    print(f"   HVTU: mean {vals[:,1].mean():7.1f} m, sd {vals[:,1].std():5.1f} m")
    print(f"   HB:   mean {vals[:,2].mean():7.1f} m, sd {vals[:,2].std():5.1f} m")
    return vals


def main():
    t = timing()
    depths, scales, hit = detector_map()
    resolution()
    steering_asym()
    noise()
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    ax.imshow(hit, cmap="Greys", vmin=0, vmax=1.4, origin="lower", aspect="auto")
    ax.set_xticks(range(len(scales))); ax.set_xticklabels(scales)
    ax.set_yticks(range(len(depths))); ax.set_yticklabels(depths)
    ax.set_xlabel("e-folding scale (km)"); ax.set_ylabel("central depth at 1000 hPa (m)")
    ax.set_title("closed-low detector: dark = detected at center", fontsize=9)
    fig.tight_layout(); fig.savefig(HERE / "figB_detector.png", dpi=300)
    print("\nwrote", HERE / "figB_detector.png")


if __name__ == "__main__":
    main()
