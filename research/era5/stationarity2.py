"""Is ERA5's hurricane-force-capable population stationary across its own
observing-system eras? The proper version of stationarity.py.

The first pass sampled 16 fields a year from two months and measured a
basin-wide MAXIMUM, which is an extreme-value statistic whose between-year
scatter (sd 2.20) was larger than the era difference it was being used to
detect (2.10). It flagged pressure gradient as ~11% stronger before 1979 at
t = -2.8, but could not settle it.

Three changes make this one decisive:

  - every year 1940-2026 rather than every third;
  - September through May rather than January and February, so the sample is
    the season the archive actually covers;
  - EXCEEDANCE COUNTS rather than maxima. The number of grid cells over a
    threshold is a far more stable statistic than the single largest value in
    the basin, and it is also closer to what a criterion would key on - an
    HF-equivalent event is an area of hurricane-force gust, not a point.

It also reads the gust field itself, `instantaneous_10m_wind_gust`, instead of
the pressure-gradient proxy. That is the variable a criterion would use: the
pilot found 10 m sustained wind unusable (0 of 103 archive events reach 64 kt
in ERA5, because 0.25 degrees does not resolve the wind maximum) while gusts
have a median of 73 kt with 85% at or above 64 kt.

Both basins come free: the chunks are global, so the Pacific box costs no extra
download. Rows print as each year finishes, so a partial run is still usable.

What the answer decides: the start year for any backward extension of the
record. If the exceedance counts step at 1979 the criterion can only be trusted
in the satellite era (47 seasons); if they are stationary from 1958, the
radiosonde buildout (68 seasons); if clean to 1940, 86.
"""
import datetime
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numcodecs
import numpy as np

B = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
     "full_37-1h-0p25deg-chunk-1.zarr-v3")
T0 = datetime.datetime(1900, 1, 1)
CODEC = numcodecs.Blosc()
BYTES = [0]

# 64 kt and 50 kt in m/s: the archive's hurricane-force and storm-force marks.
HF_MS = 64 * 0.514444
SF_MS = 50 * 0.514444


def tidx(t):
    return int((t - T0).total_seconds() // 3600)


def field(var, t, tries=4):
    url = "%s/%s/%d.0.0" % (B, var, tidx(t))
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=150) as r:
                raw = r.read()
            BYTES[0] += len(raw)
            return np.frombuffer(CODEC.decode(raw), dtype="<f4").reshape(721, 1440)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


def rows(lat_n, lat_s):
    return slice(int((90 - lat_n) / 0.25), int((90 - lat_s) / 0.25) + 1)


def cut(a, lat_n, lat_s, lon_spans):
    """Longitude spans are given in degrees east and may wrap the meridian."""
    r = rows(lat_n, lat_s)
    return np.concatenate(
        [a[r, int(w / 0.25):int(e / 0.25) + 1] for w, e in lon_spans], axis=1)


BASINS = {
    "atl": dict(lat=(70, 30), lon=[(280, 359.75), (0, 10)]),
    "pac": dict(lat=(67, 30), lon=[(160, 240)]),
}


def sample_days(season_start_year):
    """September of one year through May of the next, every 11th day at 12Z.

    11 days is deliberately not a divisor of 30: it walks the phase of the
    month across the season instead of always landing on the same dates.
    """
    out = []
    d = datetime.date(season_start_year, 9, 1)
    end = datetime.date(season_start_year + 1, 5, 31)
    while d <= end:
        out.append(datetime.datetime(d.year, d.month, d.day, 12))
        d += datetime.timedelta(days=11)
    return out


def stats(p_hpa, gust, spec):
    p = cut(p_hpa, spec["lat"][0], spec["lat"][1], spec["lon"]) / 100.0
    g = cut(gust, spec["lat"][0], spec["lat"][1], spec["lon"])
    cells = p.size
    return dict(
        # per million cells, so the two basins are comparable despite area
        hf=1e6 * float((g >= HF_MS).sum()) / cells,
        sf=1e6 * float((g >= SF_MS).sum()) / cells,
        p980=1e6 * float((p < 980).sum()) / cells,
        p960=1e6 * float((p < 960).sum()) / cells,
        minp=float(p.min()),
        maxg=float(g.max()),
    )


def one_day(t):
    """Both fields for one time step, reduced to per-basin statistics.

    The reduction happens here rather than in the caller so that only the small
    summary crosses back from the worker and the 4 MB arrays are freed at once;
    a season held whole would be 200 MB in flight for no benefit.
    """
    p = field("mean_sea_level_pressure", t)
    g = field("instantaneous_10m_wind_gust", t)
    return {b: stats(p, g, spec) for b, spec in BASINS.items()}


def _safe_day(t):
    """A single failed time step is a gap in the sample, not a dead run: 86
    seasons must not be lost to one chunk the store would not serve."""
    try:
        return one_day(t)
    except Exception:
        return None


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 1940
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    keys = ["hf", "sf", "p980", "p960", "minp", "maxg"]
    print("# gust/pressure exceedance per million grid cells, Sep-May, 12Z every 11 days")
    print("# hf = gust >= 64 kt, sf = >= 50 kt, p980/p960 = MSLP below that")
    print("season basin n " + " ".join(keys), flush=True)
    # A cloud-optimised store is meant to be read in parallel; six concurrent
    # chunk reads turn a seven-hour serial walk into about an hour, and six is
    # well inside what a public object store expects of one client.
    pool = ThreadPoolExecutor(max_workers=6)
    for y in range(y0, y1 + 1):
        acc = {b: [] for b in BASINS}
        days = sample_days(y)
        for t, res in zip(days, pool.map(_safe_day, days)):
            if res is None:
                print("# %s failed" % t.date(), file=sys.stderr)
                continue
            for b in BASINS:
                acc[b].append(res[b])
        for b in BASINS:
            v = acc[b]
            if not v:
                continue
            print("%d %s %d %s" % (
                y, b, len(v),
                " ".join("%.3f" % (sum(r[k] for r in v) / len(v)) for k in keys)),
                flush=True)
        print("# %d done, %.1f GB so far" % (y, BYTES[0] / 1e9), file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
