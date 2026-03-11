#!/usr/bin/env python3
"""
Static JSON Export — generates all API responses as static JSON files.

This script loads the same pipeline outputs as the FastAPI backend and
writes pre-computed JSON files that can be served as a static site
(GitHub Pages, Vercel Static, Netlify, etc.).

The frontend detects static mode via VITE_STATIC_MODE=true and adjusts
fetch URLs to load .json files from the public directory instead of
hitting a live API.

Usage:
    # From the gui/backend directory:
    python export_static.py --output ../frontend/public/api/

    # With a custom output directory:
    python export_static.py --output /path/to/static/api/ --pipeline-output ../../output

    # Dry run (show what would be written):
    python export_static.py --output ../frontend/public/api/ --dry-run

    # Limit player exports (for testing):
    python export_static.py --output ../frontend/public/api/ --limit 50

Generated structure:
    <output>/
    ├── health.json
    ├── meta.json
    ├── countries.json
    ├── archetypes.json
    ├── search/
    │   └── index.json              (all players for client-side search)
    ├── player/
    │   └── {id}.json               (one per player)
    ├── player/{id}/
    │   ├── batting.json
    │   ├── bowling.json
    │   ├── innings.json            (first page, all innings)
    │   ├── spells.json             (first page, all spells)
    │   ├── form.json
    │   ├── matchups.json
    │   └── similar.json
    ├── rankings/
    │   ├── bat.json                (pre-sorted leaderboard)
    │   ├── bowl.json
    │   ├── bat/
    │   │   └── columns.json
    │   └── bowl/
    │       └── columns.json
    ├── venues/
    │   ├── index.json
    │   ├── summary.json
    │   ├── flat-track-index.json
    │   └── {venue_name}.json       (one per venue)
    ├── eras/
    │   └── index.json
    └── similar/
        └── {id}.json               (one per player)

Follows gui.md Appendix D "Static JSON Export".
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Ensure imports work when run from gui/backend/ ────────────────
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from data_loader import (
    DataStore,
    get_all_archetypes,
    get_all_countries,
    get_batter_by_id,
    get_batter_form,
    get_batter_innings,
    get_batter_similarities,
    get_bowler_by_id,
    get_bowler_form,
    get_bowler_similarities,
    get_bowler_spells,
    get_head_to_head,
    get_matchups_for_batter,
    get_matchups_for_bowler,
    load_data,
)
from search_index import TrigramIndex, build_search_index

# ── JSON helpers ──────────────────────────────────────────────────


def _clean_value(v: Any) -> Any:
    """Recursively clean a value for JSON serialisation."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if isinstance(v, (dict,)):
        return {k: _clean_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean_value(item) for item in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    # Handle numpy types
    type_name = type(v).__name__
    if type_name in ("int64", "int32", "int16", "int8"):
        return int(v)
    if type_name in ("float64", "float32", "float16"):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    if type_name == "bool_":
        return bool(v)
    if type_name in ("Timestamp", "NaT"):
        try:
            import pandas as pd

            if pd.isna(v):
                return None
            return v.isoformat()
        except Exception:
            return str(v)
    return v


def _row_to_dict(row) -> dict:
    """Convert a pandas Series to a clean dict."""
    if row is None:
        return {}
    try:
        d = row.to_dict()
    except AttributeError:
        return {}
    return {k: _clean_value(v) for k, v in d.items()}


def _df_to_list(df, limit: int | None = None) -> list[dict]:
    """Convert a DataFrame to a list of clean dicts."""
    if df is None or (hasattr(df, "empty") and df.empty):
        return []
    rows = df.head(limit) if limit else df
    result = []
    for _, row in rows.iterrows():
        result.append({k: _clean_value(v) for k, v in row.items()})
    return result


def _safe_str(v: Any, default: str = "") -> str:
    """Convert to string safely."""
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>", "NaT"):
        return default
    return s


def _safe_float(v: Any) -> float | None:
    """Convert to float safely."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    """Convert to int safely."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _get_val(row, col: str, default=None):
    """Safely get a value from a pandas row."""
    try:
        v = row.get(col, default) if hasattr(row, "get") else getattr(row, col, default)
        if v is None:
            return default
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return default
        s = str(v)
        if s in ("nan", "NaN", "None", "<NA>", "NaT"):
            return default
        return v
    except Exception:
        return default


# ── Export functions ──────────────────────────────────────────────


def write_json(filepath: Path, data: Any, dry_run: bool = False) -> int:
    """Write JSON data to a file. Returns the file size in bytes."""
    content = json.dumps(_clean_value(data), separators=(",", ":"), default=str)

    if dry_run:
        return len(content.encode("utf-8"))

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    return filepath.stat().st_size


def build_player_summary(row, role: str = "bat") -> dict:
    """Build a PlayerSummary dict from a career row."""
    if role == "bat":
        player_id = _safe_str(_get_val(row, "batter_id", ""))
        return {
            "id": player_id,
            "name": _safe_str(_get_val(row, "batter_name", _get_val(row, "name", ""))),
            "country": _safe_str(_get_val(row, "country", "")),
            "role": "bat",
            "archetype": _safe_str(_get_val(row, "archetype", "")),
            "grade_overall": _safe_str(_get_val(row, "overall_grade", "D")),
            "innings_count": _safe_int(_get_val(row, "innings_count", 0)) or 0,
            "total_runs": _safe_int(_get_val(row, "total_runs", 0)) or 0,
            "career_sr": _safe_float(_get_val(row, "career_sr")),
            "career_avg": _safe_float(_get_val(row, "career_avg")),
            "score_1": _safe_float(_get_val(row, "score_acceleration")),
            "score_2": _safe_float(_get_val(row, "score_power")),
            "score_3": _safe_float(_get_val(row, "score_control")),
            "score_1_label": "acceleration",
            "score_2_label": "power",
            "score_3_label": "control",
            "is_provisional": bool(_get_val(row, "is_provisional_bat", True)),
            "overall_score": _safe_float(_get_val(row, "overall_score")),
        }
    else:
        player_id = _safe_str(_get_val(row, "bowler_id", ""))
        return {
            "id": player_id,
            "name": _safe_str(_get_val(row, "bowler_name", _get_val(row, "name", ""))),
            "country": _safe_str(_get_val(row, "country", "")),
            "role": "bowl",
            "archetype": _safe_str(_get_val(row, "archetype", "")),
            "grade_overall": _safe_str(_get_val(row, "overall_grade", "D")),
            "innings_count": _safe_int(
                _get_val(row, "matches", _get_val(row, "innings_count", 0))
            )
            or 0,
            "total_runs": _safe_int(_get_val(row, "total_wickets", 0)) or 0,
            "career_sr": _safe_float(_get_val(row, "career_economy")),
            "career_avg": _safe_float(_get_val(row, "career_avg")),
            "score_1": _safe_float(_get_val(row, "score_accuracy")),
            "score_2": _safe_float(_get_val(row, "score_control")),
            "score_3": _safe_float(_get_val(row, "score_threat")),
            "score_1_label": "accuracy",
            "score_2_label": "control",
            "score_3_label": "threat",
            "is_provisional": bool(_get_val(row, "is_provisional_bowl", True)),
            "overall_score": _safe_float(_get_val(row, "overall_score")),
        }


def build_batter_profile(row) -> dict:
    """Build a full BatterProfile dict from a career row."""
    d = _row_to_dict(row)
    d["id"] = _safe_str(_get_val(row, "batter_id", ""))
    d["name"] = _safe_str(_get_val(row, "batter_name", _get_val(row, "name", "")))
    d["role"] = "bat"
    return d


def build_bowler_profile(row) -> dict:
    """Build a full BowlerProfile dict from a career row."""
    d = _row_to_dict(row)
    d["id"] = _safe_str(_get_val(row, "bowler_id", ""))
    d["name"] = _safe_str(_get_val(row, "bowler_name", _get_val(row, "name", "")))
    d["role"] = "bowl"
    return d


def build_form_response(player_id: str, player_name: str, form_df) -> dict:
    """Build a FormResponse dict from form DataFrame."""
    series = _df_to_list(form_df)
    # Ensure date is a string
    for entry in series:
        if "date" in entry and entry["date"] is not None:
            entry["date"] = str(entry["date"])[:10]  # YYYY-MM-DD
    return {
        "player_id": player_id,
        "player_name": player_name,
        "series": series,
    }


def build_similarity_response(
    player_id: str,
    player_name: str,
    sim_df,
    store: DataStore,
    role: str = "bat",
    limit: int = 20,
) -> dict:
    """Build a SimilarityResponse dict from similarity DataFrame."""
    similar = []
    if sim_df is not None and not sim_df.empty:
        comp_id_col = "comp_batter_id" if role == "bat" else "comp_bowler_id"
        for _, sim_row in sim_df.head(limit).iterrows():
            comp_id = _safe_str(_get_val(sim_row, comp_id_col, ""))
            if not comp_id:
                continue

            # Look up the comp player's career row for scores
            if role == "bat":
                comp_row = get_batter_by_id(store, comp_id)
            else:
                comp_row = get_bowler_by_id(store, comp_id)

            entry = {
                "id": comp_id,
                "name": _safe_str(_get_val(sim_row, "comp_name", "")),
                "country": "",
                "similarity_score": _safe_float(_get_val(sim_row, "similarity")),
                "score_1": None,
                "score_2": None,
                "score_3": None,
            }

            if comp_row is not None:
                entry["country"] = _safe_str(_get_val(comp_row, "country", ""))
                if role == "bat":
                    entry["score_1"] = _safe_float(
                        _get_val(comp_row, "score_acceleration")
                    )
                    entry["score_2"] = _safe_float(_get_val(comp_row, "score_power"))
                    entry["score_3"] = _safe_float(_get_val(comp_row, "score_control"))
                    entry["score_1_label"] = "acceleration"
                    entry["score_2_label"] = "power"
                    entry["score_3_label"] = "control"
                else:
                    entry["score_1"] = _safe_float(_get_val(comp_row, "score_accuracy"))
                    entry["score_2"] = _safe_float(_get_val(comp_row, "score_control"))
                    entry["score_3"] = _safe_float(_get_val(comp_row, "score_threat"))
                    entry["score_1_label"] = "accuracy"
                    entry["score_2_label"] = "control"
                    entry["score_3_label"] = "threat"

            similar.append(entry)

    return {
        "target_id": player_id,
        "target_name": player_name,
        "similar": similar,
    }


def build_matchup_list(
    matchups_df, opponent_id_col: str, opponent_name_col: str
) -> list[dict]:
    """Build a list of MatchupSummary dicts."""
    if matchups_df is None or matchups_df.empty:
        return []

    result = []
    for _, row in matchups_df.iterrows():
        entry = {
            "opponent_id": _safe_str(_get_val(row, opponent_id_col, "")),
            "opponent_name": _safe_str(_get_val(row, opponent_name_col, "")),
            "balls": _safe_int(_get_val(row, "balls_faced", 0)) or 0,
            "runs": _safe_int(_get_val(row, "runs_scored", _get_val(row, "runs", 0)))
            or 0,
            "sr": _safe_float(_get_val(row, "sr", _get_val(row, "strike_rate"))),
            "dismissals": _safe_int(_get_val(row, "dismissals", 0)) or 0,
            "dot_pct": _safe_float(_get_val(row, "dot_pct")),
            "boundary_pct": _safe_float(_get_val(row, "boundary_pct")),
            "dominance_index": _safe_float(_get_val(row, "dominance_index")),
        }
        result.append(entry)
    return result


def compute_era_baselines(store: DataStore) -> list[dict]:
    """Compute era baselines from batting innings data."""
    import pandas as pd

    df = store.bat_innings
    if df.empty or "date" not in df.columns:
        return []

    working = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(working["date"]):
        working["date"] = pd.to_datetime(working["date"], errors="coerce")

    working = working.dropna(subset=["date"])
    working["year"] = working["date"].dt.year
    working = working[working["year"] >= 2005]

    if working.empty:
        return []

    has_sr = "sr" in working.columns
    has_runs = "runs" in working.columns
    has_balls = "balls_faced" in working.columns
    has_fours = "fours" in working.columns
    has_sixes = "sixes" in working.columns
    has_dots = "dots" in working.columns

    results = []
    for year, group in working.groupby("year"):
        if len(group) < 10:
            continue

        entry: dict[str, Any] = {"year": int(year)}

        if has_sr:
            sr_vals = group["sr"].dropna()
            entry["par_sr"] = (
                round(float(sr_vals.median()), 2) if len(sr_vals) > 0 else None
            )
        elif has_runs and has_balls:
            tr = group["runs"].sum()
            tb = group["balls_faced"].sum()
            entry["par_sr"] = round(float(tr / tb * 100), 2) if tb > 0 else None
        else:
            entry["par_sr"] = None

        if has_fours and has_sixes and has_balls:
            tf = group["fours"].fillna(0).sum()
            ts = group["sixes"].fillna(0).sum()
            tb = group["balls_faced"].fillna(0).sum()
            entry["boundary_rate"] = (
                round(float((tf + ts) / tb * 100), 2) if tb > 0 else None
            )
        else:
            entry["boundary_rate"] = None

        if has_dots and has_balls:
            td = group["dots"].fillna(0).sum()
            tb = group["balls_faced"].fillna(0).sum()
            entry["dot_pct"] = round(float(td / tb * 100), 2) if tb > 0 else None
        else:
            entry["dot_pct"] = None

        results.append(entry)

    if not results:
        return []

    results.sort(key=lambda x: x["year"])

    # Compute multiplier relative to latest year
    latest_par_sr = None
    for e in reversed(results):
        if e.get("par_sr") is not None:
            latest_par_sr = e["par_sr"]
            break

    for e in results:
        if latest_par_sr and latest_par_sr > 0 and e.get("par_sr") and e["par_sr"] > 0:
            e["multiplier"] = round(latest_par_sr / e["par_sr"], 3)
        else:
            e["multiplier"] = None

    return results


# ── Venue export helpers ──────────────────────────────────────────


def build_venue_list(store: DataStore) -> list[dict]:
    """Build the venue list from venue baselines."""
    if store.venue.empty:
        return []

    venues = []
    for _, row in store.venue.iterrows():
        venues.append(
            {
                "venue": _safe_str(_get_val(row, "venue", "")),
                "matches": _safe_int(_get_val(row, "matches", 0)) or 0,
                "avg_par_sr": _safe_float(
                    _get_val(row, "avg_par_sr", _get_val(row, "par_sr"))
                ),
                "boundary_rate": _safe_float(_get_val(row, "boundary_rate")),
                "dot_pct": _safe_float(_get_val(row, "dot_pct")),
                "difficulty_score": _safe_float(_get_val(row, "difficulty_score")),
            }
        )

    return venues


# ── Main export orchestrator ──────────────────────────────────────


def export_static(
    store: DataStore,
    search_index: TrigramIndex,
    output_dir: Path,
    dry_run: bool = False,
    limit: int | None = None,
    verbose: bool = True,
) -> dict:
    """Export all API responses as static JSON files.

    Parameters
    ----------
    store : DataStore
        Loaded pipeline data.
    search_index : TrigramIndex
        Built search index.
    output_dir : Path
        Directory to write JSON files to.
    dry_run : bool
        If True, don't write files — just calculate sizes.
    limit : int or None
        Limit the number of players to export (for testing).
    verbose : bool
        Print progress messages.

    Returns
    -------
    dict
        Statistics about the export (file count, total size, etc.).
    """
    stats = {
        "files_written": 0,
        "total_bytes": 0,
        "errors": 0,
        "skipped": 0,
    }

    def _write(path: str, data: Any) -> None:
        """Write a JSON file and update stats."""
        try:
            filepath = output_dir / path
            size = write_json(filepath, data, dry_run=dry_run)
            stats["files_written"] += 1
            stats["total_bytes"] += size
            if verbose and stats["files_written"] % 100 == 0:
                print(f"  ... {stats['files_written']} files written")
        except Exception as exc:
            stats["errors"] += 1
            if verbose:
                print(f"  [ERR] {path}: {exc}")

    t0 = time.perf_counter()

    # ── 1. Health & Meta ──────────────────────────────────────
    if verbose:
        print("Exporting health & meta...")

    _write(
        "health.json",
        {"status": "ok", "mode": "static"},
    )

    countries = get_all_countries(store)
    archetypes = get_all_archetypes(store)

    _write(
        "meta.json",
        {
            "status": "ok",
            "total_batters": len(store.bat_careers),
            "total_bowlers": len(store.bowl_careers),
            "total_matchups": len(store.matchups),
            "total_venues": len(store.venue),
            "countries": countries,
            "archetypes": archetypes,
        },
    )

    _write("countries.json", countries)
    _write("archetypes.json", archetypes)

    # ── 2. Search index ───────────────────────────────────────
    if verbose:
        print("Exporting search index...")

    all_players: list[dict] = []

    # Batting players
    bat_count = 0
    for _, row in store.bat_careers.iterrows():
        if limit and bat_count >= limit:
            break
        summary = build_player_summary(row, "bat")
        if summary.get("id"):
            all_players.append(summary)
            bat_count += 1

    # Bowling players
    bowl_count = 0
    for _, row in store.bowl_careers.iterrows():
        if limit and bowl_count >= limit:
            break
        summary = build_player_summary(row, "bowl")
        if summary.get("id"):
            all_players.append(summary)
            bowl_count += 1

    _write("search/index.json", {"results": all_players, "total": len(all_players)})

    # ── 3. Rankings ───────────────────────────────────────────
    if verbose:
        print("Exporting rankings...")

    # Batting leaderboard (sorted by overall_score desc)
    bat_rankings = []
    if not store.bat_careers.empty:
        sort_col = (
            "overall_score" if "overall_score" in store.bat_careers.columns else None
        )
        bat_df = store.bat_careers
        if sort_col:
            bat_df = bat_df.sort_values(sort_col, ascending=False, na_position="last")
        for _, row in bat_df.iterrows():
            bat_rankings.append(build_player_summary(row, "bat"))

    _write(
        "rankings/bat.json",
        {
            "players": bat_rankings,
            "total": len(bat_rankings),
            "page": 1,
            "per_page": len(bat_rankings),
            "total_pages": 1,
        },
    )

    # Bowling leaderboard
    bowl_rankings = []
    if not store.bowl_careers.empty:
        sort_col = (
            "overall_score" if "overall_score" in store.bowl_careers.columns else None
        )
        bowl_df = store.bowl_careers
        if sort_col:
            bowl_df = bowl_df.sort_values(sort_col, ascending=False, na_position="last")
        for _, row in bowl_df.iterrows():
            bowl_rankings.append(build_player_summary(row, "bowl"))

    _write(
        "rankings/bowl.json",
        {
            "players": bowl_rankings,
            "total": len(bowl_rankings),
            "page": 1,
            "per_page": len(bowl_rankings),
            "total_pages": 1,
        },
    )

    # Sort column metadata
    bat_sort_cols = [
        c
        for c in store.bat_careers.columns
        if c.startswith("score_")
        or c
        in (
            "overall_score",
            "career_sr",
            "career_avg",
            "total_runs",
            "innings_count",
            "war_batting",
            "clutch_index",
            "chase_master_index",
            "flat_track_index",
        )
    ]
    bowl_sort_cols = [
        c
        for c in store.bowl_careers.columns
        if c.startswith("score_")
        or c
        in (
            "overall_score",
            "career_economy",
            "career_sr_bowl",
            "total_wickets",
            "war_bowling",
            "clutch_index_bowl",
            "flat_track_index_bowl",
        )
    ]

    _write("rankings/bat/columns.json", bat_sort_cols)
    _write("rankings/bowl/columns.json", bowl_sort_cols)

    # ── 4. Player profiles ────────────────────────────────────
    if verbose:
        print(
            f"Exporting player profiles (batters: {bat_count}, bowlers: {bowl_count})..."
        )

    exported_bat_ids: set[str] = set()
    idx = 0
    for _, row in store.bat_careers.iterrows():
        if limit and idx >= limit:
            break

        player_id = _safe_str(_get_val(row, "batter_id", ""))
        if not player_id:
            stats["skipped"] += 1
            continue

        player_name = _safe_str(_get_val(row, "batter_name", _get_val(row, "name", "")))
        exported_bat_ids.add(player_id)

        # Full profile
        profile = build_batter_profile(row)
        _write(f"player/{player_id}.json", profile)
        _write(f"player/{player_id}/batting.json", profile)

        # Innings log
        innings_df, innings_total = get_batter_innings(
            store, player_id, page=1, per_page=10000
        )
        innings_list = _df_to_list(innings_df)
        for inn in innings_list:
            if "date" in inn and inn["date"] is not None:
                inn["date"] = str(inn["date"])[:10]
        _write(
            f"player/{player_id}/innings.json",
            {
                "innings": innings_list,
                "total": innings_total,
                "page": 1,
                "per_page": innings_total or 10000,
                "total_pages": 1,
            },
        )

        # Form time-series
        form_df = get_batter_form(store, player_id)
        form_data = build_form_response(player_id, player_name, form_df)
        _write(f"player/{player_id}/form.json", form_data)

        # Matchups
        matchups_df = get_matchups_for_batter(store, player_id, min_balls=6)
        matchup_list = build_matchup_list(matchups_df, "bowler_id", "bowler_name")
        _write(
            f"player/{player_id}/matchups.json",
            {
                "matchups": matchup_list,
                "total": len(matchup_list),
                "page": 1,
                "per_page": len(matchup_list) or 1000,
            },
        )

        # Similarity
        sim_df = get_batter_similarities(store, player_id)
        sim_data = build_similarity_response(
            player_id, player_name, sim_df, store, "bat"
        )
        _write(f"player/{player_id}/similar.json", sim_data)
        _write(f"similar/{player_id}.json", sim_data)

        idx += 1

    # Bowling profiles
    idx = 0
    for _, row in store.bowl_careers.iterrows():
        if limit and idx >= limit:
            break

        player_id = _safe_str(_get_val(row, "bowler_id", ""))
        if not player_id:
            stats["skipped"] += 1
            continue

        player_name = _safe_str(_get_val(row, "bowler_name", _get_val(row, "name", "")))

        profile = build_bowler_profile(row)

        # If we already exported a batter profile for this ID, don't overwrite
        # the main player file — but do write the bowling-specific one
        if player_id not in exported_bat_ids:
            _write(f"player/{player_id}.json", profile)

        _write(f"player/{player_id}/bowling.json", profile)

        # Spells log
        spells_df, spells_total = get_bowler_spells(
            store, player_id, page=1, per_page=10000
        )
        spells_list = _df_to_list(spells_df)
        for spell in spells_list:
            if "date" in spell and spell["date"] is not None:
                spell["date"] = str(spell["date"])[:10]
        _write(
            f"player/{player_id}/spells.json",
            {
                "spells": spells_list,
                "total": spells_total,
                "page": 1,
                "per_page": spells_total or 10000,
                "total_pages": 1,
            },
        )

        # Form time-series
        form_df = get_bowler_form(store, player_id)
        form_data = build_form_response(player_id, player_name, form_df)
        _write(f"player/{player_id}/form.json", form_data)

        # Matchups
        matchups_df = get_matchups_for_bowler(store, player_id, min_balls=6)
        matchup_list = build_matchup_list(matchups_df, "batter_id", "batter_name")
        _write(
            f"player/{player_id}/matchups.json",
            {
                "matchups": matchup_list,
                "total": len(matchup_list),
                "page": 1,
                "per_page": len(matchup_list) or 1000,
            },
        )

        # Similarity
        sim_df = get_bowler_similarities(store, player_id)
        sim_data = build_similarity_response(
            player_id, player_name, sim_df, store, "bowl"
        )
        if player_id not in exported_bat_ids:
            _write(f"player/{player_id}/similar.json", sim_data)
            _write(f"similar/{player_id}.json", sim_data)

        idx += 1

    # ── 5. Venues ─────────────────────────────────────────────
    if verbose:
        print("Exporting venues...")

    venue_list = build_venue_list(store)
    _write("venues/index.json", {"venues": venue_list})

    # Individual venue files
    for venue_data in venue_list:
        venue_name = venue_data.get("venue", "")
        if not venue_name:
            continue
        # Sanitise venue name for filesystem
        safe_name = (
            venue_name.replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
            .replace(" ", "_")
        )
        safe_name = safe_name[:100]  # Limit length

        # Get venue detail (just the baseline row for now)
        _write(f"venues/{safe_name}.json", venue_data)

    # Venue summary
    _write("venues/summary.json", {"venues": venue_list})

    # ── 6. Eras ───────────────────────────────────────────────
    if verbose:
        print("Exporting eras...")

    era_baselines = compute_era_baselines(store)
    _write("eras/index.json", {"baselines": era_baselines})

    # ── 7. Top-level endpoints for specific API routes ────────
    # The frontend in static mode can map /api/X → /api/X.json
    # So we also write a few convenience aliases.

    _write(
        "rankings/top/bat.json",
        {
            "players": bat_rankings[:10] if bat_rankings else [],
            "role": "bat",
            "metric": "overall_score",
        },
    )

    _write(
        "rankings/top/bowl.json",
        {
            "players": bowl_rankings[:10] if bowl_rankings else [],
            "role": "bowl",
            "metric": "overall_score",
        },
    )

    # ── Done ──────────────────────────────────────────────────
    elapsed = time.perf_counter() - t0
    stats["elapsed_seconds"] = round(elapsed, 2)
    stats["total_mb"] = round(stats["total_bytes"] / (1024 * 1024), 2)

    return stats


# ── CLI entry point ───────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Export Cricket Metrics API responses as static JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Full export to frontend public directory:
    python export_static.py --output ../frontend/public/api/

    # Dry run to see file count and total size:
    python export_static.py --output /tmp/api --dry-run

    # Limit to 50 players for quick testing:
    python export_static.py --output ../frontend/public/api/ --limit 50

    # Custom pipeline output directory:
    python export_static.py --output ../frontend/public/api/ --pipeline-output /data/output
        """,
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        required=True,
        help="Output directory for static JSON files",
    )
    parser.add_argument(
        "--pipeline-output",
        type=str,
        default=None,
        help="Path to pipeline output directory (default: OUTPUT_DIR env or ../../output)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate sizes without writing files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of players to export (for testing)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress messages",
    )

    args = parser.parse_args()
    output_dir = Path(args.output)
    verbose = not args.quiet

    if verbose:
        print("=" * 60)
        print("  Cricket Metrics — Static JSON Export")
        print("=" * 60)
        print()

    # Resolve pipeline output directory
    pipeline_dir = args.pipeline_output or os.environ.get("OUTPUT_DIR")

    if verbose:
        print(f"Loading pipeline data from: {pipeline_dir or '(default)'}")

    store = load_data(pipeline_dir)

    if not store.loaded:
        print(f"\n❌ ERROR: Could not load pipeline data from {store.output_dir}")
        print("   Make sure the pipeline has been run and OUTPUT_DIR is set correctly.")
        sys.exit(1)

    if verbose:
        print(f"\nBuilding search index...")

    search_index = build_search_index(store)

    if verbose:
        print(f"  Search index: {search_index.size:,} players")
        print()
        if args.dry_run:
            print(f"DRY RUN — no files will be written")
        print(f"Output directory: {output_dir}")
        if args.limit:
            print(f"Player limit: {args.limit}")
        print()

    stats = export_static(
        store=store,
        search_index=search_index,
        output_dir=output_dir,
        dry_run=args.dry_run,
        limit=args.limit,
        verbose=verbose,
    )

    if verbose:
        print()
        print("=" * 60)
        print(f"  Export {'(dry run) ' if args.dry_run else ''}complete!")
        print(f"  Files:    {stats['files_written']:,}")
        print(f"  Size:     {stats['total_mb']:.1f} MB")
        print(f"  Errors:   {stats['errors']}")
        print(f"  Skipped:  {stats['skipped']}")
        print(f"  Time:     {stats['elapsed_seconds']:.1f}s")
        print("=" * 60)

        if not args.dry_run:
            print()
            print(f"Static API files written to: {output_dir}")
            print()
            print("To use with the frontend in static mode:")
            print(f"  1. Set VITE_STATIC_MODE=true in your .env")
            print(f"  2. cd gui/frontend && npm run build")
            print(f"  3. Deploy the dist/ directory to your static host")


if __name__ == "__main__":
    main()
