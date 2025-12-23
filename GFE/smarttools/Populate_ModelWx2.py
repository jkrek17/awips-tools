"""
Marine Weather Grid Builder v2 - Advanced Wx grid creation.

Comprehensive weather grid creation tool that builds Wx grids from 
atmospheric model data including precipitation, thunderstorms, and fog.
Uses DAL for QPF/CAPE retrieval and shared utilities for model access.

Modular rewrite using shared utilities for model aliases and thresholds.
"""

from __future__ import annotations

import datetime as dt
import tkinter as tk
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage

import SmartScript
from WxMethods import *

import dal
import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Populate"]
VariableList = []

# Models that support DAL retrieval for QPF/CAPE
DAL_MODELS = ["GFS", "ECMWF", "CMC"]
# All available atmospheric models
ALL_MODELS = ["GFS", "ECMWF", "CMC", "UKMET"]


class ModelWx2GUI:
    """GUI for advanced marine weather grid builder."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Weather Grid Builder v2")
        self.master.geometry("750x1000")

        self.model_vars: Dict[str, tk.StringVar] = {}
        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Marine Weather Grid Builder v2",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Advanced weather analysis with DAL support",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 15))

        # Model Selection
        self._build_model_frame(main)

        # Build Options
        self._build_options_frame(main)

        # Parameters
        self._build_params_frame(main)

        # Outputs
        self._build_output_frame(main)

        # Buttons
        self._build_buttons(main)

        self._update_selection()

    def _build_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Select Atmospheric Models", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame, text="Models with DAL support (★) provide better QPF/CAPE",
                 font=("Arial", 9), fg="gray").pack(anchor=tk.W, pady=(0, 5))

        for alias in ALL_MODELS:
            has_dal = alias in DAL_MODELS
            label = f"★ {alias}" if has_dal else alias
            var = tk.StringVar(value="Yes" if alias == "GFS" else "No")
            var.trace("w", lambda *args: self._update_selection())
            self.model_vars[alias] = var
            tk.Checkbutton(frame, text=label, variable=var, onvalue="Yes", offvalue="No").pack(anchor=tk.W)

        self.status_label = tk.Label(frame, text="", font=("Arial", 11, "bold"))
        self.status_label.pack(pady=(10, 0))

    def _build_options_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Build Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.build_mode = tk.StringVar(value="Build New")
        tk.Radiobutton(frame, text="Build New (Replace All)", variable=self.build_mode,
                       value="Build New").pack(anchor=tk.W)
        tk.Radiobutton(frame, text="Enhance Existing", variable=self.build_mode,
                       value="Enhance").pack(anchor=tk.W)

        tk.Label(frame, text="", font=("Arial", 1)).pack()  # Spacer

        self.qualifier_type = tk.StringVar(value="Auto")
        tk.Label(frame, text="Qualifier Type:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5, 0))
        tk.Radiobutton(frame, text="Automatic (based on convective index)", variable=self.qualifier_type,
                       value="Auto").pack(anchor=tk.W)
        tk.Radiobutton(frame, text="Force Coverage (Iso, Sct, Num, Wide)", variable=self.qualifier_type,
                       value="Coverage").pack(anchor=tk.W)
        tk.Radiobutton(frame, text="Force Probability (Chc, Lkly, Def)", variable=self.qualifier_type,
                       value="Probability").pack(anchor=tk.W)

    def _build_params_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Analysis Parameters", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        # Smoothing
        tk.Label(frame, text="Spatial Smoothing:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.smoothing = tk.IntVar(value=2)
        tk.Scale(frame, from_=0, to=5, orient=tk.HORIZONTAL, variable=self.smoothing,
                 length=200).pack(anchor=tk.W)

        # Thunder threshold
        tk.Label(frame, text="Thunder CAPE Threshold (J/kg):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.thunder_thresh = tk.IntVar(value=500)
        tk.Scale(frame, from_=100, to=1500, resolution=50, orient=tk.HORIZONTAL,
                 variable=self.thunder_thresh, length=200).pack(anchor=tk.W)

        # Fog threshold
        tk.Label(frame, text="Fog Visibility Threshold (NM):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.fog_thresh = tk.DoubleVar(value=3.0)
        tk.Scale(frame, from_=0.5, to=6.0, resolution=0.5, orient=tk.HORIZONTAL,
                 variable=self.fog_thresh, length=200).pack(anchor=tk.W)

        # Model Run
        tk.Label(frame, text="Model Run:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.model_run = tk.StringVar(value="Current")
        run_frame = tk.Frame(frame)
        run_frame.pack(anchor=tk.W)
        tk.Radiobutton(run_frame, text="Current", variable=self.model_run, value="Current").pack(side=tk.LEFT)
        tk.Radiobutton(run_frame, text="Previous", variable=self.model_run, value="Previous").pack(side=tk.LEFT)

    def _build_output_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Output Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.create_diag = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Create Diagnostic Grids (QPF, CAPE, T, RH, Vis)",
                       variable=self.create_diag).pack(anchor=tk.W)

        self.use_dal = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Use DAL for QPF/CAPE (recommended for better data)",
                       variable=self.use_dal).pack(anchor=tk.W)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(frame, text="Build Weather Grids", command=self._run,
                  bg="lightblue", font=("Arial", 11, "bold"), width=20).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _update_selection(self):
        count = sum(1 for v in self.model_vars.values() if v.get() == "Yes")
        dal_count = sum(1 for alias, v in self.model_vars.items() if v.get() == "Yes" and alias in DAL_MODELS)
        if count == 0:
            self.status_label.config(text="No Models Selected", fg="red")
        else:
            dal_text = f" ({dal_count} with DAL)" if dal_count > 0 else ""
            self.status_label.config(text=f"{count} Model(s) Selected{dal_text}", fg="green")

    def _run(self):
        selected = [alias for alias, v in self.model_vars.items() if v.get() == "Yes"]
        if not selected:
            self.status_label.config(text="ERROR: Select at least 1 model!", fg="red")
            return

        self.callback({
            "models": selected,
            "build_mode": self.build_mode.get(),
            "qualifier_type": self.qualifier_type.get(),
            "smoothing": self.smoothing.get(),
            "thunder_thresh": self.thunder_thresh.get(),
            "fog_thresh": self.fog_thresh.get(),
            "model_run": self.model_run.get(),
            "create_diagnostics": self.create_diag.get(),
            "use_dal": self.use_dal.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Tool(SmartScript.SmartScript):
    """Advanced marine weather grid builder using DAL and shared utilities."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.output_log: List[str] = []

    def log(self, message: str):
        """Log message to console and collector."""
        print(message)
        self.output_log.append(message)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        self.output_log = []

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                self.statusBarMsg("Build cancelled", "S")
                return

        models = varDict["models"]
        smoothing = varDict["smoothing"]
        thunder_thresh = varDict["thunder_thresh"]
        fog_thresh = varDict["fog_thresh"]
        model_run = varDict["model_run"]
        qualifier_type = varDict["qualifier_type"]
        create_diag = varDict["create_diagnostics"]
        use_dal = varDict["use_dal"]

        run_depth = 1 if model_run == "Current" else 2

        self.log("="*80)
        self.log("MARINE WEATHER GRID BUILDER v2")
        self.log("="*80)
        self.log(f"Models: {', '.join(models)}")
        self.log(f"DAL enabled: {use_dal}")

        # Get forecast grid times
        gridinfos = self.getGridInfo("Fcst", "Wx", "SFC", timeRange)
        if not gridinfos:
            self.statusBarMsg("No Wx grids found", "S")
            return

        periods_processed = 0
        total_periods = len(gridinfos)

        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{total_periods}", "R")
            self.log(f"\nPeriod {i+1}/{total_periods}: {grid_tr}")

            # Get model data (including DAL if enabled)
            model_data = self._get_model_data(models, grid_tr, run_depth, use_dal)
            if model_data is None:
                continue

            temp_c, rh, qpf_in, vis_nm, cape = model_data

            # Get forecast wind (in knots)
            wind = self.getGrids("Fcst", "Wind", "SFC", grid_tr, mode="First", noDataError=0)

            # Apply smoothing
            if smoothing > 0:
                sigma = smoothing * thresholds.SMOOTHING_DEFAULTS["SIGMA"]
                if qpf_in is not None:
                    qpf_in = ndimage.gaussian_filter(qpf_in, sigma=sigma, mode="nearest")
                if vis_nm is not None:
                    vis_nm = ndimage.gaussian_filter(vis_nm, sigma=sigma, mode="nearest")

            # Create diagnostic grids
            if create_diag:
                self._create_diagnostics(grid_tr, temp_c, rh, qpf_in, vis_nm, cape, wind)

            # Determine weather conditions
            has_precip = qpf_in > thresholds.PRECIP_INTENSITY_INCHES["MINIMUM"] if qpf_in is not None else None
            has_thunder = (cape > thunder_thresh) & (qpf_in > 0.01) if cape is not None and qpf_in is not None else None
            has_fog = (vis_nm < fog_thresh) & (rh > thresholds.FOG_THRESHOLDS["RH_MIN"]) if vis_nm is not None and rh is not None else None

            # Get existing Wx grid
            wx_grid = self.getGrids("Fcst", "Wx", "SFC", grid_tr, noDataError=0)
            if wx_grid is None:
                continue

            wx_values, keys = wx_grid
            new_wx = np.zeros(wx_values.shape, dtype=int)
            no_wx = "<NoCov>:<NoWx>:<NoInten>:<NoVis>:"

            # Build weather grid point by point
            for ii in range(wx_values.shape[0]):
                for jj in range(wx_values.shape[1]):
                    wx_str = self._determine_weather(
                        ii, jj, has_precip, has_thunder, has_fog,
                        qpf_in, cape, temp_c, wind, thunder_thresh, qualifier_type
                    )

                    if wx_str:
                        try:
                            new_wx[ii, jj] = self.getIndex(wx_str, keys)
                        except Exception:
                            new_wx[ii, jj] = self.getIndex(no_wx, keys)
                    else:
                        new_wx[ii, jj] = self.getIndex(no_wx, keys)

            # Save weather grid
            try:
                self.createGrid("Fcst", "Wx", "WEATHER", (new_wx, keys), grid_tr)
                periods_processed += 1
                self.log(f"✓ Weather grid saved")
            except Exception as e:
                self.log(f"✗ Error saving grid: {e}")

        self.log("\n" + "="*80)
        self.log(f"Complete: {periods_processed}/{total_periods} periods")
        self.statusBarMsg(f"Complete: {periods_processed} periods", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = ModelWx2GUI(root, callback)
        root.mainloop()
        return result[0]

    def _get_model_data(self, models: List[str], grid_tr, run_depth: int, use_dal: bool):
        """Get model data, using DAL for QPF/CAPE when enabled."""
        temp_sum, rh_sum, vis_min, cape_max = None, None, None, None
        temp_cnt, rh_cnt = 0, 0

        # Initialize QPF from DAL or D2D
        qpf_sum = None
        qpf_cnt = 0

        for alias in models:
            # Temperature
            temp = grid_fetch.get_grid(self, alias, "t", "MB1000", grid_tr, run_depth=run_depth, noDataError=0)
            if temp is not None:
                temp_c = thresholds.k_to_c(temp) if np.nanmax(temp) > 200 else temp
                temp_sum = temp_c if temp_sum is None else temp_sum + temp_c
                temp_cnt += 1

            # RH
            rh = grid_fetch.get_grid(self, alias, "rh", "MB1000", grid_tr, run_depth=run_depth, noDataError=0)
            if rh is not None:
                rh_sum = rh if rh_sum is None else rh_sum + rh
                rh_cnt += 1

            # Visibility
            vis = grid_fetch.get_grid(self, alias, "vis", "SFC", grid_tr, run_depth=run_depth, noDataError=0)
            if vis is not None:
                vis_nm = thresholds.meters_to_nm(vis)
                vis_min = vis_nm if vis_min is None else np.minimum(vis_min, vis_nm)

            # CAPE - try DAL first if enabled
            if use_dal and alias in DAL_MODELS:
                cape_grids = dal.fetch_geometry(alias, "CAPE", grid_tr, dataset="atmo")
                if cape_grids:
                    for grid in cape_grids:
                        try:
                            arr = np.array(grid.getRawData())
                            cape_max = arr if cape_max is None else np.maximum(cape_max, arr)
                        except Exception:
                            pass

            # Fallback to D2D CAPE
            if cape_max is None:
                cape = grid_fetch.get_grid(self, alias, "cape", "SFC", grid_tr, run_depth=run_depth, noDataError=0)
                if cape is not None:
                    cape_max = cape if cape_max is None else np.maximum(cape_max, cape)

            # QPF - try DAL first if enabled
            if use_dal and alias in DAL_MODELS:
                qpf_grids = dal.fetch_geometry(alias, "QPF", grid_tr, dataset="atmo")
                if qpf_grids:
                    for grid in qpf_grids:
                        try:
                            arr = np.array(grid.getRawData())
                            qpf_in = thresholds.mm_to_inches(arr)
                            qpf_sum = qpf_in if qpf_sum is None else qpf_sum + qpf_in
                            qpf_cnt += 1
                        except Exception:
                            pass

            # Fallback to D2D QPF
            if qpf_sum is None or qpf_cnt == 0:
                qpf = grid_fetch.get_grid(self, alias, "tp", "SFC", grid_tr, run_depth=run_depth, noDataError=0)
                if qpf is not None:
                    qpf_in = thresholds.mm_to_inches(qpf)
                    qpf_sum = qpf_in if qpf_sum is None else qpf_sum + qpf_in
                    qpf_cnt += 1

        if temp_cnt == 0 and qpf_cnt == 0:
            return None

        temp_avg = temp_sum / temp_cnt if temp_cnt > 0 else None
        rh_avg = rh_sum / rh_cnt if rh_cnt > 0 else None
        qpf_avg = qpf_sum / qpf_cnt if qpf_cnt > 0 else None

        return temp_avg, rh_avg, qpf_avg, vis_min, cape_max

    def _create_diagnostics(self, grid_tr, temp_c, rh, qpf_in, vis_nm, cape, wind):
        """Create diagnostic grids."""
        clip = thresholds.DIAGNOSTIC_CLIPPING

        if qpf_in is not None:
            self.createGrid("Fcst", "modelQPF", "SCALAR",
                            np.clip(qpf_in, 0, clip["QPF_MAX_INCHES"]), grid_tr)

        if cape is not None:
            self.createGrid("Fcst", "modelCAPE", "SCALAR",
                            np.clip(cape, 0, clip["CAPE_MAX_J_KG"]), grid_tr)

        if temp_c is not None:
            temp_f = thresholds.c_to_f(temp_c)
            self.createGrid("Fcst", "modelT", "SCALAR",
                            np.clip(temp_f, clip["TEMP_MIN_F"], clip["TEMP_MAX_F"]), grid_tr)

        if rh is not None:
            self.createGrid("Fcst", "modelRH", "SCALAR",
                            np.clip(rh, clip["RH_MIN_PERCENT"], clip["RH_MAX_PERCENT"]), grid_tr)

        if vis_nm is not None:
            self.createGrid("Fcst", "modelVsby", "SCALAR",
                            np.clip(vis_nm, clip["VIS_MIN_NM"], clip["VIS_MAX_NM"]), grid_tr)

    def _determine_weather(self, ii, jj, has_precip, has_thunder, has_fog,
                            qpf, cape, temp, wind, thunder_thresh, qualifier_type):
        """Determine weather string for a grid point."""
        # Thunder
        if has_thunder is not None and has_thunder[ii, jj]:
            cape_val = cape[ii, jj]
            if cape_val > thresholds.CAPE_THRESHOLDS["HIGH"]:
                cov = "Sct"
            else:
                cov = "Iso"

            is_severe = cape_val > thresholds.CAPE_THRESHOLDS["SEVERE_MIN"]
            intensity = "+" if is_severe else "<NoInten>"
            return f"{cov}:T:{intensity}:<NoVis>:"

        # Precipitation
        if has_precip is not None and has_precip[ii, jj]:
            qpf_val = qpf[ii, jj]
            cape_val = cape[ii, jj] if cape is not None else 0

            # Get wind speed in m/s for convective index
            wind_ms = 0
            if wind is not None:
                wind_kt = np.sqrt(wind[0][ii, jj]**2 + wind[1][ii, jj]**2)
                wind_ms = thresholds.to_mps(wind_kt)

            conv_idx = (cape_val / 1000.0) + (wind_ms / 20.0)

            # Determine qualifier type
            if qualifier_type == "Coverage":
                is_conv = True
            elif qualifier_type == "Probability":
                is_conv = False
            else:  # Auto
                is_conv = conv_idx > thresholds.CAPE_THRESHOLDS["CONVECTIVE_INDEX_THRESHOLD"]

            # Coverage/probability
            if is_conv:
                if qpf_val > thresholds.PRECIP_COVERAGE_INCHES["WIDE_COVERAGE"]:
                    cov = "Wide"
                elif qpf_val > thresholds.PRECIP_COVERAGE_INCHES["NUMEROUS"]:
                    cov = "Num"
                elif qpf_val > thresholds.PRECIP_COVERAGE_INCHES["SCATTERED"]:
                    cov = "Sct"
                else:
                    cov = "Iso"
            else:
                if qpf_val > thresholds.PRECIP_PROBABILITY_INCHES["DEFINITE"]:
                    cov = "Def"
                elif qpf_val > thresholds.PRECIP_PROBABILITY_INCHES["LIKELY"]:
                    cov = "Lkly"
                elif qpf_val > thresholds.PRECIP_PROBABILITY_INCHES["CHANCE"]:
                    cov = "Chc"
                else:
                    cov = "SChc"

            # Intensity
            if qpf_val > thresholds.PRECIP_INTENSITY_INCHES["HEAVY"]:
                intensity = "+"
            elif qpf_val > thresholds.PRECIP_INTENSITY_INCHES["MODERATE"]:
                intensity = "m"
            else:
                intensity = "-"

            # Type (rain vs snow)
            temp_val = temp[ii, jj] if temp is not None else 40  # Default above freezing
            if temp_val < 0:  # Below freezing (Celsius)
                wx_type = "SW" if is_conv else "S"
            else:
                wx_type = "RW" if is_conv else "R"

            return f"{cov}:{wx_type}:{intensity}:<NoVis>:"

        # Fog
        if has_fog is not None and has_fog[ii, jj]:
            return "Patchy:F:<NoInten>:<NoVis>:"

        return None


__all__ = ["Tool"]
