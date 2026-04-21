/**
 * Shared TypeScript shapes for scorecard JSON (API and simulated).
 */

export type BattingLine = {
  batter_id: string | null;
  batter: string | null;
  runs: number | null;
  balls: number | null;
  fours?: number | null;
  sixes?: number | null;
  strike_rate?: number | null;
  dismissal_kind?: string | null;
  dismissal_over?: number | null;
  dismissal_ball_idx?: number | null;
  dismissal_bowler?: string | null;
  dismissal_bowler_id?: string | null;
  dismissal_fielders?: string[] | null;
  batting_position?: number | null;
  per_phase_runs?: Record<string, number> | null;
  deliveries?: Array<{
    over?: number | null;
    ball_idx?: number | null;
    batter_runs?: number | null;
    team_score_before?: number | null;
    team_wickets_before?: number | null;
    total_runs?: number | null;
    is_wicket?: boolean | null;
    player_out_id?: string | null;
    bowler?: string | null;
    bowler_id?: string | null;
    wicket_fielders?: string[] | null;
    is_wide?: boolean | null;
    is_noball?: boolean | null;
    is_batter_ball?: boolean | null;
    phase?: string | null;
  }> | null;
};

export type BowlingDelivery = {
  over?: number | null;
  ball_idx?: number | null;
  batter?: string | null;
  batter_id?: string | null;
  batter_runs?: number | null;
  total_runs?: number | null;
  is_wide?: boolean | null;
  is_noball?: boolean | null;
  is_legal?: boolean | null;
  is_wicket?: boolean | null;
  wicket_kind?: string | null;
  player_out_id?: string | null;
  phase?: string | null;
  win_prob_before?: number | null;
  win_prob_after?: number | null;
  wpa?: number | null;
};

export type BowlingLine = {
  bowler_id: string | null;
  bowler: string | null;
  balls: number | null;
  overs?: string | null;
  runs_conceded?: number | null;
  wickets?: number | null;
  economy?: number | null;
  maidens?: number | null;
  deliveries?: BowlingDelivery[] | null;
};

export type TimelineBall = BowlingDelivery & {
  bowler_id: string | null;
  bowler: string | null;
};

export type Innings = {
  innings_num: number;
  batting_team?: string | null;
  bowling_team?: string | null;
  batting: BattingLine[];
  bowling: BowlingLine[];
  innings_total?: number | null;
  innings_wickets?: number | null;
  /** Chasing target (runs to win); set in 2nd innings when present in source data. */
  target_runs?: number | null;
};

export type Scorecard = {
  meta: {
    match_id: string;
    date?: string | null;
    venue?: string | null;
    event_name?: string | null;
    teams?: string[] | null;
    winner?: string | null;
    toss_winner?: string | null;
    toss_decision?: string | null;
    overs_limit?: number | null;
    dls_applied?: boolean | null;
  };
  innings: Record<string, Innings>;
};
