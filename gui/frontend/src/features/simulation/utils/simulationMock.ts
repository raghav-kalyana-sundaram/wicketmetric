/**
 * Deterministic mock simulation output for the Simulation Hub.
 * Replace with API mapping later; keep the result shape stable.
 */

import type { PlayerSummary } from "@/api/types";
import type { Scorecard } from "@/components/scorecard/scorecardTypes";
import type { SimulationScope } from "../types";
import {
  buildSimulatedScorecard,
  type InningsPhase,
} from "./buildSimulatedScorecard";

export interface SimulationRunPayload {
  format: string;
  scope: SimulationScope;
  overNumber: number;
  tournamentLabel: string;
  battingTeam: string;
  bowlingTeam: string;
  iterations: number;
  striker: PlayerSummary | null;
  nonStriker: PlayerSummary | null;
  bowler: PlayerSummary | null;
  inningsPhase: InningsPhase;
  targetRuns: number | null;
  injectState: boolean;
  injectRuns: number;
  injectWickets: number;
  injectLegalBalls: number;
  dismissedBatters: PlayerSummary[];
  battingXI: (PlayerSummary | null)[];
  bowlingXI: (PlayerSummary | null)[];
  contextRuns: number;
  contextWickets: number;
  contextLegalBalls: number;
}

export interface WinShareRow {
  name: string;
  pct: number;
  fillKey: "a" | "b" | "tie";
}

export interface ProjectionRow {
  playerId?: string;
  name: string;
  median: number;
  low: number;
  high: number;
}

export type BallOutcomeKind =
  | "dot"
  | "single"
  | "boundary"
  | "six"
  | "wicket"
  | "extra";

export interface BallLogRow {
  over: number;
  ballInOver: number;
  strikerName: string;
  bowlerName: string;
  runs: number;
  outcome: BallOutcomeKind;
  label: string;
}

export interface SimulationResult {
  winShares: WinShareRow[];
  topScorers: ProjectionRow[];
  topWicketTakers: ProjectionRow[];
  ballLog: BallLogRow[];
  iterationsUsed: number;
  /** Populated for full_match with complete XIs */
  scorecard?: Scorecard | null;
}

function hashSeed(parts: string[]): number {
  const s = parts.join("|");
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed: number) {
  return function next() {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export function computeSimulationDelayMs(iterations: number): number {
  const base = 900;
  const scaled = Math.min(iterations, 5000) * 0.12;
  return Math.min(2500, base + scaled);
}

function fullXi(
  xs: (PlayerSummary | null)[],
): PlayerSummary[] | null {
  if (xs.length < 11) return null;
  const out: PlayerSummary[] = [];
  for (let i = 0; i < 11; i++) {
    if (!xs[i]) return null;
    out.push(xs[i]!);
  }
  return out;
}

export function runMockSimulation(input: SimulationRunPayload): SimulationResult {
  const seed = hashSeed([
    input.format,
    input.scope,
    String(input.overNumber),
    input.tournamentLabel,
    input.battingTeam,
    input.bowlingTeam,
    String(input.iterations),
    input.striker?.id ?? "",
    input.nonStriker?.id ?? "",
    input.bowler?.id ?? "",
    input.inningsPhase,
    String(input.targetRuns ?? ""),
    String(input.injectState),
    ...input.battingXI.map((p) => p?.id ?? ""),
    ...input.bowlingXI.map((p) => p?.id ?? ""),
  ]);
  const rnd = mulberry32(seed);

  const batting = input.battingTeam.trim() || "Batting side";
  const bowling = input.bowlingTeam.trim() || "Bowling side";

  let scorecard: Scorecard | null = null;
  let pTeam0 = 0.42 + rnd() * 0.28 + (batting.length % 7) * 0.01;
  if (input.scope === "specific_over") pTeam0 += 0.02;
  if (input.scope === "entire_tournament") pTeam0 += (rnd() - 0.5) * 0.06;
  pTeam0 = clamp(pTeam0, 0.18, 0.82);

  const batXI = fullXi(input.battingXI);
  const bowlXI = fullXi(input.bowlingXI);

  if (input.scope === "full_match" && batXI && bowlXI) {
    const mid = `sim-${seed.toString(16)}`;
    const built = buildSimulatedScorecard({
      matchId: mid,
      battingTeam: batting,
      bowlingTeam: bowling,
      oversLimit: 20,
      battingXI: batXI,
      bowlingXI: bowlXI,
      inningsPhase: input.inningsPhase,
      targetRuns:
        input.inningsPhase === "chase" && input.targetRuns != null
          ? Math.max(1, input.targetRuns)
          : null,
      injectFirstInnings: input.injectState,
      injectRuns: Math.max(0, input.injectRuns),
      injectWickets: clamp(input.injectWickets, 0, 10),
      injectLegalBalls: clamp(input.injectLegalBalls, 0, 119),
      injectStriker: input.injectState ? input.striker : null,
      injectNonStriker: input.injectState ? input.nonStriker : null,
      dismissedBatters: input.dismissedBatters,
      seed,
    });
    scorecard = built.scorecard;
    pTeam0 = built.finalPTeam0;
  }

  const tie = clamp(0.02 + rnd() * 0.04, 0.01, 0.08);
  const rest = 1 - tie;
  const batPct = round1(pTeam0 * rest * 100);
  const bowlPct = round1((1 - pTeam0) * rest * 100);
  const tiePct = round1(tie * 100);
  const winShares: WinShareRow[] = [
    { name: batting, pct: batPct, fillKey: "a" },
    { name: bowling, pct: bowlPct, fillKey: "b" },
  ];
  if (tiePct >= 0.5) {
    winShares.push({ name: "No result / tie", pct: tiePct, fillKey: "tie" });
  }

  const topScorers: ProjectionRow[] = [];
  const topWicketTakers: ProjectionRow[] = [];

  if (input.scope === "specific_over" && input.striker && input.nonStriker) {
    const mkBat = (p: PlayerSummary, base: number) => {
      const med = clamp(base + rnd() * 8 - 4, 0, 36);
      const spread = 4 + rnd() * 8;
      return {
        playerId: p.id,
        name: p.name,
        median: round1(med),
        low: round1(Math.max(0, med - spread)),
        high: round1(med + spread + rnd() * 6),
      };
    };
    topScorers.push(mkBat(input.striker, 8 + (input.overNumber % 6)));
    topScorers.push(mkBat(input.nonStriker, 6 + (input.overNumber % 5)));
  } else if (batXI) {
    for (const p of batXI.slice(0, 5)) {
      const med = clamp(8 + rnd() * 42, 0, 80);
      const spread = 8 + rnd() * 14;
      topScorers.push({
        playerId: p.id,
        name: p.name,
        median: round1(med),
        low: round1(Math.max(0, med - spread)),
        high: round1(med + spread),
      });
    }
  } else {
    const labels = [
      `${batting} — top order`,
      `${batting} — middle`,
      `${batting} — finisher`,
    ];
    for (const name of labels) {
      const med = clamp(18 + rnd() * 45, 8, 72);
      const spread = 10 + rnd() * 18;
      topScorers.push({
        name,
        median: round1(med),
        low: round1(Math.max(0, med - spread)),
        high: round1(med + spread),
      });
    }
  }

  if (input.scope === "specific_over" && input.bowler) {
    const med = clamp(0.4 + rnd() * 1.2, 0, 3);
    const spread = 0.35 + rnd() * 0.5;
    topWicketTakers.push({
      playerId: input.bowler.id,
      name: input.bowler.name,
      median: round1(med),
      low: round1(Math.max(0, med - spread)),
      high: round1(med + spread + 0.4),
    });
  }
  if (bowlXI) {
    for (const p of bowlXI.slice(0, 4)) {
      if (topWicketTakers.some((t) => t.playerId === p.id)) continue;
      const med = clamp(0.8 + rnd() * 2.4, 0, 5);
      const spread = 0.5 + rnd();
      topWicketTakers.push({
        playerId: p.id,
        name: p.name,
        median: round1(med),
        low: round1(Math.max(0, med - spread)),
        high: round1(med + spread),
      });
    }
  } else {
    const bowlLabels =
      input.scope === "specific_over" && input.bowler
        ? [`${bowling} — enforcer`, `${bowling} — spinner`]
        : [`${bowling} — pace`, `${bowling} — spin`, `${bowling} — death`];
    for (const name of bowlLabels) {
      if (topWicketTakers.length >= 4) break;
      const med = clamp(1.2 + rnd() * 2.8, 0.5, 5);
      const spread = 0.6 + rnd();
      topWicketTakers.push({
        name,
        median: round1(med),
        low: round1(Math.max(0, med - spread)),
        high: round1(med + spread),
      });
    }
  }

  const strikerName = input.striker?.name ?? `${batting} batter`;
  const bowlerName = input.bowler?.name ?? `${bowling} bowler`;

  const ballLog: BallLogRow[] = [];
  const outcomes: BallOutcomeKind[] = [
    "dot",
    "single",
    "single",
    "boundary",
    "six",
    "wicket",
    "extra",
  ];

  const pushBall = (
    over: number,
    ballInOver: number,
    outcome: BallOutcomeKind,
  ) => {
    let runs = 0;
    let label = "0";
    switch (outcome) {
      case "dot":
        runs = 0;
        label = "0";
        break;
      case "single":
        runs = 1;
        label = "1";
        break;
      case "boundary":
        runs = 4;
        label = "4";
        break;
      case "six":
        runs = 6;
        label = "6";
        break;
      case "wicket":
        runs = 0;
        label = "W";
        break;
      case "extra":
        runs = 1;
        label = "1wd";
        break;
      default:
        break;
    }
    ballLog.push({
      over,
      ballInOver,
      strikerName,
      bowlerName,
      runs,
      outcome,
      label,
    });
  };

  if (input.scope === "specific_over") {
    const o = clamp(input.overNumber, 1, 20);
    for (let b = 1; b <= 6; b++) {
      const oKind = outcomes[Math.floor(rnd() * outcomes.length)]!;
      pushBall(o, b, oKind);
    }
  } else if (input.scope === "full_match") {
    let over = 12 + Math.floor(rnd() * 6);
    const numOvers = 6;
    for (let oi = 0; oi < numOvers; oi++) {
      for (let b = 1; b <= 6; b++) {
        const oKind = outcomes[Math.floor(rnd() * outcomes.length)]!;
        pushBall(over + oi, b, oKind);
      }
    }
  } else {
    const start = 3 + Math.floor(rnd() * 5);
    for (let oi = 0; oi < 2; oi++) {
      for (let b = 1; b <= 6; b++) {
        const oKind = outcomes[Math.floor(rnd() * outcomes.length)]!;
        pushBall(start + oi, b, oKind);
      }
    }
  }

  return {
    winShares,
    topScorers,
    topWicketTakers,
    ballLog,
    iterationsUsed: input.iterations,
    scorecard: scorecard ?? undefined,
  };
}
