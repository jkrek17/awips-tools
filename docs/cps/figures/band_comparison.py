"""Synthetic test of the lower-band choice against Hart's 900 to 600 hPa.

For five storm archetypes, the height perturbation amplitude dZ(p) is
prescribed at 50 hPa spacing from 1000 to 300 hPa. The lower thermal
wind is the least-squares slope of dZ against ln p over three level
sets: Hart's 900 to 600 hPa at 50 hPa spacing (seven levels), the
package's 925/850/700 hPa, and the proposed 925/850/700/500 hPa. The
upper term is fitted over Hart's 600 to 300 and the package's
500/400/300 for reference.

Parameter B scales with the layer-mean thickness gradient across the
storm's motion, so for three baroclinic-zone profiles (temperature
gradient as a function of pressure) the 900-600, 925-700 and 925-500
thickness gradients are integrated, and the rescaled gridded values are
compared with the 900-600 value Hart would compute. Everything is
analytic; run this file to print the tables and write
figA_band_comparison.png next to it.
"""
from __future__ import annotations

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = __import__("pathlib").Path(__file__).resolve().parent

P50 = np.arange(1000, 299, -50)  # 1000, 950, ..., 300
LNP = np.log(P50)

# dZ(p) archetypes (m), given at 1000, 925, 850, 700, 600, 500, 400, 300
# and interpolated in ln p to the 50 hPa levels.
ANCHOR_P = np.array([1000, 925, 850, 700, 600, 500, 400, 300])
ARCHETYPES = {
    "deep warm core (mature typhoon)": [260, 235, 205, 150, 115, 85, 50, 20],
    "warm core, linear in ln p": [250, 233, 214, 172, 138, 98, 50, 20],
    "shallow warm core (seclusion)": [150, 140, 125, 100, 105, 130, 180, 230],
    "transitioning (warm below 850)": [200, 190, 165, 120, 110, 150, 220, 300],
    "deep cold core (extratropical)": [60, 70, 90, 130, 180, 240, 300, 350],
}

BANDS = {
    "Hart 900-600 (50 hPa)": np.arange(900, 599, -50),
    "package 925/850/700": np.array([925, 850, 700]),
    "proposed 925/850/700/500": np.array([925, 850, 700, 500]),
    "alternative 850/700/500": np.array([850, 700, 500]),
}
UPPER = {
    "Hart 600-300 (50 hPa)": np.arange(600, 299, -50),
    "package 500/400/300": np.array([500, 400, 300]),
}


def profile(anchors):
    """dZ on the 50 hPa levels, interpolated linearly in ln p."""
    return np.interp(LNP[::-1], np.log(ANCHOR_P)[::-1], np.asarray(anchors, float)[::-1])[::-1]


def slope(p_levels, dz_on_p50):
    dz = np.interp(np.log(p_levels)[::-1], LNP[::-1], dz_on_p50[::-1])[::-1]
    x = np.log(p_levels)
    return np.polyfit(x, dz, 1)[0]


def lower_terms():
    rows = []
    for name, anchors in ARCHETYPES.items():
        dz = profile(anchors)
        vals = {b: slope(lv, dz) for b, lv in BANDS.items()}
        ups = {b: slope(lv, dz) for b, lv in UPPER.items()}
        rows.append((name, vals, ups))
    return rows


# Baroclinic-zone profiles: dT/dy (K per 100 km) as a function of p.
# Thickness gradient of a layer = (R/g) * integral of (dT/dy) d(ln p),
# taken positive; B is proportional to it, so only ratios matter here.
R_OVER_G = 287.05 / 9.80665
BAROCLINIC = {
    "uniform with height": lambda p: np.full_like(p, 3.0, dtype=float),
    "surface based, decaying upward": lambda p: 3.0 * np.clip((p - 400.0) / 600.0, 0, None) ** 2,
    "mid level maximum (700 hPa)": lambda p: 3.0 * np.exp(-((np.log(p) - np.log(700.0)) / 0.25) ** 2),
}
LAYERS = {
    "Hart 900-600": (900.0, 600.0, 1.0),
    "package 925-700, lambda 1.455": (925.0, 700.0, np.log(900 / 600) / np.log(925 / 700)),
    "proposed 925-500, lambda 0.659": (925.0, 500.0, np.log(900 / 600) / np.log(925 / 500)),
    "alternative 850-500, lambda 0.767": (850.0, 500.0, np.log(900 / 600) / np.log(850 / 500)),
}


def thickness_gradient(fn, p_bot, p_top):
    p = np.linspace(p_top, p_bot, 601)
    lnp = np.log(p)
    return R_OVER_G * np.trapezoid(fn(p) * 1e-5, lnp) * 1e6  # K per 100 km -> K per m; m per m -> m per 1000 km


def b_terms():
    rows = []
    for name, fn in BAROCLINIC.items():
        vals = {L: thickness_gradient(fn, pb, pt) * lam for L, (pb, pt, lam) in LAYERS.items()}
        rows.append((name, vals))
    return rows


def main():
    lt = lower_terms()
    print("Lower thermal wind, -V_T^L (m), by archetype and band:")
    print(f"{'archetype':38s}" + "".join(f"{b:>27s}" for b in BANDS))
    for name, vals, _ in lt:
        print(f"{name:38s}" + "".join(f"{vals[b]:27.1f}" for b in BANDS))
    print("\nUpper thermal wind, -V_T^U (m):")
    print(f"{'archetype':38s}" + "".join(f"{b:>28s}" for b in UPPER))
    for name, _, ups in lt:
        print(f"{name:38s}" + "".join(f"{ups[b]:28.1f}" for b in UPPER))
    bt = b_terms()
    print("\nParameter B proxy (rescaled layer thickness gradient, m per 1000 km; Hart layer = truth):")
    print(f"{'baroclinic profile':38s}" + "".join(f"{L:>30s}" for L in LAYERS))
    for name, vals in bt:
        print(f"{name:38s}" + "".join(f"{vals[L]:30.1f}" for L in LAYERS))

    # ---- figure ----
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.2))
    ax = axes[0]
    colors = ["#c0392b", "#e67e22", "#8e44ad", "#27ae60", "#2980b9"]
    for (name, anchors), c in zip(ARCHETYPES.items(), colors):
        ax.plot(profile(anchors), P50, "-o", ms=3, color=c, label=name)
    ax.set_yscale("log")
    ax.set_ylim(1000, 300)
    ax.set_yticks([1000, 925, 850, 700, 600, 500, 400, 300])
    ax.set_yticklabels([1000, 925, 850, 700, 600, 500, 400, 300])
    ax.axhspan(900, 600, color="0.85", alpha=0.6, label="Hart lower band")
    ax.set_xlabel("dZ (m)")
    ax.set_ylabel("pressure (hPa)")
    ax.set_title("(a) height perturbation profiles", loc="left", fontsize=10)
    ax.legend(fontsize=6.5, loc="lower right")

    ax = axes[1]
    names = [r[0] for r in lt]
    x = np.arange(len(names))
    w = 0.2
    for k, (b, hatch) in enumerate(zip(BANDS, ["", "//", "..", "xx"])):
        ax.bar(x + (k - 1.5) * w, [r[1][b] for r in lt], w, label=b, hatch=hatch,
               color=["0.35", "#e34948", "#2a78d6", "#27ae60"][k], edgecolor="white")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(["deep warm", "linear warm", "seclusion", "transitioning", "deep cold"], fontsize=8, rotation=20)
    ax.set_ylabel("$-V_T^L$ (m)")
    ax.set_title("(b) lower term by band", loc="left", fontsize=10)
    ax.legend(fontsize=7)

    ax = axes[2]
    names = [r[0] for r in bt]
    x = np.arange(len(names))
    for k, (L, hatch) in enumerate(zip(LAYERS, ["", "//", "..", "xx"])):
        ax.bar(x + (k - 1.5) * w, [r[1][L] for r in bt], w, label=L, hatch=hatch,
               color=["0.35", "#e34948", "#2a78d6", "#27ae60"][k], edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(["uniform", "surface based", "mid-level max"], fontsize=8)
    ax.set_ylabel("rescaled thickness gradient (m per 1000 km)")
    ax.set_title("(c) B proxy by layer", loc="left", fontsize=10)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(HERE / "figA_band_comparison.png", dpi=300)
    print("\nwrote", HERE / "figA_band_comparison.png")


if __name__ == "__main__":
    main()
