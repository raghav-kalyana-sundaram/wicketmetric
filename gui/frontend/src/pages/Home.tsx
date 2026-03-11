/**
 * Home / Dashboard page — the landing page for Cricket Metrics.
 *
 * Features (from gui.md § 6.1):
 *   - Hero search bar with autocomplete
 *   - Popular player quick links
 *   - Quick leaderboard cards (Top Rated, Power Hitters, Best Bowlers, Clutch)
 *   - Quick Compare widget (two player inputs → navigate to /compare)
 *   - Archetype browser (clickable badges linking to filtered rankings)
 *
 * Data fetching:
 *   - useTopPlayers() for each leaderboard card
 *   - useMeta() for dataset stats
 *   - useArchetypes() for the archetype browser
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
} from "lucide-react";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import { useTopPlayers, useMeta, useArchetypes } from "@/api/queries";
import { scoreToColour } from "@/lib/colours";
import { fmtScore, fmtInt, countryFlag } from "@/lib/format";
import type { PlayerSummary } from "@/api/types";

// ── Popular players (quick links shown below the hero search) ────

const POPULAR_PLAYERS = [
  { name: "Kohli", query: "V Kohli" },
  { name: "Buttler", query: "JC Buttler" },
  { name: "Rashid Khan", query: "Rashid Khan" },
  { name: "Bumrah", query: "JJ Bumrah" },
  { name: "SKY", query: "SA Yadav" },
  { name: "Babar", query: "Babar Azam" },
];

// ── Archetype icon mapping ───────────────────────────────────────

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

// ── Leaderboard card config ──────────────────────────────────────

interface LeaderboardCardConfig {
  title: string;
  icon: React.ReactNode;
  role: string;
  metric: string;
  linkTo: string;
  linkLabel: string;
  isBowling?: boolean;
  /** Display the value from this field. Default: overall_score */
  valueField?:
    | "overall_score"
    | "score_1"
    | "score_2"
    | "score_3"
    | "career_sr"
    | "career_avg";
  valueSuffix?: string;
}

const LEADERBOARD_CARDS: LeaderboardCardConfig[] = [
  {
    title: "Top Rated Batters",
    icon: <Trophy size={18} className="text-gold" />,
    role: "bat",
    metric: "overall_score",
    linkTo: "/rankings?role=bat&sort=overall_score&order=desc",
    linkLabel: "View All Rankings",
  },
  {
    title: "Power Hitters",
    icon: <Zap size={18} className="text-warning" />,
    role: "bat",
    metric: "score_power",
    linkTo: "/rankings?role=bat&sort=score_power&order=desc",
    linkLabel: "View Power Rankings",
    valueField: "score_2",
  },
  {
    title: "Best Bowlers",
    icon: <Target size={18} className="text-accent" />,
    role: "bowl",
    metric: "overall_score",
    linkTo: "/rankings?role=bowl&sort=overall_score&order=desc",
    linkLabel: "View All Bowlers",
    isBowling: true,
  },
  {
    title: "Clutch Performers",
    icon: <Flame size={18} className="text-danger" />,
    role: "bat",
    metric: "clutch_index",
    linkTo: "/rankings?role=bat&sort=clutch_index&order=desc",
    linkLabel: "View Clutch Rankings",
    valueField: "overall_score",
    valueSuffix: "",
  },
];

// ── Home Page Component ──────────────────────────────────────────

export default function Home() {
  const navigate = useNavigate();
  const [comparePlayer1, setComparePlayer1] = useState<PlayerSummary | null>(
    null,
  );
  const [comparePlayer2, setComparePlayer2] = useState<PlayerSummary | null>(
    null,
  );

  // Data fetching
  const { data: meta } = useMeta();
  const { data: archetypes } = useArchetypes();

  // Handle player selection from hero search
  const handleHeroSelect = useCallback(
    (player: PlayerSummary) => {
      navigate(`/player/${player.id}`);
    },
    [navigate],
  );

  // Handle hero search form submission
  const handleHeroSubmit = useCallback(
    (query: string) => {
      navigate(`/search?q=${encodeURIComponent(query)}`);
    },
    [navigate],
  );

  // Handle compare navigation
  const handleCompare = useCallback(() => {
    if (comparePlayer1 && comparePlayer2) {
      navigate(`/compare?ids=${comparePlayer1.id},${comparePlayer2.id}`);
    }
  }, [navigate, comparePlayer1, comparePlayer2]);

  return (
    <div className="space-y-10 pb-8">
      {/* ── Hero Section ────────────────────────────────────────── */}
      <section className="relative py-12 sm:py-16 -mx-4 sm:-mx-6 lg:-mx-8 px-4 sm:px-6 lg:px-8">
        {/* Gradient background */}
        <div className="absolute inset-0 bg-gradient-to-b from-primary/5 via-transparent to-transparent pointer-events-none" />

        <div className="relative max-w-2xl mx-auto text-center">
          {/* Title */}
          <div className="mb-8">
            <h1 className="text-h1 sm:text-4xl font-bold text-text-primary mb-3 flex items-center justify-center gap-3">
              <span
                role="img"
                aria-hidden="true"
                className="text-3xl sm:text-4xl"
              >
                🏏
              </span>
              <span>Cricket Metrics</span>
            </h1>
            <p className="text-text-secondary text-base sm:text-lg">
              T20I Player Intelligence — Search, compare, and analyse every T20I
              cricketer
            </p>
          </div>

          {/* Hero search bar */}
          <div id="hero-search" className="mb-4">
            <PlayerAutocomplete
              onSelect={handleHeroSelect}
              onSubmit={handleHeroSubmit}
              size="lg"
              placeholder="Search any T20I player..."
              showRoleFilter
              autoFocus={false}
              ariaLabel="Search T20I players"
            />
          </div>

          {/* Popular players */}
          <div className="flex flex-wrap items-center justify-center gap-2 text-sm">
            <span className="text-text-muted">Popular:</span>
            {POPULAR_PLAYERS.map((p, i) => (
              <span key={p.name} className="flex items-center">
                {i > 0 && <span className="text-text-muted/30 mx-0.5">·</span>}
                <Link
                  to={`/search?q=${encodeURIComponent(p.query)}`}
                  className="text-text-secondary hover:text-primary transition-colors"
                >
                  {p.name}
                </Link>
              </span>
            ))}
          </div>

          {/* Dataset stats */}
          {meta && meta.status === "ok" && (
            <div className="mt-6 flex flex-wrap items-center justify-center gap-4 text-xs text-text-muted">
              <span>{fmtInt(meta.total_batters)} batters</span>
              <span className="text-text-muted/30">·</span>
              <span>{fmtInt(meta.total_bowlers)} bowlers</span>
              <span className="text-text-muted/30">·</span>
              <span>{fmtInt(meta.total_matchups)} matchups</span>
              <span className="text-text-muted/30">·</span>
              <span>{fmtInt(meta.total_venues)} venues</span>
            </div>
          )}
        </div>
      </section>

      {/* ── Quick Leaderboard Cards ─────────────────────────────── */}
      <section>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {LEADERBOARD_CARDS.map((config) => (
            <LeaderboardCard key={config.title} config={config} />
          ))}
        </div>
      </section>

      {/* ── Quick Compare ───────────────────────────────────────── */}
      <section>
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-4">
            <GitCompare size={20} className="text-primary" />
            <h2 className="text-h3 text-text-primary">Quick Compare</h2>
          </div>

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
              <Users size={20} className="text-accent" />
              <h2 className="text-h3 text-text-primary">Browse by Archetype</h2>
            </div>

            <p className="text-sm text-text-secondary mb-4">
              Explore players grouped by their playing style and role
              classification.
            </p>

            {/* Batting archetypes */}
            {archetypes.bat && archetypes.bat.length > 0 && (
              <div className="mb-4">
                <h3 className="text-xs text-text-muted uppercase tracking-wider mb-2">
                  🏏 Batting Archetypes
                </h3>
                <div className="flex flex-wrap gap-2">
                  {archetypes.bat.map((arch) => (
                    <Link
                      key={`bat-${arch}`}
                      to={`/rankings?role=bat&archetype=${encodeURIComponent(arch)}`}
                      className="archetype-badge hover:bg-primary/10 hover:text-primary transition-colors"
                    >
                      {archetypeIcon(arch)}
                      <span>{arch}</span>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {/* Bowling archetypes */}
            {archetypes.bowl && archetypes.bowl.length > 0 && (
              <div>
                <h3 className="text-xs text-text-muted uppercase tracking-wider mb-2">
                  🎳 Bowling Archetypes
                </h3>
                <div className="flex flex-wrap gap-2">
                  {archetypes.bowl.map((arch) => (
                    <Link
                      key={`bowl-${arch}`}
                      to={`/rankings?role=bowl&archetype=${encodeURIComponent(arch)}`}
                      className="archetype-badge hover:bg-primary/10 hover:text-primary transition-colors"
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
          <QuickLink
            to="/rankings"
            icon={<Trophy size={20} />}
            label="Leaderboards"
            colour="text-gold"
          />
          <QuickLink
            to="/compare"
            icon={<GitCompare size={20} />}
            label="Compare"
            colour="text-primary"
          />
          <QuickLink
            to="/matchups"
            icon={<Target size={20} />}
            label="Matchups"
            colour="text-accent"
          />
          <QuickLink
            to="/venues"
            icon={<BarChart3 size={20} />}
            label="Venues"
            colour="text-warning"
          />
          <QuickLink
            to="/team-builder"
            icon={<Users size={20} />}
            label="Team Builder"
            colour="text-danger"
          />
          <QuickLink
            to="/glossary"
            icon={<Shield size={20} />}
            label="Methodology"
            colour="text-text-secondary"
          />
        </div>
      </section>
    </div>
  );
}

// ── Leaderboard Card Component ───────────────────────────────────

function LeaderboardCard({ config }: { config: LeaderboardCardConfig }) {
  const {
    data: players,
    isLoading,
    error,
  } = useTopPlayers({
    role: config.role,
    metric: config.metric,
    limit: 5,
    provisional: false,
    minInnings: 10,
  });

  return (
    <div className="card p-4 flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        {config.icon}
        <h3 className="text-sm font-semibold text-text-primary">
          {config.title}
        </h3>
      </div>

      {/* Player list */}
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
          <p className="text-xs text-text-muted py-4 text-center">
            Failed to load
          </p>
        )}

        {players &&
          (Array.isArray(players) ? players : ((players as any).players ?? []))
            .slice(0, 5)
            .map((player: PlayerSummary, index: number) => {
              const valueField = config.valueField ?? "overall_score";
              let displayValue: number | null = null;

              switch (valueField) {
                case "score_1":
                  displayValue = player.score_1;
                  break;
                case "score_2":
                  displayValue = player.score_2;
                  break;
                case "score_3":
                  displayValue = player.score_3;
                  break;
                case "career_sr":
                  displayValue = player.career_sr;
                  break;
                case "career_avg":
                  displayValue = player.career_avg;
                  break;
                default:
                  displayValue = player.overall_score;
              }

              return (
                <Link
                  key={player.id}
                  to={`/player/${player.id}`}
                  className="flex items-center gap-2 py-1 group hover:bg-surface-elevated/30 rounded px-1 -mx-1 transition-colors"
                >
                  {/* Rank */}
                  <span className="text-xs font-score tabular-nums text-text-muted w-4 text-right shrink-0">
                    {index + 1}.
                  </span>

                  {/* Name + country */}
                  <span className="flex-1 min-w-0 flex items-center gap-1.5">
                    <span className="text-sm text-text-primary group-hover:text-primary transition-colors truncate">
                      {player.name}
                    </span>
                    {player.country && (
                      <span
                        className="text-[11px] shrink-0"
                        title={player.country}
                      >
                        {countryFlag(player.country)}
                      </span>
                    )}
                  </span>

                  {/* Score */}
                  <span
                    className="text-sm font-score tabular-nums shrink-0"
                    style={{
                      color: scoreToColour(displayValue),
                    }}
                  >
                    {displayValue != null ? fmtScore(displayValue) : "—"}
                  </span>
                </Link>
              );
            })}
      </div>

      {/* Link to full leaderboard */}
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

// ── Quick Link Card ──────────────────────────────────────────────

function QuickLink({
  to,
  icon,
  label,
  colour = "text-primary",
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  colour?: string;
}) {
  return (
    <Link
      to={to}
      className="card flex flex-col items-center gap-2 py-4 px-3 hover:shadow-card-hover transition-all group text-center"
    >
      <span className={`${colour} group-hover:scale-110 transition-transform`}>
        {icon}
      </span>
      <span className="text-sm font-medium text-text-secondary group-hover:text-text-primary transition-colors">
        {label}
      </span>
    </Link>
  );
}
