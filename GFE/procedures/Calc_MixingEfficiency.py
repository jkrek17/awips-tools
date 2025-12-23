"""
Marine Wind Adjustment Tool - Comprehensive wind mixing analysis.

Helps forecasters enhance winds during cold air advection over Gulf Stream
and identify low-level jets in stable conditions.

Modular rewrite using shared utilities for model access and unit conversions.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript

import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Populate"]
VariableList = []

# Available atmospheric models for wind analysis
ATMOSPHERIC_MODELS = ["GFS", "CMC", "ECMWF", "UKMET"]

# Mixing efficiency table (for unstable/neutral conditions)
# Format: (instability threshold, mixing efficiency, gust factor)
MIXING_TABLE = [
    (-15.0, 0.935, 1.28),  # Extreme unstable
    (-10.0, 0.910, 1.26),  # Strong unstable
    (-5.0,  0.890, 1.23),  # Moderate unstable
    (0.0,   0.865, 1.18),  # Weak unstable
    (3.0,   0.840, 1.12),  # Near neutral
    (5.0,   0.815, 1.08),  # Weakly stable
    (999.0, 0.775, 1.05),  # Stable
]


class MixingEfficiencyGUI:
    """GUI for marine wind adjustment configuration."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Wind Adjustment & LLJ Detection Tool")
        self.master.geometry("900x650")

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=12, pady=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Marine Wind Adjustment & LLJ Detection",
                 font=("Arial", 14, "bold")).pack(pady=(0, 10))

        # Two-column layout
        content = tk.Frame(main)
        content.pack(fill=tk.BOTH, expand=True)

        left_col = tk.Frame(content)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right_col = tk.Frame(content, relief=tk.RIDGE, borderwidth=2, bg="#f0f0f0")
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- LEFT COLUMN ---
        self._build_sst_frame(left_col)
        self._build_model_frame(left_col)
        self._build_threshold_frame(left_col)
        self._build_output_frame(left_col)
        self._build_buttons(left_col)

        # --- RIGHT COLUMN (Guide) ---
        self._build_guide(right_col)

    def _build_sst_frame(self, parent):
        frame = tk.LabelFrame(parent, text="SST Source", padx=10, pady=5)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.sst_source = tk.StringVar(value="Fcst")
        tk.Radiobutton(frame, text="Fcst", variable=self.sst_source, value="Fcst").pack(anchor=tk.W)
        tk.Radiobutton(frame, text="RTOFS", variable=self.sst_source, value="RTOFS").pack(anchor=tk.W)

        self.model_run = tk.StringVar(value="Current")
        tk.Radiobutton(frame, text="Current Run", variable=self.model_run, value="Current").pack(anchor=tk.W)
        tk.Radiobutton(frame, text="Previous Run", variable=self.model_run, value="Previous").pack(anchor=tk.W)

    def _build_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Select Models", padx=10, pady=5)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.model_vars = {}
        for model in ATMOSPHERIC_MODELS:
            var = tk.BooleanVar(value=(model == "GFS"))
            self.model_vars[model] = var
            tk.Checkbutton(frame, text=model, variable=var).pack(anchor=tk.W)

        self.status_label = tk.Label(frame, text="1 Model Selected", fg="green")
        self.status_label.pack(pady=(5, 0))

    def _build_threshold_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Thresholds", padx=10, pady=5)
        frame.pack(fill=tk.X, pady=(0, 10))

        row1 = tk.Frame(frame)
        row1.pack(fill=tk.X)
        tk.Label(row1, text="Unstable if T925-SST <").pack(side=tk.LEFT)
        self.unstable_thresh = tk.IntVar(value=-2)
        tk.Spinbox(row1, from_=-15, to=0, textvariable=self.unstable_thresh, width=5).pack(side=tk.LEFT)
        tk.Label(row1, text="°C").pack(side=tk.LEFT)

        row2 = tk.Frame(frame)
        row2.pack(fill=tk.X)
        tk.Label(row2, text="Stable if T925-SST >").pack(side=tk.LEFT)
        self.stable_thresh = tk.IntVar(value=2)
        tk.Spinbox(row2, from_=0, to=15, textvariable=self.stable_thresh, width=5).pack(side=tk.LEFT)
        tk.Label(row2, text="°C").pack(side=tk.LEFT)

        row3 = tk.Frame(frame)
        row3.pack(fill=tk.X)
        tk.Label(row3, text="LLJ if 925/Sfc wind ratio >").pack(side=tk.LEFT)
        self.llj_thresh = tk.DoubleVar(value=1.3)
        tk.Spinbox(row3, from_=1.1, to=2.0, increment=0.1, textvariable=self.llj_thresh, width=5, format="%.1f").pack(side=tk.LEFT)

        row4 = tk.Frame(frame)
        row4.pack(fill=tk.X)
        tk.Label(row4, text="Manual Adjustment:").pack(side=tk.LEFT)
        self.manual_adj = tk.IntVar(value=0)
        tk.Spinbox(row4, from_=-20, to=20, textvariable=self.manual_adj, width=5).pack(side=tk.LEFT)
        tk.Label(row4, text="%").pack(side=tk.LEFT)

    def _build_output_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Output Grids", padx=10, pady=5)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.apply_wind = tk.BooleanVar(value=True)
        self.apply_gust = tk.BooleanVar(value=True)
        self.create_925_wind = tk.BooleanVar(value=True)
        self.create_stability = tk.BooleanVar(value=True)
        self.create_adjustment = tk.BooleanVar(value=True)
        self.create_wind_shear = tk.BooleanVar(value=True)
        self.create_llj = tk.BooleanVar(value=True)

        tk.Checkbutton(frame, text="Wind", variable=self.apply_wind).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="WindGust", variable=self.apply_gust).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Wind_925mb", variable=self.create_925_wind).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Stability_Regime", variable=self.create_stability).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Adjustment_Applied", variable=self.create_adjustment).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="WindShear_925_Sfc", variable=self.create_wind_shear).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="LLJ_Indicator", variable=self.create_llj).pack(anchor=tk.W)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(10, 0))

        tk.Button(frame, text="Run Tool", command=self._run, bg="lightblue",
                  font=("Arial", 10, "bold"), width=12).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(frame, text="Cancel", command=self._cancel, width=10).pack(side=tk.LEFT)

    def _build_guide(self, parent):
        tk.Label(parent, text="Stability Regimes", font=("Arial", 10, "bold"),
                 bg="#f0f0f0").pack(pady=(10, 5))

        # Unstable
        unstable = tk.Frame(parent, bg="#e8f5e9", relief=tk.SOLID, borderwidth=1)
        unstable.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(unstable, text="UNSTABLE: Cold air over warm water",
                 font=("Arial", 9, "bold"), fg="darkgreen", bg="#e8f5e9").pack(anchor=tk.W, padx=5)
        tk.Label(unstable, text="• Strong mixing, enhances surface winds",
                 font=("Arial", 8), bg="#e8f5e9").pack(anchor=tk.W, padx=10)

        # Neutral
        neutral = tk.Frame(parent, bg="#fff9c4", relief=tk.SOLID, borderwidth=1)
        neutral.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(neutral, text="NEUTRAL: Transitional conditions",
                 font=("Arial", 9, "bold"), bg="#fff9c4").pack(anchor=tk.W, padx=5)
        tk.Label(neutral, text="• Takes maximum of mixed or model wind",
                 font=("Arial", 8), bg="#fff9c4").pack(anchor=tk.W, padx=10)

        # Stable
        stable = tk.Frame(parent, bg="#ffebee", relief=tk.SOLID, borderwidth=1)
        stable.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(stable, text="STABLE: Warm air over cold water",
                 font=("Arial", 9, "bold"), fg="red", bg="#ffebee").pack(anchor=tk.W, padx=5)
        tk.Label(stable, text="• Check for Low-Level Jet (LLJ)",
                 font=("Arial", 8), bg="#ffebee").pack(anchor=tk.W, padx=10)

        # Safety note
        tk.Label(parent, text="⚠ Tool NEVER reduces winds below model surface wind",
                 font=("Arial", 8), bg="#f0f0f0", fg="darkblue").pack(pady=(10, 5))

    def _run(self):
        selected = [m for m, v in self.model_vars.items() if v.get()]
        if not selected:
            self.status_label.config(text="ERROR: Select at least 1 model!", fg="red")
            return

        self.callback({
            "models": selected,
            "sst_source": self.sst_source.get(),
            "model_run": self.model_run.get(),
            "unstable_thresh": self.unstable_thresh.get(),
            "stable_thresh": self.stable_thresh.get(),
            "llj_thresh": self.llj_thresh.get(),
            "manual_adj": self.manual_adj.get() / 100.0,
            "apply_wind": self.apply_wind.get(),
            "apply_gust": self.apply_gust.get(),
            "create_925_wind": self.create_925_wind.get(),
            "create_stability": self.create_stability.get(),
            "create_adjustment": self.create_adjustment.get(),
            "create_wind_shear": self.create_wind_shear.get(),
            "create_llj": self.create_llj.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Marine wind adjustment procedure using shared utilities."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        if varDict is None:
            varDict = self._show_gui(editArea, timeRange)
            if varDict is None:
                self.statusBarMsg("Tool cancelled", "S")
                return

        self.statusBarMsg("Starting marine wind adjustment...", "R")

        models = varDict["models"]
        sst_source = varDict["sst_source"]
        model_run = varDict["model_run"]
        run_depth = 1 if model_run == "Current" else 2

        # Get time periods
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not gridinfos:
            gridinfos = self.getGridInfo(fcst, "SST", "SFC", timeRange)

        if not gridinfos:
            self.statusBarMsg("No grids found for time range", "S")
            return

        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing period {i+1}/{len(gridinfos)}", "R")

            # Get SST
            sst_c = self._get_sst(sst_source, grid_tr)
            if sst_c is None:
                continue

            # Get model data
            model_data = self._get_model_data(models, grid_tr, run_depth)
            if model_data is None:
                continue

            t925_c, wind_925, wind_sfc, wind_30m = model_data

            # Calculate instability
            instability = np.clip(t925_c - sst_c, -20.0, 20.0)

            # Determine mixing efficiency and gust factor
            mixing_eff, gust_factor = self._calc_mixing_params(instability)

            # Apply manual adjustment
            if abs(varDict["manual_adj"]) > 0.001:
                mixing_eff = np.clip(mixing_eff * (1.0 + varDict["manual_adj"]), 0.60, 0.98)

            # Calculate final winds using hybrid method
            final_wind, adj_applied, llj_indicator = self._hybrid_wind_calc(
                instability, wind_sfc, wind_925, wind_30m, mixing_eff,
                varDict["unstable_thresh"], varDict["stable_thresh"], varDict["llj_thresh"]
            )

            # Calculate gusts
            final_gust = self._calc_gusts(final_wind[0], gust_factor, instability, llj_indicator)

            # Create output grids
            self._create_output_grids(grid_tr, varDict, final_wind, final_gust,
                                      wind_925, instability, adj_applied, llj_indicator)

        self.statusBarMsg("Marine wind adjustment complete", "R")

    def _show_gui(self, editArea, timeRange) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = MixingEfficiencyGUI(root, callback)
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
        if np.nanmax(grid) > 50:  # Fahrenheit
            return thresholds.f_to_c(grid)
        elif np.nanmax(grid) > 200:  # Kelvin
            return thresholds.k_to_c(grid)
        return grid

    def _get_model_data(self, models: List[str], grid_tr, run_depth: int):
        """Get averaged model data for T925, wind_925, wind_sfc, wind_30m."""
        t925_sum, wind_925_sum, wind_sfc_sum, wind_30m_sum = None, None, None, None
        count = 0

        for alias in models:
            # T925 in Celsius
            t925 = grid_fetch.get_grid(self, alias, "t", "MB925", grid_tr, run_depth=run_depth, noDataError=0)
            if t925 is None:
                continue
            t925_c = thresholds.k_to_c(t925) if np.nanmax(t925) > 200 else t925

            # Surface wind (in m/s from model)
            wind_sfc = grid_fetch.get_vector_grid(self, alias, "wind", "SFC", grid_tr, run_depth=run_depth, noDataError=0)
            if wind_sfc is None:
                continue

            # 925mb wind
            wind_925 = grid_fetch.get_vector_grid(self, alias, "wind", "MB925", grid_tr, run_depth=run_depth, noDataError=0)
            if wind_925 is None:
                continue

            # 30m wind (fallback to 925mb)
            wind_30m = grid_fetch.get_vector_grid(self, alias, "wind", "FHAG30", grid_tr, run_depth=run_depth, noDataError=0)
            if wind_30m is None:
                wind_30m = wind_925

            # Accumulate
            if t925_sum is None:
                t925_sum = t925_c.copy()
                wind_925_sum = (wind_925[0].copy(), wind_925[1].copy())
                wind_sfc_sum = (wind_sfc[0].copy(), wind_sfc[1].copy())
                wind_30m_sum = (wind_30m[0].copy(), wind_30m[1].copy())
            else:
                t925_sum += t925_c
                wind_925_sum = (wind_925_sum[0] + wind_925[0], wind_925[1])
                wind_sfc_sum = (wind_sfc_sum[0] + wind_sfc[0], wind_sfc[1])
                wind_30m_sum = (wind_30m_sum[0] + wind_30m[0], wind_30m[1])

            count += 1

        if count == 0:
            return None

        # Average
        if count > 1:
            t925_avg = t925_sum / count
            wind_925_avg = (wind_925_sum[0] / count, wind_925_sum[1])
            wind_sfc_avg = (wind_sfc_sum[0] / count, wind_sfc_sum[1])
            wind_30m_avg = (wind_30m_sum[0] / count, wind_30m_sum[1])
        else:
            t925_avg = t925_sum
            wind_925_avg = wind_925_sum
            wind_sfc_avg = wind_sfc_sum
            wind_30m_avg = wind_30m_sum

        return t925_avg, wind_925_avg, wind_sfc_avg, wind_30m_avg

    def _calc_mixing_params(self, instability: np.ndarray):
        """Calculate mixing efficiency and gust factor from instability."""
        mixing_eff = np.zeros_like(instability)
        gust_factor = np.zeros_like(instability)

        for i, (thresh, eff, gust) in enumerate(MIXING_TABLE):
            if i == 0:
                mask = instability < thresh
            else:
                prev_thresh = MIXING_TABLE[i-1][0]
                mask = (instability >= prev_thresh) & (instability < thresh)
            mixing_eff[mask] = eff
            gust_factor[mask] = gust

        return mixing_eff, gust_factor

    def _hybrid_wind_calc(self, instability, wind_sfc, wind_925, wind_30m, mixing_eff,
                          unstable_thresh, stable_thresh, llj_thresh):
        """Apply hybrid wind calculation based on stability regime."""
        wind_sfc_mag, wind_sfc_dir = wind_sfc
        wind_925_mag, wind_925_dir = wind_925
        wind_30m_mag, wind_30m_dir = wind_30m

        # Initialize outputs
        final_mag = np.zeros_like(wind_sfc_mag)
        final_dir = wind_sfc_dir.copy()
        adj_applied = np.zeros_like(wind_sfc_mag)

        # Mixed wind
        mixed_wind = wind_30m_mag * mixing_eff

        # UNSTABLE: Apply strong mixing
        unstable_mask = instability < unstable_thresh
        final_mag[unstable_mask] = mixed_wind[unstable_mask]
        final_dir[unstable_mask] = wind_30m_dir[unstable_mask]
        adj_applied[unstable_mask] = mixed_wind[unstable_mask] - wind_sfc_mag[unstable_mask]

        # STABLE: Check for LLJ
        stable_mask = instability > stable_thresh
        llj_mask = stable_mask & (wind_925_mag > wind_sfc_mag * llj_thresh)
        llj_enhancement = (wind_925_mag - wind_sfc_mag) * 0.15

        final_mag[llj_mask] = wind_sfc_mag[llj_mask] + llj_enhancement[llj_mask]
        adj_applied[llj_mask] = llj_enhancement[llj_mask]

        # Stable but no LLJ: Keep model
        stable_no_llj = stable_mask & ~llj_mask
        final_mag[stable_no_llj] = wind_sfc_mag[stable_no_llj]

        # NEUTRAL: Take maximum
        neutral_mask = ~unstable_mask & ~stable_mask
        max_wind = np.maximum(wind_sfc_mag, mixed_wind)
        final_mag[neutral_mask] = max_wind[neutral_mask]
        adj_applied[neutral_mask] = max_wind[neutral_mask] - wind_sfc_mag[neutral_mask]

        # Safety: Never reduce below model
        below_model = final_mag < wind_sfc_mag
        final_mag[below_model] = wind_sfc_mag[below_model]
        adj_applied[below_model] = 0.0

        # LLJ indicator (0-10 scale)
        llj_ratio = wind_925_mag / np.maximum(wind_sfc_mag, 0.5)
        llj_indicator = np.clip((llj_ratio - 1.0) * 5.0, 0.0, 10.0)

        return (final_mag, final_dir), adj_applied, llj_indicator

    def _calc_gusts(self, final_mag, gust_factor, instability, llj_indicator):
        """Calculate wind gusts based on stability and LLJ."""
        gust = np.zeros_like(final_mag)

        unstable_mask = instability < -2
        llj_mask = llj_indicator > 3.0
        other_mask = ~unstable_mask & ~llj_mask

        gust[unstable_mask] = final_mag[unstable_mask] * gust_factor[unstable_mask]
        gust[llj_mask] = final_mag[llj_mask] * 1.35  # LLJ gusts
        gust[other_mask] = final_mag[other_mask] * 1.15  # Normal gusts

        return gust

    def _create_output_grids(self, grid_tr, params, final_wind, final_gust,
                              wind_925, instability, adj_applied, llj_indicator):
        """Create output grids based on user selections."""
        if params["apply_wind"]:
            self.createGrid("Fcst", "Wind", "VECTOR", final_wind, grid_tr)

        if params["apply_gust"]:
            self.createGrid("Fcst", "WindGust", "SCALAR", final_gust, grid_tr)

        if params["create_925_wind"]:
            self.createGrid("Fcst", "Wind_925mb", "VECTOR", wind_925, grid_tr)

        if params["create_stability"]:
            regime = np.where(instability < -15, 7,
                     np.where(instability < -10, 6,
                     np.where(instability < -5, 5,
                     np.where(instability < 0, 4,
                     np.where(instability < 3, 3,
                     np.where(instability < 5, 2, 1))))))
            self.createGrid("Fcst", "Stability_Regime", "SCALAR", regime, grid_tr,
                           minAllowedValue=1.0, maxAllowedValue=7.0, precision=0)

        if params["create_adjustment"]:
            adj_kt = thresholds.to_knots(adj_applied)
            self.createGrid("Fcst", "Adjustment_Applied", "SCALAR", adj_kt, grid_tr)

        if params["create_wind_shear"]:
            wind_925_mag = wind_925[0]
            shear = thresholds.to_knots(wind_925_mag - final_wind[0])
            self.createGrid("Fcst", "WindShear_925_Sfc", "SCALAR", shear, grid_tr)

        if params["create_llj"]:
            self.createGrid("Fcst", "LLJ_Indicator", "SCALAR", llj_indicator, grid_tr,
                           minAllowedValue=0.0, maxAllowedValue=10.0, precision=1)


__all__ = ["Procedure"]

