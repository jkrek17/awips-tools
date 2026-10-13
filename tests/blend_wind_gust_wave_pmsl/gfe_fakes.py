"""The slice of GFE that Blend_WindGustWavePmsl touches, faked for tests.

``install()`` registers fake ``AbsTime``, ``TimeRange`` and ``SmartScript``
modules (and a stub ``tkinter`` when the real one is missing), puts the
repository's GFE utilities and procedures on the path, and returns the fake
SmartScript class.  Its database is a plain dict the test fills in:

    FakeSmartScript.store[(model_id, element, level)] = {
        "units": "m/s",
        "grids": [(TimeRange, grid_or_callable), ...],
    }
    FakeSmartScript.dbs[database_name] = [model_id_newest, model_id_older, ...]

A grid may be a callable, so a test can fetch it only when the procedure
asks (the real-data run does).  ``getGridInfo`` answers from what is there,
``findDatabase(name, -n)`` walks back the list, and ``createGrid`` records
every write in ``self.created`` so a test can assert exactly what was
written - including that nothing was.
"""
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "..")


class AbsTime:
    def __init__(self, t):
        self.t = int(t)

    def unixTime(self):
        return self.t


class TimeRange:
    def __init__(self, a, b=None):
        self.a, self.b = a, b

    def startTime(self):
        return self.a

    def endTime(self):
        return self.b

    def overlaps(self, other):
        return self.a.t < other.b.t and self.b.t > other.a.t

    def __repr__(self):
        return "TimeRange(%d, %d)" % (self.a.t, self.b.t)


def time_range(start, seconds=3600):
    """A TimeRange starting at unix ``start``, one hour long by default."""
    return TimeRange(AbsTime(start), AbsTime(start + seconds))


class _Info:
    def __init__(self, tr):
        self.tr = tr

    def gridTime(self):
        return self.tr


class _Parm:
    def __init__(self, units):
        self.units = units

    def getGridInfo(self):
        return self

    def getUnitString(self):
        return self.units


class _DB:
    def __init__(self, model_id):
        self.model_id = model_id

    def modelIdentifier(self):
        return self.model_id


class FakeSmartScript:
    store = {}
    dbs = {}
    shape = (20, 30)
    reads = 0

    def __init__(self, dbss=None):
        self.created = []
        self.msgs = []

    def findDatabase(self, name, version=0):
        ids = self.dbs.get(name, [])
        return _DB(ids[-version]) if -version < len(ids) else None

    def getGridInfo(self, model, elem, level, tr):
        entry = self.store.get((model, elem, level))
        if entry is None:
            raise RuntimeError("no parm %s %s %s" % (model, elem, level))
        return [_Info(g[0]) for g in entry["grids"] if g[0].overlaps(tr)]

    def getGrids(self, model, elem, level, tr, mode="First", noDataError=1, **kwargs):
        if model == "Fcst":
            for c in reversed(self.created):
                if c[1] == elem and c[4].overlaps(tr):
                    return c[3]
        entry = self.store.get((model, elem, level))
        if entry is None:
            return None
        for g_tr, grid in entry["grids"]:
            if g_tr.overlaps(tr):
                FakeSmartScript.reads += 1
                return grid() if callable(grid) else grid
        return None

    def getParm(self, model, elem, level):
        entry = self.store.get((model, elem, level))
        if entry is None:
            raise RuntimeError("no parm %s %s %s" % (model, elem, level))
        return _Parm(entry["units"])

    def createGrid(self, model, elem, kind, grid, tr):
        self.created.append((model, elem, kind, grid, tr))

    def statusBarMsg(self, message, status):
        self.msgs.append((status, message))

    def encodeEditArea(self, area):
        return area

    def empty(self):
        return np.zeros(self.shape, np.float32)

    def MagDirToUV(self, mag, direction):
        rad = np.radians(direction)
        return -mag * np.sin(rad), -mag * np.cos(rad)

    def UVToMagDir(self, u, v):
        return np.hypot(u, v), np.mod(np.degrees(np.arctan2(-u, -v)), 360)


def install():
    """Register the fakes and return FakeSmartScript."""
    for sub in ("GFE/utilities", "GFE/procedures"):
        path = os.path.join(REPO, sub)
        if path not in sys.path:
            sys.path.insert(0, path)

    for name, attrs in (("AbsTime", {"AbsTime": AbsTime}),
                        ("TimeRange", {"TimeRange": TimeRange}),
                        ("SmartScript", {"SmartScript": FakeSmartScript})):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        sys.modules[name] = module

    try:
        import tkinter  # noqa: F401
        from tkinter import messagebox  # noqa: F401
    except ImportError:
        tk = types.ModuleType("tkinter")
        box = types.ModuleType("tkinter.messagebox")
        box.showerror = lambda *a, **k: None
        tk.messagebox = box
        sys.modules["tkinter"] = tk
        sys.modules["tkinter.messagebox"] = box
    return FakeSmartScript
