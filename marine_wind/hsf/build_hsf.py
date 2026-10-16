"""Draft High Seas Forecast text from the marine wind page's own grids (a first guess for the
desk; the forecaster still edits and issues the product).

Reads the per-basin box the page build already writes (manifest.json + fFFF.bin: the wind
Core Lifted wind, i.e. storm cores kept, and the 3-model mean pressure), adds GFS-Wave significant wave height
from the same cycle, and writes the draft with the writer in writer.py.

Valid times: the page holds leads every 12 h, so cycle C feeds the issuance whose synopsis is
C+12 h (06Z run -> 2230Z issuance, synopsis 18Z), with 24 and 48 h forecasts and a 12 h step
in between when a low's warning level goes up.

usage: python3 build_hsf.py --box DIR [--basin pac] --out DIR
"""
import argparse
import datetime as dt
import json
import os
import sys
import textwrap

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from areas import AREAS, inside, outline  # noqa: E402
from writer import WARN, Grid, Rules, write_product  # noqa: E402

SYN_LEAD = 12                 # page lead of the synopsis
HOURS = (0, 12, 24, 36, 48)   # HSF hours carried by the page's 12-hourly leads
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASIN_DOMAIN = {"pac": "npac", "atl": "natl"}


def read_box(box):
    """{lead: {field: float grid}}, lats, lons, cycle from a page box (manifest + fFFF.bin)."""
    man = json.load(open(os.path.join(box, "manifest.json")))
    g = man["grid"]
    lats = g["north"] - 0.25 * np.arange(g["ny"])
    lons = g["west"] + 0.25 * np.arange(g["nx"])
    names = [f["name"] for f in man["fields"]]
    out = {}
    for st in man["steps"]:
        raw = np.fromfile(os.path.join(box, "f%03d.bin" % st["step"]), np.uint8).reshape(len(names), g["ny"], g["nx"])
        out[st["step"]] = {f["name"]: raw[i] / float(f["scale"]) - f["offset"]
                           for i, f in enumerate(man["fields"]) if f["name"] in ("windcore", "wind", "msl")}
    cycle = dt.datetime.strptime(man["cycle"], "%Y-%m-%dT%H:00Z")
    return out, lats, lons, cycle


def wave_heights(cycle, leads):
    """GFS-Wave significant wave height (m) on the box grid; NaN over land and ice."""
    sys.path.insert(0, os.path.join(HERE, "..", "pipeline"))
    import fetch   # crops to MARINE_DOMAIN, set by the caller before import
    ymd, hh = cycle.strftime("%Y%m%d"), cycle.strftime("%H")
    out = {}
    for fh in leads:
        url = "%s/gfs.%s/%s/wave/gridded/gfswave.t%sz.global.0p25.f%03d.grib2" % (fetch.GFS, ymd, hh, hh, fh)
        w = fetch._ncep(url, {"HTSGW:surface": "hs"})
        if w is None:
            raise RuntimeError("GFS-Wave +%dh missing" % fh)
        hs = w["hs"].astype(np.float32)
        hs[(hs > 50) | (hs < 0)] = np.nan
        out[fh] = hs
    return out


def draft(fields, lats, lons, basin="pac", rules=None):
    """fields: {hour: dict(wind kt, msl hPa, hs m)} with hours from the synopsis. Returns
    (warnings, synopsis_text, areas, lows): every described area with its outline, and the
    low centers the text names."""
    grid = Grid(lats, lons)
    sea = inside(AREAS[basin], grid.LON, grid.LAT) & np.isfinite(fields[0]["hs"])
    warn, syn, dbg = write_product(fields, grid, sea, rules or Rules())
    areas = []
    for p in dbg["pieces"]:
        for i, t in enumerate(p["tiers"]):
            areas.append(dict(hour=p["hour"], warning=WARN.get(p["top"], ""), letter=LETTERS[len(areas) % 26],
                              wind=list(t.wind), seas=list(t.seas) if t.seas else None, text=t.phrase["text"],
                              rings=outline(t.mask, lats, lons)))
    # the low centers the text names (one per paragraph and time)
    lows = sorted({(p["hour"], p["low"][0], p["low"][1], p["low"][2]) for p in dbg["pieces"] if p.get("low")})
    lows = [dict(hour=h, lat=la, lon=lo, mb=mb) for h, la, lo, mb in lows]
    return warn, syn, areas, lows


def product(syn_time, warn, syn):
    wrap = lambda t: "\n".join(textwrap.fill(p, 66, break_on_hyphens=False) for p in t.split("\n"))
    head = "\n".join("%s VALID %s." % (lab, (syn_time + dt.timedelta(hours=h)).strftime("%H00 UTC %b %d").upper())
                     for lab, h in (("SYNOPSIS", 0), ("24 HOUR FORECAST", 24), ("48 HOUR FORECAST", 48)))
    return "%s\n\n.WARNINGS.\n\n%s\n\n.SYNOPSIS AND FORECAST.\n\n%s\n" % (head, wrap(warn) or "NONE.", wrap(syn) or "NONE.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--box", required=True, help="page box folder (manifest.json + fFFF.bin)")
    ap.add_argument("--basin", default="pac", choices=list(AREAS))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.environ.setdefault("MARINE_DOMAIN", BASIN_DOMAIN[a.basin])
    box, lats, lons, cycle = read_box(a.box)
    leads = [SYN_LEAD + h for h in HOURS]
    missing = [s for s in leads if s not in box]
    if missing:
        raise SystemExit("page box lacks leads %s" % missing)
    hs = wave_heights(cycle, leads)
    fields = {h: dict(wind=box[SYN_LEAD + h]["windcore"], msl=box[SYN_LEAD + h]["msl"] + 900.0, hs=hs[SYN_LEAD + h]) for h in HOURS}
    warn, syn, areas, lows = draft(fields, lats, lons, a.basin)
    syn_time = cycle + dt.timedelta(hours=SYN_LEAD)
    text = product(syn_time, warn, syn)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "%s.txt" % a.basin), "w") as f:
        f.write(text)
    doc = dict(basin=a.basin, cycle=cycle.strftime("%Y-%m-%dT%H:00Z"), synopsis=syn_time.strftime("%Y-%m-%dT%H:00Z"),
               built=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
               source="Marine wind page: Core Lifted wind (storm cores kept), 3-model mean pressure; GFS-Wave seas",
               hours=list(HOURS), text=text, areas=areas, lows=lows,
               boundary=[list(p) for p in AREAS[a.basin]], box_leads={h: SYN_LEAD + h for h in HOURS})
    with open(os.path.join(a.out, "%s.json" % a.basin), "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print("HSF draft %s from %s: %d areas" % (a.basin, doc["cycle"], len(areas)))


if __name__ == "__main__":
    main()
