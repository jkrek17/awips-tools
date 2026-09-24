# Review follow-up: what remains after the 24 September 2026 revision

The referee review of the article was answered in two parts. The first
part is done and merged: parameter B now uses true semicircle means,
the closed-low detector runs on mean sea level pressure, the article
was restructured (Data section, validation table, appendix, split
limitations), the 12% deep-warm excess was traced to the standard-level
band, the B-versus-scale panel was added to Figure 18, and eight
references were added. This file lists the second part: the items that
need CAVE, real model data, or a decision, in the order they matter.

## Needs CAVE or real data

1. **Check the class field on the remaining models.** Revision 3 is
   installed; HCPSidx and HCPSclass try four MSLP inputs in order
   (`MSLP`, `PMSL`, `MSLP` at Surface, then 1000 hPa height converted)
   and load on GFS and ECMWF (verified 24 September). For any other
   model that comes up blank, look up the key behind "MSL Press"
   (README, Install) and report it so the definition can carry it.

2. **Quantitative real-case comparison against the FSU page (review
   item 1, the main open point).** For Typhoon Dujuan in the 19
   September 1200 UTC run (or the 20 September 0600 UTC run), sample
   HVTL, HVTU and HB at the MSLP center every 6 h through the life
   cycle and record them with the FSU values for the same run and
   hours. A time-series figure of the three parameters, gridded
   against FSU, would replace the color-only comparison in Section 6.

3. **Re-sample the validation log.** Every HB value and every
   detection in the validation table was made with the former B and
   the 1000 hPa detector. Re-sample the 20 September 0600 UTC frames
   (0 to 120 h) and the 959 hPa North Atlantic low at 6 h of the 24
   September 0600 UTC run with the new install, and update the table
   in the article and the README log.

4. **Motion proxy against true motion (review item 7).** Along the
   Dujuan track, compare the window-mean deep-layer wind heading with
   the finite-differenced center motion heading frame by frame. A
   heading difference under about 20 degrees changes B by under 6%.

5. **Fresh Figure 9 captures.** The class legend in the Figure 9 and
   Figure 10 to 11 captures still reads "frontal". Retake after the
   reinstall so the captures also show the MSLP detector and the
   semicircle B, and drop them into `article/figures/` under the same
   names for `make_cave_figures.py`.

6. **A Southern Hemisphere storm.** The hemisphere factor is tested on
   synthetic fields only. One real SH case (any recurving cyclone in
   the GFS) checks the sign of HB and the class in practice.

7. **Class flicker in practice.** With the new install, note how often
   the class alternates between neighboring codes frame to frame on a
   storm near a threshold. That decides whether the one-frame
   hysteresis proposed in Limitations is worth implementing.

## Decisions

8. **Lower band estimator.** The mean of the 925/850/700 and
   850/700/500 hPa slopes tracks Hart's band more closely (rms 25 m
   against 44 m across the test profiles). Switching would change
   HVTL magnitudes on every product and needs re-validation. Keep as a
   later revision unless the real-case comparison in item 2 shows the
   deep-warm excess matters operationally.

9. **Subtropical storm at the 10 m line.** The synthetic subtropical
   case now reads B of 11 m and class 3. The article reports it as the
   borderline it is. If a symmetric reading is wanted for the catalog,
   the case's asymmetry has to be reduced, which is a choice about the
   synthetic case, not about the method.

10. **Polar low detector margin.** The synthetic polar low passes the
    5 hPa ring test by 0.6 hPa. Real polar lows are often shallower
    than that in the GFS; if they matter at OPC, a 3 hPa site setting
    (`depthHpa`) is available in the definitions.

## Small items

11. Window-size sensitivity has not been mapped (Hart noted radii up
    to about 10 degrees made no major difference); a 300, 500 and
    700 km run on one real case would close it.
12. No projected grid has been tested; all results are on
    latitude-longitude grids.
13. `basin_scene.py`'s weak frontal wave (4.5 hPa) sits below the
    detector floor by construction; deepen it or drop it if that
    figure is used anywhere.
