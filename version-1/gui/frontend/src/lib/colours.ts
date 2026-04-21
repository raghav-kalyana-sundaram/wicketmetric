/**
 * Score-to-colour and grade mapping utilities.
 *
 * Provides consistent colour coding across all components that display
 * 0–100 scores and letter grades. The mapping follows the design spec
 * in gui.md § 7.2 "Score Bar Colour Mapping".
 *
 * Usage:
 *   import { scoreToColour, gradeToColour, gradeToClass } from '@/lib/colours';
 *
 *   const colour = scoreToColour(89.7);   // "#10B981" (A+ emerald)
 *   const cls = gradeToClass('A+');        // "grade-a-plus"
 */

import type { Grade } from "@/api/types";
import {
  matchupEdgeScore,
  matchupEdgeLabel as matchupEdgeTier,
} from "@/lib/format";

// ── Score range → colour mapping ─────────────────────────────────

export interface ScoreBand {
  min: number;
  max: number;
  grade: Grade;
  colour: string;
  label: string;
  /** CSS class suffix (e.g. "s", "a-plus") */
  cssKey: string;
  /** Background colour (same hue, lower opacity in dark mode) */
  bgColour: string;
}

/**
 * Ordered score bands from highest to lowest.
 * Each band defines the range, grade, colour, and CSS class.
 */
export const SCORE_BANDS: readonly ScoreBand[] = [
  {
    min: 95,
    max: 100,
    grade: "S",
    colour: "#FFD700",
    label: "S — Elite",
    cssKey: "s",
    bgColour: "rgba(255, 215, 0, 0.20)",
  },
  {
    min: 85,
    max: 94.99,
    grade: "A+",
    colour: "#10B981",
    label: "A+ — Exceptional",
    cssKey: "a-plus",
    bgColour: "rgba(16, 185, 129, 0.20)",
  },
  {
    min: 75,
    max: 84.99,
    grade: "A",
    colour: "#22C55E",
    label: "A — Excellent",
    cssKey: "a",
    bgColour: "rgba(34, 197, 94, 0.20)",
  },
  {
    min: 60,
    max: 74.99,
    grade: "B+",
    colour: "#787878",
    label: "B+ — Very Good",
    cssKey: "b-plus",
    bgColour: "rgba(120, 120, 120, 0.22)",
  },
  {
    min: 45,
    max: 59.99,
    grade: "B",
    colour: "#5c5c5c",
    label: "B — Good",
    cssKey: "b",
    bgColour: "rgba(92, 92, 92, 0.22)",
  },
  {
    min: 30,
    max: 44.99,
    grade: "C+",
    colour: "#F59E0B",
    label: "C+ — Average",
    cssKey: "c-plus",
    bgColour: "rgba(245, 158, 11, 0.20)",
  },
  {
    min: 15,
    max: 29.99,
    grade: "C",
    colour: "#F97316",
    label: "C — Below Average",
    cssKey: "c",
    bgColour: "rgba(249, 115, 22, 0.20)",
  },
  {
    min: 0,
    max: 14.99,
    grade: "D",
    colour: "#EF4444",
    label: "D — Poor",
    cssKey: "d",
    bgColour: "rgba(239, 68, 68, 0.20)",
  },
] as const;

// ── Pre-computed lookup maps ─────────────────────────────────────

const GRADE_TO_BAND = new Map<string, ScoreBand>();
for (const band of SCORE_BANDS) {
  GRADE_TO_BAND.set(band.grade, band);
}

// Normalised key variants (handle various API formats)
const GRADE_ALIASES: Record<string, Grade> = {
  S: "S",
  s: "S",
  "A+": "A+",
  "a+": "A+",
  A_PLUS: "A+",
  a_plus: "A+",
  A: "A",
  a: "A",
  "B+": "B+",
  "b+": "B+",
  B_PLUS: "B+",
  b_plus: "B+",
  B: "B",
  b: "B",
  "C+": "C+",
  "c+": "C+",
  C_PLUS: "C+",
  c_plus: "C+",
  C: "C",
  c: "C",
  D: "D",
  d: "D",
};

// ── Public API ───────────────────────────────────────────────────

/**
 * Get the ScoreBand for a numeric score (0–100).
 * Returns the D band for null/undefined/NaN/out-of-range values.
 */
export function getScoreBand(score: number | null | undefined): ScoreBand {
  if (score == null || isNaN(score)) {
    return SCORE_BANDS[SCORE_BANDS.length - 1]; // D
  }

  const clamped = Math.max(0, Math.min(100, score));

  for (const band of SCORE_BANDS) {
    if (clamped >= band.min) {
      return band;
    }
  }

  return SCORE_BANDS[SCORE_BANDS.length - 1]; // D fallback
}

/**
 * Get the hex colour for a numeric score (0–100).
 *
 * @example
 *   scoreToColour(89.7)  // "#10B981" (A+ emerald)
 *   scoreToColour(42)    // "#F59E0B" (C+ amber)
 *   scoreToColour(null)  // "#EF4444" (D red)
 */
export function scoreToColour(score: number | null | undefined): string {
  return getScoreBand(score).colour;
}

/**
 * Get the background colour (with opacity) for a numeric score.
 * Suitable for card backgrounds and badge fills in dark mode.
 */
export function scoreToBgColour(score: number | null | undefined): string {
  return getScoreBand(score).bgColour;
}

/**
 * Get the grade letter for a numeric score (0–100).
 *
 * @example
 *   scoreToGrade(89.7)  // "A+"
 *   scoreToGrade(42)    // "C+"
 */
export function scoreToGrade(score: number | null | undefined): Grade {
  return getScoreBand(score).grade;
}

/**
 * Get the CSS key suffix for a numeric score.
 *
 * @example
 *   scoreToCssKey(89.7)  // "a-plus"
 *   scoreToCssKey(42)    // "c-plus"
 */
export function scoreToCssKey(score: number | null | undefined): string {
  return getScoreBand(score).cssKey;
}

/**
 * Get the hex colour for a grade string.
 * Handles various formats: "A+", "a+", "A_PLUS", etc.
 *
 * @example
 *   gradeToColour('A+')  // "#10B981"
 *   gradeToColour('D')   // "#EF4444"
 */
export function gradeToColour(grade: string | null | undefined): string {
  if (!grade) return SCORE_BANDS[SCORE_BANDS.length - 1].colour;
  const normalised = GRADE_ALIASES[grade.trim()] ?? "D";
  return GRADE_TO_BAND.get(normalised)?.colour ?? "#EF4444";
}

/**
 * Get the background colour for a grade string.
 */
export function gradeToBgColour(grade: string | null | undefined): string {
  if (!grade) return SCORE_BANDS[SCORE_BANDS.length - 1].bgColour;
  const normalised = GRADE_ALIASES[grade.trim()] ?? "D";
  return GRADE_TO_BAND.get(normalised)?.bgColour ?? "rgba(239, 68, 68, 0.20)";
}

/**
 * Get the Tailwind CSS class name for a grade badge.
 *
 * @example
 *   gradeToClass('A+')  // "grade-a-plus"
 *   gradeToClass('S')   // "grade-s"
 */
export function gradeToClass(grade: string | null | undefined): string {
  if (!grade) return "grade-d";
  const normalised = GRADE_ALIASES[grade.trim()] ?? "D";
  const band = GRADE_TO_BAND.get(normalised);
  return band ? `grade-${band.cssKey}` : "grade-d";
}

/**
 * Get the human-readable label for a grade.
 *
 * @example
 *   gradeToLabel('A+')  // "A+ — Exceptional"
 */
export function gradeToLabel(grade: string | null | undefined): string {
  if (!grade) return "D — Poor";
  const normalised = GRADE_ALIASES[grade.trim()] ?? "D";
  return GRADE_TO_BAND.get(normalised)?.label ?? "D — Poor";
}

// ── Chart palette ────────────────────────────────────────────────

/**
 * Colour palette for multi-player chart overlays.
 * Supports up to 4 players (the compare page max).
 */
export const CHART_COLOURS = [
  "#d4d4dc", // Chrome (dark UI)
  "#F59E0B", // Amber
  "#10B981", // Emerald
  "#EF4444", // Red
] as const;

/**
 * Get the chart colour for a player index (0-based).
 * Wraps around if index exceeds the palette size.
 */
export function chartColour(index: number): string {
  return CHART_COLOURS[index % CHART_COLOURS.length];
}

/**
 * Semi-transparent version of the chart colour (for polygon fills).
 */
export function chartColourAlpha(index: number, alpha: number = 0.25): string {
  const hex = chartColour(index);
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ── Cricket-specific semantic colours ────────────────────────────

export const CRICKET_COLOURS = {
  dot: "#64748B",
  single: "#9ca3af",
  boundary: "#22C55E",
  six: "#FFD700",
  wicket: "#EF4444",
} as const;

/**
 * Get the colour for a delivery outcome.
 */
export function deliveryColour(
  runs: number,
  isWicket: boolean = false,
): string {
  if (isWicket) return CRICKET_COLOURS.wicket;
  if (runs === 0) return CRICKET_COLOURS.dot;
  if (runs === 6) return CRICKET_COLOURS.six;
  if (runs === 4) return CRICKET_COLOURS.boundary;
  return CRICKET_COLOURS.single;
}

// ── Dominance gauge colour ───────────────────────────────────────

/**
 * Get a colour for matchup edge (cool neutrals = bowler-leaning, amber/orange = batter side).
 * Avoids red/green-only encoding for colour-vision accessibility.
 */
export function dominanceColour(value: number | null | undefined): string {
  const score = matchupEdgeScore(value);
  if (score == null) return "#64748B";
  if (score < 36) return "#404040";
  if (score < 45) return "#737373";
  if (score < 56) return "#a3a3a3";
  if (score < 65) return "#EA580C";
  return "#D97706";
}

/**
 * Get a text description for a dominance index value.
 */
export function dominanceLabel(value: number | null | undefined): string {
  return matchupEdgeTier(value);
}
