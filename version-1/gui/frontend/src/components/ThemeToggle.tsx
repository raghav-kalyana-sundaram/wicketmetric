/**
 * ThemeToggle — a button that switches between dark and light mode.
 *
 * Renders a sun icon (for switching to light) or moon icon (for switching
 * to dark) with a smooth rotation transition. Uses the `useTheme` hook
 * for state management and localStorage persistence.
 *
 * Usage:
 *   <ThemeToggle />
 *   <ThemeToggle size="lg" />
 *   <ThemeToggle showLabel />
 */

import { Sun, Moon } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";

// ── Types ────────────────────────────────────────────────────────

interface ThemeToggleProps {
  /** Icon size variant. */
  size?: "sm" | "md" | "lg";
  /** Whether to show a text label next to the icon. */
  showLabel?: boolean;
  /** Additional CSS classes for the button. */
  className?: string;
}

// ── Size mapping ─────────────────────────────────────────────────

const ICON_SIZES: Record<string, number> = {
  sm: 14,
  md: 18,
  lg: 22,
};

const BUTTON_SIZES: Record<string, string> = {
  sm: "h-7 w-7",
  md: "h-9 w-9",
  lg: "h-11 w-11",
};

// ── Component ────────────────────────────────────────────────────

export default function ThemeToggle({
  size = "md",
  showLabel = false,
  className = "",
}: ThemeToggleProps) {
  const { isDark, toggleTheme } = useTheme();
  const iconSize = ICON_SIZES[size] ?? ICON_SIZES.md;

  return (
    <button
      onClick={toggleTheme}
      className={`
        ${showLabel ? "inline-flex items-center gap-2 rounded-lg px-3 py-1.5" : `${BUTTON_SIZES[size] ?? BUTTON_SIZES.md} inline-flex items-center justify-center rounded-lg`}
        text-text-secondary hover:text-text-primary
        hover:bg-surface-elevated
        transition-colors duration-200 ease-out-quart
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary
        ${className}
      `.trim()}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      <span
        className="inline-block transition-transform duration-300 ease-out-quart"
        style={{
          transform: isDark ? "rotate(0deg)" : "rotate(180deg)",
        }}
      >
        {isDark ? (
          <Sun size={iconSize} className="text-text-secondary" />
        ) : (
          <Moon size={iconSize} className="text-primary" />
        )}
      </span>
      {showLabel && (
        <span className="text-sm font-medium">
          {isDark ? "Light" : "Dark"}
        </span>
      )}
    </button>
  );
}
