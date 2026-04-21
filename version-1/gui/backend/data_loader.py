"""
Data Loader — reads all pipeline Parquet/CSV outputs into memory at startup.

Provides a singleton `DataStore` that holds pandas DataFrames and is
injected into FastAPI route handlers via dependency injection.

Also provides `MultiDataStore` for loading multiple formats (e.g. T20I + IPL)
side-by-side, selectable via a `?format=` query parameter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Valid format keys (under a single ``output/`` root by default)
VALID_FORMATS = ("mens_t20i", "womens_t20i", "mens_ipl", "womens_ipl")
DEFAULT_FORMAT = "mens_t20i"

_LEGACY_FORMAT_ALIASES: dict[str, tuple[str, ...]] = {
    "mens_t20i": ("t20i",),
    "mens_ipl": ("ipl",),
}


def active_recency_days_for_format(fmt: str) -> int:
    """How recent a player's last match must be to count as *active* for this dataset.

    International T20: ~1 year. Franchise leagues: ~2 years (seasons span longer).
    """
    f = str(fmt).lower()
    if f in ("mens_ipl", "womens_ipl"):
        return 730
    return 365


def activity_reference_cutoff(store: "DataStore", fmt: str) -> pd.Timestamp:
    """Latest date before which a player is treated as *inactive* for ``activity=active``.

    Normally this is *today* minus the format recency window. If the loaded snapshot
    is older than that (static Parquet export), the cutoff is anchored to the end of
    coverage (max ``last_match_date`` in the slice) so leaderboards are not empty.
    """
    days = active_recency_days_for_format(fmt)
    wall = pd.Timestamp.now(tz=None).normalize() - pd.Timedelta(days=days)
    chunks: list[pd.Series] = []
    for df in (store.bat_careers, store.bowl_careers):
        if df is None or df.empty or "last_match_date" not in df.columns:
            continue
        chunks.append(pd.to_datetime(df["last_match_date"], errors="coerce"))
    if not chunks:
        return wall
    data_max = pd.concat(chunks, ignore_index=True).max()
    if pd.isna(data_max):
        return wall
    if data_max.normalize() < wall:
        return data_max - pd.Timedelta(days=days)
    return wall


def _attach_form_composite_rollups(store: DataStore) -> None:
    """Merge max/latest ``window_composite`` from form series onto career tables.

    Used for display ratings (ceiling = max ever in form; current = latest window).
    """
    if not store.bat_careers.empty:
        store.bat_careers = store.bat_careers.drop(
            columns=["form_composite_max", "form_composite_latest"],
            errors="ignore",
        )
    if not store.bowl_careers.empty:
        store.bowl_careers = store.bowl_careers.drop(
            columns=["form_composite_max", "form_composite_latest"],
            errors="ignore",
        )

    if (
        not store.bat_form.empty
        and "window_composite" in store.bat_form.columns
        and "batter_id" in store.bat_form.columns
    ):
        bf = store.bat_form.copy()
        if "date" in bf.columns:
            bf = bf.dropna(subset=["date"]).sort_values("date")
        mx = (
            bf.groupby("batter_id", observed=True)["window_composite"]
            .max()
            .reset_index(name="form_composite_max")
        )
        last_rows = bf.groupby("batter_id", observed=True).last().reset_index()
        latest = last_rows[["batter_id", "window_composite"]].rename(
            columns={"window_composite": "form_composite_latest"}
        )
        roll = mx.merge(latest, on="batter_id", how="left")
        if not store.bat_careers.empty:
            store.bat_careers = store.bat_careers.merge(roll, on="batter_id", how="left")

        for attr in ("bat_careers_ctx_entry_early", "bat_careers_ctx_entry_death"):
            cdf = getattr(store, attr, None)
            if cdf is None or cdf.empty:
                continue
            cdf = cdf.drop(
                columns=["form_composite_max", "form_composite_latest"],
                errors="ignore",
            )
            cdf = cdf.merge(roll, on="batter_id", how="left")
            setattr(store, attr, cdf)

    if (
        not store.bowl_form.empty
        and "window_composite" in store.bowl_form.columns
        and "bowler_id" in store.bowl_form.columns
    ):
        bf = store.bowl_form.copy()
        if "date" in bf.columns:
            bf = bf.dropna(subset=["date"]).sort_values("date")
        mx = (
            bf.groupby("bowler_id", observed=True)["window_composite"]
            .max()
            .reset_index(name="form_composite_max")
        )
        last_rows_b = bf.groupby("bowler_id", observed=True).last().reset_index()
        latest_b = last_rows_b[["bowler_id", "window_composite"]].rename(
            columns={"window_composite": "form_composite_latest"}
        )
        roll_b = mx.merge(latest_b, on="bowler_id", how="left")
        if not store.bowl_careers.empty:
            store.bowl_careers = store.bowl_careers.merge(
                roll_b, on="bowler_id", how="left"
            )


def _collapse_duplicate_team_label(s: str) -> str:
    """Remove accidental doubled franchise names (e.g. 'Mumbai Indians Mumbai Indians')."""
    t = s.strip()
    if len(t) < 6:
        return t
    n = len(t)
    for cut in range(min(n // 2, 80), 2, -1):
        prefix = t[:cut].rstrip()
        if len(prefix) < 3:
            continue
        rest = t[cut:].lstrip()
        if rest.startswith(prefix):
            return prefix
        if rest.startswith(prefix + " "):
            return prefix
    parts = t.split()
    if len(parts) >= 4:
        for k in range(len(parts) // 2, 0, -1):
            left = " ".join(parts[:k])
            right = " ".join(parts[k:])
            if right.startswith(left):
                return left
    return t


def _normalize_recent_team_value(v: object) -> str | None:
    """Stringify team name from innings/spell rows; None if missing."""
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "<na>"):
        return None
    return _collapse_duplicate_team_label(s)


def _attach_recent_teams(store: DataStore) -> None:
    """Add ``recent_team`` — side played for in their most recent game (by date).

    Batters: ``batting_team`` from latest batting innings.
    Bowlers: ``bowling_team`` from latest spell.
    """
    if not store.bat_careers.empty:
        store.bat_careers = store.bat_careers.drop(columns=["recent_team"], errors="ignore")
    if not store.bowl_careers.empty:
        store.bowl_careers = store.bowl_careers.drop(columns=["recent_team"], errors="ignore")

    if (
        not store.bat_innings.empty
        and "batter_id" in store.bat_innings.columns
        and "date" in store.bat_innings.columns
        and "batting_team" in store.bat_innings.columns
    ):
        inn = store.bat_innings.dropna(subset=["date", "batter_id"]).copy()
        inn = inn.sort_values(["batter_id", "date"], ascending=[True, False])
        firsts = inn.groupby("batter_id", sort=False).head(1)
        rt = firsts[["batter_id", "batting_team"]].rename(
            columns={"batting_team": "recent_team"}
        )
        rt["recent_team"] = rt["recent_team"].map(_normalize_recent_team_value)
        if not store.bat_careers.empty:
            bc = store.bat_careers.copy()
            bc["batter_id"] = bc["batter_id"].astype(str)
            rt["batter_id"] = rt["batter_id"].astype(str)
            store.bat_careers = bc.merge(rt, on="batter_id", how="left")

    if (
        not store.bowl_spells.empty
        and "bowler_id" in store.bowl_spells.columns
        and "date" in store.bowl_spells.columns
        and "bowling_team" in store.bowl_spells.columns
    ):
        sp = store.bowl_spells.dropna(subset=["date", "bowler_id"]).copy()
        sp = sp.sort_values(["bowler_id", "date"], ascending=[True, False])
        firsts_b = sp.groupby("bowler_id", sort=False).head(1)
        rt_b = firsts_b[["bowler_id", "bowling_team"]].rename(
            columns={"bowling_team": "recent_team"}
        )
        rt_b["recent_team"] = rt_b["recent_team"].map(_normalize_recent_team_value)
        if not store.bowl_careers.empty:
            boc = store.bowl_careers.copy()
            boc["bowler_id"] = boc["bowler_id"].astype(str)
            rt_b["bowler_id"] = rt_b["bowler_id"].astype(str)
            store.bowl_careers = boc.merge(rt_b, on="bowler_id", how="left")

    # Recent team on context-sliced batting careers (match full-career display)
    if (
        not store.bat_careers.empty
        and "recent_team" in store.bat_careers.columns
    ):
        rt_full = store.bat_careers[["batter_id", "recent_team"]].drop_duplicates(
            subset=["batter_id"]
        )
        for attr in ("bat_careers_ctx_entry_early", "bat_careers_ctx_entry_death"):
            cdf = getattr(store, attr, None)
            if cdf is None or cdf.empty:
                continue
            cdf = cdf.drop(columns=["recent_team"], errors="ignore")
            cdf["batter_id"] = cdf["batter_id"].astype(str)
            rtm = rt_full.copy()
            rtm["batter_id"] = rtm["batter_id"].astype(str)
            setattr(store, attr, cdf.merge(rtm, on="batter_id", how="left"))


def _attach_last_match_dates(store: DataStore) -> None:
    """Add ``last_match_date`` to career tables from innings / spell detail."""
    if not store.bat_careers.empty:
        store.bat_careers = store.bat_careers.drop(
            columns=["last_match_date"], errors="ignore"
        )
        if (
            not store.bat_innings.empty
            and "batter_id" in store.bat_innings.columns
            and "date" in store.bat_innings.columns
        ):
            lm = (
                store.bat_innings.groupby("batter_id", as_index=False)["date"]
                .max()
                .rename(columns={"date": "last_match_date"})
            )
            store.bat_careers = store.bat_careers.merge(lm, on="batter_id", how="left")
        else:
            c = store.bat_careers.copy()
            c["last_match_date"] = pd.NaT
            store.bat_careers = c

    if not store.bowl_careers.empty:
        store.bowl_careers = store.bowl_careers.drop(
            columns=["last_match_date"], errors="ignore"
        )
        if (
            not store.bowl_spells.empty
            and "bowler_id" in store.bowl_spells.columns
            and "date" in store.bowl_spells.columns
        ):
            lm = (
                store.bowl_spells.groupby("bowler_id", as_index=False)["date"]
                .max()
                .rename(columns={"date": "last_match_date"})
            )
            store.bowl_careers = store.bowl_careers.merge(lm, on="bowler_id", how="left")
        else:
            c = store.bowl_careers.copy()
            c["last_match_date"] = pd.NaT
            store.bowl_careers = c

# ── Project root (two levels up from gui/backend/) ────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Data root override (for Docker / non-standard layouts) ────────
# When DATA_ROOT is set, format output dirs are resolved relative to it
# instead of _PROJECT_ROOT.  This avoids issues in Docker where the
# backend code lives at /app/ but _PROJECT_ROOT resolves to /.
#
# Fallback search order for output_<fmt>/:
#   1. $DATA_ROOT/output_<fmt>/          (explicit override)
#   2. $PROJECT_ROOT/data/output/<fmt>/ (canonical dev layout)
#   3. $PROJECT_ROOT/output_<fmt>/      (legacy)
#   4. $CWD/output_<fmt>/               (Docker: WORKDIR /app with volumes)
#   5. $CWD/../output_<fmt>/             (Docker: backend at /app, data at /output_*)
_DATA_ROOT = Path(os.environ["DATA_ROOT"]) if os.environ.get("DATA_ROOT") else None


def _resolve_output_dir() -> Path:
    """Resolve the pipeline output directory from env or default."""
    env = os.environ.get("OUTPUT_DIR")
    if env:
        return Path(env)
    # Default: project root data/output (single-folder legacy layout lives there too)
    return _PROJECT_ROOT / "data" / "output"


def _dedupe_paths_preserve_order(paths: list[Path]) -> list[Path]:
    """Drop duplicate paths (by resolved location), keep first occurrence."""
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        try:
            key = str(p.resolve())
        except (OSError, RuntimeError):
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _format_output_dir_candidates(fmt: str) -> list[Path]:
    """Ordered directories to try for *fmt* (canonical first, then legacy).

    ``load_all_data`` attempts each existing path until ``load_data`` succeeds.
    That way an empty or stale ``output/mens_t20i/`` does not block a good
    ``output_t20i/`` tree, and the same for ``output/womens_t20i`` vs
    ``output/womens_t20``.
    """
    dirname = f"output_{fmt}"
    cwd = Path.cwd()

    candidates: list[Path] = []

    # 1. DATA_ROOT: separate dirs (output_t20i, output_ipl)
    if _DATA_ROOT is not None:
        candidates.append(_DATA_ROOT / dirname)
        candidates.append(_DATA_ROOT / "output" / fmt)
        candidates.append(_DATA_ROOT / "data" / "output" / fmt)
        candidates.append(_DATA_ROOT / fmt)

    # 2. Project root (prefer data/output/<fmt>/)
    candidates.append(_PROJECT_ROOT / "data" / "output" / fmt)
    candidates.append(_PROJECT_ROOT / dirname)
    candidates.append(_PROJECT_ROOT / "output" / fmt)
    candidates.append(_PROJECT_ROOT / fmt)

    # 3. CWD
    candidates.append(cwd / "data" / "output" / fmt)
    candidates.append(cwd / dirname)
    candidates.append(cwd / "output" / fmt)
    candidates.append(cwd / fmt)

    # 4. CWD parent
    candidates.append(cwd.parent / "data" / "output" / fmt)
    candidates.append(cwd.parent / dirname)
    candidates.append(cwd.parent / "output" / fmt)
    candidates.append(cwd.parent / fmt)

    # 5. Legacy folder names (output_t20i, output/ipl, …) after canonical paths
    bases: list[Path] = []
    if _DATA_ROOT is not None:
        bases.append(_DATA_ROOT)
    bases.extend([_PROJECT_ROOT, cwd, cwd.parent])
    if fmt == "mens_t20i":
        for b in bases:
            candidates.extend([b / "output_t20i", b / "output" / "t20i"])
        for alias in _LEGACY_FORMAT_ALIASES.get("mens_t20i", ()):
            for b in bases:
                candidates.extend([b / f"output_{alias}", b / "output" / alias])
    elif fmt == "mens_ipl":
        for b in bases:
            candidates.extend([b / "output_ipl", b / "output" / "ipl"])
        for alias in _LEGACY_FORMAT_ALIASES.get("mens_ipl", ()):
            for b in bases:
                candidates.extend([b / f"output_{alias}", b / "output" / alias])
    elif fmt == "womens_t20i":
        # Older layout used output/womens_t20 (without "i")
        for b in bases:
            candidates.append(b / "data" / "output" / "womens_t20")
            candidates.append(b / "output" / "womens_t20")
            candidates.append(b / "output_womens_t20")

    # Legacy fallback: single flat output directory (treat as default men's intl slice)
    if fmt == DEFAULT_FORMAT:
        legacy_single: list[Path] = []
        if _DATA_ROOT is not None:
            legacy_single.extend(
                [_DATA_ROOT / "data" / "output", _DATA_ROOT / "output"]
            )
        legacy_single.extend(
            [
                _PROJECT_ROOT / "data" / "output",
                _PROJECT_ROOT / "output",
                cwd / "data" / "output",
                cwd / "output",
            ]
        )
        for leg in legacy_single:
            candidates.append(leg)

    return _dedupe_paths_preserve_order(candidates)


def _resolve_format_output_dir(fmt: str) -> Path:
    """First existing candidate directory for *fmt* (for diagnostics / tooling)."""
    for p in _format_output_dir_candidates(fmt):
        if p.exists():
            return p
    cands = _format_output_dir_candidates(fmt)
    return cands[0] if cands else _PROJECT_ROOT / "data" / "output" / fmt


@dataclass
class DataStore:
    """In-memory store for all pipeline outputs.

    Each attribute is a pandas DataFrame (or None if the source file
    was missing — the backend degrades gracefully).
    """

    # Career-level aggregates
    bat_careers: pd.DataFrame = field(default_factory=pd.DataFrame)
    bowl_careers: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Batting leaderboards: entry-phase re-aggregated careers (optional Parquet)
    bat_careers_ctx_entry_early: pd.DataFrame = field(default_factory=pd.DataFrame)
    bat_careers_ctx_entry_death: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Per-innings / per-spell detail
    bat_innings: pd.DataFrame = field(default_factory=pd.DataFrame)
    bowl_spells: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Form time-series (rolling window)
    bat_form: pd.DataFrame = field(default_factory=pd.DataFrame)
    bowl_form: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Player similarities (long-form top-K)
    bat_sim: pd.DataFrame = field(default_factory=pd.DataFrame)
    bowl_sim: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Head-to-head matchups
    matchups: pd.DataFrame = field(default_factory=pd.DataFrame)
    matchups_phase: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Venue baselines
    venue: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Metadata
    output_dir: Path = field(default_factory=_resolve_output_dir)
    loaded: bool = False


def max_last_match_date_iso(store: DataStore) -> str | None:
    """Latest ``last_match_date`` across batting and bowling careers (ISO yyyy-mm-dd)."""
    best_ts = None
    for df in (store.bat_careers, store.bowl_careers):
        if df is None or df.empty or "last_match_date" not in df.columns:
            continue
        s = pd.to_datetime(df["last_match_date"], errors="coerce")
        mx = s.max()
        if pd.isna(mx):
            continue
        if best_ts is None or mx > best_ts:
            best_ts = mx
    if best_ts is None:
        return None
    try:
        return best_ts.strftime("%Y-%m-%d")
    except Exception:
        return str(best_ts)[:10]


def _read_parquet_safe(path: Path) -> pd.DataFrame:
    """Read a Parquet file, returning empty DataFrame on failure."""
    if not path.exists():
        print(f"  [WARN] Missing: {path}")
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
        print(f"  [OK]   {path.name}: {df.shape[0]:,} rows × {df.shape[1]} cols")
        return df
    except Exception as exc:
        print(f"  [ERR]  {path.name}: {exc}")
        return pd.DataFrame()


def _read_csv_safe(path: Path) -> pd.DataFrame:
    """Read a CSV file, returning empty DataFrame on failure."""
    if not path.exists():
        print(f"  [WARN] Missing: {path}")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        print(f"  [OK]   {path.name}: {df.shape[0]:,} rows × {df.shape[1]} cols")
        return df
    except Exception as exc:
        print(f"  [ERR]  {path.name}: {exc}")
        return pd.DataFrame()


def _ensure_id_columns(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """Make sure the id column is a string (for consistent lookups)."""
    if id_col in df.columns:
        df[id_col] = df[id_col].astype(str)
    return df


def _add_role_column(df: pd.DataFrame, role: str) -> pd.DataFrame:
    """Add a 'role' column if not present."""
    if "role" not in df.columns:
        df = df.copy()
        df["role"] = role
    return df


def _clean_bat_careers(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise batting careers DataFrame for API consumption."""
    if df.empty:
        return df
    df = _ensure_id_columns(df, "batter_id")
    df = _add_role_column(df, "bat")

    # Ensure key columns exist with sensible defaults
    defaults = {
        "is_provisional_bat": True,
        "overall_grade": "D",
        "archetype": "Unknown",
        "country": "Unknown",
        "position_group": "unknown",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    # Fill NaN in score columns with 0
    score_cols = [c for c in df.columns if c.startswith("score_")]
    for col in score_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df


def _clean_bowl_careers(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise bowling careers DataFrame for API consumption."""
    if df.empty:
        return df
    df = _ensure_id_columns(df, "bowler_id")
    df = _add_role_column(df, "bowl")

    defaults = {
        "is_provisional_bowl": True,
        "overall_grade": "D",
        "archetype": "Unknown",
        "country": "Unknown",
        "phase_group": "unknown",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    score_cols = [c for c in df.columns if c.startswith("score_")]
    for col in score_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df


def _clean_innings(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """Normalise innings/spells detail DataFrames."""
    if df.empty:
        return df
    df = _ensure_id_columns(df, id_col)
    # Ensure date is datetime
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def load_data(output_dir: Path | str | None = None) -> DataStore:
    """Load all pipeline outputs into memory.

    Parameters
    ----------
    output_dir : Path or str, optional
        Override the output directory. If None, uses the OUTPUT_DIR
        environment variable or the default ``data/output`` under the project root.

    Returns
    -------
    DataStore
        Populated datastore ready for API use.
    """
    store = DataStore()
    if output_dir is not None:
        store.output_dir = Path(output_dir)

    d = store.output_dir
    print(f"Loading pipeline outputs from: {d}")

    if not d.exists():
        print(f"  [ERR] Output directory does not exist: {d}")
        store.loaded = False
        return store

    # ── Career-level ──────────────────────────────────────────
    store.bat_careers = _clean_bat_careers(
        _read_parquet_safe(d / "batting_careers_full.parquet")
    )
    store.bowl_careers = _clean_bowl_careers(
        _read_parquet_safe(d / "bowling_careers_full.parquet")
    )
    store.bat_careers_ctx_entry_early = _clean_bat_careers(
        _read_parquet_safe(d / "batting_careers_ctx_entry_early.parquet")
    )
    store.bat_careers_ctx_entry_death = _clean_bat_careers(
        _read_parquet_safe(d / "batting_careers_ctx_entry_death.parquet")
    )

    # ── Per-innings / per-spell detail ────────────────────────
    store.bat_innings = _clean_innings(
        _read_parquet_safe(d / "batting_innings_detail.parquet"), "batter_id"
    )
    store.bowl_spells = _clean_innings(
        _read_parquet_safe(d / "bowling_spells_detail.parquet"), "bowler_id"
    )

    # ── Form time-series ──────────────────────────────────────
    store.bat_form = _clean_innings(
        _read_parquet_safe(d / "batting_form_series.parquet"), "batter_id"
    )
    store.bowl_form = _clean_innings(
        _read_parquet_safe(d / "bowling_form_series.parquet"), "bowler_id"
    )

    # ── Similarities ──────────────────────────────────────────
    store.bat_sim = _read_parquet_safe(d / "batting_similarities.parquet")
    if not store.bat_sim.empty:
        store.bat_sim = _ensure_id_columns(store.bat_sim, "batter_id")
        if "comp_batter_id" in store.bat_sim.columns:
            store.bat_sim["comp_batter_id"] = store.bat_sim["comp_batter_id"].astype(
                str
            )

    store.bowl_sim = _read_parquet_safe(d / "bowling_similarities.parquet")
    if not store.bowl_sim.empty:
        store.bowl_sim = _ensure_id_columns(store.bowl_sim, "bowler_id")
        if "comp_bowler_id" in store.bowl_sim.columns:
            store.bowl_sim["comp_bowler_id"] = store.bowl_sim["comp_bowler_id"].astype(
                str
            )

    # ── Matchups ──────────────────────────────────────────────
    store.matchups = _read_parquet_safe(d / "matchups.parquet")
    if not store.matchups.empty:
        store.matchups = _ensure_id_columns(store.matchups, "batter_id")
        store.matchups = _ensure_id_columns(store.matchups, "bowler_id")

    store.matchups_phase = _read_parquet_safe(d / "matchups_by_phase.parquet")
    if not store.matchups_phase.empty:
        store.matchups_phase = _ensure_id_columns(store.matchups_phase, "batter_id")
        store.matchups_phase = _ensure_id_columns(store.matchups_phase, "bowler_id")

    # ── Venue baselines ───────────────────────────────────────
    store.venue = _read_parquet_safe(d / "venue_baselines.parquet")

    _attach_last_match_dates(store)
    _attach_recent_teams(store)
    _attach_form_composite_rollups(store)

    if store.bat_careers.empty and store.bowl_careers.empty:
        print(
            f"  [SKIP] No batting or bowling careers in {d} — "
            "not registering this dataset slice."
        )
        store.loaded = False
        return store

    store.loaded = True

    # Summary
    total_rows = sum(
        len(getattr(store, attr))
        for attr in [
            "bat_careers",
            "bowl_careers",
            "bat_innings",
            "bowl_spells",
            "bat_form",
            "bowl_form",
            "bat_sim",
            "bowl_sim",
            "matchups",
            "matchups_phase",
            "venue",
        ]
    )
    print(f"\nData loading complete: {total_rows:,} total rows across all DataFrames.")
    return store


# ── Helper accessors ──────────────────────────────────────────────


def get_batter_by_id(store: DataStore, batter_id: str) -> pd.Series | None:
    """Look up a single batter by ID. Returns None if not found."""
    if store.bat_careers.empty:
        return None
    mask = store.bat_careers["batter_id"] == batter_id
    matches = store.bat_careers.loc[mask]
    if matches.empty:
        return None
    return matches.iloc[0]


def get_bowler_by_id(store: DataStore, bowler_id: str) -> pd.Series | None:
    """Look up a single bowler by ID. Returns None if not found."""
    if store.bowl_careers.empty:
        return None
    mask = store.bowl_careers["bowler_id"] == bowler_id
    matches = store.bowl_careers.loc[mask]
    if matches.empty:
        return None
    return matches.iloc[0]


def get_batter_innings(
    store: DataStore,
    batter_id: str,
    page: int = 1,
    per_page: int = 25,
    sort_by: str = "date",
    order: str = "desc",
) -> tuple[pd.DataFrame, int]:
    """Get paginated innings for a batter.

    Returns (page_df, total_count).
    """
    if store.bat_innings.empty:
        return pd.DataFrame(), 0
    mask = store.bat_innings["batter_id"] == batter_id
    subset = store.bat_innings.loc[mask]
    total = len(subset)
    if total == 0:
        return pd.DataFrame(), 0

    ascending = order.lower() == "asc"
    if sort_by in subset.columns:
        subset = subset.sort_values(sort_by, ascending=ascending, na_position="last")

    start = (page - 1) * per_page
    end = start + per_page
    return subset.iloc[start:end], total


def get_bowler_spells(
    store: DataStore,
    bowler_id: str,
    page: int = 1,
    per_page: int = 25,
    sort_by: str = "date",
    order: str = "desc",
) -> tuple[pd.DataFrame, int]:
    """Get paginated spells for a bowler.

    Returns (page_df, total_count).
    """
    if store.bowl_spells.empty:
        return pd.DataFrame(), 0
    mask = store.bowl_spells["bowler_id"] == bowler_id
    subset = store.bowl_spells.loc[mask]
    total = len(subset)
    if total == 0:
        return pd.DataFrame(), 0

    ascending = order.lower() == "asc"
    if sort_by in subset.columns:
        subset = subset.sort_values(sort_by, ascending=ascending, na_position="last")

    start = (page - 1) * per_page
    end = start + per_page
    return subset.iloc[start:end], total


def get_batter_form(store: DataStore, batter_id: str) -> pd.DataFrame:
    """Get the form time-series for a batter, sorted by date."""
    if not store.bat_form.empty:
        mask = store.bat_form["batter_id"] == batter_id
        subset = store.bat_form.loc[mask]
        if not subset.empty:
            return subset.sort_values("date")
    # Fallback: build form from innings when form series parquet is missing/empty
    if store.bat_innings.empty or "date" not in store.bat_innings.columns:
        return pd.DataFrame()
    pid = str(batter_id)
    mask = store.bat_innings["batter_id"].astype(str) == pid
    inn = store.bat_innings.loc[mask].dropna(subset=["date"]).sort_values("date").tail(20)
    if inn.empty or len(inn) < 2:
        return pd.DataFrame()
    runs_col = "runs_scored" if "runs_scored" in inn.columns else "runs" if "runs" in inn.columns else None
    if runs_col is None:
        return pd.DataFrame()
    inn = inn.copy()
    # Proxy composite 0–100 from runs (50 runs -> 100)
    inn["window_composite"] = inn[runs_col].fillna(0).clip(0, 50) * 2.0
    return inn[["date", "window_composite"]]


def get_bowler_form(store: DataStore, bowler_id: str) -> pd.DataFrame:
    """Get the form time-series for a bowler, sorted by date."""
    if not store.bowl_form.empty:
        mask = store.bowl_form["bowler_id"] == bowler_id
        subset = store.bowl_form.loc[mask]
        if not subset.empty:
            return subset.sort_values("date")
    # Fallback: build form from spells when form series parquet is missing/empty
    if store.bowl_spells.empty or "date" not in store.bowl_spells.columns:
        return pd.DataFrame()
    pid = str(bowler_id)
    mask = store.bowl_spells["bowler_id"].astype(str) == pid
    sp = store.bowl_spells.loc[mask].dropna(subset=["date"]).sort_values("date").tail(20)
    if sp.empty or len(sp) < 2:
        return pd.DataFrame()
    sp = sp.copy()
    # Proxy composite 0–100: wickets * 20 (5 wkts -> 100), capped
    if "wickets" in sp.columns:
        sp["window_composite"] = sp["wickets"].fillna(0).clip(0, 5) * 20.0
    elif "economy" in sp.columns:
        sp["window_composite"] = (10 - sp["economy"].fillna(10).clip(0, 10)) * 10.0
    else:
        return pd.DataFrame()
    return sp[["date", "window_composite"]]


def _form_summary(
    form_df: "pd.DataFrame",
    *,
    date_col: str = "date",
    composite_col: str = "window_composite",
    display_years: int = 2,
    active_recency_days: int = 365,
) -> tuple[list[tuple[str, float | None]], str | None, bool]:
    """Reduce form DataFrame to last N years for display (or all if none in window).

    Returns (form_points as list of (date_str, composite), last_played_iso, active).
    ``active`` uses the true last sample date vs ``active_recency_days`` (format-specific).
    """
    if form_df.empty or date_col not in form_df.columns:
        return [], None, False
    form_df = form_df.dropna(subset=[date_col]).sort_values(date_col)
    if form_df.empty:
        return [], None, False
    now = pd.Timestamp.now(tz=None)
    cutoff_display = now - pd.Timedelta(days=365 * display_years)
    in_window = form_df.loc[form_df[date_col] >= cutoff_display]
    use_df = in_window if not in_window.empty else form_df

    def _to_float(v):
        if v is None or (hasattr(v, "__float__") and getattr(v, "__float__", None) is None):
            return None
        try:
            f = float(v)
            return None if (f != f or f == float("inf") or f == float("-inf")) else round(f, 2)
        except (TypeError, ValueError):
            return None

    form_points = []
    for i in range(len(use_df)):
        d = use_df[date_col].iloc[i]
        date_str = str(d.date()) if hasattr(d, "date") and callable(getattr(d, "date")) else str(d)[:10]
        comp = _to_float(use_df[composite_col].iloc[i]) if composite_col in use_df.columns else None
        form_points.append((date_str, comp))
    last_dt = form_df[date_col].max()
    last_played = (
        str(last_dt.date())
        if hasattr(last_dt, "date") and callable(getattr(last_dt, "date"))
        else str(last_dt)[:10]
    )
    active_cutoff = now - pd.Timedelta(days=int(active_recency_days))
    ts_last = pd.Timestamp(last_dt)
    active = bool(pd.notna(ts_last) and ts_last >= active_cutoff)
    return form_points, last_played, active


def get_batter_form_summary(
    store: DataStore, batter_id: str, *, fmt: str | None = None
) -> tuple[list[tuple[str, float | None]], str | None, bool]:
    """Form summary for leaderboard: last 2y of points for chart; active uses format recency."""
    days = active_recency_days_for_format(fmt or DEFAULT_FORMAT)
    form_df = get_batter_form(store, batter_id)
    return _form_summary(
        form_df, composite_col="window_composite", active_recency_days=days
    )


def get_bowler_form_summary(
    store: DataStore, bowler_id: str, *, fmt: str | None = None
) -> tuple[list[tuple[str, float | None]], str | None, bool]:
    """Form summary for leaderboard: last 2y of points for chart; active uses format recency."""
    days = active_recency_days_for_format(fmt or DEFAULT_FORMAT)
    form_df = get_bowler_form(store, bowler_id)
    return _form_summary(
        form_df, composite_col="window_composite", active_recency_days=days
    )


def get_batter_similarities(store: DataStore, batter_id: str) -> pd.DataFrame:
    """Get the top-K most similar batters for a given batter."""
    if store.bat_sim.empty:
        return pd.DataFrame()
    mask = store.bat_sim["batter_id"] == batter_id
    subset = store.bat_sim.loc[mask]
    if subset.empty:
        return pd.DataFrame()
    return subset.sort_values("similarity", ascending=False)


def get_bowler_similarities(store: DataStore, bowler_id: str) -> pd.DataFrame:
    """Get the top-K most similar bowlers for a given bowler."""
    if store.bowl_sim.empty:
        return pd.DataFrame()
    mask = store.bowl_sim["bowler_id"] == bowler_id
    subset = store.bowl_sim.loc[mask]
    if subset.empty:
        return pd.DataFrame()
    return subset.sort_values("similarity", ascending=False)


def get_matchups_for_batter(
    store: DataStore, batter_id: str, min_balls: int = 6
) -> pd.DataFrame:
    """All matchups for a batter, filtered by minimum balls."""
    if store.matchups.empty:
        return pd.DataFrame()
    mask = (store.matchups["batter_id"] == batter_id) & (
        store.matchups["balls_faced"] >= min_balls
    )
    return store.matchups.loc[mask].sort_values(
        "dominance_index", ascending=False, na_position="last"
    )


def get_matchups_for_bowler(
    store: DataStore, bowler_id: str, min_balls: int = 6
) -> pd.DataFrame:
    """All matchups for a bowler, filtered by minimum balls."""
    if store.matchups.empty:
        return pd.DataFrame()
    mask = (store.matchups["bowler_id"] == bowler_id) & (
        store.matchups["balls_faced"] >= min_balls
    )
    return store.matchups.loc[mask].sort_values(
        "dominance_index", ascending=True, na_position="last"
    )


def get_head_to_head(store: DataStore, batter_id: str, bowler_id: str) -> dict:
    """Get head-to-head matchup between a specific batter and bowler.

    Returns a dict with 'overall' and 'by_phase' DataFrames.
    """
    result = {"overall": pd.DataFrame(), "by_phase": pd.DataFrame()}

    if not store.matchups.empty:
        mask = (store.matchups["batter_id"] == batter_id) & (
            store.matchups["bowler_id"] == bowler_id
        )
        result["overall"] = store.matchups.loc[mask]

    if not store.matchups_phase.empty:
        mask = (store.matchups_phase["batter_id"] == batter_id) & (
            store.matchups_phase["bowler_id"] == bowler_id
        )
        result["by_phase"] = store.matchups_phase.loc[mask]

    return result


def get_all_countries(store: DataStore) -> list[str]:
    """Get sorted list of all countries present in the data."""
    countries: set[str] = set()
    if not store.bat_careers.empty and "country" in store.bat_careers.columns:
        countries.update(store.bat_careers["country"].dropna().unique())
    if not store.bowl_careers.empty and "country" in store.bowl_careers.columns:
        countries.update(store.bowl_careers["country"].dropna().unique())
    return sorted(countries)


def get_all_archetypes(store: DataStore) -> dict[str, list[str]]:
    """Get sorted lists of all archetypes, keyed by role."""
    result: dict[str, list[str]] = {"bat": [], "bowl": []}
    if not store.bat_careers.empty and "archetype" in store.bat_careers.columns:
        result["bat"] = sorted(
            store.bat_careers["archetype"].dropna().unique().tolist()
        )
    if not store.bowl_careers.empty and "archetype" in store.bowl_careers.columns:
        result["bowl"] = sorted(
            store.bowl_careers["archetype"].dropna().unique().tolist()
        )
    return result


# ── Multi-format support ──────────────────────────────────────────


@dataclass
class MultiDataStore:
    """Holds one `DataStore` per dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).

    The backend loads all available slices at startup; the client selects one
    via ``?format=``.
    """

    stores: dict[str, DataStore] = field(default_factory=dict)

    # ── Accessors ─────────────────────────────────────────────

    def get(self, fmt: str) -> DataStore:
        """Return the DataStore for *fmt*, falling back to default then any slice."""
        fmt = fmt.lower()
        if fmt in self.stores:
            return self.stores[fmt]
        if DEFAULT_FORMAT in self.stores:
            return self.stores[DEFAULT_FORMAT]
        for k in VALID_FORMATS:
            if k in self.stores:
                return self.stores[k]
        return DataStore()

    @property
    def available_formats(self) -> list[str]:
        """Return the list of formats that loaded successfully."""
        return [k for k, v in self.stores.items() if v.loaded]

    @property
    def default(self) -> DataStore:
        """Shortcut for the default (men's international T20) store."""
        return self.get(DEFAULT_FORMAT)

    def __contains__(self, fmt: str) -> bool:
        return fmt.lower() in self.stores


def load_all_data() -> MultiDataStore:
    """Load datasets for every known format into a `MultiDataStore`.

    For each format in `VALID_FORMATS`, attempts to locate and read
    the corresponding output directory (``output_{fmt}/``).  Formats
    whose output directory is missing are silently skipped — only
    successfully-loaded formats appear in ``available_formats``.

    Returns
    -------
    MultiDataStore
        Ready for injection into FastAPI route handlers.
    """
    multi = MultiDataStore()

    for fmt in VALID_FORMATS:
        print(f"\n{'─' * 50}")
        print(f"  Loading format: {fmt.upper()}")
        print(f"{'─' * 50}")

        loaded_fmt = False
        for out_dir in _format_output_dir_candidates(fmt):
            if not out_dir.exists():
                continue
            print(f"  Trying: {out_dir}")
            store = load_data(out_dir)
            if store.loaded:
                multi.stores[fmt] = store
                loaded_fmt = True
                print(
                    f"  ✅ {fmt.upper()} loaded — "
                    f"{len(store.bat_careers):,} batters, "
                    f"{len(store.bowl_careers):,} bowlers"
                )
                break
            print(f"  ⚠️  No usable careers in {out_dir}, trying next candidate…")

        if not loaded_fmt:
            print(f"  [SKIP] {fmt.upper()}: no directory with valid career tables")

    if not multi.stores:
        # Last-ditch: single flat output dir (canonical data/output, then legacy output/)
        print(
            "\n  [FALLBACK] No format-specific dirs found, "
            "trying legacy flat data/output/ then output/"
        )
        for legacy in (
            _PROJECT_ROOT / "data" / "output",
            _PROJECT_ROOT / "output",
        ):
            if legacy.exists():
                store = load_data(legacy)
                if store.loaded:
                    multi.stores[DEFAULT_FORMAT] = store
                    break

    print(f"\n  Available formats: {multi.available_formats}")
    return multi
