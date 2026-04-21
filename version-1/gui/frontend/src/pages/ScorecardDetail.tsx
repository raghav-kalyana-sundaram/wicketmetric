/**
 * ScorecardDetail — Full-page scorecard view (ESPNcricinfo-style).
 * Route: /scorecards/:matchId
 * Data: useQuery → ScorecardDetailBody
 */

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useFormat } from "@/api/FormatContext";
import type { Scorecard } from "@/components/scorecard/scorecardTypes";
import ScorecardDetailBody from "@/components/scorecard/ScorecardDetailBody";
import "@/styles/scorecards.css";

export default function ScorecardDetail(): JSX.Element {
  const { matchId } = useParams<{ matchId: string }>();
  const { format } = useFormat();

  const {
    data: scorecard,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["scorecard", format, matchId],
    enabled: !!matchId,
    queryFn: async ({ signal }) => {
      if (!matchId) throw new Error("No match ID");
      return api.getScorecard(matchId, signal) as Promise<Scorecard>;
    },
    staleTime: 10 * 60 * 1000,
  });

  if (!matchId) {
    return (
      <div className="scorecard-detail app-page page-stack text-text-primary max-w-5xl">
        <p className="text-text-secondary">Invalid match ID.</p>
        <Link to="/scorecards" className="text-primary underline mt-2 inline-block">
          ← Back to Scorecards
        </Link>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="scorecard-detail app-page page-stack text-text-primary max-w-5xl">
        <div className="section-card section-card-body space-y-3" aria-live="polite">
          <div className="skeleton h-6 w-64 rounded-md" />
          <div className="skeleton h-10 w-full rounded-md" />
          <div className="skeleton h-10 w-full rounded-md" />
          <div className="skeleton h-10 w-full rounded-md" />
        </div>
      </div>
    );
  }

  if (isError || !scorecard) {
    return (
      <div className="scorecard-detail app-page page-stack text-text-primary max-w-5xl">
        <div className="state-error">
          {error instanceof Error ? error.message : "Failed to load scorecard"}
          <div className="mt-3 flex gap-2">
            <button type="button" className="btn-primary btn-sm" onClick={() => refetch()}>
              Retry
            </button>
            <Link to="/scorecards" className="btn-secondary btn-sm">
              Back to Scorecards
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-page">
      <ScorecardDetailBody
        scorecard={scorecard}
        matchId={matchId}
        variant="live"
      />
    </div>
  );
}
