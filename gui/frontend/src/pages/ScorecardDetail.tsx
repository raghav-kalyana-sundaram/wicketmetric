/**
 * ScorecardDetail — Full-page scorecard view (ESPNcricinfo-style).
 *
 * Accessible at /scorecards/:matchId. Shows comprehensive match data:
 * - Match header (teams, date, venue, winner)
 * - Per innings: BATTING (R, B, 4s, 6s, SR, dismissal), Extras, Total,
 *   Fall of Wickets, BOWLING (O, M, R, W, ECON, WD, NB)
 */

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useFormat } from "@/api/FormatContext";
import "@/styles/scorecards.css";

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

type BattingLine = {
  batter_id: string | null;
  batter: string | null;
  runs: number | null;
  balls: number | null;
  fours?: number | null;
  sixes?: number | null;
  strike_rate?: number | null;
  dismissal_kind?: string | null;
  dismissal_over?: number | null;
  dismissal_ball_idx?: number | null;
  batting_position?: number | null;
  per_phase_runs?: Record<string, number> | null;
  deliveries?: Array<{
    over?: number | null;
    ball_idx?: number | null;
    team_score_before?: number | null;
    total_runs?: number | null;
    is_wicket?: boolean | null;
    player_out_id?: string | null;
    bowler?: string | null;
    is_wide?: boolean | null;
    is_noball?: boolean | null;
  }> | null;
};

type BowlingLine = {
  bowler_id: string | null;
  bowler: string | null;
  balls: number | null;
  overs?: string | null;
  runs_conceded?: number | null;
  wickets?: number | null;
  economy?: number | null;
  maidens?: number | null;
  deliveries?: Array<{
    is_wide?: boolean | null;
    is_noball?: boolean | null;
    total_runs?: number | null;
  }> | null;
};

type Innings = {
  innings_num: number;
  batting_team?: string | null;
  bowling_team?: string | null;
  batting: BattingLine[];
  bowling: BowlingLine[];
  innings_total?: number | null;
  innings_wickets?: number | null;
};

type Scorecard = {
  meta: {
    match_id: string;
    date?: string | null;
    venue?: string | null;
    event_name?: string | null;
    teams?: string[] | null;
    winner?: string | null;
  };
  innings: Record<string, Innings>;
};

function formatDate(s?: string | null): string {
  if (!s) return "";
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return String(s);
    return d.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return String(s);
  }
}

function overBallStr(over?: number | null, ball?: number | null): string {
  if (over == null) return "-";
  if (ball == null) return String(over);
  return `${over}.${ball}`;
}

function computeFallOfWickets(batting: BattingLine[]): Array<{ wicket: number; score: number; batter: string; batter_id: string | null; overBall: string }> {
  const falls: Array<{ wicket: number; score: number; batter: string; batter_id: string | null; overBall: string }> = [];
  let wicketNum = 0;
  for (const b of batting) {
    if (!b.dismissal_kind) continue;
    wicketNum++;
    let score = 0;
    let overBall = overBallStr(b.dismissal_over, b.dismissal_ball_idx);
    if (b.deliveries?.length) {
      const wktDelivery = b.deliveries.find(
        (d) => d.is_wicket && String(d.player_out_id) === String(b.batter_id)
      );
      if (wktDelivery) {
        const before = Number(wktDelivery.team_score_before ?? 0);
        const runs = Number(wktDelivery.total_runs ?? 0);
        score = before + runs;
      }
    }
    falls.push({
      wicket: wicketNum,
      score,
      batter: b.batter ?? b.batter_id ?? "?",
      batter_id: b.batter_id,
      overBall,
    });
  }
  return falls;
}

function computeExtras(batting: BattingLine[], inningsTotal: number): number {
  const batterRuns = batting.reduce((s, b) => s + (Number(b.runs) || 0), 0);
  return Math.max(0, (inningsTotal ?? 0) - batterRuns);
}

function computeWidesNoballs(bowling: BowlingLine[]): { wides: number; noballs: number } {
  let wides = 0;
  let noballs = 0;
  for (const bw of bowling) {
    for (const d of bw.deliveries ?? []) {
      if (d.is_wide) wides++;
      if (d.is_noball) noballs++;
    }
  }
  return { wides, noballs };
}

function computeInningsBalls(batting: BattingLine[]): number {
  let total = 0;
  for (const b of batting) {
    for (const d of b.deliveries ?? []) {
      if (d.is_wide) continue;
      total++;
    }
  }
  return total;
}

export default function ScorecardDetail(): JSX.Element {
  const { matchId } = useParams<{ matchId: string }>();
  const { format } = useFormat();

  const {
    data: scorecard,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["scorecard", format, matchId],
    enabled: !!matchId,
    queryFn: async ({ signal }) => {
      if (!matchId) throw new Error("No match ID");
      return api.getScorecard(matchId, signal) as Promise<Scorecard>;
    },
    staleTime: 10 * 60 * 1000,
  });

  if (!matchId) {
    return (
      <div className="scorecard-detail app-page page-stack text-text-primary max-w-5xl">
        <p className="text-text-secondary">Invalid match ID.</p>
        <Link to="/scorecards" className="text-primary underline mt-2 inline-block">
          ← Back to Scorecards
        </Link>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="scorecard-detail app-page page-stack text-text-primary max-w-5xl">
        <div className="section-card section-card-body space-y-3" aria-live="polite">
          <div className="skeleton h-6 w-64 rounded-md" />
          <div className="skeleton h-10 w-full rounded-md" />
          <div className="skeleton h-10 w-full rounded-md" />
          <div className="skeleton h-10 w-full rounded-md" />
        </div>
      </div>
    );
  }

  if (isError || !scorecard) {
    return (
      <div className="scorecard-detail app-page page-stack text-text-primary max-w-5xl">
        <div className="state-error">
          {error instanceof Error ? error.message : "Failed to load scorecard"}
          <div className="mt-3 flex gap-2">
            <button type="button" className="btn-primary btn-sm" onClick={() => refetch()}>
              Retry
            </button>
            <Link to="/scorecards" className="btn-secondary btn-sm">
              Back to Scorecards
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const meta = scorecard.meta ?? {};
  const teams = meta.teams ?? [];
  const inningsList = Object.entries(scorecard.innings ?? {}).sort(
    ([a], [b]) => Number(a) - Number(b)
  );

  return (
    <div className="scorecard-detail app-page page-stack text-text-primary max-w-5xl">
      {/* Breadcrumb */}
      <nav className="mb-4 text-sm text-text-muted">
        <Link to="/scorecards" className="hover:text-text-primary">
          Scorecards
        </Link>
        <span className="mx-2">/</span>
        <span className="text-text-primary">{meta.match_id ?? matchId}</span>
      </nav>

      {/* Match header */}
      <header className="page-header">
        <h1 className="page-title">
          {teams.length >= 2 ? `${teams[0]} vs ${teams[1]}` : meta.match_id ?? matchId}
        </h1>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-text-secondary">
          <span>{formatDate(meta.date)}</span>
          {meta.venue && <span>{meta.venue}</span>}
          {meta.event_name && <span>{meta.event_name}</span>}
          {meta.winner && (
            <span className="font-medium text-primary">
              {meta.winner} won
            </span>
          )}
        </div>
      </header>

      {/* Per-innings scorecard */}
      {inningsList.map(([k, inn]) => {
        const innings = inn as Innings;
        const batting = innings.batting ?? [];
        const bowling = innings.bowling ?? [];
        const total = Number(innings.innings_total ?? 0);
        const wickets = Number(innings.innings_wickets ?? 0);
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
            {/* Innings header */}
            <div className="bg-primary/10 px-4 py-2 border-b border-surface-elevated">
              <h2 className="font-semibold text-text-primary">
                {innings.batting_team ?? "Batting"} (20 ovs maximum)
              </h2>
            </div>

            <div className="p-4">
              {/* BATTING */}
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
                      const isOut = !!b.dismissal_kind;
                      const dismissalText = isOut
                        ? `${b.dismissal_kind ?? "c ? b ?"}`
                        : "not out";
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
                              {" "}{dismissalText}
                            </span>
                          </td>
                          <td className="py-2 px-2 text-right tabular-nums">
                            {b.runs ?? "-"}
                          </td>
                          <td className="py-2 px-2 text-right tabular-nums">
                            {b.balls ?? "-"}
                          </td>
                          <td className="py-2 px-2 text-right tabular-nums">
                            {b.fours ?? "-"}
                          </td>
                          <td className="py-2 px-2 text-right tabular-nums">
                            {b.sixes ?? "-"}
                          </td>
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

              {/* Fall of Wickets */}
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
                        , {f.overBall} ov)
                      </span>
                    ))}
                  </p>
                </>
              )}

              {/* BOWLING */}
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

      <Link
        to="/scorecards"
        className="inline-flex items-center gap-1 text-primary hover:underline mt-6"
      >
        ← Back to Scorecards
      </Link>
    </div>
  );
}
