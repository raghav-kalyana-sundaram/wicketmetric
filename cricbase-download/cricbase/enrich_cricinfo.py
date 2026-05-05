from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

import requests

# Same athlete endpoint used by python-espncricinfo.Player.get_json().
# Instantiating Player() also scrapes a Cricinfo HTML layout that no longer exists.
ATHLETE_URL = "http://core.espnuk.org/v2/sports/cricket/athletes/{player_id}"
HEADERS = {"user-agent": "Mozilla/5.0 (cricbase; +https://github.com/outside-edge/python-espncricinfo)"}


def fetch_cricinfo_player(cricinfo_id: str) -> dict:
    response = requests.get(ATHLETE_URL.format(player_id=cricinfo_id), headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def _style(payload: dict, style_type: str) -> str | None:
    for item in payload.get("style") or []:
        if item.get("type") == style_type:
            return item.get("description")
    return None


def _playing_role(payload: dict) -> str | None:
    position = payload.get("position") or {}
    return position.get("name")


def enrich_players(
    conn: sqlite3.Connection,
    limit: int | None = None,
    sleep_s: float = 0.4,
    appeared_only: bool = True,
) -> dict[str, int]:
    """Fill biographical fields from the ESPNCricinfo athlete API."""
    where = "cricinfo_id IS NOT NULL AND cricinfo_enriched_at IS NULL"
    if appeared_only:
        where += " AND appeared_in_matches = 1"
    sql = f"SELECT player_id, unique_name, cricinfo_id FROM players WHERE {where} ORDER BY unique_name"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()

    stats = {"attempted": 0, "updated": 0, "failed": 0}
    for row in rows:
        stats["attempted"] += 1
        try:
            payload = fetch_cricinfo_player(row["cricinfo_id"])
            conn.execute(
                """
                UPDATE players
                SET full_name = ?,
                    date_of_birth = ?,
                    batting_style = ?,
                    bowling_style = ?,
                    playing_role = ?,
                    cricinfo_enriched_at = ?
                WHERE player_id = ?
                """,
                (
                    payload.get("fullName") or payload.get("name"),
                    payload.get("dateOfBirth"),
                    _style(payload, "batting"),
                    _style(payload, "bowling"),
                    _playing_role(payload),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    row["player_id"],
                ),
            )
            conn.commit()
            stats["updated"] += 1
            print(f"  enriched {row['unique_name']} ({row['cricinfo_id']})")
        except Exception as exc:
            stats["failed"] += 1
            print(f"  failed {row['unique_name']} ({row['cricinfo_id']}): {exc}")
        time.sleep(sleep_s)
    return stats
