"""Compare studio: match composites, player/team compare, twins, stat-line shift."""

from __future__ import annotations

from typing import Any

from cricwarehouse.app.catalog import _attach_wtc, _jsonable, _people_match
from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.teams import POOL_LABELS, default_pool, parse_comps, wtc_match_sql
from cricwarehouse.app.catalog import career_value, matchups


def resolve_person(con, needle: str) -> dict | None:
    people = _people_match(con, needle)
    if not people:
        return None
    if len(people) == 1:
        return people[0]
    top, nxt = people[0], people[1] if len(people) > 1 else None
    if int(top.get("apps") or 0) >= 15 and int(top.get("apps") or 0) >= 3 * max(int((nxt or {}).get("apps") or 0), 1):
        return top
    return {"pick": people}


def list_match_composites(
    *,
    person_id: str | None = None,
    comp: str | None = None,
    gender: str | None = None,
    wtc: bool = False,
    focus: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """One row per player-match: balls-weighted blend of bat and bowl scores."""
    if not warehouse_ready():
        return {"rows": [], "caption": "Warehouse not built"}
    con = connect()
    try:
        if wtc:
            _attach_wtc(con, gender)
        where = ["1=1"]
        params: list[Any] = []
        if person_id:
            where.append("pf.person_id = ?")
            params.append(person_id)
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
        if focus == "bat":
            floor = "g.bat_balls >= 10"
            score_sql = "ROUND(g.bat_w / NULLIF(g.bat_balls, 0), 1)"
        elif focus == "bowl":
            floor = "g.bowl_balls >= 6"
            score_sql = "ROUND(g.bowl_w / NULLIF(g.bowl_balls, 0), 1)"
        else:
            floor = "g.bat_balls + g.bowl_balls >= 12"
            score_sql = "ROUND((g.bat_w + g.bowl_w) / NULLIF(g.bat_balls + g.bowl_balls, 0), 1)"
        recs = con.execute(
            f"""
            WITH g AS (
              SELECT pf.person_id, pf.match_id, pf.competition, pf.gender, pf.team,
                     SUM(CASE WHEN pf.discipline = 'bat' THEN pf.balls ELSE 0 END) AS bat_balls,
                     SUM(CASE WHEN pf.discipline = 'bowl' THEN pf.balls ELSE 0 END) AS bowl_balls,
                     SUM(CASE WHEN pf.discipline = 'bat' THEN pf.score * pf.balls ELSE 0 END) AS bat_w,
                     SUM(CASE WHEN pf.discipline = 'bowl' THEN pf.score * pf.balls ELSE 0 END) AS bowl_w,
                     MAX(CASE WHEN pf.discipline = 'bat' THEN pf.line END) AS bat_line,
                     MAX(CASE WHEN pf.discipline = 'bowl' THEN pf.line END) AS bowl_line,
                     SUM(pf.nrc) AS nrc,
                     SUM(pf.wpa_runs) AS wpa_runs
              FROM performances_t20 pf
              JOIN matches m ON m.match_id = pf.match_id
              WHERE {' AND '.join(where)}
              GROUP BY 1,2,3,4,5
            )
            SELECT g.*, p.display_name, p.slug,
                   CASE WHEN g.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
                   m.venue, m.winner, m.start_date, m.result_method,
                   {score_sql} AS score
            FROM g
            JOIN people p ON p.person_id = g.person_id
            JOIN matches m ON m.match_id = g.match_id
            WHERE {floor}
            ORDER BY score DESC NULLS LAST
            LIMIT ?
            """,
            params + [int(limit)],
        ).fetchdf()
        rows = recs.to_dict("records") if not recs.empty else []

        def _ok_line(v):
            if v is None:
                return None
            if isinstance(v, float) and v != v:
                return None
            s = str(v).strip()
            if s.lower() in {"nan", "none", "nat", ""}:
                return None
            return s

        for r in rows:
            r["player"] = r.get("display_name")
            bat, bowl = _ok_line(r.get("bat_line")), _ok_line(r.get("bowl_line"))
            if bat and bowl:
                r["line"] = f"{bat} & {bowl}"
            else:
                r["line"] = bat or bowl
            r["result"] = "Won" if r.get("winner") == r.get("team") else ("Lost" if r.get("winner") else "—")
            r["discipline"] = focus or "match"
        cap = "Match composite: balls-weighted blend of batting and bowling 0–100 scores. A 40 and 2-12 in the same night both count. Percentiles stay within each competition."
        if focus == "bat":
            cap = "Ranked on batting percentile. Bowling from the same match is folded into the line when they bowled."
        elif focus == "bowl":
            cap = "Ranked on bowling percentile. Batting from the same match is folded into the line when they batted."
        return {
            "rows": _jsonable(rows),
            "caption": cap,
        }
    except Exception as e:
        return {"rows": [], "caption": f"Rebuild T20 metrics to score performances. ({e})"}
    finally:
        con.close()


def player_compare(a: str, b: str, *, pool: str | None = None) -> dict[str, Any]:
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built"}
    con = connect()
    try:
        pa, pb = resolve_person(con, a), resolve_person(con, b)
        if pa and pa.get("pick"):
            return {"ok": True, "kind": "pick", "side": "a", "people": pa["pick"]}
        if pb and pb.get("pick"):
            return {"ok": True, "kind": "pick", "side": "b", "people": pb["pick"]}
        if not pa or not pb:
            return {"ok": False, "error": "Need two players."}
        va = career_value(pa["person_id"], pool=pool)
        vb = career_value(pb["person_id"], pool=pool or va.get("pool"))
        h2h = _pair_h2h(con, pa["person_id"], pb["person_id"])
        ma = matchups(pa["person_id"])
        mb = matchups(pb["person_id"])
        return {
            "ok": True,
            "kind": "compare",
            "a": {**pa, "value": va, "matchups": _top_matchups(ma, 12)},
            "b": {**pb, "value": vb, "matchups": _top_matchups(mb, 12)},
            "h2h": h2h,
            "rows": _value_rows(va, vb),
            "pool": va.get("pool") or pool,
            "pool_label": va.get("pool_label"),
        }
    finally:
        con.close()


def _top_matchups(m: dict, n: int) -> dict:
    return {
        "as_batter": (m.get("as_batter") or [])[:n],
        "as_bowler": (m.get("as_bowler") or [])[:n],
    }


def _value_rows(va: dict, vb: dict) -> list[dict]:
    am = {m["key"]: m for m in va.get("metrics") or []}
    bm = {m["key"]: m for m in vb.get("metrics") or []}
    rows = []
    for key in ("war", "war_per_game", "rae_bat", "rae_bowl", "wpa", "pressure"):
        a, b = am.get(key) or {}, bm.get(key) or {}
        av, bv = a.get("value"), b.get("value")
        delta = None
        if av is not None and bv is not None:
            delta = round(float(av) - float(bv), 3)
        rows.append(
            {
                "key": key,
                "label": a.get("label") or b.get("label") or key,
                "a": av,
                "b": bv,
                "delta": delta,
                "a_rank": a.get("rank"),
                "b_rank": b.get("rank"),
                "copy": a.get("copy") or b.get("copy") or "",
            }
        )
    return rows


def _pair_h2h(con, a_id: str, b_id: str) -> dict[str, Any]:
    kinds = "'bowled','caught','caught and bowled','lbw','stumped','hit wicket'"
    def side(striker, bowler):
        row = con.execute(
            f"""
            SELECT
              SUM(CASE WHEN d.striker IS NOT NULL AND NOT d.is_wide THEN 1 ELSE 0 END) AS balls,
              SUM(CASE WHEN d.striker IS NOT NULL THEN d.runs_batter ELSE 0 END) AS runs,
              SUM(CASE WHEN d.player_out = d.striker AND d.wicket_kind IN ({kinds}) THEN 1 ELSE 0 END) AS dismissals,
              COUNT(DISTINCT d.match_id) AS matches
            FROM deliveries d
            WHERE d.striker = ? AND d.bowler = ? AND d.innings_kind = 'regular'
            """,
            [striker, bowler],
        ).fetchone()
        balls, runs, dsm, matches = [int(x or 0) for x in row]
        if balls < 6:
            return None
        return {
            "balls": balls,
            "runs": runs,
            "dismissals": dsm,
            "matches": matches,
            "sr": round(runs * 100 / balls, 1) if balls else None,
            "avg": round(runs / dsm, 1) if dsm else None,
            "econ": round(runs * 6 / balls, 2) if balls else None,
        }
    a_bat = side(a_id, b_id)
    b_bat = side(b_id, a_id)
    return {"a_faced_b": a_bat, "b_faced_a": b_bat}


def team_compare(
    team_a: str,
    team_b: str,
    *,
    comp: str = "t20i",
    season: str | None = None,
    gender: str = "male",
) -> dict[str, Any]:
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built"}
    con = connect()
    try:
        seasons = [
            r[0]
            for r in con.execute(
                """
                SELECT DISTINCT m.season FROM matches m
                WHERE m.competition = ? AND m.gender = ?
                  AND (m.team_home ILIKE ? OR m.team_away ILIKE ?)
                ORDER BY 1 DESC
                """,
                [comp, gender, f"%{team_a}%", f"%{team_a}%"],
            ).fetchall()
        ]
        if not season and seasons:
            season = seasons[0]

        def pack(team: str) -> dict:
            where = ["x.team ILIKE ?", "m.competition = ?", "m.gender = ?"]
            params: list[Any] = [f"%{team}%", comp, gender]
            if season:
                where.append("m.season = ?")
                params.append(season)
            recs = con.execute(
                f"""
                SELECT p.person_id, p.display_name, p.slug,
                       COUNT(DISTINCT x.match_id) AS matches,
                       ROUND(SUM(mt.war), 2) AS war,
                       ROUND(SUM(mt.rae_bat), 1) AS rae_bat,
                       ROUND(SUM(mt.rae_bowl), 1) AS rae_bowl,
                       CASE WHEN SUM(mt.balls_bowl) > SUM(mt.balls_bat) THEN 'bowl' ELSE 'bat' END AS primary_role
                FROM xi x
                JOIN matches m ON m.match_id = x.match_id
                JOIN people p ON p.person_id = x.person_id
                LEFT JOIN metrics_t20 mt
                  ON mt.person_id = x.person_id
                 AND mt.competition = m.competition
                 AND mt.season = m.season
                 AND mt.gender = m.gender
                WHERE {' AND '.join(where)}
                GROUP BY 1,2,3
                ORDER BY war DESC NULLS LAST, matches DESC
                LIMIT 12
                """,
                params,
            ).fetchdf()
            recs2 = con.execute(
                f"""
                SELECT COUNT(*) matches,
                       SUM(CASE WHEN m.winner ILIKE ? THEN 1 ELSE 0 END) wins
                FROM matches m
                WHERE (m.team_home ILIKE ? OR m.team_away ILIKE ?)
                  AND m.competition = ? AND m.gender = ?
                  {('AND m.season = ?' if season else '')}
                """,
                [f"%{team}%", f"%{team}%", f"%{team}%", comp, gender] + ([season] if season else []),
            ).fetchone()
            n, w = int(recs2[0] or 0), int(recs2[1] or 0)
            rows = recs.to_dict("records") if not recs.empty else []
            for i, r in enumerate(rows, start=1):
                r["rank"] = i
            return {
                "team": team,
                "matches": n,
                "wins": w,
                "win_pct": round(100 * w / n, 1) if n else None,
                "players": _jsonable(rows),
            }

        return {
            "ok": True,
            "comp": comp,
            "season": season,
            "seasons": seasons,
            "a": pack(team_a),
            "b": pack(team_b),
        }
    finally:
        con.close()


def profile_twin(player: str, *, pool: str | None = None, gender: str | None = None) -> dict[str, Any]:
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built"}
    con = connect()
    try:
        person = resolve_person(con, player)
        if person and person.get("pick"):
            return {"ok": True, "kind": "pick", "people": person["pick"]}
        if not person:
            return {"ok": False, "error": f"No player match for {player}."}
        pid = person["person_id"]
        gender = gender or person.get("gender")
        pool = pool or default_pool(gender)
        comps = parse_comps(pool) or ["t20i", "ipl"]
        ph = ",".join(["?"] * len(comps))
        params: list[Any] = list(comps)
        gender_sql = ""
        if gender:
            gender_sql = " AND mt.gender = ?"
            params.append(gender)
        recs = con.execute(
            f"""
            SELECT mt.person_id, p.display_name, p.slug, mt.competition, mt.season, mt.gender,
                   mt.war, mt.rae_bat, mt.rae_bowl, mt.wpa, mt.pressure_impact AS pressure,
                   mt.balls_bat, mt.balls_bowl, mt.role,
                   CASE WHEN mt.balls_bowl > mt.balls_bat THEN 'bowl' ELSE 'bat' END AS primary_role
            FROM metrics_t20 mt
            JOIN people p ON p.person_id = mt.person_id
            WHERE mt.competition IN ({ph})
              AND mt.balls_bat + mt.balls_bowl >= 60
              {gender_sql}
            """,
            params,
        ).fetchdf()
        if recs.empty:
            return {"ok": True, "person": person, "twins": [], "anchor": None}

        mine = recs[recs["person_id"] == pid]
        if mine.empty:
            return {"ok": True, "person": person, "twins": [], "anchor": None, "message": "Not enough T20 balls in this pool."}
        # Anchor = latest high-volume season
        mine = mine.copy()
        mine["vol"] = mine["balls_bat"] + mine["balls_bowl"]
        anchor = mine.sort_values(["season", "vol"], ascending=[False, False]).iloc[0]
        role = anchor["primary_role"]
        career = recs.groupby("person_id")[["balls_bat", "balls_bowl"]].sum()
        career["vol"] = career["balls_bat"] + career["balls_bowl"]
        seasons_n = recs.groupby("person_id").size()
        my_vol = float(career.loc[pid, "vol"]) if pid in career.index else float(anchor["vol"])
        min_vol = max(1000.0, my_vol * 0.35)
        same_comp = set(recs.loc[recs["competition"] == anchor["competition"], "person_id"])
        eligible = career[(career["vol"] >= min_vol) & (seasons_n >= 2)].index.intersection(same_comp)
        pool_df = recs[(recs["primary_role"] == role) & (recs["person_id"].isin(eligible))].copy()
        feats = ["war", "rae_bat", "rae_bowl", "wpa", "pressure"]
        for f in feats:
            mu = pool_df[f].mean()
            sd = pool_df[f].std() or 1.0
            pool_df[f"{f}_z"] = (pool_df[f].fillna(mu) - mu) / sd
        az = pool_df[pool_df["person_id"] == pid]
        if az.empty:
            return {"ok": True, "person": person, "twins": [], "anchor": _jsonable([anchor.to_dict()])[0]}
        # Use mean z of this player's seasons as the profile
        zcols = [f"{f}_z" for f in feats]
        target = az[zcols].mean().to_numpy()
        others = pool_df[pool_df["person_id"] != pid]
        names = others.groupby("person_id")[["display_name", "slug"]].first()
        by_p = others.groupby("person_id")[zcols + ["war", "rae_bat", "rae_bowl"]].mean()
        dist = ((by_p[zcols] - target) ** 2).sum(axis=1).pow(0.5)
        top = dist.nsmallest(8)
        twins = []
        for pid2, d in top.items():
            row = names.loc[pid2]
            stats = by_p.loc[pid2]
            twins.append(
                {
                    "person_id": pid2,
                    "display_name": row["display_name"],
                    "slug": row["slug"],
                    "distance": round(float(d), 3),
                    "match": round(max(0, 100 * (1 - float(d) / 4)), 1),
                    "war": round(float(stats.get("war") or 0), 2),
                    "rae_bat": round(float(stats.get("rae_bat") or 0), 1),
                    "rae_bowl": round(float(stats.get("rae_bowl") or 0), 1),
                }
            )
        # Feature bars vs league mean for anchor vs best twin
        bars = []
        best = twins[0] if twins else None
        twin_rows = others[others["person_id"] == (best["person_id"] if best else "")] if best else others.iloc[0:0]
        for f, label in (
            ("war", "WAR"),
            ("rae_bat", "RAE bat"),
            ("rae_bowl", "RAE bowl"),
            ("wpa", "WPA"),
            ("pressure", "Pressure"),
        ):
            mu = float(pool_df[f].mean() or 0)
            av = float(anchor[f] or 0)
            tv = float(twin_rows[f].mean()) if best and not twin_rows.empty else None
            bars.append(
                {
                    "key": f,
                    "label": label,
                    "league": round(mu, 2),
                    "a": round(av, 2),
                    "a_rel": round(av - mu, 2),
                    "b": round(tv, 2) if tv is not None else None,
                    "b_rel": round(tv - mu, 2) if tv is not None else None,
                }
            )
        return {
            "ok": True,
            "person": person,
            "anchor": {
                "competition": anchor["competition"],
                "season": str(anchor["season"]),
                "primary_role": role,
                "war": round(float(anchor["war"] or 0), 2),
            },
            "pool": pool,
            "pool_label": POOL_LABELS.get(pool, pool),
            "twins": twins,
            "bars": bars,
        }
    finally:
        con.close()


def stat_shift(player: str, *, team: str | None = None, comp: str | None = None) -> dict[str, Any]:
    """How teammates' bowling/batting lines change with vs without this player."""
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built"}
    con = connect()
    try:
        person = resolve_person(con, player)
        if person and person.get("pick"):
            return {"ok": True, "kind": "pick", "people": person["pick"]}
        if not person:
            return {"ok": False, "error": f"No player match for {player}."}
        pid = person["person_id"]
        if not team:
            row = con.execute(
                """
                SELECT x.team, COUNT(*) c FROM xi x
                JOIN matches m ON m.match_id = x.match_id
                WHERE x.person_id = ?
                GROUP BY 1 ORDER BY c DESC LIMIT 1
                """,
                [pid],
            ).fetchone()
            team = row[0] if row else None
        if not team:
            return {"ok": False, "error": "No team found for this player."}
        first = con.execute(
            """
            SELECT MIN(m.start_date) FROM matches m
            JOIN xi x ON x.match_id = m.match_id
            WHERE x.person_id = ? AND x.team ILIKE ?
            """,
            [pid, f"%{team}%"],
        ).fetchone()[0]
        extra = " AND m.competition = ?" if comp else ""
        with_params: list[Any] = [pid, f"%{team}%", first] + ([comp] if comp else [])
        team_params: list[Any] = [f"%{team}%", f"%{team}%", first] + ([comp] if comp else [])
        recs = con.execute(
            f"""
            WITH with_p AS (
              SELECT m.match_id FROM matches m
              JOIN xi x ON x.match_id = m.match_id
              WHERE x.person_id = ? AND x.team ILIKE ? AND m.start_date >= ?{extra}
            ),
            team_m AS (
              SELECT m.match_id FROM matches m
              WHERE (m.team_home ILIKE ? OR m.team_away ILIKE ?) AND m.start_date >= ?{extra}
            )
            SELECT p.person_id, p.display_name, p.slug,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.wickets ELSE 0 END) AS wk_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.runs ELSE 0 END) AS runs_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.legal_balls ELSE 0 END) AS balls_with,
                   SUM(CASE WHEN w.match_id IS NULL THEN bl.wickets ELSE 0 END) AS wk_wo,
                   SUM(CASE WHEN w.match_id IS NULL THEN bl.runs ELSE 0 END) AS runs_wo,
                   SUM(CASE WHEN w.match_id IS NULL THEN bl.legal_balls ELSE 0 END) AS balls_wo,
                   COUNT(DISTINCT CASE WHEN w.match_id IS NOT NULL THEN bl.match_id END) AS m_with,
                   COUNT(DISTINCT CASE WHEN w.match_id IS NULL THEN bl.match_id END) AS m_wo
            FROM bowling_lines bl
            JOIN team_m tm ON tm.match_id = bl.match_id
            JOIN xi x ON x.match_id = bl.match_id AND x.person_id = bl.person_id AND x.team ILIKE ?
            JOIN people p ON p.person_id = bl.person_id
            LEFT JOIN with_p w ON w.match_id = bl.match_id
            WHERE bl.person_id <> ? AND bl.innings_kind = 'regular'
            GROUP BY 1,2,3
            HAVING SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.legal_balls ELSE 0 END) >= 30
               AND SUM(CASE WHEN w.match_id IS NULL THEN bl.legal_balls ELSE 0 END) >= 30
            ORDER BY balls_with DESC
            LIMIT 25
            """,
            with_params + team_params + [f"%{team}%", pid],
        ).fetchdf()
        bat = con.execute(
            f"""
            WITH with_p AS (
              SELECT m.match_id FROM matches m
              JOIN xi x ON x.match_id = m.match_id
              WHERE x.person_id = ? AND x.team ILIKE ? AND m.start_date >= ?{extra}
            ),
            team_m AS (
              SELECT m.match_id FROM matches m
              WHERE (m.team_home ILIKE ? OR m.team_away ILIKE ?) AND m.start_date >= ?{extra}
            )
            SELECT p.person_id, p.display_name, p.slug,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN b.runs ELSE 0 END) AS runs_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN b.balls ELSE 0 END) AS balls_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL AND NOT b.not_out THEN 1 ELSE 0 END) AS outs_with,
                   SUM(CASE WHEN w.match_id IS NULL THEN b.runs ELSE 0 END) AS runs_wo,
                   SUM(CASE WHEN w.match_id IS NULL THEN b.balls ELSE 0 END) AS balls_wo,
                   SUM(CASE WHEN w.match_id IS NULL AND NOT b.not_out THEN 1 ELSE 0 END) AS outs_wo
            FROM batting_lines b
            JOIN team_m tm ON tm.match_id = b.match_id
            JOIN xi x ON x.match_id = b.match_id AND x.person_id = b.person_id AND x.team ILIKE ?
            JOIN people p ON p.person_id = b.person_id
            LEFT JOIN with_p w ON w.match_id = b.match_id
            WHERE b.person_id <> ? AND b.innings_kind = 'regular'
            GROUP BY 1,2,3
            HAVING SUM(CASE WHEN w.match_id IS NOT NULL THEN b.balls ELSE 0 END) >= 40
               AND SUM(CASE WHEN w.match_id IS NULL THEN b.balls ELSE 0 END) >= 40
            ORDER BY balls_with DESC
            LIMIT 25
            """,
            with_params + team_params + [f"%{team}%", pid],
        ).fetchdf()

        def econ(runs, balls):
            return round(runs * 6 / balls, 2) if balls else None

        def sr(runs, balls):
            return round(runs * 100 / balls, 1) if balls else None

        bowl_rows = []
        if recs is not None and not recs.empty:
            for r in recs.to_dict("records"):
                e_w, e_o = econ(r["runs_with"], r["balls_with"]), econ(r["runs_wo"], r["balls_wo"])
                bowl_rows.append(
                    {
                        "player": r["display_name"],
                        "slug": r["slug"],
                        "m_with": int(r["m_with"] or 0),
                        "m_wo": int(r["m_wo"] or 0),
                        "econ_with": e_w,
                        "econ_wo": e_o,
                        "econ_delta": round(e_w - e_o, 2) if e_w is not None and e_o is not None else None,
                        "wk_with": int(r["wk_with"] or 0),
                        "wk_wo": int(r["wk_wo"] or 0),
                    }
                )
        bat_rows = []
        if bat is not None and not bat.empty:
            for r in bat.to_dict("records"):
                s_w, s_o = sr(r["runs_with"], r["balls_with"]), sr(r["runs_wo"], r["balls_wo"])
                bat_rows.append(
                    {
                        "player": r["display_name"],
                        "slug": r["slug"],
                        "sr_with": s_w,
                        "sr_wo": s_o,
                        "sr_delta": round(s_w - s_o, 1) if s_w is not None and s_o is not None else None,
                        "runs_with": int(r["runs_with"] or 0),
                        "runs_wo": int(r["runs_wo"] or 0),
                    }
                )
        return {
            "ok": True,
            "person": person,
            "team": team,
            "available_from": first,
            "comp": comp,
            "bowling": _jsonable(bowl_rows),
            "batting": _jsonable(bat_rows),
            "caption": f"Teammate lines for {team} from {str(first)[:10] if first else '—'} — with vs without {person['display_name']} in the XI.",
        }
    finally:
        con.close()
