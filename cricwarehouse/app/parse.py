from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cricwarehouse.competitions import classify_match, is_world_cup, normalize_stage

try:
    import orjson

    def _load_json(path: Path) -> dict:
        return orjson.loads(path.read_bytes())
except ImportError:  # pragma: no cover
    import json

    def _load_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _pid(registry: dict[str, str], name: str | None) -> str | None:
    if not name:
        return None
    return registry.get(name) or registry.get(name.strip())


def _extra_type(extras_obj: dict | None) -> str | None:
    if not extras_obj:
        return None
    for key in ("wides", "noballs", "byes", "legbyes", "penalty"):
        if extras_obj.get(key):
            return key
    return next(iter(extras_obj), None)


def _result_method(info: dict) -> str:
    outcome = info.get("outcome") or {}
    method = (outcome.get("method") or "").lower()
    if method in {"d/l", "dls", "duckworth/lewis"}:
        return "dls"
    if outcome.get("eliminator") or any(
        inn.get("super_over") for inn in []  # filled by caller
    ):
        return "super_over"
    result = (outcome.get("result") or "").lower()
    if result in {"no result", "no_result"}:
        return "no_result"
    if result == "tie" and not outcome.get("eliminator"):
        return "tie"
    return "regular"


def _overs_to_balls(overs: float | int | None, bpo: int) -> int | None:
    if overs is None:
        return None
    whole = int(overs)
    frac = round((float(overs) - whole) * 10)
    return whole * bpo + frac


def parse_one(args: tuple[str, str | None]) -> dict[str, Any] | None:
    path, code = args
    return parse_match_file(path, readme_code=code)


def parse_match_file(
    path: str | Path,
    readme_code: str | None = None,
) -> dict[str, Any] | None:
    path = Path(path)
    try:
        data = _load_json(path)
    except Exception:
        return None
    return parse_match(data, match_id=path.stem, readme_code=readme_code)


def parse_match(
    data: dict[str, Any],
    match_id: str | None = None,
    readme_code: str | None = None,
) -> dict[str, Any] | None:
    info = data.get("info") or {}
    competition = classify_match(info, readme_code)
    if competition is None:
        return None

    registry: dict[str, str] = (info.get("registry") or {}).get("people") or {}
    teams = info.get("teams") or []
    if len(teams) < 2:
        return None
    team_home, team_away = teams[0], teams[1]
    dates = info.get("dates") or []
    start_date = dates[0] if dates else None
    event = info.get("event") or {}
    outcome = info.get("outcome") or {}
    toss = info.get("toss") or {}
    innings_raw = data.get("innings") or []
    has_super = any(bool(inn.get("super_over")) for inn in innings_raw)
    method = (outcome.get("method") or "").lower()
    if method in {"d/l", "dls", "duckworth/lewis"}:
        result_method = "dls"
    elif has_super or outcome.get("eliminator"):
        result_method = "super_over"
    elif (outcome.get("result") or "").lower() in {"no result", "no_result"}:
        result_method = "no_result"
    elif (outcome.get("result") or "").lower() == "tie":
        result_method = "tie"
    else:
        result_method = "regular"

    by = outcome.get("by") or {}
    bpo = int(info.get("balls_per_over") or 6)
    scheduled_overs = info.get("overs")
    if scheduled_overs is None:
        scheduled_overs = 20 if competition != "test" else None

    revised_overs = None
    revised_target = None
    for inn in innings_raw:
        target = inn.get("target")
        if target and result_method == "dls":
            revised_overs = target.get("overs")
            revised_target = target.get("runs")

    gender = info.get("gender") or "male"
    season = str(info.get("season") or (start_date or "")[:4])
    event_name = event.get("name")
    match_row = {
        "match_id": match_id,
        "start_date": start_date,
        "gender": gender,
        "match_type": (info.get("match_type") or "").lower(),
        "competition": competition,
        "venue": info.get("venue"),
        "city": info.get("city"),
        "event_name": event_name,
        "event_stage": normalize_stage(event.get("stage")),
        "is_world_cup": bool(competition == "t20i" and is_world_cup(event_name)),
        "team_home": team_home,
        "team_away": team_away,
        "toss_winner": toss.get("winner"),
        "toss_decision": toss.get("decision"),
        "winner": outcome.get("winner"),
        "win_by_runs": by.get("runs"),
        "win_by_wickets": by.get("wickets"),
        "win_by_innings": by.get("innings"),
        "result": outcome.get("result"),
        "result_method": result_method,
        "scheduled_overs": scheduled_overs,
        "revised_overs": revised_overs,
        "revised_target": revised_target,
        "balls_per_over": bpo,
        "season": season,
        "eliminator_winner": outcome.get("eliminator"),
    }

    people: list[dict] = []
    for name, pid in registry.items():
        people.append(
            {
                "person_id": pid,
                "display_name": name,
                "unique_name": name,
                "slug": slugify(name),
                "gender": gender,
            }
        )

    xi: list[dict] = []
    players = info.get("players") or {}
    for team, names in players.items():
        for name in names:
            pid = _pid(registry, name)
            if not pid:
                continue
            xi.append(
                {
                    "match_id": match_id,
                    "team": team,
                    "person_id": pid,
                    "is_captain": False,
                    "is_keeper": False,
                }
            )

    deliveries: list[dict] = []
    innings_rows: list[dict] = []
    batting_lines: list[dict] = []
    bowling_lines: list[dict] = []
    partnerships: list[dict] = []
    fielding_acc: dict[str, dict[str, int]] = {}

    regular_no = 0
    super_no = 0
    for inn in innings_raw:
        is_super = bool(inn.get("super_over"))
        if is_super:
            super_no += 1
            innings_no = 100 + super_no
            innings_kind = "super_over"
        else:
            regular_no += 1
            innings_no = regular_no
            innings_kind = "regular"
        batting_team = inn.get("team")
        bowling_team = team_away if batting_team == team_home else team_home
        if batting_team == team_home:
            bowling_team = team_away
        else:
            bowling_team = next((t for t in teams if t != batting_team), team_away)

        target = inn.get("target") or {}
        bat_stats: dict[str, dict] = {}
        bowl_stats: dict[str, dict] = {}
        order: list[str] = []
        pair_a = pair_b = None
        pair_runs = pair_balls = 0
        pair_start = 0
        wicket_number = 0
        legal_index = 0
        innings_runs = 0
        innings_wkts = 0
        extras_total = 0
        declared = bool(inn.get("declared"))

        def flush_partnership(end_reason: str, legal_end: int) -> None:
            nonlocal pair_a, pair_b, pair_runs, pair_balls, pair_start
            if not pair_a or not pair_b:
                pair_runs = 0
                pair_balls = 0
                return
            a, b = pair_a, pair_b
            id1, id2 = (a, b) if a < b else (b, a)
            partnerships.append(
                {
                    "match_id": match_id,
                    "innings": innings_no,
                    "innings_kind": innings_kind,
                    "wicket_number": wicket_number,
                    "person_id_1": id1,
                    "person_id_2": id2,
                    "batter_end_1": a,
                    "batter_end_2": b,
                    "runs": pair_runs,
                    "balls": pair_balls,
                    "start_legal_index": pair_start,
                    "end_legal_index": legal_end,
                    "end_reason": end_reason,
                }
            )
            pair_runs = 0
            pair_balls = 0

        def ensure_batter(pid: str, name: str) -> dict:
            if pid not in bat_stats:
                bat_stats[pid] = {
                    "match_id": match_id,
                    "innings": innings_no,
                    "innings_kind": innings_kind,
                    "team": batting_team,
                    "person_id": pid,
                    "player_name": name,
                    "position": len(order) + 1,
                    "runs": 0,
                    "balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dismissal_kind": None,
                    "bowler_id": None,
                    "fielder_id": None,
                    "not_out": True,
                }
                order.append(pid)
            return bat_stats[pid]

        def ensure_bowler(pid: str, name: str) -> dict:
            if pid not in bowl_stats:
                bowl_stats[pid] = {
                    "match_id": match_id,
                    "innings": innings_no,
                    "innings_kind": innings_kind,
                    "team": bowling_team,
                    "person_id": pid,
                    "player_name": name,
                    "legal_balls": 0,
                    "runs": 0,
                    "wickets": 0,
                    "extras": 0,
                    "dots": 0,
                    "over_runs": 0,
                    "over_legal": 0,
                    "maidens": 0,
                    "current_over": None,
                }
            return bowl_stats[pid]

        for over in inn.get("overs") or []:
            over_no = int(over.get("over") or 0)
            for ball_i, d in enumerate(over.get("deliveries") or [], start=1):
                extras_obj = d.get("extras") or {}
                extra_type = _extra_type(extras_obj)
                is_wide = extra_type == "wides"
                is_noball = extra_type == "noballs"
                legal = not is_wide and not is_noball
                runs = d.get("runs") or {}
                runs_batter = int(runs.get("batter") or 0)
                runs_extras = int(runs.get("extras") or 0)
                runs_total = int(runs.get("total") or (runs_batter + runs_extras))
                wickets = d.get("wickets") or []
                wicket_kind = wickets[0]["kind"] if wickets else None
                player_out_name = wickets[0].get("player_out") if wickets else None
                fielders = []
                if wickets:
                    for f in wickets[0].get("fielders") or []:
                        fname = f.get("name") if isinstance(f, dict) else f
                        fid = _pid(registry, fname)
                        if fid:
                            fielders.append(fid)
                striker_name = d.get("batter")
                non_name = d.get("non_striker")
                bowler_name = d.get("bowler")
                striker = _pid(registry, striker_name)
                non_striker = _pid(registry, non_name)
                bowler = _pid(registry, bowler_name)

                if legal:
                    legal_index += 1
                innings_runs += runs_total
                extras_total += runs_extras

                if striker:
                    bstat = ensure_batter(striker, striker_name)
                    if not is_wide:
                        bstat["balls"] += 1
                    bstat["runs"] += runs_batter
                    if runs_batter == 4:
                        bstat["fours"] += 1
                    elif runs_batter == 6:
                        bstat["sixes"] += 1
                if non_striker:
                    ensure_batter(non_striker, non_name)

                if striker and non_striker:
                    current = {striker, non_striker}
                    if pair_a is None or pair_b is None:
                        pair_a, pair_b = striker, non_striker
                        pair_start = legal_index
                    elif current != {pair_a, pair_b}:
                        flush_partnership("retired_hurt", legal_index)
                        pair_a, pair_b = striker, non_striker
                        pair_start = legal_index
                    pair_runs += runs_total
                    if not is_wide:
                        pair_balls += 1

                if bowler:
                    bst = ensure_bowler(bowler, bowler_name)
                    if bst["current_over"] != over_no:
                        if bst["current_over"] is not None and bst["over_legal"] >= bpo and bst["over_runs"] == 0:
                            bst["maidens"] += 1
                        bst["current_over"] = over_no
                        bst["over_runs"] = 0
                        bst["over_legal"] = 0
                    charged = runs_batter + (
                        runs_extras if extra_type in {"wides", "noballs"} else 0
                    )
                    bst["runs"] += charged
                    bst["over_runs"] += charged
                    if extra_type in {"wides", "noballs"}:
                        bst["extras"] += runs_extras
                    if legal:
                        bst["legal_balls"] += 1
                        bst["over_legal"] = bst.get("over_legal", 0) + 1
                    if runs_total == 0:
                        bst["dots"] += 1

                for w in wickets:
                    kind = w.get("kind") or ""
                    out_name = w.get("player_out")
                    out_id = _pid(registry, out_name)
                    bowler_credited = kind in {
                        "bowled",
                        "caught",
                        "caught and bowled",
                        "lbw",
                        "stumped",
                        "hit wicket",
                    }
                    if bowler and bowler_credited:
                        bowl_stats[bowler]["wickets"] += 1
                    if out_id and out_id in bat_stats:
                        bat_stats[out_id]["dismissal_kind"] = kind
                        bat_stats[out_id]["not_out"] = False
                        bat_stats[out_id]["bowler_id"] = bowler if bowler_credited else None
                        fids = []
                        for f in w.get("fielders") or []:
                            fname = f.get("name") if isinstance(f, dict) else f
                            fid = _pid(registry, fname)
                            if fid:
                                fids.append(fid)
                        bat_stats[out_id]["fielder_id"] = fids[0] if fids else (
                            bowler if kind == "caught and bowled" else None
                        )
                        for fid in fids:
                            acc = fielding_acc.setdefault(
                                fid, {"catches": 0, "run_outs": 0, "stumpings": 0}
                            )
                            if kind in {"caught", "caught and bowled"}:
                                acc["catches"] += 1
                            elif kind == "run out":
                                acc["run_outs"] += 1
                            elif kind == "stumped":
                                acc["stumpings"] += 1
                        if kind == "caught and bowled" and bowler:
                            acc = fielding_acc.setdefault(
                                bowler, {"catches": 0, "run_outs": 0, "stumpings": 0}
                            )
                            acc["catches"] += 1
                    if kind not in {"retired hurt", "retired not out", "absent hurt", "absent ill"}:
                        innings_wkts += 1
                        wicket_number += 1
                        flush_partnership(kind, legal_index)
                        # surviving batter continues with incoming
                        survivor = None
                        if striker and non_striker:
                            survivor = non_striker if out_id == striker else striker
                        pair_a, pair_b = survivor, None
                        pair_start = legal_index

                deliveries.append(
                    {
                        "match_id": match_id,
                        "innings": innings_no,
                        "innings_kind": innings_kind,
                        "batting_team": batting_team,
                        "bowling_team": bowling_team,
                        "over": over_no,
                        "ball_in_over": ball_i,
                        "legal_ball_index": legal_index,
                        "striker": striker,
                        "non_striker": non_striker,
                        "bowler": bowler,
                        "runs_batter": runs_batter,
                        "runs_extras": runs_extras,
                        "runs_total": runs_total,
                        "extra_type": extra_type,
                        "is_wide": is_wide,
                        "is_noball": is_noball,
                        "is_legal": legal,
                        "wicket_kind": wicket_kind,
                        "player_out": _pid(registry, player_out_name),
                        "fielder_ids": "|".join(fielders) if fielders else None,
                    }
                )

        flush_partnership("end_of_innings", legal_index)
        for bst in bowl_stats.values():
            if bst.get("current_over") is not None and bst.get("over_legal", 0) >= bpo and bst.get("over_runs", 0) == 0:
                bst["maidens"] += 1

        allout = innings_wkts >= 10 and not declared
        innings_rows.append(
            {
                "match_id": match_id,
                "innings": innings_no,
                "innings_kind": innings_kind,
                "batting_team": batting_team,
                "bowling_team": bowling_team,
                "runs": innings_runs,
                "wickets": innings_wkts,
                "legal_balls": legal_index,
                "extras": extras_total,
                "declared": declared,
                "all_out": allout,
                "target_runs": target.get("runs"),
                "target_overs": target.get("overs"),
            }
        )
        batting_lines.extend(bat_stats[pid] for pid in order)
        for row in bowl_stats.values():
            row.pop("current_over", None)
            row.pop("over_runs", None)
            row.pop("over_legal", None)
            bowling_lines.append(row)

    fielding_lines = [
        {
            "match_id": match_id,
            "person_id": pid,
            "catches": v["catches"],
            "run_outs": v["run_outs"],
            "stumpings": v["stumpings"],
        }
        for pid, v in fielding_acc.items()
    ]

    return {
        "match": match_row,
        "people": people,
        "xi": xi,
        "innings": innings_rows,
        "batting_lines": batting_lines,
        "bowling_lines": bowling_lines,
        "deliveries": deliveries,
        "partnerships": partnerships,
        "fielding_lines": fielding_lines,
    }
