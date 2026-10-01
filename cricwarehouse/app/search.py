"""Natural-language search: peel teams/years/scores from a query, and match people fast.

The old path treated leftover words as the player name and scanned `xi` on every
keystroke. “Sachin Tendulkar New Zealand 94” became a person called that, then a
full application scan. This module keeps a process-local people/team index and
lifts cricket English into the same tokens the query executor already understands.
"""

from __future__ import annotations

import re
import threading
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Any

from cricwarehouse.competitions import FORMAT_ALIASES, normalize_format
from cricwarehouse.paths import WAREHOUSE

# Longest aliases first when matching. Canonical names match Cricsheet sides.
_TEAM_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("New Zealand", ("new zealand", "nz", "kiwis", "kiwi")),
    ("South Africa", ("south africa", "sa", "proteas", "rsa")),
    ("West Indies", ("west indies", "wi", "windies", "west indies cricket")),
    ("Sri Lanka", ("sri lanka", "sl", "lankans")),
    ("Australia", ("australia", "aus", "aussies", "aussie")),
    ("England", ("england", "eng", "english")),
    ("Pakistan", ("pakistan", "pak")),
    ("Bangladesh", ("bangladesh", "ban", "tigers")),
    ("Afghanistan", ("afghanistan", "afg")),
    ("Zimbabwe", ("zimbabwe", "zim")),
    ("Ireland", ("ireland", "ire")),
    ("India", ("india", "ind", "bharat")),
    ("Netherlands", ("netherlands", "holland", "ned")),
    ("Scotland", ("scotland", "sco")),
    ("United Arab Emirates", ("united arab emirates", "uae")),
    ("Papua New Guinea", ("papua new guinea", "png")),
    ("United States of America", ("united states of america", "usa", "united states")),
    ("Chennai Super Kings", ("chennai super kings", "csk", "chennai")),
    ("Mumbai Indians", ("mumbai indians", "mi")),
    ("Royal Challengers Bengaluru", ("royal challengers bengaluru", "royal challengers bangalore", "rcb")),
    ("Kolkata Knight Riders", ("kolkata knight riders", "kkr")),
    ("Sunrisers Hyderabad", ("sunrisers hyderabad", "srh", "sunrisers")),
    ("Rajasthan Royals", ("rajasthan royals", "rr")),
    ("Delhi Capitals", ("delhi capitals", "delhi daredevils", "dc", "dd")),
    ("Punjab Kings", ("punjab kings", "kings xi punjab", "pbks", "kxip")),
    ("Gujarat Titans", ("gujarat titans", "gt")),
    ("Lucknow Super Giants", ("lucknow super giants", "lsg")),
    ("Gujarat Lions", ("gujarat lions")),
    ("Rising Pune Supergiant", ("rising pune supergiant", "rising pune supergiants", "rps")),
    ("Deccan Chargers", ("deccan chargers")),
    ("Pune Warriors", ("pune warriors", "pune warriors india")),
    ("Kochi Tuskers Kerala", ("kochi tuskers kerala", "kochi tuskers")),
    ("Sydney Sixers", ("sydney sixers", "sixers")),
    ("Sydney Thunder", ("sydney thunder", "thunder")),
    ("Melbourne Stars", ("melbourne stars", "stars")),
    ("Melbourne Renegades", ("melbourne renegades", "renegades")),
    ("Perth Scorchers", ("perth scorchers", "scorchers")),
    ("Hobart Hurricanes", ("hobart hurricanes", "hurricanes")),
    ("Brisbane Heat", ("brisbane heat", "heat")),
    ("Adelaide Strikers", ("adelaide strikers", "strikers")),
    ("Delhi Capitals Women", ("delhi capitals women",)),
)

_VENUE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Lord's", ("lord's", "lords")),
    ("Eden Gardens", ("eden gardens",)),
    ("Eden Park", ("eden park",)),
    ("Melbourne Cricket Ground", ("melbourne cricket ground", "mcg")),
    ("Sydney Cricket Ground", ("sydney cricket ground", "scg")),
    ("Wankhede Stadium", ("wankhede", "wankhede stadium")),
    ("M Chinnaswamy Stadium", ("chinnaswamy", "chinnaswamy stadium")),
    ("The Gabba", ("gabba", "the gabba")),
    ("The Oval", ("the oval", "kennington oval", "oval")),
    ("Headingley", ("headingley",)),
    ("Edgbaston", ("edgbaston",)),
    ("Trent Bridge", ("trent bridge",)),
    ("Old Trafford", ("old trafford",)),
    ("Newlands", ("newlands",)),
    ("The Wanderers", ("wanderers", "the wanderers")),
    ("Basin Reserve", ("basin reserve",)),
    ("Galle", ("galle", "galle international stadium")),
    ("Pallekele", ("pallekele",)),
    ("Sharjah", ("sharjah",)),
    ("Dubai", ("dubai", "dubai international")),
    ("Abu Dhabi", ("abu dhabi",)),
    ("Sabina Park", ("sabina park",)),
    ("Kensington Oval", ("kensington oval", "barbados")),
)

_EVENT_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("world cup", ("world cup", "worldcup", "cwc", "t20 world cup", "wt20")),
    ("ashes", ("ashes", "the ashes")),
    ("champions trophy", ("champions trophy",)),
    ("asia cup", ("asia cup",)),
    ("world test championship", ("world test championship", "wtc")),
    ("ipl", ("indian premier league",)),
)

_VS = frozenset({"vs", "v", "versus", "against"})
_FOR = frozenset({"for"})
_AT = frozenset({"at"})
_SKIP = frozenset({"the", "of", "and", "in", "on", "from", "to", "a", "an"})
_GENDER = {
    "men": "male",
    "mens": "male",
    "men's": "male",
    "male": "male",
    "women": "female",
    "womens": "female",
    "women's": "female",
    "female": "female",
}

_YEAR = re.compile(r"^(?:(\d{4})(?:\s*[-–]\s*(\d{2,4}))?|'(\d{2}))$")
_SCORE = re.compile(r"^\d{1,3}$")
_SLUG = re.compile(r"[^a-z0-9]+")
_MULTI_SPACE = re.compile(r"\s+")

_lock = threading.Lock()
_INDEX: "SearchIndex | None" = None
_INDEX_STAMP: tuple[float, float] | None = None


def _norm(s: str) -> str:
    return _MULTI_SPACE.sub(" ", (s or "").strip().lower())


def _slug(s: str) -> str:
    return _SLUG.sub("-", _norm(s)).strip("-")


def _year_from_two(yy: str) -> str:
    n = int(yy)
    return f"{2000 + n}" if n <= 30 else f"{1900 + n}"


def _expand_year_token(raw: str) -> tuple[str, str] | None:
    m = _YEAR.match(raw)
    if not m:
        return None
    if m.group(3):
        y = _year_from_two(m.group(3))
        return y, y
    start = m.group(1)
    end = m.group(2)
    if not end:
        return start, start
    if len(end) == 2:
        end = start[:2] + end
    return start, end


@dataclass(frozen=True)
class AliasHit:
    canonical: str
    words: int
    kind: str  # team | venue | event | format


def _compile_aliases() -> list[tuple[tuple[str, ...], AliasHit]]:
    rows: list[tuple[tuple[str, ...], AliasHit]] = []
    for canon, aliases in _TEAM_GROUPS:
        seen = {canon.lower(), *aliases}
        for alias in seen:
            parts = tuple(_norm(alias).split())
            if parts:
                rows.append((parts, AliasHit(canon, len(parts), "team")))
    for canon, aliases in _VENUE_ALIASES:
        for alias in {canon.lower(), *aliases}:
            parts = tuple(_norm(alias).split())
            if parts:
                rows.append((parts, AliasHit(canon, len(parts), "venue")))
    for needle, aliases in _EVENT_ALIASES:
        for alias in {needle, *aliases}:
            parts = tuple(_norm(alias).split())
            if parts:
                rows.append((parts, AliasHit(needle, len(parts), "event")))
    for raw, key in FORMAT_ALIASES.items():
        parts = tuple(_norm(raw).split())
        if parts:
            rows.append((parts, AliasHit(key, len(parts), "format")))
    rows.sort(key=lambda r: (-r[1].words, -len(" ".join(r[0]))))
    return rows


_ALIAS_ROWS = _compile_aliases()


def match_alias(words: list[str], i: int, *, kinds: set[str] | None = None, prefix: bool = False) -> AliasHit | None:
    """Longest alias starting at `i`. Exact first; prefix only for the last word."""
    n = len(words)
    best: AliasHit | None = None
    for parts, hit in _ALIAS_ROWS:
        if kinds and hit.kind not in kinds:
            continue
        k = len(parts)
        if i + k > n and not prefix:
            continue
        if i + k - 1 > n - 1 and not prefix:
            continue
        take = min(k, n - i)
        if take <= 0:
            continue
        chunk = [_norm(w).strip(".,") for w in words[i : i + take]]
        if take == k and chunk == list(parts):
            if best is None or hit.words > best.words:
                best = hit
            continue
        if prefix and take <= k and chunk and all(
            (chunk[j] == parts[j]) if j < take - 1 else parts[j].startswith(chunk[j])
            for j in range(take)
        ):
            if len(chunk[-1]) < (1 if take > 1 else 4):
                continue
            if best is None or take > best.words:
                best = AliasHit(hit.canonical, take, hit.kind)
    return best


def is_known_team(name: str) -> str | None:
    words = _norm(name).split()
    if not words:
        return None
    hit = match_alias(words, 0, kinds={"team"})
    if hit and hit.words == len(words):
        return hit.canonical
    return None


@dataclass
class Lifted:
    tokens: dict[str, str] = field(default_factory=dict)
    player: str | None = None
    mode: str | None = None
    heuristic: str | None = None


def lift_bare(rest: str, existing: dict[str, str] | None = None) -> Lifted:
    """Pull cricket entities out of leftover free text."""
    text = _MULTI_SPACE.sub(" ", (rest or "").strip())
    out = Lifted()
    if not text:
        return out
    vs = re.split(r"\s+v(?:s)?\.?\s+", text, maxsplit=1, flags=re.I)
    if len(vs) == 2 and vs[0].strip() and vs[1].strip():
        left = _peel(vs[0].strip(), existing)
        right = _peel(vs[1].strip(), existing)
        _merge_filters(out.tokens, left.tokens, right.tokens, existing)
        lp, rp = left.player, right.player
        lt = left.tokens.get("side") or left.tokens.get("opposition") or left.tokens.get("team")
        rt = right.tokens.get("side") or right.tokens.get("opposition") or right.tokens.get("team")
        if lp and rt and not rp:
            out.player = lp
            out.tokens["opposition"] = rt
        elif rp and lt and not lp:
            out.player = rp
            out.tokens["opposition"] = lt
        elif lt and rt and not lp and not rp:
            out.tokens["home"] = lt
            out.tokens["away"] = rt
            out.mode = "matches"
        elif lp and rp:
            out.tokens["compare"] = f"{lp},{rp}"
            out.mode = "compare"
        elif lp or rp:
            out.player = lp or rp
            if lt or rt:
                out.tokens["opposition"] = rt or lt
        elif lt or rt:
            if lt and rt:
                out.tokens["home"] = lt
                out.tokens["away"] = rt
                out.mode = "matches"
            else:
                out.tokens["side"] = lt or rt
        out.heuristic = _heuristic(out)
        return out

    peeled = _peel(text, existing)
    out.tokens = peeled.tokens
    out.player = peeled.player
    out.heuristic = _heuristic(out)
    return out


def _merge_filters(dest: dict[str, str], *sources: dict[str, str] | None) -> None:
    for src in sources:
        if not src:
            continue
        for key in ("year", "years", "format", "comp", "gender", "venue", "event", "runs", "from", "to"):
            if key in src and key not in dest:
                dest[key] = src[key]


def _peel(text: str, existing: dict[str, str] | None = None) -> Lifted:
    existing = existing or {}
    words = text.split()
    player_words: list[str] = []
    tokens: dict[str, str] = {}
    pending: str | None = None
    i = 0
    while i < len(words):
        raw = words[i]
        wl = raw.lower().strip(".,")
        years = _expand_year_token(wl)
        if years and "year" not in existing and "years" not in existing and "year" not in tokens:
            a, b = years
            if a == b:
                tokens["year"] = a
            else:
                tokens["years"] = f"{a}-{b}"
            i += 1
            pending = None
            continue
        if wl in _GENDER and "gender" not in existing:
            tokens["gender"] = _GENDER[wl]
            i += 1
            continue
        if wl in _VS:
            pending = "opposition"
            i += 1
            continue
        if wl in _FOR:
            pending = "team"
            i += 1
            continue
        if wl in _AT:
            pending = "venue"
            i += 1
            continue
        if wl in _SKIP:
            i += 1
            continue
        kinds = {"team", "venue", "event", "format"}
        if pending == "venue":
            kinds = {"venue", "team"}
        hit = match_alias(words, i, kinds=kinds)
        if hit:
            if hit.kind == "team":
                key = pending if pending in {"opposition", "team"} else "side"
                tokens[key] = hit.canonical
            elif hit.kind == "venue" and "venue" not in existing:
                tokens["venue"] = hit.canonical
            elif hit.kind == "event" and "event" not in existing:
                tokens["event"] = hit.canonical
            elif hit.kind == "format" and "format" not in existing and "comp" not in existing:
                tokens["format"] = hit.canonical
            i += hit.words
            pending = None
            continue
        if _SCORE.match(wl) and "runs" not in existing and "runs" not in tokens:
            # Trailing or isolated score. Keep earlier numbers as part of the name
            # only when they sit in the middle of words (almost never).
            tokens["runs"] = wl
            i += 1
            pending = None
            continue
        player_words.append(raw)
        pending = None
        i += 1

    leftover = [w for w in player_words if not _SCORE.match(w)]
    # A 1–3 digit number that was not trailing (e.g. "89 kohli") still counts.
    if leftover != player_words and "runs" not in tokens:
        nums = [w for w in player_words if _SCORE.match(w)]
        if nums:
            tokens["runs"] = nums[-1]

    player = _MULTI_SPACE.sub(" ", " ".join(leftover)).strip(" ,.-") or None
    if player:
        player, extra = _resolve_player_span(player)
        for key, val in extra.items():
            tokens.setdefault(key, val)
    return Lifted(tokens=tokens, player=player)


def _resolve_player_span(player: str) -> tuple[str, dict[str, str]]:
    """Keep the longest prefix that is a person; leftover often an unfinished team."""
    words = player.split()
    if len(words) < 2:
        return player, {}
    idx = get_index()
    if idx is None:
        return player, {}
    extra: dict[str, str] = {}
    for end in range(len(words), 0, -1):
        chunk = " ".join(words[:end])
        hits = idx.search(chunk, limit=1)
        if not hits or not _name_covers(hits[0], chunk):
            continue
        tail = words[end:]
        if tail:
            team = match_alias(tail, 0, kinds={"team", "venue", "event"}, prefix=True)
            if team:
                extra[team.kind if team.kind != "team" else "side"] = team.canonical
                return chunk, extra
            if end < len(words):
                return chunk, extra
        return chunk, extra
    return player, extra


def _name_covers(person: dict, chunk: str) -> bool:
    tokens = _norm(chunk).split()
    hay = _norm(
        " ".join(
            [
                person.get("display_name") or "",
                person.get("unique_name") or "",
                person.get("slug") or "",
            ]
        )
    )
    name_tokens = hay.replace("-", " ").split()
    if not tokens:
        return False
    return all(_token_hits(t, name_tokens) for t in tokens)


def _token_hits(token: str, name_tokens: list[str]) -> bool:
    if len(token) == 1:
        return any(n.startswith(token) for n in name_tokens)
    return any(n == token or n.startswith(token) for n in name_tokens)


def _heuristic(lifted: Lifted) -> str | None:
    bits: list[str] = []
    if lifted.player:
        bits.append(lifted.player)
    tokens = lifted.tokens
    if tokens.get("opposition"):
        bits.append(f"vs {tokens['opposition']}")
    elif tokens.get("side"):
        bits.append(tokens["side"])
    elif tokens.get("home") and tokens.get("away"):
        bits.append(f"{tokens['home']} v {tokens['away']}")
    if tokens.get("team") and not tokens.get("opposition"):
        bits.append(f"for {tokens['team']}")
    if tokens.get("venue"):
        bits.append(f"at {tokens['venue']}")
    if tokens.get("event"):
        bits.append(tokens["event"])
    year = tokens.get("year") or tokens.get("years")
    if year:
        bits.append(year)
    if tokens.get("format"):
        bits.append(tokens["format"])
    if tokens.get("runs"):
        bits.append(f"{tokens['runs']} runs")
    if tokens.get("runs") and lifted.player and len(bits) == 2:
        return f"runs:{tokens['runs']} (exact)"
    if len(bits) <= 1:
        return f"runs:{tokens['runs']} (exact)" if tokens.get("runs") else None
    return " · ".join(bits)


def interpretation(tokens: dict[str, str], player: str | None = None) -> str:
    lifted = Lifted(tokens=dict(tokens), player=player or tokens.get("player"))
    return _heuristic(lifted) or ""


@dataclass
class _Person:
    person_id: str
    display_name: str
    unique_name: str
    slug: str
    gender: str | None
    apps: int
    tokens: tuple[str, ...]
    hay: str
    last: str


class SearchIndex:
    def __init__(self, people: list[_Person], teams: list[tuple[str, int]]):
        self.people = people
        self.by_slug = {p.slug: p for p in people if p.slug}
        self.by_id = {p.person_id.lower(): p for p in people}
        self.token_to_idx: dict[str, list[int]] = {}
        for i, p in enumerate(people):
            for tok in set(p.tokens):
                self.token_to_idx.setdefault(tok, []).append(i)
        self.tokens_sorted = sorted(self.token_to_idx)
        self.teams = teams
        self.team_norm = {_norm(name): (name, n) for name, n in teams}

    @classmethod
    def from_rows(
        cls,
        rows: list[dict[str, Any]],
        teams: list[tuple[str, int]] | None = None,
    ) -> "SearchIndex":
        people: list[_Person] = []
        for r in rows:
            display = str(r.get("display_name") or "")
            unique = str(r.get("unique_name") or display)
            slug = str(r.get("slug") or _slug(unique or display))
            variants = str(r.get("name_variants") or "").replace("|", " ")
            hay = _norm(f"{display} {unique} {slug.replace('-', ' ')} {variants}")
            tokens = tuple(t for t in hay.replace("-", " ").split() if t)
            people.append(
                _Person(
                    person_id=str(r.get("person_id") or ""),
                    display_name=display,
                    unique_name=unique,
                    slug=slug,
                    gender=r.get("gender"),
                    apps=int(r.get("apps") or 0),
                    tokens=tokens,
                    hay=hay,
                    last=tokens[-1] if tokens else "",
                )
            )
        return cls(people, teams or [])

    def _prefix_indices(self, prefix: str) -> set[int]:
        keys = self.tokens_sorted
        lo = bisect_left(keys, prefix)
        hi = bisect_right(keys, prefix + "\uffff")
        out: set[int] = set()
        for key in keys[lo:hi]:
            if not key.startswith(prefix):
                break
            out.update(self.token_to_idx[key])
        return out

    def search(self, needle: str, limit: int = 20) -> list[dict]:
        raw = _norm(needle)
        if not raw:
            return []
        slug = _slug(raw)
        tokens = raw.replace("-", " ").split()
        exact = self.by_slug.get(slug) or self.by_id.get(raw)
        if exact and (len(tokens) <= 1 or _name_covers(
            {"display_name": exact.display_name, "unique_name": exact.unique_name, "slug": exact.slug},
            raw,
        )):
            # Still rank nearby names so a slug query can show alternatives.
            pass

        used = list(tokens)
        candidates: set[int] | None = None
        while used:
            acc: set[int] | None = None
            for tok in used:
                hits = self._prefix_indices(tok) if len(tok) > 1 else {
                    i for i, p in enumerate(self.people) if any(t.startswith(tok) for t in p.tokens)
                }
                acc = hits if acc is None else acc & hits
            if acc:
                candidates = acc
                tokens = used
                break
            used = used[:-1]
        if not candidates and exact:
            candidates = {self.people.index(exact)} if exact in self.people else set()
        if not candidates:
            # Last-name / hay substring for a single leftover token.
            last = tokens[-1] if tokens else raw
            candidates = {i for i, p in enumerate(self.people) if last in p.hay}
            if len(candidates) > 80:
                candidates = {i for i in candidates if self.people[i].last.startswith(last) or last in self.people[i].last}

        scored: list[tuple[int, int, _Person]] = []
        for i in candidates:
            p = self.people[i]
            hit = _score_person(p, raw, slug, tokens)
            if hit is None:
                continue
            scored.append((hit, -p.apps, p))
        scored.sort(key=lambda r: (r[0], r[1], r[2].unique_name))
        return [_person_dict(p, hit) for hit, _, p in scored[:limit]]

    def search_teams(self, needle: str, limit: int = 8) -> list[dict]:
        q = _norm(needle)
        if not q:
            return [{"team": name} for name, _ in self.teams[:limit]]
        alias = is_known_team(q)
        scored: list[tuple[int, int, str]] = []
        for name, n in self.teams:
            ln = _norm(name)
            if alias and _norm(alias) == ln:
                scored.append((0, -n, name))
            elif ln == q:
                scored.append((0, -n, name))
            elif ln.startswith(q) or q in ln:
                scored.append((1 if ln.startswith(q) else 2, -n, name))
        if not scored and alias:
            scored.append((0, 0, alias))
        scored.sort()
        seen: set[str] = set()
        out = []
        for _, __, name in scored:
            if name in seen:
                continue
            seen.add(name)
            out.append({"team": name})
            if len(out) >= limit:
                break
        return out


def _score_person(p: _Person, raw: str, slug: str, tokens: list[str]) -> int | None:
    if p.slug == slug or p.person_id.lower() == raw:
        return 0
    if p.hay == raw or _norm(p.display_name) == raw or _norm(p.unique_name) == raw:
        return 1
    if tokens and all(_token_hits(t, list(p.tokens)) for t in tokens):
        if len(tokens) >= 2 or (tokens[-1] == p.last):
            return 2
        return 3
    if raw in p.hay:
        return 4
    if tokens and _token_hits(tokens[-1], list(p.tokens)):
        return 5
    return None


def _person_dict(p: _Person, hit: int) -> dict:
    return {
        "person_id": p.person_id,
        "display_name": p.display_name,
        "unique_name": p.unique_name,
        "slug": p.slug,
        "gender": p.gender,
        "hit": hit,
        "apps": p.apps,
    }


def _stamp() -> tuple[float, float] | None:
    people = WAREHOUSE / "people.parquet"
    if not people.exists():
        return None
    xi = WAREHOUSE / "xi.parquet"
    return (people.stat().st_mtime, xi.stat().st_mtime if xi.exists() else 0.0)


def get_index() -> SearchIndex | None:
    global _INDEX, _INDEX_STAMP
    stamp = _stamp()
    if stamp is None:
        return None
    if _INDEX is not None and _INDEX_STAMP == stamp:
        return _INDEX
    with _lock:
        if _INDEX is not None and _INDEX_STAMP == stamp:
            return _INDEX
        _INDEX = _load_index()
        _INDEX_STAMP = stamp
        return _INDEX


def _load_index() -> SearchIndex | None:
    from cricwarehouse.app.db import connect, warehouse_ready

    if not warehouse_ready():
        return None
    con = connect()
    try:
        recs = con.execute(
            """
            SELECT p.person_id, p.display_name, p.unique_name, p.slug, p.gender,
                   p.name_variants, COALESCE(x.apps, 0) AS apps
            FROM people p
            LEFT JOIN (
              SELECT person_id, COUNT(*) AS apps FROM xi GROUP BY 1
            ) x ON x.person_id = p.person_id
            """
        ).fetchall()
        cols = ["person_id", "display_name", "unique_name", "slug", "gender", "name_variants", "apps"]
        rows = [dict(zip(cols, r)) for r in recs]
        teams = con.execute(
            """
            SELECT team, COUNT(*) AS n FROM (
              SELECT team_home AS team FROM matches
              UNION ALL
              SELECT team_away AS team FROM matches
            )
            WHERE team IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC
            """
        ).fetchall()
        return SearchIndex.from_rows(rows, [(r[0], int(r[1])) for r in teams])
    finally:
        con.close()


def search_people(needle: str, limit: int = 20) -> list[dict]:
    idx = get_index()
    if idx is None:
        return []
    return idx.search(needle, limit=limit)


def search_teams(needle: str, limit: int = 8) -> list[dict]:
    idx = get_index()
    if idx is None:
        alias = is_known_team(needle)
        return [{"team": alias}] if alias else []
    return idx.search_teams(needle, limit=limit)


def reset_index() -> None:
    global _INDEX, _INDEX_STAMP
    _INDEX = None
    _INDEX_STAMP = None
