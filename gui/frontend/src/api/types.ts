/**
 * TypeScript interfaces matching the FastAPI Pydantic response schemas.
 *
 * These types are the single source of truth for the frontend's understanding
 * of the API contract. Every API response is typed through these interfaces.
 */

// ── Player Summary (search results, leaderboards, cards) ─────────

export interface PlayerSummary {
  id: string;
  name: string;
  country: string;
  role: "bat" | "bowl";
  archetype: string;
  grade_overall: string;
  innings_count: number;
  total_runs: number; // or total_wickets for bowlers
  career_sr: number | null; // or career_economy for bowlers
  career_avg: number | null;
  score_1: number | null; // acceleration (bat) / accuracy (bowl)
  score_2: number | null; // power (bat) / control (bowl)
  score_3: number | null; // control (bat) / threat (bowl)
  score_1_label: string;
  score_2_label: string;
  score_3_label: string;
  is_provisional: boolean;
  overall_score: number | null;
  metrics?: Record<string, number | null>;
  /** ISO date of last game in the current format's dataset */
  last_match_date?: string | null;
  /** True if last match within format recency (1y T20I / 2y IPL) */
  is_active?: boolean;
  /** Simple views: prefer this over `overall_score` (rolling form, capped). */
  rating_current?: number | null;
  /** Expanded / career-style display rating (capped by peak form). */
  rating_overall?: number | null;
  /** Modal batting position 1–11 when role is bat */
  modal_position?: number | null;
  /** Squad / franchise from the player's most recent match in this format */
  recent_team?: string | null;
  /** Bowl: pp_heavy / middle_heavy / death_heavy when known */
  phase_group?: string | null;
  /** Team builder dual-skill hint (never show negative labels in UI) */
  allrounder_class?: "genuine" | "batting" | "bowling" | null;
  /**
   * Optional headshot URL for UI / social export. When present, must be CORS-accessible
   * for canvas compositing; backend may add this field later.
   */
  photo_url?: string | null;
}

// ── Phase Split ──────────────────────────────────────────────────

export interface PhaseSplit {
  balls: number | null;
  runs: number | null;
  sr: number | null;
  dots: number | null;
  fours: number | null;
  sixes: number | null;
  dot_pct: number | null;
  boundary_pct: number | null;
  // Bowling-specific
  wickets?: number | null;
  economy?: number | null;
}

// ── Chase Split ──────────────────────────────────────────────────

export interface ChaseSplit {
  innings: number | null;
  avg: number | null;
  sr: number | null;
  composite: number | null;
}

// ── Component Breakdown ──────────────────────────────────────────

export interface ComponentBreakdown {
  values: Record<string, number | null>;
}

// ── Matchup Summary ──────────────────────────────────────────────

export interface MatchupSummary {
  opponent_id: string;
  opponent_name: string;
  balls: number;
  runs: number;
  sr: number | null;
  dismissals: number;
  dot_pct: number | null;
  boundary_pct: number | null;
  dominance_index: number | null;
}

// ── Matchup Phase ────────────────────────────────────────────────

export interface MatchupPhase {
  phase: string;
  balls: number;
  runs: number;
  sr: number | null;
  dots: number;
  dismissals: number;
  dominance_index: number | null;
}

// ── Similar Player ───────────────────────────────────────────────

export interface SimilarPlayer {
  id: string;
  name: string;
  country: string;
  similarity_score: number | null;
  score_1: number | null;
  score_2: number | null;
  score_3: number | null;
  score_1_label: string;
  score_2_label: string;
  score_3_label: string;
}

// ── Form Point (time-series) ─────────────────────────────────────

export interface FormPoint {
  date: string;
  match_id: string;
  window_innings: number | null;
  composite: number | null;

  // ── 0-100 sub-scores (percentile-ranked) ──
  score_1: number | null; // Acceleration (bat) or Accuracy (bowl)
  score_2: number | null; // Power (bat) or Control (bowl)
  score_3: number | null; // Control (bat) or Threat (bowl)
  score_1_label: string;
  score_2_label: string;
  score_3_label: string;

  // ── Peak annotation ──
  is_peak_window: boolean;

  // ── Raw stats for tooltip / context ──
  window_avg_runs: number | null;
  window_avg_sr: number | null;
  window_total_runs: number | null;
  window_fours: number | null;
  window_sixes: number | null;

  // Batting form fields (raw component means)
  window_sr_vs_par: number | null;
  window_impact: number | null;
  window_boundary_pct: number | null;
  window_six_rate: number | null;
  window_dot_control: number | null;
  window_consistency: number | null;
  window_rotation: number | null;

  // Bowling form fields (raw component means)
  window_economy: number | null;
  window_dot_pct: number | null;
  window_wickets_per_spell: number | null;
  window_total_wickets: number | null;
  window_economy_vs_par: number | null;
  window_quality_wickets: number | null;
  window_threat_pressure: number | null;
}

// ── Player Roles (lightweight role detection) ────────────────────

export interface PlayerRoles {
  player_id: string;
  player_name: string;
  has_batting: boolean;
  has_bowling: boolean;
  batting_innings: number;
  bowling_innings: number;
  default_role: "bat" | "bowl";
}

// ── Venue Baseline ───────────────────────────────────────────────

export interface VenueBaseline {
  venue: string;
  matches: number;
  avg_par_sr: number | null;
  boundary_rate: number | null;
  dot_pct: number | null;
  /** 0–100 index; higher = harder conditions (percentile of internal difficulty). */
  difficulty_score: number | null;
}

// ── Full Batter Profile ──────────────────────────────────────────

export interface BatterProfile {
  // Identity
  id: string;
  name: string;
  country: string;
  archetype: string;
  archetypes?: string[];
  position_group: string;
  /** Most common batting slot 1–11 */
  modal_position?: number | null;
  /** Side they played for in their last game (batting_team) */
  recent_team?: string | null;
  /** Optional headshot; CORS required for social export canvas. */
  photo_url?: string | null;

  // Career stats
  innings_count: number;
  total_runs: number;
  total_balls: number;
  total_fours: number;
  total_sixes: number;
  total_outs: number;
  career_sr: number | null;
  career_avg: number | null;

  // Scores (0–100)
  score_acceleration: number | null;
  score_power: number | null;
  score_control: number | null;

  // Grades
  grade_acceleration: string;
  grade_power: string;
  grade_control: string;
  overall_score: number | null;
  overall_grade: string;
  /** Simple header: current form rating */
  rating_current?: number | null;
  /** Expanded: career-style overall (capped by form peak) */
  rating_overall?: number | null;

  // Provisional
  is_provisional: boolean;

  // Peak ratings
  peak_composite_batting: number | null;
  peak_window_start: string | null;
  peak_window_end: string | null;
  peak_window_innings: number | null;
  peak_window_composite: number | null;

  // Advanced metrics
  war_batting: number | null;
  war_batting_rate: number | null;
  clutch_index: number | null;
  clutch_sr_delta: number | null;
  pressure_innings: number | null;
  chase_master_index: number | null;
  chase_master_full: number | null;
  flat_track_index: number | null;
  venue_adjusted_composite: number | null;
  selfless_index: number | null;
  anchor_cost_ratio: number | null;
  avg_balls_to_par: number | null;

  // Matchup summary
  avg_dominance: number | null;
  pct_dominant: number | null;
  matchup_consistency: number | null;
  unique_bowlers: number | null;

  // Phase splits
  phases: Record<string, PhaseSplit>;

  // Chase splits
  chase_splits: Record<string, ChaseSplit>;

  // Component breakdowns
  components: Record<string, ComponentBreakdown>;

  // Top matchups
  top_dominant: MatchupSummary[];
  top_nemeses: MatchupSummary[];

  // Similar players
  similar: SimilarPlayer[];
}

// ── Full Bowler Profile ──────────────────────────────────────────

export interface BowlerProfile {
  // Identity
  id: string;
  name: string;
  country: string;
  archetype: string;
  archetypes?: string[];
  phase_group: string;
  /** Side they played for in their last game (bowling_team) */
  recent_team?: string | null;
  /** Optional headshot; CORS required for social export canvas. */
  photo_url?: string | null;

  // Career stats
  matches: number;
  total_overs: number | null;
  total_wickets: number;
  total_runs_conceded: number;
  career_economy: number | null;
  career_sr_bowl: number | null;
  career_dot_pct: number | null;
  bowled_lbw_pct: number | null;

  // Scores (0–100)
  score_accuracy: number | null;
  score_control: number | null;
  score_threat: number | null;

  // Grades
  grade_accuracy: string;
  grade_control: string;
  grade_threat: string;
  overall_score: number | null;
  overall_grade: string;
  rating_current?: number | null;
  rating_overall?: number | null;

  // Provisional
  is_provisional: boolean;

  // Peak ratings
  peak_composite_bowling: number | null;
  peak_window_start: string | null;
  peak_window_end: string | null;
  peak_window_spells: number | null;
  peak_window_composite: number | null;

  // Advanced metrics
  war_bowling: number | null;
  war_bowling_rate: number | null;
  clutch_index_bowl: number | null;
  pressure_spells: number | null;
  flat_track_index_bowl: number | null;

  // Matchup summary
  avg_dominance_bowl: number | null;
  pct_dominant_bowl: number | null;

  // Phase splits
  phases: Record<string, PhaseSplit>;

  // Component breakdowns
  components: Record<string, ComponentBreakdown>;

  // Top matchups
  top_bunnies: MatchupSummary[];
  top_dominated_by: MatchupSummary[];

  // Similar bowlers
  similar: SimilarPlayer[];
}

/**
 * Union type for any player profile (batter or bowler).
 * Use type guards to narrow.
 */
export type PlayerProfile = BatterProfile | BowlerProfile;

/** Type guard: check if a profile is a BatterProfile */
export function isBatterProfile(p: PlayerProfile): p is BatterProfile {
  return "score_acceleration" in p;
}

/** Type guard: check if a profile is a BowlerProfile */
export function isBowlerProfile(p: PlayerProfile): p is BowlerProfile {
  return "score_accuracy" in p;
}

// ── Innings Detail (paginated log) ───────────────────────────────

export interface InningsDetail {
  match_id: string;
  date: string;
  opposition: string;
  runs: number;
  balls_faced: number;
  sr: number | null;
  fours: number;
  sixes: number;
  dots: number;
  is_out: boolean;
  how_out: string;
  batting_position: number | null;
  powerplay_sr: number | null;
  middle_sr: number | null;
  death_sr: number | null;
  sr_vs_par: number | null;
  match_par_sr: number | null;
}

// ── Spell Detail (paginated log) ─────────────────────────────────

export interface SpellDetail {
  match_id: string;
  date: string;
  opposition: string;
  overs_bowled: number | null;
  runs_conceded: number;
  wickets: number;
  economy: number | null;
  dot_pct: number | null;
  fours_conceded: number;
  sixes_conceded: number;
  wides_count: number;
  noballs_count: number;
  powerplay_economy: number | null;
  middle_economy: number | null;
  death_economy: number | null;
  economy_vs_par: number | null;
}

// ── Paginated response wrapper ───────────────────────────────────

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  items: T[];
}

// ── Search Response ──────────────────────────────────────────────

export interface SearchResponse {
  results: PlayerSummary[];
  total: number;
}

// ── Leaderboard Response ─────────────────────────────────────────

export interface LeaderboardResponse {
  players: PlayerSummary[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

// ── Compare Response ─────────────────────────────────────────────

export interface CompareResponse {
  batters: BatterProfile[];
  bowlers: BowlerProfile[];
}

// ── Head-to-Head Response ────────────────────────────────────────

export interface HeadToHeadResponse {
  batter_id: string;
  batter_name: string;
  bowler_id: string;
  bowler_name: string;
  balls: number;
  runs: number;
  sr: number | null;
  dismissals: number;
  dots: number;
  fours: number;
  sixes: number;
  dot_pct: number | null;
  boundary_pct: number | null;
  dominance_index: number | null;
  by_phase: MatchupPhase[];
}

// ── Matchup Explore Response ─────────────────────────────────────

export interface MatchupExploreResponse {
  matchups: MatchupSummary[];
  total: number;
  page: number;
  per_page: number;
}

// ── Form Response ────────────────────────────────────────────────

export interface FormResponse {
  player_id: string;
  player_name: string;
  series: FormPoint[];
}

export interface FormBatchPoint {
  date: string;
  composite: number | null;
}

export interface FormBatchItem {
  player_id: string;
  form_points: FormBatchPoint[];
  last_played: string | null;
  active: boolean;
}

export interface FormBatchResponse {
  results: FormBatchItem[];
}

// ── Similarity Response ──────────────────────────────────────────

export interface SimilarityResponse {
  target_id: string;
  target_name: string;
  similar: SimilarPlayer[];
}

// ── Venue List Response ──────────────────────────────────────────

export interface VenueListResponse {
  venues: VenueBaseline[];
}

// ── Venue Detail ─────────────────────────────────────────────────

export interface VenueDetail {
  venue: string;
  matches: number;
  avg_par_sr: number | null;
  par_sr_std: number | null;
  boundary_rate: number | null;
  dot_pct: number | null;
  difficulty_raw: number | null;
  /** 0–100 display index; higher = harder. */
  difficulty_score: number | null;
}

/** Rich venue profile from GET /api/venues/profile */
export interface VenueProfile extends VenueDetail {
  batting_innings: number;
  balls_faced_total: number;
  matches_in_slice: number;
  small_sample: boolean;
  vs_world: {
    avg_par_sr_percentile: number | null;
    boundary_rate_percentile: number | null;
    dot_pct_percentile: number | null;
    difficulty_percentile: number | null;
  };
  chase_defend: Record<string, number | null | undefined>;
  phases_batting: Record<
    string,
    {
      venue_sr?: number | null;
      format_mean_sr?: number | null;
      median_venue_sr?: number | null;
      vs_par_ratio_mean?: number | null;
    }
  >;
  phases_bowling: Record<string, unknown>;
}

export interface VenuePlayerAtVenue {
  id: string;
  name: string;
  country?: string;
  innings?: number;
  spells?: number;
  runs?: number;
  wickets?: number;
  balls_faced?: number;
  legal_balls?: number;
  sr?: number | null;
  avg?: number | null;
  economy?: number | null;
  strike_rate_bowl?: number | null;
  dot_pct?: number | null;
  boundary_pct?: number | null;
  six_rate?: number | null;
  last_played_at_venue?: string | null;
  career_sr?: number | null;
  career_avg?: number | null;
  career_economy?: number | null;
  career_sr_bowl?: number | null;
  career_dot_pct?: number | null;
  sr_delta?: number | null;
  avg_delta?: number | null;
  economy_delta?: number | null;
  strike_rate_delta?: number | null;
  dot_pct_delta?: number | null;
  boundary_pct_delta?: number | null;
  six_rate_delta?: number | null;
  overall_score?: number | null;
  overall_grade?: string;
  score_acceleration?: number | null;
  score_power?: number | null;
  score_control?: number | null;
  score_accuracy?: number | null;
  score_threat?: number | null;
  /** Mean per-innings / per-spell scores at this venue (when pipeline columns exist). */
  venue_overall_score?: number | null;
  venue_score_acceleration?: number | null;
  venue_score_power?: number | null;
  venue_score_control?: number | null;
  venue_score_accuracy?: number | null;
  venue_score_threat?: number | null;
}

// ── Venue Summary ────────────────────────────────────────────────

export interface VenueSummaryEntry {
  venue: string;
  matches: number;
  difficulty: number | null;
}

export interface DifficultyBucket {
  bin_low: number;
  bin_high: number;
  count: number;
}

export interface VenueSummary {
  total_venues: number;
  hardest_venue: VenueSummaryEntry | null;
  easiest_venue: VenueSummaryEntry | null;
  most_used_venue: VenueSummaryEntry | null;
  avg_difficulty: number | null;
  difficulty_distribution: DifficultyBucket[];
}

// ── Era Baseline ─────────────────────────────────────────────────

export interface EraBaseline {
  year: number;
  par_sr: number | null;
  boundary_rate: number | null;
  dot_pct: number | null;
  multiplier: number | null;
}

export interface EraResponse {
  baselines: EraBaseline[];
}

// ── Team Builder ─────────────────────────────────────────────────

export interface TeamAnalysis {
  player_count: number;
  batters: PlayerSummary[];
  bowlers: PlayerSummary[];
  avg_acceleration: number | null;
  avg_bat_power: number | null;
  avg_bat_control: number | null;
  avg_accuracy: number | null;
  avg_bowl_control: number | null;
  avg_threat: number | null;
  total_war_batting: number | null;
  total_war_bowling: number | null;
  avg_clutch: number | null;
  weaknesses: string[];
  composition_critical?: string[];
  composition_advisory?: string[];
  role_fit_warnings?: string[];
  composition_summary?: Record<string, boolean | string>;
  genuine_batter_count?: number;
  genuine_bowler_count?: number;
  bowling_aggregate_count?: number;
  /** XI order as analysed (for auto-fill slot alignment) */
  player_ids_ordered?: string[];
}

// ── Team vs Team Comparison ──────────────────────────────────────

export interface TeamComparison {
  batting_edge: "A" | "B" | "even";
  batting_diff: number;
  bowling_edge: "A" | "B" | "even";
  bowling_diff: number;
  war_edge: "A" | "B" | "even";
  war_diff: number;
  clutch_edge: "A" | "B" | "even";
}

export interface TeamCompareResponse {
  team_a: TeamAnalysis;
  team_b: TeamAnalysis;
  comparison: TeamComparison;
}

// ── Shared Matchup (for Compare page) ────────────────────────────

export interface SharedMatchupEntry {
  balls: number;
  runs: number;
  sr: number | null;
  dismissals: number;
  dots: number;
  fours: number;
  sixes: number;
  dot_pct: number | null;
  boundary_pct: number | null;
  dominance_index: number | null;
}

export interface SharedMatchup {
  bowler_id: string;
  bowler_name: string;
  matchups: Record<string, SharedMatchupEntry>;
}

export interface SharedMatchupsResponse {
  batter_ids: string[];
  shared: SharedMatchup[];
}

// ── Innings Log Response ─────────────────────────────────────────

export interface InningsLogResponse {
  innings: InningsDetail[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

// ── Spells Log Response ──────────────────────────────────────────

export interface SpellsLogResponse {
  spells: SpellDetail[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

// ── API Metadata ─────────────────────────────────────────────────

/** Latest match in scorecard JSON corpus for the active format (from /api/meta). */
export interface LatestScorecardSummary {
  match_id: string;
  date?: string | null;
  venue?: string | null;
  teams?: string[] | null;
  /** Cricsheet `info.event.name` when present (e.g. World Cup, bilateral series). */
  event_name?: string | null;
}

/** Paginated impact leaderboard from GET /api/scorecards/performances/by-impact. */
export interface MatchImpactPerformanceRow {
  match_id: string;
  date?: string | null;
  venue?: string | null;
  event_name?: string | null;
  teams?: string[] | null;
  player_id: string;
  player_name: string;
  total_impact: number;
  bat_impact: number;
  bowl_impact: number;
  bat_runs?: number | null;
  bat_balls?: number | null;
  bowl_wickets?: number | null;
  bowl_runs_conceded?: number | null;
  bowl_balls?: number | null;
}

export interface MatchImpactPerformancesResponse {
  performances: MatchImpactPerformanceRow[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface MatchImpactPerformancesParams {
  date_from?: string | null;
  date_to?: string | null;
  team?: string | null;
  event?: string | null;
  player_id?: string | null;
  /** T20I only (ignored for IPL). */
  match_tier?: "all" | "main_only" | "associate_fixture";
  discipline?: "combined" | "bat" | "bowl";
  order?: "asc" | "desc";
  page?: number;
  per_page?: number;
}

/** One match from GET /api/scorecards/player/{id}/match-impact (sorted best-first). */
export interface PlayerMatchImpactRow {
  match_id: string;
  date?: string | null;
  venue?: string | null;
  event_name?: string | null;
  /** Short team names from scorecard meta, when present (typically two sides). */
  teams?: string[] | null;
  total_impact: number;
  bat_impact: number;
  bowl_impact: number;
  bat_runs?: number | null;
  bat_balls?: number | null;
  bowl_wickets?: number | null;
  bowl_runs_conceded?: number | null;
  bowl_balls?: number | null;
}

/** ICC rating–based tiers for T20I filters (from config); null for IPL. */
export interface T20ITeamTiers {
  top_n: number;
  main: string[];
  associates: string[];
}

export interface ApiMeta {
  status: string;
  total_batters: number;
  total_bowlers: number;
  total_matchups: number;
  total_venues: number;
  countries: string[];
  archetypes: Record<string, string[]>;
  /** Latest career last_match_date across bat/bowl tables (yyyy-mm-dd). */
  data_through_date?: string | null;
  latest_scorecard?: LatestScorecardSummary | null;
  t20i_team_tiers?: T20ITeamTiers | null;
}

// ── Grade type (for type-safe grade handling) ────────────────────

export type Grade = "S" | "A+" | "A" | "B+" | "B" | "C+" | "C" | "D";

/**
 * Map a grade string from the API to a standardised Grade type.
 * Falls back to "D" for unrecognised values.
 */
export function parseGrade(raw: string | null | undefined): Grade {
  if (!raw) return "D";
  const normalised = raw.trim().toUpperCase();
  const gradeMap: Record<string, Grade> = {
    S: "S",
    "A+": "A+",
    A: "A",
    "B+": "B+",
    B: "B",
    "C+": "C+",
    C: "C",
    D: "D",
  };
  return gradeMap[normalised] ?? "D";
}

// ── Role type ────────────────────────────────────────────────────

export type Role = "bat" | "bowl";

// ── Sort order ───────────────────────────────────────────────────

export type SortOrder = "asc" | "desc";

// ── Search / filter parameters ───────────────────────────────────

export interface SearchParams {
  q?: string;
  role?: Role | null;
  country?: string | null;
  archetype?: string | null;
  provisional?: boolean | null;
  min_innings?: number | null;
  limit?: number;
}

export interface LeaderboardParams {
  sort?: string;
  order?: SortOrder;
  country?: string | null;
  archetype?: string | null;
  position_group?: string | null;
  /** Batting only: filter to players whose modal batting-order slot is 1–11 */
  modal_slot?: number | null;
  phase_group?: string | null;
  min_innings?: number | null;
  provisional?: boolean | null;
  /** active (default) | retired | all — recency window depends on format */
  activity?: "active" | "retired" | "all";
  page?: number;
  per_page?: number;
  /** Batting leaderboard: innings entry slice (API default none) */
  ctx_entry_phase?: "none" | "early" | "death";
  /** Batting: not yet supported server-side */
  ctx_knockouts_only?: boolean;
  /** Batting: not yet supported server-side */
  ctx_chase_high_rpo?: boolean;
}

export interface MatchupExploreParams {
  player_id: string;
  role?: Role;
  min_balls?: number;
  sort?: string;
  order?: SortOrder;
  page?: number;
  per_page?: number;
}

export interface VenueListParams {
  sort?: string;
  order?: SortOrder;
  min_matches?: number;
}

// ── ESPN live scoreboard (proxied; not tied to Cricsheet scorecards) ──

export interface EspnScoreboardCompetitorSummary {
  name: string;
  score_display: string;
}

export interface EspnEventSummary {
  event_id: string;
  name: string;
  short_name: string;
  status: string;
  state: string;
  competitors: EspnScoreboardCompetitorSummary[];
  /** One-line live scores for both sides, e.g. "RCB 120/4 · MI 118/8" */
  score_line?: string;
  /** ESPN series / competition name from the header feed */
  league_name?: string;
  /** One-line match state from ESPN (e.g. toss, session) */
  situation_short?: string;
  /** Longer situation line when available */
  situation_long?: string;
  /** Team currently batting when ESPN exposes battingTeamId */
  batting_team_name?: string;
  /** Latest matchnote-style update (not full commentary) */
  recent_note?: string;
  /** Link to ESPN match summary / scorecard */
  espn_url?: string;
  /** Numeric ESPN series/league id — required for in-app match summary */
  league_id?: string;
}

export interface EspnCricketScoreboardQuery {
  dates?: string | null;
  region?: string | null;
  lang?: string | null;
}

/** Wrapper from `GET /api/live/espn/cricket/scoreboard` */
export interface EspnCricketScoreboardResponse {
  enabled: boolean;
  league?: string;
  query?: EspnCricketScoreboardQuery;
  fetched_at?: string;
  served_from_cache?: boolean;
  refresh_interval_seconds?: number;
  payload?: unknown;
  events_summary?: EspnEventSummary[];
  upstream_http_status?: number | null;
  upstream_error?: string | null;
  message?: string | null;
}

/** Normalized rows from ESPN match summary (site v2) for in-app scorecard UI */
export interface EspnMatchNoteRow {
  type: string;
  text: string;
}

export interface EspnMatchDetailStatus {
  summary: string;
  display_clock: string;
  short_detail: string;
  detail: string;
  batting_team_id: string;
}

export interface EspnMatchDetailInnings {
  period: number | null;
  runs: number | null;
  wickets: number | null;
  overs: number | null;
  score: string;
  is_batting: boolean;
  description: string;
}

export interface EspnMatchDetailTeam {
  id: string;
  name: string;
  abbreviation: string;
  home_away: string;
  score: string;
  innings: EspnMatchDetailInnings[];
}

export interface EspnMatchFallOfWicket {
  team_score_runs: number | null;
  wicket_number: number | null;
  over: number | null;
  batter_out: string;
  team_name: string;
}

/** One ESPN ``matchcards`` block: batting, bowling, or partnerships for an innings */
export interface EspnMatchcardSection {
  kind: string;
  headline: string;
  team_name: string;
  innings_number: number | null;
  extras_summary?: string | null;
  total_line?: string | null;
  runs_summary?: string | null;
  rows: Record<string, string>[];
}

/** Single ball from ``competition.commentaries`` (newest first) */
export interface EspnRecentBall {
  short_text: string;
  summary: string;
  home_score: string;
  away_score: string;
  over_display: string;
}

export interface EspnCricketMatchDetail {
  title: string;
  short_title: string;
  venue: string | null;
  notes: EspnMatchNoteRow[];
  status: EspnMatchDetailStatus;
  teams: EspnMatchDetailTeam[];
  fall_of_wickets: EspnMatchFallOfWicket[];
  /** Batting / bowling / partnership tables from ESPN ``matchcards`` */
  matchcard_sections?: EspnMatchcardSection[];
  /** Ball-by-ball style lines from ``commentaries`` (newest first) */
  recent_balls?: EspnRecentBall[];
}

/** Wrapper from `GET /api/live/espn/cricket/summary` */
export interface EspnCricketMatchSummaryResponse {
  enabled: boolean;
  league_id: string;
  event_id: string;
  fetched_at?: string;
  served_from_cache?: boolean;
  refresh_interval_seconds?: number;
  detail: EspnCricketMatchDetail | null;
  upstream_http_status?: number | null;
  upstream_error?: string | null;
  message?: string | null;
}
