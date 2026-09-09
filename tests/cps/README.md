# cps test suite

Analytic verification of `cps/hart.py` (Hart 2003 cyclone phase space
math), per `web/CPS/PLAN.md` section 8. `synthetic.py` builds
closed-form vortices (Gaussian warm/cold core height bumps, a
modified-Rankine wind field) with its own independent haversine, so
expected values come from geometry, not from re-running the module
under test.

Covers: mask geometry (dateline/lon-convention invariance, circle
area), symmetric warm core (B near zero, VTL > VTU > 0), a known
left/right thickness tilt (exact expected B, sign flips with heading
and hemisphere), cold core (negative VTL/VTU), `track_motion` headings
and speeds (including a dateline crossing), `gale_radius_km` against
an analytic Rankine R34, `refine_center` against a known MSLP minimum,
and `compute_point` end to end (including the too-few-points path).

Run from the repo root:

    python3 -m pytest tests/cps -q
