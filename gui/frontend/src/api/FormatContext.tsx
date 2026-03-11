/**
 * FormatContext — React context for the active cricket data format.
 *
 * Provides a global `format` state ("t20i" | "ipl") that:
 *   - Persists the user's choice in localStorage
 *   - Is available to all components via `useFormat()`
 *   - Integrates with TanStack Query by including `format` in query keys
 *   - Drives the `?format=` query parameter sent to all API calls
 *
 * Usage:
 *   // Wrap your app (in App.tsx):
 *   <FormatProvider>
 *     <RouterProvider router={router} />
 *   </FormatProvider>
 *
 *   // In any component:
 *   const { format, setFormat, formatLabel } = useFormat();
 *
 *   // In query hooks:
 *   const { format } = useFormat();
 *   useQuery({ queryKey: ["player", id, format], ... });
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import { setClientFormat } from "@/api/client";

// ── Types ────────────────────────────────────────────────────────

/** Supported data formats. */
export type Format = "t20i" | "ipl";

/** Human-readable labels for each format. */
export const FORMAT_LABELS: Record<Format, string> = {
  t20i: "T20I",
  ipl: "IPL",
};

/** Icons/emoji for each format. */
export const FORMAT_ICONS: Record<Format, string> = {
  t20i: "🌏",
  ipl: "🏆",
};

/** All valid format values. */
export const ALL_FORMATS: readonly Format[] = ["t20i", "ipl"] as const;

/** Default format when nothing is persisted. */
export const DEFAULT_FORMAT: Format = "t20i";

// ── LocalStorage persistence ─────────────────────────────────────

const STORAGE_KEY = "cricket_metrics_format";

function loadFormat(): Format {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && ALL_FORMATS.includes(stored as Format)) {
      return stored as Format;
    }
  } catch {
    // localStorage unavailable (SSR, privacy mode, etc.)
  }
  return DEFAULT_FORMAT;
}

function saveFormat(fmt: Format): void {
  try {
    localStorage.setItem(STORAGE_KEY, fmt);
  } catch {
    // Silently ignore storage failures
  }
}

// ── Context ──────────────────────────────────────────────────────

interface FormatContextValue {
  /** The currently active format. */
  format: Format;

  /** Change the active format. Persists to localStorage. */
  setFormat: (f: Format) => void;

  /** Human-readable label for the current format (e.g. "T20I"). */
  formatLabel: string;

  /** Emoji/icon for the current format. */
  formatIcon: string;

  /** List of formats the backend reported as available. Empty = not yet fetched. */
  availableFormats: Format[];
}

const FormatContext = createContext<FormatContextValue>({
  format: DEFAULT_FORMAT,
  setFormat: () => {},
  formatLabel: FORMAT_LABELS[DEFAULT_FORMAT],
  formatIcon: FORMAT_ICONS[DEFAULT_FORMAT],
  availableFormats: [],
});

// ── Provider ─────────────────────────────────────────────────────

interface FormatProviderProps {
  children: ReactNode;
}

export function FormatProvider({ children }: FormatProviderProps) {
  const [format, setFormatRaw] = useState<Format>(loadFormat);
  const [availableFormats, setAvailableFormats] = useState<Format[]>([]);

  // Keep the API client's module-level format in sync on initial load
  useEffect(() => {
    setClientFormat(format);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Persist to localStorage and sync with the API client whenever format changes
  const setFormat = useCallback((f: Format) => {
    setFormatRaw(f);
    saveFormat(f);
    setClientFormat(f);
  }, []);

  // On mount, fetch available formats from the backend
  useEffect(() => {
    let cancelled = false;

    async function fetchFormats() {
      try {
        const baseUrl = import.meta.env.VITE_API_URL ?? "";
        const resp = await fetch(`${baseUrl}/api/formats`);
        if (resp.ok) {
          const data: { formats: string[]; default: string } =
            await resp.json();
          if (!cancelled && Array.isArray(data.formats)) {
            const valid = data.formats.filter((f): f is Format =>
              ALL_FORMATS.includes(f as Format),
            );
            setAvailableFormats(valid);

            // If the user's stored format isn't available, reset to default
            if (valid.length > 0 && !valid.includes(format)) {
              const fallback = (data.default as Format) || valid[0];
              setFormat(fallback);
            }
          }
        }
      } catch {
        // Backend not reachable yet — that's fine, we'll use the default.
        // The format list will stay empty; the toggle can hide itself.
      }
    }

    fetchFormats();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value: FormatContextValue = {
    format,
    setFormat,
    formatLabel: FORMAT_LABELS[format],
    formatIcon: FORMAT_ICONS[format],
    availableFormats,
  };

  return (
    <FormatContext.Provider value={value}>{children}</FormatContext.Provider>
  );
}

// ── Hook ─────────────────────────────────────────────────────────

/**
 * Access the current format context.
 *
 * Must be used within a `<FormatProvider>`.
 */
export function useFormat(): FormatContextValue {
  const ctx = useContext(FormatContext);
  if (ctx === undefined) {
    throw new Error("useFormat() must be used within a <FormatProvider>");
  }
  return ctx;
}
