from __future__ import annotations

import sqlite3
from collections import defaultdict

from .ingest_cricsheet import ensure_players
from .ingest_players import mark_appeared_players
from .statsguru import (
    COMMON_DISMISSAL_CODES,
    fetch_html,
    innings_url,
    page_count,
    parse_batting_rows,
    parse_bowling_rows,
    parse_fow_rows,
    parse_year_matches,
    year_results_url,
)

TEST_YEARS = range(1877, 2002)
ODI_YEARS = range(1971, 2002)


def _span(years: range) -> tuple[str, str]:
    return (f"01 Jan {years.start}", f"31 Dec {years.stop - 1}")


def _player_maps(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
    by_cricinfo = {}
    by_name = {}
    for row in conn.execute("SELECT player_id, unique_name, name, cricinfo_id, cricinfo_id_2 FROM players"):
        if row["cricinfo_id"]:
            by_cricinfo[str(row["cricinfo_id"])] = row["player_id"]
        if row["cricinfo_id_2"]:
            by_cricinfo[str(row["cricinfo_id_2"])] = row["player_id"]
        by_name[row["unique_name"]] = row["player_id"]
        by_name[row["name"]] = row["player_id"]
    return by_cricinfo, by_name


def resolve_registry_player(
    conn: sqlite3.Connection,
    by_cricinfo: dict[str, str],
    by_name: dict[str, str],
    cricinfo_id: str | None,
    name: str | None,
) -> str | None:
    if cricinfo_id and cricinfo_id in by_cricinfo:
        return by_cricinfo[cricinfo_id]
    if name and name in by_name:
        return by_name[name]
    if not cricinfo_id and not name:
        return None
    player_id = f"cricinfo:{cricinfo_id}" if cricinfo_id else f"unknown:{name}"
    label = name or cricinfo_id
    ensure_players(conn, {player_id})
    if cricinfo_id:
        conn.execute(
            "UPDATE players SET name = COALESCE(name, ?), unique_name = COALESCE(unique_name, ?), cricinfo_id = ? WHERE player_id = ?",
            (label, label, cricinfo_id, player_id),
        )
        by_cricinfo[cricinfo_id] = player_id
    if name:
        conn.execute(
            "UPDATE players SET name = ?, unique_name = ? WHERE player_id = ? AND (name = player_id OR name IS NULL)",
            (name, name, player_id),
        )
        by_name[name] = player_id
    return player_id


def collect_year_matches(match_type: str, years: range, sleep_s: float = 0.12) -> list[dict]:
    matches = []
    for year in years:
        html = fetch_html(year_results_url(match_type, year), sleep_s=sleep_s)
        found = parse_year_matches(html, match_type)
        print(f"  {match_type} {year}: {len(found)} matches")
        matches.extend(found)
    return matches


def insert_matches(conn: sqlite3.Connection, matches: list[dict]) -> dict[str, int]:
    existing = {row[0] for row in conn.execute("SELECT match_id FROM matches")}
    inserted = skipped = 0
    for match in matches:
        if match["match_id"] in existing:
            skipped += 1
            continue
        conn.execute(
            """
            INSERT INTO matches (
                match_id, cricinfo_match_id, match_type, gender, start_date, end_date,
                venue, city, team1, team2, winner, result, win_runs, win_wickets,
                win_innings, source
            ) VALUES (?, ?, ?, 'male', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'cricinfo')
            """,
            (
                match["match_id"],
                int(match["match_id"]),
                match["match_type"],
                match["start_date"],
                match["start_date"],
                match["ground"],
                match["ground"],
                match["team1"],
                match["team2"],
                match["winner"],
                match["result"],
                match["win_runs"],
                match["win_wickets"],
                match["win_innings"],
            ),
        )
        existing.add(match["match_id"])
        inserted += 1
    conn.commit()
    return {"inserted": inserted, "already_present": skipped}


def match_index(matches: list[dict]) -> dict[tuple, str]:
    """Map a batting/bowling row onto a match.

    Prefer (date, ground, team, opposition). Fall back to (date, team,
    opposition) because Statsguru ground names are not always identical
    between the year list and the innings views.
    """
    exact = {}
    loose = {}
    for match in matches:
        if not match["start_date"]:
            continue
        for team, opp in ((match["team1"], match["team2"]), (match["team2"], match["team1"])):
            exact[(match["start_date"], match["ground"], team, opp)] = match["match_id"]
            loose[(match["start_date"], team, opp)] = match["match_id"]
    exact["_loose"] = loose  # type: ignore[assignment]
    return exact


def lookup_match(index: dict, row: dict) -> str | None:
    loose = index.get("_loose") or {}
    return index.get((row["start_date"], row["ground"], row["team"], row["opposition"])) or loose.get(
        (row["start_date"], row["team"], row["opposition"])
    )


def ensure_innings(conn: sqlite3.Connection, match_id: str, innings_number: int, batting_team: str | None) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO innings (match_id, innings_number, batting_team)
        VALUES (?, ?, ?)
        """,
        (match_id, innings_number, batting_team or "unknown"),
    )
    if batting_team:
        conn.execute(
            """
            UPDATE innings SET batting_team = ?
            WHERE match_id = ? AND innings_number = ? AND batting_team = 'unknown'
            """,
            (batting_team, match_id, innings_number),
        )


def iter_innings_pages(
    match_type: str,
    data_type: str,
    years: range,
    dismissal: int | None = None,
    sleep_s: float = 0.12,
):
    span_min, span_max = _span(years)
    first_url = innings_url(match_type, data_type, 1, span_min, span_max, dismissal)
    first = fetch_html(first_url, sleep_s=sleep_s)
    pages = page_count(first)
    yield 1, pages, first
    for page in range(2, pages + 1):
        url = innings_url(match_type, data_type, page, span_min, span_max, dismissal)
        yield page, pages, fetch_html(url, sleep_s=sleep_s)


def ingest_batting(
    conn: sqlite3.Connection,
    matches: list[dict],
    match_type: str,
    by_cricinfo: dict[str, str],
    by_name: dict[str, str],
    years: range,
    sleep_s: float = 0.12,
) -> dict[str, int]:
    index = match_index(matches)
    stats = defaultdict(int)
    for page, pages, html in iter_innings_pages(match_type, "batting", years, sleep_s=sleep_s):
        rows = parse_batting_rows(html)
        for row in rows:
            match_id = lookup_match(index, row)
            if not match_id or not row["innings_number"]:
                stats["unmatched"] += 1
                continue
            player_id = resolve_registry_player(conn, by_cricinfo, by_name, row["cricinfo_id"], row["name"])
            if not player_id:
                stats["unmatched"] += 1
                continue
            ensure_innings(conn, match_id, row["innings_number"], row["team"])
            conn.execute(
                """
                INSERT INTO batting_innings (
                    match_id, innings_number, player_id, runs, balls, fours, sixes,
                    dismissal_kind, not_out
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id, innings_number, player_id) DO UPDATE SET
                    runs = excluded.runs,
                    balls = excluded.balls,
                    fours = excluded.fours,
                    sixes = excluded.sixes,
                    not_out = excluded.not_out
                """,
                (
                    match_id,
                    row["innings_number"],
                    player_id,
                    row["runs"],
                    row["balls"] or 0,
                    row["fours"] or 0,
                    row["sixes"] or 0,
                    None if row["not_out"] else None,
                    row["not_out"],
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO match_players (match_id, team, player_id) VALUES (?, ?, ?)",
                (match_id, row["team"], player_id),
            )
            stats["rows"] += 1
        if page % 10 == 0 or page == pages:
            conn.commit()
            print(f"  {match_type} batting {page}/{pages} ({stats['rows']} rows, {stats['unmatched']} unmatched)")
    conn.commit()
    return dict(stats)


def ingest_bowling(
    conn: sqlite3.Connection,
    matches: list[dict],
    match_type: str,
    by_cricinfo: dict[str, str],
    by_name: dict[str, str],
    years: range,
    sleep_s: float = 0.12,
) -> dict[str, int]:
    index = match_index(matches)
    stats = defaultdict(int)
    for page, pages, html in iter_innings_pages(match_type, "bowling", years, sleep_s=sleep_s):
        rows = parse_bowling_rows(html)
        for row in rows:
            match_id = lookup_match(index, row)
            if not match_id or not row["innings_number"]:
                stats["unmatched"] += 1
                continue
            player_id = resolve_registry_player(conn, by_cricinfo, by_name, row["cricinfo_id"], row["name"])
            if not player_id:
                stats["unmatched"] += 1
                continue
            ensure_innings(conn, match_id, row["innings_number"], row["opposition"])
            conn.execute(
                """
                INSERT INTO bowling_innings (
                    match_id, innings_number, player_id, balls, runs, wickets, maidens
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id, innings_number, player_id) DO UPDATE SET
                    balls = excluded.balls,
                    runs = excluded.runs,
                    wickets = excluded.wickets,
                    maidens = excluded.maidens
                """,
                (
                    match_id,
                    row["innings_number"],
                    player_id,
                    row["balls"],
                    row["runs"],
                    row["wickets"],
                    row["maidens"],
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO match_players (match_id, team, player_id) VALUES (?, ?, ?)",
                (match_id, row["team"], player_id),
            )
            stats["rows"] += 1
        if page % 10 == 0 or page == pages:
            conn.commit()
            print(f"  {match_type} bowling {page}/{pages} ({stats['rows']} rows, {stats['unmatched']} unmatched)")
    conn.commit()
    return dict(stats)


def ingest_dismissals(
    conn: sqlite3.Connection,
    matches: list[dict],
    match_type: str,
    by_cricinfo: dict[str, str],
    by_name: dict[str, str],
    years: range,
    sleep_s: float = 0.12,
) -> dict[str, int]:
    index = match_index(matches)
    stats = defaultdict(int)
    for code, kind in COMMON_DISMISSAL_CODES.items():
        kind_count = 0
        for page, pages, html in iter_innings_pages(match_type, "batting", years, dismissal=code, sleep_s=sleep_s):
            for row in parse_batting_rows(html):
                match_id = lookup_match(index, row)
                if not match_id or not row["innings_number"]:
                    stats["unmatched"] += 1
                    continue
                player_id = resolve_registry_player(conn, by_cricinfo, by_name, row["cricinfo_id"], row["name"])
                if not player_id:
                    stats["unmatched"] += 1
                    continue
                cur = conn.execute(
                    """
                    UPDATE batting_innings
                    SET dismissal_kind = ?, not_out = 0
                    WHERE match_id = ? AND innings_number = ? AND player_id = ?
                    """,
                    (kind, match_id, row["innings_number"], player_id),
                )
                if cur.rowcount:
                    kind_count += 1
                    stats["updated"] += 1
                else:
                    stats["missed"] += 1
            if page == pages:
                print(f"  {match_type} {kind}: {kind_count} ({page} pages)")
        conn.commit()
    return dict(stats)


def ingest_fow(
    conn: sqlite3.Connection,
    matches: list[dict],
    match_type: str,
    by_cricinfo: dict[str, str],
    by_name: dict[str, str],
    years: range,
    sleep_s: float = 0.12,
) -> dict[str, int]:
    index = match_index(matches)
    stats = defaultdict(int)
    for page, pages, html in iter_innings_pages(match_type, "fow", years, sleep_s=sleep_s):
        for row in parse_fow_rows(html):
            match_id = lookup_match(index, row)
            if not match_id or not row["innings_number"] or not row["wicket_number"]:
                stats["unmatched"] += 1
                continue
            player_1 = resolve_registry_player(
                conn, by_cricinfo, by_name, row["cricinfo_id_1"], row["name_1"]
            )
            player_2 = resolve_registry_player(
                conn, by_cricinfo, by_name, row["cricinfo_id_2"], row["name_2"]
            )
            if not player_1 or not player_2:
                stats["unmatched"] += 1
                continue
            ensure_innings(conn, match_id, row["innings_number"], row["team"])
            conn.execute(
                """
                INSERT INTO partnerships (
                    match_id, innings_number, wicket_number,
                    player_id_1, player_id_2, runs, not_out
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id, innings_number, wicket_number) DO UPDATE SET
                    player_id_1 = excluded.player_id_1,
                    player_id_2 = excluded.player_id_2,
                    runs = excluded.runs,
                    not_out = excluded.not_out
                """,
                (
                    match_id,
                    row["innings_number"],
                    row["wicket_number"],
                    player_1,
                    player_2,
                    row["runs"],
                    row["not_out"],
                ),
            )
            stats["rows"] += 1
        if page % 10 == 0 or page == pages:
            conn.commit()
            print(f"  {match_type} fow {page}/{pages} ({stats['rows']} rows, {stats['unmatched']} unmatched)")
    conn.commit()
    return dict(stats)


def ingest_historical(
    conn: sqlite3.Connection,
    match_types: tuple[str, ...] = ("Test", "ODI"),
    test_years: range = TEST_YEARS,
    odi_years: range = ODI_YEARS,
    sleep_s: float = 0.12,
    only_fow: bool = False,
) -> dict:
    """Load Cricinfo scorecards for years Cricsheet does not already cover.

    Years are ingested one at a time so a 2002 hole does not re-download every
    later innings page, and a crash can resume from the next year.
    """
    from .db import init_db

    init_db(conn)
    by_cricinfo, by_name = _player_maps(conn)
    summary: dict = {}
    existing_cricsheet = {
        row[0]
        for row in conn.execute("SELECT match_id FROM matches WHERE source = 'cricsheet'")
    }
    for match_type in match_types:
        years = test_years if match_type == "Test" else odi_years
        listed = 0
        inserted = {"inserted": 0, "already_present": 0}
        batting: dict = {}
        bowling: dict = {}
        dismissals: dict = {}
        fow: dict = {}
        print(f"Collecting {match_type} match list {years.start}-{years.stop - 1}...")
        for year in years:
            year_range = range(year, year + 1)
            found = collect_year_matches(match_type, year_range, sleep_s=sleep_s)
            matches = [match for match in found if match["match_id"] not in existing_cricsheet]
            listed += len(matches)
            if not matches:
                print(f"  {match_type} {year}: nothing new")
                continue
            print(f"Inserting {len(matches)} {match_type} scorecards for {year}...")
            ins = insert_matches(conn, matches)
            inserted["inserted"] += ins.get("inserted", 0)
            inserted["already_present"] += ins.get("already_present", 0)
            if not only_fow:
                print(f"Ingesting {match_type} {year} batting...")
                batting[year] = ingest_batting(
                    conn, matches, match_type, by_cricinfo, by_name, year_range, sleep_s=sleep_s
                )
                print(f"Ingesting {match_type} {year} bowling...")
                bowling[year] = ingest_bowling(
                    conn, matches, match_type, by_cricinfo, by_name, year_range, sleep_s=sleep_s
                )
                print(f"Tagging {match_type} {year} dismissals...")
                dismissals[year] = ingest_dismissals(
                    conn, matches, match_type, by_cricinfo, by_name, year_range, sleep_s=sleep_s
                )
            print(f"Ingesting {match_type} {year} partnerships...")
            fow[year] = ingest_fow(
                conn, matches, match_type, by_cricinfo, by_name, year_range, sleep_s=sleep_s
            )
            by_cricinfo, by_name = _player_maps(conn)
        summary[f"{match_type}_listed"] = listed
        summary[f"{match_type}_matches"] = inserted
        summary[f"{match_type}_batting"] = batting
        summary[f"{match_type}_bowling"] = bowling
        summary[f"{match_type}_dismissals"] = dismissals
        summary[f"{match_type}_fow"] = fow
    deleted = conn.execute(
        """
        DELETE FROM batting_innings
        WHERE COALESCE(runs, 0) = 0 AND COALESCE(balls, 0) = 0
          AND dismissal_kind IS NULL AND not_out = 0
        """
    ).rowcount
    conn.commit()
    summary["dnb_rows_removed"] = deleted
    appeared = mark_appeared_players(conn)
    summary["appeared_players"] = appeared
    return summary
