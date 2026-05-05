import json
from pathlib import Path

from cricbase.ingest_cricsheet import derive_scorecards, parse_match


def test_lbw_scorecard_from_docs_example():
    deliveries = [
        {
            "over_number": 12,
            "batter_id": "prior",
            "bowler_id": "harbhajan",
            "non_striker_id": "strauss",
            "runs_batter": 0,
            "extras_wides": 0,
            "extras_noballs": 0,
            "is_four": 0,
            "is_six": 0,
        }
    ]
    wickets = [
        {
            "player_out_id": "prior",
            "kind": "lbw",
            "bowler_id": "harbhajan",
            "fielder_ids": None,
        }
    ]
    batting, bowling = derive_scorecards(deliveries, wickets)
    prior = next(row for row in batting if row["player_id"] == "prior")
    harbhajan = next(row for row in bowling if row["player_id"] == "harbhajan")
    assert prior["dismissal_kind"] == "lbw"
    assert prior["not_out"] == 0
    assert prior["balls"] == 1
    assert harbhajan["wickets"] == 1


def test_parse_filters_non_test_nations():
    payload = {
        "info": {
            "gender": "male",
            "match_type": "ODI",
            "teams": ["India", "Netherlands"],
            "registry": {"people": {}},
            "players": {},
            "dates": ["2023-01-01"],
            "toss": {},
            "outcome": {},
        },
        "innings": [],
    }
    assert parse_match(Path("1.json"), payload, "male") is None


def test_parse_keeps_test_nation_odi():
    payload = {
        "info": {
            "gender": "male",
            "match_type": "ODI",
            "teams": ["India", "Australia"],
            "season": "2022/23",
            "registry": {"people": {"V Kohli": "a1b2c3d4", "DA Warner": "e5f6g7h8"}},
            "players": {"India": ["V Kohli"], "Australia": ["DA Warner"]},
            "dates": ["2023-01-01"],
            "toss": {"winner": "India", "decision": "bat"},
            "outcome": {"winner": "India", "by": {"runs": 10}},
            "balls_per_over": 6,
        },
        "innings": [],
    }
    parsed = parse_match(Path("1144530.json"), payload, "male")
    assert parsed is not None
    assert parsed["match"][2] == "ODI"
    assert parsed["match"][11] == "India"
    assert json.dumps(parsed["match_players"])
