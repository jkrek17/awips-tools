# Five-minute talk: Cyclone Phase Space in AWIPS

About 680 words, seven slides, roughly 40 seconds each. Timings are
cumulative. Slide cues are in brackets. The deck is `TALK.pptx` beside
this file; the same text is in each slide's speaker notes.

---

**[Slide 1, title] 0:00**

I want to show you a tool that tells you what kind of cyclone a model
is forecasting, not just where it is or how deep. It runs inside AWIPS,
on every model we ingest, with nothing external.

**[Slide 2, the phase space] 0:40**

The science is Bob Hart's cyclone phase space from 2003. It describes
a cyclone with three numbers from the height field alone. Two are
thermal wind terms, lower and upper troposphere, which say whether the
core is warmer or colder than its surroundings. Positive is warm core,
a hurricane. Negative is cold core, an extratropical low. The third,
B, measures the temperature contrast across the storm's track, which is
whether it's frontal.

Plotted against each other, a storm traces a path. A hurricane starts
in the deep warm core corner. During extratropical transition it loses
the upper warm core, then the lower one, and ends up cold core. Evans
and Hart showed the crossings give objective onset and completion times
for transition. And transition is when the wind field expands, so for a
marine center this is the forecast question.

**[Slide 3, what we built] 1:30**

Until now the only operational access was FSU's web page: static plots,
computed externally, for tracked tropical cyclones only. The hybrid,
post-tropical, and non-tropical systems that OPC actually warns on
aren't on it.

We reformulated the parameters as gridded fields and implemented them
as AWIPS derived parameters. At every grid point, the code takes the
height range inside a 500 kilometer window at each level and regresses
it against log pressure. That is Hart's exact quantity, evaluated
everywhere instead of at one tracked center. It needs only geopotential
height on standard levels, surface pressure, and winds, so it works on
every model in D2D with no tracker and no advisory. A closed-low
detector on the 1000 hPa height blanks everything that isn't a real
low, and terrain is masked below ground.

**[Slide 4, why not the shortcut] 2:20**

We tried a cheaper version first, differencing vorticity between
levels. It fails in a specific way worth knowing. A baroclinic low is
tilted: its upper trough sits west of the surface center. At the
surface low the upper vorticity is weak, so the proxy reads warm, and
the cold signal shows up displaced to the west as a dipole. Hart's
window spans the tilt and reads cold at the center. This figure is that
comparison on a synthetic tilted low: the proxy near zero at the
center, the Hart field at minus 285 meters.

**[Slide 5, on shift] 3:00**

This is the operational display. Four panels: the lower and upper
terms, a category field, and an index. The category reads at the
storm's center: 4 is deep warm core, 3 shallow, 1 cold, blank means no
closed low. Step through the frames and the first hour the category
leaves 4 is the loss of the deep warm core. Load a second model beside
it and where they disagree on that hour is your transition uncertainty.
That is a product nobody had before, because it needed a tracker for
every model.

**[Slide 6, validation] 3:50**

Three checks so far. A typhoon at 984 millibars read 120 and 180
meters, class 4, squarely in the range Hart published for hurricanes.
For Typhoon Dujuan, the hour our class dropped below 4 matched the hour
FSU's page showed the same GFS run moving from deep to shallow warm
core. And a deep North Atlantic low classified cold core, which the
vorticity shortcut could not do. Greenland and the Rockies come out
blank rather than contaminated. Compute cost is about a second per
frame on the full global grid.

**[Slide 7, limits and next] 4:30**

Honest limits: we use standard levels, not Hart's 50 hectopascal
spacing, so magnitudes are near his but not identical. The window is a
square, which carries a small cold bias on a strong gradient. B and the
transition-onset field are implemented but not yet validated. And it's
three cases, not a season.

Next is a season of use, a model-comparison product for transition
timing, and a storm-centered diagram inside GFE. The package, guides,
and tests are in the repository. Questions.

**5:00**
