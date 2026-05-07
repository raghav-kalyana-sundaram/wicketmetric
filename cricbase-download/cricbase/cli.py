from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DB_PATH, DEFAULT_GENDER, PEOPLE_CSV
from .db import connect, init_db
from .download import download_cricsheet
from .ingest_cricsheet import ingest_zips
from .ingest_players import load_people, mark_appeared_players
from .queries import (
    database_summary,
    dismissal_breakdown,
    dismissal_leaders,
    find_player,
    player_profile,
)


def cmd_download(_args: argparse.Namespace) -> None:
    download_cricsheet()


def cmd_ingest_historical(args: argparse.Namespace) -> None:
    from .ingest_historical import ingest_historical

    conn = connect()
    init_db(conn)
    match_types = []
    if args.tests:
        match_types.append("Test")
    if args.odis:
        match_types.append("ODI")
    if not match_types:
        match_types = ["Test", "ODI"]
    test_years = range(args.from_year, args.to_year + 1)
    odi_years = range(max(args.from_year, 1971), args.to_year + 1)
    print(f"Ingesting Cricinfo scorecards {args.from_year}-{args.to_year} ({', '.join(match_types)})")
    summary = ingest_historical(
        conn,
        match_types=tuple(match_types),
        test_years=test_years,
        odi_years=odi_years,
        sleep_s=args.sleep,
        only_fow=args.only_fow,
    )
    print(json.dumps(summary, indent=2, default=str))
    print(json.dumps(database_summary(conn), indent=2))
    conn.close()


def cmd_ingest(args: argparse.Namespace) -> None:
    conn = connect()
    init_db(conn)
    print(f"Loading player register from {PEOPLE_CSV}")
    people = load_people(conn)
    print(f"  {people} players in registry")
    zips = [Path(p) for p in args.zips] if args.zips else None
    print("Ingesting Cricsheet matches...")
    stats = ingest_zips(conn, zip_paths=zips, gender=args.gender)
    appeared = mark_appeared_players(conn)
    print(f"Done: {stats}")
    print(f"Players who appeared in kept matches: {appeared}")
    print(json.dumps(database_summary(conn), indent=2))
    conn.close()


def cmd_enrich(args: argparse.Namespace) -> None:
    from .enrich_cricinfo import enrich_players

    conn = connect()
    stats = enrich_players(conn, limit=args.limit, sleep_s=args.sleep, appeared_only=not args.all)
    print(stats)
    conn.close()


def cmd_summary(_args: argparse.Namespace) -> None:
    conn = connect()
    print(json.dumps(database_summary(conn), indent=2))
    conn.close()


def cmd_dismissals(args: argparse.Namespace) -> None:
    conn = connect()
    if args.breakdown:
        rows = dismissal_breakdown(conn, match_type=args.match_type)
    else:
        rows = dismissal_leaders(
            conn,
            kind=args.kind,
            match_type=args.match_type,
            limit=args.limit,
            as_bowler=args.bowler,
        )
    print(json.dumps(rows, indent=2))
    conn.close()


def cmd_profile(args: argparse.Namespace) -> None:
    conn = connect()
    matches = find_player(conn, args.query)
    if not matches:
        raise SystemExit(f"No player matched {args.query!r}")
    if len(matches) > 1 and not args.pick:
        print("Multiple players matched. Re-run with --pick <player_id>:")
        for row in matches:
            print(f"  {row['player_id']}  {row['unique_name']}  cricinfo={row['cricinfo_id']}")
        conn.close()
        return
    player_id = args.pick or matches[0]["player_id"]
    print(json.dumps(player_profile(conn, player_id), indent=2, default=str))
    conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query a Test/ODI cricket database")
    parser.add_argument("--db", default=str(DB_PATH), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("download", help="Download Cricsheet Test and ODI JSON zips")

    hist = sub.add_parser(
        "ingest-historical",
        help="Load Test/ODI scorecards from Cricinfo Statsguru for years Cricsheet does not already cover",
    )
    hist.add_argument("--from-year", type=int, default=1877)
    hist.add_argument("--to-year", type=int, default=2001)
    hist.add_argument("--tests", action="store_true")
    hist.add_argument("--odis", action="store_true")
    hist.add_argument("--sleep", type=float, default=0.12)
    hist.add_argument(
        "--only-fow",
        action="store_true",
        help="Skip batting/bowling/dismissals and only load partnership/FOW pages",
    )

    ingest = sub.add_parser("ingest", help="Load people.csv and Cricsheet scorecards")
    ingest.add_argument("--gender", default=DEFAULT_GENDER)
    ingest.add_argument("zips", nargs="*", help="Optional zip paths (defaults to data/raw/cricsheet)")

    enrich = sub.add_parser("enrich", help="Fetch ESPNCricinfo bios for players in the DB")
    enrich.add_argument("--limit", type=int, default=None)
    enrich.add_argument("--sleep", type=float, default=0.4)
    enrich.add_argument("--all", action="store_true", help="Enrich the full register, not just match players")

    sub.add_parser("summary", help="Show database coverage")

    dismiss = sub.add_parser("dismissals", help="Dismissal leaderboards")
    dismiss.add_argument("--kind", default="lbw")
    dismiss.add_argument("--match-type", choices=["Test", "ODI"])
    dismiss.add_argument("--limit", type=int, default=25)
    dismiss.add_argument("--bowler", action="store_true", help="Count wickets taken instead of times out")
    dismiss.add_argument("--breakdown", action="store_true")

    profile = sub.add_parser("profile", help="Player career profile")
    profile.add_argument("query")
    profile.add_argument("--pick", help="Cricsheet player_id if the name is ambiguous")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "download": cmd_download,
        "ingest": cmd_ingest,
        "ingest-historical": cmd_ingest_historical,
        "enrich": cmd_enrich,
        "summary": cmd_summary,
        "dismissals": cmd_dismissals,
        "profile": cmd_profile,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
