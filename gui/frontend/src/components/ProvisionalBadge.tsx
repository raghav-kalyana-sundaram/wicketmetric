/**
 * ProvisionalBadge — warning indicator for provisional (low-sample) players.
 *
 * Displays a compact badge alerting the user that a player's ratings
 * are based on a small sample size and may not be stable. Provisional
 * status is determined by the pipeline when a player has fewer than
 * the minimum innings/spells threshold (typically 10).
 *
 * Features:
 *   - Multiple size variants (xs, sm, md, lg)
 *   - Compact (icon only) and full (icon + text) modes
 *   - Tooltip with explanation on hover
 *   - Animated pulse option for emphasis
 *   - Optional innings count display
 *   - Accessible: uses role="status" with aria-label
 *   - Light/dark mode support via Tailwind classes
 *
 * Usage:
 *   <ProvisionalBadge />
 *   <ProvisionalBadge innings={3} />
 *   <ProvisionalBadge size="lg" variant="full" />
 *   <ProvisionalBadge variant="icon" pulse />
 *   {player.is_provisional && <ProvisionalBadge innings={player.innings_count} />}
 *
 * Follows gui.md § 7.1 Component Library — `<ProvisionalBadge>`.
 */

import { useState, useRef, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';

// ── Size configuration ───────────────────────────────────────────

const SIZE_CONFIG = {
  xs: {
    container: 'px-1.5 py-0.5 text-[10px] leading-none gap-0.5',
    icon: 10,
    tooltip: 'text-[10px] max-w-[180px]',
  },
  sm: {
    container: 'px-2 py-0.5 text-xs leading-none gap-1',
    icon: 12,
    tooltip: 'text-xs max-w-[220px]',
  },
  md: {
    container: 'px-2.5 py-1 text-xs leading-none gap-1',
    icon: 14,
    tooltip: 'text-xs max-w-[240px]',
  },
  lg: {
    container: 'px-3 py-1.5 text-sm leading-none gap-1.5',
    icon: 16,
    tooltip: 'text-sm max-w-[260px]',
  },
} as const;

type BadgeSize = keyof typeof SIZE_CONFIG;

// ── Props ────────────────────────────────────────────────────────

interface ProvisionalBadgeProps {
  /**
   * Variant:
   * - "full" (default): icon + "Provisional" text
   * - "compact": icon + "Prov." text
   * - "icon": icon only (with tooltip on hover)
   * - "text": text only, no icon
   * - "detailed": icon + "Provisional (N innings)" text
   */
  variant?: 'full' | 'compact' | 'icon' | 'text' | 'detailed';
  /** Size variant. Default: "sm". */
  size?: BadgeSize;
  /** Number of innings (for the detailed variant and tooltip). */
  innings?: number | null;
  /** Minimum innings threshold to explain in tooltip. Default: 10. */
  minInnings?: number;
  /** Whether to show a subtle pulse animation. Default: false. */
  pulse?: boolean;
  /** Whether to show a tooltip on hover. Default: true. */
  showTooltip?: boolean;
  /** Override the tooltip text. */
  tooltipText?: string;
  /** Additional CSS classes for the outer container. */
  className?: string;
  /** Shape variant. Default: "pill". */
  shape?: 'pill' | 'badge';
}

// ── Component ────────────────────────────────────────────────────

export default function ProvisionalBadge({
  variant = 'full',
  size = 'sm',
  innings,
  minInnings = 10,
  pulse = false,
  showTooltip = true,
  tooltipText,
  className = '',
  shape = 'pill',
}: ProvisionalBadgeProps) {
  const [isTooltipVisible, setIsTooltipVisible] = useState(false);
  const [tooltipPos, setTooltipPos] = useState<'above' | 'below'>('above');
  const containerRef = useRef<HTMLSpanElement>(null);
  const tooltipTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const config = SIZE_CONFIG[size];
  const roundedClass = shape === 'pill' ? 'rounded-full' : 'rounded-md';

  // Determine the display text based on variant
  let displayText = '';
  switch (variant) {
    case 'full':
      displayText = 'Provisional';
      break;
    case 'compact':
      displayText = 'Prov.';
      break;
    case 'detailed':
      displayText =
        innings != null
          ? `Provisional (${innings} inn.)`
          : 'Provisional';
      break;
    case 'text':
      displayText = 'Provisional';
      break;
    case 'icon':
      displayText = '';
      break;
  }

  const showIcon = variant !== 'text';
  const showText = variant !== 'icon';

  // Build tooltip content
  const defaultTooltip =
    innings != null
      ? `Provisional rating — based on only ${innings} innings (minimum ${minInnings} required for full confidence). Ratings may change significantly with more data.`
      : `Provisional rating — based on fewer than ${minInnings} innings. Ratings may change significantly with more data.`;

  const tooltip = tooltipText ?? defaultTooltip;

  // Tooltip positioning: check if there's room above
  useEffect(() => {
    if (isTooltipVisible && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const spaceAbove = rect.top;
      setTooltipPos(spaceAbove > 80 ? 'above' : 'below');
    }
  }, [isTooltipVisible]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (tooltipTimeoutRef.current) {
        clearTimeout(tooltipTimeoutRef.current);
      }
    };
  }, []);

  const handleMouseEnter = () => {
    if (!showTooltip) return;
    tooltipTimeoutRef.current = setTimeout(() => {
      setIsTooltipVisible(true);
    }, 200);
  };

  const handleMouseLeave = () => {
    if (tooltipTimeoutRef.current) {
      clearTimeout(tooltipTimeoutRef.current);
      tooltipTimeoutRef.current = null;
    }
    setIsTooltipVisible(false);
  };

  const handleFocus = () => {
    if (showTooltip) setIsTooltipVisible(true);
  };

  const handleBlur = () => {
    setIsTooltipVisible(false);
  };

  return (
    <span
      ref={containerRef}
      className={[
        'provisional-badge inline-flex items-center font-medium select-none relative',
        'bg-warning/20 text-warning',
        config.container,
        roundedClass,
        pulse ? 'animate-pulse-score' : '',
        showTooltip ? 'cursor-help' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      role="status"
      aria-label={
        innings != null
          ? `Provisional: ${innings} innings (minimum ${minInnings})`
          : `Provisional rating`
      }
      tabIndex={showTooltip ? 0 : undefined}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onFocus={handleFocus}
      onBlur={handleBlur}
    >
      {/* Icon */}
      {showIcon && (
        <AlertTriangle
          size={config.icon}
          className="shrink-0"
          aria-hidden="true"
        />
      )}

      {/* Text label */}
      {showText && displayText && (
        <span className="truncate">{displayText}</span>
      )}

      {/* Tooltip */}
      {showTooltip && isTooltipVisible && (
        <span
          className={[
            'absolute z-50 pointer-events-none rounded-lg px-3 py-2',
            'bg-surface-elevated text-text-primary shadow-lg',
            'border border-surface-elevated',
            config.tooltip,
            'leading-relaxed font-normal',
            // Position
            tooltipPos === 'above'
              ? 'bottom-full mb-2 left-1/2 -translate-x-1/2'
              : 'top-full mt-2 left-1/2 -translate-x-1/2',
            // Fade in
            'animate-fade-in',
          ]
            .filter(Boolean)
            .join(' ')}
          role="tooltip"
        >
          {tooltip}
          {/* Arrow */}
          <span
            className={[
              'absolute left-1/2 -translate-x-1/2 w-2 h-2 rotate-45',
              'bg-surface-elevated border-surface-elevated',
              tooltipPos === 'above'
                ? 'top-full -mt-1 border-b border-r'
                : 'bottom-full -mb-1 border-t border-l',
            ].join(' ')}
            aria-hidden="true"
          />
        </span>
      )}
    </span>
  );
}

// ── Variant: ProvisionalBanner ───────────────────────────────────
// A wider banner variant for use at the top of profile pages to
// prominently warn about provisional status.

interface ProvisionalBannerProps {
  /** Number of innings played. */
  innings?: number | null;
  /** Minimum innings threshold. Default: 10. */
  minInnings?: number;
  /** Additional CSS classes. */
  className?: string;
  /** Custom message override. */
  message?: string;
}

export function ProvisionalBanner({
  innings,
  minInnings = 10,
  className = '',
  message,
}: ProvisionalBannerProps) {
  const defaultMessage =
    innings != null
      ? `This player has only ${innings} innings — ratings are provisional and may change significantly as more data becomes available. A minimum of ${minInnings} innings is needed for stable ratings.`
      : `This player has fewer than ${minInnings} innings — ratings are provisional and may change significantly.`;

  return (
    <div
      className={[
        'flex items-start gap-3 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3',
        className,
      ].join(' ')}
      role="alert"
    >
      <AlertTriangle
        size={18}
        className="shrink-0 mt-0.5 text-warning"
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="text-sm font-medium text-warning">
          Provisional Rating
        </p>
        <p className="text-xs text-text-secondary mt-0.5 leading-relaxed">
          {message ?? defaultMessage}
        </p>
      </div>
    </div>
  );
}

// ── Variant: ProvisionalInline ───────────────────────────────────
// Minimal inline text indicator — just "⚠ Provisional" in warning colour.
// For use inside table cells and compact layouts.

interface ProvisionalInlineProps {
  innings?: number | null;
  className?: string;
}

export function ProvisionalInline({
  innings,
  className = '',
}: ProvisionalInlineProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-warning text-xs ${className}`}
      title={
        innings != null
          ? `Provisional: ${innings} innings`
          : 'Provisional rating'
      }
    >
      <AlertTriangle size={10} className="shrink-0" aria-hidden="true" />
      <span>Prov.</span>
      {innings != null && (
        <span className="text-text-muted">({innings})</span>
      )}
    </span>
  );
}
