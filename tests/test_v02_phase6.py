"""
Tests for Version 0.2 Phase 6 features:
  - Feature 16: Bowl First / Bowl Second Index (bowling innings splits)
  - Feature 17: Condition-Dependence Metrics (flat-track bully detection)
  - Feature 18: Bayesian Matchup Shrinkage (archetype-based priors)

Total: ~130 tests covering core logic, edge cases, and cross-feature integration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ───────────────────────────────────────────────────────────────────────────
# Imports under test
# ───────────────────────────────────────────────────────────────────────────
from src.bowling import compute_bowling_innings_splits
from src.condition import (
    _assign_bowling_condition_tag,
    _assign_condition_tag,
    _ols_interaction_coeff,
    _pearson_corr,
    compute_all_condition_metrics,
    compute_batting_condition_dependence,
    compute_batting_condition_terciles,
    compute_bowling_condition_dependence,
)
from src.matchups import (
    apply_bayesian_matchup_shrinkage,
    compute_archetype_baselines,
    compute_matchups,
    project_unseen_matchup,
)

# ───────────────────────────────────────────────────────────────────────────
# Test data factories
# ───────────────────────────────────────────────────────────────────────────


def _make_bowl_components(
    n_first: int = 10,
    n_second: int = 10,
    bowler_id: str = "b1",
    bowler: str = "Bowler A",
    first_econ_vs_par: float = 0.05,
    second_econ_vs_par: float = -0.02,
    first_dot_pct: float = 0.40,
    second_dot_pct: float = 0.35,
    first_wickets: float = 1.0,
    second_wickets: float = 0.5,
    first_ctrl_vs_others: float = 0.02,
    second_ctrl_vs_others: float = -0.01,
    first_ctrl_bowling_rv: float = 0.01,
    second_ctrl_bowling_rv: float = -0.005,
) -> pd.DataFrame:
    """Build a minimal bowl_components DataFrame for two innings types."""
    rows = []
    for i in range(n_first):
        rows.append(
            {
                "match_id": f"m{i}",
                "innings_num": 1,
                "bowler_id": bowler_id,
                "bowler": bowler,
                "bowling_team": "TeamX",
                "acc_economy_vs_par": first_econ_vs_par,
                "acc_dot_pct": first_dot_pct,
                "ctrl_vs_others": first_ctrl_vs_others,
                "ctrl_bowling_rv": first_ctrl_bowling_rv,
                "wickets": first_wickets,
                "spell_weight": 1.0,
            }
        )
    for i in range(n_second):
        rows.append(
            {
                "match_id": f"m{n_first + i}",
                "innings_num": 2,
                "bowler_id": bowler_id,
                "bowler": bowler,
                "bowling_team": "TeamX",
                "acc_economy_vs_par": second_econ_vs_par,
                "acc_dot_pct": second_dot_pct,
                "ctrl_vs_others": second_ctrl_vs_others,
                "ctrl_bowling_rv": second_ctrl_bowling_rv,
                "wickets": second_wickets,
                "spell_weight": 1.0,
            }
        )
    return pd.DataFrame(rows)


def _make_bat_innings(
    n: int = 30,
    batter_id: str = "bat1",
    batter: str = "Batter A",
    performance_range: tuple[float, float] = (-0.1, 0.15),
) -> pd.DataFrame:
    """Build a minimal batting innings DataFrame with varying performance."""
    np.random.seed(42)
    rows = []
    for i in range(n):
        par_sr = 130 + np.random.uniform(-20, 20)
        # Higher par_sr = easier conditions
        # performance correlated with par_sr for flat-track bully
        perf = (
            performance_range[0]
            + (performance_range[1] - performance_range[0]) * ((par_sr - 110) / 40)
            + np.random.normal(0, 0.02)
        )
        rows.append(
            {
                "match_id": f"m{i}",
                "innings_num": 1 if i % 2 == 0 else 2,
                "batter_id": batter_id,
                "batter": batter,
                "batting_team": "TeamA",
                "acc_overall_sr": perf,
                "runs": 20 + int(par_sr / 10),
                "balls": 15,
            }
        )
    return pd.DataFrame(rows)


def _make_match_ctx(
    n: int = 30, par_sr_range: tuple[float, float] = (110, 150)
) -> pd.DataFrame:
    """Build match context with varying par SR."""
    np.random.seed(42)
    rows = []
    for i in range(n):
        par_sr = np.random.uniform(*par_sr_range)
        rows.append(
            {
                "match_id": f"m{i}",
                "match_par_sr": par_sr,
                "match_par_rr": par_sr / 100 * 6,
                "match_boundary_rate": 0.15 + np.random.uniform(-0.05, 0.05),
                "match_dot_pct": 0.40 + np.random.uniform(-0.1, 0.1),
                "match_wickets_per_ball": 0.05,
                "match_date": pd.Timestamp("2023-01-01") + pd.Timedelta(days=i),
            }
        )
    return pd.DataFrame(rows)


def _make_delivery_df(
    n_deliveries_per_matchup: int = 12,
    batter_ids: list[str] | None = None,
    bowler_ids: list[str] | None = None,
    match_id: str = "m1",
) -> pd.DataFrame:
    """Build a minimal delivery DataFrame for matchup testing."""
    if batter_ids is None:
        batter_ids = ["bat1", "bat2"]
    if bowler_ids is None:
        bowler_ids = ["bowl1", "bowl2"]

    np.random.seed(42)
    rows = []
    delivery_num = 0
    for bat_id in batter_ids:
        for bowl_id in bowler_ids:
            for i in range(n_deliveries_per_matchup):
                delivery_num += 1
                runs = np.random.choice(
                    [0, 1, 2, 4, 6], p=[0.35, 0.30, 0.10, 0.15, 0.10]
                )
                is_wicket = (
                    i == n_deliveries_per_matchup - 1 and np.random.random() < 0.3
                )
                rows.append(
                    {
                        "match_id": match_id,
                        "innings_num": 1,
                        "batter_id": bat_id,
                        "batter": f"Batter_{bat_id}",
                        "bowler_id": bowl_id,
                        "bowler": f"Bowler_{bowl_id}",
                        "batting_team": "TeamA",
                        "bowling_team": "TeamB",
                        "batter_runs": runs,
                        "total_runs": runs,
                        "is_batter_ball": True,
                        "is_legal": True,
                        "is_wide": False,
                        "is_noball": False,
                        "is_wicket": is_wicket,
                        "is_four": runs == 4,
                        "is_six": runs == 6,
                        "is_dot_batter": runs == 0,
                        "is_dot_bowler": runs == 0,
                        "phase": "middle",
                        "player_out": bat_id if is_wicket else None,
                        "player_out_id": bat_id if is_wicket else None,
                        "wicket_kind": "bowled" if is_wicket else None,
                        "over": delivery_num // 6,
                        "ball_in_over": delivery_num % 6,
                        "date": pd.Timestamp("2023-06-15"),
                    }
                )
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# Feature 16: Bowl First / Bowl Second Index
# ═══════════════════════════════════════════════════════════════════════════


class TestBowlingInningsSplits:
    """Tests for compute_bowling_innings_splits()."""

    def test_basic_split_computed(self):
        bc = _make_bowl_components(n_first=8, n_second=8)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert not result.empty
        assert "bowl_first_index" in result.columns
        assert "bowl_second_index" in result.columns

    def test_bowl_first_index_positive_when_better_first(self):
        bc = _make_bowl_components(
            n_first=10,
            n_second=10,
            first_econ_vs_par=0.10,  # much better first
            second_econ_vs_par=-0.05,
        )
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert not result.empty
        idx = result.iloc[0]["bowl_first_index"]
        assert pd.notna(idx)
        assert idx > 0, (
            "Bowl first index should be positive when bowler restricts better in first innings"
        )

    def test_bowl_second_index_positive_when_better_second(self):
        bc = _make_bowl_components(
            n_first=10,
            n_second=10,
            first_econ_vs_par=-0.05,
            second_econ_vs_par=0.10,  # much better defending
            first_dot_pct=0.30,
            second_dot_pct=0.45,
            first_wickets=0.5,
            second_wickets=1.5,
            first_ctrl_vs_others=-0.05,
            second_ctrl_vs_others=0.05,
            first_ctrl_bowling_rv=-0.02,
            second_ctrl_bowling_rv=0.03,
        )
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert not result.empty
        idx = result.iloc[0]["bowl_second_index"]
        assert pd.notna(idx)
        assert idx > 0, (
            "Bowl second index should be positive when bowler defends better"
        )

    def test_indices_are_negatives_of_each_other(self):
        bc = _make_bowl_components(n_first=10, n_second=10)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        row = result.iloc[0]
        if pd.notna(row["bowl_first_index"]) and pd.notna(row["bowl_second_index"]):
            assert row["bowl_first_index"] == pytest.approx(
                -row["bowl_second_index"], abs=1e-3
            )

    def test_min_spells_filter(self):
        bc = _make_bowl_components(n_first=2, n_second=2)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=5)
        assert not result.empty
        # Should have NaN indices because not enough spells
        row = result.iloc[0]
        assert pd.isna(row["bowl_first_index"])
        assert pd.isna(row["bowl_second_index"])

    def test_only_first_innings_spells(self):
        bc = _make_bowl_components(n_first=10, n_second=0)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert not result.empty
        row = result.iloc[0]
        # No second innings data → both indices should be NaN
        assert pd.isna(row["bowl_first_index"])

    def test_only_second_innings_spells(self):
        bc = _make_bowl_components(n_first=0, n_second=10)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert not result.empty
        row = result.iloc[0]
        assert pd.isna(row["bowl_second_index"])

    def test_spell_counts_correct(self):
        bc = _make_bowl_components(n_first=7, n_second=5)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        row = result.iloc[0]
        assert row["bowl_first_spells"] == 7
        assert row["bowl_second_spells"] == 5

    def test_multiple_bowlers(self):
        bc1 = _make_bowl_components(
            n_first=8, n_second=8, bowler_id="b1", bowler="Bowler A"
        )
        bc2 = _make_bowl_components(
            n_first=6, n_second=6, bowler_id="b2", bowler="Bowler B"
        )
        # Need unique match_ids for bowler 2
        bc2["match_id"] = "x" + bc2["match_id"]
        bc = pd.concat([bc1, bc2], ignore_index=True)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert len(result) == 2
        assert set(result["bowler_id"]) == {"b1", "b2"}

    def test_empty_components(self):
        bc = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "bowler_id",
                "bowler",
                "acc_economy_vs_par",
                "acc_dot_pct",
                "ctrl_vs_others",
                "ctrl_bowling_rv",
                "wickets",
                "spell_weight",
            ]
        )
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert result.empty

    def test_missing_innings_num_returns_empty(self):
        bc = _make_bowl_components(n_first=5, n_second=5)
        bc = bc.drop(columns=["innings_num"])
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert result.empty

    def test_categorical_columns_handled(self):
        bc = _make_bowl_components(n_first=8, n_second=8)
        bc["bowler_id"] = bc["bowler_id"].astype("category")
        bc["bowler"] = bc["bowler"].astype("category")
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert not result.empty

    def test_wickets_per_spell_computed(self):
        bc = _make_bowl_components(
            n_first=8, n_second=8, first_wickets=2.0, second_wickets=0.5
        )
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        row = result.iloc[0]
        assert pd.notna(row["bowl_first_wickets_per_spell"])
        assert pd.notna(row["bowl_second_wickets_per_spell"])
        assert (
            row["bowl_first_wickets_per_spell"] > row["bowl_second_wickets_per_spell"]
        )

    def test_avg_econ_vs_par_in_output(self):
        bc = _make_bowl_components(
            n_first=8,
            n_second=8,
            first_econ_vs_par=0.10,
            second_econ_vs_par=-0.03,
        )
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        row = result.iloc[0]
        assert "bowl_first_avg_econ_vs_par" in result.columns
        assert "bowl_second_avg_econ_vs_par" in result.columns
        # First innings econ should be better (higher = better for bowler)
        assert row["bowl_first_avg_econ_vs_par"] > row["bowl_second_avg_econ_vs_par"]

    def test_values_are_rounded(self):
        bc = _make_bowl_components(n_first=8, n_second=8)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        for c in result.columns:
            if result[c].dtype in ("float64", "float32"):
                # Check that values have at most 4 decimal places
                vals = result[c].dropna()
                if len(vals) > 0:
                    assert all(v == round(v, 4) for v in vals), (
                        f"Column {c} not rounded"
                    )


# ═══════════════════════════════════════════════════════════════════════════
# Feature 17: Condition-Dependence Metrics
# ═══════════════════════════════════════════════════════════════════════════


class TestPearsonCorr:
    """Tests for the _pearson_corr helper."""

    def test_perfect_positive_correlation(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        assert _pearson_corr(x, y) == pytest.approx(1.0, abs=1e-10)

    def test_perfect_negative_correlation(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
        assert _pearson_corr(x, y) == pytest.approx(-1.0, abs=1e-10)

    def test_no_correlation(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([5.0, 1.0, 4.0, 2.0, 3.0])
        r = _pearson_corr(x, y)
        assert -0.5 < r < 0.5  # Roughly uncorrelated

    def test_too_few_observations(self):
        x = np.array([1.0, 2.0])
        y = np.array([3.0, 4.0])
        assert _pearson_corr(x, y) == 0.0

    def test_zero_variance_x(self):
        x = np.array([5.0, 5.0, 5.0, 5.0])
        y = np.array([1.0, 2.0, 3.0, 4.0])
        assert _pearson_corr(x, y) == 0.0

    def test_zero_variance_y(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        y = np.array([5.0, 5.0, 5.0, 5.0])
        assert _pearson_corr(x, y) == 0.0

    def test_nan_values_excluded(self):
        x = np.array([1.0, np.nan, 3.0, 4.0, 5.0])
        y = np.array([2.0, 4.0, np.nan, 8.0, 10.0])
        r = _pearson_corr(x, y)
        # Only 3 valid pairs: (1,2), (4,8), (5,10) — positive
        assert r > 0

    def test_all_nan_returns_zero(self):
        x = np.array([np.nan, np.nan])
        y = np.array([np.nan, np.nan])
        assert _pearson_corr(x, y) == 0.0


class TestOLSInteraction:
    """Tests for the _ols_interaction_coeff helper."""

    def test_no_interaction(self):
        np.random.seed(42)
        n = 50
        x = np.random.randn(n)
        z = np.random.randn(n)
        # y depends on x and z but NOT on their interaction
        y = 2.0 * x + 3.0 * z + np.random.randn(n) * 0.1
        coeff = _ols_interaction_coeff(x, y, z)
        assert abs(coeff) < 0.5  # Should be near 0

    def test_strong_interaction(self):
        np.random.seed(42)
        n = 50
        x = np.random.randn(n)
        z = np.random.randn(n)
        # y has a strong interaction term
        y = 1.0 * x + 1.0 * z + 5.0 * x * z + np.random.randn(n) * 0.1
        coeff = _ols_interaction_coeff(x, y, z)
        assert coeff == pytest.approx(5.0, abs=0.5)

    def test_too_few_observations(self):
        x = np.array([1.0, 2.0, 3.0])
        y = np.array([1.0, 2.0, 3.0])
        z = np.array([1.0, 2.0, 3.0])
        assert _ols_interaction_coeff(x, y, z) == 0.0


class TestConditionTag:
    """Tests for _assign_condition_tag."""

    def test_flat_track_bully(self):
        tag = _assign_condition_tag(cdi=0.30, spread=0.10)
        assert tag == "Flat-Track Bully"

    def test_tough_track_star(self):
        tag = _assign_condition_tag(cdi=-0.30, spread=-0.10)
        assert tag == "Tough-Track Star"

    def test_conditions_proof_low_cdi(self):
        tag = _assign_condition_tag(cdi=0.05, spread=0.10)
        assert tag == "Conditions-Proof"

    def test_conditions_proof_conflicting_signals(self):
        # CDI positive but spread negative — conflicting
        tag = _assign_condition_tag(cdi=0.20, spread=-0.10)
        assert tag == "Conditions-Proof"

    def test_none_spread_high_cdi(self):
        tag = _assign_condition_tag(cdi=0.30, spread=None)
        assert tag == "Flat-Track Bully"

    def test_none_spread_negative_cdi(self):
        tag = _assign_condition_tag(cdi=-0.30, spread=None)
        assert tag == "Tough-Track Star"

    def test_none_spread_moderate_cdi(self):
        tag = _assign_condition_tag(cdi=0.18, spread=None)
        assert tag == "Conditions-Proof"

    def test_nan_spread(self):
        tag = _assign_condition_tag(cdi=0.30, spread=float("nan"))
        assert tag == "Flat-Track Bully"


class TestBowlingConditionTag:
    """Tests for _assign_bowling_condition_tag."""

    def test_flat_track_leaker(self):
        tag = _assign_bowling_condition_tag(cdi=-0.30, spread=-0.10)
        assert tag == "Flat-Track Leaker"

    def test_tough_track_enforcer(self):
        tag = _assign_bowling_condition_tag(cdi=0.30, spread=0.10)
        assert tag == "Tough-Track Enforcer"

    def test_conditions_proof(self):
        tag = _assign_bowling_condition_tag(cdi=0.05, spread=0.01)
        assert tag == "Conditions-Proof"


class TestBattingConditionDependence:
    """Tests for compute_batting_condition_dependence."""

    def test_basic_computation(self):
        bi = _make_bat_innings(n=30)
        mc = _make_match_ctx(n=30)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        assert not result.empty
        assert "condition_dependence_index" in result.columns
        assert "condition_dependence_tag" in result.columns

    def test_flat_track_bully_detected(self):
        """A batter whose performance strongly correlates with easy conditions."""
        np.random.seed(42)
        n = 40
        rows = []
        mc_rows = []
        for i in range(n):
            par_sr = 110 + i * 1.0  # gradually easier conditions
            # Performance linearly correlates with conditions
            perf = -0.10 + 0.005 * i + np.random.normal(0, 0.005)
            rows.append(
                {
                    "match_id": f"m{i}",
                    "innings_num": 1,
                    "batter_id": "ftb",
                    "batter": "Flat Track Bully",
                    "acc_overall_sr": perf,
                    "runs": 30,
                    "balls": 20,
                }
            )
            mc_rows.append({"match_id": f"m{i}", "match_par_sr": par_sr})

        bi = pd.DataFrame(rows)
        mc = pd.DataFrame(mc_rows)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        assert not result.empty
        row = result.iloc[0]
        assert row["condition_dependence_index"] > 0.3
        assert row["condition_dependence_tag"] == "Flat-Track Bully"

    def test_tough_track_star_detected(self):
        """A batter who performs better in tough conditions."""
        np.random.seed(42)
        n = 40
        rows = []
        mc_rows = []
        for i in range(n):
            par_sr = 110 + i * 1.0
            # Performance inversely correlates with conditions
            perf = 0.10 - 0.005 * i + np.random.normal(0, 0.005)
            rows.append(
                {
                    "match_id": f"m{i}",
                    "innings_num": 1,
                    "batter_id": "tts",
                    "batter": "Tough Track Star",
                    "acc_overall_sr": perf,
                    "runs": 30,
                    "balls": 20,
                }
            )
            mc_rows.append({"match_id": f"m{i}", "match_par_sr": par_sr})

        bi = pd.DataFrame(rows)
        mc = pd.DataFrame(mc_rows)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        assert not result.empty
        row = result.iloc[0]
        assert row["condition_dependence_index"] < -0.3
        assert row["condition_dependence_tag"] == "Tough-Track Star"

    def test_min_innings_filter(self):
        bi = _make_bat_innings(n=5)
        mc = _make_match_ctx(n=5)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        assert not result.empty
        assert pd.isna(result.iloc[0]["condition_dependence_index"])

    def test_condition_spread_computed(self):
        bi = _make_bat_innings(n=30)
        mc = _make_match_ctx(n=30)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        row = result.iloc[0]
        assert "condition_spread" in result.columns
        assert "easy_sr_vs_par" in result.columns
        assert "hard_sr_vs_par" in result.columns

    def test_condition_innings_count(self):
        bi = _make_bat_innings(n=25)
        mc = _make_match_ctx(n=25)
        result = compute_batting_condition_dependence(bi, mc, min_innings=5)
        row = result.iloc[0]
        assert row["condition_innings"] > 0

    def test_empty_inputs(self):
        result = compute_batting_condition_dependence(
            pd.DataFrame(), pd.DataFrame(), min_innings=10
        )
        assert result.empty

    def test_missing_par_sr_col(self):
        bi = _make_bat_innings(n=20)
        mc = _make_match_ctx(n=20).drop(columns=["match_par_sr"])
        result = compute_batting_condition_dependence(
            bi, mc, min_innings=10, par_sr_col="match_par_sr"
        )
        assert result.empty

    def test_missing_performance_col(self):
        bi = _make_bat_innings(n=20).drop(columns=["acc_overall_sr"])
        mc = _make_match_ctx(n=20)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        assert result.empty

    def test_multiple_batters(self):
        bi1 = _make_bat_innings(n=20, batter_id="b1", batter="Batter 1")
        bi2 = _make_bat_innings(n=20, batter_id="b2", batter="Batter 2")
        bi2["match_id"] = "x" + bi2["match_id"]
        bi = pd.concat([bi1, bi2], ignore_index=True)
        mc1 = _make_match_ctx(n=20)
        mc2 = _make_match_ctx(n=20)
        mc2["match_id"] = "x" + mc2["match_id"]
        mc = pd.concat([mc1, mc2], ignore_index=True)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        assert len(result) == 2
        assert set(result["batter_id"]) == {"b1", "b2"}

    def test_cdi_in_valid_range(self):
        bi = _make_bat_innings(n=30)
        mc = _make_match_ctx(n=30)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        cdi = result.iloc[0]["condition_dependence_index"]
        if pd.notna(cdi):
            assert -1.0 <= cdi <= 1.0


class TestBowlingConditionDependence:
    """Tests for compute_bowling_condition_dependence."""

    def test_basic_computation(self):
        bc = _make_bowl_components(n_first=20, n_second=20)
        mc = _make_match_ctx(n=40)
        # Ensure match_ids align
        all_match_ids = bc["match_id"].unique()
        mc = mc.head(len(all_match_ids))
        mc["match_id"] = all_match_ids[: len(mc)]
        result = compute_bowling_condition_dependence(bc, mc, min_spells=10)
        assert not result.empty
        assert "condition_dependence_index_bowl" in result.columns

    def test_empty_inputs(self):
        result = compute_bowling_condition_dependence(
            pd.DataFrame(), pd.DataFrame(), min_spells=10
        )
        assert result.empty

    def test_min_spells_filter(self):
        bc = _make_bowl_components(n_first=3, n_second=3)
        mc = _make_match_ctx(n=6)
        mc["match_id"] = bc["match_id"].unique()[: len(mc)]
        result = compute_bowling_condition_dependence(bc, mc, min_spells=10)
        if not result.empty:
            assert pd.isna(result.iloc[0]["condition_dependence_index_bowl"])

    def test_tag_column_present(self):
        bc = _make_bowl_components(n_first=20, n_second=20)
        mc = _make_match_ctx(n=40)
        mc["match_id"] = bc["match_id"].unique()[: len(mc)]
        result = compute_bowling_condition_dependence(bc, mc, min_spells=10)
        assert "condition_dependence_tag_bowl" in result.columns


class TestBattingConditionTerciles:
    """Tests for compute_batting_condition_terciles."""

    def test_basic_tercile_output(self):
        bi = _make_bat_innings(n=30)
        mc = _make_match_ctx(n=30)
        result = compute_batting_condition_terciles(bi, mc, min_innings_per_tercile=2)
        assert not result.empty
        assert "condition_tercile" in result.columns
        # Should have entries for at least some terciles
        terciles = set(result["condition_tercile"].unique())
        assert terciles.issubset({"hard", "neutral", "easy"})

    def test_min_innings_per_tercile_filter(self):
        bi = _make_bat_innings(n=6)
        mc = _make_match_ctx(n=6)
        result = compute_batting_condition_terciles(bi, mc, min_innings_per_tercile=5)
        # With only 6 innings split across 3 terciles, each has ~2 innings
        # so most terciles will be filtered out
        assert len(result) <= 3  # at most one row per tercile

    def test_empty_inputs(self):
        result = compute_batting_condition_terciles(pd.DataFrame(), pd.DataFrame())
        assert result.empty

    def test_missing_par_sr_column(self):
        bi = _make_bat_innings(n=20)
        mc = _make_match_ctx(n=20).drop(columns=["match_par_sr"])
        result = compute_batting_condition_terciles(bi, mc)
        assert result.empty


class TestComputeAllConditionMetrics:
    """Tests for the convenience wrapper."""

    def test_returns_all_keys(self):
        bi = _make_bat_innings(n=30)
        bc = _make_bowl_components(n_first=15, n_second=15)
        mc = _make_match_ctx(n=30)
        result = compute_all_condition_metrics(
            bat_innings=bi,
            bowl_spells=bc,
            match_ctx=mc,
            min_bat_innings=10,
            min_bowl_spells=10,
        )
        assert "batting_condition" in result
        assert "bowling_condition" in result
        assert "batting_terciles" in result

    def test_batting_condition_populated(self):
        bi = _make_bat_innings(n=30)
        bc = _make_bowl_components(n_first=15, n_second=15)
        mc = _make_match_ctx(n=30)
        result = compute_all_condition_metrics(
            bat_innings=bi,
            bowl_spells=bc,
            match_ctx=mc,
            min_bat_innings=10,
        )
        assert not result["batting_condition"].empty

    def test_custom_performance_cols(self):
        bi = _make_bat_innings(n=30)
        bi["custom_perf"] = bi["acc_overall_sr"]
        bc = _make_bowl_components(n_first=15, n_second=15)
        mc = _make_match_ctx(n=30)
        result = compute_all_condition_metrics(
            bat_innings=bi,
            bowl_spells=bc,
            match_ctx=mc,
            bat_performance_col="custom_perf",
        )
        assert not result["batting_condition"].empty


# ═══════════════════════════════════════════════════════════════════════════
# Feature 18: Bayesian Matchup Shrinkage
# ═══════════════════════════════════════════════════════════════════════════


class TestArchetypeBaselines:
    """Tests for compute_archetype_baselines."""

    def test_empty_matchups(self):
        result = compute_archetype_baselines(pd.DataFrame())
        assert result["batter_vs_bowler_archetype"].empty
        assert result["bowler_vs_batter_archetype"].empty

    def test_with_bowler_archetypes(self):
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]

        bowler_arch = pd.DataFrame(
            {
                "bowler_id": ["bowl1", "bowl2"],
                "archetype": ["Pace", "Spin"],
                "phase_group": ["death_heavy", "middle_heavy"],
            }
        )

        result = compute_archetype_baselines(matchups, bowler_archetypes=bowler_arch)
        bva = result["batter_vs_bowler_archetype"]
        assert not bva.empty
        assert "bowler_archetype" in bva.columns
        assert "archetype_dominance" in bva.columns

    def test_with_batter_archetypes(self):
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]

        batter_arch = pd.DataFrame(
            {
                "batter_id": ["bat1", "bat2"],
                "archetype": ["Opener", "Finisher"],
                "position_group": ["top_order", "lower_middle"],
            }
        )

        result = compute_archetype_baselines(matchups, batter_archetypes=batter_arch)
        bva = result["bowler_vs_batter_archetype"]
        assert not bva.empty
        assert "batter_archetype" in bva.columns

    def test_no_archetypes_returns_empty_baselines(self):
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]

        result = compute_archetype_baselines(matchups)
        assert result["batter_vs_bowler_archetype"].empty
        assert result["bowler_vs_batter_archetype"].empty


class TestBayesianMatchupShrinkage:
    """Tests for apply_bayesian_matchup_shrinkage."""

    def _get_matchups(self, n_deliveries=15):
        deliveries = _make_delivery_df(n_deliveries_per_matchup=n_deliveries)
        core = compute_matchups(deliveries, min_balls=6)
        return core["matchups"]

    def test_basic_shrinkage_applied(self):
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups)
        assert "bayesian_dominance" in result.columns
        assert "shrinkage_applied" in result.columns
        assert "archetype_prior" in result.columns

    def test_shrinkage_factor_range(self):
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups, shrinkage_balls=30)
        assert all(result["shrinkage_applied"].between(0, 1))

    def test_more_balls_less_shrinkage(self):
        """Matchups with more balls should have less shrinkage."""
        matchups = self._get_matchups(n_deliveries=20)
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups, shrinkage_balls=30)
        # For matchups with > 30 balls, shrinkage should be < 0.5
        big = result[result["balls_faced"] > 30]
        if not big.empty:
            assert all(big["shrinkage_applied"] < 0.5)

    def test_small_sample_heavily_shrunk(self):
        """Matchups with very few balls should be heavily shrunk toward prior."""
        matchups = self._get_matchups(n_deliveries=8)
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups, shrinkage_balls=30)
        # For matchups with 8 balls, λ = 30/(8+30) ≈ 0.79
        small = result[result["balls_faced"] <= 10]
        if not small.empty:
            assert all(small["shrinkage_applied"] > 0.5)

    def test_bayesian_dominance_between_observed_and_prior(self):
        """Bayesian dominance should be between the observed value and prior."""
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups, shrinkage_balls=30)
        for _, row in result.iterrows():
            obs = row["dominance_index"]
            prior = row["archetype_prior"]
            bayes = row["bayesian_dominance"]
            lo = min(obs, prior)
            hi = max(obs, prior)
            # Bayesian estimate should be between observed and prior (or equal)
            assert lo - 0.01 <= bayes <= hi + 0.01, (
                f"Bayesian dominance {bayes} not between "
                f"observed {obs} and prior {prior}"
            )

    def test_with_bowler_archetypes(self):
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")

        bowler_arch = pd.DataFrame(
            {
                "bowler_id": ["bowl1", "bowl2"],
                "archetype": ["Pace", "Spin"],
            }
        )
        result = apply_bayesian_matchup_shrinkage(
            matchups, bowler_archetypes=bowler_arch, shrinkage_balls=30
        )
        assert not result.empty
        # Archetype prior should be populated
        assert result["archetype_prior"].notna().any()

    def test_with_both_archetypes(self):
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")

        bowler_arch = pd.DataFrame(
            {
                "bowler_id": ["bowl1", "bowl2"],
                "archetype": ["Pace", "Spin"],
            }
        )
        batter_arch = pd.DataFrame(
            {
                "batter_id": ["bat1", "bat2"],
                "archetype": ["Opener", "Finisher"],
            }
        )
        result = apply_bayesian_matchup_shrinkage(
            matchups,
            bowler_archetypes=bowler_arch,
            batter_archetypes=batter_arch,
        )
        assert "bayesian_dominance" in result.columns

    def test_empty_matchups(self):
        result = apply_bayesian_matchup_shrinkage(pd.DataFrame())
        assert result.empty

    def test_matchup_confidence_present(self):
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups)
        assert "matchup_confidence" in result.columns
        assert all(result["matchup_confidence"].between(0, 1))

    def test_global_prior_fallback(self):
        """Without archetype data, the prior falls back to the batter's global avg."""
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(
            matchups, bowler_archetypes=None, batter_archetypes=None
        )
        # All archetype priors should be filled with global fallback
        assert result["archetype_prior"].notna().all()

    def test_shrinkage_k_zero_means_no_shrinkage(self):
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups, shrinkage_balls=1)
        # With k=1, λ = 1/(n+1) is very small for n > 6
        for _, row in result.iterrows():
            if row["balls_faced"] > 20:
                assert row["shrinkage_applied"] < 0.1

    def test_large_shrinkage_k_pulls_to_prior(self):
        matchups = self._get_matchups()
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups, shrinkage_balls=10000)
        # With very large k, bayesian_dominance ≈ prior
        for _, row in result.iterrows():
            assert abs(row["bayesian_dominance"] - row["archetype_prior"]) < 0.1

    def test_categorical_columns_handled(self):
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        deliveries["batter_id"] = deliveries["batter_id"].astype("category")
        deliveries["bowler_id"] = deliveries["bowler_id"].astype("category")
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]
        if matchups.empty:
            pytest.skip("No matchups generated from test data")
        result = apply_bayesian_matchup_shrinkage(matchups)
        assert not result.empty


class TestProjectUnseenMatchup:
    """Tests for project_unseen_matchup."""

    def test_global_fallback(self):
        result = project_unseen_matchup(
            batter_id="bat1",
            bowler_id="bowl1",
            batter_vs_bowler_arch=pd.DataFrame(),
            bowler_archetypes=pd.DataFrame(),
            global_dominance=0.5,
        )
        assert result["projected_dominance"] == 0.5
        assert result["confidence"] == 0.0
        assert result["source"] == "global"

    def test_archetype_projection(self):
        bowler_arch = pd.DataFrame(
            {
                "bowler_id": ["bowl1", "bowl2"],
                "archetype": ["Pace", "Spin"],
            }
        )
        batter_vs_arch = pd.DataFrame(
            {
                "batter_id": ["bat1", "bat1"],
                "bowler_archetype": ["Pace", "Spin"],
                "archetype_dominance": [0.3, -0.5],
                "archetype_balls": [100, 80],
            }
        )

        result = project_unseen_matchup(
            batter_id="bat1",
            bowler_id="bowl1",
            batter_vs_bowler_arch=batter_vs_arch,
            bowler_archetypes=bowler_arch,
        )
        assert result["projected_dominance"] == pytest.approx(0.3, abs=1e-3)
        assert result["source"] == "archetype"
        assert result["confidence"] == 0.0

    def test_unknown_bowler_global_fallback(self):
        bowler_arch = pd.DataFrame(
            {
                "bowler_id": ["bowl1"],
                "archetype": ["Pace"],
            }
        )
        result = project_unseen_matchup(
            batter_id="bat1",
            bowler_id="unknown_bowler",
            batter_vs_bowler_arch=pd.DataFrame(),
            bowler_archetypes=bowler_arch,
            global_dominance=-0.1,
        )
        assert result["source"] == "global"

    def test_no_batter_archetype_data(self):
        bowler_arch = pd.DataFrame(
            {
                "bowler_id": ["bowl1"],
                "archetype": ["Pace"],
            }
        )
        result = project_unseen_matchup(
            batter_id="bat_new",
            bowler_id="bowl1",
            batter_vs_bowler_arch=pd.DataFrame(
                columns=["batter_id", "bowler_archetype", "archetype_dominance"]
            ),
            bowler_archetypes=bowler_arch,
            global_dominance=0.0,
        )
        assert result["source"] == "global"

    def test_none_bowler_archetypes(self):
        result = project_unseen_matchup(
            batter_id="bat1",
            bowler_id="bowl1",
            batter_vs_bowler_arch=pd.DataFrame(),
            bowler_archetypes=None,
        )
        assert result["source"] == "global"

    def test_no_archetype_column(self):
        bowler_arch = pd.DataFrame(
            {
                "bowler_id": ["bowl1"],
                "some_other_col": ["value"],
            }
        )
        result = project_unseen_matchup(
            batter_id="bat1",
            bowler_id="bowl1",
            batter_vs_bowler_arch=pd.DataFrame(),
            bowler_archetypes=bowler_arch,
        )
        assert result["source"] == "global"


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases and cross-feature integration
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases for all three features."""

    def test_bowl_splits_with_single_spell(self):
        bc = _make_bowl_components(n_first=1, n_second=1)
        result = compute_bowling_innings_splits(bc, min_spells_per_type=1)
        assert not result.empty

    def test_condition_dependence_all_same_par_sr(self):
        """All matches have the same par SR → zero variance → CDI = 0."""
        bi = _make_bat_innings(n=20)
        mc = _make_match_ctx(n=20)
        mc["match_par_sr"] = 130.0  # constant
        result = compute_batting_condition_dependence(bi, mc, min_innings=5)
        if not result.empty:
            cdi = result.iloc[0]["condition_dependence_index"]
            assert cdi == 0.0

    def test_condition_dependence_all_same_performance(self):
        """All innings have the same performance → zero variance → CDI = 0."""
        bi = _make_bat_innings(n=20)
        bi["acc_overall_sr"] = 0.05  # constant
        mc = _make_match_ctx(n=20)
        result = compute_batting_condition_dependence(bi, mc, min_innings=5)
        if not result.empty:
            cdi = result.iloc[0]["condition_dependence_index"]
            assert cdi == 0.0

    def test_matchup_shrinkage_preserves_columns(self):
        """Shrinkage should not remove any existing columns."""
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]
        if matchups.empty:
            pytest.skip("No matchups generated from test data")

        original_cols = set(matchups.columns)
        result = apply_bayesian_matchup_shrinkage(matchups)
        # All original columns should still be present
        assert original_cols.issubset(set(result.columns))

    def test_matchup_shrinkage_same_row_count(self):
        """Shrinkage should not add or remove rows."""
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]
        if matchups.empty:
            pytest.skip("No matchups generated from test data")

        result = apply_bayesian_matchup_shrinkage(matchups)
        assert len(result) == len(matchups)

    def test_bowl_splits_with_nan_components(self):
        bc = _make_bowl_components(n_first=8, n_second=8)
        bc.loc[0, "acc_economy_vs_par"] = np.nan
        bc.loc[1, "acc_dot_pct"] = np.nan
        result = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        # Should not crash; NaN values handled via nanmean
        assert not result.empty

    def test_condition_dependence_with_nan_performance(self):
        bi = _make_bat_innings(n=30)
        bi.loc[0, "acc_overall_sr"] = np.nan
        mc = _make_match_ctx(n=30)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        # Should handle NaN gracefully (dropping those rows)
        assert not result.empty

    def test_condition_spread_sign_convention(self):
        """easy_sr_vs_par > hard_sr_vs_par → positive spread for flat-track."""
        np.random.seed(42)
        n = 60
        rows = []
        mc_rows = []
        for i in range(n):
            par_sr = 110 + i * (40 / n)
            perf = 0.01 * i / n  # monotonically increases with conditions
            rows.append(
                {
                    "match_id": f"m{i}",
                    "innings_num": 1,
                    "batter_id": "bat1",
                    "batter": "Test",
                    "acc_overall_sr": perf,
                    "runs": 25,
                    "balls": 18,
                }
            )
            mc_rows.append({"match_id": f"m{i}", "match_par_sr": par_sr})
        bi = pd.DataFrame(rows)
        mc = pd.DataFrame(mc_rows)
        result = compute_batting_condition_dependence(bi, mc, min_innings=10)
        row = result.iloc[0]
        if pd.notna(row["condition_spread"]):
            # Positive spread means better in easy conditions
            assert row["condition_spread"] > 0


class TestCrossFeatureIntegration:
    """Tests combining multiple phase 6 features."""

    def test_bowl_splits_and_condition_on_same_components(self):
        """Both features should work on the same bowl_components DataFrame."""
        bc = _make_bowl_components(n_first=15, n_second=15)
        mc = _make_match_ctx(n=30)
        mc["match_id"] = bc["match_id"].unique()[: len(mc)]

        splits = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        condition = compute_bowling_condition_dependence(bc, mc, min_spells=10)

        assert not splits.empty
        # Both should have the same bowler
        if not condition.empty:
            split_bowlers = set(splits["bowler_id"])
            cond_bowlers = set(condition["bowler_id"])
            assert split_bowlers == cond_bowlers

    def test_matchup_shrinkage_with_conditions_data(self):
        """Bayesian shrinkage and condition-dependence can coexist."""
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]

        if matchups.empty:
            pytest.skip("No matchups generated from test data")

        # Apply shrinkage
        shrunk = apply_bayesian_matchup_shrinkage(matchups)

        # Compute condition dependence on separate batting data
        bi = _make_bat_innings(n=30)
        mc = _make_match_ctx(n=30)
        cdi = compute_batting_condition_dependence(bi, mc, min_innings=10)

        # Both should produce valid outputs
        assert not shrunk.empty
        assert isinstance(cdi, pd.DataFrame)

    def test_all_three_features_produce_output(self):
        """All three features should produce non-empty output from valid data."""
        # Bowl splits
        bc = _make_bowl_components(n_first=10, n_second=10)
        splits = compute_bowling_innings_splits(bc, min_spells_per_type=3)
        assert not splits.empty

        # Condition dependence
        bi = _make_bat_innings(n=30)
        mc = _make_match_ctx(n=30)
        cdi = compute_batting_condition_dependence(bi, mc, min_innings=10)
        assert not cdi.empty

        # Matchup shrinkage
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]
        if not matchups.empty:
            shrunk = apply_bayesian_matchup_shrinkage(matchups)
            assert "bayesian_dominance" in shrunk.columns

    def test_matchup_confidence_from_compute_matchups(self):
        """compute_matchups should now include matchup_confidence in output."""
        deliveries = _make_delivery_df(n_deliveries_per_matchup=15)
        core = compute_matchups(deliveries, min_balls=6)
        matchups = core["matchups"]
        if not matchups.empty:
            assert "matchup_confidence" in matchups.columns
            assert all(matchups["matchup_confidence"].between(0, 1))
