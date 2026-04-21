/**
 * Dismissible home hint — keyboard search shortcut (onboarding / discoverability).
 */

import { useState, useCallback } from "react";
import { X } from "lucide-react";

const STORAGE_KEY = "cricket-metrics-home-tip-dismissed";

export default function HomeWelcomeTip() {
  const [visible, setVisible] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem(STORAGE_KEY) !== "1";
    } catch {
      return true;
    }
  });

  const dismiss = useCallback(() => {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      /* localStorage unavailable */
    }
    setVisible(false);
  }, []);

  if (!visible) return null;

  return (
    <div
      className="mb-4 flex flex-col gap-2 rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between dark:border-white/[0.1] dark:bg-surface"
      role="status"
    >
      <p className="text-left text-sm text-text-secondary">
        <span className="font-semibold text-text-primary">Quick tip:</span>{" "}
        Press{" "}
        <kbd className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-800 dark:border-white/15 dark:bg-[#0a0a0a] dark:text-text-primary">
          ⌘K
        </kbd>{" "}
        or{" "}
        <kbd className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-800 dark:border-white/15 dark:bg-[#0a0a0a] dark:text-text-primary">
          Ctrl+K
        </kbd>{" "}
        from most pages to open player search.
      </p>
      <button
        type="button"
        onClick={dismiss}
        className="btn-ghost btn-sm shrink-0 gap-1.5 self-end sm:self-center"
        aria-label="Dismiss tip"
      >
        <X size={16} aria-hidden />
        Dismiss
      </button>
    </div>
  );
}
