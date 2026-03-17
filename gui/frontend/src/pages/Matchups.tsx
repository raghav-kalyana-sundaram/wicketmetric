/**
 * Matchups — Head-to-Head and Matchup Explorer page.
 *
 * Route: /matchups?bat=<id>&bowl=<id>  (Head-to-Head)
 * Route: /matchups/explore              (Explorer — handled by sub-route)
 *
 * Features (from gui.md § 6.6):
 *   - Batter vs Bowler autocomplete selection
 *   - Overall head-to-head stats card (balls, runs, SR, dismissals, dots, 4s, 6s)
 *   - Dominance gauge — visual indicator of who dominates
 *   - Phase breakdown table (powerplay / middle / death)
 *   - Matchup Explorer: browse all matchups for a player, sorted/filtered
 *   - Top bunnies / nemeses / dominant matchups quick views
 *   - Links to player profiles
 *
 * Data fetching:
 *   - useHeadToHead() — specific batter vs bowler
 *   - useExploreMatchups() — paginated matchup list for a player
 *   - useTopBunnies() / useTopNemeses() / useTopDominantMatchups()
 */

import { useState, useCallback } from "react";
import { useSearchParams, Link, useLocation } from "react-router-dom";
import {
  Swords,
  Search,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Target,
  Flame,
  Info,
  AlertTriangle,
} from "lucide-react";

import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import Pagination from "@/components/Pagination";
import { PageLoading, PageError } from "@/components/Layout";
import {
  useHeadToHead,
  useExploreMatchups,
  useTopBunnies,
  useTopNemeses,
  useTopDominantMatchups,
} from "@/api/queries";
import { dominanceColour, dominanceLabel } from "@/lib/colours";
import {
  fmtInt,
  fmtSR,
  fmtPct,
  fmtPhase,
  fmtMatchupEdge,
  matchupEdgeScore,
} from "@/lib/format";
import type {
  PlayerSummary,
  HeadToHeadResponse,
  MatchupSummary,
  MatchupPhase,
  MatchupExploreParams,
} from "@/api/types";

// ── Sort options for explorer ────────────────────────────────────

const SORT_OPTIONS = [
  { value: "dominance_index", label: "Matchup Edge" },
  { value: "balls_faced", label: "Balls Faced" },
  { value: "strike_rate", label: "Strike Rate" },
  { value: "dismissals", label: "Dismissals" },
  { value: "runs_scored", label: "Runs" },
  { value: "dot_pct", label: "Dot %" },
  { value: "boundary_pct", label: "Boundary %" },
];

// ── DominanceGauge sub-component ─────────────────────────────────

interface DominanceGaugeProps {
  value: number | null | undefined;
  size?: "sm" | "md" | "lg";
}

function DominanceGauge({ value, size = "md" }: DominanceGaugeProps) {
  const score = matchupEdgeScore(value);
  const pct = score ?? 50;
  const colour = dominanceColour(value);
  const label = dominanceLabel(value);

  const heightClass = size === "sm" ? "h-3" : size === "lg" ? "h-6" : "h-4";

  return (
    <div
      className="w-full"
      role="meter"
      aria-valuenow={score ?? undefined}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Matchup edge score: ${label}`}
    >
      <div className={`dominance-gauge ${heightClass} relative`}>
        {/* Pointer */}
        <div className="dominance-gauge-pointer" style={{ left: `${pct}%` }} />
      </div>
      <div className="flex items-center justify-between mt-1 text-[10px] text-text-muted">
        <span>← Bowler</span>
        <span
          className="font-score font-semibold text-xs"
          style={{ color: colour }}
        >
          {score != null ? `${fmtMatchupEdge(value)}/100` : "—"} · {label}
        </span>
        <span>Batter →</span>
      </div>
    </div>
  );
}

// ── Phase Breakdown Table ────────────────────────────────────────

interface PhaseBreakdownProps {
  phases: MatchupPhase[];
}

function PhaseBreakdown({ phases }: PhaseBreakdownProps) {
  if (!phases || phases.length === 0) {
    return (
      <p className="text-sm text-text-muted italic">
        No phase-by-phase data available.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="sortable-table">
        <thead>
          <tr>
            <th>Phase</th>
            <th className="text-right">Balls</th>
            <th className="text-right">Runs</th>
            <th className="text-right">SR</th>
            <th className="text-right">Dots</th>
            <th className="text-right">Wkts</th>
            <th className="text-right">Edge</th>
          </tr>
        </thead>
        <tbody>
          {phases.map((p, i) => (
            <tr key={p.phase || i}>
              <td className="font-medium">{fmtPhase(p.phase)}</td>
              <td className="text-right font-score tabular-nums">
                {fmtInt(p.balls)}
              </td>
              <td className="text-right font-score tabular-nums">
                {fmtInt(p.runs)}
              </td>
              <td className="text-right font-score tabular-nums">
                {fmtSR(p.sr)}
              </td>
              <td className="text-right font-score tabular-nums">
                {fmtInt(p.dots)}
              </td>
              <td className="text-right font-score tabular-nums">
                {fmtInt(p.dismissals)}
              </td>
              <td className="text-right">
                <span
                  className="font-score tabular-nums"
                  style={{ color: dominanceColour(p.dominance_index) }}
                >
                  {p.dominance_index != null
                    ? `${fmtMatchupEdge(p.dominance_index)}/100`
                    : "—"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Matchup Card (used in explorer lists) ────────────────────────

// ── MatchupMiniList (for bunnies / nemeses) ──────────────────────

interface MatchupMiniListProps {
  title: string;
  icon: React.ReactNode;
  matchups: MatchupSummary[] | undefined;
  isLoading: boolean;
  emptyMessage?: string;
}

function MatchupMiniList({
  title,
  icon,
  matchups,
  isLoading,
  emptyMessage = "No matchup data available.",
}: MatchupMiniListProps) {
  if (isLoading) {
    return (
      <div className="card p-4">
        <h3 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
          {icon} {title}
        </h3>
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton h-16 rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (!matchups || matchups.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
          {icon} {title}
        </h3>
        <p className="text-xs text-text-muted italic">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <h3 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
        {icon} {title}
      </h3>
      <div className="space-y-2">
        {matchups.slice(0, 5).map((m, i) => (
          <div
            key={m.opponent_id || i}
            className="flex items-center justify-between gap-2 rounded px-2 py-1.5 hover:bg-surface-elevated/50 transition-colors"
          >
            <div className="min-w-0 flex-1">
              <Link
                to={`/player/${m.opponent_id}`}
                className="text-xs font-medium text-text-primary hover:text-primary transition-colors truncate block"
              >
                {m.opponent_name}
              </Link>
              <span className="text-[10px] text-text-muted">
                {m.balls}b · SR {fmtSR(m.sr)} · {m.dismissals}w
              </span>
            </div>
            <span
              className="font-score text-xs font-bold tabular-nums shrink-0"
              style={{ color: dominanceColour(m.dominance_index) }}
            >
              {m.dominance_index != null
                ? `${fmtMatchupEdge(m.dominance_index)}/100`
                : "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Head-to-Head View ────────────────────────────────────────────

interface HeadToHeadViewProps {
  data: HeadToHeadResponse;
}

function HeadToHeadView({ data }: HeadToHeadViewProps) {
  return (
    <div className="app-page page-stack">
      {/* Hero card */}
      <div
        className="card p-6 border-l-4"
        style={{ borderLeftColor: dominanceColour(data.dominance_index) }}
      >
        <div className="flex items-center justify-between flex-wrap gap-4 mb-4">
          <div className="flex items-center gap-3">
            <Link
              to={`/player/${data.batter_id}`}
              className="text-h3 font-semibold text-text-primary hover:text-primary transition-colors"
            >
              {data.batter_name}
            </Link>
            <span className="text-text-muted text-lg">vs</span>
            <Link
              to={`/player/${data.bowler_id}`}
              className="text-h3 font-semibold text-text-primary hover:text-primary transition-colors"
            >
              {data.bowler_name}
            </Link>
          </div>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 gap-4 mb-6">
          <StatBadge label="Balls" value={fmtInt(data.balls)} />
          <StatBadge label="Runs" value={fmtInt(data.runs)} />
          <StatBadge label="SR" value={fmtSR(data.sr)} />
          <StatBadge label="Dismissals" value={fmtInt(data.dismissals)} />
          <StatBadge label="Dots" value={fmtInt(data.dots)} />
          <StatBadge label="Fours" value={fmtInt(data.fours)} />
          <StatBadge label="Sixes" value={fmtInt(data.sixes)} />
        </div>

        {/* Extra stat row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
          <StatBadge label="Dot %" value={fmtPct(data.dot_pct)} />
          <StatBadge label="Boundary %" value={fmtPct(data.boundary_pct)} />
          <StatBadge
            label="Matchup Edge"
            value={
              data.dominance_index != null
                ? `${fmtMatchupEdge(data.dominance_index)}/100`
                : "—"
            }
            valueColour={dominanceColour(data.dominance_index)}
          />
        </div>

        {/* Dominance gauge */}
        <DominanceGauge value={data.dominance_index} size="lg" />
      </div>

      {/* Phase breakdown */}
      <div className="card p-6">
        <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
          <Target size={20} className="text-accent" />
          By Phase
        </h2>
        <PhaseBreakdown phases={data.by_phase} />
      </div>

      {/* Profile links */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link to={`/player/${data.batter_id}`} className="btn-secondary btn-sm">
          View {data.batter_name}'s profile <ArrowRight size={14} />
        </Link>
        <Link to={`/player/${data.bowler_id}`} className="btn-secondary btn-sm">
          View {data.bowler_name}'s profile <ArrowRight size={14} />
        </Link>
      </div>
    </div>
  );
}

// ── StatBadge ────────────────────────────────────────────────────

interface StatBadgeProps {
  label: string;
  value: string;
  valueColour?: string;
}

function StatBadge({ label, value, valueColour }: StatBadgeProps) {
  return (
    <div className="text-center">
      <div
        className="font-score text-lg font-bold tabular-nums"
        style={valueColour ? { color: valueColour } : undefined}
      >
        {value}
      </div>
      <div className="text-[10px] text-text-muted uppercase tracking-wider mt-0.5">
        {label}
      </div>
    </div>
  );
}

// ── Explorer View ────────────────────────────────────────────────

interface ExplorerViewProps {
  initialPlayerId?: string;
  initialRole?: "bat" | "bowl";
}

function ExplorerView({ initialPlayerId, initialRole }: ExplorerViewProps) {
  const [playerId, setPlayerId] = useState(initialPlayerId ?? "");
  const [playerName, setPlayerName] = useState("");
  const [role, setRole] = useState<"bat" | "bowl">(initialRole ?? "bat");
  const [sortBy, setSortBy] = useState("dominance_index");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [minBalls, setMinBalls] = useState(6);
  const [page, setPage] = useState(1);
  const perPage = 20;

  const params: MatchupExploreParams = {
    player_id: playerId,
    role,
    min_balls: minBalls,
    sort: sortBy,
    order,
    page,
    per_page: perPage,
  };

  const {
    data: exploreData,
    isLoading: exploreLoading,
    error: exploreError,
  } = useExploreMatchups(params);

  // Top bunnies (for bowlers)
  const { data: bunniesData, isLoading: bunniesLoading } = useTopBunnies(
    playerId || undefined,
    { minBalls, limit: 5 },
    { enabled: !!playerId && role === "bowl" },
  );

  // Top nemeses (for batters)
  const { data: nemesesData, isLoading: nemesesLoading } = useTopNemeses(
    playerId || undefined,
    { minBalls, limit: 5 },
    { enabled: !!playerId && role === "bat" },
  );

  // Top dominant (for batters)
  const { data: dominantData, isLoading: dominantLoading } =
    useTopDominantMatchups(
      playerId || undefined,
      { minBalls, limit: 5 },
      { enabled: !!playerId && role === "bat" },
    );

  const totalPages = exploreData ? Math.ceil(exploreData.total / perPage) : 0;

  const handlePlayerSelect = useCallback((player: PlayerSummary) => {
    setPlayerId(player.id);
    setPlayerName(player.name);
    setRole(player.role === "bowl" ? "bowl" : "bat");
    setPage(1);
  }, []);

  const toggleSort = useCallback(
    (col: string) => {
      if (sortBy === col) {
        setOrder((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(col);
        setOrder("desc");
      }
      setPage(1);
    },
    [sortBy],
  );

  return (
    <div className="app-page page-stack">
      {/* Player search + filters */}
      <div className="card p-4 space-y-4">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1 max-w-md">
            <PlayerAutocomplete
              onSelect={handlePlayerSelect}
              placeholder="Search for a player…"
              size="md"
            />
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <select
              value={role}
              onChange={(e) => {
                setRole(e.target.value as "bat" | "bowl");
                setPage(1);
              }}
              className="filter-select text-sm"
              aria-label="Role"
            >
              <option value="bat">As Batter</option>
              <option value="bowl">As Bowler</option>
            </select>

            <div className="flex items-center gap-1.5">
              <label
                className="text-xs text-text-secondary"
                htmlFor="min-balls"
              >
                Min Balls:
              </label>
              <input
                id="min-balls"
                type="number"
                min={1}
                max={100}
                value={minBalls}
                onChange={(e) => {
                  setMinBalls(Math.max(1, parseInt(e.target.value) || 6));
                  setPage(1);
                }}
                className="filter-input w-16 text-sm text-center"
              />
            </div>

            <select
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value);
                setPage(1);
              }}
              className="filter-select text-sm"
              aria-label="Sort by"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <button
              onClick={() => setOrder((o) => (o === "asc" ? "desc" : "asc"))}
              className="btn-ghost btn-sm"
              aria-label={`Sort ${order === "asc" ? "ascending" : "descending"}`}
            >
              {order === "desc" ? (
                <ChevronDown size={16} />
              ) : (
                <ChevronUp size={16} />
              )}
            </button>
          </div>
        </div>

        {playerName && playerId && (
          <div className="text-sm text-text-secondary">
            Showing matchups for{" "}
            <Link
              to={`/player/${playerId}`}
              className="text-primary hover:underline font-medium"
            >
              {playerName}
            </Link>{" "}
            as {role === "bat" ? "batter" : "bowler"}
          </div>
        )}
      </div>

      {/* Empty state */}
      {!playerId && (
        <div className="card flex flex-col items-center justify-center py-16 text-center">
          <Search size={48} className="text-text-muted mb-4" />
          <h2 className="text-h3 text-text-primary mb-2">
            Search for a Player
          </h2>
          <p className="text-sm text-text-secondary max-w-md">
            Search for any batter or bowler to explore their matchups. Sort by
            matchup edge, balls faced, strike rate, or dismissals.
          </p>
        </div>
      )}

      {/* Loading */}
      {playerId && exploreLoading && <PageLoading />}

      {/* Error */}
      {exploreError && (
        <PageError
          title="Matchup Error"
          message="Failed to load matchup data."
        />
      )}

      {/* Results */}
      {playerId && exploreData && (
        <div className="app-page page-stack">
          {/* Quick stats sidebar (bunnies / nemeses / dominant) */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {role === "bat" && (
              <>
                <MatchupMiniList
                  title="Nemeses (Struggles Against)"
                  icon={<AlertTriangle size={14} className="text-danger" />}
                  matchups={nemesesData as MatchupSummary[] | undefined}
                  isLoading={nemesesLoading}
                  emptyMessage="No nemesis data found."
                />
                <MatchupMiniList
                  title="Dominates (Thrives Against)"
                  icon={<Flame size={14} className="text-accent" />}
                  matchups={dominantData as MatchupSummary[] | undefined}
                  isLoading={dominantLoading}
                  emptyMessage="No dominant matchup data found."
                />
                <div className="card p-4">
                  <h3 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
                    <Info size={14} className="text-primary" />
                    About Matchups
                  </h3>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    <strong>Matchup Edge</strong> is a 0-100 score showing who
                    controls the matchup. Around 50 is even, higher favours the
                    batter, and lower favours the bowler. Sort low for nemeses
                    and high for targets.
                  </p>
                </div>
              </>
            )}
            {role === "bowl" && (
              <>
                <MatchupMiniList
                  title="Bunnies (Dominates)"
                  icon={<Target size={14} className="text-accent" />}
                  matchups={bunniesData as MatchupSummary[] | undefined}
                  isLoading={bunniesLoading}
                  emptyMessage="No bunny data found."
                />
                <div className="card p-4">
                  <h3 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
                    <Info size={14} className="text-primary" />
                    About Matchups
                  </h3>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    <strong>Bunnies</strong> are batters this bowler dominates.
                    Lower matchup edge scores mean stronger bowler control.
                  </p>
                </div>
                <div /> {/* Spacer for grid alignment */}
              </>
            )}
          </div>

          {/* Matchup list */}
          <div className="card p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-text-primary">
                All Matchups ({fmtInt(exploreData.total)})
              </h3>
            </div>

            {exploreData.matchups.length === 0 ? (
              <p className="text-sm text-text-muted italic py-8 text-center">
                No matchups found matching the current filters.
              </p>
            ) : (
              <>
                {/* Table view */}
                <div className="overflow-x-auto">
                  <table className="sortable-table">
                    <thead>
                      <tr>
                        <th className="min-w-[160px]">
                          {role === "bat" ? "Bowler" : "Batter"}
                        </th>
                        <SortableHeader
                          label="Balls"
                          column="balls_faced"
                          currentSort={sortBy}
                          currentOrder={order}
                          onSort={toggleSort}
                        />
                        <SortableHeader
                          label="Runs"
                          column="runs_scored"
                          currentSort={sortBy}
                          currentOrder={order}
                          onSort={toggleSort}
                        />
                        <SortableHeader
                          label="SR"
                          column="strike_rate"
                          currentSort={sortBy}
                          currentOrder={order}
                          onSort={toggleSort}
                        />
                        <SortableHeader
                          label="Wkts"
                          column="dismissals"
                          currentSort={sortBy}
                          currentOrder={order}
                          onSort={toggleSort}
                        />
                        <SortableHeader
                          label="Dot %"
                          column="dot_pct"
                          currentSort={sortBy}
                          currentOrder={order}
                          onSort={toggleSort}
                        />
                        <SortableHeader
                          label="Bdry %"
                          column="boundary_pct"
                          currentSort={sortBy}
                          currentOrder={order}
                          onSort={toggleSort}
                        />
                        <SortableHeader
                          label="Edge"
                          column="dominance_index"
                          currentSort={sortBy}
                          currentOrder={order}
                          onSort={toggleSort}
                        />
                      </tr>
                    </thead>
                    <tbody>
                      {exploreData.matchups.map((m, i) => (
                        <tr key={m.opponent_id || i}>
                          <td>
                            <Link
                              to={`/player/${m.opponent_id}`}
                              className="text-primary hover:underline text-sm"
                            >
                              {m.opponent_name || m.opponent_id}
                            </Link>
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtInt(m.balls)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtInt(m.runs)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtSR(m.sr)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtInt(m.dismissals)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtPct(m.dot_pct)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtPct(m.boundary_pct)}
                          </td>
                          <td className="text-right">
                            <span
                              className="font-score tabular-nums font-semibold"
                              style={{
                                color: dominanceColour(m.dominance_index),
                              }}
                            >
                              {m.dominance_index != null
                                ? `${fmtMatchupEdge(m.dominance_index)}/100`
                                : "—"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="mt-4">
                    <Pagination
                      page={page}
                      totalPages={totalPages}
                      onPageChange={setPage}
                      total={exploreData.total}
                      perPage={perPage}
                      showSummary
                    />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Sortable table header ────────────────────────────────────────

interface SortableHeaderProps {
  label: string;
  column: string;
  currentSort: string;
  currentOrder: "asc" | "desc";
  onSort: (column: string) => void;
}

function SortableHeader({
  label,
  column,
  currentSort,
  currentOrder,
  onSort,
}: SortableHeaderProps) {
  const isActive = currentSort === column;

  return (
    <th
      className="text-right cursor-pointer select-none"
      onClick={() => onSort(column)}
      aria-sort={
        isActive
          ? currentOrder === "asc"
            ? "ascending"
            : "descending"
          : "none"
      }
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {isActive && (
          <span className="text-primary">
            {currentOrder === "desc" ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronUp size={12} />
            )}
          </span>
        )}
      </span>
    </th>
  );
}

// ── Main Matchups Page ───────────────────────────────────────────

export default function Matchups() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();

  // Determine if we're in H2H mode or Explorer mode
  const isExplorer = location.pathname.includes("/explore");

  // H2H params from URL
  const batId = searchParams.get("bat") ?? "";
  const bowlId = searchParams.get("bowl") ?? "";
  const hasH2HParams = !!(batId && bowlId);

  // Tab state (only relevant for /matchups without /explore)
  const [activeTab, setActiveTab] = useState<"h2h" | "explore">(
    isExplorer ? "explore" : hasH2HParams ? "h2h" : "explore",
  );

  // H2H data
  const {
    data: h2hData,
    isLoading: h2hLoading,
    error: h2hError,
  } = useHeadToHead(batId, bowlId);

  // H2H player selection
  const handleBatterSelect = useCallback(
    (player: PlayerSummary) => {
      const newParams = new URLSearchParams(searchParams);
      newParams.set("bat", player.id);
      setSearchParams(newParams);
      setActiveTab("h2h");
    },
    [searchParams, setSearchParams],
  );

  const handleBowlerSelect = useCallback(
    (player: PlayerSummary) => {
      const newParams = new URLSearchParams(searchParams);
      newParams.set("bowl", player.id);
      setSearchParams(newParams);
      setActiveTab("h2h");
    },
    [searchParams, setSearchParams],
  );

  return (
    <div className="app-page page-stack animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <h1 className="page-title flex items-center gap-3">
          <Swords size={28} className="text-primary" />
          {isExplorer ? "Matchup Explorer" : "Head-to-Head Matchups"}
        </h1>
        <p className="page-subtitle">
          {isExplorer
            ? "Browse all matchups for any player. Sort by matchup edge, balls, strike rate, or dismissals."
            : "Analyse the head-to-head record between any batter and bowler, or explore all matchups."}
        </p>
      </div>

      {/* Tab switcher (only on /matchups, not /matchups/explore) */}
      {!isExplorer && (
        <div className="flex items-center gap-1 border-b border-surface-elevated">
          <button
            onClick={() => setActiveTab("h2h")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "h2h"
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            <Swords size={14} className="inline mr-1.5" />
            Head-to-Head
          </button>
          <button
            onClick={() => setActiveTab("explore")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "explore"
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            <Search size={14} className="inline mr-1.5" />
            Explorer
          </button>
        </div>
      )}

      {/* H2H Mode */}
      {(activeTab === "h2h" || isExplorer) && activeTab === "h2h" && (
        <div className="app-page page-stack">
          {/* Selection */}
          <div className="card p-4">
            <div className="flex flex-col sm:flex-row items-center gap-3">
              <div className="flex-1 w-full max-w-xs">
                <label className="text-xs text-text-secondary uppercase tracking-wider mb-1 block">
                  Batter
                </label>
                <PlayerAutocomplete
                  onSelect={handleBatterSelect}
                  placeholder="Search batter…"
                  size="sm"
                  role="bat"
                />
              </div>
              <span className="text-text-muted text-xl font-bold mt-4 sm:mt-5">
                vs
              </span>
              <div className="flex-1 w-full max-w-xs">
                <label className="text-xs text-text-secondary uppercase tracking-wider mb-1 block">
                  Bowler
                </label>
                <PlayerAutocomplete
                  onSelect={handleBowlerSelect}
                  placeholder="Search bowler…"
                  size="sm"
                  role="bowl"
                />
              </div>
            </div>
          </div>

          {/* Loading */}
          {h2hLoading && hasH2HParams && <PageLoading />}

          {/* Error */}
          {h2hError && hasH2HParams && (
            <PageError
              title="No Matchup Data"
              message="No matchup data found for these players. They may not have faced each other, or you may need to check the player IDs."
            />
          )}

          {/* Empty state */}
          {!hasH2HParams && !h2hLoading && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <Swords size={48} className="text-text-muted mb-4" />
              <h2 className="text-h3 text-text-primary mb-2">
                Select a Batter and Bowler
              </h2>
              <p className="text-sm text-text-secondary max-w-md">
                Use the search inputs above to select a batter and a bowler,
                then see their complete head-to-head record.
              </p>
            </div>
          )}

          {/* H2H results */}
          {h2hData && <HeadToHeadView data={h2hData} />}
        </div>
      )}

      {/* Explorer Mode */}
      {(activeTab === "explore" || isExplorer) &&
        (activeTab === "explore" || isExplorer) && <ExplorerView />}
    </div>
  );
}
