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
  { label: "Eras", to: "/eras", icon: <BarChart3 size={16} /> },
  { label: "Venues", to: "/venues", icon: <MapPin size={16} /> },
  { label: "Glossary", to: "/glossary", icon: <BookOpen size={16} /> },
];

// ── Active link styling ──────────────────────────────────────────

function navLinkClasses({ isActive }: { isActive: boolean }): string {
  const base =
    "flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors";
  if (isActive) {
    return `${base} bg-primary/10 text-primary`;
  }
  return `${base} text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50`;
}

function mobileNavLinkClasses({ isActive }: { isActive: boolean }): string {
  const base =
    "flex items-center gap-3 px-4 py-3 rounded-lg text-base font-medium transition-colors w-full";
  if (isActive) {
    return `${base} bg-primary/10 text-primary`;
  }
  return `${base} text-text-secondary hover:text-text-primary hover:bg-surface-elevated/50`;
}

// ── Component ────────────────────────────────────────────────────

export default function Layout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showNavSearch, setShowNavSearch] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const navSearchRef = useRef<HTMLDivElement>(null);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
    setShowNavSearch(false);
  }, [location.pathname]);

  // Close mobile menu on Escape
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileMenuOpen(false);
        setShowNavSearch(false);
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

  return (
    <div className="min-h-screen flex flex-col">
      {/* Skip to main content (accessibility) */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      {/* ── Navigation Bar ──────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-surface-elevated/50 bg-background/80 backdrop-blur-xl">
        {/* Light mode variant */}
        <div className="hidden" aria-hidden="true">
          {/* This div exists to ensure Tailwind generates the light-mode classes */}
        </div>

        <div className="mx-auto max-w-8xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-14 items-center justify-between gap-4">
            {/* Left: Logo + Desktop Nav */}
            <div className="flex items-center gap-1 sm:gap-6">
              {/* Logo */}
              <Link
                to="/"
                className="flex items-center gap-2 shrink-0 group"
                aria-label="Cricket Metrics — Home"
              >
                <span
                  className="text-lg sm:text-xl"
                  role="img"
                  aria-hidden="true"
                >
                  🏏
                </span>
                <span className="font-bold text-text-primary text-sm sm:text-base group-hover:text-primary transition-colors">
                  <span className="hidden xs:inline">Cricket </span>Metrics
                </span>
              </Link>

              {/* Desktop navigation links */}
              <nav
                className="hidden md:flex items-center gap-1"
                aria-label="Main navigation"
              >
                {NAV_ITEMS.filter((item) => !item.mobileOnly).map((item) => (
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
              className="fixed inset-0 top-14 bg-black/40 z-40 md:hidden"
              onClick={() => setMobileMenuOpen(false)}
              aria-hidden="true"
            />

            {/* Menu panel */}
            <nav
              id="mobile-menu"
              className="fixed inset-x-0 top-14 z-50 md:hidden bg-background border-b border-surface-elevated shadow-lg animate-slide-up"
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
      <main
        id="main-content"
        className="flex-1 mx-auto w-full max-w-8xl px-4 sm:px-6 lg:px-8 py-6"
      >
        <Outlet />
      </main>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="border-t border-surface-elevated/50 bg-background/50">
        <div className="mx-auto max-w-8xl px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-text-muted">
            <div className="flex items-center gap-2">
              <span role="img" aria-hidden="true">
                🏏
              </span>
              <span>Cricket Metrics</span>
              <span className="text-text-muted/50">·</span>
              <span>T20 Player Intelligence</span>
            </div>
            <div className="flex items-center gap-4">
              <Link
                to="/glossary"
                className="hover:text-text-primary transition-colors"
              >
                Methodology
              </Link>
              <span className="text-text-muted/30">·</span>
              <span className="text-xs">
                Data: Cricsheet &middot; Ball-by-ball T20I &amp; IPL JSON
              </span>
            </div>
          </div>
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
        <div className="text-4xl">⚠️</div>
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
        <div className="text-6xl">🏏</div>
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
