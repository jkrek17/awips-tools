"""The confirmed result, in the space the question was originally posed in.

Panel (a) is the plot the plan called decisive: depth against scale, with
hurricane-force tracks marked. The prediction was that if wind follows
depth/scale the boundary is a RAY THROUGH THE ORIGIN, and if it follows
depth alone the boundary is HORIZONTAL. Both are drawn, each at the
threshold that best separates the confirmation seasons, so the comparison is
by eye and not by assertion.

Panel (b) is why the ray wins: ERA5's own maximum gust against the gradient
the ray is a contour of.

Confirmation seasons only -- 2021, 2023, 2025 -- because the exploration
seasons are what the thresholds were chosen on.
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

from analyze_tracks import load, CONFIRM  # noqa: E402
import diagram_style as ds  # noqa: E402

HF_C, NO_C = "#e34948", "#2a78d6"
GRAD_THR = 7.0
DEPTH_THR = 30.0
OUT = HERE / "data" / "confirmed.png"


def main():
    rows = [r for r in load() if r["season"] in CONFIRM]
    ok = [r for r in rows if np.isfinite(r["peak_depth"])
          and np.isfinite(r["peak_scale_km"]) and np.isfinite(r["max_gust_kt"])]
    hf = [r for r in ok if r["hf"] == 1]
    no = [r for r in ok if r["hf"] == 0]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.7), dpi=120)
    fig.patch.set_facecolor("white")

    for grp, c, name, m in ((no, NO_C, "no hurricane force", "o"),
                            (hf, HF_C, "hurricane force", "^")):
        ax1.scatter([g["peak_scale_km"] for g in grp],
                    [g["peak_depth"] for g in grp],
                    s=20, c=c, marker=m, alpha=0.6, linewidths=0, label=name)
    x = np.array([150.0, 1200.0])
    ax1.plot(x, GRAD_THR * x / 100.0, color=ds.TEXT_DARK, lw=1.8,
             label=f"ray: gradient = {GRAD_THR:.0f} hPa/100 km")
    ax1.axhline(DEPTH_THR, color=ds.TEXT_SECONDARY, lw=1.6, ls=(0, (5, 3)),
                label=f"flat: depth = {DEPTH_THR:.0f} hPa")
    ax1.set_xlim(150, 1100)
    ax1.set_ylim(0, 75)
    ax1.set_xlabel("scale L at the track's deepest moment  (km)",
                   fontsize=9, color=ds.TEXT_SECONDARY)
    ax1.set_ylabel("depth  $\\Delta P$  (hPa)", fontsize=9, color=ds.TEXT_SECONDARY)
    ax1.set_title("(a) ray or flat? the ray wins on false alarms",
                  fontsize=9.5, color=ds.TEXT_DARK)
    ax1.legend(fontsize=7, frameon=False, loc="upper left")

    for grp, c, name, m in ((no, NO_C, "no hurricane force", "o"),
                            (hf, HF_C, "hurricane force", "^")):
        ax2.scatter([g["peak_grad"] for g in grp], [g["max_gust_kt"] for g in grp],
                    s=20, c=c, marker=m, alpha=0.6, linewidths=0, label=name)
    g = np.array([r["peak_grad"] for r in ok])
    y = np.array([r["max_gust_kt"] for r in ok])
    b = np.polyfit(g, y, 1)
    xs = np.linspace(g.min(), g.max(), 50)
    r2 = 1 - ((y - np.polyval(b, g)) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    ax2.plot(xs, np.polyval(b, xs), color=ds.TEXT_DARK, lw=1.8,
             label=f"{b[0]:+.2f} kt per hPa/100 km   $R^2$ = {r2:.2f}")
    ax2.axhline(64.0, color=ds.TEXT_SECONDARY, lw=1.0, ls=(0, (4, 3)))
    ax2.annotate("64 kt", xy=(g.max(), 64), fontsize=7, color=ds.TEXT_SECONDARY,
                 ha="right", va="bottom")
    ax2.axvline(GRAD_THR, color=ds.TEXT_DARK, lw=1.0, ls=(0, (2, 2)))
    ax2.set_xlabel("pressure gradient at the peak  (hPa / 100 km)",
                   fontsize=9, color=ds.TEXT_SECONDARY)
    ax2.set_ylabel("ERA5 maximum gust near the low  (kt)",
                   fontsize=9, color=ds.TEXT_SECONDARY)
    ax2.set_title("(b) why: the gradient is what the wind follows",
                  fontsize=9.5, color=ds.TEXT_DARK)
    ax2.legend(fontsize=7, frameon=False, loc="lower right")

    for ax in (ax1, ax2):
        ax.tick_params(labelsize=7.5, colors=ds.TEXT_SECONDARY)
        ax.grid(True, color=ds.GRID_COLOR, lw=0.6, zorder=0)
        for sp in ax.spines.values():
            sp.set_color(ds.GRID_COLOR)

    fig.suptitle("North Pacific, held-out seasons 2021, 2023, 2025 — "
                 f"{len(hf)} hurricane-force tracks, {len(no)} others, "
                 "all detected and measured by the same code",
                 fontsize=9.5, color=ds.TEXT_DARK, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT, facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
