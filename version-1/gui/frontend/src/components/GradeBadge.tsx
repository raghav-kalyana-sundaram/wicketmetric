/**
 * GradeBadge — displays a letter grade (S, A+, A, B+, B, C+, C, D)
 * with colour-coded styling matching the design spec in gui.md § 7.2.
 *
 * Usage:
 *   <GradeBadge grade="A+" />
 *   <GradeBadge grade="S" size="lg" />
 *   <GradeBadge grade={player.grade_overall} showLabel />
 */

import { gradeToClass, gradeToLabel } from '@/lib/colours';

// ── Size variants ────────────────────────────────────────────────

const SIZE_CLASSES = {
  xs: 'px-1.5 py-0.5 text-[10px] leading-none',
  sm: 'px-2 py-0.5 text-xs leading-none',
  md: 'px-2.5 py-1 text-sm leading-none',
  lg: 'px-3 py-1.5 text-base leading-none',
  xl: 'px-4 py-2 text-lg leading-none',
} as const;

type BadgeSize = keyof typeof SIZE_CLASSES;

// ── Props ────────────────────────────────────────────────────────

interface GradeBadgeProps {
  /** The grade string (e.g. "A+", "S", "D"). */
  grade: string | null | undefined;
  /** Size variant. Default: "sm". */
  size?: BadgeSize;
  /** If true, show the full label (e.g. "A+ — Exceptional") instead of just the letter. */
  showLabel?: boolean;
  /** Additional CSS classes to merge. */
  className?: string;
  /** Whether to render as a pill (fully rounded) or a badge (slightly rounded). Default: badge. */
  pill?: boolean;
}

// ── Component ────────────────────────────────────────────────────

export default function GradeBadge({
  grade,
  size = 'sm',
  showLabel = false,
  className = '',
  pill = false,
}: GradeBadgeProps) {
  const displayGrade = grade?.trim() || 'D';
  const colourClass = gradeToClass(displayGrade);
  const sizeClass = SIZE_CLASSES[size];
  const roundedClass = pill ? 'rounded-full' : 'rounded-md';
  const label = showLabel ? gradeToLabel(displayGrade) : displayGrade;

  return (
    <span
      className={`grade-badge ${colourClass} ${sizeClass} ${roundedClass} inline-flex items-center justify-center font-semibold uppercase tracking-wide select-none ${className}`}
      title={gradeToLabel(displayGrade)}
      role="img"
      aria-label={`Grade: ${gradeToLabel(displayGrade)}`}
    >
      {label}
    </span>
  );
}

// ── Variant: GradeBadgeInline ────────────────────────────────────
// A minimal inline version without background — just coloured text.

interface GradeBadgeInlineProps {
  grade: string | null | undefined;
  className?: string;
}

export function GradeBadgeInline({
  grade,
  className = '',
}: GradeBadgeInlineProps) {
  const displayGrade = grade?.trim() || 'D';
  const colourClass = gradeToClass(displayGrade);

  // Extract just the text colour from the grade class by using the
  // score-color utility classes instead.
  const cssKey = colourClass.replace('grade-', '');

  return (
    <span
      className={`score-color-${cssKey} font-semibold ${className}`}
      title={gradeToLabel(displayGrade)}
    >
      {displayGrade}
    </span>
  );
}
