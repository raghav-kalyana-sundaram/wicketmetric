/**
 * TeamBuilder — Interactive page for assembling hypothetical T20I XIs.
 *
 * Route: /team-builder
 *
 * Features:
 *   - 11 player slots with autocomplete search for each
 *   - Real-time aggregate stats recalculation as players are added/removed
 *   - Team radar chart (6 axes: Bat Acceleration, Bat Power, Bat Control,
 *     Bowl Accuracy, Bowl Control, Bowl Threat)
 *   - Weakness detection (flags dimensions below 50th percentile)
 *   - Template auto-fill buttons (Best XI by WAR, Power, Control, Country)
 *   - Shareable URL encoding the selected player IDs
 *   - Country-constrained auto-fill
 *
 * Follows gui.md § 6.8 "Team Builder".
 */

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import {
  Users,
  X,
  Wand2,
  Share2,
  Trash2,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Trophy,
  Zap,
  Shield,
  Globe,
  Check,
  Info,
  Swords,
} from "lucide-react";

import {
  useTeamAnalysis,
  useTeamAutoFill,
  useTeamCompare,
  useCountries,
} from "@/api/queries";
import type {
  PlayerSummary,
  TeamAnalysis,
  TeamCompareResponse,
} from "@/api/types";
import api from "@/api/client";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import GradeBadge from "@/components/GradeBadge";
import ScoreBar from "@/components/ScoreBar";
import { countryFlag } from "@/lib/format";
import { scoreToColour } from "@/lib/colours";

// ── Constants ────────────────────────────────────────────────────

const MAX_PLAYERS = 11;
const LOCALSTORAGE_KEY = "cricket-metrics-team-builder";

// ── Slot type constants ──────────────────────────────────────────

const SLOT_TYPE_OPTIONS = [
  { key: "opener", label: "Opener", icon: "🏏" },
  { key: "top_order", label: "Top Order", icon: "🏏" },
  { key: "middle_order", label: "Middle Order", icon: "🏏" },
  { key: "finisher_wk", label: "Finisher / WK", icon: "🧤" },
  { key: "allrounder", label: "All-rounder", icon: "⚡" },
  { key: "bowler", label: "Bowler", icon: "🎳" },
] as const;

type SlotTypeKey = (typeof SLOT_TYPE_OPTIONS)[number]["key"];

const DEFAULT_SLOT_TYPES: SlotTypeKey[] = [
  "opener",
  "opener",
  "top_order",
  "top_order",
  "middle_order",
  "middle_order",
  "finisher_wk",
  "allrounder",
  "bowler",
  "bowler",
  "bowler",
];

const TYPE_SHORT_CODES: Record<SlotTypeKey, string> = {
  opener: "o",
  top_order: "t",
  middle_order: "m",
  finisher_wk: "f",
  allrounder: "a",
  bowler: "b",
};
const SHORT_CODE_TO_TYPE: Record<string, SlotTypeKey> = Object.fromEntries(
  Object.entries(TYPE_SHORT_CODES).map(([k, v]) => [v, k as SlotTypeKey]),
);

// ── localStorage helpers ─────────────────────────────────────────

interface SavedTeam {
  slots: (PlayerSummary | null)[];
  slotTypes?: SlotTypeKey[];
  savedAt: number;
}

function saveTeamToStorage(
  slots: (PlayerSummary | null)[],
  slotTypes?: SlotTypeKey[],
) {
  try {
    const data: SavedTeam = { slots, slotTypes, savedAt: Date.now() };
    localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(data));
  } catch {
    // localStorage may be full or unavailable — silently ignore
  }
}

function loadTeamFromStorage(): SavedTeam | null {
  try {
    const raw = localStorage.getItem(LOCALSTORAGE_KEY);
    if (!raw) return null;
    const data: SavedTeam = JSON.parse(raw);
    // Expire after 30 days
    if (Date.now() - data.savedAt > 30 * 24 * 60 * 60 * 1000) {
      localStorage.removeItem(LOCALSTORAGE_KEY);
      return null;
    }
    if (!Array.isArray(data.slots)) return null;
    // Ensure correct length
    const slots: (PlayerSummary | null)[] = Array(MAX_PLAYERS).fill(null);
    for (let i = 0; i < Math.min(data.slots.length, MAX_PLAYERS); i++) {
      slots[i] = data.slots[i] ?? null;
    }
    return { slots, slotTypes: data.slotTypes, savedAt: data.savedAt };
  } catch {
    return null;
  }
}

function clearTeamStorage() {
  try {
    localStorage.removeItem(LOCALSTORAGE_KEY);
  } catch {
    // ignore
  }
}

interface AutoFillStrategy {
  key: string;
  label: string;
  shortLabel: string;
  icon: React.ReactNode;
  description: string;
  needsCountry?: boolean;
}

const AUTO_FILL_STRATEGIES: AutoFillStrategy[] = [
  {
    key: "war",
    label: "Best XI by WAR",
    shortLabel: "Best WAR",
    icon: <Trophy size={14} />,
    description: "Pick the highest-WAR players, respecting positional balance",
  },
  {
    key: "power",
    label: "Best Power XI",
    shortLabel: "Power",
    icon: <Zap size={14} />,
    description: "Maximise batting power + bowling threat",
  },
  {
    key: "control",
    label: "Best Control XI",
    shortLabel: "Control",
    icon: <Shield size={14} />,
    description: "Maximise batting control + bowling control",
  },
  {
    key: "country",
    label: "Best Country XI",
    shortLabel: "Country",
    icon: <Globe size={14} />,
    description: "Best XI from a single country",
    needsCountry: true,
  },
];

// ── Radar chart component ────────────────────────────────────────

interface RadarAxis {
  label: string;
  shortLabel: string;
  value: number | null;
}

function TeamRadar({ axes }: { axes: RadarAxis[] }) {
  const size = 300;
  const center = size / 2;
  const maxRadius = size / 2 - 45;
  const n = axes.length;

  if (n < 3) return null;

  const angleStep = (2 * Math.PI) / n;
  const startAngle = -Math.PI / 2;
  const gridLevels = [20, 40, 60, 80, 100];

  const points = axes.map((axis, i) => {
    const val = axis.value ?? 0;
    const r = (Math.min(100, Math.max(0, val)) / 100) * maxRadius;
    const angle = startAngle + i * angleStep;
    return {
      x: center + r * Math.cos(angle),
      y: center + r * Math.sin(angle),
      labelX: center + (maxRadius + 25) * Math.cos(angle),
      labelY: center + (maxRadius + 25) * Math.sin(angle),
      label: axis.shortLabel,
      value: val,
    };
  });

  const polygonPath = points.map((p) => `${p.x},${p.y}`).join(" ");

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="overflow-visible mx-auto"
    >
      {/* Grid polygons */}
      {gridLevels.map((level) => {
        const r = (level / 100) * maxRadius;
        const pts = Array.from({ length: n }, (_, i) => {
          const angle = startAngle + i * angleStep;
          return `${center + r * Math.cos(angle)},${center + r * Math.sin(angle)}`;
        }).join(" ");
        return (
          <polygon
            key={level}
            points={pts}
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

      {/* Team polygon */}
      <polygon
        points={polygonPath}
        fill="rgba(59, 130, 246, 0.15)"
        stroke="#3B82F6"
        strokeWidth={2}
      />

      {/* Data points */}
      {points.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={4}
          fill="#3B82F6"
          stroke="white"
          strokeWidth={1.5}
        />
      ))}

      {/* Labels */}
      {points.map((p, i) => (
        <g key={`label-${i}`}>
          <text
            x={p.labelX}
            y={p.labelY - 7}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-text-secondary"
            fontSize={11}
            fontWeight={500}
          >
            {p.label}
          </text>
          <text
            x={p.labelX}
            y={p.labelY + 7}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={10}
            fontWeight={600}
            style={{ fill: scoreToColour(p.value) }}
          >
            {p.value > 0 ? p.value.toFixed(0) : "—"}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ── Player slot component ────────────────────────────────────────

interface PlayerSlotProps {
  index: number;
  slotLabel: string;
  slotIcon: string;
  player: PlayerSummary | null;
  onSelect: (player: PlayerSummary) => void;
  onRemove: () => void;
  excludeIds: string[];
  onLabelClick?: () => void;
}

function PlayerSlot({
  index,
  slotLabel,
  slotIcon,
  player,
  onSelect,
  onRemove,
  excludeIds,
  onLabelClick,
}: PlayerSlotProps) {
  if (player) {
    const isBowler = player.role === "bowl";
    const flag = countryFlag(player.country);

    return (
      <div className="flex items-center gap-3 p-3 rounded-lg bg-surface-elevated/50 hover:bg-surface-elevated/70 transition-colors group">
        {/* Slot number */}
        <span className="w-6 h-6 flex items-center justify-center rounded-full bg-primary/20 text-primary text-xs font-semibold shrink-0">
          {index + 1}
        </span>

        {/* Player info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            {flag && <span className="text-sm">{flag}</span>}
            <span className="text-sm font-medium text-text-primary truncate">
              {player.name}
            </span>
            <GradeBadge grade={player.grade_overall} size="xs" />
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs text-text-muted">
              {player.archetype || (isBowler ? "Bowler" : "Batter")}
            </span>
            <span className="text-xs text-text-muted">·</span>
            <span className="text-xs text-text-muted">
              {isBowler
                ? `${player.total_runs} wkts`
                : `${player.total_runs} runs`}
            </span>
          </div>
        </div>

        {/* Score bars (compact) */}
        <div className="hidden sm:flex items-center gap-3 shrink-0">
          <div className="text-center">
            <span className="text-[10px] text-text-muted uppercase block">
              {player.score_1_label?.slice(0, 3) ?? "S1"}
            </span>
            <span
              className="text-xs font-score tabular-nums font-semibold"
              style={{ color: scoreToColour(player.score_1) }}
            >
              {player.score_1 != null ? Math.round(player.score_1) : "—"}
            </span>
          </div>
          <div className="text-center">
            <span className="text-[10px] text-text-muted uppercase block">
              {player.score_2_label?.slice(0, 3) ?? "S2"}
            </span>
            <span
              className="text-xs font-score tabular-nums font-semibold"
              style={{ color: scoreToColour(player.score_2) }}
            >
              {player.score_2 != null ? Math.round(player.score_2) : "—"}
            </span>
          </div>
          <div className="text-center">
            <span className="text-[10px] text-text-muted uppercase block">
              {player.score_3_label?.slice(0, 3) ?? "S3"}
            </span>
            <span
              className="text-xs font-score tabular-nums font-semibold"
              style={{ color: scoreToColour(player.score_3) }}
            >
              {player.score_3 != null ? Math.round(player.score_3) : "—"}
            </span>
          </div>
        </div>

        {/* Remove button */}
        <button
          onClick={onRemove}
          className="p-1.5 rounded-lg text-text-muted hover:text-danger hover:bg-danger/10 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
          title="Remove player"
          aria-label={`Remove ${player.name}`}
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  // Empty slot — show autocomplete
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border border-dashed border-surface-elevated hover:border-primary/30 transition-colors">
      {/* Slot number */}
      <span className="w-6 h-6 flex items-center justify-center rounded-full bg-surface-elevated text-text-muted text-xs font-semibold shrink-0">
        {index + 1}
      </span>

      {/* Slot label — click to cycle role */}
      <button
        onClick={onLabelClick}
        className="text-xs text-text-muted hover:text-primary transition-colors cursor-pointer select-none shrink-0 w-20 text-left"
        title="Click to change slot role"
      >
        {slotIcon} {slotLabel}
      </button>

      {/* Autocomplete */}
      <div className="flex-1 min-w-0">
        <PlayerAutocomplete
          placeholder={`Add ${slotLabel}…`}
          onSelect={onSelect}
          excludeIds={excludeIds}
          size="sm"
        />
      </div>
    </div>
  );
}

// ── Analysis panel component ─────────────────────────────────────

interface AnalysisPanelProps {
  analysis: TeamAnalysis | undefined;
  isLoading: boolean;
  playerCount: number;
}

function AnalysisPanel({
  analysis,
  isLoading,
  playerCount,
}: AnalysisPanelProps) {
  const [showDetails, setShowDetails] = useState(true);

  if (playerCount === 0) {
    return (
      <div className="card p-6 text-center">
        <Users size={32} className="mx-auto mb-2 text-text-muted opacity-30" />
        <p className="text-sm text-text-muted">
          Add players to see team analysis
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="card p-6 space-y-4">
        <div className="skeleton h-6 w-40" />
        <div className="skeleton h-72 w-full rounded-lg" />
        <div className="grid grid-cols-3 gap-3">
          <div className="skeleton h-16 w-full" />
          <div className="skeleton h-16 w-full" />
          <div className="skeleton h-16 w-full" />
        </div>
      </div>
    );
  }

  if (!analysis) {
    return null;
  }

  // Build radar axes
  const radarAxes: RadarAxis[] = [
    {
      label: "Batting Acceleration",
      shortLabel: "Bat ACC",
      value: analysis.avg_acceleration,
    },
    {
      label: "Batting Power",
      shortLabel: "Bat POW",
      value: analysis.avg_bat_power,
    },
    {
      label: "Batting Control",
      shortLabel: "Bat CTL",
      value: analysis.avg_bat_control,
    },
    {
      label: "Bowling Accuracy",
      shortLabel: "Bowl ACR",
      value: analysis.avg_accuracy,
    },
    {
      label: "Bowling Control",
      shortLabel: "Bowl CTL",
      value: analysis.avg_bowl_control,
    },
    {
      label: "Bowling Threat",
      shortLabel: "Bowl THR",
      value: analysis.avg_threat,
    },
  ];

  const totalWAR =
    (analysis.total_war_batting ?? 0) + (analysis.total_war_bowling ?? 0);

  return (
    <div className="card p-4 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-h3 text-text-primary flex items-center gap-2">
          📊 Team Analysis
        </h2>
        <span className="text-xs text-text-muted">
          {analysis.player_count} player{analysis.player_count !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Radar chart */}
      <TeamRadar axes={radarAxes} />

      {/* Aggregate stats */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full flex items-center justify-between text-sm text-text-secondary hover:text-text-primary transition-colors py-1"
      >
        <span className="font-medium">Detailed Scores</span>
        {showDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {showDetails && (
        <div className="space-y-4">
          {/* Batting */}
          <div>
            <h3 className="text-xs text-text-muted uppercase tracking-wider mb-2">
              Batting Strength (
              {analysis.genuine_batter_count ?? analysis.batters.length}{" "}
              batters)
            </h3>
            <div className="space-y-1.5">
              <ScoreBar
                value={analysis.avg_acceleration}
                label="Acceleration"
                size="sm"
                variant="full"
                labelWidth="w-28"
              />
              <ScoreBar
                value={analysis.avg_bat_power}
                label="Power"
                size="sm"
                variant="full"
                labelWidth="w-28"
              />
              <ScoreBar
                value={analysis.avg_bat_control}
                label="Control"
                size="sm"
                variant="full"
                labelWidth="w-28"
              />
            </div>
          </div>

          {/* Bowling */}
          <div>
            <h3 className="text-xs text-text-muted uppercase tracking-wider mb-2">
              Bowling Strength (
              {analysis.genuine_bowler_count ?? analysis.bowlers.length}{" "}
              bowlers)
            </h3>
            <div className="space-y-1.5">
              <ScoreBar
                value={analysis.avg_accuracy}
                label="Accuracy"
                size="sm"
                variant="full"
                labelWidth="w-28"
              />
              <ScoreBar
                value={analysis.avg_bowl_control}
                label="Control"
                size="sm"
                variant="full"
                labelWidth="w-28"
              />
              <ScoreBar
                value={analysis.avg_threat}
                label="Threat"
                size="sm"
                variant="full"
                labelWidth="w-28"
              />
            </div>
          </div>

          {/* WAR & Clutch */}
          <div className="grid grid-cols-3 gap-3">
            <div className="p-3 rounded-lg bg-surface-elevated/50 text-center">
              <span className="text-xs text-text-muted block uppercase tracking-wider">
                Total WAR
              </span>
              <span className="text-lg font-score tabular-nums font-semibold text-primary">
                {totalWAR > 0 ? totalWAR.toFixed(1) : "—"}
              </span>
            </div>
            <div className="p-3 rounded-lg bg-surface-elevated/50 text-center">
              <span className="text-xs text-text-muted block uppercase tracking-wider">
                Bat WAR
              </span>
              <span className="text-lg font-score tabular-nums font-semibold">
                {analysis.total_war_batting != null
                  ? analysis.total_war_batting.toFixed(1)
                  : "—"}
              </span>
            </div>
            <div className="p-3 rounded-lg bg-surface-elevated/50 text-center">
              <span className="text-xs text-text-muted block uppercase tracking-wider">
                Avg Clutch
              </span>
              <span
                className="text-lg font-score tabular-nums font-semibold"
                style={{
                  color:
                    analysis.avg_clutch != null && analysis.avg_clutch > 0
                      ? "#10B981"
                      : analysis.avg_clutch != null && analysis.avg_clutch < 0
                        ? "#EF4444"
                        : undefined,
                }}
              >
                {analysis.avg_clutch != null
                  ? (analysis.avg_clutch > 0 ? "+" : "") +
                    analysis.avg_clutch.toFixed(1)
                  : "—"}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Weaknesses */}
      {analysis.weaknesses.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs text-text-muted uppercase tracking-wider flex items-center gap-1.5">
            <AlertTriangle size={12} className="text-warning" />
            Weaknesses Detected
          </h3>
          <div className="space-y-1">
            {analysis.weaknesses.map((w, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-sm text-warning bg-warning/5 rounded-lg px-3 py-2"
              >
                <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                <span>{w}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page component ──────────────────────────────────────────

// ── Comparison Panel (Team A vs Team B) ──────────────────────────

function ComparisonPanel({
  data,
  isLoading,
}: {
  data: TeamCompareResponse;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="card p-4 animate-pulse text-sm text-text-muted">
        Computing comparison…
      </div>
    );
  }

  const { team_a, team_b, comparison } = data;

  const edgeLabel = (edge: string) => {
    if (edge === "even") return "Even";
    return edge === "A" ? "Team A" : "Team B";
  };

  const edgeColour = (edge: string) => {
    if (edge === "even") return "text-text-muted";
    return edge === "A" ? "text-primary" : "text-accent";
  };

  const rows: { label: string; edge: string; diff: number; unit?: string }[] = [
    {
      label: "Batting",
      edge: comparison.batting_edge,
      diff: comparison.batting_diff,
    },
    {
      label: "Bowling",
      edge: comparison.bowling_edge,
      diff: comparison.bowling_diff,
    },
    { label: "WAR", edge: comparison.war_edge, diff: comparison.war_diff },
    { label: "Clutch", edge: comparison.clutch_edge, diff: 0 },
  ];

  return (
    <div className="card p-4 space-y-4 mt-4">
      <h3 className="text-h4 text-text-primary flex items-center gap-2">
        <Swords size={16} className="text-primary" />
        Head-to-Head Comparison
      </h3>

      {/* Edge summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {rows.map((r) => (
          <div
            key={r.label}
            className="rounded-lg bg-surface-elevated p-3 text-center space-y-1"
          >
            <div className="text-xs text-text-muted">{r.label} Edge</div>
            <div className={`text-sm font-bold ${edgeColour(r.edge)}`}>
              {edgeLabel(r.edge)}
            </div>
            {r.diff !== 0 && (
              <div className="text-[10px] text-text-muted">
                {r.diff > 0 ? "+" : ""}
                {r.diff.toFixed(1)}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Side-by-side aggregates */}
      <div className="grid grid-cols-2 gap-4 text-xs">
        {/* Team A */}
        <div className="space-y-2">
          <div className="font-medium text-text-primary text-sm">Team A</div>
          <div className="space-y-1">
            <StatCompareRow
              label="Batters"
              value={team_a.genuine_batter_count ?? team_a.batters.length}
            />
            <StatCompareRow
              label="Bowlers"
              value={team_a.genuine_bowler_count ?? team_a.bowlers.length}
            />
            <StatCompareRow label="Avg ACC" value={team_a.avg_acceleration} />
            <StatCompareRow label="Avg POW" value={team_a.avg_bat_power} />
            <StatCompareRow label="Avg CTL" value={team_a.avg_bat_control} />
            <StatCompareRow label="Avg Accuracy" value={team_a.avg_accuracy} />
            <StatCompareRow label="Avg Threat" value={team_a.avg_threat} />
            <StatCompareRow
              label="Total WAR"
              value={(
                (team_a.total_war_batting ?? 0) +
                (team_a.total_war_bowling ?? 0)
              ).toFixed(1)}
            />
          </div>
        </div>
        {/* Team B */}
        <div className="space-y-2">
          <div className="font-medium text-text-primary text-sm">Team B</div>
          <div className="space-y-1">
            <StatCompareRow
              label="Batters"
              value={team_b.genuine_batter_count ?? team_b.batters.length}
            />
            <StatCompareRow
              label="Bowlers"
              value={team_b.genuine_bowler_count ?? team_b.bowlers.length}
            />
            <StatCompareRow label="Avg ACC" value={team_b.avg_acceleration} />
            <StatCompareRow label="Avg POW" value={team_b.avg_bat_power} />
            <StatCompareRow label="Avg CTL" value={team_b.avg_bat_control} />
            <StatCompareRow label="Avg Accuracy" value={team_b.avg_accuracy} />
            <StatCompareRow label="Avg Threat" value={team_b.avg_threat} />
            <StatCompareRow
              label="Total WAR"
              value={(
                (team_b.total_war_batting ?? 0) +
                (team_b.total_war_bowling ?? 0)
              ).toFixed(1)}
            />
          </div>
        </div>
      </div>

      {/* Weaknesses */}
      <div className="grid grid-cols-2 gap-4 text-xs">
        <div>
          <div className="text-text-muted mb-1">Team A Weaknesses</div>
          {team_a.weaknesses.length === 0 ? (
            <span className="text-green-400">None detected ✓</span>
          ) : (
            <ul className="space-y-0.5">
              {team_a.weaknesses.map((w, i) => (
                <li key={i} className="text-warning flex items-start gap-1">
                  <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div className="text-text-muted mb-1">Team B Weaknesses</div>
          {team_b.weaknesses.length === 0 ? (
            <span className="text-green-400">None detected ✓</span>
          ) : (
            <ul className="space-y-0.5">
              {team_b.weaknesses.map((w, i) => (
                <li key={i} className="text-warning flex items-start gap-1">
                  <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCompareRow({
  label,
  value,
}: {
  label: string;
  value: number | string | null | undefined;
}) {
  const display =
    value == null ? "—" : typeof value === "number" ? value.toFixed(1) : value;
  return (
    <div className="flex justify-between">
      <span className="text-text-muted">{label}</span>
      <span className="text-text-primary font-score tabular-nums">
        {display}
      </span>
    </div>
  );
}

export default function TeamBuilder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlLoadAttempted = useRef(false);
  const [urlLoading, setUrlLoading] = useState(false);

  // ── State: selected players ────────────────────────────────
  // Initialise from localStorage if available
  const [slots, setSlots] = useState<(PlayerSummary | null)[]>(() => {
    const saved = loadTeamFromStorage();
    if (saved) return saved.slots;
    return Array(MAX_PLAYERS).fill(null) as (PlayerSummary | null)[];
  });

  const [slotTypes, setSlotTypes] = useState<SlotTypeKey[]>(() => {
    const saved = loadTeamFromStorage();
    if (saved?.slotTypes && saved.slotTypes.length === MAX_PLAYERS)
      return saved.slotTypes;
    return [...DEFAULT_SLOT_TYPES];
  });

  const [copied, setCopied] = useState(false);
  const [autoFillStrategy, setAutoFillStrategy] = useState<string | null>(null);
  const [autoFillCountry, setAutoFillCountry] = useState<string | null>(null);
  const [showAutoFill, setShowAutoFill] = useState(false);

  // ── State: Compare mode (Team B) ───────────────────────────
  const [isCompareMode, setIsCompareMode] = useState(false);
  const [slotsB, setSlotsB] = useState<(PlayerSummary | null)[]>(
    () => Array(MAX_PLAYERS).fill(null) as (PlayerSummary | null)[],
  );
  const [slotTypesB, setSlotTypesB] = useState<SlotTypeKey[]>(() => [
    ...DEFAULT_SLOT_TYPES,
  ]);

  // Countries for country auto-fill
  const { data: countries } = useCountries();

  // ── Persist to localStorage on every slot/type change ──────
  useEffect(() => {
    saveTeamToStorage(slots, slotTypes);
  }, [slots, slotTypes]);

  // ── URL pre-fill: load from ?ids= on mount ────────────────
  // When the page loads with ?ids=id1,id2,..., fetch each player's
  // summary via the search endpoint and populate the slots.
  useEffect(() => {
    if (urlLoadAttempted.current) return;
    urlLoadAttempted.current = true;

    const idsParam = searchParams.get("ids");
    if (!idsParam) return;

    // Decode slot types from URL if present
    const typesParam = searchParams.get("types");
    if (typesParam) {
      const decoded = [...typesParam].map(
        (c) => SHORT_CODE_TO_TYPE[c] ?? "bowler",
      );
      while (decoded.length < MAX_PLAYERS)
        decoded.push(DEFAULT_SLOT_TYPES[decoded.length] ?? "bowler");
      setSlotTypes(decoded.slice(0, MAX_PLAYERS));
    }

    const ids = idsParam
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, MAX_PLAYERS);

    if (ids.length === 0) return;

    setUrlLoading(true);

    // Fetch player profiles for each ID, then populate slots
    Promise.all(
      ids.map(async (id) => {
        try {
          const profile = await api.getPlayer(id);
          // Convert the full profile to a PlayerSummary shape
          const isBat = "score_acceleration" in profile;
          const summary: PlayerSummary = {
            id: profile.id,
            name: profile.name,
            country: profile.country,
            role: isBat ? "bat" : "bowl",
            archetype: profile.archetype,
            grade_overall: isBat
              ? ((profile as any).overall_grade ?? "D")
              : ((profile as any).overall_grade ?? "D"),
            innings_count: isBat
              ? ((profile as any).innings_count ?? 0)
              : ((profile as any).matches ?? 0),
            total_runs: isBat
              ? ((profile as any).total_runs ?? 0)
              : ((profile as any).total_wickets ?? 0),
            career_sr: isBat
              ? ((profile as any).career_sr ?? null)
              : ((profile as any).career_economy ?? null),
            career_avg: (profile as any).career_avg ?? null,
            score_1: isBat
              ? ((profile as any).score_acceleration ?? null)
              : ((profile as any).score_accuracy ?? null),
            score_2: isBat
              ? ((profile as any).score_power ?? null)
              : ((profile as any).score_control ?? null),
            score_3: isBat
              ? ((profile as any).score_control ?? null)
              : ((profile as any).score_threat ?? null),
            score_1_label: isBat ? "acceleration" : "accuracy",
            score_2_label: isBat ? "power" : "control",
            score_3_label: isBat ? "control" : "threat",
            is_provisional: (profile as any).is_provisional ?? true,
            overall_score: (profile as any).overall_score ?? null,
          };
          return summary;
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      const newSlots: (PlayerSummary | null)[] = Array(MAX_PLAYERS).fill(null);
      for (let i = 0; i < results.length; i++) {
        if (results[i] && i < MAX_PLAYERS) {
          newSlots[i] = results[i];
        }
      }
      if (results.some((r) => r != null)) {
        setSlots(newSlots);
      }
      setUrlLoading(false);
    });
  }, [searchParams]);

  // ── Derived values ─────────────────────────────────────────
  const selectedIds = useMemo(
    () => slots.filter((s): s is PlayerSummary => s !== null).map((s) => s.id),
    [slots],
  );

  // Slot types aligned with selectedIds (only for filled slots)
  const selectedSlotTypes = useMemo(
    () =>
      slots.reduce<string[]>((acc, s, i) => {
        if (s !== null) acc.push(slotTypes[i]);
        return acc;
      }, []),
    [slots, slotTypes],
  );

  const playerCount = selectedIds.length;

  // ── Derived values for Team B (compare mode) ───────────────
  const selectedIdsB = useMemo(
    () => slotsB.filter((s): s is PlayerSummary => s !== null).map((s) => s.id),
    [slotsB],
  );

  const playerCountB = selectedIdsB.length;

  const excludeIds = useMemo(
    () => (isCompareMode ? [...selectedIds, ...selectedIdsB] : selectedIds),
    [selectedIds, selectedIdsB, isCompareMode],
  );

  const excludeIdsB = useMemo(
    () => [...selectedIdsB, ...selectedIds],
    [selectedIdsB, selectedIds],
  );

  // ── Team comparison query (compare mode) ───────────────────
  const teamCompare = useTeamCompare(
    isCompareMode ? selectedIds : [],
    isCompareMode ? selectedIdsB : [],
  );

  // ── Team analysis query ────────────────────────────────────
  const { data: analysis, isLoading: analysisLoading } = useTeamAnalysis(
    selectedIds,
    selectedSlotTypes,
  );

  // ── Auto-fill query (only when triggered) ──────────────────
  const [autoFillEnabled, setAutoFillEnabled] = useState(false);

  const { data: autoFillData, isLoading: autoFillLoading } = useTeamAutoFill({
    strategy: autoFillStrategy ?? "war",
    country: autoFillCountry,
    exclude: [],
    enabled: autoFillEnabled && !!autoFillStrategy,
  });

  // Apply auto-fill results when they arrive
  useEffect(() => {
    if (!autoFillData || !autoFillEnabled) return;

    // Merge batters and bowlers into slots
    const allPlayers: PlayerSummary[] = [
      ...autoFillData.batters,
      ...autoFillData.bowlers,
    ];

    // Deduplicate by ID
    const seen = new Set<string>();
    const unique: PlayerSummary[] = [];
    for (const p of allPlayers) {
      if (!seen.has(p.id)) {
        seen.add(p.id);
        unique.push(p);
      }
    }

    // Fill slots
    const newSlots: (PlayerSummary | null)[] = Array(MAX_PLAYERS).fill(null);
    for (let i = 0; i < Math.min(unique.length, MAX_PLAYERS); i++) {
      newSlots[i] = unique[i];
    }

    setSlots(newSlots);
    setAutoFillEnabled(false);
  }, [autoFillData, autoFillEnabled]);

  // ── Handlers ───────────────────────────────────────────────

  // Known bowling archetypes from the pipeline — used to auto-assign slot type
  // ── Handlers for Team B ────────────────────────────────────
  const handleAddPlayerB = useCallback(
    (slotIndex: number, player: PlayerSummary) => {
      setSlotsB((prev) => {
        const next = [...prev];
        next[slotIndex] = player;
        return next;
      });
      // Auto-assign slot type based on role/archetype (same logic as Team A)
      const isBowlingArchetype =
        player.role === "bowl" ||
        BOWLING_ARCHETYPE_LABELS.has(player.archetype ?? "");
      if (isBowlingArchetype) {
        setSlotTypesB((prev) => {
          const next = [...prev];
          next[slotIndex] = "bowler";
          return next;
        });
      }
    },
    [],
  );

  const handleRemovePlayerB = useCallback((slotIndex: number) => {
    setSlotsB((prev) => {
      const next = [...prev];
      next[slotIndex] = null;
      return next;
    });
  }, []);

  const handleClearAllB = useCallback(() => {
    setSlotsB(Array(MAX_PLAYERS).fill(null));
    setSlotTypesB([...DEFAULT_SLOT_TYPES]);
  }, []);

  const BOWLING_ARCHETYPE_LABELS = useMemo(
    () =>
      new Set([
        "Death Specialist",
        "Powerplay Enforcer",
        "Strike Bowler",
        "Spin Restrictor",
        "Economical",
        "All-Round Threat",
        "Restrictive Spinner",
        "Enforcer",
      ]),
    [],
  );

  const handleAddPlayer = useCallback(
    (index: number, player: PlayerSummary) => {
      setSlots((prev) => {
        const next = [...prev];
        next[index] = player;
        return next;
      });

      // Auto-assign slot type based on the player's actual role/archetype.
      // This ensures the slot label reflects what the player actually is,
      // rather than relying on the static default slot position.
      setSlotTypes((prev) => {
        const next = [...prev];
        const isBowlingArchetype = BOWLING_ARCHETYPE_LABELS.has(
          player.archetype,
        );

        if (player.role === "bowl" || isBowlingArchetype) {
          // Player is a bowler — set slot to "bowler"
          next[index] = "bowler";
        } else if (player.role === "bat" && next[index] === "bowler") {
          // Player is a batter but was placed in a bowler slot —
          // switch to a sensible batting slot type based on position
          if (index <= 1) {
            next[index] = "opener";
          } else if (index <= 3) {
            next[index] = "top_order";
          } else if (index <= 6) {
            next[index] = "middle_order";
          } else {
            next[index] = "finisher_wk";
          }
        }
        // Otherwise keep the existing slot type (it's already a batting type)
        return next;
      });
    },
    [],
  );

  const handleRemovePlayer = useCallback((index: number) => {
    setSlots((prev) => {
      const next = [...prev];
      next[index] = null;
      return next;
    });
  }, []);

  const handleClearAll = useCallback(() => {
    setSlots(Array(MAX_PLAYERS).fill(null));
    setSlotTypes([...DEFAULT_SLOT_TYPES]);
    clearTeamStorage();
  }, []);

  const handleAutoFill = useCallback(
    (strategy: string, country?: string | null) => {
      setAutoFillStrategy(strategy);
      setAutoFillCountry(country ?? null);
      setAutoFillEnabled(true);
    },
    [],
  );

  const handleShare = useCallback(() => {
    if (selectedIds.length === 0) return;

    const url = new URL(window.location.href);
    // Encode player IDs in slot order (preserving gaps as empty)
    const orderedIds = slots.map((s) => s?.id ?? "").join(",");
    url.searchParams.set("ids", orderedIds);
    // Encode slot types compactly
    url.searchParams.set(
      "types",
      slotTypes.map((t) => TYPE_SHORT_CODES[t]).join(""),
    );
    const shareUrl = url.toString();

    if (navigator.clipboard) {
      navigator.clipboard.writeText(shareUrl).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  }, [selectedIds, slots, slotTypes]);

  const handleCompare = useCallback(() => {
    if (selectedIds.length < 2) return;
    const ids = selectedIds.slice(0, 4).join(",");
    navigate(`/compare?ids=${ids}`);
  }, [selectedIds, navigate]);

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      {/* ── Page header ───────────────────────────────────────── */}
      <div>
        <h1 className="text-h1 text-text-primary flex items-center gap-2">
          <Users size={24} className="text-primary" />
          Team Builder
        </h1>
        <p className="text-sm text-text-secondary mt-1 max-w-2xl">
          Build a hypothetical T20I XI and see how your team stacks up. Add
          players to slots, view aggregate metrics, and detect team weaknesses.
        </p>
        <div className="mt-2">
          <button
            onClick={() => setIsCompareMode(!isCompareMode)}
            className={`btn-sm text-xs flex items-center gap-1.5 ${
              isCompareMode ? "btn-primary" : "btn-secondary"
            }`}
          >
            <Swords size={14} />
            {isCompareMode ? "Exit Compare Mode" : "⚔️ Compare Teams"}
          </button>
        </div>
      </div>

      {/* URL loading indicator */}
      {urlLoading && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-primary/10 text-sm text-primary animate-pulse">
          <span className="animate-spin-slow">⏳</span>
          Loading team from shared URL…
        </div>
      )}

      {/* ── Main layout: slots + analysis ─────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* ── Left: Player slots (3/5 width) ───────────────── */}
        <div className="lg:col-span-3 space-y-4">
          {/* Slot header */}
          <div className="flex items-center justify-between">
            <h2 className="text-h3 text-text-primary">
              {isCompareMode ? "Team A" : "Your XI"}{" "}
              <span className="text-text-muted font-normal text-sm">
                ({playerCount}/{MAX_PLAYERS})
              </span>
            </h2>
            <div className="flex items-center gap-2">
              {playerCount >= 2 && (
                <button
                  onClick={handleCompare}
                  className="btn-ghost btn-sm text-xs"
                  title="Compare selected players"
                >
                  Compare
                </button>
              )}
              {playerCount > 0 && (
                <button
                  onClick={handleClearAll}
                  className="btn-ghost btn-sm text-xs text-danger hover:text-danger"
                  title="Clear all players"
                >
                  <Trash2 size={12} />
                  Clear
                </button>
              )}
            </div>
          </div>

          {/* Player slots */}
          <div className="space-y-2">
            {slots.map((player, i) => {
              const typeOption =
                SLOT_TYPE_OPTIONS.find((t) => t.key === slotTypes[i]) ??
                SLOT_TYPE_OPTIONS[0];
              return (
                <PlayerSlot
                  key={i}
                  index={i}
                  slotLabel={typeOption.label}
                  slotIcon={typeOption.icon}
                  player={player}
                  onSelect={(p) => handleAddPlayer(i, p)}
                  onRemove={() => handleRemovePlayer(i)}
                  excludeIds={excludeIds}
                  onLabelClick={() => {
                    setSlotTypes((prev) => {
                      const next = [...prev];
                      const curIdx = SLOT_TYPE_OPTIONS.findIndex(
                        (t) => t.key === next[i],
                      );
                      next[i] =
                        SLOT_TYPE_OPTIONS[
                          (curIdx + 1) % SLOT_TYPE_OPTIONS.length
                        ].key;
                      return next;
                    });
                  }}
                />
              );
            })}
          </div>

          {/* Constraints note */}
          {!isCompareMode && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-surface-elevated/30 text-xs text-text-muted">
              <Info size={14} className="shrink-0 mt-0.5 text-text-muted" />
              <span>
                Recommended: 5–6 batters, 4–5 bowlers, at least 1 all-rounder.
                Slot labels are suggestions — add any player to any slot.
              </span>
            </div>
          )}

          {/* ── Team B slots (compare mode) ────────────────── */}
          {isCompareMode && (
            <div className="space-y-4 mt-6 pt-6 border-t border-border/50">
              <div className="flex items-center justify-between">
                <h2 className="text-h3 text-text-primary">
                  Team B{" "}
                  <span className="text-text-muted font-normal text-sm">
                    ({playerCountB}/{MAX_PLAYERS})
                  </span>
                </h2>
                {playerCountB > 0 && (
                  <button
                    onClick={handleClearAllB}
                    className="btn-ghost btn-sm text-xs text-danger hover:text-danger"
                    title="Clear Team B"
                  >
                    <Trash2 size={12} />
                    Clear
                  </button>
                )}
              </div>
              <div className="space-y-2">
                {slotsB.map((player, i) => {
                  const typeOption =
                    SLOT_TYPE_OPTIONS.find((t) => t.key === slotTypesB[i]) ??
                    SLOT_TYPE_OPTIONS[0];
                  return (
                    <PlayerSlot
                      key={`b-${i}`}
                      index={i}
                      slotLabel={typeOption.label}
                      slotIcon={typeOption.icon}
                      player={player}
                      onSelect={(p) => handleAddPlayerB(i, p)}
                      onRemove={() => handleRemovePlayerB(i)}
                      excludeIds={excludeIdsB}
                      onLabelClick={() => {
                        setSlotTypesB((prev) => {
                          const next = [...prev];
                          const curIdx = SLOT_TYPE_OPTIONS.findIndex(
                            (t) => t.key === next[i],
                          );
                          next[i] =
                            SLOT_TYPE_OPTIONS[
                              (curIdx + 1) % SLOT_TYPE_OPTIONS.length
                            ].key;
                          return next;
                        });
                      }}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Comparison Panel ────────────────────────────── */}
          {isCompareMode && teamCompare.data && (
            <ComparisonPanel
              data={teamCompare.data}
              isLoading={teamCompare.isLoading}
            />
          )}

          {/* ── Auto-fill templates ─────────────────────────── */}
          <div className="space-y-3">
            <button
              onClick={() => setShowAutoFill(!showAutoFill)}
              className="flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
            >
              <Wand2 size={14} />
              <span className="font-medium">Auto-Fill Templates</span>
              {showAutoFill ? (
                <ChevronUp size={14} />
              ) : (
                <ChevronDown size={14} />
              )}
            </button>

            {showAutoFill && (
              <div className="card p-4 space-y-3">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {AUTO_FILL_STRATEGIES.filter((s) => !s.needsCountry).map(
                    (strategy) => (
                      <button
                        key={strategy.key}
                        onClick={() => handleAutoFill(strategy.key)}
                        disabled={autoFillLoading}
                        className="btn-secondary btn-sm text-xs flex flex-col items-center gap-1 py-3"
                        title={strategy.description}
                      >
                        {strategy.icon}
                        <span>{strategy.shortLabel}</span>
                      </button>
                    ),
                  )}
                </div>

                {/* Country auto-fill */}
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                  <select
                    value={autoFillCountry ?? ""}
                    onChange={(e) => setAutoFillCountry(e.target.value || null)}
                    className="filter-select text-xs flex-1"
                  >
                    <option value="">Select country…</option>
                    {(countries ?? []).map((c) => (
                      <option key={c} value={c}>
                        {countryFlag(c)} {c}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => {
                      if (autoFillCountry) {
                        handleAutoFill("country", autoFillCountry);
                      }
                    }}
                    disabled={!autoFillCountry || autoFillLoading}
                    className="btn-secondary btn-sm text-xs whitespace-nowrap"
                  >
                    <Globe size={12} />
                    Best {autoFillCountry || "Country"} XI
                  </button>
                </div>

                {autoFillLoading && (
                  <div className="text-xs text-text-muted text-center py-2">
                    ⏳ Finding the best XI…
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Share button ─────────────────────────────────── */}
          {playerCount > 0 && (
            <div className="flex items-center gap-3">
              <button
                onClick={handleShare}
                className="btn-secondary btn-sm text-xs"
              >
                {copied ? (
                  <>
                    <Check size={12} className="text-accent" />
                    Copied!
                  </>
                ) : (
                  <>
                    <Share2 size={12} />
                    Share Team
                  </>
                )}
              </button>
              <span className="text-xs text-text-muted">
                Copies a shareable URL with your team selection
              </span>
            </div>
          )}
        </div>

        {/* ── Right: Team analysis (2/5 width) ─────────────── */}
        <div className="lg:col-span-2 space-y-4">
          <div className="lg:sticky lg:top-20">
            <AnalysisPanel
              analysis={analysis}
              isLoading={analysisLoading}
              playerCount={playerCount}
            />

            {/* Player list summary — in batting order */}
            {analysis && playerCount > 0 && (
              <div className="card p-4 mt-4 space-y-3">
                <h3 className="text-xs text-text-muted uppercase tracking-wider">
                  Batting Order
                </h3>
                <div className="space-y-0.5">
                  {slots.map((player, i) => {
                    if (!player) return null;
                    const typeOption = SLOT_TYPE_OPTIONS.find(
                      (t) => t.key === slotTypes[i],
                    );
                    return (
                      <div
                        key={player.id}
                        className="flex items-center justify-between text-xs py-0.5"
                      >
                        <span className="text-text-muted w-5">{i + 1}</span>
                        <span className="text-text-primary truncate flex-1 ml-1">
                          {countryFlag(player.country)} {player.name}
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-text-muted">
                            {typeOption?.icon ?? ""} {typeOption?.label ?? ""}
                          </span>
                          <span className="text-text-muted">
                            {player.archetype}
                          </span>
                          <GradeBadge grade={player.grade_overall} size="xs" />
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Role grouping — secondary */}
                <div className="pt-2 border-t border-border/30 space-y-2">
                  {analysis.batters.length > 0 && (
                    <div>
                      <span className="text-xs font-medium text-text-secondary">
                        🏏 Batters ({analysis.batters.length})
                      </span>
                      <div className="mt-1 space-y-0.5">
                        {analysis.batters.map((b) => (
                          <div
                            key={b.id}
                            className="flex items-center justify-between text-xs py-0.5"
                          >
                            <span className="text-text-primary truncate max-w-[10rem]">
                              {countryFlag(b.country)} {b.name}
                            </span>
                            <div className="flex items-center gap-2">
                              <span className="text-text-muted">
                                {b.archetype}
                              </span>
                              <GradeBadge grade={b.grade_overall} size="xs" />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {analysis.bowlers.length > 0 && (
                    <div>
                      <span className="text-xs font-medium text-text-secondary">
                        🎳 Bowlers ({analysis.bowlers.length})
                      </span>
                      <div className="mt-1 space-y-0.5">
                        {analysis.bowlers.map((b) => (
                          <div
                            key={b.id}
                            className="flex items-center justify-between text-xs py-0.5"
                          >
                            <span className="text-text-primary truncate max-w-[10rem]">
                              {countryFlag(b.country)} {b.name}
                            </span>
                            <div className="flex items-center gap-2">
                              <span className="text-text-muted">
                                {b.archetype}
                              </span>
                              <GradeBadge grade={b.grade_overall} size="xs" />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
