"""
League-wide team standings from innings-level rows (format-scoped schema).
"""

from __future__ import annotations

import math
from typing import Any

import duckdb

from db import query_all, query_one, safe_float, safe_fmt, safe_int, safe_str
from team_canonicalization import (
    canonical_display,
    canonicalize_rows_by_team,
    variant_keys_lower_for_any_name,
)
from t20i_team_tiers import is_t20_international_format


def _round_pct(v: Any) -> float | None:
    x = safe_float(v)
    if x is None:
        return None
    return round(x, 2)


def _round_runs(v: Any) -> float | None:
    x = safe_float(v)
    if x is None:
        return None
    return round(x, 2)


def build_league_team_standings(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    *,
    min_matches: int = 3,
    sort: str = "win_pct",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
    q: str | None = None,
) -> dict[str, Any]:
    """Aggregate team W/L, win %, and mean first-innings batting total per team for the active format."""
    f = safe_fmt(fmt)
    needle = (q or "").strip()

    if needle:
        sql = f"""
            SELECT batting_team AS team,
                   COUNT(DISTINCT match_id) AS matches,
                   SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS wins,
                   COUNT(DISTINCT match_id)
                     - SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS losses,
                   ROUND(
                       SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) * 100.0
                       / NULLIF(COUNT(DISTINCT match_id), 0), 4
                   ) AS win_pct,
                   ROUND(AVG(total_runs), 4) AS avg_innings_runs
            FROM (
                SELECT DISTINCT match_id, innings_num, batting_team, winner, total_runs
                FROM {f}.bat_innings
                WHERE batting_team IS NOT NULL
                  AND TRIM(CAST(batting_team AS VARCHAR)) != ''
                  AND instr(lower(CAST(batting_team AS VARCHAR)), lower(?)) > 0
            ) t
            GROUP BY batting_team
            HAVING COUNT(DISTINCT match_id) >= ?
        """
        params: list[Any] = [needle, min_matches]
    else:
        sql = f"""
            SELECT batting_team AS team,
                   COUNT(DISTINCT match_id) AS matches,
                   SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS wins,
                   COUNT(DISTINCT match_id)
                     - SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS losses,
                   ROUND(
                       SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) * 100.0
                       / NULLIF(COUNT(DISTINCT match_id), 0), 4
                   ) AS win_pct,
                   ROUND(AVG(total_runs), 4) AS avg_innings_runs
            FROM (
                SELECT DISTINCT match_id, innings_num, batting_team, winner, total_runs
                FROM {f}.bat_innings
                WHERE batting_team IS NOT NULL
                  AND TRIM(CAST(batting_team AS VARCHAR)) != ''
            ) t
            GROUP BY batting_team
            HAVING COUNT(DISTINCT match_id) >= ?
        """
        params = [min_matches]

    all_rows = query_all(conn, sql, params)
    all_rows = canonicalize_rows_by_team(all_rows, team_col="team", fmt=f)

    if not all_rows:
        return {
            "teams": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    sort_col = sort if sort in (
        "team",
        "matches",
        "wins",
        "losses",
        "win_pct",
        "avg_innings_runs",
    ) else "win_pct"
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
    total_pages = max(1, math.ceil(total / per_page)) if per_page > 0 else 1
    start = (page - 1) * per_page
    chunk = all_rows[start:start + per_page]

    return {
        "teams": [
            {
                "team": safe_str(r.get("team")),
                "matches": safe_int(r.get("matches")),
                "wins": safe_int(r.get("wins")),
                "losses": safe_int(r.get("losses")),
                "win_pct": _round_pct(r.get("win_pct")),
                "avg_innings_runs": _round_runs(r.get("avg_innings_runs")),
            }
            for r in chunk
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def list_team_names_chips(conn: duckdb.DuckDBPyConnection, fmt: str) -> list[str]:
    """Distinct sides for the team picker: canonical names; T20I sorted by matches (desc)."""
    f = safe_fmt(fmt)
    rows = query_all(
        conn,
        f"""
        SELECT team_raw, COUNT(DISTINCT match_id) AS cnt
        FROM (
            SELECT DISTINCT
                match_id,
                TRIM(CAST(batting_team AS VARCHAR)) AS team_raw
            FROM {f}.bat_innings
            WHERE batting_team IS NOT NULL
              AND TRIM(CAST(batting_team AS VARCHAR)) != ''
            UNION
            SELECT DISTINCT
                match_id,
                TRIM(CAST(bowling_team AS VARCHAR)) AS team_raw
            FROM {f}.bat_innings
            WHERE bowling_team IS NOT NULL
              AND TRIM(CAST(bowling_team AS VARCHAR)) != ''
        ) u
        WHERE team_raw IS NOT NULL AND team_raw != ''
        GROUP BY team_raw
        """,
    )
    counts: dict[str, int] = {}
    for r in rows:
        raw = safe_str(r.get("team_raw"))
        if not raw:
            continue
        c = canonical_display(raw, f)
        counts[c] = counts.get(c, 0) + safe_int(r.get("cnt"))
    names = list(counts.keys())
    if is_t20_international_format(f):
        names.sort(key=lambda n: (-counts.get(n, 0), n.lower()))
    else:
        names.sort(key=lambda n: n.lower())
    return names


def _match_result_code(
    team: str,
    winner_raw: Any,
    opposition: str | None,
    fmt: str,
) -> str:
    w = canonical_display(safe_str(winner_raw), fmt)
    t = canonical_display(team.strip(), fmt)
    o = canonical_display((opposition or "").strip(), fmt) if opposition else ""
    wl = w.lower()
    tl = t.lower()
    ol = o.lower()
    if not wl:
        return "NR"
    if wl == tl:
        return "W"
    if ol and wl == ol:
        return "L"
    if "tie" in wl:
        return "T"
    return "NR"


def build_team_detail(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    team: str,
    *,
    recent_limit: int = 20,
    squad_bat_limit: int = 14,
    squad_bowl_limit: int = 14,
) -> dict[str, Any] | None:
    """Recent matches with W/L/NR, squad lists, for one team in the active format."""
    team = (team or "").strip()
    if not team:
        return None
    f = safe_fmt(fmt)
    canon = canonical_display(team, f)
    vars_l = variant_keys_lower_for_any_name(team, f)
    if not vars_l:
        return None
    ph = ",".join(["?"] * len(vars_l))
    in_params = list(vars_l)

    exists = query_one(
        conn,
        f"""
        SELECT 1 AS ok FROM {f}.bat_innings
        WHERE LOWER(TRIM(CAST(batting_team AS VARCHAR))) IN ({ph})
           OR LOWER(TRIM(CAST(bowling_team AS VARCHAR))) IN ({ph})
        LIMIT 1
        """,
        in_params + in_params,
    )
    if not exists:
        return None

    q_params = in_params * 4 + [recent_limit]
    recent_rows = query_all(
        conn,
        f"""
        SELECT
            match_id,
            match_date,
            winner,
            opposition,
            venue
        FROM (
            SELECT
                CAST(match_id AS VARCHAR) AS match_id,
                MAX(TRY_CAST(date AS DATE)) AS match_date,
                MAX(CAST(winner AS VARCHAR)) AS winner,
                MAX(CASE
                    WHEN LOWER(TRIM(CAST(batting_team AS VARCHAR))) IN ({ph})
                    THEN TRIM(CAST(bowling_team AS VARCHAR))
                    WHEN LOWER(TRIM(CAST(bowling_team AS VARCHAR))) IN ({ph})
                    THEN TRIM(CAST(batting_team AS VARCHAR))
                END) AS opposition,
                MAX(TRIM(CAST(venue AS VARCHAR))) AS venue
            FROM (
                SELECT DISTINCT
                    match_id, innings_num, date, winner,
                    batting_team, bowling_team, venue
                FROM {f}.bat_innings
            ) d
            WHERE LOWER(TRIM(CAST(batting_team AS VARCHAR))) IN ({ph})
               OR LOWER(TRIM(CAST(bowling_team AS VARCHAR))) IN ({ph})
            GROUP BY match_id
        ) x
        ORDER BY match_date DESC NULLS LAST, match_id DESC
        LIMIT ?
        """,
        q_params,
    )

    recent: list[dict[str, Any]] = []
    for r in recent_rows:
        opp = safe_str(r.get("opposition")) or None
        wraw = r.get("winner")
        recent.append(
            {
                "match_id": safe_str(r.get("match_id")),
                "date": str(r.get("match_date"))[:10]
                if r.get("match_date") is not None
                else None,
                "opposition": opp,
                "result": _match_result_code(canon, wraw, opp, f),
                "venue": safe_str(r.get("venue")) or None,
            }
        )

    bat_squad = query_all(
        conn,
        f"""
        SELECT
            CAST(batter_id AS VARCHAR) AS player_id,
            MAX(CAST(batter AS VARCHAR)) AS player_name,
            COUNT(*) AS innings
        FROM {f}.bat_innings
        WHERE LOWER(TRIM(CAST(batting_team AS VARCHAR))) IN ({ph})
        GROUP BY batter_id
        ORDER BY innings DESC
        LIMIT ?
        """,
        in_params + [squad_bat_limit],
    )

    bowl_squad: list[dict[str, Any]] = []
    try:
        bowl_squad = query_all(
            conn,
            f"""
            SELECT
                CAST(bowler_id AS VARCHAR) AS player_id,
                MAX(CAST(bowler AS VARCHAR)) AS player_name,
                COUNT(*) AS spells
            FROM {f}.bowl_spells
            WHERE LOWER(TRIM(CAST(bowling_team AS VARCHAR))) IN ({ph})
            GROUP BY bowler_id
            ORDER BY spells DESC
            LIMIT ?
            """,
            in_params + [squad_bowl_limit],
        )
    except Exception:
        bowl_squad = []

    return {
        "team": canon,
        "display_name": canon,
        "recent_matches": recent,
        "squad_batters": [
            {
                "player_id": safe_str(x.get("player_id")),
                "player_name": safe_str(x.get("player_name")),
                "innings": safe_int(x.get("innings")),
            }
            for x in bat_squad
        ],
        "squad_bowlers": [
            {
                "player_id": safe_str(x.get("player_id")),
                "player_name": safe_str(x.get("player_name")),
                "spells": safe_int(x.get("spells")),
            }
            for x in bowl_squad
        ],
    }


def build_team_proficient_players(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    team: str,
    *,
    min_team_innings: int = 3,
    min_team_spells: int = 3,
    limit: int = 24,
) -> dict[str, Any] | None:
    """Rank players for this team using career WAR joined to team innings / spells."""
    team = (team or "").strip()
    if not team:
        return None
    f = safe_fmt(fmt)
    canon = canonical_display(team, f)
    vars_l = variant_keys_lower_for_any_name(team, f)
    if not vars_l:
        return None
    ph = ",".join(["?"] * len(vars_l))
    in_params = list(vars_l)

    exists = query_one(
        conn,
        f"""
        SELECT 1 AS ok FROM {f}.bat_innings
        WHERE LOWER(TRIM(CAST(batting_team AS VARCHAR))) IN ({ph})
           OR LOWER(TRIM(CAST(bowling_team AS VARCHAR))) IN ({ph})
        LIMIT 1
        """,
        in_params + in_params,
    )
    if not exists:
        return None

    bat_rows = query_all(
        conn,
        f"""
        SELECT
            CAST(bi.batter_id AS VARCHAR) AS player_id,
            MAX(CAST(bi.batter AS VARCHAR)) AS player_name,
            COUNT(*)::INTEGER AS team_innings,
            MAX(TRY_CAST(bc.war_batting AS DOUBLE)) AS war_batting
        FROM {f}.bat_innings bi
        LEFT JOIN {f}.bat_careers bc
          ON CAST(bi.batter_id AS VARCHAR) = CAST(bc.batter_id AS VARCHAR)
        WHERE LOWER(TRIM(CAST(bi.batting_team AS VARCHAR))) IN ({ph})
        GROUP BY bi.batter_id
        HAVING COUNT(*) >= 1
        """,
        in_params,
    )

    bowl_rows: list[dict[str, Any]] = []
    try:
        bowl_rows = query_all(
            conn,
            f"""
            SELECT
                CAST(bs.bowler_id AS VARCHAR) AS player_id,
                MAX(CAST(bs.bowler AS VARCHAR)) AS player_name,
                COUNT(*)::INTEGER AS team_spells,
                MAX(TRY_CAST(bw.war_bowling AS DOUBLE)) AS war_bowling
            FROM {f}.bowl_spells bs
            LEFT JOIN {f}.bowl_careers bw
              ON CAST(bs.bowler_id AS VARCHAR) = CAST(bw.bowler_id AS VARCHAR)
            WHERE LOWER(TRIM(CAST(bs.bowling_team AS VARCHAR))) IN ({ph})
            GROUP BY bs.bowler_id
            HAVING COUNT(*) >= 1
            """,
            in_params,
        )
    except Exception:
        bowl_rows = []

    by_id: dict[str, dict[str, Any]] = {}
    for r in bat_rows:
        pid = safe_str(r.get("player_id"))
        if not pid:
            continue
        by_id[pid] = {
            "player_id": pid,
            "player_name": safe_str(r.get("player_name")),
            "team_innings": safe_int(r.get("team_innings")),
            "team_spells": 0,
            "war_batting": safe_float(r.get("war_batting")),
            "war_bowling": None,
        }
    for r in bowl_rows:
        pid = safe_str(r.get("player_id"))
        if not pid:
            continue
        wb = safe_float(r.get("war_bowling"))
        if pid in by_id:
            by_id[pid]["team_spells"] = safe_int(r.get("team_spells"))
            by_id[pid]["war_bowling"] = wb
            if safe_str(r.get("player_name")):
                by_id[pid]["player_name"] = safe_str(r.get("player_name"))
        else:
            by_id[pid] = {
                "player_id": pid,
                "player_name": safe_str(r.get("player_name")),
                "team_innings": 0,
                "team_spells": safe_int(r.get("team_spells")),
                "war_batting": None,
                "war_bowling": wb,
            }

    out_rows: list[dict[str, Any]] = []
    for rec in by_id.values():
        inn = int(rec.get("team_innings") or 0)
        spl = int(rec.get("team_spells") or 0)
        wbat = rec.get("war_batting")
        wbowl = rec.get("war_bowling")
        wb_f = float(wbat) if wbat is not None else 0.0
        wl_f = float(wbowl) if wbowl is not None else 0.0

        batting_signal = inn >= min_team_innings and wb_f > 0
        bowling_signal = spl >= min_team_spells and wl_f > 0

        if batting_signal and bowling_signal:
            role = "allrounder"
            prof = (wb_f + wl_f) / 2.0
        elif batting_signal and not bowling_signal:
            role = "batter"
            prof = wb_f
        elif bowling_signal and not batting_signal:
            role = "bowler"
            prof = wl_f
        elif inn >= min_team_innings and wb_f > 0:
            role = "batter"
            prof = wb_f
        elif spl >= min_team_spells and wl_f > 0:
            role = "bowler"
            prof = wl_f
        else:
            continue

        out_rows.append({
            "player_id": rec["player_id"],
            "player_name": rec["player_name"],
            "role": role,
            "proficiency_score": round(prof, 4) if prof is not None else None,
            "war_batting": wbat,
            "war_bowling": wbowl,
            "team_innings": inn,
            "team_spells": spl,
        })

    def _sort_key(x: dict[str, Any]) -> tuple:
        p = x.get("proficiency_score")
        if p is None:
            return (0, 0.0, "")
        return (1, float(p), str(x.get("player_name") or ""))

    out_rows.sort(key=_sort_key, reverse=True)
    out_rows = out_rows[:limit]

    return {"team": canon, "players": out_rows}


def _bat_innings_columns(conn: duckdb.DuckDBPyConnection, fmt: str) -> set[str]:
    f = safe_fmt(fmt)
    res = conn.execute(f"SELECT * FROM {f}.bat_innings LIMIT 0")
    return {str(d[0]).lower() for d in res.description}


def build_team_composition_series(
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
    team: str,
    *,
    limit: int = 40,
) -> dict[str, Any] | None:
    """Per-innings stacked composition for batting (runs) and bowling (wickets) for charting."""
    team = (team or "").strip()
    if not team:
        return None
    f = safe_fmt(fmt)
    canon = canonical_display(team, f)
    vars_l = variant_keys_lower_for_any_name(team, f)
    if not vars_l:
        return None
    ph = ",".join(["?"] * len(vars_l))
    in_params = list(vars_l)

    exists = query_one(
        conn,
        f"""
        SELECT 1 AS ok FROM {f}.bat_innings
        WHERE LOWER(TRIM(CAST(batting_team AS VARCHAR))) IN ({ph})
           OR LOWER(TRIM(CAST(bowling_team AS VARCHAR))) IN ({ph})
        LIMIT 1
        """,
        in_params + in_params,
    )
    if not exists:
        return None

    cols = _bat_innings_columns(conn, f)
    if "runs" in cols and "runs_scored" in cols:
        run_sql = "SUM(TRY_CAST(COALESCE(runs, runs_scored, 0) AS BIGINT))"
    elif "runs" in cols:
        run_sql = "SUM(COALESCE(TRY_CAST(runs AS BIGINT), 0))"
    elif "runs_scored" in cols:
        run_sql = "SUM(COALESCE(TRY_CAST(runs_scored AS BIGINT), 0))"
    else:
        run_sql = "0::BIGINT"

    six_sql = (
        "SUM(6 * COALESCE(TRY_CAST(sixes AS BIGINT), 0))"
        if "sixes" in cols
        else "0::BIGINT"
    )
    four_sql = (
        "SUM(4 * COALESCE(TRY_CAST(fours AS BIGINT), 0))"
        if "fours" in cols
        else "0::BIGINT"
    )
    ones_cnt = (
        "SUM(COALESCE(TRY_CAST(ones AS BIGINT), 0))"
        if "ones" in cols
        else "0::BIGINT"
    )
    twos_cnt = (
        "SUM(COALESCE(TRY_CAST(twos AS BIGINT), 0))"
        if "twos" in cols
        else "0::BIGINT"
    )
    threes_cnt = (
        "SUM(COALESCE(TRY_CAST(threes AS BIGINT), 0))"
        if "threes" in cols
        else "0::BIGINT"
    )

    inn_runs_sql = (
        "MAX(COALESCE(TRY_CAST(total_runs AS BIGINT), 0))"
        if "total_runs" in cols
        else "0::BIGINT"
    )

    bat_rows = query_all(
        conn,
        f"""
        SELECT * FROM (
            SELECT
                CAST(match_id AS VARCHAR) AS match_id,
                TRY_CAST(innings_num AS INTEGER) AS innings_num,
                MAX(TRY_CAST(date AS DATE)) AS dt,
                {inn_runs_sql} AS inn_runs,
                {run_sql} AS bat_runs,
                {six_sql} AS r_sixes,
                {four_sql} AS r_fours,
                {ones_cnt} AS cnt_ones,
                {twos_cnt} AS cnt_twos,
                {threes_cnt} AS cnt_threes
            FROM {f}.bat_innings
            WHERE LOWER(TRIM(CAST(batting_team AS VARCHAR))) IN ({ph})
            GROUP BY match_id, innings_num
        ) s
        ORDER BY s.dt DESC NULLS LAST, s.match_id DESC, s.innings_num DESC
        LIMIT ?
        """,
        in_params + [limit],
    )

    singles_breakdown = (
        "ones" in cols and "twos" in cols and "threes" in cols
    )

    batting: list[dict[str, Any]] = []
    for r in reversed(bat_rows):
        dt = r.get("dt")
        date_s = str(dt)[:10] if dt is not None else None
        inn_runs = safe_int(r.get("inn_runs"))
        bat_runs = safe_int(r.get("bat_runs"))
        r6 = safe_int(r.get("r_sixes"))
        r4 = safe_int(r.get("r_fours"))
        c1 = safe_int(r.get("cnt_ones"))
        c2 = safe_int(r.get("cnt_twos"))
        c3 = safe_int(r.get("cnt_threes"))
        r1 = c1
        r2 = c2 * 2
        r3 = c3 * 3
        rest = bat_runs - r6 - r4 - r1 - r2 - r3
        if rest < 0:
            rest = 0
        extras = inn_runs - bat_runs if inn_runs > 0 else 0
        if extras < 0:
            extras = 0
        total = inn_runs if inn_runs > 0 else bat_runs + extras
        if total <= 0:
            continue
        shares = {
            "sixes": r6 / total,
            "fours": r4 / total,
            "threes": r3 / total,
            "twos": r2 / total,
            "ones": r1 / total,
            "running": rest / total,
            "extras": extras / total,
        }
        s = sum(shares.values())
        if s > 0 and abs(s - 1.0) > 1e-6:
            shares = {k: v / s for k, v in shares.items()}
        inn_num = safe_int(r.get("innings_num")) or 1
        label = (date_s or "?") + (f" ·{inn_num}i" if inn_num != 1 else "")
        batting.append(
            {
                "match_id": safe_str(r.get("match_id")),
                "innings_num": inn_num,
                "date": date_s,
                "label": label,
                "total_runs": inn_runs if inn_runs > 0 else None,
                "share_sixes": round(shares["sixes"], 4),
                "share_fours": round(shares["fours"], 4),
                "share_threes": round(shares["threes"], 4),
                "share_twos": round(shares["twos"], 4),
                "share_ones": round(shares["ones"], 4),
                "share_running": round(shares["running"], 4),
                "share_extras": round(shares["extras"], 4),
            }
        )

    is_out_sql = "COALESCE(TRY_CAST(is_out AS BOOLEAN), false)"
    if "is_out" not in cols:
        if "how_out" in cols:
            is_out_sql = (
                "(how_out IS NOT NULL AND TRIM(CAST(how_out AS VARCHAR)) != '')"
            )
        else:
            is_out_sql = "false"

    ho = "LOWER(TRIM(CAST(how_out AS VARCHAR)))"
    bowl_rows: list[dict[str, Any]] = []
    if "how_out" in cols or "is_out" in cols:
        bowl_rows = query_all(
            conn,
            f"""
            SELECT * FROM (
                SELECT
                    CAST(match_id AS VARCHAR) AS match_id,
                    TRY_CAST(innings_num AS INTEGER) AS innings_num,
                    MAX(TRY_CAST(date AS DATE)) AS dt,
                    SUM(CASE WHEN {is_out_sql} THEN 1 ELSE 0 END)::BIGINT AS wk,
                    SUM(CASE WHEN {is_out_sql} AND (
                        {ho} LIKE 'run out%' OR {ho} LIKE 'retired out%'
                    ) THEN 1 ELSE 0 END)::BIGINT AS w_run_out,
                    SUM(CASE WHEN {is_out_sql} AND ({ho} LIKE 'stump%') THEN 1 ELSE 0 END)::BIGINT AS w_stumped,
                    SUM(CASE WHEN {is_out_sql} AND (
                        {ho} = 'lbw' OR {ho} LIKE 'lbw %'
                    ) THEN 1 ELSE 0 END)::BIGINT AS w_lbw,
                    SUM(CASE WHEN {is_out_sql} AND (
                        {ho} LIKE 'caught and bowled%' OR {ho} LIKE 'bowled%' OR {ho} LIKE 'hit wicket%'
                    ) THEN 1 ELSE 0 END)::BIGINT AS w_bowled,
                    SUM(CASE WHEN {is_out_sql} AND (
                        {ho} LIKE 'caught%' AND {ho} NOT LIKE 'caught and bowled%'
                    ) THEN 1 ELSE 0 END)::BIGINT AS w_caught
                FROM {f}.bat_innings
                WHERE LOWER(TRIM(CAST(bowling_team AS VARCHAR))) IN ({ph})
                GROUP BY match_id, innings_num
            ) s
            WHERE s.wk > 0
            ORDER BY s.dt DESC NULLS LAST, s.match_id DESC, s.innings_num DESC
            LIMIT ?
            """,
            in_params + [limit],
        )

    bowling_out: list[dict[str, Any]] = []
    for r in reversed(bowl_rows):
        dt = r.get("dt")
        date_s = str(dt)[:10] if dt is not None else None
        wk = safe_int(r.get("wk"))
        if wk <= 0:
            continue
        w_ro = safe_int(r.get("w_run_out"))
        w_st = safe_int(r.get("w_stumped"))
        w_lb = safe_int(r.get("w_lbw"))
        w_bo = safe_int(r.get("w_bowled"))
        w_ca = safe_int(r.get("w_caught"))
        typed = w_ro + w_st + w_lb + w_bo + w_ca
        w_ot = max(0, wk - typed)
        shares_b = {
            "bowled": w_bo / wk,
            "caught": w_ca / wk,
            "lbw": w_lb / wk,
            "run_out": w_ro / wk,
            "stumped": w_st / wk,
            "other": w_ot / wk,
        }
        sb = sum(shares_b.values())
        if sb > 0 and abs(sb - 1.0) > 1e-6:
            shares_b = {k: v / sb for k, v in shares_b.items()}
        inn_num = safe_int(r.get("innings_num")) or 1
        label = (date_s or "?") + (f" ·{inn_num}i" if inn_num != 1 else "")
        bowling_out.append(
            {
                "match_id": safe_str(r.get("match_id")),
                "innings_num": inn_num,
                "date": date_s,
                "label": label,
                "wickets": wk,
                "share_bowled": round(shares_b["bowled"], 4),
                "share_caught": round(shares_b["caught"], 4),
                "share_lbw": round(shares_b["lbw"], 4),
                "share_run_out": round(shares_b["run_out"], 4),
                "share_stumped": round(shares_b["stumped"], 4),
                "share_other": round(shares_b["other"], 4),
            }
        )

    return {
        "team": canon,
        "batting_singles_breakdown": singles_breakdown,
        "batting": batting,
        "bowling": bowling_out,
    }
