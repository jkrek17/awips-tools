"""
Analyze_Scenarios - Ensemble Scenario Analysis with Hazard Suggestions

Analyzes ensemble spread to create:
- Low/Most Likely/High wind scenarios
- Low/Most Likely/High wave scenarios  
- Suggested hazard grids based on scenario analysis
- Headline recommendations based on probability thresholds

Use when model spread is high to communicate uncertainty effectively.

Uses: grid_ops, stability_blend utilities
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript

from utilities import grid_ops
from utilities import stability_blend
import grid_fetch
import model_aliases

MenuItems = ["Populate"]
VariableList = []

# =============================================================================
# Configuration
# =============================================================================

WIND_MODELS = ["GFS", "ECMWF", "NAM", "CMC", "UKMET", "GEFS"]
WAVE_MODELS = ["GFSWAVE", "ECMWF", "CMC"]

# Hazard thresholds
WIND_HAZARDS = {
    "SCA": {"threshold": 21, "headline": "Small Craft Advisory"},
    "Gale": {"threshold": 34, "headline": "Gale Warning"},
    "Storm": {"threshold": 48, "headline": "Storm Warning"},
    "Hurricane": {"threshold": 64, "headline": "Hurricane Force Wind Warning"},
}

WAVE_HAZARDS = {
    "SCA": {"threshold": 5, "headline": "Small Craft Advisory"},
    "Rough": {"threshold": 8, "headline": "Hazardous Seas"},
    "VeryRough": {"threshold": 13, "headline": "Very Rough Seas"},
    "High": {"threshold": 20, "headline": "High Seas"},
}

# Probability thresholds for headline suggestions
PROB_LIKELY = 60      # Likely to occur
PROB_POSSIBLE = 30    # Possible
PROB_LOW = 10         # Low chance


# =============================================================================
# GUI
# =============================================================================

class AnalyzeScenariosGUI:
    """GUI for scenario analysis tool."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Scenario Analysis & Hazard Assessment")
        self.master.geometry("750x900")
        self.master.resizable(True, True)

        self._build_ui()

    def _build_ui(self):
        notebook = ttk.Notebook(self.master)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Wind Scenarios
        self.wind_frame = ttk.Frame(notebook)
        notebook.add(self.wind_frame, text="Wind Scenarios")
        self._build_wind_tab()

        # Tab 2: Wave Scenarios
        self.wave_frame = ttk.Frame(notebook)
        notebook.add(self.wave_frame, text="Wave Scenarios")
        self._build_wave_tab()

        # Tab 3: Hazard Suggestions
        self.hazard_frame = ttk.Frame(notebook)
        notebook.add(self.hazard_frame, text="Hazard Suggestions")
        self._build_hazard_tab()

        # Bottom buttons
        btn_frame = tk.Frame(self.master)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(btn_frame, text="Analyze Scenarios", command=self._run,
                  bg="lightblue", font=("Arial", 12, "bold"), width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _build_wind_tab(self):
        frame = self.wind_frame

        # Enable
        self.enable_wind_scenarios = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Create Wind Scenario Grids",
                       variable=self.enable_wind_scenarios, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Description
        desc = tk.Label(frame, 
            text="Creates Low (10th pct), Likely (median), and High (90th pct) wind scenarios.\n"
                 "Use when model spread is high to bracket uncertainty.",
            font=("Arial", 9), fg="gray", justify=tk.LEFT)
        desc.pack(anchor=tk.W, padx=20)

        # Model selection
        model_frame = tk.LabelFrame(frame, text="Wind Models for Scenarios", padx=10, pady=5)
        model_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wind_model_vars = {}
        for model in WIND_MODELS:
            var = tk.BooleanVar(value=(model in ["GFS", "ECMWF", "NAM", "CMC"]))
            self.wind_model_vars[model] = var
            tk.Checkbutton(model_frame, text=model, variable=var).pack(anchor=tk.W)

        # Percentile settings
        pct_frame = tk.LabelFrame(frame, text="Scenario Percentiles", padx=10, pady=5)
        pct_frame.pack(fill=tk.X, padx=10, pady=10)

        row = tk.Frame(pct_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Low Scenario:", width=14).pack(side=tk.LEFT)
        self.wind_low_pct = tk.IntVar(value=10)
        tk.Scale(row, from_=5, to=30, orient=tk.HORIZONTAL, variable=self.wind_low_pct,
                length=150).pack(side=tk.LEFT)
        tk.Label(row, text="percentile").pack(side=tk.LEFT)

        row = tk.Frame(pct_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="High Scenario:", width=14).pack(side=tk.LEFT)
        self.wind_high_pct = tk.IntVar(value=90)
        tk.Scale(row, from_=70, to=95, orient=tk.HORIZONTAL, variable=self.wind_high_pct,
                length=150).pack(side=tk.LEFT)
        tk.Label(row, text="percentile").pack(side=tk.LEFT)

        # Output options
        output_frame = tk.LabelFrame(frame, text="Output Grids", padx=10, pady=5)
        output_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wind_outputs = {
            "WindLow": tk.BooleanVar(value=True),
            "WindLikely": tk.BooleanVar(value=True),
            "WindHigh": tk.BooleanVar(value=True),
            "WindScenarioSpread": tk.BooleanVar(value=True),
        }
        for name, var in self.wind_outputs.items():
            tk.Checkbutton(output_frame, text=name, variable=var).pack(anchor=tk.W)

    def _build_wave_tab(self):
        frame = self.wave_frame

        # Enable
        self.enable_wave_scenarios = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Create Wave Scenario Grids",
                       variable=self.enable_wave_scenarios, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Model selection
        model_frame = tk.LabelFrame(frame, text="Wave Models for Scenarios", padx=10, pady=5)
        model_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wave_model_vars = {}
        for model in WAVE_MODELS:
            var = tk.BooleanVar(value=True)
            self.wave_model_vars[model] = var
            tk.Checkbutton(model_frame, text=model, variable=var).pack(anchor=tk.W)

        # Percentile settings
        pct_frame = tk.LabelFrame(frame, text="Scenario Percentiles", padx=10, pady=5)
        pct_frame.pack(fill=tk.X, padx=10, pady=10)

        row = tk.Frame(pct_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Low Scenario:", width=14).pack(side=tk.LEFT)
        self.wave_low_pct = tk.IntVar(value=10)
        tk.Scale(row, from_=5, to=30, orient=tk.HORIZONTAL, variable=self.wave_low_pct,
                length=150).pack(side=tk.LEFT)

        row = tk.Frame(pct_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="High Scenario:", width=14).pack(side=tk.LEFT)
        self.wave_high_pct = tk.IntVar(value=90)
        tk.Scale(row, from_=70, to=95, orient=tk.HORIZONTAL, variable=self.wave_high_pct,
                length=150).pack(side=tk.LEFT)

        # Output options
        output_frame = tk.LabelFrame(frame, text="Output Grids", padx=10, pady=5)
        output_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wave_outputs = {
            "WaveLow": tk.BooleanVar(value=True),
            "WaveLikely": tk.BooleanVar(value=True),
            "WaveHigh": tk.BooleanVar(value=True),
            "WaveScenarioSpread": tk.BooleanVar(value=True),
        }
        for name, var in self.wave_outputs.items():
            tk.Checkbutton(output_frame, text=name, variable=var).pack(anchor=tk.W)

    def _build_hazard_tab(self):
        frame = self.hazard_frame

        # Enable
        self.enable_hazard_analysis = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Generate Hazard Suggestions",
                       variable=self.enable_hazard_analysis, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Description
        desc = tk.Label(frame,
            text="Creates suggested hazard grids and headline recommendations\n"
                 "based on probability thresholds.",
            font=("Arial", 9), fg="gray", justify=tk.LEFT)
        desc.pack(anchor=tk.W, padx=20)

        # Probability thresholds
        prob_frame = tk.LabelFrame(frame, text="Probability Thresholds for Headlines", padx=10, pady=5)
        prob_frame.pack(fill=tk.X, padx=10, pady=10)

        row = tk.Frame(prob_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Likely (mention):", width=18).pack(side=tk.LEFT)
        self.prob_likely = tk.IntVar(value=60)
        tk.Scale(row, from_=40, to=80, orient=tk.HORIZONTAL, variable=self.prob_likely,
                length=150).pack(side=tk.LEFT)
        tk.Label(row, text="%").pack(side=tk.LEFT)

        row = tk.Frame(prob_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Possible (consider):", width=18).pack(side=tk.LEFT)
        self.prob_possible = tk.IntVar(value=30)
        tk.Scale(row, from_=20, to=50, orient=tk.HORIZONTAL, variable=self.prob_possible,
                length=150).pack(side=tk.LEFT)
        tk.Label(row, text="%").pack(side=tk.LEFT)

        # Output options
        output_frame = tk.LabelFrame(frame, text="Hazard Analysis Outputs", padx=10, pady=5)
        output_frame.pack(fill=tk.X, padx=10, pady=10)

        self.hazard_outputs = {
            "SuggestedWindHazard": tk.BooleanVar(value=True),
            "SuggestedWaveHazard": tk.BooleanVar(value=True),
            "MaxWindHazard": tk.BooleanVar(value=True),
            "HeadlineReport": tk.BooleanVar(value=True),
        }
        
        descriptions = {
            "SuggestedWindHazard": "Wind hazard based on 'likely' probability",
            "SuggestedWaveHazard": "Wave hazard based on 'likely' probability",
            "MaxWindHazard": "Highest hazard with any significant probability",
            "HeadlineReport": "Text summary with recommendations",
        }
        
        for name, var in self.hazard_outputs.items():
            row = tk.Frame(output_frame)
            row.pack(fill=tk.X)
            tk.Checkbutton(row, text=name, variable=var).pack(side=tk.LEFT)
            tk.Label(row, text=f"  ({descriptions[name]})", font=("Arial", 8), fg="gray").pack(side=tk.LEFT)

    def _run(self):
        config = {
            # Wind scenarios
            "enable_wind_scenarios": self.enable_wind_scenarios.get(),
            "wind_models": [m for m, v in self.wind_model_vars.items() if v.get()],
            "wind_low_pct": self.wind_low_pct.get(),
            "wind_high_pct": self.wind_high_pct.get(),
            "wind_outputs": {k: v.get() for k, v in self.wind_outputs.items()},

            # Wave scenarios
            "enable_wave_scenarios": self.enable_wave_scenarios.get(),
            "wave_models": [m for m, v in self.wave_model_vars.items() if v.get()],
            "wave_low_pct": self.wave_low_pct.get(),
            "wave_high_pct": self.wave_high_pct.get(),
            "wave_outputs": {k: v.get() for k, v in self.wave_outputs.items()},

            # Hazard analysis
            "enable_hazard_analysis": self.enable_hazard_analysis.get(),
            "prob_likely": self.prob_likely.get(),
            "prob_possible": self.prob_possible.get(),
            "hazard_outputs": {k: v.get() for k, v in self.hazard_outputs.items()},
        }
        self.callback(config)
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


# =============================================================================
# Procedure
# =============================================================================

class Procedure(SmartScript.SmartScript):
    """Scenario analysis and hazard suggestion procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.log_messages: List[str] = []
        self.headline_report: List[str] = []

    def log(self, msg: str):
        print(msg)
        self.log_messages.append(msg)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution."""
        self.log_messages = []
        self.headline_report = []

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                return

        self.log("=" * 70)
        self.log("SCENARIO ANALYSIS & HAZARD ASSESSMENT")
        self.log("=" * 70)

        # Get time ranges
        fcst = self.mutableID().modelIdentifier()
        grid_infos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not grid_infos:
            self.statusBarMsg("No Wind grids found", "S")
            return

        total = len(grid_infos)
        self.log(f"Analyzing {total} time periods")

        # Track hazard probabilities across all periods for headline report
        max_wind_probs = {h: 0.0 for h in WIND_HAZARDS}
        max_wave_probs = {h: 0.0 for h in WAVE_HAZARDS}

        for i, grid_info in enumerate(grid_infos):
            grid_tr = grid_info.gridTime()
            self.statusBarMsg(f"Analyzing {i+1}/{total}", "R")
            self.log(f"\n--- Period {i+1}/{total}: {grid_tr} ---")

            wind_grids = []
            wave_grids = []

            # Fetch wind models
            if varDict["enable_wind_scenarios"] or varDict["enable_hazard_analysis"]:
                for model in varDict["wind_models"]:
                    grid = grid_fetch.get_vector_grid(
                        self, model, "Wind", "SFC", grid_tr,
                        run_depth=1, noDataError=0
                    )
                    if grid is not None:
                        wind_grids.append(grid[0])  # Magnitude only

            # Fetch wave models
            if varDict["enable_wave_scenarios"] or varDict["enable_hazard_analysis"]:
                for model in varDict["wave_models"]:
                    grid = grid_fetch.get_grid(
                        self, model, "WaveHeight", "SFC", grid_tr,
                        run_depth=1, noDataError=0
                    )
                    if grid is not None:
                        wave_grids.append(grid)

            # Create wind scenarios
            if varDict["enable_wind_scenarios"] and len(wind_grids) >= 2:
                self._create_wind_scenarios(varDict, wind_grids, grid_tr)

            # Create wave scenarios
            if varDict["enable_wave_scenarios"] and len(wave_grids) >= 2:
                self._create_wave_scenarios(varDict, wave_grids, grid_tr)

            # Hazard analysis
            if varDict["enable_hazard_analysis"]:
                wind_probs, wave_probs = self._analyze_hazards(
                    varDict, wind_grids, wave_grids, grid_tr
                )
                
                # Track max probabilities
                for h, p in wind_probs.items():
                    max_wind_probs[h] = max(max_wind_probs[h], np.nanmax(p) if p is not None else 0)
                for h, p in wave_probs.items():
                    max_wave_probs[h] = max(max_wave_probs[h], np.nanmax(p) if p is not None else 0)

        # Generate headline report
        if varDict["enable_hazard_analysis"] and varDict["hazard_outputs"].get("HeadlineReport"):
            self._generate_headline_report(varDict, max_wind_probs, max_wave_probs)

        self.log("\n" + "=" * 70)
        self.log("Analysis Complete")
        self.statusBarMsg("Scenario analysis complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(config):
            result[0] = config

        gui = AnalyzeScenariosGUI(root, callback)
        root.mainloop()
        return result[0]

    # =========================================================================
    # Wind Scenarios
    # =========================================================================

    def _create_wind_scenarios(self, config: Dict, wind_grids: List[np.ndarray], grid_tr):
        """Create wind scenario grids."""
        self.log("  [Wind Scenarios]")

        low_pct = config["wind_low_pct"]
        high_pct = config["wind_high_pct"]
        outputs = config["wind_outputs"]

        # Calculate percentiles
        low, high = grid_ops.ensemble_percentile_range(wind_grids, low_pct, high_pct)
        median = grid_ops.ensemble_median(wind_grids)
        
        # Find which model is closest to each scenario
        summary = grid_ops.scenario_summary(wind_grids, model_names=config["wind_models"])

        if outputs.get("WindLow"):
            self.createGrid("Fcst", "WindLow", "SCALAR", low, grid_tr,
                           minAllowedValue=0, maxAllowedValue=150, units="kt")
            self.log(f"    WindLow ({low_pct}th pct): mean={np.nanmean(low):.1f} kt")

        if outputs.get("WindLikely"):
            self.createGrid("Fcst", "WindLikely", "SCALAR", median, grid_tr,
                           minAllowedValue=0, maxAllowedValue=150, units="kt")
            self.log(f"    WindLikely (median): mean={np.nanmean(median):.1f} kt")

        if outputs.get("WindHigh"):
            self.createGrid("Fcst", "WindHigh", "SCALAR", high, grid_tr,
                           minAllowedValue=0, maxAllowedValue=150, units="kt")
            self.log(f"    WindHigh ({high_pct}th pct): mean={np.nanmean(high):.1f} kt")

        if outputs.get("WindScenarioSpread"):
            spread = high - low
            self.createGrid("Fcst", "WindScenarioSpread", "SCALAR", spread, grid_tr,
                           minAllowedValue=0, maxAllowedValue=50, units="kt")
            self.log(f"    Scenario spread: mean={np.nanmean(spread):.1f} kt")

    # =========================================================================
    # Wave Scenarios
    # =========================================================================

    def _create_wave_scenarios(self, config: Dict, wave_grids: List[np.ndarray], grid_tr):
        """Create wave scenario grids."""
        self.log("  [Wave Scenarios]")

        low_pct = config["wave_low_pct"]
        high_pct = config["wave_high_pct"]
        outputs = config["wave_outputs"]

        low, high = grid_ops.ensemble_percentile_range(wave_grids, low_pct, high_pct)
        median = grid_ops.ensemble_median(wave_grids)

        if outputs.get("WaveLow"):
            self.createGrid("Fcst", "WaveLow", "SCALAR", low, grid_tr,
                           minAllowedValue=0, maxAllowedValue=50, units="ft")
            self.log(f"    WaveLow ({low_pct}th pct): mean={np.nanmean(low):.1f} ft")

        if outputs.get("WaveLikely"):
            self.createGrid("Fcst", "WaveLikely", "SCALAR", median, grid_tr,
                           minAllowedValue=0, maxAllowedValue=50, units="ft")
            self.log(f"    WaveLikely (median): mean={np.nanmean(median):.1f} ft")

        if outputs.get("WaveHigh"):
            self.createGrid("Fcst", "WaveHigh", "SCALAR", high, grid_tr,
                           minAllowedValue=0, maxAllowedValue=50, units="ft")
            self.log(f"    WaveHigh ({high_pct}th pct): mean={np.nanmean(high):.1f} ft")

        if outputs.get("WaveScenarioSpread"):
            spread = high - low
            self.createGrid("Fcst", "WaveScenarioSpread", "SCALAR", spread, grid_tr,
                           minAllowedValue=0, maxAllowedValue=20, units="ft")

    # =========================================================================
    # Hazard Analysis
    # =========================================================================

    def _analyze_hazards(self, config: Dict, wind_grids: List, wave_grids: List, 
                        grid_tr) -> Tuple[Dict, Dict]:
        """Analyze hazards and create suggested hazard grids."""
        self.log("  [Hazard Analysis]")

        prob_likely = config["prob_likely"]
        prob_possible = config["prob_possible"]
        outputs = config["hazard_outputs"]

        wind_probs = {}
        wave_probs = {}

        # Calculate wind hazard probabilities
        if len(wind_grids) >= 2:
            for hazard, info in WIND_HAZARDS.items():
                prob = grid_ops.prob_exceeds(wind_grids, info["threshold"])
                wind_probs[hazard] = prob
                max_prob = np.nanmax(prob)
                if max_prob > prob_possible:
                    self.log(f"    Wind {hazard} (≥{info['threshold']}kt): max prob={max_prob:.0f}%")

            # Create suggested wind hazard grid
            if outputs.get("SuggestedWindHazard"):
                suggested = self._create_suggested_hazard_grid(
                    wind_probs, WIND_HAZARDS, prob_likely
                )
                self.createGrid("Fcst", "SuggestedWindHazard", "SCALAR", suggested, grid_tr,
                               minAllowedValue=0, maxAllowedValue=4)

            # Create max wind hazard grid (any hazard with prob > possible)
            if outputs.get("MaxWindHazard"):
                max_haz = self._create_max_hazard_grid(
                    wind_probs, WIND_HAZARDS, prob_possible
                )
                self.createGrid("Fcst", "MaxWindHazard", "SCALAR", max_haz, grid_tr,
                               minAllowedValue=0, maxAllowedValue=4)

        # Calculate wave hazard probabilities
        if len(wave_grids) >= 2:
            for hazard, info in WAVE_HAZARDS.items():
                prob = grid_ops.prob_exceeds(wave_grids, info["threshold"])
                wave_probs[hazard] = prob
                max_prob = np.nanmax(prob)
                if max_prob > prob_possible:
                    self.log(f"    Wave {hazard} (≥{info['threshold']}ft): max prob={max_prob:.0f}%")

            # Create suggested wave hazard grid
            if outputs.get("SuggestedWaveHazard"):
                suggested = self._create_suggested_hazard_grid(
                    wave_probs, WAVE_HAZARDS, prob_likely
                )
                self.createGrid("Fcst", "SuggestedWaveHazard", "SCALAR", suggested, grid_tr,
                               minAllowedValue=0, maxAllowedValue=4)

        return wind_probs, wave_probs

    def _create_suggested_hazard_grid(self, probs: Dict[str, np.ndarray], 
                                       hazards: Dict, prob_threshold: float) -> np.ndarray:
        """
        Create grid with suggested hazard level based on probability threshold.
        
        Returns integer grid:
        0 = No hazard
        1 = SCA level
        2 = Gale/Rough level
        3 = Storm/VeryRough level
        4 = Hurricane/High level
        """
        # Get any probability grid for shape
        any_prob = next(iter(probs.values()))
        result = np.zeros_like(any_prob, dtype=np.float32)

        # Map hazard names to levels
        level_map = {
            "SCA": 1,
            "Gale": 2, "Rough": 2,
            "Storm": 3, "VeryRough": 3,
            "Hurricane": 4, "High": 4,
        }

        # Assign highest hazard level where prob exceeds threshold
        for hazard, prob in probs.items():
            level = level_map.get(hazard, 0)
            mask = prob >= prob_threshold
            result = np.where(mask & (level > result), level, result)

        return result

    def _create_max_hazard_grid(self, probs: Dict[str, np.ndarray],
                                 hazards: Dict, prob_threshold: float) -> np.ndarray:
        """Create grid showing maximum hazard with any significant probability."""
        any_prob = next(iter(probs.values()))
        result = np.zeros_like(any_prob, dtype=np.float32)

        level_map = {
            "SCA": 1,
            "Gale": 2, "Rough": 2,
            "Storm": 3, "VeryRough": 3,
            "Hurricane": 4, "High": 4,
        }

        for hazard, prob in probs.items():
            level = level_map.get(hazard, 0)
            mask = prob >= prob_threshold
            result = np.where(mask & (level > result), level, result)

        return result

    # =========================================================================
    # Headline Report
    # =========================================================================

    def _generate_headline_report(self, config: Dict, 
                                   max_wind_probs: Dict[str, float],
                                   max_wave_probs: Dict[str, float]):
        """Generate text report with headline recommendations."""
        self.log("\n" + "=" * 70)
        self.log("HEADLINE RECOMMENDATIONS")
        self.log("=" * 70)

        prob_likely = config["prob_likely"]
        prob_possible = config["prob_possible"]

        report = []
        report.append("HEADLINE ANALYSIS REPORT")
        report.append("=" * 40)
        report.append("")

        # Wind hazards
        report.append("WIND HAZARDS:")
        report.append("-" * 20)
        
        wind_recommendations = []
        for hazard in ["Hurricane", "Storm", "Gale", "SCA"]:
            prob = max_wind_probs.get(hazard, 0)
            info = WIND_HAZARDS[hazard]
            
            if prob >= prob_likely:
                status = "LIKELY"
                action = "RECOMMEND"
                wind_recommendations.append((hazard, info["headline"], prob, "LIKELY"))
            elif prob >= prob_possible:
                status = "POSSIBLE"
                action = "CONSIDER"
                wind_recommendations.append((hazard, info["headline"], prob, "POSSIBLE"))
            else:
                status = "UNLIKELY"
                action = None
            
            report.append(f"  {info['headline']}: {status} (max prob: {prob:.0f}%)")
            if action:
                self.log(f"  {action}: {info['headline']} (max prob: {prob:.0f}%)")

        report.append("")

        # Wave hazards
        report.append("WAVE HAZARDS:")
        report.append("-" * 20)
        
        for hazard in ["High", "VeryRough", "Rough", "SCA"]:
            prob = max_wave_probs.get(hazard, 0)
            info = WAVE_HAZARDS[hazard]
            
            if prob >= prob_likely:
                status = "LIKELY"
            elif prob >= prob_possible:
                status = "POSSIBLE"
            else:
                status = "UNLIKELY"
            
            report.append(f"  {info['headline']}: {status} (max prob: {prob:.0f}%)")

        report.append("")

        # Summary recommendation
        report.append("SUMMARY:")
        report.append("-" * 20)
        
        # Find highest likely wind hazard
        highest_wind = None
        for hazard in ["Hurricane", "Storm", "Gale", "SCA"]:
            if max_wind_probs.get(hazard, 0) >= prob_likely:
                highest_wind = WIND_HAZARDS[hazard]["headline"]
                break

        # Find highest possible wind hazard (for uncertainty messaging)
        highest_possible = None
        for hazard in ["Hurricane", "Storm", "Gale"]:
            prob = max_wind_probs.get(hazard, 0)
            if prob >= prob_possible and prob < prob_likely:
                highest_possible = WIND_HAZARDS[hazard]["headline"]
                break

        if highest_wind:
            report.append(f"  Primary headline: {highest_wind}")
            if highest_possible and highest_possible != highest_wind:
                report.append(f"  Consider upgrade to: {highest_possible} (if trend continues)")
        elif highest_possible:
            report.append(f"  Monitor for: {highest_possible}")
            report.append("  Currently no headlines warranted")
        else:
            report.append("  No significant wind hazards expected")

        report.append("")
        report.append("Hazard levels: 0=None, 1=SCA, 2=Gale, 3=Storm, 4=Hurricane")

        # Print full report
        for line in report:
            self.log(line)

        self.headline_report = report

        # Show popup with report
        self._show_report_popup(report)

    def _show_report_popup(self, report: List[str]):
        """Show headline report in a popup window."""
        try:
            popup = tk.Tk()
            popup.title("Headline Recommendations")
            popup.geometry("500x400")

            text = scrolledtext.ScrolledText(popup, wrap=tk.WORD, width=60, height=20)
            text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            for line in report:
                text.insert(tk.END, line + "\n")

            text.config(state=tk.DISABLED)

            tk.Button(popup, text="Close", command=popup.destroy).pack(pady=10)

            popup.mainloop()
        except Exception:
            pass  # GUI may not be available in all contexts


__all__ = ["Procedure"]
