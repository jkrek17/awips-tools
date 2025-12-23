"""
Model Guidance Assistant - Comprehensive model analysis tool.

Combines model consistency and inter-model agreement analysis
to help forecasters make informed model selection decisions.

Modular rewrite using shared utilities for model access.
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
WeatherElementEdited = "variableElement"
HideTool = 0
ScreenList = ["Wind"]
VariableList = []

# Model definitions with run counts
MODEL_CATEGORIES = {
    "Global Models": [
        ("ECMWF", "European Centre", 2),
        ("GFS", "Global Forecast System", 2),
        ("CMC", "Canadian Global", 2),
        ("UKMET", "UK Met Office", 2),
    ],
    "Ensemble Models": [
        ("GEFS", "GFS Ensemble Mean", 2),
        ("ECENS", "ECMWF Ensemble Mean", 2),
        ("NationalBlend", "National Blend", 2),
        ("NationalBlendOC", "National Blend Oceanic", 2),
    ],
}


class ModelGuidanceGUI:
    """GUI for model guidance analysis."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Model Guidance Assistant")
        self.master.geometry("700x800")

        self.model_vars: Dict[str, tk.StringVar] = {}
        self.model_info: Dict[str, Dict] = {}

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Model Guidance Assistant",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Comprehensive Wind Speed Model Analysis",
                 font=("Arial", 12), fg="navy").pack(pady=(0, 15))

        # Model selection
        model_frame = tk.LabelFrame(main, text="Select Models for Analysis", padx=15, pady=10)
        model_frame.pack(fill=tk.X, pady=(0, 15))

        self._build_presets(model_frame)
        self._build_model_list(model_frame)

        self.status_label = tk.Label(model_frame, text="No Models Selected",
                                     font=("Arial", 11, "bold"), fg="red")
        self.status_label.pack(pady=(10, 0))

        # Analysis options
        self._build_options(main)

        # What this tool helps decide
        self._build_info(main)

        # Buttons
        self._build_buttons(main)

        self._update_selection()

    def _build_presets(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame, text="Quick Presets:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        tk.Button(frame, text="All Global", command=self._select_global,
                  bg="lightgreen", width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Ensemble", command=self._select_ensemble,
                  bg="lightblue", width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Clear All", command=self._clear_all,
                  bg="lightgray", width=10).pack(side=tk.LEFT, padx=5)

    def _build_model_list(self, parent):
        for category, models in MODEL_CATEGORIES.items():
            tk.Label(parent, text=category, font=("Arial", 10, "bold"),
                     fg="darkblue").pack(anchor=tk.W, pady=(10, 5))

            for alias, display_name, run_count in models:
                var = tk.StringVar(value="No")
                var.trace("w", lambda *args: self._update_selection())
                self.model_vars[alias] = var
                self.model_info[alias] = {"displayName": display_name, "runCount": run_count}

                tk.Checkbutton(parent, text=f"{display_name} ({alias})",
                               variable=var, onvalue="Yes", offvalue="No").pack(anchor=tk.W, padx=20)

    def _build_options(self, parent):
        frame = tk.LabelFrame(parent, text="Analysis Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 15))

        # Threshold
        thresh_frame = tk.Frame(frame)
        thresh_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(thresh_frame, text="Wind Speed Threshold:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.wind_threshold = tk.IntVar(value=20)
        tk.Scale(thresh_frame, from_=5, to=70, orient=tk.HORIZONTAL,
                 variable=self.wind_threshold, width=12).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Analysis types
        self.run_consistency = tk.StringVar(value="Yes")
        self.run_agreement = tk.StringVar(value="Yes")
        self.create_guidance = tk.StringVar(value="Yes")

        tk.Checkbutton(frame, text="Model Consistency Analysis",
                       variable=self.run_consistency, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Checkbutton(frame, text="Model Agreement Analysis",
                       variable=self.run_agreement, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Checkbutton(frame, text="Create Guidance Grid",
                       variable=self.create_guidance, onvalue="Yes", offvalue="No",
                       font=("Arial", 10, "bold")).pack(anchor=tk.W)

    def _build_info(self, parent):
        frame = tk.LabelFrame(parent, text="What This Tool Helps You Decide", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 15))

        info_items = [
            "Which models are being consistent vs erratic?",
            "Where do models agree vs disagree geographically?",
            "What areas need more forecaster attention?",
            "Which model guidance is most reliable right now?",
        ]
        for item in info_items:
            tk.Label(frame, text=f"✓ {item}", font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(frame, text="Run Analysis", command=self._run,
                  bg="lightblue", font=("Arial", 11, "bold"), width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _update_selection(self):
        count = sum(1 for v in self.model_vars.values() if v.get() == "Yes")
        if count == 0:
            self.status_label.config(text="No Models Selected", fg="red")
        elif count == 1:
            self.status_label.config(text="1 Model Selected", fg="orange")
        else:
            self.status_label.config(text=f"{count} Models Selected", fg="green")

    def _select_global(self):
        self._clear_all()
        for alias in ["ECMWF", "GFS", "CMC", "UKMET"]:
            if alias in self.model_vars:
                self.model_vars[alias].set("Yes")

    def _select_ensemble(self):
        self._clear_all()
        for alias in ["GEFS", "ECENS", "NationalBlend", "NationalBlendOC"]:
            if alias in self.model_vars:
                self.model_vars[alias].set("Yes")

    def _clear_all(self):
        for v in self.model_vars.values():
            v.set("No")

    def _run(self):
        selected = {alias: self.model_info[alias] for alias, v in self.model_vars.items() if v.get() == "Yes"}
        if not selected:
            self.status_label.config(text="ERROR: Select at least 1 model!", fg="red")
            return

        self.callback({
            "selected_models": selected,
            "run_consistency": self.run_consistency.get(),
            "run_agreement": self.run_agreement.get(),
            "create_guidance": self.create_guidance.get(),
            "wind_threshold": self.wind_threshold.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Model guidance analysis procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.analysis_stats: Dict = {}

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                return

        self.analysis_stats = {
            "modelsAnalyzed": [],
            "timePeriodsProcessed": 0,
            "consistencyStats": {},
            "agreementStats": {},
            "overallStats": {},
        }

        selected_models = varDict["selected_models"]
        wind_threshold = varDict["wind_threshold"]

        if not selected_models:
            return

        # Validate model coverage
        valid_models = self._validate_coverage(selected_models, timeRange)
        if not valid_models:
            self.statusBarMsg("No models have data for selected time range", "S")
            return

        self.analysis_stats["modelsAnalyzed"] = list(valid_models.keys())

        # Get forecast grid info
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
        self.analysis_stats["timePeriodsProcessed"] = len(gridinfos)

        # Process each time period
        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing period {i+1}/{len(gridinfos)}", "R")

            consistency_grids = []
            current_wind_speeds = []
            model_names = []

            # Consistency analysis
            if varDict["run_consistency"] == "Yes":
                for alias, info in valid_models.items():
                    run_count = info["runCount"]
                    wind_grids = self._get_model_wind_runs(alias, grid_tr, run_count)

                    if len(wind_grids) >= 2:
                        consistency = self._create_consistency_grid(
                            wind_grids, alias, grid_tr, wind_threshold
                        )
                        if consistency is not None:
                            consistency_grids.append(consistency)

            # Agreement analysis
            if varDict["run_agreement"] == "Yes" and len(valid_models) >= 2:
                for alias in valid_models.keys():
                    wind_speed = self._get_current_wind_speed(alias, grid_tr)
                    if wind_speed is not None:
                        current_wind_speeds.append(wind_speed)
                        model_names.append(alias)

                if len(current_wind_speeds) >= 2:
                    self._create_agreement_grid(
                        current_wind_speeds, model_names, grid_tr, wind_threshold
                    )

            # Guidance grid
            if varDict["create_guidance"] == "Yes":
                self._create_guidance_grid(consistency_grids, grid_tr)

        self.statusBarMsg("Analysis complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = ModelGuidanceGUI(root, callback)
        root.mainloop()
        return result[0]

    def _validate_coverage(self, selected_models: Dict, timeRange) -> Dict:
        """Check which models have data."""
        valid = {}
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not gridinfos:
            return valid

        test_tr = gridinfos[0].gridTime()

        for alias, info in selected_models.items():
            wind = self._get_current_wind_speed(alias, test_tr)
            if wind is not None:
                valid[alias] = info

        return valid

    def _get_model_wind_runs(self, alias: str, grid_tr, run_count: int) -> List[np.ndarray]:
        """Get wind speed grids from multiple runs."""
        grids = []
        for run_offset in range(run_count):
            wind = grid_fetch.get_vector_grid(
                self, alias, "Wind", "SFC", grid_tr,
                run_depth=run_offset+1, noDataError=0
            )
            if wind is not None:
                grids.append(wind[0])  # Magnitude only
        return grids

    def _get_current_wind_speed(self, alias: str, grid_tr) -> Optional[np.ndarray]:
        """Get current run wind speed."""
        wind = grid_fetch.get_vector_grid(
            self, alias, "Wind", "SFC", grid_tr,
            run_depth=1, noDataError=0
        )
        if wind is not None:
            return wind[0]  # Magnitude only
        return None

    def _create_consistency_grid(self, wind_grids: List[np.ndarray], alias: str,
                                  grid_tr, wind_threshold: int) -> Optional[np.ndarray]:
        """Create consistency grid for a single model across runs."""
        if len(wind_grids) < 2:
            return None

        model_array = np.array(wind_grids)
        std_dev = np.std(model_array, axis=0)
        mean_wind = np.mean(model_array, axis=0)

        # Mask for significant winds
        significant_mask = mean_wind >= wind_threshold

        if not np.any(significant_mask):
            return None

        # Calculate relative std dev
        rel_std = np.where(significant_mask, std_dev / (mean_wind + 0.1), 0)

        # Normalize to consistency score (0-100)
        max_rel_std = np.max(rel_std[significant_mask]) if np.any(significant_mask) else 1
        if max_rel_std > 0:
            consistency = 100.0 * (1.0 - (rel_std / max_rel_std))
            consistency = np.clip(consistency, 0, 100)
            consistency = np.where(significant_mask, consistency, 50)  # Light winds = 50%
        else:
            consistency = np.full_like(mean_wind, 50.0)

        # Store stats
        self.analysis_stats["consistencyStats"][alias] = {
            "avgConsistency": float(np.mean(consistency[significant_mask])),
            "minConsistency": float(np.min(consistency[significant_mask])),
            "maxConsistency": float(np.max(consistency[significant_mask])),
            "significantPercent": float(np.sum(significant_mask) / significant_mask.size * 100),
            "runsUsed": len(wind_grids),
        }

        self.createGrid("Fcst", f"WindSpeedConsistency{alias}", "SCALAR",
                        consistency, grid_tr, minAllowedValue=0, maxAllowedValue=100)
        return consistency

    def _create_agreement_grid(self, wind_speeds: List[np.ndarray], model_names: List[str],
                                grid_tr, wind_threshold: int):
        """Create agreement grid from current model runs."""
        if len(wind_speeds) < 2:
            return

        model_array = np.array(wind_speeds)
        std_dev = np.std(model_array, axis=0)
        mean_wind = np.mean(model_array, axis=0)

        significant_mask = mean_wind >= wind_threshold

        if not np.any(significant_mask):
            return

        rel_std = np.where(significant_mask, std_dev / (mean_wind + 0.1), 0)
        max_rel_std = np.max(rel_std[significant_mask]) if np.any(significant_mask) else 1

        if max_rel_std > 0:
            agreement = 100.0 * (1.0 - (rel_std / max_rel_std))
            agreement = np.clip(agreement, 0, 100)
            agreement = np.where(significant_mask, agreement, 50)
        else:
            agreement = np.full_like(mean_wind, 50.0)

        self.analysis_stats["agreementStats"] = {
            "avgAgreement": float(np.mean(agreement[significant_mask])),
            "minAgreement": float(np.min(agreement[significant_mask])),
            "maxAgreement": float(np.max(agreement[significant_mask])),
            "significantPercent": float(np.sum(significant_mask) / significant_mask.size * 100),
            "modelsUsed": len(model_names),
        }

        self.createGrid("Fcst", "WindSpeedAgreement", "SCALAR",
                        agreement, grid_tr, minAllowedValue=0, maxAllowedValue=100)

    def _create_guidance_grid(self, consistency_grids: List[np.ndarray], grid_tr):
        """Create overall guidance grid."""
        if not consistency_grids:
            return

        # Average consistency across models
        avg_consistency = np.mean(np.array(consistency_grids), axis=0)

        # Try to get agreement grid
        try:
            agreement = self.getGrids("Fcst", "WindSpeedAgreement", "SFC", grid_tr, noDataError=0)
            if agreement is not None:
                guidance = (avg_consistency + agreement) / 2.0
            else:
                guidance = avg_consistency
        except Exception:
            guidance = avg_consistency

        guidance = np.clip(guidance, 0, 100)

        significant_mask = guidance > 50
        if np.any(significant_mask):
            self.analysis_stats["overallStats"] = {
                "avgGuidance": float(np.mean(guidance[significant_mask])),
                "minGuidance": float(np.min(guidance[significant_mask])),
                "maxGuidance": float(np.max(guidance[significant_mask])),
            }

        self.createGrid("Fcst", "WindSpeedGuidance", "SCALAR",
                        guidance, grid_tr, minAllowedValue=0, maxAllowedValue=100)


__all__ = ["Procedure"]

