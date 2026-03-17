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
  difficulty_score: number | null;
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

// ── Flat Track Bully Entry ───────────────────────────────────────

export interface FlatTrackEntry {
  id: string;
  name: string;
  country: string;
  flat_track_index: number | null;
  innings_at_known_venues: number;
  avg_venue_difficulty_faced: number | null;
  overall_grade: string;
  archetype: string;
  interpretation: string;
  icon: string;
  // Optional score columns (depend on role)
  score_acceleration?: number | null;
  score_power?: number | null;
  score_control?: number | null;
  score_accuracy?: number | null;
  score_threat?: number | null;
}

export interface FlatTrackResponse {
  role: string;
  players: FlatTrackEntry[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
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
  genuine_batter_count?: number;
  genuine_bowler_count?: number;
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

export interface ApiMeta {
  status: string;
  total_batters: number;
  total_bowlers: number;
  total_matchups: number;
  total_venues: number;
  countries: string[];
  archetypes: Record<string, string[]>;
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
  phase_group?: string | null;
  min_innings?: number | null;
  provisional?: boolean | null;
  page?: number;
  per_page?: number;
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

export interface FlatTrackParams {
  role?: Role;
  min_innings?: number;
  provisional?: boolean | null;
  sort?: string;
  order?: SortOrder;
  page?: number;
  per_page?: number;
}
