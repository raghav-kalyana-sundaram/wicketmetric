/**
 * Venues — Venue Analysis page.
 *
 * Route: /venues
 *
 * Features (from gui.md § 6.10):
 *   - Venue difficulty list with sorting (avg par SR, boundary rate, dot %, difficulty score)
 *   - Venue detail view — click any venue for detailed breakdown
 *   - Player at venue stats — search a player to see their venue-by-venue record
 *   - Venue summary statistics (hardest, easiest, most used)
 *
 * Data fetching:
 *   - useVenues() — list of all venues with baselines
 *   - useVenueSummary() — aggregate venue statistics
 *   - VenueDetailPanel — profile, trends, leaders (see VenueDetailPanel.tsx)
 */

import { useState, useMemo, useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  MapPin,
  ChevronDown,
  ChevronUp,
  Trophy,
  TrendingUp,
  TrendingDown,
} from "lucide-react";

import { PageLoading, PageError } from "@/components/Layout";
import { useVenues, useVenueSummary } from "@/api/queries";
import { VenueDetailPanel } from "@/pages/VenueDetailPanel";
import { scoreToColour as _scoreToColour } from "@/lib/colours";
import {
  fmtInt,
  fmtSR,
  fmtPct,
  fmtScore,
} from "@/lib/format";
import type {
  VenueBaseline,
  VenueSummary,
  VenueListParams,
} from "@/api/types";

// ── Tab type ─────────────────────────────────────────────────────

type VenueTab = "venues" | "detail";

// ── Sort options ─────────────────────────────────────────────────

const VENUE_SORT_OPTIONS = [
  { value: "venue_difficulty", label: "Difficulty (0–100)" },
  { value: "venue_avg_par_sr", label: "Avg Par SR" },
  { value: "venue_avg_boundary_rate", label: "Boundary Rate" },
  { value: "venue_avg_dot_pct", label: "Dot %" },
  { value: "venue_matches", label: "Matches" },
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

// ── Main Component ───────────────────────────────────────────────

export default function Venues() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<VenueTab>("venues");
  const [selectedVenue, setSelectedVenue] = useState<string | null>(null);

  // ── Venue list state ───────────────────────────────────────────
  const [venueSort, setVenueSort] = useState("venue_difficulty");
  const [venueOrder, setVenueOrder] = useState<"asc" | "desc">("desc");
  const [minMatches, setMinMatches] = useState(10);

  useEffect(() => {
    const v = searchParams.get("venue");
    if (v) {
      setSelectedVenue(v);
      setActiveTab("detail");
      return;
    }
    setSelectedVenue(null);
    setActiveTab((t) => (t === "detail" ? "venues" : t));
  }, [searchParams]);

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

  const handleVenueClick = useCallback(
    (venueName: string) => {
      setSelectedVenue(venueName);
      setActiveTab("detail");
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          n.set("venue", venueName);
          if (!n.get("vtab")) n.set("vtab", "overview");
          return n;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const handleCloseDetail = useCallback(() => {
    setSelectedVenue(null);
    setActiveTab("venues");
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.delete("venue");
        n.delete("vtab");
        return n;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  // ── Derived data ───────────────────────────────────────────────

  const venues: VenueBaseline[] = useMemo(
    () => (venuesData as { venues?: VenueBaseline[] })?.venues ?? [],
    [venuesData],
  );

  const summary = summaryData as VenueSummary | undefined;

  // ── Render ─────────────────────────────────────────────────────

  return (
    <div className="app-page page-stack animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <h1 className="page-title flex items-center gap-3">
          <MapPin size={28} className="text-primary" />
          Venue Analysis
        </h1>
        <p className="page-subtitle">
          Explore venue characteristics and difficulty ratings across the
          dataset.
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
                    setMinMatches(Math.max(1, parseInt(e.target.value, 10) || 10))
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
                        column="venue_matches"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Avg Par SR"
                        column="venue_avg_par_sr"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Bdry Rate"
                        column="venue_avg_boundary_rate"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Dot %"
                        column="venue_avg_dot_pct"
                        currentSort={venueSort}
                        currentOrder={venueOrder}
                        onSort={toggleVenueSort}
                      />
                      <SortableHeader
                        label="Difficulty (0–100)"
                        column="venue_difficulty"
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
    </div>
  );
}
