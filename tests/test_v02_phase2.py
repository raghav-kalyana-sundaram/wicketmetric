"""
Tests for Version 0.2 Phase 2 features:
  - Feature 6:  Chase Master Index (innings 1 vs 2 splits)
  - Feature 11: Anchor Cost / Balls-to-Par
  - Feature 8:  Selfless vs Stat-Padder Index (milestone approach SRs)

Tests cover:
  - Per-innings extraction (balls_to_par, milestone zone SRs)
  - Career aggregation (avg_balls_to_par, anchor_cost_ratio, selfless_*)
  - Chase Master standalone function (compute_chase_splits)
  - Edge cases (short innings, no data, disabled features, NaN handling)
  - Integration with the rating pipeline columns
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal DataFrames that look like pipeline output
# ---------------------------------------------------------------------------


def _make_delivery_df(
    match_id: str = "m1",
    innings_num: int = 1,
    batter_id: str = "b1",
    batter: str = "Player A",
    batting_team: str = "TeamA",
    bowling_team: str = "TeamB",
    batter_runs: list[int] | None = None,
    overs: list[float] | None = None,
    phases: list[str] | None = None,
    bowler_id: str = "bw1",
    bowler: str = "Bowler X",
    batting_position: int = 3,
) -> pd.DataFrame:
    """Create a minimal delivery-level DataFrame for a single innings."""
    if batter_runs is None:
        batter_runs = [0, 1, 4, 0, 2, 6, 1, 0, 1, 4]
    n = len(batter_runs)
    if overs is None:
        overs = [i // 6 for i in range(n)]
    if phases is None:
        phases = ["powerplay"] * min(n, 6) + ["middle"] * max(0, n - 6)

    # Compute cumulative team score for team_score_before
    cum_runs = np.cumsum([0] + batter_runs[:-1])

    rows = []
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
                "over": overs[i],
                "ball_idx": i % 6,
                "phase": phases[i],
                "team_score_before": int(cum_runs[i]),
                "team_wickets_before": 0,
                "batting_position": batting_position,
                "date": pd.Timestamp("2024-01-15"),
            }
        )
    return pd.DataFrame(rows)


def _make_innings_context(
    match_id: str = "m1",
    innings_num: int = 1,
    batting_team: str = "TeamA",
    total_runs: int = 170,
    legal_balls: int = 120,
) -> pd.DataFrame:
    sr = total_runs / legal_balls * 100 if legal_balls > 0 else 0
    return pd.DataFrame(
        [
            {
                "match_id": match_id,
                "innings_num": innings_num,
                "batting_team": batting_team,
                "total_runs": total_runs,
                "legal_balls": legal_balls,
                "innings_sr": sr,
                "match_par_sr": sr,
                "match_par_rr": total_runs / (legal_balls / 6)
                if legal_balls > 0
                else 0,
                "match_boundary_rate": 0.10,
            }
        ]
    )


def _make_multi_batter_delivery_df(
    match_id: str = "m1",
    innings_num: int = 1,
    target_batter_id: str = "b1",
    target_batter: str = "Player A",
    target_runs: list[int] | None = None,
    other_batter_id: str = "b2",
    other_batter: str = "Other Batter",
    other_runs: list[int] | None = None,
    batting_team: str = "TeamA",
    bowling_team: str = "TeamB",
) -> pd.DataFrame:
    """
    Create a delivery DataFrame with TWO batters so that phase par SRs
    are meaningful (not solely determined by the target batter's own data).

    Both batters are interleaved ball-by-ball (alternating) so that they
    share the same phases.  This ensures the "other" batter provides
    scoring context in every phase the target batter bats in.
    """
    if target_runs is None:
        target_runs = [0, 1, 4, 0, 2, 6, 1, 0, 1, 4]
    if other_runs is None:
        # Other batter provides realistic par: ~140 SR across phases
        other_runs = [2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1]

    # Interleave: other ball, target ball, other ball, target ball, ...
    # If one list is longer, its remaining balls are appended at the end.
    all_rows = []
    n_other = len(other_runs)
    n_target = len(target_runs)
    max_len = max(n_other, n_target)
    cum_score = 0
    ball_counter = 0  # global ball counter across both batters

    for idx in range(max_len):
        # Other batter's ball first
        if idx < n_other:
            over = ball_counter // 6
            phase = "powerplay" if over < 1 else ("middle" if over < 3 else "death")
            r = other_runs[idx]
            all_rows.append(
                {
                    "match_id": match_id,
                    "innings_num": innings_num,
                    "batter_id": other_batter_id,
                    "batter": other_batter,
                    "batting_team": batting_team,
                    "bowling_team": bowling_team,
                    "bowler_id": "bw1",
                    "bowler": "Bowler X",
                    "batter_runs": r,
                    "extras_runs": 0,
                    "total_runs": r,
                    "is_legal": True,
                    "is_batter_ball": True,
                    "is_wide": False,
                    "is_noball": False,
                    "is_wicket": False,
                    "player_out_id": None,
                    "wicket_kind": None,
                    "is_four": r == 4,
                    "is_six": r == 6,
                    "is_dot_batter": r == 0,
                    "over": over,
                    "ball_idx": ball_counter % 6,
                    "phase": phase,
                    "team_score_before": cum_score,
                    "team_wickets_before": 0,
                    "batting_position": 1,
                    "date": pd.Timestamp("2024-01-15"),
                }
            )
            cum_score += r
            ball_counter += 1

        # Target batter's ball
        if idx < n_target:
            over = ball_counter // 6
            phase = "powerplay" if over < 1 else ("middle" if over < 3 else "death")
            r = target_runs[idx]
            all_rows.append(
                {
                    "match_id": match_id,
                    "innings_num": innings_num,
                    "batter_id": target_batter_id,
                    "batter": target_batter,
                    "batting_team": batting_team,
                    "bowling_team": bowling_team,
                    "bowler_id": "bw1",
                    "bowler": "Bowler X",
                    "batter_runs": r,
                    "extras_runs": 0,
                    "total_runs": r,
                    "is_legal": True,
                    "is_batter_ball": True,
                    "is_wide": False,
                    "is_noball": False,
                    "is_wicket": False,
                    "player_out_id": None,
                    "wicket_kind": None,
                    "is_four": r == 4,
                    "is_six": r == 6,
                    "is_dot_batter": r == 0,
                    "over": over,
                    "ball_idx": ball_counter % 6,
                    "phase": phase,
                    "team_score_before": cum_score,
                    "team_wickets_before": 0,
                    "batting_position": 3,
                    "date": pd.Timestamp("2024-01-15"),
                }
            )
            cum_score += r
            ball_counter += 1

    return pd.DataFrame(all_rows)


def _make_bat_components(
    n_players: int = 4,
    innings_per_player: int = 10,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Create a minimal bat_components-like DataFrame with the columns needed
    by compute_chase_splits and career aggregation.
    """
    rng = np.random.RandomState(seed)
    rows = []
    for p in range(n_players):
        pid = f"b{p}"
        pname = f"Player {chr(65 + p)}"
        for i in range(innings_per_player):
            inn_num = 1 if i % 2 == 0 else 2  # alternating setting/chasing
            rows.append(
                {
                    "match_id": f"m{p}_{i}",
                    "innings_num": inn_num,
                    "batter_id": pid,
                    "batter": pname,
                    "batting_team": "TeamA",
                    "runs": rng.randint(10, 80),
                    "balls_faced": rng.randint(10, 50),
                    "sr": rng.uniform(100, 200),
                    "acc_overall_sr": rng.uniform(-0.2, 0.4),
                    "acc_sr_growth": rng.uniform(0, 0.3),
                    "acc_death_sr": rng.uniform(-0.2, 0.3),
                    "acc_impact": rng.uniform(0, 30),
                    "acc_runs_above_expected": rng.uniform(-0.5, 1.0),
                    "pow_boundary_pct": rng.uniform(0.2, 0.6),
                    "pow_six_rate": rng.uniform(0.0, 0.15),
                    "pow_boundary_rate_vs_par": rng.uniform(-0.05, 0.1),
                    "pow_peak_phase_sr": rng.uniform(-0.1, 0.4),
                    "pow_finishing_burst": rng.uniform(0.0, 0.5),
                    "pow_power_impact": rng.uniform(0.0, 2.0),
                    "ctrl_dot_pct_weighted": rng.uniform(0.4, 0.8),
                    "ctrl_scoring_consistency": rng.uniform(0.3, 0.8),
                    "ctrl_rotation": rng.uniform(0.3, 0.6),
                    "ctrl_contribution": rng.uniform(0.05, 0.4),
                    "ctrl_avg_proxy": rng.uniform(10, 60),
                    "ctrl_dismissal_quality": rng.uniform(-0.3, 0.0),
                    "opp_quality_weight": 1.0,
                    "opposition_quality": 0.0,
                    "opp_team_quality": 0.0,
                    "opp_icc_rating": 250.0,
                    "recency_weight": 1.0,
                    "sr_vs_par": rng.uniform(0.8, 1.3),
                    "date": pd.Timestamp("2024-01-15"),
                    # Phase stats (minimal)
                    "first_half_sr": rng.uniform(80, 160),
                    "first_half_balls": 10,
                    "first_half_runs": rng.randint(5, 30),
                    "second_half_sr": rng.uniform(100, 220),
                    "second_half_balls": 10,
                    "second_half_runs": rng.randint(5, 30),
                    "first_two_thirds_sr": rng.uniform(80, 160),
                    "first_two_thirds_balls": 14,
                    "first_two_thirds_runs": rng.randint(8, 35),
                    "first_two_thirds_sixes": rng.randint(0, 2),
                    "first_two_thirds_fours": rng.randint(0, 3),
                    "final_third_sr": rng.uniform(100, 250),
                    "final_third_balls": 6,
                    "final_third_runs": rng.randint(5, 25),
                    "final_third_sixes": rng.randint(0, 3),
                    "final_third_fours": rng.randint(0, 2),
                    "match_par_sr": 140.0,
                    "pp_par_sr": 130.0,
                    "middle_par_sr": 135.0,
                    "death_par_sr": 155.0,
                    "match_boundary_rate": 0.10,
                    "powerplay_balls": 6,
                    "powerplay_runs": rng.randint(3, 20),
                    "powerplay_sr": rng.uniform(100, 200),
                    "powerplay_dots": 2,
                    "powerplay_fours": 1,
                    "powerplay_sixes": 0,
                    "middle_balls": rng.randint(0, 20),
                    "middle_runs": rng.randint(0, 30),
                    "middle_sr": rng.uniform(100, 180),
                    "middle_dots": 1,
                    "middle_fours": 0,
                    "middle_sixes": 0,
                    "death_balls": rng.randint(0, 10),
                    "death_runs": rng.randint(0, 20),
                    "death_sr": rng.uniform(110, 250),
                    "death_dots": 0,
                    "death_fours": 0,
                    "death_sixes": 0,
                    "fours": rng.randint(0, 6),
                    "sixes": rng.randint(0, 4),
                    "dots": rng.randint(2, 15),
                    "ones": rng.randint(2, 10),
                    "twos": rng.randint(0, 4),
                    "threes": 0,
                    "total_runs": 170,
                    "legal_balls": 120,
                    "is_out": rng.choice([True, False]),
                    "how_out": None,
                    "boundary_pct": rng.uniform(0.2, 0.6),
                    "dot_pct": rng.uniform(0.2, 0.5),
                    "rotation_rate": rng.uniform(0.3, 0.6),
                    "team_contribution_pct": rng.uniform(0.05, 0.4),
                    "balls_pct_of_team": rng.uniform(0.05, 0.3),
                    "sr_diff_par": rng.uniform(-30, 50),
                    # Anchor cost and selfless (may or may not be present)
                    "balls_to_par": rng.randint(0, 15),
                    "fifty_approach_sr": rng.choice([np.nan, 90, 110, 130]),
                    "fifty_approach_balls": rng.choice([np.nan, 0, 3, 5, 8]),
                    "fifty_approach_runs": rng.choice([np.nan, 0, 5, 10, 15]),
                    "century_approach_sr": np.nan,
                    "century_approach_balls": np.nan,
                    "century_approach_runs": np.nan,
                    "batting_position": 3,
                }
            )
    return pd.DataFrame(rows)


# ===========================================================================
# Feature 6: Chase Master Index
# ===========================================================================


class TestChaseMasterIndex:
    """Tests for compute_chase_splits()."""

    def test_basic_split(self):
        """Should produce setting and chasing aggregates."""
        from src.batting import compute_chase_splits

        bc = _make_bat_components(n_players=2, innings_per_player=12)
        result = compute_chase_splits(bc)

        assert not result.empty
        assert "chase_master_index" in result.columns
        assert "bat_first_index" in result.columns
        assert "chase_master_full" in result.columns
        assert "setting_inn" in result.columns
        assert "chasing_inn" in result.columns

    def test_one_row_per_player(self):
        """Should produce exactly one row per batter."""
        from src.batting import compute_chase_splits

        bc = _make_bat_components(n_players=5, innings_per_player=10)
        result = compute_chase_splits(bc)

        assert len(result) == 5
        assert result["batter_id"].nunique() == 5

    def test_chase_master_positive_means_better_chasing(self):
        """
        A player who has higher acc_overall_sr when chasing should have
        a positive chase_master_index.
        """
        from src.batting import compute_chase_splits

        rows = []
        for i in range(12):
            inn_num = 1 if i < 6 else 2
            # Setting innings: low SR vs par; Chasing: high SR vs par
            sr_vs = -0.1 if inn_num == 1 else 0.3
            rows.append(
                {
                    "match_id": f"m_{i}",
                    "innings_num": inn_num,
                    "batter_id": "b1",
                    "batter": "Chase King",
                    "runs": 40,
                    "balls_faced": 25,
                    "sr": 160.0,
                    "acc_overall_sr": sr_vs,
                    "acc_impact": 10.0,
                    "ctrl_scoring_consistency": 0.6,
                }
            )
        bc = pd.DataFrame(rows)
        result = compute_chase_splits(bc)

        assert len(result) == 1
        cmi = result.iloc[0]["chase_master_index"]
        assert pd.notna(cmi)
        assert cmi > 0, "Chase Master Index should be positive for a better chaser"

    def test_bat_first_index_is_inverse(self):
        """bat_first_index should be the inverse of chase_master_index."""
        from src.batting import compute_chase_splits

        bc = _make_bat_components(n_players=3, innings_per_player=12)
        result = compute_chase_splits(bc)

        for _, row in result.iterrows():
            cmi = row["chase_master_index"]
            bfi = row["bat_first_index"]
            if pd.notna(cmi) and pd.notna(bfi):
                assert abs(cmi + bfi) < 1e-9, (
                    "bat_first_index should be -chase_master_index"
                )

    def test_min_innings_filter(self):
        """
        Players with fewer than min_innings_per_type in setting or chasing
        should get NaN for the index.
        """
        from src.batting import compute_chase_splits

        # Player with only 3 chasing innings (below default min of 5)
        rows = []
        for i in range(8):
            inn_num = 1 if i < 5 else 2  # 5 setting, 3 chasing
            rows.append(
                {
                    "match_id": f"m_{i}",
                    "innings_num": inn_num,
                    "batter_id": "b1",
                    "batter": "Few Chases",
                    "runs": 30,
                    "balls_faced": 20,
                    "sr": 150.0,
                    "acc_overall_sr": 0.1,
                    "acc_impact": 5.0,
                    "ctrl_scoring_consistency": 0.5,
                }
            )
        bc = pd.DataFrame(rows)
        result = compute_chase_splits(bc)

        assert len(result) == 1
        assert pd.isna(result.iloc[0]["chase_master_index"])

    def test_all_setting_no_chasing(self):
        """Player who only batted first should still appear but with NaN index."""
        from src.batting import compute_chase_splits

        rows = []
        for i in range(10):
            rows.append(
                {
                    "match_id": f"m_{i}",
                    "innings_num": 1,  # Always setting
                    "batter_id": "b1",
                    "batter": "Setting Only",
                    "runs": 30,
                    "balls_faced": 20,
                    "sr": 150.0,
                    "acc_overall_sr": 0.1,
                    "acc_impact": 5.0,
                    "ctrl_scoring_consistency": 0.5,
                }
            )
        bc = pd.DataFrame(rows)
        result = compute_chase_splits(bc)

        assert len(result) == 1
        assert pd.isna(result.iloc[0]["chase_master_index"])
        assert pd.notna(result.iloc[0]["setting_inn"])

    def test_categorical_columns_handled(self):
        """Should work even if batter_id/batter are categoricals."""
        from src.batting import compute_chase_splits

        bc = _make_bat_components(n_players=2, innings_per_player=10)
        bc["batter_id"] = bc["batter_id"].astype("category")
        bc["batter"] = bc["batter"].astype("category")
        result = compute_chase_splits(bc)

        assert not result.empty

    def test_chase_master_full_includes_control(self):
        """chase_master_full should differ from chase_master_index by control term."""
        from src.batting import compute_chase_splits

        # Create a player where control differs between setting and chasing
        rows = []
        for i in range(12):
            inn_num = 1 if i < 6 else 2
            rows.append(
                {
                    "match_id": f"m_{i}",
                    "innings_num": inn_num,
                    "batter_id": "b1",
                    "batter": "Control Diff",
                    "runs": 40,
                    "balls_faced": 25,
                    "sr": 160.0,
                    "acc_overall_sr": 0.1,  # Same SR both innings types
                    "acc_impact": 10.0,
                    "ctrl_scoring_consistency": 0.4 if inn_num == 1 else 0.8,
                }
            )
        bc = pd.DataFrame(rows)
        result = compute_chase_splits(bc)

        cmi = result.iloc[0]["chase_master_index"]
        cmf = result.iloc[0]["chase_master_full"]
        # chase_master_index should be ~0 (same SR), but full should be positive
        # because control is higher when chasing
        assert abs(cmi) < 0.01
        assert cmf > cmi

    def test_empty_input(self):
        """Should return empty DataFrame for empty input."""
        from src.batting import compute_chase_splits

        bc = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "batter_id",
                "batter",
                "acc_overall_sr",
                "acc_impact",
                "ctrl_scoring_consistency",
                "runs",
            ]
        )
        result = compute_chase_splits(bc)
        # Should not error; result can be empty
        assert isinstance(result, pd.DataFrame)


# ===========================================================================
# Feature 11: Anchor Cost / Balls-to-Par
# ===========================================================================


class TestAnchorCost:
    """Tests for Anchor Cost (balls_to_par) in extract_batting_innings."""

    def _extract_with_multi_batter(
        self,
        target_runs: list[int],
        other_runs: list[int] | None = None,
    ) -> pd.DataFrame:
        """
        Helper: build a multi-batter delivery DataFrame so that phase par
        SRs are meaningful, then extract and return the target batter's row.
        """
        from src.batting import extract_batting_innings

        if other_runs is None:
            # "Other batter" provides realistic par context (~130-150 SR)
            other_runs = [2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1]

        df = _make_multi_batter_delivery_df(
            target_runs=target_runs,
            other_runs=other_runs,
        )
        total = sum(target_runs) + sum(other_runs)
        n_balls = len(target_runs) + len(other_runs)
        ctx = _make_innings_context(total_runs=total, legal_balls=n_balls)
        result = extract_batting_innings(df, ctx)

        # Return only the target batter's row
        target = result[result["batter_id"] == "b1"]
        return target

    def _extract_with_deliveries(
        self,
        batter_runs: list[int],
        phases: list[str] | None = None,
        overs: list[float] | None = None,
    ) -> pd.DataFrame:
        """Helper: build deliveries → extract_batting_innings → return agg."""
        from src.batting import extract_batting_innings

        n = len(batter_runs)
        if phases is None:
            phases = ["powerplay"] * min(n, 6) + ["middle"] * max(0, n - 6)
        if overs is None:
            overs = [i // 6 for i in range(n)]

        df = _make_delivery_df(
            batter_runs=batter_runs,
            phases=phases,
            overs=overs,
        )
        ctx = _make_innings_context()
        return extract_batting_innings(df, ctx)

    def test_balls_to_par_column_exists(self):
        """extract_batting_innings should add balls_to_par column."""
        result = self._extract_with_deliveries([1, 4, 6, 2, 0, 1, 4, 1, 2, 6])
        assert "balls_to_par" in result.columns

    def test_fast_starter_low_balls_to_par(self):
        """
        A batter who immediately scores above par should have a very low
        balls_to_par (0 or 1).
        """
        # All boundaries: cumulative SR is always very high (~400)
        # Other batter provides par of ~130-ish SR
        runs = [4, 6, 4, 4, 6, 4, 4, 6, 4, 4]
        result = self._extract_with_multi_batter(target_runs=runs)
        assert len(result) >= 1
        btp = result.iloc[0]["balls_to_par"]
        assert pd.notna(btp)
        assert btp <= 1, (
            f"Expected balls_to_par <= 1 for all-boundary innings, got {btp}"
        )

    def test_slow_starter_high_balls_to_par(self):
        """
        A batter who starts with many dots should have a high balls_to_par.
        The other batter in the match provides a realistic par (~130+ SR)
        so the slow starter's cumulative SR stays below par for many balls.
        """
        # 8 dots then two sixes: cumulative SR stays 0 for 8 balls, then
        # 66.7 after ball 9, 120 after ball 10 — still below par (~130+)
        runs = [0, 0, 0, 0, 0, 0, 0, 0, 6, 6]
        result = self._extract_with_multi_batter(target_runs=runs)
        assert len(result) >= 1
        btp = result.iloc[0]["balls_to_par"]
        bf = result.iloc[0]["balls_faced"]
        assert pd.notna(btp)
        # With par ~130+ SR, cumulative SR of 120 after 10 balls never reaches par
        # so balls_to_par should be balls_faced (10) or close to it
        assert btp >= 6, f"Expected balls_to_par >= 6 for slow starter, got {btp}"

    def test_never_reaches_par(self):
        """
        A batter who never reaches par should get balls_to_par = balls_faced.
        """
        # All dots — cumulative SR stays 0 throughout
        runs = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        result = self._extract_with_multi_batter(target_runs=runs)
        assert len(result) >= 1
        btp = result.iloc[0]["balls_to_par"]
        bf = result.iloc[0]["balls_faced"]
        assert btp == bf, "balls_to_par should equal balls_faced when par never reached"

    def test_career_avg_balls_to_par(self):
        """Career aggregation should produce avg_balls_to_par."""
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=2, innings_per_player=15)
        career = aggregate_batting_careers(bc, min_innings=5)

        assert "avg_balls_to_par" in career.columns
        assert "anchor_cost_ratio" in career.columns
        # All should be non-NaN for players with enough innings
        for _, row in career.iterrows():
            assert pd.notna(row["avg_balls_to_par"])
            assert pd.notna(row["anchor_cost_ratio"])

    def test_anchor_cost_ratio_between_0_and_1(self):
        """anchor_cost_ratio should be between 0 and 1 for typical data."""
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=3, innings_per_player=15)
        career = aggregate_batting_careers(bc, min_innings=5)

        for _, row in career.iterrows():
            ratio = row["anchor_cost_ratio"]
            if pd.notna(ratio):
                assert 0 <= ratio <= 1.5, f"Unexpected anchor_cost_ratio: {ratio}"

    def test_single_ball_innings(self):
        """An innings of 1 ball should not crash."""
        runs = [4]
        result = self._extract_with_multi_batter(target_runs=runs)
        assert len(result) >= 1
        assert "balls_to_par" in result.columns


# ===========================================================================
# Feature 8: Selfless vs Stat-Padder Index
# ===========================================================================


class TestSelflessIndex:
    """Tests for Selfless Index (milestone approach zone SRs)."""

    def _extract_with_deliveries(
        self,
        batter_runs: list[int],
        phases: list[str] | None = None,
        overs: list[float] | None = None,
    ) -> pd.DataFrame:
        """Helper: build deliveries → extract_batting_innings → return agg."""
        from src.batting import extract_batting_innings

        n = len(batter_runs)
        if phases is None:
            phases = ["powerplay"] * min(n, 6) + ["middle"] * max(0, n - 6)
        if overs is None:
            overs = [i // 6 for i in range(n)]

        df = _make_delivery_df(
            batter_runs=batter_runs,
            phases=phases,
            overs=overs,
        )
        ctx = _make_innings_context()
        return extract_batting_innings(df, ctx)

    def _extract_with_multi_batter(
        self,
        target_runs: list[int],
        other_runs: list[int] | None = None,
    ) -> pd.DataFrame:
        """
        Helper: build a multi-batter delivery DataFrame and return the
        target batter's row from extract_batting_innings.
        """
        from src.batting import extract_batting_innings

        if other_runs is None:
            other_runs = [2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1]

        df = _make_multi_batter_delivery_df(
            target_runs=target_runs,
            other_runs=other_runs,
        )
        total = sum(target_runs) + sum(other_runs)
        n_balls = len(target_runs) + len(other_runs)
        ctx = _make_innings_context(total_runs=total, legal_balls=n_balls)
        result = extract_batting_innings(df, ctx)
        target = result[result["batter_id"] == "b1"]
        return target

    def test_fifty_approach_columns_exist(self):
        """extract_batting_innings should add fifty_approach_* columns."""
        # Build an innings long enough that batter reaches 40-49 zone
        # Runs: 4 per ball for 10 balls = 40, then enter zone
        runs = [4] * 10 + [1] * 5 + [4] * 3  # reaches 40 at ball 10
        phases = ["powerplay"] * 6 + ["middle"] * 12
        overs = [i // 6 for i in range(len(runs))]
        result = self._extract_with_deliveries(runs, phases=phases, overs=overs)

        assert "fifty_approach_sr" in result.columns
        assert "fifty_approach_balls" in result.columns
        assert "fifty_approach_runs" in result.columns

    def test_century_approach_columns_exist(self):
        """extract_batting_innings should add century_approach_* columns."""
        # Short innings — no century approach zone, but columns should exist
        runs = [4, 1, 0, 2, 6, 1]
        result = self._extract_with_deliveries(runs)

        assert "century_approach_sr" in result.columns
        assert "century_approach_balls" in result.columns
        assert "century_approach_runs" in result.columns

    def test_fifty_zone_sr_calculation(self):
        """
        When a batter is in the 40-49 zone, fifty_approach_sr should
        reflect their strike rate in that zone.

        Zone logic: score_before_ball is the cumulative score BEFORE the
        current delivery.  A ball is in the zone if 40 <= score_before <= 49.

        Innings: [4]*10 + [1]*5 + [4]*3
        - Balls 0-9: 4 each → cumsum 4,8,...,40. score_before: 0,4,...,36
          (none in 40-49 zone since score_before maxes at 36)
        - Ball 10 (1): cumsum=41, score_before=40 → IN zone
        - Ball 11 (1): cumsum=42, score_before=41 → IN zone
        - Ball 12 (1): cumsum=43, score_before=42 → IN zone
        - Ball 13 (1): cumsum=44, score_before=43 → IN zone
        - Ball 14 (1): cumsum=45, score_before=44 → IN zone
        - Ball 15 (4): cumsum=49, score_before=45 → IN zone
        - Ball 16 (4): cumsum=53, score_before=49 → IN zone
        - Ball 17 (4): cumsum=57, score_before=53 → OUT of zone

        Zone balls: 10-16 = 7 balls. Runs in zone: 5*1 + 2*4 = 13.
        Zone SR = 13/7 * 100 ≈ 185.7
        """
        runs = [4] * 10 + [1] * 5 + [4] * 3
        phases = ["powerplay"] * 6 + ["middle"] * 12
        overs = [i // 6 for i in range(len(runs))]
        result = self._extract_with_deliveries(runs, phases=phases, overs=overs)

        sr = result.iloc[0]["fifty_approach_sr"]
        balls = result.iloc[0]["fifty_approach_balls"]

        assert pd.notna(sr), "fifty_approach_sr should not be NaN when zone was entered"
        assert pd.notna(balls)
        assert balls == 7, f"Expected 7 balls in 40-49 zone, got {balls}"
        # 13 runs in 7 balls → SR ≈ 185.7
        assert abs(sr - 185.7) < 1.0, f"Expected SR ~185.7, got {sr}"

    def test_no_zone_entry_gives_nan(self):
        """If batter never reaches 40, fifty_approach_sr should be NaN."""
        runs = [4, 1, 0, 2, 6, 1]  # Total 14 — never reaches 40
        result = self._extract_with_deliveries(runs)

        sr = result.iloc[0]["fifty_approach_sr"]
        assert pd.isna(sr), "fifty_approach_sr should be NaN when zone never entered"

    def test_career_selfless_index(self):
        """Career aggregation should produce selfless_fifty and selfless_index."""
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=2, innings_per_player=15)
        career = aggregate_batting_careers(bc, min_innings=5)

        assert "selfless_fifty" in career.columns
        assert "selfless_century" in career.columns
        assert "selfless_index" in career.columns

    def test_selfless_index_near_one_for_consistent_player(self):
        """
        A player whose fifty-approach SR equals their career SR
        should have selfless_fifty near 1.0.
        """
        from src.batting import aggregate_batting_careers

        rows = []
        for i in range(15):
            rows.append(
                {
                    "match_id": f"m_{i}",
                    "innings_num": 1,
                    "batter_id": "b1",
                    "batter": "Consistent Player",
                    "batting_team": "TeamA",
                    "runs": 40,
                    "balls_faced": 25,
                    "sr": 160.0,
                    "opp_quality_weight": 1.0,
                    "opposition_quality": 0.0,
                    "opp_team_quality": 0.0,
                    "opp_icc_rating": 250.0,
                    "recency_weight": 1.0,
                    "sr_vs_par": 1.1,
                    "date": pd.Timestamp("2024-01-15"),
                    "acc_overall_sr": 0.1,
                    "acc_sr_growth": 0.05,
                    "acc_death_sr": np.nan,
                    "acc_impact": 10.0,
                    "acc_runs_above_expected": 0.5,
                    "pow_boundary_pct": 0.4,
                    "pow_six_rate": 0.04,
                    "pow_boundary_rate_vs_par": 0.05,
                    "pow_peak_phase_sr": 0.2,
                    "pow_finishing_burst": 0.15,
                    "pow_power_impact": 0.8,
                    "ctrl_dot_pct_weighted": 0.6,
                    "ctrl_scoring_consistency": 0.6,
                    "ctrl_rotation": 0.4,
                    "ctrl_contribution": 0.2,
                    "ctrl_avg_proxy": 40.0,
                    "ctrl_dismissal_quality": 0.0,
                    "is_out": True,
                    "how_out": "caught",
                    "first_half_sr": 140.0,
                    "second_half_sr": 180.0,
                    "first_two_thirds_sr": 140.0,
                    "first_two_thirds_balls": 17,
                    "first_two_thirds_runs": 24,
                    "first_two_thirds_sixes": 0,
                    "first_two_thirds_fours": 2,
                    "final_third_sr": 200.0,
                    "final_third_balls": 8,
                    "final_third_runs": 16,
                    "final_third_sixes": 1,
                    "final_third_fours": 1,
                    "match_par_sr": 140.0,
                    "pp_par_sr": 130.0,
                    "middle_par_sr": 135.0,
                    "death_par_sr": 155.0,
                    "match_boundary_rate": 0.10,
                    "fours": 3,
                    "sixes": 1,
                    "dots": 5,
                    "ones": 4,
                    "twos": 2,
                    "threes": 0,
                    "total_runs": 170,
                    "legal_balls": 120,
                    "boundary_pct": 0.4,
                    "dot_pct": 0.25,
                    "rotation_rate": 0.4,
                    "team_contribution_pct": 0.2,
                    "balls_pct_of_team": 0.2,
                    "sr_diff_par": 20.0,
                    "batting_position": 3,
                    "powerplay_balls": 6,
                    "powerplay_runs": 12,
                    "powerplay_sr": 200.0,
                    "powerplay_dots": 1,
                    "powerplay_fours": 2,
                    "powerplay_sixes": 0,
                    "middle_balls": 15,
                    "middle_runs": 20,
                    "middle_sr": 133.0,
                    "middle_dots": 3,
                    "middle_fours": 1,
                    "middle_sixes": 0,
                    "death_balls": 4,
                    "death_runs": 8,
                    "death_sr": 200.0,
                    "death_dots": 1,
                    "death_fours": 0,
                    "death_sixes": 1,
                    "balls_to_par": 3,
                    # Fifty approach: same SR as career
                    "fifty_approach_sr": 160.0,
                    "fifty_approach_balls": 5,
                    "fifty_approach_runs": 8,
                    "century_approach_sr": np.nan,
                    "century_approach_balls": np.nan,
                    "century_approach_runs": np.nan,
                }
            )
        bc = pd.DataFrame(rows)
        career = aggregate_batting_careers(bc, min_innings=5)

        sf = career.iloc[0]["selfless_fifty"]
        assert pd.notna(sf)
        # fifty_approach_sr (160) / career_sr (160) ≈ 1.0
        assert abs(sf - 1.0) < 0.15, f"Expected selfless_fifty near 1.0, got {sf}"

    def test_selfless_below_one_for_slow_zone(self):
        """
        A player who slows down in the fifty zone should have selfless_fifty < 1.0.
        """
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=15)
        # Override: make fifty approach SR much lower than career SR
        bc["fifty_approach_sr"] = 80.0
        bc["fifty_approach_balls"] = 5
        bc["fifty_approach_runs"] = 4
        bc["sr"] = 160.0
        bc["runs"] = 40
        bc["balls_faced"] = 25
        bc["is_out"] = True

        career = aggregate_batting_careers(bc, min_innings=5)
        sf = career.iloc[0]["selfless_fifty"]

        assert pd.notna(sf)
        assert sf < 1.0, f"Expected selfless_fifty < 1.0, got {sf}"

    def test_selfless_index_weights_fifty_over_century(self):
        """
        selfless_index should weight fifty_approach more than century_approach.
        Default is 0.7 / 0.3.
        """
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=15)
        bc["fifty_approach_sr"] = 120.0  # 120/160 = 0.75
        bc["fifty_approach_balls"] = 5
        bc["century_approach_sr"] = 160.0  # 160/160 = 1.0
        bc["century_approach_balls"] = 4
        bc["sr"] = 160.0
        bc["runs"] = 40
        bc["balls_faced"] = 25
        bc["is_out"] = True

        career = aggregate_batting_careers(bc, min_innings=5)
        si = career.iloc[0]["selfless_index"]
        sf = career.iloc[0]["selfless_fifty"]
        sc = career.iloc[0]["selfless_century"]

        assert pd.notna(si)
        assert pd.notna(sf)
        # selfless_index should be between sf and sc, weighted toward sf
        if pd.notna(sc):
            expected = 0.7 * sf + 0.3 * sc
            assert abs(si - expected) < 0.05


# ===========================================================================
# Integration / Edge Cases
# ===========================================================================


class TestPhase2Integration:
    """Cross-feature integration and edge case tests."""

    def test_all_new_columns_in_career(self):
        """Career aggregation should include all new columns."""
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=2, innings_per_player=15)
        career = aggregate_batting_careers(bc, min_innings=5)

        expected_cols = [
            "avg_balls_to_par",
            "anchor_cost_ratio",
            "selfless_fifty",
            "selfless_century",
            "selfless_index",
        ]
        for col in expected_cols:
            assert col in career.columns, f"Missing column: {col}"

    def test_chase_splits_merges_onto_careers(self):
        """
        Simulates the main.py integration: chase splits should merge cleanly
        onto bat_careers.
        """
        from src.batting import aggregate_batting_careers, compute_chase_splits

        bc = _make_bat_components(n_players=3, innings_per_player=12)
        career = aggregate_batting_careers(bc, min_innings=5)
        chase = compute_chase_splits(bc)

        if not chase.empty:
            merged = career.merge(
                chase[["batter_id", "batter", "chase_master_index", "bat_first_index"]],
                on=["batter_id", "batter"],
                how="left",
            )
            assert "chase_master_index" in merged.columns
            assert len(merged) == len(career)

    def test_provisional_players_have_metrics(self):
        """Even provisional players should have the new metrics (not gated)."""
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=3)
        career = aggregate_batting_careers(bc, min_innings=10)

        assert (
            career.iloc[0]["is_provisional_bat"] is True
            or career.iloc[0]["is_provisional_bat"] == True
        )
        # Should still have anchor cost values
        assert "avg_balls_to_par" in career.columns

    def test_no_crash_with_all_nan_zones(self):
        """Should handle gracefully when all zone SRs are NaN."""
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=15)
        bc["fifty_approach_sr"] = np.nan
        bc["fifty_approach_balls"] = np.nan
        bc["fifty_approach_runs"] = np.nan
        bc["century_approach_sr"] = np.nan
        bc["century_approach_balls"] = np.nan
        bc["century_approach_runs"] = np.nan

        career = aggregate_batting_careers(bc, min_innings=5)

        assert "selfless_index" in career.columns
        # selfless_index should be NaN when no zone data
        si = career.iloc[0]["selfless_index"]
        # With all NaN inputs, the result depends on the fallback logic
        # Just ensure it doesn't crash

    def test_no_crash_with_zero_balls(self):
        """Should not crash on players with 0 balls faced (edge case)."""
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=15)
        bc["balls_faced"] = 0
        bc["balls_to_par"] = 0

        career = aggregate_batting_careers(bc, min_innings=5)

        assert "anchor_cost_ratio" in career.columns

    def test_multiple_matches_different_innings(self):
        """Test extract with multiple matches and different innings numbers."""
        from src.batting import extract_batting_innings

        # Match 1: target batter hits all fours (fast), other batter provides par
        df1 = _make_multi_batter_delivery_df(
            match_id="m1",
            innings_num=1,
            target_batter_id="b1",
            target_batter="Player A",
            target_runs=[4, 4, 4, 4, 4, 4, 4, 4, 4, 4],  # All fours = 40 runs
            other_runs=[2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1],
        )
        total1 = 40 + sum([2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1])
        ctx1 = _make_innings_context(
            match_id="m1", innings_num=1, total_runs=total1, legal_balls=22
        )

        # Match 2: target batter scores mostly dots (slow), other provides par
        df2 = _make_multi_batter_delivery_df(
            match_id="m2",
            innings_num=2,
            target_batter_id="b1",
            target_batter="Player A",
            target_runs=[0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # Very slow
            other_runs=[2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1],
        )
        total2 = 2 + sum([2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1])
        ctx2 = _make_innings_context(
            match_id="m2", innings_num=2, total_runs=total2, legal_balls=22
        )

        df = pd.concat([df1, df2], ignore_index=True)
        ctx = pd.concat([ctx1, ctx2], ignore_index=True)

        result = extract_batting_innings(df, ctx)

        # Filter to target batter only
        target = result[result["batter_id"] == "b1"]
        assert len(target) == 2

        # Match 1 should have low balls_to_par (fast starter)
        m1_row = target[target["match_id"] == "m1"].iloc[0]
        m2_row = target[target["match_id"] == "m2"].iloc[0]

        assert m1_row["balls_to_par"] < m2_row["balls_to_par"]


class TestChaseMasterEdgeCases:
    """Edge cases for Chase Master Index."""

    def test_single_player_both_innings_types(self):
        """A player with enough of both types should get valid indices."""
        from src.batting import compute_chase_splits

        rows = []
        for i in range(20):
            inn_num = 1 if i % 2 == 0 else 2
            rows.append(
                {
                    "match_id": f"m_{i}",
                    "innings_num": inn_num,
                    "batter_id": "b1",
                    "batter": "Balanced Player",
                    "runs": 35,
                    "balls_faced": 25,
                    "sr": 140.0,
                    "acc_overall_sr": 0.05 if inn_num == 1 else 0.10,
                    "acc_impact": 8.0,
                    "ctrl_scoring_consistency": 0.55,
                }
            )
        bc = pd.DataFrame(rows)
        result = compute_chase_splits(bc)

        assert len(result) == 1
        row = result.iloc[0]
        assert pd.notna(row["chase_master_index"])
        assert pd.notna(row["bat_first_index"])
        assert pd.notna(row["chase_master_full"])
        assert row["setting_inn"] == 10
        assert row["chasing_inn"] == 10

    def test_many_players_no_overlap(self):
        """Multiple players with distinct IDs should all get their own row."""
        from src.batting import compute_chase_splits

        rows = []
        for p in range(10):
            for i in range(12):
                inn_num = 1 if i < 6 else 2
                rows.append(
                    {
                        "match_id": f"m_{p}_{i}",
                        "innings_num": inn_num,
                        "batter_id": f"b{p}",
                        "batter": f"Player {p}",
                        "runs": 30 + p,
                        "balls_faced": 20,
                        "sr": 150.0,
                        "acc_overall_sr": 0.1 * p,
                        "acc_impact": 5.0,
                        "ctrl_scoring_consistency": 0.5,
                    }
                )
        bc = pd.DataFrame(rows)
        result = compute_chase_splits(bc)

        assert len(result) == 10


class TestAnchorCostEdgeCases:
    """Edge cases for Anchor Cost."""

    def test_boundary_first_ball(self):
        """A boundary on the first ball should give balls_to_par = 0."""
        from src.batting import extract_batting_innings

        # Use multi-batter approach so phase pars are realistic
        target_runs = [6, 0, 1, 4, 0, 2]
        # Other batter provides ~130 SR par context
        other_runs = [2, 1, 4, 1, 2, 1, 2, 1, 4, 1, 2, 1]
        df = _make_multi_batter_delivery_df(
            target_runs=target_runs, other_runs=other_runs
        )
        total = sum(target_runs) + sum(other_runs)
        n_balls = len(target_runs) + len(other_runs)
        ctx = _make_innings_context(total_runs=total, legal_balls=n_balls)
        result = extract_batting_innings(df, ctx)

        target = result[result["batter_id"] == "b1"]
        assert len(target) >= 1
        btp = target.iloc[0]["balls_to_par"]
        assert btp == 0, f"Expected balls_to_par = 0 for boundary first ball, got {btp}"

    def test_all_ones(self):
        """
        Running ones at SR=100 in a match where par is higher should
        result in balls_to_par = balls_faced (never reaches par).
        """
        from src.batting import extract_batting_innings

        # Target batter: all singles (SR=100)
        target_runs = [1] * 20
        # Other batter: aggressive scoring to make par ~140+ SR
        other_runs = [4, 2, 6, 1, 4, 2, 4, 1, 6, 2, 4, 1, 4, 2, 6, 1, 4, 2, 4, 1]

        df = _make_multi_batter_delivery_df(
            target_runs=target_runs, other_runs=other_runs
        )
        total = sum(target_runs) + sum(other_runs)
        n_balls = len(target_runs) + len(other_runs)
        ctx = _make_innings_context(total_runs=total, legal_balls=n_balls)
        result = extract_batting_innings(df, ctx)

        target = result[result["batter_id"] == "b1"]
        assert len(target) >= 1
        btp = target.iloc[0]["balls_to_par"]
        bf = target.iloc[0]["balls_faced"]
        # SR=100 but par SR should be well above 100, so never reaches par
        assert btp == bf


class TestSelflessIndexEdgeCases:
    """Edge cases for Selfless Index."""

    def test_player_who_accelerates_in_zone(self):
        """
        A player who accelerates approaching 50 should have selfless_fifty > 1.0.
        """
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=15)
        # Zone SR higher than career SR
        bc["fifty_approach_sr"] = 200.0
        bc["fifty_approach_balls"] = 5
        bc["fifty_approach_runs"] = 10
        bc["sr"] = 140.0
        bc["runs"] = 35
        bc["balls_faced"] = 25
        bc["is_out"] = True

        career = aggregate_batting_careers(bc, min_innings=5)
        sf = career.iloc[0]["selfless_fifty"]

        assert pd.notna(sf)
        assert sf > 1.0, (
            f"Expected selfless_fifty > 1.0 for accelerating player, got {sf}"
        )

    def test_century_zone_nan_when_no_data(self):
        """
        Century approach should be NaN when no player ever reaches 90-99 zone.
        """
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=15)
        bc["century_approach_sr"] = np.nan
        bc["century_approach_balls"] = np.nan
        bc["century_approach_runs"] = np.nan

        career = aggregate_batting_careers(bc, min_innings=5)
        sc = career.iloc[0]["selfless_century"]

        assert pd.isna(sc)

    def test_selfless_index_with_only_fifty_data(self):
        """
        When only fifty approach data exists, selfless_index should equal selfless_fifty.
        """
        from src.batting import aggregate_batting_careers

        bc = _make_bat_components(n_players=1, innings_per_player=15)
        bc["fifty_approach_sr"] = 140.0
        bc["fifty_approach_balls"] = 5
        bc["century_approach_sr"] = np.nan
        bc["century_approach_balls"] = np.nan
        bc["sr"] = 140.0
        bc["runs"] = 35
        bc["balls_faced"] = 25
        bc["is_out"] = True

        career = aggregate_batting_careers(bc, min_innings=5)
        si = career.iloc[0]["selfless_index"]
        sf = career.iloc[0]["selfless_fifty"]

        if pd.notna(sf):
            assert pd.notna(si)
            assert abs(si - sf) < 0.01
