/**
 * Eras — Era Explorer page showing how T20I cricket has evolved over time.
 *
 * Route: /eras
 *
 * Features:
 *   - Line chart showing par SR, boundary rate, and dot% over time
 *   - Era multiplier table with colour-coded values
 *   - Cross-era player comparison with radar chart
 *   - Explanation of what era multipliers mean
 *   - Responsive layout
 *
 * Follows gui.md § 6.9 "Era Explorer".
 */

import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  Calendar,
  TrendingUp,
  Info,
  Users,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import { useEras, usePlayerProfile } from "@/api/queries";
import { isBatterProfile, isBowlerProfile } from "@/api/types";
import type { PlayerProfile } from "@/api/types";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import GradeBadge from "@/components/GradeBadge";
import ScoreBar from "@/components/ScoreBar";
import { countryFlag } from "@/lib/format";
import { CHART_COLOURS, chartColour, chartColourAlpha } from "@/lib/colours";

// ── Chart metric configuration ───────────────────────────────────

type ChartMetric =
  | "par_sr"
  | "boundary_rate"
  | "dot_pct"
  | "multiplier"
  | "avg_rr"
  | "predicted_score";

interface MetricConfig {
  key: ChartMetric;
  label: string;
  colour: string;
  yAxisId: string;
  unit: string;
  formatter: (v: number | null) => string;
}

const METRIC_CONFIGS: MetricConfig[] = [
  {
    key: "par_sr",
    label: "Par Strike Rate",
    colour: "#3B82F6",
    yAxisId: "left",
    unit: "",
    formatter: (v) => (v != null ? v.toFixed(1) : "—"),
  },
  {
    key: "boundary_rate",
    label: "Boundary Rate %",
    colour: "#10B981",
    yAxisId: "right",
    unit: "%",
    formatter: (v) => (v != null ? v.toFixed(1) + "%" : "—"),
  },
  {
    key: "dot_pct",
    label: "Dot Ball %",
    colour: "#F59E0B",
    yAxisId: "right",
    unit: "%",
    formatter: (v) => (v != null ? v.toFixed(1) + "%" : "—"),
  },
  {
    key: "avg_rr",
    label: "Avg Run Rate",
    colour: "#8B5CF6",
    yAxisId: "left",
    unit: " RPO",
    formatter: (v) => (v != null ? v.toFixed(2) + " RPO" : "—"),
  },
  {
    key: "predicted_score",
    label: "Predicted Score",
    colour: "#EC4899",
    yAxisId: "left",
    unit: "",
    formatter: (v) => (v != null ? Math.round(v).toString() : "—"),
  },
];

// ── Multiplier colour helper ─────────────────────────────────────

function multiplierColour(m: number | null): string {
  if (m == null) return "#64748B";
  if (m >= 1.2) return "#FFD700";
  if (m >= 1.1) return "#10B981";
  if (m >= 1.05) return "#22C55E";
  if (m >= 0.98) return "#3B82F6";
  return "#64748B";
}

function multiplierLabel(m: number | null): string {
  if (m == null) return "—";
  if (m >= 1.2) return "Much harder era";
  if (m >= 1.1) return "Harder era";
  if (m >= 1.05) return "Slightly harder era";
  if (m >= 0.98) return "Modern baseline";
  return "Easier era";
}

// ── Custom tooltip component ─────────────────────────────────────

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div
      style={{
        backgroundColor: "rgba(15, 23, 42, 0.95)",
        border: "1px solid rgba(51, 65, 85, 0.5)",
        borderRadius: "8px",
        padding: "10px 14px",
        fontSize: "13px",
      }}
    >
      <p style={{ color: "#94A3B8", marginBottom: "6px", fontWeight: 600 }}>
        {label}
      </p>
      {payload.map((entry, i) => (
        <p key={i} style={{ color: entry.color, margin: "2px 0" }}>
          {entry.name}:{" "}
          <strong>
            {typeof entry.value === "number" ? entry.value.toFixed(1) : "—"}
          </strong>
        </p>
      ))}
    </div>
  );
}

// ── Collapsible section helper ───────────────────────────────────

function CollapsibleSection({
  title,
  icon,
  defaultOpen = true,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-surface-elevated/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-h3 text-text-primary">{title}</h2>
        </div>
        {open ? (
          <ChevronUp size={18} className="text-text-muted" />
        ) : (
          <ChevronDown size={18} className="text-text-muted" />
        )}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}

// ── Simple SVG radar for cross-era comparison ────────────────────

interface RadarPoint {
  label: string;
  shortLabel: string;
  values: (number | null)[];
}

function ComparisonRadar({
  axes,
  playerNames,
  playerColours,
}: {
  axes: RadarPoint[];
  playerNames: string[];
  playerColours: string[];
}) {
  const size = 280;
  const center = size / 2;
  const maxRadius = size / 2 - 40;
  const n = axes.length;

  if (n < 3) return null;

  const angleStep = (2 * Math.PI) / n;
  const startAngle = -Math.PI / 2;
  const gridLevels = [20, 40, 60, 80, 100];

  // Compute polygon paths for each player
  const polygons = playerNames.map((_, pIdx) => {
    const points = axes.map((axis, i) => {
      const val = axis.values[pIdx] ?? 0;
      const r = (Math.min(100, Math.max(0, val)) / 100) * maxRadius;
      const angle = startAngle + i * angleStep;
      return `${center + r * Math.cos(angle)},${center + r * Math.sin(angle)}`;
    });
    return points.join(" ");
  });

  return (
    <div className="flex flex-col items-center gap-3">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="overflow-visible"
      >
        {/* Grid circles */}
        {gridLevels.map((level) => {
          const r = (level / 100) * maxRadius;
          const points = Array.from({ length: n }, (_, i) => {
            const angle = startAngle + i * angleStep;
            return `${center + r * Math.cos(angle)},${center + r * Math.sin(angle)}`;
          }).join(" ");
          return (
            <polygon
              key={level}
              points={points}
              fill="none"
              stroke="rgba(100, 116, 139, 0.2)"
              strokeWidth={0.5}
            />
          );
        })}

        {/* Axis lines */}
        {axes.map((_, i) => {
          const angle = startAngle + i * angleStep;
          const endX = center + maxRadius * Math.cos(angle);
          const endY = center + maxRadius * Math.sin(angle);
          return (
            <line
              key={i}
              x1={center}
              y1={center}
              x2={endX}
              y2={endY}
              stroke="rgba(100, 116, 139, 0.15)"
              strokeWidth={0.5}
            />
          );
        })}

        {/* Player polygons */}
        {polygons.map((poly, pIdx) => (
          <polygon
            key={pIdx}
            points={poly}
            fill={chartColourAlpha(pIdx, 0.15)}
            stroke={playerColours[pIdx]}
            strokeWidth={2}
          />
        ))}

        {/* Data points */}
        {playerNames.map((_, pIdx) =>
          axes.map((axis, i) => {
            const val = axis.values[pIdx] ?? 0;
            const r = (Math.min(100, Math.max(0, val)) / 100) * maxRadius;
            const angle = startAngle + i * angleStep;
            const cx = center + r * Math.cos(angle);
            const cy = center + r * Math.sin(angle);
            return (
              <circle
                key={`${pIdx}-${i}`}
                cx={cx}
                cy={cy}
                r={3}
                fill={playerColours[pIdx]}
              />
            );
          }),
        )}

        {/* Axis labels */}
        {axes.map((axis, i) => {
          const angle = startAngle + i * angleStep;
          const labelR = maxRadius + 20;
          const x = center + labelR * Math.cos(angle);
          const y = center + labelR * Math.sin(angle);
          return (
            <text
              key={i}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-text-secondary"
              fontSize={11}
              fontWeight={500}
            >
              {axis.shortLabel}
            </text>
          );
        })}
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4">
        {playerNames.map((name, i) => (
          <span key={i} className="inline-flex items-center gap-1.5 text-sm">
            <span
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: playerColours[i] }}
            />
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Main page component ──────────────────────────────────────────

export default function Eras() {
  const navigate = useNavigate();

  // Fetch era data
  const { data: eraData, isLoading, error } = useEras();

  // Active chart metrics (toggleable)
  const [activeMetrics, setActiveMetrics] = useState<Set<ChartMetric>>(
    new Set(["par_sr", "boundary_rate", "dot_pct"]),
  );

  // Cross-era comparison state
  const [comparePlayer1Id, setComparePlayer1Id] = useState<string | undefined>(
    undefined,
  );
  const [comparePlayer2Id, setComparePlayer2Id] = useState<string | undefined>(
    undefined,
  );

  const { data: profile1 } = usePlayerProfile(comparePlayer1Id, {
    enabled: !!comparePlayer1Id,
  });
  const { data: profile2 } = usePlayerProfile(comparePlayer2Id, {
    enabled: !!comparePlayer2Id,
  });

  const baselines = eraData?.baselines ?? [];

  // Prepare chart data
  const chartData = useMemo(() => {
    return baselines.map((b) => ({
      year: b.year,
      par_sr: b.par_sr,
      boundary_rate: b.boundary_rate,
      dot_pct: b.dot_pct,
      multiplier: b.multiplier,
      avg_rr:
        b.par_sr != null ? Number(((b.par_sr / 100) * 6).toFixed(2)) : null,
      predicted_score:
        b.par_sr != null ? Math.round((b.par_sr / 100) * 6 * 20) : null,
    }));
  }, [baselines]);

  // Toggle a metric
  const toggleMetric = (key: ChartMetric) => {
    setActiveMetrics((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  // Get scores for cross-era comparison
  const getScores = (
    profile: PlayerProfile | undefined,
  ): {
    s1: number | null;
    s2: number | null;
    s3: number | null;
    labels: [string, string, string];
  } => {
    if (!profile)
      return { s1: null, s2: null, s3: null, labels: ["—", "—", "—"] };
    if (isBatterProfile(profile)) {
      return {
        s1: profile.score_acceleration,
        s2: profile.score_power,
        s3: profile.score_control,
        labels: ["ACC", "POW", "CTL"],
      };
    }
    if (isBowlerProfile(profile)) {
      return {
        s1: profile.score_accuracy,
        s2: profile.score_control,
        s3: profile.score_threat,
        labels: ["ACR", "CTL", "THR"],
      };
    }
    return { s1: null, s2: null, s3: null, labels: ["—", "—", "—"] };
  };

  const scores1 = getScores(profile1);
  const scores2 = getScores(profile2);

  // Build radar axes if both players selected
  const radarAxes = useMemo<RadarPoint[]>(() => {
    if (!profile1 && !profile2) return [];

    const s1 = getScores(profile1);
    const s2 = getScores(profile2);

    // Use first player's labels (or second if first not available)
    const labels = s1.labels[0] !== "—" ? s1.labels : s2.labels;

    return [
      {
        label: labels[0],
        shortLabel: labels[0],
        values: [s1.s1, s2.s1],
      },
      {
        label: labels[1],
        shortLabel: labels[1],
        values: [s1.s2, s2.s2],
      },
      {
        label: labels[2],
        shortLabel: labels[2],
        values: [s1.s3, s2.s3],
      },
    ];
  }, [profile1, profile2]);

  const playerNames = [
    profile1 ? profile1.name : "",
    profile2 ? profile2.name : "",
  ].filter(Boolean);

  const playerColours = [CHART_COLOURS[0], CHART_COLOURS[1]];

  // Key stats from baselines
  const earliest = baselines[0];
  const latest = baselines[baselines.length - 1];
  const srChange =
    earliest?.par_sr != null && latest?.par_sr != null
      ? latest.par_sr - earliest.par_sr
      : null;

  // ── Loading state ──────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="max-w-6xl mx-auto px-4 py-8 space-y-6">
        <div className="skeleton h-8 w-48" />
        <div className="skeleton h-4 w-96" />
        <div className="card p-6">
          <div className="skeleton h-72 w-full" />
        </div>
        <div className="card p-6">
          <div className="skeleton h-48 w-full" />
        </div>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────
  if (error) {
    return (
      <div className="app-page py-16 text-center">
        <div className="mb-4 text-2xl font-semibold text-text-muted">No Era Data</div>
        <h1 className="text-h2 text-text-primary mb-2">Era Data Unavailable</h1>
        <p className="text-sm text-text-secondary mb-6">
          Era baselines could not be loaded. This might mean the innings detail
          data hasn't been generated yet by the pipeline.
        </p>
        <button onClick={() => navigate("/")} className="btn-primary">
          ← Back to Home
        </button>
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────
  if (baselines.length === 0) {
    return (
      <div className="app-page py-16 text-center">
        <div className="mb-4 text-2xl font-semibold text-text-muted">No Era Data</div>
        <h1 className="text-h2 text-text-primary mb-2">No Era Data</h1>
        <p className="text-sm text-text-secondary mb-6">
          No era baselines were computed. Ensure the pipeline has processed
          sufficient innings data.
        </p>
        <button onClick={() => navigate("/")} className="btn-primary">
          ← Back to Home
        </button>
      </div>
    );
  }

  return (
    <div className="app-page page-stack">
      {/* ── Page header ─────────────────────────────────────── */}
      <div className="page-header">
        <h1 className="page-title flex items-center gap-2">
          <Calendar size={24} className="text-primary" />
          Era Explorer
        </h1>
        <p className="page-subtitle max-w-2xl">
          How has T20I cricket evolved? Explore how par scoring rates, boundary
          frequencies, and dot ball percentages have changed over the years —
          and how era adjustments put historical performances in context.
        </p>
      </div>

      {/* ── Key stats summary ─────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="card p-3 flex flex-col gap-1">
          <span className="text-xs text-text-muted uppercase tracking-wider">
            Years Covered
          </span>
          <span className="text-lg font-score tabular-nums font-semibold">
            {earliest?.year}–{latest?.year}
          </span>
        </div>
        <div className="card p-3 flex flex-col gap-1">
          <span className="text-xs text-text-muted uppercase tracking-wider">
            Latest Par SR
          </span>
          <span className="text-lg font-score tabular-nums font-semibold text-primary">
            {latest?.par_sr != null ? latest.par_sr.toFixed(1) : "—"}
          </span>
        </div>
        <div className="card p-3 flex flex-col gap-1">
          <span className="text-xs text-text-muted uppercase tracking-wider">
            SR Growth
          </span>
          <span
            className="text-lg font-score tabular-nums font-semibold"
            style={{
              color: srChange != null && srChange > 0 ? "#10B981" : "#64748B",
            }}
          >
            {srChange != null
              ? (srChange > 0 ? "+" : "") + srChange.toFixed(1)
              : "—"}
          </span>
        </div>
        <div className="card p-3 flex flex-col gap-1">
          <span className="text-xs text-text-muted uppercase tracking-wider">
            Max Era Multiplier
          </span>
          <span
            className="text-lg font-score tabular-nums font-semibold"
            style={{
              color: multiplierColour(
                Math.max(...baselines.map((b) => b.multiplier ?? 0)),
              ),
            }}
          >
            {Math.max(...baselines.map((b) => b.multiplier ?? 0)).toFixed(2)}×
          </span>
        </div>
        <div className="card p-3 flex flex-col gap-1">
          <span className="text-xs text-text-muted uppercase tracking-wider">
            Latest Avg RR
          </span>
          <span className="text-lg font-score tabular-nums font-semibold text-[#8B5CF6]">
            {latest?.par_sr != null
              ? ((latest.par_sr / 100) * 6).toFixed(2) + " RPO"
              : "—"}
          </span>
        </div>
        <div className="card p-3 flex flex-col gap-1">
          <span className="text-xs text-text-muted uppercase tracking-wider">
            Predicted Score
          </span>
          <span className="text-lg font-score tabular-nums font-semibold text-[#EC4899]">
            {latest?.par_sr != null
              ? Math.round((latest.par_sr / 100) * 6 * 20).toString()
              : "—"}
          </span>
        </div>
      </div>

      {/* ── Timeline Chart ────────────────────────────────────── */}
      <CollapsibleSection
        title="Timeline"
        icon={<TrendingUp size={18} className="text-primary" />}
      >
        {/* Metric toggles */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {METRIC_CONFIGS.map((mc) => {
            const isActive = activeMetrics.has(mc.key);
            return (
              <button
                key={mc.key}
                onClick={() => toggleMetric(mc.key)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                  isActive
                    ? "text-white"
                    : "bg-surface-elevated text-text-secondary hover:text-text-primary"
                }`}
                style={isActive ? { backgroundColor: mc.colour } : undefined}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    backgroundColor: mc.colour,
                    opacity: isActive ? 1 : 0.4,
                  }}
                />
                {mc.label}
              </button>
            );
          })}
        </div>

        {/* Chart */}
        <div className="w-full" style={{ height: 360 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 5, right: 10, left: 10, bottom: 5 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="rgba(100, 116, 139, 0.15)"
              />
              <XAxis
                dataKey="year"
                tick={{ fontSize: 12, fill: "#94A3B8" }}
                stroke="rgba(100, 116, 139, 0.3)"
              />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 12, fill: "#94A3B8" }}
                stroke="rgba(100, 116, 139, 0.3)"
                label={{
                  value: "Par SR",
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 11, fill: "#64748B" },
                }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fontSize: 12, fill: "#94A3B8" }}
                stroke="rgba(100, 116, 139, 0.3)"
                label={{
                  value: "%",
                  angle: 90,
                  position: "insideRight",
                  style: { fontSize: 11, fill: "#64748B" },
                }}
              />
              <Tooltip content={<ChartTooltip />} />
              <Legend wrapperStyle={{ fontSize: 12 }} />

              {METRIC_CONFIGS.filter((mc) => activeMetrics.has(mc.key)).map(
                (mc) => (
                  <Line
                    key={mc.key}
                    yAxisId={mc.yAxisId}
                    type="monotone"
                    dataKey={mc.key}
                    name={mc.label}
                    stroke={mc.colour}
                    strokeWidth={2.5}
                    dot={{ r: 3, fill: mc.colour }}
                    activeDot={{ r: 5, fill: mc.colour }}
                    connectNulls
                  />
                ),
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CollapsibleSection>

      {/* ── Era Multiplier Table ───────────────────────────────── */}
      <CollapsibleSection
        title="Era Multiplier Table"
        icon={<Calendar size={18} className="text-primary" />}
      >
        {/* Explanation */}
        <div className="flex items-start gap-2 mb-4 p-3 rounded-lg bg-primary/5 border border-primary/10">
          <Info size={16} className="text-primary shrink-0 mt-0.5" />
          <p className="text-sm text-text-secondary">
            <strong className="text-text-primary">Era multipliers</strong>{" "}
            adjust historical performances to account for changes in the scoring
            environment. A multiplier of{" "}
            <span className="font-score text-gold">1.28</span> means a
            performance from that year is worth <strong>28% more</strong> than
            the same raw numbers in the most recent year, because the overall
            scoring environment was harder.
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="sortable-table text-sm">
            <thead>
              <tr>
                <th className="text-left">Year</th>
                <th className="text-right">Par SR</th>
                <th className="text-right">Boundary Rate</th>
                <th className="text-right">Dot %</th>
                <th className="text-right">Era Multiplier</th>
                <th className="text-left hidden sm:table-cell">
                  Interpretation
                </th>
              </tr>
            </thead>
            <tbody>
              {[...baselines].reverse().map((b) => (
                <tr key={b.year}>
                  <td className="font-medium">{b.year}</td>
                  <td className="text-right font-score tabular-nums">
                    {b.par_sr != null ? b.par_sr.toFixed(1) : "—"}
                  </td>
                  <td className="text-right tabular-nums">
                    {b.boundary_rate != null
                      ? b.boundary_rate.toFixed(1) + "%"
                      : "—"}
                  </td>
                  <td className="text-right tabular-nums">
                    {b.dot_pct != null ? b.dot_pct.toFixed(1) + "%" : "—"}
                  </td>
                  <td className="text-right">
                    <span
                      className="font-score tabular-nums font-semibold"
                      style={{ color: multiplierColour(b.multiplier) }}
                    >
                      {b.multiplier != null
                        ? b.multiplier.toFixed(3) + "×"
                        : "—"}
                    </span>
                  </td>
                  <td className="text-text-secondary text-xs hidden sm:table-cell">
                    {b.multiplier != null &&
                    b.multiplier >= 0.99 &&
                    b.multiplier <= 1.01
                      ? "📌 Current baseline"
                      : multiplierLabel(b.multiplier)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      {/* ── Cross-Era Player Comparison ────────────────────────── */}
      <CollapsibleSection
        title="Cross-Era Player Comparison"
        icon={<Users size={18} className="text-primary" />}
        defaultOpen={false}
      >
        <p className="text-sm text-text-secondary mb-4">
          Compare peak performers across different eras. Select two players to
          see their scores side-by-side with a radar chart overlay.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
          {/* Player 1 */}
          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider mb-1.5 block">
              Player 1
            </label>
            <PlayerAutocomplete
              placeholder="Search player…"
              onSelect={(player) => setComparePlayer1Id(player.id || undefined)}
              size="md"
            />
            {profile1 && (
              <ComparePlayerCard profile={profile1} colourIndex={0} />
            )}
          </div>

          {/* Player 2 */}
          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider mb-1.5 block">
              Player 2
            </label>
            <PlayerAutocomplete
              placeholder="Search player…"
              onSelect={(player) => setComparePlayer2Id(player.id || undefined)}
              size="md"
            />
            {profile2 && (
              <ComparePlayerCard profile={profile2} colourIndex={1} />
            )}
          </div>
        </div>

        {/* Radar chart (only show if at least one player selected) */}
        {(profile1 || profile2) && radarAxes.length >= 3 && (
          <div className="flex flex-col items-center">
            <ComparisonRadar
              axes={radarAxes}
              playerNames={playerNames}
              playerColours={playerColours.slice(0, playerNames.length)}
            />
          </div>
        )}

        {/* Side-by-side score table */}
        {profile1 && profile2 && (
          <div className="mt-6 overflow-x-auto">
            <table className="sortable-table text-sm">
              <thead>
                <tr>
                  <th className="text-left">Metric</th>
                  <th className="text-right">
                    <span
                      className="inline-flex items-center gap-1.5"
                      style={{ color: CHART_COLOURS[0] }}
                    >
                      {profile1.name}
                    </span>
                  </th>
                  <th className="text-right">
                    <span
                      className="inline-flex items-center gap-1.5"
                      style={{ color: CHART_COLOURS[1] }}
                    >
                      {profile2.name}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="text-text-secondary">{scores1.labels[0]}</td>
                  <td className="text-right font-score tabular-nums">
                    {scores1.s1 != null ? scores1.s1.toFixed(1) : "—"}
                  </td>
                  <td className="text-right font-score tabular-nums">
                    {scores2.s1 != null ? scores2.s1.toFixed(1) : "—"}
                  </td>
                </tr>
                <tr>
                  <td className="text-text-secondary">{scores1.labels[1]}</td>
                  <td className="text-right font-score tabular-nums">
                    {scores1.s2 != null ? scores1.s2.toFixed(1) : "—"}
                  </td>
                  <td className="text-right font-score tabular-nums">
                    {scores2.s2 != null ? scores2.s2.toFixed(1) : "—"}
                  </td>
                </tr>
                <tr>
                  <td className="text-text-secondary">{scores1.labels[2]}</td>
                  <td className="text-right font-score tabular-nums">
                    {scores1.s3 != null ? scores1.s3.toFixed(1) : "—"}
                  </td>
                  <td className="text-right font-score tabular-nums">
                    {scores2.s3 != null ? scores2.s3.toFixed(1) : "—"}
                  </td>
                </tr>
                <tr>
                  <td className="text-text-secondary">Overall Grade</td>
                  <td className="text-right">
                    <GradeBadge
                      grade={
                        isBatterProfile(profile1)
                          ? profile1.overall_grade
                          : isBowlerProfile(profile1)
                            ? profile1.overall_grade
                            : "D"
                      }
                      size="sm"
                    />
                  </td>
                  <td className="text-right">
                    <GradeBadge
                      grade={
                        isBatterProfile(profile2)
                          ? profile2.overall_grade
                          : isBowlerProfile(profile2)
                            ? profile2.overall_grade
                            : "D"
                      }
                      size="sm"
                    />
                  </td>
                </tr>
                <tr>
                  <td className="text-text-secondary">Country</td>
                  <td className="text-right">
                    {countryFlag(profile1.country)} {profile1.country}
                  </td>
                  <td className="text-right">
                    {countryFlag(profile2.country)} {profile2.country}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

        {!profile1 && !profile2 && (
          <div className="text-center py-8 text-text-muted">
            <Users size={32} className="mx-auto mb-2 opacity-30" />
            <p className="text-sm">
              Select two players above to compare their profiles across eras.
            </p>
          </div>
        )}
      </CollapsibleSection>

      {/* ── Methodology note ──────────────────────────────────── */}
      <div className="text-xs text-text-muted space-y-1 px-1">
        <p>
          <strong>Methodology:</strong> Era baselines are computed from the
          median strike rate across all T20I batting innings in each calendar
          year. Boundary rate and dot% are computed from aggregate ball-by-ball
          data. The era multiplier is the ratio of the latest year's par SR to
          each year's par SR, reflecting how much harder it was to score at
          modern rates in earlier eras.
        </p>
        <p>Years with fewer than 10 recorded innings are excluded.</p>
      </div>
    </div>
  );
}

// ── Compare player mini card ─────────────────────────────────────

function ComparePlayerCard({
  profile,
  colourIndex,
}: {
  profile: PlayerProfile;
  colourIndex: number;
}) {
  const isBatter = isBatterProfile(profile);
  const isBowler = isBowlerProfile(profile);
  const flag = countryFlag(profile.country);
  const colour = chartColour(colourIndex);

  let s1: number | null = null;
  let s2: number | null = null;
  let s3: number | null = null;
  let l1 = "Score 1";
  let l2 = "Score 2";
  let l3 = "Score 3";
  let grade = "D";

  if (isBatter) {
    s1 = profile.score_acceleration;
    s2 = profile.score_power;
    s3 = profile.score_control;
    l1 = "Acceleration";
    l2 = "Power";
    l3 = "Control";
    grade = profile.overall_grade;
  } else if (isBowler) {
    s1 = profile.score_accuracy;
    s2 = profile.score_control;
    s3 = profile.score_threat;
    l1 = "Accuracy";
    l2 = "Control";
    l3 = "Threat";
    grade = profile.overall_grade;
  }

  return (
    <div
      className="mt-2 p-3 rounded-lg bg-surface-elevated/50 border-l-4"
      style={{ borderLeftColor: colour }}
    >
      <div className="flex items-center gap-2 mb-2">
        {flag && <span>{flag}</span>}
        <span className="font-medium text-sm text-text-primary">
          {profile.name}
        </span>
        <GradeBadge grade={grade} size="xs" />
      </div>
      <div className="space-y-1.5">
        <ScoreBar
          value={s1}
          label={l1}
          size="xs"
          variant="full"
          labelWidth="w-24"
        />
        <ScoreBar
          value={s2}
          label={l2}
          size="xs"
          variant="full"
          labelWidth="w-24"
        />
        <ScoreBar
          value={s3}
          label={l3}
          size="xs"
          variant="full"
          labelWidth="w-24"
        />
      </div>
    </div>
  );
}
