"""
Populate_ConsensusWind - Pattern-Based Multi-Model Wind Consensus.

Creates wind grids using:
1. PATTERN (Direction): Multi-model circular mean for consensus flow
2. MAGNITUDE: Individual model speeds combined using one of the supported strategies

The key insight: Models often agree on synoptic patterns (direction) better
than on exact speeds. By using consensus direction with agreement-weighted
magnitudes, we create more realistic wind forecasts.

MAGNITUDE STRATEGIES:

1. Mean
   Simple arithmetic average of all model wind speeds at each grid point.
   Pros: Smooth, balanced result that reduces noise.
   Cons: Washes out strong features (fronts, jets, gradients) that may be
         important for marine operations.
   Best for: General forecasting when model agreement is high.

2. Maximum
   Takes the highest wind speed from all models at each grid point.
   Pros: Conservative approach - errs on the side of safety by using strongest
         winds. Preserves extreme values that might be critical.
   Cons: May over-forecast winds, especially if one model is an outlier.
   Best for: Safety-critical operations, marine warnings, when conservative
             forecasts are preferred.

3. Median
   The middle value of all model winds at each grid point.
   Pros: Highly robust to outliers. If one model has crazy high winds,
         Median ignores it (unlike Mean, which gets skewed).
   Cons: Can result in "jumpy" fields if models are very different.
   Best for: General forecasting when you want to filter out rogue models
             without any manual tuning.

4. 90th Percentile
   The value below which 90% of the models fall. "Reasonable Worst Case".
   Pros: Standard statistical approach for safety/risk assessment. Captures
         high-end potential without using the absolute single-point maximum
         (which is often an error/outlier).
   Cons: Higher than the mean/consensus.
   Best for: Marine warnings and safety-critical forecasts where under-
             forecasting is more dangerous than over-forecasting.

5. Spread-Adjusted
    Mean + (Standard Deviation × Factor). Dynamically pads the forecast
    based on model uncertainty.
    Method: Calculates mean and standard deviation across all models at each
            grid point, then adds a fraction of the spread to the mean.
    Pros: Automatically increases forecast where models disagree (high spread),
          stays close to mean where models agree. Accounts for uncertainty.
    Cons: Can over-pad if one outlier creates large spread.
    Best for: When you want a single field that implicitly captures risk.
              The spread factor (default 0.5) can be tuned.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage

import SmartScript

import grid_fetch
import thresholds
import model_aliases

MenuItems = ["Populate"]
VariableList = []

# Available models for consensus
CONSENSUS_MODELS = [
    ("GFS", "Global Forecast System", 4),
    ("ECMWF", "European Centre", 2),
    ("CMC", "Canadian Global", 4),
    ("UKMET", "UK Met Office", 4),
    ("GEFS", "GFS Ensemble Mean", 4),
]

# Magnitude strategies
MAG_STRATEGIES = [
    "Mean",                    # Simple average
    "Median",                  # Robust central tendency (ignores outliers)
    "Maximum",                 # Highest model (conservative)
    "90th Percentile",         # Reasonable worst case
    "Spread-Adjusted",         # Mean + (spread × factor) for uncertainty padding
]

# Centralized tunables for GUI defaults and method parameters
CONFIG = {
    "gui_defaults": {
        "dir_tolerance_deg": 30,
        "weight_decay": 0.5,
        "smoothing_passes": 2,
        "gust_multiplier": 1.3,
        "max_boost": 0.25,
    },
    "pattern_weighted": {
        # Decay scale (deg) in exp(-(diff - tol)/scale)
        "decay_scale_deg": 45.0,
    },
    "feature_preserving": {
        # Feature mask when max exceeds mean by this multiplier
        "feature_threshold": 1.2,
        # Gradient percentile to flag frontal zones
        "gradient_percentile": 75,
    },
    "spread_adjusted": {
        # Mean + std * factor
        "spread_factor": 0.5,
    },
    "spatial_consensus": {
        # Fraction of centroid spacing for decay radius
        "decay_fraction": 0.25,
        "decay_min": 8.0,
        "decay_max": 15.0,
        # Fallback decay when only one centroid
        "single_decay": 12.0,
        # Significant wind mask threshold (fraction of model max)
        "significant_fraction": 0.8,
        # Percentile used for magnitude (reasonable worst case)
        "percentile": 90,
    },
    "hybrid_consensus": {
        "significant_fraction": 0.8,
        "percentile": 90,
    },
    "instability_boost": {
        "boost_scale": 0.02,  # per °F instability
    },
}


class ConsensusWindGUI:
    """GUI for pattern-based consensus wind tool."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Populate Consensus Wind")
        self.master.geometry("1200x800")
        self.master.resizable(True, True)

        self.model_vars: Dict[str, tk.StringVar] = {}
        self.model_info: Dict[str, Dict] = {}
        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Pattern-Based Consensus Wind",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Consensus direction + Agreement-weighted magnitude",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 15))

        # Create two-column layout
        content_frame = tk.Frame(main)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Left column
        left_column = tk.Frame(content_frame)
        left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Right column
        right_column = tk.Frame(content_frame)
        right_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # Left column: Model Selection and Strategy Selection
        self._build_model_frame(left_column)
        self._build_strategy_frame(left_column)

        # Right column: Boost and Output Options
        self._build_boost_frame(right_column)
        self._build_output_frame(right_column)

        # Buttons at bottom
        self._build_buttons(main)

        self._update_selection()

    def _build_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Select Models for Consensus", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame, text="Select models and number of runs (depth) to include",
                 font=("Arial", 9), fg="gray").pack(anchor=tk.W, pady=(0, 5))

        # Grid header
        header = tk.Frame(frame)
        header.pack(fill=tk.X, pady=2)
        tk.Label(header, text="Model", width=25, anchor="w", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        tk.Label(header, text="Runs", width=10, anchor="w", font=("Arial", 9, "bold")).pack(side=tk.LEFT)

        for alias, display_name, run_count in CONSENSUS_MODELS:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=2)

            var = tk.StringVar(value="Yes" if alias in ["GFS", "ECMWF"] else "No")
            var.trace("w", lambda *args: self._update_selection())
            
            # Default to 1 run, max available from config
            runs_var = tk.IntVar(value=1)
            
            self.model_vars[alias] = var
            self.model_info[alias] = {
                "displayName": display_name, 
                "maxRuns": run_count,
                "runsVar": runs_var
            }

            # Checkbox
            tk.Checkbutton(row, text=f"{display_name} ({alias})",
                           variable=var, onvalue="Yes", offvalue="No",
                           font=("Arial", 10), width=25, anchor="w").pack(side=tk.LEFT)

            # Runs spinner
            tk.Spinbox(row, from_=1, to=4, textvariable=runs_var, width=3).pack(side=tk.LEFT)

        self.status_label = tk.Label(frame, text="", font=("Arial", 11, "bold"))
        self.status_label.pack(pady=(10, 0))

    def _build_strategy_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Magnitude Strategy", padx=15, pady=10)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        tk.Label(frame, text="How to combine individual model wind speeds:",
                 font=("Arial", 9), fg="gray").pack(anchor=tk.W, pady=(0, 5))

        self.mag_strategy = tk.StringVar(value="Spread-Adjusted")

        strategies_info = [
            ("Mean", "Simple average of all models"),
            ("Median", "Middle value, ignores outliers"),
            ("Maximum", "Highest model speed"),
            ("90th Percentile", "Reasonable worst case"),
            ("Spread-Adjusted", "Mean plus uncertainty padding"),
        ]

        for strategy, description in strategies_info:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=0)
            tk.Radiobutton(row, text=strategy, variable=self.mag_strategy,
                           value=strategy, font=("Arial", 9, "bold")).pack(side=tk.LEFT)
            tk.Label(row, text=f"- {description}",
                     font=("Arial", 8), fg="darkblue").pack(side=tk.LEFT, padx=(5, 0))

    def _build_boost_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Instability Boost (applies to all strategies)", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.enable_boost = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Enable instability-based wind boost",
                       variable=self.enable_boost).pack(anchor=tk.W)
        tk.Label(frame, text="Boosts winds where SST/Surface T > Air Temp (cold air over warm water). Uses surface T if SST unavailable.",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W)

        row = tk.Frame(frame)
        row.pack(fill=tk.X, pady=(5, 0))
        tk.Label(row, text="Max Boost:", width=12).pack(side=tk.LEFT)
        self.max_boost = tk.DoubleVar(value=float(CONFIG["gui_defaults"]["max_boost"]))
        tk.Scale(row, from_=0.10, to=0.40, resolution=0.05, orient=tk.HORIZONTAL,
                 variable=self.max_boost, length=150).pack(side=tk.LEFT)
        tk.Label(row, text="(25% = 0.25)", font=("Arial", 8)).pack(side=tk.LEFT)

    def _build_output_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Output Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.apply_smoothing = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Apply spatial smoothing",
                       variable=self.apply_smoothing).pack(anchor=tk.W)

        self.smoothing_passes = tk.IntVar(value=int(CONFIG["gui_defaults"]["smoothing_passes"]))
        row = tk.Frame(frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Smoothing passes:", width=15).pack(side=tk.LEFT)
        tk.Scale(row, from_=1, to=5, orient=tk.HORIZONTAL,
                 variable=self.smoothing_passes, length=150).pack(side=tk.LEFT)

        self.create_diagnostics = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Create diagnostic grids (PatternAgreement, ModelWeights)",
                       variable=self.create_diagnostics).pack(anchor=tk.W, pady=(10, 0))

        self.create_gusts = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Also create WindGust grid",
                       variable=self.create_gusts).pack(anchor=tk.W)

        self.gust_multiplier = tk.DoubleVar(value=float(CONFIG["gui_defaults"]["gust_multiplier"]))
        row2 = tk.Frame(frame)
        row2.pack(fill=tk.X)
        tk.Label(row2, text="Gust multiplier:", width=15).pack(side=tk.LEFT)
        tk.Scale(row2, from_=1.0, to=2.0, resolution=0.05, orient=tk.HORIZONTAL,
                 variable=self.gust_multiplier, length=150).pack(side=tk.LEFT)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(frame, text="Build Consensus Wind", command=self._run,
                  bg="lightgreen", font=("Arial", 11, "bold"), width=20).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _update_selection(self):
        model_count = sum(1 for v in self.model_vars.values() if v.get() == "Yes")
        
        # Calculate total "opinions" = models × runs
        total_opinions = 0
        for alias, v in self.model_vars.items():
            if v.get() == "Yes":
                runs = self.model_info[alias]["runsVar"].get()
                total_opinions += runs
        
        if model_count == 0:
            self.status_label.config(text="No Models Selected", fg="red")
        elif total_opinions < 2:
            self.status_label.config(text="Need at least 2 total runs for consensus", fg="orange")
        else:
            self.status_label.config(
                text=f"{model_count} model(s), {total_opinions} runs total ✓", 
                fg="green"
            )

    def _run(self):
        selected = {}
        for alias, v in self.model_vars.items():
            if v.get() == "Yes":
                info = self.model_info[alias]
                # Store runs count in the info dict
                selected[alias] = {
                    "displayName": info["displayName"],
                    "runs": info["runsVar"].get()
                }

        # Check total runs >= 2 for meaningful consensus
        total_runs = sum(info["runs"] for info in selected.values())
        if total_runs < 2:
            self.status_label.config(text="ERROR: Need at least 2 total runs!", fg="red")
            return

        self.callback({
            "selected_models": selected,
            "mag_strategy": self.mag_strategy.get(),
            "enable_boost": self.enable_boost.get(),
            "max_boost": self.max_boost.get(),
            "apply_smoothing": self.apply_smoothing.get(),
            "smoothing_passes": self.smoothing_passes.get(),
            "create_diagnostics": self.create_diagnostics.get(),
            "create_gusts": self.create_gusts.get(),
            "gust_multiplier": self.gust_multiplier.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Pattern-based consensus wind procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.output_log: List[str] = []

    def log(self, message: str):
        print(message)
        self.output_log.append(message)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        self.output_log = []

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                self.statusBarMsg("Tool cancelled", "S")
                return

        selected_models = varDict["selected_models"]
        mag_strategy = varDict.get("mag_strategy", "Spread-Adjusted")
        enable_boost = varDict["enable_boost"]
        max_boost = varDict["max_boost"]
        apply_smoothing = varDict["apply_smoothing"]
        smoothing_passes = varDict["smoothing_passes"]
        create_diagnostics = varDict["create_diagnostics"]
        create_gusts = varDict["create_gusts"]
        gust_multiplier = varDict["gust_multiplier"]

        # Guard against removed/legacy strategy names.
        if mag_strategy not in MAG_STRATEGIES:
            mag_strategy = "Spread-Adjusted"

        self.log("=" * 70)
        self.log("PATTERN-BASED CONSENSUS WIND")
        self.log("=" * 70)
        
        # Show model/run configuration
        total_runs = sum(info.get("runs", 1) for info in selected_models.values())
        model_list = [f"{alias}({info.get('runs', 1)} runs)" for alias, info in selected_models.items()]
        self.log(f"Models: {', '.join(model_list)}")
        self.log(f"Total ensemble members: {total_runs}")
        self.log(f"Magnitude Strategy: {mag_strategy}")

        # Validate models
        valid_models = self._validate_models(selected_models, timeRange)
        total_valid_runs = sum(info.get("runs", 1) for info in valid_models.values())
        if total_valid_runs < 2:
            self.statusBarMsg("Need at least 2 total runs for consensus", "S")
            return

        # Note: SST/temperature grids will be fetched per grid time if boosting enabled

        # Get forecast grid times
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not gridinfos:
            self.statusBarMsg("No Wind grids found", "S")
            return

        total = len(gridinfos)
        
        # Cache for winds from previous times (keyed by (alias, run_depth))
        wind_cache: Dict[Tuple[str, int], Tuple[np.ndarray, np.ndarray]] = {}

        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{total}", "R")
            self.log(f"\nPeriod {i+1}/{total}: {grid_tr}")

            # Collect wind data from all models (including multiple runs)
            model_winds, updated_cache = self._collect_model_winds(valid_models, grid_tr, wind_cache)
            wind_cache.update(updated_cache)  # Update cache with successfully retrieved winds
            if len(model_winds) < 2:
                self.log(f"  Insufficient data: only {len(model_winds)} runs available")
                continue
            self.log(f"  Collected {len(model_winds)} ensemble members: {list(model_winds.keys())}")

            # Calculate CONSENSUS PATTERN (direction)
            consensus_dir, dir_agreement = self._calc_consensus_direction(model_winds)
            self.log(f"  Pattern agreement: {np.mean(dir_agreement):.1f}%")

            # Calculate the supported magnitude strategies (and optionally create
            # diagnostics for them). Pattern/feature/spatial strategies were removed
            # from the UI because they can introduce discontinuities.
            all_strategies = {}
            
            # Mean
            mean_mag = self._calc_mean_magnitude(model_winds)
            all_strategies["Mean"] = mean_mag
            self.log("  Calculated: Mean")
            
            # Median
            median_mag = self._calc_median_magnitude(model_winds)
            all_strategies["Median"] = median_mag
            self.log("  Calculated: Median")
            
            # Maximum
            max_mag = self._calc_max_magnitude(model_winds)
            all_strategies["Maximum"] = max_mag
            self.log("  Calculated: Maximum")
            
            # 90th Percentile
            p90_mag = self._calc_percentile_magnitude(model_winds, 90)
            all_strategies["90thPercentile"] = p90_mag
            self.log("  Calculated: 90th Percentile")
            
            # Spread-Adjusted (Mean + spread × factor)
            spread_adjusted_mag = self._calc_spread_adjusted(
                model_winds,
                spread_factor=CONFIG["spread_adjusted"]["spread_factor"],
            )
            all_strategies["SpreadAdjusted"] = spread_adjusted_mag
            self.log("  Calculated: Spread-Adjusted")

            # Apply instability boost if enabled (for all strategies and diagnostic grids)
            if enable_boost:
                sst_grid = self._get_sst_grid(grid_tr, valid_models)
                if sst_grid is not None:
                    air_temp = self._get_air_temp(valid_models, grid_tr)
                    if air_temp is not None:
                        # Apply boost to all diagnostic grids
                        for key in all_strategies:
                            all_strategies[key] = self._apply_instability_boost(
                                all_strategies[key], sst_grid, air_temp, max_boost
                            )
                        self.log("  Applied instability boost to all magnitude strategies")

            # Select the final magnitude based on chosen strategy
            strategy_map = {
                "Mean": "Mean",
                "Median": "Median",
                "Maximum": "Maximum",
                "90th Percentile": "90thPercentile",
                "Spread-Adjusted": "SpreadAdjusted",
            }
            final_mag = all_strategies[strategy_map[mag_strategy]]
            self.log(f"  Using strategy: {mag_strategy} for final Wind grid")

            # Apply smoothing if requested
            if apply_smoothing:
                # Get sigma from thresholds (default 0.7 if not available)
                try:
                    sigma = smoothing_passes * thresholds.SMOOTHING_DEFAULTS.get("sigma", 0.7)
                except AttributeError:
                    sigma = smoothing_passes * 0.7
                final_mag = ndimage.gaussian_filter(final_mag, sigma=sigma, mode="nearest")
                consensus_dir = ndimage.gaussian_filter(consensus_dir, sigma=sigma, mode="nearest")
                # Also smooth diagnostic grids
                for key in all_strategies:
                    all_strategies[key] = ndimage.gaussian_filter(all_strategies[key], sigma=sigma, mode="nearest")

            # Ensure valid ranges
            final_mag = np.clip(final_mag, 0, 150)
            consensus_dir = np.mod(consensus_dir, 360)
            
            # Clip all diagnostic grids
            for key in all_strategies:
                all_strategies[key] = np.clip(all_strategies[key], 0, 150)

            # Create Wind grid using selected strategy
            self.createGrid("Fcst", "Wind", "VECTOR", (final_mag, consensus_dir), grid_tr)
            self.log(f"  Wind: {np.mean(final_mag):.1f} kt mean, max {np.max(final_mag):.1f} kt")

            # Create WindGust if requested
            if create_gusts:
                gust = np.clip(final_mag * gust_multiplier, 0, 150)
                self.createGrid("Fcst", "WindGust", "SCALAR", gust, grid_tr)
                self.log(f"  Gust: {np.mean(gust):.1f} kt mean")

            # Create diagnostic grids for all magnitude strategies
            if create_diagnostics:
                # Map strategy names to valid element names (no underscores allowed)
                element_name_map = {
                    "Mean": "WindMagMean",
                    "Median": "WindMagMedian",
                    "Maximum": "WindMagMaximum",
                    "90thPercentile": "WindMag90thPercentile",
                    "SpreadAdjusted": "WindMagSpreadAdjusted",
                }
                
                for strategy_name, strategy_mag in all_strategies.items():
                    element_name = element_name_map.get(strategy_name, f"WindMag{strategy_name}")
                    try:
                        self.createGrid(
                            "Fcst",
                            element_name,
                            "SCALAR",
                            strategy_mag,
                            grid_tr,
                            minAllowedValue=0.0,
                            maxAllowedValue=125.0
                        )
                        # Set display rules for all diagnostic grids
                        try:
                            self.setActiveElement(
                                "Fcst",
                                element_name,
                                "SFC",
                                grid_tr,
                                "/GFE/Beaufort_Winds",
                                (0.0, 125.0),
                                0
                            )
                        except Exception as e:
                            # If setActiveElement fails, log but continue
                            self.log(f"  Warning: Could not set display rules for {element_name}: {e}")
                        self.log(f"  Diagnostic: {element_name} (mean {np.mean(strategy_mag):.1f} kt)")
                    except Exception as e:
                        self.log(f"  Warning: Could not create diagnostic grid {element_name}: {e}")

        self.log("\n" + "=" * 70)
        self.log("Complete")
        self.statusBarMsg("Consensus Wind complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = ConsensusWindGUI(root, callback)
        root.mainloop()
        return result[0]

    def _validate_models(self, selected_models: Dict, timeRange) -> Dict:
        """Check which models have data."""
        valid = {}
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not gridinfos:
            return valid

        test_tr = gridinfos[0].gridTime()

        for alias, info in selected_models.items():
            wind = grid_fetch.get_vector_grid(
                self, alias, "Wind", "SFC", test_tr,
                run_depth=1, noDataError=0
            )
            if wind is not None:
                valid[alias] = info
                self.log(f"  ✓ {alias} has data")
            else:
                self.log(f"  ✗ {alias} no data")

        return valid

    def _collect_model_winds(self, valid_models: Dict, grid_tr, 
                             wind_cache: Dict[Tuple[str, int], Tuple[np.ndarray, np.ndarray]]
                             ) -> Tuple[Dict[str, Tuple[np.ndarray, np.ndarray]], 
                                       Dict[Tuple[str, int], Tuple[np.ndarray, np.ndarray]]]:
        """
        Collect wind data from all valid models, including multiple runs per model.
        
        Each run is treated as a separate "model opinion" in the consensus.
        E.g., GFS with 2 runs becomes "GFS_run1" and "GFS_run2" in the dictionary.
        
        Only uses the exact requested run_depth. If a grid is missing for the current time,
        fills in with the most recent available grid from previous times at the same run_depth.
        
        Args:
            valid_models: Dictionary of valid model configurations
            grid_tr: Time range for the current grid
            wind_cache: Cache of winds from previous times, keyed by (alias, run_depth)
        
        Returns:
            Tuple of (winds dictionary for current time, updated cache with new successful retrievals)
        """
        winds = {}
        updated_cache = {}
        
        for alias, info in valid_models.items():
            num_runs = info.get("runs", 1)  # Default to 1 run if not specified
            
            for run_offset in range(num_runs):
                run_depth = run_offset + 1  # 1 = current, 2 = previous, etc.
                cache_key = (alias, run_depth)
                
                # Try to get the grid for the requested run depth only
                wind = grid_fetch.get_vector_grid(
                    self, alias, "Wind", "SFC", grid_tr,
                    run_depth=run_depth, noDataError=0
                )
                
                # If missing, try to fill in from cache (previous times at same run_depth)
                if wind is None:
                    if cache_key in wind_cache:
                        wind = wind_cache[cache_key]
                        self.log(f"  {alias} run{run_depth}: using cached grid from previous time")
                    else:
                        # No cache available, skip this run
                        continue
                else:
                    # Successfully retrieved - add to updated cache for future use
                    updated_cache[cache_key] = wind
                
                # Create unique key for each run
                if num_runs > 1:
                    key = f"{alias}_run{run_depth}"
                else:
                    key = alias
                winds[key] = wind
                    
        return winds, updated_cache

    def _calc_consensus_direction(self, model_winds: Dict) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calculate consensus direction using circular mean.
        
        Returns:
            consensus_dir: Consensus direction (degrees)
            agreement: Agreement score (0-100%) based on circular variance
        """
        dirs = [wind[1] for wind in model_winds.values()]
        dir_array = np.array(dirs)

        # Circular mean
        dir_rad = np.radians(dir_array)
        mean_cos = np.mean(np.cos(dir_rad), axis=0)
        mean_sin = np.mean(np.sin(dir_rad), axis=0)
        consensus_dir = np.degrees(np.arctan2(mean_sin, mean_cos))
        consensus_dir = np.where(consensus_dir < 0, consensus_dir + 360, consensus_dir)

        # Calculate agreement (R = resultant length, 1 = perfect agreement)
        R = np.sqrt(mean_cos**2 + mean_sin**2)
        agreement = R * 100  # Convert to percentage

        return consensus_dir, agreement

    def _calc_mean_magnitude(self, model_winds: Dict) -> np.ndarray:
        """Simple mean of all model magnitudes."""
        mags = [wind[0] for wind in model_winds.values()]
        return np.mean(np.array(mags), axis=0)

    def _calc_max_magnitude(self, model_winds: Dict) -> np.ndarray:
        """Maximum of all model magnitudes (conservative)."""
        mags = [wind[0] for wind in model_winds.values()]
        return np.max(np.array(mags), axis=0)

    def _calc_median_magnitude(self, model_winds: Dict) -> np.ndarray:
        """Median of all model magnitudes (robust to outliers)."""
        mags = [wind[0] for wind in model_winds.values()]
        return np.median(np.array(mags), axis=0)

    def _calc_percentile_magnitude(self, model_winds: Dict, percentile: float) -> np.ndarray:
        """Calculate percentile magnitude (e.g., 90th for reasonable worst case)."""
        mags = [wind[0] for wind in model_winds.values()]
        return np.percentile(np.array(mags), percentile, axis=0)

    def _calc_spread_adjusted(self, model_winds: Dict, spread_factor: float | None = None) -> np.ndarray:
        """
        SPREAD-ADJUSTED: Mean + (Standard Deviation × Factor).
        
        Dynamically pads the forecast based on model uncertainty:
        - Where models agree (low spread): stays close to mean
        - Where models disagree (high spread): increases wind to capture risk
        
        Args:
            model_winds: Dictionary of model wind data
            spread_factor: Multiplier for spread (defaults to CONFIG)
        
        Returns:
            Spread-adjusted magnitude
        """
        if spread_factor is None:
            spread_factor = CONFIG["spread_adjusted"]["spread_factor"]
        mags = [wind[0] for wind in model_winds.values()]
        mag_array = np.array(mags)
        
        mean_mag = np.mean(mag_array, axis=0)
        std_mag = np.std(mag_array, axis=0)
        
        # Add uncertainty padding proportional to spread
        adjusted_mag = mean_mag + (std_mag * spread_factor)
        
        # Log spread statistics
        avg_spread = np.mean(std_mag)
        avg_padding = np.mean(std_mag * spread_factor)
        self.log(f"  Spread-Adjusted: avg spread {avg_spread:.1f} kt, avg padding +{avg_padding:.1f} kt")
        
        return adjusted_mag

    def _calc_pattern_weighted_magnitude(self, model_winds: Dict, consensus_dir: np.ndarray,
                                          tolerance: float, decay: float) -> np.ndarray:
        """
        Weight model magnitudes by how well their direction agrees with consensus.
        
        Models with directions close to consensus get higher weight.
        """
        weighted_sum = np.zeros_like(consensus_dir)
        weight_sum = np.zeros_like(consensus_dir)

        for alias, (mag, direction) in model_winds.items():
            # Calculate angular difference from consensus
            diff = np.abs(direction - consensus_dir)
            diff = np.minimum(diff, 360 - diff)  # Handle wrap-around

            # Calculate weight: full weight within tolerance, decay outside
            # Weight = 1.0 for diff <= tolerance
            # Weight decays exponentially for diff > tolerance
            weight = np.where(
                diff <= tolerance,
                1.0,
                np.exp(
                    -decay * (diff - tolerance) / CONFIG["pattern_weighted"]["decay_scale_deg"]
                ),
            )

            weighted_sum += mag * weight
            weight_sum += weight

        # Avoid division by zero
        weight_sum = np.maximum(weight_sum, 0.001)
        return weighted_sum / weight_sum

    def _calc_confidence_weighted_magnitude(self, model_winds: Dict) -> np.ndarray:
        """
        Weight magnitudes by inverse of spread (models clustered together get more weight).
        """
        mags = [wind[0] for wind in model_winds.values()]
        mag_array = np.array(mags)

        # Calculate local spread (std dev)
        spread = np.std(mag_array, axis=0)

        # Weight = inverse of distance from mean (normalized)
        mean_mag = np.mean(mag_array, axis=0)
        weighted_sum = np.zeros_like(mean_mag)
        weight_sum = np.zeros_like(mean_mag)

        for mag in mags:
            # Distance from mean
            dist = np.abs(mag - mean_mag)
            # Weight = inverse of distance (with smoothing to avoid division by zero)
            # Models closer to mean get higher weight
            weight = 1.0 / (1.0 + dist / (spread + 0.1))
            weighted_sum += mag * weight
            weight_sum += weight

        weight_sum = np.maximum(weight_sum, 0.001)
        return weighted_sum / weight_sum

    def _calc_pattern_matched_max(self, model_winds: Dict, consensus_dir: np.ndarray,
                                   tolerance: float) -> Tuple[np.ndarray, np.ndarray]:
        """
        PATTERN-MATCHED MAXIMUM: Take maximum speed from models that agree with consensus direction.
        
        This preserves strong features (fronts, jets, gradients) while still using 
        pattern consensus to filter out outlier models.
        
        Logic:
        1. For each grid point, find models within direction tolerance of consensus
        2. Take the MAXIMUM speed from those agreeing models
        3. If no models agree (rare), fall back to the model closest to consensus
        
        Returns:
            final_mag: Maximum speed from agreeing models
            agreeing_count: Number of models that agreed at each point
        """
        sample_shape = next(iter(model_winds.values()))[0].shape
        final_mag = np.zeros(sample_shape)
        agreeing_count = np.zeros(sample_shape)

        # For each model, check if it agrees with consensus
        agreeing_mags = []
        for alias, (mag, direction) in model_winds.items():
            # Calculate angular difference from consensus
            diff = np.abs(direction - consensus_dir)
            diff = np.minimum(diff, 360 - diff)  # Handle wrap-around

            # Mark where this model agrees
            agrees = diff <= tolerance
            
            # Create masked magnitude (0 where doesn't agree)
            masked_mag = np.where(agrees, mag, -999)
            agreeing_mags.append((masked_mag, agrees))
            
        # Stack all agreeing magnitudes
        mag_stack = np.array([m[0] for m in agreeing_mags])
        agree_stack = np.array([m[1] for m in agreeing_mags])
        
        # Count how many models agree at each point
        agreeing_count = np.sum(agree_stack, axis=0)
        
        # Take maximum where at least one model agrees
        # Use -999 masking: max will pick real values over -999
        max_agreeing = np.max(mag_stack, axis=0)
        
        # Where at least one model agrees, use max of agreeing models
        has_agreement = agreeing_count >= 1
        
        # Fallback for no agreement: use mean of all models
        all_mags = np.array([wind[0] for wind in model_winds.values()])
        mean_fallback = np.mean(all_mags, axis=0)
        
        final_mag = np.where(has_agreement, max_agreeing, mean_fallback)
        
        return final_mag, agreeing_count

    def _calc_feature_preserving(self, model_winds: Dict, consensus_dir: np.ndarray,
                                  tolerance: float) -> np.ndarray:
        """
        FEATURE-PRESERVING BLEND: Preserve local wind maxima from individual models.
        
        This method:
        1. Identifies "features" (local maxima) in each model's wind field
        2. At feature points, uses the maximum model value
        3. At non-feature points, uses pattern-weighted blend
        
        This preserves fronts, jets, and gradients while still blending background flow.
        """
        sample_shape = next(iter(model_winds.values()))[0].shape
        
        # Get all magnitudes
        all_mags = [wind[0] for wind in model_winds.values()]
        mag_array = np.array(all_mags)
        
        # Calculate mean and max
        mean_mag = np.mean(mag_array, axis=0)
        max_mag = np.max(mag_array, axis=0)
        
        # Identify "feature" regions where max exceeds mean significantly
        # These are areas with strong gradients/fronts that we want to preserve
        feature_threshold = CONFIG["feature_preserving"]["feature_threshold"]
        feature_mask = max_mag > (mean_mag * feature_threshold)
        
        # Also identify local maxima using gradient analysis
        # Smooth first to reduce noise
        smoothed_max = ndimage.gaussian_filter(max_mag, sigma=1.0, mode="nearest")
        
        # Calculate local gradient magnitude
        grad_y, grad_x = np.gradient(smoothed_max)
        grad_mag = np.sqrt(grad_x**2 + grad_y**2)
        
        # Areas with high gradient are frontal zones - preserve these
        if np.any(grad_mag > 0):
            gradient_threshold = np.percentile(
                grad_mag[grad_mag > 0],
                CONFIG["feature_preserving"]["gradient_percentile"],
            )
            gradient_mask = grad_mag > gradient_threshold
        else:
            gradient_mask = np.zeros(sample_shape, dtype=bool)
        
        # Combine masks: preserve both strong features AND gradient zones
        preserve_mask = feature_mask | gradient_mask
        
        # For non-feature areas, use pattern-weighted blend
        # (simplified version - just use mean for background)
        background_mag = mean_mag
        
        # For feature areas, use the max from agreeing models
        mags_list = list(model_winds.values())
        agreeing_max = np.zeros(sample_shape)
        
        for alias, (mag, direction) in model_winds.items():
            diff = np.abs(direction - consensus_dir)
            diff = np.minimum(diff, 360 - diff)
            agrees = diff <= tolerance
            # Only consider agreeing models for max
            candidate = np.where(agrees, mag, 0)
            agreeing_max = np.maximum(agreeing_max, candidate)
        
        # Where no models agree, use regular max
        no_agreement = agreeing_max == 0
        agreeing_max = np.where(no_agreement, max_mag, agreeing_max)
        
        # Final blend: preserve features, use background elsewhere
        final_mag = np.where(preserve_mask, agreeing_max, background_mag)
        
        # Log feature preservation stats
        feature_pct = np.sum(preserve_mask) / preserve_mask.size * 100
        self.log(f"  Preserving features in {feature_pct:.1f}% of domain")
        
        return final_mag

    def _calc_pattern_blended(self, model_winds: Dict, consensus_dir: np.ndarray,
                              consensus_mag: np.ndarray, tolerance: float) -> np.ndarray:
        """
        PATTERN-BLENDED: Blend spatial patterns from all models, then match consensus magnitude.
        
        Solves the problem where models agree on magnitude but disagree on spatial placement.
        
        Method:
        1. Convert each model's wind to u/v components (spatial pattern)
        2. Create weighted blend of u/v components (models with better direction agreement
           get higher weight)
        3. Convert blended u/v back to magnitude/direction
        4. Scale the blended magnitude to match consensus magnitude while preserving
           the blended spatial pattern
        
        This creates a wind field that:
        - Has a blended spatial pattern from all models (smooths out placement disagreements)
        - Matches the consensus magnitude (models agree on "how much" wind)
        - Preserves the blended direction pattern
        
        Returns:
            final_mag: Blended magnitude scaled to match consensus
        """
        sample_shape = next(iter(model_winds.values()))[0].shape
        
        # Convert all winds to u/v components for blending
        u_components = []
        v_components = []
        weights = []
        
        for alias, (mag, direction) in model_winds.items():
            # Calculate angular difference from consensus direction
            diff = np.abs(direction - consensus_dir)
            diff = np.minimum(diff, 360 - diff)  # Handle wrap-around
            
            # Weight by direction agreement (models closer to consensus get higher weight)
            # Full weight within tolerance, exponential decay outside
            weight = np.where(
                diff <= tolerance,
                1.0,
                np.exp(-(diff - tolerance) / 45.0)  # Decay factor
            )
            
            # Convert to u/v components
            dir_rad = np.radians(direction)
            u = mag * np.sin(dir_rad)  # u = speed * sin(direction) [eastward]
            v = mag * np.cos(dir_rad)  # v = speed * cos(direction) [northward]
            
            u_components.append(u)
            v_components.append(v)
            weights.append(weight)
        
        # Stack into arrays
        u_array = np.array(u_components)
        v_array = np.array(v_components)
        weight_array = np.array(weights)
        
        # Weighted blend of u/v components (spatial pattern blending)
        # Normalize weights
        weight_sum = np.sum(weight_array, axis=0)
        weight_sum = np.maximum(weight_sum, 0.001)  # Avoid division by zero
        normalized_weights = weight_array / weight_sum[np.newaxis, :, :]
        
        # Blend u and v components
        blended_u = np.sum(u_array * normalized_weights, axis=0)
        blended_v = np.sum(v_array * normalized_weights, axis=0)
        
        # Convert blended u/v back to magnitude and direction
        blended_mag = np.sqrt(blended_u**2 + blended_v**2)
        blended_dir = np.degrees(np.arctan2(blended_u, blended_v))
        blended_dir = np.where(blended_dir < 0, blended_dir + 360, blended_dir)
        
        # Scale the blended magnitude to match consensus magnitude
        # This preserves the blended spatial pattern but uses consensus magnitude
        # Scale factor = consensus_mag / blended_mag (with safety checks)
        scale_factor = np.where(
            blended_mag > 0.1,  # Avoid division by very small numbers
            consensus_mag / blended_mag,
            1.0  # No scaling if blended magnitude is too small
        )
        
        # Apply scaling to preserve pattern but match magnitude
        final_mag = blended_mag * scale_factor
        
        # Log blending statistics
        avg_weight = np.mean(weight_array)
        self.log(f"  Pattern blending: avg weight {avg_weight:.2f}, scale factor range {np.min(scale_factor):.2f}-{np.max(scale_factor):.2f}")
        
        return final_mag

    def _calc_spatial_consensus(self, model_winds: Dict) -> np.ndarray:
        """
        SPATIAL-CONSENSUS: Finds centroid of wind maxima locations, places 90th percentile magnitude there.
        
        Solves the problem where models agree on magnitude but disagree on location.
        For example: Both models show 65 kt winds, but 300 miles apart. This strategy
        finds the centroid (middle point) and places the 90th percentile winds there, creating
        a single consensus location for the storm.
        
        Method:
        1. For each model, find locations where winds exceed a threshold (e.g., 80% of max)
        2. Calculate the centroid of these locations (weighted by magnitude)
        3. Create a distance-weighted field: strongest winds at centroid, decreasing with distance
        4. Use 90th percentile magnitude (reasonable worst case) instead of absolute maximum
        
        Args:
            model_winds: Dictionary of model wind data
        
        Returns:
            Spatial consensus magnitude (single location with max magnitude)
        """
        sample_shape = next(iter(model_winds.values()))[0].shape
        ny, nx = sample_shape
        
        # Get all magnitudes
        mags = [wind[0] for wind in model_winds.values()]
        mag_array = np.array(mags)
        
        percentile_mag = np.percentile(
            mag_array,
            CONFIG["spatial_consensus"]["percentile"],
            axis=0,
        )
        global_percentile = np.max(percentile_mag)
        
        if global_percentile < 1.0:  # No significant winds
            return percentile_mag
        
        # For each model, find locations of significant winds (above threshold)
        threshold_factor = CONFIG["spatial_consensus"]["significant_fraction"]
        centroid_locations = []
        centroid_weights = []
        
        for mag in mags:
            model_max = np.max(mag)
            if model_max < 1.0:
                continue
            
            threshold = model_max * threshold_factor
            significant_mask = mag >= threshold
            
            # Find centroid of significant winds (weighted by magnitude)
            if np.any(significant_mask):
                # Create coordinate grids
                y_coords, x_coords = np.meshgrid(np.arange(ny), np.arange(nx), indexing='ij')
                
                # Weight by magnitude
                weights = mag * significant_mask.astype(float)
                total_weight = np.sum(weights)
                
                if total_weight > 0:
                    centroid_y = np.sum(y_coords * weights) / total_weight
                    centroid_x = np.sum(x_coords * weights) / total_weight
                    centroid_locations.append((centroid_y, centroid_x))
                    centroid_weights.append(model_max)  # Weight by model's max magnitude
        
        if not centroid_locations:
            # Fallback: use mean magnitude
            return np.mean(mag_array, axis=0)
        
        # Calculate overall centroid (weighted average of model centroids)
        centroid_weights = np.array(centroid_weights)
        total_weight = np.sum(centroid_weights)
        
        if total_weight > 0:
            centroid_y = np.sum([loc[0] * w for loc, w in zip(centroid_locations, centroid_weights)]) / total_weight
            centroid_x = np.sum([loc[1] * w for loc, w in zip(centroid_locations, centroid_weights)]) / total_weight
        else:
            # Fallback: simple average
            centroid_y = np.mean([loc[0] for loc in centroid_locations])
            centroid_x = np.mean([loc[1] for loc in centroid_locations])
        
        # Create distance-weighted field
        # Winds are strongest at centroid, decrease with distance
        y_coords, x_coords = np.meshgrid(np.arange(ny), np.arange(nx), indexing='ij')
        
        # Distance from centroid (in grid points)
        dist_y = y_coords - centroid_y
        dist_x = x_coords - centroid_x
        distance = np.sqrt(dist_x**2 + dist_y**2)
        
        # Calculate decay radius: make it more compact/focused
        if len(centroid_locations) > 1:
            # Find max distance between any two centroids
            max_dist = 0
            for i, loc1 in enumerate(centroid_locations):
                for loc2 in centroid_locations[i+1:]:
                    dist = np.sqrt((loc1[0] - loc2[0])**2 + (loc1[1] - loc2[1])**2)
                    max_dist = max(max_dist, dist)
            decay_radius = min(
                max(
                    max_dist * CONFIG["spatial_consensus"]["decay_fraction"],
                    CONFIG["spatial_consensus"]["decay_min"],
                ),
                CONFIG["spatial_consensus"]["decay_max"],
            )
        else:
            decay_radius = CONFIG["spatial_consensus"]["single_decay"]
        
        # Create distance-weighted magnitude field
        # Gaussian decay: exp(-0.5 * (distance / radius)^2)
        # At centroid: magnitude = 90th percentile (reasonable worst case)
        # At decay_radius: magnitude ≈ 0.6 * percentile
        # At 2*decay_radius: magnitude ≈ 0.14 * percentile
        weight = np.exp(-0.5 * (distance / decay_radius)**2)
        
        # Combine with background: use mean magnitude as base, add percentile boost at centroid
        mean_mag = np.mean(mag_array, axis=0)
        consensus_mag = mean_mag + (global_percentile - mean_mag) * weight
        
        # Log centroid statistics
        self.log(f"  Spatial-Consensus: centroid at ({centroid_y:.1f}, {centroid_x:.1f}), "
                 f"90th percentile {global_percentile:.1f} kt, decay radius {decay_radius:.1f} pts")
        
        return consensus_mag

    def _calc_hybrid_consensus(self, model_winds: Dict, consensus_dir: np.ndarray,
                               tolerance: float) -> np.ndarray:
        """
        HYBRID CONSENSUS: Combines direction filtering + spatial consensus + flexible magnitude.
        
        This is the "best of all worlds" strategy that:
        1. Filters models by direction agreement (removes outliers)
        2. Finds centroid of wind maxima from agreeing models only
        3. Uses 90th percentile magnitude at consensus location (reasonable worst case)
        
        Solves the problem where:
        - Models agree on magnitude but disagree on location (spatial consensus)
        - Some models may have wrong directions (direction filtering)
        - You want a conservative but not extreme magnitude (90th percentile)
        
        Method:
        1. Filter models: only use models whose direction agrees with consensus (within tolerance)
        2. For agreeing models, find locations where winds exceed 80% of that model's maximum
        3. Calculate weighted centroid of these locations
        4. Use 90th percentile magnitude from agreeing models at the centroid
        5. Create distance-weighted field with Gaussian decay
        
        Args:
            model_winds: Dictionary of model wind data
            consensus_dir: Consensus direction (degrees)
            tolerance: Direction tolerance for agreement (degrees)
        
        Returns:
            Hybrid consensus magnitude (single location with 90th percentile magnitude)
        """
        sample_shape = next(iter(model_winds.values()))[0].shape
        ny, nx = sample_shape
        
        # Step 1: Filter models by direction agreement
        agreeing_winds = {}
        for alias, (mag, direction) in model_winds.items():
            # Calculate angular difference from consensus
            diff = np.abs(direction - consensus_dir)
            diff = np.minimum(diff, 360 - diff)  # Handle wrap-around
            
            # Check if model agrees with consensus direction
            # Use mean agreement across grid to determine if model is "agreeing"
            mean_agreement = np.mean(diff <= tolerance)
            
            # Include model if >50% of grid points agree
            if mean_agreement > 0.5:
                agreeing_winds[alias] = (mag, direction)
        
        if len(agreeing_winds) == 0:
            # Fallback: use all models if none agree
            agreeing_winds = model_winds
            self.log("  Hybrid Consensus: No models fully agree, using all models")
        else:
            self.log(f"  Hybrid Consensus: {len(agreeing_winds)}/{len(model_winds)} models agree on direction")
        
        # Step 2: Get magnitudes from agreeing models
        agreeing_mags = [wind[0] for wind in agreeing_winds.values()]
        mag_array = np.array(agreeing_mags)
        
        percentile_mag = np.percentile(
            mag_array,
            CONFIG["hybrid_consensus"]["percentile"],
            axis=0,
        )
        global_percentile = np.max(percentile_mag)
        
        if global_percentile < 1.0:  # No significant winds
            return percentile_mag
        
        threshold_factor = CONFIG["hybrid_consensus"]["significant_fraction"]
        centroid_locations = []
        centroid_weights = []
        
        for mag in agreeing_mags:
            model_max = np.max(mag)
            if model_max < 1.0:
                continue
            
            threshold = model_max * threshold_factor
            significant_mask = mag >= threshold
            
            if np.any(significant_mask):
                y_coords, x_coords = np.meshgrid(np.arange(ny), np.arange(nx), indexing='ij')
                weights = mag * significant_mask.astype(float)
                total_weight = np.sum(weights)
                
                if total_weight > 0:
                    centroid_y = np.sum(y_coords * weights) / total_weight
                    centroid_x = np.sum(x_coords * weights) / total_weight
                    centroid_locations.append((centroid_y, centroid_x))
                    centroid_weights.append(model_max)
        
        if not centroid_locations:
            # Fallback: use mean magnitude
            return np.mean(mag_array, axis=0)
        
        # Calculate overall centroid (weighted average)
        centroid_weights = np.array(centroid_weights)
        total_weight = np.sum(centroid_weights)
        
        if total_weight > 0:
            centroid_y = np.sum([loc[0] * w for loc, w in zip(centroid_locations, centroid_weights)]) / total_weight
            centroid_x = np.sum([loc[1] * w for loc, w in zip(centroid_locations, centroid_weights)]) / total_weight
        else:
            centroid_y = np.mean([loc[0] for loc in centroid_locations])
            centroid_x = np.mean([loc[1] for loc in centroid_locations])
        
        # Step 5: Create distance-weighted field with 90th percentile magnitude at centroid
        y_coords, x_coords = np.meshgrid(np.arange(ny), np.arange(nx), indexing='ij')
        dist_y = y_coords - centroid_y
        dist_x = x_coords - centroid_x
        distance = np.sqrt(dist_x**2 + dist_y**2)
        
        # Calculate decay radius: make it more compact/focused
        if len(centroid_locations) > 1:
            max_dist = 0
            for i, loc1 in enumerate(centroid_locations):
                for loc2 in centroid_locations[i+1:]:
                    dist = np.sqrt((loc1[0] - loc2[0])**2 + (loc1[1] - loc2[1])**2)
                    max_dist = max(max_dist, dist)
            decay_radius = min(
                max(
                    max_dist * CONFIG["spatial_consensus"]["decay_fraction"],
                    CONFIG["spatial_consensus"]["decay_min"],
                ),
                CONFIG["spatial_consensus"]["decay_max"],
            )
        else:
            decay_radius = CONFIG["spatial_consensus"]["single_decay"]
        
        # Gaussian decay weight
        weight = np.exp(-0.5 * (distance / decay_radius)**2)
        
        # Combine: use mean as base, add 90th percentile boost at centroid
        mean_mag = np.mean(mag_array, axis=0)
        hybrid_mag = mean_mag + (global_percentile - mean_mag) * weight
        
        # Log statistics
        self.log(f"  Hybrid Consensus: {len(agreeing_winds)} agreeing models, "
                 f"centroid at ({centroid_y:.1f}, {centroid_x:.1f}), "
                 f"90th percentile {global_percentile:.1f} kt")
        
        return hybrid_mag

    def _get_sst_grid(self, tr, valid_models: Dict) -> Optional[np.ndarray]:
        """Get SST grid from RTOFS or Fcst. Falls back to surface temperature if SST not available."""
        # Try to get actual SST first
        try:
            sst = grid_fetch.get_grid(self, "RTOFS", "SST", "SFC", tr, run_depth=2, noDataError=0)
            if sst is not None:
                # Convert from Kelvin if needed
                if np.nanmax(sst) > 200:
                    try:
                        sst_c = thresholds.k_to_c(sst)
                        sst = thresholds.c_to_f(sst_c)
                    except AttributeError:
                        sst_c = sst - 273.15
                        sst = sst_c * 9.0/5.0 + 32.0
                return sst
        except Exception:
            pass

        try:
            sst = self.getGrids("Fcst", "SST", "SFC", tr, mode="First", noDataError=0)
            if sst is not None:
                # Convert from Kelvin if needed
                if np.nanmax(sst) > 200:
                    try:
                        sst_c = thresholds.k_to_c(sst)
                        sst = thresholds.c_to_f(sst_c)
                    except AttributeError:
                        sst_c = sst - 273.15
                        sst = sst_c * 9.0/5.0 + 32.0
                return sst
        except Exception:
            pass

        # Fallback: use surface temperature from models as SST proxy
        self.log("  SST not available, using surface temperature as proxy")
        return self._get_air_temp(valid_models, tr)

    def _get_air_temp(self, valid_models: Dict, grid_tr) -> Optional[np.ndarray]:
        """Get average air temperature from models.

        For marine instability boosting we prefer **925 mb temperature** (T925) over
        surface temperature to better represent the low-level air mass over water.
        Falls back to MB1000/SFC if MB925 is unavailable.
        """
        temp_sum = None
        count = 0

        for alias in valid_models.keys():
            # Prefer 925 mb temperature. Try a few common element/level variants.
            temp = None
            for elem, level in (
                ("T", "MB925"),
                ("t", "MB925"),
                ("T", "MB1000"),
                ("t", "MB1000"),
                ("T", "SFC"),
                ("t", "SFC"),
            ):
                temp = grid_fetch.get_grid(
                    self, alias, elem, level, grid_tr, run_depth=1, noDataError=0
                )
                if temp is not None:
                    break

            if temp is not None:
                # Convert from Kelvin if needed
                if np.nanmax(temp) > 200:
                    try:
                        temp_c = thresholds.k_to_c(temp)
                        temp = thresholds.c_to_f(temp_c)
                    except AttributeError:
                        # Fallback: K to F conversion (K -> C -> F)
                        temp_c = temp - 273.15
                        temp = temp_c * 9.0/5.0 + 32.0

                if temp_sum is None:
                    temp_sum = temp.copy()
                else:
                    temp_sum += temp
                count += 1

        if count == 0:
            return None
        return temp_sum / count

    def _apply_instability_boost(self, mag: np.ndarray, sst: np.ndarray,
                                  air_temp: np.ndarray, max_boost: float) -> np.ndarray:
        """Apply instability-based wind boost."""
        # Instability = SST - Air Temp (positive = unstable)
        instability = sst - air_temp

        boost_scale = CONFIG["instability_boost"]["boost_scale"]
        boost_factor = np.clip(instability * boost_scale, 0.0, max_boost)

        boosted_mag = mag * (1.0 + boost_factor)

        # Log boost statistics
        boost_area = np.sum(boost_factor > 0) / boost_factor.size * 100
        if boost_area > 0:
            avg_boost = np.mean(boost_factor[boost_factor > 0]) * 100
            self.log(f"  Boost applied to {boost_area:.1f}% of grid, avg boost {avg_boost:.1f}%")

        return boosted_mag


__all__ = ["Procedure", "ConsensusWindGUI"]

