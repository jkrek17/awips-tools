"""fsu_digitize: the geometry of the FSU phase plot digitizer on a
synthetic plot drawn with matplotlib in FSU's layout (1024 x 768, frame,
outward ticks, shading in FSU's hue families, a black polyline with
outlined discs, white X on forecast markers, the C ring around the
analysis marker and the Z glyph at the end), and the tick and header
reading on one of the archived FSU plots (the font templates are FSU's).
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import numpy as np
import pytest

import fsu_digitize as fd

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Arc, Ellipse  # noqa: E402

W, H = 1024, 768
FRAME = (139, 884, 90, 655)  # left, right, top, bottom in display pixels (top-left origin)
XLIM, YLIM = (-60.0, 220.0), (-15.0, 130.0)
# hour, x, y, radius (px), fill color: two analysis markers, the analysis (C), five forecasts
TRACK = [(-12, -30.0, 8.0, 5, (162, 0, 201)), (-6, 0.0, 6.0, 6, (30, 60, 255)),
         (0, 30.0, 4.0, 8, (0, 201, 201)), (6, 60.0, 2.0, 9, (0, 221, 0)),
         (12, 95.0, 12.0, 10, (231, 221, 50)), (18, 110.0, 40.0, 11, (241, 131, 40)),
         (24, 80.0, 75.0, 12, (241, 0, 131)), (30, 40.0, 100.0, 12, (251, 60, 60))]


def draw_fsu_like(path: Path) -> dict:
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    l, r, t, b = FRAME
    ax = fig.add_axes([l / W, 1 - b / H, (r - l) / W, (b - t) / H])
    ax.set_xlim(*XLIM)
    ax.set_ylim(*YLIM)
    # shading in FSU's hue families, changing at x = 0 and y = 10 like phase1
    ax.add_patch(plt.Rectangle((XLIM[0], 10), -XLIM[0], YLIM[1] - 10, color=(150 / 255, 150 / 255, 1), zorder=0))
    ax.add_patch(plt.Rectangle((0, 10), XLIM[1], YLIM[1] - 10, color=(1, 120 / 255, 1), zorder=0))
    ax.add_patch(plt.Rectangle((XLIM[0], YLIM[0]), -XLIM[0], 10 - YLIM[0], color=(0.8, 0.8, 0.8), zorder=0))
    ax.add_patch(plt.Rectangle((0, YLIM[0]), XLIM[1], 10 - YLIM[0], color=(1, 150 / 255, 150 / 255), zorder=0))
    for s in ax.spines.values():
        s.set_linewidth(1.5)
    ax.set_xticks(np.arange(-50, 201, 50))
    ax.set_yticks(np.arange(-10, 121, 10))
    ax.tick_params(direction="out", length=0)  # ticks drawn below, unsnapped, where the data put them
    sx = (r - l) / (XLIM[1] - XLIM[0])  # px per data unit
    sy = (b - t) / (YLIM[1] - YLIM[0])
    for v in np.arange(-50, 201, 50):
        ax.plot([v, v], [YLIM[0], YLIM[0] - 5 / sy], color="k", lw=1.0, clip_on=False, snap=False,
                solid_capstyle="butt")
    for v in np.arange(-10, 121, 10):
        ax.plot([XLIM[0], XLIM[0] - 5 / sx], [v, v], color="k", lw=1.0, clip_on=False, snap=False,
                solid_capstyle="butt")
    xs, ys = [p[1] for p in TRACK], [p[2] for p in TRACK]
    ax.plot(xs, ys, color="k", lw=1.5, zorder=2, solid_capstyle="round")
    for k, (h, x, y, rad, col) in enumerate(TRACK):
        # patches, not scatter markers: Agg snaps marker offsets to whole pixels
        ax.add_patch(Ellipse((x, y), 2 * rad / sx, 2 * rad / sy, facecolor=np.array(col) / 255, edgecolor="k",
                             lw=1.0, zorder=3 + k))
        if h > 0:
            q = 0.62 * rad
            for s1 in (-1, 1):
                ax.plot([x - q / sx, x + q / sx], [y - s1 * q / sy, y + s1 * q / sy], color="white", lw=0.8,
                        zorder=3.5 + k, snap=False)
    # C ring (open on the right) around the analysis marker
    _, xc, yc, rc, _ = TRACK[2]
    ax.add_patch(Arc((xc, yc), 2 * 18 / sx, 2 * 21 / sy, theta1=60, theta2=300, lw=1.8, color="k", zorder=2.5))
    # Z glyph centered on the last marker: bars 21.5 px above and below, 33 px long
    _, xz, yz, rz, _ = TRACK[-1]
    hx, hy = 16.5 / sx, 21.5 / sy
    ax.plot([xz - hx, xz + hx, xz - hx, xz + hx], [yz + hy, yz + hy, yz - hy, yz - hy], color="k", lw=1.8,
            zorder=2.5)
    fig.savefig(path, dpi=100, facecolor="white")
    trans = ax.transData
    plt.close(fig)

    def to_px(x, y):  # data -> pixel-index coordinates (row down)
        X, Y = trans.transform((x, y))
        return X - 0.5, (H - Y) - 0.5
    return {"to_px": to_px, "sx": sx, "sy": sy}


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    p = tmp_path_factory.mktemp("fsu") / "synthetic_phase1.png"
    info = draw_fsu_like(p)
    info["rgb"] = fd.load_rgb(p)
    return info


def test_frame_and_ticks(synth):
    rgb, to_px = synth["rgb"], synth["to_px"]
    fr = fd.find_frame(rgb)
    l, r, t, b = FRAME
    assert abs(fr.left_out - l) <= 2 and abs(fr.right_out - r) <= 2
    assert abs(fr.top_out - t) <= 2 and abs(fr.bottom_out - b) <= 2
    xt, yt = fd.find_ticks(rgb, fr)
    want_x = [to_px(v, 0)[0] for v in range(-50, 201, 50)]
    want_y = sorted(to_px(0, v)[1] for v in range(-10, 121, 10))
    assert len(xt) == len(want_x) and len(yt) == len(want_y)
    assert np.max(np.abs(np.array(xt) - want_x)) < 0.6
    assert np.max(np.abs(np.array(sorted(yt)) - want_y)) < 0.6


def test_fit_axis_rejects_a_misread_label():
    pairs = [(100.0, "-50"), (200.0, "0"), (300.0, "50"), (400.0, "100"), (500.0, "190")]  # last misread
    a = fd.fit_axis(pairs)
    assert a.b == pytest.approx(0.5)
    assert a.value(200.0) == pytest.approx(0.0)
    assert any(t == "190" for _, t in a.rejected)


def test_discs_found_at_their_centers(synth):
    rgb, to_px = synth["rgb"], synth["to_px"]
    fr = fd.find_frame(rgb)
    area = fd.plot_area_mask(rgb, fr, fd.find_inset(rgb, fr))
    discs = fd.detect_discs(rgb, area)
    fd.disc_features(rgb, discs, fd.pixel_classes(rgb))
    for h, x, y, rad, col in TRACK:
        px, py = to_px(x, y)
        d = min(discs, key=lambda q: math.hypot(q.x - px, q.y - py))
        assert math.hypot(d.x - px, d.y - py) < 0.75, (h, d)
        assert abs(d.r - rad) < 1.6  # the fitted radius is the fill's, inside the outline
        if h > 0:
            assert d.xmark >= fd.XCUT
        else:
            assert d.xmark < fd.XCUT
    assert len(discs) == len(TRACK)


def test_trace_times_every_marker(synth):
    rgb, to_px = synth["rgb"], synth["to_px"]
    fr = fd.find_frame(rgb)
    xt, yt = fd.find_ticks(rgb, fr)
    ax = fd.fit_axis(list(zip(xt, [str(v) for v in range(-50, 201, 50)])))
    ay = fd.fit_axis(list(zip(sorted(yt), [str(v) for v in range(120, -11, -10)])))
    hdr = {"start_h": -12, "end_h": 30, "future": False}
    cyc = dt.datetime(2026, 10, 1, 12)
    res = fd.trace(rgb, fr, ax, ay, hdr, cyc)
    assert res["quality"] == "closed"
    assert res["spacing_h"] == 6
    got = {p["hour"]: p for p in res["points"]}
    for h, x, y, rad, col in TRACK:
        if h < 0:
            continue  # the walk from Z stops at C (hour 0) on a closed plot
        assert h in got, h
        assert got[h]["x"] == pytest.approx(x, abs=0.6 / synth["sx"] + 0.05)
        assert got[h]["y"] == pytest.approx(y, abs=0.6 / synth["sy"] + 0.05)
        assert got[h]["valid"] == (cyc + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ")
        assert got[h]["ex"] > 0 and got[h]["ey"] > 0


# the 12 h marker lies wholly under the larger 18 h one
TRACK_HIDDEN = TRACK[:4] + [(12, 95.0, 12.0, 7, (231, 221, 50)), (18, 96.0, 13.0, 11, (241, 131, 40))] + TRACK[6:]


def test_hidden_marker_gets_no_time(tmp_path):
    """A marker drawn wholly under the next one cannot be seen. The walks
    from Z and from C must not shift the times across it: the hidden hour
    gets no point, and every hour that is timed carries the right values."""
    global TRACK
    saved = TRACK
    try:
        TRACK = TRACK_HIDDEN
        p = tmp_path / "hidden.png"
        draw_fsu_like(p)
        rgb = fd.load_rgb(p)
    finally:
        TRACK = saved
    fr = fd.find_frame(rgb)
    xt, yt = fd.find_ticks(rgb, fr)
    ax = fd.fit_axis(list(zip(xt, [str(v) for v in range(-50, 201, 50)])))
    ay = fd.fit_axis(list(zip(sorted(yt), [str(v) for v in range(120, -11, -10)])))
    res = fd.trace(rgb, fr, ax, ay, {"start_h": -12, "end_h": 30, "future": False}, None)
    assert res["quality"] != "closed"
    want = {h: (x, y) for h, x, y, _, _ in TRACK_HIDDEN}
    hours = [p["hour"] for p in res["points"]]
    assert 12 not in hours  # the hidden marker gets no time, and no other marker takes its hour
    assert len(hours) >= 4
    for p in res["points"]:
        assert p["x"] == pytest.approx(want[p["hour"]][0], abs=0.4)
        assert p["y"] == pytest.approx(want[p["hour"]][1], abs=0.4)


DATA = Path(__file__).resolve().parents[2] / "realtime" / "data"
WPAC1 = DATA / "2026100200" / "WPAC" / "fsu_phase1.png"


@pytest.mark.skipif(not WPAC1.exists(), reason="archived FSU plot not present")
def test_reads_ticks_and_header_of_an_fsu_plot():
    rgb = fd.load_rgb(WPAC1)
    fr, ax, ay, lab = fd.read_axes(rgb)
    assert [w for _, w in lab["x_labels"]] == ["-50", "0", "50", "100", "150", "200"]
    assert [w for _, w in lab["y_labels"]] == [str(v) for v in range(130, -11, -10)]
    assert ax.resid_px < 0.3 and ay.resid_px < 0.3
    assert ax.b == pytest.approx(50 / 119.4, rel=0.01)
    hdr = fd.read_header(rgb)
    assert (hdr["start_h"], hdr["end_h"], hdr["future"]) == (-96, 144, False)


@pytest.mark.skipif(not WPAC1.exists(), reason="archived FSU plot not present")
def test_embedded_templates_match_the_sources():
    built = fd.build_templates(DATA)
    emb = fd.templates()
    for kind in ("tick", "header"):
        assert set(built[kind]) == set(emb[kind])
