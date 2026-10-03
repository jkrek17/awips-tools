# `CreateXML_WindHazards` checks

Two scripts, no dependencies beyond `numpy` and `matplotlib`:

```bash
python3 test_windhazard_xml.py      # the checks
python3 plot_synthetic_case.py      # a synthetic case, plotted from the XML
```

It exits non-zero on the first failing check and prints every check it ran.
Output XML lands in `out/`, which is gitignored - open it to see exactly what
PGEN will be handed.

## Why a harness

`GFE/procedures/CreateXML_WindHazards.py` only defines `Procedure` when
`AbsTime`, `TimeRange`, `A2GraphicsFunctions` and `A2GraphicsConfig` all
import (`_IN_GFE`), none of which exist outside AWIPS. So the script fakes the
minimum surface they provide - including an `XmlUtils` that builds a real
ElementTree, so the written XML can be parsed and asserted against - then
imports the procedure fresh against those fakes and drives
`Procedure.execute()` with a fully built `varDict`, the way GFE would.

The fake database holds a grid every N hours (6 by default, and the tests
vary it), answers `getGridInfo` with what is there, and returns a list from
`getGrids` when a range spans several grids - the way GFE does. It records
every call, which is what lets the tests assert *which* grids the procedure
reads, and that it reads the inventory rather than assuming a cadence.

## What the synthetic data is built to prove

A wind bullseye whose peak changes with forecast hour, with **both peaks at a
non-endpoint hour** of their period: 56 kt at F012 and 80 kt at F036, with
40-46 kt shoulders.

That shape is the test. A snapshot at either end of F000-024 would be 18 or
28 kt and produce no polygon at all, so a 34-48 *and* a 48-64 polygon for that
period can only come from a per-gridpoint maximum over the whole window.

F000-024 topping out at 56 kt is also why there must be **no**
`Hurricane_64+_F000-024` layer, while F024-048 at 80 kt gets all three bands.
The band labels (`34-47`, `48-63`, `64+`) match the Marine Weather Forecast
Viewer's warning legend and the colors are the marine warning convention
(yellow, orange, red), so either one drifting fails here rather than quietly
going its own way.

`pmsl` encodes the forecast hour in both the Low's value *and* its position -
the Low tracks northeast a gridpoint at a time - so the labels prove which grid
each plotted Low came from, and the track through them has a direction to
check. The High the field also carries must appear nowhere at all.

## Covered

- Cycle resolution: 20Z picks 18Z, 17:59Z picks 12Z, an explicit cycle that
  has not come round today steps back a day (including across a month end).
- `epochSeconds` is unaffected by the workstation's `TZ` (the reason the
  procedure uses `calendar.timegm` rather than `datetime.timestamp`).
- Polygon extraction: the bands overlapping rather than being cut out of each
  other (34-47 contains 48-63 contains 64+, and the 64+ ring is nested inside
  the gale one), `(lat, lon)` ordering, decimation, no duplicate closing
  point, nothing below threshold, and a single-gridpoint spike filtered out as
  noise *and reported* - nothing leaves the chart unannounced.
- The four layers, what lands in each, and the forecast hours actually read.
- Track building: a moving low making one track, two lows never confused for
  each other, a jump beyond the move limit breaking a track, a missing plot
  time widening the allowance instead of ending it, and a low seen once not
  being a track at all.
- The plot times following the pmsl inventory: a 12-hourly database giving
  12-hourly Lows, an hourly one thinned to 6-hourly rather than 49 Lows, a
  missing grid simply absent rather than warned about, no pmsl at all giving
  no Lows and no Track layer, and a site without `getGridInfo` falling back.
- The track being an open line, in the track color, with a vertex on every
  plotted Low.
- A site whose `plotPeakPressureLocations` hands back formatted strings
  (`"968"`, not `968.0`) rather than numbers - which used to break the
  track's pressure filter with a `TypeError`.
- The PGEN `Line` element's attributes, color child and `linePoints`.
- `Color by:` Threshold vs Period, and `Hatch fill:` On.
- The `Land` mask on and off, `saveLayers` false collapsing to one `Default`
  layer, a single selected period, no period selected, and missing `Wind` or
  `pmsl` grids.

## The synthetic case plot

`plot_synthetic_case.py` reuses the same fakes - `_installFakes` takes
`windFn`, `pmslFn`, `landFn` and `domain` overrides for exactly this - over a
North Atlantic case: a low deepening from 992 to 956 mb along a northeast
track, a second gale-only feature to the east, a High that must not be
plotted, and a coastline that doubles as the `Land` edit area, so the
polygons are clipped by the same outline the plot draws.

It runs the real procedure, then plots **the XML that run wrote**: every
polygon and every Low is parsed back out of the file, in the colors and line
patterns the XML itself carries. The shading behind them is the period-max
wind field recomputed for context. Vertices are drawn raw - PGEN renders them
with `smoothFactor`, so the real chart comes out smoother.

```bash
python3 plot_synthetic_case.py                     # default Band coloring
python3 plot_synthetic_case.py --color-by Period --hatch
```
