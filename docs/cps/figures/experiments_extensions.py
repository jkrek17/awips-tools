"""Synthetic tests of four candidate extensions to Hart's parameters.

Run from this directory: python3 experiments_extensions.py. Prints four
tables and writes figC_extensions.png. Tests 1 and 2 use the
operational module on 0.25 degree grids; tests 3 and 4 are analytic.

1. Background gradient removal. A deep warm core sits on a meridional
   height gradient that grows with height (a baroclinic zone). The
   package's lower and upper terms are compared with the isolated-vortex
   truth, for the gradient aligned with the grid and at 45 degrees, and
   again after the domain-wide background plane is subtracted from every
   level before the range is taken.
2. Storm-scaled radius. The lower term for vortices of 100 to 600 km
   e-folding scale at fixed window half-widths of 300, 500 and 700 km,
   and at a half-width scaled to 2.5 times the vortex scale (clipped to
   250 to 1000 km), each as a fraction of the profile's true slope.
3. Warm-core top from the vertical profile. For the five archetype
   profiles, the layer-by-layer slope of dZ against ln p on the seven
   standard levels, and the pressure at which the warm signal ends.
4. Vector asymmetry. For a thickness gradient of fixed magnitude at
   angles 0 to 90 degrees to the storm motion, Hart's B (the right-left
   projection) against the full gradient magnitude and the fore-aft
   component.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent.parent / "D2D" / "derivedParameters" / "functions"))
import cps_HartCPS as hc  # noqa: E402
from experiments import make_grid, dist_km, std_height, LEVELS, linear_amp, ANCHOR_P  # noqa: E402
from band_comparison import ARCHETYPES  # noqa: E402

hc.ORIENTATION_MODE = 0
TRUE_SLOPE = 191.0  # slope of the linear 250 -> 20 m amplitude profile


def fields_with_background(lat2d, lon2d, amp, g0_m_per_deg, angle_deg, scale_km=150.0):
    """Height on each level: standard height, minus a vortex, minus a
    background plane whose gradient magnitude grows with height and
    points at angle_deg from north (0 = purely meridional)."""
    r = dist_km(lat2d, lon2d, 45.0, 165.0)
    shape = np.exp(-((r / scale_km) ** 2))
    xdeg = (lon2d - 165.0) * np.cos(np.radians(45.0))
    ydeg = lat2d - 45.0
    a = np.radians(angle_deg)
    coord = ydeg * np.cos(a) + xdeg * np.sin(a)
    out, planes = {}, {}
    for p in LEVELS:
        g = g0_m_per_deg * (1.0 + 1.5 * np.log(1000.0 / p))
        planes[p] = g * coord
        out[p] = std_height(p) - amp[p] * shape - planes[p]
    return out, planes


def terms(z, dx, dy, ci, cj, radius=500.0):
    psfc = np.full(dx.shape, 1013.0)
    vtl = hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy, radius, 925.0, 850.0, 700.0)[ci, cj]
    vtu = hc.executeBand3(z[500], z[400], z[300], psfc, dx, dy, radius, 500.0, 400.0, 300.0)[ci, cj]
    return float(vtl), float(vtu)


def test_background():
    lats, lons, lat2d, lon2d, dx, dy = make_grid(0.25)
    ci = int(np.argmin(abs(lats - 45.0))); cj = int(np.argmin(abs(lons - 165.0)))
    amp = linear_amp(250.0, 20.0)
    print("1. Background gradient (m per degree at 1000 hPa, growing with height) and the terms at the center; truth is %.0f m for both" % TRUE_SLOPE)
    print("   gradient  angle   HVTL  HVTU   |  after plane removal: HVTL  HVTU")
    rows = []
    for g0 in (0.0, 5.0, 10.0, 20.0):
        for ang in (0, 45):
            if g0 == 0 and ang == 45:
                continue
            z, planes = fields_with_background(lat2d, lon2d, amp, g0, ang)
            vtl, vtu = terms(z, dx, dy, ci, cj)
            zr = {p: z[p] + planes[p] for p in LEVELS}
            vtl_r, vtu_r = terms(zr, dx, dy, ci, cj)
            rows.append((g0, ang, vtl, vtu, vtl_r, vtu_r))
            print(f"   {g0:6.0f}    {ang:3d}   {vtl:6.1f} {vtu:6.1f}   |                      {vtl_r:6.1f} {vtu_r:6.1f}")
    return rows


def test_radius():
    lats, lons, lat2d, lon2d, dx, dy = make_grid(0.25)
    ci = int(np.argmin(abs(lats - 45.0))); cj = int(np.argmin(abs(lons - 165.0)))
    amp = linear_amp(250.0, 20.0)
    scales = [100, 200, 300, 400, 600]
    radii = [300, 500, 700]
    print("\n2. Lower term as a fraction of the true slope, by vortex e-folding scale (rows) and window half-width (columns)")
    print("   scale   " + "".join(f"{r:>8d}" for r in radii) + "   scaled (2.5x)")
    table = []
    for s in scales:
        r = dist_km(lat2d, lon2d, 45.0, 165.0)
        shape = np.exp(-((r / s) ** 2))
        z = {p: std_height(p) - amp[p] * shape for p in LEVELS}
        vals = [terms(z, dx, dy, ci, cj, radius=R)[0] / TRUE_SLOPE for R in radii]
        rs = float(np.clip(2.5 * s, 250, 1000))
        vs = terms(z, dx, dy, ci, cj, radius=rs)[0] / TRUE_SLOPE
        table.append((s, vals, rs, vs))
        print(f"   {s:4d} km " + "".join(f"{v:8.2f}" for v in vals) + f"   {vs:6.2f} (at {rs:.0f} km)")
    return table


def test_profile():
    print("\n3. Layer slopes of dZ against ln p on the seven standard levels (m; positive = warm), and the warm-core top")
    layers = [(1000, 925), (925, 850), (850, 700), (700, 500), (500, 400), (400, 300)]
    print(f"   {'archetype':36s}" + "".join(f"{a}-{b:>4d}" for a, b in layers) + "   warm-core top")
    out = {}
    for name, anchors in ARCHETYPES.items():
        dz = dict(zip(ANCHOR_P.tolist(), anchors))
        sl = []
        for a, b in layers:
            sl.append((dz[a] - dz[b]) / (np.log(a) - np.log(b)))
        top = "none (warm to 300)"
        for (a, b), s in zip(layers, sl):
            if s < 0:
                top = f"{a} hPa"
                break
        if sl[0] < 0:
            top = "cold throughout" if all(s < 0 for s in sl) else "cold below, warm above"
        out[name] = (sl, top)
        print(f"   {name:36s}" + "".join(f"{s:9.0f}" for s in sl) + f"   {top}")
    return out


def test_vector_b():
    print("\n4. Vector asymmetry: thickness gradient of 40 m per 1000 km at an angle to the motion (0 = moving straight toward colder air)")
    G = 40.0 / 1000.0  # m per km
    k = hc.b_geometry_km(500.0) * hc.HART_B_LAYER_SCALE
    print("   angle   Hart B (right-left)   fore-aft   full magnitude")
    rows = []
    for ang in (0, 15, 30, 45, 60, 75, 90):
        b = k * G * np.sin(np.radians(ang))
        fa = k * G * np.cos(np.radians(ang))
        rows.append((ang, b, fa, k * G))
        print(f"   {ang:5d}   {b:19.1f}   {fa:8.1f}   {k * G:14.1f}")
    return rows


def main():
    bg = test_background()
    rad = test_radius()
    prof = test_profile()
    vec = test_vector_b()

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9))
    ax = axes[0]
    g = [r[0] for r in bg if r[1] == 0]
    ax.plot(g, [r[2] for r in bg if r[1] == 0], "o-", color="#e34948", label="HVTL, gradient on grid axis")
    ax.plot([r[0] for r in bg if r[1] == 45], [r[2] for r in bg if r[1] == 45], "s--", color="#e34948", label="HVTL, gradient at 45 deg")
    ax.plot(g, [r[3] for r in bg if r[1] == 0], "o-", color="#2a78d6", label="HVTU, on axis")
    ax.plot([r[0] for r in bg if r[1] == 45], [r[3] for r in bg if r[1] == 45], "s--", color="#2a78d6", label="HVTU, 45 deg")
    ax.plot(g, [r[4] for r in bg if r[1] == 0], "^:", color="0.3", label="after plane removal")
    ax.axhline(TRUE_SLOPE, color="k", lw=0.8)
    ax.set_xlabel("background height gradient at 1000 hPa (m per deg)")
    ax.set_ylabel("term at center (m)")
    ax.set_title("(a) background gradient", loc="left", fontsize=10)
    ax.legend(fontsize=6.5)

    ax = axes[1]
    for k, R in enumerate((300, 500, 700)):
        ax.plot([t[0] for t in rad], [t[1][k] for t in rad], "o-", label=f"half-width {R} km")
    ax.plot([t[0] for t in rad], [t[3] for t in rad], "k^--", label="half-width 2.5 x scale")
    ax.axhline(1.0, color="k", lw=0.8)
    ax.set_xlabel("vortex e-folding scale (km)")
    ax.set_ylabel("lower term / true slope")
    ax.set_title("(b) window radius versus storm size", loc="left", fontsize=10)
    ax.legend(fontsize=7)

    ax = axes[2]
    ax.plot([r[0] for r in vec], [r[1] for r in vec], "o-", color="#e34948", label="Hart B (right minus left)")
    ax.plot([r[0] for r in vec], [r[2] for r in vec], "s-", color="#2a78d6", label="fore minus aft")
    ax.axhline(vec[0][3], color="k", lw=0.8, label="full magnitude")
    ax.axhline(10, color="0.5", lw=0.8, ls=":", label="10 m threshold")
    ax.set_xlabel("angle between thickness gradient and motion (deg)")
    ax.set_ylabel("m")
    ax.set_title("(c) vector asymmetry", loc="left", fontsize=10)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(HERE / "figC_extensions.png", dpi=300)
    print("\nwrote", HERE / "figC_extensions.png")


if __name__ == "__main__":
    main()
