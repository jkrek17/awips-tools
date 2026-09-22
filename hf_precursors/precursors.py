"""The literature's ingredients, computed for one low at one time.

Every quantity here traces to a published finding about explosive
cyclogenesis -- see INGREDIENTS.md for the citations and what each one is
supposed to mean. Nothing is included because it was easy.

    Sanders and Gyakum 1980       trough vector, jet-relative latitude,
                                  SST gradient
    Gyakum and Danielson 2000     upstream anticyclone, downstream cyclone,
                                  1000-500 thickness anomaly
    Hart 2003                     HVTL and HVTU, this package's own fields,
                                  here given a fair test beside named
                                  alternatives rather than beside nothing

ANOMALIES, NOT VALUES. Thickness and 500 hPa height are taken as departures
from their own zonal mean at the same latitude inside the domain, because
both vary by more across the basin's latitude range than any storm-to-storm
difference the study is looking for. Sanders and Gyakum's own SST result is
the same lesson from the other side: the gradient discriminated, the value
did not.

THE FRAME. Upstream and downstream are taken as the west and east sectors.
The North Pacific storm track is westerly through the cold season, so this
matches Gyakum and Danielson's composite frame closely enough; using each
storm's own motion instead would make the sectors depend on a track, and the
point of this module is to be computable wherever a low is found.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cyclone_phase_space" / "D2D"
                      / "derivedParameters" / "functions"))

import cps_HartCPS as hc  # noqa: E402
from pressure_field import Field, great_circle_km, offset_point  # noqa: E402

hc.ORIENTATION_MODE = 1        # ERA5 latitude runs north to south

SECTOR_INNER_KM = 750.0
SECTOR_OUTER_KM = 2000.0
UPSTREAM_BEARINGS = np.arange(240.0, 301.0, 10.0)    # west sector
DOWNSTREAM_BEARINGS = np.arange(60.0, 121.0, 10.0)   # east sector
SECTOR_RADII_KM = np.arange(SECTOR_INNER_KM, SECTOR_OUTER_KM + 1, 250.0)

TROUGH_SEARCH_KM = 2000.0
DOWNSTREAM_THICK_KM = 1500.0   # Gyakum and Danielson's own offset
SST_GRAD_RADIUS_KM = 500.0
CPS_RADIUS_KM = 500.0          # Hart's own analysis radius
SUBSET_LAT_DEG, SUBSET_LON_DEG = 22.0, 35.0


def _sector(field, clat, clon, bearings, reduce_fn):
    """Extreme value of `field` over a ring sector around the low."""
    vals = []
    for b in bearings:
        for r in SECTOR_RADII_KM:
            la, lo = offset_point(clat, clon, b, r)
            vals.append(float(field.sample(la, lo)))
    return reduce_fn(vals)


def sector_pressures(mslp, clat, clon):
    """Gyakum and Danielson's upstream anticyclone and downstream cyclone.

    Both are reported as differences from the low's own centre, so a deep
    low does not automatically come with a large-looking anticyclone.
    """
    p_c = float(mslp.sample(clat, clon))
    up = _sector(mslp, clat, clon, UPSTREAM_BEARINGS, max)
    down = _sector(mslp, clat, clon, DOWNSTREAM_BEARINGS, min)
    return dict(up_high_hpa=up, up_high_rel=up - p_c,
                down_low_hpa=down, down_low_rel=down - p_c)


def _zonal_anomaly(grid, lats, rows):
    """`grid` minus its own zonal mean at each latitude, over `rows`."""
    sub = grid[rows, :]
    return sub - np.nanmean(sub, axis=1, keepdims=True)


def thickness_anomaly(z1000, z500, lats, lons, clat, clon):
    """1000-500 hPa thickness anomaly at the low and 1500 km east of it.

    Gyakum and Danielson found the explosive sample about 40 m colder in the
    region of incipient cyclogenesis, and eastward by 1500 km, so both
    points are taken.
    """
    thick = z500 - z1000
    rows = np.arange(len(lats))
    anom = _zonal_anomaly(thick, lats, rows)
    f = Field(anom, lats, lons)
    e_lat, e_lon = offset_point(clat, clon, 90.0, DOWNSTREAM_THICK_KM)
    return dict(thick_anom_m=float(f.sample(clat, clon)),
                thick_anom_east_m=float(f.sample(e_lat, e_lon)),
                thick_m=float(Field(thick, lats, lons).sample(clat, clon)))


def trough_vector(z500, lats, lons, clat, clon):
    """Distance and bearing from the low to the 500 hPa trough.

    Sanders and Gyakum put the bomb about 740 km downstream of a mobile
    500 mb trough, so the search is over the upstream half and the answer is
    a vector. The trough is the minimum of the zonal height ANOMALY, not of
    height itself, which would simply find the pole-most point in the box.
    """
    rows = np.where(np.abs(lats - clat) <= SUBSET_LAT_DEG)[0]
    anom = _zonal_anomaly(z500, lats, rows)
    la = lats[rows][:, None] * np.ones((1, len(lons)))
    lo = lons[None, :] * np.ones((len(rows), 1))
    dist = great_circle_km(clat, clon, la, lo)
    dlon = ((lo - clon + 180.0) % 360.0) - 180.0
    inside = (dist <= TROUGH_SEARCH_KM) & (dist >= 200.0) & (dlon < 0.0)
    if not inside.any():
        return dict(trough_km=np.nan, trough_bearing=np.nan, trough_anom_m=np.nan)
    masked = np.where(inside, anom, np.inf)
    k = np.unravel_index(np.argmin(masked), masked.shape)
    tlat, tlon = float(la[k]), float(lo[k])
    brg = np.degrees(np.arctan2(
        (((tlon - clon + 180.0) % 360.0) - 180.0) * np.cos(np.radians(clat)),
        tlat - clat)) % 360.0
    return dict(trough_km=float(dist[k]), trough_bearing=brg,
                trough_anom_m=float(anom[k]))


def jet_relative(u, v, lats, lons, clat, clon, radius_km=2000.0):
    """The low's latitude relative to the wind maximum near it.

    Sanders and Gyakum put bombs within or poleward of the maximum
    westerlies, so what matters is the sign and size of the offset.
    """
    rows = np.where(np.abs(lats - clat) <= SUBSET_LAT_DEG)[0]
    spd = np.hypot(u[rows, :], v[rows, :])
    la = lats[rows][:, None] * np.ones((1, len(lons)))
    lo = lons[None, :] * np.ones((len(rows), 1))
    dist = great_circle_km(clat, clon, la, lo)
    inside = dist <= radius_km
    if not inside.any():
        return dict(jet_kt=np.nan, jet_dlat=np.nan)
    masked = np.where(inside, spd, -np.inf)
    k = np.unravel_index(np.argmax(masked), masked.shape)
    return dict(jet_kt=float(spd[k]) * 1.943844,
                jet_dlat=float(clat - la[k]))      # positive = low is poleward


def sst_gradient(sst, lats, lons, clat, clon):
    """Magnitude of the SST gradient near the low, in K per 100 km.

    Sanders and Gyakum: development occurs over a wide range of SSTs but
    preferentially near the strongest gradients, so the gradient is the
    ingredient and the value is not.
    """
    rows = np.where(np.abs(lats - clat) <= 12.0)[0]
    sub = sst[rows, :]
    dlat_m = abs(lats[1] - lats[0]) * 111320.0
    dlon_m = abs(lons[1] - lons[0]) * 111320.0 * np.cos(
        np.radians(lats[rows]))[:, None]
    gy, gx = np.gradient(sub)
    grad = np.hypot(gx / dlon_m, gy / dlat_m) * 1e5      # K per 100 km
    la = lats[rows][:, None] * np.ones((1, len(lons)))
    lo = lons[None, :] * np.ones((len(rows), 1))
    inside = great_circle_km(clat, clon, la, lo) <= SST_GRAD_RADIUS_KM
    vals = grad[inside & np.isfinite(grad)]
    centre = float(Field(sub, lats[rows], lons).sample(clat, clon))
    if vals.size == 0:
        return dict(sst_grad=np.nan, sst_c=centre - 273.15)
    return dict(sst_grad=float(np.nanmax(vals)), sst_c=centre - 273.15)


def cps_fields(z, lats, lons, clat, clon):
    """HVTL and HVTU at the low, from this package's own operational code.

    Run on a subset of the grid around the storm rather than globally: the
    sliding-window machinery costs seconds on a full field and milliseconds
    on a box, and the 500 km window only ever looks a few degrees out.
    """
    rows = np.where(np.abs(lats - clat) <= SUBSET_LAT_DEG)[0]
    dlon = ((lons - clon + 180.0) % 360.0) - 180.0
    cols = np.where(np.abs(dlon) <= SUBSET_LON_DEG)[0]
    if len(rows) < 40 or len(cols) < 40:
        return dict(hvtl=np.nan, hvtu=np.nan)
    sub = {p: z[p][np.ix_(rows, cols)] for p in z}
    la = lats[rows]
    lo = lons[cols]
    dy = np.full(sub[500].shape, 6371000.0 * np.radians(abs(la[1] - la[0])))
    dx = (6371000.0 * np.cos(np.radians(la))[:, None]
          * np.radians(abs(lo[1] - lo[0])) * np.ones((1, len(lo))))
    psfc = np.full(sub[500].shape, 1013.0)
    hvtl = hc.executeBand3(sub[925], sub[850], sub[700], psfc, dx, dy,
                           CPS_RADIUS_KM, 925.0, 850.0, 700.0)
    hvtu = hc.executeBand3(sub[500], sub[400], sub[300], psfc, dx, dy,
                           CPS_RADIUS_KM, 500.0, 400.0, 300.0)
    i = int(np.argmin(np.abs(la - clat)))
    j = int(np.argmin(np.abs(((lo - clon + 180.0) % 360.0) - 180.0)))
    return dict(hvtl=float(hvtl[i, j]), hvtu=float(hvtu[i, j]))
