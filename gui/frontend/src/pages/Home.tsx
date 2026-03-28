/**
 * Home / Dashboard page — the landing page for Cricket Metrics.
 *
 * Redesigned to feel alive and fan-first:
 *   - Hero search with one-line promise and featured insight
 *   - Latest match / trending section
 *   - "Start exploring" preset cards linking to filtered views
 *   - Why our rankings look different explainer strip
 *   - Quick Compare widget
 *   - Archetype browser
 */

import { useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Trophy,
  Zap,
  Target,
  Flame,
  GitCompare,
  ArrowRight,
  TrendingUp,
  Shield,
  BarChart3,
  Users,
  MapPin,
  Swords,
  Activity,
  Layers,
  Clock,
  Crosshair,
} from "lucide-react";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import HomeWelcomeTip from "@/components/HomeWelcomeTip";
import { useTopPlayers, useMeta, useArchetypes } from "@/api/queries";
import { scoreToColour } from "@/lib/colours";
import { fmtScore, fmtInt, countryFlag, primaryDisplayRating } from "@/lib/format";
import type { PlayerSummary } from "@/api/types";

const POPULAR_PLAYERS = [
  { name: "Kohli", query: "V Kohli" },
  { name: "Buttler", query: "JC Buttler" },
  { name: "Rashid Khan", query: "Rashid Khan" },
  { name: "Bumrah", query: "JJ Bumrah" },
  { name: "SKY", query: "SA Yadav" },
  { name: "Babar", query: "Babar Azam" },
];

const ARCHETYPE_ICONS: Record<string, React.ReactNode> = {
  Anchor: <Shield size={14} />,
  "Chase Master": <Flame size={14} />,
  "Explosive Finisher": <Zap size={14} />,
  "Power Hitter": <Zap size={14} />,
  Accumulator: <TrendingUp size={14} />,
  "All-Phase": <BarChart3 size={14} />,
  "Aggressive Opener": <Zap size={14} />,
  "Wicket-Taker": <Target size={14} />,
  "Economy Specialist": <Shield size={14} />,
  "Death Specialist": <Flame size={14} />,
  "Powerplay Specialist": <Zap size={14} />,
};

function archetypeIcon(archetype: string): React.ReactNode {
  for (const [key, icon] of Object.entries(ARCHETYPE_ICONS)) {
    if (archetype.toLowerCase().includes(key.toLowerCase())) {
      return icon;
    }
  }
  return <BarChart3 size={14} />;
}

interface LeaderboardCardConfig {
  title: string;
  icon: React.ReactNode;
  role: string;
  metric: string;
  linkTo: string;
  linkLabel: string;
  isBowling?: boolean;
  valueField?:
    | "overall_score"
    | "score_1"
    | "score_2"
    | "score_3"
    | "career_sr"
    | "career_avg";
  valueSuffix?: string;
  valueCaption?: string;
}

const LEADERBOARD_CARDS: LeaderboardCardConfig[] = [
  {
    title: "Top Rated Batters",
    icon: <Trophy size={18} className="text-text-muted" />,
    role: "bat",
    metric: "rating_current",
    linkTo: "/rankings?role=bat&sort=rating_current&order=desc",
    linkLabel: "View All Rankings",
    valueCaption: "Current rating",
  },
  {
    title: "Power Hitters",
    icon: <Zap size={18} className="text-text-muted" />,
    role: "bat",
    metric: "score_power",
    linkTo: "/rankings?role=bat&sort=score_power&order=desc",
    linkLabel: "View Power Rankings",
    valueField: "score_2",
    valueCaption: "Power score",
  },
  {
    title: "Best Bowlers",
    icon: <Target size={18} className="text-text-muted" />,
    role: "bowl",
    metric: "rating_current",
    linkTo: "/rankings?role=bowl&sort=rating_current&order=desc",
    linkLabel: "View All Bowlers",
    isBowling: true,
    valueCaption: "Current rating",
  },
  {
    title: "Best Under Pressure",
    icon: <Flame size={18} className="text-text-muted" />,
    role: "bat",
    metric: "clutch_index",
    linkTo: "/rankings?role=bat&sort=clutch_index&order=desc",
    linkLabel: "View Pressure Rankings",
    valueField: "overall_score",
    valueSuffix: "",
    valueCaption: "Pressure score",
  },
];

const EXPLORE_PRESETS = [
  { label: "Best batters", to: "/rankings?role=bat&sort=rating_current&order=desc", icon: <Trophy size={16} /> },
  { label: "Best death bowlers", to: "/rankings?role=bowl&sort=rating_overall&order=desc&phase_group=death", icon: <Crosshair size={16} /> },
  { label: "Best under pressure", to: "/rankings?role=bat&sort=clutch_index&order=desc", icon: <Flame size={16} /> },
  { label: "Power hitters", to: "/rankings?role=bat&sort=score_power&order=desc", icon: <Zap size={16} /> },
  { label: "Toughest venues", to: "/venues", icon: <MapPin size={16} /> },
  { label: "Great recent innings", to: "/performances?sort=combined&order=desc", icon: <Activity size={16} /> },
  { label: "Head-to-head matchups", to: "/matchups", icon: <Swords size={16} /> },
  { label: "Match scorecards", to: "/scorecards", icon: <Layers size={16} /> },
];

const METHODOLOGY_PILLS = [
  { label: "Role-aware", desc: "Different metrics for openers, finishers, death bowlers" },
  { label: "Phase-aware", desc: "Powerplay, middle, and death overs scored separately" },
  { label: "Era-adjusted", desc: "Performances normalised for the scoring environment" },
  { label: "Matchup-aware", desc: "Ball-by-ball batter vs bowler contest analysis" },
];

export default function Home() {
  const navigate = useNavigate();
  const [comparePlayer1, setComparePlayer1] = useState<PlayerSummary | null>(null);
  const [comparePlayer2, setComparePlayer2] = useState<PlayerSummary | null>(null);

  const { data: meta } = useMeta();
  const { data: archetypes } = useArchetypes();

  const handleHeroSelect = useCallback(
    (player: PlayerSummary) => navigate(`/player/${player.id}`),
    [navigate],
  );

  const handleHeroSubmit = useCallback(
    (query: string) => navigate(`/search?q=${encodeURIComponent(query)}`),
    [navigate],
  );

  const handleCompare = useCallback(() => {
    if (comparePlayer1 && comparePlayer2) {
      navigate(`/compare?ids=${comparePlayer1.id},${comparePlayer2.id}`);
    }
  }, [navigate, comparePlayer1, comparePlayer2]);

  return (
    <div className="app-page page-stack">
      <HomeWelcomeTip />

      {/* ── Hero ─────────────────────────────────────────────── */}
      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-surface-light py-10 shadow-sm sm:py-12 dark:rounded-2xl dark:border-white/[0.1] dark:bg-surface dark:shadow-[0_20px_40px_-28px_rgba(0,0,0,0.65)]"
        aria-label="Search and overview"
      >
        <div className="mx-auto max-w-3xl px-4 text-center md:px-6">
          <div className="mb-8 border-b border-slate-200 pb-8 dark:border-white/[0.08]">
            <h1 className="mb-3 flex items-center justify-center gap-3 text-h1 font-bold text-text-primary">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-primary transition-transform duration-300 ease-out-quart motion-reduce:transition-none hover:scale-105 dark:border-white/[0.1] dark:bg-surface-elevated">
                <BarChart3 size={20} />
              </span>
              <span>Cricket Metrics</span>
            </h1>
            <p className="mx-auto max-w-xl text-pretty text-base text-text-secondary sm:text-lg">
              T20 intelligence for fans who care about the details.
            </p>
          </div>

          <div id="hero-search" className="mb-4">
            <PlayerAutocomplete
              onSelect={handleHeroSelect}
              onSubmit={handleHeroSubmit}
              size="lg"
              placeholder="Search any T20 player..."
              showRoleFilter
              autoFocus={false}
              ariaLabel="Search T20 players"
            />
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2 text-sm">
            <span className="text-text-muted">Popular:</span>
            {POPULAR_PLAYERS.map((p, i) => (
              <span key={p.name} className="flex items-center">
                {i > 0 && <span className="mx-0.5 text-text-muted/50">·</span>}
                <Link
                  to={`/search?q=${encodeURIComponent(p.query)}`}
                  className="rounded-full border border-slate-200/90 bg-slate-100/80 px-2.5 py-1 text-xs text-text-secondary transition-colors duration-200 ease-out-quart hover:border-primary/40 hover:bg-slate-200/80 hover:text-primary dark:border-white/[0.1] dark:bg-surface-elevated dark:hover:bg-[#1a1a1a]"
                >
                  {p.name}
                </Link>
              </span>
            ))}
          </div>

          {meta && meta.status === "ok" && (
            <div className="mt-6 flex flex-wrap items-center justify-center gap-4 text-xs text-text-muted">
              <span>{fmtInt(meta.total_batters)} batters</span>
              <span className="text-text-muted/50">·</span>
              <span>{fmtInt(meta.total_bowlers)} bowlers</span>
              <span className="text-text-muted/50">·</span>
              <span>{fmtInt(meta.total_matchups)} matchups</span>
              <span className="text-text-muted/50">·</span>
              <span>{fmtInt(meta.total_venues)} venues</span>
              {meta.data_through_date && (
                <>
                  <span className="text-text-muted/50">·</span>
                  <span className="tabular-nums">Data through {meta.data_through_date}</span>
                </>
              )}
            </div>
          )}
        </div>
      </section>

      {/* ── Latest match + Featured insight ──────────────────── */}
      {meta?.latest_scorecard && (
        <section className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Link
            to={`/scorecards/${meta.latest_scorecard.match_id}`}
            className="card group flex items-start gap-3 p-4 transition-all hover:shadow-card-hover"
          >
            <div className="mt-0.5 rounded-lg bg-accent/10 p-2 text-accent">
              <Activity size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Latest match</p>
              <p className="text-sm font-medium text-text-primary group-hover:text-primary transition-colors truncate">
                {meta.latest_scorecard.teams?.join(" vs ") ?? meta.latest_scorecard.match_id}
              </p>
              <p className="text-xs text-text-muted mt-0.5">
                {[meta.latest_scorecard.date, meta.latest_scorecard.event_name].filter(Boolean).join(" · ") || "View scorecard"}
              </p>
            </div>
            <ArrowRight size={14} className="mt-1 shrink-0 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
          </Link>
          <Link
            to="/live"
            className="card group flex items-start gap-3 p-4 transition-all hover:shadow-card-hover"
          >
            <div className="mt-0.5 rounded-lg bg-warning/10 p-2 text-warning">
              <Clock size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mb-1">Live matches</p>
              <p className="text-sm font-medium text-text-primary group-hover:text-primary transition-colors">
                Check live T20 scores and win probability
              </p>
            </div>
            <ArrowRight size={14} className="mt-1 shrink-0 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
          </Link>
        </section>
      )}

      {/* ── Quick Leaderboard Cards ─────────────────────────────── */}
      <section>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {LEADERBOARD_CARDS.map((config) => (
            <LeaderboardCard key={config.title} config={config} />
          ))}
        </div>
      </section>

      {/* ── Start Exploring ────────────────────────────────────── */}
      <section>
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-4">
            <Swords size={20} className="text-text-muted" />
            <h2 className="text-h3 text-text-primary">Start exploring</h2>
          </div>
          <p className="text-sm text-text-secondary mb-4">
            Jump straight to the questions fans care about.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
            {EXPLORE_PRESETS.map((preset) => (
              <Link
                key={preset.to}
                to={preset.to}
                className="group flex items-center gap-2 rounded-lg border border-surface-elevated/70 bg-surface-elevated/20 px-3 py-2.5 text-xs font-medium text-text-secondary transition-all hover:border-primary/30 hover:bg-surface-elevated/40 hover:text-primary dark:border-white/[0.06] dark:hover:border-white/[0.12] dark:hover:bg-white/[0.03]"
              >
                <span className="shrink-0 text-text-muted group-hover:text-primary transition-colors">{preset.icon}</span>
                <span className="truncate">{preset.label}</span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ── Why our rankings look different ─────────────────── */}
      <section>
        <div className="rounded-xl border border-surface-elevated/50 bg-surface-elevated/15 px-5 py-4 dark:bg-white/[0.015]">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
            Why our rankings look different
          </p>
          <div className="flex flex-wrap gap-2">
            {METHODOLOGY_PILLS.map((pill) => (
              <span
                key={pill.label}
                className="inline-flex items-center gap-1.5 rounded-lg border border-surface-elevated/70 bg-surface px-3 py-1.5 text-xs dark:border-white/[0.08]"
                title={pill.desc}
              >
                <span className="font-semibold text-text-primary">{pill.label}</span>
                <span className="hidden sm:inline text-text-muted">— {pill.desc}</span>
              </span>
            ))}
          </div>
          <Link
            to="/glossary"
            className="mt-3 inline-flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors"
          >
            Learn about our methodology <ArrowRight size={12} />
          </Link>
        </div>
      </section>

      {/* ── Quick Compare ───────────────────────────────────────── */}
      <section>
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-1">
            <GitCompare size={20} className="text-text-muted" />
            <h2 className="text-h3 text-text-primary">Quick Compare</h2>
          </div>
          <p className="text-xs text-text-secondary mb-4">Who wins this matchup of careers?</p>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3">
            <div className="flex-1">
              <label className="text-xs text-text-muted uppercase tracking-wider mb-1.5 block">
                Player 1
              </label>
              <PlayerAutocomplete
                value={comparePlayer1}
                onSelect={setComparePlayer1}
                onClear={() => setComparePlayer1(null)}
                size="md"
                placeholder="Search player..."
                excludeIds={comparePlayer2 ? [comparePlayer2.id] : undefined}
              />
            </div>

            <span className="text-text-muted font-medium text-center py-2 sm:pb-2.5">
              vs
            </span>

            <div className="flex-1">
              <label className="text-xs text-text-muted uppercase tracking-wider mb-1.5 block">
                Player 2
              </label>
              <PlayerAutocomplete
                value={comparePlayer2}
                onSelect={setComparePlayer2}
                onClear={() => setComparePlayer2(null)}
                size="md"
                placeholder="Search player..."
                excludeIds={comparePlayer1 ? [comparePlayer1.id] : undefined}
              />
            </div>

            <button
              onClick={handleCompare}
              disabled={!comparePlayer1 || !comparePlayer2}
              className="btn-primary shrink-0"
            >
              Compare
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </section>

      {/* ── Archetype Browser ───────────────────────────────────── */}
      {archetypes && (
        <section>
          <div className="card p-6">
            <div className="flex items-center gap-2 mb-4">
              <Users size={20} className="text-text-muted" />
              <h2 className="text-h3 text-text-primary">Browse by Archetype</h2>
            </div>

            <p className="text-sm text-text-secondary mb-4">
              Explore players grouped by their playing style and role classification.
            </p>

            {archetypes.bat && archetypes.bat.length > 0 && (
              <div className="mb-4">
                <h3 className="text-xs text-text-muted uppercase tracking-wider mb-2">
                  Batting Archetypes
                </h3>
                <div className="flex flex-wrap gap-2">
                  {archetypes.bat.map((arch) => (
                    <Link
                      key={`bat-${arch}`}
                      to={`/rankings?role=bat&archetype=${encodeURIComponent(arch)}`}
                      className="archetype-badge transition-colors hover:bg-white/[0.06] hover:text-primary dark:hover:bg-white/[0.08]"
                    >
                      {archetypeIcon(arch)}
                      <span>{arch}</span>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {archetypes.bowl && archetypes.bowl.length > 0 && (
              <div>
                <h3 className="text-xs text-text-muted uppercase tracking-wider mb-2">
                  Bowling Archetypes
                </h3>
                <div className="flex flex-wrap gap-2">
                  {archetypes.bowl.map((arch) => (
                    <Link
                      key={`bowl-${arch}`}
                      to={`/rankings?role=bowl&archetype=${encodeURIComponent(arch)}`}
                      className="archetype-badge transition-colors hover:bg-white/[0.06] hover:text-primary dark:hover:bg-white/[0.08]"
                    >
                      {archetypeIcon(arch)}
                      <span>{arch}</span>
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {/* ── Quick Links Grid ────────────────────────────────────── */}
      <section>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <QuickLink to="/rankings" icon={<Trophy size={20} />} label="Leaderboards" />
          <QuickLink to="/compare" icon={<GitCompare size={20} />} label="Compare" />
          <QuickLink to="/matchups" icon={<Target size={20} />} label="Matchups" />
          <QuickLink to="/venues" icon={<BarChart3 size={20} />} label="Venues" />
          <QuickLink to="/team-builder" icon={<Users size={20} />} label="Team Builder" />
          <QuickLink to="/glossary" icon={<Shield size={20} />} label="Methodology" />
        </div>
      </section>
    </div>
  );
}

function LeaderboardCard({ config }: { config: LeaderboardCardConfig }) {
  const {
    data: players,
    isLoading,
    error,
    refetch,
  } = useTopPlayers({
    role: config.role,
    metric: config.metric,
    limit: 5,
  });

  return (
    <div className="card p-4 flex flex-col">
      <div className="flex items-center gap-2 mb-1">
        {config.icon}
        <h3 className="text-sm font-semibold text-text-primary">
          {config.title}
        </h3>
      </div>
      {config.valueCaption && (
        <p className="text-[10px] text-text-muted mb-2 leading-snug">
          {config.valueCaption}
        </p>
      )}

      <div className="flex-1 space-y-1.5 mb-3">
        {isLoading && (
          <>
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center gap-2 py-1">
                <div className="skeleton w-4 h-4 rounded" />
                <div className="skeleton-text flex-1 h-3.5" />
                <div className="skeleton w-8 h-3.5 rounded" />
              </div>
            ))}
          </>
        )}

        {error && (
          <div className="py-4 text-center space-y-2">
            <p className="text-xs text-text-muted">Failed to load</p>
            <button type="button" onClick={() => refetch()} className="btn-secondary btn-sm">
              Try again
            </button>
          </div>
        )}

        {players &&
          (Array.isArray(players) ? players : ((players as any).players ?? []))
            .slice(0, 5)
            .map((player: PlayerSummary, index: number) => {
              const valueField = config.valueField ?? "overall_score";
              let displayValue: number | null = null;

              switch (valueField) {
                case "score_1": displayValue = player.score_1; break;
                case "score_2": displayValue = player.score_2; break;
                case "score_3": displayValue = player.score_3; break;
                case "career_sr": displayValue = player.career_sr; break;
                case "career_avg": displayValue = player.career_avg; break;
                default: displayValue = primaryDisplayRating(player);
              }

              return (
                <Link
                  key={player.id}
                  to={`/player/${player.id}`}
                  className="flex items-center gap-2 py-1 group hover:bg-surface-elevated/30 rounded px-1 -mx-1 transition-colors"
                >
                  <span className="text-xs font-score tabular-nums text-text-muted w-4 text-right shrink-0">
                    {index + 1}.
                  </span>
                  <span
                    className="flex-1 min-w-0 flex items-center gap-1.5"
                    title={
                      [(player.recent_team || "").trim(), player.country]
                        .filter(Boolean)
                        .join(" · ") || undefined
                    }
                  >
                    <span className="text-sm text-text-primary group-hover:text-primary transition-colors truncate">
                      {player.name}
                    </span>
                    {player.country && (
                      <span className="text-[11px] shrink-0" title={player.country}>
                        {countryFlag(player.country)}
                      </span>
                    )}
                  </span>
                  <span
                    className="text-sm font-score tabular-nums shrink-0"
                    style={{ color: scoreToColour(displayValue) }}
                  >
                    {displayValue != null ? fmtScore(displayValue) : "—"}
                  </span>
                </Link>
              );
            })}
      </div>

      <Link
        to={config.linkTo}
        className="text-xs text-primary hover:text-primary-hover transition-colors flex items-center gap-1 mt-auto pt-2 border-t border-surface-elevated/50"
      >
        <span>{config.linkLabel}</span>
        <ArrowRight size={12} />
      </Link>
    </div>
  );
}

function QuickLink({
  to,
  icon,
  label,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <Link
      to={to}
      className="card flex flex-col items-center gap-2 py-4 px-3 text-center transition-all duration-200 ease-out-quart hover:shadow-card-hover group motion-reduce:transition-none"
    >
      <span className="text-text-muted transition-transform duration-200 ease-out-quart group-hover:scale-105 group-hover:text-primary motion-reduce:group-hover:scale-100">
        {icon}
      </span>
      <span className="text-sm font-medium text-text-secondary transition-colors group-hover:text-text-primary">
        {label}
      </span>
    </Link>
  );
}
