"""The HVTL tendency index, demonstrated on a synthetic pair of storms.

The claim this figure tests: after extratropical transition completes, the
sign of dHVTL/dt separates a low that is secluding (rebuilding a shallow
warm core, winds about to reintensify) from one decaying to a cold core --
and it separates them EARLIER than HVTL's own crossing back above zero,
which is the event `cyclone_phase_space/README.md` names as the seclusion
signature.

Two storms are built from `lifecycle_comparison`'s own life cycle, so the
track, the grid, the vortex, the baroclinic environment and the dipole are
bit-identical between them. They differ in exactly one thing, the archetype
the vertical structure blends toward after hour 126:

- "seclusion": `blended_amp` unchanged -- deep cold core blending into
  `ARCHETYPES["shallow warm core (seclusion)"]`, the life cycle the article's
  figD/figE already show.
- "decay": the same blend held at `ARCHETYPES["deep cold core
  (extratropical)"]`, so no lower warm core ever returns.

Heights come from `lifecycle_comparison.build_heights` in both cases rather
than from a second copy of that logic here, so the two scenarios cannot
drift from each other or from the article's other figures; the scenario is
applied by temporarily rebinding that module's own `blended_amp`, which is
the single knob the two cases differ in (see `scenario_amp`).

HVTL is the operational gridded field, `cps_HartCPS.executeBand3` on
925/850/700, exactly as the installed `cps_HVTL.xml` computes it. The
tendency is the plain 12 h difference of that field, which is what a
derived parameter using `ftime`/`timeShift="-43200"` would return -- see
`cyclone_phase_space/docs/TIME_ACCESS.md`. It is blank for the first two
frames because there is no frame 12 h earlier, the same forecast-hour-0
hole that document describes.

What it shows (the printed numbers, on this synthetic pair):

- ET completes (HVTL crosses below 0) at hour 108. Both storms are
  identical up to hour 126, so nothing before then can separate them.
- After that, peak 12 h tendency is +152 m for the secluding storm and
  +29 m for the decaying one.
- **Sign alone does not work.** The decaying storm turns positive at hour
  133, only 2 h after the secluding one, as its cold core settles and the
  vortex broadens. A field thresholded at "> 0" would fire on both.
- At a +50 m threshold the separation is clean: the secluding storm fires
  at hour 135 and the decaying one never does.
- That firing leads HVTL's own crossing back above zero -- the event the
  README names as the seclusion signature -- by **17 h**.

The threshold is the finding here, not an afterthought. It is the same
reason `HCPSidx` keeps a neutral band: "a continuous index needs one to
avoid painting noise as a trend". 50 m per 12 h is what separates these
two synthetic profiles and is NOT a calibrated value -- a real threshold
has to come off the case set, per the warm seclusion project's own rule
that no threshold in a product is one taken from a synthetic test.

Run from this directory:

    python3 seclusion_tendency.py

Writes two files next to this one:

- figF_seclusion_tendency.png (300 dpi): the final frame, plus the printed
  lead time.
- seclusion_tendency.gif: 29 frames, one per 6 h, 500 ms per frame. Two
  rows (seclusion, decay) by three columns: the gridded HVTL field, the
  gridded 12 h HVTL tendency, and the storm-center trace of both against
  forecast hour.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lifecycle_comparison as lc  # noqa: E402
import diagram_style as ds  # noqa: E402
from band_comparison import ARCHETYPES  # noqa: E402

PNG_PATH = HERE / "figF_seclusion_tendency.png"
GIF_PATH = HERE / "seclusion_tendency.gif"

TENDENCY_HOURS = 12.0  # the timeShift the D2D field would use (-43200 s)
# Sign alone does not separate the two cases: the decaying storm produces a
# brief positive bump of its own as the cold core settles (see the module
# docstring). The index needs a magnitude threshold, the same reason
# HCPSidx keeps a neutral band -- "a continuous index needs one to avoid
# painting noise as a trend" (cyclone_phase_space/README.md).
THRESHOLD_M = 50.0
SCENARIOS = ("seclusion", "decay")
SCENARIO_TITLE = {
    "seclusion": "Warm seclusion: lower warm core rebuilds",
    "decay": "Cold-core decay: it never comes back",
}

# Diverging ramps through a neutral tone, anchored at 0, in the article's own
# colors (diagram_style/lifecycle_comparison): cold core blue, warm core red
# for HVTL itself; a separate purple/green pair for the tendency so the two
# map columns cannot be mistaken for each other at a glance.
HVTL_CMAP = LinearSegmentedColormap.from_list("hvtl", [lc.BLUE, "#f4f3ee", lc.RED])
TEND_CMAP = LinearSegmentedColormap.from_list("tend", ["#6d4aa7", "#f4f3ee", "#1d7f6e"])
for _cm in (HVTL_CMAP, TEND_CMAP):
    _cm.set_bad(alpha=0.0)

SEC_COLOR = lc.RED
DEC_COLOR = lc.BLUE


# --------------------------------------------------------- the one knob
def scenario_amp(scenario, base):
    """`base` (lifecycle_comparison's own `blended_amp`), or the decay
    variant of it.

    The decay variant is that function with its final stage removed: from
    hour 126 on it holds `ARCHETYPES["deep cold core (extratropical)"]`
    instead of blending into the seclusion archetype. Everything before
    hour 126 -- the whole transition -- is identical, so the two storms are
    the same storm until the moment the outcome is decided.

    `base` is passed in rather than looked up, because the returned
    function runs while `lifecycle_comparison.blended_amp` is rebound to
    it: reading that name at call time would find this function itself.
    """
    if scenario == "seclusion":
        return base

    def decay_amp(t):
        if t <= 126.0:
            return base(t)
        return np.array(ARCHETYPES["deep cold core (extratropical)"], float)

    return decay_amp


@contextlib.contextmanager
def amp_override(scenario):
    """Run the body with `lifecycle_comparison.blended_amp` rebound to this
    scenario's version, so `lifecycle_comparison.build_heights` -- the one
    height builder the article's other figures use -- produces this
    scenario's fields without a second copy of it living here.
    """
    original = lc.blended_amp
    lc.blended_amp = scenario_amp(scenario, original)
    try:
        yield
    finally:
        lc.blended_amp = original


# ------------------------------------------------------------- compute
def run_scenario(scenario, hours, lats, lons, headings, speeds, grid, psfc):
    """(hvtl_fields, center_trace) for one scenario.

    `hvtl_fields` is a list of the gridded HVTL array at each hour;
    `center_trace` the value at the grid point nearest the storm center.
    """
    lat_vals, lon_vals, lat2d, lon2d, dx, dy = grid
    fields, trace = [], []
    with amp_override(scenario):
        for t, clat, clon, hdg, spd in zip(hours, lats, lons, headings, speeds):
            z = lc.build_heights(t, clat, clon, lat2d, lon2d, hdg, spd, lc.NEEDED_LEVELS)
            hvtl = lc.hc.executeBand3(z[925], z[850], z[700], psfc, dx, dy,
                                       lc.RADIUS_KM, 925.0, 850.0, 700.0)
            ci = int(np.argmin(np.abs(lat_vals - clat)))
            cj = int(np.argmin(np.abs(lon_vals - clon)))
            fields.append(hvtl)
            trace.append(float(hvtl[ci, cj]))
    return fields, np.array(trace)


def tendency(fields, hours):
    """The 12 h difference of `fields`, frame by frame, as the D2D field
    would compute it: field(t) - field(t - 12 h), and None where there is
    no frame 12 h earlier (the forecast-hour-0 hole).
    """
    step = float(hours[1] - hours[0])
    back = int(round(TENDENCY_HOURS / step))
    return [None if i < back else fields[i] - fields[i - back] for i in range(len(fields))]


def trace_tendency(trace, hours):
    """`tendency` for a 1D center trace: NaN where there is no earlier frame."""
    step = float(hours[1] - hours[0])
    back = int(round(TENDENCY_HOURS / step))
    out = np.full(len(trace), np.nan)
    out[back:] = trace[back:] - trace[:-back]
    return out


def first_crossing(hours, values, level=0.0, positive=True, after=None):
    """Hour of the first frame at or after `after` where `values` crosses
    `level` upward (or downward), by linear interpolation between that
    frame and the one before it, or None if it never does. NaNs are
    skipped.

    `after` matters: this index is only meaningful once extratropical
    transition has completed, and an ungated search finds the tropical
    phase's own intensification instead.
    """
    for i in range(1, len(values)):
        if after is not None and hours[i] <= after:
            continue
        a, b = values[i - 1], values[i]
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        crossed = (a <= level < b) if positive else (a >= level > b)
        if crossed:
            frac = (level - a) / (b - a)
            return float(hours[i - 1] + frac * (hours[i] - hours[i - 1]))
    return None


# -------------------------------------------------------------- plotting
def draw_map(ax, lon_vals, lat_vals, field, cmap, vmax, clon, clat, track_lon, track_lat, title):
    """One map panel: the field, the track so far, and the storm center."""
    ax.set_facecolor("#f7f6f2")
    if field is None:
        ax.text(0.5, 0.5, "no frame 12 h earlier", transform=ax.transAxes, ha="center",
                va="center", color=ds.TEXT_SECONDARY, fontsize=8, style="italic")
    else:
        ax.pcolormesh(lon_vals, lat_vals, np.ma.masked_invalid(field), cmap=cmap,
                      norm=TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax), shading="auto")
    ax.plot(track_lon, track_lat, color=ds.TEXT_DARK, lw=0.8, alpha=0.55, zorder=3)
    ax.plot([clon], [clat], marker="o", ms=5, mfc="none", mec=ds.TEXT_DARK, mew=1.3, zorder=4)
    ax.set_title(title, fontsize=8, color=ds.TEXT_DARK, pad=3)
    ax.set_xlim(lon_vals[0], lon_vals[-1])
    ax.set_ylim(lat_vals[0], lat_vals[-1])
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(ds.GRID_COLOR)


def draw_trace(ax, hours, upto, common, series, ylabel, zero_label, marks, ylim, threshold=None):
    """One trace panel.

    `common` is the hour up to which both scenarios are the same storm;
    that stretch is drawn once in grey rather than as two overlapping
    colored lines that imply a difference there is none. `marks` is a list
    of (hour, color, label) verticals, and `threshold`, when given, draws
    the index's firing level.
    """
    ax.set_facecolor("white")
    # Fixed across every frame, so the animation does not rescale under the
    # curve as it is drawn.
    ax.set_ylim(*ylim)
    ax.axhline(0.0, color=ds.TEXT_DARK, lw=0.9, zorder=2)
    if threshold is not None:
        ax.axhline(threshold, color=ds.TEXT_SECONDARY, lw=0.9, ls=(0, (4, 3)), zorder=2)
        ax.text(hours[0] + 3, threshold, f"  index fires: +{threshold:.0f} m",
                fontsize=6.2, color=ds.TEXT_SECONDARY, ha="left", va="bottom")
    for hour, color, label in marks:
        if hour is None or hour > upto:
            continue
        ax.axvline(hour, color=color, lw=0.9, ls=(0, (2, 2)), alpha=0.8, zorder=2)
        ax.annotate(label, xy=(hour, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(2, -2), textcoords="offset points", fontsize=6.2,
                    color=color, rotation=90, ha="left", va="top", zorder=6,
                    bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.85))

    n = int(np.searchsorted(hours, upto, side="right"))
    nc = min(n, int(np.searchsorted(hours, common, side="right")))
    for values, color, label in series:
        ax.plot(hours[:nc], values[:nc], color="#8f8d86", lw=1.6, zorder=3)
        ax.plot(hours[nc - 1:n], values[nc - 1:n], color=color, lw=1.8, label=label, zorder=4)
        if n:
            last = values[n - 1]
            if np.isfinite(last):
                ax.plot([hours[n - 1]], [last], marker="o", ms=4,
                        color=color if n > nc else "#8f8d86", zorder=5)
    ax.text(hours[-1], 0.0, zero_label + " ", fontsize=6.2, color=ds.TEXT_SECONDARY,
            ha="right", va="bottom", style="italic")
    ax.set_xlim(hours[0], hours[-1])
    ax.set_xlabel("forecast hour", fontsize=7.5, color=ds.TEXT_SECONDARY)
    ax.set_ylabel(ylabel, fontsize=7.5, color=ds.TEXT_SECONDARY)
    ax.tick_params(labelsize=6.5, colors=ds.TEXT_SECONDARY)
    ax.grid(True, color=ds.GRID_COLOR, lw=0.6, zorder=0)
    ax.legend(fontsize=6.5, loc="lower left", frameon=True, framealpha=0.85,
              edgecolor="none")
    for sp in ax.spines.values():
        sp.set_color(ds.GRID_COLOR)


def render_frame(i, hours, grid, tracks, data, limits, stats):
    """The full 2x3 figure at frame `i`, returned as a PIL image."""
    lat_vals, lon_vals = grid
    track_lat, track_lon = tracks
    hvtl_vmax, tend_vmax = limits
    t = hours[i]

    fig, axes = plt.subplots(2, 3, figsize=(10.6, 5.6), dpi=110,
                             gridspec_kw=dict(width_ratios=[1.0, 1.0, 1.35]))
    fig.patch.set_facecolor("white")

    for row, sc in enumerate(SCENARIOS):
        draw_map(axes[row][0], lon_vals, lat_vals, data[sc]["fields"][i], HVTL_CMAP, hvtl_vmax,
                 track_lon[i], track_lat[i], track_lon[:i + 1], track_lat[:i + 1],
                 f"HVTL  ({sc})")
        draw_map(axes[row][1], lon_vals, lat_vals, data[sc]["tend"][i], TEND_CMAP, tend_vmax,
                 track_lon[i], track_lat[i], track_lon[:i + 1], track_lat[:i + 1],
                 f"12 h HVTL tendency  ({sc})")
        axes[row][0].set_ylabel(sc, fontsize=9, color=ds.TEXT_DARK)

    draw_trace(axes[0][2], hours, t, stats["common_hour"],
               [(data["seclusion"]["trace"], SEC_COLOR, "seclusion"),
                (data["decay"]["trace"], DEC_COLOR, "decay")],
               "HVTL at center  (m)", "warm core above this line",
               marks=[(stats["et_done"], ds.TEXT_SECONDARY, "ET complete"),
                      (stats["hvtl_back"], SEC_COLOR, "HVTL back above 0")],
               ylim=stats["ylim_hvtl"])
    draw_trace(axes[1][2], hours, t, stats["common_hour"],
               [(data["seclusion"]["trace_tend"], SEC_COLOR, "seclusion"),
                (data["decay"]["trace_tend"], DEC_COLOR, "decay")],
               f"{TENDENCY_HOURS:.0f} h HVTL tendency  (m)", "core rebuilding above this line",
               marks=[(stats["et_done"], ds.TEXT_SECONDARY, "ET complete"),
                      (stats["sec_fire"], SEC_COLOR, "index fires")],
               ylim=stats["ylim_tend"], threshold=THRESHOLD_M)

    # The payoff: the gap between the index firing and the event it predicts.
    if stats["sec_fire"] is not None and t >= stats["sec_fire"]:
        ax = axes[1][2]
        ax.axvspan(stats["sec_fire"], stats["hvtl_back"], color=SEC_COLOR, alpha=0.16, zorder=1)
        ax.annotate(f"{stats['lead']:.0f} h lead",
                    xy=(0.5 * (stats["sec_fire"] + stats["hvtl_back"]), 0.06),
                    xycoords=("data", "axes fraction"), fontsize=8, color=SEC_COLOR,
                    ha="center", va="bottom", weight="bold", zorder=6,
                    bbox=dict(boxstyle="square,pad=0.2", fc="white", ec="none", alpha=0.85))

    fig.suptitle(f"HVTL tendency separates seclusion from decay   |   forecast hour {t:.0f}",
                 fontsize=10.5, color=ds.TEXT_DARK, y=0.985)
    fig.text(0.5, 0.952, "same synthetic storm in both rows; they differ only in what happens "
             "after hour 126", fontsize=7.5, color=ds.TEXT_SECONDARY, ha="center", va="top")
    fig.tight_layout(rect=(0, 0, 1, 0.955))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("P", palette=Image.ADAPTIVE)


# ------------------------------------------------------------------ main
def main():
    hours = lc.make_hours()
    lats, lons, headings, speeds = lc.build_track_and_motion(hours)
    grid = lc.build_grid()
    lat_vals, lon_vals, lat2d, lon2d, dx, dy = grid
    psfc, _ = lc.env_fields(lat2d)

    data = {}
    for sc in SCENARIOS:
        print(f"computing {sc} ...", flush=True)
        fields, trace = run_scenario(sc, hours, lats, lons, headings, speeds, grid, psfc)
        data[sc] = dict(fields=fields, trace=trace,
                        tend=tendency(fields, hours),
                        trace_tend=trace_tendency(trace, hours))

    # Map color limits from the fields themselves, at the 99th percentile so
    # one extreme cell cannot wash the rest of the map out. (Taking them from
    # the center trace instead leaves the maps far too faint: the trace is a
    # single point, the field's typical magnitude is much smaller.)
    def field_vmax(key):
        vals = np.concatenate([
            np.abs(np.asarray(f, float)[np.isfinite(f)]).ravel()
            for d in data.values() for f in d[key] if f is not None
        ])
        return float(np.percentile(vals, 99.0))

    limits = (field_vmax("fields"), field_vmax("tend"))

    # The claim, as numbers. Both storms are identical until ET completes,
    # so everything below is measured from that hour on.
    sec, dec = data["seclusion"], data["decay"]
    et_done = first_crossing(hours, sec["trace"], positive=False)
    print()
    print(f"ET completion (HVTL first crosses below 0): hour {et_done:.0f}")

    after = hours > et_done
    sec_peak = np.nanmax(sec["trace_tend"][after])
    dec_peak = np.nanmax(dec["trace_tend"][after])
    print(f"  peak tendency after that -- seclusion {sec_peak:6.1f}, "
          f"decay {dec_peak:6.1f}  m / {TENDENCY_HOURS:.0f} h")

    # Sign alone is ambiguous: report where each case first turns positive,
    # then where each first passes the threshold.
    sec_sign = first_crossing(hours, sec["trace_tend"], 0.0, True, after=et_done)
    dec_sign = first_crossing(hours, dec["trace_tend"], 0.0, True, after=et_done)
    print(f"  first positive           -- seclusion {sec_sign}, decay {dec_sign}"
          "   <- sign alone fires on both")

    sec_fire = first_crossing(hours, sec["trace_tend"], THRESHOLD_M, True, after=et_done)
    dec_fire = first_crossing(hours, dec["trace_tend"], THRESHOLD_M, True, after=et_done)
    hvtl_back = first_crossing(hours, sec["trace"], 0.0, True, after=et_done)
    print(f"  first past {THRESHOLD_M:.0f} m          -- seclusion "
          f"{sec_fire and round(sec_fire, 1)}, decay {dec_fire}   <- clean separation")
    print(f"  HVTL itself back above 0 -- seclusion {hvtl_back:.1f}")
    lead = None if (sec_fire is None or hvtl_back is None) else hvtl_back - sec_fire
    if lead is not None:
        print(f"\n  LEAD of the index over the crossing it predicts: {lead:.1f} h")

    def trace_ylim(key, pad=0.10):
        vals = np.concatenate([np.asarray(d[key], float) for d in data.values()])
        vals = vals[np.isfinite(vals)]
        lo, hi = float(vals.min()), float(vals.max())
        span = hi - lo
        return (lo - pad * span, hi + pad * span)

    stats = dict(et_done=et_done, sec_fire=sec_fire, hvtl_back=hvtl_back, lead=lead,
                 common_hour=126.0,
                 ylim_hvtl=trace_ylim("trace"), ylim_tend=trace_ylim("trace_tend"))

    frames = [render_frame(i, hours, (lat_vals, lon_vals), (lats, lons), data, limits, stats)
              for i in range(len(hours))]
    frames[0].save(GIF_PATH, save_all=True, append_images=frames[1:], duration=500, loop=0)
    print(f"\nwrote {GIF_PATH.name} ({len(frames)} frames)")

    fig_last = render_frame(len(hours) - 1, hours, (lat_vals, lon_vals), (lats, lons), data,
                             limits, stats)
    fig_last.convert("RGB").save(PNG_PATH, dpi=(300, 300))
    print(f"wrote {PNG_PATH.name}")


if __name__ == "__main__":
    main()
