"""
Grid Comparison Tool - Compare two model/forecast grids and create difference analysis.

Modular rewrite using shared utilities for model alias resolution.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript
import AbsTime

import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Edit"]
WeatherElementEdited = "DifferenceGrid"
HideTool = 0
ScreenList = ["Wind", "WaveHeight"]


# Available models for comparison
COMPARISON_MODELS = [
    ("GFS (Global Forecast System)", "GFS", 4),
    ("ECMWF (European Centre)", "ECMWF", 2),
    ("CMC (Canadian Global)", "CMC", 4),
    ("UKMET (UK Met Office)", "UKMET", 4),
    ("GEFS Mean (GFS Ensemble)", "GEFS", 4),
    ("Official (Published Grid)", "OFFICIAL", 0),
    ("Fcst (Forecast Grid)", "FCST", 0),
]


class GridCompareGUI:
    """GUI for grid comparison parameter selection."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Grid Comparison Tool")
        self.master.geometry("500x600")
        self.result = {"cancelled": True}

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self.master, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Grid Comparison Analysis", font=("Arial", 14, "bold")).pack(pady=(0, 15))

        # Weather Element
        ttk.Label(main, text="Weather Element:").pack(anchor=tk.W)
        self.element_var = tk.StringVar(value="Wind")
        ttk.Combobox(main, textvariable=self.element_var, values=["Wind", "WaveHeight"], width=15).pack(anchor=tk.W, pady=(0, 10))

        # Wind components
        self.wind_frame = ttk.LabelFrame(main, text="Wind Components", padding=5)
        self.wind_frame.pack(fill=tk.X, pady=(0, 10))

        self.wind_speed_var = tk.BooleanVar(value=True)
        self.wind_dir_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.wind_frame, text="Wind Speed", variable=self.wind_speed_var).pack(anchor=tk.W)
        ttk.Checkbutton(self.wind_frame, text="Wind Direction", variable=self.wind_dir_var).pack(anchor=tk.W)

        self.element_var.trace("w", self._toggle_wind_options)

        # Grid Source 1
        ttk.Label(main, text="Grid Source 1:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 5))
        self.model1_var = tk.StringVar(value=COMPARISON_MODELS[0][0])
        ttk.Combobox(main, textvariable=self.model1_var, values=[m[0] for m in COMPARISON_MODELS], width=30).pack(anchor=tk.W)

        ttk.Label(main, text="Previous Run:").pack(anchor=tk.W)
        self.prev_run1_var = tk.StringVar(value="0")
        ttk.Combobox(main, textvariable=self.prev_run1_var, values=["0", "1", "2", "3"], width=10).pack(anchor=tk.W)

        ttk.Label(main, text="Time Offset (hrs):").pack(anchor=tk.W)
        self.offset1_var = tk.StringVar(value="0")
        ttk.Entry(main, textvariable=self.offset1_var, width=10).pack(anchor=tk.W, pady=(0, 10))

        # Grid Source 2
        ttk.Label(main, text="Grid Source 2:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 5))
        self.model2_var = tk.StringVar(value=COMPARISON_MODELS[1][0] if len(COMPARISON_MODELS) > 1 else COMPARISON_MODELS[0][0])
        ttk.Combobox(main, textvariable=self.model2_var, values=[m[0] for m in COMPARISON_MODELS], width=30).pack(anchor=tk.W)

        ttk.Label(main, text="Previous Run:").pack(anchor=tk.W)
        self.prev_run2_var = tk.StringVar(value="0")
        ttk.Combobox(main, textvariable=self.prev_run2_var, values=["0", "1", "2", "3"], width=10).pack(anchor=tk.W)

        ttk.Label(main, text="Time Offset (hrs):").pack(anchor=tk.W)
        self.offset2_var = tk.StringVar(value="0")
        ttk.Entry(main, textvariable=self.offset2_var, width=10).pack(anchor=tk.W, pady=(0, 10))

        # Create grid option
        self.create_grid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="Create Difference Grid(s)", variable=self.create_grid_var).pack(anchor=tk.W, pady=(10, 0))

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        ttk.Button(btn_frame, text="Execute", command=self._on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.LEFT)

    def _toggle_wind_options(self, *args):
        if self.element_var.get() == "Wind":
            self.wind_frame.pack(fill=tk.X, pady=(0, 10))
        else:
            self.wind_frame.pack_forget()

    def _get_alias_from_display(self, display_name: str) -> str:
        for name, alias, _ in COMPARISON_MODELS:
            if name == display_name:
                return alias
        return "GFS"

    def _on_ok(self):
        try:
            self.result = {
                "cancelled": False,
                "element": self.element_var.get(),
                "wind_speed": self.wind_speed_var.get(),
                "wind_direction": self.wind_dir_var.get(),
                "alias1": self._get_alias_from_display(self.model1_var.get()),
                "alias2": self._get_alias_from_display(self.model2_var.get()),
                "prev_run1": int(self.prev_run1_var.get()),
                "prev_run2": int(self.prev_run2_var.get()),
                "offset1": int(self.offset1_var.get()),
                "offset2": int(self.offset2_var.get()),
                "create_grid": self.create_grid_var.get(),
            }
            self.master.destroy()
        except ValueError:
            pass

    def _on_cancel(self):
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Grid comparison procedure using shared utilities."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        params = self._get_parameters()
        if not params or params.get("cancelled", True):
            return

        try:
            self._perform_comparison(editArea, timeRange, params)
        except Exception as e:
            self.statusBarMsg(f"Error in GridComparison: {e}", "S")

    def _get_parameters(self) -> Optional[Dict]:
        root = tk.Tk()
        gui = GridCompareGUI(root, lambda: None)
        root.mainloop()
        return gui.result

    def _perform_comparison(self, editArea, timeRange, params):
        """Perform the grid comparison analysis."""
        self.statusBarMsg("Starting grid comparison...", "R")

        fcst = self.mutableID().modelIdentifier()
        grid_infos = self.getGridInfo(fcst, params["element"], "SFC", timeRange)

        if not grid_infos:
            self.statusBarMsg(f"No {params['element']} grids found", "S")
            return

        for i, grid_info in enumerate(grid_infos):
            grid_tr = grid_info.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{len(grid_infos)}", "R")

            # Get grids with time offset
            grid1 = self._get_comparison_grid(
                params["alias1"],
                params["element"],
                grid_tr,
                params["offset1"],
                params["prev_run1"],
                params.get("wind_speed", True),
                params.get("wind_direction", False),
            )

            grid2 = self._get_comparison_grid(
                params["alias2"],
                params["element"],
                grid_tr,
                params["offset2"],
                params["prev_run2"],
                params.get("wind_speed", True),
                params.get("wind_direction", False),
            )

            if grid1 is None or grid2 is None:
                continue

            # Calculate differences
            if params["element"] == "Wind" and isinstance(grid1, dict):
                self._process_wind_components(grid1, grid2, grid_tr, params)
            else:
                self._process_scalar(grid1, grid2, grid_tr, params)

        self.statusBarMsg("Grid comparison complete", "R")

    def _get_comparison_grid(self, alias: str, element: str, grid_tr, offset_hrs: int, prev_run: int, use_speed: bool, use_dir: bool):
        """Retrieve grid for comparison with time offset."""
        # Apply time offset
        if offset_hrs != 0:
            start_secs = grid_tr.startTime().unixTime() + (offset_hrs * 3600)
            end_secs = grid_tr.endTime().unixTime() + (offset_hrs * 3600)
            target_tr = self.createTimeRange(AbsTime.AbsTime(start_secs), AbsTime.AbsTime(end_secs))
        else:
            target_tr = grid_tr

        # Get the grid using grid_fetch
        run_depth = max(1, prev_run + 1)
        grid = grid_fetch.get_grid(self, alias, element, "SFC", target_tr, run_depth=run_depth, mode="First", noDataError=0)

        if grid is None:
            return None

        if element == "Wind":
            if isinstance(grid, tuple) and len(grid) == 2:
                speed, direction = grid
                result = {}
                if use_speed:
                    result["speed"] = speed
                if use_dir:
                    result["direction"] = direction
                return result if result else None
        return grid

    def _process_wind_components(self, grid1: Dict, grid2: Dict, grid_tr, params):
        """Process wind speed and direction components."""
        for component in ["speed", "direction"]:
            if component not in grid1 or component not in grid2:
                continue

            if component == "direction":
                diff = self._calc_direction_diff(grid1[component], grid2[component])
                grid_name = "WindDirectionDiff"
                min_val, max_val = -180.0, 180.0
            else:
                diff = grid1[component] - grid2[component]
                grid_name = "WindSpeedDiff"
                min_val, max_val = -40.0, 40.0

            if params["create_grid"]:
                self.createGrid("Fcst", grid_name, "SCALAR", diff, grid_tr, minAllowedValue=min_val, maxAllowedValue=max_val)

    def _process_scalar(self, grid1, grid2, grid_tr, params):
        """Process scalar grids like WaveHeight."""
        diff = grid1 - grid2
        if params["create_grid"]:
            self.createGrid("Fcst", "GridDiff", "SCALAR", diff, grid_tr, minAllowedValue=-999.0, maxAllowedValue=999.0)

    def _calc_direction_diff(self, dir1, dir2):
        """Calculate angular difference handling wrap-around."""
        diff = dir1 - dir2
        diff = np.where(diff > 180, diff - 360, diff)
        diff = np.where(diff < -180, diff + 360, diff)
        return diff


__all__ = ["Procedure"]

