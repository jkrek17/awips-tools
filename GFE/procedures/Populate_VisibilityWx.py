"""
Populate_VisibilityWx - Visibility and Weather Grid Builder.

Creates:
- Vsby (visibility) grid in nautical miles
- Wx (weather) grid with simple fog and precipitation types

Simple fog and precipitation grids for marine forecasting.
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

# Available atmospheric models for vis/wx
ATMO_MODELS = ["GFS", "ECMWF", "CMC", "UKMET"]


class VisibilityWeatherGUI:
    """GUI for visibility and weather tool."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Populate Visibility & Wx")
        self.master.geometry("550x650")
        self.master.resizable(True, True)

        self.model_vars: Dict[str, tk.StringVar] = {}
        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Populate Visibility & Wx",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Simple fog and precipitation grids for marine forecasting",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 15))

        # Model selection
        self._build_model_frame(main)

        # Visibility options
        self._build_vis_frame(main)

        # Wx options
        self._build_wx_frame(main)

        # Smoothing
        self._build_smoothing_frame(main)

        # Buttons
        self._build_buttons(main)

    def _build_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Select Atmospheric Models", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        for alias in ATMO_MODELS:
            var = tk.StringVar(value="Yes" if alias == "GFS" else "No")
            self.model_vars[alias] = var
            tk.Checkbutton(frame, text=alias, variable=var, onvalue="Yes",
                           offvalue="No", font=("Arial", 10)).pack(anchor=tk.W, pady=2)

        self.status_label = tk.Label(frame, text="1 Model Selected", fg="green",
                                     font=("Arial", 10, "bold"))
        self.status_label.pack(pady=(10, 0))

        for var in self.model_vars.values():
            var.trace("w", lambda *args: self._update_status())

    def _build_vis_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Visibility Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame, text="Create Vsby grid from model visibility data",
                 font=("Arial", 9), fg="gray").pack(anchor=tk.W)

        self.create_vsby = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Create Vsby grid (nautical miles)",
                       variable=self.create_vsby).pack(anchor=tk.W, pady=(5, 0))

        tk.Label(frame, text="Fog Visibility Threshold (NM):",
                 font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.fog_thresh = tk.DoubleVar(value=3.0)
        tk.Scale(frame, from_=0.5, to=6.0, resolution=0.5, orient=tk.HORIZONTAL,
                 variable=self.fog_thresh, length=200).pack(anchor=tk.W)

    def _build_wx_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Weather Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.create_wx = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Create Wx grid",
                       variable=self.create_wx).pack(anchor=tk.W)

        tk.Label(frame, text="Weather types: F (fog), R (rain), S (snow)",
                 font=("Arial", 9), fg="gray").pack(anchor=tk.W)

        tk.Label(frame, text="Min QPF for precip (inches):",
                 font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.precip_thresh = tk.DoubleVar(value=0.01)
        tk.Scale(frame, from_=0.0, to=0.10, resolution=0.01, orient=tk.HORIZONTAL,
                 variable=self.precip_thresh, length=200).pack(anchor=tk.W)

    def _build_smoothing_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Smoothing", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.smoothing = tk.IntVar(value=2)
        tk.Label(frame, text="Spatial Smoothing:").pack(anchor=tk.W)
        tk.Scale(frame, from_=0, to=5, orient=tk.HORIZONTAL,
                 variable=self.smoothing, length=200).pack(anchor=tk.W)

        tk.Label(frame, text="Model Run:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.model_run = tk.StringVar(value="Current")
        run_frame = tk.Frame(frame)
        run_frame.pack(anchor=tk.W)
        tk.Radiobutton(run_frame, text="Current", variable=self.model_run,
                       value="Current").pack(side=tk.LEFT)
        tk.Radiobutton(run_frame, text="Previous", variable=self.model_run,
                       value="Previous").pack(side=tk.LEFT, padx=(10, 0))

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(frame, text="Build Grids", command=self._run,
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
            "create_vsby": self.create_vsby.get(),
            "create_wx": self.create_wx.get(),
            "fog_thresh": self.fog_thresh.get(),
            "precip_thresh": self.precip_thresh.get(),
            "smoothing": self.smoothing.get(),
            "model_run": self.model_run.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Visibility and weather grid builder."""

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
        create_vsby = varDict["create_vsby"]
        create_wx = varDict["create_wx"]
        fog_thresh = varDict["fog_thresh"]
        precip_thresh = varDict["precip_thresh"]
        smoothing = varDict["smoothing"]
        model_run = varDict["model_run"]

        run_depth = 1 if model_run == "Current" else 2

        self.log("=" * 70)
        self.log("POPULATE VISIBILITY & WX")
        self.log("=" * 70)
        self.log(f"Models: {', '.join(models)}")
        self.log(f"Fog threshold: {fog_thresh} NM")
        self.log(f"Precip threshold: {precip_thresh} in")

        if create_wx:
            gridinfos = self.getGridInfo("Fcst", "Wx", "SFC", timeRange)
        else:
            gridinfos = self.getGridInfo("Fcst", "Wind", "SFC", timeRange)

        if not gridinfos:
            self.statusBarMsg("No grids found in time range", "S")
            return

        total = len(gridinfos)
        processed = 0

        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{total}", "R")
            self.log(f"\nPeriod {i+1}/{total}: {grid_tr}")

            model_data = self._get_model_data(models, grid_tr, run_depth)
            if model_data is None:
                continue

            temp_c, rh, qpf_in, vis_nm = model_data

            if smoothing > 0 and vis_nm is not None:
                sigma = smoothing * thresholds.SMOOTHING_DEFAULTS["sigma"]
                vis_nm = ndimage.gaussian_filter(vis_nm, sigma=sigma, mode="nearest")

            if create_vsby and vis_nm is not None:
                vsby_clipped = np.clip(vis_nm, 0.0, 10.0)
                try:
                    self.createGrid("Fcst", "Vsby", "SCALAR", vsby_clipped, grid_tr,
                                    minAllowedValue=0.0, maxAllowedValue=10.0)
                    self.log(f"  Vsby: {np.mean(vsby_clipped):.1f} NM mean, min {np.min(vsby_clipped):.1f}")
                except Exception as e:
                    self.log(f"  Vsby error: {e}")

            if create_wx:
                wx_result = self._build_wx_grid(
                    grid_tr, temp_c, rh, qpf_in, vis_nm,
                    fog_thresh, precip_thresh
                )
                if wx_result:
                    processed += 1

        self.log("\n" + "=" * 70)
        self.log(f"Complete: {processed}/{total} periods")
        self.statusBarMsg(f"Complete: {processed} periods", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = VisibilityWeatherGUI(root, callback)
        root.mainloop()
        return result[0]

    def _get_model_data(self, models: List[str], grid_tr, run_depth: int):
        """Get averaged model data for visibility and weather."""
        temp_sum, rh_sum, qpf_sum = None, None, None
        vis_min = None
        temp_cnt, rh_cnt, qpf_cnt = 0, 0, 0

        for alias in models:
            temp = grid_fetch.get_grid(self, alias, "t", "MB1000", grid_tr,
                                       run_depth=run_depth, noDataError=0)
            if temp is not None:
                temp_c = thresholds.k_to_c(temp) if np.nanmax(temp) > 200 else temp
                temp_sum = temp_c if temp_sum is None else temp_sum + temp_c
                temp_cnt += 1

            rh = grid_fetch.get_grid(self, alias, "rh", "MB1000", grid_tr,
                                     run_depth=run_depth, noDataError=0)
            if rh is not None:
                rh_sum = rh if rh_sum is None else rh_sum + rh
                rh_cnt += 1

            vis = grid_fetch.get_grid(self, alias, "vis", "SFC", grid_tr,
                                      run_depth=run_depth, noDataError=0)
            if vis is not None:
                vis_nm = thresholds.meters_to_nm(vis)
                vis_min = vis_nm if vis_min is None else np.minimum(vis_min, vis_nm)

            qpf = grid_fetch.get_grid(self, alias, "tp", "SFC", grid_tr,
                                      run_depth=run_depth, noDataError=0)
            if qpf is not None:
                qpf_in = thresholds.mm_to_inches(qpf)
                qpf_sum = qpf_in if qpf_sum is None else qpf_sum + qpf_in
                qpf_cnt += 1

        if temp_cnt == 0 and qpf_cnt == 0 and vis_min is None:
            return None

        temp_avg = temp_sum / temp_cnt if temp_cnt > 0 else None
        rh_avg = rh_sum / rh_cnt if rh_cnt > 0 else None
        qpf_avg = qpf_sum / qpf_cnt if qpf_cnt > 0 else None

        return temp_avg, rh_avg, qpf_avg, vis_min

    def _build_wx_grid(self, grid_tr, temp_c, rh, qpf_in, vis_nm,
                       fog_thresh: float, precip_thresh: float) -> bool:
        """Build simple weather grid."""
        wx_grid = self.getGrids("Fcst", "Wx", "SFC", grid_tr, noDataError=0)
        if wx_grid is None:
            self.log("  No existing Wx grid")
            return False

        wx_values, keys = wx_grid
        new_wx = np.zeros(wx_values.shape, dtype=int)
        no_wx = "<NoCov>:<NoWx>:<NoInten>:<NoVis>:"

        has_precip = qpf_in > precip_thresh if qpf_in is not None else None
        has_fog = None
        if vis_nm is not None and rh is not None:
            has_fog = (vis_nm < fog_thresh) & (rh > thresholds.FOG_THRESHOLDS["relative_humidity_min"])

        fog_count = 0
        precip_count = 0

        for ii in range(wx_values.shape[0]):
            for jj in range(wx_values.shape[1]):
                wx_str = None

                if has_precip is not None and has_precip[ii, jj]:
                    if temp_c is not None and temp_c[ii, jj] < 0:
                        wx_str = "Chc:S:-:<NoVis>:"
                    else:
                        wx_str = "Chc:R:-:<NoVis>:"
                    precip_count += 1

                elif has_fog is not None and has_fog[ii, jj]:
                    wx_str = "Patchy:F:<NoInten>:<NoVis>:"
                    fog_count += 1

                if wx_str:
                    try:
                        new_wx[ii, jj] = self.getIndex(wx_str, keys)
                    except Exception:
                        new_wx[ii, jj] = self.getIndex(no_wx, keys)
                else:
                    new_wx[ii, jj] = self.getIndex(no_wx, keys)

        try:
            self.createGrid("Fcst", "Wx", "WEATHER", (new_wx, keys), grid_tr)
            total_pts = wx_values.size
            self.log(f"  Wx: {fog_count} fog pts ({fog_count/total_pts*100:.1f}%), "
                     f"{precip_count} precip pts ({precip_count/total_pts*100:.1f}%)")
            return True
        except Exception as e:
            self.log(f"  Wx error: {e}")
            return False


__all__ = ["Procedure", "VisibilityWeatherGUI"]

