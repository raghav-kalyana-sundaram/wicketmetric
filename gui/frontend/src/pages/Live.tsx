/**
 * Live scores — ESPN cricket scoreboard via our backend proxy (TTL cache).
 * Standalone from Cricsheet scorecards; see Public-ESPN-API cricket docs.
 */

import { Activity, AlertCircle, Clock, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useEspnCricketScoreboard } from "@/api/queries";
import type { EspnEventSummary } from "@/api/types";

/** Backend only returns T20 IPL/WPL + international T20; presets narrow that list. */
const ESPN_PRESET_LEAGUES: { slug: string; label: string }[] = [
  { slug: "all", label: "All T20 (IPL + internationals)" },
  { slug: "ipl", label: "IPL / WPL only" },
  { slug: "icc.t20", label: "ICC T20 tournaments" },
];

const ESPN_REGIONS = ["us", "in", "gb", "au"] as const;

/** Allow YYYYMMDD or YYYYMMDD-YYYYMMDD for the dates field. */
function normalizeDatesInput(raw: string): string {
  const cleaned = raw.replace(/[^\d-]/g, "");
  const parts = cleaned.split("-");
  if (parts.length <= 1) {
    return (parts[0] ?? "").replace(/\D/g, "").slice(0, 8);
  }
  const a = (parts[0] ?? "").replace(/\D/g, "").slice(0, 8);
  const rest = parts
    .slice(1)
    .join("")
    .replace(/\D/g, "")
    .slice(0, 8);
  return rest ? `${a}-${rest}` : a;
}

function eventTitle(ev: EspnEventSummary): string {
  const s = ev.short_name?.trim();
  if (s) return s;
  const n = ev.name?.trim();
  return n || "Match";
}

export default function Live(): JSX.Element {
  const [preset, setPreset] = useState("all");
  const [leagueOverride, setLeagueOverride] = useState("");
  const [dates, setDates] = useState("");
  const [region, setRegion] = useState<string>("in");

  const league = useMemo(() => {
    const o = leagueOverride.trim();
    if (o) return o;
    return preset.trim() || "all";
  }, [leagueOverride, preset]);

  const datesNorm = useMemo(() => {
    const d = dates.trim();
    return d.length ? d : null;
  }, [dates]);

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useEspnCricketScoreboard({
    league,
    dates: datesNorm,
    region,
    lang: "en",
  });

  const events = data?.events_summary ?? [];
  const refreshSec = data?.refresh_interval_seconds ?? 90;
  const proxyDisabled = data != null && data.enabled === false;
  const staleUpstream =
    data?.enabled &&
    data.served_from_cache &&
    Boolean(data.upstream_error?.trim());

  return (
    <div className="app-page page-stack max-w-5xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="mb-2 flex items-center gap-3 text-h1 font-bold text-text-primary">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <Activity size={22} aria-hidden />
              </span>
              Live scores
            </h1>
            <p className="text-text-secondary max-w-xl text-sm">
              <strong>Live scores</strong> from ESPN&apos;s cricket header feed, proxied and cached
              (about every {refreshSec}s). Only <strong>T20</strong> is shown: IPL / WPL and
              international T20 (T20I, T20 World Cup, etc.) — no ODIs, Tests, or leagues like BBL/PSL.
              Presets narrow the list. Not official. Reference:{" "}
              <a
                href="https://github.com/pseudo-r/Public-ESPN-API/blob/main/docs/sports/cricket.md"
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:underline"
              >
                cricket endpoints
              </a>
              . This page is separate from{" "}
              <Link to="/scorecards" className="text-primary hover:underline">
                Cricsheet scorecards
              </Link>
              .
            </p>
            <p className="text-text-muted text-xs mt-3 max-w-xl border-l-2 border-surface-elevated pl-3">
              Each match has an in-app <strong>Full detail</strong> page (scorecard-shaped summary
              from ESPN: innings lines, fall of wickets, match notes).{" "}
              <Link to="/scorecards" className="text-primary hover:underline">
                Scorecards
              </Link>{" "}
              here remain historical Cricsheet data only, not linked to these live games.
            </p>
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching || proxyDisabled}
            className="btn-secondary btn-sm inline-flex items-center gap-2 shrink-0"
            title="Re-fetch from server (subject to server cache)"
          >
            <RefreshCw
              size={16}
              className={isFetching ? "animate-spin" : ""}
              aria-hidden
            />
            Refresh
          </button>
        </div>
      </header>

      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <label className="flex flex-col gap-1 text-xs text-text-muted">
          League
          <select
            className="input text-sm min-w-[10rem]"
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
            disabled={!!leagueOverride.trim()}
          >
            {ESPN_PRESET_LEAGUES.map(({ slug, label }) => (
              <option key={slug} value={slug}>
                {label} ({slug})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-muted min-w-[8rem] flex-1 max-w-xs">
          Custom filter slug
          <input
            type="text"
            className="input text-sm font-mono"
            placeholder="advanced (still T20-only)"
            value={leagueOverride}
            onChange={(e) => setLeagueOverride(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-muted">
          Region
          <select
            className="input text-sm"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          >
            {ESPN_REGIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-muted">
          Dates (optional)
          <input
            type="text"
            className="input text-sm font-mono w-36"
            placeholder="YYYYMMDD"
            value={dates}
            onChange={(e) => setDates(normalizeDatesInput(e.target.value))}
            title="Empty = ESPN default window. Or YYYYMMDD or YYYYMMDD-YYYYMMDD"
          />
        </label>
      </div>
      <p className="text-xs text-text-muted mb-6">
        Dates: leave blank for ESPN&apos;s default, or use 8 digits (YYYYMMDD) or 17 characters
        (YYYYMMDD-YYYYMMDD).
      </p>

      {proxyDisabled && data && (
        <div className="section-card section-card-body border-amber-500/30 bg-amber-500/5 text-sm text-text-secondary flex gap-3">
          <AlertCircle
            className="shrink-0 text-amber-600 dark:text-amber-400"
            size={20}
          />
          <div>
            <p className="font-medium text-text-primary">Live proxy disabled</p>
            <p className="mt-1">{data.message}</p>
          </div>
        </div>
      )}

      {isLoading && !proxyDisabled && (
        <div className="section-card section-card-body py-16 text-center text-text-muted">
          Loading scoreboard…
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
          <AlertCircle
            className="shrink-0 text-amber-600 dark:text-amber-400"
            size={18}
          />
          <span>
            {data.message ?? "Upstream error — showing last successful data."}{" "}
            {data.upstream_error ? `(${data.upstream_error})` : ""}
          </span>
        </div>
      )}

      {data?.enabled &&
        !isLoading &&
        !isError &&
        data.upstream_error &&
        !data.served_from_cache &&
        (!data.events_summary || data.events_summary.length === 0) && (
          <div
            className="section-card border-danger/20 bg-danger/5 section-card-body flex gap-3 text-sm text-text-secondary mb-6"
            role="alert"
          >
            <AlertCircle className="shrink-0 text-danger" size={20} />
            <div>
              <p className="font-medium text-text-primary">No scoreboard data</p>
              <p className="mt-1">
                {data.message}{" "}
                {data.upstream_error ? `— ${data.upstream_error}` : ""}
              </p>
            </div>
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
            <span className="rounded-full bg-surface-elevated px-2 py-0.5">
              Served from cache
            </span>
          )}
          {data.upstream_http_status != null && (
            <span>Upstream HTTP {data.upstream_http_status}</span>
          )}
        </div>
      )}

      {data?.enabled &&
        !isLoading &&
        !isError &&
        events.length === 0 &&
        !data.upstream_error && (
          <div className="section-card section-card-body py-12 text-center text-text-secondary text-sm">
            No events in this scoreboard. Try another league, region, or date — or check
            during an active window for that competition.
          </div>
        )}

      {data?.enabled && events.length > 0 && (
        <ul className="grid gap-3">
          {events.map((ev) => {
            const id =
              ev.event_id?.trim() ||
              `ev-${eventTitle(ev)}-${ev.status ?? ""}`;
            return (
              <li key={id}>
                <article className="section-card section-card-body">
                  <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
                    <h2 className="text-base font-semibold text-text-primary">
                      {eventTitle(ev)}
                    </h2>
                    {ev.status ? (
                      <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
                        {ev.status}
                      </span>
                    ) : null}
                  </div>
                  {ev.league_name ? (
                    <p className="text-xs text-text-muted mb-2">{ev.league_name}</p>
                  ) : null}
                  {ev.score_line?.trim() ? (
                    <p
                      className="font-mono text-sm sm:text-base font-semibold text-emerald-800 dark:text-emerald-300 mb-3 leading-snug"
                      aria-label="Live scores"
                    >
                      {ev.score_line}
                    </p>
                  ) : null}
                  {(ev.situation_long || ev.situation_short) ? (
                    <p className="text-sm text-text-secondary mb-2">
                      {ev.situation_long || ev.situation_short}
                    </p>
                  ) : null}
                  {ev.batting_team_name ? (
                    <p className="text-xs font-medium text-emerald-700 dark:text-emerald-400 mb-2">
                      Batting: {ev.batting_team_name}
                    </p>
                  ) : null}
                  {!ev.score_line?.trim() && ev.competitors.length > 0 ? (
                    <ul className="font-mono text-xs text-text-primary/90 space-y-1">
                      {ev.competitors.map((c, i) => (
                        <li key={`${id}-c-${i}`}>
                          {[c.name, c.score_display].filter(Boolean).join(" ")}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {ev.recent_note ? (
                    <p className="text-xs text-text-muted mt-2 leading-relaxed">
                      {ev.recent_note}
                    </p>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
                    {ev.league_id?.trim() && ev.event_id?.trim() ? (
                      <Link
                        to={`/live/match/${encodeURIComponent(ev.event_id.trim())}?league=${encodeURIComponent(ev.league_id.trim())}`}
                        className="text-xs font-semibold text-primary hover:underline"
                      >
                        Full detail (in app) →
                      </Link>
                    ) : (
                      <span className="text-xs text-text-muted">Detail unavailable (no league id)</span>
                    )}
                    {ev.espn_url ? (
                      <a
                        href={ev.espn_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-text-muted hover:text-primary hover:underline"
                      >
                        ESPN site (optional)
                      </a>
                    ) : null}
                  </div>
                </article>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-10 text-center text-xs text-text-muted">
        Analytics:{" "}
        <Link to="/" className="text-primary hover:underline">
          Home
        </Link>
        {" · "}
        <Link to="/rankings" className="text-primary hover:underline">
          Rankings
        </Link>
      </p>
    </div>
  );
}
