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
each tracked storm. These D2D products compute the same numbers at
every grid point of a model and show them as maps, so every low in the
domain gets classified on every frame, with no tracker and no advisory
required. What you lose is the trajectory picture; what you gain is
every low at once, on every model in D2D, including ones nobody is
issuing advisories on.

The three numbers behind every product here are explained in plain
language in section 2. In short:

- **Lower thermal wind, -VT lower.** Whether the storm's core is warmer
  or colder than its surroundings in the lower troposphere (925 to 700
  hPa). Positive is warm.
- **Upper thermal wind, -VT upper.** The same for the upper troposphere
  (500 to 300 hPa). Positive is warm.
- **B, the frontal asymmetry.** Whether warm and cold air sit on
  opposite sides of the storm's track. Computed as HB, and combined
  with the lower thermal wind into HETstage, the extratropical
  transition stage (see sections 3 and 6).

HB relies on the model's own steering flow standing in for the storm's
motion, so it is worth cross-checking by eye too: overlay 1000 to 500
hPa thickness and look for closed contours around the low (symmetric)
or a tight gradient across it (frontal).

---

## 2. How the three terms work

Everything else in this guide is a way of reading three numbers off a
map. This section explains what those numbers mean before you look at
the products in section 3.

### The lower and upper thermal wind: is the core warm or cold?

Picture a cross-section through a storm. The height of a pressure
surface dips down over the low, like a shallow bowl. How that bowl
changes shape as you go up in the atmosphere is what tells you whether
the storm is warm-core or cold-core.

In a hurricane, the whole column of air above the storm is warm, and
warm air is less dense, so the dip is deepest right at the surface and
fills in quickly with height: by 300 hPa there is not much of a low
left. In a cold-core low the column is cold and dense, so it is the
other way around: the dip is shallow at the surface but gets deeper
with height, and the strongest low sits aloft rather than at the
ground.

Hart turns that shape into a number. At each level, measure the height
range inside a circle around the center, the highest point inside minus
the lowest. Then look at how that range changes with height. Shrinking
upward means warm core, and the number comes out positive. Growing
upward means cold core, and the number comes out negative.

Because a storm's structure can differ between the lower and upper
troposphere, Hart computes this twice: once for a lower band of levels
and once for an upper band. HVTL and VTL are the lower number, HVTU and
VTU are the upper number. A hurricane is warm all the way up, so both
read positive. A subtropical storm or a warm seclusion is warm only
near the surface, so the lower number is positive while the upper
number is near zero or negative. That split between the two levels is
exactly what HCPScat's category and HCPSidx's index are built from.

### Parameter B: is the storm sitting in a front?

The two thermal wind numbers describe the storm's own core. B describes
what is going on around it.

Thickness, the depth of the layer between two pressure levels, is a
stand-in for how warm that layer of air is: a thick layer is warm, a
thin one is cold. Take the same circle around the storm, split it into
a side to the right of the storm's direction of travel and a side to
the left, and compare the average thickness on each side.

For a hurricane sitting in a uniform tropical air mass, the two sides
look about the same, so B comes out near zero: the storm is symmetric.
Once a storm moves into a baroclinic zone, warm air collects on one
side and cold air on the other, and B grows. Hart's threshold for
calling that asymmetry significant is 10 meters. HB reproduces this
idea from a gridded approximation, standing in the model's own
steering-level wind for a tracked heading, which is why it should not
be trusted blindly for a storm that is barely moving or moving against
its own steering flow (see section 7).

### The two diagrams and the transition sequence

Hart plots these three numbers on two diagrams: B against the lower
thermal wind, which separates symmetric from frontal and warm from
cold; and lower against upper thermal wind, which separates deep warm
core, shallow warm core, and cold core. A hurricane starts in the deep
warm, symmetric corner of both.

As a storm undergoes extratropical transition it moves through these
diagrams in a set order: B climbs past 10 meters first (HETstage moves
from 0 to 1, the Evans and Hart onset), then the upper warm core is
usually lost next (HCPScat drops out of category 4, which is a sign
transition is under way but not itself one of the two named markers),
and finally the lower thermal wind turns negative (HETstage reaches 2,
the Evans and Hart completion). Some storms then curve back toward the
warm side as a warm seclusion re-forms a shallow warm core near the
surface, which is one reason those systems can deepen unexpectedly over
cold water. Section 6 walks through spotting this sequence on shift.

![Cross-sections showing a warm-core storm's height dip shrinking with altitude and a cold-core low's dip growing with altitude, with the resulting height-range-versus-pressure slope on the right](../../docs/cps/figures/fig8_thermal_wind_concept.png)
*A warm core's height perturbation weakens with height, giving a positive slope; a cold core's grows, giving a negative slope: that slope is HVTL and HVTU.*

![Plan view of parameter B for a symmetric hurricane against a storm sitting on a thickness gradient](../../docs/cps/figures/fig9_b_concept.png)
*B compares the average thickness on the two sides of the storm's track; a hurricane in a uniform air mass reads near zero, a storm in a front reads well above 10 meters.*

![Hart's two cyclone phase space diagrams sharing one schematic extratropical transition trajectory](../../docs/cps/figures/fig10_two_diagrams.png)
*A transitioning storm traces a path through both diagrams: B crosses 10 meters, the upper warm core is lost, then the lower one, sometimes hooking back toward a warm seclusion.*

---

## 3. The products

Two families exist. **Use the Hart family.** The vorticity family is an
earlier shortcut that reads tilted or broad systems as too warm and is
kept for comparison only.

| Product | Menu name | What it shows | Read as |
| :--- | :--- | :--- | :--- |
| HCPScat | Hart CPS Core Class | category 0 to 4 at each detected low, blank elsewhere | see table in section 5 |
| HETstage | Hart CPS ET Stage | extratropical transition stage 0/1/2 at each detected low, blank elsewhere | 0 pre-onset, 1 onset, 2 complete |
| HVTL | Hart CPS -VT lower (925-700) (m) | lower thermal wind, meters | positive warm core, negative cold core |
| HVTU | Hart CPS -VT upper (500-300) (m) | upper thermal wind, meters | positive warm core, negative cold core |
| HB | Hart CPS B Asymmetry (HB) | thermal asymmetry, meters (900-600 hPa equivalent) | near zero symmetric/tropical, above 10 asymmetric/frontal |
| HCPSidx | Hart CPS Core Index | one number from -3 to +3 at each detected low | -3 deep cold, 0 neutral, +3 deep warm |

Vorticity family, secondary: VTL, VTU, CPScat, CPSidx, same layout,
different method and units (1e-5 per second, not meters). cpsZ850 is an
installation and orientation check for site administrators, not a
forecast product.

All products sit at a single Surface plane in the Product Browser and
overlay on anything.

---

## 4. Loading

**Product Browser.** Grid, then the model, then the product name, then
Surface. The six Hart products appear together because their names
start with Hart CPS. If a product is missing for a model, that model does
not carry the six standard levels or surface pressure.

**Volume Browser.** Only if your site has added the entries to the
Fields menu; then they are under a Hart CPS heading.

**Saved procedure.** The recommended way. Someone at the site has saved
a four-panel with the colormaps and ranges set. Load it from the
procedures list or from the site menu item if one was added.

**Recommended four-panel.** MSLP contours in every panel, then:

1. HCPScat as image, with 10 m wind barbs.
2. HETstage as image.
3. HVTL as image, with 1000 to 500 hPa thickness contours.
4. HVTU as image.

HCPSidx and HB are useful optional panels: HCPSidx for a smoother trend
line than the category alone, HB to read the asymmetry number directly
instead of inferring it from HETstage.

**Colormaps.** If a panel comes up in the default green ramp, right
click the legend, Change Colormap, Grid, and pick CPS_CoreDiverging for
HVTL, HVTU, HB, and HCPSidx; CPS_CoreClass for HCPScat; or CPS_ETStage
for HETstage. The diverging map is transparent near zero on purpose so
the contours show through.

**Sampling.** Left click and hold reads the value under the cursor.
HVTL, HVTU, and HB read in meters, HCPScat and HETstage read the
category or stage number, HCPSidx reads the index.

---

## 5. Reading the fields

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

### The ET stage, HETstage

| Code | Meaning |
| :--- | :--- |
| 0 | pre-onset: B has not yet exceeded 10 m |
| 1 | onset: B has exceeded 10 m, HVTL still zero or positive |
| 2 | complete: HVTL has turned strictly negative |

HETstage has no memory of an earlier frame, so a warm seclusion that
re-forms a low-level warm core after transition can drop back to 0 or 1
rather than staying at 2. Read it alongside HCPScat at the same point
and time rather than on its own.

### The numbers, HVTL and HVTU

These are Hart's own quantities in his units. Typical values:

| System | HVTL | HVTU | HB |
| :--- | :--- | :--- | :--- |
| mature hurricane or typhoon | +100 to +300 | +50 to +300 | near 0 |
| subtropical or sheared storm | positive | near zero or negative | rising toward 10 |
| storm undergoing extratropical transition | mixed, falling | usually negative first | above 10 |
| deep extratropical or post-transition low | negative | -100 to -300 | well above 10 |
| weak or marginal system | within about 25 of zero | | |

Zero is the warm versus cold boundary, exactly as on the FSU diagram.
Values are close to but not identical to the FSU page for the same
storm, because the FSU page uses 50 hPa levels and these use standard
levels only.

The raw HVTL, HVTU, and HB images paint a square about 1000 km across
around each low. That is the shape of the analysis window, not a
feature of the storm; see section 7 for why the window is a square.
Read the value at the MSLP center.

### The index, HCPSidx

One number for glanceability and trends. Near +3 deep warm, +1 to +2
shallow warm, near 0 neutral, negative cold. It blurs the shallow warm
versus cold distinction that the category keeps, so use it for trends
and the category for the call.

---

## 6. Using it on shift

**Extratropical transition timing.** Step through the frames on a
tropical cyclone headed into higher latitudes. Three markers, in the
order they happen:

1. **Onset.** HETstage steps from 0 to 1 the first hour HB exceeds
   10 m. This is the Evans and Hart (2003) objective onset: the storm
   has picked up a frontal asymmetry, even though HCPScat may still
   read 4.
2. **Loss of the upper warm core.** The first hour HCPScat leaves
   category 4 typically falls between onset and completion, and marks
   HVTU going negative. This is a sign transition is under way, not
   one of the two named Evans and Hart markers itself.
3. **Completion.** HETstage reaches 2 the hour HVTL turns negative:
   the lower warm core is gone. This is the Evans and Hart (2003)
   completion time.

Keep the thickness overlay as a cross-check: the low moving from closed
thickness contours into a tight gradient across it should line up with
the frame HETstage crosses into stage 1, and a mismatch is worth a
second look before trusting either field alone. Around these hours the
wind field expands well beyond its tropical radius and becomes strongly
asymmetric, and the gale and storm-force radii grow fastest.

**Caution on HB and HETstage.** HB is computed from the steering flow
(the mean wind at 850, 700, 500, and 300 hPa) standing in for the
storm's own motion, not a tracked heading. It is unreliable or blank
for a storm moving against its own steering flow or one that is nearly
stationary, and HETstage's onset call inherits that weakness. See
section 7 for how to handle a suspicious reading.

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

## 7. Cautions

- **It classifies the model's storm.** A confident-looking class on a
  bad model track is a confident wrong answer. Compare models.
- **The square analysis window is a known and accepted shape, not a
  bug.** HVTL, HVTU, and HB are computed over a square window, not a
  circle, because the square runs fast enough to compute at every grid
  point on every frame. This carries a small cold bias on a strong
  background gradient. The square window is a permanent design choice:
  a circular window was considered and rejected because the speed of
  the fast filter is worth more than that small, understood bias.
- **HB depends on the steering flow, not the storm's real motion.** HB
  and HETstage stand in the model's mean 850-300 hPa wind for the
  storm's own heading. A storm moving against its own steering flow,
  or a nearly stationary one, gets an unreliable or blank HB and an
  onset call in HETstage that should not be trusted on its own.
  Cross-check against the thickness overlay before calling onset from
  HB or HETstage alone.
- **Blank over high terrain.** Greenland, the Rockies, and other high
  ground are blank because the lower levels are below the surface
  there. This is correct behavior, not missing data.
- **Weak lows are not classified.** Under about 5 hPa deep gets no
  blob, on HCPScat, HCPSidx, or HETstage. The numbers still exist in
  HVTL, HVTU, and HB if you need them.
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

## 8. Quick reference

- Load: Product Browser, Grid, model, Hart CPS products, Surface. Or the
  saved procedure.
- Colors: CPS_CoreDiverging for HVTL, HVTU, HB, and HCPSidx;
  CPS_CoreClass for the category; CPS_ETStage for HETstage.
- Read: category at the MSLP center. 4 deep warm, 3 shallow warm,
  2 neutral, 1 cold, 0 unclassified.
- Numbers: positive warm, negative cold, zero is the line, meters for
  the Hart family (HVTL, HVTU, HB); the vorticity family is secondary
  and reads in 1e-5 per second.
- Transition sequence: onset at HETstage 1 (HB above 10), upper warm
  core lost when the category leaves 4, completion at HETstage 2
  (HVTL negative). Cross-check against the thickness overlay.
- The square window footprint on the raw fields is a permanent design
  choice, not something waiting to be fixed.
- Always overlay MSLP and thickness.
