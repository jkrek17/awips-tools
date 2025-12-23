##
# GridComparison - AWIPS2 Grid Difference Analysis Tool
# 
# SOFTWARE HISTORY
# Date         Ticket#    Engineer    Description
# ------------ ---------- ----------- --------------------------
# 2025-05-30   Initial    Developer   Initial Creation
#
# Purpose: Compare two model/forecast grids and create difference analysis
# Usage: Tools -> Edit -> GridComparison
##

MenuItems = ["Edit"]

import LogStream, time
from numpy import *
import math
import JUtil
import tkinter as tk
from tkinter import ttk
import SmartScript
import time
import AbsTime

WeatherElementEdited = "DifferenceGrid"
HideTool = 0
ScreenList = ["Wind", "WaveHeight"]

class Procedure(SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        
    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method"""
        
        # Launch GUI for parameter selection
        params = self._getParameters()
        if not params:
            return
            
        try:
            # Execute grid comparison
            self._performGridComparison(editArea, timeRange, params)
            
        except Exception as e:
            self.statusBarMsg(f"Error in GridComparison: {str(e)}", "S")
            
    def _getParameters(self):
        """Custom GUI for parameter selection"""
        
        root = tk.Tk()
        root.title("Grid Comparison Tool")
        root.geometry("500x650")
        root.resizable(False, False)
        
        # Result storage
        result = {'cancelled': True}
        
        # Main frame
        main_frame = ttk.Frame(root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="Grid Comparison Analysis", 
                               font=('Arial', 14, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Model definitions
        models = [
            ("GFS (Global Forecast System)", "GFS", 4),
            ("ECMWF (European Centre)", "nECMWF0p25", 2), 
            ("CMC (Canadian Global)", "CMCnh", 4),
            ("UKMET (UK Met Office)", "UKMEThr", 4),
            ("GEFS Mean (GFS Ensemble)", "GEFSMEAN", 4),
            ("ECENS Mean (ECMWF Ensemble)", "ECENSMEAN", 2),
            ("Official (Published Grid)", "Official", 0),
            ("Fcst (Forecast Grid)", "Fcst", 0)
        ]
        
        # Create model lookup dictionaries
        model_display_names = [f"{name} ({db})" if db not in ["Official", "Fcst"] else name for name, db, runs in models]
        model_db_lookup = {f"{name} ({db})" if db not in ["Official", "Fcst"] else name: db for name, db, runs in models}
        model_runs_lookup = {f"{name} ({db})" if db not in ["Official", "Fcst"] else name: runs for name, db, runs in models}
        
        # Weather Element Selection
        ttk.Label(main_frame, text="Weather Element:").grid(row=1, column=0, sticky=tk.W, pady=5)
        element_var = tk.StringVar(value="Wind")
        element_combo = ttk.Combobox(main_frame, textvariable=element_var, width=15)
        element_combo['values'] = ("Wind", "WaveHeight")
        element_combo.grid(row=1, column=1, sticky=tk.W, pady=5)
        
        # Wind Component Selection (only visible for Wind element)
        wind_frame = ttk.LabelFrame(main_frame, text="Wind Components", padding=5)
        wind_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        
        wind_speed_var = tk.BooleanVar(value=True)
        wind_dir_var = tk.BooleanVar(value=False)
        
        ttk.Checkbutton(wind_frame, text="Wind Speed (magnitude)", 
                       variable=wind_speed_var).grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Checkbutton(wind_frame, text="Wind Direction", 
                       variable=wind_dir_var).grid(row=1, column=0, sticky=tk.W, pady=2)
        
        wind_note_label = ttk.Label(wind_frame, text="Select one or both components to analyze", 
                                   font=('Arial', 8), foreground='gray')
        wind_note_label.grid(row=2, column=0, sticky=tk.W, pady=(5, 0))
        
        # Function to show/hide wind component options
        def toggle_wind_options(*args):
            if element_var.get() == "Wind":
                wind_frame.grid()
            else:
                wind_frame.grid_remove()
        
        # Bind element selection to show/hide wind options
        element_var.trace('w', toggle_wind_options)
        
        # Initialize visibility
        toggle_wind_options()
        
        # Grid Source 1
        ttk.Label(main_frame, text="Grid Source 1:", font=('Arial', 10, 'bold')).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(15, 5))
        
        ttk.Label(main_frame, text="Model:").grid(row=4, column=0, sticky=tk.W, pady=2)
        model1_var = tk.StringVar(value=model_display_names[0])
        model1_combo = ttk.Combobox(main_frame, textvariable=model1_var, width=25)
        model1_combo['values'] = model_display_names
        model1_combo.grid(row=4, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(main_frame, text="Previous Run:").grid(row=5, column=0, sticky=tk.W, pady=2)
        prev_run1_var = tk.StringVar(value="0")
        prev_run1_combo = ttk.Combobox(main_frame, textvariable=prev_run1_var, width=15)
        prev_run1_combo.grid(row=5, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(main_frame, text="Time Offset (hrs):").grid(row=6, column=0, sticky=tk.W, pady=2)
        offset1_var = tk.StringVar(value="0")
        offset1_entry = ttk.Entry(main_frame, textvariable=offset1_var, width=10)
        offset1_entry.grid(row=6, column=1, sticky=tk.W, pady=2)
        
        # Grid Source 2
        ttk.Label(main_frame, text="Grid Source 2:", font=('Arial', 10, 'bold')).grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(15, 5))
        
        ttk.Label(main_frame, text="Model:").grid(row=8, column=0, sticky=tk.W, pady=2)
        model2_var = tk.StringVar(value=model_display_names[1] if len(model_display_names) > 1 else model_display_names[0])
        model2_combo = ttk.Combobox(main_frame, textvariable=model2_var, width=25)
        model2_combo['values'] = model_display_names
        model2_combo.grid(row=8, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(main_frame, text="Previous Run:").grid(row=9, column=0, sticky=tk.W, pady=2)
        prev_run2_var = tk.StringVar(value="0")
        prev_run2_combo = ttk.Combobox(main_frame, textvariable=prev_run2_var, width=15)
        prev_run2_combo.grid(row=9, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(main_frame, text="Time Offset (hrs):").grid(row=10, column=0, sticky=tk.W, pady=2)
        offset2_var = tk.StringVar(value="0")
        offset2_entry = ttk.Entry(main_frame, textvariable=offset2_var, width=10)
        offset2_entry.grid(row=10, column=1, sticky=tk.W, pady=2)
        
        # Function to update previous run options based on model selection
        def update_prev_runs(combo_var, prev_run_combo, prev_run_var):
            def callback(*args):
                selected_model = combo_var.get()
                max_runs = model_runs_lookup.get(selected_model, 0)
                if max_runs == 0:
                    # Official and Fcst don't have previous runs
                    prev_run_combo['values'] = ("0 (Current)",)
                    prev_run_combo.config(state='disabled')
                    prev_run_var.set("0")
                else:
                    # Generate options for previous runs
                    run_options = ["0 (Current)"]
                    for i in range(1, max_runs + 1):
                        if i == 1:
                            run_options.append(f"{i} (Previous)")
                        else:
                            run_options.append(f"{i} ({i} runs ago)")
                    prev_run_combo['values'] = run_options
                    prev_run_combo.config(state='readonly')
                    prev_run_var.set("0")
            return callback
        
        # Bind model selection to previous run updates
        model1_var.trace('w', update_prev_runs(model1_var, prev_run1_combo, prev_run1_var))
        model2_var.trace('w', update_prev_runs(model2_var, prev_run2_combo, prev_run2_var))
        
        # Initialize previous run options
        update_prev_runs(model1_var, prev_run1_combo, prev_run1_var)()
        update_prev_runs(model2_var, prev_run2_combo, prev_run2_var)()
        
        # Analysis Options
        ttk.Label(main_frame, text="Analysis Options:", font=('Arial', 10, 'bold')).grid(row=11, column=0, columnspan=2, sticky=tk.W, pady=(15, 5))
        
        create_grid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main_frame, text="Create Difference Grid(s)", 
                       variable=create_grid_var).grid(row=12, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # Error message label
        error_label = ttk.Label(main_frame, text="", foreground="red", font=('Arial', 9))
        error_label.grid(row=13, column=0, columnspan=2, pady=(10, 0))
        
        # Description text
        desc_text = tk.Text(main_frame, height=7, width=50, font=('Arial', 9))
        desc_text.grid(row=14, column=0, columnspan=2, pady=(15, 10))
        desc_text.insert('1.0', 
            "This tool compares two weather grids and creates signed difference grid(s).\n\n"
            "• For Wind: Select speed, direction, or both components\n"
            "• Creates ONE grid per selected component:\n"
            "  - WindSpeedDiff (signed: + means Grid1 > Grid2)\n"
            "  - WindDirectionDiff (signed: + means Grid1 more clockwise)\n"
            "• Grid stores ALL calculated values (no data clipping)\n"
            "• Use grid display settings to adjust color scaling as needed")
        desc_text.config(state='disabled')
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=15, column=0, columnspan=2, pady=(10, 0))
        
        def clear_error():
            """Clear error message after delay"""
            root.after(5000, lambda: error_label.config(text=""))
        
        def on_ok():
            try:
                # Clear any previous error
                error_label.config(text="")
                
                # Validate wind component selection for Wind element
                if element_var.get() == "Wind":
                    if not wind_speed_var.get() and not wind_dir_var.get():
                        error_label.config(text="ERROR: Select at least one wind component")
                        clear_error()
                        return
                
                # Extract database names from selected models
                model1_selected = model1_var.get()
                model2_selected = model2_var.get()
                
                db1 = model_db_lookup[model1_selected]
                db2 = model_db_lookup[model2_selected]
                
                # Extract previous run numbers (convert from display string to integer)
                prev_run1_str = prev_run1_var.get()
                prev_run2_str = prev_run2_var.get()
                
                prev_run1 = int(prev_run1_str.split()[0])  # Extract number from "0 (Current)" etc.
                prev_run2 = int(prev_run2_str.split()[0])
                
                # Validate numeric inputs
                offset1 = int(offset1_var.get())
                offset2 = int(offset2_var.get())
                
                result.update({
                    'cancelled': False,
                    'element': element_var.get(),
                    'wind_speed': wind_speed_var.get(),
                    'wind_direction': wind_dir_var.get(),
                    'model1_display': model1_selected,
                    'model2_display': model2_selected,
                    'db1': db1,
                    'db2': db2,
                    'prev_run1': prev_run1,
                    'prev_run2': prev_run2,
                    'offset1': offset1,
                    'offset2': offset2,
                    'create_grid': create_grid_var.get()
                })
                root.destroy()
            except ValueError as e:
                error_label.config(text=f"ERROR: Invalid numeric input - {str(e)}")
                clear_error()
            except KeyError as e:
                error_label.config(text=f"ERROR: Invalid model selection - {str(e)}")
                clear_error()
            except Exception as e:
                error_label.config(text=f"ERROR: {str(e)}")
                clear_error()
        
        def on_cancel():
            root.destroy()
        
        ttk.Button(button_frame, text="Execute", command=on_ok, width=12).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        
        # Center window
        root.update_idletasks()
        root.geometry(f"+{root.winfo_screenwidth()//2 - root.winfo_width()//2}+"
                     f"{root.winfo_screenheight()//2 - root.winfo_height()//2}")
        
        root.mainloop()
        
        return None if result['cancelled'] else result
    
    def _performGridComparison(self, editArea, timeRange, params):
        """Perform the grid comparison analysis for each time period"""
        
        self.statusBarMsg("Starting grid comparison analysis...", "R")
        
        # Get forecast grid info to process each time period
        try:
            fcst = self.mutableID().modelIdentifier()
            gridinfos = self.getGridInfo(fcst, params['element'], "SFC", timeRange)
            
            if not gridinfos:
                self.statusBarMsg(f"No {params['element']} grids found in time range", "S")
                return
                
            self.statusBarMsg(f"Processing {len(gridinfos)} time periods...", "R")
            
            # Process each forecast time period
            for i, gridinfo in enumerate(gridinfos):
                GridTimeRange = gridinfo.gridTime()
                self.statusBarMsg(f"Processing time {i+1}/{len(gridinfos)}: {GridTimeRange.startTime().string()}", "R")
                
                # Determine wind components to analyze
                wind_components = None
                if params['element'] == "Wind":
                    wind_components = {
                        'speed': params['wind_speed'],
                        'direction': params['wind_direction']
                    }
                
                # Get grids for comparison for this time period
                grid1_data = self._getComparisonGrid(params['db1'], params['element'], 
                                                   GridTimeRange, params['offset1'], params['prev_run1'], wind_components)
                grid2_data = self._getComparisonGrid(params['db2'], params['element'], 
                                                   GridTimeRange, params['offset2'], params['prev_run2'], wind_components)
                
                if grid1_data is None or grid2_data is None:
                    self.statusBarMsg(f"Skipping time period - failed to retrieve grids", "S")
                    continue
                
                grid1, tr1, db1_info = grid1_data
                grid2, tr2, db2_info = grid2_data
                
                # Handle different analysis types
                if params['element'] == "Wind" and isinstance(grid1, dict):
                    # Process wind components separately
                    self._processWindComponents(grid1, grid2, GridTimeRange, params)
                else:
                    # Process single scalar grid
                    self._processSingleGrid(grid1, grid2, GridTimeRange, params)
            
            self.statusBarMsg("Grid comparison analysis complete", "R")
            
        except Exception as e:
            self.statusBarMsg(f"Error in grid comparison: {str(e)}", "S")
    
    def getWaveID(self, userModel):
        """Return the wave model ID for given model"""
        waveMap = {
            "GFS": "GFSwaveNH",
            "nECMWF0p25": "nECMWF0p25wave",
            "CMCnh": "CMCwave",
            "UKMEThr": "UKMETwave", 
            "GEFSMEAN": "GEFSwaveNH",
            "ECENSMEAN": "ECENSwave",
            "Official": "Official",
            "Fcst": "Fcst"
        }
        return waveMap.get(userModel, userModel)
    
    def getModelGridWithFallback(self, modelName, elementName, level, timeRange, maxRuns=3):
        """Get model grid with fallback to previous runs if current run doesn't have data"""
        if modelName in ["Fcst", "Official"]:
            if modelName == "Fcst":
                return self.getGrids(self.mutableID().modelIdentifier(), elementName, level, timeRange, mode="First", noDataError=0)
            else:
                return self.getGrids("Official", elementName, level, timeRange, mode="First", noDataError=0)
        
        # For model databases, try current run first, then fallback
        for run in range(maxRuns):
            runOffset = -run if run > 0 else 0
            db = self.findDatabase(modelName, runOffset)
            if db is not None:
                grid = self.getGrids(db.modelIdentifier(), elementName, level, timeRange, mode="First", noDataError=0)
                if grid is not None:
                    if runOffset < 0:
                        self.statusBarMsg(f"Using {modelName} {elementName} from {abs(runOffset)} cycles ago", "S")
                    return grid
        
        return None
    
    def _getComparisonGrid(self, database, element, GridTimeRange, offset_hours, prev_run=0, wind_components=None):
        """Retrieve grid for comparison with time offset and previous run selection"""
        
        try:
            # For WaveHeight, use the corresponding wave model database
            actual_database = database
            if element == "WaveHeight":
                actual_database = self.getWaveID(database)
                if actual_database is None:
                    self.statusBarMsg(f"No wave model available for {database}", "S")
                    return None
            
            # Handle time offset by modifying the time range
            target_time = GridTimeRange
            if offset_hours != 0:
                # Calculate offset time
                start_time_secs = GridTimeRange.startTime().unixTime() + (offset_hours * 3600)
                end_time_secs = GridTimeRange.endTime().unixTime() + (offset_hours * 3600)
                
                # Create new time range with offset
                target_start = AbsTime.AbsTime(start_time_secs)
                target_end = AbsTime.AbsTime(end_time_secs)
                target_time = self.createTimeRange(target_start, target_end)
            
            # Get grid data using fallback method
            if prev_run > 0:
                # For previous runs, adjust the database access
                if actual_database in ["Fcst", "Official"]:
                    self.statusBarMsg(f"{actual_database} doesn't have previous runs", "S")
                    return None
                else:
                    # Try to find previous run database
                    db = self.findDatabase(actual_database, -prev_run)
                    if db is not None:
                        grid_data = self.getGrids(db.modelIdentifier(), element, "SFC", target_time, mode="First", noDataError=0)
                    else:
                        self.statusBarMsg(f"Previous run {prev_run} not available for {actual_database}", "S")
                        return None
            else:
                # Use current run with fallback
                grid_data = self.getModelGridWithFallback(actual_database, element, "SFC", target_time)
            
            if grid_data is None:
                self.statusBarMsg(f"Failed to retrieve {element} grid from {actual_database}", "S")
                return None
            
            # Handle different element types
            if element == "Wind":
                # Wind is a vector - extract requested components
                if isinstance(grid_data, tuple) and len(grid_data) == 2:
                    wind_speed, wind_direction = grid_data
                    
                    result_grids = {}
                    if wind_components and wind_components.get('speed', False):
                        result_grids['speed'] = wind_speed
                    if wind_components and wind_components.get('direction', False):
                        result_grids['direction'] = wind_direction
                    
                    if not result_grids:
                        self.statusBarMsg(f"No wind components selected for analysis", "S")
                        return None
                        
                    grid = result_grids
                else:
                    self.statusBarMsg(f"Unexpected Wind grid format from {actual_database}", "S")
                    return None
            else:
                # WaveHeight is scalar
                grid = grid_data
            
            # Create descriptive database info using original database name for clarity
            run_info = ""
            if prev_run > 0:
                run_info = f" (Run-{prev_run})"
            elif database not in ["Fcst", "Official"]:
                run_info = " (Current)"
                
            offset_info = f" +{offset_hours}h" if offset_hours > 0 else f" {offset_hours}h" if offset_hours < 0 else ""
            
            # Show both the user-selected model and actual database used for waves
            if element == "WaveHeight" and actual_database != database:
                db_info = f"{database}→{actual_database}{run_info}{offset_info} ({target_time.startTime().string()})"
            else:
                db_info = f"{database}{run_info}{offset_info} ({target_time.startTime().string()})"
            
            return grid, target_time, db_info
            
        except Exception as e:
            self.statusBarMsg(f"Error retrieving grid from {database}: {str(e)}", "S")
            return None
    
    def createTimeRange(self, startTime, endTime):
        """Create a time range using AbsTime objects"""
        # Use the proper AWIPS2 method from TimeRange
        from com.raytheon.uf.common.time import TimeRange
        return TimeRange(startTime, endTime)
    
    def _processWindComponents(self, grid1_dict, grid2_dict, time_range, params):
        """Process wind speed and/or direction components separately"""
        
        for component in ['speed', 'direction']:
            if component not in grid1_dict or component not in grid2_dict:
                continue
                
            self.statusBarMsg(f"Processing wind {component}...", "R")
            
            grid1 = grid1_dict[component]
            grid2 = grid2_dict[component]
            
            # Handle direction differences specially (angular)
            if component == 'direction':
                diff_grid = self._calculateDirectionDifference(grid1, grid2, use_abs=False)
                diff_type = "Wind Direction Difference"
                grid_name = "WindDirectionDiff"
            else:
                # Standard signed difference for speed
                diff_grid = grid1 - grid2
                diff_type = "Wind Speed Difference"
                grid_name = "WindSpeedDiff"
            
            # Create difference grid if requested
            if params['create_grid']:
                self._createComponentDifferenceGrid(diff_grid, time_range, grid_name, diff_type)
    
    def _processSingleGrid(self, grid1, grid2, time_range, params):
        """Process single scalar grid (like WaveHeight)"""
        
        self.statusBarMsg("Calculating grid differences...", "R")
        
        # Always use signed differences to show which model is higher
        diff_grid = grid1 - grid2
        diff_type = f"{params['element']} Difference"
        
        # Create difference grid if requested
        if params['create_grid']:
            self._createDifferenceGrid(diff_grid, time_range, diff_type)
    
    def _calculateDirectionDifference(self, dir1, dir2, use_abs=False):
        """
        Calculate relative angular difference for wind direction, handling wrap-around
        
        This calculates the smallest angular difference between two directions.
        Example: NW (315°) to NE (45°) = 90° rotation (not 270°)
        Result is always in the range [-180°, +180°]
        Positive = clockwise rotation, Negative = counterclockwise rotation
        """
        
        # Calculate angular difference with proper wrap-around
        diff = dir1 - dir2
        
        # Normalize to [-180, 180] range for smallest angular difference
        diff = where(diff > 180, diff - 360, diff)
        diff = where(diff < -180, diff + 360, diff)
        
        if use_abs:
            diff = abs(diff)
        
        return diff
    
    def _createDifferenceGrid(self, diff_grid, time_range, diff_type):
        """Create the difference grid with appropriate constraints"""
        
        try:
            self.statusBarMsg("Creating difference grid...", "R")
            
            # Create the grid with wide constraints for general elements
            grid_name = "GridDiff"
            self.createGrid("Fcst", grid_name, "SCALAR", diff_grid, time_range,
                          minAllowedValue=-999.0, maxAllowedValue=999.0)
            
            self.statusBarMsg(f"Grid difference created: {diff_type}", "R")
            
        except Exception as e:
            self.statusBarMsg(f"Error creating difference grid: {str(e)}", "S")
    
    def _createComponentDifferenceGrid(self, diff_grid, time_range, grid_name, diff_type):
        """Create difference grid for wind components with appropriate constraints"""
        
        try:
            self.statusBarMsg(f"Creating {grid_name} grid...", "R")
            
            # Set appropriate constraints based on component type
            if "Direction" in grid_name:
                # Wind direction differences: relative angular differences -180 to +180 degrees
                self.createGrid("Fcst", grid_name, "SCALAR", diff_grid, time_range,
                              minAllowedValue=-180.0, maxAllowedValue=180.0)
            else:
                # Wind speed differences: typical range -20 to +20 knots
                self.createGrid("Fcst", grid_name, "SCALAR", diff_grid, time_range,
                              minAllowedValue=-40.0, maxAllowedValue=40.0)
            
            self.statusBarMsg(f"{grid_name} grid created: {diff_type}", "R")
            
        except Exception as e:
            self.statusBarMsg(f"Error creating {grid_name} grid: {str(e)}", "S")