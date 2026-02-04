Creating draftConversation opened. 1 unread message.

Skip to content
Using National Oceanic and Atmospheric Administration Mail with screen readers

1 of 6,215
email_file.pl has sent: output.txt
Inbox
Backup
ME
Summarize this email

ldad@ls2-opcn.er.awips.noaa.gov
Attachments
7:55 AM (2 minutes ago)
to me

 One attachment
  •  Scanned by Gmail
Jkrek17@gmail.com. Press tab to insert.
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
# Enhanced Model Blender Tool v2.0
#
# Combines model blending functionality with boosting, alternate wind levels,
# and power law stability calculations. Supports both Wind and WaveHeight 
# parameters with configurable processing options.
#
# Author: Casey Joseph/OPC - Enhanced from Boost_Model_Blender and Unstable_Winds_Calculator
# Credit to original authors: Tim Barker, Jim Kells, Fran Achorn
#
# Features:
# - Model blending with weights (5 configurable rows)
# - Dynamic dropdown menus based on model selection
# - Wind options: 10m, Boosted, 30m Stability, .995sig Stability, Stability Height
# - Wave options: Default, Boosted, Stability
# - Power law wind derivation for Stability Height option
# - Boundary layer stability analysis
# - Edit area support (automatic detection)
# - Temp grid creation (optional)
# - Smooth edge transitions
##

##
# This is an absolute override file, indicating that a higher priority version
# of the file will completely replace a lower priority version of the file.
##

#---------------------------------------------------------------------
#
#  C O N F I G U R A T I O N   S E C T I O N
#
#---------------------------------------------------------------------

# Number of blend rows in GUI
NUM_BLEND_ROWS = 6

# Default weight range for sliders
USE_NEGATIVE_WEIGHTS = 1

# Power law exponent for stability height calculations
POWER_LAW_EXPONENT = 0.15
REFERENCE_HEIGHT = 10.0

# Smoothing parameters for mask edges
SWATH_EDGE = 2
TAPER_WIDTH_MULTIPLIER = 2

# Edge style default
edgestyleDefault = "Unstable"

# Wind Models Configuration (from Boost_Model_Blender)
WindModels = (
    "GFS:3:Wind",
    "nECMWF0p25:3:Wind",
    "CMCnh:3:Wind",
    "UKMet:3:Wind",
    "JMA:3:Wind",
    "BoMACCESS-G:3:Wind",
    "NationalBlendOC:4:Wind",
    "NationalBlend:6:Wind",
    "GEFSMEAN:2:Wind",
    "ECENSMEAN:2:Wind",
    "NAM12:2:Wind",
    "NAMNest:2:Wind",
    "HRRR:2:Wind",
    "HIRESWarw:2:Wind",
    "RAP13:2:Wind",
)

# Wave Models Configuration (from Boost_Model_Blender)
WaveModels = (
    "GFSwave:3:WaveHeight",
    "nECMWF0p25wave:3:WaveHeight",
    "cmc0p25wave:2:WaveHeight",
    "JMA:2:WaveHeight",
    "BoMAUSWAVE-G:2:WaveHeight",
    "NWPS-ONA:3:WaveHeight",
    "NationalBlendOC:2:WaveHeight",
    "FNMOCwave:2:WaveHeight",
    "GEFSwaveMean:2:WaveHeight",
)

# Wind model D2D configuration for stability calculations (from Unstable_Winds_Calculator)
WIND_MODEL_CONFIG = {
    'GFS': {
        'surfaceTemp': 't:FHAG2',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    },
    'nECMWF0p25': {
        'surfaceTemp': 't:SFC',
        'temp925': 't:MB925',
        'surfacePressure': 'pmsl:SFC',
        'surfaceWind': 'wind:SFC'
    },
    'CMCnh': {
        'surfaceTemp': 't:FHAG2',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    },
    'UKMet': {
        'surfaceTemp': 't:SFC',
        'temp925': 't:MB925',
        'surfacePressure': 'pmsl:MSL',
        'surfaceWind': 'wind:FHAG10'
    },
    'BoMACCESS-G': {
        'surfaceTemp': 't:SFC',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    },
    'ECENSMEAN': {
        'surfaceTemp': 't:SFC',
        'temp925': 't:MB925',
        'surfacePressure': 'pmsl:MSL',
        'surfaceWind': 'wind:SFC'
    },
    'GEFSMEAN': {
        'surfaceTemp': 'tmean:FHAG2',
        'temp925': 'tmean:MB925',
        'surfacePressure': 'pmslmean:MSL',
        'surfaceWind': 'uwmean:FHAG10|vwmean:FHAG10'
    },
    'NAM12': {
        'surfaceTemp': 't:FHAG2',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    },
    'RAP13': {
        'surfaceTemp': 't:FHAG2',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    },
    'HIRESWarw': {
        'surfaceTemp': 't:FHAG2',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    },
    'HRRR': {
        'surfaceTemp': 't:FHAG2',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    },
    'JMA': {
        'surfaceTemp': 't:FHAG2',
        'temp925': 't:MB925',
        'surfacePressure': 'p:SFC',
        'surfaceWind': 'wind:FHAG10'
    }
}

# Wind models that support stability height / stability-based boosting
# This list should mirror the models that have stability data available
# and are used by the Unstable Winds / Stability tools.
STABILITY_MODELS = [
    'GFS',
    'nECMWF0p25',
    'CMCnh',
    'NAM12',
    'BoMACCESS-G',
    'JMA',
]

# Wave models that support stability calculations (from Unstable_Winds_Calculator)
WAVE_STABILITY_MODELS = ['GFSwave', 'nECMWF0p25wave', 'cmc0p25wave', 'BoMAUSWAVE-G', 'JMA']

# Mapping of wave models to their corresponding wind models for stability calculations
WAVE_TO_WIND_MODEL_MAP = {
    'GFSwave': 'GFS',
    'nECMWF0p25wave': 'nECMWF0p25',
    'cmc0p25wave': 'CMCnh',
    'BoMAUSWAVE-G': 'BoMACCESS-G',
    'JMA': 'JMA'
}

# Boost options per wind model
WIND_BOOST_OPTIONS = {
    'Forecast': ['10m', 'Boosted'],
    'Official': ['10m', 'Boosted'],
    'GFS': ['10m', 'Boosted', '30m Stability', '.995sig Stability', 'Stability Height'],
    'NAM12': ['10m', 'Boosted', '30m Stability', 'Stability Height'],
    'nECMWF0p25': ['10m', 'Boosted', 'Stability Height'],
    'CMCnh': ['10m', 'Boosted', 'Stability Height'],
    'UKMet': ['10m', 'Boosted', 'Stability Height'],
    'BoMACCESS-G': ['10m', 'Boosted', 'Stability Height'],
    'ECENSMEAN': ['10m', 'Boosted', 'Stability Height'],
    'GEFSMEAN': ['10m', 'Boosted', 'Stability Height'],
    'RAP13': ['10m', 'Boosted', 'Stability Height'],
    'HIRESWarw': ['10m', 'Boosted', 'Stability Height'],
    'HRRR': ['10m', 'Boosted', 'Stability Height'],
    'JMA': ['10m', 'Boosted', 'Stability Height'],
    'NAMNest': ['10m', 'Boosted'],
    'NationalBlendOC': ['10m', 'Boosted'],
    'NationalBlend': ['10m', 'Boosted'],
}

#---------------------------------------------------------------------
#
#  END OF CONFIGURATION SECTION  
#
#---------------------------------------------------------------------

ToolType = "numeric"
WeatherElementEdited = "variableElement"
ScreenList = ["SCALAR", "VECTOR"]

from numpy import *
import tkinter as tk
from tkinter import ttk
import SmartScript
import numpy as np
import TimeRange
import AbsTime

edgestyles = ["Unstable", "Flat", "Edge", "Taper"]


class EnhancedBlenderDialog:
    """Dialog for the Enhanced Model Blender with dynamic dropdowns"""
    
    def __init__(self, parent, title, paramType, availableModels, callbackMethod):
        self.parent = parent
        self.paramType = paramType  # "Wind" or "WaveHeight"
        self.availableModels = availableModels  # Dict: {modelName: [(runLabel, dbId, modelTime), ...]}
        self.callbackMethod = callbackMethod
        
        # Storage for row data
        self.rows = []  # List of row widget dictionaries
        self.result = None
        
        # Create dialog window
        self.dialog = tk.Tk()
        self.dialog.title(title)
        self.dialog.geometry("950x750")
        self.dialog.protocol("WM_DELETE_WINDOW", self._onCancel)
        
        self._buildGUI()
        
    def _buildGUI(self):
        """Build the main GUI"""
        mainFrame = tk.Frame(self.dialog, padx=10, pady=10)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        if self.paramType == "Wind":
            titleText = "Enhanced Model Blender - Wind"
        else:
            titleText = "Enhanced Model Blender - Wave Height"
        titleLabel = tk.Label(mainFrame, text=titleText, font=("Arial", 14, "bold"))
        titleLabel.pack(pady=(0, 10))
        
        # Build the model blend rows
        self._buildBlendSection(mainFrame)
        
        # Build stability application options
        self._buildStabilityOptions(mainFrame)
        
        # Build edge control
        self._buildEdgeControl(mainFrame)
        
        # Build temp grid option
        self._buildTempGridOption(mainFrame)
        
        # Build buttons
        self._buildButtons(mainFrame)
        
    
    def _buildBlendSection(self, parent):
        """Build the model blending rows section"""
        blendFrame = tk.LabelFrame(parent, text="Model Blend Configuration", padx=10, pady=10)
        blendFrame.pack(fill=tk.X, pady=(0, 10))

        # Header row aligned with data columns
        tk.Label(blendFrame, text="Model", width=20, anchor=tk.W, font=("Arial", 9, "bold")).grid(row=0, column=0, padx=2, sticky="w")
        tk.Label(blendFrame, text="Run", width=12, anchor=tk.W, font=("Arial", 9, "bold")).grid(row=0, column=1, padx=2, sticky="w")
        tk.Label(blendFrame, text="Boost Type", width=15, anchor=tk.W, font=("Arial", 9, "bold")).grid(row=0, column=2, padx=2, sticky="w")

        if self.paramType == "Wind":
            tk.Label(blendFrame, text="Height (m)", width=10, anchor=tk.W, font=("Arial", 9, "bold")).grid(row=0, column=3, padx=2, sticky="w")
        else:
            tk.Label(blendFrame, text="Boost %", width=10, anchor=tk.W, font=("Arial", 9, "bold")).grid(row=0, column=3, padx=2, sticky="w")

        tk.Label(blendFrame, text="Weight", width=15, anchor=tk.CENTER, font=("Arial", 9, "bold")).grid(row=0, column=4, padx=2, sticky="w")
        tk.Label(blendFrame, text="Pct", width=6, anchor=tk.CENTER, font=("Arial", 9, "bold")).grid(row=0, column=5, padx=2, sticky="w")
        tk.Label(blendFrame, text="", width=7, anchor=tk.W, font=("Arial", 9, "bold")).grid(row=0, column=6, padx=2, sticky="w")

        # Create blend rows directly in the same grid so columns line up
        for i in range(NUM_BLEND_ROWS):
            self._createBlendRow(blendFrame, i)


    def _createBlendRow(self, parent, rowIndex):
        """Create a single blend row with dynamic dropdowns"""
        gridRow = rowIndex + 1

        # Default height/boost% values
        if self.paramType == "Wind":
            defaultHeight = "30"
        else:
            defaultHeight = "10"

        rowData = {
            'parent': parent,
            'rowIndex': rowIndex,
            'modelVar': tk.StringVar(value=""),
            'runVar': tk.StringVar(value=""),
            'boostVar': tk.StringVar(value=""),
            'heightVar': tk.StringVar(value=defaultHeight),
            'weightVar': tk.IntVar(value=0),
            'pctVar': tk.StringVar(value="  0%"),
        }

        # Model dropdown
        modelOptions = [""] + list(self.availableModels.keys())
        rowData['modelCombo'] = ttk.Combobox(parent, textvariable=rowData['modelVar'],
                                             values=modelOptions, width=18, state="readonly")
        rowData['modelCombo'].grid(row=gridRow, column=0, padx=2)
        rowData['modelCombo'].bind('<<ComboboxSelected>>', lambda e, r=rowData: self._onModelChange(r))

        # Run dropdown (initially empty)
        rowData['runCombo'] = ttk.Combobox(parent, textvariable=rowData['runVar'],
                                           values=[""], width=10, state="readonly")
        rowData['runCombo'].grid(row=gridRow, column=1, padx=2)

        # Boost type dropdown (initially empty)
        rowData['boostCombo'] = ttk.Combobox(parent, textvariable=rowData['boostVar'],
                                             values=[""], width=13, state="readonly")
        rowData['boostCombo'].grid(row=gridRow, column=2, padx=2)
        rowData['boostCombo'].bind('<<ComboboxSelected>>', lambda e, r=rowData: self._onBoostChange(r))

        # Height/Boost% entry (shared)
        rowData['heightEntry'] = tk.Entry(parent, textvariable=rowData['heightVar'], width=6, state="disabled")
        rowData['heightEntry'].grid(row=gridRow, column=3, padx=2)

        # Weight slider
        if USE_NEGATIVE_WEIGHTS:
            origin = -10
        else:
            origin = 0

        rowData['weightSlider'] = tk.Scale(parent, from_=origin, to=10, orient=tk.HORIZONTAL,
                                           variable=rowData['weightVar'], length=100,
                                           state="disabled",
                                           command=lambda v: self._updatePercents())
        rowData['weightSlider'].grid(row=gridRow, column=4, padx=2)

        # Percent label
        rowData['pctLabel'] = tk.Label(parent, textvariable=rowData['pctVar'], width=5)
        rowData['pctLabel'].grid(row=gridRow, column=5, padx=2)

        # Clear button for this row
        rowData['clearButton'] = tk.Button(parent, text="Clear", width=6,
                                           command=lambda r=rowData: self._clearRow(r))
        rowData['clearButton'].grid(row=gridRow, column=6, padx=2)

        self.rows.append(rowData)



    def _onModelChange(self, rowData):
        """Handle model selection change - update run and boost options"""
        modelName = rowData['modelVar'].get()

        # Reset dependent fields tied to the model choice
        rowData['runVar'].set("")
        rowData['boostVar'].set("")
        rowData['heightEntry'].config(state="disabled")

        if not modelName:
            # No model selected: clear run/boost options and zero the weight
            rowData['runCombo']['values'] = [""]
            rowData['boostCombo']['values'] = [""]
            rowData['weightVar'].set(0)
            rowData['weightSlider'].set(0)
            rowData['weightSlider'].config(state="disabled")
            rowData['pctVar'].set("  0%")
            self._updatePercents()
            return

        # Update run options
        if modelName in self.availableModels:
            runs = self.availableModels[modelName]
            runLabels = [r[0] for r in runs]  # Get just the labels
            rowData['runCombo']['values'] = runLabels
            if runLabels:
                rowData['runVar'].set(runLabels[0])

        # Update boost options
        if self.paramType == "Wind":
            # Wind model boost options - use per-model configuration from WIND_BOOST_OPTIONS
            if modelName in WIND_BOOST_OPTIONS:
                boostOptions = WIND_BOOST_OPTIONS[modelName]
            else:
                # Fallback for any unexpected models
                boostOptions = ['10m', 'Boosted']
            rowData['boostCombo']['values'] = boostOptions
            if boostOptions:
                rowData['boostVar'].set(boostOptions[0])
        else:
            # Wave model boost options
            if modelName in ['Forecast', 'Official']:
                boostOptions = ['Default']
            elif modelName in WAVE_STABILITY_MODELS:
                boostOptions = ['Default', 'Boosted', 'Stability']
            else:
                boostOptions = ['Default', 'Boosted']
            rowData['boostCombo']['values'] = boostOptions
            if boostOptions:
                rowData['boostVar'].set(boostOptions[0])

        # Ensure weight slider is active now that a model is selected
        rowData['weightSlider'].config(state="normal")

        # If this row was at zero weight, give it one "part" by default
        if rowData['weightVar'].get() == 0:
            rowData['weightVar'].set(1)
            rowData['weightSlider'].set(1)

        # Recompute percentages
        self._updatePercents()

        # Trigger boost change to update height/boost% entry state
        self._onBoostChange(rowData)

    def _onBoostChange(self, rowData):
        """Handle boost type change - enable/disable height entry"""
        boostType = rowData['boostVar'].get()
        
        if self.paramType == "Wind":
            # Height entry only enabled for "Stability Height"
            if boostType == "Stability Height":
                rowData['heightEntry'].config(state="normal")
                try:
                    currentVal = float(rowData['heightVar'].get())
                    if currentVal < 10 or currentVal > 200:
                        rowData['heightVar'].set("30")
                except ValueError:
                    rowData['heightVar'].set("30")
            else:
                rowData['heightEntry'].config(state="disabled")
        else:
            # Boost % entry enabled for "Boosted" or "Stability"
            if boostType in ["Boosted", "Stability"]:
                rowData['heightEntry'].config(state="normal")
                try:
                    currentVal = float(rowData['heightVar'].get())
                    if currentVal > 20:
                        rowData['heightVar'].set("10")
                except ValueError:
                    rowData['heightVar'].set("10")
            else:
                rowData['heightEntry'].config(state="disabled")
                
    def _updatePercents(self):
        """Update percentage labels based on current weights"""
        total = 0
        for rowData in self.rows:
            total += abs(rowData['weightVar'].get())
            
        for rowData in self.rows:
            weight = rowData['weightVar'].get()
            if total == 0:
                rowData['pctVar'].set("  0%")
            else:
                pct = int(abs(weight) * 100 / total)
                rowData['pctVar'].set(f"{pct:3d}%")
                

    def _clearRow(self, rowData):
        """Reset a single blend row back to its initial state."""
        # Clear model/run/boost selections
        rowData['modelVar'].set("")
        rowData['runVar'].set("")
        rowData['boostVar'].set("")

        # Restore combobox option lists
        modelOptions = [""] + list(self.availableModels.keys())
        rowData['modelCombo']['values'] = modelOptions
        rowData['runCombo']['values'] = [""]
        rowData['boostCombo']['values'] = [""]

        # Reset height/boost% field and disable it
        if self.paramType == "Wind":
            rowData['heightVar'].set("30")
        else:
            rowData['heightVar'].set("10")
        rowData['heightEntry'].config(state="disabled")

        # Reset weight and percentage
        rowData['weightVar'].set(0)
        rowData['weightSlider'].set(0)
        rowData['pctVar'].set("  0%")

        # Recompute percentages across all rows
        self._updatePercents()

    def _onClearAll(self):
        """Clear all rows and reset global options to defaults."""
        for rowData in self.rows:
            self._clearRow(rowData)

        # Reset stability application mode
        try:
            self.stabilityModeVar.set("Unstable")
        except Exception:
            pass

        # Reset edge style and width
        try:
            self.edgestyleVar.set(edgestyleDefault)
        except Exception:
            pass
        try:
            self.edgeWidthVar.set(5)
        except Exception:
            pass

        # Reset temp grid option
        try:
            self.tempGridVar.set("Yes")
        except Exception:
            pass

        # Final percent update
        self._updatePercents()
    def _buildStabilityOptions(self, parent):
        """Build the stability application options"""
        stabilityFrame = tk.LabelFrame(
            parent,
            text="Stability Application (for Stability Height/Stability boost)",
            padx=10,
            pady=10
        )
        stabilityFrame.pack(fill=tk.X, pady=(0, 10))

        # How to apply stability-based boosts
        self.stabilityModeVar = tk.StringVar(value="Unstable")

        rb1 = tk.Radiobutton(
            stabilityFrame,
            text="Unstable Across Domain/Edit Area",
            variable=self.stabilityModeVar,
            value="Unstable"
        )
        rb1.pack(anchor=tk.W)

        rb2 = tk.Radiobutton(
            stabilityFrame,
            text="Across Entire Domain/Edit Area",
            variable=self.stabilityModeVar,
            value="Entire"
        )
        rb2.pack(anchor=tk.W)

        infoLabel = tk.Label(
            stabilityFrame,
            text=(
                "Applies when 'Stability Height', '30m Stability', '.995sig Stability' (Wind)\n"
                "or 'Stability' (Wave) is selected. If an edit area is drawn, processing is\n"
                "limited to that area."
            ),
            font=("Arial", 8, "italic"),
            fg="gray"
        )
        infoLabel.pack(anchor=tk.W, pady=(2, 0))

    def _buildEdgeControl(self, parent):
        """Build the edge style control"""
        edgeFrame = tk.LabelFrame(parent, text="Edge Control", padx=10, pady=10)
        edgeFrame.pack(fill=tk.X, pady=(0, 10))

        innerFrame = tk.Frame(edgeFrame)
        innerFrame.pack(fill=tk.X)

        # Edge style
        styleFrame = tk.Frame(innerFrame)
        styleFrame.pack(side=tk.LEFT, padx=(0, 20))

        # Edge style radio buttons, including new 'Unstable' option
        edgestyles = ["Unstable", "Flat", "Edge", "Taper"]
        self.edgestyleVar = tk.StringVar(value=edgestyleDefault)

        for style in edgestyles:
            rb = tk.Radiobutton(
                styleFrame,
                text=style,
                variable=self.edgestyleVar,
                value=style,
                command=self._onEdgeStyleChange
            )
            rb.pack(anchor=tk.W)

        # Edge width
        widthFrame = tk.Frame(innerFrame)
        widthFrame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.edgeWidthVar = tk.IntVar(value=5)
        self.edgeWidthSlider = tk.Scale(
            widthFrame,
            from_=1,
            to=30,
            orient=tk.HORIZONTAL,
            variable=self.edgeWidthVar,
            label="Edge Width:",
            length=200
        )
        self.edgeWidthSlider.pack(anchor=tk.W)

        # Initialize slider state based on default style
        self._onEdgeStyleChange()

    def _onEdgeStyleChange(self):
        """Enable/disable Edge Width slider depending on edge style."""
        # Edge width is only meaningful for legacy 'Edge' and 'Taper' modes.
        # For 'Flat' and 'Unstable', the width slider is disabled.
        style = self.edgestyleVar.get()
        if style in ("Edge", "Taper"):
            self.edgeWidthSlider.config(state="normal")
        else:
            self.edgeWidthSlider.config(state="disabled")
        
    def _buildTempGridOption(self, parent):
        """Build the temp grid creation option"""
        tempFrame = tk.LabelFrame(parent, text="Temp Grids", padx=10, pady=10)
        tempFrame.pack(fill=tk.X, pady=(0, 10))
        
        self.tempGridVar = tk.StringVar(value="Yes")
        
        rb1 = tk.Radiobutton(tempFrame, text="Yes", variable=self.tempGridVar, value="Yes")
        rb1.pack(side=tk.LEFT, padx=(0, 20))
        
        rb2 = tk.Radiobutton(tempFrame, text="No", variable=self.tempGridVar, value="No")
        rb2.pack(side=tk.LEFT)
        
        infoLabel = tk.Label(tempFrame, 
                            text="Creates temporary grids for boosted/modified model data and stability masks",
                            font=("Arial", 8, "italic"), fg="gray")
        infoLabel.pack(side=tk.LEFT, padx=(20, 0))
        
    
    def _buildButtons(self, parent):
        """Build the action buttons"""
        buttonFrame = tk.Frame(parent)
        buttonFrame.pack(pady=(10, 0))

        tk.Button(buttonFrame, text="Run", width=10, command=self._onRun).pack(side=tk.LEFT, padx=5)
        tk.Button(buttonFrame, text="Run/Dismiss", width=12, command=self._onRunDismiss).pack(side=tk.LEFT, padx=5)
        tk.Button(buttonFrame, text="Cancel", width=10, command=self._onCancel).pack(side=tk.LEFT, padx=5)
        tk.Button(buttonFrame, text="Clear All", width=10, command=self._onClearAll).pack(side=tk.LEFT, padx=5)


    def _collectResults(self):
        """Collect GUI selections into a settings dict"""
        blendConfigs = []

        for rowData in self.rows:
            modelName = rowData['modelVar'].get()
            if not modelName:
                continue

            runLabel = rowData['runVar'].get()
            boostType = rowData['boostVar'].get()
            weight = rowData['weightVar'].get()

            if weight == 0:
                continue

            # Get the dbId and modelTime for the selected run
            dbId = None
            modelTime = None
            if modelName in self.availableModels:
                for item in self.availableModels[modelName]:
                    # Handle both old format (3 items) and new format (4 items)
                    if len(item) >= 3:
                        label = item[0]
                        dbid = item[1]
                        mtime = item[2]
                    else:
                        continue
                    if label == runLabel:
                        dbId = dbid
                        modelTime = mtime
                        break

            if dbId is None:
                continue

            config = {
                'modelName': modelName,
                'runLabel': runLabel,
                'dbId': dbId,
                'modelTime': modelTime,
                'boostType': boostType,
                'weight': weight,
            }

            # Add height or boost% based on parameter type
            if self.paramType == "Wind":
                try:
                    config['height'] = float(rowData['heightVar'].get())
                except ValueError:
                    config['height'] = 30.0
            else:
                try:
                    config['boostPercent'] = float(rowData['heightVar'].get())
                except ValueError:
                    config['boostPercent'] = 10.0

            blendConfigs.append(config)

        return {
            'blendConfigs': blendConfigs,
            'stabilityMode': self.stabilityModeVar.get(),
            'edgeStyle': self.edgestyleVar.get(),
            'edgeWidth': self.edgeWidthVar.get(),
            'createTempGrids': self.tempGridVar.get() == "Yes",
        }

    def _onRun(self):
        """Handle Run button"""
        self.result = self._collectResults()
        self.callbackMethod("Run", self.result)
        
    def _onRunDismiss(self):
        """Handle Run/Dismiss button"""
        self.result = self._collectResults()
        self.callbackMethod("OK", self.result)
        self.dialog.destroy()
        
    def _onCancel(self):
        """Handle Cancel button"""
        self.callbackMethod("Cancel", None)
        self.dialog.destroy()
        
    def show(self):
        """Show the dialog"""
        self.dialog.mainloop()


class Tool(SmartScript.SmartScript):
    def __init__(self, dbss):
        self._dbss = dbss
        SmartScript.SmartScript.__init__(self, dbss)
        self._failedTimeSteps = []
        self._successfulGrids = 0
        self._dialogShown = False
        self._cancelled = False
        self._settings = None
        self._paramType = None
        
    def preProcessTool(self, varDict):
        """Called once at beginning of Tool"""
        self.savemode = self.getVectorEditMode()
        self.setVectorEditMode("Both")
        self._failedTimeSteps = []
        self._successfulGrids = 0
        self._dialogShown = False
        self._cancelled = False
        
    def postProcessTool(self, varDict):
        """Called once at end of Tool"""
        self.setVectorEditMode(self.savemode)
        self._dialogShown = False
        self._cancelled = False
        
    def preProcessGrid(self, WEname):
        """Set up GUI based on parameter type"""
        if self._dialogShown:
            return
            
        self._dialogShown = True
        
        if WEname not in ["Wind", "WaveHeight"]:
            msg = "Enhanced Model Blender Error\n\n"
            msg += f"Tool only supports Wind and WaveHeight parameters.\n\n"
            msg += f"You attempted to run it on: {WEname}\n\n"
            msg += "Please select Wind or WaveHeight grids and try again."
            self.statusBarMsg(msg, "A")
            self.cancel()
            return
            
        self._paramType = WEname
        self._cancelled = False
        
        # Get available models
        availableModels = self._getAvailableModels(WEname)
        
        if not availableModels:
            msg = f"No models available for {WEname}"
            self.statusBarMsg(msg, "A")
            self.cancel()
            return
            
        # Show GUI
        title = f"Enhanced Model Blender - {WEname}"
        self.dlg = EnhancedBlenderDialog(None, title, WEname, availableModels, self._dialogCallback)
        self.dlg.show()
        
        # Cancel to prevent GFE from marking grids edited
        self.cancel()
        
    def _getAvailableModels(self, WEname):
        """Get available models with their runs"""
        availableModels = {}
        
        # Add Forecast database first
        fcstDb = self.mutableID()
        fcstId = fcstDb.modelIdentifier()
        if fcstId:
            availableModels['Forecast'] = [("Current", fcstId, None)]
            
        # Add Official database
        officialDb = self.findDatabase("Official")
        if officialDb is not None:
            officialId = officialDb.modelIdentifier()
            if officialId:
                availableModels['Official'] = [("Current", officialId, None)]
        
        if WEname == "Wind":
            modelConfigs = WindModels
        else:
            modelConfigs = WaveModels
            
        for modelString in modelConfigs:
            model, versions, parmlist = self._parseModelString(modelString)
            if model is None:
                continue
            if not self._acceptParmList(WEname, parmlist):
                continue
                
            runs = []
            for run in range(0, -versions, -1):
                db = self.findDatabase(model, run)
                if db is None:
                    continue
                    
                modelId = db.modelIdentifier()
                if modelId is None or modelId == "":
                    continue
                    
                modtime = db.modelTime()
                year = modtime.year
                
                if year == 1970:
                    lbltext = f"{model}: Current"
                else:
                    month = modtime.month
                    day = modtime.day
                    hour = modtime.hour
                    lbltext = f"{month:02d}/{day:02d} {hour:02d}Z"
                
                # Store: (label, dbId, modelTime, offset)
                # The offset is what we'll use to find matching D2D database
                runs.append((lbltext, modelId, modtime, run))
                
            if runs:
                availableModels[model] = runs
                
        return availableModels
        
    def _parseModelString(self, modelstring):
        """Parse a model string into model, versions, parmlist"""
        model = None
        versions = 1
        parmlist = 'ALL'
        
        pieces = modelstring.split(":")
        if len(pieces) >= 1:
            model = pieces[0]
        if len(pieces) >= 2:
            try:
                versions = abs(int(pieces[1]))
            except:
                pass
        if len(pieces) >= 3:
            parmlist = pieces[2]
            
        return (model, versions, parmlist)
        
    def _acceptParmList(self, WEName, parmlist):
        """Check if WEName is in parmlist"""
        invert = False
        parms = parmlist.split(",")
        if parms[0].startswith('^'):
            parms[0] = parms[0][1:]
            invert = True
        result = ('ALL' == parms[0]) or (WEName in parms)
        return invert ^ result
        
    def _dialogCallback(self, button, settings):
        """Handle dialog button callbacks"""
        if button == "Cancel":
            self._cancelled = True
            return
            
        self._settings = settings
        
        if not settings or not settings.get('blendConfigs'):
            self.statusBarMsg("No models selected for blending", "R")
            return
            
        # Validate weights
        weights = [c['weight'] for c in settings['blendConfigs']]
        totalWeight = sum(weights)
        
        if totalWeight == 0:
            self.statusBarMsg("Weights cannot add up to zero", "A")
            return
            
        # Process all grids
        self._processAllGrids()
        
        # Show summary
        self._showProcessingSummary()
        
    def execute(self, variableElement):
        """Execute method - does nothing, all processing in callback"""
        return variableElement
        
    def _processAllGrids(self):
        """Process all selected grids"""
        try:
            fcst = self.mutableID()
            fcstId = fcst.modelIdentifier()
            
            allParms = self.selectedParms()
            parms = []
            for parm in allParms:
                model = parm[2].modelIdentifier()
                if model == fcstId:
                    parms.append(parm)
                    
            if not parms:
                self.statusBarMsg("No forecast grids selected", "A")
                return
                
            # Get selected time range
            selectTR = self._dbss.getParmOp().getSelectionTimeRange()
            
            # Get edit area (if any)
            editAreaMask = self._getEditAreaMask()
            
            for WEname, parmlevel, dbId in parms:
                if WEname != self._paramType:
                    continue
                    
                gridinfos = self.getGridInfo(fcstId, WEname, parmlevel, selectTR)
                
                for gridinfo in gridinfos:
                    GridTimeRange = gridinfo.gridTime()
                    
                    oldGrid = self.getGrids(fcstId, WEname, parmlevel, GridTimeRange, noDataError=0)
                    if oldGrid is None:
                        continue
                        
                    if self._paramType == "Wind":
                        newGrid = self._processWindBlend(oldGrid, GridTimeRange, editAreaMask)
                    else:
                        newGrid = self._processWaveBlend(oldGrid, GridTimeRange, editAreaMask)
                        
                    if newGrid is not None:
                        if self._paramType == "Wind":
                            self.createGrid(fcstId, WEname, "VECTOR", newGrid, GridTimeRange)
                        else:
                            self.createGrid(fcstId, WEname, "SCALAR", newGrid, GridTimeRange)
                        self._successfulGrids += 1
                        
        except Exception as e:
            self.statusBarMsg(f"Error processing grids: {str(e)}", "A")
            
    def _getEditAreaMask(self):
        """Get the mask for the current edit area"""
        try:
            activeRefSet = self.getActiveEditArea()
            if activeRefSet is None:
                return None
            
            # Check if edit area is empty
            if activeRefSet.isEmpty():
                return None
                
            editAreaMask = self.encodeEditArea(activeRefSet)
            
            if editAreaMask is None or not np.any(editAreaMask):
                return None
                
            return editAreaMask
            
        except Exception:
            return None
            
    def _findD2DDatabase(self, modelName, modelTime):
        """Find the D2D database that matches the selected model run time.
        
        Uses AbsTime comparison which works correctly per diagnostic testing.
        Returns the D2D database object, or None if not found.
        """
        d2dModel = f"D2D_{modelName}"
        
        # For Forecast/Official (modelTime is None), use most recent D2D
        if modelTime is None:
            d2dDb = self.findDatabase(d2dModel, 0)
            if d2dDb is None:
                self.statusBarMsg(f"Could not find {d2dModel} database", "A")
            return d2dDb
        
        # Debug: Show what we're searching for
        targetTimeStr = f"{modelTime.month:02d}/{modelTime.day:02d} {modelTime.hour:02d}Z"
        targetUnix = None
        try:
            # Try to get the unix timestamp for comparison
            targetUnix = int(str(modelTime).replace("AbsTime(", "").replace(")", ""))
        except:
            pass
        
        # self.statusBarMsg(f"DEBUG: Searching {d2dModel} for time {targetTimeStr} (unix: {targetUnix})", "R")
            
        # Try to find D2D database with matching model time
        for offset in range(0, -10, -1):
            testDb = self.findDatabase(d2dModel, offset)
            if testDb is not None:
                testTime = testDb.modelTime()
                # Check for null database (year 1970)
                if testTime.year == 1970:
                    continue
                
                # Debug: Show what we found
                testTimeStr = f"{testTime.month:02d}/{testTime.day:02d} {testTime.hour:02d}Z"
                testUnix = None
                try:
                    testUnix = int(str(testTime).replace("AbsTime(", "").replace(")", ""))
                except:
                    pass
                
                # Try multiple comparison methods
                equalOperator = (testTime == modelTime)
                equalUnix = (testUnix == targetUnix) if (testUnix and targetUnix) else "N/A"
                
                # self.statusBarMsg(f"DEBUG: D2D offset {offset}: {testTimeStr} (unix: {testUnix}) == target? {equalOperator}, unix match? {equalUnix}", "R")
                
                if testTime == modelTime:
                    # self.statusBarMsg(f"DEBUG: FOUND MATCH at offset {offset}!", "R")
                    return testDb
                    
        # Model run not found - show debug info
        availableTimes = []
        for offset in range(0, -5, -1):
            testDb = self.findDatabase(d2dModel, offset)
            if testDb is not None:
                t = testDb.modelTime()
                if t.year != 1970:
                    availableTimes.append(f"{t.month:02d}/{t.day:02d} {t.hour:02d}Z")
        
        msg = f"Could not find {d2dModel} for time {targetTimeStr}.\n"
        msg += f"Available D2D times: {', '.join(availableTimes) if availableTimes else 'None'}"
        self.statusBarMsg(msg, "A")
        
        return None
            
    def _processWindBlend(self, oldGrid, GridTimeRange, editAreaMask):
        """Process wind blend for a single time step"""
        settings = self._settings
        blendConfigs = settings['blendConfigs']
        stabilityMode = settings['stabilityMode']
        edgeStyle = settings['edgeStyle']
        edgeWidth = settings['edgeWidth']
        createTempGrids = settings['createTempGrids']
        
        # Convert old grid to U/V
        mag, direc = oldGrid
        uOld, vOld = self.MagDirToUV(mag, direc)
        
        uSum = self.empty()
        vSum = self.empty()
        totalWeight = 0
        
        for config in blendConfigs:
            modelName = config['modelName']
            dbId = config['dbId']
            modelTime = config['modelTime']
            boostType = config['boostType']
            weight = config['weight']
            height = config.get('height', 30.0)
            
            try:
                windData = self._getProcessedWind(modelName, dbId, modelTime, boostType, height, 
                                                   GridTimeRange, stabilityMode, createTempGrids)
                                                   
                if windData is not None:
                    windMag, windDir = windData
                    u, v = self.MagDirToUV(windMag, windDir)
                    uSum += u * weight
                    vSum += v * weight
                    totalWeight += weight
                else:
                    self._failedTimeSteps.append(f"{modelName} ({boostType}) at {GridTimeRange}")
                    
            except Exception as e:
                self._failedTimeSteps.append(f"{modelName} ({boostType}) at {GridTimeRange}: {str(e)}")
                
        if totalWeight == 0:
            return None
            
        # Calculate blended wind
        uNew = uSum / totalWeight
        vNew = vSum / totalWeight
        
        # Apply edit area blending
        uFinal = self._applyEditArea(uNew, uOld, edgeStyle, edgeWidth, editAreaMask)
        vFinal = self._applyEditArea(vNew, vOld, edgeStyle, edgeWidth, editAreaMask)
        
        result = self.UVToMagDir(uFinal, vFinal)
        return result
        
    def _getProcessedWind(self, modelName, dbId, modelTime, boostType, height, GridTimeRange, stabilityMode, createTempGrids):
        """Get processed wind data based on boost type"""
        
        # Get base wind grid
        baseWind = self.getGrids(dbId, "Wind", "SFC", GridTimeRange, noDataError=0, cache=0)
        if baseWind is None:
            return None
        
        if boostType == "10m":
            # Standard 10m winds - no processing, no temp grid
            return baseWind
            
        elif boostType == "Boosted":
            # Apply variable boost formula
            return self._boostWind(baseWind, modelName, modelTime, GridTimeRange, createTempGrids)
            
        elif boostType == "30m Stability":
            # GFS or NAM12 30m with stability
            return self._getAlternateWind(modelName, dbId, modelTime, "30m", GridTimeRange, stabilityMode, createTempGrids)
            
        elif boostType == ".995sig Stability":
            # GFS .995 sigma with stability
            return self._getAlternateWind(modelName, dbId, modelTime, ".995sig", GridTimeRange, stabilityMode, createTempGrids)
            
        elif boostType == "Stability Height":
            # Power law with stability mask
            return self._getStabilityHeightWind(modelName, dbId, modelTime, height, GridTimeRange, 
                                                 stabilityMode, createTempGrids)
                                                 
        return None
        
    def _boostWind(self, windGrid, modelName, modelTime, GridTimeRange, createTempGrids):
        """Apply variable boost to wind"""
        mag, direc = windGrid
        
        # Boost formula from Boost_Model_Blender
        multiplier = 0.008571 * mag + 0.914286
        multiplier[multiplier < 1.0] = 1.0
        multiplier[multiplier > 1.15] = 1.15
        
        boostedMag = mag * multiplier
        boostedWind = (boostedMag, direc)
        
        if createTempGrids:
            tempName = self._createTempGridName("Boosted", modelName, modelTime)
            self._createTempGrid(tempName, "VECTOR", boostedWind, GridTimeRange)
            
        return boostedWind
        
    def _getAlternateWind(self, modelName, dbId, modelTime, windLevel, GridTimeRange, stabilityMode, createTempGrids):
        """Get alternate wind level (30m or .995sig) with stability blending"""
        try:
            # Find D2D database that matches the selected model run time
            d2dDb = self._findD2DDatabase(modelName, modelTime)
                        
            if d2dDb is None:
                return None
                
            # Get grid info for time range
            info = self.getGridInfo(d2dDb, "wind", "FHAG10", GridTimeRange)
            if not info:
                return None
            firstGridTR = info[0].gridTime()
            
            # Determine wind levels based on model and selection
            if modelName == "NAM12":
                if windLevel == "30m":
                    windLevels = ["FHAG10", "BL030"]
                    tempLevel = "FHAG2"
                else:
                    return None  # NAM12 doesn't support .995sig
            else:  # GFS
                if windLevel == "30m":
                    windLevels = ["FHAG10", "FHAG30"]
                elif windLevel == ".995sig":
                    windLevels = ["FHAG10", "SIG995"]
                else:
                    return None
                tempLevel = "SFC"
                    
            # Get stability data
            sfcPresPa = self.getGrids(d2dDb, "p", "SFC", firstGridTR, noDataError=0)
            if sfcPresPa is None:
                self.statusBarMsg(f"Unable to get surface pressure from {modelName}", "A")
                return None
            sfcPres = sfcPresPa / 100.0
            
            sfcTemp = self.getGrids(d2dDb, "t", tempLevel, firstGridTR, noDataError=0)
            topTemp = self.getGrids(d2dDb, "t", "MB925", firstGridTR, noDataError=0)
            
            if sfcTemp is None or topTemp is None:
                self.statusBarMsg(f"Unable to get temperature data from {modelName}", "A")
                return None
                
            # Get wind data
            model10mWind = self.getGrids(d2dDb, "wind", windLevels[0], firstGridTR, noDataError=0)
            modelAltWind = self.getGrids(d2dDb, "wind", windLevels[1], firstGridTR, noDataError=0)
            
            if model10mWind is None or modelAltWind is None:
                self.statusBarMsg(f"Unable to get wind data from {modelName} at {windLevels}", "A")
                return None
                
            # Convert to knots
            model10mWind = (model10mWind[0] * 1.94, model10mWind[1])
            modelAltWind = (modelAltWind[0] * 1.94, modelAltWind[1])

            # Apply based on stability mode:
            # - "Unstable": blend 10m and alt using stability mask + taper
            # - "Entire":   use alternate level everywhere, ignore stability
            if stabilityMode == "Unstable":
                result = self._blendWindsBasedOnStability(
                    model10mWind, modelAltWind,
                    sfcTemp, topTemp, sfcPres,
                    d2dDb, modelName, GridTimeRange, createTempGrids
                )
            else:
                result = modelAltWind

            if createTempGrids and result is not None:
                tempName = self._createTempGridName(windLevel, modelName, modelTime)
                self._createTempGrid(tempName, "VECTOR", result, GridTimeRange)
                
            return result
            
        except Exception as e:
            self.statusBarMsg(f"Error getting {modelName} {windLevel} winds: {str(e)}", "A")
            return None
            
    def _getStabilityHeightWind(self, modelName, dbId, modelTime, height, GridTimeRange, stabilityMode, createTempGrids):
        """Get wind at specified height using power law with stability mask
        
        This follows the exact pattern from Unstable_Winds_Calculator
        """
        # Debug: Show EVERY call to this function
        # self.statusBarMsg(f"DEBUG ENTRY: _getStabilityHeightWind for {modelName}, TR={GridTimeRange}", "A")
        
        try:
            if modelName not in WIND_MODEL_CONFIG:
                # For Forecast/Official, just apply power law without stability
                baseWind = self.getGrids(dbId, "Wind", "SFC", GridTimeRange, noDataError=0, cache=0)
                if baseWind is None:
                    return None
                derivedMag = self._applyPowerLaw(baseWind[0], REFERENCE_HEIGHT, height, POWER_LAW_EXPONENT)
                result = (derivedMag, baseWind[1])
                if createTempGrids:
                    tempName = self._createTempGridName(f"StabHt{int(height)}m", modelName, modelTime)
                    self._createTempGrid(tempName, "VECTOR", result, GridTimeRange)
                return result
                
            config = WIND_MODEL_CONFIG[modelName]
            
            # Find D2D database that matches the selected model run time
            d2dDb = self._findD2DDatabase(modelName, modelTime)
            
            if d2dDb is None:
                return None
                
            # Get wind config
            windConfig = config['surfaceWind']
            if '|' in windConfig:
                windVar = windConfig.split('|')[0].split(':')[0]
                windLevel = windConfig.split('|')[0].split(':')[1]
            else:
                windVar, windLevel = windConfig.split(':')
                
            info = self.getGridInfo(d2dDb, windVar, windLevel, GridTimeRange)
            if not info:
                self.statusBarMsg(f"No {modelName} data available for this time range", "A")
                return None
            firstGridTR = info[0].gridTime()
            
            # Debug: Show the time range we're using
            # self.statusBarMsg(f"DEBUG: firstGridTR = {firstGridTR}", "R")
            
            # Get temperature and pressure data - with detailed debugging
            tempVar, tempLevel = config['surfaceTemp'].split(':')
            # self.statusBarMsg(f"DEBUG: Getting {tempVar}:{tempLevel} from D2D...", "R")
            sfcTemp = self.getGrids(d2dDb, tempVar, tempLevel, firstGridTR, noDataError=0)
            # self.statusBarMsg(f"DEBUG: sfcTemp result: {'GOT DATA' if sfcTemp is not None else 'NONE'}", "R")
            
            tempVar925, tempLevel925 = config['temp925'].split(':')
            # self.statusBarMsg(f"DEBUG: Getting {tempVar925}:{tempLevel925} from D2D...", "R")
            topTemp = self.getGrids(d2dDb, tempVar925, tempLevel925, firstGridTR, noDataError=0)
            # self.statusBarMsg(f"DEBUG: topTemp result: {'GOT DATA' if topTemp is not None else 'NONE'}", "R")
            
            presVar, presLevel = config['surfacePressure'].split(':')
            # self.statusBarMsg(f"DEBUG: Getting {presVar}:{presLevel} from D2D...", "R")
            sfcPresPa = self.getGrids(d2dDb, presVar, presLevel, firstGridTR, noDataError=0)
            # self.statusBarMsg(f"DEBUG: sfcPresPa result: {'GOT DATA' if sfcPresPa is not None else 'NONE'}", "R")
            
            # Debug: Show the actual values before the None check
            # self.statusBarMsg(f"DEBUG: About to check None - sfcTemp is None: {sfcTemp is None}, topTemp is None: {topTemp is None}, sfcPresPa is None: {sfcPresPa is None}", "R")
            
            # Get wind data
            if '|' in windConfig:
                # GEFSMEAN case: separate u and v components
                uConfig, vConfig = windConfig.split('|')
                uVar, uLevel = uConfig.split(':')
                vVar, vLevel = vConfig.split(':')
                
                u = self.getGrids(d2dDb, uVar, uLevel, firstGridTR, noDataError=0)
                v = self.getGrids(d2dDb, vVar, vLevel, firstGridTR, noDataError=0)
                
                if u is None or v is None:
                    self.statusBarMsg(f"Unable to get wind components from {modelName}", "A")
                    return None
                    
                # Convert u,v to magnitude and direction, then to knots
                mag = np.sqrt(u**2 + v**2) * 1.94  # m/s to knots
                direc = np.arctan2(-u, -v) * 180.0 / np.pi
                direc = (direc + 360.0) % 360.0
                model10mWind = (mag, direc)
            else:
                # Standard case: wind vector
                model10mWind = self.getGrids(d2dDb, windVar, windLevel, firstGridTR, noDataError=0)
                if model10mWind is None:
                    self.statusBarMsg(f"Unable to get wind data from {modelName}", "A")
                    return None
                    
                # Handle HIRESWarw fill values (150 m/s for no data areas)
                if modelName == 'HIRESWarw':
                    fillMask = model10mWind[0] >= 149.0
                    model10mWind = (np.where(fillMask, 0.0, model10mWind[0]), model10mWind[1])
                    
                # Convert m/s to knots
                model10mWind = (model10mWind[0] * 1.94, model10mWind[1])
                
            # Check if any stability data is missing (explicit explicit check)
            missing_vars = []
            if sfcTemp is None:
                missing_vars.append(f"{tempVar}:{tempLevel}")
            if topTemp is None:
                missing_vars.append(f"{tempVar925}:{tempLevel925}")
            if sfcPresPa is None:
                missing_vars.append(f"{presVar}:{presLevel}")
            if missing_vars:
                self.statusBarMsg(
                    f"Unable to get stability data from {modelName}. Missing: {', '.join(missing_vars)}",
                    "A",
                )
                return None

            self.statusBarMsg(
                "DEBUG: Passed None check in _getStabilityHeightWind (all stability fields present).",
                "R",
            )
            sfcPres = sfcPresPa / 100.0

            # self.statusBarMsg(f"DEBUG: Calculating potential temperatures...", "R")
            # Calculate potential temperatures
            topTheta = self._calcPotentialTemp(topTemp, 925.0)
            sfcTheta = self._calcPotentialTemp(sfcTemp, sfcPres)
            
            # self.statusBarMsg(f"DEBUG: Creating unstable mask...", "R")
            # Calculate unstable mask for the entire domain
            unstableMask = (topTheta <= sfcTheta)
            
            # self.statusBarMsg(f"DEBUG: Stability calculations complete!", "R")
            
            # Create stability mask visualization
            if createTempGrids:
                self._createMaskVisualization(unstableMask, GridTimeRange, d2dDb, modelName)
                
            # Calculate derived wind using power law
            derivedMag = self._applyPowerLaw(model10mWind[0], REFERENCE_HEIGHT, height, POWER_LAW_EXPONENT)
            derivedWind = (derivedMag, model10mWind[1])
            
            # Apply based on stability mode
            if stabilityMode == "Unstable":
                # Use unstable mask - blend from model 10m to derived
                result = self._applyWindWithMask(model10mWind, derivedWind, unstableMask)
            else:
                # Apply to entire grid - use derived wind everywhere
                result = derivedWind
                
            if createTempGrids:
                tempName = self._createTempGridName(f"StabHt{int(height)}m", modelName, modelTime)
                self._createTempGrid(tempName, "VECTOR", result, GridTimeRange)
                
            return result
            
        except Exception as e:
            self.statusBarMsg(f"Error in stability height wind: {str(e)}", "A")
            return None
            
    def _processWaveBlend(self, oldGrid, GridTimeRange, editAreaMask):
        """Process wave blend for a single time step"""
        settings = self._settings
        blendConfigs = settings['blendConfigs']
        stabilityMode = settings['stabilityMode']
        edgeStyle = settings['edgeStyle']
        edgeWidth = settings['edgeWidth']
        createTempGrids = settings['createTempGrids']
        
        waveSum = self.empty()
        totalWeight = 0
        
        for config in blendConfigs:
            modelName = config['modelName']
            dbId = config['dbId']
            modelTime = config['modelTime']
            boostType = config['boostType']
            weight = config['weight']
            boostPercent = config.get('boostPercent', 10.0)
            
            try:
                waveData = self._getProcessedWave(modelName, dbId, modelTime, boostType, boostPercent,
                                                   GridTimeRange, stabilityMode, createTempGrids)
                                                   
                if waveData is not None:
                    waveSum += waveData * weight
                    totalWeight += weight
                else:
                    self._failedTimeSteps.append(f"{modelName} ({boostType}) at {GridTimeRange}")
                    
            except Exception as e:
                self._failedTimeSteps.append(f"{modelName} ({boostType}) at {GridTimeRange}: {str(e)}")
                
        if totalWeight == 0:
            return None
            
        # Calculate blended wave
        newWave = waveSum / totalWeight
        
        # Apply edit area blending
        finalWave = self._applyEditArea(newWave, oldGrid, edgeStyle, edgeWidth, editAreaMask)
        
        return finalWave
        
    def _getProcessedWave(self, modelName, dbId, modelTime, boostType, boostPercent, GridTimeRange, stabilityMode, createTempGrids):
        """Get processed wave data based on boost type"""
        
        # Get base wave data
        waveData = self.getGrids(dbId, "WaveHeight", "SFC", GridTimeRange, 
                                  mode="TimeWtAverage", noDataError=0, cache=0)
        if waveData is None:
            return None
            
        if boostType == "Default":
            return waveData
            
        elif boostType == "Boosted":
            # Apply simple percentage boost
            multiplier = 1.0 + (boostPercent / 100.0)
            boostedWave = waveData * multiplier
            
            if createTempGrids:
                if boostPercent >= 0:
                    tempName = self._createTempGridName(f"Boost{int(boostPercent)}pct", modelName, modelTime)
                else:
                    tempName = self._createTempGridName(f"Reduce{int(abs(boostPercent))}pct", modelName, modelTime)
                self._createTempGrid(tempName, "SCALAR", boostedWave, GridTimeRange)
                
            return boostedWave
            
        elif boostType == "Stability":
            # Apply boost in unstable areas only
            return self._getStabilityWave(modelName, dbId, modelTime, waveData, boostPercent, 
                                           GridTimeRange, stabilityMode, createTempGrids)
                                           
        return waveData
        
    def _getStabilityWave(self, modelName, dbId, modelTime, waveData, boostPercent, GridTimeRange, stabilityMode, createTempGrids):
        """Get wave data with stability-based boosting
        
        This follows the exact pattern from Unstable_Winds_Calculator _processWaveGrid
        """
        try:
            if modelName not in WAVE_TO_WIND_MODEL_MAP:
                self.statusBarMsg(f"No stability mapping available for {modelName}", "A")
                return waveData
                
            # Get the wind model for stability calculations
            windModelForStability = WAVE_TO_WIND_MODEL_MAP[modelName]
            
            if windModelForStability not in WIND_MODEL_CONFIG:
                self.statusBarMsg(f"No configuration available for {windModelForStability}", "A")
                return waveData
                
            config = WIND_MODEL_CONFIG[windModelForStability]
            
            # For wave models, try to find D2D wind database with matching time first
            # If that fails, search for one that has data for our time range
            d2dDb = self._findD2DDatabase(windModelForStability, modelTime)
            
            # If no exact match, search for any D2D that has data for this time range
            if d2dDb is None:
                d2dModel = f"D2D_{windModelForStability}"
                windConfig = config['surfaceWind']
                if '|' in windConfig:
                    windVar = windConfig.split('|')[0].split(':')[0]
                    windLevel = windConfig.split('|')[0].split(':')[1]
                else:
                    windVar, windLevel = windConfig.split(':')
                    
                for offset in range(0, -5, -1):
                    testDb = self.findDatabase(d2dModel, offset)
                    if testDb is not None and testDb.modelTime().year != 1970:
                        info = self.getGridInfo(testDb, windVar, windLevel, GridTimeRange)
                        if info:
                            d2dDb = testDb
                            break
            
            if d2dDb is None:
                self.statusBarMsg(f"Unable to find {windModelForStability} D2D data for stability", "A")
                return waveData
                
            # Get wind variable for determining first grid time
            windConfig = config['surfaceWind']
            if '|' in windConfig:
                windVar = windConfig.split('|')[0].split(':')[0]
                windLevel = windConfig.split('|')[0].split(':')[1]
            else:
                windVar, windLevel = windConfig.split(':')
                
            info = self.getGridInfo(d2dDb, windVar, windLevel, GridTimeRange)
            if not info:
                self.statusBarMsg(f"No {windModelForStability} data available for this time range", "A")
                return waveData
                
            firstGridTR = info[0].gridTime()
            
            # Get temperature and pressure data
            tempVar, tempLevel = config['surfaceTemp'].split(':')
            sfcTemp = self.getGrids(d2dDb, tempVar, tempLevel, firstGridTR, noDataError=0)
            
            tempVar925, tempLevel925 = config['temp925'].split(':')
            topTemp = self.getGrids(d2dDb, tempVar925, tempLevel925, firstGridTR, noDataError=0)
            
            presVar, presLevel = config['surfacePressure'].split(':')
            sfcPresPa = self.getGrids(d2dDb, presVar, presLevel, firstGridTR, noDataError=0)
            
            # Check if any data is missing for wave stability (explicit check)
            missing_vars = []
            if sfcTemp is None:
                missing_vars.append(f"{tempVar}:{tempLevel}")
            if topTemp is None:
                missing_vars.append(f"{tempVar925}:{tempLevel925}")
            if sfcPresPa is None:
                missing_vars.append(f"{presVar}:{presLevel}")
            if missing_vars:
                self.statusBarMsg(
                    f"Unable to get stability data for {windModelForStability}. Missing: {', '.join(missing_vars)}",
                    "A",
                )
                return waveData

            sfcPres = sfcPresPa / 100.0

            # Calculate stability
            topTheta = self._calcPotentialTemp(topTemp, 925.0)
            sfcTheta = self._calcPotentialTemp(sfcTemp, sfcPres)
            unstableMask = (topTheta <= sfcTheta)
            
            # Create stability mask visualization
            if createTempGrids:
                self._createMaskVisualization(unstableMask, GridTimeRange, d2dDb, windModelForStability)
            
            # Apply boost
            multiplier = 1.0 + (boostPercent / 100.0)
            boostedWave = waveData * multiplier
                    
            # Apply based on stability mode
            if stabilityMode == "Unstable":
                # Use unstable mask - blend from model to boosted model
                result = self._applyWaveWithMask(waveData, boostedWave, unstableMask)
            else:
                # Apply to entire grid - use boosted waves everywhere
                result = boostedWave
                
            if createTempGrids:
                if boostPercent >= 0:
                    tempName = self._createTempGridName(f"StabBoost{int(boostPercent)}pct", modelName, modelTime)
                else:
                    tempName = self._createTempGridName(f"StabReduce{int(abs(boostPercent))}pct", modelName, modelTime)
                self._createTempGrid(tempName, "SCALAR", result, GridTimeRange)
                
            return result
            
        except Exception as e:
            self.statusBarMsg(f"Error in stability wave: {str(e)}", "A")
            return waveData
            
    def _getStabilityMask(self, GridTimeRange, windModel):
        """Get stability mask using wind model"""
        try:
            if windModel not in WIND_MODEL_CONFIG:
                return None
                
            config = WIND_MODEL_CONFIG[windModel]
            
            d2dModel = f"D2D_{windModel}"
            d2dDb = self.findDatabase(d2dModel, 0)
            
            if d2dDb is None:
                return None
                
            # Get wind variable for time
            windConfig = config['surfaceWind']
            if '|' in windConfig:
                windVar = windConfig.split('|')[0].split(':')[0]
                windLevel = windConfig.split('|')[0].split(':')[1]
            else:
                windVar, windLevel = windConfig.split(':')
                
            info = self.getGridInfo(d2dDb, windVar, windLevel, GridTimeRange)
            if not info:
                return None
            firstGridTR = info[0].gridTime()
            
            # Get stability data
            tempVar, tempLevel = config['surfaceTemp'].split(':')
            sfcTemp = self.getGrids(d2dDb, tempVar, tempLevel, firstGridTR, noDataError=0)
            
            tempVar925, tempLevel925 = config['temp925'].split(':')
            topTemp = self.getGrids(d2dDb, tempVar925, tempLevel925, firstGridTR, noDataError=0)
            
            presVar, presLevel = config['surfacePressure'].split(':')
            sfcPresPa = self.getGrids(d2dDb, presVar, presLevel, firstGridTR, noDataError=0)
            
            if any(x is None for x in [sfcTemp, topTemp, sfcPresPa]):
                return None
                
            sfcPres = sfcPresPa / 100.0
            
            topTheta = self._calcPotentialTemp(topTemp, 925.0)
            sfcTheta = self._calcPotentialTemp(sfcTemp, sfcPres)
            unstableMask = (topTheta <= sfcTheta)
            
            return unstableMask
            
        except Exception:
            return None
            
    def _blendWindsBasedOnStability(self, wind10m, windAlt, sfcTemp, topTemp, sfcPres, 
                                     d2dDb, modelName, GridTimeRange, createTempGrids):
        """Blend winds based on atmospheric stability"""
        topTheta = self._calcPotentialTemp(topTemp, 925.0)
        sfcTheta = self._calcPotentialTemp(sfcTemp, sfcPres)
        
        unstableMask = (topTheta <= sfcTheta)
        
        # Create stability mask visualization
        if createTempGrids:
            self._createMaskVisualization(unstableMask, GridTimeRange, d2dDb, modelName)
                
        # Expand mask and create taper
        swathEditArea = self.getGridCellSwath(self.decodeEditArea(unstableMask), SWATH_EDGE)
        swathMask = self.encodeEditArea(swathEditArea)
        expandedMask = swathMask | unstableMask
        
        resultMag = wind10m[0].copy()
        resultDir = wind10m[1].copy()
        
        if np.any(expandedMask):
            magDiff = wind10m[0] - windAlt[0]
            dirDiff = wind10m[1] - windAlt[1]
            
            dirDiff[dirDiff < -180] += 360
            dirDiff[dirDiff > 180] -= 360
            
            taperGrid = self.taperGrid(self.decodeEditArea(expandedMask), SWATH_EDGE * TAPER_WIDTH_MULTIPLIER)
            
            magDiff *= taperGrid
            dirDiff *= taperGrid
            
            resultMag = wind10m[0] - magDiff
            resultDir = wind10m[1] - dirDiff
            
            resultDir[resultDir < 0] += 360
            resultDir[resultDir >= 360] -= 360
            
        return (resultMag, resultDir)
        
    def _applyWindWithMask(self, originalWind, derivedWind, unstableMask):
        """Apply derived winds with smooth transition at mask edges"""
        originalMask = unstableMask.copy()
        
        swathEditArea = self.getGridCellSwath(self.decodeEditArea(unstableMask), SWATH_EDGE)
        swathMask = self.encodeEditArea(swathEditArea)
        expandedMask = swathMask | unstableMask
        
        if not np.any(expandedMask):
            return originalWind
            
        magDiffGrid = np.zeros(self.getGridShape(), np.float32)
        dirDiffGrid = np.zeros(self.getGridShape(), np.float32)
        
        magDiffGrid[expandedMask] = originalWind[0][expandedMask] - derivedWind[0][expandedMask]
        dirDiffGrid[expandedMask] = originalWind[1][expandedMask] - derivedWind[1][expandedMask]
        
        dirDiffGrid[dirDiffGrid < -180] += 360
        dirDiffGrid[dirDiffGrid > 180] -= 360
        
        taperEdgeGrid = self.taperGrid(self.decodeEditArea(expandedMask), 
                                        SWATH_EDGE * TAPER_WIDTH_MULTIPLIER)
        
        magDiffGrid[expandedMask] *= taperEdgeGrid[expandedMask]
        dirDiffGrid[expandedMask] *= taperEdgeGrid[expandedMask]
        
        magWind = originalWind[0] - magDiffGrid
        dirWind = originalWind[1] - dirDiffGrid
        
        dirWind[dirWind < 0] += 360
        dirWind[dirWind >= 360] -= 360
        
        return (magWind, dirWind)
        
    def _applyWaveWithMask(self, originalWave, boostedWave, unstableMask):
        """Apply boosted waves with smooth transition at mask edges"""
        # Store original mask before expansion
        originalMask = unstableMask.copy()

        # Expand mask slightly and create taper
        swathEditArea = self.getGridCellSwath(self.decodeEditArea(unstableMask), SWATH_EDGE)
        swathMask = self.encodeEditArea(swathEditArea)
        expandedMask = swathMask | unstableMask

        if not np.any(expandedMask):
            return originalWave

        # Initialize difference grid
        diffGrid = np.zeros(self.getGridShape(), np.float32)
        diffGrid[expandedMask] = originalWave[expandedMask] - boostedWave[expandedMask]

        # Create taper grid for smooth transitions
        taperEdgeGrid = self.taperGrid(
            self.decodeEditArea(expandedMask),
            SWATH_EDGE * TAPER_WIDTH_MULTIPLIER
        )

        # Apply taper to difference - ONLY where the expanded mask is True
        diffGrid[expandedMask] *= taperEdgeGrid[expandedMask]

        # Calculate final wave heights
        finalWave = originalWave - diffGrid

        return finalWave

    def _applyEditArea(self, newGrid, oldGrid, edgeStyle, edgeWidth, editAreaMask):
        """Apply edit area effects with edge handling.

        Edge styles:
          - Unstable: use Unstable Winds Calculator-style mask expansion and tapering
                      (SWATH_EDGE / TAPER_WIDTH_MULTIPLIER) via _applyWindWithMask /
                      _applyWaveWithMask. Edge width slider is ignored.
          - Flat:     hard edge at edit area boundary.
          - Edge:     simple edge taper using user-specified edgeWidth.
          - Taper:    full taper using default width.
        """
        # Special case: Unstable edge control uses Unstable Winds-style blending
        if edgeStyle == "Unstable":
            # Determine boolean mask for where to apply the new grid
            if editAreaMask is not None:
                mask = editAreaMask.copy()
            else:
                editArea = self.getActiveEditArea()
                if editArea is None:
                    # No edit area at all – just return the new grid unchanged
                    return newGrid
                if editArea.isEmpty():
                    # Empty edit area means use entire domain
                    editArea.invert()
                mask = self.encodeEditArea(editArea)

            # If mask is empty, nothing to do
            if mask is None or not np.any(mask):
                return oldGrid

            # Use the same mask-expansion / taper logic as the Unstable Winds Calculator
            if isinstance(newGrid, tuple):
                # Vector field (Wind)
                return self._applyWindWithMask(oldGrid, newGrid, mask)
            else:
                # Scalar field (WaveHeight or other scalar)
                return self._applyWaveWithMask(oldGrid, newGrid, mask)

        # All other edge styles use the legacy edit-area-based blending
        # If no edit area mask was supplied, fall back to active edit area / full domain
        if editAreaMask is None:
            editArea = self.getActiveEditArea()
            if editArea.isEmpty():
                editArea.invert()
        else:
            editArea = self.decodeEditArea(editAreaMask)

        # Create edge grid based on style
        if edgeStyle == "Flat":
            edgeGrid = self.encodeEditArea(editArea).astype(np.float32)
        elif edgeStyle == "Edge":
            edgeGrid = self.taperGrid(editArea, edgeWidth)
        else:  # Taper
            edgeGrid = self.taperGrid(editArea, 0)

        # Apply blending
        if isinstance(newGrid, tuple):
            # Vector
            diff0 = newGrid[0] - oldGrid[0]
            diff1 = newGrid[1] - oldGrid[1]
            final0 = oldGrid[0] + (diff0 * edgeGrid)
            final1 = oldGrid[1] + (diff1 * edgeGrid)
            return (final0, final1)
        else:
            # Scalar
            diff = newGrid - oldGrid
            final = oldGrid + (diff * edgeGrid)
            return final
    def _applyPowerLaw(self, u1, z1, z2, p):
        """Apply power law to calculate wind at height z2"""
        heightRatio = z2 / z1
        u2 = u1 * np.power(heightRatio, p)
        return u2
        
    def _calcPotentialTemp(self, t_k, pres):
        """Calculate potential temperature"""
        theta = t_k * np.power((1000.0 / pres), (2.0 / 7.0))
        return theta
        
    def _createTempGridName(self, prefix, modelName, modelTime):
        """Create descriptive name for temporary grids using MODEL RUN TIME (not grid time)"""
        # Clean model name
        cleanModel = modelName.replace("nECMWF0p25", "ECMWF").replace("wave", "")
        cleanModel = cleanModel.replace("-", "").replace(".", "")
        
        # Get day/hour from MODEL TIME (not grid time)
        if modelTime is not None:
            try:
                day = modelTime.day
                hour = modelTime.hour
            except:
                day = 0
                hour = 0
        else:
            # For Forecast/Official, no timestamp
            day = None
            hour = None
            
        # Handle special prefixes
        if prefix == ".995sig":
            prefix = "sig995"
        elif prefix == "30m":
            prefix = "30m"
            
        # Build name
        if day is not None and hour is not None:
            safeName = f"{prefix}{cleanModel}{day:02d}{hour:02d}"
        else:
            safeName = f"{prefix}{cleanModel}"
            
        safeName = safeName.replace(".", "").replace(" ", "").replace("-", "")
        return safeName
        
    def _createTempGrid(self, gridName, gridType, gridData, timeRange):
        """Create temporary grid with descriptive name and proper color tables"""
        try:
            fcst = self.mutableID()
            hr = 3600
            tc = (0, 1 * hr, 1 * hr)
            
            if gridType == "VECTOR":
                try:
                    windParm = self.getParm(fcst, "Wind", "SFC")
                    windInfo = windParm.getGridInfo()
                    
                    self.createGrid("Temp", gridName, "VECTOR", gridData, timeRange,
                                    descriptiveName=gridName, timeConstraints=tc,
                                    precision=windInfo.precision(),
                                    minAllowedValue=0, maxAllowedValue=125,
                                    units=windInfo.units(), rateParm=windInfo.rateParm())
                                    
                    try:
                        self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                              "SITE/ONA/GFE/Beaufort_Winds",
                                              (0.0, 125.0), 0)
                    except:
                        try:
                            self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                  None, (0.0, 125.0), 0)
                        except:
                            pass
                        
                except Exception:
                    self.createGrid("Temp", gridName, "VECTOR", gridData, timeRange,
                                    descriptiveName=gridName, timeConstraints=tc,
                                    precision=1, minAllowedValue=0, maxAllowedValue=125,
                                    units="kt", rateParm=0)
                    try:
                        self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                              "SITE/ONA/GFE/Beaufort_Winds",
                                              (0.0, 125.0), 0)
                    except:
                        pass
                                    
            elif gridType == "SCALAR":
                if self._paramType == "WaveHeight":
                    try:
                        waveParm = self.getParm(fcst, "WaveHeight", "SFC")
                        waveInfo = waveParm.getGridInfo()
                        
                        self.createGrid("Temp", gridName, "SCALAR", gridData, timeRange,
                                        descriptiveName=gridName, timeConstraints=tc,
                                        precision=waveInfo.precision(),
                                        minAllowedValue=0, maxAllowedValue=85,
                                        units=waveInfo.units(), rateParm=waveInfo.rateParm())
                                        
                        try:
                            self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                  "SITE/ONA/GFE/Wave_Altimeter_Interp",
                                                  (0.0, 85.0), 0)
                        except:
                            try:
                                self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                      None, (0.0, 85.0), 0)
                            except:
                                pass
                            
                    except Exception:
                        self.createGrid("Temp", gridName, "SCALAR", gridData, timeRange,
                                        descriptiveName=gridName, timeConstraints=tc,
                                        precision=1, minAllowedValue=0, maxAllowedValue=85,
                                        units="ft", rateParm=0)
                        try:
                            self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                  "SITE/ONA/GFE/Wave_Altimeter_Interp",
                                                  (0.0, 85.0), 0)
                        except:
                            pass
                else:
                    # Stability mask - binary 0/1
                    self.createGrid("Temp", gridName, "SCALAR", gridData, timeRange,
                                    descriptiveName=gridName, timeConstraints=tc,
                                    precision=0, minAllowedValue=0, maxAllowedValue=1,
                                    rateParm=0)
                                    
        except Exception as e:
            self.statusBarMsg(f"Could not create temp grid {gridName}: {str(e)}", "S")
            
    def _createMaskVisualization(self, unstableMask, GridTimeRange, modelDb, modelName):
        """Create temporary grid showing unstable areas with descriptive name"""
        try:
            maskGrid = unstableMask.astype(np.float32)
            
            # Get model time from database for naming
            modTime = modelDb.modelTime()
            day = modTime.day
            hour = modTime.hour
            
            # Sanitize model name
            safeModelName = modelName.replace("-", "").replace(" ", "").replace(".", "")
            safeModelName = safeModelName.replace("nECMWF0p25", "ECMWF")
            
            # Create grid name using MODEL RUN TIME
            gridName = f"UnstableMask{safeModelName}{day:02d}{hour:02d}"
            
            hr = 3600
            tc = (0, 1 * hr, 1 * hr)
            
            self.createGrid("Temp", gridName, "SCALAR", maskGrid, GridTimeRange,
                            descriptiveName=f"Unstable Mask - {modelName} {day:02d}/{hour:02d}Z",
                            timeConstraints=tc,
                            precision=0,
                            minAllowedValue=0,
                            maxAllowedValue=1,
                            rateParm=0)
                            
        except Exception:
            pass
            
    def _showProcessingSummary(self):
        """Show AlertViz popup summary of processing results"""
        if self._successfulGrids == 0 and self._failedTimeSteps:
            msg = "Enhanced Model Blender FAILED\n\n"
            msg += "Unable to process any grids.\n\n"
            msg += "Failed for:\n"
            # Remove duplicates
            uniqueFailures = list(set(self._failedTimeSteps))
            msg += "\n".join(uniqueFailures[:15])
            if len(uniqueFailures) > 15:
                msg += f"\n... and {len(uniqueFailures) - 15} more"
            msg += "\n\nCheck that selected models have data for the selected time range."
            
            self.statusBarMsg(msg, "A")
            
        elif self._failedTimeSteps:
            msg = "Enhanced Model Blender - Partial Success\n\n"
            msg += f"Processed {self._successfulGrids} grid(s) successfully.\n\n"
            # Remove duplicates
            uniqueFailures = list(set(self._failedTimeSteps))
            msg += f"Unable to get data for {len(uniqueFailures)} component(s):\n\n"
            msg += "\n".join(uniqueFailures[:15])
            if len(uniqueFailures) > 15:
                msg += f"\n... and {len(uniqueFailures) - 15} more"
            msg += "\n\nCheck model data availability."
            
            self.statusBarMsg(msg, "A")
output.txt
Displaying output.txt.
