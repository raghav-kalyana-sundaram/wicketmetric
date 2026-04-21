"""
Enrich bowling careers with ESPNcricinfo bowling-style metadata.

Uses the Cricsheet Register ``people.csv`` (``identifier`` → ``key_cricinfo``) to
resolve ESPN athlete IDs, then fetches public JSON from ESPN's core athlete
API.  Rows are only labelled when *identity checks* pass: the Cricsheet /
career name must match ESPN's ``battingName``, ``name``, ``fullName``, etc.

Outputs:
    - ``bowling_style`` — raw description (e.g. "Right-arm fast-medium")
    - ``bowling_kind`` — ``pace`` | ``spin`` | ``unknown``
    - ``espn_player_id`` — numeric string when resolved
    - ``bowling_style_verified`` — True when the name gate passed

Respect ESPN rate limits: configure ``sleep_seconds`` between requests.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

ATHLETE_URL = "http://core.espnuk.org/v2/sports/cricket/athletes/{player_id}"
DEFAULT_UA = "CricketMetrics/1.0 (+https://github.com/cricket-metrics; registry enrichment)"


def normalize_registry_id(raw: str | None) -> str:
    """Lowercase hex / UUID-style ids with hyphens removed for joining."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    s = str(raw).strip().lower().replace("-", "")
    return s


def _flatten_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _name_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def names_match_cricsheet_to_athlete(
    cricsheet_label: str,
    athlete: Mapping[str, Any],
    *,
    min_ratio: float = 0.82,
) -> bool:
    """
    Return True if *cricsheet_label* is plausibly the same person as *athlete*.

    ESPN's ``battingName`` often matches Cricsheet abbreviations (e.g. JE Root).
    """
    label = (cricsheet_label or "").strip()
    if not label:
        return False
    flat_label = _flatten_name(label)

    fields: list[str] = []
    for key in ("battingName", "name", "displayName", "fullName", "shortName"):
        v = athlete.get(key)
        if v and str(v).strip():
            fields.append(str(v).strip())

    for f in fields:
        if flat_label == _flatten_name(f):
            return True
        if _name_ratio(flat_label, _flatten_name(f)) >= min_ratio:
            return True

    last = (athlete.get("lastName") or "").strip().lower()
    if not last:
        return False
    tokens = re.findall(r"[A-Za-z]+", label)
    if not tokens or tokens[-1].lower() != last:
        return False

    first = (athlete.get("firstName") or "").strip()
    middle = (athlete.get("middleName") or "").strip()
    if len(tokens) < 2:
        return len(tokens) == 1 and tokens[0].lower() == last

    initials_blob = "".join(t.lower() for t in tokens[:-1])
    expected_initials = ""
    if first:
        expected_initials += first[0].lower()
    if middle:
        expected_initials += middle[0].lower()
    if expected_initials and initials_blob == expected_initials[: len(initials_blob)]:
        return True
    if len(initials_blob) == 1 and first and initials_blob == first[0].lower():
        return True
    return False


def verify_player_identity(
    career_bowler: str,
    register_name: str,
    register_unique: str,
    athlete: Mapping[str, Any],
) -> bool:
    """True if any trusted Cricsheet-side label matches the ESPN athlete."""
    for side in (career_bowler, register_name, register_unique):
        if side and str(side).strip() and names_match_cricsheet_to_athlete(str(side).strip(), athlete):
            return True
    return False


def extract_bowling_description(athlete: Mapping[str, Any]) -> str | None:
    styles = athlete.get("style") or athlete.get("styles") or []
    if not isinstance(styles, list):
        return None
    for item in styles:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "bowling":
            desc = item.get("description")
            if desc:
                return str(desc).strip()
    return None


def classify_bowling_kind(description: str | None) -> str:
    """Coarse pace vs spin from ESPN's free-text bowling style."""
    if not description:
        return "unknown"
    d = description.lower()

    spin_markers = (
        "offbreak",
        "off break",
        "legbreak",
        "leg break",
        "googly",
        "chinaman",
        "wrist",
        "orthodox",
        "offspin",
        "off-spin",
        "legspin",
        "leg-spin",
        "left-arm wrist",
        "slow left",
        "slow right-arm wrist",
        "roundarm",
    )
    if "spin" in d:
        return "spin"
    for m in spin_markers:
        if m in d:
            return "spin"

    pace_markers = ("fast", "medium", "seam", "pace", "quick")
    for m in pace_markers:
        if m in d:
            return "pace"
    return "unknown"


def _normalise_espn_id(raw: Any) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    try:
        return str(int(float(s)))
    except ValueError:
        if s.isdigit():
            return s
        return None


def load_cricsheet_people_register(path: str | Path) -> pd.DataFrame:
    """
    Load Cricsheet ``people.csv``.

    Required columns: ``identifier``, ``key_cricinfo``.  Optional: ``name``,
    ``unique_name``.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Cricsheet register not found: {p}")

    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    if "identifier" not in df.columns:
        raise ValueError(f"{p} missing required column 'identifier'")
    if "key_cricinfo" not in df.columns:
        raise ValueError(f"{p} missing required column 'key_cricinfo'")

    for col in ("name", "unique_name"):
        if col not in df.columns:
            df[col] = ""

    df["_nid"] = df["identifier"].map(normalize_registry_id)
    df["key_cricinfo"] = df["key_cricinfo"].map(_normalise_espn_id)
    df = df[(df["_nid"].str.len() > 0) & df["key_cricinfo"].notna()]
    df = df.drop_duplicates(subset="_nid", keep="first")
    return df


def _read_json_cache(cache_file: Path) -> dict[str, Any] | None:
    if not cache_file.is_file():
        return None
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def fetch_athlete_json(
    player_id: str,
    *,
    timeout: float,
    cache_file: Path | None = None,
) -> dict[str, Any] | None:
    """GET athlete JSON; optionally read/write *cache_file*."""
    if cache_file is not None:
        cached = _read_json_cache(cache_file)
        if cached is not None:
            return cached

    url = ATHLETE_URL.format(player_id=player_id)
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    except Exception:
        return None

    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
        except OSError:
            pass
    return data


def build_enrichment_frame(
    bowl_careers: pd.DataFrame,
    people_csv: str | Path,
    *,
    cache_dir: str | Path | None = None,
    sleep_seconds: float = 0.35,
    timeout_seconds: float = 25.0,
    skip_network: bool = False,
) -> pd.DataFrame:
    """
    For each distinct ``bowler_id`` in *bowl_careers*, resolve ESPN id via the
    register and fetch bowling style when identity checks pass.
    """
    if "bowler_id" not in bowl_careers.columns or "bowler" not in bowl_careers.columns:
        raise ValueError("bowl_careers must contain bowler_id and bowler")

    register = load_cricsheet_people_register(people_csv)
    cache_root = Path(cache_dir) if cache_dir else None

    # One enrichment row per bowler_id (careers can repeat ids if the label differs).
    if "matches" in bowl_careers.columns:
        keys = (
            bowl_careers.sort_values("matches", ascending=False)
            .drop_duplicates(subset=["bowler_id"], keep="first")[["bowler_id", "bowler"]]
            .copy()
        )
    else:
        keys = bowl_careers.drop_duplicates(subset=["bowler_id"], keep="first")[
            ["bowler_id", "bowler"]
        ].copy()
    keys["_nid"] = keys["bowler_id"].map(normalize_registry_id)
    merged = keys.merge(
        register[["_nid", "key_cricinfo", "name", "unique_name"]],
        on="_nid",
        how="left",
    )

    records: list[dict[str, Any]] = []
    for row in merged.itertuples(index=False):
        bid = str(row.bowler_id)
        bname = str(row.bowler)
        reg_name = str(row.name) if getattr(row, "name", "") else ""
        reg_unique = str(row.unique_name) if getattr(row, "unique_name", "") else ""
        espn_id = getattr(row, "key_cricinfo", None)

        base = {
            "bowler_id": bid,
            "bowling_style": "",
            "bowling_kind": "unknown",
            "espn_player_id": "",
            "bowling_style_verified": False,
        }

        if espn_id is None or (isinstance(espn_id, float) and pd.isna(espn_id)):
            records.append(base)
            continue
        pid = str(espn_id).strip()
        if not pid:
            records.append(base)
            continue

        cache_file = (cache_root / f"{pid}.json") if cache_root is not None else None
        athlete: dict[str, Any] | None = None
        if skip_network and cache_file is not None:
            athlete = _read_json_cache(cache_file)
        elif skip_network:
            records.append(base)
            continue
        else:
            athlete = fetch_athlete_json(pid, timeout=timeout_seconds, cache_file=cache_file)

        if athlete is None:
            records.append({**base, "espn_player_id": pid})
            continue

        if not verify_player_identity(bname, reg_name, reg_unique, athlete):
            records.append({**base, "espn_player_id": pid})
            continue

        desc = extract_bowling_description(athlete)
        kind = classify_bowling_kind(desc)
        records.append(
            {
                "bowler_id": bid,
                "bowling_style": desc or "",
                "bowling_kind": kind,
                "espn_player_id": pid,
                "bowling_style_verified": True,
            }
        )
        if sleep_seconds > 0 and not skip_network:
            time.sleep(sleep_seconds)

    enr = pd.DataFrame.from_records(records)
    # One enrichment row per bowler_id (latest wins if duplicates)
    enr = enr.drop_duplicates(subset=["bowler_id"], keep="last")
    return enr


def enrich_bowl_careers_with_espn_styles(
    bowl_careers: pd.DataFrame,
    *,
    people_csv: str | Path,
    cache_dir: str | Path | None = None,
    sleep_seconds: float = 0.35,
    timeout_seconds: float = 25.0,
    skip_network: bool = False,
) -> pd.DataFrame:
    """Left-merge enrichment columns onto a bowling careers frame."""
    enr = build_enrichment_frame(
        bowl_careers,
        people_csv,
        cache_dir=cache_dir,
        sleep_seconds=sleep_seconds,
        timeout_seconds=timeout_seconds,
        skip_network=skip_network,
    )
    out = bowl_careers.merge(enr, on="bowler_id", how="left")
    out["bowling_style"] = out["bowling_style"].fillna("").astype(str)
    out["bowling_kind"] = out["bowling_kind"].fillna("unknown").astype(str)
    out["espn_player_id"] = out["espn_player_id"].fillna("").astype(str)
    out["bowling_style_verified"] = out["bowling_style_verified"].fillna(False).astype(bool)
    return out


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fetch ESPN bowling styles via Cricsheet people.csv + athlete API."
    )
    p.add_argument("--people-csv", type=Path, required=True, help="Path to Cricsheet people.csv")
    p.add_argument(
        "--bowling-careers-parquet",
        type=Path,
        help="Optional bowling_careers_full.parquet to enrich (writes sidecar parquet)",
    )
    p.add_argument(
        "--output-parquet",
        type=Path,
        help="Write enrichment lookup only (bowler_id, bowling_style, ...)",
    )
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache/espn_athletes"),
        help="Per-player JSON cache directory",
    )
    p.add_argument("--sleep-seconds", type=float, default=0.35)
    p.add_argument("--timeout-seconds", type=float, default=25.0)
    p.add_argument(
        "--skip-network",
        action="store_true",
        help="Only use cache hits (no HTTP)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    if args.output_parquet:
        if not args.bowling_careers_parquet:
            raise SystemExit("--output-parquet requires --bowling-careers-parquet")
        bc = pd.read_parquet(args.bowling_careers_parquet)
        enr = build_enrichment_frame(
            bc,
            args.people_csv,
            cache_dir=args.cache_dir,
            sleep_seconds=args.sleep_seconds,
            timeout_seconds=args.timeout_seconds,
            skip_network=args.skip_network,
        )
        args.output_parquet.parent.mkdir(parents=True, exist_ok=True)
        enr.to_parquet(args.output_parquet, index=False)
        print(f"Wrote {len(enr):,} rows to {args.output_parquet}")
        return 0

    if args.bowling_careers_parquet:
        bc = pd.read_parquet(args.bowling_careers_parquet)
        out = enrich_bowl_careers_with_espn_styles(
            bc,
            people_csv=args.people_csv,
            cache_dir=args.cache_dir,
            sleep_seconds=args.sleep_seconds,
            timeout_seconds=args.timeout_seconds,
            skip_network=args.skip_network,
        )
        dest = args.bowling_careers_parquet.with_name(
            args.bowling_careers_parquet.stem + "_enriched.parquet"
        )
        out.to_parquet(dest, index=False)
        print(f"Wrote {len(out):,} rows to {dest}")
        return 0

    raise SystemExit("Provide --output-parquet or rely on pipeline config integration.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
