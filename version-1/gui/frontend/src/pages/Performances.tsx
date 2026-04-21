/**
 * Match impact performances — browse individual match performances ranked by impact.
 *
 * Route: /performances (filters in query string)
 *
 * Similar filters to scorecards search (date, team, event, player) plus discipline
 * and sort order. Data from GET /api/scorecards/performances/by-impact.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Zap, ChevronRight, Info, FileText, Trophy, GitCompare } from "lucide-react";
import { useFormat } from "@/api/FormatContext";
import { isFranchiseFormat } from "@/api/formatConstants";
import { useMatchImpactPerformances } from "@/api/queries";
import type {
  MatchImpactPerformanceRow,
  MatchImpactPerformancesParams,
} from "@/api/types";
import CrossLinkBar, { type CrossLink } from "@/components/CrossLinkBar";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import Pagination from "@/components/Pagination";
import {
  formatCombinedSummary,
  formatScorecardMatchLabel,
} from "@/lib/scorecardMatchImpact";
import { fmtDate } from "@/lib/format";
import "@/styles/scorecards.css";

const FIELD =
  "block w-full rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted";

function parseDiscipline(
  raw: string | null,
): "combined" | "bat" | "bowl" {
  if (raw === "bat" || raw === "bowl") return raw;
  return "combined";
}

function parseOrder(raw: string | null): "asc" | "desc" {
  return raw === "asc" ? "asc" : "desc";
}

function parseMatchTier(
  raw: string | null,
): "all" | "main_only" | "associate_fixture" {
  if (raw === "main_only" || raw === "associate_fixture") return raw;
  return "all";
}

function clampPerPage(n: number): number {
  if (!Number.isFinite(n) || n < 1) return 25;
  return Math.min(100, Math.max(1, Math.floor(n)));
}

function rowToCombined(r: MatchImpactPerformanceRow) {
  return {
    playerId: r.player_id,
    name: r.player_name,
    batImpact: r.bat_impact,
    bowlImpact: r.bowl_impact,
    totalImpact: r.total_impact,
    batRuns: r.bat_runs ?? undefined,
    batBalls: r.bat_balls ?? undefined,
    bowlWkts: r.bowl_wickets ?? undefined,
    bowlRuns: r.bowl_runs_conceded ?? undefined,
    bowlBalls: r.bowl_balls ?? undefined,
  };
}

const PERF_PRESETS = [
  { id: "greatest-knocks", label: "Greatest knocks", discipline: "bat" as const, order: "desc" as const },
  { id: "greatest-spells", label: "Greatest spells", discipline: "bowl" as const, order: "desc" as const },
  { id: "best-allround", label: "Best all-round", discipline: "combined" as const, order: "desc" as const },
  { id: "most-clutch", label: "Most clutch", discipline: "combined" as const, order: "desc" as const },
];

const CROSS_LINKS: CrossLink[] = [
  { label: "Match scorecards", to: "/scorecards", icon: <FileText size={12} /> },
  { label: "Player rankings", to: "/rankings", icon: <Trophy size={12} /> },
  { label: "Compare players", to: "/compare", icon: <GitCompare size={12} /> },
];

type Draft = {
  dateFrom: string;
  dateTo: string;
  team: string;
  event: string;
  playerId: string | null;
  matchTier: "all" | "main_only" | "associate_fixture";
  discipline: "combined" | "bat" | "bowl";
  order: "asc" | "desc";
  perPage: number;
};

export default function PerformancesPage(): JSX.Element {
  const { format } = useFormat();
  const isInternationalT20 = !isFranchiseFormat(format);
  const [searchParams, setSearchParams] = useSearchParams();

  const [draft, setDraft] = useState<Draft>(() => ({
    dateFrom: "",
    dateTo: "",
    team: "",
    event: "",
    playerId: null,
    matchTier: "all",
    discipline: "combined",
    order: "desc",
    perPage: 25,
  }));

  useEffect(() => {
    const pp = clampPerPage(
      parseInt(searchParams.get("per_page") || "25", 10),
    );
    setDraft({
      dateFrom: searchParams.get("date_from") ?? "",
      dateTo: searchParams.get("date_to") ?? "",
      team: searchParams.get("team") ?? "",
      event: searchParams.get("event") ?? "",
      playerId: searchParams.get("player_id") || null,
      matchTier: parseMatchTier(searchParams.get("match_tier")),
      discipline: parseDiscipline(searchParams.get("discipline")),
      order: parseOrder(searchParams.get("order")),
      perPage: pp,
    });
  }, [searchParams]);

  useEffect(() => {
    if (isInternationalT20) return;
    if (!searchParams.has("match_tier")) return;
    const p = new URLSearchParams(searchParams);
    p.delete("match_tier");
    setSearchParams(p, { replace: true });
  }, [isInternationalT20, searchParams, setSearchParams]);

  const apiParams: MatchImpactPerformancesParams = useMemo(() => {
    const page = Math.max(
      1,
      parseInt(searchParams.get("page") || "1", 10) || 1,
    );
    const perPage = clampPerPage(
      parseInt(searchParams.get("per_page") || "25", 10),
    );
    const mt = parseMatchTier(searchParams.get("match_tier"));
    return {
      date_from: searchParams.get("date_from") || undefined,
      date_to: searchParams.get("date_to") || undefined,
      team: searchParams.get("team") || undefined,
      event: searchParams.get("event") || undefined,
      player_id: searchParams.get("player_id") || undefined,
      match_tier:
        isInternationalT20 && mt !== "all" ? mt : "all",
      discipline: parseDiscipline(searchParams.get("discipline")),
      order: parseOrder(searchParams.get("order")),
      page,
      per_page: perPage,
    };
  }, [searchParams, isInternationalT20]);

  const { data, isLoading, isFetching, isError, error, refetch } =
    useMatchImpactPerformances(apiParams);

  const hasDateRangeError = Boolean(
    draft.dateFrom && draft.dateTo && draft.dateFrom > draft.dateTo,
  );

  const applyFilters = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      if (draft.dateFrom && draft.dateTo && draft.dateFrom > draft.dateTo) {
        return;
      }
      const p = new URLSearchParams();
      if (draft.dateFrom.trim()) p.set("date_from", draft.dateFrom.trim());
      if (draft.dateTo.trim()) p.set("date_to", draft.dateTo.trim());
      if (draft.team.trim()) p.set("team", draft.team.trim());
      if (draft.event.trim()) p.set("event", draft.event.trim());
      if (draft.playerId?.trim()) p.set("player_id", draft.playerId.trim());
      if (draft.discipline !== "combined")
        p.set("discipline", draft.discipline);
      if (draft.order !== "desc") p.set("order", draft.order);
      if (draft.perPage !== 25) p.set("per_page", String(draft.perPage));
      if (isInternationalT20 && draft.matchTier !== "all")
        p.set("match_tier", draft.matchTier);
      p.set("page", "1");
      setSearchParams(p);
    },
    [draft, setSearchParams, isInternationalT20],
  );

  const onPageChange = useCallback(
    (newPage: number) => {
      const p = new URLSearchParams(searchParams);
      p.set("page", String(newPage));
      setSearchParams(p);
    },
    [searchParams, setSearchParams],
  );

  const onPerPageChange = useCallback(
    (pp: number) => {
      const p = new URLSearchParams(searchParams);
      p.set("per_page", String(clampPerPage(pp)));
      p.set("page", "1");
      setSearchParams(p);
    },
    [searchParams, setSearchParams],
  );

  const sortLabelDraft =
    draft.discipline === "bat"
      ? "batting impact"
      : draft.discipline === "bowl"
        ? "bowling impact"
        : "combined impact";

  const sortLabelResult =
    apiParams.discipline === "bat"
      ? "batting impact"
      : apiParams.discipline === "bowl"
        ? "bowling impact"
        : "combined impact";

  const errMsg =
    error instanceof Error ? error.message : "Failed to load performances";

  return (
    <div className="scorecards-page app-page page-stack text-text-primary pb-8">
      <div className="page-header">
        <p className="text-xs font-medium uppercase tracking-wider text-text-muted mb-1">
          What decided the biggest matches?
        </p>
        <h1 className="page-title flex items-center gap-2">
          <Zap className="text-primary shrink-0" size={28} aria-hidden />
          Top Performances
        </h1>
        <p className="page-subtitle">
          The greatest innings, spells, and all-round performances ranked by match impact.
        </p>
      </div>

      <div className="section-card section-card-body mb-4 flex gap-2 items-start border border-surface-elevated/70 bg-surface/40 p-3 text-sm text-text-secondary">
        <Info size={16} className="shrink-0 mt-0.5 text-text-muted" />
        <span>
          <strong className="text-text-primary">Combined</strong> sorts by bat
          + bowl in that match. <strong className="text-text-primary">Batting</strong>{" "}
          / <strong className="text-text-primary">Bowling</strong> only include
          matches where that discipline met minimum balls (5 bat / 6 bowl) and
          sort by that impact alone.
        </span>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        {PERF_PRESETS.map(preset => (
          <button
            key={preset.id}
            type="button"
            onClick={() => {
              setDraft(d => ({ ...d, discipline: preset.discipline, order: preset.order }));
              const p = new URLSearchParams(searchParams);
              if (preset.discipline !== "combined") {
                p.set("discipline", preset.discipline);
              } else {
                p.delete("discipline");
              }
              if (preset.order !== "desc") {
                p.set("order", preset.order);
              } else {
                p.delete("order");
              }
              p.set("page", "1");
              setSearchParams(p);
            }}
            className="rounded-lg border border-surface-elevated/70 bg-surface-elevated/20 px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-primary/30 hover:text-primary dark:border-white/[0.06]"
          >
            {preset.label}
          </button>
        ))}
      </div>

      <form
        className="section-card section-card-body mb-6 space-y-4"
        onSubmit={applyFilters}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-muted">Date from</span>
            <input
              type="date"
              className={FIELD}
              value={draft.dateFrom}
              onChange={(e) =>
                setDraft((d) => ({ ...d, dateFrom: e.target.value }))
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-muted">Date to</span>
            <input
              type="date"
              className={FIELD}
              value={draft.dateTo}
              onChange={(e) =>
                setDraft((d) => ({ ...d, dateTo: e.target.value }))
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-muted">Team (contains)</span>
            <input
              type="text"
              className={FIELD}
              placeholder="e.g. India, Mumbai"
              value={draft.team}
              onChange={(e) =>
                setDraft((d) => ({ ...d, team: e.target.value }))
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-muted">Series / event (contains)</span>
            <input
              type="text"
              className={FIELD}
              placeholder="e.g. World Cup, IPL"
              value={draft.event}
              onChange={(e) =>
                setDraft((d) => ({ ...d, event: e.target.value }))
              }
            />
          </label>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
          {isInternationalT20 && (
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-text-muted">Fixture tier (ICC T20I)</span>
              <select
                className={FIELD}
                value={draft.matchTier}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    matchTier: parseMatchTier(e.target.value),
                  }))
                }
              >
                <option value="all">All T20I fixtures</option>
                <option value="main_only">
                  Main only (top 15 rated sides, both teams)
                </option>
                <option value="associate_fixture">
                  At least one associate / unlisted side
                </option>
              </select>
            </label>
          )}
          <div className="flex flex-col gap-1 text-sm min-w-0">
            <span className="text-text-muted">Player</span>
            <PlayerAutocomplete
              placeholder="Search to filter…"
              size="sm"
              onSelect={(p) =>
                setDraft((d) => ({ ...d, playerId: p.id }))
              }
              onClear={() => setDraft((d) => ({ ...d, playerId: null }))}
              value={null}
            />
            {draft.playerId && (
              <p className="text-xs text-text-muted truncate" title={draft.playerId}>
                Filtering:{" "}
                <Link
                  to={`/player/${encodeURIComponent(draft.playerId)}`}
                  className="text-primary hover:underline"
                >
                  {draft.playerId}
                </Link>
              </p>
            )}
          </div>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-muted">Discipline</span>
            <select
              className={FIELD}
              value={draft.discipline}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  discipline: parseDiscipline(e.target.value),
                }))
              }
            >
              <option value="combined">Combined (bat + bowl)</option>
              <option value="bat">Batting only</option>
              <option value="bowl">Bowling only</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-muted">Sort</span>
            <select
              className={FIELD}
              value={draft.order}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  order: parseOrder(e.target.value),
                }))
              }
            >
              <option value="desc">Highest {sortLabelDraft} first</option>
              <option value="asc">Lowest {sortLabelDraft} first</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-muted">Results per page</span>
            <select
              className={FIELD}
              value={String(draft.perPage)}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  perPage: clampPerPage(parseInt(e.target.value, 10)),
                }))
              }
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>

        {hasDateRangeError && (
          <p className="text-sm text-red-500">Date from must be before date to.</p>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="submit" className="btn-primary btn-sm">
            Apply filters
          </button>
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => {
              setDraft({
                dateFrom: "",
                dateTo: "",
                team: "",
                event: "",
                playerId: null,
                matchTier: "all",
                discipline: "combined",
                order: "desc",
                perPage: 25,
              });
              setSearchParams(new URLSearchParams());
            }}
          >
            Reset
          </button>
        </div>
      </form>

      {isError && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-text-primary mb-4">
          {errMsg}
          <button
            type="button"
            className="ml-3 text-primary underline"
            onClick={() => refetch()}
          >
            Retry
          </button>
        </div>
      )}

      <div className="relative">
        {isFetching && !isLoading && (
          <div className="absolute inset-0 z-10 bg-surface/50 rounded-lg pointer-events-none" />
        )}
        {isLoading ? (
          <p className="text-text-muted text-sm py-8">Loading performances…</p>
        ) : data && data.total === 0 ? (
          <p className="text-text-muted text-sm py-8">
            No performances match these filters in the current dataset.
          </p>
        ) : data ? (
          <>
            <p className="text-xs text-text-muted mb-3">
              Sorted by{" "}
              <span className="text-text-secondary font-medium">
                {sortLabelResult}
              </span>{" "}
              ({apiParams.order === "desc" ? "high → low" : "low → high"}).{" "}
              <span className="tabular-nums">{data.total}</span> performances
              total.
            </p>
            <div className="overflow-x-auto rounded-lg border border-surface-elevated/80">
              <table className="sortable-table text-sm w-full min-w-[720px]">
                <thead>
                  <tr>
                    <th className="text-left w-12">#</th>
                    <th className="text-left">Player</th>
                    <th className="text-left">Performance</th>
                    <th className="text-right">Total</th>
                    <th className="text-right">Bat</th>
                    <th className="text-right">Bowl</th>
                    <th className="text-left">Date</th>
                    <th className="text-left">Match</th>
                  </tr>
                </thead>
                <tbody>
                  {data.performances.map((row, i) => {
                    const rank = (data.page - 1) * data.per_page + i + 1;
                    const matchLabel = formatScorecardMatchLabel(row);
                    return (
                      <tr key={`${row.match_id}-${row.player_id}-${i}`}>
                        <td className="text-text-muted tabular-nums">{rank}</td>
                        <td>
                          <Link
                            to={`/player/${encodeURIComponent(row.player_id)}`}
                            className="text-primary font-medium hover:underline"
                          >
                            {row.player_name}
                          </Link>
                        </td>
                        <td className="text-text-secondary max-w-[12rem]">
                          {formatCombinedSummary(rowToCombined(row))}
                        </td>
                        <td className="text-right font-medium tabular-nums">
                          {row.total_impact.toFixed(2)}
                        </td>
                        <td className="text-right tabular-nums text-text-secondary">
                          {row.bat_impact > 0
                            ? row.bat_impact.toFixed(2)
                            : "—"}
                        </td>
                        <td className="text-right tabular-nums text-text-secondary">
                          {row.bowl_impact > 0
                            ? row.bowl_impact.toFixed(2)
                            : "—"}
                        </td>
                        <td className="text-text-secondary whitespace-nowrap">
                          {fmtDate(row.date)}
                        </td>
                        <td>
                          <Link
                            to={`/scorecards/${encodeURIComponent(row.match_id)}`}
                            className="text-primary hover:underline inline-flex items-center gap-0.5 line-clamp-2 max-w-[min(28rem,50vw)] text-left"
                          >
                            {matchLabel}
                            <ChevronRight size={12} className="shrink-0 opacity-60" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <Pagination
              className="mt-6"
              page={data.page}
              totalPages={data.total_pages}
              total={data.total}
              perPage={data.per_page}
              onPageChange={onPageChange}
              onPerPageChange={onPerPageChange}
              showSummary
              showPerPage
              perPageOptions={[10, 25, 50, 100]}
            />
          </>
        ) : null}
      </div>

      <CrossLinkBar links={CROSS_LINKS} title="Explore more" className="mt-8" />
    </div>
  );
}
