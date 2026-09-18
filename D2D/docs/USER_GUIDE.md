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
  with both thermal wind terms into HCPSclass, the joint
  classification (see sections 3 and 5).

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
exactly what HCPSclass's class and HCPSidx's index are built from.

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
diagrams in a set order: B climbs past 10 meters and the storm becomes
frontal first (HCPSclass moves from 0 to 2, the Evans and Hart onset),
then the upper warm core is usually lost next (HCPSclass moves from 2
to 3), and finally the lower thermal wind turns negative (HCPSclass
reaches 4, the Evans and Hart completion). Some storms then curve back
toward the warm side as a warm seclusion re-forms a shallow warm core
near the surface (HCPSclass back to 1, with the upper term still
cold), which is one reason those systems can deepen unexpectedly over
cold water. Section 6 walks through spotting this sequence on shift.

![Cross-sections showing a warm-core storm's height dip shrinking with altitude and a cold-core low's dip growing with altitude, with the resulting height-range-versus-pressure slope on the right](../../docs/cps/figures/fig8_thermal_wind_concept.png)
*A warm core's height perturbation weakens with height, giving a positive slope; a cold core's grows, giving a negative slope: that slope is HVTL and HVTU.*

![Plan view of parameter B for a symmetric hurricane against a storm sitting on a thickness gradient](../../docs/cps/figures/fig9_b_concept.png)
*B compares the average thickness on the two sides of the storm's track; a hurricane in a uniform air mass reads near zero, a storm in a front reads well above 10 meters.*

![Hart's two cyclone phase space diagrams sharing one schematic extratropical transition trajectory](../../docs/cps/figures/fig10_two_diagrams.png)
*A transitioning storm traces a path through both diagrams: B crosses 10 meters, the upper warm core is lost, then the lower one, sometimes hooking back toward a warm seclusion.*

### Why one number

Hart's two diagrams are two projections of one three-dimensional space
(B, lower thermal wind, upper thermal wind) that happen to share the
lower thermal wind axis. Each diagram alone carries one piece of
information the other lacks: the B-versus-lower diagram says whether
the storm is frontal, the lower-versus-upper diagram says whether a
warm core is deep or shallow. A classification built from all three
numbers at once carries both and loses neither. Operationally that
means sampling one number at the low center instead of reading two
panels and combining them by eye, and the resulting codes fall in
order along the transition (see "Reading the class" in section 5).
The old two-field product's "onset" and "complete" labels named
events, and an event needs history to detect; a single frame can only
say what state the storm is in right now. HCPSclass names the states,
which are Hart's; the events are still there, read from how the state
changes frame to frame.

### How this differs from the FSU page

HCPSclass and the FSU page describe the same three numbers, but not the
same measurement. The FSU page follows one tracked storm along its
path; HCPSclass classifies every closed low on the grid, every frame,
independent of any track. The FSU page draws a trajectory through the
diagram; HCPSclass gives you a map per forecast hour, and you recover
the trajectory by animating and reading the class at the low center (or
by sampling HVTL, HVTU, and HB there directly). The FSU page uses
Hart's own 500 km circle and true half-circle motion; this package uses
a 1000 km square for speed (a documented, permanent design choice, not
a bug; see section 7) and the model's steering flow in place of a
tracked heading, so HB and HCPSclass are unreliable for a stationary or
steering-opposed storm. Both are memoryless at any single time; both
read onset and completion from watching the trajectory change, not from
one frame. And HCPSclass classifies any closed low at least about 5 hPa
deep, tropical or not, tracked or not, which is the point of building
it as a gridded product at all.

---

## 3. The products

| Product | Menu name | What it shows | Read as |
| :--- | :--- | :--- | :--- |
| HCPSclass | Hart CPS Class | one of Hart's six named structures (0-6) at each detected low, blank elsewhere | see "Reading the class" in section 5 |
| HVTL | Hart CPS -VT lower (925-700) (m) | lower thermal wind, meters | positive warm core, negative cold core |
| HVTU | Hart CPS -VT upper (500-300) (m) | upper thermal wind, meters | positive warm core, negative cold core |
| HB | Hart CPS B Asymmetry (HB) | thermal asymmetry, meters (900-600 hPa equivalent) | at or below 10 symmetric, above 10 frontal |
| HCPSidx | Hart CPS Core Index | one number from -3 to +3 at each detected low | -3 deep cold, 0 neutral, +3 deep warm |

All products sit at a single Surface plane in the Product Browser and
overlay on anything.

See "Retired products" in section 7 for the earlier vorticity-based
products that these replaced.

---

## 4. Loading

**Product Browser.** Grid, then the model, then the product name, then
Surface. The five Hart products appear together because their names
start with Hart CPS. If a product is missing for a model, that model does
not carry the six standard levels or surface pressure.

**Volume Browser.** Only if your site has added the entries to the
Fields menu; then they are under a Hart CPS heading.

**Saved procedure.** The recommended way. Someone at the site has saved
a four-panel with the colormaps and ranges set. Load it from the
procedures list or from the site menu item if one was added.

**Recommended four-panel.** MSLP contours in every panel, then:

1. HCPSclass as image, with 10 m wind barbs.
2. HVTL as image, with 1000 to 500 hPa thickness contours.
3. HVTU as image.
4. HB as image.

HCPSidx is a useful optional fifth panel, for a smoother trend line
than the class alone.

**Colormaps.** If a panel comes up in the default green ramp, right
click the legend, Change Colormap, Grid, and pick CPS_CoreDiverging for
HVTL, HVTU, HB, and HCPSidx; or CPS_HartClass for HCPSclass. The
diverging map is transparent near zero on purpose so the contours show
through.

**Sampling.** Left click and hold reads the value under the cursor.
HVTL, HVTU, and HB read in meters, HCPSclass reads the class code,
HCPSidx reads the index.

---

## 5. Reading the fields

### Reading the class, HCPSclass

Hart's strict lines: B against 10 m, and both thermal wind terms
against 0, warm if greater than or equal to zero and cold if less
than zero. There is no neutral band here (compare HCPSidx below, which
keeps one).

| Code | Color | Name | B | lower VT | upper VT | Typical system |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | red | symmetric deep warm core | <= 10 | warm | warm | hurricane, typhoon |
| 1 | orange | symmetric shallow warm core | <= 10 | warm | cold | subtropical storm, or warm seclusion after transition |
| 2 | magenta | frontal deep warm core | > 10 | warm | warm | hurricane meeting a trough, transition beginning |
| 3 | yellow | frontal shallow warm core | > 10 | warm | cold | transition under way |
| 4 | blue | frontal cold core | > 10 | cold | any | extratropical low, transition complete |
| 5 | violet | symmetric cold core | <= 10 | cold | any | occluded or cutoff cold low |
| 6 | gray | mid-level vortex | any | cold | warm | rare, treat as unclassified |
| blank | | not a closed low, or B undefined | | | | no closed low, or steering below 1 m/s |

The codes rise along a typical extratropical transition: 0, 2, 3, 4. A
warm seclusion is 4 then back to 1, with the upper term still cold.
Onset (Evans and Hart, 2003) is the first frame in class 2 or 3;
completion is the first frame in class 4 or 5. Read both from the
animation, never from a single frame; the field has no memory of the
frame before it.

A blob appears only where the model has a closed low at least about
5 hPa deep, painted 200 km around the center. Open ocean stays blank.
Very weak lows get no blob; that is deliberate. A storm sitting exactly
on a strict line (B at 10 m, or a thermal wind term at 0) can flip
between adjacent codes frame to frame; that is expected near a
boundary, and HVTL, HVTU, and HB are smoother places to look for the
underlying trend when it happens.

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
versus cold distinction that the class keeps, so use it for trends and
the class for the call.

---

## 6. Using it on shift

**Extratropical transition timing.** Step through the frames on a
tropical cyclone headed into higher latitudes and watch the class
climb: 0, then 2, then 3, then 4.

1. **Onset.** The first frame HCPSclass reaches 2 or 3 is the Evans
   and Hart (2003) objective onset: the storm has picked up a frontal
   asymmetry (B above 10 m) while at least the lower core is still
   warm.
2. **Loss of the upper warm core.** The class moving from 2 to 3 marks
   HVTU going negative while the storm is still frontal. This is a
   sign transition is under way, not itself one of the two named
   Evans and Hart markers.
3. **Completion.** The first frame HCPSclass reaches 4 or 5 is the
   Evans and Hart (2003) completion time: the lower warm core is gone.

Read both onset and completion from the animation, stepping several
frames back and forth, not from one frame in isolation; the field
has no memory, so a single frame cannot tell you whether a code is the
start of a trend or a one-frame flicker on a strict line.

Keep the thickness overlay as a cross-check: the low moving from closed
thickness contours into a tight gradient across it should line up with
the frame HCPSclass crosses into 2 or 3, and a mismatch is worth a
second look before trusting either field alone. Around these hours the
wind field expands well beyond its tropical radius and becomes strongly
asymmetric, and the gale and storm-force radii grow fastest.

**Caution on HB and HCPSclass.** HB is computed from the steering flow
(the mean wind at 850, 700, 500, and 300 hPa) standing in for the
storm's own motion, not a tracked heading. It is unreliable or blank
for a storm moving against its own steering flow or one that is nearly
stationary, and HCPSclass's frontal/symmetric split inherits that
weakness wherever HB is unreliable or blank. See section 7 for how to
handle a suspicious reading.

**Model comparison.** Load HCPSclass for two models on the same storm
and step frames side by side. Compare the hour each model's class first
reaches 2 or 3 (onset) and the hour each first reaches 4 or 5
(completion); where they disagree is the transition uncertainty, and
that is usually the wind forecast uncertainty as well.

**Warm seclusion.** A high-latitude low that returns to class 1 after
having reached 4, with the upper term still cold, has re-formed a warm
core near the surface. Confirm with closed thickness contours around
it. These are the systems that unexpectedly deepen and produce
hurricane-force winds over cold water.

**Handoff and hybrid cases.** A system reading 2 or 3, frontal with a
still-warm lower core, is the classic subtropical or hybrid case.
Whether it trends toward 0 (rare) or on toward 4 over the next 24 h
says which way the handoff goes.

**Read the trend, not the frame.** One frame jumping a class is noise,
especially near a strict line. Two or three consecutive frames in the
same direction is signal.

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
  and HCPSclass stand in the model's mean 850-300 hPa wind for the
  storm's own heading. A storm moving against its own steering flow,
  or a nearly stationary one, gets an unreliable or blank HB, and
  HCPSclass's frontal/symmetric call inherits that weakness wherever
  HB is unreliable or blank. Cross-check against the thickness overlay
  before calling onset or completion from HB or HCPSclass alone.
- **Blank over high terrain.** Greenland, the Rockies, and other high
  ground are blank because the lower levels are below the surface
  there. This is correct behavior, not missing data.
- **Weak lows are not classified.** Under about 5 hPa deep gets no
  blob, on HCPSclass or HCPSidx. The numbers still exist in HVTL,
  HVTU, and HB if you need them.
- **Near-strict-line flicker.** A storm sitting on one of HCPSclass's
  strict lines (B at 10 m, or a thermal wind term at 0) can flip
  between adjacent codes from one frame to the next. This is expected,
  not a bug: the class has no neutral band by design. HVTL, HVTU, HB,
  and HCPSidx are smoother places to look for the underlying trend
  through a flickering stretch.
- **Values near a coast.** Within about 500 km of high terrain the
  window has less data on one side. The value is still valid but less
  robust.

### Retired products

VTL, VTU, CPScat, CPSidx, and cpsZ850, the earlier vorticity-based
family, were removed from the menu on 2026-09-18. They read tilted and
broad systems too warm and blanked Southern Hemisphere warm cores
outright. HVTL, HVTU, HB, HCPSidx, and HCPSclass, described above,
replace them and cover the same ground without either problem.

---

## 8. Quick reference

- Load: Product Browser, Grid, model, Hart CPS products, Surface. Or the
  saved procedure.
- Colors: CPS_CoreDiverging for HVTL, HVTU, HB, and HCPSidx;
  CPS_HartClass for the class.
- Read: class at the MSLP center. 0 symmetric deep warm, 1 symmetric
  shallow warm, 2 frontal deep warm, 3 frontal shallow warm, 4 frontal
  cold, 5 symmetric cold, 6 mid-level vortex (rare), blank not a closed
  low.
- Numbers: positive warm, negative cold, zero is the line for HVTL and
  HVTU; B at or below 10 m is symmetric, above 10 m frontal; HVTL, HVTU,
  and HB read in meters, HCPSidx is a dimensionless -3 to +3 index.
- Transition sequence: 0, then 2 (onset, B above 10), then 3 (upper
  warm core lost), then 4 (completion, HVTL negative). A warm seclusion
  runs 4 then back to 1. Read onset and completion from the animation.
  Cross-check against the thickness overlay.
- The square window footprint on the raw fields is a permanent design
  choice, not something waiting to be fixed.
- Always overlay MSLP and thickness.
