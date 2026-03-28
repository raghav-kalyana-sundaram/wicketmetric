"""
Per-match batting / bowling / combined impact from scorecard innings JSON.

Mirrors gui/frontend/src/lib/scorecardMatchImpact.ts (same thresholds and formulas).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

MIN_BALLS_BAT_IMPACT = 5
MIN_BALLS_BOWL_IMPACT = 6
# Wicket term is linear in wickets (historically was quadratic, which made +1–2
# wickets explode vs peers). Calibrated so a ~3w spell matches the old scale.
BOWL_SPELL_K = 18.0
RUNS_SAVED_K = 2.35


def _to_int(x: Any, default: int = 0) -> int:
    if x is None:
        return default
    try:
        return int(x)
    except (TypeError, ValueError):
        try:
            return int(float(x))
        except (TypeError, ValueError):
            return default


def _to_float(x: Any, default: float = 0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _pid(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _round_impact(x: float) -> float:
    return round(x * 100) / 100


def _bowling_impact_relative(
    wickets: int,
    runs_conceded: int,
    balls: int,
    match_totals: Dict[str, int],
) -> float:
    safe_runs = max(runs_conceded, 1)
    pool_runs = match_totals["total_runs"] - runs_conceded
    pool_balls = match_totals["total_balls"] - balls
    if pool_balls > 0:
        match_rpb = pool_runs / pool_balls
    elif match_totals["total_balls"] > 0:
        match_rpb = match_totals["total_runs"] / match_totals["total_balls"]
    else:
        match_rpb = 0.0
    expected_runs = match_rpb * balls
    runs_saved = expected_runs - runs_conceded
    if wickets > 0:
        spell_core = (BOWL_SPELL_K * wickets * balls) / safe_runs
        return spell_core + RUNS_SAVED_K * runs_saved
    return RUNS_SAVED_K * runs_saved


def _innings_sort_key(item: Tuple[str, Any]) -> Tuple[int, str]:
    k = item[0]
    try:
        return (int(k), k)
    except (TypeError, ValueError):
        return (0, str(k))


CombinedRow = Dict[str, Any]


def compute_match_impact_combined_rows(innings_map: Dict[str, Any]) -> List[CombinedRow]:
    """
    Aggregate all innings in the match and return combined impact rows (sorted by total desc).
    """
    bat_agg: Dict[str, Dict[str, Any]] = {}
    bowl_agg: Dict[str, Dict[str, Any]] = {}

    for _, inn in sorted(innings_map.items(), key=_innings_sort_key):
        if not isinstance(inn, dict):
            continue
        for b in inn.get("batting") or []:
            if not isinstance(b, dict):
                continue
            bid = _pid(b.get("batter_id"))
            if not bid:
                continue
            name = str(b.get("batter") or bid)
            runs = _to_int(b.get("runs"))
            balls = _to_int(b.get("balls"))
            cur = bat_agg.setdefault(bid, {"name": name, "runs": 0, "balls": 0})
            cur["name"] = name
            cur["runs"] += runs
            cur["balls"] += balls

        for bw in inn.get("bowling") or []:
            if not isinstance(bw, dict):
                continue
            oid = _pid(bw.get("bowler_id"))
            if not oid:
                continue
            name = str(bw.get("bowler") or oid)
            w = _to_int(bw.get("wickets"))
            r = _to_int(bw.get("runs_conceded"))
            balls = _to_int(bw.get("balls"))
            cur = bowl_agg.setdefault(
                oid, {"name": name, "wickets": 0, "runs_conceded": 0, "balls": 0}
            )
            cur["name"] = name
            cur["wickets"] += w
            cur["runs_conceded"] += r
            cur["balls"] += balls

    batting: List[Dict[str, Any]] = []
    for player_id, v in bat_agg.items():
        if v["balls"] < MIN_BALLS_BAT_IMPACT:
            continue
        balls = max(v["balls"], 1)
        sr = (v["runs"] / balls) * 100 if balls else None
        impact = (v["runs"] * v["runs"]) / balls
        batting.append(
            {
                "player_id": player_id,
                "name": v["name"],
                "runs": v["runs"],
                "balls": v["balls"],
                "strike_rate": round(sr * 100) / 100 if sr is not None else None,
                "impact": _round_impact(_to_float(impact)),
            }
        )
    batting.sort(key=lambda x: (-x["impact"], x["name"]))

    total_bowl_runs = sum(v["runs_conceded"] for v in bowl_agg.values())
    total_bowl_balls = sum(v["balls"] for v in bowl_agg.values())
    match_bowl_totals = {"total_runs": total_bowl_runs, "total_balls": total_bowl_balls}

    bowling: List[Dict[str, Any]] = []
    for player_id, v in bowl_agg.items():
        if v["balls"] < MIN_BALLS_BOWL_IMPACT:
            continue
        balls = max(v["balls"], 1)
        econ = round((v["runs_conceded"] * 600) / balls) / 100
        impact = _bowling_impact_relative(
            v["wickets"], v["runs_conceded"], v["balls"], match_bowl_totals
        )
        bowling.append(
            {
                "player_id": player_id,
                "name": v["name"],
                "wickets": v["wickets"],
                "runs_conceded": v["runs_conceded"],
                "balls": v["balls"],
                "economy": econ,
                "impact": _round_impact(impact),
            }
        )
    bowling.sort(key=lambda x: (-x["impact"], x["name"]))

    merged: Dict[str, CombinedRow] = {}
    for b in batting:
        pid = b["player_id"]
        merged[pid] = {
            "player_id": pid,
            "name": b["name"],
            "bat_impact": b["impact"],
            "bowl_impact": 0.0,
            "total_impact": b["impact"],
            "bat_runs": b["runs"],
            "bat_balls": b["balls"],
        }

    for bo in bowling:
        pid = bo["player_id"]
        if pid in merged:
            x = merged[pid]
            x["bowl_impact"] = bo["impact"]
            x["total_impact"] = _round_impact(x["bat_impact"] + bo["impact"])
            x["bowl_wickets"] = bo["wickets"]
            x["bowl_runs_conceded"] = bo["runs_conceded"]
            x["bowl_balls"] = bo["balls"]
        else:
            merged[pid] = {
                "player_id": pid,
                "name": bo["name"],
                "bat_impact": 0.0,
                "bowl_impact": bo["impact"],
                "total_impact": bo["impact"],
                "bowl_wickets": bo["wickets"],
                "bowl_runs_conceded": bo["runs_conceded"],
                "bowl_balls": bo["balls"],
            }

    rows = list(merged.values())
    rows.sort(key=lambda r: (-r["total_impact"], str(r.get("name") or "")))
    return rows


def combined_row_for_player(
    scorecard: Dict[str, Any], player_id: str
) -> Optional[CombinedRow]:
    """Return this player's combined impact row for the match, if they qualify."""
    pid = str(player_id).strip()
    if not pid:
        return None
    innings_map = scorecard.get("innings") or {}
    if not isinstance(innings_map, dict):
        return None
    for row in compute_match_impact_combined_rows(innings_map):
        if str(row.get("player_id")) == pid:
            return row
    return None
