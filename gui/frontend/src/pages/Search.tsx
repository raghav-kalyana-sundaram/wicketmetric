/**
 * Search — full search results page with filters.
 *
 * Route: /search?q=...&country=...&role=...&archetype=...&provisional=...&min_innings=...
 *
 * Features (from gui.md § 6.2):
 *   - Full-text fuzzy search via the backend trigram index
 *   - Filters: country, role, archetype, provisional toggle, min innings
 *   - URL-driven state: all filters reflected in query params for shareability
 *   - Results rendered as full PlayerCard components with score bars
 *   - Result count header
 *   - Loading/error/empty states
 *
 * Data fetching:
 *   - useSearchPlayers() with all filter params
 *   - useCountries() and useArchetypes() for filter dropdowns
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import {
  Search as SearchIcon,
  SlidersHorizontal,
  X,
  Filter,
} from "lucide-react";
import PlayerCard, { PlayerCardSkeleton } from "@/components/PlayerCard";
import { PageError } from "@/components/Layout";
import { useSearchPlayers, useCountries, useArchetypes } from "@/api/queries";
import { parseBoolParam, parseIntParam } from "@/lib/format";
import type { PlayerSummary } from "@/api/types";

// ── Default values ───────────────────────────────────────────────

const DEFAULT_LIMIT = 50;
const DEFAULT_MIN_INNINGS = 0;

// ── Component ────────────────────────────────────────────────────

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // ── Parse URL state ────────────────────────────────────────
  const urlQuery = searchParams.get("q") ?? "";
  const urlRole = (searchParams.get("role") ?? undefined) as
    | "bat"
    | "bowl"
    | undefined;
  const urlCountry = searchParams.get("country") ?? undefined;
  const urlArchetype = searchParams.get("archetype") ?? undefined;
  const urlProvisional = parseBoolParam(searchParams.get("provisional"));
  const urlMinInnings = parseIntParam(
    searchParams.get("min_innings"),
    DEFAULT_MIN_INNINGS,
  );

  // ── Local input state (for the search box) ─────────────────
  const [inputQuery, setInputQuery] = useState(urlQuery);
  const [showFilters, setShowFilters] = useState(
    Boolean(
      urlRole ||
      urlCountry ||
      urlArchetype ||
      urlProvisional !== undefined ||
      urlMinInnings > 0,
    ),
  );

  // Sync local input when URL changes (e.g. back/forward navigation)
  useEffect(() => {
    setInputQuery(urlQuery);
  }, [urlQuery]);

  // ── Reference data for filter dropdowns ────────────────────
  const { data: countries = [] } = useCountries();
  const { data: archetypes } = useArchetypes();

  // Derive the archetype list based on selected role
  const archetypeOptions = useMemo(() => {
    if (!archetypes) return [];
    if (urlRole === "bat") return archetypes.bat ?? [];
    if (urlRole === "bowl") return archetypes.bowl ?? [];
    // Both roles
    const all = new Set<string>([
      ...(archetypes.bat ?? []),
      ...(archetypes.bowl ?? []),
    ]);
    return Array.from(all).sort();
  }, [archetypes, urlRole]);

  // ── Fetch search results ───────────────────────────────────
  const searchEnabled =
    urlQuery.length >= 1 || Boolean(urlRole || urlCountry || urlArchetype);

  const {
    data: searchResult,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useSearchPlayers(
    {
      q: urlQuery,
      role: urlRole,
      country: urlCountry,
      archetype: urlArchetype,
      provisional: urlProvisional,
      min_innings: urlMinInnings > 0 ? urlMinInnings : undefined,
      limit: DEFAULT_LIMIT,
    },
    { enabled: searchEnabled },
  );

  const results = searchResult?.results ?? [];
  const totalResults = searchResult?.total ?? 0;

  // ── URL update helper ──────────────────────────────────────
  const updateParams = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(updates)) {
          if (value == null || value === "" || value === "undefined") {
            next.delete(key);
          } else {
            next.set(key, value);
          }
        }
        return next;
      });
    },
    [setSearchParams],
  );

  // ── Handlers ───────────────────────────────────────────────

  const handleSearchSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      updateParams({ q: inputQuery.trim() || null });
    },
    [inputQuery, updateParams],
  );

  const handleQueryChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setInputQuery(e.target.value);
    },
    [],
  );

  const handleQueryKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        updateParams({ q: inputQuery.trim() || null });
      }
    },
    [inputQuery, updateParams],
  );

  const handleClearQuery = useCallback(() => {
    setInputQuery("");
    updateParams({ q: null });
  }, [updateParams]);

  const handleRoleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const val = e.target.value || undefined;
      // Clear archetype if role changes (archetypes are role-specific)
      updateParams({ role: val ?? null, archetype: null });
    },
    [updateParams],
  );

  const handleCountryChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      updateParams({ country: e.target.value || null });
    },
    [updateParams],
  );

  const handleArchetypeChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      updateParams({ archetype: e.target.value || null });
    },
    [updateParams],
  );

  const handleProvisionalChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const val = e.target.value;
      if (val === "hide") {
        updateParams({ provisional: "false" });
      } else if (val === "only") {
        updateParams({ provisional: "true" });
      } else {
        updateParams({ provisional: null });
      }
    },
    [updateParams],
  );

  const handleMinInningsChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseInt(e.target.value, 10);
      updateParams({
        min_innings: isNaN(val) || val <= 0 ? null : String(val),
      });
    },
    [updateParams],
  );

  const handleClearFilters = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams();
      // Keep only the search query
      const q = prev.get("q");
      if (q) next.set("q", q);
      return next;
    });
  }, [setSearchParams]);

  // Compare: track selected players
  const [compareIds, setCompareIds] = useState<Set<string>>(new Set());

  const handleCompareToggle = useCallback((player: PlayerSummary) => {
    setCompareIds((prev) => {
      const next = new Set(prev);
      if (next.has(player.id)) {
        next.delete(player.id);
      } else if (next.size < 4) {
        next.add(player.id);
      }
      return next;
    });
  }, []);

  const handleCompareNavigate = useCallback(() => {
    if (compareIds.size >= 2) {
      navigate(`/compare?ids=${Array.from(compareIds).join(",")}`);
    }
  }, [navigate, compareIds]);

  // Determine provisional filter display value
  const provisionalValue = useMemo(() => {
    if (urlProvisional === true) return "only";
    if (urlProvisional === false) return "hide";
    return "all";
  }, [urlProvisional]);

  // Active filter count (for the filter toggle badge)
  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (urlRole) count++;
    if (urlCountry) count++;
    if (urlArchetype) count++;
    if (urlProvisional !== undefined) count++;
    if (urlMinInnings > 0) count++;
    return count;
  }, [urlRole, urlCountry, urlArchetype, urlProvisional, urlMinInnings]);

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="app-page page-stack">
      {/* ── Search Header ────────────────────────────────────── */}
      <div className="page-header">
        <h1 className="page-title">Player Search</h1>
        <p className="page-subtitle">
          Search players by name with advanced filters for role, country, archetype, and sample size.
        </p>

        {/* Search input row */}
        <form onSubmit={handleSearchSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none">
              <SearchIcon size={18} />
            </div>
            <input
              type="text"
              value={inputQuery}
              onChange={handleQueryChange}
              onKeyDown={handleQueryKeyDown}
              placeholder="Search by player name..."
              className="filter-input w-full h-11 pl-10 pr-10 text-base"
              autoFocus
              autoComplete="off"
              spellCheck={false}
              aria-label="Search players by name"
            />
            {inputQuery && (
              <button
                type="button"
                onClick={handleClearQuery}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors p-0.5"
                aria-label="Clear search"
              >
                <X size={16} />
              </button>
            )}
          </div>

          <button type="submit" className="btn-primary shrink-0">
            Search
          </button>

          {/* Filter toggle */}
          <button
            type="button"
            onClick={() => setShowFilters(!showFilters)}
            className={`btn-secondary shrink-0 relative ${
              showFilters ? "ring-2 ring-primary" : ""
            }`}
            aria-expanded={showFilters}
            aria-controls="search-filters"
            title="Toggle filters"
          >
            <SlidersHorizontal size={16} />
            <span className="hidden sm:inline">Filters</span>
            {activeFilterCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 h-4 w-4 rounded-full bg-primary text-white text-[10px] font-bold flex items-center justify-center">
                {activeFilterCount}
              </span>
            )}
          </button>
        </form>

        {/* ── Filter Bar ─────────────────────────────────────── */}
        {showFilters && (
          <div id="search-filters" className="mt-3 p-4 card animate-slide-up">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <Filter size={14} />
                <span>Filters</span>
                {activeFilterCount > 0 && (
                  <span className="text-xs text-text-muted">
                    ({activeFilterCount} active)
                  </span>
                )}
              </div>
              {activeFilterCount > 0 && (
                <button
                  onClick={handleClearFilters}
                  className="text-xs text-primary hover:text-primary-hover transition-colors"
                >
                  Clear all filters
                </button>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
              {/* Role filter */}
              <div>
                <label
                  htmlFor="filter-role"
                  className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                >
                  Role
                </label>
                <select
                  id="filter-role"
                  value={urlRole ?? ""}
                  onChange={handleRoleChange}
                  className="filter-select w-full"
                >
                  <option value="">All Roles</option>
                  <option value="bat">Batters</option>
                  <option value="bowl">Bowlers</option>
                </select>
              </div>

              {/* Country filter */}
              <div>
                <label
                  htmlFor="filter-country"
                  className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                >
                  Country
                </label>
                <select
                  id="filter-country"
                  value={urlCountry ?? ""}
                  onChange={handleCountryChange}
                  className="filter-select w-full"
                >
                  <option value="">All Countries</option>
                  {countries.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              {/* Archetype filter */}
              <div>
                <label
                  htmlFor="filter-archetype"
                  className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                >
                  Archetype
                </label>
                <select
                  id="filter-archetype"
                  value={urlArchetype ?? ""}
                  onChange={handleArchetypeChange}
                  className="filter-select w-full"
                >
                  <option value="">All Archetypes</option>
                  {archetypeOptions.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </div>

              {/* Provisional filter */}
              <div>
                <label
                  htmlFor="filter-provisional"
                  className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                >
                  Provisional
                </label>
                <select
                  id="filter-provisional"
                  value={provisionalValue}
                  onChange={handleProvisionalChange}
                  className="filter-select w-full"
                >
                  <option value="all">Show All</option>
                  <option value="hide">Hide Provisional</option>
                  <option value="only">Only Provisional</option>
                </select>
              </div>

              {/* Min innings filter */}
              <div>
                <label
                  htmlFor="filter-min-innings"
                  className="text-xs text-text-muted uppercase tracking-wider mb-1 block"
                >
                  Min Innings
                </label>
                <input
                  id="filter-min-innings"
                  type="number"
                  min={0}
                  max={500}
                  step={1}
                  value={urlMinInnings || ""}
                  onChange={handleMinInningsChange}
                  placeholder="0"
                  className="filter-input w-full"
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Compare Bar (sticky, shows when ≥ 1 player selected) */}
      {compareIds.size > 0 && (
        <div className="sticky top-14 z-30 bg-surface border border-surface-elevated rounded-lg p-3 flex items-center justify-between gap-3 shadow-card animate-slide-up">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-text-secondary">
              {compareIds.size} player{compareIds.size !== 1 ? "s" : ""}{" "}
              selected
            </span>
            <button
              onClick={() => setCompareIds(new Set())}
              className="text-xs text-text-muted hover:text-text-primary transition-colors"
            >
              Clear
            </button>
          </div>
          <button
            onClick={handleCompareNavigate}
            disabled={compareIds.size < 2}
            className="btn-primary btn-sm"
          >
            Compare Selected ({compareIds.size}/4)
          </button>
        </div>
      )}

      {/* ── Results Header ────────────────────────────────────── */}
      {searchEnabled && !isLoading && !error && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-text-secondary">
            {totalResults > 0 ? (
              <>
                <span className="font-medium text-text-primary">
                  {totalResults}
                </span>{" "}
                result{totalResults !== 1 ? "s" : ""}
                {urlQuery && (
                  <>
                    {" "}
                    for{" "}
                    <span className="font-medium text-text-primary">
                      "{urlQuery}"
                    </span>
                  </>
                )}
              </>
            ) : (
              <>
                No results found
                {urlQuery && (
                  <>
                    {" "}
                    for{" "}
                    <span className="font-medium text-text-primary">
                      "{urlQuery}"
                    </span>
                  </>
                )}
              </>
            )}
          </p>

          {isFetching && !isLoading && (
            <span className="text-xs text-text-muted animate-pulse">
              Updating…
            </span>
          )}
        </div>
      )}

      {/* ── Loading State ─────────────────────────────────────── */}
      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <PlayerCardSkeleton key={i} variant="full" />
          ))}
        </div>
      )}

      {/* ── Error State ───────────────────────────────────────── */}
      {error && !isLoading && (
        <PageError
          title="Search failed"
          message="Could not fetch search results. The backend might be unavailable."
          onRetry={() => refetch()}
        />
      )}

      {/* ── Empty State (no query) ────────────────────────────── */}
      {!searchEnabled && !isLoading && (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🔍</div>
          <h2 className="text-h3 text-text-primary mb-2">
            Search T20I Players
          </h2>
          <p className="text-sm text-text-secondary max-w-md mx-auto">
            Enter a player name in the search box above, or use the filters to
            browse players by country, role, or archetype.
          </p>
          <div className="mt-6 flex items-center justify-center gap-3">
            <button
              onClick={() => {
                updateParams({ role: "bat" });
                setShowFilters(true);
              }}
              className="btn-secondary btn-sm"
            >
              Browse Batters
            </button>
            <button
              onClick={() => {
                updateParams({ role: "bowl" });
                setShowFilters(true);
              }}
              className="btn-secondary btn-sm"
            >
              Browse Bowlers
            </button>
          </div>
        </div>
      )}

      {/* ── No Results State ──────────────────────────────────── */}
      {searchEnabled && !isLoading && !error && totalResults === 0 && (
        <div className="text-center py-16">
          <div className="mb-4 text-2xl font-semibold text-text-muted">No Results</div>
          <h2 className="text-h3 text-text-primary mb-2">No players found</h2>
          <p className="text-sm text-text-secondary max-w-md mx-auto mb-4">
            {urlQuery ? (
              <>
                No players match "{urlQuery}" with the current filters. Try a
                different spelling, relax the filters, or search for a different
                player.
              </>
            ) : (
              <>
                No players match the current filter combination. Try broadening
                your filters.
              </>
            )}
          </p>
          {activeFilterCount > 0 && (
            <button
              onClick={handleClearFilters}
              className="btn-secondary btn-sm"
            >
              Clear All Filters
            </button>
          )}
        </div>
      )}

      {/* ── Results List ──────────────────────────────────────── */}
      {results.length > 0 && (
        <div className="space-y-4">
          {results.map((player, index) => (
            <PlayerCard
              key={player.id}
              player={player}
              variant="full"
              rank={index + 1}
              onCompare={handleCompareToggle}
              isCompareSelected={compareIds.has(player.id)}
              showCompareButton
              showProfileLink
            />
          ))}
        </div>
      )}

      {/* ── End of results indicator ──────────────────────────── */}
      {results.length > 0 && results.length >= DEFAULT_LIMIT && (
        <div className="text-center py-6">
          <p className="text-sm text-text-muted">
            Showing first {DEFAULT_LIMIT} results. Narrow your search or add
            filters for more specific results.
          </p>
        </div>
      )}
    </div>
  );
}
