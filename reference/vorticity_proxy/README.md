# Retired: vorticity-proxy CPS family

This folder holds the first version of the D2D cyclone phase space
package, retired on 2026-09-18 in favor of the height-based Hart family
in `D2D/` (HVTL, HVTU, HB, HCPSidx, HCPSclass). It is kept for reference
only and is not part of the install set.

Why it was retired: the proxy estimated core structure from the vertical
difference of smoothed relative vorticity (850 minus 600 hPa, 600 minus
300 hPa). That is not Hart's quantity, its sign depends on the grid's
axis orientation, it reads Southern Hemisphere warm cores with the wrong
sign, and on tilted extratropical lows it paints a cold ring where the
upper trough sits rather than reading the core (Figure 4 of the article
in `docs/cps/`). The Hart family measures Hart's actual thermal wind
from geopotential height and has none of these problems.

Contents:

- `CycloneCore.py`: the derived-parameter module (entry points `execute`,
  `executeVorticity`, `executeClass`, `executeIndex`).
- `definitions/`: VTL, VTU, CPScat, CPSidx, cpsZ850.
- `colormaps/CPS_CoreClass.cmap`: the five-color map for CPScat.
- `menus/` and `styleRules/`: the last menu and style-rule files that
  still carried the vorticity entries, before they were trimmed.
- Tests: `tests/reference_vorticity/`.

`docs/cps/figures/make_figures.py` still imports `CycloneCore` from here
to draw Figure 4, the tilt-bias comparison that motivated the
retirement. Do not delete this folder without also freezing that figure.

To reinstall it (not recommended), copy `CycloneCore.py` to the site
`derivedParameters/functions/` directory, the five XMLs to
`derivedParameters/definitions/`, the colormap to `colormaps/Grid/`, and
merge the menu items and style rules back into the live files.
