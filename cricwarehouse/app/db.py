from __future__ import annotations

from pathlib import Path

import duckdb

from cricwarehouse.paths import WAREHOUSE, ensure_dirs

TABLES = (
    "people",
    "matches",
    "xi",
    "innings",
    "batting_lines",
    "bowling_lines",
    "deliveries",
    "partnerships",
    "fielding_lines",
    "standings",
    "playoffs",
    "team_strength",
    "metrics_t20",
    "super_over_stats",
    "model_meta",
)

VIEWS_SQL = """
CREATE OR REPLACE VIEW v_people AS SELECT * FROM people;
CREATE OR REPLACE VIEW v_matches AS SELECT * FROM matches;
CREATE OR REPLACE VIEW v_xi AS SELECT * FROM xi;
CREATE OR REPLACE VIEW v_innings AS SELECT * FROM innings;
CREATE OR REPLACE VIEW v_batting_lines AS
  SELECT b.*, p.display_name, p.unique_name, p.slug, m.start_date, m.competition,
         m.gender, m.season, m.winner, m.result_method, m.team_home, m.team_away,
         m.event_name, m.venue
  FROM batting_lines b
  JOIN people p ON p.person_id = b.person_id
  JOIN matches m ON m.match_id = b.match_id;
CREATE OR REPLACE VIEW v_bowling_lines AS
  SELECT b.*, p.display_name, p.unique_name, p.slug, m.start_date, m.competition,
         m.gender, m.season
  FROM bowling_lines b
  JOIN people p ON p.person_id = b.person_id
  JOIN matches m ON m.match_id = b.match_id;
CREATE OR REPLACE VIEW v_partnerships AS
  SELECT pr.*, p1.display_name AS name_1, p2.display_name AS name_2,
         m.competition, m.gender, m.season, m.start_date
  FROM partnerships pr
  JOIN people p1 ON p1.person_id = pr.person_id_1
  JOIN people p2 ON p2.person_id = pr.person_id_2
  JOIN matches m ON m.match_id = pr.match_id;
CREATE OR REPLACE VIEW v_fielding AS
  SELECT f.*, p.display_name, p.unique_name, p.slug, m.competition, m.gender, m.season
  FROM fielding_lines f
  JOIN people p ON p.person_id = f.person_id
  JOIN matches m ON m.match_id = f.match_id;
CREATE OR REPLACE VIEW v_standings AS SELECT * FROM standings;
CREATE OR REPLACE VIEW v_playoffs AS SELECT * FROM playoffs;
CREATE OR REPLACE VIEW v_metrics_t20 AS
  SELECT mt.*, p.display_name, p.unique_name, p.slug
  FROM metrics_t20 mt
  JOIN people p ON p.person_id = mt.person_id;
CREATE OR REPLACE VIEW v_super_over_stats AS
  SELECT s.*, p.display_name, p.unique_name
  FROM super_over_stats s
  JOIN people p ON p.person_id = s.person_id;
"""

DOCUMENTED_VIEWS = [
    "v_people",
    "v_matches",
    "v_xi",
    "v_innings",
    "v_batting_lines",
    "v_bowling_lines",
    "v_partnerships",
    "v_fielding",
    "v_standings",
    "v_playoffs",
    "v_metrics_t20",
    "v_super_over_stats",
]


def warehouse_ready() -> bool:
    return (WAREHOUSE / "matches.parquet").exists()


def connect(*, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    ensure_dirs()
    con = duckdb.connect(database=":memory:")
    _attach_parquet(con)
    if warehouse_ready():
        try:
            con.execute(VIEWS_SQL)
        except duckdb.Error:
            pass
    return con


def _attach_parquet(con: duckdb.DuckDBPyConnection) -> None:
    for name in TABLES:
        path = WAREHOUSE / f"{name}.parquet"
        if path.exists():
            escaped = str(path).replace("'", "''")
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{escaped}')"
            )
        else:
            con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT NULL WHERE 1=0")


def write_parquet(name: str, rows: list[dict] | None, *, schema_sql: str | None = None) -> Path:
    ensure_dirs()
    path = WAREHOUSE / f"{name}.parquet"
    con = duckdb.connect(database=":memory:")
    if not rows:
        if schema_sql:
            con.execute(schema_sql)
            con.execute(f"COPY empty_tbl TO '{path}' (FORMAT PARQUET)")
        else:
            # zero-row file with a dummy column so DuckDB can still read it
            con.execute("CREATE TABLE empty_tbl (dummy INTEGER)")
            con.execute("DELETE FROM empty_tbl")
            con.execute(f"COPY empty_tbl TO '{path}' (FORMAT PARQUET)")
        return path
    import pyarrow as pa

    table = pa.Table.from_pylist(rows)
    import pyarrow.parquet as pq

    pq.write_table(table, path, compression="zstd")
    return path


def disk_size_bytes() -> int:
    if not WAREHOUSE.exists():
        return 0
    return sum(p.stat().st_size for p in WAREHOUSE.glob("*.parquet"))
