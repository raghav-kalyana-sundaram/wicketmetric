/**
 * ScorecardDetail — Full-page scorecard view (ESPNcricinfo-style).
 *
 * Accessible at /scorecards/:matchId. Shows comprehensive match data:
 * - Match header (teams, date, venue, winner)
 * - Scorecard: per innings BATTING / BOWLING / fall of wickets
 * - Ball-by-ball: chronological play-by-play per innings
 * - Match impact: batting / bowling metrics, combined table, Player of the match (bat + bowl)
 */

import { Link, useParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useFormat } from "@/api/FormatContext";
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
  dismissal_bowler?: string | null;
  dismissal_bowler_id?: string | null;
  dismissal_fielders?: string[] | null;
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
    wicket_fielders?: string[] | null;
    is_wide?: boolean | null;
    is_noball?: boolean | null;
  }> | null;
};

type BowlingDelivery = {
  over?: number | null;
  ball_idx?: number | null;
  batter?: string | null;
  batter_id?: string | null;
  batter_runs?: number | null;
  total_runs?: number | null;
  is_wide?: boolean | null;
  is_noball?: boolean | null;
  is_legal?: boolean | null;
  is_wicket?: boolean | null;
  wicket_kind?: string | null;
  player_out_id?: string | null;
  phase?: string | null;
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
  deliveries?: BowlingDelivery[] | null;
};

/** One row in the chronological ball-by-ball feed (from bowling delivery lists). */
type TimelineBall = BowlingDelivery & {
  bowler_id: string | null;
  bowler: string | null;
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

function findWicketDelivery(b: BattingLine) {
  return b.deliveries?.find(
    (d) => d.is_wicket && String(d.player_out_id) === String(b.batter_id),
  );
}

function fieldersForDismissal(b: BattingLine): string[] {
  const fromLine = b.dismissal_fielders?.filter(Boolean) ?? [];
  if (fromLine.length) return fromLine;
  const d = findWicketDelivery(b);
  const fromBall = d?.wicket_fielders?.filter(Boolean) ?? [];
  return fromBall;
}

/** Standard scorecard dismissal text (e.g. c Fielder b Bowler). */
function formatBattingDismissal(b: BattingLine): string {
  if (!b.dismissal_kind) return "not out";
  const d = findWicketDelivery(b);
  const bowlerRaw = (b.dismissal_bowler ?? d?.bowler ?? "").trim();
  const bowler = bowlerRaw || null;
  const fielders = fieldersForDismissal(b);
  const f1 = fielders[0];
  const fJoin = fielders.join("/");

  const k = (b.dismissal_kind || "").toLowerCase().replace(/_/g, " ");

  if (k === "caught" && bowler) {
    if (f1) return `c ${f1} b ${bowler}`;
    return `caught b ${bowler}`;
  }
  if (k === "caught and bowled" && bowler) return `c & b ${bowler}`;
  if (k === "bowled" && bowler) return `b ${bowler}`;
  if (k === "lbw" && bowler) return `lbw b ${bowler}`;
  if (k === "stumped" && bowler) {
    if (f1) return `st ${f1} b ${bowler}`;
    return `st b ${bowler}`;
  }
  if (k === "hit wicket" && bowler) return `hit wicket b ${bowler}`;
  if (k === "hit wicket") return "hit wicket";
  if (k === "run out" && fJoin) return `run out (${fJoin})`;
  if (k === "run out") return "run out";
  if (k === "obstructing the field") return "obstructing the field";
  if (k === "retired hurt") return "retired hurt";
  if (k === "retired out") return "retired out";
  if (bowler) return `${k} b ${bowler}`;
  return b.dismissal_kind;
}

function computeFallOfWickets(
  batting: BattingLine[],
): Array<{
  wicket: number;
  score: number;
  batter: string;
  batter_id: string | null;
  overBall: string;
  dismissalText: string;
}> {
  const falls: Array<{
    wicket: number;
    score: number;
    batter: string;
    batter_id: string | null;
    overBall: string;
    dismissalText: string;
  }> = [];
  let wicketNum = 0;
  for (const b of batting) {
    if (!b.dismissal_kind) continue;
    wicketNum++;
    let score = 0;
    let overBall = overBallStr(b.dismissal_over, b.dismissal_ball_idx);
    if (b.deliveries?.length) {
      const wktDelivery = b.deliveries.find(
        (d) => d.is_wicket && String(d.player_out_id) === String(b.batter_id),
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
      dismissalText: formatBattingDismissal(b),
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

function sortKeyOverBall(over: number | null | undefined, ball: number | null | undefined): number {
  const o = over ?? 0;
  const bi = ball ?? 0;
  return o * 1000 + bi;
}

/** Full innings timeline: every delivery appears once on its bowler's row. */
function buildInningsTimeline(bowling: BowlingLine[]): TimelineBall[] {
  const rows: TimelineBall[] = [];
  for (const bw of bowling) {
    for (const d of bw.deliveries ?? []) {
      rows.push({
        ...d,
        bowler_id: bw.bowler_id,
        bowler: bw.bowler,
      });
    }
  }
  rows.sort((a, b) => sortKeyOverBall(a.over, a.ball_idx) - sortKeyOverBall(b.over, b.ball_idx));
  return rows;
}

function formatWicketKind(kind?: string | null): string {
  if (!kind) return "W";
  return String(kind).replace(/_/g, " ");
}

function formatBallNarrative(
  b: TimelineBall,
  nameById: Map<string, string>,
): string {
  const br = Number(b.batter_runs ?? 0);
  const tr = Number(b.total_runs ?? 0);

  if (b.is_wide) {
    const extra = tr > 1 ? ` (${tr} runs)` : "";
    return `Wide${extra}`;
  }
  if (b.is_noball) {
    const bit = br > 0 ? `, ${br} off the bat` : "";
    return `No ball${bit} (${tr} total)`;
  }
  if (b.is_wicket) {
    const outId = b.player_out_id != null ? String(b.player_out_id) : "";
    const outName = outId ? nameById.get(outId) ?? outId : "batter";
    return `WICKET — ${outName} (${formatWicketKind(b.wicket_kind)})`;
  }
  if (br === 4) return "FOUR";
  if (br === 6) return "SIX";
  if (tr === 0) return "No run";
  if (tr === 1) return "1 run";
  return `${tr} runs`;
}

function collectPlayerNames(inningsList: [string, Innings][]): Map<string, string> {
  const m = new Map<string, string>();
  for (const [, inn] of inningsList) {
    for (const b of inn.batting ?? []) {
      if (b.batter_id && b.batter) m.set(String(b.batter_id), String(b.batter));
    }
    for (const bw of inn.bowling ?? []) {
      if (bw.bowler_id && bw.bowler) m.set(String(bw.bowler_id), String(bw.bowler));
    }
    for (const bw of inn.bowling ?? []) {
      for (const d of bw.deliveries ?? []) {
        if (d.batter_id && d.batter) m.set(String(d.batter_id), String(d.batter));
      }
    }
  }
  return m;
}

const MIN_BALLS_BAT_IMPACT = 5;
const MIN_BALLS_BOWL_IMPACT = 6;

type BowlAggLine = { wickets: number; runsConceded: number; balls: number };

/**
 * Bowling impact on the same scale as batting (runs² ÷ balls).
 *
 * - Spell core (wickets > 0): K × wickets² × balls ÷ max(runs, 1) — structurally similar to
 *   batting’s runs² ÷ balls (wickets/runs vs runs/balls). K is chosen so e.g. 4/15 in a typical
 *   four-over spell lands a little above a strong ~52(21) innings (~129).
 * - Match context: leave-one-out runs saved is added so cheap spells in run-heavy games gain extra.
 * - Wicketless: runs-saved only (no w² term), so expensive spells without wickets stay down.
 */
function computeBowlingImpactRelative(
  line: BowlAggLine,
  matchTotals: { totalRuns: number; totalBalls: number },
): number {
  const { wickets, runsConceded, balls } = line;
  const safeRuns = Math.max(runsConceded, 1);

  const poolRuns = matchTotals.totalRuns - runsConceded;
  const poolBalls = matchTotals.totalBalls - balls;
  const matchRpb =
    poolBalls > 0
      ? poolRuns / poolBalls
      : matchTotals.totalBalls > 0
        ? matchTotals.totalRuns / matchTotals.totalBalls
        : 0;

  const expectedRuns = matchRpb * balls;
  const runsSaved = expectedRuns - runsConceded;

  /** Calibrated vs batting runs²/balls: 4/15 should edge ~52(21) (~128.8) even ~20 legal balls */
  const BOWL_SPELL_K = 6.05;
  const RUNS_SAVED_K = 2.35;

  if (wickets > 0) {
    const spellCore = (BOWL_SPELL_K * wickets * wickets * balls) / safeRuns;
    return spellCore + RUNS_SAVED_K * runsSaved;
  }

  return RUNS_SAVED_K * runsSaved;
}

type BattingImpactRow = {
  playerId: string;
  name: string;
  runs: number;
  balls: number;
  strikeRate: number | null;
  impact: number;
};

type BowlingImpactRow = {
  playerId: string;
  name: string;
  wickets: number;
  runsConceded: number;
  balls: number;
  economy: number | null;
  impact: number;
};

type CombinedImpactRow = {
  playerId: string;
  name: string;
  batImpact: number;
  bowlImpact: number;
  totalImpact: number;
  batRuns?: number;
  batBalls?: number;
  bowlWkts?: number;
  bowlRuns?: number;
  bowlBalls?: number;
};

function mergeBattingBowlingImpact(
  batting: BattingImpactRow[],
  bowling: BowlingImpactRow[],
): CombinedImpactRow[] {
  const m = new Map<string, CombinedImpactRow>();

  for (const b of batting) {
    m.set(b.playerId, {
      playerId: b.playerId,
      name: b.name,
      batImpact: b.impact,
      bowlImpact: 0,
      totalImpact: b.impact,
      batRuns: b.runs,
      batBalls: b.balls,
    });
  }

  for (const bo of bowling) {
    const x = m.get(bo.playerId);
    if (x) {
      x.bowlImpact = bo.impact;
      x.totalImpact =
        Math.round((x.batImpact + bo.impact) * 100) / 100;
      x.bowlWkts = bo.wickets;
      x.bowlRuns = bo.runsConceded;
      x.bowlBalls = bo.balls;
    } else {
      m.set(bo.playerId, {
        playerId: bo.playerId,
        name: bo.name,
        batImpact: 0,
        bowlImpact: bo.impact,
        totalImpact: bo.impact,
        bowlWkts: bo.wickets,
        bowlRuns: bo.runsConceded,
        bowlBalls: bo.balls,
      });
    }
  }

  const rows = [...m.values()].sort((a, b) => {
    if (b.totalImpact !== a.totalImpact) return b.totalImpact - a.totalImpact;
    return a.name.localeCompare(b.name);
  });
  return rows;
}

function formatCombinedSummary(r: CombinedImpactRow): string {
  const parts: string[] = [];
  if (r.batRuns != null && r.batBalls != null) {
    parts.push(`${r.batRuns} (${r.batBalls}b)`);
  }
  if (
    r.bowlWkts != null &&
    r.bowlRuns != null &&
    r.bowlBalls != null
  ) {
    parts.push(`${r.bowlWkts}/${r.bowlRuns} (${r.bowlBalls}b)`);
  }
  return parts.join(" · ") || "—";
}

function computeMatchImpact(inningsList: [string, Innings][]): {
  batting: BattingImpactRow[];
  bowling: BowlingImpactRow[];
  combined: CombinedImpactRow[];
} {
  const batAgg = new Map<string, { name: string; runs: number; balls: number }>();
  const bowlAgg = new Map<
    string,
    { name: string; wickets: number; runsConceded: number; balls: number }
  >();

  for (const [, inn] of inningsList) {
    for (const b of inn.batting ?? []) {
      const id = b.batter_id != null ? String(b.batter_id) : null;
      if (!id) continue;
      const name = b.batter ?? id;
      const runs = Number(b.runs ?? 0);
      const balls = Number(b.balls ?? 0);
      const cur = batAgg.get(id) ?? { name, runs: 0, balls: 0 };
      cur.name = name;
      cur.runs += runs;
      cur.balls += balls;
      batAgg.set(id, cur);
    }
    for (const bw of inn.bowling ?? []) {
      const id = bw.bowler_id != null ? String(bw.bowler_id) : null;
      if (!id) continue;
      const name = bw.bowler ?? id;
      const w = Number(bw.wickets ?? 0);
      const r = Number(bw.runs_conceded ?? 0);
      const balls = Number(bw.balls ?? 0);
      const cur = bowlAgg.get(id) ?? { name, wickets: 0, runsConceded: 0, balls: 0 };
      cur.name = name;
      cur.wickets += w;
      cur.runsConceded += r;
      cur.balls += balls;
      bowlAgg.set(id, cur);
    }
  }

  const batting: BattingImpactRow[] = [];
  for (const [playerId, v] of batAgg) {
    if (v.balls < MIN_BALLS_BAT_IMPACT) continue;
    const sr = v.balls > 0 ? (v.runs / v.balls) * 100 : null;
    const impact = (v.runs * v.runs) / Math.max(v.balls, 1);
    batting.push({
      playerId,
      name: v.name,
      runs: v.runs,
      balls: v.balls,
      strikeRate: sr != null ? Math.round(sr * 100) / 100 : null,
      impact: Math.round(impact * 100) / 100,
    });
  }
  batting.sort((a, b) => b.impact - a.impact);

  let totalBowlRuns = 0;
  let totalBowlBalls = 0;
  for (const v of bowlAgg.values()) {
    totalBowlRuns += v.runsConceded;
    totalBowlBalls += v.balls;
  }
  const matchBowlTotals = { totalRuns: totalBowlRuns, totalBalls: totalBowlBalls };

  const bowling: BowlingImpactRow[] = [];
  for (const [playerId, v] of bowlAgg) {
    if (v.balls < MIN_BALLS_BOWL_IMPACT) continue;
    const econ =
      v.balls > 0 ? Math.round((v.runsConceded * 600) / v.balls) / 100 : null;
    const impact = computeBowlingImpactRelative(v, matchBowlTotals);
    bowling.push({
      playerId,
      name: v.name,
      wickets: v.wickets,
      runsConceded: v.runsConceded,
      balls: v.balls,
      economy: econ,
      impact: Math.round(impact * 100) / 100,
    });
  }
  bowling.sort((a, b) => b.impact - a.impact);

  const combined = mergeBattingBowlingImpact(batting, bowling);

  return { batting, bowling, combined };
}

export default function ScorecardDetail(): JSX.Element {
  const { matchId } = useParams<{ matchId: string }>();
  const { format } = useFormat();
  const [view, setView] = useState<ViewTab>("scorecard");
  const [ballsInnKey, setBallsInnKey] = useState<string>("");

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
      return {
        key: `${ball.over ?? "?"}.${ball.ball_idx ?? "?"}-${idx}`,
        ob: `${ball.over ?? "?"}.${ball.ball_idx ?? "?"}`,
        bowler: ball.bowler,
        batter: ball.batter,
        narr: formatBallNarrative(ball, nameById),
        scoreAfter: runningScore,
        wktsAfter: runningWkts,
      };
    });
  }, [ballsInningsEntry, nameById]);

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

      {/* View mode */}
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
            className={
              view === id
                ? "btn-primary btn-sm"
                : "btn-secondary btn-sm"
            }
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
            Every delivery in order; score shows team total after the ball.
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
            {MIN_BALLS_BAT_IMPACT} balls faced or {MIN_BALLS_BOWL_IMPACT} balls bowled to qualify.
            {" "}
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
              className="rounded-xl border-2 border-primary/35 bg-gradient-to-br from-primary/10 via-surface to-surface px-5 py-6 shadow-sm"
              aria-label="Player of the match"
            >
              <p className="text-xs font-semibold uppercase tracking-wider text-primary mb-1">
                Player of the match
              </p>
              <h2 className="text-2xl font-bold text-text-primary mb-2">
                <PlayerLink
                  id={playerOfMatch.playerId}
                  name={playerOfMatch.name}
                  className="text-primary hover:underline"
                />
              </h2>
              <p className="text-sm text-text-secondary mb-1">
                <span className="font-medium text-text-primary tabular-nums">
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
            <div className="bg-primary/10 px-4 py-2 border-b border-surface-elevated">
              <h2 className="font-semibold text-text-primary">Combined impact</h2>
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
                            ? "border-b border-primary/25 bg-primary/5"
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
            <div className="bg-primary/10 px-4 py-2 border-b border-surface-elevated">
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
            <div className="bg-primary/10 px-4 py-2 border-b border-surface-elevated">
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
        <section className="mb-10 rounded-lg border border-surface-elevated bg-surface overflow-hidden shadow-sm">
          <div className="divide-y divide-surface-elevated max-h-[70vh] overflow-y-auto">
            {ballsTimelineRows.length === 0 ? (
              <p className="p-4 text-sm text-text-muted">
                No ball-by-ball data for this innings (regenerate scorecards with deliveries).
              </p>
            ) : (
              ballsTimelineRows.map((row) => (
                <div
                  key={row.key}
                  className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2.5 text-sm hover:bg-surface-elevated/30"
                >
                  <span className="w-14 shrink-0 tabular-nums text-text-muted font-medium">
                    {row.ob}
                  </span>
                  <span className="flex-1 min-w-[12rem]">
                    <span className="text-text-primary">
                      {(row.bowler ?? "—").trim()} to {(row.batter ?? "—").trim()}
                    </span>
                    <span className="text-text-secondary"> — {row.narr}</span>
                  </span>
                  <span className="shrink-0 tabular-nums text-text-muted">
                    {row.scoreAfter}/{row.wktsAfter}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      )}

      {/* Per-innings scorecard */}
      {view === "scorecard" &&
        inningsList.map(([k, inn]) => {
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
                        , {f.dismissalText}, {f.overBall} ov)
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
