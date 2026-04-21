/**
 * Rich mini-card tooltip for sortable leaderboard column headers (portal + fixed position).
 * Escapes overflow-x clipping; dotted underline on the label; hover on desktop, tap toggle on touch.
 */

import {
  useState,
  useRef,
  useEffect,
  useLayoutEffect,
  useCallback,
  useId,
} from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
  METRIC_DEFINITIONS,
  WAR_FIRST_USE_STORAGE_KEY,
  WAR_METRIC_KEYS,
} from "@/components/MetricTooltip";

const TOOLTIP_MAX_W = 300;
const VIEWPORT_PAD = 8;

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const fn = () => setReduced(mq.matches);
    fn();
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  return reduced;
}

function useNoHover(): boolean {
  const [noHover, setNoHover] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(hover: none)");
    const fn = () => setNoHover(mq.matches);
    fn();
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  return noHover;
}

export interface MetricColumnHeaderTooltipProps {
  /** Key into METRIC_DEFINITIONS */
  lookupKey: string;
  /** Shown in header with dotted underline */
  label: string;
  /** Set when the column uses an API metric key that can be WAR (first-use footer). */
  warMetricKey?: string;
  /** Extra classes on the trigger span */
  triggerClassName?: string;
}

export default function MetricColumnHeaderTooltip({
  lookupKey,
  label,
  warMetricKey,
  triggerClassName = "",
}: MetricColumnHeaderTooltipProps) {
  const def = METRIC_DEFINITIONS[lookupKey];
  const tipId = useId();
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const delayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, place: "below" as "below" | "above" });
  const [warSeen, setWarSeen] = useState(
    () => typeof window !== "undefined" && !!localStorage.getItem(WAR_FIRST_USE_STORAGE_KEY),
  );
  const reducedMotion = usePrefersReducedMotion();
  const noHover = useNoHover();

  const isWarMetric =
    warMetricKey != null && warMetricKey !== "" && WAR_METRIC_KEYS.has(warMetricKey);
  const showWarFooter = open && isWarMetric && !warSeen;

  const subtitle = def?.headerSubtitle ?? def?.name ?? "";
  const bodyText =
    def?.goodGuide ??
    def?.interpretation ??
    def?.description ??
    (def ? "" : "See the glossary or player profile for details on this stat.");
  const calcLine = def?.calculationLine;
  const scaleLine = def?.range && !calcLine ? def.range : undefined;

  const clearDelay = useCallback(() => {
    if (delayRef.current) {
      clearTimeout(delayRef.current);
      delayRef.current = null;
    }
  }, []);

  const hide = useCallback(() => {
    clearDelay();
    setOpen(false);
  }, [clearDelay]);

  const showAfterDelay = useCallback(() => {
    if (!bodyText.trim()) return;
    clearDelay();
    delayRef.current = setTimeout(() => setOpen(true), 280);
  }, [clearDelay, bodyText]);

  const updatePosition = useCallback(() => {
    const trig = triggerRef.current;
    const tip = tooltipRef.current;
    if (!trig) return;
    const tr = trig.getBoundingClientRect();
    const tipH = tip?.offsetHeight ?? 120;
    const tipW = Math.min(TOOLTIP_MAX_W, tip?.offsetWidth ?? TOOLTIP_MAX_W);
    const margin = 8;

    let place: "below" | "above" = "below";
    let top = tr.bottom + margin;
    if (tr.bottom + tipH + VIEWPORT_PAD > window.innerHeight && tr.top > tipH + VIEWPORT_PAD) {
      place = "above";
      top = tr.top - tipH - margin;
    }
    top = Math.max(VIEWPORT_PAD, Math.min(top, window.innerHeight - tipH - VIEWPORT_PAD));

    let left = tr.left + tr.width / 2;
    const half = tipW / 2;
    left = Math.max(half + VIEWPORT_PAD, Math.min(left, window.innerWidth - half - VIEWPORT_PAD));

    setPos({ top, left, place });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const tip = tooltipRef.current;
    const ro = tip ? new ResizeObserver(() => updatePosition()) : null;
    if (tip) ro?.observe(tip);
    const onScroll = () => updatePosition();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      ro?.disconnect();
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, updatePosition, bodyText, calcLine, scaleLine, showWarFooter]);

  useEffect(() => {
    if (!open || !noHover) return;
    const onDoc = (e: MouseEvent | TouchEvent) => {
      const t = triggerRef.current;
      const el = tooltipRef.current;
      const target = e.target as Node;
      if (t?.contains(target) || el?.contains(target)) return;
      hide();
    };
    document.addEventListener("mousedown", onDoc, true);
    document.addEventListener("touchstart", onDoc, true);
    return () => {
      document.removeEventListener("mousedown", onDoc, true);
      document.removeEventListener("touchstart", onDoc, true);
    };
  }, [open, noHover, hide]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") hide();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, hide]);

  useEffect(() => () => clearDelay(), [clearDelay]);

  const handleWarAck = useCallback(() => {
    localStorage.setItem(WAR_FIRST_USE_STORAGE_KEY, "1");
    setWarSeen(true);
    hide();
  }, [hide]);

  const handleTriggerClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!bodyText.trim()) return;
    if (noHover) {
      setOpen((v) => !v);
    }
  };

  const handleTriggerMouseEnter = () => {
    if (!noHover && bodyText.trim()) showAfterDelay();
  };

  const handleTriggerMouseLeave = () => {
    if (!noHover) hide();
  };

  const handleTriggerFocus = () => {
    if (bodyText.trim()) showAfterDelay();
  };

  const handleTriggerBlur = (e: React.FocusEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) hide();
  };

  if (!bodyText.trim()) {
    return <span>{label}</span>;
  }

  const titleLine = subtitle ? `${label}: ${subtitle}` : label;

  const portal =
    open &&
    createPortal(
      <div
        ref={tooltipRef}
        id={tipId}
        role="tooltip"
        className={[
          "fixed z-[120] rounded-lg border border-surface-elevated/90 bg-surface-elevated px-3 py-2.5 text-left shadow-xl dark:shadow-[0_16px_48px_rgba(0,0,0,0.55)]",
          reducedMotion ? "" : "animate-fade-in",
          showWarFooter ? "pointer-events-auto" : "pointer-events-none",
        ]
          .filter(Boolean)
          .join(" ")}
        style={{
          top: pos.top,
          left: pos.left,
          maxWidth: TOOLTIP_MAX_W,
          width: "max-content",
        }}
      >
        <div className="text-xs leading-snug space-y-2">
          <div className="font-bold text-text-primary">{titleLine}</div>
          <p className="text-text-secondary leading-relaxed m-0">{bodyText}</p>
          {(calcLine || scaleLine) && (
            <p className="text-[11px] leading-relaxed text-text-muted m-0 pt-1 border-t border-surface-elevated/80">
              {calcLine ? (
                <>
                  <span className="font-medium text-text-muted/90">Calculation: </span>
                  {calcLine}
                </>
              ) : (
                <>
                  <span className="font-medium text-text-muted/90">Typical scale: </span>
                  {scaleLine}
                </>
              )}
            </p>
          )}
          {showWarFooter && (
            <div className="pt-2 border-t border-surface-elevated/80 flex items-center gap-2 flex-wrap pointer-events-auto">
              <span className="text-text-muted text-[11px]">First time here?</span>
              <Link
                to="/glossary#advanced"
                className="text-primary hover:text-primary-hover text-[11px] font-medium"
                onClick={handleWarAck}
              >
                Glossary
              </Link>
              <button
                type="button"
                onClick={handleWarAck}
                className="text-[11px] font-medium px-2 py-0.5 rounded bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
              >
                Got it
              </button>
            </div>
          )}
        </div>
        <span
          className={[
            "absolute w-2 h-2 rotate-45 bg-surface-elevated border-surface-elevated/90",
            pos.place === "below"
              ? "bottom-full left-1/2 -translate-x-1/2 translate-y-1/2 border-l border-t"
              : "top-full left-1/2 -translate-x-1/2 -translate-y-1/2 border-r border-b",
          ].join(" ")}
          aria-hidden
        />
      </div>,
      document.body,
    );

  return (
    <>
      <span
        ref={triggerRef}
        tabIndex={0}
        className={[
          "underline decoration-dotted decoration-text-muted/70 underline-offset-[5px] hover:decoration-text-muted cursor-help text-inherit rounded-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 focus-visible:ring-offset-surface",
          triggerClassName,
        ]
          .filter(Boolean)
          .join(" ")}
        onClick={handleTriggerClick}
        onMouseEnter={handleTriggerMouseEnter}
        onMouseLeave={handleTriggerMouseLeave}
        onFocus={handleTriggerFocus}
        onBlur={handleTriggerBlur}
        aria-describedby={open ? tipId : undefined}
        aria-expanded={noHover ? open : undefined}
      >
        {label}
      </span>
      {portal}
    </>
  );
}

export function rankingsHeaderDefinitionKey(
  metricKey: string,
  isBowling: boolean,
): string | undefined {
  if (isBowling && metricKey === "score_control") return "control_bowl";
  return undefined;
}
