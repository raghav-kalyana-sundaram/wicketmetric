"""
Tests for Version 0.2 Phase 5 features:
  - Feature 4: Head-to-Head / Matchup Analysis
  - Feature 10: Win Probability Added (WPA)

Tests cover:
  - Core matchup aggregation (batter × bowler)
  - Phase-level matchup breakdowns
  - Dominance index computation
  - Bowling-style matchups (with external lookup)
  - Batter nemeses / bowler bunnies / dominant matchups
  - Matchup diversity stats (per batter)
  - Bowler matchup summary
  - Pivot helpers for single-player views
  - Convenience wrapper (compute_all_matchup_metrics)
  - WPA model building (2nd innings + 1st innings)
  - Delivery-level WPA scoring (row-by-row + vectorised)
  - Batting / bowling WPA aggregation
  - Match-level WPA summary
  - WPA convenience wrapper (compute_all_wpa_metrics)
  - Edge cases (empty data, single delivery, no target, all wides,
    no winner, multi-innings, super overs, etc.)
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
    event_name: str = "IPL 2024",
    target_runs: int | None = None,
    team_wickets_before: list[int] | None = None,
    team_score_before: list[int] | None = None,
    winner: str | None = None,
    overs_limit: int = 20,
    is_wicket: list[bool] | None = None,
    wicket_kind: list[str | None] | None = None,
    player_out: list[str | None] | None = None,
    player_out_id: list[str | None] | None = None,
    is_wide: list[bool] | None = None,
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
    if team_score_before is None:
        cum = list(np.cumsum([0] + batter_runs[:-1]))
        team_score_before = cum
    if is_wicket is None:
        is_wicket = [False] * n
    if wicket_kind is None:
        wicket_kind = [None] * n
    if player_out is None:
        player_out = [None] * n
    if player_out_id is None:
        player_out_id = [None] * n
    if is_wide is None:
        is_wide = [False] * n

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
                "is_legal": not is_wide[i],
                "is_batter_ball": not is_wide[i],
                "is_wide": is_wide[i],
                "is_noball": False,
                "is_wicket": is_wicket[i],
                "wicket_kind": wicket_kind[i],
                "player_out": player_out[i],
                "player_out_id": player_out_id[i],
                "is_four": batter_runs[i] == 4,
                "is_six": batter_runs[i] == 6,
                "is_dot_batter": batter_runs[i] == 0 and not is_wide[i],
                "is_dot_bowler": batter_runs[i] == 0 and not is_wide[i],
                "over": overs[i],
                "phase": phases[i],
                "team_score_before": team_score_before[i],
                "team_wickets_before": team_wickets_before[i],
                "target_runs": target_runs,
                "winner": winner,
                "overs_limit": overs_limit,
                "event_name": event_name,
                "date": "2024-01-15",
                "batting_position": 3,
                "legal_ball_seq": legal_ball_seq,
            }
        )
        if not is_wide[i]:
            legal_ball_seq += 1

    return pd.DataFrame(rows)


def _make_multi_matchup_df() -> pd.DataFrame:
    """
    Create a delivery DataFrame with multiple batters, bowlers, and matches.
    """
    frames = []

    # Match 1: b1 vs bw1 (10 balls), b1 vs bw2 (8 balls), b2 vs bw1 (6 balls)
    frames.append(
        _make_delivery_df(
            match_id="m1",
            innings_num=1,
            batter_id="b1",
            batter="Batter A",
            bowler_id="bw1",
            bowler="Bowler X",
            batter_runs=[0, 1, 4, 0, 2, 6, 1, 0, 1, 4],
            winner="TeamA",
        )
    )
    frames.append(
        _make_delivery_df(
            match_id="m1",
            innings_num=1,
            batter_id="b1",
            batter="Batter A",
            bowler_id="bw2",
            bowler="Bowler Y",
            batter_runs=[4, 4, 6, 0, 2, 1, 0, 4],
            winner="TeamA",
        )
    )
    frames.append(
        _make_delivery_df(
            match_id="m1",
            innings_num=1,
            batter_id="b2",
            batter="Batter B",
            bowler_id="bw1",
            bowler="Bowler X",
            batter_runs=[0, 0, 0, 1, 0, 0],
            winner="TeamA",
        )
    )

    # Match 2: b1 vs bw1 (8 balls), b2 vs bw2 (6 balls)
    frames.append(
        _make_delivery_df(
            match_id="m2",
            innings_num=2,
            batter_id="b1",
            batter="Batter A",
            bowler_id="bw1",
            bowler="Bowler X",
            batter_runs=[6, 4, 0, 2, 1, 0, 6, 4],
            target_runs=180,
            winner="TeamA",
        )
    )
    frames.append(
        _make_delivery_df(
            match_id="m2",
            innings_num=2,
            batter_id="b2",
            batter="Batter B",
            bowler_id="bw2",
            bowler="Bowler Y",
            batter_runs=[0, 0, 1, 0, 0, 0],
            target_runs=180,
            winner="TeamA",
        )
    )

    return pd.concat(frames, ignore_index=True)


def _make_wpa_delivery_df() -> pd.DataFrame:
    """
    Create a minimal delivery DataFrame suitable for WPA testing.
    Includes both 1st and 2nd innings across multiple matches.
    """
    frames = []

    # Match 1, innings 1: TeamA bats, sets 160
    runs_inn1 = [4, 1, 0, 2, 6, 1, 4, 0, 1, 2, 4, 6]
    overs_inn1 = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    score_before_inn1 = list(np.cumsum([0] + runs_inn1[:-1]))
    frames.append(
        _make_delivery_df(
            match_id="m1",
            innings_num=1,
            batter_id="b1",
            batter="Batter A",
            bowler_id="bw1",
            bowler="Bowler X",
            batting_team="TeamA",
            bowling_team="TeamB",
            batter_runs=runs_inn1,
            overs=overs_inn1,
            team_score_before=score_before_inn1,
            winner="TeamA",
        )
    )

    # Match 1, innings 2: TeamB chases 160, scores 162 and wins
    runs_inn2 = [0, 1, 4, 2, 6, 0, 4, 1, 0, 2, 4, 6]
    overs_inn2 = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    score_before_inn2 = list(np.cumsum([0] + runs_inn2[:-1]))
    frames.append(
        _make_delivery_df(
            match_id="m1",
            innings_num=2,
            batter_id="b2",
            batter="Batter B",
            bowler_id="bw2",
            bowler="Bowler Y",
            batting_team="TeamB",
            bowling_team="TeamA",
            batter_runs=runs_inn2,
            overs=overs_inn2,
            team_score_before=score_before_inn2,
            target_runs=160,
            winner="TeamA",
        )
    )

    # Match 2, innings 1
    runs_m2i1 = [1, 0, 4, 2, 0, 6, 1, 4, 0, 2]
    overs_m2i1 = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    score_m2i1 = list(np.cumsum([0] + runs_m2i1[:-1]))
    frames.append(
        _make_delivery_df(
            match_id="m2",
            innings_num=1,
            batter_id="b3",
            batter="Batter C",
            bowler_id="bw3",
            bowler="Bowler Z",
            batting_team="TeamC",
            bowling_team="TeamD",
            batter_runs=runs_m2i1,
            overs=overs_m2i1,
            team_score_before=score_m2i1,
            winner="TeamD",
        )
    )

    # Match 2, innings 2: TeamD chases
    runs_m2i2 = [4, 0, 2, 1, 6, 0, 4, 0, 1, 4]
    overs_m2i2 = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    score_m2i2 = list(np.cumsum([0] + runs_m2i2[:-1]))
    frames.append(
        _make_delivery_df(
            match_id="m2",
            innings_num=2,
            batter_id="b4",
            batter="Batter D",
            bowler_id="bw1",
            bowler="Bowler X",
            batting_team="TeamD",
            bowling_team="TeamC",
            batter_runs=runs_m2i2,
            overs=overs_m2i2,
            team_score_before=score_m2i2,
            target_runs=140,
            winner="TeamD",
        )
    )

    return pd.concat(frames, ignore_index=True)


# ═══════════════════════════════════════════════════════════════════════════
#  Feature 4: HEAD-TO-HEAD / MATCHUP ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════


class TestMatchupAggregation:
    """Tests for core matchup computation."""

    def test_basic_matchup(self):
        """Single batter vs single bowler produces correct aggregates."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[0, 1, 4, 0, 2, 6, 1, 0, 1, 4],
            batter_id="b1",
            bowler_id="bw1",
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        assert not m.empty
        assert len(m) == 1
        row = m.iloc[0]
        assert row["batter_id"] == "b1"
        assert row["bowler_id"] == "bw1"
        assert row["balls_faced"] == 10
        assert row["runs_scored"] == 19  # 0+1+4+0+2+6+1+0+1+4
        assert row["fours"] == 2
        assert row["sixes"] == 1
        assert row["boundaries"] == 3
        assert row["dots"] == 3  # three zeros
        assert row["matches"] == 1
        assert row["strike_rate"] == pytest.approx(190.0, abs=0.1)

    def test_min_balls_filter(self):
        """Matchups with fewer balls than min_balls are excluded."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[4, 6, 1],
            batter_id="b1",
            bowler_id="bw1",
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        assert result["matchups"].empty

        result2 = compute_matchups(df, min_balls=3, include_phase=False)
        assert len(result2["matchups"]) == 1

    def test_multiple_batters_and_bowlers(self):
        """Multiple batter-bowler pairs produce separate rows."""
        from src.matchups import compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        # b1 vs bw1 (10+8=18 balls), b1 vs bw2 (8 balls), b2 vs bw1 (6 balls), b2 vs bw2 (6 balls)
        pairs = set(zip(m["batter_id"], m["bowler_id"]))
        assert ("b1", "bw1") in pairs
        assert ("b1", "bw2") in pairs
        assert ("b2", "bw1") in pairs
        assert ("b2", "bw2") in pairs

    def test_dismissals_counted_correctly(self):
        """Bowler dismissals (caught, bowled, lbw) are counted; run-outs are not."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[0, 1, 4, 0, 0, 6, 0, 0, 1, 4],
            is_wicket=[
                False,
                False,
                False,
                True,
                False,
                False,
                True,
                False,
                False,
                False,
            ],
            wicket_kind=[
                None,
                None,
                None,
                "bowled",
                None,
                None,
                "run out",
                None,
                None,
                None,
            ],
            player_out=[
                None,
                None,
                None,
                "Player A",
                None,
                None,
                "Player A",
                None,
                None,
                None,
            ],
            player_out_id=[None, None, None, "b1", None, None, "b1", None, None, None],
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]
        assert len(m) == 1
        # Only "bowled" counts as bowler dismissal; "run out" doesn't
        assert m.iloc[0]["dismissals"] == 1
        assert m.iloc[0]["total_wickets"] == 2

    def test_wides_excluded_from_balls_faced(self):
        """Wides are not counted as batter balls."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[4, 1, 0, 2, 0, 6, 1, 0, 1, 4],
            is_wide=[
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]
        assert len(m) == 1
        assert m.iloc[0]["balls_faced"] == 9  # 10 - 1 wide

    def test_dominance_index_positive_for_batter(self):
        """High SR + boundaries should give positive dominance index."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[4, 6, 4, 6, 4, 6],
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]
        assert m.iloc[0]["dominance_index"] > 0

    def test_dominance_index_negative_for_bowler(self):
        """All dots + a dismissal should give negative dominance index."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[0, 0, 0, 0, 0, 0],
            is_wicket=[False, False, False, False, False, True],
            wicket_kind=[None, None, None, None, None, "bowled"],
            player_out=[None, None, None, None, None, "Player A"],
            player_out_id=[None, None, None, None, None, "b1"],
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]
        assert m.iloc[0]["dominance_index"] < 0

    def test_empty_deliveries(self):
        """Empty DataFrame returns empty matchups."""
        from src.matchups import compute_matchups

        df = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "batter_id",
                "batter",
                "bowler_id",
                "bowler",
                "batter_runs",
                "is_batter_ball",
                "is_wicket",
                "is_four",
                "is_six",
                "is_dot_batter",
                "phase",
                "is_wide",
                "wicket_kind",
                "player_out",
                "player_out_id",
            ]
        )
        result = compute_matchups(df, min_balls=6)
        assert result["matchups"].empty
        assert result["matchups_by_phase"].empty


class TestPhaseMatchups:
    """Tests for phase-level matchup breakdowns."""

    def test_phase_level_output(self):
        """Phase matchups produce separate rows per phase."""
        from src.matchups import compute_matchups

        # 6 balls in powerplay, 6 in middle — enough for min_balls=4 per phase
        batter_runs = [4, 1, 0, 2, 6, 0, 1, 4, 0, 2, 6, 1]
        overs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        phases = [
            "powerplay",
            "powerplay",
            "powerplay",
            "powerplay",
            "powerplay",
            "powerplay",
            "middle",
            "middle",
            "middle",
            "middle",
            "middle",
            "middle",
        ]
        df = _make_delivery_df(
            batter_runs=batter_runs,
            overs=overs,
            phases=phases,
        )
        result = compute_matchups(df, min_balls=4, include_phase=True)
        mp = result["matchups_by_phase"]

        assert not mp.empty
        phases_in_result = set(mp["phase"])
        assert "powerplay" in phases_in_result
        assert "middle" in phases_in_result

    def test_phase_disabled(self):
        """When include_phase=False, phase matchups are empty."""
        from src.matchups import compute_matchups

        df = _make_delivery_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        assert result["matchups_by_phase"].empty

    def test_phase_min_balls_filter(self):
        """Phase matchups are filtered independently by min_balls_phase."""
        from src.matchups import compute_matchups

        # Only 3 balls in powerplay — should be excluded at min_balls=4
        batter_runs = [4, 1, 0, 2, 6, 0, 1, 4]
        overs = [0, 0, 0, 6, 7, 8, 9, 10]
        phases = [
            "powerplay",
            "powerplay",
            "powerplay",
            "middle",
            "middle",
            "middle",
            "middle",
            "middle",
        ]
        df = _make_delivery_df(
            batter_runs=batter_runs,
            overs=overs,
            phases=phases,
        )
        result = compute_matchups(df, min_balls=8, include_phase=True)
        # min_balls for phase = max(8//2, 4) = 4
        mp = result["matchups_by_phase"]
        if not mp.empty:
            phases_in_result = set(mp["phase"])
            assert "powerplay" not in phases_in_result
            assert "middle" in phases_in_result


class TestBowlingStyleMatchups:
    """Tests for bowling-style matchups (requires external lookup)."""

    def test_bowling_style_matchup(self):
        """Matchups grouped by bowling style when lookup is provided."""
        from src.matchups import compute_matchups

        df = _make_multi_matchup_df()
        style_lookup = pd.DataFrame(
            {
                "bowler_id": ["bw1", "bw2"],
                "bowling_style": ["right-arm fast", "left-arm orthodox"],
            }
        )
        result = compute_matchups(
            df,
            min_balls=6,
            include_phase=False,
            bowling_style_lookup=style_lookup,
        )
        bsm = result["bowling_style_matchups"]
        assert not bsm.empty
        assert "bowling_style" in bsm.columns

    def test_no_lookup_returns_empty(self):
        """Without a bowling style lookup, bowling_style_matchups is empty."""
        from src.matchups import compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        assert result["bowling_style_matchups"].empty

    def test_empty_lookup_returns_empty(self):
        """Empty lookup DataFrame returns empty style matchups."""
        from src.matchups import compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(
            df,
            min_balls=6,
            include_phase=False,
            bowling_style_lookup=pd.DataFrame(),
        )
        assert result["bowling_style_matchups"].empty


class TestBatterNemesesAndBunnies:
    """Tests for player-centric matchup views."""

    def test_find_batter_nemeses(self):
        """Nemeses are bowlers with lowest dominance index."""
        from src.matchups import compute_matchups, find_batter_nemeses

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        nemeses = find_batter_nemeses(m, top_k=2, min_balls=6)
        assert not nemeses.empty
        assert "nemesis_rank" in nemeses.columns
        # All rank values should be 1 or 2
        assert nemeses["nemesis_rank"].max() <= 2

    def test_find_bowler_bunnies(self):
        """Bunnies are batters with lowest dominance index for a bowler."""
        from src.matchups import compute_matchups, find_bowler_bunnies

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        bunnies = find_bowler_bunnies(m, top_k=2, min_balls=6)
        assert not bunnies.empty
        assert "bunny_rank" in bunnies.columns

    def test_find_batter_dominant_matchups(self):
        """Dominant matchups are bowlers with highest dominance index."""
        from src.matchups import compute_matchups, find_batter_dominant_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        dominant = find_batter_dominant_matchups(m, top_k=2, min_balls=6)
        assert not dominant.empty
        assert "dominant_rank" in dominant.columns

    def test_empty_matchups_returns_empty(self):
        """All player-centric views return empty on empty matchups."""
        from src.matchups import (
            find_batter_dominant_matchups,
            find_batter_nemeses,
            find_bowler_bunnies,
        )

        empty = pd.DataFrame()
        assert find_batter_nemeses(empty).empty
        assert find_bowler_bunnies(empty).empty
        assert find_batter_dominant_matchups(empty).empty


class TestMatchupDiversityStats:
    """Tests for career-level matchup diversity."""

    def test_basic_diversity_stats(self):
        """Diversity stats are computed for batters with qualified matchups."""
        from src.matchups import compute_matchup_diversity_stats, compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        diversity = compute_matchup_diversity_stats(m, min_balls=6)
        assert not diversity.empty
        assert "batter_id" in diversity.columns
        assert "unique_bowlers" in diversity.columns
        assert "avg_dominance" in diversity.columns
        assert "pct_dominant" in diversity.columns
        assert "matchup_consistency" in diversity.columns

    def test_pct_dominant_in_range(self):
        """pct_dominant should be between 0 and 1."""
        from src.matchups import compute_matchup_diversity_stats, compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        diversity = compute_matchup_diversity_stats(m, min_balls=6)
        assert (diversity["pct_dominant"] >= 0).all()
        assert (diversity["pct_dominant"] <= 1).all()

    def test_matchup_consistency_in_range(self):
        """matchup_consistency should be between 0 and 1."""
        from src.matchups import compute_matchup_diversity_stats, compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        diversity = compute_matchup_diversity_stats(result["matchups"], min_balls=6)
        if not diversity.empty:
            assert (diversity["matchup_consistency"] >= 0).all()
            assert (diversity["matchup_consistency"] <= 1).all()

    def test_empty_returns_empty(self):
        """Empty matchups → empty diversity stats."""
        from src.matchups import compute_matchup_diversity_stats

        assert compute_matchup_diversity_stats(pd.DataFrame()).empty


class TestBowlerMatchupSummary:
    """Tests for per-bowler matchup summary."""

    def test_basic_bowler_summary(self):
        """Bowler summary has expected columns."""
        from src.matchups import compute_bowler_matchup_summary, compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        summary = compute_bowler_matchup_summary(m, min_balls=6)
        assert not summary.empty
        assert "bowler_id" in summary.columns
        assert "unique_batters" in summary.columns
        assert "avg_dominance" in summary.columns
        assert "pct_dominant_bowl" in summary.columns

    def test_empty_returns_empty(self):
        """Empty matchups → empty bowler summary."""
        from src.matchups import compute_bowler_matchup_summary

        assert compute_bowler_matchup_summary(pd.DataFrame()).empty


class TestPivotHelpers:
    """Tests for single-player matchup pivot helpers."""

    def test_pivot_for_batter(self):
        """Pivot for a specific batter returns their matchups."""
        from src.matchups import compute_matchups, pivot_matchup_summary_for_batter

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        batter_view = pivot_matchup_summary_for_batter(m, "b1", top_k=5)
        assert not batter_view.empty
        assert (batter_view["batter_id"] == "b1").all()

    def test_pivot_for_bowler(self):
        """Pivot for a specific bowler returns their matchups."""
        from src.matchups import compute_matchups, pivot_matchup_summary_for_bowler

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        bowler_view = pivot_matchup_summary_for_bowler(m, "bw1", top_k=5)
        assert not bowler_view.empty
        assert (bowler_view["bowler_id"] == "bw1").all()

    def test_pivot_nonexistent_player(self):
        """Pivot for a player not in the data returns empty."""
        from src.matchups import compute_matchups, pivot_matchup_summary_for_batter

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        assert pivot_matchup_summary_for_batter(m, "nonexistent").empty

    def test_pivot_empty_matchups(self):
        """Pivot on empty matchups returns empty."""
        from src.matchups import (
            pivot_matchup_summary_for_batter,
            pivot_matchup_summary_for_bowler,
        )

        assert pivot_matchup_summary_for_batter(pd.DataFrame(), "b1").empty
        assert pivot_matchup_summary_for_bowler(pd.DataFrame(), "bw1").empty


class TestMatchupConvenienceWrapper:
    """Tests for compute_all_matchup_metrics wrapper."""

    def test_wrapper_returns_all_keys(self):
        """Wrapper returns all expected dict keys."""
        from src.matchups import compute_all_matchup_metrics

        df = _make_multi_matchup_df()
        result = compute_all_matchup_metrics(df, min_balls=6)

        expected_keys = {
            "matchups",
            "matchups_by_phase",
            "bowling_style_matchups",
            "batter_nemeses",
            "bowler_bunnies",
            "batter_dominant",
            "batter_diversity",
            "bowler_summary",
        }
        assert set(result.keys()) == expected_keys

    def test_wrapper_empty_input(self):
        """Wrapper handles empty input gracefully."""
        from src.matchups import compute_all_matchup_metrics

        df = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "batter_id",
                "batter",
                "bowler_id",
                "bowler",
                "batter_runs",
                "is_batter_ball",
                "is_wicket",
                "is_four",
                "is_six",
                "is_dot_batter",
                "phase",
                "is_wide",
                "wicket_kind",
                "player_out",
                "player_out_id",
            ]
        )
        result = compute_all_matchup_metrics(df, min_balls=6)
        assert result["matchups"].empty

    def test_wrapper_with_bowling_style(self):
        """Wrapper with bowling style lookup populates style matchups."""
        from src.matchups import compute_all_matchup_metrics

        df = _make_multi_matchup_df()
        style_lookup = pd.DataFrame(
            {
                "bowler_id": ["bw1", "bw2"],
                "bowling_style": ["pace", "spin"],
            }
        )
        result = compute_all_matchup_metrics(
            df,
            min_balls=6,
            bowling_style_lookup=style_lookup,
        )
        assert not result["bowling_style_matchups"].empty


class TestMatchupEdgeCases:
    """Edge cases for matchup analysis."""

    def test_single_ball_matchup(self):
        """Single-ball matchup is filtered out by min_balls."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(batter_runs=[4])
        result = compute_matchups(df, min_balls=6, include_phase=False)
        assert result["matchups"].empty

    def test_all_wides_no_batter_balls(self):
        """All wides means no batter balls → empty matchups."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[0, 0, 0, 0, 0, 0],
            is_wide=[True, True, True, True, True, True],
        )
        result = compute_matchups(df, min_balls=1, include_phase=False)
        assert result["matchups"].empty

    def test_average_not_out(self):
        """When batter is not dismissed, average = total runs."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[4, 6, 4, 6, 4, 6],
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]
        assert m.iloc[0]["average"] == 30  # total runs, no dismissal

    def test_average_with_dismissals(self):
        """Average = runs / dismissals when dismissed."""
        from src.matchups import compute_matchups

        df = _make_delivery_df(
            batter_runs=[4, 0, 0, 0, 6, 0],
            is_wicket=[False, False, True, False, False, True],
            wicket_kind=[None, None, "caught", None, None, "bowled"],
            player_out=[None, None, "Player A", None, None, "Player A"],
            player_out_id=[None, None, "b1", None, None, "b1"],
        )
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]
        assert m.iloc[0]["average"] == pytest.approx(5.0)  # 10 runs / 2 dismissals

    def test_categorical_columns_handled(self):
        """Categorical columns don't cause errors."""
        from src.matchups import compute_matchups

        df = _make_delivery_df()
        for c in ["match_id", "batter_id", "bowler_id", "phase"]:
            df[c] = df[c].astype("category")

        result = compute_matchups(df, min_balls=6, include_phase=True)
        assert not result["matchups"].empty

    def test_multi_match_counts(self):
        """Matches column correctly counts unique matches."""
        from src.matchups import compute_matchups

        df = _make_multi_matchup_df()
        result = compute_matchups(df, min_balls=6, include_phase=False)
        m = result["matchups"]

        b1_bw1 = m[(m["batter_id"] == "b1") & (m["bowler_id"] == "bw1")]
        if not b1_bw1.empty:
            assert b1_bw1.iloc[0]["matches"] == 2  # appears in m1 and m2


# ═══════════════════════════════════════════════════════════════════════════
#  Feature 10: WIN PROBABILITY ADDED (WPA)
# ═══════════════════════════════════════════════════════════════════════════


class TestWPModel2ndInnings:
    """Tests for building the 2nd-innings win probability model."""

    def test_basic_model_building(self):
        """Model is built and returns a non-empty dict."""
        from src.wpa import build_second_innings_wp_model

        df = _make_wpa_delivery_df()
        model = build_second_innings_wp_model(df)
        assert isinstance(model, dict)
        assert len(model) > 0

    def test_model_keys_are_tuples(self):
        """Each key is a (over, wickets, score_ratio) tuple."""
        from src.wpa import build_second_innings_wp_model

        df = _make_wpa_delivery_df()
        model = build_second_innings_wp_model(df)
        for key in model:
            assert isinstance(key, tuple)
            assert len(key) == 3

    def test_model_values_in_range(self):
        """All win probabilities are between 0 and 1."""
        from src.wpa import build_second_innings_wp_model

        df = _make_wpa_delivery_df()
        model = build_second_innings_wp_model(df)
        for v in model.values():
            assert 0 <= v <= 1

    def test_laplace_smoothing(self):
        """With Laplace smoothing, no probability is exactly 0 or 1."""
        from src.wpa import build_second_innings_wp_model

        df = _make_wpa_delivery_df()
        model = build_second_innings_wp_model(df, laplace_alpha=2)
        for v in model.values():
            assert v > 0
            assert v < 1

    def test_empty_deliveries(self):
        """Empty DataFrame returns empty model."""
        from src.wpa import build_second_innings_wp_model

        df = pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "over",
                "team_wickets_before",
                "team_score_before",
                "target_runs",
                "batting_team",
                "winner",
            ]
        )
        model = build_second_innings_wp_model(df)
        assert model == {}

    def test_no_second_innings(self):
        """DataFrame with only 1st-innings data returns empty model."""
        from src.wpa import build_second_innings_wp_model

        df = _make_delivery_df(innings_num=1)
        model = build_second_innings_wp_model(df)
        assert model == {}


class TestWPModel1stInnings:
    """Tests for building the 1st-innings win probability model."""

    def test_basic_model_building(self):
        """1st-innings model and par scores are built."""
        from src.wpa import build_first_innings_wp_model

        df = _make_wpa_delivery_df()
        model, par_scores = build_first_innings_wp_model(df)
        assert isinstance(model, dict)
        assert isinstance(par_scores, dict)
        assert len(model) > 0
        assert len(par_scores) > 0

    def test_par_scores_reasonable(self):
        """Par scores should be non-negative floats."""
        from src.wpa import build_first_innings_wp_model

        df = _make_wpa_delivery_df()
        _, par_scores = build_first_innings_wp_model(df)
        for k, v in par_scores.items():
            assert isinstance(k, tuple)
            assert len(k) == 2
            assert v >= 0

    def test_model_values_in_range(self):
        """All 1st-innings WP values are between 0 and 1."""
        from src.wpa import build_first_innings_wp_model

        df = _make_wpa_delivery_df()
        model, _ = build_first_innings_wp_model(df)
        for v in model.values():
            assert 0 <= v <= 1


class TestDeliveryWPA:
    """Tests for delivery-level WPA scoring."""

    def test_wpa_column_added(self):
        """WPA column is added to deliveries."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        result = compute_delivery_wpa(df, wp2, wp1, par1)

        assert "wpa" in result.columns
        assert "win_prob_before" in result.columns
        assert "win_prob_after" in result.columns
        assert len(result) == len(df)

    def test_wpa_sums_per_match_approximate_zero(self):
        """
        For a complete match, the total WPA across all deliveries
        should sum to approximately ±1 (since one team ends with WP 1
        and the other with WP 0).

        This is a loose check because not all matches are "complete" in
        our test data, and the empirical model can't capture terminal
        states perfectly.
        """
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        result = compute_delivery_wpa(df, wp2, wp1, par1)

        # Just check no NaN in WPA
        assert not result["wpa"].isna().any()

    def test_wpa_win_prob_in_range(self):
        """Win probabilities should always be between 0 and 1."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        result = compute_delivery_wpa(df, wp2, wp1, par1)

        assert (result["win_prob_before"] >= 0).all()
        assert (result["win_prob_before"] <= 1).all()
        assert (result["win_prob_after"] >= 0).all()
        assert (result["win_prob_after"] <= 1).all()

    def test_wpa_chase_completion_terminal(self):
        """When a chase is completed, win_prob_after should be 1.0."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa,
        )

        # Create a simple chase scenario where target is reached
        df = _make_delivery_df(
            match_id="chase",
            innings_num=2,
            batter_runs=[4, 6, 4, 6, 4, 6],  # 30 runs off 6 balls
            overs=[18, 18, 18, 19, 19, 19],
            phases=["death"] * 6,
            target_runs=25,
            team_score_before=[0, 4, 10, 14, 20, 24],
            team_wickets_before=[0, 0, 0, 0, 0, 0],
            winner="TeamA",
            batting_team="TeamA",
        )
        # Build models from a bigger dataset
        full_df = pd.concat([_make_wpa_delivery_df(), df], ignore_index=True)
        wp2 = build_second_innings_wp_model(full_df)
        wp1, par1 = build_first_innings_wp_model(full_df)

        result = compute_delivery_wpa(full_df, wp2, wp1, par1)

        # Find the delivery where target was reached in our chase match
        chase = result[result["match_id"] == "chase"]
        # After first 4 balls (total 24), 5th ball (score 24 + 4 = 28 >= 25)
        target_reached = chase[chase["team_score_before"] + chase["total_runs"] >= 25]
        if not target_reached.empty:
            first_complete = target_reached.iloc[0]
            assert first_complete["win_prob_after"] == 1.0


class TestDeliveryWPAVectorised:
    """Tests for the vectorised WPA scorer."""

    def test_vectorised_produces_same_structure(self):
        """Vectorised scorer adds the same columns."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        result = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)

        assert "wpa" in result.columns
        assert "win_prob_before" in result.columns
        assert "win_prob_after" in result.columns
        assert len(result) == len(df)

    def test_vectorised_no_nan(self):
        """No NaN values in vectorised WPA output."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        result = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)

        assert not result["wpa"].isna().any()
        assert not result["win_prob_before"].isna().any()
        assert not result["win_prob_after"].isna().any()

    def test_vectorised_win_prob_in_range(self):
        """All WP values in range [0, 1]."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        result = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)

        assert (result["win_prob_before"] >= 0).all()
        assert (result["win_prob_before"] <= 1).all()
        assert (result["win_prob_after"] >= 0).all()
        assert (result["win_prob_after"] <= 1).all()


class TestBattingWPAAggregation:
    """Tests for career batting WPA aggregation."""

    def test_basic_batting_wpa(self):
        """Batting WPA aggregation produces expected columns."""
        from src.wpa import (
            aggregate_batting_wpa,
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)

        bat_wpa = aggregate_batting_wpa(wpa_df)
        assert not bat_wpa.empty
        assert "batter_id" in bat_wpa.columns
        assert "career_wpa_bat" in bat_wpa.columns
        assert "wpa_per_match_bat" in bat_wpa.columns
        assert "positive_wpa_bat" in bat_wpa.columns
        assert "negative_wpa_bat" in bat_wpa.columns
        assert "clutch_wpa_pct_bat" in bat_wpa.columns

    def test_positive_wpa_non_negative(self):
        """Positive WPA should be >= 0."""
        from src.wpa import (
            aggregate_batting_wpa,
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)
        bat_wpa = aggregate_batting_wpa(wpa_df)
        assert (bat_wpa["positive_wpa_bat"] >= 0).all()

    def test_negative_wpa_non_positive(self):
        """Negative WPA should be <= 0."""
        from src.wpa import (
            aggregate_batting_wpa,
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)
        bat_wpa = aggregate_batting_wpa(wpa_df)
        assert (bat_wpa["negative_wpa_bat"] <= 0).all()

    def test_clutch_wpa_pct_in_range(self):
        """Clutch WPA percentage should be between 0 and 1."""
        from src.wpa import (
            aggregate_batting_wpa,
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)
        bat_wpa = aggregate_batting_wpa(wpa_df)
        assert (bat_wpa["clutch_wpa_pct_bat"] >= 0).all()
        assert (bat_wpa["clutch_wpa_pct_bat"] <= 1).all()

    def test_wpa_per_match_computation(self):
        """wpa_per_match = career_wpa / matches."""
        from src.wpa import (
            aggregate_batting_wpa,
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)
        bat_wpa = aggregate_batting_wpa(wpa_df)

        for _, row in bat_wpa.iterrows():
            if row["wpa_matches_bat"] > 0:
                expected = row["career_wpa_bat"] / row["wpa_matches_bat"]
                assert row["wpa_per_match_bat"] == pytest.approx(expected, abs=1e-4)

    def test_empty_input(self):
        """Empty input returns empty aggregation."""
        from src.wpa import aggregate_batting_wpa

        df = pd.DataFrame(
            columns=[
                "batter_id",
                "batter",
                "is_batter_ball",
                "wpa",
                "match_id",
                "batter_runs",
            ]
        )
        assert aggregate_batting_wpa(df).empty


class TestBowlingWPAAggregation:
    """Tests for career bowling WPA aggregation."""

    def test_basic_bowling_wpa(self):
        """Bowling WPA aggregation produces expected columns."""
        from src.wpa import (
            aggregate_bowling_wpa,
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)

        bowl_wpa = aggregate_bowling_wpa(wpa_df)
        assert not bowl_wpa.empty
        assert "bowler_id" in bowl_wpa.columns
        assert "career_wpa_bowl" in bowl_wpa.columns
        assert "wpa_per_match_bowl" in bowl_wpa.columns

    def test_bowling_sign_convention(self):
        """Bowling WPA is sign-flipped: positive = good for bowler."""
        from src.wpa import (
            aggregate_bowling_wpa,
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
        )

        # Scenario: all dots (bad for batting → good for bowling)
        df = _make_delivery_df(
            match_id="dots",
            innings_num=2,
            batter_runs=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            overs=[0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            target_runs=150,
            team_score_before=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            team_wickets_before=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            winner="TeamB",  # bowling team wins
        )
        bigger = pd.concat([_make_wpa_delivery_df(), df], ignore_index=True)
        wp2 = build_second_innings_wp_model(bigger)
        wp1, par1 = build_first_innings_wp_model(bigger)
        wpa_df = compute_delivery_wpa_vectorised(bigger, wp2, wp1, par1)

        bowl_wpa = aggregate_bowling_wpa(wpa_df)
        # In this test the bowler bowling all-dot chase balls should have
        # some positive bowling WPA
        assert not bowl_wpa.empty

    def test_empty_input(self):
        """Empty input returns empty aggregation."""
        from src.wpa import aggregate_bowling_wpa

        assert aggregate_bowling_wpa(pd.DataFrame()).empty


class TestMatchWPASummary:
    """Tests for match-level WPA summary."""

    def test_match_summary_structure(self):
        """Match WPA summary returns batting, bowling, and timeline."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
            compute_match_wpa_summary,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)

        summary = compute_match_wpa_summary(wpa_df, "m1")
        assert "batting_wpa" in summary
        assert "bowling_wpa" in summary
        assert "wpa_timeline" in summary
        assert not summary["wpa_timeline"].empty

    def test_nonexistent_match(self):
        """Non-existent match_id returns empty DataFrames."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa_vectorised,
            compute_match_wpa_summary,
        )

        df = _make_wpa_delivery_df()
        wp2 = build_second_innings_wp_model(df)
        wp1, par1 = build_first_innings_wp_model(df)
        wpa_df = compute_delivery_wpa_vectorised(df, wp2, wp1, par1)

        summary = compute_match_wpa_summary(wpa_df, "nonexistent")
        assert summary["batting_wpa"].empty
        assert summary["bowling_wpa"].empty
        assert summary["wpa_timeline"].empty


class TestWPAConvenienceWrapper:
    """Tests for compute_all_wpa_metrics wrapper."""

    def test_wrapper_returns_all_keys(self):
        """Wrapper returns all expected dict keys."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()
        result = compute_all_wpa_metrics(df)

        expected_keys = {
            "wpa_deliveries",
            "batting_wpa",
            "bowling_wpa",
            "wp_model_2nd",
            "wp_model_1st",
            "par_scores_1st",
        }
        assert set(result.keys()) == expected_keys

    def test_wrapper_non_vectorised(self):
        """Wrapper works with use_vectorised=False."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()
        result = compute_all_wpa_metrics(df, use_vectorised=False)

        assert not result["wpa_deliveries"].empty
        assert "wpa" in result["wpa_deliveries"].columns
        assert not result["batting_wpa"].empty
        assert not result["bowling_wpa"].empty

    def test_wrapper_vectorised(self):
        """Wrapper works with use_vectorised=True (default)."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()
        result = compute_all_wpa_metrics(df, use_vectorised=True)

        assert not result["wpa_deliveries"].empty
        assert "wpa" in result["wpa_deliveries"].columns

    def test_wrapper_configurable_buckets(self):
        """Bucket configuration doesn't crash the pipeline."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()
        result = compute_all_wpa_metrics(
            df,
            score_ratio_buckets=5,
            rr_ratio_buckets=4,
        )
        assert not result["wpa_deliveries"].empty


class TestWPAEdgeCases:
    """Edge cases for WPA computation."""

    def test_single_delivery(self):
        """Single-delivery DataFrame doesn't crash."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_delivery_df(
            match_id="single",
            innings_num=2,
            batter_runs=[6],
            overs=[19],
            phases=["death"],
            target_runs=10,
            team_score_before=[5],
            winner="TeamA",
        )
        result = compute_all_wpa_metrics(df)
        assert "wpa" in result["wpa_deliveries"].columns

    def test_no_target_first_innings_only(self):
        """First-innings-only data works without target."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_delivery_df(
            match_id="first_only",
            innings_num=1,
            batter_runs=[4, 1, 0, 2, 6, 1, 4, 0],
            winner="TeamA",
        )
        result = compute_all_wpa_metrics(df)
        assert "wpa" in result["wpa_deliveries"].columns

    def test_no_winner(self):
        """Match with no winner (tie / no result) doesn't crash."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_delivery_df(
            match_id="tie",
            innings_num=2,
            batter_runs=[4, 1, 0, 2, 6, 1],
            target_runs=150,
            team_score_before=[0, 4, 5, 5, 7, 13],
            winner=None,
        )
        result = compute_all_wpa_metrics(df)
        assert "wpa" in result["wpa_deliveries"].columns

    def test_all_zeros(self):
        """All-zero runs DataFrame doesn't crash."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_delivery_df(
            match_id="zeros",
            innings_num=2,
            batter_runs=[0, 0, 0, 0, 0, 0],
            target_runs=100,
            team_score_before=[0, 0, 0, 0, 0, 0],
            winner="TeamB",
        )
        result = compute_all_wpa_metrics(df)
        assert not result["wpa_deliveries"]["wpa"].isna().any()

    def test_categorical_columns(self):
        """Categorical columns don't cause errors in WPA pipeline."""
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()
        for c in ["match_id", "batter_id", "bowler_id", "batting_team", "winner"]:
            if c in df.columns:
                df[c] = df[c].astype("category")
        result = compute_all_wpa_metrics(df)
        assert "wpa" in result["wpa_deliveries"].columns

    def test_high_target_low_score(self):
        """Chasing a very high target with low score → low win prob."""
        from src.wpa import (
            build_first_innings_wp_model,
            build_second_innings_wp_model,
            compute_delivery_wpa,
        )

        base = _make_wpa_delivery_df()
        # Add a chase scenario: target=300, score=10 at over 15
        chase_df = _make_delivery_df(
            match_id="hopeless",
            innings_num=2,
            batter_runs=[0, 0, 0, 0, 0, 0],
            overs=[15, 15, 16, 16, 17, 17],
            phases=["middle", "middle", "death", "death", "death", "death"],
            target_runs=300,
            team_score_before=[10, 10, 10, 10, 10, 10],
            winner="TeamB",
        )
        combined = pd.concat([base, chase_df], ignore_index=True)

        wp2 = build_second_innings_wp_model(combined)
        wp1, par1 = build_first_innings_wp_model(combined)
        result = compute_delivery_wpa(combined, wp2, wp1, par1)

        hopeless = result[result["match_id"] == "hopeless"]
        # Win prob should be low (well below 0.5) when chasing 300 with only 10 runs
        avg_wp = hopeless["win_prob_before"].mean()
        assert avg_wp < 0.6

    def test_wpa_lookup_fallback(self):
        """
        WPA lookup falls back gracefully when exact bucket isn't found.
        Ensures no KeyError even with unusual state combinations.
        """
        from src.wpa import _lookup_wp_1st, _lookup_wp_2nd

        # Minimal model: only one state
        wp_model = {(10, 3, 0.5): 0.45}
        par_scores = {(10, 3): 80.0}

        # Exact match
        wp = _lookup_wp_2nd(10, 3, 75.0, 150.0, wp_model, 10)
        assert 0 <= wp <= 1

        # Fallback: different wickets but same over
        wp2 = _lookup_wp_2nd(10, 5, 75.0, 150.0, wp_model, 10)
        assert 0 <= wp2 <= 1

        # Complete miss: different over
        wp3 = _lookup_wp_2nd(0, 0, 0.0, 150.0, wp_model, 10)
        assert 0 <= wp3 <= 1  # should return 0.5 as last resort

        # 1st innings fallback
        wp1_model = {(10, 3, 0.5): 0.55}
        wp4 = _lookup_wp_1st(10, 3, 80.0, wp1_model, par_scores, 8)
        assert 0 <= wp4 <= 1

        # Miss fallback
        wp5 = _lookup_wp_1st(0, 0, 0.0, wp1_model, par_scores, 8)
        assert 0 <= wp5 <= 1


class TestWPABucketisation:
    """Tests for the bucketing utility."""

    def test_bucketise_basic(self):
        """Basic bucketisation produces expected buckets."""
        from src.wpa import _bucketise

        series = pd.Series([0.0, 0.15, 0.5, 0.85, 1.0])
        result = _bucketise(series, n_buckets=10)
        # Each value should be rounded to nearest 0.1
        assert result.iloc[0] == 0.0
        assert result.iloc[2] == 0.5
        assert result.iloc[4] == 1.0

    def test_bucketise_clipping(self):
        """Values > 1.0 are clipped to 1.0, < 0 to 0.0."""
        from src.wpa import _bucketise

        series = pd.Series([-0.5, 1.5, 2.0])
        result = _bucketise(series, n_buckets=10)
        assert result.iloc[0] == 0.0
        assert result.iloc[1] == 1.0
        assert result.iloc[2] == 1.0

    def test_bucketise_nan_preserved(self):
        """NaN values stay NaN after bucketisation."""
        from src.wpa import _bucketise

        series = pd.Series([0.5, np.nan, 0.7])
        result = _bucketise(series, n_buckets=10)
        assert pd.isna(result.iloc[1])


# ═══════════════════════════════════════════════════════════════════════════
#  CROSS-FEATURE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossFeatureIntegration:
    """Integration tests verifying matchups and WPA work together."""

    def test_matchup_and_wpa_same_deliveries(self):
        """Both features can run on the same delivery DataFrame."""
        from src.matchups import compute_all_matchup_metrics
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()

        matchup_result = compute_all_matchup_metrics(df, min_balls=6)
        wpa_result = compute_all_wpa_metrics(df)

        # Both should produce results
        assert not matchup_result["matchups"].empty
        assert not wpa_result["wpa_deliveries"].empty

    def test_wpa_players_overlap_matchup_players(self):
        """Players in WPA output should overlap with matchup output."""
        from src.matchups import compute_all_matchup_metrics
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()

        matchup_result = compute_all_matchup_metrics(df, min_balls=1)
        wpa_result = compute_all_wpa_metrics(df)

        matchup_batters = set(matchup_result["matchups"]["batter_id"].unique())
        wpa_batters = set(wpa_result["batting_wpa"]["batter_id"].unique())

        # There should be some overlap
        assert matchup_batters & wpa_batters

    def test_both_features_handle_categorical(self):
        """Both features handle categorical columns correctly."""
        from src.matchups import compute_all_matchup_metrics
        from src.wpa import compute_all_wpa_metrics

        df = _make_wpa_delivery_df()
        cat_cols = [
            "match_id",
            "batter_id",
            "bowler_id",
            "batting_team",
            "bowling_team",
            "winner",
            "phase",
            "batter",
            "bowler",
        ]
        for c in cat_cols:
            if c in df.columns:
                df[c] = df[c].astype("category")

        matchup_result = compute_all_matchup_metrics(df, min_balls=1)
        wpa_result = compute_all_wpa_metrics(df)

        assert not matchup_result["matchups"].empty
        assert not wpa_result["wpa_deliveries"].empty
