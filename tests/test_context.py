"""
Unit tests for the context module: innings context, match context, phase par,
and the build_full_context orchestrator.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.context import (
    build_full_context,
    compute_innings_context,
    compute_match_context,
)

# ---------------------------------------------------------------------------
# compute_innings_context
# ---------------------------------------------------------------------------


class TestComputeInningsContext:
    """Tests for compute_innings_context()."""

    def test_basic_aggregation(self, synthetic_deliveries_simple):
        """Should produce one row per (match, innings, batting_team)."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 has 2 innings, M002 has 2 innings → 4 rows
        assert len(result) == 4

    def test_total_runs(self, synthetic_deliveries_simple):
        """Total runs should match hand-calculated sums."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 Inn 1: Batter1 scores 12+12=24, Batter2 scores 2 → total = 26
        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        assert len(m001_inn1) == 1
        assert m001_inn1.iloc[0]["total_runs"] == 26

        # M001 Inn 2: Batter3 scores 17+13=30
        m001_inn2 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 2)
        ]
        assert len(m001_inn2) == 1
        assert m001_inn2.iloc[0]["total_runs"] == 30

    def test_legal_balls(self, synthetic_deliveries_simple):
        """Legal balls count should match expected values."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 Inn 1: 3 overs × 6 balls = 18 legal balls
        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        assert m001_inn1.iloc[0]["legal_balls"] == 18

        # M001 Inn 2: 2 overs × 6 balls = 12 legal balls
        m001_inn2 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 2)
        ]
        assert m001_inn2.iloc[0]["legal_balls"] == 12

    def test_overs_bowled(self, synthetic_deliveries_simple):
        """Overs bowled should be legal_balls / 6."""
        result = compute_innings_context(synthetic_deliveries_simple)

        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        assert m001_inn1.iloc[0]["overs_bowled"] == pytest.approx(3.0)

    def test_innings_sr(self, synthetic_deliveries_simple):
        """Innings strike rate should be (total_runs / legal_balls) * 100."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 Inn 1: 26 runs / 18 balls * 100 ≈ 144.44
        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        expected_sr = 26 / 18 * 100.0
        assert m001_inn1.iloc[0]["innings_sr"] == pytest.approx(expected_sr, rel=1e-3)

    def test_run_rate(self, synthetic_deliveries_simple):
        """Run rate should be total_runs / overs_bowled."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 Inn 2: 30 runs / 2 overs = 15.0
        m001_inn2 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 2)
        ]
        assert m001_inn2.iloc[0]["run_rate"] == pytest.approx(15.0)

    def test_boundary_counts(self, synthetic_deliveries_simple):
        """Fours and sixes should be correctly counted."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 Inn 1: Batter1 has 4,4,4 (3 fours) and 6 (1 six). Batter2 has 0 fours, 0 sixes.
        # Over 0: 1,0,4,1,0,6 → 1 four, 1 six
        # Over 1: 4,4,1,0,1,2 → 2 fours, 0 sixes
        # Over 2: 0,1,0,0,1,0 → 0 fours, 0 sixes
        # Total: 3 fours, 1 six
        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        assert m001_inn1.iloc[0]["total_fours"] == 3
        assert m001_inn1.iloc[0]["total_sixes"] == 1

    def test_boundary_runs(self, synthetic_deliveries_simple):
        """Boundary runs = 4*fours + 6*sixes."""
        result = compute_innings_context(synthetic_deliveries_simple)

        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        expected = 3 * 4 + 1 * 6  # 18
        assert m001_inn1.iloc[0]["boundary_runs"] == expected

    def test_boundary_pct(self, synthetic_deliveries_simple):
        """Boundary pct = boundary_runs / total_runs."""
        result = compute_innings_context(synthetic_deliveries_simple)

        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        expected_pct = 18 / 26
        assert m001_inn1.iloc[0]["boundary_pct"] == pytest.approx(
            expected_pct, rel=1e-3
        )

    def test_boundary_rate(self, synthetic_deliveries_simple):
        """Boundary rate = (fours + sixes) / legal_balls."""
        result = compute_innings_context(synthetic_deliveries_simple)

        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        expected_rate = (3 + 1) / 18
        assert m001_inn1.iloc[0]["boundary_rate"] == pytest.approx(
            expected_rate, rel=1e-3
        )

    def test_dot_balls(self, synthetic_deliveries_simple):
        """Dot ball count should match expected values."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 Inn 1:
        # Over 0: 1,0,4,1,0,6 → dot bowler: balls 1,4 → 2 dots
        # Over 1: 4,4,1,0,1,2 → dot bowler: ball 3 → 1 dot
        # Over 2: 0,1,0,0,1,0 → dot bowler: balls 0,2,3,5 → 4 dots
        # Total: 7 bowler dots
        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        assert m001_inn1.iloc[0]["dot_balls_bowler"] == 7

    def test_dot_pct(self, synthetic_deliveries_simple):
        """Dot pct = dot_balls_bowler / legal_balls."""
        result = compute_innings_context(synthetic_deliveries_simple)

        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        expected_dot_pct = 7 / 18
        assert m001_inn1.iloc[0]["dot_pct"] == pytest.approx(expected_dot_pct, rel=1e-3)

    def test_wicket_count(self, synthetic_deliveries_simple):
        """Wicket count should be correct."""
        result = compute_innings_context(synthetic_deliveries_simple)

        # M001 Inn 1: wicket on over 1, ball 5 → 1 wicket
        m001_inn1 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 1)
        ]
        assert m001_inn1.iloc[0]["total_wickets"] == 1

        # M001 Inn 2: no wickets
        m001_inn2 = result[
            (result["match_id"] == "M001") & (result["innings_num"] == 2)
        ]
        assert m001_inn2.iloc[0]["total_wickets"] == 0

    def test_zero_runs_innings(self):
        """An innings with zero runs should not cause division by zero."""
        from tests.conftest import _build_over

        rows = _build_over(
            "M099",
            1,
            "Team Z",
            "Team W",
            0,
            "ZeroBatter",
            "zbat",
            "ZeroBowler",
            "zbowl",
            "ZeroPartner",
            "zpart",
            1,
            [0, 0, 0, 0, 0, 0],
        )
        df = pd.DataFrame(rows)
        result = compute_innings_context(df)

        assert len(result) == 1
        assert result.iloc[0]["total_runs"] == 0
        assert result.iloc[0]["innings_sr"] == 0.0
        assert result.iloc[0]["run_rate"] == 0.0
        assert result.iloc[0]["boundary_pct"] == 0.0
        assert result.iloc[0]["boundary_rate"] == 0.0

    def test_has_date_column(self, synthetic_deliveries_simple):
        """Should carry the date through."""
        result = compute_innings_context(synthetic_deliveries_simple)
        assert "date" in result.columns
        assert result["date"].notna().all()


# ---------------------------------------------------------------------------
# compute_match_context
# ---------------------------------------------------------------------------


class TestComputeMatchContext:
    """Tests for compute_match_context()."""

    def test_basic_aggregation(self, innings_context_simple):
        """Should produce one row per match."""
        result = compute_match_context(innings_context_simple)

        # 2 matches → 2 rows
        assert len(result) == 2

    def test_match_total_runs(self, innings_context_simple):
        """Total runs across both innings should be correct."""
        result = compute_match_context(innings_context_simple)

        # M001: 26 (inn1) + 30 (inn2) = 56
        m001 = result[result["match_id"] == "M001"].iloc[0]
        assert m001["match_total_runs"] == 56

        # M002: 11 (inn1) + 5 (inn2) = 16
        m002 = result[result["match_id"] == "M002"].iloc[0]
        assert m002["match_total_runs"] == 16

    def test_match_total_legal_balls(self, innings_context_simple):
        """Total legal balls across both innings."""
        result = compute_match_context(innings_context_simple)

        # M001: 18 (inn1) + 12 (inn2) = 30
        m001 = result[result["match_id"] == "M001"].iloc[0]
        assert m001["match_total_legal_balls"] == 30

    def test_match_par_sr(self, innings_context_simple):
        """Par SR = total_runs / total_legal_balls * 100."""
        result = compute_match_context(innings_context_simple)

        # M001: 56/30 * 100 ≈ 186.67
        m001 = result[result["match_id"] == "M001"].iloc[0]
        expected = 56 / 30 * 100.0
        assert m001["match_par_sr"] == pytest.approx(expected, rel=1e-3)

    def test_match_par_rr(self, innings_context_simple):
        """Par RR = total_runs / (total_legal_balls / 6)."""
        result = compute_match_context(innings_context_simple)

        # M001: 56 / (30/6) = 56 / 5 = 11.2
        m001 = result[result["match_id"] == "M001"].iloc[0]
        expected = 56 / 5.0
        assert m001["match_par_rr"] == pytest.approx(expected, rel=1e-3)

    def test_match_boundary_rate(self, innings_context_simple):
        """Match boundary rate = (fours+sixes) / legal_balls."""
        result = compute_match_context(innings_context_simple)

        # M001 Inn 1: 3 fours + 1 six = 4 boundaries
        # M001 Inn 2: Over0: 6,4,2,1,0,4 → 2 fours, 1 six; Over1: 1,1,1,4,0,6 → 1 four, 1 six
        # Inn 2 fours: 3, sixes: 2
        # Total: 6 fours, 3 sixes = 9 boundaries in 30 balls
        m001 = result[result["match_id"] == "M001"].iloc[0]
        total_fours = m001["match_total_fours"]
        total_sixes = m001["match_total_sixes"]
        expected_rate = (total_fours + total_sixes) / 30
        assert m001["match_boundary_rate"] == pytest.approx(expected_rate, rel=1e-3)

    def test_match_dot_pct(self, innings_context_simple):
        """Match dot pct = total_dot_balls / total_legal_balls."""
        result = compute_match_context(innings_context_simple)

        m001 = result[result["match_id"] == "M001"].iloc[0]
        total_dots = m001["match_total_dot_balls"]
        expected = total_dots / 30
        assert m001["match_dot_pct"] == pytest.approx(expected, rel=1e-3)

    def test_match_wickets_per_ball(self, innings_context_simple):
        """Wickets per ball = total_wickets / total_legal_balls."""
        result = compute_match_context(innings_context_simple)

        # M001: 1 wicket in 30 balls
        m001 = result[result["match_id"] == "M001"].iloc[0]
        assert m001["match_wickets_per_ball"] == pytest.approx(1 / 30, rel=1e-3)

    def test_num_innings(self, innings_context_simple):
        """num_innings should reflect how many innings were played."""
        result = compute_match_context(innings_context_simple)

        m001 = result[result["match_id"] == "M001"].iloc[0]
        assert m001["num_innings"] == 2

    def test_zero_balls_match_safe(self):
        """A match with zero legal balls (shouldn't happen, but safety check)."""
        # Create an innings context with 0 balls
        innings_ctx = pd.DataFrame(
            {
                "match_id": ["M999"],
                "innings_num": [1],
                "batting_team": ["Empty"],
                "total_runs": [0],
                "legal_balls": [0],
                "total_wickets": [0],
                "total_fours": [0],
                "total_sixes": [0],
                "dot_balls_bowler": [0],
                "date": [pd.Timestamp("2023-01-01")],
                "overs_bowled": [0.0],
                "run_rate": [0.0],
                "innings_sr": [0.0],
                "boundary_runs": [0],
                "boundary_pct": [0.0],
                "boundary_rate": [0.0],
                "dot_pct": [0.0],
                "total_deliveries": [0],
            }
        )
        result = compute_match_context(innings_ctx)

        assert len(result) == 1
        assert result.iloc[0]["match_par_sr"] == 0.0
        assert result.iloc[0]["match_par_rr"] == 0.0
        assert result.iloc[0]["match_boundary_rate"] == 0.0


# ---------------------------------------------------------------------------
# build_full_context
# ---------------------------------------------------------------------------


class TestBuildFullContext:
    """Tests for the full context builder."""

    def test_returns_tuple(self, synthetic_deliveries_simple):
        """Should return (innings_ctx, match_ctx) tuple."""
        innings_ctx, match_ctx = build_full_context(synthetic_deliveries_simple)

        assert isinstance(innings_ctx, pd.DataFrame)
        assert isinstance(match_ctx, pd.DataFrame)

    def test_innings_ctx_has_match_par(self, synthetic_deliveries_simple):
        """Innings context should have match_par_sr merged in."""
        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)

        assert "match_par_sr" in innings_ctx.columns
        assert "match_par_rr" in innings_ctx.columns
        assert innings_ctx["match_par_sr"].notna().all()

    def test_match_par_consistent(self, synthetic_deliveries_simple):
        """match_par_sr should be the same for both innings of the same match."""
        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)

        m001_pars = innings_ctx[innings_ctx["match_id"] == "M001"]["match_par_sr"]
        assert m001_pars.nunique() == 1

    def test_all_matches_present(self, synthetic_deliveries_simple):
        """All matches in the data should be in both outputs."""
        innings_ctx, match_ctx = build_full_context(synthetic_deliveries_simple)

        match_ids_inn = set(innings_ctx["match_id"].unique())
        match_ids_match = set(match_ctx["match_id"].unique())

        assert "M001" in match_ids_inn
        assert "M002" in match_ids_inn
        assert "M001" in match_ids_match
        assert "M002" in match_ids_match

    def test_innings_ctx_has_boundary_rate(self, synthetic_deliveries_simple):
        """Innings context should have match_boundary_rate."""
        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)

        assert "match_boundary_rate" in innings_ctx.columns

    def test_innings_ctx_has_wickets_per_ball(self, synthetic_deliveries_simple):
        """Innings context should have match_wickets_per_ball."""
        innings_ctx, _ = build_full_context(synthetic_deliveries_simple)

        assert "match_wickets_per_ball" in innings_ctx.columns

    def test_match_par_sr_values(self, synthetic_deliveries_simple):
        """Spot check the actual match par SR values."""
        innings_ctx, match_ctx = build_full_context(synthetic_deliveries_simple)

        # M001: 56 runs / 30 balls * 100 ≈ 186.67
        m001_par = match_ctx[match_ctx["match_id"] == "M001"]["match_par_sr"].iloc[0]
        assert m001_par == pytest.approx(56 / 30 * 100, rel=1e-3)

        # M002: 16 runs / 12 balls * 100 ≈ 133.33
        m002_par = match_ctx[match_ctx["match_id"] == "M002"]["match_par_sr"].iloc[0]
        assert m002_par == pytest.approx(16 / 12 * 100, rel=1e-3)


# ---------------------------------------------------------------------------
# Phase-par computation (tested via batting module helper)
# ---------------------------------------------------------------------------


class TestPhasePar:
    """Tests for phase-specific par SR computation."""

    def test_phase_par_computed_for_multi_phase_match(
        self, synthetic_deliveries_with_phases
    ):
        """Match M010 spans PP, middle, death — all pars should exist."""
        from src.batting import _compute_phase_par_sr

        result = _compute_phase_par_sr(synthetic_deliveries_with_phases)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["match_id"] == "M010"
        assert pd.notna(row["pp_par_sr"])
        assert pd.notna(row["middle_par_sr"])
        assert pd.notna(row["death_par_sr"])

    def test_death_par_higher_than_middle(self, synthetic_deliveries_with_phases):
        """In our synthetic data, death overs have more big hits → higher par."""
        from src.batting import _compute_phase_par_sr

        result = _compute_phase_par_sr(synthetic_deliveries_with_phases)
        row = result.iloc[0]

        # Death overs (18-19): 23 + 21 = 44 runs in 12 balls → SR 366.7
        # Middle overs (8-9): 5 + 6 = 11 runs in 12 balls → SR 91.7
        assert row["death_par_sr"] > row["middle_par_sr"]

    def test_phase_par_sr_values(self, synthetic_deliveries_with_phases):
        """Spot-check phase par SR values against hand calculations."""
        from src.batting import _compute_phase_par_sr

        result = _compute_phase_par_sr(synthetic_deliveries_with_phases)
        row = result.iloc[0]

        # PP (overs 0-1): 8 + 11 = 19 runs in 12 balls → SR = 19/12*100 ≈ 158.33
        assert row["pp_par_sr"] == pytest.approx(19 / 12 * 100, rel=0.05)

        # Middle (overs 8-9): 5 + 6 = 11 runs in 12 balls → SR ≈ 91.67
        assert row["middle_par_sr"] == pytest.approx(11 / 12 * 100, rel=0.05)

        # Death (overs 18-19): 23 + 21 = 44 runs in 12 balls → SR ≈ 366.67
        assert row["death_par_sr"] == pytest.approx(44 / 12 * 100, rel=0.05)

    def test_single_phase_match_has_nan_for_others(self, synthetic_deliveries_simple):
        """Matches with only powerplay overs should have NaN for middle/death."""
        from src.batting import _compute_phase_par_sr

        result = _compute_phase_par_sr(synthetic_deliveries_simple)

        # Both M001 and M002 only have overs 0-2 (powerplay)
        for _, row in result.iterrows():
            assert pd.notna(row["pp_par_sr"])
            assert pd.isna(row["middle_par_sr"])
            assert pd.isna(row["death_par_sr"])


# ---------------------------------------------------------------------------
# Extras handling in context
# ---------------------------------------------------------------------------


class TestContextWithExtras:
    """Tests that extras (wides, no-balls) are handled correctly in context."""

    def test_total_runs_includes_extras(self, synthetic_deliveries_with_extras):
        """Total runs should include wide and no-ball extras."""
        result = compute_innings_context(synthetic_deliveries_with_extras)

        # Deliveries:
        # wide: 1, legal: 1, legal: 0, wide: 1, legal: 4,
        # noball: 1+1=2, legal: 0, legal: 6, legal: 2
        # Total: 1 + 1 + 0 + 1 + 4 + 2 + 0 + 6 + 2 = 17
        assert result.iloc[0]["total_runs"] == 17

    def test_legal_balls_excludes_wides_noballs(self, synthetic_deliveries_with_extras):
        """Legal balls should not count wides or no-balls."""
        result = compute_innings_context(synthetic_deliveries_with_extras)

        # 6 legal deliveries out of 9 total
        assert result.iloc[0]["legal_balls"] == 6

    def test_innings_sr_uses_legal_balls(self, synthetic_deliveries_with_extras):
        """Strike rate should use legal balls in the denominator."""
        result = compute_innings_context(synthetic_deliveries_with_extras)

        # 17 runs / 6 legal balls * 100 ≈ 283.33
        expected = 17 / 6 * 100.0
        assert result.iloc[0]["innings_sr"] == pytest.approx(expected, rel=1e-3)

    def test_total_deliveries_includes_all(self, synthetic_deliveries_with_extras):
        """Total deliveries should count everything (including wides/noballs)."""
        result = compute_innings_context(synthetic_deliveries_with_extras)

        assert result.iloc[0]["total_deliveries"] == 9


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestContextEdgeCases:
    """Edge case tests for context computations."""

    def test_single_delivery_match(self):
        """A match with just one delivery should work."""
        from tests.conftest import _make_delivery

        d = _make_delivery(
            match_id="M_SINGLE",
            innings_num=1,
            batting_team="Solo",
            bowling_team="Other",
            batter_runs=6,
            total_runs=6,
            is_six=True,
            is_dot_batter=False,
            is_dot_bowler=False,
        )
        df = pd.DataFrame([d])

        innings_ctx = compute_innings_context(df)
        assert len(innings_ctx) == 1
        assert innings_ctx.iloc[0]["total_runs"] == 6
        assert innings_ctx.iloc[0]["legal_balls"] == 1
        assert innings_ctx.iloc[0]["innings_sr"] == pytest.approx(600.0)

        match_ctx = compute_match_context(innings_ctx)
        assert len(match_ctx) == 1
        assert match_ctx.iloc[0]["match_par_sr"] == pytest.approx(600.0)

    def test_multiple_teams_same_match(self):
        """Two innings from different teams in the same match."""
        from tests.conftest import _build_over

        rows = []
        # Inn 1: Team Alpha scores 10 in one over
        rows += _build_over(
            "MTEST",
            1,
            "Alpha",
            "Beta",
            0,
            "A1",
            "a1",
            "B1",
            "b1",
            "A2",
            "a2",
            1,
            [1, 2, 1, 4, 0, 2],
        )
        # Inn 2: Team Beta scores 8 in one over
        rows += _build_over(
            "MTEST",
            2,
            "Beta",
            "Alpha",
            0,
            "B1",
            "b1",
            "A1",
            "a1",
            "B2",
            "b2",
            1,
            [0, 0, 4, 1, 1, 2],
        )
        df = pd.DataFrame(rows)

        innings_ctx = compute_innings_context(df)
        assert len(innings_ctx) == 2

        match_ctx = compute_match_context(innings_ctx)
        assert len(match_ctx) == 1

        # Alpha: 1+2+1+4+0+2 = 10, Beta: 0+0+4+1+1+2 = 8
        # Total: 18 runs / 12 balls * 100 = 150.0
        assert match_ctx.iloc[0]["match_par_sr"] == pytest.approx(150.0)

    def test_context_columns_are_numeric(self, synthetic_deliveries_simple):
        """All computed columns should be numeric types."""
        result = compute_innings_context(synthetic_deliveries_simple)

        numeric_cols = [
            "total_runs",
            "legal_balls",
            "total_wickets",
            "overs_bowled",
            "run_rate",
            "innings_sr",
            "boundary_runs",
            "boundary_pct",
            "boundary_rate",
            "dot_pct",
        ]
        for col in numeric_cols:
            assert pd.api.types.is_numeric_dtype(result[col]), (
                f"Column '{col}' should be numeric but is {result[col].dtype}"
            )

    def test_match_context_columns_are_numeric(self, innings_context_simple):
        """All match context columns should be numeric."""
        result = compute_match_context(innings_context_simple)

        numeric_cols = [
            "match_total_runs",
            "match_total_legal_balls",
            "match_par_sr",
            "match_par_rr",
            "match_boundary_rate",
            "match_dot_pct",
            "match_wickets_per_ball",
        ]
        for col in numeric_cols:
            assert pd.api.types.is_numeric_dtype(result[col]), (
                f"Column '{col}' should be numeric but is {result[col].dtype}"
            )

    def test_no_nan_in_core_fields(self, synthetic_deliveries_simple):
        """Core aggregated fields should not have NaN."""
        innings_ctx, match_ctx = build_full_context(synthetic_deliveries_simple)

        for col in ["total_runs", "legal_balls", "innings_sr", "match_par_sr"]:
            assert innings_ctx[col].notna().all(), f"NaN found in innings_ctx['{col}']"

        for col in [
            "match_total_runs",
            "match_total_legal_balls",
            "match_par_sr",
            "match_par_rr",
        ]:
            assert match_ctx[col].notna().all(), f"NaN found in match_ctx['{col}']"
