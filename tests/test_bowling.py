"""
Unit tests for the bowling module: spell extraction, component computation,
run-distribution entropy, career aggregation, and the z-score normalisation
pipeline.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bowling import (
    ACC_WEIGHTS,
    CTRL_WEIGHTS,
    MIN_PHASE_BALLS,
    THREAT_WEIGHTS,
    _zscore_series,
    aggregate_bowling_careers,
    compute_bowling_components,
    compute_run_distribution_entropy,
    extract_bowling_spells,
)
from src.context import build_full_context

# ---------------------------------------------------------------------------
# Helper: build innings context from deliveries
# ---------------------------------------------------------------------------


def _get_innings_ctx(df):
    """Convenience: run build_full_context and return innings_ctx."""
    innings_ctx, _ = build_full_context(df)
    return innings_ctx


# ---------------------------------------------------------------------------
# _zscore_series (bowling copy — same function, separate module)
# ---------------------------------------------------------------------------


class TestBowlingZscoreSeries:
    """Tests for the bowling module's _zscore_series()."""

    def test_basic_zscore(self):
        """Z-score of [1, 2, 3] should have mean 0 and std 1."""
        s = pd.Series([1.0, 2.0, 3.0])
        result = _zscore_series(s)
        assert result.mean() == pytest.approx(0.0, abs=1e-10)
        assert result.std() == pytest.approx(1.0, abs=1e-6)

    def test_all_same_returns_zeros(self):
        """If all values are the same, z-scores should be 0."""
        s = pd.Series([5.0, 5.0, 5.0])
        result = _zscore_series(s)
        assert (result == 0.0).all()

    def test_nan_stays_nan(self):
        """NaN values should remain NaN after z-scoring."""
        s = pd.Series([1.0, np.nan, 3.0])
        result = _zscore_series(s)
        assert pd.isna(result.iloc[1])
        assert pd.notna(result.iloc[0])


# ---------------------------------------------------------------------------
# extract_bowling_spells
# ---------------------------------------------------------------------------


class TestExtractBowlingSpells:
    """Tests for extract_bowling_spells()."""

    def test_basic_extraction(self, synthetic_deliveries_simple):
        """Should produce one row per (match, innings, bowler)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        # M001 Inn 1: Bowler1 (overs 0,2), Bowler2 (over 1) → 2 bowlers
        # M001 Inn 2: Bowler3 (overs 0,1) → 1 bowler
        # M002 Inn 1: Bowler1 (over 0) → 1 bowler
        # M002 Inn 2: Bowler3 (over 0) → 1 bowler
        # Total: 5 spells
        assert len(result) == 5

    def test_bowler1_spell_m001(self, synthetic_deliveries_simple):
        """Bowler1 in M001 Inn1 bowls overs 0 and 2."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ]
        assert len(b1_m001) == 1
        row = b1_m001.iloc[0]

        # Over 0: 1,0,4,1,0,6 = 12 runs, 6 legal balls
        # Over 2: 0,1,0,0,1,0 = 2 runs, 6 legal balls
        # Total: 14 runs, 12 legal balls, 2 overs
        assert row["legal_balls"] == 12
        assert row["runs_conceded"] == 14
        assert row["overs_bowled"] == pytest.approx(2.0)

    def test_bowler1_economy_m001(self, synthetic_deliveries_simple):
        """Bowler1's economy in M001 should be runs / overs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]

        # 14 runs / 2 overs = 7.0
        assert b1_m001["economy"] == pytest.approx(7.0)

    def test_bowler2_spell_m001(self, synthetic_deliveries_simple):
        """Bowler2 in M001 Inn1 bowls over 1 only."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        b2_m001 = result[
            (result["bowler_id"] == "bowl2")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ]
        assert len(b2_m001) == 1
        row = b2_m001.iloc[0]

        # Over 1: 4,4,1,0,1,2 = 12 runs, 6 legal balls, 1 wicket
        assert row["legal_balls"] == 6
        assert row["runs_conceded"] == 12
        assert row["wickets"] == 1

    def test_wicket_count(self, synthetic_deliveries_simple):
        """Wicket counts should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        # Bowler2 in M001 Inn1: 1 wicket (ball 5 of over 1)
        b2_m001 = result[
            (result["bowler_id"] == "bowl2")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b2_m001["wickets"] == 1

        # Bowler1 in M001 Inn1: 0 wickets
        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b1_m001["wickets"] == 0

    def test_dot_ball_count(self, synthetic_deliveries_simple):
        """Dot balls (bowler) should be counted per spell."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        # Bowler1 M001 Inn1:
        # Over 0: 1,0,4,1,0,6 → 2 bowler dots (balls where total_runs=0)
        # Over 2: 0,1,0,0,1,0 → 4 bowler dots
        # Total: 6 dots
        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b1_m001["dots_bowler"] == 6

    def test_dot_pct(self, synthetic_deliveries_simple):
        """Dot pct should be dots / legal_balls."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]

        # 6 dots / 12 legal balls = 0.5
        assert b1_m001["dot_pct"] == pytest.approx(0.5)

    def test_bowling_strike_rate(self, synthetic_deliveries_simple):
        """Bowling SR = legal_balls / wickets (NaN if 0 wickets)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        # Bowler2 M001: 6 balls / 1 wicket = 6.0
        b2_m001 = result[
            (result["bowler_id"] == "bowl2")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b2_m001["strike_rate_bowl"] == pytest.approx(6.0)

        # Bowler1 M001: 0 wickets → NaN
        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert pd.isna(b1_m001["strike_rate_bowl"])

    def test_boundary_counts(self, synthetic_deliveries_simple):
        """Fours and sixes conceded should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        # Bowler1 M001 Inn1:
        # Over 0: 1,0,4,1,0,6 → 1 four, 1 six
        # Over 2: 0,1,0,0,1,0 → 0 fours, 0 sixes
        # Total: 1 four, 1 six
        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b1_m001["fours_conceded"] == 1
        assert b1_m001["sixes_conceded"] == 1

    def test_boundary_pct_conceded(self, synthetic_deliveries_simple):
        """boundary_pct_conceded = (fours*4 + sixes*6) / runs_conceded."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]

        # (1*4 + 1*6) / 14 = 10/14 ≈ 0.714
        expected = (1 * 4 + 1 * 6) / 14
        assert b1_m001["boundary_pct_conceded"] == pytest.approx(expected, rel=1e-3)

    def test_extras_per_over_zero_when_no_extras(self, synthetic_deliveries_simple):
        """extras_per_over should be 0 when no wides/noballs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        # synthetic_deliveries_simple has no extras
        for _, row in result.iterrows():
            assert row["extras_per_over"] == pytest.approx(0.0)

    def test_economy_vs_others(self, synthetic_deliveries_simple):
        """economy_vs_others should compare to other bowlers in the same innings."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        # M001 Inn1: Bowler1 econ=7.0, Bowler2 econ=12.0
        # Bowler1 others_econ = 12.0, economy_vs_others = 7.0 - 12.0 = -5.0
        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b1_m001["economy_vs_others"] == pytest.approx(-5.0)

        # Bowler2 others_econ = 7.0, economy_vs_others = 12.0 - 7.0 = 5.0
        b2_m001 = result[
            (result["bowler_id"] == "bowl2")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b2_m001["economy_vs_others"] == pytest.approx(5.0)

    def test_has_match_context_columns(self, synthetic_deliveries_simple):
        """Extracted spells should carry match context columns."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        assert "match_par_sr" in result.columns
        assert "match_par_rr" in result.columns
        assert "match_boundary_rate" in result.columns
        assert "match_dot_pct" in result.columns

    def test_economy_ratio_par(self, synthetic_deliveries_simple):
        """economy_ratio_par = economy / match_par_rr."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        assert "economy_ratio_par" in result.columns
        # All values should be positive
        assert (result["economy_ratio_par"] > 0).all()

    def test_economy_vs_par_sign(self, synthetic_deliveries_simple):
        """economy_vs_par should be positive when bowler is more expensive than par."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        for _, row in result.iterrows():
            if row["economy"] > row["match_par_rr"]:
                assert row["economy_vs_par"] > 0
            elif row["economy"] < row["match_par_rr"]:
                assert row["economy_vs_par"] < 0


# ---------------------------------------------------------------------------
# Phase-specific stats in bowling spells
# ---------------------------------------------------------------------------


class TestBowlingPhaseStats:
    """Tests for phase-level breakdown in bowling spells."""

    def test_all_phases_present(self, synthetic_deliveries_with_phases):
        """Multi-phase match should have stats for PP, middle, death."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)

        # BowlerP bowls in all three phases
        bowlP = result[result["bowler_id"] == "bowlP"]
        assert len(bowlP) == 1
        row = bowlP.iloc[0]

        # All phases should have valid data (12 balls each ≥ MIN_PHASE_BALLS)
        assert pd.notna(row["powerplay_economy"])
        assert pd.notna(row["middle_economy"])
        assert pd.notna(row["death_economy"])

    def test_powerplay_runs(self, synthetic_deliveries_with_phases):
        """PP runs for BowlerP should match hand calculation."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)

        bowlP = result[result["bowler_id"] == "bowlP"].iloc[0]
        # Over 0: 1+1+4+0+1+1 = 8, Over 1: 0+6+0+1+4+0 = 11
        assert bowlP["powerplay_runs"] == 19
        assert bowlP["powerplay_legal_balls"] == 12

    def test_powerplay_economy(self, synthetic_deliveries_with_phases):
        """PP economy = PP runs / PP overs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)

        bowlP = result[result["bowler_id"] == "bowlP"].iloc[0]
        # 19 runs / 2 overs = 9.5
        assert bowlP["powerplay_economy"] == pytest.approx(9.5)

    def test_middle_overs_economy(self, synthetic_deliveries_with_phases):
        """Middle overs economy should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)

        bowlP = result[result["bowler_id"] == "bowlP"].iloc[0]
        # Middle: 11 runs / 2 overs = 5.5
        assert bowlP["middle_economy"] == pytest.approx(5.5)

    def test_death_overs_economy(self, synthetic_deliveries_with_phases):
        """Death overs economy should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)

        bowlP = result[result["bowler_id"] == "bowlP"].iloc[0]
        # Death: 44 runs / 2 overs = 22.0
        assert bowlP["death_economy"] == pytest.approx(22.0)

    def test_phase_dots(self, synthetic_deliveries_with_phases):
        """Phase dot counts should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)

        bowlP = result[result["bowler_id"] == "bowlP"].iloc[0]
        # PP Over 0: 1,1,4,0,1,1 → 1 dot; Over 1: 0,6,0,1,4,0 → 3 dots → 4
        assert bowlP["powerplay_dots"] == 4
        # Middle Over 8: 1,1,0,2,1,0 → 2 dots; Over 9: 0,1,0,0,4,1 → 3 dots → 5
        assert bowlP["middle_dots"] == 5
        # Death Over 18: 4,6,1,4,6,2 → 0; Over 19: 6,0,4,4,6,1 → 1 → 1
        assert bowlP["death_dots"] == 1

    def test_phase_dot_pct(self, synthetic_deliveries_with_phases):
        """Phase dot % should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)

        bowlP = result[result["bowler_id"] == "bowlP"].iloc[0]
        assert bowlP["powerplay_dot_pct"] == pytest.approx(4 / 12, rel=1e-3)
        assert bowlP["middle_dot_pct"] == pytest.approx(5 / 12, rel=1e-3)
        assert bowlP["death_dot_pct"] == pytest.approx(1 / 12, rel=1e-3)

    def test_single_phase_match_has_nan_for_other_phases(
        self, synthetic_deliveries_simple
    ):
        """Bowlers in matches with only PP overs should have NaN for mid/death."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]

        assert pd.notna(b1_m001["powerplay_economy"])
        assert pd.isna(b1_m001.get("middle_economy", np.nan))
        assert pd.isna(b1_m001.get("death_economy", np.nan))

    def test_min_phase_balls_threshold(self):
        """Phase economy should be NaN if fewer than MIN_PHASE_BALLS bowled."""
        from tests.conftest import _build_over, _make_delivery

        rows = []
        # PP over: 6 legal balls
        rows += _build_over(
            "M_SHORT_BOWL",
            1,
            "TBat",
            "TBowl",
            0,
            "BatA",
            "bata",
            "ShortBowler",
            "sbowl",
            "BatB",
            "batb",
            1,
            [1, 0, 4, 0, 1, 2],
        )

        # Death: only 3 balls by ShortBowler (< MIN_PHASE_BALLS=6)
        for ball_i, br in enumerate([4, 0, 6]):
            d = _make_delivery(
                match_id="M_SHORT_BOWL",
                innings_num=1,
                batting_team="TBat",
                bowling_team="TBowl",
                over=18,
                ball_idx=ball_i,
                batter="BatA",
                batter_id="bata",
                bowler="ShortBowler",
                bowler_id="sbowl",
                non_striker="BatB",
                non_striker_id="batb",
                batting_position=1,
                batter_runs=br,
                total_runs=br,
                is_four=(br == 4),
                is_six=(br == 6),
                is_dot_batter=(br == 0),
                is_dot_bowler=(br == 0),
                phase="death",
                team_score_before=8 + ball_i * 3,
            )
            rows.append(d)

        # Fill remaining death balls with a different bowler
        for ball_i in range(3, 6):
            d = _make_delivery(
                match_id="M_SHORT_BOWL",
                innings_num=1,
                batting_team="TBat",
                bowling_team="TBowl",
                over=18,
                ball_idx=ball_i,
                batter="BatA",
                batter_id="bata",
                bowler="OtherBowler",
                bowler_id="obowl",
                non_striker="BatB",
                non_striker_id="batb",
                batting_position=1,
                batter_runs=1,
                total_runs=1,
                is_dot_batter=False,
                is_dot_bowler=False,
                phase="death",
                team_score_before=18 + ball_i,
            )
            rows.append(d)

        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        result = extract_bowling_spells(df, innings_ctx)

        sbowl = result[result["bowler_id"] == "sbowl"].iloc[0]
        # ShortBowler has 3 death balls (< MIN_PHASE_BALLS=6) → death_economy NaN
        assert sbowl["death_legal_balls"] == 3
        assert pd.isna(sbowl["death_economy"])
        # PP has 6 balls → should be valid
        assert pd.notna(sbowl["powerplay_economy"])


# ---------------------------------------------------------------------------
# compute_run_distribution_entropy
# ---------------------------------------------------------------------------


class TestRunDistributionEntropy:
    """Tests for compute_run_distribution_entropy()."""

    def test_basic_entropy(self, synthetic_deliveries_simple):
        """Should produce one row per (match, innings, bowler) with run_entropy."""
        result = compute_run_distribution_entropy(synthetic_deliveries_simple)

        assert "run_entropy" in result.columns
        assert len(result) > 0

    def test_all_dots_zero_entropy(self):
        """All dot balls should have 0 entropy (one value, probability 1)."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_ALLDOTS",
            1,
            "T1",
            "T2",
            0,
            "Bat1",
            "b1",
            "DotBowler",
            "dbowl",
            "Bat2",
            "b2",
            1,
            [0, 0, 0, 0, 0, 0],
        )
        df = pd.DataFrame(rows)
        result = compute_run_distribution_entropy(df)

        dbowl = result[result["bowler_id"] == "dbowl"]
        assert len(dbowl) == 1
        assert dbowl.iloc[0]["run_entropy"] == pytest.approx(0.0, abs=1e-10)

    def test_all_same_nonzero_zero_entropy(self):
        """All same non-zero runs should have 0 entropy."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_ALLONES",
            1,
            "T1",
            "T2",
            0,
            "Bat1",
            "b1",
            "SingleBowler",
            "sbowl",
            "Bat2",
            "b2",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        df = pd.DataFrame(rows)
        result = compute_run_distribution_entropy(df)

        sbowl = result[result["bowler_id"] == "sbowl"]
        assert sbowl.iloc[0]["run_entropy"] == pytest.approx(0.0, abs=1e-10)

    def test_uniform_distribution_max_entropy(self):
        """Uniform distribution should have higher entropy than concentrated."""
        from tests.conftest import _build_over

        # Concentrated: 5 dots + 1 six
        rows_conc = _build_over(
            "M_CONC",
            1,
            "T1",
            "T2",
            0,
            "Bat1",
            "b1",
            "ConcBowler",
            "cbowl",
            "Bat2",
            "b2",
            1,
            [0, 0, 0, 0, 0, 6],
        )
        # Uniform-ish: 0, 1, 2, 3, 4, 6
        rows_unif = _build_over(
            "M_UNIF",
            1,
            "T1",
            "T2",
            0,
            "Bat1",
            "b1",
            "UnifBowler",
            "ubowl",
            "Bat2",
            "b2",
            1,
            [0, 1, 2, 3, 4, 6],
        )

        df_conc = pd.DataFrame(rows_conc)
        df_unif = pd.DataFrame(rows_unif)

        ent_conc = compute_run_distribution_entropy(df_conc)
        ent_unif = compute_run_distribution_entropy(df_unif)

        conc_val = ent_conc.iloc[0]["run_entropy"]
        unif_val = ent_unif.iloc[0]["run_entropy"]

        assert unif_val > conc_val

    def test_entropy_non_negative(self, synthetic_deliveries_simple):
        """Entropy should always be ≥ 0."""
        result = compute_run_distribution_entropy(synthetic_deliveries_simple)
        assert (result["run_entropy"] >= 0).all()


# ---------------------------------------------------------------------------
# compute_bowling_components
# ---------------------------------------------------------------------------


class TestComputeBowlingComponents:
    """Tests for compute_bowling_components()."""

    def test_adds_component_columns(self, synthetic_deliveries_simple):
        """Should add acc_, ctrl_, threat_ columns."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        acc_cols = [c for c in result.columns if c.startswith("acc_")]
        ctrl_cols = [c for c in result.columns if c.startswith("ctrl_")]
        threat_cols = [c for c in result.columns if c.startswith("threat_")]

        assert len(acc_cols) >= 3
        assert len(ctrl_cols) >= 3
        assert len(threat_cols) >= 3

    def test_acc_economy_vs_par_sign(self, synthetic_deliveries_simple):
        """acc_economy_vs_par should be positive when economy < par (good)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        for _, row in result.iterrows():
            if row["economy_ratio_par"] < 1.0:
                # Better than par → positive component
                assert row["acc_economy_vs_par"] > 0
            elif row["economy_ratio_par"] > 1.0:
                # Worse than par → negative component
                assert row["acc_economy_vs_par"] < 0

    def test_acc_dot_pct_range(self, synthetic_deliveries_simple):
        """acc_dot_pct should be in [0, 1]."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        assert (result["acc_dot_pct"] >= 0).all()
        assert (result["acc_dot_pct"] <= 1).all()

    def test_acc_extras_penalty_nonpositive(self, synthetic_deliveries_simple):
        """acc_extras_penalty should be ≤ 0 (negated extras per over)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        # No extras in our simple data → should be 0
        assert (result["acc_extras_penalty"] <= 0.001).all()

    def test_acc_boundary_penalty_nonpositive(self, synthetic_deliveries_simple):
        """acc_boundary_penalty should be ≤ 0 (negated boundary % conceded)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        assert (result["acc_boundary_penalty"] <= 0.001).all()

    def test_ctrl_entropy_nonpositive(self, synthetic_deliveries_simple):
        """ctrl_entropy should be ≤ 0 (negated Shannon entropy)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        assert (result["ctrl_entropy"] <= 0.001).all()

    def test_ctrl_vs_others_sign(self, synthetic_deliveries_simple):
        """ctrl_vs_others should be positive when better than teammates."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        # Bowler1 M001: economy_vs_others = -5.0, so ctrl_vs_others = +5.0
        b1 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b1["ctrl_vs_others"] > 0

        # Bowler2 M001: economy_vs_others = +5.0, so ctrl_vs_others = -5.0
        b2 = result[
            (result["bowler_id"] == "bowl2")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b2["ctrl_vs_others"] < 0

    def test_threat_wickets_value(self, synthetic_deliveries_simple):
        """threat_wickets should equal the spell wicket count."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        b2_m001 = result[
            (result["bowler_id"] == "bowl2")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b2_m001["threat_wickets"] == 1

    def test_threat_sr_nan_when_no_wickets(self, synthetic_deliveries_simple):
        """threat_sr should be NaN when no wickets taken."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        b1_m001 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert pd.isna(b1_m001["threat_sr"])

    def test_threat_sr_negative_when_has_wickets(self, synthetic_deliveries_simple):
        """threat_sr should be negative (inverted SR) when wickets taken."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        b2_m001 = result[
            (result["bowler_id"] == "bowl2")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        assert b2_m001["threat_sr"] < 0  # negated SR = -6.0

    def test_threat_dots_range(self, synthetic_deliveries_simple):
        """threat_dots should be in [0, 1]."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        assert (result["threat_dots"] >= 0).all()
        assert (result["threat_dots"] <= 1).all()

    def test_threat_pressure_sign(self, synthetic_deliveries_simple):
        """threat_pressure should be positive when better econ than teammates."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        result = compute_bowling_components(spells, entropy)

        b1 = result[
            (result["bowler_id"] == "bowl1")
            & (result["match_id"] == "M001")
            & (result["innings_num"] == 1)
        ].iloc[0]
        # Bowler1 has lower economy → positive pressure
        assert b1["threat_pressure"] > 0

    def test_ctrl_phase_consistency_with_multi_phase(
        self, synthetic_deliveries_with_phases
    ):
        """Phase consistency should reflect variation in economy across phases."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        spells = extract_bowling_spells(synthetic_deliveries_with_phases, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_with_phases)
        result = compute_bowling_components(spells, entropy)

        bowlP = result[result["bowler_id"] == "bowlP"].iloc[0]
        # BowlerP: PP econ=9.5, mid econ=5.5, death econ=22.0
        # High variance → very negative consistency
        assert bowlP["ctrl_phase_consistency"] < 0


# ---------------------------------------------------------------------------
# aggregate_bowling_careers
# ---------------------------------------------------------------------------


class TestAggregateBowlingCareers:
    """Tests for aggregate_bowling_careers()."""

    def test_basic_aggregation(self, synthetic_deliveries_simple):
        """Should produce one row per bowler."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        bowler_ids = set(result["bowler_id"])
        assert "bowl1" in bowler_ids
        assert "bowl2" in bowler_ids
        assert "bowl3" in bowler_ids

    def test_career_total_wickets(self, synthetic_deliveries_simple):
        """Career total wickets should be summed across all spells."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler2: 1 wicket in M001 only (doesn't appear in M002)
        b2 = result[result["bowler_id"] == "bowl2"].iloc[0]
        assert b2["total_wickets"] == 1

        # Bowler1: 0 wickets in both matches
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        assert b1["total_wickets"] == 0

    def test_career_total_legal_balls(self, synthetic_deliveries_simple):
        """Career total legal balls should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler1: M001 (12 balls) + M002 (6 balls) = 18
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        assert b1["total_legal_balls"] == 18

    def test_career_economy(self, synthetic_deliveries_simple):
        """Career economy = total_runs_conceded / total_overs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler1: M001: 14 runs, M002: 11 runs = 25 runs / 3 overs ≈ 8.33
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        expected_econ = b1["total_runs_conceded"] / b1["total_overs"]
        assert b1["career_economy"] == pytest.approx(expected_econ, rel=1e-3)

    def test_career_sr_bowl(self, synthetic_deliveries_simple):
        """Career bowling SR = total_legal_balls / total_wickets."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler2: 6 balls / 1 wicket = 6.0
        b2 = result[result["bowler_id"] == "bowl2"].iloc[0]
        assert b2["career_sr_bowl"] == pytest.approx(6.0)

        # Bowler1: 0 wickets → 999.0
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        assert b1["career_sr_bowl"] == pytest.approx(999.0)

    def test_match_count(self, synthetic_deliveries_simple):
        """matches should be the number of distinct matches bowled in."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler1 bowls in M001 and M002
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        assert b1["matches"] == 2

        # Bowler2 only bowls in M001
        b2 = result[result["bowler_id"] == "bowl2"].iloc[0]
        assert b2["matches"] == 1

    def test_provisional_flag(self, synthetic_deliveries_simple):
        """Bowlers with fewer than min_overs should be flagged provisional."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)

        # With min_overs=1, everyone with ≥ 1 over should be non-provisional
        result_low = aggregate_bowling_careers(
            comps, synthetic_deliveries_simple, min_overs=1
        )
        assert not result_low["is_provisional_bowl"].any()

        # With min_overs=100, everyone should be provisional
        result_high = aggregate_bowling_careers(
            comps, synthetic_deliveries_simple, min_overs=100
        )
        assert result_high["is_provisional_bowl"].all()

    def test_has_raw_composites(self, synthetic_deliveries_simple):
        """Should produce raw_accuracy, raw_control, raw_threat columns."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        assert "raw_accuracy" in result.columns
        assert "raw_control" in result.columns
        assert "raw_threat" in result.columns

    def test_raw_composites_are_finite(self, synthetic_deliveries_simple):
        """Raw composite scores should be finite (not NaN or inf)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        for col in ["raw_accuracy", "raw_control", "raw_threat"]:
            assert np.isfinite(result[col]).all(), f"{col} has non-finite values"

    def test_zscore_composites_have_mean_near_zero(self, synthetic_deliveries_simple):
        """Z-score weighted composites should have mean near 0."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        for col in ["raw_accuracy", "raw_control", "raw_threat"]:
            mean = result[col].mean()
            assert abs(mean) < 1.0, f"{col} mean={mean:.3f} is too far from 0"

    def test_more_economical_bowler_ranks_higher_on_accuracy(
        self, synthetic_deliveries_simple
    ):
        """Bowler with better economy should have higher raw_accuracy."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler1 career econ ≈ 8.33, Bowler2 career econ = 12.0
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        b2 = result[result["bowler_id"] == "bowl2"].iloc[0]
        assert b1["raw_accuracy"] > b2["raw_accuracy"]

    def test_wicket_taker_has_higher_threat_wickets_component(
        self, synthetic_deliveries_simple
    ):
        """Bowler who takes wickets should have higher threat_wickets_mean."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler2 has 1 wicket, Bowler1 has 0
        # The wickets *component* should be higher for b2, even if the overall
        # raw_threat composite isn't (because b1's superior dot% and pressure
        # components can outweigh the wicket advantage in a z-score framework).
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        b2 = result[result["bowler_id"] == "bowl2"].iloc[0]
        assert b2["threat_wickets_mean"] > b1["threat_wickets_mean"]

    def test_bowled_lbw_pct(self, synthetic_deliveries_simple):
        """bowled_lbw_pct should be fraction of wickets that are bowled/lbw."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        # Bowler2 has 1 wicket, kind="bowled" → bowled_lbw_pct = 1.0
        b2 = result[result["bowler_id"] == "bowl2"].iloc[0]
        assert b2["bowled_lbw_pct"] == pytest.approx(1.0)

        # Bowler1 has 0 wickets → bowled_lbw_pct = 0.0
        b1 = result[result["bowler_id"] == "bowl1"].iloc[0]
        assert b1["bowled_lbw_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Career aggregation with multi-match fixture
# ---------------------------------------------------------------------------


class TestBowlingCareerMultiMatch:
    """Tests using the synthetic_multi_match_career fixture (15 matches)."""

    def test_career_has_correct_match_count(self, synthetic_multi_match_career):
        """BowlStar should have 15 matches."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        spells = extract_bowling_spells(synthetic_multi_match_career, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_multi_match_career)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_multi_match_career)

        star = result[result["bowler_id"] == "bowl_star"]
        assert len(star) == 1
        assert star.iloc[0]["matches"] == 15

    def test_non_provisional_with_enough_overs(self, synthetic_multi_match_career):
        """BowlStar with 30 overs should not be provisional with min_overs=10."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        spells = extract_bowling_spells(synthetic_multi_match_career, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_multi_match_career)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(
            comps, synthetic_multi_match_career, min_overs=10
        )

        star = result[result["bowler_id"] == "bowl_star"].iloc[0]
        # BowlStar bowls in both innings per match: 15 matches × 2 overs = 30
        assert star["total_overs"] == pytest.approx(30.0)
        assert star["is_provisional_bowl"] == False

    def test_career_total_wickets_sum(self, synthetic_multi_match_career):
        """Total wickets should match known fixtures."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        spells = extract_bowling_spells(synthetic_multi_match_career, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_multi_match_career)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_multi_match_career)

        star = result[result["bowler_id"] == "bowl_star"].iloc[0]
        # bowl_figures wkts: 1,0,2,0,0,1,1,0,1,0,0,1,0,1,0
        # _build_over only supports a single wicket per over via wicket_on_ball,
        # so the match with wkts=2 only produces 1 actual wicket in the data.
        # Actual wickets placed: 1,0,1,0,0,1,1,0,1,0,0,1,0,1,0 = 7
        expected_wickets = 7
        assert star["total_wickets"] == expected_wickets


# ---------------------------------------------------------------------------
# Component weight validation
# ---------------------------------------------------------------------------


class TestBowlingComponentWeights:
    """Verify that component weights sum to 1.0."""

    def test_accuracy_weights_sum_to_one(self):
        total = sum(ACC_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_control_weights_sum_to_one(self):
        total = sum(CTRL_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_threat_weights_sum_to_one(self):
        total = sum(THREAT_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Extras handling in bowling
# ---------------------------------------------------------------------------


class TestBowlingWithExtras:
    """Tests that extras are handled correctly in bowling spells."""

    def test_extras_counted(self, synthetic_deliveries_with_extras):
        """Wides and no-balls should be counted in the spell."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_extras)
        result = extract_bowling_spells(synthetic_deliveries_with_extras, innings_ctx)

        assert len(result) == 1
        row = result.iloc[0]

        # 2 wides and 1 no-ball
        assert row["wides_count"] == 2
        assert row["noballs_count"] == 1

    def test_legal_balls_exclude_extras(self, synthetic_deliveries_with_extras):
        """Legal balls should not include wides or no-balls."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_extras)
        result = extract_bowling_spells(synthetic_deliveries_with_extras, innings_ctx)

        row = result.iloc[0]
        # 6 legal deliveries out of 9 total
        assert row["legal_balls"] == 6

    def test_extras_per_over_positive(self, synthetic_deliveries_with_extras):
        """extras_per_over should be positive when there are wides/noballs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_extras)
        result = extract_bowling_spells(synthetic_deliveries_with_extras, innings_ctx)

        row = result.iloc[0]
        # 3 extras in 1 over → 3.0
        assert row["extras_per_over"] == pytest.approx(3.0)

    def test_bowler_extras_pct(self, synthetic_deliveries_with_extras):
        """bowler_extras_pct = (wide_runs + noball_runs) / runs_conceded."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_extras)
        result = extract_bowling_spells(synthetic_deliveries_with_extras, innings_ctx)

        row = result.iloc[0]
        # wide_runs = 2 (two wides, 1 run each), noball_runs = 1
        expected = (row["wide_runs"] + row["noball_runs"]) / row["runs_conceded"]
        assert row["bowler_extras_pct"] == pytest.approx(expected, rel=1e-3)

    def test_total_deliveries_includes_extras(self, synthetic_deliveries_with_extras):
        """total_deliveries should count ALL deliveries including wides/noballs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_extras)
        result = extract_bowling_spells(synthetic_deliveries_with_extras, innings_ctx)

        row = result.iloc[0]
        assert row["total_deliveries"] == 9

    def test_total_runs_includes_extras(self, synthetic_deliveries_with_extras):
        """Runs conceded should include extras from wides and no-balls."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_extras)
        result = extract_bowling_spells(synthetic_deliveries_with_extras, innings_ctx)

        row = result.iloc[0]
        # Total: 1+1+0+1+4+2+0+6+2 = 17
        assert row["runs_conceded"] == 17


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestBowlingEdgeCases:
    """Edge case tests for the bowling pipeline."""

    def test_zero_runs_conceded(self):
        """A spell with 0 runs conceded should not crash."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_ZERO_BOWL",
            1,
            "TBat",
            "TBowl",
            0,
            "Bat1",
            "b1",
            "PerfectBowler",
            "pbowl",
            "Bat2",
            "b2",
            1,
            [0, 0, 0, 0, 0, 0],
            wicket_on_ball=3,
        )
        # Add innings 2
        rows += _build_over(
            "M_ZERO_BOWL",
            2,
            "TBowl",
            "TBat",
            0,
            "Bat3",
            "b3",
            "Bat1",
            "b1",
            "Bat4",
            "b4",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        spells = extract_bowling_spells(df, innings_ctx)
        entropy = compute_run_distribution_entropy(df)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, df)

        pbowl = result[result["bowler_id"] == "pbowl"]
        assert len(pbowl) == 1
        assert pbowl.iloc[0]["total_runs_conceded"] == 0
        assert pbowl.iloc[0]["career_economy"] == pytest.approx(0.0)
        for col in ["raw_accuracy", "raw_control", "raw_threat"]:
            assert np.isfinite(pbowl.iloc[0][col])

    def test_all_boundaries_spell(self):
        """A spell of all boundaries should not crash and should have bad metrics."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_ALL_BOUND",
            1,
            "TBat",
            "TBowl",
            0,
            "Bat1",
            "b1",
            "BadBowler",
            "bbowl",
            "Bat2",
            "b2",
            1,
            [6, 4, 6, 4, 6, 4],
        )
        rows += _build_over(
            "M_ALL_BOUND",
            2,
            "TBowl",
            "TBat",
            0,
            "Bat3",
            "b3",
            "Bat1",
            "b1",
            "Bat4",
            "b4",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        spells = extract_bowling_spells(df, innings_ctx)
        entropy = compute_run_distribution_entropy(df)
        comps = compute_bowling_components(spells, entropy)

        bbowl = comps[comps["bowler_id"] == "bbowl"].iloc[0]
        assert bbowl["acc_boundary_penalty"] < 0  # bad: lots of boundaries
        assert bbowl["runs_conceded"] == 30  # 6+4+6+4+6+4

    def test_columns_preserved_through_pipeline(self, synthetic_deliveries_simple):
        """Important columns should survive from extraction through aggregation."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        entropy = compute_run_distribution_entropy(synthetic_deliveries_simple)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, synthetic_deliveries_simple)

        required = [
            "bowler_id",
            "bowler",
            "matches",
            "total_legal_balls",
            "total_runs_conceded",
            "total_wickets",
            "total_overs",
            "career_economy",
            "career_sr_bowl",
            "bowled_lbw_pct",
            "raw_accuracy",
            "raw_control",
            "raw_threat",
            "is_provisional_bowl",
        ]
        for col in required:
            assert col in result.columns, f"Missing required column: {col}"

    def test_sole_bowler_economy_vs_others_neutral(self):
        """If there's only one bowler in an innings, economy_vs_others should be 0."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_SOLE",
            1,
            "TBat",
            "TBowl",
            0,
            "Bat1",
            "b1",
            "SoleBowler",
            "sole",
            "Bat2",
            "b2",
            1,
            [1, 0, 4, 0, 1, 2],
        )
        rows += _build_over(
            "M_SOLE",
            2,
            "TBowl",
            "TBat",
            0,
            "Bat3",
            "b3",
            "Bat1",
            "b1",
            "Bat4",
            "b4",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        result = extract_bowling_spells(df, innings_ctx)

        sole = result[result["bowler_id"] == "sole"]
        if len(sole) > 0:
            row = sole.iloc[0]
            # Sole bowler's economy vs others: other_overs = 0 → falls back to own economy
            # economy_vs_others = own_econ - own_econ = 0
            assert row["economy_vs_others"] == pytest.approx(0.0, abs=1e-3)

    def test_no_crash_with_varied_wicket_kinds(self):
        """Different wicket kinds should all be handled."""
        from tests.conftest import _build_over

        for kind in ["bowled", "lbw", "caught", "run out", "stumped"]:
            rows = _build_over(
                f"M_WKT_{kind}",
                1,
                "TBat",
                "TBowl",
                0,
                "Bat1",
                "b1",
                "WktBowler",
                "wbowl",
                "Bat2",
                "b2",
                1,
                [0, 0, 0, 0, 0, 0],
                wicket_on_ball=3,
                wicket_kind_val=kind,
            )
            rows += _build_over(
                f"M_WKT_{kind}",
                2,
                "TBowl",
                "TBat",
                0,
                "Bat3",
                "b3",
                "Bat1",
                "b1",
                "Bat4",
                "b4",
                1,
                [1, 1, 1, 1, 1, 1],
            )
            df = pd.DataFrame(rows)
            innings_ctx = _get_innings_ctx(df)
            spells = extract_bowling_spells(df, innings_ctx)
            entropy = compute_run_distribution_entropy(df)
            comps = compute_bowling_components(spells, entropy)
            result = aggregate_bowling_careers(comps, df)
            assert len(result) > 0

    def test_bowled_lbw_pct_with_mixed_wickets(self):
        """bowled_lbw_pct should correctly compute from mixed wicket types."""
        from tests.conftest import _build_over

        rows = []
        # Match 1: bowled wicket
        rows += _build_over(
            "M_MIX1",
            1,
            "TBat",
            "TBowl",
            0,
            "Bat1",
            "b1",
            "MixBowler",
            "mbowl",
            "Bat2",
            "b2",
            1,
            [0, 0, 0, 0, 0, 0],
            wicket_on_ball=2,
            wicket_kind_val="bowled",
        )
        rows += _build_over(
            "M_MIX1",
            2,
            "TBowl",
            "TBat",
            0,
            "Bat3",
            "b3",
            "Bat1",
            "b1",
            "Bat4",
            "b4",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        # Match 2: caught wicket
        rows += _build_over(
            "M_MIX2",
            1,
            "TBat",
            "TBowl",
            0,
            "Bat1",
            "b1",
            "MixBowler",
            "mbowl",
            "Bat2",
            "b2",
            1,
            [0, 0, 0, 0, 0, 0],
            wicket_on_ball=4,
            wicket_kind_val="caught",
        )
        rows += _build_over(
            "M_MIX2",
            2,
            "TBowl",
            "TBat",
            0,
            "Bat3",
            "b3",
            "Bat1",
            "b1",
            "Bat4",
            "b4",
            1,
            [1, 1, 1, 1, 1, 1],
        )

        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        spells = extract_bowling_spells(df, innings_ctx)
        entropy = compute_run_distribution_entropy(df)
        comps = compute_bowling_components(spells, entropy)
        result = aggregate_bowling_careers(comps, df)

        mbowl = result[result["bowler_id"] == "mbowl"].iloc[0]
        # 1 bowled + 1 caught = 2 wickets, 1 bowled/lbw → 50%
        assert mbowl["bowled_lbw_pct"] == pytest.approx(0.5)
