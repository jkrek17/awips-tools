"""
Blend_WindGustWavePmsl - one model blend for Wind, WindGust, WaveHeight and pmsl.

The forecaster sets one weight per model; the same weights build every
selected element, so the winds, gusts, seas and pressure field all come
from the same blend of the same model runs.

Runs
    For each model the newest *complete* cycle is used: the newest run that
    has every selected element at every grid time being edited.  A run that
    is still arriving (18Z with only the first two days in) is passed over
    for the previous one, and the log and the closing status message say
    which cycle each model contributed and why a newer one was skipped.
    Wind, WindGust and pmsl for a model always come from one cycle; its
    paired wave model is chosen the same way on its own cycle.

Nothing written unless everything is there
    Before any grid is touched the tool checks the inventory of every model
    for every element and grid time.  If any model has no complete run, it
    stops with an error naming the model, element and time, and Fcst is left
    as it was.  Then every model grid the blend will use is read once: a grid
    that is all missing or one value everywhere (the usual look of an empty
    or failed decode) stops the run the same way, before anything is written.

Gusts
    Each model's own gust grid is blended.  A model run without gusts falls
    back to that model's wind speed times the gust factor from the dialog,
    and the log says so.  The blended gust is never below the Fcst wind.

Times
    The grids edited are the existing Fcst grids of each element in the
    selected time range; an element with none there gets new grids laid out
    on its time constraints.  A Fcst time with no model grid on it takes the
    model's two neighbouring grids, interpolated in time, if they are no more
    than MAX_INTERP_GAP_HOURS apart.

Wind is blended as speed (weighted mean of the model speeds) and direction
(of the weighted mean u/v), so models that disagree on direction do not cut
the blended speed.  The edit area, if one is selected, limits the change.

Deterministic blend for Wind (checkbox)
    Wind ignores the weights and uses the recipe on the marine wind page
    (layer "Deterministic blend"): GFS, ECMWF and AIFS, each weighted point by
    point by how many of 9 runs sit near its speed (these 3 models plus the
    same models' runs 12 h and 24 h earlier, valid at the same time; Gaussian
    kernel DET_SUPPORT_KT wide), plus min(DET_SPREAD_K x spread of the 9,
    DET_CAP_KT).  Direction is the mean u/v of the current runs.  A run that
    is not on the server is left out and named in the closing message; the
    blend needs at least one current model run.  Gust, waves and pmsl keep
    the weights.  Gusts are never left below the new Wind, also when
    WindGust is not being blended.
    Tested by hindcast on 12Z runs (265 cases, 30-67N): about 90% of the
    member blend's gain against analyses, about 40% of its gale hits at
    ships and buoys.
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import SmartScript

import grid_fetch
import model_aliases

try:
    import AbsTime
    import TimeRange
except ImportError:  # outside GFE
    AbsTime = None
    TimeRange = None

MenuItems = ["Populate"]
VariableList = []

# ==================== CONFIGURATION ====================
# A Fcst time between two model grids is interpolated only when the grids
# are at most this far apart.
MAX_INTERP_GAP_HOURS = 6

# Runs searched per model: the registry's max_runs, but at least this many.
MIN_RUN_DEPTH = 2

DEFAULT_GUST_FACTOR = 1.3

FCST_LEVEL = "SFC"

# Deterministic blend for Wind (see the docstring).  Speeds in kt.
DET_MODELS = ("GFS", "ECMWF", "AIFS")
DET_LAGS_HOURS = (12, 24)
DET_SUPPORT_KT = 5.0
DET_SPREAD_K = 0.3
DET_CAP_KT = 5.0
# Runs searched per model: enough to reach 24 h back on a 6-hourly model
# whose newest run is still arriving.
DET_RUN_DEPTH = 6


@dataclass(frozen=True)
class ElementSpec:
    """A Fcst element and where to find it in the model databases."""

    key: str
    vector: bool
    dataset: str  # "atmo" or "wave"
    # (model element, level) pairs tried in order in each database.
    sources: Tuple[Tuple[str, str], ...]
    floor: Optional[float]


ELEMENT_SPECS: Dict[str, ElementSpec] = {
    spec.key: spec
    for spec in (
        ElementSpec("Wind", True, "atmo",
                    (("Wind", "SFC"), ("wind", "FHAG10"), ("wind", "10FHAG")), 0.0),
        ElementSpec("WindGust", False, "atmo",
                    (("WindGust", "SFC"), ("gust", "SFC")), 0.0),
        ElementSpec("WaveHeight", False, "wave",
                    (("WaveHeight", "SFC"), ("WaveHeight", "MSL"),
                     ("htsgw", "SFC"), ("htsgw", "MSL"), ("swh", "SFC"), ("swh", "MSL")), 0.0),
        ElementSpec("pmsl", False, "atmo",
                    (("pmsl", "SFC"), ("pmsl", "MSL"), ("PMSL", "SFC"), ("mmsl", "MSL")), None),
    )
}
ELEMENT_ORDER = ("Wind", "WindGust", "WaveHeight", "pmsl")

# Unit names as GFE spells them, and their size in SI units.
_UNIT_ALIASES = {
    "kts": "kt", "kt": "kt", "knots": "kt", "knot": "kt",
    "m/s": "m/s", "mps": "m/s", "ms-1": "m/s", "m s-1": "m/s", "mph": "mph",
    "pa": "pa", "hpa": "mb", "mb": "mb", "millibar": "mb", "millibars": "mb",
    "m": "m", "ft": "ft", "feet": "ft",
}
_UNIT_SI = {"kt": 0.514444, "m/s": 1.0, "mph": 0.44704,
            "pa": 1.0, "mb": 100.0, "m": 1.0, "ft": 0.3048}
_UNIT_KIND = {"kt": "speed", "m/s": "speed", "mph": "speed",
              "pa": "pressure", "mb": "pressure", "m": "length", "ft": "length"}


def unit_factor(src: Optional[str], dst: Optional[str]) -> Optional[float]:
    """Multiplier from ``src`` to ``dst`` units, or None if it can't be told."""

    if not src or not dst:
        return None
    a = _UNIT_ALIASES.get(src.strip().lower())
    b = _UNIT_ALIASES.get(dst.strip().lower())
    if a is None or b is None:
        return 1.0 if src.strip() == dst.strip() else None
    if _UNIT_KIND[a] != _UNIT_KIND[b]:
        return None
    return _UNIT_SI[a] / _UNIT_SI[b]


def time_recipe(inventory, start: int, end: int):
    """
    How to get a model value for the Fcst grid ``start``-``end``.

    ``("direct", tr)`` when a model grid overlaps it, ``("interp", trA, trB,
    w)`` when the two grids either side of ``start`` are close enough to
    interpolate between, None when neither.
    """

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


def empty_reason(value: np.ndarray) -> Optional[str]:
    """Why a model grid looks empty, or None if it looks like data."""

    finite = np.isfinite(value)
    if not finite.any():
        return "all points missing"
    lo = float(np.min(value[finite]))
    hi = float(np.max(value[finite]))
    if lo == hi:
        return "the same value (%g) everywhere" % lo
    return None


def fmt_time(unix: int) -> str:
    return time.strftime("%m/%d %HZ", time.gmtime(unix))


def fmt_cycle(unix: int) -> str:
    return time.strftime("%m/%d %HZ run", time.gmtime(unix))


def tr_key(tr) -> Tuple[int, int]:
    return (tr.startTime().unixTime(), tr.endTime().unixTime())


class BlendError(Exception):
    """A model grid the plan relied on could not be used."""


@dataclass
class Source:
    """Where one model's grids for one Fcst element come from."""

    model_id: str
    element: str
    level: str
    read_as: str  # ELEMENT_SPECS key describing the model grid (Wind for gusts-from-wind)
    factor: Optional[float]  # unit conversion to the Fcst element; None = unknown
    recipes: Dict[Tuple[int, int], tuple]
    from_wind: bool = False


@dataclass
class ModelPlan:
    alias: str
    label: str
    weight: float
    cycles: Dict[str, int] = field(default_factory=dict)
    sources: Dict[str, Source] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)


# ==================== GUI ====================


class BlendDialog:
    """Model weights, elements and the gust factor."""

    def __init__(self, master, callback, models: Sequence[Tuple[str, str]]):
        self.master = master
        self.callback = callback
        self.models = models
        self.weights: Dict[str, tk.IntVar] = {}
        self.pct_labels: Dict[str, tk.Label] = {}
        self.elements = {key: tk.BooleanVar(value=True) for key in ELEMENT_ORDER}
        self.gust_factor = tk.DoubleVar(value=DEFAULT_GUST_FACTOR)
        self.deterministic = tk.BooleanVar(value=False)

        master.title("Blend Wind/Gust/Wave/pmsl")
        main = tk.Frame(master, padx=12, pady=12)
        main.pack(fill=tk.BOTH, expand=True)

        tk.Label(main, text="Blend Wind / Gust / Wave / pmsl",
                 font=("Arial", 14, "bold")).pack(pady=(0, 2))
        tk.Label(main, text="One set of weights for every element; newest complete run of each model",
                 font=("Arial", 9), fg="gray").pack(pady=(0, 8))

        frame = tk.LabelFrame(main, text="Model weights", padx=10, pady=6)
        frame.pack(fill=tk.X, pady=(0, 8))
        for alias, label in models:
            var = tk.IntVar(value=0)
            self.weights[alias] = var
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label + ":", width=22, anchor=tk.W).pack(side=tk.LEFT)
            tk.Scale(row, from_=0, to=5, orient=tk.HORIZONTAL, variable=var,
                     command=self._update, width=12, showvalue=True).pack(side=tk.LEFT, fill=tk.X, expand=True)
            pct = tk.Label(row, text="0%", width=6)
            pct.pack(side=tk.RIGHT)
            self.pct_labels[alias] = pct

        frame = tk.LabelFrame(main, text="Elements", padx=10, pady=6)
        frame.pack(fill=tk.X, pady=(0, 8))
        for key in ELEMENT_ORDER:
            tk.Checkbutton(frame, text=key, variable=self.elements[key]).pack(side=tk.LEFT, padx=6)

        frame = tk.LabelFrame(main, text="Wind", padx=10, pady=6)
        frame.pack(fill=tk.X, pady=(0, 8))
        tk.Checkbutton(frame, text="Deterministic blend for Wind (GFS, ECMWF, AIFS; ignores the weights)",
                       variable=self.deterministic, command=self._update).pack(anchor=tk.W)
        tk.Label(frame, text="Weighted by agreement with their runs 12 h and 24 h earlier, plus 0.3 x their spread",
                 font=("Arial", 9), fg="gray").pack(anchor=tk.W)

        frame = tk.LabelFrame(main, text="Gusts", padx=10, pady=6)
        frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(frame, text="Gust factor for a model run with no gust grid (wind speed x factor):",
                 font=("Arial", 9)).pack(anchor=tk.W)
        tk.Scale(frame, from_=1.0, to=2.0, resolution=0.05, orient=tk.HORIZONTAL,
                 variable=self.gust_factor, length=220).pack(anchor=tk.W)

        self.message = tk.Label(main, text="", fg="red")
        self.message.pack()

        buttons = tk.Frame(main)
        buttons.pack(fill=tk.X, pady=(6, 0))
        tk.Button(buttons, text="Run", command=self._run, bg="lightgreen",
                  font=("Arial", 11, "bold"), width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(buttons, text="Cancel", command=self._cancel, width=10).pack(side=tk.LEFT)

        self._update()

    def _update(self, *args):
        total = sum(var.get() for var in self.weights.values())
        for alias, var in self.weights.items():
            pct = int(round(100.0 * var.get() / total)) if total else 0
            self.pct_labels[alias].config(text="%d%%" % pct)
        self.message.config(text="" if total or self.deterministic.get() else "Move at least one slider above 0")

    def _run(self):
        weights = {alias: var.get() for alias, var in self.weights.items() if var.get() > 0}
        elements = [key for key in ELEMENT_ORDER if self.elements[key].get()]
        deterministic = bool(self.deterministic.get())
        if not elements:
            messagebox.showerror("Blend", "Select at least one element.")
            return
        if not weights and not (deterministic and elements == ["Wind"]):
            messagebox.showerror("Blend", "Give at least one model a weight above 0.")
            return
        self.callback({"weights": weights, "elements": elements, "deterministic": deterministic,
                       "gust_factor": float(self.gust_factor.get())})
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


# ==================== PROCEDURE ====================


class Procedure(SmartScript.SmartScript):
    """Blend Wind, WindGust, WaveHeight and pmsl from one set of model weights."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self._used_gui = False

    def log(self, message: str):
        print(message)

    def execute(self, editArea, timeRange, varDict=None):
        """
        varDict, when given (from another procedure), skips the dialog:
          weights      {model alias: weight}, at least one above 0
          elements     any of Wind, WindGust, WaveHeight, pmsl (default all)
          gust_factor  wind-to-gust factor for model runs without gusts
          deterministic  True: Wind from the deterministic blend, not the weights
        """

        settings = varDict if varDict and ("weights" in varDict or "deterministic" in varDict) else self._show_gui()
        if settings is None:
            self.statusBarMsg("Blend cancelled", "R")
            return

        try:
            weights, elements, gust_factor, deterministic = self._read_settings(settings)
        except ValueError as exc:
            self._fail(str(exc))
            return

        self.log("=" * 70)
        self.log("BLEND WIND/GUST/WAVE/PMSL")
        self.log("=" * 70)
        det_wind = deterministic and "Wind" in elements
        weighted = [e for e in elements if not (det_wind and e == "Wind")]
        if weighted:
            self.log("Weights: " + ", ".join("%s %.0f%%" % (a, 100 * w) for a, w in weights.items()))
        self.log("Elements: " + ", ".join(elements) + ("  (Wind: deterministic blend)" if det_wind else ""))

        mask = self._edit_area_mask(editArea)

        # --- Grid times to edit ---------------------------------------------
        targets: Dict[str, list] = {}
        problems: List[str] = []
        for elem in elements:
            times = self._target_times(elem, timeRange)
            if not times:
                problems.append("Fcst %s: no grids in the selected time range and none could be laid out "
                                "on its time constraints" % elem)
            targets[elem] = times
        if problems:
            self._fail("Nothing was changed.\n" + "\n".join(problems))
            return

        starts = [tr.startTime().unixTime() for times in targets.values() for tr in times]
        ends = [tr.endTime().unixTime() for times in targets.values() for tr in times]
        pad = MAX_INTERP_GAP_HOURS * 3600
        window = TimeRange.TimeRange(AbsTime.AbsTime(min(starts) - pad), AbsTime.AbsTime(max(ends) + pad))

        # --- Pick each model's run and check it has everything ---------------
        plans: List[ModelPlan] = []
        for alias, weight in (weights.items() if weighted else ()):
            self.statusBarMsg("Checking %s runs..." % alias, "R")
            plan, model_problems = self._plan_model(alias, weight, weighted, targets, window)
            plans.append(plan)
            problems.extend(model_problems)

        det_plans: List[ModelPlan] = []
        det_notes: List[str] = []
        if det_wind:
            self.statusBarMsg("Checking GFS, ECMWF and AIFS runs...", "R")
            det_plans, det_notes = self._plan_deterministic(targets, window)
            if not any(p.weight > 0 for p in det_plans):
                problems.append("Deterministic blend: no complete Wind run of GFS, ECMWF or AIFS - "
                                + "; ".join(det_notes))

        for plan in plans:
            for note in plan.skipped:
                self.log("  Skipped " + note)
        if problems:
            self._fail("Nothing was changed - not every model has the data:\n" + "\n".join(problems))
            return

        run_summary = []
        for plan in plans:
            for dataset, cycle in plan.cycles.items():
                run_summary.append("%s%s %s" % (plan.label, " wave" if dataset == "wave" else "",
                                                time.strftime("%HZ %m/%d", time.gmtime(cycle))))
            for elem, src in plan.sources.items():
                self.log("  %-10s %-10s <- %s %s %s%s" % (plan.label, elem, src.model_id, src.element, src.level,
                                                         "  (wind x %.2f)" % gust_factor if src.from_wind else ""))
        if det_wind:
            det_runs = ["%s %s" % (p.label, time.strftime("%HZ %m/%d", time.gmtime(p.cycles["atmo"])))
                        for p in det_plans]
            self.log("Deterministic blend runs: " + ", ".join(det_runs))
            for note in det_notes:
                self.log("  Left out " + note)
            run_summary.append("Wind from %d runs (%s)" % (len(det_plans), ", ".join(det_runs)))
        self.log("Runs: " + ", ".join(run_summary))

        # --- Read every model grid once and reject empty ones -----------------
        self.statusBarMsg("Checking model grids...", "R")
        try:
            self._check_grids(plans, weighted)
            self._check_grids(det_plans, ["Wind"])
        except BlendError as exc:
            self._fail("Nothing was changed - %s" % exc)
            return

        # --- Blend and write ---------------------------------------------------
        written: List[str] = []
        try:
            for elem in elements:
                total = len(targets[elem])
                for i, tr in enumerate(targets[elem]):
                    self.statusBarMsg("%s %d/%d" % (elem, i + 1, total), "R")
                    if det_wind and elem == "Wind":
                        result, covered = self._blend_deterministic(tr, det_plans)
                    else:
                        result, covered = self._blend(elem, tr, plans, gust_factor)
                    self._write(elem, tr, result, covered, mask)
                    written.append("%s %s" % (elem, fmt_time(tr.startTime().unixTime())))
        except BlendError as exc:
            done = ("Already written: %d grids, through %s." % (len(written), written[-1])
                    if written else "Nothing was written.")
            self._fail("Blend stopped: %s\n%s" % (exc, done))
            return

        if det_wind and "WindGust" not in elements:
            raised = self._raise_gusts(timeRange, mask)
            if raised:
                written.append("WindGust raised to Wind in %d grids" % raised)
                self.log("  WindGust raised to the new Wind in %d grids" % raised)

        notes = [n for plan in plans for n in plan.skipped]
        message = "Blend done: %d grids from %s." % (len(written), ", ".join(run_summary))
        if notes:
            message += " Newer runs skipped as incomplete: " + "; ".join(notes)
        if det_wind and det_notes:
            message += " Left out of the deterministic blend: " + "; ".join(det_notes)
        self.log(message)
        self.statusBarMsg(message, "R")

    # ---------------------------------------------------------------- settings

    def _show_gui(self) -> Optional[Dict]:
        models = [(alias, label) for alias, label, _ in model_aliases.list_models_for_gui("atmo")]
        result = [None]

        def callback(values):
            result[0] = values

        root = tk.Tk()
        BlendDialog(root, callback, models)
        root.mainloop()
        self._used_gui = True
        return result[0]

    @staticmethod
    def _read_settings(settings: Dict):
        deterministic = bool(settings.get("deterministic", False))
        raw = settings.get("weights") or {}
        weights: Dict[str, float] = {}
        for alias, weight in raw.items():
            weight = float(weight)
            if weight < 0:
                raise ValueError("Weight for %s is negative." % alias)
            if weight == 0:
                continue
            if not model_aliases.has_alias(alias):
                raise ValueError("%s is not a known model." % alias)
            weights[model_aliases.resolve_alias(alias)] = weights.get(model_aliases.resolve_alias(alias), 0.0) + weight
        elements = [e for e in ELEMENT_ORDER if e in (settings.get("elements") or ELEMENT_ORDER)]
        unknown = set(settings.get("elements") or ()) - set(ELEMENT_ORDER)
        if unknown:
            raise ValueError("Unknown element(s): %s." % ", ".join(sorted(unknown)))
        if not elements:
            raise ValueError("No element selected.")

        if not weights and not (deterministic and elements == ["Wind"]):
            raise ValueError("No model has a weight above 0.")
        total = sum(weights.values())
        weights = {alias: weight / total for alias, weight in weights.items()}

        gust_factor = float(settings.get("gust_factor", DEFAULT_GUST_FACTOR))
        if gust_factor < 1.0:
            raise ValueError("Gust factor must be at least 1.0.")
        return weights, elements, gust_factor, deterministic

    def _fail(self, message: str):
        """Report an error loudly: the status bar, and a dialog if the GUI ran."""

        self.log("ERROR: " + message)
        self.statusBarMsg(message.replace("\n", " | "), "U")
        if self._used_gui:
            try:
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("Blend Wind/Gust/Wave/pmsl", message)
                root.destroy()
            except Exception:
                pass

    def _edit_area_mask(self, editArea) -> np.ndarray:
        """Selected edit area, or the whole domain when nothing is selected."""

        try:
            if editArea is not None:
                mask = np.asarray(self.encodeEditArea(editArea), dtype=bool)
                if mask.any():
                    return mask
        except Exception:
            pass
        return np.ones(self.empty().shape, dtype=bool)

    def _target_times(self, elem: str, selection) -> list:
        """Fcst grids of ``elem`` in the selection, else its time-constraint slots."""

        existing = grid_fetch.grid_times(self, "Fcst", elem, FCST_LEVEL, selection)
        if existing:
            return [tr for _, _, tr in existing]
        try:
            parm = self.getParm("Fcst", elem, FCST_LEVEL)
            constraints = parm.getGridInfo().getTimeConstraints()
            return [TimeRange.TimeRange(jtr) for jtr in constraints.constraintTimes(selection.toJavaObj())]
        except Exception:
            return []

    # ---------------------------------------------------------------- planning

    def _plan_model(self, alias: str, weight: float, elements, targets, window):
        cfg = model_aliases.get_model_config(alias)
        plan = ModelPlan(alias=alias, label=alias, weight=weight)
        problems: List[str] = []
        run_depth = max(cfg.max_runs, MIN_RUN_DEPTH)

        for dataset in ("atmo", "wave"):
            wanted = [e for e in elements if ELEMENT_SPECS[e].dataset == dataset]
            if not wanted:
                continue
            if dataset == "wave" and cfg.wave is None:
                problems.append("%s: has no paired wave model, so it can't go into WaveHeight "
                                "(give it no weight, or untick WaveHeight)" % plan.label)
                continue

            runs = grid_fetch.list_model_runs(self, alias, dataset=dataset, run_depth=run_depth)[:run_depth]
            if not runs:
                names = model_aliases.get_database_candidates(alias, dataset=dataset)
                problems.append("%s: no %s database found (looked for %s)"
                                % (plan.label, "wave" if dataset == "wave" else "model", ", ".join(names) or "none"))
                continue

            reasons = []
            for cycle, databases in runs:
                sources, missing = self._resolve_run(alias, cfg, databases, wanted, targets, window)
                if not missing:
                    plan.cycles[dataset] = cycle
                    plan.sources.update(sources)
                    break
                why = missing[0] + (" (and %d more)" % (len(missing) - 1) if len(missing) > 1 else "")
                reasons.append("%s: %s" % (fmt_cycle(cycle), why))
            else:
                problems.append("%s: no complete %srun among the newest %d - %s"
                                % (plan.label, "wave " if dataset == "wave" else "", len(runs), "; ".join(reasons)))
                continue
            plan.skipped.extend("%s %s" % (plan.label, r) for r in reasons)

        return plan, problems

    def _plan_deterministic(self, targets, window):
        """Wind sources for the deterministic blend.

        Returns (plans, notes).  Each model's newest complete Wind run is a plan
        with weight 1 (a current run); the same model's runs DET_LAGS_HOURS
        earlier are plans with weight 0.  Runs that are missing or incomplete
        are left out and described in notes.
        """

        plans: List[ModelPlan] = []
        notes: List[str] = []
        for alias in DET_MODELS:
            try:
                cfg = model_aliases.get_model_config(alias)
            except Exception:
                notes.append("%s (not a known model)" % alias)
                continue
            runs = grid_fetch.list_model_runs(self, alias, dataset="atmo",
                                              run_depth=max(cfg.max_runs, DET_RUN_DEPTH))
            if not runs:
                names = model_aliases.get_database_candidates(alias, dataset="atmo")
                notes.append("%s (no database found; looked for %s)" % (alias, ", ".join(names) or "none"))
                continue

            by_cycle = dict(runs)
            newest = None
            for cycle, databases in runs:
                sources, missing = self._resolve_run(alias, cfg, databases, ["Wind"], targets, window)
                if not missing:
                    newest = cycle
                    plan = ModelPlan(alias=alias, label=alias, weight=1.0)
                    plan.cycles["atmo"] = cycle
                    plan.sources.update(sources)
                    plans.append(plan)
                    break
            if newest is None:
                notes.append("%s (no complete Wind run among the newest %d)" % (alias, len(runs)))
                continue

            for lag in DET_LAGS_HOURS:
                cycle = newest - lag * 3600
                label = "%s -%dh" % (alias, lag)
                databases = by_cycle.get(cycle)
                if databases is None:
                    notes.append("%s %s (not on the server)" % (alias, fmt_cycle(cycle)))
                    continue
                sources, missing = self._resolve_run(alias, cfg, databases, ["Wind"], targets, window)
                if missing:
                    notes.append("%s %s (%s)" % (alias, fmt_cycle(cycle), missing[0]))
                    continue
                plan = ModelPlan(alias=alias, label=label, weight=0.0)
                plan.cycles["atmo"] = cycle
                plan.sources.update(sources)
                plans.append(plan)
        return plans, notes

    def _resolve_run(self, alias, cfg, databases: Dict[str, str], wanted, targets, window):
        """Sources for every wanted element from one cycle, and what is missing."""

        sources: Dict[str, Source] = {}
        missing: List[str] = []
        for elem in wanted:
            spec = ELEMENT_SPECS[elem]
            src, why = self._find_source(alias, cfg, spec, databases, targets[elem], window, elem)
            if src is None and elem == "WindGust":
                src, _ = self._find_source(alias, cfg, ELEMENT_SPECS["Wind"], databases, targets[elem], window, elem)
                if src is not None:
                    src.from_wind = True
            if src is None:
                missing.append("%s %s" % (elem, why))
            else:
                sources[elem] = src
        return sources, missing

    def _find_source(self, alias, cfg, spec: ElementSpec, databases, times, window, fcst_elem):
        """First database/element/level of this cycle that covers every time."""

        preferred = model_aliases.get_database_candidates_for_element(alias, spec.key, dataset=spec.dataset)
        order = [name for name in preferred if name in databases]
        order += [name for name in databases if name not in order]

        pairs = list(spec.sources)
        if spec.dataset == "wave" and cfg.wave is not None:
            level = cfg.wave.default_levels.get("wave")
            if level:
                pairs = [(element, lvl) for element, _ in spec.sources[:1]
                         for lvl in (level, grid_fetch._normalize_level(level))] + pairs

        why = "not in %s" % ", ".join(order)
        partial = None
        for name in order:
            model_id = databases[name]
            for element, level in pairs:
                inventory = grid_fetch.grid_times(self, model_id, element, level, window)
                if not inventory:
                    continue
                recipes = {}
                gap = None
                for tr in times:
                    start, end = tr_key(tr)
                    recipe = time_recipe(inventory, start, end)
                    if recipe is None:
                        gap = start
                        break
                    recipes[(start, end)] = recipe
                if gap is None:
                    factor = unit_factor(self._units(model_id, element, level),
                                         self._units("Fcst", fcst_elem, FCST_LEVEL))
                    return Source(model_id, element, level, spec.key, factor, recipes), ""
                if partial is None:
                    partial = "has no grid at or near %s (%s ends %s)" % (
                        fmt_time(gap), name, fmt_time(inventory[-1][0]))
        return None, partial or why

    def _units(self, model_id, element, level) -> Optional[str]:
        try:
            return str(self.getParm(model_id, element, level).getGridInfo().getUnitString())
        except Exception:
            return None

    # ---------------------------------------------------------------- blending

    def _check_grids(self, plans: List[ModelPlan], elements):
        """Read every model grid the blend will use once, before anything is written."""

        seen = set()
        for plan in plans:
            for elem in elements:
                src = plan.sources[elem]
                for recipe in src.recipes.values():
                    for tr in (recipe[1:3] if recipe[0] == "interp" else recipe[1:2]):
                        key = (src.model_id, src.element, src.level, tr_key(tr))
                        if key in seen:
                            continue
                        seen.add(key)
                        parts = self._read_one(plan, src, tr)
                        value = np.hypot(*parts) if len(parts) == 2 else parts[0]
                        bad = empty_reason(value)
                        if bad:
                            raise BlendError("%s %s %s grid for %s is empty (%s) in %s"
                                             % (plan.label, src.element, src.level,
                                                fmt_time(tr.startTime().unixTime()), bad, src.model_id))

    def _read_one(self, plan: ModelPlan, src: Source, tr):
        """One model grid as stored: (u, v) or (value,), in model units."""

        grid = self.getGrids(src.model_id, src.element, src.level, tr, mode="First", noDataError=0)
        if grid is None:
            raise BlendError("%s %s %s at %s could not be read although it is in the inventory"
                             % (plan.label, src.element, src.level, fmt_time(tr.startTime().unixTime())))
        if ELEMENT_SPECS[src.read_as].vector:
            u, v = self.MagDirToUV(np.asarray(grid[0], dtype=float), np.asarray(grid[1], dtype=float))
            return (np.asarray(u, dtype=float), np.asarray(v, dtype=float))
        return (np.asarray(grid, dtype=float),)

    def _read(self, plan: ModelPlan, src: Source, recipe, fcst_elem: str):
        """One model's grid at one Fcst time, in Fcst units: (u, v) or (value,)."""

        if recipe[0] == "direct":
            parts = self._read_one(plan, src, recipe[1])
        else:
            a, b, w = self._read_one(plan, src, recipe[1]), self._read_one(plan, src, recipe[2]), recipe[3]
            parts = tuple(x * (1.0 - w) + y * w for x, y in zip(a, b))

        factor = src.factor
        if factor is None:
            # Units unreadable: catch the one mix-up that matters most.
            factor = 0.01 if fcst_elem == "pmsl" and np.nanmax(parts[0]) > 2000 else 1.0
        return tuple(p * factor for p in parts)

    def _blend(self, elem: str, tr, plans: List[ModelPlan], gust_factor: float):
        """Weighted blend of every model at one time; also where any model had data."""

        key = tr_key(tr)
        shape = None
        value_sum = u_sum = v_sum = weight_sum = None

        for plan in plans:
            src = plan.sources[elem]
            parts = self._read(plan, src, src.recipes[key], elem)
            if len(parts) == 2:
                u, v = parts
                value = np.hypot(u, v)
                if src.from_wind:
                    value = value * gust_factor
            else:
                value = parts[0]

            bad = empty_reason(value)
            if bad:
                raise BlendError("%s %s for %s is empty (%s) - %s"
                                 % (plan.label, src.element, fmt_time(key[0]), bad, src.model_id))

            if shape is None:
                shape = value.shape
                value_sum = np.zeros(shape)
                weight_sum = np.zeros(shape)
                if elem == "Wind":
                    u_sum = np.zeros(shape)
                    v_sum = np.zeros(shape)
            ok = np.isfinite(value)
            w = np.where(ok, plan.weight, 0.0)
            value_sum += np.where(ok, value, 0.0) * w
            weight_sum += w
            if elem == "Wind":
                u_sum += np.where(ok, u, 0.0) * w
                v_sum += np.where(ok, v, 0.0) * w

        covered = weight_sum > 0
        safe = np.where(covered, weight_sum, 1.0)
        value = value_sum / safe
        if elem == "Wind":
            _, direction = self.UVToMagDir(u_sum / safe, v_sum / safe)
            return (value, np.asarray(direction, dtype=float)), covered
        return value, covered

    def _blend_deterministic(self, tr, plans: List[ModelPlan]):
        """Deterministic blend of Wind at one time (see the docstring)."""

        key = tr_key(tr)
        kt = unit_factor("kt", self._units("Fcst", "Wind", FCST_LEVEL)) or 1.0
        current, runs, u_cur, v_cur = [], [], [], []
        for plan in plans:
            src = plan.sources["Wind"]
            u, v = self._read(plan, src, src.recipes[key], "Wind")
            speed = np.hypot(u, v) / kt  # kt
            bad = empty_reason(speed)
            if bad:
                raise BlendError("%s wind for %s is empty (%s) - %s"
                                 % (plan.label, fmt_time(key[0]), bad, src.model_id))
            runs.append(speed)
            if plan.weight > 0:
                current.append(speed)
                u_cur.append(u)
                v_cur.append(v)

        runs = np.array(runs)
        current = np.array(current)
        ok = np.isfinite(runs)
        n = ok.sum(0)
        run_vals = np.where(ok, runs, 0.0)

        # Support: share of the runs near each current model's speed.
        weights = []
        for speed in current:
            near = np.exp(-0.5 * ((runs - speed[None]) / DET_SUPPORT_KT) ** 2)
            share = np.where(ok, near, 0.0).sum(0) / np.maximum(n, 1)
            weights.append(np.where(np.isfinite(speed), share + 1e-6, 0.0))
        weights = np.array(weights)
        w_sum = weights.sum(0)
        covered = w_sum > 0
        safe = np.where(covered, w_sum, 1.0)
        base = (weights * np.where(np.isfinite(current), current, 0.0)).sum(0) / safe

        mean = run_vals.sum(0) / np.maximum(n, 1)
        var = np.where(ok, (runs - mean[None]) ** 2, 0.0).sum(0) / np.maximum(n, 1)
        boost = np.where(n >= 2, np.minimum(DET_SPREAD_K * np.sqrt(var), DET_CAP_KT), 0.0)
        speed = (base + boost) * kt

        cur_ok = np.isfinite(np.array(u_cur))
        count = np.maximum(cur_ok.sum(0), 1)
        u_mean = np.where(cur_ok, u_cur, 0.0).sum(0) / count
        v_mean = np.where(cur_ok, v_cur, 0.0).sum(0) / count
        _, direction = self.UVToMagDir(u_mean, v_mean)
        return (speed, np.asarray(direction, dtype=float)), covered

    def _raise_gusts(self, selection, mask: np.ndarray) -> int:
        """Raise existing Fcst WindGust to the strongest Fcst Wind it overlaps."""

        count = 0
        for _, _, gust_tr in grid_fetch.grid_times(self, "Fcst", "WindGust", FCST_LEVEL, selection):
            gust = self.getGrids("Fcst", "WindGust", FCST_LEVEL, gust_tr, mode="First", noDataError=0)
            if gust is None:
                continue
            wind_max = None
            for _, _, wind_tr in grid_fetch.grid_times(self, "Fcst", "Wind", FCST_LEVEL, gust_tr):
                wind = self.getGrids("Fcst", "Wind", FCST_LEVEL, wind_tr, mode="First", noDataError=0)
                if wind is None:
                    continue
                speed = np.asarray(wind[0], dtype=float)
                wind_max = speed if wind_max is None else np.maximum(wind_max, speed)
            if wind_max is None:
                continue
            gust = np.asarray(gust, dtype=float)
            low = mask & (gust < wind_max)
            if low.any():
                self.createGrid("Fcst", "WindGust", "SCALAR",
                                np.where(low, wind_max, gust).astype(np.float32), gust_tr)
                count += 1
        return count

    def _write(self, elem: str, tr, result, covered: np.ndarray, mask: np.ndarray):
        spec = ELEMENT_SPECS[elem]
        use = mask & covered
        existing = self.getGrids("Fcst", elem, FCST_LEVEL, tr, mode="First", noDataError=0)

        def merge(new, old, fill):
            if old is not None:
                return np.where(use, new, np.asarray(old, dtype=float))
            return np.where(covered, new, fill)

        if spec.vector:
            speed, direction = result
            speed = np.maximum(speed, spec.floor)
            old_speed, old_dir = existing if existing is not None else (None, None)
            speed = merge(speed, old_speed, 0.0)
            direction = np.mod(merge(direction, old_dir, 0.0), 360.0)
            grid = (speed.astype(np.float32), direction.astype(np.float32))
            self.createGrid("Fcst", elem, "VECTOR", grid, tr)
            if use.any():
                self.log("  %s %s: mean %.1f, max %.1f" % (elem, fmt_time(tr_key(tr)[0]),
                                                          float(np.mean(speed[use])), float(np.max(speed[use]))))
            return

        value = result
        if spec.floor is not None:
            value = np.maximum(value, spec.floor)
        if elem == "WindGust":
            wind = self.getGrids("Fcst", "Wind", FCST_LEVEL, tr, mode="First", noDataError=0)
            if wind is not None:
                value = np.maximum(value, np.asarray(wind[0], dtype=float))
        fill = float(np.mean(value[covered])) if spec.floor is None else spec.floor
        value = merge(value, existing, fill)
        self.createGrid("Fcst", elem, "SCALAR", value.astype(np.float32), tr)
        if use.any():
            self.log("  %s %s: mean %.1f, min %.1f, max %.1f" % (
                elem, fmt_time(tr_key(tr)[0]), float(np.mean(value[use])),
                float(np.min(value[use])), float(np.max(value[use]))))


__all__ = ["Procedure", "BlendDialog"]
