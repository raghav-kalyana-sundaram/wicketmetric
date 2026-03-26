import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { ChevronDown } from "lucide-react";
import { useOnClickOutside } from "@/hooks/useOnClickOutside";

export type InningsPhaseOption = "any" | "early" | "death";

const PHASE_OPTIONS: { value: InningsPhaseOption; label: string }[] = [
  { value: "any", label: "Any entry" },
  { value: "early", label: "Entered overs 1–4" },
  { value: "death", label: "Death overs (16–20)" },
];

export interface AdvancedContextFiltersProps {
  chaseHighRpo: boolean;
  playoffsOnly: boolean;
  inningsPhase: InningsPhaseOption;
  onChaseHighRpoChange: (next: boolean) => void;
  onPlayoffsOnlyChange: (next: boolean) => void;
  onInningsPhaseChange: (next: InningsPhaseOption) => void;
  /** Removes only situational ctx_* URL params (not country, archetype, etc.). */
  onClearContext: () => void;
}

function chipBase(active: boolean) {
  return [
    "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-2 text-sm font-medium transition-all duration-200 ease-out-quart",
    active
      ? "border-slate-400 bg-slate-200/90 text-slate-900 shadow-sm dark:border-white/[0.14] dark:bg-surface dark:text-text-primary dark:shadow-[0_8px_24px_-16px_rgba(0,0,0,0.45)]"
      : "border-surface-elevated bg-surface-elevated/60 text-text-secondary hover:border-surface-elevated hover:bg-surface-elevated/80 hover:text-text-primary",
  ].join(" ");
}

export default function AdvancedContextFilters({
  chaseHighRpo,
  playoffsOnly,
  inningsPhase,
  onChaseHighRpoChange,
  onPlayoffsOnlyChange,
  onInningsPhaseChange,
  onClearContext,
}: AdvancedContextFiltersProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxRef = useRef<HTMLDivElement>(null);
  const [phaseOpen, setPhaseOpen] = useState(false);
  const [activeOptionIndex, setActiveOptionIndex] = useState(0);
  const reactId = useId();
  const listboxId = `ctx-phase-listbox-${reactId}`;
  const triggerId = `ctx-phase-trigger-${reactId}`;
  const optId = (i: number) => `ctx-phase-opt-${reactId}-${i}`;

  const selectedPhaseLabel =
    PHASE_OPTIONS.find((o) => o.value === inningsPhase)?.label ?? "Any entry";

  useOnClickOutside(
    rootRef,
    useCallback(() => {
      setPhaseOpen(false);
    }, []),
    phaseOpen,
  );

  useEffect(() => {
    if (!phaseOpen) return;
    const idx = PHASE_OPTIONS.findIndex((o) => o.value === inningsPhase);
    setActiveOptionIndex(idx >= 0 ? idx : 0);
    const t = requestAnimationFrame(() => listboxRef.current?.focus());
    return () => cancelAnimationFrame(t);
  }, [phaseOpen, inningsPhase]);

  const closePhase = useCallback(() => {
    setPhaseOpen(false);
    triggerRef.current?.focus();
  }, []);

  const selectPhase = useCallback(
    (value: InningsPhaseOption) => {
      onInningsPhaseChange(value);
      closePhase();
    },
    [onInningsPhaseChange, closePhase],
  );

  const onListboxKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closePhase();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveOptionIndex((i) => (i + 1) % PHASE_OPTIONS.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveOptionIndex(
          (i) => (i - 1 + PHASE_OPTIONS.length) % PHASE_OPTIONS.length,
        );
        return;
      }
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        const opt = PHASE_OPTIONS[activeOptionIndex];
        if (opt) selectPhase(opt.value);
      }
    },
    [activeOptionIndex, closePhase, selectPhase],
  );

  const phaseChipActive = inningsPhase !== "any" || phaseOpen;

  const hasAnyContext =
    chaseHighRpo || playoffsOnly || inningsPhase !== "any";

  return (
    <div
      ref={rootRef}
      className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-elevated/60 px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-2 min-w-0">
        <span className="text-[11px] uppercase tracking-wider text-text-muted shrink-0 mr-1 hidden sm:inline">
          Context
        </span>

        <button
          type="button"
          aria-pressed={chaseHighRpo}
          onClick={() => onChaseHighRpoChange(!chaseHighRpo)}
          className={chipBase(chaseHighRpo)}
        >
          Chasing 10+ RPO
        </button>

        <button
          type="button"
          aria-pressed={playoffsOnly}
          onClick={() => onPlayoffsOnlyChange(!playoffsOnly)}
          className={chipBase(playoffsOnly)}
        >
          Playoffs / Knockouts only
        </button>

        <div className="relative">
          <button
            ref={triggerRef}
            type="button"
            id={triggerId}
            aria-haspopup="listbox"
            aria-expanded={phaseOpen}
            aria-controls={listboxId}
            onClick={() => setPhaseOpen((o) => !o)}
            className={chipBase(phaseChipActive)}
          >
            <span className="max-w-[200px] truncate sm:max-w-none">
              Innings phase
              {inningsPhase !== "any" ? (
                <span className="text-text-muted font-normal">
                  {" "}
                  · {selectedPhaseLabel}
                </span>
              ) : null}
            </span>
            <ChevronDown
              size={16}
              className={`shrink-0 opacity-70 transition-transform ${phaseOpen ? "rotate-180" : ""}`}
              aria-hidden
            />
          </button>

          {phaseOpen && (
            <div
              ref={listboxRef}
              id={listboxId}
              role="listbox"
              tabIndex={0}
              aria-labelledby={triggerId}
              aria-activedescendant={optId(activeOptionIndex)}
              onKeyDown={onListboxKeyDown}
              className="absolute left-0 top-[calc(100%+6px)] z-40 min-w-[240px] rounded-xl border border-surface-elevated bg-surface py-1 shadow-card outline-none ring-1 ring-black/10 dark:border-white/15 dark:bg-surface dark:shadow-xl dark:backdrop-blur-none dark:ring-white/5"
            >
              {PHASE_OPTIONS.map((opt, i) => {
                const selected = opt.value === inningsPhase;
                const highlighted = i === activeOptionIndex;
                return (
                  <div
                    key={opt.value}
                    id={optId(i)}
                    role="option"
                    aria-selected={selected}
                    className={`cursor-pointer px-3 py-2.5 text-sm transition-colors ${
                      highlighted
                        ? "bg-surface-elevated/80 text-text-primary"
                        : "text-text-secondary"
                    } ${selected ? "font-medium text-text-primary dark:text-zinc-100" : ""}`}
                    onMouseEnter={() => setActiveOptionIndex(i)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => selectPhase(opt.value)}
                  >
                    {opt.label}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={onClearContext}
        disabled={!hasAnyContext}
        className="shrink-0 text-sm text-text-muted transition-colors hover:text-primary disabled:pointer-events-none disabled:opacity-40"
      >
        Clear All Filters
      </button>
    </div>
  );
}
