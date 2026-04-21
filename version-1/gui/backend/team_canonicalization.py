"""
Canonical team names — merge known franchise renames and a few international synonyms.

Franchise (IPL / WPL): same BCCI lineage or official rebrand (e.g. Daredevils → Capitals).
We deliberately do NOT merge different franchises that only shared a city (e.g. Deccan
Chargers vs Sunrisers Hyderabad).

International (T20I): only long-form vs abbreviation style variants for the same side;
never merge distinct countries (e.g. England vs Scotland).
"""

from __future__ import annotations

from typing import Any, Iterable

from t20i_team_tiers import is_t20_international_format

# (preferred display name, lowercase aliases including the display name lowercased)
_FRANCHISE_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "Delhi Capitals",
        frozenset(
            {
                "delhi capitals",
                "delhi daredevils",
            }
        ),
    ),
    (
        "Punjab Kings",
        frozenset(
            {
                "punjab kings",
                "kings xi punjab",
            }
        ),
    ),
    (
        "Royal Challengers Bengaluru",
        frozenset(
            {
                "royal challengers bengaluru",
                "royal challengers bangalore",
            }
        ),
    ),
    (
        "Rising Pune Supergiant",
        frozenset(
            {
                "rising pune supergiant",
                "rising pune supergiants",
            }
        ),
    ),
)

_INTL_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "United States of America",
        frozenset(
            {
                "united states of america",
                "united states",
                "usa",
                "u.s.a.",
            }
        ),
    ),
    (
        "United Arab Emirates",
        frozenset(
            {
                "united arab emirates",
                "uae",
            }
        ),
    ),
    (
        "Netherlands",
        frozenset(
            {
                "netherlands",
                "the netherlands",
                "holland",
            }
        ),
    ),
    (
        "Papua New Guinea",
        frozenset(
            {
                "papua new guinea",
                "png",
            }
        ),
    ),
    (
        "Czech Republic",
        frozenset(
            {
                "czech republic",
                "czechia",
            }
        ),
    ),
    (
        "Türkiye",
        frozenset(
            {
                "türkiye",
                "turkey",
            }
        ),
    ),
)


def _norm_key(name: str) -> str:
    return str(name or "").strip().lower()


def _groups_for_fmt(fmt: str) -> tuple[tuple[str, frozenset[str]], ...]:
    f = str(fmt).lower().strip()
    if f in ("mens_ipl", "womens_ipl"):
        return _FRANCHISE_GROUPS
    if is_t20_international_format(f):
        return _INTL_GROUPS
    return tuple()


def canonical_display(name: str, fmt: str) -> str:
    """Return the preferred display string for this team's equivalence class."""
    raw = str(name or "").strip()
    if not raw:
        return raw
    k = _norm_key(raw)
    for canon, aliases in _groups_for_fmt(fmt):
        if k in aliases or k == _norm_key(canon):
            return canon
    return raw


def variant_keys_lower_for_canonical(canonical_display: str, fmt: str) -> frozenset[str]:
    """All lowercase keys that should map to this canonical side (for SQL IN lists)."""
    c = str(canonical_display or "").strip()
    if not c:
        return frozenset()
    ck = _norm_key(c)
    for canon, aliases in _groups_for_fmt(fmt):
        if ck == _norm_key(canon) or ck in aliases:
            out = set(aliases)
            out.add(_norm_key(canon))
            return frozenset(out)
    return frozenset({ck})


def variant_keys_lower_for_any_name(name: str, fmt: str) -> list[str]:
    """Expand a chip label or URL team param to all DB string forms (lowercase)."""
    canon = canonical_display(name, fmt)
    return sorted(variant_keys_lower_for_canonical(canon, fmt))


def canonicalize_rows_by_team(
    rows: Iterable[dict[str, Any]],
    *,
    team_col: str,
    fmt: str,
    merge_numeric: tuple[str, ...] = ("matches", "wins", "losses"),
    avg_runs_col: str | None = "avg_innings_runs",
) -> list[dict[str, Any]]:
    """Merge leaderboard-style rows that share the same canonical team name."""
    merged: dict[str, dict[str, Any]] = {}
    acc_key = "_w_avg_num"
    acc_m_key = "_w_avg_den"
    for r in rows:
        raw_team = str(r.get(team_col) or "").strip()
        c = canonical_display(raw_team, fmt)
        if c not in merged:
            nr = dict(r)
            nr[team_col] = c
            nr[acc_key] = 0.0
            nr[acc_m_key] = 0
            mi0 = int(nr.get("matches") or 0)
            ar0 = nr.get(avg_runs_col) if avg_runs_col else None
            if avg_runs_col and mi0 > 0 and ar0 is not None:
                try:
                    nr[acc_key] = float(ar0) * mi0
                    nr[acc_m_key] = mi0
                except (TypeError, ValueError):
                    pass
            merged[c] = nr
            continue
        m = merged[c]
        for col in merge_numeric:
            m[col] = int(m.get(col) or 0) + int(r.get(col) or 0)
        if avg_runs_col and avg_runs_col in r:
            mi = int(r.get("matches") or 0)
            ar = r.get(avg_runs_col)
            if mi > 0 and ar is not None:
                try:
                    af = float(ar)
                except (TypeError, ValueError):
                    af = 0.0
                m[acc_key] = float(m.get(acc_key) or 0.0) + af * mi
                m[acc_m_key] = int(m.get(acc_m_key) or 0) + mi
    out: list[dict[str, Any]] = []
    for m in merged.values():
        den = int(m.pop(acc_m_key, 0) or 0)
        num = float(m.pop(acc_key, 0.0) or 0.0)
        if avg_runs_col and den > 0:
            m[avg_runs_col] = round(num / den, 4)
        elif avg_runs_col:
            m[avg_runs_col] = None
        mt = int(m.get("matches") or 0)
        w = int(m.get("wins") or 0)
        if mt > 0:
            m["win_pct"] = round(w * 100.0 / mt, 4)
        else:
            m["win_pct"] = None
        out.append(m)
    return out
