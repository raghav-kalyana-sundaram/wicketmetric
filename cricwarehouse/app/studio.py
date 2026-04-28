"""Compare studio: match composites, player/team compare, twins, stat-line shift."""

from __future__ import annotations

from typing import Any

from cricwarehouse.app.catalog import (
    _attach_wtc,
    _jsonable,
    _people_match,
    career_value,
    matchups,
)
from cricwarehouse.app.db import connect, warehouse_ready
from cricwarehouse.teams import POOL_LABELS, default_pool, parse_comps, wtc_match_sql
from cricwarehouse.competitions import LABELS, T20_METRICS

# Ground country for Tests/ODIs — Cricsheet team_home is not the host.
_TEAM_CC = {
    "India": "IND",
    "Australia": "AUS",
    "England": "ENG",
    "South Africa": "SA",
    "New Zealand": "NZ",
    "Sri Lanka": "SL",
    "Bangladesh": "BAN",
    "Pakistan": "PAK",
    "West Indies": "WI",
    "Zimbabwe": "ZIM",
    "Ireland": "IRE",
    "Afghanistan": "AFG",
}
_CITY_CC = {
    "London": "ENG", "Birmingham": "ENG", "Nottingham": "ENG", "Leeds": "ENG",
    "Manchester": "ENG", "Southampton": "ENG", "Cardiff": "ENG", "Bristol": "ENG",
    "Chester-le-Street": "ENG", "Taunton": "ENG", "Worcester": "ENG", "Leicester": "ENG",
    "Canterbury": "ENG", "Wormsley": "ENG",
    "Melbourne": "AUS", "Sydney": "AUS", "Brisbane": "AUS", "Perth": "AUS",
    "Adelaide": "AUS", "Hobart": "AUS", "Canberra": "AUS", "Darwin": "AUS",
    "Carrara": "AUS", "Mackay": "AUS", "Bowral": "AUS",
    "Cape Town": "SA", "Centurion": "SA", "Johannesburg": "SA", "Durban": "SA",
    "Port Elizabeth": "SA", "Gqeberha": "SA", "Bloemfontein": "SA", "Potchefstroom": "SA",
    "Wellington": "NZ", "Christchurch": "NZ", "Hamilton": "NZ", "Dunedin": "NZ",
    "Auckland": "NZ", "Mount Maunganui": "NZ", "Napier": "NZ",
    "Colombo": "SL", "Galle": "SL", "Kandy": "SL", "Pallekele": "SL",
    "Dhaka": "BAN", "Chattogram": "BAN", "Mirpur": "BAN", "Chittagong": "BAN",
    "Sylhet": "BAN", "Khulna": "BAN", "Fatullah": "BAN", "Bogra": "BAN",
    "Kolkata": "IND", "Chennai": "IND", "Ahmedabad": "IND", "Mumbai": "IND",
    "Chandigarh": "IND", "Nagpur": "IND", "Delhi": "IND", "Hyderabad": "IND",
    "Kanpur": "IND", "Bengaluru": "IND", "Bangalore": "IND", "Visakhapatnam": "IND",
    "Pune": "IND", "Ranchi": "IND", "Indore": "IND", "Rajkot": "IND",
    "Dharamsala": "IND", "Guwahati": "IND", "Navi Mumbai": "IND",
    "Rawalpindi": "PAK", "Karachi": "PAK", "Multan": "PAK", "Lahore": "PAK", "Faisalabad": "PAK",
    "Abu Dhabi": "UAE", "Sharjah": "UAE", "Dubai": "UAE",
    "Barbados": "WI", "Jamaica": "WI", "North Sound": "WI", "Antigua": "WI",
    "Trinidad": "WI", "Kingston": "WI", "Dominica": "WI", "Bridgetown": "WI",
    "Gros Islet": "WI", "St Lucia": "WI", "Port of Spain": "WI", "St Kitts": "WI",
    "St John's": "WI", "Guyana": "WI", "St George's": "WI", "Grenada": "WI",
    "St Vincent": "WI", "Roseau": "WI", "Providence": "WI", "Tarouba": "WI",
    "Bulawayo": "ZIM", "Harare": "ZIM",
    "Belfast": "IRE", "Dublin": "IRE",
}
_VENUE_CC = (
    ("galle", "SL"), ("adelaide oval", "AUS"), ("sydney cricket ground", "AUS"),
    ("melbourne cricket ground", "AUS"), ("perth stadium", "AUS"), ("waca", "AUS"),
    ("gabba", "AUS"), ("dubai", "UAE"), ("sharjah", "UAE"), ("harare sports", "ZIM"),
    ("pallekele", "SL"), ("chittagong", "BAN"), ("multan", "PAK"), ("sylhet", "BAN"),
    ("wankhede", "IND"), ("chidambaram", "IND"), ("eden gardens", "IND"),
    ("chinnaswamy", "IND"), ("modi stadium", "IND"), ("lord", "ENG"),
    ("kennington oval", "ENG"), ("trent bridge", "ENG"), ("headingley", "ENG"),
    ("edgbaston", "ENG"), ("wanderers", "SA"), ("newlands", "SA"),
    ("supersport", "SA"), ("basin reserve", "NZ"), ("hagley", "NZ"), ("sabina", "WI"),
)


def _ground_cc(city: str | None, venue: str | None) -> str | None:
    if city and city in _CITY_CC:
        return _CITY_CC[city]
    v = (venue or "").lower()
    for needle, cc in _VENUE_CC:
        if needle in v:
            return cc
    return None


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
    """One row per player-match: bat and bowl value from the same night, added, then ranked."""
    if not warehouse_ready():
        return {"rows": [], "caption": "Warehouse not built"}
    con = connect()
    try:
        if wtc:
            _attach_wtc(con, gender)
        where = ["1=1"]
        params: list[Any] = []
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
            nrc_sql = "g.bat_nrc"
            blend_sql = "g.bat_blend"
        elif focus == "bowl":
            floor = "g.bowl_balls >= 6"
            nrc_sql = "g.bowl_nrc"
            blend_sql = "g.bowl_blend"
        else:
            floor = "g.bat_balls + g.bowl_balls >= 12"
            nrc_sql = "g.bat_nrc + g.bowl_nrc"
            blend_sql = "g.bat_blend + g.bowl_blend"
        person_f = ""
        extra: list[Any] = []
        if person_id:
            person_f = "WHERE r.person_id = ?"
            extra.append(person_id)
        recs = con.execute(
            f"""
            WITH g AS (
              SELECT pf.person_id, pf.match_id, pf.competition, pf.gender, pf.team,
                     SUM(CASE WHEN pf.discipline = 'bat' THEN pf.balls ELSE 0 END) AS bat_balls,
                     SUM(CASE WHEN pf.discipline = 'bowl' THEN pf.balls ELSE 0 END) AS bowl_balls,
                     SUM(CASE WHEN pf.discipline = 'bat' THEN pf.nrc ELSE 0 END) AS bat_nrc,
                     SUM(CASE WHEN pf.discipline = 'bowl' THEN pf.nrc ELSE 0 END) AS bowl_nrc,
                     SUM(CASE WHEN pf.discipline = 'bat' THEN pf.wpa_runs ELSE 0 END) AS bat_wpa,
                     SUM(CASE WHEN pf.discipline = 'bowl' THEN pf.wpa_runs ELSE 0 END) AS bowl_wpa,
                     SUM(CASE WHEN pf.discipline = 'bat' THEN pf.press ELSE 0 END) AS bat_press,
                     SUM(CASE WHEN pf.discipline = 'bowl' THEN pf.press ELSE 0 END) AS bowl_press,
                     SUM(CASE WHEN pf.discipline = 'bat' THEN pf.blend ELSE 0 END) AS bat_blend,
                     SUM(CASE WHEN pf.discipline = 'bowl' THEN pf.blend ELSE 0 END) AS bowl_blend,
                     MAX(CASE WHEN pf.discipline = 'bat' THEN pf.line END) AS bat_line,
                     MAX(CASE WHEN pf.discipline = 'bowl' THEN pf.line END) AS bowl_line
              FROM performances_t20 pf
              JOIN matches m ON m.match_id = pf.match_id
              WHERE {' AND '.join(where)}
              GROUP BY 1,2,3,4,5
            ),
            ok AS (
              SELECT g.*, {nrc_sql} AS nrc, {blend_sql} AS blend
              FROM g
              WHERE {floor}
            ),
            r AS (
              SELECT ok.*,
                     ROUND(100 + 10 * blend, 1) AS composite,
                     ROUND(PERCENT_RANK() OVER (
                       PARTITION BY competition, gender
                       ORDER BY blend
                     ) * 100, 1) AS score
              FROM ok
            )
            SELECT r.*, p.display_name, p.slug,
                   CASE WHEN r.team = m.team_home THEN m.team_away ELSE m.team_home END AS opposition,
                   m.venue, m.winner, m.start_date, m.result_method
            FROM r
            JOIN people p ON p.person_id = r.person_id
            JOIN matches m ON m.match_id = r.match_id
            {person_f}
            ORDER BY r.composite DESC, r.nrc DESC
            LIMIT ?
            """,
            params + extra + [int(limit)],
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

        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
            row["player"] = row.get("display_name")
            bat, bowl = _ok_line(row.get("bat_line")), _ok_line(row.get("bowl_line"))
            if bat and bowl:
                row["line"] = f"{bat} & {bowl}"
            else:
                row["line"] = bat or bowl
            row["result"] = "Won" if row.get("winner") == row.get("team") else ("Lost" if row.get("winner") else "—")
            row["discipline"] = focus or "match"
        cap = "Composite index: 100 is the reference line; each 10 points is one blended standard deviation. Batting and bowling value from the same match are added."
        if focus == "bat":
            cap = "Ranked on batting value. Bowling from the same match is folded into the line when they bowled."
        elif focus == "bowl":
            cap = "Ranked on bowling value. Batting from the same match is folded into the line when they batted."
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
        gender = pa.get("gender") or pb.get("gender")
        pool = pool or default_pool(gender)
        va = career_value(pa["person_id"], pool=pool, gender=gender)
        vb = career_value(pb["person_id"], pool=pool, gender=gender)
        comps = parse_comps(pool)
        h2h = _pair_h2h(con, pa["person_id"], pb["person_id"], comps=comps)
        ma = matchups(pa["person_id"], comp=pool)
        mb = matchups(pb["person_id"], comp=pool)
        t20 = bool(comps) and all(c in T20_METRICS for c in comps)
        ia = _xi_impact(con, pa["person_id"], comps=comps)
        ib = _xi_impact(con, pb["person_id"], comps=comps)
        sa = _format_line(con, pa["person_id"], comps)
        sb = _format_line(con, pb["person_id"], comps)
        pairing = _pairing(sa.get("primary_role"), sb.get("primary_role"))
        return {
            "ok": True,
            "kind": "compare",
            "a": {**pa, "value": va, "xi": ia, "line": sa, "primary_role": sa.get("primary_role")},
            "b": {**pb, "value": vb, "xi": ib, "line": sb, "primary_role": sb.get("primary_role")},
            "h2h": h2h,
            "rows": _value_rows(va, vb) if t20 else [],
            "classic": _classic_rows(sa, sb),
            "pairing": pairing,
            "shared_bowlers": _shared_opponents(
                ma.get("as_batter") or [], mb.get("as_batter") or [], kind="bat", tests=not t20 and pool == "test"
            ),
            "shared_batters": _shared_opponents(
                ma.get("as_bowler") or [], mb.get("as_bowler") or [], kind="bowl", tests=not t20 and pool == "test"
            ),
            "pool": pool,
            "pool_label": POOL_LABELS.get(pool, pool),
            "has_t20_value": t20 and bool(va.get("metrics") or vb.get("metrics")),
        }
    finally:
        con.close()


def _xi_rates(con, pid: str, team: str, match_ids: list[str], with_ids: set[str]) -> dict[str, Any] | None:
    if not match_ids:
        return None
    ph = ",".join(["?"] * len(match_ids))
    with_list = list(with_ids)
    bat = con.execute(
        f"""
        SELECT
          SUM(CASE WHEN list_contains(?, b.match_id) THEN b.runs ELSE 0 END),
          SUM(CASE WHEN list_contains(?, b.match_id) AND NOT b.not_out THEN 1 ELSE 0 END),
          SUM(CASE WHEN list_contains(?, b.match_id) THEN b.balls ELSE 0 END),
          SUM(CASE WHEN NOT list_contains(?, b.match_id) THEN b.runs ELSE 0 END),
          SUM(CASE WHEN NOT list_contains(?, b.match_id) AND NOT b.not_out THEN 1 ELSE 0 END),
          SUM(CASE WHEN NOT list_contains(?, b.match_id) THEN b.balls ELSE 0 END),
          COUNT(DISTINCT CASE WHEN list_contains(?, b.match_id) THEN b.match_id END),
          COUNT(DISTINCT CASE WHEN NOT list_contains(?, b.match_id) THEN b.match_id END)
        FROM batting_lines b
        JOIN xi x ON x.match_id = b.match_id AND x.person_id = b.person_id AND x.team = ?
        WHERE b.person_id <> ? AND b.innings_kind = 'regular' AND b.match_id IN ({ph})
        """,
        [with_list] * 8 + [team, pid] + match_ids,
    ).fetchone()
    bowl = con.execute(
        f"""
        SELECT
          SUM(CASE WHEN list_contains(?, bl.match_id) THEN bl.wickets ELSE 0 END),
          SUM(CASE WHEN list_contains(?, bl.match_id) THEN bl.runs ELSE 0 END),
          SUM(CASE WHEN list_contains(?, bl.match_id) THEN bl.legal_balls ELSE 0 END),
          SUM(CASE WHEN NOT list_contains(?, bl.match_id) THEN bl.wickets ELSE 0 END),
          SUM(CASE WHEN NOT list_contains(?, bl.match_id) THEN bl.runs ELSE 0 END),
          SUM(CASE WHEN NOT list_contains(?, bl.match_id) THEN bl.legal_balls ELSE 0 END)
        FROM bowling_lines bl
        JOIN xi x ON x.match_id = bl.match_id AND x.person_id = bl.person_id AND x.team = ?
        WHERE bl.person_id <> ? AND bl.innings_kind = 'regular' AND bl.match_id IN ({ph})
        """,
        [with_list] * 6 + [team, pid] + match_ids,
    ).fetchone()

    def _n(v, default=0):
        try:
            if v is None or v != v:
                return default
            return int(v)
        except (TypeError, ValueError):
            return default

    def rate(num, den, places=1):
        if not den:
            return None
        try:
            if num is None or num != num:
                return None
            return round(float(num) / den, places)
        except (TypeError, ValueError):
            return None

    def dlt(a, b, places=1):
        if a is None or b is None:
            return None
        return round(a - b, places)

    ru_w, ou_w, ba_w, ru_o, ou_o, ba_o, m_w, m_o = [_n(x) for x in (bat or (0,) * 8)]
    wk_w, br_w, bb_w, wk_o, br_o, bb_o = [_n(x) for x in (bowl or (0,) * 6)]
    bat_avg_w, bat_avg_o = rate(ru_w, ou_w, 1), rate(ru_o, ou_o, 1)
    return {
        "matches_with": m_w,
        "matches_wo": m_o,
        "bat": {
            "avg_with": bat_avg_w,
            "avg_wo": bat_avg_o,
            "avg_delta": dlt(bat_avg_w, bat_avg_o, 1),
            "sr_with": round(ru_w * 100 / ba_w, 1) if ba_w else None,
            "sr_wo": round(ru_o * 100 / ba_o, 1) if ba_o else None,
        },
        "bowl": {
            "econ_with": round(br_w * 6 / bb_w, 2) if bb_w else None,
            "econ_wo": round(br_o * 6 / bb_o, 2) if bb_o else None,
            "econ_delta": dlt(
                round(br_w * 6 / bb_w, 2) if bb_w else None,
                round(br_o * 6 / bb_o, 2) if bb_o else None,
                2,
            ),
            "avg_with": rate(br_w, wk_w, 1),
            "avg_wo": rate(br_o, wk_o, 1),
        },
    }


def _xi_impact(con, pid: str, *, comps: list[str] | None = None) -> dict[str, Any]:
    """Teammates' batting/bowling with this player in the XI vs without, one side, one format pool."""
    extra = ""
    extra_params: list[Any] = []
    if comps:
        ph = ",".join(["?"] * len(comps))
        extra = f" AND m.competition IN ({ph})"
        extra_params = list(comps)
    team_row = con.execute(
        f"""
        SELECT x.team, COUNT(*) FROM xi x
        JOIN matches m ON m.match_id = x.match_id
        WHERE x.person_id = ?{extra}
        GROUP BY 1 ORDER BY 2 DESC LIMIT 1
        """,
        [pid] + extra_params,
    ).fetchone()
    if not team_row:
        return {"ok": False}
    team = team_row[0]
    first = con.execute(
        f"""
        SELECT MIN(m.start_date) FROM matches m
        JOIN xi x ON x.match_id = m.match_id
        WHERE x.person_id = ? AND x.team = ?{extra}
        """,
        [pid, team] + extra_params,
    ).fetchone()[0]
    if not first:
        return {"ok": False, "team": team}
    with_ids = {
        r[0]
        for r in con.execute(
            f"""
            SELECT m.match_id FROM matches m
            JOIN xi x ON x.match_id = m.match_id
            WHERE x.person_id = ? AND x.team = ? AND m.start_date >= ?{extra}
            """,
            [pid, team, first] + extra_params,
        ).fetchall()
    }
    team_rows = con.execute(
        f"""
        SELECT m.match_id, m.city, m.venue FROM matches m
        WHERE (m.team_home = ? OR m.team_away = ?) AND m.start_date >= ?{extra}
        """,
        [team, team, first] + extra_params,
    ).fetchall()
    all_ids = [r[0] for r in team_rows]
    pooled = _xi_rates(con, pid, team, all_ids, with_ids)
    if not pooled:
        return {"ok": False, "team": team}
    home_ids, away_ids = [], []
    cc = _TEAM_CC.get(team)
    if cc:
        for mid, city, venue in team_rows:
            g = _ground_cc(city, venue)
            if g == cc:
                home_ids.append(mid)
            elif g:
                away_ids.append(mid)
    home = _xi_rates(con, pid, team, home_ids, with_ids)
    away = _xi_rates(con, pid, team, away_ids, with_ids)
    vol = con.execute(
        f"""
        SELECT
          COALESCE((SELECT SUM(b.balls) FROM batting_lines b
                    JOIN matches m ON m.match_id = b.match_id
                    WHERE b.person_id = ? AND b.innings_kind = 'regular'
                      AND m.start_date >= ?{extra}), 0),
          COALESCE((SELECT SUM(bl.legal_balls) FROM bowling_lines bl
                    JOIN matches m ON m.match_id = bl.match_id
                    WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
                      AND m.start_date >= ?{extra}), 0)
        """,
        [pid, first] + extra_params + [pid, first] + extra_params,
    ).fetchone()

    def _n(v, default=0):
        try:
            if v is None or v != v:
                return default
            return int(v)
        except (TypeError, ValueError):
            return default

    bat_pack, bowl_pack = pooled["bat"], pooled["bowl"]
    m_w, m_o = pooled["matches_with"], pooled["matches_wo"]
    bat_balls, bowl_balls = _n(vol[0] if vol else 0), _n(vol[1] if vol else 0)
    role = "bowl" if bowl_balls > bat_balls else "bat"
    ad, ed = bat_pack.get("avg_delta"), bowl_pack.get("econ_delta")
    schedule_mix = False
    hd = (home or {}).get("bat", {}).get("avg_delta") if home else None
    ad_away = (away or {}).get("bat", {}).get("avg_delta") if away else None
    home_ok = home and home["matches_with"] >= 6 and home["matches_wo"] >= 6
    away_ok = away and away["matches_with"] >= 6 and away["matches_wo"] >= 6
    if home_ok and away_ok and hd is not None and ad_away is not None:
        if (hd >= 2 and ad_away <= -1) or (hd <= -2 and ad_away >= 1) or (abs(hd - ad_away) >= 8):
            schedule_mix = True
            ad = None
            bat_pack = {**bat_pack, "avg_delta": None}
    parts = []
    if not schedule_mix:
        if ad is not None:
            if ad >= 2:
                parts.append("batters average more with them")
            elif ad <= -2:
                parts.append("batters average less with them")
        if ed is not None:
            if ed <= -0.2:
                parts.append("bowlers go at less with them")
            elif ed >= 0.2:
                parts.append("bowlers go at more with them")
    if m_w < 8 or m_o < 8:
        verdict = "Too few matches in this format to call it."
        lift = None
    elif schedule_mix:
        verdict = "Home and away don't agree. That's mostly where they played, not a teammate effect."
        lift = 0
    elif not parts:
        verdict = "Teammates look about the same with or without them."
        lift = 0
    else:
        verdict = parts[0][0].upper() + parts[0][1:] + ("." if len(parts) == 1 else "; " + parts[1] + ".")
        lift = (1 if ad is not None and ad >= 2 else -1 if ad is not None and ad <= -2 else 0) + (
            1 if ed is not None and ed <= -0.2 else -1 if ed is not None and ed >= 0.2 else 0
        )
    return {
        "ok": True,
        "team": team,
        "from": str(first)[:10] if first else None,
        "primary_role": role,
        "matches_with": m_w,
        "matches_wo": m_o,
        "bat": bat_pack,
        "bowl": bowl_pack,
        "home": home,
        "away": away,
        "schedule_mix": schedule_mix,
        "verdict": verdict,
        "lift": lift,
    }


def _shared_opponents(
    a_rows: list[dict], b_rows: list[dict], *, kind: str, tests: bool = False, limit: int = 20
) -> list[dict]:
    """Same opponent in the same competition — not two unrelated leaderboards."""
    def key(r):
        return (r.get("opp_slug") or r.get("opponent"), r.get("competition"))

    def with_avg(row: dict, line: str | None) -> str:
        base = line or ""
        if tests and row.get("avg") is not None:
            return f"{base} · {row['avg']} avg"
        return base

    am = {key(r): r for r in a_rows}
    bm = {key(r): r for r in b_rows}
    keys = [k for k in am if k in bm]
    keys.sort(key=lambda k: int(am[k].get("balls") or 0) + int(bm[k].get("balls") or 0), reverse=True)
    out = []
    for k in keys[:limit]:
        ar, br = am[k], bm[k]
        row = {
            "opponent": ar.get("opponent"),
            "opp_slug": ar.get("opp_slug"),
            "slug": ar.get("opp_slug"),
            "player": ar.get("opponent"),
            "competition": ar.get("competition"),
            "a_line": with_avg(ar, ar.get("line")),
            "b_line": with_avg(br, br.get("line")),
            "a_balls": ar.get("balls"),
            "b_balls": br.get("balls"),
            "a_sr": ar.get("sr"),
            "b_sr": br.get("sr"),
            "a_avg": ar.get("avg"),
            "b_avg": br.get("avg"),
            "a_econ": ar.get("econ"),
            "b_econ": br.get("econ"),
            "a_dismissals": ar.get("dismissals"),
            "b_dismissals": br.get("dismissals"),
        }
        if kind == "bat" and tests:
            if (
                ar.get("avg") is not None
                and br.get("avg") is not None
                and int(ar.get("dismissals") or 0) >= 3
                and int(br.get("dismissals") or 0) >= 3
            ):
                row["delta"] = round(float(ar["avg"]) - float(br["avg"]), 1)
            else:
                row["delta"] = None
            row["delta_label"] = "avg"
        elif kind == "bat" and ar.get("sr") is not None and br.get("sr") is not None:
            row["delta"] = round(float(ar["sr"]) - float(br["sr"]), 1)
            row["delta_label"] = "SR"
        elif kind == "bowl" and tests:
            if (
                ar.get("avg") is not None
                and br.get("avg") is not None
                and int(ar.get("dismissals") or 0) >= 3
                and int(br.get("dismissals") or 0) >= 3
            ):
                row["delta"] = round(float(ar["avg"]) - float(br["avg"]), 1)
            else:
                row["delta"] = None
            row["delta_label"] = "avg"
        elif kind == "bowl" and ar.get("econ") is not None and br.get("econ") is not None:
            row["delta"] = round(float(ar["econ"]) - float(br["econ"]), 2)
            row["delta_label"] = "econ"
        else:
            row["delta"] = None
            row["delta_label"] = ""
        out.append(row)
    return out


def _pairing(ra: str | None, rb: str | None) -> str:
    if ra == "bowl" and rb == "bowl":
        return "bowl_bowl"
    if ra == rb:
        return "bat_bat"
    return "mixed"


def _format_line(con, pid: str, comps: list[str] | None) -> dict[str, Any]:
    extra = ""
    params: list[Any] = [pid]
    if comps:
        ph = ",".join(["?"] * len(comps))
        extra = f" AND m.competition IN ({ph})"
        params = [pid] + list(comps)
    bat = con.execute(
        f"""
        SELECT COUNT(DISTINCT b.match_id), COUNT(*), SUM(b.runs), MAX(b.runs), SUM(b.balls),
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END),
               SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END),
               SUM(CASE WHEN b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END)
        FROM batting_lines b JOIN matches m ON m.match_id = b.match_id
        WHERE b.person_id = ? AND b.innings_kind = 'regular'{extra}
        """,
        params,
    ).fetchone()
    bowl = con.execute(
        f"""
        SELECT COUNT(DISTINCT bl.match_id), SUM(bl.wickets), SUM(bl.runs), SUM(bl.legal_balls)
        FROM bowling_lines bl JOIN matches m ON m.match_id = bl.match_id
        WHERE bl.person_id = ? AND bl.innings_kind = 'regular'{extra}
        """,
        params,
    ).fetchone()
    xi = con.execute(
        f"""
        SELECT COUNT(DISTINCT x.match_id) FROM xi x
        JOIN matches m ON m.match_id = x.match_id
        WHERE x.person_id = ?{extra}
        """,
        params,
    ).fetchone()

    def _n(v, default=0):
        try:
            if v is None or v != v:
                return default
            return int(v)
        except (TypeError, ValueError):
            return default

    def rate(num, den, places=1):
        if not den:
            return None
        try:
            return round(float(num) / den, places)
        except (TypeError, ValueError):
            return None

    matches = _n(xi[0] if xi else 0)
    inns = _n(bat[1] if bat else 0)
    runs = _n(bat[2] if bat else 0)
    hs = _n(bat[3] if bat else 0)
    balls = _n(bat[4] if bat else 0)
    outs = _n(bat[5] if bat else 0)
    hundreds = _n(bat[6] if bat else 0)
    fifties = _n(bat[7] if bat else 0)
    wk = _n(bowl[1] if bowl else 0)
    bruns = _n(bowl[2] if bowl else 0)
    bballs = _n(bowl[3] if bowl else 0)
    return {
        "matches": matches,
        "inns": inns or None,
        "runs": runs if inns else None,
        "hs": hs if inns else None,
        "avg": rate(runs, outs, 1),
        "sr": round(runs * 100 / balls, 1) if balls else None,
        "hundreds": hundreds if inns else None,
        "fifties": fifties if inns else None,
        "wickets": wk if wk else None,
        "bowl_avg": rate(bruns, wk, 1),
        "econ": round(bruns * 6 / bballs, 2) if bballs else None,
        "bowl_sr": rate(bballs, wk, 1),
        "balls_bat": balls,
        "balls_bowl": bballs,
        "primary_role": "bowl" if bballs > balls else "bat",
    }


def _classic_rows(sa: dict, sb: dict) -> list[dict]:
    specs = [
        ("matches", "Matches", 0, False),
        ("inns", "Inns", 0, False),
        ("runs", "Runs", 0, False),
        ("hs", "HS", 0, False),
        ("avg", "Avg", 1, False),
        ("sr", "Strike rate", 1, False),
        ("hundreds", "100s", 0, False),
        ("fifties", "50s", 0, False),
        ("wickets", "Wickets", 0, False),
        ("bowl_avg", "Bowl avg", 1, True),
        ("econ", "Econ", 2, True),
        ("bowl_sr", "Bowl SR", 1, True),
    ]
    show_bowl = (
        ((sa.get("wickets") or 0) >= 10 and (sb.get("wickets") or 0) >= 10)
        or sa.get("primary_role") == "bowl"
        or sb.get("primary_role") == "bowl"
    )
    rows = []
    for key, label, digits, lower in specs:
        if key in {"wickets", "bowl_avg", "econ", "bowl_sr"} and not show_bowl:
            continue
        av, bv = sa.get(key), sb.get(key)
        if av is None and bv is None:
            continue
        rows.append({"key": key, "label": label, "a": av, "b": bv, "digits": digits, "lower": lower})
    return rows


def _value_rows(va: dict, vb: dict) -> list[dict]:
    am = {m["key"]: m for m in va.get("metrics") or []}
    bm = {m["key"]: m for m in vb.get("metrics") or []}
    rows = []
    for key in (
        "war",
        "war_per_game",
        "raa_bat",
        "raa_bowl",
        "tsr",
        "te",
        "war_bat",
        "war_bowl",
        "twr_bat",
        "twr_bowl",
    ):
        a, b = am.get(key) or {}, bm.get(key) or {}
        av, bv = a.get("value"), b.get("value")
        delta = None
        if av is not None and bv is not None:
            delta = round(float(av) - float(bv), 3)
        if av is None and bv is None:
            continue
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
                "lower": key in {"te", "twr_bat"},
                "digits": 2 if key in {"tsr", "te", "twr_bat", "twr_bowl", "war", "war_bat", "war_bowl"} else (3 if key == "war_per_game" else 1),
            }
        )
    return rows


def _pair_h2h(con, a_id: str, b_id: str, comps: list[str] | None = None) -> dict[str, Any]:
    kinds = "'bowled','caught','caught and bowled','lbw','stumped','hit wicket'"
    extra = ""
    extra_params: list[Any] = []
    if comps:
        ph = ",".join(["?"] * len(comps))
        extra = f" AND m.competition IN ({ph})"
        extra_params = list(comps)

    def side(striker, bowler):
        row = con.execute(
            f"""
            SELECT
              SUM(CASE WHEN d.striker IS NOT NULL AND NOT d.is_wide THEN 1 ELSE 0 END) AS balls,
              SUM(CASE WHEN d.striker IS NOT NULL THEN d.runs_batter ELSE 0 END) AS runs,
              SUM(CASE WHEN d.player_out = d.striker AND d.wicket_kind IN ({kinds}) THEN 1 ELSE 0 END) AS dismissals,
              COUNT(DISTINCT d.match_id) AS matches
            FROM deliveries d
            JOIN matches m ON m.match_id = d.match_id
            WHERE d.striker = ? AND d.bowler = ? AND d.innings_kind = 'regular'{extra}
            """,
            [striker, bowler] + extra_params,
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
    season_a: str | None = None,
    season_b: str | None = None,
    gender: str = "male",
) -> dict[str, Any]:
    if not warehouse_ready():
        return {"ok": False, "error": "Warehouse not built"}
    con = connect()
    try:
        aliases = {
            "rcb": "Royal Challengers",
            "csk": "Chennai Super Kings",
            "mi": "Mumbai Indians",
            "kkr": "Kolkata Knight Riders",
            "srh": "Sunrisers Hyderabad",
            "rr": "Rajasthan Royals",
            "dc": "Delhi Capitals",
            "pbks": "Punjab Kings",
        }

        def query_name(name: str) -> str:
            return aliases.get(name.strip().lower(), name.strip())

        def available_seasons(name: str) -> list[str]:
            needle = query_name(name)
            return [
                r[0]
                for r in con.execute(
                """
                SELECT DISTINCT m.season FROM matches m
                WHERE m.competition = ? AND m.gender = ?
                  AND (m.team_home ILIKE ? OR m.team_away ILIKE ?)
                ORDER BY 1 DESC
                """,
                    [comp, gender, f"%{needle}%", f"%{needle}%"],
                ).fetchall()
            ]

        seasons_a = available_seasons(team_a)
        seasons_b = available_seasons(team_b)
        season_a = season_a or season or (seasons_a[0] if seasons_a else None)
        season_b = season_b or season or (seasons_b[0] if seasons_b else None)

        t20 = comp in T20_METRICS

        def pack(raw_name: str, side_season: str | None) -> dict:
            needle = query_name(raw_name)
            season_sql = "AND m.season = ?" if side_season else ""
            canon_row = con.execute(
                f"""
                SELECT team, COUNT(*) c FROM (
                  SELECT m.team_home AS team FROM matches m
                  WHERE m.competition = ? AND m.gender = ? AND m.team_home ILIKE ? {season_sql}
                  UNION ALL
                  SELECT m.team_away FROM matches m
                  WHERE m.competition = ? AND m.gender = ? AND m.team_away ILIKE ? {season_sql}
                )
                GROUP BY 1 ORDER BY c DESC LIMIT 1
                """,
                [comp, gender, f"%{needle}%"] + ([side_season] if side_season else [])
                + [comp, gender, f"%{needle}%"] + ([side_season] if side_season else []),
            ).fetchone()
            team = canon_row[0] if canon_row else needle
            recs = con.execute(
                f"""
                WITH team_m AS (
                  SELECT m.match_id, m.winner
                  FROM matches m
                  WHERE m.competition = ? AND m.gender = ?
                    AND (m.team_home = ? OR m.team_away = ?)
                    {season_sql}
                ),
                first_inn AS (
                  SELECT b.match_id, MIN(b.innings) AS inn
                  FROM batting_lines b
                  JOIN team_m tm ON tm.match_id = b.match_id
                  WHERE b.team = ? AND b.innings_kind = 'regular'
                  GROUP BY 1
                ),
                order_pos AS (
                  SELECT b.person_id, AVG(b.position) AS bat_pos
                  FROM batting_lines b
                  JOIN first_inn f ON f.match_id = b.match_id AND b.innings = f.inn
                  WHERE b.team = ? AND b.innings_kind = 'regular'
                  GROUP BY 1
                ),
                bat AS (
                  SELECT b.person_id,
                         COUNT(*) AS inns,
                         SUM(b.runs) AS runs,
                         SUM(b.balls) AS balls,
                         SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END) AS outs,
                         MAX(b.runs) AS hs,
                         SUM(CASE WHEN b.runs >= 100 THEN 1 ELSE 0 END) AS hundreds,
                         SUM(CASE WHEN b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) AS fifties
                  FROM batting_lines b
                  JOIN team_m tm ON tm.match_id = b.match_id
                  WHERE b.team = ? AND b.innings_kind = 'regular'
                  GROUP BY 1
                ),
                bowl AS (
                  SELECT bl.person_id,
                         SUM(bl.wickets) AS wickets,
                         SUM(bl.legal_balls) AS legal_balls,
                         SUM(bl.runs) AS bowl_runs
                  FROM bowling_lines bl
                  JOIN team_m tm ON tm.match_id = bl.match_id
                  WHERE bl.team = ? AND bl.innings_kind = 'regular'
                  GROUP BY 1
                ),
                apps AS (
                  SELECT s.person_id, s.matches
                  FROM (
                    SELECT x.person_id, COUNT(*) AS matches
                    FROM xi x
                    JOIN team_m tm ON tm.match_id = x.match_id
                    WHERE x.team = ?
                    GROUP BY 1
                  ) s
                  LEFT JOIN order_pos o ON o.person_id = s.person_id
                  ORDER BY s.matches DESC, o.bat_pos NULLS LAST, s.person_id
                  LIMIT 11
                )
                SELECT p.person_id, p.display_name, p.slug,
                       a.matches, o.bat_pos,
                       b.inns, b.runs, b.balls, b.outs, b.hs, b.hundreds, b.fifties,
                       bl.wickets, bl.legal_balls, bl.bowl_runs
                FROM apps a
                JOIN people p ON p.person_id = a.person_id
                LEFT JOIN order_pos o ON o.person_id = a.person_id
                LEFT JOIN bat b ON b.person_id = a.person_id
                LEFT JOIN bowl bl ON bl.person_id = a.person_id
                ORDER BY o.bat_pos NULLS LAST, a.matches DESC, p.display_name
                """,
                [comp, gender, team, team] + ([side_season] if side_season else []) + [team, team, team, team, team],
            ).fetchdf()
            recs2 = con.execute(
                f"""
                SELECT COUNT(*) matches,
                       SUM(CASE WHEN m.winner = ? THEN 1 ELSE 0 END) wins
                FROM matches m
                WHERE (m.team_home = ? OR m.team_away = ?)
                  AND m.competition = ? AND m.gender = ?
                  {season_sql}
                """,
                [team, team, team, comp, gender] + ([side_season] if side_season else []),
            ).fetchone()
            inn = con.execute(
                f"""
                SELECT
                  SUM(CASE WHEN i.batting_team = ? THEN i.runs ELSE 0 END),
                  SUM(CASE WHEN i.batting_team = ? THEN i.wickets ELSE 0 END),
                  SUM(CASE WHEN i.bowling_team = ? THEN i.runs ELSE 0 END),
                  SUM(CASE WHEN i.bowling_team = ? THEN i.wickets ELSE 0 END)
                FROM innings i
                JOIN matches m ON m.match_id = i.match_id
                WHERE i.innings_kind = 'regular'
                  AND (m.team_home = ? OR m.team_away = ?)
                  AND m.competition = ? AND m.gender = ?
                  {season_sql}
                """,
                [team, team, team, team, team, team, comp, gender] + ([side_season] if side_season else []),
            ).fetchone()
            n, w = int(recs2[0] or 0), int(recs2[1] or 0)

            def _n(v, default=0):
                if v is None:
                    return default
                try:
                    if v != v:
                        return default
                    return int(v)
                except (TypeError, ValueError):
                    return default

            def _avg(runs, den):
                return round(runs / den, 1) if den else None

            team_runs, team_wkts = _n(inn[0] if inn else 0), _n(inn[1] if inn else 0)
            conceded, taken = _n(inn[2] if inn else 0), _n(inn[3] if inn else 0)
            rows = recs.to_dict("records") if not recs.empty else []
            xi_runs = xi_outs = 0
            for i, r in enumerate(rows, start=1):
                r["rank"] = i
                runs = _n(r.get("runs"))
                outs = _n(r.get("outs"))
                inns = _n(r.get("inns"))
                wk = _n(r.get("wickets"))
                bowl_runs = _n(r.get("bowl_runs"))
                avg = _avg(runs, outs)
                bowl_avg = _avg(bowl_runs, wk)
                xi_runs += runs
                xi_outs += outs
                r["inns"] = inns or None
                r["runs"] = runs if inns else None
                r["hs"] = _n(r.get("hs")) if inns else None
                r["avg"] = avg
                r["hundreds"] = _n(r.get("hundreds")) if inns else None
                r["wickets"] = wk if wk else None
                r["bowl_avg"] = bowl_avg
                bits = []
                if inns:
                    bits.append(f"{runs} run{'s' if runs != 1 else ''}" + (f" · {avg} avg" if avg is not None else ""))
                if wk:
                    bits.append(f"{wk} wkt{'s' if wk != 1 else ''}")
                r["line"] = " · ".join(bits) if bits else f"{_n(r.get('matches'))} XI"
                r["fig"] = runs if inns else (wk if wk else None)
                r["primary_role"] = "bowl" if _n(r.get("legal_balls")) > _n(r.get("balls")) else "bat"
                r["war"] = None
                r["war_per_game"] = None
            war_sum = None
            if t20 and rows and side_season:
                ids = [r["person_id"] for r in rows]
                ph = ",".join(["?"] * len(ids))
                wars = con.execute(
                    f"""
                    SELECT person_id,
                           SUM(war) AS war,
                           SUM(balls_bat) AS balls_bat,
                           SUM(balls_bowl) AS balls_bowl
                    FROM metrics_t20
                    WHERE competition = ? AND gender = ? AND season = ?
                      AND person_id IN ({ph})
                    GROUP BY 1
                    """,
                    [comp, gender, side_season] + ids,
                ).fetchdf()
                wmap = {row["person_id"]: row for row in wars.to_dict("records")} if not wars.empty else {}
                for r in rows:
                    wm = wmap.get(r["person_id"]) or {}
                    games = _n(r.get("matches"))
                    war = wm.get("war")
                    try:
                        war = None if war is None or war != war else float(war)
                    except (TypeError, ValueError):
                        war = None
                    r["war"] = round(war, 2) if war is not None else None
                    r["war_per_game"] = round(war / games, 3) if war is not None and games else None
                    bb, bo = _n(wm.get("balls_bat")), _n(wm.get("balls_bowl"))
                    if bb or bo:
                        r["primary_role"] = "bowl" if bo > bb else "bat"
                    r["line"] = (
                        f"{'Bowl' if r['primary_role'] == 'bowl' else 'Bat'} · "
                        f"{_n(r.get('matches'))} of {n} XIs"
                    )
                    r["fig"] = r["war_per_game"]
                rows.sort(
                    key=lambda r: (
                        r.get("war_per_game") is not None,
                        r.get("war_per_game") if r.get("war_per_game") is not None else -1e9,
                    ),
                    reverse=True,
                )
                for i, r in enumerate(rows, start=1):
                    r["rank"] = i
                squad = con.execute(
                    f"""
                    SELECT SUM(war) FROM metrics_t20
                    WHERE competition = ? AND gender = ? AND season = ?
                      AND person_id IN (
                        SELECT DISTINCT x.person_id FROM xi x
                        JOIN matches m ON m.match_id = x.match_id
                        WHERE x.team = ? AND m.competition = ? AND m.gender = ?
                          AND m.season = ?
                      )
                    """,
                    [comp, gender, side_season, team, comp, gender, side_season],
                ).fetchone()
                tot = squad[0] if squad else None
                try:
                    tot = None if tot is None or tot != tot else float(tot)
                except (TypeError, ValueError):
                    tot = None
                war_sum = round(tot / n, 3) if tot is not None and n else None
            return {
                "team": team,
                "season": side_season,
                "matches": n,
                "wins": w,
                "win_pct": round(100 * w / n, 1) if n else None,
                "team_runs": team_runs,
                "team_wkts": team_wkts,
                "team_avg": _avg(team_runs, team_wkts),
                "bowl_avg": _avg(conceded, taken),
                "xi_runs": xi_runs,
                "xi_avg": _avg(xi_runs, xi_outs),
                "war_sum": war_sum,
                "players": _jsonable(rows),
            }

        a_side = pack(team_a, season_a)
        b_side = pack(team_b, season_b)
        edge = None
        if t20 and a_side.get("war_sum") is not None and b_side.get("war_sum") is not None:
            edge = round(a_side["war_sum"] - b_side["war_sum"], 3)
        return {
            "ok": True,
            "comp": comp,
            "season_a": season_a,
            "season_b": season_b,
            "seasons_a": seasons_a,
            "seasons_b": seasons_b,
            "t20": t20,
            "edge": edge,
            "a": a_side,
            "b": b_side,
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
                    "primary_role": role,
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
            av = float(az[f].mean() or 0)
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
                "war": round(float(az["war"].mean() or 0), 2),
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
        comps = parse_comps(comp)
        if comps:
            ph = ",".join(["?"] * len(comps))
            extra = f" AND m.competition IN ({ph})"
            extra_params: list[Any] = list(comps)
        else:
            extra = ""
            extra_params = []
        first = con.execute(
            f"""
            SELECT MIN(m.start_date) FROM matches m
            JOIN xi x ON x.match_id = m.match_id
            WHERE x.person_id = ? AND x.team ILIKE ?{extra}
            """,
            [pid, f"%{team}%"] + extra_params,
        ).fetchone()[0]
        with_params: list[Any] = [pid, f"%{team}%", first] + extra_params
        team_params: list[Any] = [f"%{team}%", f"%{team}%", first] + extra_params
        ctes = f"""
            WITH with_p AS (
              SELECT m.match_id FROM matches m
              JOIN xi x ON x.match_id = m.match_id
              WHERE x.person_id = ? AND x.team ILIKE ? AND m.start_date >= ?{extra}
            ),
            team_m AS (
              SELECT m.match_id FROM matches m
              WHERE (m.team_home ILIKE ? OR m.team_away ILIKE ?) AND m.start_date >= ?{extra}
            )
        """
        vol = con.execute(
            f"""
            {ctes}
            SELECT
              COALESCE((
                SELECT SUM(b.balls) FROM batting_lines b
                JOIN team_m tm ON tm.match_id = b.match_id
                WHERE b.person_id = ? AND b.innings_kind = 'regular'
              ), 0),
              COALESCE((
                SELECT SUM(bl.legal_balls) FROM bowling_lines bl
                JOIN team_m tm ON tm.match_id = bl.match_id
                WHERE bl.person_id = ? AND bl.innings_kind = 'regular'
              ), 0)
            """,
            with_params + team_params + [pid, pid],
        ).fetchone()
        bat_balls, bowl_balls = int(vol[0] or 0), int(vol[1] or 0)
        primary_role = "bowl" if bowl_balls > bat_balls else "bat"
        recs = con.execute(
            f"""
            {ctes}
            SELECT p.person_id, p.display_name, p.slug,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.wickets ELSE 0 END) AS wk_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.runs ELSE 0 END) AS runs_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.legal_balls ELSE 0 END) AS balls_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN bl.maidens ELSE 0 END) AS mdn_with,
                   SUM(CASE WHEN w.match_id IS NULL THEN bl.wickets ELSE 0 END) AS wk_wo,
                   SUM(CASE WHEN w.match_id IS NULL THEN bl.runs ELSE 0 END) AS runs_wo,
                   SUM(CASE WHEN w.match_id IS NULL THEN bl.legal_balls ELSE 0 END) AS balls_wo,
                   SUM(CASE WHEN w.match_id IS NULL THEN bl.maidens ELSE 0 END) AS mdn_wo,
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
            {ctes}
            SELECT p.person_id, p.display_name, p.slug,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN b.runs ELSE 0 END) AS runs_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL THEN b.balls ELSE 0 END) AS balls_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL AND NOT b.not_out THEN 1 ELSE 0 END) AS outs_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL AND b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) AS fifty_with,
                   SUM(CASE WHEN w.match_id IS NOT NULL AND b.runs >= 100 THEN 1 ELSE 0 END) AS hundred_with,
                   MAX(CASE WHEN w.match_id IS NOT NULL THEN b.runs END) AS hs_with,
                   COUNT(CASE WHEN w.match_id IS NOT NULL THEN 1 END) AS inns_with,
                   SUM(CASE WHEN w.match_id IS NULL THEN b.runs ELSE 0 END) AS runs_wo,
                   SUM(CASE WHEN w.match_id IS NULL THEN b.balls ELSE 0 END) AS balls_wo,
                   SUM(CASE WHEN w.match_id IS NULL AND NOT b.not_out THEN 1 ELSE 0 END) AS outs_wo,
                   SUM(CASE WHEN w.match_id IS NULL AND b.runs >= 50 AND b.runs < 100 THEN 1 ELSE 0 END) AS fifty_wo,
                   SUM(CASE WHEN w.match_id IS NULL AND b.runs >= 100 THEN 1 ELSE 0 END) AS hundred_wo,
                   MAX(CASE WHEN w.match_id IS NULL THEN b.runs END) AS hs_wo,
                   COUNT(CASE WHEN w.match_id IS NULL THEN 1 END) AS inns_wo,
                   COUNT(DISTINCT CASE WHEN w.match_id IS NOT NULL THEN b.match_id END) AS m_with,
                   COUNT(DISTINCT CASE WHEN w.match_id IS NULL THEN b.match_id END) AS m_wo
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

        t20 = not comps or any(c in T20_METRICS for c in comps)

        def _n(v, default=0):
            if v is None:
                return default
            try:
                if v != v:
                    return default
                return int(v)
            except (TypeError, ValueError):
                return default

        def _f(v):
            if v is None:
                return None
            try:
                if v != v:
                    return None
                return float(v)
            except (TypeError, ValueError):
                return None

        def rate(num, den, places=1):
            if not den:
                return None
            n = _f(num)
            return None if n is None else round(n / den, places)

        def delta(a, b, places=1):
            if a is None or b is None:
                return None
            return round(a - b, places)

        def adv_split(discipline: str) -> dict[str, dict]:
            if not t20:
                return {}
            df = con.execute(
                f"""
                {ctes}
                SELECT pf.person_id,
                       SUM(CASE WHEN w.match_id IS NOT NULL THEN pf.nrc ELSE 0 END) AS nrc_with,
                       SUM(CASE WHEN w.match_id IS NULL THEN pf.nrc ELSE 0 END) AS nrc_wo,
                       SUM(CASE WHEN w.match_id IS NOT NULL THEN pf.wpa ELSE 0 END) AS wpa_with,
                       SUM(CASE WHEN w.match_id IS NULL THEN pf.wpa ELSE 0 END) AS wpa_wo,
                       SUM(CASE WHEN w.match_id IS NOT NULL THEN pf.press ELSE 0 END) AS press_with,
                       SUM(CASE WHEN w.match_id IS NULL THEN pf.press ELSE 0 END) AS press_wo,
                       SUM(CASE WHEN w.match_id IS NOT NULL THEN pf.score * pf.balls ELSE 0 END) AS score_w_with,
                       SUM(CASE WHEN w.match_id IS NULL THEN pf.score * pf.balls ELSE 0 END) AS score_w_wo,
                       SUM(CASE WHEN w.match_id IS NOT NULL THEN pf.balls ELSE 0 END) AS pf_balls_with,
                       SUM(CASE WHEN w.match_id IS NULL THEN pf.balls ELSE 0 END) AS pf_balls_wo,
                       COUNT(DISTINCT CASE WHEN w.match_id IS NOT NULL THEN pf.match_id END) AS m_with,
                       COUNT(DISTINCT CASE WHEN w.match_id IS NULL THEN pf.match_id END) AS m_wo
                FROM performances_t20 pf
                JOIN team_m tm ON tm.match_id = pf.match_id
                JOIN xi x ON x.match_id = pf.match_id AND x.person_id = pf.person_id AND x.team ILIKE ?
                LEFT JOIN with_p w ON w.match_id = pf.match_id
                WHERE pf.person_id <> ? AND pf.discipline = ?
                GROUP BY 1
                """,
                with_params + team_params + [f"%{team}%", pid, discipline],
            ).fetchdf()
            if df is None or df.empty:
                return {}
            out = {}
            for row in df.to_dict("records"):
                mw, mo = _n(row.get("m_with")), _n(row.get("m_wo"))
                rae_w, rae_o = rate(row.get("nrc_with"), mw, 2), rate(row.get("nrc_wo"), mo, 2)
                wpa_w, wpa_o = rate(row.get("wpa_with"), mw, 3), rate(row.get("wpa_wo"), mo, 3)
                pr_w, pr_o = rate(row.get("press_with"), mw, 2), rate(row.get("press_wo"), mo, 2)
                sc_w = rate(row.get("score_w_with"), _n(row.get("pf_balls_with")), 1)
                sc_o = rate(row.get("score_w_wo"), _n(row.get("pf_balls_wo")), 1)
                out[row["person_id"]] = {
                    "rae_with": rae_w,
                    "rae_wo": rae_o,
                    "rae_delta": delta(rae_w, rae_o, 2),
                    "wpa_with": wpa_w,
                    "wpa_wo": wpa_o,
                    "wpa_delta": delta(wpa_w, wpa_o, 3),
                    "press_with": pr_w,
                    "press_wo": pr_o,
                    "press_delta": delta(pr_w, pr_o, 2),
                    "score_with": sc_w,
                    "score_wo": sc_o,
                    "score_delta": delta(sc_w, sc_o, 1),
                }
            return out

        bowl_adv = adv_split("bowl")
        bat_adv = adv_split("bat")

        def econ(runs, balls):
            return round(runs * 6 / balls, 2) if balls else None

        def sr_bat(runs, balls):
            return round(runs * 100 / balls, 1) if balls else None

        bowl_rows = []
        if recs is not None and not recs.empty:
            for r in recs.to_dict("records"):
                wk_w, wk_o = _n(r["wk_with"]), _n(r["wk_wo"])
                ru_w, ru_o = _n(r["runs_with"]), _n(r["runs_wo"])
                ba_w, ba_o = _n(r["balls_with"]), _n(r["balls_wo"])
                e_w, e_o = econ(ru_w, ba_w), econ(ru_o, ba_o)
                avg_w, avg_o = rate(ru_w, wk_w, 1), rate(ru_o, wk_o, 1)
                sr_w, sr_o = rate(ba_w, wk_w, 1), rate(ba_o, wk_o, 1)
                row = {
                    "player": r["display_name"],
                    "slug": r["slug"],
                    "m_with": _n(r["m_with"]),
                    "m_wo": _n(r["m_wo"]),
                    "wk_with": wk_w,
                    "wk_wo": wk_o,
                    "avg_with": avg_w,
                    "avg_wo": avg_o,
                    "avg_delta": delta(avg_w, avg_o, 1),
                    "econ_with": e_w,
                    "econ_wo": e_o,
                    "econ_delta": delta(e_w, e_o, 2),
                    "sr_with": sr_w,
                    "sr_wo": sr_o,
                    "sr_delta": delta(sr_w, sr_o, 1),
                    "mdn_with": _n(r["mdn_with"]),
                    "mdn_wo": _n(r["mdn_wo"]),
                }
                row.update(bowl_adv.get(r["person_id"]) or {})
                bowl_rows.append(row)
        bat_rows = []
        if bat is not None and not bat.empty:
            for r in bat.to_dict("records"):
                ru_w, ru_o = _n(r["runs_with"]), _n(r["runs_wo"])
                ba_w, ba_o = _n(r["balls_with"]), _n(r["balls_wo"])
                ou_w, ou_o = _n(r["outs_with"]), _n(r["outs_wo"])
                s_w, s_o = sr_bat(ru_w, ba_w), sr_bat(ru_o, ba_o)
                avg_w, avg_o = rate(ru_w, ou_w, 1), rate(ru_o, ou_o, 1)
                row = {
                    "player": r["display_name"],
                    "slug": r["slug"],
                    "m_with": _n(r["m_with"]),
                    "m_wo": _n(r["m_wo"]),
                    "inns_with": _n(r["inns_with"]),
                    "inns_wo": _n(r["inns_wo"]),
                    "no_with": max(_n(r["inns_with"]) - ou_w, 0),
                    "no_wo": max(_n(r["inns_wo"]) - ou_o, 0),
                    "runs_with": ru_w,
                    "runs_wo": ru_o,
                    "balls_with": ba_w,
                    "balls_wo": ba_o,
                    "hs_with": _n(r.get("hs_with")) if _n(r["inns_with"]) else None,
                    "hs_wo": _n(r.get("hs_wo")) if _n(r["inns_wo"]) else None,
                    "avg_with": avg_w,
                    "avg_wo": avg_o,
                    "avg_delta": delta(avg_w, avg_o, 1),
                    "sr_with": s_w,
                    "sr_wo": s_o,
                    "sr_delta": delta(s_w, s_o, 1),
                    "fifty_with": _n(r["fifty_with"]),
                    "fifty_wo": _n(r["fifty_wo"]),
                    "hundred_with": _n(r["hundred_with"]),
                    "hundred_wo": _n(r["hundred_wo"]),
                }
                row.update(bat_adv.get(r["person_id"]) or {})
                bat_rows.append(row)
        pool_label = (
            POOL_LABELS.get(comp or "", "")
            or LABELS.get(comp or "", "")
            or (comp.upper() if comp else "all formats")
        )
        return {
            "ok": True,
            "person": person,
            "team": team,
            "available_from": first,
            "comp": comp,
            "pool_label": pool_label,
            "t20": t20,
            "primary_role": primary_role,
            "bowling": _jsonable(bowl_rows),
            "batting": _jsonable(bat_rows),
            "caption": (
                f"Teammate lines for {team} in {pool_label} from "
                f"{str(first)[:10] if first else '—'} — with vs without {person['display_name']} in the XI."
            ),
        }
    finally:
        con.close()
