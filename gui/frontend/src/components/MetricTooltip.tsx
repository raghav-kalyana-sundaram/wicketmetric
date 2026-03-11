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
} from 'react';
import { Info } from 'lucide-react';

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
  category?: 'batting' | 'bowling' | 'advanced' | 'context' | 'general';
}

export const METRIC_DEFINITIONS: Record<string, MetricDefinition> = {
  // ── Core batting metrics ─────────────────────────────────────
  acceleration: {
    name: 'Acceleration',
    description:
      'Measures how quickly a batter scores relative to match conditions. Combines overall strike rate, SR growth through the innings, death-overs SR, and high-impact innings frequency.',
    interpretation:
      'Higher is better. Elite batters (A+/S grade) consistently score faster than the match par rate and accelerate through their innings.',
    range: '0–100',
    highMeaning: 'Scores very fast, especially in the death overs',
    lowMeaning: 'Below-par scoring rate for match conditions',
    category: 'batting',
  },
  score_acceleration: {
    name: 'Acceleration',
    description:
      'Measures how quickly a batter scores relative to match conditions. Combines overall strike rate, SR growth through the innings, death-overs SR, and high-impact innings frequency.',
    interpretation:
      'Higher is better. Elite batters consistently score faster than the match par rate.',
    range: '0–100',
    category: 'batting',
  },
  power: {
    name: 'Power',
    description:
      'Quantifies a batter\'s ability to hit boundaries. Combines boundary percentage, six-hitting rate, boundaries vs par, peak SR bursts, and burst scoring ability.',
    interpretation:
      'Higher is better. Power hitters (85+) clear the rope frequently and score in large chunks.',
    range: '0–100',
    highMeaning: 'Frequent boundaries and sixes, high peak SR',
    lowMeaning: 'Relies on rotation rather than boundaries',
    category: 'batting',
  },
  score_power: {
    name: 'Power',
    description:
      'Quantifies boundary-hitting ability. Combines boundary %, six rate, boundaries vs par, peak SR, and burst scoring.',
    range: '0–100',
    category: 'batting',
  },
  control: {
    name: 'Control (Batting)',
    description:
      'Measures a batter\'s ability to manage their innings. Combines dot ball avoidance, strike rotation, runs contribution, batting average, and dismissal quality.',
    interpretation:
      'Higher is better. Controlled batters rarely get stuck, rotate strike well, and get out to good deliveries rather than loose shots.',
    range: '0–100',
    highMeaning: 'Low dot %, good rotation, high average',
    lowMeaning: 'Gets stuck frequently, poor shot selection',
    category: 'batting',
  },
  score_control: {
    name: 'Control',
    description:
      'Measures innings management: dot ball avoidance, rotation, runs contribution, average, and dismissal quality.',
    range: '0–100',
    category: 'batting',
  },

  // ── Core bowling metrics ─────────────────────────────────────
  accuracy: {
    name: 'Accuracy',
    description:
      'Measures a bowler\'s ability to restrict scoring. Combines economy rate vs par, dot ball percentage, and consistency of restricting boundaries.',
    interpretation:
      'Higher is better. Accurate bowlers consistently bowl dots and keep the economy below par for the venue/era.',
    range: '0–100',
    highMeaning: 'Low economy, high dot ball %',
    lowMeaning: 'Leaks runs frequently',
    category: 'bowling',
  },
  score_accuracy: {
    name: 'Accuracy',
    description:
      'Measures scoring restriction: economy vs par, dot ball %, and boundary prevention.',
    range: '0–100',
    category: 'bowling',
  },
  control_bowl: {
    name: 'Control (Bowling)',
    description:
      'Measures a bowler\'s discipline and plan execution. Combines consistency of lengths, wide/no-ball rate, and phase-specific performance.',
    interpretation:
      'Higher is better. Controlled bowlers execute their plans consistently across different phases.',
    range: '0–100',
    category: 'bowling',
  },
  threat: {
    name: 'Threat',
    description:
      'Measures a bowler\'s wicket-taking ability. Combines strike rate, quality of wickets (bowled/LBW %), top-order scalps, and pressure-building sequences.',
    interpretation:
      'Higher is better. Threatening bowlers take wickets regularly and break partnerships.',
    range: '0–100',
    highMeaning: 'Frequent wickets, high bowled/LBW %',
    lowMeaning: 'Rarely takes wickets',
    category: 'bowling',
  },
  score_threat: {
    name: 'Threat',
    description:
      'Wicket-taking ability: strike rate, wicket quality (bowled/LBW %), top-order scalps, and pressure sequences.',
    range: '0–100',
    category: 'bowling',
  },

  // ── Advanced metrics ─────────────────────────────────────────
  war_batting: {
    name: 'WAR (Batting)',
    description:
      'Wins Above Replacement — estimates how many additional wins a batter provides compared to a replacement-level player over their career.',
    interpretation:
      'Higher is better. A WAR of 3+ over a career is excellent. WAR accounts for innings count, so longevity matters.',
    range: '0+',
    highMeaning: 'Significantly better than replacement level',
    lowMeaning: 'Close to or below replacement level',
    category: 'advanced',
  },
  war_bowling: {
    name: 'WAR (Bowling)',
    description:
      'Wins Above Replacement for bowling — estimates additional wins provided compared to a replacement-level bowler.',
    interpretation:
      'Higher is better. Bowlers accumulate WAR through consistent wicket-taking and run restriction.',
    range: '0+',
    category: 'advanced',
  },
  war_batting_rate: {
    name: 'WAR Rate (Batting)',
    description:
      'WAR per 50 innings — normalises WAR by sample size to allow comparison between players with different career lengths.',
    range: '0+',
    category: 'advanced',
  },
  war_bowling_rate: {
    name: 'WAR Rate (Bowling)',
    description:
      'WAR per 50 spells — normalises bowling WAR by sample size.',
    range: '0+',
    category: 'advanced',
  },
  clutch_index: {
    name: 'Clutch Index',
    description:
      'Measures how much a player elevates their performance in high-pressure situations (close matches, chases, knockout games) compared to their baseline.',
    interpretation:
      'Positive values indicate a player who performs better under pressure. Negative values suggest they underperform in high-stakes moments.',
    range: '-30 to +30',
    highMeaning: 'Thrives under pressure — "big-game player"',
    lowMeaning: 'Underperforms in pressure situations',
    category: 'advanced',
  },
  clutch_index_bowl: {
    name: 'Clutch Index (Bowling)',
    description:
      'Measures how much a bowler elevates their performance in high-pressure situations compared to their baseline.',
    range: '-30 to +30',
    category: 'advanced',
  },
  chase_master_index: {
    name: 'Chase Master Index',
    description:
      'Quantifies a batter\'s ability in successful run chases. Based on SR elevation, average in chases, and contributions to chase wins.',
    interpretation:
      'Higher is better. A score of 8+ indicates an elite chase specialist.',
    range: '0–15+',
    highMeaning: 'Elite chase ability — controls innings 2 run chases',
    lowMeaning: 'Struggles or has limited impact in chases',
    category: 'advanced',
  },
  flat_track_index: {
    name: 'Flat Track Index',
    description:
      'Measures how much a player\'s performance varies between easy and tough conditions. A negative or near-zero value means they perform consistently everywhere.',
    interpretation:
      'Near zero is ideal. A high positive value (flat-track bully) means the player primarily scores on easy pitches. Negative means they actually perform better in tough conditions.',
    range: '-5 to +5',
    highMeaning: 'Scores mostly on flat tracks — "flat-track bully"',
    lowMeaning: 'Performs well across all conditions',
    category: 'advanced',
  },
  flat_track_index_bowl: {
    name: 'Flat Track Index (Bowling)',
    description:
      'Measures how much a bowler\'s performance varies between easy and tough conditions.',
    range: '-5 to +5',
    category: 'advanced',
  },
  selfless_index: {
    name: 'Selfless Index',
    description:
      'Measures how much a batter prioritises team outcomes over personal milestones. Based on SR acceleration when the team needs quick runs vs. when personal stats might suffer.',
    range: '0–10',
    category: 'advanced',
  },
  venue_adjusted_composite: {
    name: 'Venue-Adjusted Composite',
    description:
      'Overall composite rating adjusted for the difficulty of venues played at. Accounts for the fact that some players have played more at high-scoring grounds.',
    range: '0–100',
    category: 'advanced',
  },
  anchor_cost_ratio: {
    name: 'Anchor Cost Ratio',
    description:
      'For anchoring batters — the ratio of team benefit (stability, partnerships) to the scoring rate sacrifice compared to a more aggressive approach.',
    interpretation:
      'Higher is better. A high ratio means the anchor contributes more stability than they cost in scoring rate.',
    range: '0+',
    category: 'advanced',
  },

  // ── Context adjustments ──────────────────────────────────────
  sr_vs_par: {
    name: 'SR vs Par',
    description:
      'Strike rate relative to the match par rate. A value of 1.15 means the batter scored 15% faster than the median for that match/venue.',
    interpretation:
      'Above 1.0 is good. The match par accounts for venue, era, and conditions.',
    range: '0.5–2.0+',
    category: 'context',
  },
  economy_vs_par: {
    name: 'Economy vs Par',
    description:
      'Economy rate relative to the match par. A negative value means the bowler conceded fewer runs than par.',
    interpretation:
      'Negative is good (bowled better than par). Positive means more expensive than par.',
    range: '-5 to +5',
    category: 'context',
  },
  dominance_index: {
    name: 'Dominance Index',
    description:
      'Measures who has the upper hand in a batter-vs-bowler matchup. Positive values favour the batter, negative values favour the bowler.',
    interpretation:
      'Based on SR vs expected, dismissal rate, and dot ball frequency in the matchup.',
    range: '-50 to +50',
    highMeaning: 'Batter dominates the matchup',
    lowMeaning: 'Bowler dominates the matchup',
    category: 'context',
  },

  // ── General / derived ────────────────────────────────────────
  overall_score: {
    name: 'Overall Score',
    description:
      'Weighted composite of all three dimension scores (e.g. Acceleration + Power + Control for batters). Includes a superstar bonus for players who excel across all dimensions.',
    range: '0–100',
    category: 'general',
  },
  overall_grade: {
    name: 'Overall Grade',
    description:
      'Letter grade derived from the overall score. S (95–100) is elite, A+ (85–94) exceptional, down to D (0–14).',
    range: 'D to S',
    category: 'general',
  },
  career_sr: {
    name: 'Career Strike Rate',
    description:
      'Runs scored per 100 balls faced across all T20I innings. A basic counting stat — the composite scores provide a more nuanced view.',
    range: '80–200+',
    category: 'general',
  },
  career_avg: {
    name: 'Career Average',
    description:
      'Runs per dismissal across all T20I innings. Higher is better, but in T20s a high average with a low SR can indicate overly cautious batting.',
    range: '10–60+',
    category: 'general',
  },
  career_economy: {
    name: 'Career Economy',
    description:
      'Runs conceded per over across all T20I spells. Lower is better.',
    range: '4–12+',
    category: 'general',
  },
  innings_count: {
    name: 'Innings',
    description:
      'Total number of batting innings played in T20Is. Used to determine provisional status and as a weighting factor in several metrics.',
    category: 'general',
  },
  is_provisional: {
    name: 'Provisional Status',
    description:
      'Players with fewer than the minimum innings threshold (typically 10) are marked as provisional. Their ratings may change significantly with more data.',
    category: 'general',
  },
  multiplier: {
    name: 'Era Multiplier',
    description:
      'Adjustment factor for different eras of T20I cricket. A multiplier of 1.28 means performances from that year are worth 28% more than equivalent raw numbers in the most recent year.',
    interpretation:
      'Earlier eras had lower scoring rates, so the multiplier compensates for this when comparing across eras.',
    range: '0.9–1.5+',
    category: 'context',
  },
  par_sr: {
    name: 'Par Strike Rate',
    description:
      'The median strike rate for a given year, representing the typical scoring rate of the era. Used as a baseline for SR vs Par calculations.',
    range: '100–160+',
    category: 'context',
  },
  boundary_rate: {
    name: 'Boundary Rate',
    description:
      'Percentage of balls that resulted in a boundary (four or six). Shows how boundary-dependent scoring is in a given era or venue.',
    range: '5–25%',
    category: 'context',
  },
  dot_pct: {
    name: 'Dot Ball %',
    description:
      'Percentage of balls faced/bowled that resulted in zero runs. For batters, lower is better; for bowlers, higher is better.',
    range: '20–50%',
    category: 'general',
  },
  similarity_score: {
    name: 'Similarity Score',
    description:
      'Cosine similarity between two players\' metric profiles. 1.0 means identical profiles, 0.0 means completely different.',
    range: '0.0–1.0',
    highMeaning: 'Very similar statistical profile',
    lowMeaning: 'Very different statistical profile',
    category: 'general',
  },
};

// ── Tooltip positioning ──────────────────────────────────────────

type TooltipPosition = 'above' | 'below' | 'left' | 'right' | 'auto';

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
  mode?: 'wrap' | 'icon';
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
  position = 'auto',
  delay = 300,
  maxWidth = 280,
  children,
  className = '',
  helpCursor = true,
  underline = false,
  mode = 'wrap',
  iconSize = 14,
  disabled = false,
}: MetricTooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [resolvedPosition, setResolvedPosition] = useState<
    'above' | 'below' | 'left' | 'right'
  >('above');
  const triggerRef = useRef<HTMLSpanElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Look up the metric definition
  const definition = metric ? METRIC_DEFINITIONS[metric] : undefined;

  // Resolve the display content
  const tooltipTitle = titleProp ?? definition?.name;
  const tooltipContent = contentProp ?? definition?.description;
  const tooltipInterpretation =
    showInterpretation && definition?.interpretation
      ? definition.interpretation
      : undefined;
  const tooltipRange = showRange && definition?.range ? definition.range : undefined;
  const tooltipHigh = showRange ? definition?.highMeaning : undefined;
  const tooltipLow = showRange ? definition?.lowMeaning : undefined;

  // If there's nothing to show, just render children
  const hasContent = !disabled && (tooltipContent || tooltipTitle);

  // Auto-position based on trigger location in viewport
  const resolvePosition = useCallback(() => {
    if (position !== 'auto') {
      setResolvedPosition(position);
      return;
    }

    if (!triggerRef.current) {
      setResolvedPosition('above');
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
      setResolvedPosition('above');
    } else if (spaceBelow > 100) {
      setResolvedPosition('below');
    } else if (spaceRight > maxWidth + 20) {
      setResolvedPosition('right');
    } else if (spaceLeft > maxWidth + 20) {
      setResolvedPosition('left');
    } else {
      // Fallback: whichever vertical direction has more room
      setResolvedPosition(spaceAbove >= spaceBelow ? 'above' : 'below');
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

  // Hide on Escape key
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
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
    above: 'bottom-full mb-2 left-1/2 -translate-x-1/2',
    below: 'top-full mt-2 left-1/2 -translate-x-1/2',
    left: 'right-full mr-2 top-1/2 -translate-y-1/2',
    right: 'left-full ml-2 top-1/2 -translate-y-1/2',
  };

  // Arrow classes
  const arrowClasses = {
    above: 'top-full left-1/2 -translate-x-1/2 -mt-[3px] border-t border-l',
    below: 'bottom-full left-1/2 -translate-x-1/2 -mb-[3px] border-b border-r',
    left: 'left-full top-1/2 -translate-y-1/2 -ml-[3px] border-t border-r',
    right: 'right-full top-1/2 -translate-y-1/2 -mr-[3px] border-b border-l',
  };

  const tooltipElement = hasContent && isVisible && (
    <span
      className={[
        'absolute z-50 pointer-events-none rounded-lg px-3 py-2.5',
        'bg-surface-elevated text-text-primary shadow-lg',
        'border border-surface-elevated/80',
        'text-xs leading-relaxed font-normal',
        'animate-fade-in',
        positionClasses[resolvedPosition],
      ].join(' ')}
      style={{ maxWidth: `${maxWidth}px`, width: 'max-content' }}
      role="tooltip"
    >
      {/* Title */}
      {tooltipTitle && (
        <span className="block font-semibold text-text-primary mb-1">
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
            <span className="flex items-center gap-1 text-accent text-[10px]">
              <span>▲</span>
              <span>{tooltipHigh}</span>
            </span>
          )}
          {tooltipLow && (
            <span className="flex items-center gap-1 text-danger text-[10px]">
              <span>▼</span>
              <span>{tooltipLow}</span>
            </span>
          )}
        </span>
      )}

      {/* Arrow */}
      <span
        className={[
          'absolute w-2 h-2 rotate-45',
          'bg-surface-elevated border-surface-elevated/80',
          arrowClasses[resolvedPosition],
        ].join(' ')}
        aria-hidden="true"
      />
    </span>
  );

  // ── Render: icon mode ──────────────────────────────────────

  if (mode === 'icon') {
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
            aria-describedby={isVisible ? 'metric-tooltip' : undefined}
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
        'relative inline-flex items-center',
        helpCursor ? 'cursor-help' : '',
        underline ? 'underline decoration-dotted decoration-text-muted underline-offset-2' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      aria-describedby={isVisible ? 'metric-tooltip' : undefined}
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
  className = '',
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
  textSize = 'text-sm',
  showIcon = true,
  iconSize = 12,
  showRange = false,
  className = '',
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
