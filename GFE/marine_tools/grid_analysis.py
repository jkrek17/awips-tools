"""
Grid-based spatial analysis utilities for marine meteorology.

Provides tools for:
- Grid subsetting and extraction by domain
- Spatial gradient and derivative calculations
- Grid-based statistics (mean, variance, percentiles)
- Spatial filtering and smoothing with proper edge handling
- Variogram/spatial autocorrelation analysis
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import ndimage
from scipy.spatial.distance import cdist

from .domains import OceanDomain, NORTH_ATLANTIC, NORTH_PACIFIC


@dataclass
class SpatialStatistics:
    """
    Container for grid-based spatial statistics.
    
    Attributes:
        mean: Grid mean value.
        std: Standard deviation.
        variance: Variance.
        min_val: Minimum value.
        max_val: Maximum value.
        percentiles: Dict mapping percentile -> value.
        valid_fraction: Fraction of non-masked points.
        gradient_magnitude_mean: Mean of |∇field|.
        laplacian_mean: Mean of ∇²field.
        spatial_autocorr_range_km: Decorrelation length scale.
    """
    mean: float
    std: float
    variance: float
    min_val: float
    max_val: float
    percentiles: Dict[int, float]
    valid_fraction: float
    gradient_magnitude_mean: Optional[float] = None
    laplacian_mean: Optional[float] = None
    spatial_autocorr_range_km: Optional[float] = None


class GridAnalyzer:
    """
    Analyzer for grid-based marine meteorological data.
    
    Handles coordinate transformations, subgrid extraction, and
    spatial statistics calculation for ocean domains that may
    cross the dateline.
    """
    
    def __init__(
        self,
        domain: OceanDomain,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray
    ):
        """
        Initialize the analyzer.
        
        Args:
            domain: OceanDomain defining the analysis region.
            lat_grid: 2D array of latitudes for the input data grid.
            lon_grid: 2D array of longitudes for the input data grid.
        """
        self.domain = domain
        self.lat_grid = lat_grid
        self.lon_grid = lon_grid
        
        # Create domain mask
        self.domain_mask = domain.create_domain_mask(lat_grid, lon_grid)
        
        # Calculate grid spacing
        self._calculate_grid_metrics()
    
    def _calculate_grid_metrics(self):
        """Calculate grid spacing in degrees and km."""
        # Estimate resolution from grid
        if self.lat_grid.shape[0] > 1:
            self.dlat = np.abs(self.lat_grid[1, 0] - self.lat_grid[0, 0])
        else:
            self.dlat = 1.0
            
        if self.lon_grid.shape[1] > 1:
            # Handle dateline crossing
            dlon = self.lon_grid[0, 1] - self.lon_grid[0, 0]
            if dlon < -180:
                dlon += 360
            elif dlon > 180:
                dlon -= 360
            self.dlon = np.abs(dlon)
        else:
            self.dlon = 1.0
            
        # Convert to km at domain center
        center_lat = self.domain.center_lat
        self.dy_km, self.dx_km = self.domain.degrees_to_km(
            center_lat, self.dlat, self.dlon
        )
    
    def extract_subgrid(
        self,
        data: np.ndarray,
        apply_mask: bool = True,
        fill_value: float = np.nan
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Extract the portion of data grid within the domain.
        
        Args:
            data: 2D data array matching lat_grid/lon_grid shape.
            apply_mask: Whether to apply domain mask.
            fill_value: Value for masked points.
            
        Returns:
            Tuple of (data_sub, lat_sub, lon_sub) arrays.
        """
        if apply_mask:
            data_masked = np.where(self.domain_mask, data, fill_value)
        else:
            data_masked = data.copy()
            
        # Find bounding box of masked region
        rows = np.any(self.domain_mask, axis=1)
        cols = np.any(self.domain_mask, axis=0)
        
        if not np.any(rows) or not np.any(cols):
            return data_masked, self.lat_grid.copy(), self.lon_grid.copy()
            
        row_indices = np.where(rows)[0]
        col_indices = np.where(cols)[0]
        
        r_min, r_max = row_indices[0], row_indices[-1] + 1
        c_min, c_max = col_indices[0], col_indices[-1] + 1
        
        return (
            data_masked[r_min:r_max, c_min:c_max],
            self.lat_grid[r_min:r_max, c_min:c_max],
            self.lon_grid[r_min:r_max, c_min:c_max],
        )
    
    def compute_statistics(
        self,
        data: np.ndarray,
        percentile_list: Optional[List[int]] = None,
        compute_gradients: bool = True,
        compute_autocorr: bool = False,
        max_lag_km: float = 1000.0
    ) -> SpatialStatistics:
        """
        Compute comprehensive spatial statistics for grid data.
        
        Args:
            data: 2D data array.
            percentile_list: List of percentiles to compute (default [10,25,50,75,90]).
            compute_gradients: Whether to compute gradient statistics.
            compute_autocorr: Whether to estimate spatial autocorrelation range.
            max_lag_km: Maximum lag distance for autocorrelation (km).
            
        Returns:
            SpatialStatistics instance.
        """
        if percentile_list is None:
            percentile_list = [10, 25, 50, 75, 90]
            
        # Apply domain mask
        masked_data = np.where(self.domain_mask, data, np.nan)
        valid_data = masked_data[~np.isnan(masked_data)]
        
        if len(valid_data) == 0:
            return SpatialStatistics(
                mean=np.nan, std=np.nan, variance=np.nan,
                min_val=np.nan, max_val=np.nan,
                percentiles={p: np.nan for p in percentile_list},
                valid_fraction=0.0
            )
        
        # Basic statistics
        mean = float(np.mean(valid_data))
        std = float(np.std(valid_data))
        variance = float(np.var(valid_data))
        min_val = float(np.min(valid_data))
        max_val = float(np.max(valid_data))
        percentiles = {p: float(np.percentile(valid_data, p)) for p in percentile_list}
        valid_fraction = len(valid_data) / self.domain_mask.size
        
        # Gradient statistics
        grad_mag_mean = None
        laplacian_mean = None
        if compute_gradients:
            grad_y, grad_x = compute_gradient_fields(
                data, self.dy_km, self.dx_km, mask=self.domain_mask
            )
            grad_mag = np.sqrt(grad_x**2 + grad_y**2)
            grad_mag_masked = grad_mag[self.domain_mask & ~np.isnan(grad_mag)]
            if len(grad_mag_masked) > 0:
                grad_mag_mean = float(np.mean(grad_mag_masked))
                
            laplacian = compute_laplacian(data, self.dy_km, self.dx_km, mask=self.domain_mask)
            laplacian_masked = laplacian[self.domain_mask & ~np.isnan(laplacian)]
            if len(laplacian_masked) > 0:
                laplacian_mean = float(np.mean(laplacian_masked))
        
        # Spatial autocorrelation
        autocorr_range = None
        if compute_autocorr:
            autocorr_range = self._estimate_autocorr_range(data, max_lag_km)
        
        return SpatialStatistics(
            mean=mean, std=std, variance=variance,
            min_val=min_val, max_val=max_val,
            percentiles=percentiles,
            valid_fraction=valid_fraction,
            gradient_magnitude_mean=grad_mag_mean,
            laplacian_mean=laplacian_mean,
            spatial_autocorr_range_km=autocorr_range
        )
    
    def _estimate_autocorr_range(
        self,
        data: np.ndarray,
        max_lag_km: float,
        n_samples: int = 1000
    ) -> Optional[float]:
        """
        Estimate the spatial decorrelation length scale.
        
        Uses a semi-variogram approach: finds the lag at which
        correlation drops to 1/e of its maximum.
        
        Args:
            data: 2D data array.
            max_lag_km: Maximum lag distance to consider.
            n_samples: Number of point pairs to sample.
            
        Returns:
            Decorrelation range in km, or None if not estimable.
        """
        # Get valid points
        valid_mask = self.domain_mask & ~np.isnan(data)
        valid_indices = np.argwhere(valid_mask)
        
        if len(valid_indices) < 100:
            return None
            
        # Sample random pairs
        n_pairs = min(n_samples, len(valid_indices) * (len(valid_indices) - 1) // 2)
        if n_pairs < 50:
            return None
            
        rng = np.random.default_rng(42)
        idx1 = rng.choice(len(valid_indices), size=n_pairs, replace=True)
        idx2 = rng.choice(len(valid_indices), size=n_pairs, replace=True)
        
        # Remove same-point pairs
        different = idx1 != idx2
        idx1, idx2 = idx1[different], idx2[different]
        
        if len(idx1) < 50:
            return None
        
        # Calculate distances and value differences
        pts1 = valid_indices[idx1]
        pts2 = valid_indices[idx2]
        
        lats1 = self.lat_grid[pts1[:, 0], pts1[:, 1]]
        lons1 = self.lon_grid[pts1[:, 0], pts1[:, 1]]
        lats2 = self.lat_grid[pts2[:, 0], pts2[:, 1]]
        lons2 = self.lon_grid[pts2[:, 0], pts2[:, 1]]
        
        # Approximate distances (faster than haversine for many points)
        mean_lat = (lats1 + lats2) / 2
        dlat_km = (lats2 - lats1) * 111.0
        dlon_km = (lons2 - lons1) * 111.0 * np.cos(np.radians(mean_lat))
        distances = np.sqrt(dlat_km**2 + dlon_km**2)
        
        # Filter by max lag
        valid = distances < max_lag_km
        distances = distances[valid]
        idx1, idx2 = idx1[valid], idx2[valid]
        
        if len(distances) < 50:
            return None
        
        # Value differences (semi-variance)
        vals1 = data[valid_indices[idx1, 0], valid_indices[idx1, 1]]
        vals2 = data[valid_indices[idx2, 0], valid_indices[idx2, 1]]
        gamma = 0.5 * (vals1 - vals2)**2
        
        # Bin by distance and fit
        n_bins = 20
        bin_edges = np.linspace(0, max_lag_km, n_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        
        binned_gamma = []
        for i in range(n_bins):
            in_bin = (distances >= bin_edges[i]) & (distances < bin_edges[i+1])
            if np.sum(in_bin) > 5:
                binned_gamma.append(np.mean(gamma[in_bin]))
            else:
                binned_gamma.append(np.nan)
        
        binned_gamma = np.array(binned_gamma)
        valid_bins = ~np.isnan(binned_gamma)
        
        if np.sum(valid_bins) < 5:
            return None
        
        # Estimate range as distance where gamma reaches 63% of sill
        sill = np.nanmax(binned_gamma)
        threshold = 0.63 * sill
        
        above = binned_gamma[valid_bins] >= threshold
        if not np.any(above):
            return float(bin_centers[valid_bins][-1])
            
        first_above = np.argmax(above)
        return float(bin_centers[valid_bins][first_above])
    
    def apply_spatial_filter(
        self,
        data: np.ndarray,
        filter_type: str = "gaussian",
        length_scale_km: Optional[float] = None,
        preserve_extremes: bool = False
    ) -> np.ndarray:
        """
        Apply spatial filtering/smoothing to grid data.
        
        Args:
            data: 2D data array.
            filter_type: 'gaussian', 'uniform', 'median'.
            length_scale_km: Filter length scale in km (default: domain characteristic).
            preserve_extremes: Use min/max filters to preserve local extrema.
            
        Returns:
            Filtered data array.
        """
        if length_scale_km is None:
            length_scale_km = self.domain.characteristic_length_km / 4
        
        # Convert length scale to grid points
        sigma_pts = length_scale_km / np.mean([self.dx_km, self.dy_km])
        
        # Handle masked regions
        data_filled = np.where(self.domain_mask, data, np.nan)
        data_filled = np.nan_to_num(data_filled, nan=np.nanmean(data))
        
        if filter_type == "gaussian":
            filtered = ndimage.gaussian_filter(data_filled, sigma=sigma_pts, mode='nearest')
        elif filter_type == "uniform":
            size = max(3, int(2 * sigma_pts + 1))
            if size % 2 == 0:
                size += 1
            filtered = ndimage.uniform_filter(data_filled, size=size, mode='nearest')
        elif filter_type == "median":
            size = max(3, int(2 * sigma_pts + 1))
            if size % 2 == 0:
                size += 1
            filtered = ndimage.median_filter(data_filled, size=size, mode='nearest')
        else:
            raise ValueError(f"Unknown filter type: {filter_type}")
        
        if preserve_extremes:
            # Preserve local maxima and minima
            max_filtered = ndimage.maximum_filter(data_filled, size=int(sigma_pts))
            min_filtered = ndimage.minimum_filter(data_filled, size=int(sigma_pts))
            
            is_local_max = (data_filled == max_filtered)
            is_local_min = (data_filled == min_filtered)
            
            filtered = np.where(is_local_max | is_local_min, data_filled, filtered)
        
        # Re-apply domain mask
        return np.where(self.domain_mask, filtered, np.nan)


def extract_subgrid(
    data: np.ndarray,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    domain: OceanDomain
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Convenience function to extract subgrid for a domain.
    
    Args:
        data: 2D data array.
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        domain: OceanDomain defining extraction region.
        
    Returns:
        Tuple of (data_sub, lat_sub, lon_sub).
    """
    analyzer = GridAnalyzer(domain, lat_grid, lon_grid)
    return analyzer.extract_subgrid(data)


def compute_spatial_statistics(
    data: np.ndarray,
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    domain: OceanDomain,
    **kwargs
) -> SpatialStatistics:
    """
    Convenience function to compute spatial statistics.
    
    Args:
        data: 2D data array.
        lat_grid: 2D latitude array.
        lon_grid: 2D longitude array.
        domain: OceanDomain defining analysis region.
        **kwargs: Additional arguments for compute_statistics.
        
    Returns:
        SpatialStatistics instance.
    """
    analyzer = GridAnalyzer(domain, lat_grid, lon_grid)
    return analyzer.compute_statistics(data, **kwargs)


def compute_gradient_fields(
    data: np.ndarray,
    dy_km: float,
    dx_km: float,
    mask: Optional[np.ndarray] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute gradient components of a 2D field.
    
    Uses central differencing with proper boundary handling.
    
    Args:
        data: 2D data array.
        dy_km: Grid spacing in y direction (km).
        dx_km: Grid spacing in x direction (km).
        mask: Optional boolean mask (True = valid).
        
    Returns:
        Tuple of (grad_y, grad_x) arrays (units: data_units/km).
    """
    # Central differences
    grad_y = np.gradient(data, dy_km, axis=0)
    grad_x = np.gradient(data, dx_km, axis=1)
    
    if mask is not None:
        grad_y = np.where(mask, grad_y, np.nan)
        grad_x = np.where(mask, grad_x, np.nan)
    
    return grad_y, grad_x


def compute_laplacian(
    data: np.ndarray,
    dy_km: float,
    dx_km: float,
    mask: Optional[np.ndarray] = None
) -> np.ndarray:
    """
    Compute the Laplacian (∇²) of a 2D field.
    
    Args:
        data: 2D data array.
        dy_km: Grid spacing in y direction (km).
        dx_km: Grid spacing in x direction (km).
        mask: Optional boolean mask.
        
    Returns:
        Laplacian array (units: data_units/km²).
    """
    # Second derivatives
    d2y = np.gradient(np.gradient(data, dy_km, axis=0), dy_km, axis=0)
    d2x = np.gradient(np.gradient(data, dx_km, axis=1), dx_km, axis=1)
    
    laplacian = d2y + d2x
    
    if mask is not None:
        laplacian = np.where(mask, laplacian, np.nan)
    
    return laplacian


def compute_vorticity(
    u: np.ndarray,
    v: np.ndarray,
    dy_km: float,
    dx_km: float,
    mask: Optional[np.ndarray] = None
) -> np.ndarray:
    """
    Compute relative vorticity from wind components.
    
    ζ = ∂v/∂x - ∂u/∂y
    
    Args:
        u: Zonal wind component.
        v: Meridional wind component.
        dy_km: Grid spacing in y direction (km).
        dx_km: Grid spacing in x direction (km).
        mask: Optional boolean mask.
        
    Returns:
        Vorticity array (units: 1/s if winds in m/s).
    """
    dvdx = np.gradient(v, dx_km * 1000, axis=1)  # Convert to meters
    dudy = np.gradient(u, dy_km * 1000, axis=0)
    
    vorticity = dvdx - dudy
    
    if mask is not None:
        vorticity = np.where(mask, vorticity, np.nan)
    
    return vorticity


def compute_divergence(
    u: np.ndarray,
    v: np.ndarray,
    dy_km: float,
    dx_km: float,
    mask: Optional[np.ndarray] = None
) -> np.ndarray:
    """
    Compute horizontal divergence from wind components.
    
    div = ∂u/∂x + ∂v/∂y
    
    Args:
        u: Zonal wind component.
        v: Meridional wind component.
        dy_km: Grid spacing in y direction (km).
        dx_km: Grid spacing in x direction (km).
        mask: Optional boolean mask.
        
    Returns:
        Divergence array (units: 1/s if winds in m/s).
    """
    dudx = np.gradient(u, dx_km * 1000, axis=1)
    dvdy = np.gradient(v, dy_km * 1000, axis=0)
    
    divergence = dudx + dvdy
    
    if mask is not None:
        divergence = np.where(mask, divergence, np.nan)
    
    return divergence


__all__ = [
    "SpatialStatistics",
    "GridAnalyzer",
    "extract_subgrid",
    "compute_spatial_statistics",
    "compute_gradient_fields",
    "compute_laplacian",
    "compute_vorticity",
    "compute_divergence",
]
