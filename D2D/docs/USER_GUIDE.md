# Cyclone Phase Space in D2D: User Guide

For forecasters. This guide covers what the CPS products show, how to
load them, how to read them, and where they mislead. It assumes nothing
about how they are computed; that is in the Technical Guide.

**Status: experimental.** Validated on a typhoon, its extratropical
transition timing against the FSU cyclone phase page, and a cold-core
North Atlantic low. Not yet through a full season.

---

## 1. What it is

Cyclone Phase Space (Hart 2003) classifies a cyclone by its thermal
structure rather than by intensity or track. The FSU web page draws the
result as a trajectory through a diagram, one dot per forecast hour, for
each tracked storm. These D2D products compute the same two thermal
numbers at every grid point of a model and show them as maps, so every
low in the domain gets classified on every frame, with no tracker and
no advisory required. What you lose is the trajectory picture; what you
gain is every low at once, on every model in D2D, including ones nobody
is issuing advisories on.

The two numbers are:

- **Lower thermal wind, -VT lower.** Whether the storm's core is warmer
  or colder than its surroundings in the lower troposphere (925 to 700
  hPa). Positive is warm.
- **Upper thermal wind, -VT upper.** The same for the upper troposphere
  (500 to 300 hPa). Positive is warm.

Hart's third number, B, the frontal asymmetry, is not computed. Overlay
1000 to 500 hPa thickness and read it by eye: closed thickness contours
around the low mean symmetric, a low sitting in a tight thickness
gradient means frontal.

---

## 2. The products

Two families exist. **Use the Hart family.** The vorticity family is an
earlier shortcut that reads tilted or broad systems as too warm and is
kept for comparison only.

| Product | Menu name | What it shows | Read as |
| :--- | :--- | :--- | :--- |
| HVTL | Hart CPS -VT lower (925-700) (m) | lower thermal wind, meters | positive warm core, negative cold core |
| HVTU | Hart CPS -VT upper (500-300) (m) | upper thermal wind, meters | positive warm core, negative cold core |
| HCPScat | Hart CPS Core Class | category 0 to 4 at each detected low, blank elsewhere | see table in section 4 |
| HCPSidx | Hart CPS Core Index | one number from -3 to +3 at each detected low | -3 deep cold, 0 neutral, +3 deep warm |

Vorticity family, secondary: VTL, VTU, CPScat, CPSidx, same layout,
different method and units. cpsZ850 is an installation check, not a
forecast product.

All products sit at a single Surface plane in the Product Browser and
overlay on anything.

---

## 3. Loading

**Product Browser.** Grid, then the model, then the product name, then
Surface. The four Hart products appear together because their names
start with Hart CPS. If a product is missing for a model, that model does
not carry the six standard levels or surface pressure.

**Volume Browser.** Only if your site has added the entries to the
Fields menu; then they are under a Hart CPS heading.

**Saved procedure.** The recommended way. Someone at the site has saved
a four-panel with the colormaps and ranges set. Load it from the
procedures list or from the site menu item if one was added.

**Recommended four-panel.** MSLP contours in every panel, then:

1. HCPScat as image, with 10 m wind barbs.
2. HCPSidx as image.
3. HVTL as image, with 1000 to 500 hPa thickness contours.
4. HVTU as image.

**Colormaps.** If a panel comes up in the default green ramp, right
click the legend, Change Colormap, Grid, and pick CPS_CoreDiverging for
HVTL, HVTU, and HCPSidx, or CPS_CoreClass for HCPScat. The diverging map
is transparent near zero on purpose so the contours show through.

**Sampling.** Left click and hold reads the value under the cursor.
HVTL and HVTU read in meters, HCPScat reads the category number,
HCPSidx reads the index.

---

## 4. Reading the fields

### The category, HCPScat

| Code | Color | Structure | Typical system |
| :--- | :--- | :--- | :--- |
| 4 | red | deep warm core | hurricane, strong tropical storm |
| 3 | orange | shallow warm core | subtropical storm, weak or sheared tropical cyclone, warm seclusion late in an extratropical low's life |
| 2 | pale gray | neutral | both numbers within 25 m of zero, marginal |
| 1 | blue | cold core | extratropical or cutoff low |
| 0 | gray | mid-level vortex | rare and transient, treat as unclassified |
| blank | | not a closed low | nothing to classify here |

A blob appears only where the model has a closed low at least about
5 hPa deep, painted 200 km around the center. Open ocean stays blank.
Very weak lows get no blob; that is deliberate.

### The numbers, HVTL and HVTU

These are Hart's own quantities in his units. Typical values:

| System | HVTL | HVTU |
| :--- | :--- | :--- |
| mature hurricane or typhoon | +100 to +300 | +50 to +300 |
| subtropical or sheared storm | positive | near zero or negative |
| deep extratropical low | negative | -100 to -300 |
| weak or marginal system | within about 25 of zero | |

Zero is the warm versus cold boundary, exactly as on the FSU diagram.
Values are close to but not identical to the FSU page for the same
storm, because the FSU page uses 50 hPa levels and these use standard
levels only.

The raw HVTL and HVTU images paint a square about 1000 km across around
each low. That is the shape of the analysis window, not a feature of
the storm. Read the value at the MSLP center.

### The index, HCPSidx

One number for glanceability and trends. Near +3 deep warm, +1 to +2
shallow warm, near 0 neutral, negative cold. It blurs the shallow warm
versus cold distinction that the category keeps, so use it for trends
and the category for the call.

---

## 5. Using it on shift

**Extratropical transition timing.** Step through the frames on a
tropical cyclone. Two markers are available here:

- The first hour the category drops from 4 is the loss of the deep warm
  core, HVTU turning negative, which usually means the upper trough has
  reached the storm. This is a sign transition is under way, not the
  formal onset.
- The hour HVTL turns negative and the category reaches 1 is the loss
  of the low-level warm core. This is the Evans and Hart (2003)
  completion time.

The formal Evans and Hart onset, when the thermal asymmetry B exceeds
10 m, is not computed here because B needs a storm motion. Read it from
the thickness overlay instead: the low moving from closed thickness
contours into a tight gradient is onset. Around these hours the wind
field expands well beyond its tropical radius and becomes strongly
asymmetric, and the gale and storm-force radii grow fastest.

**Model comparison.** Load HCPScat for two models on the same storm and
step frames side by side. Where they disagree on the hour the category
drops is the transition uncertainty, and that is usually the wind
forecast uncertainty as well.

**Warm seclusion.** A high-latitude occluded low that reads 3, positive
HVTL over negative HVTU, has re-formed a warm core near the surface.
Confirm with closed thickness contours around it. These are the systems
that unexpectedly deepen and produce hurricane-force winds over cold
water.

**Handoff and hybrid cases.** A system reading 3 with a thickness
gradient across it is the classic subtropical or hybrid case. Whether
it trends toward 4 or toward 1 over the next 24 h says which way the
handoff goes.

**Read the trend, not the frame.** One frame jumping a category is
noise. Two or three consecutive frames in the same direction is signal.

---

## 6. Cautions

- **It classifies the model's storm.** A confident-looking class on a
  bad model track is a confident wrong answer. Compare models.
- **Blank over high terrain.** Greenland, the Rockies, and other high
  ground are blank because the lower levels are below the surface
  there. This is correct behavior, not missing data.
- **Weak lows are not classified.** Under about 5 hPa deep gets no
  blob. The numbers still exist in HVTL and HVTU if you need them.
- **Near-threshold flicker.** A storm near a category boundary can flip
  between frames. The index is smoother for those.
- **Values near a coast.** Within about 500 km of high terrain the
  window has less data on one side. The value is still valid but less
  robust.
- **The vorticity family reads warm too often.** Tilted systems and
  broad upper troughs bias it warm, which is why the Hart family
  replaced it. If you use it, do not call cold core from it.
- **Southern Hemisphere.** The Hart family is fine there. The vorticity
  family blanks Southern Hemisphere cyclones entirely.

---

## 7. Quick reference

- Load: Product Browser, Grid, model, Hart CPS products, Surface. Or the
  saved procedure.
- Colors: CPS_CoreDiverging for the numbers and index,
  CPS_CoreClass for the category.
- Read: category at the MSLP center. 4 deep warm, 3 shallow warm,
  2 neutral, 1 cold, 0 unclassified.
- Numbers: positive warm, negative cold, zero is the line, meters.
- Deep warm core lost: first frame the category leaves 4. Transition
  complete: HVTL negative, category 1. Onset: read from thickness.
- Always overlay MSLP and thickness.
