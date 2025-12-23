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
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# Populate_SkyTool -- Version 1.0
#
# Author: Pete Banacos, WFO BTV (Started: 9/20/06)
# Last update: 1/23/07
# ----------------------------------------------------------------------------

ToolType = "numeric"
WeatherElementEdited = "IceAccretion"

import numpy as np
import TimeRange
import SmartScript

### Solicite variables from the forecaster:
VariableList = [
    ("Populate IceAccretion Version 1.0", "", "label"),
    ("Model for Temps:", "GFS", "radio", ["GFS", "nECMWF0p25"]),
    ("Model Run for Temps:", "Current", "radio", ["Current", "Previous"]),
    ("Model for SST:", "RTOFS", "radio", ["SST","RTOFS"]),
    ("Model Run for SST:", "Current", "radio", ["Current", "Previous"]),
    ]

import SmartScript

class Tool (SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def execute(self, IceAccretion, Wind, GridTimeRange, varDict):
        "Determine IcingPredictor based on air temp, SST and winds."
        print("Start Populate_IccAccretion smartTool")
        model1 = varDict["Model for Temps:"]
        modelrun = varDict["Model Run for Temps:"]
        model1SST = varDict["Model for SST:"]
        modelrunSST = varDict["Model Run for SST:"]

        modeltemp = model1
        modeltempSST = model1SST


        if modelrun == "Current":
            model = self.findDatabase(modeltemp, 0)
        else:
            model = self.findDatabase(modeltemp, -1)

        if modelrunSST == "Current":
            modelSST = self.findDatabase(modeltempSST, 0)
        else:
            modelSST = self.findDatabase(modeltempSST, -1)

        # Grab temp/sst values from the numerical model

        print('GridTimeRange = ', GridTimeRange)
        print('Air Temp model = ', model)

        # if Current model run was selected but is missing some data, use the previous run
        try:
            Temp = self.getGrids(model, "T", "SFC", GridTimeRange)
        except:
            model = self.findDatabase(modeltemp, -1)
            Temp = self.getGrids(model, "T", "SFC", GridTimeRange)
            self.statusBarMsg("Previous model run needed to be used for some temperature grids", "R")

        #convert F to C
        Ta = (Temp - 32.0) * 5.0 / 9.0

        print('SST model = ', modelSST)
        print('GridTimeRange = ', GridTimeRange)
        
        #since the sst is an analysis, use it for all time periods
        #figure out the time of the chosen sst analysis
        
        four_days_ago = self._gmtime() - (4 * 24 * 3600)
        ten_days_from_now = self._gmtime() + 10 * 24 * 3600
        allTimes = TimeRange.TimeRange(four_days_ago, ten_days_from_now)
        gridInfo = self.getGridInfo(modelSST, "SST", "SFC", allTimes)
        alltrs=[]
        overlaptrs=[]
        for info in gridInfo:
            tr=info.gridTime()
            alltrs.append(tr)
            if tr.overlaps(GridTimeRange):
                overlaptrs.append(tr)
        if len(overlaptrs) > 0:
            SST = self.getGrids(modelSST, "SST", "SFC", GridTimeRange)
        else:
            SST = self.getGrids(modelSST, "SST", "SFC", allTimes)
            
        print("max SST, Air Temp, Wind Speed")
        print(SST.max(), Ta.max(), Wind[0].max())
        #convert F to C
        Tw = (SST - 32.0) * 5.0 / 9.0

        #mask where sst > -80 (the null value over land)
        runEditArea = self.getEditArea("OPC_AOR")
#         runEditArea = self.getEditArea("Water")
        runEditAreaMask = self.encodeEditArea(runEditArea)
#
#         mask = greater(Tw, -80)
        # default/missing SST values are 25F. Don't calculate there
        mask=(runEditAreaMask) & (SST > 25)

        # get wind grids and convert to m/s
        (mag_kt, dir) = Wind
        # convert to m/s
        mag = mag_kt * 0.514
#         print(mag)

        # Default freezing point of sea water
        Tf = -1.7

        # calculate the ship icing potential using the
        # algorithm developed by Overland
        Da = (Tf - Ta)
#         print(Da)
        Dw = (Tw - Tf)
#         print(Dw)
        ppr = ((mag * Da) / (1.0 + (0.3 * Dw)))
        
        #troubleshooting.
        x,y=self.getGridCell(38.81, -74.48)
        print("Inputs (Imperial): SST(F)={}, T(F)={}, Ws(kts)={}".format(SST[x][y], Temp[x][y], Wind[0][x][y]))
        print("Inputs (SI): SST(C)={}, T(C)={}, Ws(m/s)={}".format(Tw[x][y], Ta[x][y], mag[x][y]))
        print("Da (Tw- Ta): {}C, Dw (Tw-Tf) {}C, Result: {}".format(Da[x][y],Dw[x][y],ppr[x][y]))
        print("Done with Populate_IccAccretion smartTool")
        IceAccretion[mask]=ppr[mask]
        return(IceAccretion)
