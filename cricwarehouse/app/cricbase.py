"""Import pre-2002 Test/ODI scorecards from the local cricbase SQLite file.

Cricsheet ball-by-ball starts in late 2001. Cricbase fills the gap from
ESPNCricinfo Statsguru: men's Tests from 1877 and ODIs from 1971, through 2001.
Those rows are innings scorecards — batting and bowling lines, not deliveries.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from cricwarehouse.app.parse import slugify
from cricwarehouse.paths import CRICBASE_DB, CRICBASE_STATS_CACHE, WAREHOUSE

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# Date cell immediately before the scorecard link in a Statsguru year table.
_YEAR_DATE = re.compile(
    r'<td nowrap="nowrap">([^<]+)</td>\s*'
    r'<td nowrap="nowrap"><a href="/ci/engine/match/(\d+)\.html"',
    re.I,
)


def cricbase_available(db_path: Path | None = None) -> bool:
    path = db_path or CRICBASE_DB
    return path.exists() and path.stat().st_size > 0


def parse_statsguru_date(text: str) -> date | None:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return None
    patterns = (
        r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$",
        r"^([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})$",
        r"^([A-Za-z]{3})\s+(\d{1,2})-\d{1,2},\s+(\d{4})$",
        r"^([A-Za-z]{3})\s+(\d{1,2})-[A-Za-z]{3}\s+\d{1,2},\s+(\d{4})$",
        r"^([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})\s*-",
        r"^(\d{1,2})-\d{1,2}\s+([A-Za-z]{3})\s+(\d{4})$",
    )
    for i, pat in enumerate(patterns):
        match = re.match(pat, text)
        if not match:
            continue
        a, b, c = match.groups()
        if i == 0 or i == 5:
            day, mon, year = a, b, c
        else:
            mon, day, year = a, b, c
        if mon not in MONTHS:
            return None
        return date(int(year), MONTHS[mon], int(day))
    return None


def dates_from_year_cache(cache_dir: Path | None = None) -> dict[str, str]:
    """Recover start dates that the original ingest left blank (year-spanning Tests)."""
    root = cache_dir or CRICBASE_STATS_CACHE
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for path in root.glob("*match_results*.html"):
        html = path.read_text(encoding="utf-8", errors="replace")
        for date_text, match_id in _YEAR_DATE.findall(html):
            parsed = parse_statsguru_date(date_text)
            if parsed and match_id not in out:
                out[match_id] = parsed.isoformat()
    return out


def _balls_per_over(start: str | None) -> int:
    year = int(start[:4]) if start and len(start) >= 4 and start[:4].isdigit() else 1900
    if year < 1889:
        return 4
    if year < 1900:
        return 5
    return 6


def _result_method(result: str | None) -> str:
    raw = (result or "").lower()
    if raw in {"no result", "n/r", "no_result"}:
        return "no_result"
    if raw in {"tie", "tied"}:
        return "tie"
    return "regular"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_historical(
    db_path: Path | None = None,
    *,
    existing_ids: set[str] | None = None,
    cache_dir: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Map cricinfo-source cricbase rows onto warehouse table dicts."""
    path = db_path or CRICBASE_DB
    if not path.exists():
        return {
            "matches": [],
            "people": [],
            "xi": [],
            "innings": [],
            "batting_lines": [],
            "bowling_lines": [],
        }

    recovered = dates_from_year_cache(cache_dir)
    skip = existing_ids or set()
    conn = _connect(path)
    try:
        players = {
            row["player_id"]: dict(row)
            for row in conn.execute("SELECT * FROM players")
        }
        matches = []
        kept_ids: set[str] = set()
        for row in conn.execute(
            """
            SELECT * FROM matches
            WHERE source = 'cricinfo' AND match_type IN ('Test', 'ODI')
            ORDER BY start_date, match_id
            """
        ):
            mid = str(row["match_id"])
            if mid in skip:
                continue
            start = row["start_date"] or recovered.get(mid)
            if start == "":
                start = recovered.get(mid)
            competition = "test" if row["match_type"] == "Test" else "odi"
            result = row["result"]
            winner = row["winner"]
            if (result or "").lower() in {"draw", "drawn"}:
                winner = None
            matches.append(
                {
                    "match_id": mid,
                    "start_date": start or None,
                    "gender": row["gender"] or "male",
                    "match_type": competition,
                    "competition": competition,
                    "venue": row["venue"] or None,
                    "city": row["city"] or None,
                    "event_name": row["event_name"] or None,
                    "event_stage": None,
                    "is_world_cup": False,
                    "team_home": row["team1"],
                    "team_away": row["team2"],
                    "toss_winner": row["toss_winner"] or None,
                    "toss_decision": row["toss_decision"] or None,
                    "winner": winner,
                    "win_by_runs": row["win_runs"],
                    "win_by_wickets": row["win_wickets"],
                    "win_by_innings": row["win_innings"],
                    "result": result,
                    "result_method": _result_method(result),
                    "scheduled_overs": None if competition == "test" else 50,
                    "revised_overs": None,
                    "revised_target": None,
                    "balls_per_over": int(row["balls_per_over"] or _balls_per_over(start)),
                    "season": (start or "")[:4] or None,
                    "eliminator_winner": None,
                    "data_version": None,
                    "revision": None,
                    "source_created": None,
                    "source": "cricinfo",
                }
            )
            kept_ids.add(mid)

        if not kept_ids:
            return {
                "matches": [],
                "people": [],
                "xi": [],
                "innings": [],
                "batting_lines": [],
                "bowling_lines": [],
            }

        marks = ",".join("?" * len(kept_ids))
        ids = list(kept_ids)
        match_teams = {m["match_id"]: (m["team_home"], m["team_away"]) for m in matches}

        xi: list[dict] = []
        used_people: set[str] = set()
        for row in conn.execute(
            f"SELECT match_id, team, player_id FROM match_players WHERE match_id IN ({marks})",
            ids,
        ):
            mid = str(row["match_id"])
            pid = row["player_id"]
            used_people.add(pid)
            xi.append(
                {
                    "match_id": mid,
                    "team": row["team"],
                    "person_id": pid,
                    "is_captain": False,
                    "is_keeper": False,
                }
            )

        bat_by_inn: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
        batting_lines: list[dict] = []
        for row in conn.execute(
            f"""
            SELECT match_id, innings_number, player_id, batting_position,
                   runs, balls, fours, sixes, dismissal_kind, bowler_id, not_out
            FROM batting_innings
            WHERE match_id IN ({marks})
            ORDER BY match_id, innings_number, batting_position, player_id
            """,
            ids,
        ):
            mid = str(row["match_id"])
            inn_no = int(row["innings_number"])
            pid = row["player_id"]
            used_people.add(pid)
            person = players.get(pid) or {}
            bat_by_inn[(mid, inn_no)].append(row)
            batting_lines.append(
                {
                    "match_id": mid,
                    "innings": inn_no,
                    "innings_kind": "regular",
                    "team": None,
                    "person_id": pid,
                    "player_name": person.get("unique_name") or person.get("name") or pid,
                    "position": row["batting_position"],
                    "runs": int(row["runs"] or 0),
                    "balls": int(row["balls"] or 0),
                    "fours": int(row["fours"] or 0),
                    "sixes": int(row["sixes"] or 0),
                    "dismissal_kind": row["dismissal_kind"],
                    "bowler_id": row["bowler_id"],
                    "fielder_id": None,
                    "not_out": bool(row["not_out"]),
                }
            )

        bowl_by_inn: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
        bowling_lines: list[dict] = []
        for row in conn.execute(
            f"""
            SELECT match_id, innings_number, player_id, balls, runs, wickets, maidens
            FROM bowling_innings
            WHERE match_id IN ({marks})
            """,
            ids,
        ):
            mid = str(row["match_id"])
            inn_no = int(row["innings_number"])
            pid = row["player_id"]
            used_people.add(pid)
            person = players.get(pid) or {}
            bowl_by_inn[(mid, inn_no)].append(row)
            bowling_lines.append(
                {
                    "match_id": mid,
                    "innings": inn_no,
                    "innings_kind": "regular",
                    "team": None,
                    "person_id": pid,
                    "player_name": person.get("unique_name") or person.get("name") or pid,
                    "legal_balls": int(row["balls"] or 0),
                    "runs": int(row["runs"] or 0),
                    "wickets": int(row["wickets"] or 0),
                    "extras": 0,
                    "dots": 0,
                    "maidens": int(row["maidens"] or 0),
                }
            )

        innings_rows: list[dict] = []
        inn_team: dict[tuple[str, int], str] = {}
        for row in conn.execute(
            f"""
            SELECT match_id, innings_number, batting_team, declared, forfeited
            FROM innings
            WHERE match_id IN ({marks})
            ORDER BY match_id, innings_number
            """,
            ids,
        ):
            mid = str(row["match_id"])
            inn_no = int(row["innings_number"])
            team_home, team_away = match_teams[mid]
            batting_team = row["batting_team"]
            if not batting_team or batting_team == "unknown":
                batting_team = team_home
            bowling_team = team_away if batting_team == team_home else team_home
            inn_team[(mid, inn_no)] = batting_team
            bats = bat_by_inn.get((mid, inn_no), [])
            bowls = bowl_by_inn.get((mid, inn_no), [])
            bat_runs = sum(int(r["runs"] or 0) for r in bats)
            bat_outs = sum(1 for r in bats if not r["not_out"])
            bowl_runs = sum(int(r["runs"] or 0) for r in bowls)
            bowl_wkts = sum(int(r["wickets"] or 0) for r in bowls)
            bowl_balls = sum(int(r["balls"] or 0) for r in bowls)
            runs = max(bat_runs, bowl_runs)
            wickets = max(bowl_wkts, bat_outs)
            extras = max(0, bowl_runs - bat_runs)
            innings_rows.append(
                {
                    "match_id": mid,
                    "innings": inn_no,
                    "innings_kind": "regular",
                    "batting_team": batting_team,
                    "bowling_team": bowling_team,
                    "runs": runs,
                    "wickets": wickets,
                    "legal_balls": bowl_balls,
                    "extras": extras,
                    "declared": bool(row["declared"]),
                    "all_out": wickets >= 10 and not row["declared"],
                    "target_runs": None,
                    "target_overs": None,
                    "pre_penalty_runs": 0,
                    "post_penalty_runs": 0,
                    "delivery_runs": bat_runs,
                    "super_over": False,
                    "forfeited": bool(row["forfeited"]),
                    "absent_hurt": False,
                    "miscounted_overs": 0,
                    "powerplay_balls": 0,
                    "schema_warnings": None,
                }
            )

        for line in batting_lines:
            line["team"] = inn_team.get((line["match_id"], line["innings"]))
        for line in bowling_lines:
            batting = inn_team.get((line["match_id"], line["innings"]))
            home, away = match_teams[line["match_id"]]
            line["team"] = away if batting == home else home

        people = []
        for pid in sorted(used_people):
            person = players.get(pid) or {}
            name = person.get("unique_name") or person.get("name") or pid
            people.append(
                {
                    "person_id": pid,
                    "display_name": person.get("name") or name,
                    "unique_name": name,
                    "slug": slugify(name),
                    "gender": "male",
                    "key_cricinfo": person.get("cricinfo_id") or None,
                    "key_cricketarchive": person.get("cricketarchive_id") or None,
                    "key_cricbuzz": person.get("cricbuzz_id") or None,
                    "key_bcci": None,
                    "name_variants": None,
                }
            )

        return {
            "matches": matches,
            "people": people,
            "xi": xi,
            "innings": innings_rows,
            "batting_lines": batting_lines,
            "bowling_lines": bowling_lines,
        }
    finally:
        conn.close()


def _existing_match_ids() -> set[str]:
    path = WAREHOUSE / "matches.parquet"
    if not path.exists():
        return set()
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=["match_id"])
    return {str(v) for v in table.column("match_id").to_pylist() if v}


def _append_parquet(name: str, new_rows: list[dict], *, unique: str | None = None) -> int:
    if not new_rows:
        return 0
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = WAREHOUSE / f"{name}.parquet"
    new = pa.Table.from_pylist(new_rows)
    if not path.exists():
        pq.write_table(new, path, compression="zstd")
        return len(new_rows)
    existing = pq.read_table(path)
    if unique and unique in existing.column_names:
        seen = {str(v) for v in existing.column(unique).to_pylist() if v}
        keep = [i for i, v in enumerate(new.column(unique).to_pylist()) if str(v) not in seen]
        if not keep:
            return 0
        new = new.take(keep)
    if name == "matches" and "source" not in existing.column_names:
        existing = existing.append_column(
            "source", pa.array(["cricsheet"] * existing.num_rows, type=pa.string())
        )
    for field in existing.schema:
        if field.name not in new.column_names:
            new = new.append_column(field.name, pa.nulls(new.num_rows, type=field.type))
    for field in new.schema:
        if field.name not in existing.column_names:
            existing = existing.append_column(
                field.name, pa.nulls(existing.num_rows, type=field.type)
            )
    new = new.select(existing.column_names)
    aligned = []
    for field in existing.schema:
        col = new.column(field.name)
        if col.type != field.type:
            col = col.cast(field.type, safe=False)
        aligned.append(col)
    new = pa.table(aligned, schema=existing.schema)
    combined = pa.concat_tables([existing, new])
    pq.write_table(combined, path, compression="zstd")
    return new.num_rows


def stamp_sources(*, db_path: Path | None = None) -> int:
    """Mark warehouse matches that came from cricbase so the UI can say so."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = WAREHOUSE / "matches.parquet"
    if not path.exists() or not cricbase_available(db_path):
        return 0
    conn = _connect(db_path or CRICBASE_DB)
    try:
        hist_ids = {
            str(row[0])
            for row in conn.execute(
                "SELECT match_id FROM matches WHERE source = 'cricinfo'"
            )
        }
    finally:
        conn.close()
    table = pq.read_table(path)
    ids = [str(v) if v is not None else "" for v in table.column("match_id").to_pylist()]
    if "source" in table.column_names:
        current = [v or "cricsheet" for v in table.column("source").to_pylist()]
    else:
        current = ["cricsheet"] * table.num_rows
    updated = ["cricinfo" if mid in hist_ids else src for mid, src in zip(ids, current)]
    if updated == current and "source" in table.column_names:
        return 0
    if "source" in table.column_names:
        idx = table.schema.get_field_index("source")
        table = table.set_column(idx, "source", pa.array(updated, type=pa.string()))
    else:
        table = table.append_column("source", pa.array(updated, type=pa.string()))
    pq.write_table(table, path, compression="zstd")
    return sum(1 for src in updated if src == "cricinfo")


def merge_historical(*, db_path: Path | None = None) -> dict[str, Any]:
    """Append cricinfo scorecards onto an already-built warehouse."""
    if not cricbase_available(db_path):
        return {"ok": False, "error": f"cricbase SQLite not found at {db_path or CRICBASE_DB}"}
    existing = _existing_match_ids()
    buckets = load_historical(db_path, existing_ids=existing)
    added = {
        "matches": _append_parquet("matches", buckets["matches"], unique="match_id"),
        "people": _append_parquet("people", buckets["people"], unique="person_id"),
        "xi": _append_parquet("xi", buckets["xi"]),
        "innings": _append_parquet("innings", buckets["innings"]),
        "batting_lines": _append_parquet("batting_lines", buckets["batting_lines"]),
        "bowling_lines": _append_parquet("bowling_lines", buckets["bowling_lines"]),
    }
    tagged = stamp_sources(db_path=db_path)
    meta_path = WAREHOUSE / "build.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["cricbase"] = {
        "db": str(db_path or CRICBASE_DB),
        "added": added,
        "listed": {k: len(v) for k, v in buckets.items()},
    }
    if added["matches"]:
        meta["matches"] = int(meta.get("matches") or 0) + added["matches"]
        comps = set(meta.get("competitions") or [])
        comps.update({m["competition"] for m in buckets["matches"]})
        meta["competitions"] = sorted(comps)
    meta["cricbase"]["tagged"] = tagged
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "added": added,
        "tagged": tagged,
        "listed": {k: len(v) for k, v in buckets.items()},
    }


def ingest_into_build(
    buckets: dict[str, list],
    *,
    db_path: Path | None = None,
) -> dict[str, int]:
    """Used by a full warehouse build: extend in-memory buckets before write."""
    existing = {m["match_id"] for m in buckets.get("matches", [])}
    hist = load_historical(db_path, existing_ids=existing)
    people_seen = {p["person_id"] for p in buckets.get("people", [])}
    buckets.setdefault("matches", []).extend(hist["matches"])
    buckets.setdefault("xi", []).extend(hist["xi"])
    buckets.setdefault("innings", []).extend(hist["innings"])
    buckets.setdefault("batting_lines", []).extend(hist["batting_lines"])
    buckets.setdefault("bowling_lines", []).extend(hist["bowling_lines"])
    for person in hist["people"]:
        if person["person_id"] not in people_seen:
            buckets.setdefault("people", []).append(person)
            people_seen.add(person["person_id"])
    return {k: len(v) for k, v in hist.items()}
