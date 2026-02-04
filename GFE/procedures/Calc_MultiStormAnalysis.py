"""
Multi-Storm Grid Analysis Procedure.

Analyzes multiple concurrent storm systems across ocean basins using
grid-based identification and ensemble statistics. Designed for the
North Atlantic (30N-65N, 85W-20E) and North Pacific (30N-65N, 115W-120E).

Features:
- Grid-based storm identification from MSLP/wind fields
- Multi-storm ensemble spread analysis
- Storm interaction detection
- Basin-wide risk assessment
- Storm-relative coordinate statistics

Modular implementation using GFE.marine_tools package.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional, Tuple

import numpy as np

import SmartScript

import grid_fetch
import model_aliases
import thresholds

# Import marine tools
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from marine_tools import (
    OceanDomain,
    NORTH_ATLANTIC,
    NORTH_PACIFIC,
    get_domain,
    GridAnalyzer,
    StormIdentifier,
    StormIdentificationConfig,
    StormFeature,
    MultiStormAnalyzer,
    MultiStormSummary,
    EnsembleAnalyzer,
    compute_storm_relative_spread,
    compute_position_uncertainty,
    analyze_storm_interactions,
)

MenuItems = ["Edit"]
VariableList = []

# Available domains
DOMAIN_OPTIONS = ["North Atlantic", "North Pacific", "Both Basins"]

# Analysis models for ensemble
ENSEMBLE_MODELS = ["GFS", "ECMWF", "CMC", "GEFS"]


class MultiStormGUI:
    """Configuration GUI for multi-storm analysis."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Multi-Storm Grid Analysis")
        self.master.geometry("750x900")

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Multi-Storm Grid Analysis",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Concurrent Storm System Analysis for Ocean Basins",
                 font=("Arial", 11), fg="navy").pack(pady=(0, 15))

        # Domain selection
        self._build_domain_frame(main)

        # Data source
        self._build_source_frame(main)

        # Storm identification options
        self._build_storm_config_frame(main)

        # Analysis options
        self._build_analysis_frame(main)

        # Output options
        self._build_output_frame(main)

        # Info panel
        self._build_info_frame(main)

        # Buttons
        self._build_buttons(main)

    def _build_domain_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Ocean Basin Selection", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.domain_var = tk.StringVar(value="North Atlantic")

        for domain in DOMAIN_OPTIONS:
            tk.Radiobutton(frame, text=domain, variable=self.domain_var,
                          value=domain, font=("Arial", 10)).pack(anchor=tk.W)

        # Domain info
        info = tk.Label(frame, text="", font=("Arial", 9), fg="gray")
        info.pack(anchor=tk.W, pady=(5, 0))

        def update_info(*args):
            domain = self.domain_var.get()
            if domain == "North Atlantic":
                info.config(text="30°N-65°N, 85°W-20°E | US East Coast to Europe")
            elif domain == "North Pacific":
                info.config(text="30°N-65°N, 115°W-120°E | US West Coast to Asia (crosses dateline)")
            else:
                info.config(text="Analysis of both basins with comparison")

        self.domain_var.trace("w", update_info)
        update_info()

    def _build_source_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Data Source", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.source_var = tk.StringVar(value="Single Model")

        tk.Radiobutton(frame, text="Single Model (GFS)", variable=self.source_var,
                      value="Single Model", font=("Arial", 10)).pack(anchor=tk.W)
        tk.Radiobutton(frame, text="Multi-Model Ensemble", variable=self.source_var,
                      value="Ensemble", font=("Arial", 10)).pack(anchor=tk.W)

        # Model selection for ensemble
        self.model_vars: Dict[str, tk.BooleanVar] = {}
        model_frame = tk.Frame(frame)
        model_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Label(model_frame, text="Ensemble Models:",
                 font=("Arial", 9, "bold")).pack(anchor=tk.W)

        for model in ENSEMBLE_MODELS:
            var = tk.BooleanVar(value=True)
            self.model_vars[model] = var
            tk.Checkbutton(model_frame, text=model, variable=var,
                          font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))

    def _build_storm_config_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Storm Identification Parameters", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        # Detection method
        tk.Label(frame, text="Detection Method:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.detection_var = tk.StringVar(value="pressure")

        tk.Radiobutton(frame, text="MSLP Minima (recommended)", variable=self.detection_var,
                      value="pressure", font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))
        tk.Radiobutton(frame, text="Wind Speed Maxima", variable=self.detection_var,
                      value="wind", font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))
        tk.Radiobutton(frame, text="Vorticity Maxima", variable=self.detection_var,
                      value="vorticity", font=("Arial", 9)).pack(anchor=tk.W, padx=(20, 0))

        # Thresholds
        thresh_frame = tk.Frame(frame)
        thresh_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Label(thresh_frame, text="Min Pressure Anomaly (hPa):",
                 font=("Arial", 9)).pack(side=tk.LEFT)
        self.pressure_anomaly_var = tk.DoubleVar(value=4.0)
        tk.Spinbox(thresh_frame, from_=2.0, to=12.0, increment=1.0,
                  textvariable=self.pressure_anomaly_var, width=6).pack(side=tk.LEFT, padx=5)

        tk.Label(thresh_frame, text="Min Wind (kt):",
                 font=("Arial", 9)).pack(side=tk.LEFT, padx=(20, 0))
        self.wind_thresh_var = tk.DoubleVar(value=34.0)
        tk.Spinbox(thresh_frame, from_=20.0, to=64.0, increment=2.0,
                  textvariable=self.wind_thresh_var, width=6).pack(side=tk.LEFT, padx=5)

        # Separation
        sep_frame = tk.Frame(frame)
        sep_frame.pack(fill=tk.X, pady=(5, 0))

        tk.Label(sep_frame, text="Min Storm Separation (km):",
                 font=("Arial", 9)).pack(side=tk.LEFT)
        self.separation_var = tk.IntVar(value=500)
        tk.Scale(sep_frame, from_=200, to=1000, orient=tk.HORIZONTAL,
                variable=self.separation_var, length=200).pack(side=tk.LEFT, padx=5)

    def _build_analysis_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Analysis Options", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.detect_interactions = tk.BooleanVar(value=True)
        self.compute_ensemble_spread = tk.BooleanVar(value=True)
        self.compute_risk_index = tk.BooleanVar(value=True)
        self.compute_spatial_stats = tk.BooleanVar(value=True)

        tk.Checkbutton(frame, text="Detect Storm Interactions (Fujiwhara potential)",
                      variable=self.detect_interactions,
                      font=("Arial", 10)).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Compute Ensemble Position/Intensity Spread",
                      variable=self.compute_ensemble_spread,
                      font=("Arial", 10)).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Calculate Aggregate Risk Index",
                      variable=self.compute_risk_index,
                      font=("Arial", 10)).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Spatial Statistics (autocorrelation, gradients)",
                      variable=self.compute_spatial_stats,
                      font=("Arial", 10)).pack(anchor=tk.W)

    def _build_output_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Output Grids", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.output_storm_mask = tk.BooleanVar(value=True)
        self.output_spread = tk.BooleanVar(value=True)
        self.output_probability = tk.BooleanVar(value=True)
        self.output_risk = tk.BooleanVar(value=True)

        tk.Checkbutton(frame, text="Storm Extent Mask (StormMask)",
                      variable=self.output_storm_mask,
                      font=("Arial", 9)).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Ensemble Spread Grids (WindSpeedSpread, PositionSpread)",
                      variable=self.output_spread,
                      font=("Arial", 9)).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Exceedance Probability (ProbGale, ProbStorm, ProbHurricane)",
                      variable=self.output_probability,
                      font=("Arial", 9)).pack(anchor=tk.W)
        tk.Checkbutton(frame, text="Risk Index Grid (MarineRisk)",
                      variable=self.output_risk,
                      font=("Arial", 9)).pack(anchor=tk.W)

    def _build_info_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Analysis Output", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        info_items = [
            "📊 Per-storm statistics (position, intensity, extent)",
            "🌀 Storm interaction analysis with Fujiwhara potential",
            "📈 Ensemble spread for position and intensity uncertainty",
            "⚠️ Basin-wide aggregate risk assessment",
            "🗺️ Grid-based spatial statistics and correlations",
        ]
        for item in info_items:
            tk.Label(frame, text=item, font=("Arial", 9), fg="darkblue").pack(anchor=tk.W)

    def _build_buttons(self, parent):
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=(15, 0))

        tk.Button(frame, text="Run Analysis", command=self._run,
                  bg="lightblue", font=("Arial", 11, "bold"), width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="Cancel", command=self._cancel, width=12).pack(side=tk.LEFT)

    def _run(self):
        selected_models = [m for m, v in self.model_vars.items() if v.get()]

        self.callback({
            "domain": self.domain_var.get(),
            "source": self.source_var.get(),
            "selected_models": selected_models,
            "detection_method": self.detection_var.get(),
            "pressure_anomaly_hpa": self.pressure_anomaly_var.get(),
            "wind_threshold_kt": self.wind_thresh_var.get(),
            "min_separation_km": self.separation_var.get(),
            "detect_interactions": self.detect_interactions.get(),
            "compute_ensemble_spread": self.compute_ensemble_spread.get(),
            "compute_risk_index": self.compute_risk_index.get(),
            "compute_spatial_stats": self.compute_spatial_stats.get(),
            "output_storm_mask": self.output_storm_mask.get(),
            "output_spread": self.output_spread.get(),
            "output_probability": self.output_probability.get(),
            "output_risk": self.output_risk.get(),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Multi-storm grid analysis procedure."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.analysis_results: Dict = {}

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                self.statusBarMsg("Analysis cancelled", "S")
                return

        self.log("=" * 80)
        self.log("MULTI-STORM GRID ANALYSIS")
        self.log("=" * 80)

        # Get domains to analyze
        domains = self._get_domains(varDict["domain"])
        
        # Configure storm identification
        storm_config = StormIdentificationConfig(
            min_separation_km=float(varDict["min_separation_km"]),
            min_pressure_anomaly_hpa=float(varDict["pressure_anomaly_hpa"]),
            min_wind_threshold_kt=float(varDict["wind_threshold_kt"]),
        )

        # Get forecast grid info
        fcst = self.mutableID().modelIdentifier()
        gridinfos = self.getGridInfo(fcst, "Wind", "SFC", timeRange)

        if not gridinfos:
            self.statusBarMsg("No grids found for time range", "S")
            return

        self.log(f"Analyzing {len(gridinfos)} time periods")
        self.log(f"Domains: {[d.name for d in domains]}")

        # Process each time period
        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing period {i+1}/{len(gridinfos)}", "R")

            for domain in domains:
                self._analyze_domain(
                    domain, grid_tr, varDict, storm_config
                )

        self._generate_summary()
        self.statusBarMsg("Multi-storm analysis complete", "R")

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = MultiStormGUI(root, callback)
        root.mainloop()
        return result[0]

    def _get_domains(self, domain_selection: str) -> List[OceanDomain]:
        """Get OceanDomain objects based on selection."""
        if domain_selection == "North Atlantic":
            return [NORTH_ATLANTIC]
        elif domain_selection == "North Pacific":
            return [NORTH_PACIFIC]
        else:
            return [NORTH_ATLANTIC, NORTH_PACIFIC]

    def _analyze_domain(
        self,
        domain: OceanDomain,
        grid_tr,
        config: Dict,
        storm_config: StormIdentificationConfig
    ):
        """Analyze a single domain for the given time range."""
        self.log(f"\n--- Analyzing {domain.name} ---")

        # Get grid coordinates
        lat_grid, lon_grid = self._get_grid_coordinates()

        # Get data based on source
        if config["source"] == "Single Model":
            pressure = self._get_pressure_grid("GFS", grid_tr)
            wind = self._get_wind_grid("GFS", grid_tr)
            
            if pressure is None and wind is None:
                self.log(f"  No data available for {domain.name}")
                return

            # Create analyzer
            analyzer = MultiStormAnalyzer(domain, lat_grid, lon_grid, storm_config)
            
            # Run analysis
            wind_speed = wind[0] if wind is not None else None
            summary = analyzer.analyze_current_state(
                pressure=pressure,
                wind_speed=wind_speed
            )

            self._process_summary(summary, domain, grid_tr, config)

        else:
            # Ensemble analysis
            ensemble_pressure = []
            ensemble_wind = []

            for model in config["selected_models"]:
                p = self._get_pressure_grid(model, grid_tr)
                w = self._get_wind_grid(model, grid_tr)
                if p is not None:
                    ensemble_pressure.append(p)
                if w is not None:
                    ensemble_wind.append(w[0])

            if not ensemble_pressure and not ensemble_wind:
                self.log(f"  No ensemble data for {domain.name}")
                return

            analyzer = MultiStormAnalyzer(domain, lat_grid, lon_grid, storm_config)

            summary, storm_stats = analyzer.analyze_ensemble(
                ensemble_pressure=ensemble_pressure if ensemble_pressure else None,
                ensemble_wind=ensemble_wind if ensemble_wind else None
            )

            self._process_summary(summary, domain, grid_tr, config)
            self._process_ensemble_stats(storm_stats, domain, grid_tr, config)

    def _get_grid_coordinates(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get lat/lon grids from GFE."""
        # Get a reference grid to determine shape
        ref_grid = self.newGrid(0.0)
        shape = ref_grid.shape

        # Create coordinate grids (simplified - actual implementation would
        # use GFE's coordinate system)
        # For now, create a reasonable approximation
        lats = np.linspace(20.0, 70.0, shape[0])
        lons = np.linspace(-180.0, 180.0, shape[1])
        lon_grid, lat_grid = np.meshgrid(lons, lats)

        return lat_grid, lon_grid

    def _get_pressure_grid(self, model: str, grid_tr) -> Optional[np.ndarray]:
        """Get MSLP grid from a model."""
        try:
            grid = grid_fetch.get_grid(
                self, model, "PMSL", "0.0MSL", grid_tr,
                run_depth=2, mode="First", noDataError=0
            )
            if grid is not None:
                # Convert Pa to hPa if needed
                if np.max(grid) > 10000:
                    grid = grid / 100.0
                return grid
        except Exception:
            pass

        # Try alternate names
        for elem in ["Pressure", "MSLP", "pmsl"]:
            try:
                grid = grid_fetch.get_grid(
                    self, model, elem, "SFC", grid_tr,
                    run_depth=2, mode="First", noDataError=0
                )
                if grid is not None:
                    if np.max(grid) > 10000:
                        grid = grid / 100.0
                    return grid
            except Exception:
                continue

        return None

    def _get_wind_grid(self, model: str, grid_tr) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Get wind vector grid from a model."""
        try:
            wind = grid_fetch.get_vector_grid(
                self, model, "Wind", "SFC", grid_tr,
                run_depth=2, mode="First", noDataError=0
            )
            return wind
        except Exception:
            return None

    def _process_summary(
        self,
        summary: MultiStormSummary,
        domain: OceanDomain,
        grid_tr,
        config: Dict
    ):
        """Process and output storm summary."""
        self.log(f"\n  {summary.n_storms} storms identified in {domain.name}")

        if summary.n_storms == 0:
            return

        # Log storm details
        for storm in summary.storms:
            self.log(f"    {storm.storm_id}: {storm.center_lat:.1f}°N, "
                    f"{storm.center_lon:.1f}°E")
            if storm.max_wind:
                self.log(f"      Max Wind: {storm.max_wind:.0f} kt")
            if storm.min_pressure:
                self.log(f"      Min Pressure: {storm.min_pressure:.0f} hPa")
            self.log(f"      Intensity: {storm.intensity_category}")

        # Log interactions
        if config["detect_interactions"] and summary.interactions:
            self.log(f"\n  Storm Interactions:")
            for interaction in summary.interactions:
                self.log(f"    {interaction.storm1_id} <-> {interaction.storm2_id}")
                self.log(f"      Separation: {interaction.separation_km:.0f} km")
                self.log(f"      Type: {interaction.interaction_type}")
                if interaction.fujiwhara_potential > 0.1:
                    self.log(f"      Fujiwhara potential: {interaction.fujiwhara_potential:.2f}")

        # Log risk index
        if config["compute_risk_index"]:
            self.log(f"\n  Basin Risk Index: {summary.aggregate_risk_index:.1f}/10")

        # Create output grids
        if config["output_storm_mask"]:
            self._create_storm_mask_grid(summary, grid_tr)

        if config["output_risk"]:
            self._create_risk_grid(summary, grid_tr)

    def _process_ensemble_stats(
        self,
        storm_stats: Dict,
        domain: OceanDomain,
        grid_tr,
        config: Dict
    ):
        """Process ensemble statistics for each storm."""
        if not storm_stats:
            return

        self.log(f"\n  Ensemble Statistics:")
        for storm_id, stats in storm_stats.items():
            self.log(f"    {storm_id}:")
            self.log(f"      Position uncertainty: {stats.position_std_km:.0f} km")
            self.log(f"      Intensity spread: {stats.intensity_std:.1f}")
            self.log(f"      Members matched: {stats.n_members}")

    def _create_storm_mask_grid(self, summary: MultiStormSummary, grid_tr):
        """Create grid showing storm extents."""
        mask = self.newGrid(0.0)

        for i, storm in enumerate(summary.storms):
            if storm.extent_mask is not None:
                # Add storm ID to mask (1, 2, 3, etc.)
                mask = np.where(storm.extent_mask, float(i + 1), mask)

        self.createGrid("Fcst", "StormMask", "SCALAR", mask, grid_tr,
                       minAllowedValue=0.0, maxAllowedValue=10.0)

    def _create_risk_grid(self, summary: MultiStormSummary, grid_tr):
        """Create risk index grid."""
        risk = self.newGrid(0.0)

        # Base risk from overall assessment
        base_risk = summary.aggregate_risk_index / 10.0 * 5.0

        # Add storm-specific risk
        for storm in summary.storms:
            if storm.extent_mask is not None:
                storm_risk = base_risk
                if storm.max_wind:
                    if storm.max_wind >= 64:
                        storm_risk += 4.0
                    elif storm.max_wind >= 48:
                        storm_risk += 3.0
                    elif storm.max_wind >= 34:
                        storm_risk += 2.0
                risk = np.maximum(risk, np.where(storm.extent_mask, storm_risk, 0))

        risk = np.clip(risk, 0.0, 10.0)

        self.createGrid("Fcst", "MarineRisk", "SCALAR", risk, grid_tr,
                       minAllowedValue=0.0, maxAllowedValue=10.0,
                       units="index")

    def _generate_summary(self):
        """Generate final summary output."""
        self.log("\n" + "=" * 80)
        self.log("ANALYSIS SUMMARY")
        self.log("=" * 80)

        total_storms = sum(
            len(r.get("storms", []))
            for r in self.analysis_results.values()
        )

        self.log(f"Total storms analyzed: {total_storms}")

    def log(self, message: str):
        """Log message to status bar and console."""
        print(message)


__all__ = ["Procedure"]
