# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# Marine_Wind_Fog_Analysis.py - Marine Wind Mixing and Fog Analysis Tool
# Version 2.1 - Enhanced with RTOFS SST and 925mb options
#
# Calculates marine wind mixing potential and fog formation potential:
# 1. SST-T850/T925 instability (ingredient for wind mixing)
# 2. Wind mixing potential (general and specific thresholds)
# 3. Marine fog formation potential
#
# Author: AWIPS2 Developer
# ----------------------------------------------------------------------------

MenuItems = ["Edit"]
import LogStream, time
import numpy as np
import tkinter as tk
import SmartScript

# Empty VariableList since we're using custom GUI
VariableList = []

class Marine_Wind_Fog_GUI:
    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Wind Mixing and Fog Analysis - Enhanced")
        self.master.geometry("650x1400")
        self.master.resizable(False, False)
        
        self.createWidgets()
        
    def updateSelection(self, *args):
        """Update selection status"""
        if not hasattr(self, 'statusLabel') or not hasattr(self, 'messageLabel'):
            return
            
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        
        if selectedCount == 0:
            self.statusLabel.config(text="No Models Selected", fg="red")
            self.messageLabel.config(text="Select at least one atmospheric model", fg="red")
        else:
            self.statusLabel.config(text=f"{selectedCount} Model(s) Selected", fg="green")
            self.messageLabel.config(text="Ready for analysis", fg="green")

    def createWidgets(self):
        # Main frame
        mainFrame = tk.Frame(self.master, padx=15, pady=15)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Marine Wind Mixing and Fog Analysis - Enhanced", 
                             font=("Arial", 16, "bold"))
        titleLabel.pack(pady=(0, 5))
        
        # Description
        descLabel = tk.Label(mainFrame, 
                           text="Analyzes potential for high winds aloft to mix down and marine fog formation\nNow with RTOFS SST and 925mb temperature options",
                           font=("Arial", 10), fg="gray", justify=tk.CENTER)
        descLabel.pack(pady=(0, 15))
        
        # SST Source Selection Frame
        sstFrame = tk.LabelFrame(mainFrame, text="Sea Surface Temperature Source", padx=15, pady=10)
        sstFrame.pack(fill=tk.X, pady=(0, 15))
        
        self.sstSource = tk.StringVar()
        self.sstSource.set("Fcst")
        
        tk.Label(sstFrame, text="Select SST data source:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        
        sstSourceFrame = tk.Frame(sstFrame)
        sstSourceFrame.pack(fill=tk.X, pady=(5, 0))
        
        tk.Radiobutton(sstSourceFrame, text="Forecast SST (Fcst database)", 
                      variable=self.sstSource, value="Fcst", font=("Arial", 10)).pack(anchor=tk.W)
        tk.Radiobutton(sstSourceFrame, text="RTOFS SST (Real-Time Ocean Forecast)", 
                      variable=self.sstSource, value="RTOFS", font=("Arial", 10)).pack(anchor=tk.W)
        
        tk.Label(sstFrame, text="• Fcst SST: Local/regional SST analysis", 
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(sstFrame, text="• RTOFS SST: NOAA's operational ocean model", 
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Model Selection Frame
        modelFrame = tk.LabelFrame(mainFrame, text="Select Atmospheric Models", padx=15, pady=10)
        modelFrame.pack(fill=tk.X, pady=(0, 15))
        
        # Create status labels first
        self.statusLabel = tk.Label(modelFrame, text="No Models Selected", 
                                  font=("Arial", 11, "bold"), fg="red")
        self.statusLabel.pack(side=tk.BOTTOM, pady=(10, 0))
        
        self.messageLabel = tk.Label(modelFrame, text="Select at least one atmospheric model", 
                                   font=("Arial", 9), fg="red")
        self.messageLabel.pack(side=tk.BOTTOM)
        
        # Atmospheric model definitions (only models with 850mb data)
        atmModels = [
            ("GFS (Global Forecast System)", "GFS"),
            ("ECMWF (European Centre)", "nECMWF0p25"),
            ("CMC (Canadian Global)", "CMCnh"),
            ("UKMET (UK Met Office)", "UKMEThires4")
        ]
        
        self.modelSelections = {}
        
        tk.Label(modelFrame, text="Atmospheric Models (for 850/925 mb data):", 
                font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        
        for displayName, modelId in atmModels:
            var = tk.StringVar()
            var.set("No")
            self.modelSelections[modelId] = var
            
            cb = tk.Checkbutton(modelFrame, text=displayName, 
                              variable=var, onvalue="Yes", offvalue="No",
                              command=self.updateSelection, anchor=tk.W, font=("Arial", 10))
            cb.pack(fill=tk.X, pady=2)
        
        # Set default selection
        self.modelSelections["GFS"].set("Yes")
        self.statusLabel.config(text="1 Model Selected", fg="green")
        self.messageLabel.config(text="Ready for analysis", fg="green")
        
        # Output Grid Selection Frame
        outputFrame = tk.LabelFrame(mainFrame, text="Output Grids to Create", padx=15, pady=10)
        outputFrame.pack(fill=tk.X, pady=(0, 15))
        
        self.outputGrids = {}
        
        # Grid options - enhanced with 925mb options
        gridOptions = [
            # 850mb-based grids
            ("SSTInstability850", "SST-T850 instability index", True),
            ("WindMixingPotential850", "Wind mixing potential (850mb-based)", True),
            ("Wind35ktPotential850", "Potential for winds >35 knots (850mb)", True),
            ("Wind50ktPotential850", "Potential for winds >50 knots (850mb)", False),
            ("Wind65ktPotential850", "Potential for winds >65 knots (850mb)", False),
            
            # 925mb-based grids (NEW)
            ("SSTInstability925", "SST-T925 instability index", True),
            ("WindMixingPotential925", "Wind mixing potential (925mb-based)", True),
            ("Wind35ktPotential925", "Potential for winds >35 knots (925mb)", False),
            ("Wind50ktPotential925", "Potential for winds >50 knots (925mb)", False),
            ("Wind65ktPotential925", "Potential for winds >65 knots (925mb)", False),
            
            # Other grids
            ("FogPotential", "Marine fog formation potential", True),
            ("BulkRichardson", "Bulk Richardson Number", False),
            ("WindShear", "850-925mb wind shear magnitude", False),
            ("SSTGrid", "SST values (for reference)", False)
        ]
        
        # Group grids by category
        tk.Label(outputFrame, text="850mb Temperature-Based Grids:", 
                font=("Arial", 10, "bold"), fg="blue").pack(anchor=tk.W)
        
        for gridId, description, default in gridOptions[:5]:
            var = tk.BooleanVar()
            var.set(default)
            self.outputGrids[gridId] = var
            
            cb = tk.Checkbutton(outputFrame, text=f"✓ {description}", 
                              variable=var, anchor=tk.W, font=("Arial", 9))
            cb.pack(fill=tk.X, pady=1, padx=(20, 0))
        
        tk.Label(outputFrame, text="\n925mb Temperature-Based Grids:", 
                font=("Arial", 10, "bold"), fg="darkgreen").pack(anchor=tk.W)
        
        for gridId, description, default in gridOptions[5:10]:
            var = tk.BooleanVar()
            var.set(default)
            self.outputGrids[gridId] = var
            
            cb = tk.Checkbutton(outputFrame, text=f"✓ {description}", 
                              variable=var, anchor=tk.W, font=("Arial", 9))
            cb.pack(fill=tk.X, pady=1, padx=(20, 0))
        
        tk.Label(outputFrame, text="\nOther Analysis Grids:", 
                font=("Arial", 10, "bold"), fg="purple").pack(anchor=tk.W)
        
        for gridId, description, default in gridOptions[10:]:
            var = tk.BooleanVar()
            var.set(default)
            self.outputGrids[gridId] = var
            
            cb = tk.Checkbutton(outputFrame, text=f"✓ {description}", 
                              variable=var, anchor=tk.W, font=("Arial", 9))
            cb.pack(fill=tk.X, pady=1, padx=(20, 0))
        
        # Analysis Options Frame
        optionsFrame = tk.LabelFrame(mainFrame, text="Analysis Options", padx=15, pady=10)
        optionsFrame.pack(fill=tk.X, pady=(0, 15))
        
        # Model Run Selection
        tk.Label(optionsFrame, text="Model Run:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.modelRun = tk.StringVar()
        self.modelRun.set("Current")
        
        runFrame = tk.Frame(optionsFrame)
        runFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Radiobutton(runFrame, text="Current Run", variable=self.modelRun, 
                      value="Current", font=("Arial", 10)).pack(side=tk.LEFT)
        tk.Radiobutton(runFrame, text="Previous Run", variable=self.modelRun, 
                      value="Previous", font=("Arial", 10)).pack(side=tk.LEFT, padx=(20, 0))
        
        # Interpretation Frame
        interpFrame = tk.LabelFrame(mainFrame, text="Interpretation Guide", padx=15, pady=10)
        interpFrame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(interpFrame, text="WIND MIXING (0-10 scale):",
                font=("Arial", 10, "bold"), fg="blue").pack(anchor=tk.W)
        tk.Label(interpFrame, text="• 850mb-based: Traditional upper-level wind mixing",
                font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))
        tk.Label(interpFrame, text="• 925mb-based: Lower-level wind mixing (more immediate)",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(interpFrame, text="• 7-10: High potential, 4-6: Moderate, 0-3: Low",
                font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))
        
        tk.Label(interpFrame, text="\nINSTABILITY INDICES:",
                font=("Arial", 10, "bold"), fg="purple").pack(anchor=tk.W)
        tk.Label(interpFrame, text="• Positive: Unstable (SST > air temp), favors mixing",
                font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))
        tk.Label(interpFrame, text="• Negative: Stable (SST < air temp), suppresses mixing",
                font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))
        tk.Label(interpFrame, text="• 925mb typically shows stronger gradients than 850mb",
                font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))
        
        # Buttons Frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(15, 0))
        
        tk.Button(buttonFrame, text="Run Analysis", command=self.runTool, 
                 bg="lightblue", font=("Arial", 11, "bold"), width=15).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(buttonFrame, text="Cancel", command=self.cancel, 
                 font=("Arial", 11), width=12).pack(side=tk.LEFT)
    
    def getValues(self):
        """Return dictionary of selected options"""
        selectedModels = []
        for modelId, var in self.modelSelections.items():
            if var.get() == "Yes":
                selectedModels.append(modelId)
        
        selectedOutputs = []
        for gridId, var in self.outputGrids.items():
            if var.get():
                selectedOutputs.append(gridId)
        
        return {
            "Atmospheric Models": selectedModels,
            "SST Source": self.sstSource.get(),
            "Model Run": self.modelRun.get(),
            "Output Grids": selectedOutputs
        }
    
    def runTool(self):
        """Validate inputs and run the tool"""
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        if selectedCount == 0:
            self.messageLabel.config(text="ERROR: Select at least 1 model!", fg="red")
            self.master.after(3000, lambda: self.messageLabel.config(text=""))
            return
        
        outputCount = sum(1 for var in self.outputGrids.values() if var.get())
        if outputCount == 0:
            self.messageLabel.config(text="ERROR: Select at least 1 output grid!", fg="red")
            self.master.after(3000, lambda: self.messageLabel.config(text=""))
            return
        
        # Get values and close GUI
        self.callback(self.getValues())
        self.master.destroy()

    def cancel(self):
        """Close without running"""
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def showGUI(self, editArea, timeRange):
        """Show the custom GUI and get parameters"""
        print("Showing GUI...")
        self.editArea = editArea
        self.timeRange = timeRange
        self.varDict = None
        
        root = tk.Tk()
        gui = Marine_Wind_Fog_GUI(root, self.guiCallback)
        root.mainloop()
        
        print("GUI completed, varDict:", self.varDict)
        return self.varDict
    
    def guiCallback(self, values):
        """Callback from GUI"""
        print("GUI callback received with values:", values)
        self.varDict = values

    def getSST(self, sstSource, GridTimeRange):
        """Get SST data from specified source"""
        sst_grid = None
        
        if sstSource == "RTOFS":
            # Get RTOFS SST data
            print("Attempting to retrieve RTOFS SST data...")
            try:
                # Try to find RTOFS database
                rtofsModelID = "D2D_RTOFS"
                rtofsDB = self.findDatabase(rtofsModelID, 0)
                
                if rtofsDB is None:
                    print("Warning: RTOFS database not found, falling back to Fcst SST")
                    return self.getSST("Fcst", GridTimeRange)
                
                rtofsDataBaseID = rtofsDB.modelIdentifier()
                print(f"Found RTOFS database: {rtofsDataBaseID}")
                
                # Get first grid time range for RTOFS
                info = self.getGridInfo(rtofsDataBaseID, "SST", "SFC", GridTimeRange)
                if info:
                    firstGridTR = info[0].gridTime()
                else:
                    firstGridTR = GridTimeRange
                
                # Retrieve RTOFS SST
                rtofs_sst = self.getGrids(rtofsDataBaseID, "SST", "SFC", firstGridTR, noDataError=0)
                
                if rtofs_sst is not None:
                    # Handle temperature units for RTOFS
                    if np.max(rtofs_sst) > 50.0:
                        sst_celsius = (rtofs_sst - 32.0) * 5.0/9.0
                    else:
                        sst_celsius = rtofs_sst
                    
                    sst_grid = sst_celsius.copy()
                    print("Successfully retrieved RTOFS SST data")
                else:
                    print("Warning: Failed to retrieve RTOFS SST, falling back to Fcst SST")
                    return self.getSST("Fcst", GridTimeRange)
                    
            except Exception as e:
                print(f"Error retrieving RTOFS SST: {str(e)}, falling back to Fcst SST")
                return self.getSST("Fcst", GridTimeRange)
        
        else:  # Fcst SST
            print("Retrieving Forecast SST data...")
            try:
                fcst = self.mutableID().modelIdentifier()
                sst_data = self.getGrids(fcst, "SST", "SFC", GridTimeRange, noDataError=0)
                
                if sst_data is None:
                    print("ERROR: Failed to retrieve Fcst SST data")
                    return None
                
                # Handle temperature units
                if np.max(sst_data) > 50.0:
                    sst_celsius = (sst_data - 32.0) * 5.0/9.0
                else:
                    sst_celsius = sst_data
                
                sst_grid = sst_celsius.copy()
                print("Successfully retrieved Fcst SST data")
                
            except Exception as e:
                print(f"Error retrieving Fcst SST data: {str(e)}")
                return None
        
        return sst_grid

    def calculateWindShear(self, wind_upper, wind_lower):
        """Calculate wind shear magnitude between two levels"""
        mag_upper, dir_upper = wind_upper
        mag_lower, dir_lower = wind_lower
        
        # Convert to u,v components
        u_upper = -mag_upper * np.sin(np.radians(dir_upper))
        v_upper = -mag_upper * np.cos(np.radians(dir_upper))
        u_lower = -mag_lower * np.sin(np.radians(dir_lower))
        v_lower = -mag_lower * np.cos(np.radians(dir_lower))
        
        # Calculate shear vector
        du = u_upper - u_lower
        dv = v_upper - v_lower
        
        # Shear magnitude in m/s
        shear_magnitude = np.sqrt(du*du + dv*dv)
        
        return shear_magnitude

    def calculateBulkRichardsonNumber(self, temp_upper, temp_lower, wind_shear, height_diff=925.0):
        """Calculate Bulk Richardson Number"""
        g = 9.81  # gravity
        temp_avg = (temp_upper + temp_lower + 546.3) / 2.0  # Average temp in Kelvin
        
        # Temperature gradient (K/m)
        dT_dz = (temp_upper - temp_lower) / height_diff
        
        # Wind shear squared (1/s^2) - avoid division by zero
        wind_shear_sq = np.maximum(wind_shear**2, 0.01) / height_diff**2
        
        # Richardson Number
        Ri = (g / temp_avg) * dT_dz / wind_shear_sq
        
        return Ri

    def calculateWindMixingPotential(self, bulk_ri, wind_shear, instability_index, wind_speed=None, level="850"):
        """Calculate wind mixing potential for specified level"""
        # Richardson Number component (lower Ri = better mixing)
        ri_factor = np.where(bulk_ri < 0.25, 
                           2.0 - 4.0 * bulk_ri,
                           np.where(bulk_ri < 1.0,
                                  1.0 - 0.8 * (bulk_ri - 0.25) / 0.75,
                                  0.2 / (1.0 + bulk_ri - 1.0)))
        ri_factor = np.clip(ri_factor, 0.1, 2.0)
        
        # Wind shear component (higher shear = more mixing potential)
        shear_factor = np.minimum(wind_shear / 10.0, 2.0)
        shear_factor = np.maximum(shear_factor, 0.1)
        
        # Instability component
        instab_factor = np.where(instability_index > 0,
                               1.0 + instability_index / 10.0,
                               1.0 / (1.0 - instability_index / 20.0))
        instab_factor = np.clip(instab_factor, 0.3, 1.8)
        
        # Wind speed component - adjusted for level
        if wind_speed is not None:
            if level == "925":
                # 925mb is closer to surface, different scaling
                wind_factor = np.minimum(wind_speed / 12.0, 2.0)
            else:  # 850mb
                wind_factor = np.minimum(wind_speed / 15.0, 2.0)
            wind_factor = np.maximum(wind_factor, 0.2)
        else:
            wind_factor = 1.0
        
        # Combine all factors
        mixing_potential = ri_factor * shear_factor * instab_factor * wind_factor
        
        # Scale to 0-10 index - adjust for level
        if level == "925":
            # 925mb mixing typically more immediate/stronger
            mixing_index = mixing_potential * 2.2
        else:  # 850mb
            mixing_index = mixing_potential * 2.0
            
        mixing_index = np.clip(mixing_index, 0.0, 10.0)
        
        return mixing_index

    def calculateWindThresholdPotential(self, bulk_ri, wind_shear, instability_index, wind_speed, threshold_kts, level="850"):
        """Calculate potential for specific wind threshold to mix down"""
        if wind_speed is None:
            return None
        
        # Convert wind speed to knots 
        wind_speed_kts = wind_speed * 1.94  # m/s to knots
        
        # Base requirement: winds aloft must exceed threshold
        wind_factor = np.where(wind_speed_kts >= threshold_kts,
                             np.minimum((wind_speed_kts - threshold_kts) / 20.0 + 0.5, 2.0),
                             0.0)
        
        # Richardson Number mixing factor
        ri_factor = np.where(bulk_ri < 0.25, 
                           1.0,
                           np.where(bulk_ri < 1.0,
                                  1.0 - 0.8 * (bulk_ri - 0.25) / 0.75,
                                  0.2))
        ri_factor = np.clip(ri_factor, 0.1, 1.0)
        
        # Wind shear enhancement
        shear_factor = np.minimum(wind_shear / 15.0 + 0.5, 1.5)
        shear_factor = np.maximum(shear_factor, 0.3)
        
        # Instability modification
        instab_factor = np.where(instability_index > 0,
                               1.0 + instability_index / 15.0,
                               1.0 / (1.0 - instability_index / 25.0))
        instab_factor = np.clip(instab_factor, 0.4, 1.6)
        
        # Level-specific adjustments
        if level == "925":
            # 925mb winds mix more readily
            level_factor = 1.2
        else:  # 850mb
            level_factor = 1.0
        
        # Combine factors
        threshold_potential = wind_factor * ri_factor * shear_factor * instab_factor * level_factor
        
        # Scale to 0-10
        threshold_index = threshold_potential * 3.0
        threshold_index = np.clip(threshold_index, 0.0, 10.0)
        
        return threshold_index

    def calculateFogPotential(self, sst_grid, surface_temp, surface_rh=None, wind_speed=None, instability_index=None):
        """Calculate marine fog formation potential"""
        # Temperature difference component
        temp_diff = np.abs(sst_grid - surface_temp)
        temp_factor = np.exp(-temp_diff / 2.0)
        
        # Stability component
        if instability_index is not None:
            stability_factor = np.where(instability_index <= 0, 
                                      1.0 + np.abs(instability_index) / 10.0,
                                      1.0 / (1.0 + instability_index / 5.0))
            stability_factor = np.clip(stability_factor, 0.1, 2.0)
        else:
            stability_factor = 1.0
        
        # Wind component
        if wind_speed is not None:
            wind_factor = np.where(wind_speed <= 2.0,
                                 0.5 + 0.25 * wind_speed,
                                 np.where(wind_speed <= 7.0,
                                        1.0 - 0.1 * (wind_speed - 2.0),
                                        0.3 / (1.0 + 0.1 * (wind_speed - 7.0))))
            wind_factor = np.clip(wind_factor, 0.1, 1.0)
        else:
            wind_factor = 0.7
        
        # Humidity component
        if surface_rh is not None:
            rh_factor = np.where(surface_rh >= 85.0, 
                               1.0 + (surface_rh - 85.0) / 15.0,
                               surface_rh / 85.0)
            rh_factor = np.clip(rh_factor, 0.2, 1.5)
        else:
            rh_factor = 0.8
        
        # Combine all factors
        fog_potential = temp_factor * stability_factor * wind_factor * rh_factor
        
        # Scale to 0-10 index
        fog_index = fog_potential * 4.0
        fog_index = np.clip(fog_index, 0.0, 10.0)
        
        return fog_index

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method for marine wind mixing and fog analysis"""
        
        self.statusBarMsg("Starting enhanced marine wind mixing and fog analysis...", "R")
        
        # Show GUI if no varDict provided
        if varDict is None:
            self.statusBarMsg("Showing parameter selection GUI...", "R")
            varDict = self.showGUI(editArea, timeRange)
            if varDict is None:
                self.statusBarMsg("Analysis cancelled by user", "S")
                return
        
        # Get parameters from GUI
        atmModels = varDict["Atmospheric Models"]
        sstSource = varDict["SST Source"]
        modelRun = varDict["Model Run"]
        outputGrids = varDict["Output Grids"]
        
        self.statusBarMsg(f"Selected: {len(atmModels)} models, SST: {sstSource}, {len(outputGrids)} outputs", "R")
        
        if len(atmModels) == 0:
            self.statusBarMsg("ERROR: No atmospheric models selected", "S")
            return
        
        # Get forecast grid info for processing each time period
        self.statusBarMsg("Accessing forecast database...", "R")
        fcst = self.mutableID().modelIdentifier()
        print(f"Using forecast database: {fcst}")
        
        try:
            gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
            if not gridinfos:
                gridinfos = self.getGridInfo(fcst, "SST", "SFC", timeRange)
            if not gridinfos:
                self.statusBarMsg("ERROR: No forecast grids found for time range", "S")
                return
        except Exception as e:
            print(f"Error getting grid info: {str(e)}")
            self.statusBarMsg(f"ERROR: Failed to access forecast grids - {str(e)}", "S")
            return
        
        print(f"Processing {len(gridinfos)} time periods...")
        
        # Initialize variables
        periods_processed = 0
        
        # Process each forecast time period
        for i, gridinfo in enumerate(gridinfos):
            GridTimeRange = gridinfo.gridTime()
            
            self.statusBarMsg(f"Processing time period {i+1}/{len(gridinfos)}: {GridTimeRange}", "R")
            print(f"Processing time period {i+1}/{len(gridinfos)}")
            
            # Initialize accumulation variables  
            t850_accum = None
            t925_accum = None
            sst_grid = None
            wind_925_accum = None
            wind_850_accum = None
            surface_temp_grid = None
            surface_rh_grid = None
            model_count = 0
            
            # Get SST data from selected source
            sst_grid = self.getSST(sstSource, GridTimeRange)
            if sst_grid is None:
                print(f"Failed to retrieve SST data for time period {i+1}")
                continue
            
            # Process each atmospheric model using D2D approach
            for model in atmModels:
                self.statusBarMsg(f"Processing model {model}...", "R")
                print(f"Processing atmospheric model: {model}")
                
                # Set up atmospheric model database ID using D2D approach
                atmModelID = "D2D_" + model
                
                try:
                    if modelRun == "Current":
                        atmDataBase = self.findDatabase(atmModelID, 0)
                    else:
                        atmDataBase = self.findDatabase(atmModelID, -1)
                    
                    if atmDataBase is None:
                        print(f"Warning: Could not find D2D database for {model}")
                        continue
                    
                    atmDataBaseID = atmDataBase.modelIdentifier()
                    print(f"Found D2D database for {model}: {atmDataBaseID}")
                    
                    # Get first grid time range (critical pattern)
                    info = self.getGridInfo(atmDataBaseID, "t", "MB850", GridTimeRange)
                    if info:
                        firstGridTR = info[0].gridTime()
                    else:
                        firstGridTR = TimeRange.TimeRange(GridTimeRange.startTime(), GridTimeRange.startTime() + 1)
                    
                except Exception as e:
                    print(f"Error setting up database access for {model}: {str(e)}")
                    continue
                
                # Get 850 mb temperature
                try:
                    t850_grid = self.getGrids(atmDataBaseID, "t", "MB850", firstGridTR, noDataError=0)
                    if t850_grid is None:
                        print(f"ERROR: Failed to retrieve 850 mb temperature for {model}")
                        continue
                    
                    # Convert from Kelvin to Celsius
                    t850_celsius = t850_grid - 273.15
                    print(f"Retrieved 850 mb temperature for {model}")
                    
                except Exception as e:
                    print(f"Error retrieving 850 mb temperature for {model}: {str(e)}")
                    continue

                # Get 925 mb temperature (NEW)
                try:
                    t925_grid = self.getGrids(atmDataBaseID, "t", "MB925", firstGridTR, noDataError=0)
                    if t925_grid is not None:
                        t925_celsius = t925_grid - 273.15
                        print(f"Retrieved 925 mb temperature for {model}")
                    else:
                        t925_celsius = None
                        print(f"925 mb temperature not available for {model}")
                except Exception as e:
                    print(f"Could not retrieve 925 mb temperature for {model}: {str(e)}")
                    t925_celsius = None

                # Get 925 mb winds
                try:
                    wind_925 = self.getGrids(atmDataBaseID, "wind", "MB925", firstGridTR, noDataError=0)
                    if wind_925 is not None:
                        print(f"Retrieved 925 mb winds for {model}")
                    else:
                        wind_925 = None
                except Exception as e:
                    print(f"Could not retrieve 925 mb winds for {model}: {str(e)}")
                    wind_925 = None

                # Get 850 mb winds
                try:
                    wind_850 = self.getGrids(atmDataBaseID, "wind", "MB850", firstGridTR, noDataError=0)
                    if wind_850 is not None:
                        print(f"Retrieved 850 mb winds for {model}")
                    else:
                        wind_850 = None
                except Exception as e:
                    print(f"Could not retrieve 850 mb winds for {model}: {str(e)}")
                    wind_850 = None

                # Get surface temperature for fog calculations
                if surface_temp_grid is None:
                    try:
                        surf_temp = self.getGrids(atmDataBaseID, "t", "SFC", firstGridTR, noDataError=0)
                        if surf_temp is not None:
                            if np.max(surf_temp) > 200:  # Kelvin
                                surface_temp_grid = surf_temp - 273.15
                            else:
                                surface_temp_grid = surf_temp
                            print("Retrieved surface temperature")
                    except Exception as e:
                        print(f"Could not retrieve surface temperature: {str(e)}")
                
                # Get surface relative humidity
                if surface_rh_grid is None:
                    try:
                        surf_rh = self.getGrids(atmDataBaseID, "rh", "SFC", firstGridTR, noDataError=0)
                        if surf_rh is not None:
                            surface_rh_grid = surf_rh
                            print("Retrieved surface relative humidity")
                    except Exception as e:
                        print(f"Could not retrieve surface RH: {str(e)}")
                
                # Accumulate data
                if t850_accum is None:
                    t850_accum = t850_celsius.copy()
                else:
                    t850_accum += t850_celsius
                
                if t925_celsius is not None:
                    if t925_accum is None:
                        t925_accum = t925_celsius.copy()
                    else:
                        t925_accum += t925_celsius
                
                if wind_925 is not None:
                    if wind_925_accum is None:
                        wind_925_accum = wind_925
                    else:
                        wind_925_accum = ((wind_925_accum[0] + wind_925[0]) / 2.0, 
                                        (wind_925_accum[1] + wind_925[1]) / 2.0)
                
                if wind_850 is not None:
                    if wind_850_accum is None:
                        wind_850_accum = wind_850
                    else:
                        wind_850_accum = ((wind_850_accum[0] + wind_850[0]) / 2.0,
                                        (wind_850_accum[1] + wind_850[1]) / 2.0)
                
                model_count += 1
                print(f"Successfully processed model {model}")
            
            # Check if we got valid data
            if model_count == 0 or sst_grid is None:
                print(f"No valid data for time period {i+1}")
                continue
            
            # Calculate averages
            if model_count > 1:
                t850_avg = t850_accum / model_count
                if t925_accum is not None:
                    t925_avg = t925_accum / model_count
                else:
                    t925_avg = None
                print(f"Averaged {model_count} atmospheric models")
            else:
                t850_avg = t850_accum
                t925_avg = t925_accum
            
            # Calculate instability indices
            instability_850 = sst_grid - t850_avg
            instability_850 = np.clip(instability_850, -20.0, 20.0)
            
            instability_925 = None
            if t925_avg is not None:
                instability_925 = sst_grid - t925_avg
                instability_925 = np.clip(instability_925, -20.0, 20.0)
            
            # Calculate wind mixing and other indices
            additional_grids = {}
            
            # Wind mixing calculations
            if wind_925_accum is not None and wind_850_accum is not None:
                # Calculate wind shear
                wind_shear = self.calculateWindShear(wind_850_accum, wind_925_accum)
                
                # Calculate Bulk Richardson Number using 850mb temp
                temp_925_approx = surface_temp_grid + 2.0 if surface_temp_grid is not None else t850_avg + 2.0
                bulk_ri = self.calculateBulkRichardsonNumber(t850_avg, temp_925_approx, wind_shear)
                
                # 850mb-based wind mixing potentials
                if any(grid.endswith("850") for grid in outputGrids):
                    wind_850_speed = wind_850_accum[0] if wind_850_accum is not None else None
                    
                    if "WindMixingPotential850" in outputGrids:
                        wind_mixing_850 = self.calculateWindMixingPotential(bulk_ri, wind_shear, instability_850, wind_850_speed, "850")
                        additional_grids["WindMixingPotential850"] = wind_mixing_850
                    
                    # 850mb threshold potentials
                    if wind_850_speed is not None:
                        if "Wind35ktPotential850" in outputGrids:
                            wind_35kt_850 = self.calculateWindThresholdPotential(bulk_ri, wind_shear, instability_850, wind_850_speed, 35.0, "850")
                            additional_grids["Wind35ktPotential850"] = wind_35kt_850
                        
                        if "Wind50ktPotential850" in outputGrids:
                            wind_50kt_850 = self.calculateWindThresholdPotential(bulk_ri, wind_shear, instability_850, wind_850_speed, 50.0, "850")
                            additional_grids["Wind50ktPotential850"] = wind_50kt_850
                        
                        if "Wind65ktPotential850" in outputGrids:
                            wind_65kt_850 = self.calculateWindThresholdPotential(bulk_ri, wind_shear, instability_850, wind_850_speed, 65.0, "850")
                            additional_grids["Wind65ktPotential850"] = wind_65kt_850
                
                # 925mb-based wind mixing potentials (NEW)
                if any(grid.endswith("925") for grid in outputGrids) and instability_925 is not None:
                    wind_925_speed = wind_925_accum[0] if wind_925_accum is not None else None
                    
                    if "WindMixingPotential925" in outputGrids:
                        wind_mixing_925 = self.calculateWindMixingPotential(bulk_ri, wind_shear, instability_925, wind_925_speed, "925")
                        additional_grids["WindMixingPotential925"] = wind_mixing_925
                    
                    # 925mb threshold potentials
                    if wind_925_speed is not None:
                        if "Wind35ktPotential925" in outputGrids:
                            wind_35kt_925 = self.calculateWindThresholdPotential(bulk_ri, wind_shear, instability_925, wind_925_speed, 35.0, "925")
                            additional_grids["Wind35ktPotential925"] = wind_35kt_925
                        
                        if "Wind50ktPotential925" in outputGrids:
                            wind_50kt_925 = self.calculateWindThresholdPotential(bulk_ri, wind_shear, instability_925, wind_925_speed, 50.0, "925")
                            additional_grids["Wind50ktPotential925"] = wind_50kt_925
                        
                        if "Wind65ktPotential925" in outputGrids:
                            wind_65kt_925 = self.calculateWindThresholdPotential(bulk_ri, wind_shear, instability_925, wind_925_speed, 65.0, "925")
                            additional_grids["Wind65ktPotential925"] = wind_65kt_925
                
                # Optional intermediate grids
                if "BulkRichardson" in outputGrids:
                    additional_grids["BulkRichardson"] = np.clip(bulk_ri, -5.0, 5.0)
                
                if "WindShear" in outputGrids:
                    additional_grids["WindShear"] = np.clip(wind_shear, 0.0, 30.0)
                
                print(f"Calculated wind mixing potentials")
            else:
                print("Wind mixing potential not calculated - missing wind data")
            
            # Fog potential calculation (can use either instability index)
            if "FogPotential" in outputGrids:
                temp_for_fog = surface_temp_grid if surface_temp_grid is not None else sst_grid
                
                # Use 925mb instability if available, otherwise 850mb
                fog_instability = instability_925 if instability_925 is not None else instability_850
                
                # Get surface wind for fog calculation
                surface_wind_speed = None
                try:
                    surface_wind = self.getGrids(fcst, "Wind", "SFC", GridTimeRange, noDataError=0)
                    if surface_wind is not None:
                        surface_wind_speed = surface_wind[0] * 0.514  # Convert to m/s
                except:
                    pass
                
                fog_potential = self.calculateFogPotential(
                    sst_grid, temp_for_fog, surface_rh_grid, surface_wind_speed, fog_instability
                )
                additional_grids["FogPotential"] = fog_potential
                print(f"Calculated fog potential")
            
            # Create output grids
            grids_created = 0
            
            try:
                # 850mb instability grid
                if "SSTInstability850" in outputGrids:
                    self.createGrid(
                        "Fcst",
                        "SSTInstability850",
                        "SCALAR",
                        instability_850,
                        GridTimeRange,
                        precision=1,
                        minAllowedValue=-20.0,
                        maxAllowedValue=20.0,
                        units="C",
                        descriptiveName="SST-T850 Instability Index"
                    )
                    grids_created += 1
                    print(f"Created SSTInstability850 grid")
                
                # 925mb instability grid (NEW)
                if "SSTInstability925" in outputGrids and instability_925 is not None:
                    self.createGrid(
                        "Fcst",
                        "SSTInstability925",
                        "SCALAR",
                        instability_925,
                        GridTimeRange,
                        precision=1,
                        minAllowedValue=-20.0,
                        maxAllowedValue=20.0,
                        units="C",
                        descriptiveName="SST-T925 Instability Index"
                    )
                    grids_created += 1
                    print(f"Created SSTInstability925 grid")
                
                # Additional grids
                for grid_name, grid_data in additional_grids.items():
                    # Set default values
                    desc = grid_name
                    units = "index"
                    min_val, max_val = 0.0, 10.0
                    precision = 1
                    
                    # Override with specific values
                    if grid_name == "WindMixingPotential850":
                        desc = "Wind Mixing Potential (850mb-based)"
                    elif grid_name == "WindMixingPotential925":
                        desc = "Wind Mixing Potential (925mb-based)"
                    elif "Wind35ktPotential" in grid_name:
                        level = grid_name[-3:]
                        desc = f"Potential for Winds >35 Knots ({level}mb)"
                    elif "Wind50ktPotential" in grid_name:
                        level = grid_name[-3:]
                        desc = f"Potential for Winds >50 Knots ({level}mb)"
                    elif "Wind65ktPotential" in grid_name:
                        level = grid_name[-3:]
                        desc = f"Potential for Winds >65 Knots ({level}mb)"
                    elif grid_name == "FogPotential":
                        desc = "Marine Fog Formation Potential"
                    elif grid_name == "BulkRichardson":
                        desc = "Bulk Richardson Number"
                        units = "ratio"
                        min_val, max_val = -5.0, 5.0
                        precision = 2
                    elif grid_name == "WindShear":
                        desc = "850-925mb Wind Shear Magnitude"
                        units = "m/s"
                        min_val, max_val = 0.0, 30.0
                    
                    self.createGrid(
                        "Fcst",
                        grid_name,
                        "SCALAR",
                        grid_data,
                        GridTimeRange,
                        precision=precision,
                        minAllowedValue=min_val,
                        maxAllowedValue=max_val,
                        units=units,
                        descriptiveName=desc
                    )
                    grids_created += 1
                    print(f"Created {grid_name} grid")
                
                # SST reference grid
                if "SSTGrid" in outputGrids:
                    self.createGrid(
                        "Fcst",
                        "SSTGrid",
                        "SCALAR",
                        sst_grid,
                        GridTimeRange,
                        precision=1,
                        minAllowedValue=-5.0,
                        maxAllowedValue=35.0,
                        units="C",
                        descriptiveName=f"Sea Surface Temperature ({sstSource})"
                    )
                    grids_created += 1
                    print(f"Created SST reference grid from {sstSource}")
                
                periods_processed += 1
                
                # Display statistics
                inst_850_mean = float(np.mean(instability_850))
                stats_text = f"850mb: {inst_850_mean:.1f}°C"
                
                if instability_925 is not None:
                    inst_925_mean = float(np.mean(instability_925))
                    stats_text += f" | 925mb: {inst_925_mean:.1f}°C"
                
                # Calculate statistics for wind thresholds
                wind_stats = []
                for threshold in [35, 50, 65]:
                    for level in ["850", "925"]:
                        grid_name = f"Wind{threshold}ktPotential{level}"
                        if grid_name in additional_grids:
                            thresh_grid = additional_grids[grid_name]
                            thresh_mean = float(np.mean(thresh_grid))
                            wind_stats.append(f"{threshold}kt-{level}:{thresh_mean:.1f}")
                
                wind_stats_text = f" | {', '.join(wind_stats)}" if wind_stats else ""
                
                # Fog statistics
                fog_stats_text = ""
                if "FogPotential" in additional_grids:
                    fog_grid = additional_grids["FogPotential"]
                    fog_mean = float(np.mean(fog_grid))
                    fog_stats_text = f" | Fog: {fog_mean:.1f}"
                
                print(f"Time Period {i+1} - Enhanced Marine Wind/Fog Analysis:")
                print(f"  SST Source: {sstSource}")
                print(f"  Instability: {stats_text}")
                if wind_stats_text:
                    print(f"  Wind Thresholds: {wind_stats_text.strip(' |')}")
                if fog_stats_text:
                    print(f"  Fog Potential: {fog_stats_text.strip(' |')}")
                
                status_msg = f"Period {i+1}: {grids_created} grids | {stats_text}{wind_stats_text}{fog_stats_text}"
                self.statusBarMsg(status_msg, "R")
                
            except Exception as e:
                print(f"Error creating grids for time period {i+1}: {str(e)}")
                continue
        
        # Final status message
        if periods_processed == 0:
            self.statusBarMsg("ERROR: No time periods processed successfully", "S")
        else:
            final_msg = f"SUCCESS: Enhanced marine analysis completed - {periods_processed} periods, SST: {sstSource}"
            self.statusBarMsg(final_msg, "R")
            print(f"Enhanced marine wind/fog analysis completed successfully - {periods_processed} periods processed")
        
        return None