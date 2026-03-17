/**
 * PlayerCard — compact card displaying a player summary with score bars.
 *
 * Used in search results, leaderboard rows (expanded), home page quick
 * lists, and anywhere a player needs a visual summary. Shows:
 *   - Name, country (with flag), archetype badge
 *   - Summary stats (innings, runs/wickets, SR/economy, average)
 *   - Three mini score bars (Acceleration/Power/Control or Accuracy/Control/Threat)
 *   - Overall grade badge
 *   - Provisional indicator if applicable
 *   - Action buttons (View Profile, + Compare)
 *
 * Variants:
 *   - "full"    — all details, used on search results page
 *   - "compact" — smaller card for leaderboard preview, home page lists
 *   - "mini"    — just name + grade + one-line stats, for autocomplete dropdown
 *
 * Usage:
 *   <PlayerCard player={playerSummary} />
 *   <PlayerCard player={playerSummary} variant="compact" />
 *   <PlayerCard player={playerSummary} variant="mini" onSelect={handleSelect} />
 *   <PlayerCard player={playerSummary} onCompare={handleCompare} />
 */

import { Link } from 'react-router-dom';
import type { PlayerSummary } from '@/api/types';
import GradeBadge from '@/components/GradeBadge';
import ScoreBar, { ScoreBarMini } from '@/components/ScoreBar';
import { fmtInt, fmtSR, fmtEcon, fmtAvg, fmtScore, countryFlag, fmtRole } from '@/lib/format';

// ── Props ────────────────────────────────────────────────────────

interface PlayerCardProps {
  /** The player summary data to render. */
  player: PlayerSummary;
  /**
   * Display variant:
   * - "full" (default): full card with all details and score bars
   * - "compact": smaller card with mini score bars
   * - "mini": single-line for autocomplete dropdowns and lists
   */
  variant?: 'full' | 'compact' | 'mini';
  /** Rank number to display (e.g. in leaderboard context). */
  rank?: number;
  /** Callback when "Compare" button is clicked. */
  onCompare?: (player: PlayerSummary) => void;
  /** Callback when the card itself is clicked (e.g. for autocomplete selection). */
  onSelect?: (player: PlayerSummary) => void;
  /** Whether this player is currently selected for comparison. */
  isCompareSelected?: boolean;
  /** Whether to show the "Compare" button. Default: true for full variant. */
  showCompareButton?: boolean;
  /** Whether to show the "View Profile" link. Default: true for full/compact. */
  showProfileLink?: boolean;
  /** Whether to link the player name to their profile. Default: true. */
  linkName?: boolean;
  /** Whether the card is highlighted (e.g. keyboard navigation in autocomplete). */
  highlighted?: boolean;
  /** Additional CSS classes for the outer container. */
  className?: string;
}

// ── Helpers ──────────────────────────────────────────────────────

function isBowler(player: PlayerSummary): boolean {
  return player.role === 'bowl';
}

function primaryStat(player: PlayerSummary): string {
  if (isBowler(player)) {
    return `${fmtInt(player.total_runs, '0')} wkts`;
  }
  return `${fmtInt(player.total_runs, '0')} runs`;
}

function rateStat(player: PlayerSummary): string {
  if (isBowler(player)) {
    return `Econ ${fmtEcon(player.career_sr)}`;
  }
  return `SR ${fmtSR(player.career_sr)}`;
}

function avgStat(player: PlayerSummary): string {
  if (isBowler(player)) {
    return `SR ${fmtSR(player.career_avg)}`;
  }
  return `Avg ${fmtAvg(player.career_avg)}`;
}

function inningsStat(player: PlayerSummary): string {
  if (isBowler(player)) {
    return `${fmtInt(player.innings_count, '0')} matches`;
  }
  return `${fmtInt(player.innings_count, '0')} innings`;
}

// ── Component ────────────────────────────────────────────────────

export default function PlayerCard({
  player,
  variant = 'full',
  rank,
  onCompare,
  onSelect,
  isCompareSelected = false,
  showCompareButton,
  showProfileLink,
  linkName = true,
  highlighted = false,
  className = '',
}: PlayerCardProps) {
  // Default showCompareButton and showProfileLink based on variant
  const shouldShowCompare = showCompareButton ?? (variant === 'full' && !!onCompare);
  const shouldShowProfile = showProfileLink ?? (variant !== 'mini');

  const flag = countryFlag(player.country);
  const labels = getScoreLabels(player);

  // ── Mini variant ───────────────────────────────────────────
  if (variant === 'mini') {
    return (
      <div
        className={`autocomplete-item flex items-center gap-3 ${highlighted ? 'highlighted' : ''} ${className}`}
        onClick={() => onSelect?.(player)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect?.(player);
          }
        }}
        role="option"
        aria-selected={highlighted}
        tabIndex={0}
      >
        {/* Rank (if provided) */}
        {rank != null && (
          <span className="text-text-muted text-xs font-score tabular-nums w-6 text-right shrink-0">
            {rank}
          </span>
        )}

        {/* Name + country */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium text-text-primary truncate">
              {player.name}
            </span>
            {flag && (
              <span className="text-xs shrink-0" title={player.country}>
                {flag}
              </span>
            )}
            {player.is_provisional && (
              <span className="provisional-badge text-[10px] px-1 py-0">!</span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <span>{player.archetype || fmtRole(player.role)}</span>
            <span className="text-text-muted/50">·</span>
            <span>{inningsStat(player)}</span>
            <span className="text-text-muted/50">·</span>
            <span>{primaryStat(player)}</span>
          </div>
        </div>

        {/* Grade */}
        <GradeBadge grade={player.grade_overall} size="xs" />

        {/* Overall score */}
        <span
          className="text-xs font-score tabular-nums text-text-secondary w-8 text-right shrink-0"
        >
          {fmtScore(player.overall_score, '')}
        </span>
      </div>
    );
  }

  // ── Compact variant ────────────────────────────────────────
  if (variant === 'compact') {
    const nameContent = (
      <span className="text-sm font-semibold text-text-primary truncate">
        {player.name}
      </span>
    );

    return (
      <div
        className={`card flex items-center gap-3 px-3 py-2.5 ${className}`}
      >
        {/* Rank */}
        {rank != null && (
          <span className="text-text-muted text-sm font-score tabular-nums w-8 text-right shrink-0">
            {rank}
          </span>
        )}

        {/* Name + country + archetype */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            {linkName ? (
              <Link
                to={`/player/${player.id}`}
                className="hover:text-primary transition-colors truncate"
              >
                {nameContent}
              </Link>
            ) : (
              nameContent
            )}
            {flag && (
              <span className="text-xs shrink-0" title={player.country}>
                {flag}
              </span>
            )}
            {player.is_provisional && (
              <span className="provisional-badge text-[10px]">Prov</span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-text-muted mt-0.5">
            {player.archetype && (
              <>
                <span className="archetype-badge text-[10px] px-1.5 py-0">
                  {player.archetype}
                </span>
              </>
            )}
            <span>{inningsStat(player)}</span>
            <span className="text-text-muted/50">·</span>
            <span>{primaryStat(player)}</span>
          </div>
        </div>

        {/* Mini score bars */}
        <div className="flex flex-col gap-0.5 shrink-0">
          <ScoreBarMini value={player.score_1} width={40} />
          <ScoreBarMini value={player.score_2} width={40} />
          <ScoreBarMini value={player.score_3} width={40} />
        </div>

        {/* Grade */}
        <GradeBadge grade={player.grade_overall} size="sm" />

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          {shouldShowProfile && (
            <Link
              to={`/player/${player.id}`}
              className="btn-ghost btn-sm text-xs"
              title="View profile"
            >
              →
            </Link>
          )}
          {shouldShowCompare && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onCompare?.(player);
              }}
              className={`btn-sm text-xs ${
                isCompareSelected
                  ? 'btn-primary'
                  : 'btn-ghost'
              }`}
              title={isCompareSelected ? 'Remove from comparison' : 'Add to comparison'}
            >
              {isCompareSelected ? '✓' : '+'}
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Full variant (default) ─────────────────────────────────
  const nameContent = (
    <span className="text-lg font-bold text-text-primary">
      {player.name}
    </span>
  );

  return (
    <div className={`card p-4 animate-fade-in ${className}`}>
      {/* Header row: name + country + archetype */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {rank != null && (
              <span className="text-text-muted text-sm font-score tabular-nums">
                #{rank}
              </span>
            )}
            {linkName ? (
              <Link
                to={`/player/${player.id}`}
                className="hover:text-primary transition-colors"
              >
                {nameContent}
              </Link>
            ) : (
              nameContent
            )}
            {flag && (
              <span className="text-base" title={player.country}>
                {flag}
              </span>
            )}
            <span className="text-sm text-text-secondary">
              {player.country}
            </span>
          </div>

          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {player.archetype && (
              <span className="archetype-badge">
                {player.archetype}
              </span>
            )}
            {player.is_provisional && (
              <span className="provisional-badge">
                Provisional ({player.innings_count} {isBowler(player) ? 'matches' : 'innings'})
              </span>
            )}
          </div>
        </div>

        {/* Overall grade */}
        <div className="flex flex-col items-center gap-1 shrink-0">
          <span className="text-xs text-text-muted uppercase tracking-wider">Overall</span>
          <GradeBadge grade={player.grade_overall} size="lg" />
        </div>
      </div>

      {/* Stats summary row */}
      <div className="flex items-center gap-3 text-sm text-text-secondary mb-4 flex-wrap">
        <span>{inningsStat(player)}</span>
        <span className="text-text-muted/50">·</span>
        <span>{primaryStat(player)}</span>
        <span className="text-text-muted/50">·</span>
        <span>{rateStat(player)}</span>
        <span className="text-text-muted/50">·</span>
        <span>{avgStat(player)}</span>
      </div>

      {/* Score bars */}
      <div className="space-y-2 mb-4">
        <ScoreBar
          value={player.score_1}
          label={labels.s1}
          labelShort={labels.s1Short}
          size="md"
          variant="full"
          labelWidth="w-28"
          showGrade
          grade={undefined}
        />
        <ScoreBar
          value={player.score_2}
          label={labels.s2}
          labelShort={labels.s2Short}
          size="md"
          variant="full"
          labelWidth="w-28"
          showGrade
          grade={undefined}
        />
        <ScoreBar
          value={player.score_3}
          label={labels.s3}
          labelShort={labels.s3Short}
          size="md"
          variant="full"
          labelWidth="w-28"
          showGrade
          grade={undefined}
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-2 border-t border-surface-elevated/50">
        {shouldShowProfile && (
          <Link
            to={`/player/${player.id}`}
            className="btn-primary btn-sm"
          >
            View Profile →
          </Link>
        )}
        {shouldShowCompare && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onCompare?.(player);
            }}
            className={`btn-sm ${
              isCompareSelected
                ? 'btn-danger'
                : 'btn-secondary'
            }`}
          >
            {isCompareSelected ? '✕ Remove' : '+ Compare'}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Skeleton Loading ─────────────────────────────────────────────
// A loading placeholder that matches the card's layout.

interface PlayerCardSkeletonProps {
  variant?: 'full' | 'compact' | 'mini';
  className?: string;
}

export function PlayerCardSkeleton({
  variant = 'full',
  className = '',
}: PlayerCardSkeletonProps) {
  if (variant === 'mini') {
    return (
      <div className={`flex items-center gap-3 px-4 py-3 ${className}`}>
        <div className="flex-1 min-w-0">
          <div className="skeleton-text w-32 mb-1" />
          <div className="skeleton-text w-48 h-3" />
        </div>
        <div className="skeleton w-8 h-5 rounded-md" />
      </div>
    );
  }

  if (variant === 'compact') {
    return (
      <div className={`card flex items-center gap-3 px-3 py-2.5 ${className}`}>
        <div className="flex-1 min-w-0">
          <div className="skeleton-text w-28 mb-1" />
          <div className="skeleton-text w-40 h-3" />
        </div>
        <div className="flex flex-col gap-1 shrink-0">
          <div className="skeleton w-12 h-1.5 rounded-full" />
          <div className="skeleton w-12 h-1.5 rounded-full" />
          <div className="skeleton w-12 h-1.5 rounded-full" />
        </div>
        <div className="skeleton w-8 h-5 rounded-md" />
      </div>
    );
  }

  // Full skeleton
  return (
    <div className={`card p-4 ${className}`}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1">
          <div className="skeleton-title w-40 mb-2" />
          <div className="skeleton w-24 h-5 rounded-full" />
        </div>
        <div className="skeleton w-10 h-10 rounded-md" />
      </div>
      <div className="flex gap-3 mb-4">
        <div className="skeleton-text w-20" />
        <div className="skeleton-text w-20" />
        <div className="skeleton-text w-20" />
      </div>
      <div className="space-y-2 mb-4">
        <div className="skeleton-score-bar" />
        <div className="skeleton-score-bar" />
        <div className="skeleton-score-bar" />
      </div>
      <div className="flex gap-2 pt-2 border-t border-surface-elevated/50">
        <div className="skeleton w-28 h-8 rounded-lg" />
        <div className="skeleton w-24 h-8 rounded-lg" />
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────

function getScoreLabels(player: PlayerSummary): {
  s1: string;
  s2: string;
  s3: string;
  s1Short: string;
  s2Short: string;
  s3Short: string;
} {
  // Use labels from the API if available, otherwise derive from role.
  if (player.score_1_label && player.score_1_label !== 'acceleration') {
    // Trust the API labels
    return {
      s1: capitalise(player.score_1_label),
      s2: capitalise(player.score_2_label),
      s3: capitalise(player.score_3_label),
      s1Short: player.score_1_label.slice(0, 3).toUpperCase(),
      s2Short: player.score_2_label.slice(0, 3).toUpperCase(),
      s3Short: player.score_3_label.slice(0, 3).toUpperCase(),
    };
  }

  if (isBowler(player)) {
    return {
      s1: 'Accuracy',
      s2: 'Control',
      s3: 'Threat',
      s1Short: 'ACC',
      s2Short: 'CTL',
      s3Short: 'THR',
    };
  }

  return {
    s1: 'Acceleration',
    s2: 'Power',
    s3: 'Control',
    s1Short: 'ACL',
    s2Short: 'POW',
    s3Short: 'CTL',
  };
}

function capitalise(str: string): string {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}
