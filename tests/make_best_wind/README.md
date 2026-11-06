# Make_BestWind test

Offline check of `GFE/procedures/Make_BestWind.py` against the fake GFE in
`tests/blend_wind_gust_wave_pmsl/gfe_fakes.py` (numpy only):

    python3 test_make_best_wind.py

Covers the blend against a direct numpy computation of `rk.features.det_blend`
with 6 runs, a missing lagged run, one model missing (other used alone), both
missing (grid left unchanged), kt / m/s units, direction from the mean u/v of
the current runs, the lift ramps at 37/40/45/50/55 kt for both triggers, lift
Off = plain blend, the edit area (plain blend outside it), time
interpolation of a 6-hourly model, and the HF core option (skipped and said
when GFS 925 mb data are missing; ramp 52-56 kt only where 925 mb wind x
stability factor >= 55 kt), lagged runs Off (current runs only), no dependency
on `grid_fetch`, and the settings window (Cancel writes nothing; the window's
choices are used; a varDict skips it). The HF core check in the message
(inputs read, gate, cells raised; a quiet day; a units warning) is tested too.
The window and the pop-up need tkinter and were checked by hand under Xvfb.

GFE calls the procedure makes that are guesses to check on AWIPS:
`findDatabase` / `getGridInfo` for runs and inventory, `getGrids(...,
mode="First", noDataError=0)`, `getParm(...).getGridInfo().getUnitString()`,
`getTimeConstraints().constraintTimes(...)` (only when no Fcst Wind grid is in
the range), `MagDirToUV` / `UVToMagDir`, `encodeEditArea`, `empty()`,
`createGrid("Fcst", "Wind", "VECTOR", (mag, dir), tr)`; model element/level
pairs `wind FHAG10`, `wind 10FHAG`, `Wind SFC`; HF core: `wind MB925` / `925MB`,
`t SFC`, `t FHAG2` (GFS).
