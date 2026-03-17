/**
 * ArchetypeBadge — styled label with icon for player archetypes.
 *
 * Displays a player's archetype (e.g. "Chase Master", "Wicket-Taker")
 * as a compact badge with an optional icon. The icon is derived from
 * a mapping of known archetypes to emoji/unicode glyphs, with a
 * fallback for unknown archetypes.
 *
 * Features:
 *   - Automatic icon selection based on archetype name
 *   - Compact pill and badge shape variants
 *   - Multiple size options (xs, sm, md, lg)
 *   - Click handler for filtering by archetype
 *   - Accessible: includes title and aria-label
 *   - Light/dark mode support via Tailwind classes
 *
 * Usage:
 *   <ArchetypeBadge archetype="Chase Master" />
 *   <ArchetypeBadge archetype="Wicket-Taker" size="lg" />
 *   <ArchetypeBadge archetype="Explosive Finisher" onClick={() => filterByArchetype('Explosive Finisher')} />
 *   <ArchetypeBadge archetype="Unknown" showIcon={false} />
 *
 * Follows gui.md § 7.1 Component Library — `<ArchetypeBadge>`.
 */

// ── Archetype → icon mapping ─────────────────────────────────────

const ARCHETYPE_ICONS: Record<string, string> = {
  // Batting archetypes
  Anchor: "A",
  "Chase Master": "C",
  "Explosive Finisher": "F",
  "Explosive Opener": "O",
  "Power Hitter": "P",
  "Power Middle-Order": "M",
  Accumulator: "U",
  "All-Phase": "L",
  "Aggressive Opener": "G",
  "Top-Order Anchor": "T",
  "Middle-Order Finisher": "N",
  Floater: "R",

  // Bowling archetypes
  "Wicket-Taker": "W",
  "Economy Specialist": "E",
  "Death Specialist": "D",
  "Powerplay Specialist": "P",
  "Spin Wizard": "S",
  "New Ball Specialist": "N",
  "Containing Bowler": "C",
  "Strike Bowler": "K",
  "All-Round Bowler": "B",

  // Generic / fallback
  "All-Rounder": "R",
  Unknown: "?",
};

/**
 * Look up the icon for a given archetype string.
 * Uses case-insensitive matching with fallback to a generic icon.
 */
function archetypeIcon(archetype: string): string {
  // Exact match first
  if (archetype in ARCHETYPE_ICONS) {
    return ARCHETYPE_ICONS[archetype];
  }

  // Case-insensitive match
  const lower = archetype.toLowerCase();
  for (const [key, icon] of Object.entries(ARCHETYPE_ICONS)) {
    if (key.toLowerCase() === lower) {
      return icon;
    }
  }

  // Partial match — check if any known key is a substring
  for (const [key, icon] of Object.entries(ARCHETYPE_ICONS)) {
    if (
      lower.includes(key.toLowerCase()) ||
      key.toLowerCase().includes(lower)
    ) {
      return icon;
    }
  }

  return "R";
}

// ── Archetype → colour mapping ───────────────────────────────────
// Subtle background tints to differentiate archetype categories

const ARCHETYPE_COLOURS: Record<
  string,
  { bg: string; text: string; darkBg: string; darkText: string }
> = {
  // Batting — warm tones
  Anchor: {
    bg: "bg-blue-100",
    text: "text-blue-800",
    darkBg: "bg-blue-500/15",
    darkText: "text-blue-300",
  },
  "Chase Master": {
    bg: "bg-emerald-100",
    text: "text-emerald-800",
    darkBg: "bg-emerald-500/15",
    darkText: "text-emerald-300",
  },
  "Explosive Finisher": {
    bg: "bg-amber-100",
    text: "text-amber-800",
    darkBg: "bg-amber-500/15",
    darkText: "text-amber-300",
  },
  "Explosive Opener": {
    bg: "bg-yellow-100",
    text: "text-yellow-800",
    darkBg: "bg-yellow-500/15",
    darkText: "text-yellow-300",
  },
  "Power Hitter": {
    bg: "bg-red-100",
    text: "text-red-800",
    darkBg: "bg-red-500/15",
    darkText: "text-red-300",
  },
  "Power Middle-Order": {
    bg: "bg-fuchsia-100",
    text: "text-fuchsia-800",
    darkBg: "bg-fuchsia-500/15",
    darkText: "text-fuchsia-300",
  },
  Accumulator: {
    bg: "bg-slate-100",
    text: "text-slate-800",
    darkBg: "bg-slate-500/15",
    darkText: "text-slate-300",
  },
  "All-Phase": {
    bg: "bg-purple-100",
    text: "text-purple-800",
    darkBg: "bg-purple-500/15",
    darkText: "text-purple-300",
  },
  "Aggressive Opener": {
    bg: "bg-orange-100",
    text: "text-orange-800",
    darkBg: "bg-orange-500/15",
    darkText: "text-orange-300",
  },

  // Bowling — cool tones
  "Wicket-Taker": {
    bg: "bg-rose-100",
    text: "text-rose-800",
    darkBg: "bg-rose-500/15",
    darkText: "text-rose-300",
  },
  "Economy Specialist": {
    bg: "bg-teal-100",
    text: "text-teal-800",
    darkBg: "bg-teal-500/15",
    darkText: "text-teal-300",
  },
  "Death Specialist": {
    bg: "bg-violet-100",
    text: "text-violet-800",
    darkBg: "bg-violet-500/15",
    darkText: "text-violet-300",
  },
  "Powerplay Specialist": {
    bg: "bg-cyan-100",
    text: "text-cyan-800",
    darkBg: "bg-cyan-500/15",
    darkText: "text-cyan-300",
  },
};

const DEFAULT_COLOUR = {
  bg: "bg-gray-100",
  text: "text-gray-700",
  darkBg: "bg-surface-elevated",
  darkText: "text-text-secondary",
};

function getArchetypeColour(archetype: string) {
  // Exact match
  if (archetype in ARCHETYPE_COLOURS) {
    return ARCHETYPE_COLOURS[archetype];
  }

  // Case-insensitive match
  const lower = archetype.toLowerCase();
  for (const [key, colour] of Object.entries(ARCHETYPE_COLOURS)) {
    if (key.toLowerCase() === lower) {
      return colour;
    }
  }

  // Partial match
  for (const [key, colour] of Object.entries(ARCHETYPE_COLOURS)) {
    if (lower.includes(key.toLowerCase())) {
      return colour;
    }
  }

  return DEFAULT_COLOUR;
}

// ── Size classes ─────────────────────────────────────────────────

const SIZE_CLASSES = {
  xs: {
    container: "px-1.5 py-0.5 text-[10px] leading-none gap-0.5",
    icon: "text-[10px]",
  },
  sm: {
    container: "px-2 py-0.5 text-xs leading-none gap-1",
    icon: "text-xs",
  },
  md: {
    container: "px-3 py-1 text-xs leading-none gap-1",
    icon: "text-sm",
  },
  lg: {
    container: "px-3 py-1.5 text-sm leading-none gap-1.5",
    icon: "text-base",
  },
} as const;

type BadgeSize = keyof typeof SIZE_CLASSES;

// ── Props ────────────────────────────────────────────────────────

interface ArchetypeBadgeProps {
  /** The archetype string (e.g. "Chase Master", "Wicket-Taker"). */
  archetype: string | null | undefined;
  /** Size variant. Default: "sm". */
  size?: BadgeSize;
  /** Whether to show the emoji icon. Default: true. */
  showIcon?: boolean;
  /** Shape variant. Default: "pill" (fully rounded). */
  shape?: "pill" | "badge";
  /** Whether to use archetype-specific colours. Default: true. */
  coloured?: boolean;
  /** Click handler (e.g. to filter by archetype). */
  onClick?: (archetype: string) => void;
  /** Additional CSS classes. */
  className?: string;
  /** Override the displayed label text. */
  label?: string;
}

// ── Component ────────────────────────────────────────────────────

export default function ArchetypeBadge({
  archetype,
  size = "sm",
  showIcon = true,
  shape = "pill",
  coloured = true,
  onClick,
  className = "",
  label,
}: ArchetypeBadgeProps) {
  const displayArchetype = archetype?.trim() || "Unknown";
  const displayLabel = label ?? displayArchetype;
  const icon = archetypeIcon(displayArchetype);
  const colours = coloured
    ? getArchetypeColour(displayArchetype)
    : DEFAULT_COLOUR;
  const sizeClasses = SIZE_CLASSES[size];
  const roundedClass = shape === "pill" ? "rounded-full" : "rounded-md";

  const isClickable = !!onClick;

  // Build the colour classes. In dark mode we use the dark variants,
  // in light mode the light variants. Using Tailwind's dark: prefix
  // doesn't work inline, so we use the html:not(.dark) pattern via
  // the parent approach. The simplest approach: just apply the dark
  // classes as defaults and light classes with the data attribute.
  // Since our theme uses the `html.dark` class, we can use:
  //   dark:bg-X  for dark mode
  //   bg-Y       for light mode (html:not(.dark))
  // But Tailwind only supports `dark:` prefix natively. We'll use
  // both and let the `darkMode: "class"` config handle it.

  const colourClasses = coloured
    ? `${colours.bg} ${colours.text} dark:${colours.darkBg} dark:${colours.darkText}`
    : "bg-gray-100 text-gray-700 dark:bg-surface-elevated dark:text-text-secondary";

  const Tag = isClickable ? "button" : "span";

  return (
    <Tag
      className={[
        "archetype-badge inline-flex items-center font-medium select-none",
        sizeClasses.container,
        roundedClass,
        colourClasses,
        isClickable
          ? "cursor-pointer transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary"
          : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      title={displayArchetype}
      aria-label={`Archetype: ${displayArchetype}`}
      onClick={isClickable ? () => onClick(displayArchetype) : undefined}
      {...(isClickable ? { type: "button" as const } : {})}
    >
      {showIcon && (
        <span className={sizeClasses.icon} aria-hidden="true">
          {icon}
        </span>
      )}
      <span className="truncate max-w-[12rem]">{displayLabel}</span>
    </Tag>
  );
}

// ── Variant: ArchetypeBadgeList ──────────────────────────────────
// Renders a list of archetype badges, useful for the archetype browser
// on the home page.

interface ArchetypeBadgeListProps {
  /** Array of archetype names. */
  archetypes: string[];
  /** Size of each badge. Default: "sm". */
  size?: BadgeSize;
  /** Click handler for a badge. */
  onSelect?: (archetype: string) => void;
  /** Additional CSS classes for the container. */
  className?: string;
  /** Gap between badges. Default: "gap-2". */
  gap?: string;
}

export function ArchetypeBadgeList({
  archetypes,
  size = "sm",
  onSelect,
  className = "",
  gap = "gap-2",
}: ArchetypeBadgeListProps) {
  if (!archetypes || archetypes.length === 0) return null;

  return (
    <div className={`flex flex-wrap items-center ${gap} ${className}`}>
      {archetypes.map((archetype) => (
        <ArchetypeBadge
          key={archetype}
          archetype={archetype}
          size={size}
          onClick={onSelect}
          coloured
        />
      ))}
    </div>
  );
}

// ── Variant: ArchetypeBadgeInline ────────────────────────────────
// Ultra-minimal inline text variant without background — just icon + text.

interface ArchetypeBadgeInlineProps {
  archetype: string | null | undefined;
  showIcon?: boolean;
  className?: string;
}

export function ArchetypeBadgeInline({
  archetype,
  showIcon = true,
  className = "",
}: ArchetypeBadgeInlineProps) {
  const displayArchetype = archetype?.trim() || "Unknown";
  const icon = archetypeIcon(displayArchetype);

  return (
    <span
      className={`inline-flex items-center gap-1 text-text-secondary text-xs ${className}`}
      title={displayArchetype}
    >
      {showIcon && <span aria-hidden="true">{icon}</span>}
      <span>{displayArchetype}</span>
    </span>
  );
}
