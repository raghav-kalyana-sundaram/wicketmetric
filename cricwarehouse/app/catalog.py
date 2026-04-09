from __future__ import annotations

import re
from typing import Any

from cricwarehouse.competitions import GENDER_LABEL, LABELS
from cricwarehouse.teams import (
    METRIC_COPY,
    POOL_LABELS,
    default_pool,
    parse_comps,
    wtc_match_sql,
    wtc_params,
)
from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.app.query import _people_match

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
        {"id": "stats", "label": "Stats table", "hint": "Master batting and bowling, with percentiles and WAR"},
        {"id": "wowy", "label": "WOWY", "hint": "With or without a player"},
        {"id": "best", "label": "Best T20", "hint": "Greatest match composites in this warehouse"},
        {"id": "compare", "label": "Compare", "hint": "Two players, side by side"},
        {"id": "teams", "label": "Team compare", "hint": "Two sides, same season"},
        {"id": "twin", "label": "Profile twin", "hint": "Closest T20 shape in this warehouse"},
        {"id": "shift", "label": "Stat line shift", "hint": "How teammates change with you"},
    ]
    ql = q.lower()
    if ql:
        dest = [d for d in dest if ql in d["id"] or ql in d["label"].lower() or ql in d["hint"].lower()] or dest
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
                 COUNT(DISTINCT season) AS seasons
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
               v.war, v.wpa, v.pressure, v.seasons,
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
        WHERE (j.inns >= ? OR j.wickets >= ?)
        """
        floor = max(int(min_inns), 1)
        try:
            recs = con.execute(sql, params + bparams + vparams + gparams + [floor, floor]).fetchdf()
        except Exception:
            recs = con.execute(
                sql.replace("LEFT JOIN val v ON v.person_id = j.person_id", "")
                .replace("LEFT JOIN games g ON g.person_id = j.person_id", "")
                .replace("v.war, v.wpa, v.pressure, v.seasons,", "NULL AS war, NULL AS wpa, NULL AS pressure, NULL AS seasons,")
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
        }.get(sort, "runs")
        reverse = key not in {"bowl_avg", "econ"}

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
        first = con.execute(
            f"""
            SELECT MIN(m.start_date)
            FROM matches m
            JOIN xi x ON x.match_id = m.match_id
            WHERE x.person_id = ? AND x.team ILIKE ?
              AND {' AND '.join(where)}
            """,
            [pid, f"%{team}%"] + params,
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
            "scope": f"{team} · {person['display_name']} · from {first[:10] if first else '—'} · in this warehouse",
            "available_from": first,
            "caption": (
                f"Only matches on or after {person['display_name']}'s first XI for {team}"
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
            ("rae_bat", True),
            ("rae_bowl", True),
            ("wpa", True),
            ("pressure", True),
        ):
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
            ("rae_bat", "RAE bat / game"),
            ("rae_bowl", "RAE bowl / game"),
            ("wpa", "WPA"),
            ("pressure", "Pressure"),
        ):
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


def pulse(limit: int = 8) -> dict[str, Any]:
    if not warehouse_ready():
        return {"hundreds": [], "five_fors": [], "matches": []}
    n = max(int(limit), 1)
    con = connect()
    try:
        hundreds = con.execute(
            """
            SELECT b.runs, b.balls, b.not_out, b.match_id, b.team,
                   p.display_name, p.slug, m.start_date, m.competition, m.venue,
                   CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition
            FROM batting_lines b
            JOIN matches m ON m.match_id = b.match_id
            JOIN people p ON p.person_id = b.person_id
            WHERE b.innings_kind = 'regular' AND b.runs >= 100
            ORDER BY m.start_date DESC
            LIMIT ?
            """,
            [n],
        ).fetchdf()
        five = con.execute(
            """
            SELECT bl.wickets, bl.runs, bl.legal_balls, bl.match_id, bl.team,
                   p.display_name, p.slug, m.start_date, m.competition, m.venue,
                   CASE WHEN bl.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition
            FROM bowling_lines bl
            JOIN matches m ON m.match_id = bl.match_id
            JOIN people p ON p.person_id = bl.person_id
            WHERE bl.innings_kind = 'regular' AND bl.wickets >= 5
            ORDER BY m.start_date DESC
            LIMIT ?
            """,
            [n],
        ).fetchdf()
        matches = con.execute(
            """
            SELECT match_id, start_date, team_home, team_away, winner, competition, gender, venue,
                   win_by_runs, win_by_wickets
            FROM matches
            ORDER BY start_date DESC
            LIMIT ?
            """,
            [n],
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
            if r.get("winner") and r.get("win_by_runs"):
                r["result"] = f"{r['winner']} by {int(r['win_by_runs'])} runs"
            elif r.get("winner") and r.get("win_by_wickets"):
                r["result"] = f"{r['winner']} by {int(r['win_by_wickets'])} wkts"
            elif r.get("winner"):
                r["result"] = f"{r['winner']} won"
            else:
                r["result"] = "No result"
        return {"hundreds": hundreds_rows, "five_fors": five_rows, "matches": match_rows}
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
               SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
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
        r["econ"] = round(r["runs"] * 6 / balls, 2) if balls and r.get("runs") is not None else None

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
        "win_loss": win_loss,
        "phases": phases,
    }

