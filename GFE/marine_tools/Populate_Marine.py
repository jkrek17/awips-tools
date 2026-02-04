"""
Populate_Marine - Unified Marine Forecast Population Tool

Comprehensive tool for creating marine forecast grids:
- Wind Section: Wind, WindGust with stability-based boosting
- Wave Section: WaveHeight, Swell with wind-wave consistency
- Weather Section: Wx, Visibility, IceAccretion

Uses: grid_ops, stability_blend utilities for meteorologically sound processing.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage

import SmartScript
from WxMethods import *

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

WIND_MODELS = ["GFS", "ECMWF", "NAM", "CMC", "UKMET", "GEFS"]
WAVE_MODELS = ["GFSWAVE", "ECMWF", "CMC", "NWPS"]
ATMO_MODELS = ["GFS", "ECMWF", "NAM", "CMC"]

# Ice accretion thresholds
ICE_TEMP_MAX_C = -1.7  # Max air temp for icing (C)
ICE_SST_MAX_C = 7.0    # Max SST for icing (C)
ICE_WIND_MIN_KT = 15   # Minimum wind for spray


# =============================================================================
# GUI
# =============================================================================

class PopulateMarineGUI:
    """GUI for marine population tool."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Populate Marine Forecast")
        self.master.geometry("750x950")
        self.master.resizable(True, True)

        self._build_ui()

    def _build_ui(self):
        notebook = ttk.Notebook(self.master)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Wind
        self.wind_frame = ttk.Frame(notebook)
        notebook.add(self.wind_frame, text="Wind & Gust")
        self._build_wind_tab()

        # Tab 2: Waves
        self.wave_frame = ttk.Frame(notebook)
        notebook.add(self.wave_frame, text="Waves")
        self._build_wave_tab()

        # Tab 3: Weather
        self.wx_frame = ttk.Frame(notebook)
        notebook.add(self.wx_frame, text="Wx / Vis / Ice")
        self._build_wx_tab()

        # Bottom buttons
        btn_frame = tk.Frame(self.master)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(btn_frame, text="Populate Grids", command=self._run,
                  bg="lightgreen", font=("Arial", 12, "bold"), width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    # =========================================================================
    # Wind Tab
    # =========================================================================

    def _build_wind_tab(self):
        frame = self.wind_frame

        # Enable
        self.enable_wind = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Populate Wind and WindGust",
                       variable=self.enable_wind, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Model weights
        model_frame = tk.LabelFrame(frame, text="Model Weights (0-10)", padx=10, pady=5)
        model_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wind_weights = {}
        self.wind_pct_labels = {}
        for model in WIND_MODELS:
            row = tk.Frame(model_frame)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=f"{model}:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            
            default = 5 if model in ["GFS", "ECMWF"] else 0
            var = tk.IntVar(value=default)
            self.wind_weights[model] = var
            
            tk.Scale(row, from_=0, to=10, orient=tk.HORIZONTAL, variable=var,
                    command=lambda x: self._update_wind_pcts(), length=150).pack(side=tk.LEFT)
            
            lbl = tk.Label(row, text="0%", width=6)
            lbl.pack(side=tk.LEFT)
            self.wind_pct_labels[model] = lbl

        self._update_wind_pcts()

        # Blend method
        blend_frame = tk.LabelFrame(frame, text="Blend Method", padx=10, pady=5)
        blend_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wind_blend_method = tk.StringVar(value="weighted")
        methods = [
            ("Weighted Mean", "weighted"),
            ("Spread-Weighted (downweight outliers)", "spread_weighted"),
            ("Trimmed Mean (exclude extremes)", "trimmed"),
            ("Median", "median"),
        ]
        for text, value in methods:
            tk.Radiobutton(blend_frame, text=text, variable=self.wind_blend_method,
                          value=value).pack(anchor=tk.W)

        # Stability boost
        boost_frame = tk.LabelFrame(frame, text="Stability-Based Wind Boost", padx=10, pady=5)
        boost_frame.pack(fill=tk.X, padx=10, pady=5)

        self.enable_boost = tk.BooleanVar(value=True)
        tk.Checkbutton(boost_frame, text="Enable instability wind boost",
                       variable=self.enable_boost).pack(anchor=tk.W)
        tk.Label(boost_frame, text="(Boosts winds where SST >> T_air)",
                font=("Arial", 8), fg="gray").pack(anchor=tk.W)

        row = tk.Frame(boost_frame)
        row.pack(fill=tk.X, pady=5)
        tk.Label(row, text="Max Boost:", width=12).pack(side=tk.LEFT)
        self.max_boost = tk.DoubleVar(value=1.30)
        tk.Scale(row, from_=1.1, to=1.5, resolution=0.05, orient=tk.HORIZONTAL,
                variable=self.max_boost, length=150).pack(side=tk.LEFT)

        # Gust settings
        gust_frame = tk.LabelFrame(frame, text="Gust Calculation", padx=10, pady=5)
        gust_frame.pack(fill=tk.X, padx=10, pady=5)

        row = tk.Frame(gust_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Base Gust Factor:", width=14).pack(side=tk.LEFT)
        self.gust_factor = tk.DoubleVar(value=1.30)
        tk.Scale(row, from_=1.1, to=1.6, resolution=0.05, orient=tk.HORIZONTAL,
                variable=self.gust_factor, length=150).pack(side=tk.LEFT)

        self.stability_gust = tk.BooleanVar(value=True)
        tk.Checkbutton(gust_frame, text="Higher gust factor in unstable conditions",
                       variable=self.stability_gust).pack(anchor=tk.W)

        # Smoothing
        smooth_frame = tk.LabelFrame(frame, text="Smoothing", padx=10, pady=5)
        smooth_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wind_smooth = tk.BooleanVar(value=True)
        tk.Checkbutton(smooth_frame, text="Apply Gaussian smoothing",
                       variable=self.wind_smooth).pack(anchor=tk.W)

        row = tk.Frame(smooth_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Sigma:", width=12).pack(side=tk.LEFT)
        self.wind_sigma = tk.DoubleVar(value=0.7)
        tk.Scale(row, from_=0.3, to=2.0, resolution=0.1, orient=tk.HORIZONTAL,
                variable=self.wind_sigma, length=150).pack(side=tk.LEFT)

    def _update_wind_pcts(self):
        total = sum(v.get() for v in self.wind_weights.values())
        for model, var in self.wind_weights.items():
            if total > 0:
                pct = int(100 * var.get() / total)
            else:
                pct = 0
            self.wind_pct_labels[model].config(text=f"{pct}%")

    # =========================================================================
    # Wave Tab
    # =========================================================================

    def _build_wave_tab(self):
        frame = self.wave_frame

        # Enable
        self.enable_wave = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Populate WaveHeight",
                       variable=self.enable_wave, font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=10, padx=10)

        # Model weights
        model_frame = tk.LabelFrame(frame, text="Wave Model Weights (0-10)", padx=10, pady=5)
        model_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wave_weights = {}
        self.wave_pct_labels = {}
        for model in WAVE_MODELS:
            row = tk.Frame(model_frame)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=f"{model}:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            
            default = 5 if model in ["GFSWAVE", "ECMWF"] else 0
            var = tk.IntVar(value=default)
            self.wave_weights[model] = var
            
            tk.Scale(row, from_=0, to=10, orient=tk.HORIZONTAL, variable=var,
                    command=lambda x: self._update_wave_pcts(), length=150).pack(side=tk.LEFT)
            
            lbl = tk.Label(row, text="0%", width=6)
            lbl.pack(side=tk.LEFT)
            self.wave_pct_labels[model] = lbl

        self._update_wave_pcts()

        # Blend method
        blend_frame = tk.LabelFrame(frame, text="Blend Method", padx=10, pady=5)
        blend_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wave_blend_method = tk.StringVar(value="weighted")
        methods = [
            ("Weighted Mean", "weighted"),
            ("Spread-Weighted", "spread_weighted"),
            ("Maximum (conservative)", "max"),
            ("Median", "median"),
        ]
        for text, value in methods:
            tk.Radiobutton(blend_frame, text=text, variable=self.wave_blend_method,
                          value=value).pack(anchor=tk.W)

        # Wave enhancement
        enhance_frame = tk.LabelFrame(frame, text="Wave Enhancement", padx=10, pady=5)
        enhance_frame.pack(fill=tk.X, padx=10, pady=5)

        self.stability_wave = tk.BooleanVar(value=False)
        tk.Checkbutton(enhance_frame, text="Enhance waves in unstable conditions",
                       variable=self.stability_wave).pack(anchor=tk.W)
        tk.Label(enhance_frame, text="(Unstable BL = enhanced momentum transfer = slightly higher waves)",
                font=("Arial", 8), fg="gray").pack(anchor=tk.W)

        # Smoothing
        smooth_frame = tk.LabelFrame(frame, text="Smoothing", padx=10, pady=5)
        smooth_frame.pack(fill=tk.X, padx=10, pady=5)

        self.wave_smooth = tk.BooleanVar(value=True)
        tk.Checkbutton(smooth_frame, text="Apply Gaussian smoothing",
                       variable=self.wave_smooth).pack(anchor=tk.W)

        row = tk.Frame(smooth_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Sigma:", width=12).pack(side=tk.LEFT)
        self.wave_sigma = tk.DoubleVar(value=0.7)
        tk.Scale(row, from_=0.3, to=2.0, resolution=0.1, orient=tk.HORIZONTAL,
                variable=self.wave_sigma, length=150).pack(side=tk.LEFT)

    def _update_wave_pcts(self):
        total = sum(v.get() for v in self.wave_weights.values())
        for model, var in self.wave_weights.items():
            if total > 0:
                pct = int(100 * var.get() / total)
            else:
                pct = 0
            self.wave_pct_labels[model].config(text=f"{pct}%")

    # =========================================================================
    # Weather Tab
    # =========================================================================

    def _build_wx_tab(self):
        frame = self.wx_frame

        # Wx grid
        wx_frame = tk.LabelFrame(frame, text="Weather Grid (Wx)", padx=10, pady=5)
        wx_frame.pack(fill=tk.X, padx=10, pady=5)

        self.enable_wx = tk.BooleanVar(value=True)
        tk.Checkbutton(wx_frame, text="Populate Wx grid",
                       variable=self.enable_wx, font=("Arial", 10, "bold")).pack(anchor=tk.W)

        self.wx_model = tk.StringVar(value="GFS")
        row = tk.Frame(wx_frame)
        row.pack(fill=tk.X)
        tk.Label(row, text="Primary Model:").pack(side=tk.LEFT)
        for model in ["GFS", "ECMWF", "NAM", "Blend"]:
            tk.Radiobutton(row, text=model, variable=self.wx_model, value=model).pack(side=tk.LEFT)

        self.include_thunder = tk.BooleanVar(value=True)
        tk.Checkbutton(wx_frame, text="Include thunderstorms (CAPE-based)",
                       variable=self.include_thunder).pack(anchor=tk.W)

        self.include_fog = tk.BooleanVar(value=True)
        tk.Checkbutton(wx_frame, text="Include fog (stability-based)",
                       variable=self.include_fog).pack(anchor=tk.W)

        # Visibility
        vis_frame = tk.LabelFrame(frame, text="Visibility", padx=10, pady=5)
        vis_frame.pack(fill=tk.X, padx=10, pady=5)

        self.enable_vis = tk.BooleanVar(value=True)
        tk.Checkbutton(vis_frame, text="Populate Visibility grid",
                       variable=self.enable_vis, font=("Arial", 10, "bold")).pack(anchor=tk.W)

        self.vis_method = tk.StringVar(value="model")
        methods = [
            ("Use model visibility", "model"),
            ("Derive from RH/fog potential", "derived"),
            ("Blend model + derived", "blend"),
        ]
        for text, value in methods:
            tk.Radiobutton(vis_frame, text=text, variable=self.vis_method,
                          value=value).pack(anchor=tk.W)

        # Ice Accretion
        ice_frame = tk.LabelFrame(frame, text="Ice Accretion", padx=10, pady=5)
        ice_frame.pack(fill=tk.X, padx=10, pady=5)

        self.enable_ice = tk.BooleanVar(value=True)
        tk.Checkbutton(ice_frame, text="Populate IceAccretion grid",
                       variable=self.enable_ice, font=("Arial", 10, "bold")).pack(anchor=tk.W)

        tk.Label(ice_frame, text="Based on: Wind speed, air temp, SST, wave height",
                font=("Arial", 8), fg="gray").pack(anchor=tk.W)

        self.ice_algorithm = tk.StringVar(value="overland")
        algs = [
            ("Overland (1990) - Standard NWS", "overland"),
            ("Comiso-Sullivan - Enhanced", "comiso"),
        ]
        for text, value in algs:
            tk.Radiobutton(ice_frame, text=text, variable=self.ice_algorithm,
                          value=value).pack(anchor=tk.W)

    # =========================================================================
    # Actions
    # =========================================================================

    def _run(self):
        config = {
            # Wind settings
            "enable_wind": self.enable_wind.get(),
            "wind_weights": {k: v.get() for k, v in self.wind_weights.items()},
            "wind_blend_method": self.wind_blend_method.get(),
            "enable_boost": self.enable_boost.get(),
            "max_boost": self.max_boost.get(),
            "gust_factor": self.gust_factor.get(),
            "stability_gust": self.stability_gust.get(),
            "wind_smooth": self.wind_smooth.get(),
            "wind_sigma": self.wind_sigma.get(),

            # Wave settings
            "enable_wave": self.enable_wave.get(),
            "wave_weights": {k: v.get() for k, v in self.wave_weights.items()},
            "wave_blend_method": self.wave_blend_method.get(),
            "stability_wave": self.stability_wave.get(),
            "wave_smooth": self.wave_smooth.get(),
            "wave_sigma": self.wave_sigma.get(),

            # Wx settings
            "enable_wx": self.enable_wx.get(),
            "wx_model": self.wx_model.get(),
            "include_thunder": self.include_thunder.get(),
            "include_fog": self.include_fog.get(),

            # Visibility settings
            "enable_vis": self.enable_vis.get(),
            "vis_method": self.vis_method.get(),

            # Ice settings
            "enable_ice": self.enable_ice.get(),
            "ice_algorithm": self.ice_algorithm.get(),
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
    """Marine forecast population procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.log_messages: List[str] = []
        self.stability_cache: Dict = {}

    def log(self, msg: str):
        print(msg)
        self.log_messages.append(msg)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution."""
        self.log_messages = []
        self.stability_cache = {}

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                return

        self.log("=" * 70)
        self.log("POPULATE MARINE FORECAST")
        self.log("=" * 70)

        # Get time ranges
        fcst = self.mutableID().modelIdentifier()
        grid_infos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not grid_infos:
            self.statusBarMsg("No Wind grids found", "S")
            return

        total = len(grid_infos)
        self.log(f"Processing {total} time periods")

        # Pre-fetch stability data if needed
        if varDict["enable_boost"] or varDict["stability_gust"] or varDict["include_fog"]:
            self._prefetch_stability(timeRange)

        for i, grid_info in enumerate(grid_infos):
            grid_tr = grid_info.gridTime()
            self.statusBarMsg(f"Populating {i+1}/{total}", "R")
            self.log(f"\n--- Period {i+1}/{total}: {grid_tr} ---")

            if varDict["enable_wind"]:
                self._populate_wind(varDict, grid_tr)

            if varDict["enable_wave"]:
                self._populate_wave(varDict, grid_tr)

            if varDict["enable_wx"]:
                self._populate_wx(varDict, grid_tr)

            if varDict["enable_vis"]:
                self._populate_vis(varDict, grid_tr)

            if varDict["enable_ice"]:
                self._populate_ice(varDict, grid_tr)

        self.log("\n" + "=" * 70)
        self.log("Population Complete")
        self.statusBarMsg("Population complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(config):
            result[0] = config

        gui = PopulateMarineGUI(root, callback)
        root.mainloop()
        return result[0]

    def _prefetch_stability(self, timeRange):
        """Pre-fetch SST and T850 for stability calculations."""
        self.log("Pre-fetching stability data...")
        
        # Get SST (relatively static)
        sst = grid_fetch.get_grid(self, "RTOFS", "SST", "SFC", timeRange, 
                                  run_depth=2, noDataError=0)
        if sst is None:
            sst = self.getGrids("Fcst", "SST", "SFC", timeRange, noDataError=0)
        
        if sst is not None:
            if np.nanmax(sst) > 200:
                sst = sst - 273.15
            elif np.nanmax(sst) > 50:
                sst = (sst - 32) * 5 / 9
            self.stability_cache["sst"] = sst
            self.log(f"  SST loaded: {np.nanmin(sst):.1f} to {np.nanmax(sst):.1f} C")

    def _get_stability(self, grid_tr) -> Optional[stability_blend.StabilityResult]:
        """Get or calculate stability for a time range."""
        sst = self.stability_cache.get("sst")
        if sst is None:
            return None

        t850 = grid_fetch.get_grid(self, "GFS", "t", "MB850", grid_tr, noDataError=0)
        if t850 is None:
            return None

        if np.nanmax(t850) > 200:
            t850 = t850 - 273.15

        config = BoostConfig(min_factor=1.0, max_factor=1.35)
        return stability_blend.analyze_stability(sst, t850, boost_config=config)

    # =========================================================================
    # Wind Population
    # =========================================================================

    def _populate_wind(self, config: Dict, grid_tr):
        """Populate Wind and WindGust grids."""
        self.log("  [Wind]")

        weights = config["wind_weights"]
        blend_method = config["wind_blend_method"]

        # Fetch model winds
        wind_grids = []
        wind_mags = []
        weight_list = []
        model_names = []

        for model, weight in weights.items():
            if weight <= 0:
                continue
            grid = grid_fetch.get_vector_grid(
                self, model, "Wind", "SFC", grid_tr,
                run_depth=1, noDataError=0
            )
            if grid is not None:
                wind_grids.append(grid)
                wind_mags.append(grid[0])
                weight_list.append(weight)
                model_names.append(model)

        if not wind_grids:
            self.log("    No wind data available")
            return

        self.log(f"    Models: {model_names}")

        # Blend based on method
        if blend_method == "weighted":
            blended_mag, blended_dir = grid_ops.blend_vector(wind_grids, weight_list)
        elif blend_method == "spread_weighted":
            # Use spread-weighted for magnitude, regular blend for direction
            blended_mag = grid_ops.weighted_by_spread(wind_mags)
            _, blended_dir = grid_ops.blend_vector(wind_grids, weight_list)
        elif blend_method == "trimmed":
            blended_mag = grid_ops.trimmed_mean(wind_mags, trim_fraction=0.1)
            _, blended_dir = grid_ops.blend_vector(wind_grids, weight_list)
        elif blend_method == "median":
            blended_mag = grid_ops.ensemble_median(wind_mags)
            _, blended_dir = grid_ops.blend_vector(wind_grids, weight_list)
        else:
            blended_mag, blended_dir = grid_ops.blend_vector(wind_grids, weight_list)

        # Apply stability boost
        boost_factor = None
        if config["enable_boost"]:
            stab = self._get_stability(grid_tr)
            if stab is not None:
                boost_factor = stab.boost_factor
                # Scale to user's max boost setting
                user_max = config["max_boost"]
                boost_factor = 1.0 + (boost_factor - 1.0) * (user_max - 1.0) / 0.35
                boost_factor = np.clip(boost_factor, 1.0, user_max)
                
                blended_mag = blended_mag * boost_factor
                boost_area = np.sum(boost_factor > 1.05) / boost_factor.size * 100
                self.log(f"    Boost applied to {boost_area:.1f}% of area")

        # Smooth
        if config["wind_smooth"]:
            sigma = config["wind_sigma"]
            blended_mag = grid_ops.smooth_gaussian(blended_mag, sigma=sigma)
            # Smooth direction via U/V
            u, v = grid_ops.mag_dir_to_uv(blended_mag, blended_dir)
            u = grid_ops.smooth_gaussian(u, sigma=sigma)
            v = grid_ops.smooth_gaussian(v, sigma=sigma)
            _, blended_dir = grid_ops.uv_to_mag_dir(u, v)

        # Clip and save
        blended_mag = grid_ops.clip_values(blended_mag, 0, 150)
        blended_dir = np.mod(blended_dir, 360)

        self.createGrid("Fcst", "Wind", "VECTOR", (blended_mag, blended_dir), grid_tr)
        self.log(f"    Wind: mean={np.nanmean(blended_mag):.1f} kt, max={np.nanmax(blended_mag):.1f} kt")

        # Calculate gust
        gust_factor = config["gust_factor"]
        
        if config["stability_gust"] and boost_factor is not None:
            # Higher gust factor in unstable areas
            gust_factor_grid = gust_factor + (boost_factor - 1.0) * 0.3
            gust_factor_grid = np.clip(gust_factor_grid, gust_factor, gust_factor + 0.15)
            gust = blended_mag * gust_factor_grid
        else:
            gust = blended_mag * gust_factor

        if config["wind_smooth"]:
            gust = grid_ops.smooth_gaussian(gust, sigma=config["wind_sigma"])

        gust = grid_ops.clip_values(gust, 0, 150)
        self.createGrid("Fcst", "WindGust", "SCALAR", gust, grid_tr)
        self.log(f"    Gust: mean={np.nanmean(gust):.1f} kt, max={np.nanmax(gust):.1f} kt")

    # =========================================================================
    # Wave Population
    # =========================================================================

    def _populate_wave(self, config: Dict, grid_tr):
        """Populate WaveHeight grid."""
        self.log("  [Waves]")

        weights = config["wave_weights"]
        blend_method = config["wave_blend_method"]

        # Fetch wave grids
        wave_grids = []
        weight_list = []
        model_names = []

        for model, weight in weights.items():
            if weight <= 0:
                continue
            grid = grid_fetch.get_grid(
                self, model, "WaveHeight", "SFC", grid_tr,
                run_depth=1, noDataError=0
            )
            if grid is not None:
                wave_grids.append(grid)
                weight_list.append(weight)
                model_names.append(model)

        if not wave_grids:
            self.log("    No wave data available")
            return

        self.log(f"    Models: {model_names}")

        # Blend based on method
        if blend_method == "weighted":
            blended = grid_ops.blend_scalar(wave_grids, weight_list)
        elif blend_method == "spread_weighted":
            blended = grid_ops.weighted_by_spread(wave_grids)
        elif blend_method == "max":
            blended = grid_ops.ensemble_max(wave_grids)
        elif blend_method == "median":
            blended = grid_ops.ensemble_median(wave_grids)
        else:
            blended = grid_ops.blend_scalar(wave_grids, weight_list)

        # Stability-based wave enhancement
        if config["stability_wave"]:
            stab = self._get_stability(grid_tr)
            if stab is not None:
                # Get wind for enhancement calculation
                wind = self.getGrids("Fcst", "Wind", "SFC", grid_tr, noDataError=0)
                if wind is not None:
                    wind_mag = wind[0]
                    enhancement = stability_blend.estimate_wave_enhancement(
                        wind_mag, stab.instability
                    )
                    blended = blended * enhancement
                    self.log(f"    Wave enhancement applied")

        # Smooth
        if config["wave_smooth"]:
            blended = grid_ops.smooth_gaussian(blended, sigma=config["wave_sigma"])

        # Clip and save
        blended = grid_ops.clip_values(blended, 0, 50)
        self.createGrid("Fcst", "WaveHeight", "SCALAR", blended, grid_tr,
                       minAllowedValue=0)
        self.log(f"    WaveHeight: mean={np.nanmean(blended):.1f} ft, max={np.nanmax(blended):.1f} ft")

    # =========================================================================
    # Weather Population
    # =========================================================================

    def _populate_wx(self, config: Dict, grid_tr):
        """Populate Wx grid."""
        self.log("  [Weather]")

        model = config["wx_model"]
        include_thunder = config["include_thunder"]
        include_fog = config["include_fog"]

        # Get existing Wx grid
        wx_grid = self.getGrids("Fcst", "Wx", "SFC", grid_tr, noDataError=0)
        if wx_grid is None:
            self.log("    No existing Wx grid")
            return

        wx_values, keys = wx_grid
        new_wx = np.zeros(wx_values.shape, dtype=int)
        no_wx = "<NoCov>:<NoWx>:<NoInten>:<NoVis>:"

        # Get model data
        if model == "Blend":
            qpf = self._get_blended_grid(ATMO_MODELS, "tp", "SFC", grid_tr)
            temp = self._get_blended_grid(ATMO_MODELS, "t", "MB1000", grid_tr)
        else:
            qpf = grid_fetch.get_grid(self, model, "tp", "SFC", grid_tr, noDataError=0)
            temp = grid_fetch.get_grid(self, model, "t", "MB1000", grid_tr, noDataError=0)

        cape = grid_fetch.get_grid(self, model if model != "Blend" else "GFS", 
                                   "cape", "SFC", grid_tr, noDataError=0)

        # Convert units
        if qpf is not None:
            qpf_in = qpf * 0.03937  # mm to inches
        else:
            qpf_in = None

        if temp is not None and np.nanmax(temp) > 200:
            temp = temp - 273.15

        # Get fog potential
        fog_potential = None
        if include_fog:
            stab = self._get_stability(grid_tr)
            if stab is not None:
                t2m = grid_fetch.get_grid(self, "GFS", "t", "SFC", grid_tr, noDataError=0)
                rh = grid_fetch.get_grid(self, "GFS", "rh", "SFC", grid_tr, noDataError=0)
                if t2m is not None and rh is not None:
                    if np.nanmax(t2m) > 200:
                        t2m = t2m - 273.15
                    sst = self.stability_cache.get("sst")
                    if sst is not None:
                        fog_potential = stability_blend.calc_fog_potential(sst, t2m, rh)

        # Build weather strings
        precip_thresh = 0.01  # inches

        for ii in range(wx_values.shape[0]):
            for jj in range(wx_values.shape[1]):
                wx_str = None

                # Check precipitation
                has_precip = qpf_in is not None and qpf_in[ii, jj] > precip_thresh
                
                # Thunder
                if include_thunder and cape is not None and has_precip:
                    if cape[ii, jj] > 1000:
                        cov = "Sct" if cape[ii, jj] > 2000 else "Iso"
                        wx_str = f"{cov}:T:<NoInten>:<NoVis>:"

                # Precipitation
                if wx_str is None and has_precip:
                    qpf_val = qpf_in[ii, jj]
                    
                    if qpf_val > 0.5:
                        cov, inten = "Wide", "+"
                    elif qpf_val > 0.1:
                        cov, inten = "Sct", "m"
                    else:
                        cov, inten = "Iso", "-"

                    if temp is not None and temp[ii, jj] < 0:
                        wx_type = "S"
                    else:
                        wx_type = "R"

                    wx_str = f"{cov}:{wx_type}:{inten}:<NoVis>:"

                # Fog
                if wx_str is None and include_fog and fog_potential is not None:
                    if fog_potential[ii, jj] > 50:
                        wx_str = "Patchy:F:<NoInten>:<NoVis>:"

                # Set value
                if wx_str:
                    try:
                        new_wx[ii, jj] = self.getIndex(wx_str, keys)
                    except Exception:
                        new_wx[ii, jj] = self.getIndex(no_wx, keys)
                else:
                    new_wx[ii, jj] = self.getIndex(no_wx, keys)

        self.createGrid("Fcst", "Wx", "WEATHER", (new_wx, keys), grid_tr)
        self.log("    Wx grid populated")

    def _get_blended_grid(self, models: List[str], element: str, level: str, 
                          grid_tr) -> Optional[np.ndarray]:
        """Get blended grid from multiple models."""
        grids = []
        for model in models:
            grid = grid_fetch.get_grid(self, model, element, level, grid_tr, noDataError=0)
            if grid is not None:
                grids.append(grid)
        
        if not grids:
            return None
        return grid_ops.ensemble_mean(grids)

    # =========================================================================
    # Visibility Population
    # =========================================================================

    def _populate_vis(self, config: Dict, grid_tr):
        """Populate Visibility grid."""
        self.log("  [Visibility]")

        method = config["vis_method"]

        # Get model visibility
        model_vis = grid_fetch.get_grid(self, "GFS", "Vis", "SFC", grid_tr, noDataError=0)
        if model_vis is not None and np.nanmax(model_vis) > 100:
            model_vis = model_vis / 1852.0  # meters to NM

        # Get derived visibility from fog potential
        derived_vis = None
        stab = self._get_stability(grid_tr)
        if stab is not None:
            t2m = grid_fetch.get_grid(self, "GFS", "t", "SFC", grid_tr, noDataError=0)
            rh = grid_fetch.get_grid(self, "GFS", "rh", "SFC", grid_tr, noDataError=0)
            if t2m is not None and rh is not None:
                if np.nanmax(t2m) > 200:
                    t2m = t2m - 273.15
                sst = self.stability_cache.get("sst")
                if sst is not None:
                    fog_pot = stability_blend.calc_fog_potential(sst, t2m, rh)
                    # Convert fog potential (0-100) to visibility
                    # High fog potential = low visibility
                    derived_vis = 10.0 - (fog_pot / 100.0) * 9.5
                    derived_vis = np.clip(derived_vis, 0.1, 10.0)

        # Combine based on method
        if method == "model" and model_vis is not None:
            vis = model_vis
        elif method == "derived" and derived_vis is not None:
            vis = derived_vis
        elif method == "blend" and model_vis is not None and derived_vis is not None:
            vis = (model_vis + derived_vis) / 2.0
        elif model_vis is not None:
            vis = model_vis
        elif derived_vis is not None:
            vis = derived_vis
        else:
            self.log("    No visibility data available")
            return

        vis = grid_ops.clip_values(vis, 0.0, 10.0)
        self.createGrid("Fcst", "Visibility", "SCALAR", vis, grid_tr,
                       minAllowedValue=0, maxAllowedValue=10, units="NM")
        self.log(f"    Visibility: min={np.nanmin(vis):.1f} NM")

    # =========================================================================
    # Ice Accretion Population
    # =========================================================================

    def _populate_ice(self, config: Dict, grid_tr):
        """Populate IceAccretion grid."""
        self.log("  [Ice Accretion]")

        algorithm = config["ice_algorithm"]

        # Get required data
        wind = self.getGrids("Fcst", "Wind", "SFC", grid_tr, noDataError=0)
        if wind is None:
            self.log("    No wind data for ice calculation")
            return
        wind_kt = wind[0]

        temp = grid_fetch.get_grid(self, "GFS", "t", "SFC", grid_tr, noDataError=0)
        if temp is None:
            self.log("    No temperature data for ice calculation")
            return
        if np.nanmax(temp) > 200:
            temp_c = temp - 273.15
        else:
            temp_c = temp

        sst = self.stability_cache.get("sst")
        if sst is None:
            sst = grid_fetch.get_grid(self, "RTOFS", "SST", "SFC", grid_tr, noDataError=0)
            if sst is not None and np.nanmax(sst) > 200:
                sst = sst - 273.15

        wave = self.getGrids("Fcst", "WaveHeight", "SFC", grid_tr, noDataError=0)
        wave_ft = wave if wave is not None else np.zeros_like(wind_kt)

        # Calculate ice accretion
        if algorithm == "overland":
            ice = self._calc_ice_overland(wind_kt, temp_c, sst, wave_ft)
        else:
            ice = self._calc_ice_comiso(wind_kt, temp_c, sst, wave_ft)

        self.createGrid("Fcst", "IceAccretion", "SCALAR", ice, grid_tr,
                       minAllowedValue=0, maxAllowedValue=5, units="in/hr")
        
        ice_area = np.sum(ice > 0.1) / ice.size * 100
        if ice_area > 0:
            self.log(f"    IceAccretion: {ice_area:.1f}% of area has icing potential")
        else:
            self.log("    No significant ice accretion expected")

    def _calc_ice_overland(self, wind_kt: np.ndarray, temp_c: np.ndarray,
                          sst: Optional[np.ndarray], wave_ft: np.ndarray) -> np.ndarray:
        """
        Overland (1990) ice accretion algorithm.
        
        Standard NWS method based on:
        - Air temperature (must be below freezing)
        - Wind speed (spray generation)
        - Sea surface temperature
        """
        ice = np.zeros_like(wind_kt)

        # Conditions for icing
        temp_ok = temp_c < ICE_TEMP_MAX_C
        wind_ok = wind_kt >= ICE_WIND_MIN_KT
        
        if sst is not None:
            sst_ok = sst < ICE_SST_MAX_C
            conditions = temp_ok & wind_ok & sst_ok
        else:
            conditions = temp_ok & wind_ok

        # Simplified Overland formula
        # Rate = f(wind, temp_diff)
        where_icing = np.where(conditions)
        
        if sst is not None:
            temp_diff = sst[where_icing] - temp_c[where_icing]
        else:
            temp_diff = -temp_c[where_icing]  # Use air temp below freezing

        wind_factor = (wind_kt[where_icing] - ICE_WIND_MIN_KT) / 50.0
        temp_factor = temp_diff / 20.0

        rate = wind_factor * temp_factor * 0.5  # inches per hour
        ice[where_icing] = np.clip(rate, 0, 3.0)

        # Wave enhancement
        wave_factor = np.clip(wave_ft / 10.0, 1.0, 1.5)
        ice = ice * wave_factor

        return ice

    def _calc_ice_comiso(self, wind_kt: np.ndarray, temp_c: np.ndarray,
                        sst: Optional[np.ndarray], wave_ft: np.ndarray) -> np.ndarray:
        """
        Comiso-Sullivan enhanced ice accretion algorithm.
        
        More sophisticated treatment including wave spray contribution.
        """
        ice = self._calc_ice_overland(wind_kt, temp_c, sst, wave_ft)
        
        # Add wave spray contribution for high winds
        high_wind = wind_kt > 40
        high_wave = wave_ft > 8
        
        spray_enhancement = np.where(
            high_wind & high_wave,
            1.0 + (wind_kt - 40) / 30.0 * (wave_ft - 8) / 10.0,
            1.0
        )
        spray_enhancement = np.clip(spray_enhancement, 1.0, 2.0)
        
        ice = ice * spray_enhancement
        return np.clip(ice, 0, 5.0)


__all__ = ["Procedure"]
