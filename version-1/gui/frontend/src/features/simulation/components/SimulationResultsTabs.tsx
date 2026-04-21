import { useEffect, useMemo, useState } from "react";
import ScorecardDetailBody from "@/components/scorecard/ScorecardDetailBody";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  Legend,
} from "recharts";
import type { BallLogRow, SimulationResult } from "../utils/simulationMock";

const PIE_COLORS: Record<string, string> = {
  a: "#d4d4dc",
  b: "#F59E0B",
  tie: "#64748B",
};

const TOOLTIP_STYLE = {
  backgroundColor: "#141414",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: "0.5rem",
  color: "#e8e8ee",
};

type TabId = "summary" | "scorecard" | "players" | "log";

interface SimulationResultsTabsProps {
  data: SimulationResult;
}

export default function SimulationResultsTabs({ data }: SimulationResultsTabsProps) {
  const [tab, setTab] = useState<TabId>("summary");

  const tabs = useMemo(() => {
    const list: { id: TabId; label: string }[] = [
      { id: "summary", label: "Match summary" },
    ];
    if (data.scorecard) {
      list.push({ id: "scorecard", label: "Scorecard" });
    }
    list.push(
      { id: "players", label: "Player projections" },
      { id: "log", label: "Ball-by-ball log" },
    );
    return list;
  }, [data.scorecard]);

  useEffect(() => {
    if (tab === "scorecard" && !data.scorecard) {
      setTab("summary");
    }
  }, [tab, data.scorecard]);

  const pieData = useMemo(
    () =>
      data.winShares.map((w) => ({
        name: w.name,
        value: Math.max(0, w.pct),
        fillKey: w.fillKey,
      })),
    [data.winShares],
  );

  const oversGrouped = useMemo(() => groupBallsByOver(data.ballLog), [data.ballLog]);

  return (
    <div className="section-card overflow-hidden">
      <div
        role="tablist"
        aria-label="Simulation results"
        className="flex flex-wrap gap-1 border-b border-surface-elevated bg-surface-elevated/20 px-2 pt-2"
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`rounded-t-lg px-4 py-2.5 text-sm font-medium transition-colors ${
              tab === t.id
                ? "border-b-2 border-primary text-primary bg-surface"
                : "text-text-secondary hover:text-text-primary"
            }`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="section-card-body min-h-[280px]">
        {tab === "summary" && (
          <div className="flex flex-col items-center gap-6 lg:flex-row lg:items-center lg:justify-center lg:gap-10">
            <div className="h-[260px] w-full max-w-[320px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius="58%"
                    outerRadius="88%"
                    paddingAngle={1}
                    stroke="none"
                  >
                    {pieData.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={PIE_COLORS[entry.fillKey] ?? "#64748B"}
                      />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    formatter={(value: number) => [`${value.toFixed(1)}%`, "Share"]}
                    contentStyle={TOOLTIP_STYLE}
                  />
                  <Legend
                    verticalAlign="bottom"
                    wrapperStyle={{ color: "#d4d4d8", fontSize: "12px", paddingTop: 8 }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="max-w-sm space-y-3 text-center lg:text-left">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
                Win probability
              </h3>
              <p className="text-sm text-text-secondary">
                Distribution from the preview Monte Carlo-style run. Shares are
                illustrative until a live model is wired in.
              </p>
              <ul className="space-y-2 text-left text-sm">
                {data.winShares.map((w) => (
                  <li
                    key={w.name}
                    className="flex items-center justify-between gap-4 rounded-lg border border-surface-elevated/80 bg-surface-elevated/20 px-3 py-2"
                  >
                    <span className="flex items-center gap-2 text-text-primary">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{
                          backgroundColor: PIE_COLORS[w.fillKey] ?? "#64748B",
                        }}
                      />
                      <span className="truncate">{w.name}</span>
                    </span>
                    <span className="font-mono tabular-nums text-primary">
                      {w.pct.toFixed(1)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {tab === "scorecard" && data.scorecard && (
          <div className="min-w-0 -mx-1 sm:mx-0">
            <ScorecardDetailBody
              scorecard={data.scorecard}
              matchId={null}
              variant="simulation"
            />
          </div>
        )}

        {tab === "players" && (
          <div className="space-y-8">
            <ProjectionTable
              title="Most likely top scorers"
              unit="runs"
              rows={data.topScorers}
            />
            <ProjectionTable
              title="Most likely wicket takers"
              unit="wickets"
              rows={data.topWicketTakers}
            />
          </div>
        )}

        {tab === "log" && (
          <div className="space-y-2">
            <p className="text-xs text-text-muted">
              Sample “most probable” passage — not the union of all iteration paths.
            </p>
            <div className="max-h-[min(60vh,32rem)] space-y-2 overflow-y-auto pr-1">
              {oversGrouped.map(({ over, balls }) => (
                <OverBlock key={over} over={over} balls={balls} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectionTable({
  title,
  unit,
  rows,
}: {
  title: string;
  unit: string;
  rows: SimulationResult["topScorers"];
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-text-primary mb-3">{title}</h3>
      <div className="overflow-x-auto rounded-lg border border-surface-elevated">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-elevated bg-surface-elevated/30 text-left text-xs uppercase tracking-wide text-text-muted">
              <th className="px-3 py-2 font-medium">Player</th>
              <th className="px-3 py-2 font-medium text-right">Median</th>
              <th className="px-3 py-2 font-medium text-right">Range (low–high)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={`${r.name}-${i}`}
                className="border-b border-surface-elevated/60 last:border-0"
              >
                <td className="px-3 py-2.5 text-text-primary">{r.name}</td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary">
                  {r.median}
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-text-secondary">
                  {r.low} – {r.high} {unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function groupBallsByOver(ballLog: BallLogRow[]): { over: number; balls: BallLogRow[] }[] {
  const map = new Map<number, BallLogRow[]>();
  for (const b of ballLog) {
    if (!map.has(b.over)) map.set(b.over, []);
    map.get(b.over)!.push(b);
  }
  return [...map.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([over, balls]) => ({ over, balls }));
}

function OverBlock({ over, balls }: { over: number; balls: BallLogRow[] }) {
  const runs = balls.reduce((s, b) => s + b.runs, 0);
  const wkts = balls.filter((b) => b.outcome === "wicket").length;
  const wktLabel =
    wkts === 0 ? "" : wkts === 1 ? ", 1 wicket" : `, ${wkts} wickets`;

  return (
    <details className="group rounded-lg border border-surface-elevated bg-surface-elevated/15 open:bg-surface-elevated/25">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-text-primary [&::-webkit-details-marker]:hidden">
        <span className="flex items-center justify-between gap-2">
          <span>
            Over {over}{" "}
            <span className="font-normal text-text-muted">
              · {runs} runs{wktLabel}
            </span>
          </span>
          <span className="text-xs text-text-muted group-open:hidden">Expand</span>
          <span className="hidden text-xs text-text-muted group-open:inline">
            Collapse
          </span>
        </span>
      </summary>
      <ul className="space-y-2 border-t border-surface-elevated/60 px-4 py-3">
        {balls.map((b, i) => (
          <li
            key={`${b.over}-${b.ballInOver}-${i}`}
            className="flex flex-wrap items-center gap-2 text-sm"
          >
            <span className="w-14 shrink-0 font-mono text-xs text-text-muted tabular-nums">
              {b.over}.{b.ballInOver}
            </span>
            <OutcomeChip outcome={b.outcome} label={b.label} />
            <span className="text-text-secondary">
              {b.strikerName}
              <span className="text-text-muted"> vs </span>
              {b.bowlerName}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function OutcomeChip({
  outcome,
  label,
}: {
  outcome: BallLogRow["outcome"];
  label: string;
}) {
  const cls = {
    dot: "border-cricket-dot/50 text-cricket-dot bg-cricket-dot/10",
    single: "border-chart-1/40 text-chart-1 bg-chart-1/10",
    boundary: "border-cricket-boundary/50 text-cricket-boundary bg-cricket-boundary/10",
    six: "border-cricket-six/50 text-cricket-six bg-cricket-six/15",
    wicket: "border-cricket-wicket/50 text-cricket-wicket bg-cricket-wicket/10",
    extra: "border-text-muted/40 text-text-muted bg-surface-elevated/40",
  }[outcome];

  return (
    <span
      className={`inline-flex min-w-[2.25rem] justify-center rounded-md border px-2 py-0.5 text-xs font-semibold font-mono tabular-nums ${cls}`}
    >
      {label}
    </span>
  );
}
