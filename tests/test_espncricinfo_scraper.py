import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.espncricinfo_scraper import (
    classify_match,
    default_start_date,
    match_output_path,
    normalise_competitions,
)


def test_normalise_competitions_deduplicates_and_preserves_order():
    assert normalise_competitions(["ipl", "T20I", "ipl"]) == ["ipl", "t20i"]


def test_default_start_date_uses_earliest_requested_competition():
    assert default_start_date(["ipl", "t20i"]).isoformat() == "2005-02-17"


def test_classify_match_detects_ipl_from_series_name():
    assert (
        classify_match(
            series_name="Indian Premier League 2024",
            match_class="T20",
            competitions=["ipl", "t20i"],
        )
        == "ipl"
    )


def test_classify_match_detects_t20i_and_wt20i():
    assert (
        classify_match(
            series_name="India in Australia 2024/25",
            match_class="T20I",
            competitions=["t20i"],
        )
        == "t20i"
    )
    assert (
        classify_match(
            series_name="Women's Ashes 2025",
            match_class="WT20I",
            competitions=["t20i"],
        )
        == "t20i"
    )


def test_classify_match_skips_domestic_t20_when_not_requested():
    assert (
        classify_match(
            series_name="Big Bash League 2024/25",
            match_class="T20",
            competitions=["t20i", "ipl"],
        )
        is None
    )


def test_match_output_path_groups_by_competition_season_and_series():
    path = match_output_path(
        Path("espncricinfo_raw"),
        competition="ipl",
        season="2024",
        match_date="2024-05-26",
        match_id=1449924,
        series_name="Indian Premier League 2024",
    )
    assert path.as_posix() == (
        "espncricinfo_raw/ipl/2024/indian-premier-league-2024/1449924.json"
    )
