from __future__ import annotations

import re
from typing import Any

from cricwarehouse.competitions import GENDER_LABEL, LABELS
from cricwarehouse.laws import dismissal_group
from cricwarehouse.teams import (
    METRIC_COPY,
    POOL_LABELS,
    default_pool,
    parse_comps,
    wtc_match_sql,
    wtc_params,
)
from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.app.query import _people_match, pick_person, resolve_team
from cricwarehouse.app.search import search_people, search_teams

BOWL_CREDITED = (
    "bowled",
    "caught",
    "caught and bowled",
    "lbw",
    "stumped",
    "hit wicket",
)


def search(q: str) -> dict[str, Any]:
    q = (q or "").strip()
    if not warehouse_ready() or len(q) < 1:
        return {"people": [], "teams": [], "destinations": _destinations(q)}
    from cricwarehouse.app.query import parse_query

    parsed = parse_query(q)
    needle = parsed.tokens.get("player") or q
    people = search_people(needle)
    side = (
        parsed.tokens.get("opposition")
        or parsed.tokens.get("side")
        or parsed.tokens.get("home")
        or parsed.tokens.get("team")
        or ""
    )
    teams = search_teams(side or q.split()[-1])
    return {
        "people": people,
        "teams": teams,
        "destinations": _destinations(q),
        "parsed": {
            "tokens": parsed.tokens,
            "mode": parsed.mode,
            "heuristic": parsed.heuristic,
        },
    }


def _destinations(q: str) -> list[dict]:
    dest = [
        {"id": "stats", "label": "Stats table", "hint": "Master batting and bowling, with percentiles and WAR"},
        {"id": "records", "label": "Record book", "hint": "Highest scores, best bowling, biggest stands, fastest hundreds"},
        {"id": "rankings", "label": "Rankings", "hint": "One leaderboard at a time, including form overalls"},
        {"id": "standings", "label": "Standings", "hint": "League points tables and playoffs"},
        {"id": "grounds", "label": "Grounds", "hint": "Venue records and whether the chase is on"},
        {"id": "wowy", "label": "WOWY", "hint": "With or without a player"},
        {"id": "best", "label": "Best T20", "hint": "Greatest match composites in this warehouse"},
        {"id": "compare", "label": "Compare", "hint": "Two players, side by side"},
        {"id": "teams", "label": "Team compare", "hint": "Two sides, same season"},
        {"id": "twin", "label": "Profile twin", "hint": "Closest T20 shape in this warehouse"},
        {"id": "shift", "label": "Stat line shift", "hint": "How teammates change with you"},
    ]
    ql = q.lower()
    if ql:
        dest = [d for d in dest if ql in d["id"] or ql in d["label"].lower() or ql in d["hint"].lower()]
    return dest


def _attach_wtc(con, gender: str | None) -> None:
    con.execute("CREATE TEMP TABLE wtc_teams (team VARCHAR)")
    for t in wtc_params(gender):
        con.execute("INSERT INTO wtc_teams VALUES (?)", [t])


def master_stats(
    *,
    comp: str | None = None,
    gender: str | None = None,
    min_inns: int = 5,
    role: str = "all",
    sort: str = "runs",
    wtc: bool = False,
) -> dict[str, Any]:
    if not warehouse_ready():
        return {"rows": [], "scope": "Warehouse not built"}
    con = connect()
    try:
        if wtc:
            _attach_wtc(con, gender)
        comps = parse_comps(comp)
        bat_w = ["b.innings_kind = 'regular'"]
        bowl_w = ["bl.innings_kind = 'regular'"]
        params: list[Any] = []
        bparams: list[Any] = []
        if comps:
            ph = ",".join(["?"] * len(comps))
            bat_w.append(f"m.competition IN ({ph})")
            bowl_w.append(f"m.competition IN ({ph})")
            params.extend(comps)
            bparams.extend(comps)
        if gender:
            bat_w.append("m.gender = ?")
            bowl_w.append("m.gender = ?")
            params.append(gender)
            bparams.append(gender)
        if wtc:
            bat_w.append(wtc_match_sql("m"))
            bowl_w.append(wtc_match_sql("m"))
        t20_comps = [c for c in (comps or ["t20i", "ipl", "wpl", "bbl", "wbbl"]) if c in ("t20i", "ipl", "wpl", "bbl", "wbbl")]
        val_w = ["1=1"]
        vparams: list[Any] = []
        if t20_comps:
            phv = ",".join(["?"] * len(t20_comps))
            val_w.append(f"competition IN ({phv})")
            vparams.extend(t20_comps)
        if gender:
            val_w.append("gender = ?")
            vparams.append(gender)
        game_w = ["1=1"]
        gparams: list[Any] = []
        if t20_comps:
            phg = ",".join(["?"] * len(t20_comps))
            game_w.append(f"m.competition IN ({phg})")
            gparams.extend(t20_comps)
        if gender:
            game_w.append("m.gender = ?")
            gparams.append(gender)
        from cricwarehouse.app.form import form_ready
        if form_ready():
            form_cte = """frm AS (
          SELECT person_id, COALESCE(form, overall) AS form, is_99
          FROM form_ratings
          WHERE as_of = (SELECT MAX(as_of) FROM form_ratings)
        ),"""
            form_select = "frm.form, frm.is_99,"
            form_join = "LEFT JOIN frm ON frm.person_id = j.person_id"
        else:
            form_cte = ""
            form_select = "NULL AS form, FALSE AS is_99,"
            form_join = ""
        sql = f"""
        WITH bat AS (
          SELECT b.person_id,
                 COUNT(DISTINCT b.match_id) AS matches,
                 COUNT(*) AS inns,
                 SUM(b.runs) AS runs,
                 MAX(b.runs) AS hs,
                 SUM(b.balls) AS balls,
                 SUM(CASE WHEN b.not_out THEN 0 ELSE 1 END) AS outs,
                 SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds,
                 SUM(CASE WHEN b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) AS fifties
          FROM batting_lines b
          JOIN matches m ON m.match_id = b.match_id
          WHERE {' AND '.join(bat_w)}
          GROUP BY 1
        ),
        bowl AS (
          SELECT bl.person_id,
                 SUM(bl.wickets) AS wickets,
                 SUM(bl.runs) AS bowl_runs,
                 SUM(bl.legal_balls) AS legal_balls,
                 SUM(bl.maidens) AS maidens
          FROM bowling_lines bl
          JOIN matches m ON m.match_id = bl.match_id
          WHERE {' AND '.join(bowl_w)}
          GROUP BY 1
        ),
        val AS (
          SELECT person_id,
                 ROUND(SUM(war), 2) AS war,
                 ROUND(SUM(rae_bat), 1) AS rae_bat,
                 ROUND(SUM(rae_bowl), 1) AS rae_bowl,
                 ROUND(SUM(wpa), 3) AS wpa,
                 ROUND(SUM(pressure_impact), 1) AS pressure,
                 COUNT(DISTINCT season) AS seasons,
                 ROUND(SUM(war_bat), 2) AS war_bat,
                 ROUND(SUM(war_bowl), 2) AS war_bowl,
                 ROUND(SUM(raa_bat), 1) AS raa_bat,
                 ROUND(SUM(raa_bowl), 1) AS raa_bowl,
                 SUM(bf) AS bf,
                 SUM(lb) AS lb,
                 CASE WHEN SUM(bf) >= 300
                      THEN ROUND(100.0 * SUM(raa_bat) / SUM(bf), 2) END AS raa100_bat,
                 CASE WHEN SUM(lb) >= 300
                      THEN ROUND(6.0 * SUM(raa_bowl) / SUM(lb), 2) END AS raa_over_bowl,
                 CASE WHEN SUM(CASE WHEN tsr IS NOT NULL THEN bf ELSE 0 END) >= 60
                      THEN ROUND(SUM(tsr * bf) / SUM(CASE WHEN tsr IS NOT NULL THEN bf ELSE 0 END), 2) END AS tsr,
                 CASE WHEN SUM(CASE WHEN te IS NOT NULL THEN lb ELSE 0 END) >= 60
                      THEN ROUND(SUM(te * lb) / SUM(CASE WHEN te IS NOT NULL THEN lb ELSE 0 END), 2) END AS te,
                 CASE WHEN SUM(CASE WHEN twr_bat IS NOT NULL THEN bf ELSE 0 END) >= 60
                      THEN ROUND(SUM(twr_bat * bf) / SUM(CASE WHEN twr_bat IS NOT NULL THEN bf ELSE 0 END), 2) END AS twr_bat,
                 CASE WHEN SUM(CASE WHEN twr_bowl IS NOT NULL THEN lb ELSE 0 END) >= 60
                      THEN ROUND(SUM(twr_bowl * lb) / SUM(CASE WHEN twr_bowl IS NOT NULL THEN lb ELSE 0 END), 2) END AS twr_bowl
          FROM metrics_t20
          WHERE {' AND '.join(val_w)}
          GROUP BY 1
        ),
        games AS (
          SELECT x.person_id, COUNT(DISTINCT x.match_id) AS games
          FROM xi x
          JOIN matches m ON m.match_id = x.match_id
          WHERE {' AND '.join(game_w)}
          GROUP BY 1
        ),
        {form_cte}
        joined AS (
          SELECT COALESCE(bat.person_id, bowl.person_id) AS person_id,
                 COALESCE(bat.matches, 0) AS matches,
                 COALESCE(bat.inns, 0) AS inns,
                 COALESCE(bat.runs, 0) AS runs,
                 bat.hs,
                 COALESCE(bat.balls, 0) AS balls,
                 COALESCE(bat.outs, 0) AS outs,
                 COALESCE(bat.hundreds, 0) AS hundreds,
                 COALESCE(bat.fifties, 0) AS fifties,
                 COALESCE(bowl.wickets, 0) AS wickets,
                 COALESCE(bowl.bowl_runs, 0) AS bowl_runs,
                 COALESCE(bowl.legal_balls, 0) AS legal_balls,
                 COALESCE(bowl.maidens, 0) AS maidens
          FROM bat FULL OUTER JOIN bowl ON bat.person_id = bowl.person_id
        )
        SELECT j.*, p.display_name, p.slug, p.unique_name,
               CASE WHEN j.outs > 0 THEN ROUND(j.runs * 1.0 / j.outs, 1) END AS avg,
               CASE WHEN j.balls > 0 THEN ROUND(j.runs * 100.0 / j.balls, 1) END AS sr,
               CASE WHEN j.wickets > 0 THEN ROUND(j.bowl_runs * 1.0 / j.wickets, 1) END AS bowl_avg,
               CASE WHEN j.legal_balls > 0 THEN ROUND(j.bowl_runs * 6.0 / j.legal_balls, 2) END AS econ,
               CASE WHEN j.legal_balls > j.balls THEN 'bowl' ELSE 'bat' END AS primary_role,
               {form_select}
               v.war, v.wpa, v.pressure, v.seasons,
               v.war_bat, v.war_bowl, v.raa_bat, v.raa_bowl,
               v.raa100_bat, v.raa_over_bowl, v.bf, v.lb,
               v.tsr, v.te, v.twr_bat, v.twr_bowl,
               CASE WHEN g.games >= 20 THEN ROUND(v.war / g.games, 3) END AS war_per_game,
               CASE WHEN g.games >= 20 THEN ROUND(v.rae_bat / g.games, 2) END AS rae_bat,
               CASE WHEN g.games >= 20 THEN ROUND(v.rae_bowl / g.games, 2) END AS rae_bowl,
               ROUND(PERCENT_RANK() OVER (ORDER BY j.runs) * 100) AS runs_pct,
               ROUND(PERCENT_RANK() OVER (ORDER BY j.wickets) * 100) AS wickets_pct,
               ROUND(PERCENT_RANK() OVER (ORDER BY v.war NULLS FIRST) * 100) AS war_pct,
               ROUND(PERCENT_RANK() OVER (ORDER BY CASE WHEN j.outs > 0 THEN j.runs * 1.0 / j.outs END NULLS FIRST) * 100) AS avg_pct,
               ROUND(PERCENT_RANK() OVER (ORDER BY CASE WHEN j.balls > 0 THEN j.runs * 100.0 / j.balls END NULLS FIRST) * 100) AS sr_pct
        FROM joined j
        JOIN people p ON p.person_id = j.person_id
        LEFT JOIN val v ON v.person_id = j.person_id
        LEFT JOIN games g ON g.person_id = j.person_id
        {form_join}
        WHERE (j.inns >= ? OR j.wickets >= ?)
        """
        floor = max(int(min_inns), 1)
        try:
            recs = con.execute(sql, params + bparams + vparams + gparams + [floor, floor]).fetchdf()
        except Exception:
            recs = con.execute(
                sql.replace("LEFT JOIN val v ON v.person_id = j.person_id", "")
                .replace("LEFT JOIN games g ON g.person_id = j.person_id", "")
                .replace(
                    "v.war, v.wpa, v.pressure, v.seasons,\n               v.war_bat, v.war_bowl, v.raa_bat, v.raa_bowl,\n               v.raa100_bat, v.raa_over_bowl, v.bf, v.lb,\n               v.tsr, v.te, v.twr_bat, v.twr_bowl,",
                    "NULL AS war, NULL AS wpa, NULL AS pressure, NULL AS seasons,"
                    " NULL AS war_bat, NULL AS war_bowl, NULL AS raa_bat, NULL AS raa_bowl,"
                    " NULL AS raa100_bat, NULL AS raa_over_bowl, NULL AS bf, NULL AS lb,"
                    " NULL AS tsr, NULL AS te, NULL AS twr_bat, NULL AS twr_bowl,",
                )
                .replace("CASE WHEN g.games >= 20 THEN ROUND(v.war / g.games, 3) END AS war_per_game,", "NULL AS war_per_game,")
                .replace("CASE WHEN g.games >= 20 THEN ROUND(v.rae_bat / g.games, 2) END AS rae_bat,", "NULL AS rae_bat,")
                .replace("CASE WHEN g.games >= 20 THEN ROUND(v.rae_bowl / g.games, 2) END AS rae_bowl,", "NULL AS rae_bowl,"),
                params + bparams + [floor, floor],
            ).fetchdf()
        if recs.empty:
            return {"rows": [], "scope": _scope(comp, gender, 0, wtc)}
        rows = recs.to_dict("records")
        if role == "bowl":
            rows = [r for r in rows if r.get("primary_role") == "bowl" or (r.get("wickets") or 0) >= floor]
        elif role == "bat":
            rows = [r for r in rows if r.get("primary_role") == "bat"]
        key = {
            "runs": "runs",
            "wickets": "wickets",
            "avg": "avg",
            "sr": "sr",
            "bowl_avg": "bowl_avg",
            "econ": "econ",
            "balls": "balls",
            "war": "war",
            "war_per_game": "war_per_game",
            "rae_bat": "rae_bat",
            "rae_bowl": "rae_bowl",
            "wpa": "wpa",
            "pressure": "pressure",
            "war_bat": "war_bat",
            "war_bowl": "war_bowl",
            "raa_bat": "raa_bat",
            "raa_bowl": "raa_bowl",
            "raa100_bat": "raa100_bat",
            "raa_over_bowl": "raa_over_bowl",
            "tsr": "tsr",
            "te": "te",
            "twr_bat": "twr_bat",
            "twr_bowl": "twr_bowl",
            "form": "form",
            "overall": "form",
        }.get(sort, "runs")
        reverse = key not in {"bowl_avg", "econ", "te", "twr_bat"}

        def _sort_key(r, k=key, hi=reverse):
            v = r.get(k)
            missing = v is None or (isinstance(v, float) and v != v)
            if missing:
                return (1, 0.0)
            return (0, -float(v) if hi else float(v))

        rows.sort(key=_sort_key)
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
            r["player"] = r.get("display_name")
            overs = int(r.get("legal_balls") or 0)
            r["overs"] = f"{overs // 6}.{overs % 6}" if overs else None
        return {
            "rows": _jsonable(rows),
            "scope": _scope(comp, gender, len(rows), wtc),
        }
    finally:
        con.close()


def rankings(*, metric: str = "runs", comp: str | None = None, gender: str | None = None, min_inns: int = 5) -> dict:
    if metric == "overall":
        from cricwarehouse.app.form import latest_board
        return latest_board(gender=gender, limit=200)
    if metric == "war":
        return _war_rankings(comp=comp, gender=gender)
    data = master_stats(comp=comp, gender=gender, min_inns=min_inns, role="all", sort=metric)
    data["metric"] = metric
    return data


def _war_rankings(*, comp: str | None, gender: str | None) -> dict:
    if not warehouse_ready():
        return {"rows": [], "scope": "Warehouse not built", "metric": "war"}
    con = connect()
    try:
        where = ["1=1"]
        params: list[Any] = []
        if comp:
            where.append("m.competition = ?")
            params.append(comp)
        if gender:
            where.append("m.gender = ?")
            params.append(gender)
        try:
            recs = con.execute(
                f"""
                SELECT p.display_name, p.slug, p.unique_name, p.person_id,
                       ROUND(SUM(m.war), 2) AS war,
                       ROUND(AVG(m.overall_default), 1) AS overall_default,
                       SUM(m.balls_bat) AS balls,
                       SUM(m.balls_bowl) AS legal_balls,
                       CASE WHEN SUM(m.balls_bowl) > SUM(m.balls_bat) THEN 'bowl' ELSE 'bat' END AS primary_role
                FROM metrics_t20 m
                JOIN people p ON p.person_id = m.person_id
                WHERE {' AND '.join(where)}
                GROUP BY 1,2,3,4
                HAVING SUM(m.balls_bat) + SUM(m.balls_bowl) >= 60
                ORDER BY SUM(m.war) DESC
                LIMIT 400
                """,
                params,
            ).fetchdf()
        except Exception:
            return {"rows": [], "scope": "T20 metrics not built yet", "metric": "war"}
        rows = recs.to_dict("records") if not recs.empty else []
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
            r["player"] = r.get("display_name")
            r["runs"] = None
            r["avg"] = None
            r["wickets"] = None
            r["bowl_avg"] = None
            r["econ"] = None
        return {
            "rows": _jsonable(rows),
            "scope": _scope(comp, gender, len(rows)) + " · T20 WAR",
            "metric": "war",
        }
    finally:
        con.close()


def wowy(*, team: str, player: str, comp: str | None = None, gender: str | None = None) -> dict[str, Any]:
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built yet."}
    con = connect()
    try:
        people = _people_match(con, player)
        if not people:
            return {"ok": True, "kind": "empty", "message": f"No player match for {player}.", "rows": []}
        needle = re.sub(r"[-_]+", " ", player.strip().lower()).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", needle).strip("-")
        exact = [
            p
            for p in people
            if p["slug"] == slug
            or (p.get("unique_name") or "").lower() == needle
            or (p.get("person_id") or "").lower() == needle
            or p["slug"] == player.strip().lower()
        ]
        person = exact[0] if exact else pick_person(people, player)
        if not person:
            return {
                "ok": True,
                "kind": "pick_player",
                "people": people,
                "rows": [],
                "message": f"{len(people)} players match “{player}”. Pick one.",
            }
        pid = person["person_id"]
        side = resolve_team(con, team)
        if not side:
            return {"ok": True, "kind": "empty", "message": f"No side matching {team}.", "rows": []}
        where = ["(m.team_home = ? OR m.team_away = ?)"]
        params: list[Any] = [side, side]
        if comp:
            where.append("m.competition = ?")
            params.append(comp)
        if gender:
            where.append("m.gender = ?")
            params.append(gender)
        first = con.execute(
            f"""
            SELECT MIN(m.start_date)
            FROM matches m
            JOIN xi x ON x.match_id = m.match_id
            WHERE x.person_id = ? AND x.team = ?
              AND {' AND '.join(where)}
            """,
            [pid, side] + params,
        ).fetchone()[0]
        if first:
            where.append("m.start_date >= ?")
            params.append(first)
        matches = con.execute(
            f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner, m.competition,
                   EXISTS (
                     SELECT 1 FROM xi x
                     WHERE x.match_id = m.match_id AND x.person_id = ?
                       AND x.team = ?
                   ) AS present
            FROM matches m
            WHERE {' AND '.join(where)}
            """,
            [pid, side] + params,
        ).fetchall()

        def pack(group, label):
            ids = [r[0] for r in group]
            n = len(ids)
            wins = sum(1 for r in group if r[4] == side)
            if not ids:
                return {
                    "split": label, "matches": 0, "wins": 0, "win_pct": None,
                    "runs_for": None, "runs_against": None, "wickets": None,
                }
            placeholders = ",".join(["?"] * len(ids))
            rf, ra, wk = con.execute(
                f"""
                SELECT
                  SUM(CASE WHEN i.batting_team = ? THEN i.runs ELSE 0 END),
                  SUM(CASE WHEN i.bowling_team = ? THEN i.runs ELSE 0 END),
                  SUM(CASE WHEN i.bowling_team = ? THEN i.wickets ELSE 0 END)
                FROM innings i
                WHERE i.match_id IN ({placeholders}) AND i.innings_kind = 'regular'
                """,
                [side, side, side] + ids,
            ).fetchone()
            return {
                "split": label,
                "matches": n,
                "wins": wins,
                "win_pct": round(100 * wins / n, 1) if n else None,
                "runs_for": int(rf or 0),
                "runs_against": int(ra or 0),
                "wickets": int(wk or 0),
            }

        with_m = [r for r in matches if r[6]]
        without_m = [r for r in matches if not r[6]]
        rows = [
            pack(with_m, f"With {person['display_name']}"),
            pack(without_m, f"Without {person['display_name']}"),
        ]
        return {
            "ok": True,
            "kind": "wowy",
            "person": person,
            "team": side,
            "people": people,
            "rows": rows,
            "scope": f"{side} · {person['display_name']} · from {first[:10] if first else '—'} · in this warehouse",
            "available_from": first,
            "caption": (
                f"Only matches on or after {person['display_name']}'s first XI for {side}"
                + (f" ({first[:10]})" if first else "")
                + ". Small samples stay noisy — this is a split, not RAPM."
            ),
        }
    finally:
        con.close()


def teams(q: str = "") -> list[str]:
    if not warehouse_ready():
        return []
    con = connect()
    try:
        if q:
            rows = con.execute(
                """
                SELECT team, COUNT(*) c FROM (
                  SELECT team_home AS team FROM matches
                  UNION ALL
                  SELECT team_away AS team FROM matches
                )
                WHERE lower(team) LIKE ?
                GROUP BY 1 ORDER BY c DESC LIMIT 30
                """,
                [f"%{q.lower()}%"],
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT team, COUNT(*) c FROM (
                  SELECT team_home AS team FROM matches
                  UNION ALL
                  SELECT team_away AS team FROM matches
                )
                GROUP BY 1 ORDER BY c DESC LIMIT 40
                """
            ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def career_value(person_id: str, *, pool: str | None = None, gender: str | None = None) -> dict[str, Any]:
    if not warehouse_ready():
        return {"ok": False, "metrics": []}
    con = connect()
    try:
        g = gender
        if not g:
            row = con.execute(
                "SELECT gender FROM metrics_t20 WHERE person_id = ? LIMIT 1", [person_id]
            ).fetchone()
            g = row[0] if row else None
        pool = pool or default_pool(g)
        comps = parse_comps(pool) or list(POOL_COMPS_FALLBACK)
        ph = ",".join(["?"] * len(comps))
        try:
            recs = con.execute(
                f"""
                SELECT person_id,
                       ROUND(SUM(war), 2) AS war,
                       ROUND(SUM(war_bat), 2) AS war_bat,
                       ROUND(SUM(war_bowl), 2) AS war_bowl,
                       ROUND(SUM(raa_bat), 1) AS raa_bat,
                       ROUND(SUM(raa_bowl), 1) AS raa_bowl,
                       ROUND(SUM(rae_bat), 1) AS rae_bat,
                       ROUND(SUM(rae_bowl), 1) AS rae_bowl,
                       ROUND(SUM(wpa), 3) AS wpa,
                       ROUND(SUM(pressure_impact), 1) AS pressure,
                       COUNT(DISTINCT season) AS seasons,
                       SUM(balls_bat) AS balls_bat,
                       SUM(balls_bowl) AS balls_bowl,
                       SUM(bf) AS bf,
                       SUM(lb) AS lb,
                       CASE WHEN SUM(CASE WHEN tsr IS NOT NULL THEN bf ELSE 0 END) >= 60
                            THEN ROUND(SUM(tsr * bf) / SUM(CASE WHEN tsr IS NOT NULL THEN bf ELSE 0 END), 2) END AS tsr,
                       CASE WHEN SUM(CASE WHEN te IS NOT NULL THEN lb ELSE 0 END) >= 60
                            THEN ROUND(SUM(te * lb) / SUM(CASE WHEN te IS NOT NULL THEN lb ELSE 0 END), 2) END AS te,
                       CASE WHEN SUM(CASE WHEN twr_bat IS NOT NULL THEN bf ELSE 0 END) >= 60
                            THEN ROUND(SUM(twr_bat * bf) / SUM(CASE WHEN twr_bat IS NOT NULL THEN bf ELSE 0 END), 2) END AS twr_bat,
                       CASE WHEN SUM(CASE WHEN twr_bowl IS NOT NULL THEN lb ELSE 0 END) >= 60
                            THEN ROUND(SUM(twr_bowl * lb) / SUM(CASE WHEN twr_bowl IS NOT NULL THEN lb ELSE 0 END), 2) END AS twr_bowl
                FROM metrics_t20
                WHERE competition IN ({ph}) AND gender = ?
                GROUP BY 1
                HAVING SUM(balls_bat) + SUM(balls_bowl) >= 60
                """,
                comps + [g],
            ).fetchdf()
        except Exception:
            recs = con.execute(
                f"""
                SELECT person_id,
                       ROUND(SUM(war), 2) AS war,
                       ROUND(SUM(rae_bat), 1) AS rae_bat,
                       ROUND(SUM(rae_bowl), 1) AS rae_bowl,
                       ROUND(SUM(wpa), 3) AS wpa,
                       ROUND(SUM(pressure_impact), 1) AS pressure,
                       COUNT(DISTINCT season) AS seasons,
                       SUM(balls_bat) AS balls_bat,
                       SUM(balls_bowl) AS balls_bowl
                FROM metrics_t20
                WHERE competition IN ({ph}) AND gender = ?
                GROUP BY 1
                HAVING SUM(balls_bat) + SUM(balls_bowl) >= 60
                """,
                comps + [g],
            ).fetchdf()
        if recs.empty:
            return {
                "ok": True,
                "pool": pool,
                "pool_label": POOL_LABELS.get(pool, pool),
                "metrics": [],
                "copy": METRIC_COPY,
            }
        games = con.execute(
            f"""
            SELECT x.person_id, COUNT(DISTINCT x.match_id) AS games
            FROM xi x
            JOIN matches m ON m.match_id = x.match_id
            WHERE m.competition IN ({ph}) AND m.gender = ?
            GROUP BY 1
            """,
            comps + [g],
        ).fetchdf()
        recs = recs.merge(games, on="person_id", how="left")
        recs["games"] = recs["games"].fillna(0).astype(int)
        recs["war_per_game"] = recs.apply(
            lambda r: round(float(r["war"] or 0) / int(r["games"]), 3) if int(r["games"] or 0) >= 20 else None,
            axis=1,
        )
        recs["rae_bat"] = recs.apply(
            lambda r: round(float(r["rae_bat"] or 0) / int(r["games"]), 2) if int(r["games"] or 0) >= 20 else None,
            axis=1,
        )
        recs["rae_bowl"] = recs.apply(
            lambda r: round(float(r["rae_bowl"] or 0) / int(r["games"]), 2) if int(r["games"] or 0) >= 20 else None,
            axis=1,
        )
        n = len(recs)
        ranks = {}
        for col, higher in (
            ("war", True),
            ("war_per_game", True),
            ("war_bat", True),
            ("war_bowl", True),
            ("raa_bat", True),
            ("raa_bowl", True),
            ("tsr", True),
            ("te", False),
            ("twr_bat", False),
            ("twr_bowl", True),
            ("rae_bat", True),
            ("rae_bowl", True),
            ("wpa", True),
            ("pressure", True),
        ):
            if col not in recs.columns:
                continue
            recs[f"{col}_rank"] = recs[col].rank(ascending=not higher, method="min", na_option="bottom")
        mine = recs[recs["person_id"] == person_id]
        if mine.empty:
            return {
                "ok": True,
                "pool": pool,
                "pool_label": POOL_LABELS.get(pool, pool),
                "metrics": [],
                "n": n,
                "copy": METRIC_COPY,
            }
        r = mine.iloc[0].to_dict()
        metrics = []
        for key, label in (
            ("war", "WAR"),
            ("war_per_game", "WAR / game"),
            ("raa_bat", "RAA bat"),
            ("raa_bowl", "RAA bowl"),
            ("tsr", "TSR"),
            ("te", "TE"),
            ("war_bat", "bWAR"),
            ("war_bowl", "pWAR"),
            ("twr_bat", "TWR bat"),
            ("twr_bowl", "TWR bowl"),
        ):
            val = r.get(key)
            if val is None or (isinstance(val, float) and val != val):
                continue
            rank = int(r.get(f"{key}_rank") or 0)
            metrics.append(
                {
                    "key": key,
                    "label": label,
                    "value": _jsonable([{"v": r.get(key)}])[0]["v"],
                    "rank": rank,
                    "of": n,
                    "pct": round(100 * (n - rank) / max(n - 1, 1)) if n > 1 else 100,
                    "copy": METRIC_COPY.get(key, ""),
                }
            )
        return {
            "ok": True,
            "pool": pool,
            "pool_label": POOL_LABELS.get(pool, pool),
            "seasons": int(r.get("seasons") or 0),
            "games": int(r.get("games") or 0),
            "balls_bat": int(r.get("balls_bat") or 0),
            "balls_bowl": int(r.get("balls_bowl") or 0),
            "n": n,
            "metrics": metrics,
            "copy": METRIC_COPY,
        }
    except Exception:
        return {"ok": True, "pool": pool or "t20i_ipl", "metrics": [], "copy": METRIC_COPY}
    finally:
        con.close()


POOL_COMPS_FALLBACK = ("t20i", "ipl")


# --------------------------------------------------------------------------
# Resource-model outputs
# --------------------------------------------------------------------------

VALUE_PANELS = (
    (
        "Batting",
        "bat",
        (
            ("war_bat", "WAR", "wins", 3),
            ("vorp_bat", "Runs above replacement", "runs", 1),
            ("raa_bat", "Runs above average", "runs", 1),
            ("raa100_bat", "Per 100 balls", "rate", 2),
        ),
    ),
    (
        "Bowling",
        "bowl",
        (
            ("war_bowl", "WAR", "wins", 3),
            ("vorp_bowl", "Runs above replacement", "runs", 1),
            ("raa_bowl", "Runs above average", "runs", 1),
            ("raa_over_bowl", "Per over", "rate", 2),
        ),
    ),
)

SKILL_ROWS = (
    ("tsr", "Scoring", "runs / 100 balls vs expected", 2, True),
    ("twr_bat", "Staying in", "dismissals / 100 balls vs expected", 2, False),
    ("four_residual", "Fours", "per 100 balls vs expected", 2, True),
    ("six_residual", "Sixes", "per 100 balls vs expected", 2, True),
    ("dot_residual_bat", "Dots faced", "per 100 balls vs expected", 2, False),
    ("te", "Runs conceded", "per over vs expected", 2, False),
    ("twr_bowl", "Wickets", "per 100 balls vs expected", 2, True),
    ("dot_residual_team", "Dots bowled", "per 100 balls vs expected", 2, True),
    ("xr_runs", "Wides and no-balls", "runs per over", 2, False),
    ("xr_event", "Illegal deliveries", "per 100 attempted", 2, False),
)


def player_value_v2(person_id: str, *, comp: str | None = None) -> dict[str, Any]:
    """Resource-model value for one player, with career and per-season detail."""
    if not warehouse_ready():
        return {"ok": False}
    con = connect()
    try:
        where = ["m.person_id = ?"]
        params: list[Any] = [person_id]
        if comp:
            where.append("m.competition = ?")
            params.append(comp)
        try:
            seasons = con.execute(
                f"""
                SELECT m.competition, m.season, m.gender, m.bf, m.lb,
                       m.war_bat, m.war_bowl, m.war, m.war_label,
                       m.vorp_bat, m.vorp_bowl, m.raa_bat, m.raa_bowl,
                       m.raa100_bat, m.raa_over_bowl, m.runs_per_win_v2,
                       m.tsr, m.te, m.twr_bat, m.twr_bowl,
                       m.four_residual, m.six_residual,
                       m.dot_residual_bat, m.dot_residual_team,
                       m.xr_event, m.xr_runs,
                       m.replacement_rate_bat, m.replacement_rate_bowl,
                       m.bat_dismissals, m.bowl_wickets
                FROM metrics_t20 m
                WHERE {' AND '.join(where)} AND (m.bf > 0 OR m.lb > 0)
                ORDER BY m.season DESC, m.competition
                """,
                params,
            ).fetchdf()
        except Exception:
            return {"ok": False, "reason": "not_built"}
        if seasons.empty:
            return {"ok": True, "seasons": [], "panels": [], "skills": []}

        bf = float(seasons["bf"].fillna(0).sum())
        lb = float(seasons["lb"].fillna(0).sum())
        career = {
            "bf": int(bf),
            "lb": int(lb),
            "war_bat": _rsum(seasons, "war_bat", 3),
            "war_bowl": _rsum(seasons, "war_bowl", 3),
            "war": _rsum(seasons, "war", 3),
            "vorp_bat": _rsum(seasons, "vorp_bat", 1),
            "vorp_bowl": _rsum(seasons, "vorp_bowl", 1),
            "raa_bat": _rsum(seasons, "raa_bat", 1),
            "raa_bowl": _rsum(seasons, "raa_bowl", 1),
            "dismissals": int(seasons["bat_dismissals"].fillna(0).sum()),
            "wickets": int(seasons["bowl_wickets"].fillna(0).sum()),
        }
        career["raa100_bat"] = round(100 * career["raa_bat"] / bf, 2) if bf else None
        career["raa_over_bowl"] = round(6 * career["raa_bowl"] / lb, 2) if lb else None
        # Career rates are exposure-weighted means of the season rates, so a
        # two-over cameo cannot swing a career figure.
        career_rates = _weighted_rates(seasons)

        label = next((v for v in seasons["war_label"].dropna().tolist()), "WAR")
        panels = []
        for title, disc, fields in VALUE_PANELS:
            exposure = career["bf"] if disc == "bat" else career["lb"]
            if not exposure:
                continue
            panels.append(
                {
                    "title": title,
                    "discipline": disc,
                    "exposure": exposure,
                    "exposure_label": "balls faced" if disc == "bat" else "balls bowled",
                    "items": [
                        {
                            "key": key,
                            "label": "WAR" if key.startswith("war") and label == "WAR" else (
                                "Wins-equivalent" if key.startswith("war") else lbl
                            ),
                            "value": career.get(key),
                            "kind": kind,
                            "copy": METRIC_COPY.get(key, ""),
                        }
                        for key, lbl, kind, _ in fields
                    ],
                }
            )
        skills = []
        for key, label_txt, unit, _, higher_better in SKILL_ROWS:
            val = career_rates.get(key)
            if val is None:
                continue
            skills.append(
                {
                    "key": key,
                    "label": label_txt,
                    "unit": unit,
                    "value": val,
                    "good": (val > 0) if higher_better else (val < 0),
                    "copy": METRIC_COPY.get(key, ""),
                }
            )
        return {
            "ok": True,
            "career": career,
            "war_label": label,
            "panels": panels,
            "skills": skills,
            "seasons": _jsonable(seasons.to_dict("records")),
            "slices": player_slices(con, person_id, comp=comp),
            "dismissals": player_dismissal_profile(con, person_id, comp=comp),
            "phase_share": player_phase_share(con, person_id, comp=comp),
        }
    finally:
        con.close()


def _rsum(frame, col: str, nd: int) -> float:
    return round(float(frame[col].fillna(0).sum()), nd)


def _weighted_rates(seasons) -> dict[str, float]:
    """Exposure-weighted career rates from per-season rate columns."""
    out: dict[str, float] = {}
    bat_w = seasons["bf"].fillna(0).to_numpy(dtype=float)
    bowl_w = seasons["lb"].fillna(0).to_numpy(dtype=float)
    bat_keys = ("tsr", "twr_bat", "four_residual", "six_residual", "dot_residual_bat")
    bowl_keys = ("te", "twr_bowl", "dot_residual_team", "xr_runs", "xr_event")
    for keys, weight in ((bat_keys, bat_w), (bowl_keys, bowl_w)):
        total = weight.sum()
        if total <= 0:
            continue
        for key in keys:
            if key not in seasons:
                continue
            vals = seasons[key].astype(float).to_numpy()
            mask = ~pd_isna(vals)
            if not mask.any():
                continue
            w = weight[mask]
            if w.sum() <= 0:
                continue
            out[key] = round(float((vals[mask] * w).sum() / w.sum()), 2)
    return out


def pd_isna(values):
    import numpy as np

    return np.isnan(values)


def player_slices(con, person_id: str, *, comp: str | None = None) -> list[dict]:
    """Runs above average by phase, entry state, and match context."""
    where = ["s.person_id = ?"]
    params: list[Any] = [person_id]
    if comp:
        where.append("s.competition = ?")
        params.append(comp)
    try:
        rows = con.execute(
            f"""
            SELECT s.discipline, s.slice_kind, s.slice_label, s.slice_key,
                   SUM(s.exposure) AS exposure,
                   SUM(s.raa) AS raa,
                   SUM(s.runs) AS runs
            FROM raa_slices_t20 s
            WHERE {' AND '.join(where)}
            GROUP BY 1,2,3,4
            HAVING SUM(s.exposure) >= 20
            ORDER BY s.discipline, s.slice_kind, s.slice_key
            """,
            params,
        ).fetchdf()
    except Exception:
        return []
    if rows.empty:
        return []
    rows["rate"] = rows.apply(
        lambda r: round(
            (100 if r["discipline"] == "bat" else 6) * float(r["raa"]) / float(r["exposure"]), 2
        )
        if float(r["exposure"] or 0) > 0
        else None,
        axis=1,
    )
    rows["raa"] = rows["raa"].round(1)
    grouped: dict[tuple, dict] = {}
    for r in rows.to_dict("records"):
        key = (r["discipline"], r["slice_kind"])
        block = grouped.setdefault(
            key,
            {
                "discipline": r["discipline"],
                "kind": r["slice_kind"],
                "label": r["slice_label"],
                "unit": "per 100 balls" if r["discipline"] == "bat" else "per over",
                "rows": [],
            },
        )
        block["rows"].append(
            {
                "key": r["slice_key"],
                "exposure": int(r["exposure"]),
                "raa": r["raa"],
                "rate": r["rate"],
            }
        )
    return _jsonable(list(grouped.values()))


def player_dismissal_profile(con, person_id: str, *, comp: str | None = None) -> dict[str, list[dict]]:
    """How they got out, and how they took wickets, in T20 only.

    Groups follow the methodology map: caught stays separate from caught-and-bowled,
    and hit wicket is not folded into beaten-in-defence.
    """
    comps = parse_comps(comp) if comp else ["t20i", "ipl", "wpl", "bbl", "wbbl"]
    comps = [c for c in (comps or []) if c in ("t20i", "ipl", "wpl", "bbl", "wbbl")] or [
        "t20i", "ipl", "wpl", "bbl", "wbbl",
    ]
    ph = ",".join(["?"] * len(comps))
    bat: list[dict] = []
    bowl: list[dict] = []
    try:
        rows = con.execute(
            f"""
            SELECT COALESCE(NULLIF(b.dismissal_kind, ''), 'not out') AS kind, COUNT(*) AS n
            FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            WHERE b.person_id = ? AND b.innings_kind = 'regular'
              AND m.competition IN ({ph})
            GROUP BY 1
            """,
            [person_id, *comps],
        ).fetchdf()
        counts: dict[str, int] = {}
        for r in rows.to_dict("records") if not rows.empty else []:
            raw = (r.get("kind") or "").lower()
            if raw in {"", "not out"}:
                label = "Not out"
            else:
                label = dismissal_group(raw)
            counts[label] = counts.get(label, 0) + int(r.get("n") or 0)
        bat = [{"label": k, "n": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    except Exception:
        bat = []
    try:
        rows = con.execute(
            f"""
            SELECT COALESCE(NULLIF(d.wicket_kind, ''), 'unknown') AS kind, COUNT(*) AS n
            FROM deliveries d
            JOIN matches m ON m.match_id = d.match_id
            WHERE d.bowler = ? AND d.innings_kind = 'regular'
              AND COALESCE(d.d_bowl, 0) > 0
              AND m.competition IN ({ph})
            GROUP BY 1
            """,
            [person_id, *comps],
        ).fetchdf()
        counts = {}
        for r in rows.to_dict("records") if not rows.empty else []:
            label = dismissal_group(r.get("kind"))
            if label == "Not out":
                continue
            counts[label] = counts.get(label, 0) + int(r.get("n") or 0)
        bowl = [{"label": k, "n": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    except Exception:
        bowl = []
    return {"bat": bat, "bowl": bowl}


def player_phase_share(con, person_id: str, *, comp: str | None = None) -> list[dict]:
    """Share of bowling workload by phase — powerplay, middle, death."""
    where = ["s.person_id = ?", "s.discipline = 'bowl'", "s.slice_kind = 'phase'"]
    params: list[Any] = [person_id]
    if comp:
        where.append("s.competition = ?")
        params.append(comp)
    try:
        rows = con.execute(
            f"""
            SELECT s.slice_key AS phase, SUM(s.exposure) AS exposure
            FROM raa_slices_t20 s
            WHERE {' AND '.join(where)}
            GROUP BY 1
            HAVING SUM(s.exposure) > 0
            ORDER BY SUM(s.exposure) DESC
            """,
            params,
        ).fetchdf()
    except Exception:
        return []
    if rows.empty:
        return []
    total = float(rows["exposure"].sum())
    out = []
    for r in rows.to_dict("records"):
        exp = float(r["exposure"] or 0)
        out.append(
            {
                "phase": str(r["phase"]),
                "exposure": int(exp),
                "share": round(100.0 * exp / total, 1) if total else 0.0,
            }
        )
    return out


def resource_model(*, gender: str = "male") -> dict[str, Any]:
    """Everything behind the numbers: resource surfaces, calibration, audit."""
    if not warehouse_ready():
        return {"ok": False}
    con = connect()
    try:
        def q(sql, params=None):
            try:
                return _jsonable(con.execute(sql, params or []).fetchdf().to_dict("records"))
            except Exception:
                return []

        grid = q(
            """
            SELECT balls_remaining AS balls, wickets_in_hand AS wickets,
                   expected_runs AS value, n
            FROM resource_grid WHERE sex = ? ORDER BY balls_remaining, wickets_in_hand
            """,
            [gender],
        )
        chase = q(
            """
            SELECT need, balls_remaining AS balls, wickets_in_hand AS wickets,
                   expected_runs AS value, n
            FROM chase_grid WHERE sex = ? ORDER BY need, balls_remaining, wickets_in_hand
            """,
            [gender],
        )
        rpw = q("SELECT * FROM runs_per_win_t20 ORDER BY gender, competition")
        audit = q('SELECT * FROM model_audit ORDER BY status DESC, "check_name", scope')
        replacement = q(
            """
            SELECT competition, gender, discipline, role,
                   ROUND(AVG(rho), 4) AS rho,
                   COUNT(*) AS pools,
                   SUM(CASE WHEN method LIKE 'percentile%' THEN 1 ELSE 0 END) AS fallbacks
            FROM replacement_t20
            WHERE gender = ?
            GROUP BY 1,2,3,4
            ORDER BY competition, discipline, role
            """,
            [gender],
        )
        exposure = q(
            """
            SELECT competition, gender, season, deliveries, unscored, unscored_share, top_reason
            FROM unscored_exposure
            WHERE gender = ? AND unscored > 0
            ORDER BY unscored_share DESC
            LIMIT 40
            """,
            [gender],
        )
        distortion = q(
            """
            SELECT competition, entry_state, opportunities, raa_chase_table,
                   raa_target_neutral, gap_per_100
            FROM chase_distortion
            WHERE gender = ?
            ORDER BY abs(gap_per_100) DESC
            LIMIT 24
            """,
            [gender],
        )
        meta = {}
        try:
            row = con.execute("SELECT * FROM model_meta LIMIT 1").fetchdf()
            if not row.empty:
                meta = _clean_meta(row.iloc[0].to_dict())
        except Exception:
            meta = {}
        passing = sum(1 for a in audit if a.get("status") == "pass")
        return {
            "ok": True,
            "gender": gender,
            "grid": grid,
            "chase": chase,
            "rpw": rpw,
            "audit": audit,
            "audit_summary": {"pass": passing, "fail": len(audit) - passing, "total": len(audit)},
            "replacement": replacement,
            "exposure": exposure,
            "distortion": distortion,
            "meta": meta,
        }
    finally:
        con.close()


def _clean_meta(row: dict) -> dict:
    import json

    out = {}
    for k, v in row.items():
        if isinstance(v, str) and v.startswith(("{", "[")):
            try:
                out[k] = json.loads(v)
                continue
            except json.JSONDecodeError:
                pass
        out[k] = v.item() if hasattr(v, "item") else v
    return out


def match_value(match_id: str) -> dict[str, Any]:
    """Resource-adjusted innings values for one match."""
    if not warehouse_ready():
        return {"ok": False, "rows": []}
    con = connect()
    try:
        rows = con.execute(
            """
            SELECT innings, batting_team, bowling_team, runs, wickets_used, legal_balls,
                   resource_value, resource_value_chase, allocation, complete, fit_eligible
            FROM match_value_t20 WHERE match_id = ? ORDER BY innings
            """,
            [match_id],
        ).fetchdf()
        if rows.empty:
            return {"ok": True, "rows": []}
        recs = _jsonable(rows.to_dict("records"))
        margin = None
        if len(recs) == 2:
            margin = round(
                float(recs[0]["resource_value"]) - float(recs[1]["resource_value"]), 1
            )
        return {"ok": True, "rows": recs, "margin": margin}
    except Exception:
        return {"ok": True, "rows": []}
    finally:
        con.close()


def matchups(person_id: str, *, wtc: bool = False, comp: str | None = None) -> dict[str, Any]:
    if not warehouse_ready():
        return {"as_batter": [], "as_bowler": []}
    con = connect()
    try:
        if wtc:
            _attach_wtc(con, None)
        wtc_f = f"AND {wtc_match_sql('m')}" if wtc else ""
        comps = parse_comps(comp)
        comp_f = ""
        extra: list[Any] = []
        if comps:
            ph = ",".join(["?"] * len(comps))
            comp_f = f"AND m.competition IN ({ph})"
            extra = list(comps)
        kinds = ",".join(f"'{k}'" for k in BOWL_CREDITED)
        vs_bowl = con.execute(
            f"""
            SELECT m.competition,
                   p.display_name AS opponent, p.slug AS opp_slug, d.bowler AS opp_id,
                   SUM(CASE WHEN d.striker IS NOT NULL AND NOT d.is_wide THEN 1 ELSE 0 END) AS balls,
                   SUM(CASE WHEN d.striker IS NOT NULL THEN d.runs_batter ELSE 0 END) AS runs,
                   SUM(CASE WHEN d.player_out = d.striker AND d.wicket_kind IN ({kinds}) THEN 1 ELSE 0 END) AS dismissals
            FROM deliveries d
            JOIN matches m ON m.match_id = d.match_id
            JOIN people p ON p.person_id = d.bowler
            WHERE d.striker = ? AND d.innings_kind = 'regular' AND d.bowler IS NOT NULL {wtc_f} {comp_f}
            GROUP BY 1,2,3,4
            HAVING SUM(CASE WHEN d.striker IS NOT NULL AND NOT d.is_wide THEN 1 ELSE 0 END) >= 12
            ORDER BY balls DESC
            """,
            [person_id] + extra,
        ).fetchdf()
        vs_bat = con.execute(
            f"""
            SELECT m.competition,
                   p.display_name AS opponent, p.slug AS opp_slug, d.striker AS opp_id,
                   SUM(CASE WHEN d.is_legal THEN 1 ELSE 0 END) AS balls,
                   SUM(d.runs_batter + CASE WHEN d.extra_type IN ('wides','noballs') THEN d.runs_extras ELSE 0 END) AS runs,
                   SUM(CASE WHEN d.player_out = d.striker AND d.wicket_kind IN ({kinds}) THEN 1 ELSE 0 END) AS dismissals
            FROM deliveries d
            JOIN matches m ON m.match_id = d.match_id
            JOIN people p ON p.person_id = d.striker
            WHERE d.bowler = ? AND d.innings_kind = 'regular' AND d.striker IS NOT NULL {wtc_f} {comp_f}
            GROUP BY 1,2,3,4
            HAVING SUM(CASE WHEN d.is_legal THEN 1 ELSE 0 END) >= 12
            ORDER BY balls DESC
            """,
            [person_id] + extra,
        ).fetchdf()
        def pack(df, as_bowl: bool):
            if df is None or df.empty:
                return []
            rows = df.to_dict("records")
            out = []
            for r in rows:
                balls = int(r.get("balls") or 0)
                runs = int(r.get("runs") or 0)
                dsm = int(r.get("dismissals") or 0)
                item = {
                    "competition": r.get("competition"),
                    "opponent": r.get("opponent"),
                    "opp_slug": r.get("opp_slug"),
                    "balls": balls,
                    "runs": runs,
                    "dismissals": dsm,
                }
                if as_bowl:
                    item["avg"] = round(runs / dsm, 1) if dsm else None
                    item["econ"] = round(runs * 6 / balls, 2) if balls else None
                    item["line"] = f"{dsm}/{runs} off {balls // 6}.{balls % 6}"
                else:
                    item["sr"] = round(runs * 100 / balls, 1) if balls else None
                    item["avg"] = round(runs / dsm, 1) if dsm else None
                    item["line"] = f"{runs} off {balls}" + (f" ({dsm} out)" if dsm else "")
                out.append(item)
            return _jsonable(out)
        return {"as_batter": pack(vs_bowl, False), "as_bowler": pack(vs_bat, True)}
    finally:
        con.close()


def list_performances(
    *,
    person_id: str | None = None,
    discipline: str | None = None,
    comp: str | None = None,
    gender: str | None = None,
    wtc: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    if not warehouse_ready():
        return {"rows": [], "scope": "Warehouse not built"}
    con = connect()
    try:
        if wtc:
            _attach_wtc(con, gender)
        where = ["1=1"]
        params: list[Any] = []
        if person_id:
            where.append("pf.person_id = ?")
            params.append(person_id)
        if discipline in {"bat", "bowl"}:
            where.append("pf.discipline = ?")
            params.append(discipline)
        comps = parse_comps(comp)
        if comps:
            ph = ",".join(["?"] * len(comps))
            where.append(f"pf.competition IN ({ph})")
            params.extend(comps)
        if gender:
            where.append("pf.gender = ?")
            params.append(gender)
        if wtc:
            where.append(wtc_match_sql("m"))
        recs = con.execute(
            f"""
            SELECT pf.*, p.display_name, p.slug,
                   CASE WHEN pf.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
                   m.venue, m.winner, m.result_method, m.start_date
            FROM performances_t20 pf
            JOIN people p ON p.person_id = pf.person_id
            JOIN matches m ON m.match_id = pf.match_id
            WHERE {' AND '.join(where)}
            ORDER BY pf.blend DESC
            LIMIT ?
            """,
            params + [int(limit)],
        ).fetchdf()
        rows = recs.to_dict("records") if not recs.empty else []
        for rank, r in enumerate(rows, start=1):
            r["rank"] = rank
            r["player"] = r.get("display_name")
            r["result"] = "Won" if r.get("winner") == r.get("team") else ("Lost" if r.get("winner") else "—")
            r["composite"] = round(100 + 10 * float(r.get("blend") or 0), 1)
            r["bat_line"] = r.get("line") if r.get("discipline") == "bat" else None
            r["bowl_line"] = r.get("line") if r.get("discipline") == "bowl" else None
        return {
            "rows": _jsonable(rows),
            "caption": "Composite index: 100 is the reference line; each 10 points is one blended standard deviation.",
        }
    except Exception:
        return {"rows": [], "caption": "Rebuild T20 metrics to score performances."}
    finally:
        con.close()


def _scope(comp, gender, n, wtc=False) -> str:
    bits = [f"{n:,} players" if n != 1 else "1 player"]
    if comp:
        bits.append(POOL_LABELS.get(comp, LABELS.get(comp, comp)))
    if gender:
        bits.append("Men" if gender == "male" else "Women")
    if wtc:
        bits.append("WTC sides")
    bits.append("in this warehouse")
    return " · ".join(bits)


def _jsonable(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        item = {}
        for k, v in r.items():
            if hasattr(v, "item"):
                try:
                    v = v.item()
                except Exception:
                    v = None
            if isinstance(v, float) and v != v:
                v = None
            item[k] = v
        out.append(item)
    return out


PULSE_TIERS = ("top", "internationals", "leagues", "all")


def _pulse_tier_sql(tier: str, alias: str = "m") -> str:
    """Keep the home feed on cricket a fan follows. Associate internationals are the noise."""
    if tier == "internationals":
        return (
            f"{alias}.competition IN ('test','odi','t20i') "
            f"AND {alias}.team_home IN (SELECT team FROM wtc_teams) "
            f"AND {alias}.team_away IN (SELECT team FROM wtc_teams)"
        )
    if tier == "leagues":
        return f"{alias}.competition IN ('ipl','wpl','bbl','wbbl')"
    if tier == "top":
        return wtc_match_sql(alias)
    return "1=1"


def pulse(limit: int = 8, tier: str = "top", gender: str | None = None) -> dict[str, Any]:
    if not warehouse_ready():
        return {"hundreds": [], "five_fors": [], "matches": [], "tier": tier}
    n = max(int(limit), 1)
    tier = tier if tier in PULSE_TIERS else "top"
    con = connect()
    try:
        _attach_wtc(con, gender)
        gate = _pulse_tier_sql(tier)
        gender_gate = "AND m.gender = ?" if gender in {"male", "female"} else ""
        gender_args: list[Any] = [gender] if gender_gate else []
        hundreds = con.execute(
            f"""
            SELECT b.runs, b.balls, b.not_out, b.match_id, b.team,
                   p.display_name, p.slug, m.start_date, m.competition, m.venue,
                   CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition
            FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            JOIN people p ON p.person_id = b.person_id
            WHERE b.innings_kind = 'regular' AND b.runs >= 100 AND {gate} {gender_gate}
            ORDER BY m.start_date DESC
            LIMIT ?
            """,
            [*gender_args, n],
        ).fetchdf()
        five = con.execute(
            f"""
            SELECT bl.wickets, bl.runs, bl.legal_balls, bl.match_id, bl.team,
                   p.display_name, p.slug, m.start_date, m.competition, m.venue,
                   CASE WHEN bl.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition
            FROM bowling_lines bl
            JOIN matches m ON m.match_id = bl.match_id
            JOIN people p ON p.person_id = bl.person_id
            WHERE bl.innings_kind = 'regular' AND bl.wickets >= 5 AND {gate} {gender_gate}
            ORDER BY m.start_date DESC
            LIMIT ?
            """,
            [*gender_args, n],
        ).fetchdf()
        matches = con.execute(
            f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner, m.competition,
                   m.gender, m.venue, m.event_name, m.event_stage,
                   m.win_by_runs, m.win_by_wickets, m.win_by_innings
            FROM matches m
            WHERE {gate} {gender_gate}
            ORDER BY m.start_date DESC
            LIMIT ?
            """,
            [*gender_args, n],
        ).fetchdf()

        def pack(df):
            return _jsonable(df.to_dict("records") if not df.empty else [])

        hundreds_rows = pack(hundreds)
        for r in hundreds_rows:
            r["line"] = f"{int(r['runs'])}{'*' if r.get('not_out') else ''} ({int(r.get('balls') or 0)})"
            r["comp"] = LABELS.get(r.get("competition"), r.get("competition"))
        five_rows = pack(five)
        for r in five_rows:
            balls = int(r.get("legal_balls") or 0)
            r["line"] = f"{int(r['wickets'])}/{int(r.get('runs') or 0)} ({balls // 6}.{balls % 6})"
            r["comp"] = LABELS.get(r.get("competition"), r.get("competition"))
        match_rows = pack(matches)
        for r in match_rows:
            r["comp"] = LABELS.get(r.get("competition"), r.get("competition"))
            r["gender_label"] = GENDER_LABEL.get(r.get("gender"), r.get("gender"))
            r["result"] = _result_line(r)
        return {
            "hundreds": hundreds_rows,
            "five_fors": five_rows,
            "matches": match_rows,
            "tier": tier,
        }
    finally:
        con.close()


def _result_line(r: dict) -> str:
    if r.get("winner") and r.get("win_by_innings"):
        return f"{r['winner']} by an innings and {int(r['win_by_runs'] or 0)} runs"
    if r.get("winner") and r.get("win_by_runs"):
        return f"{r['winner']} by {int(r['win_by_runs'])} runs"
    if r.get("winner") and r.get("win_by_wickets"):
        return f"{r['winner']} by {int(r['win_by_wickets'])} wkts"
    if r.get("winner"):
        return f"{r['winner']} won"
    return "No result"


def on_this_day(*, month: int, day: int, limit: int = 6) -> dict[str, Any]:
    """Matches and innings from this calendar date in earlier years."""
    if not warehouse_ready():
        return {"matches": [], "innings": [], "month": month, "day": day}
    con = connect()
    try:
        _attach_wtc(con, None)
        stamp = f"-{month:02d}-{day:02d}"
        matches = con.execute(
            f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner, m.competition,
                   m.gender, m.venue, m.event_name, m.event_stage,
                   m.win_by_runs, m.win_by_wickets, m.win_by_innings
            FROM matches m
            WHERE substr(m.start_date, 5, 6) = ? AND {wtc_match_sql('m')}
            ORDER BY m.start_date DESC
            LIMIT ?
            """,
            [stamp, max(int(limit), 1)],
        ).fetchdf()
        knocks = con.execute(
            f"""
            SELECT b.runs, b.balls, b.not_out, b.match_id, b.team,
                   p.display_name, p.slug, m.start_date, m.competition,
                   CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition
            FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            JOIN people p ON p.person_id = b.person_id
            WHERE substr(m.start_date, 5, 6) = ? AND b.innings_kind = 'regular'
              AND b.runs >= 100 AND {wtc_match_sql('m')}
            ORDER BY b.runs DESC
            LIMIT ?
            """,
            [stamp, max(int(limit), 1)],
        ).fetchdf()
        match_rows = _jsonable(matches.to_dict("records") if not matches.empty else [])
        for r in match_rows:
            r["comp"] = LABELS.get(r.get("competition"), r.get("competition"))
            r["result"] = _result_line(r)
            r["year"] = str(r.get("start_date") or "")[:4]
        knock_rows = _jsonable(knocks.to_dict("records") if not knocks.empty else [])
        for r in knock_rows:
            r["comp"] = LABELS.get(r.get("competition"), r.get("competition"))
            r["line"] = f"{int(r['runs'])}{'*' if r.get('not_out') else ''} ({int(r.get('balls') or 0)})"
            r["year"] = str(r.get("start_date") or "")[:4]
        return {"matches": match_rows, "innings": knock_rows, "month": month, "day": day}
    finally:
        con.close()


DISMISS_LABEL = {
    "caught": "Caught",
    "bowled": "Bowled",
    "lbw": "LBW",
    "run out": "Run out",
    "stumped": "Stumped",
    "caught and bowled": "C&B",
    "hit wicket": "Hit wicket",
    "retired hurt": "Retired hurt",
    "obstructing the field": "Obstructing",
}


def player_almanac(con, person_id: str) -> dict[str, Any]:
    """Counting cuts a fan expects on a player page — from lines already in the warehouse."""

    def rows(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict]:
        try:
            recs = con.execute(sql, list(params)).fetchdf()
        except Exception:
            return []
        return _jsonable(recs.to_dict("records") if recs is not None and not recs.empty else [])

    def one(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> dict | None:
        got = rows(sql, params)
        return got[0] if got else None

    dismissals = rows(
        """
        SELECT COALESCE(NULLIF(dismissal_kind, ''), 'not out') AS kind, COUNT(*) AS n
        FROM batting_lines
        WHERE person_id = ? AND innings_kind = 'regular'
        GROUP BY 1
        ORDER BY n DESC
        """,
        [person_id],
    )
    for r in dismissals:
        raw = (r.get("kind") or "").lower()
        r["label"] = "Not out" if raw in {"", "not out"} or r.get("kind") is None else DISMISS_LABEL.get(raw, (r.get("kind") or "").title())

    positions = rows(
        """
        SELECT position, COUNT(*) AS n, SUM(runs) AS runs,
               ROUND(AVG(runs), 1) AS avg
        FROM batting_lines
        WHERE person_id = ? AND innings_kind = 'regular' AND position IS NOT NULL
        GROUP BY 1
        ORDER BY position
        """,
        [person_id],
    )

    vs = rows(
        """
        SELECT CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               COUNT(*) AS inns, SUM(b.runs) AS runs, MAX(b.runs) AS hs,
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs,
               SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'
        GROUP BY 1
        ORDER BY SUM(b.runs) DESC
        LIMIT 8
        """,
        [person_id],
    )
    for r in vs:
        outs = r.get("outs") or 0
        r["avg"] = round(r["runs"] / outs, 1) if outs and r.get("runs") is not None else None

    years = rows(
        """
        SELECT CAST(substr(m.start_date, 1, 4) AS INTEGER) AS year,
               SUM(b.runs) AS runs, COUNT(*) AS inns, MAX(b.runs) AS hs,
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs,
               SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'
        GROUP BY 1
        ORDER BY 1
        """,
        [person_id],
    )
    for r in years:
        outs = r.get("outs") or 0
        r["avg"] = round(r["runs"] / outs, 1) if outs and r.get("runs") is not None else None

    bowl_years = rows(
        """
        SELECT CAST(substr(m.start_date, 1, 4) AS INTEGER) AS year,
               COUNT(*) AS inns, SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
               SUM(bl.legal_balls) AS legal_balls
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
        GROUP BY 1
        ORDER BY 1
        """,
        [person_id],
    )
    for r in bowl_years:
        balls = r.get("legal_balls") or 0
        wk = r.get("wickets") or 0
        r["econ"] = round(r["runs"] * 6 / balls, 2) if balls and r.get("runs") is not None else None
        r["avg"] = round(r["runs"] / wk, 1) if wk and r.get("runs") is not None else None
        r["sr"] = round(balls / wk, 1) if wk else None

    ha = rows(
        """
        SELECT CASE WHEN b.team = m.team_home THEN 'Home' ELSE 'Away' END AS split,
               COUNT(*) AS inns, SUM(b.runs) AS runs,
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'
        GROUP BY 1
        """,
        [person_id],
    )
    for r in ha:
        outs = r.get("outs") or 0
        r["avg"] = round(r["runs"] / outs, 1) if outs and r.get("runs") is not None else None

    chase = rows(
        """
        SELECT CASE WHEN b.innings = 1 THEN 'Set' ELSE 'Chase' END AS split,
               COUNT(*) AS inns, SUM(b.runs) AS runs,
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'
          AND m.competition IN ('odi','t20i','ipl','wpl','bbl','wbbl')
        GROUP BY 1
        """,
        [person_id],
    )
    for r in chase:
        outs = r.get("outs") or 0
        r["avg"] = round(r["runs"] / outs, 1) if outs and r.get("runs") is not None else None

    conversion = one(
        """
        SELECT COUNT(*) AS inns,
               SUM(CASE WHEN NOT not_out THEN 1 ELSE 0 END) AS outs,
               SUM(runs) AS runs,
               SUM(balls) AS balls,
               SUM(fours) AS fours,
               SUM(sixes) AS sixes,
               SUM(CASE WHEN runs >= 100 THEN 1 ELSE 0 END) AS hundreds,
               SUM(CASE WHEN runs >= 50 AND runs < 100 THEN 1 ELSE 0 END) AS fifties,
               SUM(CASE WHEN runs = 0 AND NOT not_out THEN 1 ELSE 0 END) AS ducks,
               MAX(runs) AS hs
        FROM batting_lines
        WHERE person_id = ? AND innings_kind = 'regular'
        """,
        [person_id],
    ) or {}
    fifties = int(conversion.get("fifties") or 0)
    hundreds = int(conversion.get("hundreds") or 0)
    starts_50 = fifties + hundreds
    conversion["conversion"] = round(100.0 * hundreds / starts_50, 1) if starts_50 else None
    balls = conversion.get("balls") or 0
    bounds = (conversion.get("fours") or 0) + (conversion.get("sixes") or 0)
    conversion["boundary_pct"] = round(100.0 * bounds / balls, 1) if balls else None

    venues = rows(
        """
        SELECT m.venue, COUNT(*) AS inns, SUM(b.runs) AS runs, MAX(b.runs) AS hs,
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular' AND m.venue IS NOT NULL
        GROUP BY 1
        ORDER BY SUM(b.runs) DESC
        LIMIT 6
        """,
        [person_id],
    )
    for r in venues:
        outs = r.get("outs") or 0
        r["avg"] = round(r["runs"] / outs, 1) if outs and r.get("runs") is not None else None

    win_loss = rows(
        """
        SELECT CASE
                 WHEN m.winner = b.team THEN 'Won'
                 WHEN m.winner IS NOT NULL THEN 'Lost'
                 ELSE 'Draw / NR'
               END AS split,
               COUNT(*) AS inns, SUM(b.runs) AS runs,
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'
        GROUP BY 1
        """,
        [person_id],
    )
    for r in win_loss:
        outs = r.get("outs") or 0
        r["avg"] = round(r["runs"] / outs, 1) if outs and r.get("runs") is not None else None

    phases = rows(
        """
        WITH ord AS (
          SELECT b.runs, b.not_out,
                 ROW_NUMBER() OVER (ORDER BY m.start_date, b.innings) AS rn,
                 COUNT(*) OVER () AS n
          FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
          WHERE b.person_id = ? AND b.innings_kind = 'regular'
        )
        SELECT CASE
                 WHEN n < 80 THEN 'Career'
                 WHEN rn <= 50 THEN 'First 50'
                 WHEN rn > n - 50 THEN 'Last 50'
                 ELSE 'Middle'
               END AS split,
               COUNT(*) AS inns, SUM(runs) AS runs,
               SUM(CASE WHEN NOT not_out THEN 1 ELSE 0 END) AS outs
        FROM ord
        GROUP BY 1
        """,
        [person_id],
    )
    for r in phases:
        outs = r.get("outs") or 0
        r["avg"] = round(r["runs"] / outs, 1) if outs and r.get("runs") is not None else None

    formats = rows(
        """
        SELECT m.competition, COUNT(DISTINCT x.match_id) AS matches
        FROM xi x JOIN matches m ON m.match_id = x.match_id
        WHERE x.person_id = ?
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        [person_id],
    )
    for r in formats:
        r["label"] = LABELS.get(r.get("competition"), r.get("competition"))

    roles = one(
        """
        SELECT SUM(CASE WHEN is_captain THEN 1 ELSE 0 END) AS captain,
               SUM(CASE WHEN is_keeper THEN 1 ELSE 0 END) AS keeper,
               COUNT(*) AS xi
        FROM xi WHERE person_id = ?
        """,
        [person_id],
    ) or {"captain": 0, "keeper": 0, "xi": 0}

    debut = one(
        """
        SELECT m.match_id, m.start_date, m.competition,
               CASE WHEN x.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               x.team
        FROM xi x JOIN matches m ON m.match_id = x.match_id
        WHERE x.person_id = ?
        ORDER BY m.start_date
        LIMIT 1
        """,
        [person_id],
    )
    latest = one(
        """
        SELECT m.match_id, m.start_date, m.competition,
               CASE WHEN x.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               x.team
        FROM xi x JOIN matches m ON m.match_id = x.match_id
        WHERE x.person_id = ?
        ORDER BY m.start_date DESC
        LIMIT 1
        """,
        [person_id],
    )

    last5 = rows(
        """
        SELECT b.runs, b.not_out, b.balls, m.start_date, m.match_id,
               CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               m.competition
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'
        ORDER BY m.start_date DESC
        LIMIT 10
        """,
        [person_id],
    )

    last_bowl = rows(
        """
        SELECT bl.wickets, bl.runs, bl.legal_balls, bl.maidens, m.start_date, m.match_id,
               CASE WHEN bl.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               m.competition
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
        ORDER BY m.start_date DESC
        LIMIT 10
        """,
        [person_id],
    )

    hauls = one(
        """
        SELECT COUNT(*) AS inns,
               SUM(wickets) AS wickets,
               SUM(runs) AS runs,
               SUM(legal_balls) AS legal_balls,
               SUM(maidens) AS maidens,
               SUM(CASE WHEN wickets >= 5 THEN 1 ELSE 0 END) AS five_fors,
               SUM(CASE WHEN wickets = 4 THEN 1 ELSE 0 END) AS four_fors,
               SUM(CASE WHEN wickets = 3 THEN 1 ELSE 0 END) AS three_fors
        FROM bowling_lines
        WHERE person_id = ? AND innings_kind = 'regular'
        """,
        [person_id],
    ) or {}
    wk = int(hauls.get("wickets") or 0)
    legal = int(hauls.get("legal_balls") or 0)
    conceded = int(hauls.get("runs") or 0)
    hauls["avg"] = round(conceded / wk, 1) if wk else None
    hauls["econ"] = round(conceded * 6 / legal, 2) if legal else None
    hauls["sr"] = round(legal / wk, 1) if wk else None

    bowl_vs = rows(
        """
        SELECT CASE WHEN bl.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               COUNT(*) AS inns, SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
               SUM(bl.legal_balls) AS legal_balls
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
        GROUP BY 1
        ORDER BY SUM(bl.wickets) DESC
        LIMIT 8
        """,
        [person_id],
    )
    for r in bowl_vs:
        w = r.get("wickets") or 0
        balls = r.get("legal_balls") or 0
        r["avg"] = round(r["runs"] / w, 1) if w and r.get("runs") is not None else None
        r["econ"] = round(r["runs"] * 6 / balls, 2) if balls and r.get("runs") is not None else None

    bowl_venues = rows(
        """
        SELECT m.venue, COUNT(*) AS inns, SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
               SUM(bl.legal_balls) AS legal_balls
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.person_id = ? AND bl.innings_kind = 'regular' AND m.venue IS NOT NULL
        GROUP BY 1
        ORDER BY SUM(bl.wickets) DESC
        LIMIT 6
        """,
        [person_id],
    )
    for r in bowl_venues:
        w = r.get("wickets") or 0
        balls = r.get("legal_balls") or 0
        r["avg"] = round(r["runs"] / w, 1) if w and r.get("runs") is not None else None
        r["econ"] = round(r["runs"] * 6 / balls, 2) if balls and r.get("runs") is not None else None

    bowl_ha = rows(
        """
        SELECT CASE WHEN bl.team = m.team_home THEN 'Home' ELSE 'Away' END AS split,
               COUNT(*) AS inns, SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
               SUM(bl.legal_balls) AS legal_balls
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
        GROUP BY 1
        """,
        [person_id],
    )
    for r in bowl_ha:
        w = r.get("wickets") or 0
        balls = r.get("legal_balls") or 0
        r["avg"] = round(r["runs"] / w, 1) if w and r.get("runs") is not None else None
        r["econ"] = round(r["runs"] * 6 / balls, 2) if balls and r.get("runs") is not None else None

    bowl_win_loss = rows(
        """
        SELECT CASE
                 WHEN m.winner = bl.team THEN 'Won'
                 WHEN m.winner IS NOT NULL THEN 'Lost'
                 ELSE 'Draw / NR'
               END AS split,
               COUNT(*) AS inns, SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
               SUM(bl.legal_balls) AS legal_balls
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
        GROUP BY 1
        """,
        [person_id],
    )
    for r in bowl_win_loss:
        w = r.get("wickets") or 0
        balls = r.get("legal_balls") or 0
        r["avg"] = round(r["runs"] / w, 1) if w and r.get("runs") is not None else None
        r["econ"] = round(r["runs"] * 6 / balls, 2) if balls and r.get("runs") is not None else None

    bowl_kinds_raw = rows(
        """
        SELECT COALESCE(NULLIF(d.wicket_kind, ''), 'unknown') AS kind, COUNT(*) AS n
        FROM deliveries d
        WHERE d.bowler = ? AND d.innings_kind = 'regular'
          AND COALESCE(d.d_bowl, 0) > 0
        GROUP BY 1
        """,
        [person_id],
    )
    bowl_kind_counts: dict[str, int] = {}
    for r in bowl_kinds_raw:
        label = dismissal_group(r.get("kind"))
        if label == "Not out":
            continue
        bowl_kind_counts[label] = bowl_kind_counts.get(label, 0) + int(r.get("n") or 0)
    bowl_dismissals = [
        {"label": k, "n": v} for k, v in sorted(bowl_kind_counts.items(), key=lambda x: (-x[1], x[0]))
    ]

    return {
        "dismissals": dismissals,
        "positions": positions,
        "vs": vs,
        "years": years,
        "bowl_years": bowl_years,
        "home_away": ha,
        "chase": chase,
        "conversion": conversion,
        "venues": venues,
        "formats": formats,
        "roles": roles,
        "debut": debut,
        "latest": latest,
        "last5": last5,
        "last_bowl": last_bowl,
        "hauls": hauls,
        "bowl_vs": bowl_vs,
        "bowl_venues": bowl_venues,
        "bowl_home_away": bowl_ha,
        "bowl_win_loss": bowl_win_loss,
        "bowl_dismissals": bowl_dismissals,
        "win_loss": win_loss,
        "phases": phases,
    }

