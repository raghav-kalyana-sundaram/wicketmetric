/**
 * useTheme — hook for managing dark/light mode with localStorage persistence.
 *
 * The theme is stored in localStorage under the key "cricket-metrics-theme".
 * On first load, it respects the user's OS preference via
 * `prefers-color-scheme: dark`. The hook toggles the `dark` class on the
 * `<html>` element, which Tailwind's `darkMode: "class"` strategy uses.
 *
 * Usage:
 *   const { theme, toggleTheme, setTheme, isDark } = useTheme();
 *
 *   <button onClick={toggleTheme}>
 *     {isDark ? "Light" : "Dark"}
 *   </button>
 */

import { useState, useEffect, useCallback } from "react";

// ── Types ────────────────────────────────────────────────────────

export type Theme = "dark" | "light";

const STORAGE_KEY = "cricket-metrics-theme";

// ── Helpers ──────────────────────────────────────────────────────

/**
 * Read the saved theme from localStorage, falling back to OS preference.
 */
function getInitialTheme(): Theme {
  // 1. Check localStorage
  if (typeof window !== "undefined") {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "dark" || stored === "light") {
        return stored;
      }
    } catch {
      // localStorage might be blocked (e.g. incognito in some browsers)
    }

    // 2. Check OS preference
    if (window.matchMedia?.("(prefers-color-scheme: light)").matches) {
      return "light";
    }
  }

  // 3. Default to dark (the app's primary design)
  return "dark";
}

/**
 * Apply the theme to the DOM by toggling the `dark` class on <html>.
 */
function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;

  const root = document.documentElement;

  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }

  // Also set a meta theme-color for mobile browsers
  const metaThemeColor = document.querySelector('meta[name="theme-color"]');
  if (metaThemeColor) {
    metaThemeColor.setAttribute(
      "content",
      theme === "dark" ? "#06080C" : "#EEF1F5",
    );
  }
}

/**
 * Persist the theme choice to localStorage.
 */
function persistTheme(theme: Theme): void {
  if (typeof window === "undefined") return;

  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Silently fail if localStorage is unavailable
  }
}

// ── Hook ─────────────────────────────────────────────────────────

export interface UseThemeReturn {
  /** The current theme ("dark" | "light"). */
  theme: Theme;

  /** Whether the current theme is dark mode. */
  isDark: boolean;

  /** Toggle between dark and light mode. */
  toggleTheme: () => void;

  /** Set the theme to a specific value. */
  setTheme: (theme: Theme) => void;
}

export function useTheme(): UseThemeReturn {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);

  // Apply theme to DOM on mount and whenever it changes
  useEffect(() => {
    applyTheme(theme);
    persistTheme(theme);
  }, [theme]);

  // Listen for OS preference changes (e.g. system dark mode toggle)
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const handler = (e: MediaQueryListEvent) => {
      // Only follow OS preference if the user hasn't explicitly set a theme
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (!stored) {
          setThemeState(e.matches ? "dark" : "light");
        }
      } catch {
        setThemeState(e.matches ? "dark" : "light");
      }
    };

    mediaQuery.addEventListener("change", handler);
    return () => mediaQuery.removeEventListener("change", handler);
  }, []);

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  return {
    theme,
    isDark: theme === "dark",
    toggleTheme,
    setTheme,
  };
}

export default useTheme;
