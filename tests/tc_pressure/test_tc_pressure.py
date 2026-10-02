#!/usr/bin/env python3
"""Checks for GFE/utilities/TCPressure.py.

TCPressure moves a tropical cyclone in a pmsl field to the warning's position
and strength: it removes the background's own vortex and implants one built
from the same fitted wind profile TCWind_JTWC uses for its Wind grids.

Real warnings from tests/tcwind_jtwc/fixtures drive the physics checks, so
the pressure profiles are built from real fits, not invented numbers.

    python3 test_tc_pressure.py
"""
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "..")
for sub in ("GFE/utilities", "GFE/procedures"):
    sys.path.insert(0, os.path.join(REPO, sub))
sys.path.insert(0, os.path.join(HERE, ".."))           # bundle layout

import TCPressure as P                                          # noqa: E402

FIXTURES = os.path.join(REPO, "tests", "tcwind_jtwc", "fixtures")
FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Storms and fields
# ---------------------------------------------------------------------------

def realStorms():
    """{name: (tau0 storm dict, bulletin pressure)} from the real fixtures."""
    try:
        import TCWind_JTWC as W
    except ImportError:
        return {}
    out = {}
    for f in sorted(glob.glob(os.path.join(FIXTURES, "real_*.txt")) +
                    glob.glob(os.path.join(FIXTURES, "tcm", "real_*.txt"))):
        taus, header, _ = W.parseBulletin(open(f).read())
        name = os.path.basename(f).split("_")[-1].replace(".txt", "")
        s0 = W.interpolateTrack(taus, taus[0].epoch)
        out[name] = (P.stormFromSnapshot(s0, name), header.get("pressureMb"))
    return out


def typhoon(lat=19.5, lon=137.5, vmax=100.0, name="TEST"):
    return {"lat": lat, "lon": lon, "vmax": vmax, "a": 5.0, "rm": 18.0,
            "ri": 60.0, "x1": 0.6, "x2": 0.5, "r34": 120.0, "name": name}


def grid(west=120.0, east=160.0, south=10.0, north=35.0, res=0.25):
    lon1d = np.arange(west, east + res / 2.0, res)
    lat1d = np.arange(south, north + res / 2.0, res)
    lon, lat = np.meshgrid(lon1d, lat1d)
    return lat, lon


def environment(lat, lon):
    """A ridge to the north, lower pressure to the south."""
    return 1004.0 + 0.4 * (lat - 10.0) + 1.5 * np.sin(np.radians(lon * 4.0))


def modelVortex(lat, lon, clat, clon, depth, size_deg=2.0):
    d = P.distanceNm(lat, lon, clat, clon) / 60.0
    return -depth * np.exp(-(d / size_deg) ** 2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_profile():
    print("\ntest_profile")
    storm = typhoon()
    r, d = P.pressureDeficit(storm)
    check("the deficit is largest at the center",
          d[0] == d.max() and d[0] > 0.0, "%.1f" % d[0])
    check("and never rises outward", bool(np.all(np.diff(d) <= 1e-9)))
    check("it reaches zero at the outer radius", abs(d[-1]) < 1e-12)
    slope = abs(d[-2] - d[-1]) / (r[-1] - r[-2])
    check("with no kink there - the winds taper first", slope < 1e-4,
          "%.2e mb/nm" % slope)
    weak = P.pressureDeficit(typhoon(vmax=40.0))[1][0]
    check("a stronger storm is deeper", d[0] > 3.0 * weak,
          "%.1f vs %.1f" % (d[0], weak))

    real = realStorms()
    if real:
        lee, _ = real["lee"]
        krovanh, _ = real["krovanh"]
        leeDef = P.pressureDeficit(lee)[1][0]
        krDef = P.pressureDeficit(krovanh)[1][0]
        check("a real 105 kt hurricane's profile is 50-110 mb deep",
              50.0 < leeDef < 110.0, "%.1f" % leeDef)
        check("a real 35 kt tropical storm's is 5-20 mb",
              5.0 < krDef < 20.0, "%.1f" % krDef)


def test_anchor_on_real_warnings():
    print("\ntest_anchor_on_real_warnings")
    real = realStorms()
    if not real:
        print("  skip TCWind_JTWC not importable")
        return
    # Every real warning with a pressure anchors inside the limits against a
    # plausible local environment: 1012 mb for the hurricanes, 1005 mb for
    # tropical storms in the monsoon trough.
    for name, (storm, bulletin) in real.items():
        if not bulletin:
            continue
        env = 1012.0 if storm["vmax"] >= 64 else 1005.0
        scale, note = P.anchorScale(storm, bulletin, pEnv=env)
        check("%s (%d kt, %d mb) anchors: %s"
              % (name, storm["vmax"], bulletin, note),
              note.startswith("anchored"), "scale %.2f" % scale)

    storm, bulletin = real["lee"]
    scale, _ = P.anchorScale(storm, bulletin, pEnv=1012.0)
    deficit = P.pressureDeficit(storm)[1][0]
    check("the anchored tau-0 central pressure is the bulletin's",
          abs((1012.0 - scale * deficit) - bulletin) < 1e-9)
    check("no bulletin pressure leaves it unscaled",
          P.anchorScale(storm, None)[0] == 1.0)


def test_relocation():
    print("\ntest_relocation")
    lat, lon = grid()
    env = environment(lat, lon)
    # The model has the typhoon 220 nm northeast of the warning, too weak.
    modelLat, modelLon = 21.5, 140.5
    background = env + modelVortex(lat, lon, modelLat, modelLon, 25.0)
    storm = typhoon(19.5, 137.5)
    out, report = P.relocateStorms(background, lat, lon, [storm])
    r = report[0]

    i, j = np.unravel_index(np.argmin(out), out.shape)
    check("the low is now at the warning position",
          P.distanceNm(lat[i, j], lon[i, j], 19.5, 137.5) <= 15.0,
          "%.2fN %.2fE" % (lat[i, j], lon[i, j]))
    check("the background's own low was found",
          r["background"] is not None and
          P.distanceNm(r["background"][0], r["background"][1],
                       modelLat, modelLon) <= 20.0, str(r["background"]))
    check("and reported as about 220 nm off",
          180.0 < r["offsetNm"] < 260.0, "%.0f nm" % (r["offsetNm"] or -1))

    # Where the model had it is back to the environment (no second low).
    k = np.unravel_index(np.argmin(P.distanceNm(lat, lon, modelLat,
                                                modelLon)), lat.shape)
    implanted = P.implantVortex(env, lat, lon, storm, r["scale"])
    check("no low is left where the model had it",
          abs(out[k] - implanted[k]) < 2.0,
          "%.1f vs %.1f" % (out[k], implanted[k]))

    far = P.distanceNm(lat, lon, 20.5, 139.0) > 900.0
    check("far from both, the field is untouched",
          float(np.max(np.abs(out[far] - background[far]))) < 1e-9)
    check("the warning's vortex is much deeper than the model's",
          r["deficitMb"] > 40.0, "%.1f" % r["deficitMb"])


def test_removal_leaves_no_ripple():
    print("\ntest_removal_leaves_no_ripple")
    # Where the gradient is slack, a 0.15 mb ripple moves an isobar by half a
    # degree - jagged isobars.  Straight-line interpolation between ring
    # means of a curved profile left exactly that ripple, repeating every
    # ring width; crediting rings to their points' mean radius and a monotone
    # cubic between them is what removes it.
    lat, lon = grid()
    env = environment(lat, lon)
    background = env + modelVortex(lat, lon, 21.5, 140.5, 25.0)
    hit = P.findBackgroundCenter(background, lat, lon, 19.5, 137.5)
    i, j, _ = hit
    err = P.removeVortex(background, lat, lon, i, j) - env
    zone = P.distanceNm(lat, lon, lat[i, j], lon[i, j]) <= P.REMOVE_RADIUS_NM
    check("the old vortex comes out to within 0.12 mb everywhere",
          float(np.abs(err[zone]).max()) < 0.12,
          "%.3f mb" % float(np.abs(err[zone]).max()))
    core = P.distanceNm(lat, lon, lat[i, j], lon[i, j]) <= 60.0
    check("including its core", float(np.abs(err[core]).max()) < 0.05,
          "%.3f mb" % float(np.abs(err[core]).max()))
    jump = np.maximum(np.abs(np.diff(err, axis=0))[:, :-1],
                      np.abs(np.diff(err, axis=1))[:-1, :])
    check("with no gridpoint-scale ripple left behind",
          float(jump[zone[:-1, :-1]].max()) < 0.1,
          "%.3f mb" % float(jump[zone[:-1, :-1]].max()))

    x = np.linspace(0.0, 10.0, 7)
    y = np.array([-25.0, -20.0, -12.0, -5.0, -1.5, -0.2, 0.0])
    fine = P.pchip(np.linspace(0.0, 10.0, 200), x, y)
    check("the cubic between rings never overshoots a monotone profile",
          bool(np.all(np.diff(fine) >= -1e-12)) and fine.min() >= -25.0
          and fine.max() <= 0.0)


def test_anchored_at_tau0():
    print("\ntest_anchored_at_tau0")
    # A grid point exactly on the center, so the central value is exact.
    lat, lon = grid(res=0.5)
    storm = typhoon(20.0, 140.0, vmax=90.0)
    background = environment(lat, lon) + modelVortex(lat, lon, 21.0, 141.0,
                                                     15.0)
    storm["anchor"] = (dict(storm), 945)
    out, report = P.relocateStorms(background, lat, lon, [storm])
    r = report[0]
    check("at tau 0 the central pressure is the bulletin's",
          abs(r["centralMb"] - 945.0) < 0.01, "%.2f" % r["centralMb"])
    check("anchored against the local environment, not 1010",
          abs(r["envMb"] - 1010.0) > 1.0, "%.1f" % r["envMb"])
    check("and the anchor is reported", r["anchorNote"].startswith("anchored"),
          r["anchorNote"])


def test_no_background_low():
    print("\ntest_no_background_low")
    lat, lon = grid()
    env = environment(lat, lon)
    out, report = P.relocateStorms(env, lat, lon, [typhoon()])
    r = report[0]
    check("with no low to remove, nothing is removed",
          r["background"] is None and r["removedMb"] == 0.0)
    check("and the warning's vortex still goes in",
          float(out.min()) < float(env.min()) - 30.0)


def test_partial_low_on_the_edge():
    print("\ntest_partial_low_on_the_edge")
    lat, lon = grid(south=20.0)
    background = environment(lat, lon) + modelVortex(lat, lon, 19.0, 137.0,
                                                     25.0)
    out, report = P.relocateStorms(background, lat, lon,
                                   [typhoon(20.5, 137.5)])
    check("a low cut off by the field's edge is not 'removed' half-way",
          report[0]["background"] is None, str(report[0]["background"]))


def test_two_storms():
    print("\ntest_two_storms")
    lat, lon = grid(west=120.0, east=175.0)
    background = (environment(lat, lon) +
                  modelVortex(lat, lon, 18.0, 131.0, 20.0) +
                  modelVortex(lat, lon, 24.0, 161.0, 12.0))
    a = typhoon(17.0, 129.0, 110.0, "A")
    b = typhoon(25.0, 163.0, 60.0, "B")
    out, report = P.relocateStorms(background, lat, lon, [a, b])
    near = [P.distanceNm(r["background"][0], r["background"][1],
                         *pos) if r["background"] else 1e9
            for r, pos in zip(report, ((18.0, 131.0), (24.0, 161.0)))]
    check("each storm takes its own background low",
          max(near) < 30.0, str(["%.0f" % n for n in near]))
    for storm in (a, b):
        dist = P.distanceNm(lat, lon, storm["lat"], storm["lon"])
        local = np.where(dist <= 90.0, out, np.inf)
        i, j = np.unravel_index(np.argmin(local), local.shape)
        check("storm %s's low is at its warning position" % storm["name"],
              P.distanceNm(lat[i, j], lon[i, j], storm["lat"],
                           storm["lon"]) <= 15.0)


def test_dateline():
    print("\ntest_dateline")
    # A grid in -180..180 with the jump at 180, a storm sitting on it.
    lat, lon360 = grid(west=165.0, east=195.0)
    lon = ((lon360 + 180.0) % 360.0) - 180.0
    background = environment(lat, lon360) + modelVortex(lat, lon, 21.0,
                                                        -178.0, 20.0)
    storm = typhoon(20.0, 179.5)
    out, report = P.relocateStorms(background, lat, lon, [storm])
    i, j = np.unravel_index(np.argmin(out), out.shape)
    check("the low lands on the warning position across the dateline",
          P.distanceNm(lat[i, j], lon[i, j], 20.0, 179.5) <= 15.0,
          "%.2f %.2f" % (lat[i, j], lon[i, j]))
    check("the model's low across the dateline was found and removed",
          report[0]["background"] is not None and
          report[0]["offsetNm"] < 200.0, str(report[0]["background"]))


def test_warnings_to_storms():
    print("\ntest_warnings_to_storms")
    import calendar
    from synth_warning import jtwcWarning
    W = P.trackTools()
    check("TCWind_JTWC is found for its parser", W is not None)
    if W is None:
        return
    t0 = calendar.timegm((2026, 10, 2, 18, 0, 0))
    track = [(0, 19.0, 138.0, 100, 150), (12, 20.0, 137.0, 110, 160),
             (24, 21.0, 136.0, 110, 160), (48, 23.0, 134.0, 95, 180)]
    text = {"NFDTCPWP1": jtwcWarning(t0, track, 948),
            "NFDTCPWP2": "WTPN32 PGTW 021500\nnothing a parser can use\n",
            "NFDTCPWP3": jtwcWarning(t0 - 30 * 3600, track, 990, "OLDONE")}
    warnings, notes = P.readWarnings(nowSecs=t0 + 4 * 3600, tools=W,
                                     retrieve=text.get)
    check("one live warning; the old one dropped, the bad one noted",
          [w["name"] for w in warnings] == ["TESTER"] and len(notes) == 1,
          "%s %s" % ([w["name"] for w in warnings], notes))

    storms, notes = P.stormsAt(warnings, t0 + 6 * 3600, W)
    check("one storm at the chart time", len(storms) == 1 and not notes,
          str(notes))
    if storms:
        s = storms[0]
        check("interpolated along the track to the chart time",
              abs(s["lat"] - 19.5) < 1e-6 and abs(s["lon"] - 137.5) < 1e-6
              and abs(s["vmax"] - 105.0) < 1e-6,
              "%.2f %.2f %.1f" % (s["lat"], s["lon"], s["vmax"]))
        check("anchored to the tau-0 storm and its pressure",
              s.get("anchor") and s["anchor"][1] == 948.0 and
              abs(s["anchor"][0]["lat"] - 19.0) < 1e-6)
    storms, notes = P.stormsAt(warnings, t0 - 6 * 3600, W)
    check("a chart before the warning starts is left out, and said so",
          not storms and len(notes) == 1 and "does not cover" in notes[0],
          str(notes))
    storms, notes = P.stormsAt(warnings, t0 + 49 * 3600, W)
    check("and so is one after it ends", not storms and len(notes) == 1)

    noPressure = {"X": jtwcWarning(t0, track, None)}
    warnings, _ = P.readWarnings(nowSecs=t0, tools=W, pils=["X"],
                                 retrieve=noPressure.get)
    storms, _ = P.stormsAt(warnings, t0, W)
    check("no bulletin pressure: still placed, just unanchored",
          len(storms) == 1 and "anchor" not in storms[0])

    original = P.trackTools
    P.trackTools = lambda: None
    try:
        warnings, notes = P.readWarnings(nowSecs=t0, retrieve=text.get)
    finally:
        P.trackTools = original
    check("without TCWind_JTWC: nothing moved, and the reason given",
          warnings == [] and len(notes) == 1 and "not installed" in notes[0],
          str(notes))

    entry = {"name": "TESTER", "lat": 19.5, "lon": 137.5,
             "background": (21.5, 140.5), "offsetNm": 212.0,
             "centralMb": 949.6, "anchorNote": "anchored to 948 mb",
             "inGap": True}
    line = P.describeRelocation(entry)
    check("status line says where, how deep, and how far the model was off",
          "19.5N 137.5E" in line and "950 mb" in line and "212 nm" in line
          and "21.5N 140.5E" in line, line)
    entry.update(background=None, inGap=False, lon=-178.0,
                 anchorNote="anchor 2.40 outside 0.5-2.0 - unanchored")
    line = P.describeRelocation(entry)
    check("and says when it found no model low, the center is in the grid, "
          "or the anchor was refused",
          "no model low" in line and "GFE grid" in line and
          "178.0W" in line and "unanchored" in line, line)


def main():
    test_profile()
    test_anchor_on_real_warnings()
    test_relocation()
    test_removal_leaves_no_ripple()
    test_anchored_at_tau0()
    test_no_background_low()
    test_partial_low_on_the_edge()
    test_two_storms()
    test_dateline()
    test_warnings_to_storms()
    print("")
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
