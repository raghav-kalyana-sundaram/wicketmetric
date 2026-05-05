from __future__ import annotations

import sqlite3
from typing import Any


def _rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def find_player(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    like = f"%{query}%"
    return conn.execute(
        """
        SELECT *
        FROM players
        WHERE appeared_in_matches = 1
          AND (
            unique_name LIKE ? OR name LIKE ? OR full_name LIKE ?
            OR player_id = ? OR cricinfo_id = ?
          )
        ORDER BY unique_name
        LIMIT 25
        """,
        (like, like, like, query, query),
    ).fetchall()


def player_profile(conn: sqlite3.Connection, player_id: str) -> dict[str, Any]:
    player = conn.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
    if player is None:
        raise ValueError(f"Unknown player_id: {player_id}")

    career = conn.execute(
        """
        SELECT
            m.match_type,
            COUNT(DISTINCT m.match_id) AS matches,
            COUNT(b.player_id) AS innings,
            SUM(CASE WHEN b.not_out = 0 THEN 1 ELSE 0 END) AS dismissals,
            SUM(b.runs) AS runs,
            SUM(b.balls) AS balls,
            SUM(b.fours) AS fours,
            SUM(b.sixes) AS sixes,
            MAX(b.runs) AS high_score,
            SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds,
            SUM(CASE WHEN b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) AS fifties
        FROM batting_innings b
        JOIN matches m ON m.match_id = b.match_id
        WHERE b.player_id = ?
        GROUP BY m.match_type
        ORDER BY m.match_type
        """,
        (player_id,),
    )

    bowling = conn.execute(
        """
        SELECT
            m.match_type,
            COUNT(DISTINCT m.match_id) AS matches,
            COUNT(bo.player_id) AS innings,
            SUM(bo.balls) AS balls,
            SUM(bo.runs) AS runs,
            SUM(bo.wickets) AS wickets,
            SUM(bo.maidens) AS maidens,
            SUM(bo.wides) AS wides,
            SUM(bo.noballs) AS noballs
        FROM bowling_innings bo
        JOIN matches m ON m.match_id = bo.match_id
        WHERE bo.player_id = ?
        GROUP BY m.match_type
        ORDER BY m.match_type
        """,
        (player_id,),
    )

    dismissals = conn.execute(
        """
        SELECT m.match_type, b.dismissal_kind AS kind, COUNT(*) AS dismissals
        FROM batting_innings b
        JOIN matches m ON m.match_id = b.match_id
        WHERE b.player_id = ?
          AND b.dismissal_kind IS NOT NULL
        GROUP BY m.match_type, b.dismissal_kind
        ORDER BY m.match_type, dismissals DESC
        """,
        (player_id,),
    )

    wickets_taken = conn.execute(
        """
        SELECT m.match_type, w.kind, COUNT(*) AS wickets
        FROM wickets w
        JOIN matches m ON m.match_id = w.match_id
        WHERE w.bowler_id = ?
        GROUP BY m.match_type, w.kind
        ORDER BY m.match_type, wickets DESC
        """,
        (player_id,),
    )

    teams = conn.execute(
        """
        SELECT team, COUNT(DISTINCT match_id) AS matches
        FROM match_players
        WHERE player_id = ?
        GROUP BY team
        ORDER BY matches DESC
        """,
        (player_id,),
    ).fetchall()

    batting_rows = []
    for row in career:
        innings = row["innings"] or 0
        outs = row["dismissals"] or 0
        runs = row["runs"] or 0
        balls = row["balls"] or 0
        batting_rows.append(
            {
                **dict(row),
                "average": round(runs / outs, 2) if outs else None,
                "strike_rate": round(100 * runs / balls, 2) if balls else None,
            }
        )

    bowling_rows = []
    for row in bowling:
        wickets = row["wickets"] or 0
        runs = row["runs"] or 0
        balls = row["balls"] or 0
        bowling_rows.append(
            {
                **dict(row),
                "average": round(runs / wickets, 2) if wickets else None,
                "economy": round(6 * runs / balls, 2) if balls else None,
                "strike_rate": round(balls / wickets, 2) if wickets else None,
            }
        )

    return {
        "player": dict(player),
        "teams": [dict(row) for row in teams],
        "batting": batting_rows,
        "bowling": bowling_rows,
        "dismissals": [dict(row) for row in dismissals],
        "wickets_taken": [dict(row) for row in wickets_taken],
    }


def dismissal_leaders(
    conn: sqlite3.Connection,
    kind: str = "lbw",
    match_type: str | None = None,
    limit: int = 25,
    as_bowler: bool = False,
) -> list[dict[str, Any]]:
    params: list[Any] = [kind]
    type_filter = ""
    if match_type:
        type_filter = "AND m.match_type = ?"
        params.append(match_type)
    params.append(limit)
    if as_bowler:
        cur = conn.execute(
            f"""
            SELECT
                p.player_id,
                p.unique_name,
                p.name,
                p.cricinfo_id,
                COUNT(*) AS dismissals,
                SUM(CASE WHEN m.match_type = 'Test' THEN 1 ELSE 0 END) AS tests,
                SUM(CASE WHEN m.match_type = 'ODI' THEN 1 ELSE 0 END) AS odis
            FROM wickets w
            JOIN matches m ON m.match_id = w.match_id
            JOIN players p ON p.player_id = w.bowler_id
            WHERE w.kind = ?
              {type_filter}
            GROUP BY p.player_id
            ORDER BY dismissals DESC, p.unique_name
            LIMIT ?
            """,
            params,
        )
    else:
        cur = conn.execute(
            f"""
            SELECT
                p.player_id,
                p.unique_name,
                p.name,
                p.cricinfo_id,
                COUNT(*) AS dismissals,
                SUM(CASE WHEN m.match_type = 'Test' THEN 1 ELSE 0 END) AS tests,
                SUM(CASE WHEN m.match_type = 'ODI' THEN 1 ELSE 0 END) AS odis
            FROM batting_innings b
            JOIN matches m ON m.match_id = b.match_id
            JOIN players p ON p.player_id = b.player_id
            WHERE b.dismissal_kind = ?
              {type_filter}
            GROUP BY p.player_id
            ORDER BY dismissals DESC, p.unique_name
            LIMIT ?
            """,
            params,
        )
    return _rows(cur)


def dismissal_breakdown(conn: sqlite3.Connection, match_type: str | None = None) -> list[dict[str, Any]]:
    params: list[Any] = []
    type_filter = ""
    if match_type:
        type_filter = "WHERE m.match_type = ?"
        params.append(match_type)
    cur = conn.execute(
        f"""
        SELECT b.dismissal_kind AS kind, COUNT(*) AS dismissals
        FROM batting_innings b
        JOIN matches m ON m.match_id = b.match_id
        {type_filter}
        {"AND" if type_filter else "WHERE"} b.dismissal_kind IS NOT NULL
        GROUP BY b.dismissal_kind
        ORDER BY dismissals DESC
        """,
        params,
    )
    return _rows(cur)


def database_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    matches = conn.execute(
        """
        SELECT match_type, source, COUNT(*) AS matches,
               MIN(start_date) AS first_match, MAX(start_date) AS last_match
        FROM matches
        GROUP BY match_type, source
        ORDER BY match_type, source
        """
    )
    return {
        "matches": [dict(row) for row in matches],
        "players": conn.execute(
            "SELECT COUNT(*) FROM players WHERE appeared_in_matches = 1"
        ).fetchone()[0],
        "deliveries": conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0],
        "wickets": conn.execute("SELECT COUNT(*) FROM wickets").fetchone()[0],
    }
