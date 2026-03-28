"""Tests for ICC-based T20I match tier filtering."""

from __future__ import annotations

from routers.match_scorecards import _scorecard_passes_match_tier


def test_match_tier_main_only():
    main = frozenset({"India", "Australia"})
    sc = {
        "meta": {"teams": ["India", "Australia"]},
        "innings": {},
    }
    assert _scorecard_passes_match_tier(sc, tier="main_only", main_names=main)
    assert not _scorecard_passes_match_tier(
        sc,
        tier="main_only",
        main_names=frozenset({"India"}),
    )


def test_match_tier_associate_fixture():
    main = frozenset({"India", "Australia"})
    sc = {"meta": {"teams": ["India", "Nepal"]}, "innings": {}}
    assert _scorecard_passes_match_tier(sc, tier="associate_fixture", main_names=main)
    assert not _scorecard_passes_match_tier(
        {"meta": {"teams": ["India", "Australia"]}, "innings": {}},
        tier="associate_fixture",
        main_names=main,
    )


def test_match_tier_unlisted_side_is_associate():
    main = frozenset({"India", "Australia"})
    sc = {"meta": {"teams": ["India", "Romania"]}, "innings": {}}
    assert _scorecard_passes_match_tier(sc, tier="associate_fixture", main_names=main)
    assert not _scorecard_passes_match_tier(sc, tier="main_only", main_names=main)
