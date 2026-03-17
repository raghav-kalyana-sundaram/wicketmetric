/**
 * FormatToggle — pill-shaped toggle button for switching between
 * T20I and IPL datasets.
 *
 * Renders in the navigation bar. Only shows when the backend reports
 * more than one available format. Highlights the active format and
 * smoothly transitions between states.
 *
 * Usage:
 *   import FormatToggle from '@/components/FormatToggle';
 *   <FormatToggle />
 */

import {
  useFormat,
  ALL_FORMATS,
  FORMAT_LABELS,
  type Format,
} from "@/api/FormatContext";
import { useQueryClient } from "@tanstack/react-query";

interface FormatToggleProps {
  /** Optional extra CSS classes on the outer wrapper. */
  className?: string;
}

export default function FormatToggle({ className = "" }: FormatToggleProps) {
  const { format, setFormat, availableFormats } = useFormat();
  const queryClient = useQueryClient();

  // Don't render if only one (or zero) formats are available
  if (availableFormats.length <= 1) {
    return null;
  }

  const handleSwitch = (f: Format) => {
    if (f === format) return;
    setFormat(f);
    // Invalidate all queries so they re-fetch with the new format
    queryClient.invalidateQueries();
  };

  return (
    <div
      className={`flex items-center bg-surface-elevated rounded-lg p-0.5 gap-0.5 ${className}`}
      role="radiogroup"
      aria-label="Data format"
    >
      {ALL_FORMATS.filter((f) => availableFormats.includes(f)).map((f) => {
        const isActive = f === format;
        return (
          <button
            key={f}
            role="radio"
            aria-checked={isActive}
            onClick={() => handleSwitch(f)}
            className={`
              px-2.5 py-1 text-xs font-medium rounded-md
              transition-all duration-200 ease-out
              flex items-center gap-1 whitespace-nowrap
              focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50
              ${
                isActive
                  ? "bg-primary text-white shadow-sm"
                  : "text-text-muted hover:text-text-secondary hover:bg-surface"
              }
            `}
            title={`Switch to ${FORMAT_LABELS[f]} data`}
          >
            <span>{FORMAT_LABELS[f]}</span>
          </button>
        );
      })}
    </div>
  );
}
