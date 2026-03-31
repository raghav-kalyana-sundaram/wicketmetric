from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from cricwarehouse.paths import PORTRAITS, ensure_dirs

UA = "WicketMetric/1.1 (localhost cricket warehouse; portraits; https://cricsheet.org)"
SPARQL = "https://query.wikidata.org/sparql"
_LOCK = threading.Lock()
_GATE = threading.Semaphore(3)


def _miss_path() -> Path:
    ensure_dirs()
    return PORTRAITS / "_miss.json"


def _load_miss() -> dict[str, str]:
    p = _miss_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _mark_miss(person_id: str) -> None:
    with _LOCK:
        data = _load_miss()
        from datetime import datetime, timezone

        data[person_id] = datetime.now(timezone.utc).isoformat()
        _miss_path().write_text(json.dumps(data), encoding="utf-8")


def cache_path(person_id: str) -> Path:
    ensure_dirs()
    return PORTRAITS / f"{person_id}.jpg"


def _wikidata_image(cricinfo_id: str) -> str | None:
    query = (
        "SELECT ?image WHERE { "
        f'?person wdt:P2697 "{cricinfo_id}" . '
        "?person wdt:P18 ?image . } LIMIT 1"
    )
    with httpx.Client(timeout=8.0, headers={"User-Agent": UA, "Accept": "application/json"}) as client:
        r = client.get(SPARQL, params={"query": query, "format": "json"})
        r.raise_for_status()
        bindings = r.json().get("results", {}).get("bindings") or []
        if not bindings:
            return None
        url = bindings[0].get("image", {}).get("value")
        if not url:
            return None
        if "Special:FilePath/" in url:
            return url.replace("http://", "https://") + ("&" if "?" in url else "?") + "width=320"
        name = url.rsplit("/", 1)[-1]
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}?width=320"


def _download(url: str, dest: Path) -> bool:
    with httpx.Client(timeout=12.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        r = client.get(url)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
            return False
        body = r.content
        if len(body) < 800 or len(body) > 1_800_000:
            return False
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(dest)
        return True


def resolve_portrait(person: dict[str, Any], *, warm: bool) -> Path | None:
    pid = person.get("person_id")
    if not pid:
        return None
    dest = cache_path(str(pid))
    if dest.exists() and dest.stat().st_size > 800:
        return dest
    if not warm:
        return None
    if str(pid) in _load_miss():
        return None
    cid = str(person.get("key_cricinfo") or "").strip()
    if not cid or not cid.isdigit():
        _mark_miss(str(pid))
        return None
    with _GATE:
        if dest.exists() and dest.stat().st_size > 800:
            return dest
        try:
            url = _wikidata_image(cid)
            if not url or not _download(url, dest):
                _mark_miss(str(pid))
                return None
            return dest
        except Exception:
            _mark_miss(str(pid))
            return None
