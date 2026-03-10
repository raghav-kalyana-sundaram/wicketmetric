from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import httpx

from cricwarehouse.paths import CRICSHEET, LOCAL_DUMPS, ROOT, ensure_dirs

REGISTER_URLS = {
    "people.csv": "https://cricsheet.org/register/people.csv",
    "names.csv": "https://cricsheet.org/register/names.csv",
}

# Prefer subset zips over the all-matches dump (product spec §13).
SUBSET_ZIPS = {
    "ipl_json.zip": "https://cricsheet.org/downloads/ipl_json.zip",
    "bbl_json.zip": "https://cricsheet.org/downloads/bbl_json.zip",
    "wpl_json.zip": "https://cricsheet.org/downloads/wpl_json.zip",
    "wbbl_json.zip": "https://cricsheet.org/downloads/wbbl_json.zip",
    "t20s_male_json.zip": "https://cricsheet.org/downloads/t20s_male_json.zip",
    "t20s_female_json.zip": "https://cricsheet.org/downloads/t20s_female_json.zip",
    "tests_male_json.zip": "https://cricsheet.org/downloads/tests_male_json.zip",
    "tests_female_json.zip": "https://cricsheet.org/downloads/tests_female_json.zip",
}

README_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) - (\w+) - ([A-Za-z0-9]+) - (\w+) - (\d+) -"
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _sources_path() -> Path:
    return CRICSHEET / "sources.json"


def load_sources() -> dict:
    p = _sources_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"files": {}, "dumps": [], "last_pull": None}


def save_sources(data: dict) -> None:
    ensure_dirs()
    _sources_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def discover_local_dumps() -> list[Path]:
    found = []
    seen: set[str] = set()
    for path in LOCAL_DUMPS:
        if path.is_dir() and any(path.glob("*.json")):
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                found.append(path)
    return found


def iter_readme_rows(dump: Path) -> Iterator[tuple[str, str, str, str, str]]:
    readme = dump / "README.txt"
    if not readme.exists():
        return
    with readme.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = README_LINE.match(line)
            if m:
                yield m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)


def _download(url: str, dest: Path, etag: str | None) -> tuple[bool, str | None]:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 304:
                return False, etag
            resp.raise_for_status()
            new_etag = resp.headers.get("etag")
            tmp = dest.with_suffix(dest.suffix + ".part")
            with tmp.open("wb") as out:
                for chunk in resp.iter_bytes():
                    out.write(chunk)
            tmp.replace(dest)
            return True, new_etag


def _unzip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)


def pull_register() -> None:
    sources = load_sources()
    files = sources.setdefault("files", {})
    for name, url in REGISTER_URLS.items():
        dest = CRICSHEET / name
        prev = files.get(name, {}).get("etag")
        _log(f"Pull {name}…")
        try:
            changed, etag = _download(url, dest, prev)
        except Exception as exc:
            _log(f"  skipped ({exc})")
            continue
        files[name] = {
            "url": url,
            "etag": etag,
            "path": str(dest),
            "updated": datetime.now(timezone.utc).isoformat() if changed else files.get(name, {}).get("updated"),
        }
        _log("  updated" if changed else "  unchanged")
    sources["last_pull"] = datetime.now(timezone.utc).isoformat()
    save_sources(sources)


def pull_zips(*, force: bool = False) -> None:
    """Download official subset zips when local dumps are missing."""
    sources = load_sources()
    files = sources.setdefault("files", {})
    dumps = discover_local_dumps()
    if dumps and not force:
        _log(f"Using {len(dumps)} local dump folder(s); skip zip download (pass --force to refresh).")
        sources["dumps"] = [str(p) for p in dumps]
        sources["last_pull"] = datetime.now(timezone.utc).isoformat()
        save_sources(sources)
        return
    for name, url in SUBSET_ZIPS.items():
        dest = CRICSHEET / name
        prev = None if force else files.get(name, {}).get("etag")
        _log(f"Pull {name}…")
        try:
            changed, etag = _download(url, dest, prev)
        except Exception as exc:
            _log(f"  skipped ({exc})")
            continue
        files[name] = {
            "url": url,
            "etag": etag,
            "path": str(dest),
            "updated": datetime.now(timezone.utc).isoformat() if changed else files.get(name, {}).get("updated"),
        }
        if changed or force:
            extract_to = CRICSHEET / name.replace(".zip", "")
            _log(f"  extract → {extract_to.name}")
            _unzip(dest, extract_to)
        else:
            _log("  unchanged")
    sources["dumps"] = [str(p) for p in discover_local_dumps()]
    sources["last_pull"] = datetime.now(timezone.utc).isoformat()
    save_sources(sources)


def pull(*, force: bool = False) -> None:
    ensure_dirs()
    _log("Local Cricket Warehouse — pull")
    pull_register()
    dumps = discover_local_dumps()
    if dumps:
        _log("Discovered local dumps:")
        for d in dumps:
            n = sum(1 for _ in d.glob("*.json"))
            _log(f"  {d.relative_to(ROOT) if d.is_relative_to(ROOT) else d}  ({n} json)")
        sources = load_sources()
        sources["dumps"] = [str(p) for p in dumps]
        sources["last_pull"] = datetime.now(timezone.utc).isoformat()
        save_sources(sources)
        if force:
            pull_zips(force=True)
    else:
        pull_zips(force=force)
    _log("Pull complete.")
