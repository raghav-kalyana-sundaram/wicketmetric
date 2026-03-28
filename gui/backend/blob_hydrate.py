"""
Download pipeline Parquet from Vercel Blob into a local cache before ``data_loader`` runs.

Enable by setting ``BLOB_PARQUET_BASE_URL`` to your blob store origin (public or private
hostname). For private stores, also set ``BLOB_READ_WRITE_TOKEN``. Must run *before*
``import data_loader`` so ``DATA_ROOT`` is visible when that module initializes.

Unset ``OUTPUT_DIR`` when using blob multi-format layout (same as normal multi-slice deploy).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import httpx

# Same logical names as ``data_loader.load_data`` (order does not matter).
_PARQUET_NAMES = (
    "batting_careers_full.parquet",
    "bowling_careers_full.parquet",
    "batting_careers_ctx_entry_early.parquet",
    "batting_careers_ctx_entry_death.parquet",
    "batting_innings_detail.parquet",
    "bowling_spells_detail.parquet",
    "batting_form_series.parquet",
    "bowling_form_series.parquet",
    "batting_similarities.parquet",
    "bowling_similarities.parquet",
    "matchups.parquet",
    "matchups_by_phase.parquet",
    "venue_baselines.parquet",
)

# Remote folder names on blob that should map to a canonical format key under DATA_ROOT/output/<fmt>/.
_FORMAT_REMOTE_PREFIXES: dict[str, tuple[str, ...]] = {
    "womens_t20i": ("womens_t20i", "womens_t20"),
}


def _join_url(base: str, pathname: str) -> str:
    b = base.rstrip("/")
    p = pathname.lstrip("/")
    return f"{b}/{p}"


def _pick_remote_prefix(
    client: httpx.Client,
    *,
    base_url: str,
    headers: dict[str, str],
    fmt: str,
    prefix: str,
) -> str | None:
    """Return blob path prefix (e.g. output/mens_t20i) that contains career parquet."""
    candidates = _FORMAT_REMOTE_PREFIXES.get(fmt, (fmt,))
    probe = "batting_careers_full.parquet"
    for key in candidates:
        path = f"{prefix}/{key}/{probe}"
        url = _join_url(base_url, path)
        try:
            r = client.head(url, headers=headers, follow_redirects=True, timeout=60.0)
            if r.status_code == 200:
                return f"{prefix}/{key}"
            if r.status_code == 404:
                continue
            # Some stacks may not support HEAD; try GET with range 0-0
            r2 = client.get(
                url,
                headers={**headers, "Range": "bytes=0-0"},
                follow_redirects=True,
                timeout=120.0,
            )
            if r2.status_code in (200, 206):
                return f"{prefix}/{key}"
        except httpx.HTTPError:
            continue
    return None


def _download_file(
    client: httpx.Client,
    url: str,
    dest: Path,
    headers: dict[str, str],
) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with client.stream(
            "GET", url, headers=headers, follow_redirects=True, timeout=300.0
        ) as r:
            if r.status_code == 404:
                return False
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
            tmp.replace(dest)
        return True
    except httpx.HTTPError:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def maybe_hydrate_data_root_from_blob() -> None:
    """If blob env is configured, download Parquet into a cache dir and set ``DATA_ROOT``."""
    if os.environ.get("OUTPUT_DIR"):
        # Single-dir mode uses OUTPUT_DIR literally; blob multi-layout is not applied.
        return

    base_public = os.environ.get("BLOB_PARQUET_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
    access = os.environ.get("BLOB_PARQUET_ACCESS", "public").strip().lower()
    prefix = os.environ.get("BLOB_PARQUET_PREFIX", "output").strip().strip("/")

    # Require an explicit base URL so a stray upload token in .env does not override local data.
    if not base_public:
        return

    blob_base = base_public.rstrip("/")
    headers: dict[str, str] = {}
    if ".private.blob.vercel-storage.com" in blob_base or access == "private":
        if not token:
            print(
                "[blob_hydrate] Private blob host or BLOB_PARQUET_ACCESS=private requires "
                "BLOB_READ_WRITE_TOKEN — skipping."
            )
            return
        headers["Authorization"] = f"Bearer {token}"

    cache = os.environ.get("BLOB_CACHE_DIR", "").strip()
    if cache:
        root = Path(cache)
    else:
        root = Path(os.environ.get("TMPDIR", "/tmp")) / "cricket-metrics-blob-cache"

    if os.environ.get("BLOB_CACHE_CLEAR", "").lower() in ("1", "true", "yes"):
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    # DATA_ROOT is the parent of ``output/`` (see data_loader._format_output_dir_candidates).
    out_root = root / prefix
    out_root.mkdir(parents=True, exist_ok=True)
    os.environ["DATA_ROOT"] = str(root)

    # Keep in sync with data_loader.VALID_FORMATS (avoid importing data_loader here).
    format_keys = ("mens_t20i", "womens_t20i", "mens_ipl", "womens_ipl")

    print("=" * 60)
    print("  Blob hydrate — downloading Parquet into cache")
    print(f"  Base: {blob_base}")
    print(f"  Local: {out_root}  (DATA_ROOT={root})")
    print("=" * 60)

    with httpx.Client() as client:
        for fmt in format_keys:
            remote_prefix = _pick_remote_prefix(
                client,
                base_url=blob_base,
                headers=headers,
                fmt=fmt,
                prefix=prefix,
            )
            if not remote_prefix:
                print(f"  [SKIP] {fmt}: no batting_careers_full.parquet under {prefix}/…")
                continue

            local_fmt_dir = out_root / fmt
            local_fmt_dir.mkdir(parents=True, exist_ok=True)
            n_ok = 0
            for fname in _PARQUET_NAMES:
                url = _join_url(blob_base, f"{remote_prefix}/{fname}")
                dest = local_fmt_dir / fname
                if _download_file(client, url, dest, headers):
                    n_ok += 1
            print(
                f"  [OK] {fmt}: downloaded {n_ok}/{len(_PARQUET_NAMES)} parquet file(s) "
                f"← …/{remote_prefix.split('/')[-1]}/"
            )
