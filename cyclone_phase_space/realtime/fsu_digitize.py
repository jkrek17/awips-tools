#!/usr/bin/env python3
"""Digitize Florida State University cyclone phase space plots.

FSU publishes its GFS cyclone phase diagrams only as 1024 x 768 images
(`N.phase1.zoom.png`: B against -V_T^L, 900-600 hPa; `N.phase2.zoom.png`:
-V_T^U against -V_T^L), which `collect_daily.py` saves beside our own
tracks as `fsu_phase1.png` and `fsu_phase2.png`. This module turns one
such image back into numbers:

1. Axes. The plot frame is found from its long dark edges, the tick
   marks from the short dark runs just outside the bottom and left
   edges, and every tick label is read by template matching against
   digit templates cut from FSU plots (`TEMPLATE_B64`, rebuilt by
   `build_templates`). A least-squares line through (tick pixel, label
   value) gives the pixel to data mapping, so nothing about the axis
   ranges is assumed; the fit residual and the equal spacing of the
   labels are checked. The mapping is cross-checked against the shaded
   background, which changes hue at -V_T^L = 0 (both plots), at B = 10 m
   (phase1) and at -V_T^U = 0 (phase2).
2. Header. The three red lines Start (A) / Current (C) / End (Z) give
   the hour offsets of the first and last trajectory point relative to
   the run; they are read with the same template matching. The run time
   itself is the collection cycle.
3. Markers. A marker is a disc filled with an intensity color, outlined
   in black; forecast markers carry a white X. Pixels are classed as
   page background (the shading is drawn from four fixed hue families:
   grey, blue, magenta, red), dark ink and marker fill; each connected
   region of fill is decomposed into circles by a gradient Hough
   transform on its boundary, refined by a least-squares circle fit.
   A disc whose center lies inside another disc (or holds another's
   center) is "crowded": markers drawn over one another form clusters
   inside which the drawing order and the hidden markers cannot be
   recovered reliably.
4. Times. FSU draws one marker every 6 h from Start to End (the spacing
   is confirmed when a walk closes, see below). The end marker is found
   by its Z (bars above and below it and a diagonal), the analysis
   marker by its C (an open ring around it), and the first marker of a
   future cyclone by its A. The trajectory is walked from Z backward,
   from C forward and from A forward along the black polyline, one
   marker at a time; each step must be the only candidate left after
   checks on the line between the two discs, their drawing order, the
   X (forecast markers after C carry one, analysis markers do not) and,
   where no line can be seen, their size and color. A walk from Z that
   reaches C (or one from A that reaches Z) after exactly the number of
   steps the header implies is "closed"; one that reaches it with the
   wrong count means a marker is hidden, and its times are dropped. A
   walk stops at a cluster, under the inset map, or where the next step
   is ambiguous; markers no walk reaches get no time ("untimed").
5. Error. Each digitized point carries an error estimate in data units:
   0.7 px of center uncertainty, plus a quarter of the marker radius for
   a crowded disc or a tenth of it times the covered share of its rim,
   times the axis scale.
6. The two plots together (digitize_pair). phase1 and phase2 share
   -V_T^L, the intensity color and the marker size at every hour, so an
   hour timed on both is "verified" when the two -V_T^L agree, and
   "inconsistent" (dropped, with the rest of the offending walk) when
   they do not; an hour timed on one plot only is carried to the other
   plot's matching untimed marker when exactly one matches.

Only the points from the analysis (C, 0 h) onward are of use for a
comparison with a forecast track; analysis points before C are kept with
negative hours when they are timed.

Command line, for a quick look at one plot:

    python3 fsu_digitize.py data/2026100200/WPAC/fsu_phase1.png --cycle 2026100200 [--debug out.png]
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

DEBUG = False
XCUT = 0.25  # X strength above which a disc is a forecast marker
STEP_H = 6  # FSU marker spacing (checked against the marker counts)
DARK_LUM = 80  # luminance below which a pixel is dark ink (frame, ticks, outline, text)


# ------------------------------------------------------------------ image basics
def load_rgb(path) -> np.ndarray:
    """RGB image as int16 (H, W, 3)."""
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB")).astype(np.int16)


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb.mean(axis=2)


def label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected component labels of a boolean mask (0 = background,
    1..n), by run-length union-find; no scipy needed."""
    mask = np.asarray(mask, bool)
    h, w = mask.shape
    pad = np.zeros((h, w + 2), np.int8)
    pad[:, 1:-1] = mask
    d = np.diff(pad, axis=1)
    ys, xs = np.nonzero(d == 1)
    _, xe = np.nonzero(d == -1)
    n = len(xs)
    lab = np.zeros((h, w), np.int32)
    if n == 0:
        return lab, 0
    parent = np.arange(n)

    def find(i):
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    ptr = np.searchsorted(ys, np.arange(h + 1))
    xs_l = xs.tolist()
    xe_l = xe.tolist()
    for y in range(1, h):
        i, i1 = int(ptr[y - 1]), int(ptr[y])
        j, j1 = int(ptr[y]), int(ptr[y + 1])
        while i < i1 and j < j1:
            # runs [s, e) on adjacent rows touch (8-connected) if s_i <= e_j and s_j <= e_i
            if xs_l[i] <= xe_l[j] and xs_l[j] <= xe_l[i]:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
            if xe_l[i] < xe_l[j]:
                i += 1
            else:
                j += 1
    roots = np.array([find(i) for i in range(n)])
    _, comp = np.unique(roots, return_inverse=True)
    for k in range(n):
        lab[ys[k], xs_l[k]:xe_l[k]] = comp[k] + 1
    return lab, int(comp.max()) + 1


def components(mask: np.ndarray, min_px: int = 1) -> list[dict]:
    """Connected components as dicts: ys, xs (pixel indices), bbox
    (y0, y1, x0, x1, inclusive-exclusive), n."""
    lab, n = label(mask)
    if n == 0:
        return []
    ys, xs = np.nonzero(lab)
    ids = lab[ys, xs]
    order = np.argsort(ids, kind="stable")
    ys, xs, ids = ys[order], xs[order], ids[order]
    cut = np.searchsorted(ids, np.arange(1, n + 2))
    out = []
    for k in range(n):
        yy, xx = ys[cut[k]:cut[k + 1]], xs[cut[k]:cut[k + 1]]
        if len(yy) < min_px:
            continue
        out.append({"ys": yy, "xs": xx, "n": len(yy),
                    "bbox": (int(yy.min()), int(yy.max()) + 1, int(xx.min()), int(xx.max()) + 1)})
    return out


def dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
    """Square (2r+1) dilation."""
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue
            out |= shift(mask, dy, dx)
    return out


def erode(mask: np.ndarray, r: int = 1) -> np.ndarray:
    return ~dilate(~mask, r)


def shift(a: np.ndarray, dy: int, dx: int, fill=False) -> np.ndarray:
    """a moved by (dy, dx): out[y, x] = a[y - dy, x - dx]."""
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    out[ys0:ys1, xs0:xs1] = a[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def runs_1d(row: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) runs of True in a 1-D boolean array."""
    d = np.diff(np.r_[0, row.astype(np.int8), 0])
    return list(zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()))


# ------------------------------------------------------------------ axes frame and ticks
@dataclass
class Frame:
    """Plot frame: the dark edge lines, outer and inner pixel rows/columns."""
    left_out: int
    left_in: int
    right_in: int
    right_out: int
    top_out: int
    top_in: int
    bottom_in: int
    bottom_out: int


def _group(idx: list[int], gap: int = 1) -> list[list[int]]:
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][-1] <= gap:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def find_frame(rgb: np.ndarray) -> Frame:
    """The axes frame: the bottom edge is the longest dark horizontal run
    in the lower part of the image; the left and right edges are the
    outermost columns whose dark run reaches the bottom edge from at
    least 150 px above; the top edge is the row above them with the most
    dark pixels between the side edges (the inset map can hide a part of
    it, never most of it)."""
    dark = luminance(rgb) < DARK_LUM
    h, w = dark.shape
    best = np.zeros(h, int)
    for y in range(int(0.4 * h), h):
        r = runs_1d(dark[y])
        best[y] = max((e - s for s, e in r), default=0)
    yb = int(np.argmax(best))
    if best[yb] < 0.3 * w:
        raise ValueError("no bottom frame edge")
    rows = [y for y in range(yb - 3, yb + 4) if best[y] >= 0.9 * best[yb]]
    rows = next(g for g in _group(rows) if yb in g)
    b_in, b_out = min(rows), max(rows)
    # columns with a dark run ending at the bottom edge
    above = dark[:b_in][::-1]  # row 0 here is the row just above the bottom edge
    first_gap = np.where(above.all(axis=0), above.shape[0], np.argmin(above, axis=0))
    cols = np.nonzero(first_gap >= 150)[0].tolist()
    if len(cols) < 2:
        raise ValueError("no side frame edges")
    groups = _group(cols)
    lg, rg = groups[0], groups[-1]
    l_out, l_in = min(lg), max(lg)
    r_in, r_out = min(rg), max(rg)
    cnt = dark[: b_in - 150, l_in + 1:r_in].sum(axis=1)
    yt = int(np.argmax(cnt))
    trow = [y for y in range(max(0, yt - 3), yt + 4) if cnt[y] >= 0.8 * cnt[yt]]
    trow = next(g for g in _group(trow) if yt in g)
    return Frame(l_out, l_in, r_in, r_out, min(trow), max(trow), b_in, b_out)


def _peaks(profile: np.ndarray, thr: float) -> list[tuple[float, float]]:
    """(centroid, total) of each run of profile above thr."""
    out = []
    for s, e in runs_1d(profile > thr):
        p = profile[s:e]
        out.append((float((np.arange(s, e) * p).sum() / p.sum()), float(p.sum())))
    return out


def find_ticks(rgb: np.ndarray, fr: Frame) -> tuple[list[float], list[float]]:
    """Tick mark positions (pixel centroids, sub-pixel): x ticks hang below
    the bottom edge, y ticks stick out left of the left edge."""
    ink = 255.0 - luminance(rgb)
    prof = ink[fr.bottom_out + 2:fr.bottom_out + 5, fr.left_out - 2:fr.right_out + 3].sum(axis=0)
    xt = [c + fr.left_out - 2 for c, _ in _peaks(prof, 150.0)]
    prof = ink[fr.top_out - 2:fr.bottom_out + 3, fr.left_out - 5:fr.left_out - 2].sum(axis=1)
    yt = [c + fr.top_out - 2 for c, _ in _peaks(prof, 150.0)]
    return xt, yt


# ------------------------------------------------------------------ glyphs and templates
def glyphs(ink: np.ndarray, y0: int, y1: int, x0: int, x1: int, thr: float = 90.0,
           min_px: int = 3) -> list[dict]:
    """Glyph components of an ink image inside a box, left to right; each
    has its own ink crop ('img', 0..1) and its box in image pixels."""
    sub = ink[y0:y1, x0:x1]
    out = []
    for c in components(sub > thr, min_px=min_px):
        a0, a1, b0, b1 = c["bbox"]
        m = np.zeros((a1 - a0, b1 - b0), bool)
        m[c["ys"] - a0, c["xs"] - b0] = True
        img = np.where(dilate(m, 1), sub[a0:a1, b0:b1], 0.0) / 255.0
        out.append({"img": img, "y0": a0 + y0, "y1": a1 + y0, "x0": b0 + x0, "x1": b1 + x0,
                    "cy": (a0 + a1) / 2 + y0, "cx": (b0 + b1) / 2 + x0})
    # merge components that share most of their columns (none for these fonts, but safe)
    out.sort(key=lambda g: g["x0"])
    return out


def _blur(a: np.ndarray) -> np.ndarray:
    """1-2-1 smoothing in both directions, padded by one pixel, so that the
    antialiasing of a glyph drawn at another sub-pixel offset matters less."""
    p = np.pad(a, 2)
    p = (p[:-2] + 2 * p[1:-1] + p[2:]) / 4.0
    p = (p[:, :-2] + 2 * p[:, 1:-1] + p[:, 2:]) / 4.0
    return p


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Best normalized correlation of two small ink images, both smoothed,
    over shifts of up to one pixel (they are padded to a common size)."""
    a, b = _blur(a), _blur(b)
    h = max(a.shape[0], b.shape[0]) + 2
    w = max(a.shape[1], b.shape[1]) + 2
    A = np.zeros((h, w))
    A[1:1 + a.shape[0], 1:1 + a.shape[1]] = a
    best = -1.0
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            if dy + b.shape[0] > h or dx + b.shape[1] > w:
                continue
            B = np.zeros((h, w))
            B[dy:dy + b.shape[0], dx:dx + b.shape[1]] = b
            num = (A * B).sum()
            den = math.sqrt((A * A).sum() * (B * B).sum())
            if den > 0:
                best = max(best, num / den)
    return best


def classify(g: dict, templates: dict[str, list[np.ndarray]], min_score: float = 0.80) -> tuple[str, float]:
    """Best template for one glyph: (character, score); '?' when no
    template of about the same size scores min_score. A flat bar (at
    most 3 px tall, at least 7 px wide) is the minus sign."""
    img = g["img"]
    if img.shape[0] <= 3 and img.shape[1] >= 7:
        return "-", 1.0
    best, bc = -1.0, "?"
    for ch, variants in templates.items():
        for t in variants:
            if abs(t.shape[0] - img.shape[0]) > 2 or abs(t.shape[1] - img.shape[1]) > 2:
                continue
            s = _ncc(img, t)
            if s > best:
                best, bc = s, ch
    return (bc, best) if best >= min_score else ("?", best)


def read_word(gl: list[dict], templates: dict[str, np.ndarray]) -> tuple[str, float]:
    """Glyphs to a string and the lowest glyph score."""
    s, worst = "", 1.0
    for g in gl:
        ch, sc = classify(g, templates)
        s += ch
        worst = min(worst, sc)
    return s, worst


def red_ink(rgb: np.ndarray) -> np.ndarray:
    """Ink of the red header text: R above the mean of G and B."""
    return np.clip(rgb[..., 0] - (rgb[..., 1] + rgb[..., 2]) / 2.0, 0, 255).astype(float)


def dark_ink(rgb: np.ndarray) -> np.ndarray:
    """Ink of black text on a light page."""
    return 255.0 - luminance(rgb)


def header_layout(rgb: np.ndarray) -> dict:
    """Where the three red header lines are: the timestamp column (the
    widest block of red text in the top rows, 'HHZDDMONYYYY'), the digit
    rows of each line, and the width of each line's first word (Start,
    Current or End)."""
    red = red_ink(rgb)[:95] > 80
    colp = red[15:85].sum(axis=0)
    segs = []
    for s, e in runs_1d(colp > 0):
        if segs and s - segs[-1][1] <= 7:
            segs[-1] = (segs[-1][0], e)
        else:
            segs.append((s, e))
    ts = [s for s in segs if 140 <= s[1] - s[0] <= 200]
    if not ts:
        raise ValueError("header timestamp column not found")
    t0, t1 = ts[0]
    rowp = red[:, t0:t1].sum(axis=1)
    bands = [(s, e) for s, e in runs_1d(rowp > 0) if e - s >= 10]
    if len(bands) != 3:
        raise ValueError(f"header: {len(bands)} lines")
    first = []
    for s, e in bands:
        cp = red[s:e, max(0, t0 - 150):t0 - 15].sum(axis=0)
        r = runs_1d(cp > 0)
        words = []
        for a, b in r:
            if words and a - words[-1][1] <= 5:
                words[-1] = (words[-1][0], b)
            else:
                words.append((a, b))
        first.append(words[0][1] - words[0][0] if words else 0)
    return {"t0": t0, "t1": t1, "bands": bands, "first_word_px": first}


def header_offset_glyphs(rgb: np.ndarray, lay: dict, k: int) -> list[dict]:
    """Sign and digit glyphs of line k's '(+NNh)' column: the glyphs of the
    column inside the line's digit rows, without the brackets and the
    'h' (the first glyph and the last two), and without the bits of the
    neighbouring lines' brackets that reach into the band."""
    red = red_ink(rgb)
    s, e = lay["bands"][k]
    gl = glyphs(red, s - 1, e + 1, lay["t0"] + 268, lay["t0"] + 395, thr=80)
    keep = []
    for g in gl:
        hgt, wid = g["y1"] - g["y0"], g["x1"] - g["x0"]
        if hgt >= 8 or (hgt <= 3 and wid >= 7 and abs(g["cy"] - (s + e) / 2) <= 3):
            keep.append(g)
    return keep[1:-2] if len(keep) >= 4 else []


def tick_label_glyphs(rgb: np.ndarray, fr: Frame, xt: list[float], yt: list[float]):
    """Glyph lists of each x and y tick label."""
    ink = dark_ink(rgb)
    out_x, out_y = [], []
    spx = float(np.median(np.diff(xt))) if len(xt) > 1 else 80.0
    for x in xt:
        gl = glyphs(ink, fr.bottom_out + 6, fr.bottom_out + 30,
                    int(round(x - spx / 2 + 2)), int(round(x + spx / 2 - 2)))
        words: list[list[dict]] = []
        for g in gl:  # glyphs of one label are at most 7 px apart; keep the word centered on the tick
            if words and g["x0"] - max(q["x1"] for q in words[-1]) <= 7:
                words[-1].append(g)
            else:
                words.append([g])
        out_x.append(min(words, key=lambda w: abs((w[0]["x0"] + w[-1]["x1"]) / 2 - x)) if words else [])
    for y in yt:
        gl = glyphs(ink, int(round(y - 9)), int(round(y + 10)), fr.left_out - 75, fr.left_out - 5)
        out_y.append([g for g in gl if abs(g["cy"] - y) <= 4 or (g["y1"] - g["y0"] <= 3 and abs(g["cy"] - y) <= 4)])
    return out_x, out_y


# Digit templates are cut from these FSU plots, whose labels were read by
# eye: (plot under realtime/data, x tick labels left to right, y tick
# labels top to bottom, header hour offsets of lines 1 to 3).
TEMPLATE_SOURCES = [
    ("2026100200/WPAC/fsu_phase1.png", ["-50", "0", "50", "100", "150", "200"],
     [str(v) for v in range(130, -11, -10)], ["-96", "0", "+144"]),
    ("2026092812/AUTO_260924_05/fsu_phase1.png", None, None, ["-228", "0", "+54"]),
    ("2026092512/GREENLAND/fsu_phase1.png", None, None, ["-72", "0", "+30"]),
]
MAX_VARIANTS = 4


def _add(store: dict, ch: str, img: np.ndarray) -> None:
    if ch == "-":
        return  # the minus sign is recognized by its shape
    lst = store.setdefault(ch, [])
    if len(lst) < MAX_VARIANTS and not any(t.shape == img.shape and np.abs(t - img).max() < 0.02 for t in lst):
        lst.append(img)


def build_templates(data_dir) -> dict[str, dict[str, list[np.ndarray]]]:
    """Cut the tick label and header digit templates from TEMPLATE_SOURCES."""
    data_dir = Path(data_dir)
    out: dict[str, dict[str, list[np.ndarray]]] = {"tick": {}, "header": {}}
    for rel, xl, yl, hl in TEMPLATE_SOURCES:
        rgb = load_rgb(data_dir / rel)
        if xl or yl:
            fr = find_frame(rgb)
            xt, yt = find_ticks(rgb, fr)
            gx, gy = tick_label_glyphs(rgb, fr, xt, yt)
            for words, texts in ((gx, xl), (gy, yl)):
                if len(words) != len(texts):
                    raise ValueError(f"{rel}: {len(words)} labels, expected {len(texts)}")
                for gl, txt in zip(words, texts):
                    if len(gl) != len(txt):
                        raise ValueError(f"{rel}: label {txt!r} has {len(gl)} glyphs")
                    for g, ch in zip(gl, txt):
                        _add(out["tick"], ch, g["img"])
        lay = header_layout(rgb)
        for k, txt in enumerate(hl):
            gl = header_offset_glyphs(rgb, lay, k)
            if len(gl) != len(txt):
                raise ValueError(f"{rel}: header line {k} {txt!r} has {len(gl)} glyphs")
            for g, ch in zip(gl, txt):
                _add(out["header"], ch, g["img"])
    return out


def templates_to_b64(t: dict) -> str:
    arrs = {}
    for kind, d in t.items():
        for ch, lst in d.items():
            for i, a in enumerate(lst):
                arrs[f"{kind}|{ch}|{i}"] = np.round(a * 255).astype(np.uint8)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrs)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def templates_from_b64(b64: str) -> dict[str, dict[str, list[np.ndarray]]]:
    out: dict[str, dict[str, list[np.ndarray]]] = {"tick": {}, "header": {}}
    with np.load(io.BytesIO(base64.b64decode(b64))) as z:
        for key in sorted(z.files, key=lambda k: (k.split("|")[0], k.split("|")[1], int(k.split("|")[2]))):
            kind, ch, _ = key.split("|")
            out[kind].setdefault(ch, []).append(z[key].astype(float) / 255.0)
    return out


_TEMPLATES: dict | None = None


def templates() -> dict:
    """The digit templates: the embedded copy (TEMPLATE_B64, written by
    `python3 fsu_digitize.py --build-templates`), else cut afresh from
    TEMPLATE_SOURCES."""
    global _TEMPLATES
    if _TEMPLATES is None:
        b64 = globals().get("TEMPLATE_B64")
        _TEMPLATES = templates_from_b64(b64) if b64 else build_templates(Path(__file__).parent / "data")
    return _TEMPLATES


# ------------------------------------------------------------------ axis calibration
@dataclass
class Axis:
    """value = a + b * pixel, from the ticks read on the plot."""
    a: float
    b: float
    ticks: list  # (pixel, value) used in the fit
    rejected: list  # (pixel, text) not used
    resid_px: float  # RMS residual of the fit (pixels)

    def value(self, px):
        return self.a + self.b * np.asarray(px, float)

    def pixel(self, v):
        return (np.asarray(v, float) - self.a) / self.b


def fit_axis(pairs: list[tuple[float, str]]) -> Axis:
    """Robust line through (pixel, label) pairs: every pair of readable
    labels proposes a line, the one most others agree with (within 1 px)
    wins, refit by least squares on its inliers. Labels must also be
    equally spaced (a misread digit breaks that)."""
    num = []
    bad = []
    for px, txt in pairs:
        try:
            num.append((px, float(int(txt))))
        except ValueError:
            bad.append((px, txt))
    if len(num) < 2:
        raise ValueError(f"fewer than two readable tick labels: {pairs}")
    best = None
    for i in range(len(num)):
        for j in range(i + 1, len(num)):
            (p1, v1), (p2, v2) = num[i], num[j]
            if p2 == p1 or v2 == v1:
                continue
            b = (v2 - v1) / (p2 - p1)
            a = v1 - b * p1
            inl = [(p, v) for p, v in num if abs((v - a) / b - p) <= 1.0]
            if best is None or len(inl) > len(best):
                best = inl
    if best is None or len(best) < 2:
        raise ValueError(f"tick labels inconsistent: {pairs}")
    p = np.array([q for q, _ in best])
    v = np.array([q for _, q in best])
    A = np.c_[np.ones_like(p), p]
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    res = (v - (a + b * p)) / b
    rej = bad + [(q, str(int(w))) for q, w in num if (q, w) not in best]
    steps = np.diff(np.sort(v))
    if len(steps) and np.ptp(steps) > 1e-6:
        raise ValueError(f"tick labels not equally spaced: {sorted(v)}")
    return Axis(float(a), float(b), [(float(q), float(w)) for q, w in best], rej,
                float(np.sqrt(np.mean(res ** 2))))


def read_axes(rgb: np.ndarray, fr: Frame | None = None) -> tuple[Frame, Axis, Axis, dict]:
    """Frame, x axis and y axis calibrated from the tick labels."""
    fr = fr or find_frame(rgb)
    xt, yt = find_ticks(rgb, fr)
    gx, gy = tick_label_glyphs(rgb, fr, xt, yt)
    tpl = templates()["tick"]
    xs = [(p, read_word(g, tpl)[0]) for p, g in zip(xt, gx) if g]
    ys = [(p, read_word(g, tpl)[0]) for p, g in zip(yt, gy) if g]
    ax, ay = fit_axis(xs), fit_axis(ys)
    return fr, ax, ay, {"x_labels": xs, "y_labels": ys}


# ------------------------------------------------------------------ header
def read_header(rgb: np.ndarray) -> dict:
    """Start and end hour offsets of the trajectory from the red header.
    Line roles come from the first word's width (Start about 49 px,
    Current about 76 px, End about 35 px) and are checked against the
    offsets (Current is 0 h; Start <= End)."""
    lay = header_layout(rgb)
    tpl = templates()["header"]
    vals, roles = [], []
    for k in range(3):
        txt, sc = read_word(header_offset_glyphs(rgb, lay, k), tpl)
        if not txt or "?" in txt or txt in "+-":
            raise ValueError(f"header line {k + 1} unreadable: {txt!r}")
        vals.append(int(txt))
        w = lay["first_word_px"][k]
        roles.append("end" if w < 42 else "start" if w < 62 else "current")
    if sorted(roles) != ["current", "end", "start"]:
        raise ValueError(f"header roles {roles}")
    d = dict(zip(roles, vals))
    if d["current"] != 0 or d["start"] > d["end"]:
        raise ValueError(f"header offsets inconsistent: {d}")
    return {"start_h": d["start"], "end_h": d["end"], "future": roles[0] == "current", "order": roles}


# ------------------------------------------------------------------ pixel classes
def pixel_classes(rgb: np.ndarray) -> dict[str, np.ndarray]:
    """bg: page or shading (grey R=G=B, blue (v, v, 255), magenta
    (255, v, 255), red (255, v, v), all within 4 to 7 for the palette's
    dithering, except the exact deepest marker color); dark: black ink (all channels under 90); fill: neither,
    and saturated (max - min channel at least 50), which is the marker
    colors (the intensity palette and the colors between its steps) and
    some antialiased rims of dark ink; light: near
    white (the X of a forecast marker, or the page)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    bg = ((mx - mn) <= 4) | ((b >= 248) & (np.abs(r - g) <= 4)) | ((r >= 248) & (b >= 248)) | \
         ((r >= 248) & (np.abs(g - b) <= 4))
    # the deepest intensity color (251, 60, 60) is within that tolerance of the red shading
    deep = (np.abs(r - 251) <= 1) & (np.abs(g - 60) <= 1) & (np.abs(b - 60) <= 1)
    bg &= ~deep
    dark = mx < 90
    fill = ~bg & ~dark & ((mx - mn) >= 50)
    light = mn >= 200
    return {"bg": bg, "dark": dark, "fill": fill, "light": light}


def _smooth(a: np.ndarray, n: int = 2) -> np.ndarray:
    out = a.astype(float)
    for _ in range(n):
        p = np.pad(out, 1, mode="edge")
        out = (p[:-2] + 2 * p[1:-1] + p[2:]) / 4.0
        out = (out[:, :-2] + 2 * out[:, 1:-1] + out[:, 2:]) / 4.0
    return out


@dataclass
class Disc:
    x: float  # center, image pixels
    y: float
    r: float  # radius of the filled interior (pixels); the outline adds about 1
    support: float  # fraction of the circumference seen as a fill/outline edge
    color: tuple = (0, 0, 0)  # median fill RGB
    xmark: float = float("nan")  # strength of a white X (forecast marker)
    forecast: bool | None = None
    dark: bool = False  # a black-filled (1015 hPa) marker
    covered: float = 0.0  # fraction of the disc area covered by other discs drawn over it (estimated)
    cluster: int = -1
    tags: list = field(default_factory=list)


def interior_mask(cl: dict[str, np.ndarray]) -> np.ndarray:
    """Marker interiors: fill pixels, with the 1 to 2 px light strokes of a
    forecast X bridged (a pixel that is not dark with fill on both sides), opened
    by 3 x 3 so that the 1 to 2 px antialiased rims of lines and text and
    the scattered dithering of the shading drop out."""
    f = cl["fill"]
    bridged = f | (erode(dilate(f, 1), 1) & ~cl["dark"])
    return dilate(erode(bridged, 1), 1) & bridged


def hough_circles(mask: np.ndarray, solid: np.ndarray | None = None, rmin: float = 2.5, rmax: float = 30.0,
                  min_cover: float = 0.3, max_circles: int = 30) -> list[tuple]:
    """Circles whose arcs make up the boundary of one region (a marker or
    a cluster of overlapping markers). Each boundary pixel votes for
    centers along its inward normal at every radius; the peaks are scored
    by the share of the circumference (in angular bins) that boundary
    pixels with a normal toward the center actually cover; the best is
    refined by a least-squares circle fit, the boundary pixels it
    explains are removed, and the vote is repeated. A circle is kept when
    its arcs cover at least min_cover of the circumference and at least
    80% of its disc is inside `solid` (the region plus dark ink, which can
    be text written over a marker); one lying entirely inside a larger
    kept circle is dropped (the closed counter of a digit written on a
    marker looks like a small disc). Returns tuples (x, y, r, cover)
    in the mask's coordinates."""
    m = mask.astype(bool)
    solid = m if solid is None else (solid.astype(bool) | m)
    h, w = m.shape
    pad = 2
    M = np.zeros((h + 2 * pad, w + 2 * pad), bool)
    M[pad:pad + h, pad:pad + w] = m
    SOL = np.zeros_like(M)
    SOL[pad:pad + h, pad:pad + w] = solid
    edge = M & ~erode(M, 1)
    S = _smooth(M, 2)
    gy, gx = np.gradient(S)
    ys, xs = np.nonzero(edge)
    if len(ys) < 8:
        return []
    nx, ny = gx[ys, xs], gy[ys, xs]
    nn = np.hypot(nx, ny)
    ok = nn > 1e-6
    ys, xs, nx, ny = ys[ok].astype(float), xs[ok].astype(float), nx[ok] / nn[ok], ny[ok] / nn[ok]
    rmax = min(rmax, 0.5 * max(h, w) + 2)
    radii = np.arange(rmin, rmax + 0.01, 0.5)
    alive = np.ones(len(ys), bool)
    H, W = M.shape
    yy, xx = np.mgrid[0:H, 0:W]
    out: list[tuple] = []

    def coverage(cx, cy, r, sel):
        d = np.hypot(xs - cx, ys - cy)
        cosang = ((cx - xs) * nx + (cy - ys) * ny) / np.maximum(d, 1e-6)
        on = sel & (np.abs(d - r) <= 1.2) & (cosang > 0.7)
        nb = int(min(36, max(8, round(2 * math.pi * r))))
        ang = np.arctan2(ys[on] - cy, xs[on] - cx)
        bins = np.unique(np.floor((ang + math.pi) / (2 * math.pi) * nb).astype(int) % nb)
        return len(bins) / nb, on

    tried = set()
    fails = 0
    while len(out) < max_circles and fails < 10:
        if alive.sum() < 6:
            break
        al = np.nonzero(alive)[0]
        cx = xs[al][None, :] + radii[:, None] * nx[al][None, :]
        cy = ys[al][None, :] + radii[:, None] * ny[al][None, :]
        ix, iy = np.round(cx).astype(int), np.round(cy).astype(int)
        ir = np.broadcast_to(np.arange(len(radii))[:, None], ix.shape)
        good = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
        acc = np.bincount((ir[good] * H + iy[good]) * W + ix[good],
                          minlength=len(radii) * H * W).reshape(len(radii), H, W).astype(float)
        sm = acc.copy()
        sm[:, 1:] += acc[:, :-1]
        sm[:, :-1] += acc[:, 1:]
        sm[:, :, 1:] += acc[:, :, :-1]
        sm[:, :, :-1] += acc[:, :, 1:]
        sm /= (2 * math.pi * radii)[:, None, None]
        flat = sm.reshape(len(radii), -1)
        kk = np.argmax(flat, axis=1)  # the best center at every radius
        cands = [(float(flat[ri, k]), int(k % W), int(k // W), float(radii[ri])) for ri, k in enumerate(kk)
                 if flat[ri, k] > 0]
        best = None
        for _, bx, by, br in cands:
            if (bx, by, br) in tried:
                continue
            cov, on = coverage(bx, by, br, alive)
            score = cov * min(1.0, br / 8.0)  # a small circle is easy to fit to bits of anything
            if best is None or score > best[0]:
                best = (score, bx, by, br, cov, on)
        if best is None:
            break
        _, bx, by, br, cov, on = best
        tried.add((bx, by, br))
        if on.sum() >= 5:
            fx, fy, frr = fit_circle(xs[on], ys[on], bx, by, br)
            cov2, on2 = coverage(fx, fy, frr, alive)
            if cov2 >= cov:
                bx, by, br, cov, on = fx, fy, frr, cov2, on2
        if cov < min_cover or on.sum() < 5:
            fails += 1
            continue
        alive &= ~on
        inside = np.hypot(xx - bx, yy - by) <= max(br - 0.5, 1.0)
        if inside.sum() and SOL[inside].mean() < 0.8:
            fails += 1
            continue
        if br < 5.0 and (cov < 0.6 or (inside.sum() and M[inside].mean() < 0.75)):
            fails += 1  # small circles must be nearly whole and solid fill
            continue
        if any(math.hypot(bx - ox, by - oy) + br <= orr + 1.0 and br < orr for ox, oy, orr, _ in
               [(o[0] + pad, o[1] + pad, o[2], o[3]) for o in out]):
            fails += 1
            continue
        fails = 0
        out.append((bx - pad, by - pad, br, cov))
    return out


def fit_circle(xs, ys, x0, y0, r0):
    """Least-squares circle (algebraic fit, then a few Gauss-Newton steps
    on the geometric distance); falls back to the start values if the
    arc is too short to constrain it."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    cx, cy, r = float(x0), float(y0), float(r0)
    if len(xs) < 6:
        return cx, cy, r
    for _ in range(10):
        dx, dy = xs - cx, ys - cy
        d = np.hypot(dx, dy)
        d = np.maximum(d, 1e-6)
        J = np.c_[-dx / d, -dy / d, -np.ones_like(d)]
        res = d - r
        try:
            step, *_ = np.linalg.lstsq(J, -res, rcond=None)
        except np.linalg.LinAlgError:
            break
        cx, cy, r = cx + step[0], cy + step[1], r + step[2]
        if np.abs(step).max() < 1e-3:
            break
    if not (np.isfinite(cx) and np.isfinite(cy)) or abs(cx - x0) > r0 or abs(cy - y0) > r0 or r <= 1:
        return float(x0), float(y0), float(r0)
    return float(cx), float(cy), float(r)


def find_inset(rgb: np.ndarray, fr: Frame) -> tuple[int, int, int, int] | None:
    """The track inset map's box (y0, y1, x0, x1), from the dark runs of at
    least 150 px above the bottom edge other than the frame's top edge
    (its thick border); None if there is none."""
    dark = rgb.max(axis=2) < 90
    rows = []
    for y in range(0, fr.bottom_in - 5):
        if fr.top_out - 1 <= y <= fr.top_in + 1:
            continue
        for s0, e0 in runs_1d(dark[y]):
            if e0 - s0 >= 150:
                rows.append((y, s0, e0))
    if len(rows) < 2:
        return None
    return (min(r[0] for r in rows), max(r[0] for r in rows) + 1,
            min(r[1] for r in rows), max(r[2] for r in rows))


def plot_area_mask(rgb: np.ndarray, fr: Frame, inset) -> np.ndarray:
    """True inside the frame and outside the inset (with 2 px margins)."""
    h, w = rgb.shape[:2]
    m = np.zeros((h, w), bool)
    m[fr.top_in + 2:fr.bottom_in - 1, fr.left_in + 2:fr.right_in - 1] = True
    if inset is not None:
        y0, y1, x0, x1 = inset
        m[max(0, y0 - 2):y1 + 3, max(0, x0 - 2):x1 + 3] = False
    return m


def _round_component(ys, xs, n) -> tuple[float, float, float] | None:
    """A component that is a single whole disc: (x, y, r) from a circle fit
    to its boundary, else None."""
    r_area = math.sqrt(n / math.pi)
    if r_area < 2.0:
        return None
    y0, x0 = ys.min(), xs.min()
    m = np.zeros((ys.max() - y0 + 3, xs.max() - x0 + 3), bool)
    m[ys - y0 + 1, xs - x0 + 1] = True
    e = m & ~erode(m, 1)
    by, bx = np.nonzero(e)
    cx, cy = xs.mean() - x0 + 1, ys.mean() - y0 + 1
    d = np.hypot(bx - cx, by - cy)
    if d.max() - d.min() > 2.6 or abs(np.ptp(xs) - np.ptp(ys)) > 2:
        return None
    fx, fy, frr = fit_circle(bx, by, cx, cy, d.mean())
    resid = np.abs(np.hypot(bx - fx, by - fy) - frr)
    if resid.max() > 1.3:
        return None
    return fx + x0 - 1, fy + y0 - 1, frr


def detect_discs(rgb: np.ndarray, area: np.ndarray, cl: dict | None = None) -> list[Disc]:
    """All marker discs inside the plot area."""
    cl = cl or pixel_classes(rgb)
    I = interior_mask(cl) & area
    solid_all = I | cl["dark"]
    discs: list[Disc] = []
    for c in components(I, min_px=10):
        rc = _round_component(c["ys"], c["xs"], c["n"])
        if rc is not None:
            discs.append(Disc(rc[0], rc[1], rc[2], 1.0))
            continue
        y0, y1, x0, x1 = c["bbox"]
        m = np.zeros((y1 - y0, x1 - x0), bool)
        m[c["ys"] - y0, c["xs"] - x0] = True
        for x, y, r, cov in hough_circles(m, solid_all[y0:y1, x0:x1]):
            discs.append(Disc(x + x0, y + y0, r, cov))
    discs = [d for d in discs if d.r >= 1.5]
    # the same disc found twice (a second circle on its leftover boundary)
    discs.sort(key=lambda d: -d.support)
    uniq: list[Disc] = []
    for d in discs:
        if any(math.hypot(o.x - d.x, o.y - d.y) < 0.35 * min(o.r, d.r) + 1.0 and 0.75 < d.r / o.r < 1.33
               for o in uniq):
            continue
        uniq.append(d)
    # a small disc centered inside one more than twice its size is the
    # closed counter of a digit written over that marker, or a piece of
    # its outline cut by the label, not a marker (the gale radius, and so
    # the marker size, does not halve between neighboring markers)
    keep = [d for d in uniq if not any(
        o is not d and o.r > 2.0 * d.r and math.hypot(o.x - d.x, o.y - d.y) <= o.r - 1.0 for o in uniq)]
    owner = disc_owner(keep, I.shape, pad=0.5)
    return [d for i, d in enumerate(keep) if _outlined(d, i, cl, owner)]


def _outlined(d: Disc, i: int, cl: dict, owner: np.ndarray) -> bool:
    """A marker has a dark outline: in at least half of the directions
    around it that are not covered by another disc, the ring just outside
    its radius holds dark pixels, and in at most a quarter it is bare
    shading or page."""
    h, w = owner.shape
    R = int(d.r + 4)
    y0, y1 = max(0, int(d.y) - R), min(h, int(d.y) + R + 2)
    x0, x1 = max(0, int(d.x) - R), min(w, int(d.x) + R + 2)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rr = np.hypot(xx - d.x, yy - d.y)
    ring = (rr >= d.r + 0.3) & (rr <= d.r + 2.5)
    if ring.sum() == 0:
        return False
    own = owner[y0:y1, x0:x1][ring]
    other = (own >= 0) & (own != i)
    drk = cl["dark"][y0:y1, x0:x1][ring]
    bare = cl["bg"][y0:y1, x0:x1][ring] & ~drk & ~other
    nb = 24
    ang = np.floor((np.arctan2(yy - d.y, xx - d.x)[ring] + math.pi) / (2 * math.pi) * nb).astype(int) % nb
    cnt = np.bincount(ang, minlength=nb).astype(float)
    n_dark = np.bincount(ang, weights=drk, minlength=nb)
    n_other = np.bincount(ang, weights=other, minlength=nb)
    n_bare = np.bincount(ang, weights=bare, minlength=nb)
    seen = cnt > 0
    occl = seen & (n_other >= 0.5 * cnt) & (n_dark == 0)
    free = seen & ~occl
    if free.sum() < 4:
        return True  # almost wholly under other discs: keep, judged by the Hough evidence
    outlined = (n_dark > 0) & free
    bare_dir = free & (n_bare >= 0.7 * cnt)
    return outlined.sum() >= 0.5 * free.sum() and bare_dir.sum() <= 0.25 * free.sum()


# ------------------------------------------------------------------ marker features
def disc_features(rgb: np.ndarray, discs: list[Disc], cl: dict) -> None:
    """Fill color and the strength of a white X for each disc (in place).
    The X is two light diagonal strokes; its strength is how much lighter
    the diagonals are than the fill, 0 (none) to 1 (white). For a disc
    under 4 px the X is only a light center pixel."""
    lum = luminance(rgb)
    h, w = lum.shape
    for d in discs:
        R = int(d.r + 2)
        y0, y1 = max(0, int(d.y) - R), min(h, int(d.y) + R + 2)
        x0, x1 = max(0, int(d.x) - R), min(w, int(d.x) + R + 2)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dx, dy = xx - d.x, yy - d.y
        rr = np.hypot(dx, dy)
        diag = np.minimum(np.abs(dx - dy), np.abs(dx + dy)) / math.sqrt(2)
        body = (rr <= 0.75 * d.r) & (diag > 1.5) & cl["fill"][y0:y1, x0:x1]
        if body.sum() < 3:
            body = (rr <= 0.75 * d.r) & ~cl["dark"][y0:y1, x0:x1]
        if body.sum() == 0:
            continue
        col = np.median(rgb[y0:y1, x0:x1][body], axis=0)
        d.color = tuple(int(v) for v in col)
        lf = float(np.mean(col))
        if d.r >= 4:
            arm = (rr >= 0.3 * d.r) & (rr <= 0.8 * d.r) & (diag <= 0.75)
        else:
            arm = rr <= 0.8
        if arm.sum() == 0:
            continue
        ld = float(np.mean(lum[y0:y1, x0:x1][arm]))
        d.xmark = max(0.0, (ld - lf) / max(255.0 - lf, 30.0))


def ring_score(dark: np.ndarray, cover: np.ndarray, x: float, y: float, rmin: float = 12.0,
               radii=np.arange(15.0, 21.1, 1.0), off: int = 4, nang: int = 72) -> tuple[float, float, float, float]:
    """Evidence of the analysis marker's C around (x, y): the C is a large
    letter drawn centered on the marker, an elliptical arc about 18 px
    wide in radius and 21 px tall, open on the right. Returns the best
    share of the arc from 60 to 300 degrees (counterclockwise from the
    right) that is dark, less half the dark share of the opening (-40 to
    40 degrees; half of it counts against when the opening is hidden), over centers within +/- off px and horizontal
    radii in radii (above rmin), counting only the part not hidden under
    other markers (cover)."""
    radii = radii[radii >= rmin]
    if len(radii) == 0:
        return (0.0, x, y, 0.0)
    h, w = dark.shape
    ang = np.linspace(math.radians(60), math.radians(300), nang)
    gap = np.linspace(math.radians(-40), math.radians(40), 24)
    best = (0.0, x, y, 0.0)

    def frac(cx, cy, a, need):
        px = np.round(cx + radii[:, None] * np.cos(a)[None, :]).astype(int)
        py = np.round(cy - 1.17 * radii[:, None] * np.sin(a)[None, :]).astype(int)
        ok = (px >= 1) & (px < w - 1) & (py >= 1) & (py < h - 1)
        px, py = np.clip(px, 1, w - 2), np.clip(py, 1, h - 2)
        hit = dark[py, px] | dark[py + 1, px] | dark[py, px + 1]
        vis = ok & (~cover[py, px] | hit)
        f = (hit & vis).sum(axis=1) / np.maximum(vis.sum(axis=1), 1)
        f[vis.sum(axis=1) < need] = np.nan
        return f

    for oy in range(-off, off + 1):
        for ox in range(-off, off + 1):
            cx, cy = x + ox, y + oy
            sc = frac(cx, cy, ang, int(0.7 * nang))
            op = frac(cx, cy, gap, 6)
            sc = np.where(np.isnan(sc), 0.0, sc - 0.5 * np.nan_to_num(op, nan=0.5))
            k = int(np.argmax(sc))
            if sc[k] > best[0]:
                best = (float(sc[k]), cx, cy, float(radii[k]))
    return best


def bar_score(dark: np.ndarray, cover: np.ndarray, x: float, y: float) -> float:
    """Evidence of the end marker's Z: a letter about 33 px wide and 43 px
    tall centered on the marker, that is horizontal dark bars about 21 px
    above and below its center (symmetric within 4 px) whose dark runs
    are centered on the marker (within 2.5 px) where they can be seen, and
    a diagonal from the top right to the bottom left. Pixels hidden under
    other markers do not count against it, but at least 20 of the 29 px
    tested along each bar must be visible. Returns the weakest of the
    bar and diagonal scores (0 to 1)."""
    h, w = dark.shape
    xi = int(round(x))
    xs = np.arange(xi - 14, xi + 15)
    if xs.min() < 1 or xs.max() >= w - 1:
        return 0.0
    prof = {}
    for sgn in (-1, 1):
        for dy in range(17, 26):
            yy = int(round(y)) + sgn * dy
            if not (0 <= yy < h):
                continue
            row = dark[yy, xs]
            vis = ~cover[yy, xs] | row
            if vis.sum() < 20:
                continue
            f = row[vis].mean()
            # the dark run through the marker's column, where both ends can be seen
            run = [(s0, e0) for s0, e0 in runs_1d(dark[yy]) if s0 <= xi < e0]
            if run:
                s0, e0 = run[0]
                ends_seen = not cover[yy, max(0, s0 - 1)] and not cover[yy, min(w - 1, e0)]
                if ends_seen and (abs((s0 + e0 - 1) / 2.0 - x) > 2.5 or not 26 <= e0 - s0 <= 40):
                    f = 0.0
            prof[(sgn, dy)] = f
    best, bdy = 0.0, None
    for (s1, d1), f1 in prof.items():
        if s1 > 0:
            continue
        for (s2, d2), f2 in prof.items():
            if s2 < 0 or abs(d1 - d2) > 4:
                continue
            if min(f1, f2) > best:
                best, bdy = min(f1, f2), (d1, d2)
    if bdy is None:
        return 0.0
    t = np.linspace(0.1, 0.9, 40)
    px = np.round(x + 16.5 - 33.0 * t).astype(int)
    py = np.round(y - bdy[0] + (bdy[0] + bdy[1]) * t).astype(int)
    ok = (px >= 1) & (px < w - 1) & (py >= 0) & (py < h)
    px, py = np.clip(px, 1, w - 2), np.clip(py, 0, h - 1)
    hit = dark[py, px] | dark[py, px - 1] | dark[py, px + 1]
    vis = ok & (~cover[py, px] | hit)
    diag = float((hit & vis).sum() / vis.sum()) if vis.sum() >= 6 else best
    return min(best, diag)


def a_score(dark: np.ndarray, cover: np.ndarray, x: float, y: float) -> float:
    """Evidence of the start marker's A: a letter about 43 px tall
    centered on the marker, its two legs running from an apex about
    21 px above the center to feet about 16 px either side and 21 px
    below. Returns the dark share of the visible points along both legs
    (points hidden under markers are skipped; at least 15 must be
    visible)."""
    h, w = dark.shape
    best = 0.0
    for oy in (-1, 0, 1):
        t = np.linspace(0.0, 1.0, 40)
        pts = []
        for sgn in (-1, 1):
            pts.append((x + sgn * 16.5 * t, y + oy - 21.5 + 43.0 * t))
        px = np.round(np.concatenate([p[0] for p in pts])).astype(int)
        py = np.round(np.concatenate([p[1] for p in pts])).astype(int)
        ok = (px >= 1) & (px < w - 1) & (py >= 1) & (py < h - 1)
        px, py = np.clip(px, 1, w - 2), np.clip(py, 1, h - 2)
        hit = dark[py, px] | dark[py, px + 1] | dark[py, px - 1]
        vis = ok & (~cover[py, px] | hit)
        if vis.sum() < 15:
            continue
        best = max(best, float((hit & vis).sum() / vis.sum()))
    return best


# ------------------------------------------------------------------ polyline links
def link_matrix(discs: list[Disc], dark: np.ndarray, max_px: float = 400.0) -> np.ndarray:
    """Evidence that the trajectory line joins discs i and j directly:
    +1 when the stretch of the segment between the two outlines that is
    not under another disc is dark along its whole length (at least 3 px
    of it visible), 0.75 when that segment also runs through another disc
    (the line may just pass on through it), 0.5 when the two discs touch,
    overlap or are within 7 px (no line to see), 0.25 when the line would
    be hidden under other discs, 0 otherwise."""
    n = len(discs)
    L = np.zeros((n, n))
    h, w = dark.shape
    dk = dark | shift(dark, 1, 0) | shift(dark, -1, 0) | shift(dark, 0, 1) | shift(dark, 0, -1)
    X = np.array([d.x for d in discs])
    Y = np.array([d.y for d in discs])
    Rr = np.array([d.r for d in discs])
    for i in range(n):
        for j in range(i + 1, n):
            dist = math.hypot(X[j] - X[i], Y[j] - Y[i])
            if dist > max_px:
                continue
            gap = dist - Rr[i] - Rr[j]
            if gap <= 7.0:  # touching or nearly: too little line between them to see
                L[i, j] = L[j, i] = 0.5
                continue
            t = np.arange(Rr[i] + 2.0, dist - Rr[j] - 2.0 + 1e-9, 1.0) / dist
            if len(t) == 0:
                L[i, j] = L[j, i] = 0.5
                continue
            px = X[i] + t * (X[j] - X[i])
            py = Y[i] + t * (Y[j] - Y[i])
            under = np.zeros(len(t), bool)
            for k in range(n):
                if k != i and k != j:
                    under |= np.hypot(px - X[k], py - Y[k]) <= Rr[k] + 1.5
            vis = ~under
            if vis.sum() < 3:
                L[i, j] = L[j, i] = 0.25  # hidden under other markers: possible, unconfirmed
                continue
            ix = np.clip(np.round(px[vis]).astype(int), 0, w - 1)
            iy = np.clip(np.round(py[vis]).astype(int), 0, h - 1)
            if dk[iy, ix].mean() >= 0.97:
                through = any(k != i and k != j and
                              _seg_dist(X[i], Y[i], X[j], Y[j], X[k], Y[k]) < Rr[k] + 2.0 for k in range(n))
                L[i, j] = L[j, i] = 0.75 if through else 1.0
    return L


def on_top(a: Disc, b: Disc, dark: np.ndarray) -> int:
    """Which of two overlapping discs was drawn later: +1 if a's outline
    runs across b (a on top), -1 if b's runs across a, 0 if unknown."""
    def crossing(p: Disc, q: Disc) -> float:
        ang = np.linspace(0, 2 * math.pi, 90, endpoint=False)
        px = p.x + (p.r + 0.8) * np.cos(ang)
        py = p.y + (p.r + 0.8) * np.sin(ang)
        inside = np.hypot(px - q.x, py - q.y) <= q.r - 1.5
        if inside.sum() < 4:
            return float("nan")
        h, w = dark.shape
        ix = np.clip(np.round(px[inside]).astype(int), 0, w - 1)
        iy = np.clip(np.round(py[inside]).astype(int), 0, h - 1)
        return float(dark[iy, ix].mean())
    ca, cb = crossing(a, b), crossing(b, a)
    if np.isnan(ca) and np.isnan(cb):
        return 0
    ca = 0.0 if np.isnan(ca) else ca
    cb = 0.0 if np.isnan(cb) else cb
    if ca > 0.6 and ca > cb + 0.3:
        return 1
    if cb > 0.6 and cb > ca + 0.3:
        return -1
    return 0


def _seg_dist(ax, ay, bx, by, px, py) -> float:
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    return math.hypot(ax + t * vx - px, ay + t * vy - py)


def crowded(discs: list[Disc]) -> list[bool]:
    """A disc is crowded when its center lies inside another disc or
    another's center inside it: markers drawn over one another, where a
    marker can hide completely and the drawing order is hard to read."""
    out = []
    for i, a in enumerate(discs):
        out.append(any(j != i and math.hypot(a.x - b.x, a.y - b.y) < max(a.r, b.r) for j, b in enumerate(discs)))
    return out


def _why(log, i, j, reason):
    if log is not None:
        log.append((i, j, reason))


def follow(discs: list[Disc], L: np.ndarray, start: int, step: int, dark: np.ndarray, crowd: list[bool],
           t0: int, xcut: float = XCUT, exclude: set | None = None, max_len: int = 80,
           log: list | None = None) -> tuple[list[int], str]:
    """Walk the trajectory from disc `start` one marker at a time, forward
    in time (step +1) or backward (step -1), with t0 the start's hour and
    STEP_H the spacing. A step is taken only when exactly one unvisited
    disc is linked to the current one after these filters:
    - where no line is seen between the two (they touch or the line is
      under other discs), the two must be of about the same size (ratio
      0.6 to 1.67) and color (RGB distance under 170), as neighbors in
      time are;
    - where the two discs overlap, the later one must be on top;
    - a marker after the analysis (hour > 0) must carry an X and one
      before it must not, when the disc is big enough to show it
      (r >= 4 px); the analysis marker itself is the C marker;
    - of the candidates that pass, one whose segment runs through (or
      within 2 px of) another one's disc is dropped (the nearer one is
      the next marker on a straight stretch).
    The walk stops at a crowded disc (it is kept if the line to it was
    seen), at a dead end, or when the choice is ambiguous; the reason is
    returned."""
    seq = [start]
    seen = {start} | (exclude or set())
    cur, t = start, t0
    reason = "end"
    while len(seq) < max_len:
        if crowd[cur] and cur != start:
            reason = "cluster"
            break
        cand = [j for j in range(len(discs)) if j not in seen and L[cur, j] >= 0.5]
        c = discs[cur]
        tn = t + step * STEP_H
        keep = []
        for j in cand:
            d = discs[j]
            if L[cur, j] < 1.0:
                # no line seen between them: a neighbor in time has about the same
                # size and color (a fully hidden marker in between would not)
                if not (0.6 <= d.r / c.r <= 1.67) or \
                        math.dist(d.color, c.color) > 170.0:
                    _why(log, cur, j, "size/color")
                    continue
            if math.hypot(d.x - c.x, d.y - c.y) < c.r + d.r:
                o = on_top(d, c, dark)
                if (step > 0 and o < 0) or (step < 0 and o > 0):
                    _why(log, cur, j, "drawing order")
                    continue
            if d.r >= 4 and not np.isnan(d.xmark):
                if tn > 0 and d.xmark < xcut:
                    _why(log, cur, j, "no X")
                    continue
                if tn < 0 and d.xmark >= xcut:
                    _why(log, cur, j, "X")
                    continue
            keep.append(j)
        # of the candidates left, one whose segment runs through (or within 2 px of)
        # another one's disc is not the next marker: the nearer one is
        keep = [j for j in keep if not any(
            k != j and _seg_dist(c.x, c.y, discs[j].x, discs[j].y, discs[k].x, discs[k].y) < discs[k].r + 2.0
            for k in keep)]
        if not keep:
            reason = "dead end" if not cand else "no candidate passes"
            break
        if len(keep) > 1:
            conf = [j for j in keep if L[cur, j] >= 1.0]
            if len(conf) == 1 and not any(L[cur, j] in (0.5, 0.25) for j in keep):
                keep = conf
            else:
                reason = "ambiguous"
                break
        j = keep[0]
        if crowd[j] and L[cur, j] < 1.0:
            reason = "cluster"
            break
        seq.append(j)
        seen.add(j)
        cur, t = j, tn
    return seq, reason


# ------------------------------------------------------------------ one plot
def disc_owner(discs: list[Disc], shape, pad: float = 2.5) -> np.ndarray:
    """Index of a disc covering each pixel (within its radius plus pad; the
    last drawn wins where they overlap, in list order), -1 elsewhere."""
    own = np.full(shape, -1, np.int32)
    h, w = shape
    for i, d in enumerate(discs):
        R = d.r + pad
        y0, y1 = max(0, int(d.y - R)), min(h, int(d.y + R) + 2)
        x0, x1 = max(0, int(d.x - R)), min(w, int(d.x + R) + 2)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        m = np.hypot(xx - d.x, yy - d.y) <= R
        own[y0:y1, x0:x1][m] = i
    return own


def _overlap_frac(d: Disc, discs: list[Disc]) -> float:
    """Share of a disc's circumference that lies inside other discs."""
    ang = np.linspace(0, 2 * math.pi, 72, endpoint=False)
    px, py = d.x + d.r * np.cos(ang), d.y + d.r * np.sin(ang)
    ins = np.zeros(72, bool)
    for o in discs:
        if o is not d:
            ins |= np.hypot(px - o.x, py - o.y) < o.r
    return float(ins.mean())


def digitize_plot(path, cycle: dt.datetime | None = None) -> dict:
    """Digitize one FSU phase plot. Returns a dict with the calibration
    ('axes'), the header ('header'), every disc found ('discs', with its
    hour where timed), the timed trajectory points ('points': hour,
    valid, x, y, ex, ey, flag), the plot's quality ('quality': closed /
    partial / failed) and notes. x is -V_T^L; y is B (phase1) or -V_T^U
    (phase2); ex, ey are the estimated digitizing errors (m)."""
    rgb = load_rgb(path)
    name = Path(path).name
    kind = "phase1" if "phase1" in name else "phase2" if "phase2" in name else None
    res: dict = {"path": str(path), "kind": kind, "notes": [], "points": [], "discs": [], "quality": "failed"}
    try:
        fr, ax, ay, lab = read_axes(rgb)
        hdr = read_header(rgb)
    except ValueError as e:
        res["notes"].append(f"calibration: {e}")
        return res
    res["axes"] = {"frame": fr.__dict__, "x": [ax.a, ax.b, ax.resid_px, len(ax.ticks)],
                   "y": [ay.a, ay.b, ay.resid_px, len(ay.ticks)],
                   "x_labels": [w for _, w in lab["x_labels"]], "y_labels": [w for _, w in lab["y_labels"]]}
    res["header"] = hdr
    return trace(rgb, fr, ax, ay, hdr, cycle, res)


def trace(rgb: np.ndarray, fr: Frame, ax: Axis, ay: Axis, hdr: dict, cycle: dt.datetime | None = None,
          res: dict | None = None) -> dict:
    """The marker stage of digitize_plot, given the frame, the two axis
    calibrations and the header (start_h, end_h, future): find the
    discs, the end and analysis markers, walk the trajectory and time
    the markers. Fills and returns res."""
    if res is None:
        res = {"notes": [], "points": [], "discs": [], "quality": "failed", "axes": {}, "header": hdr}
    inset = find_inset(rgb, fr)
    area = plot_area_mask(rgb, fr, inset)
    cl = pixel_classes(rgb)
    res["axes"]["background"] = background_check(rgb, fr, ax, ay, area, cl, res.get("kind"))
    discs = detect_discs(rgb, area, cl)
    disc_features(rgb, discs, cl)
    crowd = crowded(discs)
    dark = cl["dark"]
    cover = interior_mask(cl)
    L = link_matrix(discs, dark)
    start_h, end_h = hdr["start_h"], hdr["end_h"]
    # the end marker (Z) and the analysis marker (C)
    owner = disc_owner(discs, dark.shape, pad=2.5)
    zs = sorted(((bar_score(dark, (owner >= 0) & (owner != i) | (cover & ~dark), d.x, d.y), i)
                 for i, d in enumerate(discs)), reverse=True)
    if sum(1 for sc, _ in zs if sc >= 0.7) > 1:  # prefer a marker that is not in a cluster
        zs = [q for q in zs if not crowd[q[1]]] or zs
    z = zs[0][1] if zs and zs[0][0] >= 0.7 and (len(zs) < 2 or zs[1][0] < zs[0][0] - 0.1) else None
    c = None
    if not hdr["future"] and start_h < 0:
        cs = sorted(((ring_score(dark, (owner >= 0) & (owner != i), d.x, d.y, rmin=d.r + 3)[0], i)
                     for i, d in enumerate(discs)
                     if not crowd[i] and not (d.r >= 4 and d.xmark >= XCUT)), reverse=True)
        if cs and cs[0][0] >= 0.6 and (len(cs) < 2 or cs[1][0] < cs[0][0] - 0.1):
            c = cs[0][1]
    elif not hdr["future"]:
        c = "start"
    a = None
    if hdr["future"]:
        As = sorted(((a_score(dark, (owner >= 0) & (owner != i) | (cover & ~dark), d.x, d.y), i)
                     for i, d in enumerate(discs) if not crowd[i]), reverse=True)
        if As and As[0][0] >= 0.75 and (len(As) < 2 or As[1][0] < As[0][0] - 0.1) and As[0][1] != z:
            a = As[0][1]
    res["notes"].append(f"Z marker {'found' if z is not None else 'not found'}; "
                        f"C marker {'found' if isinstance(c, int) else 'at start' if c == 'start' else 'not found'}")
    times: dict[int, list[tuple[int, str]]] = {}
    back, why_b = ([], "no Z")
    if z is not None:
        back, why_b = follow(discs, L, z, -1, dark, crowd, end_h)
    if c == "start" and back:
        c = back[-1] if why_b == "dead end" else None
    spacing = STEP_H
    closed = False
    if isinstance(c, int) and c in back:
        k = back.index(c)
        if k > 0 and end_h % k == 0 and end_h // k in (6, 12):
            spacing = end_h // k
            closed = True
        elif k == 0 and end_h == 0:
            closed = True
        else:
            res["notes"].append(f"chain from Z reaches C after {k} steps for {end_h} h: markers hidden")
    elif hdr["future"] and back and why_b == "dead end":
        k = len(back) - 1
        if k > 0 and (end_h - start_h) % k == 0 and (end_h - start_h) // k in (6, 12):
            spacing = (end_h - start_h) // k
            closed = True
    res["spacing_h"] = spacing
    res["notes"].append(f"walk back from Z: {len(back)} markers, stopped: {why_b}")
    bad_back = isinstance(c, int) and c in back and not closed
    if not bad_back:
        for k, i in enumerate(back):
            times.setdefault(i, []).append((end_h - k * spacing, "Z"))
    elif c in back:  # the walk reached C with the wrong count: keep only C itself
        times.setdefault(c, []).append((0, "C"))
    if isinstance(c, int) and not closed and end_h > 0 and not bad_back:
        # (after a walk from Z that reached C with the wrong count, a walk
        # forward from C over the same markers would meet the same hidden one)
        fwd, why_f = follow(discs, L, c, +1, dark, crowd, 0, exclude=set())
        res["notes"].append(f"walk forward from C: {len(fwd)} markers, stopped: {why_f}")
        for k, i in enumerate(fwd):
            times.setdefault(i, []).append((k * spacing, "C"))
    elif isinstance(c, int) and not closed:
        times.setdefault(c, []).append((0, "C"))
    if a is not None and not closed:
        fwd, why_f = follow(discs, L, a, +1, dark, crowd, start_h)
        res["notes"].append(f"walk forward from A: {len(fwd)} markers, stopped: {why_f}")
        if z is not None and z in fwd:
            k = fwd.index(z)
            if k > 0 and (end_h - start_h) % k == 0 and (end_h - start_h) // k in (6, 12):
                spacing = (end_h - start_h) // k
                closed = True
                res["spacing_h"] = spacing
                times = {}
            else:
                fwd = fwd[:1]
                res["notes"].append(f"walk from A reaches Z after {k} steps for {end_h - start_h} h: markers hidden")
        for k, i in enumerate(fwd):
            times.setdefault(i, []).append((start_h + k * spacing, "A"))
    ovf = [_overlap_frac(d, discs) for d in discs]
    for i, d in enumerate(discs):
        hrs = sorted({t for t, _ in times.get(i, [])})
        flag = "ok"
        if len(hrs) > 1:
            flag = "conflict"
        elif not hrs:
            flag = "untimed"
        elif crowd[i]:
            flag = "crowded"
        elif not closed:
            flag = "open"
        err_px = 0.7 + (0.25 * d.r if crowd[i] else 0.1 * d.r * ovf[i])
        dd = {"x_px": round(d.x, 2), "y_px": round(d.y, 2), "r_px": round(d.r, 2), "color": d.color,
              "xmark": None if np.isnan(d.xmark) else round(d.xmark, 2), "crowded": bool(crowd[i]),
              "overlap": round(ovf[i], 2), "hour": hrs[0] if len(hrs) == 1 else None, "flag": flag,
              "x": float(ax.value(d.x)), "y": float(ay.value(d.y)),
              "ex": abs(ax.b) * err_px, "ey": abs(ay.b) * err_px}
        res["discs"].append(dd)
        if len(hrs) == 1:
            walks = sorted({w for t, w in times[i]})
            p = {"hour": hrs[0], "x": dd["x"], "y": dd["y"], "ex": dd["ex"], "ey": dd["ey"], "flag": flag,
                 "r_px": dd["r_px"], "walk": "closed" if closed else "+".join(walks)}
            if cycle is not None:
                p["valid"] = (cycle + dt.timedelta(hours=hrs[0])).strftime("%Y-%m-%dT%H:%MZ")
            res["points"].append(p)
    res["points"].sort(key=lambda p: p["hour"])
    hours = [p["hour"] for p in res["points"]]
    if len(hours) != len(set(hours)):
        res["notes"].append("two markers share an hour; those points are dropped")
        dup = {h for h in hours if hours.count(h) > 1}
        res["points"] = [p for p in res["points"] if p["hour"] not in dup]
    res["quality"] = "closed" if closed else ("partial" if res["points"] else "failed")
    return res


# hue family of the shading in each quadrant: (upper left, upper right, lower left, lower right),
# 0 grey, 1 blue, 2 magenta, 3 red; phase1 splits at -V_T^L = 0 and B = 10 m, phase2 at both zeros
SHADING = {"phase1": (1, 2, 0, 3), "phase2": (2, 3, 1, 2)}


def _gap_mid(line: np.ndarray, first: int, second: int, lo: int, hi: int) -> float | None:
    """Midpoint of the gap between the last pixel of family `first` and the
    next pixel of family `second` in line[lo:hi] (the shading fades to
    white on both sides of a boundary), or None (ink in the way, or no
    such pair, or a gap over 120 px)."""
    last = None
    for i in range(lo, hi):
        v = line[i]
        if v == -2:
            return None
        if v == first:
            last = i
        elif v == second and last is not None:
            return (last + i) / 2.0 if i - last < 120 else None
    return None


def background_check(rgb, fr, ax, ay, area, cl, kind: str | None = None) -> dict:
    """Where the shading changes hue, in data units, as a check on the tick
    calibration. The shading is drawn in four hue families (SHADING) that
    change at -V_T^L = 0 on both plots, at B = 10 m on phase1 and at
    -V_T^U = 0 on phase2, fading to white on both sides of each change.
    Along rows and columns of bare shading within 150 px of where the
    tick calibration puts the boundary, the midpoint of the white gap
    between the two families is taken; the medians are returned
    (x_boundary, y_boundary) with their counts. kind is 'phase1' or
    'phase2' (None: no check)."""
    if kind not in SHADING:
        return {"x_boundary": None, "nx": 0, "y_boundary": None, "ny": 0}
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    fam = np.full(r.shape, -1, np.int8)
    fam[(np.abs(r - g) <= 4) & (np.abs(g - b) <= 4) & (r < 240)] = 0
    fam[(b >= 248) & (np.abs(r - g) <= 4) & (r < 240)] = 1
    fam[(r >= 248) & (b >= 248) & (g < 240)] = 2
    fam[(r >= 248) & (np.abs(g - b) <= 4) & (g < 240)] = 3
    fam[~cl["bg"] | ~area] = -2  # not shading (ink, markers, outside the plot)
    ul, ur, ll, lr = SHADING[kind]
    x0p = float(ax.pixel(0.0))
    y0p = float(ay.pixel(10.0 if kind == "phase1" else 0.0))
    xs, ys = [], []
    for y in range(fr.top_in + 3, fr.bottom_in - 2, 3):
        a, c = (ul, ur) if y < y0p else (ll, lr)
        m = _gap_mid(fam[y], a, c, int(max(fr.left_in + 3, x0p - 150)), int(min(fr.right_in - 3, x0p + 150)))
        if m is not None and abs(y - y0p) > 10:
            xs.append(m)
    for x in range(fr.left_in + 3, fr.right_in - 2, 3):
        a, c = (ul, ll) if x < x0p else (ur, lr)
        m = _gap_mid(fam[:, x], a, c, int(max(fr.top_in + 3, y0p - 150)), int(min(fr.bottom_in - 3, y0p + 150)))
        if m is not None and abs(x - x0p) > 10:
            ys.append(m)
    return {"x_boundary": float(ax.value(np.median(xs))) if xs else None, "nx": len(xs),
            "y_boundary": float(ay.value(np.median(ys))) if ys else None, "ny": len(ys)}


# ------------------------------------------------------------------ the two plots together
def _tol(ea: float, eb: float) -> float:
    return max(1.5, 3.0 * math.hypot(ea, eb))


def digitize_pair(phase1, phase2, cycle: dt.datetime | None = None) -> dict:
    """Digitize a storm's phase1 and phase2 plots and check them against
    each other. Both plots carry the same -V_T^L on x, the same intensity
    color and the same marker size at every hour, which this uses twice:

    - an hour timed on both plots whose two x values agree (within
      max(1.5 m, 3 times the combined error estimate)) is 'verified';
      one where they disagree is 'inconsistent' on both plots (only on
      the other one when one plot's walk is closed, its count confirmed),
      and then every other point of that plot's same walk (from C or
      from Z) that is not verified is dropped too, since one wrong count
      shifts the rest of the walk;
    - an hour timed on one plot only is looked for among the other plot's
      untimed discs: a single disc with that x (same tolerance), the same
      size (within 1.5 px or 12%) and color (RGB distance under 40, or
      100 for a disc under 5 px, whose X lightens its median color) takes
      the hour, flagged 'transferred' on that plot (its time rests on the
      first plot's walk alone), and the first plot's point is
      'single'.

    Returns {'phase1': result, 'phase2': result, 'rows': [...]} where each
    row is one hour >= 0 with hour, valid, b, vtl (phase1), vtu, vtl2
    (phase2), their errors, and flag1/flag2; a value is None where that
    plot has no usable point."""
    r1 = digitize_plot(phase1, cycle)
    r2 = digitize_plot(phase2, cycle)
    for r in (r1, r2):
        r["_pts"] = {p["hour"]: p for p in r["points"]}
    # agreement on hours both plots timed
    walks_bad = {1: set(), 2: set()}
    for h in sorted(set(r1["_pts"]) & set(r2["_pts"])):
        a, b = r1["_pts"][h], r2["_pts"][h]
        if abs(a["x"] - b["x"]) <= _tol(a["ex"], b["ex"]):
            a["check"] = b["check"] = "verified"
            continue
        # a walk whose count was confirmed (closed) outranks one that was not
        ca, cb = a.get("walk") == "closed", b.get("walk") == "closed"
        if ca != cb:
            bad, k = (b, 2) if ca else (a, 1)
            bad["check"] = "inconsistent"
            walks_bad[k].add(bad.get("walk"))
        else:
            a["check"] = b["check"] = "inconsistent"
            walks_bad[1].add(a.get("walk"))
            walks_bad[2].add(b.get("walk"))
    for k, r in ((1, r1), (2, r2)):
        for p in r["points"]:
            if "check" not in p and p.get("walk") in walks_bad[k]:
                p["check"] = "dropped"
    # transfer of single-plot hours to the other plot's untimed discs
    for src, dst in ((r1, r2), (r2, r1)):
        for h, p in list(src["_pts"].items()):
            if p.get("check") in ("inconsistent", "dropped", "verified"):
                continue
            if h in dst["_pts"] and dst["_pts"][h].get("check") not in ("inconsistent", "dropped"):
                continue
            q_src = next((d for d in src["discs"] if d["hour"] == h), None)
            if q_src is None:
                continue
            cands = [d for d in dst["discs"] if d["hour"] is None and
                     abs(d["x"] - p["x"]) <= _tol(p["ex"], d["ex"]) and
                     abs(d["r_px"] - q_src["r_px"]) <= max(1.5, 0.12 * q_src["r_px"]) and
                     math.dist(d["color"], q_src["color"]) < (40 if q_src["r_px"] >= 5 else 100)]
            if len(cands) == 1:
                d = cands[0]
                d["hour"] = h
                d["flag"] = "transferred"
                np_ = {"hour": h, "x": d["x"], "y": d["y"], "ex": d["ex"], "ey": d["ey"], "flag": d["flag"],
                       "r_px": d["r_px"], "check": "transferred", "walk": None}
                if "valid" in p:
                    np_["valid"] = p["valid"]
                dst["points"].append(np_)
                dst["_pts"][h] = np_
                p["check"] = "single"
    rows = []
    for h in sorted(set(r1["_pts"]) | set(r2["_pts"])):
        if h < 0:
            continue
        a, b = r1["_pts"].get(h), r2["_pts"].get(h)
        ok_a = a is not None and a.get("check", "single") not in ("inconsistent", "dropped")
        ok_b = b is not None and b.get("check", "single") not in ("inconsistent", "dropped")
        row = {"hour": h, "valid": (a or b).get("valid"),
               "b": a["y"] if ok_a else None, "vtl": a["x"] if ok_a else None,
               "e_b": a["ey"] if ok_a else None, "e_vtl": a["ex"] if ok_a else None,
               "vtu": b["y"] if ok_b else None, "vtl2": b["x"] if ok_b else None,
               "e_vtu": b["ey"] if ok_b else None,
               "flag1": (a.get("check", "single") + "/" + a["flag"]) if a else "missing",
               "flag2": (b.get("check", "single") + "/" + b["flag"]) if b else "missing"}
        rows.append(row)
    for r in (r1, r2):
        r.pop("_pts", None)
    return {"phase1": r1, "phase2": r2, "rows": rows}

# Digit templates cut from TEMPLATE_SOURCES by build_templates (python3 fsu_digitize.py --build-templates).
TEMPLATE_B64 = (
    "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"
)



# ------------------------------------------------------------------ command line
def debug_overlay(path, res: dict, out) -> None:
    """The plot at twice the size with every disc outlined (blue timed,
    orange crowded, yellow untimed, red conflicting) and its hour."""
    from PIL import ImageDraw
    with Image.open(path) as im:
        im = im.convert("RGB")
    S = 2
    big = im.resize((im.width * S, im.height * S), Image.NEAREST)
    dr = ImageDraw.Draw(big)
    colors = {"ok": (0, 120, 255), "open": (0, 200, 0), "crowded": (255, 128, 0), "untimed": (255, 220, 0),
              "conflict": (255, 0, 0), "transferred": (160, 0, 255)}
    for q in res["discs"]:
        x, y, r = q["x_px"] + 0.5, q["y_px"] + 0.5, q["r_px"]
        dr.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], outline=colors.get(q["flag"], (0, 0, 0)),
                   width=2)
        if q["hour"] is not None:
            dr.text(((x + r) * S + 2, (y - r) * S - 10), str(q["hour"]), fill=(0, 0, 160))
    big.save(out)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Digitize one FSU cyclone phase plot (see the module docstring).")
    ap.add_argument("png", nargs="?", help="fsu_phase1.png or fsu_phase2.png")
    ap.add_argument("--cycle", help="run time YYYYMMDDHH, for valid times")
    ap.add_argument("--debug", help="write an overlay of the discs found to this PNG")
    ap.add_argument("--build-templates", action="store_true",
                    help="cut the digit templates from TEMPLATE_SOURCES and print them as TEMPLATE_B64")
    a = ap.parse_args(argv)
    if a.build_templates:
        print(templates_to_b64(build_templates(Path(__file__).parent / "data")))
        return 0
    if not a.png:
        ap.error("a plot is needed")
    cyc = dt.datetime.strptime(a.cycle, "%Y%m%d%H") if a.cycle else None
    res = digitize_plot(a.png, cyc)
    print(json.dumps({k: res.get(k) for k in ("header", "quality", "spacing_h", "notes")}, default=str))
    for p in res["points"]:
        print(f"{p['hour']:5d} {p.get('valid', '')} x {p['x']:8.2f} +/- {p['ex']:.2f}  y {p['y']:8.2f} +/- "
              f"{p['ey']:.2f}  {p['flag']}")
    if a.debug:
        debug_overlay(a.png, res, a.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
