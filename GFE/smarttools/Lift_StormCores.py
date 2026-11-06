"""
Lift_StormCores - Add a few knots to the Wind grid where the models already show a strong core.

What it does, in forecaster terms: a blended Wind grid tends to smear out the
storm-force (48+ kt) core of a deep low.  This tool takes the Fcst Wind grid you
already have (usually from the blend procedure) and, wherever the stronger of
the deterministic GFS and ECMWF 10 m winds is at least the threshold, adds the
lift to the wind speed.  Direction is not touched.  It uses the newest GFS and
ECMWF run that has a 10 m wind grid for the grid's time.  If a selected edit
area exists only cells inside it change; otherwise the whole grid.

Options:
  GEFS storm floor - where the GEFS 48 kt probability is at least GEFS_FLOOR_P
      percent, raise Wind to at least 48 kt.
  HF ceiling check - changes nothing.  Counts the hurricane-force (64 kt+)
      cells in the result where the GFS 925 mb wind times a stability factor
      (from sea minus 2 m air temperature) is under HF_CEIL_KT, i.e. cells that
      probably peak at storm force at the surface, and reports the count.

Run it after the GFE blend over an OCEAN edit area: the scores below lifted
water cells only, and the tool lifts every cell in the edit area.

Scored on five held-out winter weeks (Nov 2025 - Mar 2026) against ASCAT,
5x5 deg storm tiles, Pacific including the 06/18Z passes (marine-research
studies/2026-11-06-gfe-wind-tool/findings.md).  Defaults (+6 kt where the
stronger model >= 42 kt):
    storm-force catch  Atlantic 35% -> 74%, Pacific 22% -> 63%
    storm area vs ASCAT 1.02x / 1.16x; false storm tiles 283 / 147
    gale-force areas unchanged
  Threshold 44 instead of 42: catch 69% / 57% at 0.81x / 0.87x area; same
  storm score, so pick 44 if storm area must stay under ASCAT's.
  Page Core Lifted on the same weeks: 62% / 40%.
  GEFS storm floor: adds almost nothing on top of the lift (left Off).
  HF is NOT fixed: HF catch 26% Atlantic.  Lift 10, threshold 44 raised
  Atlantic HF catch to 60% at 0.93x ASCAT's HF area (storm catch -2 pts);
  a setting to try for HF, not a scored pick.  The HF ceiling check was
  right 88% of the time when it called an HF cell "probably storm".
Greenland barrier and tip-jet flow (not scorable, ASCAT blind near coast):
trust the GFS family's strength there; ECMWF ran 10-20 kt low on 29 Oct.

Units: Wind is worked in knots internally and handed back in the Fcst Wind
units.  Model speeds are converted from the parm unit string (kt, m/s, mph).
If a D2D model's unit string is unknown, m/s is assumed when its maximum speed
is under 60, else knots; the closing message says so.
"""

from __future__ import annotations

import numpy as np

import SmartScript

import grid_fetch

ToolType = "numeric"
WeatherElementEdited = "Wind"
HideTool = 0
ScreenList = ["VECTOR"]

# Defaults picked on tune weeks (most storm catch, storm area <= ASCAT's, gales unchanged).
LIFT_KT = 6.0
THRESH_KT = 42.0
GEFS_FLOOR_P = 50.0  # percent
HF_CEIL_KT = 60.0
# (sea minus 2 m air below this edge, deg C -> factor on the 925 mb wind); None = no upper edge.
# Same bands as marine-research rk.features.hf_ceiling (pattern drill map-wide factors).
HF_CEIL_FACTORS = ((2.0, 0.70), (5.0, 0.79), (None, 0.83))

STORM_KT = 48.0
HF_KT = 64.0

WIND_SOURCES = [("wind", "FHAG10"), ("wind", "10FHAG"), ("Wind", "SFC")]
# Guesses: these names and levels must be checked on AWIPS.
GEFS_P48_SOURCES = [(e, lv) for e in ("prob48kt", "WindProb48", "probwind48")
                    for lv in ("FHAG10", "10FHAG", "SFC")]
WIND925_SOURCES = [("wind", "MB925"), ("wind", "925MB")]
SFC_T_SOURCES = [("t", "SFC"), ("tsfc", "SFC")]
AIR2M_T_SOURCES = [("t", "FHAG2"), ("t", "2FHAG")]

VariableList = [
    ("Lift (kt)", LIFT_KT, "numeric"),
    ("Where the stronger of GFS/ECMWF is at least (kt)", THRESH_KT, "numeric"),
    ("GEFS storm floor", "Off", "radio", ["Off", "On"]),
    ("HF ceiling check", "Off", "radio", ["Off", "On"]),
]

_TO_KT = {"kt": 1.0, "kts": 1.0, "knots": 1.0, "m/s": 1.943844, "mph": 0.868976}


def _first(grid):
    """Magnitude of a vector grid, or the scalar grid itself."""
    return np.asarray(grid[0] if isinstance(grid, (tuple, list)) else grid, dtype=float)


class Tool(SmartScript.SmartScript):
    """Lift Wind where the stronger of GFS and ECMWF is already strong."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def _fetch(self, alias, sources, tr):
        """Newest run of alias with one of the element/level pairs over tr.

        Returns (model_id, grid, unit_string) or None.
        """
        for model_id in grid_fetch._iter_database_ids(self, alias, run_depth=3, element="wind"):
            for elem, level in sources:
                try:
                    grid = self.getGrids(model_id, elem, level, tr, mode="First", noDataError=0)
                except Exception:
                    grid = None
                if grid is None:
                    continue
                try:
                    unit = str(self.getParm(model_id, elem, level).getGridInfo().getUnitString())
                except Exception:
                    unit = ""
                return model_id, grid, unit
        return None

    def _speed_kt(self, found, notes):
        """Speed in knots from a _fetch result, noting any unit assumption."""
        model_id, grid, unit = found
        spd = _first(grid)
        factor = _TO_KT.get(unit.strip().lower())
        if factor is None:
            if "D2D" in model_id.upper() and np.nanmax(spd) < 60:
                factor = _TO_KT["m/s"]
                notes.append("%s units unknown, assumed m/s" % model_id)
            else:
                factor = 1.0
                notes.append("%s units unknown, assumed kt" % model_id)
        return spd * factor

    def _temp_diff(self, tr):
        """Sea minus 2 m air temperature (deg C) or None."""
        sea, air = self._fetch("GFS", SFC_T_SOURCES, tr), self._fetch("GFS", AIR2M_T_SOURCES, tr)
        if sea is None or air is None:
            return None

        def celsius_scale(found):
            return 5.0 / 9.0 if found[2].strip().upper().endswith("F") else 1.0
        return _first(sea[1]) * celsius_scale(sea) - _first(air[1]) * celsius_scale(air)

    def _hf_check(self, mag_kt, tr):
        """Message about hurricane-force cells the 925 mb wind does not support."""
        hf = mag_kt >= HF_KT
        n_hf = int(hf.sum())
        w925 = self._fetch("GFS", WIND925_SOURCES, tr)
        diff = self._temp_diff(tr)
        if w925 is None or diff is None:
            return "HF check skipped: GFS 925 mb wind or surface/2 m temperature not found"
        factor = np.full(diff.shape, HF_CEIL_FACTORS[-1][1], dtype=float)
        for edge, fac in reversed(HF_CEIL_FACTORS[:-1]):
            factor = np.where(diff < edge, fac, factor)
        peak = self._speed_kt(w925, []) * factor
        n_flag = int((hf & (peak < HF_CEIL_KT)).sum())
        return ("%d of %d hurricane-force cells probably peak at storm force "
                "(925 mb x stability under %g kt)" % (n_flag, n_hf, HF_CEIL_KT))

    def execute(self, Wind, Wind_GridInfo, GridTimeRange, varDict, editArea=None):
        """Lift Wind speed where the stronger model wind is at least the threshold."""
        lift = float(varDict["Lift (kt)"])
        thresh = float(varDict["Where the stronger of GFS/ECMWF is at least (kt)"])
        mag, direction = Wind

        try:
            to_kt = _TO_KT.get(str(Wind_GridInfo.getUnitString()).strip().lower(), 1.0)
        except Exception:
            to_kt = 1.0
        mag_kt = np.asarray(mag, dtype=float) * to_kt

        mask = np.ones(mag_kt.shape, dtype=bool)
        if editArea is not None:
            try:
                mask = np.asarray(self.encodeEditArea(editArea), dtype=bool)
            except Exception:
                pass

        notes, used, missing, speeds = [], [], [], []
        for alias in ("GFS", "ECMWF"):
            found = self._fetch(alias, WIND_SOURCES, GridTimeRange)
            if found is None:
                missing.append(alias)
                continue
            used.append(found[0])
            speeds.append(self._speed_kt(found, notes))
        if not speeds:
            self.statusBarMsg("Lift_StormCores: no GFS or ECMWF 10 m wind found, Wind unchanged", "U")
            return Wind
        if missing:
            notes.append("%s missing, used %s only" % (" and ".join(missing), used[0]))
        strongest = np.fmax(speeds[0], speeds[-1])

        lifted = (strongest >= thresh) & mask
        new_kt = np.where(lifted, mag_kt + lift, mag_kt)

        floored = np.zeros(mask.shape, dtype=bool)
        if varDict.get("GEFS storm floor") == "On":
            found = self._fetch("GEFS", GEFS_P48_SOURCES, GridTimeRange)
            if found is None:
                notes.append("GEFS 48 kt probability not found, floor skipped")
            else:
                prob = _first(found[1])
                if np.nanmax(prob) <= 1.0:
                    prob = prob * 100.0
                floored = (prob >= GEFS_FLOOR_P) & mask & (new_kt < STORM_KT)
                new_kt = np.where(floored, STORM_KT, new_kt)
                used.append(found[0])

        if varDict.get("HF ceiling check") == "On":
            notes.append(self._hf_check(new_kt, GridTimeRange))

        self.statusBarMsg("Lift_StormCores: runs %s; %d cells lifted %g kt, %d floored to %g kt%s"
                          % (", ".join(used), int(lifted.sum()), lift, int(floored.sum()), STORM_KT,
                             "".join("; " + n for n in notes)), "R")
        return new_kt / to_kt, direction


__all__ = ["Tool"]
