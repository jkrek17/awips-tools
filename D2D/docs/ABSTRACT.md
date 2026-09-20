# Gridded Cyclone Phase Space as an AWIPS Derived Parameter for Diagnosing Tropical Cyclone Structure and Extratropical Transition

Jason Krekeler, NOAA/NWS Ocean Prediction Center

The cyclone phase space of Hart (2003) characterizes a cyclone's thermal
structure through lower- and upper-tropospheric thermal wind parameters,
derived from the vertical change of the geopotential height perturbation
within 500 km of the center, and a low-level thermal asymmetry, from
which Evans and Hart (2003) defined objective onset and completion times
for extratropical transition. This work reformulates the parameters as
gridded AWIPS II derived parameters computed on demand from geopotential
height on standard isobaric levels, surface pressure and, for the
asymmetry parameter, the deep-layer wind. At each grid point the height
perturbation is evaluated over a 500 km window by a separable sliding-
extrema filter, the thermal wind is the regression slope against log
pressure over 925 to 700 hPa and 500 to 300 hPa, below-ground levels are
excluded, and a closed-low detector on 1000 hPa height restricts
classification to closed lows about 5 hPa deep. One categorical field
assigns each detected low to one of seven classes formed from the
quadrants of Hart's two diagrams. A global 0.25° grid takes about 2.6 s
per forecast hour. On GFS forecasts, the hour at which a typhoon lost
its deep warm core matched the storm-centered diagnosis on the Florida
State University cyclone phase page. The asymmetry parameter uses the
window-mean deep-layer wind as a motion proxy and a first-order
thickness-gradient approximation, and is not yet validated. The
standard-level bands and the square window differ systematically from
Hart's definitions, and the size of those differences on real storms has
not been measured.

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
