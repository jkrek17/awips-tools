# nwp

Byte-range fetch of NWP fields from the AWS open-data mirrors (GFS, GDAS, GEFS, GFS-Wave,
ECMWF IFS, AIFS, ENS, AIFS ENS). Only the wanted GRIB records are downloaded, located
through the `.idx` / `.index` sidecars (each read once per file). Grids come back decoded,
north-up, lon 0..360, float32.

    pip install "git+https://github.com/jkrek17/awips-tools@<sha>#subdirectory=nwp"
    # in the repo: sys.path.insert(0, "<repo>/nwp"); import nwp

    nwp.ncep(url, {"UGRD:10 m above ground": "u"}, crop=None)   # NCEP file -> {name: grid} or None
    nwp.ec_fields(base, {("sfc", "10u", None): "u"})             # ECMWF file (no extension)
    nwp.fields("gfs", "2026101500", 24, names, member=None)      # gfs, gdas, gefs, gfs_wave, ifs, aifs-single
    nwp.gefs_members(ymd, hh, fh, want)                          # ([members], {name: [n,y,x]})
    nwp.ec_ens("aifs-ens", ymd, hh, step, {"10u": "u", "10v": "v"})
    nwp.newest_cycle(nwp.cycle_list(), lambda c: [url, ...])     # first cycle with all files posted
    nwp.wait_for_quiet(index_url)                                # opt-in; never in live jobs
    nwp.get(url, rng) / nwp.exists(url) / nwp.decode(blob, crop) / nwp.sources.gfs(...)

`crop=(IY, IX)` is applied as `v[IY, IX].copy()`; without it the full grid is returned.
`get` returns None on 403/404, retries S3 503 quickly, backs off otherwise, and raises
`RuntimeError` when it gives up. Tests: `python3 -m pytest nwp/tests`.
