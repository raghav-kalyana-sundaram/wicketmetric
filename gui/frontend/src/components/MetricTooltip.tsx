/**
 * MetricTooltip — hover/focus tooltip with metric explanations.
 *
 * Provides contextual help for any metric displayed in the UI.
 * When the user hovers over or focuses a metric label/value, a
 * tooltip appears with a plain-English explanation, interpretation
 * guide, and optional range/formula information.
 *
 * Features:
 *   - Automatic positioning (above/below/left/right) based on viewport
 *   - Keyboard accessible (shows on focus, hides on blur/Escape)
 *   - Configurable delay before showing (avoids accidental triggers)
 *   - Pre-built metric definitions for all Cricket Metrics scores
 *   - Custom content support for one-off tooltips
 *   - Light/dark mode support via Tailwind classes
 *   - Respects prefers-reduced-motion
 *   - Portal-free (positioned relative to trigger) for simplicity
 *
 * Usage:
 *   <MetricTooltip metric="acceleration">
 *     <span>Acceleration: 89.7</span>
 *   </MetricTooltip>
 *
 *   <MetricTooltip metric="war_batting" position="right">
 *     <span className="cursor-help underline decoration-dotted">WAR</span>
 *   </MetricTooltip>
 *
 *   <MetricTooltip content="Custom explanation text" title="My Metric">
 *     <span>Custom metric</span>
 *   </MetricTooltip>
 *
 *   <MetricTooltip metric="clutch_index" showRange>
 *     <InfoIcon size={14} />
 *   </MetricTooltip>
 *
 * Follows gui.md § 7.1 Component Library — `<MetricTooltip>`.
 */

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { Info } from "lucide-react";

/** localStorage key for "WAR tooltip seen" (Phase 2: first-use tooltip). */
export const WAR_FIRST_USE_STORAGE_KEY = "cricket_metrics_war_tooltip_seen";

export const WAR_METRIC_KEYS = new Set([
  "war_batting",
  "war_bowling",
  "war_batting_rate",
  "war_bowling_rate",
]);

// ── Metric definitions ───────────────────────────────────────────
// Pre-built explanations for all key metrics in the system.

export interface MetricDefinition {
  /** Display name of the metric. */
  name: string;
  /** Short plain-English description. */
  description: string;
  /** What constitutes a good vs bad value. */
  interpretation?: string;
  /** Numeric range description (e.g. "0–100", "-50 to +50"). */
  range?: string;
  /** What a high value means. */
  highMeaning?: string;
  /** What a low value means. */
  lowMeaning?: string;
  /** The category this metric belongs to. */
  category?: "batting" | "bowling" | "advanced" | "context" | "general";
  /** Text after the acronym in column header mini-cards, e.g. "Wins Above Replacement". */
  headerSubtitle?: string;
  /** 1–2 sentences: what a strong value looks like (header tooltip body). */
  goodGuide?: string;
  /** One-line simplified calculation / logic (muted footer). */
  calculationLine?: string;
}

export const METRIC_DEFINITIONS: Record<string, MetricDefinition> = {
  // ── Core batting metrics ─────────────────────────────────────
  acceleration: {
    name: "Acceleration",
    description:
      "Measures how quickly a batter scores relative to match conditions. Combines overall strike rate, SR growth through the innings, death-overs SR, and high-impact innings frequency.",
    interpretation:
      "Higher is better. Elite batters (A+/S grade) consistently score faster than the match par rate and accelerate through their innings.",
    range: "0–100",
    highMeaning: "Scores very fast, especially in the death overs",
    lowMeaning: "Below-par scoring rate for match conditions",
    category: "batting",
  },
  score_acceleration: {
    name: "Acceleration",
    description:
      "Measures how quickly a batter scores relative to match conditions. Combines overall strike rate, SR growth through the innings, death-overs SR, and high-impact innings frequency.",
    interpretation:
      "Higher is better. Elite batters consistently score faster than the match par rate.",
    range: "0–100",
    category: "batting",
    headerSubtitle: "Acceleration",
    goodGuide:
      "Higher is better. Top accelerators shift gears quickly—especially in the death—and routinely score above par for the match situation.",
    calculationLine:
      "Combines strike rate vs par, SR progression through the innings, death-over impact, and high-impact innings frequency (0–100 scale).",
  },
  power: {
    name: "Power",
    description:
      "Quantifies a batter's ability to hit boundaries. Combines boundary percentage, six-hitting rate, boundaries vs par, peak SR bursts, and burst scoring ability.",
    interpretation:
      "Higher is better. Power hitters (85+) clear the rope frequently and score in large chunks.",
    range: "0–100",
    highMeaning: "Frequent boundaries and sixes, high peak SR",
    lowMeaning: "Relies on rotation rather than boundaries",
    category: "batting",
  },
  score_power: {
    name: "Power",
    description:
      "Quantifies boundary-hitting ability. Combines boundary %, six rate, boundaries vs par, peak SR, and burst scoring.",
    interpretation:
      "Higher is better. Power hitters (roughly 80+) clear the rope often and score in large chunks; low scores usually mean rotation-first batters.",
    range: "0–100",
    category: "batting",
    headerSubtitle: "Power",
    goodGuide:
      "Higher is better. Look for players who combine a high boundary and six rate with strong peak scoring bursts versus par.",
    calculationLine:
      "Boundary percentage, six rate, boundaries vs expected, peak strike-rate bursts, and burst scoring consistency (0–100 scale).",
  },
  control: {
    name: "Control (Batting)",
    description:
      "Measures a batter's ability to manage their innings. Combines dot ball avoidance, strike rotation, runs contribution, batting average, and dismissal quality.",
    interpretation:
      "Higher is better. Controlled batters rarely get stuck, rotate strike well, and get out to good deliveries rather than loose shots.",
    range: "0–100",
    highMeaning: "Low dot %, good rotation, high average",
    lowMeaning: "Gets stuck frequently, poor shot selection",
    category: "batting",
  },
  score_control: {
    name: "Control",
    description:
      "Measures innings management: dot ball avoidance, rotation, runs contribution, average, and dismissal quality.",
    interpretation:
      "Higher is better. High-control batters (roughly 80+) avoid getting stuck, rotate well, and tend to fall to good balls rather than loose shots.",
    range: "0–100",
    category: "batting",
    headerSubtitle: "Control",
    goodGuide:
      "Higher is better. Strong values mean low dot-ball drag, reliable rotation, useful average, and dismissals that look like execution errors less often.",
    calculationLine:
      "Dot ball rate, strike rotation, runs contribution, batting average, and dismissal quality vs loose shots (0–100 scale).",
  },

  // ── Core bowling metrics ─────────────────────────────────────
  accuracy: {
    name: "Accuracy",
    description:
      "Measures a bowler's ability to restrict scoring. Combines economy rate vs par, dot ball percentage, and consistency of restricting boundaries.",
    interpretation:
      "Higher is better. Accurate bowlers consistently bowl dots and keep the economy below par for the venue/era.",
    range: "0–100",
    highMeaning: "Low economy, high dot ball %",
    lowMeaning: "Leaks runs frequently",
    category: "bowling",
  },
  score_accuracy: {
    name: "Accuracy",
    description:
      "Measures scoring restriction: economy vs par, dot ball %, and boundary prevention.",
    interpretation:
      "Higher is better. Accurate bowlers keep economy below par for the phase and build pressure with dots.",
    range: "0–100",
    category: "bowling",
    headerSubtitle: "Accuracy",
    goodGuide:
      "Higher is better. Strong values mean economy under par, healthy dot-ball share, and fewer boundary leaks.",
    calculationLine:
      "Economy vs expected, dot ball percentage, and boundary suppression vs par (0–100 scale).",
  },
  control_bowl: {
    name: "Control (Bowling)",
    description:
      "Measures a bowler's discipline and plan execution. Combines consistency of lengths, wide/no-ball rate, and phase-specific performance.",
    interpretation:
      "Higher is better. Controlled bowlers execute their plans consistently across different phases.",
    range: "0–100",
    category: "bowling",
    headerSubtitle: "Control (Bowling)",
    goodGuide:
      "Higher is better. Look for disciplined lengths, low extras, and plans that hold up across powerplay, middle, and death.",
    calculationLine:
      "Length consistency, wide/no-ball rate, and phase-specific execution vs par (0–100 scale).",
  },
  threat: {
    name: "Threat",
    description:
      "Measures a bowler's wicket-taking ability. Combines strike rate, quality of wickets (bowled/LBW %), top-order scalps, and pressure-building sequences.",
    interpretation:
      "Higher is better. Threatening bowlers take wickets regularly and break partnerships.",
    range: "0–100",
    highMeaning: "Frequent wickets, high bowled/LBW %",
    lowMeaning: "Rarely takes wickets",
    category: "bowling",
  },
  score_threat: {
    name: "Threat",
    description:
      "Wicket-taking ability: strike rate, wicket quality (bowled/LBW %), top-order scalps, and pressure sequences.",
    interpretation:
      "Higher is better. Threatening bowlers strike regularly, take quality wickets, and dent top orders.",
    range: "0–100",
    category: "bowling",
    headerSubtitle: "Threat",
    goodGuide:
      "Higher is better. Elite threats combine a strong strike rate with bowled/LBW-heavy wickets and big-moment breakthroughs.",
    calculationLine:
      "Strike rate, wicket quality, top-order impact, and pressure-over sequences (0–100 scale).",
  },

  // ── Advanced metrics ─────────────────────────────────────────
  war_batting: {
    name: "WAR (Batting)",
    description:
      "Wins Above Replacement — estimates how many additional wins a batter provides compared to a replacement-level player over their career. Built from run value, context adjustments (venue, era, opposition), and a replacement-level baseline.",
    interpretation:
      "Higher is better. A WAR of 3+ over a career is excellent. WAR accounts for innings count, so longevity matters.",
    range: "0+",
    highMeaning: "Significantly better than replacement level",
    lowMeaning: "Close to or below replacement level",
    category: "advanced",
    headerSubtitle: "Wins Above Replacement",
    goodGuide:
      "Higher is better. Career WAR around 3+ is excellent for batters; negative values sit below a replacement-level baseline.",
    calculationLine:
      "Batting run value vs a replacement-level batter, adjusted for venue, era, and opposition strength.",
  },
  war_bowling: {
    name: "WAR (Bowling)",
    description:
      "Wins Above Replacement for bowling — estimates additional wins provided compared to a replacement-level bowler. Built from wicket and run-restriction value, context adjustments, and a replacement-level baseline.",
    interpretation:
      "Higher is better. Bowlers accumulate WAR through consistent wicket-taking and run restriction.",
    range: "0+",
    category: "advanced",
    headerSubtitle: "Wins Above Replacement",
    goodGuide:
      "Higher is better. Elite careers add several wins above what an average domestic-standard bowler would produce in the same contexts.",
    calculationLine:
      "Wickets and economy vs par vs replacement-level bowling, with context adjustments.",
  },
  war_batting_rate: {
    name: "WAR Rate (Batting)",
    description:
      "WAR per 50 innings — normalises WAR by sample size to allow comparison between players with different career lengths.",
    interpretation:
      "Higher is better. Compares players fairly when one has many more innings than another.",
    range: "0+",
    category: "advanced",
    headerSubtitle: "Wins Above Replacement (per 50 innings)",
    goodGuide:
      "Higher is better. Use it to spot high-impact batters with shorter samples versus steady accumulators with long careers.",
    calculationLine:
      "Batting WAR expressed per 50 innings so sample size does not dominate the ranking.",
  },
  war_bowling_rate: {
    name: "WAR Rate (Bowling)",
    description: "WAR per 50 spells — normalises bowling WAR by sample size.",
    interpretation:
      "Higher is better. Normalises bowling WAR so you can compare different career lengths.",
    range: "0+",
    category: "advanced",
    headerSubtitle: "Wins Above Replacement (per 50 spells)",
    goodGuide:
      "Higher is better. Strong rates mean outsized win contribution per spell even before career volume stacks up.",
    calculationLine: "Bowling WAR scaled to a 50-spell equivalent.",
  },
  clutch_index: {
    name: "Pressure Score",
    description:
      "A 0-100 score for how much a player improves in high-pressure situations compared to their usual baseline.",
    interpretation:
      "Around 50 is neutral. Higher scores mean the player tends to raise their level in big moments; lower scores mean they usually dip.",
    range: "0–100",
    highMeaning: "Reliable or elite in high-pressure moments",
    lowMeaning: "Tends to underperform when pressure rises",
    category: "advanced",
  },
  clutch_index_bowl: {
    name: "Pressure Score (Bowling)",
    description:
      "A 0-100 score for how much a bowler improves in high-pressure spells compared to their baseline.",
    interpretation:
      "Around 50 is neutral. Higher scores mean the bowler gets better when the game tightens.",
    range: "0–100",
    category: "advanced",
  },
  chase_master_index: {
    name: "Chase Master Index",
    description:
      "Quantifies a batter's ability in successful run chases. Based on SR elevation, average in chases, and contributions to chase wins.",
    interpretation:
      "Higher is better. A score of 8+ indicates an elite chase specialist.",
    range: "0–15+",
    highMeaning: "Elite chase ability — controls innings 2 run chases",
    lowMeaning: "Struggles or has limited impact in chases",
    category: "advanced",
  },
  flat_track_index: {
    name: "Flat Track Index",
    description:
      "Measures how much a player's performance varies between easy and tough conditions. A negative or near-zero value means they perform consistently everywhere.",
    interpretation:
      "Near zero is ideal. A high positive value (flat-track bully) means the player primarily scores on easy pitches. Negative means they actually perform better in tough conditions.",
    range: "-5 to +5",
    highMeaning: 'Scores mostly on flat tracks — "flat-track bully"',
    lowMeaning: "Performs well across all conditions",
    category: "advanced",
  },
  flat_track_index_bowl: {
    name: "Flat Track Index (Bowling)",
    description:
      "Measures how much a bowler's performance varies between easy and tough conditions.",
    range: "-5 to +5",
    category: "advanced",
  },
  selfless_index: {
    name: "Selfless Index",
    description:
      "Measures how much a batter prioritises team outcomes over personal milestones. Based on SR acceleration when the team needs quick runs vs. when personal stats might suffer.",
    range: "0–10",
    category: "advanced",
  },
  venue_adjusted_composite: {
    name: "Venue-Adjusted Composite",
    description:
      "Overall composite rating adjusted for the difficulty of venues played at. Accounts for the fact that some players have played more at high-scoring grounds.",
    range: "0–100",
    category: "advanced",
  },
  anchor_cost_ratio: {
    name: "Anchor Cost Ratio",
    description:
      "For anchoring batters — the ratio of team benefit (stability, partnerships) to the scoring rate sacrifice compared to a more aggressive approach.",
    interpretation:
      "Higher is better. A high ratio means the anchor contributes more stability than they cost in scoring rate.",
    range: "0+",
    category: "advanced",
  },

  clutch_sr_delta: {
    name: "Pressure strike-rate delta",
    description:
      "How much a batter’s strike rate moves in high-pressure situations compared to their usual baseline.",
    interpretation:
      "Positive is better: the batter speeds up when it matters. Strongly negative values suggest pressure slows their scoring.",
    range: "Varies (SR points vs baseline)",
    category: "advanced",
    headerSubtitle: "SR change under pressure",
    goodGuide:
      "Look for positive deltas — the batter attacks when the game tightens — versus large negatives where tempo drops in big moments.",
    calculationLine: "Pressure-phase strike rate minus baseline strike rate, aggregated across qualifying innings.",
  },
  chase_master_full: {
    name: "Chase Master+",
    description:
      "Extended chase index: volume and outcomes in second-innings chases beyond the core Chase Master score.",
    interpretation:
      "Higher is better — rewards batters who are often in chases and lift their game when batting second to a target.",
    range: "0–15+",
    category: "advanced",
    headerSubtitle: "Extended chase impact",
    goodGuide:
      "Prefer players with high readings who repeatedly help finish chases, not one-off outliers.",
    calculationLine: "Builds on chase average, strike rate vs baseline when chasing, and contributions to successful chases.",
  },
  avg_balls_to_par: {
    name: "Balls to par",
    description:
      "Average balls needed to reach a modelled par contribution for the match situation — lower usually means quicker impact.",
    interpretation:
      "Lower is generally better: reaching par in fewer balls implies efficient scoring versus expectation.",
    range: "Context-dependent",
    category: "advanced",
    headerSubtitle: "Efficiency vs expected",
    goodGuide:
      "Lower numbers mean you reach par output for the phase and match state in fewer deliveries.",
    calculationLine: "Balls faced to reach expected run contribution for situation and opposition.",
  },
  avg_dominance: {
    name: "Average matchup edge (batting)",
    description:
      "Career-average 0–100 score for how often the batter has controlled ball-by-ball contests against bowlers faced.",
    interpretation:
      "Above 50 means the batter usually wins matchups on average; below 50 tilts toward bowlers.",
    range: "0–100",
    category: "advanced",
    headerSubtitle: "Matchup control (bat)",
    goodGuide:
      "Mid-50s+ suggests you generally get the better of the bowlers you’ve faced; mid-40s often means they edge you.",
    calculationLine: "Mean of matchup-win scores from SR vs expectation, dismissals, and pressure sequences.",
  },
  pct_dominant: {
    name: "% dominant innings",
    description:
      "Share of innings where the batter posted a clearly dominant matchup profile versus bowlers faced.",
    interpretation:
      "Higher is better — more innings where you controlled matchups rather than only surviving.",
    range: "0–100%",
    category: "advanced",
    headerSubtitle: "Share of dominant innings",
    goodGuide:
      "Elite batters show a high share of innings where they decisively won matchup battles, not just one big score.",
    calculationLine: "Fraction of innings classified as dominant under the batting matchup model.",
  },
  matchup_consistency: {
    name: "Matchup consistency",
    description:
      "How stable matchup performance is from innings to innings — less volatility implies more dependable outcomes.",
    interpretation:
      "Higher often means steadier matchup control; very low can indicate feast-or-famine.",
    range: "0–100",
    category: "advanced",
    headerSubtitle: "Innings-to-innings stability",
    goodGuide:
      "High scores mean your matchup edge doesn’t swing wildly between games — useful when picking reliable finishers or anchors.",
    calculationLine: "Inverse volatility of inning-level matchup edge scores.",
  },
  peak_composite_batting: {
    name: "Peak batting rating",
    description:
      "Best sustained composite batting score from the player’s career — a ceiling snapshot, not a longevity measure.",
    interpretation: "Higher is better — reflects how good your best stretch was on the model scale.",
    range: "0–100",
    category: "advanced",
    headerSubtitle: "Career peak composite",
    goodGuide:
      "Use to compare ceilings: two players with similar career ratings can differ sharply on how high their peak window reached.",
    calculationLine: "Maximum (or near-maximum) of rolling composite batting score over a qualifying window.",
  },
  peak_window_composite: {
    name: "Peak window composite",
    description:
      "Composite from the player’s strongest recent rolling window — how close current best form is to career peak.",
    interpretation: "Higher is better — strong values mean recent peaks still rival all-time personal highs.",
    range: "0–100",
    category: "advanced",
    headerSubtitle: "Recent peak window",
    goodGuide:
      "Compare with career peak: if this stays high, your best recent block is still near your historical ceiling.",
    calculationLine: "Best composite over a sliding recent-innings window.",
  },
  avg_dominance_bowl: {
    name: "Average matchup edge (bowling)",
    description:
      "Career-average 0–100 for how often the bowler has controlled contests against batters faced.",
    interpretation:
      "Above 50 means the bowler usually wins matchup battles on average; below 50 favours batters.",
    range: "0–100",
    category: "advanced",
    headerSubtitle: "Matchup control (bowl)",
    goodGuide:
      "Mid-50s+ suggests you usually suppress the batters you’ve bowled to; mid-40s means they often get on top.",
    calculationLine: "Mean of matchup scores from economy vs expectation, wickets, and pressure balls.",
  },
  pct_dominant_bowl: {
    name: "% dominant spells",
    description:
      "Share of spells classified as matchup-dominant (bowler controlled most contest balls).",
    interpretation: "Higher is better — more spells where you were the aggressor in head-to-head balls.",
    range: "0–100%",
    category: "advanced",
    headerSubtitle: "Share of dominant spells",
    goodGuide:
      "High values mean a large fraction of your spells are ones where you repeatedly win the ball-by-ball battle.",
    calculationLine: "Fraction of spells flagged dominant by the bowling matchup model.",
  },
  bowled_lbw_pct: {
    name: "Bowled / LBW share",
    description:
      "Percentage of wickets taken bowled or LBW — often signals attacking the stumps and beating the bat.",
    interpretation:
      "Higher shares often correlate with hitting the stumps (context- and role-dependent).",
    range: "0–100%",
    category: "bowling",
    headerSubtitle: "Stump-jarring wickets",
    goodGuide:
      "For similar wicket counts, a higher bowled/LBW share often means more wickets from beating the bat than from catches.",
    calculationLine: "(Bowled + LBW dismissals) ÷ total wickets.",
  },
  career_dot_pct: {
    name: "Career dot-ball %",
    description:
      "Percentage of balls bowled that were dots — higher generally means more pressure built without runs.",
    interpretation: "Higher is usually better for bowlers; compare within era and role.",
    range: "Roughly 25–55%",
    category: "bowling",
    headerSubtitle: "Dot-ball rate",
    goodGuide:
      "Among peers with similar economy, a higher dot share usually means you’re squeezing batters harder between boundaries.",
    calculationLine: "Career dots ÷ balls bowled.",
  },
  peak_composite_bowling: {
    name: "Peak bowling rating",
    description:
      "Best sustained composite bowling score from the player’s career — a ceiling snapshot.",
    interpretation: "Higher is better — reflects how good your best stretch was, not volume alone.",
    range: "0–100",
    category: "advanced",
    headerSubtitle: "Career peak composite",
    goodGuide:
      "Use to compare how devastating a bowler’s peak window was versus others, independent of career length.",
    calculationLine: "Maximum (or near-maximum) of rolling composite bowling score over a qualifying window.",
  },

  // ── Context adjustments ──────────────────────────────────────
  sr_vs_par: {
    name: "SR vs Par",
    description:
      "Strike rate relative to the match par rate. A value of 1.15 means the batter scored 15% faster than the median for that match/venue.",
    interpretation:
      "Above 1.0 is good. The match par accounts for venue, era, and conditions.",
    range: "0.5–2.0+",
    category: "context",
  },
  economy_vs_par: {
    name: "Economy vs Par",
    description:
      "Economy rate relative to the match par. A negative value means the bowler conceded fewer runs than par.",
    interpretation:
      "Negative is good (bowled better than par). Positive means more expensive than par.",
    range: "-5 to +5",
    category: "context",
  },
  dominance_index: {
    name: "Matchup Edge",
    description:
      "A 0-100 matchup score showing who usually controls a batter-vs-bowler contest.",
    interpretation:
      "Around 50 is even. Higher scores favour the batter, while lower scores favour the bowler.",
    range: "0–100",
    highMeaning: "The batter tends to control the matchup",
    lowMeaning: "The bowler tends to control the matchup",
    category: "context",
  },

  // ── General / derived ────────────────────────────────────────
  overall_score: {
    name: "Overall Score",
    description:
      "Weighted composite of all three dimension scores (e.g. Acceleration + Power + Control for batters). Includes a superstar bonus for players who excel across all dimensions.",
    range: "0–100",
    category: "general",
  },
  rating_current: {
    name: "Current rating",
    description:
      "Recent performance from the latest rolling form composite, capped so it never exceeds the player’s historical peak on that form track. With fewer than ~10 innings/spells, it matches the career display rating until the sample is large enough.",
    range: "0–100",
    category: "general",
  },
  rating_overall: {
    name: "Career overall (display)",
    description:
      "Career-style headline shown in expanded views: pipeline overall score capped by the maximum the player’s form composite has ever reached.",
    range: "0–100",
    category: "general",
  },
  overall_grade: {
    name: "Overall Grade",
    description:
      "Letter grade derived from the overall score. S (95–100) is elite, A+ (85–94) exceptional, down to D (0–14).",
    range: "D to S",
    category: "general",
  },
  career_sr: {
    name: "Career Strike Rate",
    description:
      "Runs scored per 100 balls faced across all T20I innings. A basic counting stat — the composite scores provide a more nuanced view.",
    interpretation:
      "Higher usually means more aggressive scoring; pair with average and role (opener vs finisher).",
    range: "80–200+",
    category: "general",
    headerSubtitle: "Strike rate",
    goodGuide:
      "Openers often run 130–150+ in T20; finishers can be higher with smaller samples. Context (era, format) matters.",
    calculationLine: "(Runs ÷ balls faced) × 100 across qualifying innings.",
  },
  career_avg: {
    name: "Career Average",
    description:
      "Runs per dismissal across all T20I innings. Higher is better, but in T20s a high average with a low SR can indicate overly cautious batting.",
    interpretation:
      "Higher is better for run volume per out, but a high average with a low strike rate can mean too few risks.",
    range: "10–60+",
    category: "general",
    headerSubtitle: "Batting average",
    goodGuide:
      "28+ at a healthy SR is strong in T20; very high average with sluggish SR often signals anchor-style trade-offs.",
    calculationLine: "Total runs ÷ dismissals in the dataset.",
  },
  career_economy: {
    name: "Career Economy",
    description:
      "Runs conceded per over across all T20I spells. Lower is better.",
    interpretation: "Lower is better — fewer runs per six balls on average.",
    range: "4–12+",
    category: "general",
    headerSubtitle: "Economy rate",
    goodGuide:
      "Under ~7.5 in high-scoring leagues is often strong; death specialists may accept higher economy for wickets.",
    calculationLine: "Runs conceded ÷ overs bowled.",
  },
  innings_count: {
    name: "Innings",
    description:
      "Total number of batting innings played in T20Is. Used to determine provisional status and as a weighting factor in several metrics.",
    interpretation: "More innings usually means more reliable ratings; low counts can be noisy or provisional.",
    range: "1+",
    category: "general",
    headerSubtitle: "Innings played",
    goodGuide:
      "Use alongside ratings: very few innings can make composites volatile until the sample grows.",
    calculationLine: "Count of completed batting innings in the selected format and filters.",
  },
  is_provisional: {
    name: "Provisional Status",
    description:
      "Players with fewer than the minimum innings threshold (typically 10) are marked as provisional. Their ratings may change significantly with more data.",
    category: "general",
  },
  multiplier: {
    name: "Era Multiplier",
    description:
      "Adjustment factor for different eras of T20I cricket. A multiplier of 1.28 means performances from that year are worth 28% more than equivalent raw numbers in the most recent year.",
    interpretation:
      "Earlier eras had lower scoring rates, so the multiplier compensates for this when comparing across eras.",
    range: "0.9–1.5+",
    category: "context",
  },
  par_sr: {
    name: "Par Strike Rate",
    description:
      "The median strike rate for a given year, representing the typical scoring rate of the era. Used as a baseline for SR vs Par calculations.",
    range: "100–160+",
    category: "context",
  },
  boundary_rate: {
    name: "Boundary Rate",
    description:
      "Percentage of balls that resulted in a boundary (four or six). Shows how boundary-dependent scoring is in a given era or venue.",
    range: "5–25%",
    category: "context",
  },
  dot_pct: {
    name: "Dot Ball %",
    description:
      "Percentage of balls faced/bowled that resulted in zero runs. For batters, lower is better; for bowlers, higher is better.",
    range: "20–50%",
    category: "general",
  },
  similarity_score: {
    name: "Similarity Score",
    description:
      "Cosine similarity between two players' metric profiles. 1.0 means identical profiles, 0.0 means completely different.",
    range: "0.0–1.0",
    highMeaning: "Very similar statistical profile",
    lowMeaning: "Very different statistical profile",
    category: "general",
  },

  // ── Leaderboard column helpers (Rankings table headers) ────────
  leaderboard_rank: {
    name: "Rank",
    description: "Position on the current leaderboard page after filters and sort order.",
    interpretation: "Updates when you change sort, filters, or pagination — it is not a career award ranking by itself.",
    category: "general",
    headerSubtitle: "Leaderboard position",
    goodGuide:
      "Shows where this row sits on this view only; use filters to compare apples-to-apples cohorts.",
    calculationLine: "Index in the sorted result set for the current page.",
  },
  leaderboard_player: {
    name: "Player",
    description: "Player name for the row. Provisional markers indicate smaller sample sizes.",
    category: "general",
    headerSubtitle: "Player identity",
    goodGuide: "Click the row or chevron to open a fuller profile; provisional tags mean ratings are still stabilising.",
    calculationLine: "Display name from the roster; sample flags come from innings/spell thresholds.",
  },
  leaderboard_team: {
    name: "Team / country",
    description: "Recent franchise or primary team label with country — space-efficient in dense tables.",
    interpretation: "Abbreviation keeps columns narrow; hover or profile has full detail when available.",
    category: "general",
    headerSubtitle: "Squad hint",
    goodGuide:
      "Use as a quick geographic or franchise cue — not all leagues encode franchise the same way.",
    calculationLine: "Derived from recent team string and country code.",
  },
  leaderboard_archetype: {
    name: "Archetype",
    description:
      "Model-assigned playing style label (e.g. power hitter, anchor) summarising metric balance.",
    category: "general",
    headerSubtitle: "Style bucket",
    goodGuide:
      "Helpful for filtering similar profiles; edge cases can sit between two archetypes.",
    calculationLine: "Cluster or rule label from composite score geometry and role priors.",
  },
  leaderboard_form_trend: {
    name: "Form trend",
    description:
      "Direction of recent rolling composite scores from the form track (last several meaningful samples).",
    interpretation:
      "Up means the latest composites are higher than ~10 samples ago; down means lower; flat is within a small band. A dash means not enough rolling points yet.",
    category: "general",
    headerSubtitle: "Recent trajectory",
    goodGuide:
      "Needs enough recent form points (~10); sparse careers may show “insufficient” until data accumulates.",
    calculationLine: "Compare latest composite to value ten form steps prior on the same track.",
  },
  leaderboard_compare: {
    name: "Compare",
    description: "Select up to four players, then use Compare to open a side-by-side stat view.",
    category: "general",
    headerSubtitle: "Selection",
    goodGuide: "Tick boxes for any players you want in the comparison tray — row click still opens the preview panel.",
    calculationLine: "Client-side selection only; does not change sort or filters.",
  },
  leaderboard_open_profile: {
    name: "Profile",
    description: "Shortcut to this player’s full analytics profile page.",
    category: "general",
    headerSubtitle: "Navigate",
    goodGuide: "Opens the detailed breakdown: charts, logs, and matchup views where available.",
    calculationLine: "Client route to the player ID.",
  },
  leaderboard_ratings_column: {
    name: "Display ratings",
    description:
      "Current (Cur) is recent rolling-form composite (capped by your peak on that track). Overall (Ovl) is the career-style display rating capped by the best the form composite has ever reached.",
    interpretation:
      "Use Cur to spot who is hot now; use Ovl for the headline career number. Sort via the Cur / Ovl buttons in this header.",
    category: "general",
    headerSubtitle: "Cur vs Ovl",
    goodGuide:
      "Both are 0–100 style display scores with form caps — not raw pipeline sums.",
    calculationLine: "See rating_current and rating_overall tooltips for full formulas.",
  },
  leaderboard_batting_innings: {
    name: "Innings (batting)",
    description: "Count of qualifying batting innings in the active dataset and format filters.",
    category: "general",
    headerSubtitle: "Innings",
    goodGuide: "Higher counts stabilise ratings; min-innings filters trim low-sample players.",
    calculationLine: "Number of batting innings included after format and activity filters.",
  },
  total_runs_batting: {
    name: "Career runs",
    description: "Total runs scored across those qualifying batting innings.",
    interpretation: "Higher is more volume — read with strike rate and role.",
    range: "0+",
    category: "general",
    headerSubtitle: "Runs",
    goodGuide: "Big totals with strong SR matter more than the same runs at a crawl.",
    calculationLine: "Sum of runs in counted innings.",
  },
  leaderboard_bowling_matches: {
    name: "Matches / spells",
    description: "Count of qualifying bowling spells (or appearances) under current filters.",
    category: "general",
    headerSubtitle: "Appearances",
    goodGuide: "Same idea as batting innings: more spells make model scores less noisy.",
    calculationLine: "Spell count after format and activity filters.",
  },
  bowling_career_wickets: {
    name: "Wickets",
    description: "Total wickets in qualifying spells — the same field as batting runs, presented for bowlers.",
    interpretation: "Higher is more volume; pair with economy and strike rate.",
    range: "0+",
    category: "general",
    headerSubtitle: "Wickets",
    goodGuide: "Wicket mass with poor economy can mean high-risk plans; elite lines balance both.",
    calculationLine: "Sum of dismissals credited in counted spells.",
  },
  leaderboard_bowling_economy: {
    name: "Economy (leaderboard)",
    description:
      "Runs conceded per over — the column sorts by the same career economy field used in profiles.",
    interpretation: "Lower is better; phase role (powerplay vs death) moves acceptable bands.",
    range: "4–12+",
    category: "general",
    headerSubtitle: "Economy",
    goodGuide: "Sub-8 in high-scoring contexts is often elite; compare peers in the same era bucket.",
    calculationLine: "Runs given ÷ overs bowled, career aggregate.",
  },
  leaderboard_bowling_strike_rate: {
    name: "Bowling strike rate",
    description: "Balls bowled per wicket on average — lower means wickets come more often.",
    interpretation: "Lower is better: fewer balls per dismissal.",
    range: "roughly 12–40 balls/wkt",
    category: "general",
    headerSubtitle: "Strike rate",
    goodGuide: "Match wicket-takers might sit in the teens; containing bowlers can be higher with good economy.",
    calculationLine: "Balls bowled ÷ wickets in the dataset.",
  },
};

// ── Tooltip positioning ──────────────────────────────────────────

type TooltipPosition = "above" | "below" | "left" | "right" | "auto";

// ── Props ────────────────────────────────────────────────────────

interface MetricTooltipProps {
  /** The metric key to look up in the definitions. */
  metric?: string;
  /** Custom title override (instead of the metric definition name). */
  title?: string;
  /** Custom content override (instead of the metric definition). */
  content?: string;
  /** Whether to show the range info. Default: false. */
  showRange?: boolean;
  /** Whether to show the interpretation guide. Default: true (if available). */
  showInterpretation?: boolean;
  /** Tooltip position preference. Default: "auto". */
  position?: TooltipPosition;
  /** Delay in ms before showing the tooltip. Default: 300. */
  delay?: number;
  /** Max width of the tooltip in pixels. Default: 280. */
  maxWidth?: number;
  /** The trigger element(s). */
  children: ReactNode;
  /** Additional CSS classes for the trigger wrapper. */
  className?: string;
  /** Whether the trigger element should show a help cursor. Default: true. */
  helpCursor?: boolean;
  /** Whether to add a subtle dotted underline to the trigger. Default: false. */
  underline?: boolean;
  /**
   * Render mode:
   * - "wrap" (default): wraps children in a span with tooltip
   * - "icon": renders a small info icon next to children, tooltip on the icon
   */
  mode?: "wrap" | "icon";
  /** Size of the info icon (when mode="icon"). Default: 14. */
  iconSize?: number;
  /** Whether the tooltip is disabled. Default: false. */
  disabled?: boolean;
}

// ── Component ────────────────────────────────────────────────────

export default function MetricTooltip({
  metric,
  title: titleProp,
  content: contentProp,
  showRange = false,
  showInterpretation = true,
  position = "auto",
  delay = 300,
  maxWidth = 280,
  children,
  className = "",
  helpCursor = true,
  underline = false,
  mode = "wrap",
  iconSize = 14,
  disabled = false,
}: MetricTooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [resolvedPosition, setResolvedPosition] = useState<
    "above" | "below" | "left" | "right"
  >("above");
  const [warFirstUseSeen, setWarFirstUseSeen] = useState(
    () =>
      typeof window !== "undefined" &&
      !!localStorage.getItem(WAR_FIRST_USE_STORAGE_KEY),
  );
  const triggerRef = useRef<HTMLSpanElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isWarMetric = metric != null && WAR_METRIC_KEYS.has(metric);
  const showWarFirstUseFooter =
    isVisible && isWarMetric && !warFirstUseSeen;

  // Look up the metric definition
  const definition = metric ? METRIC_DEFINITIONS[metric] : undefined;

  // Resolve the display content
  const tooltipTitle = titleProp ?? definition?.name;
  const tooltipContent = contentProp ?? definition?.description;
  const tooltipInterpretation =
    showInterpretation && definition?.interpretation
      ? definition.interpretation
      : undefined;
  const tooltipRange =
    showRange && definition?.range ? definition.range : undefined;
  const tooltipHigh = showRange ? definition?.highMeaning : undefined;
  const tooltipLow = showRange ? definition?.lowMeaning : undefined;

  // If there's nothing to show, just render children
  const hasContent = !disabled && (tooltipContent || tooltipTitle);

  // Auto-position based on trigger location in viewport
  const resolvePosition = useCallback(() => {
    if (position !== "auto") {
      setResolvedPosition(position);
      return;
    }

    if (!triggerRef.current) {
      setResolvedPosition("above");
      return;
    }

    const rect = triggerRef.current.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;

    const spaceAbove = rect.top;
    const spaceBelow = viewportHeight - rect.bottom;
    const spaceLeft = rect.left;
    const spaceRight = viewportWidth - rect.right;

    // Prefer above, then below, then right, then left
    if (spaceAbove > 100) {
      setResolvedPosition("above");
    } else if (spaceBelow > 100) {
      setResolvedPosition("below");
    } else if (spaceRight > maxWidth + 20) {
      setResolvedPosition("right");
    } else if (spaceLeft > maxWidth + 20) {
      setResolvedPosition("left");
    } else {
      // Fallback: whichever vertical direction has more room
      setResolvedPosition(spaceAbove >= spaceBelow ? "above" : "below");
    }
  }, [position, maxWidth]);

  // Show tooltip
  const show = useCallback(() => {
    if (!hasContent) return;
    timeoutRef.current = setTimeout(() => {
      resolvePosition();
      setIsVisible(true);
    }, delay);
  }, [hasContent, delay, resolvePosition]);

  // Hide tooltip
  const hide = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setIsVisible(false);
  }, []);

  const handleWarFirstUseAck = useCallback(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem(WAR_FIRST_USE_STORAGE_KEY, "1");
    }
    setWarFirstUseSeen(true);
    hide();
  }, [hide]);

  // Hide on Escape key
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        hide();
      }
    },
    [hide],
  );

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  // Position classes for the tooltip
  const positionClasses = {
    above: "bottom-full mb-2 left-1/2 -translate-x-1/2",
    below: "top-full mt-2 left-1/2 -translate-x-1/2",
    left: "right-full mr-2 top-1/2 -translate-y-1/2",
    right: "left-full ml-2 top-1/2 -translate-y-1/2",
  };

  // Arrow classes
  const arrowClasses = {
    above: "top-full left-1/2 -translate-x-1/2 -mt-[3px] border-t border-l",
    below: "bottom-full left-1/2 -translate-x-1/2 -mb-[3px] border-b border-r",
    left: "left-full top-1/2 -translate-y-1/2 -ml-[3px] border-t border-r",
    right: "right-full top-1/2 -translate-y-1/2 -mr-[3px] border-b border-l",
  };

  const tooltipElement = hasContent && isVisible && (
    <span
      className={[
        "absolute z-50 rounded-lg px-3 py-2.5",
        showWarFirstUseFooter ? "pointer-events-auto" : "pointer-events-none",
        "border border-surface-elevated/80 bg-surface-elevated text-text-primary shadow-lg",
        "dark:border-white/15 dark:bg-surface dark:shadow-xl dark:backdrop-blur-none",
        "text-xs leading-relaxed font-normal",
        "animate-fade-in",
        positionClasses[resolvedPosition],
      ].join(" ")}
      style={{ maxWidth: `${maxWidth}px`, width: "max-content" }}
      role="tooltip"
    >
      {/* Title */}
      {tooltipTitle && (
        <span className="mb-1 block font-semibold text-text-primary dark:text-white">
          {tooltipTitle}
          {tooltipRange && (
            <span className="font-normal text-text-muted ml-1">
              ({tooltipRange})
            </span>
          )}
        </span>
      )}

      {/* Main description */}
      {tooltipContent && (
        <span className="block text-text-secondary leading-relaxed">
          {tooltipContent}
        </span>
      )}

      {/* Interpretation */}
      {tooltipInterpretation && (
        <span className="block text-text-muted mt-1.5 leading-relaxed italic">
          {tooltipInterpretation}
        </span>
      )}

      {/* High / Low meaning */}
      {(tooltipHigh || tooltipLow) && (
        <span className="block mt-1.5 space-y-0.5">
          {tooltipHigh && (
            <span className="flex items-center gap-1 text-[10px] text-text-muted">
              <span className="text-text-secondary" aria-hidden>
                ▲
              </span>
              <span>{tooltipHigh}</span>
            </span>
          )}
          {tooltipLow && (
            <span className="flex items-center gap-1 text-[10px] text-text-muted">
              <span className="text-text-secondary" aria-hidden>
                ▼
              </span>
              <span>{tooltipLow}</span>
            </span>
          )}
        </span>
      )}

      {/* WAR first-use footer (Phase 2) */}
      {showWarFirstUseFooter && (
        <span className="mt-2 flex flex-wrap items-center gap-2 border-t border-surface-elevated/80 pt-2 dark:border-white/10">
          <span className="text-text-muted text-[11px]">First time here?</span>
          <Link
            to="/glossary#advanced"
            className="text-primary hover:text-primary-hover text-[11px] font-medium"
            onClick={handleWarFirstUseAck}
          >
            Glossary
          </Link>
          <button
            type="button"
            onClick={handleWarFirstUseAck}
            className="text-[11px] font-medium px-2 py-0.5 rounded bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
          >
            Got it
          </button>
        </span>
      )}

      {/* Arrow */}
      <span
        className={[
          "absolute h-2 w-2 rotate-45",
          "border-surface-elevated/80 bg-surface-elevated",
          "dark:border-white/15 dark:bg-surface",
          arrowClasses[resolvedPosition],
        ].join(" ")}
        aria-hidden="true"
      />
    </span>
  );

  // ── Render: icon mode ──────────────────────────────────────

  if (mode === "icon") {
    return (
      <span className={`inline-flex items-center gap-1 ${className}`}>
        {children}
        {hasContent && (
          <span
            ref={triggerRef}
            className="relative inline-flex cursor-help text-text-muted hover:text-text-secondary transition-colors"
            onMouseEnter={show}
            onMouseLeave={hide}
            onFocus={show}
            onBlur={hide}
            onKeyDown={handleKeyDown}
            tabIndex={0}
            aria-describedby={isVisible ? "metric-tooltip" : undefined}
          >
            <Info size={iconSize} aria-hidden="true" />
            {tooltipElement}
          </span>
        )}
      </span>
    );
  }

  // ── Render: wrap mode (default) ────────────────────────────

  if (!hasContent) {
    return <>{children}</>;
  }

  return (
    <span
      ref={triggerRef}
      className={[
        "relative inline-flex items-center",
        helpCursor ? "cursor-help" : "",
        underline
          ? "underline decoration-dotted decoration-text-muted underline-offset-2"
          : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      aria-describedby={isVisible ? "metric-tooltip" : undefined}
    >
      {children}
      {tooltipElement}
    </span>
  );
}

// ── Variant: MetricInfoIcon ──────────────────────────────────────
// Standalone info icon with tooltip — for placing next to metric labels.
// More semantic alternative to <MetricTooltip mode="icon">.

interface MetricInfoIconProps {
  /** The metric key to look up. */
  metric?: string;
  /** Custom title. */
  title?: string;
  /** Custom content. */
  content?: string;
  /** Icon size. Default: 14. */
  size?: number;
  /** Whether to show range info. Default: false. */
  showRange?: boolean;
  /** Additional classes. */
  className?: string;
}

export function MetricInfoIcon({
  metric,
  title,
  content,
  size = 14,
  showRange = false,
  className = "",
}: MetricInfoIconProps) {
  return (
    <MetricTooltip
      metric={metric}
      title={title}
      content={content}
      showRange={showRange}
      mode="wrap"
      className={`inline-flex cursor-help text-text-muted hover:text-text-secondary transition-colors ${className}`}
    >
      <Info size={size} aria-hidden="true" />
    </MetricTooltip>
  );
}

// ── Variant: MetricLabel ─────────────────────────────────────────
// A metric label with a built-in tooltip. Combines the label text
// with tooltip functionality so you don't need to wrap manually.

interface MetricLabelProps {
  /** The metric key. */
  metric: string;
  /** Override the displayed label text. If not set, uses the metric definition name. */
  label?: string;
  /** Text size class. Default: "text-sm". */
  textSize?: string;
  /** Whether to show an info icon after the label. Default: true. */
  showIcon?: boolean;
  /** Icon size. Default: 12. */
  iconSize?: number;
  /** Whether to show range info in the tooltip. Default: false. */
  showRange?: boolean;
  /** Additional classes. */
  className?: string;
}

export function MetricLabel({
  metric,
  label,
  textSize = "text-sm",
  showIcon = true,
  iconSize = 12,
  showRange = false,
  className = "",
}: MetricLabelProps) {
  const definition = METRIC_DEFINITIONS[metric];
  const displayLabel = label ?? definition?.name ?? metric;

  return (
    <MetricTooltip metric={metric} showRange={showRange} mode="wrap">
      <span
        className={`inline-flex items-center gap-1 text-text-secondary ${textSize} ${className}`}
      >
        <span>{displayLabel}</span>
        {showIcon && (
          <Info
            size={iconSize}
            className="text-text-muted opacity-60"
            aria-hidden="true"
          />
        )}
      </span>
    </MetricTooltip>
  );
}
