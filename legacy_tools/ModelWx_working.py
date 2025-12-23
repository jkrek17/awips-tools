"""
================================================================================
MARINE WEATHER GRID BUILDER
================================================================================

Description:
    Comprehensive weather grid creation tool for AWIPS GFE that builds Wx grids
    from atmospheric model data including precipitation, thunderstorms, and fog.
    
    Automatically determines weather qualifiers (Coverage vs Probability terms)
    based on convective conditions using CAPE and wind data.

Features:
    - Multi-model ensemble support (GFS, ECMWF, CMC, UKMET)
    - Automatic qualifier determination (convective vs stratiform)
    - Spatial smoothing and configurable thresholds
    - Diagnostic grid output (QPF, CAPE, Temperature, RH, Visibility, etc.)
    - Uses SFC Wind Fcst grid for consistency with forecast operations

Data Sources:
    - Atmospheric Models: D2D_ databases (temperature, RH, QPF, visibility, CAPE)
    - Wind: SFC Wind Fcst grid from Fcst database (in knots)

Version History:
    v2.0 - 2025-11-04
        - Modified to use SFC Wind Fcst grid (knots) instead of 1000mb model wind
        - Improved consistency with operational forecast grids
        - Simplified wind data handling
    
    v1.0 - Initial release
        - Basic multi-model weather grid builder

Author: [Your Name/Office]
Contact: [Your Contact Info]

================================================================================
"""

MenuItems = ["Populate"]
import time, calendar
import bisect
import numpy as np
import tkinter as tk
import SmartScript
from scipy import ndimage
import datetime as dt
from shapely.geometry import box
from ufpy.dataaccess import DataAccessLayer

# Import WxMethods - same pattern as working thunder tool
from WxMethods import *

# Empty VariableList since we're using custom GUI
VariableList = []

################################################################################
# CONFIGURATION SECTION - Tunable Parameters
################################################################################
"""
Adjust these values to fine-tune the weather grid builder behavior.
All thresholds and parameters are defined here for easy maintenance.
"""

class CONFIG:
    """Configuration parameters for Marine Weather Grid Builder"""
    
    # ==================== PRECIPITATION THRESHOLDS ====================
    # QPF thresholds in inches (for 3-hour periods typically)
    QPF_MINIMUM = 0.01          # Minimum QPF to consider precipitation (inches)
    
    # QPF thresholds for intensity determination (3-hour period)
    QPF_HEAVY = 1.0             # Heavy intensity threshold (inches)
    QPF_MODERATE = 0.5          # Moderate intensity threshold (inches)
    QPF_LIGHT = 0.1             # Light intensity threshold (inches)
    
    # QPF thresholds for coverage/probability terms
    QPF_WIDE_COVERAGE = 1.0     # Wide coverage threshold (inches)
    QPF_NUMEROUS = 0.5          # Numerous coverage threshold (inches)
    QPF_SCATTERED = 0.1         # Scattered coverage threshold (inches)
    # Below SCATTERED = Isolated
    
    # QPF thresholds for probability terms (stratiform)
    QPF_DEFINITE = 1.0          # Definite probability threshold (inches)
    QPF_LIKELY = 0.5            # Likely probability threshold (inches)
    QPF_CHANCE = 0.1            # Chance probability threshold (inches)
    # Below CHANCE = Slight Chance
    
    # ==================== THUNDER/CONVECTION THRESHOLDS ====================
    # CAPE thresholds in J/kg
    CAPE_THUNDER_MIN = 500      # Minimum CAPE for thunder (J/kg)
    CAPE_SEVERE_MIN = 3000      # Minimum CAPE for severe thunder (J/kg)
    CAPE_HIGH = 2000            # High CAPE for scattered thunder (J/kg)
    CAPE_MODERATE = 1000        # Moderate CAPE for isolated thunder (J/kg)
    
    # Convective Index threshold
    # Index = (CAPE/1000) + (WindSpeed_ms/20)
    CONVECTIVE_THRESHOLD = 2.0  # Above = convective/coverage, Below = stratiform/probability
    
    # Heavy precipitation with thunder threshold (suggests severe)
    QPF_SEVERE_WITH_THUNDER = 1.0  # Heavy precip + thunder (inches in 3 hours)
    
    # ==================== FOG THRESHOLDS ====================
    FOG_RH_MIN = 85             # Minimum RH for fog (%)
    FOG_VIS_DEFAULT = 3.0       # Default visibility threshold for fog (SM)
    FOG_VIS_MIN = 0.5           # Minimum configurable fog threshold (SM)
    FOG_VIS_MAX = 6.0           # Maximum configurable fog threshold (SM)
    
    # ==================== TEMPERATURE THRESHOLDS ====================
    # Temperature thresholds in Celsius
    TEMP_FREEZING = 0.0         # Freezing point - determines rain vs snow (C)
    
    # ==================== SMOOTHING PARAMETERS ====================
    SMOOTHING_DEFAULT = 2       # Default smoothing factor (0-5)
    SMOOTHING_MIN = 0           # Minimum smoothing (0 = none)
    SMOOTHING_MAX = 5           # Maximum smoothing (5 = heavy)
    SMOOTHING_SIGMA = 0.7       # Gaussian sigma multiplier
    
    # ==================== DIAGNOSTIC GRID CLIPPING ====================
    # Reasonable ranges for diagnostic grid outputs
    QPF_MAX_CLIP = 10.0         # Maximum QPF for diagnostic grid (inches)
    CAPE_MAX_CLIP = 8000.0      # Maximum CAPE for diagnostic grid (J/kg)
    TEMP_MIN_CLIP = -50.0       # Minimum temperature for diagnostic grid (F)
    TEMP_MAX_CLIP = 150.0       # Maximum temperature for diagnostic grid (F)
    RH_MIN_CLIP = 0.0           # Minimum RH for diagnostic grid (%)
    RH_MAX_CLIP = 100.0         # Maximum RH for diagnostic grid (%)
    VIS_MIN_CLIP = 0.0          # Minimum visibility for diagnostic grid (SM)
    VIS_MAX_CLIP = 10.0         # Maximum visibility for diagnostic grid (SM)
    WIND_MIN_CLIP = 0.0         # Minimum wind speed for diagnostic grid (kt)
    WIND_MAX_CLIP = 150.0       # Maximum wind speed for diagnostic grid (kt)
    CONV_INDEX_MIN = 0.0        # Minimum convective index for diagnostic grid
    CONV_INDEX_MAX = 10.0       # Maximum convective index for diagnostic grid
    
    # ==================== DEFAULT MODEL SELECTIONS ====================
    DEFAULT_MODELS = ["GFS"]    # Models selected by default in GUI
    
    # ==================== DATA ACCESS LAYER MODEL SETTINGS ====================
    # Configure the DAL location/level and parameter names for each supported model.
    # Parameter names can vary between model databases, so keep them centralized here.
    # Keys must match the model identifiers used elsewhere (e.g., GUI selection strings).
    MODEL_DAL_SETTINGS = {
        "GFS": {
            "location": "gfs0p25",
            "level": "0.0SFC",
            "parameters": {
                "QPF": "TP3hr",
                "CAPE": "SBCAPE",
            },
        },
        "nECMWF0p25": {
            "location": "ecmwf0p25",
            "level": "0.0SFC",
            "parameters": {
                "QPF": "TP3hr",
                "CAPE": "SBCAPE",
            },
        },
        "CMCnh": {
            "location": "Canadian-NH",
            "level": "0.0SFC",
            "parameters": {
                "QPF": "TP3hr",
                "CAPE": "SBCAPE",
            },
        },
    }
    
    # ==================== UNIT CONVERSION CONSTANTS ====================
    # These should generally not be changed
    MM_TO_INCHES = 25.4         # Millimeters to inches conversion
    M_TO_SM = 0.000621371       # Meters to statute miles conversion
    KT_TO_MS = 0.514444         # Knots to meters/second conversion
    C_TO_F_MULT = 9.0/5.0       # Celsius to Fahrenheit multiplier
    C_TO_F_ADD = 32.0           # Celsius to Fahrenheit offset
    MS_TO_KT = 1.94384          # Meters/second to knots conversion

################################################################################
# END CONFIGURATION SECTION
################################################################################

class ResultsPopup:
    def __init__(self, master, title, output_text):
        self.master = master
        self.master.title(title)
        self.master.geometry("900x700")
        
        # Main frame
        mainFrame = tk.Frame(self.master, padx=10, pady=10)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title label
        titleLabel = tk.Label(mainFrame, text=title, 
                             font=("Arial", 14, "bold"))
        titleLabel.pack(pady=(0, 10))
        
        # Text widget with scrollbar
        textFrame = tk.Frame(mainFrame)
        textFrame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(textFrame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.textWidget = tk.Text(textFrame, wrap=tk.WORD, 
                                  yscrollcommand=scrollbar.set,
                                  font=("Courier", 9))
        self.textWidget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.textWidget.yview)
        
        # Insert output text
        self.textWidget.insert(tk.END, output_text)
        self.textWidget.config(state=tk.DISABLED)  # Make read-only
        
        # Button frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(buttonFrame, text="Close", command=self.master.destroy,
                 font=("Arial", 11), width=15).pack(side=tk.RIGHT)
        
        tk.Button(buttonFrame, text="Copy to Clipboard", command=self.copyToClipboard,
                 font=("Arial", 11), width=20).pack(side=tk.RIGHT, padx=(0, 10))
    
    def copyToClipboard(self):
        """Copy text to clipboard"""
        self.master.clipboard_clear()
        self.master.clipboard_append(self.textWidget.get("1.0", tk.END))

class Marine_Weather_GUI:
    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Weather Grid Builder")
        self.master.geometry("700x950")
        self.master.resizable(True, True)
        
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
            self.messageLabel.config(text="Ready to build weather grids", fg="green")
        
    def createWidgets(self):
        # Main frame
        mainFrame = tk.Frame(self.master, padx=15, pady=15)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Marine Weather Grid Builder v2.0", 
                             font=("Arial", 16, "bold"))
        titleLabel.pack(pady=(0, 5))
        
        # Description
        descLabel = tk.Label(mainFrame, 
                           text="Comprehensive weather grid creation from atmospheric models\nPrecipitation • Thunderstorms • Fog",
                           font=("Arial", 10), fg="gray", justify=tk.CENTER)
        descLabel.pack(pady=(0, 15))
        
        # Model Selection Frame
        modelFrame = tk.LabelFrame(mainFrame, text="Select Atmospheric Models", padx=15, pady=10)
        modelFrame.pack(fill=tk.X, pady=(0, 10))
        
        # Create status labels first
        self.statusLabel = tk.Label(modelFrame, text="No Models Selected", 
                                  font=("Arial", 11, "bold"), fg="red")
        self.statusLabel.pack(side=tk.BOTTOM, pady=(10, 0))
        
        self.messageLabel = tk.Label(modelFrame, text="Select at least one atmospheric model", 
                                   font=("Arial", 9), fg="red")
        self.messageLabel.pack(side=tk.BOTTOM)
        
        # Atmospheric model definitions
        atmModels = [
            ("GFS (Global Forecast System)", "GFS"),
            ("ECMWF (European Centre)", "nECMWF0p25"),
            ("CMC (Canadian Global)", "CMCnh"),
            ("UKMET (UK Met Office)", "UKMEThires4")
        ]
        
        self.modelSelections = {}
        
        tk.Label(modelFrame, text="Atmospheric Models:", 
                font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        
        for displayName, modelId in atmModels:
            var = tk.StringVar()
            var.set("No")
            self.modelSelections[modelId] = var
            
            cb = tk.Checkbutton(modelFrame, text=displayName, 
                              variable=var, onvalue="Yes", offvalue="No",
                              command=self.updateSelection, anchor=tk.W, font=("Arial", 10))
            cb.pack(fill=tk.X, pady=2)
        
        # Set default selection(s)
        for model in CONFIG.DEFAULT_MODELS:
            if model in self.modelSelections:
                self.modelSelections[model].set("Yes")
        
        # Update status to reflect default selections
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        self.statusLabel.config(text=f"{selectedCount} Model(s) Selected", fg="green")
        self.messageLabel.config(text="Ready to build weather grids", fg="green")
        
        # Build Mode Frame
        modeFrame = tk.LabelFrame(mainFrame, text="Build Mode", padx=15, pady=10)
        modeFrame.pack(fill=tk.X, pady=(0, 10))
        
        self.buildMode = tk.StringVar()
        self.buildMode.set("Build New (Replace All)")
        
        tk.Radiobutton(modeFrame, text="Build New (Replace All)", 
                      variable=self.buildMode, value="Build New (Replace All)",
                      font=("Arial", 10)).pack(anchor=tk.W)
        tk.Label(modeFrame, text="   • Completely replaces existing weather grid",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W)
        
        tk.Radiobutton(modeFrame, text="Enhance Existing", 
                      variable=self.buildMode, value="Enhance Existing",
                      font=("Arial", 10)).pack(anchor=tk.W, pady=(5,0))
        tk.Label(modeFrame, text="   • Adds/updates weather while preserving other types",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W)
        
        # Parameters Frame
        paramFrame = tk.LabelFrame(mainFrame, text="Analysis Parameters", padx=15, pady=10)
        paramFrame.pack(fill=tk.X, pady=(0, 10))
        
        # Info about automatic qualifier determination
        tk.Label(paramFrame, text="Weather Qualifier Type: AUTOMATIC", 
                font=("Arial", 10, "bold")).pack(anchor=tk.W)
        tk.Label(paramFrame, text="  Convective conditions → Coverage terms (Iso, Sct, Num, Wide)",
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(paramFrame, text="  Stratiform conditions → Probability terms (Chc, Lkly, Def)",
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0), pady=(0, 10))
        
        # Smoothing
        tk.Label(paramFrame, text="Spatial Smoothing:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.smoothing = tk.IntVar()
        self.smoothing.set(CONFIG.SMOOTHING_DEFAULT)
        smoothScale = tk.Scale(paramFrame, from_=CONFIG.SMOOTHING_MIN, to=CONFIG.SMOOTHING_MAX, 
                              orient=tk.HORIZONTAL, variable=self.smoothing, length=200)
        smoothScale.pack(anchor=tk.W, padx=(20, 0))
        tk.Label(paramFrame, text=f"{CONFIG.SMOOTHING_MIN}=None • {CONFIG.SMOOTHING_DEFAULT}=Recommended • {CONFIG.SMOOTHING_MAX}=Heavy",
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Thunder CAPE threshold
        tk.Label(paramFrame, text="\nThunder CAPE Threshold (J/kg):", 
                font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5, 0))
        self.thunderThreshold = tk.IntVar()
        self.thunderThreshold.set(CONFIG.CAPE_THUNDER_MIN)
        thunderScale = tk.Scale(paramFrame, from_=100, to=2000, resolution=50,
                               orient=tk.HORIZONTAL, variable=self.thunderThreshold, length=220)
        thunderScale.pack(anchor=tk.W, padx=(20, 0))
        tk.Label(paramFrame, text="Lower = more thunder detections • Higher = fewer",
                font=("Arial", 8), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Fog threshold
        tk.Label(paramFrame, text="\nFog Visibility Threshold (SM):", 
                font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5, 0))
        self.fogThreshold = tk.DoubleVar()
        self.fogThreshold.set(CONFIG.FOG_VIS_DEFAULT)
        fogScale = tk.Scale(paramFrame, from_=CONFIG.FOG_VIS_MIN, to=CONFIG.FOG_VIS_MAX, 
                           resolution=0.5, orient=tk.HORIZONTAL,
                           variable=self.fogThreshold, length=200)
        fogScale.pack(anchor=tk.W, padx=(20, 0))
        
        # Model Run Selection
        tk.Label(paramFrame, text="\nModel Run:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5, 0))
        self.modelRun = tk.StringVar()
        self.modelRun.set("Current")
        
        runFrame = tk.Frame(paramFrame)
        runFrame.pack(fill=tk.X, padx=(20, 0))
        
        tk.Radiobutton(runFrame, text="Current Run", variable=self.modelRun, 
                      value="Current", font=("Arial", 9)).pack(side=tk.LEFT)
        tk.Radiobutton(runFrame, text="Previous Run", variable=self.modelRun, 
                      value="Previous", font=("Arial", 9)).pack(side=tk.LEFT, padx=(20, 0))
        
        # Diagnostic Options
        tk.Label(paramFrame, text="\nCreate Diagnostic Grids:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5, 0))
        self.createDiagnostics = tk.StringVar()
        self.createDiagnostics.set("No")
        
        diagFrame = tk.Frame(paramFrame)
        diagFrame.pack(fill=tk.X, padx=(20, 0))
        
        tk.Radiobutton(diagFrame, text="No", variable=self.createDiagnostics, 
                      value="No", font=("Arial", 9)).pack(side=tk.LEFT)
        tk.Radiobutton(diagFrame, text="Yes (QPF, CAPE, Temp, RH, Vis, ConvIndex)", variable=self.createDiagnostics, 
                      value="Yes", font=("Arial", 9)).pack(side=tk.LEFT, padx=(20, 0))
        
        # Status Frame
        self.statusMessageLabel = tk.Label(mainFrame, text="Ready to build weather grids",
                                          font=("Arial", 10), fg="green")
        self.statusMessageLabel.pack(pady=(10, 0))
        
        # Buttons Frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(buttonFrame, text="Build Weather Grids", command=self.runTool, 
                 bg="lightblue", font=("Arial", 11, "bold"), width=20).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(buttonFrame, text="Cancel", command=self.cancel, 
                 font=("Arial", 11), width=12).pack(side=tk.LEFT)
    
    def getValues(self):
        """Return dictionary of selected options"""
        selectedModels = []
        for modelId, var in self.modelSelections.items():
            if var.get() == "Yes":
                selectedModels.append(modelId)
        
        return {
            "Atmospheric Models": selectedModels,
            "Build Mode": self.buildMode.get(),
            "Spatial Smoothing": self.smoothing.get(),
            "Thunder CAPE Threshold": self.thunderThreshold.get(),
            "Fog Visibility Threshold": self.fogThreshold.get(),
            "Model Run": self.modelRun.get(),
            "Create Diagnostic Grids": self.createDiagnostics.get()
        }
    
    def runTool(self):
        """Validate and run the tool"""
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        if selectedCount == 0:
            self.messageLabel.config(text="ERROR: Select at least 1 model!", fg="red")
            self.master.after(3000, lambda: self.updateSelection())
            return
        
        self.callback(self.getValues())
        self.master.destroy()

    def cancel(self):
        """Close without running"""
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        
        # Define weather type priority
        self.wxPriority = {
            'T': 100,      # Thunder (highest)
            'RW': 90,      # Rain showers
            'R': 80,       # Rain
            'ZR': 85,      # Freezing rain
            'S': 75,       # Snow
            'F': 20,       # Fog (lowest, can combine with precip)
        }
        
        # Initialize output collector
        self.outputLog = []
        # Cache for DAL model fields (QPF/CAPE)
        self.dal_model_data = {}
        # Default thunder CAPE threshold (can be overridden via GUI)
        self.thunderThresholdValue = CONFIG.CAPE_THUNDER_MIN
    
    def _time_object_to_unix(self, time_obj):
        """Best-effort conversion of AWIPS time objects to a Unix timestamp."""
        if time_obj is None:
            return None
        try:
            if callable(time_obj):
                time_obj = time_obj()
            if hasattr(time_obj, "unixTime"):
                return time_obj.unixTime()
            if hasattr(time_obj, "getTimeInMillis"):
                return time_obj.getTimeInMillis() / 1000.0
            if hasattr(time_obj, "getTimeInSeconds"):
                return time_obj.getTimeInSeconds()
            if hasattr(time_obj, "getTime"):
                val = time_obj.getTime()
                if isinstance(val, (int, float)):
                    return val / 1000.0 if val > 1e12 else val
            if isinstance(time_obj, dt.datetime):
                return calendar.timegm(time_obj.utctimetuple())
        except Exception:
            return None
        return None

    def _geometry_to_numpy(self, grid, model_id, parm):
        """Extract numpy array from a DAL geometry grid using any available accessor."""
        accessors = [
            "getRawData",
            "getFloatData",
            "getDoubleData",
            "getIntData",
            "getShortData",
            "getByteData",
            "getNdArray",
            "getData",
        ]
        for accessor in accessors:
            attr = getattr(grid, accessor, None)
            if not attr:
                continue
            try:
                data = attr() if callable(attr) else attr
                arr = np.array(data, dtype=np.float32)
                return arr
            except Exception:
                continue
        attr_summary = [name for name in dir(grid) if not name.startswith("_")]
        self.log(f"ERROR: DAL {model_id}/{parm}: no supported data accessor ({accessors}), "
                 f"class={grid.__class__.__name__}, attrs sample={attr_summary[:20]}")
        return None

    def _get_valid_start_unix(self, data_time):
        """Extract the valid start time (unix seconds) from a DataTime-like object."""
        if data_time is None:
            return None
        valid_start = None
        valid_period = getattr(data_time, "getValidPeriod", None)
        if valid_period:
            try:
                vp = valid_period() if callable(valid_period) else valid_period
                start = getattr(vp, "getStart", None)
                if start:
                    start_obj = start() if callable(start) else start
                    valid_start = self._time_object_to_unix(start_obj)
            except Exception:
                valid_start = None
        if valid_start is None:
            match_valid = getattr(data_time, "getMatchValidTime", None)
            if match_valid:
                valid_start = self._time_object_to_unix(match_valid)
        if valid_start is None:
            ref_time = getattr(data_time, "getRefTime", None)
            if ref_time:
                valid_start = self._time_object_to_unix(ref_time)
        return valid_start
    
    def log(self, message):
        """Log message to both console and output collector"""
        print(message)
        self.outputLog.append(message)
    
    def showResultsPopup(self, title, periods_processed, total_periods):
        """Show results in popup window"""
        # Build summary
        summary = []
        summary.append("="*80)
        summary.append("MARINE WEATHER BUILDER v2.0 - EXECUTION SUMMARY")
        summary.append("="*80)
        summary.append(f"\nPeriods Processed: {periods_processed}/{total_periods}")
        
        if periods_processed > 0:
            summary.append(f"Status: SUCCESS ✓")
        else:
            summary.append(f"Status: FAILED - No periods processed")
        
        summary.append("\n" + "="*80)
        summary.append("DETAILED OUTPUT")
        summary.append("="*80 + "\n")
        
        # Combine summary with detailed log
        full_output = "\n".join(summary) + "\n".join(self.outputLog)
        
        # Show popup
        root = tk.Tk()
        popup = ResultsPopup(root, title, full_output)
        root.mainloop()

    # -------------------------------------------------------------------------
    # Data Access Layer helpers
    # -------------------------------------------------------------------------
    def _build_domain_envelope(self):
        """Create a shapely envelope covering the current forecast domain."""
        try:
            try:
                # Legacy SmartScript API signature is getLatLonGrids()
                lat_grid, lon_grid = self.getLatLonGrids()
            except TypeError:
                # Some sites still expose getLatLonGrids(databaseID)
                lat_grid, lon_grid = self.getLatLonGrids("Fcst")

            lat_vals = np.array(lat_grid, dtype=np.float64)
            lon_vals = np.array(lon_grid, dtype=np.float64)
            lat_min = np.nanmin(lat_vals)
            lat_max = np.nanmax(lat_vals)
            lon_min = np.nanmin(lon_vals)
            lon_max = np.nanmax(lon_vals)
            self.log(f"DAL envelope lat[{lat_min:.2f},{lat_max:.2f}] "
                     f"lon[{lon_min:.2f},{lon_max:.2f}]")
            return box(lon_min, lat_min, lon_max, lat_max)
        except Exception as e:
            self.log(f"ERROR: Unable to build DAL envelope from lat/lon grids: {str(e)}")
            # Fall back to global extent if domain lookup fails
            return box(-180.0, -90.0, 180.0, 90.0)

    def _retrieve_dal_model_fields(self, timeRange, target_times_unix=None):
        """
        Retrieve QPF and CAPE grids using the Data Access Layer for configured models.
        Returns dict keyed by model id -> parameter -> {valid_dt: numpy array}
        """
        dal_settings = CONFIG.MODEL_DAL_SETTINGS
        parameter_keys = ["QPF", "CAPE"]
        results = {model: {parm: {} for parm in parameter_keys} for model in dal_settings}
        envelope = self._build_domain_envelope()

        target_list = sorted(set(target_times_unix)) if target_times_unix else []
        tolerance = getattr(CONFIG, "DAL_TIME_MATCH_TOLERANCE_SEC", 3 * 3600)

        for model_id, cfg in dal_settings.items():
            params_map = cfg.get("parameters", {})
            for parm in parameter_keys:
                parm_name = params_map.get(parm)
                if not parm_name:
                    continue
                req = DataAccessLayer.newDataRequest()
                req.setDatatype("grid")
                req.setLocationNames(cfg.get("location"))
                req.setParameters(parm_name)
                req.setLevels(cfg.get("level"))
                if envelope is not None:
                    req.setEnvelope(envelope)
                try:
                    available_times = DataAccessLayer.getAvailableTimes(req)
                except Exception as e:
                    self.log(f"ERROR: DAL {model_id}/{parm} ({parm_name}) available times failed: {str(e)}")
                    continue

                if not available_times:
                    self.log(f"DAL {model_id}/{parm} ({parm_name}): no available times")
                    continue

                time_entries = []
                for dt_entry in available_times:
                    start_unix = self._get_valid_start_unix(dt_entry)
                    if start_unix is not None:
                        time_entries.append((dt_entry, start_unix))
                if not time_entries:
                    self.log(f"DAL {model_id}/{parm} ({parm_name}): times lacked valid start info")
                    continue

                time_entries.sort(key=lambda x: x[1])
                times_to_request = []
                if target_list:
                    for dt_entry, start_unix in time_entries:
                        idx = bisect.bisect_left(target_list, start_unix)
                        diffs = []
                        if idx < len(target_list):
                            diffs.append(abs(target_list[idx] - start_unix))
                        if idx > 0:
                            diffs.append(abs(target_list[idx - 1] - start_unix))
                        min_diff = min(diffs) if diffs else None
                        if min_diff is not None and min_diff <= tolerance:
                            times_to_request.append(dt_entry)
                if not times_to_request:
                    times_to_request = [dt_entry for dt_entry, _ in time_entries]
                max_samples = getattr(CONFIG, "DAL_MAX_TIME_SAMPLES", None)
                if max_samples and len(times_to_request) > max_samples:
                    times_to_request = times_to_request[-max_samples:]
                try:
                    data = DataAccessLayer.getGeometryData(req, times_to_request)
                    self.log(f"DAL {model_id}/{parm} ({parm_name}): retrieved {len(data)} grids "
                             f"(from {len(time_entries)} available times)")
                except Exception as e:
                    self.log(f"ERROR: DAL {model_id}/{parm} ({parm_name}) request failed: {str(e)}")
                    continue

                for grid in data or []:
                    try:
                        data_time = grid.getDataTime()
                        valid_start = self._get_valid_start_unix(data_time)
                        if valid_start is None:
                            self.log(f"ERROR: DAL {model_id}/{parm}: unable to determine valid time, skipping grid")
                            continue
                        valid_dt = dt.datetime.utcfromtimestamp(valid_start)
                        arr = self._geometry_to_numpy(grid, model_id, parm)
                        if arr is None:
                            continue
                        arr = np.where(np.isfinite(arr), arr, np.nan)
                        if parm == "QPF":
                            arr = arr / CONFIG.MM_TO_INCHES  # convert mm to inches
                        results[model_id][parm][valid_dt] = arr
                    except Exception as e:
                        self.log(f"ERROR: DAL {model_id}/{parm} grid parse error: {str(e)}")
                        continue
        return results

    def _get_dal_field_array(self, model_id, parameter, gridTimeRange):
        """Return DAL grid array for requested model/parameter/time or None."""
        model_store = self.dal_model_data.get(model_id)
        if not model_store:
            return None
        param_store = model_store.get(parameter)
        if not param_store:
            return None
        try:
            target_ts = gridTimeRange.startTime().unixTime()
        except AttributeError:
            return None
        target_dt = dt.datetime.utcfromtimestamp(target_ts)
        if target_dt in param_store:
            return param_store[target_dt]
        # Allow small timing mismatch (e.g., 1-3 hours)
        best_dt = None
        best_diff = None
        for valid_dt in param_store.keys():
            diff = abs((valid_dt - target_dt).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_dt = valid_dt
        if best_dt is not None and best_diff is not None and best_diff <= 3 * 3600:
            return param_store[best_dt]
        return None

    def showGUI(self, editArea, timeRange):
        """Show the custom GUI"""
        self.log("Showing GUI...")
        self.editArea = editArea
        self.timeRange = timeRange
        self.varDict = None
        
        root = tk.Tk()
        gui = Marine_Weather_GUI(root, self.guiCallback)
        root.mainloop()
        
        return self.varDict
    
    def guiCallback(self, values):
        """Callback from GUI"""
        self.varDict = values

    def buildWxKey(self, coverage, wxType, intensity, visibility="<NoVis>"):
        """Build weather key with 4 fields plus trailing colon"""
        # Format: Coverage:Type:Intensity:Visibility: (with trailing colon)
        return f"{coverage}:{wxType}:{intensity}:{visibility}:"
    
    def validateWxString(self, wxString):
        """Ensure weather string has exactly 4 fields with trailing colon, NO attributes"""
        # Split on ^ for multiple weather types
        components = wxString.split("^")
        validatedComponents = []
        
        for component in components:
            # Remove any trailing colons first for consistent parsing
            component = component.rstrip(":")
            fields = component.split(":")
            
            # CRITICAL: Only keep first 4 fields, discard any attributes field
            if len(fields) > 4:
                fields = fields[:4]
            
            # Pad if less than 4 fields
            while len(fields) < 4:
                fields.append("<NoVis>")
            
            # Build string with exactly 4 fields + trailing colon
            validatedComponents.append(":".join(fields) + ":")
        
        return "^".join(validatedComponents)
    
    def spatialSmooth(self, grid, factor):
        """Apply Gaussian smoothing"""
        sigma = factor * CONFIG.SMOOTHING_SIGMA
        return ndimage.gaussian_filter(grid, sigma=sigma, mode='nearest')
    
    def calculateConvectiveIndex(self, cape, wind_speed_ms):
        """
        Calculate convective index to determine if conditions are convective or stratiform.
        
        Convective Index = (CAPE / 1000) + (WindSpeed / 20)
        
        High index (> 2.0) = Convective (use Coverage: Iso, Sct, Num, Wide)
        Low index (<= 2.0) = Stratiform (use Probability: Chc, Lkly, Def)
        
        Args:
            cape: CAPE value in J/kg
            wind_speed_ms: Wind speed in m/s
        
        Returns:
            convective_index: float value
        """
        cape_component = cape / 1000.0 if cape is not None else 0.0
        wind_component = wind_speed_ms / 20.0 if wind_speed_ms is not None else 0.0
        
        return cape_component + wind_component
    
    def getCoverageFromQPF(self, qpfVal, convective_index, convective_threshold=None):
        """
        Get coverage/probability term based on QPF amount and convective index.
        Automatically determines whether to use Coverage or Probability terms.
        
        For Convective (index > threshold): Use Coverage terms (Iso, Sct, Num, Wide)
        For Stratiform (index <= threshold): Use Probability terms (Chc, Lkly, Def, SChc)
        """
        if convective_threshold is None:
            convective_threshold = CONFIG.CONVECTIVE_THRESHOLD
        
        # Determine if convective or stratiform
        is_convective = convective_index > convective_threshold
        
        if is_convective:
            # Areal coverage terms based on QPF amount
            if qpfVal > CONFIG.QPF_WIDE_COVERAGE:
                return "Wide", True
            elif qpfVal > CONFIG.QPF_NUMEROUS:
                return "Num", True
            elif qpfVal > CONFIG.QPF_SCATTERED:
                return "Sct", True
            else:
                return "Iso", True
        else:
            # Probability terms - higher QPF = higher certainty
            if qpfVal > CONFIG.QPF_DEFINITE:
                return "Def", False
            elif qpfVal > CONFIG.QPF_LIKELY:
                return "Lkly", False
            elif qpfVal > CONFIG.QPF_CHANCE:
                return "Chc", False
            else:
                return "SChc", False

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution"""
        # Clear output log for new execution
        self.outputLog = []
        
        self.statusBarMsg("Starting Marine Weather Grid Builder v2.0...", "R")
        self.log("\n" + "="*80)
        self.log("MARINE WEATHER GRID BUILDER v2.0")
        self.log("="*80)
        
        # Check if WxString is available
        try:
            test = WxString("Iso:T:<NoInten>:<NoVis>:")
            self.log("\n✓ WxString function available")
        except NameError:
            self.log("\n⚠ WARNING: WxString function not available - using direct string format")
        except Exception as e:
            self.log(f"\n⚠ WARNING: WxString test failed: {str(e)}")
        
        # Show GUI
        if varDict is None:
            self.statusBarMsg("Showing configuration GUI...", "R")
            varDict = self.showGUI(editArea, timeRange)
            if varDict is None:
                self.statusBarMsg("Build cancelled by user", "S")
                self.log("\nBuild cancelled by user")
                return
        
        # Get parameters
        atmModels = varDict["Atmospheric Models"]
        buildMode = varDict["Build Mode"]
        smoothing = varDict["Spatial Smoothing"]
        fogThreshold = varDict["Fog Visibility Threshold"]
        modelRun = varDict["Model Run"]
        createDiagnostics = varDict.get("Create Diagnostic Grids", "No")
        
        self.log(f"\nConfiguration:")
        self.log(f"  Models: {', '.join(atmModels)}")
        self.log(f"  Build Mode: {buildMode}")
        self.log(f"  Qualifier Type: AUTOMATIC (based on convective index)")
        self.log(f"  Smoothing: {smoothing}")
        self.log(f"  Fog Threshold: {fogThreshold} SM")
        self.log(f"  Model Run: {modelRun}")
        self.log(f"  Create Diagnostics: {createDiagnostics}")
        self.log(f"  Wind Source: SFC Wind Fcst grid (knots)")
        thunderThreshold = varDict.get("Thunder CAPE Threshold", CONFIG.CAPE_THUNDER_MIN)
        self.thunderThresholdValue = thunderThreshold
        self.log(f"  Thunder CAPE Threshold: {thunderThreshold} J/kg")
        
        self.statusBarMsg(f"Selected: {len(atmModels)} models, Mode: {buildMode}", "R")

        if len(atmModels) == 0:
            self.statusBarMsg("ERROR: No atmospheric models selected", "S")
            self.log("\nERROR: No atmospheric models selected")
            return
        
        # Get forecast grid times - use "Fcst" database name
        gridinfos = self.getGridInfo("Fcst", "Wx", "SFC", timeRange)
        
        if not gridinfos:
            self.statusBarMsg("ERROR: No Wx grids found in time range", "S")
            self.log("\nERROR: No Wx grids found in time range")
            return

        target_times_unix = []
        for gridinfo in gridinfos:
            grid_time = gridinfo.gridTime()
            try:
                target_start = self._time_object_to_unix(grid_time.startTime())
            except Exception:
                target_start = None
            if target_start is not None:
                target_times_unix.append(target_start)
        if not target_times_unix:
            self.log("WARNING: Unable to derive target valid times from Wx grids; DAL will use latest available data.")

        # Retrieve DAL fields for supported models
        self.log("\nRetrieving model QPF/CAPE via Data Access Layer...")
        try:
            self.dal_model_data = self._retrieve_dal_model_fields(timeRange, target_times_unix)
            for model_id, param_store in self.dal_model_data.items():
                qpf_times = len(param_store.get("QPF", {}))
                cape_times = len(param_store.get("CAPE", {}))
                self.log(f"  DAL {model_id}: QPF times={qpf_times}, CAPE times={cape_times}")
        except Exception as e:
            self.log(f"ERROR: DAL retrieval failed: {str(e)}")
            self.dal_model_data = {}
        
        total_periods = len(gridinfos)
        self.log(f"\nProcessing {total_periods} time periods...")
        periods_processed = 0
        
        # Process each time period
        for i, gridinfo in enumerate(gridinfos):
            GridTimeRange = gridinfo.gridTime()
            
            self.statusBarMsg(f"Processing period {i+1}/{total_periods}", "R")
            self.log(f"\n{'='*80}")
            self.log(f"Period {i+1}/{total_periods}: {GridTimeRange}")
            self.log(f"{'='*80}")
            
            # Initialize accumulators (NOTE: wind_accum removed - using SFC Wind Fcst instead)
            temp_accum = None
            rh_accum = None
            qpf_accum = None
            vis_accum = None
            cape_accum = None
            model_count = 0
            
            # Process each atmospheric model using D2D approach (same as working tool)
            for model in atmModels:
                self.log(f"\nProcessing model: {model}")
                
                # Set up atmospheric model database ID using D2D approach
                atmModelID = "D2D_" + model
                
                try:
                    if modelRun == "Current":
                        atmDataBase = self.findDatabase(atmModelID, 0)
                    else:
                        atmDataBase = self.findDatabase(atmModelID, -1)
                    
                    if atmDataBase is None:
                        self.log(f"  Warning: Could not find D2D database for {model}")
                        continue
                    
                    atmDataBaseID = atmDataBase.modelIdentifier()
                    self.log(f"  Found D2D database: {atmDataBaseID}")
                    
                except Exception as e:
                    self.log(f"  Error setting up database access for {model}: {str(e)}")
                    continue
                
                # Get surface temperature
                try:
                    temp_grid = self.getGrids(atmDataBaseID, "t", "MB1000", GridTimeRange, mode="First", noDataError=0)
                    if temp_grid is not None:
                        # Try to get units
                        try:
                            parm = self.getParm(atmDataBaseID, "t", "MB1000")
                            units = parm.getGridInfo().getUnitString() if parm else "unknown"
                            self.log(f"  ✓ Temperature (units: {units})")
                        except:
                            self.log(f"  ✓ Temperature (units: unknown)")
                        
                        # Convert from Kelvin to Celsius
                        if np.max(temp_grid) > 200:
                            temp_celsius = temp_grid - 273.15
                            self.log(f"    Raw range: {np.min(temp_grid):.1f} to {np.max(temp_grid):.1f} K")
                        else:
                            temp_celsius = temp_grid
                            self.log(f"    Raw range: {np.min(temp_grid):.1f} to {np.max(temp_grid):.1f} C")
                        
                        if temp_accum is None:
                            temp_accum = temp_celsius.copy()
                        else:
                            temp_accum += temp_celsius
                    else:
                        self.log(f"  ✗ Temperature")
                except Exception as e:
                    self.log(f"  ✗ Temperature: {str(e)}")
                
                # Get relative humidity
                try:
                    surf_rh = self.getGrids(atmDataBaseID, "rh", "MB1000", GridTimeRange, mode="First", noDataError=0)
                    if surf_rh is not None:
                        try:
                            parm = self.getParm(atmDataBaseID, "rh", "MB1000")
                            units = parm.getGridInfo().getUnitString() if parm else "unknown"
                            self.log(f"  ✓ Relative Humidity (units: {units})")
                        except:
                            self.log(f"  ✓ Relative Humidity (units: unknown)")
                        
                        self.log(f"    Raw range: {np.min(surf_rh):.1f} to {np.max(surf_rh):.1f}")
                        
                        if rh_accum is None:
                            rh_accum = surf_rh.copy()
                        else:
                            rh_accum += surf_rh
                    else:
                        self.log(f"  ✗ Relative Humidity")
                except Exception as e:
                    self.log(f"  ✗ Relative Humidity: {str(e)}")
                
                # NOTE: Wind section removed - now using SFC Wind Fcst grid after model loop
                
                # Get QPF (precipitation) - prefer DAL data
                qpf_grid = self._get_dal_field_array(model, "QPF", GridTimeRange)
                if qpf_grid is not None:
                    qpf_inches = qpf_grid
                    self.log("  ✓ QPF (DAL)")
                    if np.any(np.isfinite(qpf_inches)):
                        self.log(f"    Range (in): {np.nanmin(qpf_inches):.3f} to {np.nanmax(qpf_inches):.3f}")
                    else:
                        self.log("    Range (in): all NaN")
                    if qpf_accum is None:
                        qpf_accum = qpf_inches.copy()
                    else:
                        qpf_accum += qpf_inches
                else:
                    try:
                        qpf_raw = self.getGrids(atmDataBaseID, "tp", "SFC", GridTimeRange, mode="First", noDataError=0)
                        if qpf_raw is not None:
                            try:
                                parm = self.getParm(atmDataBaseID, "tp", "SFC")
                                units = parm.getGridInfo().getUnitString() if parm else "unknown"
                                self.log(f"  ✓ QPF (tp) (units: {units})")
                            except:
                                self.log(f"  ✓ QPF (tp) (units: unknown)")
                            
                            self.log(f"    Raw range: {np.min(qpf_raw):.6f} to {np.max(qpf_raw):.6f}")
                            
                            qpf_inches = qpf_raw / CONFIG.MM_TO_INCHES  # mm to inches
                            self.log(f"    Converted to inches: {np.min(qpf_inches):.3f} to {np.max(qpf_inches):.3f}")
                            
                            if qpf_accum is None:
                                qpf_accum = qpf_inches.copy()
                            else:
                                qpf_accum += qpf_inches
                        else:
                            self.log(f"  ✗ QPF")
                    except Exception as e:
                        self.log(f"  ✗ QPF: {str(e)}")
                
                # Get visibility
                try:
                    vis_grid = self.getGrids(atmDataBaseID, "vis", "SFC", GridTimeRange, mode="First", noDataError=0)
                    if vis_grid is not None:
                        try:
                            parm = self.getParm(atmDataBaseID, "vis", "SFC")
                            units = parm.getGridInfo().getUnitString() if parm else "unknown"
                            self.log(f"  ✓ Visibility (units: {units})")
                        except:
                            self.log(f"  ✓ Visibility (units: unknown)")
                        
                        self.log(f"    Raw range: {np.min(vis_grid):.1f} to {np.max(vis_grid):.1f}")
                        
                        # Convert from meters to statute miles
                        vis_sm = vis_grid * CONFIG.M_TO_SM
                        self.log(f"    Converted to SM: {np.min(vis_sm):.2f} to {np.max(vis_sm):.2f}")
                        
                        if vis_accum is None:
                            vis_accum = vis_sm.copy()
                        else:
                            vis_accum = np.minimum(vis_accum, vis_sm)  # Take minimum
                    else:
                        self.log(f"  ✗ Visibility")
                except Exception as e:
                    self.log(f"  ✗ Visibility: {str(e)}")
                
                # Get CAPE - prefer DAL data
                cape_grid = self._get_dal_field_array(model, "CAPE", GridTimeRange)
                if cape_grid is not None:
                    self.log("  ✓ CAPE (DAL)")
                    if np.any(np.isfinite(cape_grid)):
                        self.log(f"    Range: {np.nanmin(cape_grid):.1f} to {np.nanmax(cape_grid):.1f}")
                    else:
                        self.log("    Range: all NaN")
                    if cape_accum is None:
                        cape_accum = cape_grid.copy()
                    else:
                        cape_accum = np.maximum(cape_accum, cape_grid)
                else:
                    try:
                        cape_raw = self.getGrids(atmDataBaseID, "cape", "SFC", GridTimeRange, mode="First", noDataError=0)
                        if cape_raw is not None:
                            try:
                                parm = self.getParm(atmDataBaseID, "cape", "SFC")
                                units = parm.getGridInfo().getUnitString() if parm else "unknown"
                                self.log(f"  ✓ CAPE (units: {units})")
                            except:
                                self.log(f"  ✓ CAPE (units: unknown)")
                            
                            self.log(f"    Raw range: {np.min(cape_raw):.1f} to {np.max(cape_raw):.1f}")
                            
                            if cape_accum is None:
                                cape_accum = cape_raw.copy()
                            else:
                                cape_accum = np.maximum(cape_accum, cape_raw)  # Take maximum
                        else:
                            self.log(f"  ✗ CAPE")
                    except Exception as e:
                        self.log(f"  ✗ CAPE: {str(e)}")
                
                model_count += 1
                self.log(f"  Successfully processed model {model}")
            
            # Check if we got valid data
            if model_count == 0:
                self.log(f"\nNo valid data for time period {i+1}")
                continue
            
            self.log(f"\nAveraged {model_count} atmospheric models")
            
            # Get SFC Wind Fcst grid (in knots) - only need to get once from Fcst database
            self.log(f"\nGetting SFC Wind Fcst grid...")
            wind_avg = None
            try:
                wind_grid = self.getGrids("Fcst", "Wind", "SFC", GridTimeRange, mode="First", noDataError=0)
                if wind_grid is not None:
                    wind_avg = wind_grid
                    # Calculate magnitude to show range
                    wind_mag = np.sqrt(wind_avg[0]**2 + wind_avg[1]**2)
                    self.log(f"  ✓ SFC Wind Fcst (units: knots)")
                    self.log(f"    Speed range: {np.min(wind_mag):.1f} to {np.max(wind_mag):.1f} kt")
                else:
                    self.log(f"  ✗ SFC Wind Fcst not available")
            except Exception as e:
                self.log(f"  ✗ SFC Wind Fcst: {str(e)}")
            
            # Calculate averages
            if model_count > 1:
                if temp_accum is not None:
                    temp_avg = temp_accum / model_count
                else:
                    temp_avg = None
                
                if rh_accum is not None:
                    rh_avg = rh_accum / model_count
                else:
                    rh_avg = None
                
                if qpf_accum is not None:
                    qpf_avg = qpf_accum / model_count
                else:
                    qpf_avg = None
            else:
                temp_avg = temp_accum
                rh_avg = rh_accum
                qpf_avg = qpf_accum
            
            # wind_avg already set from SFC Wind Fcst grid above
            vis_avg = vis_accum
            cape_avg = cape_accum
            
            # Log what data we have
            self.log(f"\nData availability:")
            self.log(f"  Temperature: {'Available' if temp_avg is not None else 'Not available'}")
            self.log(f"  RH: {'Available' if rh_avg is not None else 'Not available'}")
            self.log(f"  Wind: {'Available' if wind_avg is not None else 'Not available'}")
            self.log(f"  QPF: {'Available' if qpf_avg is not None else 'Not available'}")
            self.log(f"  Visibility: {'Available' if vis_avg is not None else 'Not available'}")
            self.log(f"  CAPE: {'Available' if cape_avg is not None else 'Not available'}")
            
            # Create diagnostic grids if requested
            if createDiagnostics == "Yes":
                self.log(f"\nCreating diagnostic grids...")
                
                try:
                    if qpf_avg is not None:
                        # Clip QPF to reasonable range
                        qpf_clipped = np.clip(qpf_avg, 0.0, CONFIG.QPF_MAX_CLIP)
                        self.createGrid("Fcst", "QPF", "SCALAR", qpf_clipped, GridTimeRange)
                        self.log(f"  ✓ QPF grid (inches, clipped 0-{CONFIG.QPF_MAX_CLIP})")
                        # Log statistics
                        self.log(f"    Min: {np.min(qpf_avg):.3f}  Max: {np.max(qpf_avg):.3f}  Mean: {np.mean(qpf_avg):.3f}")
                except Exception as e:
                    self.log(f"  ✗ QPF grid: {str(e)}")
                
                try:
                    if cape_avg is not None:
                        # Clip CAPE to reasonable range
                        cape_clipped = np.clip(cape_avg, 0.0, CONFIG.CAPE_MAX_CLIP)
                        self.createGrid("Fcst", "CAPE", "SCALAR", cape_clipped, GridTimeRange)
                        self.log(f"  ✓ CAPE grid (J/kg, clipped 0-{CONFIG.CAPE_MAX_CLIP:.0f})")
                        self.log(f"    Min: {np.min(cape_avg):.0f}  Max: {np.max(cape_avg):.0f}  Mean: {np.mean(cape_avg):.0f}")
                except Exception as e:
                    self.log(f"  ✗ CAPE grid: {str(e)}")
                
                try:
                    if temp_avg is not None:
                        # Create temp grid (Celsius, convert to Fahrenheit for easier viewing)
                        temp_f = (temp_avg * CONFIG.C_TO_F_MULT) + CONFIG.C_TO_F_ADD
                        # Clip temperature to reasonable range
                        temp_f_clipped = np.clip(temp_f, CONFIG.TEMP_MIN_CLIP, CONFIG.TEMP_MAX_CLIP)
                        self.createGrid("Fcst", "T", "SCALAR", temp_f_clipped, GridTimeRange)
                        self.log(f"  ✓ Temperature grid (°F, clipped {CONFIG.TEMP_MIN_CLIP} to {CONFIG.TEMP_MAX_CLIP})")
                        self.log(f"    Min: {np.min(temp_f):.1f}  Max: {np.max(temp_f):.1f}  Mean: {np.mean(temp_f):.1f}")
                except Exception as e:
                    self.log(f"  ✗ Temperature grid: {str(e)}")
                
                try:
                    if rh_avg is not None:
                        # Clip RH to valid range
                        rh_clipped = np.clip(rh_avg, CONFIG.RH_MIN_CLIP, CONFIG.RH_MAX_CLIP)
                        self.createGrid("Fcst", "RH", "SCALAR", rh_clipped, GridTimeRange)
                        self.log(f"  ✓ RH grid (%, clipped {CONFIG.RH_MIN_CLIP}-{CONFIG.RH_MAX_CLIP})")
                        self.log(f"    Min: {np.min(rh_avg):.1f}  Max: {np.max(rh_avg):.1f}  Mean: {np.mean(rh_avg):.1f}")
                except Exception as e:
                    self.log(f"  ✗ RH grid: {str(e)}")
                
                try:
                    if vis_avg is not None:
                        # Clip visibility to reasonable range
                        vis_clipped = np.clip(vis_avg, CONFIG.VIS_MIN_CLIP, CONFIG.VIS_MAX_CLIP)
                        self.createGrid("Fcst", "Vsby", "SCALAR", vis_clipped, GridTimeRange)
                        self.log(f"  ✓ Visibility grid (SM, clipped {CONFIG.VIS_MIN_CLIP}-{CONFIG.VIS_MAX_CLIP})")
                        self.log(f"    Min: {np.min(vis_avg):.2f}  Max: {np.max(vis_avg):.2f}  Mean: {np.mean(vis_avg):.2f}")
                except Exception as e:
                    self.log(f"  ✗ Visibility grid: {str(e)}")
                
                try:
                    if wind_avg is not None:
                        # Calculate wind speed magnitude (already in knots from SFC Wind Fcst)
                        wind_speed_kt = np.sqrt(wind_avg[0]**2 + wind_avg[1]**2)
                        # Clip wind speed to reasonable range
                        wind_speed_kt_clipped = np.clip(wind_speed_kt, CONFIG.WIND_MIN_CLIP, CONFIG.WIND_MAX_CLIP)
                        self.createGrid("Fcst", "WindSpeed", "SCALAR", wind_speed_kt_clipped, GridTimeRange)
                        self.log(f"  ✓ Wind Speed grid (kt, clipped {CONFIG.WIND_MIN_CLIP}-{CONFIG.WIND_MAX_CLIP})")
                        self.log(f"    Min: {np.min(wind_speed_kt):.1f}  Max: {np.max(wind_speed_kt):.1f}  Mean: {np.mean(wind_speed_kt):.1f}")
                except Exception as e:
                    self.log(f"  ✗ Wind Speed grid: {str(e)}")
                
                # Calculate and create Convective Index grid
                try:
                    if cape_avg is not None and wind_avg is not None:
                        # Wind is in knots, convert to m/s for convective index
                        wind_speed_kt = np.sqrt(wind_avg[0]**2 + wind_avg[1]**2)
                        wind_speed_ms = wind_speed_kt * CONFIG.KT_TO_MS  # knots to m/s
                        # Calculate convective index for entire grid
                        conv_index = (cape_avg / 1000.0) + (wind_speed_ms / 20.0)
                        # Clip to reasonable range
                        conv_index_clipped = np.clip(conv_index, CONFIG.CONV_INDEX_MIN, CONFIG.CONV_INDEX_MAX)
                        self.createGrid("Fcst", "ConvectiveIndex", "SCALAR", conv_index_clipped, GridTimeRange)
                        self.log(f"  ✓ Convective Index grid (>{CONFIG.CONVECTIVE_THRESHOLD} = convective/coverage terms)")
                        self.log(f"    Min: {np.min(conv_index):.2f}  Max: {np.max(conv_index):.2f}  Mean: {np.mean(conv_index):.2f}")
                        self.log(f"    Threshold: {CONFIG.CONVECTIVE_THRESHOLD} (Coverage above, Probability below)")
                except Exception as e:
                    self.log(f"  ✗ Convective Index grid: {str(e)}")
            
            # Apply smoothing
            if smoothing > 0:
                self.log(f"\nApplying spatial smoothing (factor={smoothing})...")
                if qpf_avg is not None:
                    qpf_avg = self.spatialSmooth(qpf_avg, smoothing)
                if vis_avg is not None:
                    vis_avg = self.spatialSmooth(vis_avg, smoothing)
            
            # Build weather analysis
            self.log("\nAnalyzing weather conditions...")
            
            # Determine precipitation
            hasPrecip = qpf_avg > CONFIG.QPF_MINIMUM if qpf_avg is not None else None
            
            # Determine thunder (CAPE > threshold)
            threshold = getattr(self, "thunderThresholdValue", CONFIG.CAPE_THUNDER_MIN)
            hasThunder = cape_avg > threshold if cape_avg is not None else None
            
            # Determine fog (vis < threshold and RH > threshold)
            hasFog = None
            if vis_avg is not None and rh_avg is not None:
                hasFog = (vis_avg < fogThreshold) & (rh_avg > CONFIG.FOG_RH_MIN)
            
            # Get existing Wx grid from Fcst database
            wxGrid = self.getGrids("Fcst", "Wx", "SFC", GridTimeRange, noDataError=0)
            if wxGrid is None:
                self.log("  ERROR: Could not load existing Wx grid from Fcst")
                continue
            
            wxValues, keys = wxGrid
            
            # Use standard 4-field weather template with trailing colon
            noWxTemplate = "<NoCov>:<NoWx>:<NoInten>:<NoVis>:"
            
            # Build new weather grid
            self.log("\nBuilding weather grid...")
            self.log(f"  Precipitation: {'Yes' if hasPrecip is not None and np.any(hasPrecip) else 'No'}")
            self.log(f"  Thunder: {'Yes' if hasThunder is not None and np.any(hasThunder) else 'No'}")
            self.log(f"  Fog: {'Yes' if hasFog is not None and np.any(hasFog) else 'No'}")
            
            # Create new weather values grid
            newWxValues = np.zeros(wxValues.shape, dtype=wxValues.dtype)
            
            # Get grid shape
            if wxValues.shape[0] == 0 or wxValues.shape[1] == 0:
                self.log("  ERROR: Invalid grid shape")
                continue
            
            # Build weather for each grid point
            for i_pt in range(wxValues.shape[0]):
                for j_pt in range(wxValues.shape[1]):
                    wxComponents = []
                    
                    # Check for thunder at this point
                    if hasThunder is not None and hasThunder[i_pt, j_pt]:
                        # Determine coverage from CAPE magnitude
                        capeVal = cape_avg[i_pt, j_pt]
                        if capeVal > CONFIG.CAPE_HIGH:
                            tCov = "Sct"
                        elif capeVal > CONFIG.CAPE_MODERATE:
                            tCov = "Iso"
                        else:
                            tCov = "Iso"
                        
                        # Determine if severe (T+) or non-severe (T)
                        # Severe thunder uses intensity "+", non-severe uses "<NoInten>"
                        isSevere = False
                        if capeVal > CONFIG.CAPE_SEVERE_MIN:  # Very high CAPE suggests severe
                            isSevere = True
                        
                        # Also check for heavy precipitation which suggests severe
                        if qpf_avg is not None:
                            qpfVal = qpf_avg[i_pt, j_pt]
                            if qpfVal > CONFIG.QPF_SEVERE_WITH_THUNDER:  # Heavy precip with thunder
                                isSevere = True
                        
                        # Set intensity based on severity
                        if isSevere:
                            tInt = "+"  # Severe thunder (T+)
                        else:
                            tInt = "<NoInten>"  # Non-severe thunder (T)
                        
                        # Build key with 4 fields + trailing colon
                        wxStr = self.buildWxKey(tCov, "T", tInt)
                        wxComponents.append(wxStr)
                    
                    # Check for precipitation (without thunder)
                    elif hasPrecip is not None and hasPrecip[i_pt, j_pt]:
                        qpfVal = qpf_avg[i_pt, j_pt]
                        
                        # Calculate convective index for this point
                        cape_val = cape_avg[i_pt, j_pt] if cape_avg is not None else 0.0
                        
                        wind_speed_ms = 0.0
                        if wind_avg is not None:
                            # Wind is in knots, convert to m/s for convective index calculation
                            wind_speed_kt = np.sqrt(wind_avg[0][i_pt, j_pt]**2 + 
                                                   wind_avg[1][i_pt, j_pt]**2)
                            wind_speed_ms = wind_speed_kt * CONFIG.KT_TO_MS  # knots to m/s
                        
                        convective_index = self.calculateConvectiveIndex(cape_val, wind_speed_ms)
                        
                        # Get coverage/probability term and convective flag
                        pCov, is_convective = self.getCoverageFromQPF(qpfVal, convective_index)
                        
                        # Determine intensity
                        if qpfVal > CONFIG.QPF_HEAVY:
                            pInt = "+"
                        elif qpfVal > CONFIG.QPF_MODERATE:
                            pInt = "m"
                        elif qpfVal > CONFIG.QPF_LIGHT:
                            pInt = "-"
                        else:
                            pInt = "-"
                        
                        # Determine type (R, RW, S, SW)
                        if temp_avg is not None:
                            tempVal = temp_avg[i_pt, j_pt]
                            if tempVal < CONFIG.TEMP_FREEZING:  # Below freezing (Celsius)
                                # For snow - use showers if convective
                                if is_convective:
                                    pType = "SW"  # Snow showers
                                else:
                                    pType = "S"   # Steady snow
                            else:
                                # For rain - use showers if convective
                                if is_convective:
                                    pType = "RW"  # Rain showers
                                else:
                                    pType = "R"   # Steady rain
                        else:
                            # No temp data - default based on convective index
                            pType = "RW" if is_convective else "R"
                        
                        # Build key with 4 fields + trailing colon
                        wxStr = self.buildWxKey(pCov, pType, pInt)
                        wxComponents.append(wxStr)
                    
                    # Check for fog ONLY when there's no thunder or precipitation
                    elif hasFog is not None and hasFog[i_pt, j_pt]:
                        # Determine coverage
                        fCov = "Patchy"
                        
                        # Fog always uses <NoInten> for intensity
                        fInt = "<NoInten>"
                        
                        # Build key with 4 fields + trailing colon
                        wxStr = self.buildWxKey(fCov, "F", fInt)
                        wxComponents.append(wxStr)
                    
                    # Build final weather string
                    if wxComponents:
                        # Combine multiple weather types with ^
                        uglyString = "^".join(wxComponents)
                        
                        # Validate to ensure 4 fields + trailing colon per component
                        uglyString = self.validateWxString(uglyString)
                        
                        # Try to use WxString to validate/convert
                        try:
                            wxKey = WxString(uglyString)
                            # CRITICAL: Validate again to remove any <NoAttr> that WxString may have added
                            wxKey = self.validateWxString(str(wxKey))
                        except:
                            # If WxString fails, use validated ugly string
                            wxKey = uglyString
                        
                        # Get index for this weather string
                        try:
                            newWxValues[i_pt, j_pt] = self.getIndex(wxKey, keys)
                        except Exception as e:
                            # If that fails, use no weather template
                            if i_pt == 0 and j_pt == 0:  # Only log once
                                self.log(f"  Warning: Could not create weather key: {str(e)}")
                                self.log(f"  Attempted key was: {wxKey}")
                            newWxValues[i_pt, j_pt] = self.getIndex(noWxTemplate, keys)
                    else:
                        # No weather - use template
                        newWxValues[i_pt, j_pt] = self.getIndex(noWxTemplate, keys)
            
            # Save the new weather grid to Fcst database
            try:
                self.log("\nSaving weather grid to Fcst database...")
                wx_out = newWxValues.astype(wxValues.dtype, copy=False)
                self.createGrid("Fcst", "Wx", "WEATHER", (wx_out, keys), GridTimeRange)
                self.log(f"  ✓ Weather grid saved successfully")
                
                # Print statistics
                uniqueWx = {}
                for val in newWxValues.flat:
                    key = keys[val]
                    uniqueWx[key] = uniqueWx.get(key, 0) + 1
                
                self.log("\n  Weather Statistics:")
                for wx, count in sorted(uniqueWx.items(), key=lambda x: x[1], reverse=True)[:5]:
                    pct = (count / newWxValues.size) * 100
                    if wx == noWxTemplate:
                        wx = "No Weather"
                    self.log(f"    {wx}: {pct:.1f}% ({count} points)")
                
            except Exception as e:
                self.log(f"  ERROR saving grid: {str(e)}")
                import traceback
                self.log(f"  Traceback: {traceback.format_exc()}")
                continue
            
            periods_processed += 1
            self.log(f"\n✓ Completed period {i+1}")
        
        # Final message
        self.log("\n" + "="*80)
        if periods_processed > 0:
            self.statusBarMsg(f"SUCCESS: {periods_processed} periods processed", "A")
            self.log(f"Marine Weather Builder v2.0 completed - {periods_processed}/{total_periods} periods")
        else:
            self.statusBarMsg("ERROR: No periods processed", "S")
            self.log("ERROR: No periods processed successfully")
        self.log("="*80 + "\n")
        
        # Show results popup
        self.showResultsPopup("Marine Weather Builder v2.0 - Results", periods_processed, total_periods)
        
        return None