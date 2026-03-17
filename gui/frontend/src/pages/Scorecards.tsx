import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useFormat } from "@/api/FormatContext";
import { api } from "@/api/client";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import Pagination from "@/components/Pagination";
import "@/styles/scorecards.css";

/**
 * Scorecards page — search and browse match scorecards.
 *
 * - Search by date range, team, player
 * - Paginated list of matches; each links to /scorecards/:matchId for full
 *   ESPN-style scorecard view
 */

type MatchSummary = {
  match_id: string;
  date?: string | null;
  venue?: string | null;
  teams?: string[] | null;
  innings_count?: number;
};

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

  // Filters state
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [team, setTeam] = useState<string>("");
  const [playerId, setPlayerId] = useState<string | null>(null);

  // Pagination
  const [page, setPage] = useState<number>(1);
  const perPage = 50;

  // Build search params; include page via limit/offset semantics (backend supports limit only)
  const queryKey = useMemo(
    () => ["scorecards", format, dateFrom, dateTo, team, playerId, page],
    [format, dateFrom, dateTo, team, playerId, page]
  );

  const {
    data: matches,
    isLoading: listLoading,
    isError: listError,
    error: listErrorObj,
    refetch: refetchList,
  } = useQuery({
    queryKey,
    queryFn: async ({ signal }) =>
      api.searchScorecards(
        {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          team: team || undefined,
          player_id: playerId || undefined,
          limit: 500,
        },
        signal,
      ) as Promise<MatchSummary[]>,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000,
  });

  const onSearchSubmit = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      if (dateFrom && dateTo && dateFrom > dateTo) return;
      setPage(1);
      refetchList();
    },
    [refetchList, dateFrom, dateTo]
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
          </p>
        </div>

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
                  setPage(1);
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
                    setPage(1);
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
                  setPage(1);
                  refetchList();
                }}
              >
                Reset Filters
              </button>
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
