# Gridded Cyclone Phase Space as an AWIPS Derived Parameter for Diagnosing Tropical Cyclone Structure and Extratropical Transition

The cyclone phase space of Hart (2003) characterizes a cyclone's thermal
structure through the lower- and upper-tropospheric thermal wind,
derived from the vertical change of the geopotential height
perturbation within 500 km of the storm center, together with a measure
of low-level thermal asymmetry. Evans and Hart (2003) defined objective onset and
completion times for extratropical transition (ET) from these
parameters, onset when the asymmetry exceeds 10 m and completion when
the lower-tropospheric thermal wind turns negative, and Hart et al. (2006) linked
the post-transition trajectory to whether a system re-intensifies as a
warm-seclusion cyclone of the type described by Shapiro and Keyser
(1990). Operational access to these diagnostics has been limited to
static, storm-centered plots produced externally for tracked tropical
cyclones, which excludes the hybrid, post-tropical, and non-tropical
systems of greatest concern to marine forecast offices. This work
reformulates the thermal wind parameters as gridded fields computed on
demand inside the AWIPS II display system as derived parameters,
requiring only geopotential height on standard isobaric levels and
surface pressure, and therefore available for every model in the local
inventory without a cyclone tracker. At each grid point the height
perturbation amplitude is evaluated over a 500 km window using a
separable sliding-extrema filter, the thermal wind is obtained by
regression against log pressure over 925 to 700 hPa and 500 to 300 hPa,
terrain is handled by excluding below-ground levels, and a closed-low
detector on 1000 hPa height restricts classification to closed cyclones
at least 5 hPa deep. A categorical structure field (deep warm, shallow
warm, neutral, cold core) and a continuous index summarize the two
terms. Computation on a global 0.25 degree grid takes one to two seconds
per forecast hour. An initial evaluation on GFS forecasts found values
for a mature typhoon comparable in magnitude to those Hart reported for
hurricanes, allowing for the different layer definitions, a
correct cold-core classification of a deep North Atlantic cyclone, and
a forecast hour for the loss of Typhoon Dujuan's deep warm core (the
transition from deep to shallow warm core) that matched the
storm-centered diagnosis on the Florida State University cyclone phase
page for the same model run. The asymmetry parameter B is implemented as a
first-order approximation, the window-mean thickness gradient projected
across a steering-flow motion proxy, giving an Evans and Hart onset
field that has not yet been validated. A simpler formulation based on vertical differences of
relative vorticity was found to misclassify vertically tilted and broad
baroclinic systems as warm core and was retained only for comparison.
Limitations include the use of standard levels in place of Hart's
50 hPa spacing, a square analysis window whose corners overstate the
height range on a background gradient, the steering-flow approximation
of the asymmetry parameter, and validation on a small number of cases; a full season of operational use at the
Ocean Prediction Center is planned.

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
