import type { PlayerProfile, PlayerSummary } from "@/api/types";

/** Map a full API profile to the compact summary shape used by autocomplete and team UIs. */
export function profileToPlayerSummary(profile: PlayerProfile): PlayerSummary {
  const isBat = "score_acceleration" in profile;
  const p = profile as unknown as Record<string, unknown>;
  return {
    id: profile.id,
    name: profile.name,
    country: profile.country,
    role: isBat ? "bat" : "bowl",
    archetype: profile.archetype,
    grade_overall: String(p.overall_grade ?? "D"),
    innings_count: isBat
      ? ((p.innings_count as number) ?? 0)
      : ((p.matches as number) ?? 0),
    total_runs: isBat
      ? ((p.total_runs as number) ?? 0)
      : ((p.total_wickets as number) ?? 0),
    career_sr: isBat
      ? (p.career_sr as number | null) ?? null
      : (p.career_economy as number | null) ?? null,
    career_avg: (p.career_avg as number | null) ?? null,
    score_1: isBat
      ? (p.score_acceleration as number | null) ?? null
      : (p.score_accuracy as number | null) ?? null,
    score_2: isBat
      ? (p.score_power as number | null) ?? null
      : (p.score_control as number | null) ?? null,
    score_3: isBat
      ? (p.score_control as number | null) ?? null
      : (p.score_threat as number | null) ?? null,
    score_1_label: isBat ? "acceleration" : "accuracy",
    score_2_label: isBat ? "power" : "control",
    score_3_label: isBat ? "control" : "threat",
    is_provisional: (p.is_provisional as boolean) ?? true,
    overall_score: (p.overall_score as number | null) ?? null,
    rating_current: (p.rating_current as number | null) ?? null,
    rating_overall: (p.rating_overall as number | null) ?? null,
    modal_position: isBat ? ((p.modal_position as number | null) ?? null) : null,
    recent_team: (p.recent_team as string | null) ?? null,
  };
}
