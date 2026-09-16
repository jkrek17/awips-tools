"""
Multi-storm analysis tools for concurrent storm systems.

Provides integrated analysis for scenarios with multiple active storms
in the North Atlantic and North Pacific domains:
- Storm interaction detection
- Domain-wide multi-storm statistics
- Storm tracks and trajectories
- Basin-level aggregations
- Comparative analysis between basins
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta

import numpy as np
from scipy import ndimage
from scipy.spatial.distance import cdist

from .domains import OceanDomain, NORTH_ATLANTIC, NORTH_PACIFIC
from .storm_identification import (
    StormFeature,
    StormIdentifier,
    StormIdentificationConfig,
)
from .grid_analysis import GridAnalyzer, compute_gradient_fields
from .ensemble_statistics import (
    EnsembleAnalyzer,
    StormEnsembleStats,
    GridEnsembleStats,
)


@dataclass
class StormTrack:
    """
    Time series of storm positions and intensities.
    
    Attributes:
        storm_id: Unique identifier for the track.
        positions: List of (time, lat, lon) tuples.
        intensities: List of (time, value) tuples.
        genesis_location: (lat, lon) of storm genesis.
        current_state: Most recent StormFeature.
        forecast_positions: List of (time, lat, lon, uncertainty_km).
        classification: Track classification (tropical, extratropical, etc.).
    """
    storm_id: str
    positions: List[Tuple[datetime, float, float]] = field(default_factory=list)
    intensities: List[Tuple[datetime, float]] = field(default_factory=list)
    genesis_location: Optional[Tuple[float, float]] = None
    current_state: Optional[StormFeature] = None
    forecast_positions: List[Tuple[datetime, float, float, float]] = field(default_factory=list)
    classification: str = "unknown"
    
    def add_position(self, time: datetime, lat: float, lon: float):
        """Add a position to the track."""
        self.positions.append((time, lat, lon))
        if self.genesis_location is None:
            self.genesis_location = (lat, lon)
    
    def add_intensity(self, time: datetime, value: float):
        """Add intensity observation to the track."""
        self.intensities.append((time, value))
    
    @property
    def track_length_km(self) -> float:
        """Calculate total track length in km."""
        if len(self.positions) < 2:
            return 0.0
        
        total = 0.0
        for i in range(1, len(self.positions)):
            _, lat1, lon1 = self.positions[i-1]
            _, lat2, lon2 = self.positions[i]
            
            # Simple distance calculation
            dlat = (lat2 - lat1) * 111.0
            dlon = (lon2 - lon1) * 111.0 * np.cos(np.radians((lat1 + lat2) / 2))
            total += np.sqrt(dlat**2 + dlon**2)
        
        return total
    
    @property
    def average_speed_kmh(self) -> float:
        """Calculate average storm translation speed."""
        if len(self.positions) < 2:
            return 0.0
        
        total_km = self.track_length_km
        duration = (self.positions[-1][0] - self.positions[0][0]).total_seconds() / 3600
        
        if duration <= 0:
            return 0.0
        return total_km / duration
    
    @property
    def current_heading(self) -> Optional[float]:
        """Calculate current storm heading (degrees, meteorological)."""
        if len(self.positions) < 2:
            return None
        
        _, lat1, lon1 = self.positions[-2]
        _, lat2, lon2 = self.positions[-1]
        
        dlat = lat2 - lat1
        dlon = (lon2 - lon1) * np.cos(np.radians((lat1 + lat2) / 2))
        
        # Convert to meteorological heading (from direction)
        heading = 90 - np.degrees(np.arctan2(dlat, dlon))
        if heading < 0:
            heading += 360
        return heading


@dataclass
class StormInteraction:
    """
    Description of interaction between two storms.
    
    Attributes:
        storm1_id: First storm identifier.
        storm2_id: Second storm identifier.
        separation_km: Current distance between centers.
        closing_rate_kmh: Rate of approach (negative = separating).
        interaction_type: Type of interaction detected.
        interaction_strength: Quantitative strength measure (0-1).
        fujiwhara_potential: Likelihood of Fujiwhara interaction.
    """
    storm1_id: str
    storm2_id: str
    separation_km: float
    closing_rate_kmh: float = 0.0
    interaction_type: str = "none"
    interaction_strength: float = 0.0
    fujiwhara_potential: float = 0.0


@dataclass
class MultiStormSummary:
    """
    Summary statistics for multiple storms in a domain.
    
    Attributes:
        domain_name: Name of the domain analyzed.
        n_storms: Number of active storms.
        storms: List of StormFeature objects.
        total_affected_area_km2: Total area under storm influence.
        max_wind_kt: Maximum wind speed across all storms.
        min_pressure_hpa: Minimum pressure across all storms.
        mean_intensity: Mean intensity metric.
        storm_density: Storms per million km².
        interactions: List of detected storm interactions.
        aggregate_risk_index: Combined risk metric (0-10).
    """
    domain_name: str
    n_storms: int
    storms: List[StormFeature]
    total_affected_area_km2: float = 0.0
    max_wind_kt: Optional[float] = None
    min_pressure_hpa: Optional[float] = None
    mean_intensity: float = 0.0
    storm_density: float = 0.0
    interactions: List[StormInteraction] = field(default_factory=list)
    aggregate_risk_index: float = 0.0


class MultiStormAnalyzer:
    """
    Analyzer for multiple concurrent storm systems.
    
    Provides integrated analysis of storm systems across ocean basins,
    including interaction detection, track forecasting, and basin-level
    statistics.
    """
    
    def __init__(
        self,
        domain: OceanDomain,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray,
        storm_config: Optional[StormIdentificationConfig] = None
    ):
        """
        Initialize multi-storm analyzer.
        
        Args:
            domain: OceanDomain for analysis.
            lat_grid: 2D latitude array.
            lon_grid: 2D longitude array.
            storm_config: Optional storm identification configuration.
        """
        self.domain = domain
        self.lat_grid = lat_grid
        self.lon_grid = lon_grid
        
        self.storm_identifier = StormIdentifier(
            domain, lat_grid, lon_grid, storm_config
        )
        self.grid_analyzer = GridAnalyzer(domain, lat_grid, lon_grid)
        
        # Active storm tracks
        self.tracks: Dict[str, StormTrack] = {}
        
        # Analysis history
        self.analysis_times: List[datetime] = []
        self.storm_counts: List[int] = []
    
    def analyze_current_state(
        self,
        pressure: Optional[np.ndarray] = None,
        wind_speed: Optional[np.ndarray] = None,
        wind_dir: Optional[np.ndarray] = None,
        time: Optional[datetime] = None
    ) -> MultiStormSummary:
        """
        Analyze current multi-storm state in the domain.
        
        Args:
            pressure: 2D MSLP field (hPa).
            wind_speed: 2D wind speed field (kt).
            wind_dir: 2D wind direction field (degrees).
            time: Analysis time (default: now).
            
        Returns:
            MultiStormSummary with current state.
        """
        if time is None:
            time = datetime.utcnow()
        
        # Identify storms
        storms = []
        if pressure is not None:
            storms = self.storm_identifier.identify_from_pressure(
                pressure, wind_speed
            )
        elif wind_speed is not None:
            storms = self.storm_identifier.identify_from_wind(
                wind_speed, wind_dir, pressure
            )
        
        # Update tracks
        self._update_tracks(storms, time)
        
        # Compute summary statistics
        summary = self._compute_summary(storms)
        
        # Detect interactions
        summary.interactions = self._detect_interactions(storms)
        
        # Record history
        self.analysis_times.append(time)
        self.storm_counts.append(len(storms))
        
        return summary
    
    def analyze_ensemble(
        self,
        ensemble_pressure: Optional[List[np.ndarray]] = None,
        ensemble_wind: Optional[List[np.ndarray]] = None
    ) -> Tuple[MultiStormSummary, Dict[str, StormEnsembleStats]]:
        """
        Analyze multi-storm state across ensemble members.
        
        Args:
            ensemble_pressure: List of pressure fields per member.
            ensemble_wind: List of wind speed fields per member.
            
        Returns:
            Tuple of (summary from ensemble mean, per-storm ensemble stats).
        """
        # Identify storms in each member
        ensemble_storms = []
        
        if ensemble_pressure is not None:
            for pressure in ensemble_pressure:
                storms = self.storm_identifier.identify_from_pressure(pressure)
                ensemble_storms.append(storms)
        elif ensemble_wind is not None:
            for wind in ensemble_wind:
                storms = self.storm_identifier.identify_from_wind(wind)
                ensemble_storms.append(storms)
        else:
            raise ValueError("Must provide pressure or wind ensemble")
        
        # Get reference storms from mean/control (first member)
        reference_storms = ensemble_storms[0] if ensemble_storms else []
        
        # Compute ensemble mean summary
        # Use mean of pressure/wind for overall summary
        if ensemble_pressure is not None:
            mean_pressure = np.mean(np.stack(ensemble_pressure), axis=0)
            mean_storms = self.storm_identifier.identify_from_pressure(mean_pressure)
        else:
            mean_wind = np.mean(np.stack(ensemble_wind), axis=0)
            mean_storms = self.storm_identifier.identify_from_wind(mean_wind)
        
        summary = self._compute_summary(mean_storms)
        
        # Compute per-storm ensemble statistics
        ensemble_analyzer = EnsembleAnalyzer(
            self.domain, self.lat_grid, self.lon_grid
        )
        
        storm_stats = {}
        for ref_storm in reference_storms:
            stats = ensemble_analyzer.compute_storm_relative_spread(
                ensemble_storms, ref_storm
            )
            if stats is not None:
                storm_stats[ref_storm.storm_id] = stats
        
        return summary, storm_stats
    
    def _update_tracks(self, storms: List[StormFeature], time: datetime):
        """Update storm tracks with new observations."""
        matched_ids = set()
        
        for storm in storms:
            # Try to match with existing track
            best_track_id = None
            best_distance = float('inf')
            
            for track_id, track in self.tracks.items():
                if track.current_state is None:
                    continue
                
                dist = self.domain.haversine_distance(
                    storm.center_lat, storm.center_lon,
                    track.current_state.center_lat,
                    track.current_state.center_lon
                )
                
                # Match if within reasonable distance (accounting for translation)
                max_dist = 500  # km
                if dist < max_dist and dist < best_distance:
                    best_distance = dist
                    best_track_id = track_id
            
            if best_track_id is not None:
                # Update existing track
                track = self.tracks[best_track_id]
                track.add_position(time, storm.center_lat, storm.center_lon)
                if storm.max_wind is not None:
                    track.add_intensity(time, storm.max_wind)
                elif storm.min_pressure is not None:
                    track.add_intensity(time, storm.min_pressure)
                track.current_state = storm
                matched_ids.add(best_track_id)
            else:
                # Create new track
                new_track = StormTrack(storm_id=storm.storm_id)
                new_track.add_position(time, storm.center_lat, storm.center_lon)
                if storm.max_wind is not None:
                    new_track.add_intensity(time, storm.max_wind)
                elif storm.min_pressure is not None:
                    new_track.add_intensity(time, storm.min_pressure)
                new_track.current_state = storm
                self.tracks[storm.storm_id] = new_track
                matched_ids.add(storm.storm_id)
    
    def _compute_summary(self, storms: List[StormFeature]) -> MultiStormSummary:
        """Compute multi-storm summary statistics."""
        n_storms = len(storms)
        
        if n_storms == 0:
            return MultiStormSummary(
                domain_name=self.domain.name,
                n_storms=0,
                storms=[],
                total_affected_area_km2=0.0
            )
        
        # Aggregate statistics
        total_area = sum(s.area_km2 for s in storms)
        
        winds = [s.max_wind for s in storms if s.max_wind is not None]
        pressures = [s.min_pressure for s in storms if s.min_pressure is not None]
        
        max_wind = max(winds) if winds else None
        min_pressure = min(pressures) if pressures else None
        
        # Mean intensity (use wind if available, else pressure)
        if winds:
            mean_intensity = np.mean(winds)
        elif pressures:
            mean_intensity = np.mean(pressures)
        else:
            mean_intensity = 0.0
        
        # Storm density
        domain_area = self.domain.area_km2()
        storm_density = (n_storms / domain_area) * 1e6  # per million km²
        
        # Risk index (0-10 scale)
        risk = self._compute_risk_index(storms)
        
        return MultiStormSummary(
            domain_name=self.domain.name,
            n_storms=n_storms,
            storms=storms,
            total_affected_area_km2=total_area,
            max_wind_kt=max_wind,
            min_pressure_hpa=min_pressure,
            mean_intensity=mean_intensity,
            storm_density=storm_density,
            aggregate_risk_index=risk
        )
    
    def _compute_risk_index(self, storms: List[StormFeature]) -> float:
        """
        Compute aggregate risk index from multi-storm scenario.
        
        Factors:
        - Number of storms
        - Maximum intensity
        - Storm proximity (interaction potential)
        - Total affected area
        """
        if len(storms) == 0:
            return 0.0
        
        # Base risk from number of storms
        n_risk = min(2.0, len(storms) * 0.4)
        
        # Intensity risk
        intensity_risk = 0.0
        for storm in storms:
            if storm.max_wind is not None:
                if storm.max_wind >= 64:  # Hurricane
                    intensity_risk = max(intensity_risk, 3.0)
                elif storm.max_wind >= 48:  # Storm
                    intensity_risk = max(intensity_risk, 2.0)
                elif storm.max_wind >= 34:  # Gale
                    intensity_risk = max(intensity_risk, 1.0)
            elif storm.min_pressure is not None:
                if storm.min_pressure <= 960:
                    intensity_risk = max(intensity_risk, 3.0)
                elif storm.min_pressure <= 980:
                    intensity_risk = max(intensity_risk, 2.0)
                elif storm.min_pressure <= 1000:
                    intensity_risk = max(intensity_risk, 1.0)
        
        # Proximity risk (interaction potential)
        proximity_risk = 0.0
        if len(storms) >= 2:
            min_separation = float('inf')
            for i, s1 in enumerate(storms):
                for s2 in storms[i+1:]:
                    sep = self.domain.haversine_distance(
                        s1.center_lat, s1.center_lon,
                        s2.center_lat, s2.center_lon
                    )
                    min_separation = min(min_separation, sep)
            
            if min_separation < 1000:
                proximity_risk = (1000 - min_separation) / 500 * 2.0
                proximity_risk = min(proximity_risk, 2.0)
        
        # Area risk
        total_area = sum(s.area_km2 for s in storms)
        domain_area = self.domain.area_km2()
        area_fraction = total_area / domain_area
        area_risk = min(3.0, area_fraction * 10)
        
        return min(10.0, n_risk + intensity_risk + proximity_risk + area_risk)
    
    def _detect_interactions(
        self,
        storms: List[StormFeature]
    ) -> List[StormInteraction]:
        """Detect potential storm interactions."""
        interactions = []
        
        if len(storms) < 2:
            return interactions
        
        for i, s1 in enumerate(storms):
            for s2 in storms[i+1:]:
                separation = self.domain.haversine_distance(
                    s1.center_lat, s1.center_lon,
                    s2.center_lat, s2.center_lon
                )
                
                # Skip if too far apart
                if separation > 2000:
                    continue
                
                # Determine interaction type
                interaction_type = "none"
                interaction_strength = 0.0
                fujiwhara_potential = 0.0
                
                if separation < 1400:  # ~15 degrees longitude
                    # Potential for Fujiwhara interaction
                    fujiwhara_potential = max(0.0, (1400 - separation) / 1000)
                    
                    if separation < 500:
                        interaction_type = "strong"
                        interaction_strength = 0.8
                    elif separation < 800:
                        interaction_type = "moderate"
                        interaction_strength = 0.5
                    else:
                        interaction_type = "weak"
                        interaction_strength = 0.2
                
                # Calculate closing rate from tracks
                closing_rate = 0.0
                track1 = self.tracks.get(s1.storm_id)
                track2 = self.tracks.get(s2.storm_id)
                
                if track1 and track2 and len(track1.positions) >= 2 and len(track2.positions) >= 2:
                    # Previous separation
                    _, prev_lat1, prev_lon1 = track1.positions[-2]
                    _, prev_lat2, prev_lon2 = track2.positions[-2]
                    prev_sep = self.domain.haversine_distance(
                        prev_lat1, prev_lon1, prev_lat2, prev_lon2
                    )
                    
                    # Time difference
                    dt_hours = (
                        track1.positions[-1][0] - track1.positions[-2][0]
                    ).total_seconds() / 3600
                    
                    if dt_hours > 0:
                        closing_rate = (prev_sep - separation) / dt_hours
                
                if interaction_type != "none":
                    interactions.append(StormInteraction(
                        storm1_id=s1.storm_id,
                        storm2_id=s2.storm_id,
                        separation_km=separation,
                        closing_rate_kmh=closing_rate,
                        interaction_type=interaction_type,
                        interaction_strength=interaction_strength,
                        fujiwhara_potential=fujiwhara_potential
                    ))
        
        return interactions
    
    def compare_basins(
        self,
        other_analyzer: "MultiStormAnalyzer"
    ) -> Dict[str, Dict[str, float]]:
        """
        Compare storm statistics between two ocean basins.
        
        Args:
            other_analyzer: Analyzer for the other basin.
            
        Returns:
            Dict with comparison statistics.
        """
        self_storms = [t.current_state for t in self.tracks.values() 
                      if t.current_state is not None]
        other_storms = [t.current_state for t in other_analyzer.tracks.values()
                       if t.current_state is not None]
        
        self_summary = self._compute_summary(self_storms)
        other_summary = other_analyzer._compute_summary(other_storms)
        
        return {
            self.domain.name: {
                "n_storms": self_summary.n_storms,
                "max_wind_kt": self_summary.max_wind_kt or 0,
                "min_pressure_hpa": self_summary.min_pressure_hpa or 1013,
                "total_area_km2": self_summary.total_affected_area_km2,
                "risk_index": self_summary.aggregate_risk_index,
            },
            other_analyzer.domain.name: {
                "n_storms": other_summary.n_storms,
                "max_wind_kt": other_summary.max_wind_kt or 0,
                "min_pressure_hpa": other_summary.min_pressure_hpa or 1013,
                "total_area_km2": other_summary.total_affected_area_km2,
                "risk_index": other_summary.aggregate_risk_index,
            }
        }
    
    def get_active_tracks(self) -> List[StormTrack]:
        """Return list of currently active storm tracks."""
        return [t for t in self.tracks.values() if t.current_state is not None]


def analyze_storm_interactions(
    storms: List[StormFeature],
    domain: OceanDomain,
    interaction_threshold_km: float = 1500.0
) -> List[StormInteraction]:
    """
    Convenience function to analyze storm interactions.
    
    Args:
        storms: List of StormFeature objects.
        domain: OceanDomain for distance calculations.
        interaction_threshold_km: Maximum separation for interaction.
        
    Returns:
        List of StormInteraction objects.
    """
    interactions = []
    
    for i, s1 in enumerate(storms):
        for s2 in storms[i+1:]:
            separation = domain.haversine_distance(
                s1.center_lat, s1.center_lon,
                s2.center_lat, s2.center_lon
            )
            
            if separation > interaction_threshold_km:
                continue
            
            # Simple interaction strength based on separation
            strength = max(0.0, (interaction_threshold_km - separation) / interaction_threshold_km)
            
            interaction_type = "none"
            if strength > 0.6:
                interaction_type = "strong"
            elif strength > 0.3:
                interaction_type = "moderate"
            elif strength > 0:
                interaction_type = "weak"
            
            fujiwhara = max(0.0, (1400 - separation) / 1000) if separation < 1400 else 0.0
            
            interactions.append(StormInteraction(
                storm1_id=s1.storm_id,
                storm2_id=s2.storm_id,
                separation_km=separation,
                interaction_type=interaction_type,
                interaction_strength=strength,
                fujiwhara_potential=fujiwhara
            ))
    
    return interactions


__all__ = [
    "StormTrack",
    "StormInteraction",
    "MultiStormSummary",
    "MultiStormAnalyzer",
    "analyze_storm_interactions",
]
