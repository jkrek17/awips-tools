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
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

ALIAS_OVERRIDE_FILENAME = "model_aliases.overrides.json"


@dataclass(frozen=True)
class WaveModelConfig:
    """Metadata describing the paired wave/ocean dataset for an alias."""

    dal_location: Optional[str] = None
    gfe_databases: Tuple[str, ...] = ()
    default_levels: Dict[str, str] = field(default_factory=dict)
    parameter_overrides: Dict[str, str] = field(default_factory=dict)

    def preferred_gfe(self) -> Optional[str]:
        return self.gfe_databases[0] if self.gfe_databases else None


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
    gfe_databases: Tuple[str, ...]
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

    def get_display_name(self) -> str:
        """Return display name, falling back to key if not set."""
        return self.display_name if self.display_name else self.key


def _normalize_key(key: str) -> str:
    if not key:
        raise ValueError("Model alias key cannot be empty.")
    return key.strip().upper()


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
            dal_location=wave_dict.get("dal_location"),
            gfe_databases=tuple(wave_dict.get("gfe_databases", ())),
            default_levels=dict(wave_dict.get("default_levels", {})),
            parameter_overrides=dict(wave_dict.get("parameter_overrides", {})),
        )

    return ModelAliasConfig(
        key=alias_key,
        gfe_databases=tuple(data.get("gfe_databases", ())),  # type: ignore[arg-type]
        display_name=str(data.get("display_name", "")),
        dal_location=data.get("dal_location"),
        default_levels=dict(data.get("default_levels", {})),
        parameter_overrides=dict(data.get("parameter_overrides", {})),
        tags=tuple(data.get("tags", ())),  # type: ignore[arg-type]
        synonyms=tuple(data.get("synonyms", ())),  # type: ignore[arg-type]
        wave=wave_cfg,
        max_runs=int(data.get("max_runs", 4)),
    )


def _build_alias_table() -> Dict[str, ModelAliasConfig]:
    raw_data: Dict[str, Dict] = {key: value.copy() for key, value in _DEFAULT_ALIAS_DATA.items()}
    override_path = Path(__file__).with_name(ALIAS_OVERRIDE_FILENAME)
    overrides = _load_override_payload(override_path)
    _apply_overrides(raw_data, overrides)

    table: Dict[str, ModelAliasConfig] = {}
    for key, payload in raw_data.items():
        table[key] = _build_config(key, payload)
    return table


def _build_lookup(table: Mapping[str, ModelAliasConfig]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for key, config in table.items():
        lookup[_normalize_key(key)] = key
        for synonym in config.synonyms:
            lookup[_normalize_key(synonym)] = key
    return lookup


def get_model_config(alias: str) -> ModelAliasConfig:
    """
    Return the :class:`ModelAliasConfig` for the provided alias or synonym.

    Raises:
        KeyError: if the alias does not exist.
    """

    canonical = _ALIAS_LOOKUP[_normalize_key(alias)]
    return _ALIAS_TABLE[canonical]


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
        "gfe_databases": ("D2D_GFS", "GFS"),
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
        "gfe_databases": ("D2D_ECMWF", "nECMWF0p25"),
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
        "gfe_databases": ("D2D_CMC", "CMCnh"),
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
        "gfe_databases": ("D2D_UKMET", "UKMEThires4"),
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
        "gfe_databases": ("D2D_GEFS", "GEFSMEAN"),
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
        "gfe_databases": ("D2D_RTOFS",),
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

__all__ = [
    "ModelAliasConfig",
    "WaveModelConfig",
    "get_model_config",
    "list_models",
    "list_models_for_gui",
    "resolve_wave_from_atmo",
    "has_alias",
    "ALIAS_OVERRIDE_FILENAME",
]

