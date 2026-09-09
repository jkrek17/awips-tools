"""Pytest bootstrap for the cps test suite.

Puts the repo root on sys.path so `import cps` resolves no matter what
directory pytest is invoked from (e.g. `python3 -m pytest tests/cps -q`
run from the repo root, or a CI job that cds elsewhere first).
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
