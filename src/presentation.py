"""
Presentation layer — fan-facing grades and player archetypes.

This module adds two fan-friendly features on top of the existing 0-100
percentile scores produced by the rating system:

1. **Letter Grades** (S / A+ / A / B+ / B / C+ / C / D) mapped from the
   final 0-100 scores.  Also computes a single "overall" score that is
   NOT a simple average — if a player is elite in one dimension, that
   pulls the overall score up more than linearly (superstar bonus).

2. **Player Archetypes** — data-driven labels derived from the player's
   score profile.  Per algorithm_update.md, T20I batting archetypes are:
   Aggressive Opener, Anchor, Explosive Finisher, Float, Accumulator.
   T20I bowling archetypes are: Powerplay Enforcer, Containment Spinner,
   Death Specialist, Strike Pacer.

   First match wins in the rule list, so more specific / elite profiles
   come first.  Players who don't match any specific archetype get
   "Utility Player" as fallback.

Usage
-----
    from src.presentation import (
        add_batting_grades,
        add_bowling_grades,
        assign_batting_archetypes,
        assign_bowling_archetypes,
    )

    bat_careers = add_batting_grades(bat_careers)
    bowl_careers = add_bowling_grades(bowl_careers)
    bat_careers = assign_batting_archetypes(bat_careers)
    bowl_careers = assign_bowling_archetypes(bowl_careers)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import cfg

# ---------------------------------------------------------------------------
# Career production bonus constants (batting only)
# ---------------------------------------------------------------------------
# Rewards sustained run production in the overall score.  Players with more
# total career runs receive an additive bonus on top of the dimension-based
# overall.  This directly addresses finisher overvaluation: a player with
# 4000 runs gets the full bonus while a 700-run finisher gets very little.
#
#   bonus = RUNS_BONUS_MAX * clip(total_runs / RUNS_BONUS_REF, 0, 1) ** RUNS_BONUS_CURVE
#
# With defaults (max=2.0, ref=3000, curve=0.8):
#     500 runs → bonus 0.42
#    1000 runs → bonus 0.72
#    1500 runs → bonus 0.99
#    2000 runs → bonus 1.24
#    3000+ runs → bonus 2.00 (max)
RUNS_BONUS_MAX: float = cfg("presentation.runs_bonus_max", default=2.0)
RUNS_BONUS_REF: float = cfg("presentation.runs_bonus_ref", default=3000.0)
RUNS_BONUS_CURVE: float = cfg("presentation.runs_bonus_curve", default=0.8)

# ---------------------------------------------------------------------------
# Grade boundaries (default; overridable via config)
# ---------------------------------------------------------------------------

_DEFAULT_GRADE_BOUNDARIES: list[tuple[str, float]] = [
    ("S", 95.0),
    ("A+", 85.0),
    ("A", 75.0),
    ("B+", 60.0),
    ("B", 45.0),
    ("C+", 30.0),
    ("C", 15.0),
    ("D", 0.0),
]


def _get_grade_boundaries() -> list[tuple[str, float]]:
    """
    Return grade boundaries from config, falling back to defaults.

    Config format (``presentation.grade_boundaries``):
        S: 95
        A_plus: 85
        A: 75
        ...

    The ``A_plus`` key is normalised to ``A+`` for display.
    """
    raw: dict[str, float] | None = cfg("presentation.grade_boundaries", default=None)
    if raw is None:
        return _DEFAULT_GRADE_BOUNDARIES

    # Normalise key names: A_plus → A+, B_plus → B+, etc.
    normalised: dict[str, float] = {}
    for key, val in raw.items():
        display_key = key.replace("_plus", "+")
        normalised[display_key] = float(val)

    # Sort descending by threshold so the first match wins
    boundaries = sorted(normalised.items(), key=lambda kv: kv[1], reverse=True)
    return boundaries


def score_to_grade(score: float, boundaries: list[tuple[str, float]]) -> str:
    """Map a 0-100 score to a letter grade using the boundary table."""
    if pd.isna(score):
        return "?"
    for grade, threshold in boundaries:
        if score >= threshold:
            return grade
    return "D"


# ---------------------------------------------------------------------------
# Overall score (superstar-aware)
# ---------------------------------------------------------------------------


def _compute_overall_score(
    scores: list[float],
    *,
    superstar_threshold: float = 85.0,
    superstar_bonus_weight: float = 0.05,
) -> float:
    """
    Compute a single overall score from multiple sub-scores.

    This is NOT a simple average.  If a player is elite (above
    ``superstar_threshold``) in any dimension, they receive a bonus
    that pulls the overall score up.  This rewards specialists — a
    player who is the best finisher in the world deserves a higher
    overall than the mean of their three scores.

    Formula:
        base = weighted_mean(scores)      (equal weights)
        superstar_bonus = max(score − threshold) across elite scores
        overall = base + superstar_bonus_weight × superstar_bonus

    The bonus is capped at the **single best** dimension's excess above
    the threshold.  This prevents double/triple bonuses for players who
    are elite in multiple dimensions (e.g. Explosive Finishers with
    ACC=95, POW=95 now get bonus = max(10, 10) = 10, not 20).

    The weight was reduced from 0.15 → 0.10 → 0.05 as part of the
    Rating Rebalance (v3.0) to reduce overvaluation of explosive
    finishers whose ACC+POW both exceed the threshold.  The heavier
    lifting is now done by strengthened volume scaling and the career
    production bonus applied in ``add_batting_grades``.

    The result is clipped to [0, 100].
    """
    valid = [
        s for s in scores if not (s is None or (isinstance(s, float) and np.isnan(s)))
    ]
    if not valid:
        return np.nan

    base = float(np.mean(valid))

    # Superstar bonus: capped at the single best dimension's excess
    # (no double/triple bonus for multi-elite players)
    individual_bonuses = [max(s - superstar_threshold, 0.0) for s in valid]
    bonus = max(individual_bonuses) if individual_bonuses else 0.0
    overall = base + superstar_bonus_weight * bonus

    return float(np.clip(overall, 0.0, 100.0))


# ---------------------------------------------------------------------------
# Public API: Batting Grades
# ---------------------------------------------------------------------------


def _career_production_bonus(total_runs: float) -> float:
    """
    Compute an additive career production bonus from total runs scored.

    This rewards sustained high-volume production and directly addresses
    finisher overvaluation — a player with 4000 career runs gets the full
    bonus while a 700-run situational finisher gets very little.

    Formula::

        bonus = RUNS_BONUS_MAX * clip(total_runs / RUNS_BONUS_REF, 0, 1) ** RUNS_BONUS_CURVE

    With defaults (max=2.0, ref=3000, curve=0.8):
        500 runs → bonus ~0.42
       1000 runs → bonus ~0.72
       1500 runs → bonus ~0.99
       2000 runs → bonus ~1.24
       3000+ runs → bonus  2.00 (max)

    Parameters
    ----------
    total_runs : float
        Career total runs scored.

    Returns
    -------
    float — bonus in [0, RUNS_BONUS_MAX].
    """
    if pd.isna(total_runs) or total_runs <= 0:
        return 0.0
    ratio = min(total_runs / RUNS_BONUS_REF, 1.0)
    return RUNS_BONUS_MAX * (ratio**RUNS_BONUS_CURVE)


def add_batting_grades(bat_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Add grade columns to the batting careers DataFrame.

    New columns:
        - ``grade_acceleration``  (str, e.g. "A+")
        - ``grade_power``         (str)
        - ``grade_control``       (str)
        - ``overall_score``       (float, 0-100)
        - ``overall_grade``       (str)

    The overall score is the superstar-aware mean of the three dimension
    scores **plus** a career production bonus derived from total runs.
    This ensures that consistent high-volume producers rank above
    situational finishers with comparable per-ball metrics.

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Must contain ``score_acceleration``, ``score_power``, ``score_control``.
        If ``total_runs`` is present, it is used for the production bonus.

    Returns
    -------
    pd.DataFrame with new columns appended.
    """
    df = bat_careers.copy()
    boundaries = _get_grade_boundaries()

    score_cols = ["score_acceleration", "score_power", "score_control"]
    grade_names = ["grade_acceleration", "grade_power", "grade_control"]

    for score_col, grade_col in zip(score_cols, grade_names):
        if score_col in df.columns:
            df[grade_col] = df[score_col].apply(lambda s: score_to_grade(s, boundaries))
        else:
            df[grade_col] = "?"

    has_runs = "total_runs" in df.columns

    # Overall score with superstar bonus + career production bonus
    def _row_overall(row: pd.Series) -> float:
        scores = [
            row.get("score_acceleration", np.nan),
            row.get("score_power", np.nan),
            row.get("score_control", np.nan),
        ]
        base = _compute_overall_score(scores)
        if np.isnan(base):
            return base

        # Career production bonus — additive, rewards total runs scored
        if has_runs:
            runs = row.get("total_runs", 0.0)
            base += _career_production_bonus(runs)

        return float(np.clip(base, 0.0, 100.0))

    df["overall_score"] = df.apply(_row_overall, axis=1).round(1)
    df["overall_grade"] = df["overall_score"].apply(
        lambda s: score_to_grade(s, boundaries)
    )

    return df


def add_bowling_grades(bowl_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Add grade columns to the bowling careers DataFrame.

    New columns:
        - ``grade_accuracy``  (str)
        - ``grade_control``   (str)
        - ``grade_threat``    (str)
        - ``overall_score``   (float, 0-100)
        - ``overall_grade``   (str)
    """
    df = bowl_careers.copy()
    boundaries = _get_grade_boundaries()

    score_cols = ["score_accuracy", "score_control", "score_threat"]
    grade_names = ["grade_accuracy", "grade_control", "grade_threat"]

    for score_col, grade_col in zip(score_cols, grade_names):
        if score_col in df.columns:
            df[grade_col] = df[score_col].apply(lambda s: score_to_grade(s, boundaries))
        else:
            df[grade_col] = "?"

    def _row_overall(row: pd.Series) -> float:
        scores = [
            row.get("score_accuracy", np.nan),
            row.get("score_control", np.nan),
            row.get("score_threat", np.nan),
        ]
        return _compute_overall_score(scores)

    df["overall_score"] = df.apply(_row_overall, axis=1).round(1)
    df["overall_grade"] = df["overall_score"].apply(
        lambda s: score_to_grade(s, boundaries)
    )

    return df


# ---------------------------------------------------------------------------
# Archetype definitions (T20I — per algorithm_update.md)
# ---------------------------------------------------------------------------
#
# Each archetype is a (name, conditions_dict) tuple.
# Conditions use the 0-100 score columns.
#
# - ``"acceleration": 85`` means ``score_acceleration >= 85``
# - ``"acceleration_max": 55`` means ``score_acceleration <= 55``
#
# Order matters — first match wins — so the most specific / elite profiles
# come first.  "Utility Player" is the fallback.
#
# T20I batting archetypes from algorithm_update.md:
#   Aggressive Opener, Anchor, Explosive Finisher, Float, Accumulator
# T20I bowling archetypes from algorithm_update.md:
#   Powerplay Enforcer, Containment Spinner, Death Specialist, Strike Pacer
#
# We add a few more nuanced archetypes that naturally emerge from the data
# to avoid too many players falling into the "Utility Player" bucket.
# ---------------------------------------------------------------------------

BATTING_ARCHETYPES: list[tuple[str, dict[str, float]]] = [
    # ── T20I archetypes per algorithm_update.md ──
    # Order matters: first match wins.  More specific archetypes must
    # come before broader catch-alls like Float.
    #
    # Position-aware conditions:
    #   position_min / position_max use modal_position (1-11).
    #   Ensures openers aren't labelled "Explosive Finisher" just
    #   because they have elite ACC+POW — finishers must bat deep.
    #
    # Explosive Opener: top-order (1-3) with elite acceleration + power
    ("Explosive Opener", {"acceleration": 85, "power": 85, "position_max": 3}),
    # Explosive Finisher: elite acceleration + power, bats in middle/lower (4+)
    ("Explosive Finisher", {"acceleration": 85, "power": 85, "position_min": 4}),
    # Power Hitter: extreme power, lower control — high-risk slogger
    ("Power Hitter", {"power": 85, "control_max": 50}),
    # Pinch Hitter: extreme acceleration, low control — quick cameos
    ("Pinch Hitter", {"acceleration": 85, "control_max": 45}),
    # Aggressive Opener: high acceleration + decent power, fast starts (top-order)
    ("Aggressive Opener", {"acceleration": 80, "power": 65, "position_max": 3}),
    # Power Middle-Order: high acceleration + decent power, bats 4+ (not an opener)
    ("Power Middle-Order", {"acceleration": 80, "power": 65, "position_min": 4}),
    # Classic Anchor: elite control, moderate acceleration — stabilises innings
    ("Classic Anchor", {"control": 80, "acceleration_max": 55}),
    # Power Anchor: power + control hybrid — can hold and hit
    ("Power Anchor", {"power": 75, "control": 70}),
    # All-Round Elite: high across all three dimensions
    ("All-Round Elite", {"acceleration": 72, "power": 68, "control": 68}),
    # Strike Rotator: elite control, low power — pure rotation player
    ("Strike Rotator", {"control": 75, "power_max": 40}),
    # Accumulator: high control, low power/acceleration — rotates strike
    ("Accumulator", {"control": 70, "acceleration_max": 50, "power_max": 50}),
    # Float: balanced profile — adapts role to match situation (broad catch-all)
    ("Float", {"acceleration": 60, "power": 55, "control": 60}),
]

BOWLING_ARCHETYPES: list[tuple[str, dict[str, float]]] = [
    # ── T20I archetypes per algorithm_update.md ──
    # Order matters: first match wins.  More specific archetypes first.
    #
    # Death Specialist: elite accuracy + control at the death, takes wickets
    ("Death Specialist", {"accuracy": 75, "control": 75, "threat": 70}),
    # Powerplay Enforcer: high threat + accuracy upfront — new ball dominator
    ("Powerplay Enforcer", {"threat": 75, "accuracy": 70}),
    # Strike Bowler: elite threat — breaks partnerships at will
    ("Strike Bowler", {"threat": 80}),
    # Spin Restrictor: elite accuracy, restricts scoring in middle overs
    ("Spin Restrictor", {"accuracy": 80, "threat_max": 55}),
    # Economical: elite accuracy + control, modest threat
    ("Economical", {"accuracy": 78, "control": 72, "threat_max": 55}),
    # All-Round Threat: high across all three dimensions
    ("All-Round Threat", {"accuracy": 70, "control": 70, "threat": 70}),
    # Restrictive Spinner: high accuracy, low threat — dries up runs
    ("Restrictive Spinner", {"accuracy": 75, "threat_max": 45}),
    # Enforcer: high threat, moderate accuracy — aggressive pace bowler
    ("Enforcer", {"threat": 72, "accuracy": 55}),
]

# Mapping from short condition keys to actual DataFrame column names
_BAT_SCORE_MAP: dict[str, str] = {
    "acceleration": "score_acceleration",
    "power": "score_power",
    "control": "score_control",
}

_BOWL_SCORE_MAP: dict[str, str] = {
    "accuracy": "score_accuracy",
    "control": "score_control",
    "threat": "score_threat",
}


def _conditions_match(
    row: pd.Series,
    conditions: dict[str, float],
    score_map: dict[str, str],
) -> bool:
    """
    Check whether a single archetype's conditions are all satisfied.

    Conditions ending with ``_max`` are upper bounds (<=);
    all others are lower bounds (>=).

    Special positional conditions (not in *score_map*):
        - ``position_min`` — ``modal_position >= value``
        - ``position_max`` — ``modal_position <= value``
    These read directly from the row's ``modal_position`` column.
    """
    for cond_key, threshold in conditions.items():
        # ── Positional conditions (bypass score_map) ──
        if cond_key in ("position_min", "position_max"):
            if "modal_position" not in row.index:
                return False
            pos = row["modal_position"]
            if pd.isna(pos):
                return False
            pos_val = float(pos)
            if cond_key == "position_min" and pos_val < threshold:
                return False
            if cond_key == "position_max" and pos_val > threshold:
                return False
            continue

        is_upper_bound = cond_key.endswith("_max")
        base_key = cond_key.replace("_max", "") if is_upper_bound else cond_key

        col = score_map.get(base_key)
        if col is None or col not in row.index:
            return False

        value = row[col]
        if pd.isna(value):
            return False

        if is_upper_bound:
            if value > threshold:
                return False
        else:
            if value < threshold:
                return False

    return True


def _match_archetype(
    row: pd.Series,
    archetypes: list[tuple[str, dict[str, float]]],
    score_map: dict[str, str],
    fallback: str = "Utility Player",
) -> str:
    """
    Return the first archetype whose conditions are all satisfied.

    Conditions ending with ``_max`` are upper bounds (<=);
    all others are lower bounds (>=).
    """
    for archetype_name, conditions in archetypes:
        if _conditions_match(row, conditions, score_map):
            return archetype_name

    return fallback


def _match_archetypes(
    row: pd.Series,
    archetypes: list[tuple[str, dict[str, float]]],
    score_map: dict[str, str],
    top_n: int = 3,
    fallback: str = "Utility Player",
) -> list[str]:
    """
    Return up to *top_n* matching archetypes for a player.

    Every archetype whose conditions are satisfied is collected (in
    definition order).  If nothing matches the *fallback* label is
    returned as the sole entry.
    """
    matched: list[str] = []
    for archetype_name, conditions in archetypes:
        if _conditions_match(row, conditions, score_map):
            matched.append(archetype_name)
            if len(matched) >= top_n:
                break

    if not matched:
        matched.append(fallback)
    return matched


# ---------------------------------------------------------------------------
# Public API: Archetypes
# ---------------------------------------------------------------------------


def assign_batting_archetypes(bat_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Assign archetype labels to each batter.

    New columns:
        - ``archetype``   — primary (first-match) archetype for backward compat.
        - ``archetypes``  — comma-separated top-3 matching archetypes.

    Uses the final 0-100 scores (``score_acceleration``, ``score_power``,
    ``score_control``) so this is zero-cost on the pipeline — just adds
    columns.

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Must contain ``score_acceleration``, ``score_power``, ``score_control``.

    Returns
    -------
    pd.DataFrame with new ``archetype`` and ``archetypes`` columns.
    """
    archetypes_enabled = cfg("presentation.archetypes_enabled", default=True)
    df = bat_careers.copy()

    if not archetypes_enabled:
        df["archetype"] = ""
        df["archetypes"] = ""
        return df

    def _row_archetypes(row: pd.Series) -> list[str]:
        return _match_archetypes(row, BATTING_ARCHETYPES, _BAT_SCORE_MAP, top_n=3)

    all_matches = df.apply(_row_archetypes, axis=1)
    df["archetype"] = all_matches.apply(lambda m: m[0])
    df["archetypes"] = all_matches.apply(lambda m: ", ".join(m))
    return df


def assign_bowling_archetypes(bowl_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Assign archetype labels to each bowler.

    New columns:
        - ``archetype``   — primary (first-match) archetype for backward compat.
        - ``archetypes``  — comma-separated top-3 matching archetypes.

    Uses ``score_accuracy``, ``score_control``, ``score_threat``.

    Returns
    -------
    pd.DataFrame with new ``archetype`` and ``archetypes`` columns.
    """
    archetypes_enabled = cfg("presentation.archetypes_enabled", default=True)
    df = bowl_careers.copy()

    if not archetypes_enabled:
        df["archetype"] = ""
        df["archetypes"] = ""
        return df

    def _row_archetypes(row: pd.Series) -> list[str]:
        return _match_archetypes(row, BOWLING_ARCHETYPES, _BOWL_SCORE_MAP, top_n=3)

    all_matches = df.apply(_row_archetypes, axis=1)
    df["archetype"] = all_matches.apply(lambda m: m[0])
    df["archetypes"] = all_matches.apply(lambda m: ", ".join(m))
    return df
