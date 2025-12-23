"""
Populate_IceAccretion - Calculate ship icing potential using Overland algorithm.

Modularized version using shared model alias utilities.
Original Author: Pete Banacos (WFO BTV)
"""

from __future__ import annotations

import numpy as np

import SmartScript
import TimeRange

import model_aliases
import thresholds

ToolType = "numeric"
WeatherElementEdited = "IceAccretion"

# Build model choices from alias registry
_TEMP_MODELS = ["GFS", "ECMWF"]
_SST_MODELS = ["RTOFS", "Fcst"]

VariableList = [
    ("Populate IceAccretion (Modularized)", "", "label"),
    ("Model for Temps:", "GFS", "radio", _TEMP_MODELS),
    ("Model Run for Temps:", "Current", "radio", ["Current", "Previous"]),
    ("Model for SST:", "RTOFS", "radio", _SST_MODELS),
    ("Model Run for SST:", "Current", "radio", ["Current", "Previous"]),
]


class Tool(SmartScript.SmartScript):
    """Determine IceAccretion based on air temp, SST and winds using Overland algorithm."""

    # Default freezing point of sea water in Celsius
    TF_CELSIUS = -1.7

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def _get_model_database(self, alias: str, run: str):
        """Resolve model alias to database, with fallback."""
        try:
            candidates = model_aliases.get_gfe_databases(alias)
            gfe_db = candidates[0] if candidates else f"D2D_{model_aliases.resolve_alias(alias)}"
        except Exception:
            gfe_db = f"D2D_{alias}"

        offset = 0 if run == "Current" else -1
        return self.findDatabase(gfe_db, offset)

    def execute(self, IceAccretion, Wind, GridTimeRange, varDict):
        """Calculate ice accretion potential."""
        self.log("Starting Populate_IceAccretion (modularized)")

        temp_alias = varDict["Model for Temps:"]
        temp_run = varDict["Model Run for Temps:"]
        sst_alias = varDict["Model for SST:"]
        sst_run = varDict["Model Run for SST:"]

        # Get temperature model database
        temp_db = self._get_model_database(temp_alias, temp_run)
        if temp_db is None:
            self.statusBarMsg(f"Could not find temperature model {temp_alias}", "S")
            return IceAccretion

        # Get SST model database
        sst_db = self._get_model_database(sst_alias, sst_run)
        if sst_db is None:
            self.statusBarMsg(f"Could not find SST model {sst_alias}", "S")
            return IceAccretion

        self.log(f"Air Temp model: {temp_db}")
        self.log(f"SST model: {sst_db}")

        # Get temperature grid (Fahrenheit from GFE)
        try:
            temp_f = self.getGrids(temp_db, "T", "SFC", GridTimeRange)
        except Exception:
            # Fallback to previous run
            temp_db = self._get_model_database(temp_alias, "Previous")
            temp_f = self.getGrids(temp_db, "T", "SFC", GridTimeRange)
            self.statusBarMsg("Previous model run used for temperature grids", "R")

        # Convert F to C
        temp_c = thresholds.f_to_c(temp_f)

        # Get SST grid - use analysis for all time periods
        import time
        current_time = int(time.time())
        four_days_ago = current_time - (4 * 24 * 3600)
        ten_days_from_now = current_time + (10 * 24 * 3600)
        all_times = TimeRange.TimeRange(four_days_ago, ten_days_from_now)

        grid_info = self.getGridInfo(sst_db, "SST", "SFC", all_times)
        overlap_trs = [info.gridTime() for info in grid_info if info.gridTime().overlaps(GridTimeRange)]

        if overlap_trs:
            sst_f = self.getGrids(sst_db, "SST", "SFC", GridTimeRange)
        else:
            sst_f = self.getGrids(sst_db, "SST", "SFC", all_times)

        # Convert SST F to C
        sst_c = thresholds.f_to_c(sst_f)

        self.log(f"Max SST: {np.max(sst_f):.1f}F, Air Temp: {np.max(temp_f):.1f}F, Wind: {np.max(Wind[0]):.1f}kt")

        # Create mask for valid water areas (SST > 25F means valid data)
        try:
            run_edit_area = self.getEditArea("OPC_AOR")
            run_mask = self.encodeEditArea(run_edit_area)
        except Exception:
            run_mask = np.ones_like(sst_f, dtype=bool)

        valid_mask = run_mask & (sst_f > 25)

        # Get wind magnitude and convert to m/s
        mag_kt, _ = Wind
        mag_ms = thresholds.to_mps(mag_kt)

        # Calculate ice accretion using Overland algorithm
        # PPR = (V * Da) / (1 + 0.3 * Dw)
        # where Da = Tf - Ta, Dw = Tw - Tf
        da = self.TF_CELSIUS - temp_c  # Air temperature departure from freezing
        dw = sst_c - self.TF_CELSIUS  # Water temperature departure from freezing

        ppr = (mag_ms * da) / (1.0 + 0.3 * dw)

        # Apply result to masked areas
        IceAccretion[valid_mask] = ppr[valid_mask]

        self.log("Completed Populate_IceAccretion")
        return IceAccretion

    def log(self, msg: str):
        """Log message to console."""
        print(msg)


__all__ = ["Tool"]

