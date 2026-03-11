"""
Central configuration loader for Cricket Metrics.

Reads tuning constants from a YAML config file (default: ``config.yaml`` in
the project root).  If the file is missing or a section is absent, hardcoded
defaults are used — so the pipeline always works out of the box.

Usage
-----
    from src.config import get_config, cfg

    # Module-level singleton (loads once on first import):
    half_life = cfg("recency.half_life_days")          # → 545
    acc_w     = cfg("batting_acceleration_weights")     # → dict
    scale     = cfg("opposition_quality.scale")         # → 0.15

    # Or load a specific file:
    config = get_config("/path/to/custom.yaml")
    val = config.get("recency.half_life_days")

Design
------
- Dot-notation for nested keys: ``"recency.half_life_days"`` traverses
  ``config["recency"]["half_life_days"]``.
- Every constant has a default in ``_DEFAULTS`` so that missing YAML
  sections never crash the pipeline.
- ``get_config()`` caches the loaded dict so repeated calls are free.
- Thread-safe for read-only access (no mutation after load).
"""

import os
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Project root: parent of the ``src/`` directory this file lives in.
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"

# ---------------------------------------------------------------------------
# Hardcoded defaults — used when the YAML file is missing or incomplete.
# Kept in sync with config.yaml; this is the single source of truth for
# "what the pipeline does when the user hasn't configured anything".
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, Any] = {
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
    # Reworked per algorithm_update.md: xR-based Run Value Added (RVA) and
    # leveraged RVA are now primary signals (0.25 each), with SR-based
    # components as supporting evidence.
    "batting_acceleration_weights": {
        "overall_sr": 0.15,
        "sr_growth": 0.12,
        "death_sr": 0.10,
        "impact": 0.13,
        "runs_above_expected": 0.25,
        "leveraged_rva": 0.25,
    },
    # Batting — Power weights
    # Reworked per algorithm_update.md: Context-Adjusted Boundary Index (CABI)
    # is now the primary signal (0.25), isolating raw boundary ability
    # independent of ground size and conditions.
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
    # Reworked per algorithm_update.md: Expected Survival Rate (xSR) from
    # the hazard model is now the primary signal (0.30), properly handling
    # not-out innings and measuring true dismissal resistance.
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
    # Reworked per algorithm_update.md: run-yield variance (inverse) is now
    # the primary signal (0.30) — a highly accurate bowler demonstrates tight
    # clustering of run yields, consistently conceding singles or dots.
    "bowling_accuracy_weights": {
        "economy_vs_par": 0.20,
        "dot_pct": 0.20,
        "extras_penalty": 0.15,
        "boundary_penalty": 0.15,
        "run_yield_variance": 0.30,
    },
    # Bowling — Control weights
    # Reworked per algorithm_update.md: Adjusted Bowling Leveraged Run Value
    # from xR is now the primary signal (0.30) — measures how much a bowler
    # suppresses expected run value at each match state.
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
    # Reworked per algorithm_update.md: Wicket Hazard Added (WHA) is now
    # the primary signal (0.30) — isolates a bowler's ability to take wickets
    # above the baseline probability for their match state.
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
    # Team quality (derived from ICC rankings; scale/clip control innings weighting)
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
    # Death dots are most punishing (need to score fastest);
    # PP dots more acceptable (fielders in circle, harder to rotate).
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
    # ── Version 0.2 feature defaults ──────────────────────────────────────
    # Feature 1 & 2: Presentation layer (grades + archetypes)
    "presentation": {
        "grade_boundaries": {
            "S": 95,
            "A_plus": 85,
            "A": 75,
            "B_plus": 60,
            "B": 45,
            "C_plus": 30,
            "C": 15,
            "D": 0,
        },
        "archetypes_enabled": True,
    },
    # Feature 3: Clutch / Pressure Index
    "clutch": {
        "enabled": True,
        "min_pressure_innings": 5,
        "high_rrr_threshold": 9.0,
        "collapse_wickets": 3,
    },
    # Feature 6: Chase Master Index
    "chase_master": {
        "enabled": True,
        "min_innings_per_type": 5,
    },
    # Feature 7: Player Similarity Engine
    "similarity": {
        "enabled": True,
        "top_k": 3,
        "min_innings": 15,
    },
    # Feature 8: Selfless vs Stat-Padder Index
    "selfless": {
        "enabled": True,
        "fifty_approach_range": [40, 49],
        "century_approach_range": [90, 99],
        "min_zone_balls": 3,
    },
    # Feature 9: Venue & Pitch Difficulty Adjustment
    "venue": {
        "enabled": True,
        "min_matches": 5,
    },
    # Feature 4: Head-to-Head / Matchup Analysis
    "matchups": {
        "min_balls": 6,
        "min_balls_phase": 4,
        "top_k_bunnies": 5,
        "top_k_dominant": 5,
    },
    # Feature 10: Win Probability Added (WPA)
    "wpa": {
        "enabled": False,
        "score_ratio_buckets": 10,
        "rr_ratio_buckets": 8,
    },
    # Feature 11: Anchor Cost / Balls-to-Par
    "anchor_cost": {
        "enabled": True,
    },
    # Feature 13: Form Tracker (Time-Series)
    "form_tracker": {
        "enabled": True,
        "window_matches_bat": 10,
        "window_matches_bowl": 10,
        "min_window": 5,
    },
    # Feature 14: cricWAR (Wins Above Replacement)
    # Reworked per algorithm_update.md: replacement level is now the 20th
    # percentile (representing a fringe domestic / bench player), and WAR
    # uses a dynamic Runs Per Win converter computed from match data.
    "war": {
        "enabled": True,
        "replacement_percentile": 0.20,
    },
    # Feature 15: Era-Adjusted Ratings
    # Per algorithm_update.md: uses rolling 3-year window for Z-score
    # normalization and percentile mapping across eras.
    "era_adjustment": {
        "enabled": False,
        "rolling_years": 3,
    },
    # Feature 16: Bowl First / Bowl Second Index (bowling innings splits)
    # Per algorithm_update.md: differentiates a bowler's ability to restrict
    # an unknown total (bowl first) vs defending a set target (bowl second).
    "bowl_splits": {
        "enabled": True,
        "min_spells_per_type": 5,
    },
    # Feature 17: Condition-Dependence Metrics (flat-track bully detection)
    # Per algorithm_update.md: measures whether a player's performance
    # disproportionately spikes in highly favorable conditions via
    # interaction terms and Pearson correlation with match par SR.
    "condition_dependence": {
        "enabled": True,
        "min_bat_innings": 10,
        "min_bowl_spells": 10,
        "par_sr_col": "match_par_sr",
        "bat_performance_col": "acc_overall_sr",
        "bowl_performance_col": "acc_economy_vs_par",
    },
    # Feature 18: Bayesian Matchup Shrinkage (archetype-based priors)
    # Per algorithm_update.md §Matchup Modeling: shrinks sparse head-to-head
    # records toward the broader archetype baseline using Empirical Bayes.
    "matchup_shrinkage": {
        "enabled": True,
        "shrinkage_balls": 30,
    },
    # ── Expected Value (xR) framework defaults ─────────────────────────
    # Core xR model parameters
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
    # All-Rounder balance penalty (algorithm_update.md vector magnitude)
    "allrounder": {
        "enabled": True,
        "balance_penalty_scale": 0.15,
    },
}


# ---------------------------------------------------------------------------
# Deep merge helper
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge *override* into *base*.  Values in *override* take
    precedence.  Neither input dict is mutated.
    """
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------


class Config:
    """
    Thin wrapper around a nested dict with dot-notation access.

    Examples
    --------
    >>> c = Config({"a": {"b": 3}})
    >>> c.get("a.b")
    3
    >>> c.get("a.b.c", default=99)
    99
    >>> c["a"]
    {'b': 3}
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    # -- dot-notation accessor ------------------------------------------------

    def get(self, dotted_key: str, *, default: Any = KeyError) -> Any:
        """
        Retrieve a value using dot-separated keys.

        Parameters
        ----------
        dotted_key : str
            E.g. ``"recency.half_life_days"`` or ``"batting_acceleration_weights"``.
        default
            Value to return if the key is not found.  If not provided, raises
            ``KeyError``.

        Returns
        -------
        The config value (int, float, str, dict, list, bool, …).
        """
        parts = dotted_key.split(".")
        node: Any = self._data
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif default is not KeyError:
                return default
            else:
                raise KeyError(
                    f"Config key {dotted_key!r} not found (failed at {part!r})"
                )
        return node

    def __getitem__(self, key: str) -> Any:
        """Dict-style access on the top-level keys."""
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    @property
    def data(self) -> dict[str, Any]:
        """Return a shallow copy of the full config dict."""
        return self._data.copy()

    def __repr__(self) -> str:
        return f"Config({list(self._data.keys())})"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_cached_config: Config | None = None
_cached_path: str | None = None


def get_config(path: str | os.PathLike | None = None) -> Config:
    """
    Load (and cache) the pipeline configuration.

    Parameters
    ----------
    path : str or Path, optional
        Path to a YAML file.  Defaults to ``config.yaml`` in the project
        root.  If the file doesn't exist, pure defaults are used.

    Returns
    -------
    Config
        A ``Config`` instance with all defaults filled in.
    """
    global _cached_config, _cached_path

    resolved = str(Path(path).resolve()) if path else str(_DEFAULT_CONFIG_PATH)

    # Return cached if same path
    if _cached_config is not None and _cached_path == resolved:
        return _cached_config

    user_overrides: dict[str, Any] = {}
    if Path(resolved).is_file():
        with open(resolved, "r") as f:
            loaded = yaml.safe_load(f)
        if isinstance(loaded, dict):
            user_overrides = loaded

    merged = _deep_merge(_DEFAULTS, user_overrides)
    _cached_config = Config(merged)
    _cached_path = resolved
    return _cached_config


def reload_config(path: str | os.PathLike | None = None) -> Config:
    """Force-reload the config (clears cache)."""
    global _cached_config, _cached_path
    _cached_config = None
    _cached_path = None
    return get_config(path)


def reset_to_defaults() -> Config:
    """Return a Config with only the hardcoded defaults (no YAML)."""
    global _cached_config, _cached_path
    _cached_config = Config(_DEFAULTS.copy())
    _cached_path = "__defaults__"
    return _cached_config


# ---------------------------------------------------------------------------
# Module-level convenience: ``cfg(dotted_key)`` reads from the singleton.
# ---------------------------------------------------------------------------


def cfg(dotted_key: str, *, default: Any = KeyError) -> Any:
    """
    Convenience shortcut to read a config value.

    First call triggers loading ``config.yaml``; subsequent calls use cache.

    Examples
    --------
    >>> cfg("recency.half_life_days")
    545
    >>> cfg("batting_acceleration_weights")
    {'overall_sr': 0.30, 'sr_growth': 0.25, 'death_sr': 0.20, 'impact': 0.25}
    >>> cfg("nonexistent.key", default=42)
    42
    """
    config = get_config()
    return config.get(dotted_key, default=default)
