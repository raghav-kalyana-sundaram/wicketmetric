from datetime import date
from pathlib import Path

import sqlite3

from cricwarehouse.app.cricbase import load_historical, parse_statsguru_date
from cricwarehouse.app.parse import slugify


def test_year_spanning_test_date():
    assert parse_statsguru_date("Dec 30, 1882 - Jan 2, 1883") == date(1882, 12, 30)
    assert parse_statsguru_date("Mar 15-19, 1877") == date(1877, 3, 15)
    assert parse_statsguru_date("15 Mar 1877") == date(1877, 3, 15)


def _seed(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE players (
            player_id TEXT PRIMARY KEY,
            name TEXT, unique_name TEXT, cricinfo_id TEXT,
            cricketarchive_id TEXT, cricbuzz_id TEXT
        );
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY, match_type TEXT, gender TEXT,
            start_date TEXT, venue TEXT, city TEXT, event_name TEXT,
            team1 TEXT, team2 TEXT, toss_winner TEXT, toss_decision TEXT,
            winner TEXT, result TEXT, win_runs INTEGER, win_wickets INTEGER,
            win_innings INTEGER, balls_per_over INTEGER, source TEXT
        );
        CREATE TABLE match_players (
            match_id TEXT, team TEXT, player_id TEXT
        );
        CREATE TABLE innings (
            match_id TEXT, innings_number INTEGER, batting_team TEXT,
            declared INTEGER, forfeited INTEGER
        );
        CREATE TABLE batting_innings (
            match_id TEXT, innings_number INTEGER, player_id TEXT,
            batting_position INTEGER, runs INTEGER, balls INTEGER,
            fours INTEGER, sixes INTEGER, dismissal_kind TEXT,
            bowler_id TEXT, not_out INTEGER
        );
        CREATE TABLE bowling_innings (
            match_id TEXT, innings_number INTEGER, player_id TEXT,
            balls INTEGER, runs INTEGER, wickets INTEGER, maidens INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO players VALUES ('bannerman','C Bannerman','C Bannerman','4091',NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO players VALUES ('shaw','A Shaw','A Shaw','1',NULL,NULL)"
    )
    conn.execute(
        """
        INSERT INTO matches VALUES (
            '62396','Test','male',NULL,'Melbourne','Melbourne',NULL,
            'Australia','England',NULL,NULL,'Australia','won',45,NULL,NULL,4,'cricinfo'
        )
        """
    )
    conn.execute("INSERT INTO match_players VALUES ('62396','Australia','bannerman')")
    conn.execute("INSERT INTO match_players VALUES ('62396','England','shaw')")
    conn.execute("INSERT INTO innings VALUES ('62396',1,'Australia',0,0)")
    conn.execute(
        """
        INSERT INTO batting_innings VALUES (
            '62396',1,'bannerman',1,165,0,18,0,NULL,NULL,1
        )
        """
    )
    conn.execute(
        "INSERT INTO bowling_innings VALUES ('62396',1,'shaw',224,73,3,10)"
    )
    conn.commit()
    conn.close()


def test_load_historical_maps_scorecard(tmp_path: Path):
    db = tmp_path / "cricbase.sqlite"
    _seed(db)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "match_results_1877.html").write_text(
        '<td nowrap="nowrap">Mar 15-19, 1877</td>'
        '<td nowrap="nowrap"><a href="/ci/engine/match/62396.html">Test # 1</a></td>',
        encoding="utf-8",
    )
    buckets = load_historical(db, cache_dir=cache)
    match = buckets["matches"][0]
    assert match["match_id"] == "62396"
    assert match["competition"] == "test"
    assert match["source"] == "cricinfo"
    assert match["start_date"] == "1877-03-15"
    assert match["win_by_runs"] == 45
    assert match["balls_per_over"] == 4
    inn = buckets["innings"][0]
    assert inn["batting_team"] == "Australia"
    assert inn["bowling_team"] == "England"
    assert inn["runs"] == 165
    assert inn["legal_balls"] == 224
    bat = buckets["batting_lines"][0]
    assert bat["person_id"] == "bannerman"
    assert bat["runs"] == 165
    assert bat["not_out"] is True
    assert bat["team"] == "Australia"
    bowl = buckets["bowling_lines"][0]
    assert bowl["person_id"] == "shaw"
    assert bowl["wickets"] == 3
    assert bowl["team"] == "England"
    people = {p["person_id"]: p for p in buckets["people"]}
    assert people["bannerman"]["slug"] == slugify("C Bannerman")
    assert people["bannerman"]["key_cricinfo"] == "4091"


def test_skips_matches_already_in_warehouse(tmp_path: Path):
    db = tmp_path / "cricbase.sqlite"
    _seed(db)
    buckets = load_historical(db, existing_ids={"62396"})
    assert buckets["matches"] == []
    assert buckets["batting_lines"] == []
