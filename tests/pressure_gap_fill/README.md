# Gap fill checks

```bash
python3 test_pressure_gap_fill.py     # the PressureGapFill module on its own
python3 test_createxml_gapfill.py     # the site's CreateXML.py, end to end
python3 plot_gap_fill.py              # a synthetic WPAC case, drawn from the XML
python3 plot_tc_match.py              # a typhoon matched to its warning, Off vs On
```

No dependencies beyond `numpy` and `matplotlib`. Output lands in `out/`, which
is gitignored.

## The fake DataAccessLayer

`test_pressure_gap_fill.py` holds a fake DAL that serves analytic pmsl fields
per model location (`gfs0p25`, `ecmwf0p25`, ...), answers
`getAvailableParameters`, `getAvailableLevels` and `getAvailableTimes` the way
the real one does, builds each grid over the envelope it is asked for, and
records every request - so the tests can check what was asked for as well as
what came back.

## What is covered

- **Regridding and blending** - a linear field regrids exactly, a model with
  no data at a point is left out of the mean rather than counted as zero. A
  lat/lon source takes the fast bilinear path, also when two envelopes share
  the dateline column; a projected one is never mistaken for it and goes
  through the triangulation.
- **The seam** - on the GFE grid's edge the gap equals the forecaster's grid;
  `SEAM_FADE_DEG` south of it the models are untouched.
- **The dateline** - a `-180..180` Pacific grid gives two pieces that share
  the 180 column so contours meet; a `0..360` grid gives one piece in `0..360`.
  Either way the DAL is asked for each side of the dateline separately, and
  every result comes back in the GFE grid's own longitude convention.
- **Tropical cyclones** - a typhoon in the gap keeps its center and full depth
  (the seam correction never reaches it), one sitting on 180 is a single Low,
  and centers hard against the seam are left to the GFE grid.
- **Matching the warning** - a typhoon the models put 200 nm off comes out at
  the warning position at the warning's pressure, with nothing of the
  models' vortex left (against the same storm put into a model that never had
  one), the seam still matched, and the report saying where the models had
  it. A storm far from the gap changes nothing. One in the GFE grid just
  north is reported as the grid's, and when the grid has it too, the seam has
  almost nothing left to correct: 0.01 mb, against 3.2 mb when the models
  are not moved. Across the dateline, the storm lands east of 180 and is
  reported in the warning's own longitudes.
- **The DAL** - `PRMSL` at `0.0SFC` is found when `PMSL` at `0.0MSL` is not;
  the newest run valid at the chart's time wins; Pa become mb, mb are left
  alone.
- **Nothing breaks the chart** - no run, no pmsl, an unknown model, no models
  picked, or a grid that already reaches 17N all give an empty gap, never an
  exception, with the reason recorded.

`test_createxml_gapfill.py` runs the real `CreateXML.execute()` against fakes
of `A2GraphicsFunctions` and `A2GraphicsConfig` whose `makePressureContours`
contours for real with matplotlib. It checks that isobars now run to 17N, that
**every GFE isobar meeting the 30N seam is met by a gap isobar of the same
value** - and that the same check fails with seam matching switched off, so it
is not vacuous - that a hurricane in the gap gets one Low at the model's
position and depth, that `Off` and "no model available" both leave the chart
exactly as before, that an older dialog without the new rows still runs, and
that a typhoon on the dateline is one Low with isobars on both sides. With a
warning in the fake text database, the gap's Low is drawn at the warning
position at its central pressure and the status bar says what was moved.
With `Match TC warnings: Off`, the same chart keeps the model's Low and says
nothing about warnings.
