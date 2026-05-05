from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .config import PEOPLE_CSV


def load_people(conn: sqlite3.Connection, csv_path: Path | None = None) -> int:
    path = csv_path or PEOPLE_CSV
    inserted = 0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            player_id = (row.get("identifier") or "").strip()
            if not player_id:
                continue
            rows.append(
                (
                    player_id,
                    row.get("name") or player_id,
                    row.get("unique_name") or row.get("name") or player_id,
                    (row.get("key_cricinfo") or "").strip() or None,
                    (row.get("key_cricinfo_2") or "").strip() or None,
                    (row.get("key_cricinfo_3") or "").strip() or None,
                    (row.get("key_cricketarchive") or "").strip() or None,
                    (row.get("key_cricbuzz") or "").strip() or None,
                )
            )
        conn.executemany(
            """
            INSERT INTO players (
                player_id, name, unique_name, cricinfo_id, cricinfo_id_2,
                cricinfo_id_3, cricketarchive_id, cricbuzz_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                name = excluded.name,
                unique_name = excluded.unique_name,
                cricinfo_id = excluded.cricinfo_id,
                cricinfo_id_2 = excluded.cricinfo_id_2,
                cricinfo_id_3 = excluded.cricinfo_id_3,
                cricketarchive_id = excluded.cricketarchive_id,
                cricbuzz_id = excluded.cricbuzz_id
            """,
            rows,
        )
        inserted = len(rows)
    conn.commit()
    return inserted


def mark_appeared_players(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        """
        UPDATE players
        SET appeared_in_matches = 1
        WHERE player_id IN (SELECT DISTINCT player_id FROM match_players)
        """
    )
    conn.commit()
    return cur.rowcount
