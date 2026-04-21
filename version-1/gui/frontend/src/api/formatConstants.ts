/**
 * Format constants — API `?format=` values and UI labels.
 * Two-step UX: gender (men / women) × competition (T20 intl / IPL).
 */

/** Supported data formats (matches backend VALID_FORMATS). */
export type Format =
  | "mens_t20i"
  | "womens_t20i"
  | "mens_ipl"
  | "womens_ipl";

export type Gender = "men" | "women";
export type Competition = "t20" | "ipl";

/** Human-readable labels (product copy). */
export const FORMAT_LABELS: Record<Format, string> = {
  mens_t20i: "Men's T20",
  womens_t20i: "Women's T20",
  mens_ipl: "Men's IPL",
  womens_ipl: "Women's IPL",
};

export const FORMAT_ICONS: Record<Format, string> = {
  mens_t20i: "MT",
  womens_t20i: "WT",
  mens_ipl: "MI",
  womens_ipl: "WI",
};

export const ALL_FORMATS: readonly Format[] = [
  "mens_t20i",
  "womens_t20i",
  "mens_ipl",
  "womens_ipl",
] as const;

export const DEFAULT_FORMAT: Format = "mens_t20i";

const LEGACY_FORMAT_MAP: Record<string, Format> = {
  t20i: "mens_t20i",
  ipl: "mens_ipl",
  womens_t20: "womens_t20i",
};

/** Map old persisted keys to current format slugs. */
export function migrateLegacyFormat(stored: string): Format | null {
  if (ALL_FORMATS.includes(stored as Format)) return stored as Format;
  return LEGACY_FORMAT_MAP[stored] ?? null;
}

export function formatFromGenderComp(
  gender: Gender,
  competition: Competition,
): Format {
  if (gender === "men" && competition === "t20") return "mens_t20i";
  if (gender === "men" && competition === "ipl") return "mens_ipl";
  if (gender === "women" && competition === "t20") return "womens_t20i";
  return "womens_ipl";
}

export function genderCompFromFormat(f: Format): {
  gender: Gender;
  competition: Competition;
} {
  switch (f) {
    case "mens_t20i":
      return { gender: "men", competition: "t20" };
    case "mens_ipl":
      return { gender: "men", competition: "ipl" };
    case "womens_t20i":
      return { gender: "women", competition: "t20" };
    default:
      return { gender: "women", competition: "ipl" };
  }
}

export function isFranchiseFormat(f: Format): boolean {
  return f === "mens_ipl" || f === "womens_ipl";
}
