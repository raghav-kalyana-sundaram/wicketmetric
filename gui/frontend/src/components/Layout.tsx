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
  FileText,
  ChevronDown,
} from "lucide-react";
import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import ThemeToggle from "@/components/ThemeToggle";
import FormatToggle from "@/components/FormatToggle";
import type { PlayerSummary } from "@/api/types";

// ── Navigation items ─────────────────────────────────────────────

interface NavItem {
  label: string;
  to: string;
  icon: React.ReactNode;
  /** If true, only show in the mobile menu (not in the top bar). */
  mobileOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Home", to: "/", icon: <Home size={16} />, mobileOnly: true },
  { label: "Rankings", to: "/rankings", icon: <Trophy size={16} /> },
  { label: "Compare", to: "/compare", icon: <GitCompare size={16} /> },
  { label: "Matchups", to: "/matchups", icon: <Swords size={16} /> },
  { label: "Team Builder", to: "/team-builder", icon: <Users size={16} /> },
  { label: "Scorecards", to: "/scorecards", icon: <FileText size={16} /> },
  { label: "Eras", to: "/eras", icon: <BarChart3 size={16} /> },
  { label: "Venues", to: "/venues", icon: <MapPin size={16} /> },
  { label: "Glossary", to: "/glossary", icon: <BookOpen size={16} /> },
];

const DESKTOP_PRIMARY_NAV: NavItem[] = [
  { label: "Rankings", to: "/rankings", icon: <Trophy size={16} /> },
  { label: "Compare", to: "/compare", icon: <GitCompare size={16} /> },
  { label: "Matchups", to: "/matchups", icon: <Swords size={16} /> },
  { label: "Scorecards", to: "/scorecards", icon: <FileText size={16} /> },
];

const DESKTOP_SECONDARY_NAV: NavItem[] = [
  { label: "Team Builder", to: "/team-builder", icon: <Users size={16} /> },
  { label: "Eras", to: "/eras", icon: <BarChart3 size={16} /> },
  { label: "Venues", to: "/venues", icon: <MapPin size={16} /> },
  { label: "Glossary", to: "/glossary", icon: <BookOpen size={16} /> },
];

// ── Active link styling ──────────────────────────────────────────

function navLinkClasses({ isActive }: { isActive: boolean }): string {
  const base =
    "flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors";
  if (isActive) {
    return `${base} bg-primary/10 text-primary`;
  }
  return `${base} text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50`;
}

function mobileNavLinkClasses({ isActive }: { isActive: boolean }): string {
  const base =
    "flex w-full items-center gap-3 rounded-xl px-4 py-3 text-base font-medium transition-colors";
  if (isActive) {
    return `${base} bg-primary/10 text-primary`;
  }
  return `${base} text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50`;
}

function isPathActive(currentPath: string, targetPath: string): boolean {
  if (targetPath === "/") return currentPath === "/";
  return currentPath === targetPath || currentPath.startsWith(`${targetPath}/`);
}

// ── Component ────────────────────────────────────────────────────

export default function Layout() {
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

  // Don't show the nav search on the home page (it has its own hero search)
  const isHomePage = location.pathname === "/";
  const isMoreActive = DESKTOP_SECONDARY_NAV.some((item) =>
    isPathActive(location.pathname, item.to)
  );

  // Route-level page title + description for shareability and polish
  useEffect(() => {
    const routeTitleMap: Array<[RegExp, string, string]> = [
      [/^\/$/, "Cricket Metrics | Premium T20 Analytics", "Search, compare, and analyse T20I and IPL players with role-aware metrics, pressure scoring, and matchup intelligence."],
      [/^\/search/, "Player Search | Cricket Metrics", "Find players instantly with filters for role, country, and archetype."],
      [/^\/rankings/, "Rankings | Cricket Metrics", "Sortable batting and bowling leaderboards with advanced metrics and filters."],
      [/^\/compare/, "Compare Players | Cricket Metrics", "Side-by-side player comparison with metric breakdowns and trend context."],
      [/^\/matchups/, "Matchups | Cricket Metrics", "Head-to-head matchup intelligence for batters and bowlers."],
      [/^\/team-builder/, "Team Builder | Cricket Metrics", "Build XIs and evaluate team balance with role-aware analysis."],
      [/^\/scorecards/, "Scorecards | Cricket Metrics", "Match scorecards with batting, bowling, and innings context."],
      [/^\/venues/, "Venues | Cricket Metrics", "Venue baselines, difficulty analysis, and player venue performance."],
      [/^\/eras/, "Era Explorer | Cricket Metrics", "Track how T20 conditions evolve across years with era-adjusted context."],
      [/^\/glossary/, "Glossary | Cricket Metrics", "Definitions and methodology behind every cricket metric used in the app."],
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
      <header className="sticky top-0 z-50 border-b border-surface-elevated/70 bg-background/90 backdrop-blur-xl">
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
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary/20 text-primary"
                  aria-hidden="true"
                >
                  <BarChart3 size={14} />
                </span>
                <span className="text-sm font-semibold tracking-tight text-text-primary transition-colors group-hover:text-primary sm:text-base">
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
                    className={navLinkClasses}
                    end={item.to === "/"}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                ))}

                <div className="relative" ref={moreMenuRef}>
                  <button
                    type="button"
                    className={`flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
                      isMoreActive
                        ? "bg-primary/10 text-primary"
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
                      className={`transition-transform ${showMoreMenu ? "rotate-180" : ""}`}
                    />
                  </button>

                  {showMoreMenu && (
                    <div
                      role="menu"
                      className="absolute left-0 top-full z-50 mt-2 w-48 rounded-xl border border-surface-elevated bg-surface p-1.5 shadow-card-hover"
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

            {/* Right: Search + Format Toggle + Theme Toggle + Mobile Menu */}
            <div className="flex items-center gap-2">
              {/* Format toggle (T20I / IPL) */}
              <FormatToggle className="hidden sm:flex" />

              {/* Theme toggle */}
              <ThemeToggle size="sm" />

              {/* Desktop nav search toggle */}
              {!isHomePage && (
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
              {!isHomePage && (
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
                {!isHomePage && (
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
                    className={mobileNavLinkClasses}
                    end={item.to === "/"}
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                ))}

                {/* Divider */}
                <hr className="my-3 border-surface-elevated" />

                {/* Format toggle in mobile menu */}
                <div className="px-4 py-2">
                  <FormatToggle />
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
          if (isHomePage) {
            // On home page, focus the hero search
            const heroInput =
              document.querySelector<HTMLInputElement>("#hero-search input");
            heroInput?.focus();
          } else {
            setShowNavSearch(true);
          }
        }}
      />

      {/* ── Main Content ────────────────────────────────────────── */}
      <main id="main-content" className="flex-1">
        <Outlet />
      </main>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="app-footer border-t border-surface-elevated/70 bg-surface/80">
        <div className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="app-footer-brand flex items-center gap-2 text-sm text-text-secondary">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-primary/15 text-primary">
                <BarChart3 size={12} />
              </span>
              <span className="font-medium text-text-primary">Cricket Metrics</span>
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
            Data source: Cricsheet ball-by-ball JSON (T20I and IPL).
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
    <div className="flex items-center justify-center py-32">
      <div className="flex flex-col items-center gap-4">
        <div className="relative">
          <div className="h-12 w-12 rounded-full border-4 border-surface-elevated" />
          <div className="absolute inset-0 h-12 w-12 rounded-full border-4 border-primary border-t-transparent animate-spin" />
        </div>
        <p className="text-sm text-text-muted">Loading…</p>
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
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center justify-center py-32">
      <div className="flex flex-col items-center gap-4 text-center max-w-md">
        <div className="text-2xl text-danger">Error</div>
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
          The page you're looking for doesn't exist. It might have been removed
          or the URL might be incorrect.
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
