#!/usr/bin/env python3
"""
Build cricket.duckdb from pipeline Parquet output.

Runs OUTSIDE the API process (in CI or locally after the pipeline).
Produces an atomic .duckdb file ready to be copied into the API's data dir.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import duckdb

VALID_FORMATS = ("mens_t20i", "womens_t20i", "mens_ipl", "womens_ipl")

LEGACY_ALIASES = {
    "womens_t20i": "womens_t20",
}

TABLES = [
    ("bat_careers",                 "batting_careers_full.parquet"),
    ("bowl_careers",                "bowling_careers_full.parquet"),
    ("bat_careers_ctx_entry_early", "batting_careers_ctx_entry_early.parquet"),
    ("bat_careers_ctx_entry_death", "batting_careers_ctx_entry_death.parquet"),
    ("bat_innings",                 "batting_innings_detail.parquet"),
    ("bowl_spells",                 "bowling_spells_detail.parquet"),
    ("bat_form",                    "batting_form_series.parquet"),
    ("bowl_form",                   "bowling_form_series.parquet"),
    ("bat_sim",                     "batting_similarities.parquet"),
    ("bowl_sim",                    "bowling_similarities.parquet"),
    ("matchups",                    "matchups.parquet"),
    ("matchups_phase",              "matchups_by_phase.parquet"),
    ("venue",                       "venue_baselines.parquet"),
]

BAT_CAREER_DEFAULTS = [
    ("role",               "VARCHAR",  "'bat'"),
    ("is_provisional_bat", "BOOLEAN",  "TRUE"),
    ("overall_grade",      "VARCHAR",  "'D'"),
    ("archetype",          "VARCHAR",  "'Unknown'"),
    ("country",            "VARCHAR",  "'Unknown'"),
    ("position_group",     "VARCHAR",  "'unknown'"),
]

BOWL_CAREER_DEFAULTS = [
    ("role",                "VARCHAR",  "'bowl'"),
    ("is_provisional_bowl", "BOOLEAN",  "TRUE"),
    ("overall_grade",       "VARCHAR",  "'D'"),
    ("archetype",           "VARCHAR",  "'Unknown'"),
    ("country",             "VARCHAR",  "'Unknown'"),
    ("phase_group",         "VARCHAR",  "'unknown'"),
    ("bowling_style",       "VARCHAR",  "''"),
    ("bowling_kind",        "VARCHAR",  "'unknown'"),
    ("espn_player_id",      "VARCHAR",  "''"),
    ("bowling_style_verified", "BOOLEAN", "FALSE"),
]


def _safe_exec(con, sql, label=""):
    """Execute SQL, printing a warning instead of crashing on failure."""
    try:
        con.execute(sql)
    except Exception as e:
        tag = f" [{label}]" if label else ""
        print(f"  WARN{tag}: {e}")


def _column_exists(con, schema, table, column):
    rows = con.execute(
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{table}' AND column_name = '{column}'"
    ).fetchall()
    return len(rows) > 0


def _get_score_columns(con, schema, table):
    rows = con.execute(f"PRAGMA table_info('{schema}.{table}')").fetchall()
    return [r[1] for r in rows if r[1].startswith("score_")]


def _resolve_format_dir(parquet_root, fmt):
    primary = Path(parquet_root) / fmt
    if primary.is_dir():
        return primary
    alias = LEGACY_ALIASES.get(fmt)
    if alias:
        alt = Path(parquet_root) / alias
        if alt.is_dir():
            return alt
    return None


# ── Raw table loading ────────────────────────────────────────────────

def load_raw_tables(con, parquet_root):
    loaded = {}
    for fmt in VALID_FORMATS:
        fmt_dir = _resolve_format_dir(parquet_root, fmt)
        if fmt_dir is None:
            print(f"⊘ {fmt}: directory not found, skipping")
            continue

        print(f"▸ {fmt}")
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {fmt}")
        loaded[fmt] = []

        for table_name, parquet_file in TABLES:
            pq_path = fmt_dir / parquet_file
            if not pq_path.exists():
                print(f"    skip {table_name} (file missing)")
                continue
            sql = f"CREATE TABLE {fmt}.{table_name} AS SELECT * FROM read_parquet('{pq_path}')"
            _safe_exec(con, sql, f"{fmt}.{table_name}")
            loaded[fmt].append(table_name)
            print(f"    + {table_name}")

    return loaded


# ── Post-load transforms ─────────────────────────────────────────────

def _normalize_id_col(con, fqn, col):
    _safe_exec(con, f"ALTER TABLE {fqn} ALTER COLUMN {col} TYPE VARCHAR", f"cast {fqn}.{col}")


def _add_defaults(con, fqn, defaults):
    for col, dtype, default in defaults:
        _safe_exec(
            con,
            f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS {col} {dtype} DEFAULT {default}",
            f"default {fqn}.{col}",
        )


def _coerce_scores(con, schema, table):
    fqn = f"{schema}.{table}"
    score_cols = _get_score_columns(con, schema, table)
    for sc in score_cols:
        _safe_exec(
            con,
            f"UPDATE {fqn} SET {sc} = COALESCE(TRY_CAST({sc} AS DOUBLE), 0.0)",
            f"coerce {fqn}.{sc}",
        )


def _attach_last_match_date_bat(con, fmt):
    fqn = f"{fmt}.bat_careers"
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS last_match_date TIMESTAMP", "add last_match_date")
    _safe_exec(con, f"""
        UPDATE {fqn} SET last_match_date = sub.md FROM (
            SELECT CAST(batter_id AS VARCHAR) AS bid,
                   MAX(TRY_CAST(date AS TIMESTAMP)) AS md
            FROM {fmt}.bat_innings GROUP BY bid
        ) sub WHERE CAST(batter_id AS VARCHAR) = sub.bid
    """, f"{fqn}.last_match_date")


def _attach_last_match_date_bowl(con, fmt):
    fqn = f"{fmt}.bowl_careers"
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS last_match_date TIMESTAMP", "add last_match_date")
    _safe_exec(con, f"""
        UPDATE {fqn} SET last_match_date = sub.md FROM (
            SELECT CAST(bowler_id AS VARCHAR) AS bid,
                   MAX(TRY_CAST(date AS TIMESTAMP)) AS md
            FROM {fmt}.bowl_spells GROUP BY bid
        ) sub WHERE CAST(bowler_id AS VARCHAR) = sub.bid
    """, f"{fqn}.last_match_date")


def _attach_recent_team_bat(con, fmt):
    fqn = f"{fmt}.bat_careers"
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS recent_team VARCHAR", "add recent_team")
    _safe_exec(con, f"""
        UPDATE {fqn} SET recent_team = sub.team FROM (
            SELECT batter_id AS bid, batting_team AS team FROM (
                SELECT CAST(batter_id AS VARCHAR) AS batter_id,
                       CASE WHEN batting_team IS NULL
                                 OR LOWER(CAST(batting_team AS VARCHAR)) IN ('nan','none','<na>','nat','')
                            THEN NULL
                            ELSE CAST(batting_team AS VARCHAR) END AS batting_team,
                       ROW_NUMBER() OVER (
                           PARTITION BY CAST(batter_id AS VARCHAR)
                           ORDER BY TRY_CAST(date AS TIMESTAMP) DESC NULLS LAST
                       ) AS rn
                FROM {fmt}.bat_innings
                WHERE date IS NOT NULL AND batter_id IS NOT NULL
            ) t WHERE rn = 1
        ) sub WHERE CAST(batter_id AS VARCHAR) = sub.bid
    """, f"{fqn}.recent_team")


def _attach_recent_team_bowl(con, fmt):
    fqn = f"{fmt}.bowl_careers"
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS recent_team VARCHAR", "add recent_team")
    _safe_exec(con, f"""
        UPDATE {fqn} SET recent_team = sub.team FROM (
            SELECT bowler_id AS bid, bowling_team AS team FROM (
                SELECT CAST(bowler_id AS VARCHAR) AS bowler_id,
                       CASE WHEN bowling_team IS NULL
                                 OR LOWER(CAST(bowling_team AS VARCHAR)) IN ('nan','none','<na>','nat','')
                            THEN NULL
                            ELSE CAST(bowling_team AS VARCHAR) END AS bowling_team,
                       ROW_NUMBER() OVER (
                           PARTITION BY CAST(bowler_id AS VARCHAR)
                           ORDER BY TRY_CAST(date AS TIMESTAMP) DESC NULLS LAST
                       ) AS rn
                FROM {fmt}.bowl_spells
                WHERE date IS NOT NULL AND bowler_id IS NOT NULL
            ) t WHERE rn = 1
        ) sub WHERE CAST(bowler_id AS VARCHAR) = sub.bid
    """, f"{fqn}.recent_team")


def _attach_form_rollups_bat(con, fmt):
    fqn = f"{fmt}.bat_careers"
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS form_composite_max DOUBLE", "add form_composite_max")
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS form_composite_latest DOUBLE", "add form_composite_latest")
    _safe_exec(con, f"""
        UPDATE {fqn} SET form_composite_max = sub.fcm, form_composite_latest = sub.fcl FROM (
            SELECT mx.bid, mx.fcm, lt.fcl FROM (
                SELECT CAST(batter_id AS VARCHAR) AS bid, MAX(window_composite) AS fcm
                FROM {fmt}.bat_form WHERE date IS NOT NULL GROUP BY bid
            ) mx LEFT JOIN (
                SELECT bid, window_composite AS fcl FROM (
                    SELECT CAST(batter_id AS VARCHAR) AS bid, window_composite,
                           ROW_NUMBER() OVER (
                               PARTITION BY CAST(batter_id AS VARCHAR)
                               ORDER BY TRY_CAST(date AS TIMESTAMP) DESC NULLS LAST
                           ) AS rn
                    FROM {fmt}.bat_form WHERE date IS NOT NULL
                ) t WHERE rn = 1
            ) lt ON mx.bid = lt.bid
        ) sub WHERE CAST(batter_id AS VARCHAR) = sub.bid
    """, f"{fqn}.form_rollups")


def _attach_form_rollups_bowl(con, fmt):
    fqn = f"{fmt}.bowl_careers"
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS form_composite_max DOUBLE", "add form_composite_max")
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS form_composite_latest DOUBLE", "add form_composite_latest")
    _safe_exec(con, f"""
        UPDATE {fqn} SET form_composite_max = sub.fcm, form_composite_latest = sub.fcl FROM (
            SELECT mx.bid, mx.fcm, lt.fcl FROM (
                SELECT CAST(bowler_id AS VARCHAR) AS bid, MAX(window_composite) AS fcm
                FROM {fmt}.bowl_form WHERE date IS NOT NULL GROUP BY bid
            ) mx LEFT JOIN (
                SELECT bid, window_composite AS fcl FROM (
                    SELECT CAST(bowler_id AS VARCHAR) AS bid, window_composite,
                           ROW_NUMBER() OVER (
                               PARTITION BY CAST(bowler_id AS VARCHAR)
                               ORDER BY TRY_CAST(date AS TIMESTAMP) DESC NULLS LAST
                           ) AS rn
                    FROM {fmt}.bowl_form WHERE date IS NOT NULL
                ) t WHERE rn = 1
            ) lt ON mx.bid = lt.bid
        ) sub WHERE CAST(bowler_id AS VARCHAR) = sub.bid
    """, f"{fqn}.form_rollups")


def _propagate_to_ctx_table(con, fmt, ctx_table):
    """Copy recent_team and form rollups from bat_careers to a ctx entry table."""
    fqn = f"{fmt}.{ctx_table}"

    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS recent_team VARCHAR", f"{ctx_table} add recent_team")
    _safe_exec(con, f"""
        UPDATE {fqn} SET recent_team = src.recent_team
        FROM {fmt}.bat_careers src
        WHERE CAST({fqn}.batter_id AS VARCHAR) = CAST(src.batter_id AS VARCHAR)
    """, f"{ctx_table}.recent_team")

    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS form_composite_max DOUBLE", f"{ctx_table} add fcm")
    _safe_exec(con, f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS form_composite_latest DOUBLE", f"{ctx_table} add fcl")
    _safe_exec(con, f"""
        UPDATE {fqn}
        SET form_composite_max = src.form_composite_max,
            form_composite_latest = src.form_composite_latest
        FROM {fmt}.bat_careers src
        WHERE CAST({fqn}.batter_id AS VARCHAR) = CAST(src.batter_id AS VARCHAR)
    """, f"{ctx_table}.form_rollups")


def _normalize_detail_table(con, fmt, table, id_col):
    fqn = f"{fmt}.{table}"
    _normalize_id_col(con, fqn, id_col)
    _safe_exec(
        con,
        f"ALTER TABLE {fqn} ALTER COLUMN date TYPE TIMESTAMP USING TRY_CAST(date AS TIMESTAMP)",
        f"{fqn}.date",
    )


def _normalize_sim_table(con, fmt, table, id_col_a, id_col_b):
    fqn = f"{fmt}.{table}"
    _normalize_id_col(con, fqn, id_col_a)
    _normalize_id_col(con, fqn, id_col_b)


def _normalize_matchup_table(con, fmt, table):
    fqn = f"{fmt}.{table}"
    _normalize_id_col(con, fqn, "batter_id")
    _normalize_id_col(con, fqn, "bowler_id")


def transform_format(con, fmt, tables_loaded):
    print(f"  transforms for {fmt} ...")

    # ── bat_careers ──
    if "bat_careers" in tables_loaded:
        fqn = f"{fmt}.bat_careers"
        _normalize_id_col(con, fqn, "batter_id")
        _add_defaults(con, fqn, BAT_CAREER_DEFAULTS)
        _coerce_scores(con, fmt, "bat_careers")

        if "bat_innings" in tables_loaded:
            _attach_last_match_date_bat(con, fmt)
            _attach_recent_team_bat(con, fmt)
        if "bat_form" in tables_loaded:
            _attach_form_rollups_bat(con, fmt)

    # ── bowl_careers ──
    if "bowl_careers" in tables_loaded:
        fqn = f"{fmt}.bowl_careers"
        _normalize_id_col(con, fqn, "bowler_id")
        _add_defaults(con, fqn, BOWL_CAREER_DEFAULTS)
        _coerce_scores(con, fmt, "bowl_careers")

        if "bowl_spells" in tables_loaded:
            _attach_last_match_date_bowl(con, fmt)
            _attach_recent_team_bowl(con, fmt)
        if "bowl_form" in tables_loaded:
            _attach_form_rollups_bowl(con, fmt)

    # ── ctx entry tables ──
    for ctx in ("bat_careers_ctx_entry_early", "bat_careers_ctx_entry_death"):
        if ctx in tables_loaded:
            fqn = f"{fmt}.{ctx}"
            _normalize_id_col(con, fqn, "batter_id")
            _add_defaults(con, fqn, BAT_CAREER_DEFAULTS)
            _coerce_scores(con, fmt, ctx)
            if "bat_careers" in tables_loaded:
                _propagate_to_ctx_table(con, fmt, ctx)

    # ── detail tables ──
    if "bat_innings" in tables_loaded:
        _normalize_detail_table(con, fmt, "bat_innings", "batter_id")
    if "bowl_spells" in tables_loaded:
        _normalize_detail_table(con, fmt, "bowl_spells", "bowler_id")
    if "bat_form" in tables_loaded:
        _normalize_detail_table(con, fmt, "bat_form", "batter_id")
    if "bowl_form" in tables_loaded:
        _normalize_detail_table(con, fmt, "bowl_form", "bowler_id")

    # ── similarity tables ──
    if "bat_sim" in tables_loaded:
        _normalize_sim_table(con, fmt, "bat_sim", "batter_id", "comp_batter_id")
    if "bowl_sim" in tables_loaded:
        _normalize_sim_table(con, fmt, "bowl_sim", "bowler_id", "comp_bowler_id")

    # ── matchup tables ──
    if "matchups" in tables_loaded:
        _normalize_matchup_table(con, fmt, "matchups")
    if "matchups_phase" in tables_loaded:
        _normalize_matchup_table(con, fmt, "matchups_phase")


# ── Materialized startup views ────────────────────────────────────────

def create_materialized_views(con, fmt, tables_loaded):
    print(f"  materialized views for {fmt} ...")

    if "bat_innings" in tables_loaded:
        _safe_exec(con, f"""
            CREATE TABLE {fmt}.era_baselines_cache AS
            WITH yearly AS (
                SELECT DATE_PART('year', TRY_CAST(date AS TIMESTAMP))::INTEGER AS year,
                       MEDIAN(sr) AS par_sr,
                       (SUM(fours) + SUM(sixes)) / NULLIF(SUM(balls_faced), 0) * 100.0 AS boundary_rate,
                       SUM(dots) / NULLIF(SUM(balls_faced), 0) * 100.0 AS dot_pct,
                       COUNT(DISTINCT match_id) AS matches,
                       COUNT(*) AS innings
                FROM {fmt}.bat_innings
                WHERE DATE_PART('year', TRY_CAST(date AS TIMESTAMP)) >= 2005
                GROUP BY year HAVING COUNT(*) >= 10
            ),
            latest_par AS (
                SELECT par_sr AS latest_par_sr
                FROM yearly WHERE par_sr IS NOT NULL
                ORDER BY year DESC LIMIT 1
            )
            SELECT y.year,
                   ROUND(y.par_sr, 2) AS par_sr,
                   ROUND(y.boundary_rate, 2) AS boundary_rate,
                   ROUND(y.dot_pct, 2) AS dot_pct,
                   y.matches,
                   y.innings,
                   ROUND(l.latest_par_sr / NULLIF(y.par_sr, 0), 3) AS multiplier
            FROM yearly y CROSS JOIN latest_par l
            ORDER BY y.year
        """, f"{fmt}.era_baselines_cache")

    if "venue" in tables_loaded:
        try:
            has_difficulty = _column_exists(con, fmt, "venue", "venue_difficulty")
            if has_difficulty:
                _safe_exec(con, f"""
                    CREATE TABLE {fmt}.venue_with_difficulty AS
                    SELECT *,
                           ROUND(PERCENT_RANK() OVER (ORDER BY venue_difficulty) * 100, 4)
                               AS venue_difficulty_index
                    FROM {fmt}.venue
                """, f"{fmt}.venue_with_difficulty")
            else:
                print(f"    skip venue_with_difficulty (no venue_difficulty column)")
        except Exception as e:
            print(f"  WARN venue_with_difficulty: {e}")


# ── Main ──────────────────────────────────────────────────────────────

def build(parquet_root, output_path):
    tmp_path = f"{output_path}.building.duckdb"

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    t0 = time.time()
    print(f"Building {output_path} from {parquet_root}")

    con = duckdb.connect(tmp_path)
    con.execute("SET memory_limit = '2GB'")

    loaded = load_raw_tables(con, parquet_root)

    for fmt, tables_loaded in loaded.items():
        if not tables_loaded:
            continue
        transform_format(con, fmt, tables_loaded)
        create_materialized_views(con, fmt, tables_loaded)

    con.close()

    if os.path.exists(output_path):
        os.remove(output_path)
    os.rename(tmp_path, output_path)

    elapsed = time.time() - t0
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Done: {output_path} ({size_mb:.1f} MB) in {elapsed:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Build cricket.duckdb from pipeline Parquet output")
    parser.add_argument("--parquet-root", default="data/output", help="Root directory containing format subdirectories")
    parser.add_argument("--output", default="cricket.duckdb", help="Output DuckDB file path")
    args = parser.parse_args()

    build(args.parquet_root, args.output)


if __name__ == "__main__":
    main()
