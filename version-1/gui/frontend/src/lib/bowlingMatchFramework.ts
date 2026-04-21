/**
 * Single-match bowling analytics (10-pillar framework) from scorecard ball-by-ball data only.
 *
 * False-shot / edge data are not in standard Cricsheet JSON — we use a threat proxy:
 * wicket (bowler-credited) OR dot off the bat (0 batter runs on a legal ball).
 */

import type { BowlingDelivery, Innings } from "@/components/scorecard/scorecardTypes";
import { buildInningsTimeline, sortKeyOverBall } from "@/lib/scorecardDetailHelpers";

export const MIN_BALLS_BOWL_FRAMEWORK = 6;

type Phase = "powerplay" | "middle" | "death";

const NON_BOWLER_WICKET_PHRASES = [
  "run out",
  "retired",
  "obstructing",
  "hit the ball twice",
  "timed out",
];

function phaseFromOver(over: number | null | undefined): Phase {
  const o = over ?? 0;
  if (o < 6) return "powerplay";
  if (o < 16) return "middle";
  return "death";
}

function isLegalBowl(d: BowlingDelivery): boolean {
  if (d.is_wide) return false;
  if (d.is_noball) return false;
  return d.is_legal !== false;
}

function isBowlerCreditedWicket(d: BowlingDelivery): boolean {
  if (!d.is_wicket) return false;
  const k = String(d.wicket_kind ?? "")
    .toLowerCase()
    .replace(/_/g, " ");
  return !NON_BOWLER_WICKET_PHRASES.some((p) => k.includes(p));
}

type BowlPhaseBucket = {
  balls: number;
  runs: number;
  dots: number;
  boundaries: number;
  onesTwos: number;
};

function emptyBowlBucket(): BowlPhaseBucket {
  return { balls: 0, runs: 0, dots: 0, boundaries: 0, onesTwos: 0 };
}

function addBowlBall(b: BowlPhaseBucket, d: BowlingDelivery): void {
  const tr = Number(d.total_runs ?? 0);
  const br = Number(d.batter_runs ?? 0);
  b.balls += 1;
  b.runs += tr;
  if (tr === 0 && !d.is_wicket) b.dots += 1;
  if (br === 4 || br === 6) b.boundaries += 1;
  if (br === 1 || br === 2) b.onesTwos += 1;
}

function bowlBucketRpb(b: BowlPhaseBucket): number {
  return b.balls > 0 ? b.runs / b.balls : 0;
}

function bowlBucketDotPct(b: BowlPhaseBucket): number {
  return b.balls > 0 ? b.dots / b.balls : 0;
}

function bowlBucketBoundPct(b: BowlPhaseBucket): number {
  return b.balls > 0 ? b.boundaries / b.balls : 0;
}

function bowlBucketRotPct(b: BowlPhaseBucket): number {
  return b.balls > 0 ? b.onesTwos / b.balls : 0;
}

function collectBowlingPhasePar(inn: Innings): Record<Phase, BowlPhaseBucket> {
  const out: Record<Phase, BowlPhaseBucket> = {
    powerplay: emptyBowlBucket(),
    middle: emptyBowlBucket(),
    death: emptyBowlBucket(),
  };
  for (const line of inn.bowling ?? []) {
    for (const d of line.deliveries ?? []) {
      if (!isLegalBowl(d)) continue;
      const ph = (d.phase as Phase | undefined) ?? phaseFromOver(d.over);
      if (ph !== "powerplay" && ph !== "middle" && ph !== "death") continue;
      addBowlBall(out[ph], d);
    }
  }
  return out;
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
    const isLeg = isLegalBowl(d);
    m.set(key, { before: legalBefore, total: 0 });
    if (isLeg) legalBefore += 1;
  }
  const total = legalBefore;
  for (const v of m.values()) v.total = total;
  return m;
}

/** Batting team score before each ball (for chase pressure). */
function battingScoreBeforeByKey(inn: Innings): Map<string, number> {
  const timeline = buildInningsTimeline(inn.bowling ?? []);
  const sorted = [...timeline].sort(
    (a, b) => sortKeyOverBall(a.over, a.ball_idx) - sortKeyOverBall(b.over, b.ball_idx),
  );
  const m = new Map<string, number>();
  let score = 0;
  for (const d of sorted) {
    const key = `${d.over ?? 0}:${d.ball_idx ?? 0}`;
    m.set(key, score);
    score += Number(d.total_runs ?? 0);
  }
  return m;
}

function batterSrMap(inn: Innings): Map<string, number> {
  const m = new Map<string, number>();
  for (const b of inn.batting ?? []) {
    const id = b.batter_id != null ? String(b.batter_id) : "";
    if (!id) continue;
    const runs = Number(b.runs ?? 0);
    const balls = Number(b.balls ?? 0);
    if (balls < 1) continue;
    m.set(id, (runs / balls) * 100);
  }
  return m;
}

function median(nums: number[]): number {
  if (nums.length === 0) return 120;
  const s = [...nums].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)]!;
}

export type BowlingFrameworkMetrics = {
  playerId: string;
  name: string;
  balls: number;
  runs: number;
  wickets: number;
  /** 100 = par phase economy for balls bowled (higher = stingier). */
  aerIndex: number | null;
  /** Runs per legal ball conceded (lower better). */
  rpbConceded: number | null;
  dotPct: number | null;
  /** Proxy: wicket or 0 off bat on legal ball (no Cricsheet false-shot field). */
  falseShotProxyPct: number | null;
  wicketsPerBall: number | null;
  powerplayScore: number | null;
  middleScore: number | null;
  deathScore: number | null;
  pressureIndex: number | null;
  /** >100 = conceded less than phase×batter-quality expectation. */
  bqarIndex: number | null;
  cbrB: number | null;
};

const PHASE_MIN_BALLS = 3;

function phaseBowlScore(
  player: BowlPhaseBucket,
  par: BowlPhaseBucket,
  mode: "powerplay" | "middle" | "death",
): number | null {
  if (player.balls < PHASE_MIN_BALLS) return null;
  const pRpb = bowlBucketRpb(player);
  const parRpb = Math.max(bowlBucketRpb(par), 0.08);
  const econPart = 100 * (parRpb / Math.max(pRpb, 0.05));

  if (mode === "powerplay") {
    const pDot = bowlBucketDotPct(player);
    const parDot = Math.max(bowlBucketDotPct(par), 0.05);
    const dotPart = 100 * (pDot / parDot);
    return Math.min(160, (econPart + dotPart) / 2);
  }
  if (mode === "middle") {
    const pRot = bowlBucketRotPct(player);
    const parRot = Math.max(bowlBucketRotPct(par), 0.04);
    const rotPart = 100 * (parRot / Math.max(pRot, 0.02));
    return Math.min(160, (econPart * 0.55 + rotPart * 0.45));
  }
  const pB = bowlBucketBoundPct(player);
  const parB = Math.max(bowlBucketBoundPct(par), 0.03);
  const boundPart = 100 * (parB / Math.max(pB, 0.02));
  return Math.min(160, (econPart * 0.55 + boundPart * 0.45));
}

type BowlDelTagged = BowlingDelivery & { _innKey: string; _inn: Innings };

function mergeParBowling(
  phaseParByInn: Map<string, Record<Phase, BowlPhaseBucket>>,
): Record<Phase, BowlPhaseBucket> {
  const merge: Record<Phase, BowlPhaseBucket> = {
    powerplay: emptyBowlBucket(),
    middle: emptyBowlBucket(),
    death: emptyBowlBucket(),
  };
  for (const pb of phaseParByInn.values()) {
    for (const ph of ["powerplay", "middle", "death"] as const) {
      merge[ph].balls += pb[ph].balls;
      merge[ph].runs += pb[ph].runs;
      merge[ph].dots += pb[ph].dots;
      merge[ph].boundaries += pb[ph].boundaries;
      merge[ph].onesTwos += pb[ph].onesTwos;
    }
  }
  return merge;
}

function buildBowlerRow(
  pid: string,
  name: string,
  deliveries: BowlDelTagged[],
  phaseParByInn: Map<string, Record<Phase, BowlPhaseBucket>>,
  legalByInn: Map<string, Map<string, { before: number; total: number }>>,
  scoreBeforeByInn: Map<string, Map<string, number>>,
  batterSrByInn: Map<string, Map<string, number>>,
  medianSrByInn: Map<string, number>,
): BowlingFrameworkMetrics | null {
  let legalBalls = 0;
  let runs = 0;
  let wickets = 0;
  let expRunsPhase = 0;
  let expRunsBqar = 0;

  const playerPhase: Record<Phase, BowlPhaseBucket> = {
    powerplay: emptyBowlBucket(),
    middle: emptyBowlBucket(),
    death: emptyBowlBucket(),
  };

  let dots = 0;
  let threatBalls = 0;
  let pressureW = 0;
  let pressureAcc = 0;

  for (const d of deliveries) {
    if (!isLegalBowl(d)) continue;
    const tr = Number(d.total_runs ?? 0);
    const br = Number(d.batter_runs ?? 0);
    const ph = (d.phase as Phase) ?? phaseFromOver(d.over);
    const innKey = d._innKey;
    const inn = d._inn;

    legalBalls += 1;
    runs += tr;
    if (isBowlerCreditedWicket(d)) wickets += 1;

    const innPar = phaseParByInn.get(innKey);
    if (innPar && (ph === "powerplay" || ph === "middle" || ph === "death")) {
      expRunsPhase += Math.max(bowlBucketRpb(innPar[ph]), 0.06);
      addBowlBall(playerPhase[ph], d);
    }

    if (tr === 0 && !d.is_wicket) dots += 1;
    if (isBowlerCreditedWicket(d) || (br === 0 && !d.is_wicket)) {
      threatBalls += 1;
    }

    const refSr = medianSrByInn.get(innKey) ?? 120;
    const bid = d.batter_id != null ? String(d.batter_id) : "";
    const bSr = bid
      ? batterSrByInn.get(innKey)?.get(bid) ?? refSr
      : refSr;
    const qual = Math.max(0.75, Math.min(1.45, bSr / Math.max(refSr, 80)));
    if (innPar && (ph === "powerplay" || ph === "middle" || ph === "death")) {
      expRunsBqar += bowlBucketRpb(innPar[ph]) * qual;
    }

    const targetRuns =
      inn.target_runs != null && inn.target_runs > 0 ? inn.target_runs : null;
    const scoreMap = scoreBeforeByInn.get(innKey);
    const legalCtx = legalByInn.get(innKey);
    if (targetRuns != null && scoreMap && legalCtx) {
      const k = `${d.over ?? 0}:${d.ball_idx ?? 0}`;
      const sc = scoreMap.get(k);
      const ctx = legalCtx.get(k);
      if (sc != null && ctx && ctx.total > 0) {
        const need = Math.max(targetRuns - sc, 0);
        const left = Math.max(ctx.total - ctx.before, 1);
        const rpo = (6 * need) / left;
        if (rpo >= 8) {
          const intensity = Math.min((rpo - 8) / 8, 1);
          const rpbBall = tr;
          const needRpb = rpo / 6;
          pressureAcc +=
            (needRpb / Math.max(rpbBall, 0.08)) * (0.35 + 0.65 * intensity);
          pressureW += 1;
        }
      }
    }
  }

  if (legalBalls < MIN_BALLS_BOWL_FRAMEWORK) return null;

  const aerIndex =
    runs > 1e-6 ? (100 * expRunsPhase) / runs : null;
  const rpbConceded = runs / legalBalls;
  const dotPct = dots / legalBalls;
  const falseShotProxyPct = threatBalls / legalBalls;
  const wicketsPerBall = wickets / legalBalls;

  const mergePar = mergeParBowling(phaseParByInn);
  const powerplayScore = phaseBowlScore(
    playerPhase.powerplay,
    mergePar.powerplay,
    "powerplay",
  );
  const middleScore = phaseBowlScore(playerPhase.middle, mergePar.middle, "middle");
  const deathScore = phaseBowlScore(playerPhase.death, mergePar.death, "death");

  const pressureIndex =
    pressureW > 0 ? Math.min(130, (pressureAcc / pressureW) * 40) : null;

  const bqarIndex =
    runs > 1e-6 ? (100 * expRunsBqar) / runs : null;

  return {
    playerId: pid,
    name,
    balls: legalBalls,
    runs,
    wickets,
    aerIndex,
    rpbConceded,
    dotPct,
    falseShotProxyPct,
    wicketsPerBall,
    powerplayScore,
    middleScore,
    deathScore,
    pressureIndex,
    bqarIndex,
    cbrB: null,
  };
}

function minMaxNorm(values: number[]): number[] {
  if (values.length === 0) return [];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (hi <= lo) return values.map(() => 50);
  return values.map((v) => (100 * (v - lo)) / (hi - lo));
}

function normForRows<T>(
  rows: T[],
  getter: (r: T) => number | null | undefined,
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

export function formatBowlingFrameworkCell(
  key: keyof BowlingFrameworkMetrics,
  row: BowlingFrameworkMetrics,
): string {
  switch (key) {
    case "aerIndex":
      return row.aerIndex != null ? row.aerIndex.toFixed(1) : "—";
    case "rpbConceded":
      return row.rpbConceded != null ? row.rpbConceded.toFixed(3) : "—";
    case "dotPct":
      return row.dotPct != null ? `${(row.dotPct * 100).toFixed(1)}%` : "—";
    case "falseShotProxyPct":
      return row.falseShotProxyPct != null
        ? `${(row.falseShotProxyPct * 100).toFixed(1)}%`
        : "—";
    case "wicketsPerBall":
      return row.wicketsPerBall != null
        ? (row.wicketsPerBall * 100).toFixed(2) + "%"
        : "—";
    case "powerplayScore":
    case "middleScore":
    case "deathScore":
      return row[key] != null ? (row[key] as number).toFixed(0) : "—";
    case "pressureIndex":
      return row.pressureIndex != null ? row.pressureIndex.toFixed(0) : "—";
    case "bqarIndex":
      return row.bqarIndex != null ? row.bqarIndex.toFixed(1) : "—";
    case "cbrB":
      return row.cbrB != null ? row.cbrB.toFixed(1) : "—";
    case "wickets":
      return String(row.wickets);
    case "runs":
      return String(row.runs);
    case "balls":
      return String(row.balls);
    case "name":
    case "playerId":
      return "";
    default:
      return "—";
  }
}

export function computeBowlingFrameworkRows(
  inningsList: [string, Innings][],
): BowlingFrameworkMetrics[] {
  const phaseParByInn = new Map<string, Record<Phase, BowlPhaseBucket>>();
  const legalByInn = new Map<string, Map<string, { before: number; total: number }>>();
  const scoreBeforeByInn = new Map<string, Map<string, number>>();
  const batterSrByInn = new Map<string, Map<string, number>>();
  const medianSrByInn = new Map<string, number>();

  for (const [innKey, inn] of inningsList) {
    phaseParByInn.set(innKey, collectBowlingPhasePar(inn));
    legalByInn.set(innKey, legalBallContextByKey(inn));
    scoreBeforeByInn.set(innKey, battingScoreBeforeByKey(inn));
    const bm = batterSrMap(inn);
    batterSrByInn.set(innKey, bm);
    medianSrByInn.set(innKey, median([...bm.values()]));
  }

  const byPlayer = new Map<
    string,
    { name: string; deliveries: BowlDelTagged[] }
  >();

  for (const [innKey, inn] of inningsList) {
    for (const line of inn.bowling ?? []) {
      const id = line.bowler_id != null ? String(line.bowler_id) : "";
      if (!id) continue;
      const cur = byPlayer.get(id) ?? {
        name: String(line.bowler ?? id),
        deliveries: [],
      };
      cur.name = String(line.bowler ?? cur.name);
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

  const rows: BowlingFrameworkMetrics[] = [];
  for (const [pid, agg] of byPlayer) {
    const row = buildBowlerRow(
      pid,
      agg.name,
      agg.deliveries,
      phaseParByInn,
      legalByInn,
      scoreBeforeByInn,
      batterSrByInn,
      medianSrByInn,
    );
    if (row) rows.push(row);
  }

  const phaseAvgs: (number | null)[] = rows.map((r) => {
    const xs = [r.powerplayScore, r.middleScore, r.deathScore].filter(
      (x): x is number => x != null,
    );
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  });

  const aerN = normForRows(rows, (r) => r.aerIndex);
  const dotN = normForRows(rows, (r) => r.dotPct);
  const falseN = normForRows(rows, (r) => r.falseShotProxyPct);
  const wpbN = normForRows(rows, (r) => r.wicketsPerBall);
  const rpbN = normForRows(rows, (r) =>
    r.rpbConceded != null ? -r.rpbConceded : null,
  );

  const phN = (() => {
    const vals = phaseAvgs.filter((v): v is number => v != null);
    const scaled = minMaxNorm(vals);
    let j = 0;
    return phaseAvgs.map((v) => (v != null ? scaled[j++]! : 50));
  })();

  const prN = normForRows(rows, (r) => r.pressureIndex);
  const bqN = normForRows(rows, (r) => r.bqarIndex);

  rows.forEach((row, idx) => {
    row.cbrB =
      0.25 * aerN[idx]! +
      0.1 * dotN[idx]! +
      0.1 * falseN[idx]! +
      0.1 * wpbN[idx]! +
      0.15 * phN[idx]! +
      0.15 * prN[idx]! +
      0.1 * bqN[idx]! +
      0.05 * rpbN[idx]!;
    row.cbrB = Math.round(row.cbrB * 10) / 10;
  });

  rows.sort((a, b) => (b.cbrB ?? 0) - (a.cbrB ?? 0));
  return rows;
}
