/**
 * Resolve playing XIs from the most recent scorecard in the current format
 * where a team name matches (substring, case-insensitive).
 */

import api from "@/api/client";

function teamMatches(inningsLabel: unknown, query: string): boolean {
  const a = String(inningsLabel ?? "").trim().toLowerCase();
  const b = query.trim().toLowerCase();
  if (!a || !b) return false;
  return a.includes(b) || b.includes(a);
}

function asInningsMap(raw: unknown): Record<string, Record<string, unknown>> {
  if (!raw || typeof raw !== "object") return {};
  return raw as Record<string, Record<string, unknown>>;
}

/**
 * Batting order from the latest innings this team batted (by batting_position, else list order).
 */
export function extractBattingXiPlayerIds(
  scorecard: Record<string, unknown>,
  teamName: string,
): string[] {
  const innings = asInningsMap(scorecard.innings);
  const q = teamName.trim();
  if (!q) return [];

  for (const inn of Object.values(innings)) {
    if (!teamMatches(inn.batting_team, q)) continue;
    const batting = Array.isArray(inn.batting) ? inn.batting : [];
    const rows = [...batting] as Array<Record<string, unknown>>;
    rows.sort((a, b) => {
      const pa =
        typeof a.batting_position === "number" ? a.batting_position : 999;
      const pb =
        typeof b.batting_position === "number" ? b.batting_position : 999;
      return pa - pb;
    });
    const ids: string[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
      const id = row.batter_id;
      if (id == null || id === "") continue;
      const s = String(id);
      if (seen.has(s)) continue;
      seen.add(s);
      ids.push(s);
      if (ids.length >= 11) break;
    }
    if (ids.length > 0) return ids;
  }
  return [];
}

/**
 * Up to 11 distinct players who represented this team while bowling (by balls bowled),
 * then pad with teammates who batted in the same match if fewer than 11 bowlers.
 */
export function extractBowlingXiPlayerIds(
  scorecard: Record<string, unknown>,
  teamName: string,
): string[] {
  const innings = asInningsMap(scorecard.innings);
  const q = teamName.trim();
  if (!q) return [];

  const ids: string[] = [];
  const seen = new Set<string>();

  for (const inn of Object.values(innings)) {
    if (!teamMatches(inn.bowling_team, q)) continue;
    const bowling = Array.isArray(inn.bowling) ? inn.bowling : [];
    const rows = [...bowling] as Array<Record<string, unknown>>;
    rows.sort(
      (a, b) => (Number(b.balls) || 0) - (Number(a.balls) || 0),
    );
    for (const row of rows) {
      const id = row.bowler_id;
      if (id == null || id === "") continue;
      const s = String(id);
      if (seen.has(s)) continue;
      seen.add(s);
      ids.push(s);
      if (ids.length >= 11) return ids;
    }
  }

  if (ids.length >= 11) return ids.slice(0, 11);

  for (const inn of Object.values(innings)) {
    if (!teamMatches(inn.batting_team, q)) continue;
    const batting = Array.isArray(inn.batting) ? inn.batting : [];
    const rows = [...batting] as Array<Record<string, unknown>>;
    rows.sort((a, b) => {
      const pa =
        typeof a.batting_position === "number" ? a.batting_position : 999;
      const pb =
        typeof b.batting_position === "number" ? b.batting_position : 999;
      return pa - pb;
    });
    for (const row of rows) {
      const id = row.batter_id;
      if (id == null || id === "") continue;
      const s = String(id);
      if (seen.has(s)) continue;
      seen.add(s);
      ids.push(s);
      if (ids.length >= 11) return ids;
    }
  }

  return ids.slice(0, 11);
}

async function walkRecentMatchesForXi(
  teamName: string,
  extract: (sc: Record<string, unknown>, name: string) => string[],
  signal: AbortSignal,
): Promise<string[]> {
  const q = teamName.trim();
  if (!q) return [];

  const rows = await api.searchScorecards({ team: q, limit: 50 }, signal);
  for (const row of rows) {
    if (signal.aborted) return [];
    const mid = row.match_id;
    if (typeof mid !== "string" || !mid) continue;
    try {
      const sc = (await api.getScorecard(mid, signal)) as Record<
        string,
        unknown
      >;
      const ids = extract(sc, q);
      if (ids.length > 0) return ids.slice(0, 11);
    } catch {
      continue;
    }
  }
  return [];
}

export function fetchLastBattingXiPlayerIds(
  teamName: string,
  signal: AbortSignal,
): Promise<string[]> {
  return walkRecentMatchesForXi(
    teamName,
    extractBattingXiPlayerIds,
    signal,
  );
}

export function fetchLastBowlingXiPlayerIds(
  teamName: string,
  signal: AbortSignal,
): Promise<string[]> {
  return walkRecentMatchesForXi(
    teamName,
    extractBowlingXiPlayerIds,
    signal,
  );
}
