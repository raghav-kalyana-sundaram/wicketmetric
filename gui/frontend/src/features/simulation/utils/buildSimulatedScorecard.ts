/**
 * Builds API-shaped Scorecard JSON from a deterministic mock timeline (preview model).
 */

import type { PlayerSummary } from "@/api/types";
import type {
  BattingLine,
  BowlingDelivery,
  BowlingLine,
  Innings,
  Scorecard,
} from "@/components/scorecard/scorecardTypes";

export type InningsPhase = "first" | "chase";

export interface BuildSimulatedScorecardInput {
  matchId: string;
  battingTeam: string;
  bowlingTeam: string;
  /** teams[0] = first batting side (chart ref); [battingTeam, bowlingTeam] */
  oversLimit: number;
  battingXI: PlayerSummary[];
  bowlingXI: PlayerSummary[];
  inningsPhase: InningsPhase;
  /** Required when inningsPhase === "chase" for innings 2 target */
  targetRuns: number | null;
  injectFirstInnings: boolean;
  injectRuns: number;
  injectWickets: number;
  /** Legal balls already completed in first innings (e.g. 84 = next ball 15.1) */
  injectLegalBalls: number;
  injectStriker: PlayerSummary | null;
  injectNonStriker: PlayerSummary | null;
  /** Ordered dismissed batters (first = first out), length must equal injectWickets when inject */
  dismissedBatters: PlayerSummary[];
  seed: number;
}

type MutableBatter = {
  id: string;
  name: string;
  runs: number;
  balls: number;
  fours: number;
  sixes: number;
  out: boolean;
  dismissal_kind: string | null;
  dismissal_over: number | null;
  dismissal_ball_idx: number | null;
  dismissal_bowler_id: string | null;
  dismissal_bowler_name: string | null;
  deliveries: NonNullable<BattingLine["deliveries"]>;
};

type MutableBowler = {
  id: string;
  name: string;
  runs: number;
  balls: number;
  legalBalls: number;
  wickets: number;
  deliveries: BowlingDelivery[];
};

function mulberry32(seed: number) {
  return function next() {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function nextBallCoords(legalBallsSoFar: number): { over: number; ball_idx: number } {
  const over = Math.floor(legalBallsSoFar / 6) + 1;
  const ball_idx = (legalBallsSoFar % 6) + 1;
  return { over, ball_idx };
}

function simulateInnings(params: {
  rnd: () => number;
  battingOrder: PlayerSummary[];
  bowlingOrder: PlayerSummary[];
  maxLegalBalls: number;
  startScore: number;
  startWkts: number;
  startLegalBalls: number;
  strikerStart: PlayerSummary | null;
  nonStrikerStart: PlayerSummary | null;
  dismissedSoFar: PlayerSummary[];
  chaseTarget: number | null;
}): {
  battingLines: BattingLine[];
  bowlingLines: BowlingLine[];
  total: number;
  wickets: number;
  allDeliveries: BowlingDelivery[];
} {
  const {
    rnd,
    battingOrder,
    bowlingOrder,
    maxLegalBalls,
    startScore,
    startWkts,
    startLegalBalls,
    strikerStart,
    nonStrikerStart,
    dismissedSoFar,
    chaseTarget,
  } = params;

  const batters: MutableBatter[] = battingOrder.map((p) => ({
    id: p.id,
    name: p.name,
    runs: 0,
    balls: 0,
    fours: 0,
    sixes: 0,
    out: false,
    dismissal_kind: null,
    dismissal_over: null,
    dismissal_ball_idx: null,
    dismissal_bowler_id: null,
    dismissal_bowler_name: null,
    deliveries: [],
  }));

  for (const p of dismissedSoFar) {
    const b = batters.find((x) => x.id === p.id);
    if (b) {
      b.out = true;
      b.dismissal_kind = "caught";
    }
  }

  const pickFirstAvailable = (prefer?: string | null) => {
    if (prefer) {
      const i = batters.findIndex((b) => b.id === prefer && !b.out);
      if (i >= 0) return i;
    }
    return batters.findIndex((b) => !b.out);
  };

  let strikerIdx = pickFirstAvailable(strikerStart?.id ?? null);
  let nonStrikerIdx = pickFirstAvailable(nonStrikerStart?.id ?? null);
  if (nonStrikerIdx === strikerIdx) {
    nonStrikerIdx = batters.findIndex((b, bj) => bj !== strikerIdx && !b.out);
  }
  let nextBatterIdx = 0;
  for (let i = 0; i < batters.length; i++) {
    if (i !== strikerIdx && i !== nonStrikerIdx && !batters[i]!.out) {
      nextBatterIdx = i;
      break;
    }
  }

  const bowlers: MutableBowler[] = bowlingOrder.map((p) => ({
    id: p.id,
    name: p.name,
    runs: 0,
    balls: 0,
    legalBalls: 0,
    wickets: 0,
    deliveries: [],
  }));

  let teamScore = startScore;
  let wkts = startWkts;
  let legalCum = startLegalBalls;
  const allDeliveries: BowlingDelivery[] = [];

  const rotateStrike = () => {
    const t = strikerIdx;
    strikerIdx = nonStrikerIdx;
    nonStrikerIdx = t;
  };

  const bringNext = (): boolean => {
    while (nextBatterIdx < batters.length) {
      const b = batters[nextBatterIdx]!;
      if (!b.out) {
        strikerIdx = nextBatterIdx;
        nextBatterIdx++;
        return true;
      }
      nextBatterIdx++;
    }
    for (let i = 0; i < batters.length; i++) {
      const b = batters[i]!;
      if (!b.out && i !== nonStrikerIdx) {
        strikerIdx = i;
        return true;
      }
    }
    return false;
  };

  while (legalCum - startLegalBalls < maxLegalBalls && wkts < 10) {
    if (chaseTarget != null && teamScore >= chaseTarget) break;

    const striker = batters[strikerIdx];
    if (!striker || striker.out) {
      if (!bringNext()) break;
      continue;
    }

    const bowler = bowlers[legalCum % bowlers.length]!;
    const { over, ball_idx } = nextBallCoords(legalCum);

    const r = rnd();
    let is_wide = r < 0.06;
    let is_noball = !is_wide && r < 0.11;
    let is_wicket = !is_wide && !is_noball && r < 0.14;
    let total_runs = 0;
    let batter_runs = 0;
    let is_legal = true;

    if (is_wide) {
      total_runs = rnd() < 0.85 ? 1 : 2;
      is_legal = false;
    } else if (is_noball) {
      is_legal = false;
      batter_runs = rnd() < 0.7 ? 0 : rnd() < 0.5 ? 1 : 4;
      total_runs = 1 + batter_runs;
    } else if (is_wicket) {
      total_runs = 0;
      batter_runs = 0;
    } else {
      const x = rnd();
      if (x < 0.48) {
        total_runs = batter_runs = 0;
      } else if (x < 0.72) {
        total_runs = batter_runs = 1;
      } else if (x < 0.88) {
        total_runs = batter_runs = 4;
      } else {
        total_runs = batter_runs = 6;
      }
    }

    const team_score_before = teamScore;
    teamScore += total_runs;

    const d: BowlingDelivery = {
      over,
      ball_idx,
      batter: striker.name,
      batter_id: striker.id,
      batter_runs,
      total_runs,
      is_wide: is_wide || undefined,
      is_noball: is_noball || undefined,
      is_legal: is_legal,
      is_wicket: is_wicket || undefined,
      wicket_kind: is_wicket ? "caught" : undefined,
      player_out_id: is_wicket ? striker.id : undefined,
    };

    if (is_legal) {
      striker.balls += 1;
      legalCum += 1;
      bowler.legalBalls += 1;
    }
    bowler.balls += 1;
    bowler.runs += total_runs;
    striker.runs += batter_runs;
    if (batter_runs === 4) striker.fours += 1;
    if (batter_runs === 6) striker.sixes += 1;

    striker.deliveries.push({
      over,
      ball_idx,
      team_score_before,
      total_runs,
      is_wicket: is_wicket || undefined,
      player_out_id: is_wicket ? striker.id : undefined,
      bowler: bowler.name,
      is_wide: is_wide || undefined,
      is_noball: is_noball || undefined,
    });

    if (is_wicket) {
      striker.out = true;
      striker.dismissal_kind = "caught";
      striker.dismissal_over = over;
      striker.dismissal_ball_idx = ball_idx;
      striker.dismissal_bowler_id = bowler.id;
      striker.dismissal_bowler_name = bowler.name;
      bowler.wickets += 1;
      wkts += 1;
      bringNext();
    } else if (is_legal && batter_runs % 2 === 1) {
      rotateStrike();
    }

    bowler.deliveries.push(d);
    allDeliveries.push(d);

    if (chaseTarget != null && teamScore >= chaseTarget) break;
  }

  const battingLines: BattingLine[] = batters.map((b, i) => ({
    batter_id: b.id,
    batter: b.name,
    runs: b.runs,
    balls: b.balls,
    fours: b.fours,
    sixes: b.sixes,
    strike_rate: b.balls > 0 ? Math.round((b.runs / b.balls) * 10000) / 100 : null,
    dismissal_kind: b.out ? b.dismissal_kind : null,
    dismissal_over: b.dismissal_over,
    dismissal_ball_idx: b.dismissal_ball_idx,
    dismissal_bowler: b.dismissal_bowler_name,
    dismissal_bowler_id: b.dismissal_bowler_id,
    batting_position: i + 1,
    deliveries: b.deliveries.length ? b.deliveries : undefined,
  }));

  const bowlingLines: BowlingLine[] = bowlers.map((bw) => {
    const oversStr =
      bw.legalBalls > 0
        ? `${Math.floor(bw.legalBalls / 6)}.${bw.legalBalls % 6}`
        : "0.0";
    const econ =
      bw.legalBalls > 0
        ? Math.round((bw.runs * 600) / bw.legalBalls) / 100
        : null;
    return {
      bowler_id: bw.id,
      bowler: bw.name,
      balls: bw.balls,
      overs: oversStr,
      runs_conceded: bw.runs,
      wickets: bw.wickets,
      economy: econ,
      maidens: 0,
      deliveries: bw.deliveries,
    };
  });

  return {
    battingLines,
    bowlingLines,
    total: teamScore,
    wickets: wkts,
    allDeliveries,
  };
}

function assignWinProbabilities(
  deliveries: BowlingDelivery[],
  finalPTeam0: number,
): void {
  const n = deliveries.length;
  if (n === 0) return;
  let prev = 0.5;
  for (let i = 0; i < n; i++) {
    const t = n === 1 ? 1 : i / (n - 1);
    const p = 0.5 + (finalPTeam0 - 0.5) * t;
    const before = prev;
    const after = i === n - 1 ? finalPTeam0 : p;
    const wpa = after - before;
    deliveries[i]!.win_prob_before = before;
    deliveries[i]!.win_prob_after = after;
    deliveries[i]!.wpa = wpa;
    prev = after;
  }
}

export function buildSimulatedScorecard(input: BuildSimulatedScorecardInput): {
  scorecard: Scorecard;
  finalPTeam0: number;
} {
  const rnd = mulberry32(input.seed + 911);
  const { battingTeam, bowlingTeam, oversLimit } = input;

  let finalP = 0.45 + rnd() * 0.22;
  finalP = Math.max(0.08, Math.min(0.92, finalP));

  const maxI1 = Math.min(120, oversLimit * 6 - input.injectLegalBalls);
  const inn1 = simulateInnings({
    rnd,
    battingOrder: input.battingXI,
    bowlingOrder: input.bowlingXI,
    maxLegalBalls: Math.max(6, maxI1),
    startScore: input.injectFirstInnings ? input.injectRuns : 0,
    startWkts: input.injectFirstInnings ? input.injectWickets : 0,
    startLegalBalls: input.injectFirstInnings ? input.injectLegalBalls : 0,
    strikerStart: input.injectStriker,
    nonStrikerStart: input.injectNonStriker,
    dismissedSoFar: input.dismissedBatters,
    chaseTarget: null,
  });

  const deliveries1 = inn1.allDeliveries;
  let deliveries2: BowlingDelivery[] = [];

  let inn2: ReturnType<typeof simulateInnings> | null = null;
  if (input.inningsPhase === "chase" && input.targetRuns != null) {
    inn2 = simulateInnings({
      rnd,
      battingOrder: input.bowlingXI,
      bowlingOrder: input.battingXI,
      maxLegalBalls: oversLimit * 6,
      startScore: 0,
      startWkts: 0,
      startLegalBalls: 0,
      strikerStart: null,
      nonStrikerStart: null,
      dismissedSoFar: [],
      chaseTarget: input.targetRuns,
    });
    deliveries2 = inn2.allDeliveries;
  }

  const allForWp = [...deliveries1, ...deliveries2];
  assignWinProbabilities(allForWp, finalP);

  const innings1: Innings = {
    innings_num: 1,
    batting_team: battingTeam,
    bowling_team: bowlingTeam,
    batting: inn1.battingLines,
    bowling: inn1.bowlingLines,
    innings_total: inn1.total,
    innings_wickets: inn1.wickets,
  };

  const inningsRecord: Record<string, Innings> = { "1": innings1 };

  if (inn2) {
    inningsRecord["2"] = {
      innings_num: 2,
      batting_team: bowlingTeam,
      bowling_team: battingTeam,
      batting: inn2.battingLines,
      bowling: inn2.bowlingLines,
      innings_total: inn2.total,
      innings_wickets: inn2.wickets,
    };
  }

  const winner =
    input.inningsPhase === "chase" && input.targetRuns != null && inn2
      ? inn2.total >= input.targetRuns
        ? bowlingTeam
        : battingTeam
      : rnd() < 0.5
        ? battingTeam
        : bowlingTeam;

  return {
    scorecard: {
      meta: {
        match_id: input.matchId,
        date: new Date().toISOString().slice(0, 10),
        venue: "Simulated",
        event_name: "Simulation preview",
        teams: [battingTeam, bowlingTeam],
        winner,
        overs_limit: oversLimit,
        dls_applied: false,
      },
      innings: inningsRecord,
    },
    finalPTeam0: finalP,
  };
}
