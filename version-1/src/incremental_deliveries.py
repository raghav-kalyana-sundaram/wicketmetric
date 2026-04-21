"""
Incremental Cricsheet ingestion — reuse parsed deliveries, only parse new JSON files.

The full pipeline still runs xR / context / ratings on the *combined* delivery table so
models stay consistent. We only skip re-parsing JSON for match_ids already present in
``<output_dir>/.cache/deliveries_pre_xr.parquet`` (written after each successful parse step).

Updated Cricsheet files for an existing ``match_id`` are picked up (same stem) because we
``drop_duplicates(..., keep="last")`` after concat.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from src.parser import list_cricsheet_json_files, parse_match_files

DELIVERIES_CACHE_REL = Path(".cache") / "deliveries_pre_xr.parquet"


@dataclass(frozen=True)
class IncrementalDeliveryOutcome:
    kind: Literal["merged", "no_new", "need_full_parse"]
    """merged: concat cache + new JSON. no_new: nothing to do. need_full_parse: no cache."""


def deliveries_cache_path(output_dir: str) -> Path:
    return Path(output_dir) / DELIVERIES_CACHE_REL


def save_deliveries_cache(output_dir: str, df: pd.DataFrame) -> None:
    """Persist pre–step-1b deliveries for the next incremental run."""
    path = deliveries_cache_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Strip categoricals for stable parquet round-trip across versions
    df_out = df.copy()
    for c in df_out.columns:
        if isinstance(df_out[c].dtype, pd.CategoricalDtype):
            df_out[c] = df_out[c].astype(str)
    df_out.to_parquet(path, index=False, compression="snappy")


def merge_new_deliveries_if_possible(
    data_dir: str,
    output_dir: str,
    max_workers: int | None = None,
) -> tuple[IncrementalDeliveryOutcome, pd.DataFrame | None, list[dict] | None]:
    """
    If a deliveries cache exists, parse only JSON files whose ``match_id`` (stem) is not
    in the cache, merge with the cache, and return ``(outcome, df, match_infos)``.

    * ``no_new`` → *df* and *match_infos* are ``None``.
    * ``need_full_parse`` → *df* is ``None`` (caller runs ``parse_all_matches``).
    * ``merged`` → populated *df* and *match_infos* (infos list covers new files only).
    """
    os.makedirs(output_dir, exist_ok=True)
    cache_path = deliveries_cache_path(output_dir)
    json_files = list_cricsheet_json_files(data_dir)
    if not json_files:
        raise RuntimeError(f"No JSON match files under {data_dir!r}")

    if not cache_path.is_file():
        return IncrementalDeliveryOutcome(kind="need_full_parse"), None, None

    df_old = pd.read_parquet(cache_path)
    if "match_id" not in df_old.columns:
        return IncrementalDeliveryOutcome(kind="need_full_parse"), None, None

    known = set(df_old["match_id"].astype(str).str.strip().unique())
    new_paths = [p for p in json_files if p.stem not in known]
    if not new_paths:
        print(
            f"  Incremental: 0 new match files vs {cache_path.name} "
            f"({len(json_files):,} on disk, all already in cache)."
        )
        return IncrementalDeliveryOutcome(kind="no_new"), None, None

    print(
        f"  Incremental: parsing {len(new_paths):,} new/changed JSON files "
        f"(skipping {len(json_files) - len(new_paths):,} unchanged)."
    )
    df_new, infos_new = parse_match_files(new_paths, max_workers=max_workers)

    df = pd.concat([df_old, df_new], ignore_index=True, sort=True)
    dedupe_subset = [c for c in ("match_id", "innings_num", "over", "ball_idx") if c in df.columns]
    if len(dedupe_subset) >= 2:
        df = df.drop_duplicates(subset=dedupe_subset, keep="last")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df.sort_values(
        ["date", "match_id", "innings_num", "over", "ball_idx"],
        inplace=True,
        na_position="last",
    )
    df.reset_index(drop=True, inplace=True)

    return IncrementalDeliveryOutcome(kind="merged"), df, infos_new
