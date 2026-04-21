/**
 * Live match detail — ESPN match summary proxied through our API (in-app scorecard).
 * Route: /live/match/:eventId?league=<numeric_league_id>
 */

import { Activity, AlertCircle, ArrowLeft, Clock, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useEspnCricketMatchSummary } from "@/api/queries";
import type {
  EspnCricketMatchDetail,
  EspnMatchcardSection,
  EspnMatchDetailTeam,
  EspnRecentBall,
} from "@/api/types";

function teamShortLabel(t: EspnMatchDetailTeam): string {
  return (t.abbreviation || t.name || "").trim();
}

function resolveTeamShortLabel(
  teams: EspnMatchDetailTeam[],
  teamName: string,
): string {
  const raw = teamName.trim();
  if (!raw) return "";
  const hit = teams.find(
    (x) =>
      (x.name && x.name === raw) ||
      (x.abbreviation && x.abbreviation === raw),
  );
  return hit ? teamShortLabel(hit) : raw;
}

function MatchcardBlock({
  sec,
  teams,
}: {
  sec: EspnMatchcardSection;
  teams?: EspnMatchDetailTeam[];
}): JSX.Element {
  const teamLabel =
    teams?.length && sec.team_name
      ? resolveTeamShortLabel(teams, sec.team_name)
      : sec.team_name;
  const subtitle = [teamLabel, sec.innings_number != null ? `Inn. ${sec.innings_number}` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="mb-8 last:mb-0">
      <h4 className="text-sm font-semibold text-text-primary mb-1">{sec.headline}</h4>
      {subtitle ? <p className="text-xs text-text-muted mb-2">{subtitle}</p> : null}
      {sec.extras_summary ? (
        <p className="text-xs text-text-secondary mb-2">{sec.extras_summary}</p>
      ) : null}
      {sec.total_line ? (
        <p className="text-xs font-mono text-text-secondary mb-2">{sec.total_line}</p>
      ) : null}
      {sec.runs_summary ? (
        <p className="text-xs font-mono text-text-muted mb-2">{sec.runs_summary}</p>
      ) : null}
      {sec.rows.length === 0 ? (
        <p className="text-xs text-text-muted">No rows</p>
      ) : sec.kind === "batting" ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="text-text-muted border-b border-surface-elevated">
                <th className="py-2 pr-3 font-medium">Batter</th>
                <th className="py-2 pr-2 font-medium text-right">R</th>
                <th className="py-2 pr-2 font-medium text-right">B</th>
                <th className="py-2 pr-2 font-medium text-right">4s</th>
                <th className="py-2 pr-2 font-medium text-right">6s</th>
                <th className="py-2 font-medium">Dismissal</th>
              </tr>
            </thead>
            <tbody className="text-text-secondary">
              {sec.rows.map((r, j) => (
                <tr key={j} className="border-b border-surface-elevated/60">
                  <td className="py-2 pr-3 align-top text-text-primary">{r.player || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.runs || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.balls || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.fours || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.sixes || "—"}</td>
                  <td className="py-2 align-top">{r.dismissal || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : sec.kind === "bowling" ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="text-text-muted border-b border-surface-elevated">
                <th className="py-2 pr-3 font-medium">Bowler</th>
                <th className="py-2 pr-2 font-medium text-right">O</th>
                <th className="py-2 pr-2 font-medium text-right">M</th>
                <th className="py-2 pr-2 font-medium text-right">R</th>
                <th className="py-2 pr-2 font-medium text-right">W</th>
                <th className="py-2 pr-2 font-medium text-right">Econ</th>
                <th className="py-2 font-medium">NB/W</th>
              </tr>
            </thead>
            <tbody className="text-text-secondary">
              {sec.rows.map((r, j) => (
                <tr key={j} className="border-b border-surface-elevated/60">
                  <td className="py-2 pr-3 align-top text-text-primary">{r.player || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.overs || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.maidens || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.conceded || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.wickets || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.economy || "—"}</td>
                  <td className="py-2 align-top text-text-muted">{r.extras_note || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : sec.kind === "partnerships" ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="text-text-muted border-b border-surface-elevated">
                <th className="py-2 pr-3 font-medium">Wkt</th>
                <th className="py-2 pr-2 font-medium text-right">Runs</th>
                <th className="py-2 pr-3 font-medium text-right">Ovs</th>
                <th className="py-2 font-medium">Batters</th>
              </tr>
            </thead>
            <tbody className="text-text-secondary">
              {sec.rows.map((r, j) => (
                <tr key={j} className="border-b border-surface-elevated/60">
                  <td className="py-2 pr-3 align-top">{r.wicket_pair || "—"}</td>
                  <td className="py-2 pr-2 align-top text-right">{r.runs || "—"}</td>
                  <td className="py-2 pr-3 align-top text-right">{r.overs || "—"}</td>
                  <td className="py-2 align-top">
                    {[r.batter_1, r.batter_2].filter(Boolean).join(" / ") || "—"}
                    {(r.batter_1_runs || r.batter_2_runs) && (
                      <span className="text-text-muted ml-1">
                        (
                        {[r.batter_1_runs, r.batter_2_runs].filter(Boolean).join(", ")})
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function RecentBallsList({ balls }: { balls: EspnRecentBall[] }): JSX.Element {
  if (!balls.length) return <></>;
  return (
    <ol className="space-y-2 font-mono text-xs text-text-secondary list-none p-0 m-0 max-h-[28rem] overflow-y-auto">
      {balls.map((b, i) => (
        <li
          key={i}
          className="border-b border-surface-elevated/50 pb-2 last:border-0 flex flex-wrap gap-x-3 gap-y-1"
        >
          {b.over_display ? (
            <span className="text-text-muted shrink-0 w-12">{b.over_display}</span>
          ) : null}
          <span className="text-emerald-700 dark:text-emerald-400 font-medium shrink-0">
            {b.short_text || "—"}
          </span>
          <span className="text-text-primary min-w-0 flex-1">{b.summary || ""}</span>
          <span className="text-text-muted shrink-0">
            {[b.home_score, b.away_score].filter(Boolean).join(" · ")}
          </span>
        </li>
      ))}
    </ol>
  );
}

function liveScoresFromTeams(teams: EspnCricketMatchDetail["teams"]): string {
  return teams
    .map((t) => {
      const nm = teamShortLabel(t);
      const sc = (t.score || "").trim();
      if (nm && sc) return `${nm} ${sc}`;
      if (nm) return nm;
      return sc;
    })
    .filter(Boolean)
    .join(" · ");
}

export default function LiveMatch(): JSX.Element {
  const { eventId } = useParams<{ eventId: string }>();
  const [searchParams] = useSearchParams();
  const leagueId = (searchParams.get("league") ?? "").trim();

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useEspnCricketMatchSummary({
    leagueId,
    eventId: eventId ?? "",
    enabled: Boolean(eventId?.trim() && leagueId),
  });

  const refreshSec = data?.refresh_interval_seconds ?? 90;
  const proxyDisabled = data != null && data.enabled === false;
  const staleUpstream =
    data?.enabled &&
    data.served_from_cache &&
    Boolean(data.upstream_error?.trim());

  const detailLiveLine = useMemo(
    () => (data?.detail?.teams?.length ? liveScoresFromTeams(data.detail.teams) : ""),
    [data?.detail?.teams],
  );

  if (!eventId?.trim()) {
    return (
      <div className="app-page page-stack max-w-5xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        <p className="text-text-secondary">Missing match id.</p>
        <Link to="/live" className="text-primary hover:underline mt-3 inline-flex items-center gap-2">
          <ArrowLeft size={16} aria-hidden />
          Back to live scores
        </Link>
      </div>
    );
  }

  if (!leagueId) {
    return (
      <div className="app-page page-stack max-w-5xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        <p className="text-text-secondary max-w-lg">
          Open this page from the live list — ESPN needs the series id together with the match id.
        </p>
        <Link to="/live" className="text-primary hover:underline mt-3 inline-flex items-center gap-2">
          <ArrowLeft size={16} aria-hidden />
          Back to live scores
        </Link>
      </div>
    );
  }

  return (
    <div className="app-page page-stack max-w-5xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8">
        <Link
          to="/live"
          className="text-sm text-primary hover:underline inline-flex items-center gap-1.5 mb-4"
        >
          <ArrowLeft size={16} aria-hidden />
          Live scores
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="mb-2 flex items-center gap-3 text-h1 font-bold text-text-primary">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <Activity size={22} aria-hidden />
              </span>
              Match detail
            </h1>
            <p className="text-text-secondary text-sm max-w-xl">
              Live team scores, ESPN <strong>matchcard</strong> tables (batting, bowling,
              partnerships), and recent balls from commentary — all from the same summary feed,
              refreshed about every {refreshSec}s on this page.
            </p>
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching || proxyDisabled}
            className="btn-secondary btn-sm inline-flex items-center gap-2 shrink-0"
          >
            <RefreshCw size={16} className={isFetching ? "animate-spin" : ""} aria-hidden />
            Refresh
          </button>
        </div>
      </header>

      {proxyDisabled && data && (
        <div className="section-card section-card-body border-amber-500/30 bg-amber-500/5 text-sm text-text-secondary flex gap-3 mb-6">
          <AlertCircle className="shrink-0 text-amber-600 dark:text-amber-400" size={20} />
          <div>
            <p className="font-medium text-text-primary">Live proxy disabled</p>
            <p className="mt-1">{data.message}</p>
          </div>
        </div>
      )}

      {isLoading && !proxyDisabled && (
        <div className="section-card section-card-body py-16 text-center text-text-muted">
          Loading match…
        </div>
      )}

      {isError && (
        <div
          className="section-card border-danger/30 bg-danger/5 section-card-body flex gap-3 text-sm text-text-secondary"
          role="alert"
        >
          <AlertCircle className="shrink-0 text-danger" size={20} />
          <div>
            <p className="font-medium text-text-primary">Request failed</p>
            <p className="mt-1">
              {error instanceof Error ? error.message : "Unknown error"}
            </p>
          </div>
        </div>
      )}

      {data?.enabled && staleUpstream && (
        <div className="section-card section-card-body border-amber-500/25 bg-amber-500/5 text-sm text-text-secondary mb-6 flex gap-2">
          <AlertCircle className="shrink-0 text-amber-600 dark:text-amber-400" size={18} />
          <span>
            {data.message ?? "Upstream error — showing last successful data."}{" "}
            {data.upstream_error ? `(${data.upstream_error})` : ""}
          </span>
        </div>
      )}

      {data?.enabled && !isLoading && !isError && (
        <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-muted">
          {data.fetched_at && (
            <span className="inline-flex items-center gap-1.5">
              <Clock size={14} aria-hidden />
              Last update: {new Date(data.fetched_at).toLocaleString()}
            </span>
          )}
          {data.served_from_cache && (
            <span className="rounded-full bg-surface-elevated px-2 py-0.5">Served from cache</span>
          )}
        </div>
      )}

      {data?.enabled &&
        !isLoading &&
        !isError &&
        !data.detail &&
        !proxyDisabled && (
          <div
            className="section-card border-danger/20 bg-danger/5 section-card-body flex gap-3 text-sm text-text-secondary"
            role="alert"
          >
            <AlertCircle className="shrink-0 text-danger" size={20} />
            <div>
              <p className="font-medium text-text-primary">No match data</p>
              <p className="mt-1">
                {data.message}{" "}
                {data.upstream_error ? `— ${data.upstream_error}` : ""}
              </p>
            </div>
          </div>
        )}

      {data?.enabled && data.detail && !proxyDisabled && (
        <div className="space-y-6">
          <article className="section-card section-card-body">
            <h2 className="text-lg font-semibold text-text-primary mb-1">
              {data.detail.title || data.detail.short_title || "Match"}
            </h2>
            {detailLiveLine ? (
              <p
                className="font-mono text-base sm:text-lg font-semibold text-emerald-800 dark:text-emerald-300 mb-3"
                aria-label="Live scores"
              >
                {detailLiveLine}
              </p>
            ) : null}
            {data.detail.venue ? (
              <p className="text-sm text-text-muted mb-3">{data.detail.venue}</p>
            ) : null}
            {(data.detail.status.summary ||
              data.detail.status.short_detail ||
              data.detail.status.detail) && (
              <div className="text-sm text-text-secondary space-y-1 mb-4">
                {data.detail.status.summary ? (
                  <p className="font-medium text-text-primary">{data.detail.status.summary}</p>
                ) : null}
                <p>
                  {[data.detail.status.display_clock, data.detail.status.short_detail]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {data.detail.status.detail &&
                data.detail.status.detail !== data.detail.status.short_detail ? (
                  <p className="text-text-muted">{data.detail.status.detail}</p>
                ) : null}
              </div>
            )}

            {data.detail.teams.length > 0 ? (
              <ul className="space-y-4">
                {data.detail.teams.map((t) => (
                  <li
                    key={t.id || t.name}
                    className="border border-surface-elevated rounded-lg p-3 bg-surface-base/50"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
                      <span className="font-semibold text-text-primary">
                        {teamShortLabel(t)}
                        {t.home_away ? (
                          <span className="text-text-muted font-normal text-xs ml-2 capitalize">
                            {t.home_away}
                          </span>
                        ) : null}
                      </span>
                      {t.score ? (
                        <span className="font-mono text-sm text-emerald-700 dark:text-emerald-400">
                          {t.score}
                        </span>
                      ) : null}
                    </div>
                    {t.innings.length > 0 ? (
                      <ul className="text-xs font-mono text-text-secondary space-y-1">
                        {t.innings.map((inn, i) => (
                          <li key={`${t.id}-inn-${inn.period ?? i}`} className="flex flex-wrap gap-x-3">
                            <span>
                              {inn.period != null ? `Inn. ${inn.period}` : "Innings"}
                              {inn.is_batting ? (
                                <span className="text-emerald-600 dark:text-emerald-400 ml-1">
                                  (batting)
                                </span>
                              ) : null}
                            </span>
                            <span>{inn.score || "—"}</span>
                            {inn.description ? (
                              <span className="text-text-muted">{inn.description}</span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </article>

          {(data.detail.matchcard_sections?.length ?? 0) > 0 ? (
            <section className="section-card section-card-body" aria-label="Live scorecard">
              <h3 className="text-base font-semibold text-text-primary mb-4">Live scorecard</h3>
              {data.detail.matchcard_sections!.map((sec, idx) => (
                <MatchcardBlock
                  key={`${sec.headline}-${sec.innings_number ?? ""}-${idx}`}
                  sec={sec}
                  teams={data.detail!.teams}
                />
              ))}
            </section>
          ) : null}

          {(data.detail.recent_balls?.length ?? 0) > 0 ? (
            <section className="section-card section-card-body" aria-label="Recent deliveries">
              <h3 className="text-base font-semibold text-text-primary mb-3">Recent deliveries</h3>
              <p className="text-xs text-text-muted mb-3">
                Newest first. Updates as the match progresses.
              </p>
              <RecentBallsList balls={data.detail.recent_balls!} />
            </section>
          ) : null}

          {data.detail.fall_of_wickets.length > 0 ? (
            <section className="section-card section-card-body">
              <h3 className="text-base font-semibold text-text-primary mb-3">Fall of wickets</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="text-text-muted border-b border-surface-elevated">
                      <th className="py-2 pr-3 font-medium">Team</th>
                      <th className="py-2 pr-3 font-medium">Wkt</th>
                      <th className="py-2 pr-3 font-medium">Score</th>
                      <th className="py-2 pr-3 font-medium">Over</th>
                      <th className="py-2 font-medium">Batter</th>
                    </tr>
                  </thead>
                  <tbody className="text-text-secondary">
                    {data.detail.fall_of_wickets.map((w, i) => (
                      <tr key={`fow-${i}`} className="border-b border-surface-elevated/60">
                        <td className="py-2 pr-3 align-top">
                          {w.team_name
                            ? resolveTeamShortLabel(data.detail!.teams, w.team_name)
                            : "—"}
                        </td>
                        <td className="py-2 pr-3 align-top">{w.wicket_number ?? "—"}</td>
                        <td className="py-2 pr-3 align-top">{w.team_score_runs ?? "—"}</td>
                        <td className="py-2 pr-3 align-top">{w.over ?? "—"}</td>
                        <td className="py-2 align-top">{w.batter_out || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {data.detail.notes.length > 0 ? (
            <section className="section-card section-card-body">
              <h3 className="text-base font-semibold text-text-primary mb-3">Match info</h3>
              <ul className="text-sm text-text-secondary space-y-2 list-disc pl-5">
                {data.detail.notes.map((n, i) => (
                  <li key={`note-${i}`}>
                    {n.type ? (
                      <span className="text-text-muted text-xs uppercase mr-2">{n.type}</span>
                    ) : null}
                    {n.text}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}
