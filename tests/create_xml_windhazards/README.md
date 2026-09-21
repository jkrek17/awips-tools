# `CreateXML_WindHazards` checks

One script, no dependencies beyond `numpy` and `matplotlib`:

```bash
python3 test_windhazard_xml.py
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

The fake `getGrids` records every `(field, forecast hour)` it is asked for,
which is what lets the tests assert *which* grids the procedure reads.

## What the synthetic data is built to prove

A wind bullseye whose peak changes with forecast hour, with **both peaks at a
non-endpoint hour** of their period: 56 kt at F012 and 80 kt at F036, with
40-46 kt shoulders.

That shape is the test. A snapshot at either end of F000-024 would be 18 or
28 kt and produce no polygon at all, so a gale *and* storm polygon for that
period can only come from a per-gridpoint maximum over the whole window.
F000-024 topping out at 56 kt is also why there must be **no**
`Hurricane_F000-024` layer, while F024-048 at 80 kt gets all three.

`pmsl` encodes the forecast hour in its High and Low values, so the labels in
each `Features` layer prove the grid came from that period's **start** time
(F000 and F024), not anywhere else.

## Covered

- Cycle resolution: 20Z picks 18Z, 17:59Z picks 12Z, an explicit cycle that
  has not come round today steps back a day (including across a month end).
- `epochSeconds` is unaffected by the workstation's `TZ` (the reason the
  procedure uses `calendar.timegm` rather than `datetime.timestamp`).
- Polygon extraction: nesting (gale area > storm > hurricane), `(lat, lon)`
  ordering, decimation, no duplicate closing point, nothing below threshold,
  and a single-gridpoint spike filtered out as noise.
- Layer set per period, and the forecast hours actually read.
- The PGEN `Line` element's attributes, color child and `linePoints`.
- `Color by:` Threshold vs Period, and `Hatch fill:` On.
- The `Land` mask on and off, `saveLayers` false collapsing to one `Default`
  layer, a single selected period, no period selected, and missing `Wind` or
  `pmsl` grids.
