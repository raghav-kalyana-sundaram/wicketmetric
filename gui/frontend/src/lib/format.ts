/**
 * Number and string formatting utilities for the Cricket Metrics GUI.
 *
 * Provides consistent formatting for stats, scores, percentages, dates,
 * and other display values across all components.
 *
 * Usage:
 *   import { fmt, fmtPct, fmtScore, fmtDate } from '@/lib/format';
 *
 *   fmt(137.83, 1)   // "137.8"
 *   fmtPct(0.312)    // "31.2%"
 *   fmtScore(89.7)   // "89.7"
 *   fmtDate('2024-06-15')  // "15 Jun 2024"
 */

// ── Null-safe number formatting ──────────────────────────────────

/**
 * Format a number to a fixed number of decimal places.
 * Returns the fallback string for null/undefined/NaN values.
 *
 * @example
 *   fmt(137.834, 1)     // "137.8"
 *   fmt(null)            // "—"
 *   fmt(undefined, 2, 'N/A')  // "N/A"
 */
export function fmt(
  value: number | null | undefined,
  decimals: number = 1,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  return value.toFixed(decimals);
}

/**
 * Format a number as an integer (no decimal places).
 *
 * @example
 *   fmtInt(4008)    // "4,008"
 *   fmtInt(null)    // "—"
 */
export function fmtInt(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  return Math.round(value).toLocaleString("en-US");
}

/**
 * Format a raw number as an integer without comma separators.
 *
 * @example
 *   fmtIntRaw(4008)  // "4008"
 */
export function fmtIntRaw(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  return String(Math.round(value));
}

// ── Percentage formatting ────────────────────────────────────────

/**
 * Format a value as a percentage. If the value is already in 0–100 range,
 * it's displayed directly. If in 0–1 range, multiply by 100 first.
 *
 * @param value     The numeric value
 * @param decimals  Decimal places (default 1)
 * @param isRatio   If true, value is 0–1 and will be multiplied by 100
 *
 * @example
 *   fmtPct(31.2)          // "31.2%"
 *   fmtPct(0.312, 1, true)  // "31.2%"
 *   fmtPct(null)           // "—"
 */
export function fmtPct(
  value: number | null | undefined,
  decimals: number = 1,
  isRatio: boolean = false,
  fallback: string = "—",
): string {
  const pct = toPercentValue(value, isRatio);
  if (pct == null) return fallback;
  return `${pct.toFixed(decimals)}%`;
}

/**
 * Convert a numeric value into a display percentage.
 *
 * If ``isRatio`` is false and the absolute value is in [0, 1],
 * we still treat it as a ratio to avoid showing tiny percentages
 * from ratio-backed fields.
 */
export function toPercentValue(
  value: number | null | undefined,
  isRatio: boolean = false,
): number | null {
  if (value == null || isNaN(value) || !isFinite(value)) return null;
  if (isRatio || Math.abs(value) <= 1) return value * 100;
  return value;
}

// ── Matchup edge / pressure score formatting ────────────────────

const MATCHUP_EDGE_MULTIPLIER = 6;
const PRESSURE_BAT_SCALE = 2.5;
const PRESSURE_BOWL_SCALE = 0.35;

/**
 * Convert raw dominance index into a user-facing 0–100 matchup edge score.
 *
 * 0   = heavy bowler edge
 * 50  = even contest
 * 100 = heavy batter edge
 */
export function matchupEdgeScore(
  value: number | null | undefined,
): number | null {
  if (value == null || isNaN(value) || !isFinite(value)) return null;
  return Math.max(0, Math.min(100, 50 + value * MATCHUP_EDGE_MULTIPLIER));
}

/**
 * Human-readable matchup edge tier label.
 */
export function matchupEdgeLabel(value: number | null | undefined): string {
  const score = matchupEdgeScore(value);
  if (score == null) return "No data";
  if (score >= 80) return "Heavy batter edge";
  if (score >= 65) return "Batter edge";
  if (score >= 56) return "Slight batter edge";
  if (score >= 45) return "Even contest";
  if (score >= 36) return "Slight bowler edge";
  if (score >= 21) return "Bowler edge";
  return "Heavy bowler edge";
}

export function fmtMatchupEdge(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  const score = matchupEdgeScore(value);
  if (score == null) return fallback;
  return String(Math.round(score));
}

export type PressureRole = "bat" | "bowl";

/**
 * Convert raw clutch index into a user-facing 0–100 pressure score.
 *
 * Uses role-specific scaling because batting and bowling clutch ranges differ.
 */
export function pressureScore(
  value: number | null | undefined,
  role: PressureRole = "bat",
): number | null {
  if (value == null || isNaN(value) || !isFinite(value)) return null;
  const scale = role === "bowl" ? PRESSURE_BOWL_SCALE : PRESSURE_BAT_SCALE;
  const score = 50 + 45 * Math.tanh(value / scale);
  return Math.max(0, Math.min(100, score));
}

export function pressureLabel(
  value: number | null | undefined,
  role: PressureRole = "bat",
): string {
  const score = pressureScore(value, role);
  if (score == null) return "No data";
  if (score >= 80) return "Elite under pressure";
  if (score >= 65) return "Strong under pressure";
  if (score >= 56) return "Reliable under pressure";
  if (score >= 45) return "Neutral under pressure";
  if (score >= 36) return "Below par under pressure";
  return "Struggles under pressure";
}

export function fmtPressureScore(
  value: number | null | undefined,
  role: PressureRole = "bat",
  fallback: string = "—",
): string {
  const score = pressureScore(value, role);
  if (score == null) return fallback;
  return String(Math.round(score));
}

// ── Score formatting ─────────────────────────────────────────────

/**
 * Format a 0–100 score for display. Always shows one decimal place.
 *
 * @example
 *   fmtScore(89.7)   // "89.7"
 *   fmtScore(100)     // "100.0"
 *   fmtScore(null)    // "—"
 */
export function fmtScore(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  return value.toFixed(1);
}

/**
 * Format a score as an integer (for compact displays).
 *
 * @example
 *   fmtScoreCompact(89.7)  // "90"
 *   fmtScoreCompact(null)  // "—"
 */
export function fmtScoreCompact(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  return String(Math.round(value));
}

// ── Strike rate / economy formatting ─────────────────────────────

/**
 * Format a strike rate or economy rate (typically 1 decimal).
 *
 * @example
 *   fmtSR(137.83)   // "137.8"
 *   fmtSR(null)      // "—"
 */
export function fmtSR(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  return fmt(value, 1, fallback);
}

/**
 * Format a bowling economy rate.
 *
 * @example
 *   fmtEcon(6.84)   // "6.84"
 *   fmtEcon(null)    // "—"
 */
export function fmtEcon(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  return fmt(value, 2, fallback);
}

/**
 * Format a batting average.
 *
 * @example
 *   fmtAvg(52.73)  // "52.7"
 *   fmtAvg(null)   // "—"
 */
export function fmtAvg(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  return fmt(value, 1, fallback);
}

// ── Signed number formatting ─────────────────────────────────────

/**
 * Format a number with a leading + or - sign.
 * Useful for deltas, dominance indices, clutch indices, etc.
 *
 * @example
 *   fmtSigned(12.4)    // "+12.4"
 *   fmtSigned(-24.7)   // "-24.7"
 *   fmtSigned(0)        // "0.0"
 *   fmtSigned(null)     // "—"
 */
export function fmtSigned(
  value: number | null | undefined,
  decimals: number = 1,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(decimals)}`;
}

/**
 * Format as a signed integer.
 *
 * @example
 *   fmtSignedInt(7)   // "+7"
 *   fmtSignedInt(-3)  // "-3"
 */
export function fmtSignedInt(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  const rounded = Math.round(value);
  const prefix = rounded > 0 ? "+" : "";
  return `${prefix}${rounded}`;
}

// ── Similarity score ─────────────────────────────────────────────

/**
 * Format a cosine similarity score (0–1 range, show 2 decimals).
 *
 * @example
 *   fmtSimilarity(0.9412)  // "0.94"
 *   fmtSimilarity(null)    // "—"
 */
export function fmtSimilarity(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  return fmt(value, 2, fallback);
}

// ── Overs formatting ─────────────────────────────────────────────

/**
 * Format overs (cricket-specific: 4.3 means 4 overs and 3 balls).
 * The value from the API is already in this format.
 *
 * @example
 *   fmtOvers(24.3)  // "24.3"
 *   fmtOvers(null)  // "—"
 */
export function fmtOvers(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  return fmt(value, 1, fallback);
}

// ── WAR formatting ───────────────────────────────────────────────

/**
 * Format a WAR value (Wins Above Replacement). Shows 2 decimal places.
 *
 * @example
 *   fmtWAR(3.42)   // "3.42"
 *   fmtWAR(-0.18)  // "-0.18"
 *   fmtWAR(null)   // "—"
 */
export function fmtWAR(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  return fmt(value, 2, fallback);
}

// ── Date formatting ──────────────────────────────────────────────

const MONTHS_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/**
 * Format an ISO date string to a human-readable format.
 *
 * @example
 *   fmtDate('2024-06-15')             // "15 Jun 2024"
 *   fmtDate('2024-06-15T00:00:00Z')   // "15 Jun 2024"
 *   fmtDate(null)                      // "—"
 */
export function fmtDate(
  value: string | null | undefined,
  fallback: string = "—",
): string {
  if (!value) return fallback;
  try {
    const d = new Date(value);
    if (isNaN(d.getTime())) return fallback;
    const day = d.getUTCDate();
    const month = MONTHS_SHORT[d.getUTCMonth()];
    const year = d.getUTCFullYear();
    return `${day} ${month} ${year}`;
  } catch {
    return fallback;
  }
}

/**
 * Format a date as a short string (no year).
 *
 * @example
 *   fmtDateShort('2024-06-15')  // "15 Jun"
 */
export function fmtDateShort(
  value: string | null | undefined,
  fallback: string = "—",
): string {
  if (!value) return fallback;
  try {
    const d = new Date(value);
    if (isNaN(d.getTime())) return fallback;
    const day = d.getUTCDate();
    const month = MONTHS_SHORT[d.getUTCMonth()];
    return `${day} ${month}`;
  } catch {
    return fallback;
  }
}

/**
 * Format a date range for display (e.g. peak window).
 *
 * @example
 *   fmtDateRange('2016-03-01', '2018-02-28')  // "Mar 2016 – Feb 2018"
 *   fmtDateRange(null, null)                   // "—"
 */
export function fmtDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
  fallback: string = "—",
): string {
  if (!start && !end) return fallback;

  const fmtMonthYear = (val: string | null | undefined): string => {
    if (!val) return "?";
    try {
      const d = new Date(val);
      if (isNaN(d.getTime())) return "?";
      return `${MONTHS_SHORT[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    } catch {
      return "?";
    }
  };

  return `${fmtMonthYear(start)} – ${fmtMonthYear(end)}`;
}

// ── Country display ──────────────────────────────────────────────

/**
 * Map of country names to flag emoji. Covers all T20I nations.
 * Falls back to the country name if no emoji is found.
 */
const COUNTRY_FLAGS: Record<string, string> = {
  Afghanistan: "🇦🇫",
  Australia: "🇦🇺",
  Bangladesh: "🇧🇩",
  Canada: "🇨🇦",
  England: "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
  "Hong Kong": "🇭🇰",
  India: "🇮🇳",
  Ireland: "🇮🇪",
  Kenya: "🇰🇪",
  Namibia: "🇳🇦",
  Nepal: "🇳🇵",
  Netherlands: "🇳🇱",
  "New Zealand": "🇳🇿",
  Oman: "🇴🇲",
  Pakistan: "🇵🇰",
  "Papua New Guinea": "🇵🇬",
  Scotland: "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
  "South Africa": "🇿🇦",
  "Sri Lanka": "🇱🇰",
  "U.A.E.": "🇦🇪",
  UAE: "🇦🇪",
  "United Arab Emirates": "🇦🇪",
  "U.S.A.": "🇺🇸",
  USA: "🇺🇸",
  "United States of America": "🇺🇸",
  Uganda: "🇺🇬",
  "West Indies": "🌴",
  Zimbabwe: "🇿🇼",
  Jersey: "🇯🇪",
  Bermuda: "🇧🇲",
  Italy: "🇮🇹",
  Germany: "🇩🇪",
  Singapore: "🇸🇬",
  Malaysia: "🇲🇾",
  Thailand: "🇹🇭",
  Bahrain: "🇧🇭",
  Kuwait: "🇰🇼",
  Maldives: "🇲🇻",
  Qatar: "🇶🇦",
  "Saudi Arabia": "🇸🇦",
  Vanuatu: "🇻🇺",
  Philippines: "🇵🇭",
  Tanzania: "🇹🇿",
  Nigeria: "🇳🇬",
  Ghana: "🇬🇭",
  Rwanda: "🇷🇼",
  Botswana: "🇧🇼",
  Cameroon: "🇨🇲",
  Mozambique: "🇲🇿",
  "Czech Republic": "🇨🇿",
  Austria: "🇦🇹",
  Romania: "🇷🇴",
  Denmark: "🇩🇰",
  Sweden: "🇸🇪",
  Norway: "🇳🇴",
  Finland: "🇫🇮",
  Portugal: "🇵🇹",
  Spain: "🇪🇸",
  France: "🇫🇷",
  Belgium: "🇧🇪",
  Luxembourg: "🇱🇺",
};

/**
 * Get the flag emoji for a country. Returns empty string if unknown.
 *
 * @example
 *   countryFlag('India')        // "🇮🇳"
 *   countryFlag('West Indies')  // "🌴"
 *   countryFlag('Unknown')      // ""
 */
export function countryFlag(country: string | null | undefined): string {
  if (!country) return "";
  return COUNTRY_FLAGS[country] ?? "";
}

/**
 * Format a country with its flag emoji for display.
 *
 * @example
 *   fmtCountry('India')  // "India 🇮🇳"
 *   fmtCountry(null)     // "—"
 */
export function fmtCountry(
  country: string | null | undefined,
  fallback: string = "—",
): string {
  if (!country) return fallback;
  const flag = countryFlag(country);
  return flag ? `${country} ${flag}` : country;
}

/**
 * Short country abbreviations for compact displays.
 */
const COUNTRY_SHORT: Record<string, string> = {
  Afghanistan: "AFG",
  Australia: "AUS",
  Bangladesh: "BAN",
  Canada: "CAN",
  England: "ENG",
  "Hong Kong": "HK",
  India: "IND",
  Ireland: "IRE",
  Kenya: "KEN",
  Namibia: "NAM",
  Nepal: "NEP",
  Netherlands: "NED",
  "New Zealand": "NZ",
  Oman: "OMA",
  Pakistan: "PAK",
  "Papua New Guinea": "PNG",
  Scotland: "SCO",
  "South Africa": "SA",
  "Sri Lanka": "SL",
  "U.A.E.": "UAE",
  UAE: "UAE",
  "United Arab Emirates": "UAE",
  "U.S.A.": "USA",
  USA: "USA",
  "United States of America": "USA",
  Uganda: "UGA",
  "West Indies": "WI",
  Zimbabwe: "ZIM",
};

/**
 * Get a short abbreviation for a country name.
 *
 * @example
 *   countryShort('New Zealand')  // "NZ"
 *   countryShort('India')        // "IND"
 *   countryShort('Unknown')      // "Unknown"
 */
export function countryShort(
  country: string | null | undefined,
  fallback: string = "—",
): string {
  if (!country) return fallback;
  return COUNTRY_SHORT[country] ?? country;
}

// ── Role / label formatting ──────────────────────────────────────

/**
 * Convert a role string to a display label.
 *
 * @example
 *   fmtRole('bat')   // "Batter"
 *   fmtRole('bowl')  // "Bowler"
 */
export function fmtRole(role: string | null | undefined): string {
  if (!role) return "Unknown";
  switch (role.toLowerCase()) {
    case "bat":
      return "Batter";
    case "bowl":
      return "Bowler";
    case "all-rounder":
    case "allrounder":
    case "all_rounder":
      return "All-Rounder";
    default:
      return role;
  }
}

/**
 * Get the score metric labels for a given role.
 *
 * @example
 *   metricLabels('bat')  // { s1: 'Acceleration', s2: 'Power', s3: 'Control' }
 *   metricLabels('bowl') // { s1: 'Accuracy', s2: 'Control', s3: 'Threat' }
 */
export function metricLabels(role: string): {
  s1: string;
  s2: string;
  s3: string;
} {
  if (role === "bowl") {
    return { s1: "Accuracy", s2: "Control", s3: "Threat" };
  }
  return { s1: "Acceleration", s2: "Power", s3: "Control" };
}

/**
 * Get short metric labels (3 chars) for compact displays.
 */
export function metricLabelsShort(role: string): {
  s1: string;
  s2: string;
  s3: string;
} {
  if (role === "bowl") {
    return { s1: "ACC", s2: "CTL", s3: "THR" };
  }
  return { s1: "ACL", s2: "POW", s3: "CTL" };
}

// ── Ordinal formatting ───────────────────────────────────────────

/**
 * Format a number with its ordinal suffix.
 *
 * @example
 *   ordinal(1)   // "1st"
 *   ordinal(2)   // "2nd"
 *   ordinal(3)   // "3rd"
 *   ordinal(11)  // "11th"
 *   ordinal(21)  // "21st"
 */
export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

// ── Truncation ───────────────────────────────────────────────────

/**
 * Truncate a string to a maximum length, adding ellipsis if needed.
 *
 * @example
 *   truncate('Suryakumar Yadav', 12)  // "Suryakumar…"
 *   truncate('V Kohli', 12)           // "V Kohli"
 */
export function truncate(
  value: string | null | undefined,
  maxLength: number = 20,
): string {
  if (!value) return "";
  if (value.length <= maxLength) return value;
  return value.slice(0, maxLength - 1) + "…";
}

// ── Pluralisation ────────────────────────────────────────────────

/**
 * Simple pluralisation helper.
 *
 * @example
 *   plural(1, 'innings', 'innings')   // "1 innings"
 *   plural(5, 'match', 'matches')     // "5 matches"
 *   plural(0, 'wicket', 'wickets')    // "0 wickets"
 */
export function plural(
  count: number,
  singular: string,
  pluralForm?: string,
): string {
  const form = count === 1 ? singular : (pluralForm ?? `${singular}s`);
  return `${fmtInt(count)} ${form}`;
}

// ── Rank formatting ──────────────────────────────────────────────

/**
 * Format a rank number with optional "#" prefix.
 *
 * @example
 *   fmtRank(1)     // "#1"
 *   fmtRank(null)  // "—"
 */
export function fmtRank(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value)) return fallback;
  return `#${Math.round(value)}`;
}

// ── Percentile formatting ────────────────────────────────────────

/**
 * Format a percentile value for display.
 *
 * @example
 *   fmtPercentile(0.88)   // "top 12%"
 *   fmtPercentile(0.95)   // "top 5%"
 *   fmtPercentile(0.50)   // "top 50%"
 */
export function fmtPercentile(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  const pctile = Math.round((1 - value) * 100);
  return `top ${Math.max(1, pctile)}%`;
}

// ── Phase label ──────────────────────────────────────────────────

/**
 * Get a display label for a cricket phase.
 *
 * @example
 *   fmtPhase('powerplay')  // "Powerplay"
 *   fmtPhase('middle')     // "Middle"
 *   fmtPhase('death')      // "Death"
 */
export function fmtPhase(phase: string | null | undefined): string {
  if (!phase) return "—";
  switch (phase.toLowerCase()) {
    case "powerplay":
    case "pp":
      return "Powerplay";
    case "middle":
    case "mid":
      return "Middle";
    case "death":
      return "Death";
    default:
      // Capitalise first letter
      return phase.charAt(0).toUpperCase() + phase.slice(1).toLowerCase();
  }
}

// ── Compact large number formatting ──────────────────────────────

/**
 * Format a large number in compact form (e.g. 1.2K, 3.4M).
 *
 * @example
 *   fmtCompact(4008)     // "4K"
 *   fmtCompact(150000)   // "150K"
 *   fmtCompact(1500000)  // "1.5M"
 *   fmtCompact(42)       // "42"
 */
export function fmtCompact(
  value: number | null | undefined,
  fallback: string = "—",
): string {
  if (value == null || isNaN(value) || !isFinite(value)) return fallback;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000) {
    return `${sign}${(abs / 1_000_000).toFixed(1)}M`;
  }
  if (abs >= 1_000) {
    const k = abs / 1_000;
    return `${sign}${k >= 10 ? Math.round(k) : k.toFixed(1)}K`;
  }
  return `${sign}${Math.round(abs)}`;
}

// ── Query param helpers ──────────────────────────────────────────

/**
 * Build a clean query string from an object, omitting null/undefined values.
 * Useful for constructing shareable URLs with filter state.
 *
 * @example
 *   buildQueryString({ q: 'kohli', country: 'India', role: null })
 *   // "q=kohli&country=India"
 */
export function buildQueryString(
  params: Record<string, string | number | boolean | null | undefined>,
): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== "") {
      searchParams.set(key, String(value));
    }
  }
  return searchParams.toString();
}

/**
 * Parse a query parameter as an integer, with a default fallback.
 */
export function parseIntParam(
  value: string | null | undefined,
  defaultValue: number,
): number {
  if (!value) return defaultValue;
  const parsed = parseInt(value, 10);
  return isNaN(parsed) ? defaultValue : parsed;
}

/**
 * Parse a query parameter as a boolean.
 * Recognises "true", "1", "yes" as true; "false", "0", "no" as false.
 */
export function parseBoolParam(
  value: string | null | undefined,
): boolean | undefined {
  if (!value) return undefined;
  const lower = value.toLowerCase().trim();
  if (lower === "true" || lower === "1" || lower === "yes") return true;
  if (lower === "false" || lower === "0" || lower === "no") return false;
  return undefined;
}

/**
 * Primary number for list/card views: **current** (recent rolling form) when
 * the API sends it, else legacy `overall_score`.
 */
export function primaryDisplayRating(p: {
  rating_current?: number | null;
  overall_score?: number | null;
}): number | null {
  const c = p.rating_current;
  if (c != null && !Number.isNaN(c)) return c;
  return p.overall_score ?? null;
}

/**
 * Career-style headline for expanded views / “overall” column: API
 * `rating_overall` when present, else pipeline `overall_score`.
 */
export function careerDisplayRating(p: {
  rating_overall?: number | null;
  overall_score?: number | null;
}): number | null {
  const o = p.rating_overall;
  if (o != null && !Number.isNaN(o)) return o;
  return p.overall_score ?? null;
}
