"""Pytest bootstrap for the d2d_cps test suite.

Puts `D2D/derivedParameters/functions` on sys.path so `import CycloneCore`
resolves as a bare module, the same way AWIPS's embedded CAVE Python
interpreter loads it (no package, no relative imports) -- no matter what
directory pytest is invoked from.
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

import CycloneCore as cc  # noqa: E402  (must follow the sys.path insert above)


@pytest.fixture
def standard_orientation(monkeypatch):
    """Monkeypatch `ORIENTATION_MODE` to 0 (the plain numpy-default grid
    layout: axis 0 = y increasing northward, axis 1 = x) for the duration
    of a test.

    The module's real default is 1 (see CycloneCore.py), chosen for real
    AWIPS sites, not for describing "the standard layout" in a test. Tests
    that want to talk about the standard layout via the `mode=None`
    default (rather than passing `mode=0` explicitly everywhere) should
    depend on this fixture instead of assuming what the module default is.
    """
    monkeypatch.setattr(cc, "ORIENTATION_MODE", 0)
