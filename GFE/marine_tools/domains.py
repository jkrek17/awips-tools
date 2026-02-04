"""
Ocean domain definitions for grid-based marine analysis.

Provides explicit domain boundary definitions for the North Atlantic and
North Pacific basins, with proper handling of the International Date Line
crossing and spherical coordinate math.

The domains are defined as follows:
- North Atlantic: 30°N to 65°N, 85°W to 20°E (standard rectangular domain)
- North Pacific: 30°N to 65°N, 115°W to 120°E (crosses 180° meridian)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

# Earth radius in km for distance calculations
EARTH_RADIUS_KM = 6371.0

# Typical model grid resolutions (degrees)
GRID_RESOLUTIONS = {
    "coarse": 1.0,    # ~111 km
    "medium": 0.5,    # ~55 km
    "fine": 0.25,     # ~28 km
    "high": 0.125,    # ~14 km
}


@dataclass(frozen=True)
class OceanDomain:
    """
    Definition of an ocean analysis domain.
    
    Handles both standard rectangular domains and domains that cross the
    International Date Line (180° meridian). For dateline-crossing domains,
    west_lon > east_lon when expressed in standard -180 to 180 convention.
    
    Attributes:
        name: Human-readable domain name.
        south_lat: Southern boundary latitude (degrees, -90 to 90).
        north_lat: Northern boundary latitude (degrees, -90 to 90).
        west_lon: Western boundary longitude (degrees, -180 to 180).
        east_lon: Eastern boundary longitude (degrees, -180 to 180).
        crosses_dateline: True if domain spans the 180° meridian.
        description: Optional description of the domain.
        typical_storms: Expected number of concurrent storms (for sizing analysis).
        characteristic_length_km: Typical synoptic scale (km) for spatial filtering.
    """
    
    name: str
    south_lat: float
    north_lat: float
    west_lon: float
    east_lon: float
    crosses_dateline: bool = False
    description: str = ""
    typical_storms: int = 3
    characteristic_length_km: float = 500.0
    
    def __post_init__(self):
        """Validate domain boundaries."""
        if not -90 <= self.south_lat < self.north_lat <= 90:
            raise ValueError(
                f"Invalid latitude range: {self.south_lat} to {self.north_lat}"
            )
        if not -180 <= self.west_lon <= 180:
            raise ValueError(f"Invalid west longitude: {self.west_lon}")
        if not -180 <= self.east_lon <= 180:
            raise ValueError(f"Invalid east longitude: {self.east_lon}")
            
    @property
    def lat_extent(self) -> float:
        """Latitude extent in degrees."""
        return self.north_lat - self.south_lat
    
    @property
    def lon_extent(self) -> float:
        """Longitude extent in degrees (accounts for dateline crossing)."""
        if self.crosses_dateline:
            # Domain goes from west_lon eastward across dateline to east_lon
            return (180 - self.west_lon) + (self.east_lon + 180)
        return self.east_lon - self.west_lon
    
    @property
    def center_lat(self) -> float:
        """Center latitude of domain."""
        return (self.south_lat + self.north_lat) / 2
    
    @property
    def center_lon(self) -> float:
        """Center longitude of domain (handles dateline crossing)."""
        if self.crosses_dateline:
            # Compute center by going through 180
            half_extent = self.lon_extent / 2
            center = self.west_lon + half_extent
            if center > 180:
                center -= 360
            return center
        return (self.west_lon + self.east_lon) / 2
    
    def area_km2(self) -> float:
        """
        Approximate domain area in km².
        
        Uses spherical approximation accounting for latitude-dependent
        longitude scaling.
        """
        lat_rad = np.radians(self.center_lat)
        lat_km = self.lat_extent * (np.pi * EARTH_RADIUS_KM / 180)
        lon_km = self.lon_extent * (np.pi * EARTH_RADIUS_KM / 180) * np.cos(lat_rad)
        return lat_km * lon_km
    
    def contains_point(self, lat: float, lon: float) -> bool:
        """
        Check if a point is within the domain.
        
        Args:
            lat: Latitude in degrees.
            lon: Longitude in degrees (-180 to 180).
            
        Returns:
            True if point is within domain boundaries.
        """
        if not (self.south_lat <= lat <= self.north_lat):
            return False
            
        if self.crosses_dateline:
            # Point is in domain if lon >= west_lon OR lon <= east_lon
            return lon >= self.west_lon or lon <= self.east_lon
        else:
            return self.west_lon <= lon <= self.east_lon
    
    def normalize_longitude(self, lon: float) -> float:
        """
        Normalize longitude to the domain's reference frame.
        
        For dateline-crossing domains, converts to 0-360 representation
        centered on the domain.
        
        Args:
            lon: Input longitude (-180 to 180).
            
        Returns:
            Normalized longitude suitable for grid indexing.
        """
        if self.crosses_dateline:
            # Convert to 0-360 with domain starting at 0
            if lon < 0:
                lon += 360
            # Shift so west boundary is at 0
            lon_shifted = lon - self.west_lon
            if lon_shifted < 0:
                lon_shifted += 360
            return lon_shifted
        else:
            return lon - self.west_lon
    
    def denormalize_longitude(self, lon_norm: float) -> float:
        """
        Convert normalized longitude back to standard -180 to 180.
        
        Args:
            lon_norm: Normalized longitude (relative to domain).
            
        Returns:
            Standard longitude (-180 to 180).
        """
        if self.crosses_dateline:
            lon = lon_norm + self.west_lon
            if lon > 180:
                lon -= 360
            return lon
        else:
            return lon_norm + self.west_lon
    
    def create_grid_coordinates(
        self,
        resolution: Union[float, str] = "medium"
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generate 2D lat/lon coordinate arrays for the domain.
        
        Args:
            resolution: Grid spacing in degrees, or preset name
                        ('coarse', 'medium', 'fine', 'high').
                        
        Returns:
            Tuple of (lat_2d, lon_2d) numpy arrays with shape (nlat, nlon).
        """
        if isinstance(resolution, str):
            res = GRID_RESOLUTIONS.get(resolution, 0.5)
        else:
            res = resolution
            
        lats = np.arange(self.south_lat, self.north_lat + res/2, res)
        
        if self.crosses_dateline:
            # Generate longitudes going through dateline
            lons_west = np.arange(self.west_lon, 180 + res/2, res)
            lons_east = np.arange(-180, self.east_lon + res/2, res)
            lons = np.concatenate([lons_west, lons_east])
        else:
            lons = np.arange(self.west_lon, self.east_lon + res/2, res)
            
        lon_2d, lat_2d = np.meshgrid(lons, lats)
        return lat_2d, lon_2d
    
    def create_domain_mask(
        self,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray,
        include_boundary: bool = True
    ) -> np.ndarray:
        """
        Create a boolean mask for grid points within the domain.
        
        Args:
            lat_grid: 2D array of latitudes.
            lon_grid: 2D array of longitudes.
            include_boundary: Whether to include boundary points.
            
        Returns:
            Boolean mask array (True = point in domain).
        """
        lat_mask = (lat_grid >= self.south_lat) & (lat_grid <= self.north_lat)
        
        if self.crosses_dateline:
            lon_mask = (lon_grid >= self.west_lon) | (lon_grid <= self.east_lon)
        else:
            lon_mask = (lon_grid >= self.west_lon) & (lon_grid <= self.east_lon)
            
        return lat_mask & lon_mask
    
    def grid_dimensions(self, resolution: Union[float, str] = "medium") -> Tuple[int, int]:
        """
        Calculate grid dimensions for a given resolution.
        
        Args:
            resolution: Grid spacing in degrees or preset name.
            
        Returns:
            Tuple of (nlat, nlon).
        """
        if isinstance(resolution, str):
            res = GRID_RESOLUTIONS.get(resolution, 0.5)
        else:
            res = resolution
            
        nlat = int(np.ceil(self.lat_extent / res)) + 1
        nlon = int(np.ceil(self.lon_extent / res)) + 1
        return nlat, nlon
    
    def haversine_distance(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        """
        Calculate great-circle distance between two points.
        
        Args:
            lat1, lon1: First point coordinates (degrees).
            lat2, lon2: Second point coordinates (degrees).
            
        Returns:
            Distance in kilometers.
        """
        lat1_r, lon1_r = np.radians(lat1), np.radians(lon1)
        lat2_r, lon2_r = np.radians(lat2), np.radians(lon2)
        
        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r
        
        a = np.sin(dlat/2)**2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        
        return EARTH_RADIUS_KM * c
    
    def degrees_to_km(
        self,
        lat: float,
        delta_lat: float = 0.0,
        delta_lon: float = 0.0
    ) -> Tuple[float, float]:
        """
        Convert degree displacements to kilometers at given latitude.
        
        Args:
            lat: Reference latitude (degrees).
            delta_lat: Latitude displacement (degrees).
            delta_lon: Longitude displacement (degrees).
            
        Returns:
            Tuple of (dy_km, dx_km).
        """
        lat_rad = np.radians(lat)
        dy_km = delta_lat * (np.pi * EARTH_RADIUS_KM / 180)
        dx_km = delta_lon * (np.pi * EARTH_RADIUS_KM / 180) * np.cos(lat_rad)
        return dy_km, dx_km
    
    def km_to_degrees(
        self,
        lat: float,
        dy_km: float = 0.0,
        dx_km: float = 0.0
    ) -> Tuple[float, float]:
        """
        Convert kilometer displacements to degrees at given latitude.
        
        Args:
            lat: Reference latitude (degrees).
            dy_km: North-south displacement (km).
            dx_km: East-west displacement (km).
            
        Returns:
            Tuple of (delta_lat, delta_lon).
        """
        lat_rad = np.radians(lat)
        delta_lat = dy_km / (np.pi * EARTH_RADIUS_KM / 180)
        delta_lon = dx_km / (np.pi * EARTH_RADIUS_KM / 180 * np.cos(lat_rad))
        return delta_lat, delta_lon


# ===========================================================================
# Pre-defined ocean domains
# ===========================================================================

NORTH_ATLANTIC = OceanDomain(
    name="North Atlantic",
    south_lat=30.0,
    north_lat=65.0,
    west_lon=-85.0,
    east_lon=20.0,
    crosses_dateline=False,
    description="North Atlantic basin from US East Coast to European shelf",
    typical_storms=4,
    characteristic_length_km=500.0,
)

NORTH_PACIFIC = OceanDomain(
    name="North Pacific",
    south_lat=30.0,
    north_lat=65.0,
    west_lon=-115.0,  # 115°W = 245°E
    east_lon=120.0,   # 120°E
    crosses_dateline=True,
    description="North Pacific basin from US West Coast to East Asia (crosses dateline)",
    typical_storms=5,
    characteristic_length_km=600.0,
)

# Domain registry
_DOMAIN_REGISTRY: Dict[str, OceanDomain] = {
    "north_atlantic": NORTH_ATLANTIC,
    "natl": NORTH_ATLANTIC,
    "atlantic": NORTH_ATLANTIC,
    "north_pacific": NORTH_PACIFIC,
    "npac": NORTH_PACIFIC,
    "pacific": NORTH_PACIFIC,
}


def get_domain(name: str) -> OceanDomain:
    """
    Retrieve a domain by name.
    
    Args:
        name: Domain name or alias (case-insensitive).
        
    Returns:
        OceanDomain instance.
        
    Raises:
        KeyError: If domain name not recognized.
    """
    key = name.lower().replace(" ", "_").replace("-", "_")
    if key not in _DOMAIN_REGISTRY:
        available = ", ".join(sorted(set(_DOMAIN_REGISTRY.values().__iter__().__next__().name 
                                         for _ in range(1))))
        raise KeyError(f"Unknown domain '{name}'. Available: {list_domains()}")
    return _DOMAIN_REGISTRY[key]


def list_domains() -> List[str]:
    """Return list of available domain names."""
    return sorted(set(d.name for d in _DOMAIN_REGISTRY.values()))


def register_domain(domain: OceanDomain, *aliases: str) -> None:
    """
    Register a custom domain in the registry.
    
    Args:
        domain: OceanDomain instance to register.
        *aliases: Additional names to register the domain under.
    """
    key = domain.name.lower().replace(" ", "_").replace("-", "_")
    _DOMAIN_REGISTRY[key] = domain
    for alias in aliases:
        _DOMAIN_REGISTRY[alias.lower()] = domain


__all__ = [
    "OceanDomain",
    "NORTH_ATLANTIC",
    "NORTH_PACIFIC",
    "EARTH_RADIUS_KM",
    "GRID_RESOLUTIONS",
    "get_domain",
    "list_domains",
    "register_domain",
]
