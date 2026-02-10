"""
Blend_StormArea - Multi-model blend restricted to an edit area.

Designed to pair with Analyze_MarineStorms:

    1. Run Analyze_MarineStorms to identify storms and create edit areas.
    2. Select a storm edit area (e.g. ``Storm_001``) or draw one manually.
    3. Run Blend_StormArea to blend Wind / WindGust / WaveHeight from
       chosen models within just that area, with smooth taper at edges.

The key difference from Blend_WindGustWave is that this tool **only
modifies the selected area** -- the rest of the forecast grid is
untouched.  Edge tapering ensures no hard discontinuities.

Works with any edit area, not only storm edit areas.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

import SmartScript

import grid_fetch
import model_aliases

MenuItems = ["Edit"]
ToolType = "numeric"
WeatherElementEdited = "Wind"
ScreenList = ["Wind", "WindGust", "WaveHeight"]


# ---------------------------------------------------------------------------
# Model configuration from shared registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    alias: str
    label: str
    max_runs: int


def _build_model_configs(kind):
    # type: (str) -> List[ModelConfig]
    configs = []  # type: List[ModelConfig]
    if kind == "atmo":
        configs.extend([
            ModelConfig(alias="Fcst", label="Forecast", max_runs=1),
            ModelConfig(alias="Official", label="Official", max_runs=1),
        ])
    for alias, display_name, max_runs in model_aliases.list_models_for_gui(kind):
        configs.append(ModelConfig(alias=alias, label=display_name,
                                   max_runs=max_runs))
    return configs


WIND_MODELS = _build_model_configs("atmo")
WAVE_MODELS = _build_model_configs("wave")


# ===========================================================================
# GUI
# ===========================================================================

class StormBlendGUI:
    """Slider-based model blend GUI with edge-taper controls."""

    def __init__(self, master, callback, wind_configs, has_edit_area):
        self.master = master
        self.callback = callback
        self.master.title("Blend Storm Area")
        self.master.geometry("560x780")
        self.master.resizable(True, True)

        self.wind_configs = wind_configs
        self.weights = {}       # type: Dict[str, tk.IntVar]
        self.weight_labels = {} # type: Dict[str, tk.Label]
        self.has_edit_area = has_edit_area

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=12, pady=12)
        main.pack(fill=tk.BOTH, expand=True)

        tk.Label(main, text="Blend Storm Area",
                 font=("Arial", 16, "bold")).pack(pady=(0, 3))
        tk.Label(main, text="Multi-model blend inside the active edit area",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 12))

        if not self.has_edit_area:
            tk.Label(main,
                     text="WARNING: No edit area selected -- blend will "
                          "apply to the entire grid.",
                     font=("Arial", 10, "bold"), fg="red",
                     wraplength=500).pack(pady=(0, 10))

        self._build_weight_frame(main)
        self._build_options_frame(main)
        self._build_buttons(main)

    # ---- weight sliders --------------------------------------------------

    def _build_weight_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Model Weights", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))

        for cfg in self.wind_configs:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=2)

            tk.Label(row, text="%s:" % cfg.label, width=18,
                     anchor=tk.W).pack(side=tk.LEFT)

            var = tk.IntVar(value=0)
            self.weights[cfg.alias] = var
            tk.Scale(row, from_=0, to=5, orient=tk.HORIZONTAL,
                     variable=var, command=self._update_pcts,
                     width=15).pack(side=tk.LEFT, fill=tk.X, expand=True)

            lbl = tk.Label(row, text="0%", width=5)
            lbl.pack(side=tk.RIGHT)
            self.weight_labels[cfg.alias] = lbl

        self.total_label = tk.Label(frame, text="No models selected",
                                    font=("Arial", 10, "bold"), fg="red")
        self.total_label.pack(pady=(6, 0))
        self._update_pcts()

    def _update_pcts(self, *_args):
        total = sum(v.get() for v in self.weights.values())
        for alias, var in self.weights.items():
            w = var.get()
            pct = int(w / float(total) * 100) if total > 0 else 0
            self.weight_labels[alias].config(text="%d%%" % pct)
        if total > 0:
            self.total_label.config(text="Models selected", fg="green")
        else:
            self.total_label.config(text="No models selected", fg="red")

    # ---- options ---------------------------------------------------------

    def _build_options_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Options", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))

        # Gust multiplier
        row1 = tk.Frame(frame)
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="Gust multiplier:", width=18,
                 anchor=tk.W).pack(side=tk.LEFT)
        self.gust_var = tk.DoubleVar(value=1.3)
        tk.Spinbox(row1, from_=1.0, to=2.0, increment=0.05,
                   textvariable=self.gust_var, width=5).pack(side=tk.LEFT)

        # Taper width
        row2 = tk.Frame(frame)
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="Edge taper (grid pts):", width=18,
                 anchor=tk.W).pack(side=tk.LEFT)
        self.taper_var = tk.IntVar(value=10)
        tk.Scale(row2, from_=0, to=30, orient=tk.HORIZONTAL,
                 variable=self.taper_var, length=180).pack(side=tk.LEFT)

        # Smoothing
        row3 = tk.Frame(frame)
        row3.pack(fill=tk.X, pady=2)
        self.smooth_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row3, text="Smooth blended result",
                       variable=self.smooth_var).pack(side=tk.LEFT)
        self.smooth_passes = tk.IntVar(value=2)
        tk.Spinbox(row3, from_=1, to=5, textvariable=self.smooth_passes,
                   width=3).pack(side=tk.LEFT, padx=5)
        tk.Label(row3, text="passes").pack(side=tk.LEFT)

        # Wave
        self.wave_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Also blend WaveHeight",
                       variable=self.wave_var).pack(anchor=tk.W, pady=(6, 0))

    # ---- buttons ---------------------------------------------------------

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(12, 0))
        tk.Button(frame, text="Run Blend", command=self._run,
                  bg="lightgreen", font=("Arial", 11, "bold"),
                  width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel,
                  width=10).pack(side=tk.LEFT)

    def _run(self):
        raw = {a: v.get() for a, v in self.weights.items()}
        if sum(raw.values()) == 0:
            self.total_label.config(text="Select at least one model",
                                    fg="red")
            return
        self.callback({
            "weights": raw,
            "gust_multiplier": self.gust_var.get(),
            "taper_width": self.taper_var.get(),
            "smooth": self.smooth_var.get(),
            "smooth_passes": self.smooth_passes.get(),
            "create_waves": self.wave_var.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


# ===========================================================================
# Smart-tool procedure
# ===========================================================================

class Procedure(SmartScript.SmartScript):
    """Multi-model blend restricted to the active edit area."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def execute(self, editArea, timeRange, varDict=None):
        # Resolve edit-area mask
        ea_mask = self._get_edit_area_mask(editArea)

        if varDict is None:
            varDict = self._show_gui(ea_mask is not None)
            if varDict is None:
                self.statusBarMsg("Blend cancelled", "S")
                return

        weights = self._normalize(varDict["weights"])
        active = [c for c in WIND_MODELS if weights.get(c.alias, 0) > 0]
        if not active:
            self.statusBarMsg("No models selected", "S")
            return

        taper_width = int(varDict["taper_width"])
        gust_mult = float(varDict["gust_multiplier"])
        do_smooth = varDict["smooth"]
        smooth_passes = int(varDict["smooth_passes"])
        do_waves = varDict["create_waves"]

        # Build taper grid (float 0-1) from edit area
        taper = self._build_taper(editArea, ea_mask, taper_width)

        # Process time periods
        trs = self._time_ranges(timeRange)
        if not trs:
            self.statusBarMsg("No grids in selected time range", "S")
            return

        total = len(trs)
        for idx, tr in enumerate(trs):
            self.statusBarMsg("Blending %d/%d" % (idx + 1, total), "R")

            # -- Wind -------------------------------------------------------
            blended = self._blend_wind(active, weights, tr)
            if blended is None:
                continue

            new_mag, new_dir = blended
            if do_smooth:
                sigma = 0.5 * smooth_passes
                new_mag = ndimage.gaussian_filter(new_mag, sigma=sigma,
                                                  mode="nearest")
                new_dir = ndimage.gaussian_filter(new_dir, sigma=sigma,
                                                  mode="nearest")

            new_mag = np.clip(new_mag, 0.0, 150.0)
            new_dir = np.mod(new_dir, 360.0)

            # Merge with existing Fcst using taper
            old_wind = self._get_fcst_wind(tr)
            if old_wind is not None and taper is not None:
                old_mag, old_dir = old_wind
                final_mag = old_mag + (new_mag - old_mag) * taper
                final_dir = old_dir + self._dir_diff(new_dir, old_dir) * taper
                final_dir = np.mod(final_dir, 360.0)
            else:
                final_mag, final_dir = new_mag, new_dir

            self.createGrid("Fcst", "Wind", "VECTOR",
                            (final_mag, final_dir), tr)

            # -- Gust -------------------------------------------------------
            new_gust = np.clip(final_mag * gust_mult, 0.0, 150.0)
            self.createGrid("Fcst", "WindGust", "SCALAR", new_gust, tr)

            # -- Wave -------------------------------------------------------
            if do_waves:
                new_wave = self._blend_waves(weights, tr)
                if new_wave is not None:
                    if do_smooth:
                        new_wave = ndimage.gaussian_filter(
                            new_wave, sigma=sigma, mode="nearest")
                    new_wave = np.clip(new_wave, 0.0, 60.0)
                    old_wave = self._get_fcst_scalar("WaveHeight", tr)
                    if old_wave is not None and taper is not None:
                        new_wave = old_wave + (new_wave - old_wave) * taper
                    self.createGrid("Fcst", "WaveHeight", "SCALAR",
                                    new_wave, tr, minAllowedValue=0.0)

        self.statusBarMsg("Storm-area blend complete", "R")

    # ---- GUI -------------------------------------------------------------

    def _show_gui(self, has_edit_area):
        root = tk.Tk()
        result = [None]

        def cb(vals):
            result[0] = vals

        StormBlendGUI(root, cb, WIND_MODELS, has_edit_area)
        root.mainloop()
        return result[0]

    # ---- edit-area helpers -----------------------------------------------

    def _get_edit_area_mask(self, editArea):
        """Convert the GFE edit area to a boolean mask, or None."""
        try:
            if editArea is None:
                return None
            if hasattr(editArea, "isEmpty") and editArea.isEmpty():
                return None
            mask = self.encodeEditArea(editArea)
            if mask is not None and np.any(mask):
                return mask
        except Exception:
            pass
        return None

    def _build_taper(self, editArea, ea_mask, taper_width):
        """
        Create a float 0..1 taper grid.

        1.0 inside the edit area, tapering to 0.0 over *taper_width*
        grid points at the edges.  If no edit area is active the
        returned taper is None (meaning: apply everywhere at full
        weight).
        """
        if ea_mask is None:
            return None

        if taper_width <= 0:
            return ea_mask.astype(np.float32)

        # Use GFE's built-in taper if available
        try:
            taper = self.taperGrid(editArea, taper_width)
            if taper is not None:
                return taper
        except Exception:
            pass

        # Fallback: distance-transform taper
        from scipy.ndimage import distance_transform_edt
        inner = ea_mask.astype(np.float32)
        dist_outside = distance_transform_edt(~ea_mask)
        taper = np.where(ea_mask, 1.0,
                         np.clip(1.0 - dist_outside / taper_width, 0.0, 1.0))
        return taper.astype(np.float32)

    # ---- blending --------------------------------------------------------

    def _normalize(self, raw):
        total = sum(raw.values())
        if total == 0:
            return {k: 0.0 for k in raw}
        return {k: v / float(total) for k, v in raw.items()}

    def _blend_wind(self, configs, weights, tr):
        u_sum = v_sum = None
        tw = 0.0
        for cfg in configs:
            w = weights.get(cfg.alias, 0.0)
            if w <= 0:
                continue
            grid = grid_fetch.get_vector_grid(
                self, cfg.alias, "Wind", "SFC", tr,
                run_depth=1, noDataError=0)
            if grid is None:
                continue
            mag, direc = grid
            u, v = self.MagDirToUV(mag, direc)
            if u_sum is None:
                u_sum = np.zeros_like(u, dtype=float)
                v_sum = np.zeros_like(v, dtype=float)
            u_sum += u * w
            v_sum += v * w
            tw += w
        if tw == 0 or u_sum is None:
            return None
        return self.UVToMagDir(u_sum / tw, v_sum / tw)

    def _blend_waves(self, weights, tr):
        w_sum = None
        tw = 0.0
        for cfg in WAVE_MODELS:
            w = weights.get(cfg.alias, 0.0)
            if w <= 0:
                continue
            grid = grid_fetch.get_grid(
                self, cfg.alias, "WaveHeight", "SFC", tr,
                run_depth=1, mode="First", noDataError=0)
            if grid is None:
                continue
            if w_sum is None:
                w_sum = np.zeros_like(grid, dtype=float)
            w_sum += grid * w
            tw += w
        if tw == 0 or w_sum is None:
            return None
        return w_sum / tw

    # ---- forecast retrieval ----------------------------------------------

    def _get_fcst_wind(self, tr):
        try:
            grid = self.getGrids("Fcst", "Wind", "SFC", tr,
                                 mode="First", noDataError=0)
            if grid is not None:
                return grid
        except Exception:
            pass
        return None

    def _get_fcst_scalar(self, element, tr):
        try:
            grid = self.getGrids("Fcst", element, "SFC", tr,
                                 mode="First", noDataError=0)
            return grid
        except Exception:
            return None

    def _time_ranges(self, selection):
        ranges = []
        infos = self.getGridInfo("Fcst", "Wind", "SFC", selection)
        for info in infos or []:
            ranges.append(info.gridTime())
        return ranges

    @staticmethod
    def _dir_diff(new_dir, old_dir):
        """Signed angular difference, shortest path."""
        diff = new_dir - old_dir
        diff = np.where(diff > 180, diff - 360, diff)
        diff = np.where(diff < -180, diff + 360, diff)
        return diff


__all__ = ["Procedure"]
