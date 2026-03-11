/**
 * SpellsLog — Standalone page for viewing a bowler's full spells history.
 *
 * Route: /player/:id/spells
 *
 * Features:
 *   - Full paginated table of all bowling spells
 *   - Sortable columns (date, overs, runs, wickets, economy, dot%, opposition)
 *   - Back link to player profile
 *   - Player name + country in header
 *   - Phase economy columns (powerplay, middle, death) when available
 *   - Context columns (economy vs par) when available
 *   - Responsive: horizontal scroll on mobile
 *   - Keyboard accessible
 */

import { useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, ArrowUpDown, ChevronUp, ChevronDown } from "lucide-react";

import { usePlayerProfile, usePlayerSpells } from "@/api/queries";
import { isBowlerProfile, isBatterProfile } from "@/api/types";
import type { SpellDetail } from "@/api/types";
import Pagination from "@/components/Pagination";
import { fmtDate, fmtEcon, fmtPct, fmtOvers, countryFlag } from "@/lib/format";
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
  render: (spell: SpellDetail, index: number) => React.ReactNode;
}

const PER_PAGE_OPTIONS = [10, 25, 50, 100];

function getColumns(rankOffset: number): ColumnDef[] {
  return [
    {
      key: "rank",
      label: "#",
      align: "right",
      width: "w-10",
      render: (_spell: SpellDetail, index: number) => (
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
      render: (spell: SpellDetail) => (
        <span className="text-text-secondary text-sm">
          {fmtDate(spell.date)}
        </span>
      ),
    },
    {
      key: "opposition",
      label: "Vs",
      align: "left",
      width: "w-32",
      render: (spell: SpellDetail) => (
        <span className="truncate max-w-[8rem] text-sm">
          {spell.opposition || "—"}
        </span>
      ),
    },
    {
      key: "overs_bowled",
      label: "Overs",
      sortKey: "overs_bowled",
      align: "right",
      width: "w-14",
      render: (spell: SpellDetail) => (
        <span className="tabular-nums">{fmtOvers(spell.overs_bowled)}</span>
      ),
    },
    {
      key: "runs_conceded",
      label: "Runs",
      sortKey: "runs_conceded",
      align: "right",
      width: "w-14",
      render: (spell: SpellDetail) => (
        <span className="tabular-nums">{spell.runs_conceded}</span>
      ),
    },
    {
      key: "wickets",
      label: "Wkts",
      sortKey: "wickets",
      align: "right",
      width: "w-14",
      render: (spell: SpellDetail) => {
        const colour =
          spell.wickets >= 4
            ? "#FFD700"
            : spell.wickets >= 3
              ? "#10B981"
              : spell.wickets >= 2
                ? "#22C55E"
                : undefined;
        return (
          <span
            className="font-score tabular-nums font-medium"
            style={colour ? { color: colour } : undefined}
          >
            {spell.wickets}
          </span>
        );
      },
    },
    {
      key: "economy",
      label: "Econ",
      sortKey: "economy",
      align: "right",
      width: "w-16",
      render: (spell: SpellDetail) => {
        const colour =
          spell.economy != null && spell.economy <= 6.0
            ? "#10B981"
            : spell.economy != null && spell.economy <= 8.0
              ? "#22C55E"
              : spell.economy != null && spell.economy > 10.0
                ? "#EF4444"
                : spell.economy != null && spell.economy > 8.5
                  ? "#F97316"
                  : undefined;
        return (
          <span
            className="font-score tabular-nums"
            style={colour ? { color: colour } : undefined}
          >
            {fmtEcon(spell.economy)}
          </span>
        );
      },
    },
    {
      key: "dot_pct",
      label: "Dot%",
      sortKey: "dot_pct",
      align: "right",
      width: "w-16",
      render: (spell: SpellDetail) => (
        <span className="tabular-nums">{fmtPct(spell.dot_pct)}</span>
      ),
    },
    {
      key: "fours_conceded",
      label: "4s",
      sortKey: "fours_conceded",
      align: "right",
      width: "w-12",
      hideOnMobile: true,
      render: (spell: SpellDetail) => (
        <span className="tabular-nums text-text-secondary">
          {spell.fours_conceded ?? "—"}
        </span>
      ),
    },
    {
      key: "sixes_conceded",
      label: "6s",
      sortKey: "sixes_conceded",
      align: "right",
      width: "w-12",
      hideOnMobile: true,
      render: (spell: SpellDetail) => (
        <span className="tabular-nums text-text-secondary">
          {spell.sixes_conceded ?? "—"}
        </span>
      ),
    },
    {
      key: "wides_count",
      label: "Wd",
      align: "right",
      width: "w-10",
      hideOnMobile: true,
      render: (spell: SpellDetail) => (
        <span className="tabular-nums text-text-muted text-xs">
          {spell.wides_count ?? "—"}
        </span>
      ),
    },
    {
      key: "noballs_count",
      label: "NB",
      align: "right",
      width: "w-10",
      hideOnMobile: true,
      render: (spell: SpellDetail) => (
        <span className="tabular-nums text-text-muted text-xs">
          {spell.noballs_count ?? "—"}
        </span>
      ),
    },
    {
      key: "powerplay_economy",
      label: "PP Econ",
      sortKey: "powerplay_economy",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (spell: SpellDetail) => (
        <span className="tabular-nums text-xs text-text-secondary">
          {fmtEcon(spell.powerplay_economy)}
        </span>
      ),
    },
    {
      key: "middle_economy",
      label: "Mid Econ",
      sortKey: "middle_economy",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (spell: SpellDetail) => (
        <span className="tabular-nums text-xs text-text-secondary">
          {fmtEcon(spell.middle_economy)}
        </span>
      ),
    },
    {
      key: "death_economy",
      label: "Death Econ",
      shortLabel: "Dth Econ",
      sortKey: "death_economy",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (spell: SpellDetail) => (
        <span className="tabular-nums text-xs text-text-secondary">
          {fmtEcon(spell.death_economy)}
        </span>
      ),
    },
    {
      key: "economy_vs_par",
      label: "Econ/Par",
      sortKey: "economy_vs_par",
      align: "right",
      width: "w-16",
      hideOnMobile: true,
      render: (spell: SpellDetail) => {
        if (spell.economy_vs_par == null)
          return <span className="text-text-muted">—</span>;
        const val = spell.economy_vs_par;
        // For bowlers, negative econ vs par is GOOD (below par economy)
        const colour = val < 0 ? "#10B981" : val > 1 ? "#EF4444" : "#64748B";
        return (
          <span
            className="font-score tabular-nums text-xs"
            style={{ color: colour }}
          >
            {val > 0 ? "+" : ""}
            {val.toFixed(2)}
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

export default function SpellsLogPage() {
  const { id } = useParams<{ id: string }>();

  // Player profile (for name/country header)
  const { data: profile, isLoading: profileLoading } = usePlayerProfile(id);

  // Pagination & sorting state
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(25);
  const [sortBy, setSortBy] = useState("date");
  const [order, setOrder] = useState("desc");

  // Fetch spells data
  const {
    data: spellsData,
    isLoading,
    isFetching,
  } = usePlayerSpells(id, {
    page,
    perPage,
    sortBy,
    order,
  });

  const spells: SpellDetail[] = spellsData?.spells ?? [];
  const total = spellsData?.total ?? 0;
  const totalPages =
    spellsData?.total_pages ?? (Math.ceil(total / perPage) || 1);

  // Handle column sort
  const handleSort = useCallback(
    (key: string) => {
      if (key === sortBy) {
        setOrder((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(key);
        // For economy, lower is better → asc by default
        setOrder(key === "economy" ? "asc" : "desc");
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
  const playerName = profile ? profile.name : "Player";
  const playerCountry = profile
    ? isBowlerProfile(profile)
      ? profile.country
      : isBatterProfile(profile)
        ? profile.country
        : ""
    : "";
  const flag = countryFlag(playerCountry);

  const rankOffset = (page - 1) * perPage;
  const columns = getColumns(rankOffset);

  // Check if player is actually a bowler
  const isBowler = profile ? isBowlerProfile(profile) : true;

  // Get career stats if bowler
  const bowlerProfile = profile && isBowlerProfile(profile) ? profile : null;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
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
            <span className="text-text-muted font-normal">— Spells Log</span>
          </h1>
          {total > 0 && (
            <p className="text-sm text-text-secondary mt-1">
              {total.toLocaleString()} spells recorded
            </p>
          )}
        </div>

        {!isBowler && profile && (
          <div className="text-sm text-warning bg-warning/10 px-3 py-2 rounded-lg">
            ⚠ This player is primarily a batter.{" "}
            <Link
              to={`/player/${id}/innings`}
              className="underline hover:text-warning"
            >
              View innings instead →
            </Link>
          </div>
        )}
      </div>

      {/* ── Summary stats row ─────────────────────────────────── */}
      {bowlerProfile && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          <SummaryCard label="Matches" value={String(bowlerProfile.matches)} />
          <SummaryCard
            label="Wickets"
            value={String(bowlerProfile.total_wickets)}
          />
          <SummaryCard
            label="Economy"
            value={fmtEcon(bowlerProfile.career_economy)}
            colour={scoreToColour(bowlerProfile.score_accuracy)}
          />
          <SummaryCard
            label="Bowling SR"
            value={
              bowlerProfile.career_sr_bowl != null
                ? bowlerProfile.career_sr_bowl.toFixed(1)
                : "—"
            }
          />
          <SummaryCard
            label="Dot%"
            value={fmtPct(bowlerProfile.career_dot_pct)}
          />
          <SummaryCard
            label="Runs Conceded"
            value={String(bowlerProfile.total_runs_conceded ?? 0)}
          />
        </div>
      )}

      {/* ── Table ─────────────────────────────────────────────── */}
      <div className="card p-0 overflow-hidden">
        {/* Loading indicator */}
        {isFetching && (
          <div className="h-1 bg-primary/20">
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
              ) : spells.length === 0 ? (
                <tr>
                  <td
                    colSpan={columns.length}
                    className="px-6 py-16 text-center text-text-muted"
                  >
                    <div className="text-3xl mb-2">🎳</div>
                    <p className="text-sm">
                      No spells data available for this player.
                    </p>
                  </td>
                </tr>
              ) : (
                spells.map((spell, i) => {
                  const isFifer = spell.wickets >= 5;
                  const isThreeWickets = spell.wickets >= 3 && !isFifer;
                  return (
                    <tr
                      key={`${spell.match_id}-${i}`}
                      className={`hover:bg-surface-elevated/30 transition-colors ${
                        isFifer
                          ? "bg-gold/5"
                          : isThreeWickets
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
                            {col.render(spell, i)}
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
          Five-wicket haul (5+)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-accent/20 border border-accent/40" />
          Three-wicket haul (3+)
        </span>
        <span>Econ/Par = Economy minus Par Economy for the match</span>
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
