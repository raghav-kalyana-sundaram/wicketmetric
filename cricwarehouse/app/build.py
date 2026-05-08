from __future__ import annotations

import csv
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from cricwarehouse.competitions import README_CODE, IN_SCOPE
from cricwarehouse.paths import CRICSHEET, WAREHOUSE, ensure_dirs
from cricwarehouse.app.parse import parse_match_file, slugify, parse_one
from cricwarehouse.app.pull import discover_local_dumps, iter_readme_rows, load_sources
from cricwarehouse.app.db import write_parquet
from cricwarehouse.app.standings import compute_standings
from cricwarehouse.app import metrics as metrics_mod
from cricwarehouse.app.cricbase import cricbase_available

IN_SCOPE_README = {"Test", "ODI", "T20", "IT20", "IPL", "WPL", "BBL", "WBB"}
TABLE_KEYS = (
    "matches",
    "people",
    "xi",
    "innings",
    "batting_lines",
    "bowling_lines",
    "deliveries",
    "partnerships",
    "fielding_lines",
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _candidate_files() -> list[tuple[str, str | None]]:
    """(path, readme_code) for in-scope matches, deduped by match_id."""
    seen: dict[str, tuple[str, str | None]] = {}
    dumps = discover_local_dumps()
    for dump in dumps:
        indexed = False
        for _date, team_type, code, _gender, match_id in iter_readme_rows(dump):
            indexed = True
            if code not in IN_SCOPE_README:
                continue
            if code == "T20" and team_type != "international":
                # club T20s that aren't IPL/BBL/WPL/WBB are out of v1
                continue
            path = dump / f"{match_id}.json"
            if path.exists() and match_id not in seen:
                seen[match_id] = (str(path), code)
        if not indexed:
            for path in dump.glob("*.json"):
                if path.stem not in seen:
                    seen[path.stem] = (str(path), None)
    return list(seen.values())


def _load_register() -> tuple[dict[str, dict], dict[str, list[str]]]:
    people: dict[str, dict] = {}
    names: dict[str, list[str]] = defaultdict(list)
    people_csv = CRICSHEET / "people.csv"
    if people_csv.exists():
        with people_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                pid = row.get("identifier")
                if not pid:
                    continue
                name = row.get("name") or ""
                unique = row.get("unique_name") or name
                people[pid] = {
                    "person_id": pid,
                    "display_name": name,
                    "unique_name": unique,
                    "slug": slugify(unique or name),
                    "gender": None,
                    "key_cricinfo": row.get("key_cricinfo"),
                    "key_cricketarchive": row.get("key_cricketarchive"),
                    "key_cricbuzz": row.get("key_cricbuzz"),
                    "key_bcci": row.get("key_bcci"),
                }
    names_csv = CRICSHEET / "names.csv"
    if names_csv.exists():
        with names_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                pid = row.get("identifier")
                n = row.get("name")
                if pid and n:
                    names[pid].append(n)
    return people, names


def build(*, workers: int | None = None, with_metrics: bool = True) -> None:
    ensure_dirs()
    candidates = _candidate_files()
    _log(f"Build — {len(candidates)} candidate match files")
    if not candidates:
        _log("No in-scope matches found. Run: python -m cricwarehouse pull")
        return

    buckets: dict[str, list] = {k: [] for k in TABLE_KEYS}
    people_from_matches: dict[str, dict] = {}
    ok = 0
    skipped = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(parse_one, item) for item in candidates]
        total = len(futs)
        for i, fut in enumerate(as_completed(futs), start=1):
            parsed = fut.result()
            if not parsed:
                skipped += 1
            else:
                ok += 1
                buckets["matches"].append(parsed["match"])
                buckets["xi"].extend(parsed["xi"])
                buckets["innings"].extend(parsed["innings"])
                buckets["batting_lines"].extend(parsed["batting_lines"])
                buckets["bowling_lines"].extend(parsed["bowling_lines"])
                buckets["deliveries"].extend(parsed["deliveries"])
                buckets["partnerships"].extend(parsed["partnerships"])
                buckets["fielding_lines"].extend(parsed["fielding_lines"])
                for p in parsed["people"]:
                    people_from_matches[p["person_id"]] = p
            if i % 250 == 0 or i == total:
                _log(f"  parsed {i}/{total}  kept={ok}  skipped={skipped}")

    register, name_variants = _load_register()
    people_rows = []
    seen_ids = set()
    for pid, row in {**people_from_matches, **register}.items():
        base = people_from_matches.get(pid, {})
        merged = {**base, **row}
        if base.get("gender") and not merged.get("gender"):
            merged["gender"] = base["gender"]
        variants = name_variants.get(pid, [])
        merged["name_variants"] = "|".join(variants) if variants else None
        if not merged.get("slug"):
            merged["slug"] = slugify(merged.get("unique_name") or merged.get("display_name") or pid)
        people_rows.append(merged)
        seen_ids.add(pid)
    buckets["people"] = people_rows

    if cricbase_available():
        from cricwarehouse.app.cricbase import ingest_into_build

        hist = ingest_into_build(buckets)
        _log(
            f"Cricbase historical: {hist.get('matches', 0):,} Tests/ODIs "
            f"({hist.get('batting_lines', 0):,} batting lines)"
        )

    _log("Writing parquet…")
    for key in ("people", "matches", "xi", "innings", "batting_lines", "bowling_lines", "deliveries", "partnerships", "fielding_lines"):
        path = write_parquet(key, buckets[key])
        _log(f"  {key}: {len(buckets[key]):,} → {path.name}")

    _log("Computing standings…")
    standings, playoffs = compute_standings(buckets["matches"], buckets["innings"])
    write_parquet("standings", standings)
    write_parquet("playoffs", playoffs)
    _log(f"  standings {len(standings)}  playoffs {len(playoffs)}")

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "matches": ok,
        "skipped": skipped,
        "competitions": sorted({m["competition"] for m in buckets["matches"]}),
    }
    (WAREHOUSE / "build.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _print_counts(buckets["matches"], buckets["deliveries"])

    if with_metrics:
        _log("Rebuilding T20 metrics…")
        metrics_mod.rebuild_metrics()
    _log("Build complete.")


def _print_counts(matches: list[dict], deliveries: list[dict]) -> None:
    from collections import Counter

    c = Counter()
    dates: dict[str, list[str]] = defaultdict(list)
    balls = Counter()
    for m in matches:
        key = (m["competition"], m["gender"])
        c[key] += 1
        if m.get("start_date"):
            dates[key].append(m["start_date"])
    for d in deliveries:
        # deliveries don't have competition; skip detailed balls here
        pass
    _log("Counts (competition · gender · matches · date range)")
    for (comp, gender), n in sorted(c.items()):
        ds = dates.get((comp, gender), [])
        span = f"{min(ds)}–{max(ds)}" if ds else "—"
        _log(f"  {comp:6}  {gender:7}  {n:5}  {span}")
    _log(f"  deliveries stored: {len(deliveries):,}")
