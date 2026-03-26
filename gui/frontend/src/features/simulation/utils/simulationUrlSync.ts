/**
 * Shareable query params for Simulation Hub lineups (comma-separated player ids).
 */

const BAT = "bat";
const BOWL = "bowl";

export function simulationLineupToSearchParams(
  battingIds: string[],
  bowlingIds: string[],
): URLSearchParams {
  const u = new URLSearchParams();
  if (battingIds.length) u.set(BAT, battingIds.join(","));
  if (bowlingIds.length) u.set(BOWL, bowlingIds.join(","));
  return u;
}

export function parseSimulationLineupParams(search: string): {
  batIds: string[];
  bowlIds: string[];
} {
  const u = new URLSearchParams(search);
  const bat = u.get(BAT);
  const bowl = u.get(BOWL);
  return {
    batIds: bat ? bat.split(",").map((s) => s.trim()).filter(Boolean) : [],
    bowlIds: bowl ? bowl.split(",").map((s) => s.trim()).filter(Boolean) : [],
  };
}
