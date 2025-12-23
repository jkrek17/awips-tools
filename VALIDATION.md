# Validation Playbooks

This document captures regression scenarios for the new modular Smart
Tool architecture. Each scenario should be run in the AWIPS/GFE training
environment whenever utilities or Smart Tools change.

## 1. `GFE/smarttools/model_wx2.py`
- Run the tool twice with different model selections (`GFS` only, then
  `GFS + ECMWF`) to confirm the DAL wrapper hydrates QPF/CAPE via the
  alias registry.
- Temporarily disable the current run of a model (rename the database or
  use the previous cycle) and verify the fallback logic surfaces the
  status-bar message but continues with remaining models.
- Inspect the diagnostic popup to ensure QPF values are logged in inches
  (shared conversion helpers) and CAPE logs no longer reference the
  legacy `CONFIG.MODEL_DAL_SETTINGS` block.

## 2. `GFE/smarttools/spot_forecast.py`
- Configure one point forecast using `Multi-Model` → select `GFS` and
  `ECMWF`. Confirm the log prints the alias-derived dataset names and
  levels (e.g., `gfs0p25`, `ecmwf0p25wave`).
- Repeat using a lat/lon that straddles the dateline to ensure shapely
  envelopes and DAL retrieval succeed with 0–360° longitudes.
- Compare resulting wind/wave spreads against the legacy tool to verify
  that `_models_used` matches and that gust minima/maxima align.

## 3. `GFE/smarttools/out_of_domain_spot.py`
- Because this wraps the modular spot-forecast procedure, run the same
  experiments as above but via the “OutOfDomainSpot (current)” menu
  entry to ensure the production workflow exercises the shared code.

## 4. `GFE/smarttools/wind_gusts_wave.py`
- With the GUI sliders set to blend `GFS` + `ECMWF`, run the tool and
  confirm the log reports the alias-derived wave identifiers (e.g.,
  `GFSwaveNH0p16`). Toggle models on/off to ensure the alias registry
  handles synonyms such as `nECMWF0p25`.
- Force a missing wave model (temporarily rename `GFSwaveNH`) and make
  sure the tool falls back gracefully while logging the alias key that
  failed.

## 5. Shared Utilities
- `model_aliases`: run the module as a script (`python -m
  GFE.utilities.model_aliases`) to print the canonical model list and
  verify overrides (`model_aliases.overrides.json`) take effect without
  editing code.
- `dal`: inside the AWIPS Python prompt, call `fetch_geometry("GFS",
  "QPF", time_range)` for a small selection to verify the available-time
  cache is hit on subsequent calls.
- `thresholds`: execute the conversion helpers with representative
  values (knots ↔ m/s, meters ↔ nm) and assert the output matches known
  references (e.g., 10 m/s ≈ 19.44 kt).

Document the cycle date, selected models, and any DAL warnings in the
PR/issue so future regressions can re-run the same scenarios quickly.

