"""URL builders for the AWS open-data mirrors. ymd 'YYYYMMDD', hh '00', fh/step int."""

GFS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
GEFS = "https://noaa-gefs-pds.s3.amazonaws.com"
EC = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
AIGFS = "https://noaa-nws-graphcastgfs-pds.s3.amazonaws.com"
# AI-GFS (NOAA's GraphCast-based deterministic model) is one model under three bucket layouts. The
# live `graphcastgfs.*` stream before 2025-12-19 is an older model and must not be used, so earlier
# cycles come from NOAA's hindcast of the current model (`hindcast_aigfsdev2.5`, 2025-01-01 .. 2026-02-28).
# The operational `aigfs.*` feed starts 2026-04-16. Compared by cycle date (YYYYMMDD string).
AIGFS_LIVE_FROM = "20251219"        # first cycle date of the graphcastgfs.* stream that is the current model
AIGFS_OPER_FROM = "20260416"        # first cycle date of the aigfs.* feed
GEFS_MEMBERS = ["c00"] + ["p%02d" % i for i in range(1, 31)]


def gfs(ymd, hh, fh):
    return "%s/gfs.%s/%s/atmos/gfs.t%sz.pgrb2.0p25.f%03d" % (GFS, ymd, hh, hh, fh)


def aigfs(ymd, hh, fh):
    """AI-GFS 0.25 deg global GRIB2 (.idx sidecar; UGRD/VGRD 10 m above ground, PRMSL mean sea level)."""
    if ymd >= AIGFS_OPER_FROM:
        return "%s/aigfs.%s/%s/model/atmos/grib2/aigfs.t%sz.sfc.f%03d.grib2" % (AIGFS, ymd, hh, hh, fh)
    run = "graphcastgfs.%s/%s" % (ymd, hh)
    if ymd < AIGFS_LIVE_FROM:
        run = "hindcast_aigfsdev2.5/" + run
    return "%s/%s/forecasts_13_levels/graphcastgfs.t%sz.pgrb2.0p25.f%03d" % (AIGFS, run, hh, fh)


def gdas(ymd, hh, fh):
    return "%s/gdas.%s/%s/atmos/gdas.t%sz.pgrb2.0p25.f%03d" % (GFS, ymd, hh, hh, fh)


def gfs_wave(ymd, hh, fh):
    return "%s/gfs.%s/%s/wave/gridded/gfswave.t%sz.global.0p25.f%03d.grib2" % (GFS, ymd, hh, hh, fh)


def gefs(ymd, hh, fh, mem):
    """mem: 'c00', 'p01' .. 'p30'."""
    return "%s/gefs.%s/%s/atmos/pgrb2sp25/ge%s.t%sz.pgrb2s.0p25.f%03d" % (GEFS, ymd, hh, mem, hh, fh)


def ecmwf(model, stream, typ, ymd, hh, step):
    """File URL without extension. model 'ifs' or 'aifs-single' (also 'aifs-ens');
    stream/typ: oper/fc, enfo/ef, enfo/cf, enfo/pf."""
    return "%s/%s/%sz/%s/0p25/%s/%s%s0000-%dh-%s-%s" % (EC, ymd, hh, model, stream, ymd, hh, step, stream, typ)
