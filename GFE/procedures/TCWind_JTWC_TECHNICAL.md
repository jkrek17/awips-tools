# TCWind_JTWC — technical reference

**EXPERIMENTAL. NOT OPERATIONALLY VETTED.** Every grid needs forecaster review
before it informs any product.

This document holds the reasoning that used to live in `TCWind_JTWC.py` as
comment blocks. The procedure keeps short comments where a line is not
self-evident; anything longer was moved here and replaced with a `# [doc N]`
marker pointing at the matching numbered note below.

| | |
|---|---|
| Procedure | `GFE/procedures/TCWind_JTWC.py` |
| Version | `2026-10-04b` (the `VERSION` tunable; the status bar prints it) |
| Install | `/awips2/edex/data/utility/common_static/site/<SITE>/gfe/userPython/procedures/` |
| Install test | `AWIPS_TEST.md`, and `selfcheck/run_selfcheck.sh` in the export bundle |

## What it does

NHC and CPHC publish a gridded TCM, and AWIPS already ships `TCMWindTool` to
ingest it. JTWC does not: for the West Pacific there is no grid, so there is
nothing for that tool to consume, and that gap is why this procedure exists.

It reads tropical cyclone forecast **text** from the AWIPS text database,
fits an analytic vortex to the quadrant wind radii in it, and inserts the
resulting wind field over the background Wind grid, one grid every three
hours across the bulletin's forecast span.

Two products, four basins:

| Basin | Product | AWIPS PILs | Parser |
|---|---|---|---|
| Atlantic | NHC TCM forecast/advisory | `MIATCMAT1-5` | `parseTCM()` |
| East Pac | NHC TCM forecast/advisory | `MIATCMEP1-5` | `parseTCM()` |
| West Pac | JTWC WTPN warning | `NFDTCPWP1-5` | `parseJTWC()` |
| Central Pac | CPHC TCM forecast/advisory | `HFOTCMCP1-5` | `parseTCM()` |

For the three TCM basins this is a text-only fallback and cross-check, not a
replacement for the real gridded product.

The dialog's **Basins:** checklist picks one or more oceans per run (none
ticked by default) and all five storm slots in each are read; empty and stale
slots are skipped, and a storm in two basins' bulletins is kept once. `parseBulletin()` chooses
the parser by inspecting the text, not by trusting the PIL — an office can
store anything in any bin, and a misroute would not raise, it would return a
confident parse of the wrong shape.

## The pipeline

```
text (textdb)
  -> parseBulletin()            sniff the format, dispatch
       parseJTWC() / parseTCM() -> (taus, header)
  -> interpolateTrack()         Tau list -> Snapshot at an arbitrary time
  -> resolveRmax()              radius of maximum wind for that snapshot
  -> fitGTCM()                  least squares on the reported radii
  -> buildVortex()              parameters -> a wind field on the GFE grid
  -> insertStorms()             composite over the background Wind grid
  -> createGrid()               one grid per 3-hourly block
```

Both parsers return the identical `(taus, header)` shape. That is the single
most load-bearing design decision in the file: everything downstream is shared
and knows nothing about which product it came from, which is why adding NHC
and CPHC was a parser-only change.

## Data model

**`Tau`** — one forecast time. `tau` (hour), `epoch`, `lat`, `lon` (negative
west), `vmax`, `gust`, `radii` (`{34: {"NE": nm, ...}, 50: ..., 64: ...}`),
`motionDir`, `motionSpd`, `conf`, and a `fit` cache.

A quadrant reporting `000 NM` means *the profile never reaches that speed
there*, not that the radius is zero. There is no separate "not reported"
state anywhere in this data model, on either parser's output.

**`Snapshot`** — the storm state at an arbitrary time, produced by
`interpolateTrack()` between two `Tau`s. This is what the vortex code consumes.

**`header`** — `refDate`, `systemType`, `stormId`, `stormName`,
`warningNumber`, `pressureMb`, and for TCM products `basin`.

**`conf`** — a transition flag, not a blend weight: `CONF_TROPICAL` 1.00,
`CONF_BECOMING` 0.60, `CONF_SUBTROPICAL` 0.25. It ratchets downward and is
read at exactly one place, the skip check governed by
`INSERT_AFTER_SUBTROPICAL`. It never scales a wind value.

## The wind field

The vortex is the NHC Gridded TCM construction (`VORTEX_METHOD = "gtcm"`),
from the *Gridded TCM User's Guide* v1.9.1: a symmetric modified Rankine
profile with two size exponents, fitted by weighted least squares against all
reported radii jointly, plus a wavenumber-1 motion asymmetry from Schwerdt
(1979). The retired per-quadrant construction remains as `"perquad"` for
comparison only.

Notes 33–52 cover the fit and the field in detail. The ones most worth
reading before changing anything:

- **the continuity factor** — the Guide prints an expression for `A` that is
  not continuous at `ri`; both ports carry the corrected form
- **the `freeParams` ladder** — `rm`, `x1` and `x2` are three unknowns, and a
  bulletin reporting two radii constrains two numbers; fitting all three to
  two targets leaves a manifold of exact solutions
- **the outer taper** — a local heuristic, not part of GTCM

## Configuration

Tunables sit in one block near the top of the procedure and are deliberately
not exposed in the dialog: none of them is a per-run decision. The dialog
carries only what is: basins, where to write, time range, subtropical
systems, pmsl, and points past the warning.

The ones that change output most: `VORTEX_METHOD`, `GTCM_X_MIN` / `GTCM_X_MAX`,
`GTCM_ASYM_MAX_DEV_KT` / `GTCM_ASYM_MIN_CAP_KT`, `BACKGROUND_CAP_KT`,
`MAX_INSERT_RADIUS_FACTOR`, `OUTER_DECAY_FACTOR`, `NORMALIZE_CORE_PEAK`,
`INSERT_AFTER_SUBTROPICAL`, `OUTPUT_GRID_INTERVAL_SECONDS`.

`EXPERIMENTAL` gates the warning banner in the dialog and the "EXPERIMENTAL,
verify before use" note on the status bar. `MAX_BULLETIN_AGE_HOURS`
(12) is what stops a dissipated storm sitting in a PIL forever from being
gridded — textdb returns whatever was last stored there.

## What is verified, and what is not

**Verified:** that the field is internally coherent, that the Python and both
JavaScript ports agree to 0.5 kt, that the parsers reproduce committed
snapshots, and that the whole procedure runs end to end on real bulletins of
both formats.

**Not verified:** anything about the wind that actually blew. There is no
comparison against scatterometer, buoy or any other observation; best track
gives analyst-assigned radii quantised to 5 nm, not gridded truth. The
forecast hours are unverified too — every check scores against best-track
*analysis* times, so nothing says whether the tau-96 field is any good.

The claim this tool can defend is that **it renders faithfully what the
forecast centre said, in the shape NHC would have rendered it.** Not that the
wind is right.

## Known limitations

- **No land-roughness reduction.** Guide step 4 needs the USGS land-surface
  database; the field is marine exposure everywhere and will be too strong
  over land.
- **The fit is ill-posed for weak storms.** The symmetric vortex peaks at
  `Vmax − a`, where `a = 1.6·c^0.63` grows with translation speed. When that
  peak falls below the lowest threshold the bulletin reports, no choice of
  `rm` or `x` can put the vortex at the reported radius, and the optimiser
  flattens `x` onto its floor. Measured on best-track transition cases:
  100% of records at or below 35 kt are ill-posed, 53% at 40–45 kt, 3% at
  50–55 kt, none at 60 kt and above. The extreme cases produce 34 kt radii
  hundreds of nautical miles out. This is the shipped baseline, not a
  regression, and `GTCM_X_MIN = 0.20` is what bounds the damage.
- **The outer taper is a local heuristic**, not part of GTCM. The Guide's
  grids are simply missing outside the 34 kt radii and NHC leaves the blend
  to the receiving office.
- **NHC forecast hours are not multiples of 12.** NHC anchors to 00/12Z
  synoptic times, so a 15Z advisory yields taus of 0, 9, 21, 33 and so on.
  Anything assuming JTWC's neat 12-hour labels will be wrong on three basins.

## Tests

```bash
python3 tests/tcwind_jtwc/test_parser_golden.py       # both parsers vs snapshots
python3 tests/tcwind_jtwc/compare_py_js.py            # Python vs both JS ports
python3 tests/tcwind_jtwc/test_procedure_harness.py   # the procedure end to end, GFE-free
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
```

All four are hermetic — real bulletins are committed, so they need only numpy
and node, with no network.

For the AWIPS host, `python3 tools/export_awips.py` builds a bundle carrying
the procedure, this document, `AWIPS_TEST.md`, and a self-check that parses
one product of each kind and runs the full harness under the real AWIPS
interpreter.

## Design notes

Each note below carries a number that appears in the source as a
`# [doc N]` marker at the exact line the note explains. Grep the
procedure for `[doc 17]` to find where note 17 applies, or read a
note here and jump to the function named in its heading.

### Configuration, dialog and run control


#### 2.  NHC and CPHC issue the TCM ("Forecast/Advisory"), the structural...

*module level*

NHC and CPHC issue the TCM ("Forecast/Advisory"), the structural equivalent of JTWC's WTPN warning.  Their AWIPS ids are the office node plus TCM plus the basin and storm slot, and each product carries its own id on line 1: "ZCZC MIATCMAT5 ALL" on a real Atlantic advisory, "ZCZC HFOTCMCP1 ALL" on a real Central Pacific one, both confirmed against archived products.

#### 3.  One run, one basin.  The dialog is a radio, so this list is both the

*module level*

One or more basins per run.  The dialog is a checklist, so this list is both the option list and the label-to-PIL lookup, and its order is the order the forecaster sees.  The labels are deliberately the ocean names rather than ATCF codes or office ids - "Atlantic", not "AT - NHC".

#### 4.  NOTE on what this does NOT claim.  NHC and CPHC already distribute a

*module level*

NOTE on what this does NOT claim.  NHC and CPHC already distribute a gridded TCM, and AWIPS already ships TCMWindTool to ingest it; for those basins that grid is the authoritative product and this reconstruction is not a replacement for it.  Reading their text matters where the grid is late, missing, or being checked - and because rendering a bulletin whose real grid also exists is the only way to test this tool's core claim, which JTWC's text alone can never provide.

#### 5.  Retired: the built-in test case

*no longer in the code*

Earlier versions bundled a real WTPN31 warning for 22W (KROVANH) and a
"Run test case" dialog toggle that gridded it at the grid's centre with no
live storm needed.  Removed in 2026-10-04b at the forecasters' request; the
off-line harness feeds the same bulletin from
tests/tcwind_jtwc/fixtures/ instead.

#### 6.  Tunables.  Set these once for the office; they are deliberately not...

*module level*

Tunables.  Set these once for the office; they are deliberately not exposed in the dialog, because none of them is a per-run decision.

#### 7.  Which vortex construction to use

*module level*

Which vortex construction to use.

```
   "gtcm"     NHC's Gridded TCM / WTCM model, implemented from the Gridded TCM
              Users Guide v1.9.1 (Santos & DeMaria, 12/4/2023).  One symmetric
              modified Rankine vortex (Rappin et al. 2013) plus a wavenumber-1
              asymmetry, fit by weighted least squares to the reported radii.
              This is what produces NHC's Atlantic/EastPac grids, so a JTWC
              grid built this way looks like the ones OPC already ingests.
              It does not pass exactly through the reported radii, and that is
              deliberate: the guide minimises WIND error rather than radius
              error precisely because forcing the radii produces unrealistic
              structure (eq. 7 and the note beneath it).
```

```
   "perquad"  Per-quadrant radial fit, tangentially interpolated between
              quadrant bisectors.  Reproduces every reported radius exactly.
              This is what NHC's legacy TCMWindTool did - equation (4) in the
              guide - and what this tool did before the GTCM port.  Kept for
              comparison; see tests/tcwind_jtwc/compare_vortex_methods.py.
```

#### 8.  The asymmetry is not always aligned with the motion vector,...

*module level*

The asymmetry is not always aligned with the motion vector, particularly at higher latitudes and during extratropical transition.  After the size parameters are fit, the guide lets the asymmetry components move up to this far from their motion-derived first guess to further reduce the error. This is a search radius only; GTCM_ASYM_MIN_CAP_KT below now binds first (see its comment), so most candidates this radius alone would still admit are rejected for magnitude before they are ever reached.

#### 9.  Hard ceiling on the FITTED asymmetry magnitude |(ax, ay)|, relative...

*module level*

Hard ceiling on the FITTED asymmetry magnitude |(ax, ay)|, relative to the motion-derived first guess `a = GTCM_ASYM_A * c**GTCM_ASYM_B`:

```
   |(ax, ay)| <= max(1.5 * a, GTCM_ASYM_MIN_CAP_KT)
```

Unbound, a one-sided radii report (gales reported only in the quadrants facing the motion vector, 000 nm behind it) pulls |(ax, ay)| up toward `a + GTCM_ASYM_MAX_DEV_KT` to chase the lopsided WIND error, which drags the symmetric amplitude vs = Vmax - |(ax, ay)| down with it. On a live 40 kt storm with gales reported only in the two eastern quadrants this put |(ax, ay)| at 15.8 kt against a motion value of 8.1 kt, collapsing vs to 24 kt and modelling 5 kt only 34 nm upwind of the centre of a 40 kt storm - a reported 000 nm quadrant means no gales there, not calm air. Capping the magnitude at 1.5x the motion value keeps the weak side physical while still letting the fit lean asymmetric; direction is unconstrained. The GTCM_ASYM_MIN_CAP_KT floor lets a slow-moving or stationary storm (a near or at 0) take a modest asymmetry rather than being locked to (0, 0).

#### 10.  Equations (8) and (9) build the wind field from the tangential wind...

*module level*

Equations (8) and (9) build the wind field from the tangential wind and the asymmetry vector alone - there is no inflow term.  Set this True to rotate the result toward the centre by INFLOW_ANGLE_DEG anyway, which departs from the guide but matches what the "perquad" construction has always done.

#### 11.  Iteration limits for the fits.  These bound run time inside GFE;...

*module level*

Iteration limits for the fits.  These bound run time inside GFE; the fits converge well inside them on real bulletins. Admissible range for the modified-Rankine size exponents.  The guide gives no bounds, but eq. (6)'s own climatological value spans roughly 0.37 (a marginal storm at low latitude) to 0.95 (a very intense one at high latitude), so this brackets what the guide itself considers physical with headroom either side. The former floor of 0.05 admitted a wind field that barely decays with radius - flat out to hundreds of miles - which is not a shape any tropical cyclone has, and which a thinly-constrained fit will happily run to.

#### 12.  The modelled 34 kt radius (insert footprint/taper anchor) is solved by

*module level*

The modelled 34 kt radius (insert footprint/taper anchor) is solved by probing the symmetric profile out to this many nm, then finding where the asymmetric field crosses 34 kt.  It depends on azimuth alone - the fit (rm, ri, x1, x2, ax, ay) is the same everywhere on one grid - so it is solved once per azimuth bin on this fixed table and linearly interpolated (wrapping at 360) onto the grid's own azimuths, rather than broadcasting the probe against every grid point. That broadcast used to make the cost scale with grid size: on a 500x500 domain, 250,000 points x 900 probe samples is a 225,000,000-element intermediate array, computed twice over (34 s, 6.9 GB peak). Solving it on GTCM_R34_AZ_BINS azimuths instead costs 360 x 900 = 324,000 elements, independent of grid resolution. 1 degree bins keep the azimuthal interpolation error on r34 well under the 1 nm parity tolerance (tests/tcwind_jtwc/compare_py_js.py).

#### 13.  Share of the storm's translation speed added to the field, which...

*module level*

Share of the storm's translation speed added to the field, which makes the right of track stronger than the left.  Raising it also pushes the field off the reported radii, roughly 3.4 kt of error at 0.5 on a 16 kt mover. Applies to "perquad" only; "gtcm" uses GTCM_ASYM_A/B above instead.

#### 14.  Radius of maximum wind, in nm.  0 uses the Willoughby-form regression

*module level*

Radius of maximum wind, in nm.  0 uses the Willoughby-form regression (see willoughbyRmax()), clamped below the innermost reported ring.  A nonzero value is also clamped, so only settings below the clamp have any effect.

#### 15.  Outside R34 the bulletin says nothing, so the profile tapers...

*module level*

Outside R34 the bulletin says nothing, so the profile tapers exponentially rather than extrapolating the inner power law, which decays far too slowly and leaves 20 kt winds hundreds of miles out.  The e-folding length is this multiple of R34: 1.0 puts 34 kt down to 12.5 kt at twice R34.

#### 16.  The peak wind sits on a ring at Rmax, which on a coarse grid is often

*module level*

The peak wind sits on a ring at Rmax, which on a coarse grid is often narrower than one cell, so whether any grid point samples it depends on where the storm center happens to fall between cell corners.  That leaves the grid maximum a few knots light, and occasionally much worse, varying run to run for no meteorological reason.  With this on, the core is scaled so the strongest cell reaches the bulletin's max wind exactly.  The correction tapers to zero at the innermost reported ring, so the 64, 50 and 34 kt radii do not move.  It only ever corrects upward.

#### 17.  The tool owns its own output cadence.  It always writes fixed-width...

*module level*

The tool owns its own output cadence.  It always writes fixed-width grid blocks spanning the whole bulletin, regardless of what cadence the office's own background Fcst Wind inventory happens to use nearby.

An earlier version instead matched each written block's duration to whatever cadence was locally in effect in the existing Fcst Wind inventory (offices commonly run 3-hourly near term and 6-hourly further out, mirroring how JTWC itself spaces its own forecast groups).  That made the office's OWN inventory - not the bulletin, not this tool - decide the tool's output granularity, and produced exactly the "grids get created in random 3 or 6 hour chunks" behavior forecasters reported: whichever cadence a created block happened to land near came along for the ride.  Now the tool computes its own fixed-interval time series across the span up front and writes every block at that interval, splitting a coarser background block wherever a write lands inside one. A future office could change the interval deliberately by editing this constant, but the default behavior is strict, uniform 3-hourly output.

#### 18.  This tool is experimental and has not been operationally vetted.  While

*module level*

This tool is experimental and has not been operationally vetted.  While that is true, the dialog's banner and the status bar say so.  Writing to Fcst Wind no longer needs a separate acknowledgement (removed in 2026-10-04b).  Set this to False once the tool has been through local vetting.

#### 19.  A bulletin older than this is treated as a dead slot and skipped. ...

*module level*

A bulletin older than this is treated as a dead slot and skipped.  textdb returns whatever was last stored under a PIL, so without this check a storm that dissipated days ago is rebuilt on every run.  JTWC issues every six hours, so anything past 12 is either stale or the feed has stopped.

#### 20.  Not a blend weight - see INSERT_AFTER_SUBTROPICAL's only consumer, in

*module level*

Not a blend weight - see INSERT_AFTER_SUBTROPICAL's only consumer, in execute()'s buildFor(): once a storm-time's conf drops below 1.0 (i.e. from CONF_BECOMING onward) it is skipped entirely, all or nothing, and only when INSERT_AFTER_SUBTROPICAL is False. With the tunable's default of True that branch never runs and conf has no effect on the output at all. The Rankine assumption stops being defensible once JTWC flags subtropical transition; these values exist to let an office opt into handing the field back to the background at that point, in one all-or-nothing step, not a continuous fade.

#### 21.  WMO abbreviated header line ("WTPN35 PGTW 242100"): T1T2A1A2ii, an

*module level*

WMO abbreviated header line ("WTPN35 PGTW 242100"): T1T2A1A2ii, an originating station, then a DDHHMM group. Confirmed real, live fallback case: a JTWC bulletin whose REMARKS opens straight into the synopsis with no "DDMMMYY." token anywhere at all (WTPN35 PGTW, SOULIK, 22W, extra- tropical transition) - RE_REFDATE then finds nothing anywhere in the bulletin. This gives the reference DAY only (no month/year); see the fallback in parseJTWC() below for how that day is combined with the current wall-clock month/year.

#### 24.  NHC / CPHC TCM ("Forecast/Advisory") parser

*module level*

NHC / CPHC TCM ("Forecast/Advisory") parser

The TCM is NHC's structural equivalent of JTWC's WTPN warning - position, intensity, motion and quadrant wind radii per forecast hour - but its text format differs in nine ways.  Each is called out at the regex or the code line that handles it, and the numbering matches the block in Vortex.html so the two can be read side by side.

This is a PORT.  web/TCWind_JTWC/Vortex.html had parseTCM() first, because the live web tool grew NHC support before this procedure did.  That inverts the usual hierarchy for the length of this comment only: from here on THIS FILE IS CANONICAL for parseTCM(), exactly as it already is for parseJTWC(), and tests/tcwind_jtwc/compare_py_js.py drives both sides on the fixtures in tests/tcwind_jtwc/fixtures/tcm/ to keep them honest.

```
   1. Header: a title line carrying system type + name + advisory number, an
      office line carrying the ATCF basin+number+year, then an issuance line
      carrying the reference date outright (RE_TCM_ISSUE).  No REMARKS block
      to hunt through the way parseJTWC()'s RE_REFDATE needs, and so no need
      for its wall-clock fallback either.
   2. Current position: "<TYPE> CENTER LOCATED NEAR lat lon AT DD/HHMMZ"
      (RE_TCM_CURPOS).  DD/HHMMZ, not JTWC's concatenated DDHHMMZ.  The type
      word is NHC's own vocabulary - it never says TYPHOON, and JTWC never
      says POTENTIAL TROPICAL CYCLONE - so TCM_TYPE_CONF maps NHC's ladder
      onto the same CONF_* levels the rest of this file already uses.
   3. Movement: "PRESENT MOVEMENT ... OR <deg> DEGREES AT <kt> KT"
      (RE_TCM_MOVEMENT) gives the current block's motion directly.  Forecast
      blocks never repeat it, so the _bearing_speed() backfill parseJTWC()
      already does is reused unchanged.
   4. Max wind: "MAX SUSTAINED WINDS <v> KT WITH GUSTS TO <g> KT" on the
      current block, "MAX WIND <v> KT...GUSTS <g> KT" on every forecast
      block.  Different wording, same two numbers.
   5. Wind radii: all four quadrants on ONE line with dot leaders and no
      "NM"/"QUADRANT" words ("64 KT....... 40NE  35SE  30SW  40NW.").
      RE_TCM_RADII is anchored at the start of the line precisely so it can
      never match the seas line right below it ("12 FT SEAS.. 90NE ..."),
      which does not start with a bare "<n> KT".  A quadrant absent from the
      line stays 0.0 - the same "a 000 NM quadrant contributes no fit
      target" convention _gtcmTargets() already applies to JTWC radii.
   6. "AT DD/HHMMZ CENTER WAS LOCATED NEAR ..." (RE_TCM_BACKFILL) is a
      six-hour-earlier position NHC prints so the CURRENT block's motion can
      be recovered when no PRESENT MOVEMENT line exists.  It is NOT a
      forecast time and is never appended to taus.
   7. Forecast blocks start "FORECAST VALID DD/HHMMZ lat lon" (days 1-3) or
      "OUTLOOK VALID ..." (days 4-5); RE_TCM_FCST treats both alike.  Neither
      carries a tau-hour label the way JTWC's "XX HRS, VALID AT:" does, so
      tau is computed from each block's own epoch once all are known - never
      from file order, which free text can disturb.  The pattern is not
      anchored at end of line: a live product can weld a status word onto
      the longitude with no space ("...147.6W...POST-TROPICAL"), which still
      parses and downgrades confidence.  A terminal block with a valid time
      and no position at all ("OUTLOOK VALID 08/1200Z...DISSIPATED") fails
      the pattern outright and is skipped, which is the wanted behaviour.
   8. Free text between blocks (WINDS AND SEAS VARY GREATLY..., REPEAT...,
      EXTENDED OUTLOOK..., REQUEST FOR 3 HOURLY SHIP REPORTS...) matches
      nothing here and is skipped, the same tolerant line scan parseJTWC()
      uses.
   9. "$$" ends the meaningful content - a hard stop, unlike parseJTWC()'s
      REMARKS: boundary, because the reference date was already read off the
      issuance line before the scan began.
```

#### 25.  NHC's own system-type vocabulary on the same confidence ladder this...

*module level*

NHC's own system-type vocabulary on the same confidence ladder this file already uses - difference 2.  REMNANTS OF and POST-TROPICAL CYCLONE both land on CONF_BECOMING: by definition no longer an organized tropical cyclone.  A REMNANTS OF current-position line carries no storm name at all ("REMNANTS OF CENTER LOCATED NEAR ..."); the name survives only on the title line, which is why REMNANTS OF appears in both patterns.

#### 26.  A TCM always carries this phrase on its title line and a WTPN...

*module level*

A TCM always carries this phrase on its title line and a WTPN warning never does, so it is the whole test.  Sniffing the text is deliberate: the AWIPS PIL a bulletin arrived under is a hint, not a guarantee - an office can stuff anything into any bin - and a wrong guess here produces a confident parse of the wrong shape rather than an error.

#### 28.  Fit fields interpolateTrack() blends linearly between two taus. n, rms,

*module level*

Fit fields interpolateTrack() blends linearly between two taus. n, rms, freeParams and rmSource describe how well-constrained a fit is, not a field parameter, so those are carried from the nearer tau instead (see interpolateTrack()).

#### 52.  Section headers and blank spacer rows are plain "label" rows

*`_buildVarDict()`*

Section headers and blank spacer rows are plain "label" rows too, so each one still needs its own distinct text (see the note above) -- the spacers below differ only in how much whitespace they hold, which renders identically as a blank line but keeps every varDict key unique.

#### 53.  One radio, not a list of every PIL in every basin. All five

*`_buildVarDict()`*

A checklist of basins, not of every PIL in every basin, and nothing ticked by default.  A storm crossing 180 is warned on from both sides, so West Pac and Central Pac often need to run together; ticking nothing is refused rather than guessed at.  All five slots in each ticked basin are read; an empty or stale slot is skipped already, so there is nothing for a per-slot checkbox to save anyone.  A varDict with the old single "Basin:" radio still works (selectedBasins()).

#### 54.  JTWC keeps issuing position and intensity forecasts through

*`_buildVarDict()`*

JTWC keeps issuing position and intensity forecasts through subtropical status and extratropical transition, so there is still a forecast point to build from.  What is no longer certain is that a symmetric tropical vortex is the right shape for it, which is a judgement for the forecaster rather than a fixed policy - hence a per-run choice rather than the module-level default it used to be.

#### 55.  A run with no basin ticked stops

*`execute()`*

A run with no basin ticked stops with a message saying so: a silent no-op run is worse.

#### 56.  Retired: test-case safety override

*no longer in the code*

Forced the built-in test case to the preview grid.  Removed with the test
case (note 5).

#### 57.  parseBulletin, not parseJTWC: with four basins in

*`execute()`*

parseBulletin, not parseJTWC: with four basins in play the product type is decided by the text, not by which bin it arrived in.  nowSecs is GFE's own clock, already computed above - only the WTPN no-DDMMMYY fallback consults it (see the parser docstrings), so this changes nothing for the normal case of either format.

#### 58.  Fragment so partially overlapping blocks can be written.  A

*`execute()`*

Fragment so partially overlapping blocks can be written.  A preview run must not touch Fcst at all, and fragmenting would rewrite its inventory, so it is skipped.  testCase always forces preview above, so this never fires for it either. This is a defensive safety net for writing into whatever the background inventory looks like - it is not what decides this tool's own output cadence; that is fixed below regardless of what fragmentCmd leaves behind.

#### 59.  The tool computes its own fixed 3-hourly (OUTPUT_GRID_INTERVAL_

*`execute()`*

The tool computes its own fixed 3-hourly (OUTPUT_GRID_INTERVAL_ SECONDS) time series across the whole bulletin span and writes a block at every point in it, splitting a coarser background block wherever a write lands inside one.  It never looks at the background Fcst Wind inventory's own block boundaries to decide where or how wide to write - see OUTPUT_GRID_INTERVAL_ SECONDS's comment in the tunables block for why.

`spanStart`/`spanEnd` are tau epochs and so should already sit on interval boundaries, but that is not trusted blindly: floor the start down and ceiling the end up to the nearest interval boundary, so the series is never a fencepost short of the bulletins' own limits even if a tau ever lands off-boundary.

#### 60.  Bounded within the selected range too, snapped the same

*`execute()`*

Bounded within the selected range too, snapped the same way: round the selected range's start UP and its end DOWN to the nearest interval boundary so nothing is ever written outside it, without clipping a boundary that already sits exactly on one (no fencepost gap either way).

#### 62.  One loop, one series: every point in `series` gets its own

*`execute()`*

One loop, one series: every point in `series` gets its own fixed-width block, written whether or not the background Fcst Wind inventory already has a block starting there.  A tau that lands off the interval's own boundaries never occurs in practice (every JTWC tau is itself a multiple of 3 hours), but nothing here depends on that - each `when` gets evaluated at its own instant via `interpolateTrack` regardless.

#### 63.  Every block this run writes comes from the same fixed-interval

*`execute()`*

Every block this run writes comes from the same fixed-interval series, so there is no longer a separate "updated" vs. "created" distinction to report - just the total written and the (always 3-hourly, by default) interval used.

### Parsing the bulletins

#### 22.  Reference date lives in the remarks block ("27AUG26."), on every

*`parseJTWC()`*

Reference date lives in the remarks block ("27AUG26."), on every fixture seen until today. Real, live counter-example: a JTWC bulletin (WTPN35 PGTW, SOULIK, extratropical transition) whose REMARKS opens straight into the synopsis with no DDMMMYY token anywhere - confirmed by inspecting the real product text, not assumed.

#### 23.  Fallback: no DDMMMYY anywhere in the bulletin. The WMO

*`parseJTWC()`*

Fallback: no DDMMMYY anywhere in the bulletin. The WMO abbreviated header line ("WTPN35 PGTW 242100") gives the reference DAY directly (24) but not month/year, so resolve those by combining that day with wall-clock "now" through the exact same rollover rule _dtg_to_epoch() already uses for every DTG in the bulletin against its own reference day - seeded from "now" instead of a remarks-derived date. A day far from today's rolls to the adjacent month/year, precisely as any other far-from- reference DTG already does.

### Track interpolation

#### 29.  Radii: still interpolated, for drawing the reported-radii rings on the

*`interpolateTrack()`*

Radii: still interpolated, for drawing the reported-radii rings on the map. A threshold missing at one end interpolates from zero, so a 64-kt ring that first appears at 24h grows in rather than popping. The wind FIELD no longer comes from fitting these interpolated values - see _fitTau()'s docstring - it is built from s.fit below instead.

### The vortex

#### 30.  vmax < threshold (not <=): a storm whose peak exactly equals a

*`resolveRmax()`*

vmax < threshold (not <=): a storm whose peak exactly equals a threshold (e.g. a 50kt storm reporting R50) still reaches it - JTWC would not report a radius for a threshold it hadn't reached, so only a *stale* radius (already below the storm's current threshold) should be excluded here.

#### 31.  A exists solely to make V continuous across ri, which the Users Guide

*`_gtcmProfile()`*

A exists solely to make V continuous across ri, which the Users Guide states in words. Continuity requires

```
     (rm/ri)**x1 == A * (rm/ri)**x2   ->   A = (rm/ri)**(x1 - x2)
```

The guide PRINTS A = (ri/rm)**x1 (rm/ri)**x2, which does not satisfy that except in the degenerate x1 == x2 case - it is a typo, or a superscript mangled in the PDF. Transcribing it literally left a mean +4.4 kt step at ri (max +44 kt) and made the GTCM field measurably rougher than the per-quadrant construction it replaced, which is the opposite of the reason for the switch. Caught by the coherence check in tests/tcwind_jtwc/verify_gtcm.py; see its radial-value-jump column.

#### 32.  No radii anywhere: climatology is all there is.  Guide step 2c

*`fitGTCM()`*

No radii anywhere: climatology is all there is.  Guide step 2c. (This is the guide's own eq. (5) climatology, rmc - not willoughbyRmax() - since that is what step 2c specifies and there is no fit at all here for willoughbyRmax's better per-storm skill to improve on.)

#### 34.  A bulletin (or best-track record) reporting ONLY 34 kt radii carries no

*`fitGTCM()`*

A bulletin (or best-track record) reporting ONLY 34 kt radii carries no information at all about core size - see fitGTCM()'s docstring - so rm is pinned to climatology rather than searched, whatever nfit is.  This check comes before the nfit-based identifiability logic below because it changes which parameter is free even in cases nfit alone would otherwise hand rm to the optimiser (up to 4 quadrants can all be 34 kt only, landing in what used to be the freeParams == 1 or == 2 branches).

#### 35.  If even the pinned-rm profile cannot reach 34 kt, the optimum lies

*`fitGTCM()`*

If even the pinned-rm profile cannot reach 34 kt, the optimum lies below GTCM_X_MIN and the bound clamps it there rather than letting rm drift outward to compensate - the miss is real and is left for the modelled-radius / never-reached accounting to record.

#### 36.  Only estimate what the reported radii can actually identify.  rm,

*`fitGTCM()`*

Only estimate what the reported radii can actually identify.  rm, x1 and x2 are three free parameters; a bulletin reporting two nonzero radii constrains two numbers.  Fitting all three to two targets leaves a whole manifold of exact solutions - every one scoring RMS 0.00 - and the optimiser lands on an arbitrary point of it.  On live TS 22W (KROVANH), two reported R34 quadrants produced rm 7.8 nm with x1 = x2 = 0.05: a wind field that barely decays with radius, drawn as a flat sheet chopped into a one-sided wedge by the asymmetry vector.  19% of two-target configurations did this.

So drop a parameter when the data cannot carry it.  The Users Guide is silent here - it only says climatology is used when NO radius is reported - but estimating an unidentifiable parameter is not something a least-squares fit should be asked to do.

#### 37.  And keep rm near climatology when the radii cannot pin it down

*`fitGTCM()`*

And keep rm near climatology when the radii cannot pin it down. The guide describes the climatological/CP rm as a first guess that is "adjusted to better fit" the reported radii - adjusted, not replaced. Unbounded, a thin fit walks rm outward chasing a threshold the symmetric vortex cannot reach: on the KROVANH case rm went to 92.8 nm against a climatological 40.8, putting the peak wind 90 nm off the centre. That happens whenever Vm - a falls below the threshold being fitted, which for a marginal storm with a fast translation is routine: 40 kt with a = 8.4 leaves a symmetric peak of 31.6 kt, below gale.

#### 38.  Step 3: release the asymmetry, size parameters fixed.  Candidates are

*`fitGTCM()`*

Step 3: release the asymmetry, size parameters fixed.  Candidates are bounded two ways: the GTCM_ASYM_MAX_DEV_KT deviation disk around the motion-derived first guess (ax0, ay0), as before, AND - new - the GTCM_ASYM_MIN_CAP_KT-floored magnitude cap around the ORIGIN.  The magnitude cap is what stops a one-sided radii report from starving the weak side; see its comment.  asymCap >= a always (1.5x with a floor), so (ax0, ay0) itself - magnitude exactly a - is always admissible, and the floor means the cap is never zero even when a is (a stationary storm can still pick up a modest asymmetry from the grid/Nelder-Mead search below, so this no longer needs an `if a > 0.0` guard).

#### 39.  Use the magnitude of the asymmetry vector actually applied, not the

*`_buildVortexGTCM()`*

Use the magnitude of the asymmetry vector actually applied, not the Schwerdt first guess fit["a"] - see _gtcmProfile()'s docstring. This is what makes the analytic field's peak over azimuth hit Vmax exactly at r = rm, whatever the fit's step 3 did to (ax, ay).

#### 40.  Modelled 34 kt radius per azimuth, for the insert footprint and taper

*`_buildVortexGTCM()`*

Modelled 34 kt radius per azimuth, for the insert footprint and taper. This depends on azimuth ALONE - fit/amag are the same everywhere on this grid - so solve it once on a fixed azimuth table (GTCM_R34_AZ_BINS bins) and interpolate onto the grid's own azimuths, rather than broadcasting the probe against every grid point. See GTCM_R34_AZ_BINS's comment: that broadcast used to cost grid_points x GTCM_R34_PROBE_MAX_NM, computed twice over (34 s, 6.9 GB peak on a 500x500 domain); this costs GTCM_R34_AZ_BINS x GTCM_R34_PROBE_MAX_NM regardless of grid size.

#### 41.  Interpolate the crossing rather than snapping to the probe grid. ...

*`_buildVortexGTCM()`*

Interpolate the crossing rather than snapping to the probe grid.  probe[last] is the last sample still AT or ABOVE 34 kt, so the field there is >= 34 while the taper below restarts at exactly 34 - the difference lands as a step at the footprint boundary.  On a 1 nm probe that was a 3.36 kt mean jump, which made this taper the largest single source of roughness in the GTCM field, larger than anything in the vortex itself.  Solving for the exact radius where the field equals 34 makes the boundary continuous by construction.

#### 42.  Where the profile never reaches 34 kt at all - a weak system, or a

*`_buildVortexGTCM()`*

Where the profile never reaches 34 kt at all - a weak system, or a quadrant of a marginal one where the asymmetry vector opposes the flow after the Vm-a reduction - anchor the footprint on the LOCATION OF THE PROFILE'S OWN PEAK on that azimuth, not a fixed 3*rm.  This used to jump straight to 3*rm the moment the peak fell even 0.01 kt short of 34, while r34_exact above approaches the peak's own radius as the peak approaches 34 from above (right at the threshold the outermost >=34 kt point IS the peak, by definition).  So "peak location" is the r34_exact branch's own limit, and switching to it there makes r34(az) continuous across the anyAbove boundary instead of stepping between two radii that can differ by 100+ nm.

This boundary is not a rare edge case: the 34 kt targets that drive the fit (_gtcmTargets, weighted 5x) sit exactly at the quadrant bisectors (QUAD_AZ), so the fit is, by construction, trying to land the field as close to 34 kt as the least-squares average allows AT those azimuths. For a marginal storm that means the peak-over-r frequently straddles 34 kt right around a bisector, which is exactly where tests/tcwind_jtwc/verify_gtcm.py's azimuthal-kink estimator samples. The 3*rm cliff there - not the fixed-bin r34(az) table below, which reproduces this jump (or its absence) faithfully at any resolution - was the azimuthalKinkKtPerDeg regression this fix addresses; confirmed by recomputing r34 exactly per grid azimuth (bypassing the table entirely), which reproduced the same jump.

#### 43.  Anchor the taper on the field's OWN value at r34, not on a constant 34

*`_buildVortexGTCM()`*

Anchor the taper on the field's OWN value at r34, not on a constant 34. Where the field does reach 34 kt these are the same number, because r34 is solved as the radius where it does.  Where it never reaches 34, r34 is now the profile's own peak location on that azimuth (see above), so the anchor there is the peak wind itself, just short of 34 - anchoring on a constant 34 instead made the field jump UP at that radius: a 30 kt system came out with its peak of 34 kt sitting 113 nm from the centre instead of in its core.  Evaluating the profile at r34 handles both branches with one expression.

#### 44.  A reported quadrant radius already IS this storm's real asymmetry -

*`buildVortex()`*

A reported quadrant radius already IS this storm's real asymmetry - translation-driven or otherwise (shear, extratropical transition, ...) - so adding the synthetic motion vector below on top of it is double counting, not reinforcement. Confirmed against NHC's own Gridded TCM (WTCM/GTCM) Users Guide: WTCM never independently shapes a per-quadrant vortex from the radii and then ALSO adds a motion vector - it has exactly one asymmetry mechanism. It fits a single SYMMETRIC modified-Rankine vortex (Rappin et al. 2013) plus one wavenumber-1 motion term (Schwerdt 1979: a = 1.6*c^0.63, c = storm speed in kt) by least-squares against ALL the reported radii together (eq. 7 in the guide), not fit per quadrant the way this function's knot_r construction above is. (Its legacy predecessor, TCMWindTool, instead did what this function does - a per-quadrant radial fit, tangentially interpolated between quadrants - but with no separate motion vector either; WTCM replaced it rather than adding the motion term on top of it.) Skip the motion term whenever there is anything to be asymmetric about already; keep it as a shaping fallback for the radii-less case (weak/developing systems where only Vmax is known), so those aren't left perfectly circular.

#### 45.  WTCM also subtracts the asymmetry magnitude from Vm inside the vortex

*`buildVortex()`*

WTCM also subtracts the asymmetry magnitude from Vm inside the vortex itself (V = (Vm-a)*(...)) specifically so the vortex peak plus the vector added back in below sum to Vm, not Vm+a. Mirror that here: reduce the core/peak reference speed (knot_v[0], which the solid body and outer-taper formulas both key off) by the largest contribution the vector below can make, before adding that vector back in. knot_v only ever holds this single knot whenever asymFrac is nonzero here - radii present forces asymFrac to 0 above, and only the radii-less case ever reaches this - so nothing else in knot_v needs touching, and this is a no-op whenever it doesn't apply.

#### 46.  See the matching comment in resolveRmax(): vmax < threshold, not

*`buildVortex()`*

See the matching comment in resolveRmax(): vmax < threshold, not <=, so a storm whose peak exactly equals a reported ring's threshold (a 50kt storm reporting R50, say - not rare, since JTWC rounds Vmax to 5kt bins) still gets that ring built into its profile instead of the knot list jumping straight past it to the next-weaker ring.

#### 47.  x solves v1*(r1/r2)^x = v2 exactly, so the profile passes through

*`buildVortex()`*

x solves v1*(r1/r2)^x = v2 exactly, so the profile passes through the reported radius/threshold at r2 by construction - that boundary match is the entire point of solving for x per segment instead of using one global exponent. Floor at 0.0, not some higher value like the 0.05 this used to have: a storm whose Vmax barely clears the next ring's threshold (a common case - e.g. 35kt Vmax vs. a 34kt ring, or 65kt vs. 64kt) combined with a wide ratio (a large reported radius relative to Rmax, equally common) naturally needs a very shallow exponent to cover that distance on only a 1kt drop. A higher floor overrides that with an unrelated, steeper minimum decay rate, which breaks the boundary match: verified on a real bulletin (35kt TS, Rmax 36.5nm, R34 120nm reported in one quadrant) that the 0.05 floor made the modeled field fall under 34kt by ~65nm instead of the reported 120nm - a 46% shortfall the tool's own "fit check" against a sample of reported points can miss, since it only ever tests exactly at the reported radius (where, per this same bug, a sample landing there could tip into the next segment or the outer taper on floating-point noise and read correctly by accident - see compare_py_js.py's "Known benign residual"). v1 < v2 is unreachable (every segment is built strictly weaker than the last); v1 == v2 (the exact-threshold case above) is naturally x=0 here already, with no special-casing needed.

#### 48.  Outside the outermost ring the bulletin gives no information.  The

*`buildVortex()`*

Outside the outermost ring the bulletin gives no information.  The inner power law is the wrong thing to extrapolate: the R50-to-R34 slope describes the core-to-gale transition, and continuing it leaves 20 kt winds several hundred miles out.  Taper exponentially instead, anchored on the outermost ring.

#### 49.  knot_v[0], not snapshot.vmax: the same reduced core reference

*`buildVortex()`*

knot_v[0], not snapshot.vmax: the same reduced core reference used to cap mag above, so frac still reaches its ceiling (asymFrac) exactly at the peak - see the knot_v[0] reduction comment above.

#### 50.  asymFrac above is forced to 0 across the whole anchored band

*`buildVortex()`*

asymFrac above is forced to 0 across the whole anchored band (Rmax through the outermost reported ring) whenever any radius was reported, to avoid double-counting that ring's own real asymmetry. But Rmax itself is never a reported value - JTWC has no per-quadrant RMW - so strictly inside it (r <= Rmax) there is nothing to double-count. Give that zone its own, always-on vector, using the same MOTION_ASYMMETRY_FRACTION already vetted for the radii-less case above (not a new, separately-tuned number). Ramped to exactly 0 at the dead center (r=0, no direction to speak of there) and at Rmax's own boundary (continuous with the anchored band's forced 0 just outside it, so this introduces no seam at the ring itself). normalizePeak() below already runs unconditionally and never touches cells at or beyond the first REPORTED ring, so it recovers the exact Vmax peak afterward without any separate Vm-a-style correction here.

UNLIKE every other correction in this file, this one cannot be checked against IBTrACS: best-track RMW is a single scalar per storm-time, never per-quadrant, so there is no ground truth anywhere in the archive for how Rmax's own wind field actually varies by azimuth. This rests on the same wavenumber-1 mechanism already used for the radii-less fallback, not on anything verified here - see tests/tcwind_jtwc/README.md. Left the far-field taper (beyond the outermost ring) alone: it is already its own unverified heuristic (see the comment above the outer-taper block), and stacking a second one on top of it, more cheaply, less usefully (weaker winds, farther from anything operationally decided), was not worth doing.

#### 51.  Recover the peak the grid failed to sample.  The weight is 1 at the

*`buildVortex()`*

Recover the peak the grid failed to sample.  The weight is 1 at the center and 0 at the innermost reported ring, so nothing outside that ring is touched and the reported radii stay exact.  Solving for the factor at the strongest core cell makes the corrected peak land on Vmax in a single pass.

### Insertion and grid writing

#### 27.  None if the caller (e.g. a hand-built

*`__init__()`*

None if the caller (e.g. a hand-built snapshot in a verification script) never set one - _buildVortexGTCM() falls back to fitGTCM(self) then.

#### 33.  amag, not the closed-over `a`: see _gtcmProfile()'s docstring

*`err()`*

amag, not the closed-over `a`: see _gtcmProfile()'s docstring. During the rm/x1/x2-sizing steps ax==ax0, ay==ay0 always, so amag == a there by construction (no behaviour change). Step 3 below is the one place ax/ay actually move, and it needs the core's amplitude to track whatever it is testing, not stay pinned to the first guess it may be moving away from.

#### 61.  Tropical Depression strength: no organized 34kt-

*`buildFor()`*

Tropical Depression strength: no organized 34kt- or-greater wind field to speak of, and - per JTWC's own reporting practice - essentially never any wind radii to build one from even if there were. This tool's parametric vortex is built to represent an organized TC circulation; inserting it over the background model's own winds here would invent structure that isn't really there, not add real information. Leave the background untouched for this storm at this time - any other, stronger storm in the same bulletin is unaffected.

### pmsl: the storms moved to the warnings

#### 64.  pmsl follows the same warnings, through TCPressure

*module level*

The Wind grids put each storm where the warning has it; the pmsl grids still
had it wherever the model did, often 100 nm and more away and at the model's
depth.  With "Also move the storms in pmsl to the warnings:" on, the same run
moves the storm in every existing Fcst pmsl grid the warnings cover.  The
work is done by `TCPressure` (`GFE/utilities/TCPressure.py`), the module
CreateXML's gap fill uses for the same job south of the grid, so the grid and
the chart's gap move a storm identically.  It is a utility, not part of this
file: without it the Wind grids are built exactly as before and the status
bar says pmsl was left alone.  The preview goes to `pmslJTWC`, a temporary
parm made the way `WindJTWC` is; a Fcst run writes Fcst pmsl alongside Fcst
Wind.

#### 65.  `_movePmsl()`: each pmsl grid at its own time, one scale per storm

*`_movePmsl()`*

pmsl is adjusted in the grids that already exist, at their own cadence and
time ranges, not on the 3-hourly Wind series: the pmsl inventory is the
forecaster's, and nothing here should create or fragment it.  Each grid's
storms are interpolated to the grid's start time.  A storm counts if its
implanted vortex reaches the grid at all (its outer radius from the nearest
gridpoint), so one just south of the grid edge still has its outer isobars
moved.  Storm-times below 34 kt, and subtropical ones when those are skipped,
are left alone, exactly as the Wind grids leave them.

In each grid the grid's own vortex is found near the warning position, at its
center between gridpoints with the environment's tilt taken out, and the
symmetric part of its anomaly removed; the warning's vortex is implanted from
the same fitted wind profile the Wind grids use, through gradient-wind
balance.  The intensity scale that makes the tau-0 central pressure the
bulletin's is fixed at the earliest grid - the one nearest tau 0 - and
carried through the rest, so later grids are not re-anchored against a
different environment.  Run twice, the second run finds the first run's
storm and puts it back where it was: the harness holds that to 0.5 mb.

A grid low on the field's edge is not removed, since half a vortex cannot be
removed symmetrically; the status bar names any storm for which no grid low
was found, so a second low there can be looked for.

#### 66.  Off unless asked for

*`execute()`*

The dialog offers the pmsl option, set to Yes.  A varDict without the key -
one saved before the option existed, or built by a caller that never offered
it - leaves pmsl alone: a run that never showed the choice must never touch
a second weather element.

### Forecaster points past the warning, to day 7

#### 67.  Extending a warning to day 7

*module level*

Warnings stop at 120 h at most - a final or short warning sooner, often
72 h for a storm going extratropical - and the forecast runs to 168 h.  The
forecaster gives points past the warning's end - valid time, position, max wind, the four
34 kt radii, optionally a central pressure, and an extratropical flag - and
they are appended to the warning's own track, so everything downstream
(Wind, pmsl, the 3-hourly series) runs to the last point with nothing else
changed.  The run window already reaches 175 h.  Points are filed by storm
ID in `EXTENSION_STORE` (JSON) and pre-filled next run; a point the
warning now covers is dropped from the file, and a storm untouched for
`EXTENSION_KEEP_DAYS` is forgotten.  The default store is in the
forecaster's home directory: point it at a shared directory for the points
to survive a shift change.  The main-dialog choice is "Use saved" (apply
what is on file), "Edit" (the per-storm dialog), or "Off"; a varDict
without the key is Off.

#### 68.  Extratropical points: the asymmetry cap lifted

*module level, `fitGTCM()`*

The tropical fit caps the asymmetry vector at 1.5 times the motion-derived
value and searches within 10 kt of it, on purpose (note 38): a one-sided
report should not swing a tropical storm's field.  An extratropical storm's
gale field is one-sided by nature.  For a point flagged extratropical the
search reaches 30 kt from the motion vector and the cap rises to 0.45 times
the max wind.  On a slow storm with 34 kt radii of 300/250/60/40 nm this
takes the fit error from 4.4 kt to 1.2 kt and the strong side from about
245 nm to 320 nm.  The weak side still comes out larger than reported
(about 115/80 nm for 60/40): a symmetric profile plus one uniform vector
cannot make gales vanish on one side.  For a fast storm the motion vector
already supplies the asymmetry and nothing changes.

The wind fit's known limit for broad weak systems applies with full force
to extratropical storms: a 35-45 kt storm whose gales reach far out cannot
be fit (the profile would need an exponent below GTCM_X_MIN), and its 34 kt
extent comes out well short of the reported radii.

#### 69.  `_askExtension()`: the points-to-day-7 dialog

*`_askExtension()`, `extensionTimes()`*

One dialog per live storm, in time order: saved points still past the
warning, plus an empty row every EXTENSION_STEP_HOURS (12) after the
warning's initial time, from its last time to EXTENSION_LAST_HOUR (168), at
each time no saved point already holds.  A 120 h warning gets four rows; one
that stops at 72 h gets eight, so the gap to day 7 can be filled.  Every
row is optional: fill the times that matter and the track is interpolated
between them.  All entries are text boxes parsed here, so "38.5N", "165E",
"170W", "300 250 60 40" are all accepted; a row whose latitude is blank is
no point, so blanking it deletes a saved point.  A row that cannot be read
is skipped and named on the status bar; Cancel stops the run.

#### 70.  The forecaster's central pressure

*`_movePmsl()`, `TCPressure.relocateStorms()`*

Between two points with a pressure, the target is interpolated at full
weight.  From the warning's last time - depth from the winds through the
tau-0 scale - to the first point with a pressure, the target's weight ramps
from 0 to 1, so the depth hands over smoothly.  The vortex keeps its shape
from the wind profile and is scaled to reach the target, within 0.3-3.0
(an extratropical storm's pressure fall is often far from what its winds
balance); a target out of reach is reported and the warning's depth kept.

#### 71.  Extratropical storm-times follow the radio, in pmsl too

*`execute()`*

An extratropical point is flagged the way the parser flags a warning's own
transition, so "Subtropical / extratropical systems: Skip" leaves it out of
Wind, and pmsl now follows the same choice: with Include, the storm is
moved in pmsl at those times as well, where before the pmsl step always
left a flagged storm as the model had it.

#### 72.  One storm, two basins

*`dropDuplicateStorms()`*

With more than one basin ticked, a storm crossing a basin boundary can be
in both: CPHC's last advisory and JTWC's first warning sit in textdb
together for a while, and two bulletins for one storm would put two
vortices on the grid.  At the newer bulletin's initial time, the older one's
track is compared with it: the same name within 300 nm, or - when either is
unnamed - within 60 nm, is the same storm, and the older bulletin is
dropped and named on the status bar.  Two named storms with different names
are never merged, however close, so a Fujiwhara pair survives.
`TCPressure.readWarnings()`, which reads every basin for CreateXML's gap
fill, uses the same function.

### The background outside the storm

#### 73.  Outside R34 the background is only ever raised

*module level, `insertStorms()`, `execute()`*

The background Wind is the forecaster's, set before the tool runs; the tool
puts the warning in and nothing else.  Inside the storm's 34 kt radius the
warning's winds replace the background.  Outside it they fade to nothing
by MAX_INSERT_RADIUS_FACTOR (1.5) x R34, with a cos^2 taper, and go in only
where they beat the background.  On LEE at tau 0: +24 kt just outside R34
on a 10 kt background, +3 kt by 1.4 x R34, nothing past 1.5 x.

Two things that used to lower it are gone.  A 30 kt background cap out to
5 x R34 was meant to flatten a model's misplaced copy of the storm, and
flattened any front or other gale area in that ring with it - a 40 kt band
400 nm from LEE came out at 30 kt.  BACKGROUND_CAP_KT is now None.  And the
edge smoothing averaged across the seam, both sides: it now smooths only
the storm's side, and never takes a point below the background, since
averaging winds that point different ways cancels speed.  The harness
holds this end to end, with a front's 45 kt band beside LEE.

#### 74.  A forecaster point's 34 kt line follows its four radii

*`_buildVortexGTCM()`, `shapeWeightAt()`*

GTCM is a symmetric profile plus one uniform vector, so whatever four radii
it is fit to, its 34 kt line comes out a circle shifted toward the strong
side: 300/250/60/40 nm came out 338/341/114/84.  Warnings keep that by
design (note 38).  At a forecaster's point past the warning the four radii are the
forecaster's own, so they are followed: along each azimuth, distance is
rescaled by the ratio of the field's own 34 kt radius to the target there,
and the field is evaluated at the rescaled distance.  The target is 85 % of
the quadrant radii (SHAPE_RADIUS_FACTOR, the warnings' GTCM_QUAD_AVG_FACTOR:
a radius is the quadrant's maximum extent, the line its average), at the
quadrant centres, linear between, wrapping.  For 300/250/60/40 nm the 34 kt
line lands at about 255/213/51/34 nm, where the unshaped field gave
338/341/114/84 - the strong side reached past the radii, the weak side
nearly twice them - while the profile, its peak and the decay outside keep
their fitted form along each line.  The
rescaled distance is what the insertion sees too, so the core, the fade to
1.5 x R34 and the footprint follow the new shape.  The scale is held to
0.25-4.  From the warning's last time to the first forecaster point it
fades in (scale ** weight, weight 0 to 1), so nothing jumps at 120 h;
inside the warning nothing changes.  Pressure stays symmetric: the pmsl
vortex is built from the symmetric profile (TCPressure).

### Extended docstrings

Each function keeps its one-paragraph summary in the source.
The detail that followed it is here, under the function name.

#### `parseJTWC()`

`nowSecs` is unix seconds for "now"; only consulted by the no-DDMMMYY fallback below (real wall clock when omitted - callers pass it only to pin the fallback for a deterministic test). It plays no part at all when the bulletin carries a normal DDMMMYY reference date.

Returns (taus, header) where header is a dict of odds and ends.

#### `parseTCM()`

Every downstream consumer - interpolateTrack(), fitGTCM(), buildVortex(), insertStorms(), the grid writing - works on either parser's output unmodified, which is the whole reason this returns the identical shape rather than something TCM-shaped.

`nowSecs` is accepted and ignored.  parseJTWC() needs it because a WTPN warning can omit the DDMMMYY reference date from its REMARKS block and has to fall back on the WMO header day plus wall-clock now; a TCM always carries its own issuance date (difference 1), so there is nothing to guess and no clock dependency here.  The argument exists so a caller can dispatch to either parser without special-casing the signature.

Header fields carry adapted meanings, since the products name things differently: systemType     the advisory's own type word (HURRICANE, ...) stormId        ATCF basin+number ("AL13", "EP09").  JTWC's stormId is a basin-suffixed number ("22W"); NHC's text never repeats a short id, so this is the nearest stable per-storm identifier the product actually carries. stormName      the name from the title line ("LEE") warningNumber  the FORECAST/ADVISORY NUMBER pressureMb     from (ESTIMATED) MINIMUM CENTRAL PRESSURE refDate        (day, month, year) off the issuance line basin          'AT', 'EP' or 'CP'.  Extra to parseJTWC()'s header shape, so callers that do not know about it can ignore it safely.

#### `parseBulletin()`

Returns (taus, header, kind) where kind is "tcm" or "jtwc".  Callers that already know which product they hold can still call parseTCM() or parseJTWC() directly.

#### `_fitTau()`

interpolateTrack() used to fit the LINEARLY INTERPOLATED radii at the requested epoch instead of this. That manufactures targets nobody reported: a threshold missing at one tau interpolates from zero, so a 64-kt ring that has not appeared yet shows up a few nm wide midway to the tau where it does, and the shared (rm, x1, x2) fit swings to chase it - on one probed 12h span that pulled rm from 35 nm down to 8.5 nm and back up, non-monotonic, for a storm whose reported radii only grew smoothly. fitGTCM() needs nothing a Tau doesn't already carry (vmax, lat, motion, radii - the same fields interpolateTrack() puts on a Snapshot), so each tau is fit exactly once, from what JTWC actually reported at that tau, and interpolateTrack() blends the two RESULTS instead of blending their inputs and re-fitting.

#### `willoughbyRmax()`

Same functional form as Willoughby et al. (2006) - exponential in intensity and latitude - but refit against 13,834 real JTWC WestPac best-track records (2005-2024, IBTrACS, agency jtwc_wp - see besttrack_common.MIN_SEASON for why 2005, not 2001) rather than Willoughby's original Atlantic coefficients (A=46.4, B=-0.0155, C=0.0169). Those underestimated JTWC's own post-season RMW by ~10 nm on average across this dataset (worst for weak systems); this refit's out-of-sample bias on a held-out 20% of storms (never used for fitting) is -1.9 nm, MAE 9.0 nm, vs -9.4 nm / 12.4 nm for the original coefficients over the same held-out storms. See tests/tcwind_jtwc/fit_westpac_rmax.py, which produced these coefficients and reports the full validation, and tests/tcwind_jtwc/verify_besttrack_rmax.py, which reproduces the original comparison this replaces.

#### `resolveRmax()`

JTWC never gives Rmax.  willoughbyRmax() is fit to WestPac best-track data and is unbiased on average (see verify_besttrack_rmax.py), but a 2-parameter (intensity, latitude) regression has essentially no skill predicting any *individual* storm's Rmax, especially a weak one - the reported radii, when there are any, are real per-storm information the regression cannot have, so they win.

#### `_azimuthalRadii()`

A 000 NM quadrant means the profile never reaches that speed there, not that the radius is zero.  Collapsing it onto the core produces the steep gradient that is actually implied.

#### `_gtcmProfile()`

V = (Vm-a)(r/rm)            r  < rm (Vm-a)(rm/r)**x1        rm <= r < ri A(Vm-a)(rm/r)**x2       ri <= r          A = (ri/rm)**x1 (rm/ri)**x2

A makes V continuous across ri.  Two exponents, not one: the inner and outer parts of a real vortex do not share a decay rate, and forcing them to was the single biggest error in the pre-guide reconstruction of this.

`a` must be the magnitude of the (ax, ay) asymmetry vector actually applied on top of V by _gtcmUV(), not necessarily the Schwerdt estimate fitGTCM() also computes under the same name. As azimuth sweeps 360deg at a fixed r, |wind| = |V*t_hat + (ax, ay)| traces a full circle of radius V centred on (ax, ay), so its maximum over azimuth is V + |(ax, ay)|. Passing the actual |(ax, ay)| here makes that V + |(ax, ay)| equal Vmax exactly at r = rm - (Vmax - |(ax, ay)|) + |(ax, ay)| = Vmax - regardless of what the fit's step 3 did to (ax, ay). Passing the fixed Schwerdt `a` instead (the first guess/cap fitGTCM() returns) only gives that identity when (ax, ay) never moved from its motion-derived first guess; once step 3 shrinks it - which it is free to do, to reduce wind-radius error - the analytic peak fell up to ~15% short of Vmax with no way for NORMALIZE_CORE_PEAK to reach it (its weight is 0 at r = rm, exactly where the shortfall lives). Every caller of this function for the GTCM field or its r34 probe must pass the actual |(ax, ay)|, computed once as amag = hypot(fit["ax"], fit["ay"]); only fitGTCM()'s own rm/x1/x2-sizing steps, which hold (ax, ay) at the first guess, may pass the plain Schwerdt value (and get the same number either way, since |(ax0, ay0)| == a by construction).

#### `_gtcmUV()`

The guide writes u = ax - V sin(theta), v = ay + V cos(theta) with theta measured counterclockwise from east.  This file carries azimuth as a compass bearing from the centre, and theta = 90 - bearing, so sin(theta) becomes cos(bearing) and cos(theta) becomes sin(bearing).

The guide is NHC's, so it only ever describes the northern hemisphere. JTWC warns on southern-hemisphere basins too, where the tangential flow reverses; `sign` handles that.  The asymmetry vector is not reversed - it still points with the motion.

#### `_gtcmTargets()`

Reported radii are the maximum extent in the quadrant; the vortex is fit to the quadrant average, so each radius is scaled by GTCM_QUAD_AVG_FACTOR first.  Weights follow eq. (7): five on the 34 kt points, one elsewhere.

#### `fitGTCM()`

Returns dict(rm, ri, x1, x2, ax, ay, a, n, freeParams, rms, rmSource). Users Guide steps 2b-3: climatological first guess from (5)/(6); ri at the median reported radius; (rm, x1, x2) by weighted least squares on WIND error (7); then ax/ay released within GTCM_ASYM_MAX_DEV_KT of that first guess, size parameters held fixed, but only among candidates whose magnitude |(ax, ay)| does not exceed max(1.5 * a, GTCM_ASYM_MIN_CAP_KT) - see that constant's comment.  The magnitude cap binds first whenever it is tighter than the deviation radius, which for anything but a fast-moving storm it is.

rmSource is "fit" unless the target set contains no 50/64 kt radii, in which case it is "climatology": a bulletin (or best-track record) reporting ONLY 34 kt quadrants carries no information at all about core size - a tight eye and a broad one can report the same R34 ring - so rm is pinned to willoughbyRmax(vmax, lat) (the WestPac-refit RMW regression, about -2 nm bias against best-track RMW) instead of being searched, and only the shared decay exponent is fit.  If even that pinned-rm profile cannot reach 34 kt at any target - a broad, weak system, e.g. Vmax 35 kt with R34 150 nm, needs an exponent below GTCM_X_MIN to flare out that far - the exponent is clamped at GTCM_X_MIN rather than letting rm move to compensate; the resulting miss is left for the residual/never-reached accounting downstream to record.

#### `_buildVortexGTCM()`

Two deliberate departures from the guide, both documented rather than silent:

* The guide's grids are missing outside the 34 kt radii and NHC leaves the blend to the receiving office.  This tool inserts into a background instead, so the profile is tapered exponentially beyond the modelled 34 kt radius, as the "perquad" construction does.  A bare Rankine tail decays too slowly to terminate on its own. * Step 4's boundary-layer/land-roughness reduction is NOT implemented. It needs the USGS land-surface database, which this procedure does not have.  The field is therefore marine-exposure everywhere, and will be too strong over land.

#### `insertStorms()`

No blending.  Inside its R34 each warning wins outright, so the 34, 50 and 64 kt contours land on JTWC's reported radii.  Between R34 and the outer limit (1.5 x R34) the storm's winds fade to nothing and go in only where they are stronger than what is already there, which puts each seam where the two fields are equal and keeps the speed continuous without averaging anything.  Outside R34 the background is never lowered (note 73).

Storms are applied outer-first, then cores, so a core always survives a neighbouring storm's tail.  Where two storms genuinely overlap, the stronger wind wins rather than the last one processed.

Each storm is a dict with vMag, vDir, r, r34 and limitFactor. Returns (mag, dir, footprint, coreMask).

#### `_retrieveBulletin()`

Falls back to the command-line textdb, which is the retrieval path already in use at OPC for these PILs.  Uses Popen-style arguments rather than capture_output/text so it works on the older Python in the AWIPS stack.

#### `_trBounds()`

Handles both the Python TimeRange wrapper and a raw Java TimeRange, which turn up depending on which call produced it.

#### `_fcstInventory()`

getWEInventory belongs to TropicalUtility, not SmartScript, so the SmartScript path is getGridInfo.  Both are tried, since a site may have a base class that provides either.

#### `_storeGrid()`

GFE builds a temporary weather element on demand when createGrid names one that is not in the configuration, provided the parm metadata is supplied.  Older signatures reject those keywords, so fall back to the plain call.

#### `_seamMask()`

Same construction GTCM uses: smooth a 0/1 footprint and keep the values strictly between.  Every storm's core is excluded, so the smoother can never touch a wind field the warnings specify.
