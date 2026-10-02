# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# TCPressure.py
#
# Puts a tropical cyclone into a pmsl field where the warning says it is, as
# strong as the warning says it is - so the isobars match the TCM instead of
# wherever the model happened to put the storm.
#
# Two steps, both purely in lat/lon space so the same storm lands identically
# on a GFE grid and on the model field filling the strip south of it:
#
#   1. REMOVE the background's own vortex.  Its center is found near the
#      warning position, and the symmetric part of its pressure anomaly is
#      taken out, leaving the environment - the subtropical ridge, a trough -
#      in place.
#
#   2. IMPLANT the warning's vortex at the warning position.  Its pressure
#      profile comes from the SAME symmetric wind profile TCWind_JTWC fits to
#      the warning's wind radii (modified Rankine, GTCM Users Guide eq. 3),
#      through gradient-wind balance:
#
#          dp/dr = rho * (vg^2 / r + f * vg),   vg = surface wind / SFC_TO_GRADIENT
#
#      integrated in from the storm's outer radius.  So the pmsl vortex and
#      TCWind_JTWC's Wind grids agree by construction.
#
# Intensity: a warning carries a central pressure only for its initial time,
# and winds for every forecast time.  The gradient-wind integral turns the
# forecast winds into pressure, and one scale factor per storm, fixed at tau 0
# so that its central pressure equals the bulletin's, carries the conversion
# through every forecast hour.  No bulletin pressure: the scale is 1.
#
# The anchor is measured from the LOCAL environment - the background under
# the warning position once the model's vortex is out - not a fixed value.
# Against six real warnings, a fixed 1010 mb environment put the unanchored
# vortex 15-20 mb too deep for 100-105 kt hurricanes and 6-7 mb too shallow
# for 35 kt tropical storms sitting in a ~1004 mb monsoon trough; the local
# environment is what removes the second error, and the anchor the first.
#
# Storms are plain dicts, so nothing here depends on TCWind_JTWC's classes:
#
#     {"lat", "lon", "vmax" (kt), "a" (asymmetry kt), "rm", "ri" (nm),
#      "x1", "x2", "r34" (mean 34 kt radius nm, or None), "name"}
#
# stormFromSnapshot() builds one from a TCWind_JTWC Snapshot.
# ----------------------------------------------------------------------------

import numpy as np


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Surface wind over the ocean as a fraction of the gradient-level wind that
# balances the pressure field.
SFC_TO_GRADIENT = 0.85

# Boundary-layer air density, kg m-3.
AIR_DENSITY = 1.15

# Environmental pressure the tau-0 anchor falls back on when no background
# is at hand to measure the local one, mb.
P_ENV_REF_MB = 1010.0

# The anchor scale is clipped to this range: outside it, something is wrong
# with the bulletin or the fit, and an unscaled vortex is the safer error.
ANCHOR_LIMITS = (0.5, 2.0)

# The implanted vortex reaches out to R_OUT: R34_TO_R_OUT times the mean
# 34 kt radius, clamped between these, and its winds taper smoothly to zero
# from TAPER_FROM of the way out, so the isobars have no kink at its edge.
R34_TO_R_OUT = 2.5
R_OUT_LIMITS_NM = (240.0, 600.0)
TAPER_FROM = 0.6

# The background's own vortex is looked for within SEARCH_RADIUS_NM of the
# warning position, must be at least MIN_BACKGROUND_DEPTH_MB deep against its
# surroundings to count, and is removed out to REMOVE_RADIUS_NM.
SEARCH_RADIUS_NM = 360.0
REMOVE_RADIUS_NM = 360.0
MIN_BACKGROUND_DEPTH_MB = 2.0

# Ring width for the background vortex's azimuthal mean, nm - never
# narrower than RING_PER_SPACING grid spacings.  Each ring is averaged over
# RING_SECTORS azimuth sectors weighted equally, so a ring whose points fall
# unevenly around the circle does not pick up the environment's slope: on a
# sloping background, that bias is what leaves ripples - and jagged isobars
# wherever the gradient is slack.  The removed anomaly tapers to nothing over
# the outer part of the removal radius, from REMOVE_TAPER_FROM of the way out.
RING_NM = 10.0
RING_PER_SPACING = 1.5
RING_SECTORS = 8
REMOVE_TAPER_FROM = 0.85

NM_TO_M = 1852.0
KT_TO_MS = 0.514444
OMEGA = 7.2921e-5
EARTH_RADIUS_NM = 3440.065


# ---------------------------------------------------------------------------
# Storms
# ---------------------------------------------------------------------------

def stormFromSnapshot(snapshot, name=None):
    """A storm dict from a TCWind_JTWC Snapshot (or Tau) and its GTCM fit."""
    fit = snapshot.fit
    r34 = None
    quad = getattr(snapshot, "radii", {}).get(34)
    if quad:
        vals = [v for v in quad.values() if v and v > 0.0]
        if vals:
            r34 = float(np.mean(vals))
    return {"lat": float(snapshot.lat), "lon": float(snapshot.lon),
            "vmax": float(snapshot.vmax), "a": float(fit.get("a", 0.0)),
            "rm": float(fit["rm"]), "ri": float(fit["ri"]),
            "x1": float(fit["x1"]), "x2": float(fit["x2"]),
            "r34": r34, "name": name}


def symmetricWind(r_nm, storm):
    """Symmetric surface tangential wind, kt.

    The modified Rankine profile TCWind_JTWC fits to the warning's radii
    (_gtcmProfile there, GTCM Users Guide eq. 3), repeated here so this
    module needs nothing from the procedure.
    """
    vs = max(float(storm["vmax"]) - float(storm.get("a", 0.0)), 0.0)
    rm = max(float(storm["rm"]), 1e-3)
    ri = max(float(storm["ri"]), rm * 1.0001)
    x1, x2 = float(storm["x1"]), float(storm["x2"])
    r = np.maximum(np.asarray(r_nm, dtype=float), 1e-6)
    A = (rm / ri) ** (x1 - x2)
    return np.where(r < rm, vs * (r / rm),
                    np.where(r < ri, vs * (rm / r) ** x1,
                             A * vs * (rm / r) ** x2))


def outerRadius(storm):
    """How far out the implanted vortex reaches, nm."""
    r34 = storm.get("r34")
    if r34 and r34 > 0.0:
        rOut = R34_TO_R_OUT * float(r34)
    else:
        rOut = 8.0 * float(storm["ri"])
    return float(np.clip(rOut, R_OUT_LIMITS_NM[0], R_OUT_LIMITS_NM[1]))


def pressureDeficit(storm, step_nm=0.5):
    """The storm's pressure deficit against its surroundings, by radius.

    Returns (r_nm, deficit_mb): zero at the outer radius, largest at the
    center, unscaled.  Gradient-wind balance on the symmetric profile, with
    the winds tapered to zero over the outer part so pressure meets the
    surroundings without a kink.
    """
    rOut = outerRadius(storm)
    r = np.arange(step_nm, rOut + step_nm / 2.0, step_nm)
    vg = symmetricWind(r, storm) / SFC_TO_GRADIENT * KT_TO_MS

    rTaper = TAPER_FROM * rOut
    t = np.clip((r - rTaper) / (rOut - rTaper), 0.0, 1.0)
    vg = vg * np.cos(0.5 * np.pi * t) ** 2

    f = 2.0 * OMEGA * np.sin(np.radians(abs(float(storm["lat"]))))
    rm = r * NM_TO_M
    dpdr = AIR_DENSITY * (vg ** 2 / rm + f * vg)            # Pa per m

    # Integrate from the outside in: deficit(r) = integral r..rOut.
    seg = 0.5 * (dpdr[1:] + dpdr[:-1]) * np.diff(rm)
    deficit = np.concatenate([np.cumsum(seg[::-1])[::-1], [0.0]]) / 100.0
    return np.concatenate([[0.0], r]), np.concatenate([[deficit[0]], deficit])


def anchorScale(tau0Storm, bulletinPressureMb, pEnv=None):
    """Scale that makes the tau-0 central pressure equal the bulletin's,
    measured from environmental pressure ``pEnv``.

    Returns (scale, note).  No bulletin pressure, or a scale outside
    ANCHOR_LIMITS, gives 1.0 and says why.
    """
    if pEnv is None:
        pEnv = P_ENV_REF_MB
    if not bulletinPressureMb:
        return 1.0, "no bulletin pressure - unanchored"
    _, deficit = pressureDeficit(tau0Storm)
    if deficit[0] <= 0.0:
        return 1.0, "no deficit at tau 0 - unanchored"
    scale = (float(pEnv) - float(bulletinPressureMb)) / deficit[0]
    lo, hi = ANCHOR_LIMITS
    if not lo <= scale <= hi:
        return 1.0, ("anchor %.2f outside %.1f-%.1f - unanchored"
                     % (scale, lo, hi))
    return float(scale), "anchored to %d mb" % int(bulletinPressureMb)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def distanceNm(lat, lon, clat, clon):
    """Great-circle distance in nm - fine across the dateline."""
    lat1 = np.radians(np.asarray(lat, dtype=float))
    lat2 = np.radians(float(clat))
    dlat = lat1 - lat2
    dlon = np.radians(np.asarray(lon, dtype=float) - float(clon))
    h = (np.sin(dlat / 2.0) ** 2 +
         np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2)
    return 2.0 * EARTH_RADIUS_NM * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))


def _box3(grid):
    p = np.pad(np.asarray(grid, dtype=float), 1, mode="edge")
    return (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] + p[1:-1, :-2] +
            p[1:-1, 1:-1] + p[1:-1, 2:] + p[2:, :-2] + p[2:, 1:-1] +
            p[2:, 2:]) / 9.0


def gridSpacingNm(lat, lon):
    """Typical distance between neighboring grid points, nm."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    ny, nx = lat.shape
    i, j = ny // 2, nx // 2
    steps = []
    if nx > 1:
        steps.append(distanceNm(lat[i, j], lon[i, j], lat[i, j + 1],
                                lon[i, j + 1]))
    if ny > 1:
        steps.append(distanceNm(lat[i, j], lon[i, j], lat[i + 1, j],
                                lon[i + 1, j]))
    return float(max(steps)) if steps else RING_NM


def pchip(x, xp, fp):
    """Monotone cubic (Fritsch-Carlson) interpolation, numpy only.

    Straight lines between ring means leave a ripple at the ring spacing on
    any curved profile - error zero at each ring and largest between them -
    and that ripple is what makes isobars jagged.  A monotone cubic follows
    the curve without overshooting, so it cannot invent a wiggle either.
    """
    x = np.asarray(x, dtype=float)
    xp = np.asarray(xp, dtype=float)
    fp = np.asarray(fp, dtype=float)
    n = len(xp)
    if n < 3:
        return np.interp(x, xp, fp)
    h = np.diff(xp)
    delta = np.diff(fp) / h
    m = np.zeros(n)
    for k in range(1, n - 1):
        if delta[k - 1] * delta[k] > 0.0:
            w1 = 2.0 * h[k] + h[k - 1]
            w2 = h[k] + 2.0 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])
    m[0], m[-1] = delta[0], delta[-1]
    xc = np.clip(x, xp[0], xp[-1])
    k = np.clip(np.searchsorted(xp, xc) - 1, 0, n - 2)
    t = (xc - xp[k]) / h[k]
    h00 = (1 + 2 * t) * (1 - t) ** 2
    h10 = t * (1 - t) ** 2
    h01 = t ** 2 * (3 - 2 * t)
    h11 = t ** 2 * (t - 1)
    return (h00 * fp[k] + h10 * h[k] * m[k] + h01 * fp[k + 1] +
            h11 * h[k] * m[k + 1])


def bearingDeg(lat, lon, clat, clon):
    """Bearing from (clat, clon) to each point, degrees - local plane, which
    is all sectoring a ring needs."""
    dlon = ((np.asarray(lon, dtype=float) - float(clon) + 180.0) % 360.0
            - 180.0) * np.cos(np.radians(float(clat)))
    dlat = np.asarray(lat, dtype=float) - float(clat)
    return np.degrees(np.arctan2(dlon, dlat)) % 360.0


def ringMeans(field, dist, rMax, ring=None, bearing=None, sectors=None):
    """Azimuthal mean of ``field`` in rings out to rMax, by ring center.

    With ``bearing`` given, each ring is the equal-weight mean of its
    ``sectors`` azimuth sectors, so uneven sampling round the ring cannot
    bias it toward one side of a sloping environment.
    """
    if ring is None:
        ring = RING_NM
    if sectors is None:
        sectors = RING_SECTORS
    edges = np.arange(0.0, rMax + ring, ring)
    radii = np.full(len(edges) - 1, np.nan)
    means = np.full(len(edges) - 1, np.nan)
    d = np.asarray(dist, dtype=float).ravel()
    idx = np.digitize(d, edges) - 1
    vals = np.asarray(field, dtype=float).ravel()
    sec = None
    if bearing is not None:
        sec = (np.asarray(bearing, dtype=float).ravel() /
               (360.0 / sectors)).astype(int) % sectors
    for k in range(len(means)):
        sel = (idx == k) & np.isfinite(vals)
        if not sel.any():
            continue
        if sec is None:
            means[k] = vals[sel].mean()
            radii[k] = d[sel].mean()
            continue
        groups = [sel & (sec == q) for q in range(sectors)]
        groups = [g for g in groups if g.any()]
        means[k] = float(np.mean([vals[g].mean() for g in groups]))
        radii[k] = float(np.mean([d[g].mean() for g in groups]))
    # Each ring is credited to where its points actually are, not to the
    # middle of the ring: on a peaked profile the difference is a bias.
    return radii, means


# ---------------------------------------------------------------------------
# Remove and implant
# ---------------------------------------------------------------------------

def findBackgroundCenter(pmsl, lat, lon, clat, clon, radius=None,
                         taken=()):
    """The background's own vortex near a warning position.

    Returns (i, j, depthMb) for the lowest lightly-smoothed pmsl within
    ``radius`` of (clat, clon), or None when there is no low there at least
    MIN_BACKGROUND_DEPTH_MB deep, or the low sits on the field's edge - a
    partial vortex that cannot be removed cleanly.  ``taken`` holds centers
    already claimed by another storm.
    """
    if radius is None:
        radius = SEARCH_RADIUS_NM
    smooth = _box3(pmsl)
    near = distanceNm(lat, lon, clat, clon) <= radius
    for i, j in taken:
        near[max(0, i - 2):i + 3, max(0, j - 2):j + 3] = False
    if not near.any():
        return None
    masked = np.where(near, smooth, np.inf)
    i, j = np.unravel_index(np.argmin(masked), masked.shape)
    ny, nx = pmsl.shape
    if i in (0, ny - 1) or j in (0, nx - 1):
        return None

    dist = distanceNm(lat, lon, lat[i, j], lon[i, j])
    outer = (dist > REMOVE_RADIUS_NM - 2 * RING_NM) & \
        (dist <= REMOVE_RADIUS_NM)
    if not outer.any():
        return None
    depth = float(np.mean(pmsl[outer]) - smooth[i, j])
    if depth < MIN_BACKGROUND_DEPTH_MB:
        return None
    return int(i), int(j), depth


def removeVortex(pmsl, lat, lon, ci, cj):
    """Take the symmetric part of a low's anomaly out of ``pmsl``.

    The anomaly is the azimuthal-mean pmsl around the low minus its value at
    REMOVE_RADIUS_NM, kept only where negative, so the environment around it
    - and any asymmetry in it - is left as it was.
    """
    dist = distanceNm(lat, lon, lat[ci, cj], lon[ci, cj])
    ring = max(RING_NM, RING_PER_SPACING * gridSpacingNm(lat, lon))
    bearing = bearingDeg(lat, lon, lat[ci, cj], lon[ci, cj])
    centers, means = ringMeans(pmsl, dist, REMOVE_RADIUS_NM, ring, bearing)
    good = np.isfinite(means)
    if good.sum() < 3:
        return np.array(pmsl, dtype=float)
    centers, means = centers[good], means[good]
    envValue = means[-1]

    r = np.concatenate([[0.0], centers, [REMOVE_RADIUS_NM]])
    anomaly = np.concatenate([[float(pmsl[ci, cj]) - envValue],
                              means - envValue, [0.0]])
    anomaly = np.minimum(anomaly, 0.0)
    taperFrom = REMOVE_TAPER_FROM * REMOVE_RADIUS_NM
    t = np.clip((r - taperFrom) / (REMOVE_RADIUS_NM - taperFrom), 0.0, 1.0)
    anomaly = anomaly * np.cos(0.5 * np.pi * t) ** 2

    out = np.array(pmsl, dtype=float)
    inside = dist <= REMOVE_RADIUS_NM
    out[inside] -= pchip(dist[inside], r, anomaly)
    return out


def implantVortex(pmsl, lat, lon, storm, scale=1.0):
    """Add the warning's vortex at the warning position."""
    r, deficit = pressureDeficit(storm)
    dist = distanceNm(lat, lon, storm["lat"], storm["lon"])
    out = np.array(pmsl, dtype=float)
    inside = dist <= r[-1]
    out[inside] -= float(scale) * np.interp(dist[inside], r, deficit)
    return out


def relocateStorms(pmsl, lat, lon, storms):
    """Move every storm in ``storms`` to its warning position and strength.

    A storm may carry ``"anchor": (tau0Storm, bulletinPressureMb)``; its scale
    is then fixed against the background under its warning position once the
    model's vortex is out, so at tau 0 the central pressure is the
    bulletin's.  Returns (new pmsl, report): one dict per storm with where
    the background had it, how far off that was, what was removed, the
    environment, the anchor, and the central pressure implanted.  Background
    lows are matched one per storm, so two nearby storms never share one.
    """
    out = np.array(pmsl, dtype=float)
    report, taken = [], []
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)

    # Find every storm's background low before changing anything, so one
    # storm's implant is never mistaken for another's background.
    found = []
    for storm in storms:
        hit = findBackgroundCenter(out, lat, lon, storm["lat"], storm["lon"],
                                   taken=taken)
        if hit is not None:
            taken.append(hit[:2])
        found.append(hit)

    for storm, hit in zip(storms, found):
        entry = {"name": storm.get("name"), "lat": storm["lat"],
                 "lon": storm["lon"], "background": None, "offsetNm": None,
                 "removedMb": 0.0}
        if hit is not None:
            i, j, depth = hit
            entry["background"] = (float(lat[i, j]), float(lon[i, j]))
            entry["offsetNm"] = float(distanceNm(lat[i, j], lon[i, j],
                                                 storm["lat"], storm["lon"]))
            entry["removedMb"] = depth
            out = removeVortex(out, lat, lon, i, j)
        report.append(entry)

    for storm, entry in zip(storms, report):
        dist = distanceNm(lat, lon, storm["lat"], storm["lon"])
        k = np.unravel_index(np.argmin(dist), dist.shape)
        env = float(out[k])
        scale, note = 1.0, "no bulletin pressure - unanchored"
        if storm.get("anchor"):
            tau0Storm, bulletinMb = storm["anchor"]
            scale, note = anchorScale(tau0Storm, bulletinMb, pEnv=env)

        out = implantVortex(out, lat, lon, storm, scale)
        _, deficit = pressureDeficit(storm)
        entry["envMb"] = env
        entry["scale"] = scale
        entry["anchorNote"] = note
        entry["deficitMb"] = scale * float(deficit[0])
        entry["centralMb"] = float(out[k])
        entry["onField"] = bool(dist[k] <= 60.0)
    return out, report
