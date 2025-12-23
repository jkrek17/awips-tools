# ----------------------------------------------------------------------------
# OutOfDomainSpot.py
# Multi-model ensemble spot forecast tool with error bars
# Version 1.0 (WORKING VERSION - DO NOT USE IN PRODUCTION)
# 
# Stable version: OutOfDomainSpot_current.py
# ----------------------------------------------------------------------------

import LogStream
import SmartScript
import tkinter as tk
from tkinter import messagebox
import csv
import datetime as dt
from math import sqrt, atan2, degrees, radians, sin, cos
import numpy as np
import os
from shapely.geometry import Point
import time
from ufpy.dataaccess import DataAccessLayer

MenuItems = ["Consistency"]


class MarineSpotForecastGUI:
    def __init__(self, master, callback, default_lat, default_lon, default_model, prev_models):
        self.master = master
        self.callback = callback
        self.master.title("Marine Spot Forecast Configuration")
        self.master.geometry("700x900")
        self.master.resizable(True, True)
        
        self.default_lat = default_lat
        self.default_lon = default_lon
        self.default_model = default_model
        self.prev_models = prev_models
        
        self.createWidgets()
    
    def createWidgets(self):
        # Main frame
        mainFrame = tk.Frame(self.master, padx=15, pady=15)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Marine Spot Forecast Configuration", 
                             font=("Arial", 16, "bold"))
        titleLabel.pack(pady=(0, 10))
        
        # Data Source Selection Frame
        sourceFrame = tk.LabelFrame(mainFrame, text="Data Source Selection", padx=15, pady=10)
        sourceFrame.pack(fill=tk.X, pady=(0, 10))
        
        self.dataSource = tk.StringVar()
        self.dataSource.set(self.default_model if self.default_model in ["Multi-Model", "GFE"] else "Multi-Model")
        
        tk.Radiobutton(sourceFrame, text="Multi-Model", variable=self.dataSource, 
                      value="Multi-Model", font=("Arial", 10)).pack(anchor=tk.W)
        tk.Radiobutton(sourceFrame, text="GFE", variable=self.dataSource, 
                      value="GFE", font=("Arial", 10)).pack(anchor=tk.W)
        
        # Ensemble Model Selection Frame
        modelFrame = tk.LabelFrame(mainFrame, text="Ensemble Model Selection", padx=15, pady=10)
        modelFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(modelFrame, text="Select models to include in ensemble (applies to Multi-Model mode only)", 
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, pady=(0, 5))
        
        self.modelSelections = {}
        models = [
            ("GFS Model", "GFS"),
            ("ECMWF Model", "ECMWF"),
            ("CMC Model", "CMC")
        ]
        
        for displayName, modelId in models:
            var = tk.StringVar()
            var.set("Yes" if modelId in self.prev_models else "No")
            self.modelSelections[modelId] = var
            
            cb = tk.Checkbutton(modelFrame, text=displayName, 
                              variable=var, onvalue="Yes", offvalue="No",
                              anchor=tk.W, font=("Arial", 10))
            cb.pack(fill=tk.X, pady=2)
        
        # Forecast Location Frame
        locationFrame = tk.LabelFrame(mainFrame, text="Forecast Location", padx=15, pady=10)
        locationFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(locationFrame, text="Latitude:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.latVar = tk.StringVar()
        self.latVar.set(str(self.default_lat))
        latEntry = tk.Entry(locationFrame, textvariable=self.latVar, font=("Arial", 10), width=15)
        latEntry.pack(anchor=tk.W, padx=(20, 0))
        tk.Label(locationFrame, text="(degrees, positive = North, negative = South)", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        tk.Label(locationFrame, text="Longitude:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.lonVar = tk.StringVar()
        self.lonVar.set(str(self.default_lon))
        lonEntry = tk.Entry(locationFrame, textvariable=self.lonVar, font=("Arial", 10), width=15)
        lonEntry.pack(anchor=tk.W, padx=(20, 0))
        tk.Label(locationFrame, text="(degrees, positive = East, negative = West)", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Output Options Frame
        outputFrame = tk.LabelFrame(mainFrame, text="Output Options", padx=15, pady=10)
        outputFrame.pack(fill=tk.X, pady=(0, 10))
        
        self.allowEditing = tk.StringVar()
        self.allowEditing.set("No")
        tk.Checkbutton(outputFrame, text="Enable CSV Manual Editing", 
                      variable=self.allowEditing, onvalue="Yes", offvalue="No",
                      anchor=tk.W, font=("Arial", 10)).pack(anchor=tk.W)
        tk.Label(outputFrame, text="  Opens CSV file in LibreOffice for manual editing before generating outputs", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        self.sendToIntranet = tk.StringVar()
        self.sendToIntranet.set("Yes")
        tk.Checkbutton(outputFrame, text="Send Products to Intranet", 
                      variable=self.sendToIntranet, onvalue="Yes", offvalue="No",
                      anchor=tk.W, font=("Arial", 10)).pack(anchor=tk.W, pady=(10, 0))
        tk.Label(outputFrame, text="  Automatically transfer products to web server after generation", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Information Frame
        infoFrame = tk.LabelFrame(mainFrame, text="Information", padx=15, pady=10)
        infoFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(infoFrame, text="Multi-Model Mode:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        tk.Label(infoFrame, text="  • Uses last 2 cycles from each selected model", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(10, 0))
        tk.Label(infoFrame, text="  • Provides ensemble spread (min-max range) for uncertainty visualization", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(10, 0))
        tk.Label(infoFrame, text="  • Combines multiple global models for enhanced forecast reliability", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(10, 0))
        
        tk.Label(infoFrame, text="GFE Mode:", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(10, 0))
        tk.Label(infoFrame, text="  • Uses GFE forecast line with ensemble spread overlay", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(10, 0))
        tk.Label(infoFrame, text="  • Requires time range selection in GFE before running this tool", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(10, 0))
        tk.Label(infoFrame, text="  • Ensemble spread shows model uncertainty around forecaster guidance", 
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(10, 0))
        
        # Buttons Frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(buttonFrame, text="OK", command=self.runTool, 
                 bg="lightblue", font=("Arial", 11, "bold"), width=15).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(buttonFrame, text="Cancel", command=self.cancel, 
                 font=("Arial", 11), width=12).pack(side=tk.LEFT)
    
    def getValues(self):
        """Return dictionary of selected options"""
        selectedModels = []
        for modelId, var in self.modelSelections.items():
            if var.get() == "Yes":
                selectedModels.append(modelId)
        
        # Default to GFS+ECMWF if none selected
        if not selectedModels:
            selectedModels = ['GFS', 'ECMWF']
        
        return {
            "Forecast Data Source": self.dataSource.get(),
            "Latitude": self.latVar.get(),
            "Longitude": self.lonVar.get(),
            "Enable CSV Manual Editing": self.allowEditing.get(),
            "Send Products to Intranet": self.sendToIntranet.get(),
            "selected_models": selectedModels
        }
    
    def runTool(self):
        """Validate and run the tool"""
        try:
            lat = float(self.latVar.get())
            lon = float(self.lonVar.get())
            
            if not -90 <= lat <= 90:
                messagebox.showerror("Error", "Latitude must be between -90 and 90")
                return
            if not -180 <= lon <= 180:
                messagebox.showerror("Error", "Longitude must be between -180 and 180")
                return
        except ValueError:
            messagebox.showerror("Error", "Latitude and Longitude must be valid numbers")
            return
        
        self.callback(self.getValues())
        self.master.destroy()
    
    def cancel(self):
        """Close without running"""
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self._config_file = "/data/local/spot/lastPoint.csv"
        self._spot_dir = "/data/local/spot"
        self._file_retention_days = 15
    
    def windDegToStr(self, deg):
        if deg >= 337.5 or deg < 22.5:
            return "N"
        elif deg < 67.5:
            return "NE"
        elif deg < 112.5:
            return "E"
        elif deg < 157.5:
            return "SE"
        elif deg < 202.5:
            return "S"
        elif deg < 247.5:
            return "SW"
        elif deg < 292.5:
            return "W"
        else:
            return "NW"
    
    def _round_to_3hourly(self, dt_obj):
        """Round datetime to nearest 3-hour synoptic time (00, 03, 06, 09, 12, 15, 18, 21 UTC)"""
        hour = dt_obj.hour
        rounded_hour = 3 * round(hour / 3.0)
        if rounded_hour == 24:
            rounded_hour = 0
            dt_obj = dt_obj + dt.timedelta(days=1)
        return dt_obj.replace(hour=rounded_hour, minute=0, second=0, microsecond=0)
    
    def _load_previous_settings(self):
        try:
            with open(self._config_file) as f:
                lat = f.readline().strip()
                lon = f.readline().strip()
                model = f.readline().strip()
            return lat, lon, model
        except:
            return "34.17", "-73.78", "Multi-Model"
    
    def _save_current_settings(self, lat, lon, model, selected_models=None):
        try:
            os.makedirs(self._spot_dir, mode=0o775, exist_ok=True)
            # Save model selection as comma-separated list if available
            if selected_models:
                model_str = ','.join(selected_models)
            else:
                model_str = model
            with open(self._config_file, "w") as f:
                f.write(f"{lat:.2f}\n{lon:.2f}\n{model_str}")
        except Exception as e:
            LogStream.logProblem(f"Unable to save settings: {str(e)}")
    
    def _format_point_string(self, lat, lon):
        lat_hem = "N" if lat >= 0 else "S"
        lon_hem = "E" if lon >= 0 else "W"
        return f"{abs(lat):.2f}{lat_hem} {abs(lon):.2f}{lon_hem}"
    
    def _get_user_configuration(self):
        try:
            default_lat, default_lon, default_model = self._load_previous_settings()
        except Exception as e:
            LogStream.logProblem(f"Error loading previous settings: {str(e)}")
            default_lat, default_lon, default_model = 40.0, -70.0, "Multi-Model"
        
        # Parse previous model selections if available
        try:
            prev_models = default_model.split(',') if ',' in default_model else ['GFS', 'ECMWF']
        except:
            prev_models = ['GFS', 'ECMWF']
        
        # Show custom tkinter GUI
        self.varDict = None
        
        root = tk.Tk()
        gui = MarineSpotForecastGUI(root, self.guiCallback, default_lat, default_lon, default_model, prev_models)
        root.mainloop()
        
        if self.varDict is None:
            return None
        
        # Build config from GUI values
        selected_models = self.varDict.get("selected_models", ['GFS', 'ECMWF'])
        
        config = {
            'model_system': self.varDict.get("Forecast Data Source", "Multi-Model"),
            'lat': float(self.varDict.get("Latitude", default_lat)),
            'lon': float(self.varDict.get("Longitude", default_lon)),
            'allow_editing': self.varDict.get("Enable CSV Manual Editing", "No") == "Yes",
            'send_to_intranet': self.varDict.get("Send Products to Intranet", "Yes") == "Yes",
            'selected_models': selected_models,
        }
        
        config['point_str'] = self._format_point_string(config['lat'], config['lon'])
        return config
    
    def guiCallback(self, values):
        """Callback from GUI"""
        self.varDict = values
    
    def _validate_inputs(self, config, time_range):
        if not -90 <= config['lat'] <= 90:
            self.statusBarMsg("ERROR: Latitude must be -90 to 90", "S")
            return False
        if not -180 <= config['lon'] <= 180:
            self.statusBarMsg("ERROR: Longitude must be -180 to 180", "S")
            return False
        if time_range is None:
            self.statusBarMsg("ERROR: Select time range first", "S")
            return False
        duration = time_range.duration() / 3600.0
        if duration < 1:
            self.statusBarMsg("ERROR: Time range too short", "S")
            return False
        return True
    
    def _retrieve_forecast_data(self, config, time_range):
        try:
            if config['model_system'] == "GFE":
                # Get both GFE and ensemble data
                gfe_data = self._retrieve_gfe_data(config, time_range)
                ensemble_data = self._retrieve_multi_model_ensemble(config, time_range)
                # Merge them - use GFE for mean, ensemble for min/max and missing parameters
                merged = self._merge_gfe_ensemble(gfe_data, ensemble_data)
                # Preserve models_used from ensemble_data if it exists
                if '_models_used' in ensemble_data:
                    merged['_models_used'] = ensemble_data['_models_used']
                return merged
            else:
                return self._retrieve_multi_model_ensemble(config, time_range)
        except Exception as e:
            LogStream.logProblem(f"Data retrieval failed: {str(e)}")
            self.statusBarMsg(f"ERROR: {str(e)}", "S")
            return None
    
    def _merge_gfe_ensemble(self, gfe_data, ensemble_data):
        """Merge GFE and ensemble data - use GFE for mean line, ensemble for error bars and missing parameters"""
        merged = {}
        
        # Start with GFE data as base
        for var in gfe_data:
            merged[var] = gfe_data[var].copy()
        
        # Get the cycles
        gfe_cycle = list(gfe_data['speed'].keys())[0]
        ens_cycle = list(ensemble_data['speed'].keys())[0]
        
        # Replace min/max with ensemble values for error bars
        for var_base in ['speed', 'gust', 'htsgw']:
            if var_base + '_min' in ensemble_data and var_base + '_max' in ensemble_data:
                merged[var_base + '_min'] = ensemble_data[var_base + '_min'].copy()
                merged[var_base + '_max'] = ensemble_data[var_base + '_max'].copy()
        
        # Use ensemble for wave direction and period since GFE doesn't have these
        for var in ['dirpw', 'dirpwStr', 'perpw']:
            if var in ensemble_data:
                merged[var] = ensemble_data[var].copy()
        
        LogStream.logEvent("Merged GFE forecast with ensemble spread and wave parameters")
        return merged
    
    def _retrieve_gfe_data(self, config, time_range):
        model_data_dict = {}
        x_lat, y_lon = self.getGridCell(config['lat'], config['lon'])
        
        if None in (x_lat, y_lon):
            raise ValueError(f"Point outside GFE domain")
        
        cycle_dt = dt.datetime.fromtimestamp(time_range.startTime().unixTime())
        
        for parm_info in self.getGridInfo("Fcst", "Wind", "SFC", time_range):
            if parm_info.gridTime().startTime() >= time_range.startTime():
                valid_dt = dt.datetime.fromtimestamp(parm_info.gridTime().startTime().unixTime())
                fhr = int((valid_dt - cycle_dt).total_seconds() / 3600)
                
                wind_grid = self.getGrids("Fcst", "Wind", "SFC", parm_info.gridTime(), noDataError=0)
                speed = int(wind_grid[0][y_lon][x_lat])
                direction = int(wind_grid[1][y_lon][x_lat])
                dir_str = self.windDegToStr(direction)
                u_comp, v_comp = self.MagDirToUV(speed, direction)
                
                for var in ['speed', 'speed_min', 'speed_max', 'dir', 'dirStr', 'u', 'v', 'validdt']:
                    if var not in model_data_dict:
                        model_data_dict[var] = {cycle_dt: {}}
                    if var == 'dirStr':
                        model_data_dict[var][cycle_dt][fhr] = dir_str
                    elif var == 'dir':
                        model_data_dict[var][cycle_dt][fhr] = direction
                    elif var in ['u', 'v']:
                        model_data_dict[var][cycle_dt][fhr] = u_comp if var == 'u' else v_comp
                    elif var == 'validdt':
                        model_data_dict[var][cycle_dt][fhr] = valid_dt
                    else:
                        model_data_dict[var][cycle_dt][fhr] = speed
        
        # Try to get wind gusts if available
        try:
            for parm_info in self.getGridInfo("Fcst", "WindGust", "SFC", time_range):
                if parm_info.gridTime().startTime() >= time_range.startTime():
                    valid_dt = dt.datetime.fromtimestamp(parm_info.gridTime().startTime().unixTime())
                    fhr = int((valid_dt - cycle_dt).total_seconds() / 3600)
                    
                    gust_grid = self.getGrids("Fcst", "WindGust", "SFC", parm_info.gridTime(), noDataError=0)
                    gust = int(gust_grid[y_lon][x_lat])
                    
                    for var in ['gust', 'gust_min', 'gust_max']:
                        if var not in model_data_dict:
                            model_data_dict[var] = {cycle_dt: {}}
                        model_data_dict[var][cycle_dt][fhr] = gust
        except:
            LogStream.logEvent("WindGust not available in GFE")
        
        # Get wave height from GFE
        try:
            for parm_info in self.getGridInfo("Fcst", "WaveHeight", "SFC", time_range):
                if parm_info.gridTime().startTime() >= time_range.startTime():
                    valid_dt = dt.datetime.fromtimestamp(parm_info.gridTime().startTime().unixTime())
                    fhr = int((valid_dt - cycle_dt).total_seconds() / 3600)
                    
                    wave_grid = self.getGrids("Fcst", "WaveHeight", "SFC", parm_info.gridTime(), noDataError=0)
                    htsgw = int(wave_grid[y_lon][x_lat])
                    
                    for var in ['htsgw', 'htsgw_min', 'htsgw_max']:
                        if var not in model_data_dict:
                            model_data_dict[var] = {cycle_dt: {}}
                        model_data_dict[var][cycle_dt][fhr] = htsgw
        except:
            LogStream.logEvent("WaveHeight not available in GFE")
        
        # Wave direction and period will come from ensemble
        for var in ['dirpw', 'dirpwStr', 'perpw']:
            if var not in model_data_dict:
                model_data_dict[var] = {cycle_dt: {}}
        
        return model_data_dict
    
    def _retrieve_multi_model_ensemble(self, config, time_range):
        fcst_point = Point(config['lon'], config['lat'])
        
        # Model configuration: (name, atmo_model, wave_model, atmo_level, wave_level)
        model_configs = {
            'GFS': ('GFS', 'gfs0p25', 'gfswaveNH0p16', '10FHAG', '0.0SFC'),
            'ECMWF': ('ECMWF', 'ecmwf0p25', 'ecmwf0p25wave', '0.0SFC', '0.0MSL'),
            'CMC': ('CMC', 'Canadian-NH', 'cmc0p25wave', '10FHAG', '0.0SFC'),
        }
        
        # Log model configurations
        LogStream.logEvent("="*80)
        LogStream.logEvent("MODEL CONFIGURATION DEBUG")
        LogStream.logEvent("="*80)
        for model_name, (name, atmo, wave, atmo_lvl, wave_lvl) in model_configs.items():
            LogStream.logEvent(f"{model_name}: atmo='{atmo}', wave='{wave}', atmo_level='{atmo_lvl}', wave_level='{wave_lvl}'")
        
        # Get selected models
        selected_models = config.get('selected_models', ['GFS', 'ECMWF'])
        models = [model_configs[model] for model in selected_models if model in model_configs]
        
        ensemble_data = {}
        models_used = []  # Track which models actually provided data
        
        for model_name, atmo_model, wave_model, atmo_level, wave_level in models:
            self.statusBarMsg(f"Retrieving {model_name}...", "R")
            
            LogStream.logEvent("")
            LogStream.logEvent(f"{'='*80}")
            LogStream.logEvent(f"PROCESSING MODEL: {model_name}")
            LogStream.logEvent(f"{'='*80}")
            LogStream.logEvent(f"Atmospheric model name: '{atmo_model}'")
            LogStream.logEvent(f"Wave model name: '{wave_model}'")
            LogStream.logEvent(f"Atmospheric level: '{atmo_level}'")
            LogStream.logEvent(f"Wave level: '{wave_level}'")
            
            try:
                # All models use uW/vW components (including CMC)
                atmo_req = DataAccessLayer.newDataRequest()
                atmo_req.setDatatype("grid")
                atmo_req.setParameters("uW", "vW", "GUST")
                atmo_req.setLevels(atmo_level)
                atmo_req.setLocationNames(atmo_model)
                atmo_req.setEnvelope(fcst_point)
                
                LogStream.logEvent(f"{model_name}: Requesting atmospheric data...")
                LogStream.logEvent(f"  Parameters: {atmo_req.getParameters() if hasattr(atmo_req, 'getParameters') else 'N/A'}")
                LogStream.logEvent(f"  Levels: {atmo_level}")
                LogStream.logEvent(f"  Location: {atmo_model}")
                
                atmo_data = DataAccessLayer.getGeometryData(atmo_req, time_range)
                
                LogStream.logEvent(f"{model_name}: Atmospheric data returned: {len(atmo_data) if atmo_data else 0} grids")
                if atmo_data:
                    LogStream.logEvent(f"{model_name}: First grid sample:")
                    for i, grid in enumerate(atmo_data[:3]):  # Show first 3 grids
                        try:
                            grid_time = str(grid.getDataTime())
                            LogStream.logEvent(f"  Grid {i+1}: {grid_time}")
                            # Try to see what parameters are available
                            if hasattr(grid, 'getParameterName'):
                                param_name = grid.getParameterName()
                                LogStream.logEvent(f"    Parameter: {param_name}")
                        except Exception as e:
                            LogStream.logEvent(f"  Grid {i+1}: Error getting info - {str(e)}")
                
                wave_req = DataAccessLayer.newDataRequest()
                wave_req.setDatatype("grid")
                wave_req.setParameters("HTSGW", "DIRPW", "PERPW")
                wave_req.setLevels(wave_level)
                wave_req.setLocationNames(wave_model)
                wave_req.setEnvelope(fcst_point)
                
                LogStream.logEvent(f"{model_name}: Requesting wave data...")
                LogStream.logEvent(f"  Parameters: HTSGW, DIRPW, PERPW")
                LogStream.logEvent(f"  Levels: {wave_level}")
                LogStream.logEvent(f"  Location: {wave_model}")
                
                wave_data = DataAccessLayer.getGeometryData(wave_req, time_range)
                
                LogStream.logEvent(f"{model_name}: Wave data returned: {len(wave_data) if wave_data else 0} grids")
                
                if not atmo_data or not wave_data:
                    LogStream.logProblem(f"No {model_name} data (atmo: {atmo_model}, wave: {wave_model})")
                    LogStream.logProblem(f"  Atmo data: {len(atmo_data) if atmo_data else 0} grids")
                    LogStream.logProblem(f"  Wave data: {len(wave_data) if wave_data else 0} grids")
                    if model_name == "CMC":
                        LogStream.logProblem(f"  CMC DEBUG: Trying to find available CMC model names...")
                        # Try to list available models
                        try:
                            # Try common CMC model name variations
                            test_names = ['Canadian-NH', 'CMC', 'CMCnh', 'cmc_25km', 'CMCnh25', 'CMC-GEM']
                            for test_name in test_names:
                                test_req = DataAccessLayer.newDataRequest()
                                test_req.setDatatype("grid")
                                test_req.setParameters("uW")
                                test_req.setLevels(atmo_level)
                                test_req.setLocationNames(test_name)
                                test_req.setEnvelope(fcst_point)
                                test_data = DataAccessLayer.getGeometryData(test_req, time_range)
                                if test_data and len(test_data) > 0:
                                    LogStream.logEvent(f"  Found data with model name: '{test_name}' ({len(test_data)} grids)")
                        except Exception as e:
                            LogStream.logProblem(f"  Error testing model names: {str(e)}")
                    continue
                
                atmo_cycles = {}
                for grid in atmo_data:
                    cycle = str(grid.getDataTime())[:19]
                    atmo_cycles.setdefault(cycle, []).append(grid)
                
                LogStream.logEvent(f"{model_name}: Found {len(atmo_cycles)} atmospheric cycles: {list(atmo_cycles.keys())}")
                
                wave_cycles = {}
                for grid in wave_data:
                    cycle = str(grid.getDataTime())[:19]
                    wave_cycles.setdefault(cycle, []).append(grid)
                
                LogStream.logEvent(f"{model_name}: Found {len(wave_cycles)} wave cycles: {list(wave_cycles.keys())}")
                
                cycles = sorted(set(atmo_cycles.keys()) & set(wave_cycles.keys()), reverse=True)[:2]  # Get last 2 cycles
                
                if not cycles:
                    LogStream.logProblem(f"No matching {model_name} cycles")
                    LogStream.logProblem(f"  Atmo cycles: {list(atmo_cycles.keys())}")
                    LogStream.logProblem(f"  Wave cycles: {list(wave_cycles.keys())}")
                    continue
                
                LogStream.logEvent(f"{model_name}: Using {len(cycles)} matching cycles: {cycles}")
                models_used.append(model_name)  # Track that this model provided data
                
                for cycle_str in cycles:
                    cycle_dt = dt.datetime.strptime(cycle_str, "%Y-%m-%d %H:%M:%S")
                    
                    for grid in atmo_cycles[cycle_str]:
                        try:
                            if model_name == "CMC":
                                LogStream.logEvent(f"{model_name}: Processing grid for cycle {cycle_str}")
                                # Log what parameters are available in this grid
                                try:
                                    if hasattr(grid, 'getParameterName'):
                                        param_name = grid.getParameterName()
                                        LogStream.logEvent(f"  Grid parameter: {param_name}")
                                except:
                                    pass
                            
                            # All models use uW/vW components (including CMC)
                            u_val = grid.getNumber("uW")
                            v_val = grid.getNumber("vW")
                            
                            if model_name == "CMC":
                                LogStream.logEvent(f"  {model_name}: uW type: {type(u_val)}, value: {u_val}")
                                LogStream.logEvent(f"  {model_name}: vW type: {type(v_val)}, value: {v_val}")
                            
                            # Ensure values are not None
                            if u_val is None or v_val is None:
                                if model_name == "CMC":
                                    LogStream.logProblem(f"  {model_name}: uW or vW is None, skipping grid")
                                continue
                            
                            # CRITICAL: Convert to Python float BEFORE any operations
                            # This prevents isfinite errors with numpy scalar types
                            try:
                                # Convert u_val to Python float first
                                if hasattr(u_val, 'item'):
                                    # numpy scalar - use .item() to get Python native type
                                    u_python = float(u_val.item())
                                elif isinstance(u_val, (np.integer, np.floating)):
                                    # numpy type - convert via item() if available, else direct float
                                    u_python = float(u_val.item()) if hasattr(u_val, 'item') else float(u_val)
                                else:
                                    # Regular Python type or string
                                    u_python = float(u_val)
                                
                                # Convert v_val to Python float
                                if hasattr(v_val, 'item'):
                                    v_python = float(v_val.item())
                                elif isinstance(v_val, (np.integer, np.floating)):
                                    v_python = float(v_val.item()) if hasattr(v_val, 'item') else float(v_val)
                                else:
                                    v_python = float(v_val)
                                
                                # Now convert to knots (m/s to kt)
                                u = u_python * 1.94384
                                v = v_python * 1.94384
                                
                                if model_name == "CMC":
                                    LogStream.logEvent(f"  {model_name}: Converted u={u:.2f} kt, v={v:.2f} kt")
                                
                                # Calculate speed and direction
                                speed, direction = self.UVToMagDir(u, v)
                                
                                if model_name == "CMC":
                                    LogStream.logEvent(f"  {model_name}: Calculated speed={speed:.2f} kt, dir={direction:.1f} deg")
                                
                            except (ValueError, TypeError, AttributeError, OverflowError) as e:
                                LogStream.logProblem(f"  {model_name}: uW/vW conversion error: {str(e)}")
                                LogStream.logProblem(f"    u_val type: {type(u_val)}, v_val type: {type(v_val)}")
                                continue
                        except (ValueError, TypeError, AttributeError) as e:
                            LogStream.logProblem(f"{model_name} atmo grid error: {str(e)}")
                            continue
                        
                        # Get gust if available
                        try:
                            gust_val = grid.getNumber("GUST")
                            if gust_val is not None:
                                # Convert to Python float first (handle numpy types)
                                if hasattr(gust_val, 'item'):
                                    gust = float(gust_val.item()) * 1.94384
                                elif isinstance(gust_val, (np.integer, np.floating)):
                                    gust = float(gust_val.item()) if hasattr(gust_val, 'item') else float(gust_val) * 1.94384
                                else:
                                    gust = float(gust_val) * 1.94384
                            else:
                                gust = speed * 1.3  # Estimate gust as 30% higher if not available
                        except (ValueError, TypeError, AttributeError):
                            gust = speed * 1.3  # Estimate gust as 30% higher if not available
                        
                        grid_time = str(grid.getDataTime())
                        fhr = int(grid_time[grid_time.index("(")+1:grid_time.index(")")])
                        valid_dt = cycle_dt + dt.timedelta(hours=fhr)
                        
                        # Round to nearest 3-hour interval
                        valid_dt_rounded = self._round_to_3hourly(valid_dt)
                        
                        if 0 <= speed <= 150:
                            if valid_dt_rounded not in ensemble_data:
                                ensemble_data[valid_dt_rounded] = {
                                    'wind_speeds': [], 'wind_dirs': [], 'wind_gusts': [],
                                    'wave_heights': [], 'wave_dirs': [], 'wave_periods': []
                                }
                            # Ensure all values are finite floats
                            # CRITICAL: speed, direction, and gust should already be Python floats
                            # But ensure they are before calling np.isfinite()
                            try:
                                # Ensure these are Python native floats (not numpy types)
                                if isinstance(speed, (np.integer, np.floating)):
                                    speed_f = float(speed.item()) if hasattr(speed, 'item') else float(speed)
                                else:
                                    speed_f = float(speed)
                                
                                if isinstance(direction, (np.integer, np.floating)):
                                    dir_f = float(direction.item()) if hasattr(direction, 'item') else float(direction)
                                else:
                                    dir_f = float(direction)
                                
                                if isinstance(gust, (np.integer, np.floating)):
                                    gust_f = float(gust.item()) if hasattr(gust, 'item') else float(gust)
                                else:
                                    gust_f = float(gust)
                                
                                # Now safe to check isfinite on Python floats
                                if not np.isfinite(speed_f):
                                    speed_f = np.nan
                                if not np.isfinite(dir_f):
                                    dir_f = np.nan
                                if not np.isfinite(gust_f):
                                    gust_f = np.nan
                            except (ValueError, TypeError, OverflowError) as e:
                                if model_name == "CMC":
                                    LogStream.logProblem(f"  {model_name}: Error checking finiteness: {str(e)}")
                                    LogStream.logProblem(f"    speed type: {type(speed)}, dir type: {type(direction)}, gust type: {type(gust)}")
                                speed_f = np.nan
                                dir_f = np.nan
                                gust_f = np.nan
                            ensemble_data[valid_dt_rounded]['wind_speeds'].append(speed_f)
                            ensemble_data[valid_dt_rounded]['wind_dirs'].append(dir_f)
                            ensemble_data[valid_dt_rounded]['wind_gusts'].append(gust_f)
                    
                    for grid in wave_cycles[cycle_str]:
                        try:
                            htsgw_val = grid.getNumber("HTSGW")
                            perpw_val = None
                            dirpw_val = None
                            
                            if htsgw_val is None:
                                # Skip if no wave height at all
                                if model_name == "CMC":
                                    LogStream.logProblem(f"{model_name} wave grid missing HTSGW, skipping grid")
                                continue
                            
                            # Convert HTSGW to feet (m -> ft)
                            if hasattr(htsgw_val, 'item'):
                                htsgw = float(htsgw_val.item()) * 3.28084
                            elif isinstance(htsgw_val, (np.integer, np.floating)):
                                htsgw = (float(htsgw_val.item()) if hasattr(htsgw_val, 'item') else float(htsgw_val)) * 3.28084
                            else:
                                htsgw = float(htsgw_val) * 3.28084
                            
                            # Period is optional
                            try:
                                perpw_val = grid.getNumber("PERPW")
                                if perpw_val is not None:
                                    if hasattr(perpw_val, 'item'):
                                        perpw = float(perpw_val.item())
                                    elif isinstance(perpw_val, (np.integer, np.floating)):
                                        perpw = float(perpw_val.item()) if hasattr(perpw_val, 'item') else float(perpw_val)
                                    else:
                                        perpw = float(perpw_val)
                                else:
                                    perpw = np.nan
                            except (ValueError, TypeError, AttributeError):
                                perpw = np.nan
                            
                            # Direction is optional
                            try:
                                dirpw_val = grid.getNumber("DIRPW")
                                if dirpw_val is not None:
                                    if hasattr(dirpw_val, 'item'):
                                        dirpw = float(dirpw_val.item())
                                    elif isinstance(dirpw_val, (np.integer, np.floating)):
                                        dirpw = float(dirpw_val.item()) if hasattr(dirpw_val, 'item') else float(dirpw_val)
                                    else:
                                        dirpw = float(dirpw_val)
                                else:
                                    dirpw = np.nan
                            except (ValueError, TypeError, AttributeError):
                                dirpw = np.nan
                        except (ValueError, TypeError, AttributeError) as e:
                            LogStream.logProblem(f"{model_name} wave grid error: {str(e)}")
                            continue
                        
                        grid_time = str(grid.getDataTime())
                        fhr = int(grid_time[grid_time.index("(")+1:grid_time.index(")")])
                        valid_dt = cycle_dt + dt.timedelta(hours=fhr)
                        
                        # Round to nearest 3-hour interval
                        valid_dt_rounded = self._round_to_3hourly(valid_dt)
                        
                        # Basic QC on wave height (allow up to 100 ft)
                        if not (0 <= htsgw <= 100):
                            continue
                        
                        # QC on period/direction if available
                        if perpw is not None and not np.isnan(perpw):
                            if not (0 <= perpw <= 30):
                                perpw = np.nan
                        else:
                            perpw = np.nan
                        
                        if dirpw is not None and not np.isnan(dirpw):
                            dirpw = dirpw % 360
                        else:
                            dirpw = np.nan
                        
                        if valid_dt_rounded not in ensemble_data:
                            ensemble_data[valid_dt_rounded] = {
                                'wind_speeds': [], 'wind_dirs': [], 'wind_gusts': [],
                                'wave_heights': [], 'wave_dirs': [], 'wave_periods': []
                            }
                        # Ensure all values are finite floats
                        try:
                            if isinstance(htsgw, (np.integer, np.floating)):
                                htsgw_f = float(htsgw.item()) if hasattr(htsgw, 'item') else float(htsgw)
                            else:
                                htsgw_f = float(htsgw)
                            if not np.isfinite(htsgw_f):
                                htsgw_f = np.nan
                        except (ValueError, TypeError, OverflowError):
                            htsgw_f = np.nan
                        
                        try:
                            if isinstance(dirpw, (np.integer, np.floating)):
                                dirpw_f = float(dirpw.item()) if hasattr(dirpw, 'item') else float(dirpw)
                            else:
                                dirpw_f = float(dirpw)
                            if not np.isfinite(dirpw_f):
                                dirpw_f = np.nan
                        except (ValueError, TypeError, OverflowError):
                            dirpw_f = np.nan
                        
                        try:
                            if isinstance(perpw, (np.integer, np.floating)):
                                perpw_f = float(perpw.item()) if hasattr(perpw, 'item') else float(perpw)
                            else:
                                perpw_f = float(perpw)
                            if not np.isfinite(perpw_f):
                                perpw_f = np.nan
                        except (ValueError, TypeError, OverflowError):
                            perpw_f = np.nan
                        
                        ensemble_data[valid_dt_rounded]['wave_heights'].append(htsgw_f)
                        ensemble_data[valid_dt_rounded]['wave_dirs'].append(dirpw_f)
                        ensemble_data[valid_dt_rounded]['wave_periods'].append(perpw_f)
                
            except Exception as e:
                LogStream.logProblem(f"{model_name} error: {str(e)}")
        
        if not ensemble_data:
            raise ValueError("No model data retrieved")
        
        # Log the number of ensemble members per time
        sample_times = sorted(list(ensemble_data.keys()))[:5]
        for t in sample_times:
            LogStream.logEvent(f"Time {t}: {len(ensemble_data[t]['wind_speeds'])} wind members, "
                             f"{len(ensemble_data[t]['wave_heights'])} wave members")
        
        stats = self._calculate_ensemble_stats(ensemble_data)
        # Store models_used in the stats dict so it can be passed through
        stats['_models_used'] = models_used if models_used else config.get('selected_models', ['GFS', 'ECMWF'])
        return stats
    
    def _calculate_ensemble_stats(self, ensemble_data):
        def _to_python_float(value, context=None):
            """Convert AWIPS/NumPy values to native Python float and handle errors."""
            if value is None:
                return np.nan
            try:
                if hasattr(value, 'item'):
                    value = value.item()
                if isinstance(value, (np.ndarray, list, tuple)):
                    value_array = np.atleast_1d(value)
                    if value_array.size == 0:
                        return np.nan
                    value = value_array.flat[0]
                return float(value)
            except (ValueError, TypeError, AttributeError, OverflowError) as err:
                if context:
                    LogStream.logProblem(f"Value conversion error ({context}): {err} -- type={type(value)}, value={value}")
                return np.nan

        model_data_dict = {}
        sorted_times = sorted(ensemble_data.keys())
        fake_cycle = sorted_times[0].replace(hour=0, minute=0, second=0)
        
        for var in ['speed', 'speed_min', 'speed_max', 'dir', 'dirStr', 'u', 'v',
                   'gust', 'gust_min', 'gust_max',
                   'htsgw', 'htsgw_min', 'htsgw_max', 'dirpw', 'dirpwStr', 'perpw', 'validdt']:
            model_data_dict[var] = {fake_cycle: {}}
        
        # Store ensemble member count for first time
        first_time_count = 0
        
        for idx, valid_dt in enumerate(sorted_times):
            data = ensemble_data[valid_dt]
            
            if data['wind_speeds']:
                # Convert to numpy arrays and filter out non-finite values
                speeds_list = []
                for x in data['wind_speeds']:
                    val = _to_python_float(x)
                    if np.isfinite(val):
                        speeds_list.append(val)
                
                dirs_list = []
                for x in data['wind_dirs']:
                    val = _to_python_float(x)
                    if np.isfinite(val):
                        dirs_list.append(val)
                
                gusts_list = []
                for x in data['wind_gusts']:
                    val = _to_python_float(x)
                    if np.isfinite(val):
                        gusts_list.append(val)
                
                speeds = np.array(speeds_list, dtype=np.float64)
                dirs = np.array(dirs_list, dtype=np.float64)
                gusts = np.array(gusts_list, dtype=np.float64)
                
                if len(speeds) == 0 or len(dirs) == 0:
                    # Skip if no valid data
                    for var in ['speed', 'speed_min', 'speed_max', 'gust', 'gust_min', 'gust_max', 'dir', 'u', 'v']:
                        model_data_dict[var][fake_cycle][idx] = np.nan
                    model_data_dict['dirStr'][fake_cycle][idx] = ""
                    continue
                
                if idx == 0:
                    first_time_count = len(speeds)
                
                # Calculate means - ensure Python floats
                speed_mean = _to_python_float(np.nanmean(speeds) if len(speeds) > 0 else np.nan)
                dir_mean = _to_python_float(np.nanmean(dirs) if len(dirs) > 0 else np.nan)
                gust_mean = _to_python_float(np.nanmean(gusts) if len(gusts) > 0 else np.nan)
                
                # Check finiteness on Python floats
                if np.isfinite(speed_mean) and np.isfinite(dir_mean):
                    raw_u, raw_v = self.MagDirToUV(speed_mean, dir_mean)
                    u = _to_python_float(raw_u)
                    v = _to_python_float(raw_v)
                    if not np.isfinite(u):
                        u = np.nan
                    if not np.isfinite(v):
                        v = np.nan
                else:
                    u, v = np.nan, np.nan
                
                model_data_dict['speed'][fake_cycle][idx] = speed_mean
                speed_min_raw = np.nanmin(speeds) if len(speeds) > 0 else np.nan
                speed_max_raw = np.nanmax(speeds) if len(speeds) > 0 else np.nan
                model_data_dict['speed_min'][fake_cycle][idx] = _to_python_float(speed_min_raw)
                model_data_dict['speed_max'][fake_cycle][idx] = _to_python_float(speed_max_raw)
                
                model_data_dict['gust'][fake_cycle][idx] = gust_mean
                gust_min_raw = np.nanmin(gusts) if len(gusts) > 0 else np.nan
                gust_max_raw = np.nanmax(gusts) if len(gusts) > 0 else np.nan
                model_data_dict['gust_min'][fake_cycle][idx] = _to_python_float(gust_min_raw)
                model_data_dict['gust_max'][fake_cycle][idx] = _to_python_float(gust_max_raw)
                
                model_data_dict['dir'][fake_cycle][idx] = dir_mean
                model_data_dict['dirStr'][fake_cycle][idx] = self.windDegToStr(dir_mean) if np.isfinite(dir_mean) else ""
                model_data_dict['u'][fake_cycle][idx] = u if np.isfinite(u) else np.nan
                model_data_dict['v'][fake_cycle][idx] = v if np.isfinite(v) else np.nan
            else:
                for var in ['speed', 'speed_min', 'speed_max', 'gust', 'gust_min', 'gust_max', 'dir', 'u', 'v']:
                    model_data_dict[var][fake_cycle][idx] = np.nan
                model_data_dict['dirStr'][fake_cycle][idx] = ""
            
            if data['wave_heights']:
                # Convert to numpy arrays and filter out non-finite values
                waves_list = []
                for x in data['wave_heights']:
                    if x is not None:
                        try:
                            # Convert to Python float first (handle numpy types)
                            if hasattr(x, 'item'):
                                val = float(x.item())
                            elif isinstance(x, (np.integer, np.floating)):
                                val = float(x.item()) if hasattr(x, 'item') else float(x)
                            else:
                                val = float(x)
                            # Now safe to check isfinite on Python float
                            if np.isfinite(val):
                                waves_list.append(val)
                        except (ValueError, TypeError, OverflowError):
                            pass
                
                dirs_list = []
                for x in data['wave_dirs']:
                    if x is not None:
                        try:
                            # Convert to Python float first (handle numpy types)
                            if hasattr(x, 'item'):
                                val = float(x.item())
                            elif isinstance(x, (np.integer, np.floating)):
                                val = float(x.item()) if hasattr(x, 'item') else float(x)
                            else:
                                val = float(x)
                            # Now safe to check isfinite on Python float
                            if np.isfinite(val):
                                dirs_list.append(val)
                        except (ValueError, TypeError, OverflowError):
                            pass
                
                periods_list = []
                for x in data['wave_periods']:
                    if x is not None:
                        try:
                            # Convert to Python float first (handle numpy types)
                            if hasattr(x, 'item'):
                                val = float(x.item())
                            elif isinstance(x, (np.integer, np.floating)):
                                val = float(x.item()) if hasattr(x, 'item') else float(x)
                            else:
                                val = float(x)
                            # Now safe to check isfinite on Python float
                            if np.isfinite(val):
                                periods_list.append(val)
                        except (ValueError, TypeError, OverflowError):
                            pass
                
                waves = np.array(waves_list, dtype=np.float64)
                dirs = np.array(dirs_list, dtype=np.float64)
                periods = np.array(periods_list, dtype=np.float64)
                
                if len(waves) > 0:
                    htsgw_mean_raw = np.nanmean(waves)
                    htsgw_min_raw = np.nanmin(waves)
                    htsgw_max_raw = np.nanmax(waves)
                    # Convert to Python floats
                    model_data_dict['htsgw'][fake_cycle][idx] = _to_python_float(htsgw_mean_raw)
                    model_data_dict['htsgw_min'][fake_cycle][idx] = _to_python_float(htsgw_min_raw)
                    model_data_dict['htsgw_max'][fake_cycle][idx] = _to_python_float(htsgw_max_raw)
                else:
                    model_data_dict['htsgw'][fake_cycle][idx] = np.nan
                    model_data_dict['htsgw_min'][fake_cycle][idx] = np.nan
                    model_data_dict['htsgw_max'][fake_cycle][idx] = np.nan
                
                if len(dirs) > 0:
                    dirpw_mean_raw = np.nanmean(dirs)
                    # Convert to Python float
                    dirpw_mean = _to_python_float(dirpw_mean_raw)
                    model_data_dict['dirpw'][fake_cycle][idx] = dirpw_mean
                    model_data_dict['dirpwStr'][fake_cycle][idx] = self.windDegToStr(dirpw_mean) if np.isfinite(dirpw_mean) else ""
                else:
                    model_data_dict['dirpw'][fake_cycle][idx] = np.nan
                    model_data_dict['dirpwStr'][fake_cycle][idx] = ""
                
                if len(periods) > 0:
                    perpw_mean_raw = np.nanmean(periods)
                    # Convert to Python float
                    model_data_dict['perpw'][fake_cycle][idx] = _to_python_float(perpw_mean_raw)
                else:
                    model_data_dict['perpw'][fake_cycle][idx] = np.nan
            else:
                for var in ['htsgw', 'htsgw_min', 'htsgw_max', 'dirpw', 'perpw']:
                    model_data_dict[var][fake_cycle][idx] = np.nan
                model_data_dict['dirpwStr'][fake_cycle][idx] = ""
            
            model_data_dict['validdt'][fake_cycle][idx] = valid_dt
        
        # Store ensemble count in a special key
        model_data_dict['_ensemble_count'] = first_time_count
        
        return model_data_dict
    
    def _prepare_csv_data(self, model_data_dict):
        cycles = []
        for parm in model_data_dict:
            if parm != '_ensemble_count':  # Skip special keys
                # Fix: Check if value is a dict before iterating
                if isinstance(model_data_dict[parm], dict):
                    for cyc in model_data_dict[parm]:
                        if cyc not in cycles:
                            cycles.append(cyc)
        last_cycle = sorted(cycles)[-1] if cycles else None
        
        if last_cycle is None:
            raise ValueError("No cycles found in model data")
        
        fhrs = []
        for parm in model_data_dict:
            # Skip special keys and ensure parm is a dict before checking for last_cycle
            if parm == '_ensemble_count' or not isinstance(model_data_dict[parm], dict):
                continue
            if last_cycle in model_data_dict[parm]:
                # Fix: Check if value is a dict before iterating
                parm_cycle_data = model_data_dict[parm][last_cycle]
                if isinstance(parm_cycle_data, dict):
                    for fhr in parm_cycle_data:
                        if fhr not in fhrs:
                            fhrs.append(fhr)
        fhrs = sorted(fhrs)
        
        if not fhrs:
            raise ValueError("No forecast hours found in model data")
        
        metadata = {
            'validdt': "Valid Time",
            'dir': "Wind Dir (deg)",
            'dirStr': "Wind Dir",
            'speed': "Wind Speed Mean (kt)",
            'speed_min': "Wind Speed Min (kt)",
            'speed_max': "Wind Speed Max (kt)",
            'gust': "Wind Gust Mean (kt)",
            'gust_min': "Wind Gust Min (kt)",
            'gust_max': "Wind Gust Max (kt)",
            'u': "u Wind",
            'v': "v Wind",
            'htsgw': "Wave Height Mean (ft)",
            'htsgw_min': "Wave Height Min (ft)",
            'htsgw_max': "Wave Height Max (ft)",
            'dirpw': "Wave Dir (deg)",
            'dirpwStr': "Wave Dir",
            'perpw': "Wave Period (s)",
        }
        
        for parm, header in metadata.items():
            if parm not in model_data_dict:
                model_data_dict[parm] = {}
            if not isinstance(model_data_dict[parm], dict):
                model_data_dict[parm] = {}
            model_data_dict[parm]['csv'] = {'rowheader': header, 'data': []}
        
        for fhr in fhrs:
            for parm in model_data_dict:
                # Skip special keys and ensure parm is a dict before checking for 'csv'
                if parm == '_ensemble_count' or not isinstance(model_data_dict[parm], dict):
                    continue
                if 'csv' in model_data_dict[parm]:
                    if last_cycle in model_data_dict[parm] and isinstance(model_data_dict[parm][last_cycle], dict):
                        if fhr in model_data_dict[parm][last_cycle]:
                            model_data_dict[parm]['csv']['data'].append(model_data_dict[parm][last_cycle][fhr])
                        else:
                            model_data_dict[parm]['csv']['data'].append("")
                    else:
                        model_data_dict[parm]['csv']['data'].append("")
        
        return last_cycle, fhrs, model_data_dict
    
    def _save_to_csv(self, model_data_dict, config):
        os.makedirs(self._spot_dir, mode=0o775, exist_ok=True)
        last_cycle, fhrs, model_data_dict = self._prepare_csv_data(model_data_dict)
        
        now = dt.datetime.now()
        # Simple filename using the pre-formatted point string
        filename = f"spot_{config['point_str'].replace(' ', '_')}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        csv_file = os.path.join(self._spot_dir, filename)
        
        if config['model_system'] == 'Multi-Model':
            model_list = '+'.join(config.get('selected_models', ['GFS', 'ECMWF']))
            title = f"Multi-Model Ensemble for {config['point_str']} ({model_list}, last 2 cycles each) {now.strftime('%Y-%m-%d %H UTC')}"
        else:
            title = f"GFE with Ensemble Spread for {config['point_str']} {now.strftime('%Y-%m-%d %H UTC')}"
        
        parm_order = ['dirStr', 'dir', 'speed', 'speed_min', 'speed_max', 
                     'gust', 'gust_min', 'gust_max',
                     'dirpwStr', 'dirpw', 'htsgw', 'htsgw_min', 'htsgw_max', 'perpw']
        
        with open(csv_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow([title])
            
            vt_row = [x.strftime('%m/%d %HZ') if isinstance(x, dt.datetime) else str(x) for x in model_data_dict['validdt']['csv']['data']]
            writer.writerow([model_data_dict['validdt']['csv']['rowheader']] + vt_row)
            
            for parm in parm_order:
                if parm in model_data_dict and 'csv' in model_data_dict[parm]:
                    writer.writerow([model_data_dict[parm]['csv']['rowheader']] + 
                                  model_data_dict[parm]['csv']['data'])
        
        return csv_file
    
    def _handle_csv_editing(self, csv_file, model_data_dict):
        self.statusBarMsg("Opening LibreOffice - close when done", "R")
        os.system(f"/usr/bin/libreoffice --calc {csv_file}")
        
        try:
            with open(csv_file, 'r') as f:
                reader = csv.reader(f)
                next(reader)
                next(reader)
                
                for row in reader:
                    row = [float(x) if (x and x.replace('.', '', 1).replace('-', '', 1).isdigit()) else x for x in row]
                    
                    for parm in ['dirStr', 'dir', 'speed', 'speed_min', 'speed_max',
                               'gust', 'gust_min', 'gust_max',
                               'dirpwStr', 'dirpw', 'htsgw', 'htsgw_min', 'htsgw_max', 'perpw']:
                        if parm in model_data_dict and 'csv' in model_data_dict[parm]:
                            orig = [model_data_dict[parm]['csv']['rowheader']] + model_data_dict[parm]['csv']['data']
                            if str(row[0]) == str(orig[0]) and row != orig:
                                model_data_dict[parm]['csv']['data'] = row[1:]
        except Exception as e:
            LogStream.logProblem(f"CSV edit error: {str(e)}")
        
        return model_data_dict
    
    def _generate_outputs(self, model_data_dict, config, csv_file):
        # Helper function to safely get data and convert to float array
        def safe_get_data(data_dict, key, default_key):
            try:
                data = data_dict.get(key, {}).get('csv', {}).get('data',
                                    data_dict.get(default_key, {}).get('csv', {}).get('data', []))
                # Convert to float array, replacing empty strings with nan
                result = []
                for x in data:
                    if x == "" or x is None:
                        result.append(np.nan)
                    else:
                        try:
                            # Handle numpy types explicitly
                            if isinstance(x, (np.integer, np.floating)):
                                val = float(x.item())  # Convert numpy scalar to Python float
                            elif isinstance(x, np.ndarray):
                                # If it's an array, take first element or use nan
                                val = float(x.flat[0]) if x.size > 0 else np.nan
                            else:
                                val = float(x)
                            # Ensure it's a Python float, not numpy float
                            result.append(float(val))
                        except (ValueError, TypeError, OverflowError, AttributeError):
                            result.append(np.nan)
                return result
            except:
                return [np.nan] * len(data_dict.get(default_key, {}).get('csv', {}).get('data', [np.nan]))
        
        # Get base data
        speeds = safe_get_data(model_data_dict, 'speed', 'speed')
        speed_min = safe_get_data(model_data_dict, 'speed_min', 'speed')
        speed_max = safe_get_data(model_data_dict, 'speed_max', 'speed')
        
        gusts = safe_get_data(model_data_dict, 'gust', 'gust')
        gust_min = safe_get_data(model_data_dict, 'gust_min', 'gust')
        gust_max = safe_get_data(model_data_dict, 'gust_max', 'gust')
        
        waves = safe_get_data(model_data_dict, 'htsgw', 'htsgw')
        htsgw_min = safe_get_data(model_data_dict, 'htsgw_min', 'htsgw')
        htsgw_max = safe_get_data(model_data_dict, 'htsgw_max', 'htsgw')
        
        # Get wave period and direction data
        perpw = safe_get_data(model_data_dict, 'perpw', 'perpw')
        dirpw = safe_get_data(model_data_dict, 'dirpw', 'dirpw')
        
        # Get string data (dirStr, dirpwStr)
        dirStr = model_data_dict.get('dirStr', {}).get('csv', {}).get('data', [])
        dirpwStr = model_data_dict.get('dirpwStr', {}).get('csv', {}).get('data', [])
        
        # Get u/v components
        us = safe_get_data(model_data_dict, 'u', 'u')
        vs = safe_get_data(model_data_dict, 'v', 'v')
        
        # Get valid times
        times = model_data_dict.get('validdt', {}).get('csv', {}).get('data', [])
        
        # Get ensemble count
        ensemble_count = model_data_dict.get('_ensemble_count', 0)
        
        # Build model list string for display - use actual models that provided data
        models_used = model_data_dict.get('_models_used', config.get('selected_models', ['GFS', 'ECMWF']))
        model_list_str = ' + '.join(models_used)
        
        image = self.drawMeteogram(
            times,
            speeds, speed_min, speed_max,
            gusts, gust_min, gust_max,
            dirStr,
            us,
            vs,
            waves, htsgw_min, htsgw_max,
            perpw, dirpw, dirpwStr,
            config['point_str'], self._spot_dir, config['model_system'],
            ensemble_count, model_list_str
        )
        
        text = self.makeTextTable(csv_file)
        return image, text
    
    def makeTextTable(self, csv_file):
        with open(csv_file, 'r') as f:
            lines = f.readlines()
        
        title = lines[0]
        data = np.array([x.replace('\n', '').split(',') for x in lines[1:]]).T
        small = np.delete(data, [2, 5], 1)
        
        out = title + '\nDate Time       Winds         Waves\n'
        out += '\n'.join([f"{x[0]:5s} {x[1]:>7} {x[2]:>3s}kt {x[3]:>7s} {x[4]:>2s}ft at {x[5]:.2s}s"
                         for x in small[1:, :]])
        
        txt_file = csv_file.replace('.csv', '.txt')
        with open(txt_file, 'w') as f:
            f.write(out)
        return txt_file
    
    def drawMeteogram(self, times, speeds, speeds_min, speeds_max, gusts, gusts_min, gusts_max,
                     dirs, us, vs, waves, waves_min, waves_max, periods, wave_dirs, wave_dir_strs,
                     point, spot_dir, model_sys, ensemble_count=0, model_list='GFS + ECMWF'):
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.ticker import MultipleLocator, AutoMinorLocator
        from matplotlib.patches import FancyArrowPatch
        
        LogStream.logEvent("="*80)
        LogStream.logEvent("DRAWING METEOGRAM")
        LogStream.logEvent("="*80)
        LogStream.logEvent(f"Times: {len(times) if times else 0} values")
        LogStream.logEvent(f"Speeds: {len(speeds) if speeds else 0} values")
        LogStream.logEvent(f"Waves: {len(waves) if waves else 0} values")
        LogStream.logEvent(f"Point: {point}, Spot dir: {spot_dir}")
        LogStream.logEvent(f"Model system: {model_sys}, Models: {model_list}")
        
        if not times or len(times) == 0:
            LogStream.logProblem("ERROR: No times data provided to drawMeteogram")
            return None
        
        if not speeds or len(speeds) == 0:
            LogStream.logProblem("ERROR: No speeds data provided to drawMeteogram")
            return None
        
        # Create figure with adjusted height ratios
        try:
            fig = plt.figure(figsize=(14, 18))
            LogStream.logEvent("Figure created successfully")
        except Exception as e:
            LogStream.logProblem(f"ERROR creating figure: {str(e)}")
            import traceback
            LogStream.logProblem(f"Traceback: {traceback.format_exc()}")
            return None
        gs = fig.add_gridspec(6, 1, height_ratios=[3.0, 1.5, 3.0, 1.0, 1.8, 0.6], 
                              hspace=0.75, top=0.92, bottom=0.05, right=0.95)
        
        # Define professional color scheme
        colors = {
            'wind_line': '#d62728',
            'wind_fill': '#ff9999',
            'gust_line': '#8B008B',
            'gust_fill': '#DDA0DD',
            'wave_line': '#1f77b4',
            'wave_fill': '#aec7e8',
            'period_line': '#2ca02c',
            'grid': '#d0d0d0',
            'grid_minor': '#e8e8e8',
            'background': '#fafafa'
        }
        
        # Helper function to safely convert to float array
        def safe_float_array(data):
            """Safely convert data to float array with robust type checking"""
            result = []
            for x in data:
                try:
                    if x is None:
                        result.append(np.nan)
                    elif isinstance(x, str):
                        if x.strip() == "":
                            result.append(np.nan)
                        else:
                            val = float(x)
                            # Convert to Python float to ensure np.isfinite works
                            val = float(val)
                            if np.isfinite(val):
                                result.append(val)
                            else:
                                result.append(np.nan)
                    elif isinstance(x, (np.integer, np.floating)):
                        # Convert numpy scalar to Python float first
                        try:
                            val = float(x.item()) if hasattr(x, 'item') else float(x)
                            # Ensure it's a Python native float before checking isfinite
                            val = float(val)  # Double conversion to ensure Python float
                            if np.isfinite(val):
                                result.append(val)
                            else:
                                result.append(np.nan)
                        except (ValueError, TypeError, AttributeError, OverflowError):
                            result.append(np.nan)
                    elif isinstance(x, np.ndarray):
                        # If it's an array, take first element
                        if x.size > 0:
                            val = float(x.flat[0])
                            if np.isfinite(val):
                                result.append(val)
                            else:
                                result.append(np.nan)
                        else:
                            result.append(np.nan)
                    elif isinstance(x, (int, float)):
                        # Regular Python numeric types
                        val = float(x)
                        # Ensure it's a Python native float (not numpy)
                        val = float(val)
                        if np.isfinite(val):
                            result.append(val)
                        else:
                            result.append(np.nan)
                    else:
                        # Try to convert unknown types
                        # First try to get a scalar value if it's a numpy type
                        try:
                            if hasattr(x, 'item'):
                                val = float(x.item())
                            elif isinstance(x, (np.integer, np.floating)):
                                val = float(x.item()) if hasattr(x, 'item') else float(x)
                            else:
                                val = float(x)
                            # Ensure it's a Python float (double conversion)
                            val = float(val)
                            if np.isfinite(val):
                                result.append(val)
                            else:
                                result.append(np.nan)
                        except (ValueError, TypeError, AttributeError, OverflowError):
                            result.append(np.nan)
                except (ValueError, TypeError, OverflowError, AttributeError):
                    result.append(np.nan)
            return np.array(result, dtype=np.float64)
        
        # Helper function to find best legend position based on data density
        def find_best_legend_position(times_data, y_data, y_min_data=None, y_max_data=None):
            """Find the best position for legend by checking data density in corners"""
            if len(y_data) == 0 or len(times_data) == 0:
                return 'upper right'
            
            # Convert times to numeric
            times_num = mdates.date2num(times_data)
            
            # Get data ranges
            x_min, x_max = times_num.min(), times_num.max()
            y_min, y_max = np.nanmin(y_data), np.nanmax(y_data)
            
            # Include min/max data in range if provided
            if y_min_data is not None:
                y_min = min(y_min, np.nanmin(y_min_data))
            if y_max_data is not None:
                y_max = max(y_max, np.nanmax(y_max_data))
            
            x_range = x_max - x_min
            y_range = y_max - y_min if y_max > y_min else 1.0
            
            # Define corner regions (20% of axis in each corner)
            corner_size = 0.2
            corners = {
                'upper right': (x_max - x_range * corner_size, y_max - y_range * corner_size, x_max, y_max),
                'upper left': (x_min, y_max - y_range * corner_size, x_min + x_range * corner_size, y_max),
                'lower right': (x_max - x_range * corner_size, y_min, x_max, y_min + y_range * corner_size),
                'lower left': (x_min, y_min, x_min + x_range * corner_size, y_min + y_range * corner_size),
            }
            
            # Check data density in each corner
            corner_density = {}
            for corner_name, (x1, y1, x2, y2) in corners.items():
                count = 0
                for i, y_val in enumerate(y_data):
                    if not np.isnan(y_val) and i < len(times_num):
                        x_val = times_num[i]
                        if x1 <= x_val <= x2 and y1 <= y_val <= y2:
                            count += 1
                    # Also check min/max if provided
                    if y_min_data is not None and i < len(y_min_data):
                        y_min_val = y_min_data[i]
                        if not np.isnan(y_min_val) and i < len(times_num):
                            x_val = times_num[i]
                            if x1 <= x_val <= x2 and y1 <= y_min_val <= y2:
                                count += 0.5
                    if y_max_data is not None and i < len(y_max_data):
                        y_max_val = y_max_data[i]
                        if not np.isnan(y_max_val) and i < len(times_num):
                            x_val = times_num[i]
                            if x1 <= x_val <= x2 and y1 <= y_max_val <= y2:
                                count += 0.5
                corner_density[corner_name] = count
            
            # Find corner with least data
            best_corner = min(corner_density, key=corner_density.get)
            
            # Map to matplotlib legend locations
            loc_map = {
                'upper right': 'upper right',
                'upper left': 'upper left',
                'lower right': 'lower right',
                'lower left': 'lower left',
            }
            
            return loc_map.get(best_corner, 'upper right')
        
        # Convert all numeric data to numpy arrays and handle NaNs
        speeds = safe_float_array(speeds)
        speeds_min = safe_float_array(speeds_min)
        speeds_max = safe_float_array(speeds_max)
        us = safe_float_array(us)
        vs = safe_float_array(vs)
        
        LogStream.logEvent(f"After safe_float_array - speeds: {len(speeds)} values")
        if len(speeds) == 0:
            LogStream.logProblem("ERROR: No valid speed data after conversion")
            plt.close()
            return None
        
        # Process wind data
        mask = ~np.isnan(speeds)
        times_w_dt = np.array(times)[mask]
        
        LogStream.logEvent(f"Valid wind data points: {np.sum(mask)} out of {len(speeds)}")
        
        if len(times_w_dt) == 0:
            LogStream.logProblem("ERROR: No valid times for wind data")
            plt.close()
            return None
        times_w = mdates.date2num(times_w_dt)
        speeds = speeds[mask]
        speeds_min = speeds_min[mask]
        speeds_max = speeds_max[mask]
        dirs = np.array(dirs)[mask]
        us = us[mask]
        vs = vs[mask]
        
        # Process gust data
        gusts_arr = safe_float_array(gusts)
        has_gusts = len(gusts_arr) > 0 and np.any(~np.isnan(gusts_arr))
        
        if has_gusts:
            gusts_min_arr = safe_float_array(gusts_min)
            gusts_max_arr = safe_float_array(gusts_max)
            gusts = gusts_arr[mask]
            gusts_min = gusts_min_arr[mask]
            gusts_max = gusts_max_arr[mask]
        
        hours = times_w.copy()
        if len(hours) == 0:
            # Fallback if no valid times
            now = dt.datetime.now()
            hours = mdates.date2num([now, now + dt.timedelta(days=1)])
        xmin = np.nanmin(hours) - 0.042
        xmax = np.nanmax(hours) + 0.042
        if np.isnan(xmin) or np.isnan(xmax) or xmin >= xmax:
            # Fallback to current time range
            now = dt.datetime.now()
            hours = mdates.date2num([now, now + dt.timedelta(days=1)])
            xmin = hours.min() - 0.042
            xmax = hours.max() + 0.042
        
        # Better time axis setup
        duration_days = xmax - xmin
        if duration_days <= 3:
            major_interval = 0.5
            minor_interval = 0.125
        elif duration_days <= 7:
            major_interval = 1.0
            minor_interval = 0.25
        else:
            major_interval = 1.0
            minor_interval = 0.5
        
        # ============ WIND SPEED PLOT ============
        ax1 = fig.add_subplot(gs[0])
        
        # Plot wind speed
        ax1.plot(times_w, speeds, color=colors['wind_line'], linewidth=2.5, 
                 marker='o', markersize=6, markerfacecolor='white', 
                 markeredgewidth=2, markeredgecolor=colors['wind_line'],
                 label='Wind Speed', zorder=3)
        
        ax1.fill_between(times_w, speeds_min, speeds_max, 
                         color=colors['wind_fill'], alpha=0.4, 
                         label='Wind Spread', zorder=1)
        
        # Subtle error bars
        ax1.errorbar(times_w, speeds, 
                    yerr=[speeds - speeds_min, speeds_max - speeds],
                    fmt='none', ecolor='gray', elinewidth=1.0, 
                    capsize=3, capthick=1.0, alpha=0.3, zorder=2)
        
        # Plot wind gusts if available
        if has_gusts:
            ax1.plot(times_w, gusts, color=colors['gust_line'], linewidth=2.0,
                    linestyle='--', marker='s', markersize=5, markerfacecolor='white',
                    markeredgewidth=2, markeredgecolor=colors['gust_line'],
                    label='Wind Gust', zorder=3)
            
            ax1.fill_between(times_w, gusts_min, gusts_max,
                            color=colors['gust_fill'], alpha=0.3,
                            label='Gust Spread', zorder=1)
            
            ax1.errorbar(times_w, gusts,
                        yerr=[gusts - gusts_min, gusts_max - gusts],
                        fmt='none', ecolor=colors['gust_line'], elinewidth=1.0,
                        capsize=2, capthick=1.0, alpha=0.3, zorder=2)
        
        # Add threshold lines
        ax1.axhline(y=35, color='#FFA500', linestyle=':', linewidth=2, alpha=0.7, label='35kt', zorder=1)
        ax1.axhline(y=50, color='#FF4500', linestyle=':', linewidth=2, alpha=0.7, label='50kt', zorder=1)
        ax1.axhline(y=65, color='#8B0000', linestyle=':', linewidth=2, alpha=0.7, label='65kt', zorder=1)
        
        ax1.set_xlim(xmin, xmax)
        
        # Dynamic y-axis with padding
        y_max_val = np.nanmax(speeds_max) if len(speeds_max) > 0 and np.any(~np.isnan(speeds_max)) else 50.0
        if has_gusts:
            gust_max_val = np.nanmax(gusts_max) if len(gusts_max) > 0 and np.any(~np.isnan(gusts_max)) else 0.0
            y_max_val = max(y_max_val, gust_max_val)
        if np.isnan(y_max_val) or np.isinf(y_max_val) or y_max_val <= 0:
            y_max_val = 50.0
        ax1.set_ylim(bottom=0, top=y_max_val * 1.25)
        
        ax1.xaxis.set_major_locator(MultipleLocator(major_interval))
        ax1.xaxis.set_minor_locator(MultipleLocator(minor_interval))
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%a\n%b %d'))
        ax1.xaxis.set_minor_formatter(mdates.DateFormatter('%H'))
        ax1.tick_params(axis='x', which='major', labelsize=10, pad=8)
        ax1.tick_params(axis='x', which='minor', labelsize=9)
        ax1.set_xlabel('Valid Time (UTC)', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Wind Speed (kt)', fontsize=11, fontweight='bold')
        ax1.grid(True, alpha=0.5, linestyle='-', linewidth=0.7, color=colors['grid'], which='major')
        ax1.grid(True, alpha=0.3, linestyle=':', linewidth=0.4, color=colors['grid_minor'], which='minor')
        ax1.set_axisbelow(True)
        ax1.set_facecolor(colors['background'])
        
        if model_sys == 'Multi-Model':
            title = 'Wind Speed & Gust - Multi-Model Ensemble Mean'
        else:
            title = 'Wind Speed & Gust - GFE with Ensemble Spread'
        
        # Find best legend position based on data density
        best_loc = find_best_legend_position(times_w_dt, speeds, speeds_min, speeds_max)
        if has_gusts:
            # If gusts are present, prefer upper right or upper left to avoid overlap
            if best_loc in ['lower right', 'lower left']:
                best_loc = 'upper right'
        
        ax1.legend(loc=best_loc, framealpha=1.0, 
                  fontsize=8, ncol=3, facecolor='white', edgecolor='gray')
        ax1.set_title(title, fontweight='bold', fontsize=12, pad=5, loc='left')
        
        # Calculate and display average spread
        spread_diff = speeds_max - speeds_min
        avg_spread = np.nanmean(spread_diff) if len(spread_diff) > 0 and np.any(~np.isnan(spread_diff)) else 0.0
        if np.isnan(avg_spread) or np.isinf(avg_spread):
            avg_spread = 0.0
        ax1.text(0.02, 0.95, f'Avg Spread: ±{avg_spread:.1f} kt', 
                transform=ax1.transAxes, va='top', fontsize=9,
                bbox=dict(boxstyle='round,pad=0.4', facecolor='white', 
                         edgecolor='gray', alpha=0.9))
        
        # Annotate wind speed values
        for i in range(len(speeds)):
            if not np.isnan(speeds[i]):
                ax1.annotate(f'{int(speeds[i])}', 
                            xy=(times_w[i], speeds[i]),
                            xytext=(0, -20), textcoords='offset points',
                            ha='center', fontsize=8, fontweight='bold',
                            color=colors['wind_line'],
                            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', 
                                     edgecolor=colors['wind_line'], alpha=0.85, linewidth=1))
        
        # Annotate wind gust values
        if has_gusts:
            for i in range(len(gusts)):
                if not np.isnan(gusts[i]):
                    ax1.annotate(f'{int(gusts[i])}', 
                                xy=(times_w[i], gusts[i]),
                                xytext=(0, 18), textcoords='offset points',
                                ha='center', fontsize=8, fontweight='bold',
                                color=colors['gust_line'],
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', 
                                         edgecolor=colors['gust_line'], alpha=0.85, linewidth=1))
            
        
        # ============ WIND DIRECTION BARBS ============
        ax2 = fig.add_subplot(gs[1])
        
        ax2.set_xlim(xmin, xmax)
        ax2.xaxis.set_major_locator(MultipleLocator(major_interval))
        ax2.xaxis.set_minor_locator(MultipleLocator(minor_interval))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%a\n%b %d'))
        ax2.xaxis.set_minor_formatter(mdates.DateFormatter('%H'))
        ax2.tick_params(axis='x', which='major', labelsize=10, pad=8)
        ax2.tick_params(axis='x', which='minor', labelsize=9)
        ax2.set_xlabel('Valid Time (UTC)', fontsize=11, fontweight='bold')
        ax2.set_ylim(-0.5, 0.5)
        ax2.get_yaxis().set_visible(False)
        
        skip_barb = max(1, len(us)//20)
        barbs = ax2.barbs(hours[::skip_barb], np.zeros(len(hours[::skip_barb])), 
                         us[::skip_barb], vs[::skip_barb],
                         length=8, linewidth=1.5, barbcolor=colors['wind_line'],
                         flagcolor=colors['wind_line'], clip_on=False)
        
        ax2.set_title('Wind Direction', fontweight='bold', fontsize=12, pad=20, loc='left')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['left'].set_visible(False)
        ax2.set_facecolor('#f8f8f8')
        
        # ============ WAVE HEIGHT PLOT ============
        ax3 = fig.add_subplot(gs[2])
        
        # Convert wave data to arrays
        waves_arr = safe_float_array(waves)
        waves_min_arr = safe_float_array(waves_min)
        waves_max_arr = safe_float_array(waves_max)
        wave_total = len(waves_arr)
        wave_valid = int(np.sum(~np.isnan(waves_arr))) if wave_total > 0 else 0
        LogStream.logEvent(f"Wave data summary: total={wave_total}, valid={wave_valid}")
        
        if model_sys == 'Multi-Model':
            wave_title = 'Significant Wave Height - Multi-Model Ensemble Mean'
        else:
            wave_title = 'Significant Wave Height - GFE with Ensemble Spread'
        
        if wave_valid == 0:
            LogStream.logProblem("No valid wave data available for plotting")
            ax3.text(0.5, 0.5, 'Wave data not available',
                     transform=ax3.transAxes, ha='center', va='center',
                     fontsize=12, style='italic', color='gray')
            ax3.set_xlim(xmin, xmax)
            ax3.set_ylim(0, 10)
            ax3.set_title(wave_title, fontweight='bold', fontsize=12, pad=5, loc='left')
        else:
            mask_w = ~np.isnan(waves_arr)
            times_wv_dt = np.array(times)[mask_w]
            waves_plot = waves_arr[mask_w]
            waves_min_plot = waves_min_arr[mask_w]
            waves_max_plot = waves_max_arr[mask_w]
            times_wv = mdates.date2num(times_wv_dt) if len(times_wv_dt) > 0 else np.array([])
            
            ax3.plot(times_wv, waves_plot, color=colors['wave_line'], linewidth=2.5,
                     marker='o', markersize=6, markerfacecolor='white',
                     markeredgewidth=2, markeredgecolor=colors['wave_line'],
                     label='Mean', zorder=3)
            
            ax3.fill_between(times_wv, waves_min_plot, waves_max_plot,
                             color=colors['wave_fill'], alpha=0.4,
                             label='Model Spread', zorder=1)
            
            # Subtle error bars
            ax3.errorbar(times_wv, waves_plot,
                        yerr=[waves_plot - waves_min_plot, waves_max_plot - waves_plot],
                        fmt='none', ecolor='gray', elinewidth=1.0,
                        capsize=3, capthick=1.0, alpha=0.3, zorder=2)
            
            ax3.set_xlim(xmin, xmax)
            
            # Dynamic y-axis with padding
            waves_max_val = np.nanmax(waves_max_plot) if len(waves_max_plot) > 0 and np.any(~np.isnan(waves_max_plot)) else 10.0
            if np.isnan(waves_max_val) or np.isinf(waves_max_val) or waves_max_val <= 0:
                waves_max_val = 10.0
            ax3.set_ylim(bottom=0, top=waves_max_val * 1.25)
            
            ax3.xaxis.set_major_locator(MultipleLocator(major_interval))
            ax3.xaxis.set_minor_locator(MultipleLocator(minor_interval))
            ax3.xaxis.set_major_formatter(mdates.DateFormatter('%a\n%b %d'))
            ax3.xaxis.set_minor_formatter(mdates.DateFormatter('%H'))
            ax3.tick_params(axis='x', which='major', labelsize=10, pad=8)
            ax3.tick_params(axis='x', which='minor', labelsize=9)
            ax3.set_xlabel('Valid Time (UTC)', fontsize=11, fontweight='bold')
            ax3.set_ylabel('Wave Height (ft)', fontsize=11, fontweight='bold')
            ax3.grid(True, alpha=0.5, linestyle='-', linewidth=0.7, color=colors['grid'], which='major')
            ax3.grid(True, alpha=0.3, linestyle=':', linewidth=0.4, color=colors['grid_minor'], which='minor')
            ax3.set_axisbelow(True)
            ax3.set_facecolor(colors['background'])
            
            # Find best legend position based on data density
            best_loc = find_best_legend_position(times_wv_dt, waves_plot, waves_min_plot, waves_max_plot)
            
            ax3.legend(loc=best_loc, framealpha=0.9, 
                      fontsize=9, facecolor='white', edgecolor='gray')
            ax3.set_title(wave_title, fontweight='bold', fontsize=12, pad=5, loc='left')
            
            # Annotate wave height values
            for i in range(len(waves_plot)):
                if not np.isnan(waves_plot[i]):
                    ax3.annotate(f'{waves_plot[i]:.1f}',
                                xy=(times_wv[i], waves_plot[i]),
                                xytext=(0, 18), textcoords='offset points',
                                ha='center', fontsize=8, fontweight='bold',
                                color=colors['wave_line'],
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                         edgecolor=colors['wave_line'], alpha=0.85, linewidth=1))
        
        # ============ WAVE DIRECTION ARROWS ============
        ax4 = fig.add_subplot(gs[3])
        
        ax4.set_xlim(xmin, xmax)
        ax4.xaxis.set_major_locator(MultipleLocator(major_interval))
        ax4.xaxis.set_minor_locator(MultipleLocator(minor_interval))
        ax4.xaxis.set_major_formatter(mdates.DateFormatter('%a\n%b %d'))
        ax4.xaxis.set_minor_formatter(mdates.DateFormatter('%H'))
        ax4.tick_params(axis='x', which='major', labelsize=10, pad=8)
        ax4.tick_params(axis='x', which='minor', labelsize=9)
        ax4.set_xlabel('Valid Time (UTC)', fontsize=11, fontweight='bold')
        ax4.set_ylim(-0.3, 0.3)
        ax4.get_yaxis().set_visible(False)
        
        # Draw wave direction arrows
        if len(wave_dirs) > 0:
            try:
                wave_dirs_array = safe_float_array(wave_dirs)
                mask_wd = ~np.isnan(wave_dirs_array)
                
                if np.any(mask_wd):
                    wave_dirs_valid = wave_dirs_array[mask_wd]
                    hours_wd = mdates.date2num(np.array(times)[mask_wd])
                    
                    skip_arrow = max(1, len(wave_dirs_valid)//15)
                    
                    for i in range(0, len(wave_dirs_valid), skip_arrow):
                        angle_rad = radians(wave_dirs_valid[i])
                        dx = -sin(angle_rad) * 0.06
                        dy = -cos(angle_rad) * 0.06
                        
                        arrow = FancyArrowPatch((hours_wd[i], 0), 
                                              (hours_wd[i] + dx, dy),
                                              arrowstyle='->', 
                                              mutation_scale=12,
                                              linewidth=1.8,
                                              color=colors['wave_line'],
                                              zorder=3)
                        ax4.add_patch(arrow)
                    
                    skip_label = max(1, len(wave_dirs_valid)//8)
                    for i in range(0, len(wave_dirs_valid), skip_label):
                        dir_str = self.windDegToStr(wave_dirs_valid[i])
                        ax4.text(hours_wd[i], 0.22, dir_str, ha='center', va='bottom',
                                fontsize=8, fontweight='bold', color=colors['wave_line'])
                else:
                    ax4.text(0.5, 0.5, 'Wave direction data not available',
                            transform=ax4.transAxes, ha='center', va='center',
                            fontsize=10, style='italic', color='gray')
            except Exception as e:
                LogStream.logProblem(f"Wave direction plot error: {str(e)}")
                ax4.text(0.5, 0.5, 'Wave direction data not available',
                        transform=ax4.transAxes, ha='center', va='center',
                        fontsize=10, style='italic', color='gray')
        else:
            ax4.text(0.5, 0.5, 'Wave direction data not available',
                    transform=ax4.transAxes, ha='center', va='center',
                    fontsize=10, style='italic', color='gray')
        
        ax4.set_title('Wave Direction', fontweight='bold', fontsize=12, pad=20, loc='left')
        ax4.spines['top'].set_visible(False)
        ax4.spines['right'].set_visible(False)
        ax4.spines['left'].set_visible(False)
        ax4.set_facecolor('#f8f8f8')
        
        # ============ WAVE PERIOD PLOT ============
        ax5 = fig.add_subplot(gs[4])
        
        if len(periods) > 0:
            try:
                periods_array = safe_float_array(periods)
                mask_p = ~np.isnan(periods_array)
                
                if np.any(mask_p):
                    times_p_dt = np.array(times)[mask_p]
                    periods_valid = periods_array[mask_p]
                    times_p = mdates.date2num(times_p_dt)
                    
                    ax5.plot(times_p, periods_valid, color=colors['period_line'], 
                            linewidth=2.5, marker='o', markersize=6,
                            markerfacecolor='white', markeredgewidth=2,
                            markeredgecolor=colors['period_line'], zorder=3)
                    
                    # Add y-axis padding for annotations
                    period_max = np.nanmax(periods_valid) if len(periods_valid) > 0 and np.any(~np.isnan(periods_valid)) else 15.0
                    if np.isnan(period_max) or np.isinf(period_max) or period_max <= 0:
                        period_max = 15.0
                    ax5.set_ylim(bottom=0, top=period_max * 1.25)
                    
                    # Annotate wave period values
                    for i in range(len(periods_valid)):
                        if not np.isnan(periods_valid[i]):
                            ax5.annotate(f'{periods_valid[i]:.1f}',
                                        xy=(times_p[i], periods_valid[i]),
                                        xytext=(0, 12), textcoords='offset points',
                                        ha='center', fontsize=8, fontweight='bold',
                                        color=colors['period_line'],
                                        bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                                 edgecolor=colors['period_line'], alpha=0.85, linewidth=1))
                else:
                    ax5.text(0.5, 0.5, 'Wave period data not available',
                            transform=ax5.transAxes, ha='center', va='center',
                            fontsize=10, style='italic', color='gray')
            except Exception as e:
                LogStream.logProblem(f"Wave period plot error: {str(e)}")
                ax5.text(0.5, 0.5, 'Wave period data not available',
                        transform=ax5.transAxes, ha='center', va='center',
                        fontsize=10, style='italic', color='gray')
        else:
            ax5.text(0.5, 0.5, 'Wave period data not available',
                    transform=ax5.transAxes, ha='center', va='center',
                    fontsize=10, style='italic', color='gray')
        
        ax5.set_xlim(xmin, xmax)
        ax5.xaxis.set_major_locator(MultipleLocator(major_interval))
        ax5.xaxis.set_minor_locator(MultipleLocator(minor_interval))
        ax5.xaxis.set_major_formatter(mdates.DateFormatter('%a\n%b %d'))
        ax5.xaxis.set_minor_formatter(mdates.DateFormatter('%H'))
        ax5.tick_params(axis='x', which='major', labelsize=10, pad=8)
        ax5.tick_params(axis='x', which='minor', labelsize=9)
        ax5.set_xlabel('Valid Time (UTC)', fontsize=11, fontweight='bold')
        ax5.set_ylabel('Period (s)', fontsize=11, fontweight='bold')
        ax5.grid(True, alpha=0.5, linestyle='-', linewidth=0.7, color=colors['grid'], which='major')
        ax5.grid(True, alpha=0.3, linestyle=':', linewidth=0.4, color=colors['grid_minor'], which='minor')
        ax5.set_axisbelow(True)
        ax5.set_facecolor(colors['background'])
        ax5.set_title('Wave Period', fontweight='bold', fontsize=12, pad=20, loc='left')
        
        # ============ FOOTER ============
        ax6 = fig.add_subplot(gs[5])
        ax6.axis('off')
        
        now = dt.datetime.now()
        
        ax6.text(0.02, 0.7,
                'NOAA Ocean Prediction Center\n'
                'ncep.opc.idss@noaa.gov | 301-683-1520',
                ha='left', va='top', fontsize=10,
                color='#003366', fontweight='bold',
                transform=ax6.transAxes)
        
        if model_sys == 'Multi-Model':
            if ensemble_count > 0:
                info_text = (f'Models used: {model_list}\n'
                            f'Shaded areas show full model spread (min-max range)\n'
                            f'Ensemble members: {ensemble_count}')
            else:
                info_text = (f'Models used: {model_list}\n'
                            'Shaded areas show full model spread (min-max range)')
        else:
            info_text = ('GFE Forecast with Ensemble Spread\n'
                        'Shaded areas show ensemble model spread')
        
        ax6.text(0.98, 0.7, info_text,
                ha='right', va='top', fontsize=9,
                color='#666666', style='italic',
                transform=ax6.transAxes)
        
        # Add zoom reminder
        ax6.text(0.5, 0.2, 'View image at 100% for best detail',
                ha='center', va='center', fontsize=8, color='gray',
                style='italic', transform=ax6.transAxes)
        
        # Overall title
        title_text = f'Marine Spot Forecast for {point}'
        if model_sys == 'Multi-Model':
            title_text = f'Multi-Model Ensemble ' + title_text
        else:
            title_text = f'GFE with Ensemble ' + title_text
        
        fig.suptitle(f'{title_text}\nIssued: {now.strftime("%H:%M UTC %d %B %Y")}',
                    fontsize=14, fontweight='bold', y=0.985)
        
        # Save with high quality - simplified filename
        now_str = now.strftime('%Y%m%d_%H%M%S')
        point_safe = point.replace(' ', '_')
        filename = os.path.join(spot_dir, f"spot_{point_safe}_{now_str}.png")
        
        try:
            LogStream.logEvent(f"Saving meteogram to: {filename}")
            # Ensure directory exists
            os.makedirs(spot_dir, mode=0o775, exist_ok=True)
            
            plt.savefig(filename, bbox_inches='tight', dpi=150, 
                       facecolor='white', edgecolor='none')
            LogStream.logEvent(f"Meteogram saved successfully: {filename}")
            
            # Check if file was actually created
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                LogStream.logEvent(f"Image file created: {filename} ({file_size} bytes)")
            else:
                LogStream.logProblem(f"ERROR: Image file was not created: {filename}")
            
            plt.close()
            
            # Display image
            try:
                os.system(f'display {filename} &')
                LogStream.logEvent(f"Display command executed for: {filename}")
            except Exception as e:
                LogStream.logProblem(f"Error displaying image: {str(e)}")
            
            return filename
        except Exception as e:
            LogStream.logProblem(f"Error saving meteogram: {str(e)}")
            import traceback
            LogStream.logProblem(f"Traceback: {traceback.format_exc()}")
            try:
                plt.close()
            except:
                pass
            raise
    
    def _deliver_products(self, config, image, text, csv):
        LogStream.logEvent(f"Delivery requested - send_to_intranet: {config['send_to_intranet']}")
        
        if not config['send_to_intranet']:
            LogStream.logEvent("Skipping intranet delivery per user request")
            self.statusBarMsg("Products saved locally (not sent to intranet)", "R")
            return
        
        try:
            script = "/localapps/opc/opcops/.operations/site/bin/send_file_to_external.pl"
            target = "opc opcintra.ncep.noaa.gov '~/www/htdocs/temp_awips'"
            
            if not os.path.exists(script):
                LogStream.logProblem(f"Transfer script not found: {script}")
                self.statusBarMsg("ERROR: Transfer script not found", "S")
                return
            
            for f in [image, text, csv]:
                cmd = f"{script} {f} {target}"
                LogStream.logEvent(f"Executing: {cmd}")
                result = os.system(cmd)
                LogStream.logEvent(f"Transfer result code: {result}")
                
                if result != 0:
                    LogStream.logProblem(f"Transfer failed for {f} with code {result}")
                    self.statusBarMsg(f"Transfer failed - check logs", "S")
            
            self.statusBarMsg("Products sent to intranet", "R")
            self._cleanup_old_files()
            
        except Exception as e:
            LogStream.logProblem(f"Delivery error: {str(e)}")
            self.statusBarMsg(f"Delivery failed: {str(e)}", "S")
    
    def _cleanup_old_files(self):
        cutoff = time.time() - (self._file_retention_days * 86400)
        for f in os.listdir(self._spot_dir):
            path = os.path.join(self._spot_dir, f)
            if os.path.isfile(path) and os.stat(path).st_mtime < cutoff:
                try:
                    os.remove(path)
                except:
                    pass
    
    def execute(self, editArea, timeRange):
        try:
            config = self._get_user_configuration()
            if not config:
                self.cancel()
                return
            
            if not self._validate_inputs(config, timeRange):
                return
            
            self.statusBarMsg("Retrieving data...", "R")
            data = self._retrieve_forecast_data(config, timeRange)
            if not data:
                return
            
            self.statusBarMsg("Saving CSV...", "R")
            try:
                csv_file = self._save_to_csv(data, config)
            except Exception as e:
                LogStream.logProblem(f"CSV save error: {str(e)}")
                self.statusBarMsg(f"ERROR: Failed to save CSV - {str(e)}", "S")
                return
            
            if config['allow_editing']:
                try:
                    data = self._handle_csv_editing(csv_file, data)
                except Exception as e:
                    LogStream.logProblem(f"CSV editing error: {str(e)}")
                    self.statusBarMsg(f"ERROR: CSV editing failed - {str(e)}", "S")
                    return
            
            self.statusBarMsg("Creating outputs...", "R")
            try:
                image, text = self._generate_outputs(data, config, csv_file)
            except Exception as e:
                LogStream.logProblem(f"Output generation error: {str(e)}")
                import traceback
                LogStream.logProblem(f"Traceback: {traceback.format_exc()}")
                self.statusBarMsg(f"ERROR: {str(e)}", "S")
                return
            
            try:
                self._deliver_products(config, image, text, csv_file)
            except Exception as e:
                LogStream.logProblem(f"Product delivery error: {str(e)}")
                # Don't fail the whole process if delivery fails
                self.statusBarMsg(f"Warning: Delivery failed - {str(e)}", "S")
            
            try:
                self._save_current_settings(config['lat'], config['lon'], config['model_system'], 
                                           config.get('selected_models'))
            except Exception as e:
                LogStream.logProblem(f"Settings save error: {str(e)}")
                # Don't fail the whole process if settings save fails
            
            self.statusBarMsg("Complete!", "R")
        except Exception as e:
            LogStream.logProblem(f"Unhandled exception in execute: {str(e)}")
            import traceback
            LogStream.logProblem(f"Traceback: {traceback.format_exc()}")
            self.statusBarMsg(f"ERROR: {str(e)}", "S")
    
