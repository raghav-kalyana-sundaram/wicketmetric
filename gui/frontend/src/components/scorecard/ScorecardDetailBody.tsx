/**
 * Presentational scorecard: header, win probability, scorecard / balls / impact tabs.
 * Used by live ScorecardDetail and simulated match preview.
 */

import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Circle,
  CircleDot,
  Zap,
} from "lucide-react";
import { WinProbabilityMomentumChart } from "@/components/WinProbabilityMomentumChart";
import type { Innings, Scorecard } from "@/components/scorecard/scorecardTypes";
import {
  buildInningsTimeline,
  collectPlayerNames,
  computeExtras,
  computeFallOfWickets,
  computeInningsBalls,
  computeWidesNoballs,
  formatBallNarrative,
  formatBattingDismissal,
  formatDate,
  getBallFeedPresentation,
  type BallFeedKind,
} from "@/lib/scorecardDetailHelpers";
import {
  computeMatchImpact,
  formatCombinedSummary,
  MIN_BALLS_BAT_IMPACT,
  MIN_BALLS_BOWL_IMPACT,
} from "@/lib/scorecardMatchImpact";
import "@/styles/scorecards.css";

type ViewTab = "scorecard" | "balls" | "impact";

function PlayerLink({
  id,
  name,
  className = "",
}: {
  id: string | null;
  name: string;
  className?: string;
}) {
  if (id) {
    return (
      <Link
        to={`/player/${encodeURIComponent(id)}`}
        className={`hover:underline ${className}`}
      >
        {name}
      </Link>
    );
  }
  return <span className={className}>{name}</span>;
}

type BallFeedRow = {
  key: string;
  ob: string;
  bowler: string | null | undefined;
  batter: string | null | undefined;
  narr: string;
  scoreAfter: number;
  wktsAfter: number;
  kind: BallFeedKind;
  headline: string;
  wicketDetail: string | null;
};

function ballFeedSurface(kind: BallFeedKind): string {
  switch (kind) {
    case "six":
      return "border-amber-500/35 bg-gradient-to-br from-amber-500/[0.12] via-transparent to-transparent shadow-[inset_0_0_0_1px_rgba(245,158,11,0.12)]";
    case "four":
      return "border-sky-500/35 bg-gradient-to-br from-sky-500/[0.1] via-transparent to-transparent shadow-[inset_0_0_0_1px_rgba(14,165,233,0.1)]";
    case "wicket":
      return "border-rose-500/45 bg-gradient-to-br from-rose-500/[0.12] via-transparent to-transparent shadow-[inset_0_0_0_1px_rgba(244,63,94,0.14)]";
    case "dot":
      return "border-zinc-500/40 bg-zinc-500/[0.06]";
    case "wide":
    case "noball":
      return "border-violet-500/35 bg-violet-500/[0.07]";
    default:
      return "border-surface-elevated/80 bg-surface-elevated/[0.25]";
  }
}

function ballFeedHeadlineClass(kind: BallFeedKind): string {
  switch (kind) {
    case "six":
      return "text-[1.65rem] sm:text-3xl font-black uppercase tracking-tight text-amber-300 tabular-nums";
    case "four":
      return "text-[1.5rem] sm:text-[1.85rem] font-black uppercase tracking-tight text-sky-300 tabular-nums";
    case "wicket":
      return "text-[1.55rem] sm:text-[1.9rem] font-black uppercase tracking-tight text-rose-300 tabular-nums";
    case "dot":
      return "text-xl sm:text-2xl font-black uppercase tracking-[0.18em] text-zinc-400 tabular-nums";
    case "single":
    case "multi_runs":
      return "text-lg sm:text-xl font-bold text-text-primary tabular-nums";
    case "wide":
    case "noball":
      return "text-lg font-bold text-violet-300 tabular-nums";
    default:
      return "text-base font-semibold text-text-primary";
  }
}

function BallFeedGlyph({ kind }: { kind: BallFeedKind }) {
  const common = "shrink-0 opacity-90";
  switch (kind) {
    case "six":
      return <Zap className={`${common} h-7 w-7 text-amber-400`} aria-hidden />;
    case "four":
      return (
        <span
          className={`${common} flex h-7 w-7 items-center justify-center rounded-sm border-2 border-sky-400 text-[10px] font-black leading-none text-sky-300`}
          aria-hidden
        >
          4
        </span>
      );
    case "wicket":
      return <AlertTriangle className={`${common} h-7 w-7 text-rose-400`} aria-hidden />;
    case "dot":
      return (
        <Circle className={`${common} h-6 w-6 text-zinc-500`} strokeWidth={2.5} aria-hidden />
      );
    case "wide":
    case "noball":
      return <CircleDot className={`${common} h-6 w-6 text-violet-400`} aria-hidden />;
    default:
      return null;
  }
}

function BallByBallFeed({ rows }: { rows: BallFeedRow[] }): JSX.Element {
  const glyphKinds: BallFeedKind[] = ["six", "four", "wicket", "dot", "wide", "noball"];

  return (
    <section
      className="mb-10 max-h-[70vh] overflow-y-auto space-y-3 pr-1"
      aria-label="Ball by ball feed"
    >
      {rows.length === 0 ? (
        <div className="rounded-xl border border-surface-elevated bg-surface p-6 text-sm text-text-muted">
          No ball-by-ball data for this innings (regenerate scorecards with deliveries).
        </div>
      ) : (
        rows.map((row) => (
          <article
            key={row.key}
            className={`rounded-xl border px-4 py-4 sm:px-5 sm:py-4 ${ballFeedSurface(row.kind)}`}
          >
            <div className="mb-3 flex items-center justify-between gap-3 text-xs text-text-muted">
              <span className="font-score font-semibold tabular-nums tracking-wide">
                Over {row.ob}
              </span>
              <span className="font-score font-semibold tabular-nums text-text-secondary">
                {row.scoreAfter}/{row.wktsAfter}
              </span>
            </div>
            <div className="flex items-start gap-3">
              {glyphKinds.includes(row.kind) ? <BallFeedGlyph kind={row.kind} /> : null}
              <div className="min-w-0 flex-1">
                <p className={ballFeedHeadlineClass(row.kind)}>{row.headline}</p>
                {row.kind === "wicket" && row.wicketDetail ? (
                  <p className="mt-1 text-sm font-medium text-rose-200/90">{row.wicketDetail}</p>
                ) : null}
                {row.kind === "noball" && row.wicketDetail ? (
                  <p className="mt-1 text-xs text-text-muted">{row.wicketDetail}</p>
                ) : null}
                <p className="mt-2 text-sm text-text-muted">
                  <span className="text-text-secondary">{(row.bowler ?? "—").trim()}</span>
                  <span className="mx-1.5 text-text-muted">to</span>
                  <span className="text-text-secondary">{(row.batter ?? "—").trim()}</span>
                </p>
                <p className="sr-only">{row.narr}</p>
              </div>
            </div>
          </article>
        ))
      )}
    </section>
  );
}

export interface ScorecardDetailBodyProps {
  scorecard: Scorecard;
  /** Live scorecard id for breadcrumb; null for simulation. */
  matchId: string | null;
  variant: "live" | "simulation";
}

export default function ScorecardDetailBody({
  scorecard,
  matchId,
  variant,
}: ScorecardDetailBodyProps): JSX.Element {
  const [view, setView] = useState<ViewTab>("scorecard");
  const [ballsInnKey, setBallsInnKey] = useState<string>("");

  const inningsList = useMemo((): [string, Innings][] => {
    const inn = scorecard?.innings;
    if (!inn) return [];
    return Object.entries(inn).sort(
      ([a], [b]) => Number(a) - Number(b),
    ) as [string, Innings][];
  }, [scorecard]);

  const nameById = useMemo(() => collectPlayerNames(inningsList), [inningsList]);
  const {
    batting: impactBatting,
    bowling: impactBowling,
    combined: impactCombined,
  } = useMemo(() => computeMatchImpact(inningsList), [inningsList]);

  const playerOfMatch = impactCombined[0] ?? null;

  const firstInnKey = inningsList[0]?.[0] ?? "";
  const activeBallsKey = ballsInnKey || firstInnKey;
  const ballsInningsEntry = useMemo(
    () => inningsList.find(([k]) => k === activeBallsKey),
    [inningsList, activeBallsKey],
  );

  const ballsTimelineRows = useMemo(() => {
    if (!ballsInningsEntry) return [];
    const timeline = buildInningsTimeline(ballsInningsEntry[1].bowling ?? []);
    let runningScore = 0;
    let runningWkts = 0;
    return timeline.map((ball, idx) => {
      const tr = Number(ball.total_runs ?? 0);
      runningScore += tr;
      if (ball.is_wicket) runningWkts += 1;
      const pres = getBallFeedPresentation(ball, nameById);
      return {
        key: `${ball.over ?? "?"}.${ball.ball_idx ?? "?"}-${idx}`,
        ob: `${ball.over ?? "?"}.${ball.ball_idx ?? "?"}`,
        bowler: ball.bowler,
        batter: ball.batter,
        narr: formatBallNarrative(ball, nameById),
        scoreAfter: runningScore,
        wktsAfter: runningWkts,
        kind: pres.kind,
        headline: pres.headline,
        wicketDetail: pres.wicketDetail,
      };
    });
  }, [ballsInningsEntry, nameById]);

  const meta = scorecard.meta ?? {};
  const teams = meta.teams ?? [];
  const oversLimit =
    typeof meta.overs_limit === "number" && meta.overs_limit > 0 ? meta.overs_limit : 20;

  return (
    <div className="scorecard-detail page-stack text-text-primary max-w-5xl min-w-0">
      {variant === "simulation" && (
        <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50/90 px-4 py-3 text-sm text-text-secondary dark:border-white/[0.1] dark:bg-surface">
          <strong className="text-primary">Simulation preview</strong> — Win probability, ball
          data, and impact are generated by the preview model, not live pipeline outputs.
        </div>
      )}

      <nav className="mb-4 text-sm text-text-muted">
        {variant === "live" ? (
          <>
            <Link to="/scorecards" className="hover:text-text-primary">
              Scorecards
            </Link>
            <span className="mx-2">/</span>
            <span className="text-text-primary">{meta.match_id ?? matchId}</span>
          </>
        ) : (
          <>
            <Link to="/simulation" className="hover:text-text-primary">
              Simulation Hub
            </Link>
            <span className="mx-2">/</span>
            <span className="text-text-primary">Match preview</span>
          </>
        )}
      </nav>

      <header className="page-header">
        <h1 className="page-title">
          {teams.length >= 2 ? `${teams[0]} vs ${teams[1]}` : meta.match_id ?? "Match"}
        </h1>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-text-secondary">
          <span>{formatDate(meta.date)}</span>
          {meta.venue ? (
            <Link
              to={`/venues?${new URLSearchParams({
                venue: String(meta.venue),
                vtab: "overview",
              }).toString()}`}
              className="text-primary hover:underline decoration-primary/40 underline-offset-2"
            >
              {meta.venue}
            </Link>
          ) : null}
          {meta.event_name && <span>{meta.event_name}</span>}
          {meta.winner && (
            <span className="font-medium text-primary">{meta.winner} won</span>
          )}
        </div>
      </header>

      <WinProbabilityMomentumChart
        innings={scorecard.innings}
        teams={teams}
        oversLimit={oversLimit}
        dlsApplied={Boolean(meta.dls_applied)}
        nameById={nameById}
      />

      <div
        className="scorecard-view-tabs flex flex-wrap gap-2 mb-6"
        role="tablist"
        aria-label="Scorecard view"
      >
        {(
          [
            ["scorecard", "Scorecard"],
            ["balls", "Ball-by-ball"],
            ["impact", "Match impact"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={view === id}
            className={view === id ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
            onClick={() => setView(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {view === "balls" && (
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <label htmlFor="scorecard-innings-select" className="text-sm text-text-secondary">
            Innings
          </label>
          <select
            id="scorecard-innings-select"
            className="rounded-md border border-surface-elevated bg-surface px-3 py-1.5 text-sm text-text-primary"
            value={activeBallsKey}
            onChange={(e) => setBallsInnKey(e.target.value)}
          >
            {inningsList.map(([k, inn]) => (
              <option key={k} value={k}>
                {inn.innings_num ?? k} — {inn.batting_team ?? `Innings ${k}`}
              </option>
            ))}
          </select>
          <p className="text-xs text-text-muted max-w-xl">
            Chronological feed — boundaries, wickets, and dots are emphasised; score is team total after
            each ball.
          </p>
        </div>
      )}

      {view === "impact" && (
        <div className="mb-8 rounded-lg border border-surface-elevated bg-surface/80 p-4 text-sm text-text-secondary space-y-2">
          <p>
            <strong className="text-text-primary">Match impact</strong> uses parallel scales so
            you can compare batters and bowlers on fair footing. Batting:{" "}
            <span className="tabular-nums text-text-primary">runs² ÷ balls</span> (a quick 70 off
            30 beats 90 off 60). Bowling with wickets: a weighted{" "}
            <span className="tabular-nums text-text-primary">wickets² × balls ÷ runs</span> core
            (same idea as batting — productivity squared per run/ball), tuned so a spell like{" "}
            <span className="tabular-nums">4/15</span> rates alongside or above a very fast{" "}
            <span className="tabular-nums">50</span>, plus an extra for{" "}
            <span className="tabular-nums text-text-primary">runs saved</span> vs the leave-one-out
            match rate. Wicketless spells use runs saved only. Minimum{" "}
            {MIN_BALLS_BAT_IMPACT} balls faced or {MIN_BALLS_BOWL_IMPACT} balls bowled to qualify.{" "}
            <strong className="text-text-primary">Player of the match</strong> is whoever has the
            highest <span className="tabular-nums text-text-primary">bat + bowl</span> impact (only
            disciplines you qualify for count).
          </p>
        </div>
      )}

      {view === "impact" && (
        <div className="space-y-10 mb-10">
          {playerOfMatch && (
            <section
              className="rounded-xl border border-slate-200 bg-surface-light px-5 py-6 shadow-sm dark:rounded-2xl dark:border-white/[0.1] dark:bg-surface dark:shadow-[0_20px_40px_-28px_rgba(0,0,0,0.65)]"
              aria-label="Player of the match"
            >
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Player of the match
              </p>
              <h2 className="mb-2 text-2xl font-bold text-text-primary">
                <PlayerLink
                  id={playerOfMatch.playerId}
                  name={playerOfMatch.name}
                  className="text-primary hover:underline"
                />
              </h2>
              <p className="mb-1 text-sm text-text-secondary">
                <span className="font-medium tabular-nums text-text-primary">
                  {playerOfMatch.totalImpact.toFixed(2)}
                </span>{" "}
                combined impact
                {playerOfMatch.batImpact > 0 && (
                  <>
                    {" "}
                    · bat{" "}
                    <span className="tabular-nums">{playerOfMatch.batImpact.toFixed(2)}</span>
                  </>
                )}
                {playerOfMatch.bowlImpact > 0 && (
                  <>
                    {" "}
                    · bowl{" "}
                    <span className="tabular-nums">{playerOfMatch.bowlImpact.toFixed(2)}</span>
                  </>
                )}
              </p>
              <p className="text-sm text-text-muted">{formatCombinedSummary(playerOfMatch)}</p>
            </section>
          )}

          <section className="rounded-lg border border-surface-elevated bg-surface overflow-hidden shadow-sm">
            <div className="border-b border-slate-200 bg-slate-100/80 px-4 py-2 dark:border-white/[0.07] dark:bg-[#080808]">
              <h2 className="text-sm font-semibold tracking-wide text-text-primary">
                Combined impact
              </h2>
            </div>
            <div className="p-4 overflow-x-auto">
              {impactCombined.length === 0 ? (
                <p className="text-sm text-text-muted">No qualifying performances.</p>
              ) : (
                <table className="scorecard-table w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-elevated text-left text-text-muted">
                      <th className="py-2 pr-4 font-medium">#</th>
                      <th className="py-2 pr-4 font-medium">Player</th>
                      <th className="py-2 px-2 text-right">Bat</th>
                      <th className="py-2 px-2 text-right">Bowl</th>
                      <th className="py-2 px-2 text-right">Total</th>
                      <th className="py-2 pl-4 font-medium">Match figures</th>
                    </tr>
                  </thead>
                  <tbody>
                    {impactCombined.map((row, i) => (
                      <tr
                        key={row.playerId}
                        className={
                          i === 0
                            ? "border-b border-surface-elevated/50 bg-slate-100/60 dark:border-white/[0.06] dark:bg-[#080808]/80"
                            : "border-b border-surface-elevated/50"
                        }
                      >
                        <td className="py-2 pr-4 tabular-nums text-text-muted">{i + 1}</td>
                        <td className="py-2 pr-4">
                          <PlayerLink
                            id={row.playerId}
                            name={row.name}
                            className="font-medium text-primary"
                          />
                          {i === 0 && (
                            <span className="ml-2 text-xs font-medium text-primary">POTM</span>
                          )}
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums">
                          {row.batImpact > 0 ? row.batImpact.toFixed(2) : "—"}
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums">
                          {row.bowlImpact > 0 ? row.bowlImpact.toFixed(2) : "—"}
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums font-medium">
                          {row.totalImpact.toFixed(2)}
                        </td>
                        <td className="py-2 pl-4 text-text-secondary">
                          {formatCombinedSummary(row)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-surface-elevated bg-surface overflow-hidden shadow-sm">
            <div className="border-b border-slate-200 bg-slate-100/80 px-4 py-2 dark:border-white/[0.07] dark:bg-[#080808]">
              <h2 className="font-semibold text-text-primary">Batting impact</h2>
            </div>
            <div className="p-4 overflow-x-auto">
              {impactBatting.length === 0 ? (
                <p className="text-sm text-text-muted">No qualifying innings.</p>
              ) : (
                <table className="scorecard-table w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-elevated text-left text-text-muted">
                      <th className="py-2 pr-4 font-medium">#</th>
                      <th className="py-2 pr-4 font-medium">Player</th>
                      <th className="py-2 px-2 text-right">Runs</th>
                      <th className="py-2 px-2 text-right">Balls</th>
                      <th className="py-2 px-2 text-right">SR</th>
                      <th className="py-2 px-2 text-right">Impact</th>
                    </tr>
                  </thead>
                  <tbody>
                    {impactBatting.map((row, i) => (
                      <tr key={row.playerId} className="border-b border-surface-elevated/50">
                        <td className="py-2 pr-4 tabular-nums text-text-muted">{i + 1}</td>
                        <td className="py-2 pr-4">
                          <PlayerLink
                            id={row.playerId}
                            name={row.name}
                            className="font-medium text-primary"
                          />
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums">{row.runs}</td>
                        <td className="py-2 px-2 text-right tabular-nums">{row.balls}</td>
                        <td className="py-2 px-2 text-right tabular-nums">
                          {row.strikeRate != null ? row.strikeRate.toFixed(2) : "—"}
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums font-medium">
                          {row.impact.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-surface-elevated bg-surface overflow-hidden shadow-sm">
            <div className="border-b border-slate-200 bg-slate-100/80 px-4 py-2 dark:border-white/[0.07] dark:bg-[#080808]">
              <h2 className="font-semibold text-text-primary">Bowling impact</h2>
            </div>
            <div className="p-4 overflow-x-auto">
              {impactBowling.length === 0 ? (
                <p className="text-sm text-text-muted">No qualifying spells.</p>
              ) : (
                <table className="scorecard-table w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-elevated text-left text-text-muted">
                      <th className="py-2 pr-4 font-medium">#</th>
                      <th className="py-2 pr-4 font-medium">Player</th>
                      <th className="py-2 px-2 text-right">W</th>
                      <th className="py-2 px-2 text-right">R</th>
                      <th className="py-2 px-2 text-right">Balls</th>
                      <th className="py-2 px-2 text-right">Econ</th>
                      <th className="py-2 px-2 text-right">Impact</th>
                    </tr>
                  </thead>
                  <tbody>
                    {impactBowling.map((row, i) => (
                      <tr key={row.playerId} className="border-b border-surface-elevated/50">
                        <td className="py-2 pr-4 tabular-nums text-text-muted">{i + 1}</td>
                        <td className="py-2 pr-4">
                          <PlayerLink
                            id={row.playerId}
                            name={row.name}
                            className="font-medium text-primary"
                          />
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums">{row.wickets}</td>
                        <td className="py-2 px-2 text-right tabular-nums">{row.runsConceded}</td>
                        <td className="py-2 px-2 text-right tabular-nums">{row.balls}</td>
                        <td className="py-2 px-2 text-right tabular-nums">
                          {row.economy != null ? row.economy.toFixed(2) : "—"}
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums font-medium">
                          {row.impact.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </div>
      )}

      {view === "balls" && (
        <BallByBallFeed rows={ballsTimelineRows} />
      )}

      {view === "scorecard" &&
        inningsList.map(([k, inn]) => {
          const batting = inn.batting ?? [];
          const bowling = inn.bowling ?? [];
          const total = Number(inn.innings_total ?? 0);
          const wickets = Number(inn.innings_wickets ?? 0);
          const extras = computeExtras(batting, total);
          const falls = computeFallOfWickets(batting);
          const totalBalls = computeInningsBalls(batting);
          const oversStr = totalBalls > 0 ? (totalBalls / 6).toFixed(1) : "-";
          const rr = totalBalls > 0 ? ((total / totalBalls) * 6).toFixed(2) : "-";

          return (
            <section
              key={k}
              className="mb-10 rounded-lg border border-surface-elevated bg-surface overflow-hidden shadow-sm"
            >
              <div className="border-b border-slate-200 bg-slate-100/80 px-4 py-2 dark:border-white/[0.07] dark:bg-[#080808]">
                <h2 className="font-semibold text-text-primary">
                  {inn.batting_team ?? "Batting"} ({oversLimit} ovs maximum)
                </h2>
              </div>

              <div className="p-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-text-muted mb-2 mt-4 first:mt-0">
                  Batting
                </h3>
                <div className="overflow-x-auto">
                  <table className="scorecard-table w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-elevated text-left text-text-muted">
                        <th className="py-2 pr-4 font-medium">Batter</th>
                        <th className="py-2 px-2 text-right w-12">R</th>
                        <th className="py-2 px-2 text-right w-12">B</th>
                        <th className="py-2 px-2 text-right w-10">4s</th>
                        <th className="py-2 px-2 text-right w-10">6s</th>
                        <th className="py-2 px-2 text-right w-14">SR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batting.map((b) => {
                        const dismissalText = formatBattingDismissal(b);
                        return (
                          <tr
                            key={String(b.batter_id)}
                            className="border-b border-surface-elevated/50"
                          >
                            <td className="py-2 pr-4">
                              <PlayerLink
                                id={b.batter_id}
                                name={b.batter ?? b.batter_id ?? "-"}
                                className="font-medium text-primary"
                              />
                              <span className="text-text-muted text-xs ml-1.5">
                                {" "}
                                {dismissalText}
                              </span>
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">{b.runs ?? "-"}</td>
                            <td className="py-2 px-2 text-right tabular-nums">{b.balls ?? "-"}</td>
                            <td className="py-2 px-2 text-right tabular-nums">{b.fours ?? "-"}</td>
                            <td className="py-2 px-2 text-right tabular-nums">{b.sixes ?? "-"}</td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {b.strike_rate != null ? b.strike_rate.toFixed(2) : "-"}
                            </td>
                          </tr>
                        );
                      })}
                      {extras > 0 && (
                        <tr className="border-b border-surface-elevated/50 text-text-secondary">
                          <td className="py-2 pr-4">Extras</td>
                          <td className="py-2 px-2 text-right tabular-nums" colSpan={5}>
                            {extras}
                          </td>
                        </tr>
                      )}
                      <tr className="font-semibold">
                        <td className="py-2 pr-4">Total</td>
                        <td className="py-2 px-2 text-right tabular-nums" colSpan={5}>
                          {total}/{wickets} ({oversStr} Ov, RR: {rr})
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {falls.length > 0 && (
                  <>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-text-muted mb-2 mt-6">
                      Fall of Wickets
                    </h3>
                    <p className="text-sm text-text-secondary">
                      {falls.map((f, i) => (
                        <span key={f.wicket}>
                          {i > 0 && ", "}
                          {f.wicket}-{f.score} (
                          <PlayerLink
                            id={f.batter_id}
                            name={f.batter}
                            className="text-primary"
                          />
                          , {f.dismissalText}, {f.overBall} ov)
                        </span>
                      ))}
                    </p>
                  </>
                )}

                <h3 className="text-xs font-bold uppercase tracking-wider text-text-muted mb-2 mt-6">
                  Bowling
                </h3>
                <div className="overflow-x-auto">
                  <table className="scorecard-table w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-elevated text-left text-text-muted">
                        <th className="py-2 pr-4 font-medium">Bowler</th>
                        <th className="py-2 px-2 text-right w-12">O</th>
                        <th className="py-2 px-2 text-right w-10">M</th>
                        <th className="py-2 px-2 text-right w-12">R</th>
                        <th className="py-2 px-2 text-right w-10">W</th>
                        <th className="py-2 px-2 text-right w-14">ECON</th>
                        <th className="py-2 px-2 text-right w-10">WD</th>
                        <th className="py-2 px-2 text-right w-10">NB</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bowling.map((bw) => {
                        const { wides, noballs } = computeWidesNoballs([bw]);
                        return (
                          <tr
                            key={String(bw.bowler_id)}
                            className="border-b border-surface-elevated/50"
                          >
                            <td className="py-2 pr-4">
                              <PlayerLink
                                id={bw.bowler_id}
                                name={bw.bowler ?? bw.bowler_id ?? "-"}
                                className="font-medium text-primary"
                              />
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {bw.overs ?? "-"}
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {bw.maidens ?? 0}
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {bw.runs_conceded ?? "-"}
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {bw.wickets ?? "-"}
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {bw.economy != null ? bw.economy.toFixed(2) : "-"}
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {wides || "-"}
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">
                              {noballs || "-"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          );
        })}

      {variant === "live" ? (
        <Link
          to="/scorecards"
          className="inline-flex items-center gap-1 text-primary hover:underline mt-6"
        >
          ← Back to Scorecards
        </Link>
      ) : (
        <Link
          to="/simulation"
          className="inline-flex items-center gap-1 text-primary hover:underline mt-6"
        >
          ← Back to Simulation Hub
        </Link>
      )}
    </div>
  );
}
