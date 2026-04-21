/**
 * Sticky notice when the backend has no DuckDB dataset (health degraded / meta not loaded).
 */

import { AlertTriangle } from "lucide-react";

export default function DatasetUnavailableBanner({
  reason,
}: {
  /** Optional extra line from `/api/health` (e.g. "Data not loaded"). */
  reason?: string | null;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="border-b border-amber-500/35 bg-amber-500/10 text-amber-950 dark:border-amber-400/25 dark:bg-amber-400/10 dark:text-amber-50"
    >
      <div className="mx-auto flex max-w-7xl items-start gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <AlertTriangle
          className="mt-0.5 h-5 w-5 shrink-0 text-amber-700 dark:text-amber-300"
          aria-hidden
        />
        <div className="min-w-0 text-sm leading-snug">
          <p className="font-medium text-amber-950 dark:text-amber-100">
            Player and leaderboard data is not loaded on this server.
          </p>
          <p className="mt-1 text-amber-900/90 dark:text-amber-100/85">
            Point <code className="rounded bg-amber-500/15 px-1 py-0.5 font-mono text-xs dark:bg-amber-400/15">
              DUCKDB_PATH
            </code>{" "}
            at a <span className="whitespace-nowrap">cricket.duckdb</span> file, or set{" "}
            <code className="rounded bg-amber-500/15 px-1 py-0.5 font-mono text-xs dark:bg-amber-400/15">
              DUCKDB_REMOTE_URL
            </code>{" "}
            to fetch one. See{" "}
            <code className="rounded bg-amber-500/15 px-1 py-0.5 font-mono text-xs dark:bg-amber-400/15">
              gui/README.md
            </code>{" "}
            in the repo.
          </p>
          {reason ? (
            <p className="mt-1.5 text-xs text-amber-800/80 dark:text-amber-200/70">
              {reason}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
