from __future__ import annotations

import re
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
    "performances_t20",
    "super_over_stats",
    "model_meta",
    "resource_grid",
    "chase_grid",
    "raa_slices_t20",
    "replacement_t20",
    "pool_bridge_t20",
    "runs_per_win_t20",
    "match_value_t20",
    "model_audit",
    "unscored_exposure",
    "chase_distortion",
    "form_ratings",
)

# Cricsheet writes the same ground several ways depending on when the file was
# published: bare ("Lord's") in older data, ground-plus-city ("Lord's, London")
# in newer, sometimes with a renamed city or a missing space after an initial.
# Left alone, a single ground splits into two or three venue pages and every
# ground filter under-counts. Canonical form is ground-plus-city, because the
# bare ground name is ambiguous — six different County Grounds share one.
#
# Cities that were renamed, or districts recorded in place of the metro. The
# value is the spelling every variant collapses to.
CITY_ALIASES = {
    "bengaluru": "Bangalore",
    "gqeberha": "Port Elizabeth",
    "grenada": "St George's",
    "mirpur": "Dhaka",
    "navi mumbai": "Mumbai",
    "pallekele": "Kandy",
}

_INITIAL_DOT = re.compile(r"(?<=[A-Za-z])\.(?=[A-Za-z])")
_SPACES = re.compile(r"\s+")


def _canonical_city(city: str | None) -> str:
    name = _SPACES.sub(" ", (city or "").strip())
    return CITY_ALIASES.get(name.lower(), name)


def _clean_ground(venue: str) -> str:
    """Tidy a raw ground string: "M.Chinnaswamy  Stadium" -> "M Chinnaswamy Stadium"."""
    return _SPACES.sub(" ", _INITIAL_DOT.sub(" ", venue or "")).strip().strip(",").strip()


def _strip_places(ground: str, places: frozenset[str]) -> str:
    """Drop trailing place segments so the city can be re-appended just once.

    Only segments after a comma are considered, which keeps single-word grounds
    like "Melbourne Cricket Ground" intact.
    """
    while True:
        head, sep, tail = ground.rpartition(",")
        if not sep or not head.strip() or tail.strip().lower() not in places:
            return ground
        ground = head.strip().strip(",").strip()


def venue_map(rows: list[tuple[str | None, str | None]]) -> dict[tuple[str, str], tuple[str, str]]:
    """Map every raw (venue, city) pair onto its canonical pair."""
    best_city: dict[str, str] = {}
    counts: dict[tuple[str, str], int] = {}
    for venue, city in rows:
        if not venue or not (city or "").strip():
            continue
        key = (_clean_ground(venue), _SPACES.sub(" ", city.strip()))
        counts[key] = counts.get(key, 0) + 1
    for (ground, city), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        best_city.setdefault(ground, city)

    places = frozenset(_canonical_city(c).lower() for _, c in rows if c) | frozenset(
        CITY_ALIASES
    )
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for venue, city in rows:
        if not venue:
            continue
        ground = _clean_ground(venue)
        raw_city = (city or "").strip()
        if not raw_city:
            raw_city = best_city.get(ground, "")
        canonical_city = _canonical_city(raw_city)
        base = _strip_places(ground, places)
        name = f"{base}, {canonical_city}" if canonical_city and base else (base or ground)
        out[(venue, city or "")] = (name, canonical_city)
    return out


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
CREATE OR REPLACE VIEW v_performances_t20 AS
  SELECT pf.*, p.display_name, p.unique_name, p.slug, m.start_date, m.venue,
         m.winner, m.result_method, m.team_home, m.team_away
  FROM performances_t20 pf
  JOIN people p ON p.person_id = pf.person_id
  JOIN matches m ON m.match_id = pf.match_id;
CREATE OR REPLACE VIEW v_super_over_stats AS
  SELECT s.*, p.display_name, p.unique_name
  FROM super_over_stats s
  JOIN people p ON p.person_id = s.person_id;
CREATE OR REPLACE VIEW v_resource_grid AS SELECT * FROM resource_grid;
CREATE OR REPLACE VIEW v_chase_grid AS SELECT * FROM chase_grid;
CREATE OR REPLACE VIEW v_raa_slices_t20 AS
  SELECT s.*, p.display_name, p.unique_name, p.slug
  FROM raa_slices_t20 s
  JOIN people p ON p.person_id = s.person_id;
CREATE OR REPLACE VIEW v_replacement_t20 AS SELECT * FROM replacement_t20;
CREATE OR REPLACE VIEW v_pool_bridge_t20 AS SELECT * FROM pool_bridge_t20;
CREATE OR REPLACE VIEW v_runs_per_win_t20 AS SELECT * FROM runs_per_win_t20;
CREATE OR REPLACE VIEW v_match_value_t20 AS
  SELECT v.*, m.start_date, m.venue, m.winner, m.season
  FROM match_value_t20 v
  JOIN matches m ON m.match_id = v.match_id;
CREATE OR REPLACE VIEW v_model_audit AS SELECT * FROM model_audit;
CREATE OR REPLACE VIEW v_unscored_exposure AS SELECT * FROM unscored_exposure;
CREATE OR REPLACE VIEW v_chase_distortion AS SELECT * FROM chase_distortion;
CREATE OR REPLACE VIEW v_form_ratings AS
  SELECT f.*, p.display_name, p.unique_name, p.slug
  FROM form_ratings f
  JOIN people p ON p.person_id = f.person_id;
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
    "v_performances_t20",
    "v_super_over_stats",
    "v_resource_grid",
    "v_chase_grid",
    "v_raa_slices_t20",
    "v_replacement_t20",
    "v_pool_bridge_t20",
    "v_runs_per_win_t20",
    "v_match_value_t20",
    "v_model_audit",
    "v_unscored_exposure",
    "v_chase_distortion",
    "v_form_ratings",
]


def warehouse_ready() -> bool:
    return (WAREHOUSE / "matches.parquet").exists()


_VENUE_CACHE: tuple[float, list[tuple[str, str, str, str]]] | None = None


def _venue_rows(con: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str, str, str]]:
    global _VENUE_CACHE
    stamp = path.stat().st_mtime
    if _VENUE_CACHE and _VENUE_CACHE[0] == stamp:
        return _VENUE_CACHE[1]
    pairs = con.execute(
        "SELECT DISTINCT venue, city FROM matches WHERE venue IS NOT NULL"
    ).fetchall()
    mapping = venue_map(pairs)
    rows = [
        (raw_venue, raw_city, name, city)
        for (raw_venue, raw_city), (name, city) in mapping.items()
    ]
    _VENUE_CACHE = (stamp, rows)
    return rows


def _apply_venue_map(con: duckdb.DuckDBPyConnection) -> None:
    path = WAREHOUSE / "matches.parquet"
    if not path.exists():
        return
    escaped = str(path).replace("'", "''")
    try:
        rows = _venue_rows(con, path)
        if not rows:
            return
        con.execute(
            "CREATE OR REPLACE TABLE venue_alias "
            "(raw_venue VARCHAR, raw_city VARCHAR, venue VARCHAR, city VARCHAR)"
        )
        con.executemany("INSERT INTO venue_alias VALUES (?, ?, ?, ?)", rows)
        con.execute(
            f"""CREATE OR REPLACE VIEW matches AS
            SELECT s.* REPLACE (
              COALESCE(a.venue, s.venue) AS venue,
              COALESCE(a.city, s.city) AS city
            )
            FROM read_parquet('{escaped}') s
            LEFT JOIN venue_alias a
              ON a.raw_venue = s.venue
             AND a.raw_city = COALESCE(s.city, '')"""
        )
    except duckdb.Error:
        pass


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
    _apply_venue_map(con)


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
