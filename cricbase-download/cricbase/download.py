from __future__ import annotations

from pathlib import Path
from urllib.request import urlretrieve

from .config import CRICSHEET_DOWNLOADS, RAW_DIR


def download_cricsheet(dest_dir: Path | None = None) -> list[Path]:
    dest = dest_dir or RAW_DIR
    dest.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for match_type, url in CRICSHEET_DOWNLOADS.items():
        path = dest / f"{match_type.lower()}s_json.zip"
        print(f"Downloading {match_type} matches from Cricsheet...")
        urlretrieve(url, path)
        print(f"  saved {path} ({path.stat().st_size / 1_000_000:.1f} MB)")
        downloaded.append(path)
    return downloaded
