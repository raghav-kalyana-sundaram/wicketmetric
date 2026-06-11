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
    "odi": "ODI",
    "test": "Tests",
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
    "odi": ("odi",),
    "test": ("test",),
    "t20": ("t20i", "ipl", "wpl", "bbl", "wbbl"),
}

METRIC_COPY = {
    "war": "Wins above a replacement player. Career total — more games count for more.",
    "war_per_game": "Career WAR divided by matches in this pool (20-game floor). A 400-game career is not the same pile as a dozen T20Is.",
    "rae_bat": "Batting RAE per game in this pool (20-game floor). Career pile divided by matches — a long career is not a higher rate.",
    "rae_bowl": "Bowling RAE per game in this pool (20-game floor). Runs saved versus expected, per match.",
    "wpa": "Win probability added, in wins. Noisy in blowouts; NRC/RAE carries more weight.",
    "pressure": "RAE weighted toward death overs and tight chases.",
    "war_bat": "Batting wins above replacement. Batting runs above replacement divided by the runs-per-win constant for this competition.",
    "war_bowl": "Bowling wins above replacement, on the same run scale as batting, so the two add up.",
    "raa_bat": "Runs above average with the bat. Every ball is compared with what an average batter produces from the same balls remaining, wickets in hand and target pressure.",
    "raa_bowl": "Runs above average with the ball, counting runs conceded and wickets taken against the same situation.",
    "raa100_bat": "Batting runs above average per 100 balls faced. A rate, so a short season can top it.",
    "raa_over_bowl": "Bowling runs above average per over. Negative means worse than average.",
    "vorp_bat": "Batting runs above replacement — runs above average, less what a fringe player in the same batting position would have produced.",
    "vorp_bowl": "Bowling runs above replacement, using a fringe bowler in the same phase as the baseline.",
    "tsr": "True strike-rate residual: runs per 100 balls above what the same situation usually yields. Scoring only — dismissals sit in TWR.",
    "te": "True economy residual: runs per over conceded above expectation. Negative is good.",
    "twr_bat": "True wicket-rate residual: dismissals per 100 balls above expectation. Negative means harder to get out than the situation implies.",
    "twr_bowl": "True wicket-rate residual: wickets per 100 balls above expectation. Positive is good.",
    "four_residual": "Fours per 100 balls above expectation for the situation.",
    "six_residual": "Sixes per 100 balls above expectation.",
    "dot_residual_bat": "Dot balls per 100 faced above expectation. Positive means more dots than the situation implies.",
    "dot_residual_team": "Dots per 100 balls bowled above expectation.",
    "xr_event": "Wides and no-balls per 100 deliveries attempted. Counts extra deliveries, not extra runs.",
    "xr_runs": "Runs per over given away in wides and no-balls.",
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
