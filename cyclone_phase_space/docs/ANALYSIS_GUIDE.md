# Cyclone Phase Space in D2D: Surface Analysis Guide

For analysts. The User Guide explains how to load and read the five
Hart CPS products on shift. This guide is narrower: how to use them
while drawing a surface analysis. None of it replaces the analyst.
Every technique here is a check or a cue that feeds the judgment you
already make from satellite, observations, MSLP and thickness.

**Status: experimental.** These techniques follow from what the
products measure and from one typhoon life cycle checked against the
Florida State phase diagrams. None has been scored against a season of
OPC hand analyses. Treat them as a second opinion until that is done.

---

## 1. What the fields say, in analyst terms

- **HB** is the 900 to 600 hPa thickness gradient across the
  deep-layer flow, averaged over a 1000 km square and scaled to Hart's
  units. On a global map it paints the low-level baroclinic zones red.
  Bright red inside a red band is where the gradient is concentrated,
  which is where a surface front lives. It is a map of thermal
  contrast, not a front locator: the averaging blurs a 100 km front
  into a band several hundred kilometers wide.
- **HVTL and HVTU** say whether the core of a low is warm or cold in the
  lower and upper troposphere. Positive is warm.
- **HCPSclass** combines the three at each closed low. It is the field
  that tells you what kind of low you are drawing.
- **HCPSidx** is one number from +3 (hurricane) to minus 3 (deep cold
  low), for wording and for model comparison.

HB is a full field. HVTL, HVTU, HCPSclass and HCPSidx are only meaningful
at closed-low centers, and the class is blank away from them.

---

## 2. What to load

Two panels cover the analysis uses.

1. **HB** as image with CPS_CoreDiverging, range about minus 50 to
   +50 m, with MSLP contours and 10 m wind barbs. Add 1000 to 850 hPa
   thickness if the panel is not too busy.
2. **HCPSclass** as image with CPS_HartClass, range minus 0.5 to 6.5,
   with MSLP contours.

Use the analysis-time frame of the model you are analyzing against,
and keep the previous 6 and 12 h frames a click away for trends.

---

## 3. Techniques

### 3.1 Type the low before you draw fronts through it

Sample HCPSclass at the MSLP center. The class decides the frontal
geometry you draw.

| Class | Read as | Fronts |
| :--- | :--- | :--- |
| 0 symmetric deep warm core | tropical cyclone | none |
| 2 asymmetric deep warm core | tropical cyclone meeting a front | first front appears; onset of transition |
| 3 asymmetric shallow warm core | transition under way | warm and cold front, upper core gone |
| 4 asymmetric cold core | extratropical low on a front | warm and cold front, occluding |
| 5 symmetric cold core | mature occluded low | occluded front spiraling into the center (Norwegian) |
| 1 symmetric shallow warm core | warm seclusion | bent-back warm front, fractured cold front, T-bone (Shapiro-Keyser) |
| 6 shallow cold core | rare; lower cold, upper warm | treat as 4 or 5 and check the numbers |

The class 1 call is the one worth the most. A warm seclusion has the
warm air wrapped into the center, so the front near the center is a
bent-back warm front around the poleward side and the cold front is
fractured to the east, not a spiral. That geometry is judged from
satellite and thickness by eye today; the class gives it a number.

### 3.2 The post-tropical handoff

When a tropical cyclone is transitioning, the analysis switches from a
tropical symbol with no fronts to an extratropical low with fronts.
Hart's parameters are the framework NHC uses for that call.

- **Onset**, HB at the center crossing above 10 m: the first front can
  be drawn to the low. In practice the class turns yellow (2).
- **Completion**, HVTL at the center crossing below zero: the low is
  cold core throughout and the tropical symbol goes. The class turns
  blue (4) or indigo (5).

Read both hours from the animation and cross-check against thickness.
Expect them one to two frames later than the Florida State page would
show for the same run; the page also applies a 24 h running mean, so
its trajectory is smoother than the frame-by-frame class.

### 3.3 Thermal support for a drawn front

Overlay HB on the surface analysis with the 10 m winds.

- A drawn front with HB near zero along its length has no low-level
  thermal contrast under it. It is either a trough drawn as a front, a
  front that has weakened past keeping, or a front whose contrast is
  shallower than 900 hPa. Look again before keeping it.
- A strong red band with no front drawn on it is either a front you
  have not found, or a baroclinic zone that has not yet made a surface
  front. The wind barbs decide: a wind shift along the band says front,
  no shift says zone.
- The band is wider than the front. Draw the front on the wind shift
  and the observations, inside the band, not on the band's center.

### 3.4 Where the occlusion ends and when to drop a front

Around a mature low, HB falls toward zero where the warm and cold air
have wrapped into symmetry. That is the region where the occluded
front runs into the center and stops. When the class at the center
reads 5, the occlusion process is complete and the front should not be
drawn much past the center.

Along a front's length, compare HB at the front on consecutive frames.
Rising HB is frontogenesis; falling HB is frontolysis. A front whose HB
has fallen under about 10 m and is still falling is a candidate for the
dissipating symbol and then for dropping. Use the trend over two or
three frames, not one value.

### 3.5 Secondary lows on a front

The closed-low detector picks up every low with about 5 hPa of relief.
For a new low on the chart:

- On a front, class 4 (asymmetric cold core): a frontal wave. Draw it on
  the front with the front passing through.
- Off the front, class 5 (symmetric cold core): a cut-off or cold low.
  Draw it without fronts, or with a weak occlusion if the thickness
  supports one.
- Anywhere, class 0 or 2 with HVTL well above +50 m: check whether it
  is tropical or subtropical before drawing it as an ordinary low.

### 3.6 Wording

HCPSidx gives a continuous number for products that must say
tropical, subtropical, post-tropical or extratropical. Above +2 is a
hurricane-type warm core, near zero is transitional, below minus 1 is
an ordinary extratropical low. Compare the same index between two
models at the same hour to see how confident to be in the wording.

### 3.7 Lower and upper baroclinicity from HVTL and HVTU

Away from a closed low the two thermal wind terms are not blank, and
they are not noise. With no vortex in the window, the height range the
window sees is the large-scale gradient times the window's width, and
in a baroclinic zone that gradient grows with height. So the range
grows with height, and the term, which is the slope of the range
against log pressure, comes out negative. Its size is the layer's
thermal wind magnitude scaled to the window: a 925 to 700 hPa thickness
gradient of 40 m per 1000 km reads about minus 140 m on HVTL. That is
the same order as a cold-core low, which is why the environment matters
so much inside a storm's window.

Read the two fields away from lows as baroclinicity maps:

- **Blue HVTL** is the low-level baroclinic zone: fronts and the polar
  front region as the 925 to 700 hPa layer sees them.
- **Blue HVTU** is the upper-level baroclinic zone: the thermal wind
  under the jet in the 500 to 300 hPa layer. It follows the jet axis.
- **Blue HVTL with transparent HVTU** is a shallow front: an arctic
  front, a coastal front, a low-level baroclinic zone with no jet above.
- **Blue HVTU with transparent HVTL** is an elevated baroclinic zone
  with no surface front: a jet crossing warm-sector or subtropical air,
  or a front that has lifted off the surface.
- **Red away from a low** means the gradient weakens with height, so
  the geostrophic wind weakens with height through the layer: a
  shallow cold high, a cold dome, or a low-level jet that fades aloft.
- **Red HVTL with blue HVTU** is a shallow cold air mass under an
  upper-level baroclinic zone: cold-air damming or an arctic high with
  the jet overhead, or the cold side of a warm front where warm air is
  overrunning the dome. It is the overrunning signature, and in winter
  it marks where freezing spray and frozen precipitation sit under
  warm advection aloft. At a closed-low center the same pair is a
  shallow warm core, class 1 or 3, which is a different thing: read
  the class there, not the pair.

The most useful analyst move is to read a storm's core term relative
to its surroundings. If HVTL reads minus 150 m in the baroclinic zone
next to a low and minus 100 m at the low's center, the low's own core
is warm by about 50 m relative to its environment even though the
center reads cold. Hart's classes use the raw value, by design, so the
class stays as it is; the relative reading tells you whether an intact
warm core is still there under the trough, which bears on how long the
core winds persist.

### 3.8 Not yet available: warm front versus cold front

HB keeps only the part of the thickness gradient across the flow. The
part along the flow is the sign of layer-mean thermal advection, which
separates the warm-front side from the cold-front side. That component
is not in the installed product. It is on the list of candidate
extensions and would be two more fields from the same inputs.

---

## 4. Feature catalog

What each synoptic feature looks like on the three fields, with the
class where a closed low is present. Colors are for the shipped ranges
(HVTL and HVTU plus or minus 300 m, HB plus or minus 40 m): "red" and
"blue" mean solid color, "pale" the fading band, "clear" the
transparent band near zero. Read the class only at a closed low; read
HVTL, HVTU and HB anywhere.

### 4.1 At a closed low

| Feature | HVTL | HVTU | HB | Class | What to look for |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Hurricane or typhoon | red, +100 to +300 | red, +100 to +250 | clear | 0 | tight MSLP, no fronts; index above +2 |
| Tropical cyclone meeting a front | red | red | red, 10 to 30 | 2 | onset; first front to the low |
| Transitioning tropical cyclone | red, falling | blue | red, 30 to 50 | 3 | upper core gone; warm and cold fronts |
| Extratropical low on a front, frontal wave | blue | blue | red | 4 | the everyday developing low |
| Mature occluded low, Norwegian type | blue | blue | clear or pale | 5 | occlusion spirals to the center |
| Warm seclusion, Shapiro-Keyser type | red, +50 to +250 | blue | clear | 1 | bent-back warm front, fractured cold front, T-bone; often the wind peak |
| Cut-off low, cold low | blue | blue, strongly | clear | 5 | sits off the jet; slow moving; no surface fronts or weak ones |
| Subtropical storm, hybrid | pale red, +30 to +80 | clear or pale blue | pale, under 10 | 1 or 3 | index near +0.5 to +1; wording call |
| Weak tropical depression | pale red | pale red | clear | 0, or blank | may fall under the 5 hPa detector floor |
| Polar low | pale red | blue | clear | 1, or blank | small; the window smooths it and the detector may miss it |
| Lee low, thermal low | red | clear or blue | pale | 1, or blank | near terrain the mask blanks it; check surface pressure |

### 4.2 Away from lows

| Feature | HVTL | HVTU | HB | What to look for |
| :--- | :--- | :--- | :--- | :--- |
| Surface front, low-level baroclinic zone | blue band | any | red band | the front sits on the wind shift inside the band |
| Polar jet axis | any | blue band | pale or red | follows the jet; the upper thermal wind |
| Deep baroclinic zone, front under the jet | blue | blue | red | the main polar front; the storm track |
| Shallow front: arctic, coastal, marine | blue | clear | red or pale | no jet above; often sharp and short |
| Elevated baroclinic zone, jet over the warm sector | clear | blue | pale | no surface front; a lifted or upper front |
| Cold dome under the jet, overrunning | red | blue | pale or red | cold-air damming, arctic high under warm advection; freezing spray and frozen precipitation in winter |
| Shallow cold high, arctic high | red | clear | clear | the high fades aloft |
| Warm subtropical high, ridge | pale blue | pale blue | clear | the ridge builds aloft; weak signal |
| Warm sector, tropical air | clear | clear | clear | nothing to see, which is the point |
| Open trough, no closed low | blue along the axis | blue | red flanks | class blank; the fields still show the trough's structure |
| Easterly flow along a front, north side of a block | any | any | blue | warm air on the left of the flow; check the steering |

### 4.3 In the animation

- **Frontogenesis:** HB rising along a band frame to frame; the band
  narrows and brightens.
- **A storm entering the baroclinic zone:** HVTU at the center turns
  from red to blue while HVTL stays red, and HB rises through 10 m.
  The class walks 0, 2, 3.
- **Occlusion:** HB at the center falls toward zero while both terms
  are blue. The class goes 4 to 5.
- **Seclusion:** HVTL at the center turns back to red while HVTU stays
  blue and HB stays near zero. The class goes 5 or 4 to 1.
- **A front lifting off the surface:** HVTL under the band fades while
  HVTU stays blue.
- **A cold dome eroding:** red HVTL under the jet fades to clear as the
  low levels warm.

## 5. Cautions specific to analysis

- **The thresholds mean nothing away from a low.** Along a
  baroclinic zone HB can read 40 m or more and HVTL minus 150 m with no
  low anywhere. Hart's tests are for a storm, applied at the storm's
  center; away from lows the fields are environment maps (sections 3.7 and 4).
- **Blue HB is a flag, not a finding.** Negative HB means the warm air
  is on the left of the deep-layer flow. That is real for easterly flow
  along a front, for the north side of a block and for some seclusions.
  It is also what you get when the deep-layer steering points against
  the low's actual motion, which swaps left and right. Check the 850 to
  300 hPa mean flow before reading anything into blue.
- **HB under-reads a storm's own asymmetry.** For a thickness
  asymmetry confined to the storm scale it reads about 60% of Hart's
  value, which is why onset can trail the Florida State page by a
  frame or two. It reads a broad environmental gradient in full.
- **The window blurs everything.** Two fronts closer than about 500 km
  merge into one band. A short front segment reads weaker than a long
  one of the same strength.
- **Below-ground blanking.** HB is blank over Greenland and high
  terrain, and HVTL, HVTU and the class can be blank within a few
  hundred kilometers of them. A missing class near Greenland is the
  mask, not a finding.
- **Flicker.** The class alternates between neighboring codes when a
  low sits on a threshold. Read the trend over frames and read the
  numbers underneath.

---

## 6. Worked example

The 2026 September 20 0600 UTC GFS carried a western Pacific typhoon
through its transition, sampled at the center each day.

| Hour | HVTL | HVTU | HB | Class | Analysis reading |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | +128 | +176 | 6 | 0 | tropical cyclone, no fronts |
| 24 | +107 | +147 | 13 | 2 | onset; draw the first front to the low |
| 48 | +114 | minus 102 | 36 | 3 | upper core gone; warm and cold fronts |
| 72 | +22 | minus 284 | 46 | 3 | lower core nearly gone; occluding |
| 96 | +241 | minus 295 | 0.5 | 1 | warm seclusion at 976 hPa; bent-back front, T-bone |
| 120 | minus 33 | +3 | 20 | 6 (read as 4) | decaying extratropical low |

The 24 h frame is where the tropical symbol gains its first front, the
72 h frame is where the tropical symbol would be dropped by the
completion rule, and the 96 h frame is the Shapiro-Keyser call: the
front near the center is drawn bent back around the poleward side,
not spiraled in. The Florida State diagrams for this run trace the
same path.

---

## 7. Checklist

Before the analysis goes out:

- [ ] Every closed low has been sampled for its class, and the frontal
      geometry drawn through it matches the class.
- [ ] Every transitioning tropical cyclone has an onset and a
      completion hour read from HB and HVTL, and the symbol and fronts
      follow those hours.
- [ ] Every drawn front sits inside a red HB band, or has a reason not
      to.
- [ ] Every strong HB band without a front has been checked against the
      wind barbs.
- [ ] Fronts marked dissipating have falling HB over two or more frames.
- [ ] Any blue HB near a low has had its steering direction checked.

---

## 8. Document set

- `USER_GUIDE.md`: loading and reading the products on shift.
- `TECHNICAL_GUIDE.md`: method, tunables, install, limitations.
- `../README.md`: overview, validation log, acceptance criteria.
- The article at `../article/index.html` (published under `cps/` on
  the GitHub Pages site): method, results, limitations.
