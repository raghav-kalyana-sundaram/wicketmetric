#!/usr/bin/env python3
"""
Build a compact cricket_seed.duckdb (~5–10 MB) from a full Cricket Metrics DuckDB.

Copies a single format schema (default: mens_ipl) with recent matches and all
related career / form / matchup rows for players who appear in that slice.

Usage (from version-1 root, after you have a full data/cricket.duckdb):

  .venv/bin/python scripts/build_seed_duckdb.py \\
      --source data/cricket.duckdb --output data/cricket_seed.duckdb

Tune --max-matches if the file is too large or too small.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

VALID_FORMATS = ("mens_t20i", "womens_t20i", "mens_ipl", "womens_ipl")


def _list_tables(con: duckdb.DuckDBPyConnection, schema: str) -> list[str]:
    rows = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = ?
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        [schema],
    ).fetchall()
    return [r[0] for r in rows]


def _table_exists(con: duckdb.DuckDBPyConnection, schema: str, name: str) -> bool:
    r = con.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ? AND table_type = 'BASE TABLE'
        """,
        [schema, name],
    ).fetchone()
    return r is not None


def build_seed(
    source_path: Path,
    output_path: Path,
    schema: str,
    max_matches: int,
    max_matchup_rows: int,
) -> None:
    if schema not in VALID_FORMATS:
        raise SystemExit(f"Invalid schema {schema!r}; expected one of {VALID_FORMATS}")

    source_path = source_path.resolve()
    if not source_path.is_file():
        raise SystemExit(f"Source database not found: {source_path}")

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".building.duckdb")
    if tmp.exists():
        tmp.unlink()
    if output_path.exists():
        output_path.unlink()

    con = duckdb.connect(str(tmp))
    try:
        con.execute("SET memory_limit = '1GB'")
        con.execute("ATTACH ? AS src (READ_ONLY)", [str(source_path)])

        chk = con.execute(
            """
            SELECT 1 FROM information_schema.schemata
            WHERE schema_name = ?
            """,
            [schema],
        ).fetchone()
        if not chk:
            raise SystemExit(f"Schema {schema!r} not present in {source_path}")

        con.execute(f"CREATE SCHEMA {schema}")

        if not _table_exists(con, schema, "bat_innings"):
            raise SystemExit(f"Source {schema}.bat_innings missing")

        # Recent matches (cricsheet match_id sorts roughly newest-last for numeric ids).
        con.execute(
            f"""
            CREATE TEMP TABLE _seed_matches AS
            SELECT match_id
            FROM src.{schema}.bat_innings
            GROUP BY match_id
            ORDER BY MAX(CAST(match_id AS VARCHAR)) DESC
            LIMIT {int(max_matches)}
            """
        )

        con.execute(
            f"""
            CREATE TABLE {schema}.bat_innings AS
            SELECT bi.*
            FROM src.{schema}.bat_innings bi
            WHERE bi.match_id IN (SELECT match_id FROM _seed_matches)
            """
        )

        if _table_exists(con, schema, "bowl_spells"):
            con.execute(
                f"""
                CREATE TABLE {schema}.bowl_spells AS
                SELECT bs.*
                FROM src.{schema}.bowl_spells bs
                WHERE bs.match_id IN (SELECT match_id FROM _seed_matches)
                """
            )

        con.execute(
            f"""
            CREATE TEMP TABLE _seed_players AS
            SELECT DISTINCT batter_id AS player_id FROM {schema}.bat_innings
            UNION
            SELECT DISTINCT bowler_id AS player_id FROM {schema}.bowl_spells
            WHERE 1=1
            """
        )

        # If bowl_spells missing, _seed_players still works from bat_innings only.
        try:
            con.execute(
                f"""
                INSERT INTO _seed_players
                SELECT DISTINCT bowler_id FROM {schema}.bowl_spells
                WHERE bowler_id IS NOT NULL
                """
            )
        except duckdb.CatalogException:
            pass

        tables = _list_tables(con, schema)
        done = {"bat_innings", "bowl_spells"}

        copy_player_table = {
            "bat_careers",
            "bowl_careers",
            "bat_careers_ctx_entry_early",
            "bat_careers_ctx_entry_death",
            "bat_form",
            "bowl_form",
        }

        for t in tables:
            if t in done:
                continue
            if t in copy_player_table and _table_exists(con, "src", f"{schema}.{t}"):
                # src schema qualification for ATTACH
                con.execute(
                    f"""
                    CREATE TABLE {schema}.{t} AS
                    SELECT s.*
                    FROM src.{schema}.{t} s
                    INNER JOIN _seed_players p ON s.player_id = p.player_id
                    """
                )
                done.add(t)

        # Similarity matrices: keep pairs where both ends are in the seed player set.
        for t in ("bat_sim", "bowl_sim"):
            if _table_exists(con, "src", f"{schema}.{t}") and t not in done:
                con.execute(
                    f"""
                    CREATE TABLE {schema}.{t} AS
                    SELECT s.*
                    FROM src.{schema}.{t} s
                    INNER JOIN _seed_players p1 ON s.player_id = p1.player_id
                    INNER JOIN _seed_players p2 ON s.similar_player_id = p2.player_id
                    """
                )
                done.add(t)

        for t in ("matchups", "matchups_phase"):
            if _table_exists(con, "src", f"{schema}.{t}") and t not in done:
                con.execute(
                    f"""
                    CREATE TABLE {schema}.{t} AS
                    SELECT * FROM (
                        SELECT s.*
                        FROM src.{schema}.{t} s
                        INNER JOIN _seed_players pb ON s.batter_id = pb.player_id
                        INNER JOIN _seed_players pw ON s.bowler_id = pw.player_id
                    ) q
                    LIMIT {int(max_matchup_rows)}
                    """
                )
                done.add(t)

        # Venues and aggregates are small; copy whole tables if present.
        for t in ("venue", "venue_with_difficulty", "era_baselines_cache"):
            if _table_exists(con, "src", f"{schema}.{t}") and t not in done:
                con.execute(f"CREATE TABLE {schema}.{t} AS SELECT * FROM src.{schema}.{t}")
                done.add(t)

        # Any remaining tables: copy with a hard row cap for safety.
        for t in _list_tables(con, "src"):
            if t in done or t in {"bat_innings", "bowl_spells"}:
                continue
            # Already created in dest schema?
            if _table_exists(con, schema, t):
                continue
            if _table_exists(con, "src", f"{schema}.{t}"):
                con.execute(
                    f"CREATE TABLE {schema}.{t} AS SELECT * FROM src.{schema}.{t} LIMIT 500000"
                )

        con.execute("DETACH src")
    finally:
        con.close()

    os.rename(tmp, output_path)
    mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Wrote {output_path} ({mb:.2f} MB)")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="Build a small seed DuckDB for desktop / offline use.")
    ap.add_argument("--source", type=Path, required=True, help="Full cricket.duckdb path")
    ap.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "cricket_seed.duckdb",
        help="Output path (default: data/cricket_seed.duckdb under version-1)",
    )
    ap.add_argument("--schema", default="mens_ipl", choices=list(VALID_FORMATS))
    ap.add_argument("--max-matches", type=int, default=140, help="Recent matches to keep")
    ap.add_argument(
        "--max-matchup-rows",
        type=int,
        default=80_000,
        help="Cap for matchups / matchups_phase (per table)",
    )
    args = ap.parse_args()
    try:
        build_seed(args.source, args.output, args.schema, args.max_matches, args.max_matchup_rows)
    except duckdb.Error as e:
        print(f"DuckDB error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
