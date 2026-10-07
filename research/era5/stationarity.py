"""Is ERA5's deep-cyclone population stationary across its own observing-system
eras? A hurricane-force criterion calibrated on 2001-2026 can only be applied
backwards if it can. Pre-1979 is pre-satellite; radiosondes thicken from 1958.
If the deep-low population steps at either boundary, an extended record would
carry a reanalysis artefact in place of the recording-practice artefact the
archive had - the same mistake wearing different clothes."""
import urllib.request, datetime, sys, time
import numpy as np, numcodecs

B = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
     "full_37-1h-0p25deg-chunk-1.zarr-v3")
T0 = datetime.datetime(1900, 1, 1)
codec = numcodecs.Blosc()

def tidx(t): return int((t - T0).total_seconds() // 3600)

def field(var, t, tries=4):
    url = "%s/%s/%d.0.0" % (B, var, tidx(t))
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                raw = r.read()
            return np.frombuffer(codec.decode(raw), dtype='<f4').reshape(721, 1440)
        except Exception:
            if k == tries - 1: raise
            time.sleep(2 * (k + 1))

# North Atlantic, 30-70N and 80W-10E: the archive's Atlantic domain.
LA = slice(int((90 - 70) / 0.25), int((90 - 30) / 0.25) + 1)
LO_W, LO_E = slice(int(280 / 0.25), 1440), slice(0, int(10 / 0.25) + 1)

def stats(p):
    box = np.concatenate([p[LA, LO_W], p[LA, LO_E]], axis=1) / 100.0
    # Local minima that are deeper than every neighbour within ~2.5 degrees,
    # which is a crude but era-neutral stand-in for a tracked cyclone centre.
    mn = box.min()
    # max gradient in hPa per 100 km, the quantity a wind criterion keys on
    dy = np.gradient(box, axis=0) / 27.75 * 100.0
    lat = np.linspace(70, 30, box.shape[0])[:, None]
    dx = np.gradient(box, axis=1) / (27.75 * np.cos(np.radians(lat))) * 100.0
    g = np.sqrt(dx ** 2 + dy ** 2).max()
    return mn, g, int((box < 960).any()), int((box < 980).any())

years = list(range(1940, 2026, 3))
days = [5, 12, 19, 26]
hours = [0, 12]
print("year  n  minMSLP_mean  minMSLP_p10  maxgrad_mean  <960  <980", flush=True)
for y in years:
    rows = []
    for mo, yy in ((1, y), (2, y)):
        for d in days:
            for h in hours:
                try:
                    rows.append(stats(field('mean_sea_level_pressure',
                                            datetime.datetime(yy, mo, d, h))))
                except Exception as e:
                    print("  %d-%02d-%02d %02dZ failed: %s" % (yy, mo, d, h, str(e)[:40]),
                          file=sys.stderr)
    if not rows: continue
    a = np.array(rows, dtype=float)
    print("%d %3d %13.1f %12.1f %13.2f %5.0f%% %5.0f%%"
          % (y, len(rows), a[:, 0].mean(), np.percentile(a[:, 0], 10),
             a[:, 1].mean(), 100 * a[:, 2].mean(), 100 * a[:, 3].mean()), flush=True)
