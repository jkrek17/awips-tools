"""The exploration result in two panels.

(a) depth against scale, cases and controls. The compactness hypothesis
    predicted a boundary here -- a ray through the origin if the wind
    follows depth/scale, a horizontal line if it follows depth alone.
(b) the 12 h pressure tendency each low was carrying when it was observed.

Exploration seasons only. The confirmation seasons are not plotted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cyclone_phase_space" / "article" / "figures"))

from analyze import load, strata, EXPLORE_SEASONS  # noqa: E402
import diagram_style as ds  # noqa: E402

CASE_C, CTRL_C = "#e34948", "#2a78d6"
OUT = HERE / "data" / "exploration.png"


def main():
    sets = strata(load(), EXPLORE_SEASONS)
    cases = [c for c, _ in sets]
    ctrls = [m for _, cs in sets for m in cs]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.5), dpi=120)
    fig.patch.set_facecolor("white")

    for grp, color, name, mark in ((ctrls, CTRL_C, "no hurricane force", "o"),
                                   (cases, CASE_C, "hurricane force in 24 h", "^")):
        ax1.scatter([g["scale_km"] for g in grp], [g["depth"] for g in grp],
                    s=26, c=color, marker=mark, alpha=0.65, linewidths=0, label=name)
    for g in (4.0, 6.0, 8.0):   # rays of constant depth/scale
        x = np.array([150.0, 1000.0])
        ax1.plot(x, g * x / 100.0, color=ds.TEXT_SECONDARY, lw=0.8,
                 ls=(0, (4, 3)), zorder=0)
        ax1.annotate(f"{g:.0f} hPa/100 km", xy=(980, g * 9.8), fontsize=6.2,
                     color=ds.TEXT_SECONDARY, ha="right", va="bottom", rotation=0)
    ax1.set_xlabel("scale L  (km)", fontsize=9, color=ds.TEXT_SECONDARY)
    ax1.set_ylabel("depth  $\\Delta P$  (hPa)", fontsize=9, color=ds.TEXT_SECONDARY)
    ax1.set_title("(a) the space the hypothesis predicted a boundary in",
                  fontsize=9.5, color=ds.TEXT_DARK)
    ax1.legend(fontsize=7.5, frameon=False, loc="upper left")

    bins = np.arange(-30, 16, 3.0)
    for grp, color, name in ((ctrls, CTRL_C, "no hurricane force"),
                             (cases, CASE_C, "hurricane force in 24 h")):
        v = np.array([g["tend12"] for g in grp])
        v = v[np.isfinite(v)]
        ax2.hist(v, bins=bins, density=True, color=color, alpha=0.55,
                 label=f"{name}  (median {np.median(v):+.1f})")
        ax2.axvline(np.median(v), color=color, lw=1.6)
    ax2.axvline(0.0, color=ds.TEXT_DARK, lw=0.9)
    ax2.set_xlabel("12 h pressure tendency  (hPa)   ← deepening",
                   fontsize=9, color=ds.TEXT_SECONDARY)
    ax2.set_ylabel("density", fontsize=9, color=ds.TEXT_SECONDARY)
    ax2.set_title("(b) the variable that actually separates them",
                  fontsize=9.5, color=ds.TEXT_DARK)
    ax2.legend(fontsize=7.5, frameon=False, loc="upper left")

    for ax in (ax1, ax2):
        ax.tick_params(labelsize=7.5, colors=ds.TEXT_SECONDARY)
        ax.grid(True, color=ds.GRID_COLOR, lw=0.6, zorder=0)
        for sp in ax.spines.values():
            sp.set_color(ds.GRID_COLOR)

    fig.suptitle("North Pacific 2020-2025, matched on depth, latitude, month and season "
                 f"— {len(cases)} cases, {len(ctrls)} controls, exploration seasons only",
                 fontsize=9.5, color=ds.TEXT_DARK, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT, facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
