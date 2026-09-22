"""How far ahead each predictor still works, and what actually adds value.

Panel (a): out-of-sample R2 against forecast horizon, for the predictors
worth naming. Fitted on the exploration seasons, scored on the confirmation
seasons, at every horizon.

Panel (b): what each variable adds ON TOP of persistence, which is the only
comparison that decides whether a new field is worth building. The gradient
explains the wind blowing now, so once that wind is in hand it has nothing
left to say; the tendency does, because it is the one thing the current
wind cannot tell you -- which way it is going.

The horizons past about 48 h flatten because the storms are over: median
track lifetime is 30 h and only 3% reach 96 h, so a longer window stops
adding future to look at.
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

from leadtime import (load_tracks, sample_forward, fit_score,  # noqa: E402
                      EXPLORE, CONFIRM)
import diagram_style as ds  # noqa: E402

WINDOWS = (12, 24, 48, 72, 96)
OUT = HERE / "data" / "leadtime.png"

MODELS = [
    ("persistence + 24 h deepening", ["gust_now", "deep24"], "#e34948", "-", "o"),
    ("persistence (gust now)", ["gust_now"], "#0b0b0b", "-", "s"),
    ("24 h deepening alone", ["deep24"], "#eb6834", "--", "^"),
    ("gradient wind Vg", ["vg_kt"], "#2a78d6", "--", "v"),
    ("gradient = depth/scale", ["gradient"], "#4a3aa7", ":", "D"),
]
ADDED = [
    ("24 h deepening", ["deep24"], "#e34948"),
    ("12 h deepening", ["deep12"], "#eb6834"),
    ("latitude", ["lat"], "#c3c2b7"),
    ("depth + scale", ["depth", "scale_km"], "#2a78d6"),
    ("gradient", ["gradient"], "#4a3aa7"),
]


def main():
    by = load_tracks()
    curves = {name: [] for name, *_ in MODELS}
    gains = {name: [] for name, *_ in ADDED}
    for w in WINDOWS:
        rows = sample_forward(by, w)
        tr = [r for r in rows if r["season"] in EXPLORE]
        te = [r for r in rows if r["season"] in CONFIRM]
        base, _, _ = fit_score(tr, te, ["gust_now"])
        for name, feats, *_ in MODELS:
            curves[name].append(fit_score(tr, te, feats)[0])
        for name, feats, _ in ADDED:
            gains[name].append(fit_score(tr, te, ["gust_now"] + feats)[0] - base)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.6), dpi=120)
    fig.patch.set_facecolor("white")

    for name, feats, c, ls, mk in MODELS:
        ax1.plot(WINDOWS, curves[name], color=c, ls=ls, marker=mk, ms=5,
                 lw=1.8, label=name)
    ax1.set_xlabel("forecast horizon  (h)", fontsize=9, color=ds.TEXT_SECONDARY)
    ax1.set_ylabel("out-of-sample $R^2$ for max gust ahead",
                   fontsize=9, color=ds.TEXT_SECONDARY)
    ax1.set_title("(a) how far ahead each predictor works",
                  fontsize=9.5, color=ds.TEXT_DARK)
    ax1.set_ylim(0, 0.85)
    ax1.legend(fontsize=7.5, frameon=False, loc="upper right")

    for name, feats, c in ADDED:
        ax2.plot(WINDOWS, gains[name], color=c, marker="o", ms=5, lw=1.8,
                 label=name)
    ax2.axhline(0.0, color=ds.TEXT_DARK, lw=1.0)
    ax2.set_xlabel("forecast horizon  (h)", fontsize=9, color=ds.TEXT_SECONDARY)
    ax2.set_ylabel("gain in $R^2$ when added to persistence",
                   fontsize=9, color=ds.TEXT_SECONDARY)
    ax2.set_title("(b) what actually adds to knowing the wind now",
                  fontsize=9.5, color=ds.TEXT_DARK)
    ax2.legend(fontsize=7.5, frameon=False, loc="center right")

    for ax in (ax1, ax2):
        ax.set_xticks(WINDOWS)
        ax.tick_params(labelsize=7.5, colors=ds.TEXT_SECONDARY)
        ax.grid(True, color=ds.GRID_COLOR, lw=0.6, zorder=0)
        for sp in ax.spines.values():
            sp.set_color(ds.GRID_COLOR)

    fig.suptitle("North Pacific 2020-2025 — fitted on 2020/2022/2024, "
                 "scored on 2021/2023/2025, 678 held-out tracks",
                 fontsize=9.5, color=ds.TEXT_DARK, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT, facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
