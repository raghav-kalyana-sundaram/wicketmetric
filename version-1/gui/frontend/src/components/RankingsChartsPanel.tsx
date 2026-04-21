/**
 * Leaderboard charts: scatter, form lines, distribution, ranked bars, and heatmaps (correlation
 * matrix + player×metric intensity) over the filtered pool.
 */

import { useMemo, useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  ZAxis,
  BarChart,
  Bar,
} from "recharts";
import {
  BarChart3,
  LineChart as LineChartIcon,
  ScatterChart as ScatterIcon,
  Activity,
  BarChart2,
  Grid3x3,
} from "lucide-react";

import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import {
  usePlayerForm,
  useCompareForm,
  useLeaderboardDistribution,
  useLeaderboardHeatmap,
  useBarRankLeaderboard,
} from "@/api/queries";
import { chartColour } from "@/lib/colours";
import {
  primaryDisplayRating,
  careerDisplayRating,
  fmtDate,
} from "@/lib/format";
import type {
  PlayerSummary,
  FormResponse,
  FormPoint,
  LeaderboardParams,
  LeaderboardDistributionFilters,
  LeaderboardDistributionResponse,
  LeaderboardHeatmapParams,
} from "@/api/types";

const MAX_LINE_SERIES = 10;
const MAX_BAR_ROWS = 25;
const MIN_BAR_ROWS = 3;
const MAX_BAR_COMPARE_METRICS = 3;

type ChartTab = "scatter" | "line" | "distribution" | "bars" | "heatmap";
type HeatmapSubTab = "correlation" | "intensity";

function corrCellBg(r: number | null | undefined): string {
  if (r == null || Number.isNaN(r)) return "rgba(148, 163, 184, 0.14)";
  const t = (r + 1) / 2;
  const hue = 215 + t * 125;
  const light = 48 - Math.abs(r) * 14;
  return `hsl(${hue} 58% ${Math.max(22, light)}%)`;
}

function intensityCellBg(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "rgba(148, 163, 184, 0.14)";
  const L = 28 + v * 40;
  return `hsl(222 62% ${L}%)`;
}
type DistributionPlotMode = "box" | "violin" | "both" | "histogram";
type BoxViolinMode = "box" | "violin" | "both";
type LineMode = "single" | "multi";

export interface ScatterMetricOption {
  key: string;
  label: string;
}

function getScatterNumeric(player: PlayerSummary, key: string): number | null {
  switch (key) {
    case "rating_current":
      return primaryDisplayRating(player);
    case "rating_overall":
      return careerDisplayRating(player);
    case "overall_score":
      return player.overall_score ?? null;
    case "innings_count":
      return Number.isFinite(player.innings_count) ? player.innings_count : null;
    case "total_runs":
      return Number.isFinite(player.total_runs) ? player.total_runs : null;
    case "career_sr":
      return player.career_sr ?? null;
    case "career_avg":
      return player.career_avg ?? null;
    case "score_1":
      return player.score_1 ?? null;
    case "score_2":
      return player.score_2 ?? null;
    case "score_3":
      return player.score_3 ?? null;
    default: {
      const v = player.metrics?.[key];
      return typeof v === "number" && Number.isFinite(v) ? v : null;
    }
  }
}

function shortPlayerLabel(name: string, max = 22): string {
  if (name.length <= max) return name;
  return `${name.slice(0, max - 1)}…`;
}

type BarChartRow = {
  id: string;
  label: string;
  _raw: Record<string, number>;
} & Record<string, string | number | Record<string, number>>;

function buildBarChartRows(
  players: PlayerSummary[],
  keys: string[],
  normalize: boolean,
): BarChartRow[] {
  const rows: BarChartRow[] = players.map((p) => {
    const _raw: Record<string, number> = {};
    for (const k of keys) {
      _raw[k] = getScatterNumeric(p, k) ?? 0;
    }
    const row: BarChartRow = {
      id: p.id,
      label: shortPlayerLabel(p.name),
      _raw,
    };
    for (const k of keys) {
      row[k] = _raw[k] ?? 0;
    }
    return row;
  });
  if (!normalize || keys.length < 2) return rows;
  const maxByKey: Record<string, number> = {};
  for (const k of keys) {
    let m = 0;
    for (const r of rows) {
      m = Math.max(m, Math.abs(r._raw[k] ?? 0));
    }
    maxByKey[k] = m > 1e-12 ? m : 1;
  }
  return rows.map((r) => {
    const next: BarChartRow = { ...r, _raw: { ...r._raw } };
    for (const k of keys) {
      next[k] = (r._raw[k] ?? 0) / maxByKey[k];
    }
    return next;
  });
}

function BarRankTooltipContent({
  active,
  payload,
  metricLabel,
  showScaledNote,
}: {
  active?: boolean;
  payload?: unknown;
  metricLabel: (k: string) => string;
  showScaledNote: boolean;
}) {
  const items = Array.isArray(payload) ? payload : [];
  if (!active || !items.length) return null;
  const row = (items[0] as { payload?: BarChartRow } | undefined)?.payload;
  if (!row?.label) return null;
  return (
    <div className="rounded-lg border border-surface-elevated bg-[#1E293B] px-2.5 py-2 text-xs shadow-lg">
      <p className="mb-1 font-semibold text-slate-100">{row.label}</p>
      <ul className="space-y-0.5">
        {items.map((entry: unknown, idx: number) => {
          const p = entry as {
            dataKey?: string | number;
            value?: unknown;
          };
          const key = String(p.dataKey ?? idx);
          const raw = row._raw?.[key];
          const fallback =
            typeof p.value === "number"
              ? p.value
              : typeof p.value === "string"
                ? Number(p.value)
                : Number.NaN;
          return (
            <li key={key} className="text-slate-300">
              <span className="text-slate-400">{metricLabel(key)}:</span>{" "}
              <span className="font-mono tabular-nums">
                {raw !== undefined ? fmtDistValue(raw) : fmtDistValue(fallback)}
              </span>
            </li>
          );
        })}
      </ul>
      {showScaledNote ? (
        <p className="mt-1.5 border-t border-slate-600/80 pt-1.5 text-[10px] leading-snug text-slate-500">
          Bar length is each value divided by the max in this top list (per metric), so different
          units are comparable on one chart.
        </p>
      ) : null}
    </div>
  );
}

function formMetricValue(pt: FormPoint, key: string): number | null {
  const v = (pt as unknown as Record<string, unknown>)[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function mergeFormSingleMetric(
  forms: FormResponse[],
  metricKey: string,
): Record<string, string | number | null>[] {
  const dateMap = new Map<string, Record<string, string | number | null>>();
  forms.forEach((pf, pi) => {
    pf.series.forEach((point) => {
      const d = point.date;
      if (!dateMap.has(d)) dateMap.set(d, { date: d });
      const entry = dateMap.get(d)!;
      const v = formMetricValue(point, metricKey);
      entry[`p${pi}`] = v;
    });
  });
  return Array.from(dateMap.values()).sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  );
}

function buildSinglePlayerMultiMetricRows(
  series: FormPoint[],
  metricKeys: string[],
): Record<string, string | number | null>[] {
  return series.map((pt) => {
    const row: Record<string, string | number | null> = { date: pt.date };
    metricKeys.forEach((mk, i) => {
      row[`m${i}`] = formMetricValue(pt, mk);
    });
    return row;
  });
}

const BAT_FORM_LINE_METRICS: { key: string; label: string }[] = [
  { key: "composite", label: "Composite" },
  { key: "score_1", label: "Acceleration" },
  { key: "score_2", label: "Power" },
  { key: "score_3", label: "Control" },
  { key: "window_avg_sr", label: "Window SR" },
  { key: "window_avg_runs", label: "Window avg runs" },
  { key: "window_sr_vs_par", label: "SR vs par" },
  { key: "window_impact", label: "Impact" },
  { key: "window_boundary_pct", label: "Boundary %" },
  { key: "window_dot_control", label: "Dot control" },
  { key: "window_consistency", label: "Consistency" },
];

function fmtDistValue(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 100) return v.toFixed(1);
  if (a >= 10) return v.toFixed(2);
  return v.toFixed(3);
}

/** Shared value-axis range for box/violin/histogram (matches API min/max with small padding). */
function distributionValueDomain(data: LeaderboardDistributionResponse): {
  lo: number;
  hi: number;
} {
  const loRaw =
    data.min != null && data.whisker_low != null
      ? Math.min(data.min, data.whisker_low)
      : (data.min ?? data.whisker_low ?? 0);
  const hiRaw =
    data.max != null && data.whisker_high != null
      ? Math.max(data.max, data.whisker_high)
      : (data.max ?? data.whisker_high ?? 1);
  const span = hiRaw - loRaw || 1;
  const pad = span * 0.03;
  return { lo: loRaw - pad, hi: hiRaw + pad };
}

/** Frequency histogram (player counts per bin) — same bins as box/violin. */
function HistogramSvg({
  data,
  metricLabel,
}: {
  data: LeaderboardDistributionResponse;
  metricLabel: string;
}) {
  const W = 640;
  const padL = 44;
  const padR = 20;
  const padT = 10;
  const plotH = 168;
  const plotBottom = padT + plotH;
  const axisY = plotBottom + 22;
  const H = axisY + 18;
  const innerW = W - padL - padR;

  const { lo, hi } = distributionValueDomain(data);
  const xScale = (v: number) => padL + ((v - lo) / (hi - lo)) * innerW;

  const bins = data.histogram_bins ?? [];
  const maxC = Math.max(1, ...bins.map((b) => b.count));
  const med = data.median;
  const q1 = data.q1;
  const q3 = data.q3;
  const yTickCounts = [...new Set([0, Math.round(maxC * 0.5), maxC])].sort((a, b) => a - b);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full max-w-full text-primary"
      role="img"
      aria-label={`Histogram of ${metricLabel} for ${data.n} players`}
    >
      <title>
        Histogram: {metricLabel}, n={data.n}, peak count {maxC}
      </title>
      {/* y-axis grid + labels */}
      {yTickCounts.map((c) => {
        const y = plotBottom - (c / maxC) * plotH;
        return (
          <g key={`y-${c}`}>
            <line
              x1={padL}
              y1={y}
              x2={W - padR}
              y2={y}
              stroke="currentColor"
              strokeOpacity={0.08}
            />
            <text
              x={padL - 6}
              y={y + 3}
              textAnchor="end"
              className="fill-text-muted"
              style={{ fontSize: 9 }}
            >
              {c}
            </text>
          </g>
        );
      })}

      {q1 != null && q3 != null && (
        <rect
          x={xScale(Math.min(q1, q3))}
          y={padT}
          width={Math.max(2, Math.abs(xScale(q3) - xScale(q1)))}
          height={plotH}
          fill="currentColor"
          fillOpacity={0.06}
          rx={1}
        />
      )}

      {bins.map((b) => {
        const x0 = xScale(b.bin_start);
        const x1 = xScale(b.bin_end);
        const gap = bins.length > 80 ? 0 : 0.35;
        const bw = Math.max(1, x1 - x0 - gap);
        const h = (b.count / maxC) * plotH;
        return (
          <rect
            key={`${b.bin_start}-${b.bin_end}`}
            x={x0}
            y={plotBottom - h}
            width={bw}
            height={Math.max(h, b.count > 0 ? 1 : 0)}
            fill={chartColour(0)}
            fillOpacity={0.75}
            stroke="currentColor"
            strokeOpacity={0.2}
            strokeWidth={0.25}
          >
            <title>
              {fmtDistValue(b.bin_start)} – {fmtDistValue(b.bin_end)}: {b.count} player
              {b.count === 1 ? "" : "s"}
            </title>
          </rect>
        );
      })}

      {med != null && (
        <line
          x1={xScale(med)}
          x2={xScale(med)}
          y1={padT}
          y2={plotBottom}
          stroke="currentColor"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          strokeOpacity={0.65}
        >
          <title>Median {fmtDistValue(med)}</title>
        </line>
      )}

      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const v = lo + t * (hi - lo);
        const x = xScale(v);
        return (
          <g key={`x-${t}`}>
            <line
              x1={x}
              y1={plotBottom}
              x2={x}
              y2={plotBottom + 5}
              stroke="currentColor"
              strokeOpacity={0.35}
            />
            <text
              x={x}
              y={axisY}
              textAnchor="middle"
              className="fill-text-muted"
              style={{ fontSize: 9 }}
            >
              {fmtDistValue(v)}
            </text>
          </g>
        );
      })}
      <text
        x={padL + innerW / 2}
        y={H - 2}
        textAnchor="middle"
        className="fill-text-muted"
        style={{ fontSize: 10 }}
      >
        {metricLabel}
      </text>
    </svg>
  );
}

function DistributionSvg({
  data,
  mode,
  onOutlierClick,
}: {
  data: LeaderboardDistributionResponse;
  mode: BoxViolinMode;
  onOutlierClick: (playerId: string) => void;
}) {
  const W = 640;
  const padL = 32;
  const padR = 24;
  const innerW = W - padL - padR;
  const violinCy = 52;
  const maxViolinHalf = 44;
  const boxCy = 128;
  const boxHalfH = 14;

  const { lo, hi } = distributionValueDomain(data);

  const xScale = (v: number) => padL + ((v - lo) / (hi - lo)) * innerW;

  const bins = data.histogram_bins ?? [];
  const maxC = Math.max(1, ...bins.map((b) => b.count));

  const showViolin = mode === "violin" || mode === "both";
  const showBox = mode === "box" || mode === "both";

  const q1 = data.q1;
  const q3 = data.q3;
  const med = data.median;
  const wl = data.whisker_low;
  const wh = data.whisker_high;

  return (
    <svg
      viewBox={`0 0 ${W} 155`}
      className="h-auto w-full max-w-full text-primary"
      role="img"
      aria-label={`Distribution for ${data.metric}, sample size ${data.n}`}
    >
      <title>
        {data.metric}: n={data.n}, median {fmtDistValue(med)}, IQR{" "}
        {fmtDistValue(data.iqr)}
      </title>
      {/* x-axis ticks */}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const v = lo + t * (hi - lo);
        const x = xScale(v);
        return (
          <g key={t}>
            <line
              x1={x}
              y1={boxCy + boxHalfH + 6}
              x2={x}
              y2={boxCy + boxHalfH + 10}
              stroke="currentColor"
              strokeOpacity={0.35}
            />
            <text
              x={x}
              y={boxCy + boxHalfH + 24}
              textAnchor="middle"
              className="fill-text-muted"
              style={{ fontSize: 9 }}
            >
              {fmtDistValue(v)}
            </text>
          </g>
        );
      })}

      {showViolin &&
        bins.map((b) => {
          const h = (b.count / maxC) * maxViolinHalf;
          const x0 = xScale(b.bin_start);
          const x1 = xScale(b.bin_end);
          const w = Math.max(1.5, x1 - x0);
          return (
            <rect
              key={`${b.bin_start}-${b.bin_end}`}
              x={x0}
              y={violinCy - h}
              width={w}
              height={2 * h}
              fill="currentColor"
              fillOpacity={0.22}
              rx={1}
            />
          );
        })}

      {showBox && wl != null && wh != null && (
        <line
          x1={xScale(wl)}
          y1={boxCy}
          x2={xScale(wh)}
          y2={boxCy}
          stroke="currentColor"
          strokeWidth={2}
          strokeOpacity={0.85}
        />
      )}
      {showBox && q1 != null && q3 != null && (
        <rect
          x={xScale(Math.min(q1, q3))}
          y={boxCy - boxHalfH}
          width={Math.max(2, Math.abs(xScale(q3) - xScale(q1)))}
          height={2 * boxHalfH}
          fill="currentColor"
          fillOpacity={0.35}
          stroke="currentColor"
          strokeWidth={1}
          strokeOpacity={0.5}
          rx={2}
        />
      )}
      {showBox && med != null && (
        <line
          x1={xScale(med)}
          y1={boxCy - boxHalfH}
          x2={xScale(med)}
          y2={boxCy + boxHalfH}
          stroke="var(--color-background, #0f172a)"
          strokeWidth={2.5}
          strokeOpacity={0.95}
        />
      )}

      {data.outliers?.map((o, i) => (
        <circle
          key={`${o.player_id}-${i}`}
          cx={xScale(o.value)}
          cy={boxCy}
          r={4}
          fill="var(--color-danger, #f87171)"
          fillOpacity={0.9}
          stroke="rgba(255,255,255,0.4)"
          strokeWidth={0.5}
          className="cursor-pointer"
          onClick={() => onOutlierClick(o.player_id)}
        >
          <title>
            {o.player_name}: {fmtDistValue(o.value)}
          </title>
        </circle>
      ))}
    </svg>
  );
}

const BOWL_FORM_LINE_METRICS: { key: string; label: string }[] = [
  { key: "composite", label: "Composite" },
  { key: "score_1", label: "Accuracy" },
  { key: "score_2", label: "Control" },
  { key: "score_3", label: "Threat" },
  { key: "window_economy", label: "Economy" },
  { key: "window_dot_pct", label: "Dot %" },
  { key: "window_wickets_per_spell", label: "Wkts / spell" },
  { key: "window_total_wickets", label: "Window wickets" },
  { key: "window_economy_vs_par", label: "Econ vs par" },
  { key: "window_quality_wickets", label: "Quality wickets" },
  { key: "window_threat_pressure", label: "Threat pressure" },
];

interface RankingsChartsPanelProps {
  players: PlayerSummary[];
  isBowling: boolean;
  optionalScatterMetrics: ScatterMetricOption[];
  distributionFilters: LeaderboardDistributionFilters;
  distributionMetricOptions: { key: string; label: string }[];
  tableSortMetric: string;
}

export default function RankingsChartsPanel({
  players,
  isBowling,
  optionalScatterMetrics,
  distributionFilters,
  distributionMetricOptions,
  tableSortMetric,
}: RankingsChartsPanelProps) {
  const navigate = useNavigate();
  const role = isBowling ? "bowl" : "bat";
  const formMetricOptions = isBowling ? BOWL_FORM_LINE_METRICS : BAT_FORM_LINE_METRICS;

  const baseScatterOptions: ScatterMetricOption[] = useMemo(
    () => [
      { key: "rating_current", label: "Current (display)" },
      { key: "rating_overall", label: "Career overall (display)" },
      { key: "overall_score", label: "Pipeline overall score" },
      { key: "innings_count", label: isBowling ? "Matches / innings" : "Innings" },
      { key: "total_runs", label: isBowling ? "Wickets" : "Runs" },
      { key: "career_sr", label: isBowling ? "Economy" : "Strike rate" },
      { key: "career_avg", label: isBowling ? "Bowl SR (balls/wkt)" : "Average" },
      { key: "score_1", label: isBowling ? "Accuracy" : "Acceleration" },
      { key: "score_2", label: isBowling ? "Control" : "Power" },
      { key: "score_3", label: isBowling ? "Threat" : "Control" },
    ],
    [isBowling],
  );

  const scatterAxisOptions = useMemo(() => {
    const seen = new Set<string>();
    const out: ScatterMetricOption[] = [];
    for (const o of [...baseScatterOptions, ...optionalScatterMetrics]) {
      if (!seen.has(o.key)) {
        seen.add(o.key);
        out.push(o);
      }
    }
    return out;
  }, [baseScatterOptions, optionalScatterMetrics]);

  const [tab, setTab] = useState<ChartTab>("scatter");
  const [scatterX, setScatterX] = useState("rating_current");
  const [scatterY, setScatterY] = useState("career_sr");

  const defaultDistMetric = useMemo(() => {
    const opts = distributionMetricOptions;
    if (!opts.length) return isBowling ? "career_economy" : "rating_current";
    return opts.find((o) => o.key === tableSortMetric)?.key ?? opts[0]!.key;
  }, [distributionMetricOptions, tableSortMetric, isBowling]);

  const [distMetric, setDistMetric] = useState(defaultDistMetric);
  const [distPlotMode, setDistPlotMode] = useState<DistributionPlotMode>("both");

  useEffect(() => {
    setDistMetric((prev) => {
      if (distributionMetricOptions.some((o) => o.key === prev)) return prev;
      return defaultDistMetric;
    });
  }, [defaultDistMetric, distributionMetricOptions]);

  const unsupportedDistCtx =
    !isBowling &&
    Boolean(
      distributionFilters.ctx_knockouts_only || distributionFilters.ctx_chase_high_rpo,
    );

  const { data: distData, isLoading: distLoading, error: distError } =
    useLeaderboardDistribution({
      role,
      metric: distMetric,
      filters: distributionFilters,
      enabled:
        tab === "distribution" &&
        !unsupportedDistCtx &&
        distributionMetricOptions.length > 0,
    });

  const defaultBarRankBy = useMemo(() => {
    const opts = distributionMetricOptions;
    if (!opts.length) return isBowling ? "career_economy" : "total_runs";
    return (
      opts.find((o) => o.key === "total_runs")?.key ??
      opts.find((o) => o.key === tableSortMetric)?.key ??
      opts[0]!.key
    );
  }, [distributionMetricOptions, tableSortMetric, isBowling]);

  const [barRankBy, setBarRankBy] = useState(isBowling ? "career_economy" : "total_runs");
  const [barMetricB, setBarMetricB] = useState("career_avg");
  const [barMetricC, setBarMetricC] = useState(isBowling ? "innings_count" : "career_sr");
  const [barCompareMode, setBarCompareMode] = useState(false);
  const [barNormalize, setBarNormalize] = useState(true);
  const [barOrder, setBarOrder] = useState<"asc" | "desc">("desc");
  const [barLimit, setBarLimit] = useState(10);

  useEffect(() => {
    setBarRankBy((prev) =>
      distributionMetricOptions.some((o) => o.key === prev) ? prev : defaultBarRankBy,
    );
  }, [defaultBarRankBy, distributionMetricOptions]);

  useEffect(() => {
    const keys = new Set(distributionMetricOptions.map((o) => o.key));
    if (!keys.size) return;
    setBarMetricB((prev) =>
      keys.has(prev) ? prev : keys.has("career_avg") ? "career_avg" : [...keys][0]!,
    );
    setBarMetricC((prev) => {
      if (keys.has(prev)) return prev;
      if (isBowling && keys.has("innings_count")) return "innings_count";
      if (!isBowling && keys.has("career_sr")) return "career_sr";
      return [...keys].find((k) => k !== barRankBy) ?? prev;
    });
  }, [distributionMetricOptions, isBowling, barRankBy]);

  const barLeaderboardParams = useMemo((): Partial<LeaderboardParams> => {
    const lim = Math.min(MAX_BAR_ROWS, Math.max(MIN_BAR_ROWS, barLimit));
    return {
      sort: barRankBy,
      order: barOrder,
      country: distributionFilters.country,
      archetype: distributionFilters.archetype,
      position_group: distributionFilters.position_group,
      modal_slot: distributionFilters.modal_slot,
      phase_group: distributionFilters.phase_group,
      min_innings: distributionFilters.min_innings,
      provisional: distributionFilters.provisional,
      activity: distributionFilters.activity ?? "active",
      page: 1,
      per_page: lim,
      ...(isBowling
        ? {}
        : {
            ctx_entry_phase:
              distributionFilters.ctx_entry_phase &&
              distributionFilters.ctx_entry_phase !== "none"
                ? distributionFilters.ctx_entry_phase
                : undefined,
            ctx_knockouts_only: distributionFilters.ctx_knockouts_only,
            ctx_chase_high_rpo: distributionFilters.ctx_chase_high_rpo,
          }),
    };
  }, [barRankBy, barOrder, barLimit, distributionFilters, isBowling]);

  const {
    data: barLb,
    isLoading: barLoading,
    isFetching: barFetching,
    error: barError,
  } = useBarRankLeaderboard(role, barLeaderboardParams, {
    enabled: tab === "bars" && distributionMetricOptions.length > 0,
  });

  const barMetricKeys = useMemo(() => {
    if (!barCompareMode) return [barRankBy];
    return [...new Set([barRankBy, barMetricB, barMetricC])].slice(0, MAX_BAR_COMPARE_METRICS);
  }, [barCompareMode, barRankBy, barMetricB, barMetricC]);

  const barRows = useMemo(
    () =>
      buildBarChartRows(
        barLb?.players ?? [],
        barMetricKeys,
        barCompareMode && barNormalize && barMetricKeys.length > 1,
      ),
    [barLb?.players, barMetricKeys, barCompareMode, barNormalize],
  );

  const metricLabel = useCallback(
    (key: string) =>
      distributionMetricOptions.find((o) => o.key === key)?.label ?? key.replace(/_/g, " "),
    [distributionMetricOptions],
  );

  const barChartHeight = useMemo(
    () => Math.min(560, Math.max(200, barRows.length * 30 + 96)),
    [barRows.length],
  );

  const [heatView, setHeatView] = useState<HeatmapSubTab>("correlation");
  const [heatIntensitySort, setHeatIntensitySort] = useState("rating_current");
  const [heatIntensityTop, setHeatIntensityTop] = useState(20);
  const defaultHeatMetrics = useMemo(() => {
    const keys = new Set(distributionMetricOptions.map((o) => o.key));
    const pref = isBowling
      ? ["rating_current", "career_economy", "total_wickets", "matches", "overall_score"]
      : ["rating_current", "career_sr", "career_avg", "overall_score", "total_runs"];
    return pref.filter((k) => keys.has(k));
  }, [distributionMetricOptions, isBowling]);
  const [heatMetrics, setHeatMetrics] = useState<string[]>([]);
  useEffect(() => {
    setHeatMetrics((prev) => {
      const keys = new Set(distributionMetricOptions.map((o) => o.key));
      if (prev.length === 0) return defaultHeatMetrics;
      const ok = prev.filter((k) => keys.has(k));
      return ok.length >= 2 ? ok : defaultHeatMetrics;
    });
  }, [defaultHeatMetrics, distributionMetricOptions]);

  useEffect(() => {
    setHeatIntensitySort((prev) =>
      distributionMetricOptions.some((o) => o.key === prev) ? prev : "rating_current",
    );
  }, [distributionMetricOptions]);

  const heatmapParams = useMemo((): LeaderboardHeatmapParams => {
    const im =
      heatMetrics.length > 0 ? heatMetrics.slice(0, 10) : defaultHeatMetrics;
    return {
      ...distributionFilters,
      max_sample: 400,
      min_pair_obs: 12,
      intensity_top: heatIntensityTop,
      intensity_sort: heatIntensitySort,
      intensity_metrics: im.length > 0 ? im : undefined,
    };
  }, [
    distributionFilters,
    heatIntensityTop,
    heatIntensitySort,
    heatMetrics,
    defaultHeatMetrics,
  ]);

  const {
    data: heatData,
    isLoading: heatLoading,
    error: heatError,
  } = useLeaderboardHeatmap({
    role,
    params: heatmapParams,
    enabled:
      tab === "heatmap" &&
      !unsupportedDistCtx &&
      distributionMetricOptions.length > 0,
  });

  const toggleHeatMetric = useCallback((key: string) => {
    setHeatMetrics((prev) => {
      if (prev.includes(key)) {
        const next = prev.filter((k) => k !== key);
        return next.length >= 2 ? next : prev;
      }
      if (prev.length >= 10) return prev;
      return [...prev, key];
    });
  }, []);

  const [lineMode, setLineMode] = useState<LineMode>("single");
  const [singlePlayerId, setSinglePlayerId] = useState<string | null>(null);
  const [singleMetrics, setSingleMetrics] = useState<string[]>(["composite", "score_1"]);
  const [multiIds, setMultiIds] = useState<string[]>([]);
  const [multiMetric, setMultiMetric] = useState("composite");

  const defaultSingleId = players[0]?.id ?? null;
  const effectiveSingleId = singlePlayerId ?? defaultSingleId;

  const { data: singleForm, isLoading: singleFormLoading } = usePlayerForm(
    lineMode === "single" && tab === "line" ? effectiveSingleId ?? undefined : undefined,
    role,
    {
      enabled: tab === "line" && lineMode === "single" && Boolean(effectiveSingleId),
    },
  );

  const { data: multiForm, isLoading: multiFormLoading } = useCompareForm(multiIds, {
    enabled: tab === "line" && lineMode === "multi" && multiIds.length >= 2 && multiIds.length <= MAX_LINE_SERIES,
  });

  const scatterPoints = useMemo(() => {
    const pts: {
      id: string;
      name: string;
      x: number;
      y: number;
    }[] = [];
    for (const p of players) {
      const x = getScatterNumeric(p, scatterX);
      const y = getScatterNumeric(p, scatterY);
      if (x != null && y != null) {
        pts.push({ id: p.id, name: p.name, x, y });
      }
    }
    return pts;
  }, [players, scatterX, scatterY]);

  const scatterLabel = useCallback(
    (key: string) => scatterAxisOptions.find((o) => o.key === key)?.label ?? key,
    [scatterAxisOptions],
  );

  const singleLineData = useMemo(() => {
    const series = singleForm?.series ?? [];
    if (!series.length || !singleMetrics.length) return [];
    return buildSinglePlayerMultiMetricRows(series, singleMetrics.slice(0, MAX_LINE_SERIES));
  }, [singleForm?.series, singleMetrics]);

  const multiLineData = useMemo(() => {
    if (!multiForm?.length || multiIds.length < 2) return [];
    return mergeFormSingleMetric(multiForm, multiMetric);
  }, [multiForm, multiIds.length, multiMetric]);

  const toggleSingleMetric = useCallback((key: string) => {
    setSingleMetrics((prev) => {
      if (prev.includes(key)) {
        const next = prev.filter((k) => k !== key);
        return next.length > 0 ? next : prev;
      }
      if (prev.length >= MAX_LINE_SERIES) return prev;
      return [...prev, key];
    });
  }, []);

  const addMultiPlayer = useCallback(
    (p: PlayerSummary) => {
      setMultiIds((prev) => {
        if (prev.includes(p.id) || prev.length >= MAX_LINE_SERIES) return prev;
        return [...prev, p.id];
      });
    },
    [],
  );

  const removeMultiPlayer = useCallback((id: string) => {
    setMultiIds((prev) => prev.filter((x) => x !== id));
  }, []);

  const addPagePlayerToMulti = useCallback((p: PlayerSummary) => {
    addMultiPlayer(p);
  }, [addMultiPlayer]);

  const multiNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const pl of players) m.set(pl.id, pl.name);
    multiForm?.forEach((f) => m.set(f.player_id, f.player_name || f.player_id));
    return m;
  }, [players, multiForm]);

  return (
    <section className="card overflow-hidden p-4 md:p-5" aria-labelledby="rk-charts-heading">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2
            id="rk-charts-heading"
            className="text-h3 text-text-primary flex items-center gap-2 text-base font-semibold md:text-lg"
          >
            <BarChart3 size={18} className="shrink-0 text-primary" aria-hidden />
            Charts
          </h2>
          <p className="mt-1 text-xs text-text-secondary max-w-2xl">
            Scatter uses players on this page only. Line charts use rolling form time series (same
            engine as Compare). Distribution uses the full filtered leaderboard (same filters as the
            table)—box, density, or a frequency histogram.             Ranked bars shows the top N players by one stat (or compares up to three metrics on the same
            cohort). Heatmap shows Pearson correlations between numeric columns on a random sample, plus a
            player×metric intensity grid. Up to {MAX_LINE_SERIES} series per line chart.
          </p>
        </div>
        <div
          className="inline-flex flex-wrap gap-1 rounded-xl border border-surface-elevated bg-surface-elevated/20 p-1"
          role="tablist"
          aria-label="Chart type"
        >
          <button
            type="button"
            role="tab"
            aria-selected={tab === "scatter"}
            onClick={() => setTab("scatter")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
              tab === "scatter"
                ? "bg-primary text-white dark:text-background shadow-sm"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <ScatterIcon size={14} aria-hidden />
            Scatter
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "line"}
            onClick={() => setTab("line")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
              tab === "line"
                ? "bg-primary text-white dark:text-background shadow-sm"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <LineChartIcon size={14} aria-hidden />
            Over time
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "distribution"}
            onClick={() => setTab("distribution")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
              tab === "distribution"
                ? "bg-primary text-white dark:text-background shadow-sm"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <Activity size={14} aria-hidden />
            Distribution
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "bars"}
            onClick={() => setTab("bars")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
              tab === "bars"
                ? "bg-primary text-white dark:text-background shadow-sm"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <BarChart2 size={14} aria-hidden />
            Ranked bars
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "heatmap"}
            onClick={() => setTab("heatmap")}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
              tab === "heatmap"
                ? "bg-primary text-white dark:text-background shadow-sm"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <Grid3x3 size={14} aria-hidden />
            Heatmap
          </button>
        </div>
      </div>

      {tab === "scatter" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex min-w-[10rem] flex-col gap-1">
              <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                X axis
              </label>
              <select
                className="filter-select text-sm"
                value={scatterX}
                onChange={(e) => setScatterX(e.target.value)}
              >
                {scatterAxisOptions.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex min-w-[10rem] flex-col gap-1">
              <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                Y axis
              </label>
              <select
                className="filter-select text-sm"
                value={scatterY}
                onChange={(e) => setScatterY(e.target.value)}
              >
                {scatterAxisOptions.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {scatterPoints.length < 2 ? (
            <p className="text-sm text-text-muted">
              Need at least two players with numeric values for both axes on this page.
            </p>
          ) : (
            <div className="h-[320px] w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 12, right: 12, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.25} />
                  <XAxis
                    type="number"
                    dataKey="x"
                    name={scatterLabel(scatterX)}
                    tick={{ fill: "#94A3B8", fontSize: 11 }}
                    axisLine={{ stroke: "#334155" }}
                    label={{ value: scatterLabel(scatterX), position: "bottom", fill: "#94a3b8", fontSize: 11, offset: 0 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name={scatterLabel(scatterY)}
                    tick={{ fill: "#94A3B8", fontSize: 11 }}
                    axisLine={{ stroke: "#334155" }}
                    label={{ value: scatterLabel(scatterY), angle: -90, position: "insideLeft", fill: "#94a3b8", fontSize: 11 }}
                  />
                  <ZAxis range={[72, 72]} />
                  <RechartsTooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    contentStyle={{
                      backgroundColor: "#1E293B",
                      border: "1px solid #334155",
                      borderRadius: "0.5rem",
                      color: "#F8FAFC",
                    }}
                    formatter={(value: number, name: string) => [value.toFixed(2), name]}
                    labelFormatter={(_, payload) => {
                      const p = payload?.[0]?.payload as { name?: string; id?: string } | undefined;
                      return p?.name ?? "";
                    }}
                  />
                  <Scatter
                    data={scatterPoints}
                    fill={chartColour(0)}
                    shape={(props: unknown) => {
                      const { cx, cy, payload } = props as {
                        cx: number;
                        cy: number;
                        payload: { id: string; name: string; x: number; y: number };
                      };
                      return (
                        <circle
                          cx={cx}
                          cy={cy}
                          r={5}
                          fill={chartColour(0)}
                          stroke="rgba(255,255,255,0.35)"
                          strokeWidth={0.5}
                          className="cursor-pointer hover:opacity-90"
                          onClick={() => navigate(`/player/${payload.id}`)}
                        />
                      );
                    }}
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
          <p className="text-[11px] text-text-muted">
            Tip: click a player row on the leaderboard, then open their profile from the sidebar—or
            pick the same metrics here as in the table.
          </p>
        </div>
      )}

      {tab === "line" && (
        <div className="space-y-4">
          <div
            className="inline-flex rounded-lg border border-surface-elevated/80 p-0.5"
            role="tablist"
            aria-label="Line chart mode"
          >
            <button
              type="button"
              aria-pressed={lineMode === "single"}
              onClick={() => setLineMode("single")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                lineMode === "single"
                  ? "bg-surface-elevated text-text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              One player · multiple metrics
            </button>
            <button
              type="button"
              aria-pressed={lineMode === "multi"}
              onClick={() => setLineMode("multi")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                lineMode === "multi"
                  ? "bg-surface-elevated text-text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              Multiple players · one metric
            </button>
          </div>

          {lineMode === "single" && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-[12rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Player
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={effectiveSingleId ?? ""}
                    onChange={(e) =>
                      setSinglePlayerId(e.target.value || null)
                    }
                  >
                    {players.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="min-w-[12rem] flex-1 max-w-md">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1 block">
                    Or search any player
                  </label>
                  <PlayerAutocomplete
                    size="sm"
                    role={role}
                    excludeIds={effectiveSingleId ? [effectiveSingleId] : []}
                    onSelect={(p) => setSinglePlayerId(p.id)}
                    placeholder="Add by name…"
                  />
                </div>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-2">
                  Metrics (max {MAX_LINE_SERIES})
                </p>
                <div className="flex flex-wrap gap-2">
                  {formMetricOptions.map((m) => (
                    <label
                      key={m.key}
                      className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs ${
                        singleMetrics.includes(m.key)
                          ? "border-primary/50 bg-primary/10 text-text-primary"
                          : "border-surface-elevated text-text-secondary hover:border-surface-elevated/80"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="rounded border-surface-elevated"
                        checked={singleMetrics.includes(m.key)}
                        onChange={() => toggleSingleMetric(m.key)}
                      />
                      {m.label}
                    </label>
                  ))}
                </div>
              </div>
              {singleFormLoading ? (
                <p className="text-sm text-text-muted">Loading form…</p>
              ) : singleLineData.length === 0 ? (
                <p className="text-sm text-text-muted">No form series for this player in this dataset.</p>
              ) : (
                <div className="h-[320px] w-full min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={singleLineData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.25} />
                      <XAxis
                        dataKey="date"
                        tick={{ fill: "#94A3B8", fontSize: 10 }}
                        axisLine={{ stroke: "#334155" }}
                        tickFormatter={(v: string) => (v ? v.slice(0, 7) : "")}
                        interval="preserveStartEnd"
                      />
                      <YAxis tick={{ fill: "#94A3B8", fontSize: 11 }} axisLine={{ stroke: "#334155" }} domain={["auto", "auto"]} />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: "#1E293B",
                          border: "1px solid #334155",
                          borderRadius: "0.5rem",
                          color: "#F8FAFC",
                        }}
                        labelFormatter={(label: string) => fmtDate(label) ?? label}
                      />
                      <Legend />
                      {singleMetrics.slice(0, MAX_LINE_SERIES).map((mk, i) => (
                        <Line
                          key={mk}
                          type="monotone"
                          dataKey={`m${i}`}
                          name={formMetricOptions.find((o) => o.key === mk)?.label ?? mk}
                          stroke={chartColour(i)}
                          strokeWidth={2}
                          dot={false}
                          connectNulls
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          )}

          {lineMode === "multi" && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-text-muted w-full">
                  From this page (tap to add, max {MAX_LINE_SERIES})
                </span>
                {players.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    disabled={multiIds.includes(p.id) || multiIds.length >= MAX_LINE_SERIES}
                    onClick={() => addPagePlayerToMulti(p)}
                    className="rounded-lg border border-surface-elevated px-2 py-1 text-xs font-medium text-text-secondary hover:border-primary/40 hover:text-text-primary disabled:opacity-40"
                  >
                    + {p.name}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-end gap-3">
                <div className="min-w-[12rem] flex-1 max-w-md">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1 block">
                    Add player by search
                  </label>
                  <PlayerAutocomplete
                    size="sm"
                    role={role}
                    excludeIds={multiIds}
                    onSelect={addMultiPlayer}
                    placeholder="Search…"
                  />
                </div>
                <div className="flex min-w-[10rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Metric
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={multiMetric}
                    onChange={(e) => setMultiMetric(e.target.value)}
                  >
                    {formMetricOptions.map((m) => (
                      <option key={m.key} value={m.key}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {multiIds.length > 0 && (
                <ul className="flex flex-wrap gap-2 text-xs">
                  {multiIds.map((id) => (
                    <li
                      key={id}
                      className="inline-flex items-center gap-1 rounded-full border border-surface-elevated bg-surface-elevated/30 px-2 py-0.5"
                    >
                      <span className="max-w-[10rem] truncate">{multiNameById.get(id) ?? id}</span>
                      <button
                        type="button"
                        className="text-text-muted hover:text-danger"
                        aria-label={`Remove ${multiNameById.get(id)}`}
                        onClick={() => removeMultiPlayer(id)}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {multiIds.length < 2 ? (
                <p className="text-sm text-text-muted">Select at least two players to compare over time.</p>
              ) : multiFormLoading ? (
                <p className="text-sm text-text-muted">Loading form…</p>
              ) : multiLineData.length === 0 ? (
                <p className="text-sm text-text-muted">No overlapping dates for this metric.</p>
              ) : (
                <div className="h-[320px] w-full min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={multiLineData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.25} />
                      <XAxis
                        dataKey="date"
                        tick={{ fill: "#94A3B8", fontSize: 10 }}
                        axisLine={{ stroke: "#334155" }}
                        tickFormatter={(v: string) => (v ? v.slice(0, 7) : "")}
                        interval="preserveStartEnd"
                      />
                      <YAxis tick={{ fill: "#94A3B8", fontSize: 11 }} axisLine={{ stroke: "#334155" }} domain={["auto", "auto"]} />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: "#1E293B",
                          border: "1px solid #334155",
                          borderRadius: "0.5rem",
                          color: "#F8FAFC",
                        }}
                        labelFormatter={(label: string) => fmtDate(label) ?? label}
                      />
                      <Legend />
                      {multiForm?.map((pf, pi) => (
                        <Line
                          key={pf.player_id}
                          type="monotone"
                          dataKey={`p${pi}`}
                          name={pf.player_name || pf.player_id}
                          stroke={chartColour(pi)}
                          strokeWidth={2}
                          dot={false}
                          connectNulls
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {tab === "bars" && (
        <div className="space-y-4">
          {distributionMetricOptions.length === 0 ? (
            <p className="text-sm text-text-muted">Loading sort columns…</p>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-[11rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Rank by
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={barRankBy}
                    onChange={(e) => setBarRankBy(e.target.value)}
                  >
                    {distributionMetricOptions.map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex min-w-[7rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Order
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={barOrder}
                    onChange={(e) => setBarOrder(e.target.value as "asc" | "desc")}
                  >
                    <option value="desc">High → low</option>
                    <option value="asc">Low → high</option>
                  </select>
                </div>
                <div className="flex min-w-[6rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Top
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={barLimit}
                    onChange={(e) => setBarLimit(Number(e.target.value))}
                  >
                    {[5, 10, 15, 20, 25].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
                <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-surface-elevated/80 px-2.5 py-2 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    className="rounded border-surface-elevated"
                    checked={barCompareMode}
                    onChange={(e) => setBarCompareMode(e.target.checked)}
                  />
                  Compare metrics
                </label>
              </div>

              {barCompareMode && (
                <div className="flex flex-wrap items-end gap-3">
                  <div className="flex min-w-[11rem] flex-col gap-1">
                    <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                      Metric 2
                    </label>
                    <select
                      className="filter-select text-sm"
                      value={barMetricB}
                      onChange={(e) => setBarMetricB(e.target.value)}
                    >
                      {distributionMetricOptions.map((o) => (
                        <option key={o.key} value={o.key}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex min-w-[11rem] flex-col gap-1">
                    <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                      Metric 3
                    </label>
                    <select
                      className="filter-select text-sm"
                      value={barMetricC}
                      onChange={(e) => setBarMetricC(e.target.value)}
                    >
                      {distributionMetricOptions.map((o) => (
                        <option key={o.key} value={o.key}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-text-secondary">
                    <input
                      type="checkbox"
                      className="rounded border-surface-elevated"
                      checked={barNormalize}
                      onChange={(e) => setBarNormalize(e.target.checked)}
                    />
                    Scale each metric 0–1 vs max in list
                  </label>
                </div>
              )}

              {barLoading ? (
                <p className="text-sm text-text-muted">Loading leaderboard…</p>
              ) : barError ? (
                <p className="text-sm text-danger">Could not load bar chart.</p>
              ) : barRows.length === 0 ? (
                <p className="text-sm text-text-muted">
                  No players returned for these filters (try relaxing min innings or filters).
                </p>
              ) : (
                <>
                  {barFetching && !barLoading && (
                    <p className="text-xs text-text-muted animate-pulse">Updating…</p>
                  )}
                  <div className="w-full min-w-0" style={{ height: barChartHeight }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        layout="vertical"
                        data={barRows}
                        margin={{ top: 4, right: 12, left: 4, bottom: 4 }}
                        onClick={(state) => {
                          const id = (state?.activePayload?.[0]?.payload as BarChartRow | undefined)
                            ?.id;
                          if (id) navigate(`/player/${id}`);
                        }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.2} />
                        <XAxis
                          type="number"
                          tick={{ fill: "#94A3B8", fontSize: 10 }}
                          axisLine={{ stroke: "#334155" }}
                          domain={
                            barCompareMode && barNormalize && barMetricKeys.length > 1
                              ? [0, 1.05]
                              : [0, "auto"]
                          }
                        />
                        <YAxis
                          type="category"
                          dataKey="label"
                          width={108}
                          tick={{ fill: "#94A3B8", fontSize: 10 }}
                          axisLine={{ stroke: "#334155" }}
                        />
                        <RechartsTooltip
                          cursor={{ fill: "rgba(148, 163, 184, 0.08)" }}
                          content={(tooltipProps) => (
                            <BarRankTooltipContent
                              active={tooltipProps.active}
                              payload={tooltipProps.payload}
                              metricLabel={metricLabel}
                              showScaledNote={
                                barCompareMode && barNormalize && barMetricKeys.length > 1
                              }
                            />
                          )}
                        />
                        {barMetricKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
                        {barMetricKeys.map((mk, i) => (
                          <Bar
                            key={mk}
                            dataKey={mk}
                            name={metricLabel(mk)}
                            fill={chartColour(i)}
                            radius={[0, 2, 2, 0]}
                            maxBarSize={barCompareMode ? 18 : 28}
                          />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="text-[11px] text-text-muted">
                    Same filters and activity rules as the leaderboard table. Click a row to open the
                    player profile. In compare mode, pick up to three columns; optional scaling divides
                    each value by the best in this top list so different units sit on one axis.
                  </p>
                </>
              )}
            </>
          )}
        </div>
      )}

      {tab === "heatmap" && (
        <div className="space-y-4">
          {unsupportedDistCtx ? (
            <p className="text-sm text-text-muted">
              Heatmap uses the same pool as the leaderboard and is not available with knockouts-only or
              high required-rate chase filters yet.
            </p>
          ) : distributionMetricOptions.length === 0 ? (
            <p className="text-sm text-text-muted">Loading sort columns…</p>
          ) : (
            <>
              <div
                className="inline-flex rounded-lg border border-surface-elevated/80 p-0.5"
                role="tablist"
                aria-label="Heatmap view"
              >
                <button
                  type="button"
                  aria-pressed={heatView === "correlation"}
                  onClick={() => setHeatView("correlation")}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    heatView === "correlation"
                      ? "bg-surface-elevated text-text-primary"
                      : "text-text-muted hover:text-text-primary"
                  }`}
                >
                  Correlation matrix
                </button>
                <button
                  type="button"
                  aria-pressed={heatView === "intensity"}
                  onClick={() => setHeatView("intensity")}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    heatView === "intensity"
                      ? "bg-surface-elevated text-text-primary"
                      : "text-text-muted hover:text-text-primary"
                  }`}
                >
                  Players × metrics
                </button>
              </div>

              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-[11rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Intensity: rank by
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={heatIntensitySort}
                    onChange={(e) => setHeatIntensitySort(e.target.value)}
                  >
                    {distributionMetricOptions.map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex min-w-[7rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Intensity: top
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={heatIntensityTop}
                    onChange={(e) => setHeatIntensityTop(Number(e.target.value))}
                  >
                    {[10, 15, 20, 25, 30, 35].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-2">
                  Intensity columns (2–10 metrics)
                </p>
                <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto">
                  {distributionMetricOptions.map((o) => (
                    <label
                      key={o.key}
                      className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2 py-1 text-xs ${
                        heatMetrics.includes(o.key)
                          ? "border-primary/50 bg-primary/10 text-text-primary"
                          : "border-surface-elevated text-text-secondary"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="rounded border-surface-elevated"
                        checked={heatMetrics.includes(o.key)}
                        onChange={() => toggleHeatMetric(o.key)}
                      />
                      {o.label}
                    </label>
                  ))}
                </div>
              </div>

              {heatLoading ? (
                <p className="text-sm text-text-muted">Loading heatmap…</p>
              ) : heatError ? (
                <p className="text-sm text-danger">Could not load heatmap.</p>
              ) : !heatData || heatData.n_players === 0 ? (
                <p className="text-sm text-text-muted">
                  No players in the filtered pool for this sample (try relaxing filters).
                </p>
              ) : (
                <>
                  <p className="text-xs text-text-secondary">
                    Sample of <span className="font-mono font-medium">{heatData.n_players}</span>{" "}
                    players (random from current filters). Correlations need enough non-null pairs per
                    cell; blank cells are inconclusive.
                  </p>

                  {heatView === "correlation" &&
                  heatData.correlation_columns.length > 0 &&
                  heatData.correlation.length > 0 ? (
                    <div className="overflow-auto max-h-[min(70vh,720px)] rounded-lg border border-surface-elevated/60">
                      <table className="w-max min-w-full border-collapse text-[10px]">
                        <thead>
                          <tr>
                            <th className="sticky left-0 z-20 border-b border-r border-surface-elevated/50 bg-surface-elevated/90 px-1.5 py-1 text-left font-semibold text-text-muted backdrop-blur-sm">
                              Metric
                            </th>
                            {heatData.correlation_columns.map((c) => (
                              <th
                                key={c}
                                className="border-b border-surface-elevated/50 px-1 py-1 text-center font-semibold text-text-muted"
                                title={metricLabel(c)}
                              >
                                {c.length > 10 ? `${c.slice(0, 9)}…` : c}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {heatData.correlation_columns.map((rowKey, i) => (
                            <tr key={rowKey}>
                              <th
                                className="sticky left-0 z-10 border-r border-surface-elevated/40 bg-surface-elevated/80 px-1.5 py-0.5 text-left font-medium text-text-secondary backdrop-blur-sm"
                                title={metricLabel(rowKey)}
                              >
                                {rowKey.length > 14 ? `${rowKey.slice(0, 13)}…` : rowKey}
                              </th>
                              {heatData.correlation_columns.map((colKey, j) => {
                                const v = heatData.correlation[i]?.[j] ?? null;
                                return (
                                  <td
                                    key={colKey}
                                    className="border-b border-surface-elevated/30 px-1 py-0.5 text-center font-mono tabular-nums text-text-primary"
                                    style={{ backgroundColor: corrCellBg(v) }}
                                    title={`${metricLabel(rowKey)} vs ${metricLabel(colKey)}: ${
                                      v == null ? "n/a" : v.toFixed(3)
                                    }`}
                                  >
                                    {v == null ? "—" : v.toFixed(2)}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : heatView === "correlation" ? (
                    <p className="text-sm text-text-muted">Not enough numeric columns in this dataset slice.</p>
                  ) : null}

                  {heatView === "intensity" &&
                  heatData.intensity_player_ids.length > 0 &&
                  heatData.intensity_metrics.length > 0 ? (
                    <div className="overflow-auto max-h-[min(70vh,720px)] rounded-lg border border-surface-elevated/60">
                      <table className="w-max min-w-full border-collapse text-[10px]">
                        <thead>
                          <tr>
                            <th className="sticky left-0 z-20 border-b border-r border-surface-elevated/50 bg-surface-elevated/90 px-2 py-1 text-left text-text-muted backdrop-blur-sm">
                              Player
                            </th>
                            {heatData.intensity_metrics.map((m) => (
                              <th
                                key={m}
                                className="border-b border-surface-elevated/50 px-1.5 py-1 text-center font-semibold text-text-muted"
                                title={metricLabel(m)}
                              >
                                {m.length > 12 ? `${m.slice(0, 11)}…` : m}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {heatData.intensity_player_names.map((name, ri) => (
                            <tr key={heatData.intensity_player_ids[ri] ?? ri}>
                              <th
                                className="sticky left-0 z-10 cursor-pointer border-r border-surface-elevated/40 bg-surface-elevated/80 px-2 py-0.5 text-left font-medium text-primary hover:underline backdrop-blur-sm"
                                onClick={() =>
                                  navigate(`/player/${heatData.intensity_player_ids[ri]}`)
                                }
                              >
                                {name}
                              </th>
                              {(heatData.intensity_matrix[ri] ?? []).map((cell, ci) => (
                                <td
                                  key={heatData.intensity_metrics[ci] ?? ci}
                                  className="border-b border-surface-elevated/30 px-1 py-0.5 text-center font-mono tabular-nums"
                                  style={{ backgroundColor: intensityCellBg(cell) }}
                                  title={
                                    cell == null
                                      ? undefined
                                      : `${metricLabel(heatData.intensity_metrics[ci] ?? "")}: ${cell.toFixed(3)} (normalized in column)`
                                  }
                                >
                                  {cell == null ? "—" : cell.toFixed(2)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : heatView === "intensity" ? (
                    <p className="text-sm text-text-muted">No intensity rows for this selection.</p>
                  ) : null}

                  <p className="text-[11px] text-text-muted">
                    Intensity cells are min–max normalized within each column for the selected top
                    players only (0 = lowest in column, 1 = highest). Correlation uses Pearson r on the
                    same random sample.
                  </p>
                </>
              )}
            </>
          )}
        </div>
      )}

      {tab === "distribution" && (
        <div className="space-y-4">
          {unsupportedDistCtx ? (
            <p className="text-sm text-text-muted">
              Distribution is not available together with knockouts-only or high required-rate chase
              filters yet. Clear those filters to see the full pool.
            </p>
          ) : distributionMetricOptions.length === 0 ? (
            <p className="text-sm text-text-muted">Loading sort columns…</p>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-[12rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    Metric (full filtered pool)
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={distMetric}
                    onChange={(e) => setDistMetric(e.target.value)}
                  >
                    {distributionMetricOptions.map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex min-w-[10rem] flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                    View
                  </label>
                  <select
                    className="filter-select text-sm"
                    value={distPlotMode}
                    onChange={(e) => setDistPlotMode(e.target.value as DistributionPlotMode)}
                  >
                    <option value="both">Box + density</option>
                    <option value="box">Box only</option>
                    <option value="violin">Density only</option>
                    <option value="histogram">Histogram (frequency)</option>
                  </select>
                </div>
              </div>

              {distLoading ? (
                <p className="text-sm text-text-muted">Loading distribution…</p>
              ) : distError ? (
                <p className="text-sm text-danger">Could not load distribution.</p>
              ) : !distData || distData.n === 0 ? (
                <p className="text-sm text-text-muted">
                  No numeric values for this metric with the current filters (or sample too small).
                </p>
              ) : (
                <>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                    <div>
                      <dt className="text-text-muted">n</dt>
                      <dd className="font-mono font-semibold text-text-primary">
                        {distData.n.toLocaleString()}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-text-muted">Min · Max</dt>
                      <dd className="font-mono text-text-primary">
                        {fmtDistValue(distData.min)} · {fmtDistValue(distData.max)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-text-muted">Q1 · Med · Q3</dt>
                      <dd className="font-mono text-text-primary">
                        {fmtDistValue(distData.q1)} · {fmtDistValue(distData.median)} ·{" "}
                        {fmtDistValue(distData.q3)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-text-muted">Mean · IQR</dt>
                      <dd className="font-mono text-text-primary">
                        {fmtDistValue(distData.mean)} · {fmtDistValue(distData.iqr)}
                      </dd>
                    </div>
                  </dl>
                  <div className="rounded-lg border border-surface-elevated/60 bg-surface-elevated/10 p-2">
                    {distPlotMode === "histogram" ? (
                      <HistogramSvg
                        data={distData}
                        metricLabel={
                          distributionMetricOptions.find((o) => o.key === distMetric)?.label ??
                          distMetric.replace(/_/g, " ")
                        }
                      />
                    ) : (
                      <DistributionSvg
                        data={distData}
                        mode={distPlotMode}
                        onOutlierClick={(id) => navigate(`/player/${id}`)}
                      />
                    )}
                  </div>
                  <p className="text-[11px] text-text-muted">
                    {distPlotMode === "histogram" ? (
                      <>
                        Bar height is how many players fall in each metric range (equal-width bins).
                        Shaded band is the interquartile range; dashed line is the median. Hover a bar
                        for exact counts.
                      </>
                    ) : (
                      <>
                        Box: whiskers to the furthest points inside 1.5×IQR; red dots are outliers
                        (Tukey fences). Mirrored bars approximate density from the same histogram as
                        the backend. Click an outlier to open the player profile.
                      </>
                    )}
                  </p>
                  {distData.outliers.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted mb-1">
                        Outliers ({distData.outliers.length}
                        {distData.outliers.length >= 50 ? "+" : ""})
                      </p>
                      <ul className="max-h-36 overflow-y-auto text-xs space-y-0.5">
                        {distData.outliers.map((o) => (
                          <li key={o.player_id}>
                            <button
                              type="button"
                              className="text-left text-primary hover:underline"
                              onClick={() => navigate(`/player/${o.player_id}`)}
                            >
                              {o.player_name}
                            </button>
                            <span className="text-text-muted font-mono ml-1">
                              {fmtDistValue(o.value)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
