"""Fog and freezing spray paragraphs for the High Seas Forecast draft (Jason 11-11).

Only at the synopsis, 24 h and 48 h, as the desk writes them, and with the same shapes as the
wind areas (box first, then a line; at most two pieces).

Fog: GFS surface visibility under FOG_VIS_M (1 nm). Desk wording:
    .DENSE FOG. VSBY OCCASIONALLY LESS THAN 1 NM <area>.
    .24 HOUR FORECAST DENSE FOG <area>.

Freezing spray: the Overland (1990) predictor the NWS uses,
    PPR = V (Tf - Ta) / (1 + 0.3 (Tw - Tf)),  V wind m/s, Ta air, Tw sea temperature C, Tf = -1.7 C
light under 22.4 (icing under 0.7 cm/h), moderate 22.4-53.3 (0.7-2 cm/h), heavy over 53.3
(2 cm/h and up). None over sea ice. Desk wording pairs the classes:
    LIGHT / LIGHT TO MODERATE / MODERATE TO HEAVY ... ELSEWHERE LIGHT TO MODERATE ...
and a time with heavy spray puts the whole paragraph under WARNINGS as
"...HEAVY FREEZING SPRAY WARNING...".

hazard_text(fields, sea, grid, rules) -> (warning_paragraph, synopsis_paragraphs, areas)
fields: {hour: dict(wind kt, t2 C, sst C, vis m, ice fraction)}; hours other than 0/24/48 are ignored.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from writer import clean, describe_parts

TF = -1.7                  # sea water freezing point, C
PPR_MODERATE = 22.4        # Overland class limits
PPR_HEAVY = 53.3
KT_TO_MS = 0.514444
HOURS = (0, 24, 48)


@dataclass
class HazardRules:
    # tuned on the last 30 days (00/12Z 12 Oct - 10 Nov 2026) against the desk's issued areas:
    # fog under 1 nm with 60-cell patches draws about the desk's area (Pacific 0.93x, Atlantic
    # 1.15x) and holds 40-50% of it; spray with 20-cell patches draws the desk's area in the
    # Atlantic (1.0x)
    fog_vis_m: float = 1852.0     # GFS surface visibility under 1 nm
    fog_min_cells: int = 60       # smallest fog patch worth a phrase (0.25 deg cells, ~3.75 sq deg)
    spray_min_cells: int = 20
    ice_max: float = 0.5          # no spray where GFS sea ice covers this share or more
    sst_min: float = -2.0         # GFS surface temperature under this is ice skin, not open water
    lake_cells: int = 1000        # water bodies smaller than this are lakes (Great Bear, Great Slave)
    max_parts: int = 2


def overland_ppr(wind_kt, t2_c, sst_c):
    """Overland icing predictor; 0 where air is not below the freezing point of sea water."""
    v = np.asarray(wind_kt, float) * KT_TO_MS
    tw = np.maximum(np.asarray(sst_c, float), TF)
    ppr = v * (TF - np.asarray(t2_c, float)) / (1.0 + 0.3 * (tw - TF))
    return np.where(np.isfinite(ppr), np.maximum(ppr, 0.0), 0.0)


def spray_class(wind_kt, t2_c, sst_c, ice=None, ice_max=0.5):
    """0 none, 1 light, 2 moderate, 3 heavy (heavy and extreme together)."""
    ppr = overland_ppr(wind_kt, t2_c, sst_c)
    cls = np.where(ppr >= PPR_HEAVY, 3, np.where(ppr >= PPR_MODERATE, 2, np.where(ppr > 0, 1, 0)))
    if ice is not None:
        cls = np.where(np.nan_to_num(ice) >= ice_max, 0, cls)
    return cls


def _lead(h):
    return "." if h == 0 else ".%d HOUR FORECAST " % h


def _phrase(mask, sea, grid, wrules, hr):
    return describe_parts(mask, sea, grid, [], wrules, max_parts=hr.max_parts)


def fog_lines(fields, sea, grid, wrules, hr):
    lines, areas, first = [], [], True
    for h in HOURS:
        f = fields.get(h)
        if f is None or f.get("vis") is None:
            continue
        m = clean(np.nan_to_num(f["vis"], nan=1e9) < hr.fog_vis_m, sea, wrules, hr.fog_min_cells)
        if not m.any():
            continue
        p = _phrase(m, sea, grid, wrules, hr)
        head = "DENSE FOG. VSBY OCCASIONALLY LESS THAN 1 NM" if first else "DENSE FOG"
        lines.append("%s%s %s." % (_lead(h), head, p["text"]))
        areas.append(dict(hour=h, kind="fog", level="dense", text=p["text"], mask=p["mask"]))
        first = False
    return lines, areas


def spray_lines(fields, sea, grid, wrules, hr):
    lines, areas, heavy = [], [], False
    for h in HOURS:
        f = fields.get(h)
        if f is None or any(f.get(k) is None for k in ("t2", "sst", "wind")):
            continue
        cls = spray_class(f["wind"], f["t2"], f["sst"], f.get("ice"), hr.ice_max)
        cls = np.where(np.nan_to_num(f["sst"], nan=-99.0) < hr.sst_min, 0, cls)
        anyc = clean(cls >= 1, sea, wrules, hr.spray_min_cells)
        if not anyc.any():
            continue
        hv = clean(cls >= 3, sea, wrules, hr.spray_min_cells) & anyc
        if hv.any():
            heavy = True
            p = _phrase(hv, sea, grid, wrules, hr)
            text = "%sMODERATE TO HEAVY FREEZING SPRAY %s." % (_lead(h), p["text"])
            areas.append(dict(hour=h, kind="spray", level="heavy", text=p["text"], mask=p["mask"]))
            rest = anyc & ~p["mask"]
            if clean(rest, sea, wrules, hr.spray_min_cells).any():
                word = "LIGHT TO MODERATE" if (cls[rest] >= 2).any() else "LIGHT"
                q = _phrase(anyc, sea, grid, wrules, hr)
                if q["text"] != p["text"]:
                    text += " ELSEWHERE %s FREEZING SPRAY %s." % (word, q["text"])
                    areas.append(dict(hour=h, kind="spray", level="light", text=q["text"], mask=q["mask"] & ~p["mask"]))
        else:
            word = "LIGHT TO MODERATE" if (cls[anyc] >= 2).any() else "LIGHT"
            p = _phrase(anyc, sea, grid, wrules, hr)
            text = "%s%s FREEZING SPRAY %s." % (_lead(h), word, p["text"])
            areas.append(dict(hour=h, kind="spray", level="light", text=p["text"], mask=p["mask"]))
        lines.append(text)
    return lines, areas, heavy


def open_sea(sea, min_cells):
    """sea without lakes: connected water bodies under min_cells cells dropped (the wave grid
    and the forecast outline both keep Great Bear and Great Slave Lake)."""
    lab, n = ndimage.label(sea)
    if n == 0:
        return sea
    sizes = ndimage.sum(sea, lab, range(1, n + 1))
    return np.isin(lab, [i + 1 for i, s_ in enumerate(sizes) if s_ >= min_cells])


def hazard_text(fields, sea, grid, wrules, hr=None):
    """(warning paragraph or "", [synopsis paragraphs in desk order: fog, then spray], areas)."""
    hr = hr or HazardRules()
    sea = open_sea(sea, hr.lake_cells)
    fog, fog_a = fog_lines(fields, sea, grid, wrules, hr)
    spray, spray_a, heavy = spray_lines(fields, sea, grid, wrules, hr)
    warn, syn = "", []
    if fog:
        syn.append("\n".join(fog))
    if spray:
        if heavy:
            warn = "...HEAVY FREEZING SPRAY WARNING...\n" + "\n".join(spray)
        else:
            syn.append("\n".join(spray))
    return warn, syn, fog_a + spray_a
