"""
Player router — /api/player/{id} endpoints (DuckDB backend).

Provides:
- GET /api/player/{id}          → Full player profile (batting or bowling)
- GET /api/player/{id}/batting  → Explicit batting profile
- GET /api/player/{id}/bowling  → Explicit bowling profile
- GET /api/player/{id}/innings  → Paginated innings log (batting)
- GET /api/player/{id}/spells   → Paginated spells log (bowling)
- GET /api/player/{id}/form     → Form time-series
- GET /api/player/{id}/season-trend → Calendar-year form aggregates (slope charts)
- GET /api/player/{id}/matchups → Head-to-head matchup list
- GET /api/player/{id}/similar  → Similar players
- GET /api/player/{id}/roles    → Batting/bowling role detection
- GET /api/player/form-batch    → Batch form summaries (leaderboard sparklines)
"""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from db import (
    VALID_FORMATS,
    DEFAULT_FORMAT,
    safe_float,
    safe_int,
    safe_str,
    safe_fmt,
    query_one,
    query_all,
    query_count,
    active_recency_days_for_format,
)
from rating_display import batting_display_ratings, bowling_display_ratings
from schemas import (
    BatterProfile,
    BowlerProfile,
    ChaseSplit,
    ComponentBreakdown,
    FormBatchItem,
    FormBatchPoint,
    FormBatchResponse,
    FormPoint,
    FormResponse,
    InningsDetail,
    PlayerSeasonTrendPoint,
    PlayerSeasonTrendResponse,
    MatchupExploreResponse,
    MatchupSummary,
    PhaseSplit,
    PlayerRoles,
    SimilarityResponse,
    SimilarPlayer,
    SpellDetail,
)

router = APIRouter(prefix="/api", tags=["player"])

_FORM_BATCH_FMT_PATTERN = "^(" + "|".join(VALID_FORMATS) + ")$"


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


def _get_search_index():
    raise HTTPException(
        status_code=503,
        detail="Search index not initialised (dependency override missing).",
    )


# ── Sort-column allowlists ────────────────────────────────────────

_INNINGS_SORT_ALLOW = frozenset({
    "date", "runs", "balls_faced", "sr", "fours", "sixes", "dots",
    "batting_position", "powerplay_sr", "middle_sr", "death_sr",
    "sr_vs_par", "match_par_sr", "is_out", "match_id",
    "runs_scored", "strike_rate",
})

_SPELLS_SORT_ALLOW = frozenset({
    "date", "overs_bowled", "runs_conceded", "wickets", "economy",
    "dot_pct", "fours_conceded", "sixes_conceded", "wides_count",
    "noballs_count", "powerplay_economy", "middle_economy",
    "death_economy", "economy_vs_par", "match_id",
})

_MATCHUP_SORT_ALLOW = frozenset({
    "dominance_index", "balls_faced", "runs_scored", "strike_rate",
    "dismissals", "dot_pct", "boundary_pct",
})


# ── Component key lists ───────────────────────────────────────────

_BAT_ACC_KEYS = [
    "acc_overall_sr_mean", "acc_sr_growth_mean", "acc_death_sr_mean",
    "acc_impact_mean", "acc_runs_above_expected_mean",
]
_BAT_POW_KEYS = [
    "pow_boundary_pct_mean", "pow_six_rate_mean",
    "pow_boundary_rate_vs_par_mean", "pow_peak_phase_sr_mean",
    "pow_finishing_burst_mean", "pow_power_impact_mean",
]
_BAT_CTRL_KEYS = [
    "ctrl_dot_pct_weighted_mean", "ctrl_scoring_consistency_mean",
    "ctrl_rotation_mean", "ctrl_contribution_mean",
    "ctrl_avg_proxy_mean", "ctrl_dismissal_quality_mean",
]

_BOWL_ACC_KEYS = [
    "acc_economy_vs_par_mean", "acc_dot_pct_mean",
    "acc_extras_penalty_mean", "acc_boundary_penalty_mean",
]
_BOWL_CTRL_KEYS = [
    "ctrl_entropy_mean", "ctrl_extras_mean", "ctrl_vs_others_mean",
    "ctrl_extras_pct_mean", "ctrl_economy_vs_par_mean",
    "ctrl_phase_consistency_mean",
]
_BOWL_THREAT_KEYS = [
    "threat_wickets_mean", "threat_quality_wickets_mean",
    "threat_pressure_mean", "threat_dots_mean", "threat_sr_mean",
]


# ── Helpers ───────────────────────────────────────────────────────


def _g(row: dict | None, key: str, default=None):
    """Safe dict .get() that tolerates None rows."""
    if row is None:
        return default
    return row.get(key, default)


def _extract_components(row: dict, keys: list[str], prefix: str) -> ComponentBreakdown:
    vals = {}
    for key in keys:
        label = key.replace(f"{prefix}_", "").replace("_mean", "")
        vals[label] = safe_float(row.get(key))
    return ComponentBreakdown(values=vals)


def _matchup_dict_to_summary(
    row: dict, opponent_id_col: str, opponent_name_col: str
) -> MatchupSummary:
    return MatchupSummary(
        opponent_id=safe_str(row.get(opponent_id_col)),
        opponent_name=safe_str(row.get(opponent_name_col)),
        balls=safe_int(row.get("balls_faced")),
        runs=safe_int(row.get("runs_scored")),
        sr=safe_float(row.get("strike_rate")),
        dismissals=safe_int(row.get("dismissals")),
        dot_pct=safe_float(row.get("dot_pct")),
        boundary_pct=safe_float(row.get("boundary_pct")),
        dominance_index=safe_float(row.get("dominance_index")),
    )


# ── Phase splits from innings/spells ──────────────────────────────


def _compute_batting_phase_splits(
    conn: duckdb.DuckDBPyConnection, fmt: str, batter_id: str
) -> dict[str, PhaseSplit]:
    row = query_one(conn, f"""
        SELECT
            SUM(COALESCE(powerplay_balls, 0))  AS powerplay_balls,
            SUM(COALESCE(powerplay_runs, 0))   AS powerplay_runs,
            SUM(COALESCE(powerplay_dots, 0))   AS powerplay_dots,
            SUM(COALESCE(powerplay_fours, 0))  AS powerplay_fours,
            SUM(COALESCE(powerplay_sixes, 0))  AS powerplay_sixes,
            SUM(COALESCE(middle_balls, 0))     AS middle_balls,
            SUM(COALESCE(middle_runs, 0))      AS middle_runs,
            SUM(COALESCE(middle_dots, 0))      AS middle_dots,
            SUM(COALESCE(middle_fours, 0))     AS middle_fours,
            SUM(COALESCE(middle_sixes, 0))     AS middle_sixes,
            SUM(COALESCE(death_balls, 0))      AS death_balls,
            SUM(COALESCE(death_runs, 0))       AS death_runs,
            SUM(COALESCE(death_dots, 0))       AS death_dots,
            SUM(COALESCE(death_fours, 0))      AS death_fours,
            SUM(COALESCE(death_sixes, 0))      AS death_sixes
        FROM {fmt}.bat_innings WHERE batter_id = ?
    """, [batter_id])
    if row is None:
        return {}

    phases: dict[str, PhaseSplit] = {}
    for phase_name in ("powerplay", "middle", "death"):
        balls = safe_int(row.get(f"{phase_name}_balls"))
        runs = safe_int(row.get(f"{phase_name}_runs"))
        dots = safe_int(row.get(f"{phase_name}_dots"))
        fours = safe_int(row.get(f"{phase_name}_fours"))
        sixes = safe_int(row.get(f"{phase_name}_sixes"))

        if not balls:
            continue

        avg_sr = round(runs / balls * 100, 1) if balls > 0 else None
        dot_pct = round(dots / balls * 100, 1) if balls > 0 else None
        bdry_pct = round((fours + sixes) / balls * 100, 1) if balls > 0 else None

        phases[phase_name] = PhaseSplit(
            balls=balls, runs=runs, sr=avg_sr,
            dots=dots, fours=fours, sixes=sixes,
            dot_pct=dot_pct, boundary_pct=bdry_pct,
        )
    return phases


def _compute_bowling_phase_splits(
    conn: duckdb.DuckDBPyConnection, fmt: str, bowler_id: str
) -> dict[str, PhaseSplit]:
    row = query_one(conn, f"""
        SELECT
            SUM(COALESCE(powerplay_legal_balls, 0))  AS powerplay_legal_balls,
            SUM(COALESCE(powerplay_runs, 0))         AS powerplay_runs,
            SUM(COALESCE(powerplay_wickets, 0))      AS powerplay_wickets,
            SUM(COALESCE(powerplay_dots, 0))         AS powerplay_dots,
            SUM(COALESCE(powerplay_fours, 0))        AS powerplay_fours,
            SUM(COALESCE(powerplay_sixes, 0))        AS powerplay_sixes,
            SUM(COALESCE(middle_legal_balls, 0))     AS middle_legal_balls,
            SUM(COALESCE(middle_runs, 0))            AS middle_runs,
            SUM(COALESCE(middle_wickets, 0))         AS middle_wickets,
            SUM(COALESCE(middle_dots, 0))            AS middle_dots,
            SUM(COALESCE(middle_fours, 0))           AS middle_fours,
            SUM(COALESCE(middle_sixes, 0))           AS middle_sixes,
            SUM(COALESCE(death_legal_balls, 0))      AS death_legal_balls,
            SUM(COALESCE(death_runs, 0))             AS death_runs,
            SUM(COALESCE(death_wickets, 0))          AS death_wickets,
            SUM(COALESCE(death_dots, 0))             AS death_dots,
            SUM(COALESCE(death_fours, 0))            AS death_fours,
            SUM(COALESCE(death_sixes, 0))            AS death_sixes
        FROM {fmt}.bowl_spells WHERE bowler_id = ?
    """, [bowler_id])
    if row is None:
        return {}

    phases: dict[str, PhaseSplit] = {}
    for phase_name in ("powerplay", "middle", "death"):
        balls = safe_int(row.get(f"{phase_name}_legal_balls"))
        runs = safe_int(row.get(f"{phase_name}_runs"))
        wkts = safe_int(row.get(f"{phase_name}_wickets"))
        dots = safe_int(row.get(f"{phase_name}_dots"))
        fours = safe_int(row.get(f"{phase_name}_fours"))
        sixes = safe_int(row.get(f"{phase_name}_sixes"))

        if not balls:
            continue

        overs = balls / 6.0
        econ = round(runs / overs, 2) if overs > 0 else None
        dot_pct = round(dots / balls * 100, 1) if balls > 0 else None

        phases[phase_name] = PhaseSplit(
            balls=balls, runs=runs, wickets=wkts,
            dots=dots, fours=fours, sixes=sixes,
            economy=econ, dot_pct=dot_pct,
        )
    return phases


# ── Chase splits ──────────────────────────────────────────────────


def _build_batting_chase_splits(row: dict) -> dict[str, ChaseSplit]:
    splits = {}
    setting_inn = safe_int(row.get("setting_inn"))
    chasing_inn = safe_int(row.get("chasing_inn"))

    if setting_inn and setting_inn > 0:
        splits["setting"] = ChaseSplit(
            innings=setting_inn,
            avg=safe_float(row.get("setting_avg")),
            sr=safe_float(row.get("setting_sr")),
            composite=safe_float(row.get("bat_first_index")),
        )
    if chasing_inn and chasing_inn > 0:
        splits["chasing"] = ChaseSplit(
            innings=chasing_inn,
            avg=safe_float(row.get("chasing_avg")),
            sr=safe_float(row.get("chasing_sr")),
            composite=safe_float(row.get("chase_master_index")),
        )
    return splits


# ── Profile builders ──────────────────────────────────────────────


def _build_batter_profile(
    row: dict,
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    top_k_matchups: int = 5,
) -> BatterProfile:
    batter_id = safe_str(row.get("batter_id"))

    # ── Top matchups (single query, split by sort) ────────────
    top_dominant: list[MatchupSummary] = []
    top_nemeses: list[MatchupSummary] = []
    matchup_rows = query_all(conn, f"""
        SELECT * FROM {fmt}.matchups
        WHERE batter_id = ? AND balls_faced >= 6
        ORDER BY dominance_index DESC NULLS LAST
    """, [batter_id])
    if matchup_rows:
        for mrow in matchup_rows[:top_k_matchups]:
            top_dominant.append(_matchup_dict_to_summary(mrow, "bowler_id", "bowler"))
        for mrow in matchup_rows[-top_k_matchups:]:
            top_nemeses.append(_matchup_dict_to_summary(mrow, "bowler_id", "bowler"))

    # ── Similar players (batch lookup) ────────────────────────
    sim_rows = query_all(conn, f"""
        SELECT * FROM {fmt}.bat_sim
        WHERE batter_id = ?
        ORDER BY similarity DESC
    """, [batter_id])

    similar: list[SimilarPlayer] = []
    if sim_rows:
        sim_rows = sim_rows[:10]
        comp_ids = [safe_str(s.get("comp_batter_id")) for s in sim_rows]
        placeholders = ", ".join(["?"] * len(comp_ids))
        comp_rows = query_all(conn, f"""
            SELECT * FROM {fmt}.bat_careers
            WHERE batter_id IN ({placeholders})
        """, comp_ids)
        comp_map = {safe_str(c.get("batter_id")): c for c in comp_rows}

        for srow in sim_rows:
            comp_id = safe_str(srow.get("comp_batter_id"))
            comp = comp_map.get(comp_id)
            similar.append(SimilarPlayer(
                id=comp_id,
                name=safe_str(srow.get("comp_batter")),
                country=safe_str(_g(comp, "country")),
                similarity_score=safe_float(srow.get("similarity")),
                score_1=safe_float(_g(comp, "score_acceleration")),
                score_2=safe_float(_g(comp, "score_power")),
                score_3=safe_float(_g(comp, "score_control")),
                score_1_label="acceleration",
                score_2_label="power",
                score_3_label="control",
            ))

    rating_overall, rating_current = batting_display_ratings(row)
    mp = safe_int(row.get("modal_position")) or None
    modal_position = mp if mp is not None and 1 <= mp <= 11 else None

    archetypes_raw = safe_str(row.get("archetypes"))
    archetypes = [a.strip() for a in archetypes_raw.split(",") if a.strip()]
    if not archetypes:
        archetypes = [safe_str(row.get("archetype")) or "Utility Player"]

    return BatterProfile(
        id=batter_id,
        name=safe_str(row.get("batter")),
        country=safe_str(row.get("country")),
        archetype=safe_str(row.get("archetype")),
        archetypes=archetypes,
        position_group=safe_str(row.get("position_group")),
        modal_position=modal_position,
        recent_team=safe_str(row.get("recent_team")).strip() or None,
        innings_count=safe_int(row.get("innings_count")),
        total_runs=safe_int(row.get("total_runs")),
        total_balls=safe_int(row.get("total_balls")),
        total_fours=safe_int(row.get("total_fours")),
        total_sixes=safe_int(row.get("total_sixes")),
        total_outs=safe_int(row.get("total_outs")),
        career_sr=safe_float(row.get("career_sr")),
        career_avg=safe_float(row.get("career_avg")),
        score_acceleration=safe_float(row.get("score_acceleration")),
        score_power=safe_float(row.get("score_power")),
        score_control=safe_float(row.get("score_control")),
        grade_acceleration=safe_str(row.get("grade_acceleration"), "D"),
        grade_power=safe_str(row.get("grade_power"), "D"),
        grade_control=safe_str(row.get("grade_control"), "D"),
        overall_score=safe_float(row.get("overall_score")),
        overall_grade=safe_str(row.get("overall_grade"), "D"),
        rating_current=rating_current,
        rating_overall=rating_overall,
        is_provisional=bool(row.get("is_provisional_bat", True)),
        peak_composite_batting=safe_float(row.get("peak_composite_batting")),
        peak_window_start=safe_str(row.get("peak_window_start")) or None,
        peak_window_end=safe_str(row.get("peak_window_end")) or None,
        peak_window_innings=safe_int(row.get("peak_window_innings")) or None,
        peak_window_composite=safe_float(row.get("peak_window_composite")),
        war_batting=safe_float(row.get("war_batting")),
        war_batting_rate=safe_float(row.get("war_batting_rate")),
        clutch_index=safe_float(row.get("clutch_index")),
        clutch_sr_delta=safe_float(row.get("clutch_sr_delta")),
        pressure_innings=safe_int(row.get("pressure_innings")) or None,
        chase_master_index=safe_float(row.get("chase_master_index")),
        chase_master_full=safe_float(row.get("chase_master_full")),
        flat_track_index=safe_float(row.get("flat_track_index")),
        venue_adjusted_composite=safe_float(row.get("venue_adjusted_composite")),
        selfless_index=safe_float(row.get("selfless_index")),
        anchor_cost_ratio=safe_float(row.get("anchor_cost_ratio")),
        avg_balls_to_par=safe_float(row.get("avg_balls_to_par")),
        avg_dominance=safe_float(row.get("avg_dominance")),
        pct_dominant=safe_float(row.get("pct_dominant")),
        matchup_consistency=safe_float(row.get("matchup_consistency")),
        unique_bowlers=safe_int(row.get("unique_bowlers")) or None,
        phases={},
        chase_splits=_build_batting_chase_splits(row),
        components={
            "acceleration": _extract_components(row, _BAT_ACC_KEYS, "acc"),
            "power": _extract_components(row, _BAT_POW_KEYS, "pow"),
            "control": _extract_components(row, _BAT_CTRL_KEYS, "ctrl"),
        },
        top_dominant=top_dominant,
        top_nemeses=top_nemeses,
        similar=similar,
    )


def _build_bowler_profile(
    row: dict,
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    top_k_matchups: int = 5,
) -> BowlerProfile:
    bowler_id = safe_str(row.get("bowler_id"))

    # ── Top matchups ──────────────────────────────────────────
    top_bunnies: list[MatchupSummary] = []
    top_dominated_by: list[MatchupSummary] = []
    matchup_rows = query_all(conn, f"""
        SELECT * FROM {fmt}.matchups
        WHERE bowler_id = ? AND balls_faced >= 6
        ORDER BY dominance_index ASC NULLS LAST
    """, [bowler_id])
    if matchup_rows:
        for mrow in matchup_rows[:top_k_matchups]:
            top_bunnies.append(_matchup_dict_to_summary(mrow, "batter_id", "batter"))
        rev = list(reversed(matchup_rows))
        for mrow in rev[:top_k_matchups]:
            top_dominated_by.append(
                _matchup_dict_to_summary(mrow, "batter_id", "batter")
            )

    # ── Similar bowlers (batch lookup) ────────────────────────
    sim_rows = query_all(conn, f"""
        SELECT * FROM {fmt}.bowl_sim
        WHERE bowler_id = ?
        ORDER BY similarity DESC
    """, [bowler_id])

    similar: list[SimilarPlayer] = []
    if sim_rows:
        sim_rows = sim_rows[:10]
        comp_ids = [safe_str(s.get("comp_bowler_id")) for s in sim_rows]
        placeholders = ", ".join(["?"] * len(comp_ids))
        comp_rows = query_all(conn, f"""
            SELECT * FROM {fmt}.bowl_careers
            WHERE bowler_id IN ({placeholders})
        """, comp_ids)
        comp_map = {safe_str(c.get("bowler_id")): c for c in comp_rows}

        for srow in sim_rows:
            comp_id = safe_str(srow.get("comp_bowler_id"))
            comp = comp_map.get(comp_id)
            similar.append(SimilarPlayer(
                id=comp_id,
                name=safe_str(srow.get("comp_bowler")),
                country=safe_str(_g(comp, "country")),
                similarity_score=safe_float(srow.get("similarity")),
                score_1=safe_float(_g(comp, "score_accuracy")),
                score_2=safe_float(_g(comp, "score_control")),
                score_3=safe_float(_g(comp, "score_threat")),
                score_1_label="accuracy",
                score_2_label="control",
                score_3_label="threat",
            ))

    rating_overall, rating_current = bowling_display_ratings(row)

    archetypes_raw = safe_str(row.get("archetypes"))
    archetypes = [a.strip() for a in archetypes_raw.split(",") if a.strip()]
    if not archetypes:
        archetypes = [safe_str(row.get("archetype")) or "Utility Player"]

    return BowlerProfile(
        id=bowler_id,
        name=safe_str(row.get("bowler")),
        country=safe_str(row.get("country")),
        archetype=safe_str(row.get("archetype")),
        archetypes=archetypes,
        phase_group=safe_str(row.get("phase_group")),
        recent_team=safe_str(row.get("recent_team")).strip() or None,
        bowling_style=safe_str(row.get("bowling_style")),
        bowling_kind=safe_str(row.get("bowling_kind"), "unknown"),
        espn_player_id=safe_str(row.get("espn_player_id")),
        bowling_style_verified=bool(row.get("bowling_style_verified", False)),
        matches=safe_int(row.get("matches")),
        total_overs=safe_float(row.get("total_overs")),
        total_wickets=safe_int(row.get("total_wickets")),
        total_runs_conceded=safe_int(row.get("total_runs_conceded")),
        career_economy=safe_float(row.get("career_economy")),
        career_sr_bowl=safe_float(row.get("career_sr_bowl")),
        career_dot_pct=safe_float(row.get("career_dot_pct")),
        bowled_lbw_pct=safe_float(row.get("bowled_lbw_pct")),
        score_accuracy=safe_float(row.get("score_accuracy")),
        score_control=safe_float(row.get("score_control")),
        score_threat=safe_float(row.get("score_threat")),
        grade_accuracy=safe_str(row.get("grade_accuracy"), "D"),
        grade_control=safe_str(row.get("grade_control"), "D"),
        grade_threat=safe_str(row.get("grade_threat"), "D"),
        overall_score=safe_float(row.get("overall_score")),
        overall_grade=safe_str(row.get("overall_grade"), "D"),
        rating_current=rating_current,
        rating_overall=rating_overall,
        is_provisional=bool(row.get("is_provisional_bowl", True)),
        peak_composite_bowling=safe_float(row.get("peak_composite_bowling")),
        peak_window_start=safe_str(row.get("peak_window_start")) or None,
        peak_window_end=safe_str(row.get("peak_window_end")) or None,
        peak_window_spells=safe_int(row.get("peak_window_spells")) or None,
        peak_window_composite=safe_float(row.get("peak_window_composite")),
        war_bowling=safe_float(row.get("war_bowling")),
        war_bowling_rate=safe_float(row.get("war_bowling_rate")),
        clutch_index_bowl=safe_float(row.get("clutch_index_bowl")),
        pressure_spells=safe_int(row.get("pressure_spells")) or None,
        flat_track_index_bowl=safe_float(row.get("flat_track_index_bowl")),
        avg_dominance_bowl=safe_float(row.get("avg_dominance_bowl")),
        pct_dominant_bowl=safe_float(row.get("pct_dominant_bowl")),
        phases={},
        components={
            "accuracy": _extract_components(row, _BOWL_ACC_KEYS, "acc"),
            "control": _extract_components(row, _BOWL_CTRL_KEYS, "ctrl"),
            "threat": _extract_components(row, _BOWL_THREAT_KEYS, "threat"),
        },
        top_bunnies=top_bunnies,
        top_dominated_by=top_dominated_by,
        similar=similar,
    )


# ── Form helpers ──────────────────────────────────────────────────


def _batting_form_points(
    conn: duckdb.DuckDBPyConnection, fmt: str, batter_id: str
) -> list[FormPoint]:
    rows = query_all(conn, f"""
        SELECT * FROM {fmt}.bat_form
        WHERE batter_id = ? ORDER BY date
    """, [batter_id])

    if not rows:
        fallback = query_all(conn, f"""
            SELECT date,
                   LEAST(COALESCE(runs_scored, COALESCE(runs, 0)), 50) * 2.0
                       AS window_composite
            FROM {fmt}.bat_innings
            WHERE batter_id = ? AND date IS NOT NULL
            ORDER BY date DESC LIMIT 20
        """, [batter_id])
        if not fallback:
            return []
        return [
            FormPoint(
                date=safe_str(r.get("date")),
                composite=safe_float(r.get("window_composite")),
            )
            for r in reversed(fallback)
        ]

    return [
        FormPoint(
            date=safe_str(r.get("date")),
            match_id=safe_str(r.get("match_id")),
            window_innings=safe_int(r.get("window_innings")) or None,
            composite=safe_float(r.get("window_composite")),
            score_1=safe_float(r.get("window_score_acceleration")),
            score_2=safe_float(r.get("window_score_power")),
            score_3=safe_float(r.get("window_score_control")),
            score_1_label="acceleration",
            score_2_label="power",
            score_3_label="control",
            is_peak_window=bool(r.get("is_peak_window", False)),
            window_avg_runs=safe_float(r.get("window_avg_runs")),
            window_avg_sr=safe_float(r.get("window_avg_sr")),
            window_total_runs=safe_float(r.get("window_total_runs")),
            window_fours=safe_float(r.get("window_fours")),
            window_sixes=safe_float(r.get("window_sixes")),
            window_sr_vs_par=safe_float(r.get("window_sr_vs_par")),
            window_impact=safe_float(r.get("window_impact")),
            window_boundary_pct=safe_float(r.get("window_boundary_pct")),
            window_six_rate=safe_float(r.get("window_six_rate")),
            window_dot_control=safe_float(r.get("window_dot_control")),
            window_consistency=safe_float(r.get("window_consistency")),
            window_rotation=safe_float(r.get("window_rotation")),
        )
        for r in rows
    ]


def _bowling_form_points(
    conn: duckdb.DuckDBPyConnection, fmt: str, bowler_id: str
) -> list[FormPoint]:
    rows = query_all(conn, f"""
        SELECT * FROM {fmt}.bowl_form
        WHERE bowler_id = ? ORDER BY date
    """, [bowler_id])

    if not rows:
        return []

    return [
        FormPoint(
            date=safe_str(r.get("date")),
            match_id=safe_str(r.get("match_id")),
            window_innings=safe_int(r.get("window_spells")) or None,
            composite=safe_float(r.get("window_composite")),
            score_1=safe_float(r.get("window_score_accuracy")),
            score_2=safe_float(r.get("window_score_control")),
            score_3=safe_float(r.get("window_score_threat")),
            score_1_label="accuracy",
            score_2_label="control",
            score_3_label="threat",
            is_peak_window=bool(r.get("is_peak_window", False)),
            window_economy=safe_float(r.get("window_economy")),
            window_dot_pct=safe_float(r.get("window_dot_pct")),
            window_wickets_per_spell=safe_float(r.get("window_wickets_per_spell")),
            window_total_wickets=safe_float(r.get("window_total_wickets")),
            window_economy_vs_par=safe_float(r.get("window_economy_vs_par")),
            window_quality_wickets=safe_float(r.get("window_quality_wickets")),
            window_threat_pressure=safe_float(r.get("window_threat_pressure")),
        )
        for r in rows
    ]


def _batting_season_trend(
    conn: duckdb.DuckDBPyConnection, fmt: str, player_id: str
) -> dict[str, Any]:
    """Aggregate bat_form rows by calendar year for slope / before-after charts."""
    f = safe_fmt(fmt)
    name_row = query_one(
        conn,
        f"SELECT batter AS name FROM {f}.bat_careers WHERE batter_id = ? LIMIT 1",
        [player_id],
    )
    player_name = safe_str(_g(name_row, "name")) if name_row else ""
    try:
        rows = query_all(
            conn,
            f"""
            SELECT
                EXTRACT(YEAR FROM TRY_CAST(date AS DATE))::INTEGER AS yr,
                COUNT(*)::INTEGER AS n,
                AVG(TRY_CAST(window_composite AS DOUBLE)) AS c,
                AVG(TRY_CAST(window_score_acceleration AS DOUBLE)) AS s1,
                AVG(TRY_CAST(window_score_power AS DOUBLE)) AS s2,
                AVG(TRY_CAST(window_score_control AS DOUBLE)) AS s3
            FROM {f}.bat_form
            WHERE batter_id = ? AND date IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) >= 2
            ORDER BY yr
            """,
            [player_id],
        )
    except Exception:
        rows = []
    seasons: list[dict[str, Any]] = []
    for r in rows:
        yr = safe_int(r.get("yr"))
        if yr <= 0:
            continue
        seasons.append(
            {
                "year": yr,
                "sample_points": safe_int(r.get("n")),
                "avg_composite": safe_float(r.get("c")),
                "avg_score_1": safe_float(r.get("s1")),
                "avg_score_2": safe_float(r.get("s2")),
                "avg_score_3": safe_float(r.get("s3")),
            }
        )
    return {
        "player_id": player_id,
        "player_name": player_name,
        "role": "bat",
        "score_1_label": "acceleration",
        "score_2_label": "power",
        "score_3_label": "control",
        "seasons": seasons,
    }


def _bowling_season_trend(
    conn: duckdb.DuckDBPyConnection, fmt: str, player_id: str
) -> dict[str, Any]:
    """Aggregate bowl_form rows by calendar year for slope / before-after charts."""
    f = safe_fmt(fmt)
    name_row = query_one(
        conn,
        f"SELECT bowler AS name FROM {f}.bowl_careers WHERE bowler_id = ? LIMIT 1",
        [player_id],
    )
    player_name = safe_str(_g(name_row, "name")) if name_row else ""
    try:
        rows = query_all(
            conn,
            f"""
            SELECT
                EXTRACT(YEAR FROM TRY_CAST(date AS DATE))::INTEGER AS yr,
                COUNT(*)::INTEGER AS n,
                AVG(TRY_CAST(window_composite AS DOUBLE)) AS c,
                AVG(TRY_CAST(window_score_accuracy AS DOUBLE)) AS s1,
                AVG(TRY_CAST(window_score_control AS DOUBLE)) AS s2,
                AVG(TRY_CAST(window_score_threat AS DOUBLE)) AS s3
            FROM {f}.bowl_form
            WHERE bowler_id = ? AND date IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) >= 2
            ORDER BY yr
            """,
            [player_id],
        )
    except Exception:
        rows = []
    seasons: list[dict[str, Any]] = []
    for r in rows:
        yr = safe_int(r.get("yr"))
        if yr <= 0:
            continue
        seasons.append(
            {
                "year": yr,
                "sample_points": safe_int(r.get("n")),
                "avg_composite": safe_float(r.get("c")),
                "avg_score_1": safe_float(r.get("s1")),
                "avg_score_2": safe_float(r.get("s2")),
                "avg_score_3": safe_float(r.get("s3")),
            }
        )
    return {
        "player_id": player_id,
        "player_name": player_name,
        "role": "bowl",
        "score_1_label": "accuracy",
        "score_2_label": "control",
        "score_3_label": "threat",
        "seasons": seasons,
    }


# ── Form-batch helpers ────────────────────────────────────────────


def _form_batch_summary(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    player_id: str,
    role: str,
) -> tuple[list[tuple[str, float | None]], str | None, bool]:
    """Return (form_points, last_played, active) for a single player+format+role.

    form_points is a list of (date_str, composite) tuples.
    """
    import datetime

    f = safe_fmt(fmt)

    if role == "bowl":
        form_table = f"{f}.bowl_form"
        career_table = f"{f}.bowl_careers"
        id_col = "bowler_id"
        composite_col = "window_composite"
    else:
        form_table = f"{f}.bat_form"
        career_table = f"{f}.bat_careers"
        id_col = "batter_id"
        composite_col = "window_composite"

    # Get last_played from career table
    career = query_one(conn, f"""
        SELECT last_match_date FROM {career_table}
        WHERE {id_col} = ? LIMIT 1
    """, [player_id])
    last_played = None
    if career and career.get("last_match_date") is not None:
        lmd = career["last_match_date"]
        try:
            last_played = lmd.strftime("%Y-%m-%d") if hasattr(lmd, "strftime") else str(lmd)[:10]
        except Exception:
            last_played = str(lmd)[:10]

    # Active check
    active = False
    if last_played:
        try:
            lp_date = datetime.date.fromisoformat(last_played)
            cutoff = datetime.date.today() - datetime.timedelta(
                days=active_recency_days_for_format(fmt)
            )
            active = lp_date >= cutoff
        except Exception:
            pass

    # Form points (last ~2 years: 40 data points is plenty)
    rows = query_all(conn, f"""
        SELECT date, {composite_col} AS composite
        FROM {form_table}
        WHERE {id_col} = ?
        ORDER BY date DESC LIMIT 40
    """, [player_id])
    form_points = [
        (safe_str(r.get("date")), safe_float(r.get("composite")))
        for r in reversed(rows)
    ]

    return form_points, last_played, active


# ── Route: GET /api/player/form-batch ─────────────────────────────


@router.get("/player/form-batch", response_model=FormBatchResponse)
async def get_form_batch(
    ids: str = Query(..., description="Comma-separated player IDs"),
    role: str = Query(..., description="bat or bowl"),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl)",
        pattern=_FORM_BATCH_FMT_PATTERN,
    ),
    db=Depends(_get_store),
) -> FormBatchResponse:
    """Return form summary for multiple players (chart window ~ last 2 years)."""
    conn, _ = db
    fmt = safe_fmt(format) if format in VALID_FORMATS else safe_fmt(DEFAULT_FORMAT)

    player_ids = [x.strip() for x in ids.split(",") if x.strip()]
    if not player_ids:
        return FormBatchResponse(results=[])

    results: list[FormBatchItem] = []
    for pid in player_ids:
        form_points, last_played, active = _form_batch_summary(conn, fmt, pid, role)
        points = [FormBatchPoint(date=d, composite=c) for d, c in form_points]
        results.append(FormBatchItem(
            player_id=pid,
            form_points=points,
            last_played=last_played,
            active=active,
        ))
    return FormBatchResponse(results=results)


# ── Route: GET /api/player/{player_id}/roles ─────────────────────


@router.get("/player/{player_id}/roles", response_model=PlayerRoles)
async def get_player_roles(
    player_id: str,
    db=Depends(_get_store),
) -> PlayerRoles:
    """Return which roles (bat/bowl) a player has and their innings counts."""
    conn, fmt = db

    roles = query_one(conn, f"""
        SELECT
            EXISTS(SELECT 1 FROM {fmt}.bat_careers WHERE batter_id = ?) AS is_bat,
            EXISTS(SELECT 1 FROM {fmt}.bowl_careers WHERE bowler_id = ?) AS is_bowl
    """, [player_id, player_id])

    has_batting = bool(roles and roles.get("is_bat"))
    has_bowling = bool(roles and roles.get("is_bowl"))

    if not has_batting and not has_bowling:
        raise HTTPException(status_code=404, detail=f"Player not found: {player_id}")

    batting_innings = 0
    bowling_innings = 0
    name = ""

    if has_batting:
        bat_row = query_one(conn, f"""
            SELECT batter, innings_count FROM {fmt}.bat_careers
            WHERE batter_id = ? LIMIT 1
        """, [player_id])
        if bat_row:
            name = safe_str(bat_row.get("batter"))
            batting_innings = safe_int(bat_row.get("innings_count"))

    if has_bowling:
        bowl_row = query_one(conn, f"""
            SELECT bowler, matches FROM {fmt}.bowl_careers
            WHERE bowler_id = ? LIMIT 1
        """, [player_id])
        if bowl_row:
            if not name:
                name = safe_str(bowl_row.get("bowler"))
            bowling_innings = safe_int(bowl_row.get("matches"))

    if has_batting and has_bowling:
        default_role = "bowl" if bowling_innings > batting_innings else "bat"
    elif has_bowling:
        default_role = "bowl"
    else:
        default_role = "bat"

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
    db=Depends(_get_store),
) -> BatterProfile | BowlerProfile:
    """Return the full profile for a player (batter or bowler).

    Auto-detects the player's role. Batting takes precedence.
    """
    conn, fmt = db

    bat_row = query_one(conn, f"""
        SELECT * FROM {fmt}.bat_careers WHERE batter_id = ? LIMIT 1
    """, [player_id])
    if bat_row is not None:
        profile = _build_batter_profile(bat_row, conn, fmt)
        profile.phases = _compute_batting_phase_splits(conn, fmt, player_id)
        return profile

    bowl_row = query_one(conn, f"""
        SELECT * FROM {fmt}.bowl_careers WHERE bowler_id = ? LIMIT 1
    """, [player_id])
    if bowl_row is not None:
        profile = _build_bowler_profile(bowl_row, conn, fmt)
        profile.phases = _compute_bowling_phase_splits(conn, fmt, player_id)
        return profile

    raise HTTPException(status_code=404, detail=f"Player not found: {player_id}")


# ── Route: GET /api/player/{player_id}/batting ────────────────────


@router.get("/player/{player_id}/batting", response_model=BatterProfile)
async def get_batter_profile_explicit(
    player_id: str,
    db=Depends(_get_store),
) -> BatterProfile:
    """Return the batting profile for a player. 404 if not a batter."""
    conn, fmt = db

    bat_row = query_one(conn, f"""
        SELECT * FROM {fmt}.bat_careers WHERE batter_id = ? LIMIT 1
    """, [player_id])
    if bat_row is None:
        raise HTTPException(status_code=404, detail=f"Batter not found: {player_id}")

    profile = _build_batter_profile(bat_row, conn, fmt)
    profile.phases = _compute_batting_phase_splits(conn, fmt, player_id)
    return profile


# ── Route: GET /api/player/{player_id}/bowling ────────────────────


@router.get("/player/{player_id}/bowling", response_model=BowlerProfile)
async def get_bowler_profile_explicit(
    player_id: str,
    db=Depends(_get_store),
) -> BowlerProfile:
    """Return the bowling profile for a player. 404 if not a bowler."""
    conn, fmt = db

    bowl_row = query_one(conn, f"""
        SELECT * FROM {fmt}.bowl_careers WHERE bowler_id = ? LIMIT 1
    """, [player_id])
    if bowl_row is None:
        raise HTTPException(status_code=404, detail=f"Bowler not found: {player_id}")

    profile = _build_bowler_profile(bowl_row, conn, fmt)
    profile.phases = _compute_bowling_phase_splits(conn, fmt, player_id)
    return profile


# ── Route: GET /api/player/{player_id}/innings ────────────────────


@router.get("/player/{player_id}/innings")
async def get_player_innings(
    player_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    sort_by: str = Query("date", description="Column to sort by"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    db=Depends(_get_store),
) -> dict:
    """Return paginated innings log for a batter."""
    conn, fmt = db

    sort_col = sort_by if sort_by in _INNINGS_SORT_ALLOW else "date"
    direction = "ASC" if order.lower() == "asc" else "DESC"
    offset = (page - 1) * per_page

    total = query_count(conn, f"""
        SELECT COUNT(*) FROM {fmt}.bat_innings WHERE batter_id = ?
    """, [player_id])

    rows = query_all(conn, f"""
        SELECT * FROM {fmt}.bat_innings
        WHERE batter_id = ?
        ORDER BY {sort_col} {direction} NULLS LAST
        LIMIT ? OFFSET ?
    """, [player_id, per_page, offset])

    innings_list: list[dict] = []
    for r in rows:
        innings_list.append(InningsDetail(
            match_id=safe_str(r.get("match_id")),
            date=safe_str(r.get("date")),
            opposition=safe_str(r.get("bowling_team", r.get("opposition", ""))),
            runs=safe_int(r.get("runs", r.get("runs_scored", 0))),
            balls_faced=safe_int(r.get("balls_faced")),
            sr=safe_float(r.get("sr", r.get("strike_rate"))),
            fours=safe_int(r.get("fours")),
            sixes=safe_int(r.get("sixes")),
            dots=safe_int(r.get("dots")),
            is_out=bool(r.get("is_out", False)),
            how_out=safe_str(r.get("how_out")),
            batting_position=safe_int(r.get("batting_position")) or None,
            powerplay_sr=safe_float(r.get("powerplay_sr")),
            middle_sr=safe_float(r.get("middle_sr")),
            death_sr=safe_float(r.get("death_sr")),
            sr_vs_par=safe_float(r.get("sr_vs_par")),
            match_par_sr=safe_float(r.get("match_par_sr")),
        ).model_dump())

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
    db=Depends(_get_store),
) -> dict:
    """Return paginated spell log for a bowler."""
    conn, fmt = db

    sort_col = sort_by if sort_by in _SPELLS_SORT_ALLOW else "date"
    direction = "ASC" if order.lower() == "asc" else "DESC"
    offset = (page - 1) * per_page

    total = query_count(conn, f"""
        SELECT COUNT(*) FROM {fmt}.bowl_spells WHERE bowler_id = ?
    """, [player_id])

    rows = query_all(conn, f"""
        SELECT * FROM {fmt}.bowl_spells
        WHERE bowler_id = ?
        ORDER BY {sort_col} {direction} NULLS LAST
        LIMIT ? OFFSET ?
    """, [player_id, per_page, offset])

    spells_list: list[dict] = []
    for r in rows:
        spells_list.append(SpellDetail(
            match_id=safe_str(r.get("match_id")),
            date=safe_str(r.get("date")),
            opposition=safe_str(r.get("batting_team", r.get("opposition", ""))),
            overs_bowled=safe_float(r.get("overs_bowled")),
            runs_conceded=safe_int(r.get("runs_conceded")),
            wickets=safe_int(r.get("wickets")),
            economy=safe_float(r.get("economy")),
            dot_pct=safe_float(r.get("dot_pct")),
            fours_conceded=safe_int(r.get("fours_conceded")),
            sixes_conceded=safe_int(r.get("sixes_conceded")),
            wides_count=safe_int(r.get("wides_count")),
            noballs_count=safe_int(r.get("noballs_count")),
            powerplay_economy=safe_float(r.get("powerplay_economy")),
            middle_economy=safe_float(r.get("middle_economy")),
            death_economy=safe_float(r.get("death_economy")),
            economy_vs_par=safe_float(r.get("economy_vs_par")),
        ).model_dump())

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
    db=Depends(_get_store),
) -> FormResponse:
    """Return the form time-series for a player."""
    conn, fmt = db

    try_bat = role in (None, "bat")
    try_bowl = role in (None, "bowl")

    if try_bat:
        series = _batting_form_points(conn, fmt, player_id)
        if series:
            bat_row = query_one(conn, f"""
                SELECT batter FROM {fmt}.bat_careers
                WHERE batter_id = ? LIMIT 1
            """, [player_id])
            player_name = safe_str(_g(bat_row, "batter"))
            return FormResponse(
                player_id=player_id, player_name=player_name, series=series
            )

    if try_bowl:
        series = _bowling_form_points(conn, fmt, player_id)
        if series:
            bowl_row = query_one(conn, f"""
                SELECT bowler FROM {fmt}.bowl_careers
                WHERE bowler_id = ? LIMIT 1
            """, [player_id])
            player_name = safe_str(_g(bowl_row, "bowler"))
            return FormResponse(
                player_id=player_id, player_name=player_name, series=series
            )

    return FormResponse(player_id=player_id, player_name="", series=[])


@router.get(
    "/player/{player_id}/season-trend",
    response_model=PlayerSeasonTrendResponse,
)
async def get_player_season_trend(
    player_id: str,
    role: str = Query(
        ...,
        pattern="^(bat|bowl)$",
        description="bat or bowl — which form table to aggregate",
    ),
    db=Depends(_get_store),
) -> PlayerSeasonTrendResponse:
    """Calendar-year means of rolling form scores (for season-to-season slope charts)."""
    conn, fmt = db
    if role == "bat":
        raw = _batting_season_trend(conn, fmt, player_id)
    else:
        raw = _bowling_season_trend(conn, fmt, player_id)
    return PlayerSeasonTrendResponse.model_validate(raw)


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
    db=Depends(_get_store),
) -> MatchupExploreResponse:
    """Return all matchups for a player, paginated and sorted."""
    conn, fmt = db

    sort_col = sort_by if sort_by in _MATCHUP_SORT_ALLOW else "dominance_index"
    direction = "ASC" if order.lower() == "asc" else "DESC"
    offset = (page - 1) * per_page

    if role == "bowl":
        id_col = "bowler_id"
        opponent_id_col = "batter_id"
        opponent_name_col = "batter"
    else:
        id_col = "batter_id"
        opponent_id_col = "bowler_id"
        opponent_name_col = "bowler"

    total = query_count(conn, f"""
        SELECT COUNT(*) FROM {fmt}.matchups
        WHERE {id_col} = ? AND balls_faced >= ?
    """, [player_id, min_balls])

    if total == 0:
        return MatchupExploreResponse(
            matchups=[], total=0, page=page, per_page=per_page
        )

    rows = query_all(conn, f"""
        SELECT * FROM {fmt}.matchups
        WHERE {id_col} = ? AND balls_faced >= ?
        ORDER BY {sort_col} {direction} NULLS LAST
        LIMIT ? OFFSET ?
    """, [player_id, min_balls, per_page, offset])

    matchup_list = [
        _matchup_dict_to_summary(r, opponent_id_col, opponent_name_col)
        for r in rows
    ]

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
    db=Depends(_get_store),
) -> SimilarityResponse:
    """Return the most similar players for a given player.

    Auto-detects batting vs bowling. Returns cosine similarity scores.
    """
    conn, fmt = db

    # Try batting first
    bat_row = query_one(conn, f"""
        SELECT * FROM {fmt}.bat_careers WHERE batter_id = ? LIMIT 1
    """, [player_id])
    if bat_row is not None:
        target_name = safe_str(bat_row.get("batter"))
        sim_rows = query_all(conn, f"""
            SELECT * FROM {fmt}.bat_sim
            WHERE batter_id = ?
            ORDER BY similarity DESC
            LIMIT ?
        """, [player_id, limit])

        similar: list[SimilarPlayer] = []
        if sim_rows:
            comp_ids = [safe_str(s.get("comp_batter_id")) for s in sim_rows]
            placeholders = ", ".join(["?"] * len(comp_ids))
            comp_rows = query_all(conn, f"""
                SELECT * FROM {fmt}.bat_careers
                WHERE batter_id IN ({placeholders})
            """, comp_ids)
            comp_map = {safe_str(c.get("batter_id")): c for c in comp_rows}

            for srow in sim_rows:
                comp_id = safe_str(srow.get("comp_batter_id"))
                comp = comp_map.get(comp_id)
                similar.append(SimilarPlayer(
                    id=comp_id,
                    name=safe_str(srow.get("comp_batter")),
                    country=safe_str(_g(comp, "country")),
                    similarity_score=safe_float(srow.get("similarity")),
                    score_1=safe_float(_g(comp, "score_acceleration")),
                    score_2=safe_float(_g(comp, "score_power")),
                    score_3=safe_float(_g(comp, "score_control")),
                    score_1_label="acceleration",
                    score_2_label="power",
                    score_3_label="control",
                ))

        return SimilarityResponse(
            target_id=player_id,
            target_name=target_name,
            similar=similar,
        )

    # Try bowling
    bowl_row = query_one(conn, f"""
        SELECT * FROM {fmt}.bowl_careers WHERE bowler_id = ? LIMIT 1
    """, [player_id])
    if bowl_row is not None:
        target_name = safe_str(bowl_row.get("bowler"))
        sim_rows = query_all(conn, f"""
            SELECT * FROM {fmt}.bowl_sim
            WHERE bowler_id = ?
            ORDER BY similarity DESC
            LIMIT ?
        """, [player_id, limit])

        similar = []
        if sim_rows:
            comp_ids = [safe_str(s.get("comp_bowler_id")) for s in sim_rows]
            placeholders = ", ".join(["?"] * len(comp_ids))
            comp_rows = query_all(conn, f"""
                SELECT * FROM {fmt}.bowl_careers
                WHERE bowler_id IN ({placeholders})
            """, comp_ids)
            comp_map = {safe_str(c.get("bowler_id")): c for c in comp_rows}

            for srow in sim_rows:
                comp_id = safe_str(srow.get("comp_bowler_id"))
                comp = comp_map.get(comp_id)
                similar.append(SimilarPlayer(
                    id=comp_id,
                    name=safe_str(srow.get("comp_bowler")),
                    country=safe_str(_g(comp, "country")),
                    similarity_score=safe_float(srow.get("similarity")),
                    score_1=safe_float(_g(comp, "score_accuracy")),
                    score_2=safe_float(_g(comp, "score_control")),
                    score_3=safe_float(_g(comp, "score_threat")),
                    score_1_label="accuracy",
                    score_2_label="control",
                    score_3_label="threat",
                ))

        return SimilarityResponse(
            target_id=player_id,
            target_name=target_name,
            similar=similar,
        )

    raise HTTPException(status_code=404, detail=f"Player not found: {player_id}")
