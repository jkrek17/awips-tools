"""Byte-range fetch of NWP fields from the AWS open-data mirrors (GFS, GDAS, GEFS,
GFS-Wave, ECMWF IFS / AIFS / ENS / AIFS ENS). Only the wanted GRIB records are
downloaded, found through the .idx / .index sidecars; grids come back decoded,
north-up, lon 0..360, float32, optionally cropped with crop=(IY, IX)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import sources
from .cycles import cycle_list, newest_cycle, wait_for_quiet
from .grib import decode
from .http import exists, get
from .index import ec_records, forget, ncep_index, ncep_records, span

__all__ = ["get", "exists", "decode", "ncep", "ec_fields", "fields", "gefs_members", "ec_ens",
           "ncep_index", "ncep_records", "ec_records", "span", "sources", "cycle_list",
           "newest_cycle", "wait_for_quiet"]


def ncep(url, want, crop=None):
    """want: {'UGRD:10 m above ground': 'u', ...} -> {'u': array, ...} or None
    (no index, or a wanted record missing). 'msl' falls back to MSLET."""
    idx = ncep_index(url)
    if idx is None:
        return None
    out = {}
    for key, name in want.items():
        if key not in idx:
            if name == "msl" and "MSLET:mean sea level" in idx:
                key = "MSLET:mean sea level"
            else:
                return None
        r = get(url, idx[key])
        if r is None:   # index posted but the record not (yet) reachable: skip, and re-read the index next time
            forget(url + ".idx")
            return None
        out[name] = decode(r.content, crop)
    return out


def ec_fields(base, select, crop=None):
    """select: {(levtype, param, levelist): name}, levelist a string or None.
    -> {name: array} for the records found (callers check they got them all), or
    None when the file has no index."""
    recs = ec_records(base)
    if recs is None:
        return None
    out = {}
    for r in recs:
        lev = r.get("levelist")
        name = select.get((r.get("levtype"), r["param"], None if lev is None else str(lev)))
        if name is not None:
            g = get(base + ".grib2", span(r))
            if g is None:   # callers see the field missing
                forget(base + ".index")
                continue
            out[name] = decode(g.content, crop)
    return out


def fields(source, cycle, step, names, member=None, crop=None):
    """source: gfs, gdas, gefs (member), gfs_wave, ifs or aifs-single; cycle 'YYYYMMDDHH'.
    names: NCEP {'VAR:level': name} or, for ifs / aifs-single, an ec_fields select."""
    ymd, hh = cycle[:8], cycle[8:10]
    if source in ("ifs", "aifs-single"):
        return ec_fields(sources.ecmwf(source, "oper", "fc", ymd, hh, step), names, crop)
    url = {"gfs": sources.gfs, "gdas": sources.gdas, "gfs_wave": sources.gfs_wave}.get(source)
    url = url(ymd, hh, step) if url else sources.gefs(ymd, hh, step, member)
    return ncep(url, names, crop)


def _stack(mem, names, keys):
    return {n: np.array([mem[k][n] for k in keys]) for n in names}


def gefs_members(ymd, hh, fh, want, members=sources.GEFS_MEMBERS, crop=None, workers=6):
    """All members in one call, threaded -> ([members found], {name: [n,y,x]}) in
    `members` order, or None when none was posted."""
    def one(m):
        return ncep(sources.gefs(ymd, hh, fh, m), want, crop)
    with ThreadPoolExecutor(workers) as ex:
        got = list(ex.map(one, members))
    ok = [(m, g) for m, g in zip(members, got) if g]
    if not ok:
        return None
    mem = {m: g for m, g in ok}
    return [m for m, _ in ok], _stack(mem, list(want.values()), list(mem))


def ec_ens(model, ymd, hh, step, select, crop=None, workers=6):
    """All members' sfc fields -> {name: [n,y,x]} in member order, or None.
    select: {ECMWF param: name}, e.g. {'10u': 'u', '10v': 'v'}.
    model 'ifs': ENS, 50 perturbed plus the control when posted, in one -ef file.
    model 'aifs-ens': the control (-cf) and 50 perturbed (-pf) files."""
    typs = ("ef",) if model == "ifs" else ("cf", "pf")
    jobs = []
    for typ in typs:
        base = sources.ecmwf(model, "enfo", typ, ymd, hh, step)
        recs = ec_records(base)
        if recs is None:
            return None
        jobs += [(base, r) for r in recs if r.get("levtype") == "sfc" and r["param"] in select]

    def one(job):
        base, r = job
        g = get(base + ".grib2", span(r))
        return int(r.get("number", 0)), select[r["param"]], None if g is None else decode(g.content, crop)

    mem = {}
    with ThreadPoolExecutor(workers) as ex:
        for m, name, v in ex.map(one, jobs):
            if v is not None:   # a member with a missing field is dropped below
                mem.setdefault(m, {})[name] = v
    keys = sorted(k for k, d in mem.items() if len(d) == len(select))
    if not keys:
        return None
    return _stack(mem, list(select.values()), keys)
