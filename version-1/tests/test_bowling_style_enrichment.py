"""Unit tests for ESPN / Cricsheet bowling style enrichment (no live HTTP)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.bowling_style_enrichment import (
    build_enrichment_frame,
    classify_bowling_kind,
    extract_bowling_description,
    load_cricsheet_people_register,
    names_match_cricsheet_to_athlete,
    normalize_registry_id,
    verify_player_identity,
)


def test_normalize_registry_id_strips_hyphens():
    assert normalize_registry_id("A343262C-CE38-4B99-AF93-D34C8DADC379") == (
        "a343262cce384b99af93d34c8dadc379"
    )
    assert normalize_registry_id("abc12345") == "abc12345"


def test_classify_bowling_kind():
    assert classify_bowling_kind("Right-arm fast-medium") == "pace"
    assert classify_bowling_kind("Left-arm medium fast") == "pace"
    assert classify_bowling_kind("Right-arm offbreak") == "spin"
    assert classify_bowling_kind("Slow left-arm orthodox") == "spin"
    assert classify_bowling_kind(None) == "unknown"
    assert classify_bowling_kind("") == "unknown"


def test_extract_bowling_description():
    athlete = {
        "style": [
            {"type": "batting", "description": "Right-hand bat"},
            {"type": "bowling", "description": "Right-arm fast"},
        ]
    }
    assert extract_bowling_description(athlete) == "Right-arm fast"


def test_names_match_cricsheet_to_athlete():
    athlete = {
        "battingName": "JE Root",
        "name": "Joe Root",
        "firstName": "Joe",
        "middleName": "Edward",
        "lastName": "Root",
        "fullName": "Joseph Edward Root",
    }
    assert names_match_cricsheet_to_athlete("JE Root", athlete)
    assert names_match_cricsheet_to_athlete("Joe Root", athlete)
    assert not names_match_cricsheet_to_athlete("AB de Villiers", athlete)


def test_verify_player_identity_any_label():
    athlete = {
        "name": "Joe Root",
        "battingName": "JE Root",
        "firstName": "Joe",
        "lastName": "Root",
        "fullName": "Joseph Edward Root",
    }
    assert verify_player_identity("Wrong", "Joe Root", "", athlete)
    assert verify_player_identity("JE Root", "", "", athlete)


def test_load_cricsheet_people_register(tmp_path: Path):
    p = tmp_path / "people.csv"
    p.write_text(
        "identifier,name,unique_name,key_cricinfo\n"
        "bowlid1,JE Root,JE Root,303669\n"
        "bowlid2,,,,\n",
        encoding="utf-8",
    )
    reg = load_cricsheet_people_register(p)
    assert len(reg) == 1
    assert reg.iloc[0]["key_cricinfo"] == "303669"


def test_build_enrichment_frame_verifies_identity(monkeypatch, tmp_path: Path):
    people = tmp_path / "people.csv"
    people.write_text(
        "identifier,name,unique_name,key_cricinfo\n"
        "bowlid1,JE Root,JE Root,303669\n"
        "bowlid2,Other,Other,999999\n",
        encoding="utf-8",
    )
    cache = tmp_path / "cache"

    root_json = {
        "name": "Joe Root",
        "battingName": "JE Root",
        "firstName": "Joe",
        "middleName": "Edward",
        "lastName": "Root",
        "fullName": "Joseph Edward Root",
        "style": [
            {"type": "batting", "description": "Right-hand bat"},
            {"type": "bowling", "description": "Right-arm offbreak"},
        ],
    }
    wrong_json = {
        "name": "Someone Else",
        "battingName": "S Else",
        "firstName": "Someone",
        "lastName": "Else",
        "fullName": "Someone Else",
        "style": [{"type": "bowling", "description": "Right-arm fast"}],
    }

    def fake_fetch(player_id: str, **kwargs):
        if player_id == "303669":
            return root_json
        if player_id == "999999":
            return wrong_json
        return None

    monkeypatch.setattr(
        "src.bowling_style_enrichment.fetch_athlete_json",
        fake_fetch,
    )

    bc = pd.DataFrame(
        {
            "bowler_id": ["bowlid1", "bowlid2"],
            "bowler": ["JE Root", "Other"],
            "matches": [50, 40],
        }
    )
    enr = build_enrichment_frame(
        bc,
        people,
        cache_dir=cache,
        sleep_seconds=0.0,
        skip_network=False,
    )
    by_id = enr.set_index("bowler_id")
    assert by_id.loc["bowlid1", "bowling_style_verified"] is True
    assert by_id.loc["bowlid1", "bowling_kind"] == "spin"
    assert "offbreak" in by_id.loc["bowlid1", "bowling_style"].lower()
    assert by_id.loc["bowlid2", "bowling_style_verified"] is False
    assert by_id.loc["bowlid2", "bowling_kind"] == "unknown"
