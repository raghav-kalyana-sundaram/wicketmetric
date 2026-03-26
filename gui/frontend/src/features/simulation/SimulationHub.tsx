/**
 * Simulation Hub — scoped scenario setup with preview (mock) outcomes.
 * Route: /simulation
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import { FlaskConical } from "lucide-react";
import { useFormat } from "@/api/FormatContext";
import type { PlayerSummary } from "@/api/types";
import api from "@/api/client";
import { profileToPlayerSummary } from "@/lib/profileToPlayerSummary";
import SimulationSetupPanel from "./components/SimulationSetupPanel";
import SimulationResultsTabs from "./components/SimulationResultsTabs";
import SimulationLoadingPanel from "./components/SimulationLoadingPanel";
import {
  useRunSimulation,
  type SimulationFormSnapshot,
} from "./hooks/useRunSimulation";
import type { SimulationScope } from "./types";
import {
  parseSimulationLineupParams,
  simulationLineupToSearchParams,
} from "./utils/simulationUrlSync";
import {
  fetchLastBattingXiPlayerIds,
  fetchLastBowlingXiPlayerIds,
} from "./utils/lastFieldedXi";

const XI_AUTOFILL_DEBOUNCE_MS = 480;

function emptyXI(): (PlayerSummary | null)[] {
  return Array.from({ length: 11 }, () => null);
}

async function fillXiFromPlayerIds(
  ids: string[],
  signal: AbortSignal,
): Promise<(PlayerSummary | null)[]> {
  const slot = emptyXI();
  const slice = ids.slice(0, 11);
  await Promise.all(
    slice.map((id, i) =>
      (async () => {
        if (signal.aborted) return;
        try {
          slot[i] = profileToPlayerSummary(await api.getPlayer(id, signal));
        } catch {
          slot[i] = null;
        }
      })(),
    ),
  );
  return slot;
}

export default function SimulationHub() {
  const { format } = useFormat();
  const [, setSearchParams] = useSearchParams();
  const resultsRef = useRef<HTMLDivElement>(null);
  const urlLineupLoaded = useRef(false);
  /** Latest writer wins for batting / bowling XI (URL share vs team autofill). */
  const battingXiApplyGen = useRef(0);
  const bowlingXiApplyGen = useRef(0);

  const [scope, setScope] = useState<SimulationScope>("full_match");
  const [overNumber, setOverNumber] = useState(19);
  const [tournamentLabel, setTournamentLabel] = useState("");
  const [battingTeam, setBattingTeam] = useState("");
  const [bowlingTeam, setBowlingTeam] = useState("");
  const [iterations, setIterations] = useState(2500);
  const [striker, setStriker] = useState<PlayerSummary | null>(null);
  const [nonStriker, setNonStriker] = useState<PlayerSummary | null>(null);
  const [bowler, setBowler] = useState<PlayerSummary | null>(null);

  const [inningsPhase, setInningsPhase] = useState<"first" | "chase">("chase");
  const [targetRuns, setTargetRuns] = useState<number | null>(165);
  const [injectState, setInjectState] = useState(false);
  const [injectRuns, setInjectRuns] = useState(0);
  const [injectWickets, setInjectWickets] = useState(0);
  const [injectLegalBalls, setInjectLegalBalls] = useState(0);
  const [dismissedSlots, setDismissedSlots] = useState<(PlayerSummary | null)[]>(
    [],
  );
  const [battingXI, setBattingXI] = useState(emptyXI);
  const [bowlingXI, setBowlingXI] = useState(emptyXI);
  const [contextRuns, setContextRuns] = useState(0);
  const [contextWickets, setContextWickets] = useState(0);
  const [contextLegalBalls, setContextLegalBalls] = useState(0);

  const runSimulation = useRunSimulation();

  useEffect(() => {
    setDismissedSlots((prev) => {
      const w = injectWickets;
      const next = prev.slice(0, w);
      while (next.length < w) next.push(null);
      return next;
    });
  }, [injectWickets]);

  useEffect(() => {
    runSimulation.reset();
  }, [format, runSimulation.reset]);

  useEffect(() => {
    if (urlLineupLoaded.current) return;
    const { batIds, bowlIds } = parseSimulationLineupParams(
      window.location.search,
    );
    if (batIds.length === 0 && bowlIds.length === 0) {
      urlLineupLoaded.current = true;
      return;
    }

    const urlBatGen = ++battingXiApplyGen.current;
    const urlBowlGen = ++bowlingXiApplyGen.current;
    const ac = new AbortController();
    let cancelled = false;
    (async () => {
      try {
        const batSlot = await fillXiFromPlayerIds(batIds, ac.signal);
        if (cancelled || ac.signal.aborted) return;
        const bowlSlot = await fillXiFromPlayerIds(bowlIds, ac.signal);
        if (cancelled || ac.signal.aborted) return;
        if (battingXiApplyGen.current === urlBatGen) {
          setBattingXI(batSlot);
        }
        if (bowlingXiApplyGen.current === urlBowlGen) {
          setBowlingXI(bowlSlot);
        }
        setScope("full_match");
      } finally {
        urlLineupLoaded.current = true;
      }
    })();

    return () => {
      cancelled = true;
      ac.abort();
    };
  }, []);

  useEffect(() => {
    if (scope !== "full_match") return;
    const name = battingTeam.trim();
    if (!name) return;

    const ac = new AbortController();
    const g = ++battingXiApplyGen.current;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const ids = await fetchLastBattingXiPlayerIds(name, ac.signal);
          if (ac.signal.aborted || battingXiApplyGen.current !== g) return;
          const slot = await fillXiFromPlayerIds(ids, ac.signal);
          if (ac.signal.aborted || battingXiApplyGen.current !== g) return;
          setBattingXI(slot);
        } catch {
          /* ignore */
        }
      })();
    }, XI_AUTOFILL_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      ac.abort();
    };
  }, [battingTeam, scope, format]);

  useEffect(() => {
    if (scope !== "full_match") return;
    const name = bowlingTeam.trim();
    if (!name) return;

    const ac = new AbortController();
    const g = ++bowlingXiApplyGen.current;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const ids = await fetchLastBowlingXiPlayerIds(name, ac.signal);
          if (ac.signal.aborted || bowlingXiApplyGen.current !== g) return;
          const slot = await fillXiFromPlayerIds(ids, ac.signal);
          if (ac.signal.aborted || bowlingXiApplyGen.current !== g) return;
          setBowlingXI(slot);
        } catch {
          /* ignore */
        }
      })();
    }, XI_AUTOFILL_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      ac.abort();
    };
  }, [bowlingTeam, scope, format]);

  const fullBattingXI = useMemo(
    () => battingXI.every((p) => p != null),
    [battingXI],
  );
  const fullBowlingXI = useMemo(
    () => bowlingXI.every((p) => p != null),
    [bowlingXI],
  );

  const injectDismissalsOk = useMemo(() => {
    if (!injectState || injectWickets === 0) return true;
    if (!striker || !nonStriker) return false;
    for (let i = 0; i < injectWickets; i++) {
      if (!dismissedSlots[i]) return false;
    }
    return true;
  }, [injectState, injectWickets, striker, nonStriker, dismissedSlots]);

  const canRun = useMemo(() => {
    if (!battingTeam.trim() || !bowlingTeam.trim()) return false;
    if (iterations < 100 || iterations > 10_000) return false;
    if (scope === "specific_over") {
      if (!striker || !nonStriker || !bowler) return false;
      if (overNumber < 1 || overNumber > 20) return false;
    }
    if (scope === "full_match") {
      if (!fullBattingXI || !fullBowlingXI) return false;
      if (inningsPhase === "chase") {
        if (targetRuns == null || targetRuns < 1) return false;
      }
      if (!injectDismissalsOk) return false;
    }
    return true;
  }, [
    battingTeam,
    bowlingTeam,
    iterations,
    scope,
    striker,
    nonStriker,
    bowler,
    overNumber,
    fullBattingXI,
    fullBowlingXI,
    inningsPhase,
    targetRuns,
    injectDismissalsOk,
  ]);

  const scrollToResults = useCallback(() => {
    const el = resultsRef.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }, []);

  const handleRun = () => {
    const dismissedBatters: PlayerSummary[] =
      injectState && injectWickets > 0
        ? dismissedSlots
            .slice(0, injectWickets)
            .filter((p): p is PlayerSummary => p != null)
        : [];

    const snap: SimulationFormSnapshot = {
      scope,
      overNumber,
      tournamentLabel,
      battingTeam: battingTeam.trim(),
      bowlingTeam: bowlingTeam.trim(),
      iterations,
      striker,
      nonStriker,
      bowler,
      inningsPhase,
      targetRuns,
      injectState,
      injectRuns,
      injectWickets,
      injectLegalBalls,
      dismissedBatters,
      battingXI,
      bowlingXI,
      contextRuns,
      contextWickets,
      contextLegalBalls,
    };
    runSimulation.mutate(snap, {
      onSuccess: (_data, variables) => {
        if (
          variables.scope === "full_match" &&
          variables.battingXI.every((p) => p) &&
          variables.bowlingXI.every((p) => p)
        ) {
          const batIds = variables.battingXI.map((p) => p!.id);
          const bowlIds = variables.bowlingXI.map((p) => p!.id);
          const lineup = simulationLineupToSearchParams(batIds, bowlIds);
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              if (lineup.has("bat")) next.set("bat", lineup.get("bat")!);
              else next.delete("bat");
              if (lineup.has("bowl")) next.set("bowl", lineup.get("bowl")!);
              else next.delete("bowl");
              return next;
            },
            { replace: true },
          );
        }
        requestAnimationFrame(scrollToResults);
      },
    });
  };

  const onBattingXISlot = useCallback((index: number, p: PlayerSummary | null) => {
    setBattingXI((prev) => {
      const next = [...prev];
      next[index] = p;
      return next;
    });
  }, []);

  const onBowlingXISlot = useCallback((index: number, p: PlayerSummary | null) => {
    setBowlingXI((prev) => {
      const next = [...prev];
      next[index] = p;
      return next;
    });
  }, []);

  const onDismissedSlotChange = useCallback(
    (index: number, p: PlayerSummary | null) => {
      setDismissedSlots((prev) => {
        const next = [...prev];
        next[index] = p;
        return next;
      });
    },
    [],
  );

  const targetIterations =
    runSimulation.isPending && runSimulation.variables
      ? runSimulation.variables.iterations
      : iterations;

  return (
    <div className="app-page page-stack text-text-primary">
      <header className="page-header">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-white/[0.08] text-primary">
            <FlaskConical size={20} aria-hidden />
          </span>
          <div>
            <h1 className="page-title">Simulation Hub</h1>
            <p className="page-subtitle">
              Explore win odds, player projections, and a two-innings scorecard preview
              for full-match runs. Share lineups via URL query{" "}
              <code className="text-xs text-text-muted">?bat=…&amp;bowl=…</code>.
            </p>
          </div>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(280px,22rem)_1fr] lg:items-start">
        <div className="lg:sticky lg:top-24 lg:self-start">
          <SimulationSetupPanel
            format={format}
            scope={scope}
            onScopeChange={setScope}
            overNumber={overNumber}
            onOverNumberChange={setOverNumber}
            tournamentLabel={tournamentLabel}
            onTournamentLabelChange={setTournamentLabel}
            battingTeam={battingTeam}
            bowlingTeam={bowlingTeam}
            onBattingTeamChange={setBattingTeam}
            onBowlingTeamChange={setBowlingTeam}
            iterations={iterations}
            onIterationsChange={setIterations}
            striker={striker}
            nonStriker={nonStriker}
            bowler={bowler}
            onStrikerChange={setStriker}
            onNonStrikerChange={setNonStriker}
            onBowlerChange={setBowler}
            inningsPhase={inningsPhase}
            onInningsPhaseChange={setInningsPhase}
            targetRuns={targetRuns}
            onTargetRunsChange={setTargetRuns}
            injectState={injectState}
            onInjectStateChange={setInjectState}
            injectRuns={injectRuns}
            injectWickets={injectWickets}
            injectLegalBalls={injectLegalBalls}
            onInjectRunsChange={setInjectRuns}
            onInjectWicketsChange={setInjectWickets}
            onInjectLegalBallsChange={setInjectLegalBalls}
            dismissedSlots={dismissedSlots}
            onDismissedSlotChange={onDismissedSlotChange}
            battingXI={battingXI}
            bowlingXI={bowlingXI}
            onBattingXISlot={onBattingXISlot}
            onBowlingXISlot={onBowlingXISlot}
            contextRuns={contextRuns}
            contextWickets={contextWickets}
            contextLegalBalls={contextLegalBalls}
            onContextRunsChange={setContextRuns}
            onContextWicketsChange={setContextWickets}
            onContextLegalBallsChange={setContextLegalBalls}
            canRun={canRun}
            isPending={runSimulation.isPending}
            onRun={handleRun}
          />
        </div>

        <div ref={resultsRef} className="min-w-0 space-y-4 scroll-mt-24">
          <SimulationLoadingPanel
            isPending={runSimulation.isPending}
            targetIterations={targetIterations}
          />

          {!runSimulation.isPending && runSimulation.isSuccess && runSimulation.data && (
            <SimulationResultsTabs data={runSimulation.data} />
          )}

          {!runSimulation.isPending &&
            !runSimulation.isSuccess &&
            !runSimulation.isError && (
              <div className="state-empty rounded-xl border border-dashed border-surface-elevated/80">
                <p className="text-sm text-text-secondary">
                  Results will appear here after you run a simulation. For a full
                  scorecard, choose <strong>Full match</strong> and complete both XIs.
                </p>
              </div>
            )}

          {runSimulation.isError && (
            <div className="state-error" role="alert">
              {runSimulation.error.message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
