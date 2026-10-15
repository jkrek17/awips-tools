"""The page's grids, cut from the global 0.25 degree grids (lat 90..-90, lon 0..359.75).

    glob  the whole globe, 90N-90S, 180W-179.75E (what the page shows)
    natl  North Atlantic 18-67N, 95W-10E   (the OPC Atlantic surface chart area)
    npac  North Pacific  18-67N, 135E-115W (the OPC Pacific surface chart area)

The two OPC boxes are also cut from the global build (build.py --boxes) for anything
still reading the older per-basin files.

The blend was tuned and tested on 30-67N, 75W-0 and 30-67N, 160E-115W; the rest of
each box (the subtropics, Gulf of Mexico, Caribbean, NW Europe, Sea of Japan) uses the
same recipe untested.

The basin comes from the MARINE_DOMAIN environment variable (build.py --domain sets
it before anything imports this module). Longitudes are kept continuous: the Atlantic
box runs -95 to 10 across the prime meridian and the Pacific box 135 to 245 (= 115W)
across the date line; IX wraps round the global grid."""
import os

import numpy as np

BASINS = {
    "glob": dict(name="Global", north=90.0, south=-90.0, west=-180.0, east=179.75),
    "natl": dict(name="North Atlantic", north=67.0, south=18.0, west=-95.0, east=10.0),
    "npac": dict(name="North Pacific", north=67.0, south=18.0, west=135.0, east=245.0),
}
KEY = os.environ.get("MARINE_DOMAIN", "natl")
BASIN = BASINS[KEY]
NORTH, SOUTH, WEST, EAST = BASIN["north"], BASIN["south"], BASIN["west"], BASIN["east"]
IY = slice(int((90 - NORTH) * 4), int((90 - SOUTH) * 4) + 1)          # north first
IX = (int(round((WEST % 360) * 4)) + np.arange(int(round((EAST - WEST) * 4)) + 1)) % 1440  # west first
LATS = np.linspace(NORTH, SOUTH, IY.stop - IY.start)
LONS = np.linspace(WEST, EAST, len(IX))
NY, NX = len(LATS), len(LONS)
GLOBAL = KEY == "glob"
# where the blend was tuned and verified (30-67N in each basin); everywhere else is untested
TESTED = [dict(name="North Atlantic", north=67.0, south=30.0, west=-75.0, east=0.0),
          dict(name="North Pacific", north=67.0, south=30.0, west=160.0, east=245.0)]
