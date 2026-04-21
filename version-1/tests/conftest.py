"""
Shared pytest fixtures for cricket_metrics tests.

Provides small, deterministic synthetic datasets that exercise the full
pipeline without needing the real Cricsheet JSON files.
"""

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers to build synthetic delivery rows
# ---------------------------------------------------------------------------


def _make_delivery(
    match_id="M001",
    date="2023-06-15",
    venue="Test Ground",
    event_name="Test Series",
    innings_num=1,
    batting_team="Team A",
    bowling_team="Team B",
    over=0,
    ball_idx=0,
    legal_ball_seq=0,
    batter="Batter1",
    batter_id="bat1",
    bowler="Bowler1",
    bowler_id="bowl1",
    non_striker="Batter2",
    non_striker_id="bat2",
    batting_position=1,
    batter_runs=0,
    extras_runs=0,
    total_runs=0,
    wide_runs=0,
    noball_runs=0,
    legbye_runs=0,
    bye_runs=0,
    penalty_runs=0,
    is_wide=False,
    is_noball=False,
    is_legal=True,
    is_batter_ball=True,
    is_wicket=False,
    wicket_kind=None,
    player_out=None,
    player_out_id=None,
    is_four=False,
    is_six=False,
    is_dot_batter=True,
    is_dot_bowler=True,
    phase="powerplay",
    team_score_before=0,
    team_wickets_before=0,
    target_runs=None,
    winner=None,
    overs_limit=20,
):
    return {
        "match_id": match_id,
        "date": pd.Timestamp(date),
        "venue": venue,
        "event_name": event_name,
        "innings_num": innings_num,
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "over": over,
        "ball_idx": ball_idx,
        "legal_ball_seq": legal_ball_seq,
        "batter": batter,
        "batter_id": batter_id,
        "bowler": bowler,
        "bowler_id": bowler_id,
        "non_striker": non_striker,
        "non_striker_id": non_striker_id,
        "batting_position": batting_position,
        "batter_runs": batter_runs,
        "extras_runs": extras_runs,
        "total_runs": total_runs,
        "wide_runs": wide_runs,
        "noball_runs": noball_runs,
        "legbye_runs": legbye_runs,
        "bye_runs": bye_runs,
        "penalty_runs": penalty_runs,
        "is_wide": is_wide,
        "is_noball": is_noball,
        "is_legal": is_legal,
        "is_batter_ball": is_batter_ball,
        "is_wicket": is_wicket,
        "wicket_kind": wicket_kind,
        "player_out": player_out,
        "player_out_id": player_out_id,
        "is_four": is_four,
        "is_six": is_six,
        "is_dot_batter": is_dot_batter,
        "is_dot_bowler": is_dot_bowler,
        "phase": phase,
        "team_score_before": team_score_before,
        "team_wickets_before": team_wickets_before,
        "target_runs": target_runs,
        "winner": winner,
        "overs_limit": overs_limit,
    }


def _build_over(
    match_id,
    innings_num,
    batting_team,
    bowling_team,
    over_num,
    batter,
    batter_id,
    bowler,
    bowler_id,
    non_striker,
    non_striker_id,
    batting_position,
    run_sequence,
    date="2023-06-15",
    team_score_start=0,
    team_wickets_start=0,
    wicket_on_ball=None,
    wicket_kind_val="bowled",
    target_runs=None,
    winner=None,
):
    """
    Build 6 legal deliveries for a single over from a run_sequence list.

    run_sequence: list of 6 ints representing batter_runs per ball.
    wicket_on_ball: 0-based index within the over where a wicket falls (or None).
    """
    if over_num < 6:
        phase = "powerplay"
    elif over_num < 16:
        phase = "middle"
    else:
        phase = "death"

    deliveries = []
    cum_score = team_score_start
    cum_wickets = team_wickets_start
    seq = over_num * 6

    for i, runs in enumerate(run_sequence):
        is_wkt = wicket_on_ball is not None and i == wicket_on_ball
        d = _make_delivery(
            match_id=match_id,
            date=date,
            innings_num=innings_num,
            batting_team=batting_team,
            bowling_team=bowling_team,
            over=over_num,
            ball_idx=i,
            legal_ball_seq=seq + i,
            batter=batter,
            batter_id=batter_id,
            bowler=bowler,
            bowler_id=bowler_id,
            non_striker=non_striker,
            non_striker_id=non_striker_id,
            batting_position=batting_position,
            batter_runs=runs,
            extras_runs=0,
            total_runs=runs,
            is_four=(runs == 4),
            is_six=(runs == 6),
            is_dot_batter=(runs == 0),
            is_dot_bowler=(runs == 0),
            phase=phase,
            team_score_before=cum_score,
            team_wickets_before=cum_wickets,
            is_wicket=is_wkt,
            wicket_kind=wicket_kind_val if is_wkt else None,
            player_out=batter if is_wkt else None,
            player_out_id=batter_id if is_wkt else None,
            target_runs=target_runs,
            winner=winner,
        )
        deliveries.append(d)
        cum_score += runs
        if is_wkt:
            cum_wickets += 1

    return deliveries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_deliveries_simple():
    """
    A minimal 2-match, 2-innings-per-match dataset with known values.

    Match M001 (2023-06-15):
      Innings 1 — Team A bats: Batter1 faces 12 balls (overs 0-1), Batter2 faces 6 balls (over 2)
      Innings 2 — Team B bats: Batter3 faces 12 balls (overs 0-1)

    Match M002 (2023-06-16):
      Innings 1 — Team A bats: Batter1 faces 6 balls (over 0)
      Innings 2 — Team B bats: Batter3 faces 6 balls (over 0)

    All overs are in the powerplay (over < 6).
    """
    rows = []

    # ── M001 Innings 1: Team A ──
    # Batter1 over 0: 1,0,4,1,0,6 = 12 runs
    rows += _build_over(
        "M001",
        1,
        "Team A",
        "Team B",
        0,
        "Batter1",
        "bat1",
        "Bowler1",
        "bowl1",
        "Batter2",
        "bat2",
        1,
        [1, 0, 4, 1, 0, 6],
        team_score_start=0,
    )
    # Batter1 over 1: 4,4,1,0,1,2 = 12 runs, wicket on ball 5 (the 2)
    rows += _build_over(
        "M001",
        1,
        "Team A",
        "Team B",
        1,
        "Batter1",
        "bat1",
        "Bowler2",
        "bowl2",
        "Batter2",
        "bat2",
        1,
        [4, 4, 1, 0, 1, 2],
        team_score_start=12,
        wicket_on_ball=5,
    )
    # Batter2 over 2: 0,1,0,0,1,0 = 2 runs (bowled by Bowler1)
    rows += _build_over(
        "M001",
        1,
        "Team A",
        "Team B",
        2,
        "Batter2",
        "bat2",
        "Bowler1",
        "bowl1",
        "Batter3",
        "bat3",
        2,
        [0, 1, 0, 0, 1, 0],
        team_score_start=24,
    )

    # ── M001 Innings 2: Team B ──
    # Batter3 over 0: 6,4,2,1,0,4 = 17 runs
    rows += _build_over(
        "M001",
        2,
        "Team B",
        "Team A",
        0,
        "Batter3",
        "bat3",
        "Bowler3",
        "bowl3",
        "Batter4",
        "bat4",
        1,
        [6, 4, 2, 1, 0, 4],
        target_runs=27,
    )
    # Batter3 over 1: 1,1,1,4,0,6 = 13 runs
    rows += _build_over(
        "M001",
        2,
        "Team B",
        "Team A",
        1,
        "Batter3",
        "bat3",
        "Bowler3",
        "bowl3",
        "Batter4",
        "bat4",
        1,
        [1, 1, 1, 4, 0, 6],
        team_score_start=17,
        target_runs=27,
        winner="Team B",
    )

    # ── M002 Innings 1: Team A ──
    # Batter1 over 0: 0,0,4,6,1,0 = 11 runs
    rows += _build_over(
        "M002",
        1,
        "Team A",
        "Team B",
        0,
        "Batter1",
        "bat1",
        "Bowler1",
        "bowl1",
        "Batter2",
        "bat2",
        1,
        [0, 0, 4, 6, 1, 0],
        date="2023-06-16",
    )

    # ── M002 Innings 2: Team B ──
    # Batter3 over 0: 1,1,0,1,1,1 = 5 runs
    rows += _build_over(
        "M002",
        2,
        "Team B",
        "Team A",
        0,
        "Batter3",
        "bat3",
        "Bowler3",
        "bowl3",
        "Batter4",
        "bat4",
        1,
        [1, 1, 0, 1, 1, 1],
        date="2023-06-16",
        target_runs=12,
    )

    df = pd.DataFrame(rows)
    return df


@pytest.fixture
def synthetic_deliveries_with_phases():
    """
    A single match with deliveries spanning all three phases for one batter
    and one bowler, so phase-specific metrics can be tested.

    Match M010:
      Innings 1 — Team X bats:
        Batter A faces overs 0-1 (PP), 8-9 (middle), 18-19 (death)
        Bowler P bowls overs 0-1 (PP), 8-9 (middle), 18-19 (death)
    """
    rows = []

    # Powerplay overs (0, 1)
    # Over 0: 1,1,4,0,1,1 = 8 runs
    rows += _build_over(
        "M010",
        1,
        "Team X",
        "Team Y",
        0,
        "BatterA",
        "batA",
        "BowlerP",
        "bowlP",
        "BatterB",
        "batB",
        1,
        [1, 1, 4, 0, 1, 1],
    )
    # Over 1: 0,6,0,1,4,0 = 11 runs
    rows += _build_over(
        "M010",
        1,
        "Team X",
        "Team Y",
        1,
        "BatterA",
        "batA",
        "BowlerP",
        "bowlP",
        "BatterB",
        "batB",
        1,
        [0, 6, 0, 1, 4, 0],
        team_score_start=8,
    )

    # Middle overs (8, 9)
    # Over 8: 1,1,0,2,1,0 = 5 runs
    rows += _build_over(
        "M010",
        1,
        "Team X",
        "Team Y",
        8,
        "BatterA",
        "batA",
        "BowlerP",
        "bowlP",
        "BatterB",
        "batB",
        1,
        [1, 1, 0, 2, 1, 0],
        team_score_start=19,
    )
    # Over 9: 0,1,0,0,4,1 = 6 runs
    rows += _build_over(
        "M010",
        1,
        "Team X",
        "Team Y",
        9,
        "BatterA",
        "batA",
        "BowlerP",
        "bowlP",
        "BatterB",
        "batB",
        1,
        [0, 1, 0, 0, 4, 1],
        team_score_start=24,
    )

    # Death overs (18, 19)
    # Over 18: 4,6,1,4,6,2 = 23 runs
    rows += _build_over(
        "M010",
        1,
        "Team X",
        "Team Y",
        18,
        "BatterA",
        "batA",
        "BowlerP",
        "bowlP",
        "BatterB",
        "batB",
        1,
        [4, 6, 1, 4, 6, 2],
        team_score_start=30,
    )
    # Over 19: 6,0,4,4,6,1 = 21 runs, wicket on last ball
    rows += _build_over(
        "M010",
        1,
        "Team X",
        "Team Y",
        19,
        "BatterA",
        "batA",
        "BowlerP",
        "bowlP",
        "BatterB",
        "batB",
        1,
        [6, 0, 4, 4, 6, 1],
        team_score_start=53,
        wicket_on_ball=5,
    )

    df = pd.DataFrame(rows)
    return df


@pytest.fixture
def synthetic_multi_match_career():
    """
    15 matches for one batter (bat_star) and one bowler (bowl_star) to test
    career aggregation, Bayesian shrinkage, and the provisional flag.

    Batter bat_star:
      - 15 innings across 15 matches, all powerplay
      - Mix of good and bad innings
      - Scores: 30, 5, 42, 18, 0, 55, 12, 8, 35, 20, 45, 3, 28, 15, 40

    Bowler bowl_star:
      - 15 spells across 15 matches, all powerplay
      - Mix of economical and expensive spells
    """
    np.random.seed(42)
    rows = []

    bat_scores = [30, 5, 42, 18, 0, 55, 12, 8, 35, 20, 45, 3, 28, 15, 40]
    bowl_figures = [
        # (runs_conceded_per_over, wickets_in_over)
        (5, 1),
        (8, 0),
        (3, 2),
        (7, 0),
        (10, 0),
        (4, 1),
        (6, 1),
        (9, 0),
        (2, 1),
        (7, 0),
        (5, 0),
        (3, 1),
        (8, 0),
        (4, 1),
        (6, 0),
    ]

    for i in range(15):
        mid = f"M1{i:02d}"
        date = f"2023-07-{i + 1:02d}"
        target_score = bat_scores[i]

        # Build a simple 1-over batting innings per match
        # Distribute the runs across 6 balls somewhat realistically
        total = bat_scores[i]
        ball_runs = [0] * 6
        remaining = total
        for b in range(6):
            if b == 5:
                ball_runs[b] = remaining
            elif remaining > 0:
                give = min(remaining, np.random.choice([0, 1, 2, 4, 6]))
                ball_runs[b] = give
                remaining -= give

        # If remaining is negative due to randomness, fix the last ball
        if remaining < 0:
            ball_runs[5] = max(0, ball_runs[5])

        # Ensure sum matches (adjust last ball)
        ball_runs[5] = total - sum(ball_runs[:5])
        if ball_runs[5] < 0:
            ball_runs = [0, 0, 0, 0, 0, total]

        # Batting innings
        rows += _build_over(
            mid,
            1,
            "Team Star",
            "Team Opp",
            0,
            "StarBatter",
            "bat_star",
            "BowlStar",
            "bowl_star",
            "Partner",
            "partner1",
            1,
            ball_runs,
            date=date,
        )

        # Bowling innings (same bowler bowls in innings 2)
        econ_target, wkts = bowl_figures[i]
        bowl_runs = [0] * 6
        bowl_remaining = econ_target
        for b in range(5):
            give = min(bowl_remaining, np.random.choice([0, 0, 1, 1, 2]))
            bowl_runs[b] = give
            bowl_remaining -= give
        bowl_runs[5] = max(0, econ_target - sum(bowl_runs[:5]))

        wkt_ball = 2 if wkts > 0 else None

        rows += _build_over(
            mid,
            2,
            "Team Opp",
            "Team Star",
            0,
            "OppBatter",
            "opp_bat1",
            "BowlStar",
            "bowl_star",
            "OppPartner",
            "opp_bat2",
            1,
            bowl_runs,
            date=date,
            wicket_on_ball=wkt_ball,
            target_runs=target_score + 1,
        )

    df = pd.DataFrame(rows)
    return df


@pytest.fixture
def synthetic_deliveries_with_extras():
    """
    A small dataset with wides and no-balls to test extras handling.

    Match M020, Innings 1:
      Over 0 bowled by Bowler W — includes 2 wides and 1 no-ball among
      the 6 legal deliveries (so 9 total deliveries).
    """
    rows = []
    mid = "M020"
    cum_score = 0
    seq = 0

    # 9 deliveries: 6 legal + 2 wides + 1 noball
    delivery_specs = [
        # (batter_runs, is_wide, is_noball, extras_type)
        (0, True, False, "wide"),  # wide: +1 run
        (1, False, False, None),  # legal: 1 run
        (0, False, False, None),  # legal: dot
        (0, True, False, "wide"),  # wide: +1 run
        (4, False, False, None),  # legal: 4
        (1, False, True, "noball"),  # noball: 1 batter + 1 extra
        (0, False, False, None),  # legal: dot
        (6, False, False, None),  # legal: 6
        (2, False, False, None),  # legal: 2
    ]

    legal_count = 0
    for i, (br, is_w, is_nb, ext_type) in enumerate(delivery_specs):
        is_leg = not is_w and not is_nb
        extras = 0
        wide_r = 0
        noball_r = 0
        total = br

        if is_w:
            wide_r = 1
            extras = 1
            total = 1  # wide ball: 1 extra run
        elif is_nb:
            noball_r = 1
            extras = 1
            total = br + 1  # batter_runs + 1 noball extra

        d = _make_delivery(
            match_id=mid,
            innings_num=1,
            batting_team="Team W",
            bowling_team="Team X",
            over=0,
            ball_idx=i,
            legal_ball_seq=seq,
            batter="BatterW",
            batter_id="batW",
            bowler="BowlerW",
            bowler_id="bowlW",
            non_striker="BatterX",
            non_striker_id="batX",
            batting_position=1,
            batter_runs=br,
            extras_runs=extras,
            total_runs=total,
            wide_runs=wide_r,
            noball_runs=noball_r,
            is_wide=is_w,
            is_noball=is_nb,
            is_legal=is_leg,
            is_batter_ball=not is_w,
            is_four=(br == 4),
            is_six=(br == 6),
            is_dot_batter=(br == 0 and not is_w),
            is_dot_bowler=(total == 0),
            phase="powerplay",
            team_score_before=cum_score,
        )
        rows.append(d)
        cum_score += total
        if is_leg:
            seq += 1
            legal_count += 1

    df = pd.DataFrame(rows)
    return df


@pytest.fixture
def innings_context_simple(synthetic_deliveries_simple):
    """Pre-built innings context from the simple synthetic data."""
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.context import compute_innings_context

    return compute_innings_context(synthetic_deliveries_simple)


@pytest.fixture
def match_context_simple(innings_context_simple):
    """Pre-built match context from the simple synthetic data."""
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.context import compute_match_context

    return compute_match_context(innings_context_simple)


@pytest.fixture
def full_context_simple(synthetic_deliveries_simple):
    """Pre-built full context (innings + match merged) from simple data."""
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.context import build_full_context

    return build_full_context(synthetic_deliveries_simple)
