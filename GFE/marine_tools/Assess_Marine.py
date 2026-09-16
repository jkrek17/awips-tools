"""
Assess_Marine - Unified Marine Assessment Tool

Comprehensive diagnostic tool for marine forecasting that assesses:
- Model Confidence: Ensemble agreement, spread, outlier detection
- Marine Stability: SST-based instability, wind boost potential, fog risk
- Hazard Probability: Probability of exceeding gale/storm/hurricane thresholds

Run this BEFORE populating grids to understand the forecast situation.

Uses: grid_ops, stability_blend utilities
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript

from utilities import grid_ops
from utilities import stability_blend
from utilities.stability_blend import BoostConfig
import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Populate"]
VariableList = []

# =============================================================================
# Configuration
# =============================================================================

# Models for ensemble analysis
WIND_MODELS = ["GFS", "ECMWF", "NAM", "CMC", "UKMET"]
WAVE_MODELS = ["GFSWAVE", "ECMWF", "CMC"]

# Hazard thresholds
WIND_THRESHOLDS = {
    "SCA": 21,        # Small Craft Advisory
    "Gale": 34,       # Gale Warning
    "Storm": 48,      # Storm Warning
    "Hurricane": 64,  # Hurricane Force Wind Warning
}

WAVE_THRESHOLDS = {
    "Moderate": 4,    # 4 ft
    "Rough": 8,       # 8 ft
    "VeryRough": 13,  # 13 ft
    "High": 20,       # 20 ft
}

VIS_THRESHOLDS = {
    "Dense": 0.25,    # Dense Fog (NM)
    "Fog": 1.0,       # Fog
    "Mist": 3.0,      # Mist/Haze
}


# =============================================================================
# GUI
# =============================================================================

class AssessMarineGUI:
    """GUI for marine assessment tool."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Assessment Tool")
        self.master.geometry("700x900")
        self.master.resizable(True, True)

        self._build_ui()

    def _build_ui(self):
        # Create notebook for tabs
        notebook = ttk.Notebook(self.master)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Model Confidence
        self.confidence_frame = ttk.Frame(notebook)
        notebook.add(self.confidence_frame, text="Model Confidence")
        self._build_confidence_tab()

        # Tab 2: Marine Stability
        self.stability_frame = ttk.Frame(notebook)
        notebook.add(self.stability_frame, text="Marine Stability")
        self._build_stability_tab()

        # Tab 3: Hazard Probability
        self.hazard_frame = ttk.Frame(notebook)
        notebook.add(self.hazard_frame, text="Hazard Probability")
        self._build_hazard_tab()

        # Bottom buttons
        btn_frame = tk.Frame(self.master)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(btn_frame, text="Run Assessment", command=self._run,
                  bg="lightblue", font=("Arial", 12, "bold"), width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _build_confidence_tab(self):
        frame = self.confidence_frame
        
        # Enable checkbox
        self.enable_confidence = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Run Model Confidence Assessment",
                       variable=self.enable_confidence, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Description
        desc = tk.Label(frame, text="Analyzes ensemble agreement and identifies outlier models.\n"
                        "High confidence = models agree. Low confidence = consider scenarios.",
                        font=("Arial", 9), fg="gray", justify=tk.LEFT)
        desc.pack(anchor=tk.W, padx=20)

        # Model selection
        model_frame = tk.LabelFrame(frame, text="Wind Models to Analyze", padx=10, pady=5)
        model_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wind_model_vars = {}
        for model in WIND_MODELS:
            var = tk.BooleanVar(value=(model in ["GFS", "ECMWF", "NAM"]))
            self.wind_model_vars[model] = var
            tk.Checkbutton(model_frame, text=model, variable=var).pack(anchor=tk.W)

        # Wave models
        wave_frame = tk.LabelFrame(frame, text="Wave Models to Analyze", padx=10, pady=5)
        wave_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wave_model_vars = {}
        for model in WAVE_MODELS:
            var = tk.BooleanVar(value=True)
            self.wave_model_vars[model] = var
            tk.Checkbutton(wave_frame, text=model, variable=var).pack(anchor=tk.W)

        # Output options
        output_frame = tk.LabelFrame(frame, text="Output Grids", padx=10, pady=5)
        output_frame.pack(fill=tk.X, padx=10, pady=10)

        self.conf_outputs = {
            "WindConfidence": tk.BooleanVar(value=True),
            "WindSpread": tk.BooleanVar(value=True),
            "WaveConfidence": tk.BooleanVar(value=True),
            "WaveSpread": tk.BooleanVar(value=True),
            "ModelAgreement": tk.BooleanVar(value=True),
        }
        for name, var in self.conf_outputs.items():
            tk.Checkbutton(output_frame, text=name, variable=var).pack(anchor=tk.W)

    def _build_stability_tab(self):
        frame = self.stability_frame

        # Enable checkbox
        self.enable_stability = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Run Marine Stability Assessment",
                       variable=self.enable_stability, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Description
        desc = tk.Label(frame, text="Calculates atmospheric stability from SST and upper-air temperatures.\n"
                        "Identifies where winds will be enhanced and fog is likely.",
                        font=("Arial", 9), fg="gray", justify=tk.LEFT)
        desc.pack(anchor=tk.W, padx=20)

        # SST Source
        sst_frame = tk.LabelFrame(frame, text="SST Source", padx=10, pady=5)
        sst_frame.pack(fill=tk.X, padx=10, pady=10)

        self.sst_source = tk.StringVar(value="RTOFS")
        for src in ["RTOFS", "Fcst", "RTGSST"]:
            tk.Radiobutton(sst_frame, text=src, variable=self.sst_source, value=src).pack(anchor=tk.W)

        # Upper air source
        upper_frame = tk.LabelFrame(frame, text="Upper Air Source", padx=10, pady=5)
        upper_frame.pack(fill=tk.X, padx=10, pady=10)

        self.upper_source = tk.StringVar(value="GFS")
        for src in ["GFS", "ECMWF", "Blend"]:
            tk.Radiobutton(upper_frame, text=src, variable=self.upper_source, value=src).pack(anchor=tk.W)

        # Boost config
        boost_frame = tk.LabelFrame(frame, text="Wind Boost Parameters", padx=10, pady=5)
        boost_frame.pack(fill=tk.X, padx=10, pady=10)

        row1 = tk.Frame(boost_frame)
        row1.pack(fill=tk.X)
        tk.Label(row1, text="Max Boost Factor:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.max_boost = tk.DoubleVar(value=1.35)
        tk.Scale(row1, from_=1.1, to=1.5, resolution=0.05, orient=tk.HORIZONTAL,
                 variable=self.max_boost, length=150).pack(side=tk.LEFT)

        # Output options
        output_frame = tk.LabelFrame(frame, text="Output Grids", padx=10, pady=5)
        output_frame.pack(fill=tk.X, padx=10, pady=10)

        self.stab_outputs = {
            "Instability": tk.BooleanVar(value=True),
            "WindBoostFactor": tk.BooleanVar(value=True),
            "StabilityClass": tk.BooleanVar(value=True),
            "MixingPotential": tk.BooleanVar(value=True),
            "FogPotential": tk.BooleanVar(value=True),
        }
        for name, var in self.stab_outputs.items():
            tk.Checkbutton(output_frame, text=name, variable=var).pack(anchor=tk.W)

    def _build_hazard_tab(self):
        frame = self.hazard_frame

        # Enable checkbox
        self.enable_hazard = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Run Hazard Probability Assessment",
                       variable=self.enable_hazard, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Description
        desc = tk.Label(frame, text="Calculates probability of exceeding hazard thresholds.\n"
                        "Essential for headline decisions and risk communication.",
                        font=("Arial", 9), fg="gray", justify=tk.LEFT)
        desc.pack(anchor=tk.W, padx=20)

        # Wind hazards
        wind_frame = tk.LabelFrame(frame, text="Wind Hazard Probabilities", padx=10, pady=5)
        wind_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wind_hazard_outputs = {}
        for name, thresh in WIND_THRESHOLDS.items():
            var = tk.BooleanVar(value=True)
            self.wind_hazard_outputs[name] = var
            tk.Checkbutton(wind_frame, text=f"Prob{name} (≥{thresh} kt)", variable=var).pack(anchor=tk.W)

        # Wave hazards
        wave_frame = tk.LabelFrame(frame, text="Wave Hazard Probabilities", padx=10, pady=5)
        wave_frame.pack(fill=tk.X, padx=10, pady=10)

        self.wave_hazard_outputs = {}
        for name, thresh in WAVE_THRESHOLDS.items():
            var = tk.BooleanVar(value=(name in ["Rough", "VeryRough"]))
            self.wave_hazard_outputs[name] = var
            tk.Checkbutton(wave_frame, text=f"ProbWave{name} (≥{thresh} ft)", variable=var).pack(anchor=tk.W)

        # Visibility hazards
        vis_frame = tk.LabelFrame(frame, text="Visibility Hazard Probabilities", padx=10, pady=5)
        vis_frame.pack(fill=tk.X, padx=10, pady=10)

        self.vis_hazard_outputs = {}
        for name, thresh in VIS_THRESHOLDS.items():
            var = tk.BooleanVar(value=(name in ["Dense", "Fog"]))
            self.vis_hazard_outputs[name] = var
            tk.Checkbutton(vis_frame, text=f"ProbVis{name} (<{thresh} NM)", variable=var).pack(anchor=tk.W)

    def _run(self):
        config = {
            # Confidence settings
            "enable_confidence": self.enable_confidence.get(),
            "wind_models": [m for m, v in self.wind_model_vars.items() if v.get()],
            "wave_models": [m for m, v in self.wave_model_vars.items() if v.get()],
            "conf_outputs": {k: v.get() for k, v in self.conf_outputs.items()},

            # Stability settings
            "enable_stability": self.enable_stability.get(),
            "sst_source": self.sst_source.get(),
            "upper_source": self.upper_source.get(),
            "max_boost": self.max_boost.get(),
            "stab_outputs": {k: v.get() for k, v in self.stab_outputs.items()},

            # Hazard settings
            "enable_hazard": self.enable_hazard.get(),
            "wind_hazards": {k: v.get() for k, v in self.wind_hazard_outputs.items()},
            "wave_hazards": {k: v.get() for k, v in self.wave_hazard_outputs.items()},
            "vis_hazards": {k: v.get() for k, v in self.vis_hazard_outputs.items()},
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
    """Marine assessment procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.log_messages: List[str] = []

    def log(self, msg: str):
        print(msg)
        self.log_messages.append(msg)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution."""
        self.log_messages = []

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                return

        self.log("=" * 70)
        self.log("MARINE ASSESSMENT TOOL")
        self.log("=" * 70)

        # Get time ranges
        fcst = self.mutableID().modelIdentifier()
        grid_infos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not grid_infos:
            self.statusBarMsg("No Wind grids found in time range", "S")
            return

        total = len(grid_infos)
        self.log(f"Processing {total} time periods")

        for i, grid_info in enumerate(grid_infos):
            grid_tr = grid_info.gridTime()
            self.statusBarMsg(f"Assessing {i+1}/{total}", "R")
            self.log(f"\n--- Period {i+1}/{total}: {grid_tr} ---")

            # Run enabled assessments
            if varDict["enable_confidence"]:
                self._assess_confidence(varDict, grid_tr)

            if varDict["enable_stability"]:
                self._assess_stability(varDict, grid_tr)

            if varDict["enable_hazard"]:
                self._assess_hazard(varDict, grid_tr)

        self.log("\n" + "=" * 70)
        self.log("Assessment Complete")
        self.statusBarMsg("Assessment complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(config):
            result[0] = config

        gui = AssessMarineGUI(root, callback)
        root.mainloop()
        return result[0]

    # =========================================================================
    # Confidence Assessment
    # =========================================================================

    def _assess_confidence(self, config: Dict, grid_tr):
        """Assess model confidence/agreement."""
        self.log("  [Confidence Assessment]")

        wind_models = config["wind_models"]
        wave_models = config["wave_models"]
        outputs = config["conf_outputs"]

        # Fetch wind grids
        wind_grids = []
        wind_names = []
        for model in wind_models:
            grid = grid_fetch.get_vector_grid(
                self, model, "Wind", "SFC", grid_tr,
                run_depth=1, noDataError=0
            )
            if grid is not None:
                wind_grids.append(grid[0])  # Just magnitude for confidence
                wind_names.append(model)

        if len(wind_grids) >= 2:
            # Calculate confidence metrics
            if outputs.get("WindConfidence"):
                confidence = grid_ops.ensemble_confidence(wind_grids)
                self.createGrid("Fcst", "WindConfidence", "SCALAR", confidence, grid_tr,
                               minAllowedValue=0, maxAllowedValue=100, units="%")
                self.log(f"    WindConfidence: mean={np.nanmean(confidence):.1f}%")

            if outputs.get("WindSpread"):
                spread = grid_ops.ensemble_spread(wind_grids)
                self.createGrid("Fcst", "WindSpread", "SCALAR", spread, grid_tr,
                               minAllowedValue=0, maxAllowedValue=50, units="kt")
                self.log(f"    WindSpread: mean={np.nanmean(spread):.1f} kt, max={np.nanmax(spread):.1f} kt")

            if outputs.get("ModelAgreement"):
                agreement = grid_ops.ensemble_agreement(wind_grids)
                self.createGrid("Fcst", "ModelAgreement", "SCALAR", agreement, grid_tr,
                               minAllowedValue=0, maxAllowedValue=100, units="%")
        else:
            self.log(f"    Only {len(wind_grids)} wind models available, need 2+ for confidence")

        # Fetch wave grids
        wave_grids = []
        for model in wave_models:
            grid = grid_fetch.get_grid(
                self, model, "WaveHeight", "SFC", grid_tr,
                run_depth=1, noDataError=0
            )
            if grid is not None:
                wave_grids.append(grid)

        if len(wave_grids) >= 2:
            if outputs.get("WaveConfidence"):
                confidence = grid_ops.ensemble_confidence(wave_grids)
                self.createGrid("Fcst", "WaveConfidence", "SCALAR", confidence, grid_tr,
                               minAllowedValue=0, maxAllowedValue=100, units="%")
                self.log(f"    WaveConfidence: mean={np.nanmean(confidence):.1f}%")

            if outputs.get("WaveSpread"):
                spread = grid_ops.ensemble_spread(wave_grids)
                self.createGrid("Fcst", "WaveSpread", "SCALAR", spread, grid_tr,
                               minAllowedValue=0, maxAllowedValue=20, units="ft")
                self.log(f"    WaveSpread: mean={np.nanmean(spread):.1f} ft")
        else:
            self.log(f"    Only {len(wave_grids)} wave models available")

    # =========================================================================
    # Stability Assessment
    # =========================================================================

    def _assess_stability(self, config: Dict, grid_tr):
        """Assess marine stability."""
        self.log("  [Stability Assessment]")

        sst_source = config["sst_source"]
        upper_source = config["upper_source"]
        max_boost = config["max_boost"]
        outputs = config["stab_outputs"]

        # Get SST
        sst = self._get_sst(sst_source, grid_tr)
        if sst is None:
            self.log("    ERROR: No SST data available")
            return

        # Get upper air temperature (850mb)
        t850 = self._get_upper_temp(upper_source, 850, grid_tr)
        if t850 is None:
            self.log("    ERROR: No T850 data available")
            return

        # Optional: Get T925 for dual-level analysis
        t925 = self._get_upper_temp(upper_source, 925, grid_tr)

        # Get surface temperature for fog calculation
        t2m = grid_fetch.get_grid(self, upper_source, "T", "SFC", grid_tr, noDataError=0)
        rh = grid_fetch.get_grid(self, upper_source, "RH", "SFC", grid_tr, noDataError=0)

        # Run stability analysis
        boost_config = BoostConfig(
            min_factor=1.0,
            max_factor=max_boost,
            instability_threshold=3.0,
            full_boost_threshold=10.0,
        )

        result = stability_blend.analyze_stability(
            sst, t850,
            t925=t925,
            boost_config=boost_config
        )

        self.log(f"    {result.description}")

        # Create output grids
        if outputs.get("Instability"):
            instability = np.clip(result.instability, -15, 20)
            self.createGrid("Fcst", "Instability", "SCALAR", instability, grid_tr,
                           minAllowedValue=-15, maxAllowedValue=20, units="K")
            self.log(f"    Instability: mean={np.nanmean(instability):.1f} K")

        if outputs.get("WindBoostFactor"):
            boost = result.boost_factor
            self.createGrid("Fcst", "WindBoostFactor", "SCALAR", boost, grid_tr,
                           minAllowedValue=1.0, maxAllowedValue=1.5)
            boost_area = np.sum(boost > 1.05) / boost.size * 100
            self.log(f"    WindBoostFactor: {boost_area:.1f}% of area will be boosted")

        if outputs.get("StabilityClass"):
            stab_class = result.stability_class.astype(float)
            self.createGrid("Fcst", "StabilityClass", "SCALAR", stab_class, grid_tr,
                           minAllowedValue=0, maxAllowedValue=4)

        if outputs.get("MixingPotential"):
            mixing = result.mixing_potential
            self.createGrid("Fcst", "MixingPotential", "SCALAR", mixing, grid_tr,
                           minAllowedValue=0, maxAllowedValue=100, units="%")

        if outputs.get("FogPotential"):
            if t2m is not None and rh is not None:
                # Convert t2m to same units as SST if needed
                if np.nanmax(t2m) > 200:  # Kelvin
                    t2m = t2m - 273.15
                fog = stability_blend.calc_fog_potential(sst, t2m, rh)
                self.createGrid("Fcst", "FogPotential", "SCALAR", fog, grid_tr,
                               minAllowedValue=0, maxAllowedValue=100, units="%")
                self.log(f"    FogPotential: max={np.nanmax(fog):.1f}%")
            else:
                self.log("    FogPotential: Missing T2m or RH data")

    def _get_sst(self, source: str, grid_tr) -> Optional[np.ndarray]:
        """Get SST in Celsius."""
        if source == "RTOFS":
            sst = grid_fetch.get_grid(self, "RTOFS", "SST", "SFC", grid_tr, run_depth=2, noDataError=0)
        elif source == "RTGSST":
            sst = grid_fetch.get_grid(self, "RTGSST", "SST", "SFC", grid_tr, run_depth=2, noDataError=0)
        else:
            sst = self.getGrids("Fcst", "SST", "SFC", grid_tr, noDataError=0)

        if sst is None:
            return None

        # Convert to Celsius
        if np.nanmax(sst) > 200:  # Kelvin
            sst = sst - 273.15
        elif np.nanmax(sst) > 50:  # Fahrenheit
            sst = (sst - 32) * 5 / 9

        return sst

    def _get_upper_temp(self, source: str, level: int, grid_tr) -> Optional[np.ndarray]:
        """Get upper air temperature in Celsius."""
        level_str = f"MB{level}"

        if source == "Blend":
            # Average GFS and ECMWF
            gfs = grid_fetch.get_grid(self, "GFS", "t", level_str, grid_tr, noDataError=0)
            ecmwf = grid_fetch.get_grid(self, "ECMWF", "t", level_str, grid_tr, noDataError=0)
            
            temps = [t for t in [gfs, ecmwf] if t is not None]
            if not temps:
                return None
            temp = np.mean(np.stack(temps), axis=0)
        else:
            temp = grid_fetch.get_grid(self, source, "t", level_str, grid_tr, noDataError=0)

        if temp is None:
            return None

        # Convert to Celsius
        if np.nanmax(temp) > 200:
            temp = temp - 273.15

        return temp

    # =========================================================================
    # Hazard Probability Assessment
    # =========================================================================

    def _assess_hazard(self, config: Dict, grid_tr):
        """Assess hazard probabilities."""
        self.log("  [Hazard Probability Assessment]")

        wind_models = config["wind_models"]
        wave_models = config["wave_models"]
        wind_hazards = config["wind_hazards"]
        wave_hazards = config["wave_hazards"]
        vis_hazards = config["vis_hazards"]

        # Fetch wind grids
        wind_grids = []
        for model in wind_models:
            grid = grid_fetch.get_vector_grid(
                self, model, "Wind", "SFC", grid_tr,
                run_depth=1, noDataError=0
            )
            if grid is not None:
                wind_grids.append(grid[0])

        # Wind hazard probabilities
        if len(wind_grids) >= 2:
            for hazard, enabled in wind_hazards.items():
                if enabled:
                    threshold = WIND_THRESHOLDS[hazard]
                    prob = grid_ops.prob_exceeds(wind_grids, threshold)
                    self.createGrid("Fcst", f"ProbWind{hazard}", "SCALAR", prob, grid_tr,
                                   minAllowedValue=0, maxAllowedValue=100, units="%")
                    max_prob = np.nanmax(prob)
                    area_above_50 = np.sum(prob > 50) / prob.size * 100
                    self.log(f"    ProbWind{hazard} (≥{threshold}kt): max={max_prob:.0f}%, "
                            f"area >50%: {area_above_50:.1f}%")
        else:
            self.log("    Wind hazards: insufficient models")

        # Fetch wave grids
        wave_grids = []
        for model in wave_models:
            grid = grid_fetch.get_grid(
                self, model, "WaveHeight", "SFC", grid_tr,
                run_depth=1, noDataError=0
            )
            if grid is not None:
                wave_grids.append(grid)

        # Wave hazard probabilities
        if len(wave_grids) >= 2:
            for hazard, enabled in wave_hazards.items():
                if enabled:
                    threshold = WAVE_THRESHOLDS[hazard]
                    prob = grid_ops.prob_exceeds(wave_grids, threshold)
                    self.createGrid("Fcst", f"ProbWave{hazard}", "SCALAR", prob, grid_tr,
                                   minAllowedValue=0, maxAllowedValue=100, units="%")
                    max_prob = np.nanmax(prob)
                    self.log(f"    ProbWave{hazard} (≥{threshold}ft): max={max_prob:.0f}%")
        else:
            self.log("    Wave hazards: insufficient models")

        # Visibility hazard probabilities
        vis_grids = []
        for model in wind_models:  # Use same models as wind
            grid = grid_fetch.get_grid(
                self, model, "Vis", "SFC", grid_tr,
                run_depth=1, noDataError=0
            )
            if grid is not None:
                # Convert to NM if in meters
                if np.nanmax(grid) > 100:
                    grid = grid / 1852.0
                vis_grids.append(grid)

        if len(vis_grids) >= 2:
            for hazard, enabled in vis_hazards.items():
                if enabled:
                    threshold = VIS_THRESHOLDS[hazard]
                    prob = grid_ops.prob_below(vis_grids, threshold)
                    self.createGrid("Fcst", f"ProbVis{hazard}", "SCALAR", prob, grid_tr,
                                   minAllowedValue=0, maxAllowedValue=100, units="%")
                    max_prob = np.nanmax(prob)
                    self.log(f"    ProbVis{hazard} (<{threshold}NM): max={max_prob:.0f}%")
        else:
            self.log("    Visibility hazards: insufficient models")


__all__ = ["Procedure"]
