"""
Analyze_MarineStorms - Identify storms and create storm edit areas.

Detects storm features from model MSLP and/or wind grids, then creates:

  * **StormExtent** grid -- each storm labeled 1, 2, 3, ... so regions
    are visible on the GFE display.
  * **StormIntensity** grid -- max wind (kt) or pressure anomaly in each
    storm footprint, giving an at-a-glance intensity map.
  * **Named edit areas** per storm (``Storm_001``, ``Storm_002``, ...)
    so the forecaster can select a storm area and run a blend tool
    (e.g. Blend_StormArea) restricted to just that region.

Typical workflow::

    1. Select time range, run Analyze_MarineStorms.
    2. View StormExtent / StormIntensity grids.
    3. Select ``Storm_001`` from the edit-area list.
    4. Run Blend_StormArea with model weights tuned for that storm.

Uses shared utilities (grid_fetch, model_aliases, thresholds).
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript

import grid_fetch
import model_aliases

from .storm_identification import identify_storms, StormFeature

MenuItems = ["Edit"]
VariableList = []

# Models that carry MSLP / Wind
ANALYSIS_MODELS = ["GFS", "ECMWF", "CMC"]


# ===========================================================================
# GUI
# ===========================================================================

class AnalyzeStormsGUI:
    """Configuration GUI for storm identification."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Analyze Marine Storms")
        self.master.geometry("550x620")
        self._build_ui()

    # ---- layout ----------------------------------------------------------

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        tk.Label(main, text="Analyze Marine Storms",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Identify storms and create edit areas",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 15))

        self._build_model_frame(main)
        self._build_detection_frame(main)
        self._build_params_frame(main)
        self._build_output_frame(main)
        self._build_buttons(main)

    def _build_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Model Source", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.model_var = tk.StringVar(value="GFS")
        for m in ANALYSIS_MODELS:
            tk.Radiobutton(frame, text=m, variable=self.model_var,
                           value=m, font=("Arial", 10)).pack(anchor=tk.W)

    def _build_detection_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Detection Method", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.method_var = tk.StringVar(value="pressure")
        tk.Radiobutton(frame, text="MSLP minima (recommended)",
                       variable=self.method_var, value="pressure",
                       font=("Arial", 10)).pack(anchor=tk.W)
        tk.Radiobutton(frame, text="Wind speed maxima",
                       variable=self.method_var, value="wind",
                       font=("Arial", 10)).pack(anchor=tk.W)

    def _build_params_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Parameters", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))

        # Separation
        row1 = tk.Frame(frame)
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="Min separation (km):", width=22,
                 anchor=tk.W).pack(side=tk.LEFT)
        self.sep_var = tk.IntVar(value=500)
        tk.Scale(row1, from_=200, to=1000, orient=tk.HORIZONTAL,
                 variable=self.sep_var, length=180).pack(side=tk.LEFT)

        # Pressure anomaly
        row2 = tk.Frame(frame)
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="Pressure anomaly (hPa):", width=22,
                 anchor=tk.W).pack(side=tk.LEFT)
        self.anom_var = tk.DoubleVar(value=4.0)
        tk.Spinbox(row2, from_=2, to=12, increment=1,
                   textvariable=self.anom_var, width=5).pack(side=tk.LEFT)

        # Wind threshold
        row3 = tk.Frame(frame)
        row3.pack(fill=tk.X, pady=2)
        tk.Label(row3, text="Min wind (kt):", width=22,
                 anchor=tk.W).pack(side=tk.LEFT)
        self.wind_var = tk.DoubleVar(value=34.0)
        tk.Spinbox(row3, from_=20, to=64, increment=2,
                   textvariable=self.wind_var, width=5).pack(side=tk.LEFT)

        # Search radius
        row4 = tk.Frame(frame)
        row4.pack(fill=tk.X, pady=2)
        tk.Label(row4, text="Storm radius (km):", width=22,
                 anchor=tk.W).pack(side=tk.LEFT)
        self.radius_var = tk.IntVar(value=500)
        tk.Scale(row4, from_=200, to=1000, orient=tk.HORIZONTAL,
                 variable=self.radius_var, length=180).pack(side=tk.LEFT)

    def _build_output_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Output", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.create_edit_areas = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Create named edit areas per storm",
                       variable=self.create_edit_areas,
                       font=("Arial", 10)).pack(anchor=tk.W)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(12, 0))
        tk.Button(frame, text="Run Analysis", command=self._run,
                  bg="lightblue", font=("Arial", 11, "bold"),
                  width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel,
                  width=10).pack(side=tk.LEFT)

    # ---- actions ---------------------------------------------------------

    def _run(self):
        self.callback({
            "model": self.model_var.get(),
            "method": self.method_var.get(),
            "min_separation_km": self.sep_var.get(),
            "pressure_anomaly_hpa": self.anom_var.get(),
            "wind_threshold_kt": self.wind_var.get(),
            "search_radius_km": self.radius_var.get(),
            "create_edit_areas": self.create_edit_areas.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


# ===========================================================================
# Procedure
# ===========================================================================

class Procedure(SmartScript.SmartScript):
    """Identify marine storms and create edit areas."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def execute(self, editArea, timeRange, varDict=None):
        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                self.statusBarMsg("Analysis cancelled", "S")
                return

        model = varDict["model"]
        method = varDict["method"]

        # Get forecast grid times
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
        if not gridinfos:
            self.statusBarMsg("No grids in selected time range", "S")
            return

        # Build lat/lon grids from GFE coordinate system
        lat_grid, lon_grid = self._get_latlon_grids()

        total = len(gridinfos)
        for idx, gi in enumerate(gridinfos):
            tr = gi.gridTime()
            self.statusBarMsg(
                "Analyzing storms %d/%d" % (idx + 1, total), "R")

            pressure, wind_speed = self._fetch_fields(model, method, tr)
            if pressure is None and wind_speed is None:
                continue

            storms = identify_storms(
                lat_grid, lon_grid,
                pressure=pressure,
                wind_speed=wind_speed,
                min_separation_km=float(varDict["min_separation_km"]),
                min_pressure_anomaly_hpa=float(varDict["pressure_anomaly_hpa"]),
                min_wind_threshold_kt=float(varDict["wind_threshold_kt"]),
                search_radius_km=float(varDict["search_radius_km"]),
            )

            self._create_output_grids(storms, tr)

            if varDict["create_edit_areas"]:
                self._create_storm_edit_areas(storms)

        self.statusBarMsg("Storm analysis complete", "R")

    # ---- helpers ---------------------------------------------------------

    def _show_gui(self):
        root = tk.Tk()
        result = [None]

        def cb(values):
            result[0] = values

        AnalyzeStormsGUI(root, cb)
        root.mainloop()
        return result[0]

    def _get_latlon_grids(self):
        """Build lat/lon 2-D arrays from the GFE grid location."""
        gridLoc = self.getGridLoc()
        lat_grid = gridLoc.getLatLonGrid()[1]
        lon_grid = gridLoc.getLatLonGrid()[0]
        # getLatLonGrid returns (lon, lat) as flat or shaped arrays.
        # Reshape if needed.
        ny, nx = self.getGridShape()
        if lat_grid.shape != (ny, nx):
            lat_grid = lat_grid.reshape(ny, nx)
            lon_grid = lon_grid.reshape(ny, nx)
        return lat_grid, lon_grid

    def _fetch_fields(self, model, method, tr):
        """Return (pressure, wind_speed) ndarrays or Nones."""
        pressure = None
        wind_speed = None

        if method == "pressure":
            pressure = self._get_pressure(model, tr)
            # Also grab wind for intensity classification
            wind_data = self._get_wind(model, tr)
            if wind_data is not None:
                wind_speed = wind_data[0]
        else:
            wind_data = self._get_wind(model, tr)
            if wind_data is not None:
                wind_speed = wind_data[0]

        return pressure, wind_speed

    def _get_pressure(self, model, tr):
        """Retrieve MSLP in hPa."""
        for elem, level in [("PMSL", "0.0MSL"), ("Pressure", "SFC"),
                            ("MSLP", "SFC"), ("pmsl", "SFC")]:
            try:
                grid = grid_fetch.get_grid(
                    self, model, elem, level, tr,
                    run_depth=2, mode="First", noDataError=0)
                if grid is not None:
                    if np.nanmax(grid) > 10000:
                        grid = grid / 100.0
                    return grid
            except Exception:
                continue
        return None

    def _get_wind(self, model, tr):
        """Retrieve surface wind vector (mag, dir)."""
        try:
            return grid_fetch.get_vector_grid(
                self, model, "Wind", "SFC", tr,
                run_depth=2, mode="First", noDataError=0)
        except Exception:
            return None

    # ---- output ----------------------------------------------------------

    def _create_output_grids(self, storms, tr):
        """Create StormExtent and StormIntensity grids."""
        ref = self.newGrid(0.0)

        extent = np.zeros_like(ref)
        intensity = np.zeros_like(ref)

        for i, storm in enumerate(storms):
            label_val = float(i + 1)
            if storm.extent_mask is not None and storm.extent_mask.shape == ref.shape:
                extent = np.where(storm.extent_mask, label_val, extent)

                # Intensity: prefer max_wind, fall back to pressure anomaly
                if storm.max_wind is not None:
                    ival = storm.max_wind
                elif storm.min_pressure is not None:
                    ival = 1013.0 - storm.min_pressure
                else:
                    ival = label_val
                intensity = np.where(storm.extent_mask, ival, intensity)

        self.createGrid("Fcst", "StormExtent", "SCALAR", extent, tr,
                        minAllowedValue=0.0, maxAllowedValue=10.0,
                        precision=0)
        self.createGrid("Fcst", "StormIntensity", "SCALAR", intensity, tr,
                        minAllowedValue=0.0, maxAllowedValue=150.0)

    def _create_storm_edit_areas(self, storms):
        """Save a named edit area for each storm."""
        for storm in storms:
            if storm.extent_mask is None:
                continue
            try:
                ea = self.decodeEditArea(storm.extent_mask)
                self.saveEditArea(storm.storm_id.replace("STORM", "Storm"),
                                  ea)
            except Exception:
                pass


__all__ = ["Procedure"]
