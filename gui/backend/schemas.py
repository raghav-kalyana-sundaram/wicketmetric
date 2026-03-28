"""
Pydantic response models for the Cricket Metrics API.

These schemas define the JSON shape returned by every endpoint.
All float fields use `None` as the sentinel for missing/NaN values
(JSON `null`), ensuring clean serialisation without `NaN` strings.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Helpers ───────────────────────────────────────────────────────


def _clean_float(v: Any) -> float | None:
    """Convert NaN/inf to None for JSON safety."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _clean_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _clean_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>", "NaT"):
        return default
    return s


# ── Shared / reusable schemas ────────────────────────────────────


class PlayerSummary(BaseModel):
    """Compact player card used in search results, leaderboards, etc."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    country: str = ""
    role: str = "bat"  # "bat" | "bowl"
    archetype: str = ""
    grade_overall: str = "D"
    innings_count: int = 0
    total_runs: int = 0  # or total_wickets for bowlers
    career_sr: float | None = None  # or career_economy for bowlers
    career_avg: float | None = None
    score_1: float | None = None  # acceleration / accuracy
    score_2: float | None = None  # power / control (bowl)
    score_3: float | None = None  # control (bat) / threat
    score_1_label: str = "acceleration"
    score_2_label: str = "power"
    score_3_label: str = "control"
    is_provisional: bool = True
    overall_score: float | None = None
    metrics: dict[str, float | None] = {}
    last_match_date: str | None = None  # ISO date of last game in this format
    is_active: bool = False  # last_match within format-specific recency window
    # Dual display ratings (spec: simple views use current, expanded use overall)
    rating_current: float | None = None
    rating_overall: float | None = None
    modal_position: int | None = None  # 1–11 batting order (bat only)
    # Squad / franchise from the player's most recent match in this format
    recent_team: str | None = None
    # Bowl: primary phase usage (pp_heavy / middle_heavy / death_heavy) when present
    phase_group: str | None = None
    # Team builder: dual-skill classification (never expose "bits" as a negative label in UI)
    allrounder_class: str | None = None  # "genuine" | "batting" | "bowling" | None


class PhaseSplit(BaseModel):
    """Performance split for a single phase (powerplay/middle/death)."""

    balls: int | None = None
    runs: int | None = None
    sr: float | None = None
    dots: int | None = None
    fours: int | None = None
    sixes: int | None = None
    dot_pct: float | None = None
    boundary_pct: float | None = None
    # Bowling-specific
    wickets: int | None = None
    economy: float | None = None


class ChaseSplit(BaseModel):
    """Setting vs chasing split."""

    innings: int | None = None
    avg: float | None = None
    sr: float | None = None
    composite: float | None = None


class ComponentBreakdown(BaseModel):
    """Sub-component values for a single metric (e.g. acceleration components)."""

    values: dict[str, float | None] = {}


class MatchupSummary(BaseModel):
    """A single batter-vs-bowler matchup record."""

    opponent_id: str = ""
    opponent_name: str = ""
    balls: int = 0
    runs: int = 0
    sr: float | None = None
    dismissals: int = 0
    dot_pct: float | None = None
    boundary_pct: float | None = None
    dominance_index: float | None = None


class MatchupPhase(BaseModel):
    """Phase-level breakdown within a matchup."""

    phase: str = ""
    balls: int = 0
    runs: int = 0
    sr: float | None = None
    dots: int = 0
    dismissals: int = 0
    dominance_index: float | None = None


class SimilarPlayer(BaseModel):
    """A player from the similarity engine."""

    id: str = ""
    name: str = ""
    country: str = ""
    similarity_score: float | None = None
    score_1: float | None = None
    score_2: float | None = None
    score_3: float | None = None
    score_1_label: str = "acceleration"
    score_2_label: str = "power"
    score_3_label: str = "control"


class FormPoint(BaseModel):
    """A single data point in the form time-series.

    The ``composite`` and ``score_*`` fields are **0–100 percentile-ranked**
    values consistent with the career rating system.  The raw ``window_*``
    fields are the underlying component means for tooltip display.
    """

    date: str = ""
    match_id: str = ""
    window_innings: int | None = None
    composite: float | None = None

    # ── 0-100 sub-scores (percentile-ranked) ──
    score_1: float | None = None  # Acceleration (bat) or Accuracy (bowl)
    score_2: float | None = None  # Power (bat) or Control (bowl)
    score_3: float | None = None  # Control (bat) or Threat (bowl)
    score_1_label: str = ""
    score_2_label: str = ""
    score_3_label: str = ""

    # ── Peak annotation ──
    is_peak_window: bool = False

    # ── Raw stats for tooltip / context ──
    window_avg_runs: float | None = None
    window_avg_sr: float | None = None
    window_total_runs: float | None = None
    window_fours: float | None = None
    window_sixes: float | None = None

    # Batting form fields (raw component means)
    window_sr_vs_par: float | None = None
    window_impact: float | None = None
    window_boundary_pct: float | None = None
    window_six_rate: float | None = None
    window_dot_control: float | None = None
    window_consistency: float | None = None
    window_rotation: float | None = None

    # Bowling form fields (raw component means)
    window_economy: float | None = None
    window_dot_pct: float | None = None
    window_wickets_per_spell: float | None = None
    window_total_wickets: float | None = None
    window_economy_vs_par: float | None = None
    window_quality_wickets: float | None = None
    window_threat_pressure: float | None = None


class VenueBaseline(BaseModel):
    """Venue difficulty baseline."""

    venue: str = ""
    matches: int = 0
    avg_par_sr: float | None = None
    boundary_rate: float | None = None
    dot_pct: float | None = None
    difficulty_score: float | None = None  # 0–100 index (higher = harder)


# ── Full profile (player detail page) ────────────────────────────


class BatterProfile(BaseModel):
    """Complete batter profile for the player detail page."""

    model_config = ConfigDict(from_attributes=True)

    # Identity
    id: str
    name: str
    country: str = ""
    archetype: str = ""
    archetypes: list[str] = []
    position_group: str = ""
    modal_position: int | None = None  # 1–11 most common batting slot
    recent_team: str | None = None  # side played for in last game (batting_team)

    # Career stats
    innings_count: int = 0
    total_runs: int = 0
    total_balls: int = 0
    total_fours: int = 0
    total_sixes: int = 0
    total_outs: int = 0
    career_sr: float | None = None
    career_avg: float | None = None

    # Scores (0–100)
    score_acceleration: float | None = None
    score_power: float | None = None
    score_control: float | None = None

    # Grades
    grade_acceleration: str = "D"
    grade_power: str = "D"
    grade_control: str = "D"
    overall_score: float | None = None
    overall_grade: str = "D"
    rating_current: float | None = None
    rating_overall: float | None = None

    # Provisional
    is_provisional: bool = True

    # Peak ratings
    peak_composite_batting: float | None = None
    peak_window_start: str | None = None
    peak_window_end: str | None = None
    peak_window_innings: int | None = None
    peak_window_composite: float | None = None

    # Advanced metrics
    war_batting: float | None = None
    war_batting_rate: float | None = None
    clutch_index: float | None = None
    clutch_sr_delta: float | None = None
    pressure_innings: int | None = None
    chase_master_index: float | None = None
    chase_master_full: float | None = None
    flat_track_index: float | None = None
    venue_adjusted_composite: float | None = None
    selfless_index: float | None = None
    anchor_cost_ratio: float | None = None
    avg_balls_to_par: float | None = None

    # Matchup summary
    avg_dominance: float | None = None
    pct_dominant: float | None = None
    matchup_consistency: float | None = None
    unique_bowlers: int | None = None

    # Phase splits
    phases: dict[str, PhaseSplit] = {}

    # Chase splits
    chase_splits: dict[str, ChaseSplit] = {}

    # Component breakdowns
    components: dict[str, ComponentBreakdown] = {}

    # Top matchups (populated separately)
    top_dominant: list[MatchupSummary] = []
    top_nemeses: list[MatchupSummary] = []

    # Similar players (populated separately)
    similar: list[SimilarPlayer] = []


class BowlerProfile(BaseModel):
    """Complete bowler profile for the player detail page."""

    model_config = ConfigDict(from_attributes=True)

    # Identity
    id: str
    name: str
    country: str = ""
    archetype: str = ""
    archetypes: list[str] = []
    phase_group: str = ""
    recent_team: str | None = None  # side played for in last game (bowling_team)

    # Career stats
    matches: int = 0
    total_overs: float | None = None
    total_wickets: int = 0
    total_runs_conceded: int = 0
    career_economy: float | None = None
    career_sr_bowl: float | None = None
    career_dot_pct: float | None = None
    bowled_lbw_pct: float | None = None

    # Scores (0–100)
    score_accuracy: float | None = None
    score_control: float | None = None
    score_threat: float | None = None

    # Grades
    grade_accuracy: str = "D"
    grade_control: str = "D"
    grade_threat: str = "D"
    overall_score: float | None = None
    overall_grade: str = "D"
    rating_current: float | None = None
    rating_overall: float | None = None

    # Provisional
    is_provisional: bool = True

    # Peak ratings
    peak_composite_bowling: float | None = None
    peak_window_start: str | None = None
    peak_window_end: str | None = None
    peak_window_spells: int | None = None
    peak_window_composite: float | None = None

    # Advanced metrics
    war_bowling: float | None = None
    war_bowling_rate: float | None = None
    clutch_index_bowl: float | None = None
    pressure_spells: int | None = None
    flat_track_index_bowl: float | None = None

    # Matchup summary
    avg_dominance_bowl: float | None = None
    pct_dominant_bowl: float | None = None

    # Phase splits
    phases: dict[str, PhaseSplit] = {}

    # Component breakdowns
    components: dict[str, ComponentBreakdown] = {}

    # Top matchups
    top_bunnies: list[MatchupSummary] = []
    top_dominated_by: list[MatchupSummary] = []

    # Similar bowlers
    similar: list[SimilarPlayer] = []


# ── Innings / Spell detail (paginated) ───────────────────────────


class InningsDetail(BaseModel):
    """A single batting innings record."""

    match_id: str = ""
    date: str = ""
    opposition: str = ""
    runs: int = 0
    balls_faced: int = 0
    sr: float | None = None
    fours: int = 0
    sixes: int = 0
    dots: int = 0
    is_out: bool = False
    how_out: str = ""
    batting_position: int | None = None
    # Phase SR
    powerplay_sr: float | None = None
    middle_sr: float | None = None
    death_sr: float | None = None
    # Context
    sr_vs_par: float | None = None
    match_par_sr: float | None = None


class SpellDetail(BaseModel):
    """A single bowling spell record."""

    match_id: str = ""
    date: str = ""
    opposition: str = ""
    overs_bowled: float | None = None
    runs_conceded: int = 0
    wickets: int = 0
    economy: float | None = None
    dot_pct: float | None = None
    fours_conceded: int = 0
    sixes_conceded: int = 0
    wides_count: int = 0
    noballs_count: int = 0
    # Phase breakdown
    powerplay_economy: float | None = None
    middle_economy: float | None = None
    death_economy: float | None = None
    # Context
    economy_vs_par: float | None = None


# ── Leaderboard response ─────────────────────────────────────────


class LeaderboardResponse(BaseModel):
    """Paginated leaderboard response."""

    players: list[PlayerSummary] = []
    total: int = 0
    page: int = 1
    per_page: int = 25
    total_pages: int = 1


class MatchImpactPerformanceRow(BaseModel):
    """Single player performance in one scorecard match (match-impact model)."""

    match_id: str = ""
    date: str | None = None
    venue: str | None = None
    event_name: str | None = None
    teams: list[str] | None = None
    player_id: str = ""
    player_name: str = ""
    total_impact: float = 0.0
    bat_impact: float = 0.0
    bowl_impact: float = 0.0
    bat_runs: int | None = None
    bat_balls: int | None = None
    bowl_wickets: int | None = None
    bowl_runs_conceded: int | None = None
    bowl_balls: int | None = None


class MatchImpactPerformancesResponse(BaseModel):
    """Paginated list of match impact performances across scorecards."""

    performances: list[MatchImpactPerformanceRow] = []
    total: int = 0
    page: int = 1
    per_page: int = 25
    total_pages: int = 1


class SearchResponse(BaseModel):
    """Search results response."""

    results: list[PlayerSummary] = []
    total: int = 0


# ── Comparison response ──────────────────────────────────────────


class CompareResponse(BaseModel):
    """Side-by-side comparison of 2–4 players."""

    batters: list[BatterProfile] = []
    bowlers: list[BowlerProfile] = []


# ── Matchup responses ────────────────────────────────────────────


class HeadToHeadResponse(BaseModel):
    """Full head-to-head matchup detail."""

    batter_id: str = ""
    batter_name: str = ""
    bowler_id: str = ""
    bowler_name: str = ""
    balls: int = 0
    runs: int = 0
    sr: float | None = None
    dismissals: int = 0
    dots: int = 0
    fours: int = 0
    sixes: int = 0
    dot_pct: float | None = None
    boundary_pct: float | None = None
    dominance_index: float | None = None
    by_phase: list[MatchupPhase] = []


class MatchupExploreResponse(BaseModel):
    """Paginated matchup list for a single player."""

    matchups: list[MatchupSummary] = []
    total: int = 0
    page: int = 1
    per_page: int = 25


# ── Form response ────────────────────────────────────────────────


class FormResponse(BaseModel):
    """Form time-series for a player."""

    player_id: str = ""
    player_name: str = ""
    series: list[FormPoint] = []


class FormBatchPoint(BaseModel):
    """Single point for leaderboard form sparkline (date + composite)."""

    date: str = ""
    composite: float | None = None


class FormBatchItem(BaseModel):
    """Form summary for one player (last 2 years or from last game)."""

    player_id: str = ""
    form_points: list[FormBatchPoint] = []
    last_played: str | None = None  # ISO date of last match
    active: bool = False  # True if last match within format recency (1y T20I / 2y IPL)


class FormBatchResponse(BaseModel):
    """Batch form summary for leaderboard (form tracker)."""

    results: list[FormBatchItem] = []


# ── Similarity response ──────────────────────────────────────────


class SimilarityResponse(BaseModel):
    """Similar players for a given target."""

    target_id: str = ""
    target_name: str = ""
    similar: list[SimilarPlayer] = []


# ── Venue responses ──────────────────────────────────────────────


class VenueListResponse(BaseModel):
    """All venue baselines."""

    venues: list[VenueBaseline] = []


# ── Era responses ────────────────────────────────────────────────


class EraBaseline(BaseModel):
    """Era baseline for a single year."""

    year: int = 0
    par_sr: float | None = None
    boundary_rate: float | None = None
    dot_pct: float | None = None
    multiplier: float | None = None


class EraResponse(BaseModel):
    """Era baselines and multipliers."""

    baselines: list[EraBaseline] = []


# ── Team builder responses ───────────────────────────────────────


class TeamAnalysis(BaseModel):
    """Aggregate team analysis for a team builder selection."""

    player_count: int = 0
    batters: list[PlayerSummary] = []
    bowlers: list[PlayerSummary] = []

    # Aggregate batting scores (averages across selected batters)
    avg_acceleration: float | None = None
    avg_bat_power: float | None = None
    avg_bat_control: float | None = None

    # Aggregate bowling scores
    avg_accuracy: float | None = None
    avg_bowl_control: float | None = None
    avg_threat: float | None = None

    # Team totals
    total_war_batting: float | None = None
    total_war_bowling: float | None = None
    avg_clutch: float | None = None

    # Dimensional weaknesses (percentile vs population) + structural notes
    weaknesses: list[str] = []

    # T20 composition (critical vs advisory); backend source of truth
    composition_critical: list[str] = []
    composition_advisory: list[str] = []
    # Slot/modal mismatches and similar (role fit, not player quality)
    role_fit_warnings: list[str] = []

    # Compact coverage flags for UI summary card
    composition_summary: dict[str, bool | str] = Field(default_factory=dict)

    # Genuine counts (players that actually contribute to aggregates)
    genuine_batter_count: int = 0
    genuine_bowler_count: int = 0
    # Bowlers counted in team bowling averages (Q8 subset)
    bowling_aggregate_count: int = 0
    # Request order (resolved players only); use to rebuild XI slots after auto-fill
    player_ids_ordered: list[str] = Field(default_factory=list)


# ── Meta / health ────────────────────────────────────────────────


class PlayerRoles(BaseModel):
    """Which roles (bat/bowl) a player has, with innings counts for each."""

    player_id: str = ""
    player_name: str = ""
    has_batting: bool = False
    has_bowling: bool = False
    batting_innings: int = 0
    bowling_innings: int = 0
    default_role: str = "bat"  # "bat" | "bowl" — whichever has more innings


class LatestScorecardSummary(BaseModel):
    """Most recent match in the scorecard JSON corpus (by meta.date)."""

    match_id: str = ""
    date: str | None = None
    venue: str | None = None
    teams: list[str] | None = None
    event_name: str | None = None


class T20ITeamTiers(BaseModel):
    """ICC rating–based tiers for T20 international filters (see config ``icc_ranking``)."""

    top_n: int = 15
    main: list[str] = Field(default_factory=list)
    associates: list[str] = Field(default_factory=list)


class MetaResponse(BaseModel):
    """API metadata / health check."""

    status: str = "ok"
    total_batters: int = 0
    total_bowlers: int = 0
    total_matchups: int = 0
    total_venues: int = 0
    countries: list[str] = []
    archetypes: dict[str, list[str]] = {}
    data_through_date: str | None = Field(
        default=None,
        description="Latest last_match_date across career tables (ISO yyyy-mm-dd).",
    )
    latest_scorecard: LatestScorecardSummary | None = Field(
        default=None,
        description="Newest scorecard JSON by meta.date under output_dir/scorecards.",
    )
    t20i_team_tiers: T20ITeamTiers | None = Field(
        default=None,
        description=(
            "Men's/women's T20I only: top ICC-rated sides (main) vs rest of table "
            "(associates). Null for IPL formats."
        ),
    )
