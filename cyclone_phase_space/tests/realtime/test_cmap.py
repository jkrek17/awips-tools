"""gfs_cps.load_cmap_rgba against the three shipped .cmap files.

CPS_CoreDiverging.cmap and CPS_Asymmetry.cmap document themselves as 64
entry colormaps with an alpha channel that goes fully transparent
(a=0.0) over their middle 8 entries (indices 28-35) so a value near
zero (the cold/warm-core boundary, or symmetric B) does not paint an
opaque fill over MSLP contours. CPS_HartClass.cmap is documented as a
7 entry *categorical* map (one entry per HCPSclass code, all opaque),
matching HCPSclass having 7 codes (0-6) and gfs_cps.CLASS_NAMES /
compute_products's BoundaryNorm(..., 7) -- it is not one of the 64
entry diverging/sequential maps, so it is checked separately.
"""

from __future__ import annotations

import numpy as np
import pytest

import gfs_cps as g

CORE_ASYM_NAMES = ["CPS_CoreDiverging", "CPS_Asymmetry"]


@pytest.mark.parametrize("name", CORE_ASYM_NAMES)
def test_64_entries_with_alpha(name):
    rgba = g.load_cmap_rgba(g.CMAP_DIR / f"{name}.cmap")
    assert rgba.shape == (64, 4)
    # Not every entry is opaque: the alpha channel is actually populated,
    # not a column of 1.0 defaulted in because the file has no alpha.
    assert rgba[:, 3].min() == 0.0
    assert rgba[:, 3].max() == 1.0
    assert np.unique(rgba[:, 3]).size > 2


@pytest.mark.parametrize("name", CORE_ASYM_NAMES)
def test_middle_entries_transparent(name):
    """Indices 28 through 35 (the middle 8 of 64) are fully transparent, per
    both files' docstrings, with alpha ramping down to that band over the
    6 entries on each side (22-27 ramping 1.0 -> 0.0, 36-41 ramping
    0.0 -> 1.0) rather than a hard on/off edge."""
    rgba = g.load_cmap_rgba(g.CMAP_DIR / f"{name}.cmap")
    assert np.all(rgba[28:36, 3] == 0.0)
    # Inside the ramp (not yet in the fully transparent band, not yet back
    # to fully opaque) alpha is strictly between 0 and 1 on both sides.
    assert 0.0 < rgba[24, 3] < 1.0
    assert 0.0 < rgba[39, 3] < 1.0
    # The ramp reaches the transparent band's edge value (0.0) right next
    # to it on both sides, then holds fully opaque further out.
    assert rgba[27, 3] == 0.0 and rgba[36, 3] == 0.0
    assert rgba[21, 3] == 1.0 and rgba[42, 3] == 1.0
    # The very ends of the map are fully opaque.
    assert rgba[0, 3] == 1.0
    assert rgba[-1, 3] == 1.0


@pytest.mark.parametrize("name", CORE_ASYM_NAMES)
def test_rgb_in_unit_range(name):
    rgba = g.load_cmap_rgba(g.CMAP_DIR / f"{name}.cmap")
    assert np.all(rgba >= 0.0) and np.all(rgba <= 1.0)


def test_hart_class_is_seven_entry_categorical_map():
    """HCPSclass has 7 codes (0-6); the class colormap has one opaque entry
    per code, not the 64 entry diverging/sequential layout of the other
    two, and matches gfs_cps.CLASS_NAMES in length."""
    rgba = g.load_cmap_rgba(g.CMAP_DIR / "CPS_HartClass.cmap")
    assert rgba.shape == (len(g.CLASS_NAMES), 4)
    assert np.all(rgba[:, 3] == 1.0)


def test_make_cmaps_wraps_all_three_with_bad_transparent():
    """make_cmaps() builds a ListedColormap per key and sets "bad" (masked)
    to fully transparent, and the class norm has as many bins as codes."""
    cm = g.make_cmaps()
    for key in ("core", "asym", "cls"):
        assert cm[key].get_bad()[3] == 0.0
    assert cm["core"].N == 64
    assert cm["asym"].N == 64
    assert cm["cls"].N == len(g.CLASS_NAMES)
