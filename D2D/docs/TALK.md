# Seven-minute talk: Cyclone Phase Space in AWIPS

About 1000 words, ten slides. Timings are cumulative. Slide cues are in
brackets. The deck is `TALK.pptx` beside this file; the same text is in
each slide's speaker notes. To give it in five minutes, skip slides 4
and 5 and say only the first paragraph of slide 3.

---

**[Slide 1, title] 0:00**

I want to show you a tool that tells you what kind of cyclone a model
is forecasting, not just where it is or how deep. It runs inside AWIPS,
on every model we ingest, with nothing external.

**[Slide 2, the phase space] 0:35**

The science is Bob Hart's cyclone phase space from 2003. It describes
a cyclone with three numbers from the height field alone, all taken
inside a 500 kilometer circle around the center. Two are thermal wind
terms, one for the lower troposphere and one for the upper, and they
say whether the core is warmer or colder than its surroundings. The
third, B, says whether the storm is frontal. Together they place any
cyclone on a diagram, and a storm traces a path through it as it
evolves.

**[Slide 3, the thermal wind terms] 1:10**

Here is what the thermal wind terms actually measure. Take a
cross-section through a storm. The height of a pressure surface dips
over the low. In a warm-core storm, a hurricane, the column is warm, so
it is thick, so the dip is deepest at the surface and fills in with
altitude. The pressure surfaces flatten out aloft. In a cold-core low
the column is cold and thin, so the dip deepens with altitude and the
trough is strongest at the top.

Hart measures that with one number per level: the height range inside
the circle, max minus min. Then he looks at how that range changes with
height. Shrinking upward is warm core, positive. Growing upward is cold
core, negative. He does it twice, once for the lower troposphere and
once for the upper, and that split is what lets you tell a hurricane,
warm all the way up, from a subtropical storm or a warm seclusion,
which is warm only in the lower layer.

**[Slide 4, parameter B] 2:15**

The third number, B, is about the environment rather than the core.
Thickness between two pressure levels is a measure of the mean
temperature of the layer. Draw the 500 kilometer circle around the
storm, split it into left and right of the direction of motion, and
subtract the mean thickness of the two halves.

For a hurricane the thickness contours close around the storm, both
halves are the same, and B is near zero. For a storm that has moved
into a front, warm air sits on one flank and cold air on the other, and
B is large. Hart's threshold is 10 meters. Evans and Hart use the hour
B first exceeds it as the objective onset of extratropical transition,
and the hour the lower thermal wind turns negative as completion.

**[Slide 5, the two diagrams] 2:55**

Put those together and you get Hart's two diagrams. On the left, B
against the lower thermal wind: symmetric or frontal, warm or cold. On
the right, lower against upper thermal wind: deep warm, shallow warm,
or cold. A hurricane starts in the deep warm corner. During transition
it crosses the B line first, then loses the upper warm core, then the
lower one, and ends in the cold corner. Some storms then hook back
toward shallow warm core: that is a warm seclusion re-forming a warm
core at the surface, and those are the ones that deepen unexpectedly
over cold water. The operational product we built turns all three
numbers into one, so a forecaster reads a single class instead of two
diagrams. For a marine center, transition is when the wind field
expands, so these crossings are the forecast question.

**[Slide 6, what we built] 3:50**

Until now the only operational access was FSU's web page: static plots,
computed externally, for tracked tropical cyclones only. The hybrid,
post-tropical, and non-tropical systems that OPC actually warns on
aren't on it.

We reformulated the parameters as gridded fields and implemented them
as AWIPS derived parameters. At every grid point the code evaluates the
height range inside a 500 kilometer window at each level and regresses
it against log pressure. That is Hart's exact quantity, everywhere
instead of at one tracked center. It needs only geopotential height on
standard levels, surface pressure, and winds for the motion in B, so it
works on every model in D2D with no tracker and no advisory. A
closed-low detector on the 1000 hPa height blanks everything that isn't
a real low, and terrain is masked below ground.

**[Slide 7, why not the shortcut] 4:35**

We tried a cheaper version first, differencing vorticity between
levels. It fails in a specific way worth knowing. A baroclinic low is
tilted: its upper trough sits west of the surface center. At the
surface low the upper vorticity is weak, so the proxy reads warm, and
the cold signal shows up displaced to the west as a dipole. Hart's
window spans the tilt and reads cold at the center. On a synthetic
tilted low the proxy reads near zero at the center and the Hart field
reads minus 285 meters.

**[Slide 8, on shift] 5:10**

This is the operational display. Four panels: the lower and upper
terms, a joint class field, and an index. The class reads at the
storm's center, one number for one of Hart's seven named states:
symmetric or frontal, deep or shallow warm core, cold core, or a rare
mid-level vortex. Step through the frames on a transitioning storm and
the class climbs 0, then 2, then 3, then 4; a warm seclusion runs 4 and
back to 1. Load a second model beside it and compare the hour each
first reaches 2 or 3, and the hour each first reaches 4 or 5; where
they disagree is your transition uncertainty. That is a product nobody
had before, because it needed a tracker for every model.

**[Slide 9, validation] 5:55**

Three checks so far. A typhoon at 984 millibars read 120 and 180
meters, a deep warm core (class 4 in our earlier two-field product,
class 0 or 2 in the joint field depending on B), comparable to what
Hart published for hurricanes. For Typhoon Dujuan, the hour the
storm's classification left its deep warm core state matched the hour
FSU's page showed the same GFS run moving from deep to shallow warm
core. And a deep North Atlantic low classified cold core, which the
vorticity shortcut could not do. Greenland and the Rockies come out
blank rather than contaminated. Compute cost is about a second per
frame on the full global grid.

**[Slide 10, limits and next] 6:35**

Honest limits: we use standard levels, not Hart's 50 hectopascal
spacing, so magnitudes are near his but not identical. The window is a
square, which carries a small cold bias on a strong gradient. B and the
transition-onset field are implemented but not yet validated. And it's
three cases, not a season.

Next is a season of use, a model-comparison product for transition
timing, and a storm-centered diagram inside GFE. The package, guides,
and tests are in the repository. Questions.

**7:00**
