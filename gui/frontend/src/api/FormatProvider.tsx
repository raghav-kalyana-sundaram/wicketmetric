/**
 * FormatProvider — wraps the app and supplies FormatContext.
 */

import {
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import { setClientFormat } from "@/api/client";
import { FormatContext, type FormatContextValue } from "@/api/appFormatContext";
import {
  type Format,
  ALL_FORMATS,
  DEFAULT_FORMAT,
  FORMAT_ICONS,
  FORMAT_LABELS,
  migrateLegacyFormat,
} from "@/api/formatConstants";

const STORAGE_KEY = "cricket_metrics_format_v2";

function loadFormat(): Format {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const m = migrateLegacyFormat(stored);
      if (m) return m;
    }
    const legacy = localStorage.getItem("cricket_metrics_format");
    if (legacy) {
      const m = migrateLegacyFormat(legacy);
      if (m) return m;
    }
  } catch {
    /* localStorage unavailable */
  }
  return DEFAULT_FORMAT;
}

function saveFormat(fmt: Format): void {
  try {
    localStorage.setItem(STORAGE_KEY, fmt);
  } catch {
    /* ignore */
  }
}

interface FormatProviderProps {
  children: ReactNode;
}

export function FormatProvider({ children }: FormatProviderProps) {
  const [format, setFormatRaw] = useState<Format>(loadFormat);
  const [availableFormats, setAvailableFormats] = useState<Format[]>([]);

  useEffect(() => {
    setClientFormat(format);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setFormat = useCallback((f: Format) => {
    setFormatRaw(f);
    saveFormat(f);
    setClientFormat(f);
  }, []);

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

            if (valid.length > 0 && !valid.includes(format)) {
              const apiDefault = data.default as Format;
              const fallback = valid.includes(apiDefault)
                ? apiDefault
                : valid[0];
              setFormat(fallback);
            }
          }
        }
      } catch {
        /* backend unreachable */
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
