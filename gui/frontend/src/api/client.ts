/**
 * API Client — typed fetch wrapper for all Cricket Metrics backend endpoints.
 *
 * All functions return typed promises that resolve to the response data.
 * Errors are thrown as `ApiError` instances with status code and message.
 *
 * The base URL is determined by:
 * 1. `VITE_API_URL` environment variable (for production builds)
 * 2. Empty string (for development — Vite proxy handles `/api` → backend)
 *
 * Usage:
 *   import { api } from '@/api/client';
 *   const results = await api.search({ q: 'kohli', role: 'bat' });
 *   const profile = await api.getPlayer('ba607b88');
 */

import type {
  ApiMeta,
  BatterProfile,
  BowlerProfile,
  CompareResponse,
  EraResponse,
  FlatTrackParams,
  FlatTrackResponse,
  FormBatchResponse,
  FormResponse,
  HeadToHeadResponse,
  InningsLogResponse,
  LeaderboardParams,
  LeaderboardResponse,
  MatchupExploreParams,
  MatchImpactPerformancesParams,
  MatchImpactPerformancesResponse,
  MatchupExploreResponse,
  MatchupSummary,
  PlayerMatchImpactRow,
  PlayerProfile,
  PlayerRoles,
  PlayerSummary,
  SearchParams,
  SearchResponse,
  SharedMatchupsResponse,
  SimilarityResponse,
  SpellsLogResponse,
  TeamAnalysis,
  TeamCompareResponse,
  VenueDetail,
  VenueListParams,
  VenueListResponse,
  VenueSummary,
  EspnCricketMatchSummaryResponse,
  EspnCricketScoreboardResponse,
} from "./types";
import type { Format } from "@/api/formatConstants";

// ── Configuration ────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_API_URL ?? "";

/**
 * Default request timeout in milliseconds (10 seconds).
 * Individual calls can override this.
 */
const DEFAULT_TIMEOUT_MS = 10_000;

// ── Global format state ──────────────────────────────────────────
// The FormatContext calls setFormat() whenever the user toggles between
// men's/women's T20 and IPL. All API requests include ?format= via buildUrl().

type FormatValue = Format;

let _currentFormat: FormatValue = "mens_t20i";

/**
 * Set the active data format. Called by FormatContext when the user
 * switches dataset slice.
 */
export function setClientFormat(f: FormatValue): void {
  _currentFormat = f;
}

/**
 * Get the active data format.
 */
export function getClientFormat(): FormatValue {
  return _currentFormat;
}

// ── Error class ──────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly detail: string,
    public readonly url: string,
  ) {
    super(`API ${status} ${statusText}: ${detail} (${url})`);
    this.name = "ApiError";
  }

  /** True if the resource was not found (404). */
  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** True if the request was malformed (400). */
  get isBadRequest(): boolean {
    return this.status === 400;
  }

  /** True if the server errored (5xx). */
  get isServerError(): boolean {
    return this.status >= 500;
  }
}

// ── Core fetch wrapper ───────────────────────────────────────────

/**
 * Build a URL with query parameters, stripping null/undefined values.
 *
 * Automatically appends `?format=` from the global format state unless
 * the caller has already provided an explicit `format` param.
 */
function buildUrl(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>,
  omitFormat = false,
): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);

  const merged: Record<string, string | number | boolean | null | undefined> =
    omitFormat
      ? { ...params }
      : {
          format: _currentFormat,
          ...params,
        };

  for (const [key, value] of Object.entries(merged)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  return url.toString();
}

/**
 * Core fetch function with timeout, error handling, and JSON parsing.
 */
async function fetchJson<T>(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>,
  options?: {
    timeoutMs?: number;
    signal?: AbortSignal;
    /** Skip `format=` (used for endpoints unrelated to T20I/IPL datasets). */
    omitFormat?: boolean;
  },
): Promise<T> {
  const url = buildUrl(path, params, options?.omitFormat ?? false);
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  // Create an AbortController for timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // If the caller provided their own signal (e.g. from React Query),
  // abort our controller when their signal fires.
  if (options?.signal) {
    if (options.signal.aborted) {
      controller.abort();
    } else {
      options.signal.addEventListener("abort", () => controller.abort(), {
        once: true,
      });
    }
  }

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body.detail ?? body.message ?? detail;
      } catch {
        // Body wasn't JSON — use statusText
      }
      throw new ApiError(response.status, response.statusText, detail, url);
    }

    const data: T = await response.json();
    return data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }

    // AbortError from timeout or caller cancellation
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        0,
        "Aborted",
        `Request aborted (timeout ${timeoutMs}ms or cancelled)`,
        url,
      );
    }

    // Network error
    if (error instanceof TypeError) {
      throw new ApiError(
        0,
        "NetworkError",
        `Network error: ${error.message}. Is the backend running?`,
        url,
      );
    }

    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ── API functions ────────────────────────────────────────────────

// ── Health & Meta ────────────────────────────────────────────────

/** Check if the API is healthy. */
async function health(signal?: AbortSignal): Promise<{ status: string }> {
  return fetchJson("/api/health", undefined, { signal });
}

/** Get API metadata (dataset summary, countries, archetypes). */
async function meta(signal?: AbortSignal): Promise<ApiMeta> {
  return fetchJson("/api/meta", undefined, { signal });
}

// ── Search ───────────────────────────────────────────────────────

/** Full search with all filter options. */
async function search(
  params: SearchParams,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  return fetchJson(
    "/api/search",
    {
      q: params.q,
      role: params.role,
      country: params.country,
      archetype: params.archetype,
      provisional: params.provisional,
      min_innings: params.min_innings,
      limit: params.limit,
    },
    { signal },
  );
}

/** Lightweight autocomplete (min 2 chars, max 8 results). */
async function autocomplete(
  q: string,
  options?: {
    role?: string | null;
    country?: string | null;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<PlayerSummary[]> {
  if (q.length < 2) return [];
  return fetchJson(
    "/api/search/autocomplete",
    {
      q,
      role: options?.role,
      country: options?.country,
      limit: options?.limit ?? 8,
    },
    { signal: options?.signal },
  );
}

/** Get all countries in the dataset (for filter dropdowns). */
async function getCountries(signal?: AbortSignal): Promise<string[]> {
  return fetchJson("/api/search/countries", undefined, { signal });
}

/** Get all archetypes by role (for filter dropdowns). */
async function getArchetypes(
  signal?: AbortSignal,
): Promise<Record<string, string[]>> {
  return fetchJson("/api/search/archetypes", undefined, { signal });
}

// ── Player Profile ───────────────────────────────────────────────

/**
 * Get which roles (bat/bowl) a player has, with innings counts for each.
 * Used to determine the default profile view and whether to show a toggle.
 */
async function getPlayerRoles(
  playerId: string,
  signal?: AbortSignal,
): Promise<PlayerRoles> {
  return fetchJson(
    `/api/player/${encodeURIComponent(playerId)}/roles`,
    undefined,
    { signal },
  );
}

/**
 * Get the full profile for a player (auto-detects batting vs bowling).
 *
 * Returns a `BatterProfile` or `BowlerProfile` depending on the player's
 * primary role. Use `isBatterProfile()` / `isBowlerProfile()` type guards
 * to narrow.
 */
async function getPlayer(
  playerId: string,
  signal?: AbortSignal,
): Promise<PlayerProfile> {
  return fetchJson(`/api/player/${encodeURIComponent(playerId)}`, undefined, {
    signal,
  });
}

/** Get the explicit batting profile for a player. */
async function getBatterProfile(
  playerId: string,
  signal?: AbortSignal,
): Promise<BatterProfile> {
  return fetchJson(
    `/api/player/${encodeURIComponent(playerId)}/batting`,
    undefined,
    { signal },
  );
}

/** Get the explicit bowling profile for a player. */
async function getBowlerProfile(
  playerId: string,
  signal?: AbortSignal,
): Promise<BowlerProfile> {
  return fetchJson(
    `/api/player/${encodeURIComponent(playerId)}/bowling`,
    undefined,
    { signal },
  );
}

/** Get paginated innings log for a batter. */
async function getPlayerInnings(
  playerId: string,
  options?: {
    page?: number;
    per_page?: number;
    sort_by?: string;
    order?: string;
    signal?: AbortSignal;
  },
): Promise<InningsLogResponse> {
  return fetchJson(
    `/api/player/${encodeURIComponent(playerId)}/innings`,
    {
      page: options?.page ?? 1,
      per_page: options?.per_page ?? 25,
      sort_by: options?.sort_by ?? "date",
      order: options?.order ?? "desc",
    },
    { signal: options?.signal },
  );
}

/** Get paginated spells log for a bowler. */
async function getPlayerSpells(
  playerId: string,
  options?: {
    page?: number;
    per_page?: number;
    sort_by?: string;
    order?: string;
    signal?: AbortSignal;
  },
): Promise<SpellsLogResponse> {
  return fetchJson(
    `/api/player/${encodeURIComponent(playerId)}/spells`,
    {
      page: options?.page ?? 1,
      per_page: options?.per_page ?? 25,
      sort_by: options?.sort_by ?? "date",
      order: options?.order ?? "desc",
    },
    { signal: options?.signal },
  );
}

/** Get the form time-series for a player. */
async function getPlayerForm(
  playerId: string,
  role?: string,
  signal?: AbortSignal,
): Promise<FormResponse> {
  const params: Record<string, string> = {};
  if (role) params.role = role;
  return fetchJson(`/api/player/${encodeURIComponent(playerId)}/form`, params, {
    signal,
  });
}

/** Get form summary for multiple players (last 2 years, active flag). For leaderboard form tracker. */
async function getFormBatch(
  playerIds: string[],
  role: "bat" | "bowl",
  signal?: AbortSignal,
): Promise<FormBatchResponse> {
  if (playerIds.length === 0) {
    return { results: [] };
  }
  return fetchJson(
    "/api/player/form-batch",
    { ids: playerIds.join(","), role },
    { signal },
  );
}

/** Get all matchups for a player (paginated). */
async function getPlayerMatchups(
  playerId: string,
  params?: Partial<MatchupExploreParams>,
  signal?: AbortSignal,
): Promise<MatchupExploreResponse> {
  return fetchJson(
    `/api/player/${encodeURIComponent(playerId)}/matchups`,
    {
      role: params?.role ?? "bat",
      min_balls: params?.min_balls ?? 6,
      sort_by: params?.sort ?? "dominance_index",
      order: params?.order ?? "desc",
      page: params?.page ?? 1,
      per_page: params?.per_page ?? 25,
    },
    { signal },
  );
}

/** Get similar players for a given player. */
async function getPlayerSimilar(
  playerId: string,
  options?: {
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<SimilarityResponse> {
  return fetchJson(
    `/api/player/${encodeURIComponent(playerId)}/similar`,
    { limit: options?.limit ?? 10 },
    { signal: options?.signal },
  );
}

// ── Rankings / Leaderboards ──────────────────────────────────────

/** Get the batting leaderboard with filters and pagination. */
async function getBattingRankings(
  params?: LeaderboardParams,
  signal?: AbortSignal,
): Promise<LeaderboardResponse> {
  return fetchJson(
    "/api/rankings/bat",
    {
      sort: params?.sort ?? "rating_current",
      order: params?.order ?? "desc",
      country: params?.country,
      archetype: params?.archetype,
      position_group: params?.position_group,
      modal_slot: params?.modal_slot,
      min_innings: params?.min_innings,
      provisional: params?.provisional,
      activity: params?.activity ?? "active",
      page: params?.page ?? 1,
      per_page: params?.per_page ?? 25,
      ...(params?.ctx_entry_phase && params.ctx_entry_phase !== "none"
        ? { ctx_entry_phase: params.ctx_entry_phase }
        : {}),
      ...(params?.ctx_knockouts_only ? { ctx_knockouts_only: true } : {}),
      ...(params?.ctx_chase_high_rpo ? { ctx_chase_high_rpo: true } : {}),
    },
    { signal },
  );
}

/** Get the bowling leaderboard with filters and pagination. */
async function getBowlingRankings(
  params?: LeaderboardParams,
  signal?: AbortSignal,
): Promise<LeaderboardResponse> {
  return fetchJson(
    "/api/rankings/bowl",
    {
      sort: params?.sort ?? "rating_current",
      order: params?.order ?? "desc",
      country: params?.country,
      archetype: params?.archetype,
      phase_group: params?.phase_group,
      min_innings: params?.min_innings,
      provisional: params?.provisional,
      activity: params?.activity ?? "active",
      page: params?.page ?? 1,
      per_page: params?.per_page ?? 25,
    },
    { signal },
  );
}

/** Get top-N players for a specific metric (for dashboard cards). */
async function getTopPlayers(
  params: {
    role?: string;
    metric?: string;
    limit?: number;
    provisional?: boolean | null;
    min_innings?: number | null;
    activity?: "active" | "retired" | "all";
  },
  signal?: AbortSignal,
): Promise<PlayerSummary[]> {
  const q: Record<string, string | number | boolean | null | undefined> = {
    role: params.role ?? "bat",
    metric: params.metric ?? "rating_current",
    limit: params.limit ?? 5,
    activity: params.activity ?? "active",
  };
  if (params.provisional !== undefined) {
    q.provisional = params.provisional;
  }
  if (params.min_innings !== undefined && params.min_innings !== null) {
    q.min_innings = params.min_innings;
  }
  return fetchJson("/api/rankings/top", q, { signal });
}

/** Get valid sort columns for batting leaderboard. */
async function getBattingSortColumns(signal?: AbortSignal): Promise<string[]> {
  return fetchJson("/api/rankings/columns/bat", undefined, { signal });
}

/** Get valid sort columns for bowling leaderboard. */
async function getBowlingSortColumns(signal?: AbortSignal): Promise<string[]> {
  return fetchJson("/api/rankings/columns/bowl", undefined, { signal });
}

// ── Compare ──────────────────────────────────────────────────────

/**
 * Compare 2–4 players side-by-side.
 *
 * @param ids Array of player IDs (2–4).
 */
async function comparePlayers(
  ids: string[],
  signal?: AbortSignal,
): Promise<CompareResponse> {
  return fetchJson("/api/compare", { ids: ids.join(",") }, { signal });
}

/** Get overlaid form time-series for 2–4 players. */
async function compareForm(
  ids: string[],
  signal?: AbortSignal,
): Promise<FormResponse[]> {
  return fetchJson("/api/compare/form", { ids: ids.join(",") }, { signal });
}

/** Find bowlers that multiple batters have both faced. */
async function getSharedMatchups(
  ids: string[],
  options?: {
    min_balls?: number;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<SharedMatchupsResponse> {
  return fetchJson(
    "/api/compare/shared-matchups",
    {
      ids: ids.join(","),
      min_balls: options?.min_balls ?? 6,
      limit: options?.limit ?? 20,
    },
    { signal: options?.signal },
  );
}

// ── Matchups ─────────────────────────────────────────────────────

/** Get head-to-head matchup between a specific batter and bowler. */
async function getHeadToHead(
  batterId: string,
  bowlerId: string,
  signal?: AbortSignal,
): Promise<HeadToHeadResponse> {
  return fetchJson(
    "/api/matchups",
    { bat: batterId, bowl: bowlerId },
    { signal },
  );
}

/** Browse all matchups for a given player. */
async function exploreMatchups(
  params: MatchupExploreParams,
  signal?: AbortSignal,
): Promise<MatchupExploreResponse> {
  return fetchJson(
    "/api/matchups/explore",
    {
      player_id: params.player_id,
      role: params.role ?? "bat",
      min_balls: params.min_balls ?? 6,
      sort: params.sort ?? "dominance_index",
      order: params.order ?? "desc",
      page: params.page ?? 1,
      per_page: params.per_page ?? 25,
    },
    { signal },
  );
}

/** Get a bowler's top bunnies (batters they dominate). */
async function getTopBunnies(
  bowlerId: string,
  options?: {
    min_balls?: number;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<MatchupSummary[]> {
  return fetchJson(
    "/api/matchups/top-bunnies",
    {
      bowler_id: bowlerId,
      min_balls: options?.min_balls ?? 6,
      limit: options?.limit ?? 10,
    },
    { signal: options?.signal },
  );
}

/** Get a batter's top nemeses (bowlers who dominate them). */
async function getTopNemeses(
  batterId: string,
  options?: {
    min_balls?: number;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<MatchupSummary[]> {
  return fetchJson(
    "/api/matchups/top-nemeses",
    {
      batter_id: batterId,
      min_balls: options?.min_balls ?? 6,
      limit: options?.limit ?? 10,
    },
    { signal: options?.signal },
  );
}

/** Get the bowlers a batter dominates the most. */
async function getTopDominantMatchups(
  batterId: string,
  options?: {
    min_balls?: number;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<MatchupSummary[]> {
  return fetchJson(
    "/api/matchups/top-dominant",
    {
      batter_id: batterId,
      min_balls: options?.min_balls ?? 6,
      limit: options?.limit ?? 10,
    },
    { signal: options?.signal },
  );
}

// ── Venues ───────────────────────────────────────────────────────

/** Get all venue baselines. */
async function getVenues(
  params?: VenueListParams,
  signal?: AbortSignal,
): Promise<VenueListResponse> {
  return fetchJson(
    "/api/venues",
    {
      sort: params?.sort ?? "venue_difficulty",
      order: params?.order ?? "desc",
      min_matches: params?.min_matches ?? 0,
    },
    { signal },
  );
}

/** Get detailed info for a single venue. */
async function getVenueDetail(
  venue: string,
  signal?: AbortSignal,
): Promise<VenueDetail> {
  return fetchJson("/api/venues/detail", { venue }, { signal });
}

/** Get player performance at a specific venue. */
async function getPlayersAtVenue(
  venue: string,
  options?: {
    role?: string;
    min_innings?: number;
    sort?: string;
    order?: string;
    page?: number;
    per_page?: number;
    signal?: AbortSignal;
  },
): Promise<{
  venue: string;
  role: string;
  players: Array<Record<string, unknown>>;
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  message?: string;
}> {
  return fetchJson(
    "/api/venues/players",
    {
      venue,
      role: options?.role ?? "bat",
      min_innings: options?.min_innings ?? 2,
      sort: options?.sort ?? "runs",
      order: options?.order ?? "desc",
      page: options?.page ?? 1,
      per_page: options?.per_page ?? 25,
    },
    { signal: options?.signal },
  );
}

/** Get the Flat Track Bully Index leaderboard. */
async function getFlatTrackIndex(
  params?: FlatTrackParams,
  signal?: AbortSignal,
): Promise<FlatTrackResponse> {
  return fetchJson(
    "/api/venues/flat-track-index",
    {
      role: params?.role ?? "bat",
      min_innings: params?.min_innings ?? 20,
      provisional: params?.provisional ?? false,
      sort: params?.sort ?? "flat_track_index",
      order: params?.order ?? "asc",
      page: params?.page ?? 1,
      per_page: params?.per_page ?? 25,
    },
    { signal },
  );
}

/** Get a high-level venue summary (for the Venue Analysis page header). */
async function getVenueSummary(signal?: AbortSignal): Promise<VenueSummary> {
  return fetchJson("/api/venues/summary", undefined, { signal });
}

// ── Eras ─────────────────────────────────────────────────────────

/** Get era baselines (par SR, boundary rate, dot%, multiplier) by year. */
async function getEras(signal?: AbortSignal): Promise<EraResponse> {
  return fetchJson("/api/eras", undefined, { signal });
}

// ── Team Builder ─────────────────────────────────────────────────

/** Analyse a team selection (aggregate metrics, weaknesses). */
async function analyseTeam(
  ids: string[],
  signal?: AbortSignal,
  slotTypes?: string[],
  bowlingPhases?: string[],
): Promise<TeamAnalysis> {
  const params: Record<string, string> = { ids: ids.join(",") };
  if (slotTypes && slotTypes.length > 0) {
    params.slot_types = slotTypes.join(",");
  }
  if (
    bowlingPhases &&
    bowlingPhases.length > 0 &&
    bowlingPhases.some((p) => p && p.length > 0)
  ) {
    params.bowling_phases = bowlingPhases.map((p) => p || "").join(",");
  }
  return fetchJson("/api/team/analyse", params, { signal });
}

/** Auto-fill a team XI based on a strategy. */
async function autoFillTeam(
  params: {
    strategy?: string;
    country?: string | null;
    exclude?: string[];
  },
  signal?: AbortSignal,
): Promise<TeamAnalysis> {
  return fetchJson(
    "/api/team/auto-fill",
    {
      strategy: params.strategy ?? "balanced",
      country: params.country,
      exclude: params.exclude?.length ? params.exclude.join(",") : undefined,
    },
    { signal },
  );
}

/** Compare two teams side-by-side. */
async function compareTeams(
  teamAIds: string[],
  teamBIds: string[],
  signal?: AbortSignal,
): Promise<TeamCompareResponse> {
  return fetchJson(
    "/api/team/compare",
    {
      team_a: teamAIds.join(","),
      team_b: teamBIds.join(","),
    },
    { signal },
  );
}

// ── Scorecards ───────────────────────────────────────────────────

/** Search scorecards by date range, team, or player. */
async function searchScorecards(
  params?: {
    date_from?: string | null;
    date_to?: string | null;
    team?: string | null;
    player_id?: string | null;
    limit?: number;
  },
  signal?: AbortSignal,
): Promise<Array<Record<string, unknown>>> {
  const body = await fetchJson<unknown>(
    "/api/scorecards/search",
    {
      date_from: params?.date_from,
      date_to: params?.date_to,
      team: params?.team,
      player_id: params?.player_id,
      limit: params?.limit ?? 500,
    },
    { signal },
  );
  if (Array.isArray(body)) return body as Array<Record<string, unknown>>;
  if (body && typeof body === "object" && "results" in body && Array.isArray((body as { results: unknown }).results)) {
    return (body as { results: Array<Record<string, unknown>> }).results;
  }
  return [];
}

/** Get full scorecard for a match (ball-by-ball data can be large; 60s timeout). */
async function getScorecard(
  matchId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  return fetchJson(
    `/api/scorecards/${encodeURIComponent(matchId)}`,
    undefined,
    { signal, timeoutMs: 60_000 },
  );
}

/** All scorecard matches with qualifying combined match impact for this player (best first). */
async function getPlayerMatchImpact(
  playerId: string,
  signal?: AbortSignal,
): Promise<PlayerMatchImpactRow[]> {
  const body = await fetchJson<unknown>(
    `/api/scorecards/player/${encodeURIComponent(playerId)}/match-impact`,
    undefined,
    { signal, timeoutMs: 120_000 },
  );
  if (!Array.isArray(body)) return [];
  return body as PlayerMatchImpactRow[];
}

/** Filterable, paginated match-impact performances across all scorecards. */
async function getMatchImpactPerformances(
  params: MatchImpactPerformancesParams,
  signal?: AbortSignal,
): Promise<MatchImpactPerformancesResponse> {
  return fetchJson<MatchImpactPerformancesResponse>(
    "/api/scorecards/performances/by-impact",
    {
      date_from: params.date_from ?? undefined,
      date_to: params.date_to ?? undefined,
      team: params.team ?? undefined,
      event: params.event ?? undefined,
      player_id: params.player_id ?? undefined,
      discipline: params.discipline ?? "combined",
      order: params.order ?? "desc",
      page: params.page ?? 1,
      per_page: params.per_page ?? 25,
    },
    { signal, timeoutMs: 120_000 },
  );
}

/** ESPN cricket scoreboard (unofficial upstream; server-cached). Omits `format=`. */
async function getEspnCricketScoreboard(
  params: {
    league: string;
    dates?: string | null;
    region?: string | null;
    lang?: string | null;
  },
  signal?: AbortSignal,
): Promise<EspnCricketScoreboardResponse> {
  return fetchJson(
    "/api/live/espn/cricket/scoreboard",
    {
      league: params.league.trim(),
      dates: params.dates?.trim() || undefined,
      region: params.region?.trim() || undefined,
      lang: params.lang?.trim() || undefined,
    },
    { signal, omitFormat: true },
  );
}

/** ESPN match summary (scorecard-shaped JSON) for one game; requires numeric league + event ids. */
async function getEspnCricketMatchSummary(
  params: { leagueId: string; eventId: string },
  signal?: AbortSignal,
): Promise<EspnCricketMatchSummaryResponse> {
  return fetchJson(
    "/api/live/espn/cricket/summary",
    {
      league_id: params.leagueId.trim(),
      event_id: params.eventId.trim(),
    },
    { signal, omitFormat: true },
  );
}

// ── Exported API object ──────────────────────────────────────────

/**
 * The API client.
 *
 * All methods are async and return typed promises. Errors are thrown
 * as `ApiError` instances.
 *
 * Usage:
 *   import { api } from '@/api/client';
 *
 *   // Search
 *   const results = await api.search({ q: 'kohli' });
 *
 *   // Player profile
 *   const player = await api.getPlayer('ba607b88');
 *
 *   // Leaderboard
 *   const leaders = await api.getBattingRankings({
 *     sort: 'score_power',
 *     order: 'desc',
 *     min_innings: 20,
 *     provisional: false,
 *   });
 */
export const api = {
  // Health & Meta
  health,
  meta,

  // Search
  search,
  autocomplete,
  getCountries,
  getArchetypes,

  // Player Profile
  getPlayerRoles,
  getPlayer,
  getBatterProfile,
  getBowlerProfile,
  getPlayerInnings,
  getPlayerSpells,
  getPlayerForm,
  getFormBatch,
  getPlayerMatchups,
  getPlayerSimilar,

  // Rankings / Leaderboards
  getBattingRankings,
  getBowlingRankings,
  getTopPlayers,
  getBattingSortColumns,
  getBowlingSortColumns,

  // Compare
  comparePlayers,
  compareForm,
  getSharedMatchups,

  // Matchups
  getHeadToHead,
  exploreMatchups,
  getTopBunnies,
  getTopNemeses,
  getTopDominantMatchups,

  // Venues
  getVenues,
  getVenueDetail,
  getPlayersAtVenue,
  getFlatTrackIndex,
  getVenueSummary,

  // Eras
  getEras,

  // Scorecards
  searchScorecards,
  getScorecard,
  getPlayerMatchImpact,
  getMatchImpactPerformances,

  // Live (ESPN proxy)
  getEspnCricketScoreboard,
  getEspnCricketMatchSummary,

  // Team Builder
  analyseTeam,
  autoFillTeam,
  compareTeams,
} as const;

export default api;
