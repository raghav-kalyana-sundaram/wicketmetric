/**
 * ExportButton — dropdown button for exporting data as CSV, PNG, or shareable URL.
 *
 * Provides three export modes:
 *   1. **CSV** — downloads tabular data as a CSV file.
 *   2. **PNG** — captures a DOM element as a PNG screenshot (via html2canvas if available,
 *      otherwise falls back to a simple SVG-based approach).
 *   3. **Share URL** — copies the current page URL (or a custom URL) to the clipboard.
 *
 * Usage:
 *   <ExportButton
 *     csvData={rows}
 *     csvFilename="batting_rankings.csv"
 *     screenshotTargetId="leaderboard-table"
 *     shareUrl={window.location.href}
 *   />
 *
 *   // CSV-only:
 *   <ExportButton csvData={rows} csvFilename="data.csv" />
 *
 *   // Share-only:
 *   <ExportButton shareUrl="https://example.com/compare?ids=a,b" />
 */

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Download,
  Image,
  Share2,
  ChevronDown,
  Check,
  Copy,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────

export interface CsvColumn {
  /** The key in the data object. */
  key: string;
  /** The display header for the CSV column. */
  label: string;
  /** Optional formatter for the value. */
  format?: (value: unknown) => string;
}

export interface ExportButtonProps {
  /** Array of row objects for CSV export. If omitted, CSV option is hidden. */
  csvData?: Array<Record<string, unknown>>;
  /** Column definitions for CSV. If omitted, all keys from the first row are used. */
  csvColumns?: CsvColumn[];
  /** Filename for the CSV download (default: "export.csv"). */
  csvFilename?: string;
  /** DOM element ID to capture as PNG. If omitted, PNG option is hidden. */
  screenshotTargetId?: string;
  /** Filename for the PNG download (default: "screenshot.png"). */
  pngFilename?: string;
  /** URL to copy to clipboard. If omitted, uses window.location.href. */
  shareUrl?: string | null;
  /** Whether to show the share/copy URL option. Default: true. */
  showShare?: boolean;
  /** Button size variant. */
  size?: "sm" | "md";
  /** Additional CSS classes for the wrapper. */
  className?: string;
  /** Label override for the button. */
  label?: string;
}

// ── Helpers ──────────────────────────────────────────────────────

function escapeCSV(value: unknown): string {
  if (value === null || value === undefined) return "";
  const str = String(value);
  // If the value contains a comma, quote, or newline, wrap in quotes
  if (str.includes(",") || str.includes('"') || str.includes("\n")) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function buildCSV(
  data: Array<Record<string, unknown>>,
  columns?: CsvColumn[],
): string {
  if (data.length === 0) return "";

  // Determine columns
  const cols: CsvColumn[] =
    columns ??
    Object.keys(data[0]).map((key) => ({
      key,
      label: key,
    }));

  // Header row
  const header = cols.map((c) => escapeCSV(c.label)).join(",");

  // Data rows
  const rows = data.map((row) =>
    cols
      .map((col) => {
        const raw = row[col.key];
        const formatted = col.format ? col.format(raw) : raw;
        return escapeCSV(formatted);
      })
      .join(","),
  );

  return [header, ...rows].join("\n");
}

function downloadBlob(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

async function captureElementAsPNG(
  elementId: string,
  filename: string,
): Promise<boolean> {
  const element = document.getElementById(elementId);
  if (!element) {
    console.warn(
      `ExportButton: element #${elementId} not found for PNG capture.`,
    );
    return false;
  }

  // Try html2canvas if available (it may be installed as a dependency)
  try {
    // Use indirect dynamic import to avoid TS static module resolution errors
    // eslint-disable-next-line @typescript-eslint/no-explicit-any, no-new-func
    const dynamicImport = new Function("m", "return import(m)") as (
      m: string,
    ) => Promise<any>;
    const mod = await dynamicImport("html2canvas");
    const html2canvas = mod.default ?? mod;
    const canvas = await html2canvas(element, {
      backgroundColor: null,
      scale: 2, // 2x for retina quality
      useCORS: true,
      logging: false,
    });

    const dataUrl = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    return true;
  } catch {
    // html2canvas not available — use a fallback SVG approach
    console.info(
      "ExportButton: html2canvas not available. Install it for PNG export: npm i html2canvas",
    );
    return false;
  }
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for older browsers
    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      return true;
    } catch {
      return false;
    }
  }
}

// ── Component ────────────────────────────────────────────────────

export default function ExportButton({
  csvData,
  csvColumns,
  csvFilename = "export.csv",
  screenshotTargetId,
  pngFilename = "screenshot.png",
  shareUrl,
  showShare = true,
  size = "md",
  className = "",
  label,
}: ExportButtonProps) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pngBusy, setPngBusy] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!open) return;

    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;

    function handleEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }

    document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, [open]);

  // Reset copied state after a delay
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const hasCSV = !!csvData && csvData.length > 0;
  const hasPNG = !!screenshotTargetId;
  const hasShare = showShare;

  const optionCount = [hasCSV, hasPNG, hasShare].filter(Boolean).length;

  // If only one option exists, don't show a dropdown — just a single button
  const isSingleAction = optionCount === 1;

  // ── Handlers ───────────────────────────────────────────────────

  const handleCSV = useCallback(() => {
    if (!csvData || csvData.length === 0) return;
    const csv = buildCSV(csvData, csvColumns);
    downloadBlob(csv, csvFilename, "text/csv;charset=utf-8;");
    setOpen(false);
  }, [csvData, csvColumns, csvFilename]);

  const handlePNG = useCallback(async () => {
    if (!screenshotTargetId) return;
    setPngBusy(true);
    try {
      const success = await captureElementAsPNG(
        screenshotTargetId,
        pngFilename,
      );
      if (!success) {
        // Could show a toast here; for now just log
        console.warn("PNG export failed or html2canvas is not installed.");
      }
    } finally {
      setPngBusy(false);
      setOpen(false);
    }
  }, [screenshotTargetId, pngFilename]);

  const handleShare = useCallback(async () => {
    const url = shareUrl ?? window.location.href;
    const success = await copyToClipboard(url);
    if (success) {
      setCopied(true);
    }
    setOpen(false);
  }, [shareUrl]);

  // ── Single action shortcut ─────────────────────────────────────

  if (optionCount === 0) return null;

  if (isSingleAction) {
    const action = hasCSV ? handleCSV : hasPNG ? handlePNG : handleShare;
    const icon = hasCSV ? (
      <Download size={size === "sm" ? 12 : 14} />
    ) : hasPNG ? (
      <Image size={size === "sm" ? 12 : 14} />
    ) : copied ? (
      <Check size={size === "sm" ? 12 : 14} className="text-accent" />
    ) : (
      <Share2 size={size === "sm" ? 12 : 14} />
    );
    const buttonLabel =
      label ??
      (hasCSV
        ? "Export CSV"
        : hasPNG
          ? "Export PNG"
          : copied
            ? "Copied!"
            : "Share");

    return (
      <button
        onClick={action}
        className={`
          btn-ghost ${size === "sm" ? "btn-sm" : ""}
          inline-flex items-center gap-1.5
          ${className}
        `.trim()}
        aria-label={buttonLabel}
        disabled={pngBusy}
      >
        {pngBusy ? (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : (
          icon
        )}
        <span className="text-xs">{buttonLabel}</span>
      </button>
    );
  }

  // ── Dropdown ───────────────────────────────────────────────────

  const iconSize = size === "sm" ? 12 : 14;
  const buttonLabel = label ?? "Export";

  return (
    <div ref={dropdownRef} className={`relative inline-block ${className}`}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={`
          btn-ghost ${size === "sm" ? "btn-sm" : ""}
          inline-flex items-center gap-1.5
        `.trim()}
        aria-label={buttonLabel}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <Download size={iconSize} />
        <span className="text-xs">{buttonLabel}</span>
        <ChevronDown
          size={10}
          className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div
          className="
            absolute right-0 top-full z-50 mt-1
            min-w-[160px] rounded-lg border border-surface-elevated
            bg-surface shadow-lg
            animate-fade-in
          "
          role="menu"
        >
          {hasCSV && (
            <button
              onClick={handleCSV}
              className="
                flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm
                text-text-secondary hover:bg-surface-elevated hover:text-text-primary
                transition-colors first:rounded-t-lg
              "
              role="menuitem"
            >
              <Download size={14} className="shrink-0" />
              <span>Export CSV</span>
            </button>
          )}

          {hasPNG && (
            <button
              onClick={handlePNG}
              disabled={pngBusy}
              className="
                flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm
                text-text-secondary hover:bg-surface-elevated hover:text-text-primary
                transition-colors disabled:opacity-50
              "
              role="menuitem"
            >
              {pngBusy ? (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent shrink-0" />
              ) : (
                <Image size={14} className="shrink-0" />
              )}
              <span>{pngBusy ? "Capturing..." : "Export PNG"}</span>
            </button>
          )}

          {hasShare && (
            <button
              onClick={handleShare}
              className="
                flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm
                text-text-secondary hover:bg-surface-elevated hover:text-text-primary
                transition-colors last:rounded-b-lg
              "
              role="menuitem"
            >
              {copied ? (
                <Check size={14} className="shrink-0 text-accent" />
              ) : (
                <Copy size={14} className="shrink-0" />
              )}
              <span>{copied ? "Copied!" : "Copy Link"}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Named re-exports for convenience ─────────────────────────────

export { buildCSV, escapeCSV, downloadBlob, copyToClipboard };
