"""Tests for ESPN cricket scoreboard proxy (cache, validation, stale fallback)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.live_espn import (
    blob_is_ipl_or_t20_international,
    build_events_summary,
    build_events_summary_from_header,
    extract_match_detail_for_ui,
    filter_events_by_league_slug,
    normalize_scoreboard_query,
    reset_cache_for_tests,
    router,
)


@pytest.fixture
def espn_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(espn_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    reset_cache_for_tests()
    monkeypatch.setenv("ESPN_LIVE_PROXY_ENABLED", "true")
    monkeypatch.setenv("ESPN_CRICKET_SCOREBOARD_CACHE_SEC", "90")
    return TestClient(espn_app)


def test_normalize_cache_key_equivalence() -> None:
    a = normalize_scoreboard_query("  IPL  ", None, " US ", None)
    b = normalize_scoreboard_query("ipl", None, "us", None)
    assert a.cache_key() == b.cache_key()
    assert a.league == "ipl"
    assert a.region == "us"


def test_normalize_dates_single_and_range() -> None:
    s = normalize_scoreboard_query("ipl", "20260324", None, None)
    assert s.dates == "20260324"
    r = normalize_scoreboard_query("ipl", "20260301-20260331", None, None)
    assert r.dates == "20260301-20260331"


def test_normalize_empty_league_raises() -> None:
    with pytest.raises(ValueError, match="league"):
        normalize_scoreboard_query("   ", None, None, None)


def test_build_events_summary_from_header_shape() -> None:
    raw = {
        "sports": [
            {
                "leagues": [
                    {
                        "id": "12345",
                        "name": "Indian Premier League",
                        "events": [
                            {
                                "id": "99",
                                "name": "A v B",
                                "shortName": "A v B",
                                "status": "in",
                                "link": "https://www.espn.com/cricket/game/99",
                                "fullStatus": {
                                    "summary": "Team A batting",
                                    "longSummary": "Team A 10/0 in 2 overs",
                                    "battingTeamId": 7,
                                    "type": {"shortDetail": "Live"},
                                },
                                "notes": [
                                    {"type": "matchnote", "text": "First note"},
                                    {"type": "matchnote", "text": "Latest note"},
                                ],
                                "competitors": [
                                    {
                                        "id": 7,
                                        "displayName": "Team A",
                                        "score": "10/0 (2 ov)",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    s = build_events_summary_from_header(raw)
    assert len(s) == 1
    assert s[0]["league_id"] == "12345"
    assert s[0]["league_name"] == "Indian Premier League"
    assert s[0]["score_line"] == "Team A 10/0 (2 ov)"
    assert s[0]["status"] == "Live"
    assert s[0]["competitors"][0]["score_display"] == "10/0 (2 ov)"
    assert s[0]["batting_team_name"] == "Team A"
    assert s[0]["situation_short"] == "Team A batting"
    assert s[0]["recent_note"] == "Latest note"
    assert s[0]["espn_url"] == "https://www.espn.com/cricket/game/99"


def test_blob_classifier_ipl_word_not_substring_false_positive() -> None:
    assert blob_is_ipl_or_t20_international("triple century in county") is False
    assert blob_is_ipl_or_t20_international("rcb ipl fixture tonight") is True


def test_build_header_excludes_odi_notes() -> None:
    raw = {
        "sports": [
            {
                "leagues": [
                    {
                        "id": "1",
                        "name": "World Cup",
                        "events": [
                            {
                                "id": "1",
                                "name": "A v B",
                                "notes": [{"type": "matchnumber", "text": "ODI no. 999"}],
                                "competitors": [],
                            }
                        ],
                    }
                ]
            }
        ]
    }
    assert build_events_summary_from_header(raw) == []


def test_build_header_keeps_t20i_notes() -> None:
    raw = {
        "sports": [
            {
                "leagues": [
                    {
                        "id": "2",
                        "name": "International",
                        "events": [
                            {
                                "id": "2",
                                "name": "X v Y",
                                "notes": [{"type": "matchnumber", "text": "T20I no. 2000"}],
                                "competitors": [
                                    {"displayName": "X", "score": "1/0"},
                                    {"displayName": "Y", "score": ""},
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }
    s = build_events_summary_from_header(raw)
    assert len(s) == 1
    assert s[0]["score_line"] == "X 1/0 · Y"


def test_filter_all_and_ipl() -> None:
    events = [
        {"league_name": "Indian Premier League", "name": "x", "short_name": "y"},
        {"league_name": "Other", "name": "a", "short_name": "b"},
    ]
    assert len(filter_events_by_league_slug(events, "all")) == 2
    assert len(filter_events_by_league_slug(events, "ipl")) == 1


def test_build_events_summary_shape() -> None:
    raw = {
        "events": [
            {
                "id": "123",
                "name": "Team A vs Team B",
                "shortName": "A @ B",
                "status": {"state": "in", "type": {"shortDetail": "Live"}},
                "competitions": [
                    {
                        "competitors": [
                            {
                                "team": {"shortDisplayName": "A"},
                                "score": {"displayValue": "45/1"},
                            },
                            {
                                "team": {"displayName": "Team B"},
                                "score": 12,
                            },
                        ]
                    }
                ],
            }
        ]
    }
    s = build_events_summary(raw)
    assert len(s) == 1
    ev = s[0]
    assert ev["event_id"] == "123"
    assert ev["name"] == "Team A vs Team B"
    assert ev["status"] == "Live"
    assert len(ev["competitors"]) == 2
    assert ev["competitors"][0]["score_display"] == "45/1"
    assert ev["competitors"][1]["score_display"] == "12"


def test_kill_switch(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPN_LIVE_PROXY_ENABLED", "false")
    r = client.get("/api/live/espn/cricket/scoreboard", params={"league": "ipl"})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert "payload" not in body
    assert "message" in body


def test_invalid_dates_422(client: TestClient) -> None:
    r = client.get(
        "/api/live/espn/cricket/scoreboard",
        params={"league": "ipl", "dates": "notadate"},
    )
    assert r.status_code == 422


def test_stale_fallback_returns_cached_payload(client: TestClient) -> None:
    from routers import live_espn as m

    reset_cache_for_tests()
    nq = normalize_scoreboard_query("ipl", None, None, None)
    key = nq.header_fetch_cache_key()
    m._CACHE[key] = {
        "stored_at": time.time() - 99999.0,
        "fetched_at_iso": "2020-01-01T00:00:00Z",
        "payload": {"sports": []},
        "events_summary_full": [
            {
                "event_id": "1",
                "name": "Stale match",
                "short_name": "",
                "status": "",
                "state": "",
                "league_name": "Indian Premier League",
                "competitors": [],
                "score_line": "",
            }
        ],
        "upstream_http_status": 200,
    }
    m._CACHE_ORDER.append(key)

    with patch.object(
        m,
        "_http_get_json",
        new=AsyncMock(return_value=(503, None, "HTTP 503")),
    ):
        r = client.get("/api/live/espn/cricket/scoreboard", params={"league": "ipl"})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["served_from_cache"] is True
    assert body["upstream_error"] == "HTTP 503"
    assert body.get("message") == "Serving stale data due to upstream failure."
    assert body["events_summary"][0]["name"] == "Stale match"


def test_miss_upstream_fail_empty_summary(client: TestClient) -> None:
    from routers import live_espn as m

    reset_cache_for_tests()
    with patch.object(
        m,
        "_http_get_json",
        new=AsyncMock(return_value=(500, None, "HTTP 500")),
    ):
        r = client.get("/api/live/espn/cricket/scoreboard", params={"league": "ipl"})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["served_from_cache"] is False
    assert body["upstream_error"] == "HTTP 500"
    assert body.get("events_summary") == []
    assert "payload" not in body


def test_extract_match_detail_for_ui_minimal() -> None:
    raw = {
        "header": {
            "name": "A v B",
            "shortName": "A v B",
            "competitions": [
                {
                    "status": {
                        "summary": "Live",
                        "battingTeamId": 1,
                        "type": {"shortDetail": "1st inn", "detail": "In progress"},
                    },
                    "competitors": [
                        {
                            "id": "1",
                            "homeAway": "home",
                            "score": "10/0",
                            "team": {"displayName": "A", "abbreviation": "AA"},
                            "linescores": [
                                {
                                    "period": 1,
                                    "runs": 10,
                                    "wickets": 0,
                                    "overs": 2.0,
                                    "score": "10/0 (2)",
                                    "isBatting": True,
                                    "description": "in progress",
                                    "fow": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        "gameInfo": {"venue": {"fullName": "Ground X"}},
        "notes": [{"type": "toss", "text": "A bat"}],
    }
    d = extract_match_detail_for_ui(raw)
    assert d["title"] == "A v B"
    assert d["venue"] == "Ground X"
    assert d["status"]["batting_team_id"] == "1"
    assert len(d["teams"]) == 1
    assert d["teams"][0]["name"] == "A"
    assert d["teams"][0]["innings"][0]["runs"] == 10
    assert d.get("matchcard_sections") == []
    assert d.get("recent_balls") == []


def test_extract_match_detail_includes_live_scorecards() -> None:
    raw = {
        "header": {
            "name": "X v Y",
            "competitions": [
                {
                    "status": {"summary": "Live", "type": {}},
                    "competitors": [],
                    "commentaries": {
                        "a": {
                            "sortOrder": 1.0,
                            "shortText": "dot",
                            "homeScore": "0",
                            "awayScore": "1/0",
                            "over": {"overs": 0, "ball": 1},
                        },
                        "b": {
                            "sortOrder": 2.0,
                            "shortText": "FOUR",
                            "dismissal": {"text": "caught at deep"},
                            "homeScore": "0",
                            "awayScore": "5/0",
                            "over": {"overs": 0, "ball": 2},
                        },
                    },
                }
            ],
        },
        "matchcards": [
            {
                "headline": "Batting TeamX",
                "teamName": "TeamX",
                "inningsNumber": 1,
                "extras": "lb 2",
                "total": "(all out; 20 ovs)",
                "playerDetails": [
                    {
                        "playerName": "Player One",
                        "runs": "40",
                        "ballsFaced": "30",
                        "fours": "5",
                        "sixes": "1",
                        "dismissal": "not out",
                    }
                ],
            },
            {
                "headline": "Bowling TeamY",
                "teamName": "TeamY",
                "inningsNumber": 1,
                "playerDetails": [
                    {
                        "playerName": "Bowler Z",
                        "overs": "4.0",
                        "maidens": "1",
                        "conceded": "20",
                        "wickets": "2",
                        "economyRate": "5",
                    }
                ],
            },
        ],
        "notes": [],
    }
    d = extract_match_detail_for_ui(raw)
    secs = d["matchcard_sections"]
    assert len(secs) == 2
    assert secs[0]["kind"] == "batting"
    assert secs[0]["rows"][0]["player"] == "Player One"
    assert secs[0]["rows"][0]["runs"] == "40"
    assert secs[1]["kind"] == "bowling"
    assert secs[1]["rows"][0]["wickets"] == "2"
    balls = d["recent_balls"]
    assert len(balls) == 2
    assert balls[0]["short_text"] == "FOUR"
    assert "caught" in balls[0]["summary"]
    assert balls[1]["short_text"] == "dot"


def test_summary_invalid_ids_422(client: TestClient) -> None:
    r = client.get(
        "/api/live/espn/cricket/summary",
        params={"league_id": "x", "event_id": "1"},
    )
    assert r.status_code == 422
    r2 = client.get(
        "/api/live/espn/cricket/summary",
        params={"league_id": "1", "event_id": ""},
    )
    assert r2.status_code == 422


def test_summary_kill_switch(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPN_LIVE_PROXY_ENABLED", "false")
    r = client.get(
        "/api/live/espn/cricket/summary",
        params={"league_id": "1", "event_id": "2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["detail"] is None


def test_summary_ok_and_stale_fallback(client: TestClient) -> None:
    from routers import live_espn as m

    reset_cache_for_tests()
    sample = {
        "header": {
            "name": "X v Y",
            "competitions": [
                {
                    "status": {"summary": "Fin", "type": {}},
                    "competitors": [],
                }
            ],
        },
        "notes": [],
    }
    with patch.object(
        m,
        "_http_get_json",
        new=AsyncMock(return_value=(200, sample, None)),
    ):
        r = client.get(
            "/api/live/espn/cricket/summary",
            params={"league_id": "99", "event_id": "100"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["detail"]["title"] == "X v Y"
    assert body["served_from_cache"] is False

    sk = m._summary_cache_key("99", "100")
    assert sk in m._SUMMARY_CACHE
    m._SUMMARY_CACHE[sk]["stored_at"] = time.time() - 99999.0

    with patch.object(
        m,
        "_http_get_json",
        new=AsyncMock(return_value=(500, None, "HTTP 500")),
    ):
        r2 = client.get(
            "/api/live/espn/cricket/summary",
            params={"league_id": "99", "event_id": "100"},
        )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["served_from_cache"] is True
    assert b2["detail"]["title"] == "X v Y"
    assert b2.get("upstream_error")
