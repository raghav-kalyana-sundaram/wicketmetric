Here is the exhaustive pre-migration inventory.

Cricket Metrics — Data Layer Inventory (pandas → DuckDB)
1. bat_careers
Source Parquet: batting_careers_full.parquet

Columns touched in data_loader.py
Column	Where referenced
batter_id
_clean_bat_careers, _attach_last_match_dates, _attach_recent_teams, _attach_form_composite_rollups, get_batter_by_id, get_all_countries, get_all_archetypes
role
_add_role_column (synthesized)
is_provisional_bat
_clean_bat_careers (default if missing)
overall_grade
_clean_bat_careers (default "D" if missing)
archetype
_clean_bat_careers (default "Unknown"), get_all_archetypes
country
_clean_bat_careers (default "Unknown"), get_all_countries
position_group
_clean_bat_careers (default "unknown" if missing)
score_* (all prefix-matched)
_clean_bat_careers — fill NaN → 0.0
last_match_date
_attach_last_match_dates (dropped, re-added), activity_reference_cutoff, max_last_match_date_iso
recent_team
_attach_recent_teams (dropped, re-added)
form_composite_max
_attach_form_composite_rollups (dropped, re-added)
form_composite_latest
_attach_form_composite_rollups (dropped, re-added)
Post-load mutations (SQL equivalents)
-- _clean_bat_careers
ALTER TABLE bat_careers ALTER COLUMN batter_id TYPE VARCHAR;
ALTER TABLE bat_careers ADD COLUMN IF NOT EXISTS role VARCHAR DEFAULT 'bat';
ALTER TABLE bat_careers ADD COLUMN IF NOT EXISTS is_provisional_bat BOOLEAN DEFAULT TRUE;
ALTER TABLE bat_careers ADD COLUMN IF NOT EXISTS overall_grade VARCHAR DEFAULT 'D';
ALTER TABLE bat_careers ADD COLUMN IF NOT EXISTS archetype VARCHAR DEFAULT 'Unknown';
ALTER TABLE bat_careers ADD COLUMN IF NOT EXISTS country VARCHAR DEFAULT 'Unknown';
ALTER TABLE bat_careers ADD COLUMN IF NOT EXISTS position_group VARCHAR DEFAULT 'unknown';
-- for each score_* column dynamically:
UPDATE bat_careers SET score_X = COALESCE(TRY_CAST(score_X AS DOUBLE), 0.0);
-- _attach_last_match_dates  (LEFT JOIN + MAX aggregate)
ALTER TABLE bat_careers DROP COLUMN IF EXISTS last_match_date;
SELECT bc.*, lm.last_match_date
FROM bat_careers bc
LEFT JOIN (
  SELECT batter_id, MAX(date) AS last_match_date
  FROM bat_innings GROUP BY batter_id
) lm ON bc.batter_id = lm.batter_id;
-- _attach_recent_teams  (latest-row per batter via window function)
ALTER TABLE bat_careers DROP COLUMN IF EXISTS recent_team;
SELECT bc.*, rt.batting_team AS recent_team
FROM bat_careers bc
LEFT JOIN (
  SELECT batter_id, batting_team
  FROM (
    SELECT batter_id, batting_team,
           ROW_NUMBER() OVER (PARTITION BY batter_id ORDER BY date DESC NULLS LAST) AS rn
    FROM bat_innings WHERE date IS NOT NULL AND batter_id IS NOT NULL
  ) t WHERE rn = 1
) rt ON bc.batter_id = rt.batter_id;
-- _attach_form_composite_rollups  (MAX + LAST_VALUE per batter from bat_form)
ALTER TABLE bat_careers DROP COLUMN IF EXISTS form_composite_max, DROP COLUMN IF EXISTS form_composite_latest;
SELECT bc.*, mx.form_composite_max, lt.form_composite_latest
FROM bat_careers bc
LEFT JOIN (
  SELECT batter_id, MAX(window_composite) AS form_composite_max
  FROM bat_form WHERE date IS NOT NULL GROUP BY batter_id
) mx ON bc.batter_id = mx.batter_id
LEFT JOIN (
  SELECT batter_id, window_composite AS form_composite_latest
  FROM (
    SELECT batter_id, window_composite,
           ROW_NUMBER() OVER (PARTITION BY batter_id ORDER BY date DESC NULLS LAST) AS rn
    FROM bat_form WHERE date IS NOT NULL
  ) t WHERE rn = 1
) lt ON bc.batter_id = lt.batter_id;
Added-at-load columns (not in raw Parquet)
Column	How derived
role
Constant 'bat'
is_provisional_bat
Default TRUE (only if absent in Parquet)
overall_grade
Default 'D' (only if absent)
archetype
Default 'Unknown' (only if absent)
country
Default 'Unknown' (only if absent)
position_group
Default 'unknown' (only if absent)
last_match_date
MAX(bat_innings.date) GROUP BY batter_id
recent_team
batting_team from latest bat_innings row per batter
form_composite_max
MAX(bat_form.window_composite) GROUP BY batter_id
form_composite_latest
window_composite from chronologically last bat_form row per batter
2. bowl_careers
Source Parquet: bowling_careers_full.parquet

Columns touched
Column	Where referenced
bowler_id
_clean_bowl_careers, _attach_last_match_dates, _attach_recent_teams, _attach_form_composite_rollups, get_bowler_by_id
role
_add_role_column (synthesized 'bowl')
is_provisional_bowl
_clean_bowl_careers
overall_grade
_clean_bowl_careers
archetype
_clean_bowl_careers, get_all_archetypes
country
_clean_bowl_careers, get_all_countries
phase_group
_clean_bowl_careers (default "unknown")
score_*
_clean_bowl_careers
last_match_date
_attach_last_match_dates, activity_reference_cutoff, max_last_match_date_iso
recent_team
_attach_recent_teams
form_composite_max
_attach_form_composite_rollups
form_composite_latest
_attach_form_composite_rollups
Post-load mutations (SQL equivalents)
Structurally identical to bat_careers but substituting:

bowler_id for batter_id
source bowl_spells (for last_match_date and recent_team) instead of bat_innings
source bowl_form (for form rollups) instead of bat_form
bowling_team → recent_team instead of batting_team
phase_group instead of position_group
is_provisional_bowl instead of is_provisional_bat
Added-at-load columns
Column	How derived
role
Constant 'bowl'
is_provisional_bowl
Default TRUE (if absent)
overall_grade, archetype, country
Defaults (if absent)
phase_group
Default 'unknown' (if absent)
last_match_date
MAX(bowl_spells.date) GROUP BY bowler_id
recent_team
bowling_team from latest bowl_spells row per bowler
form_composite_max
MAX(bowl_form.window_composite) GROUP BY bowler_id
form_composite_latest
window_composite from last bowl_form row per bowler
3. bat_careers_ctx_entry_early
Source Parquet: batting_careers_ctx_entry_early.parquet

Columns touched
Same base columns as bat_careers (goes through identical _clean_bat_careers path), plus:

Column	Where referenced
batter_id
All three attach functions
recent_team
_attach_recent_teams (propagated from bat_careers, not re-derived from bat_innings)
form_composite_max, form_composite_latest
_attach_form_composite_rollups (same bat_form aggregates as bat_careers)
Post-load mutations (SQL equivalents)
-- _attach_recent_teams: propagate from bat_careers (not bat_innings directly)
ALTER TABLE bat_careers_ctx_entry_early DROP COLUMN IF EXISTS recent_team;
SELECT ctx.*, rt.recent_team
FROM bat_careers_ctx_entry_early ctx
LEFT JOIN (
  SELECT DISTINCT ON (batter_id) batter_id, recent_team
  FROM bat_careers
) rt ON CAST(ctx.batter_id AS VARCHAR) = CAST(rt.batter_id AS VARCHAR);
-- _attach_form_composite_rollups: same MAX/LAST_VALUE query on bat_form as bat_careers
Added-at-load columns
Same as bat_careers except last_match_date is not attached to context-sliced tables (only recent_team and form rollups are propagated).

4. bat_careers_ctx_entry_death
Source Parquet: batting_careers_ctx_entry_death.parquet

Identical treatment to bat_careers_ctx_entry_early in every respect. See §3.

5. bat_innings
Source Parquet: batting_innings_detail.parquet

Columns touched
Column	Where referenced
batter_id
_clean_innings, _attach_last_match_dates, _attach_recent_teams, get_batter_innings, get_batter_form (fallback)
date
_clean_innings (type coerce), _attach_last_match_dates, _attach_recent_teams, get_batter_innings sort, get_batter_form fallback
batting_team
_attach_recent_teams
runs_scored
get_batter_form fallback (also checks runs as alias)
runs
get_batter_form fallback (alias for runs_scored)
window_composite
get_batter_form fallback (synthesized column, see below)
Columns referenced indirectly by get_batter_innings sort: any column passed as sort_by param (API-driven, typically date, runs_scored, sr, balls_faced, etc.)

Post-load mutations (SQL equivalents)
-- _clean_innings
ALTER TABLE bat_innings ALTER COLUMN batter_id TYPE VARCHAR;
UPDATE bat_innings SET date = TRY_CAST(date AS TIMESTAMP);  -- errors='coerce' → NULL
Added-at-load columns
None permanently added to the table. The window_composite column is synthesized at query time only in the fallback path of get_batter_form:

-- Computed at query time, never stored:
SELECT date,
       LEAST(COALESCE(runs_scored, 0), 50) * 2.0 AS window_composite
FROM bat_innings
WHERE batter_id = ?
ORDER BY date
LIMIT 20;
6. bowl_spells
Source Parquet: bowling_spells_detail.parquet

Columns touched
Column	Where referenced
bowler_id
_clean_innings, _attach_last_match_dates, _attach_recent_teams, get_bowler_spells, get_bowler_form (fallback)
date
_clean_innings, _attach_last_match_dates, _attach_recent_teams, get_bowler_spells sort
bowling_team
_attach_recent_teams
wickets
get_bowler_form fallback
economy
get_bowler_form fallback
window_composite
get_bowler_form fallback (synthesized)
Post-load mutations (SQL equivalents)
ALTER TABLE bowl_spells ALTER COLUMN bowler_id TYPE VARCHAR;
UPDATE bowl_spells SET date = TRY_CAST(date AS TIMESTAMP);
Added-at-load columns
None permanently. window_composite synthesized at query time in fallback:

-- wickets path:
LEAST(COALESCE(wickets, 0), 5) * 20.0 AS window_composite
-- economy path (fallback):
(10.0 - LEAST(COALESCE(economy, 10.0), 10.0)) * 10.0 AS window_composite
7. bat_form
Source Parquet: batting_form_series.parquet

Columns touched
Column	Where referenced
batter_id
_clean_innings, _attach_form_composite_rollups, get_batter_form
date
_clean_innings, _attach_form_composite_rollups (sort + dropna), get_batter_form
window_composite
_attach_form_composite_rollups (MAX + LAST), get_batter_form, get_batter_form_summary
Columns surfaced through schemas.FormPoint (consumed by routes, not directly in data_loader.py): match_id, window_innings, score_1, score_2, score_3, score_1_label–score_3_label, is_peak_window, window_avg_runs, window_avg_sr, window_total_runs, window_fours, window_sixes, window_sr_vs_par, window_impact, window_boundary_pct, window_six_rate, window_dot_control, window_consistency, window_rotation

Post-load mutations (SQL equivalents)
ALTER TABLE bat_form ALTER COLUMN batter_id TYPE VARCHAR;
UPDATE bat_form SET date = TRY_CAST(date AS TIMESTAMP);
Added-at-load columns
None. This table is source for bat_careers rollups; nothing is added to it.

8. bowl_form
Source Parquet: bowling_form_series.parquet

Columns touched
Column	Where referenced
bowler_id
_clean_innings, _attach_form_composite_rollups, get_bowler_form
date
_clean_innings, _attach_form_composite_rollups, get_bowler_form
window_composite
_attach_form_composite_rollups, get_bowler_form, get_bowler_form_summary
Columns surfaced through schemas.FormPoint (bowling-specific): window_economy, window_dot_pct, window_wickets_per_spell, window_total_wickets, window_economy_vs_par, window_quality_wickets, window_threat_pressure

Post-load mutations
ALTER TABLE bowl_form ALTER COLUMN bowler_id TYPE VARCHAR;
UPDATE bowl_form SET date = TRY_CAST(date AS TIMESTAMP);
Added-at-load columns
None.

9. bat_sim
Source Parquet: batting_similarities.parquet

Columns touched
Column	Where referenced
batter_id
_ensure_id_columns, get_batter_similarities
comp_batter_id
Load step (astype(str))
similarity
get_batter_similarities (sort)
Columns surfaced through schemas.SimilarPlayer: name, country, score_1, score_2, score_3, score_1_label–score_3_label

Post-load mutations
ALTER TABLE bat_sim ALTER COLUMN batter_id TYPE VARCHAR;
ALTER TABLE bat_sim ALTER COLUMN comp_batter_id TYPE VARCHAR;
Added-at-load columns
None.

10. bowl_sim
Source Parquet: bowling_similarities.parquet

Columns touched
Column	Where referenced
bowler_id
_ensure_id_columns, get_bowler_similarities
comp_bowler_id
Load step (astype(str))
similarity
get_bowler_similarities (sort)
Post-load mutations
ALTER TABLE bowl_sim ALTER COLUMN bowler_id TYPE VARCHAR;
ALTER TABLE bowl_sim ALTER COLUMN comp_bowler_id TYPE VARCHAR;
Added-at-load columns
None.

11. matchups
Source Parquet: matchups.parquet

Columns touched
Column	Where referenced
batter_id
_ensure_id_columns, get_matchups_for_batter, get_matchups_for_bowler, get_head_to_head
bowler_id
_ensure_id_columns, all matchup accessors
balls_faced
get_matchups_for_batter, get_matchups_for_bowler (min_balls filter)
dominance_index
get_matchups_for_batter (sort desc), get_matchups_for_bowler (sort asc)
Columns surfaced through schemas.MatchupSummary and schemas.HeadToHeadResponse: opponent_id, opponent_name, balls, runs, sr, dismissals, dot_pct, boundary_pct

Post-load mutations
ALTER TABLE matchups ALTER COLUMN batter_id TYPE VARCHAR;
ALTER TABLE matchups ALTER COLUMN bowler_id TYPE VARCHAR;
Added-at-load columns
None.

12. matchups_phase
Source Parquet: matchups_by_phase.parquet

Columns touched
Column	Where referenced
batter_id
_ensure_id_columns, get_head_to_head
bowler_id
_ensure_id_columns, get_head_to_head
Columns surfaced through schemas.MatchupPhase: phase, balls, runs, sr, dots, dismissals, dominance_index

Post-load mutations
ALTER TABLE matchups_phase ALTER COLUMN batter_id TYPE VARCHAR;
ALTER TABLE matchups_phase ALTER COLUMN bowler_id TYPE VARCHAR;
Added-at-load columns
None.

13. venue
Source Parquet: venue_baselines.parquet

Columns touched
No column-level access in data_loader.py. Loaded raw, no mutations applied.

Columns surfaced through schemas.VenueBaseline: venue, matches, avg_par_sr, boundary_rate, dot_pct, difficulty_score

Post-load mutations
None.

Added-at-load columns
None.

Cross-DataFrame Joins Summary
Join	Left table	Right table	Key(s)	Type	Purpose
1
bat_careers
bat_innings
batter_id
LEFT JOIN
Compute last_match_date via MAX(date)
2
bat_careers
bat_innings
batter_id
LEFT JOIN + ROW_NUMBER
Compute recent_team (latest batting_team)
3
bat_careers
bat_form
batter_id
LEFT JOIN
Compute form_composite_max, form_composite_latest
4
bowl_careers
bowl_spells
bowler_id
LEFT JOIN
Compute last_match_date via MAX(date)
5
bowl_careers
bowl_spells
bowler_id
LEFT JOIN + ROW_NUMBER
Compute recent_team (latest bowling_team)
6
bowl_careers
bowl_form
bowler_id
LEFT JOIN
Compute form_composite_max, form_composite_latest
7
bat_careers_ctx_entry_early
bat_careers
batter_id
LEFT JOIN
Propagate recent_team
8
bat_careers_ctx_entry_death
bat_careers
batter_id
LEFT JOIN
Propagate recent_team
9
bat_careers_ctx_entry_early
bat_form
batter_id
LEFT JOIN
Compute form rollups
10
bat_careers_ctx_entry_death
bat_form
batter_id
LEFT JOIN
Compute form rollups
MultiDataStore Pattern and DuckDB Schema Isolation
The MultiDataStore is a dict[str, DataStore] keyed by one of four format strings:

mens_t20i  |  womens_t20i  |  mens_ipl  |  womens_ipl
Each key maps to a completely independent set of all 13 tables, loaded from a separate on-disk directory (e.g., output_mens_t20i/). There is no cross-format data sharing at the Python level.

Recommended DuckDB strategy: separate schemas inside a single .duckdb file.

CREATE SCHEMA mens_t20i;
CREATE SCHEMA womens_t20i;
CREATE SCHEMA mens_ipl;
CREATE SCHEMA womens_ipl;
-- Tables live under their schema:
mens_t20i.bat_careers
mens_t20i.bowl_careers
womens_ipl.bat_innings
-- etc.
Why not the alternatives:

Strategy	Problem
Separate .duckdb files (one per format)
Requires opening 4 connections; no cross-format aggregate queries possible; more complex connection management
Table name prefixes in a single schema (mens_t20i_bat_careers)
Proliferates to 52 tables; query construction becomes string-concatenation-heavy; no namespace boundary
Separate schemas (recommended)
Maps 1:1 to existing MultiDataStore.stores[fmt]; SET search_path = mens_t20i emulates the store.get(fmt) call; cross-format queries remain possible via fully-qualified names
The API ?format= parameter translates to a DuckDB session-level SET search_path = <fmt> (or equivalent prefix on every query) before execution.

Tricky Migrations
T1 — NaN float vs SQL NULL in object dtype columns
batting_team and bowling_team in bat_innings/bowl_spells originate from pandas object dtype columns that mix real strings with float('nan') sentinel values (a common artifact of pandas' nullable string handling). When written to Parquet, these become VARCHAR columns where some rows contain the literal string "nan".

_normalize_recent_team_value explicitly handles this:

if isinstance(v, float) and pd.isna(v): return None
if s.lower() in ("nan", "none", "<na>"): return None
DuckDB equivalent required in the view:

CASE
  WHEN batting_team IS NULL
    OR LOWER(batting_team) IN ('nan', 'none', '<na>', 'nat') THEN NULL
  ELSE batting_team
END AS batting_team
This must be applied before the recent_team window-function join or DuckDB will propagate "nan" strings as valid team names.

T2 — _collapse_duplicate_team_label is unbounded Python logic
This function deduplicates doubled franchise names like "Mumbai Indians Mumbai Indians" → "Mumbai Indians" using a substring prefix-search algorithm. There is no SQL equivalent. Options:

Implement as a DuckDB Python UDF
Run as a preprocessing step and store the cleaned value in the Parquet
Apply only at API serialization time (never in the DB layer)
The third option is safest — leave the raw team name in storage and apply the normalization in the Python response layer.

T3 — pd.NaT as explicit NULL date sentinel
In _attach_last_match_dates, if bat_innings is empty or missing, the code assigns pd.NaT directly:

c["last_match_date"] = pd.NaT
In DuckDB, the column must be declared as DATE or TIMESTAMP NOT NULL DEFAULT NULL — the concept is the same (NULL), but you must ensure the column type is a date type rather than being omitted or defaulting to VARCHAR. If last_match_date ends up in the Parquet as an object column containing NaT tokens, DuckDB will read it as a VARCHAR column with "NaT" strings, not as NULL DATE.

Fix: In activity_reference_cutoff, pd.to_datetime(df["last_match_date"], errors="coerce") is called, which converts "NaT" strings back to NaT. In DuckDB, use:

TRY_CAST(last_match_date AS DATE)
everywhere last_match_date is compared against a threshold.

T4 — batter_id / bowler_id integer-vs-string joins
Both _attach_recent_teams and _attach_form_composite_rollups explicitly call .astype(str) on batter_id columns from both sides of the join before merging. This implies the raw Parquet may store these IDs as INT64 in some tables and VARCHAR in others.

DuckDB join type inference will silently return zero rows on INT64 = VARCHAR mismatches without raising an error. All join conditions on batter_id/bowler_id must be wrapped:

CAST(bc.batter_id AS VARCHAR) = CAST(inn.batter_id AS VARCHAR)
The cleanest fix is to normalize all ID columns to VARCHAR at ingestion time inside the DuckDB views.

T5 — score_* wildcard column enumeration
score_cols = [c for c in df.columns if c.startswith("score_")]
for col in score_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
SQL has no wildcard column selector. In DuckDB this requires either:

Dynamic SQL at view-creation time (enumerate columns in Python, generate COALESCE(TRY_CAST(score_X AS DOUBLE), 0.0) for each)
A macro that operates column-by-column at runtime
The safest approach is to enumerate all score_* columns explicitly when creating the DuckDB views, accepting that adding a new score column requires a schema migration.

T6 — groupby().last() vs MAX() semantic difference
In _attach_form_composite_rollups:

bf = bf.sort_values("date")
last_rows = bf.groupby("batter_id", observed=True).last().reset_index()
.last() on a sorted GroupBy returns the values from the chronologically last row (for every column), not the maximum value. If the last row has window_composite = NULL (because the most recent form window is incomplete), form_composite_latest will be NULL even when earlier rows have values.

The DuckDB equivalent must replicate this exactly with ROW_NUMBER() rather than MAX():

SELECT batter_id, window_composite AS form_composite_latest
FROM (
  SELECT batter_id, window_composite,
         ROW_NUMBER() OVER (PARTITION BY batter_id ORDER BY date DESC NULLS LAST) AS rn
  FROM bat_form WHERE date IS NOT NULL
) t WHERE rn = 1
Using LAST_VALUE() or MAX() would yield different results when the latest row has a null composite.

T7 — pd.to_numeric(errors="coerce") on mixed-type Parquet columns
If score_* columns were written to Parquet as object dtype (mixed strings and floats), DuckDB reads them as VARCHAR. A plain CAST(score_X AS DOUBLE) will raise an error on non-numeric strings. Must use TRY_CAST:

COALESCE(TRY_CAST(score_X AS DOUBLE), 0.0)
This matches the pandas errors="coerce" + .fillna(0.0) chain exactly.

T8 — _clean_float / _clean_int / _clean_str at serialization boundary
These functions in schemas.py guard against NaN, inf, and "nan" strings leaking into JSON. They are applied at the Pydantic serialization layer, not in the data layer. In DuckDB this is less of a concern since NaN in a DOUBLE column read from Parquet is a distinct value from NULL — and DuckDB's JDBC/ADBC drivers surface it as IEEE NaN, not as NULL.

The risk is that DuckDB query results may return NaN floats where the current Pydantic validators normalize them to None. The serialization-layer guards in schemas.py must remain unchanged, but be aware that DuckDB WHERE score_X > 50 will exclude NaN rows differently than pandas (pandas excludes NaN from comparisons; DuckDB's NaN > 50 evaluates to true per IEEE 754 ordering where NaN compares greater than any finite number).

Recommended fix: Add WHERE score_X IS NOT NULL AND NOT isnan(score_X) to all leaderboard filter queries, or normalize NaN → NULL in the DuckDB ingestion views.

T9 — date column across three different tables
_clean_innings is called for bat_innings, bowl_spells, bat_form, and bowl_form. It applies pd.to_datetime(df["date"], errors="coerce"), which handles string dates, integer epoch timestamps, and pre-existing datetime objects uniformly. DuckDB's TRY_CAST(x AS TIMESTAMP) handles strings but not integer epoch milliseconds. If any of these Parquet files store dates as INT64 epoch milliseconds, a DuckDB-specific conversion is needed:

-- For epoch-millisecond integers:
epoch_ms(CAST(date AS BIGINT)) AS date
-- For ISO date strings:
TRY_STRPTIME(date, '%Y-%m-%d') AS date
The actual storage format should be verified against the Parquet schema before writing views.



Now I have a complete picture of all five files. Let me write the full DuckDB migration guide.

DuckDB Migration: Pandas Query Translation
Summary of Data Tables Referenced
Pandas store attribute	Proposed DuckDB table/view
store.bat_careers
bat_careers
store.bat_careers_ctx_entry_early
bat_careers (with ctx_entry_phase column) or separate bat_careers_ctx table
store.bat_careers_ctx_entry_death
same
store.bowl_careers
bowl_careers
store.bat_innings
bat_innings
store.bowl_spells
bowl_spells
store.matchups
matchups
MultiDataStore.get(fmt)
schema-per-format or format column on each table
1. Rankings — /api/rankings/bat and /api/rankings/bowl
1a. Leaderboard filters — _apply_filters (rankings.py:172–261)
Rating: Easy — all are direct WHERE clause predicates.

-- All filters combined (batting leaderboard example)
WHERE 1=1
  -- country filter (rankings.py:224)
  AND ($country IS NULL OR LOWER(country) = LOWER($country))
  -- archetype filter (rankings.py:228)
  AND ($archetype IS NULL OR LOWER(archetype) = LOWER($archetype))
  -- provisional filter TRUE = only provisional (rankings.py:233)
  -- provisional filter FALSE = exclude provisional (rankings.py:235)
  AND (
    $provisional IS NULL
    OR ($provisional = TRUE  AND is_provisional_bat = TRUE)
    OR ($provisional = FALSE AND (is_provisional_bat = FALSE OR is_provisional_bat IS NULL))
  )
  -- minimum innings (rankings.py:239) — column is innings_count for bat, matches for bowl
  AND ($min_innings IS NULL OR $min_innings = 0 OR innings_count >= $min_innings)
  -- position group (rankings.py:243) — batting only
  AND ($position_group IS NULL OR LOWER(position_group) = LOWER($position_group))
  -- phase group (rankings.py:249) — bowling only
  AND ($phase_group IS NULL OR LOWER(phase_group) = LOWER($phase_group))
  -- modal batting slot 1–11 (rankings.py:257)
  AND ($modal_slot IS NULL OR TRY_CAST(modal_position AS INTEGER) = $modal_slot)
1b. Activity filter — _filter_by_activity (rankings.py:284–303)
Rating: Easy

-- activity = 'active'  (rankings.py:300)
AND last_match_date IS NOT NULL
AND last_match_date >= $activity_cutoff
-- activity = 'retired'  (rankings.py:302)
AND (last_match_date IS NULL OR last_match_date < $activity_cutoff)
-- activity = 'all' → no clause added
$activity_cutoff is computed once in Python from activity_reference_cutoff(store, format) and passed as a bound parameter. That function itself has no pandas dependency — it just returns a pd.Timestamp, which becomes a DATE literal.

1c. Context entry phase — _batting_leaderboard_source_df (rankings.py:486–503)
Rating: Easy — currently switches between three separate DataFrames; in DuckDB this becomes a single table with a discriminator column (or three separate tables).

Option A — single table with a ctx_entry_phase column:

-- Full career  (ctx_entry_phase = 'none')
WHERE ctx_entry_phase = 'none'
-- Entry early  (ctx_entry_phase = 'early')
WHERE ctx_entry_phase = 'early'
-- Entry death  (ctx_entry_phase = 'death')
WHERE ctx_entry_phase = 'death'
Option B — three separate tables, chosen in Python before query dispatch:

table = {
    "none":  "bat_careers",
    "early": "bat_careers_ctx_entry_early",
    "death": "bat_careers_ctx_entry_death",
}[ctx_entry_phase]
Then f"SELECT ... FROM {table} WHERE ...". Option A is cleaner; it mirrors the existing pandas multi-DataFrame pattern as one table.

1d. Sort + pagination — sort_values + iloc[start:end] (rankings.py:643–656)
Rating: Easy

# pandas (rankings.py:643-656)
filtered = filtered.sort_values(eff_sort_col, ascending=ascending, na_position="last")
start = (page - 1) * per_page
page_df = filtered.iloc[start : start + per_page]
-- DuckDB equivalent
ORDER BY {sort_col} {ASC | DESC} NULLS LAST
LIMIT  $per_page
OFFSET $offset         -- $offset = ($page - 1) * $per_page
The total count needed for total_pages requires a separate query or a COUNT(*) OVER () window:

-- Option 1: two queries
SELECT COUNT(*) FROM bat_careers WHERE ...;
SELECT * FROM bat_careers WHERE ... ORDER BY ... LIMIT ... OFFSET ...;
-- Option 2: window (one round-trip, slightly more scan work)
SELECT *, COUNT(*) OVER () AS total_count
FROM bat_careers
WHERE ...
ORDER BY {sort_col} NULLS LAST
LIMIT $per_page OFFSET $offset;
1e. Top-N shortcuts — nlargest / nsmallest (rankings.py:895, 921; matchups.py:304, 336, 368)
Rating: Easy

# pandas (rankings.py:895)
top = filtered.nlargest(limit, eff)
# pandas (matchups.py:304)
bunnies_df = matchups_df.nsmallest(limit, "dominance_index")
-- nlargest → ORDER BY DESC LIMIT
SELECT * FROM bat_careers WHERE ...
ORDER BY {eff} DESC NULLS LAST
LIMIT $limit;
-- nsmallest → ORDER BY ASC LIMIT
SELECT * FROM matchups
WHERE bowler_id = $bowler_id AND balls_faced >= $min_balls
ORDER BY dominance_index ASC NULLS LAST
LIMIT $limit;
2. Display Ratings — rating_display.py
2a. The core problem
batting_display_ratings and bowling_display_ratings (rating_display.py:38–89) read four columns:

Column	Source in pandas
overall_score
native column in bat_careers / bowl_careers
peak_window_composite
native column in careers
form_composite_max
NOT a careers column — pre-merged from the form time-series
form_composite_latest
NOT a careers column — pre-merged from the form time-series
In the current system, form_composite_max and form_composite_latest are presumably added to the careers DataFrame at load time by joining the form tracking table. They do not live natively in the careers Parquet files. This is the central migration challenge for the display ratings.

2b. SQL translation — CTE approach
Rating: Medium — straightforward once the form aggregates are defined as a CTE or materialized view.

-- DuckDB: form aggregates needed for display ratings
-- bat_form has columns: batter_id, date, window_composite, ...
WITH form_agg AS (
    SELECT
        batter_id,
        MAX(window_composite)              AS form_composite_max,
        ARG_MAX(window_composite, date)    AS form_composite_latest
        -- ARG_MAX(val, key) = val at the row where key is maximum
    FROM bat_form
    GROUP BY batter_id
),
careers_with_ratings AS (
    SELECT
        c.*,
        -- Replicates batting_display_ratings() logic (rating_display.py:49-61)
        COALESCE(fa.form_composite_max, c.peak_window_composite)  AS _ceiling,
        CASE
            WHEN c.overall_score IS NULL THEN NULL
            WHEN COALESCE(fa.form_composite_max, c.peak_window_composite) IS NULL
                THEN c.overall_score
            ELSE LEAST(c.overall_score,
                       COALESCE(fa.form_composite_max, c.peak_window_composite))
        END AS rating_overall,
        CASE
            WHEN c.innings_count >= 10 AND fa.form_composite_latest IS NOT NULL THEN
                CASE
                    WHEN COALESCE(fa.form_composite_max, c.peak_window_composite) IS NOT NULL
                        THEN LEAST(fa.form_composite_latest,
                                   COALESCE(fa.form_composite_max, c.peak_window_composite))
                    ELSE fa.form_composite_latest
                END
            ELSE  -- fallback: same as rating_overall
                CASE
                    WHEN c.overall_score IS NULL THEN NULL
                    WHEN COALESCE(fa.form_composite_max, c.peak_window_composite) IS NULL
                        THEN c.overall_score
                    ELSE LEAST(c.overall_score,
                               COALESCE(fa.form_composite_max, c.peak_window_composite))
                END
        END AS rating_current
    FROM bat_careers c
    LEFT JOIN form_agg fa ON c.batter_id = fa.batter_id
)
SELECT * FROM careers_with_ratings
WHERE ...
ORDER BY rating_current DESC NULLS LAST  -- or rating_overall
LIMIT $per_page OFFSET $offset;
For bowling, substitute bowl_form, bowler_id, matches >= 10.

2c. apply_display_rating_sort_column (rating_display.py:97–114)
Rating: Hard in pandas → Easy in SQL once 2b is solved.

The current pandas implementation is a Python row-by-row loop that computes rating_current or rating_overall for every row in the filtered DataFrame and appends a temp column — an O(n) Python loop over potentially thousands of rows. This exists only because the careers DataFrame doesn't already carry these computed columns.

In DuckDB, rating_current and rating_overall are computed columns in the WITH clause above. Sorting by them is free:

ORDER BY rating_current DESC NULLS LAST   -- sort_col = 'rating_current'
ORDER BY rating_overall DESC NULLS LAST   -- sort_col = 'rating_overall'
Recommendation: Materialize form_composite_max and form_composite_latest onto the careers table as a pre-computation step (either in the ETL pipeline or as a DuckDB materialized view). This eliminates the join on every leaderboard request:

CREATE OR REPLACE VIEW bat_careers_with_ratings AS
WITH form_agg AS (
    SELECT batter_id,
           MAX(window_composite)           AS form_composite_max,
           ARG_MAX(window_composite, date) AS form_composite_latest
    FROM bat_form GROUP BY batter_id
)
SELECT c.*,
       fa.form_composite_max,
       fa.form_composite_latest,
       -- ... rating_overall / rating_current expressions ...
FROM bat_careers c
LEFT JOIN form_agg fa USING (batter_id);
The leaderboard endpoint then simply queries bat_careers_with_ratings.

3. Player Profile — /api/player/{id}
3a. Career row lookup — batter_id == id mask (player.py:293–296, 444–447)
Rating: Easy — DuckDB's Parquet scan with a point predicate on a string column is fast without an explicit index. Parquet's row-group statistics will skip irrelevant groups. For a careers table with O(10k) rows the full scan is also negligible. An explicit index is unnecessary.

# pandas (player.py:293-296)
mask = store.bat_careers["batter_id"] == comp_id
comp_matches = store.bat_careers.loc[mask]
comp_row = comp_matches.iloc[0]
SELECT * FROM bat_careers WHERE batter_id = $batter_id LIMIT 1;
The same applies for bowler_id lookups in bowl_careers.

N+1 warning: _build_batter_profile calls get_batter_by_id once per similar player (up to 10, player.py:292). In DuckDB, replace with a single WHERE batter_id IN (...):

SELECT * FROM bat_careers
WHERE batter_id IN ($comp_id_1, $comp_id_2, ..., $comp_id_10);
3b. Phase splits from innings — per-player aggregation (player.py:546–603)
Rating: Easy — the pandas code sums phase columns row-by-row; this is a single GROUP BY-free aggregate with a WHERE filter.

# pandas (player.py:553-554)
mask = store.bat_innings["batter_id"] == batter_id
innings = store.bat_innings.loc[mask]
total_balls = innings["powerplay_balls"].sum()   # etc. for each phase
SELECT
    SUM(powerplay_balls)  AS powerplay_balls,
    SUM(powerplay_runs)   AS powerplay_runs,
    SUM(powerplay_dots)   AS powerplay_dots,
    SUM(powerplay_fours)  AS powerplay_fours,
    SUM(powerplay_sixes)  AS powerplay_sixes,
    SUM(middle_balls)     AS middle_balls,
    SUM(middle_runs)      AS middle_runs,
    SUM(middle_dots)      AS middle_dots,
    SUM(middle_fours)     AS middle_fours,
    SUM(middle_sixes)     AS middle_sixes,
    SUM(death_balls)      AS death_balls,
    SUM(death_runs)       AS death_runs,
    SUM(death_dots)       AS death_dots,
    SUM(death_fours)      AS death_fours,
    SUM(death_sixes)      AS death_sixes
FROM bat_innings
WHERE batter_id = $batter_id;
The derived metrics (sr, dot_pct, boundary_pct) are computed in Python from the returned sums — no change needed there.

The equivalent for bowling phase splits (player.py:606–661) using bowl_spells:

SELECT
    SUM(powerplay_legal_balls) AS powerplay_legal_balls,
    SUM(powerplay_runs)        AS powerplay_runs,
    SUM(powerplay_wickets)     AS powerplay_wickets,
    SUM(powerplay_dots)        AS powerplay_dots,
    SUM(powerplay_fours)       AS powerplay_fours,
    SUM(powerplay_sixes)       AS powerplay_sixes,
    -- middle / death equivalents ...
FROM bowl_spells
WHERE bowler_id = $bowler_id;
3c. Innings/spells pagination — sort_values + iloc (player.py:875–913, 920–974)
Rating: Easy — same pattern as rankings pagination (section 1d), scoped to a single player.

-- count
SELECT COUNT(*) FROM bat_innings WHERE batter_id = $player_id;
-- page
SELECT
    match_id, date, bowling_team AS opposition,
    runs, balls_faced, sr, fours, sixes, dots,
    is_out, how_out, batting_position,
    powerplay_sr, middle_sr, death_sr,
    sr_vs_par, match_par_sr
FROM bat_innings
WHERE batter_id = $player_id
ORDER BY {sort_by} {ASC | DESC} NULLS LAST
LIMIT $per_page OFFSET $offset;
sort_by must be allowlisted in the application layer (same as current pandas column-existence check at player.py:1146) before interpolation.

-- spells equivalent
SELECT
    match_id, date, batting_team AS opposition,
    overs_bowled, runs_conceded, wickets, economy,
    dot_pct, fours_conceded, sixes_conceded,
    wides_count, noballs_count,
    powerplay_economy, middle_economy, death_economy, economy_vs_par
FROM bowl_spells
WHERE bowler_id = $player_id
ORDER BY {sort_by} {ASC | DESC} NULLS LAST
LIMIT $per_page OFFSET $offset;
4. Matchups — /api/matchups/explore and /api/matchups
4a. Explore matchups — multi-column filter + dominance_index sort (matchups.py:220–263)
Rating: Easy

# pandas (matchups.py:221-226)
matchups_df = get_matchups_for_batter(store, player_id, min_balls=min_balls)
# internally: store.matchups[(store.matchups["batter_id"] == player_id)
#                           & (store.matchups["balls_faced"] >= min_balls)]
matchups_df = matchups_df.sort_values(sort_col, ascending=ascending, na_position="last")
page_df = matchups_df.iloc[start:end]
-- role = 'bat'
SELECT
    bowler_id, bowler,
    balls_faced, runs_scored, strike_rate,
    dismissals, dot_pct, boundary_pct, dominance_index
FROM matchups
WHERE batter_id  = $player_id
  AND balls_faced >= $min_balls
ORDER BY {sort_col} {ASC | DESC} NULLS LAST
LIMIT $per_page OFFSET $offset;
-- role = 'bowl'
SELECT
    batter_id, batter,
    balls_faced, runs_scored, strike_rate,
    dismissals, dot_pct, boundary_pct, dominance_index
FROM matchups
WHERE bowler_id  = $player_id
  AND balls_faced >= $min_balls
ORDER BY {sort_col} {ASC | DESC} NULLS LAST
LIMIT $per_page OFFSET $offset;
Valid sort_col values (dominance_index, balls_faced, runs_scored, strike_rate, dismissals, dot_pct, boundary_pct, average) must be allowlisted before interpolation.

4b. Head-to-head lookup — overall_df.iloc[0] (matchups.py:148)
Rating: Easy

-- overall stats (one row per batter+bowler pair)
SELECT * FROM matchups
WHERE batter_id = $bat AND bowler_id = $bowl
LIMIT 1;
-- phase breakdown (one row per batter+bowler+phase)
SELECT * FROM matchups_by_phase
WHERE batter_id = $bat AND bowler_id = $bowl
ORDER BY phase;
5. Compare — /api/compare
5a. MultiDataStore.get(fmt) + ID lookup across formats (compare.py:158–183)
Rating: Medium

The Python code iterates over available formats in preference order, stops at the first hit:

for fmt in order:          # e.g. ['mens_t20i', 'womens_t20i', 'ipl']
    store = multi.get(fmt)
    row = get_batter_by_id(store, pid)  # mask: bat_careers["batter_id"] == pid
    if row is not None:
        return store, row
Option A — separate DuckDB schemas per format (cleanest isolation):

-- Try preferred format first; fall through to others
SELECT *, 'mens_t20i' AS _fmt FROM mens_t20i.bat_careers WHERE batter_id = $pid
UNION ALL
SELECT *, 'womens_t20i' AS _fmt FROM womens_t20i.bat_careers WHERE batter_id = $pid
UNION ALL
SELECT *, 'ipl' AS _fmt FROM ipl.bat_careers WHERE batter_id = $pid
ORDER BY CASE _fmt WHEN $preferred_fmt THEN 0 ELSE 1 END
LIMIT 1;
The _fmt column tells the application which store/schema to use for subsequent innings/form queries for that player.

Option B — single table with a format column:

SELECT * FROM bat_careers
WHERE batter_id = $pid
ORDER BY CASE format WHEN $preferred_fmt THEN 0 ELSE 1 END
LIMIT 1;
Option B is simpler operationally (one file to manage) but loses schema-level isolation between formats.

5b. Shared matchups — set intersection + per-batter pivot (compare.py:528–609)
Rating: Medium — the intersection logic translates cleanly to SQL; the per-batter pivot remains in Python.

# pandas (compare.py:543-559)
mask = (st_b.matchups["batter_id"] == bid) & (st_b.matchups["balls_faced"] >= min_balls)
bdf = st_b.matchups.loc[mask]
bowler_sets.append(set(bdf["bowler_id"].unique()))
common_bowlers = bowler_sets[0]
for bs in bowler_sets[1:]:
    common_bowlers = common_bowlers & bs
-- Single query: find bowlers faced by ALL provided batters (min_balls each)
WITH batter_bowler_pairs AS (
    SELECT batter_id, bowler_id, bowler,
           balls_faced, runs_scored, strike_rate,
           dismissals, dots, fours, sixes,
           dot_pct, boundary_pct, dominance_index
    FROM matchups
    WHERE batter_id  IN ($bid_1, $bid_2, $bid_3, $bid_4)   -- 2–4 batter IDs
      AND balls_faced >= $min_balls
),
common_bowlers AS (
    SELECT bowler_id
    FROM batter_bowler_pairs
    GROUP BY bowler_id
    HAVING COUNT(DISTINCT batter_id) = $n_batters   -- must appear for every batter
)
SELECT bbp.*
FROM batter_bowler_pairs bbp
JOIN common_bowlers      cb  ON bbp.bowler_id = cb.bowler_id
ORDER BY bbp.balls_faced DESC;
The result is a flat list of rows tagged with batter_id. The Python layer pivots these into the nested { bowler_id: { bat_id: {...stats...} } } structure and sorts by total balls (compare.py:602–605). That final sort and pivot have no clean SQL equivalent as structured JSON — they stay in Python.

Difficulty Summary
Pattern	File(s)	Rating
Country / archetype / provisional / min_innings / position_group / phase_group / modal_slot filters
rankings.py
Easy
Activity (active/retired/all) date cutoff filter
rankings.py
Easy
ctx_entry_phase table switch
rankings.py
Easy
sort_values + iloc[start:end] → ORDER BY … LIMIT … OFFSET
rankings.py, matchups.py, player.py
Easy
nlargest / nsmallest top-N
rankings.py, matchups.py
Easy
batter_id == id / bowler_id == id point lookup
player.py, matchups.py, compare.py
Easy (no index needed for small careers tables; LIMIT 1 is sufficient)
Phase split aggregation from innings/spells
player.py
Easy
Innings/spells pagination per player
player.py
Easy
Explore matchups filter + sort + paginate
matchups.py
Easy
form_composite_max / form_composite_latest join for display ratings
rating_display.py
Medium — needs a LEFT JOIN on form aggregates or a pre-built view using ARG_MAX
apply_display_rating_sort_column Python loop → SQL expression
rating_display.py
Medium — trivially eliminates the loop once the CTE is in place
Cross-format player lookup (MultiDataStore.get(fmt))
compare.py
Medium — UNION ALL with preference ordering or a format discriminator column
Shared matchups set intersection
compare.py
Medium — GROUP BY … HAVING COUNT(DISTINCT batter_id) = N
Shared matchups per-batter pivot to nested dict
compare.py
Hard — no clean SQL equivalent for the { bowler_id: { bat_id: stats } } shape; Python post-processing stays
N+1 similar-player lookups (up to 10 individual iloc[0])
player.py
Hard to justify in SQL individually — batch with IN (...) in Python to avoid 10 round-trips per profile request
Key Migration Decisions
Materialize form_composite_max / form_composite_latest. These two columns are the only fields in the entire codebase that are not native to the careers Parquet files. Adding them to the careers table in the ETL step (or defining a bat_careers_with_ratings view once) unblocks display rating sorting without a per-request join.

apply_display_rating_sort_column disappears entirely. The current O(n) Python loop over thousands of rows exists solely because form_composite_max and form_composite_latest aren't on the careers DataFrame at startup. Once they're native or in a view, ORDER BY rating_current DESC NULLS LAST replaces the whole pattern.

ctx_entry_phase source selection. Consolidate the three DataFrames (bat_careers, bat_careers_ctx_entry_early, bat_careers_ctx_entry_death) into one table with a ctx_entry_phase column, or keep them as separate tables and switch the table name in Python before query dispatch — either works equally well in DuckDB.

MultiDataStore format isolation. The cleanest DuckDB analogue is one schema per format (mens_t20i.bat_careers, ipl.bat_careers, etc.). DuckDB supports ATTACH for multiple database files and schema prefixes naturally. The UNION ALL + ORDER BY preference pattern handles the "try preferred format first" logic with a single query



Now I have a complete picture of all four files. Here is the full migration assessment.

Pre-migration DuckDB Assessment
Part 1 — venue_analytics.py — Function-by-Function Catalog
attach_global_venue_difficulty_index
Reads
store.venue — columns: venue, venue_difficulty
Operation
Series.rank(pct=True) — percentile rank across all rows
DuckDB translation
Clean. PERCENT_RANK() OVER (ORDER BY venue_difficulty)
Proposed SQL
SELECT venue, ROUND(PERCENT_RANK() OVER (ORDER BY venue_difficulty) * 100, 4) AS venue_difficulty_index FROM venue
Compute when
Startup-time materialized view — venue table is static; attach once, join everywhere
filter_bat_by_venue / filter_bowl_by_venue
Reads
bat_innings or bowl_spells — column: venue/ground/stadium
Operation
str.lower() == or str.contains() filter
DuckDB translation
Trivial: WHERE lower(venue) = lower(:v) or `WHERE lower(venue) LIKE '%'
Proposed SQL
SELECT * FROM bat_innings WHERE lower(venue) = lower($venue)
Compute when
Per-request (parameterized by venue name)
These two functions become a single reusable DuckDB parameterized CTE that all downstream queries share.

resolve_venue_row
Reads
store.venue — column: venue
Operation
Exact then partial string match to canonicalize venue name
DuckDB translation
SELECT venue FROM venue WHERE lower(venue) = lower($q) LIMIT 1 then ILIKE '%…%' fallback
Compute when
Per-request. Keep as a tiny helper that runs one cheap DuckDB lookup
_phase_bat_aggregate
Reads
bat_innings filtered slice — columns: {phase}_runs, {phase}_balls for powerplay/middle/death
Operation
Sum phase runs/balls, derive SR
DuckDB translation
Clean. All SUM + arithmetic
SELECT
  SUM(powerplay_runs)  / NULLIF(SUM(powerplay_balls), 0) * 100  AS pp_sr,
  SUM(middle_runs)     / NULLIF(SUM(middle_balls),    0) * 100  AS mid_sr,
  SUM(death_runs)      / NULLIF(SUM(death_balls),     0) * 100  AS death_sr,
  SUM(powerplay_balls) AS pp_balls, SUM(middle_balls) AS mid_balls,
  SUM(death_balls) AS death_balls
FROM bat_innings
WHERE lower(venue) = lower($venue)
| Compute when | Per-request (venue-specific) |

_phase_bat_vs_par_mean
Reads
Filtered bat_innings — columns: powerplay_sr, pp_par_sr, middle_sr, middle_par_sr, death_sr, death_par_sr
Operation
mean(sr / par_sr) per phase, ignoring inf/nan
DuckDB translation
Clean: AVG(CASE WHEN par_sr > 0 THEN sr / par_sr END) (NULLs auto-excluded from AVG)
Compute when
Per-request
_phase_bowl_aggregate
Reads
bowl_spells — columns: {phase}_legal_balls, {phase}_runs, {phase}_dots
Operation
SUM balls/runs → economy (runs/overs), dot percentage
DuckDB translation
Identical pattern to _phase_bat_aggregate
Compute when
Per-request
_percentile_rank (scalar helper)
Reads
store.venue[col] as a series + a scalar value
Operation
(series < value).mean() * 100
DuckDB translation
Subquery: SELECT COUNT(*) FILTER (WHERE col < $value) * 100.0 / COUNT(*) FROM venue WHERE venue_matches >= $min_matches
Compute when
Per-request (one cheap DuckDB scalar query per metric)
_chase_defend_from_bat
Reads
bat_innings filtered — columns: match_id, innings_num, batting_team, total_runs, winner
Operation
Per-match: identify team batting 1st/2nd, check winner, accumulate bat_first_wins / chase_wins
DuckDB translation
Translatable but requires careful use of FIRST_VALUE / LAST_VALUE window functions
WITH innings AS (
    SELECT DISTINCT match_id, innings_num, batting_team, total_runs, winner
    FROM bat_innings WHERE lower(venue) = lower($venue)
),
inn1 AS (SELECT match_id, batting_team AS team1, total_runs AS score1, winner
         FROM innings WHERE innings_num = (SELECT MIN(innings_num) FROM innings i2 WHERE i2.match_id = innings.match_id)),
inn2 AS (SELECT match_id, batting_team AS team2, total_runs AS score2
         FROM innings WHERE innings_num = (SELECT MAX(innings_num) FROM innings i2 WHERE i2.match_id = innings.match_id))
SELECT
  AVG(score1) AS avg_first_innings_score,
  AVG(score2) AS avg_second_innings_score,
  COUNT(*) FILTER (WHERE winner IS NOT NULL AND winner <> '') AS matches_with_result,
  SUM(CASE WHEN winner = team1 THEN 1 ELSE 0 END) AS wins_batting_first,
  SUM(CASE WHEN winner = team2 THEN 1 ELSE 0 END) AS wins_chasing
FROM inn1 JOIN inn2 USING (match_id)
| Compute when | Per-request. Medium complexity; worth migrating because the Python version iterates match-by-match in a Python loop |

build_venue_profile (orchestrator)
Reads
store.venue, store.bat_innings, store.bowl_spells
Key heavy operation
The median_phase loop: iterates over all venues in bat_innings, calling _phase_bat_aggregate per venue group — this is the worst pandas anti-pattern in the file
DuckDB translation
The inner loop becomes a single grouped query with a MEDIAN() window:
-- Precompute at startup as a view
CREATE VIEW median_venue_phase_sr AS
SELECT
  MEDIAN(SUM(powerplay_runs) / NULLIF(SUM(powerplay_balls), 0) * 100)
    OVER () AS median_pp_sr,
  MEDIAN(SUM(middle_runs)    / NULLIF(SUM(middle_balls),    0) * 100)
    OVER () AS median_mid_sr,
  MEDIAN(SUM(death_runs)     / NULLIF(SUM(death_balls),     0) * 100)
    OVER () AS median_death_sr
FROM bat_innings
GROUP BY venue;
| Compute when | The median_phase inner loop → startup-time view. The rest → per-request DuckDB queries. The orchestration wrapper stays in Python (assembles JSON response). |

_venue_trends_by_year
Reads
Filtered bat_innings — columns: date, match_id, innings_num, batting_team, total_runs, match_par_sr
Operation
Deduplicate to match-innings level, group by year, compute AVG(total_runs) and AVG(match_par_sr) and COUNT(DISTINCT match_id)
DuckDB translation
Clean two-step CTE
WITH deduped AS (
    SELECT DISTINCT match_id, innings_num, batting_team,
           total_runs, match_par_sr,
           DATE_PART('year', date::DATE) AS yr
    FROM bat_innings WHERE lower(venue) = lower($venue)
)
SELECT yr::TEXT AS period,
       COUNT(DISTINCT match_id) AS matches,
       AVG(total_runs)    AS mean_team_innings_score,
       AVG(match_par_sr)  AS mean_match_par_sr
FROM deduped GROUP BY yr ORDER BY yr
| Compute when | Per-request |

_venue_trends_rolling_matches
Reads
Same as above but per-match aggregated
Operation
Per-match means → sort by date → rolling(window=3).mean() on runs and par_sr
DuckDB translation
Clean window function
WITH per_match AS (
    SELECT match_id,
           MIN(date) AS match_date,
           AVG(total_runs)   AS avg_innings_runs,
           AVG(match_par_sr) AS avg_match_par_sr
    FROM bat_innings WHERE lower(venue) = lower($venue)
    GROUP BY match_id
)
SELECT
  match_date::TEXT AS period,
  AVG(avg_innings_runs)   OVER w AS roll_runs,
  AVG(avg_match_par_sr)   OVER w AS roll_par
FROM per_match
WINDOW w AS (ORDER BY match_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
ORDER BY match_date
| Compute when | Per-request. The "skip rows where both NaN" guard is just WHERE roll_runs IS NOT NULL OR roll_par IS NOT NULL |

build_venue_teams
Reads
bat_innings — columns: match_id, innings_num, batting_team, winner
Operation
Per-team: count distinct matches played, count wins (winner == batting_team), win_pct. Currently nested Python loops.
DuckDB translation
Single GROUP BY with conditional aggregation — biggest Python anti-pattern in this function
SELECT batting_team AS team,
       COUNT(DISTINCT match_id) AS matches,
       SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS wins,
       COUNT(DISTINCT match_id)
         - SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END) AS losses,
       ROUND(SUM(CASE WHEN winner = batting_team THEN 1 ELSE 0 END)
             * 100.0 / NULLIF(COUNT(DISTINCT match_id), 0), 2) AS win_pct
FROM (SELECT DISTINCT match_id, innings_num, batting_team, winner
      FROM bat_innings WHERE lower(venue) = lower($venue)) t
GROUP BY batting_team
HAVING COUNT(DISTINCT match_id) >= $min_matches
ORDER BY win_pct DESC
| Compute when | Per-request with LIMIT/OFFSET for pagination |

build_venue_similar
Reads
store.venue — columns: venue_avg_par_sr, venue_avg_boundary_rate, venue_avg_dot_pct, venue_difficulty
Operation
Z-score normalization of feature matrix → pairwise cosine similarity via numpy.dot and numpy.linalg.norm
DuckDB translation
Cannot move to DuckDB SQL. DuckDB has no native cosine similarity, and this requires a full N×N comparison.
Verdict
Stays in Python. The one optimization: pre-compute the feature matrix at startup from DuckDB and cache the numpy arrays, rather than re-fetching from pandas each call.
Compute when
Can be pre-computed at startup (the similarity matrix for all venue pairs is static) and stored in memory as a dict
build_venue_matches
Reads
bat_innings — columns: match_id, date, event_name, winner, innings_num, batting_team, total_runs
Operation
Deduplicate to one row per match-innings, then collapse to one row per match with teams list and scores list, sort by date, paginate
DuckDB translation
Translatable. The teams/scores aggregation uses LIST() / ARRAY_AGG()
SELECT match_id,
       MIN(date)::TEXT AS date,
       ANY_VALUE(event_name) AS event_name,
       ANY_VALUE(winner)     AS winner,
       LIST(batting_team ORDER BY innings_num) AS teams,
       LIST(total_runs   ORDER BY innings_num) AS innings_scores
FROM (SELECT DISTINCT match_id, date, event_name, winner, innings_num, batting_team, total_runs
      FROM bat_innings WHERE lower(venue) = lower($venue)) t
GROUP BY match_id
ORDER BY MIN(date) DESC
LIMIT $per_page OFFSET $offset
| Compute when | Per-request with pagination pushed into SQL |

build_venue_performances
Reads
bat_innings / bowl_spells (filtered), then scorecard JSON files from disk ({output_dir}/scorecards/{match_id}.json)
Operation
For each qualifying innings row: load JSON file → call combined_row_for_player() (Python impact math) → assemble result row
DuckDB translation
Cannot move to DuckDB. Filesystem JSON reads and the relative bowling impact formula (pool_runs / pool_balls per match) are outside SQL's scope.
Partial win
The initial filter + sort (balls_faced >= min_balls, ORDER BY runs DESC, DROP DUPLICATES) can be a DuckDB query that returns only the (match_id, player_id) pairs to look up. The JSON-loading loop stays in Python.
Compute when
Per-request; the JSON scan is the bottleneck, not the pandas filtering
Part 2 — eras.py — DuckDB Replacement
_compute_era_baselines reads bat_innings and performs:

Parse date → extract year
Filter year ≥ 2005
Group by year, skip groups with < 10 innings
Compute MEDIAN(sr) as par_sr (or fallback SUM(runs)/SUM(balls)*100)
Compute boundary_rate = (SUM(fours)+SUM(sixes)) / SUM(balls_faced) * 100
Compute dot_pct = SUM(dots) / SUM(balls_faced) * 100
Compute multiplier = latest_par_sr / year_par_sr (cross-year reference)
Complete DuckDB replacement:

CREATE VIEW era_baselines AS
WITH yearly AS (
    SELECT
        DATE_PART('year', date::DATE)::INTEGER                        AS year,
        MEDIAN(sr)                                                    AS par_sr,
        (SUM(fours) + SUM(sixes))
          / NULLIF(SUM(balls_faced), 0) * 100.0                      AS boundary_rate,
        SUM(dots)
          / NULLIF(SUM(balls_faced), 0) * 100.0                      AS dot_pct,
        COUNT(DISTINCT match_id)                                      AS matches,
        COUNT(*)                                                      AS innings
    FROM bat_innings
    WHERE DATE_PART('year', date::DATE) >= 2005
    GROUP BY year
    HAVING COUNT(*) >= 10
),
latest_par AS (
    SELECT par_sr AS latest_par_sr
    FROM yearly
    WHERE par_sr IS NOT NULL
    ORDER BY year DESC
    LIMIT 1
)
SELECT
    y.year,
    ROUND(y.par_sr, 2)                                               AS par_sr,
    ROUND(y.boundary_rate, 2)                                        AS boundary_rate,
    ROUND(y.dot_pct, 2)                                              AS dot_pct,
    y.matches,
    y.innings,
    ROUND(l.latest_par_sr / NULLIF(y.par_sr, 0), 3)                 AS multiplier
FROM yearly y
CROSS JOIN latest_par l
ORDER BY y.year;
Should this be a startup-time materialized view or on-request query?

Startup-time materialized view. Reasons:

The data never changes during the server's lifetime (parquet files are loaded once).
The full bat_innings table scan is expensive to repeat every time /api/eras is called.
The CROSS JOIN latest_par makes the query slightly stateful (forward reference), which is easier to reason about once pre-computed.
The endpoint has no filter parameters — the result is always the same.
At startup: CREATE TABLE era_baselines_cache AS SELECT * FROM era_baselines;
At request: SELECT * FROM era_baselines_cache ORDER BY year

Part 3 — match_impact.py — Migration Complexity Assessment
DataFrames used
None. This module uses only plain Python dicts and lists. The scorecard data arrives as JSON-parsed Python dicts, not DataFrames.
Operations
Dict iteration over innings_map; accumulating per-player batting (runs²/balls) and bowling impact (BOWL_SPELL_K * wickets * balls / safe_runs + RUNS_SAVED_K * runs_saved) formulas; pool-based runs-per-ball calculation across all bowlers in the match
Why it can't move to DuckDB
(1) Input is JSON files on disk, not database rows. (2) The bowling impact formula references pool_runs = total_match_runs − this_bowler_runs, which is a self-referential aggregate across all players in the match — it would require a correlated subquery even if the data were in a table. (3) The function is called inside build_venue_performances on a per-match-per-player basis during an HTTP request.
Migration complexity rating
Low complexity to keep in Python, high complexity to migrate. The module has no pandas dependency and has no performance problems by itself. The real bottleneck in build_venue_performances is the per-match JSON file I/O and the O(N×M) loop, not this module's arithmetic.
Recommended action
Leave the formulas in Python. If scorecard data is ever loaded into DuckDB as a table (one row per player-innings), bat_impact = runs*runs/balls and the bowling formula can be expressed as SQL expressions. That is a separate infrastructure change outside this migration's scope.
Part 4 — Migration Priority List
Tier 1 — Migrate First (Easy wins, high ROI)
#	Function / Endpoint	Why easy
1
_compute_era_baselines
Pure groupby + median + arithmetic; becomes a startup view; no request params
2
list_venues endpoint
Trivial SELECT + ORDER BY + WHERE from already-loaded venue table
3
venue_detail endpoint
Point lookup query; one row
4
venues_summary endpoint
MAX/MIN/AVG/COUNT + CASE WHEN bin counts
5
filter_bat_by_venue / filter_bowl_by_venue
Becomes a parameterized WHERE clause shared by all downstream queries
6
attach_global_venue_difficulty_index
Single PERCENT_RANK() window function; becomes a startup materialized view
Tier 2 — Migrate Second (Medium complexity, high latency impact)
#	Function / Endpoint	Why medium
7
build_venue_teams
The nested team-loop is the worst anti-pattern; single GROUP BY replaces it; pagination moves to SQL
8
build_venue_matches
LIST() aggregation + ORDER BY + LIMIT/OFFSET
9
_players_at_venue_batting (venues router)
groupby player + career LEFT JOIN; replaces verbose pandas agg with a single SQL statement
10
_players_at_venue_bowling (venues router)
Same as above for bowling
11
_venue_trends_by_year
GROUP BY year + AVG
12
_phase_bat_aggregate / _phase_bowl_aggregate
SUM phase columns; straightforward but requires confirming column names in schema
13
_phase_bat_vs_par_mean
AVG(CASE WHEN par_sr > 0 THEN sr/par_sr END)
Tier 3 — Migrate Third (Complex SQL, still worth it)
#	Function / Endpoint	Why complex
14
_chase_defend_from_bat
Requires per-match first/last innings identification with subqueries; careful handling of tie/no-result matches
15
_venue_trends_rolling_matches
Rolling window SQL with ROWS BETWEEN 2 PRECEDING AND CURRENT ROW; must re-read DuckDB's handling of NULL rows in window frames
16
build_venue_profile (median_phase inner loop)
The for vname, g in all_bi.groupby(vc) loop over the full innings table is the single most expensive operation; becomes a startup view with MEDIAN() grouped by venue
17
_percentile_rank helper
Replace with scalar DuckDB queries using COUNT(*) FILTER (WHERE col < $value)
Tier 4 — Keep in Python (Migrate last or not at all)
#	Function	Why it stays
18
build_venue_similar
Cosine similarity requires numpy matrix ops; no SQL equivalent without a vector extension
19
build_venue_performances
Depends on per-match JSON file I/O; partially improvable (push the filter to DuckDB) but the scorecard loop is irreducible
20
combined_row_for_player / compute_match_impact_combined_rows (match_impact.py)
Zero DataFrame dependencies; pure Python dict math; no migration benefit unless scorecards are loaded into DuckDB as rows, which is a separate infrastructure decision
Key Architectural Observation
The biggest single performance problem in this codebase is not a specific function — it is that every per-request call to build_venue_profile re-scans the full bat_innings table (the median_phase loop at lines 311–319 in venue_analytics.py). Moving that one loop to a startup-time DuckDB view:

CREATE TABLE venue_phase_sr_stats AS
SELECT
  venue,
  AVG(pp_sr) AS mean_pp_sr, MEDIAN(pp_sr) AS median_pp_sr,
  -- ... middle, death
FROM (
  SELECT venue,
    SUM(powerplay_runs) / NULLIF(SUM(powerplay_balls), 0) * 100 AS pp_sr,
    SUM(middle_runs)    / NULLIF(SUM(middle_balls),    0) * 100 AS mid_sr,
    SUM(death_runs)     / NULLIF(SUM(death_balls),     0) * 100 AS death_sr
  FROM bat_innings GROUP BY venue
) GROUP BY venue;
...would give the largest latency win for the least effort, before any other refactoring is done.


Here is the full assessment.

1. DataStore Input Contract
build_search_index touches exactly two attributes on the DataStore:

store.bat_careers   →  _extract_batting_entries()
store.bowl_careers  →  _extract_bowling_entries()
Batting columns (bat_careers)
Column	Mapped to
batter_id
PlayerEntry.id
batter
PlayerEntry.name
country
PlayerEntry.country
archetype
PlayerEntry.archetype
overall_grade
PlayerEntry.grade_overall
innings_count
PlayerEntry.innings_count
total_runs
PlayerEntry.total_runs
career_sr
PlayerEntry.career_sr
career_avg
PlayerEntry.career_avg
score_acceleration
PlayerEntry.score_1
score_power
PlayerEntry.score_2
score_control
PlayerEntry.score_3
is_provisional_bat
PlayerEntry.is_provisional
overall_score
PlayerEntry.overall_score
modal_position
PlayerEntry.modal_position
recent_team
PlayerEntry.recent_team
(all columns the row is passed to batting_display_ratings(row))
rating_overall, rating_current
Bowling columns (bowl_careers)
Column	Mapped to
bowler_id
PlayerEntry.id
bowler
PlayerEntry.name
country
PlayerEntry.country
archetype
PlayerEntry.archetype
overall_grade
PlayerEntry.grade_overall
matches
PlayerEntry.innings_count ← note: different column name than batting
total_wickets
PlayerEntry.total_runs ← repurposed field
career_economy
PlayerEntry.career_sr ← repurposed
career_sr_bowl
PlayerEntry.career_avg ← repurposed
score_accuracy
PlayerEntry.score_1
score_control
PlayerEntry.score_2
score_threat
PlayerEntry.score_3
is_provisional_bowl
PlayerEntry.is_provisional
overall_score
PlayerEntry.overall_score
recent_team
PlayerEntry.recent_team
(all columns the row is passed to bowling_display_ratings(row))
rating_overall, rating_current
One dependency you must audit before migration: rating_display.batting_display_ratings and rating_display.bowling_display_ratings receive the entire row and return (rating_overall, rating_current). The columns they read from that row are not visible in these two files. That module's column access is part of the input contract and must be included in the DuckDB SELECT.

2. TrigramIndex Internal Memory Layout
The index builds seven data structures at add() time:

_index:        dict[str, set[str]]   # trigram  → {role:id, ...}
_players:      dict[str, PlayerEntry] # role:id  → PlayerEntry (the full record)
_name_lower:   dict[str, list[str]]  # name.lower() → [role:id, ...]  ← built but never read in search()
_by_country:   dict[str, set[str]]   # country.lower() → {role:id, ...}
_by_role:      dict[str, set[str]]   # "bat"/"bowl" → {role:id, ...}
_by_archetype: dict[str, set[str]]   # archetype.lower() → {role:id, ...}
_provisional:  set[str]              # {role:id, ...} for is_provisional=True
_non_provisional: set[str]           # {role:id, ...} for is_provisional=False
Memory estimate per format index (~2000 unique players → ~3500–4000 entries including dual-role)
_players — 4000 entries × ~450 bytes per PlayerEntry (15 fields, mix of str/float/int) ≈ ~1.8 MB

_index — This dominates. Each player name generates trigrams from " {name} " (padded). A typical name of 15 characters yields ~17 trigrams. Country (8 chars) adds ~10 more. So ~27 trigram insertions per entry × 4000 entries = ~108,000 insertions. With ~3000–5000 distinct trigrams over English/South Asian cricket names, each trigram set holds on average 20–30 keys. Python set overhead for a string key is ~60–80 bytes. Rough total: ~8–12 MB

_by_country, _by_role, _by_archetype, _provisional — small (30 countries, 2 roles, ~15 archetypes) — < 0.5 MB combined

_name_lower — 2000 entries × ~60 bytes ≈ ~0.1 MB

Per-format total: ~10–15 MB 4 formats: ~40–60 MB — entirely comfortable for an in-memory service.

One dead-weight observation: _name_lower is populated in add() but is never accessed anywhere in search(), _browse(), or _apply_filters(). It was presumably intended as a fast exact-match lookup but was never wired up. It wastes ~0.1 MB/format and a tiny bit of build time — not critical, but worth removing in the refactor.

3. Can the trigram index stay as-is?
Yes, completely. TrigramIndex has zero pandas or DataStore references. It accepts PlayerEntry objects through add() and has no opinion on where they came from. The entire surface that needs to change is:

build_search_index(store: DataStore) — replaces store.bat_careers / store.bowl_careers access
_extract_batting_entries / _extract_bowling_entries — either kept as-is (DuckDB .df() returns a pandas DataFrame, so iterrows() + row.get() works unchanged) or rewritten to iterate DuckDB result tuples directly
The DuckDB SELECT (one per role)
Assuming your DuckDB schema has tables named analogously to the pandas DataFrames, and that recent_team comes from a join to the match/innings table rather than being pre-computed in bat_careers:

-- Batting entries
SELECT
    bc.batter_id,
    bc.batter,
    bc.country,
    bc.archetype,
    bc.overall_grade,
    bc.innings_count,
    bc.total_runs,
    bc.career_sr,
    bc.career_avg,
    bc.score_acceleration,
    bc.score_power,
    bc.score_control,
    bc.is_provisional_bat,
    bc.overall_score,
    bc.modal_position,
    bc.rating_overall,       -- consumed by batting_display_ratings
    bc.rating_current,       -- consumed by batting_display_ratings
    rt.batting_team  AS recent_team
FROM bat_careers bc
LEFT JOIN (
    SELECT
        batter_id,
        batting_team,
        ROW_NUMBER() OVER (PARTITION BY batter_id ORDER BY match_date DESC) AS rn
    FROM batting_innings
) rt ON rt.batter_id = bc.batter_id AND rt.rn = 1
-- Bowling entries
SELECT
    bc.bowler_id,
    bc.bowler,
    bc.country,
    bc.archetype,
    bc.overall_grade,
    bc.matches,
    bc.total_wickets,
    bc.career_economy,
    bc.career_sr_bowl,
    bc.score_accuracy,
    bc.score_control,
    bc.score_threat,
    bc.is_provisional_bowl,
    bc.overall_score,
    bc.rating_overall,       -- consumed by bowling_display_ratings
    bc.rating_current,       -- consumed by bowling_display_ratings
    rt.bowling_team  AS recent_team
FROM bowl_careers bc
LEFT JOIN (
    SELECT
        bowler_id,
        bowling_team,
        ROW_NUMBER() OVER (PARTITION BY bowler_id ORDER BY match_date DESC) AS rn
    FROM bowling_innings
) rt ON rt.bowler_id = bc.bowler_id AND rt.rn = 1
If recent_team is already pre-computed in your DuckDB bat_careers/bowl_careers tables (as a denormalized column added during your ETL), the LEFT JOIN subquery drops out entirely, reducing each to a single-table SELECT *-style query. Either way, one query per role at startup, feed the result into _extract_batting_entries / _extract_bowling_entries unchanged via .df().

4. DuckDB FTS as a full replacement
DuckDB (as of 1.x) offers these string-matching tools relevant here:

Function	Capability	Fuzzy?
LIKE / ILIKE
Substring scan
No
regexp_matches
Pattern matching
No
jaro_winkler_similarity(a, b)
Edit-distance-based similarity
Yes
levenshtein(a, b)
Edit distance
Yes
FTS extension (fts pragma)
Token-based inverted index
Partial
DuckDB's FTS extension does build an inverted index over tokenized text, which is fast for exact token lookups, but it does not do trigram-style fuzzy matching. For fuzzy ("Bumra" → "Bumrah"), you would fall back to a full jaro_winkler_similarity scan of all rows.

Performance for ~2000–5000 names: A full-scan similarity query over 5000 rows in DuckDB runs in ~1–3ms in-process. That is acceptable for the main /api/search endpoint but noticeable for /api/search/autocomplete, which is designed to be called on every keystroke after 2 characters with a 150ms debounce. The pre-built trigram index answers autocomplete in ~0.05–0.2ms.

More importantly, the custom ranking logic is the real obstacle. Your composite score is:

trigram_overlap + exact_bonus (0/200/500/1000) + prov_penalty (50) + overall_score/100
This is trivial in Python but painful to express correctly in SQL, particularly the overall_score / 100 tie-break and the exact-starts-with logic. The all-rounders filter (find raw IDs that appear in both bat and bowl sets) is also cleaner in Python set arithmetic than as a SQL self-join.

Verdict: DuckDB FTS is not a practical replacement here. The search corpus (~2000–5000 names) is too small to benefit from a database-side index, the latency for autocomplete would regress, and the ranking logic would become a fragile SQL expression.

5. Filter Application Order in the Hybrid Approach
In the current Python implementation:

# 1. Score ALL entries by trigram overlap (full index scan)
scores: Counter[str] = Counter()
for tri in query_trigrams:
    for ikey in self._index.get(tri, set()):
        scores[ikey] += 1
# 2. THEN apply filters to reduce candidates
candidates = self._apply_filters(set(scores.keys()), role=role, ...)
Filters are post-scoring. Every entry that shares any trigram with the query gets scored first; filters then prune the candidate set before ranking. In the hybrid DuckDB approach (DuckDB provides data → same Python trigram index rebuilt at startup), nothing changes. The TrigramIndex object is identical; the router is identical; the scoring and filtering order is identical.

There is one latent inefficiency worth knowing about: if a role filter is passed, the current code still scores entries for the other role before discarding them. A minor optimization (not part of this migration) would be to intersect with self._by_role[role] before the scoring loop, not after. This is a pre-filter optimization that would halve the work for role-filtered queries. It doesn't need to be done as part of the DuckDB migration, but it's a clean follow-up.

6. Recommendation: Keep Python trigram index, rebuild from DuckDB at startup
Recommended path: replace only the builder function. The TrigramIndex class is untouched.

Reasoning:

Zero risk to search quality. The index is data-source agnostic. You are replacing one I/O pathway (store.bat_careers) with another (con.execute(sql).df()). All scoring, filtering, deduplication, and all-rounder detection logic remains in Python.

Trivially cheap to rebuild. Two SQL queries at startup over a few thousand rows. DuckDB in-process query on 2000-row tables completes in <5ms. The Python loop to add() all entries is likewise negligible.

The custom composite ranking cannot be cleanly moved to SQL. Trigram overlap counting, the exact/starts-with bonuses, the non-provisional boost, and the overall_score tie-break are all tightly coupled. Reproducing this in a DuckDB SQL expression would be fragile and hard to test.

Autocomplete latency. The pre-built index answers in sub-millisecond. A DuckDB FTS full-scan approach adds 1–3ms per keystroke, which conflicts with the stated design goal of calling on every keystroke.

_extract_batting_entries / _extract_bowling_entries can be kept verbatim because DuckDB's .df() returns a pandas DataFrame that works with iterrows() and row.get() identically. You only replace where the DataFrames come from.

The concrete migration diff is small:

# New builder — drop-in replacement for build_search_index(store)
import duckdb
def build_search_index_from_duckdb(
    con: duckdb.DuckDBPyConnection,
    format: str,          # e.g. "T20", "ODI", "Test", "T10"
) -> TrigramIndex:
    bat_df = con.execute(BAT_SEARCH_SQL.format(format=format)).df()
    bowl_df = con.execute(BOWL_SEARCH_SQL.format(format=format)).df()
    index = TrigramIndex()
    for entry in _extract_batting_entries(bat_df):
        index.add(entry)
    for entry in _extract_bowling_entries(bowl_df):
        index.add(entry)
    return index
BAT_SEARCH_SQL and BOWL_SEARCH_SQL are the two queries from section 3 above, parameterized by format. The _extract_* functions and TrigramIndex are unchanged.

Before you write the queries: audit rating_display.batting_display_ratings and rating_display.bowling_display_ratings to enumerate every column they read from the row. Those columns must be present in the DuckDB SELECT. That is the one dependency this assessment could not resolve from the two files alone.


Here is the complete architecture document, saved to docs/duckdb-migration-architecture.md. Key findings organized by section:

§1 — Connection model: Each of the 4 uvicorn workers opens its own duckdb.connect(path, read_only=True) in the lifespan handler, stored as a module-level global exactly like the current _multi_store. The critical risk: a refresh writer acquiring the exclusive write lock will block any worker that tries to open a new read connection during that window — which matters on rolling restarts. Existing open connections are unaffected.

§2 — Schema design: Named schemas wins (mens_t20i.bat_careers, etc.). It maps exactly to the ?format= parameter with a single safe interpolation (_safe_fmt(fmt)), keeps SQL readable, and makes cross-format compare queries trivial. Never interpolate fmt into SQL without validating against VALID_FORMATS first — that is the one new injection surface this migration introduces.

§3 — Startup on Hetzner: Ship the pre-built .duckdb file as a pipeline artifact to object storage. Do not bake it into the Docker image (image becomes 3–4 GB) and do not run the pipeline on the VPS (saturates RAM during serving). Cold start is ~1–2 minutes (download + connect + index build). Warm restart after file is cached on the SSD: ~30–45 seconds.

§4 — Refresh strategy: Atomic os.rename() (cricket.new.duckdb → cricket.duckdb) followed by SIGUSR2 to trigger uvicorn's graceful worker rotation. Workers finish in-flight requests against the old file inode, then each reopens the new one in its lifespan. Zero dropped requests.

§5 — Memory budget: 4 workers at memory_limit = '512MB' each comes to ~3.9 GB — dangerously close to OOM on 4 GB. 2 workers is the right call for the CAX11. DuckDB uses SET threads = 2 per connection so it still saturates all 4 ARM cores across the two workers. Add SET temp_directory = '/data/cricket/duckdb-tmp' so spill goes to SSD, not tmpfs RAM. If 4 workers become necessary, upgrade to the CAX21 (8 GB).

§6 — Lifespan diff: The blob_hydrate.maybe_hydrate_data_root_from_blob() call, the entire load_all_data() call, and the MultiDataStore/DataStore imports are removed. The three _attach_* post-load transforms from data_loader.py move into the DuckDB builder (run once at pipeline time, not at server startup). The shutdown block changes from _multi_store = None to _db_conn.close(). The largest migration surface is rewriting all 9 routers from pandas DataFrame indexing to SQL.