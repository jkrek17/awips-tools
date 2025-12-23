"""
Modernized Wind/Gust/Wave blend tool that leverages the shared utilities.

Uses the centralized model alias registry for model configuration.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
from scipy import ndimage

import SmartScript

import grid_fetch
import model_aliases

MenuItems = ["Edit"]
ToolType = "numeric"
WeatherElementEdited = "Wind"
ScreenList = ["Wind", "WindGust", "WaveHeight"]


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    label: str
    max_runs: int


def _build_model_configs(kind: str) -> List[ModelConfig]:
    """Build model configs from the model alias registry."""
    configs: List[ModelConfig] = []
    # Ensure Fcst/Official appear first for wind models
    if kind == "atmo":
        configs.extend([
            ModelConfig(alias="Fcst", label="Forecast", max_runs=1),
            ModelConfig(alias="Official", label="Official", max_runs=1),
        ])
    for alias, display_name, max_runs in model_aliases.list_models_for_gui(kind):
        configs.append(ModelConfig(alias=alias, label=display_name, max_runs=max_runs))
    return configs


WIND_MODEL_CONFIGS = _build_model_configs(kind="atmo")
WAVE_MODEL_CONFIGS = _build_model_configs(kind="wave")


class WindBlendGUI:
    """
    Simplified slider-based GUI inspired by the legacy implementation.
    """

    def __init__(self, master, callback, wind_configs, wave_configs):
        self.master = master
        self.callback = callback
        self.master.title("Wind and Gust Blend Tool")
        self.master.geometry("520x740")
        self.master.resizable(True, True)

        self.wind_configs = wind_configs
        self.wave_configs = wave_configs
        self.modelWeights: Dict[str, tk.IntVar] = {}

        self.gustMultiplier = tk.DoubleVar(value=1.2)
        self.createWaves = tk.StringVar(value="Yes")
        self.applySmoothing = tk.StringVar(value="No")
        self.smoothingPasses = tk.IntVar(value=1)

        self.createWidgets()

    def createWidgets(self):
        main = tk.Frame(self.master, padx=12, pady=12)
        main.pack(fill=tk.BOTH, expand=True)

        tk.Label(main, text="Wind and Gust Blend Tool", font=("Arial", 16, "bold")).pack(pady=(0, 10))

        modelFrame = tk.LabelFrame(main, text="Wind Model Weights", padx=10, pady=10)
        modelFrame.pack(fill=tk.X, pady=(0, 10))
        self._buildWeightSliders(modelFrame, self.wind_configs)

        gustFrame = tk.LabelFrame(main, text="Gust Options", padx=10, pady=10)
        gustFrame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(gustFrame, text="Gust Multiplier:").pack(anchor=tk.W)
        tk.Spinbox(
            gustFrame,
            from_=1.0,
            to=2.5,
            increment=0.1,
            width=10,
            textvariable=self.gustMultiplier,
        ).pack(anchor=tk.W)

        tk.LabelFrame(main, text="Wave Options", padx=10, pady=10)

        tk.Checkbutton(
            main,
            text="Create Wave Height grids with same blend",
            variable=self.createWaves,
            onvalue="Yes",
            offvalue="No",
        ).pack(anchor=tk.W)

        smoothFrame = tk.LabelFrame(main, text="Smoothing", padx=10, pady=10)
        smoothFrame.pack(fill=tk.X, pady=(10, 10))

        tk.Checkbutton(
            smoothFrame,
            text="Apply smoothing to output grids",
            variable=self.applySmoothing,
            onvalue="Yes",
            offvalue="No",
        ).pack(anchor=tk.W)

        tk.Scale(
            smoothFrame,
            from_=1,
            to=5,
            orient=tk.HORIZONTAL,
            variable=self.smoothingPasses,
            width=15,
        ).pack(anchor=tk.W, padx=(0, 40))

        buttonFrame = tk.Frame(main)
        buttonFrame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(buttonFrame, text="Run Tool", command=self._run, bg="lightgreen", width=15).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        tk.Button(buttonFrame, text="Cancel", command=self._cancel, width=15).pack(side=tk.LEFT)

    def _buildWeightSliders(self, frame, configs: Sequence[ModelConfig]):
        for config in configs:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=f"{config.label}:", width=16, anchor=tk.W).pack(side=tk.LEFT)
            var = tk.IntVar(value=5 if config.alias in {"Fcst", "GFS"} else 0)
            tk.Scale(row, from_=0, to=5, orient=tk.HORIZONTAL, variable=var, width=20).pack(
                side=tk.LEFT, fill=tk.X, expand=True
            )
            self.modelWeights[config.alias] = var

    def _run(self):
        self.callback(self._collect_values())
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()

    def _collect_values(self):
        return {
            "weights": {alias: var.get() for alias, var in self.modelWeights.items()},
            "gust_multiplier": self.gustMultiplier.get(),
            "create_waves": self.createWaves.get(),
            "apply_smoothing": self.applySmoothing.get(),
            "smoothing_passes": self.smoothingPasses.get(),
        }


class Procedure(SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def showGUI(self, editArea, timeRange):
        self.editArea = editArea
        self.timeRange = timeRange
        self.varDict = None

        root = tk.Tk()
        gui = WindBlendGUI(root, self.guiCallback, WIND_MODEL_CONFIGS, WAVE_MODEL_CONFIGS)
        root.mainloop()

        return self.varDict

    def guiCallback(self, values):
        self.varDict = values

    def execute(self, editArea, timeRange, varDict=None):
        if varDict is None:
            varDict = self.showGUI(editArea, timeRange)
            if varDict is None:
                return

        weights = self._normalize_weights(varDict["weights"])
        active_wind = [cfg for cfg in WIND_MODEL_CONFIGS if weights.get(cfg.alias, 0.0) > 0]
        if not active_wind:
            self.statusBarMsg("No models selected for blending", "S")
            return

        gust_multiplier = float(varDict["gust_multiplier"])
        create_waves = varDict["create_waves"] == "Yes"
        apply_smoothing = varDict["apply_smoothing"] == "Yes"
        smoothing_passes = int(varDict["smoothing_passes"])

        time_ranges = self._collect_time_ranges(timeRange)
        if not time_ranges:
            self.statusBarMsg("No valid time ranges selected", "A")
            return

        for tr in time_ranges:
            blended_wind = self._blend_wind(active_wind, weights, tr, smoothing_passes if apply_smoothing else 0)
            if blended_wind is None:
                continue
            mag = np.clip(blended_wind[0], 0.0, 150.0)
            direc = np.mod(blended_wind[1], 360.0)
            self.createGrid("Fcst", "Wind", "VECTOR", (mag, direc), tr)

            gust = np.clip(mag * gust_multiplier, 0.0, 150.0)
            self.createGrid("Fcst", "WindGust", "SCALAR", gust, tr)

            if create_waves:
                blended_wave = self._blend_waves(weights, tr, smoothing_passes if apply_smoothing else 0)
                if blended_wave is not None:
                    self.createGrid("Fcst", "WaveHeight", "SCALAR", blended_wave, tr, minAllowedValue=0.0)

        self.statusBarMsg("Wind/Gust/Wave blend complete", "R")

    def _collect_time_ranges(self, selection):
        ranges = []
        gridinfos = self.getGridInfo("Fcst", "Wind", "SFC", selection)
        for info in gridinfos or []:
            ranges.append(info.gridTime())
        return ranges

    def _normalize_weights(self, weight_dict: Dict[str, int]) -> Dict[str, float]:
        total = sum(weight_dict.values())
        if total == 0:
            return {alias: 0.0 for alias in weight_dict}
        return {alias: val / total for alias, val in weight_dict.items()}

    def _blend_wind(self, configs: Sequence[ModelConfig], weights: Dict[str, float], tr, smoothing_passes: int):
        mag_base = None
        dir_base = None
        u_sum = None
        v_sum = None
        total_weight = 0.0

        for cfg in configs:
            weight = weights.get(cfg.alias, 0.0)
            if weight <= 0:
                continue

            grid = grid_fetch.get_vector_grid(self, cfg.alias, "Wind", "SFC", tr, run_depth=1, noDataError=0)
            if grid is None:
                self.statusBarMsg(f"{cfg.label}: missing data for {tr}", "S")
                continue

            mag, direc = grid
            if u_sum is None:
                mag_base, dir_base = mag.copy(), direc.copy()
                u_sum = np.zeros_like(mag, dtype=float)
                v_sum = np.zeros_like(direc, dtype=float)

            u, v = self.MagDirToUV(mag, direc)
            u_sum += u * weight
            v_sum += v * weight
            total_weight += weight

        if total_weight == 0 or u_sum is None or v_sum is None:
            return None

        u_avg = u_sum / total_weight
        v_avg = v_sum / total_weight
        mag, direc = self.UVToMagDir(u_avg, v_avg)

        if smoothing_passes > 0:
            sigma = 0.5 * smoothing_passes
            mag = ndimage.gaussian_filter(mag, sigma=sigma, mode="nearest")
            direc = ndimage.gaussian_filter(direc, sigma=sigma, mode="nearest")

        return (mag, direc)

    def _blend_waves(self, weights: Dict[str, float], tr, smoothing_passes: int):
        configs = [cfg for cfg in WAVE_MODEL_CONFIGS if weights.get(cfg.alias, 0.0) > 0]
        if not configs:
            return None

        wave_sum = None
        total_weight = 0.0

        for cfg in configs:
            weight = weights.get(cfg.alias, 0.0)
            if weight <= 0:
                continue
            grid = grid_fetch.get_grid(self, cfg.alias, "WaveHeight", "SFC", tr, run_depth=1, mode="First")
            if grid is None:
                self.statusBarMsg(f"{cfg.label}: missing wave data for {tr}", "S")
                continue
            if wave_sum is None:
                wave_sum = np.zeros_like(grid, dtype=float)
            wave_sum += grid * weight
            total_weight += weight

        if total_weight == 0 or wave_sum is None:
            return None

        blended = wave_sum / total_weight
        if smoothing_passes > 0:
            sigma = 0.5 * smoothing_passes
            blended = ndimage.gaussian_filter(blended, sigma=sigma, mode="nearest")
        blended = np.clip(blended, 0.0, 60.0)
        return blended


__all__ = ["Procedure"]

