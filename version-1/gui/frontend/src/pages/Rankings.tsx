/**
 * Rankings / Leaderboard page — sortable, filterable player rankings.
 *
 * Route: /rankings?role=bat&sort=rating_current&order=desc&country=...&archetype=...&modal_slot=...
 *   Advanced context (table card): ctx_chase=1, ctx_playoffs=1, ctx_entry=early|death (UI-only until API).
 *
 * Features (from gui.md § 6.4):
 *   - Toggle between Batting and Bowling leaderboards
 *   - Sortable column headers (click to sort, click again to reverse)
 *   - Filters: country, archetype, position/phase group, modal batting slot (1–11),
 *     min innings, provisional,
 *     active vs retired (format-specific recency; default active only)
 *   - Pagination with page size selector
 *   - Checkbox column for selecting players to compare (max 4)
 *   - "Compare Selected" button appears when ≥2 selected
 *   - Each player name links to their profile
 *   - Ratings column: Cur / Ovl header buttons sort by rating_current vs rating_overall
 *   - URL-driven state: all filters/sort/page in query params
 *   - Responsive: horizontal scroll on mobile with sticky first column
 *   - Sticky hover sidebar (lg+): live row stats, page percentiles, form sparkline; keyboard shortcuts
 *   - Touch / coarse pointer: tap row to pin quick summary bar; Full preview modal from sidebar or bar
 *   - Charts card: scatter, form lines, distribution, ranked bars, heatmap (correlation + intensity)
 *
 * Data fetching:
 *   - useBattingRankings() or useBowlingRankings() based on role
 *   - useCountries() and useArchetypes() for filter dropdowns
 *   - useBattingSortColumns() / useBowlingSortColumns() for available sorts
 */

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useSearchParams, useNavigate, Link } from "react-router-dom";
import {
  Trophy,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  SlidersHorizontal,
  Filter,
  GitCompare,
  Check,
  ChevronRight,
  Columns3,
  X,
  Keyboard,
} from "lucide-react";
import GradeBadge from "@/components/GradeBadge";
import PlayerAvatar from "@/components/PlayerAvatar";
import { ScoreBarMini } from "@/components/ScoreBar";
import MetricTooltip from "@/components/MetricTooltip";
import MetricColumnHeaderTooltip, {
  rankingsHeaderDefinitionKey,
} from "@/components/MetricColumnHeaderTooltip";
import FormSparkline from "@/components/FormSparkline";
import Pagination from "@/components/Pagination";
import RankingsChartsPanel from "@/components/RankingsChartsPanel";
import AdvancedContextFilters, {
  type InningsPhaseOption,
} from "@/components/AdvancedContextFilters";
import { ApiError, isDatasetUnavailableError } from "@/api/client";
import { PageError } from "@/components/Layout";
import {
  useBattingRankings,
  useBowlingRankings,
  useCountries,
  useArchetypes,
  useBattingSortColumns,
  useBowlingSortColumns,
  useBatterProfile,
  useBowlerProfile,
  useFormBatch,
  usePlayerForm,
} from "@/api/queries";
import { scoreToColour } from "@/lib/colours";
import {
  fmt,
  fmtScore,
  fmtInt,
  fmtSR,
  fmtEcon,
  fmtAvg,
  fmtPct,
  fmtSigned,
  fmtWAR,
  fmtPressureScore,
  fmtMatchupEdge,
  countryFlag,
  countryShort,
  parseIntParam,
  parseBoolParam,
  primaryDisplayRating,
  careerDisplayRating,
} from "@/lib/format";
import type {
  PlayerSummary,
  LeaderboardParams,
  LeaderboardDistributionFilters,
  FormBatchItem,
} from "@/api/types";
import { useFormat } from "@/api/FormatContext";
import { isFranchiseFormat } from "@/api/formatConstants";
import {
  abbreviateTeamName,
  collapseDuplicateTeamLabel,
} from "@/lib/teamDisplay";

// ── Column definitions ───────────────────────────────────────────

interface ColumnDef {
  key: string;
  label: string;
  shortLabel?: string;
  sortKey?: string;
  metricKey?: string;
  /** Glossary key for header mini-card when this column is not an API metric column. */
  headerTooltipKey?: string;
  align?: "left" | "center" | "right";
  /** Width class (Tailwind). */
  width?: string;
  /** If true, this column is hidden on small screens. */
  hideOnMobile?: boolean;
  /** Render function. */
  render: (player: PlayerSummary, rank: number) => React.ReactNode;
}

function columnHeaderLookupKey(
  col: ColumnDef,
  isBowling: boolean,
): string | undefined {
  if (col.metricKey) {
    return rankingsHeaderDefinitionKey(col.metricKey, isBowling) ?? col.metricKey;
  }
  return col.headerTooltipKey;
}

type MetricFormat =
  | "score"
  | "integer"
  | "rate1"
  | "rate2"
  | "signed1"
  | "signed2"
  | "pressure_bat"
  | "pressure_bowl"
  | "matchup_edge"
  | "percent_ratio"
  | "percent"
  | "war";

interface MetricColumnConfig {
  key: string;
  label: string;
  shortLabel?: string;
  width?: string;
  format: MetricFormat;
}

const DEFAULT_EXTRA_COLUMNS: Record<"bat" | "bowl", string[]> = {
  bat: ["war_batting", "clutch_index", "chase_master_index"],
  bowl: ["war_bowling", "clutch_index_bowl", "career_dot_pct"],
};

// ── Leaderboard presets (Phase 2) ─────────────────────────────────

type Density = "compact" | "default" | "expanded";

interface LeaderboardPreset {
  id: string;
  label: string;
  role: "bat" | "bowl";
  sort: string;
  order?: "asc" | "desc";
  phase_group?: string | null;
  position_group?: string | null;
  archetype?: string | null;
}

const LEADERBOARD_PRESETS: LeaderboardPreset[] = [
  { id: "overall", label: "Best overall", role: "bat", sort: "rating_overall", order: "desc" },
  { id: "overall", label: "Best overall", role: "bowl", sort: "rating_overall", order: "desc" },
  { id: "recent_form", label: "Recent form", role: "bat", sort: "peak_window_composite", order: "desc" },
  { id: "recent_form", label: "Recent form", role: "bowl", sort: "peak_window_composite", order: "desc" },
  { id: "power_hitters", label: "Power hitters", role: "bat", sort: "score_power", order: "desc" },
  { id: "anchors", label: "Best anchors", role: "bat", sort: "score_control", order: "desc" },
  { id: "finishers", label: "Best finishers", role: "bat", sort: "score_acceleration", order: "desc", position_group: "lower" },
  { id: "pressure", label: "Best under pressure", role: "bat", sort: "clutch_index", order: "desc" },
  { id: "death", label: "Death specialists", role: "bowl", sort: "rating_overall", order: "desc", phase_group: "death" },
  { id: "powerplay", label: "Powerplay bowlers", role: "bowl", sort: "rating_overall", order: "desc", phase_group: "powerplay" },
  { id: "control_bowl", label: "Control bowlers", role: "bowl", sort: "score_accuracy", order: "desc" },
  { id: "wicket_takers", label: "Wicket takers", role: "bowl", sort: "score_threat", order: "desc" },
];

const METRIC_COLUMN_CONFIG: Record<string, MetricColumnConfig> = {
  war_batting: {
    key: "war_batting",
    label: "WAR",
    shortLabel: "WAR",
    format: "war",
  },
  war_batting_rate: {
    key: "war_batting_rate",
    label: "WAR / 50",
    shortLabel: "WAR/50",
    format: "war",
  },
  clutch_index: {
    key: "clutch_index",
    label: "Pressure Score",
    shortLabel: "Pressure",
    format: "pressure_bat",
  },
  clutch_sr_delta: {
    key: "clutch_sr_delta",
    label: "Pressure SR",
    shortLabel: "dSR",
    format: "signed1",
  },
  chase_master_index: {
    key: "chase_master_index",
    label: "Chase",
    shortLabel: "Chase",
    format: "rate1",
  },
  chase_master_full: {
    key: "chase_master_full",
    label: "Chase+",
    shortLabel: "Chase+",
    format: "rate1",
  },
  flat_track_index: {
    key: "flat_track_index",
    label: "Flat Track",
    shortLabel: "FTI",
    format: "signed2",
  },
  venue_adjusted_composite: {
    key: "venue_adjusted_composite",
    label: "Venue Adj",
    shortLabel: "Venue",
    format: "score",
  },
  selfless_index: {
    key: "selfless_index",
    label: "Selfless",
    shortLabel: "Self",
    format: "rate1",
  },
  anchor_cost_ratio: {
    key: "anchor_cost_ratio",
    label: "Anchor Cost",
    shortLabel: "Anchor",
    format: "rate2",
  },
  avg_balls_to_par: {
    key: "avg_balls_to_par",
    label: "Balls vs Par",
    shortLabel: "BvPar",
    format: "signed1",
  },
  avg_dominance: {
    key: "avg_dominance",
    label: "Matchup Edge",
    shortLabel: "Edge",
    format: "matchup_edge",
  },
  pct_dominant: {
    key: "pct_dominant",
    label: "% Dominant",
    shortLabel: "%Dom",
    format: "percent_ratio",
  },
  matchup_consistency: {
    key: "matchup_consistency",
    label: "Matchup Cons.",
    shortLabel: "Cons.",
    format: "rate2",
  },
  peak_composite_batting: {
    key: "peak_composite_batting",
    label: "Peak Rating",
    shortLabel: "Peak",
    format: "score",
  },
  peak_window_composite: {
    key: "peak_window_composite",
    label: "Peak Window",
    shortLabel: "Peak W",
    format: "score",
  },
  war_bowling: {
    key: "war_bowling",
    label: "WAR",
    shortLabel: "WAR",
    format: "war",
  },
  war_bowling_rate: {
    key: "war_bowling_rate",
    label: "WAR / 50",
    shortLabel: "WAR/50",
    format: "war",
  },
  clutch_index_bowl: {
    key: "clutch_index_bowl",
    label: "Pressure Score",
    shortLabel: "Pressure",
    format: "pressure_bowl",
  },
  flat_track_index_bowl: {
    key: "flat_track_index_bowl",
    label: "Flat Track",
    shortLabel: "FTI",
    format: "signed2",
  },
  avg_dominance_bowl: {
    key: "avg_dominance_bowl",
    label: "Matchup Edge",
    shortLabel: "Edge",
    format: "matchup_edge",
  },
  pct_dominant_bowl: {
    key: "pct_dominant_bowl",
    label: "% Dominant",
    shortLabel: "%Dom",
    format: "percent_ratio",
  },
  bowled_lbw_pct: {
    key: "bowled_lbw_pct",
    label: "Bowled/LBW",
    shortLabel: "B/LBW",
    format: "percent_ratio",
  },
  career_dot_pct: {
    key: "career_dot_pct",
    label: "Dot %",
    shortLabel: "Dot%",
    format: "percent_ratio",
  },
  peak_composite_bowling: {
    key: "peak_composite_bowling",
    label: "Peak Rating",
    shortLabel: "Peak",
    format: "score",
  },
};

const OPTIONAL_METRIC_KEYS: Record<"bat" | "bowl", string[]> = {
  bat: [
    "war_batting",
    "war_batting_rate",
    "clutch_index",
    "clutch_sr_delta",
    "chase_master_index",
    "chase_master_full",
    "flat_track_index",
    "venue_adjusted_composite",
    "selfless_index",
    "anchor_cost_ratio",
    "avg_balls_to_par",
    "avg_dominance",
    "pct_dominant",
    "matchup_consistency",
    "peak_composite_batting",
    "peak_window_composite",
  ],
  bowl: [
    "war_bowling",
    "war_bowling_rate",
    "clutch_index_bowl",
    "career_dot_pct",
    "bowled_lbw_pct",
    "flat_track_index_bowl",
    "avg_dominance_bowl",
    "pct_dominant_bowl",
    "peak_composite_bowling",
    "peak_window_composite",
  ],
};

function formatMetricValue(
  value: number | null | undefined,
  format: MetricFormat,
): string {
  switch (format) {
    case "score":
      return fmtScore(value);
    case "integer":
      return fmtInt(value);
    case "rate1":
      return fmt(value, 1);
    case "rate2":
      return fmt(value, 2);
    case "signed1":
      return fmtSigned(value, 1);
    case "signed2":
      return fmtSigned(value, 2);
    case "pressure_bat":
      return `${fmtPressureScore(value, "bat")}/100`;
    case "pressure_bowl":
      return `${fmtPressureScore(value, "bowl")}/100`;
    case "matchup_edge":
      return `${fmtMatchupEdge(value)}/100`;
    case "percent_ratio":
      return fmtPct(value, 1, true);
    case "percent":
      return fmtPct(value, 1);
    case "war":
      return fmtWAR(value);
    default:
      return fmt(value, 1);
  }
}

function buildMetricColumn(config: MetricColumnConfig): ColumnDef {
  return {
    key: config.key,
    label: config.label,
    shortLabel: config.shortLabel,
    sortKey: config.key,
    metricKey: config.key,
    width: config.width ?? "w-24",
    align: "right",
    render: (player) => (
      <MetricTooltip
        metric={config.key}
        mode="icon"
        iconSize={12}
        className="inline-flex items-center gap-1 justify-end w-full"
      >
        <span className="font-score tabular-nums text-xs">
          {formatMetricValue(player.metrics?.[config.key], config.format)}
        </span>
      </MetricTooltip>
    ),
  };
}

function parseExtraColumns(
  raw: string | null,
  role: "bat" | "bowl",
  availableKeys: Set<string>,
): string[] {
  const requested =
    raw == null
      ? DEFAULT_EXTRA_COLUMNS[role]
      : raw === "none"
        ? []
        : raw
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean);

  return requested.filter((key, index) => {
    if (!availableKeys.has(key)) return false;
    return requested.indexOf(key) === index;
  });
}

function serialiseExtraColumns(keys: string[]): string | null {
  return keys.length > 0 ? keys.join(",") : "none";
}

const COMPACT_HIDE_KEYS = new Set(["archetype", "score_1", "score_2", "score_3"]);

type LeaderboardTrend = "up" | "down" | "stable" | "insufficient";

function computeLeaderboardTrend(
  formPoints: FormBatchItem["form_points"] | undefined,
): { trend: LeaderboardTrend; title: string } {
  const values =
    formPoints
      ?.map((p) => p.composite)
      .filter((c): c is number => c != null) ?? [];

  // Need 10 numeric composites in the *form series* returned by the API — not career innings.
  // Backend sends rolling form points (e.g. last 2 years); sparse careers can have <10 points.
  if (values.length < 10) {
    return {
      trend: "insufficient",
      title:
        "Trend needs 10 rolling-form points (last ~2y in dataset). Career innings can be higher if there are fewer form samples.",
    };
  }

  const latest = values[values.length - 1];
  const tenAgo = values[values.length - 10];
  const delta = latest - tenAgo;

  // User rule: flat if latest is within +/-3 of 10-innings-ago.
  if (Math.abs(delta) <= 3) return { trend: "stable", title: "Flat (within ±3 vs 10 innings ago)" };
  if (delta > 0) return { trend: "up", title: "Rising (last > 10 innings ago)" };
  return { trend: "down", title: "Falling (last < 10 innings ago)" };
}

function getBattingColumns(
  compareIds: Set<string>,
  onCompareToggle: (player: PlayerSummary) => void,
  selectedMetricColumns: ColumnDef[],
  formMap: Map<string, FormBatchItem>,
  density: Density,
  selectedMetricKeys: string[],
  formLoading: boolean,
): ColumnDef[] {
  const optionalKeys = new Set(selectedMetricKeys);
  const hideInCompact = (key: string) => COMPACT_HIDE_KEYS.has(key) || optionalKeys.has(key);
  const showNumericInExpanded = density === "expanded";

  const cols: ColumnDef[] = [
    {
      key: "compare",
      label: "+",
      headerTooltipKey: "leaderboard_compare",
      width: "w-8",
      align: "center",
      render: (player) => (
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onCompareToggle(player);
          }}
          className={`min-h-11 min-w-11 h-7 w-7 sm:min-h-0 sm:min-w-0 sm:h-5 sm:w-5 rounded border flex items-center justify-center transition-colors ${
            compareIds.has(player.id)
              ? "bg-primary border-primary text-white dark:text-background"
              : "border-surface-elevated hover:border-primary text-transparent hover:text-primary/50"
          }`}
          title={
            compareIds.has(player.id)
              ? "Remove from comparison"
              : "Add to comparison"
          }
          aria-label={`${compareIds.has(player.id) ? "Remove" : "Add"} ${player.name} ${compareIds.has(player.id) ? "from" : "to"} comparison`}
        >
          <Check size={12} />
        </button>
      ),
    },
    {
      key: "rank",
      label: "Rk",
      headerTooltipKey: "leaderboard_rank",
      width: "w-10",
      align: "right",
      render: (_player, rank) => (
        <span className="text-text-muted font-score tabular-nums text-xs">
          {rank}
        </span>
      ),
    },
    {
      key: "name",
      label: "Player",
      headerTooltipKey: "leaderboard_player",
      width: "min-w-[10rem]",
      align: "left",
      render: (player) => (
        <span className="flex items-center gap-1.5">
          <span className="font-medium text-text-primary truncate max-w-[9rem]">
            {player.name}
          </span>
          {player.is_provisional && (
            <span
              className="text-[10px] text-warning shrink-0"
              title="Provisional"
            >
              Prov
            </span>
          )}
        </span>
      ),
    },
    {
      key: "team",
      label: "Team",
      shortLabel: "Tm",
      headerTooltipKey: "leaderboard_team",
      width: "min-w-[6rem] max-w-[9rem]",
      align: "left",
      hideOnMobile: true,
      render: (player) => {
        const rawTeam = collapseDuplicateTeamLabel(
          (player.recent_team || "").trim(),
        );
        const label = rawTeam || (player.country || "").trim() || "—";
        const titleParts = [rawTeam || null, player.country].filter(
          (x): x is string => Boolean(x && String(x).trim()),
        );
        const title =
          titleParts.length > 0 ? Array.from(new Set(titleParts)).join(" · ") : label;
        const short =
          label === "—" ? "—" : abbreviateTeamName(rawTeam || label);
        return (
          <div className="min-w-0 pr-1" title={title}>
            <div className="flex items-center gap-1.5">
              <span className="shrink-0 text-sm leading-none opacity-90">
                {countryFlag(player.country) || countryShort(player.country)}
              </span>
              <span className="min-w-0 font-score text-xs font-semibold tabular-nums text-text-primary tracking-tight">
                {short}
              </span>
            </div>
          </div>
        );
      },
    },
    {
      key: "archetype",
      label: "Archetype",
      headerTooltipKey: "leaderboard_archetype",
      width: "w-28",
      align: "left",
      hideOnMobile: true,
      render: (player) =>
        player.archetype ? (
          <span className="text-xs text-text-secondary truncate max-w-[7rem] block">
            {player.archetype}
          </span>
        ) : (
          <span className="text-xs text-text-muted">—</span>
        ),
    },
    {
      key: "trend",
      label: "Trend",
      headerTooltipKey: "leaderboard_form_trend",
      width: "w-[5.5rem]",
      align: "center",
      hideOnMobile: false,
      render: (player) => {
        if (formLoading) return <span className="text-xs text-text-muted animate-pulse">…</span>;
        const item = formMap.get(String(player.id));
        const { trend, title } = computeLeaderboardTrend(item?.form_points);
        const sparkData =
          item?.form_points
            ?.map((p) => p.composite)
            .filter((c): c is number => c != null)
            .slice(-8) ?? [];
        if (trend === "insufficient") {
          return (
            <span className="inline-flex items-center justify-center w-full text-base font-medium text-text-muted" title={title}>
              −
            </span>
          );
        }
        return (
          <span className="inline-flex items-center justify-center gap-0.5 w-full" title={title}>
            {trend === "up" && <ArrowUp size={12} className="shrink-0 text-emerald-400" aria-hidden />}
            {trend === "down" && <ArrowDown size={12} className="text-amber-500 shrink-0" aria-hidden />}
            {trend === "stable" && <span className="text-sm font-medium text-slate-400" aria-hidden>−</span>}
            {sparkData.length >= 2 && (
              <FormSparkline
                data={sparkData}
                width={48}
                height={20}
                showFill={false}
                strokeWidth={1.25}
                variant="formTracker"
                className="shrink-0"
                ariaLabel={`Form trend: ${title}`}
              />
            )}
          </span>
        );
      },
    },
    {
      key: "innings",
      label: "Inn",
      sortKey: "innings_count",
      headerTooltipKey: "leaderboard_batting_innings",
      width: "w-14",
      align: "right",
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtInt(player.innings_count, "0")}
        </span>
      ),
    },
    {
      key: "runs",
      label: "Runs",
      sortKey: "total_runs",
      headerTooltipKey: "total_runs_batting",
      width: "w-16",
      align: "right",
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtInt(player.total_runs, "0")}
        </span>
      ),
    },
    {
      key: "sr",
      label: "SR",
      sortKey: "career_sr",
      headerTooltipKey: "career_sr",
      width: "w-16",
      align: "right",
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtSR(player.career_sr)}
        </span>
      ),
    },
    {
      key: "avg",
      label: "Avg",
      sortKey: "career_avg",
      headerTooltipKey: "career_avg",
      width: "w-14",
      align: "right",
      hideOnMobile: true,
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtAvg(player.career_avg)}
        </span>
      ),
    },
    {
      key: "score_1",
      label: "Acceleration",
      shortLabel: "ACL",
      sortKey: "score_acceleration",
      metricKey: "score_acceleration",
      width: showNumericInExpanded ? "w-24" : "w-20",
      align: "right",
      render: (player) => (
        <div className="flex items-center justify-end gap-1.5">
          <ScoreBarMini value={player.score_1} width={40} />
          {showNumericInExpanded && (
            <span className="text-xs tabular-nums text-text-muted w-7">{fmtScore(player.score_1)}</span>
          )}
        </div>
      ),
    },
    {
      key: "score_2",
      label: "Power",
      shortLabel: "POW",
      sortKey: "score_power",
      metricKey: "score_power",
      width: showNumericInExpanded ? "w-24" : "w-20",
      align: "right",
      render: (player) => (
        <div className="flex items-center justify-end gap-1.5">
          <ScoreBarMini value={player.score_2} width={40} />
          {showNumericInExpanded && (
            <span className="text-xs tabular-nums text-text-muted w-7">{fmtScore(player.score_2)}</span>
          )}
        </div>
      ),
    },
    {
      key: "score_3",
      label: "Control",
      shortLabel: "CTL",
      sortKey: "score_control",
      metricKey: "score_control",
      width: showNumericInExpanded ? "w-24" : "w-20",
      align: "right",
      render: (player) => (
        <div className="flex items-center justify-end gap-1.5">
          <ScoreBarMini value={player.score_3} width={40} />
          {showNumericInExpanded && (
            <span className="text-xs tabular-nums text-text-muted w-7">{fmtScore(player.score_3)}</span>
          )}
        </div>
      ),
    },
    ...selectedMetricColumns,
    {
      key: "overall",
      label: "Current / Overall",
      shortLabel: "Cur·Ovl",
      width: "min-w-[5.25rem] w-28",
      align: "center",
      render: (player) => {
        const cur = primaryDisplayRating(player);
        const ovl = careerDisplayRating(player);
        return (
          <div
            className="flex items-center gap-1 justify-center flex-nowrap"
            title="Use Cur / Ovl in the column header to sort by Current vs Career overall."
          >
            <span className="inline-flex items-center gap-0.5 font-score tabular-nums">
              <span
                className="text-sm font-semibold"
                style={{ color: scoreToColour(cur) }}
              >
                {fmtScore(cur)}
              </span>
              <span className="text-text-muted/45 text-[10px] font-normal px-0.5" aria-hidden>
                /
              </span>
              <span
                className="text-xs font-medium"
                style={{ color: scoreToColour(ovl) }}
              >
                {fmtScore(ovl)}
              </span>
            </span>
            <GradeBadge grade={player.grade_overall} size="xs" />
          </div>
        );
      },
    },
    {
      key: "actions",
      label: "›",
      headerTooltipKey: "leaderboard_open_profile",
      width: "w-8",
      align: "center",
      render: (player) => (
        <Link
          to={`/player/${player.id}`}
          className="text-text-muted hover:text-primary transition-colors"
          title="View profile"
          onClick={(ev) => ev.stopPropagation()}
        >
          <ChevronRight size={14} />
        </Link>
      ),
    },
  ];
  return density === "compact" ? cols.filter((c) => !hideInCompact(c.key)) : cols;
}

function getBowlingColumns(
  compareIds: Set<string>,
  onCompareToggle: (player: PlayerSummary) => void,
  selectedMetricColumns: ColumnDef[],
  formMap: Map<string, FormBatchItem>,
  density: Density,
  selectedMetricKeys: string[],
  formLoading: boolean,
): ColumnDef[] {
  const optionalKeys = new Set(selectedMetricKeys);
  const hideInCompact = (key: string) => COMPACT_HIDE_KEYS.has(key) || optionalKeys.has(key);
  const showNumericInExpanded = density === "expanded";

  const cols: ColumnDef[] = [
    {
      key: "compare",
      label: "+",
      headerTooltipKey: "leaderboard_compare",
      width: "w-8",
      align: "center",
      render: (player) => (
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onCompareToggle(player);
          }}
          className={`min-h-11 min-w-11 h-7 w-7 sm:min-h-0 sm:min-w-0 sm:h-5 sm:w-5 rounded border flex items-center justify-center transition-colors ${
            compareIds.has(player.id)
              ? "bg-primary border-primary text-white dark:text-background"
              : "border-surface-elevated hover:border-primary text-transparent hover:text-primary/50"
          }`}
          title={
            compareIds.has(player.id)
              ? "Remove from comparison"
              : "Add to comparison"
          }
          aria-label={`${compareIds.has(player.id) ? "Remove" : "Add"} ${player.name} ${compareIds.has(player.id) ? "from" : "to"} comparison`}
        >
          <Check size={12} />
        </button>
      ),
    },
    {
      key: "rank",
      label: "Rk",
      headerTooltipKey: "leaderboard_rank",
      width: "w-10",
      align: "right",
      render: (_player, rank) => (
        <span className="text-text-muted font-score tabular-nums text-xs">
          {rank}
        </span>
      ),
    },
    {
      key: "name",
      label: "Player",
      headerTooltipKey: "leaderboard_player",
      width: "min-w-[10rem]",
      align: "left",
      render: (player) => (
        <span className="flex items-center gap-1.5">
          <span className="font-medium text-text-primary truncate max-w-[9rem]">
            {player.name}
          </span>
          {player.is_provisional && (
            <span
              className="text-[10px] text-warning shrink-0"
              title="Provisional"
            >
              Prov
            </span>
          )}
        </span>
      ),
    },
    {
      key: "team",
      label: "Team",
      shortLabel: "Tm",
      headerTooltipKey: "leaderboard_team",
      width: "min-w-[6rem] max-w-[9rem]",
      align: "left",
      hideOnMobile: true,
      render: (player) => {
        const rawTeam = collapseDuplicateTeamLabel(
          (player.recent_team || "").trim(),
        );
        const label = rawTeam || (player.country || "").trim() || "—";
        const titleParts = [rawTeam || null, player.country].filter(
          (x): x is string => Boolean(x && String(x).trim()),
        );
        const title =
          titleParts.length > 0 ? Array.from(new Set(titleParts)).join(" · ") : label;
        const short =
          label === "—" ? "—" : abbreviateTeamName(rawTeam || label);
        return (
          <div className="min-w-0 pr-1" title={title}>
            <div className="flex items-center gap-1.5">
              <span className="shrink-0 text-sm leading-none opacity-90">
                {countryFlag(player.country) || countryShort(player.country)}
              </span>
              <span className="min-w-0 font-score text-xs font-semibold tabular-nums text-text-primary tracking-tight">
                {short}
              </span>
            </div>
          </div>
        );
      },
    },
    {
      key: "archetype",
      label: "Archetype",
      headerTooltipKey: "leaderboard_archetype",
      width: "w-28",
      align: "left",
      hideOnMobile: true,
      render: (player) =>
        player.archetype ? (
          <span className="text-xs text-text-secondary truncate max-w-[7rem] block">
            {player.archetype}
          </span>
        ) : (
          <span className="text-xs text-text-muted">—</span>
        ),
    },
    {
      key: "trend",
      label: "Trend",
      headerTooltipKey: "leaderboard_form_trend",
      width: "w-[5.5rem]",
      align: "center",
      hideOnMobile: false,
      render: (player) => {
        if (formLoading) return <span className="text-xs text-text-muted animate-pulse">…</span>;
        const item = formMap.get(String(player.id));
        const { trend, title } = computeLeaderboardTrend(item?.form_points);
        const sparkData =
          item?.form_points
            ?.map((p) => p.composite)
            .filter((c): c is number => c != null)
            .slice(-8) ?? [];
        if (trend === "insufficient") {
          return (
            <span className="inline-flex items-center justify-center w-full text-base font-medium text-text-muted" title={title}>
              −
            </span>
          );
        }
        return (
          <span className="inline-flex items-center justify-center gap-0.5 w-full" title={title}>
            {trend === "up" && <ArrowUp size={12} className="shrink-0 text-emerald-400" aria-hidden />}
            {trend === "down" && <ArrowDown size={12} className="text-amber-500 shrink-0" aria-hidden />}
            {trend === "stable" && <span className="text-sm font-medium text-slate-400" aria-hidden>−</span>}
            {sparkData.length >= 2 && (
              <FormSparkline
                data={sparkData}
                width={48}
                height={20}
                showFill={false}
                strokeWidth={1.25}
                variant="formTracker"
                className="shrink-0"
                ariaLabel={`Form trend: ${title}`}
              />
            )}
          </span>
        );
      },
    },
    {
      key: "matches",
      label: "Mat",
      sortKey: "innings_count",
      headerTooltipKey: "leaderboard_bowling_matches",
      width: "w-14",
      align: "right",
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtInt(player.innings_count, "0")}
        </span>
      ),
    },
    {
      key: "wickets",
      label: "Wkts",
      sortKey: "total_runs",
      headerTooltipKey: "bowling_career_wickets",
      width: "w-14",
      align: "right",
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtInt(player.total_runs, "0")}
        </span>
      ),
    },
    {
      key: "economy",
      label: "Econ",
      sortKey: "career_sr",
      headerTooltipKey: "leaderboard_bowling_economy",
      width: "w-16",
      align: "right",
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtEcon(player.career_sr)}
        </span>
      ),
    },
    {
      key: "bowl_sr",
      label: "SR",
      sortKey: "career_avg",
      headerTooltipKey: "leaderboard_bowling_strike_rate",
      width: "w-14",
      align: "right",
      hideOnMobile: true,
      render: (player) => (
        <span className="font-score tabular-nums text-xs">
          {fmtSR(player.career_avg)}
        </span>
      ),
    },
    {
      key: "score_1",
      label: "Accuracy",
      shortLabel: "ACC",
      sortKey: "score_accuracy",
      metricKey: "score_accuracy",
      width: showNumericInExpanded ? "w-24" : "w-20",
      align: "right",
      render: (player) => (
        <div className="flex items-center justify-end gap-1.5">
          <ScoreBarMini value={player.score_1} width={40} />
          {showNumericInExpanded && (
            <span className="text-xs tabular-nums text-text-muted w-7">{fmtScore(player.score_1)}</span>
          )}
        </div>
      ),
    },
    {
      key: "score_2",
      label: "Control",
      shortLabel: "CTL",
      sortKey: "score_control",
      metricKey: "score_control",
      width: showNumericInExpanded ? "w-24" : "w-20",
      align: "right",
      render: (player) => (
        <div className="flex items-center justify-end gap-1.5">
          <ScoreBarMini value={player.score_2} width={40} />
          {showNumericInExpanded && (
            <span className="text-xs tabular-nums text-text-muted w-7">{fmtScore(player.score_2)}</span>
          )}
        </div>
      ),
    },
    {
      key: "score_3",
      label: "Threat",
      shortLabel: "THR",
      sortKey: "score_threat",
      metricKey: "score_threat",
      width: showNumericInExpanded ? "w-24" : "w-20",
      align: "right",
      render: (player) => (
        <div className="flex items-center justify-end gap-1.5">
          <ScoreBarMini value={player.score_3} width={40} />
          {showNumericInExpanded && (
            <span className="text-xs tabular-nums text-text-muted w-7">{fmtScore(player.score_3)}</span>
          )}
        </div>
      ),
    },
    ...selectedMetricColumns,
    {
      key: "overall",
      label: "Current / Overall",
      shortLabel: "Cur·Ovl",
      width: "min-w-[5.25rem] w-28",
      align: "center",
      render: (player) => {
        const cur = primaryDisplayRating(player);
        const ovl = careerDisplayRating(player);
        return (
          <div
            className="flex items-center gap-1 justify-center flex-nowrap"
            title="Use Cur / Ovl in the column header to sort by Current vs Career overall."
          >
            <span className="inline-flex items-center gap-0.5 font-score tabular-nums">
              <span
                className="text-sm font-semibold"
                style={{ color: scoreToColour(cur) }}
              >
                {fmtScore(cur)}
              </span>
              <span className="text-text-muted/45 text-[10px] font-normal px-0.5" aria-hidden>
                /
              </span>
              <span
                className="text-xs font-medium"
                style={{ color: scoreToColour(ovl) }}
              >
                {fmtScore(ovl)}
              </span>
            </span>
            <GradeBadge grade={player.grade_overall} size="xs" />
          </div>
        );
      },
    },
    {
      key: "actions",
      label: "›",
      headerTooltipKey: "leaderboard_open_profile",
      width: "w-8",
      align: "center",
      render: (player) => (
        <Link
          to={`/player/${player.id}`}
          className="text-text-muted hover:text-primary transition-colors"
          title="View profile"
          onClick={(ev) => ev.stopPropagation()}
        >
          <ChevronRight size={14} />
        </Link>
      ),
    },
  ];
  return density === "compact" ? cols.filter((c) => !hideInCompact(c.key)) : cols;
}

// ── Default sort columns per role ────────────────────────────────

const DEFAULT_SORT: Record<string, string> = {
  bat: "rating_current",
  bowl: "rating_current",
};

const SORT_LABEL_MAP: Record<string, string> = {
  rating_current: "Current rating",
  rating_overall: "Career overall (display)",
  overall_score: "Overall Score (pipeline)",
  score_acceleration: "Acceleration",
  score_power: "Power",
  score_control: "Control",
  score_accuracy: "Accuracy",
  score_threat: "Threat",
  career_sr: "Strike Rate",
  career_avg: "Average",
  career_dot_pct: "Dot %",
  total_runs: "Runs / Wickets",
  innings_count: "Innings",
  war_batting: "WAR",
  war_batting_rate: "WAR / 50",
  war_bowling: "WAR",
  war_bowling_rate: "WAR / 50",
  clutch_index: "Pressure Score",
  clutch_index_bowl: "Pressure Score",
  clutch_sr_delta: "Pressure SR Delta",
  chase_master_index: "Chase Master",
  chase_master_full: "Chase Master+",
  flat_track_index: "Flat Track Index",
  flat_track_index_bowl: "Flat Track Index",
  venue_adjusted_composite: "Venue-Adjusted Composite",
  selfless_index: "Selfless Index",
  anchor_cost_ratio: "Anchor Cost Ratio",
  avg_balls_to_par: "Balls vs Par",
  avg_dominance: "Matchup Edge",
  avg_dominance_bowl: "Matchup Edge",
  pct_dominant: "% Dominant",
  pct_dominant_bowl: "% Dominant",
  matchup_consistency: "Matchup Consistency",
  bowled_lbw_pct: "Bowled/LBW %",
  peak_composite_batting: "Peak Rating",
  peak_composite_bowling: "Peak Rating",
  peak_window_composite: "Peak Window Composite",
};

/** Percentile within the current page of results (not global). */
function pagePercentile(
  players: PlayerSummary[],
  value: number | null | undefined,
  pick: (p: PlayerSummary) => number | null | undefined,
  lowerIsBetter?: boolean,
): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  const vals: number[] = [];
  for (const p of players) {
    const v = pick(p);
    if (v != null && Number.isFinite(v)) vals.push(v);
  }
  if (vals.length === 0) return null;
  const strictlyLess = vals.filter((n) => n < value).length;
  const equal = vals.filter((n) => n === value).length;
  let pct = ((strictlyLess + equal * 0.5) / vals.length) * 100;
  if (lowerIsBetter) pct = 100 - pct;
  return Math.round(Math.min(100, Math.max(0, pct)));
}

function percentilePillClass(pct: number | null): string {
  if (pct == null) {
    return "border-surface-elevated/60 text-text-muted bg-surface-elevated/30";
  }
  if (pct >= 85) return "border-primary/45 bg-primary/15 text-primary";
  if (pct >= 65) return "border-amber-500/35 bg-amber-500/10 text-amber-200/95";
  if (pct >= 40) return "border-surface-elevated text-text-secondary bg-surface-elevated/40";
  return "border-surface-elevated/70 text-text-muted bg-surface-elevated/25";
}

function SidebarStatRow({
  label,
  value,
  pct,
}: {
  label: string;
  value: string;
  pct: number | null;
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-surface-elevated/35 py-2 last:border-b-0">
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
        {label}
      </span>
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate font-score text-sm tabular-nums text-text-primary">{value}</span>
        {pct != null && (
          <span
            className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${percentilePillClass(pct)}`}
            title="Percentile vs players on this page"
          >
            {pct}
          </span>
        )}
      </div>
    </div>
  );
}

interface LeaderboardHoverSidebarProps {
  players: PlayerSummary[];
  displayPlayer: PlayerSummary | null;
  displayRank: number | null;
  isBowling: boolean;
  selectedMetricKeys: string[];
  formMap: Map<string, FormBatchItem>;
  formLoading: boolean;
  onOpenFullPreview: (playerId: string) => void;
  className?: string;
}

function LeaderboardHoverSidebar({
  players,
  displayPlayer,
  displayRank,
  isBowling,
  selectedMetricKeys,
  formMap,
  formLoading,
  onOpenFullPreview,
  className = "",
}: LeaderboardHoverSidebarProps) {
  const hotkeyRows: [string, string][] = [
    ["T", "Fullscreen this view"],
    ["W / E", "Tighter / looser table rows"],
    ["F", "Toggle filters"],
    ["M", "Toggle column picker"],
    ["G", "Open stats glossary"],
    ["[ / ]", "Scroll table horizontally"],
    ["C", "Add highlighted player to compare"],
    ["Esc", "Close panels or clear highlight"],
  ];

  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <div className="rounded-2xl border border-surface-elevated/80 bg-surface-elevated/10 p-3 shadow-sm dark:bg-surface-elevated/20 dark:shadow-[0_12px_40px_-28px_rgba(0,0,0,0.75)]">
        <div className="mb-2 flex items-center gap-2 text-text-primary">
          <Keyboard size={15} className="shrink-0 text-primary" aria-hidden />
          <span className="text-xs font-semibold tracking-tight">Hotkeys</span>
        </div>
        <ul className="space-y-1.5">
          {hotkeyRows.map(([k, desc]) => (
            <li key={k} className="flex gap-2 text-[11px] leading-snug text-text-secondary">
              <kbd className="shrink-0 rounded-md border border-surface-elevated/80 bg-surface px-1.5 py-0.5 font-mono text-[10px] font-semibold text-text-primary shadow-sm">
                {k}
              </kbd>
              <span>{desc}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-2xl border border-surface-elevated/80 bg-surface shadow-sm dark:border-white/[0.08] dark:bg-[#0c0c0c] dark:shadow-[0_16px_48px_-32px_rgba(0,0,0,0.85)]">
        {!displayPlayer && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border border-dashed border-surface-elevated/80 bg-surface-elevated/20 text-text-muted">
              <Keyboard size={22} strokeWidth={1.25} aria-hidden />
            </div>
            <p className="text-xs font-medium text-text-secondary">Hover a row for live stats</p>
            <p className="text-[11px] text-text-muted">
              Percentiles are vs this page only. Tap a row on touch devices.
            </p>
          </div>
        )}
        {displayPlayer && (
          <div className="p-3">
            <div className="mb-3 flex gap-3 border-b border-surface-elevated/50 pb-3">
              <PlayerAvatar
                name={displayPlayer.name}
                playerId={displayPlayer.id}
                photoUrl={displayPlayer.photo_url}
                size="md"
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <h2 className="truncate text-sm font-semibold text-text-primary">
                    {displayPlayer.name}
                  </h2>
                  {displayRank != null && (
                    <span className="shrink-0 font-score text-[11px] tabular-nums text-text-muted">
                      #{displayRank}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-text-secondary">
                  {(() => {
                    const raw = collapseDuplicateTeamLabel(
                      (displayPlayer.recent_team || "").trim(),
                    );
                    const team = raw || displayPlayer.country || "—";
                    const short = team === "—" ? "—" : abbreviateTeamName(raw || team);
                    return (
                      <>
                        <span className="font-medium">{short}</span>
                        {displayPlayer.archetype ? (
                          <span className="text-text-muted"> · {displayPlayer.archetype}</span>
                        ) : null}
                      </>
                    );
                  })()}
                </p>
                <p className="mt-1 text-[10px] text-text-muted">
                  {displayPlayer.innings_count}{" "}
                  {isBowling ? "matches" : "innings"} in this slice
                </p>
              </div>
            </div>

            {!isBowling && (
              <div className="space-y-0">
                <SidebarStatRow
                  label="Current"
                  value={fmtScore(primaryDisplayRating(displayPlayer))}
                  pct={pagePercentile(players, primaryDisplayRating(displayPlayer), (p) =>
                    primaryDisplayRating(p),
                  )}
                />
                <SidebarStatRow
                  label="Overall"
                  value={fmtScore(careerDisplayRating(displayPlayer))}
                  pct={pagePercentile(players, careerDisplayRating(displayPlayer), (p) =>
                    careerDisplayRating(p),
                  )}
                />
                <SidebarStatRow
                  label="Inn"
                  value={fmtInt(displayPlayer.innings_count, "0")}
                  pct={pagePercentile(players, displayPlayer.innings_count, (p) => p.innings_count)}
                />
                <SidebarStatRow
                  label="Runs"
                  value={fmtInt(displayPlayer.total_runs, "0")}
                  pct={pagePercentile(players, displayPlayer.total_runs, (p) => p.total_runs)}
                />
                <SidebarStatRow
                  label="SR"
                  value={fmtSR(displayPlayer.career_sr)}
                  pct={pagePercentile(players, displayPlayer.career_sr, (p) => p.career_sr)}
                />
                <SidebarStatRow
                  label="Avg"
                  value={fmtAvg(displayPlayer.career_avg)}
                  pct={pagePercentile(players, displayPlayer.career_avg, (p) => p.career_avg)}
                />
                <SidebarStatRow
                  label="ACL"
                  value={fmtScore(displayPlayer.score_1)}
                  pct={pagePercentile(players, displayPlayer.score_1, (p) => p.score_1)}
                />
                <SidebarStatRow
                  label="POW"
                  value={fmtScore(displayPlayer.score_2)}
                  pct={pagePercentile(players, displayPlayer.score_2, (p) => p.score_2)}
                />
                <SidebarStatRow
                  label="CTL"
                  value={fmtScore(displayPlayer.score_3)}
                  pct={pagePercentile(players, displayPlayer.score_3, (p) => p.score_3)}
                />
              </div>
            )}

            {isBowling && (
              <div className="space-y-0">
                <SidebarStatRow
                  label="Current"
                  value={fmtScore(primaryDisplayRating(displayPlayer))}
                  pct={pagePercentile(players, primaryDisplayRating(displayPlayer), (p) =>
                    primaryDisplayRating(p),
                  )}
                />
                <SidebarStatRow
                  label="Overall"
                  value={fmtScore(careerDisplayRating(displayPlayer))}
                  pct={pagePercentile(players, careerDisplayRating(displayPlayer), (p) =>
                    careerDisplayRating(p),
                  )}
                />
                <SidebarStatRow
                  label="Wkts"
                  value={fmtInt(displayPlayer.total_runs, "0")}
                  pct={pagePercentile(players, displayPlayer.total_runs, (p) => p.total_runs)}
                />
                <SidebarStatRow
                  label="Econ"
                  value={fmtEcon(displayPlayer.career_sr)}
                  pct={pagePercentile(players, displayPlayer.career_sr, (p) => p.career_sr, true)}
                />
                <SidebarStatRow
                  label="SR"
                  value={fmtSR(displayPlayer.career_avg)}
                  pct={pagePercentile(players, displayPlayer.career_avg, (p) => p.career_avg, true)}
                />
                <SidebarStatRow
                  label="ACC"
                  value={fmtScore(displayPlayer.score_1)}
                  pct={pagePercentile(players, displayPlayer.score_1, (p) => p.score_1)}
                />
                <SidebarStatRow
                  label="CTL"
                  value={fmtScore(displayPlayer.score_2)}
                  pct={pagePercentile(players, displayPlayer.score_2, (p) => p.score_2)}
                />
                <SidebarStatRow
                  label="THR"
                  value={fmtScore(displayPlayer.score_3)}
                  pct={pagePercentile(players, displayPlayer.score_3, (p) => p.score_3)}
                />
              </div>
            )}

            {selectedMetricKeys.length > 0 && (
              <div className="mt-2 border-t border-surface-elevated/50 pt-2">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                  Extra columns
                </p>
                <div className="space-y-0">
                  {selectedMetricKeys.map((key) => {
                    const cfg = METRIC_COLUMN_CONFIG[key];
                    if (!cfg) return null;
                    const raw = displayPlayer.metrics?.[key];
                    return (
                      <SidebarStatRow
                        key={key}
                        label={cfg.shortLabel ?? cfg.label}
                        value={formatMetricValue(raw, cfg.format)}
                        pct={pagePercentile(players, raw, (p) => p.metrics?.[key], false)}
                      />
                    );
                  })}
                </div>
              </div>
            )}

            <div className="mt-3 border-t border-surface-elevated/50 pt-2">
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                Form
              </p>
              {formLoading && <span className="text-xs text-text-muted">…</span>}
              {!formLoading && (() => {
                const item = formMap.get(String(displayPlayer.id));
                const sparkData =
                  item?.form_points
                    ?.map((p) => p.composite)
                    .filter((c): c is number => c != null)
                    .slice(-12) ?? [];
                if (sparkData.length >= 2) {
                  return (
                    <FormSparkline
                      data={sparkData}
                      width={220}
                      height={48}
                      variant="formTracker"
                      showMedianLine
                      showEndDot
                      interactive
                      ariaLabel="Recent form (composite)"
                    />
                  );
                }
                return <span className="text-xs text-text-muted">No sparkline on this page</span>;
              })()}
            </div>

            <div className="mt-3 flex flex-col gap-2">
              <button
                type="button"
                className="btn-primary btn-sm w-full justify-center"
                onClick={() => onOpenFullPreview(displayPlayer.id)}
              >
                Full preview
              </button>
              <Link
                to={`/player/${displayPlayer.id}`}
                className="btn-secondary btn-sm w-full justify-center no-underline"
              >
                Open profile
                <ChevronRight size={14} />
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Leaderboard preview panel (Phase 2) ───────────────────────────

interface LeaderboardPreviewPanelProps {
  playerId: string;
  isBowling: boolean;
  onClose: () => void;
}

function LeaderboardPreviewPanel({
  playerId,
  isBowling,
  onClose,
}: LeaderboardPreviewPanelProps) {
  const { data: batProfile, isLoading: batLoading } = useBatterProfile(
    isBowling ? undefined : playerId,
    { enabled: !isBowling },
  );
  const { data: bowlProfile, isLoading: bowlLoading } = useBowlerProfile(
    isBowling ? playerId : undefined,
    { enabled: isBowling },
  );
  const { data: formData, isLoading: formLoading } = usePlayerForm(
    playerId,
    isBowling ? "bowl" : "bat",
    { enabled: true },
  );
  const isLoading = isBowling ? bowlLoading : batLoading;
  const profile = isBowling ? bowlProfile : batProfile;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        aria-hidden
        onClick={onClose}
      />
      <div
        className="fixed top-0 right-0 bottom-0 w-full max-w-md bg-surface border-l border-surface-elevated shadow-xl z-50 flex flex-col animate-slide-up"
        role="dialog"
        aria-label="Player preview"
      >
        <div className="flex items-center justify-between p-3 border-b border-surface-elevated">
          <span className="text-sm font-medium text-text-secondary">
            Quick preview
          </span>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
            aria-label="Close preview"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading && (
            <div className="space-y-3">
              <div className="skeleton h-6 w-3/4 rounded" />
              <div className="skeleton h-4 w-1/2 rounded" />
              <div className="skeleton h-20 w-full rounded" />
            </div>
          )}
          {!isLoading && profile && (
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold text-text-primary">
                  {profile.name}
                </h2>
                <p className="text-sm text-text-secondary flex items-center gap-2 mt-0.5 flex-wrap">
                  {countryFlag(profile.country)}
                  <span>
                    {(profile.recent_team || "").trim() || profile.country}
                  </span>
                  {(profile.recent_team || "").trim() &&
                    profile.country &&
                    (profile.recent_team || "").trim().toLowerCase() !==
                      profile.country.trim().toLowerCase() && (
                      <span className="text-xs text-text-muted">
                        · {profile.country}
                      </span>
                    )}
                  {"overall_grade" in profile && (
                    <GradeBadge grade={profile.overall_grade ?? "D"} size="sm" />
                  )}
                </p>
                {profile.archetype && (
                  <p className="text-xs text-text-muted mt-1">
                    {profile.archetype}
                  </p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2 rounded-lg bg-surface-elevated/50 p-2 text-sm">
                <div>
                  <span className="text-text-muted block text-xs">Current</span>
                  <span
                    className="font-score tabular-nums font-semibold text-base"
                    style={{
                      color: scoreToColour(primaryDisplayRating(profile)),
                    }}
                  >
                    {fmtScore(primaryDisplayRating(profile))}
                  </span>
                </div>
                <div>
                  <span className="text-text-muted block text-xs">Overall</span>
                  <span
                    className="font-score tabular-nums font-semibold text-base"
                    style={{
                      color: scoreToColour(careerDisplayRating(profile)),
                    }}
                  >
                    {fmtScore(careerDisplayRating(profile))}
                  </span>
                </div>
              </div>

              {!isBowling && batProfile && (
                <>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">Runs</span>
                      <span className="font-score tabular-nums">{fmtInt(batProfile.total_runs, "0")}</span>
                    </div>
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">SR</span>
                      <span className="font-score tabular-nums">{fmtSR(batProfile.career_sr)}</span>
                    </div>
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">Innings</span>
                      <span className="font-score tabular-nums">{fmtInt(batProfile.innings_count, "0")}</span>
                    </div>
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">Avg</span>
                      <span className="font-score tabular-nums">{fmtAvg(batProfile.career_avg)}</span>
                    </div>
                  </div>
                  <div>
                    <span className="text-xs text-text-muted uppercase tracking-wider block mb-1.5">Dimensions</span>
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-text-muted w-8">ACL</span>
                      <ScoreBarMini value={batProfile.score_acceleration} width={56} />
                    </div>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-text-muted w-8">POW</span>
                      <ScoreBarMini value={batProfile.score_power} width={56} />
                    </div>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-text-muted w-8">CTL</span>
                      <ScoreBarMini value={batProfile.score_control} width={56} />
                    </div>
                  </div>
                  {(batProfile.war_batting != null || batProfile.war_batting_rate != null) && (
                    <div className="rounded-lg bg-surface-elevated/50 p-2 text-sm">
                      <span className="text-text-muted block text-xs">WAR</span>
                      <span className="font-score tabular-nums">
                        {fmtWAR(batProfile.war_batting)}
                        {batProfile.war_batting_rate != null && (
                          <span className="text-text-muted ml-1 text-xs">({fmtWAR(batProfile.war_batting_rate)}/50)</span>
                        )}
                      </span>
                    </div>
                  )}
                  <div>
                    <span className="text-xs text-text-muted uppercase tracking-wider block mb-1.5">Form</span>
                    {formLoading && <span className="text-xs text-text-muted">…</span>}
                    {!formLoading && formData?.series && formData.series.length > 0 && (
                      <FormSparkline
                        data={formData.series.map((p) => p.composite).filter((c): c is number => c != null)}
                        width={200}
                        height={56}
                        variant="formTracker"
                        showMedianLine
                        showEndDot={true}
                        interactive={true}
                        ariaLabel="Form (composite 0–100)"
                      />
                    )}
                    {!formLoading && (!formData?.series || formData.series.length === 0) && (
                      <span className="text-xs text-text-muted">No form data</span>
                    )}
                  </div>
                </>
              )}

              {isBowling && bowlProfile && (
                <>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">Wickets</span>
                      <span className="font-score tabular-nums">{fmtInt(bowlProfile.total_wickets ?? 0, "0")}</span>
                    </div>
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">Econ</span>
                      <span className="font-score tabular-nums">{fmtEcon(bowlProfile.career_economy)}</span>
                    </div>
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">Matches</span>
                      <span className="font-score tabular-nums">{fmtInt(bowlProfile.matches ?? 0, "0")}</span>
                    </div>
                    <div className="rounded-lg bg-surface-elevated/50 p-2">
                      <span className="text-text-muted block text-xs">SR</span>
                      <span className="font-score tabular-nums">{fmtInt(bowlProfile.career_sr_bowl ?? null, "—")}</span>
                    </div>
                  </div>
                  {bowlProfile.phase_group && (
                    <div className="text-xs text-text-muted">
                      <span className="uppercase tracking-wider">Phase</span>{" "}
                      <span className="capitalize text-text-secondary">{bowlProfile.phase_group}</span>
                    </div>
                  )}
                  <div>
                    <span className="text-xs text-text-muted uppercase tracking-wider block mb-1.5">Dimensions</span>
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-text-muted w-8">ACC</span>
                      <ScoreBarMini value={bowlProfile.score_accuracy} width={56} />
                    </div>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-text-muted w-8">CTL</span>
                      <ScoreBarMini value={bowlProfile.score_control} width={56} />
                    </div>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-text-muted w-8">THR</span>
                      <ScoreBarMini value={bowlProfile.score_threat} width={56} />
                    </div>
                  </div>
                  {(bowlProfile.career_dot_pct != null || bowlProfile.war_bowling != null) && (
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      {bowlProfile.career_dot_pct != null && (
                        <div className="rounded-lg bg-surface-elevated/50 p-2">
                          <span className="text-text-muted block text-xs">Dot %</span>
                          <span className="font-score tabular-nums">{fmtPct(bowlProfile.career_dot_pct, 1)}</span>
                        </div>
                      )}
                      {(bowlProfile.war_bowling != null || bowlProfile.war_bowling_rate != null) && (
                        <div className="rounded-lg bg-surface-elevated/50 p-2">
                          <span className="text-text-muted block text-xs">WAR</span>
                          <span className="font-score tabular-nums">
                            {fmtWAR(bowlProfile.war_bowling)}
                            {bowlProfile.war_bowling_rate != null && (
                              <span className="text-text-muted ml-1 text-xs">({fmtWAR(bowlProfile.war_bowling_rate)}/50)</span>
                            )}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                  <div>
                    <span className="text-xs text-text-muted uppercase tracking-wider block mb-1.5">Form</span>
                    {formLoading && <span className="text-xs text-text-muted">…</span>}
                    {!formLoading && formData?.series && formData.series.length > 0 && (
                      <FormSparkline
                        data={formData.series.map((p) => p.composite).filter((c): c is number => c != null)}
                        width={200}
                        height={56}
                        variant="formTracker"
                        showMedianLine
                        showEndDot={true}
                        interactive={true}
                        ariaLabel="Form (composite 0–100)"
                      />
                    )}
                    {!formLoading && (!formData?.series || formData.series.length === 0) && (
                      <span className="text-xs text-text-muted">No form data</span>
                    )}
                  </div>
                </>
              )}

              <Link
                to={`/player/${playerId}`}
                className="inline-flex items-center gap-1.5 text-sm text-primary hover:text-primary-hover font-medium"
              >
                View full profile
                <ChevronRight size={14} />
              </Link>
            </div>
          )}
          {!isLoading && !profile && (
            <p className="text-sm text-text-muted">Could not load player.</p>
          )}
        </div>
      </div>
    </>
  );
}

// ── Rankings Page Component ──────────────────────────────────────

export default function RankingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // ── Parse URL state ────────────────────────────────────────
  const role = searchParams.get("role") ?? "bat";
  const sort =
    searchParams.get("sort") ?? DEFAULT_SORT[role] ?? "rating_current";
  const order = searchParams.get("order") ?? "desc";
  const country = searchParams.get("country") ?? undefined;
  const archetype = searchParams.get("archetype") ?? undefined;
  const positionGroup = searchParams.get("position_group") ?? undefined;
  const rawModalSlot = searchParams.get("modal_slot");
  const modalSlotParsed = rawModalSlot ? parseInt(rawModalSlot, 10) : NaN;
  const modalSlot =
    role !== "bowl" &&
    Number.isFinite(modalSlotParsed) &&
    modalSlotParsed >= 1 &&
    modalSlotParsed <= 11
      ? modalSlotParsed
      : undefined;
  const phaseGroup = searchParams.get("phase_group") ?? undefined;
  const page = parseIntParam(searchParams.get("page"), 1);
  const perPage = parseIntParam(searchParams.get("per_page"), 25);
  const minInnings = parseIntParam(searchParams.get("min_innings"), 0);
  const provisional = parseBoolParam(searchParams.get("provisional"));
  const rawActivity = searchParams.get("activity");
  const activity: "active" | "retired" | "all" =
    rawActivity === "retired" || rawActivity === "all" ? rawActivity : "active";
  const chaseHighRpo = searchParams.get("ctx_chase") === "1";
  const playoffsOnly = searchParams.get("ctx_playoffs") === "1";
  const rawCtxEntry = searchParams.get("ctx_entry");
  const inningsPhase: InningsPhaseOption =
    rawCtxEntry === "early" || rawCtxEntry === "death" ? rawCtxEntry : "any";
  const densityParam = searchParams.get("density");
  const { format } = useFormat();
  const density: Density =
    densityParam === "compact" || densityParam === "expanded"
      ? densityParam
      : "default";

  // ── Local state ────────────────────────────────────────────
  const [previewPlayerId, setPreviewPlayerId] = useState<string | null>(null);
  const [hoverPlayerId, setHoverPlayerId] = useState<string | null>(null);
  const [coarsePointer, setCoarsePointer] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(pointer: coarse)").matches,
  );
  const hoverClearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const rankingsFocusRef = useRef<HTMLDivElement>(null);
  const [showFilters, setShowFilters] = useState(
    Boolean(
      country ||
      archetype ||
      positionGroup ||
      phaseGroup ||
      modalSlot != null ||
      provisional !== undefined ||
      minInnings > 0 ||
      activity !== "active",
    ),
  );
  const [showColumns, setShowColumns] = useState(false);
  const [compareIds, setCompareIds] = useState<Set<string>>(new Set());
  const [sortAnnouncement, setSortAnnouncement] = useState("");
  const [tableOverlay, setTableOverlay] = useState(false);
  const overlayEndTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const overlayStartRef = useRef<number | null>(null);

  useEffect(() => {
    const label = SORT_LABEL_MAP[sort] ?? sort;
    setSortAnnouncement(
      `Sorted by ${label}, ${order === "desc" ? "descending" : "ascending"}`,
    );
  }, [sort, order]);

  // ── Reference data ─────────────────────────────────────────
  const { data: countries = [] } = useCountries();
  const { data: archetypesData } = useArchetypes();
  const { data: battingSortColumns = [] } = useBattingSortColumns();
  const { data: bowlingSortColumns = [] } = useBowlingSortColumns();

  const archetypeOptions = useMemo(() => {
    if (!archetypesData) return [];
    if (role === "bowl") return archetypesData.bowl ?? [];
    return archetypesData.bat ?? [];
  }, [archetypesData, role]);

  // ── Data fetching ──────────────────────────────────────────
  const isBowling = role === "bowl";
  const roleKey: "bat" | "bowl" = isBowling ? "bowl" : "bat";
  const availableSortColumns = isBowling
    ? bowlingSortColumns
    : battingSortColumns;
  const availableMetricKeys = useMemo(
    () =>
      new Set(
        OPTIONAL_METRIC_KEYS[roleKey].filter((key) =>
          availableSortColumns.includes(key),
        ),
      ),
    [availableSortColumns, roleKey],
  );
  const selectedMetricKeys = useMemo(
    () =>
      parseExtraColumns(searchParams.get("cols"), roleKey, availableMetricKeys),
    [availableMetricKeys, roleKey, searchParams],
  );
  const availableMetricColumns = useMemo(
    () =>
      OPTIONAL_METRIC_KEYS[roleKey]
        .filter((key) => availableMetricKeys.has(key))
        .map((key) => METRIC_COLUMN_CONFIG[key])
        .filter((config): config is MetricColumnConfig => Boolean(config)),
    [availableMetricKeys, roleKey],
  );
  const selectedMetricColumns = useMemo(
    () =>
      selectedMetricKeys
        .map((key) => METRIC_COLUMN_CONFIG[key])
        .filter((config): config is MetricColumnConfig => Boolean(config))
        .map(buildMetricColumn),
    [selectedMetricKeys],
  );
  const sortSelectValue = useMemo(() => {
    const quickSortKeys = new Set(
      getQuickSortOptions(isBowling).map((opt) => opt.key),
    );
    if (quickSortKeys.has(sort)) return "";
    if (availableSortColumns.includes(sort)) return sort;
    return "";
  }, [availableSortColumns, isBowling, sort]);

  const rankingsParams: Partial<LeaderboardParams> = {
    sort,
    order: order as "asc" | "desc",
    country,
    archetype,
    position_group: isBowling ? undefined : positionGroup,
    modal_slot: isBowling ? undefined : modalSlot,
    phase_group: isBowling ? phaseGroup : undefined,
    min_innings: minInnings > 0 ? minInnings : undefined,
    provisional,
    activity,
    page,
    per_page: perPage,
    ...(isBowling
      ? {}
      : {
          ctx_entry_phase:
            inningsPhase === "early" || inningsPhase === "death"
              ? inningsPhase
              : undefined,
          ctx_knockouts_only: playoffsOnly || undefined,
          ctx_chase_high_rpo: chaseHighRpo || undefined,
        }),
  };

  const distributionFilters = useMemo<LeaderboardDistributionFilters>(
    () => ({
      country,
      archetype,
      position_group: isBowling ? undefined : positionGroup,
      modal_slot: isBowling ? undefined : modalSlot,
      phase_group: isBowling ? phaseGroup : undefined,
      min_innings: minInnings > 0 ? minInnings : undefined,
      provisional,
      activity,
      ...(isBowling
        ? {}
        : {
            ctx_entry_phase:
              inningsPhase === "early" || inningsPhase === "death"
                ? inningsPhase
                : undefined,
            ctx_knockouts_only: playoffsOnly ? true : undefined,
            ctx_chase_high_rpo: chaseHighRpo ? true : undefined,
          }),
    }),
    [
      country,
      archetype,
      positionGroup,
      modalSlot,
      phaseGroup,
      minInnings,
      provisional,
      activity,
      isBowling,
      inningsPhase,
      playoffsOnly,
      chaseHighRpo,
    ],
  );

  const distributionMetricOptions = useMemo(
    () =>
      (availableSortColumns ?? []).map((key) => ({
        key,
        label: METRIC_COLUMN_CONFIG[key]?.label ?? key.replace(/_/g, " "),
      })),
    [availableSortColumns],
  );

  const battingQuery = useBattingRankings(isBowling ? {} : rankingsParams);

  const bowlingQuery = useBowlingRankings(isBowling ? rankingsParams : {});

  const query = isBowling ? bowlingQuery : battingQuery;
  const { data, isLoading, isFetching, error, refetch } = query;

  useEffect(() => {
    if (isFetching && !isLoading) {
      if (overlayEndTimerRef.current) {
        clearTimeout(overlayEndTimerRef.current);
        overlayEndTimerRef.current = null;
      }
      overlayStartRef.current = Date.now();
      setTableOverlay(true);
    }
  }, [isFetching, isLoading]);

  useEffect(() => {
    if (!isFetching && tableOverlay) {
      const started = overlayStartRef.current ?? Date.now();
      const elapsed = Date.now() - started;
      const wait = Math.max(0, 300 - elapsed);
      overlayEndTimerRef.current = setTimeout(() => {
        setTableOverlay(false);
        overlayStartRef.current = null;
        overlayEndTimerRef.current = null;
      }, wait);
      return () => {
        if (overlayEndTimerRef.current) {
          clearTimeout(overlayEndTimerRef.current);
        }
      };
    }
  }, [isFetching, tableOverlay]);

  useEffect(
    () => () => {
      if (overlayEndTimerRef.current) {
        clearTimeout(overlayEndTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(pointer: coarse)");
    const fn = () => setCoarsePointer(mq.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);

  const players = data?.players ?? [];
  const totalPlayers = data?.total ?? 0;

  useEffect(() => {
    setHoverPlayerId(null);
  }, [page, perPage, role, sort, isBowling]);

  useEffect(() => {
    if (hoverPlayerId && !players.some((p) => p.id === hoverPlayerId)) {
      setHoverPlayerId(null);
    }
  }, [players, hoverPlayerId]);
  const totalPages =
    data?.total_pages ?? (Math.ceil(totalPlayers / perPage) || 1);

  const playerIds = useMemo(() => players.map((p) => p.id), [players]);
  const { data: formBatchData, isLoading: formLoading } = useFormBatch(playerIds, roleKey, {
    enabled: playerIds.length > 0,
  });
  const formMap = useMemo(() => {
    const results = Array.isArray(formBatchData?.results) ? formBatchData.results : [];
    return new Map(results.map((r) => [String(r.player_id), r]));
  }, [formBatchData?.results]);

  // ── URL update helper ──────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(updates)) {
          if (value == null || value === "" || value === "undefined") {
            next.delete(key);
          } else {
            next.set(key, value);
          }
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const updateContextParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      updateParams({ ...updates, page: "1" });
    },
    [updateParams],
  );

  // ── Handlers ───────────────────────────────────────────────

  const handleRoleToggle = useCallback(
    (newRole: string) => {
      // Reset page, sort, and role-specific filters
      const newSort = DEFAULT_SORT[newRole] ?? "rating_current";
      const next = new URLSearchParams({
        role: newRole,
        sort: newSort,
        order: "desc",
        per_page: String(perPage),
      });
      const cols = serialiseExtraColumns(
        DEFAULT_EXTRA_COLUMNS[
          (newRole === "bowl" ? "bowl" : "bat") as "bat" | "bowl"
        ],
      );
      if (cols) next.set("cols", cols);
      if (activity !== "active") next.set("activity", activity);
      if (searchParams.get("ctx_chase") === "1") next.set("ctx_chase", "1");
      if (searchParams.get("ctx_playoffs") === "1") next.set("ctx_playoffs", "1");
      const ctxEnt = searchParams.get("ctx_entry");
      if (ctxEnt === "early" || ctxEnt === "death") next.set("ctx_entry", ctxEnt);
      setSearchParams(next);
      setCompareIds(new Set());
    },
    [perPage, setSearchParams, activity, searchParams],
  );

  const handleSort = useCallback(
    (sortKey: string) => {
      if (sort === sortKey) {
        // Toggle order
        updateParams({
          order: order === "desc" ? "asc" : "desc",
          page: "1",
        });
      } else {
        updateParams({
          sort: sortKey,
          order: "desc",
          page: "1",
        });
      }
    },
    [sort, order, updateParams],
  );

  const handlePageChange = useCallback(
    (newPage: number) => {
      updateParams({ page: String(newPage) });
      // Scroll to top of table
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [updateParams],
  );

  const handlePerPageChange = useCallback(
    (newPerPage: number) => {
      updateParams({ per_page: String(newPerPage), page: "1" });
    },
    [updateParams],
  );

  const handleCompareToggle = useCallback((player: PlayerSummary) => {
    setCompareIds((prev) => {
      const next = new Set(prev);
      if (next.has(player.id)) {
        next.delete(player.id);
      } else if (next.size < 4) {
        next.add(player.id);
      }
      return next;
    });
  }, []);

  const handleCompareNavigate = useCallback(() => {
    if (compareIds.size >= 2) {
      navigate(`/compare?ids=${Array.from(compareIds).join(",")}`);
    }
  }, [navigate, compareIds]);

  const handleClearFilters = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams({
        role,
        sort: DEFAULT_SORT[role] ?? "rating_current",
        order: "desc",
        per_page: String(perPage),
      });
      const cols = serialiseExtraColumns(selectedMetricKeys);
      if (cols) next.set("cols", cols);
      for (const key of ["ctx_chase", "ctx_playoffs", "ctx_entry"] as const) {
        const v = prev.get(key);
        if (v) next.set(key, v);
      }
      return next;
    });
  }, [role, perPage, selectedMetricKeys, setSearchParams]);

  const handleClearContextFilters = useCallback(() => {
    updateContextParams({
      ctx_chase: null,
      ctx_playoffs: null,
      ctx_entry: null,
    });
  }, [updateContextParams]);

  const handleCtxChaseChange = useCallback(
    (next: boolean) => {
      updateContextParams({ ctx_chase: next ? "1" : null });
    },
    [updateContextParams],
  );

  const handleCtxPlayoffsChange = useCallback(
    (next: boolean) => {
      updateContextParams({ ctx_playoffs: next ? "1" : null });
    },
    [updateContextParams],
  );

  const handleCtxInningsPhaseChange = useCallback(
    (next: InningsPhaseOption) => {
      updateContextParams({
        ctx_entry: next === "any" ? null : next,
      });
    },
    [updateContextParams],
  );

  const handlePreset = useCallback(
    (preset: LeaderboardPreset) => {
      const updates: Record<string, string | null> = {
        sort: preset.sort,
        order: preset.order ?? "desc",
        page: "1",
        phase_group: preset.phase_group ?? null,
        position_group: preset.position_group ?? null,
        archetype: preset.archetype ?? null,
        modal_slot: null,
      };
      updateParams(updates);
    },
    [updateParams],
  );

  const handleDensityChange = useCallback(
    (d: Density) => {
      updateParams({ density: d === "default" ? null : d });
    },
    [updateParams],
  );

  const cancelHoverClear = useCallback(() => {
    if (hoverClearTimerRef.current) {
      clearTimeout(hoverClearTimerRef.current);
      hoverClearTimerRef.current = null;
    }
  }, []);

  const scheduleHoverClear = useCallback(() => {
    cancelHoverClear();
    hoverClearTimerRef.current = setTimeout(() => {
      setHoverPlayerId(null);
      hoverClearTimerRef.current = null;
    }, 200);
  }, [cancelHoverClear]);

  const handleRankingsMouseEnter = useCallback(() => {
    cancelHoverClear();
  }, [cancelHoverClear]);

  const handleRankingsMouseLeave = useCallback(() => {
    scheduleHoverClear();
  }, [scheduleHoverClear]);

  const handleMetricToggle = useCallback(
    (metricKey: string) => {
      const nextSelected = selectedMetricKeys.includes(metricKey)
        ? selectedMetricKeys.filter((key) => key !== metricKey)
        : [...selectedMetricKeys, metricKey];

      updateParams({
        cols: serialiseExtraColumns(nextSelected),
        page: "1",
      });
    },
    [selectedMetricKeys, updateParams],
  );

  // ── Active filter count ────────────────────────────────────
  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (country) count++;
    if (archetype) count++;
    if (positionGroup || phaseGroup) count++;
    if (modalSlot != null) count++;
    if (provisional !== undefined) count++;
    if (minInnings > 0) count++;
    if (activity !== "active") count++;
    return count;
  }, [
    country,
    archetype,
    positionGroup,
    phaseGroup,
    modalSlot,
    provisional,
    minInnings,
    activity,
  ]);

  // Provisional display value
  const provisionalValue = useMemo(() => {
    if (provisional === true) return "only";
    if (provisional === false) return "hide";
    return "all";
  }, [provisional]);

  // ── Columns ────────────────────────────────────────────────
  const columns = useMemo(
    () =>
      isBowling
        ? getBowlingColumns(
            compareIds,
            handleCompareToggle,
            selectedMetricColumns,
            formMap,
            density,
            selectedMetricKeys,
            formLoading,
          )
        : getBattingColumns(
            compareIds,
            handleCompareToggle,
            selectedMetricColumns,
            formMap,
            density,
            selectedMetricKeys,
            formLoading,
          ),
    [isBowling, compareIds, handleCompareToggle, selectedMetricColumns, formMap, density, selectedMetricKeys, formLoading],
  );

  // Compute the rank offset for the current page
  const rankOffset = (page - 1) * perPage;

  const hoverPlayer = useMemo(
    () =>
      hoverPlayerId != null
        ? (players.find((p) => p.id === hoverPlayerId) ?? null)
        : null,
    [players, hoverPlayerId],
  );

  const hoverRank = useMemo(() => {
    if (hoverPlayerId == null) return null;
    const idx = players.findIndex((p) => p.id === hoverPlayerId);
    if (idx < 0) return null;
    return rankOffset + idx + 1;
  }, [players, hoverPlayerId, rankOffset]);

  const bumpDensity = useCallback(
    (direction: "up" | "down") => {
      const order: Density[] = ["compact", "default", "expanded"];
      const i = order.indexOf(density);
      const next =
        direction === "up"
          ? order[Math.min(order.length - 1, i + 1)]
          : order[Math.max(0, i - 1)];
      handleDensityChange(next);
    },
    [density, handleDensityChange],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const el = e.target as HTMLElement | null;
      if (el?.closest("input, textarea, select, [contenteditable='true'], option")) {
        return;
      }

      const key = e.key;
      if (key === "Escape") {
        if (previewPlayerId) {
          e.preventDefault();
          setPreviewPlayerId(null);
          return;
        }
        if (showColumns) {
          e.preventDefault();
          setShowColumns(false);
          return;
        }
        if (showFilters) {
          e.preventDefault();
          setShowFilters(false);
          return;
        }
        if (hoverPlayerId != null) {
          e.preventDefault();
          setHoverPlayerId(null);
        }
        return;
      }

      if (key === "f" || key === "F") {
        e.preventDefault();
        setShowFilters((v) => !v);
        return;
      }
      if (key === "m" || key === "M") {
        if (availableMetricColumns.length === 0) return;
        e.preventDefault();
        setShowColumns((v) => !v);
        return;
      }
      if (key === "g" || key === "G") {
        e.preventDefault();
        navigate("/glossary");
        return;
      }
      if (key === "c" || key === "C") {
        if (!hoverPlayer) return;
        e.preventDefault();
        handleCompareToggle(hoverPlayer);
        return;
      }
      if (key === "w" || key === "W") {
        e.preventDefault();
        bumpDensity("down");
        return;
      }
      if (key === "e" || key === "E") {
        e.preventDefault();
        bumpDensity("up");
        return;
      }
      if (key === "t" || key === "T") {
        e.preventDefault();
        const zone = rankingsFocusRef.current;
        if (!zone) return;
        if (document.fullscreenElement === zone) {
          void document.exitFullscreen();
        } else {
          void zone.requestFullscreen?.();
        }
        return;
      }
      if (key === "[") {
        const sc = tableScrollRef.current;
        if (!sc) return;
        e.preventDefault();
        sc.scrollBy({ left: -200, behavior: "smooth" });
        return;
      }
      if (key === "]") {
        const sc = tableScrollRef.current;
        if (!sc) return;
        e.preventDefault();
        sc.scrollBy({ left: 200, behavior: "smooth" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    previewPlayerId,
    showColumns,
    showFilters,
    hoverPlayerId,
    hoverPlayer,
    availableMetricColumns.length,
    navigate,
    bumpDensity,
    handleCompareToggle,
  ]);

  const presetOptionsForRole = useMemo(
    () => LEADERBOARD_PRESETS.filter((p) => p.role === roleKey),
    [roleKey],
  );

  const activePresetKey = useMemo(() => {
    const found = presetOptionsForRole.find(
      (p) =>
        sort === p.sort &&
        (order === (p.order ?? "desc")) &&
        (p.phase_group == null || phaseGroup === p.phase_group) &&
        (p.position_group == null || positionGroup === p.position_group),
    );
    return found ? `${found.id}-${found.role}` : "";
  }, [presetOptionsForRole, sort, order, phaseGroup, positionGroup]);

  // ── Micro-insights (Phase 2: data-driven storytelling) ──────
  const microInsights = useMemo(() => {
    const lines: string[] = [];
    if (isBowling && phaseGroup === "death") {
      lines.push("Death specialists: bowling impact in overs 17–20.");
    }
    if (isBowling && phaseGroup === "powerplay") {
      lines.push("Powerplay bowlers: impact in overs 1–6.");
    }
    if (!isBowling && sort === "score_power") {
      lines.push("Power hitters: ranked by power score.");
    }
    if (!isBowling && sort === "score_acceleration") {
      lines.push("Anchors: ranked by acceleration score.");
    }
    if (sort === "peak_window_composite") {
      lines.push("Recent form: ranked by peak-window composite.");
    }
    if (sort === "rating_current" && !phaseGroup && !positionGroup) {
      lines.push("Sorted by Current (recent rolling form, form-capped).");
    }
    if (sort === "rating_overall" && !phaseGroup && !positionGroup) {
      lines.push("Sorted by Career overall (display rating, form-capped).");
    }
    if (sort === "overall_score" && !phaseGroup && !positionGroup) {
      lines.push(
        "Sorted by pipeline overall_score (raw composite — use header Cur/Ovl for display ratings).",
      );
    }
    return lines;
  }, [isBowling, sort, phaseGroup, positionGroup]);

  // ── Render ─────────────────────────────────────────────────
  return (
    <div className="app-page page-stack rankings-page">
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {sortAnnouncement}
      </span>
      {/* ── Unified toolbar (dataset, role, sort, table tools) ─ */}
      <section className="section-card overflow-hidden rounded-2xl border border-surface-elevated shadow-sm">
        <div className="section-card-body space-y-5 p-4 md:p-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex min-w-0 flex-col gap-3">
              <div className="flex shrink-0 items-start gap-3">
                <Trophy
                  size={28}
                  className="mt-0.5 shrink-0 text-text-muted"
                  aria-hidden
                />
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Who is best at what?</p>
                  <h1 className="page-title">Leaderboards</h1>
                  <p className="mt-1 text-xs text-text-secondary max-w-lg">
                    Role-aware, phase-aware, era-adjusted rankings built from ball-by-ball data.
                    {(sort !== (DEFAULT_SORT[role] ?? "rating_current") ||
                      order !== "desc") && (
                      <span className="text-text-muted">
                        {" "}Sorted by {SORT_LABEL_MAP[sort] ?? sort}
                        {order === "asc" ? " (ascending)" : ""}.
                      </span>
                    )}
                  </p>
                </div>
              </div>
            </div>

            <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center">
              <div
                className="inline-flex rounded-xl border border-surface-elevated bg-surface-elevated/25 p-1 dark:bg-surface-elevated/40"
                role="group"
                aria-label="Batting or bowling leaderboard"
              >
                <button
                  type="button"
                  onClick={() => handleRoleToggle("bat")}
                  className={`rounded-lg px-5 py-2.5 text-sm font-semibold transition-colors duration-200 ease-out-quart ${
                    !isBowling
                      ? "bg-primary text-white dark:text-background shadow-sm"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                  aria-pressed={!isBowling}
                >
                  Batting
                </button>
                <button
                  type="button"
                  onClick={() => handleRoleToggle("bowl")}
                  className={`rounded-lg px-5 py-2.5 text-sm font-semibold transition-colors duration-200 ease-out-quart ${
                    isBowling
                      ? "bg-primary text-white dark:text-background shadow-sm"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                  aria-pressed={isBowling}
                >
                  Bowling
                </button>
              </div>
            </div>
          </div>

          <div className="border-t border-surface-elevated/70 pt-5">
            <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
              <div className="flex min-w-0 flex-1 flex-col gap-4 lg:flex-row lg:items-end lg:gap-6">
                <div className="flex w-full flex-col gap-1.5 sm:max-w-[14rem]">
                  <label
                    htmlFor="rk-quick-view"
                    className="text-[11px] font-semibold uppercase tracking-wider text-text-muted"
                  >
                    Quick view
                  </label>
                  <select
                    id="rk-quick-view"
                    value={activePresetKey}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (!v) return;
                      const preset = presetOptionsForRole.find(
                        (p) => `${p.id}-${p.role}` === v,
                      );
                      if (preset) handlePreset(preset);
                    }}
                    className="filter-select h-10 w-full text-sm"
                  >
                    <option value="">Custom sort…</option>
                    {presetOptionsForRole.map((p) => (
                      <option key={`${p.id}-${p.role}`} value={`${p.id}-${p.role}`}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="min-w-0 flex-1 space-y-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Sort metric
                  </div>
                  <div className="rounded-2xl border border-surface-elevated/80 bg-surface-elevated/15 p-2 dark:bg-surface-elevated/25">
                    <div className="flex flex-wrap gap-1.5">
                      {getQuickSortOptions(isBowling).map((opt) => (
                        <MetricTooltip
                          key={opt.key}
                          metric={opt.key}
                          mode="wrap"
                          className="inline-flex"
                          delay={200}
                        >
                          <button
                            type="button"
                            onClick={() => handleSort(opt.key)}
                            className={`flex min-h-10 items-center gap-1 rounded-lg px-3 py-2 text-xs font-semibold transition-colors duration-200 ease-out-quart sm:min-h-0 sm:py-1.5 ${
                              sort === opt.key
                                ? "bg-primary text-white dark:text-background shadow-sm"
                                : "bg-surface/90 text-text-secondary hover:bg-surface-elevated hover:text-text-primary dark:bg-surface/50"
                            }`}
                            title={`Sort by ${opt.label}`}
                          >
                            {opt.shortLabel ?? opt.label}
                            {sort === opt.key &&
                              (order === "desc" ? (
                                <ArrowDown size={11} strokeWidth={2.5} />
                              ) : (
                                <ArrowUp size={11} strokeWidth={2.5} />
                              ))}
                          </button>
                        </MetricTooltip>
                      ))}
                      {availableMetricColumns.length > 0 && (
                        <select
                          value={sortSelectValue}
                          onChange={(e) => {
                            if (!e.target.value) return;
                            handleSort(e.target.value);
                          }}
                          className="filter-select h-9 min-w-[10.5rem] flex-1 text-xs sm:flex-none"
                          aria-label="Sort by another metric"
                        >
                          <option value="">More metrics…</option>
                          {availableMetricColumns.map((metric) => (
                            <option key={metric.key} value={metric.key}>
                              {metric.label}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t border-surface-elevated/50 pt-4 2xl:border-t-0 2xl:pt-0">
                <div
                  className="flex items-center gap-0.5 rounded-xl border border-surface-elevated/80 bg-surface-elevated/15 p-1 dark:bg-surface-elevated/25"
                  role="group"
                  aria-label="Table density"
                >
                  {(["compact", "default", "expanded"] as const).map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => handleDensityChange(d)}
                      className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors duration-200 ease-out-quart ${
                        density === d
                          ? "bg-primary text-white dark:text-background shadow-sm"
                          : "text-text-secondary hover:text-text-primary"
                      }`}
                      title={
                        d === "compact"
                          ? "Compact rows"
                          : d === "expanded"
                            ? "Expanded rows"
                            : "Default row height"
                      }
                    >
                      {d === "compact"
                        ? "Compact"
                        : d === "expanded"
                          ? "Expanded"
                          : "Default"}
                    </button>
                  ))}
                </div>

                {availableMetricColumns.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setShowColumns(!showColumns)}
                    className={`btn-secondary btn-sm relative shrink-0 ${
                      showColumns ? "ring-2 ring-primary ring-offset-2 ring-offset-background" : ""
                    }`}
                    aria-expanded={showColumns}
                  >
                    <Columns3 size={14} />
                    <span>Columns</span>
                    {selectedMetricKeys.length > 0 && (
                      <span className="absolute -right-1 -top-1 flex min-w-[1.125rem] items-center justify-center rounded-full bg-accent px-1 text-[10px] font-bold text-white">
                        {selectedMetricKeys.length}
                      </span>
                    )}
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => setShowFilters(!showFilters)}
                  className={`btn-secondary btn-sm relative shrink-0 ${
                    showFilters ? "ring-2 ring-primary ring-offset-2 ring-offset-background" : ""
                  }`}
                  aria-expanded={showFilters}
                >
                  <SlidersHorizontal size={14} />
                  <span>Filters</span>
                  {activeFilterCount > 0 && (
                    <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-accent text-[10px] font-bold text-white">
                      {activeFilterCount}
                    </span>
                  )}
                </button>
              </div>
            </div>
          </div>

          {microInsights.length > 0 && (
            <p className="border-t border-surface-elevated/60 pt-4 text-xs leading-relaxed text-text-secondary">
              {microInsights.join(" · ")}
            </p>
          )}
        </div>
      </section>

      {/* ── Column Picker ────────────────────────────────────── */}
      {showColumns && availableMetricColumns.length > 0 && (
        <div className="card p-4 animate-slide-up">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div>
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <Columns3 size={14} />
                <span>Optional stats</span>
              </div>
              <p className="text-xs text-text-muted mt-1">
                Add advanced metrics to the leaderboard and sort them directly
                from the table.
              </p>
            </div>
            {selectedMetricKeys.length > 0 && (
              <button
                onClick={() => updateParams({ cols: null, page: "1" })}
                className="text-xs text-primary hover:text-primary-hover transition-colors"
              >
                Reset columns
              </button>
            )}
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            {availableMetricColumns.map((metric) => {
              const isSelected = selectedMetricKeys.includes(metric.key);
              return (
                <button
                  key={metric.key}
                  onClick={() => handleMetricToggle(metric.key)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                    isSelected
                      ? "border-primary/80 bg-slate-100 text-text-primary ring-1 ring-primary/25 dark:bg-surface"
                      : "border-surface-elevated bg-surface-elevated/30 text-text-secondary hover:text-text-primary hover:border-primary/40"
                  }`}
                >
                  <div className="font-medium">{metric.label}</div>
                  <div className="text-[11px] text-text-muted mt-0.5">
                    {metric.shortLabel ?? metric.label}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Filter Bar ───────────────────────────────────────── */}
      {showFilters && (
        <div className="card p-4 animate-slide-up">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-sm text-text-secondary">
              <Filter size={14} />
              <span>Filters</span>
              {activeFilterCount > 0 && (
                <span className="text-xs text-text-muted">
                  ({activeFilterCount} active)
                </span>
              )}
            </div>
            {activeFilterCount > 0 && (
              <button
                onClick={handleClearFilters}
                className="text-xs text-primary hover:text-primary-hover transition-colors"
              >
                Clear all
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            {/* Country */}
            <div>
              <label
                htmlFor="rk-filter-country"
                className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
              >
                Country
              </label>
              <select
                id="rk-filter-country"
                value={country ?? ""}
                onChange={(e) =>
                  updateParams({ country: e.target.value || null, page: "1" })
                }
                className="filter-select w-full"
              >
                <option value="">All Countries</option>
                {countries.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            {/* Archetype */}
            <div>
              <label
                htmlFor="rk-filter-archetype"
                className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
              >
                Archetype
              </label>
              <select
                id="rk-filter-archetype"
                value={archetype ?? ""}
                onChange={(e) =>
                  updateParams({ archetype: e.target.value || null, page: "1" })
                }
                className="filter-select w-full"
              >
                <option value="">All Archetypes</option>
                {archetypeOptions.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>

            {/* Position + modal slot (batting) / Phase (bowling) */}
            {!isBowling ? (
              <>
                <div>
                  <label
                    htmlFor="rk-filter-position"
                    className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                  >
                    Position
                  </label>
                  <select
                    id="rk-filter-position"
                    value={positionGroup ?? ""}
                    onChange={(e) =>
                      updateParams({
                        position_group: e.target.value || null,
                        page: "1",
                      })
                    }
                    className="filter-select w-full"
                  >
                    <option value="">All Positions</option>
                    <option value="top_order">Top Order</option>
                    <option value="middle_order">Middle Order</option>
                    <option value="lower_order">Lower Order</option>
                    <option value="opener">Opener</option>
                  </select>
                </div>
                <div>
                  <label
                    htmlFor="rk-filter-modal-slot"
                    className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                  >
                    Modal slot
                  </label>
                  <select
                    id="rk-filter-modal-slot"
                    value={modalSlot != null ? String(modalSlot) : ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      updateParams({
                        modal_slot: v ? v : null,
                        page: "1",
                      });
                    }}
                    className="filter-select w-full"
                    title="Filter by most common batting-order position (1–11) in the dataset"
                  >
                    <option value="">All slots</option>
                    {Array.from({ length: 11 }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={String(n)}>
                        #{n}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            ) : (
              <div>
                <label
                  htmlFor="rk-filter-phase"
                  className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                >
                  Phase Group
                </label>
                <select
                  id="rk-filter-phase"
                  value={phaseGroup ?? ""}
                  onChange={(e) =>
                    updateParams({
                      phase_group: e.target.value || null,
                      page: "1",
                    })
                  }
                  className="filter-select w-full"
                >
                  <option value="">All Phases</option>
                  <option value="powerplay">Powerplay</option>
                  <option value="middle">Middle</option>
                  <option value="death">Death</option>
                </select>
              </div>
            )}

            {/* Active / retired (format-specific recency) */}
            <div>
              <label
                htmlFor="rk-filter-activity"
                className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
              >
                Player pool
              </label>
              <select
                id="rk-filter-activity"
                value={activity}
                onChange={(e) => {
                  const val = e.target.value as "active" | "retired" | "all";
                  updateParams({
                    activity: val === "active" ? null : val,
                    page: "1",
                  });
                }}
                className="filter-select w-full"
              >
                <option value="active">Active only</option>
                <option value="retired">Retired / inactive</option>
                <option value="all">Everyone</option>
              </select>
              <p className="text-[10px] text-text-muted mt-1 leading-snug">
                {isFranchiseFormat(format)
                  ? "Active = at least one franchise match in the last 2 years."
                  : "Active = at least one international T20 in the last year."}
              </p>
            </div>

            {/* Provisional */}
            <div>
              <label
                htmlFor="rk-filter-provisional"
                className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
              >
                Provisional
              </label>
              <select
                id="rk-filter-provisional"
                value={provisionalValue}
                onChange={(e) => {
                  const val = e.target.value;
                  if (val === "hide")
                    updateParams({ provisional: "false", page: "1" });
                  else if (val === "only")
                    updateParams({ provisional: "true", page: "1" });
                  else updateParams({ provisional: null, page: "1" });
                }}
                className="filter-select w-full"
              >
                <option value="all">Show All</option>
                <option value="hide">Hide Provisional</option>
                <option value="only">Only Provisional</option>
              </select>
            </div>

            {/* Min innings */}
            <div>
              <label
                htmlFor="rk-filter-min-innings"
                className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
              >
                Min {isBowling ? "Matches" : "Innings"}
              </label>
              <input
                id="rk-filter-min-innings"
                type="number"
                min={0}
                max={500}
                step={1}
                value={minInnings || ""}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  updateParams({
                    min_innings: isNaN(val) || val <= 0 ? null : String(val),
                    page: "1",
                  });
                }}
                placeholder="0"
                className="filter-input w-full"
              />
            </div>
          </div>
        </div>
      )}

      {/* ── Compare Bar ──────────────────────────────────────── */}
      {compareIds.size > 0 && (
        <div className="sticky top-14 z-30 bg-surface border border-surface-elevated rounded-lg p-3 flex items-center justify-between gap-3 shadow-card animate-slide-up">
          <div className="flex items-center gap-2 text-sm">
            <GitCompare size={16} className="text-primary" />
            <span className="text-text-secondary">
              {compareIds.size} player{compareIds.size !== 1 ? "s" : ""}{" "}
              selected
            </span>
            <button
              onClick={() => setCompareIds(new Set())}
              className="text-xs text-text-muted hover:text-text-primary transition-colors"
            >
              Clear
            </button>
          </div>
          <button
            onClick={handleCompareNavigate}
            disabled={compareIds.size < 2}
            className="btn-primary btn-sm"
          >
            Compare ({compareIds.size}/4) →
          </button>
        </div>
      )}

      {/* ── Summary row ──────────────────────────────────────── */}
      <div className="flex items-center justify-between text-sm text-text-secondary pt-2">
        <span>
          {isLoading ? (
            <span className="skeleton-text w-32 h-4 inline-block" />
          ) : (
            <>
              Showing{" "}
              <span className="font-medium text-text-primary">
                {totalPlayers > 0
                  ? `${rankOffset + 1}–${Math.min(
                      rankOffset + perPage,
                      totalPlayers,
                    )}`
                  : "0"}
              </span>{" "}
              of{" "}
              <span className="font-medium text-text-primary">
                {totalPlayers.toLocaleString()}
              </span>{" "}
              {isBowling ? "bowlers" : "batters"}
            </>
          )}
        </span>
        {isFetching && !isLoading && (
          <span className="text-xs text-text-muted animate-pulse">
            Updating…
          </span>
        )}
      </div>

      {!isLoading && !error && players.length > 0 && (
        <RankingsChartsPanel
          key={roleKey}
          players={players}
          isBowling={isBowling}
          optionalScatterMetrics={availableMetricColumns.map((c) => ({
            key: c.key,
            label: c.label,
          }))}
          distributionFilters={distributionFilters}
          distributionMetricOptions={distributionMetricOptions}
          tableSortMetric={sort}
        />
      )}

      {/* ── Loading State ─────────────────────────────────────── */}
      {isLoading && (
        <div className="card p-0 overflow-hidden">
          <div className="space-y-0">
            {Array.from({ length: 10 }).map((_, i) => (
              <div
                key={i}
                className="flex items-center gap-3 px-3 py-3 border-b border-surface-elevated/50"
              >
                <div className="skeleton w-5 h-5 rounded" />
                <div className="skeleton w-6 h-4 rounded" />
                <div className="skeleton-text w-32 h-4" />
                <div className="flex-1" />
                <div className="skeleton w-12 h-4 rounded" />
                <div className="skeleton w-12 h-4 rounded" />
                <div className="skeleton w-12 h-4 rounded" />
                <div className="skeleton w-16 h-5 rounded" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Error State ──────────────────────────────────────── */}
      {error && !isLoading && (
        <PageError
          variant={isDatasetUnavailableError(error) ? "dataset" : "default"}
          title={
            isDatasetUnavailableError(error)
              ? "Dataset not loaded"
              : "Failed to load rankings"
          }
          message={
            isDatasetUnavailableError(error) && error instanceof ApiError
              ? String(error.detail)
              : "Could not fetch the leaderboard data. The backend might be unavailable."
          }
          onRetry={
            isDatasetUnavailableError(error) ? undefined : () => refetch()
          }
        />
      )}

      {/* ── Empty State ──────────────────────────────────────── */}
      {!isLoading && !error && totalPlayers === 0 && (
        <div className="text-center py-16">
          <div className="text-2xl mb-4 font-semibold text-primary">No Results</div>
          <h2 className="text-h3 text-text-primary mb-2">
            No {isBowling ? "bowlers" : "batters"} found
          </h2>
          <p className="text-sm text-text-secondary max-w-md mx-auto mb-4">
            No players match the current filter combination. Try broadening your
            filters or switching between batting and bowling.
          </p>
          {activeFilterCount > 0 && (
            <button
              onClick={handleClearFilters}
              className="btn-secondary btn-sm"
            >
              Clear All Filters
            </button>
          )}
        </div>
      )}

      {/* ── Data Table + hover sidebar ───────────────────────── */}
      {!isLoading && !error && players.length > 0 && (
        <div
          ref={rankingsFocusRef}
          className={`rankings-table-shell lg:grid lg:grid-cols-[minmax(0,1fr)_17rem] xl:grid-cols-[minmax(0,1fr)_19.25rem] lg:items-start lg:gap-4 ${
            hoverPlayer ? "pb-24 lg:pb-0" : ""
          }`}
          onMouseEnter={handleRankingsMouseEnter}
          onMouseLeave={handleRankingsMouseLeave}
        >
        <div className="card min-w-0 overflow-hidden p-0 shadow-sm dark:shadow-[0_20px_56px_-36px_rgba(0,0,0,0.65)]">
          <AdvancedContextFilters
            chaseHighRpo={chaseHighRpo}
            playoffsOnly={playoffsOnly}
            inningsPhase={inningsPhase}
            onChaseHighRpoChange={handleCtxChaseChange}
            onPlayoffsOnlyChange={handleCtxPlayoffsChange}
            onInningsPhaseChange={handleCtxInningsPhaseChange}
            onClearContext={handleClearContextFilters}
          />
          <p className="sm:hidden px-4 pb-2 pt-3 text-xs text-text-muted">
            Swipe horizontally to see all columns.
          </p>
          <div className="relative">
            {tableOverlay && (
              <div
                className="pointer-events-none absolute inset-0 z-20 flex flex-col justify-center gap-2.5 bg-surface/50 px-4 py-8 backdrop-blur-[0.5px]"
                aria-hidden
              >
                {Array.from({ length: 8 }).map((_, i) => (
                  <div
                    key={i}
                    className="table-refresh-shimmer h-3 max-w-full rounded-md"
                    style={{ width: `${68 + ((i * 19) % 28)}%` }}
                  />
                ))}
              </div>
            )}
            <div
              ref={tableScrollRef}
              className={`overflow-x-auto overscroll-x-contain transition-opacity duration-200 ${
                tableOverlay ? "pointer-events-none opacity-[0.38]" : ""
              }`}
            >
            <table className="sortable-table" role="grid">
              <thead>
                <tr>
                  {columns.map((col) => {
                    if (col.key === "overall") {
                      const curActive = sort === "rating_current";
                      const ovlActive = sort === "rating_overall";
                      const ratingsSortActive = curActive || ovlActive;
                      return (
                        <th
                          key={col.key}
                          className={`text-center ${col.width ?? ""} ${
                            col.hideOnMobile ? "hidden lg:table-cell" : ""
                          }`}
                          scope="col"
                          aria-sort={
                            ratingsSortActive
                              ? order === "asc"
                                ? "ascending"
                                : "descending"
                              : undefined
                          }
                        >
                          <div className="flex flex-col items-center gap-0.5 px-0.5">
                            <div className="flex items-center justify-center gap-0.5 flex-wrap">
                              <button
                                type="button"
                                className={`inline-flex items-center gap-0.5 rounded px-0.5 text-[10px] font-semibold uppercase tracking-wide transition-colors ${
                                  curActive
                                    ? "text-primary"
                                    : "text-text-muted hover:text-text-primary"
                                }`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSort("rating_current");
                                }}
                                title="Sort by Current (recent form)"
                              >
                                Cur
                                {curActive &&
                                  (order === "desc" ? (
                                    <ArrowDown size={10} className="shrink-0" />
                                  ) : (
                                    <ArrowUp size={10} className="shrink-0" />
                                  ))}
                              </button>
                              <span
                                className="text-text-muted/40 text-[10px]"
                                aria-hidden
                              >
                                /
                              </span>
                              <button
                                type="button"
                                className={`inline-flex items-center gap-0.5 rounded px-0.5 text-[10px] font-semibold uppercase tracking-wide transition-colors ${
                                  ovlActive
                                    ? "text-primary"
                                    : "text-text-muted hover:text-text-primary"
                                }`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSort("rating_overall");
                                }}
                                title="Sort by Career overall (display rating)"
                              >
                                Ovl
                                {ovlActive &&
                                  (order === "desc" ? (
                                    <ArrowDown size={10} className="shrink-0" />
                                  ) : (
                                    <ArrowUp size={10} className="shrink-0" />
                                  ))}
                              </button>
                            </div>
                            <div className="flex items-center justify-center gap-1 normal-case">
                              <span className="text-[9px] text-text-muted/70 hidden sm:inline">
                                ratings
                              </span>
                              <MetricColumnHeaderTooltip
                                lookupKey="leaderboard_ratings_column"
                                label="ⓘ"
                                triggerClassName="text-[10px] leading-none text-text-muted/80 font-sans not-italic"
                              />
                            </div>
                          </div>
                        </th>
                      );
                    }

                    const isSortable = !!col.sortKey;
                    const isCurrentSort = col.sortKey && sort === col.sortKey;
                    const alignClass =
                      col.align === "right"
                        ? "text-right"
                        : col.align === "center"
                          ? "text-center"
                          : "text-left";

                    const headerLookup = columnHeaderLookupKey(col, isBowling);
                    const headerHasTooltip =
                      headerLookup != null && headerLookup !== "";
                    const sortByHeaderClick =
                      isSortable && col.sortKey && !headerHasTooltip;

                    const headerFlexAlign =
                      col.align === "right"
                        ? "justify-end"
                        : col.align === "center"
                          ? "justify-center"
                          : "justify-start";

                    const headerLabel = (col.shortLabel ?? col.label).trim() || "•";

                    return (
                      <th
                        key={col.key}
                        className={`${alignClass} ${col.width ?? ""} ${
                          col.hideOnMobile ? "hidden lg:table-cell" : ""
                        } ${
                          col.key === "name" ? "sticky-col-first" : ""
                        } ${sortByHeaderClick ? "cursor-pointer select-none" : ""} ${
                          isCurrentSort ? "text-primary" : ""
                        }`}
                        onClick={
                          sortByHeaderClick && col.sortKey
                            ? () => handleSort(col.sortKey!)
                            : undefined
                        }
                        scope="col"
                        aria-sort={
                          isCurrentSort
                            ? order === "asc"
                              ? "ascending"
                              : "descending"
                            : undefined
                        }
                      >
                        {headerHasTooltip ? (
                          <span
                            className={`inline-flex w-full min-w-0 items-center gap-1 ${headerFlexAlign}`}
                          >
                            <MetricColumnHeaderTooltip
                              lookupKey={headerLookup}
                              label={headerLabel}
                              warMetricKey={col.metricKey}
                            />
                            {isSortable && col.sortKey && (
                              <button
                                type="button"
                                className="inline-flex shrink-0 items-center rounded p-0.5 text-text-secondary hover:text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                                aria-label={`Sort by ${col.label}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSort(col.sortKey!);
                                }}
                              >
                                {isCurrentSort ? (
                                  order === "desc" ? (
                                    <ArrowDown size={10} />
                                  ) : (
                                    <ArrowUp size={10} />
                                  )
                                ) : (
                                  <ArrowUpDown size={10} className="opacity-30" />
                                )}
                              </button>
                            )}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1">
                            {col.shortLabel ?? col.label}
                            {isSortable && (
                              <>
                                {isCurrentSort ? (
                                  order === "desc" ? (
                                    <ArrowDown size={10} />
                                  ) : (
                                    <ArrowUp size={10} />
                                  )
                                ) : (
                                  <ArrowUpDown size={10} className="opacity-30" />
                                )}
                              </>
                            )}
                          </span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {players.map((player, index) => {
                  const rank = rankOffset + index + 1;
                  const isSelected = compareIds.has(player.id);
                  const cellPaddingStyle =
                    density === "compact"
                      ? { paddingTop: 7, paddingBottom: 7 }
                      : density === "expanded"
                        ? { paddingTop: 18, paddingBottom: 18 }
                        : { paddingTop: 12, paddingBottom: 12 };

                  return (
                    <tr
                      key={player.id}
                      onMouseEnter={() => {
                        cancelHoverClear();
                        setHoverPlayerId(player.id);
                      }}
                      onClick={(e) => {
                        if (!coarsePointer) return;
                        const t = e.target as HTMLElement;
                        if (t.closest("a, button")) return;
                        setHoverPlayerId((prev) =>
                          prev === player.id ? null : player.id,
                        );
                      }}
                      className={`cursor-pointer transition-colors ${
                        isSelected ? "bg-slate-100/90 dark:bg-surface" : "hover:bg-surface-elevated/50"
                      } ${
                        hoverPlayerId === player.id
                          ? "rankings-row-hovered bg-slate-100/80 dark:bg-surface dark:ring-1 dark:ring-inset dark:ring-primary/35"
                          : ""
                      }`}
                    >
                      {columns.map((col) => {
                        const alignClass =
                          col.align === "right"
                            ? "text-right"
                            : col.align === "center"
                              ? "text-center"
                              : "text-left";

                        return (
                          <td
                            key={col.key}
                            className={`${alignClass} ${col.width ?? ""} ${
                              col.hideOnMobile ? "hidden lg:table-cell" : ""
                            } ${col.key === "name" ? "sticky-col-first" : ""}`}
                            style={cellPaddingStyle}
                          >
                            {col.render(player, rank)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </div>
        </div>

        <aside
          className="mt-4 hidden min-w-0 flex-col lg:mt-0 lg:flex lg:sticky lg:top-[4.5rem] lg:self-start"
          aria-label="Row highlight and shortcuts"
        >
          <LeaderboardHoverSidebar
            players={players}
            displayPlayer={hoverPlayer}
            displayRank={hoverRank}
            isBowling={isBowling}
            selectedMetricKeys={selectedMetricKeys}
            formMap={formMap}
            formLoading={formLoading}
            onOpenFullPreview={(id) => setPreviewPlayerId(id)}
          />
        </aside>

        {hoverPlayer && (
          <div
            className="fixed inset-x-0 bottom-0 z-30 border-t border-surface-elevated bg-surface/95 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-[0_-12px_40px_-16px_rgba(0,0,0,0.45)] backdrop-blur-md lg:hidden"
            role="status"
            aria-live="polite"
          >
            <div className="mx-auto flex max-w-7xl items-start gap-3">
              <PlayerAvatar
                name={hoverPlayer.name}
                playerId={hoverPlayer.id}
                photoUrl={hoverPlayer.photo_url}
                size="md"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-text-primary">
                  {hoverPlayer.name}
                </p>
                <p className="text-[11px] text-text-secondary">
                  {fmtScore(primaryDisplayRating(hoverPlayer))} cur ·{" "}
                  {fmtScore(careerDisplayRating(hoverPlayer))} ovl
                  {!isBowling && (
                    <>
                      {" · "}
                      {fmtSR(hoverPlayer.career_sr)} SR
                    </>
                  )}
                  {isBowling && (
                    <>
                      {" · "}
                      {fmtEcon(hoverPlayer.career_sr)} econ
                    </>
                  )}
                </p>
              </div>
              <div className="flex shrink-0 flex-col gap-1.5">
                <button
                  type="button"
                  className="btn-primary btn-sm whitespace-nowrap"
                  onClick={() => setPreviewPlayerId(hoverPlayer.id)}
                >
                  Preview
                </button>
                <button
                  type="button"
                  className="btn-ghost btn-sm text-xs text-text-muted"
                  onClick={() => setHoverPlayerId(null)}
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        )}
        </div>
      )}

      {/* ── Pagination ───────────────────────────────────────── */}
      {!isLoading && !error && totalPlayers > 0 && (
        <Pagination
          page={page}
          totalPages={totalPages}
          total={totalPlayers}
          perPage={perPage}
          onPageChange={handlePageChange}
          onPerPageChange={handlePerPageChange}
          showSummary
          showPerPage
          perPageOptions={[10, 25, 50, 100]}
        />
      )}

      {/* ── Right-side preview panel (Phase 2) ────────────────── */}
      {previewPlayerId && (
        <LeaderboardPreviewPanel
          playerId={previewPlayerId}
          isBowling={isBowling}
          onClose={() => setPreviewPlayerId(null)}
        />
      )}
    </div>
  );
}

// ── Quick sort options ───────────────────────────────────────────

interface QuickSortOption {
  key: string;
  label: string;
  shortLabel?: string;
}

function getQuickSortOptions(isBowling: boolean): QuickSortOption[] {
  if (isBowling) {
    return [
      { key: "rating_current", label: "Current", shortLabel: "Current" },
      { key: "rating_overall", label: "Career overall", shortLabel: "Overall" },
      { key: "score_accuracy", label: "Accuracy", shortLabel: "ACC" },
      { key: "score_control", label: "Control", shortLabel: "CTL" },
      { key: "score_threat", label: "Threat", shortLabel: "THR" },
      { key: "career_sr", label: "Economy", shortLabel: "Econ" },
      { key: "total_runs", label: "Wickets", shortLabel: "Wkts" },
      { key: "war_bowling", label: "WAR", shortLabel: "WAR" },
    ];
  }
  return [
    { key: "rating_current", label: "Current", shortLabel: "Current" },
    { key: "rating_overall", label: "Career overall", shortLabel: "Overall" },
    { key: "score_acceleration", label: "Acceleration", shortLabel: "ACL" },
    { key: "score_power", label: "Power", shortLabel: "POW" },
    { key: "score_control", label: "Control", shortLabel: "CTL" },
    { key: "career_sr", label: "Strike Rate", shortLabel: "SR" },
    { key: "total_runs", label: "Runs", shortLabel: "Runs" },
    { key: "war_batting", label: "WAR", shortLabel: "WAR" },
    { key: "clutch_index", label: "Pressure Score", shortLabel: "Pressure" },
  ];
}
