"""The page's grids, cut from the global 0.25 degree grids (lat 90..-90, lon 0..359.75).

    natl  North Atlantic 30-67N, 75W-0    (the box the blend was tuned on)
    npac  North Pacific  30-67N, 160E-115W (tested on the same 733 hindcast cases)

The basin comes from the MARINE_DOMAIN environment variable (build.py --domain sets
it before anything imports this module). Longitudes are kept continuous across the
date line: the Pacific box runs 160 to 245 (= 115W)."""
import os

import numpy as np

BASINS = {
    "natl": dict(name="North Atlantic", north=67.0, south=30.0, west=-75.0, east=-0.25),
    "npac": dict(name="North Pacific", north=67.0, south=30.0, west=160.0, east=245.0),
}
KEY = os.environ.get("MARINE_DOMAIN", "natl")
BASIN = BASINS[KEY]
NORTH, SOUTH, WEST, EAST = BASIN["north"], BASIN["south"], BASIN["west"], BASIN["east"]
IY = slice(int((90 - NORTH) * 4), int((90 - SOUTH) * 4) + 1)          # north first
IX = slice(int((WEST % 360) * 4), int((WEST % 360) * 4) + int(round((EAST - WEST) * 4)) + 1)  # west first
LATS = np.linspace(NORTH, SOUTH, IY.stop - IY.start)
LONS = np.linspace(WEST, EAST, IX.stop - IX.start)
NY, NX = len(LATS), len(LONS)
