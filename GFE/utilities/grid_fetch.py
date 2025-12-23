"""
Helper functions for retrieving grids from GFE/D2D databases with
standardized fallback behavior.

The legacy Smart Tools repeatedly duplicate logic to call
``findDatabase`` for several model IDs and fall back to older cycles.
This module centralizes that logic so the new modular tools can rely on
a single implementation.
"""

from __future__ import annotations

from typing import Generator, Iterable, List, Optional, Sequence

import model_aliases


def _normalize_alias(alias: str) -> str:
    return alias.strip().upper()


def _normalize_level(level: str) -> str:
    """
    Normalize common AWIPS level strings.

    Many aliases specify ``0.0SFC`` which should be treated the same as ``SFC``.
    """

    if not level:
        return level
    level_up = level.upper()
    if level_up in {"0.0SFC", "SFC"}:
        return "SFC"
    return level


def _unique(seq: Iterable[str]) -> List[str]:
    """Return order-preserving unique values from ``seq``."""

    seen = set()
    out: List[str] = []
    for val in seq:
        if not val:
            continue
        if val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _iter_database_ids(smart_script, alias: str, run_depth: int) -> Generator[str, None, None]:
    """
    Yield model identifiers for the requested alias by searching the
    configured database names and walking back ``run_depth`` cycles.
    """

    alias_norm = _normalize_alias(alias)
    seen = set()

    if alias_norm in {"FCST", "FORECAST"}:
        try:
            mutable_id = smart_script.mutableID()
            if mutable_id:
                model_id = mutable_id.modelIdentifier()
                if model_id and isinstance(model_id, str) and model_id not in seen:
                    seen.add(model_id)
                    yield model_id
        except Exception:
            pass
        return

    if alias_norm == "OFFICIAL":
        try:
            db = smart_script.findDatabase("Official")
            if db:
                model_id = db.modelIdentifier()
                if model_id and isinstance(model_id, str) and model_id not in seen:
                    seen.add(model_id)
                    yield model_id
        except Exception:
            pass
        return

    try:
        candidates: Iterable[str] = model_aliases.get_gfe_databases(alias_norm) or ()
    except Exception:
        # Preserve legacy behavior: if alias resolution fails, just yield nothing.
        candidates = ()

    for base in candidates:
        for offset in range(0, -run_depth, -1):
            try:
                db = smart_script.findDatabase(base, offset)
            except Exception:
                db = None
            if db is None:
                continue
            try:
                model_id = getattr(db, "modelIdentifier", lambda: None)()
                if model_id and isinstance(model_id, str) and model_id not in seen:
                    seen.add(model_id)
                    yield model_id
            except Exception:
                continue


def get_grid(
    smart_script,
    alias: str,
    element: str,
    level: str,
    time_range,
    *,
    run_depth: int = 3,
    mode: str = "First",
    **kwargs,
):
    """
    Retrieve a grid for the specified alias/element/level, falling back to
    older cycles when necessary.
    """

    for model_id in _iter_database_ids(smart_script, alias, run_depth):
        if not model_id:
            continue
        try:
            grid = smart_script.getGrids(model_id, element, level, time_range, mode=mode, **kwargs)
        except Exception:
            grid = None
        if grid is not None:
            return grid
    return None


def get_grid_with_fallback(
    smart_script,
    alias: str,
    element_candidates: Sequence[str],
    level_candidates: Sequence[str],
    time_range,
    *,
    run_depth: int = 3,
    mode: str = "First",
    **kwargs,
):
    """
    Try multiple element/level combinations in order and return the first grid found.

    Args:
        smart_script: SmartScript instance.
        alias: Model alias or database selector (Fcst/Official supported).
        element_candidates: Ordered element names to try (duplicates and falsey removed).
        level_candidates: Ordered levels to try; ``0.0SFC`` is normalized to ``SFC``.
        time_range: Grid time range.
        run_depth: Number of past runs to search (default 3).
        mode: SmartScript getGrids mode (default "First").

    Returns:
        The first grid found, or ``None`` if nothing available.
    """

    elems = _unique(element_candidates)
    levels = [_normalize_level(lvl) for lvl in _unique(level_candidates)]

    # Log attempts for ECMWF/CMC to diagnose missing fields
    should_log = alias.upper() in ["ECMWF", "CMC"]
    if should_log:
        try:
            db_names = model_aliases.get_gfe_databases(alias)
            smart_script.log(f"    {alias} databases: {db_names}")
        except Exception:
            pass

    for elem in elems:
        for level in levels:
            if not level:
                continue
            if should_log:
                smart_script.log(f"    Trying {alias} {elem} {level}")
            grid = get_grid(
                smart_script,
                alias,
                elem,
                level,
                time_range,
                run_depth=run_depth,
                mode=mode,
                **kwargs,
            )
            if grid is not None:
                if should_log:
                    smart_script.log(f"    ✓ Found {alias} {elem} {level}")
                return grid
    if should_log:
        smart_script.log(f"    ✗ No grid found for {alias} with elements {elems} levels {levels}")
    return None


def get_vector_grid(
    smart_script,
    alias: str,
    element: str,
    level: str,
    time_range,
    *,
    run_depth: int = 3,
    mode: str = "First",
    **kwargs,
):
    """
    Wrapper around :func:`get_grid` kept for readability when fetching
    vector elements (e.g., ``Wind``).
    """

    return get_grid(
        smart_script,
        alias,
        element,
        level,
        time_range,
        run_depth=run_depth,
        mode=mode,
        **kwargs,
    )


def get_forecast_grid(smart_script, element: str, level: str, time_range, **kwargs):
    """
    Convenience helper for the Fcst database.
    """

    return smart_script.getGrids("Fcst", element, level, time_range, **kwargs)


def get_official_grid(smart_script, element: str, level: str, time_range, **kwargs):
    """
    Convenience helper for the Official database.
    """

    return smart_script.getGrids("Official", element, level, time_range, **kwargs)


__all__ = [
    "get_grid",
    "get_grid_with_fallback",
    "get_vector_grid",
    "get_forecast_grid",
    "get_official_grid",
]

