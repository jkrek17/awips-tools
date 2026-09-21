# Review panel report, 2026-09-18

Four independent reviews of the article (`cyclone_phase_space/article/index.html`), the
package (`cyclone_phase_space/`), the guides, the abstract and the talk, each from a
different remit: (1) extratropical transition dynamics and fidelity to
Hart (2003) and Evans and Hart (2003); (2) numerical verification of
the code and of every number in the article; (3) operational marine
forecasting; (4) editing, figures and cross-document consistency.
Findings that two or more reviewers raised independently are marked
with the reviewer numbers. All four recommended major revision. None
found an error in the core thermal wind computation: the sliding
window, the log-pressure regression, the sign conventions, the
closed-low and below-ground masks and the half-disk constant for B
all reproduced independent calculations to machine precision.

## A. Science and method (must fix before presenting)

1. **Steering flow is the pointwise deep-layer mean wind** (1, 3).
   Inside any developed cyclone that is the cyclone's own circulation,
   not its motion. Within one degree of a synthetic center the implied
   heading sweeps all four quadrants. Every B value at a low center,
   and so the frontal/symmetric half of HCPSclass, is set by the
   vortex wind. Fix: area-average the deep-layer wind over the 500 km
   window before taking its direction; verified to recover the
   environmental flow at the center on the synthetic case. Rerun
   Figures 4 and 7 and add a test with the vortex in the wind field.
2. **Figure 4 uses the vortex's own geostrophic wind as steering** (1,
   2, 4), giving a 45 m/s "storm motion", B = 15 m and class 4 where
   Figure 3 shows the same vortex as class 5. Fix: uniform 8 m/s
   westerly as in Figure 3; report whatever class results.
3. **"Warm air on the equatorward flank always reads positive" is
   wrong** (1). B is motion-relative; Figure 7 itself shows the
   easterly vortex at −25 m with warm air to its south. Fix in the
   article, `cps_HartCPS.py` and `cyclone_phase_space/cps/hart.py`.
4. **Standard-level bands may bias the lower term by 25 to 50 percent**
   (1). The lower band 925/850/700 lies entirely below Hart's 900 to
   600 layer. "Comparable in magnitude to Hart's hurricanes" and
   "near but not equal" are unsupported. Fix now: remove the
   comparison and state the bands differ systematically. Fix
   properly: run `executeBand7` against `executeBand3` on GFS native
   levels for a set of storms and publish the regression. Needs real
   data.
5. **The square-versus-circle agreement is scale dependent** (2).
   The "within 2 percent" is the test tolerance; measured agreement is
   0.002 percent for the 150 km test vortex, 1.9 percent at 250 km,
   21 percent at 400 km and 52 percent at 600 km. Both bands inflate
   equally, so the sign is preserved but magnitudes are not. Fix:
   restate with the measured numbers and the regime, add the scale
   sensitivity to the limitations, tighten the test.
6. **No longitude wrap** (1, 2). On a global grid the window is
   clipped at the seam, halving ΔZ in the first and last 500 km of
   columns, and `cells_per_row` explodes on the pole row. Fix: wrap
   the x filter when the grid is global; clamp the pole rows; add a
   seam test.
7. **Warm seclusion path is self-contradictory** (1, 3). The
   documents say 4 then 1, but the code docstring says B commonly
   stays above 10 m through a seclusion, which gives 3, not 1, and
   the bent-back front of a Shapiro-Keyser seclusion keeps B high.
   Fix: the signature is HVTL turning positive with HVTU still
   negative: 4 to 3, or 4 to 1 if B also falls. Watch HVTL crossing
   zero, not the color.
8. **Onset and completion should be read from HB and HVTL, not from
   the class** (1, 3). A storm whose B crosses 10 m in the same frame
   as HVTL crosses zero jumps 0 to 4 and onset is never seen; code 6
   also satisfies completion. Fix: define onset as HB crossing 10 m
   and completion as HVTL crossing zero, with HCPSclass as the
   summary.
9. **Class table errors** (1, 2, 3). Codes 4 and 5 list the upper term
   as "any" but code 6 takes precedence, so they require a cold upper
   term. The seven codes are the eight cells of the joint space with
   code 6 merging both B states, so "loses neither" is wrong. Add the
   tie convention (zero counts warm, 10 m counts symmetric).
10. **Orientation-invariance claim contradicts the square window**
    (1). The square's excess over the circle depends on the gradient's
    angle to the grid axes (zero when aligned, 41 percent at 45
    degrees, 27 percent averaged). Fix: claim only that ΔZ needs no
    sign convention and is hemisphere independent; note the anisotropy
    and that no projected grid has been tested.
11. **The 24 h running mean is attributed to Hart (2003) without a
    source** (1). Fix: attribute to the real-time Florida State page,
    which states it, or delete.
12. **Hart's quadrant names and axes** (1, 4). The fourth thermal wind
    quadrant is shallow cold core in Hart's convention; Hart plots B on
    the vertical axis; "Phase 1" and "Phase 2" are not his terms;
    "asymmetric" (figures) and "frontal" (tables) name one category.
    Fix: rename code 6 "shallow cold core (lower cold, upper warm)",
    transpose Figure 1a and Figure 7d, drop "Phase 1/2", use
    "frontal" everywhere with "asymmetric" given once as Hart's word.
13. **HB is unmasked and, for a symmetric vortex, purely
    environmental** (2, 3). The vortex contributes nothing to the
    window-mean gradient, so HB reads the environment and the motion;
    away from a low it is the ambient gradient across the flow and
    means nothing about a storm. Negative HB means warm air to the
    left of motion, not symmetry. Fix: say so in the article and the
    guide; cross-check large |HB| of either sign against thickness.
14. **Figure 6 shows the earlier five-code product** (3, 4). Its
    legend reads "0 mid-vortex, 1 cold, 2 neutral, 3 shallow warm, 4
    deep warm". Fix: crop to the two thermal wind panels, or replace
    with a current capture. Same on slide 8.
15. **Terrain: the lower band is computed over a clipped window while
    the upper band is not** (3), within 500 km of Greenland and
    Iceland, biasing the slope silently. Fix: require a minimum valid
    fraction of the window per level and return NaN otherwise, so the
    failure is visible.
16. **Closed-low criterion** (1, 2, 3). It is 40 m of rise between
    the center and the 300 to 500 km ring, a scale test, not "a closed
    low at least 5 hPa deep"; the effective floor is about 6 hPa for a
    300 km low and higher for broader lows; the ring is square. Fix
    the wording and add tests on a trough, a col and a broad flat low.
17. **Neighboring lows within 1000 km share windows** (3), and the
    200 km dilation can merge two blobs. Undocumented. Fix: caution in
    the guide and a two-vortex test.
18. **Validation log** (1, 3, 4). Three cases, one model cycle, B
    never sampled, the North Atlantic case unrecorded, the index
    (2.5) inconsistent with the terms (2 tanh 1.2 + tanh 1.8 = 2.61),
    the Dujuan hour written as a cycle rather than a valid time,
    "release-ready" and "validated" in the README and technical
    guide. Fix: record the missing values, correct the wording, state
    acceptance criteria and drop "release-ready".

## B. Operational guidance (user guide, README, talk)

19. Weak-low fallback to raw HVTL/HVTU at a rejected low returns the
    baroclinic zone, not the wave; unsafe as written (3).
20. The blob is a 400 km square whose pixels are not one class;
    sample at the MSLP center, never the blob color (2, 3, 4).
21. The hybrid and post-tropical claim holds for HVTL, HVTU and
    HCPSidx; the frontal half of HCPSclass is least tested on exactly
    those systems (3).
22. Four-panel recipe: class + MSLP + 1000 to 850 hPa thickness +
    wind speed contours at 34/48/64 kt; HVTL + 850 hPa temperature;
    HVTU + 500 hPa height; HB + 1000 to 850 hPa thickness. Scatterometer
    or satellite as the independent check (3).
23. Model comparison: compare crossings and trends, never magnitudes;
    a coarser grid reads a smaller ΔZ (3).
24. Deep lows: 1000 and 925 hPa heights below the surface are the
    post-processor's extrapolation and differ between models (3).
25. Class 1 alone cannot separate a subtropical storm from a warm
    seclusion; the history can (3). Subtropical storms are marginal on
    all three thresholds at once (3).
26. Onset and completion mean something only for a storm of tropical
    origin; for other lows 4 to 5 is occlusion (3).
27. "What it does not tell you": not an intensity or wind forecast (3).
28. Loading text: seven levels, and HB/HCPSclass need four wind
    levels plus the coriolis field (3, 4).
29. Talk overclaims: "Hart's exact quantity", "blanks everything that
    isn't a real low", "works on every model", "nobody had before" (3).
30. Product names: the 132-character HCPSclass name consumes the
    legend line; shorten and align menu, product browser and guide
    (3).

## C. Manuscript discipline (editor)

31. Run time given five ways (1.68 s in the figure, "about 2 s",
    "one to two", "about a second", "about 1.5 s"). One number
    everywhere (2, 4).
32. Two abstracts of different text and length, both about twice the
    250 word AMS limit (4).
33. Figures appear in order 1, 8, 9, 7, 2, 3, 4, 5, 6 and five are
    never cited in the text; an unused figure file ships (1, 4).
34. Caption mismatches: Figure 3 hatching and the class-4 fringe;
    Figure 4 versus Figure 3 class; Figure 5 "consistent with the one
    second budget" at 1.68 s; Figure 7 sliver has crossed the line;
    Figure 8 "every other figure"; Figure 9 layer and λ; axis order
    wording in Figure 1 (2, 4).
35. Missing citations: the Florida State page; wind-field expansion
    during ET; the top-down erosion ordering (Evans and Hart 2003;
    Hart et al. 2006); the 10 m threshold (1, 4).
36. Constant 1.4553 in the XML and docstrings; the value is 1.4548 (2,
    4). "Exceeds 900 hPa" should be "at or above". Abstract omits the
    wind requirement.
37. Figure quality: Figure 7d label collisions and a raw ASCII symbol;
    Figure 9 has no colorbar and blue for warm; Figure 5 label overrun;
    200 dpi (4).
38. Register: ten argumentative sentences rewritten in the editor's
    report ("not a bug", "not a gap", "do not reopen it"); sentence
    case headings; hPa not mb (4).
39. License and DOI: "No license is specified" will not pass a code
    availability policy; a US Government work is public domain and
    should say so (1, 4).

## Verdict

Major revision. The method is faithful to Hart and the code is
correct where it was checked. What fails review is the motion proxy
behind parameter B, the strength of several accuracy statements
relative to their evidence, the attribution of names, axes and
smoothing to Hart, and the discipline of the manuscript. Items 1, 2,
6 and 15 are code changes; item 4 needs real GFS data; the rest is
wording, figures and structure.
