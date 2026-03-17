from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse


# Dependency placeholder — overridden in app.py at startup to return DataStore
def _get_store():
    raise RuntimeError("DataStore not initialised")


router = APIRouter(prefix="/api", tags=["match_scorecards"])


def _load_scorecard_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load a single scorecard JSON file and return its dict, or None on error."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _sanitize_json_values(value: Any) -> Any:
    """Recursively convert non-JSON-safe float values (NaN/Inf) to None."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _sanitize_json_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_values(v) for v in value]
    return value


@router.get("/scorecards/available", response_model=List[str])
def list_available_scorecards(store=Depends(_get_store)):
    """
    List available match IDs for which scorecards exist.

    Returns a list of file names (match_id strings).
    """
    out = getattr(store, "output_dir", None)
    if out is None:
        raise HTTPException(status_code=503, detail="Data store not available")
    sc_dir = Path(out) / "scorecards"
    if not sc_dir.exists() or not sc_dir.is_dir():
        return []
    files = [p.stem for p in sorted(sc_dir.glob("*.json"))]
    return files


@router.get("/scorecards/search")
def search_scorecards(
    *,
    date_from: Optional[str] = Query(
        None, description="ISO date (inclusive) yyyy-mm-dd"
    ),
    date_to: Optional[str] = Query(None, description="ISO date (inclusive) yyyy-mm-dd"),
    team: Optional[str] = Query(
        None, description="Filter by team name (substring, case-insensitive)"
    ),
    player_id: Optional[str] = Query(
        None, description="Filter by player id (batter_id or bowler_id)"
    ),
    limit: int = Query(100, ge=1, le=1000),
    store=Depends(_get_store),
):
    """
    Search scorecards by date range, team, or player involvement.

    This is intentionally simple: it scans available scorecards on disk and
    performs lightweight filtering. For large datasets this could be optimized
    by building an index at startup (future work).
    """
    out = getattr(store, "output_dir", None)
    if out is None:
        raise HTTPException(status_code=503, detail="Data store not available")
    sc_dir = Path(out) / "scorecards"
    if not sc_dir.exists():
        return []

    # Collect results up to `limit`
    results: List[Dict[str, Any]] = []
    count = 0

    # Normalize filters
    team_l = team.lower() if team else None
    pid = str(player_id) if player_id is not None else None

    # Parse date range if provided
    from datetime import datetime

    def parse_date(s: Optional[str]):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s).date()
        except Exception:
            return None

    d_from = parse_date(date_from)
    d_to = parse_date(date_to)

    for path in sorted(sc_dir.glob("*.json")):
        if count >= limit:
            break
        sc = _load_scorecard_file(path)
        if sc is None:
            continue

        meta = sc.get("meta", {})
        # Date filter: meta.date may be a string or None
        ok = True
        if d_from or d_to:
            meta_date = meta.get("date")
            try:
                mdate = datetime.fromisoformat(meta_date).date() if meta_date else None
            except Exception:
                mdate = None
            if d_from and (mdate is None or mdate < d_from):
                ok = False
            if d_to and (mdate is None or mdate > d_to):
                ok = False
            if not ok:
                continue

        # Team filter
        if team_l:
            teams = meta.get("teams") or []
            # teams may be list of strings
            matched = False
            for t in teams:
                if t and team_l in t.lower():
                    matched = True
                    break
            if not matched:
                ok = False
            if not ok:
                continue

        # Player filter: look through innings batting and bowling lists
        if pid:
            involved = False
            for inn in sc.get("innings", {}).values():
                for bat in inn.get("batting", []):
                    if str(bat.get("batter_id")) == pid:
                        involved = True
                        break
                if involved:
                    break
                for bowl in inn.get("bowling", []):
                    if str(bowl.get("bowler_id")) == pid:
                        involved = True
                        break
                if involved:
                    break
            if not involved:
                continue

        # If passed all filters, append lightweight metadata for listing
        results.append(
            {
                "match_id": meta.get("match_id") or path.stem,
                "date": meta.get("date"),
                "venue": meta.get("venue"),
                "teams": meta.get("teams"),
                "innings_count": len(sc.get("innings", {})),
            }
        )
        count += 1

    return results


@router.get("/scorecards/{match_id}")
def get_scorecard(match_id: str, store=Depends(_get_store)):
    """
    Retrieve the full scorecard JSON for a single match_id.

    Returns 404 if the file does not exist or cannot be read.
    """
    out = getattr(store, "output_dir", None)
    if out is None:
        raise HTTPException(status_code=503, detail="Data store not available")
    sc_path = Path(out) / "scorecards" / f"{match_id}.json"
    if not sc_path.exists():
        raise HTTPException(status_code=404, detail=f"Scorecard not found: {match_id}")
    sc = _load_scorecard_file(sc_path)
    if sc is None:
        raise HTTPException(
            status_code=500, detail=f"Failed to read scorecard: {match_id}"
        )
    return JSONResponse(content=_sanitize_json_values(sc))


@router.get("/scorecards/player/{player_id}")
def player_scorecard_list(
    player_id: str,
    limit: int = Query(200, ge=1, le=2000),
    store=Depends(_get_store),
):
    """
    Return all per-match performances (batting and bowling) for a player based on scorecards.

    The response is a list of performance dicts including match meta and per-innings summary.
    """
    out = getattr(store, "output_dir", None)
    if out is None:
        raise HTTPException(status_code=503, detail="Data store not available")
    sc_dir = Path(out) / "scorecards"
    if not sc_dir.exists():
        return []

    performances: List[Dict[str, Any]] = []
    pid = str(player_id)

    for path in sorted(sc_dir.glob("*.json")):
        if len(performances) >= limit:
            break
        sc = _load_scorecard_file(path)
        if sc is None:
            continue
        meta = sc.get("meta", {})
        for inn_num, inn in sc.get("innings", {}).items():
            # batting
            for bat in inn.get("batting", []):
                if str(bat.get("batter_id")) == pid:
                    performances.append(
                        {
                            "match_id": meta.get("match_id") or path.stem,
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
                    )
            # bowling
            for bowl in inn.get("bowling", []):
                if str(bowl.get("bowler_id")) == pid:
                    performances.append(
                        {
                            "match_id": meta.get("match_id") or path.stem,
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
                    )
    # Sort performances: batting by runs desc, bowling by wickets desc, then date desc
    from datetime import datetime

    def _sort_key(p: Dict[str, Any]):
        d = p.get("date")
        try:
            dt = datetime.fromisoformat(d) if isinstance(d, str) else d
        except Exception:
            dt = None
        if p.get("role") == "batting":
            return (-(p.get("runs") or 0), dt or datetime.min)
        return (-(p.get("wickets") or 0), dt or datetime.min)

    performances_sorted = sorted(performances, key=_sort_key)
    return performances_sorted[:limit]
