"""Playing-condition constants the ball-by-ball engine needs.

Kept free of pandas and of the app package so the parser workers can import it
without dragging the metrics stack into every subprocess.

The dismissal table is the normative map from Section 6.2 of the methodology:
a wicket entry has three separate consequences, and conflating them is the
single most common way a cricket value model goes wrong. A run-out costs the
batting side a resource and is charged to the dismissed player, but it is not
bowling skill, so the bowler gets nothing for it.
"""

from __future__ import annotations

# kind -> (consumes team wicket, charge batter, credit bowler)
DISMISSALS: dict[str, tuple[int, int, int]] = {
    "bowled": (1, 1, 1),
    "lbw": (1, 1, 1),
    "hit wicket": (1, 1, 1),
    "caught": (1, 1, 1),
    "caught and bowled": (1, 1, 1),
    "stumped": (1, 1, 1),
    "run out": (1, 1, 0),
    # Retirement with intent to resume is not a lost resource: the batter may
    # come back. Cricsheet spells this several ways across eras.
    "retired hurt": (0, 0, 0),
    "retired not out": (0, 0, 0),
    "retired - hurt": (0, 0, 0),
    "retired - not out": (0, 0, 0),
    # Tactical or non-skill terminations. The side loses a wicket; nobody earns
    # or is charged for it, so the resource goes to the unallocated bucket.
    "retired out": (1, 0, 0),
    "retired - out": (1, 0, 0),
    "obstructing the field": (1, 0, 0),
    "hit the ball twice": (1, 0, 0),
    "handled the ball": (1, 0, 0),
    "timed out": (1, 0, 0),
    # Absent batters never came to the crease; the scorecard already reflects
    # them and no delivery exists to carry the transition.
    "absent hurt": (0, 0, 0),
    "absent ill": (0, 0, 0),
}

BOWLER_CREDITED = frozenset(k for k, v in DISMISSALS.items() if v[2])
BATTER_CHARGED = frozenset(k for k, v in DISMISSALS.items() if v[1])
TEAM_WICKET = frozenset(k for k, v in DISMISSALS.items() if v[0])
NO_RESOURCE_LOSS = frozenset(k for k, v in DISMISSALS.items() if not v[0])

# Dismissals the laws make impossible on a free hit. A source record of one is a
# data problem, not a cricket event, so it is quarantined rather than modelled.
FREE_HIT_IMPOSSIBLE = frozenset(
    {"bowled", "lbw", "caught", "caught and bowled", "stumped", "hit wicket"}
)

DISMISSAL_GROUPS = {
    "bowled": "Bowled or LBW",
    "lbw": "Bowled or LBW",
    "hit wicket": "Hit wicket",
    "stumped": "Stumped",
    "caught": "Caught",
    "caught and bowled": "Caught and bowled",
    "run out": "Run-out",
}


def _clean(kind: object) -> str:
    """Lower-cased dismissal string, tolerating missing values from a dataframe."""
    if kind is None or not isinstance(kind, str):
        return ""
    return kind.strip().lower()


def dismissal_effect(kind: object) -> tuple[int, int, int]:
    """Team / batter / bowler consequence of one wicket entry.

    An unmapped kind returns the conservative reading — the side loses a wicket
    but no player is credited or charged — and callers are expected to raise a
    schema warning so the string can be mapped explicitly.
    """
    key = _clean(kind)
    if not key:
        return (0, 0, 0)
    return DISMISSALS.get(key, (1, 0, 0))


def is_mapped(kind: object) -> bool:
    key = _clean(kind)
    return bool(key) and key in DISMISSALS


def dismissal_group(kind: object) -> str:
    key = _clean(kind)
    if not key:
        return "Not out"
    return DISMISSAL_GROUPS.get(key, "Other/unallocated")


# The all-no-balls free hit arrived with the T20 playing conditions in 2015.
# Before that only a foot-fault earned one, and Cricsheet does not record the
# reason for a no-ball, so a derived flag in the earlier era is an approximation
# and every affected value carries `fh_approx`.
FREE_HIT_ALL_NOBALLS_FROM = "2015-01-01"


def free_hit_is_approximate(start_date: str | None) -> bool:
    if not start_date:
        return True
    return str(start_date)[:10] < FREE_HIT_ALL_NOBALLS_FROM


# Phase names for standard 20-over cricket. The resource state carries the
# precise timing; phase exists so a leaderboard can be read out loud.
def phase_for_over(over: int, powerplay_overs: int = 6, death_from: int = 15) -> str:
    if over < powerplay_overs:
        return "powerplay"
    if over < death_from:
        return "middle"
    return "death"
