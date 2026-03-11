/**
 * Pagination — page navigation controls for paginated lists and tables.
 *
 * Renders a row of page buttons with prev/next arrows, current page
 * indicator, and optional page size selector. Designed for use with
 * the paginated API endpoints (leaderboards, innings log, matchups).
 *
 * Features:
 *   - Truncated page numbers for large page counts (1 2 … 5 6 7 … 20)
 *   - Prev/Next arrow buttons with disabled state
 *   - Current page highlighted
 *   - Optional "Showing X–Y of Z" summary text
 *   - Optional per-page size selector
 *   - Keyboard accessible
 *
 * Usage:
 *   <Pagination
 *     page={3}
 *     totalPages={20}
 *     onPageChange={(p) => setPage(p)}
 *   />
 *
 *   <Pagination
 *     page={1}
 *     totalPages={10}
 *     total={245}
 *     perPage={25}
 *     onPageChange={setPage}
 *     onPerPageChange={setPerPage}
 *     showSummary
 *   />
 */

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';

// ── Props ────────────────────────────────────────────────────────

interface PaginationProps {
  /** Current page number (1-indexed). */
  page: number;
  /** Total number of pages. */
  totalPages: number;
  /** Callback when the user navigates to a different page. */
  onPageChange: (page: number) => void;
  /** Total number of items (for the summary text). */
  total?: number;
  /** Items per page (for the summary text and per-page selector). */
  perPage?: number;
  /** Callback when the user changes the per-page size. */
  onPerPageChange?: (perPage: number) => void;
  /** Per-page size options. Default: [10, 25, 50, 100]. */
  perPageOptions?: number[];
  /** Whether to show the "Showing X–Y of Z" summary. Default: false. */
  showSummary?: boolean;
  /** Whether to show the per-page size selector. Default: false. */
  showPerPage?: boolean;
  /** Whether to show first/last page buttons. Default: false. */
  showEnds?: boolean;
  /** Maximum number of page buttons to show (excluding ellipsis). Default: 7. */
  maxButtons?: number;
  /** Additional CSS classes for the outer container. */
  className?: string;
  /** Size variant. Default: "md". */
  size?: 'sm' | 'md' | 'lg';
}

// ── Size classes ─────────────────────────────────────────────────

const BUTTON_SIZES = {
  sm: 'h-7 w-7 text-xs',
  md: 'h-9 w-9 text-sm',
  lg: 'h-11 w-11 text-base',
} as const;

const NAV_SIZES = {
  sm: 'h-7 px-2 text-xs',
  md: 'h-9 px-3 text-sm',
  lg: 'h-11 px-4 text-base',
} as const;

const ICON_SIZES = {
  sm: 14,
  md: 16,
  lg: 20,
} as const;

// ── Component ────────────────────────────────────────────────────

export default function Pagination({
  page,
  totalPages,
  onPageChange,
  total,
  perPage = 25,
  onPerPageChange,
  perPageOptions = [10, 25, 50, 100],
  showSummary = false,
  showPerPage = false,
  showEnds = false,
  maxButtons = 7,
  className = '',
  size = 'md',
}: PaginationProps) {
  // If there's only one page (or none), don't render pagination controls
  if (totalPages <= 1 && !showSummary && !showPerPage) {
    return null;
  }

  const buttonSize = BUTTON_SIZES[size];
  const navSize = NAV_SIZES[size];
  const iconSize = ICON_SIZES[size];

  // Compute the page numbers to display
  const pageNumbers = computePageNumbers(page, totalPages, maxButtons);

  // Compute summary text
  const summaryStart = total != null ? (page - 1) * perPage + 1 : null;
  const summaryEnd = total != null ? Math.min(page * perPage, total) : null;

  return (
    <div
      className={`flex flex-col sm:flex-row items-center justify-between gap-3 ${className}`}
      role="navigation"
      aria-label="Pagination"
    >
      {/* Left side: summary text and per-page selector */}
      <div className="flex items-center gap-3 text-text-secondary">
        {showSummary && total != null && summaryStart != null && summaryEnd != null && (
          <span className="text-sm">
            Showing{' '}
            <span className="font-medium text-text-primary">
              {summaryStart.toLocaleString()}–{summaryEnd.toLocaleString()}
            </span>{' '}
            of{' '}
            <span className="font-medium text-text-primary">
              {total.toLocaleString()}
            </span>
          </span>
        )}

        {showPerPage && onPerPageChange && (
          <div className="flex items-center gap-1.5">
            <label
              htmlFor="pagination-per-page"
              className="text-sm text-text-muted"
            >
              Show
            </label>
            <select
              id="pagination-per-page"
              value={perPage}
              onChange={(e) => {
                const newPerPage = parseInt(e.target.value, 10);
                onPerPageChange(newPerPage);
                // Reset to page 1 when changing page size
                onPageChange(1);
              }}
              className="filter-select text-xs py-1 px-2"
            >
              {perPageOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Right side: page buttons */}
      {totalPages > 1 && (
        <div className="flex items-center gap-1">
          {/* First page */}
          {showEnds && (
            <button
              onClick={() => onPageChange(1)}
              disabled={page <= 1}
              className={`pagination-btn ${navSize} ${
                page <= 1 ? 'opacity-30 cursor-not-allowed' : ''
              }`}
              aria-label="First page"
              title="First page"
            >
              <ChevronsLeft size={iconSize} />
            </button>
          )}

          {/* Previous page */}
          <button
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page <= 1}
            className={`pagination-btn ${navSize} ${
              page <= 1 ? 'opacity-30 cursor-not-allowed' : ''
            }`}
            aria-label="Previous page"
            title="Previous page"
          >
            <ChevronLeft size={iconSize} />
          </button>

          {/* Page number buttons */}
          {pageNumbers.map((pn, idx) => {
            if (pn === 'ellipsis') {
              return (
                <span
                  key={`ellipsis-${idx}`}
                  className={`${buttonSize} flex items-center justify-center text-text-muted select-none`}
                  aria-hidden="true"
                >
                  …
                </span>
              );
            }

            const isActive = pn === page;
            return (
              <button
                key={pn}
                onClick={() => onPageChange(pn)}
                className={`pagination-btn ${buttonSize} ${
                  isActive ? 'active' : ''
                }`}
                aria-label={`Page ${pn}`}
                aria-current={isActive ? 'page' : undefined}
              >
                {pn}
              </button>
            );
          })}

          {/* Next page */}
          <button
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages}
            className={`pagination-btn ${navSize} ${
              page >= totalPages ? 'opacity-30 cursor-not-allowed' : ''
            }`}
            aria-label="Next page"
            title="Next page"
          >
            <ChevronRight size={iconSize} />
          </button>

          {/* Last page */}
          {showEnds && (
            <button
              onClick={() => onPageChange(totalPages)}
              disabled={page >= totalPages}
              className={`pagination-btn ${navSize} ${
                page >= totalPages ? 'opacity-30 cursor-not-allowed' : ''
              }`}
              aria-label="Last page"
              title="Last page"
            >
              <ChevronsRight size={iconSize} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page number computation ──────────────────────────────────────

type PageItem = number | 'ellipsis';

/**
 * Compute which page numbers to render, inserting ellipsis markers
 * when there are too many pages to show. Always shows the first and
 * last page, with a window around the current page.
 *
 * Examples:
 *   computePageNumbers(1, 5, 7)   → [1, 2, 3, 4, 5]
 *   computePageNumbers(5, 20, 7)  → [1, 'ellipsis', 4, 5, 6, 'ellipsis', 20]
 *   computePageNumbers(1, 20, 7)  → [1, 2, 3, 4, 5, 'ellipsis', 20]
 *   computePageNumbers(20, 20, 7) → [1, 'ellipsis', 16, 17, 18, 19, 20]
 */
function computePageNumbers(
  current: number,
  total: number,
  maxButtons: number,
): PageItem[] {
  // If total pages fit within maxButtons, show them all
  if (total <= maxButtons) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const pages: PageItem[] = [];

  // We always show page 1 and page `total`.
  // The remaining slots are distributed around the current page.
  // Reserve 2 slots for first and last page.
  const sideSlots = maxButtons - 2;
  // Each ellipsis takes 1 slot.
  // Window size = sideSlots - (number of ellipsis markers)

  // Determine the window of pages around `current`
  const halfWindow = Math.floor((sideSlots - 2) / 2); // -2 for potential ellipses
  let windowStart = current - halfWindow;
  let windowEnd = current + halfWindow;

  // Adjust if window is too close to the beginning
  if (windowStart <= 2) {
    windowStart = 2;
    windowEnd = Math.min(total - 1, windowStart + sideSlots - 1);
  }

  // Adjust if window is too close to the end
  if (windowEnd >= total - 1) {
    windowEnd = total - 1;
    windowStart = Math.max(2, windowEnd - sideSlots + 1);
  }

  // Build the page list
  pages.push(1);

  if (windowStart > 2) {
    pages.push('ellipsis');
  }

  for (let i = windowStart; i <= windowEnd; i++) {
    if (i > 1 && i < total) {
      pages.push(i);
    }
  }

  if (windowEnd < total - 1) {
    pages.push('ellipsis');
  }

  pages.push(total);

  return pages;
}

// ── Simple text-based pagination for mobile ──────────────────────

interface PaginationSimpleProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}

export function PaginationSimple({
  page,
  totalPages,
  onPageChange,
  className = '',
}: PaginationSimpleProps) {
  if (totalPages <= 1) return null;

  return (
    <div
      className={`flex items-center justify-between gap-4 ${className}`}
      role="navigation"
      aria-label="Pagination"
    >
      <button
        onClick={() => onPageChange(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="btn-ghost btn-sm disabled:opacity-30"
      >
        ← Prev
      </button>

      <span className="text-sm text-text-secondary">
        Page{' '}
        <span className="font-medium text-text-primary">{page}</span>
        {' '}of{' '}
        <span className="font-medium text-text-primary">{totalPages}</span>
      </span>

      <button
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="btn-ghost btn-sm disabled:opacity-30"
      >
        Next →
      </button>
    </div>
  );
}
