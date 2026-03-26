/**
 * InningsLog — Standalone page for viewing a batter's full innings history.
 *
 * Route: /player/:id/innings
 *
 * Features:
 *   - Full paginated table of all batting innings
 *   - Sortable columns (date, runs, SR, balls, 4s, 6s, opposition)
 *   - Back link to player profile
 *   - Player name + country in header
 *   - Phase SR columns (powerplay, middle, death) when available
 *   - Context columns (SR vs Par) when available
 *   - Responsive: horizontal scroll on mobile
 *   - Keyboard accessible
 */

import { useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, ArrowUpDown, ChevronUp, ChevronDown } from "lucide-react";

import { usePlayerProfile, usePlayerInnings } from "@/api/queries";
import { isBatterProfile } from "@/api/types";
import type { InningsDetail } from "@/api/types";
import Pagination from "@/components/Pagination";
import { fmtDate, fmtSR, countryFlag } from "@/lib/format";
import { scoreToColour } from "@/lib/colours";

// ── Column definitions ───────────────────────────────────────────

interface ColumnDef {
  key: string;
  label: string;
  shortLabel?: string;
  sortKey?: string;
  align: "left" | "right" | "center";
  width?: string;
  hideOnMobile?: boolean;
  render: (inn: InningsDetail, index: number) => React.ReactNode;
}

const PER_PAGE_OPTIONS = [10, 25, 50, 100];

function getColumns(rankOffset: number): ColumnDef[] {
  return [
    {
      key: "rank",
      label: "#",
      align: "right",
      width: "w-10",
      render: (_inn: InningsDetail, index: number) => (
        <span className="text-text-muted tabular-nums text-xs">
          {rankOffset + index + 1}
        </span>
      ),
    },
    {
      key: "date",
      label: "Date",
      sortKey: "date",
      align: "left",
      width: "w-28",
      render: (inn: InningsDetail) => (
        <span className="text-text-secondary text-sm">{fmtDate(inn.date)}</span>
      ),
    },
    {
      key: "opposition",
      label: "Vs",
      align: "left",
      width: "w-32",
      render: (inn: InningsDetail) => (
        <span className="truncate max-w-[8rem] text-sm">
          {inn.opposition || "—"}
        </span>
      ),
    },
    {
      key: "runs",
      label: "Runs",
      sortKey: "runs",
      align: "right",
      width: "w-16",
      render: (inn: InningsDetail) => (
        <span className="font-score tabular-nums font-medium">
          {inn.runs}
          {!inn.is_out && inn.runs > 0 ? "*" : ""}
        </span>
      ),
    },
    {
      key: "balls_faced",
      label: "Balls",
      sortKey: "balls_faced",
      align: "right",
      width: "w-14",
      render: (inn: InningsDetail) => (
        <span className="tabular-nums">{inn.balls_faced}</span>
      ),
    },
    {
      key: "sr",
      label: "SR",
      sortKey: "sr",
      align: "right",
      width: "w-16",
      render: (inn: InningsDetail) => {
        const colour =
          inn.sr != null && inn.sr >= 150
            ? "#10B981"
            : inn.sr != null && inn.sr >= 130
              ? "#22C55E"
              : inn.sr != null && inn.sr < 100
                ? "#F97316"
                : undefined;
        return (
          <span
            className="font-score tabular-nums"
            style={colour ? { color: colour } : undefined}
          >
            {fmtSR(inn.sr)}
          </span>
        );
      },
    },
    {
      key: "fours",
      label: "4s",
      sortKey: "fours",
      align: "right",
      width: "w-12",
      render: (inn: InningsDetail) => (
        <span className="tabular-nums">{inn.fours}</span>
      ),
    },
    {
      key: "sixes",
      label: "6s",
      sortKey: "sixes",
      align: "right",
      width: "w-12",
      render: (inn: InningsDetail) => (
        <span className="tabular-nums">{inn.sixes}</span>
      ),
    },
    {
      key: "dots",
      label: "Dots",
      shortLabel: "Dots",
      sortKey: "dots",
      align: "right",
      width: "w-14",
      hideOnMobile: true,
      render: (inn: InningsDetail) => (
        <span className="tabular-nums text-text-secondary">
          {inn.dots ?? "—"}
        </span>
      ),
    },
    {
      key: "how_out",
      label: "Dismissal",
      align: "left",
      width: "w-28",
      hideOnMobile: true,
      render: (inn: InningsDetail) => (
        <span className="text-text-secondary text-xs truncate max-w-[7rem]">
          {inn.is_out ? inn.how_out || "out" : "not out"}
        </span>
      ),
    },
    {
      key: "batting_position",
      label: "Pos",
      sortKey: "batting_position",
      align: "right",
      width: "w-12",
      hideOnMobile: true,
      render: (inn: InningsDetail) => (
        <span className="tabular-nums text-text-muted text-xs">
          {inn.batting_position ?? "—"}
        </span>
      ),
    },
    {
      key: "powerplay_sr",
      label: "PP SR",
      sortKey: "powerplay_sr",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (inn: InningsDetail) => (
        <span className="tabular-nums text-xs text-text-secondary">
          {fmtSR(inn.powerplay_sr)}
        </span>
      ),
    },
    {
      key: "middle_sr",
      label: "Mid SR",
      sortKey: "middle_sr",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (inn: InningsDetail) => (
        <span className="tabular-nums text-xs text-text-secondary">
          {fmtSR(inn.middle_sr)}
        </span>
      ),
    },
    {
      key: "death_sr",
      label: "Death SR",
      sortKey: "death_sr",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (inn: InningsDetail) => (
        <span className="tabular-nums text-xs text-text-secondary">
          {fmtSR(inn.death_sr)}
        </span>
      ),
    },
    {
      key: "sr_vs_par",
      label: "SR/Par",
      sortKey: "sr_vs_par",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (inn: InningsDetail) => {
        if (inn.sr_vs_par == null)
          return <span className="text-text-muted">—</span>;
        const val = inn.sr_vs_par;
        const colour = val > 0 ? "#10B981" : val < -10 ? "#EF4444" : "#64748B";
        return (
          <span
            className="font-score tabular-nums text-xs"
            style={{ color: colour }}
          >
            {val > 0 ? "+" : ""}
            {val.toFixed(1)}
          </span>
        );
      },
    },
  ];
}

// ── Sortable header component ────────────────────────────────────

function SortableHeader({
  label,
  shortLabel,
  sortKey,
  currentSort,
  currentOrder,
  align,
  onSort,
}: {
  label: string;
  shortLabel?: string;
  sortKey?: string;
  currentSort: string;
  currentOrder: string;
  align: "left" | "right" | "center";
  onSort: (key: string) => void;
}) {
  const isSortable = !!sortKey;
  const isActive = sortKey === currentSort;
  const alignClass =
    align === "right"
      ? "text-right justify-end"
      : align === "center"
        ? "text-center justify-center"
        : "text-left justify-start";

  if (!isSortable) {
    return (
      <th
        className={`px-3 py-2 text-small text-text-secondary border-b border-surface-elevated ${alignClass}`}
      >
        <span className="hidden sm:inline">{label}</span>
        <span className="sm:hidden">{shortLabel ?? label}</span>
      </th>
    );
  }

  return (
    <th
      className={`px-3 py-2 text-small border-b border-surface-elevated cursor-pointer select-none ${alignClass} ${
        isActive ? "text-primary" : "text-text-secondary hover:text-primary"
      }`}
      onClick={() => onSort(sortKey)}
      role="columnheader"
      aria-sort={
        isActive
          ? currentOrder === "asc"
            ? "ascending"
            : "descending"
          : "none"
      }
    >
      <span className="inline-flex items-center gap-1">
        <span className="hidden sm:inline">{label}</span>
        <span className="sm:hidden">{shortLabel ?? label}</span>
        {isActive ? (
          currentOrder === "asc" ? (
            <ChevronUp size={12} />
          ) : (
            <ChevronDown size={12} />
          )
        ) : (
          <ArrowUpDown size={10} className="opacity-30" />
        )}
      </span>
    </th>
  );
}

// ── Main page component ──────────────────────────────────────────

export default function InningsLogPage() {
  const { id } = useParams<{ id: string }>();

  // Player profile (for name/country header)
  const { data: profile, isLoading: profileLoading } = usePlayerProfile(id);

  // Pagination & sorting state
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(25);
  const [sortBy, setSortBy] = useState("date");
  const [order, setOrder] = useState("desc");

  // Fetch innings data
  const {
    data: inningsData,
    isLoading,
    isFetching,
  } = usePlayerInnings(id, {
    page,
    perPage,
    sortBy,
    order,
  });

  const innings: InningsDetail[] = inningsData?.innings ?? [];
  const total = inningsData?.total ?? 0;
  const totalPages =
    inningsData?.total_pages ?? (Math.ceil(total / perPage) || 1);

  // Handle column sort
  const handleSort = useCallback(
    (key: string) => {
      if (key === sortBy) {
        // Toggle order
        setOrder((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(key);
        setOrder(key === "date" ? "desc" : "desc");
      }
      setPage(1);
    },
    [sortBy],
  );

  // Handle page change
  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  // Handle per-page change
  const handlePerPageChange = useCallback((newPerPage: number) => {
    setPerPage(newPerPage);
    setPage(1);
  }, []);

  // Player info from profile
  const playerName = profile
    ? isBatterProfile(profile)
      ? profile.name
      : profile.name
    : "Player";
  const playerCountry = profile
    ? isBatterProfile(profile)
      ? profile.country
      : profile.country
    : "";
  const flag = countryFlag(playerCountry);

  const rankOffset = (page - 1) * perPage;
  const columns = getColumns(rankOffset);

  // Check if the player is actually a batter
  const isBatter = profile ? isBatterProfile(profile) : true;

  return (
    <div className="app-page page-stack">
      {/* ── Back link ─────────────────────────────────────────── */}
      <Link
        to={`/player/${id}`}
        className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-primary transition-colors"
      >
        <ArrowLeft size={14} />
        Back to {playerName}'s profile
      </Link>

      {/* ── Header ────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-h2 text-text-primary flex items-center gap-2">
            {flag && <span className="text-xl">{flag}</span>}
            {profileLoading ? (
              <span className="skeleton h-7 w-48 inline-block" />
            ) : (
              <span>{playerName}</span>
            )}
            <span className="text-text-muted font-normal">— Innings Log</span>
          </h1>
          {total > 0 && (
            <p className="text-sm text-text-secondary mt-1">
              {total.toLocaleString()} innings recorded
            </p>
          )}
        </div>

        {!isBatter && profile && (
          <div className="text-sm text-warning bg-warning/10 px-3 py-2 rounded-lg">
            Note: this player is primarily a bowler.{" "}
            <Link
              to={`/player/${id}/spells`}
              className="underline hover:text-warning"
            >
              View spells instead →
            </Link>
          </div>
        )}
      </div>

      {/* ── Summary stats row ─────────────────────────────────── */}
      {profile && isBatterProfile(profile) && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          <SummaryCard label="Innings" value={String(profile.innings_count)} />
          <SummaryCard
            label="Total Runs"
            value={profile.total_runs.toLocaleString()}
          />
          <SummaryCard
            label="Career SR"
            value={fmtSR(profile.career_sr)}
            colour={scoreToColour(profile.score_acceleration)}
          />
          <SummaryCard
            label="Career Avg"
            value={
              profile.career_avg != null ? profile.career_avg.toFixed(1) : "—"
            }
          />
          <SummaryCard label="Fours" value={String(profile.total_fours ?? 0)} />
          <SummaryCard label="Sixes" value={String(profile.total_sixes ?? 0)} />
        </div>
      )}

      {/* ── Table ─────────────────────────────────────────────── */}
      <div className="card p-0 overflow-hidden">
        {/* Loading indicator */}
        {isFetching && (
          <div className="h-1 bg-white/10">
            <div className="h-1 bg-primary animate-pulse w-1/3" />
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {columns.map((col) => (
                  <SortableHeader
                    key={col.key}
                    label={col.label}
                    shortLabel={col.shortLabel}
                    sortKey={col.sortKey}
                    currentSort={sortBy}
                    currentOrder={order}
                    align={col.align}
                    onSort={handleSort}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                // Skeleton rows
                Array.from({ length: 10 }).map((_, i) => (
                  <tr key={`skel-${i}`}>
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className={`px-3 py-2.5 border-b border-surface-elevated/50 ${
                          col.align === "right" ? "text-right" : "text-left"
                        }`}
                      >
                        <div className="skeleton h-4 w-full max-w-[4rem] inline-block" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : innings.length === 0 ? (
                <tr>
                  <td
                    colSpan={columns.length}
                    className="px-6 py-16 text-center text-text-muted"
                  >
                    <div className="mb-2 text-lg font-semibold text-text-muted">No innings</div>
                    <p className="text-sm">
                      No innings data available for this player.
                    </p>
                  </td>
                </tr>
              ) : (
                innings.map((inn, i) => {
                  const isHighScore = inn.runs >= 50;
                  const isCentury = inn.runs >= 100;
                  return (
                    <tr
                      key={`${inn.match_id}-${i}`}
                      className={`hover:bg-surface-elevated/30 transition-colors ${
                        isCentury
                          ? "bg-gold/5"
                          : isHighScore
                            ? "bg-accent/5"
                            : ""
                      }`}
                    >
                      {columns.map((col) => {
                        const hiddenClass = col.hideOnMobile
                          ? "hidden lg:table-cell"
                          : "";
                        return (
                          <td
                            key={col.key}
                            className={`px-3 py-2.5 border-b border-surface-elevated/50 ${
                              col.align === "right"
                                ? "text-right"
                                : col.align === "center"
                                  ? "text-center"
                                  : "text-left"
                            } ${hiddenClass}`}
                          >
                            {col.render(inn, i)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* ── Pagination ──────────────────────────────────────── */}
        {totalPages > 0 && (
          <div className="px-4 py-3 border-t border-surface-elevated">
            <Pagination
              page={page}
              totalPages={totalPages}
              total={total}
              perPage={perPage}
              onPageChange={handlePageChange}
              onPerPageChange={handlePerPageChange}
              perPageOptions={PER_PAGE_OPTIONS}
              showSummary
              showPerPage
              showEnds
              size="sm"
            />
          </div>
        )}
      </div>

      {/* ── Legend ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-gold/20 border border-gold/40" />
          Century (100+)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-accent/20 border border-accent/40" />
          Half-century (50+)
        </span>
        <span>* = not out</span>
        <span>SR/Par = Strike Rate minus Par SR for the match</span>
      </div>
    </div>
  );
}

// ── Summary card component ───────────────────────────────────────

function SummaryCard({
  label,
  value,
  colour,
}: {
  label: string;
  value: string;
  colour?: string;
}) {
  return (
    <div className="card p-3 flex flex-col gap-1">
      <span className="text-xs text-text-muted uppercase tracking-wider">
        {label}
      </span>
      <span
        className="text-lg font-score tabular-nums font-semibold"
        style={colour ? { color: colour } : undefined}
      >
        {value}
      </span>
    </div>
  );
}
