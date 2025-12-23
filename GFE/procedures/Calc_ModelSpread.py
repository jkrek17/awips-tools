"""
Model Spread Analysis Tool - Enhanced marine wind model analysis.

Creates wind vector consensus, analyzes model differences,
and provides model usefulness rankings.

Modular rewrite using shared utilities for model access.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript

import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Edit"]
WeatherElementEdited = "variableElement"
HideTool = 0
ScreenList = ["Wind"]
VariableList = []

# Model definitions
ANALYSIS_MODELS = [
    ("GFS", "Global Forecast System", 4),
    ("ECMWF", "European Centre", 2),
    ("CMC", "Canadian Global", 4),
    ("UKMET", "UK Met Office", 4),
    ("GEFS", "GFS Ensemble Mean", 4),
    ("ECENS", "ECMWF Ensemble Mean", 2),
]


class ModelSpreadGUI:
    """GUI for model spread analysis."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Enhanced Marine Wind Model Analysis")
        self.master.geometry("650x850")

        self.model_vars: Dict[str, tk.StringVar] = {}
        self.model_info: Dict[str, Dict] = {}

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Enhanced Marine Wind Model Analysis",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Wind Vector Consensus & Model Rankings",
                 font=("Arial", 12), fg="navy").pack(pady=(0, 15))

        # Model selection
        self._build_model_frame(main)

        # Analysis options
        self._build_options(main)

        # Results info
        self._build_results_info(main)

        # Buttons
        self._build_buttons(main)

        self._update_selection()

    def _build_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Select Models for Analysis", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 15))

        for alias, display_name, run_count in ANALYSIS_MODELS:
            var = tk.StringVar(value="No")
            var.trace("w", lambda *args: self._update_selection())
            self.model_vars[alias] = var
            self.model_info[alias] = {"displayName": display_name, "runCount": run_count}

            tk.Checkbutton(frame, text=f"{display_name} ({alias})",
                           variable=var, onvalue="Yes", offvalue="No",
                           font=("Arial", 10)).pack(anchor=tk.W, pady=2)

        self.status_label = tk.Label(frame, text="No Models Selected",
                                     font=("Arial", 11, "bold"), fg="red")
        self.status_label.pack(pady=(10, 0))

    def _build_options(self, parent):
        frame = tk.LabelFrame(parent, text="Analysis Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 15))

        # Wind threshold
        thresh_frame = tk.Frame(frame)
        thresh_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(thresh_frame, text="Wind Speed Threshold:").pack(side=tk.LEFT)
        self.wind_threshold = tk.IntVar(value=0)
        tk.Scale(thresh_frame, from_=0, to=70, orient=tk.HORIZONTAL,
                 variable=self.wind_threshold).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Analysis types
        self.create_consensus = tk.StringVar(value="Yes")
        self.run_variability = tk.StringVar(value="Yes")
        self.run_spread = tk.StringVar(value="Yes")
        self.run_bias = tk.StringVar(value="Yes")
        self.create_uncertainty = tk.StringVar(value="Yes")
        self.calculate_usefulness = tk.StringVar(value="Yes")

        tk.Checkbutton(frame, text="Create Wind Vector Consensus (with Barbs)",
                       variable=self.create_consensus, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Checkbutton(frame, text="Model Run-to-Run Variability",
                       variable=self.run_variability, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Checkbutton(frame, text="Current Model Spread Analysis",
                       variable=self.run_spread, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Checkbutton(frame, text="Model Bias Analysis (vs Consensus)",
                       variable=self.run_bias, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Checkbutton(frame, text="Combined Uncertainty Grids",
                       variable=self.create_uncertainty, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Checkbutton(frame, text="Model Usefulness Rankings",
                       variable=self.calculate_usefulness, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

    def _build_results_info(self, parent):
        frame = tk.LabelFrame(parent, text="Enhanced Analysis Results", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 15))

        info = [
            "🌬️ WindConsensus grid with wind barbs (starting forecast)",
            "🏆 Model usefulness rankings with recommendations",
            "📊 Bias analysis relative to consensus",
            "📈 Model consistency and uncertainty analysis",
        ]
        for item in info:
            tk.Label(frame, text=item, font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(frame, text="Run Enhanced Analysis", command=self._run,
                  bg="lightblue", font=("Arial", 11, "bold"), width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _update_selection(self):
        count = sum(1 for v in self.model_vars.values() if v.get() == "Yes")
        if count == 0:
            self.status_label.config(text="No Models Selected", fg="red")
        elif count == 1:
            self.status_label.config(text="1 Model Selected", fg="orange")
        else:
            self.status_label.config(text=f"{count} Models Selected", fg="green")

    def _run(self):
        selected = {alias: self.model_info[alias] for alias, v in self.model_vars.items() if v.get() == "Yes"}
        if not selected:
            self.status_label.config(text="ERROR: Select at least 1 model!", fg="red")
            return

        self.callback({
            "selected_models": selected,
            "create_consensus": self.create_consensus.get(),
            "run_variability": self.run_variability.get(),
            "run_spread": self.run_spread.get(),
            "run_bias": self.run_bias.get(),
            "create_uncertainty": self.create_uncertainty.get(),
            "calculate_usefulness": self.calculate_usefulness.get(),
            "wind_threshold": self.wind_threshold.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Model spread analysis procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.analysis_stats: Dict = {}
        self.edit_area_mask = None

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        self.edit_area = editArea
        self.edit_area_mask = self._get_edit_area_mask(editArea)

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                return

        self.analysis_stats = {
            "modelsAnalyzed": [],
            "timePeriodsProcessed": 0,
            "variabilityStats": {},
            "spreadStats": {},
            "biasStats": {},
            "consensusStats": {},
            "modelUsefulness": {},
        }

        selected_models = varDict["selected_models"]
        wind_threshold = varDict["wind_threshold"]

        if not selected_models:
            return

        # Validate coverage
        valid_models = self._validate_coverage(selected_models, timeRange)
        if not valid_models:
            self.statusBarMsg("No models have data", "S")
            return

        self.analysis_stats["modelsAnalyzed"] = list(valid_models.keys())

        # Get forecast info
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
        self.analysis_stats["timePeriodsProcessed"] = len(gridinfos)

        # Process each time period
        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{len(gridinfos)}", "R")

            variability_speed_grids = []
            variability_dir_grids = []
            current_speeds = []
            current_dirs = []
            model_names = []

            # 1. Variability analysis
            if varDict["run_variability"] == "Yes":
                for alias, info in valid_models.items():
                    run_count = info["runCount"]
                    speed_grids, dir_grids = self._get_wind_runs(alias, grid_tr, run_count)

                    if len(speed_grids) >= 2:
                        speed_var, dir_var = self._create_variability_grids(
                            speed_grids, dir_grids, alias, grid_tr, wind_threshold
                        )
                        if speed_var is not None:
                            variability_speed_grids.append(speed_var)
                            variability_dir_grids.append(dir_var)

            # 2. Get current model data
            for alias in valid_models.keys():
                speed, direction = self._get_current_wind(alias, grid_tr)
                if speed is not None:
                    current_speeds.append(speed)
                    current_dirs.append(direction)
                    model_names.append(alias)

            # 3. Create consensus grid first
            consensus_speed = None
            consensus_dir = None
            if varDict["create_consensus"] == "Yes" and len(current_speeds) >= 2:
                consensus_speed, consensus_dir = self._create_consensus_grids(
                    current_speeds, current_dirs, model_names, grid_tr, wind_threshold
                )

            # 4. Spread analysis
            spread_speed = spread_dir = None
            if varDict["run_spread"] == "Yes" and len(current_speeds) >= 2:
                spread_speed, spread_dir = self._create_spread_grids(
                    current_speeds, current_dirs, model_names, grid_tr, wind_threshold
                )

            # 5. Bias analysis
            if varDict["run_bias"] == "Yes" and consensus_speed is not None:
                self._create_bias_grids(
                    current_speeds, model_names, grid_tr, wind_threshold, consensus_speed
                )

            # 6. Uncertainty grids
            if varDict["create_uncertainty"] == "Yes":
                self._create_uncertainty_grids(
                    variability_speed_grids, variability_dir_grids,
                    spread_speed, spread_dir, grid_tr
                )

        # 7. Model usefulness rankings
        if varDict["calculate_usefulness"] == "Yes":
            self._calculate_usefulness()

        self.statusBarMsg("Analysis complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = ModelSpreadGUI(root, callback)
        root.mainloop()
        return result[0]

    def _get_edit_area_mask(self, editArea):
        """Get edit area mask or whole domain."""
        try:
            if editArea:
                mask = self.encodeEditArea(editArea)
                if np.sum(mask) > 0:
                    return mask
        except Exception:
            pass

        # Use whole domain
        ref = self.newGrid(0.0)
        return np.ones(ref.shape, dtype=bool)

    def _validate_coverage(self, selected_models: Dict, timeRange) -> Dict:
        """Check which models have data."""
        valid = {}
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not gridinfos:
            return valid

        test_tr = gridinfos[0].gridTime()

        for alias, info in selected_models.items():
            speed, _ = self._get_current_wind(alias, test_tr)
            if speed is not None:
                valid[alias] = info

        return valid

    def _get_wind_runs(self, alias: str, grid_tr, run_count: int) -> Tuple[List, List]:
        """Get wind data from multiple runs."""
        speeds, dirs = [], []
        for run_offset in range(run_count):
            wind = grid_fetch.get_vector_grid(
                self, alias, "Wind", "SFC", grid_tr,
                run_depth=run_offset+1, noDataError=0
            )
            if wind is not None:
                speeds.append(wind[0])
                dirs.append(wind[1])
        return speeds, dirs

    def _get_current_wind(self, alias: str, grid_tr) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Get current run wind data."""
        wind = grid_fetch.get_vector_grid(
            self, alias, "Wind", "SFC", grid_tr,
            run_depth=1, noDataError=0
        )
        if wind is not None:
            return wind[0], wind[1]
        return None, None

    def _create_consensus_grids(self, speeds: List, dirs: List, model_names: List,
                                 grid_tr, wind_threshold: int):
        """Create consensus wind vector grid."""
        if len(speeds) < 2:
            return None, None

        speed_array = np.array(speeds)
        dir_array = np.array(dirs)

        # Speed: simple mean
        consensus_speed = np.mean(speed_array, axis=0)

        # Direction: circular mean
        dir_rad = np.radians(dir_array)
        mean_cos = np.mean(np.cos(dir_rad), axis=0)
        mean_sin = np.mean(np.sin(dir_rad), axis=0)
        consensus_dir = np.degrees(np.arctan2(mean_sin, mean_cos))
        consensus_dir = np.where(consensus_dir < 0, consensus_dir + 360, consensus_dir)

        # Apply mask
        sig_mask = (consensus_speed >= wind_threshold) & self.edit_area_mask
        consensus_speed_masked = np.where(sig_mask, consensus_speed, 0.0)
        consensus_dir_masked = np.where(sig_mask, consensus_dir, 0.0)

        # Store stats
        self.analysis_stats["consensusStats"] = {
            "modelsUsed": model_names,
            "speed": {
                "min": float(np.min(consensus_speed_masked[sig_mask])) if np.any(sig_mask) else 0,
                "max": float(np.max(consensus_speed_masked[sig_mask])) if np.any(sig_mask) else 0,
                "mean": float(np.mean(consensus_speed_masked[sig_mask])) if np.any(sig_mask) else 0,
            },
        }

        # Create vector grid
        consensus_vector = (consensus_speed_masked, consensus_dir_masked)
        self.createGrid("Fcst", "WindConsensus", "VECTOR", consensus_vector, grid_tr,
                        minAllowedValue=0.0, maxAllowedValue=125.0)

        return consensus_speed_masked, consensus_dir_masked

    def _create_variability_grids(self, speed_grids: List, dir_grids: List,
                                   alias: str, grid_tr, wind_threshold: int):
        """Create variability grids for a model."""
        if len(speed_grids) < 2:
            return None, None

        speed_array = np.array(speed_grids)
        dir_array = np.array(dir_grids)

        mean_speed = np.mean(speed_array, axis=0)
        sig_mask = (mean_speed >= wind_threshold) & self.edit_area_mask

        if not np.any(sig_mask):
            return None, None

        # Mean absolute deviation for speed
        speed_mad = np.mean(np.abs(speed_array - mean_speed), axis=0)
        speed_mad = np.clip(speed_mad, 0, 20)

        # Direction variability (circular)
        dir_mean = np.mean(dir_array, axis=0)
        dir_diffs = np.minimum(np.abs(dir_array - dir_mean), 360 - np.abs(dir_array - dir_mean))
        dir_mad = np.mean(dir_diffs, axis=0)
        dir_mad = np.clip(dir_mad, 0, 180)

        speed_var = np.where(sig_mask, speed_mad, 0)
        dir_var = np.where(sig_mask, dir_mad, 0)

        # Store stats
        if "variabilityStats" not in self.analysis_stats:
            self.analysis_stats["variabilityStats"] = {}
        self.analysis_stats["variabilityStats"][alias] = {
            "speed": {"mean": float(np.mean(speed_var[sig_mask])) if np.any(sig_mask) else 0},
        }

        self.createGrid("Fcst", f"WindSpeedVariability{alias}", "SCALAR",
                        speed_var, grid_tr, minAllowedValue=0, maxAllowedValue=20)
        self.createGrid("Fcst", f"WindDirVariability{alias}", "SCALAR",
                        dir_var, grid_tr, minAllowedValue=0, maxAllowedValue=180)

        return speed_var, dir_var

    def _create_spread_grids(self, speeds: List, dirs: List, model_names: List,
                              grid_tr, wind_threshold: int):
        """Create model spread grids."""
        if len(speeds) < 2:
            return None, None

        speed_array = np.array(speeds)
        dir_array = np.array(dirs)

        mean_speed = np.mean(speed_array, axis=0)
        sig_mask = (mean_speed >= wind_threshold) & self.edit_area_mask

        if not np.any(sig_mask):
            return None, None

        # Speed spread (range)
        speed_range = np.max(speed_array, axis=0) - np.min(speed_array, axis=0)
        speed_range = np.clip(speed_range, 0, 20)

        # Direction spread (circular variance)
        dir_rad = np.radians(dir_array)
        mean_cos = np.mean(np.cos(dir_rad), axis=0)
        mean_sin = np.mean(np.sin(dir_rad), axis=0)
        R = np.sqrt(mean_cos**2 + mean_sin**2)
        circ_var = 1 - R
        dir_spread = np.degrees(np.arcsin(np.minimum(np.sqrt(2 * circ_var), 1.0))) * 2
        dir_spread = np.clip(dir_spread, 0, 180)

        speed_spread = np.where(sig_mask, speed_range, 0)
        dir_spread = np.where(sig_mask, dir_spread, 0)

        # Store stats
        self.analysis_stats["spreadStats"] = {
            "speed": {
                "mean": float(np.mean(speed_spread[sig_mask])) if np.any(sig_mask) else 0,
                "max": float(np.max(speed_spread[sig_mask])) if np.any(sig_mask) else 0,
            },
        }

        self.createGrid("Fcst", "WindSpeedSpread", "SCALAR",
                        speed_spread, grid_tr, minAllowedValue=0, maxAllowedValue=20)
        self.createGrid("Fcst", "WindDirSpread", "SCALAR",
                        dir_spread, grid_tr, minAllowedValue=0, maxAllowedValue=180)

        return speed_spread, dir_spread

    def _create_bias_grids(self, speeds: List, model_names: List, grid_tr,
                            wind_threshold: int, consensus_speed: np.ndarray):
        """Create bias grids relative to consensus."""
        sig_mask = (consensus_speed >= wind_threshold) & self.edit_area_mask

        if not np.any(sig_mask):
            return

        for i, alias in enumerate(model_names):
            bias = speeds[i] - consensus_speed
            bias = np.where(sig_mask, bias, 0)
            bias = np.clip(bias, -20, 20)

            # Store stats
            if "biasStats" not in self.analysis_stats:
                self.analysis_stats["biasStats"] = {}
            self.analysis_stats["biasStats"][alias] = {
                "speed": {"mean": float(np.mean(bias[sig_mask])) if np.any(sig_mask) else 0},
            }

            self.createGrid("Fcst", f"WindSpeedBias{alias}", "SCALAR",
                            bias, grid_tr, minAllowedValue=-20, maxAllowedValue=20)

    def _create_uncertainty_grids(self, var_speeds: List, var_dirs: List,
                                   spread_speed, spread_dir, grid_tr):
        """Create combined uncertainty grids."""
        speed_uncertainty = self.newGrid(0.0)
        dir_uncertainty = self.newGrid(0.0)

        # Average variability
        if var_speeds:
            valid_vars = [g for g in var_speeds if g is not None]
            if valid_vars:
                avg_var_speed = np.mean(np.array(valid_vars), axis=0)
            else:
                avg_var_speed = self.newGrid(0.0)
        else:
            avg_var_speed = self.newGrid(0.0)

        if var_dirs:
            valid_vars = [g for g in var_dirs if g is not None]
            if valid_vars:
                avg_var_dir = np.mean(np.array(valid_vars), axis=0)
            else:
                avg_var_dir = self.newGrid(0.0)
        else:
            avg_var_dir = self.newGrid(0.0)

        # Combine with spread
        if spread_speed is not None:
            speed_uncertainty = (avg_var_speed + spread_speed) / 2.0
        else:
            speed_uncertainty = avg_var_speed

        if spread_dir is not None:
            dir_uncertainty = (avg_var_dir + spread_dir) / 2.0
        else:
            dir_uncertainty = avg_var_dir

        speed_uncertainty = np.clip(speed_uncertainty, 0, 20)
        dir_uncertainty = np.clip(dir_uncertainty, 0, 180)

        self.createGrid("Fcst", "WindSpeedUncertainty", "SCALAR",
                        speed_uncertainty, grid_tr, minAllowedValue=0, maxAllowedValue=20)
        self.createGrid("Fcst", "WindDirUncertainty", "SCALAR",
                        dir_uncertainty, grid_tr, minAllowedValue=0, maxAllowedValue=180)

    def _calculate_usefulness(self):
        """Calculate model usefulness rankings."""
        model_scores = {}
        variability_stats = self.analysis_stats.get("variabilityStats", {})
        bias_stats = self.analysis_stats.get("biasStats", {})

        for alias in self.analysis_stats.get("modelsAnalyzed", []):
            score = 100
            reasons = []

            # Consistency score (40%)
            if alias in variability_stats:
                avg_var = variability_stats[alias].get("speed", {}).get("mean", 0)
                if avg_var < 1.0:
                    consistency_score = 40
                    reasons.append("very consistent")
                elif avg_var < 2.0:
                    consistency_score = 32
                elif avg_var < 3.0:
                    consistency_score = 24
                else:
                    consistency_score = 16
            else:
                consistency_score = 20

            # Bias score (30%)
            if alias in bias_stats:
                avg_bias = abs(bias_stats[alias].get("speed", {}).get("mean", 0))
                if avg_bias < 0.5:
                    bias_score = 30
                elif avg_bias < 1.0:
                    bias_score = 25
                elif avg_bias < 2.0:
                    bias_score = 20
                else:
                    bias_score = 10
            else:
                bias_score = 15

            # Availability + quality (30%)
            avail_score = 20
            quality_score = 10

            total = consistency_score + bias_score + avail_score + quality_score

            if total >= 85:
                category = "EXCELLENT"
            elif total >= 70:
                category = "GOOD"
            elif total >= 55:
                category = "FAIR"
            else:
                category = "POOR"

            model_scores[alias] = {
                "totalScore": total,
                "category": category,
                "reasons": reasons,
            }

        self.analysis_stats["modelUsefulness"] = model_scores


__all__ = ["Procedure"]

