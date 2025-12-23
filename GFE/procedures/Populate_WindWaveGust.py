"""
Populate_WindWaveGust - Wind/Wave/Gust Unified Tool.

A comprehensive tool for marine wind and wave forecasting that:
- Blends multiple atmospheric and wave models with configurable weights
- Applies instability-based wind boosting (cold air over warm water)
- Supports alternate GFS wind levels (30m, 50m, etc.) for boosting
- Creates Wind, WindGust, and WaveHeight grids

Uses shared utilities for model configuration, grid fetching, and thresholds.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

import SmartScript

import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Populate"]
VariableList = []


@dataclass(frozen=True)
class ModelConfig:
    """Model configuration for blending."""
    alias: str
    label: str
    max_runs: int
    is_wave: bool = False


def _build_model_configs(kind: str = "atmo") -> List[ModelConfig]:
    """Build model configs from the model alias registry."""
    is_wave = kind == "wave"
    configs: List[ModelConfig] = []
    
    # Add Fcst/Official first for wind models
    if not is_wave:
        configs.extend([
            ModelConfig(alias="Fcst", label="Forecast", max_runs=1),
            ModelConfig(alias="Official", label="Official", max_runs=1),
        ])
    
    for alias, display_name, max_runs in model_aliases.list_models_for_gui(kind):
        configs.append(ModelConfig(
            alias=alias,
            label=display_name,
            max_runs=max_runs,
            is_wave=is_wave,
        ))
    return configs


WIND_MODEL_CONFIGS = _build_model_configs(kind="atmo")
WAVE_MODEL_CONFIGS = _build_model_configs(kind="wave")


def _filter_wind_models_with_waves(configs: List[ModelConfig]) -> List[ModelConfig]:
    """
    Show only the legacy set of wind models for the GUI.
    Wave grids will still auto-derive where mappings exist.
    """
    allowed = {"GFS", "ECMWF", "CMC", "Fcst", "Official"}
    return [cfg for cfg in configs if cfg.alias in allowed]


class WindWaveGustGUI:
    """GUI for wind/wave/gust blending tool."""

    def __init__(self, master, callback, wind_configs, wave_configs=None):
        self.master = master
        self.callback = callback
        self.master.title("Populate Wind/Wave/Gust")
        self.master.geometry("650x900")
        self.master.resizable(True, True)

        self.wind_configs = wind_configs
        self.wind_weights: Dict[str, tk.IntVar] = {}
        self.wind_labels: Dict[str, tk.Label] = {}  # For percentage labels

        # Options
        self.create_waves = tk.BooleanVar(value=True)
        self.gust_multiplier = tk.DoubleVar(value=1.3)
        self.apply_smoothing = tk.BooleanVar(value=False)
        self.smoothing_passes = tk.IntVar(value=2)
        self.enable_boost = tk.BooleanVar(value=True)
        # Get boost defaults from thresholds
        try:
            boost_defaults = thresholds.get_wind_boost_defaults()
            default_boost_scale = boost_defaults.get("boost_scale", 0.02)
            default_max_boost = boost_defaults.get("max_boost", 0.25)
        except (AttributeError, KeyError):
            default_boost_scale = 0.02
            default_max_boost = 0.25
        self.boost_scale = tk.DoubleVar(value=default_boost_scale)
        self.max_boost = tk.DoubleVar(value=default_max_boost)
        self.use_alt_level = tk.BooleanVar(value=False)
        self.alt_level = tk.StringVar(value="30FHAG")

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=12, pady=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Populate Wind/Wave/Gust",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Multi-model blending with instability boost",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 10))

        # Create notebook-style frames
        self._build_wind_frame(main)
        self._build_gust_frame(main)
        self._build_boost_frame(main)
        self._build_smoothing_frame(main)
        self._build_buttons(main)

    def _build_wind_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Model Blend Weights", padx=10, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        # Create sliders for each model (0-5 range like legacy tool)
        for cfg in self.wind_configs:
            # Legacy default: sliders start at 0 for all models
            var = tk.IntVar(value=0)
            self.wind_weights[cfg.alias] = var
            
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=f"{cfg.label}:", width=20, anchor=tk.W).pack(side=tk.LEFT)
            tk.Scale(row, from_=0, to=5, orient=tk.HORIZONTAL, 
                    variable=var, command=self._update_weights, width=15).pack(side=tk.LEFT, fill=tk.X, expand=True)
            label = tk.Label(row, text="0%", width=6)
            label.pack(side=tk.RIGHT)
            self.wind_labels[cfg.alias] = label
        
        # Status label
        self.total_label = tk.Label(frame, text="No Models Selected", 
                                  font=("Arial", 10, "bold"), fg="red")
        self.total_label.pack(pady=(5, 0))
        
        # Error/Warning label
        self.message_label = tk.Label(frame, text="", 
                                  font=("Arial", 9), fg="red")
        self.message_label.pack()
        
        # Initial update
        self._update_weights()

    def _build_gust_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Gust Options", padx=10, pady=5)
        frame.pack(fill=tk.X, pady=(0, 5))

        tk.Label(frame, text="Gust Multiplier:").pack(anchor=tk.W)
        tk.Scale(frame, from_=1.0, to=2.0, resolution=0.05, orient=tk.HORIZONTAL,
                 variable=self.gust_multiplier, length=200).pack(anchor=tk.W)
        tk.Label(frame, text="(1.0 = same as wind, 1.3 = 30% above wind)",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W)

    def _build_boost_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Instability Wind Boost", padx=10, pady=5)
        frame.pack(fill=tk.X, pady=(0, 5))

        tk.Checkbutton(frame, text="Enable instability-based wind boost",
                       variable=self.enable_boost).pack(anchor=tk.W)
        tk.Label(frame, text="(Boosts winds where SST > Air Temp - cold air over warm water)",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W)

        row1 = tk.Frame(frame)
        row1.pack(fill=tk.X, pady=(5, 0))
        tk.Label(row1, text="Boost Scale:", width=12).pack(side=tk.LEFT)
        tk.Scale(row1, from_=0.01, to=0.05, resolution=0.005, orient=tk.HORIZONTAL,
                 variable=self.boost_scale, length=150).pack(side=tk.LEFT)
        tk.Label(row1, text="per °F", font=("Arial", 8)).pack(side=tk.LEFT)

        row2 = tk.Frame(frame)
        row2.pack(fill=tk.X)
        tk.Label(row2, text="Max Boost:", width=12).pack(side=tk.LEFT)
        tk.Scale(row2, from_=0.10, to=0.40, resolution=0.05, orient=tk.HORIZONTAL,
                 variable=self.max_boost, length=150).pack(side=tk.LEFT)
        tk.Label(row2, text="(25% = 0.25)", font=("Arial", 8)).pack(side=tk.LEFT)

        # Alternate wind level option
        tk.Checkbutton(frame, text="Use GFS alternate wind level for boost source",
                       variable=self.use_alt_level).pack(anchor=tk.W, pady=(10, 0))
        alt_row = tk.Frame(frame)
        alt_row.pack(fill=tk.X)
        tk.Label(alt_row, text="Level:", width=12).pack(side=tk.LEFT)
        try:
            alt_levels = thresholds.GFS_ALT_WIND_LEVELS[:3]
        except AttributeError:
            # Fallback: use getter function or default values
            try:
                alt_levels = thresholds.get_gfs_alt_wind_levels()[:3]
            except AttributeError:
                alt_levels = ["30FHAG", "50FHAG", "80FHAG"]
        for level in alt_levels:
            tk.Radiobutton(alt_row, text=level, variable=self.alt_level,
                           value=level).pack(side=tk.LEFT)

    def _build_smoothing_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Smoothing", padx=10, pady=5)
        frame.pack(fill=tk.X, pady=(0, 5))

        tk.Checkbutton(frame, text="Apply spatial smoothing to output grids",
                       variable=self.apply_smoothing).pack(anchor=tk.W)

        row = tk.Frame(frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Passes:", width=12).pack(side=tk.LEFT)
        tk.Scale(row, from_=1, to=5, orient=tk.HORIZONTAL,
                 variable=self.smoothing_passes, length=150).pack(side=tk.LEFT)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(10, 0))

        tk.Button(frame, text="Run Tool", command=self._run,
                  bg="lightgreen", font=("Arial", 11, "bold"), width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _update_weights(self, *args):
        """Update weight labels and total (like legacy tool)."""
        total = 0
        
        # Calculate total from all sliders (0-5 range)
        for alias, var in self.wind_weights.items():
            weight = var.get()
            total += weight
        
        # Convert to percentages
        if total > 0:
            for alias, var in self.wind_weights.items():
                weight = var.get()
                percentage = int((weight / float(total)) * 100)
                self.wind_labels[alias].config(text="%d%%" % percentage)
        else:
            for alias in self.wind_weights.keys():
                self.wind_labels[alias].config(text="0%")
        
        # Update status message
        if total == 0:
            self.total_label.config(text="No Models Selected", fg="red")
            self.message_label.config(text="ERROR: Move at least one slider above 0", fg="red")
        else:
            self.total_label.config(text="Models Selected", fg="green")
            self.message_label.config(text="", fg="black")

    def _run(self):
        wind_weights = {alias: var.get() for alias, var in self.wind_weights.items()}

        if sum(wind_weights.values()) == 0:
            messagebox.showerror("Error", "Select at least one wind model")
            return

        self.callback({
            "wind_weights": wind_weights,
            "create_waves": self.create_waves.get(),
            "gust_multiplier": self.gust_multiplier.get(),
            "apply_smoothing": self.apply_smoothing.get(),
            "smoothing_passes": self.smoothing_passes.get(),
            "enable_boost": self.enable_boost.get(),
            "boost_scale": self.boost_scale.get(),
            "max_boost": self.max_boost.get(),
            "use_alt_level": self.use_alt_level.get(),
            "alt_level": self.alt_level.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Wind/Wave/Gust blending procedure with instability boost."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.output_log: List[str] = []

    def log(self, message: str):
        """Log message."""
        print(message)
        self.output_log.append(message)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        self.output_log = []

        try:
            if varDict is None:
                varDict = self._show_gui()
                if varDict is None:
                    self.statusBarMsg("Tool cancelled", "S")
                    return
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                self.statusBarMsg(f"Populate_WindWaveGust GUI failed: {e}", "S")
            except Exception:
                pass
            print(tb)
            return

        wind_weights = varDict["wind_weights"]
        create_waves = varDict["create_waves"]
        gust_mult = varDict["gust_multiplier"]
        apply_smoothing = varDict["apply_smoothing"]
        smoothing_passes = varDict["smoothing_passes"]
        enable_boost = varDict["enable_boost"]
        boost_scale = varDict["boost_scale"]
        max_boost = varDict["max_boost"]
        use_alt_level = varDict["use_alt_level"]
        alt_level = varDict["alt_level"]

        # Normalize wind weights
        wind_weights = self._normalize_weights(wind_weights)
        active_wind = [cfg for cfg in WIND_MODEL_CONFIGS if wind_weights.get(cfg.alias, 0) > 0]

        # Auto-derive wave models from wind models (like legacy tool)
        wave_weights = {}
        active_wave = []
        if create_waves:
            for wind_cfg in active_wind:
                wave_cfg = model_aliases.resolve_wave_from_atmo(wind_cfg.alias)
                if wave_cfg is not None:
                    # Use same weight as wind model
                    wind_weight = wind_weights.get(wind_cfg.alias, 0.0)
                    if wind_weight > 0:
                        # Prefer canonical wave alias when possible (registry resolves DB ids).
                        wave_db = wave_cfg.gfe_databases[0] if wave_cfg.gfe_databases else None
                        if wave_db:
                            try:
                                wave_alias = model_aliases.resolve_alias(wave_db)
                                wave_label = model_aliases.get_model_config(wave_alias).get_display_name()
                            except Exception:
                                wave_alias = wave_db
                                wave_label = wave_db
                            
                            wave_weights[wave_alias] = wind_weight
                            wave_model_config = ModelConfig(
                                alias=wave_alias,
                                label=wave_label,
                                max_runs=1,
                                is_wave=True
                            )
                            active_wave.append(wave_model_config)

        self.log("=" * 70)
        self.log("POPULATE WIND/WAVE/GUST")
        self.log("=" * 70)
        self.log(f"Wind models: {[c.label for c in active_wind]}")
        if create_waves:
            self.log(f"Wave models (auto-derived): {[c.label for c in active_wave]}")
        else:
            self.log("Wave creation: Disabled")
        self.log(f"Boost enabled: {enable_boost}")

        # Get forecast grid times
        time_ranges = self._get_time_ranges(timeRange)
        if not time_ranges:
            self.statusBarMsg("No valid time ranges", "S")
            return

        total = len(time_ranges)

        # Get SST once if boosting enabled (it's relatively static)
        sst_grid = None
        if enable_boost:
            sst_grid = self._get_sst_grid(timeRange)
            if sst_grid is not None:
                self.log(f"SST range: {np.nanmin(sst_grid):.1f} to {np.nanmax(sst_grid):.1f}°F")

        for i, tr in enumerate(time_ranges):
            self.statusBarMsg(f"Processing {i+1}/{total}", "R")
            self.log(f"\nPeriod {i+1}/{total}: {tr}")

            # Blend wind
            blended_wind = self._blend_wind(active_wind, wind_weights, tr)
            if blended_wind is None:
                self.log("  No wind data available")
                try:
                    self.statusBarMsg("No wind data available for this period", "S")
                except Exception:
                    pass
                continue

            mag, direc = blended_wind

            # Apply instability boost if enabled
            if enable_boost and sst_grid is not None:
                air_temp = self._get_air_temp(active_wind, wind_weights, tr)
                if air_temp is not None:
                    mag = self._apply_instability_boost(
                        mag, sst_grid, air_temp, boost_scale, max_boost
                    )

                    # Optionally blend with alternate wind level
                    if use_alt_level:
                        alt_wind = self._get_gfs_alt_wind(tr, alt_level)
                        if alt_wind is not None:
                            instability = sst_grid - air_temp
                            # Use instability to weight toward alt level
                            alt_weight = np.clip(instability / 20.0, 0.0, 0.5)
                            alt_mag, _ = alt_wind
                            mag = mag * (1 - alt_weight) + alt_mag * alt_weight
                            self.log(f"  Applied {alt_level} alt wind blending")

            # Apply smoothing
            if apply_smoothing:
                try:
                    sigma = smoothing_passes * thresholds.SMOOTHING_DEFAULTS.get("sigma", 0.7)
                except AttributeError:
                    sigma = smoothing_passes * 0.7
                mag = ndimage.gaussian_filter(mag, sigma=sigma, mode="nearest")
                direc = ndimage.gaussian_filter(direc, sigma=sigma, mode="nearest")

            # Clip and save wind
            mag = np.clip(mag, 0, 150)
            direc = np.mod(direc, 360)
            self.createGrid("Fcst", "Wind", "VECTOR", (mag, direc), tr)
            self.log(f"  Wind: {np.mean(mag):.1f} kt mean, max {np.max(mag):.1f} kt")

            # Calculate and save gust
            gust = np.clip(mag * gust_mult, 0, 150)
            if apply_smoothing:
                gust = ndimage.gaussian_filter(gust, sigma=sigma, mode="nearest")
            self.createGrid("Fcst", "WindGust", "SCALAR", gust, tr)
            self.log(f"  Gust: {np.mean(gust):.1f} kt mean, max {np.max(gust):.1f} kt")

            # Blend waves if enabled and wave models available
            if create_waves and active_wave:
                blended_wave = self._blend_waves(active_wave, wave_weights, tr)
                if blended_wave is not None:
                    if apply_smoothing:
                        blended_wave = ndimage.gaussian_filter(blended_wave, sigma=sigma, mode="nearest")
                    blended_wave = np.clip(blended_wave, 0, 60)
                    self.createGrid("Fcst", "WaveHeight", "SCALAR", blended_wave, tr,
                                    minAllowedValue=0.0)
                    self.log(f"  WaveHeight: {np.mean(blended_wave):.1f} ft mean")
                else:
                    self.log("  No wave data available")

        self.log("\n" + "=" * 70)
        self.log("Complete")
        self.statusBarMsg("Wind/Wave/Gust complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        # Only show wind models that have corresponding wave models
        filtered_wind_configs = _filter_wind_models_with_waves(WIND_MODEL_CONFIGS)
        gui = WindWaveGustGUI(root, callback, filtered_wind_configs, [])
        root.mainloop()
        return result[0]

    def _get_time_ranges(self, selection):
        """Get grid time ranges from selection."""
        ranges = []
        gridinfos = self.getGridInfo("Fcst", "Wind", "SFC", selection)
        for info in gridinfos or []:
            ranges.append(info.gridTime())
        # If no existing Fcst Wind grids, fall back to the selection itself.
        if not ranges:
            try:
                ranges = [selection]
            except Exception:
                ranges = []
        return ranges

    def _normalize_weights(self, weights: Dict[str, int]) -> Dict[str, float]:
        """Normalize weights to sum to 1."""
        total = sum(weights.values())
        if total == 0:
            return {k: 0.0 for k in weights}
        return {k: v / total for k, v in weights.items()}

    def _blend_wind(self, configs: List[ModelConfig], weights: Dict[str, float], tr):
        """Blend wind grids from multiple models."""
        u_sum = None
        v_sum = None
        total_weight = 0.0

        for cfg in configs:
            weight = weights.get(cfg.alias, 0.0)
            if weight <= 0:
                continue

            grid = grid_fetch.get_vector_grid(
                self, cfg.alias, "Wind", "SFC", tr,
                run_depth=1, noDataError=0  # Use current run
            )
            if grid is None:
                continue

            mag, direc = grid
            u, v = self.MagDirToUV(mag, direc)

            if u_sum is None:
                u_sum = np.zeros_like(u, dtype=float)
                v_sum = np.zeros_like(v, dtype=float)

            u_sum += u * weight
            v_sum += v * weight
            total_weight += weight

        if total_weight == 0 or u_sum is None:
            return None

        u_avg = u_sum / total_weight
        v_avg = v_sum / total_weight
        return self.UVToMagDir(u_avg, v_avg)

    def _blend_waves(self, configs: List[ModelConfig], weights: Dict[str, float], tr):
        """Blend wave height grids from multiple models."""
        wave_sum = None
        total_weight = 0.0

        for cfg in configs:
            weight = weights.get(cfg.alias, 0.0)
            if weight <= 0:
                continue

            # Wave databases vary by level (SFC vs 0.0SFC vs 0.0MSL).
            # Use alias-registry defaults first, then fall back to common levels.
            level_candidates = ["SFC", "0.0SFC", "0.0MSL"]
            try:
                cfg_alias = model_aliases.get_model_config(cfg.alias)
                wave_cfg = cfg_alias.wave
                if wave_cfg is not None:
                    preferred = wave_cfg.default_levels.get("wave")
                    if preferred:
                        level_candidates.insert(0, preferred)
            except Exception:
                pass

            grid = grid_fetch.get_grid_with_fallback(
                self,
                cfg.alias,
                element_candidates=["WaveHeight"],
                level_candidates=level_candidates,
                time_range=tr,
                run_depth=1,
                mode="First",
                noDataError=0,
            )
            if grid is None:
                continue

            if wave_sum is None:
                wave_sum = np.zeros_like(grid, dtype=float)

            wave_sum += grid * weight
            total_weight += weight

        if total_weight == 0 or wave_sum is None:
            return None

        return wave_sum / total_weight

    def _get_sst_grid(self, tr):
        """Get SST grid from RTOFS or Fcst, convert to Fahrenheit if needed."""
        try:
            sst = grid_fetch.get_grid(self, "RTOFS", "SST", "SFC", tr, run_depth=2, noDataError=0)
            if sst is not None:
                # Convert to Fahrenheit if needed (RTOFS is typically in Celsius)
                if np.nanmax(sst) < 50:  # Likely Celsius
                    try:
                        sst = thresholds.c_to_f(sst)
                    except AttributeError:
                        sst = sst * 9.0/5.0 + 32.0
                elif np.nanmax(sst) > 200:  # Likely Kelvin
                    try:
                        sst = thresholds.c_to_f(thresholds.k_to_c(sst))
                    except AttributeError:
                        sst_c = sst - 273.15
                        sst = sst_c * 9.0/5.0 + 32.0
                return sst
        except Exception:
            pass

        try:
            sst = self.getGrids("Fcst", "SST", "SFC", tr, mode="First", noDataError=0)
            if sst is not None:
                # Convert to Fahrenheit if needed
                if np.nanmax(sst) < 50:  # Likely Celsius
                    try:
                        sst = thresholds.c_to_f(sst)
                    except AttributeError:
                        sst = sst * 9.0/5.0 + 32.0
                elif np.nanmax(sst) > 200:  # Likely Kelvin
                    try:
                        sst = thresholds.c_to_f(thresholds.k_to_c(sst))
                    except AttributeError:
                        sst_c = sst - 273.15
                        sst = sst_c * 9.0/5.0 + 32.0
                return sst
        except Exception:
            pass
        return None

    def _get_air_temp(self, configs: List[ModelConfig], weights: Dict[str, float], tr):
        """Get blended surface air temperature."""
        temp_sum = None
        total_weight = 0.0

        for cfg in configs:
            weight = weights.get(cfg.alias, 0.0)
            if weight <= 0:
                continue

            temp = grid_fetch.get_grid(
                self, cfg.alias, "T", "SFC", tr,
                run_depth=1, noDataError=0  # Use current run
            )
            if temp is None:
                temp = grid_fetch.get_grid(
                    self, cfg.alias, "t", "MB1000", tr,
                    run_depth=1, noDataError=0  # Use current run
                )

            if temp is None:
                continue

            if np.nanmax(temp) > 200:
                try:
                    temp_c = thresholds.k_to_c(temp)
                    temp = thresholds.c_to_f(temp_c)
                except AttributeError:
                    # Fallback: K to F conversion (K -> C -> F)
                    temp_c = temp - 273.15
                    temp = temp_c * 9.0/5.0 + 32.0

            if temp_sum is None:
                temp_sum = np.zeros_like(temp, dtype=float)

            temp_sum += temp * weight
            total_weight += weight

        if total_weight == 0 or temp_sum is None:
            return None

        return temp_sum / total_weight

    def _apply_instability_boost(self, mag, sst, air_temp, boost_scale, max_boost):
        """Apply instability-based wind boost."""
        # Get minimum instability threshold from thresholds
        try:
            boost_defaults = thresholds.get_wind_boost_defaults()
            min_instability = boost_defaults.get("min_instability", 2.0)
        except (AttributeError, KeyError):
            min_instability = 2.0
        
        instability = sst - air_temp
        # Only apply boost where instability exceeds minimum threshold
        boost_factor = np.where(
            instability >= min_instability,
            np.clip(instability * boost_scale, 0.0, max_boost),
            0.0
        )
        boosted_mag = mag * (1.0 + boost_factor)

        boost_area = np.sum(boost_factor > 0) / boost_factor.size * 100
        if boost_area > 0:
            avg_boost = np.mean(boost_factor[boost_factor > 0]) * 100
            self.log(f"  Boost applied to {boost_area:.1f}% of grid, avg boost {avg_boost:.1f}%")

        return boosted_mag

    def _get_gfs_alt_wind(self, tr, level: str):
        """Get GFS wind at alternate level."""
        try:
            return grid_fetch.get_vector_grid(
                self, "GFS", "Wind", level, tr,
                run_depth=3, noDataError=0
            )
        except Exception:
            return None


__all__ = ["Procedure", "WindWaveGustGUI"]

