"""Depth, scale and gradient of a surface low, measured from an MSLP field.

The compactness hypothesis says hurricane-force winds come from a TIGHT
pressure gradient rather than a deep centre, so the quantities that matter
are not central pressure but:

    depth   dP  = p_env - p_centre, with p_env the azimuthal mean at a large
                  radius. A 985 hPa low under a 1035 hPa ridge is a 50 hPa
                  depression; central pressure alone cannot tell the two
                  apart, which is why the archive could not test this.
    scale   L   = the e-folding radius of the pressure deficit.
    gradient    ~ dP / L, and the gradient wind that follows from it.

The low is described by its azimuthal-mean radial pressure profile, fitted
with a Gaussian deficit

    p(r) = p_c + dP * (1 - exp(-(r/L)^2))

which tends to p_c + dP far out, so the fit recovers the environmental
pressure rather than assuming it. L is found by scanning candidate radii and
solving dP linearly at each -- no optimizer, no starting guess, and the
residual curve is inspectable.

GRADIENT WIND, NOT GEOSTROPHIC. For a compact low the cyclonic curvature
correction is large and subgeostrophic: solving V^2/r + fV = (1/rho) dp/dr
gives meaningfully less wind than g/f * dZ/dr at a few hundred kilometres.
Reporting the geostrophic wind would overstate exactly the compact cases the
hypothesis is about, and would build the answer into the measurement.

DATELINE. The archive stores longitude as degrees east, negative west, so a
Pacific track runs ...178, -178... across the dateline. ERA5 is 0-360.
Every longitude here goes through `to_era5_lon`, and every separation
through `great_circle_km`, which differences longitudes modulo 360. The
repository has been caught by this before -- `tests/tcwind_jtwc` carries a
`synth_dateline_crossing` fixture for the same reason -- so the self-test at
the bottom of this module runs first and refuses to proceed if it fails.
"""
from __future__ import annotations

import numpy as np

EARTH_R_KM = 6371.0088
OMEGA = 7.2921e-5
RHO = 1.225           # kg/m3, near-surface density for the gradient wind
MS_TO_KT = 1.943844

ENV_RADIUS_KM = 1000.0        # where p_env is read
PROFILE_RADII_KM = np.arange(100.0, 1301.0, 100.0)
N_AZIMUTH = 36
SCALE_CANDIDATES_KM = np.arange(150.0, 1201.0, 10.0)


# ------------------------------------------------------------- geometry
def to_era5_lon(lon):
    """Archive longitude (deg east, negative west) -> ERA5 longitude (0-360)."""
    return np.asarray(lon) % 360.0


def great_circle_km(lat1, lon1, lat2, lon2):
    """Great-circle separation (km). Longitudes are differenced modulo 360,
    so a pair straddling the dateline is 2 degrees apart, not 358."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat = p2 - p1
    dlon = np.radians((np.asarray(lon2) - np.asarray(lon1) + 180.0) % 360.0 - 180.0)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 2.0 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def offset_point(clat, clon, bearing_deg, dist_km):
    """The point `dist_km` from (clat, clon) along `bearing_deg` from north."""
    d = dist_km / EARTH_R_KM
    b = np.radians(bearing_deg)
    p1, l1 = np.radians(clat), np.radians(clon)
    p2 = np.arcsin(np.sin(p1) * np.cos(d) + np.cos(p1) * np.sin(d) * np.cos(b))
    l2 = l1 + np.arctan2(np.sin(b) * np.sin(d) * np.cos(p1),
                         np.cos(d) - np.sin(p1) * np.sin(p2))
    return np.degrees(p2), np.degrees(l2) % 360.0


def coriolis(lat):
    return 2.0 * OMEGA * np.sin(np.radians(lat))


# ------------------------------------------------------------ sampling
class Field:
    """An ERA5 MSLP field (Pa or hPa) with bilinear sampling that wraps in
    longitude. ERA5 latitude runs north to south, which `_index` accounts
    for rather than assuming an ascending axis."""

    def __init__(self, values_hpa, lats, lons):
        self.v = np.asarray(values_hpa, dtype=float)
        self.lats = np.asarray(lats, dtype=float)
        self.lons = np.asarray(lons, dtype=float)
        self.dlat = float(abs(self.lats[1] - self.lats[0]))
        self.dlon = float(abs(self.lons[1] - self.lons[0]))
        self.descending = bool(self.lats[0] > self.lats[-1])

    def _index(self, lat, lon):
        y = ((self.lats[0] - lat) / self.dlat if self.descending
             else (lat - self.lats[0]) / self.dlat)
        x = ((np.asarray(lon) % 360.0) - self.lons[0] % 360.0) / self.dlon
        return y, x % self.v.shape[1]

    def sample(self, lat, lon):
        """Bilinear value at (lat, lon), wrapping in longitude."""
        y, x = self._index(np.asarray(lat, float), np.asarray(lon, float))
        y = np.clip(y, 0, self.v.shape[0] - 1.0001)
        y0 = np.floor(y).astype(int)
        x0 = np.floor(x).astype(int)
        fy, fx = y - y0, x - x0
        y1 = np.minimum(y0 + 1, self.v.shape[0] - 1)
        x1 = (x0 + 1) % self.v.shape[1]
        return ((1 - fy) * ((1 - fx) * self.v[y0, x0] + fx * self.v[y0, x1])
                + fy * ((1 - fx) * self.v[y1, x0] + fx * self.v[y1, x1]))

    def nearest_minimum(self, lat, lon, radius_km):
        """(lat, lon, value) of the lowest grid point within `radius_km`."""
        dlat_deg = radius_km / 111.32
        dlon_deg = radius_km / (111.32 * max(np.cos(np.radians(lat)), 0.15))
        lat_lo, lat_hi = lat - dlat_deg, lat + dlat_deg
        rows = np.where((self.lats >= lat_lo) & (self.lats <= lat_hi))[0]
        centre_col = int(round(((lon % 360.0) - self.lons[0] % 360.0) / self.dlon))
        half = int(np.ceil(dlon_deg / self.dlon))
        cols = (np.arange(centre_col - half, centre_col + half + 1)
                % self.v.shape[1])
        sub = self.v[np.ix_(rows, cols)]
        la = self.lats[rows][:, None] * np.ones((1, len(cols)))
        lo = self.lons[cols][None, :] * np.ones((len(rows), 1))
        within = great_circle_km(lat, lon, la, lo) <= radius_km
        if not within.any():
            return float(lat), float(lon), float(self.sample(lat, lon))
        masked = np.where(within, sub, np.inf)
        k = np.unravel_index(np.argmin(masked), masked.shape)
        return float(la[k]), float(lo[k]), float(sub[k])


# ------------------------------------------------------------- profile
def radial_profile(field, clat, clon, radii_km=PROFILE_RADII_KM, n_az=N_AZIMUTH):
    """Azimuthal-mean pressure at each radius."""
    bearings = np.arange(0.0, 360.0, 360.0 / n_az)
    out = np.empty(len(radii_km))
    for i, r in enumerate(radii_km):
        la, lo = offset_point(clat, clon, bearings, r)
        out[i] = float(np.mean(field.sample(la, lo)))
    return out


def fit_depth_scale(p_centre, radii_km, profile):
    """(dP, L, rms) for p(r) = p_c + dP*(1 - exp(-(r/L)^2)).

    L is scanned rather than optimized: for each candidate the shape is
    fixed, so dP follows from a one-line least squares, and the best pair is
    the one with the smallest residual. No starting guess to get wrong.
    """
    y = profile - p_centre
    best = (np.nan, np.nan, np.inf)
    for L in SCALE_CANDIDATES_KM:
        g = 1.0 - np.exp(-((radii_km / L) ** 2))
        denom = float(np.sum(g * g))
        if denom <= 0:
            continue
        dP = float(np.sum(y * g) / denom)
        rms = float(np.sqrt(np.mean((y - dP * g) ** 2)))
        if rms < best[2]:
            best = (dP, float(L), rms)
    return best


def gradient_wind_kt(dP_hpa, L_km, lat):
    """Peak gradient wind (kt) for a Gaussian deficit of depth `dP_hpa` and
    scale `L_km`.

    The deficit's steepest slope is at r = L/sqrt(2), where
    dp/dr = dP * sqrt(2/e) / L. Gradient balance V^2/r + fV = (1/rho) dp/dr
    then gives V; the curvature term is what keeps a very compact low from
    delivering its geostrophic wind.
    """
    if not np.isfinite(dP_hpa) or not np.isfinite(L_km) or dP_hpa <= 0:
        return np.nan
    L = L_km * 1000.0
    r = L / np.sqrt(2.0)
    dpdr = dP_hpa * 100.0 * np.sqrt(2.0 / np.e) / L      # Pa per m
    f = abs(coriolis(lat))
    disc = (f * r) ** 2 + 4.0 * r * dpdr / RHO
    if disc < 0:
        return np.nan
    return 0.5 * (-f * r + np.sqrt(disc)) * MS_TO_KT


def geostrophic_wind_kt(dP_hpa, L_km, lat):
    """The same peak slope read geostrophically -- for the comparison only."""
    if not np.isfinite(dP_hpa) or not np.isfinite(L_km) or dP_hpa <= 0:
        return np.nan
    L = L_km * 1000.0
    dpdr = dP_hpa * 100.0 * np.sqrt(2.0 / np.e) / L
    return dpdr / (RHO * abs(coriolis(lat))) * MS_TO_KT


def describe_low(field, lat, lon, refine_km=250.0):
    """Every scalar this study needs about one low, from one MSLP field."""
    clat, clon, p_c = field.nearest_minimum(lat, lon, refine_km)
    prof = radial_profile(field, clat, clon)
    dP, L, rms = fit_depth_scale(p_c, PROFILE_RADII_KM, prof)
    env = float(np.interp(ENV_RADIUS_KM, PROFILE_RADII_KM, prof))
    return dict(
        lat=clat, lon=clon, p_centre=p_c,
        p_env=env, depth=env - p_c,
        fit_depth=dP, scale_km=L, fit_rms=rms,
        grad_hpa_per_100km=(dP / L * 100.0) if np.isfinite(L) else np.nan,
        vg_kt=gradient_wind_kt(dP, L, clat),
        vgeo_kt=geostrophic_wind_kt(dP, L, clat),
        shift_km=great_circle_km(lat, lon, clat, clon),
    )


# ------------------------------------------------------------ self-test
def _self_test():
    """Dateline and geometry. Run before anything else uses this module."""
    d = great_circle_km(36.0, 178.0, 36.0, -178.0)
    assert 300.0 < d < 400.0, f"dateline separation wrong: {d:.0f} km"
    d2 = great_circle_km(36.0, 178.0, 36.0, 182.0)
    assert abs(d - d2) < 1e-6, "0-360 and signed longitudes disagree"
    assert abs(to_era5_lon(-178.0) - 182.0) < 1e-9
    assert abs(to_era5_lon(178.0) - 178.0) < 1e-9

    la, lo = offset_point(36.0, 179.5, 90.0, 200.0)
    assert lo > 180.0 or lo < 10.0, f"eastward step did not cross: {lo}"
    assert great_circle_km(36.0, 179.5, la, lo) == 200.0 or \
        abs(great_circle_km(36.0, 179.5, la, lo) - 200.0) < 1.0

    # A synthetic Gaussian low straddling the dateline must be recovered with
    # the depth and scale it was built with, from either longitude convention.
    lats = np.arange(70.0, 19.9, -0.25)
    lons = np.arange(0.0, 360.0, 0.25)
    lo2d, la2d = np.meshgrid(lons, lats)
    for clon_true in (180.0, 179.0, 181.0):
        r = great_circle_km(45.0, clon_true, la2d, lo2d)
        p = 1010.0 - 40.0 * np.exp(-((r / 400.0) ** 2))
        f = Field(p, lats, lons)
        got = describe_low(f, 45.0, clon_true)
        assert abs(got["fit_depth"] - 40.0) < 1.5, got
        assert abs(got["scale_km"] - 400.0) < 25.0, got
        assert got["shift_km"] < 40.0, got
    print("pressure_field self-test: dateline, geometry and Gaussian recovery OK")


if __name__ == "__main__":
    _self_test()
