"""One large synthetic basin scene, the size of the North Atlantic
four-panel a forecaster actually looks at, with many features at once,
run through the operational gridded module
(cyclone_phase_space/D2D/derivedParameters/functions/cps_HartCPS.py).

Reuses the case-building blocks feature_catalog.py already established
(vortex_shape, amp_at, front_shape, profile_in_lnp, dipole_term, the
archetypes and anchor lists) and lifecycle_comparison.build_grid (given
an optional domain argument for this file, default unchanged) /
env_fields, plus regime_prototype.classify_regime for panel (f). Domain:
0.25 deg, 10-70N, 100W-10E (negative longitude west).

Background: a deep baroclinic zone (feature_catalog.DEEP_PARTS's own
vertical profile -- a gradient growing with height through every level,
so it also carries an implied jet aloft -- unchanged) confined to a band
along a wavy polar front: a tanh step across the front's own centerline,
3 deg half-width (about 300 km either side), plus a weak residual slope
(20% of the step's own peak rate) that continues gently rather than
flattening completely, so the band reads as a band -- HB and HVTL a
strip along the front, pale to clear well away from it -- instead of one
continuous zone from the front to the domain's own edge. The front's
centre latitude is 47N plus a 6 degree sine wave, one trough near 60W and
one ridge near 25W. A low-level easterly belt sits south of 22N (same
mechanism regime_prototype's composite scene uses, amplitude halved here
so its own HB reads pale rather than solid teal). Steering is a single
zonal wind profile, uniform by latitude: easterly south of 22N, turning
westerly and peaking along the front near 47N.

Nine features, one number each on panel (a), all built from the same
archetypes/anchors/scales feature_catalog.py's own catalog rows use
(band_comparison.ARCHETYPES via feature_catalog.DEEP_WARM/TRANSITION/
DEEP_COLD/SHALLOW_WARM/CUTOFF_ANCHORS, and the two isolated-anticyclone
anchor lists feature_catalog's own shallow-cold-high/warm-ridge rows
use), each moving with the local steering wind unless a feature-specific
motion is given.

Figure: 2x3, one row of maps per pair -- (a) 1000 hPa height (40 m) and
1000-500 hPa thickness (60 m dashed red), features numbered; (b)
HCPSclass over the 1000 hPa contours, the shipped class palette; (c) HB,
the CPS_Asymmetry mimic, +/-40 m; (d) HVTL and (e) HVTU, the red/blue
mimic, +/-300 m; (f) the regime prototype's own map, with its legend.
Every panel shows the whole domain with a light graticule, no
coastlines.

Run from this directory:

    python3 basin_scene.py

Prints, per feature, the sampled HVTL/HVTU/HB and class (the six lows)
or regime code (the two anticyclones and the ridge) at its own center,
and the class the catalog expects for a low. Writes figI_basin_scene.png
(300 dpi).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import feature_catalog as fc  # noqa: E402
from feature_catalog import hc  # noqa: E402
import lifecycle_comparison as lc  # noqa: E402
from regime_prototype import (  # noqa: E402
    classify_regime, REGIME_CMAP, REGIME_NORM, REGIME_NAMES, REGIME_COLORS, ENV_CODES_FOR_LEGEND,
)

FIGI_PATH = HERE / "figI_basin_scene.png"

# --------------------------------------------------------------- domain
DOMAIN = dict(lat0=10.0, lat1=70.0, lon0=-100.0, lon1=10.0)
lat_vals, lon_vals, lat2d, lon2d, dx, dy = lc.build_grid(dlat=0.25, **DOMAIN)
psfc, coriolis = lc.env_fields(lat2d)
EXTENT = (lon_vals.min(), lon_vals.max(), lat_vals.min(), lat_vals.max())


def center_ij(clat, clon):
    ci = int(np.argmin(np.abs(lat_vals - clat)))
    cj = int(np.argmin(np.abs(lon_vals - clon)))
    return ci, cj


# ------------------------------------------------------ wavy front / jet
FRONT_LAT0 = 47.0
FRONT_AMP = 6.0
FRONT_TROUGH_LON = -60.0
FRONT_WAVELENGTH = 70.0  # deg; trough at -60, ridge at -25 (half a wavelength apart)


def front_center_lat(lon2d):
    """The front's own latitude at every longitude: 47N plus a 6 deg sine
    wave, minimum (trough, equatorward) near 60W, maximum (ridge,
    poleward) near 25W.
    """
    return FRONT_LAT0 - FRONT_AMP * np.cos(2.0 * np.pi * (lon2d - FRONT_TROUGH_LON) / FRONT_WAVELENGTH)


FRONT_CENTER_LAT2D = front_center_lat(lon2d)
FRONT_REL_LAT = lat2d - FRONT_CENTER_LAT2D  # signed distance from the front's own centerline, degrees

# Real fronts are bands, not a step that keeps deepening for 60 degrees of
# latitude: front_shape's own "ramp then grow forever poleward" (used in
# the first version of this scene) made the whole domain north of the
# front one continuous baroclinic zone, drowning the arctic dome and the
# occluded low in background rather than their own signal. Replaced here
# with a tanh step confined to a 3 deg half-width (about 300 km either
# side of the line, where tanh(x/H)'s own derivative -- the actual
# gradient -- is concentrated), plus a weak residual slope, 20% of the
# step's own peak rate, that continues (both sides, not just poleward)
# rather than flattening completely -- real baroclinicity does not stop
# dead at the band's edge, it just gets much weaker. tanh(x/H) alone
# saturates to +/-1 within a few H and does not blow up like the old
# ramp+unbounded-beyond did, so no additional cap is needed here.
FRONT_STEP_HALFWIDTH = 3.0  # deg latitude, about 300 km
FRONT_RESIDUAL_FRAC = 0.20


def confined_front_shape(rel_lat, halfwidth=FRONT_STEP_HALFWIDTH, residual_frac=FRONT_RESIDUAL_FRAC):
    x = rel_lat / halfwidth
    return np.tanh(x) + residual_frac * x


# Low-level easterly belt, south of 22N -- same mechanism as
# regime_prototype's own composite scene, recentred so the belt's own
# ramp sits south of 22N instead of 25N, amplitude halved from that scene
# (-6/-5 m) so its own HB reads pale rather than solid teal.
EAST_CENTER = 17.0
EAST_HALFWIDTH = 5.0
EAST_COEF = {1000.0: -3.0, 925.0: -2.5, 850.0: 0.0, 700.0: 0.0, 500.0: 0.0, 400.0: 0.0, 300.0: 0.0}

# Steering: a single zonal wind profile, uniform by latitude -- easterly
# south of 22N, turning westerly and peaking along the front near 47N,
# easing off north of it. v = 0 everywhere (purely zonal).
STEER_LAT_PTS = np.array([10.0, 22.0, 28.0, 35.0, 47.0, 60.0, 70.0])
STEER_U_PTS = np.array([-8.0, -8.0, 0.0, 8.0, 15.0, 10.0, 8.0])


def steering_u(lat):
    return float(np.interp(lat, STEER_LAT_PTS, STEER_U_PTS))


U2D = np.interp(lat2d.ravel(), STEER_LAT_PTS, STEER_U_PTS).reshape(lat2d.shape)
V2D = np.zeros_like(U2D)


# ------------------------------------------------------------- features
STORM_SCALE_KM = fc.STORM_SCALE_KM  # 250 km, the catalog's own typical storm scale
HIGH_ANCHORS = [150, 120, 70, 25, 10, 0, 0, 0]   # feature_catalog's own shallow-cold-high/arctic-dome anchors
RIDGE_ANCHORS = [20, 40, 70, 100, 120, 150, 180, 220]  # feature_catalog's own warm-ridge anchors

FEATURES = [
    dict(num=1, name="Hurricane", kind="vortex", clat=20.0, clon=-62.0, sign=-1, anchors=fc.DEEP_WARM,
         amp_scale=1.0, scale_km=150.0, dipole_peak=0.0, expected_class=0),
    dict(num=2, name="Transitioning tropical cyclone", kind="vortex", clat=38.0, clon=-58.0, sign=-1,
         anchors=fc.TRANSITION, amp_scale=1.0, scale_km=STORM_SCALE_KM, dipole_peak=120.0,
         heading_deg=45.0, speed_ms=15.0, expected_class=3),
    dict(num=3, name="Frontal wave (weak)", kind="vortex", clat=44.0, clon=-75.0, sign=-1,
         anchors=fc.DEEP_COLD, amp_scale=0.6, scale_km=STORM_SCALE_KM, dipole_peak=40.0, expected_class=4),
    dict(num=4, name="Mature occluded low", kind="vortex", clat=60.0, clon=-40.0, sign=-1,
         anchors=fc.DEEP_COLD, amp_scale=1.0, scale_km=STORM_SCALE_KM, dipole_peak=0.0, expected_class=5),
    dict(num=5, name="Warm seclusion (959 hPa type)", kind="vortex", clat=55.0, clon=-20.0, sign=-1,
         anchors=fc.SHALLOW_WARM, amp_scale=1.5, scale_km=300.0, dipole_peak=0.0, expected_class=1),
    dict(num=6, name="Cut-off low", kind="vortex", clat=33.0, clon=-18.0, sign=-1,
         anchors=fc.CUTOFF_ANCHORS, amp_scale=1.0, scale_km=STORM_SCALE_KM, dipole_peak=0.0, expected_class=5),
    dict(num=7, name="Shallow cold high", kind="anticyclone", clat=48.0, clon=-92.0, sign=+1,
         anchors=HIGH_ANCHORS, amp_scale=1.0, scale_km=500.0, expected_regime=5),
    dict(num=8, name="Warm subtropical ridge", kind="anticyclone", clat=30.0, clon=-42.0, sign=+1,
         anchors=RIDGE_ANCHORS, amp_scale=0.5, scale_km=800.0, expected_regime=8),
    dict(num=9, name="Arctic cold dome", kind="anticyclone", clat=64.0, clon=-75.0, sign=+1,
         anchors=HIGH_ANCHORS, amp_scale=1.0, scale_km=350.0, expected_regime=5),
]


def feature_motion(feat):
    """(heading_deg, speed_ms) for a feature's own motion-relative
    dipole: the feature's own override if given, else derived from the
    local steering wind at its center (v = 0 everywhere here, so heading
    is 90 for any eastward/westerly push, -90 for an easterly one).
    """
    if "heading_deg" in feat:
        return feat["heading_deg"], feat["speed_ms"]
    u = steering_u(feat["clat"])
    heading = 90.0 if u >= 0.0 else -90.0
    return heading, max(abs(u), 1.0)


# --------------------------------------------------------- height build
def build_levels():
    levels = {}
    for p in fc.LEVELS7:
        z = fc.std_height(p)

        for g0, points in fc.DEEP_PARTS:
            g = g0 * fc.profile_in_lnp(p, points)
            z = z - g * confined_front_shape(FRONT_REL_LAT)

        z = z + EAST_COEF[p] * fc.front_shape(-lat2d, -EAST_CENTER, EAST_HALFWIDTH)

        for feat in FEATURES:
            shape = fc.vortex_shape(lat2d, lon2d, feat["clat"], feat["clon"], feat["scale_km"])
            amp = fc.amp_at(p, feat["anchors"]) * feat["amp_scale"]
            z = z + feat["sign"] * amp * shape
            if feat.get("dipole_peak", 0.0):
                heading_deg, speed_ms = feature_motion(feat)
                z = z + fc.dipole_term(p, lat2d, lon2d, feat["clat"], feat["clon"], heading_deg, speed_ms,
                                        feat["dipole_peak"])

        levels[p] = z
    return levels


def compute_fields(levels):
    vtl = hc.executeBand3(levels[925.0], levels[850.0], levels[700.0], psfc, dx, dy, fc.RADIUS_KM,
                           925.0, 850.0, 700.0)
    vtu = hc.executeBand3(levels[500.0], levels[400.0], levels[300.0], psfc, dx, dy, fc.RADIUS_KM,
                           500.0, 400.0, 300.0)
    b = hc.executeB(levels[925.0], levels[700.0], U2D, V2D, U2D, V2D, U2D, V2D, U2D, V2D,
                     psfc, coriolis, dx, dy, radiusKm=fc.RADIUS_KM, layerScale=hc.HART_B_LAYER_SCALE)
    cls = hc.executeHartClass(levels[1000.0], levels[925.0], levels[850.0], levels[700.0], levels[500.0],
                               levels[400.0], levels[300.0], U2D, V2D, U2D, V2D, U2D, V2D, U2D, V2D,
                               psfc, coriolis, dx, dy, radiusKm=fc.RADIUS_KM)
    return vtl, vtu, b, cls


# ------------------------------------------------------------- panels
def _map_axes(ax, fs=7):
    ax.set_xlim(lon_vals.min(), lon_vals.max())
    ax.set_ylim(lat_vals.min(), lat_vals.max())
    ax.grid(True, color="0.85", lw=0.3, zorder=0)
    ax.tick_params(labelsize=fs - 1)
    ax.set_xticks(np.arange(-100, 11, 20))
    ax.set_yticks(np.arange(10, 71, 10))


def draw_panel_a(ax, levels, thick, fs=7):
    z1000 = levels[1000.0]
    cs_h = ax.contour(lon2d, lat2d, z1000, levels=fc.level_step(z1000, 40.0), colors="0.3", linewidths=0.5)
    ax.clabel(cs_h, fontsize=fs - 1, fmt="%d", inline=True)
    ax.contour(lon2d, lat2d, thick, levels=fc.level_step(thick, 60.0), colors=fc.RED, linewidths=0.5,
               linestyles="dashed")
    for feat in FEATURES:
        ax.plot(feat["clon"], feat["clat"], "o", color="k", ms=4, mec="white", mew=0.5, zorder=5)
        ax.annotate(str(feat["num"]), (feat["clon"], feat["clat"]), textcoords="offset points",
                    xytext=(5, 4), fontsize=fs, fontweight="bold", zorder=6)
    ax.set_title("(a) 1000 hPa height, 1000-500 hPa thickness", fontsize=8)
    _map_axes(ax, fs)


def draw_class_panel(ax, levels, cls, fs=7):
    masked = np.ma.masked_invalid(cls)
    ax.imshow(masked, extent=EXTENT, origin="lower", cmap=fc.CLASS_CMAP, norm=fc.CLASS_NORM,
              interpolation="nearest", aspect="auto", zorder=1)
    ax.contour(lon2d, lat2d, levels[1000.0], levels=fc.level_step(levels[1000.0], 40.0), colors="0.3",
               linewidths=0.4, zorder=2)
    ax.set_title("(b) HCPSclass", fontsize=8)
    _map_axes(ax, fs)


def draw_hb_panel(ax, levels, b, fs=7):
    masked = np.ma.masked_invalid(b)
    ax.imshow(masked, extent=EXTENT, origin="lower", cmap=fc.ASYMMETRY_CMAP, vmin=-fc.HB_RANGE, vmax=fc.HB_RANGE,
              interpolation="nearest", aspect="auto", zorder=1)
    ax.contour(lon2d, lat2d, levels[1000.0], levels=fc.level_step(levels[1000.0], 40.0), colors="0.4",
               linewidths=0.4, zorder=2)
    ax.set_title("(c) HB, CPS_Asymmetry", fontsize=8)
    _map_axes(ax, fs)


def draw_diverging_panel(ax, levels, field, title, fs=7):
    rgba = fc.diverging_rgba(field, 300.0)
    ax.imshow(rgba, extent=EXTENT, origin="lower", interpolation="nearest", aspect="auto", zorder=1)
    ax.contour(lon2d, lat2d, levels[1000.0], levels=fc.level_step(levels[1000.0], 40.0), colors="0.4",
               linewidths=0.4, zorder=2)
    ax.set_title(title, fontsize=8)
    _map_axes(ax, fs)


def draw_regime_panel(ax, codes, fs=7):
    masked = np.ma.masked_invalid(codes)
    ax.imshow(masked, extent=EXTENT, origin="lower", cmap=REGIME_CMAP, norm=REGIME_NORM,
              interpolation="nearest", aspect="auto", zorder=1)
    ax.set_title("(f) regime map (environment only)", fontsize=8)
    _map_axes(ax, fs)
    env_handles = [Patch(facecolor=REGIME_COLORS[k], edgecolor="0.3", label=f"{k} {REGIME_NAMES[k]}")
                   for k in ENV_CODES_FOR_LEGEND]
    ax.legend(handles=env_handles, loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=6,
              frameon=False, handlelength=1.2, handleheight=1.2)


# ----------------------------------------------------------------- main
def sample(field, clat, clon):
    ci, cj = center_ij(clat, clon)
    return float(field[ci, cj])


def main():
    print(f"Domain: {lat2d.shape[0]} x {lat2d.shape[1]} points, "
          f"{lat_vals.min():.1f}-{lat_vals.max():.1f}N, {lon_vals.min():.1f}-{lon_vals.max():.1f}E")

    levels = build_levels()
    thick = levels[500.0] - levels[1000.0]
    vtl, vtu, b, cls = compute_fields(levels)
    codes, d, trough, closed_high = classify_regime(vtl, vtu, b, levels[1000.0], dx, dy, psfc)

    print(f"\n{'#':>2s} {'feature':32s} {'HVTL':>8s} {'HVTU':>8s} {'HB':>7s} {'class/regime':>14s} "
          f"{'catalog expects':>16s}  note")
    mismatches = []
    for feat in FEATURES:
        v_l = sample(vtl, feat["clat"], feat["clon"])
        v_u = sample(vtu, feat["clat"], feat["clon"])
        v_b = sample(b, feat["clat"], feat["clon"])
        ci, cj = center_ij(feat["clat"], feat["clon"])
        if feat["kind"] == "vortex":
            c = cls[ci, cj]
            found_txt = "NaN" if np.isnan(c) else str(int(round(c)))
            expected = feat["expected_class"]
            ok = (not np.isnan(c)) and int(round(c)) == expected
            note = "OK" if ok else "MISMATCH"
            if not ok:
                mismatches.append((feat, found_txt, expected))
            print(f"{feat['num']:2d} {feat['name']:32s} {v_l:8.1f} {v_u:8.1f} {v_b:7.2f} "
                  f"{found_txt:>14s} {expected:>16d}  {note}")
        else:
            code = codes[ci, cj]
            code_txt = "NaN" if np.isnan(code) else str(int(round(code)))
            expected = feat["expected_regime"]
            ok = (not np.isnan(code)) and int(round(code)) == expected
            note = "OK" if ok else "MISMATCH"
            if not ok:
                mismatches.append((feat, code_txt, expected))
            print(f"{feat['num']:2d} {feat['name']:32s} {v_l:8.1f} {v_u:8.1f} {v_b:7.2f} "
                  f"{code_txt:>14s} {expected:>16d}  {note}")

    fig, axes = plt.subplots(2, 3, figsize=(19.0, 12.5), constrained_layout=True)
    draw_panel_a(axes[0, 0], levels, thick)
    draw_class_panel(axes[0, 1], levels, cls)
    draw_hb_panel(axes[0, 2], levels, b)
    draw_diverging_panel(axes[1, 0], levels, vtl, "(d) HVTL")
    draw_diverging_panel(axes[1, 1], levels, vtu, "(e) HVTU")
    draw_regime_panel(axes[1, 2], codes)

    fig.suptitle("Basin scene: nine synthetic features on one North Atlantic domain (synthetic, gridded module)",
                 fontsize=12)
    fig.savefig(FIGI_PATH, dpi=300)
    plt.close(fig)

    size = FIGI_PATH.stat().st_size / 1e6
    print(f"\nwrote {FIGI_PATH} ({size:.2f} MB)")

    if mismatches:
        print("\nFeatures whose class/regime does not match the catalog's own expectation:")
        for feat, found_txt, expected in mismatches:
            print(f"  {feat['num']} {feat['name']}: expected {expected}, found {found_txt}")
    else:
        print("\nAll features match the catalog's own expectation.")


if __name__ == "__main__":
    main()
