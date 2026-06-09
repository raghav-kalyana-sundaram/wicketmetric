"""Record books, ground pages, and team records — the browse-first cuts a fan asks for.

Everything here reads the same Parquet lines the rest of the warehouse uses. Records are
"in this warehouse": men's Tests from 1877 and ODIs from 1971 come from Cricinfo
scorecards where Cricsheet has no file (no ball-by-ball on those matches), and
Cricsheet covers the ball-by-ball era plus the listed T20 leagues. Fastest
fifties/hundreds still need deliveries.
"""

from __future__ import annotations

from typing import Any

from cricwarehouse.competitions import LABELS
from cricwarehouse.teams import wtc_match_sql, wtc_params
from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.app.query import resolve_team

RECORD_KINDS = (
    "high_scores",
    "best_bowling",
    "partnerships",
    "team_totals",
    "low_totals",
    "most_sixes",
    "fast_hundreds",
    "fast_fifties",
    "big_wins",
    "carried_bat",
    "ducks",
)

RECORD_ALIASES = {
    "fastest_hundreds": "fast_hundreds",
    "fastest_fifties": "fast_fifties",
    "highest_sr": "carried_bat",
    "strike_rates": "carried_bat",
}

RECORD_LABELS = {
    "high_scores": "Highest individual scores",
    "best_bowling": "Best bowling in an innings",
    "partnerships": "Biggest partnerships",
    "team_totals": "Highest team totals",
    "low_totals": "Lowest all-out totals",
    "most_sixes": "Most sixes in an innings",
    "fast_hundreds": "Fastest hundreds",
    "fast_fifties": "Fastest fifties",
    "big_wins": "Biggest winning margins",
    "carried_bat": "Highest strike rates",
    "ducks": "Ducks, fewest balls first",
}

RECORD_BLURBS = {
    "high_scores": "One batter, one innings. Not-outs carry a star.",
    "best_bowling": "Wickets first, then fewest runs conceded.",
    "partnerships": "Runs while both were at the crease, any wicket.",
    "team_totals": "Completed innings totals, super overs excluded.",
    "low_totals": "All out only — rain-shortened innings are not records.",
    "most_sixes": "Sixes in a single innings.",
    "fast_hundreds": "Balls faced when the hundred came up.",
    "fast_fifties": "Balls faced when the fifty came up.",
    "big_wins": "Runs margin, or wickets in hand at the finish.",
    "carried_bat": "Strike rate in innings of at least 20 balls.",
    "ducks": "Dismissed for 0, fewest balls first.",
}


def _gate(con, *, comp: str | None, gender: str | None, wtc: bool, alias: str = "m"):
    """Shared WHERE fragments so every record list is filtered the same way."""
    clauses: list[str] = []
    params: list[Any] = []
    comps = _comp_list(comp)
    if comps:
        marks = ", ".join("?" for _ in comps)
        clauses.append(f"{alias}.competition IN ({marks})")
        params.extend(comps)
    if gender in {"male", "female"}:
        clauses.append(f"{alias}.gender = ?")
        params.append(gender)
    if wtc:
        con.execute("CREATE TEMP TABLE IF NOT EXISTS wtc_teams (team VARCHAR)")
        if not con.execute("SELECT COUNT(*) FROM wtc_teams").fetchone()[0]:
            for t in wtc_params(gender):
                con.execute("INSERT INTO wtc_teams VALUES (?)", [t])
        clauses.append(wtc_match_sql(alias))
    return (" AND ".join(clauses) or "1=1"), params


def _comp_list(comp: str | None) -> list[str]:
    if not comp:
        return []
    key = comp.strip().lower()
    if key in {"", "all"}:
        return []
    if key == "t20":
        return ["t20i", "ipl", "wpl", "bbl", "wbbl"]
    if key == "internationals":
        return ["test", "odi", "t20i"]
    if key == "leagues":
        return ["ipl", "wpl", "bbl", "wbbl"]
    if "," in key:
        return [c.strip() for c in key.split(",") if c.strip()]
    return [key]


def _rows(con, sql: str, params: list[Any]) -> list[dict]:
    try:
        df = con.execute(sql, params).fetchdf()
    except Exception:
        return []
    if df.empty:
        return []
    return _clean(df.to_dict("records"))


def _clean(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        item = {}
        for k, v in r.items():
            if v is None:
                item[k] = None
            elif hasattr(v, "item"):
                try:
                    n = v.item()
                    item[k] = None if n != n else n
                except Exception:
                    item[k] = str(v)
            elif isinstance(v, float) and v != v:
                item[k] = None
            else:
                item[k] = v
        if item.get("competition"):
            item["comp"] = LABELS.get(item["competition"], item["competition"])
        out.append(item)
    return out


def records(
    *,
    kind: str = "high_scores",
    comp: str | None = None,
    gender: str | None = "male",
    wtc: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    if not warehouse_ready():
        return {"rows": [], "kind": kind, "kinds": _kind_menu()}
    kind = RECORD_ALIASES.get(kind, kind)
    kind = kind if kind in RECORD_KINDS else "high_scores"
    n = max(min(int(limit), 200), 1)
    con = connect()
    try:
        where, params = _gate(con, comp=comp, gender=gender, wtc=wtc)
        rows = _RECORD_QUERIES[kind](con, where, params, n)
        return {
            "rows": rows,
            "kind": kind,
            "kinds": _kind_menu(),
            "label": RECORD_LABELS[kind],
            "blurb": RECORD_BLURBS[kind],
            "scope": _scope_line(comp, gender, wtc, len(rows)),
        }
    finally:
        con.close()


def _kind_menu() -> list[dict]:
    return [{"id": k, "label": RECORD_LABELS[k]} for k in RECORD_KINDS]


def _scope_line(comp: str | None, gender: str | None, wtc: bool, n: int) -> str:
    comps = _comp_list(comp)
    bits = [
        ", ".join(LABELS.get(c, c) for c in comps) if comps else "All competitions",
        {"male": "Men", "female": "Women"}.get(gender or "", "All"),
        "WTC sides only" if wtc else "",
        f"{n} rows",
        "in this warehouse",
    ]
    return " · ".join(b for b in bits if b)


def _q_high_scores(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT b.runs, b.balls, b.not_out, b.fours, b.sixes, b.match_id, b.team,
               p.display_name, p.slug, m.start_date, m.competition, m.venue,
               CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               CASE WHEN b.not_out THEN b.runs || '*' ELSE CAST(b.runs AS VARCHAR) END AS runs_display,
               CASE WHEN b.balls > 0 THEN ROUND(b.runs * 100.0 / b.balls, 1) END AS sr
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        JOIN people p ON p.person_id = b.person_id
        WHERE b.innings_kind = 'regular' AND {where}
        ORDER BY b.runs DESC, b.balls ASC
        LIMIT ?
        """,
        [*params, n],
    )


def _q_best_bowling(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT bl.wickets, bl.runs, bl.legal_balls, bl.maidens, bl.match_id, bl.team,
               p.display_name, p.slug, m.start_date, m.competition, m.venue,
               CASE WHEN bl.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               bl.wickets || '/' || bl.runs AS figures,
               (bl.legal_balls // 6) || '.' || (bl.legal_balls % 6) AS overs,
               CASE WHEN bl.legal_balls > 0 THEN ROUND(bl.runs * 6.0 / bl.legal_balls, 2) END AS econ
        FROM bowling_lines bl
        JOIN matches m ON m.match_id = bl.match_id
        JOIN people p ON p.person_id = bl.person_id
        WHERE bl.innings_kind = 'regular' AND bl.wickets >= 4 AND {where}
        ORDER BY bl.wickets DESC, bl.runs ASC
        LIMIT ?
        """,
        [*params, n],
    )


def _q_partnerships(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT pr.runs, pr.balls, pr.wicket_number, pr.match_id,
               p1.display_name AS name_1, p1.slug AS slug_1,
               p2.display_name AS name_2, p2.slug AS slug_2,
               p1.display_name || ' / ' || p2.display_name AS pair,
               m.start_date, m.competition, m.venue,
               i.batting_team AS team,
               CASE WHEN i.batting_team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition
        FROM partnerships pr
        JOIN matches m ON m.match_id = pr.match_id
        JOIN people p1 ON p1.person_id = pr.person_id_1
        JOIN people p2 ON p2.person_id = pr.person_id_2
        LEFT JOIN innings i ON i.match_id = pr.match_id AND i.innings = pr.innings
                           AND i.innings_kind = pr.innings_kind
        WHERE pr.innings_kind = 'regular' AND {where}
        ORDER BY pr.runs DESC
        LIMIT ?
        """,
        [*params, n],
    )


def _q_team_totals(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT i.runs, i.wickets, i.legal_balls, i.match_id, i.batting_team AS team,
               i.bowling_team AS opposition, m.start_date, m.competition, m.venue,
               i.runs || '/' || i.wickets AS total,
               (i.legal_balls // 6) || '.' || (i.legal_balls % 6) AS overs,
               CASE WHEN i.legal_balls > 0 THEN ROUND(i.runs * 6.0 / i.legal_balls, 2) END AS rr
        FROM innings i
        JOIN matches m ON m.match_id = i.match_id
        WHERE i.innings_kind = 'regular' AND {where}
        ORDER BY i.runs DESC
        LIMIT ?
        """,
        [*params, n],
    )


def _q_low_totals(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT i.runs, i.wickets, i.legal_balls, i.match_id, i.batting_team AS team,
               i.bowling_team AS opposition, m.start_date, m.competition, m.venue,
               i.runs || '/' || i.wickets AS total,
               (i.legal_balls // 6) || '.' || (i.legal_balls % 6) AS overs
        FROM innings i
        JOIN matches m ON m.match_id = i.match_id
        WHERE i.innings_kind = 'regular' AND i.all_out AND {where}
        ORDER BY i.runs ASC
        LIMIT ?
        """,
        [*params, n],
    )


def _q_most_sixes(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT b.sixes, b.fours, b.runs, b.balls, b.not_out, b.match_id, b.team,
               p.display_name, p.slug, m.start_date, m.competition, m.venue,
               CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               CASE WHEN b.not_out THEN b.runs || '*' ELSE CAST(b.runs AS VARCHAR) END AS runs_display,
               CASE WHEN b.balls > 0 THEN ROUND(b.runs * 100.0 / b.balls, 1) END AS sr
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        JOIN people p ON p.person_id = b.person_id
        WHERE b.innings_kind = 'regular' AND b.sixes >= 4 AND {where}
        ORDER BY b.sixes DESC, b.balls ASC
        LIMIT ?
        """,
        [*params, n],
    )


def _fast_milestone(con, where, params, n, target: int):
    """Balls faced when the batter reached the milestone, from ball-by-ball rows."""
    return _rows(
        con,
        f"""
        WITH faced AS (
          SELECT d.match_id, d.innings, d.innings_kind, d.striker,
                 d.runs_batter,
                 SUM(d.runs_batter) OVER w AS runs_so_far,
                 SUM(CASE WHEN d.is_legal OR d.is_noball THEN 1 ELSE 0 END) OVER w AS balls_so_far
          FROM deliveries d
          WHERE d.innings_kind = 'regular'
          WINDOW w AS (
            PARTITION BY d.match_id, d.innings, d.striker
            ORDER BY d.over, d.ball_in_over
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ), reached AS (
          SELECT match_id, innings, striker, CAST(MIN(balls_so_far) AS INTEGER) AS balls_to
          FROM faced
          WHERE runs_so_far >= ?
          GROUP BY 1,2,3
        )
        SELECT r.balls_to, b.runs, b.balls, b.not_out, b.fours, b.sixes, b.match_id, b.team,
               p.display_name, p.slug, m.start_date, m.competition, m.venue,
               CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               CASE WHEN b.not_out THEN b.runs || '*' ELSE CAST(b.runs AS VARCHAR) END AS runs_display
        FROM reached r
        JOIN batting_lines b ON b.match_id = r.match_id AND b.innings = r.innings
                            AND b.person_id = r.striker AND b.innings_kind = 'regular'
        JOIN matches m ON m.match_id = r.match_id
        JOIN people p ON p.person_id = r.striker
        WHERE {where}
        ORDER BY r.balls_to ASC, b.runs DESC
        LIMIT ?
        """,
        [target, *params, n],
    )


def _q_fast_hundreds(con, where, params, n):
    return _fast_milestone(con, where, params, n, 100)


def _q_fast_fifties(con, where, params, n):
    return _fast_milestone(con, where, params, n, 50)


def _q_big_wins(con, where, params, n):
    half = max(n // 2, 1)
    by_runs = _rows(
        con,
        f"""
        SELECT m.match_id, m.start_date, m.competition, m.venue, m.winner,
               m.team_home, m.team_away, m.win_by_runs, m.win_by_wickets,
               m.team_home || ' v ' || m.team_away AS fixture,
               CASE WHEN m.team_home = m.winner THEN m.team_away ELSE m.team_home END AS loser,
               COALESCE(m.win_by_runs, 0) AS margin_runs,
               COALESCE(m.win_by_wickets, 0) AS margin_wickets,
               m.win_by_runs || ' runs' AS margin
        FROM matches m
        WHERE m.winner IS NOT NULL AND m.win_by_runs IS NOT NULL AND {where}
        ORDER BY m.win_by_runs DESC
        LIMIT ?
        """,
        [*params, half],
    )
    by_wkts = _rows(
        con,
        f"""
        SELECT m.match_id, m.start_date, m.competition, m.venue, m.winner,
               m.team_home, m.team_away, m.win_by_runs, m.win_by_wickets,
               m.team_home || ' v ' || m.team_away AS fixture,
               CASE WHEN m.team_home = m.winner THEN m.team_away ELSE m.team_home END AS loser,
               COALESCE(m.win_by_runs, 0) AS margin_runs,
               COALESCE(m.win_by_wickets, 0) AS margin_wickets,
               m.win_by_wickets || ' wickets' AS margin
        FROM matches m
        WHERE m.winner IS NOT NULL AND m.win_by_wickets IS NOT NULL AND {where}
        ORDER BY m.win_by_wickets DESC
        LIMIT ?
        """,
        [*params, n - half],
    )
    seen = set()
    out = []
    for row in by_runs + by_wkts:
        mid = row.get("match_id")
        if mid in seen:
            continue
        seen.add(mid)
        out.append(row)
    return out[:n]


def _q_carried_bat(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT ROUND(b.runs * 100.0 / b.balls, 1) AS sr,
               b.runs, b.balls, b.not_out, b.fours, b.sixes, b.match_id, b.team,
               p.display_name, p.slug, m.start_date, m.competition, m.venue,
               CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               CASE WHEN b.not_out THEN b.runs || '*' ELSE CAST(b.runs AS VARCHAR) END AS runs_display
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        JOIN people p ON p.person_id = b.person_id
        WHERE b.innings_kind = 'regular' AND b.balls >= 20 AND {where}
        ORDER BY sr DESC, b.runs DESC
        LIMIT ?
        """,
        [*params, n],
    )


def _q_ducks(con, where, params, n):
    return _rows(
        con,
        f"""
        SELECT b.runs, b.balls, b.not_out, b.fours, b.sixes, b.match_id, b.team,
               p.display_name, p.slug, m.start_date, m.competition, m.venue,
               CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               '0' AS runs_display,
               CASE WHEN b.balls > 0 THEN ROUND(b.runs * 100.0 / b.balls, 1) END AS sr
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        JOIN people p ON p.person_id = b.person_id
        WHERE b.innings_kind = 'regular' AND b.runs = 0 AND NOT b.not_out AND {where}
        ORDER BY b.balls ASC, m.start_date DESC
        LIMIT ?
        """,
        [*params, n],
    )


_RECORD_QUERIES = {
    "high_scores": _q_high_scores,
    "best_bowling": _q_best_bowling,
    "partnerships": _q_partnerships,
    "team_totals": _q_team_totals,
    "low_totals": _q_low_totals,
    "most_sixes": _q_most_sixes,
    "fast_hundreds": _q_fast_hundreds,
    "fast_fifties": _q_fast_fifties,
    "big_wins": _q_big_wins,
    "carried_bat": _q_carried_bat,
    "ducks": _q_ducks,
}


def venue_list(q: str = "", limit: int = 40) -> dict[str, Any]:
    if not warehouse_ready():
        return {"venues": []}
    con = connect()
    try:
        needle = f"%{(q or '').lower()}%"
        rows = _rows(
            con,
            """
            SELECT venue, city, COUNT(*) AS matches,
                   MIN(start_date) AS first_date, MAX(start_date) AS last_date
            FROM matches
            WHERE venue IS NOT NULL AND lower(venue) LIKE ?
            GROUP BY 1,2
            ORDER BY matches DESC
            LIMIT ?
            """,
            [needle, max(int(limit), 1)],
        )
        for r in rows:
            r["range"] = f"{str(r.get('first_date') or '')[:4]}–{str(r.get('last_date') or '')[:4]}"
            # Canonical venue names carry the city; drop it where the table
            # already shows a City column of its own.
            name = str(r.get("venue") or "")
            city = str(r.get("city") or "")
            r["ground"] = (
                name[: -(len(city) + 2)].strip()
                if city and name.lower().endswith(f", {city.lower()}")
                else name
            )
        return {"venues": rows}
    finally:
        con.close()


def venue(*, name: str, comp: str | None = None, gender: str | None = None) -> dict[str, Any]:
    """A ground page: does it favour the chase, and who has runs and wickets here."""
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built yet."}
    con = connect()
    try:
        resolved = con.execute(
            """
            SELECT venue, city, COUNT(*) AS n FROM matches
            WHERE lower(venue) = lower(?) OR lower(venue) LIKE lower(?)
            GROUP BY 1,2 ORDER BY n DESC LIMIT 1
            """,
            [name, f"%{name}%"],
        ).fetchone()
        if not resolved:
            return {"ok": False, "error": f"No ground matching “{name}”."}
        ground, city = resolved[0], resolved[1]
        where, params = _gate(con, comp=comp, gender=gender, wtc=False)
        base = f"m.venue = ? AND {where}"
        args = [ground, *params]
        head = con.execute(
            f"""
            SELECT COUNT(*) AS matches,
                   MIN(m.start_date) AS first_date, MAX(m.start_date) AS last_date,
                   SUM(CASE WHEN m.toss_decision = 'bat' THEN 1 ELSE 0 END) AS chose_bat,
                   SUM(CASE WHEN m.toss_decision = 'field' THEN 1 ELSE 0 END) AS chose_field,
                   SUM(CASE WHEN m.winner IS NULL THEN 1 ELSE 0 END) AS no_result,
                   SUM(CASE WHEN m.winner IS NOT NULL AND m.win_by_runs IS NOT NULL THEN 1 ELSE 0 END) AS won_defending,
                   SUM(CASE WHEN m.winner IS NOT NULL AND m.win_by_wickets IS NOT NULL THEN 1 ELSE 0 END) AS won_chasing
            FROM matches m WHERE {base}
            """,
            args,
        ).fetchone()
        first_inns = con.execute(
            f"""
            SELECT ROUND(AVG(i.runs), 1) AS avg_first,
                   MAX(i.runs) AS max_first, MIN(i.runs) AS min_first,
                   ROUND(AVG(CASE WHEN i.legal_balls > 0 THEN i.runs * 6.0 / i.legal_balls END), 2) AS avg_rr
            FROM innings i JOIN matches m ON m.match_id = i.match_id
            WHERE i.innings = 1 AND i.innings_kind = 'regular' AND {base}
            """,
            args,
        ).fetchone()
        by_comp = _rows(
            con,
            f"""
            SELECT m.competition, COUNT(*) AS matches,
                   MIN(m.start_date) AS first_date, MAX(m.start_date) AS last_date
            FROM matches m WHERE {base}
            GROUP BY 1 ORDER BY matches DESC
            """,
            args,
        )
        top_bat = _rows(
            con,
            f"""
            SELECT p.display_name AS player, p.slug,
                   COUNT(*) AS inns, SUM(b.runs) AS runs, MAX(b.runs) AS hs,
                   SUM(b.balls) AS balls,
                   SUM(CASE WHEN b.not_out THEN 0 ELSE 1 END) AS outs,
                   SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds,
                   SUM(CASE WHEN b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) AS fifties
            FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            JOIN people p ON p.person_id = b.person_id
            WHERE b.innings_kind = 'regular' AND {base}
            GROUP BY 1,2
            HAVING COUNT(*) >= 3
            ORDER BY runs DESC
            LIMIT 15
            """,
            args,
        )
        for r in top_bat:
            outs = int(r.get("outs") or 0)
            balls = int(r.get("balls") or 0)
            r["avg"] = round(int(r.get("runs") or 0) / outs, 1) if outs else None
            r["sr"] = round(int(r.get("runs") or 0) * 100 / balls, 1) if balls else None
        top_bowl = _rows(
            con,
            f"""
            SELECT p.display_name AS player, p.slug,
                   COUNT(*) AS inns, SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
                   SUM(bl.legal_balls) AS legal_balls, MAX(bl.wickets) AS best
            FROM bowling_lines bl
            JOIN matches m ON m.match_id = bl.match_id
            JOIN people p ON p.person_id = bl.person_id
            WHERE bl.innings_kind = 'regular' AND {base}
            GROUP BY 1,2
            HAVING SUM(bl.legal_balls) >= 60
            ORDER BY wickets DESC
            LIMIT 15
            """,
            args,
        )
        for r in top_bowl:
            wk = int(r.get("wickets") or 0)
            balls = int(r.get("legal_balls") or 0)
            r["avg"] = round(int(r.get("runs") or 0) / wk, 1) if wk else None
            r["econ"] = round(int(r.get("runs") or 0) * 6 / balls, 2) if balls else None
            r["overs"] = f"{balls // 6}.{balls % 6}"
        recent = _rows(
            con,
            f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner, m.competition,
                   m.win_by_runs, m.win_by_wickets, m.win_by_innings, m.event_name
            FROM matches m WHERE {base}
            ORDER BY m.start_date DESC LIMIT 20
            """,
            args,
        )
        for r in recent:
            r["result"] = _result_line_local(r)
            r["fixture"] = f"{r.get('team_home')} v {r.get('team_away')}"
        decided = int(head[6] or 0) + int(head[7] or 0)
        return {
            "ok": True,
            "venue": ground,
            "city": city,
            "matches": int(head[0] or 0),
            "range": f"{str(head[1] or '')[:4]}–{str(head[2] or '')[:4]}",
            "toss": {"bat": int(head[3] or 0), "field": int(head[4] or 0)},
            "results": {
                "defending": int(head[6] or 0),
                "chasing": int(head[7] or 0),
                "no_result": int(head[5] or 0),
                "chase_pct": round(int(head[7] or 0) * 100 / decided, 1) if decided else None,
            },
            "first_innings": {
                "avg": first_inns[0],
                "max": first_inns[1],
                "min": first_inns[2],
                "run_rate": first_inns[3],
            },
            "by_comp": by_comp,
            "top_bat": top_bat,
            "top_bowl": top_bowl,
            "recent": recent,
        }
    finally:
        con.close()


def _result_line_local(r: dict) -> str:
    if r.get("winner") and r.get("win_by_innings"):
        return f"{r['winner']} by an innings"
    if r.get("winner") and r.get("win_by_runs"):
        return f"{r['winner']} by {int(r['win_by_runs'])} runs"
    if r.get("winner") and r.get("win_by_wickets"):
        return f"{r['winner']} by {int(r['win_by_wickets'])} wkts"
    if r.get("winner"):
        return f"{r['winner']} won"
    return "No result"


def team(*, name: str, comp: str | None = None, gender: str | None = None) -> dict[str, Any]:
    """A side's record, head-to-head ledger, and the players who did the work."""
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built yet."}
    con = connect()
    try:
        side = resolve_team(con, name)
        if not side:
            return {"ok": False, "error": f"No side matching “{name}”."}
        where, params = _gate(con, comp=comp, gender=gender, wtc=False)
        base = f"(m.team_home = ? OR m.team_away = ?) AND {where}"
        args = [side, side, *params]
        head = con.execute(
            f"""
            SELECT COUNT(*) AS matches,
                   SUM(CASE WHEN m.winner = ? THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN m.winner IS NOT NULL AND m.winner <> ? THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN m.winner IS NULL THEN 1 ELSE 0 END) AS undecided,
                   MIN(m.start_date) AS first_date, MAX(m.start_date) AS last_date
            FROM matches m WHERE {base}
            """,
            [side, side, *args],
        ).fetchone()
        h2h = _rows(
            con,
            f"""
            SELECT CASE WHEN m.team_home = ? THEN m.team_away ELSE m.team_home END AS opposition,
                   COUNT(*) AS matches,
                   CAST(SUM(CASE WHEN m.winner = ? THEN 1 ELSE 0 END) AS INTEGER) AS wins,
                   CAST(SUM(CASE WHEN m.winner IS NOT NULL AND m.winner <> ? THEN 1 ELSE 0 END) AS INTEGER) AS losses,
                   CAST(SUM(CASE WHEN m.winner IS NULL THEN 1 ELSE 0 END) AS INTEGER) AS undecided,
                   MAX(m.start_date) AS last_met
            FROM matches m WHERE {base}
            GROUP BY 1
            ORDER BY matches DESC
            LIMIT 40
            """,
            [side, side, side, *args],
        )
        for r in h2h:
            decided = int(r.get("wins") or 0) + int(r.get("losses") or 0)
            r["win_pct"] = round(int(r.get("wins") or 0) * 100 / decided, 1) if decided else None
            r["record"] = f"{r.get('wins')}–{r.get('losses')}"
        by_comp = _rows(
            con,
            f"""
            SELECT m.competition, COUNT(*) AS matches,
                   CAST(SUM(CASE WHEN m.winner = ? THEN 1 ELSE 0 END) AS INTEGER) AS wins,
                   CAST(SUM(CASE WHEN m.winner IS NOT NULL AND m.winner <> ? THEN 1 ELSE 0 END) AS INTEGER) AS losses
            FROM matches m WHERE {base}
            GROUP BY 1 ORDER BY matches DESC
            """,
            [side, side, *args],
        )
        for r in by_comp:
            decided = int(r.get("wins") or 0) + int(r.get("losses") or 0)
            r["win_pct"] = round(int(r.get("wins") or 0) * 100 / decided, 1) if decided else None
        top_bat = _rows(
            con,
            f"""
            SELECT p.display_name AS player, p.slug,
                   COUNT(*) AS inns, SUM(b.runs) AS runs, MAX(b.runs) AS hs,
                   SUM(b.balls) AS balls,
                   SUM(CASE WHEN b.not_out THEN 0 ELSE 1 END) AS outs,
                   SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds
            FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            JOIN people p ON p.person_id = b.person_id
            WHERE b.innings_kind = 'regular' AND b.team = ? AND {where}
            GROUP BY 1,2 ORDER BY runs DESC LIMIT 15
            """,
            [side, *params],
        )
        for r in top_bat:
            outs = int(r.get("outs") or 0)
            balls = int(r.get("balls") or 0)
            r["avg"] = round(int(r.get("runs") or 0) / outs, 1) if outs else None
            r["sr"] = round(int(r.get("runs") or 0) * 100 / balls, 1) if balls else None
        top_bowl = _rows(
            con,
            f"""
            SELECT p.display_name AS player, p.slug,
                   COUNT(*) AS inns, SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
                   SUM(bl.legal_balls) AS legal_balls, MAX(bl.wickets) AS best
            FROM bowling_lines bl
            JOIN matches m ON m.match_id = bl.match_id
            JOIN people p ON p.person_id = bl.person_id
            WHERE bl.innings_kind = 'regular' AND bl.team = ? AND {where}
            GROUP BY 1,2
            HAVING SUM(bl.legal_balls) >= 120
            ORDER BY wickets DESC LIMIT 15
            """,
            [side, *params],
        )
        for r in top_bowl:
            wk = int(r.get("wickets") or 0)
            balls = int(r.get("legal_balls") or 0)
            r["avg"] = round(int(r.get("runs") or 0) / wk, 1) if wk else None
            r["econ"] = round(int(r.get("runs") or 0) * 6 / balls, 2) if balls else None
        recent = _rows(
            con,
            f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner, m.competition,
                   m.win_by_runs, m.win_by_wickets, m.win_by_innings, m.venue
            FROM matches m WHERE {base}
            ORDER BY m.start_date DESC LIMIT 20
            """,
            args,
        )
        for r in recent:
            r["result"] = _result_line_local(r)
            r["opposition"] = r["team_away"] if r["team_home"] == side else r["team_home"]
            r["outcome"] = (
                "Won" if r.get("winner") == side
                else "Lost" if r.get("winner") else "Draw / NR"
            )
        decided = int(head[1] or 0) + int(head[2] or 0)
        return {
            "ok": True,
            "team": side,
            "matches": int(head[0] or 0),
            "wins": int(head[1] or 0),
            "losses": int(head[2] or 0),
            "undecided": int(head[3] or 0),
            "win_pct": round(int(head[1] or 0) * 100 / decided, 1) if decided else None,
            "range": f"{str(head[4] or '')[:4]}–{str(head[5] or '')[:4]}",
            "h2h": h2h,
            "by_comp": by_comp,
            "top_bat": top_bat,
            "top_bowl": top_bowl,
            "recent": recent,
        }
    finally:
        con.close()


def match_extras(match_id: str) -> dict[str, Any]:
    """Over-by-over shape and the standout performers — the two things a scorecard lacks."""
    if not warehouse_ready():
        return {"overs": [], "performers": []}
    con = connect()
    try:
        overs = _rows(
            con,
            """
            SELECT d.innings, d.innings_kind, d.batting_team, d.over,
                   CAST(SUM(d.runs_total) AS INTEGER) AS runs,
                   CAST(SUM(CASE WHEN d.wicket_kind IS NOT NULL
                             AND lower(d.wicket_kind) NOT IN
                                 ('retired hurt','retired not out','absent hurt','absent ill')
                        THEN 1 ELSE 0 END) AS INTEGER) AS wickets
            FROM deliveries d
            WHERE d.match_id = ? AND d.innings_kind = 'regular'
            GROUP BY 1,2,3,4
            ORDER BY d.innings, d.over
            """,
            [match_id],
        )
        bat = _rows(
            con,
            """
            SELECT p.display_name AS player, p.slug, b.team, b.runs, b.balls, b.not_out,
                   b.fours, b.sixes,
                   CASE WHEN b.not_out THEN b.runs || '*' ELSE CAST(b.runs AS VARCHAR) END AS line,
                   CASE WHEN b.balls > 0 THEN ROUND(b.runs * 100.0 / b.balls, 1) END AS sr
            FROM batting_lines b
            JOIN people p ON p.person_id = b.person_id
            WHERE b.match_id = ? AND b.innings_kind = 'regular'
            ORDER BY b.runs DESC, b.balls ASC
            LIMIT 3
            """,
            [match_id],
        )
        bowl = _rows(
            con,
            """
            SELECT p.display_name AS player, p.slug, bl.team, bl.wickets, bl.runs, bl.legal_balls,
                   bl.wickets || '/' || bl.runs AS line,
                   (bl.legal_balls // 6) || '.' || (bl.legal_balls % 6) AS overs,
                   CASE WHEN bl.legal_balls > 0 THEN ROUND(bl.runs * 6.0 / bl.legal_balls, 2) END AS econ
            FROM bowling_lines bl
            JOIN people p ON p.person_id = bl.person_id
            WHERE bl.match_id = ? AND bl.innings_kind = 'regular'
            ORDER BY bl.wickets DESC, bl.runs ASC
            LIMIT 3
            """,
            [match_id],
        )
        return {"overs": overs, "top_bat": bat, "top_bowl": bowl}
    finally:
        con.close()
