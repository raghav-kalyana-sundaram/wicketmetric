/**
 * App — Root application component with React Router configuration.
 *
 * Route structure:
 *   /                          → Home (dashboard)
 *   /dashboard                 → Redirect to /
 *   /search                    → Player Search
 *   /player/:id                → Player Profile
 *   … (rankings, compare, matchups, team-builder, scorecards, live, simulation, etc.)
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

const Home = lazy(() => import("@/pages/Home"));
const Search = lazy(() => import("@/pages/Search"));
const PlayerProfile = lazy(() => import("@/pages/PlayerProfile"));
const Rankings = lazy(() => import("@/pages/Rankings"));

const InningsLog = lazy(() => import("@/pages/InningsLog"));
const SpellsLog = lazy(() => import("@/pages/SpellsLog"));

const Compare = lazy(() => import("@/pages/Compare"));
const Matchups = lazy(() => import("@/pages/Matchups"));
const Similar = lazy(() => import("@/pages/Similar"));
const TeamBuilder = lazy(() => import("@/pages/TeamBuilder"));

const Eras = lazy(() => import("@/pages/Eras"));
const Venues = lazy(() => import("@/pages/Venues"));
const Glossary = lazy(() => import("@/pages/Glossary"));
const Scorecards = lazy(() => import("@/pages/Scorecards"));
const Performances = lazy(() => import("@/pages/Performances"));
const ScorecardDetail = lazy(() => import("@/pages/ScorecardDetail"));
const Live = lazy(() => import("@/pages/Live"));
const LiveMatch = lazy(() => import("@/pages/LiveMatch"));
const SimulationHub = lazy(() => import("@/features/simulation/SimulationHub"));

function SuspenseWrapper({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<PageLoading />}>{children}</Suspense>;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      {
        path: "/",
        element: (
          <SuspenseWrapper>
            <Home />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/dashboard",
        element: <Navigate to="/" replace />,
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
      {
        path: "/rankings/:role",
        element: <Navigate to="/rankings" replace />,
      },
      {
        path: "/rankings/:role/:metric",
        element: <Navigate to="/rankings" replace />,
      },

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
      {
        path: "/scorecards",
        element: (
          <SuspenseWrapper>
            <Scorecards />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/performances",
        element: (
          <SuspenseWrapper>
            <Performances />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/live/match/:eventId",
        element: (
          <SuspenseWrapper>
            <LiveMatch />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/live",
        element: (
          <SuspenseWrapper>
            <Live />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/scorecards/:matchId",
        element: (
          <SuspenseWrapper>
            <ScorecardDetail />
          </SuspenseWrapper>
        ),
      },
      {
        path: "/simulation",
        element: (
          <SuspenseWrapper>
            <SimulationHub />
          </SuspenseWrapper>
        ),
      },

      {
        path: "*",
        element: <NotFound />,
      },
    ],
  },
]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      gcTime: 30 * 60 * 1000,
      retry: 2,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <FormatProvider>
        <RouterProvider router={router} />
      </FormatProvider>
    </QueryClientProvider>
  );
}
