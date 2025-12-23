# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# Wind_and_gusts.py - Custom Tkinter GUI Version
#
# Author: jason.krekeler
# ----------------------------------------------------------------------------

MenuItems = ["Edit"]
import LogStream, time
WeatherElementEdited = "variableElement"
from numpy import *
import math
import JUtil
import tkinter as tk
HideTool = 0

ScreenList = ["Wind","WindGust","WaveHeight"]

# Empty VariableList since we're using custom GUI
VariableList = []

import time
import AbsTime
import SmartScript

class WindBlendGUI:
    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Wind and Gust Blend Tool")
        self.master.geometry("500x700")
        self.master.resizable(False, False)
        
        # Variables
        self.gustMultiplier = tk.DoubleVar()
        self.gustMultiplier.set(1.2)
        
        self.createWaves = tk.StringVar()
        self.createWaves.set("Yes")
        
        self.createDiffGrids = tk.StringVar()
        self.createDiffGrids.set("No")
        
        self.applySmoothing = tk.StringVar()
        self.applySmoothing.set("No")
        
        self.smoothingPasses = tk.IntVar()
        self.smoothingPasses.set(1)
        
        self.blendInEditArea = tk.StringVar()
        self.blendInEditArea.set("No")
        
        self.createConfidence = tk.StringVar()
        self.createConfidence.set("No")
        
        self.createWidgets()
        
    def updateWeights(self, *args):
        """Update weight labels and total"""
        total = 0
        
        # Calculate total from all sliders (0-5 range)
        for modelId, var in self.modelWeights.items():
            weight = var.get()
            total += weight
        
        # Convert to percentages
        if total > 0:
            for modelId, var in self.modelWeights.items():
                weight = var.get()
                percentage = int((weight / float(total)) * 100)
                self.modelLabels[modelId].config(text="%d%%" % percentage)
        else:
            for modelId in self.modelWeights.keys():
                self.modelLabels[modelId].config(text="0%")
        
        # Update message based on total (only if messageLabel exists)
        if hasattr(self, 'messageLabel'):
            if total == 0:
                self.totalLabel.config(text="No Models Selected", fg="red")
                self.messageLabel.config(text="ERROR: Move at least one slider above 0", fg="red")
            else:
                self.totalLabel.config(text="Models Selected", fg="green")
                self.messageLabel.config(text="", fg="black")
        else:
            # During initialization, just update the total label
            if hasattr(self, 'totalLabel'):
                if total > 0:
                    self.totalLabel.config(text="Models Selected", fg="green")
                else:
                    self.totalLabel.config(text="No Models Selected", fg="red")

    def createWidgets(self):
        # Main frame
        mainFrame = tk.Frame(self.master, padx=10, pady=10)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Wind and Gust Blend Tool", 
                             font=("Arial", 14, "bold"))
        titleLabel.pack(pady=(0, 15))
        
        # Model Blend Weights Frame - Only sliders, no radio buttons
        modelFrame = tk.LabelFrame(mainFrame, text="Model Blend Weights", padx=10, pady=10)
        modelFrame.pack(fill=tk.X, pady=(0, 10))
        
        # Define models for sliders
        models = [
            ("GFS", "GFS"),
            ("ECMWF", "nECMWF0p25"),
            ("Forecast", "Fcst")
        ]
        
        # Custom weights - create sliders only (0-5 range)
        self.modelWeights = {}
        self.modelLabels = {}
        
        for displayName, modelId in models:
            var = tk.IntVar()
            var.set(0)
            self.modelWeights[modelId] = var
            
            frame = tk.Frame(modelFrame)
            frame.pack(fill=tk.X, pady=3)
            tk.Label(frame, text=displayName + ":", width=12, anchor=tk.W).pack(side=tk.LEFT)
            tk.Scale(frame, from_=0, to=5, orient=tk.HORIZONTAL, 
                    variable=var, command=self.updateWeights, width=15).pack(side=tk.LEFT, fill=tk.X, expand=True)
            label = tk.Label(frame, text="0%", width=6)
            label.pack(side=tk.RIGHT)
            self.modelLabels[modelId] = label
        
        # Status label
        self.totalLabel = tk.Label(modelFrame, text="No Models Selected", 
                                  font=("Arial", 10, "bold"), fg="red")
        self.totalLabel.pack(pady=(5, 0))
        
        # Error/Warning label
        self.messageLabel = tk.Label(modelFrame, text="", 
                                  font=("Arial", 9), fg="red")
        self.messageLabel.pack()
        
        # Info label
        infoLabel = tk.Label(modelFrame, text="Move sliders right to include models in blend", 
                           font=("Arial", 9), fg="gray")
        infoLabel.pack()
        
        # Gust Options Frame
        gustFrame = tk.LabelFrame(mainFrame, text="Wind Gust Options", padx=10, pady=10)
        gustFrame.pack(fill=tk.X, pady=(0, 10))
        
        gustMultFrame = tk.Frame(gustFrame)
        gustMultFrame.pack(fill=tk.X)
        tk.Label(gustMultFrame, text="Gust Multiplier:").pack(side=tk.LEFT)
        gustSpinbox = tk.Spinbox(gustMultFrame, from_=1.0, to=2.5, increment=0.1, 
                                width=10, textvariable=self.gustMultiplier)
        gustSpinbox.pack(side=tk.LEFT, padx=(10, 0))
        
        # Wave Options Frame
        waveFrame = tk.LabelFrame(mainFrame, text="Wave Options", padx=10, pady=10)
        waveFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Checkbutton(waveFrame, text="Create Wave Height grids with same blend", 
                      variable=self.createWaves, onvalue="Yes", offvalue="No").pack(anchor=tk.W)
        
        # Advanced Options Frame
        advFrame = tk.LabelFrame(mainFrame, text="Advanced Options", padx=10, pady=10)
        advFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Checkbutton(advFrame, text="Create difference grids to show changes", 
                      variable=self.createDiffGrids, onvalue="Yes", offvalue="No").pack(anchor=tk.W)
        
        tk.Checkbutton(advFrame, text="Apply smoothing to output grids", 
                      variable=self.applySmoothing, onvalue="Yes", offvalue="No").pack(anchor=tk.W)
        
        smoothFrame = tk.Frame(advFrame)
        smoothFrame.pack(fill=tk.X, pady=(5, 0))
        tk.Label(smoothFrame, text="Smoothing passes:").pack(side=tk.LEFT)
        tk.Scale(smoothFrame, from_=1, to=5, orient=tk.HORIZONTAL, 
                variable=self.smoothingPasses, width=15).pack(side=tk.LEFT, padx=(10, 0))
        
        tk.Checkbutton(advFrame, text="Blend only in active edit area", 
                      variable=self.blendInEditArea, onvalue="Yes", offvalue="No").pack(anchor=tk.W)
        
        #tk.Checkbutton(advFrame, text="Create model confidence grid", 
                      #variable=self.createConfidence, onvalue="Yes", offvalue="No").pack(anchor=tk.W)
        
        # Buttons Frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(15, 0))
        
        tk.Button(buttonFrame, text="Run Tool", command=self.runTool, 
                 bg="lightgreen", width=15).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(buttonFrame, text="Cancel", command=self.cancel, 
                 width=15).pack(side=tk.LEFT)
        
        # Update initial state
        self.updateWeights()
    
    def getValues(self):
        """Return dictionary of all parameter values"""
        values = {
            "Gust Multiplier": self.gustMultiplier.get(),
            "Create Wave grids with same model blend?": self.createWaves.get(),
            "Create difference grids to show changes?": self.createDiffGrids.get(),
            "Apply smoothing to output grids?": self.applySmoothing.get(),
            "Smoothing passes": self.smoothingPasses.get(),
            "Blend only in edit area?": self.blendInEditArea.get(),
            "Create confidence grid?": self.createConfidence.get()
        }
        
        # Add all model weights (convert from 0-5 to percentages)
        total = sum(var.get() for var in self.modelWeights.values())
        if total > 0:
            for modelId, var in self.modelWeights.items():
                weight = var.get()
                percentage = int((weight / float(total)) * 100)
                values[modelId + " Weight"] = percentage
        else:
            for modelId in self.modelWeights.keys():
                values[modelId + " Weight"] = 0
        
        return values
    
    def runTool(self):
        """Validate inputs and run the tool"""
        total = sum(var.get() for var in self.modelWeights.values())
        if total == 0:
            # Just flash the error message briefly
            self.messageLabel.config(text="ERROR: Move at least one slider above 0!", fg="red")
            self.master.after(3000, lambda: self.messageLabel.config(text=""))
            return
        
        self.callback(self.getValues())
        self.master.destroy()
    
    def cancel(self):
        """Close without running"""
        self.master.destroy()

class Procedure (SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        
    def getModelID(self, userModel):
        """Return the actual model ID for given user selection"""
        modelMap = {
            "GFS": "GFS",
            "nECMWF0p25": "nECMWF0p25",
            "Fcst": "Fcst"
        }
        return modelMap.get(userModel, userModel)
        
    def getWaveID(self, userModel):
        """Return the wave model ID for given model"""
        waveMap = {
            "GFS": "GFSwaveNH",
            "nECMWF0p25": "nECMWF0p25wave",
            "Fcst": "Fcst"
        }
        return waveMap.get(userModel, None)
    
    def getAvailableModelRuns(self, modelName, maxRuns=3):
        """Get available model runs, starting with current (0) and going back in time"""
        availableRuns = []
        for run in range(maxRuns):
            db = self.findDatabase(modelName, -run if run > 0 else 0)
            if db is not None:
                availableRuns.append((-run if run > 0 else 0, db.modelIdentifier()))
        return availableRuns
    
    def getModelGridWithFallback(self, modelName, elementName, level, timeRange, maxRuns=3):
        """Get model grid with fallback to previous runs if current run doesn't have data"""
        if modelName == "Fcst":
            return self.getGrids(modelName, elementName, level, timeRange, mode="First", noDataError=0)
        
        availableRuns = self.getAvailableModelRuns(modelName, maxRuns)
        
        for runOffset, modelId in availableRuns:
            grid = self.getGrids(modelId, elementName, level, timeRange, mode="First", noDataError=0)
            if grid is not None:
                if runOffset < 0:
                    self.statusBarMsg("Using %s %s from %d cycles ago" % (modelName, elementName, abs(runOffset)), "S")
                return grid
        
        return None
    
    def calculateCustomWeights(self, varDict, modelSources):
        """Calculate weights based on user input - always use custom weights from sliders"""
        weights = []
        totalWeight = 0
        
        for model in modelSources:
            # Check for model weight in varDict
            weightKey = model + " Weight"
            weight = varDict.get(weightKey, 0) / 100.0
            
            weights.append(weight)
            totalWeight += weight
        
        if totalWeight > 0:
            weights = [w / totalWeight for w in weights]
        else:
            weights = [1.0 / len(modelSources)] * len(modelSources)
        
        return weights
    
    def createConfidenceGrid(self, modelData, timeRange):
        """Create a confidence grid based on model agreement"""
        if len(modelData) < 2:
            return None
        
        # Stack the wind speed grids
        modelArray = array(modelData)
        
        # Calculate standard deviation across models (axis=0 for grid points)
        stdDev = std(modelArray, axis=0)
        
        # Convert to confidence: lower std dev = higher confidence
        # Normalize by maximum std dev to get 0-100 scale
        maxStd = max(stdDev.flat)
        if maxStd > 0:
            confidence = 100.0 * (1.0 - (stdDev / maxStd))
        else:
            # Perfect agreement
            confidence = self.newGrid(100.0)
        
        # Ensure confidence is between 0 and 100
        confidence = clip(confidence, 0.0, 100.0)
        
        try:
            self.createGrid("Fcst", "WindConfidence", "SCALAR", confidence, timeRange)
            self.statusBarMsg("Created confidence grid for " + str(timeRange), "S")
            return confidence
        except:
            self.statusBarMsg("Failed to create confidence grid", "A")
            return None

    def showGUI(self, editArea, timeRange):
        """Show the custom GUI and get parameters"""
        self.editArea = editArea
        self.timeRange = timeRange
        self.varDict = None
        
        root = tk.Tk()
        gui = WindBlendGUI(root, self.guiCallback)
        root.mainloop()
        
        return self.varDict
    
    def guiCallback(self, values):
        """Callback from GUI"""
        self.varDict = values

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method"""
        
        # Show GUI if no varDict provided
        if varDict is None:
            varDict = self.showGUI(editArea, timeRange)
            if varDict is None:
                return  # User cancelled
        
        # Get Parameters
        gustMultiplier = varDict["Gust Multiplier"]
        createWaves = varDict["Create Wave grids with same model blend?"]
        createDiffGrids = varDict["Create difference grids to show changes?"]
        applySmoothing = varDict["Apply smoothing to output grids?"]
        smoothingPasses = varDict["Smoothing passes"]
        blendInEditArea = varDict["Blend only in edit area?"]
        createConfidence = varDict["Create confidence grid?"]
        windLevel = "SFC"
        modelSources = []
        waveSources = []
        
        # Add models based on non-zero weights from sliders
        for modelId, weight in [("GFS", varDict.get("GFS Weight", 0)),
                              ("nECMWF0p25", varDict.get("nECMWF0p25 Weight", 0)),
                              ("Fcst", varDict.get("Fcst Weight", 0))]:
            if weight > 0:
                modelSources.append(modelId)
            
        modelWeights = self.calculateCustomWeights(varDict, modelSources)
        
        # Build wave sources list - derive from wind models using getWaveID()
        if createWaves == "Yes":
            for model in modelSources:
                waveID = self.getWaveID(model)
                if waveID is not None and waveID not in waveSources:
                    waveSources.append(waveID)
        
        # Get list of grids for Wind within the selected time range
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", windLevel, timeRange)
        
        # Loop through each grid time in the time range
        for gridinfo in gridinfos:
            GridTimeRange = gridinfo.gridTime()
            
            # Get old grids for difference calculation if requested (from Official)
            oldWindGrid = None
            if createDiffGrids == "Yes":
                oldWindGrid = self.getGrids("Official", "Wind", windLevel, GridTimeRange, mode="First", noDataError=0)
            
            # Initialize blend variables for this time period
            usum = self.empty()
            vsum = self.empty()
            totweight = 0
            modelWindSpeeds = []
            
            # Loop through models and build blend for this time period
            for i, model in enumerate(modelSources):
                
                # Get wind data with fallback to previous runs
                modelWind = self.getModelGridWithFallback(model, "Wind", windLevel, GridTimeRange)
                
                if modelWind is not None:
            
                    # Use custom weights from sliders
                    weight = modelWeights[i]
        
                    # Blend Wind Grids
                    (mag, dir) = modelWind
                    (u, v) = self.MagDirToUV(mag, dir)
                    
                    usum += (u * weight)
                    vsum += (v * weight)
                    totweight += weight
                    
                    # Store for confidence calculation
                    if createConfidence == "Yes":
                        modelWindSpeeds.append(mag)

            # Calculate final blend for this time period
            if totweight > 0:
                blendedU = usum / totweight
                blendedV = vsum / totweight
                
                blendedWind = self.UVToMagDir(blendedU, blendedV)
                (blendedMag, blendedDir) = blendedWind
                
                # Create wind gust grid
                windGust = blendedMag * gustMultiplier
                
                # Handle edit area blending
                if blendInEditArea == "Yes":
                    editArea = self.getActiveEditArea()
                    if not editArea.isEmpty():
                        # Get original grids
                        origWind = self.getGrids("Fcst", "Wind", windLevel, GridTimeRange, mode="First", noDataError=0)
                        origGust = self.getGrids("Fcst", "WindGust", windLevel, GridTimeRange, mode="First", noDataError=0)
                        
                        if origWind is not None:
                            # Blend only in edit area
                            editMask = editArea.getGrid().getNDArray()
                            (origMag, origDir) = origWind
                            (origU, origV) = self.MagDirToUV(origMag, origDir)
                            
                            # Apply blend only where edit area is active
                            finalU = where(editMask, blendedU, origU)
                            finalV = where(editMask, blendedV, origV)
                            blendedWind = self.UVToMagDir(finalU, finalV)
                            
                            if origGust is not None:
                                windGust = where(editMask, windGust, origGust)
                
                # Apply smoothing if requested - use proper AWIPS2/GFE smoothing
                if applySmoothing == "Yes":
                    # First save the grids, then apply smoothing
                    self.createGrid("Fcst", "Wind", "VECTOR", blendedWind, GridTimeRange)
                    self.createGrid("Fcst", "WindGust", "SCALAR", windGust, GridTimeRange)
                    
                    # Get the proper edit area for smoothing
                    if blendInEditArea == "Yes":
                        smoothEditArea = self.getActiveEditArea()
                    else:
                        smoothEditArea = None  # This will use the entire domain
                    
                    # Apply smoothing using the proper AWIPS2 method
                    try:
                        # Get the parameter objects
                        windParm = self.getParmByExpr("Wind")
                        gustParm = self.getParmByExpr("WindGust")
                        time = GridTimeRange.startTime().javaDate()
                        
                        # Apply smoothing for the specified number of passes
                        for _ in range(smoothingPasses):
                            if windParm is not None:
                                windParm.smooth(time, smoothEditArea, 1)
                            if gustParm is not None:
                                gustParm.smooth(time, smoothEditArea, 1)
                                
                        self.statusBarMsg("Applied %d smoothing passes" % smoothingPasses, "S")
                        
                    except Exception as e:
                        self.statusBarMsg("Smoothing failed: %s" % str(e), "A")
                        
                else:
                    # No smoothing - just save the grids normally
                    self.createGrid("Fcst", "Wind", "VECTOR", blendedWind, GridTimeRange)
                    self.createGrid("Fcst", "WindGust", "SCALAR", windGust, GridTimeRange)
                
                # Create confidence grid if requested
                if createConfidence == "Yes" and len(modelWindSpeeds) > 1:
                    self.createConfidenceGrid(modelWindSpeeds, GridTimeRange)

                # Create difference grids if requested (only wind speed, no gust)
                if createDiffGrids == "Yes":
                    if oldWindGrid is not None:
                        # Get the current wind grid (potentially smoothed)
                        currentWind = self.getGrids("Fcst", "Wind", windLevel, GridTimeRange, mode="First", noDataError=0)
                        if currentWind is not None:
                            # Calculate wind speed difference (new - old)
                            (oldMag, oldDir) = oldWindGrid
                            (newMag, newDir) = currentWind
                            windSpeedDiff = newMag - oldMag
                            self.createGrid("Fcst", "WindSpeedDiff", "SCALAR", windSpeedDiff, GridTimeRange)
                            self.setActiveElement("Fcst", "WindSpeedDiff", "SFC", timeRange,
                                            "USER/jason.krekeler/Grid/gridded data", 
                                            (-20.0, 20.0), 0)
            
            # Process waves for this time period if requested
            if createWaves == "Yes" and len(waveSources) > 0:
                
                # Get old wave grid for difference calculation if requested
                oldWaveGrid = None
                if createDiffGrids == "Yes":
                    oldWaveGrid = self.getGrids("Fcst", "WaveHeight", windLevel, GridTimeRange, mode="First", noDataError=0)
                
                totalMag = self.empty()
                wavetotweight = 0
                
                for i, wave in enumerate(waveSources):
                    
                    # Get wave data with fallback to previous runs
                    modelWave = self.getModelGridWithFallback(wave, "WaveHeight", windLevel, GridTimeRange)
                    
                    if modelWave is not None:
                
                        # Use same weights as wind models (match by index if possible)
                        if i < len(modelWeights):
                            weight = modelWeights[i]
                        else:
                            weight = 1.0 / len(waveSources)
                        
                        totalMag += (modelWave * weight)
                        wavetotweight += weight
                        
                # Create final wave grid for this time period
                if wavetotweight > 0:
                    waveMag = totalMag / wavetotweight
                    
                    # Handle edit area blending for waves
                    if blendInEditArea == "Yes":
                        editArea = self.getActiveEditArea()
                        if not editArea.isEmpty():
                            origWave = self.getGrids("Fcst", "WaveHeight", windLevel, GridTimeRange, mode="First", noDataError=0)
                            if origWave is not None:
                                editMask = editArea.getGrid().getNDArray()
                                waveMag = where(editMask, waveMag, origWave)
                    
                    # Create the wave grid first
                    self.createGrid("Fcst", "WaveHeight", "SCALAR", waveMag, GridTimeRange)
                    
                    # Apply smoothing if requested
                    if applySmoothing == "Yes":
                        if blendInEditArea == "Yes":
                            smoothEditArea = self.getActiveEditArea()
                        else:
                            smoothEditArea = None
                            
                        try:
                            waveParm = self.getParmByExpr("WaveHeight")
                            time = GridTimeRange.startTime().javaDate()
                            if waveParm is not None:
                                for _ in range(smoothingPasses):
                                    waveParm.smooth(time, smoothEditArea, 1)
                        except Exception as e:
                            self.statusBarMsg("Wave smoothing failed: %s" % str(e), "A")
                    
                    # Create wave difference grid if requested
                    if createDiffGrids == "Yes" and oldWaveGrid is not None:
                        # Get the current wave grid (potentially smoothed)
                        smoothedWave = self.getGrids("Fcst", "WaveHeight", windLevel, GridTimeRange, mode="First", noDataError=0)
                        if smoothedWave is not None:
                            waveDiff = smoothedWave - oldWaveGrid
                            self.createGrid("Fcst", "WaveHeightDiff", "SCALAR", waveDiff, GridTimeRange)
        
        self.statusBarMsg("Wind and Gust blend completed successfully!", "S")
        return None