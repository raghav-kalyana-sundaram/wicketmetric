import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useFormat } from "@/api/FormatContext";
import { isFranchiseFormat } from "@/api/formatConstants";
import { useMeta } from "@/api/queries";
import { api } from "@/api/client";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import Pagination from "@/components/Pagination";
import "@/styles/scorecards.css";

/**
 * Scorecards page — search and browse match scorecards.
 *
 * - Search by date range, team, player
 * - International T20 (men/women): matches grouped by Cricsheet event/series name
 * - Franchise (IPL/WPL): flat paginated table
 */

type MatchSummary = {
  match_id: string;
  date?: string | null;
  venue?: string | null;
  teams?: string[] | null;
  innings_count?: number;
  event_name?: string | null;
};

type SeriesGroup = {
  series: string;
  matches: MatchSummary[];
  latestDate: string | null;
};

const SERIES_PER_PAGE = 10;

function parseScorecardSearchRow(r: Record<string, unknown>): MatchSummary {
  const en = r.event_name;
  const eventStr =
    en != null && String(en).trim() ? String(en).trim() : null;
  return {
    match_id: String(r.match_id ?? ""),
    date: r.date != null ? String(r.date) : null,
    venue: r.venue != null ? String(r.venue) : null,
    teams: Array.isArray(r.teams) ? r.teams.map((x) => String(x)) : null,
    innings_count:
      typeof r.innings_count === "number" ? r.innings_count : undefined,
    event_name: eventStr,
  };
}

function compareDateDesc(a?: string | null, b?: string | null): number {
  const ta = a ? new Date(a).getTime() : 0;
  const tb = b ? new Date(b).getTime() : 0;
  if (Number.isNaN(ta)) return Number.isNaN(tb) ? 0 : 1;
  if (Number.isNaN(tb)) return -1;
  return tb - ta;
}

function seriesLabelForMatch(m: MatchSummary): string {
  const s = (m.event_name ?? "").trim();
  return s.length > 0 ? s : "Other / unlisted series";
}

/** Group international matches by `event_name`; sort series by most recent match. */
function groupMatchesBySeries(matches: MatchSummary[]): SeriesGroup[] {
  const map = new Map<string, MatchSummary[]>();
  for (const m of matches) {
    const key = seriesLabelForMatch(m);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(m);
  }
  const groups: SeriesGroup[] = [];
  for (const [series, ms] of map) {
    const sorted = [...ms].sort((a, b) => compareDateDesc(a.date, b.date));
    groups.push({
      series,
      matches: sorted,
      latestDate: sorted[0]?.date ?? null,
    });
  }
  groups.sort((a, b) => compareDateDesc(a.latestDate, b.latestDate));
  return groups;
}

function formatIsoDate(s?: string | null): string {
  if (!s) return "";
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return String(s);
    return d.toISOString().slice(0, 10);
  } catch {
    return String(s);
  }
}

export default function ScorecardsPage(): JSX.Element {
  const { format } = useFormat();
  const { data: apiMeta } = useMeta();
  const latest = apiMeta?.latest_scorecard;
  const isInternationalT20 = !isFranchiseFormat(format);

  // Filters state
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [team, setTeam] = useState<string>("");
  const [playerId, setPlayerId] = useState<string | null>(null);
  const [seriesQuery, setSeriesQuery] = useState<string>("");

  // Pagination (franchise: by match row; international: by series block)
  const [page, setPage] = useState<number>(1);
  const [seriesPage, setSeriesPage] = useState<number>(1);
  const perPage = 50;

  // Build search params; include page via limit/offset semantics (backend supports limit only)
  const queryKey = useMemo(
    () => ["scorecards", format, dateFrom, dateTo, team, playerId],
    [format, dateFrom, dateTo, team, playerId],
  );

  const {
    data: matches,
    isLoading: listLoading,
    isError: listError,
    error: listErrorObj,
    refetch: refetchList,
  } = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const rows = await api.searchScorecards(
        {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          team: team || undefined,
          player_id: playerId || undefined,
          limit: 500,
        },
        signal,
      );
      return rows.map((r) =>
        parseScorecardSearchRow(r as Record<string, unknown>),
      );
    },
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000,
  });

  const seriesGroupsAll = useMemo(
    () => groupMatchesBySeries(matches ?? []),
    [matches],
  );

  const seriesGroupsFiltered = useMemo(() => {
    const q = seriesQuery.trim().toLowerCase();
    if (!q) return seriesGroupsAll;
    return seriesGroupsAll.filter((g) => g.series.toLowerCase().includes(q));
  }, [seriesGroupsAll, seriesQuery]);

  const totalSeriesPages = Math.max(
    1,
    Math.ceil(seriesGroupsFiltered.length / SERIES_PER_PAGE),
  );
  const pagedSeriesGroups = useMemo(() => {
    const start = (seriesPage - 1) * SERIES_PER_PAGE;
    return seriesGroupsFiltered.slice(start, start + SERIES_PER_PAGE);
  }, [seriesGroupsFiltered, seriesPage]);

  useEffect(() => {
    setSeriesPage(1);
  }, [seriesQuery, dateFrom, dateTo, team, playerId, format]);

  const onSearchSubmit = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      if (dateFrom && dateTo && dateFrom > dateTo) return;
      setPage(1);
      setSeriesPage(1);
      refetchList();
    },
    [refetchList, dateFrom, dateTo],
  );

  const onPlayerSelect = useCallback((id: string | null) => {
    setPlayerId(id);
  }, []);

  const totalMatches = matches?.length ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalMatches / perPage));
  const pagedMatches = useMemo(() => {
    const all = matches ?? [];
    const start = (page - 1) * perPage;
    return all.slice(start, start + perPage);
  }, [matches, page]);
  const listErrorMessage =
    listErrorObj instanceof Error ? listErrorObj.message : "Failed to load matches";
  const hasDateRangeError = Boolean(dateFrom && dateTo && dateFrom > dateTo);

  return (
    <div className="scorecards-page app-page page-stack text-text-primary">
        <div className="page-header">
          <h1 className="page-title">Match Scorecards</h1>
          <p className="page-subtitle">
            Browse full scorecards by date, team, and player.
            {isInternationalT20 && (
              <>
                {" "}
                International fixtures are grouped by series or tournament (from
                match metadata).
              </>
            )}
          </p>
        </div>

        {latest?.match_id && (
          <div className="section-card section-card-body mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border border-surface-elevated/70">
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Latest match in dataset
              </p>
              <p className="text-sm text-text-primary mt-1">
                {latest.date && (
                  <span className="tabular-nums text-text-secondary mr-2">
                    {formatIsoDate(latest.date)}
                  </span>
                )}
                <span className="font-medium">
                  {latest.teams && latest.teams.length > 0
                    ? latest.teams.join(" vs ")
                    : `Match ${latest.match_id}`}
                </span>
              </p>
              {latest.event_name && (
                <p className="text-xs text-primary/90 mt-1 font-medium truncate">
                  {latest.event_name}
                </p>
              )}
              {latest.venue && (
                <p className="text-xs text-text-muted mt-1 truncate">{latest.venue}</p>
              )}
            </div>
            <Link
              to={`/scorecards/${encodeURIComponent(latest.match_id)}`}
              className="btn-secondary btn-sm shrink-0 self-start sm:self-center"
            >
              View scorecard
            </Link>
          </div>
        )}

        <form
          onSubmit={onSearchSubmit}
          className="section-card section-card-body form-grid-4 items-end"
        >
          <div>
            <label htmlFor="scorecards-date-from" className="block text-sm font-medium text-text-secondary">
              Date from
            </label>
            <input
              id="scorecards-date-from"
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="mt-1 block w-full rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary"
              aria-invalid={hasDateRangeError}
            />
          </div>

          <div>
            <label htmlFor="scorecards-date-to" className="block text-sm font-medium text-text-secondary">
              Date to
            </label>
            <input
              id="scorecards-date-to"
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="mt-1 block w-full rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary"
              aria-invalid={hasDateRangeError}
            />
          </div>

          <div>
            <label htmlFor="scorecards-team" className="block text-sm font-medium text-text-secondary">Team</label>
            <input
              id="scorecards-team"
              type="text"
              placeholder="Team name (substring)"
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              className="mt-1 block w-full rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary">Player</label>
            <PlayerAutocomplete
              placeholder="Search player..."
              onSelect={(entry) => {
                // PlayerAutocomplete returns player object with id / name - adapt if shape differs
                const id = entry?.id ?? null;
                onPlayerSelect(id);
              }}
              value={null}
            />
          </div>

          {isInternationalT20 && (
            <div className="col-span-1 md:col-span-4">
              <label
                htmlFor="scorecards-series"
                className="block text-sm font-medium text-text-secondary"
              >
                Series / tournament (filter)
              </label>
              <input
                id="scorecards-series"
                type="search"
                placeholder="e.g. World Cup, India tour of…"
                value={seriesQuery}
                onChange={(e) => setSeriesQuery(e.target.value)}
                className="mt-1 block w-full max-w-xl rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted"
              />
            </div>
          )}

          <div className="col-span-1 md:col-span-4">
            <div className="flex items-center gap-2 mt-2">
              <button
                type="submit"
                className="btn-primary btn-sm"
                disabled={listLoading || hasDateRangeError}
              >
                Search
              </button>
              <button
                type="button"
                className="btn-secondary btn-sm"
                onClick={() => {
                  setDateFrom("");
                  setDateTo("");
                  setTeam("");
                  setPlayerId(null);
                  setSeriesQuery("");
                  setPage(1);
                  setSeriesPage(1);
                  refetchList();
                }}
              >
                Reset
              </button>
              {hasDateRangeError && (
                <p className="text-sm text-danger-light" role="alert">
                  Date range invalid: Date from must be before Date to.
                </p>
              )}
              <div className="ml-auto text-sm text-text-muted">
                Showing up to 500 matches (server-side limit)
              </div>
            </div>
          </div>
        </form>

        <div className="section-card section-card-body">
          {listLoading ? (
            <div className="space-y-2" aria-live="polite">
              <div className="skeleton h-5 w-40 rounded-md" />
              <div className="skeleton h-10 w-full rounded-md" />
              <div className="skeleton h-10 w-full rounded-md" />
              <div className="skeleton h-10 w-full rounded-md" />
            </div>
          ) : listError ? (
            <div className="state-error">
              <p>{listErrorMessage}</p>
              <div className="mt-3 flex gap-2">
                <button type="button" className="btn-primary btn-sm" onClick={() => refetchList()}>
                  Retry
                </button>
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => {
                    setDateFrom("");
                    setDateTo("");
                    setTeam("");
                    setPlayerId(null);
                    setSeriesQuery("");
                    setPage(1);
                    setSeriesPage(1);
                    refetchList();
                  }}
                >
                  Clear Filters
                </button>
              </div>
            </div>
          ) : !matches || matches.length === 0 ? (
            <div className="state-empty">
              <p>No matches found for the selected filters.</p>
              <button
                type="button"
                className="btn-secondary btn-sm mt-3"
                onClick={() => {
                  setDateFrom("");
                  setDateTo("");
                  setTeam("");
                  setPlayerId(null);
                  setSeriesQuery("");
                  setPage(1);
                  setSeriesPage(1);
                  refetchList();
                }}
              >
                Reset Filters
              </button>
            </div>
          ) : isInternationalT20 ? (
            <div>
              <p className="text-sm text-text-muted mb-4">
                {matches.length} match{matches.length !== 1 ? "es" : ""} in{" "}
                {seriesGroupsFiltered.length} series
                {seriesQuery.trim() ? " (name filter applied)" : ""}
              </p>
              {pagedSeriesGroups.length === 0 ? (
                <p className="text-sm text-text-secondary">
                  No series match the filter. Try clearing the series search.
                </p>
              ) : (
                <>
                  <div className="space-y-3">
                    {pagedSeriesGroups.map((g, idx) => (
                      <details
                        key={g.series}
                        className="scorecard-series-details rounded-lg border border-surface-elevated bg-surface overflow-hidden shadow-sm"
                        open={idx === 0}
                      >
                        <summary className="cursor-pointer list-none px-4 py-3 bg-primary/5 font-semibold text-text-primary flex flex-wrap items-baseline justify-between gap-2 hover:bg-primary/10">
                          <span className="min-w-0 pr-2">{g.series}</span>
                          <span className="shrink-0 text-xs font-normal text-text-muted tabular-nums">
                            {g.matches.length} match{g.matches.length !== 1 ? "es" : ""}
                            {g.latestDate ? (
                              <span className="ml-2">
                                · latest {formatIsoDate(g.latestDate)}
                              </span>
                            ) : null}
                          </span>
                        </summary>
                        <div className="border-t border-surface-elevated overflow-x-auto">
                          <table className="w-full text-sm table-auto">
                            <thead>
                              <tr className="border-b border-surface-elevated text-left text-text-secondary">
                                <th className="px-2 py-1">Date</th>
                                <th className="px-2 py-1">Match</th>
                                <th className="px-2 py-1">Teams</th>
                                <th className="px-2 py-1">Inns</th>
                                <th className="px-2 py-1">Venue</th>
                                <th className="px-2 py-1">Action</th>
                              </tr>
                            </thead>
                            <tbody>
                              {g.matches.map((m) => (
                                <tr
                                  key={m.match_id}
                                  className="border-t border-surface-elevated/70"
                                >
                                  <td className="px-2 py-2">{formatIsoDate(m.date)}</td>
                                  <td className="px-2 py-2 tabular-nums">{m.match_id}</td>
                                  <td className="px-2 py-2">{(m.teams || []).join(" vs ")}</td>
                                  <td className="px-2 py-2">{m.innings_count ?? "-"}</td>
                                  <td className="px-2 py-2 max-w-[12rem] truncate">
                                    {m.venue ?? "—"}
                                  </td>
                                  <td className="px-2 py-2">
                                    <Link
                                      to={`/scorecards/${encodeURIComponent(m.match_id)}`}
                                      className="text-primary hover:underline font-medium"
                                    >
                                      View →
                                    </Link>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    ))}
                  </div>
                  {totalSeriesPages > 1 && (
                    <div className="mt-4 flex justify-end">
                      <Pagination
                        page={seriesPage}
                        totalPages={totalSeriesPages}
                        total={seriesGroupsFiltered.length}
                        perPage={SERIES_PER_PAGE}
                        onPageChange={(p) => setSeriesPage(p)}
                        showSummary
                      />
                    </div>
                  )}
                </>
              )}
            </div>
          ) : (
            <div>
              <table className="w-full text-sm table-auto">
                <thead>
                  <tr className="border-b border-surface-elevated text-left text-text-secondary">
                    <th className="px-2 py-1">Date</th>
                    <th className="px-2 py-1">Match</th>
                    <th className="px-2 py-1">Teams</th>
                    <th className="px-2 py-1">Innings</th>
                    <th className="px-2 py-1">Venue</th>
                    <th className="px-2 py-1">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedMatches.map((m: MatchSummary) => (
                    <tr key={m.match_id} className="border-t border-surface-elevated">
                      <td className="px-2 py-2">{formatIsoDate(m.date)}</td>
                      <td className="px-2 py-2">{m.match_id}</td>
                      <td className="px-2 py-2">{(m.teams || []).join(" vs ")}</td>
                      <td className="px-2 py-2">{m.innings_count ?? "-"}</td>
                      <td className="px-2 py-2">{m.venue ?? "-"}</td>
                      <td className="px-2 py-2">
                        <Link
                          to={`/scorecards/${encodeURIComponent(m.match_id)}`}
                          className="text-primary hover:underline font-medium"
                        >
                          View scorecard →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="mt-3 flex justify-end">
                <Pagination
                  page={page}
                  totalPages={totalPages}
                  total={totalMatches}
                  perPage={perPage}
                  onPageChange={(p) => setPage(p)}
                />
              </div>
            </div>
          )}
        </div>
      </div>
  );
}
