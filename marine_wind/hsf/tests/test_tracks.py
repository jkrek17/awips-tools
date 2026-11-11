"""HSF writer low tracker (Jason 11-11: "the low tracking has not been working great").

In the 06Z 11 Nov run weak lows "ran" 50-65 kt between steps (61N63W 1005 -> 65N56W 1012 ->
63N44W; 41N179E 1011 -> 39N171E -> back east), which were jumps to other centres, and one
track bridged a 12 h gap to a low 600 nm off. The tracker now matches a whole step at once,
against where each track was heading, with speed and depth limits.

    python3 marine_wind/hsf/tests/test_tracks.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from writer import link_tracks  # noqa: E402

FAIL = []


def check(name, ok, got=None):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  %s" % (got,)))
    if not ok:
        FAIL.append(name)


def lw(la, lo, mb=1004):
    return (la, lo, mb, la, lo)


def same(t, h1, h2):
    return t[h1][0][0] == t[h2][0][0]


t = link_tracks({6: [lw(61, -63, 1005)], 12: [lw(65, -56, 1012)]})
check("a weak low does not jump ~300 nm in 6 h", not same(t, 6, 12), t)
t = link_tracks({0: [lw(50, -175, 976)], 6: [lw(51, -168, 965)]})
check("a deep low running ~45 kt keeps its track", same(t, 0, 6), t)
t = link_tracks({0: [lw(44, -64)], 6: [lw(44, -62)], 12: [], 18: [lw(38, -73)]})
check("a 12 h gap does not bridge 600 nm", not same(t, 6, 18), t)
t = link_tracks({0: [lw(44, -64)], 6: [lw(44, -62)], 12: [], 18: [lw(45, -59)]})
check("... but bridges a nearby centre", same(t, 6, 18), t)
t = link_tracks({0: [lw(62, -154, 983)], 6: [lw(62, -154, 985)], 12: [], 18: [lw(60, -154, 997)]})
check("... of like depth only", not same(t, 6, 18), t)
# heading: A runs E at ~30 kt toward B, which sits still. Next step A is at 50N33W and B at
# 52N30W; matched by distance alone from last positions, B would take A's centre
t = link_tracks({0: [lw(50, -40, 990), lw(52, -30, 1000)], 6: [lw(50, -36.5, 990), lw(52, -30, 1000)],
                 12: [lw(52, -30.5, 1000), lw(50, -33, 990)]})
a6 = [tid for tid, l in t[6] if l[2] == 990][0]
a12 = [tid for tid, l in t[12] if l[2] == 990][0]
check("each low follows its own heading", a6 == a12, t)

print("FAIL: %s" % FAIL if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
