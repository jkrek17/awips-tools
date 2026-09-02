"""
Grid-based storm feature identification for marine analysis.

Provides algorithms to identify storm centers and extents from:
- Pressure fields (MSLP minima)
- Wind fields (maximum wind speed regions)
- Vorticity fields (cyclonic circulation centers)

Designed for simultaneous detection of multiple storm systems within
a domain, which is critical for North Atlantic/Pacific analysis where
3-6 concurrent systems are common.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import ndimage
from scipy.ndimage import label, maximum_filter, minimum_filter

from .domains import OceanDomain, EARTH_RADIUS_KM


@dataclass
class StormFeature:
    """
    Representation of an identified storm feature on the grid.
    
    Attributes:
        storm_id: Unique identifier for this storm.
        center_lat: Storm center latitude (degrees).
        center_lon: Storm center longitude (degrees).
        center_value: Field value at storm center (pressure/wind/vorticity).
        max_wind: Maximum wind speed in storm region (kt).
        min_pressure: Minimum pressure (hPa) if available.
        extent_km: Approximate storm diameter (km).
        area_km2: Storm area (km²).
        grid_indices: (row, col) of storm center in the grid.
        extent_mask: Boolean array marking storm extent.
        intensity_category: Qualitative intensity (e.g., 'tropical', 'extratropical').
        confidence: Detection confidence score (0-1).
    """
    storm_id: str
    center_lat: float
    center_lon: float
    center_value: float
    max_wind: Optional[float] = None
    min_pressure: Optional[float] = None
    extent_km: float = 500.0
    area_km2: float = 0.0
    grid_indices: Tuple[int, int] = (0, 0)
    extent_mask: Optional[np.ndarray] = None
    intensity_category: str = "unknown"
    confidence: float = 1.0
    
    @property
    def is_intense(self) -> bool:
        """Check if storm meets intensity criteria."""
        if self.max_wind is not None and self.max_wind >= 64:  # Hurricane force
            return True
        if self.min_pressure is not None and self.min_pressure <= 980:
            return True
        return False


@dataclass
class StormIdentificationConfig:
    """
    Configuration parameters for storm identification.
    
    Attributes:
        min_separation_km: Minimum distance between storm centers.
        min_pressure_anomaly_hpa: Minimum pressure depression for detection.
        min_wind_threshold_kt: Minimum wind speed to consider.
        max_storms: Maximum number of storms to identify per domain.
        smoothing_scale_km: Smoothing scale for noise reduction.
        use_vorticity: Whether to use vorticity for identification.
        vorticity_threshold: Minimum vorticity magnitude (1/s).
        search_radius_km: Radius for feature extent calculation.
    """
    min_separation_km: float = 500.0
    min_pressure_anomaly_hpa: float = 4.0
    min_wind_threshold_kt: float = 34.0
    max_storms: int = 10
    smoothing_scale_km: float = 100.0
    use_vorticity: bool = True
    vorticity_threshold: float = 1e-5
    search_radius_km: float = 800.0


class StormIdentifier:
    """
    Identifies multiple storm features from gridded meteorological data.
    
    This class implements robust storm detection suitable for operational
    marine forecasting, handling multiple concurrent systems and providing
    confidence estimates for each detection.
    """
    
    def __init__(
        self,
        domain: OceanDomain,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray,
        config: Optional[StormIdentificationConfig] = None
    ):
        """
        Initialize the storm identifier.
        
        Args:
            domain: OceanDomain for the analysis region.
            lat_grid: 2D latitude array.
            lon_grid: 2D longitude array.
            config: Optional configuration parameters.
        """
        self.domain = domain
        self.lat_grid = lat_grid
        self.lon_grid = lon_grid
        self.config = config or StormIdentificationConfig()
        
        # Create domain mask
        self.domain_mask = domain.create_domain_mask(lat_grid, lon_grid)
        
        # Calculate grid metrics
        self._calculate_metrics()
        
        # Storm counter for unique IDs
        self._storm_counter = 0
    
    def _calculate_metrics(self):
        """Calculate grid spacing metrics."""
        center_lat = self.domain.center_lat
        if self.lat_grid.shape[0] > 1:
            dlat = np.abs(self.lat_grid[1, 0] - self.lat_grid[0, 0])
        else:
            dlat = 1.0
        if self.lon_grid.shape[1] > 1:
            dlon = np.abs(self.lon_grid[0, 1] - self.lon_grid[0, 0])
        else:
            dlon = 1.0
            
        self.dy_km, self.dx_km = self.domain.degrees_to_km(center_lat, dlat, dlon)
        self.dlat = dlat
        self.dlon = dlon
    
    def _generate_storm_id(self) -> str:
        """Generate a unique storm identifier."""
        self._storm_counter += 1
        return f"STORM_{self._storm_counter:03d}"
    
    def identify_from_pressure(
        self,
        pressure: np.ndarray,
        wind_speed: Optional[np.ndarray] = None
    ) -> List[StormFeature]:
        """
        Identify storm centers from MSLP field.
        
        Storms are detected as local pressure minima that exceed a
        threshold anomaly from the background field.
        
        Args:
            pressure: 2D MSLP field (hPa).
            wind_speed: Optional wind speed field (kt) for intensity.
            
        Returns:
            List of StormFeature objects, sorted by intensity.
        """
        storms = []
        
        # Apply domain mask and smooth
        pressure_masked = np.where(self.domain_mask, pressure, np.nan)
        pressure_smooth = self._smooth_field(pressure_masked)
        
        # Calculate background field (large-scale mean)
        background = self._calculate_background(pressure_smooth)
        anomaly = background - pressure_smooth  # Positive for low pressure
        
        # Find local minima
        min_sep_pts = max(3, int(self.config.min_separation_km / np.mean([self.dx_km, self.dy_km])))
        
        # Local minimum detection
        local_min = pressure_smooth == minimum_filter(
            pressure_smooth, size=min_sep_pts, mode='constant', cval=np.inf
        )
        
        # Apply anomaly threshold
        significant = anomaly >= self.config.min_pressure_anomaly_hpa
        candidates = local_min & significant & self.domain_mask
        
        # Get candidate locations
        candidate_indices = np.argwhere(candidates)
        
        # Sort by anomaly strength
        anomaly_values = [anomaly[i, j] for i, j in candidate_indices]
        sorted_indices = np.argsort(anomaly_values)[::-1]
        
        # Select storms with minimum separation
        selected_centers = []
        for idx in sorted_indices:
            if len(selected_centers) >= self.config.max_storms:
                break
                
            i, j = candidate_indices[idx]
            center_lat = float(self.lat_grid[i, j])
            center_lon = float(self.lon_grid[i, j])
            
            # Check separation from existing storms
            too_close = False
            for existing_lat, existing_lon in selected_centers:
                dist = self.domain.haversine_distance(
                    center_lat, center_lon, existing_lat, existing_lon
                )
                if dist < self.config.min_separation_km:
                    too_close = True
                    break
            
            if not too_close:
                selected_centers.append((center_lat, center_lon))
                
                # Create storm feature
                storm = self._create_storm_feature(
                    i, j, center_lat, center_lon,
                    float(pressure_smooth[i, j]),
                    pressure_smooth, wind_speed
                )
                storm.min_pressure = float(pressure_smooth[i, j])
                storms.append(storm)
        
        # Sort by intensity (lowest pressure first)
        storms.sort(key=lambda s: s.min_pressure or 1100)
        
        return storms
    
    def identify_from_wind(
        self,
        wind_speed: np.ndarray,
        wind_dir: Optional[np.ndarray] = None,
        pressure: Optional[np.ndarray] = None
    ) -> List[StormFeature]:
        """
        Identify storm centers from wind speed maxima.
        
        Useful for detecting storms when pressure data is unavailable
        or unreliable. Identifies regions of elevated wind speed and
        finds local maxima.
        
        Args:
            wind_speed: 2D wind speed field (kt).
            wind_dir: Optional wind direction field (degrees).
            pressure: Optional pressure field for intensity.
            
        Returns:
            List of StormFeature objects.
        """
        storms = []
        
        # Apply mask and threshold
        wind_masked = np.where(self.domain_mask, wind_speed, 0)
        wind_smooth = self._smooth_field(wind_masked)
        
        # Find regions exceeding threshold
        above_threshold = wind_smooth >= self.config.min_wind_threshold_kt
        
        # Label connected components
        labeled, n_features = label(above_threshold & self.domain_mask)
        
        if n_features == 0:
            return storms
        
        min_sep_pts = max(3, int(self.config.min_separation_km / np.mean([self.dx_km, self.dy_km])))
        
        # For each feature, find the maximum wind location
        for feature_id in range(1, min(n_features + 1, self.config.max_storms + 1)):
            feature_mask = labeled == feature_id
            
            if not np.any(feature_mask):
                continue
            
            # Find maximum within this feature
            feature_wind = np.where(feature_mask, wind_smooth, 0)
            max_idx = np.unravel_index(np.argmax(feature_wind), feature_wind.shape)
            i, j = max_idx
            
            center_lat = float(self.lat_grid[i, j])
            center_lon = float(self.lon_grid[i, j])
            max_wind = float(wind_smooth[i, j])
            
            # Check separation from existing storms
            too_close = False
            for existing in storms:
                dist = self.domain.haversine_distance(
                    center_lat, center_lon,
                    existing.center_lat, existing.center_lon
                )
                if dist < self.config.min_separation_km:
                    too_close = True
                    break
            
            if not too_close and max_wind >= self.config.min_wind_threshold_kt:
                storm = self._create_storm_feature(
                    i, j, center_lat, center_lon,
                    max_wind, None, wind_smooth
                )
                storm.max_wind = max_wind
                storm.extent_mask = feature_mask
                
                if pressure is not None:
                    # Find minimum pressure near wind max
                    search_mask = self._create_search_mask(i, j)
                    pressure_search = np.where(
                        search_mask & self.domain_mask, pressure, np.inf
                    )
                    storm.min_pressure = float(np.min(pressure_search))
                
                storms.append(storm)
        
        # Sort by max wind (highest first)
        storms.sort(key=lambda s: -(s.max_wind or 0))
        
        return storms
    
    def identify_from_vorticity(
        self,
        u_wind: np.ndarray,
        v_wind: np.ndarray,
        wind_speed: Optional[np.ndarray] = None,
        pressure: Optional[np.ndarray] = None
    ) -> List[StormFeature]:
        """
        Identify storm centers from vorticity maxima.
        
        Most physically robust method as it directly identifies
        cyclonic circulation centers. Requires u/v wind components.
        
        Args:
            u_wind: Zonal wind component (m/s).
            v_wind: Meridional wind component (m/s).
            wind_speed: Optional wind speed (kt).
            pressure: Optional pressure field (hPa).
            
        Returns:
            List of StormFeature objects.
        """
        from .grid_analysis import compute_vorticity
        
        storms = []
        
        # Compute relative vorticity
        vorticity = compute_vorticity(
            u_wind, v_wind, self.dy_km, self.dx_km, self.domain_mask
        )
        
        # In Northern Hemisphere, cyclonic = positive vorticity
        # Use absolute value for detection, then check sign
        center_lat = self.domain.center_lat
        if center_lat >= 0:
            cyclonic_vort = vorticity  # NH: positive = cyclonic
        else:
            cyclonic_vort = -vorticity  # SH: negative = cyclonic
        
        # Apply threshold
        vort_masked = np.where(self.domain_mask, cyclonic_vort, -np.inf)
        vort_smooth = self._smooth_field(vort_masked)
        
        above_threshold = vort_smooth >= self.config.vorticity_threshold
        
        # Find local maxima
        min_sep_pts = max(3, int(self.config.min_separation_km / np.mean([self.dx_km, self.dy_km])))
        
        local_max = vort_smooth == maximum_filter(
            vort_smooth, size=min_sep_pts, mode='constant', cval=-np.inf
        )
        
        candidates = local_max & above_threshold & self.domain_mask
        candidate_indices = np.argwhere(candidates)
        
        # Sort by vorticity magnitude
        vort_values = [vort_smooth[i, j] for i, j in candidate_indices]
        sorted_indices = np.argsort(vort_values)[::-1]
        
        selected_centers = []
        for idx in sorted_indices:
            if len(selected_centers) >= self.config.max_storms:
                break
                
            i, j = candidate_indices[idx]
            center_lat = float(self.lat_grid[i, j])
            center_lon = float(self.lon_grid[i, j])
            
            # Check separation
            too_close = False
            for existing_lat, existing_lon in selected_centers:
                dist = self.domain.haversine_distance(
                    center_lat, center_lon, existing_lat, existing_lon
                )
                if dist < self.config.min_separation_km:
                    too_close = True
                    break
            
            if not too_close:
                selected_centers.append((center_lat, center_lon))
                
                storm = self._create_storm_feature(
                    i, j, center_lat, center_lon,
                    float(vort_smooth[i, j]),
                    pressure, wind_speed
                )
                storms.append(storm)
        
        return storms
    
    def _smooth_field(self, field: np.ndarray) -> np.ndarray:
        """Apply Gaussian smoothing to reduce noise."""
        sigma_pts = self.config.smoothing_scale_km / np.mean([self.dx_km, self.dy_km])
        
        # Handle NaN values
        field_filled = np.nan_to_num(field, nan=np.nanmean(field))
        smoothed = ndimage.gaussian_filter(field_filled, sigma=sigma_pts, mode='nearest')
        
        # Restore NaN in masked regions
        return np.where(np.isnan(field), np.nan, smoothed)
    
    def _calculate_background(self, field: np.ndarray) -> np.ndarray:
        """Calculate large-scale background field."""
        # Use a large smoothing scale (~1000 km)
        sigma_pts = 1000.0 / np.mean([self.dx_km, self.dy_km])
        field_filled = np.nan_to_num(field, nan=np.nanmean(field))
        return ndimage.gaussian_filter(field_filled, sigma=sigma_pts, mode='nearest')
    
    def _create_search_mask(self, center_i: int, center_j: int) -> np.ndarray:
        """Create a circular search mask around a point."""
        radius_pts = int(self.config.search_radius_km / np.mean([self.dx_km, self.dy_km]))
        
        y, x = np.ogrid[:self.lat_grid.shape[0], :self.lat_grid.shape[1]]
        dist_sq = (y - center_i)**2 + (x - center_j)**2
        return dist_sq <= radius_pts**2
    
    def _create_storm_feature(
        self,
        i: int, j: int,
        center_lat: float, center_lon: float,
        center_value: float,
        pressure: Optional[np.ndarray],
        wind_speed: Optional[np.ndarray]
    ) -> StormFeature:
        """Create a StormFeature from detection results."""
        storm_id = self._generate_storm_id()
        
        # Calculate extent
        search_mask = self._create_search_mask(i, j)
        
        # Estimate intensity category
        intensity = "weak"
        max_wind = None
        min_pressure = None
        
        if wind_speed is not None:
            wind_search = np.where(search_mask & self.domain_mask, wind_speed, 0)
            max_wind = float(np.max(wind_search))
            
            if max_wind >= 64:
                intensity = "hurricane"
            elif max_wind >= 48:
                intensity = "storm"
            elif max_wind >= 34:
                intensity = "gale"
            else:
                intensity = "moderate"
        
        if pressure is not None:
            pressure_search = np.where(
                search_mask & self.domain_mask, pressure, np.inf
            )
            min_pressure = float(np.min(pressure_search))
            
            if min_pressure <= 960:
                intensity = "intense"
            elif min_pressure <= 980:
                intensity = "strong" if intensity == "weak" else intensity
            elif min_pressure <= 1000:
                intensity = "moderate" if intensity == "weak" else intensity
        
        # Calculate area
        extent_mask = search_mask & self.domain_mask
        area_km2 = float(np.sum(extent_mask) * self.dx_km * self.dy_km)
        
        # Estimate diameter
        extent_km = 2.0 * np.sqrt(area_km2 / np.pi)
        
        # Confidence based on signal strength
        confidence = min(1.0, abs(center_value) / 10.0)  # Adjust based on field type
        
        return StormFeature(
            storm_id=storm_id,
            center_lat=center_lat,
            center_lon=center_lon,
            center_value=center_value,
            max_wind=max_wind,
            min_pressure=min_pressure,
            extent_km=extent_km,
            area_km2=area_km2,
            grid_indices=(i, j),
            extent_mask=extent_mask,
            intensity_category=intensity,
            confidence=confidence
        )


def identify_storms_from_pressure(
    pressure: np.ndarray,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    domain: OceanDomain,
    wind_speed: Optional[np.ndarray] = None,
    config: Optional[StormIdentificationConfig] = None
) -> List[StormFeature]:
    """
    Convenience function to identify storms from pressure.
    
    Args:
        pressure: 2D MSLP field (hPa).
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        domain: OceanDomain for analysis.
        wind_speed: Optional wind speed field (kt).
        config: Optional configuration.
        
    Returns:
        List of StormFeature objects.
    """
    identifier = StormIdentifier(domain, lat_grid, lon_grid, config)
    return identifier.identify_from_pressure(pressure, wind_speed)


def identify_storms_from_wind(
    wind_speed: np.ndarray,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    domain: OceanDomain,
    wind_dir: Optional[np.ndarray] = None,
    pressure: Optional[np.ndarray] = None,
    config: Optional[StormIdentificationConfig] = None
) -> List[StormFeature]:
    """
    Convenience function to identify storms from wind field.
    
    Args:
        wind_speed: 2D wind speed field (kt).
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        domain: OceanDomain for analysis.
        wind_dir: Optional wind direction (degrees).
        pressure: Optional pressure field (hPa).
        config: Optional configuration.
        
    Returns:
        List of StormFeature objects.
    """
    identifier = StormIdentifier(domain, lat_grid, lon_grid, config)
    return identifier.identify_from_wind(wind_speed, wind_dir, pressure)


def calculate_storm_extent(
    storm: StormFeature,
    field: np.ndarray,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    threshold_fraction: float = 0.5
) -> Tuple[np.ndarray, float]:
    """
    Calculate detailed storm extent based on field threshold.
    
    Args:
        storm: StormFeature to analyze.
        field: 2D field for extent calculation (pressure anomaly, wind, etc.).
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        threshold_fraction: Fraction of max anomaly to define boundary.
        
    Returns:
        Tuple of (extent_mask, area_km2).
    """
    i, j = storm.grid_indices
    
    # Get field value at center and calculate threshold
    center_val = field[i, j]
    field_range = np.nanmax(field) - np.nanmin(field)
    threshold = center_val - threshold_fraction * field_range
    
    # Create extent mask using flood fill approach
    from scipy.ndimage import binary_dilation
    
    seed_mask = np.zeros_like(field, dtype=bool)
    seed_mask[i, j] = True
    
    # Iteratively grow region
    extent = seed_mask.copy()
    for _ in range(1000):  # Max iterations
        new_extent = binary_dilation(extent)
        # Only include points that meet threshold
        new_extent = new_extent & (field >= threshold)
        
        if np.array_equal(extent, new_extent):
            break
        extent = new_extent
    
    # Calculate area
    dlat = np.abs(lat_grid[1, 0] - lat_grid[0, 0]) if lat_grid.shape[0] > 1 else 1.0
    dlon = np.abs(lon_grid[0, 1] - lon_grid[0, 0]) if lon_grid.shape[1] > 1 else 1.0
    mean_lat = np.mean(lat_grid[extent]) if np.any(extent) else 45.0
    
    dy_km = dlat * 111.0
    dx_km = dlon * 111.0 * np.cos(np.radians(mean_lat))
    area_km2 = float(np.sum(extent) * dx_km * dy_km)
    
    return extent, area_km2


__all__ = [
    "StormFeature",
    "StormIdentificationConfig",
    "StormIdentifier",
    "identify_storms_from_pressure",
    "identify_storms_from_wind",
    "calculate_storm_extent",
]
