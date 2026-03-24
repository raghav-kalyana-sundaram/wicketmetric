/**
 * Normalise team labels for tables (dedupe + short codes for franchise names).
 */

const TEAM_ABBR: Record<string, string> = {
  "chennai super kings": "CSK",
  "mumbai indians": "MI",
  "royal challengers bengaluru": "RCB",
  "royal challengers bangalore": "RCB",
  "kolkata knight riders": "KKR",
  "sunrisers hyderabad": "SRH",
  "delhi capitals": "DC",
  "punjab kings": "PBKS",
  "rajasthan royals": "RR",
  "lucknow super giants": "LSG",
  "gujarat titans": "GT",
  "gujarat lions": "GL",
  "rising pune supergiant": "RPS",
  "rising pune supergiants": "RPS",
  "pune warriors": "PWI",
  "deccan chargers": "DC",
  "kochi tuskers kerala": "KTK",
};

/** Collapse doubled team string (mirrors backend; safe for client-only data). */
export function collapseDuplicateTeamLabel(raw: string): string {
  const t = raw.trim();
  if (t.length < 6) return t;
  const n = t.length;
  for (let cut = Math.min(Math.floor(n / 2), 80); cut > 2; cut--) {
    const prefix = t.slice(0, cut).trimEnd();
    if (prefix.length < 3) continue;
    const rest = t.slice(cut).trimStart();
    if (rest.startsWith(prefix) || rest.startsWith(`${prefix} `)) {
      return prefix;
    }
  }
  const parts = t.split(/\s+/);
  if (parts.length >= 4) {
    for (let k = Math.floor(parts.length / 2); k > 0; k--) {
      const left = parts.slice(0, k).join(" ");
      const right = parts.slice(k).join(" ");
      if (right.startsWith(left)) return left;
    }
  }
  return t;
}

export function abbreviateTeamName(full: string): string {
  const s = collapseDuplicateTeamLabel(full).trim();
  if (!s) return "—";
  const key = s.toLowerCase();
  const hit = TEAM_ABBR[key];
  if (hit) return hit;
  const words = s.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return words
      .slice(0, 3)
      .map((w) => w[0]?.toUpperCase() ?? "")
      .join("")
      .slice(0, 4);
  }
  return s.slice(0, 4).toUpperCase();
}
