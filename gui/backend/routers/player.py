"""
Player router — /api/player/{id} endpoints.

Provides:
- GET /api/player/{id}          → Full player profile (batting or bowling)
- GET /api/player/{id}/innings   → Paginated innings log (batting)
- GET /api/player/{id}/spells    → Paginated spells log (bowling)
- GET /api/player/{id}/form      → Form time-series
- GET /api/player/{id}/matchups  → Head-to-head matchup list
- GET /api/player/{id}/similar   → Similar players
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from schemas import (
    BatterProfile,
    BowlerProfile,
    ChaseSplit,
    ComponentBreakdown,
    FormPoint,
    FormResponse,
    InningsDetail,
    MatchupExploreResponse,
    MatchupSummary,
    PhaseSplit,
    PlayerRoles,
    SimilarityResponse,
    SimilarPlayer,
    SpellDetail,
)

if TYPE_CHECKING:
    from data_loader import DataStore

router = APIRouter(prefix="/api", tags=["player"])


# ── Dependency placeholders (overridden in app.py) ────────────────


def _get_store():
    raise RuntimeError("DataStore not initialised")


def _get_search_index():
    raise RuntimeError("Search index not initialised")


# ── Helpers ───────────────────────────────────────────────────────


def _safe_float(v: Any) -> float | None:
    """Convert to float, returning None for NaN/inf."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>", "NaT"):
        return default
    return s


def _get_val(row: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from a pandas Series or dict."""
    try:
        v = row.get(key, default) if hasattr(row, "get") else getattr(row, key, default)
        return v
    except Exception:
        return default


# ── Profile builders ──────────────────────────────────────────────


def _build_batting_phase_splits(row: Any) -> dict[str, PhaseSplit]:
    """Extract powerplay/middle/death phase splits from a career row."""
    phases = {}
    # We pull phase data from the career row if available, or leave empty
    # (Detailed phase data is in bat_innings; career row has aggregate phase cols)
    # The career row doesn't store phase aggregates directly — those come from innings.
    # We'll return empty phase splits here; the frontend can compute from innings data.
    return phases


def _build_batting_chase_splits(row: Any) -> dict[str, ChaseSplit]:
    """Extract setting/chasing splits from the career row.

    Now includes actual SR and batting average for each split (computed
    by the pipeline's enhanced ``compute_chase_splits``), in addition to
    the differential composite indices.
    """
    splits = {}
    setting_inn = _safe_int(_get_val(row, "setting_inn"))
    chasing_inn = _safe_int(_get_val(row, "chasing_inn"))

    if setting_inn is not None and setting_inn > 0:
        splits["setting"] = ChaseSplit(
            innings=setting_inn,
            avg=_safe_float(_get_val(row, "setting_avg")),
            sr=_safe_float(_get_val(row, "setting_sr")),
            composite=_safe_float(_get_val(row, "bat_first_index")),
        )
    if chasing_inn is not None and chasing_inn > 0:
        splits["chasing"] = ChaseSplit(
            innings=chasing_inn,
            avg=_safe_float(_get_val(row, "chasing_avg")),
            sr=_safe_float(_get_val(row, "chasing_sr")),
            composite=_safe_float(_get_val(row, "chase_master_index")),
        )
    return splits


def _build_batting_components(row: Any) -> dict[str, ComponentBreakdown]:
    """Extract sub-component breakdowns for acceleration, power, control."""
    components = {}

    # Acceleration components
    acc_vals = {}
    for key in [
        "acc_overall_sr_mean",
        "acc_sr_growth_mean",
        "acc_death_sr_mean",
        "acc_impact_mean",
        "acc_runs_above_expected_mean",
    ]:
        label = key.replace("acc_", "").replace("_mean", "")
        acc_vals[label] = _safe_float(_get_val(row, key))
    components["acceleration"] = ComponentBreakdown(values=acc_vals)

    # Power components
    pow_vals = {}
    for key in [
        "pow_boundary_pct_mean",
        "pow_six_rate_mean",
        "pow_boundary_rate_vs_par_mean",
        "pow_peak_phase_sr_mean",
        "pow_finishing_burst_mean",
        "pow_power_impact_mean",
    ]:
        label = key.replace("pow_", "").replace("_mean", "")
        pow_vals[label] = _safe_float(_get_val(row, key))
    components["power"] = ComponentBreakdown(values=pow_vals)

    # Control components
    ctrl_vals = {}
    for key in [
        "ctrl_dot_pct_weighted_mean",
        "ctrl_scoring_consistency_mean",
        "ctrl_rotation_mean",
        "ctrl_contribution_mean",
        "ctrl_avg_proxy_mean",
        "ctrl_dismissal_quality_mean",
    ]:
        label = key.replace("ctrl_", "").replace("_mean", "")
        ctrl_vals[label] = _safe_float(_get_val(row, key))
    components["control"] = ComponentBreakdown(values=ctrl_vals)

    return components


def _build_bowling_components(row: Any) -> dict[str, ComponentBreakdown]:
    """Extract sub-component breakdowns for accuracy, control, threat."""
    components = {}

    acc_vals = {}
    for key in [
        "acc_economy_vs_par_mean",
        "acc_dot_pct_mean",
        "acc_extras_penalty_mean",
        "acc_boundary_penalty_mean",
    ]:
        label = key.replace("acc_", "").replace("_mean", "")
        acc_vals[label] = _safe_float(_get_val(row, key))
    components["accuracy"] = ComponentBreakdown(values=acc_vals)

    ctrl_vals = {}
    for key in [
        "ctrl_entropy_mean",
        "ctrl_extras_mean",
        "ctrl_vs_others_mean",
        "ctrl_extras_pct_mean",
        "ctrl_economy_vs_par_mean",
        "ctrl_phase_consistency_mean",
    ]:
        label = key.replace("ctrl_", "").replace("_mean", "")
        ctrl_vals[label] = _safe_float(_get_val(row, key))
    components["control"] = ComponentBreakdown(values=ctrl_vals)

    threat_vals = {}
    for key in [
        "threat_wickets_mean",
        "threat_quality_wickets_mean",
        "threat_pressure_mean",
        "threat_dots_mean",
        "threat_sr_mean",
    ]:
        label = key.replace("threat_", "").replace("_mean", "")
        threat_vals[label] = _safe_float(_get_val(row, key))
    components["threat"] = ComponentBreakdown(values=threat_vals)

    return components


def _matchup_row_to_summary(
    row: Any, opponent_id_col: str, opponent_name_col: str
) -> MatchupSummary:
    """Convert a matchup DataFrame row to a MatchupSummary."""
    return MatchupSummary(
        opponent_id=_safe_str(_get_val(row, opponent_id_col)),
        opponent_name=_safe_str(_get_val(row, opponent_name_col)),
        balls=_safe_int(_get_val(row, "balls_faced")) or 0,
        runs=_safe_int(_get_val(row, "runs_scored")) or 0,
        sr=_safe_float(_get_val(row, "strike_rate")),
        dismissals=_safe_int(_get_val(row, "dismissals")) or 0,
        dot_pct=_safe_float(_get_val(row, "dot_pct")),
        boundary_pct=_safe_float(_get_val(row, "boundary_pct")),
        dominance_index=_safe_float(_get_val(row, "dominance_index")),
    )


def _build_batter_profile(
    row: Any,
    store: "DataStore",
    top_k_matchups: int = 5,
) -> BatterProfile:
    """Build a full BatterProfile from a batting career row + supporting data."""
    from data_loader import (
        get_batter_similarities,
        get_matchups_for_batter,
    )

    batter_id = _safe_str(_get_val(row, "batter_id"))

    # ── Top matchups ──────────────────────────────────────────
    top_dominant: list[MatchupSummary] = []
    top_nemeses: list[MatchupSummary] = []

    matchups_df = get_matchups_for_batter(store, batter_id, min_balls=6)
    if not matchups_df.empty:
        # Top dominant: highest dominance_index (batter dominates)
        dominant_df = matchups_df.nlargest(top_k_matchups, "dominance_index")
        for _, mrow in dominant_df.iterrows():
            top_dominant.append(_matchup_row_to_summary(mrow, "bowler_id", "bowler"))

        # Top nemeses: lowest dominance_index (bowler dominates)
        nemesis_df = matchups_df.nsmallest(top_k_matchups, "dominance_index")
        for _, mrow in nemesis_df.iterrows():
            top_nemeses.append(_matchup_row_to_summary(mrow, "bowler_id", "bowler"))

    # ── Similar players ───────────────────────────────────────
    similar: list[SimilarPlayer] = []
    sim_df = get_batter_similarities(store, batter_id)
    if not sim_df.empty:
        for _, srow in sim_df.head(10).iterrows():
            comp_id = _safe_str(_get_val(srow, "comp_batter_id"))
            # Look up the comp's scores from bat_careers
            comp_row = None
            if not store.bat_careers.empty:
                mask = store.bat_careers["batter_id"] == comp_id
                comp_matches = store.bat_careers.loc[mask]
                if not comp_matches.empty:
                    comp_row = comp_matches.iloc[0]

            similar.append(
                SimilarPlayer(
                    id=comp_id,
                    name=_safe_str(_get_val(srow, "comp_batter")),
                    country=_safe_str(
                        _get_val(comp_row, "country") if comp_row is not None else None
                    ),
                    similarity_score=_safe_float(_get_val(srow, "similarity")),
                    score_1=_safe_float(
                        _get_val(comp_row, "score_acceleration")
                        if comp_row is not None
                        else None
                    ),
                    score_2=_safe_float(
                        _get_val(comp_row, "score_power")
                        if comp_row is not None
                        else None
                    ),
                    score_3=_safe_float(
                        _get_val(comp_row, "score_control")
                        if comp_row is not None
                        else None
                    ),
                    score_1_label="acceleration",
                    score_2_label="power",
                    score_3_label="control",
                )
            )

    return BatterProfile(
        id=batter_id,
        name=_safe_str(_get_val(row, "batter")),
        country=_safe_str(_get_val(row, "country")),
        archetype=_safe_str(_get_val(row, "archetype")),
        archetypes=[
            a.strip()
            for a in _safe_str(_get_val(row, "archetypes")).split(",")
            if a.strip()
        ]
        or [_safe_str(_get_val(row, "archetype")) or "Utility Player"],
        position_group=_safe_str(_get_val(row, "position_group")),
        # Career stats
        innings_count=_safe_int(_get_val(row, "innings_count")) or 0,
        total_runs=_safe_int(_get_val(row, "total_runs")) or 0,
        total_balls=_safe_int(_get_val(row, "total_balls")) or 0,
        total_fours=_safe_int(_get_val(row, "total_fours")) or 0,
        total_sixes=_safe_int(_get_val(row, "total_sixes")) or 0,
        total_outs=_safe_int(_get_val(row, "total_outs")) or 0,
        career_sr=_safe_float(_get_val(row, "career_sr")),
        career_avg=_safe_float(_get_val(row, "career_avg")),
        # Scores
        score_acceleration=_safe_float(_get_val(row, "score_acceleration")),
        score_power=_safe_float(_get_val(row, "score_power")),
        score_control=_safe_float(_get_val(row, "score_control")),
        # Grades
        grade_acceleration=_safe_str(_get_val(row, "grade_acceleration"), "D"),
        grade_power=_safe_str(_get_val(row, "grade_power"), "D"),
        grade_control=_safe_str(_get_val(row, "grade_control"), "D"),
        overall_score=_safe_float(_get_val(row, "overall_score")),
        overall_grade=_safe_str(_get_val(row, "overall_grade"), "D"),
        # Provisional
        is_provisional=bool(_get_val(row, "is_provisional_bat", True)),
        # Peak ratings
        peak_composite_batting=_safe_float(_get_val(row, "peak_composite_batting")),
        peak_window_start=_safe_str(_get_val(row, "peak_window_start")) or None,
        peak_window_end=_safe_str(_get_val(row, "peak_window_end")) or None,
        peak_window_innings=_safe_int(_get_val(row, "peak_window_innings")),
        peak_window_composite=_safe_float(_get_val(row, "peak_window_composite")),
        # Advanced metrics
        war_batting=_safe_float(_get_val(row, "war_batting")),
        war_batting_rate=_safe_float(_get_val(row, "war_batting_rate")),
        clutch_index=_safe_float(_get_val(row, "clutch_index")),
        clutch_sr_delta=_safe_float(_get_val(row, "clutch_sr_delta")),
        pressure_innings=_safe_int(_get_val(row, "pressure_innings")),
        chase_master_index=_safe_float(_get_val(row, "chase_master_index")),
        chase_master_full=_safe_float(_get_val(row, "chase_master_full")),
        flat_track_index=_safe_float(_get_val(row, "flat_track_index")),
        venue_adjusted_composite=_safe_float(_get_val(row, "venue_adjusted_composite")),
        selfless_index=_safe_float(_get_val(row, "selfless_index")),
        anchor_cost_ratio=_safe_float(_get_val(row, "anchor_cost_ratio")),
        avg_balls_to_par=_safe_float(_get_val(row, "avg_balls_to_par")),
        # Matchup summary
        avg_dominance=_safe_float(_get_val(row, "avg_dominance")),
        pct_dominant=_safe_float(_get_val(row, "pct_dominant")),
        matchup_consistency=_safe_float(_get_val(row, "matchup_consistency")),
        unique_bowlers=_safe_int(_get_val(row, "unique_bowlers")),
        # Structured sections
        phases=_build_batting_phase_splits(row),
        chase_splits=_build_batting_chase_splits(row),
        components=_build_batting_components(row),
        # Matchups & similarity
        top_dominant=top_dominant,
        top_nemeses=top_nemeses,
        similar=similar,
    )


def _build_bowler_profile(
    row: Any,
    store: "DataStore",
    top_k_matchups: int = 5,
) -> BowlerProfile:
    """Build a full BowlerProfile from a bowling career row + supporting data."""
    from data_loader import (
        get_bowler_similarities,
        get_matchups_for_bowler,
    )

    bowler_id = _safe_str(_get_val(row, "bowler_id"))

    # ── Top matchups ──────────────────────────────────────────
    top_bunnies: list[MatchupSummary] = []
    top_dominated_by: list[MatchupSummary] = []

    matchups_df = get_matchups_for_bowler(store, bowler_id, min_balls=6)
    if not matchups_df.empty:
        # Bunnies: lowest dominance_index (bowler dominates batter)
        bunnies_df = matchups_df.nsmallest(top_k_matchups, "dominance_index")
        for _, mrow in bunnies_df.iterrows():
            top_bunnies.append(_matchup_row_to_summary(mrow, "batter_id", "batter"))

        # Dominated by: highest dominance_index (batter dominates bowler)
        dom_df = matchups_df.nlargest(top_k_matchups, "dominance_index")
        for _, mrow in dom_df.iterrows():
            top_dominated_by.append(
                _matchup_row_to_summary(mrow, "batter_id", "batter")
            )

    # ── Similar bowlers ───────────────────────────────────────
    similar: list[SimilarPlayer] = []
    sim_df = get_bowler_similarities(store, bowler_id)
    if not sim_df.empty:
        for _, srow in sim_df.head(10).iterrows():
            comp_id = _safe_str(_get_val(srow, "comp_bowler_id"))
            comp_row = None
            if not store.bowl_careers.empty:
                mask = store.bowl_careers["bowler_id"] == comp_id
                comp_matches = store.bowl_careers.loc[mask]
                if not comp_matches.empty:
                    comp_row = comp_matches.iloc[0]

            similar.append(
                SimilarPlayer(
                    id=comp_id,
                    name=_safe_str(_get_val(srow, "comp_bowler")),
                    country=_safe_str(
                        _get_val(comp_row, "country") if comp_row is not None else None
                    ),
                    similarity_score=_safe_float(_get_val(srow, "similarity")),
                    score_1=_safe_float(
                        _get_val(comp_row, "score_accuracy")
                        if comp_row is not None
                        else None
                    ),
                    score_2=_safe_float(
                        _get_val(comp_row, "score_control")
                        if comp_row is not None
                        else None
                    ),
                    score_3=_safe_float(
                        _get_val(comp_row, "score_threat")
                        if comp_row is not None
                        else None
                    ),
                    score_1_label="accuracy",
                    score_2_label="control",
                    score_3_label="threat",
                )
            )

    return BowlerProfile(
        id=bowler_id,
        name=_safe_str(_get_val(row, "bowler")),
        country=_safe_str(_get_val(row, "country")),
        archetype=_safe_str(_get_val(row, "archetype")),
        archetypes=[
            a.strip()
            for a in _safe_str(_get_val(row, "archetypes")).split(",")
            if a.strip()
        ]
        or [_safe_str(_get_val(row, "archetype")) or "Utility Player"],
        phase_group=_safe_str(_get_val(row, "phase_group")),
        # Career stats
        matches=_safe_int(_get_val(row, "matches")) or 0,
        total_overs=_safe_float(_get_val(row, "total_overs")),
        total_wickets=_safe_int(_get_val(row, "total_wickets")) or 0,
        total_runs_conceded=_safe_int(_get_val(row, "total_runs_conceded")) or 0,
        career_economy=_safe_float(_get_val(row, "career_economy")),
        career_sr_bowl=_safe_float(_get_val(row, "career_sr_bowl")),
        career_dot_pct=_safe_float(_get_val(row, "career_dot_pct")),
        bowled_lbw_pct=_safe_float(_get_val(row, "bowled_lbw_pct")),
        # Scores
        score_accuracy=_safe_float(_get_val(row, "score_accuracy")),
        score_control=_safe_float(_get_val(row, "score_control")),
        score_threat=_safe_float(_get_val(row, "score_threat")),
        # Grades
        grade_accuracy=_safe_str(_get_val(row, "grade_accuracy"), "D"),
        grade_control=_safe_str(_get_val(row, "grade_control"), "D"),
        grade_threat=_safe_str(_get_val(row, "grade_threat"), "D"),
        overall_score=_safe_float(_get_val(row, "overall_score")),
        overall_grade=_safe_str(_get_val(row, "overall_grade"), "D"),
        # Provisional
        is_provisional=bool(_get_val(row, "is_provisional_bowl", True)),
        # Peak ratings
        peak_composite_bowling=_safe_float(_get_val(row, "peak_composite_bowling")),
        peak_window_start=_safe_str(_get_val(row, "peak_window_start")) or None,
        peak_window_end=_safe_str(_get_val(row, "peak_window_end")) or None,
        peak_window_spells=_safe_int(_get_val(row, "peak_window_spells")),
        peak_window_composite=_safe_float(_get_val(row, "peak_window_composite")),
        # Advanced metrics
        war_bowling=_safe_float(_get_val(row, "war_bowling")),
        war_bowling_rate=_safe_float(_get_val(row, "war_bowling_rate")),
        clutch_index_bowl=_safe_float(_get_val(row, "clutch_index_bowl")),
        pressure_spells=_safe_int(_get_val(row, "pressure_spells")),
        flat_track_index_bowl=_safe_float(_get_val(row, "flat_track_index_bowl")),
        # Matchup summary
        avg_dominance_bowl=_safe_float(_get_val(row, "avg_dominance_bowl")),
        pct_dominant_bowl=_safe_float(_get_val(row, "pct_dominant_bowl")),
        # Structured sections
        phases={},
        components=_build_bowling_components(row),
        # Matchups & similarity
        top_bunnies=top_bunnies,
        top_dominated_by=top_dominated_by,
        similar=similar,
    )


# ── Phase splits computed from innings data ───────────────────────


def _compute_batting_phase_splits(
    store: "DataStore", batter_id: str
) -> dict[str, PhaseSplit]:
    """Aggregate phase splits from innings detail for a batter."""
    if store.bat_innings.empty:
        return {}

    mask = store.bat_innings["batter_id"] == batter_id
    innings = store.bat_innings.loc[mask]
    if innings.empty:
        return {}

    phases = {}
    for phase_name, prefix in [
        ("powerplay", "powerplay"),
        ("middle", "middle"),
        ("death", "death"),
    ]:
        balls_col = f"{prefix}_balls"
        runs_col = f"{prefix}_runs"
        dots_col = f"{prefix}_dots"
        fours_col = f"{prefix}_fours"
        sixes_col = f"{prefix}_sixes"

        if balls_col not in innings.columns:
            continue

        total_balls = innings[balls_col].sum()
        total_runs = innings[runs_col].sum() if runs_col in innings.columns else None
        total_dots = innings[dots_col].sum() if dots_col in innings.columns else None
        total_fours = innings[fours_col].sum() if fours_col in innings.columns else None
        total_sixes = innings[sixes_col].sum() if sixes_col in innings.columns else None

        avg_sr = None
        if total_balls and total_balls > 0 and total_runs is not None:
            avg_sr = round(float(total_runs) / float(total_balls) * 100, 1)

        dot_pct_val = None
        if total_balls and total_balls > 0 and total_dots is not None:
            dot_pct_val = round(float(total_dots) / float(total_balls) * 100, 1)

        bdry_pct_val = None
        if total_balls and total_balls > 0:
            bdry_total = int(total_fours or 0) + int(total_sixes or 0)
            bdry_pct_val = round(float(bdry_total) / float(total_balls) * 100, 1)

        phases[phase_name] = PhaseSplit(
            balls=_safe_int(total_balls),
            runs=_safe_int(total_runs),
            sr=avg_sr,
            dots=_safe_int(total_dots),
            fours=_safe_int(total_fours),
            sixes=_safe_int(total_sixes),
            dot_pct=dot_pct_val,
            boundary_pct=bdry_pct_val,
        )

    return phases


def _compute_bowling_phase_splits(
    store: "DataStore", bowler_id: str
) -> dict[str, PhaseSplit]:
    """Aggregate phase splits from spell detail for a bowler."""
    if store.bowl_spells.empty:
        return {}

    mask = store.bowl_spells["bowler_id"] == bowler_id
    spells = store.bowl_spells.loc[mask]
    if spells.empty:
        return {}

    phases = {}
    for phase_name, prefix in [
        ("powerplay", "powerplay"),
        ("middle", "middle"),
        ("death", "death"),
    ]:
        balls_col = f"{prefix}_legal_balls"
        runs_col = f"{prefix}_runs"
        wkts_col = f"{prefix}_wickets"
        dots_col = f"{prefix}_dots"
        fours_col = f"{prefix}_fours"
        sixes_col = f"{prefix}_sixes"

        if balls_col not in spells.columns:
            continue

        total_balls = spells[balls_col].sum()
        total_runs = spells[runs_col].sum() if runs_col in spells.columns else None
        total_wkts = spells[wkts_col].sum() if wkts_col in spells.columns else None
        total_dots = spells[dots_col].sum() if dots_col in spells.columns else None
        total_fours = spells[fours_col].sum() if fours_col in spells.columns else None
        total_sixes = spells[sixes_col].sum() if sixes_col in spells.columns else None

        econ_val = None
        if total_balls and total_balls > 0 and total_runs is not None:
            overs = float(total_balls) / 6.0
            econ_val = round(float(total_runs) / overs, 2) if overs > 0 else None

        dot_pct_val = None
        if total_balls and total_balls > 0 and total_dots is not None:
            dot_pct_val = round(float(total_dots) / float(total_balls) * 100, 1)

        phases[phase_name] = PhaseSplit(
            balls=_safe_int(total_balls),
            runs=_safe_int(total_runs),
            wickets=_safe_int(total_wkts),
            dots=_safe_int(total_dots),
            fours=_safe_int(total_fours),
            sixes=_safe_int(total_sixes),
            economy=econ_val,
            dot_pct=dot_pct_val,
        )

    return phases


# ── Route: GET /api/player/{player_id}/roles ─────────────────────


@router.get("/player/{player_id}/roles", response_model=PlayerRoles)
async def get_player_roles(
    player_id: str,
    store: "DataStore" = Depends(_get_store),
) -> PlayerRoles:
    """Return which roles (bat/bowl) a player has and their innings counts.

    This lightweight endpoint lets the frontend decide which profile view
    to show by default (the role with more innings) and whether to render
    a batting/bowling toggle.

    Raises 404 if the player ID is not found in either dataset.
    """
    from data_loader import get_batter_by_id, get_bowler_by_id

    bat_row = get_batter_by_id(store, player_id)
    bowl_row = get_bowler_by_id(store, player_id)

    if bat_row is None and bowl_row is None:
        raise HTTPException(status_code=404, detail=f"Player not found: {player_id}")

    has_batting = bat_row is not None
    has_bowling = bowl_row is not None

    batting_innings = (
        int(_safe_int(_get_val(bat_row, "innings_count")) or 0) if has_batting else 0
    )
    bowling_innings = (
        int(_safe_int(_get_val(bowl_row, "matches")) or 0) if has_bowling else 0
    )

    # Default to whichever role has more innings; tie-break to batting
    if has_batting and has_bowling:
        default_role = "bowl" if bowling_innings > batting_innings else "bat"
    elif has_bowling:
        default_role = "bowl"
    else:
        default_role = "bat"

    # Resolve player name from whichever row is available
    name = ""
    if has_batting:
        name = _safe_str(_get_val(bat_row, "batter"))
    elif has_bowling:
        name = _safe_str(_get_val(bowl_row, "bowler"))

    return PlayerRoles(
        player_id=player_id,
        player_name=name,
        has_batting=has_batting,
        has_bowling=has_bowling,
        batting_innings=batting_innings,
        bowling_innings=bowling_innings,
        default_role=default_role,
    )


# ── Route: GET /api/player/{player_id} ───────────────────────────


@router.get("/player/{player_id}")
async def get_player_profile(
    player_id: str,
    store: "DataStore" = Depends(_get_store),
) -> BatterProfile | BowlerProfile:
    """Return the full profile for a player (batter or bowler).

    The endpoint auto-detects the player's role by looking up the ID
    in both batting and bowling career DataFrames. Batting takes
    precedence if the player appears in both (the bowling profile is
    accessible via `/api/player/{id}?role=bowl` or through the bowling
    endpoints).

    Raises 404 if the player ID is not found in either dataset.
    """
    from data_loader import get_batter_by_id, get_bowler_by_id

    # Try batting first
    bat_row = get_batter_by_id(store, player_id)
    if bat_row is not None:
        profile = _build_batter_profile(bat_row, store)
        # Compute and attach phase splits from innings data
        profile.phases = _compute_batting_phase_splits(store, player_id)
        return profile

    # Try bowling
    bowl_row = get_bowler_by_id(store, player_id)
    if bowl_row is not None:
        profile = _build_bowler_profile(bowl_row, store)
        profile.phases = _compute_bowling_phase_splits(store, player_id)
        return profile

    raise HTTPException(status_code=404, detail=f"Player not found: {player_id}")


# ── Route: GET /api/player/{player_id}/batting ────────────────────


@router.get("/player/{player_id}/batting", response_model=BatterProfile)
async def get_batter_profile_explicit(
    player_id: str,
    store: "DataStore" = Depends(_get_store),
) -> BatterProfile:
    """Return the batting profile for a player. 404 if not a batter."""
    from data_loader import get_batter_by_id

    bat_row = get_batter_by_id(store, player_id)
    if bat_row is None:
        raise HTTPException(status_code=404, detail=f"Batter not found: {player_id}")

    profile = _build_batter_profile(bat_row, store)
    profile.phases = _compute_batting_phase_splits(store, player_id)
    return profile


# ── Route: GET /api/player/{player_id}/bowling ────────────────────


@router.get("/player/{player_id}/bowling", response_model=BowlerProfile)
async def get_bowler_profile_explicit(
    player_id: str,
    store: "DataStore" = Depends(_get_store),
) -> BowlerProfile:
    """Return the bowling profile for a player. 404 if not a bowler."""
    from data_loader import get_bowler_by_id

    bowl_row = get_bowler_by_id(store, player_id)
    if bowl_row is None:
        raise HTTPException(status_code=404, detail=f"Bowler not found: {player_id}")

    profile = _build_bowler_profile(bowl_row, store)
    profile.phases = _compute_bowling_phase_splits(store, player_id)
    return profile


# ── Route: GET /api/player/{player_id}/innings ────────────────────


@router.get("/player/{player_id}/innings")
async def get_player_innings(
    player_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    sort_by: str = Query("date", description="Column to sort by"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Return paginated innings log for a batter.

    Returns a dict with:
    - innings: list of InningsDetail
    - total: total innings count
    - page: current page
    - per_page: page size
    - total_pages: total number of pages
    """
    from data_loader import get_batter_innings

    innings_df, total = get_batter_innings(
        store, player_id, page=page, per_page=per_page, sort_by=sort_by, order=order
    )

    innings_list: list[dict] = []
    for _, row in innings_df.iterrows():
        innings_list.append(
            InningsDetail(
                match_id=_safe_str(_get_val(row, "match_id")),
                date=_safe_str(_get_val(row, "date")),
                opposition=_safe_str(
                    _get_val(row, "bowling_team", _get_val(row, "opposition", ""))
                ),
                runs=_safe_int(_get_val(row, "runs")) or 0,
                balls_faced=_safe_int(_get_val(row, "balls_faced")) or 0,
                sr=_safe_float(_get_val(row, "sr")),
                fours=_safe_int(_get_val(row, "fours")) or 0,
                sixes=_safe_int(_get_val(row, "sixes")) or 0,
                dots=_safe_int(_get_val(row, "dots")) or 0,
                is_out=bool(_get_val(row, "is_out", False)),
                how_out=_safe_str(_get_val(row, "how_out")),
                batting_position=_safe_int(_get_val(row, "batting_position")),
                powerplay_sr=_safe_float(_get_val(row, "powerplay_sr")),
                middle_sr=_safe_float(_get_val(row, "middle_sr")),
                death_sr=_safe_float(_get_val(row, "death_sr")),
                sr_vs_par=_safe_float(_get_val(row, "sr_vs_par")),
                match_par_sr=_safe_float(_get_val(row, "match_par_sr")),
            ).model_dump()
        )

    total_pages = max(1, (total + per_page - 1) // per_page)

    return {
        "innings": innings_list,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── Route: GET /api/player/{player_id}/spells ─────────────────────


@router.get("/player/{player_id}/spells")
async def get_player_spells(
    player_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    sort_by: str = Query("date", description="Column to sort by"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Return paginated spell log for a bowler.

    Returns a dict with:
    - spells: list of SpellDetail
    - total: total spell count
    - page, per_page, total_pages
    """
    from data_loader import get_bowler_spells

    spells_df, total = get_bowler_spells(
        store, player_id, page=page, per_page=per_page, sort_by=sort_by, order=order
    )

    spells_list: list[dict] = []
    for _, row in spells_df.iterrows():
        spells_list.append(
            SpellDetail(
                match_id=_safe_str(_get_val(row, "match_id")),
                date=_safe_str(_get_val(row, "date")),
                opposition=_safe_str(
                    _get_val(row, "batting_team", _get_val(row, "opposition", ""))
                ),
                overs_bowled=_safe_float(_get_val(row, "overs_bowled")),
                runs_conceded=_safe_int(_get_val(row, "runs_conceded")) or 0,
                wickets=_safe_int(_get_val(row, "wickets")) or 0,
                economy=_safe_float(_get_val(row, "economy")),
                dot_pct=_safe_float(_get_val(row, "dot_pct")),
                fours_conceded=_safe_int(_get_val(row, "fours_conceded")) or 0,
                sixes_conceded=_safe_int(_get_val(row, "sixes_conceded")) or 0,
                wides_count=_safe_int(_get_val(row, "wides_count")) or 0,
                noballs_count=_safe_int(_get_val(row, "noballs_count")) or 0,
                powerplay_economy=_safe_float(_get_val(row, "powerplay_economy")),
                middle_economy=_safe_float(_get_val(row, "middle_economy")),
                death_economy=_safe_float(_get_val(row, "death_economy")),
                economy_vs_par=_safe_float(_get_val(row, "economy_vs_par")),
            ).model_dump()
        )

    total_pages = max(1, (total + per_page - 1) // per_page)

    return {
        "spells": spells_list,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── Route: GET /api/player/{player_id}/form ───────────────────────


@router.get("/player/{player_id}/form", response_model=FormResponse)
async def get_player_form(
    player_id: str,
    role: str | None = Query(
        None, description="Force 'bat' or 'bowl'. Omit to auto-detect."
    ),
    store: "DataStore" = Depends(_get_store),
) -> FormResponse:
    """Return the form time-series for a player.

    Accepts an optional ``role`` query parameter (``bat`` or ``bowl``)
    to explicitly request batting or bowling form data.  When omitted
    the endpoint auto-detects by trying batting first.

    Returns an empty series if no form data is available for the
    requested role.
    """
    from data_loader import (
        get_batter_by_id,
        get_batter_form,
        get_bowler_by_id,
        get_bowler_form,
    )

    try_bat = role in (None, "bat")
    try_bowl = role in (None, "bowl")

    # Try batting (if allowed)
    bat_form = get_batter_form(store, player_id) if try_bat else None
    if bat_form is not None and not bat_form.empty:
        bat_row = get_batter_by_id(store, player_id)
        player_name = (
            _safe_str(_get_val(bat_row, "batter")) if bat_row is not None else ""
        )

        series = []
        for _, row in bat_form.iterrows():
            series.append(
                FormPoint(
                    date=_safe_str(_get_val(row, "date")),
                    match_id=_safe_str(_get_val(row, "match_id")),
                    window_innings=_safe_int(_get_val(row, "window_innings")),
                    composite=_safe_float(_get_val(row, "window_composite")),
                    # 0-100 sub-scores
                    score_1=_safe_float(_get_val(row, "window_score_acceleration")),
                    score_2=_safe_float(_get_val(row, "window_score_power")),
                    score_3=_safe_float(_get_val(row, "window_score_control")),
                    score_1_label="acceleration",
                    score_2_label="power",
                    score_3_label="control",
                    # Peak annotation
                    is_peak_window=bool(_get_val(row, "is_peak_window", False)),
                    # Raw stats for tooltip
                    window_avg_runs=_safe_float(_get_val(row, "window_avg_runs")),
                    window_avg_sr=_safe_float(_get_val(row, "window_avg_sr")),
                    window_total_runs=_safe_float(_get_val(row, "window_total_runs")),
                    window_fours=_safe_float(_get_val(row, "window_fours")),
                    window_sixes=_safe_float(_get_val(row, "window_sixes")),
                    # Raw component means
                    window_sr_vs_par=_safe_float(_get_val(row, "window_sr_vs_par")),
                    window_impact=_safe_float(_get_val(row, "window_impact")),
                    window_boundary_pct=_safe_float(
                        _get_val(row, "window_boundary_pct")
                    ),
                    window_six_rate=_safe_float(_get_val(row, "window_six_rate")),
                    window_dot_control=_safe_float(_get_val(row, "window_dot_control")),
                    window_consistency=_safe_float(_get_val(row, "window_consistency")),
                    window_rotation=_safe_float(_get_val(row, "window_rotation")),
                )
            )
        return FormResponse(player_id=player_id, player_name=player_name, series=series)

    # Try bowling (if allowed)
    bowl_form = get_bowler_form(store, player_id) if try_bowl else None
    if bowl_form is not None and not bowl_form.empty:
        bowl_row = get_bowler_by_id(store, player_id)
        player_name = (
            _safe_str(_get_val(bowl_row, "bowler")) if bowl_row is not None else ""
        )

        series = []
        for _, row in bowl_form.iterrows():
            series.append(
                FormPoint(
                    date=_safe_str(_get_val(row, "date")),
                    match_id=_safe_str(_get_val(row, "match_id")),
                    window_innings=_safe_int(_get_val(row, "window_spells")),
                    composite=_safe_float(_get_val(row, "window_composite")),
                    # 0-100 sub-scores
                    score_1=_safe_float(_get_val(row, "window_score_accuracy")),
                    score_2=_safe_float(_get_val(row, "window_score_control")),
                    score_3=_safe_float(_get_val(row, "window_score_threat")),
                    score_1_label="accuracy",
                    score_2_label="control",
                    score_3_label="threat",
                    # Peak annotation
                    is_peak_window=bool(_get_val(row, "is_peak_window", False)),
                    # Raw stats for tooltip
                    window_avg_runs=None,
                    window_avg_sr=None,
                    window_total_runs=None,
                    window_fours=None,
                    window_sixes=None,
                    # Raw component means
                    window_economy=_safe_float(_get_val(row, "window_economy")),
                    window_dot_pct=_safe_float(_get_val(row, "window_dot_pct")),
                    window_wickets_per_spell=_safe_float(
                        _get_val(row, "window_wickets_per_spell")
                    ),
                    window_total_wickets=_safe_float(
                        _get_val(row, "window_total_wickets")
                    ),
                    window_economy_vs_par=_safe_float(
                        _get_val(row, "window_economy_vs_par")
                    ),
                    window_quality_wickets=_safe_float(
                        _get_val(row, "window_quality_wickets")
                    ),
                    window_threat_pressure=_safe_float(
                        _get_val(row, "window_threat_pressure")
                    ),
                )
            )
        return FormResponse(player_id=player_id, player_name=player_name, series=series)

    # No form data found — return empty
    return FormResponse(player_id=player_id, player_name="", series=[])


# ── Route: GET /api/player/{player_id}/matchups ───────────────────


@router.get("/player/{player_id}/matchups", response_model=MatchupExploreResponse)
async def get_player_matchups(
    player_id: str,
    role: str = Query("bat", description="Role: bat or bowl"),
    min_balls: int = Query(6, ge=1, description="Minimum balls faced/bowled"),
    sort_by: str = Query("dominance_index", description="Column to sort by"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    store: "DataStore" = Depends(_get_store),
) -> MatchupExploreResponse:
    """Return all matchups for a player, paginated and sorted.

    For batters (role=bat): shows all bowlers they've faced.
    For bowlers (role=bowl): shows all batters they've bowled to.
    """
    from data_loader import get_matchups_for_batter, get_matchups_for_bowler

    if role == "bowl":
        matchups_df = get_matchups_for_bowler(store, player_id, min_balls=min_balls)
        opponent_id_col = "batter_id"
        opponent_name_col = "batter"
    else:
        matchups_df = get_matchups_for_batter(store, player_id, min_balls=min_balls)
        opponent_id_col = "bowler_id"
        opponent_name_col = "bowler"

    if matchups_df.empty:
        return MatchupExploreResponse(
            matchups=[], total=0, page=page, per_page=per_page
        )

    # Sort
    ascending = order.lower() == "asc"
    if sort_by in matchups_df.columns:
        matchups_df = matchups_df.sort_values(
            sort_by, ascending=ascending, na_position="last"
        )

    total = len(matchups_df)
    start = (page - 1) * per_page
    end = start + per_page
    page_df = matchups_df.iloc[start:end]

    matchup_list: list[MatchupSummary] = []
    for _, mrow in page_df.iterrows():
        matchup_list.append(
            _matchup_row_to_summary(mrow, opponent_id_col, opponent_name_col)
        )

    return MatchupExploreResponse(
        matchups=matchup_list,
        total=total,
        page=page,
        per_page=per_page,
    )


# ── Route: GET /api/player/{player_id}/similar ────────────────────


@router.get("/player/{player_id}/similar", response_model=SimilarityResponse)
async def get_player_similar(
    player_id: str,
    limit: int = Query(10, ge=1, le=50, description="Number of similar players"),
    store: "DataStore" = Depends(_get_store),
) -> SimilarityResponse:
    """Return the most similar players for a given player.

    Auto-detects batting vs bowling. Returns cosine similarity scores
    with the target player's metric scores for comparison.
    """
    from data_loader import (
        get_batter_by_id,
        get_batter_similarities,
        get_bowler_by_id,
        get_bowler_similarities,
    )

    # Try batting first
    bat_row = get_batter_by_id(store, player_id)
    if bat_row is not None:
        target_name = _safe_str(_get_val(bat_row, "batter"))
        sim_df = get_batter_similarities(store, player_id)

        similar: list[SimilarPlayer] = []
        if not sim_df.empty:
            for _, srow in sim_df.head(limit).iterrows():
                comp_id = _safe_str(_get_val(srow, "comp_batter_id"))
                comp_row = get_batter_by_id(store, comp_id)

                similar.append(
                    SimilarPlayer(
                        id=comp_id,
                        name=_safe_str(_get_val(srow, "comp_batter")),
                        country=_safe_str(
                            _get_val(comp_row, "country")
                            if comp_row is not None
                            else None
                        ),
                        similarity_score=_safe_float(_get_val(srow, "similarity")),
                        score_1=_safe_float(
                            _get_val(comp_row, "score_acceleration")
                            if comp_row is not None
                            else None
                        ),
                        score_2=_safe_float(
                            _get_val(comp_row, "score_power")
                            if comp_row is not None
                            else None
                        ),
                        score_3=_safe_float(
                            _get_val(comp_row, "score_control")
                            if comp_row is not None
                            else None
                        ),
                        score_1_label="acceleration",
                        score_2_label="power",
                        score_3_label="control",
                    )
                )

        return SimilarityResponse(
            target_id=player_id,
            target_name=target_name,
            similar=similar,
        )

    # Try bowling
    bowl_row = get_bowler_by_id(store, player_id)
    if bowl_row is not None:
        target_name = _safe_str(_get_val(bowl_row, "bowler"))
        sim_df = get_bowler_similarities(store, player_id)

        similar = []
        if not sim_df.empty:
            for _, srow in sim_df.head(limit).iterrows():
                comp_id = _safe_str(_get_val(srow, "comp_bowler_id"))
                comp_row = get_bowler_by_id(store, comp_id)

                similar.append(
                    SimilarPlayer(
                        id=comp_id,
                        name=_safe_str(_get_val(srow, "comp_bowler")),
                        country=_safe_str(
                            _get_val(comp_row, "country")
                            if comp_row is not None
                            else None
                        ),
                        similarity_score=_safe_float(_get_val(srow, "similarity")),
                        score_1=_safe_float(
                            _get_val(comp_row, "score_accuracy")
                            if comp_row is not None
                            else None
                        ),
                        score_2=_safe_float(
                            _get_val(comp_row, "score_control")
                            if comp_row is not None
                            else None
                        ),
                        score_3=_safe_float(
                            _get_val(comp_row, "score_threat")
                            if comp_row is not None
                            else None
                        ),
                        score_1_label="accuracy",
                        score_2_label="control",
                        score_3_label="threat",
                    )
                )

        return SimilarityResponse(
            target_id=player_id,
            target_name=target_name,
            similar=similar,
        )

    raise HTTPException(status_code=404, detail=f"Player not found: {player_id}")
