/**
 * FormSparkline — compact inline time-series chart for form indication.
 *
 * Renders a tiny SVG line chart (~100px wide) showing a player's recent
 * form trajectory. Designed for embedding inside leaderboard rows,
 * search result cards, and player cards where space is limited.
 *
 * Features:
 *   - Smooth polyline connecting data points
 *   - Optional gradient fill beneath the line
 *   - Colour derived from the trend (improving = green, declining = amber, stable = neutral grey)
 *   - Hover tooltip showing the value at each point
 *   - Accessible: uses role="img" with aria-label
 *   - Graceful handling of null/empty data (renders a flat grey line)
 *
 * Usage:
 *   <FormSparkline data={[72, 68, 75, 80, 78, 82]} />
 *   <FormSparkline data={formPoints.map(p => p.composite)} width={120} height={32} />
 *   <FormSparkline data={[]} placeholder="No form data" />
 *
 * Follows gui.md § 7.1 Component Library — `<FormSparkline>`.
 */

import { useMemo, useRef, useState } from "react";
import { detectTrend, type Trend } from "@/components/formSparklineUtils";

// ── Props ────────────────────────────────────────────────────────

interface FormSparklineProps {
  /** Array of numeric values (0–100 scale typically). Nulls are skipped. */
  data: (number | null | undefined)[];
  /** SVG width in pixels. Default: 100. */
  width?: number;
  /** SVG height in pixels. Default: 28. */
  height?: number;
  /** Stroke width of the line. Default: 1.5. */
  strokeWidth?: number;
  /** Whether to show the gradient fill beneath the line. Default: true. */
  showFill?: boolean;
  /** Whether to show a dot on the latest data point. Default: true. */
  showEndDot?: boolean;
  /** Whether to show dots on hover. Default: true. */
  interactive?: boolean;
  /** Override line colour. If not provided, derived from trend. */
  colour?: string;
  /** Placeholder text when there's no data. Default: "—". */
  placeholder?: string;
  /** Additional CSS classes for the container. */
  className?: string;
  /** Accessible label. */
  ariaLabel?: string;
  /** Minimum Y value for the scale. Default: auto from data. */
  yMin?: number;
  /** Maximum Y value for the scale. Default: auto from data. */
  yMax?: number;
  /**
   * When true, style as a miniature of the profile "Form Tracker" chart:
   * fixed 0–100 scale, neutral line, gradient fill, optional median line at 50.
   */
  variant?: 'default' | 'formTracker';
  /** When variant="formTracker", show a faint median (50) reference line. */
  showMedianLine?: boolean;
}

export type { Trend } from "@/components/formSparklineUtils";
export { detectTrend, detectTrendFromLastN } from "@/components/formSparklineUtils";

function trendColour(trend: Trend): string {
  switch (trend) {
    case 'up':
      return '#34D399'; // Emerald — up without UI chrome blue
    case 'down':
      return '#F59E0B'; // Amber
    case 'stable':
      return '#94A3B8'; // Neutral slate
  }
}

// ── Component ────────────────────────────────────────────────────

const FORM_TRACKER_NEUTRAL = '#a3a3a3';

export default function FormSparkline({
  data,
  width = 100,
  height = 28,
  strokeWidth = 1.5,
  showFill = true,
  showEndDot = true,
  interactive = true,
  colour,
  placeholder = '—',
  className = '',
  ariaLabel,
  yMin: yMinProp,
  yMax: yMaxProp,
  variant = 'default',
  showMedianLine = false,
}: FormSparklineProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const isFormTrackerVariant = variant === 'formTracker';
  const effectiveYMin = isFormTrackerVariant ? 0 : yMinProp;
  const effectiveYMax = isFormTrackerVariant ? 100 : yMaxProp;
  const effectiveColour = isFormTrackerVariant ? FORM_TRACKER_NEUTRAL : colour;
  const effectiveShowFill = isFormTrackerVariant ? true : showFill;
  const effectiveShowMedian = showMedianLine || (isFormTrackerVariant && showMedianLine !== false);

  // Filter out nulls and build clean values array
  const cleanData = useMemo(() => {
    const result: { index: number; value: number }[] = [];
    for (let i = 0; i < data.length; i++) {
      const v = data[i];
      if (v != null && isFinite(v)) {
        result.push({ index: i, value: v });
      }
    }
    return result;
  }, [data]);

  const values = useMemo(() => cleanData.map((d) => d.value), [cleanData]);

  // Compute scale
  const { yMin, yMax } = useMemo(() => {
    if (values.length === 0) return { yMin: effectiveYMin ?? 0, yMax: effectiveYMax ?? 100 };
    if (effectiveYMin != null && effectiveYMax != null)
      return { yMin: effectiveYMin, yMax: effectiveYMax };
    const dataMin = Math.min(...values);
    const dataMax = Math.max(...values);
    const range = dataMax - dataMin || 10;
    const padding = range * 0.1;
    return {
      yMin: yMinProp ?? Math.max(0, dataMin - padding),
      yMax: yMaxProp ?? Math.min(100, dataMax + padding),
    };
  }, [values, yMinProp, yMaxProp, effectiveYMin, effectiveYMax]);

  const trend = useMemo(() => detectTrend(values), [values]);
  const lineColour = effectiveColour ?? colour ?? trendColour(trend);

  // Compute points
  const points = useMemo(() => {
    if (cleanData.length === 0) return [];

    const padX = 2;
    const padY = 3;
    const usableWidth = width - padX * 2;
    const usableHeight = height - padY * 2;
    const yRange = yMax - yMin || 1;

    return cleanData.map((d, i) => {
      const x =
        cleanData.length > 1
          ? padX + (i / (cleanData.length - 1)) * usableWidth
          : padX + usableWidth / 2;
      const y = padY + usableHeight - ((d.value - yMin) / yRange) * usableHeight;
      return { x, y, value: d.value, originalIndex: d.index };
    });
  }, [cleanData, width, height, yMin, yMax]);

  // Build SVG path
  const linePath = useMemo(() => {
    if (points.length < 2) return '';
    return points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  }, [points]);

  // Build fill path (closed polygon for gradient area)
  const fillPath = useMemo(() => {
    if (points.length < 2 || !effectiveShowFill) return '';
    const bottomY = height - 1;
    const pathStart = `M ${points[0].x.toFixed(1)} ${bottomY}`;
    const lineSegments = points
      .map((p) => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join(' ');
    const pathEnd = `L ${points[points.length - 1].x.toFixed(1)} ${bottomY} Z`;
    return `${pathStart} ${lineSegments} ${pathEnd}`;
  }, [points, height, effectiveShowFill]);

  // Gradient IDs need to be unique per instance
  const gradientId = useMemo(() => `sparkline-grad-${Math.random().toString(36).slice(2, 8)}`, []);

  // ── Empty state ────────────────────────────────────────────
  if (cleanData.length === 0) {
    return (
      <span
        className={`inline-flex items-center text-text-muted text-xs ${className}`}
        aria-label={ariaLabel ?? 'No form data available'}
        role="img"
      >
        {placeholder}
      </span>
    );
  }

  // Single point — render a dot
  if (points.length === 1) {
    return (
      <svg
        ref={svgRef}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className={`inline-block ${className}`}
        role="img"
        aria-label={ariaLabel ?? `Form: ${values[0]?.toFixed(0)}`}
      >
        <circle
          cx={points[0].x}
          cy={points[0].y}
          r={3}
          fill={lineColour}
        />
      </svg>
    );
  }

  // ── Hover interaction ──────────────────────────────────────
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!interactive || points.length < 2) return;
    const svg = svgRef.current;
    if (!svg) return;

    const rect = svg.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;

    // Find the closest point
    let closest = 0;
    let closestDist = Infinity;
    for (let i = 0; i < points.length; i++) {
      const dist = Math.abs(points[i].x - mouseX);
      if (dist < closestDist) {
        closestDist = dist;
        closest = i;
      }
    }
    setHoveredIndex(closest);
  };

  const handleMouseLeave = () => {
    setHoveredIndex(null);
  };

  const lastPoint = points[points.length - 1];
  const hoveredPoint = hoveredIndex !== null ? points[hoveredIndex] : null;

  const label =
    ariaLabel ??
    `Form trend: ${trend === 'up' ? 'improving' : trend === 'down' ? 'declining' : 'stable'}. Latest: ${lastPoint.value.toFixed(0)}`;

  return (
    <span className={`inline-flex items-center relative ${className}`}>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="inline-block cursor-crosshair"
        role="img"
        aria-label={label}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {/* Median reference line (mini Form Tracker style) */}
        {effectiveShowMedian && isFormTrackerVariant && (
          <line
            x1={2}
            y1={3 + (height - 6) / 2}
            x2={width - 2}
            y2={3 + (height - 6) / 2}
            stroke="#64748B"
            strokeDasharray="2 2"
            strokeOpacity={0.4}
          />
        )}

        {/* Gradient definition */}
        {effectiveShowFill && (
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColour} stopOpacity={0.3} />
              <stop offset="100%" stopColor={lineColour} stopOpacity={0.02} />
            </linearGradient>
          </defs>
        )}

        {/* Fill area (gradient under line) */}
        {fillPath && effectiveShowFill && (
          <path d={fillPath} fill={`url(#${gradientId})`} />
        )}

        {/* Line */}
        <path
          d={linePath}
          fill="none"
          stroke={lineColour}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* End dot */}
        {showEndDot && (
          <circle
            cx={lastPoint.x}
            cy={lastPoint.y}
            r={2}
            fill={lineColour}
            stroke="none"
          />
        )}

        {/* Hover dot */}
        {hoveredPoint && (
          <>
            {/* Vertical guide line */}
            <line
              x1={hoveredPoint.x}
              y1={2}
              x2={hoveredPoint.x}
              y2={height - 2}
              stroke={lineColour}
              strokeWidth={0.5}
              strokeOpacity={0.4}
              strokeDasharray="2 2"
            />
            {/* Hover dot */}
            <circle
              cx={hoveredPoint.x}
              cy={hoveredPoint.y}
              r={3}
              fill={lineColour}
              stroke="white"
              strokeWidth={1}
            />
          </>
        )}
      </svg>

      {/* Tooltip */}
      {hoveredPoint && interactive && (
        <span
          className="absolute z-50 pointer-events-none whitespace-nowrap rounded bg-surface-elevated px-1.5 py-0.5 text-[10px] font-score tabular-nums text-text-primary shadow-lg"
          style={{
            left: `${Math.min(hoveredPoint.x, width - 30)}px`,
            bottom: `${height + 2}px`,
            transform: 'translateX(-50%)',
          }}
        >
          {hoveredPoint.value.toFixed(1)}
        </span>
      )}
    </span>
  );
}

// ── Variant: FormSparklineMini ───────────────────────────────────
// Even more compact — no hover, no fill, just the line. For table cells.

interface FormSparklineMiniProps {
  data: (number | null | undefined)[];
  width?: number;
  height?: number;
  colour?: string;
  className?: string;
}

export function FormSparklineMini({
  data,
  width = 60,
  height = 16,
  colour,
  className = '',
}: FormSparklineMiniProps) {
  return (
    <FormSparkline
      data={data}
      width={width}
      height={height}
      strokeWidth={1}
      showFill={false}
      showEndDot={false}
      interactive={false}
      colour={colour}
      className={className}
    />
  );
}
