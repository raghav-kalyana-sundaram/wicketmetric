/**
 * Pure builders for scorecard visualisations (Manhattan, partnership timeline, worm).
 */

import type { Innings } from "@/components/scorecard/scorecardTypes";
import { buildInningsTimeline } from "@/lib/scorecardDetailHelpers";

export type ManhattanOverRow = {
  over: number;
  runs: number;
  wicketsInOver: number;
};

export type ManhattanChartRow = ManhattanOverRow & {
  /** Y positions for wicket dots in this over (Recharts lines use w1..w6) */
  w1: number | null;
  w2: number | null;
  w3: number | null;
  w4: number | null;
  w5: number | null;
  w6: number | null;
};

export function buildManhattanChartRows(inn: Innings): ManhattanChartRow[] {
  const timeline = buildInningsTimeline(inn.bowling ?? []);
  const perOver = new Map<number, { runs: number; wickets: number }>();
  for (const ball of timeline) {
    const overOne = Number(ball.over ?? 0) + 1;
    const slot = perOver.get(overOne) ?? { runs: 0, wickets: 0 };
    slot.runs += Number(ball.total_runs ?? 0);
    if (ball.is_wicket) slot.wickets += 1;
    perOver.set(overOne, slot);
  }
  const overs = [...perOver.keys()].sort((a, b) => a - b);
  const bars: ManhattanOverRow[] = overs.map((over) => {
    const s = perOver.get(over)!;
    return { over, runs: s.runs, wicketsInOver: s.wickets };
  });
  const ysByOver = new Map<number, number[]>();
  for (const row of bars) {
    const n = row.wicketsInOver;
    const ys: number[] = [];
    for (let i = 0; i < n; i += 1) {
      ys.push(row.runs + 1.2 + i * 1.4);
    }
    ysByOver.set(row.over, ys);
  }
  return bars.map((b) => {
    const ys = ysByOver.get(b.over) ?? [];
    return {
      ...b,
      w1: ys[0] ?? null,
      w2: ys[1] ?? null,
      w3: ys[2] ?? null,
      w4: ys[3] ?? null,
      w5: ys[4] ?? null,
      w6: ys[5] ?? null,
    };
  });
}

export type PartnershipStandDetail = {
  order: number;
  pair: string;
  batterAId: string;
  batterBId: string;
  runsA: number;
  runsB: number;
  extras: number;
  runs: number;
  balls: number;
  wicketOver: string | null;
  /** Team total at end of this stand */
  cumScoreAtEnd: number;
};

function pairLabel(
  a: string,
  b: string,
  nameById: Map<string, string>,
): string {
  const na = nameById.get(a) ?? a;
  const nb = nameById.get(b) ?? b;
  return `${na} / ${nb}`;
}

/**
 * Chronological partnership stands with per-batter runs (off bat) and extras in the stand.
 */
export function buildPartnershipStandTimeline(
  inn: Innings,
  nameById: Map<string, string>,
): PartnershipStandDetail[] {
  const timeline = buildInningsTimeline(inn.bowling ?? []);
  if (timeline.length === 0) return [];

  const stands: PartnershipStandDetail[] = [];
  let activePair: [string, string] | null = null;
  let partnershipRuns = 0;
  let partnershipBalls = 0;
  const runsById = new Map<string, number>();
  let partnershipExtras = 0;
  let pendingOutId: string | null = null;
  let teamCumulative = 0;
  let order = 0;

  const flush = (wicketOver: string | null) => {
    if (!activePair) return;
    if (partnershipRuns <= 0 && partnershipBalls <= 0) return;
    const [idA, idB] = activePair;
    const runsA = runsById.get(idA) ?? 0;
    const runsB = idA === idB ? 0 : (runsById.get(idB) ?? 0);
    order += 1;
    stands.push({
      order,
      pair: pairLabel(idA, idB, nameById),
      batterAId: idA,
      batterBId: idB,
      runsA,
      runsB,
      extras: Math.max(0, partnershipExtras),
      runs: partnershipRuns,
      balls: partnershipBalls,
      wicketOver,
      cumScoreAtEnd: teamCumulative,
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
        activePair =
          activePair[0] === pendingOutId
            ? [batterId, activePair[1]]
            : [activePair[0], batterId];
      } else {
        flush(null);
        activePair = [activePair[1], batterId];
        partnershipRuns = 0;
        partnershipBalls = 0;
        runsById.clear();
        partnershipExtras = 0;
      }
    }

    const tr = Number(ball.total_runs ?? 0);
    const br = Number(ball.batter_runs ?? 0);
    partnershipRuns += tr;
    teamCumulative += tr;
    runsById.set(batterId, (runsById.get(batterId) ?? 0) + br);
    partnershipExtras += Math.max(0, tr - br);
    if (ball.is_legal) partnershipBalls += 1;

    if (ball.is_wicket && ball.player_out_id && activePair.includes(String(ball.player_out_id))) {
      const overText = `${ball.over ?? "?"}.${ball.ball_idx ?? "?"}`;
      flush(overText);
      pendingOutId = String(ball.player_out_id);
      partnershipRuns = 0;
      partnershipBalls = 0;
      runsById.clear();
      partnershipExtras = 0;
    } else {
      pendingOutId = null;
    }
  }
  flush(null);
  return stands;
}

export type WormOverRow = {
  over: number;
  cum1: number;
  cum2: number;
};

export function buildWormRows(
  firstInningsOvers: Map<number, { runs: number }>,
  secondInningsOvers: Map<number, { runs: number }>,
): WormOverRow[] {
  const maxOver = Math.max(
    firstInningsOvers.size ? Math.max(...firstInningsOvers.keys()) : 0,
    secondInningsOvers.size ? Math.max(...secondInningsOvers.keys()) : 0,
  );
  let c1 = 0;
  let c2 = 0;
  const rows: WormOverRow[] = [];
  for (let over = 1; over <= maxOver; over += 1) {
    c1 += firstInningsOvers.get(over)?.runs ?? 0;
    c2 += secondInningsOvers.get(over)?.runs ?? 0;
    rows.push({ over, cum1: c1, cum2: c2 });
  }
  return rows;
}

export function oversRunMapFromInnings(inn: Innings): Map<number, { runs: number }> {
  const timeline = buildInningsTimeline(inn.bowling ?? []);
  const perOver = new Map<number, { runs: number }>();
  for (const ball of timeline) {
    const overOne = Number(ball.over ?? 0) + 1;
    const slot = perOver.get(overOne) ?? { runs: 0 };
    slot.runs += Number(ball.total_runs ?? 0);
    perOver.set(overOne, slot);
  }
  return perOver;
}
