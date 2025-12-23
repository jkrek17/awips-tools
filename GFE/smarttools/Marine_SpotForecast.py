"""
Marine Spot Forecast Tool - Multi-model ensemble point forecasts.

Generates spot forecasts for a specified marine location using an ensemble
of atmospheric and wave models. Provides error bars based on model spread.

Modular rewrite using shared utilities for model aliases, DAL, and thresholds.
"""

from __future__ import annotations

import datetime as dt
import tkinter as tk
from math import atan2, cos, degrees, radians, sin, sqrt
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

import numpy as np
from shapely.geometry import Point

import SmartScript
from ufpy.dataaccess import DataAccessLayer

import dal
import grid_fetch
import model_aliases
import thresholds

MenuItems = ["Consistency"]

# Models available for ensemble
ENSEMBLE_MODELS = ["GFS", "ECMWF", "CMC"]


class MarineSpotForecastGUI:
    """Configuration GUI for marine spot forecast tool."""

    def __init__(self, master, callback, default_lat=35.0, default_lon=-160.0, 
                 prev_models=None):
        self.master = master
        self.callback = callback
        self.master.title("Marine Spot Forecast Configuration")
        self.master.geometry("700x850")
        self.master.resizable(True, True)

        self.default_lat = default_lat
        self.default_lon = default_lon
        self.prev_models = prev_models or ENSEMBLE_MODELS

        self._create_widgets()

    def _create_widgets(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Marine Spot Forecast Configuration",
                 font=("Arial", 16, "bold")).pack(pady=(0, 10))

        # Data Source
        self._create_source_frame(main)

        # Model Selection
        self._create_model_frame(main)

        # Location
        self._create_location_frame(main)

        # Output Options
        self._create_output_frame(main)

        # Info
        self._create_info_frame(main)

        # Buttons
        self._create_buttons(main)

    def _create_source_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Data Source Selection", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.data_source = tk.StringVar(value="Multi-Model")

        tk.Radiobutton(frame, text="Multi-Model Ensemble", variable=self.data_source,
                       value="Multi-Model", font=("Arial", 10)).pack(anchor=tk.W)
        tk.Radiobutton(frame, text="GFE Forecast (with ensemble spread)",
                       variable=self.data_source, value="GFE",
                       font=("Arial", 10)).pack(anchor=tk.W)

    def _create_model_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Ensemble Model Selection", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame, text="Select models for ensemble (Multi-Model mode only)",
                 font=("Arial", 9), fg="gray").pack(anchor=tk.W, pady=(0, 5))

        self.model_vars: Dict[str, tk.StringVar] = {}

        for alias in ENSEMBLE_MODELS:
            try:
                cfg = model_aliases.get_model_config(alias)
                display = cfg.display_name
            except KeyError:
                display = alias

            var = tk.StringVar(value="Yes" if alias in self.prev_models else "No")
            self.model_vars[alias] = var

            tk.Checkbutton(frame, text=display, variable=var, onvalue="Yes",
                           offvalue="No", font=("Arial", 10)).pack(anchor=tk.W, pady=2)

    def _create_location_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Forecast Location", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame, text="Latitude:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.lat_var = tk.StringVar(value=str(self.default_lat))
        tk.Entry(frame, textvariable=self.lat_var, width=15).pack(anchor=tk.W, padx=(20, 0))
        tk.Label(frame, text="(positive = North, negative = South)",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))

        tk.Label(frame, text="Longitude:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.lon_var = tk.StringVar(value=str(self.default_lon))
        tk.Entry(frame, textvariable=self.lon_var, width=15).pack(anchor=tk.W, padx=(20, 0))
        tk.Label(frame, text="(positive = East, negative = West)",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))

    def _create_output_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Output Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.allow_editing = tk.StringVar(value="No")
        tk.Checkbutton(frame, text="Enable CSV Manual Editing", variable=self.allow_editing,
                       onvalue="Yes", offvalue="No", font=("Arial", 10)).pack(anchor=tk.W)

        self.send_intranet = tk.StringVar(value="Yes")
        tk.Checkbutton(frame, text="Send Products to Intranet", variable=self.send_intranet,
                       onvalue="Yes", offvalue="No", font=("Arial", 10)).pack(anchor=tk.W, pady=(10, 0))

    def _create_info_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Information", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame, text="Multi-Model Mode:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        tk.Label(frame, text="  • Uses last 2 cycles from each model",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W)
        tk.Label(frame, text="  • Provides ensemble spread for uncertainty",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W)

        tk.Label(frame, text="GFE Mode:", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(10, 0))
        tk.Label(frame, text="  • Uses GFE forecast with ensemble spread overlay",
                 font=("Arial", 8), fg="gray").pack(anchor=tk.W)

    def _create_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(10, 0))

        tk.Button(frame, text="Generate Forecast", command=self._run,
                  bg="lightblue", font=("Arial", 11, "bold"), width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _run(self):
        try:
            lat = float(self.lat_var.get())
            lon = float(self.lon_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid latitude or longitude")
            return

        selected = [alias for alias, var in self.model_vars.items() if var.get() == "Yes"]
        if not selected and self.data_source.get() == "Multi-Model":
            messagebox.showerror("Error", "Select at least one model for Multi-Model mode")
            return

        self.callback({
            "data_source": self.data_source.get(),
            "selected_models": selected,
            "lat": lat,
            "lon": lon,
            "allow_editing": self.allow_editing.get() == "Yes",
            "send_intranet": self.send_intranet.get() == "Yes",
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Marine spot forecast procedure using multi-model ensemble."""

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
                self.statusBarMsg("Spot forecast cancelled", "S")
                return

        self.log("="*80)
        self.log("MARINE SPOT FORECAST")
        self.log("="*80)
        self.log(f"Location: {varDict['lat']:.4f}N, {varDict['lon']:.4f}W")
        self.log(f"Mode: {varDict['data_source']}")
        self.log(f"Models: {', '.join(varDict['selected_models'])}")

        fcst_point = Point(varDict["lon"], varDict["lat"])

        if varDict["data_source"] == "Multi-Model":
            ensemble_data = self._retrieve_ensemble(fcst_point, timeRange, varDict["selected_models"])
        else:
            ensemble_data = self._retrieve_gfe_with_spread(fcst_point, timeRange, varDict["selected_models"])

        if not ensemble_data:
            self.statusBarMsg("No data retrieved", "S")
            return

        # Generate outputs
        self._generate_output(ensemble_data, varDict)

        self.statusBarMsg("Spot forecast complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = MarineSpotForecastGUI(root, callback)
        root.mainloop()
        return result[0]

    def _retrieve_ensemble(self, point: Point, time_range, selected_models: List[str]) -> Dict:
        """Retrieve multi-model ensemble data for a point."""
        ensemble: Dict[str, Dict] = {
            "wind_speed": {"values": [], "times": []},
            "wind_dir": {"values": [], "times": []},
            "wind_gust": {"values": [], "times": []},
            "wave_height": {"values": [], "times": []},
            "wave_dir": {"values": [], "times": []},
            "wave_period": {"values": [], "times": []},
        }

        models_used = []

        for alias in selected_models:
            self.statusBarMsg(f"Retrieving {alias}...", "R")
            self.log(f"\nProcessing model: {alias}")

            try:
                cfg = model_aliases.get_model_config(alias)
            except KeyError:
                self.log(f"  Unknown alias: {alias}")
                continue

            # Get atmospheric data via DAL
            if cfg.dal_location:
                atmo_data = self._fetch_atmo_point(cfg, point, time_range)
                if atmo_data:
                    for key in ["wind_speed", "wind_dir", "wind_gust"]:
                        if key in atmo_data:
                            ensemble[key]["values"].extend(atmo_data[key]["values"])
                            ensemble[key]["times"].extend(atmo_data[key]["times"])
                    models_used.append(alias)
                    self.log(f"  ✓ Atmospheric data retrieved")

            # Get wave data if available
            if cfg.wave and cfg.wave.dal_location:
                wave_data = self._fetch_wave_point(cfg.wave, point, time_range)
                if wave_data:
                    for key in ["wave_height", "wave_dir", "wave_period"]:
                        if key in wave_data:
                            ensemble[key]["values"].extend(wave_data[key]["values"])
                            ensemble[key]["times"].extend(wave_data[key]["times"])
                    self.log(f"  ✓ Wave data retrieved")

        ensemble["_models_used"] = models_used
        self.log(f"\nModels used: {', '.join(models_used)}")
        return ensemble

    def _fetch_atmo_point(self, cfg, point: Point, time_range) -> Optional[Dict]:
        """Fetch atmospheric data for a point using DAL."""
        try:
            req = DataAccessLayer.newDataRequest()
            req.setDatatype("grid")
            req.setLocationNames(cfg.dal_location)
            req.setParameters("uW", "vW")

            level = cfg.default_levels.get("wind") or "10FHAG"
            req.setLevels(level)
            req.setEnvelope(point)

            times = DataAccessLayer.getAvailableTimes(req)
            if not times:
                return None

            # Get last 2 cycles worth of data
            data = DataAccessLayer.getGeometryData(req, times[-48:] if len(times) > 48 else times)

            result: Dict[str, Dict] = {
                "wind_speed": {"values": [], "times": []},
                "wind_dir": {"values": [], "times": []},
                "wind_gust": {"values": [], "times": []},
            }

            for grid in data or []:
                try:
                    valid_dt = self._extract_valid_time(grid)
                    if valid_dt is None:
                        continue

                    param = grid.getParameterName()
                    value = grid.getNumber(param)
                    if value is None:
                        continue

                    if param == "uW":
                        result["_u"] = result.get("_u", {})
                        result["_u"][valid_dt] = thresholds.to_knots(float(value))
                    elif param == "vW":
                        result["_v"] = result.get("_v", {})
                        result["_v"][valid_dt] = thresholds.to_knots(float(value))

                except Exception:
                    continue

            # Calculate magnitude and direction
            if "_u" in result and "_v" in result:
                for valid_dt in result["_u"]:
                    if valid_dt in result["_v"]:
                        u = result["_u"][valid_dt]
                        v = result["_v"][valid_dt]
                        speed = sqrt(u**2 + v**2)
                        direction = (270 - degrees(atan2(v, u))) % 360

                        result["wind_speed"]["values"].append(speed)
                        result["wind_speed"]["times"].append(valid_dt)
                        result["wind_dir"]["values"].append(direction)
                        result["wind_dir"]["times"].append(valid_dt)
                        # Estimate gust as 1.3x speed
                        result["wind_gust"]["values"].append(speed * 1.3)
                        result["wind_gust"]["times"].append(valid_dt)

            return result if result["wind_speed"]["values"] else None

        except Exception as e:
            self.log(f"  Error fetching atmospheric data: {e}")
            return None

    def _fetch_wave_point(self, wave_cfg, point: Point, time_range) -> Optional[Dict]:
        """Fetch wave data for a point using DAL."""
        try:
            req = DataAccessLayer.newDataRequest()
            req.setDatatype("grid")
            req.setLocationNames(wave_cfg.dal_location)
            req.setParameters("HTSGW", "DIRPW", "PERPW")

            level = wave_cfg.default_levels.get("wave") or "0.0SFC"
            req.setLevels(level)
            req.setEnvelope(point)

            times = DataAccessLayer.getAvailableTimes(req)
            if not times:
                return None

            data = DataAccessLayer.getGeometryData(req, times[-48:] if len(times) > 48 else times)

            result: Dict[str, Dict] = {
                "wave_height": {"values": [], "times": []},
                "wave_dir": {"values": [], "times": []},
                "wave_period": {"values": [], "times": []},
            }

            for grid in data or []:
                try:
                    valid_dt = self._extract_valid_time(grid)
                    if valid_dt is None:
                        continue

                    param = grid.getParameterName()
                    value = grid.getNumber(param)
                    if value is None:
                        continue

                    value = float(value)

                    if param == "HTSGW":
                        result["wave_height"]["values"].append(value)
                        result["wave_height"]["times"].append(valid_dt)
                    elif param == "DIRPW":
                        result["wave_dir"]["values"].append(value)
                        result["wave_dir"]["times"].append(valid_dt)
                    elif param == "PERPW":
                        result["wave_period"]["values"].append(value)
                        result["wave_period"]["times"].append(valid_dt)

                except Exception:
                    continue

            return result if result["wave_height"]["values"] else None

        except Exception as e:
            self.log(f"  Error fetching wave data: {e}")
            return None

    def _retrieve_gfe_with_spread(self, point: Point, time_range, models: List[str]) -> Dict:
        """Retrieve GFE forecast with ensemble spread overlay."""
        ensemble = self._retrieve_ensemble(point, time_range, models)

        # Also get GFE grids
        try:
            wind = self.getGrids("Fcst", "Wind", "SFC", time_range, mode="First", noDataError=0)
            if wind is not None:
                # Sample at point (simplified - would need proper lat/lon to grid coords)
                ensemble["_gfe_wind"] = wind
        except Exception:
            pass

        return ensemble

    def _extract_valid_time(self, grid) -> Optional[dt.datetime]:
        """Extract valid datetime from a DAL grid object."""
        try:
            data_time = grid.getDataTime()
            start_unix = data_time.startTime().unixTime()
            return dt.datetime.utcfromtimestamp(start_unix)
        except Exception:
            return None

    def _generate_output(self, ensemble: Dict, config: Dict):
        """Generate output products from ensemble data."""
        self.log("\n" + "="*80)
        self.log("ENSEMBLE STATISTICS")
        self.log("="*80)

        for var in ["wind_speed", "wind_gust", "wave_height"]:
            if var in ensemble and ensemble[var]["values"]:
                values = ensemble[var]["values"]
                self.log(f"\n{var.replace('_', ' ').title()}:")
                self.log(f"  Mean: {np.mean(values):.1f}")
                self.log(f"  Min: {np.min(values):.1f}")
                self.log(f"  Max: {np.max(values):.1f}")
                self.log(f"  Std Dev: {np.std(values):.1f}")
                self.log(f"  Samples: {len(values)}")

        models = ensemble.get("_models_used", [])
        self.log(f"\nModels in ensemble: {', '.join(models)}")

    def UVToMagDir(self, u, v):
        """Convert U/V components to magnitude and direction."""
        mag = sqrt(u**2 + v**2)
        direction = (270 - degrees(atan2(v, u))) % 360
        return mag, direction

    def MagDirToUV(self, mag, direction):
        """Convert magnitude and direction to U/V components."""
        rad = radians(270 - direction)
        u = mag * cos(rad)
        v = mag * sin(rad)
        return u, v

    def windDegToStr(self, deg):
        """Convert wind direction degrees to compass string."""
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                      "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        idx = int((deg + 11.25) / 22.5) % 16
        return directions[idx]


__all__ = ["Procedure", "MarineSpotForecastGUI"]
