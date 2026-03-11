from __future__ import annotations

from collections import defaultdict
from typing import Any

from cricwarehouse.competitions import LEAGUES


def _overs_float(legal_balls: int, bpo: int = 6) -> float:
    return legal_balls / bpo if bpo else 0.0


def _quota_overs(match: dict, innings: dict) -> float:
    """Overs charged for NRR. Bowled-out sides pay the full quota; DLS uses revised overs."""
    bpo = match.get("balls_per_over") or 6
    scheduled = match.get("scheduled_overs") or 20
    if match.get("result_method") == "dls":
        revised = match.get("revised_overs")
        if innings.get("innings") != 1 and revised is not None:
            return float(revised)
        target_ov = innings.get("target_overs")
        if target_ov is not None:
            return float(target_ov)
    if innings.get("all_out"):
        return float(scheduled)
    return _overs_float(int(innings.get("legal_balls") or 0), bpo)


def compute_standings(
    matches: list[dict],
    innings: list[dict],
) -> tuple[list[dict], list[dict]]:
    inn_by_match: dict[str, list[dict]] = defaultdict(list)
    for inn in innings:
        if inn.get("innings_kind") != "regular":
            continue
        inn_by_match[inn["match_id"]].append(inn)

    # season tables for league group matches (exclude knockouts)
    tables: dict[tuple[str, str, str], dict[str, dict]] = defaultdict(dict)
    playoffs: list[dict] = []

    def team_row(key: tuple[str, str, str], team: str) -> dict:
        rows = tables[key]
        if team not in rows:
            rows[team] = {
                "competition": key[0],
                "season": key[1],
                "gender": key[2],
                "team": team,
                "played": 0,
                "won": 0,
                "lost": 0,
                "tied": 0,
                "no_result": 0,
                "points": 0,
                "runs_for": 0,
                "overs_for": 0.0,
                "runs_against": 0,
                "overs_against": 0.0,
            }
        return rows[team]

    for m in matches:
        if m["competition"] not in LEAGUES and not m.get("is_world_cup"):
            continue
        stage = m.get("event_stage")
        is_knockout = stage in {"qualifier", "eliminator", "semi", "final", "third_place"}
        inns = inn_by_match.get(m["match_id"], [])
        if is_knockout:
            playoffs.append(
                {
                    "match_id": m["match_id"],
                    "competition": m["competition"],
                    "season": m["season"],
                    "gender": m["gender"],
                    "event_name": m.get("event_name"),
                    "event_stage": stage,
                    "team_home": m["team_home"],
                    "team_away": m["team_away"],
                    "winner": m.get("winner") or m.get("eliminator_winner"),
                    "result_method": m.get("result_method"),
                    "start_date": m.get("start_date"),
                }
            )
            continue
        if m["competition"] not in LEAGUES and not m.get("is_world_cup"):
            continue
        key = (m["competition"], m["season"], m["gender"])
        home, away = m["team_home"], m["team_away"]
        rh, ra = team_row(key, home), team_row(key, away)
        method = m.get("result_method")
        winner = m.get("winner")
        if method == "no_result":
            for row in (rh, ra):
                row["played"] += 1
                row["no_result"] += 1
                row["points"] += 1
            continue
        rh["played"] += 1
        ra["played"] += 1
        if method == "tie" and not m.get("eliminator_winner"):
            rh["tied"] += 1
            ra["tied"] += 1
            rh["points"] += 1
            ra["points"] += 1
        elif winner == home:
            rh["won"] += 1
            ra["lost"] += 1
            rh["points"] += 2
        elif winner == away:
            ra["won"] += 1
            rh["lost"] += 1
            ra["points"] += 2
        elif method == "super_over" and m.get("eliminator_winner"):
            w = m["eliminator_winner"]
            if w == home:
                rh["won"] += 1
                ra["lost"] += 1
                rh["points"] += 2
            elif w == away:
                ra["won"] += 1
                rh["lost"] += 1
                ra["points"] += 2
        else:
            rh["tied"] += 1
            ra["tied"] += 1
            rh["points"] += 1
            ra["points"] += 1

        # NRR from regular innings only
        for inn in inns:
            bat, bowl = inn["batting_team"], inn["bowling_team"]
            if bat not in tables[key] or bowl not in tables[key]:
                continue
            overs = _quota_overs(m, inn)
            runs = int(inn.get("runs") or 0)
            tables[key][bat]["runs_for"] += runs
            tables[key][bat]["overs_for"] += overs
            tables[key][bowl]["runs_against"] += runs
            tables[key][bowl]["overs_against"] += overs

    standings: list[dict] = []
    for key, rows in tables.items():
        computed = []
        for row in rows.values():
            of, oa = row["overs_for"], row["overs_against"]
            nrr = 0.0
            if of > 0 and oa > 0:
                nrr = (row["runs_for"] / of) - (row["runs_against"] / oa)
            row["nrr"] = round(nrr, 3)
            computed.append(row)
        computed.sort(key=lambda r: (-r["points"], -r["nrr"], -r["won"]))
        for i, row in enumerate(computed, start=1):
            out = {k: v for k, v in row.items() if k not in {"runs_for", "overs_for", "runs_against", "overs_against"}}
            out["position"] = i
            standings.append(out)
    return standings, playoffs
