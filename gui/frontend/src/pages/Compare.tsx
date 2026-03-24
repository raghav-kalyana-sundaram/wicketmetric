/**
 * Compare — side-by-side player comparison page.
 *
 * Route: /compare?ids=p1234,p5678
 *
 * Features (from gui.md § 6.5):
 *   - Autocomplete inputs for adding/removing players (2–4 supported)
 *   - 6-axis radar chart with overlaid polygons (one colour per player)
 *   - Stat comparison table with automatic "winner" highlighting per row
 *   - Form overlay — line chart showing players' rolling form on the same time axis
 *   - Phase comparison — grouped bars for powerplay/middle/death SR vs par
 *   - Shared matchup analysis — bowlers both batters have faced
 *   - URL-driven: the comparison URL is shareable
 *
 * Data fetching:
 *   - useComparePlayers() — full profiles for each player
 *   - useCompareForm() — overlaid form time-series
 *   - useSharedMatchups() — common bowlers faced
 */

import { useState, useMemo, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { X, Trophy, Share2, Swords, BarChart3, Activity } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
  BarChart,
  Bar,
} from "recharts";

import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import GradeBadge from "@/components/GradeBadge";
import { PageLoading, PageError } from "@/components/Layout";
import {
  useComparePlayers,
  useCompareForm,
  useSharedMatchups,
} from "@/api/queries";
import { MetricLabel } from "@/components/MetricTooltip";
import {
  scoreToColour,
  chartColour,
  chartColourAlpha,
  dominanceColour,
} from "@/lib/colours";
import {
  fmtScore,
  fmtInt,
  fmtSR,
  fmtAvg,
  fmtEcon,
  fmtWAR,
  fmtPct,
  countryFlag,
  fmtDate,
  fmtPhase,
  pressureScore,
  fmtPressureScore,
  fmtMatchupEdge,
  matchupEdgeScore,
  primaryDisplayRating,
  careerDisplayRating,
} from "@/lib/format";
import type {
  PlayerSummary,
  BatterProfile,
  BowlerProfile,
  FormResponse,
  SharedMatchupsResponse,
  SharedMatchup,
  PhaseSplit,
} from "@/api/types";
import { isBatterProfile } from "@/api/types";

// ── Constants ────────────────────────────────────────────────────

const MAX_PLAYERS = 4;
const MIN_PLAYERS = 2;

// Radar axes for batters
const BATTER_RADAR_AXES = [
  { key: "acceleration", label: "Acceleration", shortLabel: "ACC" },
  { key: "power", label: "Power", shortLabel: "POW" },
  { key: "war", label: "WAR", shortLabel: "WAR" },
  { key: "clutch", label: "Clutch", shortLabel: "CLT" },
  { key: "chase", label: "Chase Master", shortLabel: "CHS" },
  { key: "control", label: "Control", shortLabel: "CTL" },
];

// Radar axes for bowlers
const BOWLER_RADAR_AXES = [
  { key: "accuracy", label: "Accuracy", shortLabel: "ACC" },
  { key: "control", label: "Control", shortLabel: "CTL" },
  { key: "war", label: "WAR", shortLabel: "WAR" },
  { key: "clutch", label: "Clutch", shortLabel: "CLT" },
  { key: "dot_pct", label: "Dot %", shortLabel: "DOT" },
  { key: "threat", label: "Threat", shortLabel: "THR" },
];

const FORM_METRICS = [
  { key: "composite", label: "Overall Composite" },
  { key: "window_sr_vs_par", label: "SR vs Par" },
  { key: "window_impact", label: "Impact" },
  { key: "window_boundary_pct", label: "Boundary %" },
  { key: "window_dot_control", label: "Dot Control" },
  { key: "window_consistency", label: "Consistency" },
];

const PHASE_ORDER = ["powerplay", "middle", "death"];

// ── Helper: extract radar value from profile ─────────────────────

function getRadarValue(
  profile: BatterProfile | BowlerProfile,
  key: string,
): number {
  if (isBatterProfile(profile)) {
    switch (key) {
      case "acceleration":
        return profile.score_acceleration ?? 0;
      case "power":
        return profile.score_power ?? 0;
      case "control":
        return profile.score_control ?? 0;
      case "war":
        return Math.min(100, Math.max(0, (profile.war_batting ?? 0) * 20));
      case "clutch":
        return pressureScore(profile.clutch_index, "bat") ?? 0;
      case "chase":
        return Math.min(
          100,
          Math.max(0, (profile.chase_master_index ?? 0) * 10),
        );
      default:
        return 0;
    }
  } else {
    switch (key) {
      case "accuracy":
        return profile.score_accuracy ?? 0;
      case "control":
        return profile.score_control ?? 0;
      case "threat":
        return profile.score_threat ?? 0;
      case "war":
        return Math.min(100, Math.max(0, (profile.war_bowling ?? 0) * 20));
      case "clutch":
        return pressureScore(profile.clutch_index_bowl, "bowl") ?? 0;
      case "dot_pct":
        return Math.min(100, (profile.career_dot_pct ?? 0) * 2.5);
      default:
        return 0;
    }
  }
}

// ── Helper: stat table rows ──────────────────────────────────────

interface StatRow {
  label: string;
  metricKey?: string;
  values: (string | number | null)[];
  rawValues: (number | null)[];
  higherIsBetter: boolean;
  isGrade?: boolean;
}

function buildBatterStatRows(batters: BatterProfile[]): StatRow[] {
  return [
    {
      label: "Overall Grade",
      metricKey: "overall_grade",
      values: batters.map((b) => b.overall_grade),
      rawValues: batters.map((b) => b.overall_score),
      higherIsBetter: true,
      isGrade: true,
    },
    {
      label: "Archetype",
      values: batters.map((b) => b.archetype),
      rawValues: batters.map(() => null),
      higherIsBetter: true,
    },
    {
      label: "Innings",
      metricKey: "innings_count",
      values: batters.map((b) => fmtInt(b.innings_count)),
      rawValues: batters.map((b) => b.innings_count),
      higherIsBetter: true,
    },
    {
      label: "Runs",
      values: batters.map((b) => fmtInt(b.total_runs)),
      rawValues: batters.map((b) => b.total_runs),
      higherIsBetter: true,
    },
    {
      label: "Career SR",
      metricKey: "career_sr",
      values: batters.map((b) => fmtSR(b.career_sr)),
      rawValues: batters.map((b) => b.career_sr),
      higherIsBetter: true,
    },
    {
      label: "Career Avg",
      metricKey: "career_avg",
      values: batters.map((b) => fmtAvg(b.career_avg)),
      rawValues: batters.map((b) => b.career_avg),
      higherIsBetter: true,
    },
    {
      label: "Acceleration",
      metricKey: "acceleration",
      values: batters.map((b) => fmtScore(b.score_acceleration)),
      rawValues: batters.map((b) => b.score_acceleration),
      higherIsBetter: true,
    },
    {
      label: "Power",
      metricKey: "power",
      values: batters.map((b) => fmtScore(b.score_power)),
      rawValues: batters.map((b) => b.score_power),
      higherIsBetter: true,
    },
    {
      label: "Control",
      metricKey: "control",
      values: batters.map((b) => fmtScore(b.score_control)),
      rawValues: batters.map((b) => b.score_control),
      higherIsBetter: true,
    },
    {
      label: "WAR",
      metricKey: "war_batting",
      values: batters.map((b) => fmtWAR(b.war_batting)),
      rawValues: batters.map((b) => b.war_batting),
      higherIsBetter: true,
    },
    {
      label: "Pressure Score",
      metricKey: "clutch_index",
      values: batters.map(
        (b) => `${fmtPressureScore(b.clutch_index, "bat")}/100`,
      ),
      rawValues: batters.map((b) => pressureScore(b.clutch_index, "bat")),
      higherIsBetter: true,
    },
    {
      label: "Chase Master",
      metricKey: "chase_master_index",
      values: batters.map((b) => fmtScore(b.chase_master_index)),
      rawValues: batters.map((b) => b.chase_master_index),
      higherIsBetter: true,
    },
    {
      label: "Peak Composite",
      metricKey: "overall_score",
      values: batters.map((b) => fmtScore(b.peak_composite_batting)),
      rawValues: batters.map((b) => b.peak_composite_batting),
      higherIsBetter: true,
    },
    {
      label: "Avg Matchup Edge",
      metricKey: "dominance_index",
      values: batters.map((b) => `${fmtMatchupEdge(b.avg_dominance)}/100`),
      rawValues: batters.map((b) => matchupEdgeScore(b.avg_dominance)),
      higherIsBetter: true,
    },
  ];
}

function buildBowlerStatRows(bowlers: BowlerProfile[]): StatRow[] {
  return [
    {
      label: "Overall Grade",
      metricKey: "overall_grade",
      values: bowlers.map((b) => b.overall_grade),
      rawValues: bowlers.map((b) => b.overall_score),
      higherIsBetter: true,
      isGrade: true,
    },
    {
      label: "Archetype",
      values: bowlers.map((b) => b.archetype),
      rawValues: bowlers.map(() => null),
      higherIsBetter: true,
    },
    {
      label: "Matches",
      values: bowlers.map((b) => fmtInt(b.matches)),
      rawValues: bowlers.map((b) => b.matches),
      higherIsBetter: true,
    },
    {
      label: "Wickets",
      values: bowlers.map((b) => fmtInt(b.total_wickets)),
      rawValues: bowlers.map((b) => b.total_wickets),
      higherIsBetter: true,
    },
    {
      label: "Economy",
      metricKey: "career_economy",
      values: bowlers.map((b) => fmtEcon(b.career_economy)),
      rawValues: bowlers.map((b) => b.career_economy),
      higherIsBetter: false,
    },
    {
      label: "Accuracy",
      metricKey: "accuracy",
      values: bowlers.map((b) => fmtScore(b.score_accuracy)),
      rawValues: bowlers.map((b) => b.score_accuracy),
      higherIsBetter: true,
    },
    {
      label: "Control",
      metricKey: "control_bowl",
      values: bowlers.map((b) => fmtScore(b.score_control)),
      rawValues: bowlers.map((b) => b.score_control),
      higherIsBetter: true,
    },
    {
      label: "Threat",
      metricKey: "threat",
      values: bowlers.map((b) => fmtScore(b.score_threat)),
      rawValues: bowlers.map((b) => b.score_threat),
      higherIsBetter: true,
    },
    {
      label: "WAR",
      metricKey: "war_bowling",
      values: bowlers.map((b) => fmtWAR(b.war_bowling)),
      rawValues: bowlers.map((b) => b.war_bowling),
      higherIsBetter: true,
    },
    {
      label: "Dot %",
      metricKey: "dot_pct",
      values: bowlers.map((b) => fmtPct(b.career_dot_pct)),
      rawValues: bowlers.map((b) => b.career_dot_pct),
      higherIsBetter: true,
    },
    {
      label: "Pressure Score",
      metricKey: "clutch_index_bowl",
      values: bowlers.map(
        (b) => `${fmtPressureScore(b.clutch_index_bowl, "bowl")}/100`,
      ),
      rawValues: bowlers.map((b) => pressureScore(b.clutch_index_bowl, "bowl")),
      higherIsBetter: true,
    },
    {
      label: "Avg Matchup Edge",
      metricKey: "dominance_index",
      values: bowlers.map((b) => `${fmtMatchupEdge(b.avg_dominance_bowl)}/100`),
      rawValues: bowlers.map((b) => matchupEdgeScore(b.avg_dominance_bowl)),
      higherIsBetter: true,
    },
    {
      label: "Peak Composite",
      metricKey: "overall_score",
      values: bowlers.map((b) => fmtScore(b.peak_composite_bowling)),
      rawValues: bowlers.map((b) => b.peak_composite_bowling),
      higherIsBetter: true,
    },
  ];
}

function getWinnerIndex(
  rawValues: (number | null)[],
  higherIsBetter: boolean,
): number | null {
  const validEntries = rawValues
    .map((v, i) => ({ v, i }))
    .filter((e) => e.v != null);
  if (validEntries.length < 2) return null;

  let best = validEntries[0];
  for (let j = 1; j < validEntries.length; j++) {
    const entry = validEntries[j];
    if (higherIsBetter ? entry.v! > best.v! : entry.v! < best.v!) {
      best = entry;
    }
  }

  // Check for ties
  const tieCount = validEntries.filter((e) => e.v === best.v).length;
  if (tieCount > 1) return null;

  return best.i;
}

// ── SVG Radar Chart ──────────────────────────────────────────────

interface RadarChartProps {
  axes: { key: string; label: string; shortLabel: string }[];
  players: {
    name: string;
    values: number[];
    colour: string;
  }[];
  size?: number;
}

function RadarChart({ axes, players, size = 300 }: RadarChartProps) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 40;
  const levels = 5;
  const angleSlice = (Math.PI * 2) / axes.length;

  const getPoint = (value: number, index: number) => {
    const r = (value / 100) * radius;
    const angle = angleSlice * index - Math.PI / 2;
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    };
  };

  const gridLevels = Array.from({ length: levels }, (_, i) => i + 1);

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="w-full max-w-sm mx-auto"
      role="img"
      aria-label="Radar comparison chart"
    >
      {/* Grid circles */}
      {gridLevels.map((level) => {
        const r = (level / levels) * radius;
        const points = axes
          .map((_, i) => {
            const angle = angleSlice * i - Math.PI / 2;
            return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
          })
          .join(" ");
        return (
          <polygon
            key={`grid-${level}`}
            points={points}
            className="radar-grid"
            fill="none"
            stroke="currentColor"
            strokeOpacity={0.15}
          />
        );
      })}

      {/* Axis lines */}
      {axes.map((_, i) => {
        const end = getPoint(100, i);
        return (
          <line
            key={`axis-${i}`}
            x1={cx}
            y1={cy}
            x2={end.x}
            y2={end.y}
            stroke="currentColor"
            strokeOpacity={0.1}
            strokeWidth={0.5}
          />
        );
      })}

      {/* Player polygons */}
      {players.map((player, pi) => {
        const points = player.values
          .map((v, i) => {
            const p = getPoint(v, i);
            return `${p.x},${p.y}`;
          })
          .join(" ");
        return (
          <g key={`player-${pi}`}>
            <polygon
              points={points}
              fill={player.colour}
              fillOpacity={0.15}
              stroke={player.colour}
              strokeWidth={2}
              className="radar-polygon"
            />
            {player.values.map((v, i) => {
              const p = getPoint(v, i);
              return (
                <circle
                  key={`dot-${pi}-${i}`}
                  cx={p.x}
                  cy={p.y}
                  r={3}
                  fill={player.colour}
                />
              );
            })}
          </g>
        );
      })}

      {/* Axis labels */}
      {axes.map((axis, i) => {
        const labelRadius = radius + 20;
        const angle = angleSlice * i - Math.PI / 2;
        const x = cx + labelRadius * Math.cos(angle);
        const y = cy + labelRadius * Math.sin(angle);
        return (
          <text
            key={`label-${i}`}
            x={x}
            y={y}
            textAnchor="middle"
            dominantBaseline="central"
            className="radar-axis-label fill-text-secondary"
            fontSize={11}
          >
            {axis.shortLabel}
          </text>
        );
      })}
    </svg>
  );
}

// ── Phase Comparison Chart ───────────────────────────────────────

interface PhaseChartProps {
  players: {
    name: string;
    colour: string;
    phases: Record<string, PhaseSplit>;
  }[];
}

function PhaseComparisonChart({ players }: PhaseChartProps) {
  const data = PHASE_ORDER.map((phase) => {
    const entry: Record<string, string | number | null> = {
      phase: fmtPhase(phase),
    };
    players.forEach((p, i) => {
      const split = p.phases[phase];
      entry[`sr_${i}`] = split?.sr ?? null;
      entry[`name_${i}`] = p.name;
    });
    return entry;
  });

  return (
    <ResponsiveContainer width="100%" height={250}>
      <BarChart data={data} barGap={2} barCategoryGap="20%">
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#334155"
          strokeOpacity={0.28}
        />
        <XAxis
          dataKey="phase"
          tick={{ fill: "#94A3B8", fontSize: 12 }}
          axisLine={{ stroke: "#334155" }}
        />
        <YAxis
          tick={{ fill: "#94A3B8", fontSize: 12 }}
          axisLine={{ stroke: "#334155" }}
          label={{
            value: "Strike Rate",
            angle: -90,
            position: "insideLeft",
            fill: "#94A3B8",
            fontSize: 12,
          }}
        />
        <RechartsTooltip
          contentStyle={{
            backgroundColor: "#1E293B",
            border: "1px solid #334155",
            borderRadius: "0.5rem",
            color: "#F8FAFC",
          }}
        />
        {players.map((p, i) => (
          <Bar
            key={`sr_${i}`}
            dataKey={`sr_${i}`}
            name={p.name}
            fill={p.colour}
            radius={[4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Main Component ───────────────────────────────────────────────

export default function Compare() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<"auto" | "bat" | "bowl">("auto");

  // Parse player IDs from URL
  const playerIds = useMemo(() => {
    const idsParam = searchParams.get("ids");
    if (!idsParam) return [];
    return idsParam
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean)
      .slice(0, MAX_PLAYERS);
  }, [searchParams]);

  // Form metric selection
  const [formMetric, setFormMetric] = useState("composite");

  // Data fetching
  const {
    data: compareData,
    isLoading: compareLoading,
    error: compareError,
  } = useComparePlayers(playerIds);

  const { data: formData, isLoading: formLoading } = useCompareForm(playerIds);

  const { data: sharedMatchupsData } = useSharedMatchups(playerIds, {
    minBalls: 6,
    limit: 20,
  });

  // ── Player management ──────────────────────────────────────────

  const updateIds = useCallback(
    (newIds: string[]) => {
      if (newIds.length === 0) {
        setSearchParams({});
      } else {
        setSearchParams({ ids: newIds.join(",") });
      }
    },
    [setSearchParams],
  );

  const addPlayer = useCallback(
    (player: PlayerSummary) => {
      if (playerIds.length >= MAX_PLAYERS) return;
      if (playerIds.includes(player.id)) return;
      updateIds([...playerIds, player.id]);
    },
    [playerIds, updateIds],
  );

  const removePlayer = useCallback(
    (id: string) => {
      updateIds(playerIds.filter((pid) => pid !== id));
    },
    [playerIds, updateIds],
  );

  // ── Derived data ───────────────────────────────────────────────

  const allProfiles = useMemo(() => {
    if (!compareData) return [];
    return [...(compareData.batters || []), ...(compareData.bowlers || [])];
  }, [compareData]);

  const batters = compareData?.batters ?? [];
  const bowlers = compareData?.bowlers ?? [];
  const hasBatters = batters.length > 0;
  const hasBowlers = bowlers.length > 0;

  // Determine effective view mode for radar/stat tables
  const effectiveView = useMemo(() => {
    if (viewMode !== "auto") return viewMode;
    if (hasBatters && !hasBowlers) return "bat" as const;
    if (hasBowlers && !hasBatters) return "bowl" as const;
    // Mixed: default to the role where more players have data
    return batters.length >= bowlers.length
      ? ("bat" as const)
      : ("bowl" as const);
  }, [viewMode, hasBatters, hasBowlers, batters.length, bowlers.length]);

  // Build name → colour mapping based on order
  const playerColourMap = useMemo(() => {
    const map = new Map<string, string>();
    allProfiles.forEach((p, i) => {
      map.set(p.id, chartColour(i));
    });
    return map;
  }, [allProfiles]);

  // Radar data — driven by effectiveView
  const radarAxes = useMemo(() => {
    return effectiveView === "bat" ? BATTER_RADAR_AXES : BOWLER_RADAR_AXES;
  }, [effectiveView]);

  const radarPlayers = useMemo(() => {
    const axes =
      effectiveView === "bat" ? BATTER_RADAR_AXES : BOWLER_RADAR_AXES;
    // Use the profiles that match the effective view, falling back to all
    const profilesForRadar =
      effectiveView === "bat"
        ? batters.length > 0
          ? batters
          : allProfiles
        : bowlers.length > 0
          ? bowlers
          : allProfiles;
    return profilesForRadar.map((profile) => {
      return {
        name: profile.name,
        values: axes.map((axis) => getRadarValue(profile, axis.key)),
        colour: chartColour(
          allProfiles.findIndex((ap) => ap.id === profile.id),
        ),
      };
    });
  }, [allProfiles, batters, bowlers, effectiveView]);

  // Form chart data
  const formChartData = useMemo(() => {
    if (!formData || !Array.isArray(formData)) return [];

    // Merge all players' form series onto a common date axis
    const dateMap = new Map<string, Record<string, number | null | string>>();

    (formData as FormResponse[]).forEach((playerForm, pi) => {
      playerForm.series.forEach((point) => {
        if (!dateMap.has(point.date)) {
          dateMap.set(point.date, { date: point.date });
        }
        const entry = dateMap.get(point.date)!;
        const value = (point as unknown as Record<string, unknown>)[formMetric];
        entry[`p${pi}`] = typeof value === "number" ? value : null;
      });
    });

    return Array.from(dateMap.values()).sort((a, b) =>
      String(a.date).localeCompare(String(b.date)),
    );
  }, [formData, formMetric]);

  // ── Share URL ──────────────────────────────────────────────────

  const handleShare = useCallback(() => {
    const url = window.location.href;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, []);

  // ── Render: empty state ────────────────────────────────────────

  const canCompare = playerIds.length >= MIN_PLAYERS;

  return (
    <div className="app-page page-stack animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <h1 className="page-title">Compare Players</h1>
        <p className="page-subtitle">
          Select 2–4 players to compare side-by-side. The URL is shareable.
        </p>
        <p className="text-xs text-text-muted max-w-2xl mt-2">
          Players can be resolved across loaded datasets (e.g. men&apos;s and
          women&apos;s). Scores use the same 0–100 scale but are not directly
          comparable as physical benchmarks between genders.
        </p>
      </div>

      {/* Player Selection Inputs */}
      <div className="card p-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* Selected player chips */}
          {allProfiles.map((profile, i) => (
            <div
              key={profile.id}
              className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"
              style={{
                borderColor: chartColour(i),
                backgroundColor: chartColourAlpha(i, 0.1),
              }}
            >
              <span className="text-text-secondary">
                {countryFlag(profile.country)}
              </span>
              <Link
                to={`/player/${profile.id}`}
                className="font-medium text-text-primary hover:text-primary transition-colors"
              >
                {profile.name}
              </Link>
              <GradeBadge
                grade={
                  isBatterProfile(profile)
                    ? profile.overall_grade
                    : profile.overall_grade
                }
                size="xs"
              />
              <button
                onClick={() => removePlayer(profile.id)}
                className="ml-1 rounded p-0.5 text-text-muted hover:bg-surface-elevated hover:text-danger transition-colors"
                aria-label={`Remove ${profile.name}`}
              >
                <X size={14} />
              </button>
            </div>
          ))}

          {/* Add player when loading or IDs not yet resolved */}
          {playerIds
            .filter((id) => !allProfiles.find((p) => p.id === id))
            .map((id) => (
              <div
                key={id}
                className="flex items-center gap-2 rounded-lg border border-surface-elevated px-3 py-2 text-sm animate-pulse"
              >
                <span className="text-text-muted">Loading…</span>
                <button
                  onClick={() => removePlayer(id)}
                  className="ml-1 rounded p-0.5 text-text-muted hover:text-danger"
                  aria-label={`Remove player ${id}`}
                >
                  <X size={14} />
                </button>
              </div>
            ))}

          {/* Add player autocomplete */}
          {playerIds.length < MAX_PLAYERS && (
            <div className="min-w-[240px] flex-1 max-w-sm">
              <PlayerAutocomplete
                onSelect={(player) => {
                  addPlayer(player);
                }}
                placeholder="+ Add player…"
                size="sm"
                excludeIds={playerIds}
              />
            </div>
          )}
        </div>

        {/* Share button */}
        {canCompare && (
          <div className="mt-3 flex items-center gap-3 border-t border-surface-elevated pt-3">
            <button onClick={handleShare} className="btn-secondary btn-sm">
              <Share2 size={14} />
              {copied ? "Copied!" : "Share Comparison"}
            </button>
          </div>
        )}
      </div>

      {/* Loading state */}
      {compareLoading && canCompare && <PageLoading />}

      {/* Error state */}
      {compareError && canCompare && (
        <PageError
          title="Comparison Error"
          message="Failed to load comparison data. Please check the player IDs and try again."
        />
      )}

      {/* Empty state */}
      {!canCompare && !compareLoading && (
        <div className="state-empty flex flex-col items-center justify-center py-16 text-center">
          <h2 className="text-h3 text-text-primary mb-2">
            Select Players to Compare
          </h2>
          <p className="text-sm text-text-secondary max-w-md">
            Add at least {MIN_PLAYERS} players using the search above. You can
            compare up to {MAX_PLAYERS} players side-by-side.
          </p>
        </div>
      )}

      {/* Comparison Content */}
      {compareData && canCompare && allProfiles.length >= MIN_PLAYERS && (
        <div className="app-page page-stack">
          {/* ── Role toggle ───────────────────────────────── */}
          {hasBatters && hasBowlers && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">Compare as:</span>
              {(["auto", "bat", "bowl"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    viewMode === mode
                      ? "bg-primary text-white"
                      : "bg-surface-elevated text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {mode === "auto"
                    ? "Auto"
                    : mode === "bat"
                      ? "Batters"
                      : "Bowlers"}
                </button>
              ))}
            </div>
          )}

          {/* ── Radar Overlay ─────────────────────────────── */}
          <section className="card p-6">
            <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
              <BarChart3 size={20} className="text-primary" />
              Radar Overlay
              <span className="text-xs text-text-muted font-normal ml-1">
                ({effectiveView === "bat" ? "Batting" : "Bowling"})
              </span>
            </h2>

            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
                {allProfiles.map((profile, i) => (
                  <div key={profile.id} className="flex items-center gap-2">
                    <div
                      className="h-3 w-6 rounded shrink-0"
                      style={{ backgroundColor: chartColour(i) }}
                    />
                    <span className="text-sm text-text-primary">
                      {profile.name}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex justify-center w-full min-w-0">
                <RadarChart
                  axes={radarAxes}
                  players={radarPlayers}
                  size={320}
                />
              </div>
            </div>
          </section>

          {/* ── Stat Comparison Table (primary — driven by effectiveView) ─── */}
          {effectiveView === "bat" && batters.length >= 2 && (
            <section className="card p-6">
              <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                <Trophy size={20} className="text-gold" />
                Batting Comparison
              </h2>
              <StatTable
                players={batters}
                rows={buildBatterStatRows(batters)}
                colourMap={playerColourMap}
                allProfiles={allProfiles}
              />
            </section>
          )}

          {effectiveView === "bowl" && bowlers.length >= 2 && (
            <section className="card p-6">
              <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                <Trophy size={20} className="text-gold" />
                Bowling Comparison
              </h2>
              <StatTable
                players={bowlers}
                rows={buildBowlerStatRows(bowlers)}
                colourMap={playerColourMap}
                allProfiles={allProfiles}
              />
            </section>
          )}

          {/* ── Secondary role table (if both roles have ≥2 players) ─── */}
          {effectiveView === "bat" && hasBowlers && bowlers.length >= 2 && (
            <section className="card p-6">
              <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                <Trophy size={20} className="text-gold opacity-60" />
                <span className="text-text-secondary">Bowling Comparison</span>
              </h2>
              <StatTable
                players={bowlers}
                rows={buildBowlerStatRows(bowlers)}
                colourMap={playerColourMap}
                allProfiles={allProfiles}
              />
            </section>
          )}

          {effectiveView === "bowl" && hasBatters && batters.length >= 2 && (
            <section className="card p-6">
              <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                <Trophy size={20} className="text-gold opacity-60" />
                <span className="text-text-secondary">Batting Comparison</span>
              </h2>
              <StatTable
                players={batters}
                rows={buildBatterStatRows(batters)}
                colourMap={playerColourMap}
                allProfiles={allProfiles}
              />
            </section>
          )}

          {/* ── Mixed comparison when single of each ──────── */}
          {((effectiveView === "bat" && batters.length < 2) ||
            (effectiveView === "bowl" && bowlers.length < 2)) &&
            allProfiles.length >= 2 && (
              <section className="card p-6">
                <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                  <Trophy size={20} className="text-gold" />
                  Player Overview
                </h2>
                <div className="overflow-x-auto">
                  <table className="sortable-table">
                    <thead>
                      <tr>
                        <th>Metric</th>
                        {allProfiles.map((p, i) => (
                          <th key={p.id}>
                            <span style={{ color: chartColour(i) }}>
                              {p.name}
                            </span>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td className="text-text-secondary">Role</td>
                        {allProfiles.map((p) => (
                          <td key={p.id} className="text-right">
                            {isBatterProfile(p) ? "Batter" : "Bowler"}
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="text-text-secondary">Grade</td>
                        {allProfiles.map((p) => (
                          <td key={p.id} className="text-right">
                            <GradeBadge grade={p.overall_grade} size="sm" />
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="text-text-secondary">Archetype</td>
                        {allProfiles.map((p) => (
                          <td key={p.id} className="text-right">
                            {p.archetype}
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="text-text-secondary">Current</td>
                        {allProfiles.map((p) => (
                          <td key={p.id} className="text-right">
                            <span
                              className="font-score tabular-nums"
                              style={{
                                color: scoreToColour(
                                  primaryDisplayRating(p) ?? p.overall_score,
                                ),
                              }}
                            >
                              {fmtScore(
                                primaryDisplayRating(p) ?? p.overall_score,
                              )}
                            </span>
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="text-text-secondary">
                          Career overall
                        </td>
                        {allProfiles.map((p) => (
                          <td key={p.id} className="text-right">
                            <span
                              className="font-score tabular-nums"
                              style={{
                                color: scoreToColour(careerDisplayRating(p)),
                              }}
                            >
                              {fmtScore(careerDisplayRating(p))}
                            </span>
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>
            )}

          {/* ── Phase Comparison ───────────────────────────── */}
          {effectiveView === "bat" && batters.length >= 2 && (
            <section className="card p-6">
              <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                <BarChart3 size={20} className="text-accent" />
                Phase Comparison
              </h2>
              <PhaseComparisonChart
                players={batters.map((b, i) => ({
                  name: b.name,
                  colour: playerColourMap.get(b.id) ?? chartColour(i),
                  phases: b.phases,
                }))}
              />
            </section>
          )}

          {/* ── Form Comparison ────────────────────────────── */}
          {formData && Array.isArray(formData) && formData.length >= 2 && (
            <section className="card p-6">
              <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                <Activity size={20} className="text-primary" />
                Form Comparison
              </h2>

              {/* Metric selector */}
              <div className="mb-4">
                <label className="text-xs text-text-secondary uppercase tracking-wider mr-2">
                  Metric:
                </label>
                <select
                  value={formMetric}
                  onChange={(e) => setFormMetric(e.target.value)}
                  className="filter-select text-sm"
                >
                  {FORM_METRICS.map((m) => (
                    <option key={m.key} value={m.key}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>

              {formChartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={formChartData}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="#334155"
                      strokeOpacity={0.28}
                    />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "#94A3B8", fontSize: 11 }}
                      axisLine={{ stroke: "#334155" }}
                      tickFormatter={(v: string) => {
                        if (!v) return "";
                        const y = v.slice(0, 4);
                        return /^\d{4}$/.test(y) ? y : v;
                      }}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      tick={{ fill: "#94A3B8", fontSize: 11 }}
                      axisLine={{ stroke: "#334155" }}
                      domain={["auto", "auto"]}
                    />
                    <RechartsTooltip
                      contentStyle={{
                        backgroundColor: "#1E293B",
                        border: "1px solid #334155",
                        borderRadius: "0.5rem",
                        color: "#F8FAFC",
                      }}
                      labelFormatter={(label: string) =>
                        fmtDate(label) ?? label
                      }
                    />
                    <Legend />
                    {(formData as FormResponse[]).map((pf, pi) => (
                      <Line
                        key={pf.player_id}
                        type="monotone"
                        dataKey={`p${pi}`}
                        name={pf.player_name || `Player ${pi + 1}`}
                        stroke={chartColour(pi)}
                        strokeWidth={2}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-center py-8 text-text-muted">
                  {formLoading
                    ? "Loading form data…"
                    : "No overlapping form data available."}
                </div>
              )}
            </section>
          )}

          {/* ── Shared Matchups ────────────────────────────── */}
          {sharedMatchupsData &&
            (sharedMatchupsData as SharedMatchupsResponse).shared?.length >
              0 && (
              <section className="card p-6">
                <h2 className="text-h3 text-text-primary mb-4 flex items-center gap-2">
                  <Swords size={20} className="text-warning" />
                  Shared Matchups
                </h2>
                <p className="text-sm text-text-secondary mb-4">
                  Bowlers that all selected batters have faced (min 6 balls
                  each).
                </p>

                <div className="overflow-x-auto">
                  <table className="sortable-table">
                    <thead>
                      <tr>
                        <th>Bowler</th>
                        {(
                          sharedMatchupsData as SharedMatchupsResponse
                        ).batter_ids.map((bid, i) => {
                          const batter = batters.find((b) => b.id === bid);
                          return (
                            <th key={bid} colSpan={2}>
                              <span
                                style={{
                                  color:
                                    playerColourMap.get(bid) ?? chartColour(i),
                                }}
                              >
                                {batter?.name ?? bid}
                              </span>
                            </th>
                          );
                        })}
                      </tr>
                      <tr>
                        <th></th>
                        {(
                          sharedMatchupsData as SharedMatchupsResponse
                        ).batter_ids.map((bid) => (
                          <>
                            <th key={`${bid}-balls`} className="text-right">
                              Balls / SR
                            </th>
                            <th key={`${bid}-dom`} className="text-right">
                              Edge
                            </th>
                          </>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(
                        sharedMatchupsData as SharedMatchupsResponse
                      ).shared.map((sm: SharedMatchup, si: number) => (
                        <tr key={sm.bowler_id || si}>
                          <td>
                            <Link
                              to={`/player/${sm.bowler_id}`}
                              className="text-primary hover:underline"
                            >
                              {sm.bowler_name}
                            </Link>
                          </td>
                          {(
                            sharedMatchupsData as SharedMatchupsResponse
                          ).batter_ids.map((bid) => {
                            const entry = sm.matchups[bid];
                            if (!entry) {
                              return (
                                <>
                                  <td
                                    key={`${bid}-stats`}
                                    className="text-right text-text-muted"
                                  >
                                    —
                                  </td>
                                  <td
                                    key={`${bid}-dom`}
                                    className="text-right text-text-muted"
                                  >
                                    —
                                  </td>
                                </>
                              );
                            }
                            return (
                              <>
                                <td
                                  key={`${bid}-stats`}
                                  className="text-right font-score tabular-nums"
                                >
                                  {entry.balls}b / {fmtSR(entry.sr)}
                                </td>
                                <td key={`${bid}-dom`} className="text-right">
                                  <span
                                    className="font-score tabular-nums"
                                    style={{
                                      color: dominanceColour(
                                        entry.dominance_index,
                                      ),
                                    }}
                                  >
                                    {entry.dominance_index != null
                                      ? `${fmtMatchupEdge(entry.dominance_index)}/100`
                                      : "—"}
                                  </span>
                                </td>
                              </>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
        </div>
      )}
    </div>
  );
}

// ── StatTable sub-component ──────────────────────────────────────

interface StatTableProps {
  players: (BatterProfile | BowlerProfile)[];
  rows: StatRow[];
  colourMap: Map<string, string>;
  allProfiles: (BatterProfile | BowlerProfile)[];
}

function StatTable({ players, rows, colourMap, allProfiles }: StatTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="sortable-table">
        <thead>
          <tr>
            <th className="min-w-[140px]">Metric</th>
            {players.map((p) => {
              const globalIdx = allProfiles.findIndex((ap) => ap.id === p.id);
              return (
                <th key={p.id} className="text-right">
                  <span
                    style={{
                      color: colourMap.get(p.id) ?? chartColour(globalIdx),
                    }}
                  >
                    {p.name}
                  </span>
                </th>
              );
            })}
            {players.length >= 2 && <th>Winner</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => {
            const winnerIdx = getWinnerIndex(row.rawValues, row.higherIsBetter);
            const winnerName =
              winnerIdx != null ? (players[winnerIdx]?.name ?? "") : "";

            return (
              <tr key={ri}>
                <td className="text-text-secondary text-sm">
                  {row.metricKey ? (
                    <MetricLabel
                      metric={row.metricKey}
                      label={row.label}
                      textSize="text-sm"
                      iconSize={11}
                    />
                  ) : (
                    row.label
                  )}
                </td>
                {row.values.map((val, vi) => {
                  const isWinner = vi === winnerIdx;
                  return (
                    <td
                      key={vi}
                      className={`text-right font-score tabular-nums ${
                        isWinner
                          ? "font-bold text-text-primary"
                          : "text-text-secondary"
                      }`}
                    >
                      {row.isGrade && typeof val === "string" ? (
                        <GradeBadge
                          grade={val}
                          size="sm"
                          className={isWinner ? "ring-1 ring-gold/50" : ""}
                        />
                      ) : (
                        <span
                          style={
                            isWinner && row.rawValues[vi] != null
                              ? {
                                  color: scoreToColour(row.rawValues[vi]),
                                }
                              : undefined
                          }
                        >
                          {val ?? "—"}
                        </span>
                      )}
                    </td>
                  );
                })}
                {players.length >= 2 && (
                  <td className="text-xs text-text-muted">
                    {winnerName || "—"}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
