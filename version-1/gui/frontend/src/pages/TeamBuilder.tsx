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
 *   - Compare mode: 2–4 XIs side-by-side (aligned slots), spec-style metrics + radars
 *
 * Follows gui.md § 6.8 "Team Builder".
 */

import {
  useState,
  useCallback,
  useMemo,
  useEffect,
  useRef,
} from "react";
import { useSearchParams, useNavigate, Link } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
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
  Copy,
  Layers,
  BarChart2,
  Timer,
  CircleDot,
  Combine,
  User,
  Crosshair,
  Sunrise,
  RefreshCw,
  Flame,
  Anchor,
} from "lucide-react";

import {
  useTeamAnalysis,
  useTeamAutoFill,
  useTeamAnalysesParallel,
  useCountries,
} from "@/api/queries";
import type { PlayerSummary, TeamAnalysis } from "@/api/types";
import api from "@/api/client";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import GradeBadge from "@/components/GradeBadge";
import ScoreBar from "@/components/ScoreBar";
import PlayerAvatar from "@/components/PlayerAvatar";
import MetricTooltip from "@/components/MetricTooltip";
import { countryFlag } from "@/lib/format";
import { chartColour, chartColourAlpha, scoreToColour } from "@/lib/colours";

// ── Constants ────────────────────────────────────────────────────

const MAX_PLAYERS = 11;
const MAX_COMPARE_TEAMS = 4;
const LOCALSTORAGE_KEY = "cricket-metrics-team-builder";

type TeamDraft = {
  slots: (PlayerSummary | null)[];
  slotTypes: SlotTypeKey[];
  /** Per-slot bowling phase override for composition (pp | middle | death | "") */
  bowlingPhases: string[];
};

// ── Slot type constants ──────────────────────────────────────────

type SlotTypeKey =
  | "opener"
  | "top_order"
  | "middle_order"
  | "finisher_wk"
  | "allrounder"
  | "bowler";

const SLOT_TYPE_META: Record<
  SlotTypeKey,
  { label: string; Icon: LucideIcon; iconAriaLabel: string }
> = {
  opener: { label: "Opener", Icon: Zap, iconAriaLabel: "Opener slot" },
  top_order: {
    label: "Top Order",
    Icon: Layers,
    iconAriaLabel: "Top order batter slot",
  },
  middle_order: {
    label: "Middle Order",
    Icon: BarChart2,
    iconAriaLabel: "Middle order batter slot",
  },
  finisher_wk: {
    label: "Finisher / WK",
    Icon: Timer,
    iconAriaLabel: "Finisher or wicket-keeper slot",
  },
  allrounder: {
    label: "All-rounder",
    Icon: Combine,
    iconAriaLabel: "All-rounder slot",
  },
  bowler: {
    label: "Bowler",
    Icon: CircleDot,
    iconAriaLabel: "Bowler slot",
  },
};

const SLOT_TYPE_OPTIONS = (
  [
    "opener",
    "top_order",
    "middle_order",
    "finisher_wk",
    "allrounder",
    "bowler",
  ] as const satisfies readonly SlotTypeKey[]
).map((key) => ({ key, ...SLOT_TYPE_META[key] }));

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

function decodeBowlingPhaseCode(c: string): string {
  if (c === "p") return "pp";
  if (c === "m") return "middle";
  if (c === "d") return "death";
  return "";
}

function encodeBowlingPhaseTag(t: string): string {
  if (t === "pp") return "p";
  if (t === "middle") return "m";
  if (t === "death") return "d";
  return "0";
}

/** Sort bowlers PP → middle → death for “suggested order”. */
function bowlerPhaseSortKey(p: PlayerSummary): number {
  const g = (p.phase_group || "").toLowerCase();
  if (g.includes("pp")) return 0;
  if (g.includes("death")) return 2;
  return 1;
}

function emptyBowlingPhases(): string[] {
  return Array(MAX_PLAYERS).fill("");
}

function emptyCompareTeam(): TeamDraft {
  return {
    slots: Array(MAX_PLAYERS).fill(null) as (PlayerSummary | null)[],
    slotTypes: [...DEFAULT_SLOT_TYPES],
    bowlingPhases: emptyBowlingPhases(),
  };
}

function cloneTeamDraft(t: TeamDraft): TeamDraft {
  return {
    slots: [...t.slots],
    slotTypes: [...t.slotTypes],
    bowlingPhases: [...t.bowlingPhases],
  };
}

/** Typical batting-order slots for out-of-position hints (manual XI only). */
const SLOT_TYPICAL_POSITIONS: Record<SlotTypeKey, readonly number[]> = {
  opener: [1, 2],
  top_order: [1, 2, 3],
  middle_order: [3, 4, 5, 6],
  finisher_wk: [4, 5, 6, 7],
  allrounder: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  bowler: [],
};

function battingSlotOutOfPosition(
  player: PlayerSummary,
  slotType: SlotTypeKey,
): boolean {
  if (player.role !== "bat") return false;
  if (slotType === "bowler" || slotType === "allrounder") return false;
  const mp = player.modal_position;
  if (mp == null) return false;
  const allowed = SLOT_TYPICAL_POSITIONS[slotType];
  if (!allowed.length) return false;
  return !allowed.includes(mp);
}

function archetypeIconMeta(
  archetype: string | undefined,
  role: PlayerSummary["role"],
): { Icon: LucideIcon; ariaLabel: string } {
  const raw = archetype?.trim() || (role === "bowl" ? "Bowler" : "Batter");
  const a = raw.toLowerCase();

  if (a.includes("death")) return { Icon: Crosshair, ariaLabel: raw };
  if (a.includes("powerplay")) return { Icon: Sunrise, ariaLabel: raw };
  if (a.includes("spin") || a.includes("spinner"))
    return { Icon: RefreshCw, ariaLabel: raw };
  if (a.includes("strike") || a.includes("enforcer"))
    return { Icon: Zap, ariaLabel: raw };
  if (a.includes("econom") || a.includes("restrict"))
    return { Icon: Shield, ariaLabel: raw };
  if (a.includes("all-round") || a.includes("all round"))
    return { Icon: Combine, ariaLabel: raw };
  if (a.includes("opener") || a.includes("explosive"))
    return { Icon: Zap, ariaLabel: raw };
  if (a.includes("anchor") || a.includes("accumul"))
    return { Icon: Anchor, ariaLabel: raw };
  if (a.includes("finish")) return { Icon: Flame, ariaLabel: raw };
  if (a.includes("middle")) return { Icon: BarChart2, ariaLabel: raw };

  if (role === "bowl") return { Icon: CircleDot, ariaLabel: raw };

  return { Icon: User, ariaLabel: raw };
}

function outOfPositionTooltipText(player: PlayerSummary): string {
  const mp = player.modal_position;
  if (mp == null) return "";
  return `Usually bats #${mp}; this slot is atypical for that role (you can keep them here).`;
}

// ── localStorage helpers ─────────────────────────────────────────

interface SavedTeam {
  slots: (PlayerSummary | null)[];
  slotTypes?: SlotTypeKey[];
  bowlingPhases?: string[];
  savedAt: number;
}

function saveTeamToStorage(
  slots: (PlayerSummary | null)[],
  slotTypes?: SlotTypeKey[],
  bowlingPhases?: string[],
) {
  try {
    const data: SavedTeam = {
      slots,
      slotTypes,
      bowlingPhases,
      savedAt: Date.now(),
    };
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
    const bp = Array.isArray(data.bowlingPhases)
      ? [...data.bowlingPhases]
      : emptyBowlingPhases();
    while (bp.length < MAX_PLAYERS) bp.push("");
    return {
      slots,
      slotTypes: data.slotTypes,
      bowlingPhases: bp.slice(0, MAX_PLAYERS),
      savedAt: data.savedAt,
    };
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
    key: "balanced",
    label: "Balanced T20 XI",
    shortLabel: "Balanced",
    icon: <Layers size={14} />,
    description:
      "Shape-constrained XI with powerplay and death bowling diversity plus WAR",
  },
  {
    key: "bat_heavy",
    label: "Batting-heavy XI",
    shortLabel: "Bat-heavy",
    icon: <BarChart2 size={14} />,
    description: "Five bowlers and six bat-first picks (WAR-ordered)",
  },
  {
    key: "bowl_heavy",
    label: "Bowling-heavy XI",
    shortLabel: "Bowl-heavy",
    icon: <Shield size={14} />,
    description: "Six bowlers and five batters for low-scoring conditions",
  },
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

function TeamRadar({
  axes,
  size = 300,
  accent = "#d4d4dc",
}: {
  axes: RadarAxis[];
  size?: number;
  /** Stroke/fill colour (hex). Defaults to monochrome chrome. */
  accent?: string;
}) {
  const center = size / 2;
  const maxRadius = size / 2 - 40;
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
      labelX: center + (maxRadius + 28) * Math.cos(angle),
      labelY: center + (maxRadius + 28) * Math.sin(angle),
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
        fill={accent}
        fillOpacity={0.15}
        stroke={accent}
        strokeWidth={2}
      />

      {/* Data points */}
      {points.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={4}
          fill={accent}
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
            fontSize={12}
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
  slotType: SlotTypeKey;
  player: PlayerSummary | null;
  onSelect: (player: PlayerSummary) => void;
  onRemove: () => void;
  excludeIds: string[];
  onLabelClick?: () => void;
  bowlingPhaseTag?: string;
  onBowlingPhaseChange?: (value: string) => void;
  onDropOnSlot?: (fromIndex: number, toIndex: number) => void;
}

function PlayerSlot({
  index,
  slotLabel,
  slotType,
  player,
  onSelect,
  onRemove,
  excludeIds,
  onLabelClick,
  bowlingPhaseTag = "",
  onBowlingPhaseChange,
  onDropOnSlot,
}: PlayerSlotProps) {
  const SlotTypeIcon = SLOT_TYPE_META[slotType].Icon;
  const slotTypeAria = SLOT_TYPE_META[slotType].iconAriaLabel;

  if (player) {
    const isBowler = player.role === "bowl";
    const flag = countryFlag(player.country);
    const oop = battingSlotOutOfPosition(player, slotType);
    const archMeta = archetypeIconMeta(player.archetype, player.role);
    const ArchIcon = archMeta.Icon;
    const oopTip = outOfPositionTooltipText(player);

    const showPhase =
      (slotType === "bowler" || slotType === "allrounder") &&
      !!onBowlingPhaseChange;
    const ar = player.allrounder_class;

    return (
      <div
        className="flex items-center gap-3 p-3 rounded-lg bg-surface-elevated/50 hover:bg-surface-elevated/70 transition-colors group"
        draggable={!!onDropOnSlot}
        onDragStart={(e) => {
          e.dataTransfer.setData("text/plain", String(index));
          e.dataTransfer.effectAllowed = "move";
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
        }}
        onDrop={(e) => {
          e.preventDefault();
          const raw = e.dataTransfer.getData("text/plain");
          const from = parseInt(raw, 10);
          if (!Number.isNaN(from) && onDropOnSlot) onDropOnSlot(from, index);
        }}
      >
        {/* Slot number */}
        <span
          className="flex h-6 w-6 shrink-0 cursor-grab items-center justify-center rounded-full bg-white/[0.08] text-xs font-semibold text-primary active:cursor-grabbing"
          title="Drag to reorder"
        >
          {index + 1}
        </span>

        {/* Player info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            {flag && <span className="text-sm">{flag}</span>}
            <span className="text-sm font-medium text-text-primary truncate">
              {player.name}
            </span>
            <GradeBadge grade={player.grade_overall} size="xs" />
            {ar === "genuine" && (
              <span className="rounded bg-white/[0.08] px-1.5 py-0.5 text-[10px] font-medium text-primary">
                AR
              </span>
            )}
            {ar === "batting" && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 font-medium">
                Bat AR
              </span>
            )}
            {ar === "bowling" && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-800 dark:text-amber-200 font-medium">
                Bowl AR
              </span>
            )}
            {oop && (
              <MetricTooltip
                title="Unusual slot"
                content={oopTip}
                helpCursor={false}
                showInterpretation={false}
                className="shrink-0 rounded p-0.5 text-amber-600 hover:bg-amber-500/15 dark:text-amber-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary"
              >
                <AlertTriangle size={14} strokeWidth={2} aria-hidden />
              </MetricTooltip>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <span className="text-xs text-text-muted truncate max-w-[10rem]">
              {(player.recent_team || "").trim() || player.country || "—"}
            </span>
            <span className="text-xs text-text-muted">·</span>
            <span
              className="inline-flex items-center gap-1 text-xs text-text-muted"
              title={archMeta.ariaLabel}
            >
              <ArchIcon
                size={12}
                className="shrink-0 text-text-muted opacity-80"
                aria-hidden
              />
              <span className="sr-only">{archMeta.ariaLabel}. </span>
              <span>
                {player.archetype || (isBowler ? "Bowler" : "Batter")}
              </span>
            </span>
            <span className="text-xs text-text-muted">·</span>
            <span className="text-xs text-text-muted">
              {isBowler
                ? `${player.total_runs} wkts`
                : `${player.total_runs} runs`}
            </span>
            {player.phase_group && (
              <>
                <span className="text-xs text-text-muted">·</span>
                <span className="text-[10px] uppercase tracking-wide text-text-muted">
                  {player.phase_group.replace("_heavy", "").replace("_", " ")}
                </span>
              </>
            )}
          </div>
          {showPhase && (
            <div className="mt-1.5">
              <label className="sr-only" htmlFor={`bowl-phase-${index}`}>
                Bowling phase tag
              </label>
              <select
                id={`bowl-phase-${index}`}
                value={bowlingPhaseTag}
                onChange={(e) => onBowlingPhaseChange?.(e.target.value)}
                className="filter-select text-[10px] py-0.5 max-w-[9rem]"
              >
                <option value="">Phase (use data)</option>
                <option value="pp">Powerplay</option>
                <option value="middle">Middle</option>
                <option value="death">Death</option>
              </select>
            </div>
          )}
        </div>

        {/* Score bars (compact) */}
        <div className="hidden sm:flex items-center gap-3 shrink-0">
          <div className="text-center w-11">
            <span className="text-[10px] text-text-muted uppercase block">
              {player.score_1_label?.slice(0, 3) ?? "S1"}
            </span>
            <span
              className="text-xs font-score tabular-nums font-semibold"
              style={{ color: scoreToColour(player.score_1) }}
            >
              {player.score_1 != null ? Math.round(player.score_1) : "—"}
            </span>
            <ScoreBar
              value={player.score_1}
              variant="minimal"
              size="xs"
              decorative
              className="mt-0.5 w-full"
            />
          </div>
          <div className="text-center w-11">
            <span className="text-[10px] text-text-muted uppercase block">
              {player.score_2_label?.slice(0, 3) ?? "S2"}
            </span>
            <span
              className="text-xs font-score tabular-nums font-semibold"
              style={{ color: scoreToColour(player.score_2) }}
            >
              {player.score_2 != null ? Math.round(player.score_2) : "—"}
            </span>
            <ScoreBar
              value={player.score_2}
              variant="minimal"
              size="xs"
              decorative
              className="mt-0.5 w-full"
            />
          </div>
          <div className="text-center w-11">
            <span className="text-[10px] text-text-muted uppercase block">
              {player.score_3_label?.slice(0, 3) ?? "S3"}
            </span>
            <span
              className="text-xs font-score tabular-nums font-semibold"
              style={{ color: scoreToColour(player.score_3) }}
            >
              {player.score_3 != null ? Math.round(player.score_3) : "—"}
            </span>
            <ScoreBar
              value={player.score_3}
              variant="minimal"
              size="xs"
              decorative
              className="mt-0.5 w-full"
            />
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
    <div className="flex items-center gap-3 p-3 rounded-lg border border-border/35 bg-surface-elevated/25 dark:bg-surface-elevated/18 hover:border-primary/25 transition-colors">
      {/* Slot number */}
      <span className="w-6 h-6 flex items-center justify-center rounded-full bg-surface-elevated text-text-muted text-xs font-semibold shrink-0">
        {index + 1}
      </span>

      {/* Slot label — click to cycle role */}
      <button
        onClick={onLabelClick}
        className="inline-flex items-center gap-1 text-xs text-text-muted hover:text-primary transition-colors cursor-pointer select-none shrink-0 min-w-[5.5rem] text-left"
        title="Click to change slot role"
        aria-label={`${slotTypeAria}. Click to cycle role.`}
      >
        <SlotTypeIcon size={12} className="shrink-0 opacity-70" aria-hidden />
        <span>{slotLabel}</span>
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

const COMPOSITION_SUMMARY_BOOLS: { key: string; label: string }[] = [
  { key: "sixth_bowler_ok", label: "Six viable bowling options" },
  { key: "death_covered", label: "Death-phase bowling" },
  { key: "pp_bowling_covered", label: "Powerplay bowling" },
  { key: "pp_batting_covered", label: "Powerplay batting intent" },
  { key: "finisher_depth_ok", label: "Finisher / late-order depth" },
];

function compositionBoolOk(v: boolean | string | undefined): boolean {
  return v === true || v === "true";
}

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
          Team Analysis
        </h2>
        <span className="text-xs text-text-muted">
          {analysis.player_count} player{analysis.player_count !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Radar chart */}
      <TeamRadar axes={radarAxes} size={368} />

      {/* Composition checklist + slot/role notes */}
      {(analysis.composition_summary &&
        Object.keys(analysis.composition_summary).length > 0) ||
      (analysis.composition_critical && analysis.composition_critical.length > 0) ||
      (analysis.composition_advisory && analysis.composition_advisory.length > 0) ||
      (analysis.role_fit_warnings && analysis.role_fit_warnings.length > 0) ? (
        <div className="space-y-3 rounded-xl border border-border/40 bg-surface-elevated/25 p-3">
          <h3 className="text-xs text-text-muted uppercase tracking-wider">
            Composition
          </h3>
          {analysis.composition_summary &&
            Object.keys(analysis.composition_summary).length > 0 && (
              <div className="space-y-2">
                {typeof analysis.composition_summary.bowling_options_count ===
                  "string" && (
                  <p className="text-xs text-text-secondary">
                    Bowling pool:{" "}
                    <span className="font-medium text-text-primary tabular-nums">
                      {analysis.composition_summary.bowling_options_count}
                    </span>{" "}
                    options counted for phase checks
                  </p>
                )}
                <ul className="space-y-1">
                  {COMPOSITION_SUMMARY_BOOLS.map(({ key, label }) => {
                    const raw = analysis.composition_summary?.[key];
                    const ok = compositionBoolOk(raw);
                    return (
                      <li
                        key={key}
                        className="flex items-center gap-2 text-xs text-text-secondary"
                      >
                        {ok ? (
                          <Check
                            size={14}
                            className="shrink-0 text-emerald-600 dark:text-emerald-400"
                            aria-hidden
                          />
                        ) : (
                          <X
                            size={14}
                            className="shrink-0 text-rose-500 dark:text-rose-400"
                            aria-hidden
                          />
                        )}
                        <span>{label}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          {analysis.composition_critical &&
            analysis.composition_critical.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-rose-600 dark:text-rose-400">
                  Must fix
                </span>
                <ul className="space-y-1">
                  {analysis.composition_critical.map((c, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 text-sm text-rose-800 dark:text-rose-200/95 bg-rose-500/10 rounded-lg px-2.5 py-1.5 border border-rose-500/20"
                    >
                      <AlertTriangle
                        size={13}
                        className="shrink-0 mt-0.5 text-rose-600 dark:text-rose-400"
                      />
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          {analysis.composition_advisory &&
            analysis.composition_advisory.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                  Advisory
                </span>
                <ul className="space-y-1">
                  {analysis.composition_advisory.map((c, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50/90 px-2.5 py-1.5 text-xs text-text-secondary dark:border-white/[0.1] dark:bg-surface dark:text-text-secondary"
                    >
                      <Info
                        size={12}
                        className="mt-0.5 shrink-0 text-text-muted"
                      />
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          {analysis.role_fit_warnings &&
            analysis.role_fit_warnings.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                  Slot fit
                </span>
                <ul className="space-y-1">
                  {analysis.role_fit_warnings.map((c, i) => (
                    <li
                      key={i}
                      className="text-xs text-text-secondary flex items-start gap-2"
                    >
                      <span className="text-text-muted shrink-0">·</span>
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
        </div>
      ) : null}

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
              {analysis.genuine_bowler_count ?? analysis.bowlers.length} listed
              {analysis.bowling_aggregate_count != null
                ? ` · ${analysis.bowling_aggregate_count} in averages`
                : ""}
              )
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
                      ? "#38BDF8"
                      : analysis.avg_clutch != null && analysis.avg_clutch < 0
                        ? "#F59E0B"
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
                className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-200/90 bg-amber-500/10 dark:bg-amber-500/10 rounded-lg px-3 py-2 border border-amber-500/20"
              >
                <AlertTriangle size={13} className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-300" />
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

// ── Multi-team compare (2–4 columns, spec-style metrics) ───────────

function teamBatProfileSum(a: TeamAnalysis): number | null {
  if (
    a.avg_acceleration == null &&
    a.avg_bat_power == null &&
    a.avg_bat_control == null
  )
    return null;
  return (
    (a.avg_acceleration ?? 0) +
    (a.avg_bat_power ?? 0) +
    (a.avg_bat_control ?? 0)
  );
}

function teamBowlProfileSum(a: TeamAnalysis): number | null {
  if (
    a.avg_accuracy == null &&
    a.avg_bowl_control == null &&
    a.avg_threat == null
  )
    return null;
  return (
    (a.avg_accuracy ?? 0) +
    (a.avg_bowl_control ?? 0) +
    (a.avg_threat ?? 0)
  );
}

function teamTotalWarSum(a: TeamAnalysis): number | null {
  const t =
    (a.total_war_batting ?? 0) + (a.total_war_bowling ?? 0);
  return t > 0 ? t : null;
}

/** Indices among `visible` teams that strictly win the metric (ties → no highlight). */
function winnerIndices(
  analyses: (TeamAnalysis | undefined)[],
  visible: number,
  pick: (a: TeamAnalysis) => number | null,
  higherIsBetter: boolean,
): Set<number> {
  const entries: { i: number; v: number }[] = [];
  for (let i = 0; i < visible; i++) {
    const a = analyses[i];
    if (!a) continue;
    const v = pick(a);
    if (v == null || Number.isNaN(v)) continue;
    entries.push({ i, v });
  }
  if (entries.length < 2) return new Set();
  const extreme = higherIsBetter
    ? Math.max(...entries.map((e) => e.v))
    : Math.min(...entries.map((e) => e.v));
  const atExtreme = entries.filter((e) => e.v === extreme);
  if (atExtreme.length !== 1) return new Set();
  return new Set([atExtreme[0].i]);
}

function deltaToneClass(delta: number, higherIsBetter: boolean): string {
  if (delta === 0) return "text-text-muted";
  const good = higherIsBetter ? delta > 0 : delta < 0;
  const bad = higherIsBetter ? delta < 0 : delta > 0;
  if (good) return "text-emerald-600 dark:text-emerald-400";
  if (bad) return "text-rose-600 dark:text-rose-400";
  return "text-text-muted";
}

function formatSignedDelta(delta: number, decimals: number): string {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(decimals)}`;
}

interface CompareSlotCellProps {
  slotIndex: number;
  slotType: SlotTypeKey;
  player: PlayerSummary | null;
  accent: string;
  excludeIds: string[];
  onSelect: (p: PlayerSummary) => void;
  onRemove: () => void;
  onTypeCycle: () => void;
}

function CompareSlotCell({
  slotIndex,
  slotType,
  player,
  accent,
  excludeIds,
  onSelect,
  onRemove,
  onTypeCycle,
}: CompareSlotCellProps) {
  const typeOption =
    SLOT_TYPE_OPTIONS.find((t) => t.key === slotType) ?? SLOT_TYPE_OPTIONS[0];
  const TypeIcon = typeOption.Icon;

  if (player) {
    const isBowler = player.role === "bowl";
    const flag = countryFlag(player.country);
    const oop = battingSlotOutOfPosition(player, slotType);
    const archMeta = archetypeIconMeta(player.archetype, player.role);
    const ArchIcon = archMeta.Icon;
    const oopTip = outOfPositionTooltipText(player);

    return (
      <div
        className="rounded-xl border border-border/60 bg-surface-elevated/40 p-2.5 min-h-[6.25rem] flex flex-col gap-1 transition-shadow hover:shadow-sm"
        style={{ borderTopColor: accent, borderTopWidth: 3 }}
      >
        <div className="flex items-start justify-between gap-1">
          <span className="text-[10px] font-semibold text-text-muted tabular-nums">
            #{slotIndex + 1}
          </span>
          <button
            type="button"
            onClick={onRemove}
            className="rounded p-0.5 text-text-muted hover:bg-danger/10 hover:text-danger"
            aria-label={`Remove ${player.name}`}
          >
            <X size={12} />
          </button>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1 flex-wrap">
            <PlayerAvatar name={player.name} playerId={player.id} size="sm" />
            {flag && <span className="text-xs">{flag}</span>}
            <Link
              to={`/player/${player.id}`}
              className="text-xs font-medium text-text-primary hover:text-primary truncate min-w-0"
            >
              {player.name}
            </Link>
            <GradeBadge grade={player.grade_overall} size="xs" />
            {oop && (
              <MetricTooltip
                title="Unusual slot"
                content={oopTip}
                helpCursor={false}
                showInterpretation={false}
                className="shrink-0 rounded p-0.5 text-amber-600 hover:bg-amber-500/15 dark:text-amber-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary"
              >
                <AlertTriangle size={11} strokeWidth={2} aria-hidden />
              </MetricTooltip>
            )}
          </div>
          <p className="text-[10px] text-text-muted truncate mt-0.5 inline-flex items-center gap-1 max-w-full">
            <TypeIcon size={10} className="shrink-0 opacity-70" aria-hidden />
            <span className="sr-only">{typeOption.iconAriaLabel}. </span>
            <span className="truncate">
              {typeOption.label} ·{" "}
              <span className="inline-flex items-center gap-0.5">
                <ArchIcon size={10} className="shrink-0 opacity-70" aria-hidden />
                <span className="sr-only">{archMeta.ariaLabel}. </span>
                {player.archetype || (isBowler ? "Bowler" : "Batter")}
              </span>
            </span>
          </p>
          <div className="flex gap-1.5 mt-1.5 justify-between text-[10px] tabular-nums">
            <div className="flex flex-col items-center min-w-0 flex-1">
              <span style={{ color: scoreToColour(player.score_1) }}>
                {player.score_1 != null ? Math.round(player.score_1) : "—"}
              </span>
              <ScoreBar
                value={player.score_1}
                variant="minimal"
                size="xs"
                decorative
                className="mt-0.5 w-full max-w-[2.25rem]"
              />
            </div>
            <div className="flex flex-col items-center min-w-0 flex-1">
              <span style={{ color: scoreToColour(player.score_2) }}>
                {player.score_2 != null ? Math.round(player.score_2) : "—"}
              </span>
              <ScoreBar
                value={player.score_2}
                variant="minimal"
                size="xs"
                decorative
                className="mt-0.5 w-full max-w-[2.25rem]"
              />
            </div>
            <div className="flex flex-col items-center min-w-0 flex-1">
              <span style={{ color: scoreToColour(player.score_3) }}>
                {player.score_3 != null ? Math.round(player.score_3) : "—"}
              </span>
              <ScoreBar
                value={player.score_3}
                variant="minimal"
                size="xs"
                decorative
                className="mt-0.5 w-full max-w-[2.25rem]"
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl border border-border/40 bg-surface-elevated/22 dark:bg-surface-elevated/16 p-2 min-h-[5.5rem] flex flex-col gap-1"
      style={{ borderTopColor: accent, borderTopWidth: 2 }}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-semibold text-text-muted w-4">
          {slotIndex + 1}
        </span>
        <button
          type="button"
          onClick={onTypeCycle}
          className="inline-flex items-center gap-1 text-[9px] text-text-muted hover:text-primary truncate text-left min-w-0"
          aria-label={`${typeOption.iconAriaLabel}. Click to cycle role.`}
        >
          <TypeIcon size={10} className="shrink-0 opacity-70" aria-hidden />
          <span className="truncate">{typeOption.label}</span>
        </button>
      </div>
      <PlayerAutocomplete
        placeholder="Add…"
        onSelect={onSelect}
        excludeIds={excludeIds}
        size="sm"
      />
    </div>
  );
}

function MultiTeamComparisonPanel({
  analyses,
  visibleTeams,
  anyLoading,
  hasAnyPlayers,
}: {
  analyses: (TeamAnalysis | undefined)[];
  visibleTeams: number;
  anyLoading: boolean;
  hasAnyPlayers: boolean;
}) {
  if (!hasAnyPlayers) return null;

  if (anyLoading) {
    return (
      <div className="card p-4 animate-pulse text-sm text-text-muted">
        Computing team metrics…
      </div>
    );
  }

  const gridCols = `minmax(5.5rem,7rem) repeat(${visibleTeams}, minmax(0, 1fr))`;

  const wBat = winnerIndices(
    analyses,
    visibleTeams,
    (a) => teamBatProfileSum(a),
    true,
  );
  const wBowl = winnerIndices(
    analyses,
    visibleTeams,
    (a) => teamBowlProfileSum(a),
    true,
  );
  const wWar = winnerIndices(
    analyses,
    visibleTeams,
    (a) => teamTotalWarSum(a),
    true,
  );
  const wClutch = winnerIndices(
    analyses,
    visibleTeams,
    (a) => a.avg_clutch,
    true,
  );

  const specMetricRow = (
    label: string,
    winners: Set<number>,
    rawValues: (number | null)[],
    formatValue: (v: number) => string,
    higherIsBetter: boolean,
    deltaDecimals: number,
  ) => {
    const baseline = rawValues[0];
    return (
      <div
        className="grid gap-x-3 gap-y-1 items-stretch py-2 border-b border-border/30 last:border-b-0 text-sm"
        style={{ gridTemplateColumns: gridCols }}
      >
        <div className="text-xs text-text-muted pr-1 self-center">{label}</div>
        {Array.from({ length: visibleTeams }, (_, i) => {
          const raw = rawValues[i];
          if (raw == null || Number.isNaN(raw)) {
            return (
              <div
                key={i}
                className="text-right text-text-secondary self-center font-score tabular-nums"
              >
                —
              </div>
            );
          }
          const delta =
            i > 0 && baseline != null && !Number.isNaN(baseline)
              ? raw - baseline
              : null;
          const win = winners.has(i);
          return (
            <div
              key={i}
              className={`text-right font-score tabular-nums flex flex-col items-end justify-center gap-0.5 rounded-md py-0.5 pr-0.5 ${
                win ? "font-semibold text-text-primary" : "text-text-secondary"
              }`}
              style={
                win
                  ? {
                      borderLeft: `3px solid ${chartColour(i)}`,
                      paddingLeft: "0.35rem",
                      backgroundColor: chartColourAlpha(i, 0.14),
                    }
                  : undefined
              }
            >
              <span>{formatValue(raw)}</span>
              {delta != null && (
                <span
                  className={`text-[10px] font-medium ${deltaToneClass(delta, higherIsBetter)}`}
                >
                  vs T1 {formatSignedDelta(delta, deltaDecimals)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="card p-4 md:p-6 space-y-6 mt-4">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <h3 className="text-h4 text-text-primary flex items-center gap-2">
          <Swords size={18} className="text-primary" />
          Compare teams
        </h3>
        <p className="text-xs text-text-muted max-w-md">
          Same batting-order row across columns. Winners use each team&apos;s
          colour; other columns show delta vs Team 1 (green / red when higher is
          better). Highlights apply when one team strictly wins (no ties).
        </p>
      </div>

      <div>
        <h4 className="text-xs text-text-muted uppercase tracking-wider mb-2">
          Summary
        </h4>
        <div className="rounded-xl border border-border/40 overflow-hidden bg-surface-elevated/20">
          {specMetricRow(
            "Bat profile Σ",
            wBat,
            analyses
              .slice(0, visibleTeams)
              .map((a) => (a ? teamBatProfileSum(a) : null)),
            (v) => v.toFixed(1),
            true,
            1,
          )}
          {specMetricRow(
            "Bowl profile Σ",
            wBowl,
            analyses
              .slice(0, visibleTeams)
              .map((a) => (a ? teamBowlProfileSum(a) : null)),
            (v) => v.toFixed(1),
            true,
            1,
          )}
          {specMetricRow(
            "Total WAR",
            wWar,
            analyses
              .slice(0, visibleTeams)
              .map((a) => (a ? teamTotalWarSum(a) : null)),
            (v) => v.toFixed(1),
            true,
            1,
          )}
          {specMetricRow(
            "Bat WAR",
            winnerIndices(
              analyses,
              visibleTeams,
              (x) => x.total_war_batting,
              true,
            ),
            analyses
              .slice(0, visibleTeams)
              .map((a) => a?.total_war_batting ?? null),
            (v) => v.toFixed(1),
            true,
            1,
          )}
          {specMetricRow(
            "Bowl WAR",
            winnerIndices(
              analyses,
              visibleTeams,
              (x) => x.total_war_bowling,
              true,
            ),
            analyses
              .slice(0, visibleTeams)
              .map((a) => a?.total_war_bowling ?? null),
            (v) => v.toFixed(1),
            true,
            1,
          )}
          {specMetricRow(
            "Avg clutch",
            wClutch,
            analyses.slice(0, visibleTeams).map((a) => a?.avg_clutch ?? null),
            (v) => v.toFixed(1),
            true,
            1,
          )}
          {specMetricRow(
            "Batters",
            winnerIndices(
              analyses,
              visibleTeams,
              (x) => x.genuine_batter_count ?? x.batters.length,
              true,
            ),
            analyses.slice(0, visibleTeams).map((a) =>
              a ? (a.genuine_batter_count ?? a.batters.length) : null,
            ),
            (v) => String(Math.round(v)),
            true,
            0,
          )}
          {specMetricRow(
            "Bowlers",
            winnerIndices(
              analyses,
              visibleTeams,
              (x) => x.genuine_bowler_count ?? x.bowlers.length,
              true,
            ),
            analyses.slice(0, visibleTeams).map((a) =>
              a ? (a.genuine_bowler_count ?? a.bowlers.length) : null,
            ),
            (v) => String(Math.round(v)),
            true,
            0,
          )}
        </div>
      </div>

      <div>
        <h4 className="text-xs text-text-muted uppercase tracking-wider mb-3">
          Shape (per team)
        </h4>
        <div className="flex flex-wrap justify-center gap-6">
          {analyses.slice(0, visibleTeams).map((a, i) =>
            a ? (
              <div key={i} className="text-center space-y-2">
                <div
                  className="text-xs font-medium"
                  style={{ color: chartColour(i) }}
                >
                  Team {i + 1}
                </div>
                <TeamRadar
                  size={220}
                  accent={chartColour(i)}
                  axes={[
                    {
                      label: "Bat ACC",
                      shortLabel: "Bat ACC",
                      value: a.avg_acceleration,
                    },
                    {
                      label: "Bat POW",
                      shortLabel: "Bat POW",
                      value: a.avg_bat_power,
                    },
                    {
                      label: "Bat CTL",
                      shortLabel: "Bat CTL",
                      value: a.avg_bat_control,
                    },
                    {
                      label: "Bowl ACR",
                      shortLabel: "Bwl ACR",
                      value: a.avg_accuracy,
                    },
                    {
                      label: "Bowl CTL",
                      shortLabel: "Bwl CTL",
                      value: a.avg_bowl_control,
                    },
                    {
                      label: "Bowl THR",
                      shortLabel: "Bwl THR",
                      value: a.avg_threat,
                    },
                  ]}
                />
              </div>
            ) : null,
          )}
        </div>
      </div>

      <div>
        <h4 className="text-xs text-text-muted uppercase tracking-wider mb-2">
          Composition
        </h4>
        <div
          className="grid gap-3"
          style={{
            gridTemplateColumns: `repeat(${Math.min(visibleTeams, 4)}, minmax(0, 1fr))`,
          }}
        >
          {analyses.slice(0, visibleTeams).map((a, i) => (
            <div
              key={i}
              className="rounded-lg border border-border/40 bg-surface-elevated/30 p-3 text-xs space-y-2"
            >
              <div
                className="font-medium flex items-center gap-2"
                style={{ color: chartColour(i) }}
              >
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ backgroundColor: chartColour(i) }}
                />
                Team {i + 1}
              </div>
              {!a ? (
                <span className="text-text-muted">Add players…</span>
              ) : (
                <>
                  {a.composition_critical &&
                  a.composition_critical.length > 0 ? (
                    <ul className="space-y-1">
                      {a.composition_critical.map((c, ci) => (
                        <li
                          key={ci}
                          className="text-rose-700 dark:text-rose-300 flex items-start gap-1"
                        >
                          <AlertTriangle
                            size={11}
                            className="shrink-0 mt-0.5 opacity-90"
                          />
                          <span>{c}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="text-emerald-600/90 dark:text-emerald-400/90">
                      No critical gaps
                    </span>
                  )}
                  {a.composition_advisory &&
                    a.composition_advisory.length > 0 && (
                      <ul className="space-y-1 pt-1 border-t border-border/30">
                        {a.composition_advisory.map((c, ai) => (
                          <li
                            key={ai}
                            className="flex items-start gap-1 text-text-secondary"
                          >
                            <Info
                              size={10}
                              className="shrink-0 mt-0.5 opacity-90"
                            />
                            <span>{c}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        <h4 className="text-xs text-text-muted uppercase tracking-wider mb-2">
          Weaknesses
        </h4>
        <div
          className="grid gap-3"
          style={{
            gridTemplateColumns: `repeat(${Math.min(visibleTeams, 4)}, minmax(0, 1fr))`,
          }}
        >
          {analyses.slice(0, visibleTeams).map((a, i) => (
            <div
              key={i}
              className="rounded-lg border border-border/40 bg-surface-elevated/30 p-3 text-xs"
            >
              <div
                className="font-medium mb-2 flex items-center gap-2"
                style={{ color: chartColour(i) }}
              >
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ backgroundColor: chartColour(i) }}
                />
                Team {i + 1}
              </div>
              {!a ? (
                <span className="text-text-muted">Add players…</span>
              ) : a.weaknesses.length === 0 ? (
                <span className="text-emerald-500/90">None flagged</span>
              ) : (
                <ul className="space-y-1.5">
                  {a.weaknesses.map((w, wi) => (
                    <li
                      key={wi}
                      className="text-warning flex items-start gap-1.5"
                    >
                      <AlertTriangle
                        size={11}
                        className="shrink-0 mt-0.5 opacity-80"
                      />
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>
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

  const [bowlingPhases, setBowlingPhases] = useState<string[]>(() => {
    const saved = loadTeamFromStorage();
    if (saved?.bowlingPhases && saved.bowlingPhases.length === MAX_PLAYERS)
      return saved.bowlingPhases;
    return emptyBowlingPhases();
  });

  const [copied, setCopied] = useState(false);
  const [autoFillStrategy, setAutoFillStrategy] = useState<string | null>(null);
  const [autoFillCountry, setAutoFillCountry] = useState<string | null>(null);
  const [showAutoFill, setShowAutoFill] = useState(false);

  // ── State: Compare mode (2–4 teams side-by-side) ───────────
  const [isCompareMode, setIsCompareMode] = useState(false);
  const [compareTeamCount, setCompareTeamCount] = useState<2 | 3 | 4>(2);
  const [compareTeams, setCompareTeams] = useState<TeamDraft[]>(() =>
    Array.from({ length: MAX_COMPARE_TEAMS }, () => emptyCompareTeam()),
  );

  // Countries for country auto-fill
  const { data: countries } = useCountries();

  // ── Persist primary XI (team 1) ─────────────────────────────
  useEffect(() => {
    if (isCompareMode) {
      saveTeamToStorage(
        compareTeams[0].slots,
        compareTeams[0].slotTypes,
        compareTeams[0].bowlingPhases,
      );
    } else {
      saveTeamToStorage(slots, slotTypes, bowlingPhases);
    }
  }, [isCompareMode, slots, slotTypes, bowlingPhases, compareTeams]);

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

    const bpParam = searchParams.get("bp");
    if (bpParam) {
      const bp = [...bpParam].map((c) => decodeBowlingPhaseCode(c));
      while (bp.length < MAX_PLAYERS) bp.push("");
      setBowlingPhases(bp.slice(0, MAX_PLAYERS));
    } else {
      setBowlingPhases(emptyBowlingPhases());
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
            rating_current: (profile as any).rating_current ?? null,
            rating_overall: (profile as any).rating_overall ?? null,
            modal_position: isBat
              ? ((profile as any).modal_position ?? null)
              : null,
            recent_team: (profile as any).recent_team ?? null,
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

  const selectedBowlingPhases = useMemo(
    () =>
      slots.reduce<string[]>((acc, s, i) => {
        if (s !== null) acc.push(bowlingPhases[i] ?? "");
        return acc;
      }, []),
    [slots, bowlingPhases],
  );

  const playerCount = selectedIds.length;

  const allCompareSelectedIds = useMemo(() => {
    const s = new Set<string>();
    compareTeams.forEach((t) => {
      t.slots.forEach((p) => {
        if (p) s.add(p.id);
      });
    });
    return Array.from(s);
  }, [compareTeams]);

  const excludeIds = useMemo(
    () => (isCompareMode ? allCompareSelectedIds : selectedIds),
    [isCompareMode, allCompareSelectedIds, selectedIds],
  );

  const compareTeamInputs = useMemo(() => {
    if (!isCompareMode) {
      return Array.from({ length: MAX_COMPARE_TEAMS }, () => ({
        ids: [] as string[],
        slotTypes: [] as string[],
        bowlingPhases: [] as string[],
      }));
    }
    return compareTeams.map((t) => {
      const ids = t.slots
        .filter((s): s is PlayerSummary => s !== null)
        .map((s) => s.id);
      const st = t.slots.reduce<string[]>((acc, s, i) => {
        if (s !== null) acc.push(t.slotTypes[i]);
        return acc;
      }, []);
      const bp = t.slots.reduce<string[]>((acc, s, i) => {
        if (s !== null) acc.push(t.bowlingPhases[i] ?? "");
        return acc;
      }, []);
      return { ids, slotTypes: st, bowlingPhases: bp };
    });
  }, [isCompareMode, compareTeams]);

  const compareTeamQueries = useTeamAnalysesParallel(compareTeamInputs);

  const compareAnalyses = compareTeamQueries.map((q) => q.data);
  const compareQueriesLoading =
    isCompareMode &&
    compareTeamQueries.some(
      (q, i) =>
        i < compareTeamCount &&
        compareTeamInputs[i].ids.length > 0 &&
        q.isLoading,
    );

  const team0SelectedIds = useMemo(
    () =>
      compareTeams[0].slots
        .filter((s): s is PlayerSummary => s !== null)
        .map((s) => s.id),
    [compareTeams],
  );

  const team0SlotTypesAligned = useMemo(
    () =>
      compareTeams[0].slots.reduce<string[]>((acc, s, i) => {
        if (s !== null) acc.push(compareTeams[0].slotTypes[i]);
        return acc;
      }, []),
    [compareTeams],
  );

  const team0BowlingPhasesAligned = useMemo(
    () =>
      compareTeams[0].slots.reduce<string[]>((acc, s, i) => {
        if (s !== null) acc.push(compareTeams[0].bowlingPhases[i] ?? "");
        return acc;
      }, []),
    [compareTeams],
  );

  // ── Team analysis query (sidebar: team 1 in compare mode) ───
  const analysisIds = isCompareMode ? team0SelectedIds : selectedIds;
  const analysisSlotTypes = isCompareMode
    ? team0SlotTypesAligned
    : selectedSlotTypes;
  const analysisBowlingPhases = isCompareMode
    ? team0BowlingPhasesAligned
    : selectedBowlingPhases;

  const { data: analysis, isLoading: analysisLoading } = useTeamAnalysis(
    analysisIds,
    analysisSlotTypes,
    analysisBowlingPhases,
  );

  // ── Auto-fill query (only when triggered) ──────────────────
  const [autoFillEnabled, setAutoFillEnabled] = useState(false);

  const { data: autoFillData, isLoading: autoFillLoading } = useTeamAutoFill({
    strategy: autoFillStrategy ?? "balanced",
    country: autoFillCountry,
    exclude: [],
    enabled: autoFillEnabled && !!autoFillStrategy,
  });

  // Apply auto-fill results when they arrive
  useEffect(() => {
    if (!autoFillData || !autoFillEnabled) return;

    const pool: PlayerSummary[] = [
      ...autoFillData.batters,
      ...autoFillData.bowlers,
    ];
    const byId = new Map<string, PlayerSummary>();
    for (const p of pool) {
      if (!byId.has(p.id)) byId.set(p.id, p);
    }
    const order =
      autoFillData.player_ids_ordered && autoFillData.player_ids_ordered.length > 0
        ? autoFillData.player_ids_ordered
        : [...byId.keys()];
    const ordered: PlayerSummary[] = [];
    for (const id of order) {
      const p = byId.get(id);
      if (p) ordered.push(p);
    }

    const newSlots: (PlayerSummary | null)[] = Array(MAX_PLAYERS).fill(null);
    for (let i = 0; i < Math.min(ordered.length, MAX_PLAYERS); i++) {
      newSlots[i] = ordered[i];
    }
    const newSlotTypes = [...DEFAULT_SLOT_TYPES];
    const newBp = emptyBowlingPhases();

    if (isCompareMode) {
      setCompareTeams((prev) => {
        const next = [...prev];
        next[0] = {
          ...next[0],
          slots: newSlots,
          slotTypes: newSlotTypes,
          bowlingPhases: newBp,
        };
        return next;
      });
    } else {
      setSlots(newSlots);
      setSlotTypes(newSlotTypes);
      setBowlingPhases(newBp);
    }
    setAutoFillEnabled(false);
  }, [autoFillData, autoFillEnabled, isCompareMode]);

  // ── Handlers ───────────────────────────────────────────────

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

  const handleEnterCompareMode = useCallback(() => {
    setCompareTeams(() => {
      const next = Array.from({ length: MAX_COMPARE_TEAMS }, () =>
        emptyCompareTeam(),
      );
      next[0] = {
        slots: [...slots],
        slotTypes: [...slotTypes],
        bowlingPhases: [...bowlingPhases],
      };
      return next;
    });
    setCompareTeamCount(2);
    setIsCompareMode(true);
  }, [slots, slotTypes, bowlingPhases]);

  const handleExitCompareMode = useCallback(() => {
    setSlots(compareTeams[0].slots);
    setSlotTypes(compareTeams[0].slotTypes);
    setBowlingPhases([...compareTeams[0].bowlingPhases]);
    setIsCompareMode(false);
  }, [compareTeams]);

  const handleAddComparePlayer = useCallback(
    (teamIdx: number, slotIdx: number, player: PlayerSummary) => {
      setCompareTeams((prev) => {
        const next = prev.map((t) => cloneTeamDraft(t));
        next[teamIdx].slots[slotIdx] = player;
        const isBowlingArchetype =
          player.role === "bowl" ||
          BOWLING_ARCHETYPE_LABELS.has(player.archetype ?? "");
        if (isBowlingArchetype) {
          next[teamIdx].slotTypes[slotIdx] = "bowler";
        } else if (
          player.role === "bat" &&
          next[teamIdx].slotTypes[slotIdx] === "bowler"
        ) {
          if (slotIdx <= 1) next[teamIdx].slotTypes[slotIdx] = "opener";
          else if (slotIdx <= 3) next[teamIdx].slotTypes[slotIdx] = "top_order";
          else if (slotIdx <= 6)
            next[teamIdx].slotTypes[slotIdx] = "middle_order";
          else next[teamIdx].slotTypes[slotIdx] = "finisher_wk";
        }
        return next;
      });
    },
    [BOWLING_ARCHETYPE_LABELS],
  );

  const handleRemoveComparePlayer = useCallback(
    (teamIdx: number, slotIdx: number) => {
      setCompareTeams((prev) => {
        const next = prev.map((t) => cloneTeamDraft(t));
        next[teamIdx].slots[slotIdx] = null;
        return next;
      });
    },
    [],
  );

  const handleClearCompareTeam = useCallback((teamIdx: number) => {
    setCompareTeams((prev) => {
      const next = [...prev];
      next[teamIdx] = emptyCompareTeam();
      return next;
    });
  }, []);

  const handleDuplicateTeam1ToTeam2 = useCallback(() => {
    setCompareTeams((prev) => {
      const next = prev.map((t) => cloneTeamDraft(t));
      next[1] = cloneTeamDraft(prev[0]);
      return next;
    });
  }, []);

  const handleCompareSlotTypeCycle = useCallback(
    (teamIdx: number, slotIdx: number) => {
      setCompareTeams((prev) => {
        const next = prev.map((t) => cloneTeamDraft(t));
        const curIdx = SLOT_TYPE_OPTIONS.findIndex(
          (opt) => opt.key === next[teamIdx].slotTypes[slotIdx],
        );
        next[teamIdx].slotTypes[slotIdx] =
          SLOT_TYPE_OPTIONS[(curIdx + 1) % SLOT_TYPE_OPTIONS.length].key;
        return next;
      });
    },
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
    setBowlingPhases(emptyBowlingPhases());
    clearTeamStorage();
  }, []);

  const handleSwapSlots = useCallback((from: number, to: number) => {
    if (from === to) return;
    setSlots((prev) => {
      const n = [...prev];
      [n[from], n[to]] = [n[to], n[from]];
      return n;
    });
    setSlotTypes((prev) => {
      const n = [...prev];
      [n[from], n[to]] = [n[to], n[from]];
      return n;
    });
    setBowlingPhases((prev) => {
      const n = [...prev];
      [n[from], n[to]] = [n[to], n[from]];
      return n;
    });
  }, []);

  const handleSuggestedOrder = useCallback(() => {
    const pairs = slots
      .map((s, i) => (s ? { s, i } : null))
      .filter((x): x is { s: PlayerSummary; i: number } => x != null);
    const batPart = pairs
      .filter((x) => x.s.role === "bat")
      .sort(
        (a, b) => (a.s.modal_position ?? 99) - (b.s.modal_position ?? 99),
      );
    const bowlPart = pairs
      .filter((x) => x.s.role === "bowl")
      .sort((a, b) => bowlerPhaseSortKey(a.s) - bowlerPhaseSortKey(b.s));
    const ordered = [...batPart, ...bowlPart].map((x) => x.s);
    const next: (PlayerSummary | null)[] = Array(MAX_PLAYERS).fill(null);
    for (let i = 0; i < ordered.length; i++) next[i] = ordered[i];
    setSlots(next);
    setSlotTypes([...DEFAULT_SLOT_TYPES]);
    setBowlingPhases(emptyBowlingPhases());
  }, [slots]);

  const handleAutoFill = useCallback(
    (strategy: string, country?: string | null) => {
      setAutoFillStrategy(strategy);
      setAutoFillCountry(country ?? null);
      setAutoFillEnabled(true);
    },
    [],
  );

  const handleShare = useCallback(() => {
    const shareSlots = isCompareMode ? compareTeams[0].slots : slots;
    const shareTypes = isCompareMode ? compareTeams[0].slotTypes : slotTypes;
    const ids = shareSlots
      .filter((s): s is PlayerSummary => s !== null)
      .map((s) => s.id);
    if (ids.length === 0) return;

    const url = new URL(window.location.href);
    const orderedIds = shareSlots.map((s) => s?.id ?? "").join(",");
    url.searchParams.set("ids", orderedIds);
    url.searchParams.set(
      "types",
      shareTypes.map((t) => TYPE_SHORT_CODES[t]).join(""),
    );
    const shareBp = isCompareMode
      ? compareTeams[0].bowlingPhases
      : bowlingPhases;
    if (shareBp.some((x) => x && x.length > 0)) {
      url.searchParams.set(
        "bp",
        shareBp.map((t) => encodeBowlingPhaseTag(t || "")).join(""),
      );
    } else {
      url.searchParams.delete("bp");
    }
    const shareUrl = url.toString();

    if (navigator.clipboard) {
      navigator.clipboard.writeText(shareUrl).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  }, [isCompareMode, compareTeams, slots, slotTypes, bowlingPhases]);

  const handleCompare = useCallback(() => {
    const src = isCompareMode ? compareTeams[0].slots : slots;
    const ids = src
      .filter((s): s is PlayerSummary => s !== null)
      .map((s) => s.id);
    if (ids.length < 2) return;
    navigate(`/compare?ids=${ids.slice(0, 4).join(",")}`);
  }, [isCompareMode, compareTeams, slots, navigate]);

  const sidebarPlayerCount = isCompareMode
    ? team0SelectedIds.length
    : playerCount;

  return (
    <div className="app-page page-stack">
      {/* ── Page header ───────────────────────────────────────── */}
      <div className="page-header">
        <h1 className="page-title flex items-center gap-2">
          <Users size={24} className="text-primary" />
          Team Builder
        </h1>
        <p className="page-subtitle max-w-2xl">
          Build a hypothetical T20I XI and see how your team stacks up. Add
          players to slots, view aggregate metrics, and detect team weaknesses.
        </p>
        <div className="mt-2">
          <button
            type="button"
            onClick={() =>
              isCompareMode ? handleExitCompareMode() : handleEnterCompareMode()
            }
            className={`inline-flex items-center gap-1.5 ${
              isCompareMode ? "btn-primary" : "btn-secondary"
            }`}
          >
            <Swords size={14} />
            {isCompareMode ? "Exit compare mode" : "Compare teams"}
          </button>
        </div>
      </div>

      {/* URL loading indicator */}
      {urlLoading && (
        <div className="flex animate-pulse items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] p-3 text-sm text-text-secondary">
          <span className="inline-block h-2 w-2 rounded-full bg-primary" />
          Loading team from shared URL…
        </div>
      )}

      {/* ── Main layout: slots + analysis ─────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div
          className={`space-y-4 ${isCompareMode ? "lg:col-span-5" : "lg:col-span-3"}`}
        >
          {isCompareMode ? (
            <>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h2 className="text-h3 text-text-primary">Compare XIs</h2>
                  <p className="text-sm text-text-muted mt-1 max-w-xl">
                    Each row is the same batting-order slot across teams — like
                    a product compare grid. Add up to four squads side by side.
                  </p>
                </div>
                <div className="flex flex-col items-stretch sm:items-end gap-2">
                  <span className="text-xs text-text-muted uppercase tracking-wider">
                    Columns
                  </span>
                  <div className="inline-flex rounded-xl border border-border/50 p-1 bg-surface-elevated/40">
                    {([2, 3, 4] as const).map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setCompareTeamCount(n)}
                        className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${
                          compareTeamCount === n
                            ? "bg-primary text-white dark:text-background shadow-sm"
                            : "text-text-secondary hover:text-text-primary"
                        }`}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="overflow-x-auto overflow-y-auto max-h-[min(70vh,calc(100dvh-11rem))] rounded-xl border border-border/50 bg-surface-elevated/15 -mx-1 px-2 py-2 pb-3">
                <div
                  className="grid gap-3 min-w-[min(100%,52rem)]"
                  style={{
                    gridTemplateColumns: `repeat(${compareTeamCount}, minmax(11rem, 1fr))`,
                  }}
                >
                  {Array.from({ length: compareTeamCount }, (_, ti) => {
                    const t = compareTeams[ti];
                    const cnt = t.slots.filter(Boolean).length;
                    return (
                      <div key={ti} className="space-y-2 min-w-0">
                        <div
                          className="sticky top-0 z-20 flex items-center justify-between gap-2 rounded-xl border border-border/60 bg-background/95 dark:bg-background/92 backdrop-blur-md px-3 py-2.5 shadow-sm"
                          style={{
                            boxShadow: `inset 0 3px 0 0 ${chartColour(ti)}`,
                          }}
                        >
                          <div className="min-w-0">
                            <div
                              className="text-sm font-semibold truncate"
                              style={{ color: chartColour(ti) }}
                            >
                              Team {ti + 1}
                            </div>
                            <div className="text-[11px] text-text-muted tabular-nums">
                              {cnt}/{MAX_PLAYERS} players
                            </div>
                          </div>
                          <div className="flex items-center gap-0.5 shrink-0">
                            {ti === 0 && compareTeamCount >= 2 ? (
                              <button
                                type="button"
                                onClick={handleDuplicateTeam1ToTeam2}
                                className="btn-ghost btn-sm text-xs p-1.5 text-text-muted hover:text-primary"
                                title="Duplicate squad to Team 2 (overwrites Team 2)"
                                aria-label="Duplicate Team 1 squad to Team 2"
                              >
                                <Copy size={14} />
                              </button>
                            ) : null}
                            {cnt > 0 ? (
                              <button
                                type="button"
                                onClick={() => handleClearCompareTeam(ti)}
                                className="btn-ghost btn-sm text-xs text-danger shrink-0 p-1.5"
                                title={`Clear team ${ti + 1}`}
                                aria-label={`Clear team ${ti + 1}`}
                              >
                                <Trash2 size={14} />
                              </button>
                            ) : null}
                          </div>
                        </div>
                        <div className="space-y-2">
                          {t.slots.map((player, si) => (
                            <CompareSlotCell
                              key={si}
                              slotIndex={si}
                              slotType={t.slotTypes[si]}
                              player={player}
                              accent={chartColour(ti)}
                              excludeIds={excludeIds}
                              onSelect={(p) => handleAddComparePlayer(ti, si, p)}
                              onRemove={() => handleRemoveComparePlayer(ti, si)}
                              onTypeCycle={() =>
                                handleCompareSlotTypeCycle(ti, si)
                              }
                            />
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <MultiTeamComparisonPanel
                analyses={compareAnalyses}
                visibleTeams={compareTeamCount}
                anyLoading={compareQueriesLoading}
                hasAnyPlayers={allCompareSelectedIds.length > 0}
              />

              <div className="flex flex-wrap items-center gap-2">
                {team0SelectedIds.length >= 2 && (
                  <button
                    type="button"
                    onClick={handleCompare}
                    className="btn-ghost btn-sm text-xs"
                    title="Open player compare for team 1"
                  >
                    Compare team 1 players →
                  </button>
                )}
              </div>

              <div className="border-t border-border/50 pt-8 mt-2">
                <AnalysisPanel
                  analysis={analysis}
                  isLoading={analysisLoading}
                  playerCount={sidebarPlayerCount}
                />
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <h2 className="text-h3 text-text-primary">
                  Your XI{" "}
                  <span className="text-text-muted font-normal text-sm">
                    ({playerCount}/{MAX_PLAYERS})
                  </span>
                </h2>
                <div className="flex items-center gap-2">
                  {playerCount >= 2 && (
                    <button
                      type="button"
                      onClick={handleCompare}
                      className="btn-ghost btn-sm text-xs"
                      title="Compare selected players"
                    >
                      Compare
                    </button>
                  )}
                  {playerCount > 0 && (
                    <>
                      <button
                        type="button"
                        onClick={handleSuggestedOrder}
                        className="btn-ghost btn-sm text-xs"
                        title="Batters by modal position, then bowlers by phase"
                      >
                        Suggested order
                      </button>
                      <button
                        type="button"
                        onClick={handleClearAll}
                        className="btn-ghost btn-sm text-xs text-danger hover:text-danger"
                        title="Clear all players"
                      >
                        <Trash2 size={12} />
                        Clear
                      </button>
                    </>
                  )}
                </div>
              </div>

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
                      slotType={slotTypes[i]}
                      player={player}
                      onSelect={(p) => handleAddPlayer(i, p)}
                      onRemove={() => handleRemovePlayer(i)}
                      excludeIds={excludeIds}
                      bowlingPhaseTag={bowlingPhases[i] ?? ""}
                      onBowlingPhaseChange={(v) =>
                        setBowlingPhases((prev) => {
                          const next = [...prev];
                          next[i] = v;
                          return next;
                        })
                      }
                      onDropOnSlot={handleSwapSlots}
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

              <div className="flex items-start gap-2 p-3 rounded-lg bg-surface-elevated/30 text-xs text-text-muted">
                <Info size={14} className="shrink-0 mt-0.5 text-text-muted" />
                <span>
                  Recommended: 5–6 batters, 4–5 bowlers, at least 1 all-rounder.
                  Slot labels are suggestions — add any player to any slot.
                </span>
              </div>
            </>
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
                    Finding the best XI…
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Share button ─────────────────────────────────── */}
          {(isCompareMode ? team0SelectedIds.length > 0 : playerCount > 0) && (
            <div className="flex items-center gap-3">
              <button
                type="button"
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
        {!isCompareMode && (
        <div className="lg:col-span-2 space-y-4">
          <div className="lg:sticky lg:top-20">
            <AnalysisPanel
              analysis={analysis}
              isLoading={analysisLoading}
              playerCount={sidebarPlayerCount}
            />

            {/* Player list summary — in batting order */}
            {analysis && sidebarPlayerCount > 0 && (
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
                    const SideSlotIcon = typeOption?.Icon;
                    const archSide = archetypeIconMeta(
                      player.archetype,
                      player.role,
                    );
                    const SideArchIcon = archSide.Icon;
                    return (
                      <div
                        key={player.id}
                        className="flex items-center justify-between text-xs py-0.5 gap-1"
                      >
                        <span className="text-text-muted w-5 shrink-0">
                          {i + 1}
                        </span>
                        <span className="text-text-primary truncate flex-1 ml-1 min-w-0">
                          {countryFlag(player.country)} {player.name}
                        </span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {SideSlotIcon ? (
                            <span
                              className="inline-flex items-center gap-0.5 text-[10px] text-text-muted"
                              title={typeOption?.iconAriaLabel}
                            >
                              <SideSlotIcon
                                size={11}
                                className="shrink-0 opacity-70"
                                aria-hidden
                              />
                              <span className="sr-only">
                                {typeOption?.iconAriaLabel}.{" "}
                              </span>
                              <span className="hidden sm:inline max-w-[5rem] truncate">
                                {typeOption?.label}
                              </span>
                            </span>
                          ) : null}
                          <span className="inline-flex items-center gap-0.5 text-text-muted max-w-[6rem] truncate">
                            <SideArchIcon
                              size={11}
                              className="shrink-0 opacity-70"
                              aria-hidden
                            />
                            <span className="sr-only">{archSide.ariaLabel}. </span>
                            <span className="truncate">{player.archetype}</span>
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
                        Batters ({analysis.batters.length})
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
                        Bowlers ({analysis.bowlers.length})
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
        )}
      </div>
    </div>
  );
}
