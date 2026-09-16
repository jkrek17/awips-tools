"""
Ensemble statistics for multi-storm marine analysis.

Provides specialized ensemble analysis methods that account for
multiple concurrent storms:
- Storm-relative ensemble spread (centered on each storm)
- Position uncertainty estimation (cone of uncertainty)
- Intensity spread by storm
- Compound probability calculations
- Spatial correlation of ensemble members
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import ndimage
from scipy.stats import norm, pearsonr

from .domains import OceanDomain
from .storm_identification import StormFeature, StormIdentifier


@dataclass
class StormEnsembleStats:
    """
    Ensemble statistics for an individual storm.
    
    Attributes:
        storm_id: Identifier linking to StormFeature.
        n_members: Number of ensemble members analyzed.
        position_mean: Mean storm center position (lat, lon).
        position_std_km: Standard deviation of position (km).
        position_ellipse: Error ellipse (semi_major_km, semi_minor_km, angle_deg).
        intensity_mean: Mean intensity metric (wind or pressure).
        intensity_std: Standard deviation of intensity.
        intensity_percentiles: Dict of percentile -> value.
        track_spread_km: Spread in storm track direction.
        cross_track_spread_km: Spread perpendicular to track.
        probability_of_exceedance: Dict of threshold -> probability.
    """
    storm_id: str
    n_members: int
    position_mean: Tuple[float, float]
    position_std_km: float
    position_ellipse: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    intensity_mean: float = 0.0
    intensity_std: float = 0.0
    intensity_percentiles: Dict[int, float] = field(default_factory=dict)
    track_spread_km: float = 0.0
    cross_track_spread_km: float = 0.0
    probability_of_exceedance: Dict[float, float] = field(default_factory=dict)


@dataclass
class GridEnsembleStats:
    """
    Grid-based ensemble statistics (at each grid point).
    
    Attributes:
        mean: Ensemble mean field.
        std: Ensemble standard deviation.
        spread: Ensemble spread (max - min).
        percentile_10: 10th percentile field.
        percentile_50: Median field.
        percentile_90: 90th percentile field.
        probability_above: Probability of exceeding threshold.
        agreement_index: Fraction of members agreeing on sign/category.
    """
    mean: np.ndarray
    std: np.ndarray
    spread: np.ndarray
    percentile_10: np.ndarray
    percentile_50: np.ndarray
    percentile_90: np.ndarray
    probability_above: Optional[np.ndarray] = None
    agreement_index: Optional[np.ndarray] = None


class EnsembleAnalyzer:
    """
    Analyzer for ensemble data with multi-storm awareness.
    
    Computes ensemble statistics both globally and storm-relative,
    properly handling multiple concurrent storm systems.
    """
    
    def __init__(
        self,
        domain: OceanDomain,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray
    ):
        """
        Initialize ensemble analyzer.
        
        Args:
            domain: OceanDomain for analysis.
            lat_grid: 2D latitude array.
            lon_grid: 2D longitude array.
        """
        self.domain = domain
        self.lat_grid = lat_grid
        self.lon_grid = lon_grid
        self.domain_mask = domain.create_domain_mask(lat_grid, lon_grid)
        
        # Calculate grid metrics
        if lat_grid.shape[0] > 1:
            self.dlat = np.abs(lat_grid[1, 0] - lat_grid[0, 0])
        else:
            self.dlat = 1.0
        if lon_grid.shape[1] > 1:
            self.dlon = np.abs(lon_grid[0, 1] - lon_grid[0, 0])
        else:
            self.dlon = 1.0
        
        self.dy_km, self.dx_km = domain.degrees_to_km(
            domain.center_lat, self.dlat, self.dlon
        )
    
    def compute_grid_statistics(
        self,
        ensemble_fields: List[np.ndarray],
        threshold: Optional[float] = None,
        category_func: Optional[callable] = None
    ) -> GridEnsembleStats:
        """
        Compute grid-point ensemble statistics.
        
        Args:
            ensemble_fields: List of 2D arrays, one per ensemble member.
            threshold: Optional threshold for probability calculation.
            category_func: Optional function to categorize values for agreement.
            
        Returns:
            GridEnsembleStats instance.
        """
        n_members = len(ensemble_fields)
        if n_members == 0:
            raise ValueError("No ensemble members provided")
        
        # Stack into 3D array (member, lat, lon)
        stack = np.stack(ensemble_fields, axis=0)
        
        # Compute statistics along member axis
        mean = np.mean(stack, axis=0)
        std = np.std(stack, axis=0)
        spread = np.max(stack, axis=0) - np.min(stack, axis=0)
        
        percentile_10 = np.percentile(stack, 10, axis=0)
        percentile_50 = np.percentile(stack, 50, axis=0)
        percentile_90 = np.percentile(stack, 90, axis=0)
        
        # Probability above threshold
        prob_above = None
        if threshold is not None:
            prob_above = np.mean(stack > threshold, axis=0)
        
        # Agreement index
        agreement = None
        if category_func is not None:
            categories = np.apply_along_axis(
                lambda x: [category_func(v) for v in x], 0, stack
            )
            # Find most common category at each point
            def mode_fraction(x):
                unique, counts = np.unique(x, return_counts=True)
                return counts.max() / len(x)
            agreement = np.apply_along_axis(mode_fraction, 0, categories)
        
        return GridEnsembleStats(
            mean=mean, std=std, spread=spread,
            percentile_10=percentile_10,
            percentile_50=percentile_50,
            percentile_90=percentile_90,
            probability_above=prob_above,
            agreement_index=agreement
        )
    
    def compute_storm_relative_spread(
        self,
        ensemble_storms: List[List[StormFeature]],
        reference_storm: StormFeature,
        match_radius_km: float = 500.0
    ) -> Optional[StormEnsembleStats]:
        """
        Compute ensemble spread relative to a storm center.
        
        Matches storms across ensemble members and computes statistics
        in storm-relative coordinates.
        
        Args:
            ensemble_storms: List of storm lists (one per member).
            reference_storm: Storm to analyze (from control or mean).
            match_radius_km: Maximum distance to consider a match.
            
        Returns:
            StormEnsembleStats or None if insufficient matches.
        """
        matched_positions = []
        matched_intensities = []
        
        ref_lat = reference_storm.center_lat
        ref_lon = reference_storm.center_lon
        
        for member_storms in ensemble_storms:
            # Find closest storm in this member
            best_match = None
            best_dist = float('inf')
            
            for storm in member_storms:
                dist = self.domain.haversine_distance(
                    ref_lat, ref_lon,
                    storm.center_lat, storm.center_lon
                )
                if dist < best_dist and dist < match_radius_km:
                    best_dist = dist
                    best_match = storm
            
            if best_match is not None:
                matched_positions.append((best_match.center_lat, best_match.center_lon))
                # Use pressure if available, else wind
                if best_match.min_pressure is not None:
                    matched_intensities.append(best_match.min_pressure)
                elif best_match.max_wind is not None:
                    matched_intensities.append(best_match.max_wind)
        
        n_matches = len(matched_positions)
        if n_matches < 3:
            return None
        
        # Compute position statistics
        lats = np.array([p[0] for p in matched_positions])
        lons = np.array([p[1] for p in matched_positions])
        
        mean_lat = np.mean(lats)
        mean_lon = np.mean(lons)
        
        # Convert to km displacements from mean
        lat_disp_km = (lats - mean_lat) * 111.0
        lon_disp_km = (lons - mean_lon) * 111.0 * np.cos(np.radians(mean_lat))
        
        # Compute position spread
        position_std_km = np.sqrt(np.std(lat_disp_km)**2 + np.std(lon_disp_km)**2)
        
        # Compute error ellipse via PCA
        ellipse = self._compute_error_ellipse(lat_disp_km, lon_disp_km)
        
        # Intensity statistics
        intensities = np.array(matched_intensities)
        intensity_mean = float(np.mean(intensities))
        intensity_std = float(np.std(intensities))
        intensity_percentiles = {
            p: float(np.percentile(intensities, p))
            for p in [10, 25, 50, 75, 90]
        }
        
        return StormEnsembleStats(
            storm_id=reference_storm.storm_id,
            n_members=n_matches,
            position_mean=(mean_lat, mean_lon),
            position_std_km=position_std_km,
            position_ellipse=ellipse,
            intensity_mean=intensity_mean,
            intensity_std=intensity_std,
            intensity_percentiles=intensity_percentiles
        )
    
    def _compute_error_ellipse(
        self,
        x_displacements: np.ndarray,
        y_displacements: np.ndarray,
        confidence: float = 0.95
    ) -> Tuple[float, float, float]:
        """
        Compute error ellipse from position displacements.
        
        Uses 2D covariance matrix eigendecomposition.
        
        Args:
            x_displacements: E-W displacements (km).
            y_displacements: N-S displacements (km).
            confidence: Confidence level for ellipse.
            
        Returns:
            Tuple of (semi_major_km, semi_minor_km, angle_deg).
        """
        if len(x_displacements) < 3:
            return (0.0, 0.0, 0.0)
        
        # Compute covariance matrix
        points = np.column_stack([x_displacements, y_displacements])
        cov = np.cov(points.T)
        
        # Eigendecomposition
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        
        # Sort by eigenvalue (descending)
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[order]
        eigenvectors = eigenvectors[:, order]
        
        # Chi-squared value for confidence level (2 DOF)
        from scipy.stats import chi2
        chi2_val = chi2.ppf(confidence, 2)
        
        # Semi-axis lengths
        semi_major = np.sqrt(chi2_val * eigenvalues[0])
        semi_minor = np.sqrt(chi2_val * eigenvalues[1])
        
        # Rotation angle
        angle = np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))
        
        return (float(semi_major), float(semi_minor), float(angle))
    
    def compute_position_uncertainty_cone(
        self,
        ensemble_storms: List[List[StormFeature]],
        reference_storm: StormFeature,
        forecast_hours: List[float],
        match_radius_km: float = 500.0
    ) -> Dict[float, Tuple[float, float, float]]:
        """
        Compute position uncertainty at different lead times.
        
        Produces the data for a "cone of uncertainty" visualization.
        
        Args:
            ensemble_storms: List of storm lists (one per member).
            reference_storm: Reference storm for matching.
            forecast_hours: List of forecast lead times.
            match_radius_km: Maximum distance for storm matching.
            
        Returns:
            Dict mapping forecast_hour -> (mean_lat, mean_lon, radius_km).
        """
        # This is a simplified version - actual implementation would track
        # storms through time. Here we just compute spread at current time.
        stats = self.compute_storm_relative_spread(
            ensemble_storms, reference_storm, match_radius_km
        )
        
        if stats is None:
            return {}
        
        # Estimate growth of uncertainty with time (typical NHC formula)
        base_radius = stats.position_std_km * 2  # ~95% confidence
        
        result = {}
        for hour in forecast_hours:
            # Uncertainty grows roughly with sqrt(time)
            growth_factor = np.sqrt(max(1, hour / 24))
            radius = base_radius * growth_factor
            result[hour] = (stats.position_mean[0], stats.position_mean[1], radius)
        
        return result


def compute_storm_relative_spread(
    ensemble_fields: List[np.ndarray],
    storm: StormFeature,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    radius_km: float = 500.0
) -> Dict[str, float]:
    """
    Compute ensemble spread in a storm-relative reference frame.
    
    Extracts a circular region around the storm center from each
    ensemble member and computes spread statistics.
    
    Args:
        ensemble_fields: List of 2D fields (e.g., wind speed).
        storm: StormFeature defining the center.
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        radius_km: Radius around storm center (km).
        
    Returns:
        Dict with spread statistics.
    """
    if len(ensemble_fields) == 0:
        return {}
    
    # Create storm-centered mask
    dlat = np.abs(lat_grid[1, 0] - lat_grid[0, 0]) if lat_grid.shape[0] > 1 else 1.0
    dlon = np.abs(lon_grid[0, 1] - lon_grid[0, 0]) if lon_grid.shape[1] > 1 else 1.0
    
    center_lat = storm.center_lat
    center_lon = storm.center_lon
    
    # Distance from storm center
    lat_diff_km = (lat_grid - center_lat) * 111.0
    lon_diff_km = (lon_grid - center_lon) * 111.0 * np.cos(np.radians(center_lat))
    dist_km = np.sqrt(lat_diff_km**2 + lon_diff_km**2)
    
    storm_mask = dist_km <= radius_km
    
    if not np.any(storm_mask):
        return {}
    
    # Extract storm-centered values from each member
    storm_values = []
    for field in ensemble_fields:
        masked_vals = field[storm_mask]
        storm_values.append(masked_vals)
    
    storm_array = np.stack(storm_values, axis=0)
    
    # Compute statistics
    mean_field = np.mean(storm_array, axis=0)
    std_field = np.std(storm_array, axis=0)
    
    return {
        "mean_over_storm": float(np.mean(mean_field)),
        "max_over_storm": float(np.max(mean_field)),
        "mean_spread": float(np.mean(std_field)),
        "max_spread": float(np.max(std_field)),
        "spread_at_center": float(std_field[0]) if len(std_field) > 0 else 0.0,
        "n_points": int(np.sum(storm_mask)),
    }


def compute_position_uncertainty(
    ensemble_storms: List[List[StormFeature]],
    reference_lat: float,
    reference_lon: float,
    match_radius_km: float = 500.0
) -> Dict[str, float]:
    """
    Compute position uncertainty from ensemble storm positions.
    
    Args:
        ensemble_storms: List of storm lists (one per member).
        reference_lat: Reference latitude for matching.
        reference_lon: Reference longitude for matching.
        match_radius_km: Maximum distance to consider a match.
        
    Returns:
        Dict with position uncertainty metrics.
    """
    positions = []
    
    for member_storms in ensemble_storms:
        # Find closest storm
        best_storm = None
        best_dist = float('inf')
        
        for storm in member_storms:
            # Simple distance calculation
            lat_diff = (storm.center_lat - reference_lat) * 111.0
            lon_diff = (storm.center_lon - reference_lon) * 111.0 * np.cos(
                np.radians(reference_lat)
            )
            dist = np.sqrt(lat_diff**2 + lon_diff**2)
            
            if dist < best_dist and dist < match_radius_km:
                best_dist = dist
                best_storm = storm
        
        if best_storm is not None:
            positions.append((best_storm.center_lat, best_storm.center_lon))
    
    if len(positions) < 3:
        return {"n_members": len(positions), "position_std_km": np.nan}
    
    lats = np.array([p[0] for p in positions])
    lons = np.array([p[1] for p in positions])
    
    mean_lat = np.mean(lats)
    mean_lon = np.mean(lons)
    
    # Convert to km
    lat_displacements_km = (lats - mean_lat) * 111.0
    lon_displacements_km = (lons - mean_lon) * 111.0 * np.cos(np.radians(mean_lat))
    
    distances_from_mean = np.sqrt(lat_displacements_km**2 + lon_displacements_km**2)
    
    return {
        "n_members": len(positions),
        "mean_lat": float(mean_lat),
        "mean_lon": float(mean_lon),
        "position_std_km": float(np.std(distances_from_mean)),
        "position_mean_error_km": float(np.mean(distances_from_mean)),
        "position_max_error_km": float(np.max(distances_from_mean)),
        "lat_std_deg": float(np.std(lats)),
        "lon_std_deg": float(np.std(lons)),
    }


def compute_compound_probability(
    ensemble_storms: List[List[StormFeature]],
    domain: OceanDomain,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    wind_threshold_kt: float = 34.0,
    simultaneous: bool = True
) -> np.ndarray:
    """
    Compute probability of multiple storms exceeding threshold.
    
    Useful for assessing compound event risk from multiple
    concurrent storms.
    
    Args:
        ensemble_storms: List of storm lists per member.
        domain: OceanDomain for analysis.
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        wind_threshold_kt: Wind speed threshold (kt).
        simultaneous: If True, require all storms concurrent.
        
    Returns:
        2D array of exceedance probabilities.
    """
    n_members = len(ensemble_storms)
    if n_members == 0:
        return np.zeros_like(lat_grid)
    
    domain_mask = domain.create_domain_mask(lat_grid, lon_grid)
    exceedance_count = np.zeros_like(lat_grid, dtype=float)
    
    for member_storms in ensemble_storms:
        # Create combined exceedance mask for this member
        member_exceeds = np.zeros_like(lat_grid, dtype=bool)
        
        for storm in member_storms:
            if storm.max_wind is None or storm.max_wind < wind_threshold_kt:
                continue
            if storm.extent_mask is not None:
                member_exceeds |= storm.extent_mask
        
        exceedance_count += member_exceeds.astype(float)
    
    probability = exceedance_count / n_members
    return np.where(domain_mask, probability, np.nan)


def compute_spatial_correlation(
    ensemble_fields: List[np.ndarray],
    domain: OceanDomain,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    max_lag_km: float = 1000.0,
    n_lags: int = 20
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute spatial correlation structure of ensemble spread.
    
    Estimates how ensemble spread varies with distance, useful for
    understanding uncertainty propagation across the domain.
    
    Args:
        ensemble_fields: List of 2D fields per ensemble member.
        domain: OceanDomain for analysis.
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        max_lag_km: Maximum lag distance to analyze.
        n_lags: Number of lag bins.
        
    Returns:
        Tuple of (lag_distances_km, correlations).
    """
    if len(ensemble_fields) < 2:
        return np.array([]), np.array([])
    
    # Compute ensemble spread at each point
    stack = np.stack(ensemble_fields, axis=0)
    spread = np.std(stack, axis=0)
    
    domain_mask = domain.create_domain_mask(lat_grid, lon_grid)
    valid_mask = domain_mask & ~np.isnan(spread)
    
    valid_indices = np.argwhere(valid_mask)
    if len(valid_indices) < 100:
        return np.array([]), np.array([])
    
    # Sample point pairs
    n_samples = min(5000, len(valid_indices) * 10)
    rng = np.random.default_rng(42)
    
    idx1 = rng.choice(len(valid_indices), size=n_samples, replace=True)
    idx2 = rng.choice(len(valid_indices), size=n_samples, replace=True)
    different = idx1 != idx2
    idx1, idx2 = idx1[different], idx2[different]
    
    # Get coordinates
    pts1 = valid_indices[idx1]
    pts2 = valid_indices[idx2]
    
    lats1 = lat_grid[pts1[:, 0], pts1[:, 1]]
    lons1 = lon_grid[pts1[:, 0], pts1[:, 1]]
    lats2 = lat_grid[pts2[:, 0], pts2[:, 1]]
    lons2 = lon_grid[pts2[:, 0], pts2[:, 1]]
    
    # Calculate distances
    mean_lat = (lats1 + lats2) / 2
    dlat_km = (lats2 - lats1) * 111.0
    dlon_km = (lons2 - lons1) * 111.0 * np.cos(np.radians(mean_lat))
    distances = np.sqrt(dlat_km**2 + dlon_km**2)
    
    # Get spread values
    vals1 = spread[valid_indices[idx1, 0], valid_indices[idx1, 1]]
    vals2 = spread[valid_indices[idx2, 0], valid_indices[idx2, 1]]
    
    # Bin by distance and compute correlation
    lag_edges = np.linspace(0, max_lag_km, n_lags + 1)
    lag_centers = (lag_edges[:-1] + lag_edges[1:]) / 2
    correlations = np.zeros(n_lags)
    
    for i in range(n_lags):
        in_bin = (distances >= lag_edges[i]) & (distances < lag_edges[i+1])
        if np.sum(in_bin) > 10:
            r, _ = pearsonr(vals1[in_bin], vals2[in_bin])
            correlations[i] = r if not np.isnan(r) else 0.0
        else:
            correlations[i] = np.nan
    
    return lag_centers, correlations


__all__ = [
    "StormEnsembleStats",
    "GridEnsembleStats",
    "EnsembleAnalyzer",
    "compute_storm_relative_spread",
    "compute_position_uncertainty",
    "compute_compound_probability",
    "compute_spatial_correlation",
]
