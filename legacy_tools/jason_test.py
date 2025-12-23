# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# Model_Guidance_Assistant.py - Comprehensive Model Analysis Tool (Tkinter)
#
# Author: jason.krekeler
# Combines model consistency and inter-model agreement analysis
# to help forecasters make informed model selection decisions
# COMPLETED VERSION
# ----------------------------------------------------------------------------

MenuItems = ["Edit"]
import LogStream, time
WeatherElementEdited = "variableElement"
from numpy import *
import math
import JUtil
import tkinter as tk
HideTool = 0

ScreenList = ["Wind"]

# Empty VariableList since we're using custom GUI
VariableList = []

import time
import AbsTime
import SmartScript

class ModelGuidanceGUI:
    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Model Guidance Assistant")
        self.master.geometry("700x1000")  # Reduced height after removing agreement section
        self.master.resizable(False, False)
        
        self.createWidgets()
        
    def updateThresholdLabel(self, *args):
        """Update the threshold label"""
        threshold = self.windThreshold.get()
        self.thresholdLabel.config(text=f"{threshold} kts")
    
    def updateSelection(self, *args):
        """Update selection status"""
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        
        if selectedCount == 0:
            self.statusLabel.config(text="No Models Selected", fg="red")
            self.messageLabel.config(text="Select models for analysis", fg="red")
        elif selectedCount == 1:
            self.statusLabel.config(text=f"1 Model Selected", fg="orange")
            self.messageLabel.config(text="Select 2+ models for agreement analysis", fg="orange")
        else:
            self.statusLabel.config(text=f"{selectedCount} Models Selected", fg="green")
            self.messageLabel.config(text="Ready for comprehensive analysis", fg="green")

    def createWidgets(self):
        # Main frame with better organization
        mainFrame = tk.Frame(self.master, padx=15, pady=15)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Model Guidance Assistant", 
                             font=("Arial", 16, "bold"))
        titleLabel.pack(pady=(0, 5))
        
        # Subtitle
        subtitleLabel = tk.Label(mainFrame, text="Comprehensive Wind Speed Model Analysis", 
                               font=("Arial", 12), fg="navy")
        subtitleLabel.pack(pady=(0, 15))
        
        # Description
        descLabel = tk.Label(mainFrame, 
                           text="Analyze model consistency + agreement to guide forecasting decisions",
                           font=("Arial", 10), fg="gray", justify=tk.CENTER)
        descLabel.pack(pady=(0, 15))
        
        # Model Selection Frame with scrollable area
        modelFrame = tk.LabelFrame(mainFrame, text="Select Models for Analysis", padx=15, pady=10)
        modelFrame.pack(fill=tk.X, pady=(0, 15))
        
        # Quick Preset Buttons
        presetFrame = tk.Frame(modelFrame)
        presetFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(presetFrame, text="Quick Presets:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        tk.Button(presetFrame, text="All Global", command=self.selectAllGlobal, 
                 bg="lightgreen", font=("Arial", 9), width=10).pack(side=tk.LEFT, padx=(10, 5))
        tk.Button(presetFrame, text="Ensemble", command=self.selectEnsemble, 
                 bg="lightblue", font=("Arial", 9), width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(presetFrame, text="High-Res", command=self.selectHighRes, 
                 bg="lightyellow", font=("Arial", 9), width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(presetFrame, text="CONUS Only", command=self.selectCONUS, 
                 bg="lightcoral", font=("Arial", 9), width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(presetFrame, text="Clear All", command=self.clearAll, 
                 bg="lightgray", font=("Arial", 9), width=10).pack(side=tk.LEFT, padx=5)
        
        # Scrollable model selection area
        scrollFrame = tk.Frame(modelFrame)
        scrollFrame.pack(fill=tk.BOTH, expand=True)
        
        # Create canvas and scrollbar for scrolling
        canvas = tk.Canvas(scrollFrame, height=250)  # Reduced height to fit new sections
        scrollbar = tk.Scrollbar(scrollFrame, orient="vertical", command=canvas.yview)
        scrollableFrame = tk.Frame(canvas)
        
        scrollableFrame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollableFrame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Model definitions organized by category
        modelCategories = [
            ("Global Models:", [
                ("ECMWF (European Centre)", "nECMWF0p25", 2),
                ("GFS (Global Forecast System)", "GFS", 2), 
                ("CMC (Canadian Global)", "CMCnh", 2),
                ("UKMET High-Res", "UKMEThires4", 2),
            ]),
            ("Ensemble Models:", [
                ("GEFS Mean (GFS Ensemble)", "GEFSMEAN", 2),
                ("ECENS Mean (ECMWF Ensemble)", "ECENSMEAN", 2),
                ("NBM (National Blend)", "NBM", 2),
                ("National Blend Ocean", "NationalBlendOC", 2),
            ]),
            ("North American/CONUS Models:", [
                ("NAM 12km", "NAM12", 2),
                ("RAP 13km", "RAP13", 2),
                ("NAM Nest", "NAMNest", 2),
            ]),
            ("High-Resolution CONUS Models:", [
                ("HIRESW ARW (CONUS)", "HIRESWarw", 2),
                ("HIRESW NMM (CONUS)", "HIRESWnmm", 2),
                ("HRRR (CONUS only)", "HRRR", 2),
            ])
        ]
        
        # Create checkboxes for model selection organized by category
        self.modelSelections = {}
        self.modelInfo = {}
        
        for categoryName, models in modelCategories:
            # Category header
            categoryLabel = tk.Label(scrollableFrame, text=categoryName, 
                                   font=("Arial", 10, "bold"), fg="darkblue")
            categoryLabel.pack(anchor=tk.W, pady=(10, 5))
            
            for displayName, modelId, runCount in models:
                var = tk.StringVar()
                var.set("No")
                var.trace("w", self.updateSelection)
                self.modelSelections[modelId] = var
                self.modelInfo[modelId] = {
                    'displayName': displayName,
                    'runCount': runCount
                }
                
                # Checkbox with model info - indented under category
                cb = tk.Checkbutton(scrollableFrame, text=displayName, 
                                  variable=var, onvalue="Yes", offvalue="No",
                                  anchor=tk.W, font=("Arial", 9))
                cb.pack(fill=tk.X, pady=2, padx=(20, 0))
        
        # Status labels
        self.statusLabel = tk.Label(modelFrame, text="No Models Selected", 
                                  font=("Arial", 11, "bold"), fg="red")
        self.statusLabel.pack(pady=(10, 0))
        
        self.messageLabel = tk.Label(modelFrame, text="Select models for analysis", 
                                   font=("Arial", 9), fg="red")
        self.messageLabel.pack()
        
        # Analysis Options Frame
        optionsFrame = tk.LabelFrame(mainFrame, text="Analysis Options", padx=15, pady=10)
        optionsFrame.pack(fill=tk.X, pady=(0, 15))
        
        # Wind Speed Threshold
        thresholdFrame = tk.Frame(optionsFrame)
        thresholdFrame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(thresholdFrame, text="Wind Speed Threshold:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.windThreshold = tk.IntVar()
        self.windThreshold.set(20)  # Default 20 knots
        
        tk.Scale(thresholdFrame, from_=5, to=35, orient=tk.HORIZONTAL, 
                variable=self.windThreshold, command=self.updateThresholdLabel, 
                width=12).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        self.thresholdLabel = tk.Label(thresholdFrame, text="20 kts", width=8, font=("Arial", 10, "bold"))
        self.thresholdLabel.pack(side=tk.RIGHT)
        
        tk.Label(optionsFrame, text="Only analyze areas where wind speed ≥ threshold (ignores light/variable winds)",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, pady=(0, 10))
        
        # Warning Guidance Grid
        self.createWarningGuidance = tk.StringVar()
        self.createWarningGuidance.set("Yes")
        tk.Checkbutton(optionsFrame, text="Warning Guidance Grid", 
                      variable=self.createWarningGuidance, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=2)
        
        tk.Label(optionsFrame, text="• Single grid showing recommended warning category + confidence",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Values: 1.x=SCA, 2.x=Gale, 3.x=Storm, 4.x=Hurricane (.9=high, .2=low confidence)",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Model Consistency Analysis (report only)
        self.runConsistency = tk.StringVar()
        self.runConsistency.set("Yes")
        tk.Checkbutton(optionsFrame, text="Model Consistency Analysis (Report Only)", 
                      variable=self.runConsistency, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Analyzes how consistent each model is across recent runs",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Statistics included in analysis report (no grids created)",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))

        

        
        # Results Info Frame
        resultsFrame = tk.LabelFrame(mainFrame, text="What This Tool Helps You Decide", padx=15, pady=10)
        resultsFrame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(resultsFrame, text="✓ What warning category should I issue? (WarningGuidance Grid)",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="✓ How confident should I be in that decision? (Confidence Level)",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="✓ Which models are reliable vs erratic? (Report Statistics)",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="✓ Where should I focus my forecast attention?",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        
        # Buttons Frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(15, 0))
        
        tk.Button(buttonFrame, text="Run Analysis", command=self.runTool, 
                 bg="lightblue", font=("Arial", 11, "bold"), width=15).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(buttonFrame, text="Cancel", command=self.cancel, 
                 font=("Arial", 11), width=12).pack(side=tk.LEFT)
        
        # Update initial state
        self.updateSelection()
        self.updateThresholdLabel()
    
    def selectAllGlobal(self):
        """Select global models with worldwide coverage"""
        globalModels = ["nECMWF0p25", "GFS", "CMCnh", "UKMEThires4"]
        self.clearAll()
        for modelId in globalModels:
            if modelId in self.modelSelections:
                self.modelSelections[modelId].set("Yes")
        self.updateSelection()
    
    def selectEnsemble(self):
        """Select ensemble mean models"""
        ensembleModels = ["GEFSMEAN", "ECENSMEAN", "NBM", "NationalBlendOC"]
        self.clearAll()
        for modelId in ensembleModels:
            if modelId in self.modelSelections:
                self.modelSelections[modelId].set("Yes")
        self.updateSelection()
    
    def selectHighRes(self):
        """Select high-resolution models (may have limited coverage)"""
        highResModels = ["HRRR", "HIRESWarw", "HIRESWnmm", "NAM12", "RAP13", "NAMNest"]
        self.clearAll()
        for modelId in highResModels:
            if modelId in self.modelSelections:
                self.modelSelections[modelId].set("Yes")
        self.updateSelection()
        
        # Show coverage warning
        self.messageLabel.config(text="Note: High-res models may have limited geographic coverage", fg="orange")
        self.master.after(5000, lambda: self.messageLabel.config(text="Ready for comprehensive analysis", fg="green"))
    
    def selectCONUS(self):
        """Select North American/CONUS models with good coverage"""
        conusModels = ["GFS", "NAM12", "RAP13", "GEFSMEAN", "NBM"]
        self.clearAll()
        for modelId in conusModels:
            if modelId in self.modelSelections:
                self.modelSelections[modelId].set("Yes")
        self.updateSelection()
    
    def clearAll(self):
        """Clear all model selections"""
        for var in self.modelSelections.values():
            var.set("No")
        self.updateSelection()
    
    def getValues(self):
        """Return dictionary of selected models and analysis options"""
        selectedModels = {}
        for modelId, var in self.modelSelections.items():
            if var.get() == "Yes":
                selectedModels[modelId] = self.modelInfo[modelId]
        
        return {
            "Selected Models": selectedModels,
            "Create Warning Guidance": self.createWarningGuidance.get(),
            "Run Consistency": self.runConsistency.get(),
            "Wind Threshold": self.windThreshold.get()
        }
    
    def runTool(self):
        """Validate inputs and run the tool"""
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        if selectedCount == 0:
            self.messageLabel.config(text="ERROR: Select at least 1 model!", fg="red")
            self.master.after(3000, lambda: self.updateSelection())
            return
        
        # Get values and close GUI
        self.callback(self.getValues())
        self.master.destroy()

    def cancel(self):
        """Close without running"""
        self.master.destroy()

class AnalysisReportWindow:
    def __init__(self, analysisStats, windThreshold):
        self.analysisStats = analysisStats
        self.windThreshold = windThreshold
        
        # Create new window
        self.root = tk.Tk()
        self.root.title("Model Guidance Analysis Report")
        self.root.geometry("950x750")
        self.root.resizable(True, True)
        
        self.createReportWindow()
        self.root.mainloop()
    
    def createReportWindow(self):
        # Main frame
        mainFrame = tk.Frame(self.root, padx=15, pady=15)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Model Guidance Analysis Report", 
                             font=("Arial", 16, "bold"), fg="navy")
        titleLabel.pack(pady=(0, 15))
        
        # Create scrollable text area
        textFrame = tk.Frame(mainFrame)
        textFrame.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = tk.Scrollbar(textFrame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Text widget
        self.reportText = tk.Text(textFrame, wrap=tk.WORD, font=("Courier", 10),
                                 yscrollcommand=scrollbar.set, bg="white", fg="black")
        self.reportText.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.reportText.yview)
        
        # Generate and insert report
        self.generateReport()
        
        # Buttons frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(15, 0))
        
        tk.Button(buttonFrame, text="Save Report", command=self.saveReport,
                 font=("Arial", 11), bg="lightgreen", width=12).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(buttonFrame, text="Close Report", command=self.closeReport,
                 font=("Arial", 11, "bold"), bg="lightcoral", width=12).pack(side=tk.RIGHT)
    
    def generateReport(self):
        """Generate the comprehensive analysis report"""
        report = []
        
        # Header
        report.append("=" * 70)
        report.append("MODEL GUIDANCE ANALYSIS REPORT")
        report.append("=" * 70)
        report.append("")
        
        # General Information
        report.append("ANALYSIS PARAMETERS:")
        report.append("-" * 30)
        report.append(f"Wind Speed Threshold: ≥{self.windThreshold} knots")
        report.append(f"Time Periods Analyzed: {self.analysisStats.get('timePeriodsProcessed', 0)}")
        report.append(f"Models Analyzed: {', '.join(self.analysisStats.get('modelsAnalyzed', []))}")
        
        # Model Coverage Information
        if self.analysisStats.get('modelCoverage'):
            coverage = self.analysisStats['modelCoverage']
            report.append("")
            report.append("MODEL COVERAGE ASSESSMENT:")
            report.append("-" * 30)
            report.append(f"Models Selected: {coverage['totalSelected']}")
            report.append(f"Models with Data: {len(coverage['validModels'])}")
            
            if coverage['invalidModels']:
                report.append(f"Models without Coverage: {', '.join(coverage['invalidModels'])}")
                report.append("(High-res models may not cover your forecast area)")
        
        report.append("")
        
        # Warning Guidance Results
        if self.analysisStats.get('warningGuidanceStats'):
            report.append("WARNING GUIDANCE RESULTS:")
            report.append("(Model consensus on warning categories)")
            report.append("-" * 40)
            
            stats = self.analysisStats['warningGuidanceStats']
            report.append(f"Average Confidence: {stats['avgConfidence']:.2f}")
            report.append(f"Coverage: {stats['coverage']:.1f}% of grid points")
            report.append(f"Valid Points: {stats['validPoints']}")
            report.append(f"Total Models: {stats['totalModels']}")
            
            report.append("\nWarning Category Breakdown:")
            for category, count in stats['categoryBreakdown'].items():
                if count > 0:
                    percentage = (count / float(stats['validPoints'])) * 100
                    report.append(f"  • {category}: {count} points ({percentage:.1f}%)")
            
            # Interpretation
            if stats['avgConfidence'] >= 0.8:
                interpretation = "HIGH CONFIDENCE - Strong model consensus on warning categories"
            elif stats['avgConfidence'] >= 0.6:
                interpretation = "GOOD CONFIDENCE - Generally reliable warning guidance"
            elif stats['avgConfidence'] >= 0.4:
                interpretation = "MODERATE CONFIDENCE - Some uncertainty in warning decisions"
            else:
                interpretation = "LOW CONFIDENCE - High uncertainty, use forecaster judgment"
            
            report.append(f"\nOverall Assessment: {interpretation}")
            report.append("")
        
        # Model Consistency Results
        if self.analysisStats.get('consistencyStats'):
            report.append("MODEL CONSISTENCY RESULTS:")
            report.append("(How consistent each model is across recent runs - Analysis Only)")
            report.append("-" * 60)
            
            for modelName, stats in self.analysisStats['consistencyStats'].items():
                report.append(f"\n{modelName}:")
                report.append(f"  • Average Consistency: {stats['avgConsistency']:.1f}%")
                report.append(f"  • Range: {stats['minConsistency']:.0f}% - {stats['maxConsistency']:.0f}%")
                report.append(f"  • Significant Wind Coverage: {stats['significantPercent']:.1f}%")
                report.append(f"  • Valid Data Coverage: {stats['validCoverage']:.1f}%")
                report.append(f"  • Model Runs Used: {stats['runsUsed']}")
                
                # Interpretation
                if stats['avgConsistency'] >= 75:
                    interpretation = "HIGHLY CONSISTENT - Reliable guidance"
                elif stats['avgConsistency'] >= 60:
                    interpretation = "MODERATELY CONSISTENT - Generally reliable"
                elif stats['avgConsistency'] >= 40:
                    interpretation = "INCONSISTENT - Use with caution"
                else:
                    interpretation = "HIGHLY INCONSISTENT - Poor reliability"
                
                report.append(f"  • Assessment: {interpretation}")
            
            report.append("")


        
        # Usage Guidelines
        report.append("HOW TO INTERPRET THE GRIDS:")
        report.append("-" * 30)
        
        if self.analysisStats.get('warningGuidanceStats'):
            report.append("WarningGuidance Grid:")
            report.append("  • Single grid showing recommended warning category + confidence")
            report.append("  • Integer part = Warning Category:")
            report.append("    - 0 = No Warning")
            report.append("    - 1 = Small Craft Advisory")  
            report.append("    - 2 = Gale Warning")
            report.append("    - 3 = Storm Warning")
            report.append("    - 4 = Hurricane Force")
            report.append("  • Decimal part = Confidence Level:")
            report.append("    - .9 = High confidence (80%+ model agreement)")
            report.append("    - .6 = Medium confidence (60-79% agreement)")
            report.append("    - .2 = Low confidence (<60% agreement)")
            report.append("  • Examples: 2.9 = Gale Warning/High Confidence, 1.2 = SCA/Low Confidence")
            report.append("")
        
        if self.analysisStats.get('consistencyStats'):
            report.append("Model Consistency Analysis:")
            report.append("  • Individual model reliability analysis (report only)")
            report.append("  • 75%+: Highly consistent (reliable)")
            report.append("  • 60-74%: Moderately consistent")
            report.append("  • 40-59%: Inconsistent (use caution)")
            report.append("  • <40%: Highly inconsistent (poor reliability)")
            report.append("")
        
        # Operational Workflow
        report.append("RECOMMENDED WORKFLOW:")
        report.append("-" * 25)
        report.append("1. Check WarningGuidance grid for recommended warning categories")
        report.append("2. High confidence areas (x.9): Use model consensus")
        report.append("3. Medium confidence areas (x.6): Generally reliable, verify with obs")
        report.append("4. Low confidence areas (x.2): Use forecaster judgment and local knowledge")
        report.append("5. Review consistency statistics for model selection guidance")
        report.append("6. Apply local observations and meteorological reasoning")
        report.append("")
        
        # Technical Notes
        report.append("TECHNICAL NOTES:")
        report.append("-" * 20)
        report.append("• Warning guidance uses all available model data")
        report.append("• Categories based on operational thresholds: 20, 35, 50, 65 kt")
        report.append("• Confidence based on percentage of models agreeing on category")
        report.append("• Additional confidence reduction for high spreads near thresholds")
        report.append("• Streamlined approach creates maximum value with single grid")
        report.append("• Colors: Blue <20kt, Green 20-34kt, Yellow 35-49kt, Brown 50-64kt, Red 65+kt")
        
        report.append("\n" + "=" * 70)
        
        # Insert report into text widget
        reportText = "\n".join(report)
        self.reportText.insert(tk.END, reportText)
        self.reportText.config(state=tk.DISABLED)  # Make read-only
    
    def saveReport(self):
        """Save report to text file"""
        try:
            import tkinter.filedialog as filedialog
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                title="Save Analysis Report"
            )
            if filename:
                with open(filename, 'w') as f:
                    f.write(self.reportText.get(1.0, tk.END))
                # Show brief confirmation message
                self.root.title(f"Report Saved - {filename}")
                self.root.after(3000, lambda: self.root.title("Model Guidance Analysis Report"))
        except Exception as e:
            # Simple error handling
            self.root.title(f"Save Error: {str(e)}")
            self.root.after(3000, lambda: self.root.title("Model Guidance Analysis Report"))
    
    def closeReport(self):
        """Close the report window"""
        self.root.destroy()

class Procedure (SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
    
    def getModelRunsWithFallback(self, modelName, runCount):
        """Get the last N runs of a model, with fallback for missing runs"""
        modelRuns = []
        
        for run in range(runCount):
            runOffset = -run  # 0, -1, -2, -3, etc.
            db = self.findDatabase(modelName, runOffset)
            
            if db is not None:
                modelRuns.append((runOffset, db.modelIdentifier()))
        
        return modelRuns
    
    def getWindSpeedForRun(self, modelId, timeRange):
        """Get wind speed grid for a specific model run and time"""
        try:
            wind = self.getGrids(modelId, "Wind", "SFC", timeRange, mode="First", noDataError=0)
            if wind is not None:
                (mag, dir) = wind  # Extract magnitude component
                return mag
        except:
            # Model may not have data for this time/location
            pass
        return None
    
    def getCurrentModelWindSpeed(self, modelId, timeRange):
        """Get current run wind speed for agreement analysis"""
        try:
            db = self.findDatabase(modelId, 0)  # Current run
            if db is not None:
                wind = self.getGrids(db.modelIdentifier(), "Wind", "SFC", timeRange, mode="First", noDataError=0)
                if wind is not None:
                    (mag, dir) = wind
                    return mag
        except:
            # Model may not have data for this grid area
            pass
        return None
    
    def validateModelCoverage(self, selectedModels, timeRange):
        """Check which models actually have data for the selected time range"""
        validModels = {}
        invalidModels = []
        
        # Get a test time from the range
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
        if not gridinfos:
            return validModels, invalidModels
        
        testTimeRange = gridinfos[0].gridTime()
        
        for modelId, modelInfo in selectedModels.items():
            # Test if we can get current wind data
            testWind = self.getCurrentModelWindSpeed(modelId, testTimeRange)
            if testWind is not None:
                validModels[modelId] = modelInfo
            else:
                invalidModels.append(modelInfo['displayName'])
        
        return validModels, invalidModels
    
    def operationalThresholdConfidence(self, models, meanWind):
        """
        Calculate confidence based on operational thresholds: 20, 35, 50, 65 kt
        Models that cross warning thresholds create operational problems
        """
        thresholds = [20, 35, 50, 65]
        spread = max(models) - min(models)
        minModel = min(models)
        maxModel = max(models)
        
        # Count how many critical thresholds the models span
        crossedThresholds = []
        for threshold in thresholds:
            if minModel < threshold <= maxModel:
                crossedThresholds.append(threshold)
        
        numCrossings = len(crossedThresholds)
        
        # Base confidence depends on threshold crossings
        if numCrossings == 0:
            # All models in same warning category - this is good!
            baseConfidence = 85
            
        elif numCrossings == 1:
            # Models disagree about one warning threshold - concerning
            baseConfidence = 40
            
        elif numCrossings == 2:
            # Models span multiple warning categories - serious problem
            baseConfidence = 15
            
        else:
            # Models disagree across many categories - critical issue
            baseConfidence = 5
        
        # Apply additional penalties for large spreads within categories
        if numCrossings == 0:
            # Even within same category, large spreads reduce confidence
            if meanWind < 20:
                # Below SCA threshold - be more tolerant
                tolerance = 8
            elif meanWind < 35:
                # SCA range (20-35) - moderate tolerance
                tolerance = 6
            elif meanWind < 50:
                # Gale range (35-50) - less tolerance
                tolerance = 5
            elif meanWind < 65:
                # Storm range (50-65) - strict
                tolerance = 4
            else:
                # Hurricane force - very strict
                tolerance = 3
                
            if spread > tolerance:
                penalty = (spread - tolerance) * 5
                baseConfidence = max(baseConfidence - penalty, 20)
        
        return min(baseConfidence, 95)

    def createWarningGuidanceGrid(self, allModelData, timeRange, windThreshold):
        """
        Create a single comprehensive warning guidance grid that shows:
        - Recommended warning category (1=SCA, 2=Gale, 3=Storm, 4=Hurricane)  
        - Confidence level (decimal part: .9=high, .5=medium, .1=low confidence)
        Example: 2.8 = Gale Warning with high confidence, 1.2 = SCA with low confidence
        """
        print(f"Creating warning guidance grid with {len(allModelData)} model datasets")
        
        if not allModelData:
            print("No model data available for warning guidance grid")
            return None
            
        # Get a reference grid for shape
        referenceGrid = allModelData[0][0]
        print(f"Reference grid shape: {referenceGrid.shape}")
        guidance = self.newGrid(0.5)  # Default to 0.5 (no warning, medium confidence)
        
        # Warning thresholds
        thresholds = [20, 35, 50, 65]  # SCA, Gale, Storm, Hurricane
        categories = ["No Warning", "Small Craft Advisory", "Gale Warning", "Storm Warning", "Hurricane Force"]
        
        # Initialize stats tracking
        totalPoints = 0
        validPoints = 0
        categoryStats = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}  # Count for each category
        confidenceValues = []
        
        print("Processing grid points...")
        
        # Process each grid point
        for i in range(referenceGrid.shape[0]):
            for j in range(referenceGrid.shape[1]):
                # Collect all model values for this grid point
                allModels = []
                
                # Get values from all model runs
                for modelWindGrids in allModelData:
                    for windGrid in modelWindGrids:
                        if not isnan(windGrid[i, j]):
                            allModels.append(windGrid[i, j])
                
                if len(allModels) >= 2:
                    totalPoints += 1
                    
                    # Determine warning category for each model
                    modelCategories = []
                    for wind in allModels:
                        if wind >= 65:
                            modelCategories.append(4)  # Hurricane
                        elif wind >= 50:
                            modelCategories.append(3)  # Storm
                        elif wind >= 35:
                            modelCategories.append(2)  # Gale
                        elif wind >= 20:
                            modelCategories.append(1)  # SCA
                        else:
                            modelCategories.append(0)  # No warning
                    
                    # Find consensus category (most common)
                    from collections import Counter
                    categoryCounts = Counter(modelCategories)
                    consensusCategory = categoryCounts.most_common(1)[0][0]
                    consensusCount = categoryCounts.most_common(1)[0][1]
                    
                    # Calculate confidence based on consensus strength
                    consensusRatio = float(consensusCount) / len(modelCategories)
                    
                    if consensusRatio >= 0.8:
                        confidence = 0.9  # High confidence
                    elif consensusRatio >= 0.6:
                        confidence = 0.6  # Medium confidence  
                    else:
                        confidence = 0.2  # Low confidence
                    
                    # Additional confidence adjustment for spread near thresholds
                    meanWind = mean(allModels)
                    windSpread = max(allModels) - min(allModels)
                    
                    # Reduce confidence if there's high spread near category boundaries
                    for threshold in thresholds:
                        if abs(meanWind - threshold) <= 8 and windSpread > 10:
                            confidence = max(confidence - 0.3, 0.1)
                            break
                    
                    # Store result: category + confidence
                    guidanceValue = consensusCategory + confidence
                    guidance[i, j] = guidanceValue
                    
                    # Track statistics
                    categoryStats[consensusCategory] += 1
                    confidenceValues.append(confidence)
                    validPoints += 1
                    
                else:
                    # Not enough model data
                    guidance[i, j] = 0.5  # No warning, medium confidence
        
        print(f"Processed {validPoints} valid points out of {totalPoints} total points")
        
        # Calculate statistics
        if validPoints > 0:
            avgConfidence = mean(confidenceValues)
            coverage = (float(validPoints) / totalPoints) * 100.0 if totalPoints > 0 else 0.0
            
            print(f"Average confidence: {avgConfidence:.2f}, Coverage: {coverage:.1f}%")
            
            # Store stats
            if not hasattr(self, 'analysisStats'):
                self.analysisStats = {'warningGuidanceStats': {}}
            if 'warningGuidanceStats' not in self.analysisStats:
                self.analysisStats['warningGuidanceStats'] = {}
                
            self.analysisStats['warningGuidanceStats'] = {
                'avgConfidence': avgConfidence,
                'coverage': coverage,
                'validPoints': validPoints,
                'totalModels': len(allModelData),
                'categoryBreakdown': {
                    'No Warning': categoryStats[0],
                    'Small Craft Advisory': categoryStats[1], 
                    'Gale Warning': categoryStats[2],
                    'Storm Warning': categoryStats[3],
                    'Hurricane Force': categoryStats[4]
                }
            }
        
        # Create the grid
        try:
            print("Creating WarningGuidance grid...")
            self.createGrid("Fcst", "WarningGuidance", "SCALAR", guidance, timeRange,
                          minAllowedValue=0.0, maxAllowedValue=5.0)
            print("WarningGuidance grid created successfully!")
            return guidance
        except Exception as e:
            print(f"Error creating WarningGuidance grid: {e}")
            return None
    
    def calculateConsistencyStats(self, windSpeedGrids, modelName, windThreshold):
        """Calculate consistency statistics for a model without creating grids"""
        if len(windSpeedGrids) < 2:
            return None
        
        # Stack the wind speed grids from different runs
        modelArray = array(windSpeedGrids)
        meanWind = mean(modelArray, axis=0)
        
        # Create mask for areas where ALL model runs have valid data
        validDataMask = ~isnan(meanWind)
        for grid in windSpeedGrids:
            validDataMask = validDataMask & ~isnan(grid)
        
        # Create mask for significant winds only (within valid data areas)
        significantWindMask = (meanWind >= windThreshold) & validDataMask
        
        if any(significantWindMask.flat):
            # Calculate confidence values for statistics
            consistencyValues = []
            
            for i in range(meanWind.shape[0]):
                for j in range(meanWind.shape[1]):
                    if significantWindMask[i, j]:
                        # Get model values for this grid point
                        models = [grid[i, j] for grid in windSpeedGrids if not isnan(grid[i, j])]
                        if len(models) >= 2:
                            consistency = self.operationalThresholdConfidence(models, meanWind[i, j])
                            consistencyValues.append(consistency)
            
            # Count points for statistics
            totalPoints = validDataMask.size
            validPoints = sum(validDataMask.flat)
            significantPoints = sum(significantWindMask.flat)
            
            if validPoints > 0 and len(consistencyValues) > 0:
                validPercent = (float(validPoints) / totalPoints) * 100.0
                significantPercent = (float(significantPoints) / validPoints) * 100.0 if validPoints > 0 else 0.0
                
                avgConsistency = mean(consistencyValues)
                minConsistency = min(consistencyValues)
                maxConsistency = max(consistencyValues)
                
                # Store stats for summary
                if not hasattr(self, 'analysisStats'):
                    self.analysisStats = {'consistencyStats': {}, 'agreementStats': {}}
                if 'consistencyStats' not in self.analysisStats:
                    self.analysisStats['consistencyStats'] = {}
                
                self.analysisStats['consistencyStats'][modelName] = {
                    'avgConsistency': avgConsistency,
                    'minConsistency': minConsistency,
                    'maxConsistency': maxConsistency,
                    'significantPercent': significantPercent,
                    'validCoverage': validPercent,
                    'runsUsed': len(windSpeedGrids)
                }
    
    def createModelConsistencyGrid(self, windSpeedGrids, modelName, timeRange, windThreshold):
        """Create consistency grid for a single model across multiple runs using threshold crossing method"""
        if len(windSpeedGrids) < 2:
            return None
        
        # Stack the wind speed grids from different runs
        modelArray = array(windSpeedGrids)
        meanWind = mean(modelArray, axis=0)
        
        # Create mask for areas where ALL model runs have valid data
        validDataMask = ~isnan(meanWind)
        for grid in windSpeedGrids:
            validDataMask = validDataMask & ~isnan(grid)
        
        # Create mask for significant winds only (within valid data areas)
        significantWindMask = (meanWind >= windThreshold) & validDataMask
        
        # Only calculate consistency where winds are significant AND data exists
        consistency = self.newGrid(float('nan'))  # Default to NaN for no data areas
        
        if any(significantWindMask.flat):
            # Calculate confidence using threshold crossing method for each grid point
            consistencyValues = zeros_like(meanWind)
            
            for i in range(meanWind.shape[0]):
                for j in range(meanWind.shape[1]):
                    if significantWindMask[i, j]:
                        # Get model values for this grid point
                        models = [grid[i, j] for grid in windSpeedGrids if not isnan(grid[i, j])]
                        if len(models) >= 2:
                            consistencyValues[i, j] = self.operationalThresholdConfidence(models, meanWind[i, j])
                        else:
                            consistencyValues[i, j] = float('nan')
                    elif validDataMask[i, j] and meanWind[i, j] < windThreshold:
                        # Light winds get neutral confidence
                        consistencyValues[i, j] = 50.0
                    else:
                        consistencyValues[i, j] = float('nan')
            
            consistency = consistencyValues
            
            # Count points for statistics
            totalPoints = validDataMask.size
            validPoints = sum(validDataMask.flat)
            significantPoints = sum(significantWindMask.flat)
            
            if validPoints > 0:
                validPercent = (float(validPoints) / totalPoints) * 100.0
                significantPercent = (float(significantPoints) / validPoints) * 100.0 if validPoints > 0 else 0.0
                
                # Calculate detailed stats for significant wind areas
                if significantPoints > 0:
                    significantConsistency = consistency[significantWindMask]
                    validSignificantConsistency = significantConsistency[~isnan(significantConsistency)]
                    if len(validSignificantConsistency) > 0:
                        avgConsistency = mean(validSignificantConsistency)
                        minConsistency = min(validSignificantConsistency)
                        maxConsistency = max(validSignificantConsistency)
                        
                        # Store stats for summary
                        if not hasattr(self, 'analysisStats'):
                            self.analysisStats = {'consistencyStats': {}, 'agreementStats': {}, 'overallStats': {}}
                        if 'consistencyStats' not in self.analysisStats:
                            self.analysisStats['consistencyStats'] = {}
                        
                        self.analysisStats['consistencyStats'][modelName] = {
                            'avgConsistency': avgConsistency,
                            'minConsistency': minConsistency,
                            'maxConsistency': maxConsistency,
                            'significantPercent': significantPercent,
                            'validCoverage': validPercent,
                            'runsUsed': len(windSpeedGrids)
                        }
            
            # Create grid with color table values
            gridName = f"WindSpeedConsistency{modelName}"
            try:
                self.createGrid("Fcst", gridName, "SCALAR", consistency, timeRange, 
                              minAllowedValue=0.0, maxAllowedValue=100.0)
                
                return consistency
            except Exception as e:
                return None
        else:
            return None
    
    def createModelAgreementGrid(self, currentWindSpeeds, modelNames, timeRange, windThreshold):
        """Create agreement grid showing how well current model runs agree using threshold crossing method"""
        if len(currentWindSpeeds) < 2:
            return None
        
        # Stack current model grids
        modelArray = array(currentWindSpeeds)
        meanWind = mean(modelArray, axis=0)
        
        # Create mask for areas where ALL models have valid data
        validDataMask = ~isnan(meanWind)
        for grid in currentWindSpeeds:
            validDataMask = validDataMask & ~isnan(grid)
        
        # Create mask for significant winds only (within valid data areas)
        significantWindMask = (meanWind >= windThreshold) & validDataMask
        
        # Only calculate agreement where winds are significant AND all models have data
        agreement = self.newGrid(float('nan'))  # Default to NaN for no data areas
        
        if any(significantWindMask.flat):
            # Calculate confidence using threshold crossing method for each grid point
            agreementValues = zeros_like(meanWind)
            
            for i in range(meanWind.shape[0]):
                for j in range(meanWind.shape[1]):
                    if significantWindMask[i, j]:
                        # Get model values for this grid point
                        models = [grid[i, j] for grid in currentWindSpeeds if not isnan(grid[i, j])]
                        if len(models) >= 2:
                            agreementValues[i, j] = self.operationalThresholdConfidence(models, meanWind[i, j])
                        else:
                            agreementValues[i, j] = float('nan')
                    elif validDataMask[i, j] and meanWind[i, j] < windThreshold:
                        # Light winds get neutral agreement
                        agreementValues[i, j] = 50.0
                    else:
                        agreementValues[i, j] = float('nan')
            
            agreement = agreementValues
            
            # Statistics
            totalPoints = validDataMask.size
            validPoints = sum(validDataMask.flat)
            significantPoints = sum(significantWindMask.flat)
            
            if validPoints > 0:
                validPercent = (float(validPoints) / totalPoints) * 100.0
                significantPercent = (float(significantPoints) / validPoints) * 100.0 if validPoints > 0 else 0.0
                
                # Calculate and store stats
                if significantPoints > 0:
                    significantAgreement = agreement[significantWindMask]
                    validSignificantAgreement = significantAgreement[~isnan(significantAgreement)]
                    if len(validSignificantAgreement) > 0:
                        avgAgreement = mean(validSignificantAgreement)
                        minAgreement = min(validSignificantAgreement)
                        maxAgreement = max(validSignificantAgreement)
                        
                        # Ensure analysisStats exists and store stats
                        if not hasattr(self, 'analysisStats'):
                            self.analysisStats = {'consistencyStats': {}, 'agreementStats': {}, 'overallStats': {}}
                        
                        self.analysisStats['agreementStats'] = {
                            'avgAgreement': avgAgreement,
                            'minAgreement': minAgreement,
                            'maxAgreement': maxAgreement,
                            'significantPercent': significantPercent,
                            'validCoverage': validPercent,
                            'modelsUsed': len(modelNames)
                        }
            
            # Create grid with color table values
            gridName = "WindSpeedAgreement"
            try:
                self.createGrid("Fcst", gridName, "SCALAR", agreement, timeRange,
                              minAllowedValue=0.0, maxAllowedValue=100.0)
                
                return agreement
            except Exception as e:
                return None
        else:
            return None
    


    def showGUI(self, editArea, timeRange):
        """Show the custom GUI and get parameters"""
        self.editArea = editArea
        self.timeRange = timeRange
        self.varDict = None
        
        root = tk.Tk()
        gui = ModelGuidanceGUI(root, self.guiCallback)
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
        
        # Initialize stats
        self.analysisStats = {
            'modelsAnalyzed': [],
            'timePeriodsProcessed': 0,
            'warningGuidanceStats': {},
            'consistencyStats': {},
            'modelCoverage': {}
        }
        
        # Get parameters
        selectedModels = varDict["Selected Models"]
        createWarningGuidance = varDict["Create Warning Guidance"]
        runConsistency = varDict["Run Consistency"]
        windThreshold = varDict["Wind Threshold"]
        
        if len(selectedModels) == 0:
            return
        
        # Validate model coverage for this grid area
        validModels, invalidModels = self.validateModelCoverage(selectedModels, timeRange)
        
        # Store coverage information
        self.analysisStats['modelCoverage'] = {
            'validModels': list(validModels.keys()),
            'invalidModels': invalidModels,
            'totalSelected': len(selectedModels)
        }
        
        if len(validModels) == 0:
            # No valid models found - show report anyway with coverage info
            AnalysisReportWindow(self.analysisStats, windThreshold)
            return
        
        # Use only valid models for analysis
        selectedModels = validModels
        
        # Store analyzed models for summary
        self.analysisStats['modelsAnalyzed'] = list(selectedModels.keys())
        
        # Get forecast grid info
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
        
        self.analysisStats['timePeriodsProcessed'] = len(gridinfos)
        
        # Process each forecast time period
        for i, gridinfo in enumerate(gridinfos):
            GridTimeRange = gridinfo.gridTime()
            
            # Collect ALL model data (current + historical runs) for threshold analysis
            allModelData = []
            
            # Collect current run data for agreement analysis
            currentWindSpeeds = []
            modelNames = []
            
            for modelId, modelInfo in selectedModels.items():
                runCount = modelInfo['runCount']
                
                # Get historical runs for this model
                modelRuns = self.getModelRunsWithFallback(modelId, runCount)
                
                # Collect wind speeds from all runs of this model
                modelWindGrids = []
                for runOffset, modelIdentifier in modelRuns:
                    windSpeed = self.getWindSpeedForRun(modelIdentifier, GridTimeRange)
                    if windSpeed is not None:
                        modelWindGrids.append(windSpeed)
                        
                        # Store current run for agreement analysis
                        if runOffset == 0:  # Current run
                            currentWindSpeeds.append(windSpeed)
                            modelNames.append(modelId)
                
                if len(modelWindGrids) >= 1:  # At least current run
                    allModelData.append(modelWindGrids)
                    
                    # Calculate consistency statistics for report (no grids created)
                    if runConsistency == "Yes" and len(modelWindGrids) >= 2:
                        self.calculateConsistencyStats(modelWindGrids, modelId, windThreshold)
            
            # Create warning guidance grid if enabled
            if createWarningGuidance == "Yes" and len(allModelData) >= 1:
                print(f"Creating WarningGuidance grid with {len(allModelData)} models")
                self.createWarningGuidanceGrid(allModelData, GridTimeRange, windThreshold)
        
        # Show report window
        AnalysisReportWindow(self.analysisStats, windThreshold)
        
        return None