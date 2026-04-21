/**
 * Layout — application shell with navigation bar and page content area.
 *
 * Provides the consistent chrome around every page:
 *   - Top navigation bar with logo, nav links, and hero search
 *   - Skip-to-main-content accessibility link
 *   - Main content area with max-width constraint
 *   - Responsive: collapses to hamburger menu on mobile
 *
 * Usage:
 *   // In App.tsx router setup:
 *   <Route element={<Layout />}>
 *     <Route path="/" element={<Home />} />
 *     ...
 *   </Route>
 */

import { useState, useCallback, useEffect, useRef } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  Search,
  Menu,
  X,
  BarChart3,
  Users,
  Swords,
  GitCompare,
  MapPin,
  BookOpen,
  Home,
  Trophy,
  Shield,
  FileText,
  ChevronDown,
  FlaskConical,
  Activity,
  Zap,
} from "lucide-react";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import ThemeToggle from "@/components/ThemeToggle";
import FormatToggle from "@/components/FormatToggle";
import DatasetUnavailableBanner from "@/components/DatasetUnavailableBanner";
import { useFormat } from "@/api/FormatContext";
import { useMeta, useDatasetUnavailable } from "@/api/queries";
import type { PlayerSummary } from "@/api/types";

// ── Navigation items ─────────────────────────────────────────────

interface NavItem {
  label: string;
  to: string;
  icon: React.ReactNode;
  /** If true, only show in the mobile menu (not in the top bar). */
  mobileOnly?: boolean;
  /** Treat as active when this returns true (e.g. parent section). */
  isActive?: (pathname: string) => boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Home",
    to: "/",
    icon: <Home size={16} />,
    isActive: (p) => p === "/" || p === "/dashboard",
  },
  { label: "Rankings", to: "/rankings", icon: <Trophy size={16} /> },
  {
    label: "Performances",
    to: "/performances",
    icon: <Zap size={16} />,
    isActive: (p) => p === "/performances",
  },
  { label: "Compare", to: "/compare", icon: <GitCompare size={16} /> },
  { label: "Matchups", to: "/matchups", icon: <Swords size={16} /> },
  { label: "Teams", to: "/teams", icon: <Shield size={16} /> },
  { label: "Team Builder", to: "/team-builder", icon: <Users size={16} /> },
  { label: "Scorecards", to: "/scorecards", icon: <FileText size={16} /> },
  { label: "Live", to: "/live", icon: <Activity size={16} /> },
  { label: "Eras", to: "/eras", icon: <BarChart3 size={16} /> },
  { label: "Venues", to: "/venues", icon: <MapPin size={16} /> },
  { label: "Glossary", to: "/glossary", icon: <BookOpen size={16} /> },
  {
    label: "Simulation",
    to: "/simulation",
    icon: <FlaskConical size={16} />,
  },
];

const DESKTOP_PRIMARY_NAV: NavItem[] = [
  {
    label: "Home",
    to: "/",
    icon: <Home size={16} />,
    isActive: (p) => p === "/" || p === "/dashboard",
  },
  { label: "Rankings", to: "/rankings", icon: <Trophy size={16} /> },
  {
    label: "Performances",
    to: "/performances",
    icon: <Zap size={16} />,
    isActive: (p) => p === "/performances",
  },
  { label: "Compare", to: "/compare", icon: <GitCompare size={16} /> },
  { label: "Matchups", to: "/matchups", icon: <Swords size={16} /> },
  { label: "Teams", to: "/teams", icon: <Shield size={16} /> },
  { label: "Scorecards", to: "/scorecards", icon: <FileText size={16} /> },
  { label: "Live", to: "/live", icon: <Activity size={16} /> },
];

const DESKTOP_SECONDARY_NAV: NavItem[] = [
  { label: "Team Builder", to: "/team-builder", icon: <Users size={16} /> },
  {
    label: "Simulation",
    to: "/simulation",
    icon: <FlaskConical size={16} />,
  },
  { label: "Eras", to: "/eras", icon: <BarChart3 size={16} /> },
  { label: "Venues", to: "/venues", icon: <MapPin size={16} /> },
  { label: "Glossary", to: "/glossary", icon: <BookOpen size={16} /> },
];

// ── Active link styling ──────────────────────────────────────────

function navLinkClasses({ isActive }: { isActive: boolean }): string {
  const base =
    "flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-200 ease-out-quart";
  if (isActive) {
    return `${base} bg-slate-200/90 text-primary ring-1 ring-slate-300/80 dark:bg-surface dark:ring-1 dark:ring-white/10`;
  }
  return `${base} text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50`;
}

function mobileNavLinkClasses({ isActive }: { isActive: boolean }): string {
  const base =
    "flex w-full items-center gap-3 rounded-xl px-4 py-3 text-base font-medium transition-colors duration-200 ease-out-quart";
  if (isActive) {
    return `${base} bg-slate-200/90 text-primary ring-1 ring-slate-300/80 dark:bg-surface dark:ring-1 dark:ring-white/10`;
  }
  return `${base} text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50`;
}

function isPathActive(currentPath: string, targetPath: string): boolean {
  if (targetPath === "/") return currentPath === "/";
  return currentPath === targetPath || currentPath.startsWith(`${targetPath}/`);
}

/** Dataset Men/Women × T20/IPL — below the main nav so the header stays clean. */
function DatasetContextStrip() {
  const { availableFormats } = useFormat();
  if (availableFormats.length <= 1) return null;
  return (
    <div className="border-b border-t border-surface-elevated/60 bg-surface-elevated/15 backdrop-blur-md dark:border-white/[0.06] dark:bg-[#080808] dark:backdrop-blur-none">
      <div className="mx-auto max-w-7xl px-4 py-2.5 sm:px-6 lg:px-8">
        <FormatToggle variant="strip" />
      </div>
    </div>
  );
}

// ── Component ────────────────────────────────────────────────────

export default function Layout() {
  const { data: apiMeta } = useMeta();
  const { unavailable: datasetUnavailable, healthReason } = useDatasetUnavailable();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showNavSearch, setShowNavSearch] = useState(false);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const navSearchRef = useRef<HTMLDivElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
    setShowNavSearch(false);
    setShowMoreMenu(false);
  }, [location.pathname]);

  // Close mobile menu on Escape
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileMenuOpen(false);
        setShowNavSearch(false);
        setShowMoreMenu(false);
      }
    };
    document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, []);

  // Lock body scroll when mobile menu is open
  useEffect(() => {
    if (mobileMenuOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileMenuOpen]);

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (
        showMoreMenu &&
        moreMenuRef.current &&
        !moreMenuRef.current.contains(event.target as Node)
      ) {
        setShowMoreMenu(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [showMoreMenu]);

  // Handle player selection from nav search
  const handleNavSearchSelect = useCallback(
    (player: PlayerSummary) => {
      setShowNavSearch(false);
      navigate(`/player/${player.id}`);
    },
    [navigate],
  );

  // Handle submitting the search query (navigate to search page)
  const handleNavSearchSubmit = useCallback(
    (query: string) => {
      setShowNavSearch(false);
      navigate(`/search?q=${encodeURIComponent(query)}`);
    },
    [navigate],
  );

  // Dashboard has a hero search; other routes use the nav search control
  const isDashboardPage =
    location.pathname === "/" || location.pathname === "/dashboard";
  const isMoreActive = DESKTOP_SECONDARY_NAV.some((item) =>
    isPathActive(location.pathname, item.to)
  );

  // Route-level page title + description for shareability and polish
  useEffect(() => {
    const routeTitleMap: Array<[RegExp, string, string]> = [
      [/^\/$/, "Home | Cricket Metrics", "Search, compare, and analyse men's and women's T20 and IPL with role-aware metrics and matchup intelligence."],
      [/^\/dashboard$/, "Home | Cricket Metrics", "Search, compare, and analyse men's and women's T20 and IPL with role-aware metrics and matchup intelligence."],
      [/^\/search/, "Player Search | Cricket Metrics", "Find players instantly with filters for role, country, and archetype."],
      [/^\/rankings/, "Rankings | Cricket Metrics", "Sortable batting and bowling leaderboards with advanced metrics and filters."],
      [/^\/performances/, "Performances | Cricket Metrics", "Best individual match performances ranked by scorecard match impact, with date, team, series, and player filters."],
      [/^\/compare/, "Compare Players | Cricket Metrics", "Side-by-side player comparison with metric breakdowns and trend context."],
      [/^\/matchups/, "Matchups | Cricket Metrics", "Head-to-head matchup intelligence for batters and bowlers."],
      [/^\/team-builder/, "Team Builder | Cricket Metrics", "Build XIs and evaluate team balance with role-aware analysis."],
      [/^\/scorecards/, "Scorecards | Cricket Metrics", "Match scorecards with batting, bowling, and innings context."],
      [/^\/live/, "Live scores | Cricket Metrics", "Cricket scoreboard via ESPN (proxied). Unofficial upstream; separate from Cricsheet scorecards."],
      [/^\/venues/, "Venues | Cricket Metrics", "Venue baselines, difficulty analysis, and player venue performance."],
      [/^\/teams/, "Teams | Cricket Metrics", "Browse sides by chip, see recent W/L form, squad volume, and top match-impact games for the selected men's/women's T20 or IPL slice."],
      [/^\/eras/, "Era Explorer | Cricket Metrics", "Track how T20 conditions evolve across years with era-adjusted context."],
      [/^\/glossary/, "Glossary | Cricket Metrics", "Definitions and methodology behind every cricket metric used in the app."],
      [/^\/simulation/, "Simulation Hub | Cricket Metrics", "Configure match scenarios and explore preview win odds, projections, and sample ball timelines."],
    ];

    const matched = routeTitleMap.find(([re]) => re.test(location.pathname));
    const [_, title, description] = matched ?? routeTitleMap[0];
    document.title = title;
    const meta = document.querySelector('meta[name="description"]');
    if (meta) {
      meta.setAttribute("content", description);
    }
  }, [location.pathname]);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Skip to main content (accessibility) */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      {/* ── Navigation Bar ──────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-surface-elevated/70 bg-background/90 backdrop-blur-xl transition-[border-color,background-color] duration-300 ease-out-quart dark:border-white/[0.08] dark:bg-background dark:backdrop-blur-none">
        {/* Light mode variant */}
        <div className="hidden" aria-hidden="true">
          {/* This div exists to ensure Tailwind generates the light-mode classes */}
        </div>

        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-16 items-center justify-between gap-4">
            {/* Left: Logo + Desktop Nav */}
            <div className="flex items-center gap-1 sm:gap-6">
              {/* Logo */}
              <Link
                to="/"
                className="group flex shrink-0 items-center gap-2"
                aria-label="Cricket Metrics — Home"
              >
                <span
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-slate-200/90 text-primary dark:bg-surface-elevated"
                  aria-hidden="true"
                >
                  <BarChart3 size={14} />
                </span>
                <span className="font-heading text-sm font-semibold tracking-tight text-text-primary transition-colors group-hover:text-primary sm:text-base">
                  Cricket Metrics
                </span>
              </Link>

              {/* Desktop navigation links */}
              <nav
                className="hidden md:flex items-center gap-1"
                aria-label="Main navigation"
              >
                {DESKTOP_PRIMARY_NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={(args) =>
                      navLinkClasses({
                        isActive:
                          args.isActive ||
                          (item.isActive?.(location.pathname) ?? false),
                      })
                    }
                    end={item.to === "/"}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                ))}

                <div className="relative" ref={moreMenuRef}>
                  <button
                    type="button"
                    className={`flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-200 ease-out-quart ${
                      isMoreActive
                        ? "bg-slate-200/90 text-primary ring-1 ring-slate-300/80 dark:bg-surface dark:ring-1 dark:ring-white/10"
                        : "text-text-secondary hover:bg-surface-elevated/50 hover:text-text-primary"
                    }`}
                    onClick={() => setShowMoreMenu((prev) => !prev)}
                    aria-expanded={showMoreMenu}
                    aria-haspopup="menu"
                    aria-label="More navigation items"
                  >
                    <span>More</span>
                    <ChevronDown
                      size={14}
                      className={`transition-transform duration-200 ease-out-quart ${showMoreMenu ? "rotate-180" : ""}`}
                    />
                  </button>

                  {showMoreMenu && (
                    <div
                      role="menu"
                      className="absolute left-0 top-full z-50 mt-2 w-48 animate-fade-in rounded-xl border border-slate-200/90 bg-white p-1.5 shadow-lg dark:border-white/15 dark:bg-surface dark:shadow-xl dark:backdrop-blur-none"
                    >
                      {DESKTOP_SECONDARY_NAV.map((item) => (
                        <NavLink
                          key={item.to}
                          to={item.to}
                          className={navLinkClasses}
                          end
                          onClick={() => setShowMoreMenu(false)}
                        >
                          {item.icon}
                          <span>{item.label}</span>
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              </nav>
            </div>

            {/* Right: Search + Theme Toggle + Mobile Menu */}
            <div className="flex items-center gap-2">
              {/* Theme toggle */}
              <ThemeToggle size="sm" />

              {/* Desktop nav search toggle */}
              {!isDashboardPage && (
                <div className="hidden sm:block relative" ref={navSearchRef}>
                  {showNavSearch ? (
                    <div className="w-64 lg:w-80 animate-fade-in">
                      <PlayerAutocomplete
                        onSelect={handleNavSearchSelect}
                        onSubmit={handleNavSearchSubmit}
                        size="sm"
                        placeholder="Search players..."
                        autoFocus
                        ariaLabel="Search players"
                      />
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowNavSearch(true)}
                      className="btn-ghost btn-sm"
                      aria-label="Open search"
                      title="Search players (Ctrl+K)"
                    >
                      <Search size={16} />
                      <span className="hidden lg:inline text-text-muted text-xs">
                        Search...
                      </span>
                      <kbd className="hidden lg:inline-flex items-center gap-0.5 rounded border border-surface-elevated bg-surface px-1.5 py-0.5 text-[10px] text-text-muted font-mono">
                        ⌘K
                      </kbd>
                    </button>
                  )}
                </div>
              )}

              {/* Mobile search button */}
              {!isDashboardPage && (
                <button
                  onClick={() => navigate("/search")}
                  className="sm:hidden btn-ghost btn-sm"
                  aria-label="Search players"
                >
                  <Search size={18} />
                </button>
              )}

              {/* Mobile menu toggle */}
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="md:hidden btn-ghost btn-sm"
                aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
                aria-expanded={mobileMenuOpen}
                aria-controls="mobile-menu"
              >
                {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
              </button>
            </div>
          </div>
        </div>

        <DatasetContextStrip />

        {datasetUnavailable && (
          <DatasetUnavailableBanner reason={healthReason} />
        )}

        {/* ── Mobile Menu ───────────────────────────────────────── */}
        {mobileMenuOpen && (
          <>
            {/* Backdrop */}
            <div
              className="fixed inset-0 top-16 z-40 bg-black/40 md:hidden"
              onClick={() => setMobileMenuOpen(false)}
              aria-hidden="true"
            />

            {/* Menu panel */}
            <nav
              id="mobile-menu"
              className="fixed inset-x-0 top-16 z-50 border-b border-surface-elevated bg-background shadow-lg animate-slide-up md:hidden"
              aria-label="Mobile navigation"
            >
              <div className="px-4 py-4 space-y-1 max-h-[calc(100vh-3.5rem)] overflow-y-auto">
                {/* Mobile search */}
                {!isDashboardPage && (
                  <div className="mb-4">
                    <PlayerAutocomplete
                      onSelect={(player) => {
                        setMobileMenuOpen(false);
                        navigate(`/player/${player.id}`);
                      }}
                      onSubmit={(q) => {
                        setMobileMenuOpen(false);
                        navigate(`/search?q=${encodeURIComponent(q)}`);
                      }}
                      size="md"
                      placeholder="Search players..."
                      ariaLabel="Search players"
                    />
                  </div>
                )}

                {/* Nav links */}
                {NAV_ITEMS.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={(args) =>
                      mobileNavLinkClasses({
                        isActive:
                          args.isActive ||
                          (item.isActive?.(location.pathname) ?? false),
                      })
                    }
                    end={item.to === "/"}
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                ))}

                {/* Divider */}
                <hr className="my-3 border-surface-elevated" />

                {/* Dataset (duplicate of strip — visible when menu open on small screens) */}
                <div className="px-4 py-2">
                  <FormatToggle variant="toolbar" />
                </div>

                {/* Theme toggle in mobile menu */}
                <div className="px-4 py-2">
                  <ThemeToggle size="md" showLabel />
                </div>

                <hr className="my-3 border-surface-elevated" />

                {/* Secondary links */}
                <NavLink
                  to="/search"
                  className={mobileNavLinkClasses}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  <Search size={16} />
                  <span>Player Search</span>
                </NavLink>
                <NavLink
                  to="/team-builder"
                  className={mobileNavLinkClasses}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  <Users size={16} />
                  <span>Team Builder</span>
                </NavLink>
              </div>
            </nav>
          </>
        )}
      </header>

      {/* ── Keyboard shortcut: Ctrl+K / Cmd+K to open search ───── */}
      <KeyboardShortcutListener
        onSearchOpen={() => {
          if (isDashboardPage) {
            const heroInput =
              document.querySelector<HTMLInputElement>("#hero-search input");
            heroInput?.focus();
          } else {
            setShowNavSearch(true);
          }
        }}
      />

      {/* ── Main Content ────────────────────────────────────────── */}
      <main
        id="main-content"
        className="flex-1 animate-content-enter motion-reduce:animate-none"
      >
        <Outlet />
      </main>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="app-footer border-t border-surface-elevated/70 bg-surface/80 dark:border-white/[0.08] dark:bg-background">
        <div         className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:px-8">
          <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="app-footer-brand flex min-w-0 flex-wrap items-center gap-2 text-sm text-text-secondary">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-slate-200/90 text-primary dark:bg-surface-elevated">
                <BarChart3 size={12} />
              </span>
              <span className="font-heading font-medium text-text-primary">Cricket Metrics</span>
              <span className="text-text-muted/50">·</span>
              <span className="app-footer-tagline">T20 Intelligence</span>
            </div>

            <nav className="app-footer-links flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
              <Link to="/glossary" className="transition-colors hover:text-text-primary">
                Methodology
              </Link>
              <a
                href="https://github.com/raghav-kalyana-sundaram/wicketmetric"
                target="_blank"
                rel="noreferrer"
                className="transition-colors hover:text-text-primary"
              >
                GitHub
              </a>
              <a
                href="https://cricsheet.org/"
                target="_blank"
                rel="noreferrer"
                className="transition-colors hover:text-text-primary"
              >
                Cricsheet
              </a>
            </nav>
          </div>
          <p className="app-footer-data mt-2 text-xs text-text-muted">
            Data source: Cricsheet ball-by-ball JSON (international T20, IPL, WPL).
            {apiMeta?.status === "ok" && apiMeta.data_through_date && (
              <>
                {" "}
                Career tables through{" "}
                <span className="text-text-secondary font-medium tabular-nums">
                  {apiMeta.data_through_date}
                </span>
                .
              </>
            )}
          </p>
        </div>
      </footer>
    </div>
  );
}

// ── Keyboard shortcut listener ───────────────────────────────────

interface KeyboardShortcutListenerProps {
  onSearchOpen: () => void;
}

function KeyboardShortcutListener({
  onSearchOpen,
}: KeyboardShortcutListenerProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ctrl+K or Cmd+K to open search
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onSearchOpen();
      }
    };

    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onSearchOpen]);

  return null;
}

// ── Loading fallback ─────────────────────────────────────────────

/**
 * A full-page loading spinner for use as a Suspense fallback.
 * Renders within the Layout's main content area.
 */
export function PageLoading() {
  return (
    <div
      className="flex items-center justify-center py-32"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex flex-col items-center gap-4">
        <div className="relative" aria-hidden>
          <div className="h-12 w-12 rounded-full border-4 border-surface-elevated" />
          <div className="absolute inset-0 h-12 w-12 rounded-full border-4 border-primary border-t-transparent animate-spin motion-reduce:animate-none" />
        </div>
        <p className="text-sm text-text-secondary">Loading this view…</p>
      </div>
    </div>
  );
}

/**
 * A full-page error display.
 */
export function PageError({
  title = "Something went wrong",
  message = "An unexpected error occurred. Please try again.",
  onRetry,
  variant = "default",
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  /** Softer copy when the backend has no DuckDB dataset (HTTP 503 / health degraded). */
  variant?: "default" | "dataset";
}) {
  const isDataset = variant === "dataset";
  return (
    <div className="flex items-center justify-center py-32">
      <div className="flex flex-col items-center gap-4 text-center max-w-md px-4">
        <div
          className={
            isDataset
              ? "text-xl font-semibold text-amber-700 dark:text-amber-300"
              : "text-2xl text-danger"
          }
        >
          {isDataset ? "Dataset not loaded" : "Error"}
        </div>
        <h2 className="text-h3 text-text-primary">{title}</h2>
        <p className="text-sm text-text-secondary">{message}</p>
        {onRetry && (
          <button onClick={onRetry} className="btn-primary">
            Try Again
          </button>
        )}
        <Link to="/" className="btn-ghost text-sm">
          ← Back to Home
        </Link>
      </div>
    </div>
  );
}

/**
 * 404 Not Found page.
 */
export function NotFound() {
  return (
    <div className="flex items-center justify-center py-32">
      <div className="flex flex-col items-center gap-4 text-center max-w-md">
        <div className="text-2xl font-semibold text-primary">404</div>
        <h1 className="text-h2 text-text-primary">Page Not Found</h1>
        <p className="text-sm text-text-secondary">
          That URL is not part of this app. Check the address, or start again
          from home or search.
        </p>
        <div className="flex items-center gap-3 mt-2">
          <Link to="/" className="btn-primary">
            Go Home
          </Link>
          <Link to="/search" className="btn-secondary">
            Search Players
          </Link>
        </div>
      </div>
    </div>
  );
}
