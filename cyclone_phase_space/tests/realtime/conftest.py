"""Pytest bootstrap for the realtime test suite.

Puts `cyclone_phase_space/realtime` on sys.path so `import gfs_cps` and
`import track_cps` resolve as bare modules the way track_cps.py itself
imports gfs_cps (`import gfs_cps as g`) when it is run standalone, and
puts `cyclone_phase_space/D2D/derivedParameters/functions` on sys.path
too, the same way `cyclone_phase_space/tests/d2d_cps/conftest.py` does
for the module -- no matter what directory pytest is invoked from.
"""

from __future__ import annotations

import os
import sys

_FUNCTIONS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "D2D", "derivedParameters", "functions")
)
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

_REALTIME_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "realtime"))
if _REALTIME_DIR not in sys.path:
    sys.path.insert(0, _REALTIME_DIR)
