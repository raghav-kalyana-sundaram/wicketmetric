from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import markdown
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cricwarehouse import MODEL_VERSION
from cricwarehouse.competitions import LABELS, GENDER_LABEL
from cricwarehouse.paths import ROOT, UI, USER_DATA, WAREHOUSE, ensure_dirs
from cricwarehouse.app.db import DOCUMENTED_VIEWS, connect, disk_size_bytes, warehouse_ready
from cricwarehouse.app.pull import discover_local_dumps, load_sources
from cricwarehouse.app.query import execute, parse_query, suggest
from cricwarehouse.app import catalog
from cricwarehouse.app.portraits import resolve_portrait

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|copy|attach|detach|create|pragma|export|install|load|call)\b",
    re.I,
)


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso[:10])
        return d.strftime("%-d %b %Y")
    except Exception:
        return iso


def create_app() -> FastAPI:
    ensure_dirs()
    app = FastAPI(title="Wicket Metric", docs_url=None, redoc_url=None)

    if UI.exists():
        app.mount("/static", StaticFiles(directory=str(UI)), name="static")

    @app.get("/")
    def index():
        return FileResponse(UI / "index.html")

    @app.get("/favicon.ico")
    def favicon():
        path = UI / "favicon.svg"
        if path.exists():
            return FileResponse(path, media_type="image/svg+xml")
        raise HTTPException(404)

    @app.get("/api/status")
    def status():
        sources = load_sources()
        build = {}
        bp = WAREHOUSE / "build.json"
        if bp.exists():
            build = json.loads(bp.read_text())
        last_pull = sources.get("last_pull")
        return {
            "ready": warehouse_ready(),
            "last_pull": last_pull,
            "last_pull_display": _fmt_date((last_pull or "")[:10]) if last_pull else "—",
            "built_at": build.get("built_at"),
            "warehouse_bytes": disk_size_bytes(),
            "model_version": MODEL_VERSION,
            "dumps": [str(p) for p in discover_local_dumps()],
        }

    @app.get("/api/snapshot")
    def snapshot():
        if not warehouse_ready():
            return {"rows": []}
        con = connect()
        try:
            rows = con.execute(
                """
                SELECT competition, gender,
                       COUNT(*) AS matches,
                       MIN(start_date) AS first_date,
                       MAX(start_date) AS last_date
                FROM matches
                GROUP BY 1,2
                ORDER BY 1,2
                """
            ).fetchall()
            balls = con.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
            out = []
            for r in rows:
                out.append(
                    {
                        "competition": LABELS.get(r[0], r[0]),
                        "competition_key": r[0],
                        "gender": GENDER_LABEL.get(r[1], r[1]),
                        "matches": r[2],
                        "first_date": _fmt_date(r[3]),
                        "last_date": _fmt_date(r[4]),
                        "range": f"{r[3][:4]}–{r[4][:4]}" if r[3] and r[4] else "—",
                    }
                )
            return {"rows": out, "deliveries": balls}
        finally:
            con.close()

    @app.get("/api/pulse")
    def api_pulse(limit: int = 8):
        return catalog.pulse(limit=limit)

    @app.get("/api/query")
    def api_query(q: str = ""):
        try:
            return execute(q)
        except Exception as e:
            return {"ok": False, "error": str(e), "kind": "empty", "rows": [], "columns": []}

    @app.get("/api/parse")
    def api_parse(q: str = ""):
        p = parse_query(q)
        return {"tokens": p.tokens, "ignored": p.ignored, "heuristic": p.heuristic, "mode": p.mode}

    @app.get("/api/suggest")
    def api_suggest(q: str = ""):
        return catalog.search(q)

    @app.get("/api/portrait/{key}")
    def api_portrait(key: str, warm: bool = False):
        if not warehouse_ready():
            raise HTTPException(404, "No warehouse")
        con = connect()
        try:
            rec = con.execute(
                "SELECT person_id, slug, display_name, key_cricinfo FROM people WHERE person_id = ? OR slug = ? LIMIT 1",
                [key, key],
            ).fetchdf()
        finally:
            con.close()
        if rec.empty:
            raise HTTPException(404, "Player not found")
        person = _clean(rec.iloc[0].to_dict())
        path = resolve_portrait(person, warm=warm)
        if not path:
            raise HTTPException(404, "No portrait")
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=604800"},
        )

    @app.get("/api/stats")
    def api_stats(
        comp: str | None = None,
        gender: str | None = None,
        min_inns: int = 5,
        role: str = "all",
        sort: str = "war",
        wtc: bool = False,
    ):
        return catalog.master_stats(
            comp=comp or None, gender=gender or None, min_inns=min_inns, role=role, sort=sort, wtc=wtc
        )

    @app.get("/api/best")
    def api_best(
        discipline: str | None = None,
        comp: str | None = None,
        gender: str | None = None,
        wtc: bool = True,
        mode: str = "composite",
        limit: int = 50,
    ):
        from cricwarehouse.app import studio
        if mode == "composite" or discipline in {None, "", "match"}:
            return studio.list_match_composites(comp=comp, gender=gender, wtc=wtc, limit=limit)
        return catalog.list_performances(
            discipline=discipline, comp=comp, gender=gender, wtc=wtc, limit=limit
        )

    @app.get("/api/compare")
    def api_compare(a: str, b: str, pool: str | None = None, comp: str | None = None):
        from cricwarehouse.app import studio
        return studio.player_compare(a, b, pool=pool or comp)

    @app.get("/api/team-compare")
    def api_team_compare(
        a: str,
        b: str,
        comp: str = "t20i",
        season: str | None = None,
        season_a: str | None = None,
        season_b: str | None = None,
        gender: str = "male",
    ):
        from cricwarehouse.app import studio
        return studio.team_compare(
            a, b, comp=comp, season=season, season_a=season_a, season_b=season_b, gender=gender
        )

    @app.get("/api/twin")
    def api_twin(player: str, pool: str | None = None):
        from cricwarehouse.app import studio
        return studio.profile_twin(player, pool=pool)

    @app.get("/api/shift")
    def api_shift(player: str, team: str | None = None, comp: str | None = None):
        from cricwarehouse.app import studio
        return studio.stat_shift(player, team=team, comp=comp)

    @app.get("/api/rankings")
    def api_rankings(
        metric: str = "runs",
        comp: str | None = None,
        gender: str | None = None,
        min_inns: int = 5,
    ):
        return catalog.rankings(metric=metric, comp=comp or None, gender=gender or None, min_inns=min_inns)

    @app.get("/api/wowy")
    def api_wowy(team: str, player: str, comp: str | None = None, gender: str | None = None):
        return catalog.wowy(team=team, player=player, comp=comp or None, gender=gender or None)

    @app.get("/api/teams")
    def api_teams(q: str = ""):
        return {"teams": catalog.teams(q)}

    @app.get("/api/match/{match_id}")
    def api_match(match_id: str):
        if not warehouse_ready():
            raise HTTPException(400, "Warehouse not built yet.")
        con = connect()
        try:
            m = con.execute("SELECT * FROM matches WHERE match_id = ?", [match_id]).fetchdf()
            if m.empty:
                raise HTTPException(404, "Match not found")
            match = m.iloc[0].to_dict()
            for k, v in list(match.items()):
                if hasattr(v, "item"):
                    match[k] = v.item() if v == v else None
            inns = con.execute(
                "SELECT * FROM innings WHERE match_id = ? ORDER BY innings", [match_id]
            ).fetchdf().to_dict("records")
            bat = con.execute(
                """
                SELECT b.*, p.display_name, p.slug,
                       bp.display_name AS bowler_name,
                       fp.display_name AS fielder_name
                FROM batting_lines b
                JOIN people p ON p.person_id = b.person_id
                LEFT JOIN people bp ON bp.person_id = b.bowler_id
                LEFT JOIN people fp ON fp.person_id = b.fielder_id
                WHERE b.match_id = ? ORDER BY b.innings, b.position
                """,
                [match_id],
            ).fetchdf().to_dict("records")
            bowl = con.execute(
                """
                WITH dx AS (
                  SELECT innings, innings_kind, bowler,
                         SUM(CASE WHEN extra_type = 'wides' THEN runs_extras ELSE 0 END) AS wides,
                         SUM(CASE WHEN extra_type = 'noballs' THEN runs_extras ELSE 0 END) AS noballs
                  FROM deliveries
                  WHERE match_id = ?
                  GROUP BY 1,2,3
                )
                SELECT b.*, p.display_name, p.slug,
                       COALESCE(dx.wides, 0) AS wides,
                       COALESCE(dx.noballs, 0) AS noballs
                FROM bowling_lines b
                JOIN people p ON p.person_id = b.person_id
                LEFT JOIN dx ON dx.innings = b.innings
                            AND dx.innings_kind = b.innings_kind
                            AND dx.bowler = b.person_id
                WHERE b.match_id = ? ORDER BY b.innings, b.legal_balls DESC
                """,
                [match_id, match_id],
            ).fetchdf().to_dict("records")
            parts = con.execute(
                """
                SELECT pr.*, p1.display_name AS name_1, p2.display_name AS name_2
                FROM partnerships pr
                JOIN people p1 ON p1.person_id = pr.person_id_1
                JOIN people p2 ON p2.person_id = pr.person_id_2
                WHERE pr.match_id = ? ORDER BY pr.innings, pr.wicket_number
                """,
                [match_id],
            ).fetchdf().to_dict("records")
            fow = []
            running = 0
            # fall of wickets from batting dismissals order is approximate; use partnerships end
            dels = con.execute(
                """
                SELECT over, ball_in_over, bowler, striker, runs_total, extra_type,
                       wicket_kind, player_out, innings, innings_kind,
                       runs_extras, is_legal, legal_ball_index,
                       p1.display_name AS bowler_name, p2.display_name AS striker_name,
                       p3.display_name AS player_out_name
                FROM deliveries d
                LEFT JOIN people p1 ON p1.person_id = d.bowler
                LEFT JOIN people p2 ON p2.person_id = d.striker
                LEFT JOIN people p3 ON p3.person_id = d.player_out
                WHERE d.match_id = ?
                ORDER BY innings, over, ball_in_over
                """,
                [match_id],
            ).fetchdf().to_dict("records")
            xi = con.execute(
                """
                SELECT x.team, x.person_id, x.is_captain, x.is_keeper, p.display_name, p.slug,
                       MIN(b.position) AS bat_pos
                FROM xi x
                JOIN people p ON p.person_id = x.person_id
                LEFT JOIN batting_lines b
                  ON b.match_id = x.match_id AND b.person_id = x.person_id
                 AND b.innings_kind = 'regular'
                WHERE x.match_id = ?
                GROUP BY x.team, x.person_id, x.is_captain, x.is_keeper, p.display_name, p.slug
                ORDER BY x.team, bat_pos NULLS LAST, p.display_name
                """,
                [match_id],
            ).fetchdf().to_dict("records")
            return {
                "match": _clean(match),
                "innings": _clean_list(inns),
                "batting": _clean_list(bat),
                "bowling": _clean_list(bowl),
                "partnerships": _clean_list(parts),
                "deliveries": _clean_list(dels),
                "xi": _clean_list(xi),
            }
        finally:
            con.close()

    @app.get("/api/player/{key}")
    def api_player(key: str):
        if not warehouse_ready():
            raise HTTPException(400, "Warehouse not built yet.")
        con = connect()
        try:
            person = con.execute(
                """
                SELECT * FROM people
                WHERE person_id = ? OR slug = ? OR lower(unique_name) = lower(?)
                LIMIT 1
                """,
                [key, key, key],
            ).fetchdf()
            if person.empty:
                raise HTTPException(404, "Player not found")
            p = _clean(person.iloc[0].to_dict())
            pid = p["person_id"]
            inns = con.execute(
                """
                SELECT b.*, m.start_date, m.competition, m.gender, m.winner, m.result, m.result_method,
                       CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
                       m.event_name
                FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
                WHERE b.person_id = ? AND b.innings_kind = 'regular'
                ORDER BY m.start_date DESC, b.match_id, b.innings
                """,
                [pid],
            ).fetchdf().to_dict("records")
            summary = con.execute(
                """
                SELECT m.competition,
                       COUNT(DISTINCT b.match_id) AS matches,
                       COUNT(*) AS inns,
                       SUM(b.runs) AS runs,
                       MAX(b.runs) AS hs,
                       SUM(b.balls) AS balls,
                       SUM(CASE WHEN b.not_out THEN 0 ELSE 1 END) AS outs,
                       SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds,
                       SUM(CASE WHEN b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) AS fifties,
                       SUM(b.fours) AS fours,
                       SUM(b.sixes) AS sixes
                FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
                WHERE b.person_id = ? AND b.innings_kind = 'regular'
                GROUP BY 1
                """,
                [pid],
            ).fetchdf().to_dict("records")
            bowl = con.execute(
                """
                SELECT m.competition,
                       COUNT(DISTINCT bl.match_id) AS matches,
                       SUM(bl.wickets) AS wickets, SUM(bl.runs) AS runs,
                       SUM(bl.legal_balls) AS legal_balls, SUM(bl.maidens) AS maidens,
                       SUM(bl.dots) AS dots, SUM(bl.extras) AS extras
                FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
                WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
                GROUP BY 1
                """,
                [pid],
            ).fetchdf().to_dict("records")
            bowl_inns = con.execute(
                """
                SELECT bl.*, m.start_date, m.competition, m.winner, m.result, m.result_method,
                       CASE WHEN bl.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition
                FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
                WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
                ORDER BY m.start_date DESC, bl.match_id, bl.innings
                """,
                [pid],
            ).fetchdf().to_dict("records")
            field = con.execute(
                """
                SELECT SUM(catches), SUM(run_outs), SUM(stumpings)
                FROM fielding_lines WHERE person_id = ?
                """,
                [pid],
            ).fetchone()
            metrics = []
            try:
                metrics = con.execute(
                    "SELECT * FROM metrics_t20 WHERE person_id = ? ORDER BY season DESC",
                    [pid],
                ).fetchdf().to_dict("records")
            except Exception:
                metrics = []
            pairs = con.execute(
                """
                SELECT CASE WHEN pr.person_id_1 = ? THEN p2.display_name ELSE p1.display_name END AS partner,
                       CASE WHEN pr.person_id_1 = ? THEN pr.person_id_2 ELSE pr.person_id_1 END AS partner_id,
                       CASE WHEN pr.person_id_1 = ? THEN p2.slug ELSE p1.slug END AS partner_slug,
                       COUNT(*) AS inns, SUM(pr.runs) AS runs, ROUND(AVG(pr.runs),1) AS avg,
                       SUM(CASE WHEN pr.runs >= 100 THEN 1 ELSE 0 END) AS hundreds
                FROM partnerships pr
                JOIN people p1 ON p1.person_id = pr.person_id_1
                JOIN people p2 ON p2.person_id = pr.person_id_2
                WHERE (pr.person_id_1 = ? OR pr.person_id_2 = ?) AND pr.innings_kind = 'regular'
                GROUP BY 1,2,3
                ORDER BY SUM(pr.runs) DESC
                LIMIT 15
                """,
                [pid, pid, pid, pid, pid],
            ).fetchdf().to_dict("records")
            so = []
            try:
                so = con.execute(
                    "SELECT * FROM super_over_stats WHERE person_id = ?", [pid]
                ).fetchdf().to_dict("records")
            except Exception:
                so = []
            span = con.execute(
                "SELECT MIN(start_date), MAX(start_date), COUNT(*) FROM matches m JOIN xi x ON x.match_id = m.match_id WHERE x.person_id = ?",
                [pid],
            ).fetchone()
            teams = con.execute(
                """
                SELECT CASE
                         WHEN x.team IN ('Royal Challengers Bangalore', 'Royal Challengers Bengaluru')
                           THEN 'Royal Challengers Bengaluru'
                         ELSE x.team
                       END AS team,
                       COUNT(DISTINCT x.match_id) AS matches
                FROM xi x
                WHERE x.person_id = ?
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT 12
                """,
                [pid],
            ).fetchdf().to_dict("records")
            bat_balls = int(sum(int(s.get("balls") or 0) for s in summary))
            bowl_balls = int(sum(int(s.get("legal_balls") or 0) for s in bowl))
            primary_role = "bowl" if bowl_balls > bat_balls else "bat"
            value = catalog.career_value(pid)
            from cricwarehouse.app import studio
            perfs = studio.list_match_composites(person_id=pid, focus=primary_role, limit=25)
            if not perfs.get("rows"):
                perfs = catalog.list_performances(person_id=pid, discipline=primary_role, limit=25)
            h2h = catalog.matchups(pid)
            almanac = catalog.player_almanac(con, pid)
            return {
                "person": p,
                "primary_role": primary_role,
                "span": {
                    "first": span[0],
                    "last": span[1],
                    "matches": int(span[2] or 0),
                    "line": (
                        f"{span[0][:4]}–{span[1][:4]} · {int(span[2] or 0)} matches"
                        if span[0] and span[1]
                        else f"{int(span[2] or 0)} matches"
                    ),
                },
                "summary": _clean_list(summary),
                "bowling_summary": _clean_list(bowl),
                "innings": _clean_list(inns),
                "bowling_innings": _clean_list(bowl_inns),
                "fielding": {
                    "catches": int(field[0] or 0),
                    "run_outs": int(field[1] or 0),
                    "stumpings": int(field[2] or 0),
                },
                "metrics": _clean_list(metrics),
                "value": value,
                "performances": perfs,
                "matchups": h2h,
                "pairs": _clean_list(pairs),
                "super_over": _clean_list(so),
                "teams": _clean_list(teams),
                "almanac": _clean(almanac),
            }
        finally:
            con.close()

    @app.get("/api/player/{key}/value")
    def api_player_value(key: str, pool: str | None = None):
        if not warehouse_ready():
            raise HTTPException(400, "Warehouse not built yet.")
        con = connect()
        try:
            person = con.execute(
                "SELECT person_id FROM people WHERE person_id = ? OR slug = ? LIMIT 1",
                [key, key],
            ).fetchone()
            if not person:
                raise HTTPException(404, "Player not found")
            return catalog.career_value(person[0], pool=pool)
        finally:
            con.close()

    @app.get("/api/metrics")
    def api_metrics(
        comp: str = "ipl",
        season: str | None = None,
        gender: str = "male",
        role: str | None = None,
        qualifiers: bool = True,
    ):
        if not warehouse_ready():
            return {"rows": [], "seasons": []}
        con = connect()
        try:
            where = ["mt.competition = ?", "mt.gender = ?"]
            params: list[Any] = [comp, gender]
            seasons = [
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT season FROM metrics_t20 WHERE competition = ? AND gender = ? ORDER BY 1 DESC",
                    [comp, gender],
                ).fetchall()
            ]
            if season:
                where.append("mt.season = ?")
                params.append(season)
            elif seasons:
                where.append("mt.season = ?")
                params.append(seasons[0])
                season = seasons[0]
            if role:
                where.append("mt.role = ?")
                params.append(role)
            recs = con.execute(
                f"""
                SELECT mt.*, p.display_name, p.slug
                FROM metrics_t20 mt JOIN people p ON p.person_id = mt.person_id
                WHERE {' AND '.join(where)}
                ORDER BY mt.war DESC NULLS LAST
                """,
                params,
            ).fetchdf().to_dict("records")
            rows = _clean_list(recs)
            if qualifiers:
                from cricwarehouse.app.metrics import is_qualifier as iq

                career = {}
                allr = con.execute(
                    "SELECT person_id, SUM(balls_bat+balls_bowl) FROM metrics_t20 GROUP BY 1"
                ).fetchall()
                career = {r[0]: int(r[1] or 0) for r in allr}
                rows = [r for r in rows if iq(r, career_balls=career.get(r["person_id"], 0))]
            for i, r in enumerate(rows, start=1):
                r["rank"] = i
                r["balls"] = int(r.get("balls_bat") or 0) + int(r.get("balls_bowl") or 0)
            return {
                "rows": rows,
                "seasons": seasons,
                "season": season,
                "scope": _metrics_scope(comp, season, gender, qualifiers, len(rows)),
            }
        finally:
            con.close()

    @app.get("/api/standings")
    def api_standings(comp: str = "ipl", season: str | None = None, gender: str | None = None):
        if not warehouse_ready():
            return {"rows": [], "playoffs": [], "seasons": []}
        con = connect()
        try:
            seasons = [
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT season FROM standings WHERE competition = ? ORDER BY 1 DESC",
                    [comp],
                ).fetchall()
            ]
            where = ["competition = ?"]
            params: list[Any] = [comp]
            if season:
                where.append("season = ?")
                params.append(season)
            elif seasons:
                where.append("season = ?")
                params.append(seasons[0])
                season = seasons[0]
            if gender:
                where.append("gender = ?")
                params.append(gender)
            rows = con.execute(
                f"SELECT * FROM standings WHERE {' AND '.join(where)} ORDER BY position",
                params,
            ).fetchdf().to_dict("records")
            play = con.execute(
                "SELECT * FROM playoffs WHERE competition = ? AND season = ? ORDER BY start_date",
                [comp, season],
            ).fetchdf().to_dict("records")
            return {"rows": _clean_list(rows), "playoffs": _clean_list(play), "seasons": seasons, "season": season}
        finally:
            con.close()

    @app.post("/api/sql")
    async def api_sql(request: Request):
        if not warehouse_ready():
            raise HTTPException(400, "Warehouse not built yet.")
        data = await request.json()
        sql = str(data.get("sql") or "").strip().rstrip(";")
        if FORBIDDEN_SQL.search(sql):
            return {"ok": False, "error": "Read-only · documented views only. Write statements are rejected."}
        con = connect()
        try:
            con.execute("SET statement_timeout = '10s'")
        except Exception:
            pass
        try:
            rel = con.execute(sql)
            cols = [c[0] for c in rel.description] if rel.description else []
            rows = rel.fetchmany(500)
            return {
                "ok": True,
                "columns": [{"key": c, "label": c, "align": "left"} for c in cols],
                "rows": [dict(zip(cols, r)) for r in rows],
                "truncated": len(rows) >= 500,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            con.close()

    @app.get("/api/views")
    def api_views():
        return {"views": DOCUMENTED_VIEWS}

    @app.get("/api/docs/{name}")
    def api_docs(name: str):
        files = {"model": ROOT / "MODEL.md", "attribution": ROOT / "ATTRIBUTION.md"}
        path = files.get(name)
        if not path or not path.exists():
            raise HTTPException(404, "Doc not found")
        html = markdown.markdown(path.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
        return {"title": path.stem, "html": html, "markdown": path.read_text(encoding="utf-8")}

    @app.get("/api/settings")
    def get_settings():
        defaults = {"theme": "charcoal", "weights": {"rae": 0.45, "wpa": 0.35, "consistency": 0.20}}
        p = USER_DATA / "settings.json"
        if not p.exists():
            return dict(defaults)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return dict(defaults)
        if not isinstance(data, dict):
            return dict(defaults)
        return {**defaults, **data}

    @app.put("/api/settings")
    async def put_settings(request: Request):
        data = await request.json()
        USER_DATA.mkdir(parents=True, exist_ok=True)
        current = get_settings()
        if data.get("theme"):
            current["theme"] = data["theme"]
        if data.get("weights"):
            current["weights"] = data["weights"]
        (USER_DATA / "settings.json").write_text(json.dumps(current, indent=2))
        return current

    @app.get("/api/presets")
    def get_presets():
        p = USER_DATA / "presets.json"
        if p.exists():
            return json.loads(p.read_text())
        return {"presets": []}

    @app.post("/api/presets")
    async def post_preset(request: Request):
        incoming = await request.json()
        data = get_presets()
        data.setdefault("presets", []).append(
            {"name": incoming.get("name"), "weights": incoming.get("weights")}
        )
        USER_DATA.mkdir(parents=True, exist_ok=True)
        (USER_DATA / "presets.json").write_text(json.dumps(data, indent=2))
        return data

    @app.get("/api/export")
    def api_export(q: str = ""):
        result = execute(q)
        rows = result.get("rows") or []
        cols = [c["key"] for c in result.get("columns") or []]
        import csv
        import io

        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols or (list(rows[0].keys()) if rows else []))
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in w.fieldnames})
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=warehouse.csv"},
        )

    @app.get("/api/job/{kind}")
    def api_job(kind: str):
        if kind not in {"pull", "build", "metrics"}:
            raise HTTPException(404, "Unknown job")
        cmd = [sys.executable, "-m", "cricwarehouse", kind if kind != "metrics" else "rebuild-metrics"]

        def stream():
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout
            for line in proc.stdout:
                yield f"data: {json.dumps(line.rstrip())}\n\n"
            code = proc.wait()
            yield f"data: {json.dumps({'done': True, 'code': code})}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, float):
        if obj != obj:
            return None
        return obj
    if hasattr(obj, "item"):
        try:
            v = obj.item()
            return None if v != v else v
        except Exception:
            return str(obj)
    return obj


def _clean_list(rows: list) -> list:
    return [_clean(r) for r in rows]


def _metrics_scope(comp, season, gender, qualifiers, n) -> str:
    parts = [
        LABELS.get(comp, comp),
        season or "",
        GENDER_LABEL.get(gender, gender),
        "Qualifiers (≥60 balls)" if qualifiers else "All players — no qualifier floor",
        "in this warehouse",
    ]
    return " · ".join(p for p in parts if p)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    print(f"Wicket Metric  →  http://{host}:{port}", flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
