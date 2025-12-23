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
# Enhanced Model Blender Tool
#
# Combines model blending functionality with boosting and alternate wind levels
# Supports both Wind and WaveHeight parameters with configurable processing options
#
# Author: Casey Joseph/OPC - Enhanced from original Model_Blend by Tim Barker
# Credit to other authors Jim Kells (jmk_ModelBlend, jmk_MakeTmpGrid) Fran Achorn (10m_BL_Theta_Lapse_Rate, Boost_ECMWF_Winds)
#
# Features:
# - Model blending with weights
# - Wind and Wave boosting capability (configurable % for waves, variable for winds)
# - GFS alternate wind levels (30m, 50m, 80m, 100m, .995 sigma)
# - NAM12 alternate wind level (30m only)
# - Automatic temporary grid creation for processed models
# - Parameter-specific model filtering
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

MAX_IN_COLUMN = 15
USE_NEGATIVE_WEIGHTS = 1

# Wind Models Configuration
WindModels = (
    "nECMWF0p25:3:Wind",
    "GFS:3:Wind",
    "NAM12:2:Wind", 
    "RAP13:2:Wind",
    "HIRESWarw:2:Wind",
    "HRRR:2:Wind",
    "CMCnh:3:Wind",
    "UKMet:3:Wind",
    "NAMNest:2:Wind",
    "NationalBlendOC:4:Wind",
    "NationalBlend:6:Wind",
    "ECENSMEAN:2:Wind",
    "GEFSMEAN:2:Wind",
    "Temp:1:Wind",
)

# Wave Models Configuration  
WaveModels = (
    "nECMWF0p25wave:3:WaveHeight",
    "GFSwaveNH:3:WaveHeight", 
    "NWPS-ONA:3:WaveHeight",
    "JMA:2:WaveHeight",
    "FNMOCwave:2:WaveHeight",
    "NationalBlendOC:2:WaveHeight",
    "cmc0p25wave:2:WaveHeight",
    "BoMAUSWAVE-G:2:WaveHeight",
    "GEFSwaveMean:2:WaveHeight",
    "Temp:1:WaveHeight",
)

edgestyleDefault = "Flat"

#---------------------------------------------------------------------
#
#  END OF CONFIGURATION SECTION  
#
#---------------------------------------------------------------------

ToolType = "numeric"
WeatherElementEdited = "variableElement"
ScreenList = ["SCALAR", "VECTOR"]

from numpy import *
import tkinter
import AppDialog
import SmartScript
import numpy as np
import TimeRange
import AbsTime

edgestyles = ["Flat", "Edge", "Taper"]

class EnhancedToolDialog(AppDialog.AppDialog):
    def __init__(self, title="Tk", callbackMethod=None, labels=None, paramType=None, **kwargs):
        self.__callbackMethod = callbackMethod
        self.dbIds = []
        self.labels = []
        self.__percents = []
        self.weights = []
        self.__weightVars = []
        self.processingOptions = []  # Store processing option variables
        self.paramType = paramType  # "Wind" or "WaveHeight"
        self.waveBoostPercent = 10  # Default wave boost percentage
        self.numrows = MAX_IN_COLUMN
        self.numcolumns = 1
        if labels is not None:
            self.labels.extend(labels)
            self.numrows = min(len(labels), MAX_IN_COLUMN)
            self.numcolumns = (len(labels) - 1) // MAX_IN_COLUMN + 1
        AppDialog.AppDialog.__init__(self, **kwargs)
        self.title(title)

    def buttonbox(self):
        buttonFrame = tkinter.Frame(self)
        tkinter.Button(buttonFrame, text="Run",
            command=self.__runCB, width=10, state=tkinter.NORMAL).pack(
            side=tkinter.LEFT, pady=5, padx=10)
        tkinter.Button(buttonFrame, text="Run/Dismiss", 
            command=self.__okCB, width=12, state=tkinter.NORMAL).pack(
            side=tkinter.LEFT, pady=5, padx=10)
        tkinter.Button(buttonFrame, text="Cancel", width=10,
            command=self.cancelCB).pack(
            side=tkinter.LEFT, pady=5, padx=10)
        buttonFrame.pack(side=tkinter.BOTTOM)

    def body(self, master):
        bodyFrame = tkinter.Frame(master)
        self.buildWeightSliders(bodyFrame)
        if self.paramType == "WaveHeight":
            self.buildWaveBoostControl(bodyFrame)
        self.buildEdgeControl(bodyFrame)
        bodyFrame.pack(side=tkinter.TOP)
        return bodyFrame

    def validate(self):
        rtnval = True
        self.weights = []
        for wv in self.__weightVars:
            self.weights.append(wv.get())
        self.edgestyle = self.edgestyleString.get()
        self.edgeWidth = self.edgeWidthVar.get()
        # Get processing options
        self.selectedOptions = []
        for optVar in self.processingOptions:
            self.selectedOptions.append(optVar.get())
        # Get wave boost percentage if applicable
        if self.paramType == "WaveHeight":
            try:
                self.waveBoostPercent = float(self.waveBoostVar.get())
            except ValueError:
                self.waveBoostPercent = 10.0  # Default if invalid input
        return rtnval

    def setPercents(self, weight):
        "Set the percent labels based on the slider weights."
        total = 0
        for wv in self.__weightVars:
           total += wv.get()
        if total == 0:
            for pctVar in self.__percents:
                pctVar.set("%4d%%" % 0)
        else:
            wpct = 100 / float(total)
            for i, pctVar in enumerate(self.__percents):
                pctVar.set("%4d%%" % (self.__weightVars[i].get() * wpct))

    def __runCB(self):
        self.validate()
        self.__callbackMethod("Run")

    def __okCB(self):
        self.validate()
        self.__callbackMethod("OK")
        self.ok()

    def cancelCB(self):
        self.__callbackMethod("Cancel")
        self.cancel()

    def apply(self, event=None):
        pass

    def buildWeightSliders(self, master):
        hull = tkinter.Frame(master)
        lastColumn = len(self.labels) // MAX_IN_COLUMN
        row = 0
        column = 0
        fc = None
        
        if USE_NEGATIVE_WEIGHTS:
            origin = -10
        else:
            origin = 0
            
        for i, labelText in enumerate(self.labels):
            if fc is None:
                fc = tkinter.Frame(hull)
                
            # Create Tk variables for the weight and percent
            weightVar = tkinter.IntVar(master)
            pctVar = tkinter.StringVar(master)
            
            # Store references for other routines
            self.__weightVars.append(weightVar)
            self.__percents.append(pctVar)
            
            # Initialize the weight and percent variables
            weightVar.set(0)
            pctVar.set("%4d%%" % 0)
            
            # Create labels and sliders
            lbl = tkinter.Label(fc, text=labelText)
            slider = tkinter.Scale(fc, orient=tkinter.HORIZONTAL,
                                   from_=origin, to=10, resolution=1,
                                   command=self.setPercents,
                                   variable=weightVar, length=150)
            lab2 = tkinter.Label(fc, textvariable=pctVar, width=5)
            
            # Create processing option buttons
            optionFrame = tkinter.Frame(fc)
            optVar = tkinter.StringVar(master)
            
            if self.paramType == "Wind":
                if "GFS" in labelText:
                    # GFS gets 2x2 layout with precise positioning
                    optVar.set("10m")
                    
                    # Create a container frame with fixed height
                    container = tkinter.Frame(optionFrame, height=55, width=140)
                    container.pack_propagate(False)  # Don't shrink to fit contents
                    
                    # Create radio buttons
                    rb1 = tkinter.Radiobutton(container, text="10m", variable=optVar, value="10m")
                    rb2 = tkinter.Radiobutton(container, text="Boosted", variable=optVar, value="Boosted")
                    rb3 = tkinter.Radiobutton(container, text="30m", variable=optVar, value="30m") 
                    rb4 = tkinter.Radiobutton(container, text=".995sig", variable=optVar, value=".995sig")
                    
                    # Use place() for precise positioning within container
                    rb1.place(x=4, y=5)
                    rb2.place(x=60, y=5)
                    rb3.place(x=4, y=28)
                    rb4.place(x=60, y=28)
                    
                    container.pack()
                    
                elif "NAM12" in labelText:
                    # NAM12 gets 3 buttons with same alignment as GFS
                    optVar.set("10m")
                    
                    # Create a container frame with fixed height (same as GFS)
                    container = tkinter.Frame(optionFrame, height=55, width=140)
                    container.pack_propagate(False)  # Don't shrink to fit contents
                    
                    # Create only 3 radio buttons for NAM12
                    rb1 = tkinter.Radiobutton(container, text="10m", variable=optVar, value="10m")
                    rb2 = tkinter.Radiobutton(container, text="Boosted", variable=optVar, value="Boosted")
                    rb3 = tkinter.Radiobutton(container, text="30m", variable=optVar, value="30m")
                    
                    # Position 3 buttons with same spacing as GFS but no .995sig
                    rb1.place(x=4, y=5)
                    rb2.place(x=60, y=5)
                    rb3.place(x=4, y=28)
                    # No fourth button at (60, 28)
                    
                    container.pack()
                                       
                else:
                    # Other wind models get 2 columns, 1 row: 10m, Boosted
                    optVar.set("10m")
                    rb1 = tkinter.Radiobutton(optionFrame, text="10m", variable=optVar, value="10m")
                    rb2 = tkinter.Radiobutton(optionFrame, text="Boosted", variable=optVar, value="Boosted")
                    rb1.grid(row=0, column=0, sticky=tkinter.W)
                    rb2.grid(row=0, column=1, sticky=tkinter.W)
            elif self.paramType == "WaveHeight":
                # Wave models get 2 columns, 1 row: Default, Boosted
                optVar.set("Default")
                rb1 = tkinter.Radiobutton(optionFrame, text="Default", variable=optVar, value="Default")
                rb2 = tkinter.Radiobutton(optionFrame, text="Boosted", variable=optVar, value="Boosted")
                rb1.grid(row=0, column=0, sticky=tkinter.W)
                rb2.grid(row=0, column=1, sticky=tkinter.W)
            
            self.processingOptions.append(optVar)
            
            # Grid the items left-to-right in the current row
            if self.paramType == "Wind" and ("GFS" in labelText or "NAM12" in labelText):
                # For GFS and NAM12, center everything vertically
                lbl.grid(row=row, column=0, sticky=tkinter.E)  # East only = vertically centered
                slider.grid(row=row, column=1, sticky="", pady=(0, 20))  # Add bottom padding to push slider up
                lab2.grid(row=row, column=2, sticky=tkinter.W)  # West only = vertically centered

                # Position option frame centered
                optionFrame.grid(row=row, column=3, sticky="", padx=5, pady=0)
            else:
                # For all other models, keep bottom alignment
                lbl.grid(row=row, column=0, sticky=tkinter.SE)
                slider.grid(row=row, column=1, sticky=tkinter.SE)
                lab2.grid(row=row, column=2, sticky=tkinter.SE)
                # Position option frame at bottom
                optionFrame.grid(row=row, column=3, sticky=tkinter.S, padx=5)
            
            if column < lastColumn:
                f2 = tkinter.Frame(fc, bg="black", width=1)
                f2.grid(row=row, column=4, sticky=tkinter.NS)
                
            row += 1
            if row >= MAX_IN_COLUMN:
                fc.grid(row=0, column=column, sticky=tkinter.N)
                row = 0
                column += 1
                fc = None
                
        if fc is not None:
            fc.grid(row=0, column=column, sticky=tkinter.N)
            
        # Set initial weight for forecast
        if len(self.__weightVars) > 0:
            self.__weightVars[0].set(1)
            self.setPercents(1)
            
        hull.grid(row=0, column=0, sticky=tkinter.S)

    def buildWaveBoostControl(self, master):
        """Build wave boost percentage control - only appears for WaveHeight parameter"""
        waveBoostFrame = tkinter.Frame(master, relief=tkinter.GROOVE, borderwidth=2)
        
        # Title label
        titleLabel = tkinter.Label(waveBoostFrame, text="Wave Boost Configuration", 
                                 font=("TkDefaultFont", 10, "bold"))
        titleLabel.pack(side=tkinter.TOP, pady=(5, 10))
        
        # Input frame
        inputFrame = tkinter.Frame(waveBoostFrame)
        
        # Label and entry for boost percentage
        boostLabel = tkinter.Label(inputFrame, text="Boost Percentage:")
        self.waveBoostVar = tkinter.StringVar(master)
        self.waveBoostVar.set("10")  # Default value
        
        boostEntry = tkinter.Entry(inputFrame, textvariable=self.waveBoostVar, 
                                 width=8, justify=tkinter.CENTER)
        
        percentLabel = tkinter.Label(inputFrame, text="%")
        
        # Help text
        helpLabel = tkinter.Label(inputFrame, text="(Applied to all models with 'Boosted' selected. Negative values allowed.)",
                                font=("TkDefaultFont", 8), fg="gray")
        
        # Pack elements
        boostLabel.pack(side=tkinter.LEFT, padx=(10, 5))
        boostEntry.pack(side=tkinter.LEFT, padx=2)
        percentLabel.pack(side=tkinter.LEFT, padx=(2, 10))
        
        inputFrame.pack(side=tkinter.TOP, pady=5)
        helpLabel.pack(side=tkinter.TOP, pady=(0, 10))
        
        # Add the wave boost control after weight sliders
        waveBoostFrame.grid(row=1, column=0, columnspan=self.numcolumns, sticky=tkinter.EW, pady=5)

    def buildEdgeControl(self, master):
        edgeFrame = tkinter.Frame(master, relief=tkinter.GROOVE, borderwidth=2)
        edgestyleFrame = tkinter.Frame(edgeFrame)
        edgewidthFrame = tkinter.Frame(edgeFrame)
        
        # Create the edge style radio buttons
        self.edgestyleString = tkinter.StringVar(master)
        for edgestyle in edgestyles:
           a = tkinter.Radiobutton(edgestyleFrame, text=edgestyle,
                               variable=self.edgestyleString, value=edgestyle)
           if edgestyle == edgestyleDefault:
              a.invoke()
           a.pack(side=tkinter.TOP, anchor=tkinter.W)
        edgestyleFrame.pack(side=tkinter.LEFT, anchor=tkinter.W)
        
        # Create the edge width slider
        self.edgeWidthVar = tkinter.IntVar(master)
        self.edgeWidthVar.set(5)
        a = tkinter.Scale(edgewidthFrame, from_=1, to=30, variable=self.edgeWidthVar,
                      showvalue=1, label="Edge Width:", orient=tkinter.HORIZONTAL)
        a.pack(side=tkinter.TOP, anchor=tkinter.N, fill=tkinter.X)
        edgewidthFrame.pack(side=tkinter.RIGHT, anchor=tkinter.W, fill=tkinter.X, expand=1)

        # Add the edge control below the other controls
        # Adjust row number based on whether wave boost control is present
        edgeRow = self.numrows + (2 if self.paramType == "WaveHeight" else 1)
        edgeFrame.grid(row=edgeRow, column=0, columnspan=self.numcolumns, sticky=tkinter.EW)

#========================================================================
#
#  The Enhanced GFE Tool
#
class Tool (SmartScript.SmartScript):
    def __init__(self, dbss):
        self._dbss = dbss
        SmartScript.SmartScript.__init__(self, dbss)

    def preProcessGrid(self, WEname):
        # Determine parameter type and select appropriate models
        if WEname == "Wind":
            Models = WindModels
            paramType = "Wind"
        elif WEname == "WaveHeight":
            Models = WaveModels
            paramType = "WaveHeight"
        else:
            self.statusBarMsg("Enhanced Model Blender only supports Wind and WaveHeight parameters", "A")
            self.cancel()
            return

        self.labels = []
        self.dbIds = []
        self.modelNames = []  # Store model names for D2D access
        self.paramType = paramType

        # Add Forecast and Official databases
        db = self.mutableID()
        modelId = db.modelIdentifier()
        self._addModel('Forecast:', modelId, "Forecast")
        
        db = self.findDatabase("Official")
        if db is not None:
            modelId = db.modelIdentifier()
            self._addModel("Official", modelId, "Official")

        # Add model databases
        plist = None
        allOfficeTypes = None
        for modelString in Models:
            model, versions, parmlist = self.parseMS(modelString)
            if model is None:
                continue
            if not self.acceptPL(WEname, parmlist):
                continue

            for run in range(0, -versions, -1):
                db = self.findDatabase(model, run)
                if db is None:
                    continue
                modelId = db.modelIdentifier()
                if modelId is None or "" == modelId or modelId in self.dbIds:
                    continue
                    
                modtime = db.modelTime()
                year = modtime.year
                if year == 1970:
                    lbltext = "%s:" % model
                else:
                    month = modtime.month
                    day = modtime.day
                    hour = modtime.hour
                    lbltext = "%s %2.2d/%2.2d %2.2dZ:" % (model, month, day, hour)
                self._addModel(lbltext, modelId, model)

        # Create and show dialog
        self.dlg = EnhancedToolDialog("Enhanced Model Blender - Set Weights and Options",
                       callbackMethod=self.execWeights,
                       labels=self.labels,
                       paramType=paramType)
        self.dlg.mainloop()
        self.cancel()

    def parseMS(self, modelstring):
        """Parse a model string into a model, versions, and parmlist."""
        model = None
        versions = None
        parmlist = None
        pieces = modelstring.split(":")
        len_pcs = len(pieces)
        if len_pcs < 4:
            model = pieces[0]
            versions = 1
            parmlist = 'ALL'
            if len_pcs > 1:
                try:
                    versions = abs(int(pieces[1]))
                except:
                    pass
            if len_pcs > 2:
                parmlist = pieces[2]
        return (model, versions, parmlist)

    def acceptPL(self, WEName, parmlist):
        """Check WEName against parmlist."""
        invert = False
        parms = parmlist.split(",")
        if '^' == parms[0][0]:
            parms[0] = parms[0][1:]
            invert = True
        result = ('ALL' == parms[0]) or (WEName in parms)
        result = invert ^ result
        return result

    def _addModel(self, text, modelId, modelName):
        "Add text, modelId, and modelName to respective lists."
        self.labels.append(text)
        self.dbIds.append(modelId)
        self.modelNames.append(modelName)

    def execute(self, variableElement):
        "Enhanced blend of model/forecast fields with processing options"
        return variableElement

    def execWeights(self, button):
        if button == "Cancel":
            return

        EdgeType = self.dlg.edgestyle
        EdgeWidth = self.dlg.edgeWidth
        
        # Validate weights
        weights = self.dlg.weights
        selectedOptions = self.dlg.selectedOptions
        waveBoostPercent = getattr(self.dlg, 'waveBoostPercent', 10)  # Get wave boost percentage
        
        maxAbsWeight = max(max(weights), abs(min(weights)))
        someweights = (maxAbsWeight > 0.5)
        fcstweight = weights[0]
        otherweights = sum(weights[1:])
        totweight = fcstweight + otherweights

        if not someweights:
            self.statusBarMsg("Enhanced Model Blender has no weights", "R")
            return
        if abs(fcstweight) > 0.5 and otherweights == 0:
            self.statusBarMsg("Enhanced Model Blender weights add to no change", "R")
            return
        if totweight == 0:
            self.statusBarMsg("Weights cannot add up to zero", "A")
            return

        # Get forecast database and time range
        fcst = self.mutableID().modelIdentifier()
        selectTR = self._dbss.getParmOp().getSelectionTimeRange()
        
        # Get selected parameters
        allParms = self.selectedParms()
        parms = []
        for parm in allParms:
            model = parm[2].modelIdentifier()
            if model == fcst:
                parms.append(parm)

        # Process each parameter
        for WEname, parmlevel, dbId in parms:
            if WEname not in ["Wind", "WaveHeight"]:
                continue
                
            # Get parameter information
            parm = self.getParm(dbId, WEname, parmlevel)
            rateParm = parm.getGridInfo().isRateParm()
            wxType = str(parm.getGridInfo().getGridType())
            del parm

            # Get grids for this parameter
            gridinfos = self.getGridInfo(fcst, WEname, parmlevel, selectTR)
            for gridinfo in gridinfos:
                GridTimeRange = gridinfo.gridTime()
                
                # Process based on parameter type
                if 'SCALAR' == wxType:  # WaveHeight
                    self.processScalarParameter(WEname, GridTimeRange, weights, selectedOptions, 
                                              fcst, EdgeType, EdgeWidth, rateParm, waveBoostPercent)
                elif 'VECTOR' == wxType:  # Wind
                    self.processVectorParameter(WEname, GridTimeRange, weights, selectedOptions,
                                              fcst, EdgeType, EdgeWidth)

    def processScalarParameter(self, WEname, GridTimeRange, weights, selectedOptions, 
                             fcst, EdgeType, EdgeWidth, rateParm, waveBoostPercent):
        """Process scalar parameters (WaveHeight)"""
        gsum = self.empty()
        totweight = 0
        fcstweight = 0
        oldgrid = self.getGrids(self.dbIds[0], WEname, "SFC", GridTimeRange, noDataError=0, cache=0)
        
        if oldgrid is None:
            self.statusBarMsg("Enhanced Model Blender could not get Fcst data for " + WEname, "A")
            return

        for num, label in enumerate(self.labels):
            weight = weights[num]
            if weight != 0:
                option = selectedOptions[num] if num < len(selectedOptions) else "Default"
                
                modeType = "TimeWtAverage"
                if rateParm == 1:
                    modeType = "Sum"
                
                try:
                    grid = self.getGrids(self.dbIds[num], WEname, "SFC", GridTimeRange, 
                                       mode=modeType, noDataError=0, cache=0)
                except Exception as e:
                    # Handle cases where database exists but is corrupted/empty
                    errorstring = "Enhanced Model Blender could not get data for %s: %s" % (label, str(e))
                    self.statusBarMsg(errorstring, "A")
                    grid = None
                
                if grid is not None:
                    # Apply processing based on selected option
                    if option == "Boosted":
                        # Apply configurable boost for waves
                        grid = self.boostWaveData(grid, label, GridTimeRange, waveBoostPercent)
                    
                    gsum += (grid * weight)
                    totweight += weight
                    if (num == 0):
                        fcstweight = weight
                else:
                    if label not in [l for l in self.labels if "Enhanced Model Blender could not get data for" in str(l)]:
                        errorstring = "Enhanced Model Blender could not get data for %s" % label
                        self.statusBarMsg(errorstring, "A")

        # Create final grid
        if (totweight != 0):
            if fcstweight == totweight:
                self.statusBarMsg("Enhanced Model Blender makes no change", "R")
            else:
                newgrid = gsum / totweight
                finalgrid = self.inEditArea(newgrid, oldgrid, EdgeType, EdgeWidth)
                self.createGrid(fcst, WEname, "SCALAR", finalgrid, GridTimeRange)
        else:
            self.statusBarMsg("Enhanced Model Blender weights ended up Zero - cancelled", "A")

    def processVectorParameter(self, WEname, GridTimeRange, weights, selectedOptions,
                             fcst, EdgeType, EdgeWidth):
        """Process vector parameters (Wind)"""
        oldgrid = self.getGrids(self.dbIds[0], WEname, "SFC", GridTimeRange, noDataError=0, cache=0)
        if oldgrid is None:
            self.statusBarMsg("Enhanced Model Blender could not get Fcst data for " + WEname, "A")
            return
            
        (mag, direc) = oldgrid
        (uold, vold) = self.MagDirToUV(mag, direc)

        usum = self.empty()
        vsum = self.empty()
        totweight = 0
        fcstweight = 0

        for num, weight in enumerate(weights):
            if weight != 0:
                option = selectedOptions[num] if num < len(selectedOptions) else "10m"
                label = self.labels[num]
                modelName = self.modelNames[num] if num < len(self.modelNames) else ""
                
                try:
                    grid = self.getWindData(self.dbIds[num], WEname, GridTimeRange, option, label, modelName)
                except Exception as e:
                    # Handle cases where database exists but is corrupted/empty
                    errorstring = "Enhanced Model Blender could not get wind data for %s: %s" % (label, str(e))
                    self.statusBarMsg(errorstring, "A")
                    grid = None
                
                if grid is not None:
                    (mag, direc) = grid
                    (u, v) = self.MagDirToUV(mag, direc)
                    usum += (u * weight)
                    vsum += (v * weight)
                    totweight += weight
                    if (num == 0):
                        fcstweight = weight
                else:
                    errorstring = "Enhanced Model Blender could not get wind data for %s" % label
                    self.statusBarMsg(errorstring, "A")

        # Create final grid
        if (totweight != 0):
            if fcstweight == totweight:
                self.statusBarMsg("Enhanced Model Blender makes no change", "R")
            else:
                unew = usum / totweight
                vnew = vsum / totweight
                ufinal = self.inEditArea(unew, uold, EdgeType, EdgeWidth)
                vfinal = self.inEditArea(vnew, vold, EdgeType, EdgeWidth)
                result = self.UVToMagDir(ufinal, vfinal)
                self.createGrid(fcst, WEname, "VECTOR", result, GridTimeRange)
        else:
            self.statusBarMsg("Enhanced Model Blender weights ended up Zero - cancelled", "A")

    def getWindData(self, dbId, WEname, GridTimeRange, option, label, modelName):
        """Get wind data based on processing option"""
        if option == "10m":
            # Standard 10m winds - no temp grid created
            return self.getGrids(dbId, WEname, "SFC", GridTimeRange, noDataError=0, cache=0)
            
        elif option == "Boosted":
            # Get 10m winds and apply boost - temp grid created
            grid = self.getGrids(dbId, WEname, "SFC", GridTimeRange, noDataError=0, cache=0)
            if grid is not None:
                return self.boostWindData(grid, label, GridTimeRange)
            
        elif option in ["30m", ".995sig"]:
            # Use alternate levels - temp grid created
            if "GFS" in label:
                return self.getGFSAlternateWind(dbId, option, GridTimeRange, label, modelName)
            elif "NAM12" in label:
                # NAM12 only supports 30m
                if option == "30m":
                    return self.getNAM12AlternateWind(dbId, GridTimeRange, label, modelName)
                else:
                    # .995sig not available for NAM12
                    return None
            else:
                self.statusBarMsg(f"{option} not available for {label}", "A")
                return None
                
        return None

    def boostWindData(self, windGrid, modelLabel, GridTimeRange):
        """Apply boost to wind data using variable formula"""
        mag, dir = windGrid
        
        # Apply boost formula: factor = 0.008571*speed+0.914286, clipped to 1.0-1.15
        multiplier = 0.008571 * mag + 0.914286
        multiplier[multiplier < 1.0] = 1.0
        multiplier[multiplier > 1.15] = 1.15
        
        boosted_mag = mag * multiplier
        boosted_wind = (boosted_mag, dir)
        
        # Create temporary grid
        tempName = self.createTempGridName("Boosted", modelLabel)
        self.createTempGrid(tempName, "VECTOR", boosted_wind, GridTimeRange)
        
        return boosted_wind

    def boostWaveData(self, waveGrid, modelLabel, GridTimeRange, boostPercent=10):
        """Apply configurable boost to wave data"""
        # Convert percentage to multiplier (e.g., 10% = 1.10, -5% = 0.95)
        multiplier = 1.0 + (boostPercent / 100.0)
        boosted_wave = waveGrid * multiplier
        
        # Create temporary grid with descriptive name including percentage
        if boostPercent >= 0:
            tempName = self.createTempGridName(f"Boost{int(boostPercent)}pct", modelLabel)
        else:
            tempName = self.createTempGridName(f"Reduce{int(abs(boostPercent))}pct", modelLabel)
        
        self.createTempGrid(tempName, "SCALAR", boosted_wave, GridTimeRange)
        
        return boosted_wave

    def getGFSAlternateWind(self, dbId, windLevel, GridTimeRange, modelLabel, modelName):
        """Get GFS alternate wind levels (30m or .995 sigma)"""
        try:
            # Extract model time from the dbId by finding the matching database
            # The dbId in self.dbIds corresponds to specific model runs
            modelTime = None
            for db in [self.mutableID()] + [self.findDatabase("Official")] + [self.findDatabase(mn, offset) for mn in ["GFS", "NAM12", "nECMWF0p25", "RAP13", "HRRR", "CMCnh", "NAMNest", "NationalBlend", "NationalBlendOC"] for offset in range(-10, 1)]:
                if db is not None and db.modelIdentifier() == dbId:
                    modelTime = db.modelTime()
                    break
            
            if modelTime is None:
                self.statusBarMsg(f"Could not determine model time for {modelLabel}", "A")
                return None
            
            # Find the D2D database that matches this specific model time
            d2dModel = "D2D_GFS"
            d2dDb = None
            
            # Try to find D2D database with matching model time
            for offset in range(0, -10, -1):
                testDb = self.findDatabase(d2dModel, offset)
                if testDb is not None and testDb.modelTime() == modelTime:
                    d2dDb = testDb
                    break
            
            if d2dDb is None:
                self.statusBarMsg(f"Could not find {d2dModel} database for model time {modelTime}", "A")
                return None
            
            # Get first grid time range for the model data
            info = self.getGridInfo(d2dDb, "wind", "FHAG10", GridTimeRange)
            if info:
                firstGridTR = info[0].gridTime()
            else:
                firstGridTR = TimeRange.TimeRange(GridTimeRange.startTime(), GridTimeRange.startTime() + 1)
            
            # Determine wind levels based on selection
            if windLevel == "30m":
                windLevels = ["FHAG10", "FHAG30"]
            elif windLevel == ".995sig":
                windLevels = ["FHAG10", "SIG995"]
            else:
                return None
            
            # Get temperature and pressure data for stability calculation
            sfcPresPa = self.getGrids(d2dDb, "p", "SFC", firstGridTR, noDataError=0)
            if sfcPresPa is None:
                return None
                
            sfcPres = sfcPresPa / 100.0
            sfcTemp = self.getGrids(d2dDb, "t", "SFC", firstGridTR, noDataError=0)
            topTemp = self.getGrids(d2dDb, "t", "MB925", firstGridTR, noDataError=0)
            
            if sfcTemp is None or topTemp is None:
                return None
            
            # Get wind data
            model10mWind = self.getGrids(d2dDb, "wind", windLevels[0], firstGridTR, noDataError=0)
            modelAltWind = self.getGrids(d2dDb, "wind", windLevels[1], firstGridTR, noDataError=0)
            
            if model10mWind is None or modelAltWind is None:
                return None
            
            # Convert winds to knots
            model10mWind = (model10mWind[0] * 1.94, model10mWind[1])
            modelAltWind = (modelAltWind[0] * 1.94, modelAltWind[1])
            
            # Calculate stability and blend winds
            result = self.blendWindsBasedOnStability(model10mWind, modelAltWind, 
                                                   sfcTemp, topTemp, sfcPres)
            
            # Create temporary grid
            tempName = self.createTempGridName(windLevel, modelLabel)
            self.createTempGrid(tempName, "VECTOR", result, GridTimeRange)
            
            return result
            
        except Exception as e:
            self.statusBarMsg(f"Error getting GFS {windLevel} winds: {str(e)}", "A")
            return None

    def getNAM12AlternateWind(self, dbId, GridTimeRange, modelLabel, modelName):
        """Get NAM12 30m wind level (only 30m supported for NAM12)"""
        try:
            # Extract model time from the dbId by finding the matching database
            # The dbId in self.dbIds corresponds to specific model runs
            modelTime = None
            for db in [self.mutableID()] + [self.findDatabase("Official")] + [self.findDatabase(mn, offset) for mn in ["GFS", "NAM12", "nECMWF0p25", "RAP13", "HRRR", "CMCnh", "NAMNest", "NationalBlend", "NationalBlendOC"] for offset in range(-10, 1)]:
                if db is not None and db.modelIdentifier() == dbId:
                    modelTime = db.modelTime()
                    break
            
            if modelTime is None:
                self.statusBarMsg(f"Could not determine model time for {modelLabel}", "A")
                return None
            
            # Find the D2D database that matches this specific model time
            d2dModel = "D2D_NAM12"
            d2dDb = None
            
            # Try to find D2D database with matching model time
            for offset in range(0, -10, -1):
                testDb = self.findDatabase(d2dModel, offset)
                if testDb is not None and testDb.modelTime() == modelTime:
                    d2dDb = testDb
                    break
            
            if d2dDb is None:
                self.statusBarMsg(f"Could not find {d2dModel} database for model time {modelTime}", "A")
                return None
            
            # Get first grid time range for the model data
            info = self.getGridInfo(d2dDb, "wind", "FHAG10", GridTimeRange)
            if info:
                firstGridTR = info[0].gridTime()
            else:
                firstGridTR = TimeRange.TimeRange(GridTimeRange.startTime(), GridTimeRange.startTime() + 1)
            
            # NAM12 uses different levels than GFS
            windLevels = ["FHAG10", "BL030"]  # 10m and 30m boundary layer
            tempLevels = ["FHAG2", "MB925"]   # FHAG2 for surface, MB925 for top
            
            # Get temperature and pressure data for stability calculation
            sfcPresPa = self.getGrids(d2dDb, "p", "SFC", firstGridTR, noDataError=0)
            if sfcPresPa is None:
                return None
                
            sfcPres = sfcPresPa / 100.0
            sfcTemp = self.getGrids(d2dDb, "t", tempLevels[0], firstGridTR, noDataError=0)
            topTemp = self.getGrids(d2dDb, "t", tempLevels[1], firstGridTR, noDataError=0)
            
            if sfcTemp is None or topTemp is None:
                return None
            
            # Get wind data
            model10mWind = self.getGrids(d2dDb, "wind", windLevels[0], firstGridTR, noDataError=0)
            model30mWind = self.getGrids(d2dDb, "wind", windLevels[1], firstGridTR, noDataError=0)
            
            if model10mWind is None or model30mWind is None:
                return None
            
            # Convert winds to knots
            model10mWind = (model10mWind[0] * 1.94, model10mWind[1])
            model30mWind = (model30mWind[0] * 1.94, model30mWind[1])
            
            # Calculate stability and blend winds
            result = self.blendWindsBasedOnStability(model10mWind, model30mWind, 
                                                   sfcTemp, topTemp, sfcPres)
            
            # Create temporary grid
            tempName = self.createTempGridName("30m", modelLabel)
            self.createTempGrid(tempName, "VECTOR", result, GridTimeRange)
            
            return result
            
        except Exception as e:
            self.statusBarMsg(f"Error getting NAM12 30m winds: {str(e)}", "A")
            return None

    def blendWindsBasedOnStability(self, wind10m, windAlt, sfcTemp, topTemp, sfcPres):
        """Blend winds based on atmospheric stability"""
        # Calculate potential temperature
        topTheta = self.calcPotentialTemp(topTemp, 925.0)
        sfcTheta = self.calcPotentialTemp(sfcTemp, sfcPres)
        
        # Create stability mask (unstable where topTheta <= sfcTheta)
        unstableMask = (topTheta <= sfcTheta)
        
        # Expand mask slightly and create taper
        swathEdge = 2
        swathEditArea = self.getGridCellSwath(self.decodeEditArea(unstableMask), swathEdge)
        swathMask = self.encodeEditArea(swathEditArea)
        unstableMask = swathMask | unstableMask
        
        # Initialize result with 10m winds
        resultMag = wind10m[0].copy()
        resultDir = wind10m[1].copy()
        
        if np.any(unstableMask):
            # Calculate wind differences
            magDiff = wind10m[0] - windAlt[0]
            dirDiff = wind10m[1] - windAlt[1]
            
            # Ensure direction differences are between -180 and +180
            dirDiff[dirDiff < -180] += 360
            dirDiff[dirDiff > 180] -= 360
            
            # Create taper grid for smooth transitions
            taperGrid = self.taperGrid(self.decodeEditArea(unstableMask), swathEdge * 2)
            
            # Apply taper to differences
            magDiff *= taperGrid
            dirDiff *= taperGrid
            
            # Calculate final winds
            resultMag = wind10m[0] - magDiff
            resultDir = wind10m[1] - dirDiff
            
            # Ensure direction is 0-360
            resultDir[resultDir < 0] += 360
            resultDir[resultDir >= 360] -= 360
        
        return (resultMag, resultDir)

    def calcPotentialTemp(self, t_k, pres):
        """Calculate potential temperature"""
        theta = t_k * np.power((1000.0/pres), (2.0/7.0))
        return theta

    def createTempGridName(self, prefix, modelLabel):
        """Create descriptive name for temporary grids - format: BoostedModelNameDDHH"""
        import re
        
        # Clean up the label to extract model name and time
        cleanLabel = modelLabel.replace(":", "").strip()
        
        # Try to extract date/time if present (DD/DD HHZ format)
        timeMatch = re.search(r'(\d{2})/(\d{2}) (\d{2})Z', cleanLabel)
        if timeMatch:
            month = timeMatch.group(1)
            day = timeMatch.group(2) 
            hour = timeMatch.group(3)
            # Extract just the model name (first word before any space or time)
            modelName = cleanLabel.split()[0]
            # Clean model name of any unwanted characters
            modelName = modelName.replace("nECMWF0p25", "ECMWF").replace("n", "", 1) if modelName.startswith("n") else modelName
            # Create safe name for GFE - replace problematic characters differently
            if prefix == ".995sig":  # Special handling for .995sig
                safeName = f"sig995{modelName}{day}{hour}"
            else:
                safeName = f"{prefix}{modelName}{day}{hour}"
            # Final cleanup
            safeName = safeName.replace(".", "").replace(" ", "").replace("-", "")
            return safeName
        else:
            # For models without timestamps (like Official, Forecast)
            modelName = cleanLabel.replace("Official", "Official").replace("Forecast", "Forecast")
            if prefix == ".995sig":
                safeName = f"sig995{modelName}"
            else:
                safeName = f"{prefix}{modelName}"
            safeName = safeName.replace(".", "").replace(" ", "").replace("-", "")
            return safeName

    def createTempGrid(self, gridName, gridType, gridData, timeRange):
        """Create temporary grid with descriptive name and proper color tables"""
        try:
            # Get existing forecast parameter to copy grid structure
            fcst = self.mutableID()
            
            if gridType == "VECTOR":
                # Copy Wind parameter structure
                try:
                    windParm = self.getParm(fcst, "Wind", "SFC")
                    windInfo = windParm.getGridInfo()
                    
                    # Create time constraints
                    hr = 3600
                    tc = (0, 1 * hr, 1 * hr)
                    
                    self.createGrid("Temp", gridName, "VECTOR", gridData, timeRange,
                                  descriptiveName=gridName, timeConstraints=tc,
                                  precision=windInfo.precision(),
                                  minAllowedValue=0, maxAllowedValue=125,
                                  units=windInfo.units(), rateParm=windInfo.rateParm())
                    
                    # Set color table and display range for all modified wind grids
                    # (Boosted, 30m, .995sig) - temp grids are only created for modified data
                    try:
                        self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                            "SITE/ONA/GFE/Beaufort_Winds", 
                                            (0.0, 125.0), 0)
                    except:
                        # If the specific colormap fails, try without it but with range
                        try:
                            self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                None, (0.0, 125.0), 0)
                        except:
                            pass
                        
                except Exception as e:
                    # Fallback if can't get wind info
                    hr = 3600
                    tc = (0, 1 * hr, 1 * hr)
                    self.createGrid("Temp", gridName, "VECTOR", gridData, timeRange,
                                  descriptiveName=gridName, timeConstraints=tc,
                                  precision=1, minAllowedValue=0, maxAllowedValue=125,
                                  units="kt", rateParm=0)
                    
                    # Try to set colormap for fallback case
                    try:
                        self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                            "SITE/ONA/GFE/Beaufort_Winds",
                                            (0.0, 125.0), 0)
                    except:
                        pass
                              
            elif gridType == "SCALAR":
                if self.paramType == "WaveHeight":
                    # Copy WaveHeight parameter structure
                    try:
                        waveParm = self.getParm(fcst, "WaveHeight", "SFC")
                        waveInfo = waveParm.getGridInfo()
                        
                        hr = 3600
                        tc = (0, 1 * hr, 1 * hr)
                        
                        self.createGrid("Temp", gridName, "SCALAR", gridData, timeRange,
                                      descriptiveName=gridName, timeConstraints=tc,
                                      precision=waveInfo.precision(),
                                      minAllowedValue=0, maxAllowedValue=85,
                                      units=waveInfo.units(), rateParm=waveInfo.rateParm())
                        
                        # Set color table and display range for all boosted wave grids
                        # Temp grids are only created for boosted waves
                        try:
                            self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                "SITE/ONA/GFE/Wave_Altimeter_Interp",
                                                (0.0, 85.0), 0)
                        except:
                            # If the specific colormap fails, try without it but with range
                            try:
                                self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                    None, (0.0, 85.0), 0)
                            except:
                                pass
                            
                    except Exception as e:
                        # Fallback
                        hr = 3600
                        tc = (0, 1 * hr, 1 * hr)
                        self.createGrid("Temp", gridName, "SCALAR", gridData, timeRange,
                                      descriptiveName=gridName, timeConstraints=tc,
                                      precision=1, minAllowedValue=0, maxAllowedValue=85,
                                      units="ft", rateParm=0)
                        
                        # Try to set colormap for fallback case
                        try:
                            self.setActiveElement("Temp", gridName, "SFC", timeRange,
                                                "SITE/ONA/GFE/Wave_Altimeter_Interp",
                                                (0.0, 85.0), 0)
                        except:
                            pass
                else:
                    # Other scalar types
                    hr = 3600
                    tc = (0, 1 * hr, 1 * hr)
                    self.createGrid("Temp", gridName, "SCALAR", gridData, timeRange,
                                  descriptiveName=gridName, timeConstraints=tc,
                                  precision=1, minAllowedValue=0, maxAllowedValue=100,
                                  units="", rateParm=0)
                    
                    # Set as active
                    try:
                        self.setActiveElement("Temp", gridName, "SFC", timeRange, fitToData=1)
                    except:
                        pass
                
        except Exception as e:
            self.statusBarMsg(f"Could not create temporary grid {gridName}: {str(e)}", "A")

    def inEditArea(self, new, old, EdgeType, EdgeWidth):
        """Apply edit area effects with edge handling"""
        editArea = self.getActiveEditArea()
        
        # If no edit area selected, use entire domain
        if editArea.isEmpty():
            editArea.invert()
        
        # Create edge grid based on type
        if (EdgeType == "Flat"):
           edgegrid = editArea.getGrid().getNDArray()
        elif (EdgeType == "Edge"):
           edgegrid = self.taperGrid(editArea, EdgeWidth)
        else:
           edgegrid = self.taperGrid(editArea, 0)
        
        # Apply blending
        diff = new - old
        final = old + (diff * edgegrid)
        return final