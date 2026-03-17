from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

VALID_COMPETITIONS = ("t20i", "t20", "ipl")
EARLIEST_START_DATES = {
    "t20i": date(2005, 2, 17),
    "t20": date(2003, 1, 1),
    "ipl": date(2008, 4, 18),
}
IPL_SERIES_PATTERNS = (
    re.compile(r"indian premier league", re.IGNORECASE),
    re.compile(r"\bipl\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class MatchRef:
    match_id: int
    series_id: int

    @property
    def key(self) -> str:
        return f"{self.match_id}:{self.series_id}"


class ScrapeError(RuntimeError):
    """Raised when Cricinfo discovery or hydration fails."""


def _load_match_class():
    try:
        from espncricinfo.match import Match
    except ImportError as exc:  # pragma: no cover - exercised at runtime only
        raise ScrapeError(
            "python-espncricinfo is not installed. Run `pip install -r requirements.txt` "
            "and `playwright install webkit` first."
        ) from exc
    return Match


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Expected YYYY-MM-DD date, got {value!r}."
        ) from exc


def normalise_competitions(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    normalised: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key not in VALID_COMPETITIONS:
            raise ValueError(
                f"Unsupported competition {value!r}. Use one of: {', '.join(VALID_COMPETITIONS)}"
            )
        if key not in seen:
            seen.add(key)
            normalised.append(key)
    return normalised


def default_start_date(competitions: Sequence[str]) -> date:
    return min(EARLIEST_START_DATES[c] for c in normalise_competitions(competitions))


def iter_dates(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return text.strip("-") or "unknown"


def classify_match(
    *,
    series_name: str | None,
    match_class: str | None,
    competitions: Sequence[str],
) -> str | None:
    allowed = set(normalise_competitions(competitions))
    series = (series_name or "").strip()
    match_kind = (match_class or "").strip().upper()

    if "ipl" in allowed and any(pattern.search(series) for pattern in IPL_SERIES_PATTERNS):
        return "ipl"
    if "t20i" in allowed and match_kind in {"T20I", "WT20I"}:
        return "t20i"
    if "t20" in allowed and match_kind == "T20":
        return "t20"
    return None


def match_output_path(
    output_root: Path,
    *,
    competition: str,
    season: str | None,
    match_date: str | None,
    match_id: int,
    series_name: str | None,
) -> Path:
    season_dir = (season or "").strip() or ((match_date or "")[:4] or "unknown")
    series_dir = slugify(series_name or "unknown-series")
    return output_root / competition / season_dir / series_dir / f"{match_id}.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=True, sort_keys=False)
        fh.write("\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=True))
        fh.write("\n")


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path, default={})
    if not isinstance(payload, dict):
        raise ScrapeError(f"Manifest at {path} is not a JSON object.")
    return payload


def discover_matches_for_date(
    day: date,
    *,
    discovery_root: Path,
    refresh: bool = False,
    sleep_seconds: float = 0.0,
) -> list[MatchRef]:
    cache_path = discovery_root / f"{day.isoformat()}.json"
    cached = None if refresh else load_json(cache_path, default=None)
    if cached is not None:
        refs = cached.get("refs", [])
        return [MatchRef(int(match_id), int(series_id)) for match_id, series_id in refs]

    Match = _load_match_class()
    raw_refs = Match.get_recent_matches(date=day.isoformat())
    refs = [MatchRef(int(match_id), int(series_id)) for match_id, series_id in raw_refs]
    write_json(
        cache_path,
        {
            "date": day.isoformat(),
            "count": len(refs),
            "refs": [[ref.match_id, ref.series_id] for ref in refs],
        },
    )
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return refs


def hydrate_match(ref: MatchRef):
    Match = _load_match_class()
    return Match(match_id=ref.match_id, series_id=ref.series_id)


def build_match_payload(match: Any, *, ref: MatchRef, competition: str) -> dict[str, Any]:
    raw = getattr(match, "json", {}) or {}
    return {
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        "competition": competition,
        "match_id": ref.match_id,
        "series_id": ref.series_id,
        "series_name": getattr(match, "series_name", ""),
        "description": getattr(match, "description", ""),
        "match_class": getattr(match, "match_class", ""),
        "season": getattr(match, "season", ""),
        "date": getattr(match, "date", ""),
        "result": getattr(match, "result", ""),
        "status": getattr(match, "status", ""),
        "team_1": getattr(match, "team_1", None),
        "team_2": getattr(match, "team_2", None),
        "teams": getattr(match, "teams", []) or raw.get("teams", []),
        "ground_name": getattr(match, "ground_name", ""),
        "town_name": getattr(match, "town_name", ""),
        "continent_name": getattr(match, "continent_name", ""),
        "innings": getattr(match, "innings", []),
        "all_innings": getattr(match, "all_innings", []),
        "rosters": getattr(match, "rosters", []),
        "batting_scorecard": getattr(match, "batting_scorecard", []),
        "bowling_scorecard": getattr(match, "bowling_scorecard", []),
        "fows": getattr(match, "fows", []),
        "extras": getattr(match, "extras", []),
        "raw": raw,
    }


def build_manifest_entry(payload: dict[str, Any], *, relative_path: Path) -> dict[str, Any]:
    return {
        "competition": payload["competition"],
        "match_id": payload["match_id"],
        "series_id": payload["series_id"],
        "date": payload.get("date", ""),
        "season": payload.get("season", ""),
        "series_name": payload.get("series_name", ""),
        "description": payload.get("description", ""),
        "match_class": payload.get("match_class", ""),
        "result": payload.get("result", ""),
        "path": relative_path.as_posix(),
    }


def scrape_matches(
    *,
    competitions: Sequence[str],
    start_date: date,
    end_date: date,
    output_root: Path,
    refresh_discovery: bool = False,
    overwrite_matches: bool = False,
    sleep_seconds: float = 0.0,
    max_matches: int | None = None,
) -> dict[str, Any]:
    competitions = normalise_competitions(competitions)
    discovery_root = output_root / "_discovery"
    manifest_path = output_root / "manifest.json"
    errors_path = output_root / "errors.jsonl"

    manifest = load_manifest(manifest_path)
    seen_refs: dict[str, MatchRef] = {}

    for day in iter_dates(start_date, end_date):
        refs = discover_matches_for_date(
            day,
            discovery_root=discovery_root,
            refresh=refresh_discovery,
            sleep_seconds=sleep_seconds,
        )
        for ref in refs:
            seen_refs.setdefault(ref.key, ref)

    scraped = 0
    skipped_existing = 0
    skipped_filtered = 0
    failed = 0

    for ref in sorted(seen_refs.values(), key=lambda item: (item.match_id, item.series_id)):
        if max_matches is not None and scraped >= max_matches:
            break

        manifest_entry = manifest.get(ref.key)
        if manifest_entry and not overwrite_matches:
            existing_path = output_root / manifest_entry["path"]
            if existing_path.exists():
                skipped_existing += 1
                continue

        try:
            match = hydrate_match(ref)
            competition = classify_match(
                series_name=getattr(match, "series_name", ""),
                match_class=getattr(match, "match_class", ""),
                competitions=competitions,
            )
            if competition is None:
                skipped_filtered += 1
                continue

            payload = build_match_payload(match, ref=ref, competition=competition)
            destination = match_output_path(
                output_root,
                competition=competition,
                season=str(payload.get("season", "") or ""),
                match_date=str(payload.get("date", "") or ""),
                match_id=ref.match_id,
                series_name=str(payload.get("series_name", "") or ""),
            )
            write_json(destination, payload)
            manifest[ref.key] = build_manifest_entry(
                payload,
                relative_path=destination.relative_to(output_root),
            )
            write_json(manifest_path, manifest)
            scraped += 1
        except Exception as exc:  # pragma: no cover - network/runtime behaviour
            failed += 1
            append_jsonl(
                errors_path,
                {
                    "logged_at_utc": datetime.now(timezone.utc).isoformat(),
                    "match_id": ref.match_id,
                    "series_id": ref.series_id,
                    "error": str(exc),
                },
            )

    return {
        "competitions": competitions,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "discovered_refs": len(seen_refs),
        "scraped": scraped,
        "skipped_existing": skipped_existing,
        "skipped_filtered": skipped_filtered,
        "failed": failed,
        "manifest_path": str(manifest_path),
        "errors_path": str(errors_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resumable ESPNcricinfo scraper for T20I, domestic T20, and IPL matches "
            "using python-espncricinfo."
        )
    )
    parser.add_argument(
        "--competition",
        dest="competitions",
        action="append",
        choices=VALID_COMPETITIONS,
        help="Competition bucket to keep. Repeat for multiple values.",
    )
    parser.add_argument(
        "--start-date",
        type=parse_iso_date,
        default=None,
        help="Discovery start date (YYYY-MM-DD). Defaults to the earliest date for the requested competitions.",
    )
    parser.add_argument(
        "--end-date",
        type=parse_iso_date,
        default=date.today(),
        help="Discovery end date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("espncricinfo_raw"),
        help="Root directory for discovery cache, manifest, and match JSON files.",
    )
    parser.add_argument(
        "--refresh-discovery",
        action="store_true",
        help="Ignore cached daily discovery files and refetch date pages.",
    )
    parser.add_argument(
        "--overwrite-matches",
        action="store_true",
        help="Refetch and overwrite already-saved match payloads.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional delay between daily discovery page fetches.",
    )
    parser.add_argument(
        "--max-matches",
        type=int,
        default=None,
        help="Optional cap on the number of hydrated matches for smoke testing.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    competitions = normalise_competitions(args.competitions or ["t20i", "ipl"])
    start_date = args.start_date or default_start_date(competitions)
    end_date = args.end_date
    if start_date > end_date:
        parser.error("--start-date must be on or before --end-date")

    summary = scrape_matches(
        competitions=competitions,
        start_date=start_date,
        end_date=end_date,
        output_root=args.output_dir,
        refresh_discovery=args.refresh_discovery,
        overwrite_matches=args.overwrite_matches,
        sleep_seconds=args.sleep_seconds,
        max_matches=args.max_matches,
    )
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
