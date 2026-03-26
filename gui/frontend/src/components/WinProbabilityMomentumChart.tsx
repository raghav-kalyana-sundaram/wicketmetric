/**
 * Full-match win probability: one stepped line = first team's P(win);
 * above 50% is that team's territory, below 50% is the opponent's. 50% reference,
 * innings breaks, and top-3 |WPA| momentum markers.
 */

import { useId, useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART_COLOURS } from "@/lib/colours";

type WpBall = {
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
  win_prob_after?: number | null;
  wpa?: number | null;
};

type WpBowlingLine = {
  bowler_id?: string | null;
  bowler?: string | null;
  deliveries?: WpBall[] | null;
};

type WpInnings = {
  innings_num?: number;
  batting_team?: string | null;
  bowling_team?: string | null;
  bowling?: WpBowlingLine[];
};

function sortKeyOverBall(over: number | null | undefined, ball: number | null | undefined): number {
  const o = over ?? 0;
  const bi = ball ?? 0;
  return o * 1000 + bi;
}

type TimelineBall = WpBall & { bowler_id?: string | null; bowler?: string | null };

function buildInningsTimeline(bowling: WpBowlingLine[]): TimelineBall[] {
  const rows: TimelineBall[] = [];
  for (const bw of bowling) {
    for (const d of bw.deliveries ?? []) {
      rows.push({
        ...d,
        bowler_id: bw.bowler_id ?? null,
        bowler: bw.bowler ?? null,
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

function formatBallNarrative(b: TimelineBall, nameById: Map<string, string>): string {
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
    return `Wicket! ${outName} (${formatWicketKind(b.wicket_kind)})`;
  }
  if (br === 4) return "FOUR";
  if (br === 6) return "SIX";
  if (tr === 0) return "No run";
  if (tr === 1) return "1 run";
  return `${tr} runs`;
}

export type WpChartPoint = {
  x: number;
  /** Win probability % for the first listed team (teams[0]). */
  pRef: number;
  /** Win probability % for the second team; always 100 − pRef. */
  pOther: number;
  ob: string;
  /** Batting side runs/wickets after this ball (same innings). */
  scoreAfter: string;
  narrative: string;
  battingTeam: string;
  bowlingTeam: string;
  wpaBatPct: number;
  wpaBowlPct: number;
  wpaRef: number;
  isTopMomentum: boolean;
  /** Bridge / innings marker — exclude from momentum picks and dots. */
  synthetic?: boolean;
};

function fmtPctSigned(v: number): string {
  const n = Math.round(v * 10) / 10;
  const s = n >= 0 ? "+" : "";
  return `${s}${n}%`;
}

function territoryStroke(pRef: number, colorA: string, colorB: string): string {
  if (pRef > 50) return colorA;
  if (pRef < 50) return colorB;
  return "#a1a1aa";
}

function MomentumDot(props: {
  cx?: number;
  cy?: number;
  payload?: WpChartPoint;
  strokeColour?: string;
}): JSX.Element {
  const { cx, cy, payload, strokeColour = "#a1a1aa" } = props;
  const resolved = strokeColour;
  if (cx == null || cy == null || payload?.synthetic || !payload?.isTopMomentum) {
    return <g />;
  }
  return (
    <g className="wp-momentum-marker" style={{ color: resolved }}>
      <circle
        cx={cx}
        cy={cy}
        r={12}
        className="wp-momentum-pulse"
        fill="none"
        stroke="currentColor"
      />
      <circle cx={cx} cy={cy} r={5} className="wp-momentum-core" stroke="currentColor" />
    </g>
  );
}

function WpTooltipBody({
  active,
  payload,
  refTeam,
  otherTeam,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: WpChartPoint }>;
  refTeam: string;
  otherTeam: string;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  const pr = Math.round(p.pRef * 10) / 10;
  const po = Math.round(p.pOther * 10) / 10;
  if (p.synthetic) {
    return (
      <div className="rounded-lg border border-white/15 bg-surface px-3 py-2.5 text-xs shadow-xl max-w-xs">
        <p className="font-semibold text-text-primary mb-1">{p.narrative}</p>
        <p className="text-text-muted tabular-nums mb-1.5">
          {p.battingTeam}{" "}
          <span className="text-text-primary font-medium">{p.scoreAfter}</span>
        </p>
        <p className="tabular-nums text-text-secondary">
          <span className="text-primary">{refTeam}</span> {pr}%
          <span className="text-text-muted mx-1.5">·</span>
          <span className="text-emerald-300/95">{otherTeam}</span> {po}%
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-white/15 bg-surface px-3 py-2.5 text-xs shadow-xl max-w-xs">
      <p className="font-semibold tabular-nums text-text-primary mb-1">Over {p.ob}</p>
      <p className="text-text-muted tabular-nums mb-1">
        {p.battingTeam}{" "}
        <span className="text-text-primary font-medium">{p.scoreAfter}</span>
      </p>
      <p className="tabular-nums text-text-secondary mb-1">
        <span className="text-primary">{refTeam}</span> {pr}%
        <span className="text-text-muted mx-1.5">·</span>
        <span className="text-emerald-300/95">{otherTeam}</span> {po}%
      </p>
      <p className="text-text-primary leading-snug mb-2">{p.narrative}</p>
      <p className="text-text-muted leading-snug">
        <span className="text-text-secondary">{p.battingTeam}</span> {fmtPctSigned(p.wpaBatPct)}
        <span className="text-text-muted mx-1">·</span>
        <span className="text-text-secondary">{p.bowlingTeam}</span> {fmtPctSigned(p.wpaBowlPct)}
      </p>
      <p className="text-[10px] text-text-muted mt-2">
        Ball-level shift (empirical model). The curve is {refTeam}&apos;s win %; it mirrors{" "}
        {otherTeam}&apos;s (they sum to 100%).
      </p>
    </div>
  );
}

/** Tiny x-advance per wide/no-ball so extras never share the same x as the prior legal ball (avoids vertical spikes). */
const EXTRA_X_FRAC = 0.08 / 6;

function synthPoint(
  base: Pick<
    WpChartPoint,
    | "x"
    | "pRef"
    | "pOther"
    | "ob"
    | "narrative"
    | "battingTeam"
    | "bowlingTeam"
    | "scoreAfter"
  >,
): WpChartPoint {
  return {
    ...base,
    wpaRef: 0,
    wpaBatPct: 0,
    wpaBowlPct: 0,
    isTopMomentum: false,
    synthetic: true,
  };
}

export function buildMatchWinProbabilityPoints(
  inningsMap: Record<string, WpInnings>,
  refTeam: string,
  oversLimit: number,
  nameById: Map<string, string>,
): WpChartPoint[] {
  const keys = Object.keys(inningsMap).sort((a, b) => Number(a) - Number(b));
  type Segment = { innNum: number; pts: WpChartPoint[] };
  const segments: Segment[] = [];

  for (const k of keys) {
    const inn = inningsMap[k];
    if (!inn) continue;
    const innNum = Number(inn.innings_num ?? k);
    if (!Number.isFinite(innNum) || innNum < 1) continue;

    const offset = (innNum - 1) * oversLimit;
    let legalCum = 0;
    let extrasSinceLegal = 0;
    const timeline = buildInningsTimeline(inn.bowling ?? []);
    const battingTeam = String(inn.batting_team ?? "Batting");
    const bowlingTeam = String(inn.bowling_team ?? "Bowling");
    const segPts: WpChartPoint[] = [];
    let runningScore = 0;
    let runningWkts = 0;

    for (const ball of timeline) {
      const wpAfter = ball.win_prob_after;
      const wpaRaw = ball.wpa;
      if (wpAfter == null || wpaRaw == null) continue;

      const tr = Number(ball.total_runs ?? 0);
      runningScore += tr;
      if (ball.is_wicket) runningWkts += 1;
      const scoreAfter = `${runningScore}/${runningWkts}`;

      if (ball.is_legal) {
        legalCum += 1;
        extrasSinceLegal = 0;
      } else {
        extrasSinceLegal += 1;
      }
      const x =
        offset + legalCum / 6 + extrasSinceLegal * EXTRA_X_FRAC;
      const pBat = wpAfter * 100;
      const pRef = battingTeam === refTeam ? pBat : 100 - pBat;
      const pOther = 100 - pRef;
      const wpaBatPct = wpaRaw * 100;
      const wpaBowlPct = -wpaRaw * 100;
      const wpaRef = battingTeam === refTeam ? wpaBatPct : wpaBowlPct;

      const ob =
        ball.over != null && ball.ball_idx != null
          ? `${ball.over}.${ball.ball_idx}`
          : `${ball.over ?? "?"}.${ball.ball_idx ?? "?"}`;

      segPts.push({
        x,
        pRef,
        pOther,
        ob,
        scoreAfter,
        narrative: formatBallNarrative(ball, nameById),
        battingTeam,
        bowlingTeam,
        wpaBatPct,
        wpaBowlPct,
        wpaRef,
        isTopMomentum: false,
      });
    }

    if (segPts.length) segments.push({ innNum, pts: segPts });
  }

  const points: WpChartPoint[] = [];
  for (let si = 0; si < segments.length; si++) {
    const { pts } = segments[si];
    if (si > 0) {
      const prev = segments[si - 1]!;
      const lastPrev = prev.pts[prev.pts.length - 1]!;
      const firstCurr = pts[0]!;
      const breakX = prev.innNum * oversLimit;

      if (lastPrev.x < breakX) {
        points.push(
          synthPoint({
            x: breakX,
            pRef: lastPrev.pRef,
            pOther: lastPrev.pOther,
            ob: "—",
            narrative: "Innings break (end of phase)",
            battingTeam: lastPrev.battingTeam,
            bowlingTeam: lastPrev.bowlingTeam,
            scoreAfter: lastPrev.scoreAfter,
          }),
        );
      }

      const tip = points[points.length - 1]!;
      if (tip.pRef !== firstCurr.pRef || tip.pOther !== firstCurr.pOther) {
        const xVert = lastPrev.x < breakX ? breakX : lastPrev.x;
        points.push(
          synthPoint({
            x: xVert,
            pRef: firstCurr.pRef,
            pOther: firstCurr.pOther,
            ob: firstCurr.ob,
            narrative: `Next innings — ${firstCurr.narrative}`,
            battingTeam: firstCurr.battingTeam,
            bowlingTeam: firstCurr.bowlingTeam,
            scoreAfter: firstCurr.scoreAfter,
          }),
        );
      }
    }

    for (const p of pts) points.push(p);
  }

  const ranked = points
    .map((p, i) => ({ i, m: Math.abs(p.wpaRef) }))
    .filter((row) => !points[row.i]?.synthetic)
    .sort((a, b) => b.m - a.m);
  const top = new Set(ranked.slice(0, 3).map((r) => r.i));
  for (let i = 0; i < points.length; i++) {
    if (top.has(i)) points[i] = { ...points[i], isTopMomentum: true };
  }

  return points;
}

/** Row fields for territory fills (Recharts needs nulls to split areas). */
type WpChartRow = WpChartPoint & {
  fillAbove: number | null;
  fillBelow: number | null;
};

function rowsForTerritoryChart(points: WpChartPoint[]): WpChartRow[] {
  return points.map((p) => ({
    ...p,
    fillAbove: p.pRef > 50 ? p.pRef : null,
    fillBelow: p.pRef < 50 ? p.pRef : null,
  }));
}

export type WinProbabilityMomentumChartProps = {
  innings: Record<string, WpInnings>;
  teams: string[];
  oversLimit: number;
  dlsApplied: boolean;
  nameById: Map<string, string>;
};

export function WinProbabilityMomentumChart({
  innings,
  teams,
  oversLimit,
  dlsApplied,
  nameById,
}: WinProbabilityMomentumChartProps): JSX.Element {
  const gradId = useId().replace(/:/g, "");
  const refTeam = teams[0] ?? "Team A";
  const otherTeam = teams[1] ?? "Team B";
  const colorA = CHART_COLOURS[0];
  const colorB = CHART_COLOURS[2];

  const data = useMemo(
    () => buildMatchWinProbabilityPoints(innings, refTeam, oversLimit, nameById),
    [innings, refTeam, oversLimit, nameById],
  );

  const chartData = useMemo(() => rowsForTerritoryChart(data), [data]);

  const inningsKeys = useMemo(
    () => Object.keys(innings).sort((a, b) => Number(a) - Number(b)),
    [innings],
  );

  const xMax = oversLimit * Math.max(inningsKeys.length, 1);

  if (data.length === 0) {
    return (
      <section
        className="mb-8 rounded-xl border border-white/[0.1] bg-surface px-4 py-5 text-sm text-text-muted"
        aria-label="Win probability"
      >
        <h2 className="mb-1 text-sm font-semibold text-text-primary">Win probability and momentum</h2>
        <p>
          Win probability is not available for this scorecard. Rebuild scorecards with{" "}
          <code className="text-text-secondary">scorecards.win_probability: true</code> in config and
          re-run the pipeline (or <code className="text-text-secondary">--scorecards-only</code>).
        </p>
      </section>
    );
  }

  return (
    <section
      className="mb-8 overflow-hidden rounded-2xl border border-white/[0.1] bg-gradient-to-b from-[#141414] via-[#0c0c0c] to-[#080808] shadow-[0_24px_48px_-28px_rgba(0,0,0,0.72)]"
      aria-label="Win probability and momentum"
    >
      <div className="border-b border-white/[0.07] px-4 pb-1 pt-4">
        <h2 className="text-sm font-semibold tracking-wide text-text-primary">
          Win probability and momentum
        </h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-text-muted">
          One line is {refTeam}&apos;s modelled win chance (above 50% = their territory; below =
          {otherTeam}&apos;s). The chase starts from the first innings&apos; implied odds — not a
          50/50 reset. Wides and no-balls are nudged on the time axis to avoid vertical spikes.
          Between innings the line steps at the break. Pulses: largest real-ball |WPA| for{" "}
          {refTeam}.
        </p>
        {dlsApplied && (
          <p className="text-xs text-amber-500/90 mt-2">
            This result used a reduced target (e.g. DLS). Win probability can spike around revised
            targets — treat as indicative.
          </p>
        )}
      </div>
      <div className="p-2 sm:p-4 h-[min(360px,55vh)] min-h-[280px] w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 12, right: 14, left: 2, bottom: 6 }}>
            <defs>
              <linearGradient id={`${gradId}-ref`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colorA} stopOpacity={0.42} />
                <stop offset="100%" stopColor={colorA} stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id={`${gradId}-oth`} x1="0" y1="1" x2="0" y2="0">
                <stop offset="0%" stopColor={colorB} stopOpacity={0.42} />
                <stop offset="100%" stopColor={colorB} stopOpacity={0.02} />
              </linearGradient>
              <filter id={`${gradId}-glow`} x="-40%" y="-40%" width="180%" height="180%">
                <feGaussianBlur stdDeviation="2.2" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <CartesianGrid
              strokeDasharray="2 6"
              stroke="rgba(255,255,255,0.045)"
              vertical={false}
            />
            <XAxis
              type="number"
              dataKey="x"
              domain={[0, xMax]}
              ticks={Array.from({ length: inningsKeys.length + 1 }, (_, i) => i * oversLimit)}
              stroke="rgba(161,161,170,0.35)"
              tick={{ fill: "#a1a1aa", fontSize: 11, fontWeight: 500 }}
              tickLine={{ stroke: "rgba(161,161,170,0.25)" }}
              axisLine={{ stroke: "rgba(161,161,170,0.25)" }}
              label={{
                value: "Match overs (innings 1 → 2 → …)",
                position: "insideBottom",
                offset: -2,
                fill: "#90909a",
                fontSize: 11,
                fontWeight: 500,
              }}
            />
            <YAxis
              domain={[0, 100]}
              stroke="rgba(161,161,170,0.35)"
              tick={{ fill: "#a1a1aa", fontSize: 11, fontWeight: 500 }}
              tickLine={{ stroke: "rgba(161,161,170,0.25)" }}
              axisLine={{ stroke: "rgba(161,161,170,0.25)" }}
              tickFormatter={(v) => `${v}%`}
              width={46}
              label={{
                value: `P(${refTeam.length > 18 ? `${refTeam.slice(0, 16)}…` : refTeam} wins)`,
                angle: -90,
                position: "insideLeft",
                fill: "#90909a",
                fontSize: 10,
                fontWeight: 500,
              }}
            />
            <ReferenceLine
              y={50}
              stroke="rgba(251, 191, 36, 0.26)"
              strokeDasharray="5 5"
              strokeWidth={1}
            />
            {inningsKeys.length > 1
              ? inningsKeys.slice(0, -1).map((_, idx) => (
                  <ReferenceLine
                    key={`inn-${idx}`}
                    x={(idx + 1) * oversLimit}
                    stroke="rgba(255,255,255,0.14)"
                    strokeDasharray="2 8"
                  />
                ))
              : null}
            <Tooltip
              content={(tipProps) => (
                <WpTooltipBody
                  active={tipProps.active}
                  payload={tipProps.payload as ReadonlyArray<{ payload?: WpChartPoint }>}
                  refTeam={refTeam}
                  otherTeam={otherTeam}
                />
              )}
              cursor={{ stroke: "rgba(250, 250, 250, 0.22)", strokeWidth: 1, strokeDasharray: "4 4" }}
            />
            <Area
              type="stepAfter"
              dataKey="fillBelow"
              baseValue={50}
              stroke="none"
              connectNulls={false}
              fill={`url(#${gradId}-oth)`}
              fillOpacity={1}
              isAnimationActive={false}
              hide
            />
            <Area
              type="stepAfter"
              dataKey="fillAbove"
              baseValue={50}
              stroke="none"
              connectNulls={false}
              fill={`url(#${gradId}-ref)`}
              fillOpacity={1}
              isAnimationActive={false}
              hide
            />
            <Line
              type="stepAfter"
              dataKey="pRef"
              stroke="rgba(248, 250, 252, 0.88)"
              strokeWidth={5}
              strokeOpacity={0.14}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={false}
              isAnimationActive={false}
              hide
            />
            <Line
              type="stepAfter"
              dataKey="pRef"
              name={`${refTeam} win probability`}
              stroke="rgba(252, 252, 253, 0.95)"
              strokeWidth={2.25}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={(dotProps) => (
                <MomentumDot
                  {...dotProps}
                  strokeColour={territoryStroke(dotProps.payload?.pRef ?? 50, colorA, colorB)}
                />
              )}
              isAnimationActive={false}
              filter={`url(#${gradId}-glow)`}
              activeDot={{
                r: 5,
                fill: "rgba(252, 252, 253, 0.95)",
                stroke: "rgba(255,255,255,0.5)",
                strokeWidth: 1.5,
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 pb-4 text-[10px] text-text-muted">
        <span className="inline-flex items-center gap-2">
          <span
            className="inline-flex h-2 w-7 shrink-0 overflow-hidden rounded-full"
            style={{
              background: `linear-gradient(180deg, ${colorA} 0%, transparent 100%)`,
              boxShadow: `inset 0 0 0 1px rgba(255,255,255,0.12)`,
            }}
          />
          Above 50% → {refTeam}
        </span>
        <span className="inline-flex items-center gap-2">
          <span
            className="inline-flex h-2 w-7 shrink-0 overflow-hidden rounded-full"
            style={{
              background: `linear-gradient(0deg, ${colorB} 0%, transparent 100%)`,
              boxShadow: `inset 0 0 0 1px rgba(255,255,255,0.12)`,
            }}
          />
          Below 50% → {otherTeam}
        </span>
        <span className="inline-flex items-center gap-1.5 w-full sm:w-auto sm:ml-auto">
          <span className="h-px w-5 rounded-full bg-slate-400 dark:bg-white/22 shrink-0" />
          Win % curve
        </span>
      </div>
    </section>
  );
}
