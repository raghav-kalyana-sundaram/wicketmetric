/**
 * Teams — horizontal team picker + detail: recent results (W/L/NR), squad, best match-impact plays.
 * Respects the global format toggle (Men/Women × T20I/IPL).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import PageIntro from "@/components/PageIntro";
import CrossLinkBar from "@/components/CrossLinkBar";
import { PageLoading, PageError } from "@/components/Layout";
import { useFormat } from "@/api/FormatContext";
import { FORMAT_LABELS } from "@/api/formatConstants";
import {
  useTeamChips,
  useTeamComposition,
  useTeamDetail,
  useTeamProficientPlayers,
  useMatchImpactPerformances,
} from "@/api/queries";
import { fmtDateShort } from "@/lib/format";
import type { CrossLink } from "@/components/CrossLinkBar";
import type {
  TeamRecentMatchRow,
  TeamProficientPlayerRow,
  TeamProficientPlayersResponse,
  MatchImpactPerformancesResponse,
  TeamCompositionBattingRow,
  TeamCompositionBowlingRow,
} from "@/api/types";

const CROSS_LINKS: CrossLink[] = [
  { label: "Scorecards", to: "/scorecards" },
  { label: "Team Builder", to: "/team-builder" },
  { label: "Rankings", to: "/rankings" },
];

/** Recharts SVG attributes do not resolve CSS variables; use explicit hex. */
const TEAM_COMP_CHART = {
  grid: "#3f3f46",
  axis: "#a1a1aa",
  tooltip: {
    contentStyle: {
      backgroundColor: "#18181b",
      border: "1px solid #3f3f46",
      borderRadius: "8px",
      boxShadow: "0 10px 40px rgb(0 0 0 / 0.5)",
    },
    labelStyle: { color: "#fafafa", fontWeight: 600, marginBottom: 4 },
    itemStyle: { color: "#e4e4e7" },
  } as const,
};

const BAT_AREA_SERIES = [
  { key: "extras", name: "Extras", color: "#52525b" },
  { key: "running", name: "Other off the bat", color: "#78716c" },
  { key: "ones", name: "Ones", color: "#0ea5e9" },
  { key: "twos", name: "Twos", color: "#6366f1" },
  { key: "threes", name: "Threes", color: "#a855f7" },
  { key: "fours", name: "Fours", color: "#f59e0b" },
  { key: "sixes", name: "Sixes", color: "#ef4444" },
] as const;

const BOWL_AREA_SERIES = [
  { key: "other", name: "Other", color: "#52525b" },
  { key: "run_out", name: "Run out / retired", color: "#78716c" },
  { key: "stumped", name: "Stumped", color: "#0ea5e9" },
  { key: "lbw", name: "LBW", color: "#a855f7" },
  { key: "caught", name: "Caught", color: "#f59e0b" },
  { key: "bowled", name: "Bowled / C&B / hit wicket", color: "#ef4444" },
] as const;

function pct100(share: number): number {
  return Math.round(share * 1000) / 10;
}

function resultStyles(code: string): string {
  const c = code.toUpperCase();
  if (c === "W") {
    return "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/35 dark:text-emerald-300 dark:ring-emerald-400/25";
  }
  if (c === "L") {
    return "bg-rose-500/12 text-rose-700 ring-1 ring-rose-500/30 dark:text-rose-300 dark:ring-rose-400/25";
  }
  if (c === "T") {
    return "bg-amber-500/12 text-amber-800 ring-1 ring-amber-500/30 dark:text-amber-200 dark:ring-amber-400/20";
  }
  return "bg-slate-500/10 text-text-secondary ring-1 ring-surface-elevated";
}

function ResultChip({ code }: { code: string }) {
  return (
    <span
      className={`inline-flex h-8 min-w-[2rem] items-center justify-center rounded-lg px-2 font-score text-sm font-semibold tabular-nums ${resultStyles(code)}`}
      title={
        code === "W"
          ? "Win"
          : code === "L"
            ? "Loss"
            : code === "T"
              ? "Tie"
              : "No result / unknown"
      }
    >
      {code}
    </span>
  );
}

function LatestMatchHero({
  selectedTeam,
  row,
}: {
  selectedTeam: string;
  row: TeamRecentMatchRow;
}) {
  const opponent = row.opposition?.trim() || "Unknown opponent";
  const when = row.date ? fmtDateShort(row.date) : "—";
  const r = row.result.toUpperCase();
  const summary =
    r === "W"
      ? `Beat ${opponent}.`
      : r === "L"
        ? `Lost to ${opponent}.`
        : r === "T"
          ? `Tied with ${opponent}.`
          : `No result vs ${opponent}.`;

  return (
    <section
      className="mt-6 card p-5 sm:p-6"
      aria-labelledby="teams-latest-match-heading"
    >
      <h3
        id="teams-latest-match-heading"
        className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3"
      >
        Latest match
      </h3>
      <p className="text-xs text-text-muted mb-4">
        {when}
        {row.venue ? (
          <>
            {" "}
            · <span className="text-text-secondary">{row.venue}</span>
          </>
        ) : null}
      </p>
      <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted mb-1">
        Match-up
      </p>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-lg sm:text-xl font-heading font-semibold tracking-tight text-text-primary">
        <span className="text-primary">{selectedTeam}</span>
        <span className="text-sm font-normal text-text-muted sm:text-base">vs</span>
        <span>{opponent}</span>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <ResultChip code={row.result} />
        <span className="text-sm text-text-secondary">{summary}</span>
        <Link
          to={`/scorecards/${encodeURIComponent(row.match_id)}`}
          className="inline-flex items-center gap-0.5 text-sm font-medium text-primary hover:underline ml-auto sm:ml-0"
        >
          Open scorecard
          <ChevronRight size={14} aria-hidden />
        </Link>
      </div>
    </section>
  );
}

function roleLabel(role: string): string {
  if (role === "allrounder") return "All-rounder";
  if (role === "bowler") return "Bowler";
  return "Batter";
}

function roleBadgeClass(role: string): string {
  if (role === "allrounder") {
    return "bg-teal-500/12 text-teal-800 ring-teal-500/25 dark:text-teal-200";
  }
  if (role === "bowler") {
    return "bg-violet-500/12 text-violet-800 ring-violet-500/25 dark:text-violet-200";
  }
  return "bg-sky-500/12 text-sky-900 ring-sky-500/25 dark:text-sky-100";
}

function ProficientRow({
  row,
  rank,
}: {
  row: TeamProficientPlayerRow;
  rank: number;
}) {
  const bat = row.war_batting != null ? row.war_batting.toFixed(2) : "—";
  const bowl = row.war_bowling != null ? row.war_bowling.toFixed(2) : "—";
  const prof =
    row.proficiency_score != null ? row.proficiency_score.toFixed(2) : "—";
  return (
    <tr className="border-b border-surface-elevated/50 last:border-0">
      <td className="py-2.5 pr-2 tabular-nums text-text-muted">{rank}</td>
      <td className="py-2.5 pr-3">
        <Link
          to={`/player/${encodeURIComponent(row.player_id)}`}
          className="font-medium text-primary hover:underline"
        >
          {row.player_name || row.player_id}
        </Link>
      </td>
      <td className="py-2.5 pr-3">
        <span
          className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${roleBadgeClass(row.role)}`}
        >
          {roleLabel(row.role)}
        </span>
      </td>
      <td className="py-2.5 text-right font-score tabular-nums text-sm">{bat}</td>
      <td className="py-2.5 text-right font-score tabular-nums text-sm">{bowl}</td>
      <td className="py-2.5 text-right text-xs tabular-nums text-text-muted">
        {row.team_innings}i / {row.team_spells}s
      </td>
      <td className="py-2.5 text-right font-score tabular-nums text-sm font-medium">
        {prof}
      </td>
    </tr>
  );
}

function RecentRow({ row }: { row: TeamRecentMatchRow }) {
  const vs = row.opposition?.trim() || "—";
  const when = row.date ? fmtDateShort(row.date) : "—";
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-surface-elevated/50 py-2.5 text-sm last:border-0">
      <ResultChip code={row.result} />
      <span className="text-text-muted tabular-nums">{when}</span>
      <span className="text-text-primary">
        vs <span className="font-medium">{vs}</span>
      </span>
      {row.venue ? (
        <span className="text-xs text-text-muted truncate max-w-[12rem]">
          {row.venue}
        </span>
      ) : null}
      <Link
        to={`/scorecards/${encodeURIComponent(row.match_id)}`}
        className="ml-auto inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline shrink-0"
      >
        Scorecard
        <ChevronRight size={12} aria-hidden />
      </Link>
    </li>
  );
}

type CompositionMode = "runs" | "wickets";

function TeamCompositionSection({
  mode,
  onModeChange,
  isLoading,
  isError,
  error,
  batting,
  bowling,
  singlesBreakdown,
}: {
  mode: CompositionMode;
  onModeChange: (m: CompositionMode) => void;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  batting: TeamCompositionBattingRow[];
  bowling: TeamCompositionBowlingRow[];
  singlesBreakdown: boolean;
}): JSX.Element {
  const batData = useMemo(() => {
    return batting.map((r) => {
      let running = r.share_running;
      let o = r.share_ones;
      let t2 = r.share_twos;
      let t3 = r.share_threes;
      if (!singlesBreakdown) {
        running += o + t2 + t3;
        o = 0;
        t2 = 0;
        t3 = 0;
      }
      return {
        label: r.label,
        extras: pct100(r.share_extras),
        running: pct100(running),
        ones: pct100(o),
        twos: pct100(t2),
        threes: pct100(t3),
        fours: pct100(r.share_fours),
        sixes: pct100(r.share_sixes),
      };
    });
  }, [batting, singlesBreakdown]);

  const bowlData = useMemo(
    () =>
      bowling.map((r) => ({
        label: r.label,
        bowled: pct100(r.share_bowled),
        caught: pct100(r.share_caught),
        lbw: pct100(r.share_lbw),
        run_out: pct100(r.share_run_out),
        stumped: pct100(r.share_stumped),
        other: pct100(r.share_other),
      })),
    [bowling],
  );

  const batSeries = useMemo(
    () =>
      singlesBreakdown
        ? BAT_AREA_SERIES
        : BAT_AREA_SERIES.filter((s) => !["ones", "twos", "threes"].includes(s.key)),
    [singlesBreakdown],
  );

  const fmtTip = (v: number | string | undefined) => {
    if (v === undefined || v === "") return "—";
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? `${n}%` : "—";
  };

  const activeData = mode === "runs" ? batData : bowlData;
  const activeSeries = mode === "runs" ? batSeries : BOWL_AREA_SERIES;

  if (isError) {
    return (
      <section className="mt-10" aria-labelledby="teams-composition-heading">
        <h3
          id="teams-composition-heading"
          className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1"
        >
          Composition over time
        </h3>
        <div
          className="rounded-xl border border-rose-500/25 bg-rose-500/5 px-4 py-3 text-sm text-rose-900 dark:text-rose-100"
          role="alert"
        >
          {(error as Error)?.message ?? "Could not load team composition."}
        </div>
      </section>
    );
  }

  const emptyRuns = mode === "runs" && !batData.length;
  const emptyWkts = mode === "wickets" && !bowlData.length;

  return (
    <section className="mt-10" aria-labelledby="teams-composition-heading">
      <h3
        id="teams-composition-heading"
        className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1"
      >
        Composition over time
      </h3>
      <p className="text-xs text-text-muted mb-4 max-w-3xl">
        Each point is one team innings, oldest → newest left to right.{" "}
        <span className="text-text-secondary">Runs</span> splits team total into boundaries,
        singles activity, other off-the-bat runs, and extras.{" "}
        <span className="text-text-secondary">Wickets</span> splits dismissals credited while this
        side is fielding.
      </p>

      <div className="flex flex-wrap gap-2 mb-4" role="tablist" aria-label="Composition mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "runs"}
          onClick={() => onModeChange("runs")}
          className={`rounded-lg border px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition-colors ${
            mode === "runs"
              ? "border-primary bg-primary/10 text-primary ring-1 ring-primary/25"
              : "border-surface-elevated text-text-secondary hover:text-text-primary"
          }`}
        >
          Runs
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "wickets"}
          onClick={() => onModeChange("wickets")}
          className={`rounded-lg border px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition-colors ${
            mode === "wickets"
              ? "border-primary bg-primary/10 text-primary ring-1 ring-primary/25"
              : "border-surface-elevated text-text-secondary hover:text-text-primary"
          }`}
        >
          Wickets
        </button>
      </div>

      {isLoading && !activeData.length ? (
        <p className="text-sm text-text-muted">Loading chart…</p>
      ) : null}

      {emptyRuns || emptyWkts ? (
        <p className="text-sm text-text-secondary">
          {mode === "runs"
            ? "No batting innings rows for this team in the current window."
            : "No wicket dismissals recorded for this team while bowling in the current window."}
        </p>
      ) : null}

      {!emptyRuns && !emptyWkts && activeData.length > 0 ? (
        <div className="card p-4 sm:p-5">
          <div className="h-80 w-full min-h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={activeData} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={TEAM_COMP_CHART.grid} opacity={0.5} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: TEAM_COMP_CHART.axis, fontSize: 10 }}
                  interval="preserveStartEnd"
                  angle={-32}
                  textAnchor="end"
                  height={58}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: TEAM_COMP_CHART.axis, fontSize: 10 }}
                  tickFormatter={(v) => `${v}%`}
                  width={44}
                />
                <RechartsTooltip
                  {...TEAM_COMP_CHART.tooltip}
                  formatter={(value: number | string) => [fmtTip(value), ""]}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {activeSeries.map((s) => (
                  <Area
                    key={s.key}
                    type="monotone"
                    dataKey={s.key}
                    name={s.name}
                    stackId="comp"
                    stroke={s.color}
                    fill={s.color}
                    fillOpacity={0.82}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
          {!singlesBreakdown && mode === "runs" ? (
            <p className="text-[11px] text-text-muted mt-3">
              Singles (1–3) are rolled into &ldquo;Other off the bat&rdquo; when the dataset does
              not expose per-run tallies for this format.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export default function Teams(): JSX.Element {
  const { format } = useFormat();
  const formatLabel = FORMAT_LABELS[format];
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedTeam, setSelectedTeam] = useState("");
  const [compositionMode, setCompositionMode] = useState<CompositionMode>("runs");
  const { data: chipsData, isLoading: chipsLoading, isError: chipsError, error: chipsErr } =
    useTeamChips();

  const teamsList = chipsData?.teams ?? [];

  useEffect(() => {
    if (!teamsList.length) return;
    const fromUrl = searchParams.get("team")?.trim() ?? "";
    if (fromUrl && teamsList.includes(fromUrl)) {
      setSelectedTeam(fromUrl);
      return;
    }
    if (fromUrl && !teamsList.includes(fromUrl)) {
      const fallback = teamsList[0];
      setSelectedTeam(fallback);
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          n.set("team", fallback);
          return n;
        },
        { replace: true },
      );
      return;
    }
    setSelectedTeam((prev) =>
      prev && teamsList.includes(prev) ? prev : teamsList[0],
    );
  }, [teamsList, searchParams, setSearchParams]);

  const selectTeam = useCallback(
    (name: string) => {
      setSelectedTeam(name);
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          n.set("team", name);
          return n;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const {
    data: detail,
    isLoading: detailLoading,
    isError: detailError,
    error: detailErr,
    isFetching: detailFetching,
  } = useTeamDetail(selectedTeam || null, { recentLimit: 20 });

  const {
    data: composition,
    isLoading: compositionLoading,
    isError: compositionError,
    error: compositionErr,
  } = useTeamComposition(selectedTeam || null, { limit: 40 }, {
    enabled: !!selectedTeam.trim() && !detailError,
  });

  const impactParams = useMemo(
    () => ({
      team: selectedTeam || undefined,
      per_page: 12,
      page: 1,
      discipline: "combined" as const,
      order: "desc" as const,
      match_tier: "all" as const,
    }),
    [selectedTeam],
  );

  const { data: proficientDataRaw, isLoading: proficientLoading } =
    useTeamProficientPlayers(selectedTeam || null, { limit: 24 }, { enabled: !!selectedTeam.trim() });

  const { data: playsDataRaw, isLoading: playsLoading } = useMatchImpactPerformances(
    impactParams,
    { enabled: !!selectedTeam.trim() },
  );

  const proficientData = proficientDataRaw as TeamProficientPlayersResponse | undefined;
  const playsData = playsDataRaw as MatchImpactPerformancesResponse | undefined;

  const { latestMatch, earlierMatches, allMatches } = useMemo(() => {
    const all = detail?.recent_matches ?? [];
    return {
      allMatches: all,
      latestMatch: all[0],
      earlierMatches: all.slice(1),
    };
  }, [detail?.recent_matches]);

  if (chipsLoading && !chipsData) {
    return <PageLoading />;
  }

  if (chipsError) {
    return <PageError message={(chipsErr as Error)?.message} />;
  }

  if (!teamsList.length) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <PageIntro
          title="Teams"
          subtitle={`No sides found in ${formatLabel} yet. Try another dataset above.`}
        />
        <CrossLinkBar links={CROSS_LINKS} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <PageIntro
        title="Teams"
        subtitle={`Pick a side to see recent results, squad volume, and stand-out performances in ${formatLabel}. Use the dataset bar above to switch Men / Women or T20 / IPL.`}
      />

      <CrossLinkBar links={CROSS_LINKS} className="mb-6" />

      {/* Horizontal team chips */}
      <div
        className="flex gap-2 overflow-x-auto pb-3 pt-1 snap-x snap-mandatory"
        role="tablist"
        aria-label="Teams"
      >
        {teamsList.map((name) => {
          const active = name === selectedTeam;
          return (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => selectTeam(name)}
              className={`snap-start shrink-0 rounded-xl border px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "border-primary bg-primary/10 text-primary ring-1 ring-primary/25"
                  : "border-surface-elevated bg-surface/60 text-text-secondary hover:border-slate-300/80 hover:text-text-primary dark:border-white/10 dark:hover:border-white/20"
              }`}
            >
              {name}
            </button>
          );
        })}
      </div>

      {detailError && (
        <div
          className="mt-4 rounded-xl border border-rose-500/25 bg-rose-500/5 px-4 py-3 text-sm text-rose-900 dark:text-rose-100"
          role="alert"
        >
          {(detailErr as Error)?.message ?? "Could not load this team in the current format."}
        </div>
      )}

      {!detailError && selectedTeam && (
        <>
          <header className="mt-6 border-b border-surface-elevated pb-3">
            <h2 className="page-title text-xl sm:text-2xl">{detail?.display_name ?? selectedTeam}</h2>
            {detailFetching && detail && (
              <p className="text-xs text-text-muted mt-1">Refreshing…</p>
            )}
          </header>

          {detailLoading && !detail ? (
            <div className="mt-8 text-text-muted text-sm">Loading team…</div>
          ) : (
            <>
              {latestMatch ? (
                <LatestMatchHero selectedTeam={selectedTeam} row={latestMatch} />
              ) : null}

              <div className="mt-6 grid gap-8 lg:grid-cols-2">
              {/* Earlier matches (latest shown above) */}
              <section aria-labelledby="teams-recent-heading">
                <h3
                  id="teams-recent-heading"
                  className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3"
                >
                  {latestMatch ? "Earlier matches" : "Recent"}
                </h3>
                {latestMatch ? (
                  earlierMatches.length > 0 ? (
                    <ul className="card divide-y divide-surface-elevated/60 px-3">
                      {earlierMatches.map((row) => (
                        <RecentRow key={row.match_id} row={row} />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-text-secondary">
                      No older matches in this window (only the latest is shown above).
                    </p>
                  )
                ) : allMatches.length > 0 ? (
                  <ul className="card divide-y divide-surface-elevated/60 px-3">
                    {allMatches.map((row) => (
                      <RecentRow key={row.match_id} row={row} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-text-secondary">
                    No finished rows in the slice yet.
                  </p>
                )}
              </section>

              {/* Current squad */}
              <section aria-labelledby="teams-squad-heading">
                <h3
                  id="teams-squad-heading"
                  className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3"
                >
                  Current team
                </h3>
                <div className="card p-4 space-y-4">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-text-muted mb-2">
                      Batters (by innings in dataset)
                    </div>
                    <ul className="flex flex-wrap gap-x-3 gap-y-1.5 text-sm">
                      {(detail?.squad_batters ?? []).map((p) => (
                        <li key={p.player_id}>
                          <Link
                            to={`/player/${encodeURIComponent(p.player_id)}`}
                            className="text-primary hover:underline"
                          >
                            {p.player_name || p.player_id}
                          </Link>
                          <span className="text-text-muted text-xs tabular-nums ml-1">
                            ({p.innings})
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-text-muted mb-2">
                      Bowlers (by spells)
                    </div>
                    {(detail?.squad_bowlers ?? []).length ? (
                      <ul className="flex flex-wrap gap-x-3 gap-y-1.5 text-sm">
                        {detail!.squad_bowlers.map((p) => (
                          <li key={p.player_id}>
                            <Link
                              to={`/player/${encodeURIComponent(p.player_id)}`}
                              className="text-primary hover:underline"
                            >
                              {p.player_name || p.player_id}
                            </Link>
                            <span className="text-text-muted text-xs tabular-nums ml-1">
                              ({p.spells})
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-text-muted">No bowling rows for this side.</p>
                    )}
                  </div>
                </div>
              </section>
              </div>
            </>
          )}

          <TeamCompositionSection
            mode={compositionMode}
            onModeChange={setCompositionMode}
            isLoading={compositionLoading}
            isError={compositionError}
            error={compositionErr}
            batting={composition?.batting ?? []}
            bowling={composition?.bowling ?? []}
            singlesBreakdown={composition?.batting_singles_breakdown ?? false}
          />

          {/* Proficient players — career WAR for this side (not blocked on match list) */}
          <section className="mt-10" aria-labelledby="teams-proficient-heading">
            <h3
              id="teams-proficient-heading"
              className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1"
            >
              Most proficient players
            </h3>
            <p className="text-xs text-text-muted mb-4 max-w-3xl">
              Ranked from career{" "}
              <span className="text-text-secondary">batting / bowling WAR</span> for players with
              innings or spells for this team. Role tags use team volume: both disciplines above
              thresholds counts as an{" "}
              <span className="text-text-secondary">all-rounder</span>.
            </p>
            {proficientLoading && !proficientData?.players?.length ? (
              <p className="text-sm text-text-muted">Loading players…</p>
            ) : proficientData?.players?.length ? (
              <div className="card overflow-x-auto">
                <table className="w-full min-w-[32rem] text-sm">
                  <thead>
                    <tr className="border-b border-surface-elevated text-left text-[10px] uppercase tracking-wider text-text-muted">
                      <th className="py-2 pr-2 font-medium w-8">#</th>
                      <th className="py-2 pr-3 font-medium">Player</th>
                      <th className="py-2 pr-3 font-medium">Role</th>
                      <th className="py-2 text-right font-medium">Bat WAR</th>
                      <th className="py-2 text-right font-medium">Bowl WAR</th>
                      <th className="py-2 text-right font-medium">Team</th>
                      <th
                        className="py-2 text-right font-medium"
                        title="Sort key: mean WAR for all-rounders, primary WAR for specialists"
                      >
                        Score
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {proficientData.players.map((row, i) => (
                      <ProficientRow key={row.player_id} row={row} rank={i + 1} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-text-secondary">
                No qualifying players (need enough innings or spells for this side, plus WAR in
                careers).
              </p>
            )}
          </section>

          {/* Most impactful performances — below proficient list */}
          <section className="mt-10" aria-labelledby="teams-plays-heading">
            <h3
              id="teams-plays-heading"
              className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1"
            >
              Most impactful performances
            </h3>
            <p className="text-xs text-text-muted mb-4 max-w-3xl">
              Best single-game combined match-impact lines in scorecards that involve this team
              (same engine as the Performances page).
            </p>
            {playsLoading && !playsData?.performances?.length ? (
              <p className="text-sm text-text-muted">Loading highlights…</p>
            ) : playsData?.performances?.length ? (
              <ul className="card divide-y divide-surface-elevated/60">
                {playsData.performances.map((row) => (
                  <li
                    key={`${row.match_id}-${row.player_id}`}
                    className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <Link
                        to={`/player/${encodeURIComponent(row.player_id)}`}
                        className="font-medium text-primary hover:underline"
                      >
                        {row.player_name}
                      </Link>
                      <div className="text-xs text-text-muted truncate">
                        {(row.teams || []).join(" vs ") || row.match_id}
                        {row.date ? ` · ${fmtDateShort(String(row.date))}` : ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0 text-xs tabular-nums">
                      <span className="text-text-muted">
                        Impact{" "}
                        <span className="font-score text-text-primary">
                          {row.total_impact.toFixed(1)}
                        </span>
                      </span>
                      <Link
                        to={`/scorecards/${encodeURIComponent(row.match_id)}`}
                        className="text-primary font-medium hover:underline"
                      >
                        Match
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-text-secondary">
                No scored performances matched this team name in scorecards yet.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
