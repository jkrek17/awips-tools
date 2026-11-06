# Lift_StormCores test

Offline check of `GFE/smarttools/Lift_StormCores.py` against the fake GFE in
`tests/blend_wind_gust_wave_pmsl/gfe_fakes.py` (numpy only):

    python3 test_lift.py

Covers the lift and threshold, unit conversion, a missing model, the edit
area, the GEFS floor (0-1 and 0-100 probabilities) and the HF ceiling count.
The GEFS element names in the tool are guesses to be checked on AWIPS; the
test uses the tool's own `GEFS_P48_SOURCES`.
