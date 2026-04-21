/**
 * 10-pillar bowling analytics for one match (ball-by-ball scorecard only).
 */

import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { Innings } from "@/components/scorecard/scorecardTypes";
import {
  computeBowlingFrameworkRows,
  formatBowlingFrameworkCell,
  type BowlingFrameworkMetrics,
} from "@/lib/bowlingMatchFramework";

const COLS: {
  key: keyof BowlingFrameworkMetrics;
  label: string;
  hint: string;
}[] = [
  { key: "aerIndex", label: "AER", hint: "Adjusted economy vs innings phase par (100 ≈ par; higher = stingier)" },
  { key: "rpbConceded", label: "RPB↓", hint: "Runs per legal ball conceded (lower better)" },
  { key: "dotPct", label: "Dot%", hint: "Legal scoreless balls excluding wickets" },
  {
    key: "falseShotProxyPct",
    label: "Threat†",
    hint: "Proxy: wickets + 0 off bat (Cricsheet has no false-shot tags)",
  },
  { key: "wicketsPerBall", label: "W/B", hint: "Wickets per legal ball (%)" },
  { key: "powerplayScore", label: "PP", hint: "Powerplay control vs innings par" },
  { key: "middleScore", label: "Mid", hint: "Middle overs containment vs par" },
  { key: "deathScore", label: "Death", hint: "Death economy + boundary suppression vs par" },
  {
    key: "pressureIndex",
    label: "Press.",
    hint: "Chase: stinginess when required RPO is high (target_runs on innings)",
  },
  {
    key: "bqarIndex",
    label: "BQAR",
    hint: "Batter-quality adjusted economy (>100 = beat phase×SR expectation)",
  },
  { key: "cbrB", label: "CBR-B", hint: "Composite bowling rating 0–100 within this match" },
];

type Props = {
  inningsList: [string, Innings][];
};

export default function BowlingFrameworkTable({ inningsList }: Props): JSX.Element {
  const rows = useMemo(
    () => computeBowlingFrameworkRows(inningsList),
    [inningsList],
  );

  if (rows.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        No bowling spells with enough ball-by-ball data (need ≥6 legal deliveries with
        delivery lists).
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <details className="text-xs text-text-secondary max-w-3xl">
        <summary className="cursor-pointer font-medium text-text-primary select-none">
          How bowling metrics work (ball-by-ball only)
        </summary>
        <ul className="mt-2 list-disc pl-5 space-y-1">
          <li>
            <strong>AER / BQAR</strong> use the same innings phase run-rates everyone bowled
            under, scaled by striker SR in this innings (no career priors).
          </li>
          <li>
            <strong>Threat†</strong> is not DRS false-shot data — it counts bowler wickets plus
            scoreless balls off the bat as a beat-the-bat proxy.
          </li>
          <li>
            <strong>Pressure</strong> uses chase <code className="text-[11px]">target_runs</code>{" "}
            and required RPO from balls remaining.
          </li>
          <li>
            <strong>CBR-B</strong> weights match your spec after min–max normalisation across
            bowlers in this game.
          </li>
        </ul>
      </details>

      <div className="overflow-x-auto rounded-lg border border-surface-elevated">
        <table className="scorecard-table w-full text-xs min-w-[980px]">
          <thead>
            <tr className="border-b border-surface-elevated bg-slate-100/80 text-left text-text-muted dark:bg-[#080808]">
              <th className="py-2 pl-3 pr-2 font-medium sticky left-0 bg-inherit z-[1]">
                Bowler
              </th>
              <th className="py-2 px-1 font-medium text-right">O</th>
              <th className="py-2 px-1 font-medium text-right">R</th>
              <th className="py-2 pr-2 font-medium text-right">W</th>
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
            {rows.map((row: BowlingFrameworkMetrics) => (
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
                <td className="py-1.5 px-1 text-right tabular-nums">
                  {(row.balls / 6).toFixed(1)}
                </td>
                <td className="py-1.5 px-1 text-right tabular-nums">{row.runs}</td>
                <td className="py-1.5 pr-2 text-right tabular-nums">{row.wickets}</td>
                {COLS.map((c) => (
                  <td
                    key={c.key}
                    className="py-1.5 px-1 text-right tabular-nums text-text-primary"
                    title={c.hint}
                  >
                    {formatBowlingFrameworkCell(c.key, row)}
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
