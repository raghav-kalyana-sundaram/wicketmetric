/**
 * Rankings / Leaderboard page — sortable, filterable player rankings.
 *
 * Route: /rankings?role=bat&sort=overall_score&order=desc&country=...&archetype=...
 *
 * Features (from gui.md § 6.4):
 *   - Toggle between Batting and Bowling leaderboards
 *   - Sortable column headers (click to sort, click again to reverse)
 *   - Filters: country, archetype, position/phase group, min innings, provisional
 *   - Pagination with page size selector
 *   - Checkbox column for selecting players to compare (max 4)
 *   - "Compare Selected" button appears when ≥2 selected
 *   - Each player name links to their profile
 *   - URL-driven state: all filters/sort/page in query params
 *   - Responsive: horizontal scroll on mobile with sticky first column
 *
 * Data fetching:
 *   - useBattingRankings() or useBowlingRankings() based on role
 *   - useCountries() and useArchetypes() for filter dropdowns
 *   - useBattingSortColumns() / useBowlingSortColumns() for available sorts
 */

import { useState, useCallback, useMemo } from "react";
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
} from "lucide-react";
import GradeBadge from "@/components/GradeBadge";
import { ScoreBarMini } from "@/components/ScoreBar";
import Pagination from "@/components/Pagination";
import { PageError } from "@/components/Layout";
import {
  useBattingRankings,
  useBowlingRankings,
  useCountries,
  useArchetypes,
} from "@/api/queries";
import { scoreToColour } from "@/lib/colours";
import {
  fmtScore,
  fmtInt,
  fmtSR,
  fmtEcon,
  fmtAvg,
  countryFlag,
  countryShort,
  parseIntParam,
  parseBoolParam,
} from "@/lib/format";
import type { PlayerSummary, LeaderboardParams } from "@/api/types";

// ── Column definitions ───────────────────────────────────────────

interface ColumnDef {
  key: string;
  label: string;
  shortLabel?: string;
  sortKey?: string;
  align?: "left" | "center" | "right";
  /** Width class (Tailwind). */
  width?: string;
  /** If true, this column is hidden on small screens. */
  hideOnMobile?: boolean;
  /** Render function. */
  render: (player: PlayerSummary, rank: number) => React.ReactNode;
}

function getBattingColumns(
  compareIds: Set<string>,
  onCompareToggle: (player: PlayerSummary) => void,
): ColumnDef[] {
  return [
    {
      key: "compare",
      label: "",
      width: "w-8",
      align: "center",
      render: (player) => (
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onCompareToggle(player);
          }}
          className={`h-5 w-5 rounded border flex items-center justify-center transition-colors ${
            compareIds.has(player.id)
              ? "bg-primary border-primary text-white"
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
      width: "min-w-[10rem]",
      align: "left",
      render: (player) => (
        <Link
          to={`/player/${player.id}`}
          className="flex items-center gap-1.5 hover:text-primary transition-colors group"
        >
          <span className="font-medium text-text-primary group-hover:text-primary truncate max-w-[9rem]">
            {player.name}
          </span>
          {player.is_provisional && (
            <span
              className="text-[10px] text-warning shrink-0"
              title="Provisional"
            >
              ⚠
            </span>
          )}
        </Link>
      ),
    },
    {
      key: "country",
      label: "Country",
      shortLabel: "Ctry",
      width: "w-16",
      align: "center",
      hideOnMobile: true,
      render: (player) => (
        <span className="text-xs" title={player.country}>
          {countryFlag(player.country) || countryShort(player.country)}
        </span>
      ),
    },
    {
      key: "archetype",
      label: "Archetype",
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
      key: "innings",
      label: "Inn",
      sortKey: "innings_count",
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
      label: "ACL",
      sortKey: "score_acceleration",
      width: "w-20",
      align: "right",
      render: (player) => <ScoreBarMini value={player.score_1} width={40} />,
    },
    {
      key: "score_2",
      label: "POW",
      sortKey: "score_power",
      width: "w-20",
      align: "right",
      render: (player) => <ScoreBarMini value={player.score_2} width={40} />,
    },
    {
      key: "score_3",
      label: "CTL",
      sortKey: "score_control",
      width: "w-20",
      align: "right",
      render: (player) => <ScoreBarMini value={player.score_3} width={40} />,
    },
    {
      key: "overall",
      label: "Overall",
      sortKey: "overall_score",
      width: "w-20",
      align: "center",
      render: (player) => (
        <div className="flex items-center gap-1.5 justify-center">
          <span
            className="font-score tabular-nums text-sm font-semibold"
            style={{ color: scoreToColour(player.overall_score) }}
          >
            {fmtScore(player.overall_score)}
          </span>
          <GradeBadge grade={player.grade_overall} size="xs" />
        </div>
      ),
    },
    {
      key: "actions",
      label: "",
      width: "w-8",
      align: "center",
      render: (player) => (
        <Link
          to={`/player/${player.id}`}
          className="text-text-muted hover:text-primary transition-colors"
          title="View profile"
        >
          <ChevronRight size={14} />
        </Link>
      ),
    },
  ];
}

function getBowlingColumns(
  compareIds: Set<string>,
  onCompareToggle: (player: PlayerSummary) => void,
): ColumnDef[] {
  return [
    {
      key: "compare",
      label: "",
      width: "w-8",
      align: "center",
      render: (player) => (
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onCompareToggle(player);
          }}
          className={`h-5 w-5 rounded border flex items-center justify-center transition-colors ${
            compareIds.has(player.id)
              ? "bg-primary border-primary text-white"
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
      width: "min-w-[10rem]",
      align: "left",
      render: (player) => (
        <Link
          to={`/player/${player.id}`}
          className="flex items-center gap-1.5 hover:text-primary transition-colors group"
        >
          <span className="font-medium text-text-primary group-hover:text-primary truncate max-w-[9rem]">
            {player.name}
          </span>
          {player.is_provisional && (
            <span
              className="text-[10px] text-warning shrink-0"
              title="Provisional"
            >
              ⚠
            </span>
          )}
        </Link>
      ),
    },
    {
      key: "country",
      label: "Country",
      shortLabel: "Ctry",
      width: "w-16",
      align: "center",
      hideOnMobile: true,
      render: (player) => (
        <span className="text-xs" title={player.country}>
          {countryFlag(player.country) || countryShort(player.country)}
        </span>
      ),
    },
    {
      key: "archetype",
      label: "Archetype",
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
      key: "matches",
      label: "Mat",
      sortKey: "innings_count",
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
      label: "ACC",
      sortKey: "score_accuracy",
      width: "w-20",
      align: "right",
      render: (player) => <ScoreBarMini value={player.score_1} width={40} />,
    },
    {
      key: "score_2",
      label: "CTL",
      sortKey: "score_control",
      width: "w-20",
      align: "right",
      render: (player) => <ScoreBarMini value={player.score_2} width={40} />,
    },
    {
      key: "score_3",
      label: "THR",
      sortKey: "score_threat",
      width: "w-20",
      align: "right",
      render: (player) => <ScoreBarMini value={player.score_3} width={40} />,
    },
    {
      key: "overall",
      label: "Overall",
      sortKey: "overall_score",
      width: "w-20",
      align: "center",
      render: (player) => (
        <div className="flex items-center gap-1.5 justify-center">
          <span
            className="font-score tabular-nums text-sm font-semibold"
            style={{ color: scoreToColour(player.overall_score) }}
          >
            {fmtScore(player.overall_score)}
          </span>
          <GradeBadge grade={player.grade_overall} size="xs" />
        </div>
      ),
    },
    {
      key: "actions",
      label: "",
      width: "w-8",
      align: "center",
      render: (player) => (
        <Link
          to={`/player/${player.id}`}
          className="text-text-muted hover:text-primary transition-colors"
          title="View profile"
        >
          <ChevronRight size={14} />
        </Link>
      ),
    },
  ];
}

// ── Default sort columns per role ────────────────────────────────

const DEFAULT_SORT: Record<string, string> = {
  bat: "overall_score",
  bowl: "overall_score",
};

const SORT_LABEL_MAP: Record<string, string> = {
  overall_score: "Overall Score",
  score_acceleration: "Acceleration",
  score_power: "Power",
  score_control: "Control",
  score_accuracy: "Accuracy",
  score_threat: "Threat",
  career_sr: "Strike Rate",
  career_avg: "Average",
  total_runs: "Runs / Wickets",
  innings_count: "Innings",
  war_batting: "WAR",
  war_bowling: "WAR",
  clutch_index: "Clutch Index",
  chase_master_index: "Chase Master",
  flat_track_index: "Flat Track Index",
};

// ── Rankings Page Component ──────────────────────────────────────

export default function RankingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // ── Parse URL state ────────────────────────────────────────
  const role = searchParams.get("role") ?? "bat";
  const sort =
    searchParams.get("sort") ?? DEFAULT_SORT[role] ?? "overall_score";
  const order = searchParams.get("order") ?? "desc";
  const country = searchParams.get("country") ?? undefined;
  const archetype = searchParams.get("archetype") ?? undefined;
  const positionGroup = searchParams.get("position_group") ?? undefined;
  const phaseGroup = searchParams.get("phase_group") ?? undefined;
  const page = parseIntParam(searchParams.get("page"), 1);
  const perPage = parseIntParam(searchParams.get("per_page"), 25);
  const minInnings = parseIntParam(searchParams.get("min_innings"), 0);
  const provisional = parseBoolParam(searchParams.get("provisional"));

  // ── Local state ────────────────────────────────────────────
  const [showFilters, setShowFilters] = useState(
    Boolean(
      country ||
      archetype ||
      positionGroup ||
      phaseGroup ||
      provisional !== undefined ||
      minInnings > 0,
    ),
  );
  const [compareIds, setCompareIds] = useState<Set<string>>(new Set());

  // ── Reference data ─────────────────────────────────────────
  const { data: countries = [] } = useCountries();
  const { data: archetypesData } = useArchetypes();

  const archetypeOptions = useMemo(() => {
    if (!archetypesData) return [];
    if (role === "bowl") return archetypesData.bowl ?? [];
    return archetypesData.bat ?? [];
  }, [archetypesData, role]);

  // ── Data fetching ──────────────────────────────────────────
  const isBowling = role === "bowl";

  const rankingsParams: Partial<LeaderboardParams> = {
    sort,
    order: order as "asc" | "desc",
    country,
    archetype,
    position_group: isBowling ? undefined : positionGroup,
    phase_group: isBowling ? phaseGroup : undefined,
    min_innings: minInnings > 0 ? minInnings : undefined,
    provisional,
    page,
    per_page: perPage,
  };

  const battingQuery = useBattingRankings(isBowling ? {} : rankingsParams);

  const bowlingQuery = useBowlingRankings(isBowling ? rankingsParams : {});

  const query = isBowling ? bowlingQuery : battingQuery;
  const { data, isLoading, isFetching, error, refetch } = query;

  const players = data?.players ?? [];
  const totalPlayers = data?.total ?? 0;
  const totalPages =
    data?.total_pages ?? (Math.ceil(totalPlayers / perPage) || 1);

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

  // ── Handlers ───────────────────────────────────────────────

  const handleRoleToggle = useCallback(
    (newRole: string) => {
      // Reset page, sort, and role-specific filters
      const newSort = DEFAULT_SORT[newRole] ?? "overall_score";
      setSearchParams({
        role: newRole,
        sort: newSort,
        order: "desc",
        per_page: String(perPage),
      });
      setCompareIds(new Set());
    },
    [perPage, setSearchParams],
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
    setSearchParams({
      role,
      sort: DEFAULT_SORT[role] ?? "overall_score",
      order: "desc",
      per_page: String(perPage),
    });
  }, [role, perPage, setSearchParams]);

  // ── Active filter count ────────────────────────────────────
  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (country) count++;
    if (archetype) count++;
    if (positionGroup || phaseGroup) count++;
    if (provisional !== undefined) count++;
    if (minInnings > 0) count++;
    return count;
  }, [country, archetype, positionGroup, phaseGroup, provisional, minInnings]);

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
        ? getBowlingColumns(compareIds, handleCompareToggle)
        : getBattingColumns(compareIds, handleCompareToggle),
    [isBowling, compareIds, handleCompareToggle],
  );

  // Compute the rank offset for the current page
  const rankOffset = (page - 1) * perPage;

  // ── Render ─────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* ── Page Header ──────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <Trophy size={24} className="text-gold shrink-0" />
          <div>
            <h1 className="text-h2 text-text-primary">Leaderboards</h1>
            {sort && sort !== "overall_score" && (
              <p className="text-xs text-text-muted mt-0.5">
                Sorted by {SORT_LABEL_MAP[sort] ?? sort}
              </p>
            )}
          </div>
        </div>

        {/* Role toggle */}
        <div className="flex items-center gap-1 p-1 bg-surface rounded-lg">
          <button
            onClick={() => handleRoleToggle("bat")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              !isBowling
                ? "bg-primary text-white shadow-sm"
                : "text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50"
            }`}
            aria-pressed={!isBowling}
          >
            🏏 Batting
          </button>
          <button
            onClick={() => handleRoleToggle("bowl")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              isBowling
                ? "bg-primary text-white shadow-sm"
                : "text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50"
            }`}
            aria-pressed={isBowling}
          >
            🎳 Bowling
          </button>
        </div>
      </div>

      {/* ── Sort pills + filter toggle ───────────────────────── */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        {/* Quick sort pills */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-text-muted mr-1">Sort by:</span>
          {getQuickSortOptions(isBowling).map((opt) => (
            <button
              key={opt.key}
              onClick={() => handleSort(opt.key)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors flex items-center gap-1 ${
                sort === opt.key
                  ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                  : "bg-surface-elevated/50 text-text-secondary hover:text-text-primary hover:bg-surface-elevated"
              }`}
              title={`Sort by ${opt.label}`}
            >
              {opt.shortLabel ?? opt.label}
              {sort === opt.key &&
                (order === "desc" ? (
                  <ArrowDown size={10} />
                ) : (
                  <ArrowUp size={10} />
                ))}
            </button>
          ))}
        </div>

        {/* Filter toggle */}
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`btn-secondary btn-sm relative shrink-0 ${
            showFilters ? "ring-2 ring-primary" : ""
          }`}
          aria-expanded={showFilters}
        >
          <SlidersHorizontal size={14} />
          <span>Filters</span>
          {activeFilterCount > 0 && (
            <span className="absolute -top-1.5 -right-1.5 h-4 w-4 rounded-full bg-primary text-white text-[10px] font-bold flex items-center justify-center">
              {activeFilterCount}
            </span>
          )}
        </button>
      </div>

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

            {/* Position (batting) / Phase (bowling) */}
            {!isBowling ? (
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
      <div className="flex items-center justify-between text-sm text-text-secondary">
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
          title="Failed to load rankings"
          message="Could not fetch the leaderboard data. The backend might be unavailable."
          onRetry={() => refetch()}
        />
      )}

      {/* ── Empty State ──────────────────────────────────────── */}
      {!isLoading && !error && totalPlayers === 0 && (
        <div className="text-center py-16">
          <div className="text-5xl mb-4">🏏</div>
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

      {/* ── Data Table ───────────────────────────────────────── */}
      {!isLoading && !error && players.length > 0 && (
        <div className="card p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="sortable-table" role="grid">
              <thead>
                <tr>
                  {columns.map((col) => {
                    const isSortable = !!col.sortKey;
                    const isCurrentSort = col.sortKey && sort === col.sortKey;
                    const alignClass =
                      col.align === "right"
                        ? "text-right"
                        : col.align === "center"
                          ? "text-center"
                          : "text-left";

                    return (
                      <th
                        key={col.key}
                        className={`${alignClass} ${col.width ?? ""} ${
                          col.hideOnMobile ? "hidden lg:table-cell" : ""
                        } ${
                          col.key === "name" ? "sticky-col-first" : ""
                        } ${isSortable ? "cursor-pointer select-none" : ""} ${
                          isCurrentSort ? "text-primary" : ""
                        }`}
                        onClick={
                          isSortable && col.sortKey
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
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {players.map((player, index) => {
                  const rank = rankOffset + index + 1;
                  const isSelected = compareIds.has(player.id);

                  return (
                    <tr
                      key={player.id}
                      className={`transition-colors ${
                        isSelected ? "bg-primary/5" : ""
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
      { key: "overall_score", label: "Overall", shortLabel: "Overall" },
      { key: "score_accuracy", label: "Accuracy", shortLabel: "ACC" },
      { key: "score_control", label: "Control", shortLabel: "CTL" },
      { key: "score_threat", label: "Threat", shortLabel: "THR" },
      { key: "career_sr", label: "Economy", shortLabel: "Econ" },
      { key: "total_runs", label: "Wickets", shortLabel: "Wkts" },
      { key: "war_bowling", label: "WAR", shortLabel: "WAR" },
    ];
  }
  return [
    { key: "overall_score", label: "Overall", shortLabel: "Overall" },
    { key: "score_acceleration", label: "Acceleration", shortLabel: "ACL" },
    { key: "score_power", label: "Power", shortLabel: "POW" },
    { key: "score_control", label: "Control", shortLabel: "CTL" },
    { key: "career_sr", label: "Strike Rate", shortLabel: "SR" },
    { key: "total_runs", label: "Runs", shortLabel: "Runs" },
    { key: "war_batting", label: "WAR", shortLabel: "WAR" },
    { key: "clutch_index", label: "Clutch", shortLabel: "Clutch" },
  ];
}
