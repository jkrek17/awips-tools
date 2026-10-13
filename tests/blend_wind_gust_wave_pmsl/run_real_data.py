#!/usr/bin/env python3
"""Run Blend_WindGustWavePmsl on the newest real GFS and ECMWF runs.

The fake GFE (gfe_fakes) is filled with the last few GFS / GFS Wave cycles
from NOMADS and ECMWF / ECMWF wave cycles from the ECMWF open-data server,
laid out the way D2D presents them (wind FHAG10 and gust SFC in m/s, pmsl MSL
in Pa, waves in m).  The procedure then picks each model's newest complete
run itself, blends 3-hourly Fcst grids over the period, and this script
checks what it wrote and plots the models beside the blend.

    python3 run_real_data.py                        # W Atlantic, from now, 90 h
    python3 run_real_data.py --box 30,55,-150,-120 --hours 72 --weights GFS=1,ECMWF=1
    python3 run_real_data.py --start 2026101306

Needs numpy, matplotlib, requests and eccodes (pip install eccodes).
Writes the log, maps and cache to out/ (gitignored).
"""
import argparse
import calendar
import json
import os
import sys
import time

import numpy as np

import gfe_fakes

SS = gfe_fakes.install()
import Blend_WindGustWavePmsl as B  # noqa: E402
import model_data as M  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
H = 3600
COAST = os.path.join(HERE, "..", "..", "cyclone_phase_space", "article", "live", "basemap", "coast_50m.json")


def parse_args():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--box", default="30,50,-80,-50", help="lat0,lat1,lon0,lon1 (default W Atlantic)")
    a.add_argument("--start", help="first Fcst time YYYYMMDDHH (default: now, rounded down to 3 h)")
    a.add_argument("--hours", type=int, default=90, help="length of the period (default 90)")
    a.add_argument("--weights", default="GFS=2,ECMWF=3", help="model weights (default GFS=2,ECMWF=3)")
    a.add_argument("--cycles", type=int, default=3, help="newest cycles offered per model (default 3)")
    return a.parse_args()


def uv_to_magdir(u, v):
    return np.hypot(u, v), np.mod(270.0 - np.degrees(np.arctan2(v, u)), 360.0)


def build_store(t0, t1, n_cycles):
    """Model databases from the newest cycles on the servers, plus Fcst grids to replace."""
    store, dbs, notes = {}, {}, []
    tr = gfe_fakes.time_range

    def add(model_id, elem, level, units, valid, grid):
        store.setdefault((model_id, elem, level), {"units": units, "grids": []})["grids"].append((tr(valid), grid))

    now = int(time.time()) // (6 * H) * (6 * H)
    cycles = [time.strftime("%Y%m%d %H", time.gmtime(now - i * 6 * H)).split() for i in range(n_cycles + 1)]
    last = t1 + 12 * H

    for ymd, hh in cycles:
        c = M.cycle_unix(ymd, hh)
        hours = [h for h in M.gfs_hours(ymd, hh, "atmos") if c + h * H <= last]
        whours = [h for h in M.gfs_hours(ymd, hh, "wave") if c + h * H <= last]
        notes.append("GFS   %s %sZ: %3d atmos / %3d wave hours posted up to the period's end" % (ymd, hh, len(hours), len(whours)))
        if hours:
            mid = "XXX_GRID_D2D_GFS_%s_%s00" % (ymd, hh)
            dbs.setdefault("D2D_GFS", []).append(mid)
            for h in hours:
                f = (lambda ymd=ymd, hh=hh, h=h: M.gfs_fields(ymd, hh, h, "atmos"))
                add(mid, "wind", "FHAG10", "m/s", c + h * H, lambda f=f: uv_to_magdir(f()["10u"], f()["10v"]))
                add(mid, "gust", "SFC", "m/s", c + h * H, lambda f=f: f()["gust"])
                add(mid, "pmsl", "MSL", "Pa", c + h * H, lambda f=f: f()["prmsl"])
        if whours:
            mid = "XXX_GRID__GFSWave_%s_%s00" % (ymd, hh)
            dbs.setdefault("GFSWave", []).append(mid)
            for h in whours:
                add(mid, "WaveHeight", "SFC", "m", c + h * H,
                    lambda ymd=ymd, hh=hh, h=h: M.gfs_fields(ymd, hh, h, "wave")["swh"])

    for ymd, hh in cycles:
        c = M.cycle_unix(ymd, hh)
        steps = [s for s in M.ec_steps(ymd, hh, "oper") if c + s * H <= last]
        wsteps = [s for s in M.ec_steps(ymd, hh, "wave") if c + s * H <= last]
        notes.append("ECMWF %s %sZ: %3d oper / %3d wave steps posted up to the period's end" % (ymd, hh, len(steps), len(wsteps)))
        if steps:
            mid = "XXX_GRID_D2D_ECMWF_%s_%s00" % (ymd, hh)
            dbs.setdefault("D2D_ECMWF", []).append(mid)
            for s in steps:
                # 10fg (max gust over the last step) is 10fg3 past 90 h in open data
                f = (lambda ymd=ymd, hh=hh, s=s: M.ec_fields(ymd, hh, s, "oper", ("10u", "10v", "10fg", "10fg3", "msl")))
                add(mid, "wind", "FHAG10", "m/s", c + s * H, lambda f=f: uv_to_magdir(f()["10u"], f()["10v"]))
                if s > 0:
                    add(mid, "gust", "SFC", "m/s", c + s * H, lambda f=f: f().get("10fg", f().get("10fg3")))
                add(mid, "pmsl", "MSL", "Pa", c + s * H, lambda f=f: f()["msl"])
        if wsteps:
            mid = "XXX_GRID__ECMWFwave_%s_%s00" % (ymd, hh)
            dbs.setdefault("ECMWFwave", []).append(mid)
            for s in wsteps:
                add(mid, "WaveHeight", "MSL", "m", c + s * H,
                    lambda ymd=ymd, hh=hh, s=s: M.ec_fields(ymd, hh, s, "wave", ("swh",))["swh"])

    shape = (len(M.LATS), len(M.LONS))
    for elem, units, val in (("Wind", "kts", None), ("WindGust", "kts", 0.0),
                             ("WaveHeight", "ft", 0.0), ("pmsl", "mb", 1013.0)):
        for t in range(t0, t1 + 1, 3 * H):
            grid = (np.zeros(shape), np.zeros(shape)) if val is None else np.full(shape, val)
            add("Fcst", elem, "SFC", units, t, grid)
    return store, dbs, notes


def main():
    args = parse_args()
    lat0, lat1, lon0, lon1 = (float(x) for x in args.box.split(","))
    M.configure(os.path.join(OUT, "cache"), lat0, lat1, lon0, lon1)
    weights = {k: float(v) for k, v in (kv.split("=") for kv in args.weights.split(","))}
    if args.start:
        t0 = calendar.timegm(time.strptime(args.start, "%Y%m%d%H"))
    else:
        t0 = int(time.time()) // (3 * H) * (3 * H)
    t1 = t0 + args.hours // 3 * 3 * H

    store, dbs, notes = build_store(t0, t1, args.cycles)
    SS.store, SS.dbs, SS.shape = store, dbs, (len(M.LATS), len(M.LONS))
    print("\n".join(notes))

    plans = []
    plan_model = B.Procedure._plan_model

    def capture(self, *a, **k):
        plan, problems = plan_model(self, *a, **k)
        plans.append(plan)
        return plan, problems

    B.Procedure._plan_model = capture  # keep each model's plan to plot what was blended

    started = time.time()
    proc = B.Procedure(None)
    proc.execute(None, gfe_fakes.time_range(t0, t1 - t0 + H), {"weights": weights, "gust_factor": 1.3})
    print("\n%.0f s, %d model grid reads, %d Fcst grids written" % (time.time() - started, SS.reads, len(proc.created)))
    status = proc.msgs[-1] if proc.msgs else ("", "")
    print("status [%s]: %s" % status)
    if status[0] == "U" or not proc.created:
        return 1

    blend = {(c[1], c[4].startTime().unixTime()): c[3] for c in proc.created}
    times = sorted({t for _, t in blend})
    ok = verify(blend, times, plans, proc, weights)
    plot(blend, times, plans, proc, weights)
    return 0 if ok else 1


def model_values(proc, plan, elem, ts):
    """A model's grid at one Fcst time in Fcst units, exactly as the blend read it."""
    src = plan.sources[elem]
    parts = proc._read(plan, src, src.recipes[(ts, ts + H)], elem)
    if len(parts) == 2:
        speed = np.hypot(*parts)
        return (speed * 1.3,) if src.from_wind else (speed, parts[0], parts[1])
    return parts


def verify(blend, times, plans, proc, weights):
    total = sum(weights.values())
    nonfinite = [k for k, v in blend.items() if not np.all(np.isfinite(v[0] if k[0] == "Wind" else v))]
    constant = [k for k, v in blend.items() if np.ptp(v[0] if k[0] == "Wind" else v) == 0]
    gust_wind = min(float(np.min(blend[("WindGust", t)] - blend[("Wind", t)][0])) for t in times)
    ts = times[len(times) // 2]
    expect = sum(weights[p.alias] / total * model_values(proc, p, "pmsl", ts)[0] for p in plans)
    pmsl_err = float(np.max(np.abs(blend[("pmsl", ts)] - expect)))
    print("\nchecks on %d written grids:" % len(blend))
    print("  non-finite grids: %s" % (nonfinite or "none"))
    print("  one-value grids:  %s" % (constant or "none"))
    print("  min gust - wind:  %.2f kt" % gust_wind)
    print("  pmsl vs weighted model mean at %s: max diff %.4f mb" % (fmt(ts), pmsl_err))
    return not nonfinite and not constant and gust_wind >= -1e-6 and pmsl_err < 0.01


def fmt(t):
    return time.strftime("%a %d %b %HZ", time.gmtime(t))


def plot(blend, times, plans, proc, weights):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lats, lons = M.LATS, M.LONS
    LON, LAT = np.meshgrid(lons, lats)
    segs = []
    for feature in json.load(open(COAST))["features"]:
        g = feature["geometry"]
        for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            a = np.array(line)
            if ((a[:, 0] > lons[0] - 2) & (a[:, 0] < lons[-1] + 2) & (a[:, 1] > lats[0] - 2) & (a[:, 1] < lats[-1] + 2)).any():
                segs.append(a)

    def base(ax):
        for a in segs:
            ax.plot(a[:, 0], a[:, 1], color="#444", lw=0.6)
        ax.set_xlim(lons[0], lons[-1])
        ax.set_ylim(lats[0], lats[-1])
        ax.set_aspect(1 / np.cos(np.radians(lats.mean())))
        ax.tick_params(labelsize=7)

    total = sum(weights.values())
    rows = [("%s %s" % (p.alias, time.strftime("%HZ", time.gmtime(p.cycles["atmo"]))), p) for p in plans]
    rows.append(("Blend " + " / ".join("%d%% %s" % (100 * weights[p.alias] / total, p.alias) for p in plans), None))
    show = [times[min(i, len(times) - 1)] for i in (8, len(times) // 2, len(times) - 4)]
    os.makedirs(OUT, exist_ok=True)
    for ts in show:
        fig, axes = plt.subplots(len(rows), 4, figsize=(17, 3.5 * len(rows)), constrained_layout=True)
        for i, (name, plan) in enumerate(rows):
            if plan is None:
                spd, d = blend[("Wind", ts)]
                rad = np.radians(d)
                u, v = -spd * np.sin(rad), -spd * np.cos(rad)
                gust, wave, pm = blend[("WindGust", ts)], blend[("WaveHeight", ts)], blend[("pmsl", ts)]
            else:
                spd, u, v = model_values(proc, plan, "Wind", ts)
                gust = model_values(proc, plan, "WindGust", ts)[0]
                wave = model_values(proc, plan, "WaveHeight", ts)[0]
                pm = model_values(proc, plan, "pmsl", ts)[0]
            ax = axes[i, 0]
            base(ax)
            im0 = ax.pcolormesh(LON, LAT, spd, shading="auto", cmap="viridis", vmin=0, vmax=60)
            k = max(1, len(lons) // 20)
            ax.barbs(LON[::k, ::k], LAT[::k, ::k], u[::k, ::k], v[::k, ::k], length=4.2, lw=0.5)
            ax.set_title("Wind (kt)  max %.0f" % np.nanmax(spd), fontsize=9)
            ax.set_ylabel(name, fontsize=11, weight="bold")
            ax = axes[i, 1]
            base(ax)
            ax.pcolormesh(LON, LAT, gust, shading="auto", cmap="viridis", vmin=0, vmax=60)
            ax.set_title("WindGust (kt)  max %.0f" % np.nanmax(gust), fontsize=9)
            ax = axes[i, 2]
            base(ax)
            im2 = ax.pcolormesh(LON, LAT, np.ma.masked_invalid(wave), shading="auto", cmap="magma_r", vmin=0, vmax=25)
            ax.contour(LON, LAT, np.nan_to_num(wave), levels=[12], colors="white", linewidths=0.6)
            ax.set_title("WaveHeight (ft)  max %.0f" % np.nanmax(wave), fontsize=9)
            ax = axes[i, 3]
            base(ax)
            cs = ax.contour(LON, LAT, pm, levels=np.arange(940, 1060, 4), colors="k", linewidths=0.7)
            ax.clabel(cs, fontsize=6, fmt="%d")
            j = np.unravel_index(np.nanargmin(pm), pm.shape)
            ax.text(lons[j[1]], lats[j[0]], "L\n%.0f" % pm[j], color="red", ha="center", va="center", fontsize=8, weight="bold")
            ax.set_title("pmsl (mb)  min %.0f" % np.nanmin(pm), fontsize=9)
        fig.colorbar(im0, ax=axes[:, :2], shrink=0.5, label="kt", location="bottom")
        fig.colorbar(im2, ax=axes[:, 2], shrink=0.8, label="ft (white = 12 ft)", location="bottom")
        fig.suptitle("Blend_WindGustWavePmsl on real model data, valid %s" % fmt(ts), fontsize=13, weight="bold")
        path = os.path.join(OUT, "blend_%s.png" % time.strftime("%Y%m%d%HZ", time.gmtime(ts)))
        fig.savefig(path, dpi=85)
        plt.close(fig)
        print("wrote", path)

    fig, axes = plt.subplots(1, 4, figsize=(17, 3.6), constrained_layout=True)
    x = [(t - times[0]) / H for t in times]
    for k, (elem, f, label) in enumerate((("Wind", lambda g: np.nanmax(g[0]), "max wind (kt)"),
                                          ("WindGust", np.nanmax, "max gust (kt)"),
                                          ("WaveHeight", np.nanmax, "max seas (ft)"),
                                          ("pmsl", np.nanmin, "min pmsl (mb)"))):
        axes[k].plot(x, [f(blend[(elem, t)]) for t in times], "k-o", ms=3)
        axes[k].set_title(label, fontsize=10)
        axes[k].set_xlabel("hours after %s" % fmt(times[0]), fontsize=8)
        axes[k].grid(alpha=0.3)
    fig.suptitle("Blended Fcst grids, all %d times" % len(times), fontsize=11)
    path = os.path.join(OUT, "blend_timeseries.png")
    fig.savefig(path, dpi=85)
    print("wrote", path)


if __name__ == "__main__":
    sys.exit(main())
