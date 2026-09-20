# Seven-minute talk: Cyclone Phase Space in AWIPS

About 1200 words, ten slides, roughly 170 words a minute. Timings are
cumulative. Slide cues are in brackets. The deck is `TALK.pptx` beside
this file; the same text is in each slide's speaker notes. To give it
in five minutes, skip slides 4 and 5 and say only the first paragraph
of slide 3.

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

**[Slide 3, the thermal wind terms] 1:04**

Here is what the thermal wind terms measure. Take a cross-section
through a storm: the height of a pressure surface dips over the low.
In a warm-core storm, a hurricane, the column is warm and thick, so
the dip is deepest at the surface and fills in with altitude; the
pressure surfaces flatten out aloft. In a cold-core low the column is
cold and thin, so the dip deepens with altitude and the trough is
strongest at the top.

Hart measures that with one number per level: the height range inside
the circle, max minus min, then how that range changes with height.
Shrinking upward is warm core, positive; growing upward is cold core,
negative. He does it twice, lower and upper troposphere, and that
split tells a hurricane, warm all the way up, from a subtropical storm
or warm seclusion, warm only in the lower layer.

**[Slide 4, parameter B] 1:53**

The third number, B, is about the environment rather than the core.
Thickness between two pressure levels measures a layer's mean
temperature. The motion here is the deep-layer mean wind, averaged
over that same 500 kilometer window: inside a symmetric vortex the
storm's own circulation cancels out, leaving the environmental flow,
with a floor of 2 meters per second. Split the circle left and right
of that flow and subtract the mean thickness of the two halves.

For a hurricane both halves are the same and B is near zero. For a
storm that has moved into a front, warm air sits on one flank and cold
on the other, and B is large. Hart's threshold is 10 meters. Onset is
read as the frame HB crosses 10 meters, completion as the frame HVTL
crosses zero, from animating those two fields; HCPSclass is just the
summary.

**[Slide 5, the two diagrams] 2:41**

Put those together and you get Hart's two diagrams. On the left, B
against the lower thermal wind: symmetric or frontal, warm or cold. On
the right, lower against upper thermal wind: deep warm, shallow warm,
or cold. A hurricane starts in the deep warm corner; during transition
it crosses the B line first, loses the upper warm core, then the lower
one, and ends in the cold corner. Some storms hook back toward shallow
warm core: a warm seclusion re-forming a warm core at the surface, the
ones that deepen unexpectedly over cold water. The product we built
turns all three numbers into one, so a forecaster reads a single class
instead of two diagrams. For a marine center, transition is when the
wind field expands, so these crossings are the forecast question.

**[Slide 6, what we built] 3:26**

Until now, operational access was the FSU cyclone phase page:
storm-centered diagrams for tracker-identified cyclones, in a fixed
set of models, outside the workstation. What OPC needs is the same
diagnostic inside D2D, on every model we run, for any low we point at.

We reformulated the parameters as gridded fields and implemented them
as AWIPS derived parameters. At every grid point the code evaluates the
height range inside a 500 kilometer window at each level and regresses
it against log pressure: Hart's own definition, evaluated everywhere
instead of at one tracked center. The square window and standard
levels keep the magnitudes close to his, not identical. It needs
geopotential height on standard levels and surface pressure; the
frontal term also needs winds at four levels. That runs on any model
in D2D carrying those fields, with no tracker and no advisory. A
closed-low detector on the 1000 hPa height keeps the class off open
ocean and open troughs in the cases we've tested, and terrain is
masked below ground.

**[Slide 7, a tilted cold core] 4:23**

Here is why measuring the height field directly matters, on a
synthetic case. Build a cold-core cyclone whose upper trough sits 393
kilometers west of its surface center, tilted the way many real
baroclinic lows are, under a uniform 8 meter per second westerly
steering flow. One panel shows that geometry: the 925 and 300
hectopascal height contours, offset by the tilt. The others show the
upper thermal wind term and the joint class. Hart's 500 kilometer
window is wide enough to take in the tilted upper trough from the
surface center, so both thermal wind terms read strongly cold there,
HVTL minus 285 meters and HVTU minus 284, and the class comes out 5,
symmetric cold core, right where the surface low sits.

**[Slide 8, on shift] 5:02**

This is the operational display: four fields, HVTL, HVTU, the joint
class, and the index. The capture is the 48 hour frame of the 20
September run, the storm east of Japan at 976 millibars, class 3,
with B at 36, the lower term at 114 and the upper at minus 102. The class reads at the
storm's center, one number for one of seven classes built from Hart's
two diagrams: symmetric or frontal, deep or shallow warm core, cold
core, or shallow cold core, lower cold and upper warm, a rare state.
Step through the frames on a transitioning storm and the class climbs
0, then 2, then 3, then 4; a warm seclusion runs it from 4 to 3, or to
1 if B falls too. Load a second model beside it and compare the hour
each HB crosses 10 meters and each HVTL crosses zero; where they
disagree is your transition uncertainty. That's not something we've
had inside our own workstation before, because it needed a tracker
for every model.

**[Slide 9, validation] 5:49**

The headline case is one typhoon carried through the whole life cycle
in the 20 September 0600 UTC GFS, with all four products sampled at the
center each day. Deep warm core at 0 hours: lower term 128, upper 176,
B 6 meters. By 24 hours B is 13, past onset, both cores still warm. By
48 hours the upper core is gone, minus 102. By 72 hours the lower core
is down to 22 with B at 46. Then the seclusion: at 96 hours the lower
term is back to 241 with the upper still at minus 295 and B down to
half a meter, symmetric shallow warm core, class 1, at 976 millibars.
Hart's own diagrams for this storm trace the same path, and the
cold-phase upper term, minus 290, matches his minus 300. The
seclusion's lower term is about twice his, in the direction our bands
and window predict. One frame at 120 hours reads class 6 with an upper
term of plus 3 meters, which is zero for practical purposes: a
threshold artifact, and the honest reading is class 4. Compute cost is
about 2.6 seconds per forecast hour on the full global grid, the
median of four runs, ranging 2.4 to 3.0 seconds.

**[Slide 10, limits and next] 6:33**

Honest limits: we use standard levels, not Hart's 50 hectopascal
spacing, so magnitudes are near his but not identical. The window is a
square, which carries a small cold bias on a strong gradient. B and the
transition-onset field are implemented but not yet validated. And it's
three cases, not a season.

Next is a season of use, a model-comparison product for transition
timing, and a storm-centered diagram inside GFE. The package, guides,
and tests are in the repository. Questions.

**7:00**
