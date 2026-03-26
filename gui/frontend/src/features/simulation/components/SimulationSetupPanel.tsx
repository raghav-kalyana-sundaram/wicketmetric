import PlayerAutocomplete from "@/components/PlayerAutocomplete";
import type { Format } from "@/api/formatConstants";
import type { PlayerSummary } from "@/api/types";
import type { SimulationScope } from "../types";
import TeamNameCombobox from "./TeamNameCombobox";

const SCOPE_OPTIONS: { value: SimulationScope; label: string; hint: string }[] =
  [
    {
      value: "specific_over",
      label: "Specific over",
      hint: "Batters, bowler, over number, and innings score context.",
    },
    {
      value: "full_match",
      label: "Full match",
      hint: "Two-innings preview: fill batting XI + bowling XI (real players) for a full scorecard.",
    },
    {
      value: "entire_tournament",
      label: "Entire tournament",
      hint: "Optional series label; squad-level mock output.",
    },
  ];

const ITER_MIN = 100;
const ITER_MAX = 10_000;
const ITER_STEP = 100;

function clampIterations(n: number): number {
  const r = Math.round(n / ITER_STEP) * ITER_STEP;
  return Math.max(ITER_MIN, Math.min(ITER_MAX, r));
}

export interface SimulationSetupPanelProps {
  format: Format;
  scope: SimulationScope;
  onScopeChange: (s: SimulationScope) => void;
  overNumber: number;
  onOverNumberChange: (n: number) => void;
  tournamentLabel: string;
  onTournamentLabelChange: (s: string) => void;
  battingTeam: string;
  bowlingTeam: string;
  onBattingTeamChange: (s: string) => void;
  onBowlingTeamChange: (s: string) => void;
  iterations: number;
  onIterationsChange: (n: number) => void;
  striker: PlayerSummary | null;
  nonStriker: PlayerSummary | null;
  bowler: PlayerSummary | null;
  onStrikerChange: (p: PlayerSummary | null) => void;
  onNonStrikerChange: (p: PlayerSummary | null) => void;
  onBowlerChange: (p: PlayerSummary | null) => void;
  inningsPhase: "first" | "chase";
  onInningsPhaseChange: (p: "first" | "chase") => void;
  targetRuns: number | null;
  onTargetRunsChange: (n: number | null) => void;
  injectState: boolean;
  onInjectStateChange: (v: boolean) => void;
  injectRuns: number;
  injectWickets: number;
  injectLegalBalls: number;
  onInjectRunsChange: (n: number) => void;
  onInjectWicketsChange: (n: number) => void;
  onInjectLegalBallsChange: (n: number) => void;
  dismissedSlots: (PlayerSummary | null)[];
  onDismissedSlotChange: (index: number, p: PlayerSummary | null) => void;
  battingXI: (PlayerSummary | null)[];
  bowlingXI: (PlayerSummary | null)[];
  onBattingXISlot: (index: number, p: PlayerSummary | null) => void;
  onBowlingXISlot: (index: number, p: PlayerSummary | null) => void;
  contextRuns: number;
  contextWickets: number;
  contextLegalBalls: number;
  onContextRunsChange: (n: number) => void;
  onContextWicketsChange: (n: number) => void;
  onContextLegalBallsChange: (n: number) => void;
  canRun: boolean;
  isPending: boolean;
  onRun: () => void;
}

export default function SimulationSetupPanel(props: SimulationSetupPanelProps) {
  const {
    format,
    scope,
    onScopeChange,
    overNumber,
    onOverNumberChange,
    tournamentLabel,
    onTournamentLabelChange,
    battingTeam,
    bowlingTeam,
    onBattingTeamChange,
    onBowlingTeamChange,
    iterations,
    onIterationsChange,
    striker,
    nonStriker,
    bowler,
    onStrikerChange,
    onNonStrikerChange,
    onBowlerChange,
    inningsPhase,
    onInningsPhaseChange,
    targetRuns,
    onTargetRunsChange,
    injectState,
    onInjectStateChange,
    injectRuns,
    injectWickets,
    injectLegalBalls,
    onInjectRunsChange,
    onInjectWicketsChange,
    onInjectLegalBallsChange,
    dismissedSlots,
    onDismissedSlotChange,
    battingXI,
    bowlingXI,
    onBattingXISlot,
    onBowlingXISlot,
    contextRuns,
    contextWickets,
    contextLegalBalls,
    onContextRunsChange,
    onContextWicketsChange,
    onContextLegalBallsChange,
    canRun,
    isPending,
    onRun,
  } = props;

  const showPlayers = scope === "specific_over";
  const showOverInput = scope === "specific_over";
  const showTournamentField = scope === "entire_tournament";
  const showFullMatch = scope === "full_match";
  const showSpecificContext = scope === "specific_over";

  const chip = (n: number) => (
    <button
      key={n}
      type="button"
      className="rounded-lg border border-surface-elevated bg-surface-elevated/40 px-2.5 py-1 text-xs font-medium text-text-secondary transition-colors hover:border-primary/40 hover:text-primary"
      onClick={() => onIterationsChange(clampIterations(n))}
    >
      {n >= 1000 ? `${n / 1000}k` : n}
    </button>
  );

  const xiExcludeBatting = (idx: number) =>
    battingXI
      .map((p, i) => (i !== idx && p ? p.id : null))
      .filter(Boolean) as string[];

  const xiExcludeBowling = (idx: number) =>
    bowlingXI
      .map((p, i) => (i !== idx && p ? p.id : null))
      .filter(Boolean) as string[];

  return (
    <div className="section-card section-card-body space-y-5">
      <div>
        <h2 className="section-title">Setup</h2>
        <p className="mt-1 text-sm text-text-secondary">
          Configure scope, sides, and run count. Full match builds a two-innings scorecard when
          both XIs are complete.
        </p>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-text-secondary">
          Simulation scope
        </legend>
        <div className="flex flex-col gap-2">
          {SCOPE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors ${
                scope === opt.value
                  ? "border-primary/70 bg-slate-100 ring-1 ring-primary/20 dark:bg-surface"
                  : "border-surface-elevated hover:border-surface-elevated/80"
              }`}
            >
              <input
                type="radio"
                name="sim-scope"
                value={opt.value}
                checked={scope === opt.value}
                onChange={() => onScopeChange(opt.value)}
                className="mt-1"
              />
              <span>
                <span className="block text-sm font-medium text-text-primary">
                  {opt.label}
                </span>
                <span className="text-xs text-text-muted">{opt.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {showOverInput && (
        <div>
          <label
            htmlFor="sim-over"
            className="block text-sm font-medium text-text-secondary"
          >
            Over number
          </label>
          <input
            id="sim-over"
            type="number"
            min={1}
            max={20}
            value={overNumber}
            onChange={(e) =>
              onOverNumberChange(
                clampOver(parseInt(e.target.value, 10) || 1),
              )
            }
            className="mt-1 block w-full max-w-[8rem] rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary tabular-nums"
          />
        </div>
      )}

      {showSpecificContext && (
        <div className="space-y-3 rounded-lg border border-surface-elevated/80 bg-surface-elevated/10 p-3">
          <p className="text-sm font-medium text-text-secondary">
            Innings state at start of this over
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className="text-xs text-text-muted" htmlFor="ctx-runs">
                Runs
              </label>
              <input
                id="ctx-runs"
                type="number"
                min={0}
                value={contextRuns}
                onChange={(e) => onContextRunsChange(Math.max(0, parseInt(e.target.value, 10) || 0))}
                className="mt-1 w-full rounded-md border border-surface-elevated bg-surface px-2 py-1.5 text-sm tabular-nums"
              />
            </div>
            <div>
              <label className="text-xs text-text-muted" htmlFor="ctx-wkts">
                Wickets
              </label>
              <input
                id="ctx-wkts"
                type="number"
                min={0}
                max={10}
                value={contextWickets}
                onChange={(e) =>
                  onContextWicketsChange(Math.min(10, Math.max(0, parseInt(e.target.value, 10) || 0)))
                }
                className="mt-1 w-full rounded-md border border-surface-elevated bg-surface px-2 py-1.5 text-sm tabular-nums"
              />
            </div>
            <div>
              <label className="text-xs text-text-muted" htmlFor="ctx-balls">
                Legal balls done
              </label>
              <input
                id="ctx-balls"
                type="number"
                min={0}
                max={119}
                value={contextLegalBalls}
                onChange={(e) =>
                  onContextLegalBallsChange(
                    Math.min(119, Math.max(0, parseInt(e.target.value, 10) || 0)),
                  )
                }
                className="mt-1 w-full rounded-md border border-surface-elevated bg-surface px-2 py-1.5 text-sm tabular-nums"
              />
            </div>
          </div>
        </div>
      )}

      {showTournamentField && (
        <div>
          <label
            htmlFor="sim-tournament"
            className="block text-sm font-medium text-text-secondary"
          >
            Series / tournament (optional)
          </label>
          <input
            id="sim-tournament"
            type="text"
            value={tournamentLabel}
            onChange={(e) => onTournamentLabelChange(e.target.value)}
            placeholder="e.g. ICC Men’s T20 World Cup"
            className="mt-1 block w-full rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted"
          />
        </div>
      )}

      <TeamNameCombobox
        format={format}
        id="sim-batting-team"
        label="Batting team (first innings)"
        value={battingTeam}
        onChange={onBattingTeamChange}
      />
      <TeamNameCombobox
        format={format}
        id="sim-bowling-team"
        label="Bowling team"
        value={bowlingTeam}
        onChange={onBowlingTeamChange}
      />

      {showFullMatch && (
        <div className="space-y-4 border-t border-surface-elevated/70 pt-4">
          <p className="text-sm font-medium text-text-secondary">Match structure</p>
          <div className="flex flex-col gap-2">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name="inn-phase"
                checked={inningsPhase === "first"}
                onChange={() => onInningsPhaseChange("first")}
              />
              First innings only (no chase)
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name="inn-phase"
                checked={inningsPhase === "chase"}
                onChange={() => onInningsPhaseChange("chase")}
              />
              Two innings — second team chases a target
            </label>
          </div>
          {inningsPhase === "chase" && (
            <div>
              <label className="text-sm text-text-secondary" htmlFor="target-runs">
                Target runs
              </label>
              <input
                id="target-runs"
                type="number"
                min={1}
                max={300}
                value={targetRuns ?? ""}
                placeholder="e.g. 165"
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  onTargetRunsChange(Number.isFinite(v) ? v : null);
                }}
                className="mt-1 block w-full max-w-[10rem] rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm tabular-nums"
              />
            </div>
          )}

          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={injectState}
              onChange={(e) => onInjectStateChange(e.target.checked)}
            />
            Inject first-innings state (score, overs, crease)
          </label>

          {injectState && (
            <div className="space-y-3 rounded-lg border border-surface-elevated/60 p-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div>
                  <label className="text-xs text-text-muted">Runs</label>
                  <input
                    type="number"
                    min={0}
                    value={injectRuns}
                    onChange={(e) => onInjectRunsChange(Math.max(0, parseInt(e.target.value, 10) || 0))}
                    className="mt-1 w-full rounded-md border border-surface-elevated bg-surface px-2 py-1.5 text-sm tabular-nums"
                  />
                </div>
                <div>
                  <label className="text-xs text-text-muted">Wickets</label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={injectWickets}
                    onChange={(e) =>
                      onInjectWicketsChange(Math.min(10, Math.max(0, parseInt(e.target.value, 10) || 0)))
                    }
                    className="mt-1 w-full rounded-md border border-surface-elevated bg-surface px-2 py-1.5 text-sm tabular-nums"
                  />
                </div>
                <div>
                  <label className="text-xs text-text-muted">Legal balls done</label>
                  <input
                    type="number"
                    min={0}
                    max={119}
                    value={injectLegalBalls}
                    onChange={(e) =>
                      onInjectLegalBallsChange(
                        Math.min(119, Math.max(0, parseInt(e.target.value, 10) || 0)),
                      )
                    }
                    className="mt-1 w-full rounded-md border border-surface-elevated bg-surface px-2 py-1.5 text-sm tabular-nums"
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div>
                  <span className="text-xs text-text-muted">Striker</span>
                  <PlayerAutocomplete
                    value={striker}
                    onSelect={onStrikerChange}
                    onClear={() => onStrikerChange(null)}
                    role="bat"
                    size="sm"
                    placeholder="Striker…"
                    ariaLabel="Inject striker"
                  />
                </div>
                <div>
                  <span className="text-xs text-text-muted">Non-striker</span>
                  <PlayerAutocomplete
                    value={nonStriker}
                    onSelect={onNonStrikerChange}
                    onClear={() => onNonStrikerChange(null)}
                    role="bat"
                    size="sm"
                    placeholder="Non-striker…"
                    ariaLabel="Inject non-striker"
                  />
                </div>
              </div>
              {injectWickets > 0 && (
                <div className="space-y-2">
                  <p className="text-xs text-text-muted">
                    Dismissed batters (order: 1st out → {injectWickets}th out)
                  </p>
                  {dismissedSlots.slice(0, injectWickets).map((slot, i) => (
                    <div key={i}>
                      <span className="text-[10px] text-text-muted">Wicket {i + 1}</span>
                      <PlayerAutocomplete
                        value={slot}
                        onSelect={(p) => onDismissedSlotChange(i, p)}
                        onClear={() => onDismissedSlotChange(i, null)}
                        role="bat"
                        size="sm"
                        placeholder={`Out batter ${i + 1}…`}
                        ariaLabel={`Dismissed batter ${i + 1}`}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div>
            <p className="text-sm font-medium text-text-secondary mb-1">Batting XI (11)</p>
            <p className="mb-2 text-xs text-text-muted">
              Auto-fills from the most recent scorecard in this format where this team batted
              (batting order). You can edit slots anytime.
            </p>
            <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
              {battingXI.map((slot, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-6 text-xs text-text-muted tabular-nums">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <PlayerAutocomplete
                      value={slot}
                      onSelect={(p) => onBattingXISlot(i, p)}
                      onClear={() => onBattingXISlot(i, null)}
                      role="bat"
                      size="sm"
                      placeholder={`Batter ${i + 1}…`}
                      ariaLabel={`Batting position ${i + 1}`}
                      excludeIds={xiExcludeBatting(i)}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="text-sm font-medium text-text-secondary mb-1">Bowling XI (11)</p>
            <p className="mb-2 text-xs text-text-muted">
              Auto-fills from who bowled for this team in their latest match, then pads with
              teammates who batted if fewer than eleven bowlers appear.
            </p>
            <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
              {bowlingXI.map((slot, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-6 text-xs text-text-muted tabular-nums">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <PlayerAutocomplete
                      value={slot}
                      onSelect={(p) => onBowlingXISlot(i, p)}
                      onClear={() => onBowlingXISlot(i, null)}
                      role="bowl"
                      size="sm"
                      placeholder={`Bowler ${i + 1}…`}
                      ariaLabel={`Bowling slot ${i + 1}`}
                      excludeIds={xiExcludeBowling(i)}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {showPlayers && (
        <div className="space-y-3 border-t border-surface-elevated/70 pt-4">
          <p className="text-sm font-medium text-text-secondary">
            Players for this over
          </p>
          <div>
            <span className="block text-xs text-text-muted mb-1">Striker</span>
            <PlayerAutocomplete
              value={striker}
              onSelect={(p) => onStrikerChange(p)}
              onClear={() => onStrikerChange(null)}
              role="bat"
              size="sm"
              placeholder="Search batter…"
              ariaLabel="Striker"
              excludeIds={nonStriker ? [nonStriker.id] : undefined}
            />
          </div>
          <div>
            <span className="block text-xs text-text-muted mb-1">Non-striker</span>
            <PlayerAutocomplete
              value={nonStriker}
              onSelect={(p) => onNonStrikerChange(p)}
              onClear={() => onNonStrikerChange(null)}
              role="bat"
              size="sm"
              placeholder="Search batter…"
              ariaLabel="Non-striker"
              excludeIds={striker ? [striker.id] : undefined}
            />
          </div>
          <div>
            <span className="block text-xs text-text-muted mb-1">Bowler</span>
            <PlayerAutocomplete
              value={bowler}
              onSelect={(p) => onBowlerChange(p)}
              onClear={() => onBowlerChange(null)}
              role="bowl"
              size="sm"
              placeholder="Search bowler…"
              ariaLabel="Bowler"
            />
          </div>
        </div>
      )}

      <div className="border-t border-surface-elevated/70 pt-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-text-secondary">
            Iterations
          </span>
          <span className="text-xs text-text-muted">(step {ITER_STEP})</span>
          <div className="flex w-full gap-2 sm:ml-auto sm:w-auto">
            {chip(100)}
            {chip(1000)}
            {chip(10000)}
          </div>
        </div>
        <input
          type="range"
          min={ITER_MIN}
          max={ITER_MAX}
          step={ITER_STEP}
          value={iterations}
          onChange={(e) =>
            onIterationsChange(clampIterations(Number(e.target.value)))
          }
          className="w-full accent-primary"
        />
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-text-secondary shrink-0" htmlFor="sim-iter-num">
            Exact value
          </label>
          <input
            id="sim-iter-num"
            type="number"
            min={ITER_MIN}
            max={ITER_MAX}
            step={ITER_STEP}
            value={iterations}
            onChange={(e) =>
              onIterationsChange(clampIterations(Number(e.target.value) || ITER_MIN))
            }
            onBlur={() => onIterationsChange(clampIterations(iterations))}
            className="w-32 rounded-md border border-surface-elevated bg-surface px-3 py-2 text-sm text-text-primary tabular-nums"
          />
        </div>
      </div>

      <button
        type="button"
        className="btn-primary w-full"
        disabled={!canRun || isPending}
        onClick={onRun}
      >
        {isPending ? "Running…" : "Run simulation"}
      </button>
    </div>
  );
}

function clampOver(n: number): number {
  if (Number.isNaN(n)) return 1;
  return Math.max(1, Math.min(20, n));
}
