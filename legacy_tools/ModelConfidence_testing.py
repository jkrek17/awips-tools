# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# Model_Guidance_Assistant.py - Comprehensive Model Analysis Tool
#
# Author: jason.krekeler
# Combines model consistency and inter-model agreement analysis
# to help forecasters make informed model selection decisions
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
        self.master.geometry("650x950")
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
        # Main frame
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
        
        # Model Selection Frame
        modelFrame = tk.LabelFrame(mainFrame, text="Select Models for Analysis", padx=15, pady=10)
        modelFrame.pack(fill=tk.X, pady=(0, 15))
        
        # Model definitions
        models = [
            ("GFS (Global Forecast System)", "GFS", 4),
            ("ECMWF (European Centre)", "nECMWF0p25", 2), 
            ("CMC (Canadian Global)", "CMCnh", 4),
            ("UKMET (UK Met Office)", "UKMEThires4", 4),
            ("GEFS Mean (GFS Ensemble)", "GEFSMEAN", 4),
            ("ECENS Mean (ECMWF Ensemble)", "ECENSMEAN", 2)
        ]
        
        # Create checkboxes for model selection
        self.modelSelections = {}
        self.modelInfo = {}
        
        for displayName, modelId, runCount in models:
            var = tk.StringVar()
            var.set("No")
            self.modelSelections[modelId] = var
            self.modelInfo[modelId] = {
                'displayName': displayName,
                'runCount': runCount
            }
            
            # Checkbox with model info
            cb = tk.Checkbutton(modelFrame, text=displayName, 
                              variable=var, onvalue="Yes", offvalue="No",
                              command=self.updateSelection, anchor=tk.W, font=("Arial", 10))
            cb.pack(fill=tk.X, pady=3)
        
        # Status labels
        self.statusLabel = tk.Label(modelFrame, text="No Models Selected", 
                                  font=("Arial", 11, "bold"), fg="red")
        self.statusLabel.pack(pady=(10, 0))
        
        self.messageLabel = tk.Label(modelFrame, text="", 
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
        
        # Consistency Analysis
        self.runConsistency = tk.StringVar()
        self.runConsistency.set("Yes")
        tk.Checkbutton(optionsFrame, text="Model Consistency Analysis", 
                      variable=self.runConsistency, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=2)
        
        tk.Label(optionsFrame, text="• Analyzes how steady each model has been across recent runs",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Creates: WindSpeedConsistency[Model] grids",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Agreement Analysis
        self.runAgreement = tk.StringVar()
        self.runAgreement.set("Yes")
        tk.Checkbutton(optionsFrame, text="Model Agreement Analysis", 
                      variable=self.runAgreement, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Analyzes how well selected models agree with each other",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Creates: WindSpeedAgreement grid",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Guidance Grid
        self.createGuidance = tk.StringVar()
        self.createGuidance.set("Yes")
        tk.Checkbutton(optionsFrame, text="Model Guidance Grid", 
                      variable=self.createGuidance, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Combines consistency + agreement into actionable guidance",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Creates: WindSpeedGuidance grid (higher = more reliable models)",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Results Info Frame
        resultsFrame = tk.LabelFrame(mainFrame, text="What This Tool Helps You Decide", padx=15, pady=10)
        resultsFrame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(resultsFrame, text="✓ Which models are being consistent vs erratic?",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="✓ Where do models agree vs disagree geographically?",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="✓ What areas need more forecaster attention?",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="✓ Which model guidance is most reliable right now?",
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
    
    def getValues(self):
        """Return dictionary of selected models and analysis options"""
        selectedModels = {}
        for modelId, var in self.modelSelections.items():
            if var.get() == "Yes":
                selectedModels[modelId] = self.modelInfo[modelId]
        
        return {
            "Selected Models": selectedModels,
            "Run Consistency": self.runConsistency.get(),
            "Run Agreement": self.runAgreement.get(),
            "Create Guidance": self.createGuidance.get(),
            "Wind Threshold": self.windThreshold.get()
        }
    
    def runTool(self):
        """Validate inputs and run the tool"""
        selectedCount = sum(1 for var in self.modelSelections.values() if var.get() == "Yes")
        if selectedCount == 0:
            self.messageLabel.config(text="ERROR: Select at least 1 model!", fg="red")
            self.master.after(3000, lambda: self.messageLabel.config(text=""))
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
        self.root.geometry("900x700")
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
        
        tk.Button(buttonFrame, text="Close Report", command=self.closeReport,
                 font=("Arial", 11, "bold"), bg="lightcoral", width=12).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(buttonFrame, text="Save Report", command=self.saveReport,
                 font=("Arial", 11), bg="lightgreen", width=12).pack(side=tk.RIGHT)
    
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
        report.append("")
        
        # Model Consistency Results
        if self.analysisStats.get('consistencyStats'):
            report.append("MODEL CONSISTENCY RESULTS:")
            report.append("(How steady each model has been across recent runs)")
            report.append("-" * 50)
            
            for modelName, stats in self.analysisStats['consistencyStats'].items():
                report.append(f"\n{modelName}:")
                report.append(f"  • Average Consistency: {stats['avgConsistency']:.1f}%")
                report.append(f"  • Range: {stats['minConsistency']:.0f}% - {stats['maxConsistency']:.0f}%")
                report.append(f"  • Significant Wind Coverage: {stats['significantPercent']:.1f}%")
                report.append(f"  • Model Runs Used: {stats['runsUsed']}")
                
                # Interpretation
                if stats['avgConsistency'] >= 80:
                    interpretation = "VERY RELIABLE - Model has been very consistent"
                elif stats['avgConsistency'] >= 65:
                    interpretation = "RELIABLE - Model has been fairly consistent"
                elif stats['avgConsistency'] >= 50:
                    interpretation = "MODERATE - Model has shown some variability"
                else:
                    interpretation = "VARIABLE - Model has been inconsistent"
                
                report.append(f"  • Assessment: {interpretation}")
            
            report.append("")
        
        # Model Agreement Results
        if self.analysisStats.get('agreementStats'):
            report.append("MODEL AGREEMENT RESULTS:")
            report.append("(How well current model runs agree with each other)")
            report.append("-" * 50)
            
            stats = self.analysisStats['agreementStats']
            report.append(f"Models Compared: {stats['modelsUsed']}")
            report.append(f"Average Agreement: {stats['avgAgreement']:.1f}%")
            report.append(f"Agreement Range: {stats['minAgreement']:.0f}% - {stats['maxAgreement']:.0f}%")
            report.append(f"Significant Wind Coverage: {stats['significantPercent']:.1f}%")
            
            # Interpretation
            if stats['avgAgreement'] >= 80:
                interpretation = "STRONG CONSENSUS - Models agree well"
            elif stats['avgAgreement'] >= 65:
                interpretation = "GOOD CONSENSUS - Models mostly agree"
            elif stats['avgAgreement'] >= 50:
                interpretation = "MODERATE CONSENSUS - Some model disagreement"
            else:
                interpretation = "POOR CONSENSUS - Significant model disagreement"
            
            report.append(f"Assessment: {interpretation}")
            report.append("")
        
        # Overall Guidance Assessment
        if self.analysisStats.get('overallStats'):
            report.append("OVERALL GUIDANCE ASSESSMENT:")
            report.append("(Combined consistency + agreement reliability)")
            report.append("-" * 50)
            
            stats = self.analysisStats['overallStats']
            report.append(f"Average Guidance Confidence: {stats['avgGuidance']:.1f}%")
            report.append(f"Confidence Range: {stats['minGuidance']:.0f}% - {stats['maxGuidance']:.0f}%")
            
            # Operational recommendations
            if stats['avgGuidance'] >= 80:
                recommendation = "HIGH CONFIDENCE - Trust model guidance in most areas"
                action = "• Use model consensus for forecasting\n• Focus attention on isolated low-confidence areas"
            elif stats['avgGuidance'] >= 65:
                recommendation = "MODERATE CONFIDENCE - Models generally reliable"
                action = "• Use models as primary guidance with monitoring\n• Apply forecaster expertise in medium-confidence areas"
            elif stats['avgGuidance'] >= 50:
                recommendation = "LOW CONFIDENCE - Apply significant forecaster expertise"
                action = "• Use models as reference only\n• Apply substantial manual analysis and local knowledge"
            else:
                recommendation = "VERY LOW CONFIDENCE - Models highly unreliable"
                action = "• Do not rely on model guidance\n• Use manual analysis and alternative data sources"
            
            report.append(f"Overall Assessment: {recommendation}")
            report.append("Recommended Actions:")
            report.append(action)
            report.append("")
        
        # Usage Guidelines
        report.append("HOW TO INTERPRET THE GRIDS:")
        report.append("-" * 30)
        report.append("WindSpeedConsistency[Model] Grids:")
        report.append("  • 80-100%: Model very steady, high confidence")
        report.append("  • 65-79%:  Model fairly consistent, good confidence")
        report.append("  • 50-64%:  Model somewhat variable, moderate confidence")
        report.append("  • 0-49%:   Model inconsistent, low confidence")
        report.append("")
        report.append("WindSpeedAgreement Grid:")
        report.append("  • 80-100%: Strong model consensus")
        report.append("  • 65-79%:  Good model agreement")
        report.append("  • 50-64%:  Moderate model disagreement")
        report.append("  • 0-49%:   Poor model consensus")
        report.append("")
        report.append("WindSpeedGuidance Grid:")
        report.append("  • >75%:    Trust model consensus")
        report.append("  • 50-75%:  Apply forecaster judgment")
        report.append("  • <50%:    Manual analysis recommended")
        report.append("  • 50%:     Light wind areas (below threshold)")
        report.append("")
        
        # Operational Workflow
        report.append("RECOMMENDED WORKFLOW:")
        report.append("-" * 25)
        report.append("1. Examine WindSpeedGuidance grid for overall reliability")
        report.append("2. Focus editing on low guidance areas (<60%)")
        report.append("3. Check individual model consistency for model selection")
        report.append("4. Use agreement grid to identify forecast challenges")
        report.append("5. Apply local knowledge in low-confidence regions")
        report.append("")
        
        # Technical Notes
        report.append("TECHNICAL NOTES:")
        report.append("-" * 20)
        report.append(f"• Analysis limited to winds ≥{self.windThreshold} knots")
        report.append("• Light wind areas set to neutral 50% values")
        report.append("• Consistency based on recent model run variability")
        report.append("• Agreement based on current model spread")
        report.append("• Guidance combines both metrics equally")
        
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
            pass
        return None
    
    def createModelConsistencyGrid(self, windSpeedGrids, modelName, timeRange, windThreshold):
        """Create consistency grid for a single model across multiple runs"""
        if len(windSpeedGrids) < 2:
            return None
        
        # Stack the wind speed grids from different runs
        modelArray = array(windSpeedGrids)
        stdDev = std(modelArray, axis=0)
        meanWind = mean(modelArray, axis=0)
        
        # Create mask for significant winds only
        significantWindMask = meanWind >= windThreshold
        
        # Only calculate consistency where winds are significant
        consistency = self.newGrid(50.0)  # Default for light winds
        
        if any(significantWindMask.flat):
            # Calculate relative standard deviation only for significant winds
            relativeStdDev = stdDev / (meanWind + 0.1)  # Avoid division by zero
            
            # Normalize only among significant wind areas
            significantStdDev = where(significantWindMask, relativeStdDev, 0)
            maxRelStd = max(significantStdDev.flat)
            
            if maxRelStd > 0:
                # Calculate consistency for significant winds only
                consistencyValues = 100.0 * (1.0 - (relativeStdDev / maxRelStd))
                consistencyValues = clip(consistencyValues, 0.0, 100.0)
                
                # Apply only to significant wind areas
                consistency = where(significantWindMask, consistencyValues, 50.0)
            
            # Count significant wind points for statistics
            totalPoints = significantWindMask.size
            significantPoints = sum(significantWindMask.flat)
            significantPercent = (float(significantPoints) / totalPoints) * 100.0
            
            # Calculate detailed stats for significant wind areas
            if significantPoints > 0:
                significantConsistency = consistency[significantWindMask]
                avgConsistency = mean(significantConsistency)
                minConsistency = min(significantConsistency)
                maxConsistency = max(significantConsistency)
                
                # Store stats for summary
                if not hasattr(self, 'analysisStats'):
                    self.analysisStats = {'consistencyStats': {}, 'agreementStats': {}, 'overallStats': {}}
                
                self.analysisStats['consistencyStats'][modelName] = {
                    'avgConsistency': avgConsistency,
                    'minConsistency': minConsistency,
                    'maxConsistency': maxConsistency,
                    'significantPercent': significantPercent,
                    'runsUsed': len(windSpeedGrids)
                }
            
            # Create grid
            gridName = f"WindSpeedConsistency{modelName}"
            try:
                self.createGrid("Fcst", gridName, "SCALAR", consistency, timeRange)
                return consistency
            except Exception as e:
                return None
        else:
            return None
    
    def createModelAgreementGrid(self, currentWindSpeeds, modelNames, timeRange, windThreshold):
        """Create agreement grid showing how well current model runs agree"""
        if len(currentWindSpeeds) < 2:
            return None
        
        # Stack current model grids
        modelArray = array(currentWindSpeeds)
        stdDev = std(modelArray, axis=0)
        meanWind = mean(modelArray, axis=0)
        
        # Create mask for significant winds only
        significantWindMask = meanWind >= windThreshold
        
        # Only calculate agreement where winds are significant
        agreement = self.newGrid(50.0)  # Default for light winds
        
        if any(significantWindMask.flat):
            # Calculate relative standard deviation only for significant winds
            relativeStdDev = stdDev / (meanWind + 0.1)
            
            # Normalize only among significant wind areas
            significantStdDev = where(significantWindMask, relativeStdDev, 0)
            maxRelStd = max(significantStdDev.flat)
            
            if maxRelStd > 0:
                agreementValues = 100.0 * (1.0 - (relativeStdDev / maxRelStd))
                agreementValues = clip(agreementValues, 0.0, 100.0)
                
                # Apply only to significant wind areas
                agreement = where(significantWindMask, agreementValues, 50.0)
            
            # Statistics
            totalPoints = significantWindMask.size
            significantPoints = sum(significantWindMask.flat)
            significantPercent = (float(significantPoints) / totalPoints) * 100.0
            
            # Calculate and store stats
            if significantPoints > 0:
                significantAgreement = agreement[significantWindMask]
                avgAgreement = mean(significantAgreement)
                minAgreement = min(significantAgreement)
                maxAgreement = max(significantAgreement)
                
                # Ensure analysisStats exists and store stats
                if not hasattr(self, 'analysisStats'):
                    self.analysisStats = {'consistencyStats': {}, 'agreementStats': {}, 'overallStats': {}}
                
                self.analysisStats['agreementStats'] = {
                    'avgAgreement': avgAgreement,
                    'minAgreement': minAgreement,
                    'maxAgreement': maxAgreement,
                    'significantPercent': significantPercent,
                    'modelsUsed': len(modelNames)
                }
            
            # Create grid
            gridName = "WindSpeedAgreement"
            try:
                self.createGrid("Fcst", gridName, "SCALAR", agreement, timeRange)
                return agreement
            except Exception as e:
                return None
        else:
            return None
    
    def createGuidanceGrid(self, consistencyGrids, agreementGrid, timeRange):
        """Create overall guidance grid combining consistency and agreement"""
        if not consistencyGrids or agreementGrid is None:
            return None
        
        # Average the consistency grids
        if len(consistencyGrids) > 1:
            avgConsistency = mean(array(consistencyGrids), axis=0)
        else:
            avgConsistency = consistencyGrids[0]
        
        # Combine consistency and agreement (equal weighting)
        guidance = (avgConsistency + agreementGrid) / 2.0
        guidance = clip(guidance, 0.0, 100.0)
        
        # Calculate stats for areas with significant winds
        significantMask = guidance > 50.0  # Areas that were analyzed (not light wind default)
        
        if any(significantMask.flat):
            significantGuidance = guidance[significantMask]
            avgGuidance = mean(significantGuidance)
            minGuidance = min(significantGuidance)
            maxGuidance = max(significantGuidance)
            
            # Ensure analysisStats exists and store overall stats
            if not hasattr(self, 'analysisStats'):
                self.analysisStats = {'consistencyStats': {}, 'agreementStats': {}, 'overallStats': {}}
            
            self.analysisStats['overallStats'] = {
                'avgGuidance': avgGuidance,
                'minGuidance': minGuidance,
                'maxGuidance': maxGuidance
            }
        
        # Create grid
        gridName = "WindSpeedGuidance"
        try:
            self.createGrid("Fcst", gridName, "SCALAR", guidance, timeRange)
            return guidance
        except Exception as e:
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
            'consistencyStats': {},
            'agreementStats': {},
            'overallStats': {}
        }
        
        # Get parameters
        selectedModels = varDict["Selected Models"]
        runConsistency = varDict["Run Consistency"]
        runAgreement = varDict["Run Agreement"]
        createGuidance = varDict["Create Guidance"]
        windThreshold = varDict["Wind Threshold"]
        
        if len(selectedModels) == 0:
            return
        
        # Store analyzed models for summary
        self.analysisStats['modelsAnalyzed'] = list(selectedModels.keys())
        
        # Get forecast grid info
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
        
        self.analysisStats['timePeriodsProcessed'] = len(gridinfos)
        
        # Process each forecast time period
        for i, gridinfo in enumerate(gridinfos):
            GridTimeRange = gridinfo.gridTime()
            
            consistencyGrids = []
            currentWindSpeeds = []
            modelNames = []
            
            # 1. CONSISTENCY ANALYSIS
            if runConsistency == "Yes":
                for modelId, modelInfo in selectedModels.items():
                    runCount = modelInfo['runCount']
                    
                    # Get historical runs for consistency
                    modelRuns = self.getModelRunsWithFallback(modelId, runCount)
                    if len(modelRuns) < 2:
                        continue
                    
                    # Collect wind speeds from multiple runs
                    windSpeedGrids = []
                    for runOffset, modelIdentifier in modelRuns:
                        windSpeed = self.getWindSpeedForRun(modelIdentifier, GridTimeRange)
                        if windSpeed is not None:
                            windSpeedGrids.append(windSpeed)
                    
                    # Create consistency grid
                    if len(windSpeedGrids) >= 2:
                        consistency = self.createModelConsistencyGrid(windSpeedGrids, modelId, GridTimeRange, windThreshold)
                        if consistency is not None:
                            consistencyGrids.append(consistency)
            
            # 2. AGREEMENT ANALYSIS
            agreementGrid = None
            if runAgreement == "Yes" and len(selectedModels) >= 2:
                # Get current run data for all models
                for modelId in selectedModels.keys():
                    currentWind = self.getCurrentModelWindSpeed(modelId, GridTimeRange)
                    if currentWind is not None:
                        currentWindSpeeds.append(currentWind)
                        modelNames.append(modelId)
                
                if len(currentWindSpeeds) >= 2:
                    agreementGrid = self.createModelAgreementGrid(currentWindSpeeds, modelNames, GridTimeRange, windThreshold)
            
            # 3. GUIDANCE GRID
            if createGuidance == "Yes":
                guidanceGrid = self.createGuidanceGrid(consistencyGrids, agreementGrid, GridTimeRange)
        
        # Show report window
        AnalysisReportWindow(self.analysisStats, windThreshold)
        
        return None