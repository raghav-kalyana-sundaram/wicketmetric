/**
 * Venue drill-down: profile, trends, teams, similar venues, matches, leaders, performances.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  MapPin,
  Trophy,
  X,
  ChevronDown,
  ChevronUp,
  ChevronRight,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  BarChart,
  Bar,
  Legend,
} from "recharts";

import GradeBadge from "@/components/GradeBadge";
import Pagination from "@/components/Pagination";
import { PageLoading } from "@/components/Layout";
import { ScoreBarMini } from "@/components/ScoreBar";
import {
  useVenueProfile,
  useVenueTrends,
  useVenueTeams,
  useVenueSimilar,
  useVenueMatchesList,
  usePlayersAtVenue,
  useVenuePerformances,
} from "@/api/queries";
import {
  fmtInt,
  fmtSR,
  fmtPct,
  fmtScore,
  fmtEcon,
  fmtDate,
  fmtYearMonth,
  countryFlag,
} from "@/lib/format";
import { formatCombinedSummary } from "@/lib/scorecardMatchImpact";
import type { VenueProfile, VenuePlayerAtVenue } from "@/api/types";

function difficultyColour(score: number | null | undefined): string {
  if (score == null || isNaN(score)) return "#64748B";
  if (score < 30) return "#22C55E";
  if (score < 45) return "#06B6D4";
  if (score < 60) return "#F59E0B";
  if (score < 75) return "#F97316";
  return "#EF4444";
}

function difficultyLabel(score: number | null | undefined): string {
  if (score == null || isNaN(score)) return "Unknown";
  if (score < 30) return "Batting-friendly";
  if (score < 45) return "Balanced";
  if (score < 60) return "Moderate";
  if (score < 75) return "Challenging";
  return "Very Difficult";
}

export type VenueDetailSubTab =
  | "overview"
  | "trends"
  | "teams"
  | "similar"
  | "matches"
  | "leaders"
  | "performances";

const SUB_TABS: { id: VenueDetailSubTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "trends", label: "Trends" },
  { id: "teams", label: "Teams" },
  { id: "similar", label: "Similar" },
  { id: "matches", label: "Matches" },
  { id: "leaders", label: "Leaders" },
  { id: "performances", label: "Performances" },
];

function fmtDelta(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}

/** Recharts SVG attributes do not resolve Tailwind/CSS hsl(var(--token)); use explicit hex. */
const VENUE_CHART = {
  grid: "#3f3f46",
  axis: "#a1a1aa",
  lineInnings: "#38bdf8",
  lineParSr: "#f59e0b",
  barVenue: "#38bdf8",
  barFormat: "#71717a",
  barMedian: "#34d399",
  tooltip: {
    contentStyle: {
      backgroundColor: "#18181b",
      border: "1px solid #3f3f46",
      borderRadius: "8px",
      boxShadow: "0 10px 40px rgb(0 0 0 / 0.5)",
    },
    labelStyle: {
      color: "#fafafa",
      fontWeight: 600,
      marginBottom: 4,
    },
    itemStyle: { color: "#e4e4e7" },
  } as const,
};

function venuePerfRowToCombined(row: Record<string, unknown>) {
  const tid = String(row.match_id ?? "");
  const bi = row.bat_impact != null ? Number(row.bat_impact) : 0;
  const bo = row.bowl_impact != null ? Number(row.bowl_impact) : 0;
  const tt = row.total_impact != null ? Number(row.total_impact) : bi + bo;
  return {
    playerId: tid,
    name: "",
    batImpact: bi,
    bowlImpact: bo,
    totalImpact: tt,
    batRuns: row.bat_runs != null ? Number(row.bat_runs) : undefined,
    batBalls: row.bat_balls != null ? Number(row.bat_balls) : undefined,
    bowlWkts: row.bowl_wickets != null ? Number(row.bowl_wickets) : undefined,
    bowlRuns: row.bowl_runs_conceded != null ? Number(row.bowl_runs_conceded) : undefined,
    bowlBalls: row.bowl_balls != null ? Number(row.bowl_balls) : undefined,
  };
}

function formatVenueMatchTeams(teams: string[] | undefined): string {
  const t = (teams ?? []).map((x) => x.trim()).filter(Boolean);
  if (t.length >= 2) return `${t[0]} vs ${t[1]}`;
  if (t.length === 1) return t[0];
  return "—";
}

function venueTrendTooltipFormatter(value: number | string | undefined): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toFixed(1);
}

interface VenueDetailPanelProps {
  venueName: string;
  onClose: () => void;
}

export function VenueDetailPanel({ venueName, onClose }: VenueDetailPanelProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const vtabRaw = searchParams.get("vtab") as VenueDetailSubTab | null;
  const subTab: VenueDetailSubTab =
    vtabRaw && SUB_TABS.some((t) => t.id === vtabRaw) ? vtabRaw : "overview";

  const setSubTab = useCallback(
    (t: VenueDetailSubTab) => {
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          n.set("venue", venueName);
          n.set("vtab", t);
          return n;
        },
        { replace: true },
      );
    },
    [venueName, setSearchParams],
  );

  useEffect(() => {
    if (searchParams.get("venue") && !searchParams.get("vtab")) {
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          n.set("vtab", "overview");
          return n;
        },
        { replace: true },
      );
    }
  }, [venueName, searchParams, setSearchParams]);

  const {
    data: profile,
    isLoading: profileLoading,
    error: profileError,
  } = useVenueProfile(venueName, { exact: true });

  const { data: trendsData } = useVenueTrends(venueName, {}, { enabled: subTab === "trends" });
  const { data: teamsData } = useVenueTeams(venueName, {}, { enabled: subTab === "teams" });
  const { data: similarData } = useVenueSimilar(venueName, {}, { enabled: subTab === "similar" });
  const [matchPage, setMatchPage] = useState(1);
  const { data: matchesData } = useVenueMatchesList(
    venueName,
    { page: matchPage, perPage: 20 },
    { enabled: subTab === "matches" },
  );

  const [playerSearchRole, setPlayerSearchRole] = useState<"bat" | "bowl">("bat");
  const [playerAtVenuePage, setPlayerAtVenuePage] = useState(1);
  const [playerAtVenueSort, setPlayerAtVenueSort] = useState("venue_overall_score");
  const [playerAtVenueOrder, setPlayerAtVenueOrder] = useState<"asc" | "desc">("desc");
  const [leaderMinInnings, setLeaderMinInnings] = useState(1);
  const perPage = 15;

  const {
    data: playersData,
    isLoading: playersLoading,
    isError: playersError,
    error: playersQueryError,
    isFetching: playersFetching,
  } = usePlayersAtVenue(
    venueName,
    {
      role: playerSearchRole,
      minInnings: leaderMinInnings,
      sort: playerAtVenueSort,
      order: playerAtVenueOrder,
      page: playerAtVenuePage,
      perPage: perPage,
      exact: true,
    },
    { enabled: subTab === "leaders" },
  );

  const leadersBusy = playersLoading || (playersFetching && !playersData && !playersError);

  const [perfRole, setPerfRole] = useState<"bat" | "bowl">("bat");
  const [perfSort, setPerfSort] = useState("bat_impact");
  const [perfPage, setPerfPage] = useState(1);
  const { data: perfData, isLoading: perfLoading } = useVenuePerformances(
    venueName,
    {
      role: perfRole,
      sort: perfSort,
      page: perfPage,
      perPage: 15,
      exact: true,
    },
    { enabled: subTab === "performances" },
  );

  const detail = profile as VenueProfile | undefined;

  const phaseChartData = useMemo(() => {
    if (!detail?.phases_batting) return [];
    return ["powerplay", "middle", "death"].map((ph) => {
      const p = detail.phases_batting[ph] || {};
      return {
        phase: ph,
        venue: p.venue_sr ?? null,
        format: p.format_mean_sr ?? null,
        median: p.median_venue_sr ?? null,
      };
    });
  }, [detail]);

  if (profileLoading) return <PageLoading />;
  if (profileError || !detail) {
    return (
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-h3 text-text-primary">{venueName}</h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-sm">
            <X size={16} /> Close
          </button>
        </div>
        <p className="text-sm text-text-muted">Failed to load venue profile.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <button
        type="button"
        onClick={onClose}
        className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-primary transition-colors"
      >
        <ArrowLeft size={16} />
        Back to venue list
      </button>

      <div className="card p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-h2 text-text-primary flex items-center gap-2">
              <MapPin size={22} className="text-primary" />
              {venueName}
            </h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-secondary">
              <span>{fmtInt(detail.matches)} matches (baseline)</span>
              <span>·</span>
              <span>{fmtInt(detail.batting_innings)} batting innings in slice</span>
              {detail.small_sample ? (
                <span className="text-amber-500 text-xs">· Small sample (&lt;10 matches in slice)</span>
              ) : null}
              <span>·</span>
              <span
                style={{ color: difficultyColour(detail.difficulty_score) }}
                className="font-medium"
              >
                {difficultyLabel(detail.difficulty_score)}
              </span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
          <div className="text-center">
            <div className="font-score text-lg font-bold tabular-nums">{fmtInt(detail.matches)}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Matches</div>
          </div>
          <div className="text-center">
            <div className="font-score text-lg font-bold tabular-nums">{fmtSR(detail.avg_par_sr)}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Avg Par SR</div>
          </div>
          <div className="text-center">
            <div className="font-score text-lg font-bold tabular-nums">{fmtPct(detail.boundary_rate)}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Boundary Rate</div>
          </div>
          <div className="text-center">
            <div className="font-score text-lg font-bold tabular-nums">{fmtPct(detail.dot_pct)}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Dot %</div>
          </div>
          <div className="text-center">
            <div
              className="font-score text-lg font-bold tabular-nums"
              style={{ color: difficultyColour(detail.difficulty_score) }}
            >
              {fmtScore(detail.difficulty_score)}
            </div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">
              Difficulty (0–100)
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-surface-elevated pb-px overflow-x-auto">
        {SUB_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setSubTab(t.id)}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
              subTab === t.id
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {subTab === "overview" && (
        <div className="space-y-6">
          {detail.vs_world && (
            <div className="card p-4">
              <h3 className="text-h3 text-text-primary mb-3">Vs other venues (percentile)</h3>
              <p className="text-xs text-text-muted mb-3">
                Among venues with enough matches — where this ground sits on par SR, boundary rate, dot %, difficulty.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div>
                  Par SR pct:{" "}
                  <span className="font-score">{detail.vs_world.avg_par_sr_percentile ?? "—"}</span>
                </div>
                <div>
                  Boundary pct:{" "}
                  <span className="font-score">{detail.vs_world.boundary_rate_percentile ?? "—"}</span>
                </div>
                <div>
                  Dot % pct:{" "}
                  <span className="font-score">{detail.vs_world.dot_pct_percentile ?? "—"}</span>
                </div>
                <div>
                  Difficulty pct:{" "}
                  <span className="font-score">{detail.vs_world.difficulty_percentile ?? "—"}</span>
                </div>
              </div>
            </div>
          )}

          {detail.chase_defend && Object.keys(detail.chase_defend).length > 0 && (
            <div className="card p-4">
              <h3 className="text-h3 text-text-primary mb-3">Chase vs defend</h3>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
                <div>
                  Avg 1st inns:{" "}
                  <span className="font-score">{fmtScore(detail.chase_defend.avg_first_innings_score)}</span>
                </div>
                <div>
                  Avg 2nd inns:{" "}
                  <span className="font-score">{fmtScore(detail.chase_defend.avg_second_innings_score)}</span>
                </div>
                <div>
                  Win% batting 1st:{" "}
                  <span className="font-score">
                    {detail.chase_defend.win_pct_batting_first != null
                      ? `${fmtScore(detail.chase_defend.win_pct_batting_first)}%`
                      : "—"}
                  </span>
                </div>
              </div>
            </div>
          )}

          {phaseChartData.length > 0 && (
            <div className="card p-4">
              <h3 className="text-h3 text-text-primary mb-2">Phase SR — venue vs field</h3>
              <div className="h-64 w-full min-w-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={phaseChartData}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke={VENUE_CHART.grid}
                      opacity={0.45}
                    />
                    <XAxis
                      dataKey="phase"
                      tick={{ fontSize: 11, fill: VENUE_CHART.axis }}
                      stroke={VENUE_CHART.grid}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: VENUE_CHART.axis }}
                      stroke={VENUE_CHART.grid}
                    />
                    <Tooltip
                      {...VENUE_CHART.tooltip}
                      formatter={(value: number | string, name: string) => [
                        venueTrendTooltipFormatter(value),
                        name,
                      ]}
                    />
                    <Legend
                      wrapperStyle={{ paddingTop: 12, color: VENUE_CHART.axis }}
                      iconType="square"
                    />
                    <Bar dataKey="venue" name="This venue" fill={VENUE_CHART.barVenue} />
                    <Bar dataKey="format" name="Format mean" fill={VENUE_CHART.barFormat} />
                    <Bar dataKey="median" name="Median venue" fill={VENUE_CHART.barMedian} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}

      {subTab === "trends" && trendsData && (
        <div className="card p-4">
          <h3 className="text-h3 text-text-primary mb-1">Scoring trend</h3>
          <p className="text-xs text-text-muted mb-3 max-w-2xl">
            Rolling 3-match averages: each point uses the last three completed matches at this venue
            (mean team innings total and mean match par SR per match, ordered by date).
          </p>
          {trendsData.series.length === 0 ? (
            <p className="text-sm text-text-muted py-8 text-center">Not enough matches for a 3-match window.</p>
          ) : (
          <div className="h-72 w-full min-w-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={trendsData.series}
                margin={{ top: 8, right: 16, left: 0, bottom: 28 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke={VENUE_CHART.grid}
                  opacity={0.45}
                />
                <XAxis
                  type="category"
                  dataKey="period"
                  tick={{ fontSize: 10, fill: VENUE_CHART.axis }}
                  stroke={VENUE_CHART.grid}
                  tickLine={{ stroke: VENUE_CHART.grid }}
                  padding={{ left: 4, right: 8 }}
                  angle={-32}
                  textAnchor="end"
                  interval="preserveStartEnd"
                  minTickGap={28}
                />
                <YAxis
                  yAxisId="l"
                  tick={{ fontSize: 11, fill: VENUE_CHART.axis }}
                  stroke={VENUE_CHART.grid}
                  tickLine={{ stroke: VENUE_CHART.grid }}
                  domain={["auto", "auto"]}
                />
                <Tooltip
                  {...VENUE_CHART.tooltip}
                  formatter={(value: number | string, name: string) => [
                    venueTrendTooltipFormatter(value),
                    name,
                  ]}
                />
                <Legend
                  wrapperStyle={{ paddingTop: 16, color: VENUE_CHART.axis }}
                  iconType="line"
                  iconSize={14}
                />
                <Line
                  yAxisId="l"
                  type="monotone"
                  dataKey="mean_team_innings_score"
                  name="Team innings (3-match roll)"
                  stroke={VENUE_CHART.lineInnings}
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 5, strokeWidth: 2, stroke: "#fafafa", fill: VENUE_CHART.lineInnings }}
                  connectNulls
                />
                <Line
                  yAxisId="l"
                  type="monotone"
                  dataKey="mean_match_par_sr"
                  name="Match par SR (3-match roll)"
                  stroke={VENUE_CHART.lineParSr}
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 5, strokeWidth: 2, stroke: "#fafafa", fill: VENUE_CHART.lineParSr }}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          )}
        </div>
      )}

      {subTab === "teams" && teamsData && (
        <div className="card p-4 overflow-x-auto">
          <h3 className="text-h3 text-text-primary mb-3">Team record</h3>
          <table className="sortable-table">
            <thead>
              <tr>
                <th className="text-left">Team</th>
                <th className="text-right">Mat</th>
                <th className="text-right">W</th>
                <th className="text-right">L</th>
                <th className="text-right">Win%</th>
              </tr>
            </thead>
            <tbody>
              {teamsData.teams.map((t) => (
                <tr key={t.team}>
                  <td>{t.team}</td>
                  <td className="text-right font-score">{t.matches}</td>
                  <td className="text-right font-score">{t.wins}</td>
                  <td className="text-right font-score">{t.losses}</td>
                  <td className="text-right font-score">{t.win_pct}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {subTab === "similar" && similarData && (
        <div className="card p-4 grid gap-3 sm:grid-cols-2">
          {similarData.similar.map((s) => (
            <button
              key={s.venue}
              type="button"
              className="text-left p-3 rounded-lg border border-surface-elevated hover:border-primary transition-colors"
              onClick={() => {
                setSearchParams(
                  (prev) => {
                    const n = new URLSearchParams(prev);
                    n.set("venue", s.venue);
                    n.set("vtab", "overview");
                    return n;
                  },
                  { replace: true },
                );
              }}
            >
              <div className="font-medium text-text-primary">{s.venue}</div>
              <div className="text-xs text-text-muted mt-1">
                Similarity {s.similarity.toFixed(3)} · {s.matches} matches · par SR {fmtSR(s.avg_par_sr)}
              </div>
            </button>
          ))}
        </div>
      )}

      {subTab === "matches" && matchesData && (
        <div className="card p-4 overflow-x-auto">
          <h3 className="text-h3 text-text-primary mb-3">Matches</h3>
          <table className="sortable-table text-sm">
            <thead>
              <tr>
                <th className="text-left w-[9.5rem] whitespace-nowrap">When</th>
                <th className="text-left min-w-[200px]">Match</th>
                <th className="text-left min-w-[180px] max-w-[min(28rem,40vw)]">
                  Series
                </th>
                <th className="text-right w-24 whitespace-nowrap">Scorecard</th>
              </tr>
            </thead>
            <tbody>
              {matchesData.matches.map((m) => (
                <tr key={m.match_id}>
                  <td className="text-text-secondary tabular-nums whitespace-nowrap align-top pt-2.5">
                    {fmtYearMonth(m.date)}
                  </td>
                  <td className="font-medium text-text-primary align-top pt-2.5">
                    {formatVenueMatchTeams(m.teams)}
                  </td>
                  <td
                    className="text-text-secondary align-top pt-2.5 text-xs leading-snug max-w-[min(28rem,40vw)]"
                    title={m.event_name ?? undefined}
                  >
                    <span className="line-clamp-2">{m.event_name?.trim() || "—"}</span>
                  </td>
                  <td className="text-right align-top pt-2.5">
                    <Link
                      to={`/scorecards/${encodeURIComponent(m.match_id)}`}
                      className="text-primary hover:underline text-xs font-medium"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {matchesData.total_pages > 1 && (
            <Pagination
              page={matchPage}
              totalPages={matchesData.total_pages}
              onPageChange={setMatchPage}
              total={matchesData.total}
              perPage={20}
              showSummary
            />
          )}
        </div>
      )}

      {subTab === "leaders" && (
        <div className="card p-4">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <h3 className="text-h3 text-text-primary flex items-center gap-2">
              <Trophy size={18} className="text-gold" />
              Leaders at {venueName}
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={playerSearchRole}
                onChange={(e) => {
                  setPlayerSearchRole(e.target.value as "bat" | "bowl");
                  setPlayerAtVenuePage(1);
                  setPlayerAtVenueSort("venue_overall_score");
                  setPlayerAtVenueOrder("desc");
                }}
                className="filter-select text-xs"
                aria-label="Role"
              >
                <option value="bat">Batters</option>
                <option value="bowl">Bowlers</option>
              </select>
              <select
                value={String(leaderMinInnings)}
                onChange={(e) => {
                  setLeaderMinInnings(Math.max(1, parseInt(e.target.value, 10) || 1));
                  setPlayerAtVenuePage(1);
                }}
                className="filter-select text-xs"
                aria-label="Minimum innings or spells at venue"
              >
                <option value="1">1+ inns/sp</option>
                <option value="2">2+ inns/sp</option>
                <option value="3">3+ inns/sp</option>
                <option value="5">5+ inns/sp</option>
              </select>
              <select
                value={playerAtVenueSort}
                onChange={(e) => {
                  setPlayerAtVenueSort(e.target.value);
                  setPlayerAtVenueOrder("desc");
                  setPlayerAtVenuePage(1);
                }}
                className="filter-select text-xs min-w-[11rem]"
                aria-label="Sort by"
              >
                {playerSearchRole === "bat" ? (
                  <>
                    <option value="venue_overall_score">Overall (at venue)</option>
                    <option value="venue_score_acceleration">Acceleration (at venue)</option>
                    <option value="venue_score_power">Power (at venue)</option>
                    <option value="venue_score_control">Control (at venue)</option>
                    <option value="overall_score">Overall (career)</option>
                    <option value="runs">Runs (at venue)</option>
                    <option value="sr">SR (at venue)</option>
                    <option value="innings">Innings (at venue)</option>
                  </>
                ) : (
                  <>
                    <option value="venue_overall_score">Overall (at venue)</option>
                    <option value="venue_score_accuracy">Accuracy (at venue)</option>
                    <option value="venue_score_control">Control (at venue)</option>
                    <option value="venue_score_threat">Threat (at venue)</option>
                    <option value="overall_score">Overall (career)</option>
                    <option value="wickets">Wickets (at venue)</option>
                    <option value="economy">Economy (at venue)</option>
                    <option value="spells">Spells (at venue)</option>
                  </>
                )}
              </select>
              <button
                type="button"
                onClick={() =>
                  setPlayerAtVenueOrder((o) => (o === "desc" ? "asc" : "desc"))
                }
                className="btn-ghost btn-sm text-xs"
                aria-label={`Sort ${playerAtVenueOrder === "desc" ? "descending" : "ascending"}`}
              >
                {playerAtVenueOrder === "desc" ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              </button>
            </div>
          </div>

          <p className="text-xs text-text-muted mb-3 max-w-3xl">
            Ratings in <span className="text-text-secondary">OVR / ACC / POW / CTL</span> (bat) or{" "}
            <span className="text-text-secondary">OVR / ACC / CTL / THR</span> (bowl) are averages from
            innings or spells <em>at this venue</em> — same 0–100 scale as Rankings. Career grade is shown
            for context.
          </p>

          {playersError ? (
            <div className="rounded-lg border border-danger/35 bg-danger/10 px-4 py-3 text-sm text-text-secondary">
              {playersQueryError instanceof Error
                ? playersQueryError.message
                : "Could not load venue leaders."}
            </div>
          ) : leadersBusy ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="skeleton h-10 rounded" />
              ))}
            </div>
          ) : playersData && playersData.total === 0 ? (
            <p className="text-sm text-text-muted italic py-6 text-center">
              No players meet the minimum sample at this venue. Try lowering the minimum innings/spells.
            </p>
          ) : playersData ? (
            <>
              <div className="overflow-x-auto">
                <table className="sortable-table text-xs md:text-sm">
                  <thead>
                    <tr>
                      <th className="text-right w-10">#</th>
                      <th className="text-left min-w-[120px]">Player</th>
                      <th className="text-left">Ctry</th>
                      {playerSearchRole === "bat" ? (
                        <>
                          <th className="text-right">Inn</th>
                          <th className="text-right">Runs</th>
                          <th className="text-right">SR</th>
                          <th className="text-right" title="Overall at venue (mean per innings)">
                            OVR
                          </th>
                          <th className="text-right" title="Acceleration at venue">
                            ACC
                          </th>
                          <th className="text-right" title="Power at venue">
                            POW
                          </th>
                          <th className="text-right" title="Control at venue">
                            CTL
                          </th>
                          <th className="text-right">ΔSR</th>
                          <th className="text-left">Last</th>
                          <th className="text-right">Grd</th>
                        </>
                      ) : (
                        <>
                          <th className="text-right">Sp</th>
                          <th className="text-right">W</th>
                          <th className="text-right">Econ</th>
                          <th className="text-right" title="Overall at venue">
                            OVR
                          </th>
                          <th className="text-right" title="Accuracy at venue">
                            ACC
                          </th>
                          <th className="text-right" title="Control at venue">
                            CTL
                          </th>
                          <th className="text-right" title="Threat at venue">
                            THR
                          </th>
                          <th className="text-right">ΔEcon</th>
                          <th className="text-left">Last</th>
                          <th className="text-right">Grd</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {((playersData.players ?? []) as unknown as VenuePlayerAtVenue[]).map((p, i) => {
                      const rank = (playerAtVenuePage - 1) * perPage + i + 1;
                      return (
                        <tr key={p.id || i}>
                          <td className="text-right text-text-muted font-score tabular-nums">{rank}</td>
                          <td>
                            <Link to={`/player/${p.id}`} className="text-primary hover:underline">
                              {p.name}
                            </Link>
                          </td>
                          <td className="text-text-secondary">
                            {countryFlag(p.country)} {p.country}
                          </td>
                          {playerSearchRole === "bat" ? (
                            <>
                              <td className="text-right font-score">{fmtInt(p.innings ?? 0)}</td>
                              <td className="text-right font-score">{fmtInt(p.runs ?? 0)}</td>
                              <td className="text-right font-score">{fmtSR(p.sr ?? null)}</td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={
                                      p.venue_overall_score ?? p.overall_score ?? null
                                    }
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_overall_score ?? p.overall_score ?? null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={
                                      p.venue_score_acceleration ??
                                      p.score_acceleration ??
                                      null
                                    }
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_score_acceleration ??
                                        p.score_acceleration ??
                                        null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={p.venue_score_power ?? p.score_power ?? null}
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_score_power ?? p.score_power ?? null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={
                                      p.venue_score_control ?? p.score_control ?? null
                                    }
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_score_control ?? p.score_control ?? null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right font-score text-xs">
                                {fmtDelta(p.sr_delta ?? null)}
                              </td>
                              <td className="text-text-muted">{p.last_played_at_venue ?? "—"}</td>
                              <td className="text-right">
                                <GradeBadge grade={p.overall_grade} size="xs" />
                              </td>
                            </>
                          ) : (
                            <>
                              <td className="text-right font-score">{fmtInt(p.spells ?? 0)}</td>
                              <td className="text-right font-score">{fmtInt(p.wickets ?? 0)}</td>
                              <td className="text-right font-score">{fmtEcon(p.economy ?? null)}</td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={
                                      p.venue_overall_score ?? p.overall_score ?? null
                                    }
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_overall_score ?? p.overall_score ?? null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={
                                      p.venue_score_accuracy ?? p.score_accuracy ?? null
                                    }
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_score_accuracy ?? p.score_accuracy ?? null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={
                                      p.venue_score_control ?? p.score_control ?? null
                                    }
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_score_control ?? p.score_control ?? null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <ScoreBarMini
                                    value={p.venue_score_threat ?? p.score_threat ?? null}
                                    width={36}
                                  />
                                  <span className="text-[10px] tabular-nums text-text-muted w-7">
                                    {fmtScore(
                                      p.venue_score_threat ?? p.score_threat ?? null,
                                    )}
                                  </span>
                                </div>
                              </td>
                              <td className="text-right font-score text-xs">
                                {fmtDelta(p.economy_delta ?? null)}
                              </td>
                              <td className="text-text-muted">{p.last_played_at_venue ?? "—"}</td>
                              <td className="text-right">
                                <GradeBadge grade={p.overall_grade} size="xs" />
                              </td>
                            </>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {playersData.total_pages > 1 && (
                <Pagination
                  page={playerAtVenuePage}
                  totalPages={playersData.total_pages}
                  onPageChange={setPlayerAtVenuePage}
                  total={playersData.total}
                  perPage={perPage}
                  showSummary
                />
              )}
            </>
          ) : null}
        </div>
      )}

      {subTab === "performances" && (
        <div className="card p-4">
          <p className="text-xs text-text-muted mb-3 max-w-3xl">
            Same <strong className="text-text-secondary font-medium">match impact</strong> as player
            profiles and the scorecard Match impact tab (combined bat + bowl per match). Only matches with
            a scorecard file are listed.
          </p>
          <div className="flex flex-wrap gap-2 mb-3">
            <select
              value={perfRole}
              onChange={(e) => {
                setPerfRole(e.target.value as "bat" | "bowl");
                setPerfSort(e.target.value === "bat" ? "bat_impact" : "bowl_impact");
                setPerfPage(1);
              }}
              className="filter-select text-xs"
            >
              <option value="bat">Batting</option>
              <option value="bowl">Bowling</option>
            </select>
            {perfRole === "bat" ? (
              <select
                value={perfSort}
                onChange={(e) => setPerfSort(e.target.value)}
                className="filter-select text-xs min-w-[10rem]"
              >
                <option value="bat_impact">Bat impact</option>
                <option value="total_impact">Total impact</option>
                <option value="bowl_impact">Bowl impact</option>
                <option value="runs">Runs (match)</option>
                <option value="acc_leveraged_rva">Leveraged RVA</option>
              </select>
            ) : (
              <select
                value={perfSort}
                onChange={(e) => setPerfSort(e.target.value)}
                className="filter-select text-xs min-w-[10rem]"
              >
                <option value="bowl_impact">Bowl impact</option>
                <option value="total_impact">Total impact</option>
                <option value="bat_impact">Bat impact</option>
                <option value="wickets">Wickets</option>
                <option value="economy">Economy</option>
              </select>
            )}
          </div>
          {perfLoading ? (
            <PageLoading />
          ) : perfData && perfData.performances.length === 0 ? (
            <p className="text-text-muted text-sm">
              No qualifying scorecard performances at this venue (need scorecard JSON and the same
              minimum balls as Match impact).
            </p>
          ) : perfData ? (
            <>
              <div className="overflow-x-auto text-xs md:text-sm">
                <table className="sortable-table min-w-[720px]">
                  <thead>
                    <tr>
                      <th className="text-left">Player</th>
                      <th className="text-left whitespace-nowrap">Date</th>
                      <th className="text-left min-w-[140px]">Match</th>
                      <th className="text-left">Performance</th>
                      <th className="text-right">Total</th>
                      <th className="text-right">Bat</th>
                      <th className="text-right">Bowl</th>
                      <th className="text-left">vs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perfData.performances.map((row: Record<string, unknown>, i: number) => {
                      const mid = String(row.match_id ?? "");
                      const ev =
                        row.event_name != null ? String(row.event_name).trim() : "";
                      const vn = row.venue != null ? String(row.venue).trim() : "";
                      const title = ev || vn || mid;
                      const ti = row.total_impact != null ? Number(row.total_impact) : NaN;
                      const bi = row.bat_impact != null ? Number(row.bat_impact) : 0;
                      const bo = row.bowl_impact != null ? Number(row.bowl_impact) : 0;
                      const vs =
                        perfRole === "bat"
                          ? String(row.opposition ?? "—")
                          : String(row.opposition ?? "—");
                      return (
                        <tr key={`${mid}-${i}`}>
                          <td>
                            <Link
                              to={`/player/${row.player_id}`}
                              className="text-primary hover:underline"
                            >
                              {String(row.player_name ?? "")}
                            </Link>
                          </td>
                          <td className="text-text-secondary whitespace-nowrap">
                            {fmtDate(String(row.date ?? ""))}
                          </td>
                          <td>
                            <Link
                              to={`/scorecards/${encodeURIComponent(mid)}`}
                              className="text-primary hover:underline underline-offset-2 decoration-primary/40 inline-flex items-center gap-1 max-w-[16rem]"
                            >
                              <span className="line-clamp-2 text-left">{title}</span>
                              <ChevronRight size={12} className="shrink-0 opacity-60" />
                            </Link>
                          </td>
                          <td className="text-text-secondary max-w-[13rem]">
                            {formatCombinedSummary(venuePerfRowToCombined(row))}
                          </td>
                          <td className="text-right font-medium tabular-nums text-text-primary">
                            {!Number.isNaN(ti) ? ti.toFixed(2) : "—"}
                          </td>
                          <td className="text-right tabular-nums text-text-secondary">
                            {bi > 0 ? bi.toFixed(2) : "—"}
                          </td>
                          <td className="text-right tabular-nums text-text-secondary">
                            {bo > 0 ? bo.toFixed(2) : "—"}
                          </td>
                          <td className="text-text-secondary line-clamp-2 max-w-[9rem]">{vs}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {perfData.total_pages > 1 && (
                <Pagination
                  page={perfPage}
                  totalPages={perfData.total_pages}
                  onPageChange={setPerfPage}
                  total={perfData.total}
                  perPage={15}
                  showSummary
                />
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
