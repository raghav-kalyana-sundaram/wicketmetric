from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from cricwarehouse.competitions import normalize_format, LABELS
from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.app.metrics import is_qualifier, LEAGUE_QUAL_BALLS, INTL_CAREER_BALLS
from cricwarehouse.app.search import (
    interpretation,
    lift_bare,
    search_people,
    search_teams,
    _year_from_two,
)

TOKEN_RE = re.compile(r'([a-z_]+):("([^"]+)"|(\S+))', re.I)
KNOWN_KEYS = {
    "player",
    "runs",
    "format",
    "comp",
    "year",
    "years",
    "from",
    "to",
    "opposition",
    "opp",
    "team",
    "venue",
    "compare",
    "pair",
    "with",
    "without",
    "war",
    "metric",
    "out",
    "dismissed_by",
    "standings",
    "gender",
    "notout",
    "min_balls",
    "min_partnerships",
    "side",
    "event",
    "home",
    "away",
}

TOKEN_HELP = [
    ("player", "Name or id — player:kohli"),
    ("runs", "Exact or range — runs:89  runs:100-150"),
    ("format", "test, odi, t20i, ipl, wpl, bbl, wbbl"),
    ("comp", "Alias of format"),
    ("years", "Calendar range — years:2021-2026"),
    ("from", "Start date — from:2023-04-01"),
    ("to", "End date — to:2024-03-31"),
    ("team", "Side in the match"),
    ("opposition", "Opposing side"),
    ("compare", "Two players — compare:babar,kohli"),
    ("pair", "Partnership pair or *"),
    ("with", "XI contains this player"),
    ("without", "XI does not contain"),
    ("war", "T20 value leaderboard"),
    ("out", "Dismissal kind — out:bowled"),
    ("dismissed_by", "Bowler on the dismissal"),
    ("standings", "Points table / bracket"),
    ("gender", "male or female"),
    ("notout", "true / false"),
]


@dataclass
class ParsedQuery:
    raw: str
    tokens: dict[str, str] = field(default_factory=dict)
    ignored: list[str] = field(default_factory=list)
    bare_player: str | None = None
    heuristic: str | None = None
    mode: str = "innings"


def parse_query(raw: str) -> ParsedQuery:
    q = ParsedQuery(raw=raw.strip())
    if not q.raw:
        return q
    rest = q.raw
    for m in TOKEN_RE.finditer(q.raw):
        key = m.group(1).lower()
        val = (m.group(3) or m.group(4) or "").strip()
        if key not in KNOWN_KEYS:
            q.ignored.append(f"{key}:{val}")
        else:
            q.tokens[key] = val
        rest = rest.replace(m.group(0), " ", 1)
    rest = re.sub(r"\s+", " ", rest).strip()
    # Bare mode keywords (chips use `war format:t20i`, not `war:`)
    bare_mode = None
    rest_words = rest.split()
    if rest_words and rest_words[0].lower() in {"war", "metric", "standings"}:
        bare_mode = {"war": "war", "metric": "war", "standings": "standings"}[rest_words[0].lower()]
        rest = " ".join(rest_words[1:])
    if rest:
        lifted = lift_bare(rest, q.tokens)
        for key, val in lifted.tokens.items():
            q.tokens.setdefault(key, val)
        if lifted.player and "player" not in q.tokens and "compare" not in q.tokens:
            q.bare_player = lifted.player
            q.tokens["player"] = lifted.player
        if lifted.heuristic:
            q.heuristic = lifted.heuristic
        if lifted.mode and q.mode == "innings":
            q.mode = lifted.mode
    # mode
    if bare_mode == "standings" or "standings" in q.tokens or raw.strip().lower().startswith("standings"):
        q.mode = "standings"
    elif q.mode == "matches" or ("home" in q.tokens and "away" in q.tokens):
        q.mode = "matches"
    elif "compare" in q.tokens:
        q.mode = "compare"
    elif "pair" in q.tokens:
        q.mode = "pair"
    elif bare_mode == "war" or "war" in q.tokens or "metric" in q.tokens:
        q.mode = "war"
    elif "with" in q.tokens or "without" in q.tokens:
        q.mode = "split"
    elif (
        q.tokens.get("player")
        and (q.tokens.get("opposition") or q.tokens.get("opp") or q.tokens.get("side"))
        and not any(k in q.tokens for k in ("runs", "out", "dismissed_by", "notout"))
    ):
        q.mode = "matches"
    else:
        q.mode = "innings"
    if "format" in q.tokens:
        nf = normalize_format(q.tokens["format"])
        if nf is None:
            q.ignored.append(f"format:{q.tokens['format']}")
            del q.tokens["format"]
        else:
            q.tokens["format"] = nf
    if "comp" in q.tokens:
        nf = normalize_format(q.tokens["comp"])
        if nf is None:
            q.ignored.append(f"comp:{q.tokens['comp']}")
            del q.tokens["comp"]
        else:
            q.tokens["comp"] = nf
    return q


def _people_match(con, needle: str) -> list[dict]:
    from cricwarehouse.app.search import get_index

    idx = get_index()
    if idx is not None:
        return idx.search(needle)
    raw = (needle or "").strip().lower()
    if not raw or con is None:
        return []
    n = re.sub(r"[-_]+", " ", raw).strip()
    slug = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    last = n.split()[-1]
    first = n.split()[0]
    rows = con.execute(
        """
        SELECT p.person_id, p.display_name, p.unique_name, p.slug, p.gender,
               CASE
                 WHEN lower(p.slug) = ? THEN 0
                 WHEN lower(p.person_id) = ? THEN 0
                 WHEN lower(p.unique_name) = ? THEN 1
                 WHEN lower(p.display_name) = ? THEN 1
                 WHEN lower(p.unique_name) LIKE ? OR lower(p.display_name) LIKE ?
                   OR (p.name_variants IS NOT NULL AND lower(p.name_variants) LIKE ?) THEN 2
                 WHEN lower(p.slug) LIKE ? THEN 3
                 WHEN lower(p.unique_name) LIKE ? OR lower(p.display_name) LIKE ? THEN 4
                 WHEN lower(p.unique_name) LIKE ? OR lower(p.display_name) LIKE ? THEN 5
                 ELSE 6
               END AS hit,
               COALESCE(x.apps, 0) AS apps
        FROM people p
        LEFT JOIN (
          SELECT person_id, COUNT(*) AS apps FROM xi GROUP BY 1
        ) x ON x.person_id = p.person_id
        WHERE lower(p.person_id) IN (?, ?)
           OR lower(p.slug) IN (?, ?)
           OR lower(p.unique_name) IN (?, ?)
           OR lower(p.display_name) IN (?, ?)
           OR lower(p.unique_name) LIKE ?
           OR lower(p.display_name) LIKE ?
           OR lower(p.slug) LIKE ?
           OR lower(p.unique_name) LIKE ?
           OR lower(p.display_name) LIKE ?
           OR (p.name_variants IS NOT NULL AND (
                 lower(p.name_variants) LIKE ? OR lower(p.name_variants) LIKE ?
           ))
        ORDER BY hit, apps DESC, p.unique_name
        LIMIT 20
        """,
        [
            slug, raw,
            n, n,
            f"{n}%", f"{n}%", f"{n}%",
            f"{slug}%",
            f"{first}%", f"{first}%",
            f"% {last}", f"% {last}",
            raw, n,
            slug, re.sub(r"[^a-z0-9]+", "-", raw).strip("-"),
            n, raw,
            n, raw,
            f"{n}%", f"{n}%", f"{slug}%",
            f"% {last}", f"% {last}",
            f"%{n}%", f"%{raw}%",
        ],
    ).fetchall()
    cols = ["person_id", "display_name", "unique_name", "slug", "gender", "hit", "apps"]
    return [dict(zip(cols, r[:7])) for r in rows]


def pick_person(people: list[dict], needle: str | None = None) -> dict | None:
    """Exact slug/id, or a runaway apps lead. Otherwise None so the UI can ask."""
    if not people:
        return None
    if needle:
        raw = needle.strip().lower()
        n = re.sub(r"[-_]+", " ", raw).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
        for p in people:
            if p.get("slug") in {slug, raw} or (p.get("person_id") or "").lower() == raw:
                return p
    top = people[0]
    if top.get("hit") == 0:
        return top
    if len(people) == 1:
        return top
    nxt = people[1]
    if int(top.get("apps") or 0) >= 15 and int(top.get("apps") or 0) >= 3 * max(int(nxt.get("apps") or 0), 1):
        return top
    return None


def resolve_team(con, team: str) -> str | None:
    """Exact side name. Contains-match is how 'India' swallowed India A / Women."""
    needle = (team or "").strip()
    if not needle:
        return None
    row = con.execute(
        """
        SELECT team, COUNT(*) AS n FROM (
          SELECT team_home AS team FROM matches
          UNION ALL
          SELECT team_away AS team FROM matches
        )
        WHERE lower(team) = lower(?)
        GROUP BY 1
        ORDER BY n DESC
        LIMIT 1
        """,
        [needle],
    ).fetchone()
    if row:
        return row[0]
    row = con.execute(
        """
        SELECT team, COUNT(*) AS n FROM (
          SELECT team_home AS team FROM matches
          UNION ALL
          SELECT team_away AS team FROM matches
        )
        WHERE lower(team) LIKE lower(?)
        GROUP BY 1
        ORDER BY (lower(team) = lower(?)) DESC, n DESC
        LIMIT 1
        """,
        [f"{needle}%", needle],
    ).fetchone()
    return row[0] if row else None


def _safe_int(val: Any, default: int | None = None) -> int | None:
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return default


def _date_bounds(tokens: dict[str, str]) -> tuple[str | None, str | None]:
    start = tokens.get("from")
    end = tokens.get("to")
    years = tokens.get("years") or tokens.get("year")
    if years:
        m = re.match(r"(\d{4})(?:\s*[-–]\s*(\d{4}))?", years)
        if m:
            start = start or f"{m.group(1)}-01-01"
            end = end or f"{m.group(2) or m.group(1)}-12-31"
    return start, end


def _comp_filter(tokens: dict[str, str]) -> str | None:
    return tokens.get("comp") or tokens.get("format")


def execute(raw: str) -> dict[str, Any]:
    parsed = parse_query(raw)
    if not warehouse_ready():
        return {
            "ok": False,
            "error": "Application not built yet. Run: python -m cricwarehouse pull && python -m cricwarehouse build — or open the Build page.",
            "parsed": parsed.__dict__,
        }
    dest_key = (parsed.bare_player or "").strip().lower()
    only_name = (
        parsed.mode == "innings"
        and parsed.bare_player
        and not any(
            k in parsed.tokens
            for k in (
                "runs", "out", "dismissed_by", "notout", "opposition", "opp",
                "venue", "year", "years", "from", "to", "side", "event",
                "home", "away", "team", "format", "comp",
            )
        )
    )
    if only_name and dest_key in {"stats", "wowy", "rankings", "metrics", "war", "build", "docs", "best", "compare", "teams", "twin", "shift", "resources"}:
        dest = {
            "rankings": "/rankings",
            "war": "/metrics",
            "docs": "/resources",
            "resources": "/resources",
            "teams": "/teams",
        }.get(dest_key, f"/{dest_key}")
        return {"ok": True, "kind": "goto_page", "hash": dest}
    con = connect()
    try:
        if only_name:
            people = _people_match(con, parsed.bare_player)
            top = people[0] if people else None
            nxt = people[1] if len(people) > 1 else None
            clear_lead = bool(
                top
                and int(top.get("apps") or 0) >= 15
                and int(top.get("apps") or 0) >= 3 * max(int((nxt or {}).get("apps") or 0), 1)
            )
            if top and (len(people) == 1 or clear_lead):
                result = {"ok": True, "kind": "goto_player", "person": top, "people": people}
            elif people:
                result = {
                    "ok": True,
                    "kind": "pick_player",
                    "people": people,
                    "message": f"{len(people)} players match “{parsed.bare_player}”",
                }
            else:
                result = {
                    "ok": True,
                    "kind": "empty",
                    "message": f"No players match {parsed.bare_player}. Try a last name, or open Stats.",
                    "rows": [],
                    "columns": [],
                }
        elif parsed.mode == "matches":
            result = _exec_matches(con, parsed)
        elif parsed.mode == "compare":
            result = _exec_compare(con, parsed)
        elif parsed.mode == "pair":
            result = _exec_pair(con, parsed)
        elif parsed.mode == "war":
            result = _exec_war(con, parsed)
        elif parsed.mode == "standings":
            result = _exec_standings(con, parsed)
        elif parsed.mode == "split":
            result = _exec_split(con, parsed)
        else:
            result = _exec_innings(con, parsed)
            if _retry_two_digit_as_year(parsed, result):
                year = _year_from_two(parsed.tokens["runs"].zfill(2))
                parsed.tokens.pop("runs", None)
                parsed.tokens["year"] = year
                parsed.mode = "matches"
                parsed.heuristic = interpretation(parsed.tokens, parsed.tokens.get("player"))
                result = _exec_matches(con, parsed)
                result["year_fallback"] = year
    finally:
        con.close()
    result["parsed"] = {
        "raw": parsed.raw,
        "tokens": parsed.tokens,
        "ignored": parsed.ignored,
        "heuristic": parsed.heuristic,
        "mode": parsed.mode,
        "interpretation": interpretation(parsed.tokens, parsed.tokens.get("player")),
    }
    return result


def _scope_line(tokens: dict, n: int, extra: str = "") -> str:
    bits = [f"{n:,} rows" if n != 1 else "1 row"]
    comp = _comp_filter(tokens)
    if comp:
        bits.append(LABELS.get(comp, comp))
    start, end = _date_bounds(tokens)
    if start and end:
        bits.append(f"{start[:4]}–{end[:4]}" if start[:4] != end[:4] else start[:4])
    elif start or end:
        bits.append(start or end)
    if extra:
        bits.append(extra)
    return " · ".join(bits)


def _retry_two_digit_as_year(parsed: ParsedQuery, result: dict) -> bool:
    """‘Sachin New Zealand 94’ is often 1994 when no 94 vs that side exists."""
    if result.get("rows"):
        return False
    runs = parsed.tokens.get("runs")
    if not runs or not re.fullmatch(r"\d{1,2}", runs):
        return False
    if parsed.tokens.get("year") or parsed.tokens.get("years"):
        return False
    return bool(
        parsed.tokens.get("side")
        or parsed.tokens.get("opposition")
        or parsed.tokens.get("opp")
        or parsed.tokens.get("home")
    )


def _has_innings_constraint(tokens: dict[str, str]) -> bool:
    return any(
        k in tokens
        for k in (
            "player", "runs", "out", "dismissed_by", "notout",
            "opposition", "opp", "venue", "year", "years", "from", "to",
            "team", "format", "comp", "gender", "side", "event", "home", "away",
        )
    )


def _apply_side(con, tokens: dict[str, str], person_id: str | None) -> None:
    side = tokens.pop("side", None)
    if not side or tokens.get("opposition") or tokens.get("opp") or tokens.get("team"):
        return
    name = resolve_team(con, side) or side
    if person_id:
        n = con.execute(
            "SELECT COUNT(*) FROM xi WHERE person_id = ? AND lower(team) = lower(?)",
            [person_id, name],
        ).fetchone()[0]
        if not n:
            row = con.execute(
                """
                SELECT team FROM xi
                WHERE person_id = ? AND lower(team) LIKE ?
                GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1
                """,
                [person_id, f"%{name.lower()}%"],
            ).fetchone()
            if row:
                tokens["team"] = row[0]
                return
        else:
            tokens["team"] = name
            return
    tokens["opposition"] = name


def _match_filters(tokens: dict[str, str], alias: str = "m") -> tuple[list[str], list[Any]]:
    where = ["1=1"]
    params: list[Any] = []
    comp = _comp_filter(tokens)
    if comp:
        where.append(f"{alias}.competition = ?")
        params.append(comp)
    if tokens.get("gender"):
        g = "female" if tokens["gender"].lower().startswith(("f", "w")) else "male"
        where.append(f"{alias}.gender = ?")
        params.append(g)
    start, end = _date_bounds(tokens)
    if start:
        where.append(f"{alias}.start_date >= ?")
        params.append(start)
    if end:
        where.append(f"{alias}.start_date <= ?")
        params.append(end)
    if tokens.get("venue"):
        where.append(f"{alias}.venue ILIKE ?")
        params.append(f"%{tokens['venue']}%")
    if tokens.get("event"):
        where.append(f"lower({alias}.event_name) LIKE ?")
        params.append(f"%{tokens['event'].lower()}%")
    return where, params


def _exec_matches(con, parsed: ParsedQuery) -> dict:
    tokens = parsed.tokens
    player = tokens.get("player")
    people = _people_match(con, player) if player else []
    picked = pick_person(people, player) if people else None
    if player and not people:
        return {
            "ok": True,
            "kind": "empty",
            "title": parsed.raw,
            "message": f"No players match {player}.",
            "columns": [],
            "rows": [],
            "people": [],
            "scope": _scope_line(tokens, 0),
        }
    if people and not picked and player:
        return {
            "ok": True,
            "kind": "pick_player",
            "people": people,
            "message": f"{len(people)} players match “{player}”. Pick one.",
            "rows": [],
            "columns": [],
        }
    if picked:
        people = [picked]
        _apply_side(con, tokens, picked["person_id"])
    else:
        _apply_side(con, tokens, None)

    where, params = _match_filters(tokens)
    if picked:
        where.append("x.person_id = ?")
        params.append(picked["person_id"])
    home, away = tokens.get("home"), tokens.get("away")
    if home and away:
        a = resolve_team(con, home) or home
        b = resolve_team(con, away) or away
        where.append(
            f"(({_team_eq('m.team_home', a)} AND {_team_eq('m.team_away', b)})"
            f" OR ({_team_eq('m.team_home', b)} AND {_team_eq('m.team_away', a)}))"
        )
        params.extend([a, b, b, a])
    else:
        opp = tokens.get("opposition") or tokens.get("opp")
        side = tokens.get("team")
        if opp:
            resolved = resolve_team(con, opp) or opp
            if picked:
                where.append(
                    "((m.team_home = ? AND x.team <> m.team_home) OR (m.team_away = ? AND x.team <> m.team_away))"
                )
                params.extend([resolved, resolved])
            else:
                where.append("(m.team_home = ? OR m.team_away = ?)")
                params.extend([resolved, resolved])
        if side:
            resolved = resolve_team(con, side) or side
            if picked:
                where.append("x.team = ?")
                params.append(resolved)
            else:
                where.append("(m.team_home = ? OR m.team_away = ?)")
                params.extend([resolved, resolved])

    if picked:
        sql = f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner,
                   m.competition, m.gender, m.venue, m.event_name, m.result_method,
                   m.win_by_runs, m.win_by_wickets, m.win_by_innings, x.team AS player_team
            FROM matches m
            JOIN xi x ON x.match_id = m.match_id
            WHERE {' AND '.join(where)}
            ORDER BY m.start_date DESC
            LIMIT 200
        """
    else:
        sql = f"""
            SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner,
                   m.competition, m.gender, m.venue, m.event_name, m.result_method,
                   m.win_by_runs, m.win_by_wickets, m.win_by_innings, NULL AS player_team
            FROM matches m
            WHERE {' AND '.join(where)}
            ORDER BY m.start_date DESC
            LIMIT 200
        """
    recs = con.execute(sql, params).fetchall()
    cols = [
        "match_id", "start_date", "team_home", "team_away", "winner",
        "competition", "gender", "venue", "event_name", "result_method",
        "win_by_runs", "win_by_wickets", "win_by_innings", "player_team",
    ]
    rows = [dict(zip(cols, r)) for r in recs]
    for row in rows:
        row["fixture"] = f"{row['team_home']} v {row['team_away']}"
        row["result"] = _result_line({**row, "team": row.get("player_team") or row.get("winner")})
        if row.get("player_team") and row.get("winner"):
            row["result"] = (
                "Won" if row["winner"] == row["player_team"]
                else ("Lost" if row["winner"] else "—")
            )
            if row.get("result_method") == "dls":
                row["result"] += " (DLS)"
        elif row.get("winner"):
            row["result"] = f"{row['winner']} won"
    if len(rows) == 1:
        return {
            "ok": True,
            "kind": "goto_match",
            "match_id": rows[0]["match_id"],
            "people": people,
            "rows": rows,
        }
    title = parsed.heuristic or parsed.raw
    if not rows:
        return {
            "ok": True,
            "kind": "empty",
            "title": title,
            "message": f"No matches for {title}. Try a year, a format, or a last name.",
            "columns": [],
            "rows": [],
            "people": people,
            "scope": _scope_line(tokens, 0),
        }
    return {
        "ok": True,
        "kind": "matches",
        "title": title,
        "columns": [
            {"key": "start_date", "label": "Date", "align": "left", "link": "match"},
            {"key": "fixture", "label": "Match", "align": "left", "link": "match"},
            {"key": "competition", "label": "Comp", "align": "left"},
            {"key": "venue", "label": "Ground", "align": "left"},
            {"key": "result", "label": "Result", "align": "left"},
        ],
        "rows": rows,
        "people": people,
        "scope": _scope_line(tokens, len(rows), title if title != parsed.raw else ""),
        "empty_hint": (
            {"message": f"No matches for {title}. Try a year, a format, or a last name.", "chips": []}
            if not rows else None
        ),
    }


def _team_eq(column: str, _value: str) -> str:
    return f"{column} = ?"


def _exec_innings(con, parsed: ParsedQuery) -> dict:
    tokens = parsed.tokens
    if not _has_innings_constraint(tokens):
        ignored = parsed.ignored
        extra = f" Ignored {', '.join(ignored)}." if ignored else ""
        return {
            "ok": True,
            "kind": "empty",
            "title": parsed.raw,
            "message": "Add a player, a score, or a filter — a bare query would dump the whole application." + extra,
            "columns": [],
            "rows": [],
            "people": [],
            "scope": _scope_line(tokens, 0),
        }
    player = tokens.get("player")
    people = _people_match(con, player) if player else []
    where = ["b.innings_kind = 'regular'"]
    params: list[Any] = []
    if people:
        picked = pick_person(people, player)
        ids = [picked["person_id"]] if picked else [p["person_id"] for p in people]
        where.append(f"b.person_id IN ({','.join(['?'] * len(ids))})")
        params.extend(ids)
        if picked:
            people = [picked]
            _apply_side(con, tokens, picked["person_id"])
        else:
            _apply_side(con, tokens, None)
    elif player:
        return {
            "ok": True,
            "kind": "empty",
            "title": "No innings",
            "message": f"No players match {player}.",
            "columns": [],
            "rows": [],
            "people": [],
            "scope": _scope_line(tokens, 0),
        }
    else:
        _apply_side(con, tokens, None)
    runs = tokens.get("runs")
    if runs:
        if "-" in runs:
            a, b = runs.split("-", 1)
            lo, hi = _safe_int(a), _safe_int(b)
            if lo is None or hi is None:
                return {
                    "ok": True,
                    "kind": "empty",
                    "message": f"runs:{runs} needs numbers, like runs:80-120.",
                    "columns": [],
                    "rows": [],
                    "people": people,
                }
            if lo > hi:
                lo, hi = hi, lo
            where.append("b.runs BETWEEN ? AND ?")
            params.extend([lo, hi])
        else:
            exact = _safe_int(runs)
            if exact is None:
                return {
                    "ok": True,
                    "kind": "empty",
                    "message": f"runs:{runs} needs a number.",
                    "columns": [],
                    "rows": [],
                    "people": people,
                }
            where.append("b.runs = ?")
            params.append(exact)
    if tokens.get("notout") in {"true", "1", "yes"}:
        where.append("b.not_out = TRUE")
    if tokens.get("out"):
        where.append("lower(b.dismissal_kind) = ?")
        params.append(tokens["out"].lower())
    if tokens.get("dismissed_by"):
        bowlers = _people_match(con, tokens["dismissed_by"])
        if bowlers:
            ids = [p["person_id"] for p in bowlers]
            where.append(f"b.bowler_id IN ({','.join(['?'] * len(ids))})")
            params.extend(ids)
    comp = _comp_filter(tokens)
    if comp:
        where.append("m.competition = ?")
        params.append(comp)
    if tokens.get("gender"):
        g = "female" if tokens["gender"].lower().startswith("f") or tokens["gender"].lower() == "women" else "male"
        where.append("m.gender = ?")
        params.append(g)
    start, end = _date_bounds(tokens)
    if start:
        where.append("m.start_date >= ?")
        params.append(start)
    if end:
        where.append("m.start_date <= ?")
        params.append(end)
    if tokens.get("team"):
        where.append("(b.team ILIKE ? OR m.team_home ILIKE ? OR m.team_away ILIKE ?)")
        params.extend([f"%{tokens['team']}%"] * 3)
    if tokens.get("opposition") or tokens.get("opp"):
        opp = tokens.get("opposition") or tokens["opp"]
        resolved = resolve_team(con, opp)
        if resolved:
            where.append("((m.team_home = ? AND b.team <> m.team_home) OR (m.team_away = ? AND b.team <> m.team_away))")
            params.extend([resolved, resolved])
        else:
            where.append("((m.team_home ILIKE ? AND b.team <> m.team_home) OR (m.team_away ILIKE ? AND b.team <> m.team_away))")
            params.extend([f"%{opp}%"] * 2)
    if tokens.get("venue"):
        where.append("m.venue ILIKE ?")
        params.append(f"%{tokens['venue']}%")
    if tokens.get("event"):
        where.append("lower(m.event_name) LIKE ?")
        params.append(f"%{tokens['event'].lower()}%")

    sql = f"""
        SELECT b.match_id, m.start_date, p.display_name, p.slug, p.person_id,
               b.team,
               CASE WHEN b.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
               m.competition, m.gender, b.runs, b.balls, b.fours, b.sixes,
               CASE WHEN b.balls > 0 THEN ROUND(b.runs * 100.0 / b.balls, 1) END AS sr,
               b.dismissal_kind, b.not_out, m.winner, m.result_method, m.event_name
        FROM batting_lines b
        JOIN matches m ON m.match_id = b.match_id
        JOIN people p ON p.person_id = b.person_id
        WHERE {' AND '.join(where)}
        ORDER BY m.start_date DESC
        LIMIT 2000
    """
    recs = con.execute(sql, params).fetchall()
    cols = [
        "match_id", "start_date", "player", "slug", "person_id", "team", "opposition",
        "competition", "gender", "runs", "balls", "fours", "sixes", "sr",
        "dismissal", "not_out", "winner", "result_method", "event_name",
    ]
    rows = [dict(zip(cols, r)) for r in recs]
    for row in rows:
        row["runs_display"] = f"{row['runs']}*" if row["not_out"] else str(row["runs"])
        row["result"] = _result_line(row)
    packed = {
        "ok": True,
        "kind": "innings",
        "title": parsed.raw,
        "columns": [
            {"key": "start_date", "label": "Date", "align": "left", "link": "match"},
            {"key": "player", "label": "Player", "align": "left", "link": "player"},
            {"key": "opposition", "label": "Opp", "align": "left"},
            {"key": "competition", "label": "Comp", "align": "left"},
            {"key": "runs_display", "label": "R", "align": "right", "numeric": True},
            {"key": "balls", "label": "B", "align": "right", "numeric": True},
            {"key": "sr", "label": "SR", "align": "right", "numeric": True},
            {"key": "dismissal", "label": "Dismissal", "align": "left"},
            {"key": "result", "label": "Result", "align": "left"},
        ],
        "rows": rows,
        "people": people,
        "scope": _scope_line(tokens, len(rows)),
        "empty_hint": _empty_hint(con, parsed, people) if not rows else None,
    }
    if not rows:
        hint = packed.get("empty_hint") or {}
        packed["kind"] = "empty"
        packed["message"] = hint.get("message") or f"No innings match {parsed.raw}."
    return packed


def _result_line(row: dict) -> str:
    w = row.get("winner")
    team = row.get("team")
    if row.get("result_method") == "no_result":
        return "No result"
    if row.get("result_method") == "tie":
        return "Tie"
    if not w:
        return "—"
    mark = " (DLS)" if row.get("result_method") == "dls" else ""
    return ("Won" if w == team else "Lost") + mark


def _empty_hint(con, parsed: ParsedQuery, people: list[dict]) -> dict | None:
    if not people or "runs" not in parsed.tokens:
        return None
    pid = people[0]["person_id"]
    comp = _comp_filter(parsed.tokens)
    extra = "AND m.competition = ?" if comp else ""
    params: list[Any] = [pid]
    if comp:
        params.append(comp)
    row = con.execute(
        f"""
        SELECT MAX(b.runs), m.competition
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? {extra}
        GROUP BY m.competition
        ORDER BY MAX(b.runs) DESC LIMIT 1
        """,
        params,
    ).fetchone()
    if not row:
        return None
    name = people[0]["display_name"]
    return {
        "message": (
            f"No innings match {parsed.raw}. {name}'s highest"
            + (f" in {LABELS.get(comp, comp)}" if comp else "")
            + f" here is {row[0]} — try runs:{row[0]} or widen the filters."
        ),
        "chips": [f"{parsed.tokens.get('player', name)} {row[0]}", parsed.tokens.get("player", name)],
    }


def _exec_compare(con, parsed: ParsedQuery) -> dict:
    raw = parsed.tokens.get("compare", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) < 2:
        return {"ok": True, "kind": "empty", "message": "compare: needs two players.", "rows": [], "columns": []}
    left = _people_match(con, parts[0])
    right = _people_match(con, parts[1])
    if not left or not right:
        return {
            "ok": True,
            "kind": "empty",
            "message": f"Could not resolve compare:{raw}.",
            "rows": [],
            "columns": [],
        }
    a, b = pick_person(left, parts[0]), pick_person(right, parts[1])
    if not a:
        return {
            "ok": True,
            "kind": "pick_player",
            "people": left,
            "message": f"{len(left)} players match “{parts[0]}”. Pick one.",
            "rows": [],
            "columns": [],
        }
    if not b:
        return {
            "ok": True,
            "kind": "pick_player",
            "people": right,
            "message": f"{len(right)} players match “{parts[1]}”. Pick one.",
            "rows": [],
            "columns": [],
        }
    tokens = parsed.tokens
    start, end = _date_bounds(tokens)
    stats_a = _player_agg(con, a["person_id"], tokens, start, end)
    stats_b = _player_agg(con, b["person_id"], tokens, start, end)
    window = ""
    if start and end:
        window = f"{_fmt_year(start)}–{_fmt_year(end)}"
    rows = []
    specs = [
        ("matches", "Matches", False),
        ("innings", "Innings", False),
        ("runs", "Runs", False),
        ("average", "Average", False),
        ("sr", "Strike rate", False),
        ("wickets", "Wickets", False),
        ("bowl_avg", "Bowling avg", True),
        ("econ", "Econ", True),
        ("war", "WAR", False),
        ("rae_bat", "RAE bat", False),
        ("wpa", "WPA", False),
    ]
    for key, label, lower_better in specs:
        va, vb = stats_a.get(key), stats_b.get(key)
        delta = None
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = round(va - vb, 2 if isinstance(va, float) else 0)
        rows.append(
            {
                "stat": label,
                "left": va,
                "right": vb,
                "delta": delta,
                "lower_better": lower_better,
            }
        )
    return {
        "ok": True,
        "kind": "compare",
        "title": f"{a['display_name']} v {b['display_name']}" + (f" · {window}" if window else ""),
        "left": a,
        "right": b,
        "rows": rows,
        "caption": f"Δ = {a['display_name']} − {b['display_name']}",
        "scope": _scope_line(tokens, 2, "in this application"),
        "people": [a, b],
    }


def _fmt_year(d: str) -> str:
    return d[:4]


def _player_agg(con, pid: str, tokens: dict, start: str | None, end: str | None) -> dict:
    where = ["b.person_id = ?", "b.innings_kind = 'regular'"]
    params: list[Any] = [pid]
    comp = _comp_filter(tokens)
    if comp:
        where.append("m.competition = ?")
        params.append(comp)
    if start:
        where.append("m.start_date >= ?")
        params.append(start)
    if end:
        where.append("m.start_date <= ?")
        params.append(end)
    if tokens.get("gender"):
        g = "female" if tokens["gender"].lower().startswith(("f", "w")) else "male"
        where.append("m.gender = ?")
        params.append(g)
    bat = con.execute(
        f"""
        SELECT COUNT(DISTINCT b.match_id), COUNT(*), SUM(b.runs), SUM(b.balls),
               SUM(CASE WHEN b.not_out THEN 0 ELSE 1 END)
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE {' AND '.join(where)}
        """,
        params,
    ).fetchone()
    bowl_where = ["bl.person_id = ?", "bl.innings_kind = 'regular'"]
    bowl_params: list[Any] = [pid]
    if comp:
        bowl_where.append("m.competition = ?")
        bowl_params.append(comp)
    if start:
        bowl_where.append("m.start_date >= ?")
        bowl_params.append(start)
    if end:
        bowl_where.append("m.start_date <= ?")
        bowl_params.append(end)
    if tokens.get("gender"):
        g = "female" if tokens["gender"].lower().startswith(("f", "w")) else "male"
        bowl_where.append("m.gender = ?")
        bowl_params.append(g)
    bowl = con.execute(
        f"""
        SELECT SUM(bl.wickets), SUM(bl.runs), SUM(bl.legal_balls)
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE {' AND '.join(bowl_where)}
        """,
        bowl_params,
    ).fetchone()
    matches, inns, runs, balls, outs = bat
    wickets, bowl_runs, legal = bowl
    runs = int(runs or 0)
    balls = int(balls or 0)
    outs = int(outs or 0)
    wickets = int(wickets or 0)
    bowl_runs = int(bowl_runs or 0)
    legal = int(legal or 0)
    met = None
    try:
        met_where = ["person_id = ?"]
        met_params: list[Any] = [pid]
        if comp:
            met_where.append("competition = ?")
            met_params.append(comp)
        if tokens.get("gender"):
            g = "female" if tokens["gender"].lower().startswith(("f", "w")) else "male"
            met_where.append("gender = ?")
            met_params.append(g)
        if start:
            met_where.append("season >= ?")
            met_params.append(start[:4])
        if end:
            met_where.append("left(season, 4) <= ?")
            met_params.append(end[:4])
        met = con.execute(
            f"""
            SELECT SUM(war), SUM(rae_bat), SUM(wpa)
            FROM metrics_t20 WHERE {' AND '.join(met_where)}
            """,
            met_params,
        ).fetchone()
    except Exception:
        met = (None, None, None)
    return {
        "matches": int(matches or 0),
        "innings": int(inns or 0),
        "runs": runs,
        "average": round(runs / outs, 1) if outs else None,
        "sr": round(runs * 100 / balls, 1) if balls else None,
        "wickets": wickets,
        "bowl_avg": round(bowl_runs / wickets, 1) if wickets else None,
        "econ": round(bowl_runs * 6 / legal, 2) if legal else None,
        "war": round(float(met[0]), 2) if met and met[0] is not None else None,
        "rae_bat": round(float(met[1]), 1) if met and met[1] is not None else None,
        "wpa": round(float(met[2]), 2) if met and met[2] is not None else None,
    }


def _exec_pair(con, parsed: ParsedQuery) -> dict:
    tokens = parsed.tokens
    pair = tokens.get("pair", "*")
    min_n = _safe_int(tokens.get("min_partnerships"), 10) or 10
    where = ["pr.innings_kind = 'regular'"]
    params: list[Any] = []
    if pair != "*":
        parts = [p.strip() for p in pair.split(",") if p.strip()]
        ids = []
        for p in parts:
            found = pick_person(_people_match(con, p), p)
            if found:
                ids.append(found["person_id"])
        if len(ids) == 2:
            a, b = sorted(ids)
            where.append("pr.person_id_1 = ? AND pr.person_id_2 = ?")
            params.extend([a, b])
        elif len(ids) == 1:
            where.append("(pr.person_id_1 = ? OR pr.person_id_2 = ?)")
            params.extend([ids[0], ids[0]])
    comp = _comp_filter(tokens)
    if comp:
        where.append("m.competition = ?")
        params.append(comp)
    start, end = _date_bounds(tokens)
    if start:
        where.append("m.start_date >= ?")
        params.append(start)
    if end:
        where.append("m.start_date <= ?")
        params.append(end)
    recs = con.execute(
        f"""
        SELECT pr.person_id_1, pr.person_id_2, p1.display_name, p2.display_name,
               p1.slug, p2.slug,
               COUNT(*) AS inns, SUM(pr.runs) AS runs,
               ROUND(AVG(pr.runs), 1) AS avg,
               SUM(CASE WHEN pr.runs >= 50 THEN 1 ELSE 0 END) AS fifties,
               SUM(CASE WHEN pr.runs >= 100 THEN 1 ELSE 0 END) AS hundreds
        FROM partnerships pr
        JOIN matches m ON m.match_id = pr.match_id
        JOIN people p1 ON p1.person_id = pr.person_id_1
        JOIN people p2 ON p2.person_id = pr.person_id_2
        WHERE {' AND '.join(where)}
        GROUP BY 1,2,3,4,5,6
        HAVING COUNT(*) >= ?
        ORDER BY SUM(pr.runs) DESC
        """,
        params + [min_n],
    ).fetchall()
    cols = ["id1", "id2", "name1", "name2", "slug1", "slug2", "inns", "runs", "avg", "fifties", "hundreds"]
    rows = [dict(zip(cols, r)) for r in recs]
    for row in rows:
        row["pair"] = f"{row['name1']} / {row['name2']}"
    return {
        "ok": True,
        "kind": "pair",
        "title": "Partnerships",
        "columns": [
            {"key": "pair", "label": "Pair", "align": "left"},
            {"key": "inns", "label": "Inns", "align": "right", "numeric": True},
            {"key": "runs", "label": "Runs", "align": "right", "numeric": True},
            {"key": "avg", "label": "Avg", "align": "right", "numeric": True},
            {"key": "hundreds", "label": "100-stands", "align": "right", "numeric": True},
            {"key": "fifties", "label": "50+", "align": "right", "numeric": True},
        ],
        "rows": rows,
        "scope": _scope_line(tokens, len(rows), f"min {min_n} stands"),
    }


def _exec_war(con, parsed: ParsedQuery) -> dict:
    tokens = parsed.tokens
    where = ["1=1"]
    params: list[Any] = []
    comp = _comp_filter(tokens)
    if comp:
        where.append("mt.competition = ?")
        params.append(comp)
    if tokens.get("gender"):
        g = "female" if tokens["gender"].lower().startswith(("f", "w")) else "male"
        where.append("mt.gender = ?")
        params.append(g)
    years = tokens.get("years") or tokens.get("year")
    if years:
        m = re.match(r"(\d{4})(?:\s*[-–]\s*(\d{4}))?", years)
        if m:
            y0 = int(m.group(1))
            y1 = int(m.group(2) or m.group(1))
            if y0 > y1:
                y0, y1 = y1, y0
            where.append("TRY_CAST(left(mt.season, 4) AS INTEGER) BETWEEN ? AND ?")
            params.extend([y0, y1])
    min_balls = _safe_int(tokens.get("min_balls"), 0) or 0
    if min_balls:
        where.append("(mt.balls_bat + mt.balls_bowl) >= ?")
        params.append(min_balls)
    recs = con.execute(
        f"""
        SELECT mt.person_id, p.display_name, p.slug, mt.competition, mt.season, mt.gender,
               mt.role, mt.balls_bat, mt.balls_bowl, mt.rae_bat, mt.rae_bowl, mt.wpa,
               mt.war, mt.pressure_impact, mt.overall_default, mt.confidence, mt.dls_share
        FROM metrics_t20 mt
        JOIN people p ON p.person_id = mt.person_id
        WHERE {' AND '.join(where)}
        ORDER BY mt.war DESC NULLS LAST
        LIMIT 500
        """,
        params,
    ).fetchall()
    cols = [
        "person_id", "player", "slug", "competition", "season", "gender", "role",
        "balls_bat", "balls_bowl", "rae_bat", "rae_bowl", "wpa", "war",
        "pressure_impact", "overall", "confidence", "dls_share",
    ]
    rows = [dict(zip(cols, r)) for r in recs]
    # qualifier filter default on
    filtered = []
    career = {}
    for r in rows:
        career[r["person_id"]] = career.get(r["person_id"], 0) + (r["balls_bat"] or 0) + (r["balls_bowl"] or 0)
    for r in rows:
        r["balls"] = (r["balls_bat"] or 0) + (r["balls_bowl"] or 0)
        if is_qualifier(
            {"competition": r["competition"], "balls_bat": r["balls_bat"], "balls_bowl": r["balls_bowl"]},
            career_balls=career.get(r["person_id"], 0),
        ):
            filtered.append(r)
    use = filtered
    for i, r in enumerate(use, start=1):
        r["rank"] = i
    return {
        "ok": True,
        "kind": "war",
        "title": "WAR — in this application",
        "columns": [
            {"key": "rank", "label": "#", "align": "right", "numeric": True},
            {"key": "player", "label": "Player", "align": "left", "link": "player"},
            {"key": "competition", "label": "Comp", "align": "left"},
            {"key": "season", "label": "Season", "align": "left"},
            {"key": "balls", "label": "Balls", "align": "right", "numeric": True},
            {"key": "rae_bat", "label": "RAE", "align": "right", "numeric": True},
            {"key": "wpa", "label": "WPA", "align": "right", "numeric": True},
            {"key": "pressure_impact", "label": "Pressure", "align": "right", "numeric": True},
            {"key": "overall", "label": "Overall", "align": "right", "numeric": True},
            {"key": "war", "label": "WAR", "align": "right", "numeric": True},
        ],
        "rows": use,
        "scope": _scope_line(tokens, len(use), "qualifiers · in this application"),
        "redirect": "metrics",
    }


def _exec_standings(con, parsed: ParsedQuery) -> dict:
    tokens = parsed.tokens
    comp = _comp_filter(tokens) or "ipl"
    year = (tokens.get("year") or tokens.get("years") or tokens.get("standings") or "").split("-")[0]
    where = ["competition = ?"]
    params: list[Any] = [comp]
    if year and year.isdigit():
        where.append("season LIKE ?")
        params.append(f"{year}%")
    if tokens.get("gender"):
        g = "female" if tokens["gender"].lower().startswith(("f", "w")) else "male"
        where.append("gender = ?")
        params.append(g)
    elif comp in {"t20i", "odi", "test"}:
        where.append("gender = ?")
        params.append("male")
    recs = con.execute(
        f"""
        SELECT season, gender, position, team, played, won, lost, tied, no_result, points, nrr
        FROM standings
        WHERE {' AND '.join(where)}
        ORDER BY season DESC, gender, position
        """,
        params,
    ).fetchall()
    cols = ["season", "gender", "position", "team", "played", "won", "lost", "tied", "no_result", "points", "nrr"]
    rows = [dict(zip(cols, r)) for r in recs]
    play = con.execute(
        """
        SELECT match_id, season, event_stage, team_home, team_away, winner, start_date
        FROM playoffs WHERE competition = ?
        ORDER BY start_date
        """,
        [comp],
    ).fetchall()
    pcols = ["match_id", "season", "event_stage", "team_home", "team_away", "winner", "start_date"]
    playoffs = [dict(zip(pcols, r)) for r in play]
    if year and year.isdigit():
        playoffs = [p for p in playoffs if str(p["season"]).startswith(year)]
    return {
        "ok": True,
        "kind": "standings",
        "title": f"{LABELS.get(comp, comp)} standings",
        "columns": [
            {"key": "position", "label": "#", "align": "right", "numeric": True},
            {"key": "team", "label": "Team", "align": "left"},
            {"key": "played", "label": "P", "align": "right", "numeric": True},
            {"key": "won", "label": "W", "align": "right", "numeric": True},
            {"key": "lost", "label": "L", "align": "right", "numeric": True},
            {"key": "tied", "label": "T", "align": "right", "numeric": True},
            {"key": "no_result", "label": "NR", "align": "right", "numeric": True},
            {"key": "points", "label": "Pts", "align": "right", "numeric": True},
            {"key": "nrr", "label": "NRR", "align": "right", "numeric": True},
        ],
        "rows": rows,
        "playoffs": playoffs,
        "scope": _scope_line(tokens, len(rows)),
    }


def _exec_split(con, parsed: ParsedQuery) -> dict:
    tokens = parsed.tokens
    team = tokens.get("team")
    with_p = tokens.get("with")
    without_p = tokens.get("without")
    if not team:
        return {"ok": True, "kind": "empty", "message": "with/without needs team:", "rows": [], "columns": []}
    person_tok = with_p or without_p
    people = _people_match(con, person_tok) if person_tok else []
    person = pick_person(people, person_tok)
    if not person:
        if people:
            return {
                "ok": True,
                "kind": "pick_player",
                "people": people,
                "message": f"{len(people)} players match “{person_tok}”. Pick one.",
                "rows": [],
                "columns": [],
            }
        return {"ok": True, "kind": "empty", "message": f"No player match for {person_tok}.", "rows": [], "columns": []}
    pid = person["person_id"]
    name = person["display_name"]
    side = resolve_team(con, team)
    if not side:
        return {"ok": True, "kind": "empty", "message": f"No side matching {team}.", "rows": [], "columns": []}
    first = con.execute(
        """
        SELECT MIN(m.start_date)
        FROM matches m
        JOIN xi x ON x.match_id = m.match_id
        WHERE x.person_id = ? AND x.team = ?
        """,
        [pid, side],
    ).fetchone()[0]
    recs = con.execute(
        """
        SELECT m.match_id, m.start_date, m.team_home, m.team_away, m.winner, m.result_method,
               EXISTS (
                 SELECT 1 FROM xi x
                 WHERE x.match_id = m.match_id AND x.person_id = ? AND x.team = ?
               ) AS present
        FROM matches m
        WHERE (m.team_home = ? OR m.team_away = ?)
          AND (? IS NULL OR m.start_date >= ?)
        """,
        [pid, side, side, side, first, first],
    ).fetchall()
    with_m = [r for r in recs if r[6]]
    without_m = [r for r in recs if not r[6]]

    def summarize(group, label):
        n = len(group)
        wins = sum(1 for r in group if r[4] == side)
        return {
            "split": label,
            "matches": n,
            "wins": wins,
            "win_pct": round(100 * wins / n, 1) if n else None,
        }

    rows = [
        summarize(with_m, f"With {name}"),
        summarize(without_m, f"Without {name}"),
    ]
    wpa = None
    try:
        wpa = con.execute(
            "SELECT SUM(wpa) FROM metrics_t20 WHERE person_id = ?", [pid]
        ).fetchone()[0]
    except Exception:
        wpa = None
    return {
        "ok": True,
        "kind": "split",
        "title": f"{side} with {name}",
        "columns": [
            {"key": "split", "label": "Split", "align": "left"},
            {"key": "matches", "label": "N", "align": "right", "numeric": True},
            {"key": "wins", "label": "Wins", "align": "right", "numeric": True},
            {"key": "win_pct", "label": "Win %", "align": "right", "numeric": True},
        ],
        "rows": rows,
        "wpa": round(float(wpa), 2) if wpa is not None else None,
        "people": people,
        "scope": _scope_line(tokens, len(recs), "in this application"),
    }


def suggest(q: str) -> dict:
    q = (q or "").strip()
    parsed = parse_query(q) if q else None
    player = (parsed.tokens.get("player") if parsed else None) or q
    people = search_people(player) if len(player) >= 2 else []
    teams: list[dict] = []
    if parsed and (parsed.tokens.get("side") or parsed.tokens.get("opposition") or parsed.tokens.get("home")):
        hint = parsed.tokens.get("opposition") or parsed.tokens.get("side") or parsed.tokens.get("home") or ""
        teams = search_teams(hint)
    elif q and ":" not in q:
        last = q.split()[-1]
        if len(last) >= 2:
            teams = search_teams(last)
    token_rows = []
    ql = q.lower()
    if ":" in q:
        key, _, rest = q.partition(":")
        token_rows = [{"key": k, "hint": h} for k, h in TOKEN_HELP if k.startswith(key.lower())]
        if rest and key.lower() in {"player", "compare", "with", "without", "pair", "dismissed_by"}:
            people = search_people(rest) or people
    elif len(ql) < 12 and any(k.startswith(ql) or ql in h.lower() for k, h in TOKEN_HELP):
        token_rows = [{"key": k, "hint": h} for k, h in TOKEN_HELP if k.startswith(ql) or ql in h.lower()][:6]
    return {
        "tokens": token_rows,
        "people": people,
        "teams": teams,
        "parsed": {
            "tokens": parsed.tokens if parsed else {},
            "mode": parsed.mode if parsed else None,
            "heuristic": parsed.heuristic if parsed else None,
            "interpretation": interpretation(parsed.tokens, parsed.tokens.get("player")) if parsed else "",
        } if parsed else {},
    }
