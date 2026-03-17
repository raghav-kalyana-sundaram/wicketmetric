/**
 * PlayerAutocomplete — search-as-you-type input with dropdown suggestions.
 *
 * A composable autocomplete input that queries the backend's trigram search
 * index and displays a dropdown of matching players. Designed for use in:
 *   - Hero search bar on the Home page
 *   - Player search on the Search page
 *   - Player selection inputs on Compare, Team Builder, and Matchup pages
 *
 * Features:
 *   - Debounced search (150ms default) — doesn't fire on every keystroke
 *   - Fuzzy matching via the backend trigram index
 *   - Keyboard navigation (↑/↓/Enter/Escape)
 *   - Role and country filtering via optional props
 *   - Loading spinner during fetch
 *   - Accessible: ARIA combobox pattern with live region announcements
 *   - Controlled and uncontrolled modes
 *   - Customisable rendering via renderItem prop
 *
 * Usage:
 *   // Basic
 *   <PlayerAutocomplete onSelect={(player) => navigate(`/player/${player.id}`)} />
 *
 *   // With filters
 *   <PlayerAutocomplete
 *     role="bat"
 *     country="India"
 *     onSelect={handleSelect}
 *     placeholder="Search batters..."
 *   />
 *
 *   // Controlled value
 *   <PlayerAutocomplete
 *     value={selectedPlayer}
 *     onSelect={setSelectedPlayer}
 *     onClear={() => setSelectedPlayer(null)}
 *   />
 */

import {
  useState,
  useRef,
  useCallback,
  useEffect,
  useMemo,
  type KeyboardEvent,
  type ChangeEvent,
  type FocusEvent,
} from "react";
import { Search, X, Loader2 } from "lucide-react";
import type { PlayerSummary } from "@/api/types";
import { useAutocomplete } from "@/api/queries";
import { useDebounce } from "@/hooks/useDebounce";

import GradeBadge from "@/components/GradeBadge";
import {
  fmtScore,
  countryFlag,
  fmtRole,
  fmtInt,
  fmtSR,
  fmtEcon,
} from "@/lib/format";
import { scoreToColour } from "@/lib/colours";

// ── Props ────────────────────────────────────────────────────────

interface PlayerAutocompleteProps {
  /** Callback when a player is selected from the dropdown. */
  onSelect: (player: PlayerSummary) => void;
  /** Callback when the input is cleared. */
  onClear?: () => void;
  /** Callback when the raw query text changes (for URL sync, etc.). */
  onQueryChange?: (query: string) => void;
  /**
   * If provided, the component is "controlled" — it shows this player
   * as the selected value and the input becomes a display-only field
   * until the user clears it.
   */
  value?: PlayerSummary | null;
  /** Filter results by role: "bat", "bowl", or undefined for all. */
  role?: string | null;
  /** Filter results by country (case-insensitive). */
  country?: string | null;
  /** Maximum number of suggestions to show. Default: 8. */
  limit?: number;
  /** Debounce delay in milliseconds. Default: 150. */
  debounceMs?: number;
  /** Minimum characters before searching. Default: 2. */
  minChars?: number;
  /** Placeholder text. Default: "Search players...". */
  placeholder?: string;
  /**
   * Size variant:
   * - "sm" — compact, for inline use (Compare page player inputs)
   * - "md" — standard size (Search page, general use)
   * - "lg" — hero search bar (Home page)
   */
  size?: "sm" | "md" | "lg";
  /** Whether to auto-focus the input on mount. Default: false. */
  autoFocus?: boolean;
  /** Whether to show the search icon. Default: true. */
  showIcon?: boolean;
  /** Whether to show the clear (×) button. Default: true. */
  showClear?: boolean;
  /** Whether to show role filter toggle buttons. Default: false. */
  showRoleFilter?: boolean;
  /** IDs of players to exclude from results (e.g. already selected). */
  excludeIds?: string[];
  /** Custom render function for dropdown items. */
  renderItem?: (
    player: PlayerSummary,
    index: number,
    highlighted: boolean,
  ) => React.ReactNode;
  /** Additional CSS classes for the outer container. */
  className?: string;
  /** Additional CSS classes for the input element. */
  inputClassName?: string;
  /** HTML id attribute for the input (for label association). */
  id?: string;
  /** HTML name attribute for the input. */
  name?: string;
  /** ARIA label for the input. */
  ariaLabel?: string;
  /** Whether the input is disabled. */
  disabled?: boolean;
  /**
   * Callback fired when the user presses Enter with text in the input
   * but no dropdown item is highlighted. Useful for navigating to a
   * full search page.
   */
  onSubmit?: (query: string) => void;
}

// ── Size variants ────────────────────────────────────────────────

const INPUT_SIZES = {
  sm: "h-9 text-sm pl-8 pr-8",
  md: "h-11 text-base pl-10 pr-10",
  lg: "h-14 text-lg pl-12 pr-12",
} as const;

const ICON_SIZES = {
  sm: 14,
  md: 18,
  lg: 22,
} as const;

const ICON_POSITIONS = {
  sm: "left-2.5 top-1/2 -translate-y-1/2",
  md: "left-3 top-1/2 -translate-y-1/2",
  lg: "left-4 top-1/2 -translate-y-1/2",
} as const;

const CLEAR_POSITIONS = {
  sm: "right-2 top-1/2 -translate-y-1/2",
  md: "right-3 top-1/2 -translate-y-1/2",
  lg: "right-4 top-1/2 -translate-y-1/2",
} as const;

// ── Component ────────────────────────────────────────────────────

export default function PlayerAutocomplete({
  onSelect,
  onClear,
  onQueryChange,
  value,
  role,
  country,
  limit = 8,
  debounceMs = 150,
  minChars = 2,
  placeholder = "Search players...",
  size = "md",
  autoFocus = false,
  showIcon = true,
  showClear = true,
  showRoleFilter = false,
  excludeIds,
  renderItem,
  className = "",
  inputClassName = "",
  id,
  name,
  ariaLabel,
  disabled = false,
  onSubmit,
}: PlayerAutocompleteProps) {
  // ── State ──────────────────────────────────────────────────
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [selectedRoleFilter, setSelectedRoleFilter] = useState<string | null>(
    role ?? null,
  );

  // Refs
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isMouseInsideDropdown = useRef(false);

  // Debounce the query for API calls
  const debouncedQuery = useDebounce(query, debounceMs);

  // The effective role filter (prop takes precedence)
  const effectiveRole = role ?? selectedRoleFilter;

  // ── API query ──────────────────────────────────────────────
  const {
    data: suggestions = [],
    isLoading: _isLoading,
    isFetching,
  } = useAutocomplete(debouncedQuery, {
    role: effectiveRole,
    country: country ?? undefined,
    limit,
    enabled: debouncedQuery.length >= minChars && isOpen,
  });

  // Filter out excluded IDs
  const filteredSuggestions = useMemo(() => {
    if (!excludeIds || excludeIds.length === 0) return suggestions;
    const excludeSet = new Set(excludeIds);
    return suggestions.filter((p) => !excludeSet.has(p.id));
  }, [suggestions, excludeIds]);

  // ── Controlled mode: show selected player ──────────────────
  const isControlled = value !== undefined;
  const hasSelection = isControlled && value != null;

  // ── Handlers ───────────────────────────────────────────────

  const handleInputChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const newQuery = e.target.value;
      setQuery(newQuery);
      setHighlightedIndex(-1);
      onQueryChange?.(newQuery);

      if (newQuery.length >= minChars) {
        setIsOpen(true);
      } else {
        setIsOpen(false);
      }
    },
    [minChars, onQueryChange],
  );

  const handleSelect = useCallback(
    (player: PlayerSummary) => {
      setQuery("");
      setIsOpen(false);
      setHighlightedIndex(-1);
      onSelect(player);

      // Blur the input after selection (but keep focus in keyboard mode)
      // Small delay to allow React to process state updates
      setTimeout(() => {
        inputRef.current?.blur();
      }, 50);
    },
    [onSelect],
  );

  const handleClear = useCallback(() => {
    setQuery("");
    setIsOpen(false);
    setHighlightedIndex(-1);
    onClear?.();
    onQueryChange?.("");
    inputRef.current?.focus();
  }, [onClear, onQueryChange]);

  const handleFocus = useCallback(() => {
    if (hasSelection) return; // Don't open dropdown when showing a selection
    if (query.length >= minChars) {
      setIsOpen(true);
    }
  }, [hasSelection, query, minChars]);

  const handleBlur = useCallback((_e: FocusEvent) => {
    // Delay closing to allow click events on dropdown items to fire
    setTimeout(() => {
      if (!isMouseInsideDropdown.current) {
        setIsOpen(false);
        setHighlightedIndex(-1);
      }
    }, 150);
  }, []);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (!isOpen) {
        // Open dropdown on arrow down if we have a query
        if (e.key === "ArrowDown" && query.length >= minChars) {
          e.preventDefault();
          setIsOpen(true);
          return;
        }
        // Submit on Enter if handler provided
        if (e.key === "Enter" && onSubmit && query.trim()) {
          e.preventDefault();
          onSubmit(query.trim());
          return;
        }
        return;
      }

      const itemCount = filteredSuggestions.length;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setHighlightedIndex((prev) => (prev < itemCount - 1 ? prev + 1 : 0));
          break;

        case "ArrowUp":
          e.preventDefault();
          setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : itemCount - 1));
          break;

        case "Enter":
          e.preventDefault();
          if (highlightedIndex >= 0 && highlightedIndex < itemCount) {
            handleSelect(filteredSuggestions[highlightedIndex]);
          } else if (onSubmit && query.trim()) {
            setIsOpen(false);
            onSubmit(query.trim());
          }
          break;

        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          setHighlightedIndex(-1);
          inputRef.current?.blur();
          break;

        case "Tab":
          setIsOpen(false);
          setHighlightedIndex(-1);
          break;
      }
    },
    [
      isOpen,
      filteredSuggestions,
      highlightedIndex,
      handleSelect,
      onSubmit,
      query,
      minChars,
    ],
  );

  // ── Scroll highlighted item into view ──────────────────────
  useEffect(() => {
    if (highlightedIndex < 0 || !dropdownRef.current) return;

    const dropdown = dropdownRef.current;
    const items = dropdown.querySelectorAll('[role="option"]');
    const item = items[highlightedIndex] as HTMLElement | undefined;

    if (item) {
      item.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [highlightedIndex]);

  // ── Close dropdown on outside click ────────────────────────
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
        setHighlightedIndex(-1);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  // ── Derive display state ───────────────────────────────────
  const showDropdown =
    isOpen &&
    (filteredSuggestions.length > 0 || isFetching || query.length >= minChars);
  const showSpinner = isFetching && query.length >= minChars;
  const showNoResults =
    isOpen &&
    !isFetching &&
    query.length >= minChars &&
    debouncedQuery.length >= minChars &&
    filteredSuggestions.length === 0;
  const showClearButton =
    showClear && (query.length > 0 || hasSelection) && !disabled;

  const inputSizeClass = INPUT_SIZES[size];
  const iconSize = ICON_SIZES[size];
  const iconPos = ICON_POSITIONS[size];
  const clearPos = CLEAR_POSITIONS[size];

  // Compute listbox ID for ARIA
  const listboxId = id ? `${id}-listbox` : "player-autocomplete-listbox";

  // ── Render: Selected player (controlled mode) ──────────────
  if (hasSelection && value) {
    return (
      <div className={`relative ${className}`} ref={containerRef}>
        <div
          className={`filter-input ${inputSizeClass} flex items-center gap-2 cursor-default ${inputClassName}`}
        >
          {showIcon && (
            <Search size={iconSize} className="text-text-muted shrink-0" />
          )}
          <span className="flex items-center gap-1.5 flex-1 min-w-0 truncate">
            <span className="font-medium text-text-primary truncate">
              {value.name}
            </span>
            {value.country && (
              <span className="text-xs shrink-0" title={value.country}>
                {countryFlag(value.country)}
              </span>
            )}
          </span>
          <GradeBadge grade={value.grade_overall} size="xs" />
          {showClear && !disabled && (
            <button
              onClick={handleClear}
              className="text-text-muted hover:text-text-primary transition-colors shrink-0 p-0.5 rounded-sm hover:bg-surface-elevated"
              aria-label="Clear selection"
              title="Clear"
              type="button"
            >
              <X size={iconSize - 2} />
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Render: Search input with dropdown ─────────────────────
  return (
    <div className={`relative ${className}`} ref={containerRef}>
      {/* Role filter toggle (optional) */}
      {showRoleFilter && (
        <div className="flex items-center gap-1 mb-2">
          {(["bat", "bowl"] as const).map((r) => (
            <button
              key={r}
              onClick={() => {
                setSelectedRoleFilter(selectedRoleFilter === r ? null : r);
                setHighlightedIndex(-1);
              }}
              className={`btn-sm text-xs ${
                selectedRoleFilter === r ? "btn-primary" : "btn-ghost"
              }`}
              type="button"
            >
              {r === "bat" ? "Bat" : "Bowl"}
            </button>
          ))}
          {selectedRoleFilter && (
            <button
              onClick={() => {
                setSelectedRoleFilter(null);
                setHighlightedIndex(-1);
              }}
              className="btn-ghost btn-sm text-xs text-text-muted"
              type="button"
            >
              All
            </button>
          )}
        </div>
      )}

      {/* Input container */}
      <div className="relative">
        {/* Search icon */}
        {showIcon && (
          <div
            className={`absolute ${iconPos} pointer-events-none text-text-muted z-10`}
          >
            {showSpinner ? (
              <Loader2 size={iconSize} className="animate-spin" />
            ) : (
              <Search size={iconSize} />
            )}
          </div>
        )}

        {/* Input field */}
        <input
          ref={inputRef}
          type="text"
          id={id}
          name={name}
          value={query}
          onChange={handleInputChange}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          autoComplete="off"
          spellCheck={false}
          className={`filter-input w-full ${inputSizeClass} ${
            !showIcon ? "pl-3" : ""
          } ${inputClassName}`}
          role="combobox"
          aria-expanded={showDropdown}
          aria-haspopup="listbox"
          aria-controls={showDropdown ? listboxId : undefined}
          aria-activedescendant={
            highlightedIndex >= 0
              ? `${listboxId}-option-${highlightedIndex}`
              : undefined
          }
          aria-autocomplete="list"
          aria-label={ariaLabel ?? placeholder}
        />

        {/* Clear button */}
        {showClearButton && (
          <button
            className={`absolute ${clearPos} text-text-muted hover:text-text-primary transition-colors p-0.5 rounded-sm hover:bg-surface-elevated z-10`}
            onClick={handleClear}
            aria-label="Clear search"
            title="Clear"
            type="button"
            tabIndex={-1}
          >
            <X size={iconSize - 2} />
          </button>
        )}
      </div>

      {/* Dropdown */}
      {showDropdown && (
        <div
          ref={dropdownRef}
          className="autocomplete-dropdown"
          id={listboxId}
          role="listbox"
          aria-label="Player suggestions"
          onMouseEnter={() => {
            isMouseInsideDropdown.current = true;
          }}
          onMouseLeave={() => {
            isMouseInsideDropdown.current = false;
          }}
        >
          {/* Loading state */}
          {showSpinner && filteredSuggestions.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-text-muted">
              <Loader2 size={20} className="animate-spin mx-auto mb-2" />
              Searching…
            </div>
          )}

          {/* No results */}
          {showNoResults && (
            <div className="px-4 py-6 text-center text-sm text-text-muted">
              <p className="mb-1">No players found for "{debouncedQuery}"</p>
              <p className="text-xs">
                Try a different spelling or check the filters.
              </p>
            </div>
          )}

          {/* Results list */}
          {filteredSuggestions.map((player, index) => {
            const isHighlighted = index === highlightedIndex;

            // Custom render
            if (renderItem) {
              return (
                <div
                  key={player.id}
                  id={`${listboxId}-option-${index}`}
                  role="option"
                  aria-selected={isHighlighted}
                  onClick={() => handleSelect(player)}
                  onMouseEnter={() => setHighlightedIndex(index)}
                  className={`cursor-pointer ${
                    isHighlighted ? "bg-surface-elevated" : ""
                  }`}
                >
                  {renderItem(player, index, isHighlighted)}
                </div>
              );
            }

            // Default item rendering
            return (
              <DefaultAutocompleteItem
                key={player.id}
                player={player}
                index={index}
                isHighlighted={isHighlighted}
                listboxId={listboxId}
                onSelect={handleSelect}
                onHover={setHighlightedIndex}
                size={size}
              />
            );
          })}

          {/* Footer hint */}
          {filteredSuggestions.length > 0 && (
            <div className="px-3 py-2 border-t border-surface-elevated/50 text-xs text-text-muted flex items-center justify-between">
              <span>
                {filteredSuggestions.length} result
                {filteredSuggestions.length !== 1 ? "s" : ""}
              </span>
              <span className="hidden sm:inline">
                ↑↓ navigate · Enter select · Esc close
              </span>
            </div>
          )}
        </div>
      )}

      {/* Screen reader live region */}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic>
        {showNoResults && `No results found for ${debouncedQuery}`}
        {filteredSuggestions.length > 0 &&
          !showSpinner &&
          `${filteredSuggestions.length} suggestions available`}
      </div>
    </div>
  );
}

// ── Default autocomplete item ────────────────────────────────────

interface DefaultAutocompleteItemProps {
  player: PlayerSummary;
  index: number;
  isHighlighted: boolean;
  listboxId: string;
  onSelect: (player: PlayerSummary) => void;
  onHover: (index: number) => void;
  size: "sm" | "md" | "lg";
}

function DefaultAutocompleteItem({
  player,
  index,
  isHighlighted,
  listboxId,
  onSelect,
  onHover,
  size,
}: DefaultAutocompleteItemProps) {
  const flag = countryFlag(player.country);
  const isBowler = player.role === "bowl";

  return (
    <div
      id={`${listboxId}-option-${index}`}
      role="option"
      aria-selected={isHighlighted}
      className={`autocomplete-item ${isHighlighted ? "highlighted" : ""}`}
      onClick={() => onSelect(player)}
      onMouseEnter={() => onHover(index)}
    >
      <div className="flex items-center gap-3">
        {/* Left: name + meta */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className={`font-medium text-text-primary truncate ${
                size === "sm" ? "text-sm" : "text-base"
              }`}
            >
              {player.name}
            </span>
            {flag && (
              <span className="text-xs shrink-0" title={player.country}>
                {flag}
              </span>
            )}
            {player.is_provisional && (
              <span className="text-[10px] text-warning shrink-0">!</span>
            )}
          </div>

          <div className="flex items-center gap-2 text-xs text-text-muted mt-0.5">
            {player.archetype ? (
              <span className="truncate">{player.archetype}</span>
            ) : (
              <span>{fmtRole(player.role)}</span>
            )}
            <span className="text-text-muted/40">·</span>
            <span className="tabular-nums">
              {fmtInt(player.innings_count, "0")}
              {isBowler ? " mat" : " inn"}
            </span>
            <span className="text-text-muted/40">·</span>
            <span className="tabular-nums">
              {isBowler
                ? `${fmtInt(player.total_runs, "0")} wkts`
                : `${fmtInt(player.total_runs, "0")} runs`}
            </span>
            {player.career_sr != null && (
              <>
                <span className="text-text-muted/40">·</span>
                <span className="tabular-nums">
                  {isBowler
                    ? `Econ ${fmtEcon(player.career_sr)}`
                    : `SR ${fmtSR(player.career_sr)}`}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Right: mini scores + grade */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Mini score indicators */}
          <div className="hidden sm:flex items-center gap-1">
            {[player.score_1, player.score_2, player.score_3].map(
              (score, i) => (
                <div
                  key={i}
                  className="w-1.5 rounded-full"
                  style={{
                    height: `${Math.max(4, ((score ?? 0) / 100) * 20)}px`,
                    backgroundColor: scoreToColour(score),
                    minHeight: "4px",
                  }}
                  title={`${
                    i === 0
                      ? player.score_1_label
                      : i === 1
                        ? player.score_2_label
                        : player.score_3_label
                  }: ${fmtScore(score)}`}
                />
              ),
            )}
          </div>

          {/* Overall score */}
          <span
            className="text-xs font-score tabular-nums w-7 text-right"
            style={{ color: scoreToColour(player.overall_score) }}
          >
            {player.overall_score != null
              ? Math.round(player.overall_score)
              : "—"}
          </span>

          {/* Grade badge */}
          <GradeBadge grade={player.grade_overall} size="xs" />
        </div>
      </div>
    </div>
  );
}

// ── Skeleton ─────────────────────────────────────────────────────

interface PlayerAutocompleteSkeletonProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function PlayerAutocompleteSkeleton({
  size = "md",
  className = "",
}: PlayerAutocompleteSkeletonProps) {
  const heightClass = size === "sm" ? "h-9" : size === "lg" ? "h-14" : "h-11";

  return (
    <div className={`${className}`}>
      <div className={`skeleton ${heightClass} w-full rounded-lg`} />
    </div>
  );
}
