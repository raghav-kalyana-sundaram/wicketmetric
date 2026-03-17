from pathlib import Path

from cricwarehouse.app.parse import parse_match_file
from cricwarehouse.app.query import parse_query

FIXTURE = Path(__file__).parent / "fixtures" / "ipl_mini.json"


def test_parse_ipl_mini_totals():
    parsed = parse_match_file(FIXTURE, readme_code="IPL")
    assert parsed is not None
    m = parsed["match"]
    assert m["competition"] == "ipl"
    assert m["result_method"] == "regular"
    assert m["balls_per_over"] == 6
    inn0 = next(i for i in parsed["innings"] if i["innings"] == 1)
    assert inn0["runs"] == 30
    assert inn0["wickets"] == 1
    kohli = next(b for b in parsed["batting_lines"] if b["person_id"] == "ba607b88")
    assert kohli["runs"] == 26
    assert kohli["balls"] == 7
    assert kohli["fours"] == 3
    assert kohli["sixes"] == 2
    assert kohli["not_out"] is True
    pair = parsed["partnerships"][0]
    assert pair["runs"] == 29
    assert {pair["person_id_1"], pair["person_id_2"]} == {"ba607b88", "aaaa1111"}
    bumrah = next(b for b in parsed["bowling_lines"] if b["person_id"] == "bbbb2222")
    assert bumrah["wickets"] == 1
    assert bumrah["extras"] == 1


def test_query_heuristic_kohli_89():
    q = parse_query("kohli 89")
    assert q.tokens["player"] == "kohli"
    assert q.tokens["runs"] == "89"
    assert q.heuristic == "runs:89 (exact)"
    assert q.mode == "innings"


def test_query_out_bowled():
    q = parse_query("player:kohli out:bowled")
    assert q.tokens["out"] == "bowled"


def test_unknown_format_ignored():
    q = parse_query("player:kohli format:t30")
    assert "format:t30" in q.ignored
    assert "format" not in q.tokens


def test_bare_war_is_leaderboard_mode():
    q = parse_query("war format:t20i min_balls:200")
    assert q.mode == "war"
    assert q.tokens.get("format") == "t20i"
    assert "player" not in q.tokens


def test_odi_is_in_scope():
    from cricwarehouse.competitions import classify_match

    assert classify_match({"match_type": "ODI", "team_type": "international"}, "ODI") == "odi"
    assert classify_match({"match_type": "ODM", "team_type": "international"}) == "odi"
    assert classify_match({"match_type": "ODI", "team_type": "club"}) is None
    assert classify_match({"match_type": "ODM", "team_type": "domestic"}, "ODM") is None


def test_wtc_pool_and_comps():
    from cricwarehouse.teams import WTC_TEAMS, default_pool, parse_comps, wtc_params

    assert "India" in WTC_TEAMS
    assert "Afghanistan" not in wtc_params("male")
    assert default_pool("male") == "t20i_ipl"
    assert parse_comps("t20i_ipl") == ["t20i", "ipl"]
