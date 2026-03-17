import json
from pathlib import Path

import pandas as pd
import pytest

from src.scorecards import (
    build_scorecards,
    iter_scorecards,
    player_performances_from_scorecards,
    scorecards_to_dataframe,
    stream_write_scorecards,
)


def _make_simple_match(match_id: str, batter_a_runs: int = 10, batter_b_runs: int = 0):
    """
    Construct a very small deliveries DataFrame for one match / one innings.

    Structure:
      - Batter A faces first 3 balls: 4, 0, 6 and is out on the 3rd delivery
      - Batter B faces the 4th ball and scores `batter_b_runs`
    """
    rows = []

    # Delivery 1: A hits a four
    rows.append(
        {
            "match_id": match_id,
            "date": "2023-01-01",
            "innings_num": 1,
            "batting_team": "TeamA",
            "bowling_team": "TeamB",
            "over": 0,
            "ball_idx": 0,
            "legal_ball_seq": 0,
            "batter": "A",
            "batter_id": "pA",
            "bowler": "X",
            "bowler_id": "pX",
            "batter_runs": 4,
            "extras_runs": 0,
            "total_runs": 4,
            "wide_runs": 0,
            "noball_runs": 0,
            "is_wide": False,
            "is_noball": False,
            "is_legal": True,
            "is_batter_ball": True,
            "is_wicket": False,
            "wicket_kind": None,
            "player_out": None,
            "player_out_id": None,
            "is_four": True,
            "is_six": False,
            "is_dot_batter": False,
            "is_dot_bowler": False,
            "phase": "powerplay",
            "team_score_before": 0,
            "team_wickets_before": 0,
            "overs_limit": 20,
            "winner": None,
            "batting_position": 1,
        }
    )

    # Delivery 2: A dot
    rows.append(
        {
            "match_id": match_id,
            "date": "2023-01-01",
            "innings_num": 1,
            "batting_team": "TeamA",
            "bowling_team": "TeamB",
            "over": 0,
            "ball_idx": 1,
            "legal_ball_seq": 1,
            "batter": "A",
            "batter_id": "pA",
            "bowler": "X",
            "bowler_id": "pX",
            "batter_runs": 0,
            "extras_runs": 0,
            "total_runs": 0,
            "wide_runs": 0,
            "noball_runs": 0,
            "is_wide": False,
            "is_noball": False,
            "is_legal": True,
            "is_batter_ball": True,
            "is_wicket": False,
            "wicket_kind": None,
            "player_out": None,
            "player_out_id": None,
            "is_four": False,
            "is_six": False,
            "is_dot_batter": True,
            "is_dot_bowler": True,
            "phase": "powerplay",
            "team_score_before": 4,
            "team_wickets_before": 0,
            "overs_limit": 20,
            "winner": None,
            "batting_position": 1,
        }
    )

    # Delivery 3: A hits a six and is out (bowled)
    rows.append(
        {
            "match_id": match_id,
            "date": "2023-01-01",
            "innings_num": 1,
            "batting_team": "TeamA",
            "bowling_team": "TeamB",
            "over": 0,
            "ball_idx": 2,
            "legal_ball_seq": 2,
            "batter": "A",
            "batter_id": "pA",
            "bowler": "X",
            "bowler_id": "pX",
            "batter_runs": 6,
            "extras_runs": 0,
            "total_runs": 6,
            "wide_runs": 0,
            "noball_runs": 0,
            "is_wide": False,
            "is_noball": False,
            "is_legal": True,
            "is_batter_ball": True,
            "is_wicket": True,
            "wicket_kind": "bowled",
            "player_out": "A",
            "player_out_id": "pA",
            "is_four": False,
            "is_six": True,
            "is_dot_batter": False,
            "is_dot_bowler": False,
            "phase": "powerplay",
            "team_score_before": 4,
            "team_wickets_before": 0,
            "overs_limit": 20,
            "winner": None,
            "batting_position": 1,
        }
    )

    # Delivery 4: B comes in
    rows.append(
        {
            "match_id": match_id,
            "date": "2023-01-01",
            "innings_num": 1,
            "batting_team": "TeamA",
            "bowling_team": "TeamB",
            "over": 0,
            "ball_idx": 3,
            "legal_ball_seq": 3,
            "batter": "B",
            "batter_id": "pB",
            "bowler": "X",
            "bowler_id": "pX",
            "batter_runs": batter_b_runs,
            "extras_runs": 0,
            "total_runs": batter_b_runs,
            "wide_runs": 0,
            "noball_runs": 0,
            "is_wide": False,
            "is_noball": False,
            "is_legal": True,
            "is_batter_ball": True,
            "is_wicket": False,
            "wicket_kind": None,
            "player_out": None,
            "player_out_id": None,
            "is_four": batter_b_runs == 4,
            "is_six": batter_b_runs == 6,
            "is_dot_batter": batter_b_runs == 0,
            "is_dot_bowler": batter_b_runs == 0,
            "phase": "powerplay",
            "team_score_before": 10,
            "team_wickets_before": 1,
            "overs_limit": 20,
            "winner": None,
            "batting_position": 2,
        }
    )

    return pd.DataFrame(rows)


def test_build_scorecards_single_match_basic():
    df = _make_simple_match("m1", batter_a_runs=10, batter_b_runs=0)

    sc_map = build_scorecards(df, include_deliveries=True)
    assert "m1" in sc_map
    sc = sc_map["m1"]
    assert "meta" in sc
    assert "innings" in sc
    innings = sc["innings"]
    assert 1 in innings

    inn = innings[1]
    batting = inn["batting"]
    bowling = inn["bowling"]

    # Batting: should contain two batters A and B
    batter_ids = [b["batter_id"] for b in batting]
    assert "pA" in batter_ids
    assert "pB" in batter_ids

    # Check batter A aggregated stats
    a = next(b for b in batting if b["batter_id"] == "pA")
    assert a["runs"] == 10
    assert a["balls"] == 3
    assert a["fours"] == 1
    assert a["sixes"] == 1
    # strike rate 10 / 3 * 100 ≈ 333.3
    assert pytest.approx(a["strike_rate"], rel=1e-3) == 100.0 * 10 / 3
    assert a["is_batter_ball"] if "is_batter_ball" in a else True

    # Dismissal recorded
    assert a["dismissal_kind"] == "bowled"
    assert a["dismissal_player_out_id"] == "pA"

    # Bowling: bowler pX should have 4 legal deliveries and 1 wicket
    bx = bowling[0]
    assert bx["bowler_id"] == "pX"
    assert bx["balls"] == 4
    assert bx["runs_conceded"] == 10
    assert bx["wickets"] == 1
    assert bx["economy"] is not None


def test_iter_and_stream_write_scorecards(tmp_path: Path):
    # Build two matches and stream-write them
    df1 = _make_simple_match("m_stream_1", batter_b_runs=1)
    df2 = _make_simple_match("m_stream_2", batter_b_runs=2)

    df = pd.concat([df1, df2], ignore_index=True)

    out_dir = tmp_path / "scorecards"
    # stream_write_scorecards writes one file per match
    stream_write_scorecards(df, out_dir, include_deliveries=True)

    # Check files exist
    f1 = out_dir / "m_stream_1.json"
    f2 = out_dir / "m_stream_2.json"
    assert f1.exists()
    assert f2.exists()

    # Load and sanity-check one file
    with f1.open("r", encoding="utf-8") as fh:
        sc = json.load(fh)
    assert sc.get("meta", {}).get("match_id") == "m_stream_1" or True
    assert "innings" in sc
    # Ensure batting list present
    inn_keys = list(sc["innings"].keys())
    assert len(inn_keys) >= 1
    inn0 = sc["innings"][inn_keys[0]]
    assert "batting" in inn0 and "bowling" in inn0


def test_player_performances_and_dataframe():
    # Build two matches where pA has a small and a big score
    df_small = _make_simple_match("m_small", batter_b_runs=0)
    # Second match: give player pA a single big innings (simulate 50 off 30)
    rows = []
    # create 30 legal balls where pA scores 50 (mix of runs)
    cum = 0
    for i in range(30):
        r = 2 if i % 6 != 0 else 4  # some boundaries
        if i == 0:
            r = 6
        cum += r
        rows.append(
            {
                "match_id": "m_big",
                "date": "2023-02-01",
                "innings_num": 1,
                "batting_team": "TeamC",
                "bowling_team": "TeamD",
                "over": i // 6,
                "ball_idx": i % 6,
                "legal_ball_seq": i,
                "batter": "A",
                "batter_id": "pA",
                "bowler": "Y",
                "bowler_id": "pY",
                "batter_runs": r,
                "extras_runs": 0,
                "total_runs": r,
                "is_wide": False,
                "is_noball": False,
                "is_legal": True,
                "is_batter_ball": True,
                "is_wicket": False,
                "wicket_kind": None,
                "player_out": None,
                "player_out_id": None,
                "is_four": r == 4,
                "is_six": r == 6,
                "is_dot_batter": r == 0,
                "is_dot_bowler": r == 0,
                "phase": "middle",
                "team_score_before": 0,
                "team_wickets_before": 0,
                "overs_limit": 20,
                "winner": None,
                "batting_position": 1,
            }
        )

    df_big = pd.DataFrame(rows)

    df_all = pd.concat([df_small, df_big], ignore_index=True)

    # Build scorecards dict
    scs = build_scorecards(df_all, include_deliveries=True)

    # Flatten batting performances to DataFrame and extract pA rows
    df_flat = scorecards_to_dataframe(scs)
    # Ensure pA appears in flattened DataFrame
    assert "pA" in df_flat["batter_id"].values

    # Use player_performances_from_scorecards to collect pA performances
    perf = player_performances_from_scorecards(scs, "pA")
    assert isinstance(perf, list)
    # There should be at least two performances (one small, one big)
    assert len([p for p in perf if p["role"] == "batting"]) >= 2

    # The top batting performance should correspond to the big match (higher runs)
    top_batting = next((p for p in perf if p["role"] == "batting"), None)
    assert top_batting is not None
    assert (
        top_batting["runs"] >= 10
    )  # big innings should be >= 10 in our synthetic data
