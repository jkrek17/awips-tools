"""storm.drop_small: gale warning pieces under WARN_GALE_MIN cells are dropped, joined across the date line."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

import storm  # noqa: E402


def test_drop_small():
    m = np.zeros((20, 40), bool)
    m[2:4, 2:4] = True          # 4 cells: dropped
    m[10:16, 10:16] = True      # 36 cells: kept
    m[5, 30] = m[6, 31] = True  # diagonal pair, one 8-connected piece of 2
    out = storm.drop_small(m, 32)
    assert out[10:16, 10:16].all() and out.sum() == 36
    assert storm.drop_small(m, 2)[5, 30] and storm.drop_small(m, 2)[6, 31]


def test_wrap_joins_seam():
    m = np.zeros((20, 40), bool)
    m[5:9, 36:40] = True        # 16 cells at the east edge
    m[6:10, 0:4] = True         # 16 cells at the west edge, touching across the seam
    try:
        storm.WRAP = False
        assert not storm.drop_small(m, 32).any()
        storm.WRAP = True
        assert storm.drop_small(m, 32).sum() == 32
    finally:
        storm.WRAP = False


def test_warning_areas_gale_only():
    speeds = np.zeros((3, 20, 40), np.float32)
    speeds[0, 2:4, 2:4] = 35     # small gale speck
    speeds[1, 10:16, 10:16] = 35  # gale area
    windcore = np.zeros((20, 40), np.float32)
    windcore[2, 2] = 40          # one storm cell: storm bit is not filtered
    w = storm.warning_areas(speeds, windcore, np.zeros((2, 20, 40), np.float32))
    assert (w & 1).sum() == 36 and not (w[2:4, 2:4] & 1).any() and w[2, 2] & 2


if __name__ == "__main__":
    test_drop_small()
    test_wrap_joins_seam()
    test_warning_areas_gale_only()
    print("ok")
