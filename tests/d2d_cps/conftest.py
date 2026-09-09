"""Pytest bootstrap for the d2d_cps test suite.

Puts `D2D/derivedParameters/functions` on sys.path so `import CycloneCore`
resolves as a bare module, the same way AWIPS's embedded CAVE Python
interpreter loads it (no package, no relative imports) -- no matter what
directory pytest is invoked from.
"""

from __future__ import annotations

import os
import sys

_FUNCTIONS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "D2D", "derivedParameters", "functions")
)
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)
