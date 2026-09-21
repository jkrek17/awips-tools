# Can a D2D derived parameter read the previous forecast hour?

**Status: answered from the schema, not yet confirmed on a site.** The
mechanism exists and is documented; the spelling, the sign convention,
and the cost still have to be checked on the OPC build the way every
other field in this package was. `cps_probe_dZ12.xml` is the probe that
does that, and section 5 is what to record when it runs.

This is Phase 0 of the warm seclusion wind project, whose two strongest
candidate predictors -- central height tendency and HVTL tendency --
both need a field at more than one time. Everything else in that project
is gated on this answer, because a "no" moves both parameters out of
D2D and into an offline script.

---

## 1. The question

The five Hart fields are instantaneous: each one reads several
geopotential height levels at a single valid time and returns one grid.
A tendency is not. `dZ/dt` at forecast hour F needs the 1000 hPa height
at F and at F minus 12 (or 24) hours, in the same call.

Nothing in this package does that today, and the derived parameter
framework's usual picture -- a `<Method>` naming a Python function, a
list of `<Field>` elements handed to it as positional arguments -- has
no time in it anywhere. The `<Field>` elements in `cps_HVTL.xml` name a
parameter and a level, and that is all.

## 2. The answer: yes, with two attributes

The framework does carry time, in two attributes that are not used
anywhere in this package:

- `ftime` on `<Method>`, and
- `timeShift` on `<Field>`.

From the NWS AWIPS-2 Application Focal Point Course, Derived Parameter
Configuration Module, Appendix A: XML Schema, verbatim:

> **Method Tag**
>
> `dtime` -- Boolean (true/false). Checks the Field tags for a timeShift
> attribute and utilizes data for that field from any model run which
> has data at the specified offset.
>
> `ftime` -- Boolean (true/false). Checks the Field tags for a timeShift
> attribute and utilizes data for that field from the same model run but
> with a different forecast time.

> **Field Tag**
>
> `timeShift` -- The time offset in seconds to use when dtime or ftime
> in the Method tag is set to true. Just like in AWIPS 1, if the value
> is less than 60, it will use the intrinsic model time multiplied by
> this value.

So `ftime="true"` plus `timeShift` on the field to be shifted is exactly
the case the tendency parameters need: same model run, different
forecast hour, both grids delivered to one Python call as ordinary
positional arguments. No change to how a function is written.

## 3. `ftime` or `dtime`

`ftime` is the right one. It stays inside one model run, so the
difference it produces is a property of that forecast and nothing else.

`dtime` reaches into whatever run has data at the offset, which would
silently mix cycles. A "12 hour deepening rate" that is really the
current run's f012 minus the previous run's f012 is a different
quantity, and a worse one: it mixes the model's forecast evolution with
its run-to-run initialization changes. Do not use `dtime` for a
tendency.

`dtime` does have one use here, noted in section 6: it is the only way
to get a tendency at the start of a run.

## 4. The `< 60` rule

`timeShift` is in **seconds**, except that a magnitude below 60 is read
as a count of the model's own intrinsic timestep.

Use explicit seconds. `timeShift="-43200"` is an unambiguous 12 hours.
`timeShift="-1"` is "one model timestep back", which sounds appealingly
resolution-independent and is not. Model output spacing is not constant
across a run -- it coarsens at longer leads -- so the same `-1` would
mean one interval early in the forecast and a longer one later, and the
field would change meaning partway across it. A tendency needs a fixed
interval or its threshold means nothing.

Values to use:

| Interval | `timeShift` |
| :--- | :--- |
| 12 h | `-43200` |
| 24 h | `-86400` |

Both are multiples of the coarsest output spacing in normal use, so both
should land on an existing frame throughout a run. Confirm that on the
site's own model configuration rather than assuming it.

## 5. What the probe settles

Three things the schema documentation does not pin down, all of which
the probe answers in one load:

1. **Does `ftime` work on this build at all** -- whether the definition
   loads and the field appears in the Product Browser.
2. **The sign of `timeShift`.** The reference calls it a "time offset"
   and does not say which direction is positive. Negative for the past
   is the natural reading and matches the AWIPS 1 `offset` it inherits
   from, but it is a guess until a real field is on the screen. The
   probe is built so that the answer is visible rather than subtle: over
   a deepening low, `HdZ12` must be **negative**. If it comes out
   positive, the sign convention is the other way and every `timeShift`
   in the package flips.
3. **Whether an unshifted `<Field>` stays at the requested time.** The
   probe's first field carries no `timeShift`, on the reading that
   `ftime` shifts only the fields that ask for it. If instead the whole
   method shifts, the probe returns a field of zeros, which is equally
   unmistakable.

**How to read the result.** Load `HdZ12` on a GFS run containing a
cyclone that is known to have deepened:

| What you see | What it means |
| :--- | :--- |
| Negative over the deepening low | Working. `timeShift` negative is the past. |
| Positive over the deepening low | Working, sign convention reversed. Flip every `timeShift`. |
| All zeros | Both fields resolved to the same time. The shift is not being applied per-field. |
| Blank everywhere, at every hour | `ftime` is not honored on this build. See section 7. |
| Blank only before f012 | Expected. See section 6. |
| Field absent from the Product Browser | The definition did not load. Check `Difference` and the field spellings per the XML's own comments. |

Record the answer in `cyclone_phase_space/README.md`'s validation log,
with the run and the case, the same as every other field in this
package.

## 6. The forecast hour 0 hole

This is a real limitation and not a bug. With `ftime`, a 12 hour
tendency **cannot exist before f012**: there is no frame 12 hours
earlier in the same run. The field will be blank on every frame before
f012 and populated from f012 on.

That is acceptable for this project. The warm seclusion question is
about the 24 to 72 hours before transition completes, not about the
analysis hour. But it should be said plainly in the user guide when a
tendency field ships, because a forecaster who loads the field at f000,
sees nothing, and concludes it is broken will not load it again.

If a tendency at f000 is ever genuinely wanted, `dtime` is the only way
to get it, and it would be a different field with a different name --
not the same field quietly changing meaning at the start of the run.

## 7. Cost

Cheap, on the evidence available here; the probe measures it for real.

The arithmetic is a subtraction, which is nothing beside the sliding
window max/min that dominates the existing fields (about 2.6 s per
forecast hour for the full `executeHartClass`, per the technical
guide's performance section). The cost is an extra grid read per output
frame: one more 1000 hPa height field, the same size as the seven this
package already pulls for `HCPSidx`.

Two things to watch when the probe runs, because neither can be
predicted from here:

- **Whether the shifted grid comes from cache or from disk.** The
  frames on either side of the current one are usually already resident
  when a loop is being stepped through, in which case the extra read is
  free. A cold load may not be.
- **Whether a blank result is cheap.** Before f012 the framework has to
  fail to find a frame. If that failure is slow, the first frames of a
  loop will be slow.

Time a full loop with and without the probe field and record both
numbers against the 2.6 s baseline.

## 8. What this means for the project map

The Phase 0 gate is met in principle: the framework can do it, so
central height tendency and HVTL tendency stay in D2D and Phase 2 keeps
its full scope. The gate is not fully met until the probe has run on the
OPC build and the sign is known.

Nothing else in the warm seclusion project depends on the outcome. Phase
1's five structure fields are all instantaneous and can start now,
in parallel, exactly as the map has them.

## 9. Source

AWIPS-2 Application Focal Point Course, Derived Parameter Configuration
Module (`AWIPS_AFP_DerivParam_SxS_20140118.pdf`), Appendix A: XML
Schema, Method Tag and Field Tag, published on the NOAA Virtual Lab.

This is the configuration reference for the schema, not the source. It
is a 2014 document and the fields it describes are longstanding, but
this package's standing convention is to verify every spelling against a
base definition in
`/awips2/edex/data/utility/common_static/base/derivedParameters/definitions/`
on the site's own build before trusting it. The probe is that check.
