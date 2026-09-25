# Review follow-up: what remains after the 24 September 2026 revision

The referee review of the article was answered in two parts. The first
part is done and merged: parameter B now uses true semicircle means,
the closed-low detector runs on mean sea level pressure, the article
was restructured (Data section, validation table, appendix, split
limitations), the 12% deep-warm excess was traced to the standard-level
band, the B-versus-scale panel was added to Figure 19, and eight
references were added. This file lists the second part: the items that
need CAVE, real model data, or a decision, in the order they matter.

## Real-case comparisons so far

Nine comparisons against the Florida State page were run on 24
September, across the 1200 and 1800 UTC cycles:

- Thermal structure agreed in all eight usable cases.
- Cold-core terms read 30 to 80 m more negative than FSU.
- Warm cores ran 15 to 25 percent high on the standard bands, close to
  FSU on Hart's own bands.
- B matched FSU within a few meters on moving storms.
- The steering proxy over-read B by about 10 m on stalled or looping
  lows, which changed the class call in three cases.
- The upper band went cold about a day earlier than FSU's 600 to
  300 hPa band on a weakening tropical cyclone.
- One comparison was unusable because the tracker ended at 6 h.
- The Labrador 1800 UTC late-track B gap (30 m against FSU's 13 m) is
  unexplained.

Follow-up: use track-motion B, not the steering proxy, for the
collection's class; add the tracker's secondary-minimum rule; and
write the paper's validation section once more days are in.

## Needs CAVE or real data

1. **Check the class field on the remaining models.** Revision 3 is
   installed; HCPSidx and HCPSclass try four MSLP inputs in order
   (`MSLP`, `PMSL`, `MSLP` at Surface, then 1000 hPa height converted)
   and load on GFS and ECMWF (verified 24 September). For any other
   model that comes up blank, look up the key behind "MSL Press"
   (README, Install) and report it so the definition can carry it.

2. **Quantitative real-case comparison against the FSU page (review
   item 1, the main open point).** `realtime/gfs_cps.py` now samples
   every detected low from public GFS output, so the gridded side of
   this no longer needs hand sampling in CAVE: run it on the cycle the
   FSU page plotted for Typhoon Dujuan (the 19 September 1200 UTC run
   is past NOMADS retention; the AWS bucket keeps cycles longer, or use
   the next storm the FSU page tracks), chain the low nearest the track
   frame to frame, and read the FSU values for the same hours off the
   page. A time-series figure of the three parameters, gridded against
   FSU, would replace the color-only comparison in Section 6.

3. **Re-sample the validation log.** Every HB value and every
   detection in the validation table was made with the former B and
   the 1000 hPa detector. The 959 hPa North Atlantic low at 6 h of the
   24 September 0600 UTC run is now sampled by `realtime/gfs_cps.py`
   (958.6 hPa at 61.0N 22.75W: HVTL +68, HVTU minus 186, HB +20 m,
   class 3), and the CAVE readouts of the five captured frames match
   the tool's HVTL and HVTU to about 1 m. What remains is a CAVE
   re-sample of the 20 September 0600 UTC frames with the new install,
   or the same cycle from the AWS bucket through the tool, and the
   update of the table in the article and the README log.

4. **Motion proxy against true motion (review item 7).** Along the
   Dujuan track, compare the window-mean deep-layer wind heading with
   the finite-differenced center motion heading frame by frame. A
   heading difference under about 20 degrees changes B by under 6%.

5. **Fresh Figure 10 captures.** The class legend in the Figure 10 and
   Figure 11 to 12 captures still reads "frontal". Retake after the
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
