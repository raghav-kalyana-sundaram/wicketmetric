/**
 * Single-match batting analytics (10-pillar framework) from scorecard ball-by-ball data only.
 *
 * - ASR: phase-adjusted vs same-innings phase baselines (everyone in that innings).
 * - BDAR: runs weighted by in-match bowler economy (stingier bowlers up-weight).
 * - Pressure: chase only, when target_runs is set on the innings.
 */

import type { BattingLine, Innings } from "@/components/scorecard/scorecardTypes";
import { buildInningsTimeline, sortKeyOverBall } from "@/lib/scorecardDetailHelpers";

export const MIN_BALLS_BAT_FRAMEWORK = 5;

type Phase = "powerplay" | "middle" | "death";

function phaseFromOver(over: number | null | undefined): Phase {
  const o = over ?? 0;
  if (o < 6) return "powerplay";
  if (o < 16) return "middle";
  return "death";
}

function isBatterBall(d: {
  is_wide?: boolean | null;
  is_batter_ball?: boolean | null;
}): boolean {
  if (d.is_wide) return false;
  return d.is_batter_ball !== false;
}

type PhaseBucket = {
  balls: number;
  runs: number;
  dots: number;
  boundaries: number;
  onesTwos: number;
};

function emptyBucket(): PhaseBucket {
  return { balls: 0, runs: 0, dots: 0, boundaries: 0, onesTwos: 0 };
}

function addToBucket(b: PhaseBucket, br: number): void {
  b.balls += 1;
  b.runs += br;
  if (br === 0) b.dots += 1;
  if (br === 4 || br === 6) b.boundaries += 1;
  if (br === 1 || br === 2) b.onesTwos += 1;
}

function bucketRpb(b: PhaseBucket): number {
  return b.balls > 0 ? b.runs / b.balls : 0;
}

function bucketDotPct(b: PhaseBucket): number {
  return b.balls > 0 ? b.dots / b.balls : 0;
}

function bucketBoundPct(b: PhaseBucket): number {
  return b.balls > 0 ? b.boundaries / b.balls : 0;
}

function bucketRotPct(b: PhaseBucket): number {
  return b.balls > 0 ? b.onesTwos / b.balls : 0;
}

function legalBallContextByKey(inn: Innings): Map<string, { before: number; total: number }> {
  const timeline = buildInningsTimeline(inn.bowling ?? []);
  const sorted = [...timeline].sort(
    (a, b) => sortKeyOverBall(a.over, a.ball_idx) - sortKeyOverBall(b.over, b.ball_idx),
  );
  const m = new Map<string, { before: number; total: number }>();
  let legalBefore = 0;
  for (const d of sorted) {
    const key = `${d.over ?? 0}:${d.ball_idx ?? 0}`;
    const isLeg = d.is_legal !== false && !d.is_wide && !d.is_noball;
    m.set(key, { before: legalBefore, total: 0 });
    if (isLeg) legalBefore += 1;
  }
  const total = legalBefore;
  for (const v of m.values()) v.total = total;
  return m;
}

function collectInningsPhaseBuckets(inn: Innings): Record<Phase, PhaseBucket> {
  const out: Record<Phase, PhaseBucket> = {
    powerplay: emptyBucket(),
    middle: emptyBucket(),
    death: emptyBucket(),
  };
  for (const line of inn.batting ?? []) {
    for (const d of line.deliveries ?? []) {
      if (!isBatterBall(d)) continue;
      const br = Number(d.batter_runs ?? 0);
      const ph = (d.phase as Phase | undefined) ?? phaseFromOver(d.over);
      if (ph !== "powerplay" && ph !== "middle" && ph !== "death") continue;
      addToBucket(out[ph], br);
    }
  }
  return out;
}

function bowlerRpbMap(inn: Innings): Map<string, number> {
  const m = new Map<string, number>();
  for (const b of inn.bowling ?? []) {
    const id = b.bowler_id != null ? String(b.bowler_id) : "";
    const balls = Number(b.balls ?? 0);
    const runs = Number(b.runs_conceded ?? 0);
    if (!id || balls < 1) continue;
    m.set(id, runs / balls);
  }
  return m;
}

export type BattingFrameworkMetrics = {
  playerId: string;
  name: string;
  balls: number;
  runs: number;
  asrIndex: number | null;
  rpb: number | null;
  dotPct: number | null;
  boundaryPct: number | null;
  ballsPerDismissal: number | null;
  dismissed: boolean;
  powerplayScore: number | null;
  middleScore: number | null;
  deathScore: number | null;
  pressureIndex: number | null;
  bdar: number | null;
  cbr: number | null;
};

const PHASE_MIN_BALLS = 3;

function phaseScorePlayerVsPar(
  player: PhaseBucket,
  par: PhaseBucket,
  mode: "powerplay" | "middle" | "death",
): number | null {
  if (player.balls < PHASE_MIN_BALLS) return null;
  const pRpb = bucketRpb(player);
  const parRpb = Math.max(bucketRpb(par), 0.08);
  const srPart = 100 * (pRpb / parRpb);

  if (mode === "powerplay") {
    const pB = bucketBoundPct(player);
    const parB = Math.max(bucketBoundPct(par), 0.02);
    const bPart = 100 * (pB / parB);
    return Math.min(160, (srPart + bPart) / 2);
  }
  if (mode === "middle") {
    const pDot = bucketDotPct(player);
    const parDot = Math.max(bucketDotPct(par), 0.02);
    const dotPart = 100 * (parDot / Math.max(pDot, 0.02));
    const rotPart =
      100 * (bucketRotPct(player) / Math.max(bucketRotPct(par), 0.04));
    return Math.min(160, (dotPart * 0.5 + rotPart * 0.5));
  }
  const pB = bucketBoundPct(player);
  const parB = Math.max(bucketBoundPct(par), 0.03);
  const bPart = 100 * (pB / parB);
  return Math.min(160, (srPart * 0.55 + bPart * 0.45));
}

type DeliveryTagged = NonNullable<BattingLine["deliveries"]>[number] & {
  _innKey: string;
  _inn: Innings;
};

function median(nums: number[]): number {
  if (nums.length === 0) return 1;
  const s = [...nums].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)]!;
}

function buildRowsFromAgg(
  pid: string,
  name: string,
  deliveries: DeliveryTagged[],
  dismissed: boolean,
  phaseParByInn: Map<string, Record<Phase, PhaseBucket>>,
  legalByInn: Map<string, Map<string, { before: number; total: number }>>,
  bowlerRpbByInn: Map<string, Map<string, number>>,
  medianByInn: Map<string, number>,
): BattingFrameworkMetrics | null {
  let expRuns = 0;
  let actualRuns = 0;
  let faceBalls = 0;
  let dots = 0;
  let boundaries = 0;
  let bdarSum = 0;
  let pressureW = 0;
  let pressureAcc = 0;

  const playerPhase: Record<Phase, PhaseBucket> = {
    powerplay: emptyBucket(),
    middle: emptyBucket(),
    death: emptyBucket(),
  };

  const mergePar: Record<Phase, PhaseBucket> = {
    powerplay: emptyBucket(),
    middle: emptyBucket(),
    death: emptyBucket(),
  };
  for (const pb of phaseParByInn.values()) {
    for (const ph of ["powerplay", "middle", "death"] as const) {
      mergePar[ph].balls += pb[ph].balls;
      mergePar[ph].runs += pb[ph].runs;
      mergePar[ph].dots += pb[ph].dots;
      mergePar[ph].boundaries += pb[ph].boundaries;
      mergePar[ph].onesTwos += pb[ph].onesTwos;
    }
  }

  for (const d of deliveries) {
    if (!isBatterBall(d)) continue;
    const br = Number(d.batter_runs ?? 0);
    const ph = (d.phase as Phase) ?? phaseFromOver(d.over);
    const innKey = d._innKey;
    const innPar = phaseParByInn.get(innKey);
    if (
      innPar &&
      (ph === "powerplay" || ph === "middle" || ph === "death")
    ) {
      const parRpb = Math.max(bucketRpb(innPar[ph]), 0.06);
      expRuns += parRpb;
      actualRuns += br;
      addToBucket(playerPhase[ph], br);
    }
    faceBalls += 1;
    if (br === 0) dots += 1;
    if (br === 4 || br === 6) boundaries += 1;

    const bMap = bowlerRpbByInn.get(innKey);
    const med = medianByInn.get(innKey) ?? 1;
    const bid = d.bowler_id != null ? String(d.bowler_id) : "";
    const bRpb = bid && bMap ? bMap.get(bid) ?? med : med;
    const w = med / Math.max(bRpb, 0.12);
    bdarSum += br * Math.min(w, 2.5);

    const inn = d._inn;
    const targetRuns =
      inn.target_runs != null && inn.target_runs > 0 ? inn.target_runs : null;
    const legalCtx = legalByInn.get(innKey);
    if (targetRuns != null && d.team_score_before != null && legalCtx) {
      const sc = Number(d.team_score_before);
      const need = Math.max(targetRuns - sc, 0);
      const k = `${d.over ?? 0}:${d.ball_idx ?? 0}`;
      const ctx = legalCtx.get(k);
      if (ctx && ctx.total > 0) {
        const left = Math.max(ctx.total - ctx.before, 1);
        const rpo = (6 * need) / left;
        if (rpo >= 6) {
          const intensity = Math.min((rpo - 6) / 8, 1);
          const srBall = br * 100;
          const expected = Math.max(rpo, 6);
          pressureAcc += (srBall / expected) * (0.35 + 0.65 * intensity);
          pressureW += 1;
        }
      }
    }
  }

  if (faceBalls < MIN_BALLS_BAT_FRAMEWORK) return null;

  const asrIndex = expRuns > 1e-6 ? (actualRuns / expRuns) * 100 : null;
  const rpb = faceBalls > 0 ? actualRuns / faceBalls : null;
  const dotPct = faceBalls > 0 ? dots / faceBalls : null;
  const boundaryPct = faceBalls > 0 ? boundaries / faceBalls : null;
  const ballsPerDismissal = dismissed && faceBalls > 0 ? faceBalls : null;

  const powerplayScore = phaseScorePlayerVsPar(
    playerPhase.powerplay,
    mergePar.powerplay,
    "powerplay",
  );
  const middleScore = phaseScorePlayerVsPar(
    playerPhase.middle,
    mergePar.middle,
    "middle",
  );
  const deathScore = phaseScorePlayerVsPar(
    playerPhase.death,
    mergePar.death,
    "death",
  );

  const pressureIndex =
    pressureW > 0 ? Math.min(130, (pressureAcc / pressureW) * 100) : null;

  const bdar = faceBalls > 0 ? bdarSum / faceBalls : null;

  return {
    playerId: pid,
    name,
    balls: faceBalls,
    runs: actualRuns,
    asrIndex,
    rpb,
    dotPct,
    boundaryPct,
    ballsPerDismissal,
    dismissed,
    powerplayScore,
    middleScore,
    deathScore,
    pressureIndex,
    bdar,
    cbr: null,
  };
}

function toPct(x: number | null, digits = 1): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function formatFrameworkCell(
  key: keyof BattingFrameworkMetrics,
  row: BattingFrameworkMetrics,
): string {
  switch (key) {
    case "asrIndex":
      return row.asrIndex != null ? row.asrIndex.toFixed(1) : "—";
    case "rpb":
      return row.rpb != null ? row.rpb.toFixed(3) : "—";
    case "dotPct":
      return toPct(row.dotPct);
    case "boundaryPct":
      return toPct(row.boundaryPct);
    case "ballsPerDismissal":
      return row.ballsPerDismissal != null
        ? row.ballsPerDismissal.toFixed(0)
        : "NR";
    case "powerplayScore":
    case "middleScore":
    case "deathScore":
      return row[key] != null ? (row[key] as number).toFixed(0) : "—";
    case "pressureIndex":
      return row.pressureIndex != null ? row.pressureIndex.toFixed(0) : "—";
    case "bdar":
      return row.bdar != null ? row.bdar.toFixed(3) : "—";
    case "cbr":
      return row.cbr != null ? row.cbr.toFixed(1) : "—";
    default:
      return "—";
  }
}

function minMaxNorm(values: number[]): number[] {
  if (values.length === 0) return [];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (hi <= lo) return values.map(() => 50);
  return values.map((v) => (100 * (v - lo)) / (hi - lo));
}

/** One normalized value per row; 50 when missing. */
function normForRows(
  rows: BattingFrameworkMetrics[],
  getter: (r: BattingFrameworkMetrics) => number | null | undefined,
): number[] {
  const raw = rows.map((r) => {
    const v = getter(r);
    return v != null && !Number.isNaN(v) ? v : null;
  });
  const vals = raw.filter((v): v is number => v != null);
  const scaled = minMaxNorm(vals);
  let j = 0;
  return raw.map((v) => (v != null ? scaled[j++]! : 50));
}

export function computeBattingFrameworkRows(
  inningsList: [string, Innings][],
): BattingFrameworkMetrics[] {
  const phaseParByInn = new Map<string, Record<Phase, PhaseBucket>>();
  const legalByInn = new Map<string, Map<string, { before: number; total: number }>>();
  const bowlerRpbByInn = new Map<string, Map<string, number>>();
  const medianByInn = new Map<string, number>();

  for (const [innKey, inn] of inningsList) {
    phaseParByInn.set(innKey, collectInningsPhaseBuckets(inn));
    legalByInn.set(innKey, legalBallContextByKey(inn));
    const bm = bowlerRpbMap(inn);
    bowlerRpbByInn.set(innKey, bm);
    medianByInn.set(innKey, median([...bm.values()]));
  }

  const byPlayer = new Map<
    string,
    { name: string; deliveries: DeliveryTagged[]; dismissed: boolean }
  >();

  for (const [innKey, inn] of inningsList) {
    for (const line of inn.batting ?? []) {
      const id = line.batter_id != null ? String(line.batter_id) : "";
      if (!id) continue;
      const cur = byPlayer.get(id) ?? {
        name: String(line.batter ?? id),
        deliveries: [],
        dismissed: false,
      };
      cur.name = String(line.batter ?? cur.name);
      if (line.dismissal_kind && String(line.dismissal_kind).trim()) {
        cur.dismissed = true;
      }
      for (const d of line.deliveries ?? []) {
        cur.deliveries.push({
          ...d,
          _innKey: innKey,
          _inn: inn,
        });
      }
      byPlayer.set(id, cur);
    }
  }

  const rows: BattingFrameworkMetrics[] = [];
  for (const [pid, agg] of byPlayer) {
    const row = buildRowsFromAgg(
      pid,
      agg.name,
      agg.deliveries,
      agg.dismissed,
      phaseParByInn,
      legalByInn,
      bowlerRpbByInn,
      medianByInn,
    );
    if (row) rows.push(row);
  }

  const phaseAvgs: (number | null)[] = rows.map((r) => {
    const xs = [r.powerplayScore, r.middleScore, r.deathScore].filter(
      (x): x is number => x != null,
    );
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  });

  const asrNorm = normForRows(rows, (r) => r.asrIndex);
  const rpbNorm = normForRows(rows, (r) => r.rpb);
  const bNorm = normForRows(rows, (r) => r.boundaryPct);
  const dotRaw = normForRows(rows, (r) => r.dotPct);
  const dotNorm = dotRaw.map((t) => 100 - t);
  const bpdNorm = normForRows(rows, (r) => r.ballsPerDismissal);

  const phNormReal = (() => {
    const vals = phaseAvgs.filter((v): v is number => v != null);
    const scaled = minMaxNorm(vals);
    let j = 0;
    return phaseAvgs.map((v) => (v != null ? scaled[j++]! : 50));
  })();

  const prNorm = normForRows(rows, (r) => r.pressureIndex);
  const bdarNorm = normForRows(rows, (r) => r.bdar);

  rows.forEach((row, idx) => {
    row.cbr =
      0.2 * asrNorm[idx]! +
      0.1 * bNorm[idx]! +
      0.1 * dotNorm[idx]! +
      0.1 * bpdNorm[idx]! +
      0.15 * phNormReal[idx]! +
      0.15 * prNorm[idx]! +
      0.1 * bdarNorm[idx]! +
      0.1 * rpbNorm[idx]!;
    row.cbr = Math.round(row.cbr * 10) / 10;
  });

  rows.sort((a, b) => (b.cbr ?? 0) - (a.cbr ?? 0));
  return rows;
}
