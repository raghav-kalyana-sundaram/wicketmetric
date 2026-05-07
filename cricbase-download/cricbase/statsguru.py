from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from .config import DATA_DIR, ODI_NATIONS, TEST_NATIONS

CACHE_DIR = DATA_DIR / "raw" / "statsguru"
HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    )
}
BASE = "https://stats.espncricinfo.com"
CLASS_IDS = {"Test": 1, "ODI": 2}

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

TEAM_ABBREV = {
    "AFG": "Afghanistan",
    "Afr": "Africa XI",
    "AFR": "Africa XI",
    "Asia": "Asia XI",
    "ASIA": "Asia XI",
    "AUS": "Australia",
    "BAN": "Bangladesh",
    "BER": "Bermuda",
    "BMU": "Bermuda",
    "CAN": "Canada",
    "ENG": "England",
    "HKG": "Hong Kong",
    "ICC": "ICC World XI",
    "IND": "India",
    "IRE": "Ireland",
    "KEN": "Kenya",
    "NAM": "Namibia",
    "NED": "Netherlands",
    "NL": "Netherlands",
    "NEP": "Nepal",
    "NZ": "New Zealand",
    "OMA": "Oman",
    "PAK": "Pakistan",
    "PNG": "Papua New Guinea",
    "SA": "South Africa",
    "SCO": "Scotland",
    "SL": "Sri Lanka",
    "UAE": "United Arab Emirates",
    "USA": "United States of America",
    "WI": "West Indies",
    "World": "ICC World XI",
    "ZIM": "Zimbabwe",
}

# Statsguru batting dismissal= codes, verified against known historical innings.
DISMISSAL_CODES = {
    1: "caught",
    2: "bowled",
    3: "lbw",
    4: "run out",
    5: "stumped",
    6: "hit wicket",
    7: "handled the ball",
    8: "obstructing the field",
    11: "retired hurt",
}
COMMON_DISMISSAL_CODES = {1: "caught", 2: "bowled", 3: "lbw", 4: "run out", 5: "stumped", 6: "hit wicket"}

_SESSION: requests.Session | None = None


def session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(HEADERS)
    return _SESSION


def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    # 15 Mar 1877
    match = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$", text)
    if match:
        day, mon, year = match.groups()
        return date(int(year), MONTHS[mon], int(day))
    # Jan 5, 1971
    match = re.match(r"^([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})$", text)
    if match:
        mon, day, year = match.groups()
        return date(int(year), MONTHS[mon], int(day))
    # Mar 15-19, 1877
    match = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})-\d{1,2},\s+(\d{4})$", text)
    if match:
        mon, day, year = match.groups()
        return date(int(year), MONTHS[mon], int(day))
    # Mar 31-Apr 4, 1877  or  Jun 27-Jul 1, 1930
    match = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})-[A-Za-z]{3}\s+\d{1,2},\s+(\d{4})$", text)
    if match:
        mon, day, year = match.groups()
        return date(int(year), MONTHS[mon], int(day))
    # Dec 31, 1881 - Jan 4, 1882  or  Dec 28, 1955 - Jan 2, 1956
    match = re.match(r"^([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})\s*-", text)
    if match:
        mon, day, year = match.groups()
        return date(int(year), MONTHS[mon], int(day))
    return None


def parse_int(text: str) -> int | None:
    text = (text or "").strip().replace("*", "").replace(",", "")
    if text in {"", "-"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def overs_to_balls(overs: str, balls_per_over: int) -> int:
    overs = (overs or "").strip()
    if overs in {"", "-", "DNB", "TDNB", "sub", "absent"}:
        return 0
    if "." in overs:
        whole, extra = overs.split(".", 1)
        try:
            return int(whole) * balls_per_over + int(extra)
        except ValueError:
            return 0
    try:
        return int(float(overs)) * balls_per_over
    except ValueError:
        return 0


def cache_path(url: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", url)
    return CACHE_DIR / f"{safe[-180:]}.html"


def fetch_html(url: str, sleep_s: float = 0.12, force: bool = False) -> str:
    path = cache_path(url)
    if path.exists() and not force:
        return path.read_text(encoding="utf-8", errors="replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(5):
        try:
            response = session().get(url, timeout=40)
            if response.status_code == 200 and "engineTable" in response.text:
                path.write_text(response.text, encoding="utf-8")
                time.sleep(sleep_s)
                return response.text
            last_error = f"{response.status_code} {response.text[:80]}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def year_results_url(match_type: str, year: int) -> str:
    return (
        f"{BASE}/ci/engine/records/team/match_results.html"
        f"?class={CLASS_IDS[match_type]};id={year};type=year"
    )


def innings_url(match_type: str, data_type: str, page: int, span_min: str, span_max: str, dismissal: int | None = None) -> str:
    params = {
        "class": CLASS_IDS[match_type],
        "filter": "advanced",
        "orderby": "start",
        "page": page,
        "size": 200,
        "spanmin1": span_min,
        "spanmax1": span_max,
        "spanval1": "span",
        "template": "results",
        "type": data_type,
        "view": "innings",
    }
    if dismissal is not None:
        params["dismissal"] = dismissal
    return f"{BASE}/ci/engine/stats/index.html?{urlencode(params).replace('+', '%20')}"


def parse_year_matches(html: str, match_type: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for table in soup.select("table.engineTable"):
        headers = [th.get_text(" ", strip=True) for th in table.select("tr th")]
        if "Team 1" not in headers or "Scorecard" not in headers:
            continue
        for tr in table.select("tr.data1"):
            cells = tr.select("td")
            texts = [c.get_text(" ", strip=True) for c in cells]
            if len(texts) < 6:
                continue
            link = tr.find("a", href=re.compile(r"/match/\d+\.html"))
            if not link:
                continue
            match_id = re.search(r"/match/(\d+)\.html", link.get("href") or "")
            if not match_id:
                continue
            team1 = texts[0]
            team2 = texts[1]
            winner = texts[2]
            # Drawn/tied rows omit the margin column, so later fields shift left.
            if len(texts) == 6:
                margin = ""
                ground, date_text = texts[3], texts[4]
            else:
                margin, ground, date_text = texts[3], texts[4], texts[5]
            start = parse_date(date_text)
            nations = TEST_NATIONS if match_type == "Test" else ODI_NATIONS
            if team1 not in nations or team2 not in nations:
                continue
            result = "won"
            winner_team = winner
            if winner.lower() in {"drawn", "draw"}:
                result = "draw"
                winner_team = None
            elif winner.lower() in {"tied", "tie"}:
                result = "tie"
                winner_team = None
            elif winner.lower() in {"no result", "n/r"}:
                result = "no result"
                winner_team = None
            win_runs = win_wickets = win_innings = None
            if "runs" in margin and "inns" not in margin:
                win_runs = parse_int(margin.split()[0])
            elif "wicket" in margin:
                win_wickets = parse_int(margin.split()[0])
            elif "inns" in margin:
                win_innings = 1
                parts = re.findall(r"\d+", margin)
                if parts:
                    win_runs = int(parts[-1])
            rows.append(
                {
                    "match_id": match_id.group(1),
                    "match_type": match_type,
                    "team1": team1,
                    "team2": team2,
                    "winner": winner_team,
                    "result": result,
                    "win_runs": win_runs,
                    "win_wickets": win_wickets,
                    "win_innings": win_innings,
                    "ground": ground,
                    "start_date": start.isoformat() if start else None,
                    "label": link.get_text(" ", strip=True),
                }
            )
    return rows


def _engine_table(html: str, required: tuple[str, ...] = ("Player", "Inns")):
    soup = BeautifulSoup(html, "lxml")
    for table in soup.select("table.engineTable"):
        headers = [th.get_text(" ", strip=True) for th in table.select("tr th")]
        if all(header in headers for header in required):
            return headers, table.select("tr.data1")
    return [], []


def _cell_map(headers: list[str], cells) -> dict[str, object]:
    mapped = {}
    for index, header in enumerate(headers):
        if index < len(cells):
            mapped[header] = cells[index]
    return mapped


def _engine_rows(html: str) -> list:
    _, rows = _engine_table(html)
    return rows


def page_count(html: str) -> int:
    match = re.search(r"Page <b>\d+</b> of <b>([\d,]+)</b>", html)
    if not match:
        return 1
    return int(match.group(1).replace(",", ""))


def parse_player_cell(cell) -> tuple[str | None, str | None, str | None]:
    link = cell.find("a")
    href = link.get("href") if link else ""
    cricinfo_id = None
    found = re.search(r"/player/(\d+)\.html", href or "")
    if found:
        cricinfo_id = found.group(1)
    text = cell.get_text(" ", strip=True)
    name = link.get_text(" ", strip=True) if link else text
    abbrev = None
    found = re.search(r"\(([A-Za-z]{2,5})\)$", text)
    if found:
        abbrev = found.group(1)
    return cricinfo_id, name, TEAM_ABBREV.get(abbrev, abbrev)


def parse_batting_rows(html: str) -> list[dict]:
    headers, body = _engine_table(html)
    rows = []
    for tr in body:
        cells = tr.select("td")
        mapped = _cell_map(headers, cells)
        if "Player" not in mapped:
            continue
        cricinfo_id, name, team = parse_player_cell(mapped["Player"])
        runs_text = mapped["Runs"].get_text(strip=True)
        if runs_text in {"DNB", "TDNB", "absent", "sub", "-", ""}:
            continue
        not_out = 1 if "*" in runs_text else 0
        opposition = mapped["Opposition"].get_text(" ", strip=True).lstrip("v ").strip()
        start = parse_date(mapped["Start Date"].get_text(" ", strip=True))
        rows.append(
            {
                "cricinfo_id": cricinfo_id,
                "name": name,
                "team": team,
                "runs": parse_int(runs_text) or 0,
                "balls": parse_int((mapped.get("BF") or mapped.get("Balls")).get_text(strip=True) if (mapped.get("BF") or mapped.get("Balls")) else ""),
                "fours": parse_int(mapped["4s"].get_text(strip=True)) if "4s" in mapped else None,
                "sixes": parse_int(mapped["6s"].get_text(strip=True)) if "6s" in mapped else None,
                "innings_number": parse_int(mapped["Inns"].get_text(strip=True)),
                "opposition": opposition,
                "ground": mapped["Ground"].get_text(" ", strip=True),
                "start_date": start.isoformat() if start else None,
                "not_out": not_out,
            }
        )
    return rows


def parse_bowling_rows(html: str) -> list[dict]:
    headers, body = _engine_table(html)
    rows = []
    for tr in body:
        cells = tr.select("td")
        mapped = _cell_map(headers, cells)
        if "Player" not in mapped or "Overs" not in mapped:
            continue
        cricinfo_id, name, team = parse_player_cell(mapped["Player"])
        overs_text = mapped["Overs"].get_text(strip=True)
        if overs_text in {"DNB", "TDNB", "sub", "absent", ""}:
            continue
        opposition = mapped["Opposition"].get_text(" ", strip=True).lstrip("v ").strip()
        start = parse_date(mapped["Start Date"].get_text(" ", strip=True))
        bpo = 6
        if "BPO" in mapped:
            bpo = parse_int(mapped["BPO"].get_text(strip=True)) or 6
        elif start and start.year < 1889:
            bpo = 4
        elif start and start.year < 1900:
            bpo = 5
        rows.append(
            {
                "cricinfo_id": cricinfo_id,
                "name": name,
                "team": team,
                "balls": overs_to_balls(overs_text, bpo),
                "maidens": parse_int(mapped["Mdns"].get_text(strip=True)) if "Mdns" in mapped else 0,
                "runs": parse_int(mapped["Runs"].get_text(strip=True)) or 0,
                "wickets": parse_int(mapped["Wkts"].get_text(strip=True)) or 0,
                "innings_number": parse_int(mapped["Inns"].get_text(strip=True)),
                "opposition": opposition,
                "ground": mapped["Ground"].get_text(" ", strip=True),
                "start_date": start.isoformat() if start else None,
            }
        )
    return rows


def parse_partners_cell(cell) -> tuple[list[tuple[str | None, str | None]], str | None]:
    """Two named batters plus a team abbrev, as Statsguru FOW lists them."""
    players: list[tuple[str | None, str | None]] = []
    for link in cell.find_all("a"):
        href = link.get("href") or ""
        found = re.search(r"/player/(\d+)\.html", href)
        players.append((found.group(1) if found else None, link.get_text(" ", strip=True)))
    text = cell.get_text(" ", strip=True)
    abbrev = None
    found = re.search(r"\(([A-Za-z]{2,5})\)$", text)
    if found:
        abbrev = found.group(1)
    return players, TEAM_ABBREV.get(abbrev, abbrev)


def parse_fow_rows(html: str) -> list[dict]:
    headers, body = _engine_table(html, required=("Partners", "Inns"))
    rows = []
    for tr in body:
        cells = tr.select("td")
        mapped = _cell_map(headers, cells)
        if "Partners" not in mapped or "Wkt" not in mapped:
            continue
        players, team = parse_partners_cell(mapped["Partners"])
        if len(players) < 2:
            continue
        runs_text = mapped["Runs"].get_text(strip=True)
        opposition = mapped["Opposition"].get_text(" ", strip=True).lstrip("v ").strip()
        start = parse_date(mapped["Start Date"].get_text(" ", strip=True))
        rows.append(
            {
                "cricinfo_id_1": players[0][0],
                "name_1": players[0][1],
                "cricinfo_id_2": players[1][0],
                "name_2": players[1][1],
                "team": team,
                "wicket_number": parse_int(mapped["Wkt"].get_text(strip=True)),
                "runs": parse_int(runs_text) or 0,
                "not_out": 1 if "*" in runs_text else 0,
                "innings_number": parse_int(mapped["Inns"].get_text(strip=True)),
                "opposition": opposition,
                "ground": mapped["Ground"].get_text(" ", strip=True),
                "start_date": start.isoformat() if start else None,
            }
        )
    return rows
