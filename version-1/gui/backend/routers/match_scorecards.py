from __future__ import annotations

import json
import math
import os
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from db import (
    DEFAULT_FORMAT,
    DB_PATH,
    VALID_FORMATS,
    query_one,
    safe_fmt,
)
from schemas import (
    LatestScorecardSummary,
    MatchImpactPerformanceRow,
    MatchImpactPerformancesResponse,
)
from team_canonicalization import canonical_display
from t20i_team_tiers import is_t20_international_format, main_team_name_set


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


router = APIRouter(prefix="/api", tags=["match_scorecards"])

_FORMAT_QUERY_PATTERN = "^(" + "|".join(VALID_FORMATS) + ")$"
_MATCH_TIER_PATTERN = r"^(all|main_only|associate_fixture)$"


# ── Scorecards directory resolution ──────────────────────────────
# SCORECARDS_DIR can be an explicit base path.  Within it we expect
# per-format subdirectories: {base}/{fmt}/scorecards/*.json
# Fallback: derive from the DuckDB file's parent directory.

_SCORECARDS_BASE: str = os.environ.get("SCORECARDS_DIR", "")


def _default_scorecards_base() -> Path:
    """
    Parent of per-format dirs, each containing ``scorecards/*.json``.

    Pipeline layout: ``<repo>/data/output/<format>/scorecards/``.
    When ``DUCKDB_PATH`` is ``.../data/cricket.duckdb``, ``DB_PATH.parent`` is
    ``.../data`` — we must use ``.../data/output``, not ``.../data/<format>``.
    """
    parent = DB_PATH.resolve().parent
    output = parent / "output"
    for f in VALID_FORMATS:
        if (output / f / "scorecards").is_dir():
            return output
    return parent


def _scorecards_dir_for_fmt(fmt: str) -> Path:
    """Resolve the scorecards directory for a given format."""
    base = Path(_SCORECARDS_BASE) if _SCORECARDS_BASE.strip() else _default_scorecards_base()
    return base / fmt / "scorecards"


# ── JSON file helpers ────────────────────────────────────────────


def _load_scorecard_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _normalize_meta_teams(raw: Any) -> Optional[List[str]]:
    if not isinstance(raw, list):
        return None
    out = [str(x).strip() for x in raw if x is not None and str(x).strip()]
    return out or None


def _teams_from_scorecard(sc: Dict[str, Any]) -> Optional[List[str]]:
    """Team short names for display: prefer meta.teams; derive from innings if missing."""
    meta = sc.get("meta") or {}
    meta_teams = _normalize_meta_teams(meta.get("teams"))
    if meta_teams and len(meta_teams) >= 2:
        return meta_teams

    innings_map = sc.get("innings") or {}
    if not isinstance(innings_map, dict):
        return meta_teams

    def _inn_sort_key(key: Any) -> int:
        try:
            return int(key)
        except (TypeError, ValueError):
            return 0

    seen: List[str] = []
    for k in sorted(innings_map.keys(), key=_inn_sort_key):
        inn = innings_map[k]
        if not isinstance(inn, dict):
            continue
        for fld in ("batting_team", "bowling_team"):
            v = inn.get(fld)
            if v is None:
                continue
            s = str(v).strip()
            if s and s not in seen:
                seen.append(s)
    if len(seen) >= 2:
        return seen[:2]
    return meta_teams


def _parse_meta_date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    try:
        if isinstance(raw, datetime):
            return raw.date()
        s = str(raw).strip()
        if not s:
            return None
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None


# ── Latest scorecard helpers ─────────────────────────────────────


@lru_cache(maxsize=32)
def _cached_latest_scorecard(sc_dir_resolved: str) -> Optional[Dict[str, Any]]:
    """Scan all scorecard JSONs once per directory path (process lifetime)."""
    root = Path(sc_dir_resolved)
    if not root.is_dir():
        return None
    best_d: Optional[date] = None
    best_meta: Optional[Dict[str, Any]] = None
    best_path: Optional[Path] = None
    for path in root.glob("*.json"):
        sc = _load_scorecard_file(path)
        if sc is None:
            continue
        meta = sc.get("meta") or {}
        d = _parse_meta_date(meta.get("date"))
        if d is None:
            continue
        if best_d is None or d > best_d:
            best_d = d
            best_meta = meta
            best_path = path
    if best_meta is None or best_path is None:
        return None
    raw_teams = best_meta.get("teams")
    teams: Optional[List[str]] = None
    if isinstance(raw_teams, list):
        teams = [str(x) for x in raw_teams if x is not None and str(x).strip()]
        if not teams:
            teams = None
    return {
        "match_id": str(best_meta.get("match_id") or best_path.stem),
        "date": best_meta.get("date"),
        "venue": best_meta.get("venue"),
        "teams": teams,
        "event_name": best_meta.get("event_name"),
    }


def compute_latest_scorecard_summary_db(
    conn: duckdb.DuckDBPyConnection, fmt: str
) -> Optional[Dict[str, Any]]:
    """Newest scorecard for *fmt*, preferring the JSON scan but falling back to DuckDB."""
    f = safe_fmt(fmt)
    sc_dir = _scorecards_dir_for_fmt(f)

    # Fast path: scan JSON files on disk (cached per directory)
    if sc_dir.is_dir():
        result = _cached_latest_scorecard(str(sc_dir.resolve()))
        if result is not None:
            return result

    # Fallback: find most recent match_id from DuckDB bat_innings
    try:
        row = query_one(
            conn,
            f"""
            SELECT match_id, MAX(date) AS date
            FROM {f}.bat_innings
            WHERE date IS NOT NULL
            GROUP BY match_id
            ORDER BY date DESC
            LIMIT 1
            """,
        )
    except duckdb.CatalogException:
        return None

    if row is None:
        return None

    match_id = str(row["match_id"])
    match_date = row.get("date")

    # Try to load the scorecard JSON for richer metadata
    sc_path = sc_dir / f"{match_id}.json"
    if sc_path.is_file():
        sc = _load_scorecard_file(sc_path)
        if sc is not None:
            meta = sc.get("meta") or {}
            raw_teams = meta.get("teams")
            teams: Optional[List[str]] = None
            if isinstance(raw_teams, list):
                teams = [str(x) for x in raw_teams if x is not None and str(x).strip()]
                if not teams:
                    teams = None
            return {
                "match_id": str(meta.get("match_id") or match_id),
                "date": meta.get("date") or str(match_date)[:10] if match_date else None,
                "venue": meta.get("venue"),
                "teams": teams,
                "event_name": meta.get("event_name"),
            }

    return {
        "match_id": match_id,
        "date": str(match_date)[:10] if match_date else None,
        "venue": None,
        "teams": None,
        "event_name": None,
    }


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


# ── Scorecards directory accessor for endpoints ──────────────────


def _get_sc_dir(store_tuple: Any) -> tuple[duckdb.DuckDBPyConnection, str, Path]:
    """Unpack the (conn, fmt) dependency and resolve scorecards path."""
    conn, fmt = store_tuple
    f = safe_fmt(fmt)
    return conn, f, _scorecards_dir_for_fmt(f)


# ── Routes ───────────────────────────────────────────────────────


@router.get("/scorecards/available", response_model=List[str])
def list_available_scorecards(store=Depends(_get_store)):
    """List available match IDs for which scorecards exist."""
    _, _, sc_dir = _get_sc_dir(store)
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
    match_tier: str = Query(
        "all",
        description=(
            "T20I only (ignored for IPL). "
            "all | main_only (both teams in top ICC tier from config) | "
            "associate_fixture (at least one associate / unlisted side)"
        ),
        pattern=_MATCH_TIER_PATTERN,
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice; selects T20I vs IPL.",
        pattern=_FORMAT_QUERY_PATTERN,
    ),
    limit: int = Query(100, ge=1, le=1000),
    store=Depends(_get_store),
):
    """Search scorecards by date range, team, or player involvement."""
    _, _, sc_dir = _get_sc_dir(store)
    if not sc_dir.exists():
        return []

    results: List[Dict[str, Any]] = []

    team_l = team.lower() if team else None
    pid = str(player_id) if player_id is not None else None

    def parse_date(s: Optional[str]):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s).date()
        except Exception:
            return None

    d_from = parse_date(date_from)
    d_to = parse_date(date_to)
    eff_tier = _effective_match_tier(format, match_tier)
    main_set = main_team_name_set() if eff_tier != "all" else frozenset()

    for path in sc_dir.glob("*.json"):
        sc = _load_scorecard_file(path)
        if sc is None:
            continue

        meta = sc.get("meta", {})
        ok = True
        if d_from or d_to:
            mdate = _parse_meta_date(meta.get("date"))
            if d_from and (mdate is None or mdate < d_from):
                ok = False
            if d_to and (mdate is None or mdate > d_to):
                ok = False
            if not ok:
                continue

        if eff_tier != "all" and not _scorecard_passes_match_tier(
            sc, tier=eff_tier, main_names=main_set
        ):
            continue

        if team_l:
            teams = meta.get("teams") or []
            matched = False
            for t in teams:
                if t and team_l in t.lower():
                    matched = True
                    break
            if not matched:
                ok = False
            if not ok:
                continue

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

        results.append(
            {
                "match_id": meta.get("match_id") or path.stem,
                "date": meta.get("date"),
                "venue": meta.get("venue"),
                "teams": meta.get("teams"),
                "event_name": meta.get("event_name"),
                "innings_count": len(sc.get("innings", {})),
            }
        )

    def _row_sort_date(row: Dict[str, Any]) -> date:
        parsed = _parse_meta_date(row.get("date"))
        return parsed if parsed is not None else date.min

    results.sort(key=_row_sort_date, reverse=True)
    return results[:limit]


def _scorecard_passes_team_filter(
    sc: Dict[str, Any],
    team_l: Optional[str],
    *,
    team_raw: Optional[str] = None,
    format_key: Optional[str] = None,
) -> bool:
    if not team_l:
        return True
    fmt = safe_fmt(format_key) if format_key else ""

    def _side_matches(side: Any) -> bool:
        if not side:
            return False
        s = str(side)
        if team_l in s.lower():
            return True
        if team_raw and fmt:
            if canonical_display(s, fmt).lower() == canonical_display(team_raw, fmt).lower():
                return True
        return False

    meta = sc.get("meta") or {}
    for t in meta.get("teams") or []:
        if _side_matches(t):
            return True
    for inn in (sc.get("innings") or {}).values():
        if not isinstance(inn, dict):
            continue
        for k in ("batting_team", "bowling_team"):
            v = inn.get(k)
            if _side_matches(v):
                return True
    return False


def _scorecard_passes_match_tier(
    sc: Dict[str, Any],
    *,
    tier: str,
    main_names: frozenset[str],
) -> bool:
    """T20I ICC-tier filter using both sides from scorecard meta / innings."""
    t = (tier or "all").strip().lower()
    if t == "all":
        return True
    sides = _teams_from_scorecard(sc) or []
    if len(sides) < 2:
        return False
    a, b = sides[0], sides[1]
    in_main = a in main_names and b in main_names
    has_assoc = a not in main_names or b not in main_names
    if t == "main_only":
        return in_main
    if t == "associate_fixture":
        return has_assoc
    return True


def _effective_match_tier(format_key: str, match_tier: Optional[str]) -> str:
    if not is_t20_international_format(format_key):
        return "all"
    mt = (match_tier or "all").strip().lower()
    return mt if mt in ("main_only", "associate_fixture") else "all"


def _scorecard_passes_event_filter(sc: Dict[str, Any], event_l: Optional[str]) -> bool:
    if not event_l:
        return True
    meta = sc.get("meta") or {}
    ev = meta.get("event_name")
    return bool(ev and event_l in str(ev).lower())


@router.get(
    "/scorecards/performances/by-impact",
    response_model=MatchImpactPerformancesResponse,
)
def list_impact_performances(
    *,
    date_from: Optional[str] = Query(
        None, description="ISO date (inclusive) yyyy-mm-dd"
    ),
    date_to: Optional[str] = Query(None, description="ISO date (inclusive) yyyy-mm-dd"),
    team: Optional[str] = Query(
        None, description="Team name substring (meta or innings teams, case-insensitive)"
    ),
    event: Optional[str] = Query(
        None, description="Event / series name substring (case-insensitive)"
    ),
    player_id: Optional[str] = Query(
        None, description="Restrict to this player id (batter_id / bowler_id)"
    ),
    match_tier: str = Query(
        "all",
        description=(
            "T20I only (ignored for IPL). "
            "all | main_only | associate_fixture — same as /scorecards/search"
        ),
        pattern=_MATCH_TIER_PATTERN,
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice; selects T20I vs IPL.",
        pattern=_FORMAT_QUERY_PATTERN,
    ),
    discipline: str = Query(
        "combined",
        description="combined (bat+bowl), bat (batting impact only), bowl (bowling only)",
    ),
    order: str = Query("desc", description="Sort direction: asc or desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    store=Depends(_get_store),
):
    """All qualifying match-impact performances across scorecards, filterable and paginated."""
    from match_impact import compute_match_impact_combined_rows

    disc = (discipline or "combined").strip().lower()
    if disc not in ("combined", "bat", "bowl"):
        raise HTTPException(
            status_code=400,
            detail="discipline must be one of: combined, bat, bowl",
        )
    ord_l = (order or "desc").strip().lower()
    if ord_l not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="order must be asc or desc")

    _, _, sc_dir = _get_sc_dir(store)
    if not sc_dir.exists():
        return MatchImpactPerformancesResponse()

    team_st = (team or "").strip()
    team_l = team_st.lower() if team_st else None
    event_l = event.lower() if event else None
    pid_filter = str(player_id).strip() if player_id is not None else None

    def parse_date(s: Optional[str]) -> Optional[date]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s).date()
        except Exception:
            return None

    d_from = parse_date(date_from)
    d_to = parse_date(date_to)
    eff_tier = _effective_match_tier(format, match_tier)
    main_set = main_team_name_set() if eff_tier != "all" else frozenset()

    collected: List[Dict[str, Any]] = []

    for path in sc_dir.glob("*.json"):
        sc = _load_scorecard_file(path)
        if sc is None:
            continue

        meta = sc.get("meta") or {}
        mdate = _parse_meta_date(meta.get("date"))
        if d_from and (mdate is None or mdate < d_from):
            continue
        if d_to and (mdate is None or mdate > d_to):
            continue
        if eff_tier != "all" and not _scorecard_passes_match_tier(
            sc, tier=eff_tier, main_names=main_set
        ):
            continue
        if not _scorecard_passes_team_filter(
            sc,
            team_l,
            team_raw=team_st or None,
            format_key=format,
        ):
            continue
        if not _scorecard_passes_event_filter(sc, event_l):
            continue

        for prow in compute_match_impact_combined_rows(sc.get("innings") or {}):
            plid = str(prow.get("player_id") or "")
            if pid_filter and plid != pid_filter:
                continue
            bi = float(prow.get("bat_impact") or 0)
            boi = float(prow.get("bowl_impact") or 0)
            if disc == "bat" and bi <= 0:
                continue
            if disc == "bowl" and boi <= 0:
                continue

            teams_out = _teams_from_scorecard(sc)

            collected.append(
                {
                    "match_id": str(meta.get("match_id") or path.stem),
                    "date": meta.get("date"),
                    "venue": meta.get("venue"),
                    "event_name": meta.get("event_name"),
                    "teams": teams_out,
                    "player_id": plid,
                    "player_name": str(prow.get("name") or plid),
                    "total_impact": float(prow.get("total_impact") or 0),
                    "bat_impact": bi,
                    "bowl_impact": boi,
                    "bat_runs": prow.get("bat_runs"),
                    "bat_balls": prow.get("bat_balls"),
                    "bowl_wickets": prow.get("bowl_wickets"),
                    "bowl_runs_conceded": prow.get("bowl_runs_conceded"),
                    "bowl_balls": prow.get("bowl_balls"),
                    "_d_ord": mdate.toordinal() if mdate is not None else -1,
                }
            )

    if disc == "bat":
        sk = "bat_impact"
    elif disc == "bowl":
        sk = "bowl_impact"
    else:
        sk = "total_impact"

    reverse = ord_l == "desc"

    def _sort_tuple(row: Dict[str, Any]) -> tuple:
        v = float(row.get(sk) or 0)
        d_ord = int(row.get("_d_ord") or -1)
        mid = str(row.get("match_id") or "")
        pl = str(row.get("player_id") or "")
        if reverse:
            return (-v, -d_ord, mid, pl)
        return (v, d_ord, mid, pl)

    collected.sort(key=_sort_tuple)

    total = len(collected)
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    page_adj = min(page, total_pages)
    start = (page_adj - 1) * per_page
    slice_rows = collected[start : start + per_page]

    _perf_keys = (
        "match_id",
        "date",
        "venue",
        "event_name",
        "teams",
        "player_id",
        "player_name",
        "total_impact",
        "bat_impact",
        "bowl_impact",
        "bat_runs",
        "bat_balls",
        "bowl_wickets",
        "bowl_runs_conceded",
        "bowl_balls",
    )
    performances = [
        MatchImpactPerformanceRow(**{k: r[k] for k in _perf_keys}) for r in slice_rows
    ]

    return MatchImpactPerformancesResponse(
        performances=performances,
        total=total,
        page=page_adj,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/scorecards/latest", response_model=LatestScorecardSummary)
def get_latest_scorecard(store=Depends(_get_store)):
    """Newest match in ``scorecards/`` by ``meta.date`` (full scan; cached per dir)."""
    conn, fmt = store
    raw = compute_latest_scorecard_summary_db(conn, fmt)
    if not raw:
        raise HTTPException(status_code=404, detail="No scorecards available")
    return LatestScorecardSummary(**raw)


# Static path segments must be registered before ``/scorecards/{match_id}`` so
# ``/scorecards/player/...`` is not captured as a match id.


@router.get("/scorecards/player/{player_id}")
def player_scorecard_list(
    player_id: str,
    limit: int = Query(200, ge=1, le=2000),
    store=Depends(_get_store),
):
    """Return all per-match performances (batting and bowling) for a player based on scorecards."""
    _, _, sc_dir = _get_sc_dir(store)
    if not sc_dir.exists():
        return []

    performances: List[Dict[str, Any]] = []
    pid = str(player_id)

    for path in sorted(sc_dir.glob("*.json")):
        sc = _load_scorecard_file(path)
        if sc is None:
            continue
        meta = sc.get("meta", {})
        for inn_num, inn in sc.get("innings", {}).items():
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


@router.get("/scorecards/player/{player_id}/match-impact")
def player_match_impact_performances(player_id: str, store=Depends(_get_store)):
    """Every scorecard match where this player has a qualifying match-impact line."""
    from match_impact import combined_row_for_player

    _, _, sc_dir = _get_sc_dir(store)
    if not sc_dir.exists():
        return JSONResponse(content=[])

    pid = str(player_id)
    rows: List[Dict[str, Any]] = []

    for path in sorted(sc_dir.glob("*.json")):
        sc = _load_scorecard_file(path)
        if sc is None:
            continue
        row = combined_row_for_player(sc, pid)
        if row is None:
            continue
        meta = sc.get("meta") or {}
        teams_out = _teams_from_scorecard(sc)
        rows.append(
            {
                "match_id": str(meta.get("match_id") or path.stem),
                "date": meta.get("date"),
                "venue": meta.get("venue"),
                "event_name": meta.get("event_name"),
                "teams": teams_out,
                "total_impact": row["total_impact"],
                "bat_impact": row["bat_impact"],
                "bowl_impact": row["bowl_impact"],
                "bat_runs": row.get("bat_runs"),
                "bat_balls": row.get("bat_balls"),
                "bowl_wickets": row.get("bowl_wickets"),
                "bowl_runs_conceded": row.get("bowl_runs_conceded"),
                "bowl_balls": row.get("bowl_balls"),
            }
        )

    def _item_sort_key(item: Dict[str, Any]) -> tuple:
        d = _parse_meta_date(item.get("date"))
        d_ord = d.toordinal() if d is not None else -1
        tid = str(item.get("match_id") or "")
        return (-float(item.get("total_impact") or 0), -d_ord, tid)

    rows.sort(key=_item_sort_key)
    return JSONResponse(content=_sanitize_json_values(rows))


@router.get("/scorecards/{match_id}")
def get_scorecard(match_id: str, store=Depends(_get_store)):
    """Retrieve the full scorecard JSON for a single match_id."""
    _, _, sc_dir = _get_sc_dir(store)
    sc_path = sc_dir / f"{match_id}.json"
    if not sc_path.exists():
        raise HTTPException(status_code=404, detail=f"Scorecard not found: {match_id}")
    sc = _load_scorecard_file(sc_path)
    if sc is None:
        raise HTTPException(
            status_code=500, detail=f"Failed to read scorecard: {match_id}"
        )
    return JSONResponse(content=_sanitize_json_values(sc))
