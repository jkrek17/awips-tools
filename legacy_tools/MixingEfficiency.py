##
# This software was developed and / or modified by Raytheon Company,
# pursuant to Contract DG133W-05-CQ-1067 with the US Government.
# 
# U.S. EXPORT CONTROLLED TECHNICAL DATA
# This software product contains export-restricted data whose
# export/transfer/disclosure is restricted by U.S. law. Dissemination
# to non-U.S. persons whether in the United States or abroad requires
# an export license or other authorization.
# 
# Contractor Name:        Raytheon Company
# Contractor Address:     6825 Pine Street, Suite 340
#                         Mail Stop B8
#                         Omaha, NE 68106
#                         402.291.0100
# 
# See the AWIPS II Master Rights File ("Master Rights File.pdf") for
# further licensing information.
##

# ----------------------------------------------------------------------------
# Marine30mWindAdjustment - COMPREHENSIVE VERSION
#
# Helps forecasters enhance winds during cold air advection over Gulf Stream
# and identify low-level jets in stable conditions.
#
# Smart Hybrid Method:
# - UNSTABLE: Apply strong mixing enhancement (Gulf Stream CAA scenarios)
# - NEUTRAL: Take maximum of mixed or model wind
# - STABLE: Detect LLJ and apply modest enhancement, or keep model
# - NEVER reduces winds below model surface wind
#
# Author: Marine Forecast Team
# Version: 4.0 - Hybrid method with comprehensive diagnostics
# ----------------------------------------------------------------------------

MenuItems = ["Populate"]

import SmartScript
import numpy as np
import tkinter as tk

VariableList = []

class Marine30mWindGUI:
    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Wind Adjustment & LLJ Detection Tool")
        self.master.geometry("1100x700")
        self.master.resizable(False, False)
        
        self.createWidgets()
        
    def updateSelection(self, *args):
        """Update selection status"""
        if not hasattr(self, 'statusLabel'):
            return
            
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        
        if selectedCount == 0:
            self.statusLabel.config(text="No Models Selected", fg="red")
        else:
            self.statusLabel.config(text=f"{selectedCount} Model(s) Selected", fg="green")

    def createWidgets(self):
        # Main container
        mainFrame = tk.Frame(self.master, padx=10, pady=10)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title across top
        titleLabel = tk.Label(mainFrame, text="Marine Wind Adjustment & LLJ Detection Tool", 
                             font=("Arial", 14, "bold"))
        titleLabel.grid(row=0, column=0, columnspan=2, pady=(0, 5))
        
        descLabel = tk.Label(mainFrame, 
                           text="Enhances winds during cold air advection over Gulf Stream • Detects low-level jets in stable conditions",
                           font=("Arial", 9), fg="gray", justify=tk.CENTER)
        descLabel.grid(row=1, column=0, columnspan=2, pady=(0, 10))
        
        # LEFT COLUMN - Controls
        leftFrame = tk.Frame(mainFrame)
        leftFrame.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
        
        # RIGHT COLUMN - Guide
        rightFrame = tk.Frame(mainFrame, relief=tk.RIDGE, borderwidth=2, bg="#f0f0f0")
        rightFrame.grid(row=2, column=1, sticky="nsew")
        
        # Configure grid weights
        mainFrame.grid_rowconfigure(2, weight=1)
        mainFrame.grid_columnconfigure(0, weight=2)
        mainFrame.grid_columnconfigure(1, weight=1)
        
        # === LEFT COLUMN CONTENTS ===
        
        # Row 1: SST and Model Run side by side
        topRow = tk.Frame(leftFrame)
        topRow.pack(fill=tk.X, pady=(0, 10))
        
        # SST Source
        sstFrame = tk.LabelFrame(topRow, text="SST Source", padx=10, pady=5)
        sstFrame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.sstSource = tk.StringVar()
        self.sstSource.set("Fcst")
        
        tk.Radiobutton(sstFrame, text="Fcst", variable=self.sstSource, 
                      value="Fcst", font=("Arial", 9)).pack(anchor=tk.W)
        tk.Radiobutton(sstFrame, text="RTOFS", variable=self.sstSource, 
                      value="RTOFS", font=("Arial", 9)).pack(anchor=tk.W)
        
        # Model Run
        runFrame = tk.LabelFrame(topRow, text="Model Run", padx=10, pady=5)
        runFrame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.modelRun = tk.StringVar()
        self.modelRun.set("Current")
        
        tk.Radiobutton(runFrame, text="Current", variable=self.modelRun, 
                      value="Current", font=("Arial", 9)).pack(anchor=tk.W)
        tk.Radiobutton(runFrame, text="Previous", variable=self.modelRun, 
                      value="Previous", font=("Arial", 9)).pack(anchor=tk.W)
        
        # Model Selection
        modelFrame = tk.LabelFrame(leftFrame, text="Select Models", padx=10, pady=5)
        modelFrame.pack(fill=tk.X, pady=(0, 10))
        
        self.statusLabel = tk.Label(modelFrame, text="1 Model Selected", 
                                  font=("Arial", 9, "bold"), fg="green")
        self.statusLabel.pack(side=tk.BOTTOM, pady=(5, 0))
        
        # Models in 2 columns
        modelsGrid = tk.Frame(modelFrame)
        modelsGrid.pack(fill=tk.X)
        
        atmModels = [
            ("GFS", "GFS"),
            ("NAM", "NAM"),
            ("ECMWF", "nECMWF0p25"),
            ("CMC", "CMCnh")
        ]
        
        self.modelSelections = {}
        
        for i, (displayName, modelId) in enumerate(atmModels):
            var = tk.StringVar()
            var.set("No")
            self.modelSelections[modelId] = var
            
            col = i % 2
            row = i // 2
            
            cb = tk.Checkbutton(modelsGrid, text=displayName, 
                              variable=var, onvalue="Yes", offvalue="No",
                              command=self.updateSelection, font=("Arial", 9))
            cb.grid(row=row, column=col, sticky=tk.W, padx=5)
        
        self.modelSelections["GFS"].set("Yes")
        
        # Thresholds in compact layout
        threshFrame = tk.LabelFrame(leftFrame, text="Thresholds", padx=10, pady=5)
        threshFrame.pack(fill=tk.X, pady=(0, 10))
        
        # Three thresholds in grid
        tk.Label(threshFrame, text="Unstable if <", font=("Arial", 8)).grid(row=0, column=0, sticky=tk.W)
        self.unstableThresh = tk.IntVar()
        self.unstableThresh.set(-2)
        tk.Spinbox(threshFrame, from_=-10, to=0, textvariable=self.unstableThresh,
                  width=4, font=("Arial", 8)).grid(row=0, column=1)
        tk.Label(threshFrame, text="°C", font=("Arial", 8)).grid(row=0, column=2, sticky=tk.W)
        
        tk.Label(threshFrame, text="Stable if >", font=("Arial", 8)).grid(row=1, column=0, sticky=tk.W)
        self.stableThresh = tk.IntVar()
        self.stableThresh.set(2)
        tk.Spinbox(threshFrame, from_=0, to=10, textvariable=self.stableThresh,
                  width=4, font=("Arial", 8)).grid(row=1, column=1)
        tk.Label(threshFrame, text="°C", font=("Arial", 8)).grid(row=1, column=2, sticky=tk.W)
        
        tk.Label(threshFrame, text="LLJ if 925/Sfc >", font=("Arial", 8)).grid(row=2, column=0, sticky=tk.W)
        self.lljThresh = tk.DoubleVar()
        self.lljThresh.set(1.3)
        tk.Spinbox(threshFrame, from_=1.1, to=2.0, increment=0.1, textvariable=self.lljThresh,
                  width=4, font=("Arial", 8), format="%.1f").grid(row=2, column=1)
        tk.Label(threshFrame, text="ratio", font=("Arial", 8)).grid(row=2, column=2, sticky=tk.W)
        
        tk.Label(threshFrame, text="Manual Adj", font=("Arial", 8)).grid(row=3, column=0, sticky=tk.W)
        self.manualAdj = tk.IntVar()
        self.manualAdj.set(0)
        tk.Spinbox(threshFrame, from_=-20, to=20, textvariable=self.manualAdj,
                  width=4, font=("Arial", 8)).grid(row=3, column=1)
        tk.Label(threshFrame, text="%", font=("Arial", 8)).grid(row=3, column=2, sticky=tk.W)
        
        # Output Grids in 2 columns
        outputFrame = tk.LabelFrame(leftFrame, text="Output Grids", padx=10, pady=5)
        outputFrame.pack(fill=tk.X, pady=(0, 10))
        
        # Left side outputs
        leftOutputs = tk.Frame(outputFrame)
        leftOutputs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.applyWind = tk.BooleanVar()
        self.applyWind.set(True)
        tk.Checkbutton(leftOutputs, text="Wind", variable=self.applyWind, 
                      font=("Arial", 8)).pack(anchor=tk.W)
        
        self.applyGust = tk.BooleanVar()
        self.applyGust.set(True)
        tk.Checkbutton(leftOutputs, text="WindGust", variable=self.applyGust, 
                      font=("Arial", 8)).pack(anchor=tk.W)
        
        self.create925Wind = tk.BooleanVar()
        self.create925Wind.set(True)
        tk.Checkbutton(leftOutputs, text="Wind_925mb", variable=self.create925Wind, 
                      font=("Arial", 8)).pack(anchor=tk.W)
        
        self.createStability = tk.BooleanVar()
        self.createStability.set(True)
        tk.Checkbutton(leftOutputs, text="Stability_Regime", variable=self.createStability, 
                      font=("Arial", 8)).pack(anchor=tk.W)
        
        # Right side outputs
        rightOutputs = tk.Frame(outputFrame)
        rightOutputs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.createAdjustment = tk.BooleanVar()
        self.createAdjustment.set(True)
        tk.Checkbutton(rightOutputs, text="Adjustment_Applied", 
                      variable=self.createAdjustment, font=("Arial", 8)).pack(anchor=tk.W)
        
        self.createWindShear = tk.BooleanVar()
        self.createWindShear.set(True)
        tk.Checkbutton(rightOutputs, text="WindShear_925_Sfc", 
                      variable=self.createWindShear, font=("Arial", 8)).pack(anchor=tk.W)
        
        self.createLLJ = tk.BooleanVar()
        self.createLLJ.set(True)
        tk.Checkbutton(rightOutputs, text="LLJ_Indicator", 
                      variable=self.createLLJ, font=("Arial", 8)).pack(anchor=tk.W)
        
        # Buttons at bottom of left column
        buttonFrame = tk.Frame(leftFrame)
        buttonFrame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        tk.Button(buttonFrame, text="Run Tool", command=self.runTool, 
                 bg="lightblue", font=("Arial", 10, "bold"), width=12).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(buttonFrame, text="Cancel", command=self.cancel, 
                 font=("Arial", 10), width=10).pack(side=tk.LEFT)
        
        # === RIGHT COLUMN - GUIDE ===
        guideTitle = tk.Label(rightFrame, text="Stability Regimes & Tool Behavior", 
                             font=("Arial", 10, "bold"), bg="#f0f0f0")
        guideTitle.pack(pady=(10, 10))
        
        # Create scrollable text area for guide
        guideCanvas = tk.Canvas(rightFrame, bg="#f0f0f0", highlightthickness=0)
        guideScrollbar = tk.Scrollbar(rightFrame, orient="vertical", command=guideCanvas.yview)
        guideContent = tk.Frame(guideCanvas, bg="#f0f0f0")
        
        guideContent.bind(
            "<Configure>",
            lambda e: guideCanvas.configure(scrollregion=guideCanvas.bbox("all"))
        )
        
        guideCanvas.create_window((0, 0), window=guideContent, anchor="nw")
        guideCanvas.configure(yscrollcommand=guideScrollbar.set)
        
        guideCanvas.pack(side="left", fill="both", expand=True, padx=10)
        guideScrollbar.pack(side="right", fill="y")
        
        # UNSTABLE section
        unstableFrame = tk.Frame(guideContent, bg="#e8f5e9", relief=tk.SOLID, borderwidth=1)
        unstableFrame.pack(fill=tk.X, pady=(0, 8), padx=5)
        
        tk.Label(unstableFrame, text="UNSTABLE", font=("Arial", 9, "bold"), 
                fg="darkgreen", bg="#e8f5e9").pack(anchor=tk.W, padx=5, pady=(3,0))
        tk.Label(unstableFrame, text="Cold Air over Warm Water", font=("Arial", 8, "italic"), 
                fg="darkgreen", bg="#e8f5e9").pack(anchor=tk.W, padx=5)
        
        tk.Label(unstableFrame, text="• Strong vertical mixing", font=("Arial", 8), 
                bg="#e8f5e9").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(unstableFrame, text="• Brings 30m momentum down", font=("Arial", 8), 
                bg="#e8f5e9").pack(anchor=tk.W, padx=10)
        tk.Label(unstableFrame, text="• Gulf Stream CAA scenarios", font=("Arial", 8), 
                bg="#e8f5e9", fg="darkgreen").pack(anchor=tk.W, padx=10)
        
        tk.Label(unstableFrame, text="Tool Action:", font=("Arial", 8, "bold"), 
                bg="#e8f5e9").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(unstableFrame, text="Surface = 30m × Efficiency", font=("Arial", 8), 
                bg="#e8f5e9").pack(anchor=tk.W, padx=15)
        tk.Label(unstableFrame, text="Efficiency: 85-95%", font=("Arial", 8), 
                bg="#e8f5e9").pack(anchor=tk.W, padx=15)
        tk.Label(unstableFrame, text="ENHANCES winds ✓", font=("Arial", 8, "bold"), 
                bg="#e8f5e9", fg="darkgreen").pack(anchor=tk.W, padx=15, pady=(0,3))
        
        # NEUTRAL section
        neutralFrame = tk.Frame(guideContent, bg="#fff9c4", relief=tk.SOLID, borderwidth=1)
        neutralFrame.pack(fill=tk.X, pady=(0, 8), padx=5)
        
        tk.Label(neutralFrame, text="NEUTRAL", font=("Arial", 9, "bold"), 
                bg="#fff9c4").pack(anchor=tk.W, padx=5, pady=(3,0))
        tk.Label(neutralFrame, text="Transitional Conditions", font=("Arial", 8, "italic"), 
                bg="#fff9c4").pack(anchor=tk.W, padx=5)
        
        tk.Label(neutralFrame, text="• Moderate mixing", font=("Arial", 8), 
                bg="#fff9c4").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(neutralFrame, text="• Ambiguous stability", font=("Arial", 8), 
                bg="#fff9c4").pack(anchor=tk.W, padx=10)
        
        tk.Label(neutralFrame, text="Tool Action:", font=("Arial", 8, "bold"), 
                bg="#fff9c4").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(neutralFrame, text="Take MAX(model, mixed)", font=("Arial", 8), 
                bg="#fff9c4").pack(anchor=tk.W, padx=15)
        tk.Label(neutralFrame, text="Never reduces winds", font=("Arial", 8, "bold"), 
                bg="#fff9c4").pack(anchor=tk.W, padx=15, pady=(0,3))
        
        # STABLE section
        stableFrame = tk.Frame(guideContent, bg="#ffebee", relief=tk.SOLID, borderwidth=1)
        stableFrame.pack(fill=tk.X, pady=(0, 8), padx=5)
        
        tk.Label(stableFrame, text="STABLE", font=("Arial", 9, "bold"), 
                fg="red", bg="#ffebee").pack(anchor=tk.W, padx=5, pady=(3,0))
        tk.Label(stableFrame, text="Warm Air over Cold Water", font=("Arial", 8, "italic"), 
                fg="red", bg="#ffebee").pack(anchor=tk.W, padx=5)
        
        tk.Label(stableFrame, text="• Weak mixing", font=("Arial", 8), 
                bg="#ffebee").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(stableFrame, text="• Often LOW-LEVEL JET", font=("Arial", 8, "bold"), 
                bg="#ffebee", fg="red").pack(anchor=tk.W, padx=10)
        tk.Label(stableFrame, text="• 925mb wind can be 2x sfc", font=("Arial", 8), 
                bg="#ffebee").pack(anchor=tk.W, padx=10)
        
        tk.Label(stableFrame, text="Tool Action:", font=("Arial", 8, "bold"), 
                bg="#ffebee").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(stableFrame, text="IF LLJ detected:", font=("Arial", 8, "italic"), 
                bg="#ffebee").pack(anchor=tk.W, padx=15)
        tk.Label(stableFrame, text="  Add 15% of shear", font=("Arial", 8), 
                bg="#ffebee").pack(anchor=tk.W, padx=20)
        tk.Label(stableFrame, text="ELSE:", font=("Arial", 8, "italic"), 
                bg="#ffebee").pack(anchor=tk.W, padx=15)
        tk.Label(stableFrame, text="  Keep model wind", font=("Arial", 8), 
                bg="#ffebee").pack(anchor=tk.W, padx=20, pady=(0,3))
        
        # Key Grids section
        gridsFrame = tk.Frame(guideContent, bg="#e3f2fd", relief=tk.SOLID, borderwidth=1)
        gridsFrame.pack(fill=tk.X, pady=(0, 8), padx=5)
        
        tk.Label(gridsFrame, text="KEY DIAGNOSTIC GRIDS", font=("Arial", 9, "bold"), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=5, pady=(3,0))
        
        tk.Label(gridsFrame, text="Adjustment_Applied:", font=("Arial", 8, "bold"), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(gridsFrame, text="Shows WHERE winds changed", font=("Arial", 7), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=15)
        tk.Label(gridsFrame, text="Green = enhanced, White = kept", font=("Arial", 7), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=15)
        
        tk.Label(gridsFrame, text="Wind_925mb:", font=("Arial", 8, "bold"), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(gridsFrame, text="Shows low-level jet structure", font=("Arial", 7), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=15)
        
        tk.Label(gridsFrame, text="LLJ_Indicator:", font=("Arial", 8, "bold"), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(gridsFrame, text="0-10 scale of jet strength", font=("Arial", 7), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=15)
        
        tk.Label(gridsFrame, text="Stability_Regime:", font=("Arial", 8, "bold"), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(gridsFrame, text="7=Extreme Unstable ... 1=Stable", font=("Arial", 7), 
                bg="#e3f2fd").pack(anchor=tk.W, padx=15, pady=(0,3))
        
        # Example section
        exampleFrame = tk.Frame(guideContent, bg="#f5f5f5", relief=tk.SOLID, borderwidth=1)
        exampleFrame.pack(fill=tk.X, pady=(0, 8), padx=5)
        
        tk.Label(exampleFrame, text="GULF STREAM CAA EXAMPLE", font=("Arial", 9, "bold"), 
                bg="#f5f5f5").pack(anchor=tk.W, padx=5, pady=(3,0))
        
        tk.Label(exampleFrame, text="Model Sfc: 15 kt", font=("Arial", 7), 
                bg="#f5f5f5").pack(anchor=tk.W, padx=10, pady=(3,0))
        tk.Label(exampleFrame, text="30m Wind: 28 kt", font=("Arial", 7), 
                bg="#f5f5f5").pack(anchor=tk.W, padx=10)
        tk.Label(exampleFrame, text="T_925: 5°C, SST: 18°C", font=("Arial", 7), 
                bg="#f5f5f5").pack(anchor=tk.W, padx=10)
        tk.Label(exampleFrame, text="Instability: -13°C ⚡", font=("Arial", 7, "bold"), 
                bg="#f5f5f5", fg="darkgreen").pack(anchor=tk.W, padx=10)
        tk.Label(exampleFrame, text="→ Final: 25.5 kt (+10.5 kt)", font=("Arial", 8, "bold"), 
                bg="#f5f5f5", fg="darkgreen").pack(anchor=tk.W, padx=10, pady=(0,3))
        
        # Safety note
        safetyFrame = tk.Frame(guideContent, bg="#ffffff", relief=tk.SOLID, borderwidth=1)
        safetyFrame.pack(fill=tk.X, pady=(0, 5), padx=5)
        
        tk.Label(safetyFrame, text="⚠ SAFETY", font=("Arial", 8, "bold"), 
                bg="#ffffff").pack(anchor=tk.W, padx=5, pady=(3,0))
        tk.Label(safetyFrame, text="Tool NEVER reduces winds", font=("Arial", 7), 
                bg="#ffffff").pack(anchor=tk.W, padx=10)
        tk.Label(safetyFrame, text="below model surface wind", font=("Arial", 7), 
                bg="#ffffff").pack(anchor=tk.W, padx=10, pady=(0,3))
    
    def getValues(self):
        selectedModels = []
        for modelId, var in self.modelSelections.items():
            if var.get() == "Yes":
                selectedModels.append(modelId)
        
        return {
            "Models": selectedModels,
            "SST Source": self.sstSource.get(),
            "Apply Wind": self.applyWind.get(),
            "Apply Gust": self.applyGust.get(),
            "Create 925 Wind": self.create925Wind.get(),
            "Create Stability": self.createStability.get(),
            "Create Adjustment": self.createAdjustment.get(),
            "Create WindShear": self.createWindShear.get(),
            "Create LLJ": self.createLLJ.get(),
            "Unstable Threshold": self.unstableThresh.get(),
            "Stable Threshold": self.stableThresh.get(),
            "LLJ Threshold": self.lljThresh.get(),
            "Manual Adjustment": self.manualAdj.get(),
            "Model Run": self.modelRun.get()
        }
    
    def runTool(self):
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        if selectedCount == 0:
            self.statusLabel.config(text="ERROR: Select at least 1 model!", fg="red")
            return
        
        self.callback(self.getValues())
        self.master.destroy()

    def cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure (SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def showGUI(self, editArea, timeRange):
        """Show the custom GUI and get parameters"""
        self.editArea = editArea
        self.timeRange = timeRange
        self.varDict = None
        
        root = tk.Tk()
        gui = Marine30mWindGUI(root, self.guiCallback)
        root.mainloop()
        
        return self.varDict
    
    def guiCallback(self, values):
        """Callback from GUI"""
        self.varDict = values

    def getSST(self, sstSource, GridTimeRange):
        """Get SST data from specified source"""
        print(f"    Getting SST from {sstSource}...")
        
        if sstSource == "RTOFS":
            try:
                rtofsDB = self.findDatabase("D2D_RTOFS", 0)
                if rtofsDB is None:
                    print(f"      ✗ RTOFS not available, using Fcst")
                    return self.getSST("Fcst", GridTimeRange)
                
                rtofs_sst = self.getGrids(rtofsDB.modelIdentifier(), "SST", "SFC", 
                                         GridTimeRange, mode="First", noDataError=0)
                
                if rtofs_sst is not None:
                    if np.max(rtofs_sst) > 50.0:
                        sst_celsius = (rtofs_sst - 32.0) * 5.0/9.0
                    else:
                        sst_celsius = rtofs_sst
                    print(f"      ✓ RTOFS SST (mean: {np.mean(sst_celsius):.1f}°C)")
                    return sst_celsius.copy()
                else:
                    return self.getSST("Fcst", GridTimeRange)
            except Exception as e:
                print(f"      ✗ RTOFS error: {str(e)}")
                return self.getSST("Fcst", GridTimeRange)
        
        else:  # Fcst SST
            try:
                fcst = self.mutableID().modelIdentifier()
                sst_data = self.getGrids(fcst, "SST", "SFC", GridTimeRange, 
                                        mode="First", noDataError=0)
                
                if sst_data is None:
                    print(f"      ✗ No Fcst SST available")
                    return None
                
                if np.max(sst_data) > 50.0:
                    sst_celsius = (sst_data - 32.0) * 5.0/9.0
                else:
                    sst_celsius = sst_data
                
                print(f"      ✓ Fcst SST (mean: {np.mean(sst_celsius):.1f}°C)")
                return sst_celsius.copy()
                
            except Exception as e:
                print(f"      ✗ SST error: {str(e)}")
                return None

    def execute(self, editArea, timeRange, varDict=None):
        """
        COMPREHENSIVE MARINE WIND ADJUSTMENT
        
        Purpose: Enhance winds during cold air advection over Gulf Stream
                 Detect and handle low-level jets in stable conditions
        
        Method: Hybrid approach based on stability regime
        """
        
        print("\n" + "="*70)
        print("MARINE WIND ADJUSTMENT & LOW-LEVEL JET DETECTION")
        print("="*70)
        
        self.statusBarMsg("Starting wind adjustment tool...", "R")
        
        # Show GUI
        if varDict is None:
            varDict = self.showGUI(editArea, timeRange)
            if varDict is None:
                self.statusBarMsg("Tool cancelled", "S")
                return
        
        # Get parameters
        models = varDict["Models"]
        sstSource = varDict["SST Source"]
        applyWind = varDict["Apply Wind"]
        applyGust = varDict["Apply Gust"]
        create925Wind = varDict["Create 925 Wind"]
        createStability = varDict["Create Stability"]
        createAdjustment = varDict["Create Adjustment"]
        createWindShear = varDict["Create WindShear"]
        createLLJ = varDict["Create LLJ"]
        unstableThresh = varDict["Unstable Threshold"]
        stableThresh = varDict["Stable Threshold"]
        lljThresh = varDict["LLJ Threshold"]
        manualAdj = varDict["Manual Adjustment"] / 100.0
        modelRun = varDict["Model Run"]
        
        if len(models) == 0:
            self.statusBarMsg("ERROR: No models selected", "S")
            return
        
        print(f"\nConfiguration:")
        print(f"  Models: {', '.join(models)}")
        print(f"  SST Source: {sstSource}")
        print(f"  Unstable if T925-SST < {unstableThresh}°C")
        print(f"  Stable if T925-SST > {stableThresh}°C")
        print(f"  LLJ if Wind_925 > Surface × {lljThresh}")
        
        # Mixing efficiency table (for unstable/neutral conditions)
        mixing_table = [
            (-15.0, 0.935, 1.28),  # Extreme unstable
            (-10.0, 0.910, 1.26),  # Strong unstable
            (-5.0,  0.890, 1.23),  # Moderate unstable
            (0.0,   0.865, 1.18),  # Weak unstable
            (3.0,   0.840, 1.12),  # Near neutral
            (5.0,   0.815, 1.08),  # Weakly stable
            (999.0, 0.775, 1.05),  # Stable
        ]
        
        # Get time periods
        fcst = self.mutableID().modelIdentifier()
        try:
            gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
            if not gridinfos:
                gridinfos = self.getGridInfo(fcst, "SST", "SFC", timeRange)
            if not gridinfos:
                start = timeRange.startTime().unixTime()
                end = timeRange.endTime().unixTime()
                gridinfos = []
                current = start
                while current < end:
                    period_end = min(current + 10800, end)
                    tr = self.GM_makeTimeRange(current, period_end)
                    gridinfos.append(type('obj', (object,), {'gridTime': lambda t=tr: t})())
                    current = period_end
        except Exception as e:
            print(f"ERROR getting time periods: {str(e)}")
            return
        
        print(f"\nProcessing {len(gridinfos)} time period(s)...")
        
        periods_processed = 0
        
        # Process each period
        for idx, gridinfo in enumerate(gridinfos):
            GridTimeRange = gridinfo.gridTime()
            
            print(f"\n{'='*60}")
            print(f"PERIOD {idx+1}/{len(gridinfos)}")
            print(f"{'='*60}")
            
            self.statusBarMsg(f"Processing period {idx+1}/{len(gridinfos)}", "R")
            
            # Get SST
            sst_grid = self.getSST(sstSource, GridTimeRange)
            if sst_grid is None:
                print(f"✗ No SST - skipping period")
                continue
            
            # Initialize accumulators
            t925_accum = None
            wind_925_mag_accum = None
            wind_925_dir_accum = None
            wind_sfc_mag_accum = None
            wind_sfc_dir_accum = None
            wind_30m_mag_accum = None
            wind_30m_dir_accum = None
            model_count = 0
            
            # Process each model
            for model in models:
                print(f"\n  Model: {model}")
                atmModelID = "D2D_" + model
                
                try:
                    atmDB = self.findDatabase(atmModelID, 0 if modelRun == "Current" else -1)
                    if atmDB is None:
                        print(f"    ✗ Not available")
                        continue
                    
                    atmDataBaseID = atmDB.modelIdentifier()
                    
                    # Get T at 925mb
                    t925 = self.getGrids(atmDataBaseID, "t", "MB925", GridTimeRange, 
                                        mode="First", noDataError=0)
                    if t925 is None:
                        print(f"    ✗ No 925mb temperature")
                        continue
                    t925_celsius = t925 - 273.15
                    print(f"    ✓ T_925mb: {np.mean(t925_celsius):.1f}°C")
                    
                    # Get model surface wind
                    wind_sfc = None
                    for param, level in [("wind", "SFC"), ("wind10m", "SFC"), ("wind", "MB1000")]:
                        wind_sfc = self.getGrids(atmDataBaseID, param, level, GridTimeRange,
                                                mode="First", noDataError=0)
                        if wind_sfc is not None:
                            print(f"    ✓ Surface wind: {np.mean(wind_sfc[0])*1.94:.1f} kt")
                            break
                    
                    if wind_sfc is None:
                        print(f"    ✗ No surface wind")
                        continue
                    
                    # Get wind at 925mb
                    wind_925 = None
                    for param, level in [("wind", "MB925"), ("wind", "MB950")]:
                        wind_925 = self.getGrids(atmDataBaseID, param, level, GridTimeRange,
                                                mode="First", noDataError=0)
                        if wind_925 is not None:
                            print(f"    ✓ 925mb wind: {np.mean(wind_925[0])*1.94:.1f} kt")
                            break
                    
                    if wind_925 is None:
                        print(f"    ✗ No 925mb wind")
                        continue
                    
                    # Get wind at 30m (or use 925mb as fallback)
                    wind_30m = None
                    for param, level in [("wind", "FHAG30"), ("wind", "BL030")]:
                        wind_30m = self.getGrids(atmDataBaseID, param, level, GridTimeRange,
                                                mode="First", noDataError=0)
                        if wind_30m is not None:
                            print(f"    ✓ 30m wind: {np.mean(wind_30m[0])*1.94:.1f} kt")
                            break
                    
                    if wind_30m is None:
                        # Use 925mb wind as 30m wind
                        wind_30m = wind_925
                        print(f"    → Using 925mb wind for 30m level")
                    
                    # Accumulate
                    if t925_accum is None:
                        t925_accum = t925_celsius.copy()
                        wind_925_mag_accum = wind_925[0].copy()
                        wind_925_dir_accum = wind_925[1].copy()
                        wind_sfc_mag_accum = wind_sfc[0].copy()
                        wind_sfc_dir_accum = wind_sfc[1].copy()
                        wind_30m_mag_accum = wind_30m[0].copy()
                        wind_30m_dir_accum = wind_30m[1].copy()
                    else:
                        t925_accum += t925_celsius
                        wind_925_mag_accum += wind_925[0]
                        wind_925_dir_accum = (wind_925_dir_accum + wind_925[1]) / 2.0
                        wind_sfc_mag_accum += wind_sfc[0]
                        wind_sfc_dir_accum = (wind_sfc_dir_accum + wind_sfc[1]) / 2.0
                        wind_30m_mag_accum += wind_30m[0]
                        wind_30m_dir_accum = (wind_30m_dir_accum + wind_30m[1]) / 2.0
                    
                    model_count += 1
                    print(f"    ✓ Accumulated")
                    
                except Exception as e:
                    print(f"    ✗ Error: {str(e)}")
                    continue
            
            if model_count == 0:
                print(f"\n✗ No valid model data")
                continue
            
            print(f"\n✓ Processed {model_count} model(s)")
            
            # Calculate averages
            if model_count > 1:
                t925_avg = t925_accum / model_count
                wind_925_mag = wind_925_mag_accum / model_count
                wind_925_dir = wind_925_dir_accum
                wind_sfc_mag = wind_sfc_mag_accum / model_count
                wind_sfc_dir = wind_sfc_dir_accum
                wind_30m_mag = wind_30m_mag_accum / model_count
                wind_30m_dir = wind_30m_dir_accum
            else:
                t925_avg = t925_accum
                wind_925_mag = wind_925_mag_accum
                wind_925_dir = wind_925_dir_accum
                wind_sfc_mag = wind_sfc_mag_accum
                wind_sfc_dir = wind_sfc_dir_accum
                wind_30m_mag = wind_30m_mag_accum
                wind_30m_dir = wind_30m_dir_accum
            
            # Calculate instability
            instability = t925_avg - sst_grid
            instability = np.clip(instability, -20.0, 20.0)
            
            print(f"\nInstability Analysis:")
            print(f"  T_925mb - SST: {np.mean(instability):.1f}°C")
            print(f"  Model Surface: {np.mean(wind_sfc_mag)*1.94:.1f} kt")
            print(f"  Wind 30m: {np.mean(wind_30m_mag)*1.94:.1f} kt")
            print(f"  Wind 925mb: {np.mean(wind_925_mag)*1.94:.1f} kt")
            
            # Determine mixing efficiency (for reference)
            mixing_efficiency = np.zeros_like(instability)
            gust_factor = np.zeros_like(instability)
            
            for i_table in range(len(mixing_table)):
                threshold, efficiency, gust_mult = mixing_table[i_table]
                if i_table == 0:
                    mask = instability < threshold
                else:
                    prev_threshold = mixing_table[i_table-1][0]
                    mask = (instability >= prev_threshold) & (instability < threshold)
                mixing_efficiency[mask] = efficiency
                gust_factor[mask] = gust_mult
            
            # Apply manual adjustment
            if abs(manualAdj) > 0.001:
                mixing_efficiency = mixing_efficiency * (1.0 + manualAdj)
                mixing_efficiency = np.clip(mixing_efficiency, 0.60, 0.98)
            
            # HYBRID SMART METHOD
            print(f"\nApplying Hybrid Method:")
            
            # Calculate mixed wind (30m × efficiency)
            mixed_wind = wind_30m_mag * mixing_efficiency
            
            # Determine regime and apply appropriate logic
            final_wind_mag = np.zeros_like(wind_sfc_mag)
            final_wind_dir = wind_sfc_dir.copy()
            adjustment_applied = np.zeros_like(wind_sfc_mag)
            
            # UNSTABLE regime: Apply strong mixing
            unstable_mask = instability < unstableThresh
            final_wind_mag[unstable_mask] = mixed_wind[unstable_mask]
            final_wind_dir[unstable_mask] = wind_30m_dir[unstable_mask]
            adjustment_applied[unstable_mask] = mixed_wind[unstable_mask] - wind_sfc_mag[unstable_mask]
            unstable_count = np.sum(unstable_mask)
            
            # STABLE regime: Check for LLJ
            stable_mask = instability > stableThresh
            llj_mask = stable_mask & (wind_925_mag > wind_sfc_mag * lljThresh)
            
            # Where LLJ exists: Apply modest enhancement
            llj_enhancement = (wind_925_mag - wind_sfc_mag) * 0.15  # 15% of difference
            final_wind_mag[llj_mask] = wind_sfc_mag[llj_mask] + llj_enhancement[llj_mask]
            adjustment_applied[llj_mask] = llj_enhancement[llj_mask]
            
            # Where stable but no LLJ: Keep model
            stable_no_llj_mask = stable_mask & ~llj_mask
            final_wind_mag[stable_no_llj_mask] = wind_sfc_mag[stable_no_llj_mask]
            adjustment_applied[stable_no_llj_mask] = 0.0
            
            stable_count = np.sum(stable_mask)
            llj_count = np.sum(llj_mask)
            
            # NEUTRAL regime: Take maximum
            neutral_mask = ~unstable_mask & ~stable_mask
            max_wind = np.maximum(wind_sfc_mag, mixed_wind)
            final_wind_mag[neutral_mask] = max_wind[neutral_mask]
            adjustment_applied[neutral_mask] = max_wind[neutral_mask] - wind_sfc_mag[neutral_mask]
            neutral_count = np.sum(neutral_mask)
            
            # Safety check: Never reduce below model
            below_model_mask = final_wind_mag < wind_sfc_mag
            final_wind_mag[below_model_mask] = wind_sfc_mag[below_model_mask]
            adjustment_applied[below_model_mask] = 0.0
            
            print(f"  Unstable points: {unstable_count} (apply mixing)")
            print(f"  Neutral points: {neutral_count} (take maximum)")
            print(f"  Stable points: {stable_count} (check LLJ)")
            print(f"    LLJ detected: {llj_count} (apply enhancement)")
            print(f"    No LLJ: {stable_count - llj_count} (keep model)")
            
            # Calculate final gusts
            # In unstable: Use stability-based gust factor
            # In LLJ: Use LLJ-based gusts (higher factor)
            # Otherwise: Use model-based factor
            final_gust = np.zeros_like(final_wind_mag)
            final_gust[unstable_mask] = final_wind_mag[unstable_mask] * gust_factor[unstable_mask]
            final_gust[llj_mask] = final_wind_mag[llj_mask] * 1.35  # LLJ gusts
            other_mask = ~unstable_mask & ~llj_mask
            final_gust[other_mask] = final_wind_mag[other_mask] * 1.15  # Normal gusts
            
            # Create stability categories
            stability_regime = np.where(instability < -15, 7,
                              np.where(instability < -10, 6,
                              np.where(instability < -5, 5,
                              np.where(instability < 0, 4,
                              np.where(instability < 3, 3,
                              np.where(instability < 5, 2, 1))))))
            
            # Calculate wind shear (925mb - surface)
            wind_shear = (wind_925_mag - wind_sfc_mag) * 1.94  # Convert to knots
            
            # Calculate LLJ indicator (0-10 scale)
            llj_ratio = wind_925_mag / np.maximum(wind_sfc_mag, 0.5)  # Avoid divide by zero
            llj_indicator = np.clip((llj_ratio - 1.0) * 5.0, 0.0, 10.0)
            
            # Create grids
            try:
                if applyWind:
                    self.createGrid("Fcst", "Wind", "VECTOR",
                                  (final_wind_mag, final_wind_dir), GridTimeRange)
                    print(f"✓ Wind grid created")
                
                if applyGust:
                    self.createGrid("Fcst", "WindGust", "SCALAR",
                                  final_gust, GridTimeRange)
                    print(f"✓ WindGust grid created")
                
                if create925Wind:
                    self.createGrid("Fcst", "Wind_925mb", "VECTOR",
                                  (wind_925_mag, wind_925_dir), GridTimeRange)
                    print(f"✓ Wind_925mb grid created")
                
                if createStability:
                    self.createGrid("Fcst", "Stability_Regime", "SCALAR",
                                  stability_regime, GridTimeRange,
                                  minAllowedValue=1.0, maxAllowedValue=7.0, precision=0)
                    print(f"✓ Stability_Regime grid created")
                
                if createAdjustment:
                    adjustment_kt = adjustment_applied * 1.94
                    self.createGrid("Fcst", "Adjustment_Applied", "SCALAR",
                                  adjustment_kt, GridTimeRange)
                    print(f"✓ Adjustment_Applied grid created")
                
                if createWindShear:
                    self.createGrid("Fcst", "WindShear_925_Sfc", "SCALAR",
                                  wind_shear, GridTimeRange)
                    print(f"✓ WindShear_925_Sfc grid created")
                
                if createLLJ:
                    self.createGrid("Fcst", "LLJ_Indicator", "SCALAR",
                                  llj_indicator, GridTimeRange,
                                  minAllowedValue=0.0, maxAllowedValue=10.0, precision=1)
                    print(f"✓ LLJ_Indicator grid created")
                
                periods_processed += 1
                
                # Summary statistics
                avg_model_sfc = float(np.mean(wind_sfc_mag) * 1.94)
                avg_final = float(np.mean(final_wind_mag) * 1.94)
                avg_adj = float(np.mean(adjustment_applied) * 1.94)
                avg_gust = float(np.mean(final_gust) * 1.94)
                
                print(f"\nSummary:")
                print(f"  Model Surface: {avg_model_sfc:.1f} kt")
                print(f"  Adjustment: {avg_adj:+.1f} kt")
                print(f"  Final Wind: {avg_final:.1f} kt")
                print(f"  Gusts: {avg_gust:.1f} kt")
                
                status = f"Period {idx+1}: {avg_model_sfc:.0f}kt → {avg_final:.0f}kt ({avg_adj:+.0f}kt)"
                self.statusBarMsg(status, "R")
                
            except Exception as e:
                print(f"✗ Error creating grids: {str(e)}")
                continue
        
        # Final summary
        print(f"\n{'='*70}")
        print(f"COMPLETE: {periods_processed}/{len(gridinfos)} periods processed")
        print(f"{'='*70}\n")
        
        if periods_processed == 0:
            self.statusBarMsg("ERROR: No periods processed", "S")
        else:
            self.statusBarMsg(f"SUCCESS: {periods_processed} periods processed", "R")
        
        return