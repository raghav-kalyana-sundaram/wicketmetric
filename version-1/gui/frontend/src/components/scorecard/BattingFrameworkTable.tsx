/**
 * 10-pillar batting analytics for one match (ball-by-ball scorecard only).
 */

import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { Innings } from "@/components/scorecard/scorecardTypes";
import {
  computeBattingFrameworkRows,
  formatFrameworkCell,
  type BattingFrameworkMetrics,
} from "@/lib/battingMatchFramework";

const COLS: {
  key: keyof BattingFrameworkMetrics;
  label: string;
  hint: string;
}[] = [
  { key: "asrIndex", label: "ASR", hint: "Phase-adjusted vs this innings (100 ≈ par)" },
  { key: "rpb", label: "RPB", hint: "Runs per ball faced" },
  { key: "dotPct", label: "Dot%", hint: "Share of faced balls with 0 runs off bat" },
  { key: "boundaryPct", label: "Bnd%", hint: "4s + 6s per ball faced" },
  { key: "ballsPerDismissal", label: "BPD", hint: "Balls per dismissal; NR if not out" },
  { key: "powerplayScore", label: "PP", hint: "Powerplay vs innings PP par (SR + boundaries)" },
  { key: "middleScore", label: "Mid", hint: "Middle overs control (rotation + dot avoidance)" },
  { key: "deathScore", label: "Death", hint: "Death overs vs innings death par" },
  { key: "pressureIndex", label: "Press.", hint: "Chase only: scoring when required RPO is high" },
  { key: "bdar", label: "BDAR", hint: "Runs weighted by bowler economy this innings" },
  { key: "cbr", label: "CBR", hint: "Composite (0–100) within this match" },
];

type Props = {
  inningsList: [string, Innings][];
};

export default function BattingFrameworkTable({ inningsList }: Props): JSX.Element {
  const rows = useMemo(
    () => computeBattingFrameworkRows(inningsList),
    [inningsList],
  );

  if (rows.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        No batting lines with enough ball-by-ball data (need ≥5 faced balls with delivery
        lists).
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <details className="text-xs text-text-secondary max-w-3xl">
        <summary className="cursor-pointer font-medium text-text-primary select-none">
          How these metrics work (ball-by-ball only)
        </summary>
        <ul className="mt-2 list-disc pl-5 space-y-1">
          <li>
            <strong>ASR</strong> compares your runs to expected runs from the same phase’s
            team-wide strike rate in that innings (not venue or career priors).
          </li>
          <li>
            <strong>BDAR</strong> up-weights runs off economical bowlers in this innings only.
          </li>
          <li>
            <strong>Pressure</strong> uses target + balls-left required RPO when{" "}
            <code className="text-[11px]">target_runs</code> exists on the innings.
          </li>
          <li>
            <strong>CBR</strong> blends normalized pillars with your specified weights; ranks
            are within this match only.
          </li>
        </ul>
      </details>

      <div className="overflow-x-auto rounded-lg border border-surface-elevated">
        <table className="scorecard-table w-full text-xs min-w-[920px]">
          <thead>
            <tr className="border-b border-surface-elevated bg-slate-100/80 text-left text-text-muted dark:bg-[#080808]">
              <th className="py-2 pl-3 pr-2 font-medium sticky left-0 bg-inherit z-[1]">
                Batter
              </th>
              <th className="py-2 px-1 font-medium text-right">R</th>
              <th className="py-2 pr-2 font-medium text-right">B</th>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  className="py-2 px-1 font-medium text-right whitespace-nowrap"
                  title={c.hint}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row: BattingFrameworkMetrics) => (
              <tr
                key={row.playerId}
                className="border-b border-surface-elevated/50 hover:bg-surface-elevated/30"
              >
                <td className="py-1.5 pl-3 pr-2 sticky left-0 bg-surface z-[1]">
                  <Link
                    to={`/player/${encodeURIComponent(row.playerId)}`}
                    className="font-medium text-primary text-xs hover:underline"
                  >
                    {row.name}
                  </Link>
                </td>
                <td className="py-1.5 px-1 text-right tabular-nums">{row.runs}</td>
                <td className="py-1.5 pr-2 text-right tabular-nums">{row.balls}</td>
                {COLS.map((c) => (
                  <td
                    key={c.key}
                    className="py-1.5 px-1 text-right tabular-nums text-text-primary"
                    title={c.hint}
                  >
                    {formatFrameworkCell(c.key, row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
