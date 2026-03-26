import { useMutation } from "@tanstack/react-query";
import { useFormat } from "@/api/FormatContext";
import type { PlayerSummary } from "@/api/types";
import type { SimulationScope } from "../types";
import {
  computeSimulationDelayMs,
  runMockSimulation,
  type SimulationResult,
  type SimulationRunPayload,
} from "../utils/simulationMock";

export type { SimulationScope } from "../types";

export interface SimulationFormSnapshot {
  scope: SimulationScope;
  overNumber: number;
  tournamentLabel: string;
  battingTeam: string;
  bowlingTeam: string;
  iterations: number;
  striker: PlayerSummary | null;
  nonStriker: PlayerSummary | null;
  bowler: PlayerSummary | null;
  /** Full match only */
  inningsPhase: "first" | "chase";
  targetRuns: number | null;
  injectState: boolean;
  injectRuns: number;
  injectWickets: number;
  injectLegalBalls: number;
  dismissedBatters: PlayerSummary[];
  battingXI: (PlayerSummary | null)[];
  bowlingXI: (PlayerSummary | null)[];
  /** Specific over — score context */
  contextRuns: number;
  contextWickets: number;
  contextLegalBalls: number;
}

function buildPayload(
  format: string,
  snap: SimulationFormSnapshot,
): SimulationRunPayload {
  return {
    format,
    scope: snap.scope,
    overNumber: snap.overNumber,
    tournamentLabel: snap.tournamentLabel,
    battingTeam: snap.battingTeam,
    bowlingTeam: snap.bowlingTeam,
    iterations: snap.iterations,
    striker: snap.striker,
    nonStriker: snap.nonStriker,
    bowler: snap.bowler,
    inningsPhase: snap.inningsPhase,
    targetRuns: snap.targetRuns,
    injectState: snap.injectState,
    injectRuns: snap.injectRuns,
    injectWickets: snap.injectWickets,
    injectLegalBalls: snap.injectLegalBalls,
    dismissedBatters: snap.dismissedBatters,
    battingXI: snap.battingXI,
    bowlingXI: snap.bowlingXI,
    contextRuns: snap.contextRuns,
    contextWickets: snap.contextWickets,
    contextLegalBalls: snap.contextLegalBalls,
  };
}

export function useRunSimulation() {
  const { format } = useFormat();

  return useMutation<SimulationResult, Error, SimulationFormSnapshot>({
    mutationFn: async (snap) => {
      const delayMs = computeSimulationDelayMs(snap.iterations);
      await new Promise((r) => setTimeout(r, delayMs));
      return runMockSimulation(buildPayload(format, snap));
    },
  });
}
