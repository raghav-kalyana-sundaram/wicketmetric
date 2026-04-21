"""
T20 international team tiers from ``icc_ranking.ratings`` in the project ``config.yaml``.

Top ``t20i_main_team_count`` teams by ICC rating (descending) are *main*; remaining
listed teams are *associates*. Teams not in the table are treated as associates
for match filtering. IPL formats do not use this module in API handlers.

If ``config.yaml`` is missing (e.g. backend-only image), a built-in top-15 list is used
so filters still work.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent.parent

# When config.yaml is unavailable — matches repo ordering (ICC rating desc, Mar 2026).
_FALLBACK_MAIN_TEAMS: tuple[str, ...] = (
    "India",
    "England",
    "Australia",
    "New Zealand",
    "South Africa",
    "Pakistan",
    "West Indies",
    "Sri Lanka",
    "Afghanistan",
    "Bangladesh",
    "Zimbabwe",
    "Ireland",
    "Netherlands",
    "Scotland",
    "Namibia",
)


@functools.lru_cache(maxsize=1)
def _loaded_config() -> dict[str, Any]:
    if yaml is None:
        return {}
    path = _PROJECT_ROOT / "config.yaml"
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def get_t20i_tier_config() -> tuple[list[str], list[str], int]:
    """Return ``(main_teams, associate_teams, top_n)`` sorted by rating then name."""
    cfg = _loaded_config()
    icc = cfg.get("icc_ranking") if isinstance(cfg.get("icc_ranking"), dict) else {}
    ratings = icc.get("ratings")
    if not isinstance(ratings, dict) or not ratings:
        return list(_FALLBACK_MAIN_TEAMS), [], len(_FALLBACK_MAIN_TEAMS)

    top_n = icc.get("t20i_main_team_count", 15)
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        top_n = 15
    top_n = max(1, min(60, top_n))

    items: list[tuple[str, int]] = []
    for name, r in ratings.items():
        if name is None:
            continue
        try:
            rv = int(r)
        except (TypeError, ValueError):
            continue
        items.append((str(name), rv))

    items.sort(key=lambda x: (-x[1], x[0]))
    main = [n for n, _ in items[:top_n]]
    associates = [n for n, _ in items[top_n:]]
    return main, associates, top_n


@functools.lru_cache(maxsize=1)
def main_team_name_set() -> frozenset[str]:
    main, _, _ = get_t20i_tier_config()
    return frozenset(main)


def is_t20_international_format(fmt: str) -> bool:
    return str(fmt).lower() in ("mens_t20i", "womens_t20i")
