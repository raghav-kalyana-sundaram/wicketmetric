/**
 * Format-aware team name hints for the Simulation Hub combobox.
 * Users can always type values not in these lists.
 */

import type { Format } from "@/api/formatConstants";

const IPL_MENS = [
  "Chennai Super Kings",
  "Mumbai Indians",
  "Royal Challengers Bengaluru",
  "Kolkata Knight Riders",
  "Sunrisers Hyderabad",
  "Rajasthan Royals",
  "Delhi Capitals",
  "Punjab Kings",
  "Lucknow Super Giants",
  "Gujarat Titans",
] as const;

const IPL_WOMENS = [
  "Mumbai Indians",
  "Delhi Capitals",
  "Royal Challengers Bengaluru",
  "Gujarat Giants",
  "UP Warriorz",
] as const;

/** Common Full Member sides + frequent associates (Cricsheet-style names). */
const INTL_TEAMS = [
  "India",
  "Australia",
  "England",
  "Pakistan",
  "New Zealand",
  "South Africa",
  "Sri Lanka",
  "West Indies",
  "Bangladesh",
  "Afghanistan",
  "Ireland",
  "Scotland",
  "Netherlands",
  "Nepal",
  "Namibia",
  "Oman",
  "Papua New Guinea",
  "United Arab Emirates",
  "United States of America",
  "Canada",
] as const;

export function suggestionsForFormat(format: Format): readonly string[] {
  switch (format) {
    case "mens_ipl":
      return IPL_MENS;
    case "womens_ipl":
      return IPL_WOMENS;
    default:
      return INTL_TEAMS;
  }
}

export function filterTeamSuggestions(
  format: Format,
  query: string,
  limit = 12,
): string[] {
  const q = query.trim().toLowerCase();
  const all = suggestionsForFormat(format);
  if (!q) return [...all].slice(0, limit);
  return all
    .filter((t) => t.toLowerCase().includes(q))
    .slice(0, limit);
}
