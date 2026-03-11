/**
 * Venues — Venue Analysis page.
 *
 * Route: /venues
 *
 * Features (from gui.md § 6.10):
 *   - Venue difficulty list with sorting (avg par SR, boundary rate, dot %, difficulty score)
 *   - Flat Track Bully Index — players sorted by FTB index
 *   - Venue detail view — click any venue for detailed breakdown
 *   - Player at venue stats — search a player to see their venue-by-venue record
 *   - Venue summary statistics (hardest, easiest, most used)
 *
 * Data fetching:
 *   - useVenues() — list of all venues with baselines
 *   - useVenueSummary() — aggregate venue statistics
 *   - useVenueDetail() — single venue deep-dive
 *   - useFlatTrackIndex() — FTB leaderboard
 *   - usePlayersAtVenue() — player performance at a specific venue
 */

import { useState, useMemo, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  MapPin,
  ChevronDown,
  ChevronUp,
  Info,
  Trophy,
  AlertTriangle,
  CheckCircle2,
  Flag,
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  Target,
  X,
} from "lucide-react";

import GradeBadge from "@/components/GradeBadge";
import Pagination from "@/components/Pagination";
import { PageLoading, PageError } from "@/components/Layout";
import {
  useVenues,
  useVenueSummary,
  useVenueDetail,
  useFlatTrackIndex,
  usePlayersAtVenue,
} from "@/api/queries";
import { scoreToColour as _scoreToColour } from "@/lib/colours";
import {
  fmtInt,
  fmtSR,
  fmtPct,
  fmtScore,
  fmtEcon,
  fmtAvg,
  countryFlag,
} from "@/lib/format";
import type {
  PlayerSummary,
  VenueBaseline,
  VenueSummary,
  VenueListParams,
  FlatTrackEntry,
  FlatTrackResponse,
} from "@/api/types";

// ── Tab type ─────────────────────────────────────────────────────

type VenueTab = "venues" | "ftb" | "detail";

// ── Sort options ─────────────────────────────────────────────────

const VENUE_SORT_OPTIONS = [
  { value: "difficulty_score", label: "Difficulty Score" },
  { value: "avg_par_sr", label: "Avg Par SR" },
  { value: "boundary_rate", label: "Boundary Rate" },
  { value: "dot_pct", label: "Dot %" },
  { value: "matches", label: "Matches" },
];

const FTB_SORT_OPTIONS = [
  { value: "flat_track_index", label: "FTB Index" },
  { value: "innings_at_known_venues", label: "Innings" },
  { value: "avg_venue_difficulty_faced", label: "Avg Difficulty" },
];

// ── Difficulty colour helper ─────────────────────────────────────

function difficultyColour(score: number | null | undefined): string {
  if (score == null || isNaN(score)) return "#64748B";
  // Lower score = easier, higher = harder
  // Map roughly: 0–30 green, 30–60 amber, 60–100 red
  if (score < 30) return "#22C55E";
  if (score < 45) return "#06B6D4";
  if (score < 60) return "#F59E0B";
  if (score < 75) return "#F97316";
  return "#EF4444";
}

function difficultyLabel(score: number | null | undefined): string {
  if (score == null || isNaN(score)) return "Unknown";
  if (score < 30) return "Batting-friendly";
  if (score < 45) return "Balanced";
  if (score < 60) return "Moderate";
  if (score < 75) return "Challenging";
  return "Very Difficult";
}

// ── FTB interpretation helpers ───────────────────────────────────

function ftbIcon(interpretation: string, icon: string): React.ReactNode {
  if (icon === "🏆" || interpretation.toLowerCase().includes("consistent")) {
    return <CheckCircle2 size={14} className="text-accent" />;
  }
  if (
    icon === "⚠️" ||
    icon === "⚠" ||
    interpretation.toLowerCase().includes("slight")
  ) {
    return <AlertTriangle size={14} className="text-warning" />;
  }
  if (icon === "🚩" || interpretation.toLowerCase().includes("flat track")) {
    return <Flag size={14} className="text-danger" />;
  }
  return <span className="text-xs">{icon || "·"}</span>;
}

function ftbColour(index: number | null | undefined): string {
  if (index == null || isNaN(index)) return "#64748B";
  const abs = Math.abs(index);
  if (abs < 0.1) return "#22C55E"; // Very consistent
  if (abs < 0.2) return "#06B6D4"; // Consistent
  if (abs < 0.35) return "#F59E0B"; // Slight bias
  return "#EF4444"; // Flat track bully
}

// ── Summary Card Component ───────────────────────────────────────

interface SummaryStatProps {
  label: string;
  value: string;
  subtext?: string;
  icon: React.ReactNode;
  colour?: string;
}

function SummaryStat({
  label,
  value,
  subtext,
  icon,
  colour,
}: SummaryStatProps) {
  return (
    <div className="card p-4 flex items-start gap-3">
      <div className="shrink-0 mt-0.5">{icon}</div>
      <div className="min-w-0">
        <div className="text-[10px] text-text-muted uppercase tracking-wider">
          {label}
        </div>
        <div
          className="font-score text-lg font-bold tabular-nums mt-0.5"
          style={colour ? { color: colour } : undefined}
        >
          {value}
        </div>
        {subtext && (
          <div className="text-xs text-text-secondary mt-0.5 truncate">
            {subtext}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Difficulty Bar Component ─────────────────────────────────────

interface DifficultyBarProps {
  score: number | null | undefined;
  width?: number;
}

function DifficultyBar({ score, width = 60 }: DifficultyBarProps) {
  const val =
    score != null && isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
  const colour = difficultyColour(score);

  return (
    <div className="inline-flex items-center gap-1.5">
      <div
        className="score-bar h-2 rounded-full"
        style={{ width: `${width}px` }}
      >
        <div
          className="score-bar-fill h-2 rounded-full transition-all duration-500 ease-out"
          style={{
            width: `${val}%`,
            backgroundColor: colour,
          }}
        />
      </div>
      <span
        className="text-[10px] font-score tabular-nums min-w-[2rem] text-right"
        style={{ color: colour }}
      >
        {score != null ? Math.round(score) : "—"}
      </span>
    </div>
  );
}

// ── Sortable Header Component ────────────────────────────────────

interface SortableHeaderProps {
  label: string;
  column: string;
  currentSort: string;
  currentOrder: "asc" | "desc";
  onSort: (column: string) => void;
  align?: "left" | "right";
}

function SortableHeader({
  label,
  column,
  currentSort,
  currentOrder,
  onSort,
  align = "right",
}: SortableHeaderProps) {
  const isActive = currentSort === column;

  return (
    <th
      className={`cursor-pointer select-none ${align === "right" ? "text-right" : "text-left"}`}
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

// ── Venue Detail Panel ───────────────────────────────────────────

interface VenueDetailPanelProps {
  venueName: string;
  onClose: () => void;
}

function VenueDetailPanel({ venueName, onClose }: VenueDetailPanelProps) {
  const {
    data: detail,
    isLoading: detailLoading,
    error: detailError,
  } = useVenueDetail(venueName);

  // Player at venue
  const [playerSearchRole, setPlayerSearchRole] = useState<"bat" | "bowl">(
    "bat",
  );
  const [playerAtVenuePage, setPlayerAtVenuePage] = useState(1);
  const [playerAtVenueSort, setPlayerAtVenueSort] = useState("sr");
  const [playerAtVenueOrder, setPlayerAtVenueOrder] = useState<"asc" | "desc">(
    "desc",
  );
  const perPage = 15;

  const { data: playersData, isLoading: playersLoading } = usePlayersAtVenue(
    venueName,
    {
      role: playerSearchRole,
      minInnings: 2,
      sort: playerAtVenueSort,
      order: playerAtVenueOrder,
      page: playerAtVenuePage,
      perPage: perPage,
    },
  );

  const togglePlayerSort = useCallback(
    (col: string) => {
      if (playerAtVenueSort === col) {
        setPlayerAtVenueOrder((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setPlayerAtVenueSort(col);
        setPlayerAtVenueOrder("desc");
      }
      setPlayerAtVenuePage(1);
    },
    [playerAtVenueSort],
  );

  // togglePlayerSort is available for player-at-venue table header click handlers

  if (detailLoading) return <PageLoading />;
  if (detailError) {
    return (
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-h3 text-text-primary">{venueName}</h2>
          <button onClick={onClose} className="btn-ghost btn-sm">
            <X size={16} /> Close
          </button>
        </div>
        <p className="text-sm text-text-muted">Failed to load venue details.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Back button */}
      <button
        onClick={onClose}
        className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-primary transition-colors"
      >
        <ArrowLeft size={16} />
        Back to venue list
      </button>

      {/* Venue header */}
      <div className="card p-6">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h2 className="text-h2 text-text-primary flex items-center gap-2">
              <MapPin size={22} className="text-primary" />
              {venueName}
            </h2>
            {detail && (
              <div className="mt-1 flex items-center gap-2 text-sm text-text-secondary">
                <span>{fmtInt(detail.matches)} matches</span>
                <span>·</span>
                <span
                  style={{ color: difficultyColour(detail.difficulty_score) }}
                  className="font-medium"
                >
                  {difficultyLabel(detail.difficulty_score)}
                </span>
              </div>
            )}
          </div>
        </div>

        {detail && (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
            <div className="text-center">
              <div className="font-score text-lg font-bold tabular-nums">
                {fmtInt(detail.matches)}
              </div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider">
                Matches
              </div>
            </div>
            <div className="text-center">
              <div className="font-score text-lg font-bold tabular-nums">
                {fmtSR(detail.avg_par_sr)}
              </div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider">
                Avg Par SR
              </div>
            </div>
            <div className="text-center">
              <div className="font-score text-lg font-bold tabular-nums">
                {fmtPct(detail.boundary_rate)}
              </div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider">
                Boundary Rate
              </div>
            </div>
            <div className="text-center">
              <div className="font-score text-lg font-bold tabular-nums">
                {fmtPct(detail.dot_pct)}
              </div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider">
                Dot %
              </div>
            </div>
            <div className="text-center">
              <div
                className="font-score text-lg font-bold tabular-nums"
                style={{ color: difficultyColour(detail.difficulty_score) }}
              >
                {fmtScore(detail.difficulty_score)}
              </div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider">
                Difficulty
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Players at this venue */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h3 className="text-h3 text-text-primary flex items-center gap-2">
            <Trophy size={18} className="text-gold" />
            Player Performance at {venueName}
          </h3>
          <div className="flex items-center gap-2">
            <select
              value={playerSearchRole}
              onChange={(e) => {
                setPlayerSearchRole(e.target.value as "bat" | "bowl");
                setPlayerAtVenuePage(1);
              }}
              className="filter-select text-xs"
              aria-label="Role"
            >
              <option value="bat">Batters</option>
              <option value="bowl">Bowlers</option>
            </select>
          </div>
        </div>

        {playersLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton h-10 rounded" />
            ))}
          </div>
        ) : playersData &&
          (
            playersData as unknown as {
              players?: PlayerSummary[];
              items?: PlayerSummary[];
              total?: number;
            }
          ).total === 0 ? (
          <p className="text-sm text-text-muted italic py-6 text-center">
            No player data available for this venue.
          </p>
        ) : playersData ? (
          <>
            <div className="overflow-x-auto">
              <table className="sortable-table">
                <thead>
                  <tr>
                    <th className="min-w-[140px] text-left">Player</th>
                    <th className="text-left">Country</th>
                    {playerSearchRole === "bat" ? (
                      <>
                        <th
                          className="text-right cursor-pointer hover:text-primary select-none"
                          onClick={() => togglePlayerSort("innings_count")}
                        >
                          Inn{" "}
                          {playerAtVenueSort === "innings_count"
                            ? playerAtVenueOrder === "asc"
                              ? "↑"
                              : "↓"
                            : ""}
                        </th>
                        <th
                          className="text-right cursor-pointer hover:text-primary select-none"
                          onClick={() => togglePlayerSort("total_runs")}
                        >
                          Runs{" "}
                          {playerAtVenueSort === "total_runs"
                            ? playerAtVenueOrder === "asc"
                              ? "↑"
                              : "↓"
                            : ""}
                        </th>
                        <th
                          className="text-right cursor-pointer hover:text-primary select-none"
                          onClick={() => togglePlayerSort("career_sr")}
                        >
                          SR{" "}
                          {playerAtVenueSort === "career_sr"
                            ? playerAtVenueOrder === "asc"
                              ? "↑"
                              : "↓"
                            : ""}
                        </th>
                        <th
                          className="text-right cursor-pointer hover:text-primary select-none"
                          onClick={() => togglePlayerSort("career_avg")}
                        >
                          Avg{" "}
                          {playerAtVenueSort === "career_avg"
                            ? playerAtVenueOrder === "asc"
                              ? "↑"
                              : "↓"
                            : ""}
                        </th>
                      </>
                    ) : (
                      <>
                        <th
                          className="text-right cursor-pointer hover:text-primary select-none"
                          onClick={() => togglePlayerSort("innings_count")}
                        >
                          Matches{" "}
                          {playerAtVenueSort === "innings_count"
                            ? playerAtVenueOrder === "asc"
                              ? "↑"
                              : "↓"
                            : ""}
                        </th>
                        <th
                          className="text-right cursor-pointer hover:text-primary select-none"
                          onClick={() => togglePlayerSort("total_runs")}
                        >
                          Wkts{" "}
                          {playerAtVenueSort === "total_runs"
                            ? playerAtVenueOrder === "asc"
                              ? "↑"
                              : "↓"
                            : ""}
                        </th>
                        <th
                          className="text-right cursor-pointer hover:text-primary select-none"
                          onClick={() => togglePlayerSort("career_sr")}
                        >
                          Econ{" "}
                          {playerAtVenueSort === "career_sr"
                            ? playerAtVenueOrder === "asc"
                              ? "↑"
                              : "↓"
                            : ""}
                        </th>
                      </>
                    )}
                    <th className="text-right">Grade</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    (
                      playersData as unknown as {
                        players?: PlayerSummary[];
                        items?: PlayerSummary[];
                      }
                    ).players ||
                    (playersData as unknown as { items?: PlayerSummary[] })
                      .items ||
                    []
                  ).map((p: PlayerSummary, i: number) => (
                    <tr key={p.id || i}>
                      <td>
                        <Link
                          to={`/player/${p.id}`}
                          className="text-sm text-primary hover:underline"
                        >
                          {p.name}
                        </Link>
                      </td>
                      <td className="text-xs text-text-secondary">
                        {countryFlag(p.country)} {p.country}
                      </td>
                      {playerSearchRole === "bat" ? (
                        <>
                          <td className="text-right font-score tabular-nums">
                            {fmtInt(p.innings_count)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtInt(p.total_runs)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtSR(p.career_sr)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtAvg(p.career_avg)}
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="text-right font-score tabular-nums">
                            {fmtInt(p.innings_count)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtInt(p.total_runs)}
                          </td>
                          <td className="text-right font-score tabular-nums">
                            {fmtEcon(p.career_sr)}
                          </td>
                        </>
                      )}
                      <td className="text-right">
                        <GradeBadge grade={p.grade_overall} size="xs" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination for player-at-venue */}
            {(playersData as { total_pages?: number; total?: number })
              .total_pages &&
              (playersData as { total_pages: number }).total_pages > 1 && (
                <div className="mt-4">
                  <Pagination
                    page={playerAtVenuePage}
                    totalPages={
                      (playersData as { total_pages: number }).total_pages
                    }
                    onPageChange={setPlayerAtVenuePage}
                    total={(playersData as { total: number }).total}
                    perPage={perPage}
                    showSummary
                  />
                </div>
              )}
          </>
        ) : null}
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────

export default function Venues() {
  const [activeTab, setActiveTab] = useState<VenueTab>("venues");
  const [selectedVenue, setSelectedVenue] = useState<string | null>(null);

  // ── Venue list state ───────────────────────────────────────────
  const [venueSort, setVenueSort] = useState("difficulty_score");
  const [venueOrder, setVenueOrder] = useState<"asc" | "desc">("desc");
  const [minMatches, setMinMatches] = useState(5);

  const venueParams: VenueListParams = {
    sort: venueSort,
    order: venueOrder,
    min_matches: minMatches,
  };

  const {
    data: venuesData,
    isLoading: venuesLoading,
    error: venuesError,
  } = useVenues(venueParams);

  const { data: summaryData, isLoading: summaryLoading } = useVenueSummary();

  // ── FTB state ──────────────────────────────────────────────────
  const [ftbRole, setFtbRole] = useState<"bat" | "bowl">("bat");
  const [ftbSort, setFtbSort] = useState("flat_track_index");
  const [ftbOrder, setFtbOrder] = useState<"asc" | "desc">("asc");
  const [ftbPage, setFtbPage] = useState(1);
  const [ftbMinInnings, setFtbMinInnings] = useState(20);
  const ftbPerPage = 25;

  const {
    data: ftbData,
    isLoading: ftbLoading,
    error: ftbError,
  } = useFlatTrackIndex({
    role: ftbRole,
    min_innings: ftbMinInnings,
    sort: ftbSort,
    order: ftbOrder,
    page: ftbPage,
    per_page: ftbPerPage,
  });

  // ── Sort handlers ──────────────────────────────────────────────

  const toggleVenueSort = useCallback(
    (col: string) => {
      if (venueSort === col) {
        setVenueOrder((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setVenueSort(col);
        setVenueOrder("desc");
      }
    },
    [venueSort],
  );

  const toggleFtbSort = useCallback(
    (col: string) => {
      if (ftbSort === col) {
        setFtbOrder((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setFtbSort(col);
        setFtbOrder("asc");
      }
      setFtbPage(1);
    },
    [ftbSort],
  );

  const handleVenueClick = useCallback((venueName: string) => {
    setSelectedVenue(venueName);
    setActiveTab("detail");
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedVenue(null);
    setActiveTab("venues");
  }, []);

  // ── Derived data ───────────────────────────────────────────────

  const venues: VenueBaseline[] = useMemo(
    () => (venuesData as { venues?: VenueBaseline[] })?.venues ?? [],
    [venuesData],
  );

  const summary = summaryData as VenueSummary | undefined;

  const ftbResponse = ftbData as FlatTrackResponse | undefined;
  const ftbPlayers: FlatTrackEntry[] = ftbResponse?.players ?? [];
  const ftbTotalPages = ftbResponse
    ? Math.ceil(ftbResponse.total / ftbPerPage)
    : 0;

  // ── Render ─────────────────────────────────────────────────────

  return (
    <div className="animate-fade-in space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-h1 text-text-primary flex items-center gap-3">
          <MapPin size={28} className="text-primary" />
          Venue Analysis
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Explore venue characteristics, difficulty ratings, and see who
          performs best (or worst) depending on conditions.
        </p>
      </div>

      {/* Summary cards */}
      {!summaryLoading && summary && activeTab !== "detail" && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <SummaryStat
            label="Total Venues"
            value={fmtInt(summary.total_venues)}
            icon={<MapPin size={18} className="text-primary" />}
          />
          <SummaryStat
            label="Hardest Venue"
            value={summary.hardest_venue?.venue ?? "—"}
            subtext={
              summary.hardest_venue
                ? `Difficulty: ${fmtScore(summary.hardest_venue.difficulty)}`
                : undefined
            }
            icon={<TrendingUp size={18} className="text-danger" />}
            colour="#EF4444"
          />
          <SummaryStat
            label="Easiest Venue"
            value={summary.easiest_venue?.venue ?? "—"}
            subtext={
              summary.easiest_venue
                ? `Difficulty: ${fmtScore(summary.easiest_venue.difficulty)}`
                : undefined
            }
            icon={<TrendingDown size={18} className="text-accent" />}
            colour="#10B981"
          />
          <SummaryStat
            label="Most Used Venue"
            value={summary.most_used_venue?.venue ?? "—"}
            subtext={
              summary.most_used_venue
                ? `${fmtInt(summary.most_used_venue.matches)} matches`
                : undefined
            }
            icon={<Trophy size={18} className="text-gold" />}
          />
        </div>
      )}

      {/* Tab switcher */}
      {activeTab !== "detail" && (
        <div className="flex items-center gap-1 border-b border-surface-elevated">
          <button
            onClick={() => setActiveTab("venues")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "venues"
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            <MapPin size={14} className="inline mr-1.5" />
            Venue List
          </button>
          <button
            onClick={() => setActiveTab("ftb")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "ftb"
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            <Target size={14} className="inline mr-1.5" />
            Flat Track Bully Index
          </button>
        </div>
      )}

      {/* ── Venue Detail View ───────────────────────────────── */}
      {activeTab === "detail" && selectedVenue && (
        <VenueDetailPanel
          venueName={selectedVenue}
          onClose={handleCloseDetail}
        />
      )}

      {/* ── Venue List Tab ──────────────────────────────────── */}
      {activeTab === "venues" && (
        <div className="space-y-4">
          {/* Filters */}
          <div className="card p-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5">
                <label
                  className="text-xs text-text-secondary"
                  htmlFor="min-matches"
                >
                  Min Matches:
                </label>
                <input
                  id="min-matches"
                  type="number"
                  min={1}
                  max={100}
                  value={minMatches}
                  onChange={(e) =>
                    setMinMatches(Math.max(1, parseInt(e.target.value) || 5))
                  }
                  className="filter-input w-16 text-sm text-center"
                />
              </div>

              <select
                value={venueSort}
                onChange={(e) => {
                  setVenueSort(e.target.value);
                }}
                className="filter-select text-sm"
                aria-label="Sort by"
              >
                {VENUE_SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    Sort: {opt.label}
                  </option>
                ))}
              </select>

              <button
                onClick={() =>
                  setVenueOrder((o) => (o === "asc" ? "desc" : "asc"))
                }
                className="btn-ghost btn-sm"
                aria-label={`Sort ${venueOrder === "asc" ? "ascending" : "descending"}`}
              >
                {venueOrder === "desc" ? (
                  <ChevronDown size={16} />
                ) : (
                  <ChevronUp size={16} />
                )}
                {venueOrder === "desc" ? "Desc" : "Asc"}
              </button>
            </div>
          </div>

          {/* Loading */}
          {venuesLoading && <PageLoading />}

          {/* Error */}
          {venuesError && <PageError message="Failed to load venue data." />}

          {/* Venue table */}
          {!venuesLoading && !venuesError && venues.length > 0 && (
            <div className="card p-4">
              <div className="overflow-x-auto">
                <table className="sortable-table">
                  <thead>
                    <tr>
                      <th className="text-left min-w-[200px]">Venue</th>
                      <SortableHeader
                        label="Matches"
                        column="matches"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Avg Par SR"
                        column="avg_par_sr"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Bdry Rate"
                        column="boundary_rate"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Dot %"
                        column="dot_pct"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Difficulty"
                        column="difficulty_score"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {venues.map((v, i) => (
                      <tr
                        key={v.venue || i}
                        className="cursor-pointer group"
                        onClick={() => handleVenueClick(v.venue)}
                      >
                        <td>
                          <button
                            className="text-sm font-medium text-text-primary group-hover:text-primary transition-colors text-left"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleVenueClick(v.venue);
                            }}
                          >
                            <MapPin
                              size={12}
                              className="inline mr-1.5 text-text-muted"
                            />
                            {v.venue}
                          </button>
                        </td>
                        <td className="text-right font-score tabular-nums">
                          {fmtInt(v.matches)}
                        </td>
                        <td className="text-right font-score tabular-nums">
                          {fmtSR(v.avg_par_sr)}
                        </td>
                        <td className="text-right font-score tabular-nums">
                          {fmtPct(v.boundary_rate)}
                        </td>
                        <td className="text-right font-score tabular-nums">
                          {fmtPct(v.dot_pct)}
                        </td>
                        <td className="text-right">
                          <DifficultyBar score={v.difficulty_score} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {venues.length === 0 && (
                <p className="text-sm text-text-muted italic py-8 text-center">
                  No venues found matching the current filters.
                </p>
              )}
            </div>
          )}

          {!venuesLoading && !venuesError && venues.length === 0 && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <MapPin size={48} className="text-text-muted mb-4" />
              <h2 className="text-h3 text-text-primary mb-2">
                No Venues Found
              </h2>
              <p className="text-sm text-text-secondary max-w-md">
                Try lowering the minimum matches filter to see more venues.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Flat Track Bully Index Tab ──────────────────────── */}
      {activeTab === "ftb" && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className="card p-4 border-l-4 border-l-warning">
            <div className="flex items-start gap-3">
              <Info size={18} className="text-warning shrink-0 mt-0.5" />
              <div className="text-sm text-text-secondary">
                <p>
                  <strong className="text-text-primary">
                    Flat Track Bully Index
                  </strong>{" "}
                  measures how much a player's performance varies based on venue
                  difficulty. A score near 0 means consistent everywhere; a
                  large negative score suggests the player excels at easier
                  venues but struggles at harder ones.
                </p>
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="card p-4">
            <div className="flex flex-wrap items-center gap-3">
              <select
                value={ftbRole}
                onChange={(e) => {
                  setFtbRole(e.target.value as "bat" | "bowl");
                  setFtbPage(1);
                }}
                className="filter-select text-sm"
                aria-label="Role"
              >
                <option value="bat">Batters</option>
                <option value="bowl">Bowlers</option>
              </select>

              <div className="flex items-center gap-1.5">
                <label
                  className="text-xs text-text-secondary"
                  htmlFor="ftb-min-innings"
                >
                  Min Innings:
                </label>
                <input
                  id="ftb-min-innings"
                  type="number"
                  min={1}
                  max={200}
                  value={ftbMinInnings}
                  onChange={(e) => {
                    setFtbMinInnings(
                      Math.max(1, parseInt(e.target.value) || 20),
                    );
                    setFtbPage(1);
                  }}
                  className="filter-input w-16 text-sm text-center"
                />
              </div>

              <select
                value={ftbSort}
                onChange={(e) => {
                  setFtbSort(e.target.value);
                  setFtbPage(1);
                }}
                className="filter-select text-sm"
                aria-label="Sort by"
              >
                {FTB_SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    Sort: {opt.label}
                  </option>
                ))}
              </select>

              <button
                onClick={() =>
                  setFtbOrder((o) => (o === "asc" ? "desc" : "asc"))
                }
                className="btn-ghost btn-sm"
              >
                {ftbOrder === "desc" ? (
                  <ChevronDown size={16} />
                ) : (
                  <ChevronUp size={16} />
                )}
                {ftbOrder === "desc" ? "Desc" : "Asc"}
              </button>
            </div>
          </div>

          {/* Loading */}
          {ftbLoading && <PageLoading />}

          {/* Error */}
          {ftbError && (
            <PageError message="Failed to load Flat Track Bully data." />
          )}

          {/* FTB Table */}
          {!ftbLoading && !ftbError && ftbPlayers.length > 0 && (
            <div className="card p-4">
              <div className="overflow-x-auto">
                <table className="sortable-table">
                  <thead>
                    <tr>
                      <th className="text-left min-w-[180px]">Player</th>
                      <th className="text-left">Country</th>
                      <SortableHeader
                        label="FTB Index"
                        column="flat_track_index"
                        currentSort={ftbSort}
                        currentOrder={ftbOrder}
                        onSort={toggleFtbSort}
                      />
                      <SortableHeader
                        label="Innings"
                        column="innings_at_known_venues"
                        currentSort={ftbSort}
                        currentOrder={ftbOrder}
                        onSort={toggleFtbSort}
                      />
                      <SortableHeader
                        label="Avg Difficulty"
                        column="avg_venue_difficulty_faced"
                        currentSort={ftbSort}
                        currentOrder={ftbOrder}
                        onSort={toggleFtbSort}
                      />
                      <th className="text-center">Interpretation</th>
                      <th className="text-right">Grade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ftbPlayers.map((p, i) => (
                      <tr key={p.id || i}>
                        <td>
                          <Link
                            to={`/player/${p.id}`}
                            className="text-sm font-medium text-primary hover:underline"
                          >
                            {p.name}
                          </Link>
                        </td>
                        <td className="text-xs text-text-secondary">
                          {countryFlag(p.country)} {p.country}
                        </td>
                        <td className="text-right">
                          <span
                            className="font-score text-sm font-bold tabular-nums"
                            style={{
                              color: ftbColour(p.flat_track_index),
                            }}
                          >
                            {p.flat_track_index != null
                              ? p.flat_track_index.toFixed(2)
                              : "—"}
                          </span>
                        </td>
                        <td className="text-right font-score tabular-nums">
                          {fmtInt(p.innings_at_known_venues)}
                        </td>
                        <td className="text-right font-score tabular-nums">
                          {p.avg_venue_difficulty_faced != null
                            ? p.avg_venue_difficulty_faced.toFixed(1)
                            : "—"}
                        </td>
                        <td className="text-center">
                          <span className="inline-flex items-center gap-1.5 text-xs text-text-secondary">
                            {ftbIcon(p.interpretation, p.icon)}
                            <span className="hidden sm:inline">
                              {p.interpretation}
                            </span>
                          </span>
                        </td>
                        <td className="text-right">
                          <GradeBadge grade={p.overall_grade} size="xs" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {ftbTotalPages > 1 && (
                <div className="mt-4">
                  <Pagination
                    page={ftbPage}
                    totalPages={ftbTotalPages}
                    onPageChange={setFtbPage}
                    total={ftbResponse?.total}
                    perPage={ftbPerPage}
                    showSummary
                  />
                </div>
              )}
            </div>
          )}

          {!ftbLoading && !ftbError && ftbPlayers.length === 0 && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <Target size={48} className="text-text-muted mb-4" />
              <h2 className="text-h3 text-text-primary mb-2">
                No Players Found
              </h2>
              <p className="text-sm text-text-secondary max-w-md">
                Try lowering the minimum innings filter.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
