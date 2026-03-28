"""
Trigram Search Index — fuzzy player name matching without external dependencies.

Builds an in-memory trigram index over all player names (batters + bowlers
combined). Supports exact substring matching, fuzzy matching, and filtered
search by country/role/archetype.

Usage:
    from search_index import TrigramIndex, build_search_index
    from data_loader import DataStore

    index = build_search_index(store)
    results = index.search("Bumra", limit=8)
    results = index.search("koh", role="bat", country="India", limit=10)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from data_loader import DataStore


@dataclass
class PlayerEntry:
    """Lightweight player record stored in the search index."""

    id: str  # Raw player ID (batter_id or bowler_id)
    name: str
    country: str
    role: str  # "bat", "bowl", or "all-rounder"
    archetype: str
    grade_overall: str
    innings_count: int
    total_runs: int  # or total_wickets for bowlers
    career_sr: float  # or career_economy for bowlers
    career_avg: float
    score_1: float  # acceleration (bat) or accuracy (bowl)
    score_2: float  # power (bat) or control (bowl)
    score_3: float  # control (bat) or threat (bowl)
    score_1_label: str = "acceleration"
    score_2_label: str = "power"
    score_3_label: str = "control"
    is_provisional: bool = True
    overall_score: float = 0.0
    rating_current: float | None = None
    rating_overall: float | None = None
    modal_position: int | None = None  # batters only
    recent_team: str | None = None  # latest-match side (batting_team / bowling_team)

    @property
    def index_key(self) -> str:
        """Role-prefixed key used internally by TrigramIndex to avoid
        collisions when the same raw ID exists as both batter and bowler."""
        return f"{self.role}:{self.id}"

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict."""
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
            "role": self.role,
            "archetype": self.archetype,
            "grade_overall": self.grade_overall,
            "innings_count": self.innings_count,
            "total_runs": self.total_runs,
            "career_sr": _safe_float(self.career_sr),
            "career_avg": _safe_float(self.career_avg),
            "score_1": _safe_float(self.score_1),
            "score_2": _safe_float(self.score_2),
            "score_3": _safe_float(self.score_3),
            "score_1_label": self.score_1_label,
            "score_2_label": self.score_2_label,
            "score_3_label": self.score_3_label,
            "is_provisional": self.is_provisional,
            "overall_score": _safe_float(self.overall_score),
            "rating_current": _safe_float(self.rating_current),
            "rating_overall": _safe_float(self.rating_overall),
            "modal_position": self.modal_position,
            "recent_team": self.recent_team,
        }


def _safe_float(v: object) -> float | None:
    """Convert to float, returning None for NaN/inf."""
    try:
        import math

        f = float(v)  # type: ignore[arg-type]
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _nan_to_zero(v: object) -> float:
    """Convert a value to float, returning 0.0 for NaN/inf/None."""
    if v is None:
        return 0.0
    try:
        import math

        f = float(v)  # type: ignore[arg-type]
        if math.isnan(f) or math.isinf(f):
            return 0.0
        return f
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: object) -> int:
    """Convert to int, returning 0 for NaN/None."""
    try:
        import math

        f = float(v)  # type: ignore[arg-type]
        if math.isnan(f) or math.isinf(f):
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def _safe_str(v: object, default: str = "") -> str:
    """Convert to string, returning default for NaN/None."""
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>"):
        return default
    return s


class TrigramIndex:
    """In-memory trigram index for fuzzy player name search.

    For each player, all 3-character substrings of their lowercased name
    (with padding) are indexed. At query time, the trigram sets for the
    query string are intersected with the index, and results are ranked
    by overlap count.

    Internally, players are keyed by ``role:id`` (e.g. ``bat:abc123``,
    ``bowl:abc123``) so that the same raw player ID can exist as both a
    batter and a bowler without collision.

    Additional filters (country, role, archetype, provisional) are applied
    post-ranking.
    """

    def __init__(self) -> None:
        # trigram -> set of index keys (role:id)
        self._index: dict[str, set[str]] = defaultdict(set)
        # index_key (role:id) -> PlayerEntry
        self._players: dict[str, PlayerEntry] = {}
        # lowercased name -> list of index keys (may have bat + bowl)
        self._name_lower: dict[str, list[str]] = defaultdict(list)
        # country -> set of index keys
        self._by_country: dict[str, set[str]] = defaultdict(set)
        # role -> set of index keys
        self._by_role: dict[str, set[str]] = defaultdict(set)
        # archetype (lowered) -> set of index keys
        self._by_archetype: dict[str, set[str]] = defaultdict(set)
        # provisional status -> set of index keys
        self._provisional: set[str] = set()
        self._non_provisional: set[str] = set()

    # ── Index building ────────────────────────────────────────

    def add(self, player: PlayerEntry) -> None:
        """Add a player to the index."""
        ikey = player.index_key  # e.g. "bat:abc123"
        self._players[ikey] = player

        name_lower = player.name.lower().strip()
        self._name_lower[name_lower].append(ikey)

        for tri in self._trigrams(name_lower):
            self._index[tri].add(ikey)

        # Also index country as trigrams (so searching "india" finds Indian players)
        if player.country:
            country_lower = player.country.lower().strip()
            self._by_country[country_lower].add(ikey)
            for tri in self._trigrams(country_lower):
                self._index[tri].add(ikey)

        self._by_role[player.role].add(ikey)
        if player.archetype:
            self._by_archetype[player.archetype.lower().strip()].add(ikey)

        if player.is_provisional:
            self._provisional.add(ikey)
        else:
            self._non_provisional.add(ikey)

    def _trigrams(self, text: str) -> list[str]:
        """Generate all 3-character substrings from padded text."""
        if len(text) < 1:
            return []
        padded = f"  {text}  "
        return [padded[i : i + 3] for i in range(len(padded) - 2)]

    # ── Search ────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        role: str | None = None,
        country: str | None = None,
        archetype: str | None = None,
        provisional: bool | None = None,
        min_innings: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search for players matching the query string.

        Parameters
        ----------
        query : str
            Search string (player name or substring).
        role : str, optional
            Filter by role: "bat", "bowl", or "all-rounder".
        country : str, optional
            Filter by country name (case-insensitive).
        archetype : str, optional
            Filter by archetype (case-insensitive).
        provisional : bool, optional
            If True, include only provisional. If False, exclude provisional.
            If None, include all.
        min_innings : int, optional
            Minimum innings/matches filter.
        limit : int
            Max results to return.

        Returns
        -------
        list[dict]
            Ranked list of player dicts, best match first.
        """
        if not query or not query.strip():
            # No query — return top players by overall score, respecting filters
            return self._browse(
                role=role,
                country=country,
                archetype=archetype,
                provisional=provisional,
                min_innings=min_innings,
                limit=limit,
            )

        query_lower = query.lower().strip()
        query_trigrams = self._trigrams(query_lower)

        # Count trigram overlap per index key
        scores: Counter[str] = Counter()
        for tri in query_trigrams:
            for ikey in self._index.get(tri, set()):
                scores[ikey] += 1

        if not scores:
            return []

        # Apply filters
        candidates = set(scores.keys())
        candidates = self._apply_filters(
            candidates,
            role=role,
            country=country,
            archetype=archetype,
            provisional=provisional,
            min_innings=min_innings,
        )

        if not candidates:
            return []

        # Build ranking tuples: (trigram_overlap, exact_match_bonus, overall_score)
        ranked: list[tuple[float, str]] = []
        for ikey in candidates:
            player = self._players[ikey]
            trigram_score = scores[ikey]

            # Exact match bonus: if the query is a substring of the name
            name_lower = player.name.lower()
            exact_bonus = 0.0
            if query_lower in name_lower:
                # Full exact match
                if query_lower == name_lower:
                    exact_bonus = 1000.0
                # Starts with query
                elif name_lower.startswith(query_lower):
                    exact_bonus = 500.0
                # Contains query as substring
                else:
                    exact_bonus = 200.0

            # Tie-break by overall score (better players rank higher)
            overall = player.overall_score if player.overall_score else 0.0

            # Non-provisional boost
            prov_penalty = 0.0 if player.is_provisional else 50.0

            composite = trigram_score + exact_bonus + prov_penalty + overall / 100.0
            ranked.append((composite, ikey))

        # Sort descending by composite score
        ranked.sort(key=lambda x: -x[0])

        # Deduplicate by raw player ID — when no role filter is specified
        # and the same person appears as both bat and bowl, return only the
        # higher-scoring entry (usually batting, since those are indexed first
        # and tend to have higher composite rank).
        if role is None:
            seen_raw_ids: set[str] = set()
            deduped: list[tuple[float, str]] = []
            for score, ikey in ranked:
                player = self._players[ikey]
                if player.id in seen_raw_ids:
                    continue
                seen_raw_ids.add(player.id)
                deduped.append((score, ikey))
            ranked = deduped

        return [self._players[ikey].to_dict() for _, ikey in ranked[:limit]]

    def _browse(
        self,
        *,
        role: str | None = None,
        country: str | None = None,
        archetype: str | None = None,
        provisional: bool | None = None,
        min_innings: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Browse players without a search query — sorted by overall score."""
        candidates = set(self._players.keys())
        candidates = self._apply_filters(
            candidates,
            role=role,
            country=country,
            archetype=archetype,
            provisional=provisional,
            min_innings=min_innings,
        )

        # Sort by overall score descending
        sorted_keys = sorted(
            candidates,
            key=lambda ikey: -(self._players[ikey].overall_score or 0.0),
        )

        # Deduplicate by raw player ID when no role filter
        if role is None:
            seen_raw_ids: set[str] = set()
            deduped: list[str] = []
            for ikey in sorted_keys:
                player = self._players[ikey]
                if player.id in seen_raw_ids:
                    continue
                seen_raw_ids.add(player.id)
                deduped.append(ikey)
            sorted_keys = deduped

        return [self._players[ikey].to_dict() for ikey in sorted_keys[:limit]]

    def _apply_filters(
        self,
        candidates: set[str],
        *,
        role: str | None = None,
        country: str | None = None,
        archetype: str | None = None,
        provisional: bool | None = None,
        min_innings: int | None = None,
    ) -> set[str]:
        """Apply all post-query filters to a candidate set."""
        if role:
            role_lower = role.lower().strip()
            role_set = self._by_role.get(role_lower, set())
            if role_lower == "all-rounder":
                # All-rounders: find raw IDs that appear in BOTH bat and bowl sets
                bat_keys = self._by_role.get("bat", set())
                bowl_keys = self._by_role.get("bowl", set())
                # Extract raw IDs from each set and find the intersection
                bat_raw = {self._players[k].id for k in bat_keys if k in self._players}
                bowl_raw = {
                    self._players[k].id for k in bowl_keys if k in self._players
                }
                ar_raw = bat_raw & bowl_raw
                # Return all index keys whose raw ID is in the all-rounder set
                role_set = {
                    k
                    for k in (bat_keys | bowl_keys)
                    if k in self._players and self._players[k].id in ar_raw
                }
            candidates = candidates & role_set

        if country:
            country_lower = country.lower().strip()
            country_set = self._by_country.get(country_lower, set())
            if not country_set:
                # Try partial match on country names
                for c, ikeys in self._by_country.items():
                    if country_lower in c or c in country_lower:
                        country_set |= ikeys
            candidates = candidates & country_set

        if archetype:
            archetype_lower = archetype.lower().strip()
            arch_set = self._by_archetype.get(archetype_lower, set())
            if not arch_set:
                # Partial match
                for a, ikeys in self._by_archetype.items():
                    if archetype_lower in a or a in archetype_lower:
                        arch_set |= ikeys
            candidates = candidates & arch_set

        if provisional is True:
            candidates = candidates & self._provisional
        elif provisional is False:
            candidates = candidates & self._non_provisional

        if min_innings is not None and min_innings > 0:
            candidates = {
                ikey
                for ikey in candidates
                if self._players[ikey].innings_count >= min_innings
            }

        return candidates

    # ── Accessors ─────────────────────────────────────────────

    def get(self, player_id: str, role: str | None = None) -> PlayerEntry | None:
        """Get a player entry by raw ID, optionally scoped to a role.

        If *role* is provided, looks up ``role:player_id`` directly.
        Otherwise tries ``bat:player_id`` first, then ``bowl:player_id``.
        """
        if role:
            return self._players.get(f"{role}:{player_id}")
        return self._players.get(f"bat:{player_id}") or self._players.get(
            f"bowl:{player_id}"
        )

    def get_dict(self, player_id: str, role: str | None = None) -> dict | None:
        """Get a player entry as a dict by raw ID."""
        entry = self.get(player_id, role=role)
        return entry.to_dict() if entry else None

    @property
    def size(self) -> int:
        """Number of unique raw player IDs in the index."""
        return len({p.id for p in self._players.values()})

    @property
    def total_entries(self) -> int:
        """Total entries (including dual-role duplicates)."""
        return len(self._players)

    def all_countries(self) -> list[str]:
        """Sorted list of all countries in the index."""
        # Return properly cased country names (from the player entries)
        countries: set[str] = set()
        for player in self._players.values():
            if player.country:
                countries.add(player.country)
        return sorted(countries)

    def all_archetypes(self) -> dict[str, list[str]]:
        """Sorted lists of archetypes by role."""
        bat_archetypes: set[str] = set()
        bowl_archetypes: set[str] = set()
        for player in self._players.values():
            if player.archetype:
                if player.role == "bat":
                    bat_archetypes.add(player.archetype)
                elif player.role == "bowl":
                    bowl_archetypes.add(player.archetype)
        return {
            "bat": sorted(bat_archetypes),
            "bowl": sorted(bowl_archetypes),
        }


# ── Builder ───────────────────────────────────────────────────────


def _extract_batting_entries(bat_careers: "pd.DataFrame") -> list[PlayerEntry]:
    """Extract PlayerEntry objects from batting careers DataFrame."""
    from rating_display import batting_display_ratings

    entries: list[PlayerEntry] = []
    if bat_careers.empty:
        return entries

    for _, row in bat_careers.iterrows():
        pid = _safe_str(row.get("batter_id"), "")
        if not pid:
            continue

        ro, rc = batting_display_ratings(row)
        mp = _safe_int(row.get("modal_position", 0))
        modal = mp if 1 <= mp <= 11 else None
        rteam = _safe_str(row.get("recent_team"), "").strip() or None

        entries.append(
            PlayerEntry(
                id=pid,
                name=_safe_str(row.get("batter"), "Unknown"),
                country=_safe_str(row.get("country"), "Unknown"),
                role="bat",
                archetype=_safe_str(row.get("archetype"), "Unknown"),
                grade_overall=_safe_str(row.get("overall_grade"), "D"),
                innings_count=_safe_int(row.get("innings_count", 0)),
                total_runs=_safe_int(row.get("total_runs", 0)),
                career_sr=_nan_to_zero(row.get("career_sr", 0)),
                career_avg=_nan_to_zero(row.get("career_avg", 0)),
                score_1=_nan_to_zero(row.get("score_acceleration", 0)),
                score_2=_nan_to_zero(row.get("score_power", 0)),
                score_3=_nan_to_zero(row.get("score_control", 0)),
                score_1_label="acceleration",
                score_2_label="power",
                score_3_label="control",
                is_provisional=bool(row.get("is_provisional_bat", True)),
                overall_score=_nan_to_zero(row.get("overall_score", 0)),
                rating_current=_safe_float(rc),
                rating_overall=_safe_float(ro),
                modal_position=modal,
                recent_team=rteam,
            )
        )
    return entries


def _extract_bowling_entries(bowl_careers: "pd.DataFrame") -> list[PlayerEntry]:
    """Extract PlayerEntry objects from bowling careers DataFrame."""
    from rating_display import bowling_display_ratings

    entries: list[PlayerEntry] = []
    if bowl_careers.empty:
        return entries

    for _, row in bowl_careers.iterrows():
        pid = _safe_str(row.get("bowler_id"), "")
        if not pid:
            continue

        ro, rc = bowling_display_ratings(row)
        rteam = _safe_str(row.get("recent_team"), "").strip() or None

        entries.append(
            PlayerEntry(
                id=pid,
                name=_safe_str(row.get("bowler"), "Unknown"),
                country=_safe_str(row.get("country"), "Unknown"),
                role="bowl",
                archetype=_safe_str(row.get("archetype"), "Unknown"),
                grade_overall=_safe_str(row.get("overall_grade"), "D"),
                innings_count=_safe_int(row.get("matches", 0)),
                total_runs=_safe_int(row.get("total_wickets", 0)),
                career_sr=_nan_to_zero(row.get("career_economy", 0)),
                career_avg=_nan_to_zero(row.get("career_sr_bowl", 0)),
                score_1=_nan_to_zero(row.get("score_accuracy", 0)),
                score_2=_nan_to_zero(row.get("score_control", 0)),
                score_3=_nan_to_zero(row.get("score_threat", 0)),
                score_1_label="accuracy",
                score_2_label="control",
                score_3_label="threat",
                is_provisional=bool(row.get("is_provisional_bowl", True)),
                overall_score=_nan_to_zero(row.get("overall_score", 0)),
                rating_current=_safe_float(rc),
                rating_overall=_safe_float(ro),
                modal_position=None,
                recent_team=rteam,
            )
        )
    return entries


def build_search_index(store: "DataStore") -> TrigramIndex:
    """Build the trigram search index from the DataStore.

    Indexes all batters and all bowlers.  Each entry is stored under a
    role-prefixed key (``bat:<id>`` / ``bowl:<id>``) so the same raw
    player ID can appear as both batter and bowler without collision.

    When searching *without* a role filter, results are deduplicated by
    raw ID so a dual-role player appears only once (the entry with the
    higher composite relevance score wins — typically the batting entry
    because batters are indexed first and earn trigram hits on the same
    name).

    When searching *with* a role filter (``role=bat`` or ``role=bowl``),
    each role's entries are returned independently.

    Parameters
    ----------
    store : DataStore
        Populated data store from ``load_data()``.

    Returns
    -------
    TrigramIndex
        Ready-to-query search index.
    """
    index = TrigramIndex()

    # Add all batters
    bat_entries = _extract_batting_entries(store.bat_careers)
    for entry in bat_entries:
        index.add(entry)

    # Add all bowlers (role-prefixed key avoids overwriting batter entries)
    bowl_entries = _extract_bowling_entries(store.bowl_careers)
    for entry in bowl_entries:
        index.add(entry)

    # Count dual-role players for logging
    bat_ids = {e.id for e in bat_entries}
    bowl_ids = {e.id for e in bowl_entries}
    dual_count = len(bat_ids & bowl_ids)

    print(
        f"Search index built: {index.size} unique players "
        f"({index.total_entries} entries incl. {dual_count} dual-role)."
    )
    return index
