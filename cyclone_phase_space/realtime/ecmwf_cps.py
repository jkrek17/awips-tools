#!/usr/bin/env python3
"""Hart cyclone phase space four-panel images from ECMWF open-data IFS 0.25
degree forecasts.

Proof of concept, the ECMWF counterpart to gfs_cps.py: fetches only the
GRIB2 messages the operational D2D module needs (byte-range HTTP GETs
against the .index sidecars ECMWF publishes at
https://data.ecmwf.int/forecasts/), decodes them with pygrib, and reuses
gfs_cps.py's own compute and plotting functions unchanged to write, per
forecast hour, a compressed npz, the OPC four-panel figure and a lows
table under out/ecmwf/<cycle>/; a montage when more than one hour is
requested.

    python3 ecmwf_cps.py --cycle 2026092500 --hours 0 6 12 --region natl

Field availability (checked against real ECMWF open-data requests; see
README.md): geopotential height ('gh', already in geopotential meters,
no conversion needed) is posted at all six standard levels used here,
925, 850, 700, 500, 400 and 300 hPa, including 400 hPa, at every 6 h
step to at least 144 h of both the 00 and 12 UTC runs; u/v wind is
posted at 850, 700, 500 and 300 hPa; mean sea level pressure ('msl')
and surface pressure ('sp') are both posted. Surface pressure was not
missing at any forecast hour checked here, but the fallback below is
kept in the code because ECMWF's own product list is not guaranteed
for every future cycle: if 'sp' is absent from an hour's index, psfc is
set to a constant 1013 hPa there, which only widens the below-ground
mask to the model's own missing values (rather than PRES's terrain
mask); the frame's title and the lows-table's rows for that hour are
unaffected other than by that wider mask, and the figure's title and
this run's console output say so.

Grid convention: identical handling to gfs_cps.py. ECMWF's own grid
runs latitude descending (90 to -90) with longitude -180 to 179.75
(unlike GFS's 0 to 359.75); decode() reorders it the same way
gfs_cps.decode() reorders GFS files, to rows increasing northward and
columns increasing eastward from the fetch box's west edge, using
gfs_cps's own fetch_box() unchanged. Checked on the 2026092500 f000
natl-plus-margin box: B (Hart's asymmetry parameter) is positive at
99.9% of the 14,215 points between 35N and 60N with 850 hPa wind over
8 m/s and 925-700 hPa thickness falling northward (median 39.1 m),
the same polar-front sign check the GFS README runs (there: 98.5%
positive, median 35.6 m).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gfs_cps as gc  # noqa: E402  compute_products, plotting, region/cache helpers, all reused unchanged

ECMWF_BASE = "https://data.ecmwf.int/forecasts"
FALLBACK_PSFC_HPA = 1013.0

# Field key -> (pygrib shortName, pygrib typeOfLevel, ECMWF .index "levelist" or None).
# ECMWF's own param abbreviations equal pygrib's shortName for every field used here
# (verified against real .index/.grib2 downloads; see README), so no name-mapping
# table like gfs_cps's PYGRIB_NAMES is needed.
SELECTORS = {}
for _p in gc.HGT_LEVELS:
    SELECTORS[f"z{_p}"] = ("gh", "isobaricInhPa", str(_p))
for _p in gc.WIND_LEVELS:
    SELECTORS[f"u{_p}"] = ("u", "isobaricInhPa", str(_p))
    SELECTORS[f"v{_p}"] = ("v", "isobaricInhPa", str(_p))
SELECTORS["pmsl"] = ("msl", "meanSea", None)
SELECTORS["psfc"] = ("sp", "surface", None)
SELECTORS["land"] = ("lsm", "surface", None)


# ------------------------------------------------------------------ helpers
def grib_stem(cycle: str, fhr: int) -> str:
    """ECMWF's own file stem, e.g. 20260925000000-6h-oper-fc (no zero padding on fhr)."""
    ymd, hh = cycle[:8], cycle[8:]
    return f"{ymd}{hh}0000-{fhr}h-oper-fc"


def dir_url(cycle: str) -> str:
    ymd, hh = cycle[:8], cycle[8:]
    return f"{ECMWF_BASE}/{ymd}/{hh}z/ifs/0p25/oper"


def index_url(cycle: str, fhr: int) -> str:
    return f"{dir_url(cycle)}/{grib_stem(cycle, fhr)}.index"


def grib_url(cycle: str, fhr: int) -> str:
    return f"{dir_url(cycle)}/{grib_stem(cycle, fhr)}.grib2"


def cycle_exists(cycle: str) -> bool:
    """True if the cycle's f006 index is posted (00 or 12 UTC only; ECMWF's
    open-data HRES atmospheric product runs only at those two cycles)."""
    try:
        return requests.head(index_url(cycle, 6), timeout=gc.TIMEOUT).status_code == 200
    except requests.RequestException:
        return False


def latest_cycle(now: dt.datetime | None = None) -> str:
    """Most recent 00 or 12 UTC cycle whose f006 index exists, probing back
    up to four days in 12 h steps."""
    now = now or dt.datetime.now(dt.timezone.utc)
    t = now.replace(hour=now.hour // 12 * 12, minute=0, second=0, microsecond=0)
    for _ in range(8):
        cyc = t.strftime("%Y%m%d%H")
        if cycle_exists(cyc):
            return cyc
        t -= dt.timedelta(hours=12)
    raise RuntimeError("no ECMWF open-data IFS 0.25 cycle with an f006 index found in the last four days")


# ------------------------------------------------------------------ download
def fetch_ecmwf(cycle: str, fhr: int, path: Path) -> bool:
    """Read the .index sidecar and byte-range GET just the wanted messages of
    the whole-grid file (there is no server-side regional subset, as there is
    with NOMADS; the region box is cut out after decoding, as with gfs_cps's
    AWS path). Returns whether 'sp' (surface pressure) was found; if not,
    every other wanted field must still be present or this raises."""
    idx_text = gc.http_get(index_url(cycle, fhr)).text
    by_key = {}
    for line in idx_text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        by_key[(rec["param"], rec.get("levelist"))] = rec

    url = grib_url(cycle, fhr)
    chunks, missing, have_sp = [], [], False
    for key, (param, _tol, levelist) in SELECTORS.items():
        rec = by_key.get((param, levelist))
        if rec is None:
            if key == "psfc":
                continue  # degrade to the constant-1013-hPa fallback in decode()
            missing.append(f"{param}" + (f" {levelist} hPa" if levelist else ""))
            continue
        if key == "psfc":
            have_sp = True
        start, end = rec["_offset"], rec["_offset"] + rec["_length"] - 1
        chunks.append(gc.http_get(url, headers={"Range": f"bytes={start}-{end}"}).content)
    if missing:
        raise RuntimeError(f"{grib_stem(cycle, fhr)}: missing {', '.join(missing)}")
    path.write_bytes(b"".join(chunks))
    return have_sp


def get_grib(cycle: str, fhr: int, cache: Path) -> tuple[Path, bool]:
    """Cached GRIB2 path for one forecast hour (whole grid; serves every
    region), downloading on a miss. A sidecar .sp file records whether the
    cached file carries surface pressure, so a cache hit does not need to
    re-open the GRIB2 to know."""
    cache.mkdir(parents=True, exist_ok=True)
    grb = cache / f"global_f{fhr:03d}.ecmwf.grb2"
    sp_flag = cache / f"global_f{fhr:03d}.ecmwf.sp"
    if grb.exists() and grb.stat().st_size > 0 and sp_flag.exists():
        return grb, sp_flag.read_text().strip() == "1"
    have_sp = fetch_ecmwf(cycle, fhr, grb.with_suffix(".part"))
    grb.with_suffix(".part").rename(grb)
    sp_flag.write_text("1" if have_sp else "0")
    return grb, have_sp


# ------------------------------------------------------------------ decode
def decode(path: Path, region: str, have_sp: bool) -> dict:
    """Decode the wanted messages with pygrib and reorder them exactly like
    gfs_cps.decode(): rows latitude-ascending, columns contiguous eastward
    from the fetch box's west edge (gfs_cps.fetch_box(), unchanged), whatever
    order and longitude convention the source file used (ECMWF's own grid is
    latitude-descending, longitude -180 to 179.75). When `have_sp` is False,
    psfc is a constant 1013 hPa field instead of a decoded message."""
    import pygrib

    w, span, s, n = gc.fetch_box(region)
    out = {}
    with pygrib.open(str(path)) as g:
        msgs = list(g)
    lat_out = lon_out = None
    for key, (param, tol, levelist) in SELECTORS.items():
        if key == "psfc" and not have_sp:
            continue
        level = int(levelist) if levelist is not None else 0
        hit = [m for m in msgs if m.shortName == param and m.typeOfLevel == tol and m.level == level]
        if not hit:
            raise RuntimeError(f"{path.name}: missing {param} {tol} {level}")
        m = hit[0]
        if lat_out is None:
            la, lo = m.latlons()
            lat_raw, lon_raw = la[:, 0], lo[0, :]
            rel = (lon_raw - w) % 360.0
            cols = np.argsort(rel)
            cols = cols[rel[cols] <= span + 1e-6]
            rows = np.argsort(lat_raw)
            rows = rows[(lat_raw[rows] >= s - 1e-6) & (lat_raw[rows] <= n + 1e-6)]
            lon_out = w + rel[cols]
            lat_out = lat_raw[rows]
        out[key] = np.asarray(m.values, dtype=float)[np.ix_(rows, cols)]
        out.setdefault("valid", m.validDate.replace(tzinfo=dt.timezone.utc))
    if not have_sp:
        out["psfc"] = np.full_like(out["pmsl"], FALLBACK_PSFC_HPA * 100.0)  # Pa, like GFS's PRES
    out["lat"], out["lon"] = lat_out, lon_out
    return out


# ------------------------------------------------------------------ titles (ECMWF wording, otherwise gfs_cps's)
def frame_title(cycle: str, fhr: int, valid: dt.datetime, region: str, have_sp: bool) -> str:
    """Same layout as gfs_cps.frame_title, with the model name and, only
    when it happened, the surface-pressure fallback noted."""
    c = gc.cycle_time(cycle)
    note = "" if have_sp else "   sp not posted: below-ground mask uses a constant 1013 hPa"
    return (f"ECMWF IFS 0.25   cycle {c:%Y-%m-%d %H} UTC   F{fhr:03d}   valid {valid:%a %Y-%m-%d %H} UTC   "
            f"Hart CPS ({region}){note}")


def plot_montage(frames: list[dict], region: str, cycle: str, cm: dict, any_fallback: bool, path: Path) -> None:
    """Rows by forecast hour; identical to gfs_cps.plot_montage (draw_panels,
    add_colorbar and panel_aspect reused unchanged), only the suptitle
    differs, since gfs_cps's own suptitle text is not a separate function."""
    asp = gc.panel_aspect(region, frames[0])
    n = len(frames)
    fig = gc.plt.figure(figsize=(18.0, n * (4.5 * asp + 0.35) + 1.2), dpi=100, layout="constrained")
    columns = [[] for _ in range(4)]
    mappables = None
    for r, fr in enumerate(frames):
        axes = [fig.add_subplot(n, 4, 4 * r + k + 1, projection=gc.projection(region)) for k in range(4)]
        mappables = gc.draw_panels(axes, fr, region, cm, small=True)
        for i, ax in enumerate(axes):
            ax.set_title(f"F{fr['fhr']:03d} {fr['valid']:%d/%HZ}  {gc.PANEL_TITLES[i]}", fontsize=7)
            columns[i].append(ax)
    for i in range(4):
        gc.add_colorbar(fig, mappables[i], columns[i], i, small=True, fraction=0.045 / n)
    note = "; sp not posted for some hours: below-ground mask uses a constant 1013 hPa" if any_fallback else ""
    fig.suptitle(f"ECMWF IFS 0.25 Hart CPS, cycle {gc.cycle_time(cycle):%Y-%m-%d %H} UTC, {region}{note}",
                fontsize=13)
    fig.savefig(path, dpi=100)
    gc.plt.close(fig)


# ------------------------------------------------------------------ driver
def run_frame(cycle: str, fhr: int, region: str, outdir: Path, cm: dict) -> dict:
    """Fetch, decode, compute, save the npz and the figure for one forecast
    hour. compute_products, find_lows, region_slices, write_lows and
    plot_frame are gfs_cps's own, called unchanged (only frame_title, which
    plot_frame calls unqualified, is swapped in on gfs_cps's own module
    namespace so the title says ECMWF instead of GFS)."""
    t0 = time.time()
    cache = outdir.parent / "cache" / cycle
    grib, have_sp = get_grib(cycle, fhr, cache)
    f = decode(grib, region, have_sp)
    t1 = time.time()
    p = gc.compute_products(f)
    t2 = time.time()
    lows = gc.find_lows(f, p, region, cycle, fhr)
    rows, cols = gc.region_slices(f, region)
    cut = np.ix_(rows, cols)
    fr = {k: v[cut] for k, v in {**p, "mslp": f["pmsl"] / 100.0, "u850": f["u850"], "v850": f["v850"],
                                  "u300": f["u300"], "v300": f["v300"], "land": f["land"]}.items()}
    fr.update(lat=f["lat"][rows], lon=f["lon"][cols], valid=f["valid"], fhr=fhr, lows=lows, have_sp=have_sp)
    np.savez_compressed(outdir / f"cps_{region}_f{fhr:03d}.npz", lat=fr["lat"], lon=fr["lon"],
                        mslp_hpa=fr["mslp"].astype(np.float32),
                        **{k: fr[k].astype(np.float32) for k in ("hvtl", "hvtu", "hb", "idx", "cls") if k in fr})
    gc.frame_title = lambda cyc, fh, valid, reg: frame_title(cyc, fh, valid, reg, have_sp)
    gc.plot_frame(fr, region, cycle, cm, outdir / f"cps4_{region}_f{fhr:03d}.png")
    tag = "" if have_sp else "  [no sp: psfc=1013 hPa constant]"
    print(f"  f{fhr:03d}: {grib.name}, fetch+decode {t1 - t0:.1f} s, compute {t2 - t1:.1f} s, "
          f"plot {time.time() - t2:.1f} s, {len(lows)} lows{tag}")
    return fr


def main(argv=None) -> int:
    """Command line entry point (same flags as gfs_cps.py: --cycle, --hours,
    --region, --out)."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycle", help="YYYYMMDDHH, 00 or 12 UTC (default: latest cycle whose f006 index exists)")
    ap.add_argument("--hours", type=int, nargs="+", default=list(range(0, 145, 6)))
    ap.add_argument("--region", choices=sorted(gc.REGIONS), default="natl")
    ap.add_argument("--out", type=Path, default=HERE / "out" / "ecmwf")
    a = ap.parse_args(argv)
    cycle = a.cycle or latest_cycle()
    outdir = a.out / cycle
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"cycle {cycle}, region {a.region}, hours {a.hours}, source ECMWF open data (IFS 0.25 deg), "
          f"maps {'cartopy' if gc.HAVE_CARTOPY else 'plain lon/lat, GFS-style land-mask coastline'}")
    cm = gc.make_cmaps()
    t0 = time.time()
    frames, lows = [], []
    for fhr in a.hours:
        try:
            fr = run_frame(cycle, fhr, a.region, outdir, cm)
        except Exception as exc:  # keep going: a late hour may not be posted yet
            print(f"  f{fhr:03d}: skipped ({exc})")
            continue
        frames.append(fr)
        lows.extend(fr["lows"])
    if not frames:
        return 1
    gc.write_lows(outdir / f"lows_{a.region}.csv", lows, [fr["fhr"] for fr in frames])
    if len(frames) > 1:
        any_fallback = any(not fr.get("have_sp", True) for fr in frames)
        plot_montage(frames, a.region, cycle, cm, any_fallback, outdir / f"cps4_{a.region}_montage.png")
    print(f"done: {len(frames)} frames in {time.time() - t0:.1f} s, output in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
