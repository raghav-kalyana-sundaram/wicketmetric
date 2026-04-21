"""
Download pre-built DuckDB file from remote storage before the API connects.

Enable by setting DUCKDB_REMOTE_URL to the HTTP(S) URL of the cricket.duckdb file.
Optionally set DUCKDB_SHA256_URL to a URL returning the expected SHA256 hash.

If the local file already exists and its checksum matches, the download is skipped.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import httpx


def _sha256_file(path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_file(client: httpx.Client, url: str, dest: Path) -> bool:
    """Stream-download a file. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with client.stream("GET", url, follow_redirects=True, timeout=600.0) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
        tmp.rename(dest)
        return True
    except (httpx.HTTPError, OSError) as exc:
        print(f"  [ERR] Download failed: {exc}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False


def maybe_hydrate_duckdb() -> None:
    """Download cricket.duckdb from remote if configured and needed."""
    remote_url = os.environ.get("DUCKDB_REMOTE_URL", "").strip()
    if not remote_url:
        return

    db_path = Path(os.environ.get("DUCKDB_PATH", "/data/cricket/cricket.duckdb"))
    sha_url = os.environ.get("DUCKDB_SHA256_URL", "").strip()

    print("=" * 60)
    print("  DuckDB hydrate — checking remote")
    print(f"  Remote: {remote_url}")
    print(f"  Local:  {db_path}")
    print("=" * 60)

    with httpx.Client() as client:
        # Get expected checksum if available
        expected_sha: str | None = None
        if sha_url:
            try:
                resp = client.get(sha_url, follow_redirects=True, timeout=30.0)
                resp.raise_for_status()
                expected_sha = resp.text.strip().split()[0].lower()
                print(f"  Expected SHA256: {expected_sha[:16]}...")
            except httpx.HTTPError:
                print("  [WARN] Could not fetch SHA256 — will download regardless")

        # Check if local file already matches
        if db_path.exists() and expected_sha:
            local_sha = _sha256_file(db_path)
            if local_sha == expected_sha:
                print(f"  [OK] Local file matches checksum — skipping download")
                return
            print(f"  Local SHA256 mismatch ({local_sha[:16]}...) — re-downloading")

        if db_path.exists() and not expected_sha:
            print(f"  [OK] Local file exists and no checksum to verify — skipping download")
            return

        # Download
        print(f"  Downloading cricket.duckdb...")
        if _download_file(client, remote_url, db_path):
            size_mb = db_path.stat().st_size / (1024 * 1024)
            print(f"  [OK] Downloaded {size_mb:.1f} MB")
            # Verify checksum if available
            if expected_sha:
                actual = _sha256_file(db_path)
                if actual != expected_sha:
                    print(f"  [ERR] Checksum mismatch after download! Expected {expected_sha[:16]}, got {actual[:16]}")
                else:
                    print(f"  [OK] Checksum verified")
        else:
            print(f"  [ERR] Download failed — API will start without data")
