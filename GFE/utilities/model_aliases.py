"""
Central registry for atmospheric and wave model aliases used by Smart Tools.

The legacy Smart Tools hard-code dataset names such as ``gfs0p25`` or
``nECMWF0p25`` inside each script. When a model is renamed (for example,
``gfs0p25`` -> ``gfs0p50``) every tool has to be touched manually.
This module keeps a single source of truth so tools can refer to models
by canonical keys like ``GFS`` or ``ECMWF``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

ALIAS_OVERRIDE_FILENAME = "model_aliases.overrides.json"


@dataclass(frozen=True)
class WaveModelConfig:
    """Metadata describing the paired wave/ocean dataset for an alias."""

    dal_location: Optional[str] = None
    # Database names used with SmartScript.findDatabase (may be GFE-local or D2D-backed)
    gfe_databases: Tuple[str, ...] = ()
    d2d_databases: Tuple[str, ...] = ()
    default_levels: Dict[str, str] = field(default_factory=dict)
    parameter_overrides: Dict[str, str] = field(default_factory=dict)

    def preferred_gfe(self) -> Optional[str]:
        return self.gfe_databases[0] if self.gfe_databases else None

    def preferred_d2d(self) -> Optional[str]:
        return self.d2d_databases[0] if self.d2d_databases else None


@dataclass(frozen=True)
class ModelAliasConfig:
    """
    Metadata describing how to access a single atmospheric model.

    Attributes:
        key: Canonical identifier (e.g., ``GFS``).
        display_name: Human-readable name for GUI display.
        gfe_databases: Tuple of database identifiers to try via ``findDatabase``.
        dal_location: DAL ``locationNames`` string, if the model is available via DAL.
        default_levels: Map of semantic names (``wind``, ``cape``, etc.) to AWIPS levels.
        parameter_overrides: Map of Smart Tool parameter names to DAL-native names.
        tags: Classification keywords (``atmo``, ``wave``, ``ensemble``, etc.).
        synonyms: Alternate identifiers that should resolve to this alias.
        wave: Optional :class:`WaveModelConfig` describing the paired wave dataset.
        max_runs: Maximum number of past runs typically available for blending.
    """

    key: str
    # Separate database identifiers by source to keep naming clear.
    # - gfe_databases: local GFE databases (e.g., "GFS")
    # - d2d_databases: D2D/MDL databases (e.g., "D2D_GFS", "nECMWF0p25")
    gfe_databases: Tuple[str, ...] = ()
    d2d_databases: Tuple[str, ...] = ()
    display_name: str = ""
    dal_location: Optional[str] = None
    default_levels: Dict[str, str] = field(default_factory=dict)
    parameter_overrides: Dict[str, str] = field(default_factory=dict)
    tags: Tuple[str, ...] = ()
    synonyms: Tuple[str, ...] = ()
    wave: Optional[WaveModelConfig] = None
    max_runs: int = 4

    def preferred_gfe(self) -> Optional[str]:
        return self.gfe_databases[0] if self.gfe_databases else None

    def preferred_d2d(self) -> Optional[str]:
        return self.d2d_databases[0] if self.d2d_databases else None

    def get_display_name(self) -> str:
        """Return display name, falling back to key if not set."""
        return self.display_name if self.display_name else self.key


def _normalize_key(key: str) -> str:
    if not key:
        raise ValueError("Model alias key cannot be empty.")
    return key.strip().upper()


def _coerce_str_tuple(value: object, *, field_name: str, alias_key: str) -> Tuple[str, ...]:
    """
    Coerce override/default payload values into a tuple of strings.

    Notes:
        JSON overrides often use lists. This helper also avoids the common
        pitfall of ``tuple("D2D_GFS")`` turning into a tuple of characters.
    """

    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            out.append(text)
        return tuple(out)
    raise TypeError(f"{alias_key}.{field_name} must be a string or sequence of strings; got {type(value)!r}")


def _coerce_optional_str(value: object, *, field_name: str, alias_key: str) -> Optional[str]:
    """Coerce optional string fields (also supports single-item sequences)."""

    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (list, tuple)) and value:
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def _coerce_str_dict(value: object, *, field_name: str, alias_key: str) -> Dict[str, str]:
    """Coerce mapping-like payloads into a dict[str, str]."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{alias_key}.{field_name} must be a mapping/dict; got {type(value)!r}")
    out: Dict[str, str] = {}
    for k, v in value.items():
        if k is None or v is None:
            continue
        key = str(k).strip()
        val = str(v).strip()
        if not key or not val:
            continue
        out[key] = val
    return out


def _load_override_payload(path: Path) -> Mapping[str, Mapping]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive logging
        raise RuntimeError(f"Failed to parse alias override file {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ValueError(f"Alias override file {path} must contain an object/dict.")
    return data  # type: ignore[return-value]


def _apply_overrides(raw_data: MutableMapping[str, Dict], overrides: Mapping[str, Mapping]) -> None:
    for override_key, payload in overrides.items():
        key = _normalize_key(override_key)
        base = raw_data.setdefault(key, {})
        for attr, value in payload.items():
            if attr == "wave" and isinstance(value, Mapping):
                wave_base = base.get("wave", {})
                if not isinstance(wave_base, dict):
                    wave_base = {}
                wave_base.update(value)
                base["wave"] = wave_base
            else:
                base[attr] = value


def _build_config(alias_key: str, data: Mapping[str, object]) -> ModelAliasConfig:
    wave_cfg: Optional[WaveModelConfig] = None
    if isinstance(data.get("wave"), Mapping):
        wave_dict: Mapping[str, object] = data["wave"]  # type: ignore[assignment]
        wave_cfg = WaveModelConfig(
            dal_location=_coerce_optional_str(wave_dict.get("dal_location"), field_name="wave.dal_location", alias_key=alias_key),
            gfe_databases=_coerce_str_tuple(wave_dict.get("gfe_databases"), field_name="wave.gfe_databases", alias_key=alias_key),
            d2d_databases=_coerce_str_tuple(wave_dict.get("d2d_databases"), field_name="wave.d2d_databases", alias_key=alias_key),
            default_levels=_coerce_str_dict(wave_dict.get("default_levels"), field_name="wave.default_levels", alias_key=alias_key),
            parameter_overrides=_coerce_str_dict(
                wave_dict.get("parameter_overrides"), field_name="wave.parameter_overrides", alias_key=alias_key
            ),
        )

    return ModelAliasConfig(
        key=alias_key,
        gfe_databases=_coerce_str_tuple(data.get("gfe_databases"), field_name="gfe_databases", alias_key=alias_key),
        d2d_databases=_coerce_str_tuple(data.get("d2d_databases"), field_name="d2d_databases", alias_key=alias_key),
        display_name=str(data.get("display_name", "")),
        dal_location=_coerce_optional_str(data.get("dal_location"), field_name="dal_location", alias_key=alias_key),
        default_levels=_coerce_str_dict(data.get("default_levels"), field_name="default_levels", alias_key=alias_key),
        parameter_overrides=_coerce_str_dict(data.get("parameter_overrides"), field_name="parameter_overrides", alias_key=alias_key),
        tags=_coerce_str_tuple(data.get("tags"), field_name="tags", alias_key=alias_key),
        synonyms=_coerce_str_tuple(data.get("synonyms"), field_name="synonyms", alias_key=alias_key),
        wave=wave_cfg,
        max_runs=int(data.get("max_runs", 4)),
    )


def _build_alias_table() -> Dict[str, ModelAliasConfig]:
    raw_data: Dict[str, Dict] = {_normalize_key(key): value.copy() for key, value in _DEFAULT_ALIAS_DATA.items()}
    override_path = Path(__file__).with_name(ALIAS_OVERRIDE_FILENAME)
    overrides = _load_override_payload(override_path)
    _apply_overrides(raw_data, overrides)

    table: Dict[str, ModelAliasConfig] = {}
    for key, payload in raw_data.items():
        canonical_key = _normalize_key(key)
        table[canonical_key] = _build_config(canonical_key, payload)
    return table


def _build_lookup(table: Mapping[str, ModelAliasConfig]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    conflicts: List[Tuple[str, str, str]] = []

    def register(value: Optional[str], canonical_key: str) -> None:
        if not value:
            return
        try:
            norm = _normalize_key(value)
        except ValueError:
            return
        existing = lookup.get(norm)
        if existing is not None and existing != canonical_key:
            conflicts.append((norm, existing, canonical_key))
            # Keep the first registration to avoid surprising overrides.
            return
        lookup[norm] = canonical_key

    def register_many(values: Sequence[str], canonical_key: str) -> None:
        for value in values or ():
            register(value, canonical_key)

    for key, config in table.items():
        canonical_key = _normalize_key(key)

        # Canonical name
        register(canonical_key, canonical_key)

        # Explicit synonyms (operators, legacy scripts)
        register_many(config.synonyms, canonical_key)

        # Also treat GFE/D2D database identifiers and DAL locationNames as aliases.
        register_many(config.gfe_databases, canonical_key)
        register_many(config.d2d_databases, canonical_key)
        register(config.dal_location, canonical_key)

        # Paired wave dataset identifiers (for passing "ECMWFwave" etc.)
        if config.wave is not None:
            register_many(config.wave.gfe_databases, canonical_key)
            register_many(config.wave.d2d_databases, canonical_key)
            register(config.wave.dal_location, canonical_key)

    # Stash conflict list for introspection (do not raise at import time).
    global _ALIAS_CONFLICTS
    _ALIAS_CONFLICTS = tuple(conflicts)
    return lookup


def get_model_config(alias: str) -> ModelAliasConfig:
    """
    Return the :class:`ModelAliasConfig` for the provided alias or synonym.

    Raises:
        KeyError: if the alias does not exist.
    """

    canonical = _ALIAS_LOOKUP[_normalize_key(alias)]
    return _ALIAS_TABLE[canonical]


def resolve_alias(alias: str) -> str:
    """Resolve any alias/synonym to the canonical key (e.g., ``D2D_GFS`` -> ``GFS``)."""

    return _ALIAS_LOOKUP[_normalize_key(alias)]


def get_dal_location(alias: str, *, dataset: str = "atmo") -> Optional[str]:
    """
    Return the DAL ``locationNames`` string for the alias.

    Args:
        alias: Canonical key, synonym, DB id (e.g. ``D2D_GFS``), or DAL location (e.g. ``gfs0p25``).
        dataset: ``"atmo"`` (default) or ``"wave"``.
    """

    cfg = get_model_config(alias)
    dataset_norm = dataset.lower()
    if dataset_norm not in {"atmo", "wave"}:
        raise ValueError("dataset must be 'atmo' or 'wave'")
    if dataset_norm == "wave":
        if cfg.wave is not None:
            return cfg.wave.dal_location
        if "wave" in cfg.tags:
            return cfg.dal_location
        return None
    return cfg.dal_location


def get_gfe_databases(alias: str, *, dataset: str = "atmo") -> Tuple[str, ...]:
    """
    Return the candidate database names for the alias.

    Intended for SmartScript ``findDatabase`` lookups (GFE/D2D).
    """

    cfg = get_model_config(alias)
    dataset_norm = dataset.lower()
    if dataset_norm not in {"atmo", "wave"}:
        raise ValueError("dataset must be 'atmo' or 'wave'")
    if dataset_norm == "wave":
        if cfg.wave is not None:
            return cfg.wave.gfe_databases
        if "wave" in cfg.tags:
            return cfg.gfe_databases
        return ()
    return cfg.gfe_databases


def get_d2d_databases(alias: str, *, dataset: str = "atmo") -> Tuple[str, ...]:
    """Return the candidate D2D database names for the alias."""

    cfg = get_model_config(alias)
    dataset_norm = dataset.lower()
    if dataset_norm not in {"atmo", "wave"}:
        raise ValueError("dataset must be 'atmo' or 'wave'")
    if dataset_norm == "wave":
        if cfg.wave is not None:
            return cfg.wave.d2d_databases
        if "wave" in cfg.tags:
            return cfg.d2d_databases
        return ()
    return cfg.d2d_databases


def get_database_candidates(
    alias: str,
    *,
    dataset: str = "atmo",
    preference: Tuple[str, ...] = ("gfe", "d2d"),
) -> Tuple[str, ...]:
    """
    Return ordered database-name candidates for SmartScript findDatabase/getGrids.

    Most tools want to "just get the best available database", so this helper
    merges gfe + d2d candidates in a predictable order.
    """

    dataset_norm = dataset.lower()
    if dataset_norm not in {"atmo", "wave"}:
        raise ValueError("dataset must be 'atmo' or 'wave'")

    buckets = {
        "gfe": get_gfe_databases(alias, dataset=dataset_norm),
        "d2d": get_d2d_databases(alias, dataset=dataset_norm),
    }
    seen = set()
    out: List[str] = []
    for key in preference:
        for name in buckets.get(key, ()):
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
    return tuple(out)


def list_alias_conflicts() -> List[Tuple[str, str, str]]:
    """
    Return collisions detected while building the alias lookup table.

    Each entry is: (alias_token, first_canonical, conflicting_canonical)
    """

    return list(_ALIAS_CONFLICTS)


def validate_aliases(*, raise_on_conflict: bool = False) -> bool:
    """
    Validate the alias registry.

    Returns:
        True if no conflicts were detected; False otherwise.
    """

    ok = not _ALIAS_CONFLICTS
    if not ok and raise_on_conflict:
        examples = "; ".join(f"{a} -> {first} (conflicts with {other})" for a, first, other in _ALIAS_CONFLICTS[:10])
        raise ValueError(f"Alias conflicts detected: {examples}")
    return ok


def list_models(kind: str = "all") -> List[str]:
    """
    List available alias keys filtered by ``kind``.

    Args:
        kind: ``"all"`` (default), ``"atmo"``, or ``"wave"``.
    """

    kind_norm = kind.lower()
    if kind_norm not in {"all", "atmo", "wave"}:
        raise ValueError(f"Unknown kind '{kind}'. Expected 'all', 'atmo', or 'wave'.")

    def is_wave(config: ModelAliasConfig) -> bool:
        return "wave" in config.tags or config.wave is not None

    def is_atmo(config: ModelAliasConfig) -> bool:
        return "atmo" in config.tags or config.dal_location is not None

    keys: Iterable[str] = _ALIAS_TABLE.keys()
    if kind_norm == "wave":
        keys = [k for k, cfg in _ALIAS_TABLE.items() if is_wave(cfg)]
    elif kind_norm == "atmo":
        keys = [k for k, cfg in _ALIAS_TABLE.items() if is_atmo(cfg)]

    return sorted(keys)


def resolve_wave_from_atmo(alias: str) -> Optional[WaveModelConfig]:
    """
    Return the paired wave configuration for an atmospheric alias, if defined.
    """

    config = get_model_config(alias)
    return config.wave


def has_alias(alias: str) -> bool:
    """Convenience helper used by GUIs to validate selections."""

    try:
        _normalize_key(alias)
    except ValueError:
        return False
    return _normalize_key(alias) in _ALIAS_LOOKUP


def list_models_for_gui(kind: str = "atmo") -> List[Tuple[str, str, int]]:
    """
    Return a list of (alias, display_name, max_runs) tuples for GUI population.
    
    Args:
        kind: Filter by tag - "atmo", "wave", "blend", "ensemble", or "all"
    
    Returns:
        List of (alias, display_name, max_runs) sorted by display name.
    """
    result = []
    kind_norm = kind.lower()
    
    for key, config in _ALIAS_TABLE.items():
        # Skip internal/GFE-only entries for most GUIs
        if "gfe" in config.tags and kind_norm != "all":
            continue
            
        # Filter by kind
        if kind_norm == "all":
            pass
        elif kind_norm not in config.tags:
            # Check for implicit atmo (has dal_location but no wave tag)
            if kind_norm == "atmo" and config.dal_location and "wave" not in config.tags:
                pass
            else:
                continue
        
        result.append((
            config.key,
            config.get_display_name(),
            config.max_runs
        ))
    
    # Sort by display name
    result.sort(key=lambda x: x[1])
    return result


# ---------------------------------------------------------------------------
# Default alias definitions
# ---------------------------------------------------------------------------

_DEFAULT_ALIAS_DATA: Dict[str, Dict] = {
    "GFS": {
        "display_name": "Global Forecast System",
        "gfe_databases": ("GFS",),
        "d2d_databases": ("D2D_GFS",),
        "dal_location": "gfs0p25",
        "default_levels": {
            "wind": "10FHAG",
            "cape": "0.0SFC",
            "qpf": "0.0SFC",
            "temp": "0.0SFC",
            "rh": "0.0SFC",
            "vis": "0.0SFC",
        },
        "parameter_overrides": {
            "QPF": "TP3hr",
            "CAPE": "SBCAPE",
            "Temperature": "T",
            "RH": "RH",
            "Visibility": "vis",
        },
        "tags": ("atmo", "global"),
        "synonyms": ("GFS0P25",),
        "max_runs": 4,
        "wave": {
            "gfe_databases": ("GFSWave",),
            "dal_location": "gfswaveNH0p16",
            "default_levels": {"wave": "0.0SFC"},
            "parameter_overrides": {"WaveHeight": "HTSGW", "WaveDirection": "DIRPW", "WavePeriod": "PERPW"},
        },
    },
    "ECMWF": {
        "display_name": "European Centre",
        "gfe_databases": (),
        "d2d_databases": ("D2D_ECMWF", "nECMWF0p25"),
        "dal_location": "ecmwf0p25",
        "default_levels": {
            "wind": "10FHAG",
            "cape": "0.0SFC",
            "qpf": "0.0SFC",
            "temp": "0.0SFC",
            "rh": "0.0SFC",
            "vis": "0.0SFC",
        },
        "parameter_overrides": {
            "QPF": "TP3hr",
            "CAPE": "SBCAPE",
            "Temperature": "T",
            "RH": "RH",
            "Visibility": "vis",
        },
        "tags": ("atmo", "global"),
        "synonyms": ("NECMWF0P25",),
        "max_runs": 2,
        "wave": {
            "gfe_databases": ("ECMWFwave", "ECENSwave"),
            "dal_location": "ecmwf0p25wave",
            "default_levels": {"wave": "0.0MSL"},
            "parameter_overrides": {"WaveHeight": "HTSGW", "WaveDirection": "DIRPW", "WavePeriod": "PERPW"},
        },
    },
    "CMC": {
        "display_name": "Canadian Global",
        "gfe_databases": (),
        "d2d_databases": ("D2D_CMC", "CMCnh"),
        "dal_location": "Canadian-NH",
        "default_levels": {
            "wind": "10FHAG",
            "cape": "0.0SFC",
            "qpf": "0.0SFC",
            "temp": "0.0SFC",
            "rh": "0.0SFC",
            "vis": "0.0SFC",
        },
        "parameter_overrides": {
            "QPF": "TP3hr",
            "CAPE": "SBCAPE",
            "Temperature": "T",
            "RH": "RH",
            "Visibility": "vis",
        },
        "tags": ("atmo", "global"),
        "synonyms": ("CMCnh", "CANADIAN-NH"),
        "max_runs": 2,
        "wave": {
            "gfe_databases": ("CMCwave",),
            "dal_location": "cmc0p25wave",
            "default_levels": {"wave": "0.0SFC"},
            "parameter_overrides": {"WaveHeight": "HTSGW", "WaveDirection": "DIRPW", "WavePeriod": "PERPW"},
        },
    },
    "UKMET": {
        "display_name": "UK Met Office",
        "gfe_databases": (),
        "d2d_databases": ("D2D_UKMET", "UKMEThires4"),
        "dal_location": None,
        "default_levels": {
            "wind": "10FHAG",
            "cape": "0.0SFC",
            "qpf": "0.0SFC",
            "temp": "0.0SFC",
            "rh": "0.0SFC",
            "vis": "0.0SFC",
        },
        "parameter_overrides": {
            "QPF": "TP3hr",
            "CAPE": "SBCAPE",
            "Temperature": "T",
            "RH": "RH",
            "Visibility": "vis",
        },
        "tags": ("atmo", "global"),
        "synonyms": ("UKMETHIRES4",),
        "max_runs": 2,
    },
    "NATIONALBLEND": {
        "display_name": "National Blend",
        "gfe_databases": ("NationalBlend",),
        "dal_location": None,
        "default_levels": {"wind": "10FHAG"},
        "tags": ("blend", "gfe"),
        "synonyms": ("NationalBlend", "NBM"),
        "max_runs": 4,
    },
    "NATIONALBLENDOC": {
        "display_name": "National Blend Ocean",
        "gfe_databases": ("NationalBlendOC",),
        "dal_location": None,
        "default_levels": {"wind": "10FHAG"},
        "tags": ("blend", "marine"),
        "synonyms": ("NationalBlendOC",),
        "max_runs": 4,
    },
    "GEFS": {
        "display_name": "GEFS Ensemble",
        "gfe_databases": ("GEFSMEAN",),
        "d2d_databases": ("D2D_GEFS",),
        "dal_location": "gefs0p50",
        "default_levels": {
            "wind": "10FHAG",
            "cape": "0.0SFC",
            "qpf": "0.0SFC",
            "temp": "0.0SFC",
            "rh": "0.0SFC",
            "vis": "0.0SFC",
        },
        "parameter_overrides": {
            "Temperature": "T",
            "RH": "RH",
            "Visibility": "vis",
            "QPF": "TP3hr",
            "CAPE": "SBCAPE",
        },
        "tags": ("atmo", "ensemble"),
        "synonyms": ("GEFSMEAN",),
        "max_runs": 4,
    },
    "ECENSMEAN": {
        "display_name": "EC Ensemble Mean",
        "gfe_databases": ("ECENSMEAN",),
        "dal_location": None,
        "default_levels": {
            "wind": "10FHAG",
            "cape": "0.0SFC",
            "qpf": "0.0SFC",
            "temp": "0.0SFC",
            "rh": "0.0SFC",
            "vis": "0.0SFC",
        },
        "tags": ("atmo", "ensemble"),
        "synonyms": ("ECENSMEAN",),
        "max_runs": 2,
    },
    "GEFSMEAN": {
        "display_name": "GEFS Mean",
        "gfe_databases": ("GEFSMEAN",),
        "dal_location": None,
        "default_levels": {"wind": "10FHAG"},
        "tags": ("atmo", "ensemble"),
        "max_runs": 4,
    },
    "RTOFS": {
        "display_name": "Real-Time Ocean Forecast",
        "gfe_databases": (),
        "d2d_databases": ("D2D_RTOFS",),
        "dal_location": "rtofs",
        "default_levels": {"sst": "SFC"},
        "parameter_overrides": {"Temperature": "SST"},
        "tags": ("wave", "ocean"),
        "max_runs": 2,
    },
    "GFSWAVE": {
        "display_name": "GFS Wave",
        "gfe_databases": ("GFSWave",),
        "dal_location": "gfswaveNH0p16",
        "default_levels": {"wave": "0.0SFC"},
        "parameter_overrides": {"WaveHeight": "HTSGW", "WaveDirection": "DIRPW", "WavePeriod": "PERPW"},
        "tags": ("wave", "global"),
        "synonyms": ("GFSWave", "GFSwaveNH", "GFSWAVENH"),
        "max_runs": 4,
    },
    "NECMWF0P25WAVE": {
        "display_name": "ECMWF Wave",
        # Include office variants so auto-derivation finds the available DB
        "gfe_databases": ("ECMWFwave", "ECENSwave", "nECMWF0p25wave"),
        "dal_location": "ecmwf0p25wave",
        "default_levels": {"wave": "0.0MSL"},
        "parameter_overrides": {"WaveHeight": "HTSGW", "WaveDirection": "DIRPW", "WavePeriod": "PERPW"},
        "tags": ("wave", "global"),
        "synonyms": ("nECMWF0p25wave", "ECMWFWAVE", "ECMWFwave", "ECENSwave"),
        "max_runs": 2,
    },
    "CMC0P25WAVE": {
        "display_name": "CMC Wave",
        "gfe_databases": ("cmc0p25wave",),
        "dal_location": "cmc0p25wave",
        "default_levels": {"wave": "0.0SFC"},
        "parameter_overrides": {"WaveHeight": "HTSGW", "WaveDirection": "DIRPW", "WavePeriod": "PERPW"},
        "tags": ("wave", "global"),
        "synonyms": ("cmc0p25wave",),
        "max_runs": 2,
    },
    "FCST": {
        "display_name": "Forecast",
        "gfe_databases": ("Fcst",),
        "dal_location": None,
        "default_levels": {},
        "parameter_overrides": {},
        "tags": ("gfe", "forecast"),
        "synonyms": ("FCST", "FORECAST"),
        "max_runs": 1,
    },
    "OFFICIAL": {
        "display_name": "Official",
        "gfe_databases": ("Official",),
        "dal_location": None,
        "default_levels": {},
        "parameter_overrides": {},
        "tags": ("gfe", "official"),
        "synonyms": ("OFFICIAL",),
        "max_runs": 1,
    },
    "NWPS-ONA": {
        "display_name": "NWPS Nearshore",
        "gfe_databases": ("NWPS-ONA",),
        "dal_location": None,
        "default_levels": {"wave": "0.0SFC"},
        "parameter_overrides": {"WaveHeight": "HTSGW"},
        "tags": ("wave", "nearshore"),
        "max_runs": 2,
    },
    "JMA": {
        "display_name": "Japan Met Agency",
        "gfe_databases": ("JMA",),
        "dal_location": None,
        "default_levels": {"wave": "0.0SFC"},
        "parameter_overrides": {"WaveHeight": "HTSGW"},
        "tags": ("wave", "global"),
        "max_runs": 2,
    },
    "FNMOCWAVE": {
        "display_name": "FNMOC Wave",
        "gfe_databases": ("FNMOCwave",),
        "dal_location": None,
        "default_levels": {"wave": "0.0SFC"},
        "parameter_overrides": {"WaveHeight": "HTSGW"},
        "tags": ("wave", "global"),
        "synonyms": ("FNMOCwave",),
        "max_runs": 2,
    },
    "BOAMUSWAVE-G": {
        "display_name": "BoM Aus Wave Global",
        "gfe_databases": ("BoMAUSWAVE-G",),
        "dal_location": None,
        "default_levels": {"wave": "0.0SFC"},
        "parameter_overrides": {"WaveHeight": "HTSGW"},
        "tags": ("wave", "regional"),
        "synonyms": ("BoMAUSWAVE-G",),
        "max_runs": 2,
    },
    "GEFSWAVEMEAN": {
        "display_name": "GEFS Wave Mean",
        "gfe_databases": ("GEFSwaveMean",),
        "dal_location": None,
        "default_levels": {"wave": "0.0SFC"},
        "parameter_overrides": {"WaveHeight": "HTSGW"},
        "tags": ("wave", "ensemble"),
        "synonyms": ("GEFSwaveMean",),
        "max_runs": 4,
    },
}

_ALIAS_TABLE = _build_alias_table()
_ALIAS_LOOKUP = _build_lookup(_ALIAS_TABLE)
_ALIAS_CONFLICTS: Tuple[Tuple[str, str, str], ...] = ()

__all__ = [
    "ModelAliasConfig",
    "WaveModelConfig",
    "get_model_config",
    "resolve_alias",
    "get_dal_location",
    "get_gfe_databases",
    "get_d2d_databases",
    "get_database_candidates",
    "list_alias_conflicts",
    "validate_aliases",
    "list_models",
    "list_models_for_gui",
    "resolve_wave_from_atmo",
    "has_alias",
    "ALIAS_OVERRIDE_FILENAME",
]

