"""
Simple Marine Weather Grid Builder.

A streamlined version of the weather grid builder that creates basic Wx grids
from atmospheric model data (precipitation, thunderstorms, fog) using 
straightforward thresholds and automatic qualifier determination.

Modular rewrite using shared utilities for model aliases, grid fetch, and thresholds.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional

import numpy as np
from scipy import ndimage

import SmartScript
from WxMethods import *

import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Populate"]
VariableList = []

# Available atmospheric models
ATMO_MODELS = ["GFS", "ECMWF", "CMC", "UKMET"]


class SimpleModelWxGUI:
    """Simple GUI for weather grid builder."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Simple Weather Grid Builder")
        self.master.geometry("550x700")
        self.master.resizable(True, True)

        self.model_vars: Dict[str, tk.StringVar] = {}
        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Simple Weather Grid Builder",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Build Wx grids from atmospheric models",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 15))

        # Model selection
        self._build_model_frame(main)

        # Parameters
        self._build_params_frame(main)

        # Options
        self._build_options_frame(main)

        # Buttons
        self._build_buttons(main)

    def _build_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Select Atmospheric Models", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        for alias in ATMO_MODELS:
            try:
                cfg = model_aliases.get_model_config(alias)
                label = cfg.display_name
            except KeyError:
                label = alias

            var = tk.StringVar(value="Yes" if alias == "GFS" else "No")
            self.model_vars[alias] = var

            tk.Checkbutton(frame, text=label, variable=var, onvalue="Yes",
                           offvalue="No", font=("Arial", 10)).pack(anchor=tk.W, pady=2)

        self.status_label = tk.Label(frame, text="1 Model Selected", fg="green",
                                     font=("Arial", 10, "bold"))
        self.status_label.pack(pady=(10, 0))

        # Update status when selections change
        for var in self.model_vars.values():
            var.trace("w", lambda *args: self._update_status())

    def _build_params_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Parameters", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        # Smoothing
        tk.Label(frame, text="Spatial Smoothing:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.smoothing = tk.IntVar(value=2)
        tk.Scale(frame, from_=0, to=5, orient=tk.HORIZONTAL, variable=self.smoothing,
                 length=200).pack(anchor=tk.W)

        # Fog threshold
        tk.Label(frame, text="Fog Visibility Threshold (NM):",
                 font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.fog_thresh = tk.DoubleVar(value=3.0)
        tk.Scale(frame, from_=0.5, to=6.0, resolution=0.5, orient=tk.HORIZONTAL,
                 variable=self.fog_thresh, length=200).pack(anchor=tk.W)

        # Model run
        tk.Label(frame, text="Model Run:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.model_run = tk.StringVar(value="Current")
        run_frame = tk.Frame(frame)
        run_frame.pack(anchor=tk.W)
        tk.Radiobutton(run_frame, text="Current", variable=self.model_run,
                       value="Current").pack(side=tk.LEFT)
        tk.Radiobutton(run_frame, text="Previous", variable=self.model_run,
                       value="Previous").pack(side=tk.LEFT, padx=(10, 0))

    def _build_options_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.create_diag = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Create Diagnostic Grids (QPF, CAPE, Temp)",
                       variable=self.create_diag).pack(anchor=tk.W)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(frame, text="Build Weather", command=self._run,
                  bg="lightblue", font=("Arial", 11, "bold"), width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _update_status(self):
        count = sum(1 for v in self.model_vars.values() if v.get() == "Yes")
        if count == 0:
            self.status_label.config(text="No Models Selected", fg="red")
        else:
            self.status_label.config(text=f"{count} Model(s) Selected", fg="green")

    def _run(self):
        selected = [alias for alias, var in self.model_vars.items() if var.get() == "Yes"]
        if not selected:
            self.status_label.config(text="ERROR: Select at least 1 model!", fg="red")
            return

        self.callback({
            "models": selected,
            "smoothing": self.smoothing.get(),
            "fog_thresh": self.fog_thresh.get(),
            "model_run": self.model_run.get(),
            "create_diagnostics": self.create_diag.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Simple weather grid builder using model data."""

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

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                self.statusBarMsg("Build cancelled", "S")
                return

        models = varDict["models"]
        smoothing = varDict["smoothing"]
        fog_thresh = varDict["fog_thresh"]
        model_run = varDict["model_run"]
        create_diag = varDict["create_diagnostics"]

        run_depth = 1 if model_run == "Current" else 2

        self.log("="*70)
        self.log("SIMPLE WEATHER GRID BUILDER")
        self.log("="*70)
        self.log(f"Models: {', '.join(models)}")
        self.log(f"Smoothing: {smoothing}, Fog threshold: {fog_thresh} NM")

        # Get Wx grid times
        gridinfos = self.getGridInfo("Fcst", "Wx", "SFC", timeRange)
        if not gridinfos:
            self.statusBarMsg("No Wx grids found", "S")
            return

        total = len(gridinfos)
        processed = 0

        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{total}", "R")
            self.log(f"\nPeriod {i+1}/{total}: {grid_tr}")

            # Get model data
            model_data = self._get_model_data(models, grid_tr, run_depth)
            if model_data is None:
                continue

            temp_c, rh, qpf_in, vis_nm, cape = model_data

            # Apply smoothing
            if smoothing > 0:
                sigma = smoothing * thresholds.SMOOTHING_DEFAULTS["SIGMA"]
                if qpf_in is not None:
                    qpf_in = ndimage.gaussian_filter(qpf_in, sigma=sigma, mode="nearest")
                if vis_nm is not None:
                    vis_nm = ndimage.gaussian_filter(vis_nm, sigma=sigma, mode="nearest")

            # Create diagnostic grids
            if create_diag:
                self._create_diagnostics(grid_tr, qpf_in, cape, temp_c)

            # Determine conditions
            has_precip = qpf_in > thresholds.PRECIP_INTENSITY_INCHES["MINIMUM"] if qpf_in is not None else None
            has_thunder = (cape > thresholds.CAPE_THRESHOLDS["THUNDER_MIN"]) if cape is not None else None
            has_fog = None
            if vis_nm is not None and rh is not None:
                has_fog = (vis_nm < fog_thresh) & (rh > thresholds.FOG_THRESHOLDS["RH_MIN"])

            # Get existing Wx grid
            wx_grid = self.getGrids("Fcst", "Wx", "SFC", grid_tr, noDataError=0)
            if wx_grid is None:
                continue

            wx_values, keys = wx_grid
            new_wx = np.zeros(wx_values.shape, dtype=int)
            no_wx = "<NoCov>:<NoWx>:<NoInten>:<NoVis>:"

            # Build weather grid
            for ii in range(wx_values.shape[0]):
                for jj in range(wx_values.shape[1]):
                    wx_str = self._determine_weather(
                        ii, jj, has_precip, has_thunder, has_fog, qpf_in, cape, temp_c
                    )

                    if wx_str:
                        try:
                            new_wx[ii, jj] = self.getIndex(wx_str, keys)
                        except Exception:
                            new_wx[ii, jj] = self.getIndex(no_wx, keys)
                    else:
                        new_wx[ii, jj] = self.getIndex(no_wx, keys)

            # Save grid
            try:
                self.createGrid("Fcst", "Wx", "WEATHER", (new_wx, keys), grid_tr)
                processed += 1
                self.log("✓ Weather grid saved")
            except Exception as e:
                self.log(f"✗ Error: {e}")

        self.log("\n" + "="*70)
        self.log(f"Complete: {processed}/{total} periods")
        self.statusBarMsg(f"Complete: {processed} periods", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = SimpleModelWxGUI(root, callback)
        root.mainloop()
        return result[0]

    def _get_model_data(self, models: List[str], grid_tr, run_depth: int):
        """Get averaged model data."""
        temp_sum, rh_sum, qpf_sum = None, None, None
        vis_min, cape_max = None, None
        temp_cnt, rh_cnt, qpf_cnt = 0, 0, 0

        for alias in models:
            # Temperature
            temp = grid_fetch.get_grid(self, alias, "t", "MB1000", grid_tr,
                                       run_depth=run_depth, noDataError=0)
            if temp is not None:
                temp_c = thresholds.k_to_c(temp) if np.nanmax(temp) > 200 else temp
                temp_sum = temp_c if temp_sum is None else temp_sum + temp_c
                temp_cnt += 1

            # RH
            rh = grid_fetch.get_grid(self, alias, "rh", "MB1000", grid_tr,
                                     run_depth=run_depth, noDataError=0)
            if rh is not None:
                rh_sum = rh if rh_sum is None else rh_sum + rh
                rh_cnt += 1

            # Visibility
            vis = grid_fetch.get_grid(self, alias, "vis", "SFC", grid_tr,
                                      run_depth=run_depth, noDataError=0)
            if vis is not None:
                vis_nm = thresholds.meters_to_nm(vis)
                vis_min = vis_nm if vis_min is None else np.minimum(vis_min, vis_nm)

            # CAPE
            cape = grid_fetch.get_grid(self, alias, "cape", "SFC", grid_tr,
                                       run_depth=run_depth, noDataError=0)
            if cape is not None:
                cape_max = cape if cape_max is None else np.maximum(cape_max, cape)

            # QPF
            qpf = grid_fetch.get_grid(self, alias, "tp", "SFC", grid_tr,
                                      run_depth=run_depth, noDataError=0)
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

    def _create_diagnostics(self, grid_tr, qpf, cape, temp):
        """Create diagnostic grids."""
        clip = thresholds.DIAGNOSTIC_CLIPPING

        if qpf is not None:
            self.createGrid("Fcst", "modelQPF", "SCALAR",
                            np.clip(qpf, 0, clip["QPF_MAX_INCHES"]), grid_tr)

        if cape is not None:
            self.createGrid("Fcst", "modelCAPE", "SCALAR",
                            np.clip(cape, 0, clip["CAPE_MAX_J_KG"]), grid_tr)

        if temp is not None:
            temp_f = thresholds.c_to_f(temp)
            self.createGrid("Fcst", "modelT", "SCALAR",
                            np.clip(temp_f, clip["TEMP_MIN_F"], clip["TEMP_MAX_F"]), grid_tr)

    def _determine_weather(self, ii, jj, has_precip, has_thunder, has_fog, qpf, cape, temp):
        """Determine weather string for grid point."""
        prec_thresh = thresholds.PRECIP_INTENSITY_INCHES
        cape_thresh = thresholds.CAPE_THRESHOLDS

        # Thunder (priority)
        if has_thunder is not None and has_precip is not None:
            if has_thunder[ii, jj] and has_precip[ii, jj]:
                cape_val = cape[ii, jj]
                cov = "Sct" if cape_val > cape_thresh["HIGH"] else "Iso"
                intensity = "+" if cape_val > cape_thresh["SEVERE_MIN"] else "<NoInten>"
                return f"{cov}:T:{intensity}:<NoVis>:"

        # Precipitation
        if has_precip is not None and has_precip[ii, jj]:
            qpf_val = qpf[ii, jj]

            # Coverage
            if qpf_val > prec_thresh["HEAVY"]:
                cov = "Wide"
            elif qpf_val > prec_thresh["MODERATE"]:
                cov = "Sct"
            else:
                cov = "Iso"

            # Intensity
            if qpf_val > prec_thresh["HEAVY"]:
                intensity = "+"
            elif qpf_val > prec_thresh["MODERATE"]:
                intensity = "m"
            else:
                intensity = "-"

            # Type
            if temp is not None and temp[ii, jj] < 0:
                wx_type = "S"
            else:
                wx_type = "R"

            return f"{cov}:{wx_type}:{intensity}:<NoVis>:"

        # Fog
        if has_fog is not None and has_fog[ii, jj]:
            return "Patchy:F:<NoInten>:<NoVis>:"

        return None


__all__ = ["Procedure"]

