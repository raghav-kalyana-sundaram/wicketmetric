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
  Trophy,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import CrossLinkBar, { type CrossLink } from "@/components/CrossLinkBar";
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
import BattingFrameworkTable from "@/components/scorecard/BattingFrameworkTable";
import BowlingFrameworkTable from "@/components/scorecard/BowlingFrameworkTable";
import {
  computeMatchImpact,
  formatCombinedSummary,
  MIN_BALLS_BAT_IMPACT,
  MIN_BALLS_BOWL_IMPACT,
} from "@/lib/scorecardMatchImpact";
import {
  buildManhattanChartRows,
  buildPartnershipStandTimeline,
  buildWormRows,
  oversRunMapFromInnings,
} from "@/lib/scorecardCharts";
import "@/styles/scorecards.css";

type ViewTab = "scorecard" | "balls" | "impact" | "stats" | "overs";

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

type OverSummaryRow = {
  inningKey: string;
  team: string;
  over: number;
  runs: number;
  wickets: number;
  legalBalls: number;
  cumRuns: number;
  runRate: number;
};

type PhaseBreakdown = {
  phase: "Power Play" | "Middle Overs" | "Final Overs";
  runs: number;
  wickets: number;
};

type TeamScoringBreakdown = {
  team: string;
  phases: PhaseBreakdown[];
  sixes: number;
  fours: number;
  boundaryRuns: number;
  dotBallPct: number;
  extras: number;
};

type PartnershipRow = {
  inningKey: string;
  team: string;
  pair: string;
  runs: number;
  balls: number;
  wicketOver: string | null;
};

function overBucket(overOneBased: number): PhaseBreakdown["phase"] {
  if (overOneBased <= 6) return "Power Play";
  if (overOneBased <= 15) return "Middle Overs";
  return "Final Overs";
}

function buildOverSummaries(inningsList: [string, Innings][]): OverSummaryRow[] {
  const rows: OverSummaryRow[] = [];
  for (const [inningKey, inn] of inningsList) {
    const timeline = buildInningsTimeline(inn.bowling ?? []);
    const perOver = new Map<number, { runs: number; wickets: number; legalBalls: number }>();
    for (const ball of timeline) {
      const overOneBased = Number(ball.over ?? 0) + 1;
      const curr = perOver.get(overOneBased) ?? { runs: 0, wickets: 0, legalBalls: 0 };
      curr.runs += Number(ball.total_runs ?? 0);
      if (ball.is_wicket) curr.wickets += 1;
      if (ball.is_legal) curr.legalBalls += 1;
      perOver.set(overOneBased, curr);
    }
    let cumRuns = 0;
    const orderedOvers = Array.from(perOver.keys()).sort((a, b) => a - b);
    for (const over of orderedOvers) {
      const item = perOver.get(over);
      if (!item) continue;
      cumRuns += item.runs;
      rows.push({
        inningKey,
        team: inn.batting_team ?? `Innings ${inningKey}`,
        over,
        runs: item.runs,
        wickets: item.wickets,
        legalBalls: item.legalBalls,
        cumRuns,
        runRate: over > 0 ? cumRuns / over : 0,
      });
    }
  }
  return rows;
}

function buildScoringBreakdown(inningsList: [string, Innings][]): TeamScoringBreakdown[] {
  return inningsList.map(([, inn]) => {
    const timeline = buildInningsTimeline(inn.bowling ?? []);
    const phaseRuns = new Map<PhaseBreakdown["phase"], { runs: number; wickets: number }>([
      ["Power Play", { runs: 0, wickets: 0 }],
      ["Middle Overs", { runs: 0, wickets: 0 }],
      ["Final Overs", { runs: 0, wickets: 0 }],
    ]);
    let legalBalls = 0;
    let dotBalls = 0;
    let extras = 0;
    for (const ball of timeline) {
      const phase = overBucket(Number(ball.over ?? 0) + 1);
      const slot = phaseRuns.get(phase)!;
      slot.runs += Number(ball.total_runs ?? 0);
      if (ball.is_wicket) slot.wickets += 1;
      if (ball.is_legal) {
        legalBalls += 1;
        if (Number(ball.total_runs ?? 0) === 0) dotBalls += 1;
      }
      extras += Math.max(0, Number(ball.total_runs ?? 0) - Number(ball.batter_runs ?? 0));
    }
    const sixes = (inn.batting ?? []).reduce((acc, b) => acc + Number(b.sixes ?? 0), 0);
    const fours = (inn.batting ?? []).reduce((acc, b) => acc + Number(b.fours ?? 0), 0);
    return {
      team: inn.batting_team ?? "Team",
      phases: [
        { phase: "Power Play", ...phaseRuns.get("Power Play")! },
        { phase: "Middle Overs", ...phaseRuns.get("Middle Overs")! },
        { phase: "Final Overs", ...phaseRuns.get("Final Overs")! },
      ],
      sixes,
      fours,
      boundaryRuns: fours * 4 + sixes * 6,
      dotBallPct: legalBalls > 0 ? (dotBalls / legalBalls) * 100 : 0,
      extras,
    };
  });
}

function buildPartnerships(
  inningsList: [string, Innings][],
  nameById: Map<string, string>,
): PartnershipRow[] {
  const rows: PartnershipRow[] = [];
  for (const [inningKey, inn] of inningsList) {
    const timeline = buildInningsTimeline(inn.bowling ?? []);
    if (timeline.length === 0) continue;
    let activePair: [string, string] | null = null;
    let partnershipRuns = 0;
    let partnershipBalls = 0;
    let pendingOutId: string | null = null;
    const pairLabel = (a: string, b: string) => {
      const nameA = nameById.get(a) ?? a;
      const nameB = nameById.get(b) ?? b;
      return `${nameA} / ${nameB}`;
    };
    const flush = (wicketOver: string | null) => {
      if (!activePair) return;
      if (partnershipRuns <= 0 && partnershipBalls <= 0) return;
      rows.push({
        inningKey,
        team: inn.batting_team ?? `Innings ${inningKey}`,
        pair: pairLabel(activePair[0], activePair[1]),
        runs: partnershipRuns,
        balls: partnershipBalls,
        wicketOver,
      });
    };

    for (const ball of timeline) {
      const batterId = String(ball.batter_id ?? ball.batter ?? "");
      if (!batterId) continue;
      if (!activePair) {
        activePair = [batterId, batterId];
      } else if (activePair[0] === activePair[1] && activePair[0] !== batterId) {
        activePair = [activePair[0], batterId];
      } else if (!activePair.includes(batterId)) {
        if (pendingOutId && activePair.includes(pendingOutId)) {
          activePair = activePair[0] === pendingOutId ? [batterId, activePair[1]] : [activePair[0], batterId];
        } else {
          flush(null);
          activePair = [activePair[1], batterId];
          partnershipRuns = 0;
          partnershipBalls = 0;
        }
      }
      partnershipRuns += Number(ball.total_runs ?? 0);
      if (ball.is_legal) partnershipBalls += 1;
      if (ball.is_wicket && ball.player_out_id && activePair.includes(String(ball.player_out_id))) {
        const overText = `${ball.over ?? "?"}.${ball.ball_idx ?? "?"}`;
        flush(overText);
        pendingOutId = String(ball.player_out_id);
        partnershipRuns = 0;
        partnershipBalls = 0;
      } else {
        pendingOutId = null;
      }
    }
    flush(null);
  }
  return rows.sort((a, b) => b.runs - a.runs || a.balls - b.balls);
}

function prettyTossDecision(decision?: string | null): string | null {
  if (!decision) return null;
  const d = String(decision).trim().toLowerCase();
  if (!d) return null;
  if (d === "bat") return "bat first";
  if (d === "field" || d === "bowl") return "field first";
  return d;
}

function computeResultLine(
  winner: string | null | undefined,
  inningsList: [string, Innings][],
): string | null {
  if (!winner) return null;
  if (inningsList.length < 2) return `${winner} won`;
  const first = inningsList[0]?.[1];
  const second = inningsList[1]?.[1];
  if (!first || !second) return `${winner} won`;
  const firstTotal = Number(first.innings_total ?? 0);
  const secondTotal = Number(second.innings_total ?? 0);
  const secondWkts = Number(second.innings_wickets ?? 0);
  const firstTeam = first.batting_team ?? "";
  const secondTeam = second.batting_team ?? "";

  if (winner === firstTeam && firstTotal > secondTotal) {
    return `${winner} won by ${firstTotal - secondTotal} runs`;
  }
  if (winner === secondTeam && secondTotal >= firstTotal) {
    return `${winner} won by ${Math.max(0, 10 - secondWkts)} wickets`;
  }
  return `${winner} won`;
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
  const [statsSection, setStatsSection] = useState<
    "all" | "scoring" | "performances" | "partnerships" | "manhattan" | "runrate" | "worm"
  >("all");
  const [ballsInnKey, setBallsInnKey] = useState<string>("");
  /** Innings used for per-innings charts (Manhattan, partnership timeline). */
  const [chartsInnKey, setChartsInnKey] = useState<string>("");

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
  const overSummaries = useMemo(() => buildOverSummaries(inningsList), [inningsList]);
  const scoringBreakdown = useMemo(() => buildScoringBreakdown(inningsList), [inningsList]);
  const partnerships = useMemo(
    () => buildPartnerships(inningsList, nameById).slice(0, 12),
    [inningsList, nameById],
  );

  const chartsInningsEntry = useMemo(() => {
    const key = chartsInnKey || inningsList[0]?.[0] || "";
    return inningsList.find(([k]) => k === key) ?? inningsList[0];
  }, [inningsList, chartsInnKey]);

  const manhattanInnings = useMemo(() => {
    if (!chartsInningsEntry) return { rows: [], team: "" };
    const [, inn] = chartsInningsEntry;
    return {
      rows: buildManhattanChartRows(inn),
      team: inn.batting_team ?? "Batting",
    };
  }, [chartsInningsEntry]);

  const partnershipTimeline = useMemo(() => {
    if (!chartsInningsEntry) return [];
    return buildPartnershipStandTimeline(chartsInningsEntry[1], nameById);
  }, [chartsInningsEntry, nameById]);

  const wormData = useMemo(() => {
    const first = inningsList[0]?.[1];
    const second = inningsList[1]?.[1];
    const team1 = first?.batting_team ?? "Innings 1";
    const team2 = second?.batting_team ?? "Innings 2";
    if (!first) return { rows: [] as Array<{ over: number; a: number; b: number }>, team1, team2, target: null as number | null };
    const m1 = oversRunMapFromInnings(first);
    if (!second) {
      let c = 0;
      const rows = [...m1.keys()]
        .sort((a, b) => a - b)
        .map((over) => {
          c += m1.get(over)?.runs ?? 0;
          return { over, a: c, b: 0 };
        });
      return { rows, team1, team2, target: null };
    }
    const m2 = oversRunMapFromInnings(second);
    const built = buildWormRows(m1, m2);
    const rows = built.map((r) => ({ over: r.over, a: r.cum1, b: r.cum2 }));
    const target =
      typeof second.target_runs === "number" && second.target_runs > 0
        ? second.target_runs
        : null;
    return { rows, team1, team2, target };
  }, [inningsList]);

  const topBatters = useMemo(() => {
    const rows = inningsList.flatMap(([, inn]) =>
      (inn.batting ?? []).map((b) => ({
        name: b.batter ?? b.batter_id ?? "Unknown",
        team: inn.batting_team ?? "Team",
        runs: Number(b.runs ?? 0),
        balls: Number(b.balls ?? 0),
        fours: Number(b.fours ?? 0),
        sixes: Number(b.sixes ?? 0),
      })),
    );
    return rows.sort((a, b) => b.runs - a.runs || a.balls - b.balls).slice(0, 4);
  }, [inningsList]);

  const topBowlers = useMemo(() => {
    const rows = inningsList.flatMap(([, inn]) =>
      (inn.bowling ?? []).map((bw) => ({
        name: bw.bowler ?? bw.bowler_id ?? "Unknown",
        team: inn.bowling_team ?? "Team",
        wickets: Number(bw.wickets ?? 0),
        runs: Number(bw.runs_conceded ?? 0),
        overs: bw.overs ?? "-",
        economy: Number(bw.economy ?? 0),
      })),
    );
    return rows
      .sort((a, b) => b.wickets - a.wickets || a.runs - b.runs || a.economy - b.economy)
      .slice(0, 4);
  }, [inningsList]);

  const overCompareRows = useMemo(() => {
    const teamA = inningsList[0]?.[1]?.batting_team ?? "Team A";
    const teamB = inningsList[1]?.[1]?.batting_team ?? "Team B";
    const aRows = overSummaries.filter((r) => r.inningKey === inningsList[0]?.[0]);
    const bRows = overSummaries.filter((r) => r.inningKey === inningsList[1]?.[0]);
    const maxOver = Math.max(
      aRows.length ? Math.max(...aRows.map((r) => r.over)) : 0,
      bRows.length ? Math.max(...bRows.map((r) => r.over)) : 0,
    );
    const aMap = new Map(aRows.map((r) => [r.over, r]));
    const bMap = new Map(bRows.map((r) => [r.over, r]));
    const out: Array<{
      over: number;
      aRuns: number;
      aWkts: number;
      bRuns: number;
      bWkts: number;
      impactful: boolean;
      aText: string;
      bText: string;
    }> = [];
    for (let over = 1; over <= maxOver; over += 1) {
      const a = aMap.get(over);
      const b = bMap.get(over);
      const aRuns = a?.runs ?? 0;
      const bRuns = b?.runs ?? 0;
      const aWkts = a?.wickets ?? 0;
      const bWkts = b?.wickets ?? 0;
      const impact = Math.max(aRuns + aWkts * 6, bRuns + bWkts * 6);
      out.push({
        over,
        aRuns,
        aWkts,
        bRuns,
        bWkts,
        impactful: impact >= 14 || aWkts >= 2 || bWkts >= 2,
        aText: `${aRuns}/${aWkts}`,
        bText: `${bRuns}/${bWkts}`,
      });
    }
    return { teamA, teamB, rows: out };
  }, [overSummaries, inningsList]);

  const maxPartnership = partnerships.reduce((m, p) => Math.max(m, p.runs), 0);
  const chartRows = useMemo(() => {
    const firstInnKey = inningsList[0]?.[0];
    const secondInnKey = inningsList[1]?.[0];
    const teamA = inningsList[0]?.[1]?.batting_team ?? "Team A";
    const teamB = inningsList[1]?.[1]?.batting_team ?? "Team B";
    const aMap = new Map(
      overSummaries.filter((r) => r.inningKey === firstInnKey).map((r) => [r.over, r]),
    );
    const bMap = new Map(
      overSummaries.filter((r) => r.inningKey === secondInnKey).map((r) => [r.over, r]),
    );
    const maxOver = Math.max(
      aMap.size ? Math.max(...Array.from(aMap.keys())) : 0,
      bMap.size ? Math.max(...Array.from(bMap.keys())) : 0,
    );
    const rows: Array<{
      over: number;
      [key: string]: number;
    }> = [];
    for (let over = 1; over <= maxOver; over += 1) {
      const a = aMap.get(over);
      const b = bMap.get(over);
      rows.push({
        over,
        [teamA]: a?.runs ?? 0,
        [teamB]: b?.runs ?? 0,
        [`${teamA} RR`]: a?.runRate ?? 0,
        [`${teamB} RR`]: b?.runRate ?? 0,
        [`${teamA} Cum`]: a?.cumRuns ?? 0,
        [`${teamB} Cum`]: b?.cumRuns ?? 0,
      });
    }
    return { rows, teamA, teamB };
  }, [inningsList, overSummaries]);

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

  const matchSummary = useMemo(() => {
    let bestBatter: { name: string; runs: number } | null = null;
    let bestBowler: { name: string; wickets: number; runs: number } | null = null;
    let totalSixes = 0;

    for (const [, inn] of inningsList) {
      for (const b of inn.batting ?? []) {
        const r = Number(b.runs ?? 0);
        const s = Number(b.sixes ?? 0);
        totalSixes += s;
        if (!bestBatter || r > bestBatter.runs) {
          bestBatter = { name: b.batter ?? "Unknown", runs: r };
        }
      }
      for (const bw of inn.bowling ?? []) {
        const w = Number(bw.wickets ?? 0);
        const rc = Number(bw.runs_conceded ?? 0);
        if (!bestBowler || w > bestBowler.wickets || (w === bestBowler.wickets && rc < bestBowler.runs)) {
          bestBowler = { name: bw.bowler ?? "Unknown", wickets: w, runs: rc };
        }
      }
    }

    return { bestBatter, bestBowler, totalSixes };
  }, [inningsList]);

  const tossLine = useMemo(() => {
    const tossWinner = meta.toss_winner;
    const tossDecision = prettyTossDecision(meta.toss_decision);
    if (!tossWinner) return null;
    return tossDecision ? `${tossWinner} won the toss and chose to ${tossDecision}` : `${tossWinner} won the toss`;
  }, [meta.toss_winner, meta.toss_decision]);

  const resultLine = useMemo(
    () => computeResultLine(meta.winner, inningsList),
    [meta.winner, inningsList],
  );

  const crossLinks = useMemo((): CrossLink[] => {
    const links: CrossLink[] = [
      { label: "View player profiles", to: "/search", icon: <Target size={12} /> },
      { label: "All scorecards", to: "/scorecards", icon: <Trophy size={12} /> },
      { label: "Top performances", to: "/performances", icon: <TrendingUp size={12} /> },
    ];
    if (meta.venue) {
      links.push({
        label: `Venue: ${meta.venue}`,
        to: `/venues?${new URLSearchParams({ venue: String(meta.venue), vtab: "overview" }).toString()}`,
      });
    }
    return links;
  }, [meta.venue]);

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

      <section className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <article className="rounded-lg border border-surface-elevated bg-surface p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Result</p>
          <p className="text-sm font-medium text-text-primary">
            {resultLine ?? (meta.winner ? `${meta.winner} won` : "Result unavailable")}
          </p>
          {meta.dls_applied ? (
            <p className="mt-1 text-xs text-amber-500/90">Revised target method applied</p>
          ) : null}
        </article>

        <article className="rounded-lg border border-surface-elevated bg-surface p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Toss</p>
          <p className="text-sm font-medium text-text-primary">
            {tossLine ?? "Toss details unavailable in this scorecard"}
          </p>
        </article>

        <article className="rounded-lg border border-surface-elevated bg-surface p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Player of the Match</p>
          {playerOfMatch ? (
            <>
              <p className="text-sm font-medium text-text-primary">
                <PlayerLink
                  id={playerOfMatch.playerId}
                  name={playerOfMatch.name}
                  className="text-primary hover:underline"
                />
              </p>
              <p className="mt-1 text-xs text-text-muted tabular-nums">
                {playerOfMatch.totalImpact.toFixed(2)} impact
              </p>
            </>
          ) : (
            <p className="text-sm text-text-muted">Not available</p>
          )}
        </article>

        <article className="rounded-lg border border-surface-elevated bg-surface p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">CricMetrics MVP</p>
          {impactCombined[0] ? (
            <>
              <p className="text-sm font-medium text-text-primary">
                <PlayerLink
                  id={impactCombined[0].playerId}
                  name={impactCombined[0].name}
                  className="text-primary hover:underline"
                />
              </p>
              <p className="mt-1 text-xs text-text-muted tabular-nums">
                Bat {impactCombined[0].batImpact.toFixed(2)} · Bowl {impactCombined[0].bowlImpact.toFixed(2)}
              </p>
            </>
          ) : (
            <p className="text-sm text-text-muted">No qualifying MVP line</p>
          )}
        </article>

        <article className="rounded-lg border border-surface-elevated bg-surface p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Best batting</p>
          <p className="text-sm font-medium text-text-primary">
            {matchSummary.bestBatter
              ? `${matchSummary.bestBatter.name} (${matchSummary.bestBatter.runs})`
              : "Unavailable"}
          </p>
        </article>

        <article className="rounded-lg border border-surface-elevated bg-surface p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Best bowling</p>
          <p className="text-sm font-medium text-text-primary">
            {matchSummary.bestBowler
              ? `${matchSummary.bestBowler.name} (${matchSummary.bestBowler.wickets}/${matchSummary.bestBowler.runs})`
              : "Unavailable"}
          </p>
          {matchSummary.totalSixes > 0 ? (
            <p className="mt-1 text-xs text-text-muted tabular-nums">
              Match sixes: {matchSummary.totalSixes}
            </p>
          ) : null}
        </article>
      </section>

      <div
        className="scorecard-view-tabs flex flex-wrap gap-2 mb-6"
        role="tablist"
        aria-label="Scorecard view"
      >
        {(
          [
            ["scorecard", "Scorecard"],
            ["stats", "Stats"],
            ["overs", "Overs"],
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
            onClick={() => {
              setView(id);
              if (id !== "stats") setStatsSection("all");
            }}
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
            30 beats 90 off 60). Bowling with wickets:{" "}
            <span className="tabular-nums text-text-primary">wickets × balls ÷ runs</span> (linear
            in wickets so one extra wicket does not explode past peers), tuned so a spell like{" "}
            <span className="tabular-nums">4/15</span> rates alongside or above a very fast{" "}
            <span className="tabular-nums">50</span>, plus an extra for{" "}
            <span className="tabular-nums text-text-primary">runs saved</span> vs the leave-one-out
            match rate. Wicketless spells use runs saved only. Minimum{" "}
            {MIN_BALLS_BAT_IMPACT} balls faced or {MIN_BALLS_BOWL_IMPACT} balls bowled to qualify.{" "}
            <strong className="text-text-primary">Player of the match</strong> is whoever has the
            highest <span className="tabular-nums text-text-primary">bat + bowl</span> impact (only
            disciplines you qualify for count).
            Below, <strong className="text-text-primary">Batting analytics</strong> and{" "}
            <strong className="text-text-primary">Bowling analytics</strong> add 10-metric views
            (phase, pressure, in-match quality) from the same ball-by-ball feed — orthogonal to the
            simple impact numbers.
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
              <h2 className="font-semibold text-text-primary">Batting analytics</h2>
              <p className="text-xs text-text-muted font-normal mt-1">
                Outcome + process + context from this match’s deliveries (see tooltips on column
                headers).
              </p>
            </div>
            <div className="p-4">
              <BattingFrameworkTable inningsList={inningsList} />
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

          <section className="rounded-lg border border-surface-elevated bg-surface overflow-hidden shadow-sm">
            <div className="border-b border-slate-200 bg-slate-100/80 px-4 py-2 dark:border-white/[0.07] dark:bg-[#080808]">
              <h2 className="font-semibold text-text-primary">Bowling analytics</h2>
              <p className="text-xs text-text-muted font-normal mt-1">
                Control, threat, phase execution, and chase pressure from this match’s deliveries.
              </p>
            </div>
            <div className="p-4">
              <BowlingFrameworkTable inningsList={inningsList} />
            </div>
          </section>
        </div>
      )}

      {view === "stats" && (
        <div className="space-y-6 mb-10">
          {(statsSection === "all" ||
            statsSection === "manhattan" ||
            statsSection === "partnerships") && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-surface-elevated bg-surface-elevated/15 px-3 py-2">
              <label htmlFor="scorecard-charts-innings" className="text-sm text-text-secondary">
                Charts innings
              </label>
              <select
                id="scorecard-charts-innings"
                className="rounded-md border border-surface-elevated bg-surface px-3 py-1.5 text-sm text-text-primary"
                value={chartsInningsEntry?.[0] ?? ""}
                onChange={(e) => setChartsInnKey(e.target.value)}
              >
                {inningsList.map(([k, inn]) => (
                  <option key={k} value={k}>
                    {inn.innings_num ?? k} — {inn.batting_team ?? `Innings ${k}`}
                  </option>
                ))}
              </select>
              <p className="text-xs text-text-muted max-w-md">
                Manhattan and partnership timeline are per innings. The worm compares both sides over
                the same over numbers.
              </p>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {(
              [
                ["all", "All"],
                ["scoring", "Scoring Breakdown"],
                ["performances", "Best Performances"],
                ["partnerships", "Partnership timeline"],
                ["manhattan", "Manhattan"],
                ["runrate", "Run Rate Graph"],
                ["worm", "Worm"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={statsSection === id ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
                onClick={() => setStatsSection(id)}
              >
                {label}
              </button>
            ))}
          </div>

          {(statsSection === "all" || statsSection === "scoring") && (
            <section className="rounded-lg border border-surface-elevated bg-surface p-4">
              <h2 className="text-xl font-semibold text-text-primary mb-4">Scoring Breakdown</h2>
              <div className="grid gap-4 md:grid-cols-2">
                {scoringBreakdown.map((team) => (
                  <article
                    key={team.team}
                    className="rounded-lg border border-surface-elevated/70 bg-surface-elevated/20 p-3"
                  >
                    <h3 className="text-lg font-semibold text-text-primary mb-3">{team.team}</h3>
                    <div className="space-y-2 text-sm">
                      {team.phases.map((phase) => (
                        <div key={phase.phase} className="flex items-center justify-between">
                          <span className="text-text-secondary">{phase.phase}</span>
                          <span className="tabular-nums text-text-primary">
                            {phase.runs}/{phase.wickets}
                          </span>
                        </div>
                      ))}
                      <div className="border-t border-surface-elevated pt-2 mt-2" />
                      <div className="flex items-center justify-between">
                        <span className="text-text-secondary">Sixes</span>
                        <span className="tabular-nums">{team.sixes}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-text-secondary">Fours</span>
                        <span className="tabular-nums">{team.fours}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-text-secondary">Runs in boundaries</span>
                        <span className="tabular-nums">{team.boundaryRuns}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-text-secondary">Dot balls</span>
                        <span className="tabular-nums">{team.dotBallPct.toFixed(0)}%</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-text-secondary">Runs in extras</span>
                        <span className="tabular-nums">{team.extras}</span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}

          {(statsSection === "all" || statsSection === "performances") && (
            <section className="rounded-lg border border-surface-elevated bg-surface p-4">
              <h2 className="text-xl font-semibold text-text-primary mb-4">Best Performances</h2>
              <div className="grid gap-4 md:grid-cols-2">
                <article className="rounded-lg border border-surface-elevated/70 bg-surface-elevated/20 p-3">
                  <h3 className="text-lg font-semibold text-text-primary mb-2">Batters</h3>
                  <div className="space-y-2">
                    {topBatters.map((b, idx) => (
                      <div
                        key={`${b.name}-${idx}`}
                        className="flex items-center justify-between text-sm border-b border-surface-elevated/40 pb-2 last:border-b-0 last:pb-0"
                      >
                        <div>
                          <p className="font-medium text-text-primary">{b.name}</p>
                          <p className="text-xs text-text-muted">{b.team}</p>
                        </div>
                        <p className="tabular-nums text-text-primary">
                          {b.runs} ({b.balls}) · {b.fours}x4 · {b.sixes}x6
                        </p>
                      </div>
                    ))}
                  </div>
                </article>
                <article className="rounded-lg border border-surface-elevated/70 bg-surface-elevated/20 p-3">
                  <h3 className="text-lg font-semibold text-text-primary mb-2">Bowlers</h3>
                  <div className="space-y-2">
                    {topBowlers.map((b, idx) => (
                      <div
                        key={`${b.name}-${idx}`}
                        className="flex items-center justify-between text-sm border-b border-surface-elevated/40 pb-2 last:border-b-0 last:pb-0"
                      >
                        <div>
                          <p className="font-medium text-text-primary">{b.name}</p>
                          <p className="text-xs text-text-muted">{b.team}</p>
                        </div>
                        <p className="tabular-nums text-text-primary">
                          {b.wickets}/{b.runs} ({b.overs}) · Econ {b.economy.toFixed(2)}
                        </p>
                      </div>
                    ))}
                  </div>
                </article>
              </div>
            </section>
          )}

          {(statsSection === "all" || statsSection === "partnerships") && (
            <section className="rounded-lg border border-surface-elevated bg-surface p-4">
              <h2 className="text-xl font-semibold text-text-primary mb-1">Partnership timeline</h2>
              <p className="text-sm text-text-muted mb-4">
                Stacked bars: runs off the bat per batter (and extras) in each stand, in dismissal
                order. Line: team total after each partnership ends.
              </p>
              {partnershipTimeline.length === 0 ? (
                <p className="text-sm text-text-muted">No partnership data for this innings.</p>
              ) : (
                <div className="h-[340px] mb-8">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={partnershipTimeline.map((s) => ({
                        stand: s.order,
                        runsA: s.runsA,
                        runsB: s.runsB,
                        extras: s.extras,
                        cum: s.cumScoreAtEnd,
                        pair: s.pair,
                        balls: s.balls,
                        labelA: `${nameById.get(s.batterAId) ?? s.batterAId} (off bat)`,
                        labelB: `${nameById.get(s.batterBId) ?? s.batterBId} (off bat)`,
                      }))}
                      margin={{ top: 8, right: 12, left: 4, bottom: 4 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                      <XAxis
                        dataKey="stand"
                        tickFormatter={(v) => `#${v}`}
                        label={{ value: "Stand (chronological)", position: "insideBottom", offset: -2 }}
                      />
                      <YAxis
                        yAxisId="left"
                        label={{ value: "Runs in stand", angle: -90, position: "insideLeft" }}
                      />
                      <YAxis
                        yAxisId="right"
                        orientation="right"
                        label={{ value: "Team total", angle: 90, position: "insideRight" }}
                      />
                      <RechartsTooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const row = payload[0].payload as {
                            pair?: string;
                            balls?: number;
                            runsA?: number;
                            runsB?: number;
                            extras?: number;
                            cum?: number;
                            labelA?: string;
                            labelB?: string;
                          };
                          return (
                            <div className="rounded-md border border-surface-elevated bg-surface px-3 py-2 text-xs shadow-md">
                              <p className="font-medium text-text-primary mb-1">
                                {row.pair} · {row.balls ?? 0} balls
                              </p>
                              <ul className="space-y-0.5 text-text-secondary tabular-nums">
                                <li>
                                  {row.labelA}: {row.runsA ?? 0}
                                </li>
                                <li>
                                  {row.labelB}: {row.runsB ?? 0}
                                </li>
                                <li>Extras: {row.extras ?? 0}</li>
                                <li className="pt-1 border-t border-surface-elevated mt-1 text-text-primary">
                                  Team total after stand: {row.cum ?? 0}
                                </li>
                              </ul>
                            </div>
                          );
                        }}
                      />
                      <Legend />
                      <Bar
                        yAxisId="left"
                        name="Batter A (off bat)"
                        dataKey="runsA"
                        stackId="stand"
                        fill="#1d7ff5"
                        radius={[0, 0, 0, 0]}
                      />
                      <Bar
                        yAxisId="left"
                        name="Batter B (off bat)"
                        dataKey="runsB"
                        stackId="stand"
                        fill="#f59e0b"
                        radius={[0, 0, 0, 0]}
                      />
                      <Bar
                        yAxisId="left"
                        name="Extras in stand"
                        dataKey="extras"
                        stackId="stand"
                        fill="#8b5cf6"
                        radius={[4, 4, 0, 0]}
                      />
                      <Line
                        yAxisId="right"
                        type="monotone"
                        name="Cumulative team score"
                        dataKey="cum"
                        stroke="#a1a1aa"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "#a1a1aa" }}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}

              <h3 className="text-sm font-semibold text-text-primary mb-2">Largest stands</h3>
              <div className="space-y-2">
                {partnerships.length === 0 ? (
                  <p className="text-sm text-text-muted">No partnership data available.</p>
                ) : (
                  partnerships.map((p, idx) => (
                    <div key={`${p.team}-${idx}`} className="grid grid-cols-[1fr_auto] gap-3 items-center">
                      <div>
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-text-secondary">
                            {p.team} · {p.pair}
                          </span>
                          <span className="tabular-nums text-text-primary">
                            {p.runs} ({p.balls})
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-surface-elevated mt-1 overflow-hidden">
                          <div
                            className="h-full bg-primary"
                            style={{
                              width: `${maxPartnership > 0 ? (p.runs / maxPartnership) * 100 : 0}%`,
                            }}
                          />
                        </div>
                      </div>
                      <span className="text-xs text-text-muted tabular-nums min-w-[4rem] text-right">
                        {p.wicketOver ? `${p.wicketOver} ov` : "not out"}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </section>
          )}

          {(statsSection === "all" || statsSection === "manhattan") && (
            <section className="rounded-lg border border-surface-elevated bg-surface p-4">
              <h2 className="text-xl font-semibold text-text-primary mb-1">Manhattan</h2>
              <p className="text-sm text-text-muted mb-3">
                {manhattanInnings.team} — runs scored each over (bars). Red dots mark wickets (in
                that over).
              </p>
              {manhattanInnings.rows.length === 0 ? (
                <p className="text-sm text-text-muted">
                  No over-by-over data (regenerate scorecards with deliveries).
                </p>
              ) : (
                <div className="h-[320px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={manhattanInnings.rows} margin={{ top: 12, right: 8, left: 4, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                      <XAxis dataKey="over" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                      <RechartsTooltip
                        formatter={(v: number, name: string) =>
                          String(name).startsWith("w") ? null : [v, name === "runs" ? "Runs" : name]
                        }
                        labelFormatter={(o) => `Over ${o}`}
                      />
                      <Legend />
                      <Bar
                        name="Runs in over"
                        dataKey="runs"
                        fill="#1d7ff5"
                        radius={[2, 2, 0, 0]}
                        maxBarSize={48}
                      />
                      {(["w1", "w2", "w3", "w4", "w5", "w6"] as const).map((wk) => (
                        <Line
                          key={wk}
                          dataKey={wk}
                          stroke="transparent"
                          strokeWidth={0}
                          dot={{ r: 5, fill: "#f43f5e", strokeWidth: 1.5, stroke: "#18181b" }}
                          legendType="none"
                          isAnimationActive={false}
                          connectNulls={false}
                        />
                      ))}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>
          )}

          {(statsSection === "all" || statsSection === "runrate") && (
            <section className="rounded-lg border border-surface-elevated bg-surface p-4">
              <h2 className="text-xl font-semibold text-text-primary mb-3">Run Rate Graph</h2>
              <div className="h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartRows.rows}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                    <XAxis dataKey="over" />
                    <YAxis />
                    <RechartsTooltip />
                    <Legend />
                    <Line
                      type="monotone"
                      dataKey={`${chartRows.teamA} RR`}
                      stroke="#1d7ff5"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey={`${chartRows.teamB} RR`}
                      stroke="#f59e0b"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}

          {(statsSection === "all" || statsSection === "worm") && (
            <section className="rounded-lg border border-surface-elevated bg-surface p-4">
              <h2 className="text-xl font-semibold text-text-primary mb-1">Worm</h2>
              <p className="text-sm text-text-muted mb-3">
                Cumulative team score by over — compare run accumulation and chases. Both innings are
                aligned on over number (innings two may finish earlier).
              </p>
              {wormData.rows.length === 0 ? (
                <p className="text-sm text-text-muted">No data for worm chart.</p>
              ) : (
                <div className="h-[320px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={wormData.rows} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                      <XAxis dataKey="over" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                      <RechartsTooltip
                        formatter={(v: number) => [v, "Runs"]}
                        labelFormatter={(o) => `After over ${o}`}
                      />
                      <Legend />
                      {wormData.target != null ? (
                        <ReferenceLine
                          y={wormData.target}
                          stroke="#22c55e"
                          strokeDasharray="5 5"
                          label={{
                            value: `Target ${wormData.target}`,
                            position: "insideTopRight",
                            fill: "#86efac",
                            fontSize: 11,
                          }}
                        />
                      ) : null}
                      <Line
                        type="stepAfter"
                        name={wormData.team1}
                        dataKey="a"
                        stroke="#1d7ff5"
                        strokeWidth={2.2}
                        dot={false}
                        isAnimationActive={false}
                      />
                      {inningsList.length > 1 ? (
                        <Line
                          type="stepAfter"
                          name={wormData.team2}
                          dataKey="b"
                          stroke="#f59e0b"
                          strokeWidth={2.2}
                          dot={false}
                          isAnimationActive={false}
                        />
                      ) : null}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>
          )}
        </div>
      )}

      {view === "overs" && (
        <section className="mb-10 rounded-lg border border-surface-elevated bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-elevated">
            <h2 className="text-lg font-semibold text-text-primary">Over Highlights</h2>
            <p className="text-xs text-text-muted mt-1">
              Impactful overs are highlighted based on wickets or high run swings.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="scorecard-table w-full text-sm">
              <thead>
                <tr className="border-b border-surface-elevated text-left text-text-muted">
                  <th className="py-2 px-3">Ovs</th>
                  <th className="py-2 px-3">{overCompareRows.teamA}</th>
                  <th className="py-2 px-3">{overCompareRows.teamB}</th>
                </tr>
              </thead>
              <tbody>
                {overCompareRows.rows.map((r) => (
                  <tr
                    key={r.over}
                    className={
                      r.impactful
                        ? "border-b border-surface-elevated/60 bg-primary/10"
                        : "border-b border-surface-elevated/60"
                    }
                  >
                    <td className="py-2 px-3 tabular-nums">{r.over}</td>
                    <td className="py-2 px-3 tabular-nums">
                      {r.aText}
                      <span className="text-text-muted ml-2">({r.aRuns} runs)</span>
                    </td>
                    <td className="py-2 px-3 tabular-nums">
                      {r.bText}
                      <span className="text-text-muted ml-2">({r.bRuns} runs)</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
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

      <CrossLinkBar links={crossLinks} title="Explore more" className="mt-8" />
    </div>
  );
}
