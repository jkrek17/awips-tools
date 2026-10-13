"""The page's grid: the 0.25 degree North Atlantic box the method was tested on
(30-67N, 75W-0), cut from the global 0.25 degree grids (lat 90..-90, lon 0..359.75)."""
import numpy as np

NORTH, SOUTH, WEST, EAST = 67.0, 30.0, -75.0, -0.25
IY = slice(int((90 - NORTH) * 4), int((90 - SOUTH) * 4) + 1)   # 149 rows, north first
IX = slice(int((360 + WEST) * 4), int((360 + EAST) * 4) + 1)  # 300 columns, west first
LATS = np.linspace(NORTH, SOUTH, IY.stop - IY.start)
LONS = np.linspace(WEST, EAST, IX.stop - IX.start)
NY, NX = len(LATS), len(LONS)
