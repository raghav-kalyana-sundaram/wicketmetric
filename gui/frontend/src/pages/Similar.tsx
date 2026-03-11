/**
 * Similar — Similarity Explorer page ("Comps").
 *
 * Route: /similar/:id
 *
 * Features (from gui.md § 6.7):
 *   - Top-K similar players table ranked by cosine similarity
 *   - 2D scatter plot (simple PCA-like projection from 3 metric scores)
 *   - Click any player to view their profile
 *   - "Compare with top similar" button pre-fills the compare page
 *   - Score bars for each similar player's metrics
 *   - Target player highlighted in both table and scatter
 *
 * Data fetching:
 *   - usePlayerProfile() — target player's full profile
 *   - usePlayerSimilar() — pre-computed similar players list
 */

import { useState, useMemo, useCallback, useRef } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Users,
  GitCompare,
  Star,
  ArrowRight,
  Info,
  ZoomIn,
} from "lucide-react";

import GradeBadge from "@/components/GradeBadge";
import { ScoreBarMini } from "@/components/ScoreBar";
import { PageLoading, PageError, NotFound } from "@/components/Layout";
import { usePlayerProfile, usePlayerSimilar } from "@/api/queries";
import { scoreToColour } from "@/lib/colours";
import { fmtScore, fmtSimilarity, countryFlag } from "@/lib/format";
import type {
  PlayerProfile,
  BatterProfile,
  BowlerProfile,
  SimilarPlayer,
} from "@/api/types";
import { isBatterProfile } from "@/api/types";

// ── Constants ────────────────────────────────────────────────────

const DEFAULT_LIMIT = 15;
const SCATTER_SIZE = 400;
const SCATTER_PADDING = 50;

// ── Helpers ──────────────────────────────────────────────────────

/**
 * Simple 2D projection from 3 metric scores.
 * Uses a basic linear projection (not full PCA) that maps:
 *   x ≈ score_1 - 0.5 * score_3
 *   y ≈ score_2 - 0.5 * score_1
 * This gives a reasonable 2D spread for visualisation purposes.
 */
function project2D(
  s1: number | null,
  s2: number | null,
  s3: number | null,
): { x: number; y: number } {
  const v1 = s1 ?? 50;
  const v2 = s2 ?? 50;
  const v3 = s3 ?? 50;
  return {
    x: v1 * 0.8 - v3 * 0.3 + v2 * 0.1,
    y: v2 * 0.8 - v1 * 0.3 + v3 * 0.1,
  };
}

function getTargetScores(profile: PlayerProfile): {
  s1: number | null;
  s2: number | null;
  s3: number | null;
} {
  if (isBatterProfile(profile)) {
    return {
      s1: profile.score_acceleration,
      s2: profile.score_power,
      s3: profile.score_control,
    };
  }
  return {
    s1: profile.score_accuracy,
    s2: profile.score_control,
    s3: profile.score_threat,
  };
}

function getScoreLabels(profile: PlayerProfile): {
  s1: string;
  s2: string;
  s3: string;
} {
  if (isBatterProfile(profile)) {
    return { s1: "Acceleration", s2: "Power", s3: "Control" };
  }
  return { s1: "Accuracy", s2: "Control", s3: "Threat" };
}

// ── Scatter Plot Component ───────────────────────────────────────

interface ScatterPoint {
  id: string;
  name: string;
  country: string;
  x: number;
  y: number;
  similarity: number | null;
  isTarget: boolean;
  s1: number | null;
  s2: number | null;
  s3: number | null;
}

interface SimilarityScatterProps {
  points: ScatterPoint[];
  labels: { s1: string; s2: string; s3: string };
  onPointClick?: (id: string) => void;
}

function SimilarityScatter({
  points,
  labels,
  onPointClick,
}: SimilarityScatterProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // Compute bounds
  const { xMin, xMax, yMin, yMax } = useMemo(() => {
    if (points.length === 0) {
      return { xMin: 0, xMax: 100, yMin: 0, yMax: 100 };
    }
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const pad = 5;
    return {
      xMin: Math.min(...xs) - pad,
      xMax: Math.max(...xs) + pad,
      yMin: Math.min(...ys) - pad,
      yMax: Math.max(...ys) + pad,
    };
  }, [points]);

  const scaleX = (v: number) => {
    const range = xMax - xMin || 1;
    return (
      SCATTER_PADDING +
      ((v - xMin) / range) * (SCATTER_SIZE - 2 * SCATTER_PADDING)
    );
  };

  const scaleY = (v: number) => {
    const range = yMax - yMin || 1;
    return (
      SCATTER_SIZE -
      SCATTER_PADDING -
      ((v - yMin) / range) * (SCATTER_SIZE - 2 * SCATTER_PADDING)
    );
  };

  const hoveredPoint = points.find((p) => p.id === hoveredId);

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${SCATTER_SIZE} ${SCATTER_SIZE}`}
        className="w-full max-w-lg mx-auto"
        role="img"
        aria-label="Similarity scatter plot"
      >
        {/* Background grid */}
        <rect
          x={SCATTER_PADDING}
          y={SCATTER_PADDING}
          width={SCATTER_SIZE - 2 * SCATTER_PADDING}
          height={SCATTER_SIZE - 2 * SCATTER_PADDING}
          fill="none"
          stroke="currentColor"
          strokeOpacity={0.08}
          strokeWidth={0.5}
        />

        {/* Gridlines */}
        {[0.25, 0.5, 0.75].map((frac) => {
          const xPos =
            SCATTER_PADDING + frac * (SCATTER_SIZE - 2 * SCATTER_PADDING);
          const yPos =
            SCATTER_PADDING + frac * (SCATTER_SIZE - 2 * SCATTER_PADDING);
          return (
            <g key={frac}>
              <line
                x1={xPos}
                y1={SCATTER_PADDING}
                x2={xPos}
                y2={SCATTER_SIZE - SCATTER_PADDING}
                stroke="currentColor"
                strokeOpacity={0.05}
                strokeWidth={0.5}
              />
              <line
                x1={SCATTER_PADDING}
                y1={yPos}
                x2={SCATTER_SIZE - SCATTER_PADDING}
                y2={yPos}
                stroke="currentColor"
                strokeOpacity={0.05}
                strokeWidth={0.5}
              />
            </g>
          );
        })}

        {/* Connection lines from target to similar players */}
        {points
          .filter((p) => p.isTarget)
          .map((target) =>
            points
              .filter((p) => !p.isTarget)
              .slice(0, 5) // Only draw lines to top 5
              .map((p) => (
                <line
                  key={`line-${p.id}`}
                  x1={scaleX(target.x)}
                  y1={scaleY(target.y)}
                  x2={scaleX(p.x)}
                  y2={scaleY(p.y)}
                  stroke="#3B82F6"
                  strokeOpacity={0.12}
                  strokeWidth={1}
                  strokeDasharray="4 4"
                />
              )),
          )}

        {/* Points (non-target first, target on top) */}
        {points
          .sort((a, b) => (a.isTarget ? 1 : 0) - (b.isTarget ? 1 : 0))
          .map((point) => {
            const cx = scaleX(point.x);
            const cy = scaleY(point.y);
            const isHovered = hoveredId === point.id;
            const r = point.isTarget ? 8 : isHovered ? 7 : 5;
            const fill = point.isTarget
              ? "#FFD700"
              : scoreToColour(
                  point.similarity != null ? point.similarity * 100 : null,
                );
            const strokeWidth = point.isTarget ? 2.5 : isHovered ? 2 : 1;
            const strokeColour = point.isTarget
              ? "#B8860B"
              : isHovered
                ? "#F8FAFC"
                : "transparent";

            return (
              <g key={point.id}>
                <circle
                  cx={cx}
                  cy={cy}
                  r={r + 4}
                  fill="transparent"
                  style={{ cursor: "pointer" }}
                  onMouseEnter={() => setHoveredId(point.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onClick={() => onPointClick?.(point.id)}
                />
                <circle
                  cx={cx}
                  cy={cy}
                  r={r}
                  fill={fill}
                  fillOpacity={point.isTarget ? 1 : 0.8}
                  stroke={strokeColour}
                  strokeWidth={strokeWidth}
                  style={{
                    cursor: "pointer",
                    transition: "r 0.15s ease-out",
                  }}
                  onMouseEnter={() => setHoveredId(point.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onClick={() => onPointClick?.(point.id)}
                />
                {/* Target label */}
                {point.isTarget && (
                  <text
                    x={cx}
                    y={cy - 14}
                    textAnchor="middle"
                    className="fill-gold text-[10px] font-bold"
                  >
                    ★ {point.name}
                  </text>
                )}
                {/* Hovered label */}
                {isHovered && !point.isTarget && (
                  <text
                    x={cx}
                    y={cy - 12}
                    textAnchor="middle"
                    className="fill-text-primary text-[10px] font-medium"
                  >
                    {point.name}
                  </text>
                )}
              </g>
            );
          })}

        {/* Axis labels */}
        <text
          x={SCATTER_SIZE / 2}
          y={SCATTER_SIZE - 10}
          textAnchor="middle"
          className="fill-text-muted text-[10px]"
        >
          {labels.s1} →
        </text>
        <text
          x={12}
          y={SCATTER_SIZE / 2}
          textAnchor="middle"
          transform={`rotate(-90, 12, ${SCATTER_SIZE / 2})`}
          className="fill-text-muted text-[10px]"
        >
          {labels.s2} →
        </text>
      </svg>

      {/* Tooltip */}
      {hoveredPoint && !hoveredPoint.isTarget && (
        <div className="absolute top-2 right-2 card p-3 text-xs shadow-lg z-10 min-w-[180px]">
          <div className="font-medium text-text-primary mb-1">
            {countryFlag(hoveredPoint.country)} {hoveredPoint.name}
          </div>
          <div className="space-y-1 text-text-secondary">
            <div className="flex justify-between">
              <span>Similarity</span>
              <span className="font-score text-primary">
                {fmtSimilarity(hoveredPoint.similarity)}
              </span>
            </div>
            <div className="flex justify-between">
              <span>{labels.s1}</span>
              <span
                className="font-score"
                style={{ color: scoreToColour(hoveredPoint.s1) }}
              >
                {fmtScore(hoveredPoint.s1)}
              </span>
            </div>
            <div className="flex justify-between">
              <span>{labels.s2}</span>
              <span
                className="font-score"
                style={{ color: scoreToColour(hoveredPoint.s2) }}
              >
                {fmtScore(hoveredPoint.s2)}
              </span>
            </div>
            <div className="flex justify-between">
              <span>{labels.s3}</span>
              <span
                className="font-score"
                style={{ color: scoreToColour(hoveredPoint.s3) }}
              >
                {fmtScore(hoveredPoint.s3)}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────

export default function Similar() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [limit, setLimit] = useState(DEFAULT_LIMIT);

  // Fetch profile
  const {
    data: profile,
    isLoading: profileLoading,
    error: profileError,
  } = usePlayerProfile(id ?? "");

  // Fetch similar players
  const {
    data: similarData,
    isLoading: similarLoading,
    error: similarError,
  } = usePlayerSimilar(id ?? "", { limit });

  const isLoading = profileLoading || similarLoading;
  const error = profileError || similarError;

  // Derived data
  const targetScores = useMemo(
    () => (profile ? getTargetScores(profile) : null),
    [profile],
  );
  const scoreLabels = useMemo(
    () =>
      profile
        ? getScoreLabels(profile)
        : { s1: "Score 1", s2: "Score 2", s3: "Score 3" },
    [profile],
  );

  const similarPlayers: SimilarPlayer[] = useMemo(
    () => similarData?.similar ?? [],
    [similarData],
  );

  // Scatter plot points
  const scatterPoints: ScatterPoint[] = useMemo(() => {
    const pts: ScatterPoint[] = [];

    // Target player
    if (profile && targetScores) {
      const pos = project2D(targetScores.s1, targetScores.s2, targetScores.s3);
      pts.push({
        id: profile.id,
        name: profile.name,
        country: profile.country,
        x: pos.x,
        y: pos.y,
        similarity: 1.0,
        isTarget: true,
        s1: targetScores.s1,
        s2: targetScores.s2,
        s3: targetScores.s3,
      });
    }

    // Similar players
    similarPlayers.forEach((sp) => {
      const pos = project2D(sp.score_1, sp.score_2, sp.score_3);
      pts.push({
        id: sp.id,
        name: sp.name,
        country: sp.country,
        x: pos.x,
        y: pos.y,
        similarity: sp.similarity_score,
        isTarget: false,
        s1: sp.score_1,
        s2: sp.score_2,
        s3: sp.score_3,
      });
    });

    return pts;
  }, [profile, targetScores, similarPlayers]);

  // Navigation
  const handlePointClick = useCallback(
    (playerId: string) => {
      if (playerId === id) return;
      navigate(`/similar/${playerId}`);
    },
    [id, navigate],
  );

  const handleCompareTopSimilar = useCallback(() => {
    if (!id || similarPlayers.length === 0) return;
    const compareIds = [
      id,
      ...similarPlayers.slice(0, 3).map((p) => p.id),
    ].join(",");
    navigate(`/compare?ids=${compareIds}`);
  }, [id, similarPlayers, navigate]);

  // ── Render ─────────────────────────────────────────────────────

  if (isLoading) return <PageLoading />;

  if (error) {
    return <PageError message="Failed to load similarity data." />;
  }

  if (!profile) return <NotFound />;

  const isBatter = isBatterProfile(profile);

  return (
    <div className="animate-fade-in space-y-6">
      {/* Back link */}
      <Link
        to={`/player/${id}`}
        className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-primary transition-colors"
      >
        <ArrowLeft size={16} />
        Back to {profile.name}'s profile
      </Link>

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-h1 text-text-primary flex items-center gap-3">
            <Users size={28} className="text-primary" />
            Similar Players
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            Players ranked by statistical profile similarity (cosine) to{" "}
            <Link
              to={`/player/${id}`}
              className="text-primary hover:underline font-medium"
            >
              {countryFlag(profile.country)} {profile.name}
            </Link>
            . Higher similarity = more similar playing style and output.
          </p>
        </div>

        <button
          onClick={handleCompareTopSimilar}
          className="btn-primary btn-sm shrink-0"
          disabled={similarPlayers.length === 0}
        >
          <GitCompare size={14} />
          Compare with top similar
        </button>
      </div>

      {/* Target player summary */}
      <div className="card p-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-gold/20 flex items-center justify-center">
              <Star size={20} className="text-gold" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-text-muted text-sm">
                  {countryFlag(profile.country)}
                </span>
                <Link
                  to={`/player/${id}`}
                  className="font-semibold text-text-primary hover:text-primary transition-colors"
                >
                  {profile.name}
                </Link>
                <GradeBadge
                  grade={
                    isBatter
                      ? (profile as BatterProfile).overall_grade
                      : (profile as BowlerProfile).overall_grade
                  }
                  size="sm"
                />
              </div>
              <span className="text-xs text-text-secondary">
                {profile.archetype} · {profile.country}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-6 ml-auto">
            <div className="text-center">
              <div
                className="font-score text-sm font-bold tabular-nums"
                style={{ color: scoreToColour(targetScores?.s1) }}
              >
                {fmtScore(targetScores?.s1)}
              </div>
              <div className="text-[10px] text-text-muted uppercase">
                {scoreLabels.s1}
              </div>
            </div>
            <div className="text-center">
              <div
                className="font-score text-sm font-bold tabular-nums"
                style={{ color: scoreToColour(targetScores?.s2) }}
              >
                {fmtScore(targetScores?.s2)}
              </div>
              <div className="text-[10px] text-text-muted uppercase">
                {scoreLabels.s2}
              </div>
            </div>
            <div className="text-center">
              <div
                className="font-score text-sm font-bold tabular-nums"
                style={{ color: scoreToColour(targetScores?.s3) }}
              >
                {fmtScore(targetScores?.s3)}
              </div>
              <div className="text-[10px] text-text-muted uppercase">
                {scoreLabels.s3}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Similarity Table ──────────────────────────────── */}
        <section className="card p-4">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-h3 text-text-primary flex items-center gap-2">
              <Users size={18} className="text-primary" />
              Top {similarPlayers.length} Similar{" "}
              {isBatter ? "Batters" : "Bowlers"}
            </h2>
            <select
              value={limit}
              onChange={(e) =>
                setLimit(parseInt(e.target.value) || DEFAULT_LIMIT)
              }
              className="filter-select text-xs"
              aria-label="Number of similar players"
            >
              <option value={10}>Top 10</option>
              <option value={15}>Top 15</option>
              <option value={25}>Top 25</option>
              <option value={50}>Top 50</option>
            </select>
          </div>

          {similarPlayers.length === 0 ? (
            <div className="text-center py-8">
              <Users size={40} className="text-text-muted mx-auto mb-3" />
              <p className="text-sm text-text-muted">
                No similar players found.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="sortable-table">
                <thead>
                  <tr>
                    <th className="w-8">#</th>
                    <th className="min-w-[140px]">Player</th>
                    <th className="text-right">Sim.</th>
                    <th className="text-right">
                      {scoreLabels.s1.slice(0, 3).toUpperCase()}
                    </th>
                    <th className="text-right">
                      {scoreLabels.s2.slice(0, 3).toUpperCase()}
                    </th>
                    <th className="text-right">
                      {scoreLabels.s3.slice(0, 3).toUpperCase()}
                    </th>
                    <th className="text-right">Country</th>
                  </tr>
                </thead>
                <tbody>
                  {similarPlayers.map((sp, i) => (
                    <tr
                      key={sp.id}
                      className="group cursor-pointer"
                      onClick={() => navigate(`/player/${sp.id}`)}
                    >
                      <td className="text-text-muted text-xs tabular-nums">
                        {i + 1}
                      </td>
                      <td>
                        <Link
                          to={`/player/${sp.id}`}
                          className="text-sm font-medium text-text-primary group-hover:text-primary transition-colors"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {sp.name}
                        </Link>
                      </td>
                      <td className="text-right">
                        <span className="font-score text-sm tabular-nums text-primary font-semibold">
                          {fmtSimilarity(sp.similarity_score)}
                        </span>
                      </td>
                      <td className="text-right">
                        <ScoreBarMini value={sp.score_1} width={40} />
                      </td>
                      <td className="text-right">
                        <ScoreBarMini value={sp.score_2} width={40} />
                      </td>
                      <td className="text-right">
                        <ScoreBarMini value={sp.score_3} width={40} />
                      </td>
                      <td className="text-right text-xs text-text-secondary">
                        {countryFlag(sp.country)} {sp.country}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Actions */}
          {similarPlayers.length > 0 && (
            <div className="mt-4 flex items-center gap-3 border-t border-surface-elevated pt-3">
              <button
                onClick={handleCompareTopSimilar}
                className="btn-primary btn-sm"
              >
                <GitCompare size={14} />
                Compare top 3
              </button>
              {similarPlayers.length > 0 && (
                <Link
                  to={`/similar/${similarPlayers[0].id}`}
                  className="btn-ghost btn-sm"
                >
                  View #{1}'s comps <ArrowRight size={14} />
                </Link>
              )}
            </div>
          )}
        </section>

        {/* ── Similarity Scatter Plot ──────────────────────── */}
        <section className="card p-4">
          <h2 className="text-h3 text-text-primary mb-2 flex items-center gap-2">
            <ZoomIn size={18} className="text-accent" />
            Similarity Map
          </h2>
          <p className="text-xs text-text-secondary mb-4">
            Players projected into 2D space based on their metric scores.
            <span className="text-gold font-semibold">
              {" "}
              ★ {profile.name}
            </span>{" "}
            is highlighted. Click any dot to navigate.
          </p>

          {scatterPoints.length <= 1 ? (
            <div className="text-center py-12">
              <p className="text-sm text-text-muted">
                Not enough data to render the scatter plot.
              </p>
            </div>
          ) : (
            <SimilarityScatter
              points={scatterPoints}
              labels={scoreLabels}
              onPointClick={handlePointClick}
            />
          )}

          {/* Legend */}
          <div className="mt-4 flex items-center gap-4 text-[10px] text-text-muted justify-center flex-wrap">
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full bg-gold" />
              Target Player
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full bg-primary" />
              Similar (High)
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full bg-warning" />
              Similar (Medium)
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full bg-danger" />
              Similar (Low)
            </div>
          </div>
        </section>
      </div>

      {/* Info box */}
      <div className="card p-4 border-l-4 border-l-primary">
        <div className="flex items-start gap-3">
          <Info size={18} className="text-primary shrink-0 mt-0.5" />
          <div className="text-sm text-text-secondary space-y-1">
            <p>
              <strong className="text-text-primary">
                How is similarity computed?
              </strong>{" "}
              Players are compared using cosine similarity across their three
              core metric scores ({scoreLabels.s1}, {scoreLabels.s2},{" "}
              {scoreLabels.s3}). A similarity of 1.00 means identical profiles;
              lower values indicate more divergent playing styles.
            </p>
            <p>
              The scatter plot projects these three dimensions into 2D for
              visualisation. Nearby players in the plot have similar metric
              profiles. Click any player to explore their comparables.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
