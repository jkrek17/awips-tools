# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# Model_Difference_Assistant.py - COMPLETE ULTIMATE Enhanced Model Analysis Tool
# FINAL VERSION with Wind Vector Consensus Grids and Model Usefulness Rankings
#
# Author: jason.krekeler (enhanced with wind vector consensus and comprehensive analysis)
# Creates WindConsensus vector grid with barbs, analyzes model differences, and ranks usefulness
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
VariableList = []

import time
import AbsTime
import SmartScript

class ModelDifferenceGUI:
    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Enhanced Marine Wind Model Analysis")
        self.master.geometry("650x1150")
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
            self.messageLabel.config(text="Select 2+ models for consensus and spread analysis", fg="orange")
        else:
            self.statusLabel.config(text=f"{selectedCount} Models Selected", fg="green")
            self.messageLabel.config(text="Ready for comprehensive analysis with wind barbs", fg="green")

    def createWidgets(self):
        # Main frame
        mainFrame = tk.Frame(self.master, padx=15, pady=15)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Enhanced Marine Wind Model Analysis", 
                             font=("Arial", 16, "bold"))
        titleLabel.pack(pady=(0, 5))
        
        # Subtitle
        subtitleLabel = tk.Label(mainFrame, text="With Wind Vector Consensus & Model Rankings", 
                               font=("Arial", 12), fg="navy")
        subtitleLabel.pack(pady=(0, 15))
        
        # Description
        descLabel = tk.Label(mainFrame, 
                           text="Creates WindConsensus grid with barbs + comprehensive model analysis",
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
        self.windThreshold.set(0)  # Default 10 knots
        
        tk.Scale(thresholdFrame, from_=0, to=70, orient=tk.HORIZONTAL, 
                variable=self.windThreshold, command=self.updateThresholdLabel, 
                width=12).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        self.thresholdLabel = tk.Label(thresholdFrame, text="0 kts", width=8, font=("Arial", 10, "bold"))
        self.thresholdLabel.pack(side=tk.RIGHT)
        
        tk.Label(optionsFrame, text="Only analyze areas where wind speed ≥ threshold",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, pady=(0, 10))
        
        # Wind Vector Consensus Analysis
        self.createConsensus = tk.StringVar()
        self.createConsensus.set("Yes")
        tk.Checkbutton(optionsFrame, text="Create Wind Vector Consensus (with Barbs)", 
                      variable=self.createConsensus, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=2)
        
        tk.Label(optionsFrame, text="• Creates WindConsensus grid (VECTOR with wind barbs)",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Use as your starting forecast (shows magnitude + direction)",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Serves as bias reference point for all models",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Model Variability Analysis
        self.runVariability = tk.StringVar()
        self.runVariability.set("Yes")
        tk.Checkbutton(optionsFrame, text="Model Run-to-Run Variability", 
                      variable=self.runVariability, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Analyzes consistency between recent runs of each model",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Creates: WindSpeedVariability[Model] & WindDirVariability[Model]",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Model Spread Analysis
        self.runSpread = tk.StringVar()
        self.runSpread.set("Yes")
        tk.Checkbutton(optionsFrame, text="Current Model Spread Analysis", 
                      variable=self.runSpread, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Analyzes disagreement between current model runs",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Creates: WindSpeedSpread & WindDirSpread grids",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Model Bias Analysis
        self.runBias = tk.StringVar()
        self.runBias.set("Yes")
        tk.Checkbutton(optionsFrame, text="Model Bias Analysis (vs Wind Vector Consensus)", 
                      variable=self.runBias, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Shows which models run high/low compared to wind consensus",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Creates: WindSpeedBias[Model] grids (speed only)",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Combined Uncertainty Grid
        self.createUncertainty = tk.StringVar()
        self.createUncertainty.set("Yes")
        tk.Checkbutton(optionsFrame, text="Combined Uncertainty Grids", 
                      variable=self.createUncertainty, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Combines variability + spread into total uncertainty",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Creates: WindSpeedUncertainty & WindDirUncertainty grids",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Model Usefulness Rankings
        self.calculateUsefulness = tk.StringVar()
        self.calculateUsefulness.set("Yes")
        tk.Checkbutton(optionsFrame, text="Model Usefulness Rankings", 
                      variable=self.calculateUsefulness, onvalue="Yes", offvalue="No",
                      font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))
        
        tk.Label(optionsFrame, text="• Ranks models by consistency, bias, and data quality",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        tk.Label(optionsFrame, text="• Provides specific recommendations for each model",
                font=("Arial", 9), fg="gray").pack(anchor=tk.W, padx=(20, 0))
        
        # Results Info Frame
        resultsFrame = tk.LabelFrame(mainFrame, text="Enhanced Analysis Results", padx=15, pady=10)
        resultsFrame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(resultsFrame, text="🌬️ WindConsensus grid with wind barbs (your starting forecast)",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="🏆 Model usefulness rankings with specific recommendations",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="📊 Bias analysis relative to wind vector consensus",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="📈 Model consistency and uncertainty analysis",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        tk.Label(resultsFrame, text="📋 Comprehensive report with forecaster guidance",
                font=("Arial", 9), fg="darkgreen").pack(anchor=tk.W)
        
        # Buttons Frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(15, 0))
        
        tk.Button(buttonFrame, text="Run Enhanced Analysis", command=self.runTool, 
                 bg="lightblue", font=("Arial", 11, "bold"), width=18).pack(side=tk.LEFT, padx=(0, 10))
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
            "Create Consensus": self.createConsensus.get(),
            "Run Variability": self.runVariability.get(),
            "Run Spread": self.runSpread.get(),
            "Run Bias": self.runBias.get(),
            "Create Uncertainty": self.createUncertainty.get(),
            "Calculate Usefulness": self.calculateUsefulness.get(),
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

class EnhancedReportWindow:
    def __init__(self, analysisStats, windThreshold):
        self.analysisStats = analysisStats
        self.windThreshold = windThreshold
        
        # Create new window
        self.root = tk.Tk()
        self.root.title("Enhanced Wind Vector Model Analysis Report")
        self.root.geometry("1150x950")
        self.root.resizable(True, True)
        
        self.createReportWindow()
        self.root.mainloop()
    
    def createReportWindow(self):
        # Main frame
        mainFrame = tk.Frame(self.root, padx=15, pady=15)
        mainFrame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        titleLabel = tk.Label(mainFrame, text="Enhanced Wind Vector Model Analysis Report", 
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
        self.generateEnhancedReport()
        
        # Buttons frame
        buttonFrame = tk.Frame(mainFrame)
        buttonFrame.pack(fill=tk.X, pady=(15, 0))
        
        tk.Button(buttonFrame, text="Close Report", command=self.closeReport,
                 font=("Arial", 11, "bold"), bg="lightcoral", width=12).pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(buttonFrame, text="Save Report", command=self.saveReport,
                 font=("Arial", 11), bg="lightgreen", width=12).pack(side=tk.RIGHT)
    
    def generateEnhancedReport(self):
        """Generate comprehensive analysis report with wind vector consensus"""
        report = []
        
        # Header
        report.append("=" * 80)
        report.append("ENHANCED MARINE WIND MODEL ANALYSIS REPORT")
        report.append("=" * 80)
        report.append("")
        
        # Analysis Summary
        report.append("ANALYSIS SUMMARY:")
        report.append("-" * 40)
        report.append(f"Wind Speed Threshold: ≥{self.windThreshold} knots")
        report.append(f"Time Periods Analyzed: {self.analysisStats.get('timePeriodsProcessed', 0)}")
        report.append(f"Edit Area Used: {self.analysisStats.get('editAreaUsed', 'Unknown')}")
        report.append(f"Grid Points Analyzed: {self.analysisStats.get('gridPointsAnalyzed', 0):,}")
        report.append("")
        
        # Wind Vector Consensus Information - ENHANCED
        consensusStats = self.analysisStats.get('consensusStats', {})
        if consensusStats:
            report.append("🌬️  WIND VECTOR CONSENSUS (MULTI-MODEL MEAN):")
            report.append("-" * 50)
            report.append(f"📊 Models Used: {', '.join(consensusStats.get('modelsUsed', []))}")
            report.append(f"🎯 Consensus Grid: WindConsensus (VECTOR with wind barbs)")
            report.append("")
            
            if 'speed' in consensusStats:
                speedStats = consensusStats['speed']
                report.append(f"💨 Wind Speed Statistics:")
                report.append(f"   Range: {speedStats.get('min', 0):.1f} to {speedStats.get('max', 0):.1f} kts")
                report.append(f"   Average: {speedStats.get('mean', 0):.1f} kts")
                report.append(f"   Grid Points: {speedStats.get('count', 0):,}")
            
            report.append("")
            report.append("🎯 HOW TO USE THE WIND VECTOR CONSENSUS:")
            report.append("   1. Load 'WindConsensus' grid in GFE")
            report.append("   2. This displays as WIND BARBS (magnitude + direction)")
            report.append("   3. Use this as your STARTING FORECAST")
            report.append("   4. Adjust based on model bias patterns and local effects")
            report.append("")
            report.append("✨ The WindConsensus represents the best estimate from")
            report.append("   all available models and serves as the reference point")
            report.append("   for all bias calculations.")
            report.append("")
        
        # Model Usefulness Rankings
        modelUsefulness = self.analysisStats.get('modelUsefulness', {})
        if modelUsefulness:
            report.append("MODEL USEFULNESS RANKINGS:")
            report.append("-" * 40)
            report.append("Ranked by consistency, bias, availability, and data quality:")
            report.append("")
            
            # Sort models by total score (highest first)
            sortedModels = sorted(modelUsefulness.items(), 
                                key=lambda x: x[1]['totalScore'], reverse=True)
            
            for rank, (modelId, scores) in enumerate(sortedModels, 1):
                report.append(f"{rank}. {modelId} - {scores['category']} (Score: {scores['totalScore']}/100)")
                report.append(f"   📋 {scores['recommendation']}")
                report.append(f"   📊 {', '.join(scores['reasons'])}")
                report.append(f"   🔢 Breakdown: Consistency {scores['consistencyScore']}/40, "
                            f"Bias {scores['biasScore']}/30, "
                            f"Availability {scores['availabilityScore']}/20, "
                            f"Quality {scores['qualityScore']}/10")
                report.append("")
        
        # Model Categories for Quick Reference
        if modelUsefulness:
            excellent = [m for m, s in modelUsefulness.items() if s['category'] == 'EXCELLENT']
            good = [m for m, s in modelUsefulness.items() if s['category'] == 'GOOD']
            fair = [m for m, s in modelUsefulness.items() if s['category'] == 'FAIR']
            poor = [m for m, s in modelUsefulness.items() if s['category'] in ['POOR', 'VERY POOR']]
            
            report.append("QUICK REFERENCE - MODEL CATEGORIES:")
            report.append("-" * 40)
            if excellent:
                report.append(f"🟢 PRIMARY MODELS (Use First): {', '.join(excellent)}")
            if good:
                report.append(f"🟡 SECONDARY MODELS (Good for blending): {', '.join(good)}")
            if fair:
                report.append(f"🟠 CAUTION MODELS (Check conditions): {', '.join(fair)}")
            if poor:
                report.append(f"🔴 AVOID MODELS (Poor performance): {', '.join(poor)}")
            report.append("")
        
        # Variability Analysis Results
        variabilityStats = self.analysisStats.get('variabilityStats', {})
        if variabilityStats:
            report.append("MODEL CONSISTENCY ANALYSIS:")
            report.append("-" * 40)
            report.append("How much each model varies between runs:")
            report.append("")
            
            # Sort models by variability
            modelsByVariability = []
            for model, stats in variabilityStats.items():
                if 'speed' in stats and stats['speed'].get('count', 0) > 0:
                    avgVar = stats['speed'].get('mean', 0)
                    modelsByVariability.append((avgVar, model, stats))
            
            modelsByVariability.sort()  # Sort by variability (low to high)
            
            for avgVar, model, stats in modelsByVariability:
                speedStats = stats['speed']
                report.append(f"  {model}:")
                report.append(f"    Average Variability: {speedStats.get('mean', 0):.1f} kts")
                report.append(f"    Maximum Variability: {speedStats.get('max', 0):.1f} kts")
                
                # Add interpretation
                if avgVar < 1.0:
                    report.append(f"    → ⭐ Very consistent (excellent)")
                elif avgVar < 2.0:
                    report.append(f"    → ✅ Good consistency")
                elif avgVar < 3.0:
                    report.append(f"    → ⚠️ Moderate variability")
                else:
                    report.append(f"    → ❌ High variability - use with caution")
                report.append("")
        
        # Spread Analysis Results
        spreadStats = self.analysisStats.get('spreadStats', {})
        if spreadStats and 'speed' in spreadStats:
            speedSpread = spreadStats['speed']
            maxSpread = speedSpread.get('max', 0)
            avgSpread = speedSpread.get('mean', 0)
            
            report.append("MODEL DISAGREEMENT ANALYSIS:")
            report.append("-" * 40)
            report.append(f"Current model disagreement (spread):")
            report.append(f"  Maximum: {maxSpread:.1f} kts")
            report.append(f"  Average: {avgSpread:.1f} kts")
            
            # Add interpretation
            if maxSpread < 5:
                report.append("  → ✅ Good model agreement (high confidence)")
            elif maxSpread < 10:
                report.append("  → ⚠️ Moderate disagreement")
            else:
                report.append("  → ❌ Large disagreements - consider ensemble approaches")
            report.append("")
        
        # Bias Analysis Results (relative to WindConsensus)
        biasStats = self.analysisStats.get('biasStats', {})
        if biasStats:
            report.append("MODEL BIAS ANALYSIS (vs WindConsensus Vector):")
            report.append("-" * 50)
            
            # Sort models by bias
            modelsByBias = []
            for model, stats in biasStats.items():
                if 'speed' in stats and stats['speed'].get('count', 0) > 0:
                    bias = stats['speed'].get('mean', 0)
                    modelsByBias.append((bias, model, stats))
            
            modelsByBias.sort(key=lambda x: -x[0])  # Sort by bias (high to low)
            
            for bias, model, stats in modelsByBias:
                speedBias = stats['speed']
                report.append(f"  {model}:")
                report.append(f"    Average bias vs consensus: {bias:+.1f} kts")
                report.append(f"    Range: {speedBias.get('min', 0):+.1f} to {speedBias.get('max', 0):+.1f} kts")
                
                # Add interpretation
                if abs(bias) < 0.5:
                    report.append("    → ⭐ Well-calibrated (neutral bias)")
                elif bias > 2.0:
                    report.append("    → ⬆️ Consistently HIGH vs consensus - tends to overforecast")
                elif bias < -2.0:
                    report.append("    → ⬇️ Consistently LOW vs consensus - tends to underforecast")
                elif bias > 0:
                    report.append("    → ↗️ Slight high bias vs consensus")
                else:
                    report.append("    → ↙️ Slight low bias vs consensus")
                report.append("")
        
        # Enhanced Forecaster Guidance
        report.append("ENHANCED FORECASTER GUIDANCE:")
        report.append("-" * 40)
        
        # Generate recommendations
        recommendations = self.generateEnhancedRecommendations()
        for rec in recommendations:
            report.append(f"• {rec}")
        
        report.append("")
        report.append("🎯 ENHANCED GRID USAGE GUIDE:")
        report.append("-" * 40)
        report.append("🌬️  WindConsensus: START HERE - Your base forecast with wind barbs")
        report.append("      (Multi-model mean vector showing both speed and direction)")
        report.append("📊 WindSpeedBias[Model]: How much each model differs from consensus")
        report.append("      (Positive = model runs high, Negative = model runs low)")
        report.append("📈 WindSpeedSpread: Model disagreement areas (uncertainty indicator)")
        report.append("🔄 WindSpeedVariability[Model]: Run-to-run consistency")
        report.append("❓ WindSpeedUncertainty: Combined uncertainty estimate")
        report.append("")
        
        report.append("🚀 RECOMMENDED WORKFLOW:")
        report.append("-" * 40)
        report.append("1. 📋 Load WindConsensus grid (displays with wind barbs)")
        report.append("2. 🔍 Check WindSpeedSpread for high uncertainty areas")
        report.append("3. 📊 Review model rankings to identify most reliable models")
        report.append("4. ⚖️  Apply bias corrections from your preferred models")
        report.append("5. 🌊 Consider local marine effects and observations")
        report.append("6. 🎯 Use WindConsensus as baseline, adjust with top-ranked models")
        report.append("")
        
        report.append("=" * 80)
        report.append("End of Enhanced Report")
        report.append("=" * 80)
        
        # Insert report into text widget
        reportText = "\n".join(report)
        self.reportText.insert(tk.END, reportText)
        self.reportText.config(state=tk.DISABLED)  # Make read-only
    
    def generateEnhancedRecommendations(self):
        """Generate enhanced recommendations including model usefulness"""
        recommendations = []
        
        modelUsefulness = self.analysisStats.get('modelUsefulness', {})
        
        if modelUsefulness:
            # Get best and worst models
            sortedModels = sorted(modelUsefulness.items(), 
                                key=lambda x: x[1]['totalScore'], reverse=True)
            
            if len(sortedModels) > 0:
                bestModel = sortedModels[0]
                recommendations.append(f"🥇 RECOMMENDED PRIMARY MODEL: {bestModel[0]} "
                                     f"(Score: {bestModel[1]['totalScore']}/100)")
            
            # Find models by category
            excellent = [m for m, s in modelUsefulness.items() if s['category'] == 'EXCELLENT']
            poor = [m for m, s in modelUsefulness.items() if s['category'] in ['POOR', 'VERY POOR']]
            
            if len(excellent) > 1:
                recommendations.append(f"🏆 Consider ensemble of top models: {', '.join(excellent)}")
            
            if poor:
                recommendations.append(f"🚫 AVOID these models: {', '.join(poor)}")
        
        # Include spread-based recommendations
        spreadStats = self.analysisStats.get('spreadStats', {})
        if 'speed' in spreadStats:
            maxSpread = spreadStats['speed'].get('max', 0)
            if maxSpread > 10:
                recommendations.append("⚠️ Large model disagreements detected - use WindConsensus with uncertainty grids")
            elif maxSpread < 3:
                recommendations.append("✅ Good model agreement - higher forecast confidence")
        
        # Add workflow recommendations
        recommendations.append("🎯 START with WindConsensus vector grid as your base forecast")
        recommendations.append("🔍 CHECK WindSpeedSpread to identify low-confidence areas")
        recommendations.append("⚖️ ADJUST forecast based on bias patterns of your preferred models")
        recommendations.append("📊 USE model rankings to prioritize which models to trust most")
        recommendations.append("🌬️ WindConsensus displays as wind barbs - perfect for marine forecasting")
        
        return recommendations
    
    def saveReport(self):
        """Save report to text file"""
        try:
            import tkinter.filedialog as filedialog
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                title="Save Enhanced Analysis Report"
            )
            if filename:
                with open(filename, 'w') as f:
                    f.write(self.reportText.get(1.0, tk.END))
        except Exception as e:
            pass
    
    def closeReport(self):
        """Close the report window"""
        self.root.destroy()

class Procedure (SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.debugMode = True
    
    def debugMsg(self, msg):
        """Enhanced debug messaging"""
        if self.debugMode:
            self.statusBarMsg("DEBUG: " + str(msg), "S")
    
    def getEffectiveEditArea(self, editArea):
        """Handle cases where no edit area is active"""
        # Method 1: Try the provided edit area
        if editArea is not None and editArea != "":
            try:
                mask = self.encodeEditArea(editArea)
                if sum(mask.flat) > 0:
                    self.statusBarMsg(f"Using edit area '{editArea}': {sum(mask.flat)} points", "S")
                    return mask, f"Edit Area: {editArea}"
            except:
                pass
        
        # Method 2: Use entire domain
        self.statusBarMsg("No valid edit area - using entire grid domain", "S")
        try:
            fcst = self.mutableID().modelIdentifier()
            try:
                refGrid = self.getGrids(fcst, "Wind", "SFC", self.GM_timeRange(), mode="First", noDataError=0)
                if refGrid is not None:
                    mag, dir = refGrid
                    wholeMask = ones(mag.shape, dtype=bool)
                    self.statusBarMsg(f"Created whole domain mask: {sum(wholeMask.flat)} points", "S")
                    return wholeMask, "Entire Grid Domain"
            except:
                pass
            
            refGrid = self.newGrid(0.0)
            wholeMask = ones(refGrid.shape, dtype=bool)
            self.statusBarMsg(f"Created whole domain mask: {sum(wholeMask.flat)} points", "S")
            return wholeMask, "Entire Grid Domain"
            
        except Exception as e:
            self.statusBarMsg(f"CRITICAL: Cannot create domain mask: {str(e)}", "A")
            return None, "Failed"
    
    def collectGridStatistics(self, grid, mask, gridName):
        """Collect comprehensive statistics for a grid"""
        if grid is None or mask is None:
            return {}
        
        maskedGrid = where(mask, grid, nan)
        validData = maskedGrid[~isnan(maskedGrid)]
        
        if len(validData) == 0:
            return {'count': 0}
        
        totalPoints = sum(mask.flat)
        nonZeroPoints = sum((grid > 0).flat)
        coverage = (nonZeroPoints / totalPoints * 100) if totalPoints > 0 else 0
        
        return {
            'min': float(min(validData)),
            'max': float(max(validData)),
            'mean': float(mean(validData)),
            'count': len(validData),
            'coverage': coverage,
            'gridName': gridName
        }
    
    def createConsensusGrids(self, currentSpeedGrids, currentDirGrids, modelNames, timeRange, windThreshold):
        """Create consensus WIND VECTOR grid with barbs (mag + dir combined)"""
        if len(currentSpeedGrids) < 2:
            self.statusBarMsg("Need 2+ models for consensus - skipping consensus grids", "A")
            return None, None
        
        self.statusBarMsg(f"Creating WindConsensus VECTOR grid from {len(currentSpeedGrids)} models: {', '.join(modelNames)}", "S")
        
        # Calculate multi-model means
        speedArray = array(currentSpeedGrids)
        dirArray = array(currentDirGrids)
        
        # Speed consensus (simple mean)
        consensusSpeed = mean(speedArray, axis=0)
        
        # Direction consensus (circular mean - proper for wind directions)
        dirRad = dirArray * pi / 180.0
        meanCosDir = mean(cos(dirRad), axis=0)
        meanSinDir = mean(sin(dirRad), axis=0)
        consensusDir = arctan2(meanSinDir, meanCosDir) * 180.0 / pi
        consensusDir = where(consensusDir < 0, consensusDir + 360, consensusDir)
        
        # Get effective edit area mask
        editAreaMask, maskDescription = self.getEffectiveEditArea(self.editArea)
        if editAreaMask is None:
            return None, None
        
        # Apply wind threshold and edit area mask
        significantWindMask = (consensusSpeed >= windThreshold) & editAreaMask
        
        # Create masked consensus grids (0 where not significant)
        consensusSpeedMasked = where(significantWindMask, consensusSpeed, 0.0)
        consensusDirMasked = where(significantWindMask, consensusDir, 0.0)
        
        # Clip to reasonable ranges
        consensusSpeedMasked = clip(consensusSpeedMasked, 0.0, 100.0)
        consensusDirMasked = clip(consensusDirMasked, 0.0, 360.0)
        
        # Collect statistics for both components
        speedStats = self.collectGridStatistics(consensusSpeedMasked, significantWindMask, "WindConsensus_Speed")
        dirStats = self.collectGridStatistics(consensusDirMasked, significantWindMask, "WindConsensus_Direction")
        
        # Store consensus stats
        self.analysisStats['consensusStats'] = {
            'speed': speedStats,
            'direction': dirStats,
            'modelCount': len(modelNames),
            'modelsUsed': modelNames
        }
        
        # Create the WIND VECTOR grid (this will show as wind barbs!)
        try:
            # Create tuple for wind vector (magnitude, direction)
            consensusWindVector = (consensusSpeedMasked, consensusDirMasked)
            
            # Create VECTOR grid (not SCALAR) - this displays as wind barbs
            self.createGrid("Fcst", "WindConsensus", "VECTOR", consensusWindVector, timeRange,
                           minAllowedValue=0.0, maxAllowedValue=125.0)
            
            self.setActiveElement("Fcst", "WindConsensus", "SFC", timeRange,
                                            "SITE/ONA/GFE/Beaufort_Winds", 
                                            (0.0, 125.0), 0)
            
            self.statusBarMsg(f"✅ Created WindConsensus VECTOR grid with wind barbs from {len(modelNames)} models", "S")
            self.statusBarMsg(f"   Speed range: {speedStats.get('min', 0):.1f} to {speedStats.get('max', 0):.1f} kts", "S")
            self.statusBarMsg(f"   Grid points with consensus: {speedStats.get('count', 0):,}", "S")
            
            return consensusSpeedMasked, consensusDirMasked
            
        except Exception as e:
            self.statusBarMsg(f"Error creating consensus wind vector grid: {str(e)}", "A")
            return None, None
    
    def calculateModelUsefulness(self):
        """Calculate usefulness scores for all models"""
        modelScores = {}
        
        variabilityStats = self.analysisStats.get('variabilityStats', {})
        biasStats = self.analysisStats.get('biasStats', {})
        availableModels = self.analysisStats.get('modelsAnalyzed', [])
        
        for modelId in availableModels:
            score = 100
            reasons = []
            
            # Consistency Score (40%)
            if modelId in variabilityStats and 'speed' in variabilityStats[modelId]:
                avgVariability = variabilityStats[modelId]['speed'].get('mean', 0)
                
                if avgVariability < 1.0:
                    consistencyScore = 40
                    reasons.append("very consistent")
                elif avgVariability < 2.0:
                    consistencyScore = 32
                    reasons.append("good consistency")
                elif avgVariability < 3.0:
                    consistencyScore = 24
                    reasons.append("moderate consistency")
                elif avgVariability < 4.0:
                    consistencyScore = 16
                    reasons.append("variable")
                else:
                    consistencyScore = 8
                    reasons.append("highly variable")
            else:
                consistencyScore = 0
                reasons.append("no consistency data")
            
            # Bias Score (30%) - relative to WindConsensus
            if modelId in biasStats and 'speed' in biasStats[modelId]:
                avgBias = abs(biasStats[modelId]['speed'].get('mean', 0))
                
                if avgBias < 0.5:
                    biasScore = 30
                    reasons.append("well-calibrated vs consensus")
                elif avgBias < 1.0:
                    biasScore = 25
                    reasons.append("slight bias vs consensus")
                elif avgBias < 2.0:
                    biasScore = 20
                    reasons.append("moderate bias vs consensus")
                elif avgBias < 3.0:
                    biasScore = 15
                    reasons.append("significant bias vs consensus")
                else:
                    biasScore = 5
                    reasons.append("large bias vs consensus")
            else:
                biasScore = 0
                reasons.append("no bias data")
            
            # Availability Score (20%)
            availabilityScore = 20
            
            # Data Quality Score (10%)
            if modelId in variabilityStats and 'speed' in variabilityStats[modelId]:
                coverage = variabilityStats[modelId]['speed'].get('coverage', 0)
                if coverage > 80:
                    qualityScore = 10
                elif coverage > 60:
                    qualityScore = 8
                elif coverage > 40:
                    qualityScore = 6
                elif coverage > 20:
                    qualityScore = 4
                else:
                    qualityScore = 2
            else:
                qualityScore = 5
            
            # Calculate total score
            totalScore = consistencyScore + biasScore + availabilityScore + qualityScore
            
            # Determine category
            if totalScore >= 85:
                category = "EXCELLENT"
                recommendation = "Highly recommended for primary forecast"
            elif totalScore >= 70:
                category = "GOOD"
                recommendation = "Good choice for forecast blend"
            elif totalScore >= 55:
                category = "FAIR"
                recommendation = "Use with caution, check for local conditions"
            elif totalScore >= 40:
                category = "POOR"
                recommendation = "Consider excluding from forecast"
            else:
                category = "VERY POOR"
                recommendation = "Avoid using for forecast"
            
            modelScores[modelId] = {
                'totalScore': totalScore,
                'consistencyScore': consistencyScore,
                'biasScore': biasScore,
                'availabilityScore': availabilityScore,
                'qualityScore': qualityScore,
                'category': category,
                'recommendation': recommendation,
                'reasons': reasons
            }
        
        self.analysisStats['modelUsefulness'] = modelScores
        return modelScores
    
    def getModelRunsWithFallback(self, modelName, runCount):
        """Get the last N runs of a model, with fallback for missing runs"""
        modelRuns = []
        
        for run in range(runCount):
            runOffset = -run
            try:
                db = self.findDatabase(modelName, runOffset)
                if db is not None:
                    modelRuns.append((runOffset, db.modelIdentifier()))
            except:
                pass
        
        return modelRuns
    
    def getWindDataForRun(self, modelId, timeRange):
        """Get wind speed and direction for a specific model run and time"""
        try:
            wind = self.getGrids(modelId, "Wind", "SFC", timeRange, mode="First", noDataError=0)
            if wind is not None:
                (mag, dir) = wind
                if mag is not None and dir is not None and max(mag.flat) > 0:
                    return mag, dir
        except:
            pass
        return None, None
    
    def getCurrentModelWindData(self, modelId, timeRange):
        """Get current run wind speed and direction"""
        try:
            db = self.findDatabase(modelId, 0)
            if db is not None:
                return self.getWindDataForRun(db.modelIdentifier(), timeRange)
        except:
            pass
        return None, None
    
    def validateModelCoverage(self, selectedModels, timeRange):
        """Check which models have data"""
        validModels = {}
        invalidModels = []
        
        fcst = self.mutableID().modelIdentifier()
        try:
            gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
            if gridinfos:
                testTimeRange = gridinfos[0].gridTime()
                
                for modelId, modelInfo in selectedModels.items():
                    testWind = self.getCurrentModelWindData(modelId, testTimeRange)
                    if testWind is not None and testWind[0] is not None:
                        validModels[modelId] = modelInfo
                    else:
                        invalidModels.append(modelInfo['displayName'])
        except:
            pass
        
        return validModels, invalidModels
    
    def calculateDirectionDifference(self, dir1, dir2):
        """Calculate minimum angular difference between two directions"""
        diff = abs(dir1 - dir2)
        return minimum(diff, 360.0 - diff)
    
    def createModelVariabilityGrids(self, windSpeedGrids, windDirGrids, modelName, timeRange, windThreshold):
        """Create variability grids with statistics collection"""
        if len(windSpeedGrids) < 2:
            return None, None

        # Stack grids and calculate variability
        speedArray = array(windSpeedGrids)
        dirArray = array(windDirGrids)
        
        meanSpeed = mean(speedArray, axis=0)
        editAreaMask, maskDescription = self.getEffectiveEditArea(self.editArea)
        
        if editAreaMask is None:
            return None, None
        
        significantWindMask = (meanSpeed >= windThreshold) & editAreaMask
        
        if sum(significantWindMask.flat) > 0:
            # Calculate MAD for speed and direction
            speedMean = mean(speedArray, axis=0)
            speedMAD = mean(abs(speedArray - speedMean), axis=0)
            speedMAD = clip(speedMAD, 0.0, 20.0)
            
            dirMean = mean(dirArray, axis=0)
            dirDiffs = array([self.calculateDirectionDifference(dirArray[i], dirMean) 
                             for i in range(len(dirArray))])
            dirMAD = mean(dirDiffs, axis=0)
            dirMAD = clip(dirMAD, 0.0, 180.0)
            
            speedVariability = where(significantWindMask, speedMAD, 0.0)
            dirVariability = where(significantWindMask, dirMAD, 0.0)
            
            # Collect statistics
            speedStats = self.collectGridStatistics(speedVariability, significantWindMask, f"WindSpeedVariability{modelName}")
            dirStats = self.collectGridStatistics(dirVariability, significantWindMask, f"WindDirVariability{modelName}")
            
            if 'variabilityStats' not in self.analysisStats:
                self.analysisStats['variabilityStats'] = {}
            
            self.analysisStats['variabilityStats'][modelName] = {
                'speed': speedStats,
                'direction': dirStats
            }
            
            # Create grids
            try:
                self.createGrid("Fcst", f"WindSpeedVariability{modelName}", "SCALAR", speedVariability, timeRange,
                               minAllowedValue=0.0, maxAllowedValue=20.0)
                self.createGrid("Fcst", f"WindDirVariability{modelName}", "SCALAR", dirVariability, timeRange,
                               minAllowedValue=0.0, maxAllowedValue=180.0)
                return speedVariability, dirVariability
            except:
                return None, None
        
        return None, None
    
    def createModelBiasGrids(self, currentSpeedGrids, currentDirGrids, modelNames, timeRange, windThreshold, consensusSpeed):
        """Create bias grids relative to WindConsensus vector"""
        if len(currentSpeedGrids) < 2 or consensusSpeed is None:
            return {}

        self.statusBarMsg("Creating bias grids relative to WindConsensus vector...", "S")

        # Get effective edit area mask
        editAreaMask, maskDescription = self.getEffectiveEditArea(self.editArea)
        if editAreaMask is None:
            return {}
        
        # Use consensus speed for masking (instead of mean speed)
        significantWindMask = (consensusSpeed >= windThreshold) & editAreaMask

        biasGrids = {}

        if sum(significantWindMask.flat) > 0:
            for i, modelName in enumerate(modelNames):
                # Speed bias relative to consensus
                speedBias = currentSpeedGrids[i] - consensusSpeed
                speedBias = where(significantWindMask, speedBias, 0.0)
                speedBias = clip(speedBias, -20.0, 20.0)

                # Create speed bias grid
                speedBiasGridName = f"WindSpeedBias{modelName}"

                try:
                    self.createGrid("Fcst", speedBiasGridName, "SCALAR", speedBias, timeRange,
                                   minAllowedValue=-20.0, maxAllowedValue=20.0)
                    
                    # COLLECT STATISTICS FOR REPORT
                    speedStats = self.collectGridStatistics(speedBias, significantWindMask, speedBiasGridName)
                    
                    # Store in analysis stats
                    if 'biasStats' not in self.analysisStats:
                        self.analysisStats['biasStats'] = {}
                    
                    self.analysisStats['biasStats'][modelName] = {
                        'speed': speedStats
                    }
                    
                    biasGrids[modelName] = {'speed': speedBias}
                    
                    # Report bias statistics
                    avgBias = speedStats.get('mean', 0)
                    maxBias = speedStats.get('max', 0)
                    minBias = speedStats.get('min', 0)
                    
                    if avgBias > 1.0:
                        biasMsg = f"HIGH bias vs consensus (+{avgBias:.1f} kts avg)"
                    elif avgBias < -1.0:
                        biasMsg = f"LOW bias vs consensus ({avgBias:.1f} kts avg)"
                    else:
                        biasMsg = f"neutral bias vs consensus ({avgBias:+.1f} kts avg)"
                    
                    self.statusBarMsg(f"✅ {modelName}: {biasMsg}, range {minBias:+.1f} to {maxBias:+.1f} kts", "S")
                    
                except Exception as e:
                    self.statusBarMsg(f"Error creating bias grid for {modelName}: {str(e)}", "A")

        return biasGrids
    
    def createModelSpreadGrids(self, currentSpeedGrids, currentDirGrids, modelNames, timeRange, windThreshold):
        """Create spread grids with statistics"""
        if len(currentSpeedGrids) < 2:
            return None, None

        speedArray = array(currentSpeedGrids)
        dirArray = array(currentDirGrids)
        
        meanSpeed = mean(speedArray, axis=0)
        editAreaMask, maskDescription = self.getEffectiveEditArea(self.editArea)
        
        if editAreaMask is None:
            return None, None
        
        significantWindMask = (meanSpeed >= windThreshold) & editAreaMask

        if sum(significantWindMask.flat) > 0:
            # Calculate spread
            speedRange = amax(speedArray, axis=0) - amin(speedArray, axis=0)
            speedRange = clip(speedRange, 0.0, 20.0)
            
            # Direction spread (circular)
            dirRad = dirArray * pi / 180.0
            meanCosDir = mean(cos(dirRad), axis=0)
            meanSinDir = mean(sin(dirRad), axis=0)
            R = sqrt(meanCosDir**2 + meanSinDir**2)
            circVar = 1 - R
            dirSpreadCalc = arcsin(minimum(sqrt(2 * circVar), 1.0)) * 180.0 / pi * 2.0
            dirSpreadCalc = clip(dirSpreadCalc, 0.0, 180.0)
            
            speedSpread = where(significantWindMask, speedRange, 0.0)
            dirSpread = where(significantWindMask, dirSpreadCalc, 0.0)
            
            # Collect statistics
            speedStats = self.collectGridStatistics(speedSpread, significantWindMask, "WindSpeedSpread")
            dirStats = self.collectGridStatistics(dirSpread, significantWindMask, "WindDirSpread")
            
            self.analysisStats['spreadStats'] = {
                'speed': speedStats,
                'direction': dirStats
            }
            
            try:
                self.createGrid("Fcst", "WindSpeedSpread", "SCALAR", speedSpread, timeRange,
                               minAllowedValue=0.0, maxAllowedValue=20.0)
                self.createGrid("Fcst", "WindDirSpread", "SCALAR", dirSpread, timeRange,
                               minAllowedValue=0.0, maxAllowedValue=180.0)
                return speedSpread, dirSpread
            except:
                return None, None
        
        return None, None
    
    def createUncertaintyGrids(self, variabilitySpeedGrids, variabilityDirGrids, 
                              spreadSpeedGrid, spreadDirGrid, timeRange):
        """Create combined uncertainty grids"""
        
        speedUncertainty = self.newGrid(0.0)
        dirUncertainty = self.newGrid(0.0)
        
        if variabilitySpeedGrids and len(variabilitySpeedGrids) > 0:
            validSpeedGrids = [g for g in variabilitySpeedGrids if g is not None]
            validDirGrids = [g for g in variabilityDirGrids if g is not None]
            
            if validSpeedGrids:
                avgSpeedVar = mean(array(validSpeedGrids), axis=0)
            else:
                avgSpeedVar = self.newGrid(0.0)
                
            if validDirGrids:
                avgDirVar = mean(array(validDirGrids), axis=0)
            else:
                avgDirVar = self.newGrid(0.0)
        else:
            avgSpeedVar = self.newGrid(0.0)
            avgDirVar = self.newGrid(0.0)
        
        # Combine with spread
        if spreadSpeedGrid is not None:
            validMask = (avgSpeedVar > 0.0) & (spreadSpeedGrid > 0.0)
            speedOnlyMask = (avgSpeedVar > 0.0) & (spreadSpeedGrid == 0.0)
            spreadOnlyMask = (avgSpeedVar == 0.0) & (spreadSpeedGrid > 0.0)
            
            speedUncertainty = where(validMask, (avgSpeedVar + spreadSpeedGrid) / 2.0, speedUncertainty)
            speedUncertainty = where(speedOnlyMask, avgSpeedVar, speedUncertainty)
            speedUncertainty = where(spreadOnlyMask, spreadSpeedGrid, speedUncertainty)
        else:
            speedUncertainty = avgSpeedVar
        
        if spreadDirGrid is not None:
            validMask = (avgDirVar > 0.0) & (spreadDirGrid > 0.0)
            dirOnlyMask = (avgDirVar > 0.0) & (spreadDirGrid == 0.0)
            spreadOnlyMask = (avgDirVar == 0.0) & (spreadDirGrid > 0.0)
            
            dirUncertainty = where(validMask, (avgDirVar + spreadDirGrid) / 2.0, dirUncertainty)
            dirUncertainty = where(dirOnlyMask, avgDirVar, dirUncertainty)
            dirUncertainty = where(spreadOnlyMask, spreadDirGrid, dirUncertainty)
            dirUncertainty = clip(dirUncertainty, 0.0, 180.0)
        else:
            dirUncertainty = avgDirVar
        
        # Create grids
        try:
            speedUncertainty = clip(speedUncertainty, 0.0, 20.0)
            self.createGrid("Fcst", "WindSpeedUncertainty", "SCALAR", speedUncertainty, timeRange,
                           minAllowedValue=0.0, maxAllowedValue=20.0)
            self.createGrid("Fcst", "WindDirUncertainty", "SCALAR", dirUncertainty, timeRange,
                           minAllowedValue=0.0, maxAllowedValue=180.0)
        except:
            pass
        
        return speedUncertainty, dirUncertainty

    def showGUI(self, editArea, timeRange):
        """Show the enhanced GUI"""
        self.editArea = editArea
        self.timeRange = timeRange
        self.varDict = None
        
        root = tk.Tk()
        gui = ModelDifferenceGUI(root, self.guiCallback)
        root.mainloop()
        
        return self.varDict
    
    def guiCallback(self, values):
        """Callback from GUI"""
        self.varDict = values

    def execute(self, editArea, timeRange, varDict=None):
        """ULTIMATE execution with wind vector consensus and all enhancements"""
        
        self.editArea = editArea
        
        # Test edit area setup
        self.statusBarMsg("=== TESTING EDIT AREA SETUP ===", "S")
        mask, description = self.getEffectiveEditArea(editArea)
        
        if mask is None:
            self.statusBarMsg("CRITICAL ERROR: Cannot create edit area mask!", "A")
            return
        
        maskPoints = sum(mask.flat)
        self.statusBarMsg(f"SUCCESS: Using {description} with {maskPoints} points", "S")
        
        # Show GUI if needed
        if varDict is None:
            varDict = self.showGUI(editArea, timeRange)
            if varDict is None:
                return
        
        # Initialize comprehensive stats
        self.analysisStats = {
            'modelsAnalyzed': [],
            'unavailableModels': [],
            'timePeriodsProcessed': 0,
            'variabilityStats': {},
            'spreadStats': {},
            'biasStats': {},
            'consensusStats': {},
            'modelUsefulness': {},
            'editAreaUsed': description,
            'gridPointsAnalyzed': maskPoints
        }
        
        # Get parameters
        selectedModels = varDict["Selected Models"]
        createConsensus = varDict["Create Consensus"]
        runVariability = varDict["Run Variability"]
        runSpread = varDict["Run Spread"]
        runBias = varDict["Run Bias"]
        createUncertainty = varDict["Create Uncertainty"]
        calculateUsefulness = varDict["Calculate Usefulness"]
        windThreshold = varDict["Wind Threshold"]
        
        self.statusBarMsg("Starting ULTIMATE Wind Vector Model Analysis", "S")
        
        if len(selectedModels) == 0:
            self.statusBarMsg("ERROR: No models selected", "A")
            return
        
        # Validate models
        validModels, invalidModels = self.validateModelCoverage(selectedModels, timeRange)
        
        if len(validModels) == 0:
            self.statusBarMsg("ERROR: No models have data", "A")
            return
        
        self.analysisStats['unavailableModels'] = invalidModels
        selectedModels = validModels
        self.analysisStats['modelsAnalyzed'] = list(selectedModels.keys())
        
        # Get forecast info
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)
        self.analysisStats['timePeriodsProcessed'] = len(gridinfos)
        
        # Process each time period
        for i, gridinfo in enumerate(gridinfos):
            GridTimeRange = gridinfo.gridTime()
            self.statusBarMsg(f"Processing time {i+1}/{len(gridinfos)}", "S")
            
            variabilitySpeedGrids = []
            variabilityDirGrids = []
            currentSpeedGrids = []
            currentDirGrids = []
            modelNames = []
            
            # 1. VARIABILITY ANALYSIS
            if runVariability == "Yes":
                for modelId, modelInfo in selectedModels.items():
                    runCount = modelInfo['runCount']
                    modelRuns = self.getModelRunsWithFallback(modelId, runCount)
                    
                    if len(modelRuns) >= 2:
                        speedGrids = []
                        dirGrids = []
                        for runOffset, modelIdentifier in modelRuns:
                            speed, direction = self.getWindDataForRun(modelIdentifier, GridTimeRange)
                            if speed is not None and direction is not None:
                                speedGrids.append(speed)
                                dirGrids.append(direction)
                        
                        if len(speedGrids) >= 2:
                            speedVar, dirVar = self.createModelVariabilityGrids(speedGrids, dirGrids, modelId, GridTimeRange, windThreshold)
                            if speedVar is not None:
                                variabilitySpeedGrids.append(speedVar)
                                variabilityDirGrids.append(dirVar)
            
            # 2. GET CURRENT MODEL DATA
            if runSpread == "Yes" or runBias == "Yes" or createConsensus == "Yes":
                for modelId in selectedModels.keys():
                    currentSpeed, currentDir = self.getCurrentModelWindData(modelId, GridTimeRange)
                    if currentSpeed is not None and currentDir is not None:
                        currentSpeedGrids.append(currentSpeed)
                        currentDirGrids.append(currentDir)
                        modelNames.append(modelId)
            
            # 3. CREATE WIND VECTOR CONSENSUS GRID FIRST
            consensusSpeed = None
            consensusDir = None
            if createConsensus == "Yes" and len(currentSpeedGrids) >= 2:
                self.statusBarMsg("Creating WindConsensus vector grid with wind barbs...", "S")
                consensusSpeed, consensusDir = self.createConsensusGrids(currentSpeedGrids, currentDirGrids, modelNames, GridTimeRange, windThreshold)
                
                if consensusSpeed is not None:
                    self.statusBarMsg("✅ WindConsensus VECTOR grid created - displays with wind barbs!", "S")
            
            # 4. SPREAD ANALYSIS
            if runSpread == "Yes" and len(currentSpeedGrids) >= 2:
                self.statusBarMsg("Creating spread grids...", "S")
                spreadSpeedGrid, spreadDirGrid = self.createModelSpreadGrids(currentSpeedGrids, currentDirGrids, modelNames, GridTimeRange, windThreshold)
            else:
                spreadSpeedGrid = spreadDirGrid = None
            
            # 5. BIAS ANALYSIS (relative to WindConsensus vector)
            if runBias == "Yes" and consensusSpeed is not None:
                self.statusBarMsg("Creating bias grids relative to WindConsensus vector...", "S")
                biasGrids = self.createModelBiasGrids(currentSpeedGrids, currentDirGrids, modelNames, GridTimeRange, windThreshold, consensusSpeed)
            
            # 6. UNCERTAINTY GRIDS
            if createUncertainty == "Yes":
                self.statusBarMsg("Creating uncertainty grids...", "S")
                self.createUncertaintyGrids(variabilitySpeedGrids, variabilityDirGrids, 
                                          spreadSpeedGrid, spreadDirGrid, GridTimeRange)
        
        # 7. CALCULATE MODEL USEFULNESS RANKINGS
        if calculateUsefulness == "Yes":
            self.statusBarMsg("Calculating model usefulness rankings...", "S")
            self.calculateModelUsefulness()
        
        self.statusBarMsg("Analysis complete - generating comprehensive wind vector report...", "S")
        
        # Show enhanced report
        try:
            EnhancedReportWindow(self.analysisStats, windThreshold)
        except Exception as e:
            self.statusBarMsg(f"Error showing report: {str(e)}", "A")
        
        self.statusBarMsg("🌬️ ULTIMATE Wind Vector Model Analysis completed successfully!", "S")
        self.statusBarMsg("🎯 Load 'WindConsensus' grid to see wind barbs - your starting forecast!", "S")
        return None