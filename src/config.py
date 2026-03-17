"""
Central configuration loader for Cricket Metrics.

This module provides:
 - A single source of hard-coded defaults (_DEFAULTS)
 - Safe loading of user YAML overrides from a config file
 - A thread-safe cached `Config` singleton returned by `get_config()`
 - Utilities: `reload_config()`, `reset_to_defaults()`, and `cfg()`

Key improvements:
 - YAML parsing and file I/O are guarded; parsing errors fall back to defaults
   (and are logged).
 - Files are opened with UTF-8 encoding to avoid platform-dependent decoding issues.
 - The cached config is protected with a reentrant lock to avoid races when
   multiple threads call `get_config()` / `reload_config()` concurrently.
 - `Config` stores a deep copy of the merged configuration and exposes a
   deep-copy via the `data` property to avoid accidental mutation of module
   defaults.
"""

from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root: parent of the ``src/`` directory this file lives in.
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"

# ---------------------------------------------------------------------------
# Hardcoded defaults — used when the YAML file is missing or incomplete.
# ---------------------------------------------------------------------------
_DEFAULTS: Dict[str, Any] = {
    # Pipeline thresholds
    "pipeline": {
        "min_bat_innings": 10,
        "min_bowl_overs": 30,
        "min_phase_balls_batting": 4,
        "min_phase_balls_bowling": 6,
    },
    # Rating system
    "rating": {
        "shrinkage_k_bat": 12.0,
        "shrinkage_k_bowl": 10.0,
        "confidence_alpha": 0.03,
        "confidence_reference_n": 100.0,
    },
    # Batting — Acceleration weights
    "batting_acceleration_weights": {
        "overall_sr": 0.15,
        "sr_growth": 0.12,
        "death_sr": 0.10,
        "impact": 0.13,
        "runs_above_expected": 0.25,
        "leveraged_rva": 0.25,
    },
    # Batting — Power weights
    "batting_power_weights": {
        "boundary_pct": 0.12,
        "six_rate": 0.15,
        "boundary_rate_vs_par": 0.13,
        "peak_phase_sr": 0.10,
        "finishing_burst": 0.15,
        "power_impact": 0.10,
        "cabi": 0.25,
    },
    # Batting — Control weights
    "batting_control_weights": {
        "dot_pct_weighted": 0.12,
        "rotation": 0.08,
        "contribution": 0.10,
        "avg_proxy": 0.20,
        "dismissal_quality": 0.10,
        "scoring_consistency": 0.10,
        "survival_ratio": 0.30,
    },
    # Batting — Average quality gate
    "batting_avg_quality": {
        "reference": 18.0,
        "exponent_below": 2.5,
        "exponent_above": 0.5,
        "floor": 0.40,
        "ceil": 1.20,
        "gate_base": 0.55,
        "gate_ref": 25.0,
        "ctrl_gate_base": 0.70,
        "ctrl_gate_ref": 22.0,
    },
    # Batting — Volume scaling
    "batting_volume": {
        "base": 0.80,
        "ref": 50.0,
        "curve": 0.6,
    },
    # Bowling — Accuracy weights
    "bowling_accuracy_weights": {
        "economy_vs_par": 0.20,
        "dot_pct": 0.20,
        "extras_penalty": 0.15,
        "boundary_penalty": 0.15,
        "run_yield_variance": 0.30,
    },
    # Bowling — Control weights
    "bowling_control_weights": {
        "economy_vs_par": 0.15,
        "vs_others": 0.22,
        "entropy": 0.10,
        "phase_consistency": 0.10,
        "extras": 0.08,
        "extras_pct": 0.05,
        "bowling_rv": 0.30,
    },
    # Bowling — Threat weights
    "bowling_threat_weights": {
        "wickets": 0.10,
        "quality_wickets": 0.10,
        "sr": 0.10,
        "bowled_lbw": 0.10,
        "pressure": 0.15,
        "dots": 0.15,
        "wha": 0.30,
    },
    # Bowling — Volume scaling
    "bowling_volume": {
        "base": 0.80,
        "ref": 50.0,
        "curve": 0.6,
    },
    # Wicket quality (position-based)
    "wicket_quality": {
        "position_weights": {
            1: 1.5,
            2: 1.5,
            3: 1.4,
            4: 1.2,
            5: 1.1,
            6: 1.0,
            7: 0.8,
            8: 0.7,
            9: 0.5,
            10: 0.4,
            11: 0.3,
        },
        "default_weight": 0.8,
    },
    # Opposition quality
    "opposition_quality": {
        "scale": 0.15,
        "clip": 0.3,
    },
    # Team quality
    "team_quality": {
        "scale": 0.10,
        "clip": 0.25,
    },
    # ICC T20I ranking-based opposition weighting
    "icc_ranking": {
        "enabled": True,
        "floor": 0.70,
        "ceiling": 1.20,
        "curve": 1.0,
        "max_rating": 272,
        "default_rating": 50,
        "ratings": {
            "India": 272,
            "England": 260,
            "Australia": 258,
            "New Zealand": 250,
            "South Africa": 245,
            "Pakistan": 238,
            "West Indies": 235,
            "Sri Lanka": 227,
            "Bangladesh": 223,
            "Zimbabwe": 202,
            "Ireland": 200,
            "Netherlands": 181,
            "Scotland": 179,
            "Namibia": 178,
            "United States of America": 177,
            "United Arab Emirates": 176,
            "Nepal": 175,
            "Canada": 152,
            "Oman": 151,
            "Uganda": 142,
            "Papua New Guinea": 136,
            "Kuwait": 128,
            "Hong Kong": 128,
            "Malaysia": 125,
            "Italy": 122,
            "Qatar": 118,
            "Jersey": 117,
            "Bahrain": 116,
            "Spain": 113,
            "Bermuda": 113,
            "Saudi Arabia": 109,
            "Kenya": 106,
            "Tanzania": 100,
            "Germany": 87,
            "Nigeria": 79,
            "Guernsey": 77,
            "Singapore": 75,
            "Cayman Islands": 74,
            "Austria": 71,
            "Denmark": 70,
            "Norway": 70,
            "Japan": 69,
            "Portugal": 67,
            "Belgium": 57,
            "Argentina": 50,
            "Switzerland": 49,
            "Finland": 49,
            "Sweden": 48,
            "Malawi": 47,
            "Botswana": 47,
            "Isle of Man": 46,
            "France": 46,
            "Romania": 45,
            "Philippines": 45,
            "Bahamas": 42,
            "Czech Republic": 41,
            "Thailand": 40,
            "Cook Islands": 39,
            "Cambodia": 39,
            "Rwanda": 39,
            "Indonesia": 39,
            "Fiji": 35,
            "Vanuatu": 35,
            "Cyprus": 33,
            "Ghana": 30,
            "Hungary": 29,
            "Samoa": 29,
            "Zambia": 29,
            "Estonia": 28,
            "Malta": 26,
            "Mozambique": 26,
            "Eswatini": 26,
            "Israel": 25,
            "Panama": 21,
            "Bhutan": 21,
            "Belize": 21,
            "Gibraltar": 19,
            "Luxembourg": 18,
            "Sierra Leone": 18,
            "Costa Rica": 17,
            "Mexico": 16,
            "Suriname": 15,
            "Serbia": 11,
            "Maldives": 10,
            "Cameroon": 8,
            "Brazil": 8,
            "Bulgaria": 7,
            "South Korea": 6,
            "Saint Helena": 6,
            "China": 5,
            "Lesotho": 2,
            "Turkey": 2,
            "Gambia": 1,
        },
    },
    # Recency / time-decay
    "recency": {
        "enabled": True,
        "half_life_days": 730,
        "min_weight": 0.05,
    },
    # Phase dot-ball penalty weights
    "batting_dot_penalty_phase_weights": {
        "powerplay": 0.7,
        "middle": 1.0,
        "death": 1.5,
    },
    # Player aliases (deduplication)
    "player_aliases": {},
    "player_name_overrides": {},
    # Duplicate detection
    "duplicate_detection": {
        "min_innings": 5,
        "export_csv": True,
    },
    # Presentation layer
    "presentation": {
        "grade_boundaries": {
            "S": 95,
            "A_plus": 85,
            "A": 75,
            "B_plus": 60,
            "C_plus": 30,
            "C": 15,
            "D": 0,
        },
        "archetypes_enabled": True,
    },
    # Clutch / Pressure Index
    "clutch": {
        "enabled": True,
        "min_pressure_innings": 5,
        "high_rrr_threshold": 9.0,
        "collapse_wickets": 3,
    },
    # Chase Master Index
    "chase_master": {
        "enabled": True,
        "min_innings_per_type": 5,
    },
    # Similarity engine
    "similarity": {
        "enabled": True,
        "top_k": 3,
        "min_innings": 15,
    },
    # Selfless vs Stat-padder Index
    "selfless": {
        "enabled": True,
        "fifty_approach_range": [40, 49],
        "century_approach_range": [90, 99],
        "min_zone_balls": 3,
    },
    # Venue & Pitch Difficulty Adjustment
    "venue": {
        "enabled": True,
        "min_matches": 5,
    },
    # Matchups
    "matchups": {
        "min_balls": 6,
        "min_balls_phase": 4,
        "top_k_bunnies": 5,
        "top_k_dominant": 5,
    },
    # Win Probability Added (WPA)
    "wpa": {
        "enabled": False,
        "score_ratio_buckets": 10,
        "rr_ratio_buckets": 8,
    },
    # Anchor Cost
    "anchor_cost": {"enabled": True},
    # Form Tracker
    "form_tracker": {
        "enabled": True,
        "window_matches_bat": 10,
        "window_matches_bowl": 10,
        "min_window": 5,
    },
    # cricWAR
    "war": {
        "enabled": True,
        "replacement_percentile": 0.20,
    },
    # Era adjustment
    "era_adjustment": {"enabled": False, "rolling_years": 3},
    # Bowl splits
    "bowl_splits": {"enabled": True, "min_spells_per_type": 5},
    # Condition dependence
    "condition_dependence": {
        "enabled": True,
        "min_bat_innings": 10,
        "min_bowl_spells": 10,
        "par_sr_col": "match_par_sr",
        "bat_performance_col": "acc_overall_sr",
        "bowl_performance_col": "acc_economy_vs_par",
    },
    # Matchup shrinkage
    "matchup_shrinkage": {"enabled": True, "shrinkage_balls": 30},
    # Expected Value framework defaults
    "expected_value": {
        "enabled": True,
        "xr_sigma": 1.5,
        "xr_min_obs": 20,
        "wp_score_buckets": 12,
        "wp_rr_buckets": 10,
        "wp_laplace_alpha": 2,
        "full_wp": False,
        "compute_leverage": False,
    },
    # Allrounder
    "allrounder": {"enabled": True, "balance_penalty_scale": 0.15},
}

# ---------------------------------------------------------------------------
# Deep merge helper
# ---------------------------------------------------------------------------


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge `override` into `base`. Values in `override` take
    precedence. Input dicts are not mutated.
    """
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


# ---------------------------------------------------------------------------
# Config wrapper
# ---------------------------------------------------------------------------

_DEFAULT_SENTINEL = object()


class Config:
    """
    Thin wrapper providing dot-notation access for nested config dicts.

    - Stores a deep copy of the provided data to avoid external mutation.
    - `get()` supports dot-separated keys and a `default` sentinal.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        # Store a deep copy to isolate from caller-owned structures
        self._data: Dict[str, Any] = copy.deepcopy(data)

    def get(self, dotted_key: str, *, default: Any = _DEFAULT_SENTINEL) -> Any:
        """
        Retrieve a value using dot-separated keys.

        If `default` is provided (anything other than the sentinel), it is
        returned when a key path does not exist. Otherwise a KeyError is raised.
        """
        parts = dotted_key.split(".")
        node: Any = self._data
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif default is not _DEFAULT_SENTINEL:
                return default
            else:
                raise KeyError(
                    f"Config key {dotted_key!r} not found (failed at {part!r})"
                )
        return node

    def __getitem__(self, key: str) -> Any:
        # Top-level access only (consistent with previous behavior)
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    @property
    def data(self) -> Dict[str, Any]:
        """
        Return a deep copy of the full config dict to prevent accidental mutation.
        """
        return copy.deepcopy(self._data)

    def __repr__(self) -> str:
        return f"Config({list(self._data.keys())})"


# ---------------------------------------------------------------------------
# Loader + cache (thread-safe)
# ---------------------------------------------------------------------------
_cached_config: Optional[Config] = None
_cached_path: Optional[str] = None
_cache_lock = threading.RLock()


def get_config(path: Union[str, Path, None] = None) -> Config:
    """
    Load (and cache) the configuration.

    - `path` may be a string or Path. If None, defaults to project `config.yaml`.
    - If the file is missing or invalid YAML, we fallback to the hard-coded defaults.
    - Returns a `Config` instance with a deep copy of merged data.
    """
    global _cached_config, _cached_path

    # Treat explicit None as "use default path"; allow empty-string paths to be
    # resolved by the caller if they intentionally pass one.
    resolved: str
    if path is not None:
        resolved = str(Path(path).resolve())
    else:
        resolved = str(_DEFAULT_CONFIG_PATH)

    # Fast-path: return cached if available for same resolved path.
    with _cache_lock:
        if _cached_config is not None and _cached_path == resolved:
            return _cached_config

    user_overrides: Dict[str, Any] = {}

    try:
        cfg_path = Path(resolved)
        if cfg_path.is_file():
            try:
                # Read with explicit encoding and robust YAML parsing
                with cfg_path.open("r", encoding="utf-8") as fh:
                    loaded = yaml.safe_load(fh)
                if isinstance(loaded, dict):
                    user_overrides = loaded
                elif loaded is None:
                    # Empty YAML -> treat as no overrides
                    user_overrides = {}
                else:
                    logger.warning(
                        "Config file %s did not contain a top-level mapping; ignoring contents.",
                        resolved,
                    )
            except yaml.YAMLError as ye:
                logger.error("Failed to parse YAML config %s: %s", resolved, ye)
                user_overrides = {}
            except OSError as oe:
                logger.error("Failed to read config file %s: %s", resolved, oe)
                user_overrides = {}
    except Exception as exc:
        # Unusual failure when resolving the path; log and continue with defaults.
        logger.error("Unexpected error resolving config path %r: %s", path, exc)
        user_overrides = {}

    # Merge into defaults
    merged = _deep_merge(_DEFAULTS, user_overrides)

    # Cache under lock
    with _cache_lock:
        _cached_config = Config(merged)
        _cached_path = resolved
        return _cached_config


def reload_config(path: Union[str, Path, None] = None) -> Config:
    """
    Force-reload the configuration from `path` (or default file when None).

    This clears the cached singleton and returns a fresh `Config`.
    """
    global _cached_config, _cached_path
    with _cache_lock:
        _cached_config = None
        _cached_path = None
    return get_config(path)


def reset_to_defaults() -> Config:
    """
    Return a `Config` constructed only from the hardcoded defaults (no YAML).
    This also sets the module-level cache to that defaults-only Config.
    """
    global _cached_config, _cached_path
    with _cache_lock:
        _cached_config = Config(copy.deepcopy(_DEFAULTS))
        _cached_path = "__defaults__"
        return _cached_config


def cfg(dotted_key: str, *, default: Any = _DEFAULT_SENTINEL) -> Any:
    """
    Convenience: read a single dotted-key from the singleton config.

    Examples:
        cfg("recency.half_life_days")
        cfg("nonexistent.key", default=42)
    """
    config = get_config()
    return config.get(dotted_key, default=default)
