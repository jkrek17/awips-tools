"""
Helper functions for retrieving grids from GFE/D2D databases with
standardized fallback behavior.

The legacy Smart Tools repeatedly duplicate logic to call
``findDatabase`` for several model IDs and fall back to older cycles.
This module centralizes that logic so the new modular tools can rely on
a single implementation.
"""

from __future__ import annotations

from typing import Dict, Generator, Iterable, List, Optional, Sequence, Tuple

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


def _iter_database_ids(
    smart_script,
    alias: str,
    run_depth: int,
    *,
    element: Optional[str] = None,
) -> Generator[str, None, None]:
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
        if element:
            candidates: Iterable[str] = model_aliases.get_database_candidates_for_element(alias_norm, element) or ()
        else:
            candidates = model_aliases.get_database_candidates(alias_norm) or ()
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

    for model_id in _iter_database_ids(smart_script, alias, run_depth, element=element):
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


def model_run_time(model_id: str) -> Optional[int]:
    """
    Cycle time of a database in unix seconds, parsed from its identifier.

    Identifiers end in ``_YYYYMMDD_HHMM`` (``XXX_GRID_D2D_GFS_20261013_1200``);
    a singleton database such as ``Fcst`` has no time and returns ``None``.
    """

    import calendar
    import time as _time

    parts = (model_id or "").split("_")
    if len(parts) < 2:
        return None
    try:
        stamp = _time.strptime(parts[-2] + parts[-1], "%Y%m%d%H%M")
    except ValueError:
        return None
    return calendar.timegm(stamp)


def list_model_runs(
    smart_script,
    alias: str,
    *,
    dataset: str = "atmo",
    run_depth: int = 3,
) -> List[Tuple[int, Dict[str, str]]]:
    """
    Every run of ``alias`` the server has, newest cycle first.

    Each entry is ``(cycle_unix, {database_name: model_id})``: one cycle may
    live in several databases (a GFE smartInit copy and the D2D original),
    and they are grouped so a caller can keep to one model cycle while
    pulling elements from whichever database carries them.  A database that
    exists but holds no grids yet is still listed - whether a run is usable
    is for the caller to decide from its inventory, not from its existence.
    """

    try:
        candidates = model_aliases.get_database_candidates(alias, dataset=dataset)
    except Exception:
        candidates = ()

    runs: Dict[int, Dict[str, str]] = {}
    for base in candidates:
        for offset in range(0, -run_depth, -1):
            try:
                db = smart_script.findDatabase(base, offset)
            except Exception:
                db = None
            if db is None:
                continue
            try:
                model_id = db.modelIdentifier()
            except Exception:
                continue
            cycle = model_run_time(model_id)
            if cycle is None:
                continue
            runs.setdefault(cycle, {}).setdefault(base, model_id)

    return sorted(runs.items(), key=lambda item: item[0], reverse=True)


def grid_times(smart_script, model_id: str, element: str, level: str, time_range) -> List[Tuple[int, int, object]]:
    """
    Inventory of one element in one database over ``time_range``.

    Returns ``(start_unix, end_unix, grid_time_range)`` per grid, sorted by
    start; an element the database does not carry gives an empty list.
    """

    try:
        infos = smart_script.getGridInfo(model_id, element, level, time_range)
    except Exception:
        return []

    out = []
    for info in infos or []:
        try:
            tr = info.gridTime()
            out.append((tr.startTime().unixTime(), tr.endTime().unixTime(), tr))
        except Exception:
            continue
    out.sort(key=lambda item: item[0])
    return out


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
    "model_run_time",
    "list_model_runs",
    "grid_times",
]

