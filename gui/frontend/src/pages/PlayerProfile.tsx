/**
 * PlayerProfile — the richest page in the application.
 *
 * Route: /player/:id
 *
 * Surfaces everything known about a player (from gui.md § 6.3):
 *   - Identity header: name, recent team (latest match) + country, archetype, grade
 *   - Metric scores: 3 score bars with grades + radar chart
 *   - Advanced metrics: WAR, Clutch Index, Chase Master, Flat Track, etc.
 *   - Component breakdown: stacked bars showing sub-metric contributions
 *   - Phase splits: powerplay / middle / death performance table
 *   - Chase splits: setting vs chasing comparison
 *   - Form tracker: time-series chart of rolling metric scores
 *   - Top matchups: best-against and worst-against bowlers/batters
 *   - Similar players: cosine-similarity nearest neighbours
 *   - Recent innings/spells log (paginated)
 *   - Action buttons: compare, team builder, share
 *
 * Handles both batting and bowling profiles via auto-detection.
 * If a player appears in both, shows a toggle.
 *
 * Data fetching:
 *   - usePlayerProfile() — main profile data
 *   - usePlayerForm() — form time-series (lazy, loaded when section visible)
 *   - usePlayerInnings() / usePlayerSpells() — recent innings/spells
 */

import React, { useState, useMemo, useCallback, useRef } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Flame,
  TrendingUp,
  TrendingDown,
  Target,
  Shield,
  Zap,
  Users,
  GitCompare,
  ChevronRight,
  ExternalLink,
  Info,
  BarChart3,
  Activity,
  Swords,
  AlertTriangle,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceDot,
  Legend,
} from "recharts";

import GradeBadge from "@/components/GradeBadge";
import ScoreBar, { ScoreBarMini } from "@/components/ScoreBar";
import { PaginationSimple } from "@/components/Pagination";
import { PageError, NotFound } from "@/components/Layout";
import {
  usePlayerRoles,
  useBatterProfile,
  useBowlerProfile,
  usePlayerForm,
  usePlayerInnings,
  usePlayerSpells,
  usePlayerMatchImpact,
} from "@/api/queries";
import { scoreToColour, CHART_COLOURS, dominanceColour } from "@/lib/colours";
import {
  fmtScore,
  fmtInt,
  fmtIntRaw,
  fmtSR,
  fmtEcon,
  fmtAvg,
  fmtPct,
  fmtSigned,
  fmtWAR,
  fmtDate,
  primaryDisplayRating,
  fmtDateRange,
  fmtOvers,
  countryFlag,
  fmtPhase,
  fmtPressureScore,
  pressureScore,
  fmtMatchupEdge,
} from "@/lib/format";
import type {
  BatterProfile,
  BowlerProfile,
  MatchupSummary,
  SimilarPlayer,
  FormPoint,
  InningsDetail,
  SpellDetail,
  PlayerMatchImpactRow,
} from "@/api/types";
import { formatCombinedSummary } from "@/lib/scorecardMatchImpact";
import SocialShareTrigger from "@/components/SocialShareTrigger";
import { SOCIAL_EXPORT_ROOT_CLASS } from "@/lib/socialCapture";
import { subjectsFromPlayers } from "@/lib/socialGraphicComposite";

// ── Component ────────────────────────────────────────────────────

export default function PlayerProfile() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  // ── 1. Fetch lightweight roles info first ──────────────────
  const {
    data: roles,
    isLoading: rolesLoading,
    error: rolesError,
    refetch: rolesRefetch,
  } = usePlayerRoles(id);

  // ── 2. Active role toggle state ────────────────────────────
  // `null` means "not yet initialised — waiting for roles data".
  const [activeRole, setActiveRole] = useState<"bat" | "bowl" | null>(null);

  // Reset activeRole when the player id changes (e.g. navigating between players
  // without unmounting) so we don't briefly fetch the wrong profile.
  const prevIdRef = React.useRef<string | undefined>(id);
  React.useEffect(() => {
    if (id !== prevIdRef.current) {
      prevIdRef.current = id;
      setActiveRole(null);
      setShowForm(false);
      setLogPage(1);
    }
  }, [id]);

  // Once roles arrive, seed the default (only on first load or id change).
  const rolesDefaultRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (roles && rolesDefaultRef.current !== roles.player_id) {
      rolesDefaultRef.current = roles.player_id;
      setActiveRole(roles.default_role);
    }
  }, [roles]);

  // Derived convenience flags
  const showToggle = roles?.has_batting && roles?.has_bowling;
  const isBatView = activeRole === "bat";
  const isBowlView = activeRole === "bowl";

  // ── 3. Fetch the appropriate profile based on activeRole ───
  const {
    data: batProfile,
    isLoading: batLoading,
    error: batError,
    refetch: batRefetch,
  } = useBatterProfile(id, { enabled: isBatView && !!id });

  const {
    data: bowlProfile,
    isLoading: bowlLoading,
    error: bowlError,
    refetch: bowlRefetch,
  } = useBowlerProfile(id, { enabled: isBowlView && !!id });

  const profile = isBatView ? batProfile : bowlProfile;
  const profileLoading = isBatView ? batLoading : bowlLoading;
  const profileError = isBatView ? batError : bowlError;
  const profileRefetch = isBatView ? batRefetch : bowlRefetch;

  // ── 4. Form data ──────────────────────────────────────────
  const [showForm, setShowForm] = useState(false);
  const formRole = isBatView ? "bat" : "bowl";
  const { data: formData, isLoading: formLoading } = usePlayerForm(
    id,
    formRole,
    { enabled: showForm && !!id && activeRole !== null },
  );

  // ── 5. Innings/Spells log ─────────────────────────────────
  const [logPage, setLogPage] = useState(1);
  const [logSortBy] = useState("date");
  const [logOrder] = useState("desc");
  const LOG_PER_PAGE = 10;

  // Reset log page when toggling role
  React.useEffect(() => {
    setLogPage(1);
  }, [activeRole]);

  const { data: inningsData } = usePlayerInnings(
    id,
    {
      page: logPage,
      perPage: LOG_PER_PAGE,
      sortBy: logSortBy,
      order: logOrder,
    },
    { enabled: isBatView && !!id },
  );

  const { data: spellsData } = usePlayerSpells(
    id,
    {
      page: logPage,
      perPage: LOG_PER_PAGE,
      sortBy: logSortBy,
      order: logOrder,
    },
    { enabled: isBowlView && !!id },
  );

  const {
    data: matchImpactRows,
    isLoading: matchImpactLoading,
    isError: matchImpactError,
  } = usePlayerMatchImpact(id, { enabled: Boolean(id) });

  // ── Loading state ──────────────────────────────────────────
  if (rolesLoading || (activeRole !== null && profileLoading)) {
    return <ProfileSkeleton />;
  }

  // Still waiting for the default role to be set
  if (activeRole === null && !rolesError) {
    return <ProfileSkeleton />;
  }

  // ── Error state ────────────────────────────────────────────
  const error = rolesError || profileError;
  if (error) {
    const is404 = (error as any)?.status === 404 || (error as any)?.isNotFound;
    if (is404) {
      return (
        <div className="space-y-4">
          <BackLink />
          <NotFound />
        </div>
      );
    }
    return (
      <div className="space-y-4">
        <BackLink />
        <PageError
          title="Failed to load player"
          message="Could not fetch the player profile. The backend might be unavailable."
          onRetry={() => {
            if (rolesError) {
              rolesRefetch();
            } else {
              profileRefetch();
            }
          }}
        />
      </div>
    );
  }

  // ── No data state ──────────────────────────────────────────
  if (!profile) {
    return (
      <div className="app-page page-stack">
        <BackLink />
        <NotFound />
      </div>
    );
  }

  // ── Render profile ─────────────────────────────────────────
  return (
    <div className="app-page page-stack pb-8">
      <BackLink />

      {/* ── Batting / Bowling Toggle ──────────────────────────── */}
      {showToggle && roles && (
        <RoleToggle
          activeRole={activeRole!}
          onRoleChange={(r) => {
            setActiveRole(r);
            setShowForm(false);
          }}
          battingInnings={roles.batting_innings}
          bowlingInnings={roles.bowling_innings}
        />
      )}

      {isBatView ? (
        <BatterProfileView
          profile={profile as BatterProfile}
          formData={formData}
          formLoading={formLoading}
          showForm={showForm}
          onShowForm={() => setShowForm(true)}
          inningsData={inningsData}
          logPage={logPage}
          logPerPage={LOG_PER_PAGE}
          onLogPageChange={setLogPage}
          navigate={navigate}
          matchImpactRows={matchImpactRows}
          matchImpactLoading={matchImpactLoading}
          matchImpactError={matchImpactError}
        />
      ) : (
        <BowlerProfileView
          profile={profile as BowlerProfile}
          formData={formData}
          formLoading={formLoading}
          showForm={showForm}
          onShowForm={() => setShowForm(true)}
          spellsData={spellsData}
          logPage={logPage}
          logPerPage={LOG_PER_PAGE}
          onLogPageChange={setLogPage}
          navigate={navigate}
          matchImpactRows={matchImpactRows}
          matchImpactLoading={matchImpactLoading}
          matchImpactError={matchImpactError}
        />
      )}
    </div>
  );
}

// ── Back link ────────────────────────────────────────────────────

// ── Role Toggle (Batting / Bowling) ──────────────────────────────

interface RoleToggleProps {
  activeRole: "bat" | "bowl";
  onRoleChange: (role: "bat" | "bowl") => void;
  battingInnings: number;
  bowlingInnings: number;
}

function RoleToggle({
  activeRole,
  onRoleChange,
  battingInnings,
  bowlingInnings,
}: RoleToggleProps) {
  return (
    <div className="flex items-center gap-1 p-1 rounded-lg bg-surface-elevated/60 w-fit">
      <button
        onClick={() => onRoleChange("bat")}
        className={`
          px-4 py-2 rounded-md text-sm font-medium transition-all duration-200
          flex items-center gap-2
          ${
            activeRole === "bat"
              ? "bg-primary text-white dark:text-background shadow-sm"
              : "text-text-secondary hover:text-text-primary hover:bg-surface-elevated"
          }
        `}
      >
        <Swords size={14} />
        <span>Batting</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded-full ${
            activeRole === "bat"
              ? "bg-white/20 text-white"
              : "bg-surface text-text-muted"
          }`}
        >
          {battingInnings} inn
        </span>
      </button>
      <button
        onClick={() => onRoleChange("bowl")}
        className={`
          px-4 py-2 rounded-md text-sm font-medium transition-all duration-200
          flex items-center gap-2
          ${
            activeRole === "bowl"
              ? "bg-primary text-white dark:text-background shadow-sm"
              : "text-text-secondary hover:text-text-primary hover:bg-surface-elevated"
          }
        `}
      >
        <Target size={14} />
        <span>Bowling</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded-full ${
            activeRole === "bowl"
              ? "bg-white/20 text-white"
              : "bg-surface text-text-muted"
          }`}
        >
          {bowlingInnings} inn
        </span>
      </button>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      to="/search"
      className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-primary transition-colors"
    >
      <ArrowLeft size={14} />
      <span>Back to Search</span>
    </Link>
  );
}

function impactRowToCombined(r: PlayerMatchImpactRow) {
  return {
    playerId: r.match_id,
    name: "",
    batImpact: r.bat_impact,
    bowlImpact: r.bowl_impact,
    totalImpact: r.total_impact,
    batRuns: r.bat_runs ?? undefined,
    batBalls: r.bat_balls ?? undefined,
    bowlWkts: r.bowl_wickets ?? undefined,
    bowlRuns: r.bowl_runs_conceded ?? undefined,
    bowlBalls: r.bowl_balls ?? undefined,
  };
}

const MATCH_IMPACT_PREVIEW_COUNT = 5;

function PlayerMatchImpactSection({
  playerId,
  rows,
  isLoading,
  isError,
}: {
  playerId: string;
  rows: PlayerMatchImpactRow[] | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const [showAllMatchImpact, setShowAllMatchImpact] = useState(false);

  React.useEffect(() => {
    setShowAllMatchImpact(false);
  }, [playerId]);

  if (isLoading) {
    return (
      <section className="card p-6">
        <SectionTitle
          icon={<BarChart3 size={18} />}
          title="Match impact performances"
        />
        <p className="text-sm text-text-muted mt-4">Loading scorecard impact…</p>
      </section>
    );
  }

  if (isError) {
    return (
      <section className="card p-6">
        <SectionTitle
          icon={<BarChart3 size={18} />}
          title="Match impact performances"
        />
        <p className="text-sm text-text-muted mt-4">
          Could not load scorecard impact for this player.
        </p>
      </section>
    );
  }

  const list = rows ?? [];
  if (list.length === 0) {
    return (
      <section className="card p-6">
        <SectionTitle
          icon={<BarChart3 size={18} />}
          title="Match impact performances"
        />
        <p className="text-sm text-text-muted mt-4">
          No qualifying match impact in scorecards yet — the same minimum balls
          rules as the scorecard Match impact tab apply (batting 5+ balls and/or
          bowling 6+ balls in that match).
        </p>
      </section>
    );
  }

  const hasMoreThanPreview = list.length > MATCH_IMPACT_PREVIEW_COUNT;
  const visibleRows =
    showAllMatchImpact || !hasMoreThanPreview
      ? list
      : list.slice(0, MATCH_IMPACT_PREVIEW_COUNT);

  return (
    <section className="card p-6">
      <SectionTitle
        icon={<BarChart3 size={18} />}
        title="Match impact performances"
      />
      <p className="text-xs text-text-muted mt-2 mb-4">
        Top scorecard matches by combined impact (
        <span className="tabular-nums text-text-secondary">bat + bowl</span>,
        same rules as the Match impact tab).{" "}
        {hasMoreThanPreview && !showAllMatchImpact ? (
          <>
            Showing top{" "}
            <span className="tabular-nums text-text-secondary">
              {MATCH_IMPACT_PREVIEW_COUNT}
            </span>{" "}
            of{" "}
            <span className="tabular-nums text-text-secondary">{list.length}</span>{" "}
            matches.
          </>
        ) : (
          <>
            <span className="tabular-nums text-text-secondary">{list.length}</span>{" "}
            {list.length === 1 ? "match" : "matches"}.
          </>
        )}
      </p>
      <div className="overflow-x-auto">
        <table className="sortable-table text-sm w-full min-w-[640px]">
          <thead>
            <tr>
              <th className="text-left w-10">#</th>
              <th className="text-left">Date</th>
              <th className="text-left">Match</th>
              <th className="text-left">Performance</th>
              <th className="text-right">Total</th>
              <th className="text-right">Bat</th>
              <th className="text-right">Bowl</th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, i) => {
              const title =
                (row.event_name && String(row.event_name).trim()) ||
                (row.venue && String(row.venue).trim()) ||
                row.match_id;
              return (
                <tr key={`${row.match_id}-${i}`}>
                  <td className="text-text-muted tabular-nums">{i + 1}</td>
                  <td className="text-text-secondary whitespace-nowrap">
                    {fmtDate(row.date)}
                  </td>
                  <td>
                    <Link
                      to={`/scorecards/${encodeURIComponent(row.match_id)}`}
                      className="text-primary underline decoration-primary/35 underline-offset-2 hover:decoration-primary inline-flex items-center gap-1"
                    >
                      <span className="line-clamp-2">{title}</span>
                      <ChevronRight size={12} className="shrink-0 opacity-60" />
                    </Link>
                  </td>
                  <td className="text-text-secondary max-w-[14rem]">
                    {formatCombinedSummary(impactRowToCombined(row))}
                  </td>
                  <td className="text-right font-medium tabular-nums text-text-primary">
                    {row.total_impact.toFixed(2)}
                  </td>
                  <td className="text-right tabular-nums text-text-secondary">
                    {row.bat_impact > 0 ? row.bat_impact.toFixed(2) : "—"}
                  </td>
                  <td className="text-right tabular-nums text-text-secondary">
                    {row.bowl_impact > 0 ? row.bowl_impact.toFixed(2) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {hasMoreThanPreview && (
        <div className="mt-4 pt-3 border-t border-surface-elevated/50">
          <button
            type="button"
            onClick={() => setShowAllMatchImpact((v) => !v)}
            className="text-sm text-primary hover:text-primary-hover font-medium inline-flex items-center gap-1"
          >
            {showAllMatchImpact ? (
              <>
                Show top {MATCH_IMPACT_PREVIEW_COUNT} only
                <ChevronRight size={14} className="opacity-70" aria-hidden />
              </>
            ) : (
              <>
                Show all {list.length} matches
                <ChevronRight size={14} className="opacity-70" aria-hidden />
              </>
            )}
          </button>
        </div>
      )}
    </section>
  );
}

// ── Batter Profile View ──────────────────────────────────────────

interface BatterProfileViewProps {
  profile: BatterProfile;
  formData: any;
  formLoading: boolean;
  showForm: boolean;
  onShowForm: () => void;
  inningsData: any;
  logPage: number;
  logPerPage: number;
  onLogPageChange: (page: number) => void;
  navigate: (path: string) => void;
  matchImpactRows: PlayerMatchImpactRow[] | undefined;
  matchImpactLoading: boolean;
  matchImpactError: boolean;
}

function BatterProfileView({
  profile: p,
  formData,
  formLoading,
  showForm,
  onShowForm,
  inningsData,
  logPage,
  logPerPage,
  onLogPageChange,
  navigate,
  matchImpactRows,
  matchImpactLoading,
  matchImpactError,
}: BatterProfileViewProps) {
  const metricScoresExportRef = useRef<HTMLDivElement>(null);
  const formExportRef = useRef<HTMLDivElement>(null);
  const phaseExportRef = useRef<HTMLDivElement>(null);

  const flag = countryFlag(p.country);
  const teamPrimary =
    (p.recent_team || "").trim() || p.country || "";
  const showAlsoCountry =
    (p.recent_team || "").trim() &&
    p.country &&
    (p.recent_team || "").trim().toLowerCase() !== p.country.trim().toLowerCase();

  return (
    <>
      {/* ── Identity Header ───────────────────────────────────── */}
      <section className="player-profile-hero card p-6 bg-gradient-to-r from-surface to-surface-elevated/30">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap mb-2">
              <h1 className="text-h1 text-text-primary font-semibold">{p.name}</h1>
              {flag && (
                <span className="text-2xl" title={p.country}>
                  {flag}
                </span>
              )}
              <span className="text-text-secondary text-lg">{teamPrimary}</span>
              {showAlsoCountry && (
                <span className="text-text-muted text-sm">· {p.country}</span>
              )}
            </div>

            <div className="flex items-center gap-2 flex-wrap mb-3">
              {(p.archetypes && p.archetypes.length > 0
                ? p.archetypes
                : p.archetype
                  ? [p.archetype]
                  : []
              ).map((arch, i) => (
                <span
                  key={arch}
                  className={`archetype-badge ${i > 0 ? "opacity-60" : ""}`}
                >
                  {i === 0 && <Zap size={12} />}
                  {arch}
                </span>
              ))}
              {p.position_group && p.position_group !== "unknown" && (
                <span className="archetype-badge">
                  {p.position_group.replace(/_/g, " ")}
                </span>
              )}
              {p.is_provisional && (
                <span className="provisional-badge">
                  <AlertTriangle size={12} />
                  Provisional
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
              <StatChip label="Innings" value={fmtInt(p.innings_count, "0")} />
              <StatChip label="Runs" value={fmtInt(p.total_runs, "0")} />
              <StatChip label="SR" value={fmtSR(p.career_sr)} />
              <StatChip label="Avg" value={fmtAvg(p.career_avg)} />
              <StatChip label="4s" value={fmtInt(p.total_fours, "0")} />
              <StatChip label="6s" value={fmtInt(p.total_sixes, "0")} />
            </div>
          </div>

          {/* Current (simple) + career overall (spec) */}
          <div className="flex flex-col items-center gap-1 shrink-0">
            <span className="text-xs text-text-muted uppercase tracking-wider">
              Current
            </span>
            <GradeBadge grade={p.overall_grade} size="xl" />
            <span
              className="text-2xl font-score font-bold tabular-nums mt-1"
              style={{
                color: scoreToColour(primaryDisplayRating(p)),
              }}
            >
              {fmtScore(primaryDisplayRating(p))}
            </span>
            {p.rating_overall != null && (
              <div className="text-center mt-2 pt-2 border-t border-surface-elevated/80 w-full min-w-[7rem]">
                <span className="text-[10px] text-text-muted uppercase tracking-wider block">
                  Career overall
                </span>
                <span
                  className="text-lg font-score tabular-nums font-semibold"
                  style={{ color: scoreToColour(p.rating_overall) }}
                >
                  {fmtScore(p.rating_overall)}
                </span>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── Metric Scores ─────────────────────────────────────── */}
      <section className="card p-6">
        <SectionTitle
          icon={<BarChart3 size={18} />}
          title="Metric Scores"
          actions={
            <SocialShareTrigger
              exportRef={metricScoresExportRef}
              filenameBase={`player-${p.id}-metrics`}
              subjects={subjectsFromPlayers([p])}
              subtitle="Metric scores"
            />
          }
        />

        <div
          ref={metricScoresExportRef}
          className={`${SOCIAL_EXPORT_ROOT_CLASS} mt-4 grid grid-cols-1 gap-6 rounded-xl bg-surface/30 p-4 lg:grid-cols-2`}
        >
          {/* Score bars */}
          <div className="space-y-3">
            <ScoreBar
              value={p.score_acceleration}
              label="Acceleration"
              labelShort="ACL"
              size="lg"
              variant="full"
              labelWidth="w-32"
              showGrade
              grade={p.grade_acceleration}
            />
            <ScoreBar
              value={p.score_power}
              label="Power"
              labelShort="POW"
              size="lg"
              variant="full"
              labelWidth="w-32"
              showGrade
              grade={p.grade_power}
            />
            <ScoreBar
              value={p.score_control}
              label="Control"
              labelShort="CTL"
              size="lg"
              variant="full"
              labelWidth="w-32"
              showGrade
              grade={p.grade_control}
            />
          </div>

          {/* Simple radar/indicator */}
          <div className="flex items-center justify-center">
            <SimpleRadar
              values={[
                { label: "Acceleration", value: p.score_acceleration },
                { label: "Power", value: p.score_power },
                { label: "Control", value: p.score_control },
              ]}
              size={220}
            />
          </div>
        </div>
      </section>

      {/* ── Peak vs Current ───────────────────────────────────── */}
      {p.peak_composite_batting != null && (
        <section className="card p-6">
          <SectionTitle
            icon={<TrendingUp size={18} />}
            title="Peak vs Current"
          />
          <div className="mt-4 overflow-x-auto">
            <table className="sortable-table text-sm">
              <thead>
                <tr>
                  <th className="text-left w-32">Metric</th>
                  <th className="text-right">Current</th>
                  <th className="text-right">Peak</th>
                  <th className="text-right">Delta</th>
                </tr>
              </thead>
              <tbody>
                <PeakRow
                  label="Composite"
                  current={primaryDisplayRating(p)}
                  peak={p.peak_composite_batting}
                />
                {p.peak_window_composite != null && (
                  <PeakRow
                    label="Peak Window"
                    current={primaryDisplayRating(p)}
                    peak={p.peak_window_composite}
                  />
                )}
              </tbody>
            </table>
            {(p.peak_window_start || p.peak_window_end) && (
              <p className="text-xs text-text-muted mt-2">
                Peak window:{" "}
                {fmtDateRange(p.peak_window_start, p.peak_window_end)}
                {p.peak_window_innings != null &&
                  ` (${p.peak_window_innings} innings)`}
              </p>
            )}
          </div>
        </section>
      )}

      {/* ── Advanced Metrics ──────────────────────────────────── */}
      <section className="card p-6">
        <SectionTitle icon={<Activity size={18} />} title="Advanced Metrics" />
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 mt-4">
          <MetricTile
            label="WAR (Batting)"
            value={fmtWAR(p.war_batting)}
            tooltip="Wins Above Replacement — how many extra wins this player generates over a replacement-level player"
          />
          <MetricTile
            label="WAR Rate"
            value={fmtWAR(p.war_batting_rate)}
            suffix="/50 inn"
            tooltip="WAR normalised per 50 innings"
          />
          <MetricTile
            label="Pressure Score"
            value={`${fmtPressureScore(p.clutch_index, "bat")}/100`}
            colour={scoreToColour(pressureScore(p.clutch_index, "bat"))}
            icon={
              (pressureScore(p.clutch_index, "bat") ?? 0) >= 80 ? (
                <Flame size={14} className="text-accent" />
              ) : undefined
            }
            tooltip="0-100 score for how much better this batter performs in high-pressure situations. Around 50 is neutral."
          />
          <MetricTile
            label="Chase Master"
            value={fmtScore(p.chase_master_index)}
            tooltip="Composite chasing ability index"
          />
          <MetricTile
            label="Flat Track Index"
            value={fmtSigned(p.flat_track_index, 2)}
            colour={
              (p.flat_track_index ?? 0) > 0.15
                ? "#EF4444"
                : (p.flat_track_index ?? 0) < 0.05
                  ? "#22C55E"
                  : undefined
            }
            tooltip="Negative = consistent across venues. Positive = better on easier pitches"
          />
          <MetricTile
            label="Venue Adj. Comp."
            value={fmtScore(p.venue_adjusted_composite)}
            tooltip="Composite score adjusted for venue difficulty"
          />
          <MetricTile
            label="Avg Matchup Edge"
            value={`${fmtMatchupEdge(p.avg_dominance)}/100`}
            colour={dominanceColour(p.avg_dominance)}
            tooltip="Average 0-100 matchup edge across all bowler matchups. Around 50 is even, higher favours the batter."
          />
          <MetricTile
            label="Unique Bowlers"
            value={fmtIntRaw(p.unique_bowlers)}
            tooltip="Number of distinct bowlers faced in matchup data"
          />
        </div>
      </section>

      <PlayerMatchImpactSection
        playerId={p.id}
        rows={matchImpactRows}
        isLoading={matchImpactLoading}
        isError={matchImpactError}
      />

      {/* ── Component Breakdown ────────────────────────────────── */}
      {p.components && Object.keys(p.components).length > 0 && (
        <section className="card p-6">
          <SectionTitle
            icon={<BarChart3 size={18} />}
            title="Component Breakdown"
          />
          <div className="mt-4 space-y-6">
            {Object.entries(p.components).map(([metricName, breakdown]) => (
              <ComponentBreakdownSection
                key={metricName}
                metricName={metricName}
                values={breakdown.values}
              />
            ))}
          </div>
        </section>
      )}

      {/* ── Phase Splits ──────────────────────────────────────── */}
      {p.phases && Object.keys(p.phases).length > 0 && (
        <section className="card p-6">
          <SectionTitle
            icon={<Target size={18} />}
            title="Phase Splits"
            actions={
              <SocialShareTrigger
                exportRef={phaseExportRef}
                filenameBase={`player-${p.id}-phases`}
                subjects={subjectsFromPlayers([p])}
                subtitle="Phase splits"
              />
            }
          />
          <div
            ref={phaseExportRef}
            className={`${SOCIAL_EXPORT_ROOT_CLASS} mt-4 overflow-x-auto rounded-xl bg-surface/30 p-4`}
          >
            <table className="sortable-table text-sm">
              <thead>
                <tr>
                  <th className="text-left">Phase</th>
                  <th className="text-right">Balls</th>
                  <th className="text-right">Runs</th>
                  <th className="text-right">SR</th>
                  <th className="text-right">Dot%</th>
                  <th className="text-right">Bdry%</th>
                  <th className="text-right">4s</th>
                  <th className="text-right">6s</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(p.phases).map(([phase, data]) => (
                  <tr key={phase}>
                    <td className="font-medium">{fmtPhase(phase)}</td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.balls)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.runs)}
                    </td>
                    <td className="text-right tabular-nums font-score">
                      {fmtSR(data.sr)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtPct(data.dot_pct)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtPct(data.boundary_pct)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.fours)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.sixes)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Chase Splits ──────────────────────────────────────── */}
      {p.chase_splits && Object.keys(p.chase_splits).length > 0 && (
        <section className="card p-6">
          <SectionTitle icon={<Shield size={18} />} title="Chase Splits" />
          <div className="mt-4 overflow-x-auto">
            <table className="sortable-table text-sm">
              <thead>
                <tr>
                  <th className="text-left">Context</th>
                  <th className="text-right">Innings</th>
                  <th className="text-right">Avg</th>
                  <th className="text-right">SR</th>
                  <th className="text-right">Composite</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(p.chase_splits).map(([context, data]) => (
                  <tr key={context}>
                    <td className="font-medium capitalize">{context}</td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.innings)}
                    </td>
                    <td className="text-right tabular-nums font-score">
                      {fmtAvg(data.avg)}
                    </td>
                    <td className="text-right tabular-nums font-score">
                      {fmtSR(data.sr)}
                    </td>
                    <td className="text-right tabular-nums font-score">
                      {fmtScore(data.composite)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Form Tracker ──────────────────────────────────────── */}
      <section className="card p-6">
        <SectionTitle
          icon={<TrendingUp size={18} />}
          title="Form Tracker"
          actions={
            showForm &&
            !formLoading &&
            formData?.series &&
            formData.series.length > 0 ? (
              <SocialShareTrigger
                exportRef={formExportRef}
                filenameBase={`player-${p.id}-form`}
                subjects={subjectsFromPlayers([p])}
                subtitle="Form tracker"
              />
            ) : undefined
          }
        />
        {!showForm ? (
          <div className="mt-4 text-center py-8">
            <p className="text-sm text-text-secondary mb-3">
              View how this player's metrics have evolved over time.
            </p>
            <button onClick={onShowForm} className="btn-secondary btn-sm">
              <Activity size={14} />
              Load Form Chart
            </button>
          </div>
        ) : formLoading ? (
          <div className="mt-4 flex items-center justify-center py-16">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 rounded-full border-4 border-surface-elevated border-t-primary animate-spin" />
              <span className="text-xs text-text-muted">
                Loading form data…
              </span>
            </div>
          </div>
        ) : formData?.series && formData.series.length > 0 ? (
          <div
            ref={formExportRef}
            className={`${SOCIAL_EXPORT_ROOT_CLASS} mt-4 rounded-xl bg-surface/30 p-4`}
          >
            <FormChart series={formData.series} role="bat" />
          </div>
        ) : (
          <div className="mt-4 text-center py-8">
            <p className="text-sm text-text-muted">
              No form data available for this player.
            </p>
          </div>
        )}
      </section>

      {/* ── Top Matchups ──────────────────────────────────────── */}
      {(p.top_dominant.length > 0 || p.top_nemeses.length > 0) && (
        <section className="card p-6">
          <SectionTitle icon={<Swords size={18} />} title="Top Matchups" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
            {/* Best against */}
            {p.top_dominant.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-accent mb-2 flex items-center gap-1.5">
                  <TrendingUp size={14} />
                  Best Against (Dominates)
                </h4>
                <MatchupList matchups={p.top_dominant} perspective="bat" />
              </div>
            )}

            {/* Worst against */}
            {p.top_nemeses.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-danger mb-2 flex items-center gap-1.5">
                  <TrendingDown size={14} />
                  Worst Against (Dominated by)
                </h4>
                <MatchupList matchups={p.top_nemeses} perspective="bat" />
              </div>
            )}
          </div>

          <div className="mt-4 pt-3 border-t border-surface-elevated/50">
            <Link
              to={`/matchups/explore?player_id=${p.id}&role=bat`}
              className="text-sm text-primary hover:text-primary-hover transition-colors inline-flex items-center gap-1"
            >
              View all matchups
              <ChevronRight size={14} />
            </Link>
          </div>
        </section>
      )}

      {/* ── Similar Players ───────────────────────────────────── */}
      {p.similar.length > 0 && (
        <section className="card p-6">
          <SectionTitle icon={<Users size={18} />} title="Similar Players" />
          <p className="text-sm text-text-secondary mt-1 mb-4">
            Players with the most similar statistical profiles (cosine
            similarity).
          </p>
          <SimilarPlayersList similar={p.similar} role="bat" />
          <div className="mt-4 pt-3 border-t border-surface-elevated/50">
            <Link
              to={`/similar/${p.id}`}
              className="text-sm text-primary hover:text-primary-hover transition-colors inline-flex items-center gap-1"
            >
              View full similarity analysis
              <ChevronRight size={14} />
            </Link>
          </div>
        </section>
      )}

      {/* ── Innings Log ───────────────────────────────────────── */}
      {inningsData && (
        <section className="card p-6">
          <SectionTitle icon={<BarChart3 size={18} />} title="Recent Innings" />
          <InningsLog
            data={inningsData}
            page={logPage}
            perPage={logPerPage}
            onPageChange={onLogPageChange}
          />
          <div className="mt-3 pt-3 border-t border-surface-elevated/50">
            <Link
              to={`/player/${p.id}/innings`}
              className="text-sm text-primary hover:text-primary-hover transition-colors inline-flex items-center gap-1"
            >
              View full innings log
              <ChevronRight size={14} />
            </Link>
          </div>
        </section>
      )}

      {/* ── Action Buttons ────────────────────────────────────── */}
      <ActionBar playerId={p.id} playerName={p.name} navigate={navigate} />
    </>
  );
}

// ── Bowler Profile View ──────────────────────────────────────────

interface BowlerProfileViewProps {
  profile: BowlerProfile;
  formData: any;
  formLoading: boolean;
  showForm: boolean;
  onShowForm: () => void;
  spellsData: any;
  logPage: number;
  logPerPage: number;
  onLogPageChange: (page: number) => void;
  navigate: (path: string) => void;
  matchImpactRows: PlayerMatchImpactRow[] | undefined;
  matchImpactLoading: boolean;
  matchImpactError: boolean;
}

function BowlerProfileView({
  profile: p,
  formData,
  formLoading,
  showForm,
  onShowForm,
  spellsData,
  logPage,
  logPerPage,
  onLogPageChange,
  navigate,
  matchImpactRows,
  matchImpactLoading,
  matchImpactError,
}: BowlerProfileViewProps) {
  const metricScoresBowlExportRef = useRef<HTMLDivElement>(null);
  const formBowlExportRef = useRef<HTMLDivElement>(null);
  const phaseBowlExportRef = useRef<HTMLDivElement>(null);

  const flag = countryFlag(p.country);
  const teamPrimary =
    (p.recent_team || "").trim() || p.country || "";
  const showAlsoCountry =
    (p.recent_team || "").trim() &&
    p.country &&
    (p.recent_team || "").trim().toLowerCase() !== p.country.trim().toLowerCase();

  return (
    <>
      {/* ── Identity Header ───────────────────────────────────── */}
      <section className="player-profile-hero card p-6 bg-gradient-to-r from-surface to-surface-elevated/30">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap mb-2">
              <h1 className="text-h1 text-text-primary font-semibold">{p.name}</h1>
              {flag && (
                <span className="text-2xl" title={p.country}>
                  {flag}
                </span>
              )}
              <span className="text-text-secondary text-lg">{teamPrimary}</span>
              {showAlsoCountry && (
                <span className="text-text-muted text-sm">· {p.country}</span>
              )}
            </div>

            <div className="flex items-center gap-2 flex-wrap mb-3">
              {(p.archetypes && p.archetypes.length > 0
                ? p.archetypes
                : p.archetype
                  ? [p.archetype]
                  : []
              ).map((arch, i) => (
                <span
                  key={arch}
                  className={`archetype-badge ${i > 0 ? "opacity-60" : ""}`}
                >
                  {i === 0 && <Target size={12} />}
                  {arch}
                </span>
              ))}
              {p.phase_group && p.phase_group !== "unknown" && (
                <span className="archetype-badge">
                  {p.phase_group.replace(/_/g, " ")}
                </span>
              )}
              {p.is_provisional && (
                <span className="provisional-badge">
                  <AlertTriangle size={12} />
                  Provisional
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
              <StatChip label="Matches" value={fmtInt(p.matches, "0")} />
              <StatChip label="Wickets" value={fmtInt(p.total_wickets, "0")} />
              <StatChip label="Econ" value={fmtEcon(p.career_economy)} />
              <StatChip label="SR" value={fmtSR(p.career_sr_bowl)} />
              <StatChip label="Dot%" value={fmtPct(p.career_dot_pct)} />
              {p.total_overs != null && (
                <StatChip label="Overs" value={fmtOvers(p.total_overs)} />
              )}
            </div>
          </div>

          <div className="flex flex-col items-center gap-1 shrink-0">
            <span className="text-xs text-text-muted uppercase tracking-wider">
              Current
            </span>
            <GradeBadge grade={p.overall_grade} size="xl" />
            <span
              className="text-2xl font-score font-bold tabular-nums mt-1"
              style={{
                color: scoreToColour(primaryDisplayRating(p)),
              }}
            >
              {fmtScore(primaryDisplayRating(p))}
            </span>
            {p.rating_overall != null && (
              <div className="text-center mt-2 pt-2 border-t border-surface-elevated/80 w-full min-w-[7rem]">
                <span className="text-[10px] text-text-muted uppercase tracking-wider block">
                  Career overall
                </span>
                <span
                  className="text-lg font-score tabular-nums font-semibold"
                  style={{ color: scoreToColour(p.rating_overall) }}
                >
                  {fmtScore(p.rating_overall)}
                </span>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── Metric Scores ─────────────────────────────────────── */}
      <section className="card p-6">
        <SectionTitle
          icon={<BarChart3 size={18} />}
          title="Metric Scores"
          actions={
            <SocialShareTrigger
              exportRef={metricScoresBowlExportRef}
              filenameBase={`player-${p.id}-metrics-bowl`}
              subjects={subjectsFromPlayers([p])}
              subtitle="Metric scores"
            />
          }
        />
        <div
          ref={metricScoresBowlExportRef}
          className={`${SOCIAL_EXPORT_ROOT_CLASS} mt-4 grid grid-cols-1 gap-6 rounded-xl bg-surface/30 p-4 lg:grid-cols-2`}
        >
          <div className="space-y-3">
            <ScoreBar
              value={p.score_accuracy}
              label="Accuracy"
              labelShort="ACC"
              size="lg"
              variant="full"
              labelWidth="w-32"
              showGrade
              grade={p.grade_accuracy}
            />
            <ScoreBar
              value={p.score_control}
              label="Control"
              labelShort="CTL"
              size="lg"
              variant="full"
              labelWidth="w-32"
              showGrade
              grade={p.grade_control}
            />
            <ScoreBar
              value={p.score_threat}
              label="Threat"
              labelShort="THR"
              size="lg"
              variant="full"
              labelWidth="w-32"
              showGrade
              grade={p.grade_threat}
            />
          </div>
          <div className="flex items-center justify-center">
            <SimpleRadar
              values={[
                { label: "Accuracy", value: p.score_accuracy },
                { label: "Control", value: p.score_control },
                { label: "Threat", value: p.score_threat },
              ]}
              size={220}
            />
          </div>
        </div>
      </section>

      {/* ── Advanced Metrics ──────────────────────────────────── */}
      <section className="card p-6">
        <SectionTitle icon={<Activity size={18} />} title="Advanced Metrics" />
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 mt-4">
          <MetricTile label="WAR (Bowling)" value={fmtWAR(p.war_bowling)} />
          <MetricTile
            label="WAR Rate"
            value={fmtWAR(p.war_bowling_rate)}
            suffix="/50 spells"
          />
          <MetricTile
            label="Pressure Score"
            value={`${fmtPressureScore(p.clutch_index_bowl, "bowl")}/100`}
            colour={scoreToColour(pressureScore(p.clutch_index_bowl, "bowl"))}
            tooltip="0-100 score for how much better this bowler performs in high-pressure spells. Around 50 is neutral."
          />
          <MetricTile
            label="Flat Track Index"
            value={fmtSigned(p.flat_track_index_bowl, 2)}
          />
          <MetricTile
            label="Bowled/LBW %"
            value={fmtPct(p.bowled_lbw_pct)}
            tooltip="Percentage of wickets that are bowled or LBW — indicates quality dismissals"
          />
          <MetricTile
            label="Avg Matchup Edge"
            value={`${fmtMatchupEdge(p.avg_dominance_bowl)}/100`}
            colour={dominanceColour(p.avg_dominance_bowl)}
            tooltip="Average 0-100 matchup edge across all batter matchups. Lower scores mean the bowler tends to control contests."
          />
          <MetricTile
            label="% Dominant"
            value={fmtPct(p.pct_dominant_bowl)}
            tooltip="Percentage of matchups where the bowler dominates"
          />
          <MetricTile
            label="Pressure Spells"
            value={fmtIntRaw(p.pressure_spells)}
          />
        </div>
      </section>

      <PlayerMatchImpactSection
        playerId={p.id}
        rows={matchImpactRows}
        isLoading={matchImpactLoading}
        isError={matchImpactError}
      />

      {/* ── Component Breakdown ────────────────────────────────── */}
      {p.components && Object.keys(p.components).length > 0 && (
        <section className="card p-6">
          <SectionTitle
            icon={<BarChart3 size={18} />}
            title="Component Breakdown"
          />
          <div className="mt-4 space-y-6">
            {Object.entries(p.components).map(([metricName, breakdown]) => (
              <ComponentBreakdownSection
                key={metricName}
                metricName={metricName}
                values={breakdown.values}
              />
            ))}
          </div>
        </section>
      )}

      {/* ── Phase Splits ──────────────────────────────────────── */}
      {p.phases && Object.keys(p.phases).length > 0 && (
        <section className="card p-6">
          <SectionTitle
            icon={<Target size={18} />}
            title="Phase Splits"
            actions={
              <SocialShareTrigger
                exportRef={phaseBowlExportRef}
                filenameBase={`player-${p.id}-phases-bowl`}
                subjects={subjectsFromPlayers([p])}
                subtitle="Phase splits"
              />
            }
          />
          <div
            ref={phaseBowlExportRef}
            className={`${SOCIAL_EXPORT_ROOT_CLASS} mt-4 overflow-x-auto rounded-xl bg-surface/30 p-4`}
          >
            <table className="sortable-table text-sm">
              <thead>
                <tr>
                  <th className="text-left">Phase</th>
                  <th className="text-right">Balls</th>
                  <th className="text-right">Runs</th>
                  <th className="text-right">Wkts</th>
                  <th className="text-right">Econ</th>
                  <th className="text-right">Dot%</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(p.phases).map(([phase, data]) => (
                  <tr key={phase}>
                    <td className="font-medium">{fmtPhase(phase)}</td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.balls)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.runs)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtInt(data.wickets)}
                    </td>
                    <td className="text-right tabular-nums font-score">
                      {fmtEcon(data.economy)}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtPct(data.dot_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Form Tracker ──────────────────────────────────────── */}
      <section className="card p-6">
        <SectionTitle
          icon={<TrendingUp size={18} />}
          title="Form Tracker"
          actions={
            showForm &&
            !formLoading &&
            formData?.series &&
            formData.series.length > 0 ? (
              <SocialShareTrigger
                exportRef={formBowlExportRef}
                filenameBase={`player-${p.id}-form-bowl`}
                subjects={subjectsFromPlayers([p])}
                subtitle="Form tracker"
              />
            ) : undefined
          }
        />
        {!showForm ? (
          <div className="mt-4 text-center py-8">
            <p className="text-sm text-text-secondary mb-3">
              View how this player's metrics have evolved over time.
            </p>
            <button onClick={onShowForm} className="btn-secondary btn-sm">
              <Activity size={14} />
              Load Form Chart
            </button>
          </div>
        ) : formLoading ? (
          <div className="mt-4 flex items-center justify-center py-16">
            <div className="h-8 w-8 rounded-full border-4 border-surface-elevated border-t-primary animate-spin" />
          </div>
        ) : formData?.series && formData.series.length > 0 ? (
          <div
            ref={formBowlExportRef}
            className={`${SOCIAL_EXPORT_ROOT_CLASS} mt-4 rounded-xl bg-surface/30 p-4`}
          >
            <FormChart series={formData.series} role="bowl" />
          </div>
        ) : (
          <div className="mt-4 text-center py-8">
            <p className="text-sm text-text-muted">
              No form data available for this player.
            </p>
          </div>
        )}
      </section>

      {/* ── Top Matchups ──────────────────────────────────────── */}
      {(p.top_bunnies.length > 0 || p.top_dominated_by.length > 0) && (
        <section className="card p-6">
          <SectionTitle icon={<Swords size={18} />} title="Top Matchups" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
            {p.top_bunnies.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-accent mb-2 flex items-center gap-1.5">
                  <TrendingUp size={14} />
                  Bunnies (Dominates)
                </h4>
                <MatchupList matchups={p.top_bunnies} perspective="bowl" />
              </div>
            )}
            {p.top_dominated_by.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-danger mb-2 flex items-center gap-1.5">
                  <TrendingDown size={14} />
                  Dominated by
                </h4>
                <MatchupList matchups={p.top_dominated_by} perspective="bowl" />
              </div>
            )}
          </div>
          <div className="mt-4 pt-3 border-t border-surface-elevated/50">
            <Link
              to={`/matchups/explore?player_id=${p.id}&role=bowl`}
              className="text-sm text-primary hover:text-primary-hover transition-colors inline-flex items-center gap-1"
            >
              View all matchups
              <ChevronRight size={14} />
            </Link>
          </div>
        </section>
      )}

      {/* ── Similar Players ───────────────────────────────────── */}
      {p.similar.length > 0 && (
        <section className="card p-6">
          <SectionTitle icon={<Users size={18} />} title="Similar Players" />
          <p className="text-sm text-text-secondary mt-1 mb-4">
            Bowlers with the most similar statistical profiles.
          </p>
          <SimilarPlayersList similar={p.similar} role="bowl" />
          <div className="mt-4 pt-3 border-t border-surface-elevated/50">
            <Link
              to={`/similar/${p.id}`}
              className="text-sm text-primary hover:text-primary-hover transition-colors inline-flex items-center gap-1"
            >
              View full similarity analysis
              <ChevronRight size={14} />
            </Link>
          </div>
        </section>
      )}

      {/* ── Spells Log ────────────────────────────────────────── */}
      {spellsData && (
        <section className="card p-6">
          <SectionTitle icon={<BarChart3 size={18} />} title="Recent Spells" />
          <SpellsLog
            data={spellsData}
            page={logPage}
            perPage={logPerPage}
            onPageChange={onLogPageChange}
          />
          <div className="mt-3 pt-3 border-t border-surface-elevated/50">
            <Link
              to={`/player/${p.id}/spells`}
              className="text-sm text-primary hover:text-primary-hover transition-colors inline-flex items-center gap-1"
            >
              View full spells log
              <ChevronRight size={14} />
            </Link>
          </div>
        </section>
      )}

      {/* ── Action Buttons ────────────────────────────────────── */}
      <ActionBar playerId={p.id} playerName={p.name} navigate={navigate} />
    </>
  );
}

// ── Shared sub-components ────────────────────────────────────────

function SectionTitle({
  icon,
  title,
  actions,
}: {
  icon: React.ReactNode;
  title: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-2">
      <h2 className="text-h3 text-text-primary flex min-w-0 flex-1 items-center gap-2">
        <span className="shrink-0 text-primary">{icon}</span>
        {title}
      </h2>
      {actions ? (
        <div className="flex shrink-0 items-start">{actions}</div>
      ) : null}
    </div>
  );
}

function StatChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-text-secondary text-xs font-medium">{label}</span>
      <span className="font-score tabular-nums font-medium text-text-primary text-sm">
        {value}
      </span>
    </span>
  );
}

// ── Peak vs Current row ──────────────────────────────────────────

function PeakRow({
  label,
  current,
  peak,
}: {
  label: string;
  current: number | null | undefined;
  peak: number | null | undefined;
}) {
  const delta = current != null && peak != null ? current - peak : null;

  return (
    <tr>
      <td className="font-medium">{label}</td>
      <td className="text-right">
        <span
          className="font-score tabular-nums"
          style={{ color: scoreToColour(current) }}
        >
          {fmtScore(current)}
        </span>
      </td>
      <td className="text-right">
        <span
          className="font-score tabular-nums"
          style={{ color: scoreToColour(peak) }}
        >
          {fmtScore(peak)}
        </span>
      </td>
      <td className="text-right">
        <span
          className={`font-score tabular-nums ${
            (delta ?? 0) >= 0 ? "text-accent" : "text-danger"
          }`}
        >
          {fmtSigned(delta)}
        </span>
      </td>
    </tr>
  );
}

// ── Metric tile ──────────────────────────────────────────────────

function MetricTile({
  label,
  value,
  suffix,
  colour,
  icon,
  tooltip,
}: {
  label: string;
  value: string;
  suffix?: string;
  colour?: string;
  icon?: React.ReactNode;
  tooltip?: string;
}) {
  return (
    <div
      className="metric-tile bg-surface-elevated/30 rounded-lg p-3 group relative"
      title={tooltip}
    >
      <div className="metric-tile-label text-xs text-text-secondary mb-1 flex items-center gap-1 font-medium">
        {label}
        {tooltip && (
          <Info
            size={10}
            className="text-text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
          />
        )}
      </div>
      <div className="flex items-center gap-1.5">
        {icon}
        <span
          className="text-lg font-score font-bold tabular-nums text-text-primary"
          style={colour ? { color: colour } : undefined}
        >
          {value}
        </span>
        {suffix && <span className="metric-tile-suffix text-xs text-text-secondary">{suffix}</span>}
      </div>
    </div>
  );
}

// ── Component Breakdown Section ──────────────────────────────────

function ComponentBreakdownSection({
  metricName,
  values,
}: {
  metricName: string;
  values: Record<string, number | null>;
}) {
  const entries = Object.entries(values).filter(
    ([, v]) => v != null && !isNaN(v as number),
  );

  if (entries.length === 0) return null;

  const maxVal = Math.max(...entries.map(([, v]) => Math.abs(v as number)), 1);

  const displayName =
    metricName.charAt(0).toUpperCase() +
    metricName
      .slice(1)
      .replace(/_/g, " ")
      .replace(/([A-Z])/g, " $1");

  return (
    <div>
      <h4 className="text-sm font-medium text-text-secondary mb-2 capitalize">
        {displayName} Components
      </h4>
      <div className="space-y-1.5">
        {entries.map(([name, rawValue]) => {
          const value = rawValue as number;
          const pct = Math.min(
            100,
            Math.max(0, (Math.abs(value) / maxVal) * 100),
          );
          const label = name
            .replace(/_/g, " ")
            .replace(/([A-Z])/g, " $1")
            .trim();

          return (
            <div key={name} className="flex items-center gap-2">
              <span className="text-xs text-text-muted w-32 shrink-0 truncate capitalize">
                {label}
              </span>
              <div className="flex-1 h-2 rounded-full bg-surface-elevated overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: scoreToColour(value),
                  }}
                />
              </div>
              <span
                className="text-xs font-score tabular-nums w-10 text-right shrink-0"
                style={{ color: scoreToColour(value) }}
              >
                {value.toFixed(1)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Matchup List ─────────────────────────────────────────────────

function MatchupList({
  matchups,
  perspective: _perspective,
}: {
  matchups: MatchupSummary[];
  perspective: "bat" | "bowl";
}) {
  return (
    <div className="space-y-1.5">
      {matchups.slice(0, 5).map((m, i) => (
        <div
          key={`${m.opponent_id}-${i}`}
          className="flex items-center gap-2 py-1.5 px-2 rounded hover:bg-surface-elevated/30 transition-colors group"
        >
          <Link
            to={`/player/${m.opponent_id}`}
            className="text-sm text-text-primary group-hover:text-primary transition-colors truncate flex-1 min-w-0"
          >
            vs {m.opponent_name || m.opponent_id}
          </Link>
          <span className="text-xs text-text-muted tabular-nums shrink-0">
            {fmtInt(m.balls, "0")}b
          </span>
          <span className="text-xs text-text-secondary tabular-nums shrink-0">
            SR {fmtSR(m.sr)}
          </span>
          <span
            className="text-xs font-score tabular-nums shrink-0 font-medium"
            style={{ color: dominanceColour(m.dominance_index) }}
          >
            {m.dominance_index != null
              ? `${fmtMatchupEdge(m.dominance_index)}/100`
              : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Similar Players List ─────────────────────────────────────────

function SimilarPlayersList({
  similar,
  role,
}: {
  similar: SimilarPlayer[];
  role: "bat" | "bowl";
}) {
  return (
    <div className="overflow-x-auto">
      <table className="sortable-table text-sm">
        <thead>
          <tr>
            <th className="text-left">#</th>
            <th className="text-left">Player</th>
            <th className="text-right">Similarity</th>
            <th className="text-right">{role === "bat" ? "ACL" : "ACC"}</th>
            <th className="text-right">{role === "bat" ? "POW" : "CTL"}</th>
            <th className="text-right">{role === "bat" ? "CTL" : "THR"}</th>
          </tr>
        </thead>
        <tbody>
          {similar.slice(0, 5).map((s, i) => (
            <tr key={s.id}>
              <td className="text-text-muted">{i + 1}</td>
              <td>
                <Link
                  to={`/player/${s.id}`}
                  className="text-text-primary hover:text-primary transition-colors font-medium"
                >
                  {s.name}
                </Link>
                {s.country && (
                  <span className="ml-1.5 text-xs" title={s.country}>
                    {countryFlag(s.country)}
                  </span>
                )}
              </td>
              <td className="text-right font-score tabular-nums text-primary">
                {s.similarity_score != null
                  ? s.similarity_score.toFixed(2)
                  : "—"}
              </td>
              <td className="text-right">
                <ScoreBarMini value={s.score_1} width={36} />
              </td>
              <td className="text-right">
                <ScoreBarMini value={s.score_2} width={36} />
              </td>
              <td className="text-right">
                <ScoreBarMini value={s.score_3} width={36} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Form Chart ───────────────────────────────────────────────────

/** Capitalise first letter of a label string. */
function _cap(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

/** Colours for the sub-score lines (dimmer than the main composite). */
const SUB_COLOURS = {
  score_1: "#60A5FA", // blue-400
  score_2: "#F472B6", // pink-400
  score_3: "#34D399", // emerald-400
} as const;

/** Custom tooltip for the form chart. */
function FormChartTooltip({
  active,
  payload,
  label,
  role,
  showSubs,
}: any & { role: "bat" | "bowl"; showSubs: boolean }) {
  if (!active || !payload || payload.length === 0) return null;

  const d = payload[0]?.payload;
  if (!d) return null;

  const composite = d.composite as number | null;
  const s1 = d.score_1 as number | null;
  const s2 = d.score_2 as number | null;
  const s3 = d.score_3 as number | null;
  const avgRuns = d.window_avg_runs as number | null;
  const avgSR = d.window_avg_sr as number | null;
  const totalRuns = d.window_total_runs as number | null;
  const fours = d.window_fours as number | null;
  const sixes = d.window_sixes as number | null;
  const innings = d.window_innings as number | null;
  const isPeak = d.is_peak_window as boolean;
  const economy = d.window_economy as number | null;
  const wickets = d.window_total_wickets as number | null;
  const dotPct = d.window_dot_pct as number | null;

  return (
    <div
      className="rounded-lg border border-surface-elevated bg-surface px-3 py-2 text-xs shadow-lg"
      style={{ minWidth: 180 }}
    >
      <div className="flex items-center justify-between gap-3 mb-1.5">
        <span className="text-text-muted">{label}</span>
        {isPeak && (
          <span className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider">
            ★ Peak
          </span>
        )}
      </div>

      {/* Composite */}
      <div className="flex items-center justify-between gap-4 font-medium">
        <span style={{ color: CHART_COLOURS[0] }}>Composite</span>
        <span
          className="font-score tabular-nums"
          style={{ color: scoreToColour(composite) }}
        >
          {composite != null ? composite.toFixed(1) : "—"}
        </span>
      </div>

      {/* Sub-scores (when expanded) */}
      {showSubs && s1 != null && (
        <div className="flex items-center justify-between gap-4 mt-0.5">
          <span style={{ color: SUB_COLOURS.score_1 }}>
            {_cap(d.score_1_label)}
          </span>
          <span className="font-score tabular-nums">{s1.toFixed(1)}</span>
        </div>
      )}
      {showSubs && s2 != null && (
        <div className="flex items-center justify-between gap-4">
          <span style={{ color: SUB_COLOURS.score_2 }}>
            {_cap(d.score_2_label)}
          </span>
          <span className="font-score tabular-nums">{s2.toFixed(1)}</span>
        </div>
      )}
      {showSubs && s3 != null && (
        <div className="flex items-center justify-between gap-4">
          <span style={{ color: SUB_COLOURS.score_3 }}>
            {_cap(d.score_3_label)}
          </span>
          <span className="font-score tabular-nums">{s3.toFixed(1)}</span>
        </div>
      )}

      {/* Divider + stats */}
      <div className="border-t border-surface-elevated/60 mt-1.5 pt-1.5 space-y-0.5 text-text-secondary">
        {innings != null && (
          <div className="flex justify-between">
            <span>Window</span>
            <span className="tabular-nums">{innings} inn</span>
          </div>
        )}
        {role === "bat" ? (
          <>
            {totalRuns != null && (
              <div className="flex justify-between">
                <span>Total runs</span>
                <span className="tabular-nums font-medium text-text-primary">
                  {Math.round(totalRuns)}
                </span>
              </div>
            )}
            {avgRuns != null && (
              <div className="flex justify-between">
                <span>Avg runs/inn</span>
                <span className="tabular-nums">{avgRuns.toFixed(1)}</span>
              </div>
            )}
            {avgSR != null && (
              <div className="flex justify-between">
                <span>Avg SR</span>
                <span className="tabular-nums">{avgSR.toFixed(1)}</span>
              </div>
            )}
            {fours != null && sixes != null && (
              <div className="flex justify-between">
                <span>4s / 6s</span>
                <span className="tabular-nums">
                  {Math.round(fours)} / {Math.round(sixes)}
                </span>
              </div>
            )}
          </>
        ) : (
          <>
            {economy != null && (
              <div className="flex justify-between">
                <span>Avg economy</span>
                <span className="tabular-nums">{economy.toFixed(2)}</span>
              </div>
            )}
            {wickets != null && (
              <div className="flex justify-between">
                <span>Total wickets</span>
                <span className="tabular-nums font-medium text-text-primary">
                  {Math.round(wickets)}
                </span>
              </div>
            )}
            {dotPct != null && (
              <div className="flex justify-between">
                <span>Dot%</span>
                <span className="tabular-nums">
                  {(dotPct * 100).toFixed(1)}%
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function FormChart({
  series,
  role,
}: {
  series: FormPoint[];
  role: "bat" | "bowl";
}) {
  const [showSubScores, setShowSubScores] = useState(false);

  // Build chart data with all fields the tooltip / lines need
  const chartData = useMemo(() => {
    return series.map((pt) => ({
      date: pt.date?.slice(0, 10) ?? "",
      composite: pt.composite ?? null,
      score_1: pt.score_1 ?? null,
      score_2: pt.score_2 ?? null,
      score_3: pt.score_3 ?? null,
      score_1_label:
        pt.score_1_label || (role === "bat" ? "acceleration" : "accuracy"),
      score_2_label: pt.score_2_label || (role === "bat" ? "power" : "control"),
      score_3_label:
        pt.score_3_label || (role === "bat" ? "control" : "threat"),
      is_peak_window: pt.is_peak_window ?? false,
      window_innings: pt.window_innings ?? null,
      // Batting stats
      window_avg_runs: pt.window_avg_runs ?? null,
      window_avg_sr: pt.window_avg_sr ?? null,
      window_total_runs: pt.window_total_runs ?? null,
      window_fours: pt.window_fours ?? null,
      window_sixes: pt.window_sixes ?? null,
      // Bowling stats
      window_economy: pt.window_economy ?? null,
      window_total_wickets: pt.window_total_wickets ?? null,
      window_dot_pct: pt.window_dot_pct ?? null,
    }));
  }, [series, role]);

  // Find the peak point for the annotation dot
  const peakPoint = useMemo(() => {
    return chartData.find((d) => d.is_peak_window);
  }, [chartData]);

  // Sub-score labels from the first data point
  const labels = useMemo(() => {
    const first = chartData[0];
    return {
      s1: first?.score_1_label ?? "score 1",
      s2: first?.score_2_label ?? "score 2",
      s3: first?.score_3_label ?? "score 3",
    };
  }, [chartData]);

  if (chartData.length === 0) return null;

  return (
    <div>
      {/* Controls row */}
      <div className="flex items-center justify-end gap-3 mb-2">
        <label className="inline-flex items-center gap-1.5 text-xs text-text-muted cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showSubScores}
            onChange={(e) => setShowSubScores(e.target.checked)}
            className="accent-primary w-3.5 h-3.5"
          />
          Show sub-scores
        </label>
      </div>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 8, right: 12, left: 0, bottom: 5 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(148, 163, 184, 0.12)"
            />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "#94A3B8" }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              tickFormatter={(v: string) => {
                if (!v) return "";
                const parts = v.split("-");
                return parts.length >= 2
                  ? `${parts[1]}/${parts[0]?.slice(2)}`
                  : v;
              }}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tick={{ fontSize: 10, fill: "#94A3B8" }}
              tickLine={false}
              axisLine={false}
              width={30}
            />
            <RechartsTooltip
              content={
                <FormChartTooltip role={role} showSubs={showSubScores} />
              }
            />

            {/* Reference lines for grade thresholds */}
            <ReferenceLine
              y={50}
              stroke="#64748B"
              strokeDasharray="4 4"
              strokeOpacity={0.5}
              label={{
                value: "Median",
                position: "insideTopRight",
                fill: "#64748B",
                fontSize: 9,
              }}
            />
            <ReferenceLine
              y={75}
              stroke="#22C55E"
              strokeDasharray="4 4"
              strokeOpacity={0.25}
            />
            <ReferenceLine
              y={25}
              stroke="#EF4444"
              strokeDasharray="4 4"
              strokeOpacity={0.25}
            />

            {/* Sub-score lines (togglable) */}
            {showSubScores && (
              <>
                <Line
                  type="monotone"
                  dataKey="score_1"
                  name={_cap(labels.s1)}
                  stroke={SUB_COLOURS.score_1}
                  strokeWidth={1}
                  strokeOpacity={0.6}
                  dot={false}
                  activeDot={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="score_2"
                  name={_cap(labels.s2)}
                  stroke={SUB_COLOURS.score_2}
                  strokeWidth={1}
                  strokeOpacity={0.6}
                  dot={false}
                  activeDot={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="score_3"
                  name={_cap(labels.s3)}
                  stroke={SUB_COLOURS.score_3}
                  strokeWidth={1}
                  strokeOpacity={0.6}
                  dot={false}
                  activeDot={false}
                  connectNulls
                />
              </>
            )}

            {/* Main composite line (on top) */}
            <Line
              type="monotone"
              dataKey="composite"
              name="Composite"
              stroke={CHART_COLOURS[0]}
              strokeWidth={2.5}
              dot={false}
              activeDot={{
                r: 5,
                fill: CHART_COLOURS[0],
                stroke: "#0F172A",
                strokeWidth: 2,
              }}
              connectNulls
            />

            {/* Peak annotation dot */}
            {peakPoint && peakPoint.composite != null && (
              <ReferenceDot
                x={peakPoint.date}
                y={peakPoint.composite}
                r={6}
                fill="#F59E0B"
                stroke="#0F172A"
                strokeWidth={2}
                isFront
              />
            )}

            {showSubScores && (
              <Legend
                verticalAlign="top"
                height={28}
                wrapperStyle={{ fontSize: 11 }}
                iconType="line"
                iconSize={14}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Legend / key below chart */}
      <div className="flex flex-wrap items-center gap-4 mt-2 text-[11px] text-text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded-full"
            style={{ backgroundColor: CHART_COLOURS[0] }}
          />
          Composite (0–100)
        </span>
        {peakPoint && (
          <span className="inline-flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-3 rounded-full"
              style={{ backgroundColor: "#F59E0B" }}
            />
            All-time peak
          </span>
        )}
        <span className="ml-auto text-[10px] opacity-70">
          Rolling {chartData[0]?.window_innings ?? 10}-innings window
        </span>
      </div>
    </div>
  );
}

// ── Simple Radar (SVG) ───────────────────────────────────────────

interface RadarPoint {
  label: string;
  value: number | null | undefined;
}

function SimpleRadar({
  values,
  size = 200,
}: {
  values: RadarPoint[];
  size?: number;
}) {
  const center = size / 2;
  const maxRadius = (size / 2) * 0.78;
  const n = values.length;

  if (n < 3) return null;

  const angleStep = (2 * Math.PI) / n;
  const startAngle = -Math.PI / 2; // Start from top

  // Grid circles
  const gridLevels = [25, 50, 75, 100];

  // Compute polygon points
  const points = values.map((v, i) => {
    const score = Math.max(0, Math.min(100, v.value ?? 0));
    const r = (score / 100) * maxRadius;
    const angle = startAngle + i * angleStep;
    return {
      x: center + r * Math.cos(angle),
      y: center + r * Math.sin(angle),
      label: v.label,
      score: v.value,
      labelX: center + (maxRadius + 18) * Math.cos(angle),
      labelY: center + (maxRadius + 18) * Math.sin(angle),
    };
  });

  const polygonPath =
    points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ") + "Z";

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="overflow-visible"
    >
      {/* Grid circles */}
      {gridLevels.map((level) => {
        const r = (level / 100) * maxRadius;
        return (
          <circle
            key={level}
            cx={center}
            cy={center}
            r={r}
            fill="none"
            stroke="#334155"
            strokeWidth={0.5}
            strokeOpacity={0.5}
          />
        );
      })}

      {/* Grid labels */}
      {gridLevels.map((level) => {
        const r = (level / 100) * maxRadius;
        return (
          <text
            key={`label-${level}`}
            x={center + 2}
            y={center - r - 2}
            fill="#64748B"
            fontSize={8}
            textAnchor="start"
          >
            {level}
          </text>
        );
      })}

      {/* Axis lines */}
      {values.map((_, i) => {
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
            stroke="#334155"
            strokeWidth={0.5}
            strokeOpacity={0.5}
          />
        );
      })}

      {/* Filled polygon */}
      <path
        d={polygonPath}
        fill={`${CHART_COLOURS[0]}33`}
        stroke={CHART_COLOURS[0]}
        strokeWidth={2}
        className="transition-all duration-500"
      />

      {/* Data points */}
      {points.map((pt, i) => (
        <circle
          key={i}
          cx={pt.x}
          cy={pt.y}
          r={3.5}
          fill={scoreToColour(pt.score)}
          stroke="#0F172A"
          strokeWidth={1.5}
        />
      ))}

      {/* Axis labels */}
      {points.map((pt, i) => (
        <text
          key={`axis-${i}`}
          x={pt.labelX}
          y={pt.labelY}
          fill="#94A3B8"
          fontSize={11}
          fontWeight={500}
          textAnchor="middle"
          dominantBaseline="central"
        >
          {pt.label}
        </text>
      ))}

      {/* Score values near points */}
      {points.map((pt, i) => {
        const score = pt.score;
        if (score == null) return null;
        const offsetAngle = startAngle + i * angleStep;
        const labelR =
          (Math.max(0, Math.min(100, score)) / 100) * maxRadius + 12;
        const lx = center + labelR * Math.cos(offsetAngle);
        const ly = center + labelR * Math.sin(offsetAngle);
        return (
          <text
            key={`score-${i}`}
            x={lx}
            y={ly}
            fill={scoreToColour(score)}
            fontSize={10}
            fontWeight={700}
            fontFamily="'JetBrains Mono', monospace"
            textAnchor="middle"
            dominantBaseline="central"
          >
            {Math.round(score)}
          </text>
        );
      })}
    </svg>
  );
}

// ── Innings Log ──────────────────────────────────────────────────

function InningsLog({
  data,
  page,
  perPage,
  onPageChange,
}: {
  data: any;
  page: number;
  perPage: number;
  onPageChange: (p: number) => void;
}) {
  const innings = data?.innings ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / perPage) || 1;

  if (innings.length === 0) {
    return (
      <p className="text-sm text-text-muted mt-4">No innings data available.</p>
    );
  }

  return (
    <div className="mt-4">
      <div className="overflow-x-auto">
        <table className="sortable-table text-sm">
          <thead>
            <tr>
              <th className="text-left">Date</th>
              <th className="text-left">Vs</th>
              <th className="text-right">Runs</th>
              <th className="text-right">Balls</th>
              <th className="text-right">SR</th>
              <th className="text-right">4s</th>
              <th className="text-right">6s</th>
            </tr>
          </thead>
          <tbody>
            {innings.map((inn: InningsDetail, i: number) => (
              <tr key={`${inn.match_id}-${i}`}>
                <td className="text-text-secondary">{fmtDate(inn.date)}</td>
                <td className="truncate max-w-[8rem]">
                  {inn.opposition || "—"}
                </td>
                <td className="text-right font-score tabular-nums font-medium">
                  {inn.runs}
                  {!inn.is_out && inn.runs > 0 ? "*" : ""}
                </td>
                <td className="text-right tabular-nums">{inn.balls_faced}</td>
                <td className="text-right font-score tabular-nums">
                  {fmtSR(inn.sr)}
                </td>
                <td className="text-right tabular-nums">{inn.fours}</td>
                <td className="text-right tabular-nums">{inn.sixes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="mt-3">
          <PaginationSimple
            page={page}
            totalPages={totalPages}
            onPageChange={onPageChange}
          />
        </div>
      )}
    </div>
  );
}

// ── Spells Log ───────────────────────────────────────────────────

function SpellsLog({
  data,
  page,
  perPage,
  onPageChange,
}: {
  data: any;
  page: number;
  perPage: number;
  onPageChange: (p: number) => void;
}) {
  const spells = data?.spells ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / perPage) || 1;

  if (spells.length === 0) {
    return (
      <p className="text-sm text-text-muted mt-4">No spells data available.</p>
    );
  }

  return (
    <div className="mt-4">
      <div className="overflow-x-auto">
        <table className="sortable-table text-sm">
          <thead>
            <tr>
              <th className="text-left">Date</th>
              <th className="text-left">Vs</th>
              <th className="text-right">Overs</th>
              <th className="text-right">Runs</th>
              <th className="text-right">Wkts</th>
              <th className="text-right">Econ</th>
              <th className="text-right">Dot%</th>
            </tr>
          </thead>
          <tbody>
            {spells.map((spell: SpellDetail, i: number) => (
              <tr key={`${spell.match_id}-${i}`}>
                <td className="text-text-secondary">{fmtDate(spell.date)}</td>
                <td className="truncate max-w-[8rem]">
                  {spell.opposition || "—"}
                </td>
                <td className="text-right tabular-nums">
                  {fmtOvers(spell.overs_bowled)}
                </td>
                <td className="text-right tabular-nums">
                  {spell.runs_conceded}
                </td>
                <td className="text-right font-score tabular-nums font-medium">
                  {spell.wickets}
                </td>
                <td className="text-right font-score tabular-nums">
                  {fmtEcon(spell.economy)}
                </td>
                <td className="text-right tabular-nums">
                  {fmtPct(spell.dot_pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="mt-3">
          <PaginationSimple
            page={page}
            totalPages={totalPages}
            onPageChange={onPageChange}
          />
        </div>
      )}
    </div>
  );
}

// ── Action Bar ───────────────────────────────────────────────────

function ActionBar({
  playerId,
  playerName: _playerName,
  navigate,
}: {
  playerId: string;
  playerName: string;
  navigate: (path: string) => void;
}) {
  const handleShare = useCallback(() => {
    const url = window.location.href;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => {
        // Could show a toast here
      });
    }
  }, []);

  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => navigate(`/compare?ids=${playerId}`)}
          className="btn-primary btn-sm"
        >
          <GitCompare size={14} />
          Compare with…
        </button>
        <button
          onClick={() => navigate(`/team-builder?add=${playerId}`)}
          className="btn-secondary btn-sm"
        >
          <Users size={14} />
          Add to Team Builder
        </button>
        <button onClick={handleShare} className="btn-ghost btn-sm">
          <ExternalLink size={14} />
          Share Profile
        </button>
      </div>
    </section>
  );
}

// ── Profile Skeleton ─────────────────────────────────────────────

function ProfileSkeleton() {
  return (
    <div className="app-page page-stack pb-8 animate-pulse">
      {/* Back link */}
      <div className="skeleton w-28 h-4 rounded" />

      {/* Header */}
      <div className="card p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="skeleton w-48 h-8 rounded mb-3" />
            <div className="skeleton w-32 h-5 rounded-full mb-3" />
            <div className="flex gap-3">
              <div className="skeleton w-16 h-4 rounded" />
              <div className="skeleton w-16 h-4 rounded" />
              <div className="skeleton w-16 h-4 rounded" />
              <div className="skeleton w-16 h-4 rounded" />
            </div>
          </div>
          <div className="flex flex-col items-center gap-2">
            <div className="skeleton w-10 h-4 rounded" />
            <div className="skeleton w-14 h-14 rounded-md" />
            <div className="skeleton w-12 h-6 rounded" />
          </div>
        </div>
      </div>

      {/* Score bars */}
      <div className="card p-6">
        <div className="skeleton w-32 h-6 rounded mb-4" />
        <div className="space-y-3">
          <div className="skeleton-score-bar" />
          <div className="skeleton-score-bar" />
          <div className="skeleton-score-bar" />
        </div>
      </div>

      {/* Advanced metrics */}
      <div className="card p-6">
        <div className="skeleton w-40 h-6 rounded mb-4" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton h-16 rounded-lg" />
          ))}
        </div>
      </div>

      {/* Phase splits */}
      <div className="card p-6">
        <div className="skeleton w-28 h-6 rounded mb-4" />
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-8 rounded" />
          ))}
        </div>
      </div>
    </div>
  );
}
