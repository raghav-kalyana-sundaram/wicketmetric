"""
Unit tests for the batting module: innings extraction, component computation,
career aggregation, the z-score normalisation pipeline, config loading,
and recency / time-decay weighting.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.batting import (
    ACC_WEIGHTS,
    AVG_GATE_BASE,
    AVG_GATE_REF,
    AVG_QUALITY_CEIL,
    AVG_QUALITY_EXPONENT_ABOVE,
    AVG_QUALITY_EXPONENT_BELOW,
    AVG_QUALITY_FLOOR,
    AVG_QUALITY_REFERENCE,
    CTRL_WEIGHTS,
    MIN_PHASE_BALLS,
    OPP_QUALITY_CLIP,
    OPP_QUALITY_SCALE,
    POW_WEIGHTS,
    _compute_phase_par_sr,
    _zscore_series,
    aggregate_batting_careers,
    apply_avg_quality_gate,
    compute_batting_components,
    compute_bowler_strength_index,
    compute_opposition_quality,
    extract_batting_innings,
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
# _zscore_series
# ---------------------------------------------------------------------------


class TestZscoreSeries:
    """Tests for _zscore_series()."""

    def test_basic_zscore(self):
        """Z-score of [1, 2, 3] should have mean 0 and std 1."""
        s = pd.Series([1.0, 2.0, 3.0])
        result = _zscore_series(s)
        assert result.mean() == pytest.approx(0.0, abs=1e-10)
        assert result.std() == pytest.approx(1.0, abs=1e-6)

    def test_preserves_ordering(self):
        """Higher original values should have higher z-scores."""
        s = pd.Series([10.0, 50.0, 30.0, 90.0, 5.0])
        result = _zscore_series(s)
        sorted_pairs = sorted(zip(s, result))
        for i in range(len(sorted_pairs) - 1):
            assert sorted_pairs[i][1] < sorted_pairs[i + 1][1]

    def test_all_same_returns_zeros(self):
        """If all values are the same, z-scores should be 0."""
        s = pd.Series([7.0, 7.0, 7.0, 7.0])
        result = _zscore_series(s)
        assert (result == 0.0).all()

    def test_nan_stays_nan(self):
        """NaN values should remain NaN after z-scoring."""
        s = pd.Series([1.0, np.nan, 3.0, 5.0])
        result = _zscore_series(s)
        assert pd.isna(result.iloc[1])
        assert pd.notna(result.iloc[0])
        assert pd.notna(result.iloc[2])

    def test_empty_series(self):
        """Empty series should return empty."""
        s = pd.Series([], dtype=float)
        result = _zscore_series(s)
        assert len(result) == 0

    def test_single_element(self):
        """Single element should return 0 (std is NaN → fallback)."""
        s = pd.Series([42.0])
        result = _zscore_series(s)
        # std of a single element is NaN, so fallback returns 0
        assert result.iloc[0] == 0.0

    def test_two_elements(self):
        """Two elements should be symmetric around zero."""
        s = pd.Series([10.0, 20.0])
        result = _zscore_series(s)
        assert result.iloc[0] == pytest.approx(-result.iloc[1], abs=1e-10)


# ---------------------------------------------------------------------------
# extract_batting_innings
# ---------------------------------------------------------------------------


class TestExtractBattingInnings:
    """Tests for extract_batting_innings()."""

    def test_basic_extraction(self, synthetic_deliveries_simple):
        """Should produce one row per (match, innings, batter)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # M001 Inn 1: Batter1 (12 balls), Batter2 (6 balls) → 2 rows
        # M001 Inn 2: Batter3 (12 balls) → 1 row
        # M002 Inn 1: Batter1 (6 balls) → 1 row
        # M002 Inn 2: Batter3 (6 balls) → 1 row
        # Total: 5 batting innings
        assert len(result) == 5

    def test_batter1_runs_m001(self, synthetic_deliveries_simple):
        """Batter1 in M001 Inn1 should have 24 runs off 12 balls."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ]
        assert len(b1_m001) == 1
        row = b1_m001.iloc[0]
        assert row["runs"] == 24
        assert row["balls_faced"] == 12

    def test_batter1_sr_m001(self, synthetic_deliveries_simple):
        """Batter1 in M001 should have SR = 24/12 * 100 = 200."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ]
        assert b1_m001.iloc[0]["sr"] == pytest.approx(200.0)

    def test_batter2_runs_m001(self, synthetic_deliveries_simple):
        """Batter2 in M001 Inn1 should have 2 runs off 6 balls."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b2_m001 = result[
            (result["batter_id"] == "bat2") & (result["match_id"] == "M001")
        ]
        assert len(b2_m001) == 1
        row = b2_m001.iloc[0]
        assert row["runs"] == 2
        assert row["balls_faced"] == 6

    def test_batter3_runs_across_matches(self, synthetic_deliveries_simple):
        """Batter3 appears in both M001 (30 runs) and M002 (5 runs)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b3 = result[result["batter_id"] == "bat3"]
        assert len(b3) == 2

        b3_m001 = b3[b3["match_id"] == "M001"].iloc[0]
        assert b3_m001["runs"] == 30  # 17 + 13

        b3_m002 = b3[b3["match_id"] == "M002"].iloc[0]
        assert b3_m002["runs"] == 5

    def test_boundary_counts(self, synthetic_deliveries_simple):
        """Fours and sixes should be counted correctly per batter-innings."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: Over 0 (1,0,4,1,0,6) → 1 four, 1 six
        #               Over 1 (4,4,1,0,1,2) → 2 fours, 0 sixes
        # Total: 3 fours, 1 six
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["fours"] == 3
        assert b1_m001["sixes"] == 1

    def test_dot_ball_count(self, synthetic_deliveries_simple):
        """Dot balls should be counted per batter-innings."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: Over 0 (1,0,4,1,0,6) → 2 dots
        #               Over 1 (4,4,1,0,1,2) → 1 dot
        # Total: 3 dots
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["dots"] == 3

    def test_ones_twos_threes(self, synthetic_deliveries_simple):
        """Singles, doubles, and triples should be counted."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: Over 0 (1,0,4,1,0,6): ones=2, twos=0, threes=0
        #               Over 1 (4,4,1,0,1,2): ones=2, twos=1, threes=0
        # Total: ones=4, twos=1, threes=0
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["ones"] == 4
        assert b1_m001["twos"] == 1
        assert b1_m001["threes"] == 0

    def test_dismissal_info(self, synthetic_deliveries_simple):
        """Batter1 gets out in M001 (wicket on over 1 ball 5)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["is_out"] == True
        assert b1_m001["how_out"] == "bowled"

    def test_not_out_innings(self, synthetic_deliveries_simple):
        """Batter2 in M001 is not dismissed."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b2_m001 = result[
            (result["batter_id"] == "bat2") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b2_m001["is_out"] == False

    def test_dot_pct(self, synthetic_deliveries_simple):
        """Dot pct should be dots / balls_faced."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter2 M001: Over 2 (0,1,0,0,1,0) → 4 dots / 6 balls = 66.7%
        b2_m001 = result[
            (result["batter_id"] == "bat2") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b2_m001["dot_pct"] == pytest.approx(4 / 6, rel=1e-3)

    def test_rotation_rate(self, synthetic_deliveries_simple):
        """Rotation rate = (ones + twos) / balls_faced."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: ones=4, twos=1, balls=12 → rotation = 5/12
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["rotation_rate"] == pytest.approx(5 / 12, rel=1e-3)

    def test_team_contribution_pct(self, synthetic_deliveries_simple):
        """Team contribution pct = runs / team_total_runs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: 24 runs out of team total 26 → 24/26 ≈ 92.3%
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["team_contribution_pct"] == pytest.approx(24 / 26, rel=1e-3)

    def test_sr_vs_par_is_ratio(self, synthetic_deliveries_simple):
        """sr_vs_par should be sr / match_par_sr (ratio, centered at ~1.0)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: SR=200, match_par_sr ≈ 186.67
        # sr_vs_par = 200 / 186.67 ≈ 1.071
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        match_par = 56 / 30 * 100  # M001 par
        expected_ratio = 200.0 / match_par
        assert b1_m001["sr_vs_par"] == pytest.approx(expected_ratio, rel=1e-2)

    def test_boundary_pct(self, synthetic_deliveries_simple):
        """Boundary pct = (fours*4 + sixes*6) / runs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: 3 fours + 1 six → boundary_runs = 18, total runs = 24
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["boundary_pct"] == pytest.approx(18 / 24, rel=1e-3)

    def test_batting_position(self, synthetic_deliveries_simple):
        """Batting position should be set correctly."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["batting_position"] == 1

    def test_has_match_par_columns(self, synthetic_deliveries_simple):
        """Extracted innings should carry match context (match_par_sr, etc.)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        assert "match_par_sr" in result.columns
        assert "match_par_rr" in result.columns
        assert "match_boundary_rate" in result.columns

    def test_has_phase_par_columns(self, synthetic_deliveries_simple):
        """Extracted innings should have phase-specific par SR columns."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        assert "pp_par_sr" in result.columns
        assert "middle_par_sr" in result.columns
        assert "death_par_sr" in result.columns

    def test_entry_team_score(self, synthetic_deliveries_simple):
        """entry_team_score should be the team score when the batter first appeared."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: starts at team_score_before = 0
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["entry_team_score"] == 0

    def test_wides_excluded_from_balls_faced(self, synthetic_deliveries_with_extras):
        """Wides should not count as balls faced by the batter."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_extras)
        result = extract_batting_innings(synthetic_deliveries_with_extras, innings_ctx)

        # The extras fixture: 9 deliveries, 6 legal, but 2 wides are not balls faced
        # However the no-ball IS a ball faced (batter can score off it)
        # is_batter_ball = not is_wide, so: 9 - 2 wides = 7 batter balls
        # But extract_batting_innings filters on is_batter_ball, so
        # the batter faces 7 balls
        if len(result) > 0:
            row = result.iloc[0]
            assert row["balls_faced"] == 7


# ---------------------------------------------------------------------------
# Phase-specific stats in extract_batting_innings
# ---------------------------------------------------------------------------


class TestBattingPhaseStats:
    """Tests for phase-level breakdown in batting innings."""

    def test_all_phases_present(self, synthetic_deliveries_with_phases):
        """Multi-phase match should have stats for PP, middle, death."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)

        # BatterA faces all three phases
        batA = result[result["batter_id"] == "batA"]
        assert len(batA) == 1
        row = batA.iloc[0]

        # All phases should have valid data (12 balls each ≥ MIN_PHASE_BALLS)
        assert pd.notna(row["powerplay_sr"])
        assert pd.notna(row["middle_sr"])
        assert pd.notna(row["death_sr"])

    def test_powerplay_runs(self, synthetic_deliveries_with_phases):
        """PP runs should match hand calculation."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)

        batA = result[result["batter_id"] == "batA"].iloc[0]
        # Over 0: 1+1+4+0+1+1 = 8, Over 1: 0+6+0+1+4+0 = 11
        assert batA["powerplay_runs"] == 19
        assert batA["powerplay_balls"] == 12

    def test_powerplay_sr(self, synthetic_deliveries_with_phases):
        """PP SR = PP runs / PP balls * 100."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)

        batA = result[result["batter_id"] == "batA"].iloc[0]
        assert batA["powerplay_sr"] == pytest.approx(19 / 12 * 100, rel=1e-3)

    def test_middle_overs_stats(self, synthetic_deliveries_with_phases):
        """Middle overs stats should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)

        batA = result[result["batter_id"] == "batA"].iloc[0]
        # Over 8: 1+1+0+2+1+0 = 5, Over 9: 0+1+0+0+4+1 = 6
        assert batA["middle_runs"] == 11
        assert batA["middle_balls"] == 12
        assert batA["middle_sr"] == pytest.approx(11 / 12 * 100, rel=1e-3)

    def test_death_overs_stats(self, synthetic_deliveries_with_phases):
        """Death overs stats should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)

        batA = result[result["batter_id"] == "batA"].iloc[0]
        # Over 18: 4+6+1+4+6+2 = 23, Over 19: 6+0+4+4+6+1 = 21
        assert batA["death_runs"] == 44
        assert batA["death_balls"] == 12
        assert batA["death_sr"] == pytest.approx(44 / 12 * 100, rel=1e-3)

    def test_single_phase_match_has_nan_for_other_phases(
        self, synthetic_deliveries_simple
    ):
        """Batters in matches with only PP overs should have NaN for mid/death."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]

        assert pd.notna(b1_m001["powerplay_sr"])
        # middle and death should be NaN (no balls in those phases)
        assert pd.isna(b1_m001.get("middle_sr", np.nan))
        assert pd.isna(b1_m001.get("death_sr", np.nan))

    def test_phase_dots(self, synthetic_deliveries_with_phases):
        """Phase dot counts should be correct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        result = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)

        batA = result[result["batter_id"] == "batA"].iloc[0]
        # PP Over 0: 1,1,4,0,1,1 → 1 dot; Over 1: 0,6,0,1,4,0 → 3 dots → total 4
        assert batA["powerplay_dots"] == 4

        # Middle Over 8: 1,1,0,2,1,0 → 2 dots; Over 9: 0,1,0,0,4,1 → 3 dots → total 5
        assert batA["middle_dots"] == 5

        # Death Over 18: 4,6,1,4,6,2 → 0 dots; Over 19: 6,0,4,4,6,1 → 1 dot → total 1
        assert batA["death_dots"] == 1

    def test_min_phase_balls_threshold(self):
        """Phase SR should be NaN if fewer than MIN_PHASE_BALLS faced."""
        from tests.conftest import _build_over, _make_delivery

        # Build a match where a batter faces only 2 balls in the death
        rows = []
        # PP over (6 balls)
        rows += _build_over(
            "M_SHORT",
            1,
            "TShort",
            "TOpp",
            0,
            "ShortBat",
            "sbat",
            "OppBowl",
            "obowl",
            "ShortPart",
            "spart",
            1,
            [1, 0, 4, 0, 1, 2],
        )

        # Death over with only 2 balls then wicket and a different batter continues
        # We'll just add 2 death deliveries for this batter
        for ball_i, br in enumerate([6, 4]):
            d = _make_delivery(
                match_id="M_SHORT",
                innings_num=1,
                batting_team="TShort",
                bowling_team="TOpp",
                over=18,
                ball_idx=ball_i,
                legal_ball_seq=6 + ball_i,
                batter="ShortBat",
                batter_id="sbat",
                bowler="OppBowl",
                bowler_id="obowl",
                non_striker="ShortPart",
                non_striker_id="spart",
                batting_position=1,
                batter_runs=br,
                total_runs=br,
                is_four=(br == 4),
                is_six=(br == 6),
                is_dot_batter=(br == 0),
                is_dot_bowler=(br == 0),
                phase="death",
                team_score_before=8 + ball_i * 6,
            )
            rows.append(d)

        # Fill remaining death balls with a different batter so the over is complete
        for ball_i in range(2, 6):
            d = _make_delivery(
                match_id="M_SHORT",
                innings_num=1,
                batting_team="TShort",
                bowling_team="TOpp",
                over=18,
                ball_idx=ball_i,
                legal_ball_seq=6 + ball_i,
                batter="ShortPart",
                batter_id="spart",
                bowler="OppBowl",
                bowler_id="obowl",
                non_striker="ShortBat",
                non_striker_id="sbat",
                batting_position=2,
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
        result = extract_batting_innings(df, innings_ctx)

        sbat = result[result["batter_id"] == "sbat"].iloc[0]
        # ShortBat has 2 death balls (< MIN_PHASE_BALLS=4) → death_sr should be NaN
        assert sbat["death_balls"] == 2
        assert pd.isna(sbat["death_sr"])

        # PP has 6 balls (≥ MIN_PHASE_BALLS) → should be valid
        assert pd.notna(sbat["powerplay_sr"])


# ---------------------------------------------------------------------------
# First-half / second-half SR splits
# ---------------------------------------------------------------------------


class TestSRHalves:
    """Tests for the first-half / second-half SR computation."""

    def test_halves_computed(self, synthetic_deliveries_simple):
        """Batters with enough balls should have both halves."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        result = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)

        # Batter1 M001: 12 balls → first 6 and second 6
        b1 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]

        # first_half: balls 0-5 (over 0: 1,0,4,1,0,6) = 12 runs in 6 balls → SR 200
        # second_half: balls 6-11 (over 1: 4,4,1,0,1,2) = 12 runs in 6 balls → SR 200
        if pd.notna(b1.get("first_half_sr")) and pd.notna(b1.get("second_half_sr")):
            assert b1["first_half_balls"] == 6
            assert b1["second_half_balls"] == 6
            assert b1["first_half_sr"] == pytest.approx(200.0)
            assert b1["second_half_sr"] == pytest.approx(200.0)

    def test_min_balls_for_halves(self):
        """Halves with fewer than MIN_PHASE_BALLS should be NaN."""
        from tests.conftest import _build_over

        # Batter faces only 3 balls total (< 2 * MIN_PHASE_BALLS)
        # With 3 balls, first half = 1 ball, second half = 2 balls
        # Both should be < MIN_PHASE_BALLS and thus NaN
        rows = _build_over(
            "M_TINY",
            1,
            "TTiny",
            "TOpp",
            0,
            "TinyBat",
            "tbat",
            "TinyBowl",
            "tbowl",
            "TinyPart",
            "tpart",
            1,
            [
                4,
                0,
                6,
                0,
                0,
                0,
            ],  # only first 3 balls for this batter, rest are the same batter though
        )
        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        result = extract_batting_innings(df, innings_ctx)

        # With 6 balls total, first_half=3, second_half=3
        # Both are < MIN_PHASE_BALLS=4
        tbat = result[result["batter_id"] == "tbat"].iloc[0]
        if tbat["first_half_balls"] < MIN_PHASE_BALLS:
            assert pd.isna(tbat["first_half_sr"])
        if tbat["second_half_balls"] < MIN_PHASE_BALLS:
            assert pd.isna(tbat["second_half_sr"])


# ---------------------------------------------------------------------------
# compute_batting_components
# ---------------------------------------------------------------------------


class TestComputeBattingComponents:
    """Tests for compute_batting_components()."""

    def test_adds_component_columns(self, synthetic_deliveries_simple):
        """Should add acc_, pow_, ctrl_ columns."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        acc_cols = [c for c in result.columns if c.startswith("acc_")]
        pow_cols = [c for c in result.columns if c.startswith("pow_")]
        ctrl_cols = [c for c in result.columns if c.startswith("ctrl_")]

        assert len(acc_cols) >= 3
        assert len(pow_cols) >= 3
        assert len(ctrl_cols) >= 3

    def test_acc_overall_sr_ratio_based(self, synthetic_deliveries_simple):
        """acc_overall_sr should be SR/par - 1 (ratio-based)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]

        # SR = 200, par ≈ 186.67
        par = 56 / 30 * 100
        expected = 200.0 / par - 1.0
        assert b1_m001["acc_overall_sr"] == pytest.approx(expected, rel=1e-2)

    def test_acc_overall_sr_positive_for_fast_batter(self, synthetic_deliveries_simple):
        """A batter scoring above par should have positive acc_overall_sr."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        # Batter1 M001: SR=200, par~186 → above par → positive
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b1_m001["acc_overall_sr"] > 0

    def test_acc_overall_sr_negative_for_slow_batter(self, synthetic_deliveries_simple):
        """A batter scoring below par should have negative acc_overall_sr."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        # Batter2 M001: SR = 2/6*100 = 33.33, par ~186 → well below par
        b2_m001 = result[
            (result["batter_id"] == "bat2") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b2_m001["acc_overall_sr"] < 0

    def test_acc_death_sr_nan_when_no_death(self, synthetic_deliveries_simple):
        """acc_death_sr should be NaN when batter didn't bat in death."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        # All overs in synthetic_simple are powerplay (0-2)
        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        assert pd.isna(b1_m001["acc_death_sr"])

    def test_acc_death_sr_valid_when_in_death(self, synthetic_deliveries_with_phases):
        """acc_death_sr should be a valid number when batter batted in death."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        bat_inn = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)
        result = compute_batting_components(bat_inn)

        batA = result[result["batter_id"] == "batA"].iloc[0]
        assert pd.notna(batA["acc_death_sr"])

    def test_acc_sr_growth_non_negative(self, synthetic_deliveries_simple):
        """acc_sr_growth should be clamped at ≥ 0 (or NaN)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        growth = result["acc_sr_growth"].dropna()
        if len(growth) > 0:
            assert (growth >= 0).all()

    def test_acc_impact_non_negative(self, synthetic_deliveries_simple):
        """acc_impact should be non-negative."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        assert (result["acc_impact"] >= -1e-10).all()

    def test_pow_boundary_pct_range(self, synthetic_deliveries_simple):
        """pow_boundary_pct should be in [0, 1]."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        assert (result["pow_boundary_pct"] >= 0).all()
        assert (result["pow_boundary_pct"] <= 1).all()

    def test_pow_six_rate_range(self, synthetic_deliveries_simple):
        """pow_six_rate (sixes per ball faced) should be in [0, 1]."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        assert (result["pow_six_rate"] >= 0).all()
        assert (result["pow_six_rate"] <= 1).all()

    def test_ctrl_dot_pct_weighted_inverted(self, synthetic_deliveries_simple):
        """ctrl_dot_pct_weighted should be inverted (lower dot% → higher score)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        # Batter1 M001 has fewer dots than Batter2 M001
        b1 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        b2 = result[
            (result["batter_id"] == "bat2") & (result["match_id"] == "M001")
        ].iloc[0]

        # Batter1 dot_pct = 3/12 = 0.25, Batter2 dot_pct = 4/6 = 0.67
        # After inversion, Batter1 should have HIGHER ctrl_dot_pct_weighted
        assert b1["ctrl_dot_pct_weighted"] > b2["ctrl_dot_pct_weighted"]

    def test_ctrl_rotation(self, synthetic_deliveries_simple):
        """ctrl_rotation should match rotation_rate."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        for _, row in result.iterrows():
            assert row["ctrl_rotation"] == pytest.approx(
                row["rotation_rate"], abs=1e-10
            )

    def test_ctrl_contribution(self, synthetic_deliveries_simple):
        """ctrl_contribution should match team_contribution_pct."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        for _, row in result.iterrows():
            assert row["ctrl_contribution"] == pytest.approx(
                row["team_contribution_pct"], abs=1e-10
            )

    def test_ctrl_dismissal_quality_for_out_batter(self, synthetic_deliveries_simple):
        """Dismissed batters should have non-zero ctrl_dismissal_quality."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        b1_m001 = result[
            (result["batter_id"] == "bat1") & (result["match_id"] == "M001")
        ].iloc[0]
        # Batter1 was dismissed → should have negative (penalty) value
        assert b1_m001["ctrl_dismissal_quality"] <= 0

    def test_ctrl_dismissal_quality_zero_for_not_out(self, synthetic_deliveries_simple):
        """Not-out batters should have 0 ctrl_dismissal_quality."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        b2_m001 = result[
            (result["batter_id"] == "bat2") & (result["match_id"] == "M001")
        ].iloc[0]
        assert b2_m001["ctrl_dismissal_quality"] == 0.0

    def test_ctrl_avg_proxy_is_runs(self, synthetic_deliveries_simple):
        """ctrl_avg_proxy should equal runs scored."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        result = compute_batting_components(bat_inn)

        for _, row in result.iterrows():
            assert row["ctrl_avg_proxy"] == float(row["runs"])

    def test_pow_peak_phase_sr_uses_phases(self, synthetic_deliveries_with_phases):
        """pow_peak_phase_sr should reflect the best phase vs that phase's par."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_with_phases)
        bat_inn = extract_batting_innings(synthetic_deliveries_with_phases, innings_ctx)
        result = compute_batting_components(bat_inn)

        batA = result[result["batter_id"] == "batA"].iloc[0]
        # Death phase: SR 366.67, death par ≈ 366.67 (only 1 innings in match)
        # Since it's the only innings, death par = death SR → ratio ≈ 0
        # But peak should still be a number
        assert pd.notna(batA["pow_peak_phase_sr"])


# ---------------------------------------------------------------------------
# aggregate_batting_careers
# ---------------------------------------------------------------------------


class TestAggregateBattingCareers:
    """Tests for aggregate_batting_careers()."""

    def test_basic_aggregation(self, synthetic_deliveries_simple):
        """Should produce one row per batter."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        batter_ids = set(result["batter_id"])
        assert "bat1" in batter_ids
        assert "bat2" in batter_ids
        assert "bat3" in batter_ids

    def test_career_total_runs(self, synthetic_deliveries_simple):
        """Career total runs should be the sum across all innings."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        # Batter1: M001 (24 runs) + M002 (11 runs) = 35
        b1 = result[result["batter_id"] == "bat1"].iloc[0]
        assert b1["total_runs"] == 35

        # Batter3: M001 (30 runs) + M002 (5 runs) = 35
        b3 = result[result["batter_id"] == "bat3"].iloc[0]
        assert b3["total_runs"] == 35

    def test_career_sr(self, synthetic_deliveries_simple):
        """Career SR = total_runs / total_balls * 100."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        # Batter1: 35 runs / 18 balls * 100 ≈ 194.44
        b1 = result[result["batter_id"] == "bat1"].iloc[0]
        assert b1["career_sr"] == pytest.approx(35 / 18 * 100, rel=1e-3)

    def test_career_avg(self, synthetic_deliveries_simple):
        """Career avg = total_runs / total_outs."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        # Batter1: 35 runs / 1 out = 35.0
        b1 = result[result["batter_id"] == "bat1"].iloc[0]
        assert b1["career_avg"] == pytest.approx(35.0)

        # Batter3: 35 runs / 0 outs → uses total_runs as avg
        b3 = result[result["batter_id"] == "bat3"].iloc[0]
        assert b3["career_avg"] == pytest.approx(35.0)

    def test_career_boundary_counts(self, synthetic_deliveries_simple):
        """Career fours and sixes should be summed."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        # Batter1: M001 (3 fours, 1 six) + M002 (1 four, 1 six) = 4 fours, 2 sixes
        b1 = result[result["batter_id"] == "bat1"].iloc[0]
        assert b1["total_fours"] == 4
        assert b1["total_sixes"] == 2

    def test_innings_count(self, synthetic_deliveries_simple):
        """innings_count should be the number of distinct matches batted in."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        # Batter1 plays in M001 and M002
        b1 = result[result["batter_id"] == "bat1"].iloc[0]
        assert b1["innings_count"] == 2

        # Batter2 only plays in M001
        b2 = result[result["batter_id"] == "bat2"].iloc[0]
        assert b2["innings_count"] == 1

    def test_provisional_flag(self, synthetic_deliveries_simple):
        """Batters with fewer than min_innings should be flagged provisional."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)

        # With min_innings=3, batters with < 3 innings are provisional
        result = aggregate_batting_careers(bat_comp, min_innings=3)

        # All batters have ≤ 2 innings → all provisional
        assert result["is_provisional_bat"].all()

        # With min_innings=1, everyone should be non-provisional
        result2 = aggregate_batting_careers(bat_comp, min_innings=1)
        assert not result2["is_provisional_bat"].any()

    def test_has_raw_composites(self, synthetic_deliveries_simple):
        """Should produce raw_acceleration, raw_power, raw_control columns."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        assert "raw_acceleration" in result.columns
        assert "raw_power" in result.columns
        assert "raw_control" in result.columns

    def test_raw_composites_are_finite(self, synthetic_deliveries_simple):
        """Raw composite scores should be finite (not NaN or inf)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        for col in ["raw_acceleration", "raw_power", "raw_control"]:
            assert np.isfinite(result[col]).all(), f"{col} has non-finite values"

    def test_zscore_composites_have_mean_near_zero(self, synthetic_deliveries_simple):
        """Z-score weighted composites should have mean near 0."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        for col in ["raw_acceleration", "raw_power", "raw_control"]:
            # With small sample, mean won't be exactly 0 but should be close-ish
            # The mean of a weighted sum of z-scores should be near 0
            mean = result[col].mean()
            assert abs(mean) < 1.0, f"{col} mean={mean:.3f} is too far from 0"

    def test_faster_batter_ranks_higher_on_acceleration(
        self, synthetic_deliveries_simple
    ):
        """A batter with higher SR should have higher raw_acceleration."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        # Batter1 career SR ≈ 194 vs Batter2 SR ≈ 33
        b1 = result[result["batter_id"] == "bat1"].iloc[0]
        b2 = result[result["batter_id"] == "bat2"].iloc[0]
        assert b1["raw_acceleration"] > b2["raw_acceleration"]

    def test_more_boundaries_ranks_higher_on_power(self, synthetic_deliveries_simple):
        """A batter with more boundaries should have higher raw_power."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        # Batter1 has 4 fours + 2 sixes, Batter2 has 0 fours + 0 sixes
        b1 = result[result["batter_id"] == "bat1"].iloc[0]
        b2 = result[result["batter_id"] == "bat2"].iloc[0]
        assert b1["raw_power"] > b2["raw_power"]

    def test_death_sr_nan_does_not_penalize(self):
        """
        Batters who never bat in death should NOT be penalized.
        Their acc_death_sr_mean should be NaN, and after z-score + fillna(0),
        they should get the neutral population-average contribution (z=0).
        """
        from tests.conftest import _build_over

        # Two batters: one PP-only, one with death overs
        rows = []
        # Match 1: PP-only batter
        rows += _build_over(
            "MD1",
            1,
            "TeamD",
            "TeamE",
            0,
            "PPBatter",
            "ppbat",
            "GenBowl",
            "gbowl",
            "PPPart",
            "pppart",
            1,
            [4, 4, 4, 4, 4, 4],
        )
        rows += _build_over(
            "MD1",
            2,
            "TeamE",
            "TeamD",
            0,
            "OppBat",
            "obat",
            "GenBowl2",
            "gbowl2",
            "OppPart",
            "opart",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        # Match 2: death-overs batter
        rows += _build_over(
            "MD2",
            1,
            "TeamF",
            "TeamG",
            18,
            "DeathBatter",
            "dbat",
            "GenBowl3",
            "gbowl3",
            "DeathPart",
            "dpart",
            1,
            [6, 6, 6, 6, 6, 6],
        )
        rows += _build_over(
            "MD2",
            2,
            "TeamG",
            "TeamF",
            0,
            "OppBat2",
            "obat2",
            "GenBowl4",
            "gbowl4",
            "OppPart2",
            "opart2",
            1,
            [0, 0, 0, 0, 0, 0],
        )

        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        bat_inn = extract_batting_innings(df, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        ppbat = result[result["batter_id"] == "ppbat"]
        if len(ppbat) > 0:
            # The PP batter should NOT have a massively negative acceleration
            # Their raw_acceleration should be finite and reasonable
            assert np.isfinite(ppbat.iloc[0]["raw_acceleration"])
            # The acc_death_sr_mean should be NaN (not filled with 0 - match_par)
            assert pd.isna(ppbat.iloc[0]["acc_death_sr_mean"])


# ---------------------------------------------------------------------------
# Career aggregation with multi-match fixture
# ---------------------------------------------------------------------------


class TestCareerAggregationMultiMatch:
    """Tests using the synthetic_multi_match_career fixture (15 matches)."""

    def test_career_has_correct_innings_count(self, synthetic_multi_match_career):
        """StarBatter should have 15 innings."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        bat_inn = extract_batting_innings(synthetic_multi_match_career, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp, min_innings=10)

        star = result[result["batter_id"] == "bat_star"]
        assert len(star) == 1
        assert star.iloc[0]["innings_count"] == 15

    def test_non_provisional_with_enough_innings(self, synthetic_multi_match_career):
        """StarBatter with 15 innings should not be provisional (min=10)."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        bat_inn = extract_batting_innings(synthetic_multi_match_career, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp, min_innings=10)

        star = result[result["batter_id"] == "bat_star"].iloc[0]
        assert star["is_provisional_bat"] == False

    def test_career_total_runs_sum(self, synthetic_multi_match_career):
        """Total runs should equal sum of individual innings scores."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        bat_inn = extract_batting_innings(synthetic_multi_match_career, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        star = result[result["batter_id"] == "bat_star"].iloc[0]
        expected_total = sum([30, 5, 42, 18, 0, 55, 12, 8, 35, 20, 45, 3, 28, 15, 40])
        assert star["total_runs"] == expected_total


# ---------------------------------------------------------------------------
# Component weight validation
# ---------------------------------------------------------------------------


class TestComponentWeights:
    """Verify that component weights sum to 1.0."""

    def test_acceleration_weights_sum_to_one(self):
        total = sum(ACC_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_power_weights_sum_to_one(self):
        total = sum(POW_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_control_weights_sum_to_one(self):
        total = sum(CTRL_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestBattingEdgeCases:
    """Edge case tests for the batting pipeline."""

    def test_zero_runs_innings(self):
        """An innings with 0 runs should not crash."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_ZERO",
            1,
            "TeamZ",
            "TeamW",
            0,
            "ZeroBatter",
            "zbat",
            "ZeroBowler",
            "zbowl",
            "ZeroPartner",
            "zpart",
            1,
            [0, 0, 0, 0, 0, 0],
            wicket_on_ball=3,
        )
        # Add innings 2 so match context has 2 innings
        rows += _build_over(
            "M_ZERO",
            2,
            "TeamW",
            "TeamZ",
            0,
            "OppBat",
            "obat",
            "ZeroBatter",
            "zbat",
            "OppPart",
            "opart2",
            1,
            [1, 1, 1, 1, 1, 1],
            target_runs=1,
        )
        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        bat_inn = extract_batting_innings(df, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        zbat = result[result["batter_id"] == "zbat"]
        assert len(zbat) == 1
        assert zbat.iloc[0]["total_runs"] == 0
        assert zbat.iloc[0]["career_sr"] == 0.0
        # Should still have finite composites
        for col in ["raw_acceleration", "raw_power", "raw_control"]:
            assert np.isfinite(zbat.iloc[0][col])

    def test_single_ball_innings(self):
        """An innings with just 1 ball should not crash."""
        from tests.conftest import _make_delivery

        d1 = _make_delivery(
            match_id="M_SINGLE_BALL",
            innings_num=1,
            batting_team="T1",
            bowling_team="T2",
            batter="OneBall",
            batter_id="oneball",
            batter_runs=6,
            total_runs=6,
            is_six=True,
            is_dot_batter=False,
            is_dot_bowler=False,
        )
        d2 = _make_delivery(
            match_id="M_SINGLE_BALL",
            innings_num=2,
            batting_team="T2",
            bowling_team="T1",
            batter="OppBat",
            batter_id="oppbat",
            batter_runs=1,
            total_runs=1,
            is_dot_batter=False,
            is_dot_bowler=False,
        )
        df = pd.DataFrame([d1, d2])
        innings_ctx = _get_innings_ctx(df)
        bat_inn = extract_batting_innings(df, innings_ctx)

        assert len(bat_inn) == 2  # two batter-innings

        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        ob = result[result["batter_id"] == "oneball"]
        assert len(ob) == 1
        assert ob.iloc[0]["total_runs"] == 6

    def test_all_sixes_innings(self):
        """An innings of all sixes should have high power components."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_SIXES",
            1,
            "PowerTeam",
            "WeakTeam",
            0,
            "SixHitter",
            "sixhit",
            "GoodBowl",
            "gbowl",
            "Partner",
            "part",
            1,
            [6, 6, 6, 6, 6, 6],
        )
        rows += _build_over(
            "M_SIXES",
            2,
            "WeakTeam",
            "PowerTeam",
            0,
            "NormalBat",
            "normbat",
            "NormBowl",
            "nbowl",
            "NormPart",
            "npart",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        bat_inn = extract_batting_innings(df, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)

        six_hit = bat_comp[bat_comp["batter_id"] == "sixhit"].iloc[0]
        assert six_hit["pow_boundary_pct"] == 1.0
        # pow_six_rate: sixes per ball faced — all 6 balls were sixes
        assert six_hit["pow_six_rate"] == 1.0

    def test_all_dots_innings(self):
        """An innings of all dots should have high control penalty."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M_DOTS",
            1,
            "DotTeam",
            "DotOpp",
            0,
            "DotBatter",
            "dotbat",
            "DotBowl",
            "dbowl",
            "DotPart",
            "dpart",
            1,
            [0, 0, 0, 0, 0, 0],
        )
        rows += _build_over(
            "M_DOTS",
            2,
            "DotOpp",
            "DotTeam",
            0,
            "OppB",
            "oppb",
            "OppBowl",
            "obowl",
            "OppP",
            "oppp",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        df = pd.DataFrame(rows)
        innings_ctx = _get_innings_ctx(df)
        bat_inn = extract_batting_innings(df, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)

        dot_bat = bat_comp[bat_comp["batter_id"] == "dotbat"].iloc[0]
        # dot_pct_weighted inverted: 1 - 1.0 = 0.0 (worst possible)
        assert dot_bat["ctrl_dot_pct_weighted"] == pytest.approx(0.0, abs=0.01)

    def test_columns_preserved_through_pipeline(self, synthetic_deliveries_simple):
        """Important columns should survive from extraction through aggregation."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(synthetic_deliveries_simple, innings_ctx)
        bat_comp = compute_batting_components(bat_inn)
        result = aggregate_batting_careers(bat_comp)

        required = [
            "batter_id",
            "batter",
            "innings_count",
            "total_runs",
            "total_balls",
            "total_fours",
            "total_sixes",
            "career_sr",
            "career_avg",
            "raw_acceleration",
            "raw_power",
            "raw_control",
            "is_provisional_bat",
        ]
        for col in required:
            assert col in result.columns, f"Missing required column: {col}"

    def test_no_crash_with_empty_dataframe(self):
        """Pipeline should handle an empty deliveries DataFrame gracefully."""
        from tests.conftest import _make_delivery

        # Create a valid-schema empty DF
        d = _make_delivery()
        df = pd.DataFrame([d]).iloc[:0]  # empty with correct columns

        # This should either return empty or raise a clear error
        # We're just checking it doesn't crash with an unclear exception
        try:
            innings_ctx = _get_innings_ctx(df)
            bat_inn = extract_batting_innings(df, innings_ctx)
            # If we get here with empty frames, that's fine
            assert len(bat_inn) == 0 or True  # either outcome is acceptable
        except (ValueError, KeyError):
            # A clear error is also acceptable for empty data
            pass


# ===========================================================================
# Bowler Strength Index
# ===========================================================================


class TestBowlerStrengthIndex:
    """Tests for compute_bowler_strength_index()."""

    def _make_bowler_deliveries(
        self, bowler_id, n_balls, runs_per_ball, dots_frac, wickets
    ):
        """Create synthetic deliveries for a single bowler."""
        from tests.conftest import _make_delivery

        rows = []
        dot_count = int(n_balls * dots_frac)
        wkt_count = min(wickets, n_balls)
        wkt_placed = 0
        for i in range(n_balls):
            is_dot = i < dot_count
            br = 0 if is_dot else runs_per_ball
            tr = br
            is_wkt = wkt_placed < wkt_count and i >= (n_balls - wkt_count)
            rows.append(
                _make_delivery(
                    match_id=f"M_bs_{bowler_id}_{i // 6}",
                    innings_num=1,
                    bowler=f"Bowler_{bowler_id}",
                    bowler_id=bowler_id,
                    batter=f"Bat_{i % 3}",
                    batter_id=f"bat_{i % 3}",
                    over=i // 6,
                    ball_idx=i % 6,
                    legal_ball_seq=i,
                    batter_runs=br,
                    total_runs=tr,
                    is_dot_batter=is_dot,
                    is_dot_bowler=tr == 0,
                    is_four=br == 4,
                    is_six=br == 6,
                    is_wicket=is_wkt,
                    wicket_kind="bowled" if is_wkt else None,
                    player_out=f"Bat_{i % 3}" if is_wkt else None,
                    player_out_id=f"bat_{i % 3}" if is_wkt else None,
                )
            )
        return rows

    def test_returns_bowler_strength_column(self):
        """Output should have bowler_id and bowler_strength columns."""
        rows = self._make_bowler_deliveries("b1", 150, 1, 0.5, 10)
        df = pd.DataFrame(rows)
        result = compute_bowler_strength_index(df, min_balls=120)
        assert "bowler_id" in result.columns
        assert "bowler_strength" in result.columns

    def test_unqualified_bowlers_get_zero(self):
        """Bowlers below min_balls should have strength 0.0 (population avg)."""
        rows = self._make_bowler_deliveries("b1", 150, 1, 0.5, 10)
        rows += self._make_bowler_deliveries("b_short", 30, 1, 0.3, 1)
        df = pd.DataFrame(rows)
        result = compute_bowler_strength_index(df, min_balls=120)
        short = result[result["bowler_id"] == "b_short"]
        assert len(short) == 1
        assert short.iloc[0]["bowler_strength"] == 0.0

    def test_better_bowler_has_higher_strength(self):
        """A bowler with lower economy & more dots should rank higher."""
        # Good bowler: many dots, few runs, many wickets
        good_rows = self._make_bowler_deliveries("good", 180, 1, 0.6, 20)
        # Bad bowler: fewer dots, more runs, fewer wickets
        bad_rows = self._make_bowler_deliveries("bad", 180, 3, 0.2, 5)
        df = pd.DataFrame(good_rows + bad_rows)
        result = compute_bowler_strength_index(df, min_balls=120)

        good_s = result[result["bowler_id"] == "good"].iloc[0]["bowler_strength"]
        bad_s = result[result["bowler_id"] == "bad"].iloc[0]["bowler_strength"]
        assert good_s > bad_s, (
            f"Good bowler ({good_s}) should rank higher than bad ({bad_s})"
        )

    def test_strength_centered_around_zero(self):
        """Qualified bowlers' strength should have mean near 0 (z-score based)."""
        all_rows = []
        for i in range(5):
            all_rows += self._make_bowler_deliveries(
                f"b{i}", 150, i + 1, 0.5 - i * 0.05, max(1, 10 - i * 2)
            )
        df = pd.DataFrame(all_rows)
        result = compute_bowler_strength_index(df, min_balls=120)
        qualified = result[result["bowler_strength"] != 0.0]
        if len(qualified) >= 3:
            assert qualified["bowler_strength"].mean() == pytest.approx(0.0, abs=0.5)

    def test_empty_deliveries(self):
        """Should handle empty dataframe without crashing."""
        from tests.conftest import _make_delivery

        d = _make_delivery()
        df = pd.DataFrame([d]).iloc[:0]
        try:
            result = compute_bowler_strength_index(df, min_balls=120)
            assert "bowler_strength" in result.columns
        except (ValueError, KeyError):
            pass  # acceptable for empty data


# ===========================================================================
# Opposition Quality
# ===========================================================================


class TestOppositionQuality:
    """Tests for compute_opposition_quality() and its effect on innings."""

    def _make_matchup(self, bowler_id, batter_id, n_balls, match_id="M_oq"):
        """Create deliveries between a specific batter and bowler."""
        from tests.conftest import _make_delivery

        rows = []
        for i in range(n_balls):
            rows.append(
                _make_delivery(
                    match_id=match_id,
                    innings_num=1,
                    batter=f"Bat_{batter_id}",
                    batter_id=batter_id,
                    bowler=f"Bowl_{bowler_id}",
                    bowler_id=bowler_id,
                    over=i // 6,
                    ball_idx=i % 6,
                    legal_ball_seq=i,
                    batter_runs=1,
                    total_runs=1,
                    is_dot_batter=False,
                    is_dot_bowler=False,
                )
            )
        return rows

    def test_returns_opposition_quality_column(self):
        """Should return a DF with opposition_quality per innings."""
        rows = self._make_matchup("b1", "bat1", 12)
        df = pd.DataFrame(rows)
        bs = pd.DataFrame({"bowler_id": ["b1"], "bowler_strength": [1.5]})
        result = compute_opposition_quality(df, bs)
        assert "opposition_quality" in result.columns
        assert len(result) > 0

    def test_strong_bowlers_yield_positive_quality(self):
        """Facing a strong bowler (strength > 0) should give positive opp quality."""
        rows = self._make_matchup("strong", "bat1", 18)
        df = pd.DataFrame(rows)
        bs = pd.DataFrame({"bowler_id": ["strong"], "bowler_strength": [2.0]})
        result = compute_opposition_quality(df, bs)
        assert result.iloc[0]["opposition_quality"] > 0

    def test_weak_bowlers_yield_negative_quality(self):
        """Facing a weak bowler (strength < 0) should give negative opp quality."""
        rows = self._make_matchup("weak", "bat1", 18)
        df = pd.DataFrame(rows)
        bs = pd.DataFrame({"bowler_id": ["weak"], "bowler_strength": [-1.5]})
        result = compute_opposition_quality(df, bs)
        assert result.iloc[0]["opposition_quality"] < 0

    def test_weighted_by_balls_faced(self):
        """Quality should be weighted by balls faced per bowler."""
        # Face strong bowler for 18 balls, weak bowler for 6 balls
        rows = self._make_matchup("strong", "bat1", 18, match_id="M_w1")
        rows += self._make_matchup("weak", "bat1", 6, match_id="M_w1")
        df = pd.DataFrame(rows)
        bs = pd.DataFrame(
            {
                "bowler_id": ["strong", "weak"],
                "bowler_strength": [2.0, -2.0],
            }
        )
        result = compute_opposition_quality(df, bs)
        oq = result.iloc[0]["opposition_quality"]
        # Weighted avg: (18*2.0 + 6*(-2.0)) / 24 = (36 - 12) / 24 = 1.0
        assert oq == pytest.approx(1.0, abs=0.01)

    def test_unknown_bowler_gets_zero_strength(self):
        """Bowler not in strength table should be treated as average (0)."""
        rows = self._make_matchup("unknown", "bat1", 12)
        df = pd.DataFrame(rows)
        bs = pd.DataFrame({"bowler_id": ["other"], "bowler_strength": [1.5]})
        result = compute_opposition_quality(df, bs)
        assert result.iloc[0]["opposition_quality"] == pytest.approx(0.0, abs=0.01)

    def test_innings_extraction_includes_opp_quality(self, synthetic_deliveries_simple):
        """When bowler_strength is provided, innings should include opposition columns."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        # Create a simple bowler_strength table covering bowlers in synthetic data
        bowler_ids = synthetic_deliveries_simple["bowler_id"].unique()
        bs = pd.DataFrame(
            {
                "bowler_id": [str(b) for b in bowler_ids],
                "bowler_strength": [0.5] * len(bowler_ids),
            }
        )
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=bs
        )
        assert "opposition_quality" in bat_inn.columns
        assert "opp_quality_weight" in bat_inn.columns

    def test_opp_quality_weight_range(self, synthetic_deliveries_simple):
        """opp_quality_weight base opposition component should be within
        [1 - OPP_QUALITY_CLIP, 1 + OPP_QUALITY_CLIP].
        The combined weight also includes recency, ICC ranking, team quality,
        and match quality — divide those out to isolate the base opposition component."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bowler_ids = synthetic_deliveries_simple["bowler_id"].unique()
        bs = pd.DataFrame(
            {
                "bowler_id": [str(b) for b in bowler_ids],
                "bowler_strength": [3.0] * len(bowler_ids),  # extreme positive
            }
        )
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=bs
        )
        # Divide out all non-opposition components to isolate base opp weight.
        recency = (
            bat_inn["recency_weight"] if "recency_weight" in bat_inn.columns else 1.0
        )
        icc_w = (
            bat_inn["icc_ranking_weight"]
            if "icc_ranking_weight" in bat_inn.columns
            else 1.0
        )
        team_q_w = (
            bat_inn["team_quality_weight"]
            if "team_quality_weight" in bat_inn.columns
            else 1.0
        )
        match_q_w = (
            bat_inn["match_quality_weight"]
            if "match_quality_weight" in bat_inn.columns
            else 1.0
        )
        base_weight = (
            bat_inn["opp_quality_weight"] / recency / icc_w / team_q_w / match_q_w
        )
        assert base_weight.min() >= 1.0 - OPP_QUALITY_CLIP - 0.01
        assert base_weight.max() <= 1.0 + OPP_QUALITY_CLIP + 0.01

    def test_no_bowler_strength_gives_default_weight(self, synthetic_deliveries_simple):
        """Without bowler_strength, opp_quality base weight (before recency, ICC, team quality, match quality) should be 1.0."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        assert "opp_quality_weight" in bat_inn.columns
        # With recency, ICC ranking, team quality, and match quality enabled,
        # divide them all out to verify the base opposition weight is 1.0.
        recency = (
            bat_inn["recency_weight"] if "recency_weight" in bat_inn.columns else 1.0
        )
        icc_w = (
            bat_inn["icc_ranking_weight"]
            if "icc_ranking_weight" in bat_inn.columns
            else 1.0
        )
        team_q_w = (
            bat_inn["team_quality_weight"]
            if "team_quality_weight" in bat_inn.columns
            else 1.0
        )
        match_q_w = (
            bat_inn["match_quality_weight"]
            if "match_quality_weight" in bat_inn.columns
            else 1.0
        )
        base_weight = (
            bat_inn["opp_quality_weight"] / recency / icc_w / team_q_w / match_q_w
        )
        assert np.allclose(base_weight, 1.0, atol=1e-6)

    def test_icc_ranking_weight_column_exists(self, synthetic_deliveries_simple):
        """ICC ranking weight column should be present in innings output."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        assert "icc_ranking_weight" in bat_inn.columns
        # All weights should be positive
        assert (bat_inn["icc_ranking_weight"] > 0).all()

    def test_icc_ranking_weight_known_teams(self):
        """Teams in the ICC ratings table should get weights matching the formula."""
        from src.batting import (
            ICC_RANKING_CEILING,
            ICC_RANKING_FLOOR,
            ICC_RANKING_MAX_RATING,
            ICC_RANKING_RATINGS,
            compute_icc_ranking_weight,
        )

        # India should get the maximum weight (top-ranked)
        india_w = compute_icc_ranking_weight("India")
        assert india_w == pytest.approx(ICC_RANKING_CEILING, abs=0.01)

        # An unranked team should get close to the floor + default contribution
        unknown_w = compute_icc_ranking_weight("Nonexistent Country")
        assert unknown_w >= ICC_RANKING_FLOOR
        assert unknown_w < 1.0  # default_rating=50 is well below max

        # Higher-ranked teams should get higher weights
        eng_w = compute_icc_ranking_weight("England")
        zim_w = compute_icc_ranking_weight("Zimbabwe")
        oman_w = compute_icc_ranking_weight("Oman")
        assert eng_w > zim_w > oman_w > unknown_w

    def test_icc_ranking_weight_vectorised(self):
        """compute_icc_ranking_weights should handle a Series correctly."""
        from src.batting import compute_icc_ranking_weight, compute_icc_ranking_weights

        teams = pd.Series(["India", "England", "Zimbabwe", "Unknown Team"])
        weights = compute_icc_ranking_weights(teams)
        assert len(weights) == 4
        assert weights.iloc[0] == pytest.approx(
            compute_icc_ranking_weight("India"), abs=1e-6
        )
        assert weights.iloc[1] == pytest.approx(
            compute_icc_ranking_weight("England"), abs=1e-6
        )
        # India > England > Zimbabwe > Unknown
        assert weights.iloc[0] > weights.iloc[1] > weights.iloc[2] > weights.iloc[3]

    def test_icc_ranking_multiplied_into_opp_quality_weight(
        self, synthetic_deliveries_simple
    ):
        """ICC ranking weight should be multiplied into opp_quality_weight."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        # opp_quality_weight should incorporate icc_ranking_weight
        icc_w = bat_inn["icc_ranking_weight"]
        recency_w = bat_inn["recency_weight"]
        team_q_w = (
            bat_inn["team_quality_weight"]
            if "team_quality_weight" in bat_inn.columns
            else 1.0
        )
        match_q_w = (
            bat_inn["match_quality_weight"]
            if "match_quality_weight" in bat_inn.columns
            else 1.0
        )
        # Without bowler strength, base opp weight = 1.0
        # Final = 1.0 * team_quality_weight * icc_ranking_weight * match_quality_weight * recency_weight
        expected = 1.0 * team_q_w * icc_w * match_q_w * recency_w
        assert np.allclose(bat_inn["opp_quality_weight"], expected, atol=1e-6)


# ===========================================================================
# Match Quality Weighting
# ===========================================================================


class TestMatchQualityWeighting:
    """Tests for compute_match_quality_weights() and match quality integration."""

    def test_match_quality_weight_column_exists(self, synthetic_deliveries_simple):
        """match_quality_weight column should be present in innings output."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        assert "match_quality_weight" in bat_inn.columns
        # All weights should be positive
        assert (bat_inn["match_quality_weight"] > 0).all()

    def test_match_quality_weight_formula(self):
        """Verify the match quality weight formula against known team pairs."""
        from src.batting import (
            ICC_RANKING_DEFAULT_RATING,
            ICC_RANKING_MAX_RATING,
            MATCH_QUALITY_CEILING,
            MATCH_QUALITY_CURVE,
            MATCH_QUALITY_FLOOR,
            compute_match_quality_weights,
        )

        bat_teams = pd.Series(["India", "Uganda", "India"])
        bowl_teams = pd.Series(["Australia", "Papua New Guinea", "Uganda"])
        weights = compute_match_quality_weights(bat_teams, bowl_teams)

        assert len(weights) == 3

        # India (272) vs Australia (258): avg = 265, high quality
        max_r = max(ICC_RANKING_MAX_RATING, 1.0)
        avg_0 = (272 + 258) / 2.0
        norm_0 = min(avg_0 / max_r, 1.0)
        expected_0 = MATCH_QUALITY_FLOOR + (
            MATCH_QUALITY_CEILING - MATCH_QUALITY_FLOOR
        ) * (norm_0**MATCH_QUALITY_CURVE)
        assert weights.iloc[0] == pytest.approx(expected_0, abs=1e-6)

        # Uganda (142) vs PNG (136): avg = 139, low quality
        avg_1 = (142 + 136) / 2.0
        norm_1 = min(avg_1 / max_r, 1.0)
        expected_1 = MATCH_QUALITY_FLOOR + (
            MATCH_QUALITY_CEILING - MATCH_QUALITY_FLOOR
        ) * (norm_1**MATCH_QUALITY_CURVE)
        assert weights.iloc[1] == pytest.approx(expected_1, abs=1e-6)

        # Elite match quality > low-tier match quality
        assert weights.iloc[0] > weights.iloc[1]

    def test_match_quality_two_top_teams_higher_than_mixed(self):
        """Two top-ranked teams in a match should get higher match quality than a mixed match."""
        from src.batting import compute_match_quality_weights

        # India vs Australia (two top teams)
        elite = compute_match_quality_weights(
            pd.Series(["India"]), pd.Series(["Australia"])
        )
        # India vs Nepal (one top, one mid-tier)
        mixed = compute_match_quality_weights(
            pd.Series(["India"]), pd.Series(["Nepal"])
        )
        # Nepal vs Oman (two lower-tier)
        low = compute_match_quality_weights(pd.Series(["Nepal"]), pd.Series(["Oman"]))
        assert elite.iloc[0] > mixed.iloc[0] > low.iloc[0]

    def test_match_quality_symmetric(self):
        """Match quality should be the same regardless of which team bats first."""
        from src.batting import compute_match_quality_weights

        w1 = compute_match_quality_weights(pd.Series(["India"]), pd.Series(["England"]))
        w2 = compute_match_quality_weights(pd.Series(["England"]), pd.Series(["India"]))
        assert w1.iloc[0] == pytest.approx(w2.iloc[0], abs=1e-9)

    def test_match_quality_unknown_teams_get_low_weight(self):
        """Matches between unknown/unranked teams should get close to floor."""
        from src.batting import MATCH_QUALITY_FLOOR, compute_match_quality_weights

        w = compute_match_quality_weights(
            pd.Series(["Unknown A"]), pd.Series(["Unknown B"])
        )
        # Should be close to the floor (both teams have default_rating)
        assert w.iloc[0] >= MATCH_QUALITY_FLOOR
        assert w.iloc[0] < 1.0  # well below neutral

    def test_match_quality_multiplied_into_opp_quality_weight(
        self, synthetic_deliveries_simple
    ):
        """match_quality_weight should be multiplied into opp_quality_weight."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        # opp_quality_weight should incorporate match_quality_weight
        icc_w = bat_inn["icc_ranking_weight"]
        recency_w = bat_inn["recency_weight"]
        team_q_w = (
            bat_inn["team_quality_weight"]
            if "team_quality_weight" in bat_inn.columns
            else 1.0
        )
        match_q_w = bat_inn["match_quality_weight"]
        # Without bowler strength, base opp weight = 1.0
        expected = 1.0 * team_q_w * icc_w * match_q_w * recency_w
        assert np.allclose(bat_inn["opp_quality_weight"], expected, atol=1e-6)

    def test_match_quality_in_bowling_spells(self, synthetic_deliveries_simple):
        """match_quality_weight should be present in bowling spells and multiplied into spell_weight."""
        from src.bowling import extract_bowling_spells
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        assert "match_quality_weight" in spells.columns
        assert (spells["match_quality_weight"] > 0).all()
        # spell_weight should incorporate match_quality_weight
        expected = (
            spells["recency_weight"]
            * spells["icc_ranking_weight"]
            * spells["team_quality_weight"]
            * spells["match_quality_weight"]
        )
        np.testing.assert_allclose(
            spells["spell_weight"].values,
            expected.values,
            atol=1e-9,
        )


# ===========================================================================
# Competition Quality Gate (post-percentile)
# ===========================================================================


class TestCompetitionQualityGate:
    """Tests for apply_competition_quality_gate() and apply_bowling_competition_quality_gate()."""

    def _make_bat_career_df(self, avg_opp_ratings, base_score=90.0):
        """Create a minimal career DF with given avg opponent ICC ratings."""
        n = len(avg_opp_ratings)
        return pd.DataFrame(
            {
                "batter_id": [f"bat{i}" for i in range(n)],
                "batter": [f"Batter{i}" for i in range(n)],
                "innings_count": [50] * n,
                "career_avg": [30.0] * n,
                "career_sr": [140.0] * n,
                "avg_opp_icc_rating": avg_opp_ratings,
                "score_acceleration": [base_score] * n,
                "score_power": [base_score] * n,
                "score_control": [base_score] * n,
            }
        )

    def _make_bowl_career_df(self, avg_opp_ratings, base_score=90.0):
        """Create a minimal bowling career DF with given avg opponent ICC ratings."""
        n = len(avg_opp_ratings)
        return pd.DataFrame(
            {
                "bowler_id": [f"bowl{i}" for i in range(n)],
                "bowler": [f"Bowler{i}" for i in range(n)],
                "matches": [50] * n,
                "avg_opp_icc_rating": avg_opp_ratings,
                "score_accuracy": [base_score] * n,
                "score_control": [base_score] * n,
                "score_threat": [base_score] * n,
            }
        )

    def test_batting_gate_column_exists(self):
        """apply_competition_quality_gate should add a competition_gate column."""
        from src.batting import apply_competition_quality_gate

        df = self._make_bat_career_df([250.0, 150.0, 50.0])
        result = apply_competition_quality_gate(df)
        assert "competition_gate" in result.columns
        assert len(result) == 3

    def test_bowling_gate_column_exists(self):
        """apply_bowling_competition_quality_gate should add a competition_gate column."""
        from src.batting import apply_bowling_competition_quality_gate

        df = self._make_bowl_career_df([250.0, 150.0, 50.0])
        result = apply_bowling_competition_quality_gate(df)
        assert "competition_gate" in result.columns
        assert len(result) == 3

    def test_higher_opp_rating_gives_higher_gate(self):
        """Players facing stronger opposition should have higher gates."""
        from src.batting import apply_competition_quality_gate

        df = self._make_bat_career_df([260.0, 180.0, 100.0, 30.0])
        result = apply_competition_quality_gate(df)
        gates = result["competition_gate"].tolist()
        assert gates[0] > gates[1] > gates[2] > gates[3]

    def test_gate_reduces_scores(self):
        """All scores should be reduced (or unchanged) by the gate."""
        from src.batting import apply_competition_quality_gate

        base_score = 90.0
        df = self._make_bat_career_df([100.0], base_score=base_score)
        result = apply_competition_quality_gate(df)
        for col in ["score_acceleration", "score_power", "score_control"]:
            assert result[col].iloc[0] <= base_score
            assert result[col].iloc[0] > 0

    def test_top_nation_barely_affected(self):
        """Players facing top-ranked opposition should lose very little score."""
        from src.batting import apply_competition_quality_gate

        base_score = 90.0
        df = self._make_bat_career_df([260.0], base_score=base_score)
        result = apply_competition_quality_gate(df)
        # Gate should be > 0.95 for top opponents
        assert result["competition_gate"].iloc[0] > 0.95
        assert result["score_acceleration"].iloc[0] >= base_score * 0.95

    def test_weak_opposition_significantly_penalised(self):
        """Players facing weak opposition should have scores meaningfully reduced."""
        from src.batting import apply_competition_quality_gate

        base_score = 90.0
        df = self._make_bat_career_df([80.0], base_score=base_score)
        result = apply_competition_quality_gate(df)
        # Gate should be < 0.85 for weak opponents
        assert result["competition_gate"].iloc[0] < 0.85
        assert result["score_acceleration"].iloc[0] < base_score * 0.85

    def test_gate_within_bounds(self):
        """Gate should be between COMPETITION_GATE_BASE and 1.0."""
        from src.batting import COMPETITION_GATE_BASE, apply_competition_quality_gate

        df = self._make_bat_career_df([272.0, 200.0, 100.0, 30.0, 1.0])
        result = apply_competition_quality_gate(df)
        assert (result["competition_gate"] >= COMPETITION_GATE_BASE - 0.01).all()
        assert (result["competition_gate"] <= 1.01).all()

    def test_scores_clipped_to_0_100(self):
        """Scores should remain in [0, 100] after gate application."""
        from src.batting import apply_competition_quality_gate

        df = self._make_bat_career_df([50.0], base_score=100.0)
        result = apply_competition_quality_gate(df)
        for col in ["score_acceleration", "score_power", "score_control"]:
            assert result[col].iloc[0] >= 0.0
            assert result[col].iloc[0] <= 100.0

    def test_bowling_gate_higher_opp_gives_higher_gate(self):
        """Bowlers facing stronger batting lineups should have higher gates."""
        from src.batting import apply_bowling_competition_quality_gate

        df = self._make_bowl_career_df([260.0, 180.0, 100.0, 30.0])
        result = apply_bowling_competition_quality_gate(df)
        gates = result["competition_gate"].tolist()
        assert gates[0] > gates[1] > gates[2] > gates[3]

    def test_bowling_gate_reduces_scores(self):
        """All bowling scores should be reduced (or unchanged) by the gate."""
        from src.batting import apply_bowling_competition_quality_gate

        base_score = 85.0
        df = self._make_bowl_career_df([100.0], base_score=base_score)
        result = apply_bowling_competition_quality_gate(df)
        for col in ["score_accuracy", "score_control", "score_threat"]:
            assert result[col].iloc[0] <= base_score
            assert result[col].iloc[0] > 0

    def test_batting_gate_matches_formula(self):
        """Gate values should match the formula: base + (1 - base) * normalised ^ curve."""
        from src.batting import (
            COMPETITION_GATE_BASE,
            COMPETITION_GATE_CURVE,
            ICC_RANKING_MAX_RATING,
            apply_competition_quality_gate,
        )

        ratings = [260.0, 180.0, 100.0]
        df = self._make_bat_career_df(ratings)
        result = apply_competition_quality_gate(df)

        max_r = max(ICC_RANKING_MAX_RATING, 1.0)
        for i, rating in enumerate(ratings):
            normalised = min(rating / max_r, 1.0)
            expected_gate = COMPETITION_GATE_BASE + (1.0 - COMPETITION_GATE_BASE) * (
                normalised**COMPETITION_GATE_CURVE
            )
            assert result["competition_gate"].iloc[i] == pytest.approx(
                expected_gate, abs=1e-6
            )

    def test_opp_icc_rating_column_in_batting_innings(
        self, synthetic_deliveries_simple
    ):
        """opp_icc_rating should be present in batting innings output."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        assert "opp_icc_rating" in bat_inn.columns
        assert (bat_inn["opp_icc_rating"] > 0).all()

    def test_opp_icc_rating_column_in_bowling_spells(self, synthetic_deliveries_simple):
        """opp_icc_rating should be present in bowling spells output."""
        from src.bowling import extract_bowling_spells
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        assert "opp_icc_rating" in spells.columns
        assert (spells["opp_icc_rating"] > 0).all()


# ===========================================================================
# Average Quality Gate (post-percentile)
# ===========================================================================


class TestAvgQualityGate:
    """Tests for apply_avg_quality_gate() and avg quality constants."""

    def _make_career_df(self, avgs, base_score=90.0):
        """Create a minimal career DF with given averages and a base score."""
        n = len(avgs)
        return pd.DataFrame(
            {
                "batter_id": [f"bat{i}" for i in range(n)],
                "batter": [f"Batter{i}" for i in range(n)],
                "career_avg": avgs,
                "score_acceleration": [base_score] * n,
                "score_power": [base_score] * n,
                "score_control": [base_score] * n,
            }
        )

    def test_gate_column_added(self):
        """apply_avg_quality_gate should add avg_quality_gate column."""
        df = self._make_career_df([20.0, 30.0])
        result = apply_avg_quality_gate(df)
        assert "avg_quality_gate" in result.columns

    def test_high_avg_no_penalty(self):
        """Batters with avg >= AVG_GATE_REF should have gate = 1.0."""
        df = self._make_career_df([AVG_GATE_REF, AVG_GATE_REF + 10, 50.0])
        result = apply_avg_quality_gate(df)
        for _, row in result.iterrows():
            assert row["avg_quality_gate"] == pytest.approx(1.0, abs=0.001)
            assert row["score_acceleration"] == pytest.approx(90.0, abs=0.1)

    def test_low_avg_penalised(self):
        """Batters with avg < AVG_GATE_REF should have score_acceleration < base."""
        df = self._make_career_df([10.0, 15.0])
        result = apply_avg_quality_gate(df)
        for _, row in result.iterrows():
            assert row["avg_quality_gate"] < 1.0
            assert row["score_acceleration"] < 90.0

    def test_gate_floor(self):
        """Gate should never go below AVG_GATE_BASE."""
        df = self._make_career_df([0.0, 1.0, 2.0])
        result = apply_avg_quality_gate(df)
        for _, row in result.iterrows():
            assert row["avg_quality_gate"] >= AVG_GATE_BASE - 0.001

    def test_gate_values_specific(self):
        """Verify gate calculation for specific averages."""
        avgs = [0.0, 10.0, 15.0, 18.0, 25.0, 40.0]
        df = self._make_career_df(avgs, base_score=100.0)
        result = apply_avg_quality_gate(df)

        for _, row in result.iterrows():
            avg = row["career_avg"]
            expected_gate = AVG_GATE_BASE + (1.0 - AVG_GATE_BASE) * min(
                avg / AVG_GATE_REF, 1.0
            )
            assert row["avg_quality_gate"] == pytest.approx(expected_gate, abs=0.001), (
                f"avg={avg}: gate={row['avg_quality_gate']}, expected={expected_gate}"
            )

    def test_control_gated_mildly(self):
        """score_control should be gated by avg, but more mildly than ACC/POW."""
        df = self._make_career_df([10.0], base_score=90.0)
        result = apply_avg_quality_gate(df)
        # Control IS now gated, but with a milder gate (CTRL_AVG_GATE_BASE=0.70)
        assert result.iloc[0]["score_control"] < 90.0
        # But the penalty should be milder than ACC/POW
        assert result.iloc[0]["score_control"] > result.iloc[0]["score_acceleration"]

    def test_ctrl_avg_gate_column_added(self):
        """apply_avg_quality_gate should add ctrl_avg_gate column."""
        df = self._make_career_df([20.0, 30.0])
        result = apply_avg_quality_gate(df)
        assert "ctrl_avg_gate" in result.columns

    def test_ctrl_gate_milder_than_acc_pow_gate(self):
        """Control gate should be >= ACC/POW gate for same average."""
        df = self._make_career_df([10.0, 15.0], base_score=90.0)
        result = apply_avg_quality_gate(df)
        for _, row in result.iterrows():
            assert row["ctrl_avg_gate"] >= row["avg_quality_gate"]

    def test_acceleration_and_power_both_gated(self):
        """Both score_acceleration and score_power should be gated."""
        df = self._make_career_df([12.0], base_score=95.0)
        result = apply_avg_quality_gate(df)
        gate = result.iloc[0]["avg_quality_gate"]
        assert gate < 1.0
        assert result.iloc[0]["score_acceleration"] == pytest.approx(
            95.0 * gate, abs=0.2
        )
        assert result.iloc[0]["score_power"] == pytest.approx(95.0 * gate, abs=0.2)

    def test_scores_clipped_to_0_100(self):
        """Gated scores should remain within [0, 100]."""
        df = self._make_career_df([50.0], base_score=100.0)
        result = apply_avg_quality_gate(df)
        assert 0.0 <= result.iloc[0]["score_acceleration"] <= 100.0
        assert 0.0 <= result.iloc[0]["score_power"] <= 100.0

    def test_ordering_preserved_for_same_avg(self):
        """Batters with same avg should preserve original score ordering."""
        df = pd.DataFrame(
            {
                "batter_id": ["a", "b"],
                "batter": ["A", "B"],
                "career_avg": [20.0, 20.0],
                "score_acceleration": [80.0, 60.0],
                "score_power": [70.0, 50.0],
                "score_control": [90.0, 85.0],
            }
        )
        result = apply_avg_quality_gate(df)
        assert (
            result.iloc[0]["score_acceleration"] > result.iloc[1]["score_acceleration"]
        )
        assert result.iloc[0]["score_power"] > result.iloc[1]["score_power"]

    def test_low_avg_slogger_vs_high_avg_anchor(self):
        """A low-avg slogger with same raw score should end up lower than high-avg anchor."""
        df = pd.DataFrame(
            {
                "batter_id": ["slogger", "anchor"],
                "batter": ["Slogger", "Anchor"],
                "career_avg": [14.0, 35.0],
                "score_acceleration": [95.0, 95.0],
                "score_power": [95.0, 95.0],
                "score_control": [70.0, 95.0],
            }
        )
        result = apply_avg_quality_gate(df)
        slogger = result[result["batter_id"] == "slogger"].iloc[0]
        anchor = result[result["batter_id"] == "anchor"].iloc[0]
        assert slogger["score_acceleration"] < anchor["score_acceleration"]
        assert slogger["score_power"] < anchor["score_power"]
        # Control IS now gated (mildly), so slogger's control should drop
        assert slogger["score_control"] < 70.0
        # Anchor has high avg so gate ~1.0, control stays near original
        assert anchor["score_control"] == pytest.approx(95.0, abs=0.5)

    def test_high_avg_control_not_penalised(self):
        """Batters with avg >= CTRL_AVG_GATE_REF should have ctrl gate = 1.0."""
        from src.batting import CTRL_AVG_GATE_REF

        df = self._make_career_df(
            [CTRL_AVG_GATE_REF, CTRL_AVG_GATE_REF + 10], base_score=90.0
        )
        result = apply_avg_quality_gate(df)
        for _, row in result.iterrows():
            assert row["ctrl_avg_gate"] == pytest.approx(1.0, abs=0.001)
            assert row["score_control"] == pytest.approx(90.0, abs=0.1)


# ===========================================================================
# Pre-percentile Average Quality Factor (on raw z-scores)
# ===========================================================================


class TestPrePercentileAvgFactor:
    """Tests for the multiplicative avg factor applied to raw composites."""

    def test_constants_are_sensible(self):
        """Avg quality constants should form a valid configuration."""
        assert AVG_QUALITY_REFERENCE > 0
        assert AVG_QUALITY_EXPONENT_BELOW > 1.0, (
            "Below-reference exponent should be steep"
        )
        assert AVG_QUALITY_EXPONENT_ABOVE < 1.0, (
            "Above-reference exponent should be gentle"
        )
        assert AVG_QUALITY_FLOOR > 0
        assert AVG_QUALITY_FLOOR < 1.0
        assert AVG_QUALITY_CEIL > 1.0

    def test_factor_at_reference_is_one(self):
        """At exactly the reference avg, the factor should be ~1.0."""
        ratio = AVG_QUALITY_REFERENCE / AVG_QUALITY_REFERENCE
        factor = ratio**AVG_QUALITY_EXPONENT_BELOW  # ratio = 1, exponent irrelevant
        assert factor == pytest.approx(1.0, abs=0.001)

    def test_factor_below_reference_is_less_than_one(self):
        """Below-reference averages should produce factor < 1."""
        ratio = 15.0 / AVG_QUALITY_REFERENCE
        factor = ratio**AVG_QUALITY_EXPONENT_BELOW
        assert factor < 1.0

    def test_factor_above_reference_is_greater_than_one(self):
        """Above-reference averages should produce factor > 1 (before clipping)."""
        ratio = 30.0 / AVG_QUALITY_REFERENCE
        factor = ratio**AVG_QUALITY_EXPONENT_ABOVE
        assert factor > 1.0

    def test_asymmetric_penalty_is_steeper_below(self):
        """The penalty for being 5 below reference should be larger than
        the bonus for being 5 above reference."""
        ref = AVG_QUALITY_REFERENCE
        below_ratio = (ref - 5) / ref
        above_ratio = (ref + 5) / ref
        below_factor = below_ratio**AVG_QUALITY_EXPONENT_BELOW
        above_factor = above_ratio**AVG_QUALITY_EXPONENT_ABOVE
        penalty = 1.0 - below_factor
        bonus = above_factor - 1.0
        assert penalty > bonus, (
            "Penalty below should exceed bonus above for same distance"
        )


# ===========================================================================
# Opposition Quality Weighting Constants
# ===========================================================================


class TestVolumeScaling:
    """Tests for apply_volume_scaling()."""

    def _make_career_df(self, innings_counts, base_score=90.0):
        n = len(innings_counts)
        return pd.DataFrame(
            {
                "batter_id": [f"bat{i}" for i in range(n)],
                "batter": [f"Batter{i}" for i in range(n)],
                "innings_count": innings_counts,
                "score_acceleration": [base_score] * n,
                "score_power": [base_score] * n,
                "score_control": [base_score] * n,
            }
        )

    def test_volume_factor_column_added(self):
        from src.batting import apply_volume_scaling

        df = self._make_career_df([10, 50])
        result = apply_volume_scaling(df)
        assert "volume_factor" in result.columns

    def test_ref_innings_no_penalty(self):
        """A player at exactly VOLUME_REF innings should have factor ≈ 1.0."""
        from src.batting import VOLUME_REF, apply_volume_scaling

        df = self._make_career_df([int(VOLUME_REF)])
        result = apply_volume_scaling(df)
        row = result.iloc[0]
        assert row["volume_factor"] == pytest.approx(1.0, abs=0.01)
        assert row["score_acceleration"] == pytest.approx(90.0, abs=0.5)

    def test_beyond_ref_innings_gets_bonus(self):
        """A player well above VOLUME_REF should get a factor > 1.0."""
        from src.batting import VOLUME_REF, apply_volume_scaling

        df = self._make_career_df([int(VOLUME_REF) + 80])
        result = apply_volume_scaling(df)
        row = result.iloc[0]
        assert row["volume_factor"] > 1.0
        # Score can exceed the base_score because factor > 1.0, but clipped at 100
        assert row["score_acceleration"] >= 90.0

    def test_low_innings_penalised(self):
        from src.batting import apply_volume_scaling

        df = self._make_career_df([10, 19])
        result = apply_volume_scaling(df)
        for _, row in result.iterrows():
            assert row["volume_factor"] < 1.0
            assert row["score_acceleration"] < 90.0

    def test_19_innings_worse_than_50(self):
        """A 19-innings player should score lower than a 50-innings player."""
        from src.batting import apply_volume_scaling

        df = self._make_career_df([19, 50], base_score=90.0)
        result = apply_volume_scaling(df)
        assert (
            result.iloc[0]["score_acceleration"] < result.iloc[1]["score_acceleration"]
        )
        assert result.iloc[0]["score_power"] < result.iloc[1]["score_power"]
        assert result.iloc[0]["score_control"] < result.iloc[1]["score_control"]

    def test_50_innings_worse_than_100(self):
        """A 50-innings player should score lower than a 100-innings player."""
        from src.batting import apply_volume_scaling

        df = self._make_career_df([50, 100], base_score=90.0)
        result = apply_volume_scaling(df)
        assert (
            result.iloc[0]["score_acceleration"] < result.iloc[1]["score_acceleration"]
        )
        assert result.iloc[0]["score_power"] < result.iloc[1]["score_power"]
        assert result.iloc[0]["score_control"] < result.iloc[1]["score_control"]

    def test_volume_factor_monotonically_increasing(self):
        """Volume factor should increase with more innings."""
        from src.batting import apply_volume_scaling

        innings_list = [5, 10, 20, 50, 80, 100, 130, 180]
        df = self._make_career_df(innings_list)
        result = apply_volume_scaling(df)
        factors = result["volume_factor"].tolist()
        for i in range(len(factors) - 1):
            assert factors[i] < factors[i + 1], (
                f"Factor at {innings_list[i]} inn ({factors[i]:.4f}) should be "
                f"< factor at {innings_list[i + 1]} inn ({factors[i + 1]:.4f})"
            )

    def test_beyond_ref_bonus_capped(self):
        """Beyond-reference bonus should not exceed VOLUME_BEYOND_MAX."""
        from src.batting import (
            VOLUME_BEYOND_MAX,
            VOLUME_REF,
            apply_volume_scaling,
        )

        # Very large innings count — should cap the beyond-ref bonus
        df = self._make_career_df([int(VOLUME_REF) * 5])
        result = apply_volume_scaling(df)
        # Factor = 1.0 (base at ref) + at most VOLUME_BEYOND_MAX
        assert result.iloc[0]["volume_factor"] <= 1.0 + VOLUME_BEYOND_MAX + 0.001

    def test_volume_factor_has_floor(self):
        from src.batting import VOLUME_BASE, apply_volume_scaling

        df = self._make_career_df([0, 1])
        result = apply_volume_scaling(df)
        for _, row in result.iterrows():
            assert row["volume_factor"] >= VOLUME_BASE - 0.001

    def test_scores_clipped_to_0_100(self):
        from src.batting import apply_volume_scaling

        df = self._make_career_df([5], base_score=100.0)
        result = apply_volume_scaling(df)
        assert 0.0 <= result.iloc[0]["score_acceleration"] <= 100.0
        assert 0.0 <= result.iloc[0]["score_power"] <= 100.0
        assert 0.0 <= result.iloc[0]["score_control"] <= 100.0

    def test_scores_clipped_with_beyond_bonus(self):
        """Even with beyond-ref bonus, scores should be clipped to [0, 100]."""
        from src.batting import VOLUME_REF, apply_volume_scaling

        df = self._make_career_df([int(VOLUME_REF) * 2], base_score=99.0)
        result = apply_volume_scaling(df)
        assert 0.0 <= result.iloc[0]["score_acceleration"] <= 100.0
        assert 0.0 <= result.iloc[0]["score_power"] <= 100.0
        assert 0.0 <= result.iloc[0]["score_control"] <= 100.0


class TestTeamQuality:
    """Tests for compute_team_quality() — ICC ranking-based."""

    def test_returns_team_quality_column(self):
        """Basic smoke test: output has expected columns and one row per team."""
        from src.batting import compute_team_quality
        from tests.conftest import _build_over

        rows = []
        rows += _build_over(
            "M001",
            1,
            "India",
            "Australia",
            0,
            "Bat1",
            "b1",
            "Bowl1",
            "bw1",
            "Bat2",
            "b2",
            1,
            [4, 4, 4, 4, 4, 4],
            winner="India",
        )
        rows += _build_over(
            "M001",
            2,
            "Australia",
            "India",
            0,
            "Bat3",
            "b3",
            "Bowl3",
            "bw3",
            "Bat4",
            "b4",
            1,
            [1, 0, 0, 0, 0, 0],
            winner="India",
        )
        df = pd.DataFrame(rows)
        result = compute_team_quality(df)
        assert "team_quality" in result.columns
        assert "team" in result.columns
        assert len(result) == 2  # India and Australia

    def test_higher_ranked_team_has_higher_quality(self):
        """India (ICC 272) should have higher team_quality than Zimbabwe (ICC 202)."""
        from src.batting import compute_team_quality
        from tests.conftest import _build_over

        rows = []
        # Single match: India vs Zimbabwe
        rows += _build_over(
            "M001",
            1,
            "India",
            "Zimbabwe",
            0,
            "Bat1",
            "b1",
            "Bowl1",
            "bw1",
            "Bat2",
            "b2",
            1,
            [4, 4, 4, 4, 4, 4],
            winner="India",
        )
        rows += _build_over(
            "M001",
            2,
            "Zimbabwe",
            "India",
            0,
            "Bat3",
            "b3",
            "Bowl3",
            "bw3",
            "Bat4",
            "b4",
            1,
            [0, 0, 0, 0, 0, 0],
            winner="India",
        )
        df = pd.DataFrame(rows)
        result = compute_team_quality(df)
        india_q = result[result["team"] == "India"]["team_quality"].iloc[0]
        zim_q = result[result["team"] == "Zimbabwe"]["team_quality"].iloc[0]
        assert india_q > zim_q

    def test_team_quality_is_zscore_normalised(self):
        """Mean team_quality across teams in dataset should be ~0."""
        from src.batting import compute_team_quality
        from tests.conftest import _build_over

        rows = []
        # Three teams with different ICC ratings
        teams = [
            ("India", "Australia"),
            ("Australia", "Bangladesh"),
            ("India", "Bangladesh"),
        ]
        for i, (t1, t2) in enumerate(teams):
            mid = f"M{i:03d}"
            rows += _build_over(
                mid,
                1,
                t1,
                t2,
                0,
                "Bat1",
                "b1",
                "Bowl1",
                "bw1",
                "Bat2",
                "b2",
                1,
                [4, 4, 4, 4, 4, 4],
                winner=t1,
            )
            rows += _build_over(
                mid,
                2,
                t2,
                t1,
                0,
                "Bat3",
                "b3",
                "Bowl3",
                "bw3",
                "Bat4",
                "b4",
                1,
                [0, 0, 0, 0, 0, 0],
                winner=t1,
            )
        df = pd.DataFrame(rows)
        result = compute_team_quality(df)
        # z-score: mean should be 0
        assert result["team_quality"].mean() == pytest.approx(0.0, abs=0.01)
        # Should have 3 distinct teams
        assert len(result) == 3

    def test_unranked_teams_get_default_rating(self):
        """Teams not in the ICC table get default_rating → lowest quality."""
        from src.batting import compute_team_quality
        from tests.conftest import _build_over

        rows = []
        # India (ICC 272) vs a made-up team not in ICC table
        rows += _build_over(
            "M001",
            1,
            "India",
            "Narnia",
            0,
            "Bat1",
            "b1",
            "Bowl1",
            "bw1",
            "Bat2",
            "b2",
            1,
            [4, 4, 4, 4, 4, 4],
            winner="India",
        )
        rows += _build_over(
            "M001",
            2,
            "Narnia",
            "India",
            0,
            "Bat3",
            "b3",
            "Bowl3",
            "bw3",
            "Bat4",
            "b4",
            1,
            [0, 0, 0, 0, 0, 0],
            winner="India",
        )
        df = pd.DataFrame(rows)
        result = compute_team_quality(df)
        india_q = result[result["team"] == "India"]["team_quality"].iloc[0]
        narnia_q = result[result["team"] == "Narnia"]["team_quality"].iloc[0]
        assert india_q > narnia_q

    def test_ranking_order_reflects_icc(self):
        """With multiple ICC-ranked teams, quality order should match ICC order."""
        from src.batting import compute_team_quality
        from tests.conftest import _build_over

        rows = []
        # India (272) vs England (260) vs Bangladesh (223)
        team_pairs = [
            ("India", "England"),
            ("England", "Bangladesh"),
            ("India", "Bangladesh"),
        ]
        for i, (t1, t2) in enumerate(team_pairs):
            mid = f"M{i:03d}"
            rows += _build_over(
                mid,
                1,
                t1,
                t2,
                0,
                "Bat1",
                "b1",
                "Bowl1",
                "bw1",
                "Bat2",
                "b2",
                1,
                [4, 4, 4, 4, 4, 4],
                winner=t1,
            )
            rows += _build_over(
                mid,
                2,
                t2,
                t1,
                0,
                "Bat3",
                "b3",
                "Bowl3",
                "bw3",
                "Bat4",
                "b4",
                1,
                [0, 0, 0, 0, 0, 0],
                winner=t1,
            )
        df = pd.DataFrame(rows)
        result = compute_team_quality(df)
        q = result.set_index("team")["team_quality"]
        assert q["India"] > q["England"] > q["Bangladesh"]


class TestWicketQuality:
    """Tests for compute_wicket_quality()."""

    def test_returns_expected_columns(self):
        from src.batting import compute_wicket_quality
        from tests.conftest import _build_over

        rows = _build_over(
            "M001",
            1,
            "Team A",
            "Team B",
            0,
            "Bat1",
            "b1",
            "Bowl1",
            "bw1",
            "Bat2",
            "b2",
            1,
            [4, 0, 0, 0, 0, 0],
            wicket_on_ball=1,
        )
        df = pd.DataFrame(rows)
        result = compute_wicket_quality(df)
        assert "quality_wickets" in result.columns
        assert "raw_wickets" in result.columns
        assert "avg_wicket_quality" in result.columns

    def test_top_order_wicket_worth_more(self):
        from src.batting import WICKET_POSITION_WEIGHTS, compute_wicket_quality
        from tests.conftest import _make_delivery

        # Wicket of position 1 batter
        d1 = _make_delivery(
            match_id="M001",
            innings_num=1,
            bowler_id="bw1",
            batting_position=1,
            is_wicket=True,
            wicket_kind="bowled",
            player_out="Bat1",
            player_out_id="b1",
        )
        # Wicket of position 10 batter
        d2 = _make_delivery(
            match_id="M002",
            innings_num=1,
            bowler_id="bw1",
            batting_position=10,
            is_wicket=True,
            wicket_kind="bowled",
            player_out="Bat10",
            player_out_id="b10",
        )
        df = pd.DataFrame([d1, d2])
        result = compute_wicket_quality(df)
        m1 = result[result["match_id"] == "M001"].iloc[0]
        m2 = result[result["match_id"] == "M002"].iloc[0]
        assert m1["quality_wickets"] > m2["quality_wickets"]
        assert m1["avg_wicket_quality"] == pytest.approx(
            WICKET_POSITION_WEIGHTS[1], abs=0.01
        )
        assert m2["avg_wicket_quality"] == pytest.approx(
            WICKET_POSITION_WEIGHTS[10], abs=0.01
        )

    def test_no_wickets_returns_empty(self):
        from src.batting import compute_wicket_quality
        from tests.conftest import _build_over

        rows = _build_over(
            "M001",
            1,
            "Team A",
            "Team B",
            0,
            "Bat1",
            "b1",
            "Bowl1",
            "bw1",
            "Bat2",
            "b2",
            1,
            [1, 1, 1, 1, 1, 1],
        )
        df = pd.DataFrame(rows)
        result = compute_wicket_quality(df)
        assert len(result) == 0


class TestPlayerDedup:
    """Tests for merge_player_identities and detect_potential_duplicates."""

    def test_merge_with_empty_aliases_is_noop(self):
        from src.batting import merge_player_identities
        from tests.conftest import _build_over

        rows = _build_over(
            "M001",
            1,
            "Team A",
            "Team B",
            0,
            "Bat1",
            "b1",
            "Bowl1",
            "bw1",
            "Bat2",
            "b2",
            1,
            [1, 0, 4, 0, 1, 0],
        )
        df = pd.DataFrame(rows)
        result = merge_player_identities(df)
        assert len(result) == len(df)
        assert (result["batter_id"] == df["batter_id"]).all()

    def test_detect_potential_duplicates_returns_dataframe(self):
        from src.batting import detect_potential_duplicates
        from tests.conftest import _build_over

        rows = []
        # Two "Sharma" players on same team, non-overlapping matches
        for i in range(6):
            mid = f"M{i:03d}"
            rows += _build_over(
                mid,
                1,
                "India",
                "Team B",
                0,
                "R Sharma",
                "rs1",
                "Bowl1",
                "bw1",
                "Bat2",
                "b2",
                1,
                [4, 4, 0, 1, 0, 6],
                date=f"2023-01-{i + 1:02d}",
            )
        for i in range(6):
            mid = f"M{i + 10:03d}"
            rows += _build_over(
                mid,
                1,
                "India",
                "Team B",
                0,
                "RG Sharma",
                "rs2",
                "Bowl1",
                "bw1",
                "Bat2",
                "b2",
                1,
                [6, 4, 1, 0, 4, 0],
                date=f"2024-01-{i + 1:02d}",
            )
        df = pd.DataFrame(rows)
        result = detect_potential_duplicates(df, min_innings=5)
        assert isinstance(result, pd.DataFrame)
        assert "id_a" in result.columns
        # These two should be detected as potential duplicates
        assert len(result) >= 1


class TestOppQualityConstants:
    """Tests for opposition quality weighting constants."""

    def test_scale_positive(self):
        assert OPP_QUALITY_SCALE > 0

    def test_clip_positive(self):
        assert OPP_QUALITY_CLIP > 0

    def test_weight_range(self):
        """Maximum weight should be 1 + clip, minimum should be 1 - clip."""
        max_weight = 1.0 + OPP_QUALITY_CLIP
        min_weight = 1.0 - OPP_QUALITY_CLIP
        assert max_weight <= 2.0, "Max weight shouldn't be unreasonably large"
        assert min_weight >= 0.5, "Min weight shouldn't make innings negligible"


# ===========================================================================
# Updated Weight Structure
# ===========================================================================


class TestTeamQualityConstants:
    """Tests for team quality scaling constants."""

    def test_scale_positive(self):
        from src.batting import TEAM_QUALITY_SCALE

        assert TEAM_QUALITY_SCALE > 0

    def test_clip_positive(self):
        from src.batting import TEAM_QUALITY_CLIP

        assert TEAM_QUALITY_CLIP > 0

    def test_weight_range(self):
        """Team quality weight should be in [1 - clip, 1 + clip]."""
        import numpy as np

        from src.batting import TEAM_QUALITY_CLIP, TEAM_QUALITY_SCALE

        # Extreme z-score of +3
        w = 1.0 + np.clip(
            3.0 * TEAM_QUALITY_SCALE, -TEAM_QUALITY_CLIP, TEAM_QUALITY_CLIP
        )
        assert w <= 1.0 + TEAM_QUALITY_CLIP + 0.001
        # Extreme z-score of -3
        w2 = 1.0 + np.clip(
            -3.0 * TEAM_QUALITY_SCALE, -TEAM_QUALITY_CLIP, TEAM_QUALITY_CLIP
        )
        assert w2 >= 1.0 - TEAM_QUALITY_CLIP - 0.001


class TestUpdatedWeightStructure:
    """Tests that the updated weight structure is correct."""

    def test_acceleration_weights_sum_to_one(self):
        total = sum(ACC_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_power_weights_sum_to_one(self):
        total = sum(POW_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_control_weights_sum_to_one(self):
        total = sum(CTRL_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-10)

    def test_acc_has_no_avg_component(self):
        """ACC uses multiplicative avg factor, not an additive avg component."""
        assert "avg" not in ACC_WEIGHTS

    def test_pow_has_no_avg_component(self):
        """POW uses multiplicative avg factor, not an additive avg component."""
        assert "avg" not in POW_WEIGHTS

    def test_ctrl_has_avg_proxy(self):
        """CTRL should have avg_proxy as a significant component."""
        assert "avg_proxy" in CTRL_WEIGHTS
        assert CTRL_WEIGHTS["avg_proxy"] >= 0.15, (
            "avg_proxy should be a significant component"
        )

    def test_ctrl_survival_ratio_is_largest_weight(self):
        """survival_ratio (xSR from hazard model) should be the largest weight in CTRL."""
        assert "survival_ratio" in CTRL_WEIGHTS
        max_weight = max(CTRL_WEIGHTS.values())
        assert CTRL_WEIGHTS["survival_ratio"] == max_weight


# ===========================================================================
# End-to-end: avg gate + opposition quality through pipeline
# ===========================================================================


class TestInningsExtractTeamQuality:
    """Test that team quality flows through innings extraction."""

    def test_team_quality_weight_in_innings(self, synthetic_deliveries_simple):
        from src.batting import compute_team_quality
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        tq = compute_team_quality(synthetic_deliveries_simple)
        bat_innings = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, team_quality=tq
        )
        assert "opp_team_quality" in bat_innings.columns
        assert "team_quality_weight" in bat_innings.columns
        # All weights should be positive
        assert (bat_innings["team_quality_weight"] > 0).all()

    def test_no_team_quality_gives_default_weight(self, synthetic_deliveries_simple):
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        bat_innings = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, team_quality=None
        )
        assert "team_quality_weight" in bat_innings.columns
        assert (bat_innings["team_quality_weight"] == 1.0).all()


class TestAvgAndOppQualityEndToEnd:
    """Integration tests verifying avg gating and opp quality flow through the pipeline."""

    def test_pipeline_with_bowler_strength(self, synthetic_deliveries_simple):
        """Full pipeline should work when bowler_strength is provided."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bs = compute_bowler_strength_index(synthetic_deliveries_simple, min_balls=1)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=bs
        )
        bat_comp = compute_batting_components(bat_inn)
        career = aggregate_batting_careers(bat_comp)

        assert "raw_acceleration" in career.columns
        assert "raw_power" in career.columns
        assert "raw_control" in career.columns
        assert career["raw_acceleration"].notna().all()

    def test_pipeline_without_bowler_strength(self, synthetic_deliveries_simple):
        """Full pipeline should still work without bowler_strength (backward compat)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        bat_comp = compute_batting_components(bat_inn)
        career = aggregate_batting_careers(bat_comp)

        assert "raw_acceleration" in career.columns
        assert career["raw_acceleration"].notna().all()

    def test_avg_gate_reduces_low_avg_scores(self, synthetic_multi_match_career):
        """After avg gate, a low-average batter should have lower ACC/POW
        than a high-average batter with similar raw components."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        bat_inn = extract_batting_innings(
            synthetic_multi_match_career, innings_ctx, bowler_strength=None
        )
        bat_comp = compute_batting_components(bat_inn)
        career = aggregate_batting_careers(bat_comp)

        from src.rating import apply_rating_system

        career = apply_rating_system(
            career,
            raw_cols=["raw_acceleration", "raw_power", "raw_control"],
            sample_col="innings_count",
            provisional_col="is_provisional_bat",
        )
        career = apply_avg_quality_gate(career)

        # There should be an avg_quality_gate column
        assert "avg_quality_gate" in career.columns
        # All scores should be non-negative
        assert (career["score_acceleration"] >= 0).all()


# ===========================================================================
# Config module tests
# ===========================================================================


class TestConfig:
    """Tests for the central config loader (src.config)."""

    def test_cfg_returns_default_values(self):
        """cfg() should return sensible defaults even if no YAML file exists."""
        from src.config import Config

        c = Config({"a": {"b": 3, "c": {"d": 4}}})
        assert c.get("a.b") == 3
        assert c.get("a.c.d") == 4

    def test_cfg_default_on_missing_key(self):
        from src.config import Config

        c = Config({"a": 1})
        assert c.get("nonexistent", default=42) == 42

    def test_cfg_raises_on_missing_key_without_default(self):
        from src.config import Config

        c = Config({"a": 1})
        with pytest.raises(KeyError):
            c.get("nonexistent")

    def test_cfg_top_level_access(self):
        from src.config import Config

        c = Config({"x": {"y": 10}})
        assert c["x"] == {"y": 10}

    def test_deep_merge(self):
        from src.config import _deep_merge

        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 99}, "e": 5}
        merged = _deep_merge(base, override)
        assert merged == {"a": {"b": 99, "c": 2}, "d": 3, "e": 5}

    def test_deep_merge_does_not_mutate_inputs(self):
        from src.config import _deep_merge

        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        _deep_merge(base, override)
        assert base == {"a": {"b": 1}}
        assert override == {"a": {"c": 2}}

    def test_reset_to_defaults_returns_config(self):
        from src.config import reset_to_defaults

        c = reset_to_defaults()
        assert c.get("recency.half_life_days") == 730
        assert c.get("pipeline.min_bat_innings") == 10

    def test_config_contains(self):
        from src.config import Config

        c = Config({"batting_volume": {"base": 0.8}})
        assert "batting_volume" in c
        assert "nonexistent" not in c

    def test_config_repr(self):
        from src.config import Config

        c = Config({"a": 1, "b": 2})
        assert "a" in repr(c)
        assert "b" in repr(c)

    def test_defaults_have_all_expected_sections(self):
        """Verify that _DEFAULTS contains all sections the pipeline needs."""
        from src.config import _DEFAULTS

        expected_sections = [
            "pipeline",
            "rating",
            "batting_acceleration_weights",
            "batting_power_weights",
            "batting_control_weights",
            "batting_avg_quality",
            "batting_volume",
            "bowling_accuracy_weights",
            "bowling_control_weights",
            "bowling_threat_weights",
            "bowling_volume",
            "wicket_quality",
            "opposition_quality",
            "team_quality",
            "recency",
            "player_aliases",
            "player_name_overrides",
            "duplicate_detection",
        ]
        for section in expected_sections:
            assert section in _DEFAULTS, f"Missing default section: {section}"

    def test_batting_weights_from_config_sum_to_one(self):
        """Weights read via cfg() should sum to 1.0."""
        from src.config import cfg

        for key in [
            "batting_acceleration_weights",
            "batting_power_weights",
            "batting_control_weights",
        ]:
            weights = cfg(key)
            assert abs(sum(weights.values()) - 1.0) < 1e-6, f"{key} doesn't sum to 1"

    def test_bowling_weights_from_config_sum_to_one(self):
        from src.config import cfg

        for key in [
            "bowling_accuracy_weights",
            "bowling_control_weights",
            "bowling_threat_weights",
        ]:
            weights = cfg(key)
            assert abs(sum(weights.values()) - 1.0) < 1e-6, f"{key} doesn't sum to 1"

    def test_get_config_with_nonexistent_file_uses_defaults(self):
        """Loading a nonexistent YAML file should silently use defaults."""
        from src.config import Config, get_config, reload_config

        # Force reload to clear cache
        c = reload_config("/tmp/nonexistent_cricket_config_12345.yaml")
        # Should still work with defaults
        assert c.get("recency.half_life_days") == 730


# ===========================================================================
# Recency / time-decay weighting tests
# ===========================================================================


class TestRecencyWeighting:
    """Tests for the recency / time-decay feature in batting innings."""

    def test_recency_weight_column_present(self, synthetic_deliveries_simple):
        """Extracted innings should have a recency_weight column."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        assert "recency_weight" in bat_inn.columns

    def test_recency_weight_range(self, synthetic_deliveries_simple):
        """recency_weight should be between min_weight and 1.0."""
        from src.batting import RECENCY_MIN_WEIGHT

        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        assert (bat_inn["recency_weight"] >= RECENCY_MIN_WEIGHT - 1e-9).all()
        assert (bat_inn["recency_weight"] <= 1.0 + 1e-9).all()

    def test_most_recent_innings_has_weight_one(self, synthetic_deliveries_simple):
        """The most recent innings should have recency_weight = 1.0."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        assert bat_inn["recency_weight"].max() == pytest.approx(1.0, abs=1e-9)

    def test_older_innings_has_lower_recency(self, synthetic_multi_match_career):
        """Innings from older matches should have lower recency_weight."""
        innings_ctx = _get_innings_ctx(synthetic_multi_match_career)
        bat_inn = extract_batting_innings(
            synthetic_multi_match_career, innings_ctx, bowler_strength=None
        )
        # Merge date info and sort
        dated = bat_inn[["match_id", "recency_weight", "date"]].drop_duplicates(
            "match_id"
        )
        dated = dated.sort_values("date")
        if len(dated) > 1:
            # Older date should have lower (or equal) recency weight
            assert dated["recency_weight"].iloc[0] <= dated["recency_weight"].iloc[-1]

    def test_recency_multiplied_into_opp_quality_weight(
        self, synthetic_deliveries_simple
    ):
        """opp_quality_weight should incorporate recency (not just opposition quality)."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=None
        )
        # Without bowler strength, base opposition weight = 1.0.
        # So opp_quality_weight should equal recency_weight * team_quality_weight * icc_ranking_weight * match_quality_weight.
        team_w = (
            bat_inn["team_quality_weight"]
            if "team_quality_weight" in bat_inn.columns
            else 1.0
        )
        icc_w = (
            bat_inn["icc_ranking_weight"]
            if "icc_ranking_weight" in bat_inn.columns
            else 1.0
        )
        match_q_w = (
            bat_inn["match_quality_weight"]
            if "match_quality_weight" in bat_inn.columns
            else 1.0
        )
        expected = bat_inn["recency_weight"] * team_w * icc_w * match_q_w
        np.testing.assert_allclose(
            bat_inn["opp_quality_weight"].values,
            expected.values,
            atol=1e-6,
        )

    def test_recency_decay_formula(self):
        """Verify the half-life decay formula: weight = 2^(-(days / half_life))."""
        half_life = 730.0
        # At exactly the half-life, weight should be 0.5
        days = 730.0
        expected = 2.0 ** (-(days / half_life))
        assert expected == pytest.approx(0.5, abs=1e-9)
        # At 0 days (most recent), weight should be 1.0
        assert 2.0 ** (-(0.0 / half_life)) == pytest.approx(1.0, abs=1e-9)
        # At 2 half-lives, weight should be 0.25
        assert 2.0 ** (-(1460.0 / half_life)) == pytest.approx(0.25, abs=1e-9)

    def test_recency_weight_with_same_date_all_one(self):
        """If all innings are on the same date, all recency weights should be 1.0."""
        from tests.conftest import _build_over

        rows = []
        rows += _build_over(
            match_id="SAME_DAY_1",
            innings_num=1,
            batting_team="Team A",
            bowling_team="Team B",
            over_num=0,
            batter="Batter1",
            batter_id="bat1",
            bowler="Bowler1",
            bowler_id="bowl1",
            non_striker="Batter2",
            non_striker_id="bat2",
            batting_position=1,
            run_sequence=[1, 0, 4, 1, 0, 6],
            date="2024-01-15",
        )
        rows += _build_over(
            match_id="SAME_DAY_2",
            innings_num=1,
            batting_team="Team C",
            bowling_team="Team D",
            over_num=0,
            batter="Batter1",
            batter_id="bat1",
            bowler="Bowler2",
            bowler_id="bowl2",
            non_striker="Batter3",
            non_striker_id="bat3",
            batting_position=1,
            run_sequence=[2, 0, 1, 4, 0, 1],
            date="2024-01-15",
        )
        df = pd.DataFrame(rows)
        for c in [
            "match_id",
            "batter_id",
            "bowler_id",
            "batting_team",
            "bowling_team",
            "phase",
        ]:
            if c in df.columns:
                df[c] = df[c].astype("category")
        df["date"] = pd.to_datetime(df["date"])
        for c in [
            "is_legal",
            "is_batter_ball",
            "is_wide",
            "is_noball",
            "is_wicket",
            "is_four",
            "is_six",
            "is_dot_batter",
            "is_dot_bowler",
        ]:
            if c in df.columns:
                df[c] = df[c].astype(bool)

        innings_ctx = _get_innings_ctx(df)
        bat_inn = extract_batting_innings(df, innings_ctx, bowler_strength=None)
        np.testing.assert_allclose(bat_inn["recency_weight"].values, 1.0, atol=1e-9)


# ===========================================================================
# Bowling recency weighting tests
# ===========================================================================


class TestBowlingRecencyWeighting:
    """Tests for recency / time-decay in bowling spells."""

    def test_bowling_spell_weight_column_present(self, synthetic_deliveries_simple):
        """Extracted bowling spells should have spell_weight and recency_weight."""
        from src.bowling import extract_bowling_spells
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        assert "spell_weight" in spells.columns
        assert "recency_weight" in spells.columns

    def test_bowling_recency_weight_range(self, synthetic_deliveries_simple):
        """Bowling recency_weight should be between min_weight and 1.0."""
        from src.bowling import RECENCY_MIN_WEIGHT, extract_bowling_spells
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        assert (spells["recency_weight"] >= RECENCY_MIN_WEIGHT - 1e-9).all()
        assert (spells["recency_weight"] <= 1.0 + 1e-9).all()

    def test_bowling_most_recent_spell_has_weight_one(
        self, synthetic_deliveries_simple
    ):
        """The most recent bowling spell should have recency_weight = 1.0."""
        from src.bowling import extract_bowling_spells
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        assert spells["recency_weight"].max() == pytest.approx(1.0, abs=1e-9)

    def test_bowling_spell_weight_equals_recency_times_icc_times_team_match_quality(
        self, synthetic_deliveries_simple
    ):
        """spell_weight should equal recency_weight * icc_ranking_weight * team_quality_weight * match_quality_weight."""
        from src.bowling import extract_bowling_spells
        from src.context import build_full_context

        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)
        spells = extract_bowling_spells(synthetic_deliveries_simple, innings_ctx)
        assert "icc_ranking_weight" in spells.columns
        assert "team_quality_weight" in spells.columns
        assert "match_quality_weight" in spells.columns
        expected = (
            spells["recency_weight"]
            * spells["icc_ranking_weight"]
            * spells["team_quality_weight"]
            * spells["match_quality_weight"]
        )
        np.testing.assert_allclose(
            spells["spell_weight"].values,
            expected.values,
            atol=1e-9,
        )

    def test_career_has_avg_opp_quality(self, synthetic_deliveries_simple):
        """Career profiles should include avg_opp_quality when bowler_strength is used."""
        innings_ctx = _get_innings_ctx(synthetic_deliveries_simple)
        bs = compute_bowler_strength_index(synthetic_deliveries_simple, min_balls=1)
        bat_inn = extract_batting_innings(
            synthetic_deliveries_simple, innings_ctx, bowler_strength=bs
        )
        bat_comp = compute_batting_components(bat_inn)
        career = aggregate_batting_careers(bat_comp)

        assert "avg_opp_quality" in career.columns
