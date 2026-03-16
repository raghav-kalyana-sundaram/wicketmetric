from __future__ import annotations

from typing import Any

IN_SCOPE = ("test", "odi", "t20i", "ipl", "wpl", "bbl", "wbbl")
T20_METRICS = ("t20i", "ipl", "wpl", "bbl", "wbbl")
LEAGUES = ("ipl", "wpl", "bbl", "wbbl")

LABELS = {
    "test": "Tests",
    "odi": "ODI",
    "t20i": "T20I",
    "ipl": "IPL",
    "wpl": "WPL",
    "bbl": "BBL",
    "wbbl": "WBBL",
}

GENDER_LABEL = {"male": "Men", "female": "Women"}

README_CODE = {
    "Test": "test",
    "ODI": "odi",
    "ODM": None,  # domestic List A — international ODIs only
    "T20": None,  # depends on team_type
    "IT20": "t20i",
    "IPL": "ipl",
    "WPL": "wpl",
    "BBL": "bbl",
    "WBB": "wbbl",
}

FORMAT_ALIASES = {
    "test": "test",
    "tests": "test",
    "odi": "odi",
    "odm": "odi",
    "odis": "odi",
    "t20i": "t20i",
    "t20": "t20i",
    "it20": "t20i",
    "ipl": "ipl",
    "wpl": "wpl",
    "bbl": "bbl",
    "wbbl": "wbbl",
    "wbb": "wbbl",
}


def classify_match(info: dict[str, Any], readme_code: str | None = None) -> str | None:
    """Return a v1 competition key, or None if out of scope."""
    if readme_code:
        mapped = README_CODE.get(readme_code)
        if mapped:
            return mapped
        if readme_code in ("T20", "IT20"):
            team_type = (info.get("team_type") or "").lower()
            if team_type == "international" or readme_code == "IT20":
                return "t20i"

    match_type = (info.get("match_type") or "").lower()
    team_type = (info.get("team_type") or "").lower()
    event = info.get("event") or {}
    event_name = (event.get("name") or "").lower()

    if match_type == "test":
        return "test"
    if match_type in {"odi", "odm"} and team_type == "international":
        return "odi"
    if "indian premier league" in event_name:
        return "ipl"
    if "women's premier league" in event_name or "womens premier league" in event_name:
        return "wpl"
    if "women's big bash" in event_name or "wbbl" in event_name:
        return "wbbl"
    if "big bash" in event_name:
        return "bbl"
    if team_type == "international" and match_type in {"t20", "it20"}:
        return "t20i"
    if match_type == "it20":
        return "t20i"
    return None


def normalize_format(value: str) -> str | None:
    return FORMAT_ALIASES.get(value.strip().lower())


def normalize_stage(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    mapping = {
        "final": "final",
        "qualifier 1": "qualifier",
        "qualifier 2": "qualifier",
        "qualifier": "qualifier",
        "eliminator": "eliminator",
        "semi-final": "semi",
        "semi final": "semi",
        "semifinal": "semi",
        "group": "group",
        "group stage": "group",
        "league": "group",
        "3rd place play-off": "third_place",
    }
    if s in mapping:
        return mapping[s]
    if "qualifier" in s:
        return "qualifier"
    if "eliminator" in s:
        return "eliminator"
    if "semi" in s:
        return "semi"
    if "final" in s:
        return "final"
    if "group" in s:
        return "group"
    return s.replace(" ", "_")[:40]


def is_world_cup(event_name: str | None) -> bool:
    if not event_name:
        return False
    n = event_name.lower()
    return "world cup" in n or "worldcup" in n
