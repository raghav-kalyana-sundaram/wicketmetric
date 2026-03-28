/**
 * TanStack Query hooks for the Cricket Metrics API.
 *
 * Each hook wraps an API client method with proper caching, stale times,
 * and key management. The hooks handle loading/error states and provide
 * typed data to components.
 *
 * **Format-aware:** Every query key is prefixed with the active format
 * (e.g. "mens_t20i", "womens_t20i", "womens_ipl") so that switching datasets in the UI triggers
 * fresh fetches instead of serving stale cached data from the other dataset.
 *
 * Usage:
 *   import { usePlayerProfile, useSearchPlayers } from '@/api/queries';
 *
 *   const { data, isLoading, error } = usePlayerProfile(playerId);
 *   const { data: results } = useSearchPlayers({ q: 'kohli' });
 */

import {
  useQuery,
  useQueries,
  // useInfiniteQuery,
  keepPreviousData,
  // type UseQueryOptions,
  // type QueryKey,
} from "@tanstack/react-query";

import { api } from "@/api/client";
import { useFormat } from "@/api/FormatContext";
import type {
  PlayerSummary,
  PlayerRoles,
  SearchResponse,
  LeaderboardResponse,
  BatterProfile,
  BowlerProfile,
  PlayerProfile,
  CompareResponse,
  HeadToHeadResponse,
  MatchupExploreResponse,
  MatchupSummary,
  FormBatchResponse,
  FormResponse,
  SimilarityResponse,
  VenueListResponse,
  // VenueBaseline,
  VenueDetail,
  VenueSummary,
  InningsLogResponse,
  PlayerMatchImpactRow,
  SpellsLogResponse,
  EraResponse,
  TeamAnalysis,
  ApiMeta,
  SearchParams,
  LeaderboardParams,
  MatchImpactPerformancesParams,
  MatchImpactPerformancesResponse,
  MatchupExploreParams,
  VenueListParams,
  SharedMatchupsResponse,
  EspnCricketMatchSummaryResponse,
  EspnCricketScoreboardResponse,
} from "@/api/types";

// ── Cache time constants ─────────────────────────────────────────

/** Data is static (pipeline outputs), so stale times can be generous. */
const STALE_TIMES = {
  /** Meta / health — recheck every 5 minutes */
  meta: 5 * 60 * 1000,
  /** Search results — 10 minutes */
  search: 10 * 60 * 1000,
  /** Player profiles — 30 minutes (data doesn't change between pipeline runs) */
  profile: 30 * 60 * 1000,
  /** Leaderboards — 15 minutes */
  leaderboard: 15 * 60 * 1000,
  /** Form time-series — 30 minutes */
  form: 30 * 60 * 1000,
  /** Matchups — 30 minutes */
  matchups: 30 * 60 * 1000,
  /** Similarities — 30 minutes */
  similarity: 30 * 60 * 1000,
  /** Venues — 30 minutes */
  venues: 30 * 60 * 1000,
  /** Reference data (countries, archetypes, sort columns) — 1 hour */
  reference: 60 * 60 * 1000,
  /** Compare — 15 minutes */
  compare: 15 * 60 * 1000,
  /** ESPN scoreboard — align with backend default cache TTL (~90s) */
  liveEspn: 90 * 1000,
} as const;

// ── Query key factories ──────────────────────────────────────────
// Structured keys enable targeted invalidation and deduplication.

export const queryKeys = {
  // Meta
  health: ["health"] as const,
  meta: ["meta"] as const,

  // Search
  search: (params: Partial<SearchParams>) => ["search", params] as const,
  autocomplete: (q: string, role?: string | null, country?: string | null) =>
    ["autocomplete", { q, role, country }] as const,
  countries: ["countries"] as const,
  archetypes: ["archetypes"] as const,

  // Player
  player: (id: string) => ["player", id] as const,
  playerRoles: (id: string) => ["player", "roles", id] as const,
  playerBatter: (id: string) => ["player", "batter", id] as const,
  playerBowler: (id: string) => ["player", "bowler", id] as const,
  playerInnings: (
    id: string,
    page?: number,
    perPage?: number,
    sortBy?: string,
    order?: string,
  ) => ["player", id, "innings", { page, perPage, sortBy, order }] as const,
  playerSpells: (
    id: string,
    page?: number,
    perPage?: number,
    sortBy?: string,
    order?: string,
  ) => ["player", id, "spells", { page, perPage, sortBy, order }] as const,
  playerMatchImpact: (id: string) =>
    ["player", id, "scorecards", "match-impact"] as const,
  playerForm: (id: string, role?: string) =>
    ["player", id, "form", role] as const,
  playerMatchups: (
    id: string,
    role?: string,
    minBalls?: number,
    sort?: string,
    order?: string,
    page?: number,
    perPage?: number,
  ) =>
    [
      "player",
      id,
      "matchups",
      { role, minBalls, sort, order, page, perPage },
    ] as const,
  playerSimilar: (id: string, role?: string, limit?: number) =>
    ["player", id, "similar", { role, limit }] as const,

  matchImpactPerformances: (p: MatchImpactPerformancesParams) =>
    ["scorecards", "performances", "by-impact", p] as const,

  // Rankings
  battingRankings: (params: Partial<LeaderboardParams>) =>
    ["rankings", "bat", params] as const,
  bowlingRankings: (params: Partial<LeaderboardParams>) =>
    ["rankings", "bowl", params] as const,
  battingSortColumns: ["rankings", "bat", "sortColumns"] as const,
  bowlingSortColumns: ["rankings", "bowl", "sortColumns"] as const,
  topPlayers: (
    role?: string,
    metric?: string,
    limit?: number,
    provisional?: boolean | null,
    minInnings?: number,
    activity?: "active" | "retired" | "all",
  ) =>
    [
      "topPlayers",
      { role, metric, limit, provisional, minInnings, activity },
    ] as const,

  // Compare
  compare: (ids: string[]) => ["compare", ...ids.sort()] as const,
  compareForm: (ids: string[]) => ["compare", "form", ...ids.sort()] as const,
  sharedMatchups: (ids: string[], minBalls?: number, limit?: number) =>
    [
      "compare",
      "sharedMatchups",
      { ids: [...ids].sort(), minBalls, limit },
    ] as const,

  // Matchups
  headToHead: (bat: string, bowl: string) =>
    ["matchups", "h2h", bat, bowl] as const,
  exploreMatchups: (params: Partial<MatchupExploreParams>) =>
    ["matchups", "explore", params] as const,
  topBunnies: (bowlerId: string, minBalls?: number, limit?: number) =>
    ["matchups", "bunnies", bowlerId, { minBalls, limit }] as const,
  topNemeses: (batterId: string, minBalls?: number, limit?: number) =>
    ["matchups", "nemeses", batterId, { minBalls, limit }] as const,
  topDominant: (batterId: string, minBalls?: number, limit?: number) =>
    ["matchups", "dominant", batterId, { minBalls, limit }] as const,

  /** ESPN cricket scoreboard (not format-scoped) */
  espnCricketScoreboard: (
    league: string,
    dates?: string | null,
    region?: string | null,
    lang?: string | null,
  ) =>
    [
      "espnCricketScoreboard",
      league,
      dates ?? null,
      region ?? null,
      lang ?? null,
    ] as const,

  espnCricketMatchSummary: (leagueId: string, eventId: string) =>
    ["espnCricketMatchSummary", leagueId, eventId] as const,

  // Venues
  venues: (params?: Partial<VenueListParams>) => ["venues", params] as const,
  venueDetail: (name: string) => ["venues", "detail", name] as const,
  venueProfile: (name: string, exact?: boolean) =>
    ["venues", "profile", name, exact] as const,
  venueTrends: (name: string, bucket?: string, exact?: boolean) =>
    ["venues", "trends", name, bucket, exact] as const,
  venueTeams: (name: string, p?: Record<string, unknown>) =>
    ["venues", "teams", name, p] as const,
  venueSimilar: (name: string, k?: number, exact?: boolean) =>
    ["venues", "similar", name, k, exact] as const,
  venueMatches: (name: string, page?: number, exact?: boolean) =>
    ["venues", "matches", name, page, exact] as const,
  venuePerformances: (name: string, p?: Record<string, unknown>) =>
    ["venues", "performances", name, p] as const,
  playersAtVenue: (
    venueName: string,
    role?: string,
    minInnings?: number,
    sort?: string,
    order?: string,
    page?: number,
    perPage?: number,
    exact?: boolean,
  ) =>
    [
      "venues",
      "players",
      venueName,
      { role, minInnings, sort, order, page, perPage, exact },
    ] as const,
  venueSummary: ["venues", "summary"] as const,

  // Eras
  eras: ["eras"] as const,

  // Team Builder
  teamAnalyse: (
    ids: string[],
    slotTypes?: string[],
    bowlingPhases?: string[],
  ) =>
    [
      "team",
      "analyse",
      ids.join("~"),
      ...(slotTypes ?? []),
      "|",
      ...(bowlingPhases ?? []),
    ] as const,
  teamAutoFill: (strategy?: string, country?: string | null) =>
    ["team", "autoFill", { strategy, country }] as const,
  teamCompare: (teamAIds: string[], teamBIds: string[]) =>
    ["team", "compare", ...teamAIds.sort(), "|", ...teamBIds.sort()] as const,
} as const;

// ── Meta & Health hooks ──────────────────────────────────────────

/** Check backend health. */
export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => api.health(),
    staleTime: STALE_TIMES.meta,
    retry: 2,
  });
}

/** Fetch API metadata (player counts, countries, archetypes). */
export function useMeta(options?: { enabled?: boolean }) {
  const { format } = useFormat();
  return useQuery<ApiMeta>({
    queryKey: [format, ...queryKeys.meta],
    queryFn: () => api.meta(),
    staleTime: STALE_TIMES.meta,
    enabled: options?.enabled,
  });
}

// ── Search hooks ─────────────────────────────────────────────────

/** Full search with all filters. */
export function useSearchPlayers(
  params: Partial<SearchParams>,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<SearchResponse>({
    queryKey: [format, ...queryKeys.search(params)],
    queryFn: () =>
      api.search({
        q: params.q ?? "",
        role: params.role,
        country: params.country,
        archetype: params.archetype,
        provisional: params.provisional,
        min_innings: params.min_innings,
        limit: params.limit,
      }),
    staleTime: STALE_TIMES.search,
    placeholderData: keepPreviousData,
    enabled: options?.enabled ?? true,
  });
}

/**
 * Autocomplete search — designed for search-as-you-type inputs.
 * Only enabled when the query is at least 2 characters.
 */
export function useAutocomplete(
  q: string,
  options?: {
    role?: string | null;
    country?: string | null;
    limit?: number;
    enabled?: boolean;
  },
) {
  const { format } = useFormat();
  const enabled = (options?.enabled ?? true) && q.length >= 2;

  return useQuery<PlayerSummary[]>({
    queryKey: [
      format,
      ...queryKeys.autocomplete(q, options?.role, options?.country),
    ],
    queryFn: ({ signal }) =>
      api.autocomplete(q, {
        role: options?.role,
        country: options?.country,
        limit: options?.limit ?? 8,
        signal,
      }),
    staleTime: STALE_TIMES.search,
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** Fetch all countries in the dataset. */
export function useCountries() {
  const { format } = useFormat();
  return useQuery<string[]>({
    queryKey: [format, ...queryKeys.countries],
    queryFn: () => api.getCountries(),
    staleTime: STALE_TIMES.reference,
  });
}

/** Fetch all archetypes keyed by role. */
export function useArchetypes() {
  const { format } = useFormat();
  return useQuery<Record<string, string[]>>({
    queryKey: [format, ...queryKeys.archetypes],
    queryFn: () => api.getArchetypes(),
    staleTime: STALE_TIMES.reference,
  });
}

// ── Player Profile hooks ─────────────────────────────────────────

/**
 * Fetch which roles (bat/bowl) a player has, with innings counts.
 * Used to determine the default view and whether to show a bat/bowl toggle.
 */
export function usePlayerRoles(
  id: string | undefined,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<PlayerRoles>({
    queryKey: [format, ...queryKeys.playerRoles(id ?? "")],
    queryFn: () => api.getPlayerRoles(id!),
    staleTime: STALE_TIMES.profile,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

/**
 * Fetch a player profile (auto-detects batter vs bowler).
 * The API returns either a BatterProfile or BowlerProfile.
 */
export function usePlayerProfile(
  id: string | undefined,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<PlayerProfile>({
    queryKey: [format, ...queryKeys.player(id ?? "")],
    queryFn: () => api.getPlayer(id!),
    staleTime: STALE_TIMES.profile,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

/** Explicitly fetch a batter profile. */
export function useBatterProfile(
  id: string | undefined,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<BatterProfile>({
    queryKey: [format, ...queryKeys.playerBatter(id ?? "")],
    queryFn: () => api.getBatterProfile(id!),
    staleTime: STALE_TIMES.profile,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

/** Explicitly fetch a bowler profile. */
export function useBowlerProfile(
  id: string | undefined,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<BowlerProfile>({
    queryKey: [format, ...queryKeys.playerBowler(id ?? "")],
    queryFn: () => api.getBowlerProfile(id!),
    staleTime: STALE_TIMES.profile,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

// ── Player Innings / Spells hooks ────────────────────────────────

/** Fetch paginated batting innings for a player. */
export function usePlayerInnings(
  id: string | undefined,
  params?: {
    page?: number;
    perPage?: number;
    sortBy?: string;
    order?: string;
  },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const page = params?.page ?? 1;
  const perPage = params?.perPage ?? 25;
  const sortBy = params?.sortBy ?? "date";
  const order = params?.order ?? "desc";

  return useQuery<InningsLogResponse>({
    queryKey: [
      format,
      ...queryKeys.playerInnings(id ?? "", page, perPage, sortBy, order),
    ],
    queryFn: ({ signal }) =>
      api.getPlayerInnings(id!, {
        page,
        per_page: perPage,
        sort_by: sortBy,
        order,
        signal,
      }),
    staleTime: STALE_TIMES.profile,
    placeholderData: keepPreviousData,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

/** Fetch paginated bowling spells for a player. */
export function usePlayerSpells(
  id: string | undefined,
  params?: {
    page?: number;
    perPage?: number;
    sortBy?: string;
    order?: string;
  },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const page = params?.page ?? 1;
  const perPage = params?.perPage ?? 25;
  const sortBy = params?.sortBy ?? "date";
  const order = params?.order ?? "desc";

  return useQuery<SpellsLogResponse>({
    queryKey: [
      format,
      ...queryKeys.playerSpells(id ?? "", page, perPage, sortBy, order),
    ],
    queryFn: ({ signal }) =>
      api.getPlayerSpells(id!, {
        page,
        per_page: perPage,
        sort_by: sortBy,
        order,
        signal,
      }),
    staleTime: STALE_TIMES.profile,
    placeholderData: keepPreviousData,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

/** All scorecard matches with qualifying combined match impact (best first, full list). */
export function usePlayerMatchImpact(
  id: string | undefined,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<PlayerMatchImpactRow[]>({
    queryKey: [format, ...queryKeys.playerMatchImpact(id ?? "")],
    queryFn: ({ signal }) => api.getPlayerMatchImpact(id!, signal),
    staleTime: STALE_TIMES.profile,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

/** Paginated match-impact performances across scorecards (filterable). */
export function useMatchImpactPerformances(
  params: MatchImpactPerformancesParams,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const stable: MatchImpactPerformancesParams = {
    date_from: params.date_from ?? undefined,
    date_to: params.date_to ?? undefined,
    team: params.team ?? undefined,
    event: params.event ?? undefined,
    player_id: params.player_id ?? undefined,
    match_tier: params.match_tier ?? "all",
    discipline: params.discipline ?? "combined",
    order: params.order ?? "desc",
    page: params.page ?? 1,
    per_page: params.per_page ?? 25,
  };
  return useQuery<MatchImpactPerformancesResponse>({
    queryKey: [format, ...queryKeys.matchImpactPerformances(stable)],
    queryFn: ({ signal }) => api.getMatchImpactPerformances(stable, signal),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
    enabled: options?.enabled ?? true,
  });
}

// ── Form Time-Series hooks ───────────────────────────────────────

/** Fetch form time-series data for a player. */
export function usePlayerForm(
  id: string | undefined,
  role?: string,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<FormResponse>({
    queryKey: [format, ...queryKeys.playerForm(id ?? "", role)],
    queryFn: ({ signal }) => api.getPlayerForm(id!, role, signal),
    staleTime: STALE_TIMES.form,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

/** Fetch form summary (last 2 years, active) for multiple players. For leaderboard form tracker. */
export function useFormBatch(
  playerIds: string[],
  role: "bat" | "bowl",
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const sortedIds = [...playerIds].sort();
  return useQuery<FormBatchResponse>({
    queryKey: [format, "form-batch", role, sortedIds.join(",")],
    queryFn: ({ signal }) => api.getFormBatch(playerIds, role, signal),
    staleTime: STALE_TIMES.form,
    enabled: (options?.enabled ?? true) && playerIds.length > 0,
  });
}

// ── Player Matchups hooks ────────────────────────────────────────

/** Fetch matchups for a player (paginated). */
export function usePlayerMatchups(
  id: string | undefined,
  params?: {
    role?: string;
    minBalls?: number;
    sort?: string;
    order?: string;
    page?: number;
    perPage?: number;
  },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<MatchupExploreResponse>({
    queryKey: [
      format,
      ...queryKeys.playerMatchups(
        id ?? "",
        params?.role,
        params?.minBalls,
        params?.sort,
        params?.order,
        params?.page,
        params?.perPage,
      ),
    ],
    queryFn: () =>
      api.getPlayerMatchups(id!, {
        role: (params?.role ?? "bat") as "bat" | "bowl",
        min_balls: params?.minBalls ?? 6,
        sort: params?.sort ?? "dominance_index",
        order: (params?.order ?? "desc") as "asc" | "desc",
        page: params?.page ?? 1,
        per_page: params?.perPage ?? 25,
      }),
    staleTime: STALE_TIMES.matchups,
    placeholderData: keepPreviousData,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

// ── Player Similar hooks ─────────────────────────────────────────

/** Fetch similar players for a given player. */
export function usePlayerSimilar(
  id: string | undefined,
  params?: { role?: string; limit?: number },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<SimilarityResponse>({
    queryKey: [
      format,
      ...queryKeys.playerSimilar(id ?? "", params?.role, params?.limit),
    ],
    queryFn: ({ signal }) =>
      api.getPlayerSimilar(id!, {
        limit: params?.limit ?? 10,
        signal,
      }),
    staleTime: STALE_TIMES.similarity,
    enabled: (options?.enabled ?? true) && !!id,
  });
}

// ── Rankings / Leaderboard hooks ─────────────────────────────────

/** Fetch batting leaderboard with filters and pagination. */
export function useBattingRankings(params: Partial<LeaderboardParams>) {
  const { format } = useFormat();
  return useQuery<LeaderboardResponse>({
    queryKey: [format, ...queryKeys.battingRankings(params)],
    queryFn: () =>
      api.getBattingRankings({
        sort: params.sort ?? "rating_current",
        order: params.order ?? "desc",
        country: params.country,
        archetype: params.archetype,
        position_group: params.position_group,
        modal_slot: params.modal_slot,
        min_innings: params.min_innings,
        provisional: params.provisional,
        activity: params.activity ?? "active",
        page: params.page ?? 1,
        per_page: params.per_page ?? 25,
      }),
    staleTime: STALE_TIMES.leaderboard,
    placeholderData: keepPreviousData,
  });
}

/** Fetch bowling leaderboard with filters and pagination. */
export function useBowlingRankings(params: Partial<LeaderboardParams>) {
  const { format } = useFormat();
  return useQuery<LeaderboardResponse>({
    queryKey: [format, ...queryKeys.bowlingRankings(params)],
    queryFn: () =>
      api.getBowlingRankings({
        sort: params.sort ?? "rating_current",
        order: params.order ?? "desc",
        country: params.country,
        archetype: params.archetype,
        phase_group: params.phase_group,
        min_innings: params.min_innings,
        provisional: params.provisional,
        activity: params.activity ?? "active",
        page: params.page ?? 1,
        per_page: params.per_page ?? 25,
      }),
    staleTime: STALE_TIMES.leaderboard,
    placeholderData: keepPreviousData,
  });
}

/** Fetch available sort columns for batting leaderboard. */
export function useBattingSortColumns() {
  const { format } = useFormat();
  return useQuery<string[]>({
    queryKey: [format, ...queryKeys.battingSortColumns],
    queryFn: () => api.getBattingSortColumns(),
    staleTime: STALE_TIMES.reference,
  });
}

/** Fetch available sort columns for bowling leaderboard. */
export function useBowlingSortColumns() {
  const { format } = useFormat();
  return useQuery<string[]>({
    queryKey: [format, ...queryKeys.bowlingSortColumns],
    queryFn: () => api.getBowlingSortColumns(),
    staleTime: STALE_TIMES.reference,
  });
}

/** Fetch top N players for a specific metric. */
export function useTopPlayers(params: {
  role?: string;
  metric?: string;
  limit?: number;
  /** Omit to request all players (provisional + qualified). */
  provisional?: boolean | null;
  minInnings?: number;
}) {
  const { format } = useFormat();
  return useQuery({
    queryKey: [
      format,
      ...queryKeys.topPlayers(
        params.role,
        params.metric,
        params.limit,
        params.provisional,
        params.minInnings,
        "active",
      ),
    ],
    queryFn: () =>
      api.getTopPlayers({
        role: params?.role,
        metric: params?.metric,
        limit: params?.limit ?? 5,
        provisional: params.provisional,
        min_innings: params.minInnings,
        activity: "active",
      }),
    staleTime: STALE_TIMES.leaderboard,
  });
}

// ── Compare hooks ────────────────────────────────────────────────

/** Compare 2–4 players side by side. */
export function useComparePlayers(
  ids: string[],
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const sortedIds = [...ids].sort();
  return useQuery<CompareResponse>({
    queryKey: [format, ...queryKeys.compare(sortedIds)],
    queryFn: () => api.comparePlayers(sortedIds),
    staleTime: STALE_TIMES.compare,
    enabled: (options?.enabled ?? true) && ids.length >= 2,
  });
}

/** Compare form time-series for multiple players. */
export function useCompareForm(ids: string[], options?: { enabled?: boolean }) {
  const { format } = useFormat();
  const sortedIds = [...ids].sort();
  return useQuery({
    queryKey: [format, ...queryKeys.compareForm(sortedIds)],
    queryFn: () => api.compareForm(sortedIds),
    staleTime: STALE_TIMES.compare,
    enabled: (options?.enabled ?? true) && ids.length >= 2,
  });
}

/** Find shared matchups between compared players. */
export function useSharedMatchups(
  ids: string[],
  params?: { minBalls?: number; limit?: number },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const sortedIds = [...ids].sort();
  return useQuery<SharedMatchupsResponse>({
    queryKey: [
      format,
      ...queryKeys.sharedMatchups(sortedIds, params?.minBalls, params?.limit),
    ],
    queryFn: ({ signal }) =>
      api.getSharedMatchups(sortedIds, {
        min_balls: params?.minBalls ?? 6,
        limit: params?.limit ?? 10,
        signal,
      }),
    staleTime: STALE_TIMES.compare,
    enabled: (options?.enabled ?? true) && ids.length >= 2,
  });
}

// ── Matchup hooks ────────────────────────────────────────────────

/** Fetch head-to-head between a specific batter and bowler. */
export function useHeadToHead(
  batterId: string | undefined,
  bowlerId: string | undefined,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<HeadToHeadResponse>({
    queryKey: [format, ...queryKeys.headToHead(batterId ?? "", bowlerId ?? "")],
    queryFn: () => api.getHeadToHead(batterId!, bowlerId!),
    staleTime: STALE_TIMES.matchups,
    enabled: (options?.enabled ?? true) && !!batterId && !!bowlerId,
  });
}

/** Explore all matchups for a player. */
export function useExploreMatchups(
  params: Partial<MatchupExploreParams>,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<MatchupExploreResponse>({
    queryKey: [format, ...queryKeys.exploreMatchups(params)],
    queryFn: () =>
      api.exploreMatchups({
        player_id: params.player_id!,
        role: params.role ?? "bat",
        min_balls: params.min_balls ?? 6,
        sort: params.sort ?? "dominance_index",
        order: params.order ?? "desc",
        page: params.page ?? 1,
        per_page: params.per_page ?? 25,
      }),
    staleTime: STALE_TIMES.matchups,
    placeholderData: keepPreviousData,
    enabled: (options?.enabled ?? true) && !!params.player_id,
  });
}

/** Fetch a bowler's top bunnies. */
export function useTopBunnies(
  bowlerId: string | undefined,
  params?: { minBalls?: number; limit?: number },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<MatchupSummary[]>({
    queryKey: [
      format,
      ...queryKeys.topBunnies(bowlerId ?? "", params?.minBalls, params?.limit),
    ],
    queryFn: ({ signal }) =>
      api.getTopBunnies(bowlerId!, {
        min_balls: params?.minBalls ?? 6,
        limit: params?.limit ?? 10,
        signal,
      }),
    staleTime: STALE_TIMES.matchups,
    enabled: (options?.enabled ?? true) && !!bowlerId,
  });
}

/** Fetch a batter's top nemeses. */
export function useTopNemeses(
  batterId: string | undefined,
  params?: { minBalls?: number; limit?: number },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<MatchupSummary[]>({
    queryKey: [
      format,
      ...queryKeys.topNemeses(batterId ?? "", params?.minBalls, params?.limit),
    ],
    queryFn: ({ signal }) =>
      api.getTopNemeses(batterId!, {
        min_balls: params?.minBalls ?? 6,
        limit: params?.limit ?? 10,
        signal,
      }),
    staleTime: STALE_TIMES.matchups,
    enabled: (options?.enabled ?? true) && !!batterId,
  });
}

/** Fetch a batter's top dominant matchups. */
export function useTopDominantMatchups(
  batterId: string | undefined,
  params?: { minBalls?: number; limit?: number },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<MatchupSummary[]>({
    queryKey: [
      format,
      ...queryKeys.topDominant(batterId ?? "", params?.minBalls, params?.limit),
    ],
    queryFn: ({ signal }) =>
      api.getTopDominantMatchups(batterId!, {
        min_balls: params?.minBalls ?? 6,
        limit: params?.limit ?? 10,
        signal,
      }),
    staleTime: STALE_TIMES.matchups,
    enabled: (options?.enabled ?? true) && !!batterId,
  });
}

// ── Venue hooks ──────────────────────────────────────────────────

/** Fetch all venue baselines. */
export function useVenues(params?: Partial<VenueListParams>) {
  const { format } = useFormat();
  return useQuery<VenueListResponse>({
    queryKey: [format, ...queryKeys.venues(params)],
    queryFn: () =>
      api.getVenues({
        sort: params?.sort,
        order: params?.order,
        min_matches: params?.min_matches,
      }),
    staleTime: STALE_TIMES.venues,
    placeholderData: keepPreviousData,
  });
}

/** Fetch detail for a specific venue. */
export function useVenueDetail(
  venueName: string | undefined,
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  return useQuery<VenueDetail>({
    queryKey: [format, ...queryKeys.venueDetail(venueName ?? "")],
    queryFn: () => api.getVenueDetail(venueName!),
    staleTime: STALE_TIMES.venues,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

/** Rich venue profile (vs world, phases, chase/defend). */
export function useVenueProfile(
  venueName: string | undefined,
  options?: { enabled?: boolean; exact?: boolean },
) {
  const { format } = useFormat();
  const exact = options?.exact ?? true;
  return useQuery({
    queryKey: [format, ...queryKeys.venueProfile(venueName ?? "", exact)],
    queryFn: ({ signal }) =>
      api.getVenueProfile(venueName!, { exact, signal }),
    staleTime: STALE_TIMES.venues,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

export function useVenueTrends(
  venueName: string | undefined,
  params?: { bucket?: string; exact?: boolean },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const bucket = params?.bucket ?? "rolling_3_match";
  const exact = params?.exact ?? true;
  return useQuery({
    queryKey: [format, ...queryKeys.venueTrends(venueName ?? "", bucket, exact)],
    queryFn: ({ signal }) =>
      api.getVenueTrends(venueName!, { bucket, exact, signal }),
    staleTime: STALE_TIMES.venues,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

export function useVenueTeams(
  venueName: string | undefined,
  params?: {
    page?: number;
    perPage?: number;
    sort?: string;
    order?: string;
    minMatches?: number;
    exact?: boolean;
  },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const exact = params?.exact ?? true;
  const q = { ...params, exact };
  return useQuery({
    queryKey: [format, ...queryKeys.venueTeams(venueName ?? "", q)],
    queryFn: ({ signal }) =>
      api.getVenueTeams(venueName!, {
        page: params?.page ?? 1,
        per_page: params?.perPage ?? 25,
        sort: params?.sort ?? "win_pct",
        order: params?.order ?? "desc",
        min_matches: params?.minMatches ?? 2,
        exact,
        signal,
      }),
    staleTime: STALE_TIMES.venues,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

export function useVenueSimilar(
  venueName: string | undefined,
  params?: { k?: number; exact?: boolean },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const exact = params?.exact ?? true;
  return useQuery({
    queryKey: [
      format,
      ...queryKeys.venueSimilar(venueName ?? "", params?.k ?? 8, exact),
    ],
    queryFn: ({ signal }) =>
      api.getVenueSimilar(venueName!, {
        k: params?.k ?? 8,
        exact,
        signal,
      }),
    staleTime: STALE_TIMES.venues,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

export function useVenueMatchesList(
  venueName: string | undefined,
  params?: { page?: number; perPage?: number; exact?: boolean },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const exact = params?.exact ?? true;
  return useQuery({
    queryKey: [
      format,
      ...queryKeys.venueMatches(venueName ?? "", params?.page, exact),
    ],
    queryFn: ({ signal }) =>
      api.getVenueMatches(venueName!, {
        page: params?.page ?? 1,
        per_page: params?.perPage ?? 25,
        exact,
        signal,
      }),
    staleTime: STALE_TIMES.venues,
    placeholderData: keepPreviousData,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

export function useVenuePerformances(
  venueName: string | undefined,
  params?: {
    role?: string;
    sort?: string;
    order?: string;
    page?: number;
    perPage?: number;
    minBalls?: number;
    exact?: boolean;
  },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const exact = params?.exact ?? true;
  const q = { ...params, exact };
  return useQuery({
    queryKey: [format, ...queryKeys.venuePerformances(venueName ?? "", q)],
    queryFn: ({ signal }) =>
      api.getVenuePerformances(venueName!, {
        role: params?.role ?? "bat",
        sort: params?.sort ?? "bat_impact",
        order: params?.order ?? "desc",
        page: params?.page ?? 1,
        per_page: params?.perPage ?? 25,
        min_balls: params?.minBalls ?? 5,
        exact,
        signal,
      }),
    staleTime: STALE_TIMES.venues,
    placeholderData: keepPreviousData,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

/** Fetch player performances at a specific venue. */
export function usePlayersAtVenue(
  venueName: string | undefined,
  params?: {
    role?: string;
    minInnings?: number;
    sort?: string;
    order?: string;
    page?: number;
    perPage?: number;
    exact?: boolean;
  },
  options?: { enabled?: boolean },
) {
  const { format } = useFormat();
  const exact = params?.exact ?? true;
  return useQuery({
    queryKey: [
      format,
      ...queryKeys.playersAtVenue(
        venueName ?? "",
        params?.role,
        params?.minInnings,
        params?.sort,
        params?.order,
        params?.page,
        params?.perPage,
        exact,
      ),
    ],
    queryFn: ({ signal }) =>
      api.getPlayersAtVenue(venueName!, {
        role: params?.role ?? "bat",
        min_innings: params?.minInnings ?? 2,
        sort: params?.sort ?? "runs",
        order: params?.order ?? "desc",
        page: params?.page ?? 1,
        per_page: params?.perPage ?? 25,
        exact,
        signal,
      }),
    staleTime: STALE_TIMES.venues,
    placeholderData: keepPreviousData,
    enabled: (options?.enabled ?? true) && !!venueName,
  });
}

/** Fetch aggregated venue summary (difficulty distribution, etc.). */
export function useVenueSummary() {
  const { format } = useFormat();
  return useQuery<VenueSummary>({
    queryKey: [format, ...queryKeys.venueSummary],
    queryFn: () => api.getVenueSummary(),
    staleTime: STALE_TIMES.venues,
  });
}

// ── Live ESPN (proxied scoreboard; global, not format-scoped) ────

/** Cached cricket scoreboard via ESPN public JSON (see backend TTL). */
export function useEspnCricketScoreboard(params: {
  league: string;
  dates?: string | null;
  region?: string | null;
  lang?: string | null;
  enabled?: boolean;
}) {
  const league = params.league.trim();
  return useQuery<EspnCricketScoreboardResponse>({
    queryKey: queryKeys.espnCricketScoreboard(
      league,
      params.dates ?? null,
      params.region ?? null,
      params.lang ?? null,
    ),
    queryFn: ({ signal }) =>
      api.getEspnCricketScoreboard(
        {
          league,
          dates: params.dates,
          region: params.region,
          lang: params.lang ?? "en",
        },
        signal,
      ),
    staleTime: STALE_TIMES.liveEspn,
    refetchOnWindowFocus: false,
    enabled: params.enabled !== false && league.length > 0,
  });
}

/** Single-match scorecard summary from ESPN (proxied; needs league_id + event_id from live list). */
export function useEspnCricketMatchSummary(params: {
  leagueId: string;
  eventId: string;
  enabled?: boolean;
}) {
  const { format } = useFormat();
  const leagueId = params.leagueId.trim();
  const eventId = params.eventId.trim();
  return useQuery<EspnCricketMatchSummaryResponse>({
    queryKey: [format, ...queryKeys.espnCricketMatchSummary(leagueId, eventId)],
    queryFn: ({ signal }) =>
      api.getEspnCricketMatchSummary({ leagueId, eventId }, signal),
    staleTime: STALE_TIMES.liveEspn,
    refetchInterval: STALE_TIMES.liveEspn,
    refetchOnWindowFocus: false,
    enabled:
      params.enabled !== false && leagueId.length > 0 && eventId.length > 0,
  });
}

// ── Eras hooks ───────────────────────────────────────────────────

/** Fetch era baselines (par SR, boundary rate, dot%, multiplier) by year. */
export function useEras() {
  const { format } = useFormat();
  return useQuery<EraResponse>({
    queryKey: [format, ...queryKeys.eras],
    queryFn: ({ signal }) => api.getEras(signal),
    staleTime: STALE_TIMES.reference,
  });
}

// ── Team Builder hooks ───────────────────────────────────────────

/** Analyse a set of player IDs as a team (aggregate metrics, weaknesses). */
export function useTeamAnalysis(
  ids: string[],
  slotTypes?: string[],
  bowlingPhases?: string[],
) {
  const { format } = useFormat();
  return useQuery<TeamAnalysis>({
    queryKey: [format, ...queryKeys.teamAnalyse(ids, slotTypes, bowlingPhases)],
    queryFn: ({ signal }) =>
      api.analyseTeam(ids, signal, slotTypes, bowlingPhases),
    staleTime: STALE_TIMES.compare,
    enabled: ids.length > 0,
  });
}

/** Auto-fill a team XI based on a strategy (war, power, control, country). */
export function useTeamAutoFill(params: {
  strategy?: string;
  country?: string | null;
  exclude?: string[];
  enabled?: boolean;
}) {
  const { format } = useFormat();
  return useQuery<TeamAnalysis>({
    queryKey: [
      format,
      ...queryKeys.teamAutoFill(params.strategy, params.country),
    ],
    queryFn: ({ signal }) =>
      api.autoFillTeam(
        {
          strategy: params.strategy ?? "balanced",
          country: params.country,
          exclude: params.exclude,
        },
        signal,
      ),
    staleTime: STALE_TIMES.compare,
    enabled: params.enabled !== false,
  });
}

/** Parallel team analyses for Team Builder compare mode (2–4 XIs). */
export function useTeamAnalysesParallel(
  teams: Array<{
    ids: string[];
    slotTypes: string[];
    bowlingPhases?: string[];
  }>,
) {
  const { format } = useFormat();
  return useQueries({
    queries: teams.map((t) => ({
      queryKey: [
        format,
        ...queryKeys.teamAnalyse(t.ids, t.slotTypes, t.bowlingPhases),
      ] as const,
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.analyseTeam(t.ids, signal, t.slotTypes, t.bowlingPhases),
      staleTime: STALE_TIMES.compare,
      enabled: t.ids.length > 0,
    })),
  });
}
