"""World Test Championship sides — used to drop associate internationals."""

from __future__ import annotations

# 2025–27 WTC members. Same names as Cricsheet internationals.
WTC_TEAMS = (
    "Australia",
    "Bangladesh",
    "England",
    "India",
    "New Zealand",
    "Pakistan",
    "South Africa",
    "Sri Lanka",
    "West Indies",
)

# Women's Test-playing full members — same filter intent when WTC is checked.
WOMEN_TEST_TEAMS = WTC_TEAMS + ("Ireland",)

POOL_LABELS = {
    "t20i_ipl": "T20I + IPL",
    "t20i_wpl": "T20I + WPL",
    "t20i": "T20I",
    "ipl": "IPL",
    "wpl": "WPL",
    "t20": "All T20",
}

POOL_COMPS = {
    "t20i_ipl": ("t20i", "ipl"),
    "t20i_wpl": ("t20i", "wpl"),
    "t20i": ("t20i",),
    "ipl": ("ipl",),
    "wpl": ("wpl",),
    "bbl": ("bbl",),
    "wbbl": ("wbbl",),
    "t20": ("t20i", "ipl", "wpl", "bbl", "wbbl"),
}

METRIC_COPY = {
    "war": "Wins above a replacement player. Career total — more games count for more.",
    "war_per_season": "Career WAR divided by seasons with balls in this pool.",
    "rae_bat": "Runs scored versus expected, given over, wickets, and opposition.",
    "rae_bowl": "Runs saved versus expected on balls bowled. Higher is better.",
    "wpa": "Win probability added, in wins. Noisy in blowouts; NRC/RAE carries more weight.",
    "pressure": "RAE weighted toward death overs and tight chases.",
}


def wtc_params(gender: str | None) -> tuple[str, ...]:
    if gender == "female":
        return WOMEN_TEST_TEAMS
    return WTC_TEAMS


def wtc_match_sql(alias: str = "m") -> str:
    """Internationals must be WTC vs WTC. Leagues pass through."""
    return (
        f"({alias}.competition NOT IN ('test','odi','t20i') "
        f"OR ({alias}.team_home IN (SELECT team FROM wtc_teams) "
        f"AND {alias}.team_away IN (SELECT team FROM wtc_teams)))"
    )


def parse_comps(comp: str | None) -> list[str] | None:
    if not comp:
        return None
    key = comp.strip().lower().replace("+", "_").replace(" ", "_")
    if key in POOL_COMPS:
        return list(POOL_COMPS[key])
    if "," in key:
        return [c.strip() for c in key.split(",") if c.strip()]
    return [key]


def default_pool(gender: str | None) -> str:
    return "t20i_wpl" if gender == "female" else "t20i_ipl"
