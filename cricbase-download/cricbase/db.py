from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unique_name TEXT NOT NULL,
    cricinfo_id TEXT,
    cricinfo_id_2 TEXT,
    cricinfo_id_3 TEXT,
    cricketarchive_id TEXT,
    cricbuzz_id TEXT,
    full_name TEXT,
    date_of_birth TEXT,
    batting_style TEXT,
    bowling_style TEXT,
    playing_role TEXT,
    major_teams TEXT,
    appeared_in_matches INTEGER NOT NULL DEFAULT 0,
    cricinfo_enriched_at TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    cricinfo_match_id INTEGER,
    match_type TEXT NOT NULL,
    gender TEXT NOT NULL,
    season TEXT,
    start_date TEXT,
    end_date TEXT,
    venue TEXT,
    city TEXT,
    event_name TEXT,
    match_number INTEGER,
    team1 TEXT NOT NULL,
    team2 TEXT NOT NULL,
    toss_winner TEXT,
    toss_decision TEXT,
    winner TEXT,
    result TEXT,
    win_runs INTEGER,
    win_wickets INTEGER,
    win_innings INTEGER,
    method TEXT,
    player_of_match TEXT,
    balls_per_over INTEGER NOT NULL DEFAULT 6,
    source TEXT NOT NULL DEFAULT 'cricsheet'
);

CREATE TABLE IF NOT EXISTS match_players (
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    team TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    batting_order INTEGER,
    PRIMARY KEY (match_id, team, player_id)
);

CREATE TABLE IF NOT EXISTS innings (
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    innings_number INTEGER NOT NULL,
    batting_team TEXT NOT NULL,
    declared INTEGER NOT NULL DEFAULT 0,
    forfeited INTEGER NOT NULL DEFAULT 0,
    super_over INTEGER NOT NULL DEFAULT 0,
    target_runs INTEGER,
    target_overs REAL,
    PRIMARY KEY (match_id, innings_number)
);

CREATE TABLE IF NOT EXISTS deliveries (
    match_id TEXT NOT NULL,
    innings_number INTEGER NOT NULL,
    delivery_seq INTEGER NOT NULL,
    over_number INTEGER NOT NULL,
    ball_in_over INTEGER NOT NULL,
    actual_delivery TEXT,
    batter_id TEXT NOT NULL,
    bowler_id TEXT NOT NULL,
    non_striker_id TEXT,
    runs_batter INTEGER NOT NULL DEFAULT 0,
    runs_extras INTEGER NOT NULL DEFAULT 0,
    runs_total INTEGER NOT NULL DEFAULT 0,
    extras_wides INTEGER NOT NULL DEFAULT 0,
    extras_noballs INTEGER NOT NULL DEFAULT 0,
    extras_byes INTEGER NOT NULL DEFAULT 0,
    extras_legbyes INTEGER NOT NULL DEFAULT 0,
    extras_penalty INTEGER NOT NULL DEFAULT 0,
    is_four INTEGER NOT NULL DEFAULT 0,
    is_six INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, innings_number, delivery_seq),
    FOREIGN KEY (match_id, innings_number) REFERENCES innings(match_id, innings_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS wickets (
    match_id TEXT NOT NULL,
    innings_number INTEGER NOT NULL,
    delivery_seq INTEGER NOT NULL,
    wicket_seq INTEGER NOT NULL DEFAULT 1,
    player_out_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    bowler_id TEXT,
    fielder_ids TEXT,
    PRIMARY KEY (match_id, innings_number, delivery_seq, wicket_seq),
    FOREIGN KEY (match_id, innings_number, delivery_seq)
        REFERENCES deliveries(match_id, innings_number, delivery_seq) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batting_innings (
    match_id TEXT NOT NULL,
    innings_number INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    batting_position INTEGER,
    runs INTEGER NOT NULL DEFAULT 0,
    balls INTEGER NOT NULL DEFAULT 0,
    fours INTEGER NOT NULL DEFAULT 0,
    sixes INTEGER NOT NULL DEFAULT 0,
    dismissal_kind TEXT,
    bowler_id TEXT,
    fielder_ids TEXT,
    not_out INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (match_id, innings_number, player_id),
    FOREIGN KEY (match_id, innings_number) REFERENCES innings(match_id, innings_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bowling_innings (
    match_id TEXT NOT NULL,
    innings_number INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    balls INTEGER NOT NULL DEFAULT 0,
    runs INTEGER NOT NULL DEFAULT 0,
    wickets INTEGER NOT NULL DEFAULT 0,
    maidens INTEGER NOT NULL DEFAULT 0,
    wides INTEGER NOT NULL DEFAULT 0,
    noballs INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, innings_number, player_id),
    FOREIGN KEY (match_id, innings_number) REFERENCES innings(match_id, innings_number) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_players_cricinfo ON players(cricinfo_id);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(unique_name);
CREATE INDEX IF NOT EXISTS idx_matches_type ON matches(match_type, gender);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(start_date);
CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(team1, team2);
CREATE INDEX IF NOT EXISTS idx_deliveries_batter ON deliveries(batter_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_bowler ON deliveries(bowler_id);
CREATE INDEX IF NOT EXISTS idx_wickets_kind ON wickets(kind);
CREATE INDEX IF NOT EXISTS idx_wickets_player ON wickets(player_out_id);
CREATE INDEX IF NOT EXISTS idx_batting_player ON batting_innings(player_id);
CREATE INDEX IF NOT EXISTS idx_bowling_player ON bowling_innings(player_id);

CREATE TABLE IF NOT EXISTS partnerships (
    match_id TEXT NOT NULL,
    innings_number INTEGER NOT NULL,
    wicket_number INTEGER NOT NULL,
    player_id_1 TEXT NOT NULL,
    player_id_2 TEXT NOT NULL,
    runs INTEGER NOT NULL DEFAULT 0,
    not_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, innings_number, wicket_number),
    FOREIGN KEY (match_id, innings_number) REFERENCES innings(match_id, innings_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_partnerships_match ON partnerships(match_id);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
