"""
Parse Cricsheet JSON match files into a delivery-level DataFrame.

Uses registry IDs to uniquely identify players across matches.
Tracks cumulative match state (team score, wickets) at each delivery.
"""

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import orjson
import pandas as pd


def _parse_single_match(filepath: str) -> Optional[dict]:
    """Parse one match JSON file. Returns dict with match_info + deliveries list."""
    try:
        with open(filepath, "rb") as f:
            data = orjson.loads(f.read())
    except Exception as e:
        print(f"  WARNING: Failed to parse {filepath}: {e}")
        return None

    match_id = Path(filepath).stem
    info = data.get("info", {})
    innings_list = data.get("innings", [])

    if not innings_list:
        return None

    dates = info.get("dates", [])
    date = dates[0] if dates else None
    venue = info.get("venue", "")
    teams = info.get("teams", [])
    registry = info.get("registry", {}).get("people", {})
    players_by_team = info.get("players", {})
    outcome = info.get("outcome", {})
    winner = outcome.get("winner")
    toss = info.get("toss", {})
    overs_limit = info.get("overs", 20)
    event = info.get("event", {})
    event_name = event.get("name", "")

    def _reg(name: str) -> str:
        """Look up registry ID for a player name, falling back to the name itself."""
        return registry.get(name, name)

    deliveries = []

    for inn_idx, innings in enumerate(innings_list):
        batting_team = innings.get("team", "")
        bowling_team_candidates = [t for t in teams if t != batting_team]
        bowling_team = bowling_team_candidates[0] if bowling_team_candidates else ""
        innings_num = inn_idx + 1
        target = innings.get("target", {})
        target_runs = target.get("runs")

        # Track state as we walk through the innings ball by ball
        batters_seen: list[str] = []
        cum_runs = 0
        cum_wickets = 0
        legal_ball_seq = 0  # sequential legal-delivery counter for the innings

        for over_data in innings.get("overs", []):
            over_num = over_data.get("over", 0)

            for ball_idx, dlv in enumerate(over_data.get("deliveries", [])):
                batter = dlv.get("batter", "")
                bowler = dlv.get("bowler", "")
                non_striker = dlv.get("non_striker", "")

                runs = dlv.get("runs", {})
                batter_runs = runs.get("batter", 0)
                extras_runs = runs.get("extras", 0)
                total_runs_dlv = runs.get("total", 0)

                # Extras breakdown
                extras = dlv.get("extras", {})
                wide_runs = extras.get("wides", 0)
                noball_runs = extras.get("noballs", 0)
                legbye_runs = extras.get("legbyes", 0)
                bye_runs = extras.get("byes", 0)
                penalty_runs = extras.get("penalty", 0)

                is_wide = wide_runs > 0
                is_noball = noball_runs > 0
                is_legal = not is_wide and not is_noball

                # Track batting order by first appearance at the crease
                for name in (batter, non_striker):
                    if name and name not in batters_seen:
                        batters_seen.append(name)
                bat_pos = (
                    (batters_seen.index(batter) + 1) if batter in batters_seen else 0
                )

                # Wickets (can technically have >1, e.g. run-out of non-striker + stumping)
                wickets = dlv.get("wickets", [])
                is_wicket = len(wickets) > 0
                wkt = wickets[0] if is_wicket else {}
                wicket_kind = wkt.get("kind")
                player_out = wkt.get("player_out")

                # Phase classification
                if over_num < 6:
                    phase = "powerplay"
                elif over_num < 16:
                    phase = "middle"
                else:
                    phase = "death"

                # Batter faces the ball unless it's a wide
                is_batter_ball = not is_wide

                # Dot ball definitions
                # - Batter dot: batter scored 0 off a ball they actually faced
                # - Bowler dot: zero total runs off the delivery (inherently excludes
                #   wides/noballs since those always add ≥1 extra)
                is_dot_batter = (batter_runs == 0) and is_batter_ball
                is_dot_bowler = total_runs_dlv == 0

                row = {
                    "match_id": match_id,
                    "date": date,
                    "venue": venue,
                    "event_name": event_name,
                    "innings_num": innings_num,
                    "batting_team": batting_team,
                    "bowling_team": bowling_team,
                    "over": over_num,
                    "ball_idx": ball_idx,
                    "legal_ball_seq": legal_ball_seq,
                    "batter": batter,
                    "batter_id": _reg(batter),
                    "bowler": bowler,
                    "bowler_id": _reg(bowler),
                    "non_striker": non_striker,
                    "non_striker_id": _reg(non_striker),
                    "batting_position": bat_pos,
                    "batter_runs": batter_runs,
                    "extras_runs": extras_runs,
                    "total_runs": total_runs_dlv,
                    "wide_runs": wide_runs,
                    "noball_runs": noball_runs,
                    "legbye_runs": legbye_runs,
                    "bye_runs": bye_runs,
                    "penalty_runs": penalty_runs,
                    "is_wide": is_wide,
                    "is_noball": is_noball,
                    "is_legal": is_legal,
                    "is_batter_ball": is_batter_ball,
                    "is_wicket": is_wicket,
                    "wicket_kind": wicket_kind,
                    "player_out": player_out,
                    "player_out_id": _reg(player_out) if player_out else None,
                    "is_four": batter_runs == 4,
                    "is_six": batter_runs == 6,
                    "is_dot_batter": is_dot_batter,
                    "is_dot_bowler": is_dot_bowler,
                    "phase": phase,
                    "team_score_before": cum_runs,
                    "team_wickets_before": cum_wickets,
                    "target_runs": target_runs,
                    "winner": winner,
                    "overs_limit": overs_limit,
                }

                deliveries.append(row)

                # Update cumulative state AFTER recording the delivery
                cum_runs += total_runs_dlv
                if is_wicket:
                    cum_wickets += len(wickets)
                if is_legal:
                    legal_ball_seq += 1

    match_info = {
        "match_id": match_id,
        "date": date,
        "venue": venue,
        "event_name": event_name,
        "teams": teams,
        "winner": winner,
        "toss_winner": toss.get("winner"),
        "toss_decision": toss.get("decision"),
        "players_by_team": players_by_team,
        "registry": registry,
        "overs_limit": overs_limit,
    }

    return {"match_info": match_info, "deliveries": deliveries}


def parse_all_matches(
    data_dir: str, max_workers: int | None = None
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Parse all JSON match files in data_dir using parallel workers.

    Returns
    -------
    deliveries_df : pd.DataFrame
        One row per delivery (~750K+ rows across all matches).
        Sorted by date → match → innings → over → ball.
    match_infos : list[dict]
        Per-match metadata for downstream use.
    """
    json_files = sorted(Path(data_dir).glob("*.json"))
    # README.txt will be skipped because it doesn't parse as valid JSON

    if max_workers is None:
        max_workers = min(os.cpu_count() or 4, 8)

    all_deliveries: list[dict] = []
    match_infos: list[dict] = []
    skipped = 0

    print(f"Parsing {len(json_files)} files with {max_workers} workers...")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_parse_single_match, str(f)): f for f in json_files}
        for i, future in enumerate(as_completed(futures)):
            try:
                result = future.result()
            except Exception as e:
                print(f"  WARNING: Worker exception: {e}")
                skipped += 1
                continue

            if result is not None and result["deliveries"]:
                all_deliveries.extend(result["deliveries"])
                match_infos.append(result["match_info"])
            else:
                skipped += 1

            if (i + 1) % 500 == 0:
                print(f"  Parsed {i + 1}/{len(json_files)} files...")

    print(
        f"  Done. {len(all_deliveries):,} deliveries from {len(match_infos):,} matches "
        f"({skipped} files skipped)."
    )

    if not all_deliveries:
        raise RuntimeError(
            "No deliveries parsed — check data_dir path and file contents."
        )

    # --------------- Build DataFrame ---------------
    df = pd.DataFrame(all_deliveries)

    # --------------- Optimise dtypes for memory ---------------
    int8_cols = [
        "innings_num",
        "over",
        "ball_idx",
        "batter_runs",
        "extras_runs",
        "total_runs",
        "batting_position",
        "wide_runs",
        "noball_runs",
        "legbye_runs",
        "bye_runs",
        "penalty_runs",
        "team_wickets_before",
    ]
    for c in int8_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(np.int8)

    int16_cols = ["team_score_before", "legal_ball_seq"]
    for c in int16_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(np.int16)

    # target_runs can be NaN (first innings has no target)
    if "target_runs" in df.columns:
        df["target_runs"] = pd.to_numeric(df["target_runs"], errors="coerce").astype(
            "Int16"
        )

    if "overs_limit" in df.columns:
        df["overs_limit"] = (
            pd.to_numeric(df["overs_limit"], errors="coerce").fillna(20).astype(np.int8)
        )

    bool_cols = [
        "is_wide",
        "is_noball",
        "is_legal",
        "is_batter_ball",
        "is_wicket",
        "is_four",
        "is_six",
        "is_dot_batter",
        "is_dot_bowler",
    ]
    for c in bool_cols:
        if c in df.columns:
            df[c] = df[c].astype(bool)

    # Date
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Categorical columns for memory savings on large string columns
    cat_cols = [
        "match_id",
        "venue",
        "event_name",
        "batting_team",
        "bowling_team",
        "batter",
        "batter_id",
        "bowler",
        "bowler_id",
        "non_striker",
        "non_striker_id",
        "phase",
        "wicket_kind",
        "player_out",
        "player_out_id",
        "winner",
    ]
    for c in cat_cols:
        if c in df.columns:
            df[c] = df[c].astype("category")

    # --------------- Sort ---------------
    df.sort_values(
        ["date", "match_id", "innings_num", "over", "ball_idx"],
        inplace=True,
    )
    df.reset_index(drop=True, inplace=True)

    return df, match_infos
