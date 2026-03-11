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

# Valid format keys
VALID_FORMATS = ("t20i", "ipl")
DEFAULT_FORMAT = "t20i"

# ── Project root (two levels up from gui/backend/) ────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Data root override (for Docker / non-standard layouts) ────────
# When DATA_ROOT is set, format output dirs are resolved relative to it
# instead of _PROJECT_ROOT.  This avoids issues in Docker where the
# backend code lives at /app/ but _PROJECT_ROOT resolves to /.
#
# Fallback search order for output_<fmt>/:
#   1. $DATA_ROOT/output_<fmt>/          (explicit override)
#   2. $PROJECT_ROOT/output_<fmt>/       (normal dev layout)
#   3. $CWD/output_<fmt>/               (Docker: WORKDIR /app with volumes)
#   4. $CWD/../output_<fmt>/            (Docker: backend at /app, data at /output_*)
_DATA_ROOT = Path(os.environ["DATA_ROOT"]) if os.environ.get("DATA_ROOT") else None


def _resolve_output_dir() -> Path:
    """Resolve the pipeline output directory from env or default."""
    env = os.environ.get("OUTPUT_DIR")
    if env:
        return Path(env)
    # Default: ../../output relative to this file (gui/backend/ -> project root/output)
    return _PROJECT_ROOT / "output"


def _resolve_format_output_dir(fmt: str) -> Path:
    """Resolve the output directory for a specific format.

    Checks (in order):
    1. ``$DATA_ROOT/output_{fmt}/``       (explicit env override)
    2. ``$PROJECT_ROOT/output_{fmt}/``    (normal dev layout: ../../output_t20i)
    3. ``$CWD/output_{fmt}/``            (Docker WORKDIR with volumes)
    4. ``$CWD/../output_{fmt}/``         (alternative Docker layout)
    5. ``$PROJECT_ROOT/output/``         (legacy fallback, t20i only)
    """
    dirname = f"output_{fmt}"
    cwd = Path.cwd()

    candidates: list[Path] = []

    # 1. Explicit DATA_ROOT
    if _DATA_ROOT is not None:
        candidates.append(_DATA_ROOT / dirname)

    # 2. Project root (normal dev layout)
    candidates.append(_PROJECT_ROOT / dirname)

    # 3. Current working directory (Docker: WORKDIR /app with volumes at /app/output_*)
    candidates.append(cwd / dirname)

    # 4. One level up from CWD (Docker: backend at /app, data at /output_*)
    candidates.append(cwd.parent / dirname)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Legacy fallback: the old ``output/`` directory (only makes sense for t20i)
    if fmt == DEFAULT_FORMAT:
        legacy_candidates = [_PROJECT_ROOT / "output", cwd / "output"]
        if _DATA_ROOT is not None:
            legacy_candidates.insert(0, _DATA_ROOT / "output")
        for legacy in legacy_candidates:
            if legacy.exists():
                return legacy

    # Return the first candidate so load_data() can report it as missing
    return candidates[0]


@dataclass
class DataStore:
    """In-memory store for all pipeline outputs.

    Each attribute is a pandas DataFrame (or None if the source file
    was missing — the backend degrades gracefully).
    """

    # Career-level aggregates
    bat_careers: pd.DataFrame = field(default_factory=pd.DataFrame)
    bowl_careers: pd.DataFrame = field(default_factory=pd.DataFrame)

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
        environment variable or the default ``../../output``.

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
    if store.bat_form.empty:
        return pd.DataFrame()
    mask = store.bat_form["batter_id"] == batter_id
    subset = store.bat_form.loc[mask]
    if subset.empty:
        return pd.DataFrame()
    return subset.sort_values("date")


def get_bowler_form(store: DataStore, bowler_id: str) -> pd.DataFrame:
    """Get the form time-series for a bowler, sorted by date."""
    if store.bowl_form.empty:
        return pd.DataFrame()
    mask = store.bowl_form["bowler_id"] == bowler_id
    subset = store.bowl_form.loc[mask]
    if subset.empty:
        return pd.DataFrame()
    return subset.sort_values("date")


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
    """Holds one `DataStore` per cricket format (e.g. T20I, IPL).

    The backend loads all available formats at startup and selects the
    active store based on a ``?format=`` query parameter.
    """

    stores: dict[str, DataStore] = field(default_factory=dict)

    # ── Accessors ─────────────────────────────────────────────

    def get(self, fmt: str) -> DataStore:
        """Return the DataStore for *fmt*, falling back to default."""
        fmt = fmt.lower()
        if fmt in self.stores:
            return self.stores[fmt]
        return self.stores.get(DEFAULT_FORMAT, DataStore())

    @property
    def available_formats(self) -> list[str]:
        """Return the list of formats that loaded successfully."""
        return [k for k, v in self.stores.items() if v.loaded]

    @property
    def default(self) -> DataStore:
        """Shortcut for the default (T20I) store."""
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
        out_dir = _resolve_format_output_dir(fmt)
        print(f"\n{'─' * 50}")
        print(f"  Loading format: {fmt.upper()}  ({out_dir})")
        print(f"{'─' * 50}")

        if not out_dir.exists():
            print(f"  [SKIP] Output directory not found: {out_dir}")
            continue

        store = load_data(out_dir)
        if store.loaded:
            multi.stores[fmt] = store
            print(
                f"  ✅ {fmt.upper()} loaded — "
                f"{len(store.bat_careers):,} batters, "
                f"{len(store.bowl_careers):,} bowlers"
            )
        else:
            print(f"  ⚠️  {fmt.upper()} failed to load from {out_dir}")

    if not multi.stores:
        # Last-ditch: try the legacy ``output/`` dir as t20i
        print("\n  [FALLBACK] No format-specific dirs found, trying legacy output/")
        legacy = _PROJECT_ROOT / "output"
        if legacy.exists():
            store = load_data(legacy)
            if store.loaded:
                multi.stores[DEFAULT_FORMAT] = store

    print(f"\n  Available formats: {multi.available_formats}")
    return multi
