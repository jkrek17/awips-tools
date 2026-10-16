"""Read an issued High Seas Forecast (HSFEP1 / HSFAT1): fetch it from the IEM text archive
and turn it into map shapes, to compare the draft with what the desk sent.

Shape rules follow Jason's map parser (reference/README.md):
  quadrant  = bearing +-45 deg around the named direction, semicircle +-90
  WITHIN R NM <dirs> OF A LINE/FRONT FROM ...  = hull of the line and the line moved R nm each way named
  WITHIN R NM OF A LINE/FRONT FROM ...         = R nm either side of the line
  <dirs> OF A LINE FROM ...                    = the line closed off at the forecast-area edge on that side
  FROM aN TO bN BETWEEN x AND y                = lat/lon box; open sides run to the area edge
  AREA BOUNDED BY p1 TO p2 ...                 = that polygon
Pieces in one area joined by AND / ... are unioned; pieces written back to back
("N OF 30N WITHIN 1200 NM S SEMICIRCLE") are intersected.

parse(text, basin) -> dict(issued=..., synopsis_valid=datetime, units, blocks=[...])
each block: warning, hour (0 = synopsis), lows [(lat, lon, mb)], tier (first/also/elsewhere),
            area (shapely geometry, lon 0-360 in the Pacific, -180..180 in the Atlantic),
            area_text, wind (lo, hi), seas_m (lo, hi), parsed (bool: every piece understood)
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import unary_union

from areas import AREAS as _OUTLINES   # noqa: E402

# forecast areas as shapely polygons (Pacific lon 0-360, Atlantic -180..180, as parsed)
AREAS = {"pac": Polygon(_OUTLINES["pac"]), "atl": Polygon([(x - 360, y) for x, y in _OUTLINES["atl"]])}
PIL = {"pac": "HSFEP1", "atl": "HSFAT1"}
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=%s&fmt=text&limit=%d"
DIRS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
R_EARTH_NM = 3440.065
LL = r"\d+(?:\.\d+)?[NS]\d+(?:\.\d+)?[EW]"
D = r"(?:NE|NW|SE|SW|N|E|S|W)"
SEP = r"(?:\s*,\s*|\s*\.\.\.\s*(?:AND\s+)?|\s+AND\s+|\s+)"
DLIST = D + r"(?:" + SEP + D + r")*"
PTS = r"(?:" + LL + r"|(?:THE )?LOW(?: CENTER)?)"
PLIST = PTS + r"(?:(?: TO |\s*\.\.\.\s*)" + PTS + r")+"


def lon_of(v, hemi, basin):
    v = float(v)
    if hemi == "W":
        return 360 - v if basin == "pac" else -v
    return v if basin == "pac" or v <= 180 else v - 360


def pt(s, basin):
    m = re.match(r"(\d+(?:\.\d+)?)([NS])(\d+(?:\.\d+)?)([EW])", s)
    lat = float(m.group(1)) * (1 if m.group(2) == "N" else -1)
    return lat, lon_of(m.group(3), m.group(4), basin)


def dest(lat, lon, brg, nm):
    """Great-circle destination (lat, lon) from a start, bearing (deg) and distance (nm)."""
    p1, l1, b, d = math.radians(lat), math.radians(lon), math.radians(brg), nm / R_EARTH_NM
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def sector(lat, lon, nm, a0, a1, inner=0.0):
    angs = [a0 + (a1 - a0) * i / 36 for i in range(37)]
    outer = [dest(lat, lon, a, nm)[::-1] for a in angs]
    if inner > 0:
        ring = outer + [dest(lat, lon, a, inner)[::-1] for a in angs[::-1]]
    elif a1 - a0 >= 360:
        ring = outer
    else:
        ring = [(lon, lat)] + outer
    return Polygon(ring).buffer(0)


def dirs_of(s):
    return re.findall(D, s)


def line_pts(s, basin, lows):
    out = []
    for tok in re.split(r"\s+TO\s+|\s*\.\.\.\s*", s.strip()):
        tok = tok.strip()
        if re.fullmatch(LL, tok):
            out.append(pt(tok, basin))
        elif re.fullmatch(r"(?:THE\s+)?LOW(?:\s+CENTER)?", tok) and lows:
            out.append(lows[0][:2])
        else:
            m = re.search(LL, tok)
            if m:
                out.append(pt(m.group(0), basin))
    return out


def side_poly(points, dirs, area):
    """<dirs> OF A LINE: close the line off at the forecast-area edge on that side."""
    b = sum(DIRS[d] for d in dirs) / len(dirs) if dirs else 0
    if len(dirs) == 2 and abs(DIRS[dirs[0]] - DIRS[dirs[1]]) > 180:   # e.g. N AND NW
        b = (DIRS[dirs[0]] + DIRS[dirs[1]] + 360) / 2 % 360
    dy, dx = math.cos(math.radians(b)), math.sin(math.radians(b))
    far = 25.0
    ln = [(lo, la) for la, lo in points]
    shifted = [(x + dx * far, y + dy * far) for x, y in ln[::-1]]
    full = ln
    return Polygon(full + shifted).buffer(0).intersection(area)


def buffer_line(points, nm, dirs, area):
    allp = []
    for la, lo in points:
        allp.append((lo, la))
        for d in (dirs or list(DIRS)):
            for b in ([DIRS[d]] if dirs else [DIRS[d]]):
                p = dest(la, lo, b, nm)
                allp.append((p[1], p[0]))
    if dirs:
        return MultiPoint(allp).convex_hull.intersection(area)
    # both sides: buffer each segment (degrees, scaled by latitude) for a sausage shape
    segs = []
    for (la0, lo0), (la1, lo1) in zip(points[:-1], points[1:]):
        hull = []
        for la, lo in ((la0, lo0), (la1, lo1)):
            for b in range(0, 360, 15):
                p = dest(la, lo, b, nm)
                hull.append((p[1], p[0]))
        segs.append(MultiPoint(hull).convex_hull)
    return unary_union(segs).intersection(area)


# one regex per construct; earlier ones win at the same position
CONSTRUCTS = [
    ("annulus", r"BETWEEN (\d+) NM AND (\d+) NM (" + DLIST + r") (QUADRANTS?|SEMICIRCLES?)"),
    ("radial", r"WITHIN ((?:(?:\d+(?: NM)?\s+)?" + D + SEP + r")+?)(QUADRANTS?|QUARANTS?|QUADSRANTS?|SEMICIRCLES?)(?: OF ((?:THE )?(?:MAIN |FIRST |FIST |SECOND |SECONDARY |THIRD |NEW |SECOND NEW |NEWER |WESTERN |EASTERN |NORTHERN |SOUTHERN )?(?:LOW|CENTER)|(" + LL + r")))?"),
    ("circle", r"WITHIN (\d+) NM OF (?:THE )?(?:LOW|CENTER|(" + LL + r"))(?: CENTER)?"),
    ("linebuf_side", r"WITHIN (\d+) NM (" + DLIST + r") OF (?:A |THE )?(?:LINE|FRONT|TROUGH|COLD FRONT|WARM FRONT|STATIONARY FRONT|OCCLUDED FRONT)?\s*(?:FROM )?((?:" + LL + r"|(?:THE )?LOW(?: CENTER)?)(?: TO (?:" + LL + r"|(?:THE )?LOW(?: CENTER)?))+)"),
    ("linebuf", r"WITHIN (\d+) NM (?:EITHER SIDE )?OF (?:A |THE )?(?:LINE|FRONT|TROUGH|COLD FRONT|WARM FRONT|STATIONARY FRONT|OCCLUDED FRONT)?\s*(?:FROM )?((?:" + LL + r"|(?:THE )?LOW(?: CENTER)?)(?: TO (?:" + LL + r"|(?:THE )?LOW(?: CENTER)?))+)"),
    ("bounded", r"(?:WITHIN )?(?:AN )?(?:AREA )?BOUNDED BY (?:A LINE )?(?:FROM )?(" + PLIST + r")"),
    ("side", r"(" + DLIST + r") OF (?:A |THE )?(?:LINE|FRONT|TROUGH|COLD FRONT|WARM FRONT|STATIONARY FRONT|OCCLUDED FRONT)? ?(?:FROM )?(" + PLIST + r")"),
    ("box", r"FROM (\d+(?:\.\d+)?)N TO (\d+(?:\.\d+)?)N BETWEEN (\d+(?:\.\d+)?)([EW]) AND (\d+(?:\.\d+)?)([EW])"),
    ("latband_lon", r"FROM (\d+(?:\.\d+)?)N TO (\d+(?:\.\d+)?)N ([EW]) OF (\d+(?:\.\d+)?)([EW])"),
    ("latband", r"FROM (\d+(?:\.\d+)?)N TO (\d+(?:\.\d+)?)N"),
    ("half_box", r"\b([NS]) OF (\d+(?:\.\d+)?)N BETWEEN (\d+(?:\.\d+)?)([EW]) AND (\d+(?:\.\d+)?)([EW])"),
    ("half_lon", r"\b([NS]) OF (\d+(?:\.\d+)?)N ([EW]) OF (\d+(?:\.\d+)?)([EW])"),
    ("half", r"\b([NS]) OF (\d+(?:\.\d+)?)N\b"),
    ("lonhalf", r"\b([EW]) OF (\d+(?:\.\d+)?)([EW])\b"),
    ("lonband", r"BETWEEN (\d+(?:\.\d+)?)([EW]) AND (\d+(?:\.\d+)?)([EW])"),
]
CRE = re.compile("|".join("(?P<%s>%s)" % (n, p) for n, p in CONSTRUCTS))


def lon_span(a, b, area):
    """The shorter of the two arcs between two longitudes, as (west, east)."""
    lo, hi = sorted((a, b))
    return (lo, hi)


def shape_of(kind, m, basin, lows, area):
    g = m.groups()
    x0, y0, x1, y1 = area.bounds
    sub = lambda name: m.group(name)
    txt = m.group(0)
    if kind in ("radial", "annulus"):
        if not lows:
            return None
        which = 0
        ref = re.search(r"OF ((?:THE )?(?:MAIN |FIRST |FIST |SECOND |SECONDARY |THIRD |NEW |SECOND NEW |NEWER |WESTERN |EASTERN |NORTHERN |SOUTHERN )?(?:LOW|CENTER)|" + LL + r")$", txt)
        if ref and re.search(r"SECOND", ref.group(1)) and len(lows) > 1:
            which = 1
        if ref and "THIRD" in ref.group(1) and len(lows) > 2:
            which = 2
        lat, lon = lows[which][:2]
        if ref and re.fullmatch(LL, ref.group(1)):
            lat, lon = pt(ref.group(1), basin)
        semi = "SEMI" in txt
        half = 90 if semi else 45
        shapes = []
        if kind == "annulus":
            mm = re.match(r"BETWEEN (\d+) NM AND (\d+) NM (.*?) (?:QUADRANTS?|SEMICIRCLES?)", txt)
            r_in, r_out = float(mm.group(1)), float(mm.group(2))
            for d in dirs_of(mm.group(3)):
                shapes.append(sector(lat, lon, r_out, DIRS[d] - half, DIRS[d] + half, r_in))
        else:
            body = re.match(r"WITHIN (.*?)(?:QUADRANTS?|QUARANTS?|QUADSRANTS?|SEMICIRCLES?)", txt).group(1)
            rad = None
            for tok in re.findall(r"\d+(?: NM)?|" + D + r"\b", body):
                if tok[0].isdigit():
                    rad = float(tok.split()[0])
                elif rad:
                    shapes.append(sector(lat, lon, rad, DIRS[tok] - half, DIRS[tok] + half))
        return unary_union(shapes).intersection(area) if shapes else None
    if kind == "circle":
        mm = re.match(r"WITHIN (\d+) NM OF (?:THE )?(?:LOW|CENTER|(" + LL + r"))", txt)
        if mm.group(2):
            lat, lon = pt(mm.group(2), basin)
        elif lows:
            lat, lon = lows[0][:2]
        else:
            return None
        return sector(lat, lon, float(mm.group(1)), 0, 360).intersection(area)
    if kind in ("linebuf_side", "linebuf"):
        mm = re.match(CONSTRUCTS[[c[0] for c in CONSTRUCTS].index(kind)][1], txt)
        nm = float(mm.group(1))
        dirs = dirs_of(mm.group(2)) if kind == "linebuf_side" else []
        p = line_pts(mm.group(3) if kind == "linebuf_side" else mm.group(2), basin, lows)
        return buffer_line(p, nm, dirs, area) if len(p) >= 2 else None
    if kind == "bounded":
        p = line_pts(re.search(r"BOUNDED BY (.*)", txt).group(1), basin, lows)
        return Polygon([(lo, la) for la, lo in p]).buffer(0).intersection(area) if len(p) >= 3 else None
    if kind == "side":
        mm = re.match(CONSTRUCTS[[c[0] for c in CONSTRUCTS].index("side")][1], txt)
        p = line_pts(mm.group(2), basin, lows)
        return side_poly(p, dirs_of(mm.group(1)), area) if len(p) >= 2 else None
    if kind == "box":
        mm = re.match(CONSTRUCTS[[c[0] for c in CONSTRUCTS].index("box")][1], txt)
        la = sorted((float(mm.group(1)), float(mm.group(2))))
        w, e = lon_span(lon_of(mm.group(3), mm.group(4), basin), lon_of(mm.group(5), mm.group(6), basin), area)
        return box(w, la[0], e, la[1]).intersection(area)
    if kind == "latband_lon":
        mm = re.match(CONSTRUCTS[[c[0] for c in CONSTRUCTS].index("latband_lon")][1], txt)
        la = sorted((float(mm.group(1)), float(mm.group(2))))
        lo = lon_of(mm.group(4), mm.group(5), basin)
        w, e = (x0, lo) if mm.group(3) == "W" else (lo, x1)
        return box(w, la[0], e, la[1]).intersection(area)
    if kind == "latband":
        mm = re.match(r"FROM (\S+)N TO (\S+)N", txt)
        la = sorted((float(mm.group(1)), float(mm.group(2))))
        return box(x0, la[0], x1, la[1]).intersection(area)
    if kind in ("half_box", "half_lon", "half"):
        mm = re.match(CONSTRUCTS[[c[0] for c in CONSTRUCTS].index(kind)][1], txt)
        la = float(mm.group(2))
        s, n = (la, y1) if mm.group(1) == "N" else (y0, la)
        w, e = x0, x1
        if kind == "half_box":
            w, e = lon_span(lon_of(mm.group(3), mm.group(4), basin), lon_of(mm.group(5), mm.group(6), basin), area)
        elif kind == "half_lon":
            lo = lon_of(mm.group(4), mm.group(5), basin)
            w, e = (x0, lo) if mm.group(3) == "W" else (lo, x1)
        return box(w, s, e, n).intersection(area)
    if kind == "lonhalf":
        mm = re.match(CONSTRUCTS[[c[0] for c in CONSTRUCTS].index("lonhalf")][1], txt)
        lo = lon_of(mm.group(2), mm.group(3), basin)
        w, e = (x0, lo) if mm.group(1) == "W" else (lo, x1)
        return box(w, y0, e, y1).intersection(area)
    if kind == "lonband":
        mm = re.match(CONSTRUCTS[[c[0] for c in CONSTRUCTS].index("lonband")][1], txt)
        w, e = lon_span(lon_of(mm.group(1), mm.group(2), basin), lon_of(mm.group(3), mm.group(4), basin), area)
        return box(w, y0, e, y1).intersection(area)
    return None


FILLER = re.compile(r"^(?:\s|\.|,|AND|IN THE BERING SEA|BERING SEA|IN THE GULF OF ALASKA|ALSO|ELSEWHERE|WITHIN|OF MAIN LOW|OF SECOND LOW|OF THE LOW|OF LOW|OF NEW LOW|THE|FORECAST|WATERS|AREA|IN|INCLUDING|THE AREA|AS WELL AS|EXCEPT FOR)*$")


def area_shape(text, basin, lows):
    """Area text -> (geometry or None, fully_parsed)."""
    area = AREAS[basin]
    text = re.sub(r"\s+", " ", text).strip()
    # "WITHIN 300 NM S SEMICIRCLE AND 240 NM NW QUADRANT": the second group drops WITHIN
    text = re.sub(r"((?:QUADRANTS?|SEMICIRCLES?)(?: OF (?:THE )?(?:MAIN |FIRST |FIST |SECOND |SECONDARY |THIRD |NEW |SECOND NEW |NEWER |WESTERN |EASTERN |NORTHERN |SOUTHERN )?(?:LOW|CENTER))?\s*(?:\.\.\.\s*)?(?:AND\s+|,\s*)?)(?=\d+ NM )", r"\1WITHIN ", text)
    text = re.sub(r"\s+(?:AREA OF )?(?:MIXED )?" + D + r" TO " + D + r"(?: SWELL)?$", "", text)
    text = re.sub(r"\bAREA OF (?:MIXED )?" + D + r"(?: TO " + D + r")?(?: SWELL)?\b", "", text)
    pieces, ok, pos, prev_end, join_and = [], True, 0, 0, []
    for m in CRE.finditer(text):
        gap = text[prev_end:m.start()]
        if not FILLER.match(gap.replace("...", " ")):
            ok = False
        kind = m.lastgroup
        g = shape_of(kind, m, basin, lows, area)
        if g is None or g.is_empty:
            ok = False if g is None else ok
            prev_end = m.end()
            continue
        OPEN = ("latband", "half", "lonhalf", "side", "latband_lon", "half_lon", "lonband")
        sep_union = bool(re.search(r"AND|\.\.\.|,", gap)) or not pieces
        # "FROM 30N TO 56N AND W OF A LINE ...": a plain AND between open-ended limits narrows the area
        if pieces and re.fullmatch(r"\s*AND\s*", gap) and (kind in OPEN or pieces[-1][2] in OPEN):
            sep_union = False
        pieces.append((g, sep_union, kind))
        prev_end = m.end()
    tail = text[prev_end:]
    if not FILLER.match(tail.replace("...", " ")):
        ok = False
    if not pieces:
        return None, False
    groups = []
    for g, union, _k in pieces:
        if union or not groups:
            groups.append(g)
        else:
            groups[-1] = groups[-1].intersection(g)
    return unary_union(groups), ok


def seas_of(s, units):
    m = re.search(r"SEAS (?:TO )*(\d+(?:\.\d+)?)(?: TO (\d+(?:\.\d+)?))? (M|FT)\b", s)
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    if re.search(r"SEAS TO \d", s) and not m.group(2):
        lo, hi = 0.0, lo
    f = 0.3048 if m.group(3) == "FT" else 1.0
    return round(lo * f, 1), round(hi * f, 1)


WIND_RE = re.compile(r"WINDS? (?:(\d+) TO )?(\d+) KT\.?\s*(?:SEAS ((?:TO )*\d+(?:\.\d+)?(?: TO \d+(?:\.\d+)?)? ?(?:M|FT)\b)\.?)?")


def parse_paragraph(p, basin):
    """One '.'-led paragraph -> (hour, lows, blocks[(tier, area_text, wind, seas)])."""
    p = re.sub(r"\s+", " ", p).strip()
    hour = 0
    m = re.match(r"(\d+) HOUR FORECAST\s*", p)
    if m:
        hour = int(m.group(1))
        p = p[m.end():]
    lows = [(*pt(x.group(1), basin), int(x.group(2))) for x in re.finditer(r"(" + LL + r") (\d{3,4}) MB", p)]
    # the system sentence ends at the first '. ' after MB / MOVING ... KT / STATIONARY
    head_end = 0
    hm = re.search(r"\d{3,4} MB(?:[^.]*?(?:MOVING [^.]*?|STATIONARY|DRIFTING[^.]*?|NEARLY STATIONARY))?\.", p)
    if hm and hm.start() < 200:
        head_end = hm.end()
    elif re.match(r"(?:LOW|COMPLEX|NEW|HIGH|FRONT|TROUGH)[^.]*?\.", p) and not re.match(r"[^.]*WINDS", p.split(".")[0]):
        head_end = p.find(".") + 1
    rest = p[head_end:]
    # FRONT TO EXTEND FROM ... sentences are context, not areas
    fm = re.search(r"FRONT (?:TO )?EXT?EN(?:D|DS|DING) FROM ((?:" + LL + r"|(?:THE )?(?:LOW|MAIN CENTER|SECOND CENTER|CENTER)(?: CENTER)?)(?: TO (?:" + LL + r"))+)", p)
    rest = re.sub(r"(?:A |THE )?(?:COLD |WARM |OCCLUDED |STATIONARY )?FRONT (?:TO )?EXT?EN(?:D|DS|DING) FROM [^.]*\.", " ", rest)
    if fm:
        fpts = re.sub(r"(?:THE )?(?:MAIN CENTER|SECOND CENTER|CENTER)", "LOW", fm.group(1))
        rest = re.sub(r"OF (?:THE )?FRONT\b(?! FROM)", "OF A LINE FROM " + fpts, rest)
    blocks, pos = [], 0
    for wm in WIND_RE.finditer(rest):
        seg = rest[pos:wm.start()].strip(" .")
        tier = "first"
        if re.match(r"ALSO\b", seg):
            tier, seg = "also", seg[4:].strip()
        elif re.match(r"ELSEWHERE\b", seg):
            tier, seg = "elsewhere", seg[9:].strip()
        lo = int(wm.group(1)) if wm.group(1) else 0
        seas = seas_of("SEAS " + wm.group(3), None) if wm.group(3) else None
        blocks.append((tier, seg, (lo, int(wm.group(2))), seas))
        pos = wm.end()
        # skip trailing ...HIGHEST qualifiers / EXCEPT clauses on seas
        q = re.match(r"\.*\s*(?:HIGHEST|EXCEPT|LOCALLY|WITH|IN MIXED|IN [NSEW]+ SWELL|PRIMARILY)(?:[^.]|\.(?=\d))*\.(?=\s|$)", rest[pos:])
        if q:
            pos += q.end()
    return hour, lows, blocks, p


def parse(prod, basin="pac"):
    txt = prod.replace("\r", "")
    out = dict(blocks=[], issued=None, synopsis_valid=None)
    m = re.search(r"\n(\d{3,4}) UTC (\w{3}) (\w{3}) (\d+) (\d{4})", txt)
    if m:
        out["issued"] = datetime.strptime("%s %s %s %04d" % (m.group(5), m.group(3), m.group(4), int(m.group(1))), "%Y %b %d %H%M")
    m = re.search(r"SYNOPSIS VALID (\d{4}) UTC (\w{3}) (\d+)", txt)
    if m and out["issued"]:
        v = datetime.strptime("%d %s %s %s" % (out["issued"].year, m.group(2), m.group(3), m.group(1)), "%Y %b %d %H%M")
        if v - out["issued"] > timedelta(days=200):
            v = v.replace(year=v.year - 1)
        out["synopsis_valid"] = v
    out["units"] = "M" if re.search(r"SEAS[^.]*?\d M\b", txt) else "FT"
    body = txt.split(".WARNINGS.", 1)[-1].split(".FORECASTER", 1)[0]
    body = body.split(".SYNOPSIS AND FORECAST.", 1)
    sections = [(re.split(r"\n(?=\.\.\.[A-Z ]+?\.\.\.)", body[0]), True)]
    if len(body) > 1:
        sections.append(([body[1]], False))
    for chunks, warn in sections:
        for ch in chunks:
            hm = re.match(r"\s*\.\.\.([A-Z ]+?)\.\.\.", ch)
            warning = hm.group(1).strip() if (hm and warn) else ("NONE" if not warn else "")
            if hm:
                ch = ch[hm.end():]
            sys_lows = []
            ch = re.sub(r"\.\s+(?=\d{1,2} HOUR FORECAST)", ".\n.", ch)
            for para in re.split(r"(?:^|\n)\s*\.(?=[A-Z0-9])", ch):
                if "WINDS" not in para and " MB" not in para:
                    continue
                hour, lows, blocks, flat = parse_paragraph(para, basin)
                if lows:
                    sys_lows = lows
                use = lows or ([] if re.search(r"DISSIPATED|INLAND|MOVED", flat) else sys_lows)
                for tier, atext, wind, seas in blocks:
                    geom, ok = area_shape(atext, basin, use)
                    out["blocks"].append(dict(warning=warning, hour=hour, lows=lows, tier=tier, area=geom,
                                              area_text=atext, wind=wind, seas_m=seas, parsed=ok and geom is not None,
                                              para=flat))
    return out


def fetch(basin, synopsis, limit=8):
    """The OPC part of the newest issued product whose synopsis is `synopsis` (naive UTC),
    from the IEM archive, or None (not issued yet, or the archive is unreachable)."""
    import requests
    try:
        r = requests.get(IEM % (PIL[basin], limit), timeout=60)
        r.raise_for_status()
    except requests.RequestException:
        return None
    for prod in r.text.split("\x01"):
        prod = prod.split("\x03")[0].strip()
        if not prod:
            continue
        opc = prod.split(".FORECASTER", 1)[0]
        tail = prod.split(".FORECASTER", 1)[1].split("\n", 1)[0] if ".FORECASTER" in prod else ""
        p = parse(opc + (".FORECASTER" + tail if tail else ""), basin)
        if p["synopsis_valid"] == synopsis:
            return opc.rstrip() + ("\n\n.FORECASTER" + tail if tail else ""), p
    return None
