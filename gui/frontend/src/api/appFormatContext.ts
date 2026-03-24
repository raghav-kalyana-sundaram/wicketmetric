/**
 * React context instance for format (provider lives in FormatProvider.tsx).
 */

import { createContext } from "react";
import type { Format } from "@/api/formatConstants";

export interface FormatContextValue {
  format: Format;
  setFormat: (f: Format) => void;
  formatLabel: string;
  formatIcon: string;
  availableFormats: Format[];
}

export const FormatContext = createContext<FormatContextValue | null>(null);
