"""
Venue analytics — aggregations for /api/venues/profile, trends, teams, similar, matches, performances.

All functions accept (conn, fmt) instead of a DataStore, running SQL against DuckDB.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from db import safe_float, safe_int, safe_str, safe_fmt, query_one, query_all, query_count
from match_impact import combined_row_for_player


# ── Safe-float with 4dp (internal detail columns) ────────────────

def _sf(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


# ── Venue resolution ──────────────────────────────────────────────

def resolve_venue_row(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue_query: str,
    exact: bool,
) -> tuple[dict | None, str]:
    """Resolve a user query to a row in {fmt}.venue.

    Returns (row_or_none, canonical_venue_name).
    """
    f = safe_fmt(fmt)
    q = venue_query.strip()
    ql = q.lower()

    row = query_one(conn, f"SELECT * FROM {f}.venue WHERE LOWER(venue) = LOWER(?) LIMIT 1", [q])
    if row is not None:
        return row, safe_str(row.get("venue"), q)

    if not exact:
        row = query_one(
            conn,
            f"SELECT * FROM {f}.venue WHERE LOWER(venue) LIKE '%' || LOWER(?) || '%' LIMIT 1",
            [q],
        )
        if row is not None:
            return row, safe_str(row.get("venue"), q)

    return None, q


def venue_where_clause(venue_col: str = "venue") -> str:
    """SQL WHERE fragment for case-insensitive venue matching (use with parameterised query)."""
    return f"LOWER(CAST({venue_col} AS VARCHAR)) = LOWER(?)"


def venue_like_clause(venue_col: str = "venue") -> str:
    """SQL WHERE fragment for partial venue matching."""
    return f"LOWER(CAST({venue_col} AS VARCHAR)) LIKE '%' || LOWER(?) || '%'"


def _venue_filter_sql(venue_col: str, exact: bool) -> str:
    return venue_where_clause(venue_col) if exact else venue_where_clause(venue_col)


# ── Profile ──────────────────────────────────────────────────────

def _phase_bat_aggregate_sql(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue: str,
) -> dict[str, Any]:
    f = safe_fmt(fmt)
    row = query_one(conn, f"""
        SELECT
            SUM(COALESCE(powerplay_runs, 0)) AS pp_runs,
            SUM(COALESCE(powerplay_balls, 0)) AS pp_balls,
            SUM(COALESCE(middle_runs, 0)) AS mid_runs,
            SUM(COALESCE(middle_balls, 0)) AS mid_balls,
            SUM(COALESCE(death_runs, 0)) AS death_runs,
            SUM(COALESCE(death_balls, 0)) AS death_balls
        FROM {f}.bat_innings
        WHERE LOWER(venue) = LOWER(?)
    """, [venue])
    if row is None:
        return {p: {"sr": None, "balls": 0, "runs": 0} for p in ("powerplay", "middle", "death")}
    out: dict[str, Any] = {}
    for phase, rk, bk in (
        ("powerplay", "pp_runs", "pp_balls"),
        ("middle", "mid_runs", "mid_balls"),
        ("death", "death_runs", "death_balls"),
    ):
        runs = safe_int(row.get(rk))
        balls = safe_int(row.get(bk))
        sr = _sf((runs / balls * 100.0) if balls > 0 else None)
        out[phase] = {"sr": sr, "balls": balls, "runs": runs}
    return out


def _phase_bat_vs_par_mean_sql(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue: str,
) -> dict[str, float | None]:
    f = safe_fmt(fmt)
    res: dict[str, float | None] = {}
    par_map = {
        "powerplay": ("powerplay_sr", "pp_par_sr"),
        "middle": ("middle_sr", "middle_par_sr"),
        "death": ("death_sr", "death_par_sr"),
    }
    for phase, (sr_c, par_c) in par_map.items():
        row = query_one(conn, f"""
            SELECT AVG(
                CASE WHEN {par_c} > 0 AND {sr_c} IS NOT NULL AND {par_c} IS NOT NULL
                     THEN CAST({sr_c} AS DOUBLE) / CAST({par_c} AS DOUBLE)
                     ELSE NULL END
            ) AS ratio
            FROM {f}.bat_innings
            WHERE LOWER(venue) = LOWER(?)
        """, [venue])
        res[phase] = _sf(row["ratio"]) if row and row.get("ratio") is not None else None
    return res


def _phase_bowl_aggregate_sql(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue: str,
) -> dict[str, Any]:
    f = safe_fmt(fmt)
    row = query_one(conn, f"""
        SELECT
            SUM(COALESCE(powerplay_legal_balls, 0)) AS pp_balls,
            SUM(COALESCE(powerplay_runs, 0)) AS pp_runs,
            SUM(COALESCE(powerplay_dots, 0)) AS pp_dots,
            SUM(COALESCE(middle_legal_balls, 0)) AS mid_balls,
            SUM(COALESCE(middle_runs, 0)) AS mid_runs,
            SUM(COALESCE(middle_dots, 0)) AS mid_dots,
            SUM(COALESCE(death_legal_balls, 0)) AS death_balls,
            SUM(COALESCE(death_runs, 0)) AS death_runs,
            SUM(COALESCE(death_dots, 0)) AS death_dots
        FROM {f}.bowl_spells
        WHERE LOWER(venue) = LOWER(?)
    """, [venue])
    if row is None:
        return {p: {"economy": None, "dot_pct": None, "balls": 0} for p in ("powerplay", "middle", "death")}
    out: dict[str, Any] = {}
    for phase, bk, rk, dk in (
        ("powerplay", "pp_balls", "pp_runs", "pp_dots"),
        ("middle", "mid_balls", "mid_runs", "mid_dots"),
        ("death", "death_balls", "death_runs", "death_dots"),
    ):
        balls = safe_int(row.get(bk))
        runs = safe_int(row.get(rk))
        dots = safe_int(row.get(dk))
        overs = balls / 6.0
        econ = _sf(runs / overs) if overs > 0 else None
        dot_pct = _sf(dots / balls) if balls > 0 else None
        out[phase] = {"economy": econ, "dot_pct": dot_pct, "balls": balls}
    return out


def _format_phase_aggregate_sql(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
) -> dict[str, Any]:
    """Aggregate phase SR across the entire format (all venues)."""
    f = safe_fmt(fmt)
    row = query_one(conn, f"""
        SELECT
            SUM(COALESCE(powerplay_runs, 0)) AS pp_runs,
            SUM(COALESCE(powerplay_balls, 0)) AS pp_balls,
            SUM(COALESCE(middle_runs, 0)) AS mid_runs,
            SUM(COALESCE(middle_balls, 0)) AS mid_balls,
            SUM(COALESCE(death_runs, 0)) AS death_runs,
            SUM(COALESCE(death_balls, 0)) AS death_balls
        FROM {f}.bat_innings
    """)
    if row is None:
        return {}
    out: dict[str, Any] = {}
    for phase, rk, bk in (
        ("powerplay", "pp_runs", "pp_balls"),
        ("middle", "mid_runs", "mid_balls"),
        ("death", "death_runs", "death_balls"),
    ):
        runs = safe_int(row.get(rk))
        balls = safe_int(row.get(bk))
        sr = _sf((runs / balls * 100.0) if balls > 0 else None)
        out[phase] = {"sr": sr, "balls": balls, "runs": runs}
    return out


def _median_venue_phase_sr_sql(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
) -> dict[str, float | None]:
    """Median venue-level phase SR across all venues.

    Uses the pre-computed venue_phase_sr_stats table if available,
    otherwise computes from bat_innings.
    """
    f = safe_fmt(fmt)
    try:
        row = query_one(conn, f"""
            SELECT * FROM {f}.venue_phase_sr_stats LIMIT 1
        """)
        if row is not None:
            return {
                "powerplay": _sf(row.get("median_pp_sr")),
                "middle": _sf(row.get("median_mid_sr")),
                "death": _sf(row.get("median_death_sr")),
            }
    except duckdb.CatalogException:
        pass

    rows = query_all(conn, f"""
        SELECT
            venue,
            CASE WHEN SUM(COALESCE(powerplay_balls, 0)) > 0
                 THEN SUM(COALESCE(powerplay_runs, 0)) * 100.0
                      / SUM(COALESCE(powerplay_balls, 0))
                 ELSE NULL END AS pp_sr,
            CASE WHEN SUM(COALESCE(middle_balls, 0)) > 0
                 THEN SUM(COALESCE(middle_runs, 0)) * 100.0
                      / SUM(COALESCE(middle_balls, 0))
                 ELSE NULL END AS mid_sr,
            CASE WHEN SUM(COALESCE(death_balls, 0)) > 0
                 THEN SUM(COALESCE(death_runs, 0)) * 100.0
                      / SUM(COALESCE(death_balls, 0))
                 ELSE NULL END AS death_sr
        FROM {f}.bat_innings
        GROUP BY venue
    """)
    if not rows:
        return {"powerplay": None, "middle": None, "death": None}

    result: dict[str, float | None] = {}
    for key, col in (("powerplay", "pp_sr"), ("middle", "mid_sr"), ("death", "death_sr")):
        vals = [r[col] for r in rows if r.get(col) is not None]
        if vals:
            vals.sort()
            mid = len(vals) // 2
            result[key] = _sf(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0)
        else:
            result[key] = None
    return result


def _chase_defend_sql(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue: str,
) -> dict[str, Any]:
    f = safe_fmt(fmt)
    rows = query_all(conn, f"""
        SELECT match_id, innings_num, batting_team, total_runs, winner
        FROM (
            SELECT DISTINCT match_id, innings_num, batting_team, total_runs, winner
            FROM {f}.bat_innings
            WHERE LOWER(venue) = LOWER(?)
        ) t
        ORDER BY match_id, innings_num
    """, [venue])
    if not rows:
        return {}

    from collections import defaultdict
    matches: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        matches[str(r["match_id"])].append(r)

    inn1_scores: list[float] = []
    inn2_scores: list[float] = []
    bat_first_wins = 0
    bat_second_wins = 0
    n_decided = 0

    for _mid, innings_rows in matches.items():
        innings_rows.sort(key=lambda x: safe_int(x.get("innings_num")))
        if not innings_rows:
            continue
        r1 = innings_rows[0]
        score1 = float(safe_int(r1.get("total_runs")))
        inn1_scores.append(score1)
        t_first = safe_str(r1.get("batting_team")).strip()
        t_second = ""
        if len(innings_rows) >= 2:
            r2 = innings_rows[-1]
            score2 = float(safe_int(r2.get("total_runs")))
            inn2_scores.append(score2)
            t_second = safe_str(r2.get("batting_team")).strip()

        w = safe_str(r1.get("winner")).strip()
        if not w:
            continue
        n_decided += 1
        if w == t_first:
            bat_first_wins += 1
        elif t_second and w == t_second:
            bat_second_wins += 1

    return {
        "avg_first_innings_score": _sf(float(np.mean(inn1_scores)) if inn1_scores else None),
        "avg_second_innings_score": _sf(float(np.mean(inn2_scores)) if inn2_scores else None),
        "matches_with_result": n_decided,
        "wins_batting_first": bat_first_wins,
        "wins_chasing": bat_second_wins,
        "win_pct_batting_first": _sf((bat_first_wins / n_decided * 100) if n_decided else None),
    }


def _percentile_rank_sql(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    col: str,
    value: float | None,
    min_matches: int = 10,
) -> float | None:
    if value is None:
        return None
    f = safe_fmt(fmt)
    where = f"WHERE venue_matches >= {min_matches}" if min_matches > 0 else ""
    row = query_one(conn, f"""
        SELECT COUNT(*) FILTER (WHERE {col} < ?) * 100.0
               / NULLIF(COUNT(*) FILTER (WHERE {col} IS NOT NULL), 0) AS pct
        FROM {f}.venue
        {where}
    """, [value])
    return round(float(row["pct"]), 2) if row and row.get("pct") is not None else None


def build_venue_profile(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue_query: str,
    *,
    exact: bool = False,
    min_venues_for_field: int = 10,
) -> dict[str, Any] | None:
    row, canonical = resolve_venue_row(conn, fmt, venue_query, exact)
    if row is None:
        return None

    f = safe_fmt(fmt)
    stats = query_one(conn, f"""
        SELECT COUNT(*) AS n_inn,
               SUM(COALESCE(balls_faced, 0)) AS n_balls,
               COUNT(DISTINCT match_id) AS n_matches
        FROM {f}.bat_innings
        WHERE LOWER(venue) = LOWER(?)
    """, [canonical])
    n_inn = safe_int(stats.get("n_inn")) if stats else 0
    n_balls = safe_int(stats.get("n_balls")) if stats else 0
    n_matches = safe_int(stats.get("n_matches")) if stats else 0

    avg_par = _sf(row.get("venue_avg_par_sr"))
    boundary = _sf(row.get("venue_avg_boundary_rate"))
    dotp = _sf(row.get("venue_avg_dot_pct"))
    diff_z = _sf(row.get("venue_difficulty"))

    # Difficulty index (0-100): prefer pre-computed, else compute
    diff_display = _sf(row.get("venue_difficulty_index"))
    if diff_display is None and diff_z is not None:
        try:
            vd_row = query_one(conn, f"""
                SELECT venue_difficulty_index
                FROM {f}.venue_with_difficulty
                WHERE LOWER(venue) = LOWER(?)
                LIMIT 1
            """, [canonical])
            if vd_row:
                diff_display = _sf(vd_row.get("venue_difficulty_index"))
        except duckdb.CatalogException:
            pass

    phase_loc = _phase_bat_aggregate_sql(conn, fmt, canonical)
    phase_loc_vs_par = _phase_bat_vs_par_mean_sql(conn, fmt, canonical)
    phase_bowl = _phase_bowl_aggregate_sql(conn, fmt, canonical)
    phase_field = _format_phase_aggregate_sql(conn, fmt)
    median_phase = _median_venue_phase_sr_sql(conn, fmt)
    chase = _chase_defend_sql(conn, fmt, canonical)

    phase_compare = {}
    for ph in ("powerplay", "middle", "death"):
        loc_sr = phase_loc.get(ph, {}).get("sr")
        fld_sr = phase_field.get(ph, {}).get("sr")
        med_sr = median_phase.get(ph)
        phase_compare[ph] = {
            "venue_sr": loc_sr,
            "format_mean_sr": fld_sr,
            "median_venue_sr": med_sr,
            "vs_par_ratio_mean": phase_loc_vs_par.get(ph),
        }

    return {
        "venue": canonical,
        "matches": safe_int(row.get("venue_matches")),
        "batting_innings": n_inn,
        "balls_faced_total": n_balls,
        "matches_in_slice": n_matches,
        "small_sample": n_matches < 10,
        "avg_par_sr": avg_par,
        "boundary_rate": boundary,
        "dot_pct": dotp,
        "difficulty_score": diff_display,
        "par_sr_std": _sf(row.get("venue_par_std")),
        "difficulty_raw": _sf(row.get("venue_difficulty_raw")),
        "vs_world": {
            "avg_par_sr_percentile": _percentile_rank_sql(conn, fmt, "venue_avg_par_sr", avg_par, min_venues_for_field),
            "boundary_rate_percentile": _percentile_rank_sql(conn, fmt, "venue_avg_boundary_rate", boundary, min_venues_for_field),
            "dot_pct_percentile": _percentile_rank_sql(conn, fmt, "venue_avg_dot_pct", dotp, min_venues_for_field),
            "difficulty_percentile": _percentile_rank_sql(conn, fmt, "venue_difficulty", diff_z, min_venues_for_field),
        },
        "chase_defend": chase,
        "phases_batting": phase_compare,
        "phases_bowling": {
            ph: {
                "venue": phase_bowl.get(ph, {}),
                "note": "Economy = runs per over in phase; dot_pct when available.",
            }
            for ph in ("powerplay", "middle", "death")
        },
    }


# ── Trends ───────────────────────────────────────────────────────

def build_venue_trends(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue_query: str,
    *,
    exact: bool = False,
    bucket: str = "rolling_3_match",
) -> dict[str, Any] | None:
    _, canonical = resolve_venue_row(conn, fmt, venue_query, exact)
    f = safe_fmt(fmt)

    if bucket in ("year", "season"):
        series = _venue_trends_by_year_sql(conn, f, canonical)
    else:
        series = _venue_trends_rolling_sql(conn, f, canonical, window=3)

    out_bucket = bucket if bucket in ("year", "season") else "rolling_3_match"
    return {"venue": canonical, "bucket": out_bucket, "series": series}


def _venue_trends_by_year_sql(
    conn: duckdb.DuckDBPyConnection,
    f: str,
    venue: str,
) -> list[dict[str, Any]]:
    rows = query_all(conn, f"""
        WITH per_match AS (
            SELECT DISTINCT match_id, innings_num, batting_team,
                   total_runs, match_par_sr, date
            FROM {f}.bat_innings
            WHERE LOWER(venue) = LOWER(?) AND date IS NOT NULL
        )
        SELECT DATE_PART('year', TRY_CAST(date AS TIMESTAMP))::INTEGER AS yr,
               COUNT(DISTINCT match_id) AS matches,
               ROUND(AVG(total_runs), 4) AS mean_team_innings_score,
               ROUND(AVG(match_par_sr), 4) AS mean_match_par_sr
        FROM per_match
        WHERE DATE_PART('year', TRY_CAST(date AS TIMESTAMP)) IS NOT NULL
        GROUP BY yr
        ORDER BY yr
    """, [venue])
    return [
        {
            "period": str(safe_int(r["yr"])),
            "matches": safe_int(r["matches"]),
            "mean_team_innings_score": _sf(r.get("mean_team_innings_score")),
            "mean_match_par_sr": _sf(r.get("mean_match_par_sr")),
        }
        for r in rows
    ]


def _venue_trends_rolling_sql(
    conn: duckdb.DuckDBPyConnection,
    f: str,
    venue: str,
    *,
    window: int = 3,
) -> list[dict[str, Any]]:
    rows = query_all(conn, f"""
        WITH per_match AS (
            SELECT match_id,
                   MIN(TRY_CAST(date AS TIMESTAMP)) AS dt,
                   AVG(total_runs) AS avg_innings_runs,
                   AVG(match_par_sr) AS avg_match_par_sr
            FROM (
                SELECT DISTINCT match_id, innings_num, batting_team,
                       total_runs, match_par_sr, date
                FROM {f}.bat_innings
                WHERE LOWER(venue) = LOWER(?) AND date IS NOT NULL
            ) t
            GROUP BY match_id
        ),
        ordered AS (
            SELECT *,
                   AVG(avg_innings_runs)
                       OVER (ORDER BY dt ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW) AS roll_runs,
                   AVG(avg_match_par_sr)
                       OVER (ORDER BY dt ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW) AS roll_par,
                   ROW_NUMBER() OVER (ORDER BY dt) AS rn
            FROM per_match
        )
        SELECT dt, roll_runs, roll_par
        FROM ordered
        WHERE rn >= {window}
        ORDER BY dt
    """, [venue])
    series: list[dict[str, Any]] = []
    for r in rows:
        dt = r.get("dt")
        if dt is None:
            continue
        period = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        series.append({
            "period": period,
            "matches": window,
            "mean_team_innings_score": _sf(r.get("roll_runs")),
            "mean_match_par_sr": _sf(r.get("roll_par")),
        })
    return series


# ── Teams ────────────────────────────────────────────────────────

def build_venue_teams(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue_query: str,
    *,
    exact: bool = False,
    min_matches: int = 2,
    sort: str = "win_pct",
    order: str = "desc",
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any] | None:
    _, canonical = resolve_venue_row(conn, fmt, venue_query, exact)
    if canonical is None:
        return None
    f = safe_fmt(fmt)

    all_rows = query_all(conn, f"""
        SELECT batting_team AS team,
               COUNT(DISTINCT match_id) AS matches,
               SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS wins,
               COUNT(DISTINCT match_id)
                 - SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS losses,
               ROUND(
                   SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) * 100.0
                   / NULLIF(COUNT(DISTINCT match_id), 0), 2
               ) AS win_pct
        FROM (
            SELECT DISTINCT match_id, innings_num, batting_team, winner
            FROM {f}.bat_innings
            WHERE LOWER(venue) = LOWER(?)
        ) t
        GROUP BY batting_team
        HAVING COUNT(DISTINCT match_id) >= ?
    """, [canonical, min_matches])

    if not all_rows:
        return {
            "venue": canonical,
            "teams": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    sort_col = sort if sort in ("team", "matches", "wins", "losses", "win_pct") else "win_pct"
    reverse = order.lower() != "asc"

    def _sort_key(r: dict) -> Any:
        v = r.get(sort_col)
        if v is None:
            return (1, 0)
        if isinstance(v, str):
            return (0, v.lower())
        return (0, v)

    all_rows.sort(key=_sort_key, reverse=reverse)

    total = len(all_rows)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    chunk = all_rows[start:start + per_page]

    return {
        "venue": canonical,
        "teams": [
            {
                "team": safe_str(r.get("team")),
                "matches": safe_int(r.get("matches")),
                "wins": safe_int(r.get("wins")),
                "losses": safe_int(r.get("losses")),
                "win_pct": _sf(r.get("win_pct")),
            }
            for r in chunk
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── Similar venues (cosine similarity in Python) ─────────────────

def build_venue_similar(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue_query: str,
    *,
    exact: bool = False,
    k: int = 8,
) -> dict[str, Any] | None:
    row, canonical = resolve_venue_row(conn, fmt, venue_query, exact)
    if row is None:
        return None
    f = safe_fmt(fmt)

    try:
        venue_data = query_all(conn, f"""
            SELECT venue, venue_avg_par_sr, venue_avg_boundary_rate,
                   venue_avg_dot_pct, venue_difficulty, venue_matches,
                   venue_difficulty_index
            FROM {f}.venue_with_difficulty
        """)
    except duckdb.CatalogException:
        venue_data = query_all(conn, f"""
            SELECT venue, venue_avg_par_sr, venue_avg_boundary_rate,
                   venue_avg_dot_pct, venue_difficulty, venue_matches
            FROM {f}.venue
        """)

    if not venue_data:
        return {"venue": canonical, "similar": []}

    feat_keys = ["venue_avg_par_sr", "venue_avg_boundary_rate", "venue_avg_dot_pct", "venue_difficulty"]
    available_keys = [k_ for k_ in feat_keys if any(r.get(k_) is not None for r in venue_data)]
    if len(available_keys) < 2:
        return {"venue": canonical, "similar": []}

    n = len(venue_data)
    M = np.zeros((n, len(available_keys)), dtype=float)
    i0 = None
    for i, r in enumerate(venue_data):
        for j, fk in enumerate(available_keys):
            v = r.get(fk)
            M[i, j] = float(v) if v is not None else 0.0
        if safe_str(r.get("venue")).lower() == canonical.lower():
            i0 = i

    if i0 is None:
        return {"venue": canonical, "similar": []}

    mu = M.mean(axis=0)
    sig = M.std(axis=0)
    sig = np.where(sig == 0, 1.0, sig)
    Mz = (M - mu) / sig

    v0 = Mz[i0]
    sims = []
    for i in range(n):
        if i == i0:
            continue
        v = Mz[i]
        denom = (np.linalg.norm(v0) * np.linalg.norm(v)) or 1.0
        cos = float(np.dot(v0, v) / denom)
        sims.append((cos, i))
    sims.sort(key=lambda x: -x[0])

    out = []
    for cos, i in sims[:k]:
        r = venue_data[i]
        out.append({
            "venue": safe_str(r.get("venue")),
            "similarity": round(cos, 4),
            "matches": safe_int(r.get("venue_matches")),
            "avg_par_sr": _sf(r.get("venue_avg_par_sr")),
            "difficulty_score": _sf(r.get("venue_difficulty_index")),
        })

    return {"venue": canonical, "similar": out}


# ── Match list ───────────────────────────────────────────────────

def build_venue_matches(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue_query: str,
    *,
    exact: bool = False,
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any] | None:
    _, canonical = resolve_venue_row(conn, fmt, venue_query, exact)
    if canonical is None:
        return None
    f = safe_fmt(fmt)

    total = query_count(conn, f"""
        SELECT COUNT(DISTINCT match_id) FROM {f}.bat_innings
        WHERE LOWER(venue) = LOWER(?)
    """, [canonical])

    if total == 0:
        return {
            "venue": canonical,
            "matches": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page

    rows = query_all(conn, f"""
        SELECT match_id,
               MIN(date)::VARCHAR AS date,
               ANY_VALUE(event_name) AS event_name,
               ANY_VALUE(winner) AS winner,
               LIST(batting_team ORDER BY innings_num) AS teams,
               LIST(total_runs ORDER BY innings_num) AS innings_scores
        FROM (
            SELECT DISTINCT match_id, date, event_name, winner,
                   innings_num, batting_team, total_runs
            FROM {f}.bat_innings
            WHERE LOWER(venue) = LOWER(?)
        ) t
        GROUP BY match_id
        ORDER BY MIN(date) DESC
        LIMIT ? OFFSET ?
    """, [canonical, per_page, offset])

    matches = []
    for r in rows:
        teams_raw = r.get("teams")
        teams = list(dict.fromkeys(teams_raw)) if isinstance(teams_raw, list) else []
        scores_raw = r.get("innings_scores")
        scores = [safe_int(s) for s in scores_raw] if isinstance(scores_raw, list) else []
        matches.append({
            "match_id": safe_str(r.get("match_id")),
            "date": safe_str(r.get("date")),
            "event_name": safe_str(r.get("event_name")) or None,
            "winner": safe_str(r.get("winner")) or None,
            "teams": teams,
            "innings_scores": scores,
        })

    return {
        "venue": canonical,
        "matches": matches,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── Performances (uses scorecard JSON for match-impact) ──────────

def _scorecard_dir() -> Path | None:
    """Resolve the directory containing scorecard JSON files."""
    import os
    sc = os.environ.get("SCORECARDS_DIR")
    if sc:
        p = Path(sc)
        return p if p.is_dir() else None
    db_path = os.environ.get("DUCKDB_PATH", "/data/cricket/cricket.duckdb")
    candidates = [
        Path(db_path).parent / "scorecards",
        Path(db_path).parent.parent / "output" / "scorecards",
        Path(db_path).parent.parent / "scorecards",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _load_scorecard_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def build_venue_performances(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue_query: str,
    *,
    exact: bool = False,
    role: str = "bat",
    sort: str = "bat_impact",
    order: str = "desc",
    page: int = 1,
    per_page: int = 25,
    min_balls: int = 5,
) -> dict[str, Any] | None:
    _, canonical = resolve_venue_row(conn, fmt, venue_query, exact)
    if canonical is None:
        return None

    sc_dir = _scorecard_dir()
    sc_cache: dict[str, dict[str, Any] | None] = {}

    def _sc(mid: str) -> dict[str, Any] | None:
        if mid not in sc_cache:
            p = (sc_dir / f"{mid}.json") if sc_dir else None
            sc_cache[mid] = _load_scorecard_json(p) if p and p.is_file() else None
        return sc_cache[mid]

    f = safe_fmt(fmt)
    rows_out: list[dict[str, Any]] = []

    if role == "bowl":
        mb = max(min_balls, 6)
        db_rows = query_all(conn, f"""
            SELECT DISTINCT match_id, bowler_id, bowler, bowling_team, batting_team,
                   date, event_name, wickets, runs_conceded, legal_balls, economy,
                   acc_economy_vs_par
            FROM {f}.bowl_spells
            WHERE LOWER(venue) = LOWER(?) AND COALESCE(legal_balls, 0) >= ?
            ORDER BY wickets DESC
        """, [canonical, mb])

        seen: set[tuple[str, str]] = set()
        for r in db_rows:
            mid = safe_str(r.get("match_id"))
            pid = safe_str(r.get("bowler_id"))
            if not mid or not pid or (mid, pid) in seen:
                continue
            seen.add((mid, pid))
            sc = _sc(mid)
            if sc is None:
                continue
            crow = combined_row_for_player(sc, pid)
            if crow is None:
                continue
            meta = sc.get("meta") or {}
            d = r.get("date")
            date_out = d.isoformat() if d is not None and hasattr(d, "isoformat") else safe_str(d)
            rows_out.append({
                "player_id": pid,
                "player_name": safe_str(r.get("bowler")),
                "match_id": mid,
                "date": date_out,
                "event_name": safe_str(r.get("event_name")) or safe_str(meta.get("event_name")) or None,
                "venue": safe_str(meta.get("venue")) or None,
                "bowling_team": safe_str(r.get("bowling_team")) or None,
                "opposition": safe_str(r.get("batting_team")) or None,
                "wickets": safe_int(crow.get("bowl_wickets")),
                "runs_conceded": safe_int(crow.get("bowl_runs_conceded")),
                "legal_balls": safe_int(crow.get("bowl_balls")),
                "economy": _sf(r.get("economy")),
                "acc_economy_vs_par": _sf(r.get("acc_economy_vs_par")),
                "bat_impact": _sf(crow.get("bat_impact")),
                "bowl_impact": _sf(crow.get("bowl_impact")),
                "total_impact": _sf(crow.get("total_impact")),
                "bat_runs": safe_int(crow.get("bat_runs")),
                "bat_balls": safe_int(crow.get("bat_balls")),
            })
    else:
        db_rows = query_all(conn, f"""
            SELECT DISTINCT match_id, batter_id, batter, batting_team, bowling_team,
                   date, event_name, runs, balls_faced, sr,
                   acc_leveraged_rva, acc_runs_above_expected, acc_overall_sr,
                   total_runs, match_par_sr
            FROM {f}.bat_innings
            WHERE LOWER(venue) = LOWER(?) AND COALESCE(balls_faced, 0) >= ?
            ORDER BY runs DESC
        """, [canonical, min_balls])

        seen = set()
        for r in db_rows:
            mid = safe_str(r.get("match_id"))
            pid = safe_str(r.get("batter_id"))
            if not mid or not pid or (mid, pid) in seen:
                continue
            seen.add((mid, pid))
            sc = _sc(mid)
            if sc is None:
                continue
            crow = combined_row_for_player(sc, pid)
            if crow is None:
                continue
            meta = sc.get("meta") or {}
            d = r.get("date")
            date_out = d.isoformat() if d is not None and hasattr(d, "isoformat") else safe_str(d)
            rows_out.append({
                "player_id": pid,
                "player_name": safe_str(r.get("batter")),
                "match_id": mid,
                "date": date_out,
                "event_name": safe_str(r.get("event_name")) or safe_str(meta.get("event_name")) or None,
                "venue": safe_str(meta.get("venue")) or None,
                "batting_team": safe_str(r.get("batting_team")) or None,
                "opposition": safe_str(r.get("bowling_team")) or None,
                "runs": safe_int(crow.get("bat_runs")),
                "balls_faced": safe_int(crow.get("bat_balls")),
                "sr": _sf(r.get("sr")),
                "acc_leveraged_rva": _sf(r.get("acc_leveraged_rva")),
                "acc_runs_above_expected": _sf(r.get("acc_runs_above_expected")),
                "acc_overall_sr": _sf(r.get("acc_overall_sr")),
                "team_innings_total": safe_int(r.get("total_runs")),
                "match_par_sr": _sf(r.get("match_par_sr")),
                "bat_impact": _sf(crow.get("bat_impact")),
                "bowl_impact": _sf(crow.get("bowl_impact")),
                "total_impact": _sf(crow.get("total_impact")),
                "bat_runs": safe_int(crow.get("bat_runs")),
                "bat_balls": safe_int(crow.get("bat_balls")),
                "bowl_wickets": safe_int(crow.get("bowl_wickets")),
                "bowl_runs_conceded": safe_int(crow.get("bowl_runs_conceded")),
                "bowl_balls": safe_int(crow.get("bowl_balls")),
            })

    if not rows_out:
        return {
            "venue": canonical,
            "role": role,
            "sort": sort,
            "performances": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    sort_key = sort.strip()
    if role == "bat":
        sort_key = {"acc_impact": "bat_impact", "impact": "bat_impact"}.get(sort_key, sort_key)
        if not any(sort_key in r for r in rows_out):
            sort_key = "bat_impact"
    else:
        sort_key = {"acc_impact": "bowl_impact", "impact": "bowl_impact"}.get(sort_key, sort_key)
        if not any(sort_key in r for r in rows_out):
            sort_key = "bowl_impact"

    asc = order.lower() == "asc"

    def _sk(r: dict) -> Any:
        v = r.get(sort_key)
        if v is None:
            return (1, 0)
        return (0, v)

    rows_out.sort(key=_sk, reverse=not asc)

    total = len(rows_out)
    total_pages = math.ceil(total / per_page) if total else 0
    start = (page - 1) * per_page
    page_rows = rows_out[start:start + per_page]

    return {
        "venue": canonical,
        "role": role,
        "sort": sort_key,
        "performances": page_rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── Players at venue (batting / bowling) ─────────────────────────

def players_at_venue_batting(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue: str,
    min_innings: int,
    sort: str,
    order: str,
    page: int,
    per_page: int,
    exact: bool,
) -> dict:
    f = safe_fmt(fmt)
    row, canonical = resolve_venue_row(conn, fmt, venue, exact)
    if row is None:
        canonical = venue.strip()

    all_rows = query_all(conn, f"""
        WITH venue_agg AS (
            SELECT
                i.batter_id,
                ANY_VALUE(i.batter) AS batter,
                COUNT(*) AS innings,
                SUM(COALESCE(i.runs, 0)) AS runs,
                SUM(COALESCE(i.balls_faced, 0)) AS balls_faced,
                SUM(COALESCE(i.fours, 0)) AS fours,
                SUM(COALESCE(i.sixes, 0)) AS sixes,
                SUM(COALESCE(i.dots, 0)) AS dots,
                MAX(i.date)::VARCHAR AS last_played_at_venue,
                AVG(TRY_CAST(i.score_acceleration AS DOUBLE)) AS venue_score_acceleration,
                AVG(TRY_CAST(i.score_power AS DOUBLE)) AS venue_score_power,
                AVG(TRY_CAST(i.score_control AS DOUBLE)) AS venue_score_control,
                AVG(TRY_CAST(i.overall_score AS DOUBLE)) AS venue_overall_score
            FROM {f}.bat_innings i
            WHERE LOWER(i.venue) = LOWER(?)
            GROUP BY i.batter_id
            HAVING COUNT(*) >= ?
        )
        SELECT va.*,
               c.country,
               c.career_sr,
               c.career_avg,
               c.career_dot_pct,
               c.total_runs AS career_total_runs,
               c.total_balls AS career_total_balls,
               c.total_fours AS career_total_fours,
               c.total_sixes AS career_total_sixes,
               c.overall_score AS career_overall_score,
               c.overall_grade,
               c.score_acceleration AS career_score_acceleration,
               c.score_power AS career_score_power,
               c.score_control AS career_score_control
        FROM venue_agg va
        LEFT JOIN {f}.bat_careers c ON va.batter_id = c.batter_id
    """, [canonical, min_innings])

    if not all_rows:
        return {
            "venue": canonical,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    for r in all_rows:
        balls = safe_int(r.get("balls_faced"))
        runs = safe_int(r.get("runs"))
        dots = safe_int(r.get("dots"))
        fours = safe_int(r.get("fours"))
        sixes = safe_int(r.get("sixes"))
        inn = safe_int(r.get("innings"))

        r["sr"] = round(runs / balls * 100.0, 1) if balls > 0 else None
        r["avg"] = round(runs / max(inn, 1), 1)
        r["dot_pct"] = round(dots / balls, 4) if balls > 0 else None
        bruns = fours * 4 + sixes * 6
        r["boundary_pct"] = round(bruns / runs, 4) if runs > 0 else None
        r["six_rate"] = round(sixes / balls, 4) if balls > 0 else None

        # Career derived
        tr = float(r.get("career_total_runs") or 0)
        tb = float(r.get("career_total_balls") or 0)
        tf = float(r.get("career_total_fours") or 0)
        ts = float(r.get("career_total_sixes") or 0)
        r["career_boundary_pct"] = round((tf * 4 + ts * 6) / tr, 4) if tr > 0 else None
        r["career_six_rate"] = round(ts / tb, 4) if tb > 0 else None

        c_sr = r.get("career_sr")
        r["sr_delta"] = round(r["sr"] - float(c_sr), 2) if r["sr"] is not None and c_sr is not None else None
        c_avg = r.get("career_avg")
        r["avg_delta"] = round(r["avg"] - float(c_avg), 2) if r["avg"] is not None and c_avg is not None else None
        c_dp = r.get("career_dot_pct")
        r["dot_pct_delta"] = round(r["dot_pct"] - float(c_dp), 4) if r["dot_pct"] is not None and c_dp is not None else None
        r["boundary_pct_delta"] = (
            round(r["boundary_pct"] - r["career_boundary_pct"], 4)
            if r.get("boundary_pct") is not None and r.get("career_boundary_pct") is not None
            else None
        )
        r["six_rate_delta"] = (
            round(r["six_rate"] - r["career_six_rate"], 4)
            if r.get("six_rate") is not None and r.get("career_six_rate") is not None
            else None
        )

    alias = {
        "innings_count": "innings",
        "total_runs": "runs",
        "score_1": "venue_score_acceleration",
        "score_2": "venue_score_power",
        "score_3": "venue_score_control",
    }
    sort_col = alias.get(sort.strip(), sort.strip())
    if not any(sort_col in r for r in all_rows):
        sort_col = "venue_overall_score" if any("venue_overall_score" in r for r in all_rows) else "runs"
    ascending = order.lower() == "asc"

    def _sk(r: dict) -> Any:
        v = r.get(sort_col)
        if v is None:
            return (1, 0)
        return (0, v)

    all_rows.sort(key=_sk, reverse=not ascending)

    total = len(all_rows)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    page_rows = all_rows[start:start + per_page]

    players: list[dict] = []
    for r in page_rows:
        lp = r.get("last_played_at_venue")
        lp_out = safe_str(lp) if lp else None
        if lp_out:
            lp_out = lp_out[:10]
        players.append({
            "id": safe_str(r.get("batter_id")),
            "name": safe_str(r.get("batter")),
            "country": safe_str(r.get("country"), ""),
            "innings": safe_int(r.get("innings")),
            "runs": safe_int(r.get("runs")),
            "balls_faced": safe_int(r.get("balls_faced")),
            "sr": safe_float(r.get("sr")),
            "avg": safe_float(r.get("avg")),
            "dot_pct": safe_float(r.get("dot_pct")),
            "boundary_pct": safe_float(r.get("boundary_pct")),
            "six_rate": safe_float(r.get("six_rate")),
            "fours": safe_int(r.get("fours")),
            "sixes": safe_int(r.get("sixes")),
            "dots": safe_int(r.get("dots")),
            "last_played_at_venue": lp_out,
            "career_sr": safe_float(r.get("career_sr")),
            "career_avg": safe_float(r.get("career_avg")),
            "career_dot_pct": safe_float(r.get("career_dot_pct")),
            "career_boundary_pct": safe_float(r.get("career_boundary_pct")),
            "career_six_rate": safe_float(r.get("career_six_rate")),
            "sr_delta": safe_float(r.get("sr_delta")),
            "avg_delta": safe_float(r.get("avg_delta")),
            "dot_pct_delta": safe_float(r.get("dot_pct_delta")),
            "boundary_pct_delta": safe_float(r.get("boundary_pct_delta")),
            "six_rate_delta": safe_float(r.get("six_rate_delta")),
            "overall_score": safe_float(r.get("career_overall_score")),
            "overall_grade": safe_str(r.get("overall_grade"), "D"),
            "score_acceleration": safe_float(r.get("career_score_acceleration")),
            "score_power": safe_float(r.get("career_score_power")),
            "score_control": safe_float(r.get("career_score_control")),
            "venue_overall_score": safe_float(r.get("venue_overall_score")),
            "venue_score_acceleration": safe_float(r.get("venue_score_acceleration")),
            "venue_score_power": safe_float(r.get("venue_score_power")),
            "venue_score_control": safe_float(r.get("venue_score_control")),
        })

    return {
        "venue": canonical,
        "role": "bat",
        "players": players,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def players_at_venue_bowling(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    venue: str,
    min_innings: int,
    sort: str,
    order: str,
    page: int,
    per_page: int,
    exact: bool,
) -> dict:
    f = safe_fmt(fmt)
    row, canonical = resolve_venue_row(conn, fmt, venue, exact)
    if row is None:
        canonical = venue.strip()

    all_rows = query_all(conn, f"""
        WITH venue_agg AS (
            SELECT
                s.bowler_id,
                ANY_VALUE(s.bowler) AS bowler,
                COUNT(*) AS spells,
                SUM(COALESCE(s.wickets, 0)) AS wickets,
                SUM(COALESCE(s.runs_conceded, 0)) AS runs_conceded,
                SUM(COALESCE(s.legal_balls, 0)) AS legal_balls,
                SUM(COALESCE(s.fours_conceded, 0)) AS fours_conceded,
                SUM(COALESCE(s.sixes_conceded, 0)) AS sixes_conceded,
                SUM(COALESCE(s.dots_bowler, 0)) AS dots_bowler,
                MAX(s.date)::VARCHAR AS last_played_at_venue,
                AVG(TRY_CAST(s.score_accuracy AS DOUBLE)) AS venue_score_accuracy,
                AVG(TRY_CAST(s.score_control AS DOUBLE)) AS venue_score_control,
                AVG(TRY_CAST(s.score_threat AS DOUBLE)) AS venue_score_threat,
                AVG(TRY_CAST(s.overall_score AS DOUBLE)) AS venue_overall_score
            FROM {f}.bowl_spells s
            WHERE LOWER(s.venue) = LOWER(?)
            GROUP BY s.bowler_id
            HAVING COUNT(*) >= ?
        )
        SELECT va.*,
               c.country,
               c.career_economy,
               c.career_sr_bowl,
               c.career_dot_pct,
               c.overall_score AS career_overall_score,
               c.overall_grade,
               c.score_accuracy AS career_score_accuracy,
               c.score_control AS career_score_control,
               c.score_threat AS career_score_threat
        FROM venue_agg va
        LEFT JOIN {f}.bowl_careers c ON va.bowler_id = c.bowler_id
    """, [canonical, min_innings])

    if not all_rows:
        return {
            "venue": canonical,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    for r in all_rows:
        lb = safe_int(r.get("legal_balls"))
        rc = safe_int(r.get("runs_conceded"))
        wk = safe_int(r.get("wickets"))
        db_ = safe_int(r.get("dots_bowler"))
        overs = lb / 6.0
        r["overs_bowled"] = round(overs, 1) if lb > 0 else 0.0
        r["economy"] = round(rc / overs, 2) if overs > 0 else None
        r["strike_rate_bowl"] = round(lb / wk, 1) if wk > 0 else None
        r["dot_pct"] = round(db_ / lb, 4) if lb > 0 else None

        c_econ = r.get("career_economy")
        r["economy_delta"] = round(r["economy"] - float(c_econ), 2) if r["economy"] is not None and c_econ is not None else None
        c_sr = r.get("career_sr_bowl")
        r["strike_rate_delta"] = round(r["strike_rate_bowl"] - float(c_sr), 1) if r["strike_rate_bowl"] is not None and c_sr is not None else None
        c_dp = r.get("career_dot_pct")
        r["dot_pct_delta"] = round(r["dot_pct"] - float(c_dp), 4) if r["dot_pct"] is not None and c_dp is not None else None

    alias = {
        "innings_count": "spells",
        "total_runs": "wickets",
        "score_1": "venue_score_accuracy",
        "score_2": "venue_score_control",
        "score_3": "venue_score_threat",
    }
    sort_col = alias.get(sort.strip(), sort.strip())
    if sort_col == "strike_rate":
        sort_col = "strike_rate_bowl"
    if not any(sort_col in r for r in all_rows):
        sort_col = "venue_overall_score" if any("venue_overall_score" in r for r in all_rows) else "wickets"
    ascending = order.lower() == "asc"

    def _sk(r: dict) -> Any:
        v = r.get(sort_col)
        if v is None:
            return (1, 0)
        return (0, v)

    all_rows.sort(key=_sk, reverse=not ascending)

    total = len(all_rows)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    page_rows = all_rows[start:start + per_page]

    players: list[dict] = []
    for r in page_rows:
        lp = r.get("last_played_at_venue")
        lp_out = safe_str(lp) if lp else None
        if lp_out:
            lp_out = lp_out[:10]
        players.append({
            "id": safe_str(r.get("bowler_id")),
            "name": safe_str(r.get("bowler")),
            "country": safe_str(r.get("country"), ""),
            "spells": safe_int(r.get("spells")),
            "wickets": safe_int(r.get("wickets")),
            "runs_conceded": safe_int(r.get("runs_conceded")),
            "overs_bowled": safe_float(r.get("overs_bowled")),
            "legal_balls": safe_int(r.get("legal_balls")),
            "economy": safe_float(r.get("economy")),
            "strike_rate_bowl": safe_float(r.get("strike_rate_bowl")),
            "dot_pct": safe_float(r.get("dot_pct")),
            "fours_conceded": safe_int(r.get("fours_conceded")),
            "sixes_conceded": safe_int(r.get("sixes_conceded")),
            "last_played_at_venue": lp_out,
            "career_economy": safe_float(r.get("career_economy")),
            "career_sr_bowl": safe_float(r.get("career_sr_bowl")),
            "career_dot_pct": safe_float(r.get("career_dot_pct")),
            "economy_delta": safe_float(r.get("economy_delta")),
            "strike_rate_delta": safe_float(r.get("strike_rate_delta")),
            "dot_pct_delta": safe_float(r.get("dot_pct_delta")),
            "overall_score": safe_float(r.get("career_overall_score")),
            "overall_grade": safe_str(r.get("overall_grade"), "D"),
            "score_accuracy": safe_float(r.get("career_score_accuracy")),
            "score_control": safe_float(r.get("career_score_control")),
            "score_threat": safe_float(r.get("career_score_threat")),
            "venue_overall_score": safe_float(r.get("venue_overall_score")),
            "venue_score_accuracy": safe_float(r.get("venue_score_accuracy")),
            "venue_score_control": safe_float(r.get("venue_score_control")),
            "venue_score_threat": safe_float(r.get("venue_score_threat")),
        })

    return {
        "venue": canonical,
        "role": "bowl",
        "players": players,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }
