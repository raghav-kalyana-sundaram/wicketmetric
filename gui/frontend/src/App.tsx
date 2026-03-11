/**
 * App — Root application component with React Router configuration.
 *
 * Sets up:
 *   - TanStack Query provider for server-state management
 *   - React Router with all page routes (from gui.md § 5)
 *   - Layout wrapper with navigation bar
 *   - Lazy-loaded pages for code splitting
 *   - 404 catch-all route
 *
 * Route structure mirrors gui.md § 5 "Page & Route Structure":
 *   /                          → Home / Dashboard
 *   /search                    → Player Search
 *   /player/:id                → Player Profile
 *   /player/:id/innings        → Full Innings Log
 *   /player/:id/spells         → Full Spells Log
 *   /rankings                  → Leaderboards & Rankings
 *   /compare                   → Player Comparison
 *   /matchups                  → Head-to-Head Matchups
 *   /matchups/explore          → Matchup Explorer
 *   /similar/:id               → Similar Players
 *   /team-builder              → Team Builder
 *   /eras                      → Era Explorer
 *   /venues                    → Venue Analysis
 *   /glossary                  → Glossary & Methodology
 */

import { lazy, Suspense } from "react";
import {
  createBrowserRouter,
  RouterProvider,
  Navigate,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import Layout, { PageLoading, NotFound } from "@/components/Layout";
import { FormatProvider } from "@/api/FormatContext";

// ── Lazy-loaded pages (code-split per route) ─────────────────────

// Phase 1: Core MVP pages
const Home = lazy(() => import("@/pages/Home"));
const Search = lazy(() => import("@/pages/Search"));
const PlayerProfile = lazy(() => import("@/pages/PlayerProfile"));
const Rankings = lazy(() => import("@/pages/Rankings"));

// Phase 1: Detail log pages
const InningsLog = lazy(() => import("@/pages/InningsLog"));
const SpellsLog = lazy(() => import("@/pages/SpellsLog"));

// Phase 2: Rich Feature pages
const Compare = lazy(() => import("@/pages/Compare"));
const Matchups = lazy(() => import("@/pages/Matchups"));
const Similar = lazy(() => import("@/pages/Similar"));
const TeamBuilder = lazy(() => import("@/pages/TeamBuilder"));

// Phase 3: Polish & Advanced pages
const Eras = lazy(() => import("@/pages/Eras"));
const Venues = lazy(() => import("@/pages/Venues"));
const Glossary = lazy(() => import("@/pages/Glossary"));

// ── Suspense wrapper ─────────────────────────────────────────────

function SuspenseWrapper({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<PageLoading />}>{children}</Suspense>;
}

// ── Router configuration ─────────────────────────────────────────

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      // ── Phase 1: Core MVP routes ───────────────────────────
      {
        path: "/",
        element: (
          <SuspenseWrapper>
            <Home />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/search",
        element: (
          <SuspenseWrapper>
            <Search />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/player/:id",
        element: (
          <SuspenseWrapper>
            <PlayerProfile />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/player/:id/innings",
        element: (
          <SuspenseWrapper>
            <InningsLog />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/player/:id/spells",
        element: (
          <SuspenseWrapper>
            <SpellsLog />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/rankings",
        element: (
          <SuspenseWrapper>
            <Rankings />
          </SuspenseWrapper>
        ),
      },
      // Legacy route redirect
      {
        path: "/rankings/:role",
        element: <Navigate to="/rankings" replace />,
      },
      {
        path: "/rankings/:role/:metric",
        element: <Navigate to="/rankings" replace />,
      },

      // ── Phase 2: Rich Features routes ──────────────────────
      {
        path: "/compare",
        element: (
          <SuspenseWrapper>
            <Compare />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/matchups",
        element: (
          <SuspenseWrapper>
            <Matchups />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/matchups/explore",
        element: (
          <SuspenseWrapper>
            <Matchups />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/similar/:id",
        element: (
          <SuspenseWrapper>
            <Similar />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/team-builder",
        element: (
          <SuspenseWrapper>
            <TeamBuilder />
          </SuspenseWrapper>
        ),
      },

      // ── Phase 3: Polish & Advanced routes ──────────────────
      {
        path: "/eras",
        element: (
          <SuspenseWrapper>
            <Eras />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/venues",
        element: (
          <SuspenseWrapper>
            <Venues />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/glossary",
        element: (
          <SuspenseWrapper>
            <Glossary />
          </SuspenseWrapper>
        ),
      },

      // ── 404 catch-all ──────────────────────────────────────
      {
        path: "*",
        element: <NotFound />,
      },
    ],
  },
]);

// ── TanStack Query client ────────────────────────────────────────

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Data is static (pipeline outputs) — generous stale times.
      staleTime: 5 * 60 * 1000, // 5 minutes default
      gcTime: 30 * 60 * 1000, // 30 minutes garbage collection
      retry: 2,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
  },
});

// ── App component ────────────────────────────────────────────────

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <FormatProvider>
        <RouterProvider router={router} />
      </FormatProvider>
    </QueryClientProvider>
  );
}
