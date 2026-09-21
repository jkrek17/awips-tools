"""Pytest bootstrap for the d2d_cps test suite.

Puts `cyclone_phase_space/D2D/derivedParameters/functions` on sys.path so
`import cps_HartCPS` resolves as a bare module, the same way AWIPS's
embedded CAVE Python interpreter loads it (no package, no relative
imports) -- no matter what directory pytest is invoked from.
"""

from __future__ import annotations

import os
import sys

import pytest

_FUNCTIONS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "D2D", "derivedParameters", "functions")
)
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

# Also put the cyclone_phase_space project root on sys.path so tests can
# `import cps` (the storm-centered reference implementation, cps/hart.py)
# the same way tests/cps/conftest.py does, and its tests/cps directory so
# tests can reuse its `synthetic` vortex-generator module instead of
# duplicating it.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_CPS_TESTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cps"))
if _CPS_TESTS_DIR not in sys.path:
    sys.path.insert(0, _CPS_TESTS_DIR)
