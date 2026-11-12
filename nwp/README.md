# nwp

Byte-range fetch of NWP fields from the AWS open-data mirrors (GFS, GDAS, AI-GFS, GEFS, GFS-Wave,
ECMWF IFS, AIFS, ENS, AIFS ENS). Only the wanted GRIB records are downloaded, located
through the `.idx` / `.index` sidecars (each read once per file). Grids come back decoded,
north-up, lon 0..360, float32.

    pip install "git+https://github.com/jkrek17/awips-tools@<sha>#subdirectory=nwp"
    # in the repo: sys.path.insert(0, "<repo>/nwp"); import nwp

    nwp.ncep(url, {"UGRD:10 m above ground": "u"}, crop=None)   # NCEP file -> {name: grid} or None
    nwp.ec_fields(base, {("sfc", "10u", None): "u"})             # ECMWF file (no extension)
    nwp.fields("gfs", "2026101500", 24, names, member=None)      # gfs, gdas, aigfs, gefs, gfs_wave, ifs, aifs-single
    nwp.fields("aigfs", "2026101500", 24, {"UGRD:10 m above ground": "u"})  # AI-GFS (NOAA GraphCast), 3 bucket layouts by date
    nwp.gefs_members(ymd, hh, fh, want)                          # ([members], {name: [n,y,x]})
    nwp.ec_ens("aifs-ens", ymd, hh, step, {"10u": "u", "10v": "v"})
    nwp.newest_cycle(nwp.cycle_list(), lambda c: [url, ...])     # first cycle with all files posted
    nwp.wait_for_quiet(index_url)                                # opt-in; never in live jobs
    nwp.get(url, rng) / nwp.exists(url) / nwp.decode(blob, crop) / nwp.sources.gfs(...)
    from nwp import star                                         # NOAA STAR scatterometer passes (OSCAT-3, Metop-B/C ASCAT)
    star.passes(day)  -> [(prefix, url, start)];  star.points(url) -> {lat, lon (-180..180), u, v, spd (kt), q}
    from nwp import rss_ascat                                    # Remote Sensing Systems ASCAT, daily 0.25 deg, full swaths
    rss_ascat.day("b", date) -> {lat, lon (-180..180), spd_kt, dir_deg (from), t_min (after 00 UTC), rain, node} or None (404)

RSS ASCAT (`rss_ascat.day(sat, date)`, sat `b` or `c`) is the open-ocean ASCAT that STAR's coastal product lacks: one
1-3 MB file per satellite and UTC day, posted about 2 days late (lately about 5); cell centres sit at x.125 degrees. Winds are
RSS's equivalent-neutral 10 m wind in knots, used as STAR winds are (no conversion). Format: the module docstring.

`crop=(IY, IX)` is applied as `v[IY, IX].copy()`; without it the full grid is returned.
`get` returns None on 403/404, retries S3 503 quickly, backs off otherwise, and raises
`RuntimeError` when it gives up. Tests: `python3 -m pytest nwp/tests` (`NWP_NETWORK=1` adds the live AI-GFS fetches).
