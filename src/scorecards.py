"""
Scorecards module

Build per-match scorecards from the delivery-level DataFrame produced by the
parser. The intention is to provide an easy-to-inspect structure for every
match and every innings such that a player's individual score (e.g. 45 from
match X) can be inspected ball-by-ball to find the best/worst contributions
that led to that score.

Public functions
- build_scorecards(deliveries_df) -> dict[str, dict]
    Build scorecards keyed by `match_id`. Each scorecard contains per-innings
    batting and bowling summaries plus optional per-delivery lists for drill-down.

- player_performances_from_scorecards(scorecards, player_id) -> list[dict]
    Extract every match-level performance (batting and bowling) for a given player
    across all matches in the scorecards collection.

- scorecards_to_dataframe(scorecards) -> pandas.DataFrame
    Flatten batting performances across matches to a DataFrame useful for sorting
    and identifying best/worst performances.

Design notes
- The module uses the delivery columns produced by src.parser:
  Expected columns include (but not limited to):
    'match_id', 'date', 'innings_num', 'batting_team', 'bowling_team',
    'over', 'ball_idx', 'batter', 'batter_id', 'bowler', 'bowler_id',
    'batter_runs', 'total_runs', 'extras_runs', 'is_wide', 'is_noball',
    'is_batter_ball', 'is_wicket', 'wicket_kind', 'wicket_fielders',
    'player_out', 'player_out_id',
    'is_legal'
- Balls faced for batters counts deliveries where `is_batter_ball` is True.
  (Noballs are included as batter-faced deliveries because most scorecards
  count them when the batter hits the ball; wides are not faced by the batter.)
- Balls bowled is computed using the `is_legal` flag (legal deliveries only).
- Bowler wickets exclude run-outs and other non-bowler-attributed dismissal kinds.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Dismissal kinds that are typically not credited to the bowler
_NON_BOWLER_WICKET_KINDS = {
    "run out",
    "retired hurt",
    "obstructing the field",
    "handled the ball",
    "hit the ball twice",
}


def _wp_json_float(row: pd.Series, col: str) -> Any:
    """Round win-probability floats to 3 dp for JSON; None if missing/invalid."""
    if col not in row.index:
        return None
    v = row.get(col)
    if pd.isna(v):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, 3)


def _overs_from_balls(balls: int) -> str:
    """
    Represent balls as overs string 'O.B' where B = remaining legal balls (0-5).
    Example: 26 balls -> '4.2' (4 overs and 2 balls).
    """
    if balls < 0:
        return "0.0"
    overs = balls // 6
    rem = balls % 6
    return f"{overs}.{rem}"


def _safe_div(
    numer: float, denom: float, default: Optional[float] = None
) -> Optional[float]:
    try:
        if denom == 0:
            return default
        return numer / denom
    except Exception:
        return default


def _coerce_fielders_list(val: Any) -> Optional[List[str]]:
    """Normalise wicket fielder names from a DataFrame cell (list or ndarray)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        if hasattr(val, "tolist"):
            val = val.tolist()
    except Exception:
        return None
    if not isinstance(val, (list, tuple)):
        return None
    out = [str(x).strip() for x in val if x is not None and str(x).strip()]
    return out or None


def _build_batting_innings(
    df_inn: pd.DataFrame, include_deliveries: bool = True
) -> List[Dict[str, Any]]:
    """
    Build batting summary list for an innings.

    Returns a list of dicts, one per batter who batted in that innings.
    Each dict contains:
      - batter_id, batter (name)
      - runs, balls, fours, sixes
      - strike_rate
      - dismissal (kind), dismissal_player_id (who was out), dismissal_over/ball
      - batting_position (first appearance)
      - per_phase_runs: dict mapping phase->runs
      - deliveries: optional list of per-delivery dicts (for drill-down)
    """
    if df_inn.empty:
        return []

    # We'll group by batter_id + batter to aggregate
    id_cols = ["batter_id", "batter"]
    # Ensure consistent dtypes
    for c in id_cols:
        if c not in df_inn.columns:
            df_inn[c] = None

    batters: List[Dict[str, Any]] = []

    # Iterate per batter group
    grp = df_inn.groupby(["batter_id", "batter"], observed=True)
    for (batter_id, batter_name), g in grp:
        # Balls faced: deliveries where batter actually faced the ball (exclude wides)
        balls = (
            int(g["is_batter_ball"].sum()) if "is_batter_ball" in g.columns else len(g)
        )
        runs = int(g["batter_runs"].sum()) if "batter_runs" in g.columns else 0
        fours = int(g["is_four"].sum()) if "is_four" in g.columns else 0
        sixes = int(g["is_six"].sum()) if "is_six" in g.columns else 0
        sr = float(round((runs / balls * 100), 2)) if balls > 0 else None

        # batting position: minimum batting_position recorded (first appearance)
        batting_position = (
            int(g["batting_position"].min())
            if "batting_position" in g.columns
            else None
        )

        # Dismissal info: find the delivery where player_out_id == batter_id (if any)
        dismissal_row = None
        if "player_out_id" in g.columns:
            # There could be multiple entries for run-outs etc; prefer the earliest delivery
            outs = g[g["player_out_id"].notna() & (g["player_out_id"] == batter_id)]
            if not outs.empty:
                dismissal_row = outs.sort_values(["over", "ball_idx"]).iloc[0]

        dismissal_kind = None
        dismissal_player_out_id = None
        dismissal_over = None
        dismissal_ball_idx = None
        dismissal_bowler = None
        dismissal_bowler_id = None
        dismissal_fielders = None
        if dismissal_row is not None:
            dismissal_kind = dismissal_row.get("wicket_kind")
            dismissal_player_out_id = dismissal_row.get("player_out_id")
            dismissal_over = (
                int(dismissal_row.get("over")) if "over" in dismissal_row else None
            )
            dismissal_ball_idx = (
                int(dismissal_row.get("ball_idx"))
                if "ball_idx" in dismissal_row
                else None
            )
            _db = dismissal_row.get("bowler")
            dismissal_bowler = (
                None if _db is None or pd.isna(_db) else str(_db)
            )
            _dbid = dismissal_row.get("bowler_id")
            dismissal_bowler_id = (
                None if _dbid is None or pd.isna(_dbid) else str(_dbid)
            )
            dismissal_fielders = _coerce_fielders_list(
                dismissal_row.get("wicket_fielders")
            )

        # Per-phase runs (powerplay/middle/death)
        per_phase_runs = {}
        if "phase" in g.columns:
            per_phase_runs = (
                g.groupby("phase", observed=True)["batter_runs"].sum().to_dict()
            )
            # Convert numpy types to Python ints
            per_phase_runs = {str(k): int(v) for k, v in per_phase_runs.items()}

        entry: Dict[str, Any] = {
            "batter_id": batter_id,
            "batter": batter_name,
            "runs": runs,
            "balls": balls,
            "fours": fours,
            "sixes": sixes,
            "strike_rate": sr,
            "batting_position": batting_position,
            "dismissal_kind": dismissal_kind,
            "dismissal_player_out_id": dismissal_player_out_id,
            "dismissal_over": dismissal_over,
            "dismissal_ball_idx": dismissal_ball_idx,
            "dismissal_bowler": dismissal_bowler,
            "dismissal_bowler_id": dismissal_bowler_id,
            "dismissal_fielders": dismissal_fielders,
            "per_phase_runs": per_phase_runs,
        }

        # Optional per-delivery list for drilling down
        if include_deliveries:
            deliveries = []
            for _, row in g.sort_values(["over", "ball_idx"]).iterrows():
                deliveries.append(
                    {
                        "over": int(row.get("over")) if "over" in row else None,
                        "ball_idx": int(row.get("ball_idx"))
                        if "ball_idx" in row
                        else None,
                        "batter_runs": int(row.get("batter_runs"))
                        if "batter_runs" in row
                        else 0,
                        "total_runs": int(row.get("total_runs"))
                        if "total_runs" in row
                        else 0,
                        "extras_runs": int(row.get("extras_runs"))
                        if "extras_runs" in row
                        else 0,
                        "is_wide": bool(row.get("is_wide"))
                        if "is_wide" in row
                        else False,
                        "is_noball": bool(row.get("is_noball"))
                        if "is_noball" in row
                        else False,
                        "is_batter_ball": bool(row.get("is_batter_ball"))
                        if "is_batter_ball" in row
                        else True,
                        "is_wicket": bool(row.get("is_wicket"))
                        if "is_wicket" in row
                        else False,
                        "wicket_kind": row.get("wicket_kind"),
                        "player_out_id": row.get("player_out_id"),
                        "bowler_id": row.get("bowler_id"),
                        "bowler": row.get("bowler"),
                        "wicket_fielders": _coerce_fielders_list(
                            row.get("wicket_fielders")
                        ),
                        "phase": row.get("phase"),
                        "team_score_before": int(row.get("team_score_before"))
                        if "team_score_before" in row
                        else None,
                        "team_wickets_before": int(row.get("team_wickets_before"))
                        if "team_wickets_before" in row
                        else None,
                    }
                )
            entry["deliveries"] = deliveries

        batters.append(entry)

    # Sort batting list by batting position (if available) else by runs desc
    def _bat_sort_key(x: Dict[str, Any]) -> Tuple:
        pos = x.get("batting_position") or 999
        # we want starting bat order; within same position prefer higher runs
        return (pos, -x.get("runs", 0))

    batters_sorted = sorted(batters, key=_bat_sort_key)
    return batters_sorted


def _build_bowling_innings(
    df_inn: pd.DataFrame, include_deliveries: bool = True
) -> List[Dict[str, Any]]:
    """
    Build bowling summary list for an innings.

    Returns a list of dicts, one per bowler who bowled in that innings.
    Each dict contains:
      - bowler_id, bowler
      - balls, overs (string), runs_conceded, wickets, maidens
      - economy (runs per over)
      - per_over_runs: dict mapping over_number -> runs conceded in that over by bowler
      - deliveries: optional list of per-delivery dicts for drill-down
    """
    if df_inn.empty:
        return []

    bowlers: List[Dict[str, Any]] = []
    grp = df_inn.groupby(["bowler_id", "bowler"], observed=True)
    for (bowler_id, bowler_name), g in grp:
        # Balls bowled: count legal deliveries only
        if "is_legal" in g.columns:
            balls = int(g["is_legal"].sum())
        else:
            # Fallback: count deliveries that are not wides/noballs if columns missing
            if "is_wide" in g.columns and "is_noball" in g.columns:
                balls = int((~(g["is_wide"] | g["is_noball"])).sum())
            else:
                balls = len(g)

        # Runs conceded: total_runs associated with those deliveries (including extras)
        runs_conceded = int(g["total_runs"].sum()) if "total_runs" in g.columns else 0

        # Wickets credited to bowler: filter by is_wicket & wicket_kind not in non-bowler kinds
        wickets_mask = pd.Series([False] * len(g), index=g.index)
        if "is_wicket" in g.columns:
            wickets_mask = g["is_wicket"].fillna(False)
            if "wicket_kind" in g.columns:
                wickets_mask = wickets_mask & (
                    ~g["wicket_kind"].isin(_NON_BOWLER_WICKET_KINDS)
                )
        wickets = int(wickets_mask.sum())

        # Maidens: number of overs where bowler conceded zero total_runs
        per_over = {}
        if "over" in g.columns:
            per_over_runs = (
                g.groupby("over", observed=True)["total_runs"].sum().to_dict()
            )
            # convert numpy types to ints
            per_over = {int(k): int(v) for k, v in per_over_runs.items()}
            maidens = sum(1 for v in per_over.values() if v == 0)
        else:
            maidens = 0

        # Economy: runs per 6 legal balls
        econ = None
        if balls > 0:
            econ = round(runs_conceded * 6.0 / balls, 2)

        entry: Dict[str, Any] = {
            "bowler_id": bowler_id,
            "bowler": bowler_name,
            "balls": balls,
            "overs": _overs_from_balls(balls),
            "runs_conceded": runs_conceded,
            "wickets": wickets,
            "maidens": maidens,
            "economy": econ,
            "per_over_runs": per_over,
        }

        if include_deliveries:
            deliveries = []
            for _, row in g.sort_values(["over", "ball_idx"]).iterrows():
                dlv: Dict[str, Any] = {
                    "over": int(row.get("over")) if "over" in row else None,
                    "ball_idx": int(row.get("ball_idx"))
                    if "ball_idx" in row
                    else None,
                    "batter": row.get("batter"),
                    "batter_id": row.get("batter_id"),
                    "batter_runs": int(row.get("batter_runs"))
                    if "batter_runs" in row
                    else 0,
                    "total_runs": int(row.get("total_runs"))
                    if "total_runs" in row
                    else 0,
                    "is_wide": bool(row.get("is_wide"))
                    if "is_wide" in row
                    else False,
                    "is_noball": bool(row.get("is_noball"))
                    if "is_noball" in row
                    else False,
                    "is_legal": bool(row.get("is_legal"))
                    if "is_legal" in row
                    else True,
                    "is_wicket": bool(row.get("is_wicket"))
                    if "is_wicket" in row
                    else False,
                    "wicket_kind": row.get("wicket_kind"),
                    "player_out_id": row.get("player_out_id"),
                    "phase": row.get("phase"),
                }
                wb = _wp_json_float(row, "win_prob_before")
                wa = _wp_json_float(row, "win_prob_after")
                wpa_v = _wp_json_float(row, "wpa")
                if wb is not None:
                    dlv["win_prob_before"] = wb
                if wa is not None:
                    dlv["win_prob_after"] = wa
                if wpa_v is not None:
                    dlv["wpa"] = wpa_v
                deliveries.append(dlv)
            entry["deliveries"] = deliveries

        bowlers.append(entry)

    # Sort bowlers by balls bowled desc (primary) then wickets desc
    bowlers_sorted = sorted(
        bowlers, key=lambda x: (-x.get("balls", 0), -x.get("wickets", 0))
    )
    return bowlers_sorted


def build_scorecards(
    deliveries_df: pd.DataFrame, include_deliveries: bool = True
) -> Dict[str, Dict[str, Any]]:
    """
    Build scorecards for every match in `deliveries_df`.

    Parameters
    ----------
    deliveries_df : pd.DataFrame
        The delivery-level DataFrame produced by src.parser.parse_all_matches.
    include_deliveries : bool
        If True, attach per-batter and per-bowler delivery lists for drill-down.

    Returns
    -------
    dict mapping match_id -> scorecard dict.

    Scorecard format (top-level keys):
      - match_id, date, venue, event_name, teams (if available), winner
      - innings: mapping innings_num -> {
            'batting_team', 'bowling_team',
            'batting' : [list of batter dicts],
            'bowling' : [list of bowler dicts],
            'innings_total': int (final runs),
            'innings_wickets': int (final wickets),
        }
    """
    # Defensive copy
    df = deliveries_df.copy()
    if df.empty:
        return {}

    # Ensure expected columns exist to avoid KeyError
    required_cols = ["match_id", "innings_num"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"deliveries_df must contain column '{c}'")

    scorecards: Dict[str, Dict[str, Any]] = {}

    # Group by match_id and iterate
    for match_id, match_grp in df.groupby("match_id", observed=True):
        # Extract match-level metadata from the first row (if present)
        first_row = match_grp.iloc[0]
        om = first_row.get("outcome_method")
        dls_applied = False
        if isinstance(om, str) and om.strip():
            ol = om.lower().strip()
            dls_applied = (
                "d/l" in ol
                or "dls" in ol
                or "duckworth" in ol
                or ol == "dl"
            )
        try:
            olimit = first_row.get("overs_limit")
            overs_limit_meta = (
                int(olimit)
                if olimit is not None and not pd.isna(olimit)
                else 20
            )
        except (TypeError, ValueError):
            overs_limit_meta = 20

        match_meta = {
            "match_id": match_id,
            "date": first_row.get("date").to_pydatetime()
            if hasattr(first_row.get("date"), "to_pydatetime")
            else first_row.get("date"),
            "venue": first_row.get("venue"),
            "event_name": first_row.get("event_name"),
            "teams": list(match_grp["batting_team"].dropna().unique())
            if "batting_team" in match_grp.columns
            else None,
            "winner": first_row.get("winner") if "winner" in first_row else None,
            "toss_winner": first_row.get("toss_winner")
            if "toss_winner" in first_row
            else None,
            "toss_decision": first_row.get("toss_decision")
            if "toss_decision" in first_row
            else None,
            "dls_applied": dls_applied,
            "overs_limit": overs_limit_meta,
        }

        innings_map: Dict[int, Dict[str, Any]] = {}

        # For each innings in the match (1..n)
        for inn_num, inn_grp in match_grp.groupby("innings_num", observed=True):
            inn_grp_sorted = inn_grp.sort_values(["over", "ball_idx"])
            innings_info: Dict[str, Any] = {
                "innings_num": int(inn_num),
                "batting_team": inn_grp_sorted.iloc[0].get("batting_team")
                if "batting_team" in inn_grp_sorted.columns
                else None,
                "bowling_team": inn_grp_sorted.iloc[0].get("bowling_team")
                if "bowling_team" in inn_grp_sorted.columns
                else None,
            }

            # Innings totals: last cumulative state is in the last delivery row's team_score_before + that delivery's total_runs
            if "team_score_before" in inn_grp_sorted.columns:
                last_row = inn_grp_sorted.iloc[-1]
                innings_total = int(
                    last_row.get("team_score_before", 0) + last_row.get("total_runs", 0)
                )
                innings_wickets = int(
                    last_row.get("team_wickets_before", 0)
                    + (1 if last_row.get("is_wicket") else 0)
                )
            else:
                innings_total = (
                    int(inn_grp_sorted["total_runs"].sum())
                    if "total_runs" in inn_grp_sorted.columns
                    else 0
                )
                innings_wickets = (
                    int(inn_grp_sorted["is_wicket"].sum())
                    if "is_wicket" in inn_grp_sorted.columns
                    else 0
                )

            innings_info["innings_total"] = innings_total
            innings_info["innings_wickets"] = innings_wickets

            # Chasing target from Cricsheet (NaN in first innings) — used for pressure metrics in UI.
            target_runs_out: Optional[int] = None
            if "target_runs" in inn_grp_sorted.columns:
                tr_series = pd.to_numeric(
                    inn_grp_sorted["target_runs"], errors="coerce"
                ).dropna()
                if len(tr_series) > 0:
                    try:
                        trv = float(tr_series.iloc[0])
                        if trv > 0:
                            target_runs_out = int(round(trv))
                    except (TypeError, ValueError):
                        pass
            innings_info["target_runs"] = target_runs_out

            # Build batting and bowling lists
            batting = _build_batting_innings(
                inn_grp_sorted, include_deliveries=include_deliveries
            )
            bowling = _build_bowling_innings(
                inn_grp_sorted, include_deliveries=include_deliveries
            )

            innings_info["batting"] = batting
            innings_info["bowling"] = bowling

            innings_map[int(inn_num)] = innings_info

        scorecard = {
            "meta": match_meta,
            "innings": innings_map,
        }
        scorecards[str(match_id)] = scorecard

    return scorecards


def player_performances_from_scorecards(
    scorecards: Dict[str, Dict[str, Any]], player_id: str
) -> List[Dict[str, Any]]:
    """
    Extract match-level performances for `player_id` from scorecards.

    Each returned dict includes match meta and the player's batting and/or
    bowling performance for that match/innings. Useful to collect all
    performances for a player for sorting by runs/wickets/etc.

    Note: player_id must match the 'batter_id' / 'bowler_id' used in scorecards.
    """
    performances: List[Dict[str, Any]] = []
    for match_id, sc in scorecards.items():
        meta = sc.get("meta", {})
        for inn_num, inn in sc.get("innings", {}).items():
            # Check batting
            for bat in inn.get("batting", []):
                if bat.get("batter_id") == player_id:
                    perf = {
                        "match_id": match_id,
                        "date": meta.get("date"),
                        "venue": meta.get("venue"),
                        "innings_num": inn_num,
                        "role": "batting",
                        "team": inn.get("batting_team"),
                        "opposition": inn.get("bowling_team"),
                        "runs": bat.get("runs"),
                        "balls": bat.get("balls"),
                        "fours": bat.get("fours"),
                        "sixes": bat.get("sixes"),
                        "strike_rate": bat.get("strike_rate"),
                        "dismissal_kind": bat.get("dismissal_kind"),
                        "deliveries": bat.get("deliveries"),
                    }
                    performances.append(perf)
            # Check bowling
            for bowl in inn.get("bowling", []):
                if bowl.get("bowler_id") == player_id:
                    perf = {
                        "match_id": match_id,
                        "date": meta.get("date"),
                        "venue": meta.get("venue"),
                        "innings_num": inn_num,
                        "role": "bowling",
                        "team": inn.get("bowling_team"),
                        "opposition": inn.get("batting_team"),
                        "balls": bowl.get("balls"),
                        "overs": bowl.get("overs"),
                        "runs_conceded": bowl.get("runs_conceded"),
                        "wickets": bowl.get("wickets"),
                        "economy": bowl.get("economy"),
                        "deliveries": bowl.get("deliveries"),
                    }
                    performances.append(perf)

    # Sort: batting by runs desc, bowling by wickets desc, then date desc
    def _sort_key(p: Dict[str, Any]) -> Tuple:
        # We want to see high-impact performances first: batting by runs, bowling by wickets
        if p.get("role") == "batting":
            return (-(p.get("runs") or 0), p.get("date") or pd.NaT)
        else:
            return (-(p.get("wickets") or 0), p.get("date") or pd.NaT)

    performances_sorted = sorted(performances, key=_sort_key)
    return performances_sorted


def scorecards_to_dataframe(scorecards: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """
    Flatten batting performances from scorecards to a pandas DataFrame.

    Columns:
      - match_id, date, venue, innings_num, team, opposition,
      - batter_id, batter, runs, balls, fours, sixes, strike_rate, dismissal_kind

    Use this DataFrame to easily sort and find a player's best/worst innings.
    """
    rows: List[Dict[str, Any]] = []
    for match_id, sc in scorecards.items():
        meta = sc.get("meta", {})
        for inn_num, inn in sc.get("innings", {}).items():
            opposition = inn.get("bowling_team")
            team = inn.get("batting_team")
            for bat in inn.get("batting", []):
                rows.append(
                    {
                        "match_id": match_id,
                        "date": meta.get("date"),
                        "venue": meta.get("venue"),
                        "innings_num": inn_num,
                        "team": team,
                        "opposition": opposition,
                        "batter_id": bat.get("batter_id"),
                        "batter": bat.get("batter"),
                        "runs": bat.get("runs"),
                        "balls": bat.get("balls"),
                        "fours": bat.get("fours"),
                        "sixes": bat.get("sixes"),
                        "strike_rate": bat.get("strike_rate"),
                        "dismissal_kind": bat.get("dismissal_kind"),
                        "deliveries": bat.get("deliveries", None),  # optional
                    }
                )
    df = pd.DataFrame(rows)
    # Normalize types
    if not df.empty:
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        numeric_cols = ["runs", "balls", "fours", "sixes", "strike_rate"]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # -------------------------
        # Additional per-innings metrics (computed from deliveries when present)
        # - boundary_pct: fraction of scoring shots that are boundaries (4s or 6s)
        # - dot_balls: count of deliveries where batter faced the ball and scored 0
        # - boundary_runs: total runs from boundaries (4s*4 + 6s*6)
        # These are computed row-wise and are optional (only when `deliveries`
        # column exists and has per-delivery dicts). We fall back gracefully.
        # -------------------------
        def _compute_row_metrics(row):
            # Default values
            runs = row.get("runs", None)
            balls = row.get("balls", None)
            fours = row.get("fours", 0) or 0
            sixes = row.get("sixes", 0) or 0
            deliveries = row.get("deliveries", None)

            boundary_runs = (int(fours) * 4) + (int(sixes) * 6)
            boundary_pct = None
            dot_balls = None

            try:
                if balls and balls > 0:
                    boundary_pct = float(boundary_runs) / float(max(1, int(balls)))
                else:
                    boundary_pct = None
            except Exception:
                boundary_pct = None

            # If deliveries are available, compute accurate dot_balls
            if deliveries and isinstance(deliveries, (list, tuple)):
                try:
                    db = 0
                    for d in deliveries:
                        # We treat deliveries as dict-like
                        if (
                            d.get("is_batter_ball", True)
                            and int(d.get("batter_runs", 0)) == 0
                        ):
                            db += 1
                    dot_balls = int(db)
                except Exception:
                    dot_balls = None

            return pd.Series(
                {
                    "boundary_pct": boundary_pct,
                    "dot_balls": dot_balls,
                    "boundary_runs": boundary_runs,
                }
            )

        # Only attempt row-wise metrics when `deliveries` column exists
        if "deliveries" in df.columns:
            extra_metrics = df.apply(_compute_row_metrics, axis=1)
            df = pd.concat([df, extra_metrics], axis=1)
        else:
            # Still provide columns with None so downstream consumers have stable schema
            df["boundary_pct"] = None
            df["dot_balls"] = None
            df["boundary_runs"] = None

    return df


# ---------------------------------------------------------------------------
# Streaming / iterator helpers
# ---------------------------------------------------------------------------


def iter_scorecards(deliveries_df: pd.DataFrame, include_deliveries: bool = True):
    """
    Yield per-match scorecards as they are built, avoiding holding the
    entire set of scorecards in memory.

    Yields tuples (match_id, scorecard_dict) one-by-one for each match found
    in `deliveries_df`. This is intended for streaming writes or incremental
    processing in downstream consumers (e.g. GUI backend).
    """
    if deliveries_df is None or deliveries_df.empty:
        return

    # Group by match and yield a fresh scorecard for each group
    for match_id, mgroup in deliveries_df.groupby("match_id", observed=True):
        mg = mgroup.sort_values(["innings_num", "over", "ball_idx"]).reset_index(
            drop=True
        )
        match_scorecard: Dict[str, Any] = {}

        # Minimal match meta (keep keys aligned with build_scorecards)
        first_row = mg.iloc[0]
        om = first_row.get("outcome_method")
        dls_applied = False
        if isinstance(om, str) and om.strip():
            ol = om.lower().strip()
            dls_applied = (
                "d/l" in ol
                or "dls" in ol
                or "duckworth" in ol
                or ol == "dl"
            )
        try:
            olimit = first_row.get("overs_limit")
            overs_limit_meta = (
                int(olimit)
                if olimit is not None and not pd.isna(olimit)
                else 20
            )
        except (TypeError, ValueError):
            overs_limit_meta = 20

        match_info = {
            "match_id": str(match_id),
            "date": first_row.get("date") if "date" in first_row else None,
            "venue": first_row.get("venue") if "venue" in first_row else None,
            "event_name": first_row.get("event_name")
            if "event_name" in first_row
            else None,
            "teams": list(mg["batting_team"].dropna().unique())
            if "batting_team" in mg.columns
            else [],
            "winner": first_row.get("winner") if "winner" in first_row else None,
            "toss_winner": first_row.get("toss_winner")
            if "toss_winner" in first_row
            else None,
            "toss_decision": first_row.get("toss_decision")
            if "toss_decision" in first_row
            else None,
            "dls_applied": dls_applied,
            "overs_limit": overs_limit_meta,
        }
        match_scorecard["meta"] = match_info

        innings_list = {}
        for inn_num, inn_df in mg.groupby("innings_num", observed=True):
            inn = inn_df.sort_values(["over", "ball_idx"]).reset_index(drop=True)
            batting = _build_batting_innings(inn, include_deliveries=include_deliveries)
            bowling = _build_bowling_innings(inn, include_deliveries=include_deliveries)

            # compute innings totals defensively
            try:
                last_row = inn.iloc[-1]
                innings_total = int(
                    last_row.get("team_score_before", 0) + last_row.get("total_runs", 0)
                )
                innings_wickets = int(
                    last_row.get("team_wickets_before", 0)
                    + (1 if last_row.get("is_wicket") else 0)
                )
            except Exception:
                innings_total = (
                    int(inn["total_runs"].sum()) if "total_runs" in inn.columns else 0
                )
                innings_wickets = (
                    int(inn["is_wicket"].sum()) if "is_wicket" in inn.columns else 0
                )

            innings_list[int(inn_num)] = {
                "innings_num": int(inn_num),
                "batting_team": inn.iloc[0].get("batting_team")
                if "batting_team" in inn.columns
                else None,
                "bowling_team": inn.iloc[0].get("bowling_team")
                if "bowling_team" in inn.columns
                else None,
                "batting": batting,
                "bowling": bowling,
                "innings_total": innings_total,
                "innings_wickets": innings_wickets,
            }

        match_scorecard["innings"] = innings_list
        yield str(match_id), match_scorecard


def stream_write_scorecards(
    deliveries_df: pd.DataFrame,
    out_dir: str | Path,
    include_deliveries: bool = True,
    indent: int = 2,
):
    """
    Build and write per-match scorecards to disk incrementally.

    - Iterates `iter_scorecards()` to avoid building all scorecards in memory.
    - Writes one JSON file per match in `out_dir` named `<match_id>.json`.
    - Uses a safe write pattern (write to temporary file then atomically replace).
    """
    from pathlib import Path as _Path

    out_path = _Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    for match_id, sc in iter_scorecards(
        deliveries_df, include_deliveries=include_deliveries
    ):
        target = out_path / f"{match_id}.json"
        tmp = out_path / f".{match_id}.json.tmp"
        try:
            # Use orjson if available for compact deterministic dumps; fallback to pd.Series -> json
            try:
                import orjson

                b = orjson.dumps(
                    sc, option=orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY
                )
                tmp.write_bytes(b)
            except Exception:
                # Fallback: safe JSON serialization using json with a default handler
                # that converts numpy / pandas types into native Python types so the
                # produced JSON is valid and portable.
                def _json_fallback(o):
                    # numpy scalar -> native
                    try:
                        if isinstance(o, (np.integer, np.int_)):
                            return int(o)
                        if isinstance(o, (np.floating, np.float_)):
                            return float(o)
                        if isinstance(o, np.ndarray):
                            return o.tolist()
                    except Exception:
                        pass
                    # pandas / numpy NaN handling
                    try:
                        if pd.isna(o):
                            return None
                    except Exception:
                        pass
                    # pandas Timestamp / datetime
                    try:
                        import datetime

                        if isinstance(o, datetime.datetime):
                            return o.isoformat()
                        if isinstance(o, pd.Timestamp):
                            return o.isoformat()
                    except Exception:
                        pass
                    # Fallback to string representation
                    try:
                        return str(o)
                    except Exception:
                        return None

                try:
                    # Ensure non-ASCII characters preserved; indent for readability
                    s = json.dumps(
                        sc, default=_json_fallback, ensure_ascii=False, indent=indent
                    )
                    tmp.write_text(s, encoding="utf-8")
                except Exception:
                    # If fallback write fails, ensure temp file removed and re-raise
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except Exception:
                        pass
                    raise
            # Atomic move
            tmp.replace(target)
        except Exception as exc:
            # On failure, attempt to remove tmp and continue
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            # Log to stdout for visibility; GUI backend will capture this in logs
            print(f"[WARN] Failed to write scorecard {match_id}: {exc}")
