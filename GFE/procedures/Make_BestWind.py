"""
Make_BestWind - build the whole marine 10 m Wind grid in one run: a GFS/ECMWF
blend, then a lift in the storm cores.

RUN IT OVER AN OCEAN EDIT AREA.  The core lift was scored on water cells only
and lifts every cell of the edit area, land included.  Outside the edit area
the plain blend (no lift) is written, so select an area before you run it.

What it does, for every Fcst Wind grid in the selected time range
(if there are none, the grids the Wind time constraints lay out in it):

1. Reads the 10 m wind of the newest GFS run and the newest ECMWF run that
   have that valid time, plus each model's run 12 h and 24 h older at the
   same valid time (up to 6 runs).  A model grid that is not on the hour of
   the Fcst grid is interpolated in time from its two neighbours when they
   are no more than MAX_INTERP_GAP_HOURS apart.
2. Blends the speed, point by point.  Each current model (GFS, ECMWF) is
   weighted by how many of the runs sit near its speed (a Gaussian, 5 kt
   wide), so a model that stands alone against its own earlier runs and the
   other model counts for less.  Then it adds 0.3 x the spread of the runs
   (at most 5 kt), because the weighted mean runs weak in deep lows.
   Option "Lagged runs" Off: only the two current runs are used (weights and
   spread from those two).  Quicker and works when older runs are gone, but
   it is not the blend that was scored: with two runs the spread term is just
   0.15 x the GFS-ECMWF difference.  This is
   the "deterministic blend" of the marine wind page (rk.features.det_blend,
   without AIFS).
3. Direction is that of the mean wind vector of the two current runs.
4. Core lift (option, On by default): where the models already show a strong
   core, add a few knots.  The lift grows smoothly, no jumps.  Default
   trigger "Stronger of GFS/ECMWF": +0 kt at 38 kt of the stronger model,
   +6 kt at 42 kt, then +0 to +4 kt more between 48 and 52 kt (+10 kt from
   52 kt up).  Trigger "Blend's own wind": the same shape on the blended
   speed, ramps 36-40 kt and 44-48 kt (a blend runs weaker than its stronger
   model).  Direction is never touched.
5. HF core (option, Off by default; only with the core lift on): a further
   +0 to +6 kt as the stronger of GFS/ECMWF goes from 52 to 56 kt, but only
   where the GFS 925 mb wind x a stability factor (sea minus 2 m air below
   2 C: 0.70, 2-5 C: 0.79, 5 C or more: 0.83) is at least 55 kt, i.e. where
   the low-level jet can bring hurricane force down.  Not a blanket: it adds
   nothing where the models are under 52 kt or the air is too stable.  If the
   GFS 925 mb wind or temperatures are not found it is skipped and said so.

Missing data: a lagged run that is not on the server is left out and named in
the closing message.  If a model has no current run for a time, the other
model is used alone and the message says so.  If neither has one, that time is
left as it is and the message says so.

Units: worked in knots, converted from each parm's unit string (kt, m/s, mph)
and handed back in the Fcst Wind units.  If a D2D unit string is unknown, m/s
is assumed when the model's maximum speed is under 60, else knots; the message
says so.

Scores (held-out, against ASCAT, 5 held-out winter weeks Nov 2025 - Mar 2026,
5x5 deg storm tiles; marine-research studies/2026-11-06-gfe-wind-tool/findings.md):
  Blend alone: storm-force (48+ kt) catch Atlantic 35%, Pacific 22%.
  With the core lift, stronger-model trigger: storm-force catch Atlantic 75%,
    Pacific 64%; storm area 1.05x (Atlantic) and 1.23x (Pacific) ASCAT's;
    hurricane-force (64+ kt) catch in the Atlantic 59% at 0.92x ASCAT's HF area.
  Blend's own-wind trigger: storm-force catch Atlantic 76%, Pacific 64%;
    HF Atlantic 60%; gale-force areas exactly the blend's.
  HF core on: Atlantic HF catch 59% -> 70% (81 of 115 tiles), HF area 0.92x
    -> 1.67x ASCAT's (false HF tiles 37 -> 68; 0.96x on the tuning weeks);
    Pacific 3 -> 6 of 15.  Storm-force scores unchanged.  The 925 mb check
    cut false HF tiles by about 10% (Atlantic) and 40% (Pacific) against the
    same lift everywhere, for about one tile of catch.
  The marine wind page's Core Lifted layer on the same weeks: 62% / 40%.
  HF in the Pacific: too few cases to score.
Near the coast (Greenland barrier and tip-jet flow) ASCAT is blind, so none of
this is scored there; trust the GFS family's strength in those flows.

Self-contained: needs only SmartScript and numpy (model_aliases is used for
database names when present, else GFS/D2D_GFS and D2D_ECMWF/nECMWF0p25).
Not tested on AWIPS: the D2D database and element names come from
model_aliases and the GFE calls listed in tests/make_best_wind/README.md.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript

try:
    import model_aliases
except ImportError:
    model_aliases = None

try:
    import AbsTime
    import TimeRange
except ImportError:  # outside GFE
    AbsTime = None
    TimeRange = None

MenuItems = ["Populate"]

# ==================== CONFIGURATION ====================
# Blend (marine-research rk.features.det_blend).  Speeds in kt.
MODELS = ("GFS", "ECMWF")
LAGS_HOURS = (12, 24)
SUPPORT_KT = 5.0      # width of the Gaussian that counts runs near a model's speed
SPREAD_K = 0.3        # x population std of the runs
SPREAD_CAP_KT = 5.0   # cap on the spread term
RUN_DEPTH = 6         # runs searched per model: reaches 24 h back on a 6-hourly model

# Core lift ramps: 0 below START, full lift at FULL, straight line between.
# Trigger "Stronger of GFS/ECMWF": first ramp (LIFT_KT) 38 -> 42, second (LIFT2_KT) 48 -> 52.
MODEL_RAMP1 = (38.0, 42.0)
MODEL_RAMP2 = (48.0, 52.0)
# Trigger "Blend's own wind": 36 -> 40 and 44 -> 48 of the blended speed.
OWN_RAMP1 = (36.0, 40.0)
OWN_RAMP2 = (44.0, 48.0)
LIFT_KT = 6.0
LIFT2_KT = 4.0
TRIGGER_MODELS = "Stronger of GFS/ECMWF"
TRIGGER_OWN = "Blend's own wind"

# A Fcst time between two model grids is interpolated only when they are this close.
MAX_INTERP_GAP_HOURS = 6

FCST_LEVEL = "SFC"
# (element, level) pairs tried in each database; checked on AWIPS.
WIND_SOURCES = [("wind", "FHAG10"), ("wind", "10FHAG"), ("Wind", "SFC")]

# HF core (option, Off by default; Jason 2026-11-06: "add it where it counts the most ... targeted, we dont want to
# blanket HF").  A further 0 -> HF_CORE_KT ramp over HF_CORE_RAMP of the stronger of GFS/ECMWF, only where the GFS
# 925 mb wind x a stability factor (sea minus 2 m air: < 2 C 0.70, 2-5 C 0.79, 5+ C 0.83) is at least HF_GATE_KT,
# i.e. where the low-level jet can plausibly bring hurricane force down.  No GFS 925 mb/temperature data: skipped.
HF_CORE_KT = 6.0
HF_CORE_RAMP = (52.0, 56.0)
HF_GATE_KT = 55.0
HF_FACTORS = ((2.0, 0.70), (5.0, 0.79), (None, 0.83))
WIND925_SOURCES = [("wind", "MB925"), ("wind", "925MB")]   # guesses: check on AWIPS
SFC_T_SOURCES = [("t", "SFC"), ("tsfc", "SFC")]
AIR2M_T_SOURCES = [("t", "FHAG2"), ("t", "2FHAG")]

# Setting keys (also what another procedure passes as varDict).
K_LAGGED = "Lagged runs (12 h and 24 h older GFS/ECMWF)"
K_LIFT_ON = "Core lift"
K_TRIGGER = "Lift where"
K_LIFT = "Lift (kt)"
K_LIFT2 = "Extra lift for HF (kt, 0 = off)"
K_HF = "HF core (targeted by 925 mb wind and stability)"
DEFAULTS = {K_LAGGED: "On", K_LIFT_ON: "On", K_TRIGGER: TRIGGER_MODELS, K_LIFT: LIFT_KT, K_LIFT2: LIFT2_KT,
            K_HF: "Off"}

# The settings window is BestWindDialog (tkinter, like Blend_WindGustWavePmsl),
# so GFE's own variable list stays empty.
VariableList = []

_TO_KT = {"kt": 1.0, "kts": 1.0, "knots": 1.0, "knot": 1.0, "m/s": 1.943844, "mph": 0.868976}



# Database names per model, used when model_aliases is missing or older than this procedure.  The procedure keeps
# its own run and inventory lookups, so it does not depend on the version of the grid fetch helper on the server.
FALLBACK_DATABASES = {"GFS": ("GFS", "D2D_GFS"), "ECMWF": ("D2D_ECMWF", "nECMWF0p25")}


def database_candidates(alias, element="Wind"):
    """Database base names for a model: model_aliases when it has them, then FALLBACK_DATABASES."""
    names = []
    if model_aliases is not None:
        for fn, args in (("get_database_candidates_for_element", (alias, element)),
                         ("get_database_candidates", (alias,))):
            try:
                names += list(getattr(model_aliases, fn)(*args))
            except Exception:
                pass
    names += list(FALLBACK_DATABASES.get(alias, ()))
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def model_run_time(model_id):
    """Cycle time (unix s) from a database id ending in _YYYYMMDD_HHMM, else None."""
    import calendar
    parts = (model_id or "").split("_")
    if len(parts) < 2:
        return None
    try:
        return calendar.timegm(time.strptime(parts[-2] + parts[-1], "%Y%m%d%H%M"))
    except ValueError:
        return None


def list_model_runs(smart_script, alias, run_depth):
    """[(cycle_unix, {database_name: model_id})] newest first, from findDatabase over the candidate names."""
    runs = {}
    for base in database_candidates(alias):
        for offset in range(0, -run_depth, -1):
            try:
                db = smart_script.findDatabase(base, offset)
                model_id = db.modelIdentifier() if db is not None else None
            except Exception:
                model_id = None
            cycle = model_run_time(model_id)
            if cycle is not None:
                runs.setdefault(cycle, {}).setdefault(base, model_id)
    return sorted(runs.items(), key=lambda item: item[0], reverse=True)


def grid_times(smart_script, model_id, element, level, time_range):
    """[(start_unix, end_unix, grid_time_range)] of one element in one database over time_range, sorted."""
    try:
        infos = smart_script.getGridInfo(model_id, element, level, time_range)
    except Exception:
        return []
    out = []
    for info in infos or []:
        try:
            tr = info.gridTime()
            out.append((tr.startTime().unixTime(), tr.endTime().unixTime(), tr))
        except Exception:
            continue
    out.sort(key=lambda item: item[0])
    return out

def ramp(strongest, lift, start, full):
    """Lift in kt: 0 below start, `lift` at and above full, straight line between."""
    s = np.nan_to_num(np.asarray(strongest, dtype=float), nan=-999.0)
    if full <= start:
        return np.where(s >= start, float(lift), 0.0)
    return float(lift) * np.clip((s - start) / (full - start), 0.0, 1.0)


def stability_factor(sea_minus_air):
    """Drill factor on the 925 mb wind from sea minus 2 m air temperature (deg C)."""
    d = np.asarray(sea_minus_air, dtype=float)
    f = np.full(d.shape, HF_FACTORS[-1][1])
    for edge, fac in reversed(HF_FACTORS[:-1]):
        f = np.where(d < edge, fac, f)
    return f


def hf_core(strongest, s925_kt, sea_minus_air):
    """Extra kt for the HF core: the ramp, only where 925 mb wind x stability factor >= HF_GATE_KT."""
    ceiling = np.nan_to_num(np.asarray(s925_kt, dtype=float) * stability_factor(sea_minus_air), nan=-1.0)
    return np.where(ceiling >= HF_GATE_KT, ramp(strongest, HF_CORE_KT, *HF_CORE_RAMP), 0.0)


def det_blend(runs, speeds):
    """Blended speed (kt) from all runs and the current models' speeds.

    Same as rk.features.det_blend: weight of model i = mean over runs of
    exp(-0.5 ((run - speed_i) / 5)^2) + 1e-6; base = weighted mean of the
    speeds; plus min(0.3 x population std of the runs, 5), only with 2+ runs.
    """
    runs = np.asarray(runs, dtype=float)
    weights = [np.mean(np.exp(-0.5 * ((runs - s[None]) / SUPPORT_KT) ** 2), axis=0) + 1e-6 for s in speeds]
    base = sum(w * s for w, s in zip(weights, speeds)) / sum(weights)
    if len(runs) < 2:
        return base
    return base + np.minimum(SPREAD_K * np.std(runs, axis=0), SPREAD_CAP_KT)


def time_recipe(inventory, start, end):
    """("direct", tr) when a model grid overlaps start-end, ("interp", trA, trB, w) between
    two close grids, else None.  inventory is grid_times() output."""
    for g_start, g_end, g_tr in inventory:
        if g_start < end and g_end > start:
            return ("direct", g_tr)
    before = [g for g in inventory if g[0] <= start]
    after = [g for g in inventory if g[0] >= start]
    if before and after:
        a, b = before[-1], after[0]
        span = b[0] - a[0]
        if 0 < span <= MAX_INTERP_GAP_HOURS * 3600:
            return ("interp", a[2], b[2], (start - a[0]) / float(span))
    return None


def _hhz(unix):
    return time.strftime("%HZ", time.gmtime(unix))


def _stamp(unix):
    return time.strftime("%m/%d %HZ", time.gmtime(unix))


def _tr_key(tr):
    return (tr.startTime().unixTime(), tr.endTime().unixTime())




# ==================== SETTINGS WINDOW ====================

NAVY, OXBLOOD, CREAM, GREY = "#1f3354", "#7a1f2b", "#fbf7ee", "#555555"


class BestWindDialog:
    """Settings window: three boxed groups, a short note under every choice, Run / Defaults / Cancel."""

    def __init__(self, master, callback):
        import tkinter as tk
        self.tk, self.master, self.callback = tk, master, callback
        master.title("Make Best Wind")
        master.configure(bg=CREAM)
        master.resizable(False, False)
        master.protocol("WM_DELETE_WINDOW", self._cancel)
        self.lagged = tk.BooleanVar(value=True)
        self.lift_on = tk.BooleanVar(value=True)
        self.trigger = tk.StringVar(value=TRIGGER_MODELS)
        self.lift = tk.DoubleVar(value=LIFT_KT)
        self.lift2 = tk.DoubleVar(value=LIFT2_KT)
        self.hf = tk.BooleanVar(value=False)

        main = tk.Frame(master, padx=16, pady=12, bg=CREAM)
        main.pack(fill=tk.BOTH, expand=True)
        tk.Label(main, text="Make Best Wind", font=("Arial", 15, "bold"), fg=NAVY, bg=CREAM).pack(anchor=tk.W)
        tk.Label(main, text="GFS/ECMWF blend, then a lift in the storm cores. Run it over an ocean edit area.",
                 font=("Arial", 9), fg=GREY, bg=CREAM).pack(anchor=tk.W, pady=(0, 10))

        box = self._group(main, "1. Blend")
        self._check(box, "Use the 12 h and 24 h older runs", self.lagged,
                    "Weights each model by how its own earlier runs agree, plus 0.3 x their spread. This is the "
                    "scored blend. Off: current runs only, quicker.")

        box = self._group(main, "2. Storm-core lift")
        self._check(box, "Lift the storm cores", self.lift_on,
                    "Held-out vs ASCAT: storm-force catch 35% -> 75% Atlantic, 22% -> 64% Pacific; gales unchanged.",
                    command=self._refresh)
        self.trigger_widgets = []
        for value, note in ((TRIGGER_MODELS, "ramps in over 38-42 kt, extra over 48-52 kt"),
                            (TRIGGER_OWN, "ramps in over 36-40 kt and 44-48 kt; reads no other model")):
            row = tk.Frame(box, bg=CREAM)
            row.pack(fill=tk.X, padx=(22, 0))
            b = tk.Radiobutton(row, text=value, variable=self.trigger, value=value, bg=CREAM,
                               activebackground=CREAM, anchor=tk.W, width=24, highlightthickness=0)
            b.pack(side=tk.LEFT)
            tk.Label(row, text=note, font=("Arial", 8), fg=GREY, bg=CREAM).pack(side=tk.LEFT)
            self.trigger_widgets.append(b)
        self.scales = [self._scale(box, "Lift at storm force (kt)", self.lift, 0, 10),
                       self._scale(box, "Extra lift toward HF (kt)", self.lift2, 0, 8)]

        box = self._group(main, "3. Hurricane-force core (optional)")
        self.hf_check = self._check(
            box, "Add an HF core where the 925 mb jet can mix down", self.hf,
            "+0 to +6 kt as the stronger model goes 52 -> 56 kt, only where GFS 925 mb wind x stability >= 55 kt. "
            "Atlantic HF catch 59% -> 70%, but HF area grows from 0.9x to 1.7x ASCAT's. Needs the lift on.")

        buttons = tk.Frame(main, bg=CREAM)
        buttons.pack(fill=tk.X, pady=(8, 0))
        tk.Button(buttons, text="Run", command=self._run, bg=NAVY, fg="white", activebackground=OXBLOOD,
                  activeforeground="white", font=("Arial", 11, "bold"), width=12).pack(side=tk.LEFT)
        tk.Button(buttons, text="Defaults", command=self._defaults, width=10).pack(side=tk.LEFT, padx=8)
        tk.Button(buttons, text="Cancel", command=self._cancel, width=10).pack(side=tk.RIGHT)
        master.bind("<Return>", lambda e: self._run())
        master.bind("<Escape>", lambda e: self._cancel())
        self._refresh()

    def _group(self, parent, title):
        tk = self.tk
        box = tk.LabelFrame(parent, text=" %s " % title, padx=10, pady=6, fg=OXBLOOD, bg=CREAM,
                            font=("Arial", 10, "bold"))
        box.pack(fill=tk.X, pady=(0, 10))
        return box

    def _check(self, parent, text, var, note, command=None):
        tk = self.tk
        c = tk.Checkbutton(parent, text=text, variable=var, bg=CREAM, activebackground=CREAM, anchor=tk.W, highlightthickness=0,
                           font=("Arial", 10, "bold"), fg=NAVY, command=command)
        c.pack(fill=tk.X)
        tk.Label(parent, text=note, font=("Arial", 8), fg=GREY, bg=CREAM, wraplength=480, justify=tk.LEFT
                 ).pack(anchor=tk.W, padx=(22, 0), pady=(0, 4))
        return c

    def _scale(self, parent, text, var, lo, hi):
        tk = self.tk
        row = tk.Frame(parent, bg=CREAM)
        row.pack(fill=tk.X, padx=(22, 0))
        tk.Label(row, text=text, width=24, anchor=tk.W, bg=CREAM).pack(side=tk.LEFT)
        sc = tk.Scale(row, from_=lo, to=hi, resolution=1, orient=tk.HORIZONTAL, variable=var, length=220,
                      bg=CREAM, troughcolor="#e6dcc6", highlightthickness=0)
        sc.pack(side=tk.LEFT)
        return sc

    def _refresh(self):
        state = self.tk.NORMAL if self.lift_on.get() else self.tk.DISABLED
        for w in self.trigger_widgets + self.scales + [self.hf_check]:
            w.config(state=state)

    def _defaults(self):
        self.lagged.set(True)
        self.lift_on.set(True)
        self.trigger.set(TRIGGER_MODELS)
        self.lift.set(LIFT_KT)
        self.lift2.set(LIFT2_KT)
        self.hf.set(False)
        self._refresh()

    def values(self):
        def on(b):
            return "On" if b else "Off"
        return {K_LAGGED: on(self.lagged.get()), K_LIFT_ON: on(self.lift_on.get()), K_TRIGGER: self.trigger.get(),
                K_LIFT: float(self.lift.get()), K_LIFT2: float(self.lift2.get()), K_HF: on(self.hf.get())}

    def _run(self):
        self.callback(self.values())
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()

class Procedure(SmartScript.SmartScript):
    """Blend GFS and ECMWF 10 m wind, then lift the storm cores."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self._inventory = {}
        self._runs = {}

    # ------------------------------------------------------------ helpers

    def _edit_area_mask(self, editArea, shape):
        """Selected edit area, or the whole grid when none is selected."""
        try:
            if editArea is not None:
                mask = np.asarray(self.encodeEditArea(editArea), dtype=bool)
                if mask.shape == tuple(shape) and mask.any():
                    return mask
        except Exception:
            pass
        return np.ones(shape, dtype=bool)

    def _target_times(self, selection):
        """Fcst Wind grids in the selection, else the Wind time-constraint slots in it."""
        existing = grid_times(self, "Fcst", "Wind", FCST_LEVEL, selection)
        if existing:
            return [tr for _, _, tr in existing]
        try:
            parm = self.getParm("Fcst", "Wind", FCST_LEVEL)
            constraints = parm.getGridInfo().getTimeConstraints()
            return [TimeRange.TimeRange(j) for j in constraints.constraintTimes(selection.toJavaObj())]
        except Exception:
            return []

    def _model_runs(self, alias):
        """[(cycle_unix, {database: model_id})] newest first, once per alias."""
        if alias not in self._runs:
            self._runs[alias] = list_model_runs(self, alias, RUN_DEPTH)
        return self._runs[alias]

    def _find(self, alias, databases, tr, window, sources=None):
        """(model_id, element, level, recipe) of the first source of one cycle covering tr, else None."""
        start, end = _tr_key(tr)
        preferred = database_candidates(alias)
        order = [n for n in preferred if n in databases] + [n for n in databases if n not in preferred]
        for name in order:
            model_id = databases[name]
            for element, level in (sources or WIND_SOURCES):
                key = (model_id, element, level)
                if key not in self._inventory:
                    self._inventory[key] = grid_times(self, model_id, element, level, window)
                recipe = time_recipe(self._inventory[key], start, end)
                if recipe is not None:
                    return model_id, element, level, recipe
        return None

    def _units(self, model_id, element, level):
        try:
            return str(self.getParm(model_id, element, level).getGridInfo().getUnitString())
        except Exception:
            return ""

    def _read_uv(self, found, tr_pick, notes):
        """(u, v) in kt of one model grid, or None if it is empty."""
        model_id, element, level, _ = found
        grid = self.getGrids(model_id, element, level, tr_pick, mode="First", noDataError=0)
        if grid is None:
            return None
        mag = np.asarray(grid[0], dtype=float)
        direction = np.asarray(grid[1], dtype=float)
        unit = self._units(model_id, element, level).strip().lower()
        factor = _TO_KT.get(unit)
        if factor is None:
            if "D2D" in model_id.upper() and np.nanmax(mag) < 60:
                factor = _TO_KT["m/s"]
                note = "%s units unknown, assumed m/s" % model_id
            else:
                factor = 1.0
                note = "%s units unknown, assumed kt" % model_id
            if note not in notes:
                notes.append(note)
        u, v = self.MagDirToUV(mag * factor, direction)
        return np.asarray(u, dtype=float), np.asarray(v, dtype=float)

    def _read_run(self, found, notes):
        """(u, v) in kt of one run at the Fcst time, interpolated in time if needed."""
        recipe = found[3]
        if recipe[0] == "direct":
            uv = self._read_uv(found, recipe[1], notes)
        else:
            a, b = self._read_uv(found, recipe[1], notes), self._read_uv(found, recipe[2], notes)
            w = recipe[3]
            uv = None if a is None or b is None else tuple(x * (1.0 - w) + y * w for x, y in zip(a, b))
        if uv is None or not np.isfinite(uv[0]).any():
            return None
        return uv

    def _read_scalar(self, found):
        """Scalar grid of one source at the Fcst time (direct or interpolated), as float, or None."""
        model_id, element, level, recipe = found

        def one(tr):
            g = self.getGrids(model_id, element, level, tr, mode="First", noDataError=0)
            return None if g is None else np.asarray(g[0] if isinstance(g, (tuple, list)) else g, dtype=float)
        if recipe[0] == "direct":
            return one(recipe[1])
        a, b = one(recipe[1]), one(recipe[2])
        return None if a is None or b is None else a * (1.0 - recipe[3]) + b * recipe[3]

    def _hf_inputs(self, tr, window, notes):
        """(GFS 925 mb speed kt, sea minus 2 m air C) from the newest GFS run that has all three, else None."""
        for _, databases in self._model_runs("GFS"):
            f925 = self._find("GFS", databases, tr, window, WIND925_SOURCES)
            fsea = self._find("GFS", databases, tr, window, SFC_T_SOURCES)
            fair = self._find("GFS", databases, tr, window, AIR2M_T_SOURCES)
            if not (f925 and fsea and fair):
                continue
            uv = self._read_run(f925, notes)
            sea, air = self._read_scalar(fsea), self._read_scalar(fair)
            if uv is None or sea is None or air is None:
                continue

            def to_c_scale(found):
                return 5.0 / 9.0 if self._units(*found[:3]).strip().upper().endswith("F") else 1.0
            return np.hypot(*uv), sea * to_c_scale(fsea) - air * to_c_scale(fair)
        return None

    # ------------------------------------------------------------ one time

    def _collect(self, tr, window, notes, lags=LAGS_HOURS):
        """Per model: [(label, u, v)] with the current run first, plus what was missing."""
        out, missing = {}, []
        for alias in MODELS:
            runs = self._model_runs(alias)
            current = None
            for cycle, databases in runs:
                found = self._find(alias, databases, tr, window)
                uv = self._read_run(found, notes) if found else None
                if uv is not None:
                    current = (cycle, databases, uv)
                    break
            if current is None:
                missing.append("%s current" % alias)
                continue
            cycle, _, uv = current
            entries = [("%s %s" % (alias, _hhz(cycle)), uv)]
            by_cycle = dict(runs)
            for lag in lags:
                databases = by_cycle.get(cycle - lag * 3600)
                found = self._find(alias, databases, tr, window) if databases else None
                uv = self._read_run(found, notes) if found else None
                if uv is None:
                    missing.append("%s -%dh" % (alias, lag))
                else:
                    entries.append(("%s -%dh" % (alias, lag), uv))
            out[alias] = entries
        return out, missing

    def _make_one(self, tr, window, settings, mask, notes):
        """Return ((speed_kt, direction), lifted_count, run_text, missing) or None if both models missing."""
        collected, missing = self._collect(tr, window, notes, LAGS_HOURS if settings["lagged"] else ())
        if not collected:
            return None, 0, "", missing
        current = [entries[0][1] for entries in collected.values()]
        all_runs = [uv for entries in collected.values() for _, uv in entries]
        run_speeds = [np.hypot(u, v) for u, v in all_runs]
        cur_speeds = [np.hypot(u, v) for u, v in current]
        speed = det_blend(run_speeds, cur_speeds)

        u_mean = np.mean([u for u, _ in current], axis=0)
        v_mean = np.mean([v for _, v in current], axis=0)
        _, direction = self.UVToMagDir(u_mean, v_mean)
        direction = np.mod(np.asarray(direction, dtype=float), 360.0)

        lifted = 0
        if settings["lift_on"]:
            if settings["own"]:
                strongest, r1, r2 = speed, OWN_RAMP1, OWN_RAMP2
            else:
                strongest = np.fmax.reduce(cur_speeds)
                r1, r2 = MODEL_RAMP1, MODEL_RAMP2
            add = ramp(strongest, settings["lift"], *r1)
            if settings["lift2"] > 0:
                add = add + ramp(strongest, settings["lift2"], *r2)
            if settings["hf_core"]:
                hf_in = self._hf_inputs(tr, window, notes)
                if hf_in is None:
                    note = "HF core skipped: GFS 925 mb wind or surface/2 m temperature not found"
                    if note not in notes:
                        notes.append(note)
                else:
                    add = add + hf_core(np.fmax.reduce(cur_speeds), *hf_in)
            add = np.where(mask, add, 0.0)
            speed = speed + add
            lifted = int((add > 0).sum())

        text = ", ".join(label for entries in collected.values() for label, _ in entries)
        return (speed, direction), lifted, text, missing

    # ------------------------------------------------------------ execute

    def _show_gui(self):
        """Settings from the window, or None if cancelled."""
        import tkinter as tk
        result = [None]

        def callback(values):
            result[0] = values
        root = tk.Tk()
        BestWindDialog(root, callback)
        root.mainloop()
        return result[0]

    def execute(self, editArea, timeRange, varDict=None):
        # A varDict carrying any setting (another procedure, the tests) skips the window.
        if varDict and any(k in varDict for k in DEFAULTS):
            chosen = dict(DEFAULTS, **varDict)
        else:
            chosen = self._show_gui()
            if chosen is None:
                self.statusBarMsg("Make_BestWind: cancelled, nothing written", "R")
                return
        settings = {
            "lagged": chosen[K_LAGGED] != "Off",
            "lift_on": chosen[K_LIFT_ON] != "Off",
            "own": chosen[K_TRIGGER] == TRIGGER_OWN,
            "lift": float(chosen[K_LIFT]),
            "lift2": float(chosen[K_LIFT2] or 0.0),
            "hf_core": chosen[K_HF] == "On",
        }
        times = self._target_times(timeRange)
        if not times:
            self.statusBarMsg("Make_BestWind: no Fcst Wind grids in the selected time range and none could be "
                              "laid out on the Wind time constraints; nothing changed", "U")
            return

        starts = [tr.startTime().unixTime() for tr in times]
        ends = [tr.endTime().unixTime() for tr in times]
        pad = MAX_INTERP_GAP_HOURS * 3600
        window = TimeRange.TimeRange(AbsTime.AbsTime(min(starts) - pad), AbsTime.AbsTime(max(ends) + pad))

        fcst_unit = self._units("Fcst", "Wind", FCST_LEVEL).strip().lower()
        from_kt = 1.0 / _TO_KT.get(fcst_unit, 1.0)

        notes: List[str] = []
        summary: List[str] = []
        problems: List[str] = []
        total_lifted = 0
        mask = None
        for i, tr in enumerate(times):
            self.statusBarMsg("Make_BestWind %d/%d" % (i + 1, len(times)), "R")
            when = _stamp(tr.startTime().unixTime())
            if mask is None:
                mask = self._edit_area_mask(editArea, self.empty().shape)
            result, lifted, text, missing = self._make_one(tr, window, settings, mask, notes)
            if result is None:
                problems.append("%s left unchanged (no GFS or ECMWF run)" % when)
                continue
            speed, direction = result
            speed = np.where(np.isfinite(speed), np.maximum(speed, 0.0), 0.0)
            grid = ((speed * from_kt).astype(np.float32), direction.astype(np.float32))
            self.createGrid("Fcst", "Wind", "VECTOR", grid, tr)
            total_lifted += lifted
            line = "%s: %s" % (when, text)
            if missing:
                line += " [missing %s]" % ", ".join(missing)
            if any(m.endswith("current") for m in missing):
                line += " [other model alone]"
            summary.append(line)

        parts = ["Make_BestWind: %d of %d grids written" % (len(summary), len(times))]
        if not settings["lagged"]:
            parts.append("lagged runs off (current GFS and ECMWF only; not the scored blend)")
        parts.append("core lift %s" % ("off" if not settings["lift_on"] else
                                       "on (%s), %d cells lifted" % (
                                           TRIGGER_OWN if settings["own"] else TRIGGER_MODELS, total_lifted)))
        message = "; ".join(parts)
        if summary:
            message += ". Runs used: " + " | ".join(summary)
        if problems:
            message += ". " + "; ".join(problems)
        if notes:
            message += ". " + "; ".join(notes)
        status = "U" if problems else "R"
        print(message)
        self.statusBarMsg(message, status)


__all__ = ["Procedure"]
