"""
Proxy ESPN cricket scores (unofficial public JSON) with TTL cache and normalization.

ESPN's Site API ``.../cricket/{league}/scoreboard`` returns 404 for cricket (see Public-ESPN-API
cricket.md). This router uses the working **scoreboard header** feed instead:

``https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket``

The ``league`` query param filters the flattened event list (IPL, ICC, etc.). ``region=us`` is
omitted when calling ESPN (their API returns 502 for ``region=us`` on this endpoint).

Only **T20** fixtures are returned: IPL / WPL (India) and **international** T20 (T20I, T20 World Cup,
etc.). ODIs, Tests, and non-IPL domestic T20 leagues (BBL, PSL, …) are dropped using ESPN note and
league text heuristics.

Match detail (in-app scorecard-shaped JSON) is proxied at ``GET .../summary`` using ESPN Site API
``/apis/site/v2/sports/cricket/{league_id}/summary?event={event_id}``. Each scoreboard row includes
``league_id`` from the header feed for that URL.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live/espn/cricket", tags=["live_espn"])

ESPN_USER_AGENT = (
    "Mozilla/5.0 (compatible; CricketMetrics/1.0; +https://github.com/) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ── Cache (per process) ─────────────────────────────────────────

_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_ORDER: list[str] = []

_SUMMARY_CACHE: dict[str, dict[str, Any]] = {}
_SUMMARY_ORDER: list[str] = []


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(1, int(raw.strip()))
    except ValueError:
        return default


def proxy_enabled() -> bool:
    return _env_bool("ESPN_LIVE_PROXY_ENABLED", True)


def cache_ttl_sec() -> int:
    return _env_int("ESPN_CRICKET_SCOREBOARD_CACHE_SEC", 90)


def cache_max_entries() -> int:
    return _env_int("ESPN_CRICKET_SCOREBOARD_CACHE_MAX_ENTRIES", 32)


def summary_cache_max_entries() -> int:
    return _env_int("ESPN_CRICKET_SUMMARY_CACHE_MAX_ENTRIES", 48)


def reset_cache_for_tests() -> None:
    """Clear cache (tests only)."""
    _CACHE.clear()
    _CACHE_ORDER.clear()
    _SUMMARY_CACHE.clear()
    _SUMMARY_ORDER.clear()


@dataclass
class NormalizedQuery:
    league: str
    dates: str | None
    region: str | None
    lang: str | None

    def cache_key(self) -> str:
        return "|".join(
            (
                self.league,
                self.dates or "",
                self.region or "",
                self.lang or "",
            )
        )

    def header_fetch_cache_key(self) -> str:
        """Upstream cricket header is global per region/lang; league filters client-side."""
        r = _effective_region_for_header(self.region) or ""
        lang = (self.lang or "").strip().lower()
        return f"header|{r}|{lang}"

    def response_query(self) -> dict[str, str | None]:
        return {
            "dates": self.dates,
            "region": self.region,
            "lang": self.lang,
        }


def _effective_region_for_header(region: str | None) -> str | None:
    """``region=us`` triggers 502 on the cricket header endpoint; treat as unspecified."""
    if not region:
        return None
    r = region.strip().lower()
    if r == "us":
        return None
    return r


def normalize_scoreboard_query(
    league: str,
    dates: str | None,
    region: str | None,
    lang: str | None,
) -> NormalizedQuery:
    """Normalize query params for ESPN and cache key. Raises ValueError on bad input."""
    lg = (league or "").strip().lower()
    if not lg:
        raise ValueError("league is required")

    d_raw = (dates or "").strip()
    dates_out: str | None = None
    if d_raw:
        dr = d_raw.lower()
        if len(dr) == 8 and dr.isdigit():
            dates_out = dr
        elif len(dr) == 17 and dr[8] == "-":
            a, b = dr[:8], dr[9:]
            if a.isdigit() and b.isdigit():
                dates_out = dr
            else:
                raise ValueError(
                    "dates range must be YYYYMMDD-YYYYMMDD (digits only in each part)"
                )
        else:
            raise ValueError(
                "dates must be YYYYMMDD or YYYYMMDD-YYYYMMDD, or empty for ESPN default"
            )

    r = (region or "").strip().lower() or None
    l = (lang or "").strip().lower() or None
    return NormalizedQuery(league=lg, dates=dates_out, region=r, lang=l)


def build_events_summary(payload: Any) -> list[dict[str, Any]]:
    """Defensive extraction for the UI."""
    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    out: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("id")
        event_id = str(eid) if eid is not None else ""
        name = str(ev.get("name") or "")
        short_name = str(ev.get("shortName") or "")
        status_str = ""
        state_str = ""
        st = ev.get("status")
        if isinstance(st, dict):
            state_str = str(st.get("state") or "")
            t = st.get("type")
            if isinstance(t, dict):
                status_str = str(
                    t.get("shortDetail") or t.get("detail") or t.get("description") or ""
                ).strip()
        competitors_out: list[dict[str, str]] = []
        comps = ev.get("competitions")
        if isinstance(comps, list):
            for comp in comps:
                if not isinstance(comp, dict):
                    continue
                clist = comp.get("competitors")
                if not isinstance(clist, list):
                    continue
                for row in clist:
                    if not isinstance(row, dict):
                        continue
                    team = row.get("team")
                    nm = ""
                    if isinstance(team, dict):
                        nm = str(
                            team.get("shortDisplayName")
                            or team.get("displayName")
                            or team.get("name")
                            or ""
                        ).strip()
                    sc = row.get("score")
                    score_display = ""
                    if isinstance(sc, dict):
                        score_display = str(sc.get("displayValue") or "")
                    elif sc is not None:
                        score_display = str(sc)
                    if nm or score_display:
                        competitors_out.append(
                            {"name": nm, "score_display": score_display}
                        )
        out.append(
            {
                "event_id": event_id,
                "name": name,
                "short_name": short_name,
                "status": status_str,
                "state": state_str,
                "competitors": competitors_out,
            }
        )
    return out


# Keywords for filtering global header feed by preset league slug (substring match on text blob).
_LEAGUE_FILTER_HINTS: dict[str, tuple[str, ...]] = {
    "ipl": ("ipl", "indian premier"),
    "icc.t20": ("t20 world", "icc", "world cup"),
    "icc.odi": ("odi world", "icc", "world cup", "champions trophy"),
    "icc.test": ("test championship", "icc", "ashes"),
    "bbl": ("big bash", "bbl"),
    "wbbl": ("women's big bash", "wbbl", "w-bbl"),
    "psl": ("pakistan super", "psl"),
}

# Only these formats are returned from the header feed (ODI/Test and non-IPL domestic T20 dropped).
_EXCLUDE_ODI_MARKERS: tuple[str, ...] = (
    "odi no.",
    "women odi",
    " wodi",
    "one-day international",
    "50-over match",
    " 50 over ",
    "50 over match",
    "odi world cup",
)
_EXCLUDE_TEST_MARKERS: tuple[str, ...] = (
    "test no.",
    "test match",
    "first-class",
    "5-day",
    "five-day",
    "four-innings",
    " multi-day",
)
_DOMESTIC_T20_NON_IPL: tuple[str, ...] = (
    "big bash",
    "wbbl",
    "w-bbl",
    "pakistan super",
    "psl",
    "caribbean premier",
    "cpl",
    "bangladesh premier",
    "bpl",
    "sa20",
    "the hundred",
    "vitality blast",
    "t20 blast",
    "super smash",
    "lanka premier",
    "global t20",
    "ilt20",
    "major league cricket",
    "county championship",
)


def _header_event_format_blob(ev: dict[str, Any], league_name: str) -> str:
    """Lowercase text used to classify T20 IPL vs T20I vs other formats."""
    parts: list[str] = [
        league_name,
        str(ev.get("name") or ""),
        str(ev.get("shortName") or ""),
    ]
    fs = ev.get("fullStatus")
    if isinstance(fs, dict):
        parts.append(str(fs.get("summary") or ""))
        parts.append(str(fs.get("longSummary") or ""))
    notes = ev.get("notes")
    if isinstance(notes, list):
        for n in notes:
            if isinstance(n, dict):
                parts.append(str(n.get("text") or ""))
    return " ".join(parts).lower()


def blob_is_ipl_or_t20_international(blob: str) -> bool:
    """
    True for Indian Premier League / WPL (India) or international T20 (T20I, World Cup T20, etc.).
    Excludes ODIs, Tests, and non-IPL domestic T20 (BBL, PSL, etc.).
    """
    b = (blob or "").lower()
    if any(m in b for m in _EXCLUDE_ODI_MARKERS):
        return False
    if any(m in b for m in _EXCLUDE_TEST_MARKERS):
        return False
    # Franchise T20 in India (avoid matching "ipl" inside unrelated words)
    if "indian premier" in b or "women's premier league" in b:
        return True
    if re.search(r"(^|[^a-z0-9])ipl([^a-z0-9]|$)", b):
        return True
    # Other franchise / domestic T20 leagues (not requested)
    if any(m in b for m in _DOMESTIC_T20_NON_IPL):
        return False
    # International T20 markers (ESPN notes / competition names)
    if "t20i" in b or "women t20" in b or "wt20" in b:
        return True
    if "t20 world" in b:
        return True
    if "icc men" in b and "t20" in b:
        return True
    if "icc women" in b and "t20" in b:
        return True
    if "asia cup" in b and "t20" in b:
        return True
    if "twenty20" in b and "international" in b:
        return True
    return False


def filter_events_by_league_slug(
    events: list[dict[str, Any]], slug: str
) -> list[dict[str, Any]]:
    """Narrow global feed to events plausibly matching the requested slug."""
    s = (slug or "").strip().lower()
    if not s or s in ("all", "any", "*"):
        return list(events)
    hints = _LEAGUE_FILTER_HINTS.get(s)
    if hints is None:
        hints = tuple(x for x in (s.replace(".", " "), s) if x)
    out: list[dict[str, Any]] = []
    for ev in events:
        blob = " ".join(
            [
                str(ev.get("league_name") or ""),
                str(ev.get("name") or ""),
                str(ev.get("short_name") or ""),
            ]
        ).lower()
        if any(h in blob for h in hints):
            out.append(ev)
    return out


def build_events_summary_from_header(payload: Any) -> list[dict[str, Any]]:
    """Parse scoreboard/header?sport=cricket JSON into events_summary rows."""
    if not isinstance(payload, dict):
        return []
    sports = payload.get("sports")
    if not isinstance(sports, list):
        return []
    out: list[dict[str, Any]] = []
    for sp in sports:
        if not isinstance(sp, dict):
            continue
        leagues = sp.get("leagues")
        if not isinstance(leagues, list):
            continue
        for lg in leagues:
            if not isinstance(lg, dict):
                continue
            lid = lg.get("id")
            league_id = str(lid).strip() if lid is not None else ""
            league_name = str(
                lg.get("name") or lg.get("shortName") or lg.get("shortAlternateName") or ""
            ).strip()
            events = lg.get("events")
            if not isinstance(events, list):
                continue
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                fmt_blob = _header_event_format_blob(ev, league_name)
                if not blob_is_ipl_or_t20_international(fmt_blob):
                    continue
                eid = ev.get("id")
                event_id = str(eid) if eid is not None else ""
                name = str(ev.get("name") or "")
                short_name = str(ev.get("shortName") or "")
                status = ""
                state = str(ev.get("status") or "").strip()
                situation_short = ""
                situation_long = ""
                batting_team_name = ""
                btid_s = ""
                fs = ev.get("fullStatus")
                if isinstance(fs, dict):
                    situation_short = str(fs.get("summary") or "").strip()
                    situation_long = str(fs.get("longSummary") or "").strip()
                    t = fs.get("type")
                    if isinstance(t, dict):
                        status = str(
                            t.get("shortDetail") or t.get("detail") or ""
                        ).strip()
                    btid = fs.get("battingTeamId")
                    if btid is not None:
                        btid_s = str(btid)

                competitors_out: list[dict[str, str]] = []
                comps = ev.get("competitors")
                if isinstance(comps, list):
                    for row in comps:
                        if not isinstance(row, dict):
                            continue
                        tid = row.get("id")
                        nm = str(
                            row.get("displayName")
                            or row.get("name")
                            or row.get("abbreviation")
                            or ""
                        ).strip()
                        score = str(row.get("score") or "").strip()
                        if tid is not None and btid_s and str(tid) == btid_s and nm:
                            batting_team_name = nm
                        if nm or score:
                            competitors_out.append(
                                {"name": nm, "score_display": score}
                            )

                recent_note = ""
                notes = ev.get("notes")
                if isinstance(notes, list):
                    for n in reversed(notes):
                        if not isinstance(n, dict):
                            continue
                        if str(n.get("type") or "") != "matchnote":
                            continue
                        tx = str(n.get("text") or "").strip()
                        if tx:
                            recent_note = tx
                            break

                espn_url = str(ev.get("link") or "").strip()

                score_bits: list[str] = []
                for c in competitors_out:
                    nm = (c.get("name") or "").strip()
                    sc = (c.get("score_display") or "").strip()
                    if nm and sc:
                        score_bits.append(f"{nm} {sc}")
                    elif nm:
                        score_bits.append(nm)
                    elif sc:
                        score_bits.append(sc)
                score_line = " · ".join(score_bits)

                out.append(
                    {
                        "event_id": event_id,
                        "name": name,
                        "short_name": short_name,
                        "status": status,
                        "state": state,
                        "competitors": competitors_out,
                        "score_line": score_line,
                        "league_name": league_name,
                        "league_id": league_id,
                        "situation_short": situation_short,
                        "situation_long": situation_long,
                        "batting_team_name": batting_team_name,
                        "recent_note": recent_note,
                        "espn_url": espn_url,
                    }
                )
    return out


def _normalize_matchcard_section(mc: dict[str, Any]) -> dict[str, Any]:
    """One block from summary ``matchcards`` (batting / bowling / partnerships)."""
    headline = str(mc.get("headline") or "").strip()
    hl = headline.lower()
    if hl.startswith("batting"):
        kind = "batting"
    elif hl.startswith("bowling"):
        kind = "bowling"
    elif hl.startswith("partnership"):
        kind = "partnerships"
    else:
        kind = "other"

    rows: list[dict[str, Any]] = []
    pd = mc.get("playerDetails")
    if isinstance(pd, list) and kind == "batting":
        for row in pd:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "player": str(row.get("playerName") or "").strip(),
                    "runs": str(row.get("runs") or "").strip(),
                    "balls": str(row.get("ballsFaced") or "").strip(),
                    "fours": str(row.get("fours") or "").strip(),
                    "sixes": str(row.get("sixes") or "").strip(),
                    "dismissal": str(row.get("dismissal") or "").strip(),
                }
            )
    elif isinstance(pd, list) and kind == "bowling":
        for row in pd:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "player": str(row.get("playerName") or "").strip(),
                    "overs": str(row.get("overs") or "").strip(),
                    "maidens": str(row.get("maidens") or "").strip(),
                    "conceded": str(row.get("conceded") or "").strip(),
                    "wickets": str(row.get("wickets") or "").strip(),
                    "economy": str(row.get("economyRate") or "").strip(),
                    "extras_note": str(row.get("nbw") or "").strip(),
                }
            )
    elif isinstance(pd, list) and kind == "partnerships":
        for row in pd:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "wicket_pair": str(row.get("partnershipWicketName") or "").strip(),
                    "runs": str(row.get("partnershipRuns") or "").strip(),
                    "overs": str(row.get("partnershipOvers") or "").strip(),
                    "batter_1": str(row.get("player1Name") or "").strip(),
                    "batter_2": str(row.get("player2Name") or "").strip(),
                    "batter_1_runs": str(row.get("player1Runs") or "").strip(),
                    "batter_2_runs": str(row.get("player2Runs") or "").strip(),
                }
            )

    total = mc.get("total")
    if isinstance(total, dict):
        total_s = str(
            total.get("display") or total.get("text") or total.get("summary") or ""
        ).strip()
    else:
        total_s = str(total or "").strip()

    return {
        "kind": kind,
        "headline": headline,
        "team_name": str(mc.get("teamName") or "").strip(),
        "innings_number": mc.get("inningsNumber"),
        "extras_summary": str(mc.get("extras") or "").strip() or None,
        "total_line": total_s or None,
        "runs_summary": str(mc.get("runs") or "").strip() or None,
        "rows": rows,
    }


def _extract_recent_plays(competition: dict[str, Any], limit: int = 36) -> list[dict[str, Any]]:
    """Flatten ``competition.commentaries`` ball events, newest first for UI."""
    com = competition.get("commentaries")
    if not isinstance(com, dict):
        return []
    plays: list[tuple[float, dict[str, Any]]] = []
    for play in com.values():
        if not isinstance(play, dict):
            continue
        so = play.get("sortOrder")
        try:
            key = float(so) if so is not None else 0.0
        except (TypeError, ValueError):
            key = 0.0
        plays.append((key, play))
    plays.sort(key=lambda x: x[0])
    tail = plays[-limit:]
    out: list[dict[str, Any]] = []
    for _k, p in reversed(tail):
        ov = p.get("over")
        over_s = ""
        if isinstance(ov, dict):
            o = ov.get("overs")
            b = ov.get("ball")
            if o is not None and b is not None:
                over_s = f"{o}.{b}"
            elif o is not None:
                over_s = str(o)
        dismiss = p.get("dismissal")
        dismiss_txt = ""
        if isinstance(dismiss, dict):
            dismiss_txt = str(dismiss.get("text") or "").strip()
        summary = dismiss_txt or str(p.get("text") or "").strip()
        if not summary:
            summary = str(p.get("preText") or "").strip()
        out.append(
            {
                "short_text": str(p.get("shortText") or "").strip(),
                "summary": summary,
                "home_score": str(p.get("homeScore") or "").strip(),
                "away_score": str(p.get("awayScore") or "").strip(),
                "over_display": over_s,
            }
        )
    return out


def extract_match_detail_for_ui(payload: dict[str, Any]) -> dict[str, Any]:
    """Pick stable fields from ESPN site summary JSON for in-app scorecard-style UI."""
    header = payload.get("header")
    header = header if isinstance(header, dict) else {}
    title = str(header.get("name") or "")
    short_title = str(header.get("shortName") or "")

    gid = payload.get("gameInfo")
    gid = gid if isinstance(gid, dict) else {}
    venue_o = gid.get("venue")
    venue_o = venue_o if isinstance(venue_o, dict) else {}
    venue = str(venue_o.get("fullName") or "").strip() or None

    notes_raw = payload.get("notes")
    notes_out: list[dict[str, str]] = []
    if isinstance(notes_raw, list):
        for n in notes_raw:
            if not isinstance(n, dict):
                continue
            tx = str(n.get("text") or "").strip()
            if not tx:
                continue
            notes_out.append(
                {
                    "type": str(n.get("type") or ""),
                    "text": tx,
                }
            )

    comps_h = header.get("competitions")
    competition: dict[str, Any] | None = None
    if isinstance(comps_h, list) and comps_h and isinstance(comps_h[0], dict):
        competition = comps_h[0]

    status_block: dict[str, Any] = {}
    teams_out: list[dict[str, Any]] = []
    fow_out: list[dict[str, Any]] = []

    if competition is not None:
        st = competition.get("status")
        if isinstance(st, dict):
            t = st.get("type")
            t = t if isinstance(t, dict) else {}
            btid = st.get("battingTeamId")
            status_block = {
                "summary": str(st.get("summary") or "").strip(),
                "display_clock": str(st.get("displayClock") or "").strip(),
                "short_detail": str(t.get("shortDetail") or "").strip(),
                "detail": str(t.get("detail") or "").strip(),
                "batting_team_id": str(btid).strip() if btid is not None else "",
            }
        crows = competition.get("competitors")
        if isinstance(crows, list):
            for row in crows:
                if not isinstance(row, dict):
                    continue
                team_o = row.get("team")
                team_o = team_o if isinstance(team_o, dict) else {}
                name = str(team_o.get("displayName") or team_o.get("name") or "").strip()
                abbr = str(team_o.get("abbreviation") or "").strip()
                score_s = str(row.get("score") or "").strip()
                home_away = str(row.get("homeAway") or "").strip()
                tid = row.get("id")
                innings_out: list[dict[str, Any]] = []
                lss = row.get("linescores")
                if isinstance(lss, list):
                    for ls in lss:
                        if not isinstance(ls, dict):
                            continue
                        innings_out.append(
                            {
                                "period": ls.get("period"),
                                "runs": ls.get("runs"),
                                "wickets": ls.get("wickets"),
                                "overs": ls.get("overs"),
                                "score": str(ls.get("score") or "").strip(),
                                "is_batting": bool(ls.get("isBatting")),
                                "description": str(ls.get("description") or "").strip(),
                            }
                        )
                        fows = ls.get("fow")
                        if isinstance(fows, list):
                            for fw in fows[:60]:
                                if not isinstance(fw, dict):
                                    continue
                                ath = fw.get("athlete")
                                ath = ath if isinstance(ath, dict) else {}
                                batter = str(
                                    ath.get("displayName") or ath.get("shortName") or ""
                                ).strip()
                                fow_out.append(
                                    {
                                        "team_score_runs": fw.get("runs"),
                                        "wicket_number": fw.get("wicketNumber"),
                                        "over": fw.get("wicketOver"),
                                        "batter_out": batter,
                                        "team_name": name,
                                    }
                                )
                teams_out.append(
                    {
                        "id": str(tid) if tid is not None else "",
                        "name": name,
                        "abbreviation": abbr,
                        "home_away": home_away,
                        "score": score_s,
                        "innings": innings_out,
                    }
                )

    matchcard_sections: list[dict[str, Any]] = []
    mcards = payload.get("matchcards")
    if isinstance(mcards, list):
        for mc in mcards:
            if isinstance(mc, dict):
                matchcard_sections.append(_normalize_matchcard_section(mc))

    recent_balls: list[dict[str, Any]] = []
    if competition is not None:
        recent_balls = _extract_recent_plays(competition, limit=40)

    return {
        "title": title,
        "short_title": short_title,
        "venue": venue,
        "notes": notes_out,
        "status": status_block,
        "teams": teams_out,
        "fall_of_wickets": fow_out[:50],
        "matchcard_sections": matchcard_sections,
        "recent_balls": recent_balls,
    }


def _summary_cache_key(league_id: str, event_id: str) -> str:
    return f"{league_id}|{event_id}"


def _enforce_summary_cache_cap() -> None:
    max_e = summary_cache_max_entries()
    while len(_SUMMARY_CACHE) > max_e and _SUMMARY_ORDER:
        oldest = _SUMMARY_ORDER.pop(0)
        _SUMMARY_CACHE.pop(oldest, None)


def _touch_summary_order(key: str) -> None:
    if key in _SUMMARY_ORDER:
        _SUMMARY_ORDER.remove(key)
    _SUMMARY_ORDER.append(key)


def _build_cricket_summary_url(league_id: str, event_id: str) -> str:
    from urllib.parse import urlencode

    return (
        f"https://site.api.espn.com/apis/site/v2/sports/cricket/{league_id}/summary?"
        + urlencode({"event": event_id})
    )


def _validate_numeric_id(label: str, raw: str) -> str:
    s = (raw or "").strip()
    if not s.isdigit():
        raise ValueError(f"{label} must be a positive integer id")
    return s


def _enforce_cache_cap() -> None:
    """Drop oldest entries when over max size. TTL does not delete entries (stale rows are needed for upstream-error fallback)."""
    max_e = cache_max_entries()
    while len(_CACHE) > max_e and _CACHE_ORDER:
        oldest = _CACHE_ORDER.pop(0)
        _CACHE.pop(oldest, None)


def _touch_order(key: str) -> None:
    if key in _CACHE_ORDER:
        _CACHE_ORDER.remove(key)
    _CACHE_ORDER.append(key)


async def _http_get_json(url: str) -> tuple[int | None, dict[str, Any] | None, str | None]:
    """GET JSON from ESPN. One retry on transport errors only."""
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    headers = {"User-Agent": ESPN_USER_AGENT, "Accept": "application/json"}
    last_err: str | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return r.status_code, None, f"HTTP {r.status_code}"
            try:
                data = r.json()
            except Exception as e:
                return r.status_code, None, f"Invalid JSON: {e}"
            if not isinstance(data, dict):
                return r.status_code, None, "Response JSON is not an object"
            return r.status_code, data, None
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
            last_err = str(e)
            if attempt == 0:
                logger.warning("ESPN scoreboard transport error (retrying): %s", e)
                continue
            return None, None, last_err
        except httpx.HTTPError as e:
            return None, None, str(e)
    return None, None, last_err


def _build_cricket_header_url(nq: NormalizedQuery) -> str:
    from urllib.parse import urlencode

    params: dict[str, str] = {"sport": "cricket"}
    r = _effective_region_for_header(nq.region)
    if r:
        params["region"] = r
    if nq.lang:
        params["lang"] = nq.lang
    return "https://site.web.api.espn.com/apis/v2/scoreboard/header?" + urlencode(
        params
    )


def _wrapper(
    *,
    enabled: bool,
    nq: NormalizedQuery | None,
    fetched_at: str | None,
    served_from_cache: bool,
    refresh_interval_seconds: int,
    payload: dict[str, Any] | None,
    events_summary: list[dict[str, Any]] | None,
    upstream_http_status: int | None,
    upstream_error: str | None,
    message: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "enabled": enabled,
        "served_from_cache": served_from_cache,
        "refresh_interval_seconds": refresh_interval_seconds,
        "upstream_http_status": upstream_http_status,
        "upstream_error": upstream_error,
        "message": message,
    }
    if nq is not None:
        body["league"] = nq.league
        body["query"] = nq.response_query()
    if fetched_at is not None:
        body["fetched_at"] = fetched_at
    if payload is not None:
        body["payload"] = payload
    if events_summary is not None:
        body["events_summary"] = events_summary
    return body


@router.get("/scoreboard")
async def espn_cricket_scoreboard(
    league: str = Query(..., min_length=1, description="ESPN cricket league slug, e.g. ipl"),
    dates: str | None = Query(None, description="YYYYMMDD or YYYYMMDD-YYYYMMDD"),
    region: str | None = Query(None),
    lang: str | None = Query(None),
) -> dict[str, Any]:
    """
    Proxied cricket scores from ESPN Web API scoreboard header (global feed), filtered by
    ``league`` slug. Only T20 IPL/WPL and international T20 matches are included.

    ``dates`` is accepted for API compatibility but does not change the upstream request (the header
    feed is ESPN-curated).
    """
    refresh_sec = cache_ttl_sec()
    if not proxy_enabled():
        logger.info("ESPN scoreboard: proxy disabled (kill-switch)")
        return _wrapper(
            enabled=False,
            nq=None,
            fetched_at=None,
            served_from_cache=False,
            refresh_interval_seconds=refresh_sec,
            payload=None,
            events_summary=None,
            upstream_http_status=None,
            upstream_error=None,
            message="ESPN live proxy is disabled (ESPN_LIVE_PROXY_ENABLED).",
        )

    try:
        nq = normalize_scoreboard_query(league, dates, region, lang)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    fetch_key = nq.header_fetch_cache_key()
    now = time.time()
    ttl = float(refresh_sec)

    entry = _CACHE.get(fetch_key)
    if entry and (now - float(entry["stored_at"]) <= ttl):
        summary_full = entry.get("events_summary_full") or []
        filtered = filter_events_by_league_slug(list(summary_full), nq.league)
        logger.info(
            "ESPN cricket header cache fresh hit league=%s fetch_key=%s filtered=%s",
            nq.league,
            fetch_key,
            len(filtered),
        )
        return _wrapper(
            enabled=True,
            nq=nq,
            fetched_at=entry["fetched_at_iso"],
            served_from_cache=True,
            refresh_interval_seconds=refresh_sec,
            payload=entry.get("payload"),
            events_summary=filtered,
            upstream_http_status=entry.get("upstream_http_status"),
            upstream_error=None,
            message=None,
        )

    url = _build_cricket_header_url(nq)
    logger.info("ESPN cricket header fetch league=%s url=%s", nq.league, url)
    http_st, payload, err = await _http_get_json(url)

    fetched_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )

    if payload is not None:
        summary_full = build_events_summary_from_header(payload)
        filtered = filter_events_by_league_slug(summary_full, nq.league)
        _CACHE[fetch_key] = {
            "stored_at": now,
            "fetched_at_iso": fetched_iso,
            "payload": payload,
            "events_summary_full": summary_full,
            "upstream_http_status": http_st,
        }
        _touch_order(fetch_key)
        _enforce_cache_cap()
        logger.info(
            "ESPN cricket header ok league=%s status=%s total_events=%s after_filter=%s",
            nq.league,
            http_st,
            len(summary_full),
            len(filtered),
        )
        return _wrapper(
            enabled=True,
            nq=nq,
            fetched_at=fetched_iso,
            served_from_cache=False,
            refresh_interval_seconds=refresh_sec,
            payload=payload,
            events_summary=filtered,
            upstream_http_status=http_st,
            upstream_error=None,
            message=None,
        )

    # Upstream failed
    if entry:
        logger.warning(
            "ESPN scoreboard upstream failed; serving stale league=%s err=%s",
            nq.league,
            err,
        )
        summary_full = entry.get("events_summary_full") or []
        filtered = filter_events_by_league_slug(list(summary_full), nq.league)
        return _wrapper(
            enabled=True,
            nq=nq,
            fetched_at=entry["fetched_at_iso"],
            served_from_cache=True,
            refresh_interval_seconds=refresh_sec,
            payload=entry.get("payload"),
            events_summary=filtered,
            upstream_http_status=http_st,
            upstream_error=err,
            message="Serving stale data due to upstream failure.",
        )

    logger.warning(
        "ESPN cricket header upstream failed; no cache league=%s err=%s",
        nq.league,
        err,
    )
    return _wrapper(
        enabled=True,
        nq=nq,
        fetched_at=None,
        served_from_cache=False,
        refresh_interval_seconds=refresh_sec,
        payload=None,
        events_summary=[],
        upstream_http_status=http_st,
        upstream_error=err,
        message="Could not load scoreboard and no cached data is available.",
    )


def _summary_response(
    *,
    enabled: bool,
    league_id: str,
    event_id: str,
    fetched_at: str | None,
    served_from_cache: bool,
    refresh_interval_seconds: int,
    detail: dict[str, Any] | None,
    upstream_http_status: int | None,
    upstream_error: str | None,
    message: str | None,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "league_id": league_id,
        "event_id": event_id,
        "fetched_at": fetched_at,
        "served_from_cache": served_from_cache,
        "refresh_interval_seconds": refresh_interval_seconds,
        "detail": detail,
        "upstream_http_status": upstream_http_status,
        "upstream_error": upstream_error,
        "message": message,
    }


@router.get("/summary")
async def espn_cricket_match_summary(
    league_id: str = Query(..., min_length=1, description="ESPN league/series id from header feed"),
    event_id: str = Query(..., min_length=1, description="ESPN event / game id"),
) -> dict[str, Any]:
    """
    Proxied **match summary** (scorecard-shaped JSON) for one fixture.

    ESPN requires the numeric series id in the path:
    ``/apis/site/v2/sports/cricket/{league_id}/summary?event={event_id}``.
    The live list includes ``league_id`` on each row for this purpose.
    """
    refresh_sec = cache_ttl_sec()
    if not proxy_enabled():
        logger.info("ESPN match summary: proxy disabled (kill-switch)")
        return _summary_response(
            enabled=False,
            league_id="",
            event_id="",
            fetched_at=None,
            served_from_cache=False,
            refresh_interval_seconds=refresh_sec,
            detail=None,
            upstream_http_status=None,
            upstream_error=None,
            message="ESPN live proxy is disabled (ESPN_LIVE_PROXY_ENABLED).",
        )

    try:
        lg = _validate_numeric_id("league_id", league_id)
        ev = _validate_numeric_id("event_id", event_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    sk = _summary_cache_key(lg, ev)
    now = time.time()
    ttl = float(refresh_sec)

    entry = _SUMMARY_CACHE.get(sk)
    if entry and (now - float(entry["stored_at"]) <= ttl):
        logger.info("ESPN cricket summary cache fresh hit league=%s event=%s", lg, ev)
        return _summary_response(
            enabled=True,
            league_id=lg,
            event_id=ev,
            fetched_at=entry["fetched_at_iso"],
            served_from_cache=True,
            refresh_interval_seconds=refresh_sec,
            detail=entry.get("detail"),
            upstream_http_status=entry.get("upstream_http_status"),
            upstream_error=None,
            message=None,
        )

    url = _build_cricket_summary_url(lg, ev)
    logger.info("ESPN cricket summary fetch league=%s event=%s", lg, ev)
    http_st, payload, err = await _http_get_json(url)

    fetched_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )

    if payload is not None and err is None:
        c = payload.get("code")
        if isinstance(c, int) and c >= 400:
            err = str(payload.get("message") or f"ESPN error {c}")
            http_st = c
            payload = None

    if payload is not None:
        detail = extract_match_detail_for_ui(payload)
        _SUMMARY_CACHE[sk] = {
            "stored_at": now,
            "fetched_at_iso": fetched_iso,
            "detail": detail,
            "upstream_http_status": http_st,
        }
        _touch_summary_order(sk)
        _enforce_summary_cache_cap()
        return _summary_response(
            enabled=True,
            league_id=lg,
            event_id=ev,
            fetched_at=fetched_iso,
            served_from_cache=False,
            refresh_interval_seconds=refresh_sec,
            detail=detail,
            upstream_http_status=http_st,
            upstream_error=None,
            message=None,
        )

    if entry:
        logger.warning(
            "ESPN match summary upstream failed; serving stale league=%s event=%s err=%s",
            lg,
            ev,
            err,
        )
        return _summary_response(
            enabled=True,
            league_id=lg,
            event_id=ev,
            fetched_at=entry["fetched_at_iso"],
            served_from_cache=True,
            refresh_interval_seconds=refresh_sec,
            detail=entry.get("detail"),
            upstream_http_status=entry.get("upstream_http_status"),
            upstream_error=err,
            message="Serving stale data due to upstream failure.",
        )

    logger.warning(
        "ESPN match summary upstream failed; no cache league=%s event=%s err=%s",
        lg,
        ev,
        err,
    )
    return _summary_response(
        enabled=True,
        league_id=lg,
        event_id=ev,
        fetched_at=None,
        served_from_cache=False,
        refresh_interval_seconds=refresh_sec,
        detail=None,
        upstream_http_status=http_st,
        upstream_error=err,
        message="Could not load match summary and no cached data is available.",
    )
