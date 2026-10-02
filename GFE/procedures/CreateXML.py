# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# CreateXML.py
#
# Author: stephanie.stevenson
#
# Modification History:
# 4/25/26 by S.Williamson, updated to add Isobars and Features layers
# ----------------------------------------------------------------------------

# The MenuItems list defines the GFE menu item(s) under which the
# Procedure is to appear.
# Possible items are: Populate, Edit, Consistency, Verify, Hazards
MenuItems = ["Consistency"]

### If desired, Set up variables to be solicited from the user:
##  If your script calls Smart Tools, this VariableList should
##  cover all the variables necessary for the tools.

VariableList = [("Cycle:","00z","radio",["00z","06z","12z","18z"]),
                ("Area:","HS","radio",["HS","Reg"]),
                ("Product:","Surface","radio",["Surface","Wave"]),
                ("Fcst Hr:",["on"],"check",["F000","F024","F048","F072","F096"]),
                ("Input Grid:", "Fcst","radio",["Fcst","Official"])]#,"GFSwave"])] 

# Import python packages
import LogStream, time
from math import *
import time
from datetime import datetime, timedelta
import AbsTime, TimeRange
import SmartScript
import os
from A2GraphicsConfig import *
import A2GraphicsFunctions 
from A2GraphicsFunctions import MathUtils as MathUtils
from A2GraphicsFunctions import XmlUtils as XmlUtils
import numpy as np
from xml.dom import minidom
from xml.etree import ElementTree as ET

## For documentation on the available commands,
##   see the SmartScript Utility, which can be viewed from
##   the Edit Actions Dialog Utilities window

class Procedure (A2GraphicsFunctions.A2GraphicsFunctions):
    def __init__(self, dbss):
        A2GraphicsFunctions.A2GraphicsFunctions.__init__(self, dbss)
        A2GraphicsFunctions.MathUtils.__init__(self, dbss)
        A2GraphicsFunctions.XmlUtils.__init__(self, dbss)
        
    def execute(self, varDict):
    
        # Message to indicate start of procedure
        self.statusBarMsg("Starting CreateXML", "R")
        
        # Read data from user input
        input = varDict["Input Grid:"]
        area  = varDict["Area:"]
        prod  = varDict["Product:"]
        fhr   = varDict["Fcst Hr:"]
        cyc   = varDict["Cycle:"]
        
        # Set other variables based on environment
        basin = self.getSiteID()
        fcstr  = os.environ["USER"].split('.')[-1].upper()
        den = map_dict[basin]["den_ss"]
        den_ww = map_dict[basin]["den_warningwinds"]
        start_index1 = map_dict[basin]["start_index1_ss"]
        start_index2 = map_dict[basin]["start_index2_ss"]
        start_index1_wind = map_dict[basin]["start_index1_wind"]
        start_index2_wind = map_dict[basin]["start_index2_wind"]
        extra_pts = map_dict[basin]["extra_pts_ss"]
        
        # Get lat/lon grids
        lat, lon = self.getLatLonGrids()
                
        # Thin lat/lon 
        lat_flat = lat[start_index1::den,start_index2::den].flatten()
        lon_flat = lon[start_index1::den,start_index2::den].flatten()
        
        lat_flat_dens = lat[start_index1::den_ww,start_index2::den_ww].flatten()
        lon_flat_dens = lon[start_index1::den_ww,start_index2::den_ww].flatten()
        
        lat_flat_wind = lat[start_index1_wind::den,start_index2_wind::den].flatten()
        lon_flat_wind = lon[start_index1_wind::den,start_index2_wind::den].flatten()

        # Get indices of extra lat/lon points
        lat_p,lon_p,lat_p_ind,lon_p_ind=[],[],[],[]
        for p in extra_pts:
            outlat_p, outlat_p_ind = MathUtils.find_nearest(lat[:,0],p[0])
            outlon_p, outlon_p_ind = MathUtils.find_nearest(lon[0,:],p[1])
            self.statusBarMsg("outlon_p_ind: "+str(outlon_p_ind),"R")
            lat_p = np.append(lat_p, outlat_p)
            lon_p = np.append(lon_p, outlon_p)
            lat_p_ind = np.append(lat_p_ind, outlat_p_ind)
            lon_p_ind = np.append(lon_p_ind, outlon_p_ind)      

        # Throw an alertviz error and exit if user selected combo that is not a product in the prod_list
        for fhr_opt in fhr:
            
            combined_prod_name=cyc+"_"+area+"_"+prod+"_"+fhr_opt
            self.statusBarMsg("creating XML for "+combined_prod_name, "R")
            
            if combined_prod_name not in prod_list[basin]:
                valid_options = ",".join(prod_list[basin])
                error_message = f"ERROR: '{combined_prod_name}' is not a valid product for {basin}. Please choose from: {valid_options}"
                self.statusBarMsg(error_message, "S")
                return
        
            # Find the grid time    
            cycle_input = varDict["Cycle:"]
            cycle = int(cycle_input[:2])
            gridstart= MathUtils.findCycleDate(cycle)
        
            start_time=datetime.strptime(str(gridstart),"%Y%m%d%H")
            start_time=start_time+timedelta(hours=int(fhr_opt[-3:]))
            end_time=start_time+timedelta(hours=1)
            timeRange = TimeRange.TimeRange(AbsTime.AbsTime(start_time.timestamp()),AbsTime.AbsTime(end_time.timestamp()))
        
            # Read needed GFE fields
            if fhr_opt == "F000":
                ftype = "Anl"
            else: 
                ftype = "Fcst"
            
            # Set input to current model run if selected
            if input != "Fcst":
                input = self.findDatabase(input,0)
            
            gfe_fields = layer_dict[area+"_"+prod+"_"+ftype]["gfeFields"]
                
            for field in gfe_fields: 
                
                # Read WaveHeight grid in meters
                if field == "WaveHeight":
                    waveheight = self.getGrids(input,field,"SFC",timeRange)*0.3048
                # Read Wind grid in knots
                if field == "Wind":
                    wind = self.getGrids(input,field,"SFC",timeRange)
                    wind_mag = wind[0]
                    wind_dir = wind[1]
                # Read swell vector grids
                if field == "Swell":
                    swell = self.getGrids(input,field,"SFC",timeRange)
                    swell_mag = swell[0]
                    swell_dir = swell[1]
                # Read pmsl grid
                if field == "pmsl":
                    pmsl = self.getGrids(input,field,"SFC",timeRange)               
                    
            #self.statusBarMsg("max wind first "+str(np.max(wind_mag)), "R")
            # Set generic XML information based on product
            # Create shortcut to prod_dict
            pd = pgenProd_dict[basin]
            basin_long = pd["basin"]
            
            # Set output xml filename and activity type/subtype to be used by AWIPS storeActivty
            outputFile  = outDir+basin_long+"_"+area+"_"+prod+"_"+str(input)+"_"+gridstart+"_"+fhr_opt+".xml"
            typeSubtype = basin_long+"_"+area+"_"+prod+"("+fhr_opt+")"
        
            # Create XML product
            products,product = XmlUtils.createXmlProduct(outputFile,pd["useFile"],pd["saveLayers"],pd["onOff"],
                                                         pd["status"],pd["center"],fcstr,typeSubtype,typeSubtype)
        
            # Create necessary layers 
            layer_list = layer_dict[area+"_"+prod+"_"+ftype]["layers"]
      
            # Set layer name to Default if saveLayers is false
            if pd["saveLayers"] == "false":
                de = XmlUtils.createXmlLayer(product,"Default")
            
            for each_layer in layer_list:
                
                self.statusBarMsg("creating XML layer for "+each_layer, "R")
                
                # Generate waveheight contours and peak values
                if each_layer == "Wave_Heights":
                    # --- Set layer name and read PGEN attributes from config ---
                    if pd["saveLayers"] == "true":
                        de = XmlUtils.createXmlLayer(product,each_layer)
                    pa = pgenAttr_dict[each_layer]
                    cont_attr = pa["cont_attr"]
                    line_attr = pa["line_attr"]
                    line_color = pa["line_color"]
                    line_text_attr = pa["line_text_attr"]
                    line_text_color = pa["line_text_color"]
                    text_attr = pa["text_attr"]
                    text_color = pa["text_color"]
                    
                    # --- Mask waveheights out over Hudson Bay if Atlantic chart ---
                    if basin_long == "Atlantic":
                        runEditArea = self.getEditArea("Hudson_Bay")
                        baymask     = self.encodeEditArea(runEditArea)
                        waveheight[baymask] = 0
                    
                    # --- Contours ---
                    # Smooth waveheight and generate contours
                    wh_smooth = MathUtils.smoothWaveheight(waveheight)
                    con_info = MathUtils.makeWaveheightContours(lon,lat,wh_smooth,basin)
                    # Add contour lines and text to XML if desired
                    contourflag = layer_dict[area+"_"+prod+"_"+ftype]["plotContours"]
                    if contourflag == "y":
                        XmlUtils.xmladdWaveHeightContour(con_info,de,cont_attr,line_attr,line_color,line_text_attr,line_text_color)
                    
                    # --- Max value labels ---
                    # Find peaks in waveheight and ideal plotting location
                    peak_mean_lon,peak_mean_lat,peak_mean_value = MathUtils.findLocalMaxima(waveheight,lon,lat,2,5)
                    xml_peak_lon,xml_peak_lat,xml_peak_value    = XmlUtils.plotPeakLocations(peak_mean_lon,peak_mean_lat,peak_mean_value,basin)
                    
                    # Find minima in waveheight and ideal plotting location
                    #min_mean_lon,min_mean_lat,min_mean_value    = MathUtils.findLocalMinima(waveheight,lon,lat,3,5)
                    #xml_min_lon,xml_min_lat,xml_min_value       = MathUtils.plotPeakLocations(min_mean_lon,min_mean_lat,min_mean_value,basin)
                    
                    #for ss in peak_mean_lon:
                    #    self.statusBarMsg("xml_peak "+str(ss), "R")

                    # Add peak waveheight values to XML if desired
                    maxflag = layer_dict[area+"_"+prod+"_"+ftype]["plotMax"]
                    if maxflag != "n":
                        for flagstring in maxflag:
                            if flagstring == "y":
                                XmlUtils.xmladdWaveHeightPeak(xml_peak_value,xml_peak_lat,xml_peak_lon,de,text_attr,text_color)
                            if flagstring == str(fhr_opt):
                                XmlUtils.xmladdWaveHeightPeak(xml_peak_value,xml_peak_lat,xml_peak_lon,de,text_attr,text_color)
                        #XmlUtils.xmladdWaveHeightPeak(xml_min_value,xml_min_lat,xml_min_lon,de,text_attr,text_color)
                                        
                # Generate data for printed waveheight values    
                if each_layer == "Wave_Heights_Values":    
                    # --- Set layer name and read PGEN attributes from config ---
                    #if pd["saveLayers"] == "true":
                    #    de = XmlUtils.createXmlLayer(product,"Wave_Heights")
                    pa = pgenAttr_dict[each_layer]
                    text_attr = pa["text_attr"]
                    text_color= pa["text_color"]                    
                    # --- Printed values ---    
                    #wh_smooth_half_meter = np.char.mod('%.1f',(np.round(wh_smooth)*2)/2)
                    #wh_smooth_half_meter2 = ["" if wh_smooth_half_meter==0.0 else x for x in wh_smooth_half_meter]
                    #height_str = wh_smooth_half_meter

                    # Change waveheight to a string array and flatten for plotting
                    height_str = np.char.mod('%d',np.round(waveheight))
                    height_flat = height_str[start_index1::den,start_index2::den].flatten()
                    
                    # Add extra points if they are defined
                    lat_flat = np.append(lat_flat, lat_p)
                    lon_flat = np.append(lon_flat, lon_p)
                    for ind in zip(lat_p_ind,lon_p_ind):
                        height_flat = np.append(height_flat,height_str[int(ind[0]),int(ind[1])])
                    self.statusBarMsg("point height: "+str(lat_p)+","+str(lon_p), "R")

                    # Add text waveheight values to XML
                    XmlUtils.xmladdWaveHeightValues(height_flat,lat_flat,lon_flat,de,text_attr,text_color)

                # Generate disclaimer box in Wave_Misc layer
                if each_layer == "Wave_Misc":
                    if pd["saveLayers"] == "true":
                        de = XmlUtils.createXmlLayer(product,each_layer)
                    pa = pgenAttr_dict[each_layer]
                    text_attr = pa["text_attr"]
                    text_color= pa["text_color"] 
                    
                    disclaimer_flag = layer_dict[area+"_"+prod+"_"+ftype]["disclaimer"]
                    if disclaimer_flag == "y":
                        dtext = disclaimer_box_dict[basin][area+"_"+prod+"_"+ftype]["text"]
                        dlats = disclaimer_box_dict[basin][area+"_"+prod+"_"+ftype]["lat"]
                        dlons = disclaimer_box_dict[basin][area+"_"+prod+"_"+ftype]["lon"]
                        
                        for dlat,dlon in zip(dlats,dlons):
                            XmlUtils.xmladdTextBox(dtext,dlat,dlon,de,text_attr,text_color)

                # Generate data for swell arrows    
                if each_layer == "Swell":
                    # --- Set layer name and read PGEN attributes from config ---
                    if pd["saveLayers"] == "true":
                        de = XmlUtils.createXmlLayer(product,each_layer)
                    pa = pgenAttr_dict[each_layer]
                    vect_attr = pa["vect_attr"]
                    vect_color= pa["vect_color"]
                    # --- Set swell variables ---
                    swell_dir_flat = swell_dir[start_index1::den,start_index2::den].flatten()
                    swell_dir_rad_flat = swell_dir_rad[start_index1::den,start_index2::den].flatten()
                    swell_mag_flat = swell_mag[start_index1::den,start_index2::den].flatten()
                    # Add swell vectors to XML
                    XmlUtils.xmladdSwellArrows(swell_dir_flat,lat_flat,lon_flat,de,vect_attr,vect_color)
                
                # Generate data for wind barbs less than warning level
                if each_layer == "Winds":
                    # --- Mask winds to only over water ---
                    runEditArea = self.getEditArea("Land")
                    landmask    = self.encodeEditArea(runEditArea)
                    wind_mag[landmask] = 0
                    wind_dir[landmask] = 0
                    # --- Mask winds out over Hudson Bay if Atlantic chart ---
                    if basin_long == "Atlantic":
                        runEditArea = self.getEditArea("Hudson_Bay")
                        baymask     = self.encodeEditArea(runEditArea)
                        wind_mag[baymask] = 0
                        wind_dir[baymask] = 0
                    # --- Remove winds above warning criteria
                    wind_mag_mask = np.where(wind_mag >= 34, 0, wind_mag)
                    # --- Set layer name and read PGEN attributes from config ---
                    if pd["saveLayers"] == "true":
                        de = XmlUtils.createXmlLayer(product,each_layer)
                    pa = pgenAttr_dict[each_layer]
                    vect_attr = pa["vect_attr"]
                    vect_color= pa["vect_color"]
                    # --- Set wind variables ---
                    wind_dir_flat = wind_dir[start_index1_wind::den,start_index2_wind::den].flatten()
                    wind_mag_flat = wind_mag_mask[start_index1_wind::den,start_index2_wind::den].flatten()
                    # Add wind barbs to XML
                    XmlUtils.xmladdWindBarbs(wind_mag_flat,wind_dir_flat,lat_flat_wind,lon_flat_wind,de,vect_attr,vect_color)
                    
                # Generate data for wind barbs
                if each_layer == "Warning_Winds":
                    #--- Check if we want to create Warning_Winds for this fhr
                    wwhours = layer_dict[area+"_"+prod+"_"+ftype]["warningWinds"]
                    
                    for wwhour in wwhours:
                        if wwhour == str(fhr_opt):
                            # --- Mask winds to only over water ---
                            runEditArea = self.getEditArea("Land")
                            landmask    = self.encodeEditArea(runEditArea)
                            wind_mag[landmask] = 0
                            wind_dir[landmask] = 0
                            # --- Remove winds below warning criteria 
                            #self.statusBarMsg("max wind "+str(np.max(wind_mag)), "R")
                            wind_mag_mask_warning = np.where(wind_mag < 34, 0, wind_mag)
                            self.statusBarMsg("max wind "+str(np.max(wind_mag_mask_warning)), "R")
                            # --- Set layer name and read PGEN attributes from config ---
                            if pd["saveLayers"] == "true":
                                de = XmlUtils.createXmlLayer(product,each_layer)
                            pa = pgenAttr_dict[each_layer]
                            vect_attr = pa["vect_attr"]
                            vect_color= pa["vect_color"]
                            # --- Set wind variables ---
                            wind_dir_flat = wind_dir[start_index1::den_ww,start_index2::den_ww].flatten()
                            wind_mag_flat = wind_mag_mask_warning[start_index1::den_ww,start_index2::den_ww].flatten()
                            # Add wind barbs to XML
                            XmlUtils.xmladdWindBarbs(wind_mag_flat,wind_dir_flat,lat_flat_dens,lon_flat_dens,de,vect_attr,vect_color)

                # Generate pressure contours and contour labels
                if each_layer == "Isobars":
                    # --- Set layer name and read PGEN attributes from config ---
                    if pd["saveLayers"] == "true":
                        de = XmlUtils.createXmlLayer(product,each_layer)
                    pa = pgenAttr_dict[each_layer]
                    cont_attr = pa["cont_attr"]
                    line_attr = pa["line_attr"]
                    line_color = pa["line_color"]
                    line_text_attr = pa["line_text_attr"]
                    line_text_color = pa["line_text_color"]

                    # --- Contours ---
                    # Smooth pressure and generate contours
                    pmsl_smooth = MathUtils.smoothPressure(pmsl)
                    con_info    = MathUtils.makePressureContours(lon,lat,pmsl_smooth,basin)
                    # Add contour lines and text to XML
                    XmlUtils.xmladdPressureContour(con_info,de,cont_attr,line_attr,line_color,line_text_attr,line_text_color)

                # Generate pressure extrema (Highs/Lows) and labels
                if each_layer == "Features":
                    # --- Set layer name and read PGEN attributes from config ---
                    if pd["saveLayers"] == "true":
                        de = XmlUtils.createXmlLayer(product,each_layer)
                    pa = pgenAttr_dict[each_layer]
                    high_attr = pa["high_attr"]
                    high_color = pa["high_color"]
                    low_attr = pa["low_attr"]
                    low_color = pa["low_color"]
                    text_attr = pa["text_attr"]
                    text_color = pa["text_color"]

                    # --- Pressure maximums (Highs) and labels ---
                    # Find Highs in pressure and ideal plotting locations
                    peak_mean_lon,peak_mean_lat,peak_mean_value = MathUtils.findPressureExtrema(pmsl,lon,lat,type="Max")
                    xml_peak_lon,xml_peak_lat,xml_peak_value    = XmlUtils.plotPeakPressureLocations(peak_mean_lon,peak_mean_lat,peak_mean_value,basin)
                    # Add High pressure symbols and labels to XML
                    XmlUtils.xmladdPressureSymbol(xml_peak_value,xml_peak_lat,xml_peak_lon,de,high_attr,high_color)
                    XmlUtils.xmladdPressureExtremaLabel(xml_peak_value,xml_peak_lat,xml_peak_lon,de,text_attr,text_color)     
                    # --- Pressure minimums (Lows) and labels ---
                    # Find Lows in pressure and ideal plotting locations
                    valley_mean_lon,valley_mean_lat,valley_mean_value = MathUtils.findPressureExtrema(pmsl,lon,lat,type="Min")
                    xml_valley_lon,xml_valley_lat,xml_valley_value    = XmlUtils.plotPeakPressureLocations(valley_mean_lon,valley_mean_lat,valley_mean_value,basin)
                    # Add Low pressure symbols to XML and labels
                    XmlUtils.xmladdPressureSymbol(xml_valley_value,xml_valley_lat,xml_valley_lon,de,low_attr,low_color)
                    XmlUtils.xmladdPressureExtremaLabel(xml_valley_value,xml_valley_lat,xml_valley_lon,de,text_attr,text_color)
                    
          
            # Write XML to a file
            XmlUtils.writeXML(products,outputFile)

            # Store XML to PGEN database
            XmlUtils.storeXML(outputFile) 

            # Attempt to delete XML files older than 7 days
            one_week_ago = time.time() - (24 * 60 * 60 * 7)
            for filename in os.listdir(outDir):
                file_path = os.path.join(outDir,filename)

                if os.path.isfile(file_path):
                    try:
                        if os.path.getmtime(file_path) < one_week_ago:
                            os.remove(file_path)
                            print(f"Successfully deleted: {filename}")
                    except Exception as e:
                        print(f"Skipped {filename} due to error: {e}")

        return

