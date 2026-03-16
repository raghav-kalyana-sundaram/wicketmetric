from __future__ import annotations

import re
from typing import Any

from cricwarehouse.competitions import LABELS
from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.app.query import _people_match


def search(q: str) -> dict[str, Any]:
    q = (q or "").strip()
    if not warehouse_ready() or len(q) < 1:
        return {"people": [], "teams": [], "destinations": _destinations(q)}
    con = connect()
    try:
        people = _people_match(con, q)
        teams = [
            {"team": r[0]}
            for r in con.execute(
                """
                SELECT DISTINCT team FROM (
                  SELECT team_home AS team FROM matches
                  UNION
                  SELECT team_away AS team FROM matches
                )
                WHERE lower(team) LIKE ?
                ORDER BY team
                LIMIT 8
                """,
                [f"%{q.lower()}%"],
            ).fetchall()
        ]
        return {"people": people, "teams": teams, "destinations": _destinations(q)}
    finally:
        con.close()


def _destinations(q: str) -> list[dict]:
    dest = [
        {"id": "stats", "label": "Stats table", "hint": "Master batting and bowling, with percentiles"},
        {"id": "wowy", "label": "WOWY", "hint": "With or without a player"},
        {"id": "rankings", "label": "Rankings", "hint": "Runs, wickets, WAR in this warehouse"},
    ]
    ql = q.lower()
    if ql:
        dest = [d for d in dest if ql in d["id"] or ql in d["label"].lower() or ql in d["hint"].lower()] or dest
    return dest


def master_stats(
    *,
    comp: str | None = None,
    gender: str | None = None,
    min_inns: int = 5,
    role: str = "all",
    sort: str = "runs",
) -> dict[str, Any]:
    if not warehouse_ready():
        return {"rows": [], "scope": "Warehouse not built"}
    con = connect()
    try:
        bat_w = ["b.innings_kind = 'regular'"]
        bowl_w = ["bl.innings_kind = 'regular'"]
        params: list[Any] = []
        bparams: list[Any] = []
        if comp:
            bat_w.append("m.competition = ?")
            bowl_w.append("m.competition = ?")
            params.append(comp)
            bparams.append(comp)
        if gender:
            bat_w.append("m.gender = ?")
            bowl_w.append("m.gender = ?")
            params.append(gender)
            bparams.append(gender)
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
               ROUND(PERCENT_RANK() OVER (ORDER BY j.runs) * 100) AS runs_pct,
               ROUND(PERCENT_RANK() OVER (ORDER BY j.wickets) * 100) AS wickets_pct,
               ROUND(PERCENT_RANK() OVER (
                 ORDER BY CASE WHEN j.outs >= 8 THEN j.runs * 1.0 / j.outs END
               ) * 100) AS avg_pct,
               ROUND(PERCENT_RANK() OVER (
                 ORDER BY CASE WHEN j.wickets >= 10 THEN j.bowl_runs * 1.0 / j.wickets END DESC
               ) * 100) AS bowl_avg_pct
        FROM joined j
        JOIN people p ON p.person_id = j.person_id
        WHERE (j.inns >= ? OR j.wickets >= ?)
        """
        floor = max(int(min_inns), 1)
        recs = con.execute(sql, params + bparams + [floor, floor]).fetchdf()
        if recs.empty:
            return {"rows": [], "scope": _scope(comp, gender, 0)}
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
        }.get(sort, "runs")
        reverse = key not in {"bowl_avg", "econ"}
        rows.sort(key=lambda r: (r.get(key) is not None, r.get(key) or 0), reverse=reverse)
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
            r["player"] = r.get("display_name")
            overs = int(r.get("legal_balls") or 0)
            r["overs"] = f"{overs // 6}.{overs % 6}" if overs else None
        return {
            "rows": _jsonable(rows),
            "scope": _scope(comp, gender, len(rows)),
        }
    finally:
        con.close()


def rankings(*, metric: str = "runs", comp: str | None = None, gender: str | None = None, min_inns: int = 5) -> dict:
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
            r["econ"] = r.get("war")
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
        needle = player.strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", needle).strip("-")
        exact = [
            p
            for p in people
            if p["slug"] == slug
            or (p.get("unique_name") or "").lower() == needle
            or (p.get("person_id") or "").lower() == needle
        ]
        top, nxt = people[0], people[1] if len(people) > 1 else None
        clear_lead = int(top.get("apps") or 0) >= 15 and int(top.get("apps") or 0) >= 3 * max(int((nxt or {}).get("apps") or 0), 1)
        if len(people) > 1 and not exact and not clear_lead:
            return {
                "ok": True,
                "kind": "pick_player",
                "people": people,
                "rows": [],
                "message": f"{len(people)} players match “{player}”. Pick one.",
            }
        person = exact[0] if exact else people[0]
        pid = person["person_id"]
        where = ["(m.team_home ILIKE ? OR m.team_away ILIKE ?)"]
        params: list[Any] = [f"%{team}%", f"%{team}%"]
        if comp:
            where.append("m.competition = ?")
            params.append(comp)
        if gender:
            where.append("m.gender = ?")
            params.append(gender)
        matches = con.execute(
            f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner, m.competition,
                   EXISTS (
                     SELECT 1 FROM xi x
                     WHERE x.match_id = m.match_id AND x.person_id = ?
                       AND x.team ILIKE ?
                   ) AS present
            FROM matches m
            WHERE {' AND '.join(where)}
            """,
            [pid, f"%{team}%"] + params,
        ).fetchall()

        def pack(group, label):
            ids = [r[0] for r in group]
            n = len(ids)
            wins = sum(1 for r in group if r[4] and team.lower() in str(r[4]).lower())
            if not ids:
                return {
                    "split": label, "matches": 0, "wins": 0, "win_pct": None,
                    "runs_for": None, "runs_against": None, "wickets": None,
                }
            placeholders = ",".join(["?"] * len(ids))
            rf, ra, wk = con.execute(
                f"""
                SELECT
                  SUM(CASE WHEN i.batting_team ILIKE ? THEN i.runs ELSE 0 END),
                  SUM(CASE WHEN i.bowling_team ILIKE ? THEN i.runs ELSE 0 END),
                  SUM(CASE WHEN i.bowling_team ILIKE ? THEN i.wickets ELSE 0 END)
                FROM innings i
                WHERE i.match_id IN ({placeholders}) AND i.innings_kind = 'regular'
                """,
                [f"%{team}%", f"%{team}%", f"%{team}%"] + ids,
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
            "team": team,
            "people": people,
            "rows": rows,
            "scope": f"{team} · {person['display_name']} · in this warehouse",
            "caption": "On/off for the side. Small samples stay noisy — this is a split, not RAPM.",
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


def _scope(comp, gender, n) -> str:
    bits = [f"{n:,} players" if n != 1 else "1 player"]
    if comp:
        bits.append(LABELS.get(comp, comp))
    if gender:
        bits.append("Men" if gender == "male" else "Women")
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
