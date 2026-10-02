# TCPressure checks

```bash
python3 test_tc_pressure.py
```

`GFE/utilities/TCPressure.py` moves a tropical cyclone in a pmsl field to the
warning's position and strength: it removes the background's own vortex and
puts in one built from the same fitted wind profile `TCWind_JTWC` uses for
its Wind grids. The physics checks run on **real warnings** - the JTWC and
NHC fixtures under `tests/tcwind_jtwc/fixtures/` - so the pressure profiles
come from real fits, not invented numbers.

- **The profile**: deepest at the center, never rising outward, zero at the
  outer radius with no kink there, deeper for stronger storms; a real 105 kt
  hurricane comes out 50-110 mb deep, a real 35 kt storm 5-20 mb.
- **The anchor**: all five real warnings with a central pressure anchor inside
  the limits against their local environment, and at tau 0 the implanted
  central pressure is the bulletin's exactly.
- **Relocation**: a typhoon the model put 220 nm off moves to the warning
  position, the model's low is found and reported, nothing is left where the
  model had it, and the field far from both is untouched.
- **No ripple**: the old vortex comes out to within 0.12 mb, its core to
  within 0.05 mb, and no gridpoint-scale ripple is left behind - the ripple
  straight-line interpolation between ring means used to leave, which showed
  up as jagged isobars wherever the gradient was slack.
- **Edge cases**: no background low (implant only), a low cut off by the
  field's edge (not removed half-way), two storms (each takes its own
  background low), and a storm on the dateline in a `-180..180` grid.
- **From the text database to the storms**: a live warning is read, an old
  one dropped and an unparseable one noted; the storm at a chart time is
  interpolated along the track and anchored to the tau-0 storm and its
  pressure; a chart time outside the warning's span leaves it out and says
  so; with no bulletin pressure, the storm is placed unanchored; without
  `TCWind_JTWC`, nothing moves and the reason is given. `synth_warning.py`
  writes the warnings in the real JTWC layout, dated to whatever chart is
  being tested.
