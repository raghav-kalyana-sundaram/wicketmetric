/**
 * Glossary & Methodology — comprehensive reference page.
 *
 * Route: /glossary
 *
 * Features (from gui.md § 6.11):
 *   1. Core Batting Metrics — Acceleration, Power, Control (with sub-component breakdowns)
 *   2. Core Bowling Metrics — Accuracy, Control, Threat (with sub-component breakdowns)
 *   3. Rating System — Bayesian shrinkage, percentile mapping, confidence bonus
 *   4. Advanced Metrics — WAR, Clutch Index, Chase Master Index, WPA, Flat Track Index
 *   5. Context Adjustments — Opposition quality, team quality, match quality, recency, era
 *   6. Grades & Archetypes — Grade boundaries, archetype definitions
 *   7. Similarity — Cosine similarity methodology
 *   8. FAQ — Common questions
 *
 * Each metric entry includes:
 *   - Plain-English definition
 *   - Interpretation guide (what's good, what's bad)
 *   - Example usage
 *
 * This page is entirely static content — no data fetching required.
 */

import { useState, useMemo, useCallback, useEffect } from "react";
import { useLocation } from "react-router-dom";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  Search,
  Zap,
  Target,
  BarChart3,
  Activity,
  HelpCircle,
  Hash,
  Award,
  Layers,
  GitCompare,
  Info,
  ArrowUp,
} from "lucide-react";

import GradeBadge from "@/components/GradeBadge";
import ScoreBar from "@/components/ScoreBar";
import { SCORE_BANDS } from "@/lib/colours";

// ── Types ────────────────────────────────────────────────────────

interface MetricDefinition {
  name: string;
  shortName?: string;
  description: string;
  interpretation?: string;
  components?: { name: string; description: string }[];
  formula?: string;
  range?: string;
  goodValue?: string;
  badValue?: string;
}

interface SectionDef {
  id: string;
  title: string;
  icon: React.ReactNode;
  description?: string;
  metrics?: MetricDefinition[];
  content?: React.ReactNode;
}

interface FAQItem {
  question: string;
  answer: string;
}

// ── Data ─────────────────────────────────────────────────────────

const BATTING_METRICS: MetricDefinition[] = [
  {
    name: "Acceleration Score",
    shortName: "ACC",
    description:
      "Measures a batter's ability to increase the scoring rate over an innings. Captures how quickly a player transitions from settling in to dominating the bowling, reflecting strike rate progression, boundary escalation, and run-rate impact.",
    interpretation:
      "Higher is better. Elite accelerators (A+ / S grade) can shift gears quickly, turning a steady start into a match-winning assault. Players with low acceleration may struggle to lift the tempo in the death overs.",
    components: [
      {
        name: "Strike Rate vs Par",
        description:
          "How much the batter's strike rate exceeds the expected par rate for the match conditions, phase, and opposition quality.",
      },
      {
        name: "Impact Score",
        description:
          "Measures the magnitude of a batter's scoring contributions weighted by match context (WPA-adjusted).",
      },
      {
        name: "Boundary Percentage",
        description:
          "Proportion of runs scored from boundaries (fours and sixes). Higher boundary % indicates more aggressive, high-impact scoring.",
      },
    ],
    range: "0–100",
    goodValue: "80+ (A or above)",
    badValue: "Below 30 (C or below)",
  },
  {
    name: "Power Score",
    shortName: "POW",
    description:
      "Quantifies a batter's raw hitting ability — the capacity to clear boundaries and score through brute force. Heavily weighted towards six-hitting rate, boundary frequency in the death overs, and maximum distances.",
    interpretation:
      "Higher is better. Power hitters (80+) can change games in a few deliveries. Low power scores are common among anchor-type players who rely on placement and rotation rather than big hits.",
    components: [
      {
        name: "Six Rate",
        description:
          "Number of sixes hit per 100 balls faced. The primary indicator of raw power.",
      },
      {
        name: "Dot Ball Control (inverted)",
        description:
          "Lower dot ball percentage when attacking. Power hitters who also avoid dots score higher.",
      },
      {
        name: "Consistency",
        description:
          "Standard deviation of innings-to-innings scoring rate — lower variance among big-hitting attempts is rewarded.",
      },
    ],
    range: "0–100",
    goodValue: "75+ (A or above)",
    badValue: "Below 25 (C or below)",
  },
  {
    name: "Control Score",
    shortName: "CTL",
    description:
      "Assesses a batter's ability to manage risk, rotate strike, and maintain consistency. Captures dot ball avoidance, strike rotation effectiveness, and the ability to adapt to different match situations.",
    interpretation:
      "Higher is better. High-control players (80+) rarely get stuck, rotate strike efficiently, and provide stability to the innings. They may not always have the highest strike rate but their consistency and low dot percentage make them invaluable.",
    components: [
      {
        name: "Rotation Efficiency",
        description:
          "Ability to score 1s and 2s and keep the scoreboard ticking between boundaries.",
      },
      {
        name: "Average Runs per Innings",
        description:
          "Consistency of scoring contributions — players who regularly post useful scores rank higher.",
      },
      {
        name: "Average Strike Rate",
        description:
          "Career strike rate adjusted for era and conditions, ensuring baseline scoring ability.",
      },
    ],
    range: "0–100",
    goodValue: "80+ (A or above)",
    badValue: "Below 30 (C or below)",
  },
];

const BOWLING_METRICS: MetricDefinition[] = [
  {
    name: "Accuracy Score",
    shortName: "ACC",
    description:
      "Measures a bowler's ability to hit good lengths and control the scoring rate. Captures economy rate vs par, dot ball generation, and consistency of line and length.",
    interpretation:
      "Higher is better. Accurate bowlers (80+) consistently build pressure by bowling dots, hitting yorkers, and varying pace effectively. Low accuracy bowlers leak runs and struggle to maintain economy.",
    components: [
      {
        name: "Economy vs Par",
        description:
          "How much cheaper the bowler is compared to the expected par economy for the conditions, phase, and opposition.",
      },
      {
        name: "Dot Ball Percentage",
        description:
          "Proportion of deliveries where no runs are scored. Higher dot % = more pressure.",
      },
    ],
    range: "0–100",
    goodValue: "75+ (A or above)",
    badValue: "Below 30 (C or below)",
  },
  {
    name: "Control Score",
    shortName: "CTL",
    description:
      "Measures a bowler's consistency, economy under pressure, and ability to restrict scoring across all phases. Captures wide/no-ball avoidance, economy in death overs, and variation effectiveness.",
    interpretation:
      "Higher is better. High-control bowlers (80+) rarely give away freebies and can be trusted in any phase. They maintain composure under pressure and adapt their plans mid-over.",
    components: [
      {
        name: "Wickets per Spell",
        description:
          "Average number of wickets taken per bowling spell. Consistent wicket-taking ability.",
      },
      {
        name: "Economy vs Par (sustained)",
        description:
          "Economy rate compared to par over multiple-spell averages — rewards sustained performance.",
      },
    ],
    range: "0–100",
    goodValue: "75+ (A or above)",
    badValue: "Below 30 (C or below)",
  },
  {
    name: "Threat Score",
    shortName: "THR",
    description:
      "Quantifies a bowler's wicket-taking ability and attacking prowess. Captures strike rate, quality wickets (top-order/set batters), bowled/LBW %, and ability to break partnerships.",
    interpretation:
      "Higher is better. High-threat bowlers (80+) are genuine wicket-takers who can change the game. They get the big wickets and take them in clusters. Low threat bowlers are containing-only.",
    components: [
      {
        name: "Quality Wickets",
        description:
          "Proportion of wickets that are high-value — dismissing top-order or well-set batters counts for more.",
      },
      {
        name: "Threat-Pressure Composite",
        description:
          "Combined metric of wicket-taking frequency and pressure building (dot clusters before wickets).",
      },
    ],
    range: "0–100",
    goodValue: "75+ (A or above)",
    badValue: "Below 30 (C or below)",
  },
];

const ADVANCED_METRICS: MetricDefinition[] = [
  {
    name: "Wins Above Replacement (WAR)",
    shortName: "WAR",
    description:
      "Estimates how many additional wins a player contributes compared to a replacement-level player (i.e., an average domestic-level player). Combines batting/bowling value, adjusts for context, and normalises to a per-match rate.",
    interpretation:
      "Higher is better. Elite players (5+ career WAR) have contributed multiple extra wins to their team over their career. A WAR of 0 means the player is performing at replacement level.",
    range: "-5 to 10+",
    goodValue: "3+ career, 0.15+ per match",
    badValue: "Negative WAR suggests below replacement level",
  },
  {
    name: "Clutch Index",
    shortName: "CLT",
    description:
      "Measures how much a player's performance improves (or deteriorates) in high-pressure situations compared to low-pressure ones. Uses Win Probability Added (WPA) in clutch moments vs. non-clutch moments.",
    interpretation:
      "Positive = performs better under pressure. A clutch index of +10 means the player's effective scoring rate is ~10% higher in pressure situations. Negative = wilts under pressure.",
    range: "-30 to +30",
    goodValue: "+5 or above",
    badValue: "Below -5",
  },
  {
    name: "Chase Master Index",
    shortName: "CHS",
    description:
      "Quantifies a batter's ability when chasing targets. Combines chase average, chase strike rate, and a composite of high-pressure chase innings to identify who can be trusted with run chases.",
    interpretation:
      "Higher is better. Elite chasers (8+) consistently perform above their baseline when the team is batting second with a target. Compares setting vs chasing performance to identify specialists.",
    range: "0–10",
    goodValue: "7+ (elite chase specialist)",
    badValue: "Below 3",
  },
  {
    name: "Win Probability Added (WPA)",
    shortName: "WPA",
    description:
      "Measures the change in win probability attributable to each player action (ball, over, innings). Aggregated WPA per match shows a player's average impact on match outcomes.",
    interpretation:
      "Positive WPA = helped the team win. Negative = hurt the team's chances. A WPA/match of +0.10 means the player adds 10 percentage points of win probability per game on average.",
    range: "-1 to +1 per match",
    goodValue: "+0.08 per match or higher",
    badValue: "Negative per-match WPA",
  },
  {
    name: "Flat Track Bully Index",
    shortName: "FTB",
    description:
      "Measures how much a player's performance varies based on venue difficulty. Compares performance at easier venues vs. harder venues. A score near zero means consistent performance regardless of conditions.",
    interpretation:
      'Closer to zero is better. Large negative values (below -0.30) indicate a "flat track bully" — someone who excels on easy pitches but struggles when conditions are challenging.',
    range: "-1 to +1",
    goodValue: "Between -0.10 and +0.10 (consistent everywhere)",
    badValue: "Below -0.30 (flat track bully)",
  },
  {
    name: "Selfless Index",
    description:
      "Measures how often a batter sacrifices personal stats for the team's benefit — e.g., accelerating at the risk of getting out, rotating strike to give a better batter the face, or playing a different role than their natural game demands.",
    interpretation:
      'Contextual. A high selfless index isn\'t necessarily "better" — it means the player adapts their approach to serve the team. Combined with high overall scores, it indicates a versatile, team-first player.',
    range: "0–100",
  },
  {
    name: "Anchor Cost Ratio",
    description:
      "For anchor-type batters, measures the cost of their accumulation approach — how many balls they consume relative to the run-rate pressure they create for their batting partners.",
    interpretation:
      "Lower is better (less cost). An anchor who maintains a high average but consumes balls at below par rate has a high anchor cost. The best anchors keep the cost ratio below 1.0 while providing stability.",
    range: "0–3+",
    goodValue: "Below 1.0",
    badValue: "Above 1.5",
  },
  {
    name: "Avg Balls to Par",
    description:
      'Average number of balls a batter needs to start scoring above the par strike rate for the match conditions. Measures how long the player takes to "get going".',
    interpretation:
      "Lower is better. Elite accelerators reach par within 5–10 balls. Slow starters may need 20+ balls before they start scoring above par, which can put pressure on partners.",
    range: "0–50+",
    goodValue: "Below 10 balls",
    badValue: "Above 25 balls",
  },
];

const CONTEXT_ADJUSTMENTS: MetricDefinition[] = [
  {
    name: "Opposition Quality",
    description:
      "Every metric is adjusted based on the quality of the opposition bowling/batting attack. Performing well against a top-tier attack (e.g., Bumrah, Rashid Khan) is worth more than the same stats against weaker opposition.",
    interpretation:
      "Automatic adjustment applied to all scores. Players who face consistently strong opposition get a boost; those who mainly play against weaker teams get a discount.",
  },
  {
    name: "Match Context Quality",
    description:
      "Adjusts for the importance and quality of the match. World Cup matches, knockout games, and bilateral series between top teams are weighted higher than low-stakes friendlies.",
    interpretation:
      "Automatic weighting. Performances in high-stakes matches contribute more to overall ratings.",
  },
  {
    name: "Recency Weighting",
    description:
      "More recent performances carry greater weight than older ones. Uses an exponential decay function where the most recent innings/spells count significantly more than those from 3+ years ago.",
    interpretation:
      "Ensures ratings reflect current form. A player who was elite in 2019 but has declined since will see their rating decrease, even if their career averages look good.",
  },
  {
    name: "Era Adjustment",
    description:
      "Normalises metrics across different eras of T20I cricket. As the game evolves (higher scoring rates, more boundaries, improved batting techniques), the par baselines shift. Era adjustment ensures fair comparison between a 2008 performance and a 2024 one.",
    interpretation:
      "Applied via era multipliers. A strike rate of 130 in 2008 was above par; the same rate in 2024 is below par. Multipliers correct for this.",
  },
  {
    name: "Venue Adjustment",
    description:
      "Adjusts metrics based on the difficulty of the venue. High-scoring grounds like Dharamsala have lower par performance expectations; challenging venues like Bridgetown require less for the same credit.",
    interpretation:
      "Automatic. See the Venue Analysis page for venue difficulty ratings.",
  },
];

const ARCHETYPES: {
  role: string;
  archetypes: { name: string; description: string; icon: string }[];
}[] = [
  {
    role: "Batting Archetypes",
    archetypes: [
      {
        name: "Aggressive Opener",
        description:
          "High acceleration and power upfront. Takes the attack to the bowling in the powerplay. Often a high-risk, high-reward player.",
        icon: "⚡",
      },
      {
        name: "Anchor",
        description:
          "High control, moderate acceleration. Provides stability and builds the innings. Often bats through and accelerates in the back end.",
        icon: "🛡️",
      },
      {
        name: "Chase Master",
        description:
          "Elite performance in chases. High clutch index and chase master score. Can be trusted to pace a run chase perfectly.",
        icon: "🎯",
      },
      {
        name: "Explosive Finisher",
        description:
          "Extreme power and acceleration in the death overs. Often bats at 5-7 and can score at 200+ SR in the last 5 overs.",
        icon: "💥",
      },
      {
        name: "Power Hitter",
        description:
          "Raw six-hitting ability throughout the innings. High power score but may sacrifice some control for aggression.",
        icon: "🔥",
      },
      {
        name: "Accumulator",
        description:
          "Consistent scorer with high average but moderate strike rate. Rarely fails but may not always provide the scoring rate the team needs.",
        icon: "📊",
      },
      {
        name: "All-Phase",
        description:
          "Balanced performer across all three metrics. No glaring weakness, adaptable to any match situation.",
        icon: "⚖️",
      },
    ],
  },
  {
    role: "Bowling Archetypes",
    archetypes: [
      {
        name: "Death Specialist",
        description:
          "Excels in death overs (16-20). Yorker accuracy, slower ball variety, and composure under pressure define this type.",
        icon: "🎯",
      },
      {
        name: "Powerplay Enforcer",
        description:
          "Dominates the first 6 overs with new ball. Takes early wickets and restricts scoring when the field is up.",
        icon: "⚡",
      },
      {
        name: "Spin Wizard",
        description:
          "Control-oriented spinner who excels in the middle overs. High dot percentage, good economy, and the ability to take wickets through deception.",
        icon: "🌀",
      },
      {
        name: "Wicket-Taker",
        description:
          "High threat score — a genuine wicket-taking option. May be expensive at times but provides crucial breakthroughs.",
        icon: "🔥",
      },
      {
        name: "Containment Specialist",
        description:
          "Elite economy and accuracy. May not take bags of wickets but builds immense pressure through dot balls and tight spells.",
        icon: "🛡️",
      },
      {
        name: "All-Phase",
        description:
          "Balanced bowler effective in all phases. Can bowl in the powerplay, middle, and death without a significant dip in performance.",
        icon: "⚖️",
      },
    ],
  },
];

const FAQ_ITEMS: FAQItem[] = [
  {
    question: "Why is Player X rated lower than I expect?",
    answer:
      "Our ratings adjust for context — opposition quality, venue difficulty, era, and recency. A player who averages 40 but mostly against weaker opposition at batting-friendly venues will rate lower than someone with the same average against tougher conditions. Additionally, recency weighting means older peak performances carry less weight than recent form.",
  },
  {
    question: "How is provisional status determined?",
    answer:
      'A player is marked as "provisional" if they have fewer than the minimum innings threshold (typically 15 for batters, 15 for bowlers). Provisional players\' ratings use Bayesian shrinkage towards the population mean, which means their scores are pulled towards average until they have enough data to be confident in their true ability.',
  },
  {
    question: "What does Bayesian shrinkage mean?",
    answer:
      "Bayesian shrinkage is a statistical technique that blends a player's observed performance with a prior (the average player). With few innings, the rating is mostly the average; as more data accumulates, the rating converges to the player's true performance. This prevents small-sample flukes from distorting ratings.",
  },
  {
    question: "How often are ratings updated?",
    answer:
      "The pipeline runs after each batch of T20I matches. Player scores, form charts, matchups, and all derived metrics are recalculated from the full historical dataset each time.",
  },
  {
    question: "Can I compare batters and bowlers?",
    answer:
      "The Compare page supports mixed comparisons — you can add both batters and bowlers. However, the stat table and radar chart will show role-specific metrics. The most meaningful comparisons are between players of the same role.",
  },
  {
    question: "What is the dominance index in matchups?",
    answer:
      "The dominance index ranges from roughly -50 to +50. Positive values indicate the batter dominated the matchup (high SR, few dismissals). Negative values indicate the bowler dominated (low SR, frequent dismissals). Values near zero indicate an even contest. It's calculated from strike rate vs par, dismissal frequency, and dot ball percentage in the specific matchup.",
  },
  {
    question: "How is similarity calculated?",
    answer:
      "Player similarity uses cosine similarity across the three core metric scores (Acceleration/Power/Control for batters, Accuracy/Control/Threat for bowlers). A similarity of 1.00 means identical metric profiles. We compute this for all player pairs and return the K nearest neighbours.",
  },
  {
    question: "What does the Flat Track Bully Index actually measure?",
    answer:
      "It compares a player's performance at easy venues (low difficulty score) versus hard venues (high difficulty score). If a player averages 45 at flat pitches but only 20 on challenging decks, they'll have a large negative FTB index. A player who performs consistently regardless of venue conditions will have an index near zero.",
  },
  {
    question: "How do the form charts work?",
    answer:
      "Form charts show a rolling window (typically 8–12 innings/spells) of performance metrics over time. Each point represents the average of the recent window at that date. This smooths out individual innings variance and reveals trends — whether a player is improving, declining, or staying steady.",
  },
  {
    question: "Are all-rounders rated separately for batting and bowling?",
    answer:
      "Yes. An all-rounder like Hardik Pandya will have separate batting and bowling profiles with their own scores, grades, and archetypes. The Player Profile page shows both views with a toggle. In the compare page, batting profiles take precedence unless explicitly specified.",
  },
];

// ── Section definitions ──────────────────────────────────────────

const SECTIONS: SectionDef[] = [
  {
    id: "batting",
    title: "Core Batting Metrics",
    icon: <Zap size={18} className="text-accent" />,
    description:
      "Every batter is rated on three core dimensions. These combine sub-components into a single 0–100 score with a letter grade.",
    metrics: BATTING_METRICS,
  },
  {
    id: "bowling",
    title: "Core Bowling Metrics",
    icon: <Target size={18} className="text-danger" />,
    description:
      "Every bowler is rated on three core dimensions, mirroring the batting metrics structure.",
    metrics: BOWLING_METRICS,
  },
  {
    id: "rating-system",
    title: "Rating System",
    icon: <BarChart3 size={18} className="text-primary" />,
    description:
      "How raw performance data is transformed into 0–100 scores and letter grades.",
  },
  {
    id: "advanced",
    title: "Advanced Metrics",
    icon: <Activity size={18} className="text-warning" />,
    description:
      "Beyond the core three metrics, several advanced analytics provide deeper insight.",
    metrics: ADVANCED_METRICS,
  },
  {
    id: "context",
    title: "Context Adjustments",
    icon: <Layers size={18} className="text-primary" />,
    description:
      "All metrics are adjusted for context so that performances are compared on a level playing field.",
    metrics: CONTEXT_ADJUSTMENTS,
  },
  {
    id: "grades",
    title: "Grades & Archetypes",
    icon: <Award size={18} className="text-gold" />,
    description:
      "Scores are mapped to letter grades, and players are classified into archetypes based on their metric profile.",
  },
  {
    id: "similarity",
    title: "Similarity",
    icon: <GitCompare size={18} className="text-accent" />,
    description: 'The methodology behind the "Similar Players" feature.',
  },
  {
    id: "faq",
    title: "FAQ",
    icon: <HelpCircle size={18} className="text-text-secondary" />,
    description: "Frequently asked questions about the rating methodology.",
  },
];

// ── Collapsible Section Component ────────────────────────────────

interface CollapsibleProps {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function Collapsible({
  title,
  defaultOpen = false,
  children,
}: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border border-surface-elevated rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left text-sm font-medium text-text-primary hover:bg-surface-elevated/50 transition-colors"
        aria-expanded={open}
      >
        {title}
        {open ? (
          <ChevronDown size={16} className="text-text-muted shrink-0" />
        ) : (
          <ChevronRight size={16} className="text-text-muted shrink-0" />
        )}
      </button>
      {open && <div className="px-4 pb-4 animate-fade-in">{children}</div>}
    </div>
  );
}

// ── MetricCard Component ─────────────────────────────────────────

interface MetricCardProps {
  metric: MetricDefinition;
  defaultOpen?: boolean;
}

function MetricCard({ metric, defaultOpen = false }: MetricCardProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="card p-0 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-surface-elevated/30 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-3">
          {metric.shortName && (
            <span className="font-score text-xs font-bold text-primary bg-primary/10 px-2 py-1 rounded">
              {metric.shortName}
            </span>
          )}
          <span className="text-sm font-semibold text-text-primary">
            {metric.name}
          </span>
          {metric.range && (
            <span className="text-[10px] text-text-muted bg-surface-elevated px-2 py-0.5 rounded-full hidden sm:inline">
              Range: {metric.range}
            </span>
          )}
        </div>
        {open ? (
          <ChevronDown size={16} className="text-text-muted shrink-0" />
        ) : (
          <ChevronRight size={16} className="text-text-muted shrink-0" />
        )}
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-4 animate-fade-in border-t border-surface-elevated">
          {/* Description */}
          <p className="text-sm text-text-secondary leading-relaxed mt-4">
            {metric.description}
          </p>

          {/* Interpretation */}
          {metric.interpretation && (
            <div className="bg-surface-elevated/30 rounded-lg p-3">
              <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1 flex items-center gap-1">
                <Info size={10} /> Interpretation
              </div>
              <p className="text-xs text-text-secondary leading-relaxed">
                {metric.interpretation}
              </p>
            </div>
          )}

          {/* Good / Bad values */}
          {(metric.goodValue || metric.badValue) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {metric.goodValue && (
                <div className="flex items-start gap-2 text-xs">
                  <span className="text-accent mt-0.5">✓</span>
                  <div>
                    <span className="font-medium text-text-primary">
                      Good:{" "}
                    </span>
                    <span className="text-text-secondary">
                      {metric.goodValue}
                    </span>
                  </div>
                </div>
              )}
              {metric.badValue && (
                <div className="flex items-start gap-2 text-xs">
                  <span className="text-danger mt-0.5">✗</span>
                  <div>
                    <span className="font-medium text-text-primary">
                      Concerning:{" "}
                    </span>
                    <span className="text-text-secondary">
                      {metric.badValue}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Formula */}
          {metric.formula && (
            <div className="bg-surface-elevated/30 rounded-lg p-3">
              <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1 flex items-center gap-1">
                <Hash size={10} /> Formula
              </div>
              <code className="text-xs text-primary font-mono">
                {metric.formula}
              </code>
            </div>
          )}

          {/* Sub-components */}
          {metric.components && metric.components.length > 0 && (
            <div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider mb-2 flex items-center gap-1">
                <Layers size={10} /> Sub-Components
              </div>
              <div className="space-y-2">
                {metric.components.map((comp, ci) => (
                  <div
                    key={ci}
                    className="flex items-start gap-2 pl-2 border-l-2 border-surface-elevated"
                  >
                    <div>
                      <span className="text-xs font-medium text-text-primary">
                        {comp.name}
                      </span>
                      <p className="text-xs text-text-muted leading-relaxed mt-0.5">
                        {comp.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────

export default function Glossary() {
  const location = useLocation();
  const [searchQuery, setSearchQuery] = useState("");
  const [showBackToTop, setShowBackToTop] = useState(false);

  // Track scroll for back-to-top button
  useEffect(() => {
    const handleScroll = () => {
      setShowBackToTop(window.scrollY > 400);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Scroll to hash on mount
  useEffect(() => {
    if (location.hash) {
      const el = document.getElementById(location.hash.slice(1));
      if (el) {
        setTimeout(() => {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 100);
      }
    }
  }, [location.hash]);

  // Filter sections by search
  const filteredSections = useMemo(() => {
    if (!searchQuery.trim()) return SECTIONS;
    const q = searchQuery.toLowerCase().trim();

    return SECTIONS.filter((section) => {
      if (section.title.toLowerCase().includes(q)) return true;
      if (section.description?.toLowerCase().includes(q)) return true;
      if (
        section.metrics?.some(
          (m) =>
            m.name.toLowerCase().includes(q) ||
            m.description.toLowerCase().includes(q) ||
            m.shortName?.toLowerCase().includes(q),
        )
      )
        return true;
      if (section.id === "faq") {
        return FAQ_ITEMS.some(
          (f) =>
            f.question.toLowerCase().includes(q) ||
            f.answer.toLowerCase().includes(q),
        );
      }
      return false;
    });
  }, [searchQuery]);

  const handleBackToTop = useCallback(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return (
    <div className="animate-fade-in space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-h1 text-text-primary flex items-center gap-3">
          <BookOpen size={28} className="text-primary" />
          Glossary & Methodology
        </h1>
        <p className="mt-1 text-sm text-text-secondary max-w-3xl">
          A comprehensive reference explaining every metric, the rating system,
          context adjustments, and how player archetypes are determined. Click
          any metric to expand its full definition.
        </p>
      </div>

      {/* Search + Table of Contents */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sidebar: ToC */}
        <aside className="lg:col-span-1">
          <div className="card p-4 lg:sticky lg:top-20">
            {/* Search */}
            <div className="relative mb-4">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
              />
              <input
                type="text"
                placeholder="Search metrics…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="filter-input pl-8 w-full text-sm"
                aria-label="Search glossary"
              />
            </div>

            {/* Section links */}
            <nav className="space-y-1" aria-label="Table of contents">
              {SECTIONS.map((section) => (
                <a
                  key={section.id}
                  href={`#${section.id}`}
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50 transition-colors"
                  onClick={(e) => {
                    e.preventDefault();
                    const el = document.getElementById(section.id);
                    if (el) {
                      el.scrollIntoView({ behavior: "smooth", block: "start" });
                    }
                  }}
                >
                  {section.icon}
                  <span>{section.title}</span>
                </a>
              ))}
            </nav>
          </div>
        </aside>

        {/* Main content */}
        <main className="lg:col-span-3 space-y-10">
          {/* ── 1. Core Batting Metrics ──────────────────────── */}
          {filteredSections.find((s) => s.id === "batting") && (
            <section id="batting" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <Zap size={20} className="text-accent" />
                <h2 className="text-h2 text-text-primary">
                  Core Batting Metrics
                </h2>
              </div>
              <p className="text-sm text-text-secondary mb-4">
                Every batter is rated on three core dimensions. These combine
                sub-components into a single 0–100 score with a letter grade.
              </p>
              <div className="space-y-3">
                {BATTING_METRICS.map((m, i) => (
                  <MetricCard key={m.name} metric={m} defaultOpen={i === 0} />
                ))}
              </div>
            </section>
          )}

          {/* ── 2. Core Bowling Metrics ──────────────────────── */}
          {filteredSections.find((s) => s.id === "bowling") && (
            <section id="bowling" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <Target size={20} className="text-danger" />
                <h2 className="text-h2 text-text-primary">
                  Core Bowling Metrics
                </h2>
              </div>
              <p className="text-sm text-text-secondary mb-4">
                Every bowler is rated on three core dimensions, mirroring the
                batting metrics structure.
              </p>
              <div className="space-y-3">
                {BOWLING_METRICS.map((m, i) => (
                  <MetricCard key={m.name} metric={m} defaultOpen={i === 0} />
                ))}
              </div>
            </section>
          )}

          {/* ── 3. Rating System ─────────────────────────────── */}
          {filteredSections.find((s) => s.id === "rating-system") && (
            <section id="rating-system" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <BarChart3 size={20} className="text-primary" />
                <h2 className="text-h2 text-text-primary">Rating System</h2>
              </div>
              <p className="text-sm text-text-secondary mb-4">
                How raw performance data is transformed into 0–100 scores and
                letter grades.
              </p>

              <div className="space-y-4">
                <Collapsible title="Step 1: Raw Metric Calculation" defaultOpen>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    Sub-component metrics (e.g., SR vs Par, boundary %, dot
                    control) are computed from ball-by-ball data. Each is
                    adjusted for context (opposition, venue, era) before
                    aggregation. A rolling window captures recent form, and
                    career-weighted averages provide stability.
                  </p>
                </Collapsible>

                <Collapsible title="Step 2: Bayesian Shrinkage">
                  <p className="text-xs text-text-secondary leading-relaxed">
                    For players with limited data, raw scores are shrunk towards
                    the population mean. The shrinkage factor depends on the
                    number of innings — with 5 innings, the rating is ~60%
                    population mean; with 30+ innings, it's ~95% the player's
                    own data. This prevents small-sample outliers from
                    dominating.
                  </p>
                </Collapsible>

                <Collapsible title="Step 3: Percentile Mapping">
                  <p className="text-xs text-text-secondary leading-relaxed">
                    Shrinkage-adjusted scores are mapped to percentiles within
                    the player population (separately for batters and bowlers).
                    A score of 85 means the player is at the 85th percentile —
                    better than 85% of all qualified players.
                  </p>
                </Collapsible>

                <Collapsible title="Step 4: Confidence Bonus">
                  <p className="text-xs text-text-secondary leading-relaxed">
                    Players with a larger sample size (more innings) receive a
                    small confidence bonus that reflects the reliability of
                    their rating. This bonus is capped and is most significant
                    in the transition from provisional to established status.
                  </p>
                </Collapsible>

                <Collapsible title="Step 5: Grade Assignment">
                  <div className="space-y-2">
                    <p className="text-xs text-text-secondary leading-relaxed mb-3">
                      Final percentile scores are mapped to letter grades:
                    </p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {SCORE_BANDS.map((band) => (
                        <div
                          key={band.grade}
                          className="flex items-center gap-2 rounded-lg p-2"
                          style={{ backgroundColor: band.bgColour }}
                        >
                          <GradeBadge grade={band.grade} size="sm" />
                          <div className="text-xs">
                            <div className="font-medium text-text-primary">
                              {band.min}–
                              {band.max >= 100 ? "100" : band.max.toFixed(0)}
                            </div>
                            <div className="text-text-muted text-[10px]">
                              {band.label.split(" — ")[1]}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </Collapsible>

                <Collapsible title="Step 6: Overall Score">
                  <p className="text-xs text-text-secondary leading-relaxed">
                    The overall score is a weighted average of the three core
                    metric scores. By default, all three are weighted equally
                    (33/33/33). The overall grade is derived from this combined
                    score using the same grade boundaries.
                  </p>
                </Collapsible>
              </div>
            </section>
          )}

          {/* ── 4. Advanced Metrics ──────────────────────────── */}
          {filteredSections.find((s) => s.id === "advanced") && (
            <section id="advanced" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <Activity size={20} className="text-warning" />
                <h2 className="text-h2 text-text-primary">Advanced Metrics</h2>
              </div>
              <p className="text-sm text-text-secondary mb-4">
                Beyond the core three metrics, several advanced analytics
                provide deeper insight into player value and tendencies.
              </p>
              <div className="space-y-3">
                {ADVANCED_METRICS.map((m) => (
                  <MetricCard key={m.name} metric={m} />
                ))}
              </div>
            </section>
          )}

          {/* ── 5. Context Adjustments ───────────────────────── */}
          {filteredSections.find((s) => s.id === "context") && (
            <section id="context" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <Layers size={20} className="text-primary" />
                <h2 className="text-h2 text-text-primary">
                  Context Adjustments
                </h2>
              </div>
              <p className="text-sm text-text-secondary mb-4">
                All metrics are adjusted for context so that performances are
                compared on a level playing field.
              </p>
              <div className="space-y-3">
                {CONTEXT_ADJUSTMENTS.map((m) => (
                  <MetricCard key={m.name} metric={m} />
                ))}
              </div>
            </section>
          )}

          {/* ── 6. Grades & Archetypes ───────────────────────── */}
          {filteredSections.find((s) => s.id === "grades") && (
            <section id="grades" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <Award size={20} className="text-gold" />
                <h2 className="text-h2 text-text-primary">
                  Grades & Archetypes
                </h2>
              </div>

              {/* Grade table */}
              <div className="card p-5 mb-6">
                <h3 className="text-h3 text-text-primary mb-3">
                  Grade Boundaries
                </h3>
                <p className="text-xs text-text-secondary mb-4">
                  Each 0–100 score is mapped to a letter grade based on these
                  boundaries:
                </p>
                <div className="overflow-x-auto">
                  <table className="sortable-table">
                    <thead>
                      <tr>
                        <th className="text-left">Grade</th>
                        <th className="text-left">Range</th>
                        <th className="text-left">Description</th>
                        <th className="text-left">Preview</th>
                      </tr>
                    </thead>
                    <tbody>
                      {SCORE_BANDS.map((band) => (
                        <tr key={band.grade}>
                          <td>
                            <GradeBadge grade={band.grade} size="md" />
                          </td>
                          <td className="font-score tabular-nums text-sm">
                            {band.min}–
                            {band.max >= 100 ? "100" : band.max.toFixed(0)}
                          </td>
                          <td className="text-sm text-text-secondary">
                            {band.label}
                          </td>
                          <td>
                            <ScoreBar
                              value={(band.min + band.max) / 2}
                              variant="minimal"
                              size="sm"
                              className="w-20"
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Archetypes */}
              {ARCHETYPES.map((group) => (
                <div key={group.role} className="card p-5 mb-4">
                  <h3 className="text-h3 text-text-primary mb-4">
                    {group.role}
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {group.archetypes.map((arch) => (
                      <div
                        key={arch.name}
                        className="rounded-lg border border-surface-elevated p-3 hover:bg-surface-elevated/30 transition-colors"
                      >
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="text-base">{arch.icon}</span>
                          <span className="text-sm font-semibold text-text-primary">
                            {arch.name}
                          </span>
                        </div>
                        <p className="text-xs text-text-secondary leading-relaxed">
                          {arch.description}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          )}

          {/* ── 7. Similarity ────────────────────────────────── */}
          {filteredSections.find((s) => s.id === "similarity") && (
            <section id="similarity" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <GitCompare size={20} className="text-accent" />
                <h2 className="text-h2 text-text-primary">Similarity</h2>
              </div>
              <div className="card p-5 space-y-4">
                <p className="text-sm text-text-secondary leading-relaxed">
                  The "Similar Players" feature uses{" "}
                  <strong className="text-text-primary">
                    cosine similarity
                  </strong>{" "}
                  to find players with the most similar statistical profiles.
                </p>

                <Collapsible title="How it works" defaultOpen>
                  <div className="space-y-3 text-xs text-text-secondary leading-relaxed">
                    <p>
                      Each player is represented as a 3-dimensional vector of
                      their core metric scores:
                    </p>
                    <div className="bg-surface-elevated/30 rounded-lg p-3 font-mono text-primary">
                      Batter: [Acceleration, Power, Control]
                      <br />
                      Bowler: [Accuracy, Control, Threat]
                    </div>
                    <p>
                      Cosine similarity measures the angle between two vectors.
                      If two players have exactly the same proportional profile
                      (e.g., both high Acceleration, medium Power, high
                      Control), the cosine similarity is 1.0 — regardless of the
                      absolute magnitudes.
                    </p>
                    <p>
                      We compute pairwise similarity for all players of the same
                      role and return the K nearest neighbours (default K=10).
                    </p>
                  </div>
                </Collapsible>

                <Collapsible title="Scatter plot projection">
                  <div className="text-xs text-text-secondary leading-relaxed space-y-2">
                    <p>
                      The 2D scatter plot on the Similar Players page projects
                      the 3D score vectors into 2D space using a simplified
                      linear projection (analogous to PCA). This provides an
                      approximate visual clustering.
                    </p>
                    <p>
                      Players close together on the scatter plot have similar
                      metric profiles. The target player is shown as a gold
                      star, with dashed lines to their closest matches.
                    </p>
                  </div>
                </Collapsible>

                <Collapsible title="Limitations">
                  <div className="text-xs text-text-secondary leading-relaxed space-y-2">
                    <p>
                      Cosine similarity only considers the three core metrics.
                      Two players might be "similar" by this measure but play
                      very different roles in their teams, face different
                      opposition quality, or have different career stages.
                    </p>
                    <p>
                      Similarity is role-specific: batters are only compared to
                      batters, bowlers to bowlers. Cross-role similarity is not
                      supported.
                    </p>
                  </div>
                </Collapsible>
              </div>
            </section>
          )}

          {/* ── 8. FAQ ───────────────────────────────────────── */}
          {filteredSections.find((s) => s.id === "faq") && (
            <section id="faq" className="scroll-mt-20">
              <div className="flex items-center gap-2 mb-2">
                <HelpCircle size={20} className="text-text-secondary" />
                <h2 className="text-h2 text-text-primary">
                  Frequently Asked Questions
                </h2>
              </div>
              <div className="space-y-3">
                {FAQ_ITEMS.filter((f) => {
                  if (!searchQuery.trim()) return true;
                  const q = searchQuery.toLowerCase().trim();
                  return (
                    f.question.toLowerCase().includes(q) ||
                    f.answer.toLowerCase().includes(q)
                  );
                }).map((faq, i) => (
                  <Collapsible key={i} title={faq.question}>
                    <p className="text-xs text-text-secondary leading-relaxed">
                      {faq.answer}
                    </p>
                  </Collapsible>
                ))}
              </div>
            </section>
          )}

          {/* Empty search state */}
          {searchQuery.trim() && filteredSections.length === 0 && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <Search size={48} className="text-text-muted mb-4" />
              <h2 className="text-h3 text-text-primary mb-2">
                No Results Found
              </h2>
              <p className="text-sm text-text-secondary max-w-md">
                No metrics or sections match "{searchQuery}". Try a different
                search term.
              </p>
            </div>
          )}
        </main>
      </div>

      {/* Back to top button */}
      {showBackToTop && (
        <button
          onClick={handleBackToTop}
          className="fixed bottom-6 right-6 z-40 btn-primary rounded-full p-3 shadow-lg animate-fade-in"
          aria-label="Back to top"
        >
          <ArrowUp size={20} />
        </button>
      )}
    </div>
  );
}
