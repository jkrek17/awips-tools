# Gridded Cyclone Phase Space as an AWIPS Derived Parameter for Diagnosing Tropical Cyclone Structure and Extratropical Transition

Jason Krekeler, NOAA/NWS Ocean Prediction Center

The cyclone phase space of Hart (2003) characterizes a cyclone's thermal
structure through lower- and upper-tropospheric thermal wind parameters,
derived from the vertical change of the geopotential height perturbation
within 500 km of the center, and a low-level thermal asymmetry, from
which Evans and Hart (2003) defined objective onset and completion times
for extratropical transition. This work reformulates the parameters as
gridded AWIPS II derived parameters computed on demand from geopotential
height on standard isobaric levels, mean sea level pressure, surface
pressure and the deep-layer wind. At each grid point the height
perturbation is evaluated over a 500 km window by a separable sliding-
extrema filter, the thermal wind is its regression slope against log
pressure over 925 to 700 hPa and 500 to 300 hPa, the asymmetry is the
difference of true semicircle means across the window-mean deep-layer
wind, and a 5 hPa ring test on mean sea level pressure restricts
classification to closed lows. One categorical field assigns each
detected low to one of seven classes formed from the quadrants of Hart's
two diagrams. A global 0.25° grid takes about 2.7 s per forecast hour.
On GFS forecasts the class followed Typhoon Dujuan through its full
transition on the path the Florida State University phase diagrams
traced for the same run. On a synthetic life cycle evaluated with both
methods, the class sequence is the same, the asymmetry parameter matches
Hart's to 1%, onset falls at the same hour and completion one frame
later. For a profile not linear in log pressure the 925 to 700 hPa band
reads a deep warm core about 12% high and the upper band about 9% low,
and the lower band a warm seclusion two to three times higher than
Hart's layer; the square window adds under 0.2% for compact storms.

## References

- Hart, R. E., 2003: A cyclone phase space derived from thermal wind and
  thermal asymmetry. *Mon. Wea. Rev.*, **131**, 585–616.
- Evans, J. L., and R. E. Hart, 2003: Objective indicators of the life
  cycle evolution of extratropical transition for Atlantic tropical
  cyclones. *Mon. Wea. Rev.*, **131**, 909–925.
- Hart, R. E., J. L. Evans, and C. Evans, 2006: Synoptic composites of
  the extratropical transition life cycle of North Atlantic tropical
  cyclones: Factors determining posttransition evolution. *Mon. Wea.
  Rev.*, **134**, 553–578.
- Shapiro, M. A., and D. Keyser, 1990: Fronts, jet streams and the
  tropopause. *Extratropical Cyclones: The Erik Palmén Memorial Volume*,
  C. W. Newton and E. O. Holopainen, Eds., Amer. Meteor. Soc., 167–191.
- Jones, S. C., and Coauthors, 2003: The extratropical transition of
  tropical cyclones: Forecast challenges, current understanding, and
  future directions. *Wea. Forecasting*, **18**, 1052–1092.
