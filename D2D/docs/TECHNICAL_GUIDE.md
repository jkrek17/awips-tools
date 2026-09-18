# Cyclone Phase Space in D2D: Technical Guide

For whoever installs, tunes, maintains, or ports this package. The
forecaster-facing material is in `USER_GUIDE.md`; the install checklist
and validation log are in `../README.md`. This document explains how
the products are computed, how they are wired into AWIPS, where every
tunable lives, and what the known limitations are.

---

## 1. Overview

The package provides gridded cyclone phase space diagnostics as AWIPS II
D2D derived parameters. Everything runs inside CAVE's embedded Python
on demand, per frame, from grids already in the D2D inventory. There is
no server, no cron, no tracker, no external data.

Two independent families share the same delivery mechanism:

| Family | Function file | Products | Inputs | Status |
| :--- | :--- | :--- | :--- | :--- |
| Hart | `derivedParameters/functions/HartCPS.py` | HVTL, HVTU, HCPScat, HCPSidx, HB, HETstage | geopotential height at 1000, 925, 850, 700, 500, 400, 300 hPa; u/v wind at 850, 700, 500, 300 hPa; surface pressure; coriolis (HB/HETstage only) | primary, validated (HB/HETstage new, awaiting validation) |
| Vorticity | `derivedParameters/functions/CycloneCore.py` | VTL, VTU, CPScat, CPSidx, cpsZ850 | u and v wind at 850, 600, 300 hPa | secondary, warm bias |

Both function files are self-contained numpy with no imports from the
rest of the repository, because the CAVE interpreter only sees the
functions directory. Both can be run standalone for a sanity check:

```
python3 D2D/derivedParameters/functions/HartCPS.py
python3 D2D/derivedParameters/functions/CycloneCore.py
```

Package layout:

```
D2D/
  derivedParameters/functions/    HartCPS.py, CycloneCore.py
  derivedParameters/definitions/  one XML per product
  colormaps/Grid/                 CPS_CoreDiverging.cmap, CPS_CoreClass.cmap, CPS_ETStage.cmap
  styleRules/cpsStyleRules.xml    base-schema style rules (see 6.3)
  menus/volumebrowser/cpsFields.xml  Volume Browser entries (see 6.4)
  docs/                           this guide, the user guide
  README.md                       install, troubleshooting, validation log
tests/d2d_cps/                    pytest suite for both families
cps/hart.py                       storm-centered reference implementation
```

---

## 2. Hart family method

### 2.1 Hart's quantities

Hart (2003) defines the cyclone thermal wind from the height
perturbation amplitude inside a 500 km radius of the storm center. At
each pressure level p:

    dZ(p) = max(Z) - min(Z)    over the 500 km circle

Then -VT for a layer is the least-squares slope of dZ against ln p over
the levels in that layer. A warm core has a height perturbation that
weakens upward, so dZ falls as p falls, the slope of dZ against ln p is
positive, and -VT is positive. A cold core gives negative. Zero is the
boundary. Units are meters per unit ln p, and the sign is independent
of hemisphere because dZ is positive definite.

### 2.2 Gridded form

The point definition is evaluated at every grid point by replacing "the
500 km circle around the storm" with "a window of half-width 500 km
around this point". The window is a square, not a circle, because a
square sliding max and min is separable and runs in a handful of passes
per level (section 4). Corners reach 707 km. For an isolated compact vortex the
max and min are the far field and the center either way, so the
difference from a circle is small; the test suite checks agreement with
the circular point implementation in `cps/hart.py` to within 2 percent
on an isolated synthetic vortex. On a background height gradient the
square sees up to 41 percent more of the gradient's contribution to
dZ than the circle does, and because that contribution grows with
height in a baroclinic environment, the square window carries a small
cold bias relative to Hart's circle. This is the main methodological
difference from Hart. It is a documented, permanent design decision,
not an open question awaiting a fix; see section 8 for the reasoning.

A consequence worth knowing: around a compact low, every point whose
window contains the low center sees roughly the same dZ, so the raw
HVTL and HVTU images paint a plateau the size of the window, a 1000 km
square. This is cosmetic. The class and index products are masked to a
blob around the center and do not show it.

### 2.3 Level bands

Hart uses 900 to 600 hPa and 600 to 300 hPa at 50 hPa spacing, which
only the GFS carries in D2D. The package uses standard levels so the
products exist for every model:

| Band | Levels | Constant |
| :--- | :--- | :--- |
| lower | 925, 850, 700 | `LOWER_BAND` |
| upper | 500, 400, 300 | `UPPER_BAND` |

The 700 to 500 layer is deliberately in neither band. Magnitudes are
therefore near but not equal to the FSU page's values for the same
storm; signs, the zero threshold, and transition timing carry over, and
the Dujuan case confirmed the timing matches. A GFS-only definition on
Hart's exact levels can be added with `executeBand7` (section 5.4).

### 2.4 Below-ground masking

Each height level is compared against surface pressure before any
window filter. A grid point is set to missing for level p where

    psfc < min(p, capHpa)        capHpa = 900 by default

The sliding max, min, and box sums are NaN-aware, so the window simply
ignores those points. Output at a below-ground point is missing, which
is why Greenland and the Rockies are blank. The cap keeps a deep low
over open water, where the surface pressure is below 1000 or 925 but
the extrapolated height is fine, from being treated as terrain.
Surface pressure arrives in Pa from AWIPS; the code detects Pa versus
hPa from the finite median and converts.

### 2.5 Closed-low mask

The class and index products are shown only near closed lows. The mask
is built from 1000 hPa height, which is nearly linear in MSLP at about
8 m per hPa, so a detected low is the one on the MSLP contours. A point
is a low center when both hold:

1. Candidate: it is within `center_tol_m` (5 m) of the minimum of its
   own 300 km neighborhood (`MIN_RADIUS_KM`).
2. Depth: the mean height over the annulus from 300 to 500 km out
   exceeds the point's height by at least `depthM` (40 m, about 5 hPa).

A uniform gradient fails the depth test because the annulus mean equals
the point's own value on a slope. Detected centers are dilated by
`blobKm` (200 km) for display. The annulus mean is computed from two
NaN-aware box sums.

### 2.6 Class and index

With band = `neutralM` (25 m):

| Condition | Code |
| :--- | :--- |
| VTL > band and VTU > band | 4 deep warm core |
| VTL > band and VTU <= band | 3 shallow warm core |
| abs(VTL) <= band and VTU < -band | 1 cold core |
| abs(VTL) <= band and VTU >= -band | 2 neutral |
| VTL < -band and VTU > band | 0 mid-level vortex |
| VTL < -band and VTU <= band | 1 cold core |

Index = 2 tanh(VTL / scaleM) + tanh(VTU / scaleM), scaleM = 100 m.
Both are NaN outside the closed-low mask.

### 2.7 Parameter B and ET stage

Hart's third number, B, is the right-minus-left half-window mean of
925-700 hPa thickness across the storm's motion, over the same 500 km
window. A single grid point has no half-disk of its own, so the
gridded version uses a linear-gradient approximation: for a smoothly
varying thickness field, that right-minus-left difference equals
`(8*radiusKm/(3*pi))` times the window-mean thickness gradient,
projected onto the right-hand normal of the storm's motion. This is
exact for a linear field and only first-order for a genuinely
nonlinear one (a warm-seclusion tongue folding into one side of the
circle is the case that loses the most).

Motion has no tracked storm to read either, so it comes from the
steering flow, the mean wind at 850, 700, 500, and 300 hPa. A point
whose steering speed is below `MIN_STEERING_MS` (1 m/s) has no well
defined right/left of motion and is blanked. The thickness layer is
925-700 hPa (matching `LOWER_BAND`), not Hart's 900-600 hPa, so B is
multiplied by `layerScale = ln(900/600)/ln(925/700)` (about 1.4553) to
read as a 900-600 hPa equivalent against Hart's 10 m threshold;
`layerScale=1.0` gives the raw 925-700 hPa value instead. The
hemisphere factor is the sign of the coriolis pseudo-field (positive
north, negative south, zero treated as positive), matching
`cps.hart.parameter_b`'s own `hemisphere_sign`.

Unlike every other function in this file, computing B's thickness
gradient (`gradient_2d`) takes a spatial derivative, so it is subject
to the same grid-orientation ambiguity `CycloneCore.relative_vorticity`
has. `HartCPS.py` therefore carries its own `ORIENTATION_MODE` (0 to 3,
same semantics as `CycloneCore.py`'s, default 1, confirmed on the OPC
build) -- used only by `gradient_2d`; `HVTL`/`HVTU`/`HCPScat`/`HCPSidx`
never call it and are unaffected.

ET stage (`HETstage`) combines B and VTL: 0 pre-onset, 1 onset (B above
`bThresholdM`, default 10 m), 2 complete (VTL strictly negative, no
neutral band), NaN outside the closed-low mask. It has no memory of an
earlier frame, so a warm seclusion (a re-formed low-level warm core
after transition) reads back down to 0 or 1 rather than staying at 2 --
read that alongside `HCPScat` at the same point and time.

---

## 3. Vorticity family method

Kept for comparison. The local analogue of the thermal wind is the
vertical change of relative vorticity:

    VTL = smooth(zeta_850 - zeta_600)
    VTU = smooth(zeta_600 - zeta_300)

with zeta = dv/dx - du/dy from centered differences and a 100 km box
smoother. Positive is warm core. Values cross the AWIPS boundary scaled
by `UNIT_SCALE` = 1e5, so a readout of 12 means 1.2e-4 per second, and
the XML thresholds are in the same units.

Known biases, which are why the Hart family exists:

- Tilt reads as warm. The upper trough of a baroclinic low sits west of
  the surface center, so the upper difference is positive at the center
  and the cold signal lands in a ring to the west.
- Broad upper features have small vorticity for their height
  perturbation, so upper cold cores are understated.
- The vortex mask selects points where 850 hPa vorticity is high, which
  favors positive lower differences.

Grid orientation matters because derivatives are taken. `ORIENTATION_MODE`
(0 to 3) covers row direction and transposed axes. Mode 1 is confirmed
on the OPC build. The cpsZ850 debug definition takes the mode from its
last ConstantField so a new site can find its mode without editing
Python. `HartCPS.py` now carries its own `ORIENTATION_MODE` as well
(section 2.7) -- same 0-to-3 semantics, used only by `HB`/`HETstage`'s
thickness-gradient step; the two `ORIENTATION_MODE` constants are
independent module-level values, so setting one does not affect the
other.

Southern Hemisphere: cyclonic vorticity is negative there, so warm cores
read negative and the vortex mask blanks them. Not fixed; the Hart
family has no such issue.

---

## 4. Implementation notes

### 4.1 Sliding extrema

`running_extreme_1d` computes a sliding max or min over a window of
length 2w+1 along one axis in O(N log w): pad with sentinels, build
power-of-two window extrema by repeated combination, then cover the
window with two overlapping power-of-two blocks. `np.fmax` and `np.fmin`
ignore NaN, and all-sentinel results are converted back to NaN so edges
shrink rather than wrap.

`window_extreme_2d` runs the x pass with a per-row half-width, because
500 km is more grid cells at high latitude on a lat/lon grid, then the
y pass with one half-width. Rows are grouped by half-width and each
group processed at once. On projected grids dx varies in two
dimensions; the per-row nanmean is used, which is an approximation.

`window_sum_2d` does the same for NaN-aware sums and counts using
cumulative sums, for the annulus mean.

### 4.2 Performance

Measured on a 721 by 1440 grid (0.25 degree global) in the test suite:

| Call | Time |
| :--- | :--- |
| `thermal_wind_grid`, three levels | about 0.8 s |
| `executeClassStd`, six levels plus mask | about 1.3 s |
| `executeETStage`, four levels, B, and mask | about 1.4 s |

CAVE computes per frame on load, so a 41-frame loop costs under a
minute on first display and is cached after. A regional grid is faster.

### 4.3 Missing data

Anything non-finite or below `MISSING_THRESHOLD` (-99990) is treated as
missing on input. Missing propagates to NaN on output at that point only.

---

## 5. Derived parameter wiring

### 5.1 How a definition maps to a function

Each XML under `definitions/` names a Python entry point as
`Module.function` and lists inputs. AWIPS passes the Field and
ConstantField elements to the function as positional arguments in file
order. **The order in the XML must match the function signature
exactly.** The `dx` and `dy` pseudo-fields are grid spacing in meters.
`levels="Surface"` places the output at a single plane.

Definitions declare `unit=""`. A definition with no unit attribute
raised a DataCubeException on the OPC build.

### 5.2 Entry points and argument order

Hart family (`HartCPS.py`):

| Entry point | Arguments in order |
| :--- | :--- |
| `executeBand3` | z1, z2, z3, psfc, dx, dy, radiusKm, p1, p2, p3, capHpa |
| `executeBand4` | z1..z4, psfc, dx, dy, radiusKm, p1..p4, capHpa |
| `executeBand7` | z1..z7, psfc, dx, dy, radiusKm, p1..p7, capHpa |
| `executeClassStd` | z1000, z925, z850, z700, z500, z400, z300, psfc, dx, dy, radiusKm, neutralM, depthM, blobKm, capHpa |
| `executeIndexStd` | z1000, z925, z850, z700, z500, z400, z300, psfc, dx, dy, radiusKm, scaleM, depthM, blobKm, capHpa |
| `executeB` | z925, z700, u850, v850, u700, v700, u500, v500, u300, v300, psfc, coriolis, dx, dy, radiusKm, layerScale, capHpa |
| `executeETStage` | z1000, z925, z850, z700, u850, v850, u700, v700, u500, v500, u300, v300, psfc, coriolis, dx, dy, radiusKm, bThresholdM, layerScale, depthM, blobKm, capHpa |

Vorticity family (`CycloneCore.py`):

| Entry point | Arguments in order |
| :--- | :--- |
| `execute` | uLo, vLo, uHi, vHi, dx, dy, smoothKm |
| `executeVorticity` | u, v, dx, dy, mode |
| `executeClass` | uLo, vLo, uMid, vMid, uHi, vHi, dx, dy, smoothKm, band, vortexMin |
| `executeIndex` | uLo, vLo, uMid, vMid, uHi, vHi, dx, dy, smoothKm, scale, vortexMin |

### 5.3 Tunables by definition

Every tunable is a ConstantField in the XML. Edit the value and restart
CAVE; no Python change is needed.

| Definition | ConstantFields in order | Defaults |
| :--- | :--- | :--- |
| HVTL | radiusKm, p1, p2, p3, capHpa | 500, 925, 850, 700, 900 |
| HVTU | radiusKm, p1, p2, p3, capHpa | 500, 500, 400, 300, 900 |
| HCPScat | radiusKm, neutralM, depthM, blobKm, capHpa | 500, 25, 40, 200, 900 |
| HCPSidx | radiusKm, scaleM, depthM, blobKm, capHpa | 500, 100, 40, 200, 900 |
| HB | radiusKm, layerScale, capHpa | 500, 1.4553, 900 |
| HETstage | radiusKm, bThresholdM, layerScale, depthM, blobKm, capHpa | 500, 10, 1.4553, 40, 200, 900 |
| VTL, VTU | smoothKm | 100 |
| CPScat | smoothKm, band, vortexMin | 100, 3, 5 |
| CPSidx | smoothKm, scale, vortexMin | 100, 10, 5 |
| cpsZ850 | mode | 1 |

What each does:

- `radiusKm`: window half-width. Hart's 500. Larger integrates more of
  a tilted system; smaller sharpens compact storms.
- `neutralM`: half-width of the neutral band on both terms. Hart's own
  threshold is zero; 25 m prevents flicker.
- `depthM`: minimum low depth at 1000 hPa for classification. 40 m is
  about 5 hPa. Use 25 to include weak lows.
- `blobKm`: display radius around a detected center.
- `capHpa`: below-ground cap. Lower it only if deep ocean lows are
  being blanked, which has not been seen.
- `scaleM`: tanh scale for the index.
- `layerScale`: rescales B from the 925-700 hPa layer this package
  computes it on to a 900-600 hPa equivalent, so Hart's 10 m threshold
  applies. 1.0 gives the raw, unscaled value.
- `bThresholdM`: the Evans and Hart onset threshold for B. Hart's own
  is 10 m.

### 5.4 Adding definitions

To change the levels of a band, edit the GH Field levels and the
matching pressure ConstantFields together. To add a GFS-only definition
on Hart's exact 900 to 600 band, copy HVTL.xml, list GH at 900, 850,
800, 750, 700, 650, 600, then P, dx, dy, then ConstantFields radiusKm,
the seven pressures, capHpa, and name the method
`HartCPS.executeBand7`. A class product on those levels would need a
new entry point; `executeClassStd` is fixed to the standard levels.

---

## 6. Installation and localization

### 6.1 EDEX files

Site level under `/awips2/edex/data/utility/common_static/site/<SITE>/`:

```
derivedParameters/functions/HartCPS.py
derivedParameters/functions/CycloneCore.py
derivedParameters/definitions/HVTL.xml HVTU.xml HCPScat.xml HCPSidx.xml HB.xml HETstage.xml
derivedParameters/definitions/VTL.xml VTU.xml CPScat.xml CPSidx.xml cpsZ850.xml
colormaps/Grid/CPS_CoreDiverging.cmap
colormaps/Grid/CPS_CoreClass.cmap
colormaps/Grid/CPS_ETStage.cmap
```

Restart CAVE after any change. The embedded interpreter caches Python
modules until restart, and definitions are cached as well. Products
already loaded in a pane keep their old data until cleared and
reloaded.

Colormaps go in the existing Grid folder because creating a new
colormap subfolder at site level was not possible on the OPC build.
They appear under Grid in the legend's Change Colormap menu.

### 6.2 First-install verification

1. Product Browser, Grid, GFS: the six Hart products (HVTL, HVTU,
   HCPScat, HCPSidx, HB, HETstage) and the five vorticity products
   appear at Surface. Missing products mean a definition failed to
   parse; the CAVE log names the file.
2. Vorticity family only: load cpsZ850 beside D2D's own relative
   vorticity at 850 mb on a known hurricane. Matching sign and a single
   blob means the orientation mode is right. Lobes mean try mode 2 then
   3 in cpsZ850.xml, then set `ORIENTATION_MODE` in CycloneCore.py.
3. Load HCPScat on a hurricane: 4 at the center, blank ocean.
4. Load HETstage on the same hurricane, stepping toward its
   extratropical transition: 0 (or 1, once B crosses 10 m) while the
   storm is still tropical, 2 once HVTL turns negative. If HB/HETstage
   fail to load specifically (while HVTL/HVTU/HCPScat/HCPSidx load
   fine), the first suspect is the coriolis pseudo-field's abbreviation
   -- see HB.xml's/HETstage.xml's own VERIFY comment for the
   `<ConstantField value="1.0"/>` fallback.

### 6.3 Style rules

`styleRules/cpsStyleRules.xml` is written in the base schema (one
`paramLevelMatch` per rule with `parameter` children, `contourLabeling`
with space-separated values, `interpolate` off for categorical maps).
On the OPC build, placing it as a separate file at site level did not
apply automatically. Working route: set colormaps and ranges once and
save a procedure; the bundle stores them. Untested fallback: paste the
rules into site copies of `gridImageryStyleRules.xml` and
`gridContourStyleRules.xml`.

### 6.4 Menus

`menus/volumebrowser/cpsFields.xml` holds Volume Browser field entries
in the standard `contribute` form. It is not a drop-in; paste its lines
into a site copy of the Fields menu file the Volume Browser uses.

A one-click D2D menu item is a `bundleItem` on a site menu pointing at a
bundle file extracted from the saved procedure:

```xml
<contribute xsi:type="bundleItem" file="bundles/cpsHart4panel.xml"
            menuText="Cyclone Phase 4-panel" id="cpsHart4panel"/>
```

### 6.5 Troubleshooting

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| product missing from Product Browser | definition failed to parse, or an input field or level spelling not in the inventory | CAVE log names the file; check Field spellings against a base definition |
| DataCubeException on load | no unit attribute, or stale Python module | ensure `unit=""`; replace the .py and restart CAVE |
| readout 0.00 on VTL/VTU | old CycloneCore.py without unit scaling | install current .py and definitions together |
| lobed pattern on cpsZ850 | wrong orientation mode | mode search per 6.2 |
| dipole on vorticity family at a low | tilt, inherent | use the Hart family |
| whole field green on load | style rule not applied | pick the colormap from the legend or load the procedure |
| Hart products vanish after adding P | P field level spelling | check how base definitions reference Surface |
| blank over land | below-ground mask | expected |
| HB/HETstage missing while other Hart products load | coriolis pseudo-field abbreviation not recognized | replace the `coriolis` Field with `<ConstantField value="1.0"/>` (assumes Northern Hemisphere) |
| HB near zero everywhere on an obviously asymmetric storm | steering speed below `MIN_STEERING_MS` (1 m/s) at that point | check the four steering wind levels are not all missing/near-calm there |

---

## 7. Tests

```
python3 -m pytest tests -q
```

89 tests: the storm-centered reference in `tests/cps`, and the two
families in `tests/d2d_cps`. Every expected value is analytic or from a
brute-force comparison, never copied from the implementation. Coverage
includes sliding extrema against brute force, band slopes on exact
linear profiles, agreement between the gridded and the point Hart
implementation on a synthetic vortex, the closed-low mask on flat,
sloped, and two-low fields, the terrain mask, Pa versus hPa detection,
orientation modes on transposed inputs, and a performance budget on a
full 0.25 degree grid. `tests/d2d_cps/conftest.py` puts the functions
directory on the path so the files import exactly as CAVE imports them.

---

## 8. Known limitations and future work

**Design decision, final (2026-09-18).** The square analysis window is
kept permanently. A circular window was considered and rejected: the
square supports the fast separable sliding-extrema filter (section
4.1), and a circular filter would cost several times more per frame.
The trade-off is a small cold bias on a strong background gradient
(section 2.2), which is documented and understood, not a defect to be
fixed. This is not future work; do not reopen it without a new reason
to revisit the cost/accuracy trade-off.

- Standard-level bands differ from Hart's. A GFS-only 13-level
  definition is a small addition (5.4).
- Parameter B (`HB`/`HETstage`) now uses the steering flow (mean wind
  at 850/700/500/300 hPa) as its motion proxy and a linear-gradient
  approximation for the right-minus-left half-window mean. Both are
  new and awaiting validation: the steering proxy is unreliable for a
  storm moving against its own steering flow or for a nearly
  stationary system, and the linear approximation loses genuinely
  nonlinear thickness structure inside the window (e.g. a
  warm-seclusion tongue) to first order.
- Vorticity family Southern Hemisphere sign. Needs a latitude input.
- Below-ground rule uses one cap for all levels. A per-level margin
  would be more precise.
- Style rules did not auto-apply at site level; the mechanism on this
  build is unverified.
- Next steps under discussion: a GFE procedure that samples HVTL and
  HVTU along the TCM track and draws the classic phase diagram; model
  comparison of transition timing as a routine product; the
  self-hosted web version described in `web/CPS/PLAN.md`.

---

## 9. References

- Hart, R. E., 2003: A cyclone phase space derived from thermal wind
  and thermal asymmetry. Mon. Wea. Rev., 131, 585 to 616.
- FSU cyclone phase page: https://moe.met.fsu.edu/cyclonephase/
- Storm-centered reference implementation: `cps/hart.py` in this
  repository.

---

## 10. Document set

Where everything about this package lives, and what each piece is for:

- `D2D/README.md`: install checklist, per-field method notes, and the
  validation log. The first thing to read when standing up the package
  at a new site.
- `D2D/docs/USER_GUIDE.md`: for forecasters, how to load and read the
  products, what the three terms mean, and where they mislead.
- `D2D/docs/TECHNICAL_GUIDE.md`: this document, for whoever installs,
  tunes, maintains, or ports the package.
- `D2D/docs/ABSTRACT.md`: the one-paragraph scientific abstract, for
  anyone citing or summarizing this work outside the repository.
- `D2D/docs/TALK.md`: the script for a seven-minute spoken
  introduction to the package, timed and slide-cued.
- `D2D/docs/TALK.pptx`: the slide deck that goes with `TALK.md`, same
  text in each slide's speaker notes.
- `docs/cps/index.html`: the longer web article, with the method,
  figures, and validation cases in full; the source for the teaching
  figures embedded in the User Guide.
