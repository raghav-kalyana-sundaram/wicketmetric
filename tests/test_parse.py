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
    closing_pair = next(
        p for p in parsed["partnerships"]
        if p["innings"] == 1 and p["end_reason"] == "end_of_innings"
    )
    assert closing_pair["wicket_number"] == 2
    bumrah = next(b for b in parsed["bowling_lines"] if b["person_id"] == "bbbb2222")
    assert bumrah["wickets"] == 1
    assert bumrah["extras"] == 1


def test_query_heuristic_kohli_89():
    q = parse_query("kohli 89")
    assert q.tokens["player"] == "kohli"
    assert q.tokens["runs"] == "89"
    assert q.heuristic == "runs:89 (exact)"
    assert q.mode == "innings"


def test_nl_sachin_new_zealand_94():
    q = parse_query("Sachin Tendulkar New Zealand 94")
    assert q.tokens["player"] == "Sachin Tendulkar"
    assert q.tokens.get("side") == "New Zealand" or q.tokens.get("opposition") == "New Zealand"
    assert q.tokens["runs"] == "94"
    assert q.mode == "innings"


def test_nl_year_is_not_a_score():
    q = parse_query("Sachin Tendulkar New Zealand 1994")
    assert q.tokens["player"] == "Sachin Tendulkar"
    assert q.tokens.get("year") == "1994"
    assert "runs" not in q.tokens
    assert q.mode == "matches"


def test_nl_india_vs_new_zealand():
    q = parse_query("India vs New Zealand 1994")
    assert q.mode == "matches"
    assert q.tokens.get("home") == "India"
    assert q.tokens.get("away") == "New Zealand"
    assert q.tokens.get("year") == "1994"
    assert "compare" not in q.tokens


def test_nl_player_vs_team():
    q = parse_query("Kohli vs New Zealand")
    assert q.tokens["player"] == "Kohli"
    assert q.tokens.get("opposition") == "New Zealand"
    assert q.mode == "matches"


def test_nl_apostrophe_year():
    q = parse_query("Sachin Tendulkar New Zealand '94")
    assert q.tokens["player"] == "Sachin Tendulkar"
    assert q.tokens.get("year") == "1994"
    assert "runs" not in q.tokens


def test_compare_still_two_players():
    q = parse_query("kohli vs rohit")
    assert q.mode == "compare"
    assert q.tokens["compare"] == "kohli,rohit"


def test_sachin_nz_94_falls_back_to_1994_series():
    from cricwarehouse.app.db import warehouse_ready
    from cricwarehouse.app.query import execute

    if not warehouse_ready():
        return
    res = execute("Sachin Tendulkar New Zealand 94")
    assert res.get("ok") is True
    if res.get("year_fallback") == "1994":
        assert res.get("kind") in {"matches", "goto_match"}
        assert (res.get("rows") or res.get("match_id"))
    elif res.get("kind") == "innings":
        assert all(int(r["runs"]) == 94 for r in res.get("rows") or [])


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


def test_runs_range_swaps_and_unfiltered_stays_empty():
    from cricwarehouse.app.db import warehouse_ready
    from cricwarehouse.app.query import parse_query, execute

    q = parse_query("runs:100-50")
    assert q.tokens["runs"] == "100-50"
    if not warehouse_ready():
        return
    result = execute("format:foo")
    assert result.get("kind") == "empty"
    assert result.get("rows") == []
    swapped = execute("player:kohli runs:100-50")
    assert swapped.get("ok") is True
    if swapped.get("kind") == "innings":
        for row in swapped.get("rows") or []:
            assert 50 <= int(row["runs"]) <= 100


def test_compare_rohit_resolves_to_rohit_sharma():
    from cricwarehouse.app.db import warehouse_ready
    from cricwarehouse.app.query import execute

    if not warehouse_ready():
        return
    res = execute("kohli vs rohit")
    if res.get("kind") == "compare":
        assert res["right"]["slug"] == "rg-sharma"
        assert "Damodaran" not in (res["right"].get("display_name") or "")


def test_record_kind_aliases():
    from cricwarehouse.app.records import RECORD_ALIASES, records
    from cricwarehouse.app.db import warehouse_ready

    assert RECORD_ALIASES["fastest_hundreds"] == "fast_hundreds"
    if not warehouse_ready():
        return
    d = records(kind="fastest_hundreds", comp="ipl", limit=3)
    assert d["kind"] == "fast_hundreds"
    ducks = records(kind="ducks", comp="ipl", limit=3)
    assert ducks["kind"] == "ducks"


def test_portable_date_and_sql_guard():
    from cricwarehouse.app.serve import _fmt_date, create_app
    from fastapi.testclient import TestClient

    assert _fmt_date("2024-08-09") == "9 Aug 2024"
    client = TestClient(create_app())
    blocked = client.post("/api/sql", json={"sql": "SELECT 1; DROP TABLE matches"})
    assert blocked.json().get("ok") is False


def test_wtc_pool_and_comps():
    from cricwarehouse.teams import WTC_TEAMS, default_pool, parse_comps, wtc_params

    assert "India" in WTC_TEAMS
    assert "Afghanistan" not in wtc_params("male")
    assert default_pool("male") == "t20i_ipl"
    assert parse_comps("t20i_ipl") == ["t20i", "ipl"]
