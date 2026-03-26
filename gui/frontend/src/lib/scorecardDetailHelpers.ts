import type {
  BattingLine,
  BowlingLine,
  Innings,
  TimelineBall,
} from "@/components/scorecard/scorecardTypes";

export function formatDate(s?: string | null): string {
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

export function overBallStr(over?: number | null, ball?: number | null): string {
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

export function formatBattingDismissal(b: BattingLine): string {
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
  return b.dismissal_kind ?? "out";
}

export function computeFallOfWickets(
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

export function computeExtras(batting: BattingLine[], inningsTotal: number): number {
  const batterRuns = batting.reduce((s, b) => s + (Number(b.runs) || 0), 0);
  return Math.max(0, (inningsTotal ?? 0) - batterRuns);
}

export function computeWidesNoballs(bowling: BowlingLine[]): { wides: number; noballs: number } {
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

export function computeInningsBalls(batting: BattingLine[]): number {
  let total = 0;
  for (const b of batting) {
    for (const d of b.deliveries ?? []) {
      if (d.is_wide) continue;
      total++;
    }
  }
  return total;
}

export function sortKeyOverBall(
  over: number | null | undefined,
  ball: number | null | undefined,
): number {
  const o = over ?? 0;
  const bi = ball ?? 0;
  return o * 1000 + bi;
}

export function buildInningsTimeline(bowling: BowlingLine[]): TimelineBall[] {
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

export function formatBallNarrative(
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

export function collectPlayerNames(inningsList: [string, Innings][]): Map<string, string> {
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
