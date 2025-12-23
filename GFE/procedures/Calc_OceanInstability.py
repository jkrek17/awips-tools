"""
Ocean Instability Analysis - Marine wind mixing and fog analysis tool.

Modular rewrite using shared utilities for model access and unit conversions.
Calculates SST-based instability indices, wind mixing potential, and fog formation.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional

import numpy as np

import SmartScript

import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Edit"]
VariableList = []

# Configuration
ATMOSPHERIC_MODELS = ["GFS", "ECMWF", "CMC", "UKMET"]
SST_SOURCES = ["Fcst", "RTOFS"]

# Physical constants
GRAVITY = 9.81
KELVIN_OFFSET = 273.15


class OceanInstabilityGUI:
    """GUI for marine wind/fog analysis configuration."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Ocean Instability Analysis")
        self.master.geometry("600x800")

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        tk.Label(main, text="Marine Wind Mixing & Fog Analysis", font=("Arial", 14, "bold")).pack(pady=(0, 10))

        # SST Source
        sst_frame = tk.LabelFrame(main, text="SST Source", padx=10, pady=5)
        sst_frame.pack(fill=tk.X, pady=(0, 10))

        self.sst_var = tk.StringVar(value="Fcst")
        for src in SST_SOURCES:
            tk.Radiobutton(sst_frame, text=src, variable=self.sst_var, value=src).pack(anchor=tk.W)

        # Model Selection
        model_frame = tk.LabelFrame(main, text="Atmospheric Models", padx=10, pady=5)
        model_frame.pack(fill=tk.X, pady=(0, 10))

        self.model_vars = {}
        for model in ATMOSPHERIC_MODELS:
            var = tk.BooleanVar(value=(model == "GFS"))
            self.model_vars[model] = var
            tk.Checkbutton(model_frame, text=model, variable=var).pack(anchor=tk.W)

        # Model Run
        run_frame = tk.LabelFrame(main, text="Model Run", padx=10, pady=5)
        run_frame.pack(fill=tk.X, pady=(0, 10))

        self.run_var = tk.StringVar(value="Current")
        tk.Radiobutton(run_frame, text="Current", variable=self.run_var, value="Current").pack(side=tk.LEFT)
        tk.Radiobutton(run_frame, text="Previous", variable=self.run_var, value="Previous").pack(side=tk.LEFT)

        # Output Grids
        output_frame = tk.LabelFrame(main, text="Output Grids", padx=10, pady=5)
        output_frame.pack(fill=tk.X, pady=(0, 10))

        self.output_vars = {}
        outputs = [
            ("SSTInstability850", "SST-T850 Instability Index", True),
            ("SSTInstability925", "SST-T925 Instability Index", True),
            ("WindMixingPotential", "Wind Mixing Potential", True),
            ("FogPotential", "Marine Fog Potential", True),
            ("WindShear", "850-925mb Wind Shear", False),
        ]
        for grid_id, desc, default in outputs:
            var = tk.BooleanVar(value=default)
            self.output_vars[grid_id] = var
            tk.Checkbutton(output_frame, text=desc, variable=var).pack(anchor=tk.W)

        # Buttons
        btn_frame = tk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(btn_frame, text="Run Analysis", command=self._run, bg="lightblue", width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=self._cancel, width=10).pack(side=tk.LEFT)

    def _run(self):
        selected_models = [m for m, v in self.model_vars.items() if v.get()]
        selected_outputs = [g for g, v in self.output_vars.items() if v.get()]

        self.callback({
            "sst_source": self.sst_var.get(),
            "models": selected_models,
            "model_run": self.run_var.get(),
            "outputs": selected_outputs,
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Ocean instability analysis procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution."""
        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                self.statusBarMsg("Analysis cancelled", "S")
                return

        models = varDict["models"]
        sst_source = varDict["sst_source"]
        model_run = varDict["model_run"]
        outputs = varDict["outputs"]

        if not models:
            self.statusBarMsg("No models selected", "S")
            return

        fcst = self.mutableID().modelIdentifier()
        grid_infos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not grid_infos:
            grid_infos = self.getGridInfo(fcst, "SST", "SFC", timeRange)

        if not grid_infos:
            self.statusBarMsg("No grids found for time range", "S")
            return

        self.statusBarMsg(f"Processing {len(grid_infos)} periods...", "R")

        for i, grid_info in enumerate(grid_infos):
            grid_tr = grid_info.gridTime()
            self.statusBarMsg(f"Period {i+1}/{len(grid_infos)}", "R")

            # Get SST
            sst_c = self._get_sst(sst_source, grid_tr)
            if sst_c is None:
                continue

            # Get model data
            t850_c, t925_c, wind_850, wind_925 = self._get_model_data(models, model_run, grid_tr)

            if t850_c is None:
                continue

            # Calculate instability indices
            if "SSTInstability850" in outputs and t850_c is not None:
                instab_850 = np.clip(sst_c - t850_c, -20.0, 20.0)
                self.createGrid("Fcst", "SSTInstability850", "SCALAR", instab_850, grid_tr,
                               minAllowedValue=-20.0, maxAllowedValue=20.0, units="C")

            if "SSTInstability925" in outputs and t925_c is not None:
                instab_925 = np.clip(sst_c - t925_c, -20.0, 20.0)
                self.createGrid("Fcst", "SSTInstability925", "SCALAR", instab_925, grid_tr,
                               minAllowedValue=-20.0, maxAllowedValue=20.0, units="C")

            # Wind mixing potential
            if "WindMixingPotential" in outputs and wind_850 is not None:
                instab = sst_c - t850_c if t850_c is not None else sst_c - t925_c
                mixing = self._calc_mixing_potential(instab, wind_850[0])
                self.createGrid("Fcst", "WindMixingPotential", "SCALAR", mixing, grid_tr,
                               minAllowedValue=0.0, maxAllowedValue=10.0)

            # Wind shear
            if "WindShear" in outputs and wind_850 is not None and wind_925 is not None:
                shear = self._calc_wind_shear(wind_850, wind_925)
                self.createGrid("Fcst", "WindShear", "SCALAR", shear, grid_tr,
                               minAllowedValue=0.0, maxAllowedValue=30.0, units="m/s")

            # Fog potential
            if "FogPotential" in outputs:
                instab = sst_c - t850_c if t850_c is not None else np.zeros_like(sst_c)
                fog = self._calc_fog_potential(sst_c, instab)
                self.createGrid("Fcst", "FogPotential", "SCALAR", fog, grid_tr,
                               minAllowedValue=0.0, maxAllowedValue=10.0)

        self.statusBarMsg("Ocean instability analysis complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = OceanInstabilityGUI(root, callback)
        root.mainloop()
        return result[0]

    def _get_sst(self, source: str, grid_tr) -> Optional[np.ndarray]:
        """Get SST data in Celsius."""
        if source == "RTOFS":
            grid = grid_fetch.get_grid(self, "RTOFS", "SST", "SFC", grid_tr, mode="First", noDataError=0)
        else:
            grid = self.getGrids("Fcst", "SST", "SFC", grid_tr, noDataError=0)

        if grid is None:
            return None

        # Convert to Celsius if needed
        if np.max(grid) > 50:  # Fahrenheit
            return thresholds.f_to_c(grid)
        elif np.max(grid) > 200:  # Kelvin
            return thresholds.k_to_c(grid)
        return grid

    def _get_model_data(self, models: List[str], run: str, grid_tr):
        """Get atmospheric model data (temperature and winds at 850/925mb)."""
        run_depth = 1 if run == "Current" else 2

        t850_sum, t925_sum = None, None
        wind_850_sum, wind_925_sum = None, None
        count = 0

        for alias in models:
            # Get 850mb temperature
            t850 = grid_fetch.get_grid(self, alias, "t", "MB850", grid_tr, run_depth=run_depth, noDataError=0)
            if t850 is not None:
                t850_c = thresholds.k_to_c(t850) if np.max(t850) > 200 else t850
                t850_sum = t850_c if t850_sum is None else t850_sum + t850_c

            # Get 925mb temperature
            t925 = grid_fetch.get_grid(self, alias, "t", "MB925", grid_tr, run_depth=run_depth, noDataError=0)
            if t925 is not None:
                t925_c = thresholds.k_to_c(t925) if np.max(t925) > 200 else t925
                t925_sum = t925_c if t925_sum is None else t925_sum + t925_c

            # Get 850mb wind
            w850 = grid_fetch.get_vector_grid(self, alias, "wind", "MB850", grid_tr, run_depth=run_depth, noDataError=0)
            if w850 is not None:
                wind_850_sum = w850 if wind_850_sum is None else (wind_850_sum[0] + w850[0], wind_850_sum[1])

            # Get 925mb wind
            w925 = grid_fetch.get_vector_grid(self, alias, "wind", "MB925", grid_tr, run_depth=run_depth, noDataError=0)
            if w925 is not None:
                wind_925_sum = w925 if wind_925_sum is None else (wind_925_sum[0] + w925[0], wind_925_sum[1])

            count += 1

        # Average
        if count > 1:
            if t850_sum is not None:
                t850_sum /= count
            if t925_sum is not None:
                t925_sum /= count
            if wind_850_sum is not None:
                wind_850_sum = (wind_850_sum[0] / count, wind_850_sum[1])
            if wind_925_sum is not None:
                wind_925_sum = (wind_925_sum[0] / count, wind_925_sum[1])

        return t850_sum, t925_sum, wind_850_sum, wind_925_sum

    def _calc_mixing_potential(self, instability: np.ndarray, wind_speed: np.ndarray) -> np.ndarray:
        """Calculate wind mixing potential (0-10 scale)."""
        # Higher instability + higher wind = more mixing
        instab_factor = np.where(instability > 0, 1.0 + instability / 10.0, 1.0 / (1.0 - instability / 20.0))
        instab_factor = np.clip(instab_factor, 0.3, 1.8)

        wind_factor = np.minimum(wind_speed / 15.0, 2.0)
        wind_factor = np.maximum(wind_factor, 0.2)

        mixing = instab_factor * wind_factor * 2.5
        return np.clip(mixing, 0.0, 10.0)

    def _calc_wind_shear(self, wind_850, wind_925) -> np.ndarray:
        """Calculate wind shear magnitude between levels."""
        u850 = -wind_850[0] * np.sin(np.radians(wind_850[1]))
        v850 = -wind_850[0] * np.cos(np.radians(wind_850[1]))
        u925 = -wind_925[0] * np.sin(np.radians(wind_925[1]))
        v925 = -wind_925[0] * np.cos(np.radians(wind_925[1]))

        du = u850 - u925
        dv = v850 - v925
        return np.sqrt(du**2 + dv**2)

    def _calc_fog_potential(self, sst: np.ndarray, instability: np.ndarray) -> np.ndarray:
        """Calculate marine fog formation potential (0-10 scale)."""
        # Stable conditions favor fog
        stability_factor = np.where(instability <= 0, 1.0 + np.abs(instability) / 10.0, 1.0 / (1.0 + instability / 5.0))
        stability_factor = np.clip(stability_factor, 0.1, 2.0)

        fog = stability_factor * 4.0
        return np.clip(fog, 0.0, 10.0)


__all__ = ["Procedure"]

