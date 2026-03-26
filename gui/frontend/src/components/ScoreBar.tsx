/**
 * ScoreBar — horizontal 0–100 score bar with colour-coded fill.
 *
 * Renders a compact horizontal bar that visually represents a player's
 * score on a 0–100 scale. The fill colour corresponds to the grade
 * band (S=gold, A+=emerald, …, D=red) as defined in gui.md § 7.2.
 *
 * Features:
 *   - Animated fill width on mount / value change (CSS transition).
 *   - Optional label (metric name) on the left.
 *   - Optional numeric value on the right.
 *   - Optional grade badge inline.
 *   - Compact and full-width variants.
 *   - Accessible: uses role="meter" with aria attributes.
 *
 * Usage:
 *   <ScoreBar value={89.7} label="Acceleration" />
 *   <ScoreBar value={75.3} label="Power" showGrade />
 *   <ScoreBar value={null} label="Control" />  // renders empty bar with "—"
 *   <ScoreBar value={92.1} variant="compact" />
 */

import { scoreToColour, scoreToGrade } from "@/lib/colours";
import { fmtScore } from "@/lib/format";
import GradeBadge from "@/components/GradeBadge";

// ── Size variants ────────────────────────────────────────────────

const BAR_HEIGHT = {
  xs: "h-1.5",
  sm: "h-2",
  md: "h-3",
  lg: "h-4",
  xl: "h-5",
} as const;

const LABEL_SIZE = {
  xs: "text-[10px]",
  sm: "text-xs",
  md: "text-sm",
  lg: "text-sm",
  xl: "text-base",
} as const;

const VALUE_SIZE = {
  xs: "text-[10px]",
  sm: "text-xs",
  md: "text-sm font-score",
  lg: "text-base font-score",
  xl: "text-lg font-score",
} as const;

type BarSize = keyof typeof BAR_HEIGHT;

// ── Props ────────────────────────────────────────────────────────

interface ScoreBarProps {
  /** Score value (0–100). Null/undefined renders an empty bar. */
  value: number | null | undefined;
  /** Label text displayed to the left of the bar (e.g. "Acceleration"). */
  label?: string;
  /** Short label (3-char) displayed in compact mode. */
  labelShort?: string;
  /** Size variant. Default: "md". */
  size?: BarSize;
  /** If true, show the grade badge (e.g. "A+") to the right of the value. */
  showGrade?: boolean;
  /** If true, show the numeric value to the right of the bar. */
  showValue?: boolean;
  /**
   * Variant:
   * - "full" (default): label + bar + value on a single row
   * - "compact": smaller bar with no label, value below
   * - "minimal": just the bar, no label or value
   * - "stacked": label above the bar, value to the right
   */
  variant?: "full" | "compact" | "minimal" | "stacked";
  /** Width of the label column. Default: "w-24". */
  labelWidth?: string;
  /** Additional CSS classes for the outer container. */
  className?: string;
  /** Override the fill colour (hex string). If not set, derived from score band. */
  colour?: string;
  /** Whether to animate the fill on mount. Default: true. */
  animate?: boolean;
  /** Grade string override. If not provided, derived from the score value. */
  grade?: string;
  /**
   * When true with variant="minimal", hides the bar from assistive tech (aria-hidden)
   * and omits role="meter" — use when the numeric value is already announced beside the bar.
   */
  decorative?: boolean;
}

// ── Component ────────────────────────────────────────────────────

export default function ScoreBar({
  value,
  label,
  labelShort,
  size = "md",
  showGrade = false,
  showValue = true,
  variant = "full",
  labelWidth = "w-24",
  className = "",
  colour,
  animate = true,
  grade,
  decorative = false,
}: ScoreBarProps) {
  const score =
    value != null && isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
  const fillPct = score != null ? score : 0;
  const fillColour = colour ?? scoreToColour(score);
  const displayGrade = grade ?? (score != null ? scoreToGrade(score) : null);
  const displayValue = fmtScore(score);

  const barHeight = BAR_HEIGHT[size];
  const labelSizeClass = LABEL_SIZE[size];
  const valueSizeClass = VALUE_SIZE[size];

  // Transition class for animated fill
  const transitionClass = animate ? "transition-all duration-500 ease-out" : "";

  // ── Render: minimal ────────────────────────────────────────
  if (variant === "minimal") {
    if (decorative) {
      return (
        <div
          className={`score-bar ${barHeight} ${className}`}
          aria-hidden="true"
        >
          <div
            className={`score-bar-fill ${barHeight} ${transitionClass}`}
            style={{
              width: `${fillPct}%`,
              backgroundColor: fillColour,
            }}
          />
        </div>
      );
    }
    return (
      <div
        className={`score-bar ${barHeight} ${className}`}
        role="meter"
        aria-valuenow={score ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Score"}
      >
        <div
          className={`score-bar-fill ${barHeight} ${transitionClass}`}
          style={{
            width: `${fillPct}%`,
            backgroundColor: fillColour,
          }}
        />
      </div>
    );
  }

  // ── Render: compact ────────────────────────────────────────
  if (variant === "compact") {
    return (
      <div className={`flex flex-col gap-0.5 ${className}`}>
        {(label || labelShort) && (
          <div className="flex items-center justify-between">
            <span className={`${labelSizeClass} text-text-secondary truncate`}>
              {labelShort ?? label}
            </span>
            {showValue && (
              <span
                className={`${valueSizeClass} tabular-nums`}
                style={{ color: fillColour }}
              >
                {displayValue}
              </span>
            )}
          </div>
        )}
        <div
          className={`score-bar ${BAR_HEIGHT.sm}`}
          role="meter"
          aria-valuenow={score ?? undefined}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={label ?? "Score"}
        >
          <div
            className={`score-bar-fill ${BAR_HEIGHT.sm} ${transitionClass}`}
            style={{
              width: `${fillPct}%`,
              backgroundColor: fillColour,
            }}
          />
        </div>
      </div>
    );
  }

  // ── Render: stacked ────────────────────────────────────────
  if (variant === "stacked") {
    return (
      <div className={`flex flex-col gap-1 ${className}`}>
        {label && (
          <span className={`${labelSizeClass} text-text-secondary`}>
            {label}
          </span>
        )}
        <div className="flex items-center gap-2">
          <div
            className={`score-bar ${barHeight} flex-1`}
            role="meter"
            aria-valuenow={score ?? undefined}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={label ?? "Score"}
          >
            <div
              className={`score-bar-fill ${barHeight} ${transitionClass}`}
              style={{
                width: `${fillPct}%`,
                backgroundColor: fillColour,
              }}
            />
          </div>
          {showValue && (
            <span
              className={`${valueSizeClass} tabular-nums min-w-[2.5rem] text-right`}
              style={{ color: fillColour }}
            >
              {displayValue}
            </span>
          )}
          {showGrade && displayGrade && (
            <GradeBadge
              grade={displayGrade}
              size={size === "xs" || size === "sm" ? "xs" : "sm"}
            />
          )}
        </div>
      </div>
    );
  }

  // ── Render: full (default) ─────────────────────────────────
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {/* Label */}
      {label && (
        <span
          className={`${labelSizeClass} ${labelWidth} shrink-0 text-text-secondary uppercase tracking-wider truncate`}
          title={label}
        >
          {labelShort ?? label}
        </span>
      )}

      {/* Bar track */}
      <div
        className={`score-bar ${barHeight} flex-1 min-w-0`}
        role="meter"
        aria-valuenow={score ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Score"}
      >
        {/* Fill */}
        <div
          className={`score-bar-fill ${barHeight} ${transitionClass}`}
          style={{
            width: `${fillPct}%`,
            backgroundColor: fillColour,
          }}
        />
      </div>

      {/* Value */}
      {showValue && (
        <span
          className={`${valueSizeClass} tabular-nums min-w-[2.5rem] text-right`}
          style={{ color: fillColour }}
        >
          {displayValue}
        </span>
      )}

      {/* Grade badge */}
      {showGrade && displayGrade && (
        <GradeBadge
          grade={displayGrade}
          size={size === "xs" || size === "sm" ? "xs" : "sm"}
        />
      )}
    </div>
  );
}

// ── Variant: ScoreBarGroup ───────────────────────────────────────
// Renders the standard 3-metric score bars (Acceleration/Power/Control
// or Accuracy/Control/Threat) as a vertical group.

interface ScoreBarGroupProps {
  /** The three score values (score_1, score_2, score_3). */
  scores: {
    score_1: number | null | undefined;
    score_2: number | null | undefined;
    score_3: number | null | undefined;
  };
  /** Labels for the three scores. */
  labels?: {
    s1?: string;
    s2?: string;
    s3?: string;
  };
  /** Grade strings for the three scores. */
  grades?: {
    g1?: string;
    g2?: string;
    g3?: string;
  };
  /** Whether to show grade badges. Default: false. */
  showGrades?: boolean;
  /** Bar size. Default: "md". */
  size?: BarSize;
  /** ScoreBar variant. Default: "full". */
  variant?: "full" | "compact" | "stacked";
  /** Space between bars. Default: "gap-2". */
  gap?: string;
  /** Label column width. Default: "w-24". */
  labelWidth?: string;
  /** Additional CSS classes. */
  className?: string;
}

export function ScoreBarGroup({
  scores,
  labels = {},
  grades = {},
  showGrades = false,
  size = "md",
  variant = "full",
  gap = "gap-2",
  labelWidth = "w-24",
  className = "",
}: ScoreBarGroupProps) {
  const s1Label = labels.s1 ?? "Score 1";
  const s2Label = labels.s2 ?? "Score 2";
  const s3Label = labels.s3 ?? "Score 3";

  return (
    <div className={`flex flex-col ${gap} ${className}`}>
      <ScoreBar
        value={scores.score_1}
        label={s1Label}
        grade={grades.g1}
        showGrade={showGrades}
        size={size}
        variant={variant}
        labelWidth={labelWidth}
      />
      <ScoreBar
        value={scores.score_2}
        label={s2Label}
        grade={grades.g2}
        showGrade={showGrades}
        size={size}
        variant={variant}
        labelWidth={labelWidth}
      />
      <ScoreBar
        value={scores.score_3}
        label={s3Label}
        grade={grades.g3}
        showGrade={showGrades}
        size={size}
        variant={variant}
        labelWidth={labelWidth}
      />
    </div>
  );
}

// ── Variant: ScoreBarMini ────────────────────────────────────────
// Ultra-compact score bar for use inside table cells and cards.

interface ScoreBarMiniProps {
  value: number | null | undefined;
  /** Width of the bar track in pixels. Default: 48. */
  width?: number;
  className?: string;
}

export function ScoreBarMini({
  value,
  width = 48,
  className = "",
}: ScoreBarMiniProps) {
  const score =
    value != null && isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
  const fillPct = score != null ? score : 0;
  const fillColour = scoreToColour(score);

  return (
    <div className={`inline-flex items-center gap-1.5 ${className}`}>
      <div
        className="score-bar h-1.5 rounded-full"
        style={{ width: `${width}px` }}
        role="meter"
        aria-valuenow={score ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="score-bar-fill h-1.5 rounded-full transition-all duration-500 ease-out"
          style={{
            width: `${fillPct}%`,
            backgroundColor: fillColour,
          }}
        />
      </div>
      <span
        className="text-[10px] font-score tabular-nums min-w-[1.75rem] text-right"
        style={{ color: fillColour }}
      >
        {score != null ? Math.round(score) : "—"}
      </span>
    </div>
  );
}
