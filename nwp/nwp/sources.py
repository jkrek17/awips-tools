"""URL builders for the AWS open-data mirrors. ymd 'YYYYMMDD', hh '00', fh/step int."""

GFS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
GEFS = "https://noaa-gefs-pds.s3.amazonaws.com"
EC = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
GEFS_MEMBERS = ["c00"] + ["p%02d" % i for i in range(1, 31)]


def gfs(ymd, hh, fh):
    return "%s/gfs.%s/%s/atmos/gfs.t%sz.pgrb2.0p25.f%03d" % (GFS, ymd, hh, hh, fh)


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
