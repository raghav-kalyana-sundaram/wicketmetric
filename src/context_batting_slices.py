"""
Context-sliced batting career tables for GUI leaderboards.

Entry-phase slices use innings where the batter's first faced ball is in a
given over range (early: 1–4, death: 16–20). Careers are re-aggregated from
filtered per-innings components with the core rating + presentation pipeline
(ratings, avg gate, volume scaling, competition gate when enabled, grades,
archetypes). Chase / peak / WAR enrichments are intentionally omitted.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from src.batting import (
    aggregate_batting_careers,
    apply_avg_quality_gate,
    apply_competition_quality_gate,
    apply_volume_scaling,
)
from src.presentation import add_batting_grades, assign_batting_archetypes
from src.rating import apply_rating_system


def _filter_components_by_entry_phase(
    bat_components: pd.DataFrame, phase: Literal["early", "death"]
) -> pd.DataFrame:
    if bat_components.empty or "entry_over" not in bat_components.columns:
        return pd.DataFrame()
    eo = pd.to_numeric(bat_components["entry_over"], errors="coerce")
    if phase == "early":
        mask = eo.between(1, 4, inclusive="both")
    else:
        mask = eo.between(16, 20, inclusive="both")
    return bat_components.loc[mask].copy()


def _finalize_context_bat_careers(
    bat_components_slice: pd.DataFrame,
    *,
    min_bat_innings: int,
    survival_rates: pd.DataFrame | None,
    cabi_data: pd.DataFrame | None,
    shrinkage_k_bat: float,
    confidence_alpha: float,
    is_franchise: bool,
    competition_gate_enabled: bool,
) -> pd.DataFrame:
    if bat_components_slice.empty:
        return pd.DataFrame()
    career = aggregate_batting_careers(
        bat_components_slice,
        min_innings=min_bat_innings,
        survival_rates=survival_rates,
        cabi_data=cabi_data,
    )
    if career.empty:
        return career
    last_dt = (
        bat_components_slice.groupby(["batter_id", "batter"], observed=True)["date"]
        .max()
        .reset_index(name="last_match_date")
    )
    career = career.merge(last_dt, on=["batter_id", "batter"], how="left")
    career = apply_rating_system(
        career,
        raw_cols=["raw_acceleration", "raw_power", "raw_control"],
        sample_col="innings_count",
        provisional_col="is_provisional_bat",
        shrinkage_k=shrinkage_k_bat,
        confidence_alpha=confidence_alpha,
    )
    career = apply_avg_quality_gate(career)
    career = apply_volume_scaling(career)
    if not is_franchise and competition_gate_enabled:
        career = apply_competition_quality_gate(career)
    career = add_batting_grades(career)
    career = assign_batting_archetypes(career)
    return career


def build_entry_phase_bat_career_tables(
    bat_components: pd.DataFrame,
    *,
    min_bat_innings: int,
    survival_rates: pd.DataFrame | None,
    cabi_data: pd.DataFrame | None,
    shrinkage_k_bat: float,
    confidence_alpha: float,
    is_franchise: bool,
    competition_gate_enabled: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (early_entry_careers, death_entry_careers)."""
    early = _filter_components_by_entry_phase(bat_components, "early")
    death = _filter_components_by_entry_phase(bat_components, "death")
    return (
        _finalize_context_bat_careers(
            early,
            min_bat_innings=min_bat_innings,
            survival_rates=survival_rates,
            cabi_data=cabi_data,
            shrinkage_k_bat=shrinkage_k_bat,
            confidence_alpha=confidence_alpha,
            is_franchise=is_franchise,
            competition_gate_enabled=competition_gate_enabled,
        ),
        _finalize_context_bat_careers(
            death,
            min_bat_innings=min_bat_innings,
            survival_rates=survival_rates,
            cabi_data=cabi_data,
            shrinkage_k_bat=shrinkage_k_bat,
            confidence_alpha=confidence_alpha,
            is_franchise=is_franchise,
            competition_gate_enabled=competition_gate_enabled,
        ),
    )
