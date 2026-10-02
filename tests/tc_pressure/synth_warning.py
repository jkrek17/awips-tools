"""Write a JTWC warning for a made-up storm, in the real product's layout.

Real fixtures are pinned to their own dates; the end-to-end checks need a
warning valid at the chart they draw, so this writes one with the same
lines TCWind_JTWC's parser reads off the real ones.

    jtwcWarning(tau0Epoch, [(tauHours, lat, lon, vmaxKt, r34Nm), ...],
                pressureMb=950, name="TESTER")
"""
import time


def _pos(lat, lon):
    lon = ((lon + 180.0) % 360.0) - 180.0
    return "%.1f%s %.1f%s" % (abs(lat), "N" if lat >= 0 else "S",
                              abs(lon), "E" if lon >= 0 else "W")


def _radii(lines, vmax, r34):
    for kt, frac in ((64, 0.35), (50, 0.6), (34, 1.0)):
        if vmax < kt + 1 or not r34:
            continue
        r = int(round(r34 * frac))
        lines.append("   RADIUS OF %03d KT WINDS - %03d NM NORTHEAST QUADRANT"
                     % (kt, r + 10))
        for quad, extra in (("SOUTHEAST", 0), ("SOUTHWEST", -10),
                            ("NORTHWEST", 0)):
            lines.append("                            %03d NM %s QUADRANT"
                         % (max(r + extra, 5), quad))


def jtwcWarning(tau0Epoch, track, pressureMb=None, name="TESTER",
                stormId="25W", number=10):
    dtg = lambda epoch: time.strftime("%d%H%MZ", time.gmtime(epoch))
    t0 = track[0]
    issued = time.strftime("%d%H00", time.gmtime(tau0Epoch + 3 * 3600))
    kind = "TYPHOON" if t0[3] >= 64 else "TROPICAL STORM"
    lines = [
        "WTPN31 PGTW %s" % issued,
        "MSGID/GENADMIN/JOINT TYPHOON WRNCEN PEARL HARBOR HI//",
        "SUBJ/%s %s (%s) WARNING NR %03d//" % (kind, stormId, name, number),
        "RMKS/",
        "1. %s %s (%s) WARNING NR %03d" % (kind, stormId, name, number),
        "   MAX SUSTAINED WINDS BASED ON ONE-MINUTE AVERAGE",
        "    ---",
        "   WARNING POSITION:",
        "   %s --- NEAR %s" % (dtg(tau0Epoch), _pos(t0[1], t0[2])),
        "     MOVEMENT PAST SIX HOURS - 300 DEGREES AT 10 KTS",
        "   PRESENT WIND DISTRIBUTION:",
        "   MAX SUSTAINED WINDS - %03d KT, GUSTS %03d KT"
        % (t0[3], t0[3] + 15),
        "   WIND RADII VALID OVER OPEN WATER ONLY",
    ]
    _radii(lines, t0[3], t0[4])
    lines += ["   REPEAT POSIT: %s" % _pos(t0[1], t0[2]), "    ---",
              "   FORECASTS:"]
    for tau, lat, lon, vmax, r34 in track[1:]:
        lines += ["   %d HRS, VALID AT:" % tau,
                  "   %s --- %s" % (dtg(tau0Epoch + tau * 3600),
                                    _pos(lat, lon)),
                  "   MAX SUSTAINED WINDS - %03d KT, GUSTS %03d KT"
                  % (vmax, vmax + 15),
                  "   WIND RADII VALID OVER OPEN WATER ONLY"]
        _radii(lines, vmax, r34)
        lines += ["   VECTOR TO NEXT POSIT: 300 DEG/ 10 KTS", "    ---"]
    lines += ["REMARKS:",
              "%s POSITION NEAR %s. %s (%s) HAS TRACKED NORTHWESTWARD."
              % (dtg(tau0Epoch + 3 * 3600), _pos(t0[1], t0[2]), kind, name)]
    if pressureMb:
        lines.append("MINIMUM CENTRAL PRESSURE AT %s IS %d MB."
                     % (dtg(tau0Epoch), pressureMb))
    lines += ["NEXT WARNINGS AT LATER.//", "NNNN", ""]
    return "\n".join(lines)
