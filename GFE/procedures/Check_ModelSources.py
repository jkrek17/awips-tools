"""
Check_ModelSources - list which model databases this GFE can see.  Read only.

For the deterministic blend in Blend_WindGustWavePmsl, and before any
ensemble-member blend, it answers three questions on the real system:

  * Which databases exist: the ones model_aliases knows, plus guesses for
    AIFS, AIFS ENS, the ECMWF ENS and GEFS members, CMC and UKMET.  When
    the server's full database list can be read, every database whose name
    looks like a model is listed too, so a name nobody guessed still shows up.
  * How many past runs of each the server keeps (the deterministic blend
    needs each model's runs 12 h and 24 h before its newest).
  * Whether each has a 10 m wind, where, and how far out the newest run goes.

Nothing is written.  The report goes to a window (to copy into the project
thread) and to the log.
"""

from __future__ import annotations

import re
import time
import tkinter as tk
from typing import Dict, List, Optional, Tuple

import SmartScript

import grid_fetch
import model_aliases

try:
    import AbsTime
    import TimeRange
except ImportError:  # outside GFE
    AbsTime = None
    TimeRange = None

MenuItems = ["Populate"]
VariableList = []

# Runs looked for per database (findDatabase offsets 0, -1, ...).
RUN_DEPTH = 8

# Names tried besides those in model_aliases.  Guesses: none of these has
# been seen on a real D2D.
EXTRA_DATABASES = (
    "D2D_AIFS", "AIFS", "ECMWF-AIFS", "nAIFS0p25",
    "D2D_AIFSENS", "AIFSENS", "AIFS-ENS", "ECMWF-AIFSENS",
    "D2D_ECENS", "ECENS", "ECMWF-ENS", "ECENSMEAN", "nECENS0p25",
    "D2D_GEFS", "GEFS", "GEFSMEAN", "GEFSmembers",
    "D2D_CMC", "CMCnh", "D2D_UKMET", "UKMEThires4",
)

# Database names worth listing from the server's full list.
MODEL_NAME = re.compile(r"GFS|GEFS|EC|AIFS|ENS|CMC|UKMET|GDPS|GEPS|NAVGEM|ICON|JMA", re.I)

# (element, level) pairs that hold the 10 m wind.
WIND_PARMS = (("Wind", "SFC"), ("wind", "FHAG10"), ("wind", "10FHAG"))

LOOK_AHEAD_DAYS = 16


class Procedure(SmartScript.SmartScript):
    """List model databases, runs kept and 10 m wind.  Writes nothing."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self._dbss_ref = dbss

    def log(self, message: str):
        print(message)

    def execute(self, editArea=None, timeRange=None, varDict=None):
        self.statusBarMsg("Checking model databases...", "R")
        lines = self.report()
        text = "\n".join(lines)
        self.log(text)
        found = sum(1 for line in lines if line.startswith("  ") and "runs" in line)
        self.statusBarMsg("Model source check done: %d databases found (report in the log)" % found, "R")
        if not (varDict or {}).get("no_window"):
            self._show(text)

    # ------------------------------------------------------------------ report

    def report(self) -> List[str]:
        names = self._candidate_names()
        server = self._server_database_names()
        if server:
            names += [n for n in server if n not in names and MODEL_NAME.search(n)]

        now = int(time.time())
        window = TimeRange.TimeRange(AbsTime.AbsTime(now - 2 * 86400),
                                     AbsTime.AbsTime(now + LOOK_AHEAD_DAYS * 86400))

        lines = ["MODEL SOURCES  %s" % time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(now)),
                 "Server database list: %s" % ("read, %d names" % len(server) if server else "not readable here; "
                                               "only the names below were tried"),
                 ""]
        found, missing = [], []
        for name in names:
            runs = self._runs(name)
            if not runs:
                missing.append(name)
                continue
            found.append(name)
            newest_id, newest_db = runs[0][1], runs[0][2]
            wind = self._wind(newest_id, window)
            cycles = ", ".join(time.strftime("%HZ %d", time.gmtime(c)) for c, _, _ in runs)
            lines.append("%s" % name)
            lines.append("  %d runs kept: %s" % (len(runs), cycles))
            lines.append("  newest: %s" % newest_id)
            lines.append("  10 m wind: %s" % wind)
            parms = self._wind_parm_names(newest_db)
            if parms:
                lines.append("  wind-like parms: %s" % parms)
            lines.append("")

        lines.append("Found %d of %d names tried." % (len(found), len(names)))
        lines.append("Not found: " + (", ".join(missing) or "none"))
        lines.append("")
        lines.append("Deterministic blend needs GFS, ECMWF and AIFS with runs 12 h and 24 h before the newest.")
        for alias in ("GFS", "ECMWF", "AIFS"):
            lines.append("  %-6s %s" % (alias, self._lag_check(alias)))
        return lines

    def _candidate_names(self) -> List[str]:
        names: List[str] = []
        for alias in model_aliases.list_models("all"):
            for dataset in ("atmo",):
                try:
                    names += [n for n in model_aliases.get_database_candidates(alias, dataset=dataset)
                              if n not in names]
                except Exception:
                    continue
        names += [n for n in EXTRA_DATABASES if n not in names]
        return names

    def _server_database_names(self) -> List[str]:
        """Model names of every database the server offers, if GFE lets us read them."""

        try:
            dbs = self._dbss_ref.getParmManager().getAvailableDbs()
        except Exception:
            return []
        names: List[str] = []
        for db in dbs:
            try:
                name = str(db.getModelName())
            except Exception:
                continue
            if name and name not in names:
                names.append(name)
        return names

    def _runs(self, name: str) -> List[Tuple[int, str, object]]:
        """(cycle, model id, database id) of each run kept, newest first."""

        out: List[Tuple[int, str, object]] = []
        for offset in range(0, -RUN_DEPTH, -1):
            try:
                db = self.findDatabase(name, offset)
                model_id = str(db.modelIdentifier()) if db is not None else None
            except Exception:
                model_id = None
            if not model_id:
                break
            cycle = grid_fetch.model_run_time(model_id)
            if cycle is None or any(c == cycle for c, _, _ in out):
                break
            out.append((cycle, model_id, db))
        return out

    def _wind(self, model_id: str, window) -> str:
        for element, level in WIND_PARMS:
            inv = grid_fetch.grid_times(self, model_id, element, level, window)
            if inv:
                cycle = grid_fetch.model_run_time(model_id) or inv[0][0]
                return "%s %s, %d grids to +%d h" % (element, level, len(inv), (inv[-1][0] - cycle) // 3600)
        return "none of " + ", ".join("%s %s" % p for p in WIND_PARMS)

    def _wind_parm_names(self, dbid) -> Optional[str]:
        """Parm names with 'wind' in them (shows per-member parms if a database has them)."""

        try:
            parms = self._dbss_ref.getParmManager().getAvailableParms(dbid)
        except Exception:
            return None
        names = sorted({"%s %s" % (p.getParmName(), p.getParmLevel()) for p in parms
                        if "wind" in str(p.getParmName()).lower()})
        if not names:
            return None
        return ", ".join(names[:20]) + (" (+%d more)" % (len(names) - 20) if len(names) > 20 else "")

    def _lag_check(self, alias: str) -> str:
        cycles = set()
        for name in model_aliases.get_database_candidates(alias, dataset="atmo"):
            cycles.update(c for c, _, _ in self._runs(name))
        if not cycles:
            return "not found"
        newest = max(cycles)
        have = [lag for lag in (0, 12, 24) if newest - lag * 3600 in cycles]
        return "newest %s; has %s" % (time.strftime("%HZ %d", time.gmtime(newest)),
                                      ", ".join("now" if lag == 0 else "-%d h" % lag for lag in have)
                                      + ("" if have == [0, 12, 24] else "  (missing %s)" % ", ".join(
                                          "-%d h" % lag for lag in (12, 24) if lag not in have)))

    def _show(self, text: str):
        try:
            root = tk.Tk()
            root.title("Model sources")
            box = tk.Text(root, width=110, height=40, font=("Courier", 10))
            box.insert("1.0", text)
            box.pack(fill=tk.BOTH, expand=True)
            tk.Button(root, text="Close", command=root.destroy).pack(pady=4)
            root.mainloop()
        except Exception:
            pass


__all__ = ["Procedure"]
