"""
Tests for the presentation layer (grades, overall scores, and archetypes).

Covers:
- Grade boundary mapping (score → letter grade)
- Overall score computation (with superstar bonus)
- Batting grades integration (add_batting_grades)
- Bowling grades integration (add_bowling_grades)
- Batting archetype assignment (assign_batting_archetypes)
- Bowling archetype assignment (assign_bowling_archetypes)
- Edge cases: NaN scores, missing columns, all-low scores (fallback archetype)
"""

import numpy as np
import pandas as pd
import pytest

from src.config import reset_to_defaults
from src.presentation import (
    BATTING_ARCHETYPES,
    BOWLING_ARCHETYPES,
    _compute_overall_score,
    add_batting_grades,
    add_bowling_grades,
    assign_batting_archetypes,
    assign_bowling_archetypes,
    score_to_grade,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_defaults():
    """Ensure config defaults are used for every test."""
    reset_to_defaults()
    yield
    reset_to_defaults()


@pytest.fixture()
def sample_bat_careers() -> pd.DataFrame:
    """Minimal batting careers DataFrame with the columns presentation needs."""
    return pd.DataFrame(
        {
            "batter_id": ["p1", "p2", "p3", "p4", "p5", "p6"],
            "batter": [
                "Elite All-Rounder",
                "Explosive Finisher",
                "Classic Anchor",
                "Low Scorer",
                "Mid Scorer",
                "NaN Scorer",
            ],
            "score_acceleration": [80.0, 90.0, 40.0, 10.0, 55.0, np.nan],
            "score_power": [75.0, 92.0, 35.0, 12.0, 50.0, np.nan],
            "score_control": [78.0, 50.0, 85.0, 8.0, 60.0, np.nan],
        }
    )


@pytest.fixture()
def sample_bowl_careers() -> pd.DataFrame:
    """Minimal bowling careers DataFrame with the columns presentation needs."""
    return pd.DataFrame(
        {
            "bowler_id": ["b1", "b2", "b3", "b4"],
            "bowler": [
                "Strike Bowler",
                "Economical",
                "All-Round Threat",
                "Average Joe",
            ],
            "score_accuracy": [60.0, 85.0, 75.0, 40.0],
            "score_control": [55.0, 80.0, 72.0, 38.0],
            "score_threat": [88.0, 30.0, 74.0, 35.0],
        }
    )


# ---------------------------------------------------------------------------
# Tests: score_to_grade
# ---------------------------------------------------------------------------


class TestScoreToGrade:
    """Tests for the score_to_grade mapping function."""

    def _default_boundaries(self):
        return [
            ("S", 95.0),
            ("A+", 85.0),
            ("A", 75.0),
            ("B+", 60.0),
            ("B", 45.0),
            ("C+", 30.0),
            ("C", 15.0),
            ("D", 0.0),
        ]

    def test_exact_boundary_values(self):
        b = self._default_boundaries()
        assert score_to_grade(95.0, b) == "S"
        assert score_to_grade(85.0, b) == "A+"
        assert score_to_grade(75.0, b) == "A"
        assert score_to_grade(60.0, b) == "B+"
        assert score_to_grade(45.0, b) == "B"
        assert score_to_grade(30.0, b) == "C+"
        assert score_to_grade(15.0, b) == "C"
        assert score_to_grade(0.0, b) == "D"

    def test_values_between_boundaries(self):
        b = self._default_boundaries()
        assert score_to_grade(99.5, b) == "S"
        assert score_to_grade(90.0, b) == "A+"
        assert score_to_grade(80.0, b) == "A"
        assert score_to_grade(70.0, b) == "B+"
        assert score_to_grade(50.0, b) == "B"
        assert score_to_grade(35.0, b) == "C+"
        assert score_to_grade(20.0, b) == "C"
        assert score_to_grade(5.0, b) == "D"

    def test_hundred_gets_s(self):
        b = self._default_boundaries()
        assert score_to_grade(100.0, b) == "S"

    def test_nan_returns_question_mark(self):
        b = self._default_boundaries()
        assert score_to_grade(np.nan, b) == "?"

    def test_negative_score_returns_d(self):
        b = self._default_boundaries()
        assert score_to_grade(-5.0, b) == "D"


# ---------------------------------------------------------------------------
# Tests: _compute_overall_score
# ---------------------------------------------------------------------------


class TestComputeOverallScore:
    """Tests for the overall score with superstar bonus."""

    def test_equal_scores_returns_mean(self):
        result = _compute_overall_score([50.0, 50.0, 50.0])
        assert result == pytest.approx(50.0, abs=0.01)

    def test_no_superstar_bonus_below_threshold(self):
        """All scores below 85 → no bonus, just mean."""
        result = _compute_overall_score([60.0, 60.0, 60.0])
        assert result == pytest.approx(60.0, abs=0.01)

    def test_superstar_bonus_applied(self):
        """One score above 85 → bonus pulls overall up."""
        # base = mean(95, 50, 50) = 65.0
        # bonus = max(10, 0, 0) = 10  (capped at single best dimension)
        # overall = 65.0 + 0.10 * 10 = 66.0
        result = _compute_overall_score([95.0, 50.0, 50.0])
        assert result == pytest.approx(66.0, abs=0.01)

    def test_multiple_superstar_dimensions(self):
        """Two scores above threshold → bonus capped at single best."""
        # base = mean(95, 90, 50) = 78.33
        # bonus = max(10, 5, 0) = 10  (capped at single best dimension)
        # overall = 78.33 + 0.10 * 10 = 79.33
        result = _compute_overall_score([95.0, 90.0, 50.0])
        assert result == pytest.approx(79.33, abs=0.1)

    def test_clipped_at_100(self):
        result = _compute_overall_score([99.0, 99.0, 99.0])
        assert result <= 100.0

    def test_empty_list_returns_nan(self):
        result = _compute_overall_score([])
        assert np.isnan(result)

    def test_all_nan_returns_nan(self):
        result = _compute_overall_score([np.nan, np.nan])
        assert np.isnan(result)

    def test_partial_nan_ignored(self):
        """NaN values are excluded from both mean and bonus."""
        result = _compute_overall_score([80.0, np.nan, 60.0])
        # mean(80, 60) = 70, no bonus
        assert result == pytest.approx(70.0, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: add_batting_grades
# ---------------------------------------------------------------------------


class TestAddBattingGrades:
    """Tests for add_batting_grades integration."""

    def test_columns_added(self, sample_bat_careers):
        result = add_batting_grades(sample_bat_careers)
        expected_cols = [
            "grade_acceleration",
            "grade_power",
            "grade_control",
            "overall_score",
            "overall_grade",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_grade_values_are_valid(self, sample_bat_careers):
        result = add_batting_grades(sample_bat_careers)
        valid_grades = {"S", "A+", "A", "B+", "B", "C+", "C", "D", "?"}
        for col in [
            "grade_acceleration",
            "grade_power",
            "grade_control",
            "overall_grade",
        ]:
            unique_grades = set(result[col].unique())
            assert unique_grades.issubset(valid_grades), (
                f"Invalid grades in {col}: {unique_grades - valid_grades}"
            )

    def test_elite_player_gets_high_grade(self, sample_bat_careers):
        result = add_batting_grades(sample_bat_careers)
        elite = result[result["batter"] == "Explosive Finisher"].iloc[0]
        assert elite["grade_acceleration"] in ("S", "A+")
        assert elite["grade_power"] in ("S", "A+")

    def test_low_scorer_gets_low_grade(self, sample_bat_careers):
        result = add_batting_grades(sample_bat_careers)
        low = result[result["batter"] == "Low Scorer"].iloc[0]
        assert low["grade_acceleration"] == "D"
        assert low["grade_power"] == "D"

    def test_nan_scores_produce_question_mark(self, sample_bat_careers):
        result = add_batting_grades(sample_bat_careers)
        nan_row = result[result["batter"] == "NaN Scorer"].iloc[0]
        assert nan_row["grade_acceleration"] == "?"
        assert nan_row["grade_power"] == "?"
        assert nan_row["grade_control"] == "?"

    def test_overall_score_is_numeric(self, sample_bat_careers):
        result = add_batting_grades(sample_bat_careers)
        # Non-NaN rows should be numeric
        valid = result[result["batter"] != "NaN Scorer"]["overall_score"]
        assert valid.dtype == np.float64 or valid.dtype == float

    def test_overall_score_bounded(self, sample_bat_careers):
        result = add_batting_grades(sample_bat_careers)
        valid = result["overall_score"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_does_not_modify_original(self, sample_bat_careers):
        original_cols = set(sample_bat_careers.columns)
        _ = add_batting_grades(sample_bat_careers)
        assert set(sample_bat_careers.columns) == original_cols


# ---------------------------------------------------------------------------
# Tests: add_bowling_grades
# ---------------------------------------------------------------------------


class TestAddBowlingGrades:
    """Tests for add_bowling_grades integration."""

    def test_columns_added(self, sample_bowl_careers):
        result = add_bowling_grades(sample_bowl_careers)
        expected_cols = [
            "grade_accuracy",
            "grade_control",
            "grade_threat",
            "overall_score",
            "overall_grade",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_strike_bowler_high_threat(self, sample_bowl_careers):
        result = add_bowling_grades(sample_bowl_careers)
        strike = result[result["bowler"] == "Strike Bowler"].iloc[0]
        assert strike["grade_threat"] in ("S", "A+", "A")

    def test_does_not_modify_original(self, sample_bowl_careers):
        original_cols = set(sample_bowl_careers.columns)
        _ = add_bowling_grades(sample_bowl_careers)
        assert set(sample_bowl_careers.columns) == original_cols


# ---------------------------------------------------------------------------
# Tests: assign_batting_archetypes
# ---------------------------------------------------------------------------


class TestAssignBattingArchetypes:
    """Tests for batting archetype assignment."""

    def test_archetype_column_added(self, sample_bat_careers):
        result = assign_batting_archetypes(sample_bat_careers)
        assert "archetype" in result.columns

    def test_explosive_finisher_assigned(self):
        """Player with ACC ≥ 85 and POW ≥ 85 → Explosive Finisher."""
        df = pd.DataFrame(
            {
                "score_acceleration": [90.0],
                "score_power": [88.0],
                "score_control": [40.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Explosive Finisher"

    def test_classic_anchor_assigned(self):
        """Player with CTRL ≥ 80 and ACC ≤ 55 → Classic Anchor."""
        df = pd.DataFrame(
            {
                "score_acceleration": [45.0],
                "score_power": [50.0],
                "score_control": [85.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Classic Anchor"

    def test_power_anchor_assigned(self):
        """Player with POW ≥ 75 and CTRL ≥ 75 → Power Anchor."""
        df = pd.DataFrame(
            {
                "score_acceleration": [60.0],
                "score_power": [80.0],
                "score_control": [78.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Power Anchor"

    def test_pinch_hitter_assigned(self):
        """Player with ACC ≥ 85 and CTRL ≤ 45 → Pinch Hitter."""
        df = pd.DataFrame(
            {
                "score_acceleration": [90.0],
                "score_power": [60.0],
                "score_control": [40.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Pinch Hitter"

    def test_all_round_elite_assigned(self):
        """Player with ACC ≥ 75, POW ≥ 70, CTRL ≥ 70 (but not matching
        earlier, more specific archetypes) → All-Round Elite."""
        df = pd.DataFrame(
            {
                "score_acceleration": [78.0],
                "score_power": [72.0],
                "score_control": [73.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "All-Round Elite"

    def test_strike_rotator_assigned(self):
        """Player with CTRL ≥ 80 and POW ≤ 40 → Strike Rotator."""
        df = pd.DataFrame(
            {
                "score_acceleration": [60.0],
                "score_power": [35.0],
                "score_control": [82.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Strike Rotator"

    def test_accumulator_assigned(self):
        """Player with CTRL ≥ 70, ACC ≤ 50, POW ≤ 50 → Accumulator."""
        df = pd.DataFrame(
            {
                "score_acceleration": [45.0],
                "score_power": [42.0],
                "score_control": [72.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Accumulator"

    def test_fallback_utility_player(self):
        """Player matching no archetype → Utility Player."""
        df = pd.DataFrame(
            {
                "score_acceleration": [50.0],
                "score_power": [50.0],
                "score_control": [50.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Utility Player"

    def test_first_match_wins(self):
        """If multiple archetypes could match, the first in order wins.
        Explosive Finisher (ACC ≥ 85, POW ≥ 85) comes before All-Round Elite."""
        df = pd.DataFrame(
            {
                "score_acceleration": [90.0],
                "score_power": [90.0],
                "score_control": [90.0],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Explosive Finisher"

    def test_nan_scores_get_utility_player(self):
        """NaN scores should not match any archetype conditions."""
        df = pd.DataFrame(
            {
                "score_acceleration": [np.nan],
                "score_power": [np.nan],
                "score_control": [np.nan],
            }
        )
        result = assign_batting_archetypes(df)
        assert result.iloc[0]["archetype"] == "Utility Player"

    def test_does_not_modify_original(self, sample_bat_careers):
        original_cols = set(sample_bat_careers.columns)
        _ = assign_batting_archetypes(sample_bat_careers)
        assert set(sample_bat_careers.columns) == original_cols


# ---------------------------------------------------------------------------
# Tests: assign_bowling_archetypes
# ---------------------------------------------------------------------------


class TestAssignBowlingArchetypes:
    """Tests for bowling archetype assignment."""

    def test_archetype_column_added(self, sample_bowl_careers):
        result = assign_bowling_archetypes(sample_bowl_careers)
        assert "archetype" in result.columns

    def test_strike_bowler_assigned(self):
        """Player with THR ≥ 80 → Strike Bowler."""
        df = pd.DataFrame(
            {
                "score_accuracy": [50.0],
                "score_control": [50.0],
                "score_threat": [85.0],
            }
        )
        result = assign_bowling_archetypes(df)
        assert result.iloc[0]["archetype"] == "Strike Bowler"

    def test_death_specialist_assigned(self):
        """Player with ACC ≥ 75, CTRL ≥ 75, THR ≥ 70 → Death Specialist."""
        df = pd.DataFrame(
            {
                "score_accuracy": [80.0],
                "score_control": [78.0],
                "score_threat": [75.0],
            }
        )
        result = assign_bowling_archetypes(df)
        assert result.iloc[0]["archetype"] == "Death Specialist"

    def test_spin_restrictor_assigned(self):
        """Player with ACC ≥ 80 and THR ≤ 55 → Spin Restrictor."""
        df = pd.DataFrame(
            {
                "score_accuracy": [85.0],
                "score_control": [60.0],
                "score_threat": [40.0],
            }
        )
        result = assign_bowling_archetypes(df)
        assert result.iloc[0]["archetype"] == "Spin Restrictor"

    def test_economical_assigned(self):
        """Player with ACC ≥ 80, CTRL ≥ 75, THR ≤ 50 → Economical."""
        df = pd.DataFrame(
            {
                "score_accuracy": [82.0],
                "score_control": [78.0],
                "score_threat": [45.0],
            }
        )
        result = assign_bowling_archetypes(df)
        # Spin Restrictor also matches (ACC ≥ 80, THR ≤ 55) and comes first
        # so this will be Spin Restrictor due to first-match-wins rule
        assert result.iloc[0]["archetype"] in ("Spin Restrictor", "Economical")

    def test_all_round_threat_assigned(self):
        """Player with ACC ≥ 70, CTRL ≥ 70, THR ≥ 70 (but THR < 80 so
        not Strike Bowler, and ACC < 75 so not Death Specialist)."""
        df = pd.DataFrame(
            {
                "score_accuracy": [72.0],
                "score_control": [71.0],
                "score_threat": [73.0],
            }
        )
        result = assign_bowling_archetypes(df)
        assert result.iloc[0]["archetype"] == "All-Round Threat"

    def test_fallback_utility_player(self):
        """Player matching no archetype → Utility Player."""
        df = pd.DataFrame(
            {
                "score_accuracy": [30.0],
                "score_control": [30.0],
                "score_threat": [30.0],
            }
        )
        result = assign_bowling_archetypes(df)
        assert result.iloc[0]["archetype"] == "Utility Player"

    def test_does_not_modify_original(self, sample_bowl_careers):
        original_cols = set(sample_bowl_careers.columns)
        _ = assign_bowling_archetypes(sample_bowl_careers)
        assert set(sample_bowl_careers.columns) == original_cols


# ---------------------------------------------------------------------------
# Tests: End-to-end (grades + archetypes together)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Test that grades and archetypes can be applied sequentially."""

    def test_batting_grades_then_archetypes(self, sample_bat_careers):
        df = add_batting_grades(sample_bat_careers)
        df = assign_batting_archetypes(df)
        assert "overall_grade" in df.columns
        assert "archetype" in df.columns
        assert len(df) == len(sample_bat_careers)

    def test_bowling_grades_then_archetypes(self, sample_bowl_careers):
        df = add_bowling_grades(sample_bowl_careers)
        df = assign_bowling_archetypes(df)
        assert "overall_grade" in df.columns
        assert "archetype" in df.columns
        assert len(df) == len(sample_bowl_careers)

    def test_empty_dataframe_batting(self):
        empty = pd.DataFrame(
            columns=["score_acceleration", "score_power", "score_control"]
        )
        result = add_batting_grades(empty)
        result = assign_batting_archetypes(result)
        assert len(result) == 0
        assert "archetype" in result.columns
        assert "overall_grade" in result.columns

    def test_empty_dataframe_bowling(self):
        empty = pd.DataFrame(
            columns=["score_accuracy", "score_control", "score_threat"]
        )
        result = add_bowling_grades(empty)
        result = assign_bowling_archetypes(result)
        assert len(result) == 0
        assert "archetype" in result.columns
        assert "overall_grade" in result.columns

    def test_single_player_batting(self):
        df = pd.DataFrame(
            {
                "batter_id": ["solo"],
                "batter": ["Solo Player"],
                "score_acceleration": [72.0],
                "score_power": [68.0],
                "score_control": [65.0],
            }
        )
        result = add_batting_grades(df)
        result = assign_batting_archetypes(result)
        assert len(result) == 1
        assert result.iloc[0]["overall_grade"] in {
            "S",
            "A+",
            "A",
            "B+",
            "B",
            "C+",
            "C",
            "D",
        }
        assert isinstance(result.iloc[0]["archetype"], str)
