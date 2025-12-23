"""
Thin wrappers around AWIPS DataAccessLayer (DAL).

The legacy Smart Tools repeatedly implement the same boilerplate:
create a DAL request, look up available times, fall back to previous
cycles, and map logical parameter names (``QPF``, ``CAPE``) to the
model-specific identifiers (``TP3hr``, ``SBCAPE``). This module
centralizes that behavior so every Smart Tool can share consistent
logging, caching, and error handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, NamedTuple, Optional, Sequence, Tuple

try:  # pragma: no cover - ufpy unavailable in local dev
    from ufpy.dataaccess import DataAccessLayer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - handled at runtime
    DataAccessLayer = None  # type: ignore

import model_aliases
from model_aliases import ModelAliasConfig, WaveModelConfig


ParameterInput = Sequence[str] | str


class _AvailableTimeKey(NamedTuple):
    location: str
    parameters: Tuple[str, ...]
    level: Optional[str]
    envelope_signature: Optional[str]


@dataclass(frozen=True)
class _DatasetView:
    location: Optional[str]
    defaults: dict
    overrides: dict
    kind: str


_AVAILABLE_TIMES_CACHE: dict[_AvailableTimeKey, Tuple] = {}


def _require_dal():
    if DataAccessLayer is None:
        raise ImportError(
            "ufpy.DataAccessLayer is not available. "
            "These utilities must run inside an AWIPS/GFE environment."
        )


def _coerce_parameters(parameters: ParameterInput) -> Tuple[str, ...]:
    if isinstance(parameters, str):
        params = (parameters,)
    else:
        params = tuple(parameters)
    if not params:
        raise ValueError("At least one parameter must be supplied.")
    return params


def _map_parameters(params: Tuple[str, ...], overrides: dict) -> Tuple[str, ...]:
    return tuple(overrides.get(param, param) for param in params)


def _pick_default_level(dataset: str, defaults: dict, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    preferred_keys = ("wave", "waves") if dataset == "wave" else ("wind", "atmo", "default")
    for key in preferred_keys:
        if key in defaults:
            return defaults[key]
    if defaults:
        return next(iter(defaults.values()))
    return None


def _dataset_view(config: ModelAliasConfig, dataset: str) -> _DatasetView:
    dataset_norm = dataset.lower()
    if dataset_norm == "wave":
        # Two supported shapes:
        # 1) Atmospheric alias with a paired wave config (e.g., GFS with config.wave set)
        # 2) Wave-only alias (e.g., GFSWAVE) where the wave dataset info lives directly on config
        wave: Optional[WaveModelConfig] = config.wave
        if wave is not None:
            return _DatasetView(
                location=wave.dal_location,
                defaults=wave.default_levels,
                overrides=wave.parameter_overrides,
                kind="wave",
            )
        if "wave" in getattr(config, "tags", ()):
            return _DatasetView(
                location=config.dal_location,
                defaults=config.default_levels,
                overrides=config.parameter_overrides,
                kind="wave",
            )
        raise ValueError(f"Alias '{config.key}' does not define a wave dataset.")
    return _DatasetView(
        location=config.dal_location,
        defaults=config.default_levels,
        overrides=config.parameter_overrides,
        kind="atmo",
    )


def _envelope_signature(envelope) -> Optional[str]:
    if envelope is None:
        return None
    if hasattr(envelope, "wkt"):
        return str(envelope.wkt)
    return repr(envelope)


def _extract_start_unix(obj) -> Optional[int]:
    if obj is None:
        return None
    candidate_attrs = ("startTime", "getStart", "getStartTime")
    for attr_name in candidate_attrs:
        attr = getattr(obj, attr_name, None)
        if callable(attr):
            start = attr()
            if start is None:
                continue
            unix = getattr(start, "unixTime", None)
            if callable(unix):
                return int(unix())
            if isinstance(start, (int, float)):
                return int(start)
    for period_attr in ("getValidPeriod", "validPeriod"):
        attr = getattr(obj, period_attr, None)
        if callable(attr):
            period = attr()
            value = _extract_start_unix(period)
            if value is not None:
                return value
    return None


def _time_range_start_unix(time_range) -> Optional[int]:
    if time_range is None:
        return None
    start_attr = getattr(time_range, "startTime", None)
    if callable(start_attr):
        start = start_attr()
        if start is not None:
            unix = getattr(start, "unixTime", None)
            if callable(unix):
                return int(unix())
    return None


def _time_range_end_unix(time_range) -> Optional[int]:
    if time_range is None:
        return None
    end_attr = getattr(time_range, "endTime", None)
    if callable(end_attr):
        end = end_attr()
        if end is not None:
            unix = getattr(end, "unixTime", None)
            if callable(unix):
                return int(unix())
    return None


def _filter_datatimes_in_range(times: Iterable, start_unix: Optional[int], end_unix: Optional[int]) -> List:
    if start_unix is None and end_unix is None:
        return list(times)
    selected: List = []
    for data_time in times:
        t0 = _extract_start_unix(data_time)
        if t0 is None:
            continue
        if start_unix is not None and t0 < start_unix:
            continue
        if end_unix is not None and t0 > end_unix:
            continue
        selected.append(data_time)
    return selected


def _filter_datatimes_by_tolerance(times: Iterable, target_unix: Optional[int], tolerance: int) -> List:
    if target_unix is None:
        return list(times)
    selected: List = []
    for data_time in times:
        start_unix = _extract_start_unix(data_time)
        if start_unix is None:
            continue
        if abs(start_unix - target_unix) <= tolerance:
            selected.append(data_time)
    return selected


def build_data_request(
    alias: str,
    parameters: ParameterInput,
    *,
    dataset: str = "atmo",
    level: Optional[str] = None,
    envelope=None,
):
    """
    Create a DAL data request for the given alias and parameter list.
    """

    _require_dal()
    config = model_aliases.get_model_config(alias)
    view = _dataset_view(config, dataset)
    if not view.location:
        raise ValueError(f"Alias '{config.key}' has no DAL location for dataset '{dataset}'.")

    raw_params = _coerce_parameters(parameters)
    resolved_params = _map_parameters(raw_params, view.overrides)
    level_to_use = _pick_default_level(view.kind, view.defaults, level)

    request = DataAccessLayer.newDataRequest()
    request.setDatatype("grid")
    request.setLocationNames(view.location)
    request.setParameters(*resolved_params)
    if level_to_use:
        request.setLevels(level_to_use)
    if envelope is not None:
        request.setEnvelope(envelope)

    return request, resolved_params, level_to_use, view.location


def get_available_times(
    alias: str,
    parameters: ParameterInput,
    *,
    dataset: str = "atmo",
    level: Optional[str] = None,
    envelope=None,
    refresh_cache: bool = False,
):
    """
    Return cached DAL available times for the request described by ``alias``.
    """

    request, resolved_params, level_to_use, location = build_data_request(
        alias, parameters, dataset=dataset, level=level, envelope=envelope
    )
    key = _AvailableTimeKey(location, resolved_params, level_to_use, _envelope_signature(envelope))
    if not refresh_cache and key in _AVAILABLE_TIMES_CACHE:
        return _AVAILABLE_TIMES_CACHE[key]

    _require_dal()
    times = DataAccessLayer.getAvailableTimes(request) or []
    _AVAILABLE_TIMES_CACHE[key] = tuple(times)
    return _AVAILABLE_TIMES_CACHE[key]


def clear_available_times_cache():
    """Invalidate the in-memory cache of DAL available times."""

    _AVAILABLE_TIMES_CACHE.clear()


def fetch_geometry(
    alias: str,
    parameters: ParameterInput,
    time_range=None,
    *,
    dataset: str = "atmo",
    level: Optional[str] = None,
    envelope=None,
    tolerance: int = 3 * 3600,
    max_samples: Optional[int] = None,
    refresh_cache: bool = False,
    target_unix: Optional[int] = None,
):
    """
    Retrieve geometry data for the requested alias and parameter list.

    Args:
        alias: Canonical or synonym model key (``GFS``, ``ECMWF``, etc.).
        parameters: Logical parameter names (overrides are applied automatically).
        time_range: AWIPS ``TimeRange`` describing the desired period (optional if ``target_unix`` supplied).
        dataset: ``"atmo"`` (default) or ``"wave"``.
        level: Optional explicit level string (otherwise defaults are used).
        envelope: Optional geometry to limit DAL retrieval (e.g., shapely box/point).
        tolerance: Allowed seconds between available time and ``time_range`` start.
        max_samples: If no matches occur within tolerance, limit fallback sample count.
        refresh_cache: Force the available-times cache to refresh before fetching.
        target_unix: Optional unix timestamp override for time matching.
    """

    if time_range is None and target_unix is None:
        raise ValueError("Either time_range or target_unix must be provided.")

    request, resolved_params, level_to_use, location = build_data_request(
        alias, parameters, dataset=dataset, level=level, envelope=envelope
    )
    key = _AvailableTimeKey(location, resolved_params, level_to_use, _envelope_signature(envelope))
    if refresh_cache and key in _AVAILABLE_TIMES_CACHE:
        del _AVAILABLE_TIMES_CACHE[key]

    available = get_available_times(
        alias,
        parameters,
        dataset=dataset,
        level=level_to_use,
        envelope=envelope,
        refresh_cache=refresh_cache,
    )

    target_start = target_unix if target_unix is not None else _time_range_start_unix(time_range)
    selected = _filter_datatimes_by_tolerance(available, target_start, tolerance)

    if not selected and available:
        if max_samples:
            selected = list(available)[-max_samples:]
        else:
            selected = list(available)

    if not selected:
        return []

    _require_dal()
    return DataAccessLayer.getGeometryData(request, selected)


def fetch_point_series(
    alias: str,
    parameters: ParameterInput,
    time_range,
    point_geometry,
    *,
    dataset: str = "atmo",
    level: Optional[str] = None,
    tolerance: int = 3 * 3600,
    max_samples: Optional[int] = None,
):
    """
    Convenience wrapper to sample a single point (or small geometry).
    """

    return fetch_geometry(
        alias,
        parameters,
        time_range,
        dataset=dataset,
        level=level,
        envelope=point_geometry,
        tolerance=tolerance,
        max_samples=max_samples,
    )


def fetch_geometry_for_timerange(
    alias: str,
    parameters: ParameterInput,
    time_range,
    *,
    dataset: str = "atmo",
    level: Optional[str] = None,
    envelope=None,
    refresh_cache: bool = False,
    max_samples: Optional[int] = 48,
):
    """
    Fetch geometry data for *all* available times that fall within ``time_range``.

    This is useful for time-series products (spot forecasts, meteograms, etc.)
    where callers want the entire period rather than a single time match.

    Args:
        max_samples: If no times fall inside ``time_range``, fall back to the last N samples.
    """

    if time_range is None:
        raise ValueError("time_range must be provided.")

    request, resolved_params, level_to_use, location = build_data_request(
        alias, parameters, dataset=dataset, level=level, envelope=envelope
    )
    key = _AvailableTimeKey(location, resolved_params, level_to_use, _envelope_signature(envelope))
    if refresh_cache and key in _AVAILABLE_TIMES_CACHE:
        del _AVAILABLE_TIMES_CACHE[key]

    available = get_available_times(
        alias,
        parameters,
        dataset=dataset,
        level=level_to_use,
        envelope=envelope,
        refresh_cache=refresh_cache,
    )

    start_unix = _time_range_start_unix(time_range)
    end_unix = _time_range_end_unix(time_range)
    selected = _filter_datatimes_in_range(available, start_unix, end_unix)

    if not selected and available:
        if max_samples:
            selected = list(available)[-max_samples:]
        else:
            selected = list(available)

    if not selected:
        return []

    _require_dal()
    return DataAccessLayer.getGeometryData(request, selected)


__all__ = [
    "build_data_request",
    "get_available_times",
    "clear_available_times_cache",
    "fetch_geometry",
    "fetch_geometry_for_timerange",
    "fetch_point_series",
]

