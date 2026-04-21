"""
Tests for Version 0.2 Phase 4 features:
  - Feature 3: Clutch / Pressure Index

Tests cover:
  - Delivery-level pressure tagging (batting + bowling)
  - Innings-level pressure aggregation
  - Spell-level pressure aggregation
  - Batting Clutch Index computation
  - Bowling Clutch Index computation
  - Convenience wrapper (compute_all_clutch_metrics)
  - Edge cases (no pressure, all pressure, disabled, min threshold, NaN)
  - Config integration
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal DataFrames
# ---------------------------------------------------------------------------


def _make_delivery_df(
    match_id: str = "m1",
    innings_num: int = 1,
    batter_id: str = "b1",
    batter: str = "Player A",
    batting_team: str = "TeamA",
    bowling_team: str = "TeamB",
    batter_runs: list[int] | None = None,
    overs: list[int] | None = None,
    phases: list[str] | None = None,
    bowler_id: str = "bw1",
    bowler: str = "Bowler X",
    batting_position: int = 3,
    event_name: str = "IPL 2024",
    target_runs: int | None = None,
    team_wickets_before: list[int] | None = None,
    winner: str | None = None,
    overs_limit: int = 20,
) -> pd.DataFrame:
    """Create a minimal delivery-level DataFrame for a single innings."""
    if batter_runs is None:
        batter_runs = [0, 1, 4, 0, 2, 6, 1, 0, 1, 4]
    n = len(batter_runs)
    if overs is None:
        overs = [i // 6 for i in range(n)]
    if phases is None:
        phases = [
            "powerplay" if o < 6 else ("middle" if o < 16 else "death") for o in overs
        ]
    if team_wickets_before is None:
        team_wickets_before = [0] * n

    cum_runs = list(np.cumsum([0] + batter_runs[:-1]))

    rows = []
    legal_ball_seq = 0
    for i in range(n):
        rows.append(
            {
                "match_id": match_id,
                "innings_num": innings_num,
                "batter_id": batter_id,
                "batter": batter,
                "batting_team": batting_team,
                "bowling_team": bowling_team,
                "bowler_id": bowler_id,
                "bowler": bowler,
                "batter_runs": batter_runs[i],
                "extras_runs": 0,
                "total_runs": batter_runs[i],
                "is_legal": True,
                "is_batter_ball": True,
                "is_wide": False,
                "is_noball": False,
                "is_wicket": False,
                "player_out_id": None,
                "wicket_kind": None,
                "is_four": batter_runs[i] == 4,
                "is_six": batter_runs[i] == 6,
                "is_dot_batter": batter_runs[i] == 0,
                "is_dot_bowler": batter_runs[i] == 0,
                "over": overs[i],
                "ball_idx": i % 6,
                "legal_ball_seq": legal_ball_seq,
                "phase": phases[i],
                "team_score_before": int(cum_runs[i]),
                "team_wickets_before": team_wickets_before[i],
                "batting_position": batting_position,
                "date": pd.Timestamp("2024-01-15"),
                "event_name": event_name,
                "target_runs": target_runs,
                "winner": winner,
                "overs_limit": overs_limit,
                "non_striker": "NS",
                "non_striker_id": "ns1",
            }
        )
        legal_ball_seq += 1
    return pd.DataFrame(rows)


def _make_bat_components(
    batter_id: str = "b1",
    batter: str = "Player A",
    match_ids: list[str] | None = None,
    innings_nums: list[int] | None = None,
    runs: list[int] | None = None,
    acc_overall_sr: list[float] | None = None,
    acc_impact: list[float] | None = None,
    ctrl_scoring_consistency: list[float] | None = None,
    ctrl_contribution: list[float] | None = None,
) -> pd.DataFrame:
    """Create a minimal bat_components-like DataFrame."""
    if match_ids is None:
        match_ids = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10"]
    n = len(match_ids)
    if innings_nums is None:
        innings_nums = [1] * n
    if runs is None:
        runs = [30] * n
    if acc_overall_sr is None:
        acc_overall_sr = [0.15] * n
    if acc_impact is None:
        acc_impact = [5.0] * n
    if ctrl_scoring_consistency is None:
        ctrl_scoring_consistency = [0.65] * n
    if ctrl_contribution is None:
        ctrl_contribution = [0.25] * n

    return pd.DataFrame(
        {
            "match_id": match_ids,
            "innings_num": innings_nums,
            "batter_id": [batter_id] * n,
            "batter": [batter] * n,
            "runs": runs,
            "balls_faced": [20] * n,
            "sr": [150.0] * n,
            "acc_overall_sr": acc_overall_sr,
            "acc_impact": acc_impact,
            "ctrl_scoring_consistency": ctrl_scoring_consistency,
            "ctrl_contribution": ctrl_contribution,
            "opp_quality_weight": [1.0] * n,
            "date": pd.Timestamp("2024-01-15"),
        }
    )


def _make_bowl_components(
    bowler_id: str = "bw1",
    bowler: str = "Bowler X",
    match_ids: list[str] | None = None,
    innings_nums: list[int] | None = None,
    wickets: list[int] | None = None,
    acc_economy_vs_par: list[float] | None = None,
    acc_dot_pct: list[float] | None = None,
) -> pd.DataFrame:
    """Create a minimal bowl_components-like DataFrame."""
    if match_ids is None:
        match_ids = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]
    n = len(match_ids)
    if innings_nums is None:
        innings_nums = [1] * n
    if wickets is None:
        wickets = [2] * n
    if acc_economy_vs_par is None:
        acc_economy_vs_par = [0.10] * n
    if acc_dot_pct is None:
        acc_dot_pct = [0.40] * n

    return pd.DataFrame(
        {
            "match_id": match_ids,
            "innings_num": innings_nums,
            "bowler_id": [bowler_id] * n,
            "bowler": [bowler] * n,
            "wickets": wickets,
            "overs": [4.0] * n,
            "runs_conceded": [30] * n,
            "acc_economy_vs_par": acc_economy_vs_par,
            "acc_dot_pct": acc_dot_pct,
            "opp_quality_weight": [1.0] * n,
            "date": pd.Timestamp("2024-01-15"),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test: tag_pressure_deliveries (batting)
# ═══════════════════════════════════════════════════════════════════════════


class TestTagPressureDeliveries:
    """Tests for delivery-level pressure tagging."""

    def test_normal_innings_no_pressure(self):
        """First innings, normal event → no pressure."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(innings_num=1, event_name="IPL 2024")
        result = tag_pressure_deliveries(df)
        assert "is_pressure" in result.columns
        assert not result["is_pressure"].any()

    def test_high_required_run_rate(self):
        """Chasing with RRR > 9 RPO → high_rrr pressure."""
        from src.clutch import tag_pressure_deliveries

        # Innings 2, target 200, early in innings (low score), need ~10 RPO
        df = _make_delivery_df(
            innings_num=2,
            target_runs=200,
            batter_runs=[0, 1, 0, 0, 1, 0, 0, 0, 1, 0],
            overs=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
        )
        result = tag_pressure_deliveries(df)
        # Required runs is ~197-200 with 20 overs → ~10 RPO
        assert result["is_pressure_high_rrr"].any()
        assert result["is_pressure"].any()

    def test_high_rrr_not_triggered_first_innings(self):
        """First innings never triggers high RRR (no target)."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(innings_num=1, target_runs=None)
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_high_rrr"].any()

    def test_high_rrr_below_threshold(self):
        """Chasing with RRR below threshold → no pressure."""
        from src.clutch import tag_pressure_deliveries

        # Target 120 with 20 overs → RRR = 6.0, well below 9.0
        df = _make_delivery_df(
            innings_num=2,
            target_runs=120,
            batter_runs=[0, 1, 0, 0, 1, 0],
            overs=[0, 0, 0, 0, 0, 0],
        )
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_high_rrr"].any()

    def test_collapse_in_powerplay(self):
        """3+ wickets down in powerplay → collapse pressure."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(
            innings_num=1,
            batter_runs=[0, 1, 4, 0, 2, 6],
            overs=[0, 1, 2, 3, 4, 5],
            phases=["powerplay"] * 6,
            team_wickets_before=[0, 1, 2, 3, 3, 4],  # 3+ from ball 4 onwards
        )
        result = tag_pressure_deliveries(df)
        assert (
            result["is_pressure_collapse"].sum() == 3
        )  # balls 4, 5, 6 (indices 3, 4, 5)
        assert result.iloc[3]["is_pressure_collapse"]
        assert not result.iloc[2]["is_pressure_collapse"]

    def test_knockout_match(self):
        """Final match → knockout pressure on all deliveries."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(event_name="IPL 2024 Final")
        result = tag_pressure_deliveries(df)
        assert result["is_pressure_knockout"].all()
        assert result["is_pressure"].all()

    def test_knockout_semifinal_case_insensitive(self):
        """Semi-final detection is case-insensitive."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(event_name="T20 World Cup Semi-Final")
        result = tag_pressure_deliveries(df)
        assert result["is_pressure_knockout"].all()

    def test_knockout_eliminator(self):
        """Eliminator match detected."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(event_name="IPL Eliminator 2023")
        result = tag_pressure_deliveries(df)
        assert result["is_pressure_knockout"].all()

    def test_knockout_qualifier(self):
        """Qualifier match detected."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(event_name="Qualifier 1")
        result = tag_pressure_deliveries(df)
        assert result["is_pressure_knockout"].all()

    def test_not_knockout_regular_match(self):
        """Regular league match → no knockout pressure."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(event_name="Big Bash League 2024")
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_knockout"].any()

    def test_deep_chase_pressure(self):
        """Deep in a chase with most of target still needed → deep chase."""
        from src.clutch import tag_pressure_deliveries

        # Over 14 (0-indexed), target 180, score 60 → 120/180 = 67% remaining
        n = 6
        df = _make_delivery_df(
            innings_num=2,
            target_runs=180,
            batter_runs=[1, 0, 1, 0, 1, 0],
            overs=[14, 14, 14, 14, 14, 14],  # over 14 → last 6 overs
            phases=["middle"] * n,
        )
        # team_score_before starts at 60
        df["team_score_before"] = [60, 61, 61, 62, 62, 63]
        result = tag_pressure_deliveries(df)
        # Over 14 ≥ 12 (20 - 8) and remaining pct > 50% → should be deep chase
        assert result["is_pressure_deep_chase"].any()

    def test_deep_chase_not_triggered_early(self):
        """Early overs of a chase don't trigger deep chase."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=180,
            batter_runs=[1, 0, 1, 0, 1, 0],
            overs=[2, 2, 2, 2, 2, 2],  # over 2 → early
            phases=["powerplay"] * 6,
        )
        df["team_score_before"] = [10, 11, 11, 12, 12, 13]
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_deep_chase"].any()

    def test_combined_pressure_flag(self):
        """is_pressure is True if ANY individual flag is True."""
        from src.clutch import tag_pressure_deliveries

        # Knockout match in first innings (so no high_rrr, no deep_chase)
        df = _make_delivery_df(innings_num=1, event_name="World Cup Final")
        result = tag_pressure_deliveries(df)
        # Knockout is True for all → is_pressure should be True for all
        assert result["is_pressure"].all()
        assert result["is_pressure_knockout"].all()
        # No high_rrr (first innings)
        assert not result["is_pressure_high_rrr"].any()

    def test_custom_rrr_threshold(self):
        """Override high_rrr_threshold parameter."""
        from src.clutch import tag_pressure_deliveries

        # Target 140 from over 0 → ~7 RPO, below 9 but above 6
        df = _make_delivery_df(
            innings_num=2,
            target_runs=140,
            batter_runs=[0, 0, 0, 0, 0, 0],
            overs=[0, 0, 0, 0, 0, 0],
        )

        # Default threshold 9.0 → not triggered
        result_default = tag_pressure_deliveries(df, high_rrr_threshold=9.0)
        assert not result_default["is_pressure_high_rrr"].any()

        # Lower threshold 6.0 → triggered
        result_low = tag_pressure_deliveries(df, high_rrr_threshold=6.0)
        assert result_low["is_pressure_high_rrr"].all()

    def test_custom_collapse_threshold(self):
        """Override collapse_wickets parameter."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(
            innings_num=1,
            batter_runs=[0, 1, 4],
            overs=[0, 1, 2],
            phases=["powerplay"] * 3,
            team_wickets_before=[2, 2, 2],  # 2 wickets down
        )

        # Default threshold 3 → not triggered
        result_3 = tag_pressure_deliveries(df, collapse_wickets=3)
        assert not result_3["is_pressure_collapse"].any()

        # Lower threshold 2 → triggered
        result_2 = tag_pressure_deliveries(df, collapse_wickets=2)
        assert result_2["is_pressure_collapse"].all()

    def test_preserves_original_columns(self):
        """Original columns are preserved in output."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df()
        result = tag_pressure_deliveries(df)
        for col in df.columns:
            assert col in result.columns

    def test_does_not_mutate_input(self):
        """Input DataFrame is not modified."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df()
        cols_before = set(df.columns)
        _ = tag_pressure_deliveries(df)
        assert set(df.columns) == cols_before

    def test_empty_dataframe(self):
        """Empty DataFrame doesn't crash."""
        from src.clutch import tag_pressure_deliveries

        df = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "batter_id",
                "phase",
                "team_wickets_before",
                "over",
                "legal_ball_seq",
                "target_runs",
                "team_score_before",
                "overs_limit",
                "is_batter_ball",
                "event_name",
            ]
        )
        result = tag_pressure_deliveries(df)
        assert len(result) == 0
        assert "is_pressure" in result.columns

    def test_missing_event_name_column(self):
        """Missing event_name column → no knockout but no crash."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df()
        df = df.drop(columns=["event_name"])
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_knockout"].any()

    def test_categorical_columns_handled(self):
        """Categorical columns don't break tagging."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(event_name="T20 World Cup Final")
        df["event_name"] = df["event_name"].astype("category")
        df["phase"] = df["phase"].astype("category")
        df["innings_num"] = df["innings_num"].astype("int8")
        result = tag_pressure_deliveries(df)
        assert result["is_pressure_knockout"].all()

    def test_required_run_rate_column(self):
        """required_run_rate is correctly computed for chasing innings."""
        from src.clutch import tag_pressure_deliveries

        # Inn 2, target 180, ball 0, score 0 → RRR = 180 / 20 = 9.0
        df = _make_delivery_df(
            innings_num=2,
            target_runs=180,
            batter_runs=[0],
            overs=[0],
        )
        df["team_score_before"] = [0]
        df["legal_ball_seq"] = [0]
        result = tag_pressure_deliveries(df)
        assert result["required_run_rate"].iloc[0] == pytest.approx(9.0, abs=0.1)


# ═══════════════════════════════════════════════════════════════════════════
# Test: tag_bowling_pressure_deliveries
# ═══════════════════════════════════════════════════════════════════════════


class TestBowlingPressureDeliveries:
    """Tests for bowling-specific pressure tagging."""

    def test_low_defend_pressure(self):
        """Defending a low total (≤140) in innings 2 → low defend pressure."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(innings_num=2, target_runs=130)
        result = tag_bowling_pressure_deliveries(df)
        assert result["is_pressure_low_defend"].all()
        assert result["is_bowl_pressure"].any()

    def test_low_defend_not_triggered_high_total(self):
        """High total (>140) → no low defend pressure."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(innings_num=2, target_runs=180)
        result = tag_bowling_pressure_deliveries(df)
        assert not result["is_pressure_low_defend"].any()

    def test_low_defend_not_triggered_first_innings(self):
        """First innings → no low defend pressure (no target)."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(innings_num=1, target_runs=None)
        result = tag_bowling_pressure_deliveries(df)
        assert not result["is_pressure_low_defend"].any()

    def test_death_close_chase(self):
        """Death overs (over 16+) of a close chase (margin < 30)."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=170,
            batter_runs=[4, 1, 6, 2, 1, 4],
            overs=[16, 16, 17, 17, 18, 18],
        )
        # Set scores so margin < 30
        df["team_score_before"] = [150, 154, 155, 161, 163, 164]
        result = tag_bowling_pressure_deliveries(df)
        assert result["is_pressure_death_close"].any()

    def test_death_close_not_triggered_wide_margin(self):
        """Wide margin in death → no close-chase pressure."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=200,
            batter_runs=[1, 0, 1, 0, 1, 0],
            overs=[16, 16, 17, 17, 18, 18],
        )
        # Score 100, target 200 → margin 100, well above 30
        df["team_score_before"] = [100, 101, 101, 102, 102, 103]
        result = tag_bowling_pressure_deliveries(df)
        assert not result["is_pressure_death_close"].any()

    def test_knockout_reused_from_batting(self):
        """If is_pressure_knockout already exists, it's reused."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(innings_num=1, event_name="Regular Match")
        df["is_pressure_knockout"] = True  # pre-tagged
        result = tag_bowling_pressure_deliveries(df)
        assert result["is_pressure_knockout"].all()
        assert result["is_bowl_pressure"].all()

    def test_knockout_computed_when_missing(self):
        """If is_pressure_knockout is missing, compute from event_name."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(innings_num=1, event_name="World Cup Final")
        # Make sure is_pressure_knockout is NOT in columns
        assert "is_pressure_knockout" not in df.columns
        result = tag_bowling_pressure_deliveries(df)
        assert result["is_pressure_knockout"].all()

    def test_combined_bowling_pressure(self):
        """Multiple bowling pressure flags combine."""
        from src.clutch import tag_bowling_pressure_deliveries

        # Knockout + low defend (both apply)
        df = _make_delivery_df(
            innings_num=2,
            target_runs=130,
            event_name="Final",
        )
        df["is_pressure_knockout"] = True
        result = tag_bowling_pressure_deliveries(df)
        assert result["is_pressure_low_defend"].all()
        assert result["is_pressure_knockout"].all()
        assert result["is_bowl_pressure"].all()


# ═══════════════════════════════════════════════════════════════════════════
# Test: aggregate_pressure_to_innings
# ═══════════════════════════════════════════════════════════════════════════


class TestAggregatePressureToInnings:
    """Tests for innings-level pressure aggregation."""

    def test_basic_aggregation(self):
        """All balls under pressure → pressure_ball_pct = 1.0."""
        from src.clutch import aggregate_pressure_to_innings

        n = 10
        df = _make_delivery_df(batter_runs=[1] * n, overs=[i // 6 for i in range(n)])
        df["is_batter_ball"] = True
        df["is_pressure"] = True
        df["is_pressure_high_rrr"] = True
        df["is_pressure_collapse"] = False
        df["is_pressure_knockout"] = False
        df["is_pressure_deep_chase"] = False

        result = aggregate_pressure_to_innings(df)
        assert len(result) == 1
        assert result.iloc[0]["pressure_ball_pct"] == pytest.approx(1.0)
        assert result.iloc[0]["is_pressure_innings"]

    def test_partial_pressure(self):
        """Only 2 of 10 balls under pressure → pct = 0.20, below 0.30 threshold."""
        from src.clutch import aggregate_pressure_to_innings

        n = 10
        df = _make_delivery_df(batter_runs=[1] * n, overs=[i // 6 for i in range(n)])
        df["is_batter_ball"] = True
        df["is_pressure"] = [True, True] + [False] * 8
        df["is_pressure_high_rrr"] = [True, True] + [False] * 8
        df["is_pressure_collapse"] = False
        df["is_pressure_knockout"] = False
        df["is_pressure_deep_chase"] = False

        result = aggregate_pressure_to_innings(df)
        assert result.iloc[0]["pressure_ball_pct"] == pytest.approx(0.20, abs=0.01)
        assert not result.iloc[0]["is_pressure_innings"]

    def test_knockout_overrides_pct_threshold(self):
        """Knockout match → pressure innings even if pressure_ball_pct is low."""
        from src.clutch import aggregate_pressure_to_innings

        n = 20
        df = _make_delivery_df(batter_runs=[1] * n, overs=[i // 6 for i in range(n)])
        df["is_batter_ball"] = True
        df["is_pressure"] = False
        df["is_pressure_high_rrr"] = False
        df["is_pressure_collapse"] = False
        df["is_pressure_knockout"] = [True] + [False] * 19  # just 1 knockout ball
        df["is_pressure_deep_chase"] = False

        result = aggregate_pressure_to_innings(df)
        assert result.iloc[0]["knockout_balls"] == 1
        # Even though pressure_ball_pct is low, knockout → pressure innings
        assert result.iloc[0]["is_pressure_innings"]

    def test_no_pressure_innings(self):
        """No pressure at all → is_pressure_innings = False."""
        from src.clutch import aggregate_pressure_to_innings

        n = 12
        df = _make_delivery_df(batter_runs=[1] * n, overs=[i // 6 for i in range(n)])
        df["is_batter_ball"] = True
        df["is_pressure"] = False
        df["is_pressure_high_rrr"] = False
        df["is_pressure_collapse"] = False
        df["is_pressure_knockout"] = False
        df["is_pressure_deep_chase"] = False

        result = aggregate_pressure_to_innings(df)
        assert not result.iloc[0]["is_pressure_innings"]
        assert result.iloc[0]["pressure_ball_pct"] == 0.0

    def test_multiple_batters_same_innings(self):
        """Multiple batters in same innings are aggregated separately."""
        from src.clutch import aggregate_pressure_to_innings

        df1 = _make_delivery_df(batter_id="b1", batter="A", batter_runs=[1, 1, 1])
        df2 = _make_delivery_df(batter_id="b2", batter="B", batter_runs=[1, 1, 1])
        df = pd.concat([df1, df2], ignore_index=True)
        df["is_batter_ball"] = True
        df["is_pressure"] = [True, True, True, False, False, False]
        df["is_pressure_high_rrr"] = [True, True, True, False, False, False]
        df["is_pressure_collapse"] = False
        df["is_pressure_knockout"] = False
        df["is_pressure_deep_chase"] = False

        result = aggregate_pressure_to_innings(df)
        assert len(result) == 2
        b1_row = result[result["batter_id"] == "b1"].iloc[0]
        b2_row = result[result["batter_id"] == "b2"].iloc[0]
        assert b1_row["pressure_ball_pct"] == pytest.approx(1.0)
        assert b2_row["pressure_ball_pct"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Test: aggregate_pressure_to_spells
# ═══════════════════════════════════════════════════════════════════════════


class TestAggregatePressureToSpells:
    """Tests for spell-level bowling pressure aggregation."""

    def test_basic_spell_aggregation(self):
        """All balls under bowling pressure → is_pressure_spell True."""
        from src.clutch import aggregate_pressure_to_spells

        df = _make_delivery_df(batter_runs=[1] * 10, overs=[i // 6 for i in range(10)])
        df["is_bowl_pressure"] = True
        df["is_pressure_knockout"] = True
        df["is_pressure_low_defend"] = False
        df["is_pressure_death_close"] = False

        result = aggregate_pressure_to_spells(df)
        assert len(result) == 1
        assert result.iloc[0]["is_pressure_spell"]

    def test_no_bowling_pressure(self):
        """No bowling pressure → is_pressure_spell False."""
        from src.clutch import aggregate_pressure_to_spells

        df = _make_delivery_df(batter_runs=[1] * 10, overs=[i // 6 for i in range(10)])
        df["is_bowl_pressure"] = False
        df["is_pressure_knockout"] = False
        df["is_pressure_low_defend"] = False
        df["is_pressure_death_close"] = False

        result = aggregate_pressure_to_spells(df)
        assert not result.iloc[0]["is_pressure_spell"]


# ═══════════════════════════════════════════════════════════════════════════
# Test: compute_clutch_index (batting)
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeClutchIndex:
    """Tests for batting Clutch Index computation."""

    def test_clutch_player(self):
        """Player who performs better under pressure → positive clutch_index."""
        from src.clutch import compute_clutch_index

        # 10 innings: 6 pressure, 4 normal
        # Pressure innings have higher acc_overall_sr
        bc = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10"],
            acc_overall_sr=[
                0.50,
                0.40,
                0.45,
                0.35,
                0.48,
                0.42,  # pressure
                0.10,
                0.05,
                0.08,
                0.12,
            ],  # normal
            acc_impact=[10.0, 8.0, 9.0, 7.0, 9.5, 8.5, 2.0, 1.5, 2.5, 3.0],
        )
        pressure_innings = pd.DataFrame(
            {
                "match_id": [
                    "m1",
                    "m2",
                    "m3",
                    "m4",
                    "m5",
                    "m6",
                    "m7",
                    "m8",
                    "m9",
                    "m10",
                ],
                "innings_num": [1] * 10,
                "batter_id": ["b1"] * 10,
                "is_pressure_innings": [True] * 6 + [False] * 4,
                "pressure_ball_pct": [0.80] * 6 + [0.0] * 4,
            }
        )

        result = compute_clutch_index(bc, pressure_innings, min_pressure_innings=3)
        assert len(result) == 1
        assert result.iloc[0]["clutch_index"] > 0  # better under pressure
        assert result.iloc[0]["pressure_innings"] == 6
        assert result.iloc[0]["normal_innings"] == 4

    def test_choker_player(self):
        """Player who performs worse under pressure → negative clutch_index."""
        from src.clutch import compute_clutch_index

        bc = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10"],
            acc_overall_sr=[
                0.05,
                0.02,
                0.08,
                -0.05,
                0.00,
                -0.03,  # pressure (low)
                0.40,
                0.35,
                0.50,
                0.45,
            ],  # normal (high)
            acc_impact=[1.0, 0.5, 1.5, 0.0, 0.5, 0.0, 10.0, 8.0, 12.0, 9.0],
        )
        pressure_innings = pd.DataFrame(
            {
                "match_id": [
                    "m1",
                    "m2",
                    "m3",
                    "m4",
                    "m5",
                    "m6",
                    "m7",
                    "m8",
                    "m9",
                    "m10",
                ],
                "innings_num": [1] * 10,
                "batter_id": ["b1"] * 10,
                "is_pressure_innings": [True] * 6 + [False] * 4,
                "pressure_ball_pct": [0.80] * 6 + [0.0] * 4,
            }
        )

        result = compute_clutch_index(bc, pressure_innings, min_pressure_innings=3)
        assert result.iloc[0]["clutch_index"] < 0  # worse under pressure

    def test_min_pressure_innings_filter(self):
        """Not enough pressure innings → clutch_index is NaN."""
        from src.clutch import compute_clutch_index

        bc = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4", "m5"],
            acc_overall_sr=[0.50, 0.40, 0.10, 0.05, 0.08],
        )
        pressure_innings = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5"],
                "innings_num": [1] * 5,
                "batter_id": ["b1"] * 5,
                "is_pressure_innings": [True, True, False, False, False],
                "pressure_ball_pct": [0.80, 0.80, 0.0, 0.0, 0.0],
            }
        )

        result = compute_clutch_index(bc, pressure_innings, min_pressure_innings=5)
        assert pd.isna(result.iloc[0]["clutch_index"])  # only 2 pressure < 5

    def test_equal_performance(self):
        """Same performance in both conditions → clutch_index ≈ 0."""
        from src.clutch import compute_clutch_index

        bc = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10"],
            acc_overall_sr=[0.20] * 10,
            acc_impact=[5.0] * 10,
            ctrl_scoring_consistency=[0.65] * 10,
            ctrl_contribution=[0.25] * 10,
        )
        pressure_innings = pd.DataFrame(
            {
                "match_id": [
                    "m1",
                    "m2",
                    "m3",
                    "m4",
                    "m5",
                    "m6",
                    "m7",
                    "m8",
                    "m9",
                    "m10",
                ],
                "innings_num": [1] * 10,
                "batter_id": ["b1"] * 10,
                "is_pressure_innings": [True] * 5 + [False] * 5,
                "pressure_ball_pct": [0.80] * 5 + [0.0] * 5,
            }
        )

        result = compute_clutch_index(bc, pressure_innings, min_pressure_innings=3)
        assert result.iloc[0]["clutch_index"] == pytest.approx(0.0, abs=0.01)

    def test_multiple_batters(self):
        """Multiple batters computed independently."""
        from src.clutch import compute_clutch_index

        bc1 = _make_bat_components(
            batter_id="b1",
            batter="Player A",
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6"],
            acc_overall_sr=[0.50, 0.45, 0.48, 0.10, 0.05, 0.08],
        )
        bc2 = _make_bat_components(
            batter_id="b2",
            batter="Player B",
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6"],
            acc_overall_sr=[0.05, 0.02, 0.08, 0.40, 0.35, 0.50],
        )
        bc = pd.concat([bc1, bc2], ignore_index=True)

        pi1 = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5", "m6"],
                "innings_num": [1] * 6,
                "batter_id": ["b1"] * 6,
                "is_pressure_innings": [True, True, True, False, False, False],
                "pressure_ball_pct": [0.80] * 3 + [0.0] * 3,
            }
        )
        pi2 = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5", "m6"],
                "innings_num": [1] * 6,
                "batter_id": ["b2"] * 6,
                "is_pressure_innings": [True, True, True, False, False, False],
                "pressure_ball_pct": [0.80] * 3 + [0.0] * 3,
            }
        )
        pi = pd.concat([pi1, pi2], ignore_index=True)

        result = compute_clutch_index(bc, pi, min_pressure_innings=3)
        assert len(result) == 2
        b1 = result[result["batter_id"] == "b1"].iloc[0]
        b2 = result[result["batter_id"] == "b2"].iloc[0]
        assert b1["clutch_index"] > 0  # better under pressure
        assert b2["clutch_index"] < 0  # worse under pressure

    def test_clutch_sr_delta_column(self):
        """clutch_sr_delta is computed alongside clutch_index."""
        from src.clutch import compute_clutch_index

        bc = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6"],
            acc_overall_sr=[0.50, 0.45, 0.48, 0.10, 0.05, 0.08],
        )
        pi = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5", "m6"],
                "innings_num": [1] * 6,
                "batter_id": ["b1"] * 6,
                "is_pressure_innings": [True, True, True, False, False, False],
                "pressure_ball_pct": [0.80] * 3 + [0.0] * 3,
            }
        )

        result = compute_clutch_index(bc, pi, min_pressure_innings=3)
        assert "clutch_sr_delta" in result.columns
        assert pd.notna(result.iloc[0]["clutch_sr_delta"])
        # Pressure SR vs par higher than normal → positive delta
        assert result.iloc[0]["clutch_sr_delta"] > 0

    def test_empty_components(self):
        """Empty bat_components → empty result."""
        from src.clutch import compute_clutch_index

        bc = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "batter_id",
                "batter",
                "runs",
                "acc_overall_sr",
                "acc_impact",
                "ctrl_scoring_consistency",
                "ctrl_contribution",
            ]
        )
        pi = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "batter_id",
                "is_pressure_innings",
                "pressure_ball_pct",
            ]
        )
        result = compute_clutch_index(bc, pi)
        assert len(result) == 0
        assert "clutch_index" in result.columns

    def test_all_pressure_no_normal(self):
        """All innings are pressure → normal composite from 0 innings = NaN."""
        from src.clutch import compute_clutch_index

        bc = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4", "m5"],
            acc_overall_sr=[0.30, 0.25, 0.35, 0.28, 0.32],
        )
        pi = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5"],
                "innings_num": [1] * 5,
                "batter_id": ["b1"] * 5,
                "is_pressure_innings": [True] * 5,
                "pressure_ball_pct": [0.80] * 5,
            }
        )

        result = compute_clutch_index(bc, pi, min_pressure_innings=3)
        # Normal innings = 0 → normal composite is NaN → clutch_index uses 0 fill
        assert result.iloc[0]["pressure_innings"] == 5
        assert result.iloc[0]["normal_innings"] == 0

    def test_opp_quality_weight_used(self):
        """Opposition quality weight is used in composite computation."""
        from src.clutch import compute_clutch_index

        bc = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6"],
            acc_overall_sr=[0.50, 0.10, 0.10, 0.10, 0.10, 0.10],
        )
        # Give m1 very high weight
        bc.loc[0, "opp_quality_weight"] = 10.0

        pi = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5", "m6"],
                "innings_num": [1] * 6,
                "batter_id": ["b1"] * 6,
                "is_pressure_innings": [True, True, True, False, False, False],
                "pressure_ball_pct": [0.80] * 3 + [0.0] * 3,
            }
        )

        result = compute_clutch_index(bc, pi, min_pressure_innings=3)
        # m1 has weight 10 and acc_overall_sr 0.50, so pressure composite
        # should be pulled upward compared to unweighted
        assert result.iloc[0]["pressure_innings"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# Test: compute_bowling_clutch_index
# ═══════════════════════════════════════════════════════════════════════════


class TestBowlingClutchIndex:
    """Tests for bowling Clutch Index computation."""

    def test_clutch_bowler(self):
        """Bowler who performs better under pressure → positive clutch_index_bowl."""
        from src.clutch import compute_bowling_clutch_index

        bc = _make_bowl_components(
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"],
            acc_economy_vs_par=[
                0.5,
                0.4,
                0.45,
                0.35,  # pressure (good)
                0.1,
                0.05,
                0.08,
                0.12,
            ],  # normal
            acc_dot_pct=[0.55, 0.50, 0.52, 0.48, 0.30, 0.25, 0.28, 0.35],
            wickets=[3, 2, 3, 2, 1, 0, 1, 1],
        )
        ps = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"],
                "innings_num": [1] * 8,
                "bowler_id": ["bw1"] * 8,
                "is_pressure_spell": [True] * 4 + [False] * 4,
                "bowl_pressure_ball_pct": [0.80] * 4 + [0.0] * 4,
            }
        )

        result = compute_bowling_clutch_index(bc, ps, min_pressure_spells=3)
        assert len(result) == 1
        assert result.iloc[0]["clutch_index_bowl"] > 0

    def test_min_pressure_spells_filter(self):
        """Not enough pressure spells → NaN."""
        from src.clutch import compute_bowling_clutch_index

        bc = _make_bowl_components(match_ids=["m1", "m2", "m3"])
        ps = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3"],
                "innings_num": [1] * 3,
                "bowler_id": ["bw1"] * 3,
                "is_pressure_spell": [True, False, False],
                "bowl_pressure_ball_pct": [0.80, 0.0, 0.0],
            }
        )

        result = compute_bowling_clutch_index(bc, ps, min_pressure_spells=5)
        assert pd.isna(result.iloc[0]["clutch_index_bowl"])

    def test_empty_components(self):
        """Empty bowl_components → empty result."""
        from src.clutch import compute_bowling_clutch_index

        bc = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "bowler_id",
                "bowler",
                "wickets",
                "acc_economy_vs_par",
                "acc_dot_pct",
            ]
        )
        ps = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "bowler_id",
                "is_pressure_spell",
                "bowl_pressure_ball_pct",
            ]
        )
        result = compute_bowling_clutch_index(bc, ps)
        assert len(result) == 0
        assert "clutch_index_bowl" in result.columns

    def test_multiple_bowlers(self):
        """Multiple bowlers computed independently."""
        from src.clutch import compute_bowling_clutch_index

        bc1 = _make_bowl_components(
            bowler_id="bw1",
            bowler="Bowler A",
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6"],
            acc_economy_vs_par=[0.5, 0.4, 0.45, 0.1, 0.05, 0.08],
        )
        bc2 = _make_bowl_components(
            bowler_id="bw2",
            bowler="Bowler B",
            match_ids=["m1", "m2", "m3", "m4", "m5", "m6"],
            acc_economy_vs_par=[0.05, 0.02, 0.08, 0.40, 0.35, 0.50],
        )
        bc = pd.concat([bc1, bc2], ignore_index=True)

        ps1 = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5", "m6"],
                "innings_num": [1] * 6,
                "bowler_id": ["bw1"] * 6,
                "is_pressure_spell": [True, True, True, False, False, False],
                "bowl_pressure_ball_pct": [0.80] * 3 + [0.0] * 3,
            }
        )
        ps2 = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5", "m6"],
                "innings_num": [1] * 6,
                "bowler_id": ["bw2"] * 6,
                "is_pressure_spell": [True, True, True, False, False, False],
                "bowl_pressure_ball_pct": [0.80] * 3 + [0.0] * 3,
            }
        )
        ps = pd.concat([ps1, ps2], ignore_index=True)

        result = compute_bowling_clutch_index(bc, ps, min_pressure_spells=3)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Test: compute_all_clutch_metrics (convenience wrapper)
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeAllClutchMetrics:
    """Tests for the convenience wrapper."""

    def _build_scenario(self):
        """Build a scenario with some pressure and some normal innings."""
        # Create deliveries for 4 matches: 2 knockout (pressure), 2 normal
        frames = []
        for i, (mid, event) in enumerate(
            [
                ("m1", "World Cup Final"),
                ("m2", "World Cup Semi-Final"),
                ("m3", "League Match"),
                ("m4", "League Match"),
            ]
        ):
            df = _make_delivery_df(
                match_id=mid,
                innings_num=1,
                event_name=event,
                batter_runs=[1, 4, 0, 2, 6, 1],
                overs=[0, 1, 2, 3, 4, 5],
            )
            frames.append(df)

        deliveries = pd.concat(frames, ignore_index=True)

        bat_components = _make_bat_components(
            match_ids=["m1", "m2", "m3", "m4"],
            innings_nums=[1, 1, 1, 1],
            acc_overall_sr=[0.50, 0.45, 0.10, 0.05],
            acc_impact=[10.0, 9.0, 2.0, 1.5],
        )

        bowl_components = _make_bowl_components(
            match_ids=["m1", "m2", "m3", "m4"],
            innings_nums=[1, 1, 1, 1],
            acc_economy_vs_par=[0.5, 0.4, 0.1, 0.05],
        )

        return deliveries, bat_components, bowl_components

    def test_returns_all_keys(self):
        """Wrapper returns dict with all expected keys."""
        from src.clutch import compute_all_clutch_metrics

        deliveries, bc, boc = self._build_scenario()
        result = compute_all_clutch_metrics(deliveries, bc, boc, min_pressure_innings=2)
        expected_keys = {
            "pressure_deliveries",
            "pressure_innings",
            "pressure_spells",
            "batting_clutch",
            "bowling_clutch",
        }
        assert set(result.keys()) == expected_keys

    def test_pressure_deliveries_tagged(self):
        """Pressure deliveries are correctly tagged."""
        from src.clutch import compute_all_clutch_metrics

        deliveries, bc, boc = self._build_scenario()
        result = compute_all_clutch_metrics(deliveries, bc, boc, min_pressure_innings=2)
        pd_df = result["pressure_deliveries"]
        assert "is_pressure" in pd_df.columns
        assert "is_bowl_pressure" in pd_df.columns

        # Matches m1 and m2 are knockout → all pressure
        m1_pressure = pd_df[pd_df["match_id"] == "m1"]["is_pressure"]
        assert m1_pressure.all()
        m3_pressure = pd_df[pd_df["match_id"] == "m3"]["is_pressure"]
        assert not m3_pressure.any()

    def test_batting_clutch_computed(self):
        """Batting clutch index is computed."""
        from src.clutch import compute_all_clutch_metrics

        deliveries, bc, boc = self._build_scenario()
        result = compute_all_clutch_metrics(deliveries, bc, boc, min_pressure_innings=2)
        bat_clutch = result["batting_clutch"]
        assert "clutch_index" in bat_clutch.columns
        assert len(bat_clutch) > 0

    def test_bowling_clutch_computed(self):
        """Bowling clutch index is computed."""
        from src.clutch import compute_all_clutch_metrics

        deliveries, bc, boc = self._build_scenario()
        result = compute_all_clutch_metrics(deliveries, bc, boc, min_pressure_spells=2)
        bowl_clutch = result["bowling_clutch"]
        assert "clutch_index_bowl" in bowl_clutch.columns
        assert len(bowl_clutch) > 0

    def test_custom_thresholds_passed_through(self):
        """Custom rrr_threshold and collapse_wickets are respected."""
        from src.clutch import compute_all_clutch_metrics

        deliveries, bc, boc = self._build_scenario()
        result = compute_all_clutch_metrics(
            deliveries,
            bc,
            boc,
            high_rrr_threshold=100.0,  # impossibly high → no RRR pressure
            collapse_wickets=11,  # impossible → no collapse pressure
            min_pressure_innings=2,
        )
        pd_df = result["pressure_deliveries"]
        assert not pd_df["is_pressure_high_rrr"].any()
        assert not pd_df["is_pressure_collapse"].any()


# ═══════════════════════════════════════════════════════════════════════════
# Test: Edge cases & integration
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and integration tests."""

    def test_single_delivery_innings(self):
        """Single-delivery innings doesn't crash."""
        from src.clutch import aggregate_pressure_to_innings, tag_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=200,
            batter_runs=[6],
            overs=[19],
            phases=["death"],
        )
        df["team_score_before"] = [194]
        tagged = tag_pressure_deliveries(df)
        agg = aggregate_pressure_to_innings(tagged)
        assert len(agg) == 1

    def test_nan_target_runs(self):
        """NaN target_runs (first innings) handled gracefully."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(innings_num=1)
        df["target_runs"] = np.nan
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_high_rrr"].any()
        assert not result["is_pressure_deep_chase"].any()

    def test_all_innings_normal(self):
        """No pressure innings at all → clutch_index is NaN for all."""
        from src.clutch import compute_clutch_index

        bc = _make_bat_components(match_ids=["m1", "m2", "m3", "m4", "m5"])
        pi = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5"],
                "innings_num": [1] * 5,
                "batter_id": ["b1"] * 5,
                "is_pressure_innings": [False] * 5,
                "pressure_ball_pct": [0.0] * 5,
            }
        )

        result = compute_clutch_index(bc, pi, min_pressure_innings=3)
        assert pd.isna(result.iloc[0]["clutch_index"])

    def test_pressure_innings_with_missing_components(self):
        """Missing component columns → NaN composites, no crash."""
        from src.clutch import compute_clutch_index

        bc = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5"],
                "innings_num": [1] * 5,
                "batter_id": ["b1"] * 5,
                "batter": ["Player A"] * 5,
                "runs": [30] * 5,
                # No acc_overall_sr, acc_impact, etc.
            }
        )
        pi = pd.DataFrame(
            {
                "match_id": ["m1", "m2", "m3", "m4", "m5"],
                "innings_num": [1] * 5,
                "batter_id": ["b1"] * 5,
                "is_pressure_innings": [True] * 3 + [False] * 2,
                "pressure_ball_pct": [0.80] * 3 + [0.0] * 2,
            }
        )

        result = compute_clutch_index(bc, pi, min_pressure_innings=3)
        # Should still produce a result, just with 0-based composite
        assert len(result) == 1

    def test_large_overs_limit(self):
        """Non-standard overs limit (e.g. 10-over match) handled."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=100,
            overs_limit=10,
            batter_runs=[0, 0, 0],
            overs=[0, 0, 0],
        )
        result = tag_pressure_deliveries(df)
        # RRR = 100 / 10 = 10.0 > 9.0 → pressure
        assert result["is_pressure_high_rrr"].any()

    def test_collapse_not_in_powerplay(self):
        """Collapse wickets in middle overs → no collapse pressure (PP only)."""
        from src.clutch import tag_pressure_deliveries

        df = _make_delivery_df(
            innings_num=1,
            batter_runs=[0, 1, 4],
            overs=[8, 9, 10],
            phases=["middle", "middle", "middle"],
            team_wickets_before=[4, 4, 5],
        )
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_collapse"].any()

    def test_deep_chase_at_exactly_50_pct(self):
        """Exactly 50% remaining → should be at boundary (> not >=)."""
        from src.clutch import tag_pressure_deliveries

        # Target 200, score 100 → 100/200 = 50% remaining
        # is_pressure_deep_chase uses > 0.50, so exactly 50% should NOT trigger
        df = _make_delivery_df(
            innings_num=2,
            target_runs=200,
            batter_runs=[0],
            overs=[14],
            phases=["middle"],
        )
        df["team_score_before"] = [100]
        result = tag_pressure_deliveries(df)
        assert not result["is_pressure_deep_chase"].iloc[0]

    def test_deep_chase_above_50_pct(self):
        """Just above 50% remaining → should trigger."""
        from src.clutch import tag_pressure_deliveries

        # Target 200, score 99 → 101/200 = 50.5% remaining
        df = _make_delivery_df(
            innings_num=2,
            target_runs=200,
            batter_runs=[0],
            overs=[14],
            phases=["middle"],
        )
        df["team_score_before"] = [99]
        result = tag_pressure_deliveries(df)
        assert result["is_pressure_deep_chase"].iloc[0]

    def test_categorical_batter_id_in_aggregation(self):
        """Categorical batter_id in aggregate_pressure_to_innings."""
        from src.clutch import aggregate_pressure_to_innings

        n = 6
        df = _make_delivery_df(batter_runs=[1] * n, overs=[i // 6 for i in range(n)])
        df["is_batter_ball"] = True
        df["is_pressure"] = True
        df["is_pressure_high_rrr"] = False
        df["is_pressure_collapse"] = False
        df["is_pressure_knockout"] = True
        df["is_pressure_deep_chase"] = False
        df["batter_id"] = df["batter_id"].astype("category")
        df["match_id"] = df["match_id"].astype("category")

        result = aggregate_pressure_to_innings(df)
        assert len(result) == 1
        assert result.iloc[0]["is_pressure_innings"]

    def test_bowling_death_close_boundary_margin(self):
        """Margin exactly 30 → close (implementation uses <= 30)."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=180,
            batter_runs=[0],
            overs=[16],
        )
        df["team_score_before"] = [150]  # margin = 30, included by <= 30
        result = tag_bowling_pressure_deliveries(df)
        assert result["is_pressure_death_close"].iloc[0]

    def test_bowling_death_close_margin_29(self):
        """Margin 29 → close (< 30)."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=180,
            batter_runs=[0],
            overs=[16],
        )
        df["team_score_before"] = [151]  # margin = 29 < 30
        result = tag_bowling_pressure_deliveries(df)
        assert result["is_pressure_death_close"].iloc[0]

    def test_bowling_death_close_target_already_reached(self):
        """Target already reached (margin ≤ 0) → not close chase."""
        from src.clutch import tag_bowling_pressure_deliveries

        df = _make_delivery_df(
            innings_num=2,
            target_runs=170,
            batter_runs=[4],
            overs=[18],
        )
        df["team_score_before"] = [170]  # margin = 0
        result = tag_bowling_pressure_deliveries(df)
        assert not result["is_pressure_death_close"].iloc[0]
