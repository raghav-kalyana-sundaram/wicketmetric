from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import DEFAULT_GENDER, MATCH_TYPES, RAW_DIR, TEST_NATIONS

UNKNOWN_PLAYER_PREFIX = "unknown:"


def is_test_nation_match(teams: list[str]) -> bool:
    return len(teams) == 2 and all(team in TEST_NATIONS for team in teams)


def resolve_player(registry: dict[str, str], name: str | None) -> str | None:
    if not name:
        return None
    return registry.get(name) or f"{UNKNOWN_PLAYER_PREFIX}{name}"


def ensure_players(conn, player_ids: set[str]) -> None:
    rows = []
    for pid in sorted(player_ids):
        if not pid:
            continue
        label = pid.removeprefix(UNKNOWN_PLAYER_PREFIX)
        rows.append((pid, label, label))
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR IGNORE INTO players (player_id, name, unique_name)
        VALUES (?, ?, ?)
        """,
        rows,
    )


def extra_counts(extras: dict[str, Any] | None) -> dict[str, int]:
    extras = extras or {}
    return {
        "wides": int(extras.get("wides") or 0),
        "noballs": int(extras.get("noballs") or 0),
        "byes": int(extras.get("byes") or 0),
        "legbyes": int(extras.get("legbyes") or 0),
        "penalty": int(extras.get("penalty") or 0),
    }


def is_boundary(runs: dict[str, Any], value: int) -> bool:
    if int(runs.get("batter") or 0) != value:
        return False
    return not bool(runs.get("non_boundary"))


def outcome_fields(outcome: dict[str, Any] | None) -> dict[str, Any]:
    outcome = outcome or {}
    by = outcome.get("by") or {}
    winner = outcome.get("winner")
    result = outcome.get("result")
    if winner and not result:
        result = "won"
    return {
        "winner": winner,
        "result": result,
        "win_runs": by.get("runs"),
        "win_wickets": by.get("wickets"),
        "win_innings": by.get("innings"),
        "method": outcome.get("method"),
    }


def derive_scorecards(deliveries: list[dict[str, Any]], wickets: list[dict[str, Any]]):
    batters: dict[str, dict[str, Any]] = {}
    bowlers: dict[str, dict[str, Any]] = {}
    position = 0
    legal_in_over = 0
    over_bowler = None
    over_runs = 0
    current_over = None

    def touch_batter(player_id: str) -> dict[str, Any]:
        nonlocal position
        if player_id not in batters:
            position += 1
            batters[player_id] = {
                "player_id": player_id,
                "batting_position": position,
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0,
                "dismissal_kind": None,
                "bowler_id": None,
                "fielder_ids": None,
                "not_out": 1,
            }
        return batters[player_id]

    def touch_bowler(player_id: str) -> dict[str, Any]:
        if player_id not in bowlers:
            bowlers[player_id] = {
                "player_id": player_id,
                "balls": 0,
                "runs": 0,
                "wickets": 0,
                "maidens": 0,
                "wides": 0,
                "noballs": 0,
            }
        return bowlers[player_id]

    def close_over():
        nonlocal legal_in_over, over_bowler, over_runs
        if over_bowler and legal_in_over >= 6 and over_runs == 0:
            bowlers[over_bowler]["maidens"] += 1
        legal_in_over = 0
        over_runs = 0

    for delivery in deliveries:
        over_number = delivery["over_number"]
        if current_over is None:
            current_over = over_number
            over_bowler = delivery["bowler_id"]
        elif over_number != current_over:
            close_over()
            current_over = over_number
            over_bowler = delivery["bowler_id"]

        batter = touch_batter(delivery["batter_id"])
        if delivery.get("non_striker_id"):
            touch_batter(delivery["non_striker_id"])
        bowler = touch_bowler(delivery["bowler_id"])

        wides = delivery["extras_wides"]
        noballs = delivery["extras_noballs"]
        legal = wides == 0 and noballs == 0
        if wides == 0:
            batter["balls"] += 1
        if legal:
            bowler["balls"] += 1
            legal_in_over += 1

        batter["runs"] += delivery["runs_batter"]
        batter["fours"] += delivery["is_four"]
        batter["sixes"] += delivery["is_six"]
        conceded = delivery["runs_batter"] + wides + noballs
        bowler["runs"] += conceded
        bowler["wides"] += wides
        bowler["noballs"] += noballs
        over_runs += conceded

    if deliveries:
        close_over()

    credited = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
    for wicket in wickets:
        batter = touch_batter(wicket["player_out_id"])
        batter["dismissal_kind"] = wicket["kind"]
        batter["bowler_id"] = wicket.get("bowler_id")
        batter["fielder_ids"] = wicket.get("fielder_ids")
        batter["not_out"] = 0 if wicket["kind"] not in {"retired hurt"} else 1
        if wicket["kind"] in credited and wicket.get("bowler_id"):
            touch_bowler(wicket["bowler_id"])["wickets"] += 1

    return list(batters.values()), list(bowlers.values())


def parse_match(path: Path, payload: dict[str, Any], gender: str) -> dict[str, Any] | None:
    info = payload.get("info") or {}
    if info.get("gender") != gender:
        return None
    match_type = info.get("match_type")
    if match_type not in MATCH_TYPES:
        return None
    teams = info.get("teams") or []
    if not is_test_nation_match(teams):
        return None

    registry = (info.get("registry") or {}).get("people") or {}
    dates = info.get("dates") or []
    event = info.get("event") or {}
    toss = info.get("toss") or {}
    outcome = outcome_fields(info.get("outcome"))
    pom_names = info.get("player_of_match") or []
    pom_ids = [resolve_player(registry, name) for name in pom_names]

    match_id = path.stem
    cricinfo_match_id = int(match_id) if match_id.isdigit() else None
    needed_players: set[str] = set(pid for pid in pom_ids if pid)

    match_players = []
    for team, names in (info.get("players") or {}).items():
        for order, name in enumerate(names, start=1):
            player_id = resolve_player(registry, name)
            if player_id:
                needed_players.add(player_id)
                match_players.append((match_id, team, player_id, order))

    innings_rows = []
    delivery_rows = []
    wicket_rows = []
    batting_rows = []
    bowling_rows = []

    for innings_number, innings in enumerate(payload.get("innings") or [], start=1):
        batting_team = innings.get("team")
        target = innings.get("target") or {}
        innings_rows.append(
            (
                match_id,
                innings_number,
                batting_team,
                1 if innings.get("declared") else 0,
                1 if innings.get("forfeited") else 0,
                1 if innings.get("super_over") else 0,
                target.get("runs"),
                target.get("overs"),
            )
        )
        if innings.get("forfeited"):
            continue

        parsed_deliveries = []
        parsed_wickets = []
        seq = 0
        for over in innings.get("overs") or []:
            over_number = int(over.get("over") or 0)
            for ball_in_over, delivery in enumerate(over.get("deliveries") or [], start=1):
                seq += 1
                extras = extra_counts(delivery.get("extras"))
                runs = delivery.get("runs") or {}
                batter_id = resolve_player(registry, delivery.get("batter"))
                bowler_id = resolve_player(registry, delivery.get("bowler"))
                non_striker_id = resolve_player(registry, delivery.get("non_striker"))
                for pid in (batter_id, bowler_id, non_striker_id):
                    if pid:
                        needed_players.add(pid)
                row = {
                    "match_id": match_id,
                    "innings_number": innings_number,
                    "delivery_seq": seq,
                    "over_number": over_number,
                    "ball_in_over": ball_in_over,
                    "actual_delivery": delivery.get("actual_delivery"),
                    "batter_id": batter_id,
                    "bowler_id": bowler_id,
                    "non_striker_id": non_striker_id,
                    "runs_batter": int(runs.get("batter") or 0),
                    "runs_extras": int(runs.get("extras") or 0),
                    "runs_total": int(runs.get("total") or 0),
                    "extras_wides": extras["wides"],
                    "extras_noballs": extras["noballs"],
                    "extras_byes": extras["byes"],
                    "extras_legbyes": extras["legbyes"],
                    "extras_penalty": extras["penalty"],
                    "is_four": 1 if is_boundary(runs, 4) else 0,
                    "is_six": 1 if is_boundary(runs, 6) else 0,
                }
                parsed_deliveries.append(row)
                delivery_rows.append(tuple(row.values()))

                for wicket_seq, wicket in enumerate(delivery.get("wickets") or [], start=1):
                    player_out_id = resolve_player(registry, wicket.get("player_out"))
                    if player_out_id:
                        needed_players.add(player_out_id)
                    fielder_ids = []
                    for fielder in wicket.get("fielders") or []:
                        fname = fielder.get("name") if isinstance(fielder, dict) else fielder
                        fid = resolve_player(registry, fname)
                        if fid:
                            needed_players.add(fid)
                            fielder_ids.append(fid)
                    kind = wicket.get("kind") or "unknown"
                    bowler_for_wicket = bowler_id if kind not in {"run out", "retired hurt", "retired out", "obstructing the field", "handled the ball", "timed out"} else None
                    parsed_wickets.append(
                        {
                            "player_out_id": player_out_id,
                            "kind": kind,
                            "bowler_id": bowler_for_wicket,
                            "fielder_ids": ",".join(fielder_ids) if fielder_ids else None,
                        }
                    )
                    wicket_rows.append(
                        (
                            match_id,
                            innings_number,
                            seq,
                            wicket_seq,
                            player_out_id,
                            kind,
                            bowler_for_wicket,
                            ",".join(fielder_ids) if fielder_ids else None,
                        )
                    )

        batting, bowling = derive_scorecards(parsed_deliveries, parsed_wickets)
        for row in batting:
            batting_rows.append(
                (
                    match_id,
                    innings_number,
                    row["player_id"],
                    row["batting_position"],
                    row["runs"],
                    row["balls"],
                    row["fours"],
                    row["sixes"],
                    row["dismissal_kind"],
                    row["bowler_id"],
                    row["fielder_ids"],
                    row["not_out"],
                )
            )
        for row in bowling:
            bowling_rows.append(
                (
                    match_id,
                    innings_number,
                    row["player_id"],
                    row["balls"],
                    row["runs"],
                    row["wickets"],
                    row["maidens"],
                    row["wides"],
                    row["noballs"],
                )
            )

    return {
        "needed_players": needed_players,
        "match": (
            match_id,
            cricinfo_match_id,
            match_type,
            info.get("gender"),
            info.get("season"),
            dates[0] if dates else None,
            dates[-1] if dates else None,
            info.get("venue"),
            info.get("city"),
            event.get("name"),
            event.get("match_number") or info.get("match_type_number"),
            teams[0],
            teams[1],
            toss.get("winner"),
            toss.get("decision"),
            outcome["winner"],
            outcome["result"],
            outcome["win_runs"],
            outcome["win_wickets"],
            outcome["win_innings"],
            outcome["method"],
            ",".join(pid for pid in pom_ids if pid) or None,
            int(info.get("balls_per_over") or 6),
            "cricsheet",
        ),
        "match_players": match_players,
        "innings": innings_rows,
        "deliveries": delivery_rows,
        "wickets": wicket_rows,
        "batting": batting_rows,
        "bowling": bowling_rows,
    }


def delete_match(conn, match_id: str) -> None:
    conn.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))


def insert_parsed(conn, parsed: dict[str, Any]) -> None:
    ensure_players(conn, parsed["needed_players"])
    delete_match(conn, parsed["match"][0])
    conn.execute(
        """
        INSERT INTO matches (
            match_id, cricinfo_match_id, match_type, gender, season, start_date,
            end_date, venue, city, event_name, match_number, team1, team2,
            toss_winner, toss_decision, winner, result, win_runs, win_wickets,
            win_innings, method, player_of_match, balls_per_over, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        parsed["match"],
    )
    conn.executemany(
        "INSERT INTO match_players (match_id, team, player_id, batting_order) VALUES (?, ?, ?, ?)",
        parsed["match_players"],
    )
    conn.executemany(
        """
        INSERT INTO innings (
            match_id, innings_number, batting_team, declared, forfeited,
            super_over, target_runs, target_overs
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        parsed["innings"],
    )
    conn.executemany(
        """
        INSERT INTO deliveries (
            match_id, innings_number, delivery_seq, over_number, ball_in_over,
            actual_delivery, batter_id, bowler_id, non_striker_id, runs_batter,
            runs_extras, runs_total, extras_wides, extras_noballs, extras_byes,
            extras_legbyes, extras_penalty, is_four, is_six
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        parsed["deliveries"],
    )
    conn.executemany(
        """
        INSERT INTO wickets (
            match_id, innings_number, delivery_seq, wicket_seq, player_out_id,
            kind, bowler_id, fielder_ids
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        parsed["wickets"],
    )
    conn.executemany(
        """
        INSERT INTO batting_innings (
            match_id, innings_number, player_id, batting_position, runs, balls,
            fours, sixes, dismissal_kind, bowler_id, fielder_ids, not_out
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        parsed["batting"],
    )
    conn.executemany(
        """
        INSERT INTO bowling_innings (
            match_id, innings_number, player_id, balls, runs, wickets, maidens,
            wides, noballs
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        parsed["bowling"],
    )


def iter_zip_matches(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        names = [name for name in zf.namelist() if name.endswith(".json")]
        for name in names:
            with zf.open(name) as handle:
                yield Path(name), json.load(handle)


def ingest_zips(
    conn,
    zip_paths: list[Path] | None = None,
    gender: str = DEFAULT_GENDER,
) -> dict[str, int]:
    paths = zip_paths or sorted(RAW_DIR.glob("*_json.zip"))
    stats = defaultdict(int)
    for zip_path in paths:
        for path, payload in iter_zip_matches(zip_path):
            stats["files"] += 1
            parsed = parse_match(path, payload, gender=gender)
            if parsed is None:
                stats["skipped"] += 1
                continue
            insert_parsed(conn, parsed)
            stats["ingested"] += 1
            stats[parsed["match"][2]] += 1
            if stats["ingested"] % 100 == 0:
                conn.commit()
                print(f"  ingested {stats['ingested']} matches from {zip_path.name}...", flush=True)
        conn.commit()
    return dict(stats)
