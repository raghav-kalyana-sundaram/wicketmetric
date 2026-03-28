/**
 * Match impact tables (batting / bowling / combined) from scorecard innings data.
 */

import type { Innings } from "@/components/scorecard/scorecardTypes";

export const MIN_BALLS_BAT_IMPACT = 5;
export const MIN_BALLS_BOWL_IMPACT = 6;

type BowlAggLine = { wickets: number; runsConceded: number; balls: number };

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

  /** Linear in wickets (was w² — too steep vs +1–2 wickets). ~3w scale matches old formula. */
  const BOWL_SPELL_K = 18.0;
  const RUNS_SAVED_K = 2.35;

  if (wickets > 0) {
    const spellCore = (BOWL_SPELL_K * wickets * balls) / safeRuns;
    return spellCore + RUNS_SAVED_K * runsSaved;
  }

  return RUNS_SAVED_K * runsSaved;
}

export type BattingImpactRow = {
  playerId: string;
  name: string;
  runs: number;
  balls: number;
  strikeRate: number | null;
  impact: number;
};

export type BowlingImpactRow = {
  playerId: string;
  name: string;
  wickets: number;
  runsConceded: number;
  balls: number;
  economy: number | null;
  impact: number;
};

export type CombinedImpactRow = {
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

export function formatCombinedSummary(r: CombinedImpactRow): string {
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

export function computeMatchImpact(inningsList: [string, Innings][]): {
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

/** Row subset: match column label for tables (teams vs event / venue / id). */
export type ScorecardMatchLabelFields = {
  teams?: string[] | null;
  event_name?: string | null;
  venue?: string | null;
  match_id: string;
};

export function formatScorecardMatchLabel(r: ScorecardMatchLabelFields): string {
  const teams = r.teams;
  if (Array.isArray(teams)) {
    const names = teams.map((t) => String(t).trim()).filter(Boolean);
    if (names.length >= 2) {
      return `${names[0]} vs ${names[1]}`;
    }
    if (names.length === 1) {
      return names[0];
    }
  }
  const event = (r.event_name && String(r.event_name).trim()) || "";
  const venue = (r.venue && String(r.venue).trim()) || "";
  if (event && venue) {
    return `${event} · ${venue}`;
  }
  return event || venue || r.match_id;
}
